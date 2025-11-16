# rosters/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select, and_
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

rosters_bp = Blueprint("rosters", __name__)


def _get_tables():
    """
    Reflect and cache the tables we need for roster queries.
    """
    if not hasattr(rosters_bp, "_tables"):
        engine = get_engine()
        md = MetaData()

        rosters_bp._tables = {
            "contracts": Table("contracts", md, autoload_with=engine),
            "contract_details": Table("contractDetails", md, autoload_with=engine),
            "contract_team_share": Table("contractTeamShare", md, autoload_with=engine),
            "organizations": Table("organizations", md, autoload_with=engine),
            "players": Table("simbbPlayers", md, autoload_with=engine),
        }
    return rosters_bp._tables


def _row_to_player_dict(row):
    """
    Convert a row that contains org + contract + player fields
    into a player-centric dict, keeping things like current_level
    but dropping org metadata (since that will be at the group level).
    """
    m = row._mapping
    player = {}
    for key, value in m.items():
        # These are org-level fields we’ll keep outside the player dict
        if key in ("org_id", "org_abbrev"):
            continue
        player[key] = value
    return player


def _build_base_roster_stmt(level_filter=None):
    """
    Build the core SELECT for roster queries, without any org filter.
    This is reused by both org-specific and global roster endpoints.

    level_filter can be:
      - None: no level restriction
      - int: exact level_id
      - (min_level, max_level): inclusive range
    """
    tables = _get_tables()
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    orgs = tables["organizations"]
    players = tables["players"]

    conditions = [
        contracts.c.isActive == 1,       # only active contracts
        shares.c.isHolder == 1,          # only the org that actually holds the player
    ]

    # Optional level filtering (on contracts.current_level)
    if isinstance(level_filter, int):
        conditions.append(contracts.c.current_level == level_filter)
    elif isinstance(level_filter, tuple) and len(level_filter) == 2:
        min_level, max_level = level_filter
        if min_level is not None:
            conditions.append(contracts.c.current_level >= min_level)
        if max_level is not None:
            conditions.append(contracts.c.current_level <= max_level)

    stmt = (
        select(
            orgs.c.id.label("org_id"),
            orgs.c.org_abbrev.label("org_abbrev"),
            contracts.c.current_level.label("current_level"),
            players,  # expands all player columns
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
                orgs,
                orgs.c.id == shares.c.orgID,
            )
            .join(
                players,
                players.c.id == contracts.c.playerID,
            )
        )
        .where(and_(*conditions))
    )

    return stmt


# -------------------------------------------------------------------
# 1 & 2) All active players in an org, optionally at a specific level
# -------------------------------------------------------------------
@rosters_bp.get("/orgs/<string:org_abbrev>/roster")
def get_org_roster(org_abbrev: str):
    """
    Return all active players for a given organization.

    Query params:
      - level (optional, int): specific level_id (e.g. 8 for AAA, 9 for MLB)
      - min_level / max_level (optional, int): inclusive range of levels

    Examples:
      /api/v1/orgs/NYY/roster
      /api/v1/orgs/NYY/roster?level=8      # Yankees AAA
      /api/v1/orgs/NYY/roster?min_level=4&max_level=9  # all pro levels
    """
    # Parse level filters from query string
    level_filter = None

    level_param = request.args.get("level", type=int)
    if level_param is not None:
        level_filter = level_param
    else:
        min_level = request.args.get("min_level", type=int)
        max_level = request.args.get("max_level", type=int)
        if min_level is not None or max_level is not None:
            level_filter = (min_level, max_level)

    stmt = _build_base_roster_stmt(level_filter=level_filter)

    # Add org filter
    tables = _get_tables()
    orgs = tables["organizations"]
    stmt = stmt.where(orgs.c.org_abbrev == org_abbrev)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(stmt).all()
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

    # Deduplicate by player id (in case of any weird data)
    players_out = []
    seen_ids = set()
    for row in rows:
        player = _row_to_player_dict(row)
        pid = player.get("id")  # assumes simbbPlayers primary key is "id"
        if pid is not None and pid in seen_ids:
            continue
        if pid is not None:
            seen_ids.add(pid)
        players_out.append(player)

    return jsonify(
        {
            "org": org_abbrev,
            "count": len(players_out),
            "players": players_out,
        }
    ), 200


# -------------------------------------------------------------------
# 3) All active players across DB, grouped by organization
# -------------------------------------------------------------------
@rosters_bp.get("/rosters")
def get_all_rosters_grouped():
    """
    Return all active players across the database, grouped by organization.

    Query params (optional):
      - min_level / max_level (int): inclusive range for current_level filter.
        e.g., min_level=4&max_level=9 for all pro levels.

    Output shape:
      {
        "NYY": {
          "org_id": ...,
          "org_abbrev": "NYY",
          "players": [ {player fields...}, ... ]
        },
        "LAD": {...},
        ...
      }
    """
    min_level = request.args.get("min_level", type=int)
    max_level = request.args.get("max_level", type=int)
    level_filter = None
    if min_level is not None or max_level is not None:
        level_filter = (min_level, max_level)

    stmt = _build_base_roster_stmt(level_filter=level_filter)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(stmt).all()
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

    by_org = {}
    # For safety, dedupe player per org by id
    seen_per_org = {}

    for row in rows:
        m = row._mapping
        org_abbrev = m["org_abbrev"]
        org_id = m["org_id"]

        player = _row_to_player_dict(row)
        pid = player.get("id")

        bucket = by_org.setdefault(
            org_abbrev,
            {
                "org_id": org_id,
                "org_abbrev": org_abbrev,
                "players": [],
            },
        )

        seen_ids = seen_per_org.setdefault(org_abbrev, set())
        if pid is not None and pid in seen_ids:
            continue
        if pid is not None:
            seen_ids.add(pid)

        bucket["players"].append(player)

    return jsonify(by_org), 200
