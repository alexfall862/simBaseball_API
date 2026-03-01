# player_ops/__init__.py
"""
Player operations blueprint — generation and progression endpoints.
All endpoints under /player-ops/.
"""

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from services.player_engine_svc import (
    svc_generate_players,
    svc_progress_single,
    svc_progress_all,
    svc_seed_table_status,
)

player_ops_bp = Blueprint("player_ops", __name__)


# ── Generation ────────────────────────────────────────────────────────

@player_ops_bp.post("/player-ops/generate")
def api_generate_players():
    """Generate new players.  Body: {count: int, age?: int}"""
    data = request.get_json(silent=True) or {}
    count = data.get("count", 1)
    age = data.get("age", 15)

    if not isinstance(count, int) or count < 1 or count > 500:
        return jsonify(error="bad_request", message="count must be 1-500"), 400
    if not isinstance(age, int) or age < 14 or age > 45:
        return jsonify(error="bad_request", message="age must be 14-45"), 400

    try:
        players = svc_generate_players(count, age=age)
        summary = [
            {
                "id": p["id"],
                "firstname": p["firstname"],
                "lastname": p["lastname"],
                "ptype": p["ptype"],
                "age": p["age"],
                "area": p["area"],
            }
            for p in players
        ]
        return jsonify(created=len(summary), players=summary), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error during generation"), 500


# ── Progression ───────────────────────────────────────────────────────

@player_ops_bp.post("/player-ops/progress/<int:player_id>")
def api_progress_player(player_id: int):
    """Progress a single player by one year."""
    try:
        result = svc_progress_single(player_id)
        return jsonify(result), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error during progression"), 500


@player_ops_bp.post("/player-ops/progress-all")
def api_progress_all():
    """Batch-progress all players.  Body: {max_age?: int}"""
    data = request.get_json(silent=True) or {}
    max_age = data.get("max_age", 45)

    if not isinstance(max_age, int) or max_age < 16 or max_age > 60:
        return jsonify(error="bad_request", message="max_age must be 16-60"), 400

    try:
        result = svc_progress_all(max_age=max_age)
        return jsonify(result), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error during batch progression"), 500


# ── Seed table status ─────────────────────────────────────────────────

@player_ops_bp.get("/player-ops/seed-status")
def api_seed_status():
    """Return row counts for the 7 player-engine seed tables."""
    try:
        status = svc_seed_table_status()
        return jsonify(status), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500
