# players/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine
import logging

players_bp = Blueprint("players", __name__)


def _reflect_players_table():
    """Reflect the simbbPlayers table and cache it on the blueprint."""
    if not hasattr(players_bp, "_players_table"):
        engine = get_engine()
        metadata = MetaData()
        players_bp._players_table = Table(
            "simbbPlayers",
            metadata,
            autoload_with=engine,
        )
    return players_bp._players_table


@players_bp.get("/players")
def get_players():
    """
    Return all players, or at least their IDs.
    """
    try:
        engine = get_engine()
        players_table = _reflect_players_table()

        stmt = select(players_table.c.id).order_by(players_table.c.id)

        with engine.connect() as conn:
            rows = conn.execute(stmt).all()

        logging.getLogger("app").info("get_players: fetched %d rows", len(rows))
        return jsonify([row[0] for row in rows]), 200
    except SQLAlchemyError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "db_unavailable",
                        "message": "Database temporarily unavailable",
                    }
                }
            ),
            503,
        )


# NOTE: GET /players/<int:player_id>/ was deleted in the canonical displayovr
# refactor. It was a parallel pipeline that returned the raw simbbPlayers row
# (including stale stored displayovr) with bespoke fog-of-war that bypassed
# the canonical compute_displayovr() pipeline. Use one of these instead:
#   - GET /api/v1/scouting/player/<int:player_id>?org_id=&league_year_id=
#   - GET /api/v1/rosters/team/<int:team_id>?viewing_org_id=
#   - GET /api/v1/bootstrap/landing/<int:org_id>
