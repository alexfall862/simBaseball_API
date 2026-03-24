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
    _tick_injuries,
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


@games_bp.post("/games/simulate-subweek")
def simulate_subweek():
    """
    Simulate a single subweek (a, b, c, or d) for a given week.

    Request body:
    {
        "league_year_id": 2026,
        "season_week": 53,
        "subweek": "a",
        "league_level": 9  // optional
    }
    """
    body = request.get_json(force=True, silent=True) or {}

    league_year_id = body.get("league_year_id")
    season_week = body.get("season_week")
    subweek = body.get("subweek")
    league_level = body.get("league_level")

    if not league_year_id or not season_week or not subweek:
        return jsonify(
            error="missing_field",
            message="league_year_id, season_week, and subweek are required"
        ), 400

    if subweek not in ("a", "b", "c", "d"):
        return jsonify(
            error="invalid_subweek",
            message="subweek must be one of: a, b, c, d"
        ), 400

    try:
        league_year_id = int(league_year_id)
        season_week = int(season_week)
        if league_level is not None:
            league_level = int(league_level)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    engine = get_engine()

    try:
        update_timestamp({"week": season_week, "run_games": True})

        with engine.connect() as conn:
            result = build_week_payloads(
                conn=conn,
                league_year_id=league_year_id,
                season_week=season_week,
                league_level=league_level,
                subweek_filter=subweek,
            )

        # Mark just this subweek as completed
        set_subweek_completed(subweek, broadcast=False)
        set_run_games(False, broadcast=True)

        games_in_subweek = len(result.get("subweeks", {}).get(subweek, []))
        current_app.logger.info(
            "simulate_subweek: %d games in subweek '%s' (week %d, level %s)",
            games_in_subweek, subweek, season_week, league_level,
        )

        return jsonify(result), 200

    except ValueError as e:
        set_run_games(False, broadcast=True)
        return jsonify(error="validation_error", message=str(e)), 404

    except SQLAlchemyError as e:
        set_run_games(False, broadcast=True)
        return jsonify(error="database_error", message=str(e)), 500

    except Exception as e:
        set_run_games(False, broadcast=True)
        current_app.logger.exception("simulate_subweek: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


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


@games_bp.post("/games/rollback-week")
def rollback_week():
    """
    Roll back a specific week's simulation results.

    Removes game results, per-game box score lines, substitutions,
    injuries, and stamina changes for the given week. Decrements
    season-accumulated stats by each game's per-game line values.
    Resets the week's simulation flags so it can be re-run.

    Does NOT touch gameplans, rotation config, or the schedule.

    Request body:
    {
        "league_year_id": 1,
        "season_week": 5
    }
    """
    from sqlalchemy import text as sa_text

    body = request.get_json(force=True, silent=True) or {}
    league_year_id = body.get("league_year_id")
    season_week = body.get("season_week")

    if league_year_id is None or season_week is None:
        return jsonify(error="missing_field",
                       message="league_year_id and season_week are required"), 400

    try:
        league_year_id = int(league_year_id)
        season_week = int(season_week)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    engine = get_engine()

    try:
        with engine.begin() as conn:
            deleted = {}

            # Find all game_ids for this week
            game_rows = conn.execute(sa_text(
                "SELECT game_id FROM game_results "
                "WHERE season = :lyid AND season_week = :sw"
            ), {"lyid": league_year_id, "sw": season_week}).all()
            game_ids = [int(r[0]) for r in game_rows]

            if not game_ids:
                return jsonify(
                    ok=True, message="No games found for this week",
                    deleted={}, games_found=0
                ), 200

            gid_ph = ", ".join(f":g{i}" for i in range(len(game_ids)))
            gid_params = {f"g{i}": gid for i, gid in enumerate(game_ids)}
            lyid_params = {"lyid": league_year_id}
            all_params = {**gid_params, **lyid_params}

            # 1. Subtract per-game batting lines from season accumulation
            r = conn.execute(sa_text(f"""
                UPDATE player_batting_stats pbs
                JOIN (
                    SELECT player_id, team_id,
                        SUM(at_bats) AS at_bats, SUM(runs) AS runs,
                        SUM(hits) AS hits, SUM(doubles_hit) AS doubles_hit,
                        SUM(triples) AS triples, SUM(home_runs) AS home_runs,
                        SUM(rbi) AS rbi, SUM(walks) AS walks,
                        SUM(strikeouts) AS strikeouts,
                        SUM(stolen_bases) AS stolen_bases,
                        SUM(caught_stealing) AS caught_stealing
                    FROM game_batting_lines
                    WHERE game_id IN ({gid_ph}) AND league_year_id = :lyid
                    GROUP BY player_id, team_id
                ) gbl ON pbs.player_id = gbl.player_id
                    AND pbs.team_id = gbl.team_id
                    AND pbs.league_year_id = :lyid
                SET pbs.at_bats = GREATEST(0, pbs.at_bats - gbl.at_bats),
                    pbs.runs = GREATEST(0, pbs.runs - gbl.runs),
                    pbs.hits = GREATEST(0, pbs.hits - gbl.hits),
                    pbs.doubles_hit = GREATEST(0, pbs.doubles_hit - gbl.doubles_hit),
                    pbs.triples = GREATEST(0, pbs.triples - gbl.triples),
                    pbs.home_runs = GREATEST(0, pbs.home_runs - gbl.home_runs),
                    pbs.rbi = GREATEST(0, pbs.rbi - gbl.rbi),
                    pbs.walks = GREATEST(0, pbs.walks - gbl.walks),
                    pbs.strikeouts = GREATEST(0, pbs.strikeouts - gbl.strikeouts),
                    pbs.stolen_bases = GREATEST(0, pbs.stolen_bases - gbl.stolen_bases),
                    pbs.caught_stealing = GREATEST(0, pbs.caught_stealing - gbl.caught_stealing)
            """), all_params)
            deleted["batting_stats_decremented"] = r.rowcount

            # 2. Subtract per-game pitching lines from season accumulation
            r = conn.execute(sa_text(f"""
                UPDATE player_pitching_stats pps
                JOIN (
                    SELECT player_id, team_id,
                        SUM(games_started) AS games_started,
                        SUM(win) AS win, SUM(loss) AS loss,
                        SUM(save_recorded) AS save_recorded,
                        SUM(innings_pitched_outs) AS innings_pitched_outs,
                        SUM(hits_allowed) AS hits_allowed,
                        SUM(runs_allowed) AS runs_allowed,
                        SUM(earned_runs) AS earned_runs,
                        SUM(walks) AS walks, SUM(strikeouts) AS strikeouts,
                        SUM(home_runs_allowed) AS home_runs_allowed
                    FROM game_pitching_lines
                    WHERE game_id IN ({gid_ph}) AND league_year_id = :lyid
                    GROUP BY player_id, team_id
                ) gpl ON pps.player_id = gpl.player_id
                    AND pps.team_id = gpl.team_id
                    AND pps.league_year_id = :lyid
                SET pps.games = GREATEST(0, pps.games - 1),
                    pps.games_started = GREATEST(0, pps.games_started - gpl.games_started),
                    pps.wins = GREATEST(0, pps.wins - gpl.win),
                    pps.losses = GREATEST(0, pps.losses - gpl.loss),
                    pps.saves = GREATEST(0, pps.saves - gpl.save_recorded),
                    pps.innings_pitched_outs = GREATEST(0, pps.innings_pitched_outs - gpl.innings_pitched_outs),
                    pps.hits_allowed = GREATEST(0, pps.hits_allowed - gpl.hits_allowed),
                    pps.runs_allowed = GREATEST(0, pps.runs_allowed - gpl.runs_allowed),
                    pps.earned_runs = GREATEST(0, pps.earned_runs - gpl.earned_runs),
                    pps.walks = GREATEST(0, pps.walks - gpl.walks),
                    pps.strikeouts = GREATEST(0, pps.strikeouts - gpl.strikeouts),
                    pps.home_runs_allowed = GREATEST(0, pps.home_runs_allowed - gpl.home_runs_allowed)
            """), all_params)
            deleted["pitching_stats_decremented"] = r.rowcount

            # 3. Delete per-game lines
            for tbl in ("game_batting_lines", "game_pitching_lines",
                        "game_substitutions"):
                r = conn.execute(sa_text(
                    f"DELETE FROM {tbl} WHERE game_id IN ({gid_ph})"
                ), gid_params)
                deleted[tbl] = r.rowcount

            # 4. Delete game results
            r = conn.execute(sa_text(
                f"DELETE FROM game_results WHERE game_id IN ({gid_ph})"
            ), gid_params)
            deleted["game_results"] = r.rowcount

            # 5. Delete position usage for this week
            r = conn.execute(sa_text(
                "DELETE FROM player_position_usage_week "
                "WHERE league_year_id = :lyid AND season_week = :sw"
            ), {"lyid": league_year_id, "sw": season_week})
            deleted["position_usage"] = r.rowcount

            # 6. Delete injuries created during this week's games
            r = conn.execute(sa_text(
                f"DELETE FROM player_injury_events "
                f"WHERE gamelist_id IN ({gid_ph})"
            ), gid_params)
            deleted["injury_events"] = r.rowcount

            # Reset orphaned injury states
            r = conn.execute(sa_text(
                "UPDATE player_injury_state "
                "SET status = 'healthy', weeks_remaining = 0 "
                "WHERE current_event_id IS NULL AND status = 'injured'"
            ))
            deleted["injury_states_reset"] = r.rowcount

            # 7. Reset fatigue to 100 for all players this season
            # (stamina drain/recovery is cumulative and not easily reversible
            # per-week, so reset to fresh state)
            r = conn.execute(sa_text(
                "DELETE FROM player_fatigue_state WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["fatigue_reset"] = r.rowcount

            # 8. Reset rotation state pointers
            conn.execute(sa_text(
                "UPDATE team_rotation_state SET current_slot = 0, "
                "last_game_id = NULL, last_updated_at = NOW()"
            ))

            # 9. Reset week simulation flags
            conn.execute(sa_text(
                "UPDATE timestamp_state SET "
                "games_a_ran = 0, games_b_ran = 0, "
                "games_c_ran = 0, games_d_ran = 0, run_games = 0 "
                "WHERE id = 1"
            ))

        # Broadcast updated timestamp
        from services.websocket_manager import ws_manager
        ws_manager.broadcast_timestamp()

        current_app.logger.info(
            f"Rolled back week {season_week} for league_year_id={league_year_id}: {deleted}"
        )

        return jsonify(
            ok=True,
            deleted=deleted,
            games_rolled_back=len(game_ids),
        ), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("rollback_week: database error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        current_app.logger.exception("rollback_week: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


@games_bp.post("/games/rollback-to-week")
def rollback_to_week():
    """
    Roll back all simulation output from target_week onward.

    Undoes game results, per-game lines, season stat accumulation,
    injuries, fatigue, financials, waivers, FA auctions, position
    usage, and transaction log from target_week through the latest
    simulated week.  Resets the timestamp to the start of target_week.

    Request body:
    {
        "league_year_id": 1,
        "target_week": 10
    }
    """
    from sqlalchemy import text as sa_text

    body = request.get_json(force=True, silent=True) or {}
    league_year_id = body.get("league_year_id")
    target_week = body.get("target_week")

    if league_year_id is None or target_week is None:
        return jsonify(error="missing_field",
                       message="league_year_id and target_week are required"), 400

    try:
        league_year_id = int(league_year_id)
        target_week = int(target_week)
    except (TypeError, ValueError) as e:
        return jsonify(error="invalid_type", message=str(e)), 400

    if target_week < 1:
        return jsonify(error="invalid_value",
                       message="target_week must be >= 1"), 400

    engine = get_engine()

    try:
        with engine.begin() as conn:
            deleted = {}

            # ── 1. Find all game_ids for weeks >= target_week ──
            game_rows = conn.execute(sa_text(
                "SELECT game_id FROM game_results "
                "WHERE season = :lyid AND season_week >= :tw"
            ), {"lyid": league_year_id, "tw": target_week}).all()
            game_ids = [int(r[0]) for r in game_rows]

            if not game_ids:
                # Nothing simulated from target_week onward — just reset timestamp
                conn.execute(sa_text(
                    "UPDATE timestamp_state SET "
                    "week = :tw, games_a_ran = 0, games_b_ran = 0, "
                    "games_c_ran = 0, games_d_ran = 0, run_games = 0 "
                    "WHERE id = 1"
                ), {"tw": target_week})

                from services.websocket_manager import ws_manager
                ws_manager.broadcast_timestamp()

                return jsonify(
                    ok=True, message="No games found from target_week onward",
                    deleted={}, games_found=0, timestamp_reset_to=target_week,
                ), 200

            # Build parameterised placeholder list for game_ids
            gid_ph = ", ".join(f":g{i}" for i in range(len(game_ids)))
            gid_params = {f"g{i}": gid for i, gid in enumerate(game_ids)}
            base_params = {"lyid": league_year_id, "tw": target_week}
            all_params = {**gid_params, **base_params}

            # Capture the earliest game_results timestamp for the target week
            # (used later for time-based deletes; must be read before we delete
            # game_results rows).
            cutoff_row = conn.execute(sa_text(
                "SELECT MIN(created_at) FROM game_results "
                "WHERE season = :lyid AND season_week = :tw"
            ), base_params).first()
            rollback_cutoff = cutoff_row[0] if cutoff_row and cutoff_row[0] else None

            # ── 2. Subtract per-game BATTING lines from season stats ──
            r = conn.execute(sa_text(f"""
                UPDATE player_batting_stats pbs
                JOIN (
                    SELECT player_id, team_id,
                        SUM(at_bats) AS at_bats, SUM(runs) AS runs,
                        SUM(hits) AS hits, SUM(doubles_hit) AS doubles_hit,
                        SUM(triples) AS triples, SUM(home_runs) AS home_runs,
                        SUM(rbi) AS rbi, SUM(walks) AS walks,
                        SUM(strikeouts) AS strikeouts,
                        SUM(stolen_bases) AS stolen_bases,
                        SUM(caught_stealing) AS caught_stealing
                    FROM game_batting_lines
                    WHERE game_id IN ({gid_ph}) AND league_year_id = :lyid
                    GROUP BY player_id, team_id
                ) gbl ON pbs.player_id = gbl.player_id
                    AND pbs.team_id = gbl.team_id
                    AND pbs.league_year_id = :lyid
                SET pbs.at_bats = GREATEST(0, pbs.at_bats - gbl.at_bats),
                    pbs.runs = GREATEST(0, pbs.runs - gbl.runs),
                    pbs.hits = GREATEST(0, pbs.hits - gbl.hits),
                    pbs.doubles_hit = GREATEST(0, pbs.doubles_hit - gbl.doubles_hit),
                    pbs.triples = GREATEST(0, pbs.triples - gbl.triples),
                    pbs.home_runs = GREATEST(0, pbs.home_runs - gbl.home_runs),
                    pbs.rbi = GREATEST(0, pbs.rbi - gbl.rbi),
                    pbs.walks = GREATEST(0, pbs.walks - gbl.walks),
                    pbs.strikeouts = GREATEST(0, pbs.strikeouts - gbl.strikeouts),
                    pbs.stolen_bases = GREATEST(0, pbs.stolen_bases - gbl.stolen_bases),
                    pbs.caught_stealing = GREATEST(0, pbs.caught_stealing - gbl.caught_stealing)
            """), all_params)
            deleted["batting_stats_decremented"] = r.rowcount

            # ── 3. Subtract per-game PITCHING lines from season stats ──
            r = conn.execute(sa_text(f"""
                UPDATE player_pitching_stats pps
                JOIN (
                    SELECT player_id, team_id,
                        SUM(games_started) AS games_started,
                        SUM(win) AS win, SUM(loss) AS loss,
                        SUM(save_recorded) AS save_recorded,
                        SUM(innings_pitched_outs) AS innings_pitched_outs,
                        SUM(hits_allowed) AS hits_allowed,
                        SUM(runs_allowed) AS runs_allowed,
                        SUM(earned_runs) AS earned_runs,
                        SUM(walks) AS walks, SUM(strikeouts) AS strikeouts,
                        SUM(home_runs_allowed) AS home_runs_allowed
                    FROM game_pitching_lines
                    WHERE game_id IN ({gid_ph}) AND league_year_id = :lyid
                    GROUP BY player_id, team_id
                ) gpl ON pps.player_id = gpl.player_id
                    AND pps.team_id = gpl.team_id
                    AND pps.league_year_id = :lyid
                SET pps.games = GREATEST(0, pps.games - 1),
                    pps.games_started = GREATEST(0, pps.games_started - gpl.games_started),
                    pps.wins = GREATEST(0, pps.wins - gpl.win),
                    pps.losses = GREATEST(0, pps.losses - gpl.loss),
                    pps.saves = GREATEST(0, pps.saves - gpl.save_recorded),
                    pps.innings_pitched_outs = GREATEST(0, pps.innings_pitched_outs - gpl.innings_pitched_outs),
                    pps.hits_allowed = GREATEST(0, pps.hits_allowed - gpl.hits_allowed),
                    pps.runs_allowed = GREATEST(0, pps.runs_allowed - gpl.runs_allowed),
                    pps.earned_runs = GREATEST(0, pps.earned_runs - gpl.earned_runs),
                    pps.walks = GREATEST(0, pps.walks - gpl.walks),
                    pps.strikeouts = GREATEST(0, pps.strikeouts - gpl.strikeouts),
                    pps.home_runs_allowed = GREATEST(0, pps.home_runs_allowed - gpl.home_runs_allowed)
            """), all_params)
            deleted["pitching_stats_decremented"] = r.rowcount

            # ── 4. Subtract per-game FIELDING lines from season stats ──
            r = conn.execute(sa_text(f"""
                UPDATE player_fielding_stats pfs
                JOIN (
                    SELECT player_id, team_id, position_code,
                        SUM(innings) AS innings,
                        SUM(putouts) AS putouts,
                        SUM(assists) AS assists,
                        SUM(errors) AS errors,
                        COUNT(*) AS game_count
                    FROM game_fielding_lines
                    WHERE game_id IN ({gid_ph}) AND league_year_id = :lyid
                    GROUP BY player_id, team_id, position_code
                ) gfl ON pfs.player_id = gfl.player_id
                    AND pfs.team_id = gfl.team_id
                    AND pfs.position_code = gfl.position_code
                    AND pfs.league_year_id = :lyid
                SET pfs.games = GREATEST(0, pfs.games - gfl.game_count),
                    pfs.innings = GREATEST(0, pfs.innings - gfl.innings),
                    pfs.putouts = GREATEST(0, pfs.putouts - gfl.putouts),
                    pfs.assists = GREATEST(0, pfs.assists - gfl.assists),
                    pfs.errors = GREATEST(0, pfs.errors - gfl.errors)
            """), all_params)
            deleted["fielding_stats_decremented"] = r.rowcount

            # ── 5. Delete per-game line tables ──
            for tbl in ("game_batting_lines", "game_pitching_lines",
                        "game_fielding_lines", "game_substitutions"):
                r = conn.execute(sa_text(
                    f"DELETE FROM {tbl} WHERE game_id IN ({gid_ph})"
                ), gid_params)
                deleted[tbl] = r.rowcount

            # ── 6. Delete game results ──
            r = conn.execute(sa_text(
                f"DELETE FROM game_results WHERE game_id IN ({gid_ph})"
            ), gid_params)
            deleted["game_results"] = r.rowcount

            # ── 7. Delete position usage for rolled-back weeks ──
            r = conn.execute(sa_text(
                "DELETE FROM player_position_usage_week "
                "WHERE league_year_id = :lyid AND season_week >= :tw"
            ), base_params)
            deleted["position_usage"] = r.rowcount

            # ── 8. Delete injuries from rolled-back games ──
            # In-game injuries (linked to gamelist_id)
            r = conn.execute(sa_text(
                f"DELETE FROM player_injury_events "
                f"WHERE gamelist_id IN ({gid_ph})"
            ), gid_params)
            deleted["injury_events_ingame"] = r.rowcount

            # Pregame injuries (gamelist_id IS NULL) created during the
            # rolled-back period — use the cutoff timestamp captured earlier
            if rollback_cutoff is not None:
                r = conn.execute(sa_text(
                    "DELETE FROM player_injury_events "
                    "WHERE league_year_id = :lyid AND gamelist_id IS NULL "
                    "AND created_at >= :cutoff"
                ), {"lyid": league_year_id, "cutoff": rollback_cutoff})
                deleted["injury_events_pregame"] = r.rowcount
            else:
                deleted["injury_events_pregame"] = 0

            # career_injuries are auto-cascade-deleted via FK on origin_event_id

            # Rebuild injury state: update to longest remaining event or delete
            conn.execute(sa_text("""
                UPDATE player_injury_state pis
                JOIN (
                    SELECT pie.player_id,
                           MAX(pie.id) AS best_event_id,
                           bw.max_weeks AS best_weeks
                    FROM player_injury_events pie
                    INNER JOIN (
                        SELECT player_id, MAX(weeks_remaining) AS max_weeks
                        FROM player_injury_events
                        WHERE weeks_remaining > 0
                        GROUP BY player_id
                    ) bw ON bw.player_id = pie.player_id
                        AND pie.weeks_remaining = bw.max_weeks
                    GROUP BY pie.player_id, bw.max_weeks
                ) best ON best.player_id = pis.player_id
                SET pis.current_event_id = best.best_event_id,
                    pis.weeks_remaining  = best.best_weeks
                WHERE pis.status = 'injured'
            """))

            # Delete state rows with no remaining active events
            r = conn.execute(sa_text("""
                DELETE pis FROM player_injury_state pis
                LEFT JOIN player_injury_events pie
                    ON pie.player_id = pis.player_id AND pie.weeks_remaining > 0
                WHERE pis.status = 'injured' AND pie.id IS NULL
            """))
            deleted["injury_states_cleaned"] = r.rowcount

            # ── 9. Delete financial ledger entries for rolled-back weeks ──
            gw_rows = conn.execute(sa_text(
                "SELECT id FROM game_weeks "
                "WHERE league_year_id = :lyid AND week_index >= :tw"
            ), base_params).all()
            gw_ids = [int(r[0]) for r in gw_rows]

            if gw_ids:
                gw_ph = ", ".join(f":gw{i}" for i in range(len(gw_ids)))
                gw_params = {f"gw{i}": gid for i, gid in enumerate(gw_ids)}
                r = conn.execute(sa_text(
                    f"DELETE FROM org_ledger_entries "
                    f"WHERE game_week_id IN ({gw_ph})"
                ), gw_params)
                deleted["org_ledger_entries"] = r.rowcount
            else:
                deleted["org_ledger_entries"] = 0

            # ── 10. Delete waiver claims from rolled-back weeks ──
            r = conn.execute(sa_text(
                "DELETE FROM waiver_claims "
                "WHERE league_year_id = :lyid AND placed_week >= :tw"
            ), base_params)
            deleted["waiver_claims"] = r.rowcount

            # ── 11. Delete FA auctions entered during rolled-back weeks ──
            # Offers first (FK), then auctions
            r = conn.execute(sa_text(
                "DELETE ao FROM fa_auction_offers ao "
                "JOIN fa_auction a ON a.id = ao.auction_id "
                "WHERE a.league_year_id = :lyid AND a.entered_week >= :tw"
            ), base_params)
            deleted["fa_auction_offers"] = r.rowcount

            r = conn.execute(sa_text(
                "DELETE FROM fa_auction "
                "WHERE league_year_id = :lyid AND entered_week >= :tw"
            ), base_params)
            deleted["fa_auction"] = r.rowcount

            # Player demands and market history created during the period
            if rollback_cutoff is not None:
                r = conn.execute(sa_text(
                    "DELETE FROM player_demands "
                    "WHERE league_year_id = :lyid AND computed_at >= :cutoff"
                ), {"lyid": league_year_id, "cutoff": rollback_cutoff})
                deleted["player_demands"] = r.rowcount

                r = conn.execute(sa_text(
                    "DELETE FROM fa_market_history "
                    "WHERE league_year_id = :lyid AND created_at >= :cutoff"
                ), {"lyid": league_year_id, "cutoff": rollback_cutoff})
                deleted["fa_market_history"] = r.rowcount
            else:
                deleted["player_demands"] = 0
                deleted["fa_market_history"] = 0

            # ── 12. Delete transaction log entries from rolled-back period ──
            if rollback_cutoff is not None:
                r = conn.execute(sa_text(
                    "DELETE FROM transaction_log "
                    "WHERE league_year_id = :lyid AND executed_at >= :cutoff"
                ), {"lyid": league_year_id, "cutoff": rollback_cutoff})
                deleted["transaction_log"] = r.rowcount
            else:
                deleted["transaction_log"] = 0

            # ── 13. Reset fatigue (cumulative — not reversible per-week) ──
            r = conn.execute(sa_text(
                "DELETE FROM player_fatigue_state "
                "WHERE league_year_id = :lyid"
            ), {"lyid": league_year_id})
            deleted["fatigue_reset"] = r.rowcount

            # ── 14. Reset rotation state ──
            conn.execute(sa_text(
                "UPDATE team_rotation_state SET current_slot = 0, "
                "last_game_id = NULL, last_updated_at = NOW()"
            ))

            # ── 15. Reset timestamp to start of target_week ──
            conn.execute(sa_text(
                "UPDATE timestamp_state SET "
                "week = :tw, games_a_ran = 0, games_b_ran = 0, "
                "games_c_ran = 0, games_d_ran = 0, run_games = 0 "
                "WHERE id = 1"
            ), {"tw": target_week})

            # ── 16. Refresh listed positions based on post-rollback state ──
            try:
                from services.listed_position import refresh_all_teams
                refresh_all_teams(conn, league_year_id)
                deleted["listed_positions_refreshed"] = True
            except Exception:
                current_app.logger.exception(
                    "rollback_to_week: listed position refresh failed"
                )
                deleted["listed_positions_refreshed"] = False

        # Broadcast updated timestamp
        from services.websocket_manager import ws_manager
        ws_manager.broadcast_timestamp()

        current_app.logger.info(
            f"Rolled back to week {target_week} for "
            f"league_year_id={league_year_id}: {deleted}"
        )

        return jsonify(
            ok=True,
            deleted=deleted,
            games_rolled_back=len(game_ids),
            timestamp_reset_to=target_week,
        ), 200

    except SQLAlchemyError as e:
        current_app.logger.exception("rollback_to_week: database error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        current_app.logger.exception("rollback_to_week: unexpected error")
        return jsonify(error="unexpected_error", message=str(e)), 500


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

        deleted = {}

        # Resolve season_id from league_year_id
        with engine.connect() as conn:
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

        # Helper: fresh connection per step so a dropped conn doesn't kill everything
        def _wipe(label, sql, params=None):
            with engine.begin() as c:
                r = c.execute(sa_text(sql), params or {})
                deleted[label] = r.rowcount

        # Chunked delete for very large tables — deletes BATCH_SIZE rows at a time
        def _wipe_chunked(label, table, where_clause, params, batch=5000):
            total = 0
            while True:
                with engine.begin() as c:
                    r = c.execute(sa_text(
                        f"DELETE FROM {table} WHERE {where_clause} LIMIT {batch}"
                    ), params)
                    total += r.rowcount
                    if r.rowcount < batch:
                        break
            deleted[label] = total

        # 1. game_results — chunked with small batch (rows contain ~1MB JSON each)
        gr_where = "season IN :season_ids"
        gr_params = {"season_ids": tuple(season_ids) if season_ids else (0,)}
        if league_level is not None:
            gr_where += " AND league_level = :league_level"
            gr_params["league_level"] = league_level
        _wipe_chunked("game_results", "game_results", gr_where, gr_params, batch=500)

        # 2-4. Per-game line tables — chunked
        for tbl_name in ("game_batting_lines", "game_pitching_lines",
                         "game_substitutions"):
            _wipe_chunked(tbl_name, tbl_name,
                          "league_year_id = :lyid", {"lyid": league_year_id})

        # 5-7. Player stat tables — chunked (can be large)
        for tbl_name in ("player_batting_stats", "player_pitching_stats",
                         "player_fielding_stats"):
            _wipe_chunked(tbl_name, tbl_name,
                          "league_year_id = :lyid", {"lyid": league_year_id})

        # 5. Financial ledger — chunked
        _wipe_chunked("org_ledger_entries", "org_ledger_entries",
                      "league_year_id = :lyid", {"lyid": league_year_id})

        # 6. Position usage — chunked
        _wipe_chunked("player_position_usage_week", "player_position_usage_week",
                      "league_year_id = :lyid", {"lyid": league_year_id})

        # 6. Injury events (FK SET NULL cascades to player_injury_state)
        _wipe("player_injury_events",
              "DELETE FROM player_injury_events WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 7. Reset orphaned injury states to healthy
        _wipe("injury_states_reset",
              "UPDATE player_injury_state "
              "SET status = 'healthy', weeks_remaining = 0 "
              "WHERE current_event_id IS NULL AND status = 'injured'")

        # 8. Fatigue state
        _wipe("player_fatigue_state",
              "DELETE FROM player_fatigue_state WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 8b. Scouting actions — only reset attribute unlocks
        _wipe("scouting_actions_attrs",
              "DELETE FROM scouting_actions WHERE league_year_id = :lyid "
              "AND action_type IN ('hs_report', 'draft_attrs_fuzzed', "
              "'draft_attrs_precise', 'pro_attrs_precise')",
              {"lyid": league_year_id})

        # 8c. Scouting budgets
        _wipe("scouting_budgets",
              "DELETE FROM scouting_budgets WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 8d-8h. Recruiting data — NOT wiped on season wipe.

        # 8i. Listed positions
        _wipe("player_listed_position",
              "DELETE FROM player_listed_position WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 8j. Playoff series + bracket
        _wipe("playoff_series",
              "DELETE FROM playoff_series WHERE league_year_id = :lyid",
              {"lyid": league_year_id})
        _wipe("cws_bracket",
              "DELETE FROM cws_bracket WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # Remove playoff/allstar/wbc gamelist entries (regular schedule preserved)
        if season_ids:
            sid_csv = ",".join(str(s) for s in season_ids)
            for gt in ("playoff", "allstar", "wbc"):
                _wipe(f"{gt}_gamelist",
                      f"DELETE FROM gamelist WHERE game_type = '{gt}' "
                      f"AND season IN ({sid_csv})")

        # 8k. Special events (allstar + wbc) — rosters first (FK), then events
        _wipe("special_event_rosters",
              "DELETE ser FROM special_event_rosters ser "
              "JOIN special_events se ON se.id = ser.event_id "
              "WHERE se.league_year_id = :lyid",
              {"lyid": league_year_id})
        _wipe("special_events",
              "DELETE FROM special_events WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 8l. WBC teams — cascade-deleted by special_events FK, no explicit wipe needed

        # 8m. Transaction log
        _wipe_chunked("transaction_log", "transaction_log",
                      "league_year_id = :lyid", {"lyid": league_year_id})

        # 8n. FA auction system (offers first due to FK, then auctions, demands, market history)
        _wipe("fa_auction_offers",
              "DELETE ao FROM fa_auction_offers ao "
              "JOIN fa_auction a ON a.id = ao.auction_id "
              "WHERE a.league_year_id = :lyid",
              {"lyid": league_year_id})
        _wipe("fa_auction",
              "DELETE FROM fa_auction WHERE league_year_id = :lyid",
              {"lyid": league_year_id})
        _wipe("player_demands",
              "DELETE FROM player_demands WHERE league_year_id = :lyid",
              {"lyid": league_year_id})
        _wipe("fa_market_history",
              "DELETE FROM fa_market_history WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 8o. Waiver claims
        _wipe("waiver_claims",
              "DELETE FROM waiver_claims WHERE league_year_id = :lyid",
              {"lyid": league_year_id})

        # 9. Reset rotation state
        _wipe("rotation_states_reset",
              "UPDATE team_rotation_state SET current_slot = 0, "
              "last_game_id = NULL, last_updated_at = NOW()")

        # 10. Reset timestamp
        _wipe("timestamp_reset",
              "UPDATE timestamp_state SET "
              "week = 1, games_a_ran = 0, games_b_ran = 0, "
              "games_c_ran = 0, games_d_ran = 0, run_games = 0 "
              "WHERE id = 1")

        # 11. Reclaim disk space (each OPTIMIZE is its own implicit commit)
        optimize_tables = [
            "game_results", "game_batting_lines", "game_pitching_lines",
            "game_substitutions",
            "player_batting_stats", "player_pitching_stats",
            "player_fielding_stats", "player_position_usage_week",
            "player_injury_events", "player_fatigue_state",
            "org_ledger_entries",
            "scouting_actions", "scouting_budgets",
            "player_listed_position",
            "playoff_series", "cws_bracket",
            "special_events", "special_event_rosters",
            "transaction_log",
            "fa_auction_offers", "fa_auction", "player_demands",
            "fa_market_history", "waiver_claims",
        ]
        for tbl in optimize_tables:
            try:
                with engine.begin() as c:
                    c.execute(sa_text(f"OPTIMIZE TABLE {tbl}"))
            except Exception:
                pass  # OPTIMIZE is best-effort
        deleted["optimized_tables"] = len(optimize_tables)

        # 12. Re-run year-start books (media payouts + bonuses)
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
                       gbl.position_code, gbl.batting_order,
                       gbl.at_bats, gbl.runs, gbl.hits, gbl.doubles_hit,
                       gbl.triples, gbl.home_runs, gbl.inside_the_park_hr,
                       gbl.rbi, gbl.walks,
                       gbl.strikeouts, gbl.stolen_bases, gbl.caught_stealing,
                       gbl.plate_appearances, gbl.hbp
                FROM game_batting_lines gbl
                JOIN simbbPlayers p ON p.id = gbl.player_id
                WHERE gbl.game_id = :gid
                ORDER BY gbl.team_id, gbl.batting_order, gbl.id
            """), {"gid": game_id}).mappings().all()

            # 3. Pitching lines
            pit_rows = conn.execute(sa_text("""
                SELECT gpl.player_id, gpl.team_id,
                       p.firstName, p.lastName,
                       gpl.pitch_appearance_order,
                       gpl.games_started, gpl.win, gpl.loss, gpl.save_recorded,
                       gpl.hold, gpl.blown_save, gpl.quality_start,
                       gpl.innings_pitched_outs, gpl.hits_allowed, gpl.runs_allowed,
                       gpl.earned_runs, gpl.walks, gpl.strikeouts,
                       gpl.home_runs_allowed, gpl.inside_the_park_hr_allowed,
                       gpl.pitches_thrown, gpl.balls, gpl.strikes,
                       gpl.hbp, gpl.wildpitches
                FROM game_pitching_lines gpl
                JOIN simbbPlayers p ON p.id = gpl.player_id
                WHERE gpl.game_id = :gid
                ORDER BY gpl.team_id, gpl.pitch_appearance_order, gpl.id
            """), {"gid": game_id}).mappings().all()

            # 4. Substitutions
            sub_rows = conn.execute(sa_text("""
                SELECT gs.inning, gs.half, gs.sub_type,
                       gs.player_in_id, pin.firstName AS in_first, pin.lastName AS in_last,
                       gs.player_out_id, pout.firstName AS out_first, pout.lastName AS out_last,
                       gs.new_position,
                       gs.entry_score_diff, gs.entry_runners_on,
                       gs.entry_inning, gs.entry_outs,
                       gs.entry_is_save_situation
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
                "pos": r.get("position_code") or None,
                "batting_order": int(r.get("batting_order") or 0),
                "pa": int(r.get("plate_appearances") or 0),
                "ab": int(r["at_bats"]), "r": int(r["runs"]),
                "h": int(r["hits"]), "2b": int(r["doubles_hit"]),
                "3b": int(r["triples"]), "hr": int(r["home_runs"]),
                "itphr": int(r["inside_the_park_hr"]),
                "rbi": int(r["rbi"]), "bb": int(r["walks"]),
                "hbp": int(r.get("hbp") or 0),
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
                "appearance_order": int(r.get("pitch_appearance_order") or 0),
                "gs": int(r["games_started"]),
                "ip": ip, "h": int(r["hits_allowed"]),
                "r": int(r["runs_allowed"]), "er": int(r["earned_runs"]),
                "bb": int(r["walks"]), "so": int(r["strikeouts"]),
                "hr": int(r["home_runs_allowed"]),
                "itphr": int(r["inside_the_park_hr_allowed"]),
                "pc": int(r.get("pitches_thrown") or 0),
                "balls": int(r.get("balls") or 0),
                "strikes": int(r.get("strikes") or 0),
                "hbp": int(r.get("hbp") or 0),
                "wp": int(r.get("wildpitches") or 0),
                "dec": dec,
                "hold": int(r.get("hold") or 0),
                "blown_save": int(r.get("blown_save") or 0),
                "quality_start": int(r.get("quality_start") or 0),
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

        substitutions = []
        for s in sub_rows:
            sub_obj = {
                "inning": int(s["inning"]),
                "half": s["half"],
                "type": s["sub_type"],
                "player_in": {"id": int(s["player_in_id"]),
                               "name": f"{s['in_first']} {s['in_last']}"},
                "player_out": {"id": int(s["player_out_id"]),
                                "name": f"{s['out_first']} {s['out_last']}"},
                "new_position": s["new_position"],
            }
            # Entry-state context (present on pitching changes)
            if s.get("entry_score_diff") is not None:
                sub_obj["entry_score_diff"] = int(s["entry_score_diff"])
                sub_obj["entry_runners_on"] = int(s.get("entry_runners_on") or 0)
                sub_obj["entry_inning"] = int(s.get("entry_inning") or 0)
                sub_obj["entry_outs"] = int(s.get("entry_outs") or 0)
                sub_obj["entry_is_save_situation"] = bool(s.get("entry_is_save_situation"))
            substitutions.append(sub_obj)

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
    Background worker: simulate every week for ALL league levels.

    Processes all levels in a single build_week_payloads() call per week,
    which parallelises engine calls across levels via ThreadPoolExecutor.
    After all levels complete, runs weekly processing (injuries, finances,
    waivers, FA auction, position refresh).
    """
    import logging
    from sqlalchemy import text as _sa_text

    logger = logging.getLogger(__name__)

    LEVEL_NAMES = {9: "MLB", 8: "AAA", 7: "AA", 6: "High-A",
                   5: "A", 4: "Scraps", 3: "College"}

    store = get_task_store()
    store.set_running(task_id)

    engine = get_engine()
    total_games = 0
    weeks_completed = 0

    # Resolve league_year (the year number) from league_year_id
    with engine.connect() as _conn:
        _ly_row = _conn.execute(
            _sa_text("SELECT league_year FROM league_years WHERE id = :id"),
            {"id": league_year_id},
        ).first()
    league_year = int(_ly_row[0]) if _ly_row else None

    try:
        for week in range(start_week, end_week + 1):
            # Update timestamp to current week
            update_timestamp({"week": week, "run_games": True}, broadcast=True)

            # --- Run ALL levels for this week in one call ---
            from services.timing_log import timed_stage, log_timing
            import time as _time

            try:
                with timed_stage("build_week_payloads", week=week,
                                 detail="all levels"):
                    with engine.connect() as conn:
                        result = build_week_payloads(
                            conn=conn,
                            league_year_id=league_year_id,
                            season_week=week,
                            league_level=None,
                            simulate=True,
                        )

                week_games = result.get("total_games", 0)
                total_games += week_games

                subweeks = result.get("subweeks", {})
                for sw_key in ["a", "b", "c", "d"]:
                    if subweeks.get(sw_key):
                        set_subweek_completed(sw_key, broadcast=False)
            except ValueError as ve:
                logger.debug(
                    "run_all_levels: no games for week %d: %s",
                    week, ve,
                )
            except Exception as ex:
                logger.exception(
                    "run_all_levels: error at week %d: %s",
                    week, ex,
                )
                raise

            weeks_completed += 1
            store.set_progress(task_id, weeks_completed)

            set_run_games(False, broadcast=False)

            # --- Weekly processing (once per week, after all levels) ---
            _wp_t0 = _time.monotonic()

            try:
                from bootstrap import invalidate_season_context
                invalidate_season_context()
            except Exception:
                pass

            with timed_stage("weekly_tick_injuries", week=week):
                try:
                    healed = _tick_injuries(engine)
                except Exception as inj_err:
                    logger.warning(
                        "run_all_levels: injury tick failed at week %d: %s",
                        week, inj_err,
                    )

            if league_year is not None:
                with timed_stage("weekly_books", week=week):
                    try:
                        from financials.books import run_week_books
                        run_week_books(engine, league_year, week)
                    except Exception as books_err:
                        logger.warning(
                            "run_all_levels: week books failed at week %d: %s",
                            week, books_err,
                        )

            with timed_stage("weekly_waivers", week=week):
                try:
                    from services.waivers import process_expired_waivers
                    with engine.begin() as conn:
                        process_expired_waivers(conn, week, league_year_id)
                except Exception as waiver_err:
                    logger.warning(
                        "run_all_levels: waiver processing failed at week %d: %s",
                        week, waiver_err,
                    )

            with timed_stage("weekly_fa_auction", week=week):
                try:
                    from services.fa_auction import advance_auction_phases
                    with engine.begin() as conn:
                        advance_auction_phases(conn, week, league_year_id)
                except Exception as auc_err:
                    logger.warning(
                        "run_all_levels: FA auction failed at week %d: %s",
                        week, auc_err,
                    )

            with timed_stage("weekly_listed_positions", week=week):
                try:
                    from services.listed_position import refresh_all_teams
                    with engine.begin() as conn:
                        refresh_all_teams(conn, league_year_id)
                except Exception:
                    logger.exception(
                        "run_all_levels: listed position refresh failed at week %d",
                        week,
                    )

            log_timing("weekly_processing_total",
                       _time.monotonic() - _wp_t0, week=week)

            logger.info(
                f"run_all_levels task {task_id}: week {week} complete — "
                f"{total_games} total games so far"
            )

        summary = {
            "league_year_id": league_year_id,
            "weeks_simulated": end_week - start_week + 1,
            "total_games": total_games,
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
            f"run_all_levels task {task_id} failed at week "
            f"{start_week + weeks_completed}"
        )
        store.set_failed(task_id, str(e))


@games_bp.post("/games/run-season-all")
def run_season_all():
    """
    Start a background task to simulate ALL league levels for a season.

    Iterates week-by-week, running all levels (9→3) per week with full
    weekly processing (injuries, finances, waivers, FA auction, positions).

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

    store = get_task_store()
    task_data = store.create_task("run_all_levels", total=total_weeks, metadata={
        "league_year_id": league_year_id,
        "start_week": start_week,
        "end_week": end_week,
        "levels": "all (parallel)",
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
        total=total_weeks,
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
