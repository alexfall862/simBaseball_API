# rosters/__init__.py
from flask import Blueprint, jsonify, request, current_app, func
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

@rosters_bp.get("/orgs/<string:org_abbrev>/obligations/history")
def get_org_obligations_history(org_abbrev: str):
    """
    Return a full financial snapshot for an organization across ALL league years.

    Optional query params:
      - min_year (int): minimum league_year to include
      - max_year (int): maximum league_year to include

    Response shape:
      {
        "org": "NYY",
        "org_id": 45,
        "years": {
          "2024": {
            "league_year": 2024,
            "totals": {
              "active_salary": ...,
              "inactive_salary": ...,
              "buyout": ...,
              "signing_bonus": ...,
              "overall": ...
            },
            "obligations": [ ...rows... ]
          },
          "2025": { ... },
          ...
        },
        "lifetime_totals": {
          "active_salary": ...,
          "inactive_salary": ...,
          "buyout": ...,
          "signing_bonus": ...,
          "overall": ...
        }
      }
    """
    min_year = request.args.get("min_year", type=int)
    max_year = request.args.get("max_year", type=int)

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
            # A. Salary obligations (all years)
            # -------------------------
            # league_year_for_row = contracts.leagueYearSigned + (contractDetails.year - 1)
            league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

            salary_conditions = [
                shares.c.orgID == org_id,
                shares.c.salary_share > 0,
            ]

            if min_year is not None:
                salary_conditions.append(league_year_expr >= min_year)
            if max_year is not None:
                salary_conditions.append(league_year_expr <= max_year)

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
                    league_year_expr.label("league_year"),
                )
                .select_from(
                    contracts
                    .join(details, details.c.contractID == contracts.c.id)
                    .join(shares, shares.c.contractDetailsID == details.c.id)
                    .join(players, players.c.id == contracts.c.playerID)
                )
                .where(and_(*salary_conditions))
            )

            salary_rows = conn.execute(salary_stmt).all()

            # -------------------------
            # B. Bonus / buyout obligations (all years)
            # -------------------------
            bonus_conditions = [
                contracts.c.signingOrg == org_id,
                contracts.c.bonus > 0,
            ]
            if min_year is not None:
                bonus_conditions.append(contracts.c.leagueYearSigned >= min_year)
            if max_year is not None:
                bonus_conditions.append(contracts.c.leagueYearSigned <= max_year)

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
                .where(and_(*bonus_conditions))
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
    # Group by league_year and compute totals
    # -------------------------
    def _num(val):
        return float(val) if val is not None else 0.0

    years = {}
    lifetime_totals = {
        "active_salary": 0.0,
        "inactive_salary": 0.0,
        "buyout": 0.0,
        "signing_bonus": 0.0,
        "overall": 0.0,
    }

    def _get_year_bucket(ly: int):
        key = str(ly)
        bucket = years.get(key)
        if bucket is None:
            bucket = {
                "league_year": ly,
                "totals": {
                    "active_salary": 0.0,
                    "inactive_salary": 0.0,
                    "buyout": 0.0,
                    "signing_bonus": 0.0,
                    "overall": 0.0,
                },
                "obligations": [],
            }
            years[key] = bucket
        return bucket

    # ----- Salary obligations across all years -----
    for row in salary_rows:
        m = row._mapping
        league_year = int(m["league_year"])
        bucket = _get_year_bucket(league_year)

        salary = _num(m["salary"])
        share = _num(m["salary_share"])
        base_amount = salary * share

        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)
        is_holder = bool(m.get("isHolder") or False)

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

        # Per-year totals
        bucket["totals"]["overall"] += base_amount
        if category == "buyout":
            bucket["totals"]["buyout"] += base_amount
        elif category == "active_salary":
            bucket["totals"]["active_salary"] += base_amount
        elif category == "inactive_salary":
            bucket["totals"]["inactive_salary"] += base_amount

        # Lifetime totals
        lifetime_totals["overall"] += base_amount
        if category == "buyout":
            lifetime_totals["buyout"] += base_amount
        elif category == "active_salary":
            lifetime_totals["active_salary"] += base_amount
        elif category == "inactive_salary":
            lifetime_totals["inactive_salary"] += base_amount

    # ----- Bonus / buyout obligations across all years -----
    for row in bonus_rows:
        m = row._mapping
        league_year = int(m["leagueYearSigned"])
        bucket = _get_year_bucket(league_year)

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

        # Per-year totals
        bucket["totals"]["overall"] += bonus
        if category == "buyout":
            bucket["totals"]["buyout"] += bonus
        elif category == "signing_bonus":
            bucket["totals"]["signing_bonus"] += bonus

        # Lifetime totals
        lifetime_totals["overall"] += bonus
        if category == "buyout":
            lifetime_totals["buyout"] += bonus
        elif category == "signing_bonus":
            lifetime_totals["signing_bonus"] += bonus

    response = {
        "org": org_abbrev,
        "org_id": org_id,
        "years": years,
        "lifetime_totals": lifetime_totals,
    }

    return jsonify(response), 200

def get_org_financial_summary(engine, org_abbrev: str, league_year: int):
    """
    Summarize an organization's finances for a given league_year.

    - starting_balance: net balance from all prior league years
    - year_start_events: media/bonus/buyout (non-week entries in this year)
    - weeks: per-week salary/performance/other + cumulative balance
    - interest_events: interest_income/interest_expense entries in this year
    - ending_balance: after this year's activity + interest
    """
    md = MetaData()
    orgs = Table("organizations", md, autoload_with=engine)
    league_years = Table("league_years", md, autoload_with=engine)
    game_weeks = Table("game_weeks", md, autoload_with=engine)
    ledger = Table("org_ledger_entries", md, autoload_with=engine)

    with engine.connect() as conn:
        # --- Resolve org_abbrev -> org_id ---
        org_row = conn.execute(
            select(orgs.c.id, orgs.c.org_abbrev)
            .where(orgs.c.org_abbrev == org_abbrev)
            .limit(1)
        ).first()
        if not org_row:
            raise ValueError(f"Organization '{org_abbrev}' not found")

        org_m = org_row._mapping
        org_id = org_m["id"]

        # --- Resolve league_year -> league_years row ---
        ly_row = conn.execute(
            select(
                league_years.c.id,
                league_years.c.league_year,
                league_years.c.weeks_in_season,
            )
            .where(league_years.c.league_year == league_year)
            .limit(1)
        ).first()
        if not ly_row:
            raise ValueError(f"league_year {league_year} not found in league_years")

        ly_m = ly_row._mapping
        league_year_id = ly_m["id"]
        weeks_in_season = int(ly_m["weeks_in_season"])

        # --- Starting balance: all ledger entries from prior years ---
        starting_balance = conn.execute(
            select(func.coalesce(func.sum(ledger.c.amount), 0))
            .select_from(
                ledger.join(
                    league_years,
                    ledger.c.league_year_id == league_years.c.id,
                )
            )
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    league_years.c.league_year < league_year,
                )
            )
        ).scalar_one()

        # --- Year-level (non-week) entries for this year ---
        year_level_rows = conn.execute(
            select(
                ledger.c.entry_type,
                func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
            )
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ledger.c.league_year_id == league_year_id,
                    ledger.c.game_week_id.is_(None),
                )
            )
            .group_by(ledger.c.entry_type)
        ).all()

        year_level_totals = {
            r._mapping["entry_type"]: float(r._mapping["total"])
            for r in year_level_rows
        }

        # Separate out categories
        year_start_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("media", "bonus", "buyout")
        }
        interest_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("interest_income", "interest_expense")
        }

        year_start_net = sum(year_start_events.values())
        interest_net = sum(interest_events.values())

        # Balance right after year-start events but before weekly activity
        balance_after_year_start = float(starting_balance) + year_start_net

        # --- Weekly entries (grouped by week_index + entry_type) ---
        weekly_rows = conn.execute(
            select(
                game_weeks.c.week_index,
                ledger.c.entry_type,
                func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
            )
            .select_from(
                ledger.join(game_weeks, ledger.c.game_week_id == game_weeks.c.id)
            )
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ledger.c.league_year_id == league_year_id,
                )
            )
            .group_by(game_weeks.c.week_index, ledger.c.entry_type)
        ).all()

        # Organize totals per week & type
        week_type_totals = {}
        for row in weekly_rows:
            m = row._mapping
            week = m["week_index"]
            etype = m["entry_type"]
            total = float(m["total"])
            week_type_totals.setdefault(week, {})[etype] = total

        weeks_summary = []
        cumulative = balance_after_year_start

        for week_index in range(1, weeks_in_season + 1):
            by_type = week_type_totals.get(week_index, {})
            salary_total = by_type.get("salary", 0.0)          # negative in ledger
            performance_total = by_type.get("performance", 0.0)  # positive

            other_types = {
                k: v for k, v in by_type.items()
                if k not in ("salary", "performance")
            }
            other_in = sum(v for v in other_types.values() if v > 0)
            other_out = -sum(v for v in other_types.values() if v < 0)

            week_net = sum(by_type.values())
            cumulative += week_net

            weeks_summary.append(
                {
                    "week_index": week_index,
                    # Present salary_out as positive “outflow” for the frontend
                    "salary_out": -salary_total,
                    "performance_in": performance_total,
                    "other_in": other_in,
                    "other_out": other_out,
                    "net": week_net,
                    "cumulative_balance": cumulative,
                    "by_type": by_type,  # detailed breakdown if you want it
                }
            )

        ending_balance_before_interest = cumulative
        ending_balance = ending_balance_before_interest + interest_net

    return {
        "org": {
            "id": org_id,
            "abbrev": org_m["org_abbrev"],
        },
        "league_year": league_year,
        "starting_balance": float(starting_balance),
        "year_start_events": year_start_events,
        "weeks": weeks_summary,
        "interest_events": interest_events,
        "ending_balance_before_interest": ending_balance_before_interest,
        "ending_balance": ending_balance,
    }

@rosters_bp.get("/orgs/<string:org_abbrev>/financial_summary")
def get_org_financial_summary_endpoint(org_abbrev):
    app = current_app
    engine = getattr(app, "engine", None)
    if not engine:
        return jsonify(
            error="no_db_engine",
            message="Database engine is not initialized on the app."
        ), 500

    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    try:
        summary = get_org_financial_summary(engine, org_abbrev, league_year)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    except SQLAlchemyError as e:
        app.logger.exception("get_org_financial_summary: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(summary), 200

def get_league_financial_summary(engine, league_year: int):
    """
    League-wide financial summary for a given league_year.

    Returns:
      {
        "league_year": 2026,
        "orgs": {
          "NYY": { ...same shape as get_org_financial_summary... },
          "LAD": { ... },
          ...
        }
      }
    """
    md = MetaData()
    orgs = Table("organizations", md, autoload_with=engine)
    league_years = Table("league_years", md, autoload_with=engine)

    # Validate league_year once up front, and get its row (so
    # get_org_financial_summary won't fail per org on missing year)
    with engine.connect() as conn:
        ly_row = conn.execute(
            select(league_years.c.id, league_years.c.league_year)
            .where(league_years.c.league_year == league_year)
            .limit(1)
        ).first()

        if not ly_row:
            raise ValueError(f"league_year {league_year} not found in league_years")

        # Get all orgs (abbrev + id) – order by abbrev for stable output
        org_rows = conn.execute(
            select(orgs.c.org_abbrev, orgs.c.id)
            .order_by(orgs.c.org_abbrev)
        ).all()

    org_summaries = {}

    # Reuse the existing per-org helper for each org
    for row in org_rows:
        m = row._mapping
        org_abbrev = m["org_abbrev"]
        org_summaries[org_abbrev] = get_org_financial_summary(
            engine,
            org_abbrev,
            league_year,
        )

    return {
        "league_year": league_year,
        "orgs": org_summaries,
    }

@rosters_bp.get("/financial_summary")
def get_league_financial_summary_endpoint():
    """
    League-wide financial summary for a given league_year.

    Example:
      GET /api/v1/financial_summary?league_year=2026
    """
    app = current_app
    engine = getattr(app, "engine", None)
    if not engine:
        return jsonify(
            error="no_db_engine",
            message="Database engine is not initialized on the app."
        ), 500

    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    try:
        summary = get_league_financial_summary(engine, league_year)
    except ValueError as e:
        # e.g. league_year not found
        return jsonify(error="not_found", message=str(e)), 404
    except SQLAlchemyError as e:
        app.logger.exception("get_league_financial_summary: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(summary), 200
