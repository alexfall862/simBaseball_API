# awards/__init__.py
"""
Awards API — admin entry of player trophies + read endpoints for player career
awards and per-season award boards.

Endpoints (all under /api/v1):
    GET    /awards/types                  — award catalog (labels/config for UI)
    GET    /awards/player/<player_id>     — one player's career awards
    GET    /awards/season/<league_year_id>— a season's full award slate
    POST   /awards                        — record/update one award (admin)
    DELETE /awards/<award_id>             — revoke one award (admin)
"""

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.awards import (
    list_award_types,
    record_award,
    revoke_award,
    get_player_awards,
    get_season_awards,
)

awards_bp = Blueprint("awards", __name__)


@awards_bp.get("/awards/types")
def get_award_types():
    """Return the catalog of award types (codes, labels, config flags)."""
    engine = get_engine()
    try:
        with engine.begin() as conn:  # begin(): first call may create/seed tables
            return jsonify(award_types=list_award_types(conn)), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@awards_bp.get("/awards/player/<int:player_id>")
def get_awards_for_player(player_id: int):
    """All awards a player has won/received across every season."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            return jsonify(get_player_awards(conn, player_id)), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@awards_bp.get("/awards/season/<int:league_year_id>")
def get_awards_for_season(league_year_id: int):
    """A season's full award slate, grouped by award."""
    league_level = request.args.get("league_level", default=9, type=int)
    engine = get_engine()
    try:
        with engine.begin() as conn:
            return jsonify(get_season_awards(conn, league_year_id, league_level)), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@awards_bp.post("/awards")
def post_award():
    """
    Record (or update) a single award.

    Body: {
      player_id, league_year_id, award_code,
      sub_league?      ("AL"/"NL", required for league-split awards),
      position_code?   (required for per-position awards: silver_slugger/gold_glove),
      rank?            (default 1 = winner; >1 = finalist),
      is_winner?, league_level? (default 9), team_id? (auto-snapshotted if omitted),
      vote_points?, vote_share?, metadata?, created_by?
    }
    """
    data = request.get_json(force=True) or {}
    try:
        player_id = int(data["player_id"])
        league_year_id = int(data["league_year_id"])
        award_code = str(data["award_code"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="validation_error",
                       message="player_id, league_year_id, award_code are required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = record_award(
                conn,
                player_id=player_id,
                league_year_id=league_year_id,
                award_code=award_code,
                sub_league=data.get("sub_league", ""),
                position_code=data.get("position_code", ""),
                rank=int(data.get("rank", 1)),
                is_winner=data.get("is_winner"),
                league_level=int(data.get("league_level", 9)),
                team_id=data.get("team_id"),
                vote_points=data.get("vote_points"),
                vote_share=data.get("vote_share"),
                metadata=data.get("metadata"),
                created_by=data.get("created_by"),
            )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@awards_bp.delete("/awards/<int:award_id>")
def delete_award(award_id: int):
    """Revoke (delete) a single award row."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            removed = revoke_award(conn, award_id)
        if not removed:
            return jsonify(error="not_found", message="Award not found"), 404
        return jsonify(deleted=True, award_id=award_id), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500
