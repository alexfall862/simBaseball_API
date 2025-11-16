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
            # NEW: level reference table (rename "level" here if your table name differs)
            "levels": Table("levels", md, autoload_with=engine),
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
    Return active players across the database.

    Behaviors:
      - No query params: group all orgs:
        {
          "NYY": {"org_id": ..., "org_abbrev": "NYY", "players": [...]},
          "LAD": {...},
          ...
        }

      - ?org=NYY: return a single-org roster:
        {
          "org": "NYY",
          "org_id": ...,
          "count": ...,
          "players": [...]
        }

      - ?org=NYY&level=aaa: same as above, restricted to that level.
        `level` may be either:
          - a numeric level id (e.g. 8), or
          - a league_level string (e.g. "aaa").

      - min_level / max_level (int) still work as before when you want ranges.
    """
    org_abbrev = request.args.get("org")

    # Level can be numeric (id) or a league_level string ("aaa", "mlb", ...)
    level_arg = request.args.get("level")
    min_level = request.args.get("min_level", type=int)
    max_level = request.args.get("max_level", type=int)

    tables = _get_tables()
    orgs = tables["organizations"]

    level_filter = None

    if level_arg:
        # Try to interpret as integer level id first
        try:
            level_id = int(level_arg)
        except ValueError:
            # Not an int; treat as league_level string, look up in levels table
            levels = tables.get("levels")
            if levels is None:
                return (
                    jsonify(
                        {
                            "error": {
                                "code": "level_lookup_not_configured",
                                "message": "String level requires 'levels' table configuration.",
                            }
                        }
                    ),
                    400,
                )

            engine = get_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    select(levels.c.id)
                    .where(levels.c.league_level == level_arg)
                    .limit(1)
                ).first()

            if not row:
                return (
                    jsonify(
                        {
                            "error": {
                                "code": "unknown_level",
                                "message": f"Unknown level '{level_arg}'",
                            }
                        }
                    ),
                    400,
                )

            level_id = row[0]

        level_filter = level_id
    else:
        # Fallback to numeric min/max filters
        if min_level is not None or max_level is not None:
            level_filter = (min_level, max_level)

    stmt = _build_base_roster_stmt(level_filter=level_filter)

    # Restrict to a specific org if requested
    if org_abbrev:
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

    by_org = {}
    # For safety, dedupe player per org by id
    seen_per_org = {}

    for row in rows:
        m = row._mapping
        this_org_abbrev = m["org_abbrev"]
        org_id = m["org_id"]

        player = _row_to_player_dict(row)
        pid = player.get("id")

        bucket = by_org.setdefault(
            this_org_abbrev,
            {
                "org_id": org_id,
                "org_abbrev": this_org_abbrev,
                "players": [],
            },
        )

        seen_ids = seen_per_org.setdefault(this_org_abbrev, set())
        if pid is not None and pid in seen_ids:
            continue
        if pid is not None:
            seen_ids.add(pid)

        bucket["players"].append(player)

    # If org query param was provided, return a single-org structure
    if org_abbrev:
        org_bucket = by_org.get(
            org_abbrev,
            {"org_abbrev": org_abbrev, "org_id": None, "players": []},
        )
        players_out = org_bucket.get("players", [])
        return (
            jsonify(
                {
                    "org": org_abbrev,
                    "org_id": org_bucket.get("org_id"),
                    "count": len(players_out),
                    "players": players_out,
                }
            ),
            200,
        )

    # Otherwise, return the grouped-by-org map
    return jsonify(by_org), 200

from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select, and_, literal
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

rosters_bp = Blueprint("rosters", __name__)

# ... _get_tables and _row_to_player_dict etc. defined above ...


@rosters_bp.get("/orgs/<string:org_abbrev>/obligations")
def get_org_obligations(org_abbrev: str):
    """
    Return all financial obligations for an organization in a given league year.

    Query params:
      - league_year (required, int): the league year (e.g., 2027)

    Obligations include:
      - salary obligations for that league year from contractDetails + contractTeamShare
      - bonus / buyout obligations from contracts.bonus in leagueYearSigned

    Each obligation row is classified so the frontend can distinguish:
      - active vs inactive vs buyout
      - salary vs bonus
    """
    league_year = request.args.get("league_year", type=int)
    if league_year is None:
        return (
            jsonify(
                {
                    "error": {
                        "code": "missing_league_year",
                        "message": "Query parameter 'league_year' is required and must be an integer.",
                    }
                }
            ),
            400,
        )

    tables = _get_tables()
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    orgs = tables["organizations"]
    players = tables["players"]

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # 1) Resolve org_abbrev -> org_id
            org_row = conn.execute(
                select(orgs.c.id).where(orgs.c.org_abbrev == org_abbrev).limit(1)
            ).first()

            if not org_row:
                return (
                    jsonify(
                        {
                            "error": {
                                "code": "org_not_found",
                                "message": f"No organization with abbrev '{org_abbrev}'",
                            }
                        }
                    ),
                    404,
                )

            org_id = org_row[0]

            # -------------------------
            # A. Salary obligations
            # -------------------------
            # league_year_for_row = contracts.leagueYearSigned + (contractDetails.year - 1)
            league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

            salary_stmt = (
                select(
                    contracts.c.id.label("contract_id"),
                    contracts.c.leagueYearSigned.label("leagueYearSigned"),
                    contracts.c.isActive.label("isActive"),
                    contracts.c.isBuyout.label("isBuyout"),
                    contracts.c.bonus.label("bonus"),
                    contracts.c.signingOrg.label("signingOrg"),
                    details.c.id.label("contractDetails_id"),
                    details.c.year.label("year_index"),
                    details.c.salary.label("salary"),
                    shares.c.salary_share.label("salary_share"),
                    shares.c.isHolder.label("isHolder"),
                    shares.c.orgID.label("org_id"),
                    players.c.id.label("player_id"),
                    # if you want more player columns, add them here explicitly
                )
                .select_from(
                    contracts
                    .join(details, details.c.contractID == contracts.c.id)
                    .join(shares, shares.c.contractDetailsID == details.c.id)
                    .join(players, players.c.id == contracts.c.playerID)
                )
                .where(
                    and_(
                        league_year_expr == league_year,
                        shares.c.orgID == org_id,
                        shares.c.salary_share > 0,
                    )
                )
            )

            salary_rows = conn.execute(salary_stmt).all()

            # -------------------------
            # B. Bonus / buyout obligations
            # -------------------------
            # Bonus applies in leagueYearSigned, from signingOrg.
            bonus_stmt = (
                select(
                    contracts.c.id.label("contract_id"),
                    contracts.c.leagueYearSigned.label("leagueYearSigned"),
                    contracts.c.isActive.label("isActive"),
                    contracts.c.isBuyout.label("isBuyout"),
                    contracts.c.bonus.label("bonus"),
                    contracts.c.signingOrg.label("signingOrg"),
                    players.c.id.label("player_id"),
                )
                .select_from(contracts.join(players, players.c.id == contracts.c.playerID))
                .where(
                    and_(
                        contracts.c.leagueYearSigned == league_year,
                        contracts.c.signingOrg == org_id,
                        contracts.c.bonus > 0,
                    )
                )
            )

            bonus_rows = conn.execute(bonus_stmt).all()

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

    obligations = []
    totals = {
        "active_salary": 0.0,
        "inactive_salary": 0.0,
        "buyout": 0.0,
        "signing_bonus": 0.0,
        "overall": 0.0,
    }

    # Helper to safely coerce numeric values
    def _num(val):
        return float(val) if val is not None else 0.0

    # ------------------------------------
    # Build salary-based obligation rows
    # ------------------------------------
    for row in salary_rows:
        m = row._mapping
        salary = _num(m["salary"])
        share = _num(m["salary_share"])
        base_amount = salary * share

        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)
        is_holder = bool(m.get("isHolder") or False)

        # Category classification:
        # - Any obligations from a buyout contract are considered "buyout" money.
        # - Otherwise, distinguish active vs inactive based on isActive + isHolder.
        if is_buyout:
            category = "buyout"
        elif is_active and is_holder:
            category = "active_salary"
        else:
            category = "inactive_salary"

        obligations.append(
            {
                "type": "salary",
                "category": category,
                "league_year": league_year,
                "year_index": m["year_index"],
                "player": {
                    "id": m["player_id"],
                },
                "contract": {
                    "id": m["contract_id"],
                    "leagueYearSigned": m["leagueYearSigned"],
                    "isActive": is_active,
                    "isBuyout": is_buyout,
                },
                "flags": {
                    "is_holder": is_holder,
                    "is_buyout": is_buyout,
                },
                "salary": salary,
                "salary_share": share,
                "base_amount": base_amount,
                "bonus_amount": 0.0,
            }
        )

        totals["overall"] += base_amount
        if category == "buyout":
            totals["buyout"] += base_amount
        elif category == "active_salary":
            totals["active_salary"] += base_amount
        elif category == "inactive_salary":
            totals["inactive_salary"] += base_amount

    # ------------------------------------
    # Build bonus / buyout obligation rows
    # ------------------------------------
    for row in bonus_rows:
        m = row._mapping
        bonus = _num(m["bonus"])
        if bonus <= 0:
            continue

        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)

        category = "buyout" if is_buyout else "signing_bonus"

        obligations.append(
            {
                "type": "bonus",
                "category": category,
                "league_year": league_year,
                "player": {
                    "id": m["player_id"],
                },
                "contract": {
                    "id": m["contract_id"],
                    "leagueYearSigned": m["leagueYearSigned"],
                    "isActive": is_active,
                    "isBuyout": is_buyout,
                },
                "flags": {
                    "is_holder": False,  # bonus based on signingOrg, not holder
                    "is_buyout": is_buyout,
                },
                "salary": 0.0,
                "salary_share": None,
                "base_amount": 0.0,
                "bonus_amount": bonus,
            }
        )

        totals["overall"] += bonus
        if category == "buyout":
            totals["buyout"] += bonus
        elif category == "signing_bonus":
            totals["signing_bonus"] += bonus

    response = {
        "org": org_abbrev,
        "org_id": org_id,
        "league_year": league_year,
        "totals": totals,
        "obligations": obligations,
    }

    return jsonify(response), 200

@rosters_bp.get("/obligations")
def get_all_org_obligations():
    """
    Return financial obligations for ALL organizations in a given league year.

    Query params:
      - league_year (required, int): the league year (e.g., 2027)

    Response structure:
      {
        "league_year": 2027,
        "orgs": {
          "NYY": {
            "org_id": ...,
            "org_abbrev": "NYY",
            "totals": {
              "active_salary": ...,
              "inactive_salary": ...,
              "buyout": ...,
              "signing_bonus": ...,
              "overall": ...
            },
            "obligations": [ ...rows as in the single-org endpoint... ]
          },
          "LAD": { ... },
          ...
        }
      }
    """
    league_year = request.args.get("league_year", type=int)
    if league_year is None:
        return (
            jsonify(
                {
                    "error": {
                        "code": "missing_league_year",
                        "message": "Query parameter 'league_year' is required and must be an integer.",
                    }
                }
            ),
            400,
        )

    tables = _get_tables()
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    orgs = tables["organizations"]
    players = tables["players"]

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # -------------------------
            # A. Salary obligations
            # -------------------------
            league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

            salary_stmt = (
                select(
                    orgs.c.id.label("org_id"),
                    orgs.c.org_abbrev.label("org_abbrev"),
                    contracts.c.id.label("contract_id"),
                    contracts.c.leagueYearSigned.label("leagueYearSigned"),
                    contracts.c.isActive.label("isActive"),
                    contracts.c.isBuyout.label("isBuyout"),
                    contracts.c.bonus.label("bonus"),
                    contracts.c.signingOrg.label("signingOrg"),
                    details.c.id.label("contractDetails_id"),
                    details.c.year.label("year_index"),
                    details.c.salary.label("salary"),
                    shares.c.salary_share.label("salary_share"),
                    shares.c.isHolder.label("isHolder"),
                    shares.c.orgID.label("share_org_id"),
                    players.c.id.label("player_id"),
                )
                .select_from(
                    contracts
                    .join(details, details.c.contractID == contracts.c.id)
                    .join(shares, shares.c.contractDetailsID == details.c.id)
                    .join(orgs, orgs.c.id == shares.c.orgID)
                    .join(players, players.c.id == contracts.c.playerID)
                )
                .where(
                    and_(
                        league_year_expr == league_year,
                        shares.c.salary_share > 0,
                    )
                )
            )

            salary_rows = conn.execute(salary_stmt).all()

            # -------------------------
            # B. Bonus / buyout obligations
            # -------------------------
            bonus_stmt = (
                select(
                    orgs.c.id.label("org_id"),
                    orgs.c.org_abbrev.label("org_abbrev"),
                    contracts.c.id.label("contract_id"),
                    contracts.c.leagueYearSigned.label("leagueYearSigned"),
                    contracts.c.isActive.label("isActive"),
                    contracts.c.isBuyout.label("isBuyout"),
                    contracts.c.bonus.label("bonus"),
                    contracts.c.signingOrg.label("signingOrg"),
                    players.c.id.label("player_id"),
                )
                .select_from(
                    contracts
                    .join(orgs, orgs.c.id == contracts.c.signingOrg)
                    .join(players, players.c.id == contracts.c.playerID)
                )
                .where(
                    and_(
                        contracts.c.leagueYearSigned == league_year,
                        contracts.c.bonus > 0,
                    )
                )
            )

            bonus_rows = conn.execute(bonus_stmt).all()

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

    # -------------------------
    # Build grouped-by-org result
    # -------------------------
    def _num(val):
        return float(val) if val is not None else 0.0

    by_org = {}

    # Helper to get/create org bucket
    def _get_bucket(org_id, org_abbrev):
        bucket = by_org.get(org_abbrev)
        if bucket is None:
            bucket = {
                "org_id": org_id,
                "org_abbrev": org_abbrev,
                "totals": {
                    "active_salary": 0.0,
                    "inactive_salary": 0.0,
                    "buyout": 0.0,
                    "signing_bonus": 0.0,
                    "overall": 0.0,
                },
                "obligations": [],
            }
            by_org[org_abbrev] = bucket
        return bucket

    # ----- Salary obligations -----
    for row in salary_rows:
        m = row._mapping
        org_id = m["org_id"]
        org_abbrev = m["org_abbrev"]

        bucket = _get_bucket(org_id, org_abbrev)

        salary = _num(m["salary"])
        share = _num(m["salary_share"])
        base_amount = salary * share

        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)
        is_holder = bool(m.get("isHolder") or False)

        # Category classification:
        if is_buyout:
            category = "buyout"
        elif is_active and is_holder:
            category = "active_salary"
        else:
            category = "inactive_salary"

        obligation = {
            "type": "salary",
            "category": category,
            "league_year": league_year,
            "year_index": m["year_index"],
            "player": {
                "id": m["player_id"],
            },
            "contract": {
                "id": m["contract_id"],
                "leagueYearSigned": m["leagueYearSigned"],
                "isActive": is_active,
                "isBuyout": is_buyout,
            },
            "flags": {
                "is_holder": is_holder,
                "is_buyout": is_buyout,
            },
            "salary": salary,
            "salary_share": share,
            "base_amount": base_amount,
            "bonus_amount": 0.0,
        }

        bucket["obligations"].append(obligation)

        bucket["totals"]["overall"] += base_amount
        if category == "buyout":
            bucket["totals"]["buyout"] += base_amount
        elif category == "active_salary":
            bucket["totals"]["active_salary"] += base_amount
        elif category == "inactive_salary":
            bucket["totals"]["inactive_salary"] += base_amount

    # ----- Bonus / buyout obligations -----
    for row in bonus_rows:
        m = row._mapping
        org_id = m["org_id"]
        org_abbrev = m["org_abbrev"]

        bucket = _get_bucket(org_id, org_abbrev)

        bonus = _num(m["bonus"])
        if bonus <= 0:
            continue

        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)

        category = "buyout" if is_buyout else "signing_bonus"

        obligation = {
            "type": "bonus",
            "category": category,
            "league_year": league_year,
            "player": {
                "id": m["player_id"],
            },
            "contract": {
                "id": m["contract_id"],
                "leagueYearSigned": m["leagueYearSigned"],
                "isActive": is_active,
                "isBuyout": is_buyout,
            },
            "flags": {
                "is_holder": False,
                "is_buyout": is_buyout,
            },
            "salary": 0.0,
            "salary_share": None,
            "base_amount": 0.0,
            "bonus_amount": bonus,
        }

        bucket["obligations"].append(obligation)

        bucket["totals"]["overall"] += bonus
        if category == "buyout":
            bucket["totals"]["buyout"] += bonus
        elif category == "signing_bonus":
            bucket["totals"]["signing_bonus"] += bonus

    response = {
        "league_year": league_year,
        "orgs": by_org,
    }

    return jsonify(response), 200
