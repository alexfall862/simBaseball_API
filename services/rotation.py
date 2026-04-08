# services/rotation.py

import logging
from typing import Dict, Any, List

from sqlalchemy import MetaData, Table, select, and_
from db import get_engine
from rosters import _get_tables as _get_roster_tables
from services.stamina import get_effective_stamina, get_effective_stamina_bulk
from services.injuries import get_active_injury_malus_bulk

logger = logging.getLogger(__name__)

_metadata = None
_rotation_tables = None

_USAGE_THRESHOLDS = {
    "only_fully_rested": 95,
    "normal": 70,
    "play_tired": 40,
    "desperation": 0,
}

# Role priority for bullpen spot-starts (lower = preferred)
_SPOT_START_ROLE_PRIORITY = {
    "long": 0,
    "mop_up": 1,
    "middle": 2,
    "setup": 3,
    "closer": 4,
}

_SPOT_START_STAMINA_THRESHOLD = 70  # "normal" threshold for spot starters


def _apply_injury_stamina_pct(stamina_by_player: Dict[int, int], malus_by_player: Dict[int, Dict]) -> None:
    """
    Mutate stamina_by_player in-place: apply stamina_pct from injury malus.
    A pitcher with stamina_pct=0.0 injury has effective stamina forced to 0.
    """
    for pid, malus in malus_by_player.items():
        stam_pct = malus.get("stamina_pct")
        if stam_pct is not None and pid in stamina_by_player:
            stamina_by_player[pid] = int(max(0, stamina_by_player[pid] * float(stam_pct)))


def _safe_float(val) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _compute_pitcher_ability_score(p: Dict[str, Any]) -> float:
    """
    Compute overall ability score for a starting pitcher.

    Formula:
      - 30% pendurance_base (workload capacity)
      - 40% pgencontrol_base (general control)
      - 10% pickoff_base
      - 20% average of 5 pitches' quality (each pitch = avg of pacc, pbrk, pcntrl, pconsist)

    Returns:
        Float score (higher is better).
    """
    pendurance = _safe_float(p.get("pendurance_base"))
    pgencontrol = _safe_float(p.get("pgencontrol_base"))
    pickoff = _safe_float(p.get("pickoff_base"))

    # Calculate average quality across all 5 pitches
    pitch_qualities = []
    for n in range(1, 6):
        pacc = _safe_float(p.get(f"pitch{n}_pacc_base"))
        pbrk = _safe_float(p.get(f"pitch{n}_pbrk_base"))
        pcntrl = _safe_float(p.get(f"pitch{n}_pcntrl_base"))
        pconsist = _safe_float(p.get(f"pitch{n}_consist_base"))
        pitch_avg = (pacc + pbrk + pcntrl + pconsist) / 4.0
        pitch_qualities.append(pitch_avg)

    avg_pitch_quality = sum(pitch_qualities) / 5.0

    # Weighted combination
    score = (
        (pendurance * 0.30) +
        (pgencontrol * 0.40) +
        (pickoff * 0.10) +
        (avg_pitch_quality * 0.20)
    )

    return score


def _get_rotation_tables():
    global _metadata, _rotation_tables
    if _rotation_tables is not None:
        return _rotation_tables

    engine = get_engine()
    md = MetaData()

    rotation = Table("team_pitching_rotation", md, autoload_with=engine)
    slots = Table("team_pitching_rotation_slots", md, autoload_with=engine)
    state = Table("team_rotation_state", md, autoload_with=engine)
    strategies = Table("playerStrategies", md, autoload_with=engine)
    bullpen_order = Table("team_bullpen_order", md, autoload_with=engine)

    _rotation_tables = {
        "rotation": rotation,
        "slots": slots,
        "state": state,
        "strategies": strategies,
        "players": _get_roster_tables()["players"],
        "bullpen_order": bullpen_order,
    }
    _metadata = md
    return _rotation_tables


def _get_team_pitcher_ids(conn, team_id: int) -> List[int]:
    """
    Fallback helper: get all pitcher player_ids on a team based on active contracts.

    This mirrors the join we use elsewhere, but filters by ptype='Pitcher'.
    """
    r_tables = _get_roster_tables()
    contracts = r_tables["contracts"]
    details = r_tables["contract_details"]
    shares = r_tables["contract_team_share"]
    orgs = r_tables["organizations"]
    players = r_tables["players"]
    levels = r_tables["levels"]
    teams = r_tables["teams"]

    conditions = [
        contracts.c.isActive == 1,
        shares.c.isHolder == 1,
        teams.c.id == team_id,
    ]

    stmt = (
        select(players.c.id, players.c.ptype)
        .select_from(
            shares
            .join(details, shares.c.contractDetailsID == details.c.id)
            .join(contracts, details.c.contractID == contracts.c.id)
            .join(orgs, orgs.c.id == shares.c.orgID)
            .join(players, players.c.id == contracts.c.playerID)
            .join(levels, levels.c.id == contracts.c.current_level)
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

    pitcher_ids: List[int] = []
    for pid, ptype in conn.execute(stmt):
        if (ptype or "").lower() == "pitcher":
            pitcher_ids.append(int(pid))
    return pitcher_ids


def _load_pitcher_ratings_bulk(conn, pitcher_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Bulk-load pitcher rating attributes needed for ability score calculation.

    Returns:
        {player_id: {pendurance_base, pgencontrol_base, pickoff_base,
                     pitch1_pacc_base, pitch1_pbrk_base, ...}, ...}
    """
    if not pitcher_ids:
        return {}

    r_tables = _get_roster_tables()
    players = r_tables["players"]

    # Columns needed for ability score calculation
    columns = [
        players.c.id,
        players.c.pendurance_base,
        players.c.pgencontrol_base,
        players.c.pickoff_base,
    ]

    # Add all 5 pitch rating columns
    for n in range(1, 6):
        columns.extend([
            getattr(players.c, f"pitch{n}_pacc_base"),
            getattr(players.c, f"pitch{n}_pbrk_base"),
            getattr(players.c, f"pitch{n}_pcntrl_base"),
            getattr(players.c, f"pitch{n}_consist_base"),
        ])

    stmt = select(*columns).where(players.c.id.in_(pitcher_ids))

    result: Dict[int, Dict[str, Any]] = {}
    for row in conn.execute(stmt).mappings():
        pid = int(row["id"])
        result[pid] = dict(row)

    return result


def _get_usage_preference_for_player(conn, player_id: int) -> str:
    tables = _get_rotation_tables()
    strategies = tables["strategies"]

    stmt = select(strategies.c.usage_preference).where(
        strategies.c.playerID == player_id
    )
    val = conn.execute(stmt).scalar_one_or_none()
    if not val:
        return "normal"
    return val


def _get_usage_preferences_bulk(conn, player_ids: List[int]) -> Dict[int, str]:
    """
    Bulk-load usage preferences for multiple players at once.

    Returns:
        {player_id: usage_preference, ...}

    Players without an explicit strategy row default to 'normal'.
    """
    if not player_ids:
        return {}

    tables = _get_rotation_tables()
    strategies = tables["strategies"]

    stmt = select(
        strategies.c.playerID,
        strategies.c.usage_preference
    ).where(strategies.c.playerID.in_(player_ids))

    result = {pid: "normal" for pid in player_ids}

    for row in conn.execute(stmt):
        pid = int(row.playerID)
        pref = row.usage_preference
        if pref:
            result[pid] = pref

    return result


# -------------------------------------------------------------------
# Rotation roster helpers (for excluding rotation arms from bullpen)
# -------------------------------------------------------------------

def get_rotation_pitcher_ids(conn, team_id: int) -> set:
    """
    Return the set of player IDs assigned to rotation slots for a team.
    Returns an empty set if no rotation is configured.
    """
    tables = _get_rotation_tables()
    rotation = tables["rotation"]
    slots = tables["slots"]

    rot_row = conn.execute(
        select(rotation.c.id).where(rotation.c.team_id == team_id)
    ).first()
    if not rot_row:
        return set()

    slot_rows = conn.execute(
        select(slots.c.player_id).where(slots.c.rotation_id == rot_row[0])
    ).all()
    return {int(r[0]) for r in slot_rows}


def get_rotation_pitcher_ids_from_cache(cache, team_id: int) -> set:
    """
    Return the set of player IDs assigned to rotation slots for a team,
    reading from SubweekCache. Returns an empty set if no rotation is configured.
    """
    rot_row = cache.rotation_by_team.get(team_id)
    if not rot_row:
        return set()
    rotation_id = int(rot_row["id"])
    slot_rows = cache.rotation_slots_by_rotation.get(rotation_id, [])
    return {int(r["player_id"]) for r in slot_rows}


# -------------------------------------------------------------------
# Bullpen spot-starter selection
# -------------------------------------------------------------------

def _find_bullpen_spot_starter(
    conn,
    team_id: int,
    league_year_id: int,
    exclude_pids: set[int],
) -> Dict[str, Any] | None:
    """
    Find the best bullpen pitcher to make a spot start when the scheduled
    rotation starter is unavailable.

    Prefers mop_up / long relievers with high endurance. Returns a candidate
    dict compatible with the rotation candidates list, or None if no suitable
    reliever is available.
    """
    tables = _get_rotation_tables()
    bo = tables["bullpen_order"]

    rows = conn.execute(
        select(bo).where(bo.c.team_id == team_id).order_by(bo.c.slot.asc())
    ).mappings().all()

    bp_pitchers = [
        {"player_id": int(r["player_id"]), "role": r.get("role") or "middle"}
        for r in rows
        if int(r["player_id"]) not in exclude_pids
    ]
    if not bp_pitchers:
        return None

    bp_ids = [p["player_id"] for p in bp_pitchers]

    # Load stamina + injury data
    stamina_by_player = get_effective_stamina_bulk(conn, bp_ids, league_year_id)
    injury_malus = get_active_injury_malus_bulk(conn, bp_ids)
    _apply_injury_stamina_pct(stamina_by_player, injury_malus)

    # Load endurance ratings for ranking
    ratings = _load_pitcher_ratings_bulk(conn, bp_ids)

    candidates = []
    for bp in bp_pitchers:
        pid = bp["player_id"]
        stamina = stamina_by_player.get(pid, 100)
        if stamina < _SPOT_START_STAMINA_THRESHOLD:
            continue
        role = bp["role"]
        pendurance = _safe_float(ratings.get(pid, {}).get("pendurance_base"))
        role_priority = _SPOT_START_ROLE_PRIORITY.get(role, 2)
        candidates.append({
            "player_id": pid,
            "slot": None,
            "stamina": stamina,
            "usage_preference": "normal",
            "threshold": _SPOT_START_STAMINA_THRESHOLD,
            "role_priority": role_priority,
            "pendurance": pendurance,
            "is_spot_starter": True,
        })

    if not candidates:
        return None

    # Sort: prefer lower role_priority (mop_up first), then higher endurance
    candidates.sort(key=lambda c: (c["role_priority"], -c["pendurance"]))
    best = candidates[0]
    logger.info(
        "Bullpen spot starter for team %s: player %s (role_pri=%d, pendurance=%.1f, stamina=%d)",
        team_id, best["player_id"], best["role_priority"], best["pendurance"], best["stamina"],
    )
    return best


def _find_bullpen_spot_starter_from_cache(
    cache,
    team_id: int,
    exclude_pids: set[int],
) -> Dict[str, Any] | None:
    """
    Cache-aware variant of _find_bullpen_spot_starter.  Zero DB queries.
    """
    bp_rows = cache.bullpen_order_by_team.get(team_id, [])

    bp_pitchers = [
        {"player_id": int(r["player_id"]), "role": r.get("role") or "middle"}
        for r in bp_rows
        if int(r["player_id"]) not in exclude_pids
    ]
    if not bp_pitchers:
        return None

    candidates = []
    for bp in bp_pitchers:
        pid = bp["player_id"]
        raw_stamina = cache.stamina.get(pid, 100)
        stam_pct = cache.injury_malus.get(pid, {}).get("stamina_pct")
        if stam_pct is not None:
            raw_stamina = int(max(0, raw_stamina * float(stam_pct)))
        if raw_stamina < _SPOT_START_STAMINA_THRESHOLD:
            continue
        role = bp["role"]
        pendurance = _safe_float(cache.player_rows.get(pid, {}).get("pendurance_base"))
        role_priority = _SPOT_START_ROLE_PRIORITY.get(role, 2)
        candidates.append({
            "player_id": pid,
            "slot": None,
            "stamina": raw_stamina,
            "usage_preference": "normal",
            "threshold": _SPOT_START_STAMINA_THRESHOLD,
            "role_priority": role_priority,
            "pendurance": pendurance,
            "is_spot_starter": True,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda c: (c["role_priority"], -c["pendurance"]))
    best = candidates[0]
    logger.info(
        "Bullpen spot starter (cached) for team %s: player %s (role_pri=%d, pendurance=%.1f, stamina=%d)",
        team_id, best["player_id"], best["role_priority"], best["pendurance"], best["stamina"],
    )
    return best


def _fallback_pick_starter_without_rotation(
    conn,
    team_id: int,
    league_year_id: int,
) -> Dict[str, Any]:
    """
    Fallback when no team_pitching_rotation row exists:

      - Find all pitchers on this team.
      - Compute ability score for each (weighted: pendurance, pgencontrol, pickoff, pitch quality).
      - Compute stamina + usage_preference for rest eligibility.
      - Among pitchers who meet their stamina threshold, pick highest ability score.
      - If none meet threshold, pick highest ability score regardless (desperation mode).
    """
    pitcher_ids = _get_team_pitcher_ids(conn, team_id)
    if not pitcher_ids:
        raise ValueError(f"No pitchers found on roster for team_id {team_id}")

    # Bulk-load all needed data
    stamina_by_player = get_effective_stamina_bulk(conn, pitcher_ids, league_year_id)
    injury_malus = get_active_injury_malus_bulk(conn, pitcher_ids)
    _apply_injury_stamina_pct(stamina_by_player, injury_malus)
    usage_prefs = _get_usage_preferences_bulk(conn, pitcher_ids)
    ratings_by_player = _load_pitcher_ratings_bulk(conn, pitcher_ids)

    candidates: List[Dict[str, Any]] = []

    for pid in pitcher_ids:
        stamina = stamina_by_player.get(pid, 100)
        usage_pref = usage_prefs.get(pid, "normal")
        threshold = _USAGE_THRESHOLDS.get(usage_pref, 70)

        # Compute ability score from ratings
        player_ratings = ratings_by_player.get(pid, {})
        ability_score = _compute_pitcher_ability_score(player_ratings)

        candidates.append(
            {
                "player_id": pid,
                "slot": None,  # no explicit slot in fallback
                "stamina": stamina,
                "usage_preference": usage_pref,
                "threshold": threshold,
                "ability_score": ability_score,
            }
        )

    # Filter to pitchers who meet their stamina threshold
    rested_candidates = [c for c in candidates if c["stamina"] >= c["threshold"]]

    if rested_candidates:
        # Pick highest ability score among rested pitchers
        starter = max(rested_candidates, key=lambda c: c["ability_score"])
    else:
        # Desperation mode: pick highest ability score regardless of stamina
        starter = max(candidates, key=lambda c: c["ability_score"])
        logger.warning(
            "Desperation mode: no pitchers meet stamina threshold for team_id %s",
            team_id,
        )

    logger.info(
        "Fallback rotation for team_id %s: starter %s (ability=%.2f, stamina=%s, usage_pref=%s)",
        team_id,
        starter["player_id"],
        starter["ability_score"],
        starter["stamina"],
        starter["usage_preference"],
    )

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
        "scheduled_rotation_slot": None,  # no rotation configured
    }


def pick_starting_pitcher(
    conn,
    team_id: int,
    league_year_id: int,
) -> Dict[str, Any]:
    """
    Pick a starting pitcher for a team.

    Primary path:
      - Use team_pitching_rotation + slots + state (if configured).

    Fallback:
      - If no rotation row exists, pick among all pitchers on the team using
        stamina + usage_preference thresholds.
    """
    tables = _get_rotation_tables()
    rotation = tables["rotation"]
    slots = tables["slots"]
    state = tables["state"]

    # Try to use configured rotation
    rot_row = conn.execute(
        select(rotation).where(rotation.c.team_id == team_id)
    ).mappings().first()

    if not rot_row:
        # Fallback: auto-pick SP without a configured rotation
        return _fallback_pick_starter_without_rotation(conn, team_id, league_year_id)

    rotation_id = rot_row["id"]
    rotation_size = int(rot_row["rotation_size"])

    slot_rows = conn.execute(
        select(slots)
        .where(slots.c.rotation_id == rotation_id)
        .order_by(slots.c.slot.asc())
    ).mappings().all()

    if not slot_rows or len(slot_rows) != rotation_size:
        # If rotation row exists but slots are incomplete, also fallback
        logger.warning(
            "Incomplete rotation config for team_id %s; using fallback starter selection",
            team_id,
        )
        return _fallback_pick_starter_without_rotation(conn, team_id, league_year_id)

    st_row = conn.execute(
        select(state).where(state.c.team_id == team_id)
    ).mappings().first()

    current_slot = int(st_row["current_slot"]) if st_row and st_row["current_slot"] is not None else 0

    # Order: next slot after current_slot, wrapping around
    slot_order: List[int] = []
    for i in range(rotation_size):
        next_slot = ((current_slot + i) % rotation_size) + 1
        slot_order.append(next_slot)

    # Collect all pitcher IDs from rotation slots
    pitcher_ids = [int(r["player_id"]) for r in slot_rows]

    # Bulk-load stamina and usage preferences for all rotation pitchers
    stamina_by_player = get_effective_stamina_bulk(conn, pitcher_ids, league_year_id)
    injury_malus = get_active_injury_malus_bulk(conn, pitcher_ids)
    _apply_injury_stamina_pct(stamina_by_player, injury_malus)
    usage_prefs = _get_usage_preferences_bulk(conn, pitcher_ids)

    candidates: List[Dict[str, Any]] = []

    for slot_num in slot_order:
        s_row = next(r for r in slot_rows if r["slot"] == slot_num)
        pid = int(s_row["player_id"])

        stamina = stamina_by_player.get(pid, 100)
        usage_pref = usage_prefs.get(pid, "normal")
        threshold = _USAGE_THRESHOLDS.get(usage_pref, 70)

        candidates.append(
            {
                "player_id": pid,
                "slot": slot_num,
                "stamina": stamina,
                "usage_preference": usage_pref,
                "threshold": threshold,
            }
        )

    # The first candidate is the scheduled starter (whose turn it is)
    scheduled = candidates[0]
    scheduled_slot = scheduled["slot"]

    if scheduled["stamina"] >= scheduled["threshold"]:
        # Normal case: scheduled starter is good to go
        starter = scheduled
    else:
        # Scheduled starter unavailable — try a bullpen spot starter
        # before compressing the rotation by using the next rotation pitcher
        rotation_pids = {c["player_id"] for c in candidates}
        spot = _find_bullpen_spot_starter(
            conn, team_id, league_year_id, exclude_pids=rotation_pids,
        )
        if spot is not None:
            starter = spot
            candidates.append(spot)
        else:
            # No bullpen option — try remaining rotation pitchers
            starter = None
            for cand in candidates[1:]:
                if cand["stamina"] >= cand["threshold"]:
                    starter = cand
                    break
            if starter is None:
                # Desperation: highest stamina from anyone in rotation
                starter = max(candidates, key=lambda c: c["stamina"])
                logger.warning(
                    "Desperation mode: no pitchers meet threshold for team_id %s",
                    team_id,
                )

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
        "scheduled_rotation_slot": scheduled_slot,
    }


# -------------------------------------------------------------------
# Cache-aware variant (zero DB queries)
# -------------------------------------------------------------------

def pick_starting_pitcher_from_cache(cache, team_id: int) -> Dict[str, Any]:
    """
    Same logic as pick_starting_pitcher but reads entirely from SubweekCache.
    No database queries.
    """
    rot_row = cache.rotation_by_team.get(team_id)

    if not rot_row:
        return _fallback_pick_starter_from_cache(cache, team_id)

    rotation_id = int(rot_row["id"])
    rotation_size = int(rot_row["rotation_size"])

    slot_rows = cache.rotation_slots_by_rotation.get(rotation_id, [])

    if not slot_rows or len(slot_rows) != rotation_size:
        return _fallback_pick_starter_from_cache(cache, team_id)

    st_row = cache.rotation_state_by_team.get(team_id)
    current_slot = int(st_row["current_slot"]) if st_row and st_row.get("current_slot") is not None else 0

    slot_order: List[int] = []
    for i in range(rotation_size):
        next_slot = ((current_slot + i) % rotation_size) + 1
        slot_order.append(next_slot)

    pitcher_ids = [int(r["player_id"]) for r in slot_rows]

    usage_prefs = _get_usage_prefs_from_cache(cache, pitcher_ids)

    candidates: List[Dict[str, Any]] = []

    for slot_num in slot_order:
        s_row = next((r for r in slot_rows if r["slot"] == slot_num), None)
        if s_row is None:
            continue
        pid = int(s_row["player_id"])

        raw_stamina = cache.stamina.get(pid, 100)
        stam_pct = cache.injury_malus.get(pid, {}).get("stamina_pct")
        if stam_pct is not None:
            raw_stamina = int(max(0, raw_stamina * float(stam_pct)))
        usage_pref = usage_prefs.get(pid, "normal")
        threshold = _USAGE_THRESHOLDS.get(usage_pref, 70)

        candidates.append({
            "player_id": pid,
            "slot": slot_num,
            "stamina": raw_stamina,
            "usage_preference": usage_pref,
            "threshold": threshold,
        })

    # The first candidate is the scheduled starter (whose turn it is)
    scheduled = candidates[0] if candidates else None
    scheduled_slot = scheduled["slot"] if scheduled else None

    if scheduled and scheduled["stamina"] >= scheduled["threshold"]:
        starter = scheduled
    else:
        # Scheduled starter unavailable — try a bullpen spot starter
        rotation_pids = {c["player_id"] for c in candidates}
        spot = _find_bullpen_spot_starter_from_cache(
            cache, team_id, exclude_pids=rotation_pids,
        )
        if spot is not None:
            starter = spot
            candidates.append(spot)
        else:
            # No bullpen option — try remaining rotation pitchers
            starter = None
            for cand in candidates[1:]:
                if cand["stamina"] >= cand["threshold"]:
                    starter = cand
                    break
            if starter is None and candidates:
                starter = max(candidates, key=lambda c: c["stamina"])

    if starter is None:
        raise ValueError(f"No rotation candidates found for team_id {team_id}")

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
        "scheduled_rotation_slot": scheduled_slot,
    }


def _fallback_pick_starter_from_cache(cache, team_id: int) -> Dict[str, Any]:
    """
    Fallback rotation selection using cached data.
    Same logic as _fallback_pick_starter_without_rotation but zero DB.
    """
    pitcher_ids = cache.pitcher_ids_by_team.get(team_id, [])
    if not pitcher_ids:
        raise ValueError(f"No pitchers found on roster for team_id {team_id}")

    usage_prefs = _get_usage_prefs_from_cache(cache, pitcher_ids)

    candidates: List[Dict[str, Any]] = []

    for pid in pitcher_ids:
        raw_stamina = cache.stamina.get(pid, 100)
        stam_pct = cache.injury_malus.get(pid, {}).get("stamina_pct")
        if stam_pct is not None:
            raw_stamina = int(max(0, raw_stamina * float(stam_pct)))
        usage_pref = usage_prefs.get(pid, "normal")
        threshold = _USAGE_THRESHOLDS.get(usage_pref, 70)

        player_ratings = cache.player_rows.get(pid, {})
        ability_score = _compute_pitcher_ability_score(player_ratings)

        candidates.append({
            "player_id": pid,
            "slot": None,
            "stamina": raw_stamina,
            "usage_preference": usage_pref,
            "threshold": threshold,
            "ability_score": ability_score,
        })

    rested = [c for c in candidates if c["stamina"] >= c["threshold"]]

    if rested:
        starter = max(rested, key=lambda c: c["ability_score"])
    else:
        starter = max(candidates, key=lambda c: c["ability_score"])
        logger.warning(
            "Desperation mode (cached): no pitchers meet stamina threshold for team_id %s",
            team_id,
        )

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
        "scheduled_rotation_slot": None,  # no rotation configured
    }


def _get_usage_prefs_from_cache(cache, player_ids: List[int]) -> Dict[int, str]:
    """Extract usage_preference from cached strategy rows."""
    result = {}
    for pid in player_ids:
        rows = cache.strategy_rows_by_player.get(pid)
        if rows:
            pref = rows[0].get("usage_preference")
            result[pid] = pref if pref else "normal"
        else:
            result[pid] = "normal"
    return result


# -------------------------------------------------------------------
# Rotation state advancement (post-game)
# -------------------------------------------------------------------

def advance_rotation_states_bulk(conn, payloads: List[Dict[str, Any]]) -> int:
    """
    After a subweek's games are played, advance each team's rotation slot
    based on which pitcher actually started.

    For each team that has a configured rotation, finds the slot of the
    pitcher who started and sets current_slot to that slot so the next
    game starts from the following slot.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        payloads: List of game payloads (each has home_side/away_side
                  with team_id and starting_pitcher_id).

    Returns:
        Number of team rotation states advanced.
    """
    from sqlalchemy import text as sa_text

    # Collect (team_id, starter_id, game_id, scheduled_slot) from all games
    team_starters: Dict[int, tuple] = {}  # team_id → (starter_id, game_id, scheduled_slot)
    for payload in payloads:
        game_id = payload.get("game_id")
        for side_key in ("home_side", "away_side"):
            side = payload.get(side_key) or {}
            team_id = side.get("team_id")
            starter_id = side.get("starting_pitcher_id")
            scheduled_slot = side.get("scheduled_rotation_slot")
            if team_id and starter_id:
                # Last game in subweek wins (teams play at most once per subweek)
                team_starters[int(team_id)] = (int(starter_id), game_id, scheduled_slot)

    if not team_starters:
        return 0

    # Load all rotation configs + slots for these teams in one pass
    team_ids_ph = ", ".join(f":t{i}" for i in range(len(team_starters)))
    team_params = {f"t{i}": tid for i, tid in enumerate(team_starters.keys())}

    rot_rows = conn.execute(sa_text(
        f"SELECT id, team_id, rotation_size FROM team_pitching_rotation "
        f"WHERE team_id IN ({team_ids_ph})"
    ), team_params).mappings().all()

    if not rot_rows:
        return 0

    rotation_ids = [int(r["id"]) for r in rot_rows]
    rot_ids_ph = ", ".join(f":r{i}" for i in range(len(rotation_ids)))
    rot_params = {f"r{i}": rid for i, rid in enumerate(rotation_ids)}

    slot_rows = conn.execute(sa_text(
        f"SELECT rotation_id, slot, player_id FROM team_pitching_rotation_slots "
        f"WHERE rotation_id IN ({rot_ids_ph})"
    ), rot_params).mappings().all()

    # Build lookup: rotation_id → {player_id → slot}
    pid_to_slot: Dict[int, Dict[int, int]] = {}
    for sr in slot_rows:
        rid = int(sr["rotation_id"])
        pid_to_slot.setdefault(rid, {})[int(sr["player_id"])] = int(sr["slot"])

    # Build rotation_id → team_id mapping
    rot_by_team = {int(r["team_id"]): (int(r["id"]), int(r["rotation_size"])) for r in rot_rows}

    # Advance each team's rotation state
    count = 0
    update_sql = sa_text("""
        INSERT INTO team_rotation_state (team_id, current_slot, last_game_id, last_updated_at)
        VALUES (:team_id, :new_slot, :game_id, NOW())
        ON DUPLICATE KEY UPDATE
            current_slot = :new_slot,
            last_game_id = :game_id,
            last_updated_at = NOW()
    """)

    for team_id, (starter_id, game_id, scheduled_slot) in team_starters.items():
        rot_info = rot_by_team.get(team_id)
        if not rot_info:
            continue  # Team has no configured rotation

        rotation_id, rotation_size = rot_info
        slot_map = pid_to_slot.get(rotation_id, {})
        starter_slot = slot_map.get(starter_id)

        if starter_slot is not None:
            # Starter is in the rotation — advance to their slot
            new_slot = starter_slot
        elif scheduled_slot is not None:
            # Spot starter (bullpen arm) filled in — advance past the
            # scheduled slot so the rotation doesn't get stuck
            new_slot = int(scheduled_slot)
        else:
            # No rotation info at all (desperation/fallback) — don't advance
            continue

        conn.execute(update_sql, {
            "team_id": team_id,
            "new_slot": new_slot,
            "game_id": int(game_id) if game_id else None,
        })
        count += 1

    logger.info("advance_rotation_states_bulk: advanced %d team rotations", count)
    return count
