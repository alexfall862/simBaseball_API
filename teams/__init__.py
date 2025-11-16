# teams/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

teams_bp = Blueprint("teams", __name__)


def _reflect_teams_table():
    """Reflect only the teams table and cache it on the blueprint."""
    if not hasattr(teams_bp, "_teams_table"):
        engine = get_engine()
        metadata = MetaData()
        teams_bp._teams_table = Table("teams", metadata, autoload_with=engine)
    return teams_bp._teams_table


def _row_to_dict(row):
    # Works for any number of columns; no need to name them
    return {key: value for key, value in row._mapping.items()}


@teams_bp.get("/teams")
def get_teams():
    """
    Return all team abbreviations (similar to /api/v1/organizations).
    """
    try:
        engine = get_engine()
        teams_table = _reflect_teams_table()
        stmt = select(teams_table.c.team_abbrev).order_by(teams_table.c.team_abbrev)

        with engine.connect() as conn:
            rows = conn.execute(stmt).all()

        # rows are single-column tuples, so row[0] is team_abbrev
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


@teams_bp.get("/teams/<team_abbrev>/")
def get_team(team_abbrev):
    """
    Return a single team row, looked up by abbreviation (case-insensitive).
    Returns [] with 200 if no match (matching org behavior).
    """
    try:
        engine = get_engine()
        teams_table = _reflect_teams_table()

        stmt = (
            select(teams_table)
            .where(text("UPPER(team_abbrev) = :team_upper"))
            .limit(1)
        )

        with engine.connect() as conn:
            row = conn.execute(stmt, {"team_upper": team_abbrev.upper()}).first()

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
