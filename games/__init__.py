# games/__init__.py

from flask import Blueprint, jsonify, current_app, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.game_payload import build_game_payload, build_week_payloads
from services.timestamp import (
    set_run_games,
    set_subweek_completed,
    update_timestamp,
    advance_week,
    reset_week_games,
)

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
    if not request.json:
        return jsonify(
            error="invalid_request",
            message="Request body must be JSON"
        ), 400

    league_year_id = request.json.get("league_year_id")
    season_week = request.json.get("season_week")
    league_level = request.json.get("league_level")

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
        from services.timestamp import get_current_timestamp

        timestamp = get_current_timestamp()

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
