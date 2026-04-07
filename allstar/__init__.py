# allstar/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.allstar import (
    create_allstar_event,
    simulate_allstar_game,
    get_event_rosters,
    get_allstar_results,
)

allstar_bp = Blueprint("allstar", __name__)


@allstar_bp.post("/allstar/create")
def create_event():
    """
    Create an All-Star event with manually specified rosters.
    Body: {
      league_year_id, league_level?,
      home: {label, starting_pitchers[], relief_pitchers[], lineup[{player_id,position}], bench[]},
      away: {label, starting_pitchers[], relief_pitchers[], lineup[{player_id,position}], bench[]}
    }
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data.get("league_level", 9))
    home = data["home"]
    away = data["away"]

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = create_allstar_event(
                conn, league_year_id, league_level, home, away,
            )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@allstar_bp.post("/allstar/<int:event_id>/simulate")
def simulate_event(event_id: int):
    """
    Simulate the All-Star game ad-hoc (not part of the weekly schedule).
    """
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = simulate_allstar_game(conn, event_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@allstar_bp.get("/allstar/<int:event_id>/rosters")
def get_rosters(event_id: int):
    """Get rosters for an All-Star event."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_event_rosters(conn, event_id)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@allstar_bp.get("/allstar/<int:event_id>/results")
def get_results(event_id: int):
    """Get results for a completed All-Star event."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_allstar_results(conn, event_id)
        if result is None:
            return jsonify(error="not_found", message="Event not found"), 404
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500
