# services/rotation.py

import logging
from typing import Dict, Any, List

from sqlalchemy import MetaData, Table, select, and_
from db import get_engine
from rosters import _get_tables as _get_roster_tables
from services.stamina import get_effective_stamina, get_effective_stamina_bulk

logger = logging.getLogger(__name__)

_metadata = None
_rotation_tables = None

_USAGE_THRESHOLDS = {
    "only_fully_rested": 95,
    "normal": 70,
    "play_tired": 40,
    "desperation": 0,
}


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

    _rotation_tables = {
        "rotation": rotation,
        "slots": slots,
        "state": state,
        "strategies": strategies,
        "players": _get_roster_tables()["players"],
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


def _fallback_pick_starter_without_rotation(
    conn,
    team_id: int,
    league_year_id: int,
) -> Dict[str, Any]:
    """
    Fallback when no team_pitching_rotation row exists:

      - Find all pitchers on this team.
      - Compute stamina + usage_preference for each.
      - Pick the first who meets their threshold; if none, pick the highest stamina.
    """
    pitcher_ids = _get_team_pitcher_ids(conn, team_id)
    if not pitcher_ids:
        raise ValueError(f"No pitchers found on roster for team_id {team_id}")

    # Bulk-load stamina and usage preferences for all pitchers
    stamina_by_player = get_effective_stamina_bulk(conn, pitcher_ids, league_year_id)
    usage_prefs = _get_usage_preferences_bulk(conn, pitcher_ids)

    candidates: List[Dict[str, Any]] = []

    for pid in pitcher_ids:
        stamina = stamina_by_player.get(pid, 100)
        usage_pref = usage_prefs.get(pid, "normal")
        threshold = _USAGE_THRESHOLDS.get(usage_pref, 70)

        candidates.append(
            {
                "player_id": pid,
                "slot": None,  # no explicit slot in fallback
                "stamina": stamina,
                "usage_preference": usage_pref,
                "threshold": threshold,
            }
        )

    # Try to find someone who meets their threshold
    starter = None
    for cand in candidates:
        if cand["stamina"] >= cand["threshold"]:
            starter = cand
            break

    # If none meet threshold, pick the highest stamina (desperation mode)
    if starter is None:
        starter = max(candidates, key=lambda c: c["stamina"])

    logger.warning(
        "Fallback rotation used for team_id %s, starter %s (stamina=%s, usage_pref=%s)",
        team_id,
        starter["player_id"],
        starter["stamina"],
        starter["usage_preference"],
    )

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
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

    starter = None
    for cand in candidates:
        if cand["stamina"] >= cand["threshold"]:
            starter = cand
            break

    if starter is None:
        starter = max(candidates, key=lambda c: c["stamina"])

    return {
        "starter_id": starter["player_id"],
        "candidates": candidates,
    }
