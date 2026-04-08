# rosters/__init__.py

from typing import Dict
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import MetaData, Table, select, and_, literal, func, text as sa_text
from sqlalchemy.exc import SQLAlchemyError
import logging
import re
from db import get_engine
from services.attribute_visibility import get_visible_players_batch

logger = logging.getLogger(__name__)

rosters_bp = Blueprint("rosters", __name__)

# Re-export from shared player_display for backward compat
# (bootstrap, admin, game_payload all import from rosters)
from services.player_display import (  # noqa: F401, E402
    PITCH_COMPONENT_RE,
    _DEFAULT_POSITION_WEIGHTS,
    compute_derived_raw_ratings as _compute_derived_raw_ratings_plain,
    to_20_80 as _to_20_80,
    get_player_column_categories as _get_player_column_categories_shared,
    load_position_weights,
    load_dist_by_level,
    build_player_display,
    load_display_context,
)


def clear_rosters_caches() -> Dict[str, bool]:
    """
    Clear all in-memory caches in the rosters module.

    Returns:
        Dict with cache names and whether they were cleared (had data).
    """
    from services.player_display import clear_column_cache
    cleared = {}

    # Tables cache (stored on blueprint)
    cleared["tables"] = hasattr(rosters_bp, "_tables")
    if hasattr(rosters_bp, "_tables"):
        delattr(rosters_bp, "_tables")

    # Player column categories cache (shared service)
    clear_column_cache()
    cleared["player_col_cats"] = True

    return cleared

# -------------------------------------------------------------------
# Table reflection helpers
# -------------------------------------------------------------------
def _get_tables():
    """
    Reflect and cache the tables we need for roster & obligations queries.
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
            "levels": Table("levels", md, autoload_with=engine),
            "teams": Table("teams", md, autoload_with=engine),
            "league_years": Table("league_years", md, autoload_with=engine),
            "game_weeks": Table("game_weeks", md, autoload_with=engine),
            "league_state": Table("league_state", md, autoload_with=engine),
            "org_ledger_entries": Table("org_ledger_entries", md, autoload_with=engine),
            "team_weekly_record": Table("team_weekly_record", md, autoload_with=engine),
        }
    return rosters_bp._tables

def _get_player_column_categories():
    """Categorize simbbPlayers columns. Delegates to shared service."""
    return _get_player_column_categories_shared(get_engine())

def _load_stamina_for_players(conn, player_ids):
    """
    Batch-load current stamina from player_fatigue_state for a list of player IDs.

    Returns a dict: {player_id: {"stamina": int, "has_fatigue_data": bool}}
    Players without a fatigue row get stamina=100, has_fatigue_data=False.
    """
    if not player_ids:
        return {}

    # Resolve current league_year_id from league_state
    ly_row = conn.execute(sa_text(
        "SELECT current_league_year_id FROM league_state LIMIT 1"
    )).first()
    if not ly_row or not ly_row[0]:
        return {}
    league_year_id = ly_row[0]

    placeholders = ", ".join(f":p{i}" for i in range(len(player_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(player_ids)}
    params["lyid"] = league_year_id

    rows = conn.execute(sa_text(
        f"SELECT player_id, stamina "
        f"FROM player_fatigue_state "
        f"WHERE league_year_id = :lyid AND player_id IN ({placeholders})"
    ), params).all()

    stamina_map = {}
    for r in rows:
        stamina_map[r[0]] = {"stamina": r[1], "has_fatigue_data": True}

    return stamina_map


def _load_injury_data_for_players(conn, player_ids):
    """
    Bulk-load injury state, active event details, and combined maluses for a
    list of player IDs.

    Returns:
      {
        player_id: {
          "is_injured": bool,
          "combined_malus": {"contact": 0.7, "stamina_pct": 0.0, ...},
          "injury_details": [
            {
              "event_id": int,
              "injury_type_id": int,
              "injury_name": str,
              "weeks_remaining": int,
              "weeks_assigned": int,
              "effects": {"contact": 0.7, ...},
            },
            ...
          ],
        },
        ...
      }

    Players with no injury data get is_injured=False, empty malus and details.
    """
    if not player_ids:
        return {}

    from services.injuries import get_active_injury_malus_bulk, _parse_malus_json

    ph = ", ".join(f":p{i}" for i in range(len(player_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(player_ids)}

    # Combined malus (acute + career, multiplicative)
    combined_malus_by_player = get_active_injury_malus_bulk(conn, player_ids)

    # Active event details for display (only currently-injured players)
    rows = conn.execute(sa_text(f"""
        SELECT
            pie.id          AS event_id,
            pie.player_id,
            pie.injury_type_id,
            it.name         AS injury_name,
            pie.weeks_remaining,
            pie.weeks_assigned,
            pie.malus_json
        FROM player_injury_events pie
        JOIN player_injury_state pis ON pis.player_id = pie.player_id
        JOIN injury_types it ON it.id = pie.injury_type_id
        WHERE pie.player_id IN ({ph})
          AND pie.weeks_remaining > 0
          AND pis.status = 'injured'
    """), params).mappings().all()

    details_by_player = {}
    for r in rows:
        pid = int(r["player_id"])
        details_by_player.setdefault(pid, []).append({
            "event_id": int(r["event_id"]),
            "injury_type_id": int(r["injury_type_id"]),
            "injury_name": r["injury_name"],
            "weeks_remaining": int(r["weeks_remaining"]),
            "weeks_assigned": int(r["weeks_assigned"]),
            "effects": _parse_malus_json(r["malus_json"]),
        })

    result = {}
    for pid in player_ids:
        result[pid] = {
            "is_injured": pid in details_by_player,
            "combined_malus": combined_malus_by_player.get(pid, {}),
            "injury_details": details_by_player.get(pid, []),
        }
    return result


def _attach_injury_and_stamina_to_players(conn, players_out):
    """
    For each player dict in players_out:
      - Apply active injury maluses to all *_base attributes (multiplicative).
      - Apply stamina_pct malus to stamina (zeroes it when benched by injury).
      - Attach stamina, has_fatigue_data, is_injured, injury_details.
    """
    pids = [p["id"] for p in players_out if p.get("id")]
    if not pids:
        return

    stamina_map = _load_stamina_for_players(conn, pids)
    injury_map = _load_injury_data_for_players(conn, pids)

    for p in players_out:
        pid = p.get("id")
        if pid is None:
            continue

        # --- stamina ---
        raw = stamina_map.get(pid)
        stamina_val = int(raw["stamina"]) if raw else 100
        p["has_fatigue_data"] = bool(raw)

        inj = injury_map.get(pid, {})
        malus = inj.get("combined_malus", {})

        # Apply stamina_pct (e.g. 0.0 forces stamina to 0 for benched players)
        stam_pct = malus.get("stamina_pct")
        if stam_pct is not None:
            stamina_val = int(max(0, stamina_val * float(stam_pct)))
        p["stamina"] = stamina_val

        # --- attribute maluses ---
        # _build_player_with_ratings stores scaled 20-80 values under
        # p["ratings"]["contact_display"], not at the top level.
        # Apply malus factor proportionally to each *_display entry.
        ratings = p.get("ratings")
        if isinstance(ratings, dict):
            for attr, factor in malus.items():
                if attr == "stamina_pct":
                    continue
                display_key = f"{attr}_display"
                if display_key in ratings and ratings[display_key] is not None:
                    try:
                        ratings[display_key] = float(ratings[display_key]) * float(factor)
                    except (TypeError, ValueError):
                        pass

        # --- injury fields ---
        p["is_injured"] = inj.get("is_injured", False)
        p["injury_details"] = inj.get("injury_details", [])



# Backward-compat wrapper: accepts SQLAlchemy Row (extracts ._mapping)
def _compute_derived_raw_ratings(row, position_weights=None):
    """Compute derived ratings. Accepts SQLAlchemy Row or plain dict."""
    if hasattr(row, "_mapping"):
        mapping = dict(row._mapping)
    else:
        mapping = row
    return _compute_derived_raw_ratings_plain(mapping, position_weights)

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

def _build_ratings_base_stmt(level_filter=None, org_abbrev=None, team_abbrev=None):
    """
    Build a SELECT that returns:
      - org_id, org_abbrev
      - current_level (int)
      - league_level (string, e.g. 'mlb', 'aa')
      - team_abbrev (from teams)
      - all simbbPlayers columns
      - selected contract metadata for the *current* active, holding contract

    Filters:
      - contracts.isActive = 1
      - contractTeamShare.isHolder = 1
      - optional level_filter: int or (min_level, max_level)
      - optional org_abbrev
      - optional team_abbrev
    """
    tables = _get_tables()
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    orgs = tables["organizations"]
    players = tables["players"]
    teams = tables["teams"]
    levels = tables["levels"]

    conditions = [
        contracts.c.isActive == 1,
        shares.c.isHolder == 1,
    ]

    # Level filter: either single int or (min_level, max_level)
    if isinstance(level_filter, int):
        conditions.append(contracts.c.current_level == level_filter)
    elif isinstance(level_filter, tuple) and len(level_filter) == 2:
        min_level, max_level = level_filter
        if min_level is not None:
            conditions.append(contracts.c.current_level >= min_level)
        if max_level is not None:
            conditions.append(contracts.c.current_level <= max_level)

    if org_abbrev:
        conditions.append(orgs.c.org_abbrev == org_abbrev)

    if team_abbrev:
        conditions.append(teams.c.team_abbrev == team_abbrev)

    stmt = (
        select(
            # Org / level / team
            orgs.c.id.label("org_id"),
            orgs.c.org_abbrev.label("org_abbrev"),
            contracts.c.current_level.label("current_level"),
            levels.c.league_level.label("league_level"),
            teams.c.team_abbrev.label("team_abbrev"),

            # Contract metadata (current active holding contract)
            contracts.c.id.label("contract_id"),
            contracts.c.years.label("contract_years"),
            contracts.c.current_year.label("contract_current_year"),
            contracts.c.leagueYearSigned.label("contract_leagueYearSigned"),
            contracts.c.isActive.label("contract_isActive"),
            contracts.c.isBuyout.label("contract_isBuyout"),
            contracts.c.isExtension.label("contract_isExtension"),
            contracts.c.isFinished.label("contract_isFinished"),
            contracts.c.onIR.label("contract_onIR"),

            # Current-year detail row (for this contract)
            details.c.id.label("contractDetails_id"),
            details.c.year.label("contractDetails_year_index"),
            details.c.salary.label("contractDetails_salary"),

            # Team share for that detail row
            shares.c.salary_share.label("contractTeam_salary_share"),

            # All player columns
            players,
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
            .join(
                levels,
                levels.c.id == contracts.c.current_level,
            )
            .outerjoin(
                teams,
                and_(
                    teams.c.orgID == orgs.c.id,
                    teams.c.team_level == contracts.c.current_level,
                ),
            )
        )
        .where(and_(*conditions))
    )

    return stmt

def _compute_distributions_by_level(rows, rating_cols, include_derived=False, position_weights=None):
    """
    Given a list of rows (with 'league_level' and/or 'current_level'),
    compute mean and stddev for each rating dimension per level.

    Behavior:
      - For non-pitch *_base columns: each column gets its own distribution
        key, e.g. "contact_base", "speed_base".
      - For pitch component *_base columns (pitchN_pacc/pbrk/pcntrl/consist_base):
        we POOL values across all pitchN for that component at a given level:
          * all pitchN_pacc_base contribute to a single "pitch_pacc" dist
          * all pitchN_pbrk_base -> "pitch_pbrk"
          * all pitchN_pcntrl_base -> "pitch_pcntrl"
          * all pitchN_consist_base -> "pitch_consist"

    If include_derived is True, we also compute distributions for:
      - c_rating, fb_rating
      - pitch1_ovr ... pitch5_ovr
    based on _compute_derived_raw_ratings.
    """
    # --- Base attributes (includes pooled pitch components) ---
    level_attr_values = {}

    for row in rows:
        m = row._mapping
        level_key = m.get("league_level") or m.get("current_level")
        if level_key is None:
            continue

        level_bucket = level_attr_values.setdefault(level_key, {})

        for col in rating_cols:
            val = m.get(col)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue

            # Check if this is a pitch component column
            m_pitch = PITCH_COMPONENT_RE.match(col)
            if m_pitch:
                component = m_pitch.group(1)  # pacc / pbrk / pcntrl / consist
                # pooled key per component
                dist_key = f"pitch_{component}"
            else:
                # normal attribute: use column name directly
                dist_key = col

            level_bucket.setdefault(dist_key, []).append(num)

    dist = {}
    for level_key, attrs in level_attr_values.items():
        dist[level_key] = {}
        for dist_key, vals in attrs.items():
            if not vals:
                dist[level_key][dist_key] = {"mean": None, "std": None}
            elif len(vals) == 1:
                mean = float(vals[0])
                dist[level_key][dist_key] = {"mean": mean, "std": 0.0}
            else:
                mean = float(sum(vals) / len(vals))
                var = sum((v - mean) ** 2 for v in vals) / len(vals)  # population variance
                std = var ** 0.5
                dist[level_key][dist_key] = {"mean": mean, "std": std}

    # --- Derived attributes (position ratings, pitch overalls) ---
    if include_derived:
        derived_values = {}

        for row in rows:
            m = row._mapping
            level_key = m.get("league_level") or m.get("current_level")
            if level_key is None:
                continue

            raw_derived = _compute_derived_raw_ratings(row, position_weights)
            if not raw_derived:
                continue

            lvl_bucket = derived_values.setdefault(level_key, {})
            for name, val in raw_derived.items():
                if val is None:
                    continue
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    continue
                lvl_bucket.setdefault(name, []).append(num)

        for level_key, attrs in derived_values.items():
            level_dist = dist.setdefault(level_key, {})
            for name, vals in attrs.items():
                if not vals:
                    continue
                if len(vals) == 1:
                    mean = float(vals[0])
                    std = 0.0
                else:
                    mean = float(sum(vals) / len(vals))
                    var = sum((v - mean) ** 2 for v in vals) / len(vals)
                    std = var ** 0.5
                level_dist[name] = {"mean": mean, "std": std}

    return dist


# _to_20_80 is imported from services.player_display above


def _build_player_with_ratings(row, dist_by_level, col_cats, position_weights=None):
    """
    Convert a row into a structured player dict.
    Delegates core bio/ratings/potentials to shared build_player_display(),
    then appends roster-specific fields (contract, org, team, level).
    """
    m = row._mapping

    ctx = {
        "col_cats": col_cats,
        "dist_by_level": dist_by_level,
        "position_weights": position_weights,
    }
    player = build_player_display(dict(m), ctx)

    # --- Contract metadata (roster-specific) ---
    def _num_or_none(val):
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    base_salary = _num_or_none(m.get("contractDetails_salary"))
    share = _num_or_none(m.get("contractTeam_salary_share"))
    salary_for_org = None
    if base_salary is not None and share is not None:
        salary_for_org = base_salary * share

    player["contract"] = {
        "id": m.get("contract_id"),
        "years": m.get("contract_years"),
        "current_year": m.get("contract_current_year"),
        "league_year_signed": m.get("contract_leagueYearSigned"),
        "is_active": bool(m.get("contract_isActive") or 0),
        "is_buyout": bool(m.get("contract_isBuyout") or 0),
        "is_extension": bool(m.get("contract_isExtension") or 0),
        "is_finished": bool(m.get("contract_isFinished") or 0),
        "on_ir": bool(m.get("contract_onIR") or 0),
        "current_year_detail": {
            "id": m.get("contractDetails_id"),
            "year_index": m.get("contractDetails_year_index"),
            "base_salary": base_salary,
            "salary_share": share,
            "salary_for_org": salary_for_org,
        },
    }
    player["org_abbrev"] = m.get("org_abbrev")
    player["league_level"] = m.get("league_level")
    player["current_level"] = m.get("current_level")
    player["team_abbrev"] = m.get("team_abbrev")

    return player

# -------------------------------------------------------------------
# Roster Display Endpoints
# -------------------------------------------------------------------

def _load_position_weights(conn):
    """Load position rating weights from DB, or None to use defaults."""
    return load_position_weights(conn)


def _load_dist_by_level(conn, col_cats):
    """
    Load distributions. Delegates to shared service, with local fallback
    for on-the-fly computation from active players.
    """
    result, source = load_dist_by_level(conn, col_cats)
    if result:
        return result, source

    # Fallback: compute from all active players (original behavior)
    all_stmt = _build_ratings_base_stmt(level_filter=(1, 9))
    all_rows = conn.execute(all_stmt).all()
    if not all_rows:
        return {}, "computed"

    dist = _compute_distributions_by_level(
        all_rows, col_cats["rating"], include_derived=True,
    )
    dist = {"all": dist}
    return dist, "computed"


def _apply_fog_of_war(conn, players_out, rows, viewing_org_id, dist_by_level, col_cats, position_weights):
    """
    Apply fog-of-war visibility to a list of player dicts.

    If viewing_org_id is None, returns players_out unchanged (admin/legacy).
    Otherwise, routes through the attribute_visibility service.

    rows: the original SQLAlchemy rows (used to extract holding_org_id and level)
    """
    if not viewing_org_id:
        return players_out

    # Build lookup dicts for holding org and level from the original rows
    holding_org_ids = {}
    player_levels = {}
    for row in rows:
        m = row._mapping
        pid = m.get("id")
        if pid is None:
            continue
        holding_org_ids[pid] = m.get("org_id", 0)
        player_levels[pid] = m.get("current_level", 0)

    return get_visible_players_batch(
        conn, players_out, viewing_org_id,
        holding_org_ids, player_levels,
        dist_by_level, col_cats, position_weights,
    )


@rosters_bp.get("/ratings/teams")
def get_team_ratings():
    """
    Team-level 20–80 ratings view.

    Query params:
      - level (required, int): league_level id (e.g. 9 for MLB)
      - team (optional, string): team_abbrev; if missing, returns ALL players at that level.

    Examples:
      /api/v1/ratings/teams?level=9&team=NYY
      /api/v1/ratings/teams?level=9
    """
    level = request.args.get("level", type=int)
    if level is None:
        return jsonify(
            error="missing_param",
            message="level query param (int) is required, e.g. ?level=9 for MLB"
        ), 400

    team_abbrev = request.args.get("team")
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400

    try:
        engine = get_engine()
        col_cats = _get_player_column_categories()

        with engine.connect() as conn:
            dist_by_level, _ = _load_dist_by_level(conn, col_cats)
            position_weights = _load_position_weights(conn)

            # Query only the players we need to return
            stmt = _build_ratings_base_stmt(
                level_filter=level,
                team_abbrev=team_abbrev,
            )
            rows = conn.execute(stmt).all()

            if not rows:
                return jsonify(
                    {
                        "league_level": None,
                        "league_level_id": level,
                        "team": team_abbrev,
                        "count": 0,
                        "players": [],
                    }
                ), 200

            players_out = [
                _build_player_with_ratings(row, dist_by_level, col_cats, position_weights)
                for row in rows
            ]

            # Apply fog-of-war if viewing_org_id provided
            players_out = _apply_fog_of_war(
                conn, players_out, rows, viewing_org_id,
                dist_by_level, col_cats, position_weights,
            )

    except SQLAlchemyError as e:
        current_app.logger.exception("get_team_ratings: db error")
        return jsonify(error="database_error", message=str(e)), 500

    # Determine league_level string for this level from the rows
    league_level_name = None
    for p in players_out:
        if p.get("league_level"):
            league_level_name = p["league_level"]
            break

    return jsonify(
        {
            "league_level": league_level_name,
            "league_level_id": level,
            "team": team_abbrev,
            "count": len(players_out),
            "players": players_out,
        }
    ), 200

@rosters_bp.get("/orgs/<string:org_abbrev>/ratings")
def get_org_ratings(org_abbrev: str):
    """
    Org-level 20–80 ratings, grouped by league_level string.

    Uses pro levels 4–9 by default (scraps → MLB).

    Example:
      /api/v1/orgs/NYY/ratings
    """
    # Pro levels range (4=scraps, 9=MLB)
    level_filter = (4, 9)
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400

    tables = _get_tables()
    orgs = tables["organizations"]

    try:
        engine = get_engine()
        col_cats = _get_player_column_categories()

        with engine.connect() as conn:
            # Ensure org exists
            org_row = conn.execute(
                select(orgs.c.id).where(orgs.c.org_abbrev == org_abbrev).limit(1)
            ).first()
            if not org_row:
                return jsonify(
                    error="org_not_found",
                    message=f"No organization with abbrev '{org_abbrev}'"
                ), 404

            org_id = org_row[0]

            dist_by_level, _ = _load_dist_by_level(conn, col_cats)
            position_weights = _load_position_weights(conn)

            # Query only this org's players
            org_stmt = _build_ratings_base_stmt(
                level_filter=level_filter,
                org_abbrev=org_abbrev,
            )
            org_rows = conn.execute(org_stmt).all()

            if not org_rows:
                return jsonify(
                    {
                        "org": org_abbrev,
                        "org_id": org_id,
                        "levels": {},
                    }
                ), 200

            # Build all player dicts first
            all_players = [
                _build_player_with_ratings(row, dist_by_level, col_cats, position_weights)
                for row in org_rows
            ]

            # Apply fog-of-war if viewing_org_id provided
            all_players = _apply_fog_of_war(
                conn, all_players, org_rows, viewing_org_id,
                dist_by_level, col_cats, position_weights,
            )

    except SQLAlchemyError as e:
        current_app.logger.exception("get_org_ratings: db error")
        return jsonify(error="database_error", message=str(e)), 500

    # Group by level
    levels_out = {}
    for i, row in enumerate(org_rows):
        m = row._mapping
        lvl_id = m.get("current_level")
        lvl_name = m.get("league_level")
        if lvl_id is None:
            continue

        key = lvl_name or str(lvl_id)
        bucket = levels_out.setdefault(
            key,
            {
                "league_level": key,
                "level_id": lvl_id,
                "players": [],
            },
        )
        bucket["players"].append(all_players[i])

    # Add counts
    for bucket in levels_out.values():
        bucket["count"] = len(bucket["players"])

    return jsonify(
        {
            "org": org_abbrev,
            "org_id": org_id,
            "levels": levels_out,
        }
    ), 200

@rosters_bp.get("/ratings")
def get_league_ratings():
    """
    League-wide 20–80 ratings, grouped by org then league_level string.

    Uses pro levels 4–9 by default.

    Required: ?viewing_org_id=X for fog-of-war.

    Example:
      /api/v1/ratings?viewing_org_id=5
    """
    level_filter = (4, 9)
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400

    try:
        engine = get_engine()
        col_cats = _get_player_column_categories()

        with engine.connect() as conn:
            dist_by_level, _ = _load_dist_by_level(conn, col_cats)
            position_weights = _load_position_weights(conn)

            stmt = _build_ratings_base_stmt(level_filter=level_filter)
            rows = conn.execute(stmt).all()

            if not rows:
                return jsonify({"levels": [], "orgs": {}}), 200

            # Build all player dicts, then apply fog-of-war
            all_players = [
                _build_player_with_ratings(row, dist_by_level, col_cats, position_weights)
                for row in rows
            ]
            all_players = _apply_fog_of_war(
                conn, all_players, rows, viewing_org_id,
                dist_by_level, col_cats, position_weights,
            )

    except SQLAlchemyError as e:
        current_app.logger.exception("get_league_ratings: db error")
        return jsonify(error="database_error", message=str(e)), 500

    orgs_out = {}
    level_names_set = set()

    for player, row in zip(all_players, rows):
        m = row._mapping
        org_id = m.get("org_id")
        org_abbrev = m.get("org_abbrev")
        lvl_id = m.get("current_level")
        lvl_name = m.get("league_level")
        if lvl_id is None:
            continue

        key_lvl = lvl_name or str(lvl_id)
        level_names_set.add(key_lvl)

        org_bucket = orgs_out.setdefault(
            org_abbrev,
            {
                "org_id": org_id,
                "org_abbrev": org_abbrev,
                "levels": {},
            },
        )
        lvl_bucket = org_bucket["levels"].setdefault(
            key_lvl,
            {
                "league_level": key_lvl,
                "level_id": lvl_id,
                "players": [],
            },
        )

        lvl_bucket["players"].append(player)

    # Add counts per level
    for org_bucket in orgs_out.values():
        for lvl_bucket in org_bucket["levels"].values():
            lvl_bucket["count"] = len(lvl_bucket["players"])

    level_names = sorted(level_names_set)

    return jsonify(
        {
            "levels": level_names,
            "orgs": orgs_out,
        }
    ), 200

# -------------------------------------------------------------------
# Face generation helper (reuses face_generator service from bootstrap)
# -------------------------------------------------------------------
def _generate_faces_for_rows(conn, rows):
    """
    Generate face data for a list of player rows.
    Returns {str(player_id): FaceDataResponse, ...}.
    """
    try:
        from services.face_generator import generate_face, get_team_jersey, load_face_config
        face_config = load_face_config(conn)
    except Exception:
        return {}

    result = {}
    # Cache jerseys per team
    jersey_cache = {}
    for row in rows:
        m = row._mapping
        pid = m.get("id")
        if pid is None:
            continue
        # Get team_id from the row; fall back to org_id-based lookup
        # _build_ratings_base_stmt labels team columns, but team_id
        # may not be directly available — use team_abbrev + current_level
        # to derive. However, the face generator just needs a stable int
        # for jersey determinism. Use org_id as the team grouping key.
        org_id = m.get("org_id") or 0
        level = m.get("current_level") or 0
        team_key = (int(org_id), int(level))

        if team_key not in jersey_cache:
            # Use org_id * 100 + level as a stable team_id for jersey generation
            jersey_cache[team_key] = get_team_jersey(int(org_id) * 100 + int(level), face_config)

        result[str(pid)] = generate_face(int(pid), face_config, jersey=jersey_cache[team_key])

    return result


# -------------------------------------------------------------------
# 1 & 2) All active players in an org, optionally at a specific level
# -------------------------------------------------------------------
@rosters_bp.get("/orgs/<string:org_abbrev>/roster")
def get_org_roster(org_abbrev: str):
    """
    Return all active players for a given organization with 20-80 scaled ratings.

    Query params:
      - level (optional, int): specific level_id (e.g. 8 for AAA, 9 for MLB)
      - min_level / max_level (optional, int): inclusive range of levels
      - include_faces (optional, "1"): include face data

    Examples:
      /api/v1/orgs/NYY/roster
      /api/v1/orgs/NYY/roster?level=8      # Yankees AAA
      /api/v1/orgs/NYY/roster?min_level=4&max_level=9  # all pro levels
    """
    include_faces = request.args.get("include_faces", "0") == "1"
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400

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

    try:
        engine = get_engine()
        col_cats = _get_player_column_categories()

        with engine.connect() as conn:
            dist_by_level, _ = _load_dist_by_level(conn, col_cats)
            position_weights = _load_position_weights(conn)

            stmt = _build_ratings_base_stmt(
                level_filter=level_filter,
                org_abbrev=org_abbrev,
            )
            rows = conn.execute(stmt).all()

            face_data = {}
            if include_faces and rows:
                face_data = _generate_faces_for_rows(conn, rows)

            # Deduplicate by player id
            players_out = []
            seen_ids = set()
            deduped_rows = []
            for row in rows:
                player = _build_player_with_ratings(
                    row, dist_by_level, col_cats, position_weights
                )
                pid = player.get("id")
                if pid is not None and pid in seen_ids:
                    continue
                if pid is not None:
                    seen_ids.add(pid)
                players_out.append(player)
                deduped_rows.append(row)

            # Apply fog-of-war if viewing_org_id provided
            players_out = _apply_fog_of_war(
                conn, players_out, deduped_rows, viewing_org_id,
                dist_by_level, col_cats, position_weights,
            )

            # Attach listed positions
            try:
                from services.listed_position import POSITION_DISPLAY  # noqa: F811
                pids = [p["id"] for p in players_out if p.get("id")]
                if pids:
                    ph = ", ".join(f":p{i}" for i in range(len(pids)))
                    prm = {f"p{i}": pid for i, pid in enumerate(pids)}
                    lp_rows = conn.execute(sa_text(
                        f"SELECT player_id, position_code "
                        f"FROM player_listed_position "
                        f"WHERE player_id IN ({ph})"
                    ), prm).all()
                    lp_map = {r[0]: POSITION_DISPLAY.get(r[1], r[1]) for r in lp_rows}
                    for p in players_out:
                        p["listed_position"] = lp_map.get(p["id"])
            except Exception:
                pass

            # Attach stamina data
            try:
                _attach_injury_and_stamina_to_players(conn, players_out)
            except Exception as exc:
                logger.warning("_attach_injury_and_stamina_to_players failed: %s", exc, exc_info=True)

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

    result = {
        "org": org_abbrev,
        "count": len(players_out),
        "players": players_out,
    }
    if include_faces:
        result["faces"] = face_data
    return jsonify(result), 200


# -------------------------------------------------------------------
# 3) All active players across DB, grouped by organization
# -------------------------------------------------------------------
@rosters_bp.get("/rosters")
def get_all_rosters_grouped():
    """
    Return active players across the database with 20-80 scaled ratings,
    structured identically to bootstrap (bio / ratings / potentials / contract).

    Optional: ?include_faces=1 to include face data for all returned players.

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
          "players": [...],
          "faces": {...}          // if include_faces=1
        }

      - ?org=NYY&level=aaa: same as above, restricted to that level.
        `level` may be either:
          - a numeric level id (e.g. 8), or
          - a league_level string (e.g. "aaa").

      - min_level / max_level (int) still work as before when you want ranges.

    Required: ?viewing_org_id=X for fog-of-war.
    """
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400

    org_abbrev = request.args.get("org")
    include_faces = request.args.get("include_faces", "0") == "1"

    # Level can be numeric (id) or a league_level string ("aaa", "mlb", ...)
    level_arg = request.args.get("level")
    min_level = request.args.get("min_level", type=int)
    max_level = request.args.get("max_level", type=int)

    level_filter = None

    if level_arg:
        # Try to interpret as integer level id first
        try:
            level_id = int(level_arg)
        except ValueError:
            # Not an int; treat as league_level string, look up in levels table
            tables = _get_tables()
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

    try:
        engine = get_engine()
        col_cats = _get_player_column_categories()

        with engine.connect() as conn:
            dist_by_level, _ = _load_dist_by_level(conn, col_cats)
            position_weights = _load_position_weights(conn)

            stmt = _build_ratings_base_stmt(
                level_filter=level_filter,
                org_abbrev=org_abbrev,
            )
            rows = conn.execute(stmt).all()

            # Build face data if requested
            face_data = {}
            if include_faces and rows:
                face_data = _generate_faces_for_rows(conn, rows)

            by_org = {}
            seen_per_org = {}

            for row in rows:
                m = row._mapping
                this_org_abbrev = m["org_abbrev"]
                org_id = m["org_id"]

                player = _build_player_with_ratings(
                    row, dist_by_level, col_cats, position_weights
                )
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

            # Apply fog-of-war to all players across all orgs
            all_players = [p for b in by_org.values() for p in b["players"]]
            # Build a row lookup for fog-of-war (needs holding_org_id + level)
            row_by_id = {r._mapping.get("id"): r for r in rows}
            matching_rows = [row_by_id[p["id"]] for p in all_players if p.get("id") in row_by_id]
            fogged = _apply_fog_of_war(
                conn, all_players, matching_rows, viewing_org_id,
                dist_by_level, col_cats, position_weights,
            )
            # Rebuild org buckets with fogged player dicts
            fogged_by_id = {p["id"]: p for p in fogged if p.get("id") is not None}
            for bucket in by_org.values():
                bucket["players"] = [
                    fogged_by_id.get(p.get("id"), p) for p in bucket["players"]
                ]
            all_players = fogged

            # Attach stamina to all players across all orgs
            try:
                _attach_injury_and_stamina_to_players(conn, all_players)
            except Exception as exc:
                logger.warning("_attach_injury_and_stamina_to_players failed: %s", exc, exc_info=True)

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

    # If org query param was provided, return a single-org structure
    if org_abbrev:
        org_bucket = by_org.get(
            org_abbrev,
            {"org_abbrev": org_abbrev, "org_id": None, "players": []},
        )
        players_out = org_bucket.get("players", [])
        result = {
            "org": org_abbrev,
            "org_id": org_bucket.get("org_id"),
            "count": len(players_out),
            "players": players_out,
        }
        if include_faces:
            result["faces"] = face_data
        return jsonify(result), 200

    # Otherwise, return the grouped-by-org map
    if include_faces:
        return jsonify({"rosters": by_org, "faces": face_data}), 200
    return jsonify(by_org), 200


# -------------------------------------------------------------------
# Global face data endpoint
# -------------------------------------------------------------------
@rosters_bp.get("/faces")
def get_faces():
    """
    Return face data for players.

    Query params:
      - org (optional): org abbreviation to filter by (e.g. NYY)
      - level (optional, int): level id to filter by
      - player_ids (optional): comma-separated player ids (e.g. 123,456,789)

    Returns: {"faces": {str(player_id): FaceDataResponse, ...}}
    """
    org_abbrev = request.args.get("org")
    level = request.args.get("level", type=int)
    player_ids_param = request.args.get("player_ids")

    try:
        engine = get_engine()
        with engine.connect() as conn:
            if player_ids_param:
                # Specific player IDs requested
                try:
                    pids = [int(x.strip()) for x in player_ids_param.split(",") if x.strip()]
                except ValueError:
                    return jsonify(error="invalid_param", message="player_ids must be comma-separated integers"), 400

                from services.face_generator import generate_face, load_face_config
                face_config = load_face_config(conn)
                faces = {}
                for pid in pids:
                    faces[str(pid)] = generate_face(pid, face_config)
                return jsonify({"faces": faces}), 200

            # Otherwise query by org/level
            stmt = _build_ratings_base_stmt(
                level_filter=level,
                org_abbrev=org_abbrev,
            )
            rows = conn.execute(stmt).all()
            face_data = _generate_faces_for_rows(conn, rows)

    except SQLAlchemyError:
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503

    return jsonify({"faces": face_data}), 200


# -------------------------------------------------------------------
# Obligations: single org, all orgs, and history
# -------------------------------------------------------------------
@rosters_bp.get("/orgs/<string:org_abbrev>/obligations")
def get_org_obligations(org_abbrev: str):
    """
    Return all financial obligations for an organization in a given league year.

    Query params:
      - league_year (required, int): the league year (e.g., 2027)
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

    def _num(val):
        return float(val) if val is not None else 0.0

    # Salary obligations
    for row in salary_rows:
        m = row._mapping
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

        obligations.append(
            {
                "type": "salary",
                "category": category,
                "league_year": league_year,
                "year_index": m["year_index"],
                "player": {"id": m["player_id"]},
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

    # Bonus / buyout obligations
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
                "player": {"id": m["player_id"]},
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
@rosters_bp.get("/obligations/")
def get_all_org_obligations():
    """
    Return financial obligations for ALL organizations in a given league year.

    Query params:
      - league_year (required, int): the league year (e.g., 2027)
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

    def _num(val):
        return float(val) if val is not None else 0.0

    by_org = {}

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

    # Salary obligations
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
            "player": {"id": m["player_id"]},
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

    # Bonus / buyout obligations
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
            "player": {"id": m["player_id"]},
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

    # Salary obligations across all years
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
            "player": {"id": m["player_id"]},
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

        lifetime_totals["overall"] += base_amount
        if category == "buyout":
            lifetime_totals["buyout"] += base_amount
        elif category == "active_salary":
            lifetime_totals["active_salary"] += base_amount
        elif category == "inactive_salary":
            lifetime_totals["inactive_salary"] += base_amount

    # Bonus / buyout obligations across all years
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
            "player": {"id": m["player_id"]},
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


# -------------------------------------------------------------------
# Financial summaries (ledger-based)
# -------------------------------------------------------------------
def get_org_financial_summary(org_abbrev: str, league_year: int):
    """
    Summarize an organization's finances for a given league_year.

    - starting_balance: net balance from all prior league years
    - season_revenue: sum of all positive ledger entries in this league_year
    - season_expenses: sum of absolute values of all negative ledger entries in this league_year
    - year_start_events: media/bonus/buyout (non-week entries in this year)
    - weeks: per-week salary/performance/other + cumulative balance
    - interest_events: interest_income/interest_expense entries in this year
    - ending_balance: after this year's activity + interest
    """
    engine = get_engine()
    tables = _get_tables()
    orgs = tables["organizations"]
    league_years = tables["league_years"]
    game_weeks = tables["game_weeks"]
    ledger = tables["org_ledger_entries"]

    with engine.connect() as conn:
        # --- Resolve org ---
        org_row = conn.execute(
            select(orgs.c.id, orgs.c.org_abbrev)
            .where(orgs.c.org_abbrev == org_abbrev)
            .limit(1)
        ).first()
        if not org_row:
            raise ValueError(f"Organization '{org_abbrev}' not found")

        org_m = org_row._mapping
        org_id = org_m["id"]

        # --- Resolve league_year ---
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

        # --- Starting balance: all prior years ---
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

        # --- Year-level entries (no game_week_id) for this league_year ---
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

        # Break out categories
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

        # Season revenue/expenses (include year-level + weekly + interest)
        season_revenue = 0.0
        season_expenses = 0.0

        for v in year_level_totals.values():
            if v > 0:
                season_revenue += v
            elif v < 0:
                season_expenses += -v

        balance_after_year_start = float(starting_balance) + year_start_net

        # --- Weekly entries grouped by week_index + entry_type ---
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

        week_type_totals = {}
        for row in weekly_rows:
            m = row._mapping
            week = m["week_index"]
            etype = m["entry_type"]
            total = float(m["total"])
            week_type_totals.setdefault(week, {})[etype] = total

            # contribute to season revenue/expenses
            if total > 0:
                season_revenue += total
            elif total < 0:
                season_expenses += -total

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
                    "salary_out": -salary_total,  # present as positive outflow
                    "performance_in": performance_total,
                    "other_in": other_in,
                    "other_out": other_out,
                    "net": week_net,
                    "cumulative_balance": cumulative,
                    "by_type": by_type,
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
        "season_revenue": season_revenue,
        "season_expenses": season_expenses,
        "year_start_events": year_start_events,
        "weeks": weeks_summary,
        "interest_events": interest_events,
        "ending_balance_before_interest": ending_balance_before_interest,
        "ending_balance": ending_balance,
    }


def get_league_financial_summary(league_year: int):
    """
    League-wide financial summary for a given league_year.

    Returns:
      {
        "league_year": 2026,
        "league_totals": {
          "season_revenue": ...,
          "season_expenses": ...
        },
        "orgs": {
          "NYY": { ...per-org financial summary... },
          "LAD": { ... },
          ...
        }
      }
    """
    engine = get_engine()
    tables = _get_tables()
    orgs = tables["organizations"]
    league_years = tables["league_years"]

    with engine.connect() as conn:
        ly_row = conn.execute(
            select(league_years.c.id, league_years.c.league_year)
            .where(league_years.c.league_year == league_year)
            .limit(1)
        ).first()

        if not ly_row:
            raise ValueError(f"league_year {league_year} not found in league_years")

        org_rows = conn.execute(
            select(orgs.c.org_abbrev, orgs.c.id).order_by(orgs.c.org_abbrev)
        ).all()

    org_summaries = {}
    league_totals = {
        "season_revenue": 0.0,
        "season_expenses": 0.0,
    }

    for row in org_rows:
        m = row._mapping
        org_abbrev = m["org_abbrev"]
        summary = get_org_financial_summary(org_abbrev, league_year)
        org_summaries[org_abbrev] = summary

        league_totals["season_revenue"] += float(summary.get("season_revenue", 0.0))
        league_totals["season_expenses"] += float(summary.get("season_expenses", 0.0))

    return {
        "league_year": league_year,
        "league_totals": league_totals,
        "orgs": org_summaries,
    }

@rosters_bp.get("/orgs/<string:org_abbrev>/financial_summary")
def get_org_financial_summary_endpoint(org_abbrev):
    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    try:
        summary = get_org_financial_summary(org_abbrev, league_year)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    except SQLAlchemyError as e:
        current_app.logger.exception("get_org_financial_summary: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(summary), 200


@rosters_bp.get("/financial_summary")
@rosters_bp.get("/financial_summary/")
def get_league_financial_summary_endpoint():
    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    try:
        summary = get_league_financial_summary(league_year)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    except SQLAlchemyError as e:
        current_app.logger.exception("get_league_financial_summary: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(summary), 200

@rosters_bp.get("/orgs/<string:org_abbrev>/ledger")
def get_org_ledger(org_abbrev: str):
    """
    Inspect raw ledger entries for an org in a given league_year.

    Query params:
      - league_year (required, int)
      - entry_type (optional, string) to filter (e.g. 'salary', 'media', 'performance', etc.)
    """
    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    entry_type = request.args.get("entry_type")

    engine = get_engine()
    tables = _get_tables()
    orgs = tables["organizations"]
    league_years = tables["league_years"]
    game_weeks = tables["game_weeks"]
    ledger = tables["org_ledger_entries"]

    try:
        with engine.connect() as conn:
            # org lookup
            org_row = conn.execute(
                select(orgs.c.id, orgs.c.org_abbrev)
                .where(orgs.c.org_abbrev == org_abbrev)
                .limit(1)
            ).first()
            if not org_row:
                return jsonify(
                    error="org_not_found",
                    message=f"Organization '{org_abbrev}' not found"
                ), 404

            org_m = org_row._mapping
            org_id = org_m["id"]

            # league_year lookup
            ly_row = conn.execute(
                select(league_years.c.id, league_years.c.league_year)
                .where(league_years.c.league_year == league_year)
                .limit(1)
            ).first()
            if not ly_row:
                return jsonify(
                    error="league_year_not_found",
                    message=f"league_year {league_year} not found in league_years"
                ), 404

            league_year_id = ly_row._mapping["id"]

            conditions = [
                ledger.c.org_id == org_id,
                ledger.c.league_year_id == league_year_id,
            ]
            if entry_type:
                conditions.append(ledger.c.entry_type == entry_type)

            stmt = (
                select(
                    ledger,
                    game_weeks.c.week_index,
                )
                .select_from(
                    ledger.outerjoin(game_weeks, ledger.c.game_week_id == game_weeks.c.id)
                )
                .where(and_(*conditions))
                .order_by(game_weeks.c.week_index.asc(), ledger.c.id)
            )

            rows = conn.execute(stmt).all()

            entries = []
            for row in rows:
                m = row._mapping
                # row includes all ledger columns + week_index
                entry = {k: v for k, v in m.items()}
                entries.append(entry)

    except SQLAlchemyError as e:
        current_app.logger.exception("get_org_ledger: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(
        {
            "org": {
                "id": org_id,
                "abbrev": org_abbrev,
            },
            "league_year": league_year,
            "count": len(entries),
            "entries": entries,
        }
    ), 200

@rosters_bp.get("/orgs/<string:org_abbrev>/weekly_record")
def get_org_weekly_record(org_abbrev: str):
    """
    Weekly performance summary for an org in a given league_year.

    Uses team_weekly_record + game_weeks.

    Query params:
      - league_year (required, int)

    Response:
      {
        "org": {...},
        "league_year": 2026,
        "weeks": [
          {"week_index": 1, "wins": 3, "losses": 1},
          ...
        ],
        "totals": {"wins": 85, "losses": 77}
      }
    """
    league_year = request.args.get("league_year", type=int)
    if not league_year:
        return jsonify(
            error="missing_param",
            message="league_year query param is required, e.g. ?league_year=2026"
        ), 400

    engine = get_engine()
    tables = _get_tables()
    orgs = tables["organizations"]
    league_years = tables["league_years"]
    game_weeks = tables["game_weeks"]
    team_weekly = tables["team_weekly_record"]

    try:
        with engine.connect() as conn:
            # org lookup
            org_row = conn.execute(
                select(orgs.c.id, orgs.c.org_abbrev)
                .where(orgs.c.org_abbrev == org_abbrev)
                .limit(1)
            ).first()
            if not org_row:
                return jsonify(
                    error="org_not_found",
                    message=f"Organization '{org_abbrev}' not found"
                ), 404

            org_m = org_row._mapping
            org_id = org_m["id"]

            # league_year lookup
            ly_row = conn.execute(
                select(league_years.c.id, league_years.c.league_year)
                .where(league_years.c.league_year == league_year)
                .limit(1)
            ).first()
            if not ly_row:
                return jsonify(
                    error="league_year_not_found",
                    message=f"league_year {league_year} not found in league_years"
                ), 404

            league_year_id = ly_row._mapping["id"]

            stmt = (
                select(
                    team_weekly.c.wins,
                    team_weekly.c.losses,
                    game_weeks.c.week_index,
                )
                .select_from(
                    team_weekly.join(
                        game_weeks,
                        team_weekly.c.game_week_id == game_weeks.c.id,
                    )
                )
                .where(
                    and_(
                        team_weekly.c.org_id == org_id,
                        team_weekly.c.league_year_id == league_year_id,
                    )
                )
                .order_by(game_weeks.c.week_index)
            )

            rows = conn.execute(stmt).all()

            weeks = []
            total_wins = 0
            total_losses = 0

            for row in rows:
                m = row._mapping
                w = int(m["wins"])
                l = int(m["losses"])
                weeks.append(
                    {
                        "week_index": m["week_index"],
                        "wins": w,
                        "losses": l,
                    }
                )
                total_wins += w
                total_losses += l

    except SQLAlchemyError as e:
        current_app.logger.exception("get_org_weekly_record: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(
        {
            "org": {
                "id": org_id,
                "abbrev": org_abbrev,
            },
            "league_year": league_year,
            "weeks": weeks,
            "totals": {
                "wins": total_wins,
                "losses": total_losses,
            },
        }
    ), 200

@rosters_bp.get("/league_state")
def get_league_state():
    """
    Return the current league_state row, plus resolved league_year and week_index.

    Assumes a single row in league_state.
    """
    engine = get_engine()
    tables = _get_tables()
    league_state = tables["league_state"]
    league_years = tables["league_years"]
    game_weeks = tables["game_weeks"]

    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(
                    league_state.c.id,
                    league_state.c.current_league_year_id,
                    league_state.c.current_game_week_id,
                    league_state.c.books_last_run_at,
                    league_state.c.games_last_run_at,
                ).limit(1)
            ).first()

            if not row:
                # Table exists but no state row yet
                return jsonify(
                    {
                        "state": None,
                        "message": "league_state table is empty; initialize it via admin tools.",
                    }
                ), 200

            m = row._mapping

            current_league_year = None
            current_week_index = None

            if m["current_league_year_id"] is not None:
                ly_row = conn.execute(
                    select(league_years.c.league_year)
                    .where(league_years.c.id == m["current_league_year_id"])
                    .limit(1)
                ).first()
                if ly_row:
                    current_league_year = ly_row._mapping["league_year"]

            if m["current_game_week_id"] is not None:
                gw_row = conn.execute(
                    select(game_weeks.c.week_index)
                    .where(game_weeks.c.id == m["current_game_week_id"])
                    .limit(1)
                ).first()
                if gw_row:
                    current_week_index = gw_row._mapping["week_index"]

            def _to_str_or_none(val):
                if val is None:
                    return None
                # Safely stringify timestamps or other types
                return getattr(val, "isoformat", lambda: str(val))()

            payload = {
                "id": m["id"],
                "current_league_year_id": m["current_league_year_id"],
                "current_game_week_id": m["current_game_week_id"],
                "current_league_year": current_league_year,
                "current_week_index": current_week_index,
                "books_last_run_at": _to_str_or_none(m["books_last_run_at"]),
                "games_last_run_at": _to_str_or_none(m["games_last_run_at"]),
            }

    except SQLAlchemyError as e:
        current_app.logger.exception("get_league_state: db error")
        return jsonify(error="database_error", message=str(e)), 500

    return jsonify(payload), 200
