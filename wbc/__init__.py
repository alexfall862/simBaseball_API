# wbc/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.wbc import (
    identify_eligible_countries,
    create_wbc_event,
    generate_wbc_rosters,
    generate_pool_games,
    process_pool_results,
    generate_knockout_bracket,
    advance_wbc_knockout,
    cleanup_wbc,
    get_wbc_teams,
    get_wbc_rosters,
)

wbc_bp = Blueprint("wbc", __name__)


@wbc_bp.get("/wbc/eligible-countries")
def eligible_countries():
    """Get list of countries eligible for WBC (>=26 players)."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = identify_eligible_countries(conn)
        return jsonify(countries=result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/create")
def create_event():
    """
    Create a WBC event with virtual teams.
    Body: {league_year_id, countries?: [str]}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    countries = data.get("countries")

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = create_wbc_event(conn, league_year_id, countries)
        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/generate-rosters")
def gen_rosters(event_id: int):
    """Generate rosters for all WBC teams."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = generate_wbc_rosters(conn, event_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.get("/wbc/<int:event_id>/teams")
def teams(event_id: int):
    """Get all WBC teams for an event."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_wbc_teams(conn, event_id)
        return jsonify(teams=result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.get("/wbc/<int:event_id>/rosters")
def rosters(event_id: int):
    """Get rosters for all WBC teams."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_wbc_rosters(conn, event_id)
        return jsonify(rosters=result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/generate-pool-games")
def gen_pool_games(event_id: int):
    """Generate round-robin pool play games."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = generate_pool_games(conn, event_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/process-pool-results")
def pool_results(event_id: int):
    """Process pool play results and update standings."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = process_pool_results(conn, event_id)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/generate-knockout")
def gen_knockout(event_id: int):
    """Generate knockout bracket from pool results."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = generate_knockout_bracket(conn, event_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/advance-knockout")
def advance_ko(event_id: int):
    """Advance knockout rounds."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = advance_wbc_knockout(conn, event_id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@wbc_bp.post("/wbc/<int:event_id>/cleanup")
def cleanup(event_id: int):
    """Clean up virtual teams after WBC completion."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = cleanup_wbc(conn, event_id)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500
