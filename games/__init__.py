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
