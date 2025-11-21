# games/__init__.py

from flask import Blueprint, jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.game_payload import build_game_payload

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
