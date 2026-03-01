# admin/__init__.py
import os, re, logging, time
from flask import Blueprint, request, jsonify, session, render_template
from sqlalchemy import text
from flask import current_app

# This module expects your app.py to create an `engine` in create_app()
# We'll get the engine via current_app in handlers.
from flask import current_app as cap

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates/admin",
    static_folder="static/admin",
)

# Allowed statement patterns
SQL_READ_ALLOWED  = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|EXPLAIN)\b", re.I)
SQL_WRITE_ALLOWED = re.compile(r"^\s*(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|TRUNCATE|RENAME|REPLACE)\b", re.I)
SQL_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.I)

# Preset queries (you can move to JSON later)
PRESET_QUERIES = {
    "tables": {
        "label": "List tables",
        "sql": "SHOW TABLES",
        "mode": "read",
    },
    "sizes": {
        "label": "Table sizes",
        "sql": """
            SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
        """,
        "mode": "read",
    },
    "recent_users": {
        "label": "Recent users",
        "sql": "SELECT id, name, email, created_at FROM users ORDER BY created_at DESC",
        "mode": "read",
    },
}

def _mask(sql: str) -> str:
    s = re.sub(r"password\s*=\s*'[^']*'", "password='***'", sql, flags=re.I)
    return s[:1000] + ("..." if len(s) > 1000 else "")

def _writes_allowed() -> bool:
    # Global toggle via env; you can add a time-box mechanism if desired
    return os.getenv("ADMIN_ALLOW_WRITE", "false").lower() == "true"

def _require_admin():
    if session.get("admin") is True:
        return None
    return jsonify(error="unauthorized"), 401

@admin_bp.get("/")
def admin_index():
    # Serves templates/admin/index.html
    return render_template("index.html")

@admin_bp.post("/login")
def admin_login():
    want = (request.json or {}).get("password", "")
    # If ADMIN_PASSWORD is empty: allow login with no password (convenient for local)
    needed = os.getenv("ADMIN_PASSWORD", "")
    if needed and want != needed:
        return jsonify(ok=False, error="bad_password"), 401
    session["admin"] = True
    return jsonify(ok=True)

@admin_bp.post("/logout")
def admin_logout():
    session.clear()
    return jsonify(ok=True)

@admin_bp.get("/me")
def admin_me():
    from flask import current_app
    return jsonify(
       admin=session.get("admin"),
       secure=current_app.config.get("SESSION_COOKIE_SECURE"),
       samesite=current_app.config.get("SESSION_COOKIE_SAMESITE"),
    )

@admin_bp.get("/presets")
def admin_presets():
    guard = _require_admin()
    if guard: return guard
    presets = [{"key": k, "label": v["label"], "mode": v["mode"]} for k, v in PRESET_QUERIES.items()]
    return jsonify(presets=presets)

@admin_bp.get("/run_preset")
def admin_run_preset():
    guard = _require_admin()
    if guard: return guard

    key = request.args.get("key")
    p = PRESET_QUERIES.get(key)
    if not p:
        return jsonify(error="preset_not_found"), 404
    return _run_sql_internal(p["sql"], p["mode"], limit=int(os.getenv("ADMIN_MAX_ROWS", "500")), dry_run=False)

@admin_bp.post("/run_sql")
def admin_run_sql():
    guard = _require_admin()
    if guard: return guard

    body = request.get_json(force=True, silent=True) or {}
    sql = (body.get("sql") or "").strip()
    mode = (body.get("mode") or "read").lower()
    limit = max(1, min(int(body.get("limit", 100)), int(os.getenv("ADMIN_MAX_ROWS", "500"))))
    dry_run = bool(body.get("dry_run", True))
    return _run_sql_internal(sql, mode, limit, dry_run)


@admin_bp.post("/clear-caches")
def admin_clear_caches():
    """
    Clear all in-memory caches to force fresh data from the database.

    Use this after making direct database changes to configuration tables
    (level_catch_rates, level_rules, injury_types, etc.) to ensure the
    API returns updated values.

    Response:
    {
        "ok": true,
        "cleared": {
            "game_payload": {"core_tables": true, "level_config": true, ...},
            "rosters": {"tables": true, "player_col_cats": false}
        }
    }

    Example:
        POST /admin/clear-caches
    """
    guard = _require_admin()
    if guard:
        return guard

    try:
        from services.game_payload import clear_game_payload_caches
        from rosters import clear_rosters_caches

        cleared = {
            "game_payload": clear_game_payload_caches(),
            "rosters": clear_rosters_caches(),
        }

        logging.getLogger("app").info(
            "admin_clear_caches",
            extra={"cleared": cleared}
        )

        return jsonify(ok=True, cleared=cleared)

    except Exception as e:
        logging.exception("admin_clear_caches failed")
        return jsonify(ok=False, error="clear_caches_failed", message=str(e)), 500

# ---------------------------------------------------------------------------
# Rating scale config management
# ---------------------------------------------------------------------------

@admin_bp.post("/rating-config/seed")
def admin_seed_rating_config():
    """
    Compute mean/stddev for every attribute at every level from current
    player data and UPSERT into rating_scale_config.

    POST /admin/rating-config/seed

    Levels with no players (e.g. 1-3 before import) are skipped.
    """
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.rating_config import seed_rating_config

        engine = get_engine()
        with engine.connect() as conn:
            result = seed_rating_config(conn)
            conn.commit()

        return jsonify(ok=True, **result)

    except Exception as e:
        logging.exception("admin_seed_rating_config failed")
        return jsonify(ok=False, error="seed_failed", message=str(e)), 500


@admin_bp.get("/rating-config")
def admin_get_rating_config():
    """
    Return current rating_scale_config contents.

    GET /admin/rating-config
    GET /admin/rating-config?level=9
    GET /admin/rating-config?ptype=Pitcher

    Response groups by ptype then level_id, each with attribute_key -> {mean, std}.
    """
    guard = _require_admin()
    if guard:
        return guard

    level_id = request.args.get("level", type=int)
    ptype = request.args.get("ptype")

    try:
        from db import get_engine
        from services.rating_config import get_rating_config

        engine = get_engine()
        with engine.connect() as conn:
            config = get_rating_config(conn, level_id=level_id, ptype=ptype)

        # Convert int keys to strings for JSON
        out = {}
        for pt, levels in config.items():
            out[pt] = {str(k): v for k, v in levels.items()}
        return jsonify(ok=True, levels=out)

    except Exception as e:
        logging.exception("admin_get_rating_config failed")
        return jsonify(ok=False, error="read_failed", message=str(e)), 500


@admin_bp.put("/rating-config")
def admin_update_rating_config():
    """
    Update mean_value / std_dev for specific config rows.

    PUT /admin/rating-config
    Body: { "updates": [ { "level_id": 9, "ptype": "Pitcher", "attribute_key": "power_base", "mean_value": 50.0, "std_dev": 15.0 }, ... ] }
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    updates = body.get("updates")
    if not updates or not isinstance(updates, list):
        return jsonify(ok=False, error="missing_updates", message="Body must contain 'updates' list"), 400

    try:
        from db import get_engine
        from services.rating_config import update_config_rows

        engine = get_engine()
        with engine.connect() as conn:
            count = update_config_rows(conn, updates)
            conn.commit()

        return jsonify(ok=True, updated=count)

    except Exception as e:
        logging.exception("admin_update_rating_config failed")
        return jsonify(ok=False, error="update_failed", message=str(e)), 500


@admin_bp.put("/rating-config/bulk-set")
def admin_bulk_set_rating_config():
    """
    Set the SAME mean / std for ALL attributes at a given level + ptype.

    PUT /admin/rating-config/bulk-set
    Body: { "level_id": 9, "ptype": "Pitcher", "mean_value": 50.0, "std_dev": 15.0 }
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    level_id = body.get("level_id")
    ptype = body.get("ptype")
    mean_val = body.get("mean_value")
    std_val = body.get("std_dev")

    if level_id is None or not ptype or mean_val is None or std_val is None:
        return jsonify(ok=False, error="missing_fields",
                       message="Required: level_id, ptype, mean_value, std_dev"), 400

    try:
        from db import get_engine
        from services.rating_config import bulk_set_config

        engine = get_engine()
        with engine.connect() as conn:
            count = bulk_set_config(conn, int(level_id), ptype, float(mean_val), float(std_val))
            conn.commit()

        return jsonify(ok=True, updated=count)

    except Exception as e:
        logging.exception("admin_bulk_set_rating_config failed")
        return jsonify(ok=False, error="update_failed", message=str(e)), 500


@admin_bp.get("/rating-config/overall-weights")
def admin_get_overall_weights():
    """
    Return current overall rating weights.

    GET /admin/rating-config/overall-weights

    Response: { ok: true, weights: { "pitcher_overall": { attr: weight }, ... } }
    """
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.rating_config import get_overall_weights

        engine = get_engine()
        with engine.connect() as conn:
            weights = get_overall_weights(conn)

        return jsonify(ok=True, weights=weights)

    except Exception as e:
        logging.exception("admin_get_overall_weights failed")
        return jsonify(ok=False, error="read_failed", message=str(e)), 500


@admin_bp.put("/rating-config/overall-weights")
def admin_update_overall_weights():
    """
    Update overall rating weights.

    PUT /admin/rating-config/overall-weights
    Body: { "weights": { "pitcher_overall": { "attr": weight, ... }, ... } }
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    weights = body.get("weights")
    if not weights or not isinstance(weights, dict):
        return jsonify(ok=False, error="missing_weights", message="Body must contain 'weights' dict"), 400

    try:
        from db import get_engine
        from services.rating_config import update_overall_weight

        engine = get_engine()
        count = 0
        with engine.connect() as conn:
            for rating_type, attr_map in weights.items():
                if not isinstance(attr_map, dict):
                    continue
                for attr_key, weight in attr_map.items():
                    update_overall_weight(conn, rating_type, attr_key, float(weight))
                    count += 1
            conn.commit()

        return jsonify(ok=True, updated=count)

    except Exception as e:
        logging.exception("admin_update_overall_weights failed")
        return jsonify(ok=False, error="update_failed", message=str(e)), 500


def _run_sql_internal(sql: str, mode: str, limit: int, dry_run: bool):
    if not sql:
        return jsonify(error="missing_sql"), 400

    # Guardrails
    if mode == "read":
        if not SQL_READ_ALLOWED.match(sql):
            return jsonify(error="read_only_violation",
                           message="Only SELECT/SHOW/DESCRIBE/EXPLAIN allowed in read mode."), 400
    elif mode == "write":
        if not _writes_allowed():
            return jsonify(error="write_disabled"), 403
        if not (SQL_READ_ALLOWED.match(sql) or SQL_WRITE_ALLOWED.match(sql)):
            return jsonify(error="write_violation", message="Statement type not allowed."), 400
    else:
        return jsonify(error="bad_mode"), 400

    logging.getLogger("app").info(
        "admin_sql",
        extra={"sql_preview": _mask(sql), "mode": mode, "dry_run": dry_run}
    )

    # Enforce LIMIT for SELECTs if missing
    if SQL_SELECT_ONLY.match(sql) and not re.search(r"\bLIMIT\s+\d+\b", sql, flags=re.I):
        sql = f"{sql.rstrip(';')} LIMIT {limit}"

    try:
        engine = getattr(current_app, "engine", None)
        if engine is None:
            return jsonify(error="db_not_configured"), 503

        with engine.connect() as conn:
            if dry_run and SQL_WRITE_ALLOWED.match(sql):
                # EXPLAIN DML when possible
                try:
                    plan = [dict(r._mapping) for r in conn.execute(text(f"EXPLAIN {sql}"))]
                    return jsonify(ok=True, dry_run=True, explain=plan)
                except Exception as e:
                    return jsonify(ok=False, dry_run=True, message=f"EXPLAIN failed: {str(e)}"), 400

            result = conn.execute(text(sql))
            if result.returns_rows:
                rows = [dict(r._mapping) for r in result]
                return jsonify(ok=True, count=len(rows), rows=rows[:limit])
            else:
                return jsonify(ok=True, rowcount=result.rowcount)
    except Exception as e:
        logging.exception("admin_sql_failed")
        return jsonify(ok=False, error="admin_sql_failed", message=str(e)), 500
