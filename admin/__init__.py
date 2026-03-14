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


@admin_bp.post("/schedule/swap-ooc")
def admin_schedule_swap_ooc():
    """
    Swap OOC opponents so two specified teams play each other instead.

    POST /admin/schedule/swap-ooc
    Body: {
        "team_a_id": 101,
        "team_b_id": 202,
        "season_week": 3,
        "season_subweek": "a"
    }

    If team A plays X and team B plays Y in that slot, after the swap:
    - team A plays team B
    - team X plays team Y
    """
    guard = _require_admin()
    if guard:
        return guard

    if not _writes_allowed():
        return jsonify(ok=False, error="write_disabled"), 403

    body = request.get_json(force=True, silent=True) or {}
    team_a_id = body.get("team_a_id")
    team_b_id = body.get("team_b_id")
    season_week = body.get("season_week")
    season_subweek = body.get("season_subweek")

    missing = []
    if not team_a_id:
        missing.append("team_a_id")
    if not team_b_id:
        missing.append("team_b_id")
    if season_week is None:
        missing.append("season_week")
    if not season_subweek:
        missing.append("season_subweek")
    if missing:
        return jsonify(ok=False, error="missing_params",
                       message="Missing: %s" % ", ".join(missing)), 400

    team_a_id = int(team_a_id)
    team_b_id = int(team_b_id)
    season_week = int(season_week)

    if team_a_id == team_b_id:
        return jsonify(ok=False, error="same_team",
                       message="team_a_id and team_b_id must be different"), 400

    try:
        from db import get_engine
        from sqlalchemy import text as sa_text

        engine = get_engine()

        with engine.begin() as conn:
            # Find both teams' games in this (week, subweek)
            rows = conn.execute(
                sa_text("""
                    SELECT id, home_team, away_team, is_conference
                    FROM gamelist
                    WHERE season_week = :week
                      AND season_subweek = :subweek
                      AND (home_team IN (:ta, :tb) OR away_team IN (:ta, :tb))
                """),
                {"week": season_week, "subweek": season_subweek,
                 "ta": team_a_id, "tb": team_b_id},
            ).fetchall()

            # Find game for team A and game for team B
            game_a = None
            game_b = None
            for r in rows:
                row = dict(r._mapping)
                if row["home_team"] == team_a_id or row["away_team"] == team_a_id:
                    game_a = row
                if row["home_team"] == team_b_id or row["away_team"] == team_b_id:
                    game_b = row

            if not game_a:
                return jsonify(ok=False, error="no_game",
                               message="Team %d has no game in week %d subweek %s"
                               % (team_a_id, season_week, season_subweek)), 404
            if not game_b:
                return jsonify(ok=False, error="no_game",
                               message="Team %d has no game in week %d subweek %s"
                               % (team_b_id, season_week, season_subweek)), 404

            # If they already play each other, nothing to do
            if game_a["id"] == game_b["id"]:
                return jsonify(ok=True, message="Teams already play each other in this slot",
                               swapped=False)

            # Both must be OOC
            if game_a.get("is_conference"):
                return jsonify(ok=False, error="conference_game",
                               message="Team %d's game is a conference game — cannot swap"
                               % team_a_id), 400
            if game_b.get("is_conference"):
                return jsonify(ok=False, error="conference_game",
                               message="Team %d's game is a conference game — cannot swap"
                               % team_b_id), 400

            # Check neither game has results
            played = conn.execute(
                sa_text("""
                    SELECT game_id FROM game_results
                    WHERE game_id IN (:ga, :gb)
                """),
                {"ga": game_a["id"], "gb": game_b["id"]},
            ).fetchall()
            if played:
                return jsonify(ok=False, error="already_played",
                               message="Cannot swap — one or both games already have results"), 400

            # Determine opponents
            opp_a = (game_a["away_team"] if game_a["home_team"] == team_a_id
                     else game_a["home_team"])
            opp_b = (game_b["away_team"] if game_b["home_team"] == team_b_id
                     else game_b["home_team"])

            # Swap: game_a becomes team_a vs team_b, game_b becomes opp_a vs opp_b
            # Preserve home/away: team_a keeps home/away status from game_a,
            # opp_a keeps home/away status from game_a's opponent slot
            if game_a["home_team"] == team_a_id:
                new_a_home, new_a_away = team_a_id, team_b_id
            else:
                new_a_home, new_a_away = team_b_id, team_a_id

            if game_b["home_team"] == team_b_id:
                # opp_b was away in game_b, so opp_a takes the away slot
                new_b_home, new_b_away = opp_b, opp_a
            else:
                new_b_home, new_b_away = opp_a, opp_b

            conn.execute(
                sa_text("UPDATE gamelist SET home_team = :h, away_team = :a WHERE id = :id"),
                {"h": new_a_home, "a": new_a_away, "id": game_a["id"]},
            )
            conn.execute(
                sa_text("UPDATE gamelist SET home_team = :h, away_team = :a WHERE id = :id"),
                {"h": new_b_home, "a": new_b_away, "id": game_b["id"]},
            )

        return jsonify(
            ok=True,
            swapped=True,
            game_1={"game_id": game_a["id"], "home": new_a_home, "away": new_a_away},
            game_2={"game_id": game_b["id"], "home": new_b_home, "away": new_b_away},
            week=season_week,
            subweek=season_subweek,
        )

    except Exception as e:
        logging.exception("admin_schedule_swap_ooc failed")
        return jsonify(ok=False, error="swap_failed", message=str(e)), 500


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


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------


@admin_bp.get("/analytics/league-years")
def admin_analytics_league_years():
    guard = _require_admin()
    if guard:
        return guard
    try:
        from db import get_engine
        from services.analytics import get_league_years
        engine = get_engine()
        with engine.connect() as conn:
            data = get_league_years(conn)
        return jsonify(ok=True, league_years=data)
    except Exception as e:
        logging.exception("analytics_league_years_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/teams")
def admin_analytics_teams():
    guard = _require_admin()
    if guard:
        return guard
    try:
        from db import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT id, team_abbrev, team_level FROM teams ORDER BY team_level, team_abbrev"
            )).mappings().all()
        teams = [{"id": int(r["id"]), "team_abbrev": r["team_abbrev"], "team_level": int(r["team_level"])} for r in rows]
        return jsonify(ok=True, teams=teams)
    except Exception as e:
        logging.exception("analytics_teams_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/batting-correlations")
def admin_batting_correlations():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    min_ab = request.args.get("min_ab", 50, type=int)
    drill_attr = request.args.get("drill_attr")
    drill_stat = request.args.get("drill_stat")
    try:
        from db import get_engine
        from services.analytics import batting_correlations
        engine = get_engine()
        with engine.connect() as conn:
            result = batting_correlations(
                conn, league_year_id, league_level, min_ab,
                drill_attr, drill_stat,
            )
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("batting_correlations_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/pitching-correlations")
def admin_pitching_correlations():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    min_ipo = request.args.get("min_ipo", 60, type=int)
    drill_attr = request.args.get("drill_attr")
    drill_stat = request.args.get("drill_stat")
    try:
        from db import get_engine
        from services.analytics import pitching_correlations
        engine = get_engine()
        with engine.connect() as conn:
            result = pitching_correlations(
                conn, league_year_id, league_level, min_ipo,
                drill_attr, drill_stat,
            )
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("pitching_correlations_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/defensive-analysis")
def admin_defensive_analysis():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    position_code = request.args.get("position_code")
    min_innings = request.args.get("min_innings", 50, type=int)
    drill_attr = request.args.get("drill_attr")
    drill_stat = request.args.get("drill_stat")
    try:
        from db import get_engine
        from services.analytics import defensive_correlations
        engine = get_engine()
        with engine.connect() as conn:
            result = defensive_correlations(
                conn, league_year_id, league_level,
                position_code, min_innings,
                drill_attr, drill_stat,
            )
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("defensive_analysis_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/war-leaderboard")
def admin_war_leaderboard():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    replacement_pct = request.args.get("replacement_pct", 0.80, type=float)
    min_ab = request.args.get("min_ab", 50, type=int)
    min_ipo = request.args.get("min_ipo", 60, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)
    weights = {
        "batting": request.args.get("w_batting", 1.0, type=float),
        "baserunning": request.args.get("w_baserunning", 1.0, type=float),
        "fielding": request.args.get("w_fielding", 1.0, type=float),
        "pitching": request.args.get("w_pitching", 1.0, type=float),
    }
    try:
        from db import get_engine
        from services.analytics import war_leaderboard
        engine = get_engine()
        with engine.connect() as conn:
            result = war_leaderboard(
                conn, league_year_id, league_level,
                replacement_pct, min_ab, min_ipo, weights,
                page, page_size,
            )
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("war_leaderboard_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/multi-regression")
def admin_multi_regression():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    target_stat = request.args.get("target_stat")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    if not league_year_id or not league_level or not target_stat:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import multi_regression
        engine = get_engine()
        with engine.connect() as conn:
            result = multi_regression(conn, category, league_year_id, league_level, target_stat, min_threshold)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("multi_regression_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/sensitivity")
def admin_sensitivity():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    target_stat = request.args.get("target_stat")
    attribute = request.args.get("attribute")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    num_buckets = request.args.get("num_buckets", 10, type=int)
    if not league_year_id or not league_level or not target_stat or not attribute:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import sensitivity_curves
        engine = get_engine()
        with engine.connect() as conn:
            result = sensitivity_curves(conn, category, league_year_id, league_level, target_stat, attribute, min_threshold, num_buckets)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("sensitivity_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/isolation")
def admin_isolation():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    target_stat = request.args.get("target_stat")
    test_attr = request.args.get("test_attr")
    control_attrs = request.args.getlist("control_attr")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    if not league_year_id or not league_level or not target_stat or not test_attr:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import attribute_isolation
        engine = get_engine()
        with engine.connect() as conn:
            result = attribute_isolation(conn, category, league_year_id, league_level, target_stat, test_attr, control_attrs, min_threshold)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("isolation_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/xstats")
def admin_xstats():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import xstats_analysis
        engine = get_engine()
        with engine.connect() as conn:
            result = xstats_analysis(conn, category, league_year_id, league_level, min_threshold)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("xstats_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/interactions")
def admin_interactions():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    target_stat = request.args.get("target_stat")
    attr_a = request.args.get("attr_a")
    attr_b = request.args.get("attr_b")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    if not all([league_year_id, league_level, target_stat, attr_a, attr_b]):
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import interaction_analysis
        engine = get_engine()
        with engine.connect() as conn:
            result = interaction_analysis(conn, category, league_year_id, league_level, target_stat, attr_a, attr_b, min_threshold)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("interactions_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/stat-dashboard")
def admin_stat_dashboard():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    category = request.args.get("category", "batting")
    target_stat = request.args.get("target_stat")
    min_threshold = request.args.get("min_threshold", 50, type=int)
    if not league_year_id or not league_level or not target_stat:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import stat_tuning_dashboard
        engine = get_engine()
        with engine.connect() as conn:
            result = stat_tuning_dashboard(conn, category, league_year_id, league_level, target_stat, min_threshold)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stat_dashboard_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/archetypes")
def admin_archetypes():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    min_ab = request.args.get("min_ab", 50, type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import archetype_validation
        engine = get_engine()
        with engine.connect() as conn:
            result = archetype_validation(conn, league_year_id, league_level, min_ab)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("archetypes_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/pitch-types")
def admin_pitch_types():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    min_ipo = request.args.get("min_ipo", 60, type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import pitch_type_analysis
        engine = get_engine()
        with engine.connect() as conn:
            result = pitch_type_analysis(conn, league_year_id, league_level, min_ipo)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("pitch_types_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/defensive-positions")
def admin_defensive_positions():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    min_innings = request.args.get("min_innings", 50, type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params"), 400
    try:
        from db import get_engine
        from services.analytics import defensive_position_importance
        engine = get_engine()
        with engine.connect() as conn:
            result = defensive_position_importance(conn, league_year_id, league_level, min_innings)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("defensive_positions_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/db-storage")
def admin_db_storage():
    guard = _require_admin()
    if guard:
        return guard
    try:
        from db import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(sa_text("""
                SELECT
                    table_name,
                    table_rows,
                    ROUND(data_length / 1024 / 1024, 2) AS data_mb,
                    ROUND(index_length / 1024 / 1024, 2) AS index_mb,
                    ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
                    ROUND(data_free / 1024 / 1024, 2) AS free_mb
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                ORDER BY (data_length + index_length) DESC
            """)).mappings().all()
            tables = [dict(r) for r in rows]
            total_data = sum(float(t["data_mb"] or 0) for t in tables)
            total_index = sum(float(t["index_mb"] or 0) for t in tables)
            total_size = sum(float(t["total_mb"] or 0) for t in tables)
            total_rows = sum(int(t["table_rows"] or 0) for t in tables)
        return jsonify(ok=True, tables=tables, summary={
            "table_count": len(tables),
            "total_rows": total_rows,
            "total_data_mb": round(total_data, 2),
            "total_index_mb": round(total_index, 2),
            "total_mb": round(total_size, 2),
        })
    except Exception as e:
        logging.exception("db_storage_failed")
        return jsonify(ok=False, error="db_storage_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Stamina Reports
# ---------------------------------------------------------------------------

@admin_bp.get("/analytics/stamina-overview")
def admin_stamina_overview():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(ok=False, error="missing_params"), 400
    league_level = request.args.get("league_level", type=int)
    try:
        from db import get_engine
        from services.analytics import stamina_league_overview
        engine = get_engine()
        with engine.connect() as conn:
            result = stamina_league_overview(conn, league_year_id, league_level)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stamina_overview_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/stamina-team")
def admin_stamina_team():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    team_id = request.args.get("team_id", type=int)
    if not league_year_id or not team_id:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and team_id are required"), 400
    try:
        from db import get_engine
        from services.analytics import stamina_team_detail
        engine = get_engine()
        with engine.connect() as conn:
            result = stamina_team_detail(conn, league_year_id, team_id)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stamina_team_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/stamina-availability")
def admin_stamina_availability():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(ok=False, error="missing_params"), 400
    league_level = request.args.get("league_level", type=int)
    try:
        from db import get_engine
        from services.analytics import stamina_availability_report
        engine = get_engine()
        with engine.connect() as conn:
            result = stamina_availability_report(conn, league_year_id, league_level)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stamina_availability_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/stamina-consumption")
def admin_stamina_consumption():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(ok=False, error="missing_params"), 400
    league_level = request.args.get("league_level", type=int)
    try:
        from db import get_engine
        from services.analytics import stamina_consumption_analysis
        engine = get_engine()
        with engine.connect() as conn:
            result = stamina_consumption_analysis(conn, league_year_id, league_level)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stamina_consumption_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/stamina-flow")
def admin_stamina_flow():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(ok=False, error="missing_params"), 400
    team_id = request.args.get("team_id", type=int)
    try:
        from db import get_engine
        from services.analytics import stamina_flow_history
        engine = get_engine()
        with engine.connect() as conn:
            result = stamina_flow_history(conn, league_year_id, team_id)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("stamina_flow_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/contact-breakdown")
def admin_contact_breakdown():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    min_ab = request.args.get("min_ab", 30, type=int)
    try:
        from db import get_engine
        from services.analytics import contact_type_breakdown
        engine = get_engine()
        with engine.connect() as conn:
            result = contact_type_breakdown(conn, league_year_id, league_level, min_ab)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("contact_breakdown_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


@admin_bp.get("/analytics/hr-depth")
def admin_hr_depth():
    guard = _require_admin()
    if guard:
        return guard
    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    if not league_year_id or not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level are required"), 400
    game_type = request.args.get("game_type", "regular")
    try:
        from db import get_engine
        from services.analytics import hr_depth_analysis
        engine = get_engine()
        with engine.connect() as conn:
            result = hr_depth_analysis(conn, league_year_id, league_level, game_type)
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("hr_depth_analysis_failed")
        return jsonify(ok=False, error="analytics_error", message=str(e)), 500


# ── Batting Lab ──────────────────────────────────────────────────────

@admin_bp.get("/batting-lab/runs")
def admin_batting_lab_runs():
    guard = _require_admin()
    if guard:
        return guard
    try:
        from db import get_engine
        from services.batting_lab import list_runs
        engine = get_engine()
        with engine.connect() as conn:
            runs = list_runs(conn)
        return jsonify(ok=True, runs=runs)
    except Exception as e:
        logging.exception("batting_lab_list_failed")
        return jsonify(ok=False, error="batting_lab_error", message=str(e)), 500


@admin_bp.get("/batting-lab/results/<int:run_id>")
def admin_batting_lab_results(run_id: int):
    guard = _require_admin()
    if guard:
        return guard
    try:
        from db import get_engine
        from services.batting_lab import get_run_results
        engine = get_engine()
        with engine.connect() as conn:
            result = get_run_results(conn, run_id)
        if result is None:
            return jsonify(ok=False, error="not_found"), 404
        return jsonify(ok=True, **result)
    except Exception as e:
        logging.exception("batting_lab_results_failed")
        return jsonify(ok=False, error="batting_lab_error", message=str(e)), 500


@admin_bp.post("/batting-lab/run")
def admin_batting_lab_run():
    guard = _require_admin()
    if guard:
        return guard

    data = request.get_json(force=True, silent=True) or {}
    league_level = data.get("league_level")
    games_per_tier = data.get("games_per_tier", 50)
    label = data.get("label", "")

    if not league_level:
        return jsonify(ok=False, error="missing_params",
                       message="league_level required"), 400

    games_per_tier = max(1, min(500, int(games_per_tier)))

    try:
        from db import get_engine
        from services.batting_lab import execute_batting_lab_run
        engine = get_engine()

        # Create the run record
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO batting_lab_runs (label, league_level, games_per_scenario, scenario_type) "
                "VALUES (:label, :ll, :gpt, 'tier_sweep')"
            ), {"label": label, "ll": int(league_level), "gpt": games_per_tier})
            row = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            run_id = int(row)

        # Execute synchronously (engine calls are fast for small batches)
        result = execute_batting_lab_run(run_id, int(league_level), games_per_tier)

        return jsonify(ok=True, run_id=run_id, message=f"Completed {len(result.get('tiers', {}))} tiers")

    except Exception as e:
        logging.exception("batting_lab_run_failed")
        return jsonify(ok=False, error="batting_lab_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Listed Positions — manual fill
# ---------------------------------------------------------------------------

@admin_bp.post("/fill-listed-positions")
def admin_fill_listed_positions():
    """Derive and upsert listed positions for every team with active rosters."""
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.listed_position import refresh_all_teams, _resolve_league_year_id

        engine = get_engine()
        with engine.begin() as conn:
            league_year_id = _resolve_league_year_id(conn)
            total = refresh_all_teams(conn, league_year_id)

        return jsonify(ok=True, total=total,
                       message=f"Listed positions filled for {total} players")

    except Exception as e:
        logging.exception("admin_fill_listed_positions failed")
        return jsonify(ok=False, error="fill_failed", message=str(e)), 500


# ---------------------------------------------------------------------------
# Default Gameplan Generation
# ---------------------------------------------------------------------------

@admin_bp.post("/generate-default-gameplans")
def admin_generate_default_gameplans():
    """Generate default gameplans (defense, rotation, bullpen) for all teams at a level."""
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    team_level = body.get("team_level")
    league_year_id = body.get("league_year_id")
    overwrite = bool(body.get("overwrite", False))

    if team_level is None or league_year_id is None:
        return jsonify(ok=False, error="missing_params",
                       message="team_level and league_year_id are required"), 400

    try:
        from db import get_engine
        from services.default_gameplan import generate_default_gameplans

        engine = get_engine()
        with engine.begin() as conn:
            result = generate_default_gameplans(
                conn,
                team_level=int(team_level),
                league_year_id=int(league_year_id),
                overwrite=overwrite,
            )

        return jsonify(ok=True, **result)

    except Exception as e:
        logging.exception("admin_generate_default_gameplans failed")
        return jsonify(ok=False, error="generation_failed", message=str(e)), 500


# ---------------------------------------------------------------------------
# Weight Calibration
# ---------------------------------------------------------------------------

@admin_bp.post("/calibration/run")
def admin_calibration_run():
    """Run OLS regression calibration to derive position weights from game data."""
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    league_year_id = body.get("league_year_id")
    league_level = body.get("league_level")

    if league_year_id is None or league_level is None:
        return jsonify(ok=False, error="missing_params",
                       message="league_year_id and league_level required"), 400

    config = body.get("config", {})
    config["name"] = body.get("name", config.get("name"))

    try:
        from db import get_engine
        from services.weight_calibration import run_calibration

        engine = get_engine()
        with engine.begin() as conn:
            result = run_calibration(
                conn, int(league_year_id), int(league_level), config
            )

        # Clean up positions for JSON (strip large lists)
        positions_summary = {}
        for rt, cal in result.get("positions", {}).items():
            positions_summary[rt] = {
                "position_code": cal.get("position_code"),
                "n": cal.get("n", 0),
                "offense_r2": cal.get("offense_r2"),
                "defense_r2": cal.get("defense_r2"),
                "r2": cal.get("r2"),
                "skipped": cal.get("skipped", False),
                "warnings": cal.get("warnings", []),
                "weights": cal.get("weights", {}),
            }

        return jsonify(ok=True, profile_id=result["profile_id"],
                       name=result["name"], positions=positions_summary)

    except Exception as e:
        logging.exception("admin_calibration_run failed")
        return jsonify(ok=False, error="calibration_failed", message=str(e)), 500


@admin_bp.get("/calibration/profiles")
def admin_calibration_profiles():
    """List all weight profiles."""
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.weight_calibration import get_profiles

        engine = get_engine()
        with engine.connect() as conn:
            profiles = get_profiles(conn)

        # Convert datetimes to strings
        for p in profiles:
            if p.get("created_at"):
                p["created_at"] = str(p["created_at"])

        return jsonify(ok=True, profiles=profiles)

    except Exception as e:
        logging.exception("admin_calibration_profiles failed")
        return jsonify(ok=False, error="load_failed", message=str(e)), 500


@admin_bp.get("/calibration/profiles/<int:profile_id>")
def admin_calibration_profile_detail(profile_id):
    """Get a single profile with full weight breakdown."""
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.weight_calibration import get_profile_detail

        engine = get_engine()
        with engine.connect() as conn:
            detail = get_profile_detail(conn, profile_id)

        if not detail:
            return jsonify(ok=False, error="not_found"), 404

        if detail.get("created_at"):
            detail["created_at"] = str(detail["created_at"])

        return jsonify(ok=True, profile=detail)

    except Exception as e:
        logging.exception("admin_calibration_profile_detail failed")
        return jsonify(ok=False, error="load_failed", message=str(e)), 500


@admin_bp.get("/calibration/compare")
def admin_calibration_compare():
    """Compare two profiles side-by-side."""
    guard = _require_admin()
    if guard:
        return guard

    a = request.args.get("a", type=int)
    b = request.args.get("b", type=int)
    if not a or not b:
        return jsonify(ok=False, error="missing_params",
                       message="a and b profile IDs required"), 400

    try:
        from db import get_engine
        from services.weight_calibration import compare_profiles

        engine = get_engine()
        with engine.connect() as conn:
            result = compare_profiles(conn, a, b)

        if "error" in result:
            return jsonify(ok=False, error=result["error"]), 404

        return jsonify(ok=True, **result)

    except Exception as e:
        logging.exception("admin_calibration_compare failed")
        return jsonify(ok=False, error="compare_failed", message=str(e)), 500


@admin_bp.post("/calibration/activate/<int:profile_id>")
def admin_calibration_activate(profile_id):
    """Activate a weight profile — writes to rating_overall_weights."""
    guard = _require_admin()
    if guard:
        return guard

    try:
        from db import get_engine
        from services.weight_calibration import activate_profile

        engine = get_engine()
        with engine.begin() as conn:
            result = activate_profile(conn, profile_id)

        return jsonify(ok=True, **result)

    except Exception as e:
        logging.exception("admin_calibration_activate failed")
        return jsonify(ok=False, error="activate_failed", message=str(e)), 500


@admin_bp.post("/calibration/profiles")
def admin_calibration_create_manual():
    """Create a manual weight profile."""
    guard = _require_admin()
    if guard:
        return guard

    body = request.get_json(force=True, silent=True) or {}
    name = body.get("name")
    description = body.get("description", "")
    weights = body.get("weights")

    if not name or not weights:
        return jsonify(ok=False, error="missing_params",
                       message="name and weights required"), 400

    try:
        from db import get_engine
        from services.weight_calibration import create_manual_profile

        engine = get_engine()
        with engine.begin() as conn:
            profile_id = create_manual_profile(conn, name, description, weights)

        return jsonify(ok=True, profile_id=profile_id)

    except Exception as e:
        logging.exception("admin_calibration_create_manual failed")
        return jsonify(ok=False, error="create_failed", message=str(e)), 500
