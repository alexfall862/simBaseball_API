# services/lineups.py

from typing import Dict, Any, List, Tuple

from sqlalchemy import MetaData, Table, select, and_, or_
from db import get_engine


_metadata = None
_lineup_tables = None


def _get_lineup_tables():
    """
    Reflect and cache lineup-related tables:
      - team_position_plan
      - team_lineup_roles
      - player_position_usage_week (not used yet, but reserved)
    """
    global _metadata, _lineup_tables
    if _lineup_tables is not None:
        return _lineup_tables

    engine = get_engine()
    md = MetaData()

    team_position_plan = Table("team_position_plan", md, autoload_with=engine)
    team_lineup_roles = Table("team_lineup_roles", md, autoload_with=engine)
    player_position_usage_week = Table("player_position_usage_week", md, autoload_with=engine)

    _metadata = md
    _lineup_tables = {
        "tpp": team_position_plan,
        "tlr": team_lineup_roles,
        "ppuw": player_position_usage_week,
    }
    return _lineup_tables


# -------------------------------------------------------------------
# Scoring helpers
# -------------------------------------------------------------------

def _compute_offense_score(p: Dict[str, Any]) -> float:
    """
    Crude offensive score for lineup ordering.
    """
    comps = [
        p.get("contact_base"),
        p.get("power_base"),
        p.get("eye_base"),
        p.get("discipline_base"),
    ]
    vals = []
    for v in comps:
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            continue
    return sum(vals) if vals else 0.0


def _safe_float(p: Dict[str, Any], key: str) -> float:
    try:
        v = p.get(key)
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _get_rating(p: Dict[str, Any], key: str) -> float:
    """
    Safe helper to read a positional rating from the player dict.
    Missing / non-numeric values are treated as 0.
    """
    return _safe_float(p, key)


# Map your internal position codes to their rating keys
_POS_RATING_KEY = {
    "c": "c_rating",
    "fb": "fb_rating",
    "sb": "sb_rating",
    "tb": "tb_rating",
    "ss": "ss_rating",
    "lf": "lf_rating",
    "cf": "cf_rating",
    "rf": "rf_rating",
    "dh": "dh_rating",
}

# Priority order for assigning field positions
_POSITION_PRIORITY_ORDER = ["c", "ss", "cf", "tb", "sb", "lf", "rf", "fb"]

_USAGE_THRESHOLDS = {
    "only_fully_rested": 95,
    "normal": 70,
    "play_tired": 40,
    "desperation": 0,
}


def _get_usage_threshold(usage_pref: str) -> int:
    return _USAGE_THRESHOLDS.get(usage_pref or "normal", 70)


def _is_player_available_for_lineup(p: Dict[str, Any]) -> bool:
    """
    Determine if a player is available to start this game based on
    stamina and usage_preference.

    usage_preference semantics:

      - 'only_fully_rested': require stamina >= 95
      - 'normal':            require stamina >= 70
      - 'play_tired':        require stamina >= 40
      - 'desperation':       no stamina requirement (0+)
    """
    stamina = p.get("stamina")
    try:
        stamina_val = int(stamina)
    except (TypeError, ValueError):
        stamina_val = 0

    usage_pref = (p.get("usage_preference") or "normal").lower()
    threshold = _get_usage_threshold(usage_pref)

    if usage_pref == "desperation":
        return True

    return stamina_val >= threshold


# -------------------------------------------------------------------
# team_position_plan loading (with vs_hand support)
# -------------------------------------------------------------------

def _load_team_position_plan_for_pos(
    conn,
    team_id: int,
    position_code: str,
    vs_hand: str | None,
) -> List[Dict[str, Any]]:
    """
    Load team_position_plan rows for a given team and position.

    If vs_hand is 'L' or 'R', we prefer rows that match that hand or 'both'.
    If vs_hand is None, we load all rows for this position.

    NOTE: It's safe if you haven't populated vs_hand-specific rows yet;
    the function will just treat everything as generic.
    """
    tables = _get_lineup_tables()
    tpp = tables["tpp"]

    conditions = [tpp.c.team_id == team_id, tpp.c.position_code == position_code]

    if vs_hand in ("L", "R"):
        conditions.append(or_(tpp.c.vs_hand == vs_hand, tpp.c.vs_hand == "both"))

    stmt = (
        select(
            tpp.c.player_id,
            tpp.c.target_weight,
            tpp.c.priority,
            tpp.c.locked,
        )
        .where(and_(*conditions))
        .order_by(tpp.c.priority.asc(), tpp.c.id.asc())
    )

    rows = conn.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def _load_all_position_plans_for_team(
    conn,
    team_id: int,
    vs_hand: str | None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Bulk-load ALL position plans for a team at once.

    Returns:
        {position_code: [list of plan rows], ...}

    This replaces 8 individual queries with a single query.
    """
    tables = _get_lineup_tables()
    tpp = tables["tpp"]

    conditions = [tpp.c.team_id == team_id]

    if vs_hand in ("L", "R"):
        conditions.append(or_(tpp.c.vs_hand == vs_hand, tpp.c.vs_hand == "both"))

    stmt = (
        select(
            tpp.c.position_code,
            tpp.c.player_id,
            tpp.c.target_weight,
            tpp.c.priority,
            tpp.c.locked,
            tpp.c.lineup_role,
            tpp.c.min_order,
            tpp.c.max_order,
        )
        .where(and_(*conditions))
        .order_by(tpp.c.position_code.asc(), tpp.c.priority.asc(), tpp.c.id.asc())
    )

    rows = conn.execute(stmt).mappings().all()

    # Group by position_code
    plans_by_position: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        pos = row["position_code"]
        plan_row = {
            "player_id": row["player_id"],
            "target_weight": row["target_weight"],
            "priority": row["priority"],
            "locked": row["locked"],
            "lineup_role": row.get("lineup_role", "balanced"),
            "min_order": row.get("min_order"),
            "max_order": row.get("max_order"),
        }
        if pos not in plans_by_position:
            plans_by_position[pos] = []
        plans_by_position[pos].append(plan_row)

    return plans_by_position


# -------------------------------------------------------------------
# team_lineup_roles loading
# -------------------------------------------------------------------

def _load_team_lineup_roles(conn, team_id: int) -> Dict[int, Dict[str, Any]]:
    """
    Load team_lineup_roles rows for a team.

    Returns a mapping:
      {slot: row_dict, ...}
    """
    tables = _get_lineup_tables()
    tlr = tables["tlr"]

    stmt = (
        select(
            tlr.c.slot,
            tlr.c.role,
            tlr.c.locked_player_id,
            tlr.c.min_order,
            tlr.c.max_order,
        )
        .where(tlr.c.team_id == team_id)
        .order_by(tlr.c.slot.asc())
    )

    roles_by_slot: Dict[int, Dict[str, Any]] = {}
    for row in conn.execute(stmt).mappings():
        slot = int(row["slot"])
        roles_by_slot[slot] = dict(row)
    return roles_by_slot

def _load_weekly_usage_for_pos(
    conn,
    league_year_id: int,
    season_week: int,
    team_id: int,
    position_code: str,
    vs_hand: str | None,
) -> Tuple[Dict[int, int], int]:
    """
    Load player_position_usage_week for this (league_year, week, team, pos, vs_hand).

    Returns:
      (usage_map, total_starts)
        usage_map: {player_id: starts_this_week, ...}
        total_starts: sum of starts_this_week across all players for this pos/split
    """
    tables = _get_lineup_tables()
    ppuw = tables["ppuw"]

    conditions = [
        ppuw.c.league_year_id == league_year_id,
        ppuw.c.season_week == season_week,
        ppuw.c.team_id == team_id,
        ppuw.c.position_code == position_code,
    ]
    if vs_hand in ("L", "R"):
        conditions.append(ppuw.c.vs_hand == vs_hand)

    stmt = select(ppuw.c.player_id, ppuw.c.starts_this_week).where(and_(*conditions))

    usage_map: Dict[int, int] = {}
    total = 0
    for row in conn.execute(stmt):
        pid = int(row.player_id)
        starts = int(row.starts_this_week or 0)
        usage_map[pid] = starts
        total += starts

    return usage_map, total


def _load_all_weekly_usage_for_team(
    conn,
    league_year_id: int,
    season_week: int,
    team_id: int,
    vs_hand: str | None,
) -> Dict[str, Tuple[Dict[int, int], int]]:
    """
    Bulk-load ALL weekly usage data for a team at once.

    Returns:
        {position_code: (usage_map, total_starts), ...}

    This replaces 8 individual queries with a single query.
    """
    tables = _get_lineup_tables()
    ppuw = tables["ppuw"]

    conditions = [
        ppuw.c.league_year_id == league_year_id,
        ppuw.c.season_week == season_week,
        ppuw.c.team_id == team_id,
    ]
    if vs_hand in ("L", "R"):
        conditions.append(ppuw.c.vs_hand == vs_hand)

    stmt = select(
        ppuw.c.position_code,
        ppuw.c.player_id,
        ppuw.c.starts_this_week
    ).where(and_(*conditions))

    rows = conn.execute(stmt).all()

    # Group by position_code
    usage_by_position: Dict[str, Dict[int, int]] = {}
    totals_by_position: Dict[str, int] = {}

    for row in rows:
        pos = row.position_code
        pid = int(row.player_id)
        starts = int(row.starts_this_week or 0)

        if pos not in usage_by_position:
            usage_by_position[pos] = {}
            totals_by_position[pos] = 0

        usage_by_position[pos][pid] = starts
        totals_by_position[pos] += starts

    # Convert to expected return format
    result: Dict[str, Tuple[Dict[int, int], int]] = {}
    for pos in usage_by_position:
        result[pos] = (usage_by_position[pos], totals_by_position[pos])

    return result


def _score_player_for_role(p: Dict[str, Any], role: str) -> float:
    """
    Score a hitter for a given role.

    Uses existing base metrics, but is robust to missing columns by
    falling back to overall offense.
    """
    role = (role or "balanced").lower()

    off = _compute_offense_score(p)
    contact = _safe_float(p, "contact_base")
    power = _safe_float(p, "power_base")
    eye = _safe_float(p, "eye_base")
    disc = _safe_float(p, "discipline_base")

    # Try a few likely speed keys; fall back to 0 if none exist
    speed = 0.0
    for key in ("speed_base", "spd_base", "run_base"):
        v = _safe_float(p, key)
        if v > 0:
            speed = v
            break

    if role in ("table_setter", "on_base"):
        # Favor OBP-ish profile: eye/discipline/contact
        return eye * 0.5 + disc * 0.3 + contact * 0.2

    if role == "slugger":
        return power * 0.7 + off * 0.3

    if role == "speed":
        return speed * 0.7 + off * 0.3

    if role == "bottom":
        # We will invert this later; for now just return offense
        return off

    # 'balanced' and unknown roles
    return off


def _build_batting_order(
    conn,
    team_id: int,
    players_by_id: Dict[int, Dict[str, Any]],
    starter_id: int,
    defense: Dict[str, Any],
    use_dh: bool,
    plans_by_position: Dict[str, List[Dict[str, Any]]] | None = None,
) -> List[int]:
    """
    Build batting order from starting players.

    Uses defense-assignment lineup prefs (lineup_role, min_order, max_order)
    when available. Falls back to team_lineup_roles, then to offense sorting.
    """
    # Determine starting hitters
    starting_ids: List[int] = []

    if use_dh:
        dh_id = defense.get("dh")
        if dh_id is not None:
            starting_ids.append(dh_id)
    else:
        # Pitcher hits
        if starter_id in players_by_id:
            starting_ids.append(starter_id)

    for pos in _POSITION_PRIORITY_ORDER:
        pid = defense.get(pos)
        if pid is not None and pid not in starting_ids:
            starting_ids.append(pid)

    # Deduplicate
    unique_start_ids: List[int] = []
    seen = set()
    for pid in starting_ids:
        if pid not in seen:
            seen.add(pid)
            unique_start_ids.append(pid)

    if not unique_start_ids:
        return []

    # Build player→lineup prefs from defense assignments
    player_lineup_prefs: Dict[int, Dict[str, Any]] = {}
    has_defense_lineup_data = False

    if plans_by_position:
        # Map each starter back to the assignment that placed them
        for pos, plans in plans_by_position.items():
            chosen_pid = defense.get(pos)
            if chosen_pid is None or chosen_pid not in unique_start_ids:
                continue
            # Use the first matching plan entry for this player at this position
            for plan in plans:
                if plan["player_id"] == chosen_pid:
                    role = plan.get("lineup_role", "balanced")
                    mn = plan.get("min_order")
                    mx = plan.get("max_order")
                    # Only overwrite if we haven't already set prefs for this player,
                    # or this entry has more specific data
                    if chosen_pid not in player_lineup_prefs:
                        player_lineup_prefs[chosen_pid] = {
                            "lineup_role": role,
                            "min_order": mn,
                            "max_order": mx,
                        }
                        if role != "balanced" or mn is not None or mx is not None:
                            has_defense_lineup_data = True
                    break

    # If defense assignments carry lineup data, use the new algorithm
    if has_defense_lineup_data:
        return _build_order_from_defense_prefs(
            unique_start_ids, players_by_id, player_lineup_prefs
        )

    # Otherwise fall back to team_lineup_roles (legacy)
    roles_by_slot = _load_team_lineup_roles(conn, team_id)

    if not roles_by_slot:
        return sorted(
            unique_start_ids,
            key=lambda pid: _compute_offense_score(players_by_id[pid]),
            reverse=True,
        )

    # Legacy team_lineup_roles algorithm
    lineup: List[int | None] = [None] * min(9, len(unique_start_ids))
    assigned_players: set[int] = set()

    # 1) Pre-assign locked players to their slots
    for slot_idx in range(len(lineup)):
        slot_num = slot_idx + 1
        role_row = roles_by_slot.get(slot_num)
        if not role_row:
            continue
        locked_pid = role_row.get("locked_player_id")
        if locked_pid is None:
            continue
        locked_pid = int(locked_pid)
        if locked_pid in unique_start_ids and locked_pid not in assigned_players:
            lineup[slot_idx] = locked_pid
            assigned_players.add(locked_pid)

    # 2) Fill remaining slots by role match
    for slot_idx in range(len(lineup)):
        if lineup[slot_idx] is not None:
            continue
        slot_num = slot_idx + 1
        role_row = roles_by_slot.get(slot_num)
        role_name = role_row["role"] if role_row else "balanced"

        best_pid = None
        best_score = None
        for pid in unique_start_ids:
            if pid in assigned_players:
                continue
            p = players_by_id[pid]
            score = _score_player_for_role(p, role_name)
            if role_name == "bottom":
                score = -score
            if best_pid is None or score > best_score:
                best_pid = pid
                best_score = score
        if best_pid is not None:
            lineup[slot_idx] = best_pid
            assigned_players.add(best_pid)

    # 3) Append remaining starters by offense
    remaining_ids = [pid for pid in unique_start_ids if pid not in assigned_players]
    remaining_sorted = sorted(
        remaining_ids,
        key=lambda pid: _compute_offense_score(players_by_id[pid]),
        reverse=True,
    )
    final_lineup: List[int] = [pid for pid in lineup if pid is not None]
    for pid in remaining_sorted:
        if pid not in final_lineup:
            final_lineup.append(pid)
    return final_lineup


def _build_order_from_defense_prefs(
    starter_ids: List[int],
    players_by_id: Dict[int, Dict[str, Any]],
    prefs: Dict[int, Dict[str, Any]],
) -> List[int]:
    """
    Build batting order using lineup prefs from defense assignments.

    Algorithm:
      1. Place constrained players (min/max_order) first, tightest range first
      2. Fill remaining slots by role score
      3. Append leftovers by offense
    """
    num_slots = min(9, len(starter_ids))
    lineup: List[int | None] = [None] * num_slots
    assigned: set[int] = set()

    # Step 1: Place constrained players (those with min/max_order)
    constrained = []
    for pid in starter_ids:
        p = prefs.get(pid, {})
        mn = p.get("min_order")
        mx = p.get("max_order")
        if mn is not None or mx is not None:
            lo = mn if mn is not None else 1
            hi = mx if mx is not None else 9
            # Clamp to actual lineup size
            lo = max(1, min(lo, num_slots))
            hi = max(1, min(hi, num_slots))
            constrained.append((pid, lo, hi, hi - lo))

    # Sort by range tightness (smallest range first)
    constrained.sort(key=lambda x: x[3])

    for pid, lo, hi, _ in constrained:
        # Find best available slot within range
        role = prefs.get(pid, {}).get("lineup_role", "balanced")
        p = players_by_id[pid]
        score = _score_player_for_role(p, role)

        best_slot = None
        for slot_idx in range(lo - 1, hi):  # convert to 0-based
            if slot_idx < num_slots and lineup[slot_idx] is None:
                best_slot = slot_idx
                break

        if best_slot is not None:
            lineup[best_slot] = pid
            assigned.add(pid)

    # Step 2: Fill remaining slots by role score
    unconstrained = [pid for pid in starter_ids if pid not in assigned]

    for slot_idx in range(num_slots):
        if lineup[slot_idx] is not None:
            continue

        best_pid = None
        best_score = None

        for pid in unconstrained:
            if pid in assigned:
                continue
            p = players_by_id[pid]
            role = prefs.get(pid, {}).get("lineup_role", "balanced")
            score = _score_player_for_role(p, role)

            # Bias by slot position: table_setter/on_base/speed prefer early slots,
            # slugger prefers middle, bottom prefers late
            slot_num = slot_idx + 1
            if role in ("table_setter", "on_base", "speed") and slot_num <= 3:
                score *= 1.2
            elif role == "slugger" and 3 <= slot_num <= 5:
                score *= 1.2
            elif role == "bottom" and slot_num >= 7:
                score *= 1.2

            if best_pid is None or score > best_score:
                best_pid = pid
                best_score = score

        if best_pid is not None:
            lineup[slot_idx] = best_pid
            assigned.add(best_pid)

    # Step 3: Append any remaining starters by offense
    remaining = [pid for pid in starter_ids if pid not in assigned]
    remaining.sort(
        key=lambda pid: _compute_offense_score(players_by_id[pid]),
        reverse=True,
    )

    final = [pid for pid in lineup if pid is not None]
    for pid in remaining:
        if pid not in final:
            final.append(pid)

    return final


# -------------------------------------------------------------------
# Position selection
# -------------------------------------------------------------------

def _choose_player_for_position(
    conn,
    team_id: int,
    league_year_id: int,
    season_week: int,
    position_code: str,
    vs_hand: str | None,
    players_by_id: Dict[int, Dict[str, Any]],
    remaining_ids: List[int],
    plans_by_position: Dict[str, List[Dict[str, Any]]],
    usage_by_position: Dict[str, Tuple[Dict[int, int], int]],
) -> int | None:
    """
    Choose a player for a single defensive position.

    Preference order:
      - Use team_position_plan if present:
          * filter by availability (stamina + usage_preference)
          * filter to remaining_ids (not already assigned)
          * combine:
              normalized target_weight
              positional rating * XP modifier
              offensive score
              locked flag
      - If no suitable candidate, fall back to best remaining player by
        positional rating + XP + offense.

    Parameters:
      plans_by_position: Pre-loaded position plans from _load_all_position_plans_for_team
      usage_by_position: Pre-loaded weekly usage from _load_all_weekly_usage_for_team
    """
    # We never put pitchers in *field* positions here (only SP at 'p')
    remaining_field_ids = [
        pid for pid in remaining_ids
        if (players_by_id[pid].get("ptype") or "").lower() != "pitcher"
    ]
    if not remaining_field_ids:
        return None

    rating_key = _POS_RATING_KEY.get(position_code)

    # Get pre-loaded depth chart for this position (if any)
    plan_rows = plans_by_position.get(position_code, [])

    # First pass: using team_position_plan
    if plan_rows:
        filtered_plan = []
        total_weight = 0.0

        for row in plan_rows:
            pid = int(row["player_id"])
            if pid not in players_by_id or pid not in remaining_field_ids:
                continue

            p = players_by_id[pid]
            if not _is_player_available_for_lineup(p):
                continue

            w = float(row.get("target_weight") or 0.0)
            if w <= 0:
                continue

            filtered_plan.append(row)
            total_weight += w

        if filtered_plan and total_weight > 0:
            # Get pre-loaded weekly usage for this pos/split
            usage_map, total_starts = usage_by_position.get(position_code, ({}, 0))

            best_pid = None
            best_score = None

            for row in filtered_plan:
                pid = int(row["player_id"])
                p = players_by_id[pid]

                # Normalized target share for this slot
                weight = float(row["target_weight"]) / total_weight
                target_share = weight

                # Actual share so far this week for this pos/split
                starts_i = usage_map.get(pid, 0)
                if total_starts > 0:
                    actual_share = starts_i / float(total_starts)
                    gap = target_share - actual_share  # >0 = under target
                    target_bias = gap * 10.0
                else:
                    target_bias = 0.0

                # Positional rating + XP
                base_pos_rating = _get_rating(p, rating_key) if rating_key else 0.0
                xp_mod = 0.0
                xp_dict = p.get("defensive_xp_mod") or {}
                if isinstance(xp_dict, dict):
                    xp_mod = float(xp_dict.get(position_code, 0.0) or 0.0)

                pos_score = base_pos_rating * (1.0 + xp_mod)

                # Offensive contribution (smaller factor)
                off_score = _compute_offense_score(p)
                base_score = pos_score * 0.7 + off_score * 0.3

                # Weight by relative target and usage bias
                weighted_score = base_score * (0.5 + 0.5 * weight) + target_bias

                # Locked flag: large bump
                locked = bool(row.get("locked"))
                if locked:
                    weighted_score += 1000.0

                if best_pid is None or weighted_score > best_score:
                    best_pid = pid
                    best_score = weighted_score

            if best_pid is not None:
                return best_pid

    # Second pass: fallback to "best available" if no suitable plan candidate
    best_pid = None
    best_score = None

    for pid in remaining_field_ids:
        p = players_by_id[pid]
        if not _is_player_available_for_lineup(p):
            continue

        base_pos_rating = _get_rating(p, rating_key) if rating_key else 0.0
        xp_mod = 0.0
        xp_dict = p.get("defensive_xp_mod") or {}
        if isinstance(xp_dict, dict):
            xp_mod = float(xp_dict.get(position_code, 0.0) or 0.0)

        pos_score = base_pos_rating * (1.0 + xp_mod)
        off_score = _compute_offense_score(p)
        base_score = pos_score * 0.7 + off_score * 0.3

        if best_pid is None or base_score > best_score:
            best_pid = pid
            best_score = base_score

    return best_pid


# -------------------------------------------------------------------
# Public entrypoint: defense + lineup + bench
# -------------------------------------------------------------------

def build_defense_and_lineup(
    conn,
    team_id: int,
    league_level_id: int,  # reserved if you ever want level-specific tuning
    league_year_id: int,
    season_week: int,
    vs_hand: str | None,
    players_by_id: Dict[int, Dict[str, Any]],
    starter_id: int,
    use_dh: bool = False,
) -> Tuple[Dict[str, Any], List[int], List[int]]:
    """
    Build:

      - defensive alignment (including starting pitcher)
      - batting order lineup (list of player_ids)
      - bench (all other player_ids)

    This is depth-chart aware via team_position_plan (with vs_hand support),
    but will fall back to a pure rating-based auto assignment when:
      - no plan is present, or
      - plan is incomplete, or
      - no plan candidates are available.

    It respects:
      - usage_preference + stamina for availability
      - defensive ratings
      - defensive XP modifiers
      - offensive ability
      - team_lineup_roles for batting order (if present)

    It uses:
      - player_position_usage_week (weekly starts, written post-game)
    """
    # Bulk-load position plans and weekly usage for all positions at once
    # This replaces 8-16 individual queries with just 2 queries
    plans_by_position = _load_all_position_plans_for_team(conn, team_id, vs_hand)
    usage_by_position = _load_all_weekly_usage_for_team(
        conn, league_year_id, season_week, team_id, vs_hand
    )

    # Initialize defense with SP fixed
    defense: Dict[str, Any] = {
        "startingpitcher": starter_id,
        "c": None,
        "fb": None,
        "sb": None,
        "tb": None,
        "ss": None,
        "lf": None,
        "cf": None,
        "rf": None,
        "dh": None,
    }

    remaining_ids = [pid for pid in players_by_id.keys() if pid != starter_id]

    # Assign field positions in priority order
    for pos in _POSITION_PRIORITY_ORDER:
        chosen = _choose_player_for_position(
            conn=conn,
            team_id=team_id,
            league_year_id=league_year_id,
            season_week=season_week,
            position_code=pos,
            vs_hand=vs_hand,
            players_by_id=players_by_id,
            remaining_ids=remaining_ids,
            plans_by_position=plans_by_position,
            usage_by_position=usage_by_position,
        )
        if chosen is not None:
            defense[pos] = chosen
            if chosen in remaining_ids:
                remaining_ids.remove(chosen)

    # DH assignment (optional; for now we run use_dh=False in callers)
    if use_dh:
        best_pid = None
        best_score = None
        for pid in remaining_ids:
            p = players_by_id[pid]
            if not _is_player_available_for_lineup(p):
                continue

            base_pos_rating = _get_rating(p, "dh_rating")
            off_score = _compute_offense_score(p)
            score = base_pos_rating * 0.7 + off_score * 0.3

            if best_pid is None or score > best_score:
                best_pid = pid
                best_score = score

        if best_pid is not None:
            defense["dh"] = best_pid
            if best_pid in remaining_ids:
                remaining_ids.remove(best_pid)

    # Build batting order using defense-based prefs (with safe fallback)
    lineup_ids = _build_batting_order(
        conn=conn,
        team_id=team_id,
        players_by_id=players_by_id,
        starter_id=starter_id,
        defense=defense,
        use_dh=use_dh,
        plans_by_position=plans_by_position,
    )

    # Bench = everyone not in lineup and not the SP
    all_ids = set(players_by_id.keys())
    bench_ids = sorted(all_ids - set(lineup_ids) - {starter_id})

    return defense, lineup_ids, bench_ids
