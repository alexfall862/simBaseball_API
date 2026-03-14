# scouting/__init__.py
"""
Scouting pool endpoints — paginated, filterable player browsing
for pro scouting (MLB draft/FA) and college recruiting.

Also provides scouting action endpoints for budget management,
unlocking player information, and visibility-based player profiles.

All endpoints under /scouting/.
"""

import logging
import math
import re
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)
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
    ALL_ACTION_TYPES,
)
from services.scouting_stats import generate_scouting_stats
from services.scouting_reports import generate_text_report
from services.attribute_visibility import (
    get_visible_player,
    determine_player_context,
    fuzz_letter_grade,
    fuzz_20_80,
    base_to_letter_grade as visibility_base_to_letter_grade,
    PITCH_COMPONENT_RE as VIS_PITCH_RE,
)
from services.rating_config import get_rating_config_by_level_name

scouting_bp = Blueprint("scouting", __name__)

# Org ID constants
INTAM_ORG_ID = 339
USHS_ORG_ID = 340
COLLEGE_ORG_MIN = 31
COLLEGE_ORG_MAX = 342
MLB_ORG_MIN = 1
MLB_ORG_MAX = 30

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
    "star_rating",
}

# Potential (_pot) fields that use letter-grade sort ordering
POT_SORT_FIELDS = {
    "contact_pot", "power_pot", "eye_pot", "discipline_pot",
    "speed_pot", "baserunning_pot",
    "fieldcatch_pot", "fieldreact_pot", "throwacc_pot", "throwpower_pot",
    "pendurance_pot", "pgencontrol_pot", "pthrowpower_pot", "psequencing_pot",
}

# Letter-grade sort order (lower number = better grade)
_GRADE_ORDER = {
    "A+": 1, "A": 2, "A-": 3,
    "B+": 4, "B": 5, "B-": 6,
    "C+": 7, "C": 8, "C-": 9,
    "D+": 10, "D": 11, "D-": 12,
    "F": 13, "N": 14,
}
_GRADE_ORDER_WORST = 15  # for null/unknown values

# Generated-stats sort aliases (Python-side sorting after stat computation)
GENERATED_STAT_SORTS = {
    # Batting
    "batting_avg":    ("batting", "avg"),
    "batting_obp":    ("batting", "obp"),
    "batting_slg":    ("batting", "slg"),
    "batting_hr":     ("batting", "home_runs"),
    "batting_rbi":    ("batting", "rbi"),
    "batting_runs":   ("batting", "runs"),
    "batting_sb":     ("batting", "stolen_bases"),
    "batting_so":     ("batting", "strikeouts"),
    # Pitching
    "pitching_era":   ("pitching", "era"),
    "pitching_k9":    ("pitching", "k_per_9"),
    "pitching_bb9":   ("pitching", "bb_per_9"),
    "pitching_whip":  ("pitching", "whip"),
    "pitching_wins":  ("pitching", "wins"),
    "pitching_so":    ("pitching", "strikeouts"),
    "pitching_ip":    ("pitching", "innings_pitched"),
    # Fielding
    "fielding_fpct":  ("fielding", "fielding_pct"),
    "fielding_errors": ("fielding", "errors"),
    "fielding_po":    ("fielding", "putouts"),
    "fielding_a":     ("fielding", "assists"),
}

# Generated-stats filter aliases — same mapping, used for min/max filters
# Query params: ?filter_batting_avg_min=0.250&filter_pitching_era_max=4.50
GENERATED_STAT_FILTERS = GENERATED_STAT_SORTS  # same key → (section, field)


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
    """Build the standard contract -> player join chain."""
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
    """
    Parse sort column and direction from query string.

    Returns (sql_order_clause_or_None, python_sort_key_or_None, direction).

    For regular columns and _pot fields: returns (sql_clause, None, dir).
    For generated-stat aliases: returns (None, sort_key_name, dir)
        so the caller knows to sort in Python after stat generation.
    For star_rating: returns (None, "star_rating", dir) — also Python-side
        since star_rating is added after the SQL query.
    """
    sort_name = request.args.get("sort", "lastname")
    direction = request.args.get("dir", "asc").lower()
    if direction not in ("asc", "desc"):
        direction = "asc"

    # Generated-stat sort → Python-side
    if sort_name in GENERATED_STAT_SORTS:
        return None, sort_name, direction

    # star_rating → Python-side (added post-query)
    if sort_name == "star_rating":
        return None, "star_rating", direction

    # Potential field → SQL CASE expression for letter-grade ordering
    if sort_name in POT_SORT_FIELDS:
        players = tables["players"]
        pot_col = players.c[sort_name]
        whens = [(pot_col == grade, rank) for grade, rank in _GRADE_ORDER.items()]
        sort_expr = case(*whens, else_=_GRADE_ORDER_WORST)
        sql_clause = sort_expr.asc() if direction == "asc" else sort_expr.desc()
        return sql_clause, None, direction

    # Regular column sort
    if sort_name not in ALLOWED_SORTS:
        sort_name = "lastname"

    players = tables["players"]
    sort_col = players.c[sort_name]
    sql_clause = sort_col.asc() if direction == "asc" else sort_col.desc()
    return sql_clause, None, direction


def _apply_common_filters(conditions, tables):
    """Apply ptype, area, search, pot whitelist, and base range filters."""
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

    # Potential grade whitelist filters: ?filter_contact_pot=A+,A,A-
    for pot_field in POT_SORT_FIELDS:
        param = request.args.get(f"filter_{pot_field}")
        if param:
            allowed_grades = [g.strip() for g in param.split(",") if g.strip() in _GRADE_ORDER or g.strip() == "N"]
            if allowed_grades:
                conditions.append(players.c[pot_field].in_(allowed_grades))

    # Base attribute range filters: ?filter_power_base_min=50&filter_power_base_max=80
    for col_name in ALLOWED_SORTS:
        if not col_name.endswith("_base"):
            continue
        min_val = request.args.get(f"filter_{col_name}_min", type=float)
        max_val = request.args.get(f"filter_{col_name}_max", type=float)
        if min_val is not None:
            conditions.append(players.c[col_name] >= min_val)
        if max_val is not None:
            conditions.append(players.c[col_name] <= max_val)

    # Star rating range: ?filter_star_rating_min=3&filter_star_rating_max=5
    # (handled Python-side since star_rating is added post-query)


def _parse_python_filters():
    """
    Parse generated-stat and star_rating filters from query string.

    Returns a list of (test_fn, label) tuples. Each test_fn takes a player
    dict and returns True if the player passes the filter.

    Query params:
      ?filter_batting_avg_min=0.250
      ?filter_batting_avg_max=0.350
      ?filter_pitching_era_max=4.50
      ?filter_fielding_fpct_min=0.950
      ?filter_star_rating_min=3
      ?filter_star_rating_max=5
    """
    filters = []

    # Generated stat range filters
    for key, (section, field) in GENERATED_STAT_FILTERS.items():
        min_val = request.args.get(f"filter_{key}_min", type=float)
        max_val = request.args.get(f"filter_{key}_max", type=float)
        if min_val is not None:
            v = min_val
            filters.append(
                lambda p, s=section, f=field, mv=v: (
                    (p.get("generated_stats") or {}).get(s, {}).get(f) or 0
                ) >= mv
            )
        if max_val is not None:
            v = max_val
            filters.append(
                lambda p, s=section, f=field, mv=v: (
                    (p.get("generated_stats") or {}).get(s, {}).get(f) or 0
                ) <= mv
            )

    # Star filters only make sense when league_year_id is provided,
    # since star_rating data comes from recruiting_rankings which
    # requires league_year_id.  Without it every player has
    # star_rating=None and all filters would produce empty results.
    has_league_year = request.args.get("league_year_id", type=int) is not None

    # Exact star rating match: ?star_rating=3
    sr_exact = request.args.get("star_rating", type=int)
    if sr_exact is not None and has_league_year:
        filters.append(lambda p, mv=sr_exact: (p.get("star_rating") or 0) == mv)

    # Star rating range: ?filter_star_rating_min=3&filter_star_rating_max=5
    sr_min = request.args.get("filter_star_rating_min", type=float)
    sr_max = request.args.get("filter_star_rating_max", type=float)
    if sr_min is not None and has_league_year:
        filters.append(lambda p, mv=sr_min: (p.get("star_rating") or 0) >= mv)
    if sr_max is not None and has_league_year:
        filters.append(lambda p, mv=sr_max: (p.get("star_rating") or 0) <= mv)

    return filters


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


def _apply_pool_fuzz(players_list, viewing_org_id, pool):
    """
    Apply fog-of-war fuzz to pool listing results.

    For pool listings we apply lightweight fuzz without needing the full
    visibility service (no scouting action lookups — pool views show
    the public fuzzed baseline).
    """
    if not viewing_org_id:
        return players_list

    for player in players_list:
        pid = player.get("id")
        if not pid:
            continue

        if pool == "hs":
            # College recruiting context: attributes hidden, potentials unknown
            for key in list(player.keys()):
                if key.endswith("_base"):
                    player[key] = None
                elif key.endswith("_pot"):
                    player[key] = "?"
        elif pool in ("college", "intam"):
            # Fuzz _base columns to letter grades for college/intam pool views
            for key in list(player.keys()):
                if key.endswith("_base"):
                    raw_val = player[key]
                    true_grade = base_to_letter_grade(raw_val)
                    player[key] = fuzz_letter_grade(
                        true_grade, viewing_org_id, pid, key
                    )
                elif key.endswith("_pot"):
                    true_pot = player[key]
                    if true_pot:
                        player[key] = fuzz_letter_grade(
                            true_pot, viewing_org_id, pid, key
                        )
                    else:
                        player[key] = "?"
        elif pool == "pro":
            # Pro roster context: fuzzed letter grades for pool listing
            for key in list(player.keys()):
                if key.endswith("_base"):
                    raw_val = player[key]
                    true_grade = base_to_letter_grade(raw_val)
                    player[key] = fuzz_letter_grade(
                        true_grade, viewing_org_id, pid, key
                    )
                elif key.endswith("_pot"):
                    true_pot = player[key]
                    if true_pot:
                        player[key] = fuzz_letter_grade(
                            true_pot, viewing_org_id, pid, key
                        )
                    else:
                        player[key] = "?"

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

    Optional: ?viewing_org_id=X to apply fog-of-war fuzz.
    """
    try:
        page, per_page = _parse_pagination()
        viewing_org_id = request.args.get("viewing_org_id", type=int)
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
        sql_order, _, _ = _parse_sort(tables)
        if sql_order is None:
            sql_order = tables["players"].c.lastname.asc()

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
                .order_by(sql_order)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            rows = conn.execute(data_stmt).all()

        players_list = _build_player_list(rows, tables)

        # Apply fog-of-war fuzz for pool listing
        if viewing_org_id:
            # Determine pool type per player based on their org
            for p in players_list:
                p_org = p.get("org_id", 0)
                if p_org == INTAM_ORG_ID:
                    _apply_pool_fuzz([p], viewing_org_id, "intam")
                else:
                    _apply_pool_fuzz([p], viewing_org_id, "college")

        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            pool_counts={"college": college_count, "intam": intam_count},
            players=players_list,
        ), 200

    except SQLAlchemyError as e:
        log.exception("pro-pool db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("pro-pool error")
        return jsonify(error="server_error", message=str(e)), 500


# -------------------------------------------------------------------
# Endpoint 2: College Recruiting Pool
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/college-pool")
def api_college_pool():
    """
    Paginated list of HS players available for college recruiting.
    Supports ?age=17 for "Class of" tabs (seniors, juniors, etc).
    Returns age_counts for tab badge rendering.

    Optional: ?viewing_org_id=X to apply fog-of-war fuzz.
    """
    try:
        page, per_page = _parse_pagination()
        viewing_org_id = request.args.get("viewing_org_id", type=int)
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
        sql_order, py_sort_key, sort_dir = _parse_sort(tables)
        py_filters = _parse_python_filters()
        # Need Python-side processing if sorting by generated stat/star
        # or if any generated-stat / star_rating filters are active
        needs_python_pass = py_sort_key is not None or len(py_filters) > 0

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

            # When Python-side filters/sort are needed, fetch all matching
            # rows so we can filter + sort + paginate in Python.
            # Otherwise SQL handles pagination directly.
            data_stmt = (
                select(*select_cols)
                .select_from(join)
                .where(where)
            )
            if needs_python_pass:
                data_stmt = data_stmt.order_by(
                    tables["players"].c.lastname.asc()
                )
            else:
                # Total count only needed for SQL-paginated path
                count_stmt = (
                    select(func.count())
                    .select_from(join)
                    .where(where)
                )
                total = conn.execute(count_stmt).scalar()
                data_stmt = (
                    data_stmt
                    .order_by(sql_order)
                    .limit(per_page)
                    .offset((page - 1) * per_page)
                )
            rows = conn.execute(data_stmt).all()

            # Batch-fetch star ratings from recruiting_rankings
            star_map = {}
            league_year_id = request.args.get("league_year_id", type=int)
            if league_year_id and rows:
                pids = [r._mapping["id"] for r in rows]
                ph = ", ".join([f":p{i}" for i in range(len(pids))])
                star_params = {"ly": league_year_id}
                star_params.update({f"p{i}": pid for i, pid in enumerate(pids)})
                star_rows = conn.execute(
                    sa_text(f"""
                        SELECT player_id, star_rating
                        FROM recruiting_rankings
                        WHERE league_year_id = :ly
                          AND player_id IN ({ph})
                    """),
                    star_params,
                ).all()
                star_map = {r[0]: r[1] for r in star_rows}

        players_list = _build_player_list(rows, tables)

        # Add star_rating to each player
        for player in players_list:
            player["star_rating"] = star_map.get(player["id"])

        # Generate deterministic stats from raw attributes (before fuzz)
        for player in players_list:
            player["generated_stats"] = generate_scouting_stats(player, "hs")

        # Python-side filter + sort + paginate
        if needs_python_pass:
            # Apply generated-stat and star_rating filters
            if py_filters:
                players_list = [
                    p for p in players_list
                    if all(fn(p) for fn in py_filters)
                ]

            # Sort
            reverse = sort_dir == "desc"
            if py_sort_key == "star_rating":
                players_list.sort(
                    key=lambda p: (p.get("star_rating") or 0),
                    reverse=reverse,
                )
            elif py_sort_key and py_sort_key in GENERATED_STAT_SORTS:
                section, field = GENERATED_STAT_SORTS[py_sort_key]
                players_list.sort(
                    key=lambda p: (
                        (p.get("generated_stats") or {}).get(section, {}).get(field) or 0
                    ),
                    reverse=reverse,
                )
            elif sql_order is not None:
                # Filters active but SQL sort — data is already ordered
                pass

            # Total reflects post-filter count
            total = len(players_list)

            # Manual pagination
            start = (page - 1) * per_page
            players_list = players_list[start:start + per_page]

        # Apply fog-of-war fuzz for HS pool
        if viewing_org_id:
            _apply_pool_fuzz(players_list, viewing_org_id, "hs")

        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            age_counts=age_counts,
            players=players_list,
        ), 200

    except SQLAlchemyError as e:
        log.exception("college-pool db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("college-pool error")
        return jsonify(error="server_error", message=str(e)), 500


# -------------------------------------------------------------------
# Endpoint 2b: INTAM Scouting Pool
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/intam-pool")
def api_intam_pool():
    """
    Paginated list of international amateur players (org 339, age 18+).

    Filters: ptype, area, search, min_age, max_age.
    Optional: ?viewing_org_id=X to apply fog-of-war fuzz.
    """
    try:
        page, per_page = _parse_pagination()
        viewing_org_id = request.args.get("viewing_org_id", type=int)
        join, tables = _build_join_chain()

        contracts = tables["contracts"]
        shares = tables["contract_team_share"]
        orgs = tables["organizations"]
        players = tables["players"]

        conditions = [
            contracts.c.isActive == 1,
            shares.c.isHolder == 1,
            shares.c.orgID == INTAM_ORG_ID,
            players.c.age >= 18,
        ]

        _apply_common_filters(conditions, tables)

        min_age = request.args.get("min_age", type=int)
        max_age = request.args.get("max_age", type=int)
        if min_age is not None:
            conditions.append(players.c.age >= min_age)
        if max_age is not None:
            conditions.append(players.c.age <= max_age)

        where = and_(*conditions)
        sql_order, _, _ = _parse_sort(tables)
        if sql_order is None:
            sql_order = tables["players"].c.lastname.asc()

        scouting_cols = _get_scouting_columns()
        select_cols = [
            *scouting_cols,
            orgs.c.id.label("org_id"),
            orgs.c.org_abbrev.label("org_abbrev"),
            contracts.c.current_level.label("current_level"),
        ]

        engine = get_engine()
        with engine.connect() as conn:
            count_stmt = (
                select(func.count())
                .select_from(join)
                .where(where)
            )
            total = conn.execute(count_stmt).scalar()

            data_stmt = (
                select(*select_cols)
                .select_from(join)
                .where(where)
                .order_by(sql_order)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            rows = conn.execute(data_stmt).all()

        players_list = _build_player_list(rows, tables)

        if viewing_org_id:
            _apply_pool_fuzz(players_list, viewing_org_id, "intam")

        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            players=players_list,
        ), 200

    except SQLAlchemyError as e:
        log.exception("intam-pool db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("intam-pool error")
        return jsonify(error="server_error", message=str(e)), 500


# -------------------------------------------------------------------
# Endpoint 2c: MLB / Pro Roster Scouting Pool
# -------------------------------------------------------------------

@scouting_bp.get("/scouting/mlb-pool")
def api_mlb_pool():
    """
    Paginated list of professional players on active rosters (levels 4-9).

    Filters: ptype, area, search, min_age, max_age, org_id, level.
    Optional: ?viewing_org_id=X to apply fog-of-war fuzz.

    Returns level_counts for level tab badges.
    """
    try:
        page, per_page = _parse_pagination()
        viewing_org_id = request.args.get("viewing_org_id", type=int)
        join, tables = _build_join_chain()

        contracts = tables["contracts"]
        shares = tables["contract_team_share"]
        orgs = tables["organizations"]
        players = tables["players"]

        # Pro rosters: orgs 1-30, levels 4-9
        conditions = [
            contracts.c.isActive == 1,
            shares.c.isHolder == 1,
            shares.c.orgID >= MLB_ORG_MIN,
            shares.c.orgID <= MLB_ORG_MAX,
            contracts.c.current_level.in_(["4", "5", "6", "7", "8", "9"]),
        ]

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

        level = request.args.get("level", type=str)
        if level is not None:
            conditions.append(contracts.c.current_level == level)

        where = and_(*conditions)
        sql_order, _, _ = _parse_sort(tables)
        if sql_order is None:
            sql_order = tables["players"].c.lastname.asc()

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

            # Level breakdown counts (full pro pool, ignoring level/org filter)
            pro_base_conditions = [
                contracts.c.isActive == 1,
                shares.c.isHolder == 1,
                shares.c.orgID >= MLB_ORG_MIN,
                shares.c.orgID <= MLB_ORG_MAX,
                contracts.c.current_level.in_(["4", "5", "6", "7", "8", "9"]),
            ]
            level_counts_stmt = (
                select(
                    contracts.c.current_level,
                    func.count().label("cnt"),
                )
                .select_from(join)
                .where(and_(*pro_base_conditions))
                .group_by(contracts.c.current_level)
                .order_by(contracts.c.current_level)
            )
            level_rows = conn.execute(level_counts_stmt).all()
            level_counts = {str(row[0]): row[1] for row in level_rows}

            # Paginated data
            data_stmt = (
                select(*select_cols)
                .select_from(join)
                .where(where)
                .order_by(sql_order)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            rows = conn.execute(data_stmt).all()

        players_list = _build_player_list(rows, tables)

        if viewing_org_id:
            _apply_pool_fuzz(players_list, viewing_org_id, "pro")

        pages = math.ceil(total / per_page) if per_page else 1

        return jsonify(
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            level_counts=level_counts,
            players=players_list,
        ), 200

    except SQLAlchemyError as e:
        log.exception("mlb-pool db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("mlb-pool error")
        return jsonify(error="server_error", message=str(e)), 500


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
    except SQLAlchemyError as e:
        log.exception("scouting db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("scouting error")
        return jsonify(error="server_error", message=str(e)), 500


# -------------------------------------------------------------------
# Endpoint 4: Perform Scouting Action
# -------------------------------------------------------------------

@scouting_bp.post("/scouting/action")
def api_scouting_action():
    """
    Spend scouting points to unlock player information.

    Body: { org_id, league_year_id, player_id, action_type }
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
    except SQLAlchemyError as e:
        log.exception("scouting db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("scouting error")
        return jsonify(error="server_error", message=str(e)), 500


# -------------------------------------------------------------------
# Endpoint 4b: Batch Scouting Action
# -------------------------------------------------------------------

@scouting_bp.post("/scouting/action/batch")
def api_scouting_action_batch():
    """
    Batch-unlock the same action_type for multiple players.

    Body: { org_id, league_year_id, player_ids: [...], action_type }
    Validates budget upfront for total cost (per-player cost * new unlocks).
    Returns summary with successes, already_unlocked, errors.
    """
    body = request.get_json(silent=True) or {}
    required = ["org_id", "league_year_id", "player_ids", "action_type"]
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify(error="missing_fields", fields=missing), 400

    player_ids = body.get("player_ids", [])
    if not isinstance(player_ids, list) or len(player_ids) == 0:
        return jsonify(error="validation", message="player_ids must be a non-empty list"), 400

    if len(player_ids) > 200:
        return jsonify(error="validation", message="Maximum 200 players per batch"), 400

    action_type = body["action_type"]
    if action_type not in ALL_ACTION_TYPES:
        return jsonify(error="validation", message=f"Unknown action_type: {action_type}"), 400

    org_id = int(body["org_id"])
    league_year_id = int(body["league_year_id"])

    try:
        engine = get_engine()
        successes = []
        already_unlocked = []
        errors = []

        with engine.begin() as conn:
            for pid in player_ids:
                try:
                    result = perform_scouting_action(
                        conn,
                        org_id=org_id,
                        league_year_id=league_year_id,
                        player_id=int(pid),
                        action_type=action_type,
                    )
                    if result["status"] == "already_unlocked":
                        already_unlocked.append(int(pid))
                    else:
                        successes.append(int(pid))
                except ValueError as e:
                    errors.append({"player_id": int(pid), "error": str(e)})

            # Get final budget state
            budget = get_or_create_budget(conn, org_id, league_year_id)

        total_spent = sum(
            1 for _ in successes
        )  # actual cost per player resolved inside perform_scouting_action

        return jsonify(
            successes=successes,
            already_unlocked=already_unlocked,
            errors=errors,
            budget={
                "total_points": budget["total_points"],
                "spent_points": budget["spent_points"],
                "remaining_points": budget["total_points"] - budget["spent_points"],
            },
        ), 200

    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError as e:
        log.exception("scouting db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("scouting error")
        return jsonify(error="server_error", message=str(e)), 500


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
    "org_id", "org_abbrev",
}


@scouting_bp.get("/scouting/player/<int:player_id>")
def api_scouted_player(player_id):
    """
    Get player data at the requesting org's scouting visibility level.

    Query params: org_id (required), league_year_id (required)

    Uses the fog-of-war visibility system to determine what the
    requesting org can see. Response includes visibility_context
    metadata indicating the display format.
    """
    org_id = request.args.get("org_id", type=int)
    league_year_id = request.args.get("league_year_id", type=int)
    if not org_id or not league_year_id:
        return jsonify(error="missing_fields", fields=["org_id", "league_year_id"]), 400

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Get visibility (pool + unlocked + available actions)
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

            # Load rating distributions for 20-80 conversion
            dist_by_level = get_rating_config_by_level_name(conn) or {}

            # Load contract data
            contract_row = conn.execute(
                sa_text("""
                    SELECT c.id AS contract_id, c.years, c.current_year,
                           c.leagueYearSigned, c.isActive, c.isBuyout,
                           c.isExtension, c.isFinished, c.current_level, c.onIR,
                           c.bonus,
                           cd.id AS detail_id, cd.year AS year_index,
                           cd.salary AS base_salary,
                           cts.salary_share,
                           cts.orgID AS org_id,
                           o.org_abbrev
                    FROM contracts c
                    JOIN contractDetails cd
                         ON cd.contractID = c.id AND cd.year = c.current_year
                    JOIN contractTeamShare cts
                         ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
                    JOIN organizations o
                         ON o.id = cts.orgID
                    WHERE c.playerID = :pid AND c.isActive = 1
                    LIMIT 1
                """),
                {"pid": player_id},
            ).first()

            # Build contract dict while connection is open
            contract = None
            if contract_row:
                cm = contract_row._mapping
                player_dict["current_level"] = cm["current_level"]
                player_dict["org_id"] = cm["org_id"]
                player_dict["org_abbrev"] = cm["org_abbrev"]
                base_salary = cm["base_salary"]
                share = cm["salary_share"]
                salary_for_org = None
                if base_salary is not None and share is not None:
                    try:
                        salary_for_org = float(base_salary) * float(share)
                    except (TypeError, ValueError):
                        pass
                contract = {
                    "id": cm["contract_id"],
                    "years": cm["years"],
                    "current_year": cm["current_year"],
                    "league_year_signed": cm["leagueYearSigned"],
                    "is_active": bool(cm["isActive"] or 0),
                    "is_buyout": bool(cm["isBuyout"] or 0),
                    "is_extension": bool(cm["isExtension"] or 0),
                    "is_finished": bool(cm["isFinished"] or 0),
                    "on_ir": bool(cm["onIR"] or 0),
                    "bonus": float(cm["bonus"] or 0),
                    "current_level": cm["current_level"],
                    "current_year_detail": {
                        "id": cm["detail_id"],
                        "year_index": cm["year_index"],
                        "base_salary": float(base_salary) if base_salary is not None else None,
                        "salary_share": float(share) if share is not None else None,
                        "salary_for_org": salary_for_org,
                    },
                }

        # Pass org_id into visibility for fuzz functions
        visibility["_org_id"] = org_id

        # Build response based on visibility
        response = _build_scouted_response(player_dict, visibility, dist_by_level)
        response["contract"] = contract

        # Attach listed position
        try:
            from services.listed_position import POSITION_DISPLAY
            with engine.connect() as conn2:
                lp_row = conn2.execute(sa_text(
                    "SELECT position_code FROM player_listed_position "
                    "WHERE player_id = :pid LIMIT 1"
                ), {"pid": player_id}).first()
            if lp_row:
                response["listed_position"] = POSITION_DISPLAY.get(lp_row[0], lp_row[0])
            else:
                response["listed_position"] = None
        except Exception:
            response["listed_position"] = None

        # Remove internal field before returning
        del visibility["_org_id"]
        response["visibility"] = visibility

        return jsonify(response), 200

    except SQLAlchemyError as e:
        log.exception("scouting db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("scouting error")
        return jsonify(error="server_error", message=str(e)), 500


_LEVEL_MAP = {
    9: "mlb", 8: "aaa", 7: "aa", 6: "higha", 5: "a", 4: "scraps",
    3: "college", 2: "intam", 1: "hs",
}

_PITCH_COMP_RE = re.compile(r"^pitch\d+_(pacc|pbrk|pcntrl|consist)_base$")


def _to_20_80(raw_val, mean, std):
    """Convert a raw _base value to 20-80 scale (same formula as bootstrap)."""
    if raw_val is None or mean is None:
        return None
    try:
        x = float(raw_val)
    except (TypeError, ValueError):
        return None
    if std is None or std <= 0:
        z = 0.0
    else:
        z = (x - mean) / std
    z = max(-3.0, min(3.0, z))
    raw_score = 50.0 + (z / 3.0) * 30.0
    score = int(round(max(20.0, min(80.0, raw_score)) / 5.0) * 5)
    return max(20, min(80, score))


def _convert_attrs_to_20_80(player, dist_for_level, org_id, player_id, fuzzed):
    """
    Build an attributes dict with 20-80 scaled values.

    Keys use _display suffix (matching bootstrap format).
    If *fuzzed*, applies fuzz_20_80 after conversion.
    """
    attributes = {}
    for k, v in player.items():
        if not k.endswith("_base"):
            continue
        mp = _PITCH_COMP_RE.match(k)
        dist_key = f"pitch_{mp.group(1)}" if mp else k
        d = dist_for_level.get(dist_key)
        if d and d.get("mean") is not None:
            scaled = _to_20_80(v, d["mean"], d["std"])
        else:
            scaled = None
        display_key = k.replace("_base", "_display")
        if fuzzed and scaled is not None:
            scaled = fuzz_20_80(scaled, org_id, player_id, k)
        attributes[display_key] = scaled
    # Pitch overalls (derived) — scale them too
    for i in range(1, 6):
        ovr_key = f"pitch{i}_ovr"
        if ovr_key in player and player[ovr_key] is not None:
            d = dist_for_level.get(ovr_key)
            if d and d.get("mean") is not None:
                scaled = _to_20_80(player[ovr_key], d["mean"], d["std"])
            else:
                scaled = None
            if fuzzed and scaled is not None:
                scaled = fuzz_20_80(scaled, org_id, player_id, ovr_key)
            attributes[ovr_key] = scaled
    return attributes


def _build_scouted_response(player, visibility, dist_by_level=None):
    """
    Build the response dict with fog-of-war data masking.

    Applies org-specific fuzz based on pool and unlocked actions.
    Attributes are returned as 20-80 scaled values (not raw _base).
    """
    pool = visibility["pool"]
    unlocked = set(visibility["unlocked"])
    dist_by_level = dist_by_level or {}

    # Bio is always included
    bio = {k: player.get(k) for k in _BIO_FIELDS if k in player}
    response = {"bio": bio}

    # Extract org_id from visibility context (set by the endpoint)
    org_id = visibility.get("_org_id", 0)
    player_id = player.get("id", 0)

    # Resolve distribution for this player's ptype + level
    ptype = (player.get("ptype") or "").strip()
    current_level = player.get("current_level")
    league_level = _LEVEL_MAP.get(current_level, "mlb")
    ptype_dist = dist_by_level.get(ptype) or dist_by_level.get("all") or {}
    dist_for_level = ptype_dist.get(league_level, {})

    if pool == "hs":
        # Stats always visible for HS
        level = "hs"
        response["generated_stats"] = generate_scouting_stats(player, level)

        # Text report if unlocked
        if "hs_report" in unlocked:
            response["text_report"] = generate_text_report(player, level)

        # Potentials: ? / fuzzed / precise
        potentials = {}
        for k, v in player.items():
            if k.endswith("_pot"):
                if "recruit_potential_precise" in unlocked:
                    potentials[k] = v  # precise
                elif "recruit_potential_fuzzed" in unlocked:
                    potentials[k] = fuzz_letter_grade(v, org_id, player_id, k) if v else "?"
                else:
                    potentials[k] = "?"
        response["potentials"] = potentials

    elif pool in ("college", "intam"):
        level = pool

        # Letter grades: fuzzed per viewing org
        letter_grades = {}
        for k, v in player.items():
            if k.endswith("_base"):
                true_grade = base_to_letter_grade(v)
                letter_grades[k[:-5]] = fuzz_letter_grade(
                    true_grade, org_id, player_id, k
                ) if org_id else true_grade
        response["letter_grades"] = letter_grades

        # INTAM: counting stats always visible
        if pool == "intam":
            response["counting_stats"] = generate_scouting_stats(player, level)

        # Numeric attributes if unlocked (draft scouting) — now 20-80 scaled
        if "draft_attrs_precise" in unlocked:
            response["attributes"] = _convert_attrs_to_20_80(
                player, dist_for_level, org_id, player_id, fuzzed=False
            )
            response["display_format"] = "20-80"
        elif "draft_attrs_fuzzed" in unlocked:
            response["attributes"] = _convert_attrs_to_20_80(
                player, dist_for_level, org_id, player_id, fuzzed=True
            )
            response["display_format"] = "20-80-fuzzed"

        # Potentials
        potentials = {}
        for k, v in player.items():
            if k.endswith("_pot"):
                if "draft_potential_precise" in unlocked or "college_potential_precise" in unlocked:
                    potentials[k] = v  # precise
                else:
                    potentials[k] = fuzz_letter_grade(v, org_id, player_id, k) if v else "?"
        response["potentials"] = potentials

    elif pool == "pro":
        # Pro roster: 20-80 scaled, precise or fuzzed
        is_precise = "pro_attrs_precise" in unlocked or "draft_attrs_precise" in unlocked
        response["attributes"] = _convert_attrs_to_20_80(
            player, dist_for_level, org_id, player_id, fuzzed=not is_precise
        )

        if is_precise:
            response["display_format"] = "20-80"
        else:
            response["display_format"] = "20-80-fuzzed"

        # Potentials
        potentials = {}
        for k, v in player.items():
            if k.endswith("_pot"):
                if "pro_potential_precise" in unlocked or "draft_potential_precise" in unlocked:
                    potentials[k] = v
                else:
                    potentials[k] = fuzz_letter_grade(v, org_id, player_id, k) if v else "?"
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

    except SQLAlchemyError as e:
        log.exception("scouting db error")
        return jsonify(error="db_error", message=str(e)), 500
    except Exception as e:
        log.exception("scouting error")
        return jsonify(error="server_error", message=str(e)), 500
