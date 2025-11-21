# teams/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, text, and_
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

def _get_roster_tables_for_teams():
    """
    Reflect the tables needed to compute team rosters from inside the teams blueprint.
    This mirrors what rosters/__init__.py uses.
    """
    if not hasattr(teams_bp, "_roster_tables"):
        engine = get_engine()
        md = MetaData()
        teams_bp._roster_tables = {
            "contracts": Table("contracts", md, autoload_with=engine),
            "contract_details": Table("contractDetails", md, autoload_with=engine),
            "contract_team_share": Table("contractTeamShare", md, autoload_with=engine),
            "organizations": Table("organizations", md, autoload_with=engine),
            "players": Table("simbbPlayers", md, autoload_with=engine),
        }
    return teams_bp._roster_tables


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

@teams_bp.get("/teams/<team_abbrev>/players")
def get_team_players(team_abbrev: str):
    """
    Return all active players currently assigned to the given team.

    A player is considered "on" a team if:
      - Their contract isActive = 1
      - contractTeamShare.isHolder = 1 for the current year
      - contractTeamShare.orgID == team.orgID
      - contracts.current_level == teams.team_level
    """
    try:
        engine = get_engine()
        teams_table = _reflect_teams_table()

        # 1) Look up the team
        with engine.connect() as conn:
            team_row = conn.execute(
                select(teams_table).where(teams_table.c.team_abbrev == team_abbrev)
            ).first()

        if not team_row:
            # Team abbrev not found
            return (
                jsonify(
                    {
                        "error": {
                            "code": "team_not_found",
                            "message": f"No team with abbrev '{team_abbrev}'",
                        }
                    }
                ),
                404,
            )

        team = team_row._mapping
        org_id = team["orgID"]
        team_level = team["team_level"]

        # 2) Build roster query using contracts + contractDetails + contractTeamShare
        tables = _get_roster_tables_for_teams()
        contracts = tables["contracts"]
        details = tables["contract_details"]
        shares = tables["contract_team_share"]
        players = tables["players"]

        conditions = [
            contracts.c.isActive == 1,
            shares.c.isHolder == 1,
            shares.c.orgID == org_id,
            contracts.c.current_level == team_level,
        ]

        stmt = (
            select(
                players,  # all player columns
                contracts.c.current_level.label("current_level"),
            )
            .select_from(
                contracts
                .join(
                    details,
                    and_(
                        details.c.contractID == contracts.c.id,
                        details.c.year == contracts.c.current_year,
                    ),
                )
                .join(
                    shares,
                    shares.c.contractDetailsID == details.c.id,
                )
                .join(
                    players,
                    players.c.id == contracts.c.playerID,
                )
            )
            .where(and_(*conditions))
        )

        with engine.connect() as conn:
            rows = conn.execute(stmt).all()

        # 3) Deduplicate players by id, build response
        players_out = []
        seen_ids = set()
        for row in rows:
            m = row._mapping
            player = {k: v for k, v in m.items() if k not in ("current_level",)}
            pid = player.get("id")
            if pid is not None and pid in seen_ids:
                continue
            if pid is not None:
                seen_ids.add(pid)
            players_out.append(player)

        return (
            jsonify(
                {
                    "team": {
                        "team_id": team["id"],
                        "team_abbrev": team["team_abbrev"],
                        "org_id": team["orgID"],
                        "team_level": team["team_level"],
                    },
                    "count": len(players_out),
                    "players": players_out,
                }
            ),
            200,
        )

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