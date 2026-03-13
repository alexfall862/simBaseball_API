# games/__init__.py

import threading
import gzip
from flask import Blueprint, jsonify, current_app, request, redirect, Response
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.game_payload import (
    build_game_payload,
    build_week_payloads,
    build_synthetic_matchups,
    build_synthetic_matchups_with_progress,
)
from services.timestamp import (
    set_run_games,
    set_subweek_completed,
    update_timestamp,
    advance_week,
    reset_week_games,
)
from services.task_store import get_task_store, TaskStatus

games_bp = Blueprint("games", __name__)


@games_bp.get("/games/<int:game_id>/payload")
def get_game_payload(game_id: int):
    """
    Return the full engine-facing payload for a single game in gamelist.

    Example:
      GET /api/v1/games/123/payload
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            payload = build_game_payload(conn, game_id)
        return jsonify(payload), 200
    except SQLAlchemyError as e:
        current_app.logger.exception("get_game_payload: db error")
        return jsonify(
            error="database_error",
            message=str(e),
        ), 500
    except Exception as e:
        current_app.logger.exception("get_game_payload: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e),
        ), 500


@games_bp.get("/games/simulate-week/<int:league_year_id>/<int:season_week>")
def simulate_week_get(league_year_id: int, season_week: int):
    """
    GET version of simulate-week for testing - returns payloads WITHOUT sending to engine.

    Query parameters:
      - league_level (optional): Filter by league level (e.g., 9 for MLB)

    Example:
      GET /api/v1/games/simulate-week/2026/1
      GET /api/v1/games/simulate-week/2026/1?league_level=9
    """
    league_level = request.args.get("league_level", type=int)

    engine = get_engine()

    try:
        with engine.connect() as conn:
            result = build_week_payloads(
                conn=conn,
                league_year_id=league_year_id,
                season_week=season_week,
                league_level=league_level,
                simulate=False,  # Don't send to engine, just return payloads
            )

        current_app.logger.info(
            f"Successfully built {result['total_games']} game payloads for "
            f"league_year={league_year_id}, week={season_week} (GET endpoint)"
        )

        return jsonify(result), 200

    except ValueError as e:
        current_app.logger.warning(f"simulate_week_get validation error: {e}")
        return jsonify(
            error="validation_error",
            message=str(e)
        ), 404

    except SQLAlchemyError as e:
        current_app.logger.exception("simulate_week_get: database error")
        return jsonify(
            error="database_error",
            message=str(e)
        ), 500

    except Exception as e:
        current_app.logger.exception("simulate_week_get: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


@games_bp.post("/games/simulate-week")
def simulate_week():
    """
    Build game payloads for all games in a season week.

    Processes games sequentially by subweek (a → b → c → d) to support
    state updates between subweeks (rotation, stamina, injuries).

    Updates the Timestamp state and broadcasts to WebSocket clients:
    - Sets RunGames=true when starting
    - Marks each subweek as complete (GamesARan, GamesBRan, etc.)
    - Sets RunGames=false when finished

    Request body:
    {
        "league_year_id": 2026,
        "season_week": 1,
        "league_level": 9  // optional (e.g., 9 for MLB)
    }

    Response:
    {
        "league_year_id": 2026,
        "season_week": 1,
        "league_level": 9,
        "total_games": 47,
        "subweeks": {
            "a": [game_payload, ...],
            "b": [game_payload, ...],
            "c": [game_payload, ...],
            "d": [game_payload, ...]
        }
    }

    Example:
      POST /api/v1/games/simulate-week
      Content-Type: application/json

      {"league_year_id": 2026, "season_week": 1}
    """
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return jsonify(
            error="invalid_request",
            message="Request body must be JSON"
        ), 400

    league_year_id = body.get("league_year_id")
    season_week = body.get("season_week")
    league_level = body.get("league_level")

    # Validate required fields
    if league_year_id is None:
        return jsonify(
            error="missing_field",
            message="league_year_id is required"
        ), 400

    if season_week is None:
        return jsonify(
            error="missing_field",
            message="season_week is required"
        ), 400

    # Validate types
    try:
        league_year_id = int(league_year_id)
        season_week = int(season_week)
        if league_level is not None:
            league_level = int(league_level)
    except (TypeError, ValueError) as e:
        return jsonify(
            error="invalid_type",
            message=f"league_year_id and season_week must be integers: {e}"
        ), 400

    engine = get_engine()

    try:
        # Update timestamp: simulation starting
        update_timestamp({
            "week": season_week,
            "run_games": True,
        })
        current_app.logger.info(f"Simulation starting for week {season_week}")

        with engine.connect() as conn:
            result = build_week_payloads(
                conn=conn,
                league_year_id=league_year_id,
                season_week=season_week,
                league_level=league_level,
            )

        # Mark each subweek that had games as completed
        subweeks = result.get("subweeks", {})
        for subweek_key in ["a", "b", "c", "d"]:
            if subweeks.get(subweek_key):
                set_subweek_completed(subweek_key, broadcast=False)

        # Update timestamp: simulation complete
        set_run_games(False, broadcast=True)

        current_app.logger.info(
            f"Successfully built {result['total_games']} game payloads for "
            f"league_year={league_year_id}, week={season_week}"
        )

        return jsonify(result), 200

    except ValueError as e:
        # No games found or validation error - reset run_games flag
        set_run_games(False, broadcast=True)
        current_app.logger.warning(f"simulate_week validation error: {e}")
        return jsonify(
            error="validation_error",
            message=str(e)
        ), 404

    except SQLAlchemyError as e:
        # Database error - reset run_games flag
        set_run_games(False, broadcast=True)
        current_app.logger.exception("simulate_week: database error")
        return jsonify(
            error="database_error",
            message=str(e)
        ), 500

    except Exception as e:
        # Unexpected error - reset run_games flag
        set_run_games(False, broadcast=True)
        current_app.logger.exception("simulate_week: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


@games_bp.post("/games/advance-week")
def advance_week_endpoint():
    """
    Advance to the next week and reset all game completion flags.

    This endpoint should be called after all games for the current week
    have been simulated and results processed.

    Updates the Timestamp state:
    - Increments Week by 1
    - Resets GamesARan, GamesBRan, GamesCRan, GamesDRan to false
    - Broadcasts updated state to all WebSocket clients

    Request body (optional):
    {
        "season_id": 1  // Optional: update season_id if changing seasons
    }

    Response:
    {
        "status": "ok",
        "message": "Advanced to week X"
    }

    Example:
      POST /api/v1/games/advance-week
    """
    try:
        # Check for optional season_id update
        payload = request.get_json(silent=True) or {}
        season_id = payload.get("season_id")

        if season_id is not None:
            # Update season_id along with advancing week
            update_timestamp({"season_id": int(season_id)}, broadcast=False)

        # Advance the week (increments week, resets game flags, broadcasts)
        success = advance_week(broadcast=True)

        if success:
            current_app.logger.info("Successfully advanced to next week")
            return jsonify(
                status="ok",
                message="Advanced to next week"
            ), 200
        else:
            current_app.logger.error("Failed to advance week")
            return jsonify(
                error="update_failed",
                message="Failed to advance week"
            ), 500

    except Exception as e:
        current_app.logger.exception("advance_week: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


@games_bp.post("/games/reset-week")
def reset_week_endpoint():
    """
    Reset all game completion flags for the current week without advancing.

    Useful for re-running a week's simulation.

    Updates the Timestamp state:
    - Resets GamesARan, GamesBRan, GamesCRan, GamesDRan to false
    - Broadcasts updated state to all WebSocket clients

    Response:
    {
        "status": "ok",
        "message": "Week games reset"
    }

    Example:
      POST /api/v1/games/reset-week
    """
    try:
        success = reset_week_games(broadcast=True)

        if success:
            current_app.logger.info("Successfully reset week games")
            return jsonify(
                status="ok",
                message="Week games reset"
            ), 200
        else:
            current_app.logger.error("Failed to reset week games")
            return jsonify(
                error="update_failed",
                message="Failed to reset week games"
            ), 500

    except Exception as e:
        current_app.logger.exception("reset_week: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


@games_bp.post("/games/wipe-season")
def wipe_season():
    """
    Wipe all simulation results, stats, and player state for a season.

    Deletes game_results, player stats, fatigue, injuries, and position usage
    for the given league_year_id. Optionally filter by league_level for
    game_results only. Resets timestamp to week 1.

    Does NOT delete the schedule (gamelist) — only simulation output.

    Request body:
    {
        "league_year_id": 1,
        "league_level": 9   // optional — filters game_results only
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return jsonify(error="invalid_request",
                       message="Request body must be JSON"), 400

    league_year_id = body.get("league_year_id")
    league_level = body.get("league_level")

    if league_year_id is None:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    try:
        league_year_id = int(league_year_id)
        if league_level is not None:
            league_level = int(league_level)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    engine = get_engine()

    try:
        from sqlalchemy import text as sa_text, MetaData, Table, select

        with engine.begin() as conn:
            deleted = {}

            # Resolve season_id from league_year_id
            md = MetaData()
            league_years = Table("league_years", md, autoload_with=engine)
            seasons = Table("seasons", md, autoload_with=engine)

            ly_row = conn.execute(
                select(league_years.c.league_year)
                .where(league_years.c.id == league_year_id)
            ).first()
            if not ly_row:
                return jsonify(error="not_found",
                               message=f"league_year_id {league_year_id} not found"), 404

            year = int(ly_row[0])
            season_rows = conn.execute(
                select(seasons.c.id).where(seasons.c.year == year)
            ).all()
            season_ids = [int(r[0]) for r in season_rows]

            # 1. game_results (uses season FK, optionally filtered by level)
            gr_sql = "DELETE FROM game_results WHERE season IN :season_ids"
            params = {"season_ids": tuple(season_ids) if season_ids else (0,)}
            if league_level is not None:
                gr_sql += " AND league_level = :league_level"
                params["league_level"] = league_level
            r = conn.execute(sa_text(gr_sql), params)
            deleted["game_results"] = r.rowcount

            # 2-4. Per-game line tables (keyed by league_year_id)
            for tbl_name in ("game_batting_lines", "game_pitching_lines",
                             "game_substitutions"):
                r = conn.execute(sa_text(
                    f"DELETE FROM {tbl_name} WHERE league_year_id = :lyid"
                ), {"lyid": league_year_id})
                deleted[tbl_name] = r.rowcount

            # 5-7. Player stat tables (keyed by league_year_id)
            for tbl_name in ("player_batting_stats", "player_pitching_stats",
                             "player_fielding_stats"):
                r = conn.execute(sa_text(
                    f"DELETE FROM {tbl_name} WHERE league_year_id = :lyid"
                ), {"lyid": league_year_id})
                deleted[tbl_name] = r.rowcount

            # 5. Financial ledger (keyed by league_year_id)
            # NOTE: org_media_shares is NOT wiped — it's configuration data
            # (each org's share percentage), not simulation output.
            r = conn.execute(sa_text(
                "DELETE FROM org_ledger_entries WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["org_ledger_entries"] = r.rowcount

            # 6. Position usage
            r = conn.execute(sa_text(
                "DELETE FROM player_position_usage_week WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["player_position_usage_week"] = r.rowcount

            # 6. Injury events (FK SET NULL cascades to player_injury_state)
            r = conn.execute(sa_text(
                "DELETE FROM player_injury_events WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["player_injury_events"] = r.rowcount

            # 7. Reset orphaned injury states to healthy
            r = conn.execute(sa_text(
                "UPDATE player_injury_state "
                "SET status = 'healthy', weeks_remaining = 0 "
                "WHERE current_event_id IS NULL AND status = 'injured'"
            ))
            deleted["injury_states_reset"] = r.rowcount

            # 8. Fatigue state
            r = conn.execute(sa_text(
                "DELETE FROM player_fatigue_state WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["player_fatigue_state"] = r.rowcount

            # 8b. Scouting actions (what orgs have unlocked on players)
            r = conn.execute(sa_text(
                "DELETE FROM scouting_actions WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["scouting_actions"] = r.rowcount

            # 8c. Scouting budgets (per-org spend tracking)
            r = conn.execute(sa_text(
                "DELETE FROM scouting_budgets WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["scouting_budgets"] = r.rowcount

            # 8d. Recruiting investments
            r = conn.execute(sa_text(
                "DELETE FROM recruiting_investments WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["recruiting_investments"] = r.rowcount

            # 8e. Recruiting commitments
            r = conn.execute(sa_text(
                "DELETE FROM recruiting_commitments WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["recruiting_commitments"] = r.rowcount

            # 8f. Recruiting rankings
            r = conn.execute(sa_text(
                "DELETE FROM recruiting_rankings WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["recruiting_rankings"] = r.rowcount

            # 8g. Recruiting state
            r = conn.execute(sa_text(
                "DELETE FROM recruiting_state WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["recruiting_state"] = r.rowcount

            # 9. Reset timestamp
            conn.execute(sa_text(
                "UPDATE timestamp_state SET "
                "week = 1, games_a_ran = 0, games_b_ran = 0, "
                "games_c_ran = 0, games_d_ran = 0, run_games = 0 "
                "WHERE id = 1"
            ))

            # 10. Reclaim disk space from deleted rows
            optimize_tables = [
                "game_results", "game_batting_lines", "game_pitching_lines",
                "game_substitutions",
                "player_batting_stats", "player_pitching_stats",
                "player_fielding_stats", "player_position_usage_week",
                "player_injury_events", "player_fatigue_state",
                "org_ledger_entries",
                "scouting_actions", "scouting_budgets",
                "recruiting_investments", "recruiting_commitments",
                "recruiting_rankings", "recruiting_state",
            ]
            for tbl in optimize_tables:
                conn.execute(sa_text(f"OPTIMIZE TABLE {tbl}"))
            deleted["optimized_tables"] = len(optimize_tables)

            # 11. Re-run year-start books (media payouts + bonuses)
            from financials.books import run_year_start_books
            books_result = run_year_start_books(engine, year)
            deleted["year_start_books"] = books_result

        # Broadcast updated timestamp
        from services.websocket_manager import ws_manager
        ws_manager.broadcast_timestamp()

        current_app.logger.info(
            f"Wiped season data for league_year_id={league_year_id}: {deleted}"
        )

        return jsonify(ok=True, deleted=deleted, timestamp_reset=True), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("wipe_season: database error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        current_app.logger.exception("wipe_season: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.get("/games/timestamp")
def get_timestamp_endpoint():
    """
    Get the current simulation timestamp state.

    This returns the same data that WebSocket clients receive.

    Response:
    {
        "ID": 1,
        "Season": 2026,
        "SeasonID": 1,
        "Week": 15,
        "GamesARan": true,
        "GamesBRan": false,
        ...
    }

    Example:
      GET /api/v1/games/timestamp
    """
    try:
        from services.timestamp import get_enhanced_timestamp

        timestamp = get_enhanced_timestamp()

        if timestamp:
            return jsonify(timestamp), 200
        else:
            return jsonify(
                error="not_found",
                message="No timestamp data found. Run the database setup first."
            ), 404

    except Exception as e:
        current_app.logger.exception("get_timestamp: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


@games_bp.post("/games/set-week")
def set_week_endpoint():
    """
    Set the simulation to a specific week number.
    Resets all game completion flags.

    Request body:
    {
        "week": 10
    }

    Example:
      POST /api/v1/games/set-week
    """
    try:
        data = request.get_json(silent=True) or {}
        week = data.get("week")

        if week is None or not isinstance(week, int) or week < 1:
            return jsonify(
                error="invalid_request",
                message="'week' is required and must be a positive integer."
            ), 400

        from services.timestamp import set_week

        if set_week(week):
            from services.timestamp import get_enhanced_timestamp
            return jsonify(get_enhanced_timestamp()), 200
        else:
            return jsonify(
                error="update_failed",
                message="Failed to set week."
            ), 500

    except Exception as e:
        current_app.logger.exception("set_week: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/set-phase")
def set_phase_endpoint():
    """
    Directly set phase-related flags on the timestamp.
    Only provided fields are updated.

    Request body (all fields optional):
    {
        "is_offseason": true,
        "is_free_agency_locked": false,
        "is_draft_time": false,
        "is_recruiting_locked": true,
        "free_agency_round": 1
    }

    Example:
      POST /api/v1/games/set-phase
    """
    try:
        data = request.get_json(silent=True) or {}

        if not data:
            return jsonify(
                error="invalid_request",
                message="Request body must include at least one phase flag."
            ), 400

        from services.timestamp import set_phase_flags

        success = set_phase_flags(
            is_offseason=data.get("is_offseason"),
            is_free_agency_locked=data.get("is_free_agency_locked"),
            is_draft_time=data.get("is_draft_time"),
            is_recruiting_locked=data.get("is_recruiting_locked"),
            free_agency_round=data.get("free_agency_round"),
        )

        if success:
            from services.timestamp import get_enhanced_timestamp
            return jsonify(get_enhanced_timestamp()), 200
        else:
            return jsonify(
                error="update_failed",
                message="Failed to set phase flags. Check that at least one valid flag was provided."
            ), 500

    except Exception as e:
        current_app.logger.exception("set_phase: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/end-season")
def end_season_endpoint():
    """
    Transition from regular season to offseason.
    Runs end-of-season contract processing and player progression.

    Request body:
    {
        "league_year_id": 1
    }

    Example:
      POST /api/v1/games/end-season
    """
    try:
        data = request.get_json(silent=True) or {}
        league_year_id = data.get("league_year_id")

        if league_year_id is None:
            return jsonify(
                error="invalid_request",
                message="'league_year_id' is required."
            ), 400

        from services.timestamp import end_regular_season
        result = end_regular_season(int(league_year_id))
        return jsonify(result), 200

    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("end_season: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/start-free-agency")
def start_free_agency_endpoint():
    """
    Open the free agency window.

    Example:
      POST /api/v1/games/start-free-agency
    """
    try:
        from services.timestamp import start_free_agency, get_enhanced_timestamp
        if start_free_agency():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to start free agency."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("start_free_agency: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/advance-fa-round")
def advance_fa_round_endpoint():
    """
    Advance to the next free agency round.

    Example:
      POST /api/v1/games/advance-fa-round
    """
    try:
        from services.timestamp import advance_fa_round, get_enhanced_timestamp
        round_info = advance_fa_round()
        ts = get_enhanced_timestamp()
        ts["round_info"] = round_info
        return jsonify(ts), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("advance_fa_round: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/end-free-agency")
def end_free_agency_endpoint():
    """
    Close the free agency window.

    Example:
      POST /api/v1/games/end-free-agency
    """
    try:
        from services.timestamp import end_free_agency, get_enhanced_timestamp
        if end_free_agency():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to end free agency."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("end_free_agency: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/start-draft")
def start_draft_endpoint():
    """
    Open the draft phase.

    Example:
      POST /api/v1/games/start-draft
    """
    try:
        from services.timestamp import start_draft, get_enhanced_timestamp
        if start_draft():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to start draft."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("start_draft: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/end-draft")
def end_draft_endpoint():
    """
    Close the draft phase.

    Example:
      POST /api/v1/games/end-draft
    """
    try:
        from services.timestamp import end_draft, get_enhanced_timestamp
        if end_draft():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to end draft."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("end_draft: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/start-recruiting")
def start_recruiting_endpoint():
    """
    Open the recruiting window.

    Example:
      POST /api/v1/games/start-recruiting
    """
    try:
        from services.timestamp import start_recruiting, get_enhanced_timestamp
        if start_recruiting():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to start recruiting."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("start_recruiting: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/end-recruiting")
def end_recruiting_endpoint():
    """
    Close the recruiting window.

    Example:
      POST /api/v1/games/end-recruiting
    """
    try:
        from services.timestamp import end_recruiting, get_enhanced_timestamp
        if end_recruiting():
            return jsonify(get_enhanced_timestamp()), 200
        return jsonify(error="update_failed", message="Failed to end recruiting."), 500
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("end_recruiting: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/start-new-season")
def start_new_season_endpoint():
    """
    Transition from offseason to a new regular season.
    Runs year-start financial books and resets timestamp.

    Request body:
    {
        "league_year_id": 2
    }

    Example:
      POST /api/v1/games/start-new-season
    """
    try:
        data = request.get_json(silent=True) or {}
        league_year_id = data.get("league_year_id")

        if league_year_id is None:
            return jsonify(
                error="invalid_request",
                message="'league_year_id' is required."
            ), 400

        from services.timestamp import start_new_season
        result = start_new_season(int(league_year_id))
        return jsonify(result), 200

    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        current_app.logger.exception("start_new_season: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.get("/schedule/week-levels")
def get_week_levels():
    """
    Return distinct league levels that have scheduled games for a given
    league_year + season_week.  Used by the admin panel to dynamically
    populate the level dropdown.

    Query params:
      - league_year_id (required)
      - season_week    (required)
    """
    league_year_id = request.args.get("league_year_id", type=int)
    season_week = request.args.get("season_week", type=int)

    if not league_year_id or not season_week:
        return jsonify(error="missing_field",
                       message="league_year_id and season_week are required"), 400

    try:
        from sqlalchemy import text as sa_text
        from services.schedule_generator import LEVEL_NAMES

        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT DISTINCT league_level FROM gamelist "
                "WHERE season = :ly AND season_week = :sw "
                "ORDER BY league_level DESC"
            ), {"ly": league_year_id, "sw": season_week}).fetchall()

        levels = [
            {"level": r[0], "name": LEVEL_NAMES.get(r[0], f"Level {r[0]}")}
            for r in rows
        ]
        return jsonify(levels=levels), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("get_week_levels: database error")
        return jsonify(error="database_error", message=str(e)), 500


@games_bp.get("/schedule")
def get_schedule():
    """
    View schedule data with filtering. Used by frontend for schedule display.

    Query parameters:
      - season_year (required): The league year
      - league_level (optional): Filter by level
      - team_id (optional): Filter to games involving this team
      - week_start / week_end (optional): Week range filter
      - page (optional): Page number (default 1)
      - page_size (optional): Results per page (default 200, max 500)
    """
    season_year = request.args.get("season_year", type=int)
    if not season_year:
        return jsonify(error="missing_field", message="season_year is required"), 400

    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    week_start = request.args.get("week_start", type=int)
    week_end = request.args.get("week_end", type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 200, type=int), 500)

    try:
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

        return jsonify(result), 200

    except ValueError as e:
        current_app.logger.warning("get_schedule validation error: %s", e)
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        current_app.logger.exception("get_schedule: database error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        current_app.logger.exception("get_schedule: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


def _build_linescore(pbp_data, home_abbrev, away_abbrev, final_home, final_away):
    """
    Build an inning-by-inning linescore from play-by-play data.

    PBP plays have: Inning (int), Inning Half ("Top"/"Bottom"),
    Home Score (cumulative int), Away Score (cumulative int).

    Returns:
        {
            "innings": 9,
            "away": {"runs": [0, 0, 2, 0, ...], "R": 4},
            "home": {"runs": [1, 0, 0, 3, ...], "R": 5}
        }
    H and E are added by the caller from boxscore_json stats.
    """
    from collections import defaultdict

    # Track the cumulative score at the end of each half-inning
    # Key = (inning, half), value = (home_score, away_score)
    end_scores = {}
    for play in pbp_data:
        inn = play.get("Inning")
        half = play.get("Inning Half")
        if inn is None or half is None:
            continue
        # Always overwrite — the last play in each half has the final score
        end_scores[(inn, half)] = (
            int(play.get("Home Score", 0)),
            int(play.get("Away Score", 0)),
        )

    if not end_scores:
        return None

    max_inning = max(k[0] for k in end_scores)

    away_runs = []
    home_runs = []
    prev_away = 0
    prev_home = 0

    for i in range(1, max_inning + 1):
        # Top of inning = away team batting
        if (i, "Top") in end_scores:
            _, cum_away = end_scores[(i, "Top")][0], end_scores[(i, "Top")][1]
            away_runs.append(end_scores[(i, "Top")][1] - prev_away)
            prev_away = end_scores[(i, "Top")][1]
        else:
            away_runs.append(0)

        # Bottom of inning = home team batting
        if (i, "Bottom") in end_scores:
            home_runs.append(end_scores[(i, "Bottom")][0] - prev_home)
            prev_home = end_scores[(i, "Bottom")][0]
        elif i == max_inning:
            # Home didn't bat (was already winning)
            home_runs.append("x")
        else:
            home_runs.append(0)

    return {
        "innings": max_inning,
        "away": {"runs": away_runs, "R": final_away},
        "home": {"runs": home_runs, "R": final_home},
    }


@games_bp.get("/games/<int:game_id>/boxscore")
def get_game_boxscore(game_id: int):
    """
    Return the full box score for a single game.

    Includes linescore (inning-by-inning), per-player batting and pitching
    lines, outcome, and optionally play-by-play.

    Query params:
      - include_pbp (optional, "1"): include full play-by-play array
    """
    from sqlalchemy import text as sa_text

    include_pbp = request.args.get("include_pbp", "1") == "1"

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # 1. Game result + boxscore JSON + play-by-play
            gr = conn.execute(sa_text("""
                SELECT gr.game_id, gr.home_team_id, gr.away_team_id,
                       gr.home_score, gr.away_score, gr.game_outcome,
                       gr.boxscore_json, gr.play_by_play_json,
                       gr.completed_at, gr.season_week,
                       gr.season_subweek, gr.league_level,
                       ht.team_abbrev AS home_abbrev, at2.team_abbrev AS away_abbrev
                FROM game_results gr
                JOIN teams ht ON ht.id = gr.home_team_id
                JOIN teams at2 ON at2.id = gr.away_team_id
                WHERE gr.game_id = :gid
            """), {"gid": game_id}).mappings().first()

            if not gr:
                return jsonify(error="not_found",
                               message=f"No results for game {game_id}"), 404

            # 2. Batting lines
            bat_rows = conn.execute(sa_text("""
                SELECT gbl.player_id, gbl.team_id,
                       p.firstName, p.lastName,
                       gbl.at_bats, gbl.runs, gbl.hits, gbl.doubles_hit,
                       gbl.triples, gbl.home_runs, gbl.rbi, gbl.walks,
                       gbl.strikeouts, gbl.stolen_bases, gbl.caught_stealing
                FROM game_batting_lines gbl
                JOIN simbbPlayers p ON p.id = gbl.player_id
                WHERE gbl.game_id = :gid
                ORDER BY gbl.team_id, gbl.id
            """), {"gid": game_id}).mappings().all()

            # 3. Pitching lines
            pit_rows = conn.execute(sa_text("""
                SELECT gpl.player_id, gpl.team_id,
                       p.firstName, p.lastName,
                       gpl.games_started, gpl.win, gpl.loss, gpl.save_recorded,
                       gpl.innings_pitched_outs, gpl.hits_allowed, gpl.runs_allowed,
                       gpl.earned_runs, gpl.walks, gpl.strikeouts,
                       gpl.home_runs_allowed
                FROM game_pitching_lines gpl
                JOIN simbbPlayers p ON p.id = gpl.player_id
                WHERE gpl.game_id = :gid
                ORDER BY gpl.team_id, gpl.id
            """), {"gid": game_id}).mappings().all()

            # 4. Substitutions
            sub_rows = conn.execute(sa_text("""
                SELECT gs.inning, gs.half, gs.sub_type,
                       gs.player_in_id, pin.firstName AS in_first, pin.lastName AS in_last,
                       gs.player_out_id, pout.firstName AS out_first, pout.lastName AS out_last,
                       gs.new_position
                FROM game_substitutions gs
                JOIN simbbPlayers pin ON pin.id = gs.player_in_id
                JOIN simbbPlayers pout ON pout.id = gs.player_out_id
                WHERE gs.game_id = :gid
                ORDER BY gs.inning, gs.id
            """), {"gid": game_id}).mappings().all()

        home_tid = int(gr["home_team_id"])
        away_tid = int(gr["away_team_id"])

        def _format_batter(r):
            return {
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "ab": int(r["at_bats"]), "r": int(r["runs"]),
                "h": int(r["hits"]), "2b": int(r["doubles_hit"]),
                "3b": int(r["triples"]), "hr": int(r["home_runs"]),
                "rbi": int(r["rbi"]), "bb": int(r["walks"]),
                "so": int(r["strikeouts"]), "sb": int(r["stolen_bases"]),
                "cs": int(r["caught_stealing"]),
            }

        def _format_pitcher(r):
            ipo = int(r["innings_pitched_outs"])
            ip = f"{ipo // 3}.{ipo % 3}"
            dec = ""
            if int(r["win"]):
                dec = "W"
            elif int(r["loss"]):
                dec = "L"
            elif int(r["save_recorded"]):
                dec = "S"
            return {
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "gs": int(r["games_started"]),
                "ip": ip, "h": int(r["hits_allowed"]),
                "r": int(r["runs_allowed"]), "er": int(r["earned_runs"]),
                "bb": int(r["walks"]), "so": int(r["strikeouts"]),
                "hr": int(r["home_runs_allowed"]), "dec": dec,
            }

        import json as _json

        # ---- Build inning-by-inning linescore from play-by-play ----
        linescore = None
        pbp_parsed = None
        pbp_raw = gr["play_by_play_json"]
        boxscore_raw = gr["boxscore_json"]

        if pbp_raw:
            pbp_parsed = _json.loads(pbp_raw) if isinstance(pbp_raw, str) else pbp_raw
            if isinstance(pbp_parsed, list) and pbp_parsed:
                linescore = _build_linescore(
                    pbp_parsed,
                    gr["home_abbrev"], gr["away_abbrev"],
                    int(gr["home_score"]), int(gr["away_score"]),
                )

        # Compute team hits / errors from boxscore_json stats
        home_hits = 0
        away_hits = 0
        home_errors = 0
        away_errors = 0
        if boxscore_raw:
            bs = _json.loads(boxscore_raw) if isinstance(boxscore_raw, str) else boxscore_raw
            stats_block = bs.get("stats") or {}
            home_abbrev = gr["home_abbrev"]
            away_abbrev = gr["away_abbrev"]
            for b in (stats_block.get("batting") or []):
                tn = b.get("teamname", "")
                h = int(b.get("hits", 0))
                if tn == home_abbrev:
                    home_hits += h
                elif tn == away_abbrev:
                    away_hits += h
            for f in (stats_block.get("fielding") or []):
                tn = f.get("teamname", "")
                e = int(f.get("errors", 0))
                if tn == home_abbrev:
                    home_errors += e
                elif tn == away_abbrev:
                    away_errors += e

        if linescore:
            linescore["home"]["H"] = home_hits
            linescore["home"]["E"] = home_errors
            linescore["away"]["H"] = away_hits
            linescore["away"]["E"] = away_errors

        substitutions = [
            {
                "inning": int(s["inning"]),
                "half": s["half"],
                "type": s["sub_type"],
                "player_in": {"id": int(s["player_in_id"]),
                               "name": f"{s['in_first']} {s['in_last']}"},
                "player_out": {"id": int(s["player_out_id"]),
                                "name": f"{s['out_first']} {s['out_last']}"},
                "new_position": s["new_position"],
            }
            for s in sub_rows
        ]

        result = {
            "game_id": game_id,
            "home_team": {"id": home_tid, "abbrev": gr["home_abbrev"],
                          "score": int(gr["home_score"])},
            "away_team": {"id": away_tid, "abbrev": gr["away_abbrev"],
                          "score": int(gr["away_score"])},
            "linescore": linescore,
            "batting": {
                "home": [_format_batter(r) for r in bat_rows if int(r["team_id"]) == home_tid],
                "away": [_format_batter(r) for r in bat_rows if int(r["team_id"]) == away_tid],
            },
            "pitching": {
                "home": [_format_pitcher(r) for r in pit_rows if int(r["team_id"]) == home_tid],
                "away": [_format_pitcher(r) for r in pit_rows if int(r["team_id"]) == away_tid],
            },
            "substitutions": substitutions,
            "game_outcome": gr["game_outcome"],
            "season_week": int(gr["season_week"]),
            "season_subweek": gr["season_subweek"],
            "completed_at": str(gr["completed_at"]) if gr["completed_at"] else None,
        }
        if include_pbp and pbp_parsed:
            result["play_by_play"] = pbp_parsed
        return jsonify(result), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("get_game_boxscore: db error")
        return jsonify(error="database_error", message=str(e)), 500


@games_bp.get("/games/<int:game_id>/play-by-play")
def get_game_play_by_play(game_id: int):
    """Return the play-by-play JSON blob for a single game."""
    from sqlalchemy import text as sa_text
    import json as _json

    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(sa_text(
                "SELECT play_by_play_json FROM game_results WHERE game_id = :gid"
            ), {"gid": game_id}).first()

        if not row:
            return jsonify(error="not_found",
                           message=f"No results for game {game_id}"), 404

        pbp = row[0]
        if pbp is None:
            return jsonify(game_id=game_id, play_by_play=[]), 200

        data = _json.loads(pbp) if isinstance(pbp, str) else pbp
        return jsonify(game_id=game_id, play_by_play=data), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("get_game_play_by_play: db error")
        return jsonify(error="database_error", message=str(e)), 500


@games_bp.get("/games/results")
def get_game_results_list():
    """
    Paginated list of completed games with scores.

    Query params: league_year_id, season_week, league_level, team_id, page, page_size
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    season_week = request.args.get("season_week", type=int)
    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    where_clauses = []
    params = {}

    if league_year_id:
        where_clauses.append("gr.season = :season")
        params["season"] = league_year_id
    if season_week:
        where_clauses.append("gr.season_week = :sw")
        params["sw"] = season_week
    if league_level:
        where_clauses.append("gr.league_level = :ll")
        params["ll"] = league_level
    if team_id:
        where_clauses.append("(gr.home_team_id = :tid OR gr.away_team_id = :tid)")
        params["tid"] = team_id

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(
                f"SELECT COUNT(*) FROM game_results gr{where_sql}"
            ), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT gr.game_id, gr.home_team_id, gr.away_team_id,
                       gr.home_score, gr.away_score, gr.game_outcome,
                       gr.season_week, gr.season_subweek, gr.league_level,
                       gr.completed_at,
                       ht.team_abbrev AS home_abbrev,
                       at2.team_abbrev AS away_abbrev
                FROM game_results gr
                JOIN teams ht ON ht.id = gr.home_team_id
                JOIN teams at2 ON at2.id = gr.away_team_id
                {where_sql}
                ORDER BY gr.completed_at DESC
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        games = [{
            "game_id": int(r["game_id"]),
            "home_team": {"id": int(r["home_team_id"]), "abbrev": r["home_abbrev"],
                          "score": int(r["home_score"])},
            "away_team": {"id": int(r["away_team_id"]), "abbrev": r["away_abbrev"],
                          "score": int(r["away_score"])},
            "outcome": r["game_outcome"],
            "week": int(r["season_week"]),
            "subweek": r["season_subweek"],
            "league_level": int(r["league_level"]),
            "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
        } for r in rows]

        pages = (total + page_size - 1) // page_size if total else 0

        return jsonify(games=games, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("get_game_results_list: db error")
        return jsonify(error="database_error", message=str(e)), 500


@games_bp.get("/games/debug/synthetic")
def get_synthetic_matchups():
    """
    Generate synthetic matchups for testing purposes.

    Creates fake game payloads by randomly pairing teams from the database.
    Returns payloads in the same structure as build_week_payloads() for
    consistent engine testing.

    Query parameters:
      - count (int): Number of matchups to generate (default: 10, max: 1000)
      - league_level (int): League level to use (default: 9 for MLB)
      - league_year_id (int): Optional league year ID for context
      - seed (int): Optional random seed for reproducible results

    Example:
      GET /api/v1/games/debug/synthetic
      GET /api/v1/games/debug/synthetic?count=50&league_level=9
      GET /api/v1/games/debug/synthetic?count=100&seed=12345

    Response:
    {
        "league_year_id": null,
        "season_week": null,
        "league_level": 9,
        "total_games": 50,
        "synthetic": true,
        "seed": 12345,
        "game_constants": {...},
        "rules": {...},
        "subweeks": {
            "a": [game_payload, ...],
            "b": [...],
            "c": [...],
            "d": [...]
        }
    }
    """
    # Parse query parameters
    count = request.args.get("count", default=10, type=int)
    league_level = request.args.get("league_level", default=9, type=int)
    league_year_id = request.args.get("league_year_id", type=int)
    seed = request.args.get("seed", type=int)

    # Validate count
    if count < 1:
        return jsonify(
            error="invalid_parameter",
            message="count must be at least 1"
        ), 400

    if count > 1000:
        return jsonify(
            error="invalid_parameter",
            message="count cannot exceed 1000"
        ), 400

    engine = get_engine()

    try:
        with engine.connect() as conn:
            result = build_synthetic_matchups(
                conn=conn,
                count=count,
                league_level=league_level,
                league_year_id=league_year_id,
                seed=seed,
            )

        current_app.logger.info(
            f"Generated {result['total_games']} synthetic matchups "
            f"(level={league_level}, seed={seed})"
        )

        return jsonify(result), 200

    except ValueError as e:
        current_app.logger.warning(f"get_synthetic_matchups validation error: {e}")
        return jsonify(
            error="validation_error",
            message=str(e)
        ), 400

    except SQLAlchemyError as e:
        current_app.logger.exception("get_synthetic_matchups: database error")
        return jsonify(
            error="database_error",
            message=str(e)
        ), 500

    except Exception as e:
        current_app.logger.exception("get_synthetic_matchups: unexpected error")
        return jsonify(
            error="unexpected_error",
            message=str(e)
        ), 500


# -------------------------------------------------------------------
# Async task endpoints
# -------------------------------------------------------------------

def _run_synthetic_task(task_id: str, count: int, league_level: int,
                        league_year_id: int | None, seed: int | None):
    """
    Background worker function for synthetic matchup generation.

    Runs in a separate thread and updates the task store with progress.
    """
    import logging
    logger = logging.getLogger(__name__)

    store = get_task_store()
    store.set_running(task_id)

    def on_progress(current: int, total: int):
        store.set_progress(task_id, current)

    engine = get_engine()

    try:
        with engine.connect() as conn:
            result = build_synthetic_matchups_with_progress(
                conn=conn,
                count=count,
                league_level=league_level,
                league_year_id=league_year_id,
                seed=seed,
                on_progress=on_progress,
            )

        store.set_complete(task_id, result)
        logger.info(f"Task {task_id} completed: {result['total_games']} games")

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        store.set_failed(task_id, str(e))


def _run_season_task(task_id: str, league_year_id: int, league_level: int,
                     start_week: int, end_week: int):
    """
    Background worker: simulate every week of a season in sequence.

    Runs in a separate thread, updates task store progress per week.
    """
    import logging
    logger = logging.getLogger(__name__)

    store = get_task_store()
    store.set_running(task_id)

    engine = get_engine()
    total_games = 0
    weeks_completed = 0

    try:
        for week in range(start_week, end_week + 1):
            logger.info(
                f"run_season task {task_id}: simulating week {week} "
                f"(league_year={league_year_id}, level={league_level})"
            )

            # Update timestamp to current week and mark running
            update_timestamp({"week": week, "run_games": True}, broadcast=True)

            # Fresh connection per week to avoid long-held transactions
            with engine.connect() as conn:
                result = build_week_payloads(
                    conn=conn,
                    league_year_id=league_year_id,
                    season_week=week,
                    league_level=league_level,
                    simulate=True,
                )

            week_games = result.get("total_games", 0)
            total_games += week_games

            # Mark subweeks completed
            subweeks = result.get("subweeks", {})
            for sw_key in ["a", "b", "c", "d"]:
                if subweeks.get(sw_key):
                    set_subweek_completed(sw_key, broadcast=False)

            set_run_games(False, broadcast=False)

            # Advance to next week
            advance_week(broadcast=True)

            weeks_completed += 1
            store.set_progress(task_id, weeks_completed)

            logger.info(
                f"run_season task {task_id}: week {week} done — "
                f"{week_games} games, {weeks_completed}/{end_week - start_week + 1} weeks"
            )

        summary = {
            "league_year_id": league_year_id,
            "league_level": league_level,
            "weeks_completed": weeks_completed,
            "total_games": total_games,
            "start_week": start_week,
            "end_week": end_week,
        }
        store.set_complete(task_id, summary)
        logger.info(f"run_season task {task_id} completed: {summary}")

    except Exception as e:
        # Reset run_games flag on failure
        try:
            set_run_games(False, broadcast=True)
        except Exception:
            pass
        logger.exception(
            f"run_season task {task_id} failed at week "
            f"{start_week + weeks_completed}"
        )
        store.set_failed(task_id, str(e))


@games_bp.post("/games/run-season")
def run_season():
    """
    Start a background task to simulate an entire season.

    Processes every week from start_week to end_week sequentially,
    advancing the timestamp after each week.

    Request body:
    {
        "league_year_id": 1,
        "league_level": 9,
        "start_week": 1,    // optional, default 1
        "end_week": 52       // optional, default 52
    }

    Response (immediate):
    {
        "task_id": "abc12345",
        "status": "pending",
        "total": 52,
        "poll_url": "/api/v1/games/tasks/abc12345"
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return jsonify(error="invalid_request",
                       message="Request body must be JSON"), 400

    league_year_id = body.get("league_year_id")
    league_level = body.get("league_level")
    start_week = body.get("start_week", 1)
    end_week = body.get("end_week", 52)

    if league_year_id is None or league_level is None:
        return jsonify(error="missing_field",
                       message="league_year_id and league_level are required"), 400

    try:
        league_year_id = int(league_year_id)
        league_level = int(league_level)
        start_week = int(start_week)
        end_week = int(end_week)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    if start_week < 1 or end_week < start_week:
        return jsonify(error="invalid_range",
                       message="start_week must be >= 1 and end_week >= start_week"), 400

    total_weeks = end_week - start_week + 1

    store = get_task_store()
    task_data = store.create_task("run_season", total=total_weeks, metadata={
        "league_year_id": league_year_id,
        "league_level": league_level,
        "start_week": start_week,
        "end_week": end_week,
    })
    task_id = task_data["task_id"]

    t = threading.Thread(
        target=_run_season_task,
        args=(task_id, league_year_id, league_level, start_week, end_week),
        daemon=True,
    )
    t.start()

    current_app.logger.info(
        f"Started run_season task {task_id}: weeks {start_week}-{end_week}, "
        f"level={league_level}, league_year={league_year_id}"
    )

    return jsonify(
        task_id=task_id,
        status="pending",
        total=total_weeks,
        poll_url=f"/api/v1/games/tasks/{task_id}",
    ), 202


def _run_all_levels_task(task_id: str, league_year_id: int,
                         start_week: int, end_week: int):
    """
    Background worker: simulate every week for ALL league levels in sequence.

    Iterates level-by-level (9,8,7,6,5,4,3), running each level's full
    week range. Does NOT advance the timestamp/season state — purely runs
    simulations for testing statistical and financial models.
    """
    import logging
    logger = logging.getLogger(__name__)

    ALL_LEVELS = [9, 8, 7, 6, 5, 4, 3]
    LEVEL_NAMES = {9: "MLB", 8: "AAA", 7: "AA", 6: "High-A",
                   5: "A", 4: "Scraps", 3: "College"}

    store = get_task_store()
    store.set_running(task_id)

    engine = get_engine()
    total_games = 0
    steps_completed = 0
    total_weeks = end_week - start_week + 1

    level_summaries = {}

    try:
        for level in ALL_LEVELS:
            level_games = 0
            level_name = LEVEL_NAMES.get(level, str(level))
            logger.info(
                f"run_all_levels task {task_id}: starting level {level_name}"
            )

            for week in range(start_week, end_week + 1):
                # Update timestamp to current week
                update_timestamp({"week": week, "run_games": True}, broadcast=True)

                try:
                    with engine.connect() as conn:
                        result = build_week_payloads(
                            conn=conn,
                            league_year_id=league_year_id,
                            season_week=week,
                            league_level=level,
                            simulate=True,
                        )

                    week_games = result.get("total_games", 0)
                    level_games += week_games
                    total_games += week_games

                    subweeks = result.get("subweeks", {})
                    for sw_key in ["a", "b", "c", "d"]:
                        if subweeks.get(sw_key):
                            set_subweek_completed(sw_key, broadcast=False)
                except ValueError:
                    # No games for this level/week — skip silently
                    pass

                set_run_games(False, broadcast=False)
                advance_week(broadcast=True)

                steps_completed += 1
                store.set_progress(task_id, steps_completed)

            level_summaries[level_name] = level_games
            logger.info(
                f"run_all_levels task {task_id}: level {level_name} done — "
                f"{level_games} games"
            )

        summary = {
            "league_year_id": league_year_id,
            "levels_completed": len(ALL_LEVELS),
            "weeks_per_level": total_weeks,
            "total_games": total_games,
            "by_level": level_summaries,
            "start_week": start_week,
            "end_week": end_week,
        }
        store.set_complete(task_id, summary)
        logger.info(f"run_all_levels task {task_id} completed: {summary}")

    except Exception as e:
        try:
            set_run_games(False, broadcast=True)
        except Exception:
            pass
        logger.exception(
            f"run_all_levels task {task_id} failed at step {steps_completed}"
        )
        store.set_failed(task_id, str(e))


@games_bp.post("/games/run-season-all")
def run_season_all():
    """
    Start a background task to simulate ALL league levels for a season.

    Runs levels 9,8,7,6,5,4,3 sequentially, each through the full
    week range. Does not change season state — for testing only.

    Request body:
    {
        "league_year_id": 1,
        "start_week": 1,
        "end_week": 52
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return jsonify(error="invalid_request",
                       message="Request body must be JSON"), 400

    league_year_id = body.get("league_year_id")
    start_week = body.get("start_week", 1)
    end_week = body.get("end_week", 52)

    if league_year_id is None:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    try:
        league_year_id = int(league_year_id)
        start_week = int(start_week)
        end_week = int(end_week)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    if start_week < 1 or end_week < start_week:
        return jsonify(error="invalid_range",
                       message="start_week must be >= 1 and end_week >= start_week"), 400

    total_weeks = end_week - start_week + 1
    num_levels = 7  # levels 9 through 3
    total_steps = total_weeks * num_levels

    store = get_task_store()
    task_data = store.create_task("run_all_levels", total=total_steps, metadata={
        "league_year_id": league_year_id,
        "start_week": start_week,
        "end_week": end_week,
        "levels": "9,8,7,6,5,4,3",
    })
    task_id = task_data["task_id"]

    t = threading.Thread(
        target=_run_all_levels_task,
        args=(task_id, league_year_id, start_week, end_week),
        daemon=True,
    )
    t.start()

    current_app.logger.info(
        f"Started run_all_levels task {task_id}: weeks {start_week}-{end_week}, "
        f"all levels, league_year={league_year_id}"
    )

    return jsonify(
        task_id=task_id,
        status="pending",
        total=total_steps,
        poll_url=f"/api/v1/games/tasks/{task_id}",
    ), 202


@games_bp.route("/games/debug/synthetic-async", methods=["GET", "POST"])
def start_synthetic_matchups_async():
    """
    Start async generation of synthetic matchups.

    Returns immediately with a task_id that can be polled for status/results.

    GET (browser-friendly):
        /api/v1/games/debug/synthetic-async?count=1000&league_level=9

    POST (JSON body):
    {
        "count": 1000,           // Number of games (default: 10, max: 10000)
        "league_level": 9,       // League level (default: 9)
        "league_year_id": null,  // Optional league year ID
        "seed": 12345            // Optional random seed
    }

    Response:
    {
        "task_id": "abc12345",
        "status": "pending",
        "total": 1000,
        "poll_url": "/api/v1/games/tasks/abc12345"
    }

    Example:
        GET  /api/v1/games/debug/synthetic-async?count=1000
        POST /api/v1/games/debug/synthetic-async  (with JSON body)
    """
    # Support both GET (query params) and POST (JSON body)
    if request.method == "GET":
        body = {
            "count": request.args.get("count", 10),
            "league_level": request.args.get("league_level", 9),
            "league_year_id": request.args.get("league_year_id"),
            "seed": request.args.get("seed"),
        }
    else:
        body = request.get_json(silent=True) or {}

    count = body.get("count", 10)
    league_level = body.get("league_level", 9)
    league_year_id = body.get("league_year_id")
    seed = body.get("seed")

    # Validate count
    try:
        count = int(count)
    except (TypeError, ValueError):
        return jsonify(
            error="invalid_parameter",
            message="count must be an integer"
        ), 400

    if count < 1:
        return jsonify(
            error="invalid_parameter",
            message="count must be at least 1"
        ), 400

    if count > 10000:
        return jsonify(
            error="invalid_parameter",
            message="count cannot exceed 10000 for async jobs"
        ), 400

    # Validate league_level
    try:
        league_level = int(league_level)
    except (TypeError, ValueError):
        return jsonify(
            error="invalid_parameter",
            message="league_level must be an integer"
        ), 400

    # Validate optional params
    if league_year_id is not None:
        try:
            league_year_id = int(league_year_id)
        except (TypeError, ValueError):
            return jsonify(
                error="invalid_parameter",
                message="league_year_id must be an integer"
            ), 400

    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            return jsonify(
                error="invalid_parameter",
                message="seed must be an integer"
            ), 400

    # Create task
    store = get_task_store()
    task = store.create_task(
        task_type="synthetic_matchups",
        total=count,
        metadata={
            "league_level": league_level,
            "league_year_id": league_year_id,
            "seed": seed,
        }
    )
    task_id = task["task_id"]

    # Start background thread
    thread = threading.Thread(
        target=_run_synthetic_task,
        args=(task_id, count, league_level, league_year_id, seed),
        daemon=True,
    )
    thread.start()

    current_app.logger.info(
        f"Started async synthetic task {task_id} (count={count}, level={league_level})"
    )

    poll_url = f"/api/v1/games/tasks/{task_id}"

    # If redirect=true, send browser directly to status page
    if request.args.get("redirect", "").lower() == "true":
        return redirect(poll_url)

    return jsonify(
        task_id=task_id,
        status=task["status"],
        total=count,
        poll_url=poll_url,
        download_url=f"/api/v1/games/tasks/{task_id}/download",
    ), 202


@games_bp.get("/games/tasks/<task_id>")
def get_task_status(task_id: str):
    """
    Get the status and result of an async task.

    Response (pending/running):
    {
        "task_id": "abc12345",
        "status": "running",
        "progress": 450,
        "total": 1000,
        "metadata": {...}
    }

    Response (complete):
    {
        "task_id": "abc12345",
        "status": "complete",
        "progress": 1000,
        "total": 1000,
        "result": {...}  // Full game payload (WARNING: can be very large!)
    }

    Response (failed):
    {
        "task_id": "abc12345",
        "status": "failed",
        "error": "Error message"
    }

    Query parameters:
        - include_result (bool): If false, omit result even when complete (default: false)
                                 Set to true only for small tasks; use /download for large results

    Example:
        GET /api/v1/games/tasks/abc12345
        GET /api/v1/games/tasks/abc12345?include_result=true
    """
    store = get_task_store()

    # Default to NOT including result (it's huge and crashes browsers)
    include_result = request.args.get("include_result", "false").lower() == "true"

    if include_result:
        task = store.get_task(task_id)
    else:
        # Get task without result to avoid loading large data
        tasks = store.list_tasks()
        task = next((t for t in tasks if t["task_id"] == task_id), None)
        if task is None:
            # Try to get it directly (might be filtered out)
            task = store.get_task(task_id)
            if task:
                task.pop("result", None)

    if not task:
        return jsonify(
            error="not_found",
            message=f"Task {task_id} not found"
        ), 404

    # Add download URL hint for completed tasks
    if task["status"] == TaskStatus.COMPLETE.value and not include_result:
        task["download_url"] = f"/api/v1/games/tasks/{task_id}/download"

    return jsonify(task), 200


@games_bp.get("/games/tasks/<task_id>/download")
def download_task_result(task_id: str):
    """
    Download the task result as a JSON file.

    This streams the compressed result directly, avoiding memory issues
    with large payloads. The browser will download it as a .json file.

    Query parameters:
        - compressed (bool): If true, return gzipped data (default: false)

    Example:
        GET /api/v1/games/tasks/abc12345/download
        GET /api/v1/games/tasks/abc12345/download?compressed=true
    """
    store = get_task_store()

    # First check if task exists and is complete
    task = store.get_task(task_id)
    if not task:
        return jsonify(
            error="not_found",
            message=f"Task {task_id} not found"
        ), 404

    if task["status"] != TaskStatus.COMPLETE.value:
        return jsonify(
            error="not_ready",
            message=f"Task {task_id} is not complete (status: {task['status']})",
            status=task["status"],
            progress=task["progress"],
            total=task["total"],
        ), 400

    # Get compressed result
    compressed_data = store.get_task_result_compressed(task_id)
    if not compressed_data:
        return jsonify(
            error="no_result",
            message=f"Task {task_id} has no result data"
        ), 404

    # Return compressed or decompressed based on query param
    return_compressed = request.args.get("compressed", "false").lower() == "true"

    filename = f"synthetic_games_{task_id}.json"

    if return_compressed:
        return Response(
            compressed_data,
            mimetype="application/gzip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}.gz",
                "Content-Length": len(compressed_data),
            }
        )
    else:
        # Decompress for download
        decompressed = gzip.decompress(compressed_data)
        return Response(
            decompressed,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Length": len(decompressed),
            }
        )


@games_bp.get("/games/tasks")
def list_tasks():
    """
    List all active tasks.

    Query parameters:
        - type (str): Filter by task type (e.g., "synthetic_matchups")

    Response:
    {
        "tasks": [
            {"task_id": "abc123", "status": "running", "progress": 50, "total": 100, ...},
            {"task_id": "def456", "status": "complete", "progress": 100, "total": 100, ...}
        ]
    }

    Example:
        GET /api/v1/games/tasks
        GET /api/v1/games/tasks?type=synthetic_matchups
    """
    store = get_task_store()
    task_type = request.args.get("type")

    tasks = store.list_tasks(task_type=task_type)

    # Add download URLs for completed tasks
    for task in tasks:
        if task["status"] == TaskStatus.COMPLETE.value:
            task["download_url"] = f"/api/v1/games/tasks/{task['task_id']}/download"

    return jsonify(tasks=tasks), 200


@games_bp.delete("/games/tasks/<task_id>")
def delete_task(task_id: str):
    """
    Delete a task from the store.

    Useful for cleaning up completed tasks or freeing memory.

    Response:
    {
        "ok": true,
        "message": "Task abc12345 deleted"
    }

    Example:
        DELETE /api/v1/games/tasks/abc12345
    """
    store = get_task_store()

    if store.delete_task(task_id):
        return jsonify(
            ok=True,
            message=f"Task {task_id} deleted"
        ), 200
    else:
        return jsonify(
            error="not_found",
            message=f"Task {task_id} not found"
        ), 404
