# allstar/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.allstar import (
    create_allstar_event,
    update_roster,
    get_event_rosters,
    get_allstar_results,
)

allstar_bp = Blueprint("allstar", __name__)


@allstar_bp.post("/allstar/create")
def create_event():
    """
    Create an All-Star event with auto-generated rosters.
    Body: {league_year_id}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = create_allstar_event(conn, league_year_id)
        return jsonify(result), 201
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


@allstar_bp.put("/allstar/<int:event_id>/rosters")
def modify_rosters(event_id: int):
    """
    Admin roster overrides.
    Body: {changes: [{action: "add"/"remove", player_id, team_label?, position_code?}]}
    """
    data = request.get_json(force=True)
    changes = data.get("changes", [])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = update_roster(conn, event_id, changes)
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
