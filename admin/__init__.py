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
    static_url_path="/static/admin",
)


@admin_bp.after_request
def admin_no_cache(response):
    """Prevent browser from caching admin HTML/JS so deploys take effect immediately."""
    if response.content_type and (
        "text/html" in response.content_type
        or "javascript" in response.content_type
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
    """Check if destructive writes are enabled (env var OR session toggle)."""
    if os.getenv("ADMIN_ALLOW_WRITE", "false").lower() == "true":
        return True
    return session.get("admin_write_mode") is True

def _require_admin():
    if session.get("admin") is True:
        return None
    return jsonify(error="unauthorized"), 401

@admin_bp.get("/")
def admin_index():
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
       write_mode=_writes_allowed(),
    )

@admin_bp.post("/write-mode")
def admin_toggle_write_mode():
    """Toggle write mode on/off for the current admin session."""
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(force=True, silent=True) or {}
    enabled = bool(body.get("enabled", False))
    session["admin_write_mode"] = enabled
    return jsonify(ok=True, write_mode=enabled)

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


@admin_bp.put("/rating-config/levels")
def admin_update_level_config():
    """
    Set mean / std per level + ptype (applied to ALL attributes at that level).

    PUT /admin/rating-config/levels
    Body: { "levels": [
        { "level_id": 9, "ptype": "Pitcher", "mean_value": 50.0, "std_dev": 15.0 },
        { "level_id": 9, "ptype": "Position", "mean_value": 50.0, "std_dev": 15.0 },
        ...
    ]}
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    levels = body.get("levels")
    if not levels or not isinstance(levels, list):
        return jsonify(ok=False, error="missing_levels",
                       message="Body must contain 'levels' list"), 400

    try:
        from db import get_engine
        from services.rating_config import bulk_set_config

        engine = get_engine()
        total = 0
        with engine.connect() as conn:
            for entry in levels:
                level_id = entry.get("level_id")
                ptype = entry.get("ptype")
                mean_val = entry.get("mean_value")
                std_val = entry.get("std_dev")
                if level_id is None or not ptype or mean_val is None or std_val is None:
                    continue
                total += bulk_set_config(conn, int(level_id), ptype, float(mean_val), float(std_val))
            conn.commit()

        return jsonify(ok=True, updated=total)

    except Exception as e:
        logging.exception("admin_update_level_config failed")
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


# ---------------------------------------------------------------------------
# Growth curves management
# ---------------------------------------------------------------------------

@admin_bp.get("/growth-curves")
def admin_get_growth_curves():
    """
    Return all growth_curves rows grouped by grade.

    GET /admin/growth-curves
    GET /admin/growth-curves?grade=A

    Response: { ok: true, grades: ["A+","A",...], curves: { "A+": [{age, prog_min, prog_mode, prog_max}, ...], ... } }
    """
    guard = _require_admin()
    if guard:
        return guard

    grade_filter = request.args.get("grade")

    try:
        from db import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            query = "SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves"
            params = {}
            if grade_filter:
                query += " WHERE grade = :grade"
                params["grade"] = grade_filter
            query += " ORDER BY grade, age"
            rows = conn.execute(text(query), params).mappings().all()

        curves = {}
        for r in rows:
            g = r["grade"]
            if g not in curves:
                curves[g] = []
            curves[g].append({
                "age": int(r["age"]),
                "prog_min": float(r["prog_min"]),
                "prog_mode": float(r["prog_mode"]),
                "prog_max": float(r["prog_max"]),
            })

        return jsonify(ok=True, grades=sorted(curves.keys()), curves=curves)

    except Exception as e:
        logging.exception("admin_get_growth_curves failed")
        return jsonify(ok=False, error="read_failed", message=str(e)), 500


@admin_bp.put("/growth-curves")
def admin_update_growth_curves():
    """
    Bulk update growth_curves rows.

    PUT /admin/growth-curves
    Body: { "updates": [ { "grade": "A+", "age": 20, "prog_min": 1.0, "prog_mode": 3.0, "prog_max": 5.0 }, ... ] }
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

        engine = get_engine()
        count = 0
        with engine.connect() as conn:
            for entry in updates:
                grade = entry.get("grade")
                age = entry.get("age")
                prog_min = entry.get("prog_min")
                prog_mode = entry.get("prog_mode")
                prog_max = entry.get("prog_max")
                if grade is None or age is None:
                    continue
                conn.execute(
                    text("""
                        UPDATE growth_curves
                        SET prog_min = :prog_min, prog_mode = :prog_mode, prog_max = :prog_max
                        WHERE grade = :grade AND age = :age
                    """),
                    {"grade": grade, "age": int(age),
                     "prog_min": float(prog_min), "prog_mode": float(prog_mode), "prog_max": float(prog_max)},
                )
                count += 1
            conn.commit()

        return jsonify(ok=True, updated=count)

    except Exception as e:
        logging.exception("admin_update_growth_curves failed")
        return jsonify(ok=False, error="update_failed", message=str(e)), 500


@admin_bp.post("/migrations/fix-amateur-contracts")
def admin_fix_amateur_contracts():
    """
    Fix HS/College contract years and current_year for class year derivation.

    POST /admin/migrations/fix-amateur-contracts

    Moves 18yo USA players from College to HS, sets correct years/current_year
    based on age, and rebuilds contractDetails + contractTeamShare.
    """
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from migrations.fix_amateur_contract_years import migrate_amateur_contract_years

        engine = get_engine()
        result = migrate_amateur_contract_years(engine)
        return jsonify(ok=True, **result)

    except Exception as e:
        logging.exception("admin_fix_amateur_contracts failed")
        return jsonify(ok=False, error="migration_failed", message=str(e)), 500


# ---------------------------------------------------------------------------
# Schedule generator endpoints
# ---------------------------------------------------------------------------

@admin_bp.get("/schedule/report")
def admin_schedule_report():
    """
    Summary of existing schedules across all levels and seasons.

    GET /admin/schedule/report
    """
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.schedule_generator import _get_tables, schedule_report

        engine = get_engine()
        tables = _get_tables(engine)
        with engine.connect() as conn:
            report = schedule_report(conn, tables)

        return jsonify(ok=True, **report)

    except Exception as e:
        logging.exception("admin_schedule_report failed")
        return jsonify(ok=False, error="report_failed", message=str(e)), 500


@admin_bp.get("/schedule/validate")
def admin_schedule_validate():
    """
    Validate prerequisites for schedule generation.

    GET /admin/schedule/validate?league_year=2027&league_level=9
    """
    guard = _require_admin()
    if guard:
        return guard

    league_year = request.args.get("league_year", type=int)
    league_level = request.args.get("league_level", type=int)

    if not league_year or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year and league_level are required"), 400

    try:
        from db import get_engine
        from services.schedule_generator import (
            _get_tables, _resolve_season_id, validate_schedule_generation,
        )

        engine = get_engine()
        tables = _get_tables(engine)
        with engine.connect() as conn:
            season_id = _resolve_season_id(conn, tables, league_year)
            result = validate_schedule_generation(conn, tables, season_id, league_level)

        return jsonify(ok=True, **result)

    except ValueError as e:
        return jsonify(ok=False, error="validation_error", message=str(e)), 400
    except Exception as e:
        logging.exception("admin_schedule_validate failed")
        return jsonify(ok=False, error="validate_failed", message=str(e)), 500


@admin_bp.post("/schedule/generate")
def admin_schedule_generate():
    """
    Generate a schedule for the given level and year.

    POST /admin/schedule/generate
    Body: { "league_year": 2027, "league_level": 9, "start_week": 1, "seed": null, "clear_existing": false }
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    league_year = body.get("league_year")
    league_level = body.get("league_level")
    start_week = body.get("start_week", 1)
    seed = body.get("seed")
    clear_existing = bool(body.get("clear_existing", False))

    if not league_year or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year and league_level are required"), 400

    try:
        from db import get_engine
        from services.schedule_generator import (
            LEVEL_MLB, LEVEL_COLLEGE, MINOR_LEVELS,
            generate_mlb_schedule,
            generate_college_schedule,
            generate_minor_league_schedule,
        )

        engine = get_engine()
        league_level = int(league_level)

        if league_level == LEVEL_MLB:
            result = generate_mlb_schedule(
                engine, int(league_year), seed=seed, clear_existing=clear_existing,
            )
        elif league_level == LEVEL_COLLEGE:
            result = generate_college_schedule(
                engine, int(league_year), start_week=int(start_week),
                seed=seed, clear_existing=clear_existing,
            )
        elif league_level in MINOR_LEVELS:
            result = generate_minor_league_schedule(
                engine, int(league_year), level=league_level,
                start_week=int(start_week), seed=seed,
                clear_existing=clear_existing,
            )
        else:
            return jsonify(ok=False, error="invalid_level",
                           message="Level %d is not supported" % league_level), 400

        return jsonify(ok=True, **result)

    except ValueError as e:
        return jsonify(ok=False, error="generation_error", message=str(e)), 400
    except RuntimeError as e:
        from services.schedule_generator import ScheduleTimeout
        if isinstance(e, ScheduleTimeout):
            return jsonify(ok=False, error="generation_timeout", message=str(e)), 504
        return jsonify(ok=False, error="generation_failed", message=str(e)), 500
    except Exception as e:
        logging.exception("admin_schedule_generate failed")
        return jsonify(ok=False, error="schedule_generate_failed", message=str(e)), 500


@admin_bp.post("/schedule/clear")
def admin_schedule_clear():
    """
    Clear an existing schedule for a given level and year.

    POST /admin/schedule/clear
    Body: { "league_year": 2027, "league_level": 9 }
    """
    guard = _require_admin()
    if guard:
        return guard

    if not _writes_allowed():
        return jsonify(ok=False, error="write_disabled"), 403

    body = request.get_json(force=True, silent=True) or {}
    league_year = body.get("league_year")
    league_level = body.get("league_level")

    if not league_year or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year and league_level are required"), 400

    try:
        from db import get_engine
        from services.schedule_generator import (
            _get_tables, _resolve_season_id, _clear_existing_schedule,
        )

        engine = get_engine()
        tables = _get_tables(engine)
        with engine.begin() as conn:
            season_id = _resolve_season_id(conn, tables, int(league_year))
            deleted = _clear_existing_schedule(conn, tables, season_id, int(league_level))

        return jsonify(ok=True, deleted=deleted)

    except ValueError as e:
        return jsonify(ok=False, error="clear_error", message=str(e)), 400
    except Exception as e:
        logging.exception("admin_schedule_clear failed")
        return jsonify(ok=False, error="clear_failed", message=str(e)), 500


@admin_bp.post("/schedule/add-series")
def admin_schedule_add_series():
    """
    Insert a single series into the schedule.

    POST /admin/schedule/add-series
    Body: { "league_year": 2027, "league_level": 9, "home_team_id": 1, "away_team_id": 5, "week": 53, "games": 4 }
    """
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    league_year = body.get("league_year")
    league_level = body.get("league_level")
    home_team_id = body.get("home_team_id")
    away_team_id = body.get("away_team_id")
    week = body.get("week")
    games = body.get("games", 3)

    missing = []
    if not league_year: missing.append("league_year")
    if not league_level: missing.append("league_level")
    if not home_team_id: missing.append("home_team_id")
    if not away_team_id: missing.append("away_team_id")
    if not week: missing.append("week")
    if missing:
        return jsonify(ok=False, error="missing_params",
                       message="Missing: %s" % ", ".join(missing)), 400

    try:
        from db import get_engine
        from services.schedule_generator import add_series

        engine = get_engine()
        result = add_series(
            engine, int(league_year), int(league_level),
            int(home_team_id), int(away_team_id), int(week), int(games),
        )

        return jsonify(ok=True, **result)

    except ValueError as e:
        return jsonify(ok=False, error="add_series_error", message=str(e)), 400
    except Exception as e:
        logging.exception("admin_schedule_add_series failed")
        return jsonify(ok=False, error="add_series_failed", message=str(e)), 500


# ── Schedule Viewer endpoints ────────────────────────────────────────

@admin_bp.get("/schedule/viewer")
def admin_schedule_viewer():
    """
    View schedule data with filtering and pagination.

    GET /admin/schedule/viewer?season_year=2027&league_level=9&team_id=1&week_start=1&week_end=10&page=1&page_size=200
    """
    guard = _require_admin()
    if guard:
        return guard

    season_year = request.args.get("season_year", type=int)
    if not season_year:
        return jsonify(ok=False, error="missing_params",
                       message="season_year is required"), 400

    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    week_start = request.args.get("week_start", type=int)
    week_end = request.args.get("week_end", type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 200, type=int), 1000)

    try:
        from db import get_engine
        from services.schedule_generator import _get_tables, schedule_viewer

        engine = get_engine()
        tables = _get_tables(engine)
        with engine.connect() as conn:
            result = schedule_viewer(
                conn, tables,
                season_year=season_year,
                league_level=league_level,
                team_id=team_id,
                week_start=week_start,
                week_end=week_end,
                page=page,
                page_size=page_size,
            )

        return jsonify(ok=True, **result)

    except ValueError as e:
        return jsonify(ok=False, error="viewer_error", message=str(e)), 400
    except Exception as e:
        logging.exception("admin_schedule_viewer failed")
        return jsonify(ok=False, error="viewer_failed", message=str(e)), 500


@admin_bp.get("/schedule/quality")
def admin_schedule_quality():
    """
    Schedule quality metrics (games per team, home/away balance).

    GET /admin/schedule/quality?season_year=2027&league_level=9
    """
    guard = _require_admin()
    if guard:
        return guard

    season_year = request.args.get("season_year", type=int)
    league_level = request.args.get("league_level", type=int)

    if not season_year or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="season_year and league_level are required"), 400

    try:
        from db import get_engine
        from services.schedule_generator import _get_tables, schedule_quality_metrics

        engine = get_engine()
        tables = _get_tables(engine)
        with engine.connect() as conn:
            result = schedule_quality_metrics(conn, tables, season_year, league_level)

        return jsonify(ok=True, **result)

    except ValueError as e:
        return jsonify(ok=False, error="quality_error", message=str(e)), 400
    except Exception as e:
        logging.exception("admin_schedule_quality failed")
        return jsonify(ok=False, error="quality_failed", message=str(e)), 500


@admin_bp.put("/schedule/game/<int:game_id>")
def admin_update_game(game_id: int):
    """
    Update a single game in the schedule.

    PUT /admin/schedule/game/123
    Body: { "home_team": 5, "away_team": 10, "season_week": 3, "season_subweek": "b" }
    Only provided fields are updated.
    """
    guard = _require_admin()
    if guard:
        return guard

    if not _writes_allowed():
        return jsonify(ok=False, error="write_disabled"), 403

    body = request.get_json(force=True, silent=True) or {}
    allowed_fields = {"home_team", "away_team", "season_week", "season_subweek", "random_seed"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}

    if not updates:
        return jsonify(ok=False, error="no_updates",
                       message="No valid fields to update"), 400

    try:
        from db import get_engine
        from sqlalchemy import text as sa_text

        engine = get_engine()
        set_clause = ", ".join("%s = :%s" % (k, k) for k in updates)
        updates["game_id"] = game_id

        with engine.begin() as conn:
            result = conn.execute(
                sa_text("UPDATE gamelist SET %s WHERE id = :game_id" % set_clause),
                updates,
            )
            if result.rowcount == 0:
                return jsonify(ok=False, error="not_found",
                               message="Game %d not found" % game_id), 404

        return jsonify(ok=True, updated=game_id)

    except Exception as e:
        logging.exception("admin_update_game failed")
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
