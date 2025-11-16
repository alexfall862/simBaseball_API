# players/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

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


def _row_to_dict(row):
    # Generic: handles 100+ columns without listing them
    return {key: value for key, value in row._mapping.items()}


@players_bp.get("/players")
def get_players():
    """
    Return all players, or at least their IDs.
    For now, let's keep it similar to orgs/teams and just return IDs.
    If you want full rows, you can switch to select(players_table).
    """
    try:
        engine = get_engine()
        players_table = _reflect_players_table()

        # ASSUMPTION: primary key column is named "id".
        # If it's "playerID" etc., change players_table.c.id to that.
        stmt = select(players_table.c.id).order_by(players_table.c.id)

        with engine.connect() as conn:
            rows = conn.execute(stmt).all()

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


@players_bp.get("/players/<int:player_id>/")
def get_player(player_id):
    """
    Return a single player row by integer ID.
    Again, if your PK is named differently, change players_table.c.id.
    """
    try:
        engine = get_engine()
        players_table = _reflect_players_table()

        # ASSUMPTION: PK column is "id"; adjust if needed.
        stmt = select(players_table).where(players_table.c.id == player_id).limit(1)

        with engine.connect() as conn:
            row = conn.execute(stmt).first()

        if not row:
            return jsonify([]), 200

        return jsonify([_row_to_dict(row)]), 200
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
