# scouting/__init__.py
"""
Scouting pool endpoints — paginated, filterable player browsing
for pro scouting (MLB draft/FA) and college recruiting.

Also provides scouting action endpoints for budget management,
unlocking player information, and visibility-based player profiles.

All endpoints under /scouting/.
"""

import math
import re
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select, and_, or_, func, case, literal, text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.scouting_service import (
    get_or_create_budget,
    perform_scouting_action,
    get_player_scouting_visibility,
    get_org_scouting_actions,
    get_scouting_config,
    base_to_letter_grade,
)
from services.scouting_stats import generate_scouting_stats
from services.scouting_reports import generate_text_report

scouting_bp = Blueprint("scouting", __name__)

# Org ID constants
INTAM_ORG_ID = 339
USHS_ORG_ID = 340
COLLEGE_ORG_MIN = 31
COLLEGE_ORG_MAX = 338

# Pagination defaults
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

# Columns allowed for sorting (whitelist to prevent injection)
ALLOWED_SORTS = {
    "lastname", "firstname", "age", "ptype", "area",
    "height", "weight", "displayovr",
    "contact_base", "power_base", "discipline_base", "eye_base",
    "speed_base", "baserunning_base", "basereaction_base",
    "throwpower_base", "throwacc_base",
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    "catchframe_base", "catchsequence_base",
    "pendurance_base", "pgencontrol_base", "pthrowpower_base",
    "psequencing_base", "pickoff_base",
}


# -------------------------------------------------------------------
# Table reflection (cached on blueprint, same pattern as rosters)
# -------------------------------------------------------------------

def _get_tables():
    if not hasattr(scouting_bp, "_tables"):
        engine = get_engine()
        md = MetaData()
        scouting_bp._tables = {
            "contracts": Table("contracts", md, autoload_with=engine),
            "contract_details": Table("contractDetails", md, autoload_with=engine),
            "contract_team_share": Table("contractTeamShare", md, autoload_with=engine),
            "organizations": Table("organizations", md, autoload_with=engine),
            "players": Table("simbbPlayers", md, autoload_with=engine),
        }
    return scouting_bp._tables


def _get_scouting_columns():
    """
    Build the list of columns to SELECT for scouting card responses.
    Dynamically discovers _base, _pot, pitch name/ovr columns from the
    reflected table so we don't need to hardcode every column name.
    """
    if hasattr(scouting_bp, "_scouting_cols"):
        return scouting_bp._scouting_cols

    tables = _get_tables()
    players = tables["players"]

    cols = []
    for col in players.c:
        name = col.name
        # Bio columns
        if name in (
            "id", "firstname", "lastname", "age", "ptype",
            "area", "city", "intorusa",
            "height", "weight", "bat_hand", "pitch_hand",
            "arm_angle", "durability", "injury_risk",
            "displayovr",
            "left_split", "center_split", "right_split",
        ):
            cols.append(col)
        # All _base ability columns (numeric, sortable)
        elif name.endswith("_base"):
            cols.append(col)
        # All _pot potential grade columns
        elif name.endswith("_pot"):
            cols.append(col)
        # Pitch names and OVRs
        elif re.match(r"^pitch\d+_name$", name) or re.match(r"^pitch\d+_ovr$", name):
            cols.append(col)

    scouting_bp._scouting_cols = cols
    return cols


# -------------------------------------------------------------------
# Shared query builder
# -------------------------------------------------------------------

def _build_join_chain():
    """Build the standard contract → player join chain."""
    tables = _get_tables()
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    orgs = tables["organizations"]
    players = tables["players"]

    join = (
        contracts
        .join(
            details,
            and_(
                details.c.contractID == contracts.c.id,
                details.c.year == contracts.c.current_year,
            ),
        )
        .join(shares, shares.c.contractDetailsID == details.c.id)
        .join(orgs, orgs.c.id == shares.c.orgID)
        .join(players, players.c.id == contracts.c.playerID)
    )

    return join, tables


def _parse_pagination():
    """Parse and validate page/per_page from query string."""
    page = request.args.get("page", DEFAULT_PAGE, type=int)
    per_page = request.args.get("per_page", DEFAULT_PER_PAGE, type=int)
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _parse_sort(tables):
    """Parse sort column and direction from query string. Returns (column, direction)."""
    sort_name = request.args.get("sort", "lastname")
    direction = request.args.get("dir", "asc").lower()

    if sort_name not in ALLOWED_SORTS:
        sort_name = "lastname"
    if direction not in ("asc", "desc"):
        direction = "asc"

    players = tables["players"]
    sort_col = players.c[sort_name]
    return sort_col.asc() if direction == "asc" else sort_col.desc()


def _apply_common_filters(conditions, tables):
    """Apply ptype, area, and search filters from query string."""
    players = tables["players"]

    ptype = request.args.get("ptype")
    if ptype in ("Pitcher", "Position"):
        conditions.append(players.c.ptype == ptype)

    area = request.args.get("area")
    if area:
        conditions.append(players.c.area == area)

    search = request.args.get("search")
    if search and len(search) >= 2:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                players.c.firstname.like(pattern),
                players.c.lastname.like(pattern),
            )
        )


def _build_player_list(rows, tables):
    """Convert result rows into list of player dicts."""
    players_list = []
    for row in rows:
        m = row._mapping
        player = {}
        for key, value in m.items():
            # Convert Decimal to float for JSON serialization
            if hasattr(value, "is_finite"):
                value = float(value)
            player[key] = value
        players_list.append(player)
    return players_list


# -------------------------------------------------------------------
# Endpoint 1: Pro Scouting Pool
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/pro-pool")
def api_pro_pool():
    """
    Paginated list of players eligible for pro scouting:
    - INTAM (org 339) age 18+
    - College (orgs 31-338) any age
    """
    try:
        page, per_page = _parse_pagination()
        join, tables = _build_join_chain()

        contracts = tables["contracts"]
        shares = tables["contract_team_share"]
        orgs = tables["organizations"]
        players = tables["players"]

        # Base conditions: active contract, held by org
        conditions = [
            contracts.c.isActive == 1,
            shares.c.isHolder == 1,
        ]

        # Pool filter: INTAM 18+ OR College any age
        pool_condition = or_(
            and_(shares.c.orgID == INTAM_ORG_ID, players.c.age >= 18),
            and_(
                shares.c.orgID >= COLLEGE_ORG_MIN,
                shares.c.orgID <= COLLEGE_ORG_MAX,
            ),
        )
        conditions.append(pool_condition)

        # Optional filters
        _apply_common_filters(conditions, tables)

        min_age = request.args.get("min_age", type=int)
        max_age = request.args.get("max_age", type=int)
        if min_age is not None:
            conditions.append(players.c.age >= min_age)
        if max_age is not None:
            conditions.append(players.c.age <= max_age)

        org_id = request.args.get("org_id", type=int)
        if org_id is not None:
            conditions.append(shares.c.orgID == org_id)

        where = and_(*conditions)
        order = _parse_sort(tables)

        # Build column selection
        scouting_cols = _get_scouting_columns()
        select_cols = [
            *scouting_cols,
            orgs.c.id.label("org_id"),
            orgs.c.org_abbrev.label("org_abbrev"),
            contracts.c.current_level.label("current_level"),
        ]

        engine = get_engine()
        with engine.connect() as conn:
            # Total count
            count_stmt = (
                select(func.count())
                .select_from(join)
                .where(where)
            )
            total = conn.execute(count_stmt).scalar()

            # Pool breakdown counts (college vs intam) — always based
            # on full pool (ignores org_id filter for summary)
            pool_conditions = [
                contracts.c.isActive == 1,
                shares.c.isHolder == 1,
                pool_condition,
            ]
            college_count_stmt = (
                select(func.count())
                .select_from(join)
                .where(and_(
                    *pool_conditions,
                    shares.c.orgID >= COLLEGE_ORG_MIN,
                    shares.c.orgID <= COLLEGE_ORG_MAX,
                ))
            )
            intam_count_stmt = (
                select(func.count())
                .select_from(join)
                .where(and_(
                    *pool_conditions,
                    shares.c.orgID == INTAM_ORG_ID,
                    players.c.age >= 18,
                ))
            )
            college_count = conn.execute(college_count_stmt).scalar()
            intam_count = conn.execute(intam_count_stmt).scalar()

            # Paginated data
            data_stmt = (
                select(*select_cols)
                .select_from(join)
                .where(where)
                .order_by(order)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            rows = conn.execute(data_stmt).all()

        players_list = _build_player_list(rows, tables)
        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            pool_counts={"college": college_count, "intam": intam_count},
            players=players_list,
        ), 200

    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error loading pro scouting pool"), 500


# -------------------------------------------------------------------
# Endpoint 2: College Recruiting Pool
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/college-pool")
def api_college_pool():
    """
    Paginated list of HS players available for college recruiting.
    Supports ?age=17 for "Class of" tabs (seniors, juniors, etc).
    Returns age_counts for tab badge rendering.
    """
    try:
        page, per_page = _parse_pagination()
        join, tables = _build_join_chain()

        contracts = tables["contracts"]
        shares = tables["contract_team_share"]
        orgs = tables["organizations"]
        players = tables["players"]

        # Base conditions: active contract at USHS
        conditions = [
            contracts.c.isActive == 1,
            shares.c.isHolder == 1,
            shares.c.orgID == USHS_ORG_ID,
        ]

        # Optional age class filter
        age = request.args.get("age", type=int)
        if age is not None:
            conditions.append(players.c.age == age)

        # Common filters (ptype, area, search)
        _apply_common_filters(conditions, tables)

        where = and_(*conditions)
        order = _parse_sort(tables)

        # Build column selection
        scouting_cols = _get_scouting_columns()
        select_cols = [
            *scouting_cols,
            orgs.c.id.label("org_id"),
            orgs.c.org_abbrev.label("org_abbrev"),
            contracts.c.current_level.label("current_level"),
        ]

        engine = get_engine()
        with engine.connect() as conn:
            # Total count (with current filters)
            count_stmt = (
                select(func.count())
                .select_from(join)
                .where(where)
            )
            total = conn.execute(count_stmt).scalar()

            # Age breakdown counts (always full HS pool, ignoring age filter)
            hs_base_conditions = [
                contracts.c.isActive == 1,
                shares.c.isHolder == 1,
                shares.c.orgID == USHS_ORG_ID,
            ]
            age_counts_stmt = (
                select(
                    players.c.age,
                    func.count().label("cnt"),
                )
                .select_from(join)
                .where(and_(*hs_base_conditions))
                .group_by(players.c.age)
                .order_by(players.c.age)
            )
            age_rows = conn.execute(age_counts_stmt).all()
            age_counts = {str(row[0]): row[1] for row in age_rows}

            # Paginated data
            data_stmt = (
                select(*select_cols)
                .select_from(join)
                .where(where)
                .order_by(order)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            rows = conn.execute(data_stmt).all()

        players_list = _build_player_list(rows, tables)
        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            age_counts=age_counts,
            players=players_list,
        ), 200

    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error loading college recruiting pool"), 500


# -------------------------------------------------------------------
# Endpoint 3: Scouting Budget
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/budget/<int:org_id>")
def api_scouting_budget(org_id):
    """Return scouting budget for an org in a given league year."""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400

    try:
        engine = get_engine()
        with engine.begin() as conn:
            budget = get_or_create_budget(conn, org_id, league_year_id)

        return jsonify(
            org_id=org_id,
            league_year_id=league_year_id,
            total_points=budget["total_points"],
            spent_points=budget["spent_points"],
            remaining_points=budget["total_points"] - budget["spent_points"],
        ), 200

    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -------------------------------------------------------------------
# Endpoint 4: Perform Scouting Action
# -------------------------------------------------------------------

@scouting_bp.post("/scouting/action")
def api_scouting_action():
    """
    Spend scouting points to unlock player information.

    Body: { org_id, league_year_id, player_id, action_type }
    action_type: 'hs_report' | 'hs_potential' | 'pro_numeric'
    """
    body = request.get_json(silent=True) or {}
    required = ["org_id", "league_year_id", "player_id", "action_type"]
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify(error="missing_fields", fields=missing), 400

    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = perform_scouting_action(
                conn,
                org_id=int(body["org_id"]),
                league_year_id=int(body["league_year_id"]),
                player_id=int(body["player_id"]),
                action_type=body["action_type"],
            )
        return jsonify(result), 200

    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -------------------------------------------------------------------
# Endpoint 5: Scouted Player Profile
# -------------------------------------------------------------------

# Bio fields always included in player profile
_BIO_FIELDS = {
    "id", "firstname", "lastname", "age", "ptype",
    "area", "city", "intorusa",
    "height", "weight", "bat_hand", "pitch_hand",
    "arm_angle", "durability", "injury_risk",
    "pitch1_name", "pitch2_name", "pitch3_name", "pitch4_name", "pitch5_name",
}


@scouting_bp.get("/scouting/player/<int:player_id>")
def api_scouted_player(player_id):
    """
    Get player data at the requesting org's scouting visibility level.

    Query params: org_id (required), league_year_id (required)

    Response varies by pool and unlock level:
      HS free:      bio + generated_stats
      HS report:    bio + generated_stats + text_report
      HS potential: bio + generated_stats + text_report + potentials
      College/INTAM free:    bio + letter_grades (+ counting_stats for INTAM)
      College/INTAM numeric: bio + attributes
      MLB FA:       bio + attributes + potentials
    """
    org_id = request.args.get("org_id", type=int)
    league_year_id = request.args.get("league_year_id", type=int)
    if not org_id or not league_year_id:
        return jsonify(error="missing_fields", fields=["org_id", "league_year_id"]), 400

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Get visibility
            visibility = get_player_scouting_visibility(conn, org_id, player_id)

            if visibility["pool"] == "none":
                return jsonify(error="not_found", message="Player not found"), 404

            # Load full player data
            row = conn.execute(
                sa_text("SELECT * FROM simbbPlayers WHERE id = :pid"),
                {"pid": player_id},
            ).first()

            if not row:
                return jsonify(error="not_found", message="Player not found"), 404

            player_dict = {}
            for key, value in row._mapping.items():
                if hasattr(value, "is_finite"):
                    value = float(value)
                player_dict[key] = value

        # Build response based on visibility
        response = _build_scouted_response(player_dict, visibility)
        response["visibility"] = visibility

        return jsonify(response), 200

    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


def _build_scouted_response(player, visibility):
    """Build the response dict with appropriate data masking."""
    pool = visibility["pool"]
    unlocked = visibility["unlocked"]

    # Bio is always included
    bio = {k: player.get(k) for k in _BIO_FIELDS if k in player}
    response = {"bio": bio}

    if pool == "hs":
        # Stats always visible for HS
        level = "hs"
        response["generated_stats"] = generate_scouting_stats(player, level)

        # Text report if unlocked
        if "hs_report" in unlocked:
            response["text_report"] = generate_text_report(player, level)

        # Potentials if unlocked
        if "hs_potential" in unlocked:
            potentials = {}
            for k, v in player.items():
                if k.endswith("_pot"):
                    potentials[k] = v
            response["potentials"] = potentials

    elif pool in ("college", "intam"):
        level = pool

        # Letter grades always visible (convert _base to grade)
        letter_grades = {}
        for k, v in player.items():
            if k.endswith("_base"):
                ability_name = k[:-5]  # strip _base
                letter_grades[ability_name] = base_to_letter_grade(v)
        response["letter_grades"] = letter_grades

        # INTAM: counting stats always visible
        if pool == "intam":
            response["counting_stats"] = generate_scouting_stats(player, level)

        # Numeric attributes if unlocked
        if "pro_numeric" in unlocked:
            attributes = {}
            for k, v in player.items():
                if k.endswith("_base"):
                    attributes[k] = v
            # Include pitch OVRs
            for i in range(1, 6):
                ovr_key = f"pitch{i}_ovr"
                if ovr_key in player:
                    attributes[ovr_key] = player[ovr_key]
            response["attributes"] = attributes

    elif pool == "mlb_fa":
        # Full visibility
        attributes = {}
        potentials = {}
        for k, v in player.items():
            if k.endswith("_base"):
                attributes[k] = v
            elif k.endswith("_pot"):
                potentials[k] = v
        # Include pitch OVRs
        for i in range(1, 6):
            ovr_key = f"pitch{i}_ovr"
            if ovr_key in player:
                attributes[ovr_key] = player[ovr_key]
        response["attributes"] = attributes
        response["potentials"] = potentials

    return response


# -------------------------------------------------------------------
# Endpoint 6: Scouting Action History
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/actions/<int:org_id>")
def api_scouting_actions(org_id):
    """List all scouting actions by an org in a given league year."""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400

    try:
        engine = get_engine()
        with engine.connect() as conn:
            actions = get_org_scouting_actions(conn, org_id, league_year_id)
            budget = get_or_create_budget(conn, org_id, league_year_id)

        return jsonify(
            org_id=org_id,
            league_year_id=league_year_id,
            budget={
                "total_points": budget["total_points"],
                "spent_points": budget["spent_points"],
                "remaining_points": budget["total_points"] - budget["spent_points"],
            },
            actions=actions,
        ), 200

    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500
