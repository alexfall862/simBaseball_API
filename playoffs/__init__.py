# playoffs/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.playoffs import (
    determine_mlb_playoff_field,
    create_mlb_bracket,
    determine_milb_playoff_field,
    create_milb_bracket,
    determine_cws_field,
    create_cws_bracket,
    update_series_after_game,
    advance_round,
    advance_cws_round,
    get_bracket,
    get_pending_playoff_games,
    process_completed_playoff_games,
    wipe_playoffs,
)

playoffs_bp = Blueprint("playoffs", __name__)


@playoffs_bp.get("/special-events")
def list_special_events():
    """
    List all special events, optionally filtered by league_year_id and/or type.
    Also returns playoff status per league level.

    Query params:
      league_year_id (optional) — filter to a specific league year
      event_type     (optional) — "allstar", "wbc", or "playoff"
    """
    league_year_id = request.args.get("league_year_id", type=int)
    event_type = request.args.get("event_type")

    engine = get_engine()
    try:
        with engine.connect() as conn:
            events = []

            # Special events (allstar, wbc)
            if event_type in (None, "allstar", "wbc"):
                conditions = []
                params = {}
                if league_year_id is not None:
                    conditions.append("league_year_id = :lyid")
                    params["lyid"] = league_year_id
                if event_type is not None and event_type != "playoff":
                    conditions.append("event_type = :etype")
                    params["etype"] = event_type

                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                rows = conn.execute(sa_text(f"""
                    SELECT id, league_year_id, event_type, status,
                           created_at, completed_at
                    FROM special_events
                    {where}
                    ORDER BY created_at DESC
                """), params).mappings().all()

                for r in rows:
                    events.append({
                        "id": int(r["id"]),
                        "league_year_id": int(r["league_year_id"]),
                        "event_type": r["event_type"],
                        "status": r["status"],
                        "created_at": str(r["created_at"]) if r["created_at"] else None,
                        "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
                    })

            # Playoff status per level (derived from playoff_series)
            if event_type in (None, "playoff"):
                ps_conditions = []
                ps_params = {}
                if league_year_id is not None:
                    ps_conditions.append("league_year_id = :lyid")
                    ps_params["lyid"] = league_year_id

                ps_where = ("WHERE " + " AND ".join(ps_conditions)) if ps_conditions else ""
                ps_rows = conn.execute(sa_text(f"""
                    SELECT league_year_id, league_level,
                           COUNT(*) AS total_series,
                           SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS completed,
                           MAX(round) AS latest_round,
                           MAX(CASE WHEN winner_team_id IS NOT NULL THEN 1 ELSE 0 END) AS has_winner
                    FROM playoff_series
                    {ps_where}
                    GROUP BY league_year_id, league_level
                    ORDER BY league_year_id DESC, league_level DESC
                """), ps_params).mappings().all()

                for r in ps_rows:
                    total = int(r["total_series"])
                    completed = int(r["completed"])
                    events.append({
                        "id": None,
                        "league_year_id": int(r["league_year_id"]),
                        "event_type": "playoff",
                        "league_level": int(r["league_level"]),
                        "status": "complete" if total == completed else "in_progress",
                        "total_series": total,
                        "completed_series": completed,
                        "latest_round": r["latest_round"],
                        "created_at": None,
                        "completed_at": None,
                    })

        return jsonify(events=events), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/generate")
def generate_playoffs():
    """
    Generate playoff bracket for a given league level.
    Body: {league_year_id, league_level, start_week?}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])
    start_week = int(data.get("start_week", 53 if league_level == 9 else 40))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            if league_level == 9:
                field = determine_mlb_playoff_field(conn, league_year_id)
                result = create_mlb_bracket(conn, league_year_id, field, start_week)
                result["field"] = field
            elif league_level == 3:
                field = determine_cws_field(conn, league_year_id)
                result = create_cws_bracket(conn, league_year_id, field, start_week)
                result["field"] = field
            elif 5 <= league_level <= 8:
                field = determine_milb_playoff_field(conn, league_year_id, league_level)
                result = create_milb_bracket(
                    conn, league_year_id, league_level, field, start_week
                )
                result["field"] = field
            else:
                return jsonify(error="invalid_level",
                               message=f"Level {league_level} has no playoff format"), 400

        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/bracket/<int:league_year_id>/<int:league_level>")
def get_bracket_endpoint(league_year_id: int, league_level: int):
    """Get full bracket state."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_bracket(conn, league_year_id, league_level)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/advance")
def advance_playoffs():
    """
    Advance to next round after current round completes.
    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            if league_level == 3:
                result = advance_cws_round(conn, league_year_id)
            else:
                result = advance_round(conn, league_year_id, league_level)

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/update-series")
def update_series():
    """
    Update a series after a game completes.
    Body: {game_id}
    """
    data = request.get_json(force=True)
    game_id = int(data["game_id"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = update_series_after_game(conn, game_id)
        if result is None:
            return jsonify(message="Not a playoff game"), 200
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/pending-games/<int:league_year_id>/<int:league_level>")
def pending_games(league_year_id: int, league_level: int):
    """
    Get all pending (unsimulated) playoff gamelist entries for active/pending series.
    Useful for the admin UI to show which games are next.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            games = get_pending_playoff_games(conn, league_year_id, league_level)
        return jsonify(games=games), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/process-results")
def process_results():
    """
    Scan for completed playoff games that haven't been tracked in playoff_series
    yet and process them. This is a catch-up mechanism for games simulated via
    the normal simulate-week flow.

    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            updates = process_completed_playoff_games(
                conn, league_year_id, league_level
            )
        return jsonify(updates=updates, processed=len(updates)), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/wipe")
def wipe():
    """
    Wipe all playoff data for a given league year and level.
    Removes series, games, results, and per-game stat lines.
    Season-accumulated stats and stamina are left untouched.

    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = wipe_playoffs(conn, league_year_id, league_level)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500
