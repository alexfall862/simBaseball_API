# services/default_gameplan.py
"""
Generate default gameplans for all teams at a given level.

Populates team_position_plan (defensive assignments), team_pitching_rotation
(5-man rotation), team_bullpen_order, and emergency_pitcher_id using the same
"best defender" logic the game engine uses.

Does NOT touch batting order roles, player strategies, or team strategy
settings beyond emergency_pitcher_id.
"""

import logging
from typing import Any, Dict, List, Tuple

from sqlalchemy import MetaData, Table, and_, select, text

logger = logging.getLogger("app")

_VERSION = "2026-03-14a"  # diagnostic: confirm deployed code version

# ---------------------------------------------------------------------------
# Constants (mirrored from lineups.py)
# ---------------------------------------------------------------------------

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

_POSITION_PRIORITY_ORDER = ["c", "ss", "cf", "tb", "sb", "lf", "rf", "fb"]

# Bullpen role assignments by slot position
_BULLPEN_ROLES = {
    1: "closer",
    2: "setup",
    3: "middle",
    4: "middle",
}
# Slots beyond 4 get "long", last slot gets "mop_up"

DEFAULT_ROTATION_SIZE = 5


# ---------------------------------------------------------------------------
# Scoring helpers (same formulas as lineups.py / rotation.py)
# ---------------------------------------------------------------------------

def _safe_float(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _compute_offense_score(p: Dict[str, Any]) -> float:
    return (
        _safe_float(p.get("contact_base"))
        + _safe_float(p.get("power_base"))
        + _safe_float(p.get("eye_base"))
        + _safe_float(p.get("discipline_base"))
    )


def _compute_pitcher_ability_score(p: Dict[str, Any]) -> float:
    """Same formula as rotation.py:34."""
    pendurance = _safe_float(p.get("pendurance_base"))
    pgencontrol = _safe_float(p.get("pgencontrol_base"))
    pickoff = _safe_float(p.get("pickoff_base"))

    pitch_qualities = []
    for n in range(1, 6):
        pacc = _safe_float(p.get(f"pitch{n}_pacc_base"))
        pbrk = _safe_float(p.get(f"pitch{n}_pbrk_base"))
        pcntrl = _safe_float(p.get(f"pitch{n}_pcntrl_base"))
        pconsist = _safe_float(p.get(f"pitch{n}_consist_base"))
        pitch_qualities.append((pacc + pbrk + pcntrl + pconsist) / 4.0)

    avg_pitch_quality = sum(pitch_qualities) / 5.0

    return (
        pendurance * 0.30
        + pgencontrol * 0.40
        + pickoff * 0.10
        + avg_pitch_quality * 0.20
    )


def _score_for_position(p: Dict[str, Any], pos: str) -> float:
    """Score a player for a defensive position (lineups.py formula)."""
    rating_key = _POS_RATING_KEY.get(pos)
    pos_rating = _safe_float(p.get(rating_key)) if rating_key else 0.0
    off_score = _compute_offense_score(p)
    return pos_rating * 0.7 + off_score * 0.3


def _bullpen_role_for_slot(slot: int, total: int) -> str:
    """Assign a bullpen role based on slot position."""
    if slot == total:
        return "mop_up"
    return _BULLPEN_ROLES.get(slot, "long")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_default_gameplans(
    conn,
    team_level: int,
    league_year_id: int,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Generate default gameplans for all teams at a given level.

    Args:
        conn: SQLAlchemy connection (caller manages transaction).
        team_level: The team_level to process (e.g. 9 for MLB).
        league_year_id: Current league year.
        overwrite: If True, regenerate even if a gameplan already exists.

    Returns:
        {teams_processed, teams_skipped, errors: [{team_id, message}]}
    """
    # Get all teams at this level
    teams = conn.execute(text("""
        SELECT id AS team_id, orgID AS org_id
        FROM teams
        WHERE team_level = :level
        ORDER BY id
    """), {"level": team_level}).mappings().all()

    if not teams:
        return {"teams_processed": 0, "teams_skipped": 0, "errors": []}

    # Check DH rule for this level
    use_dh = _check_use_dh(conn, team_level)

    processed = 0
    skipped = 0
    errors = []

    for team in teams:
        team_id = team["team_id"]
        org_id = team["org_id"]
        try:
            did_generate = _generate_for_team(
                conn, team_id, org_id, league_year_id, use_dh, overwrite
            )
            if did_generate:
                processed += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Failed to generate gameplan for team %d: %s",
                           team_id, e, exc_info=True)
            errors.append({"team_id": team_id, "message": str(e)})

    return {
        "teams_processed": processed,
        "teams_skipped": skipped,
        "errors": errors,
    }


def _check_use_dh(conn, team_level: int) -> bool:
    """Check if this level uses the DH rule."""
    try:
        row = conn.execute(text(
            "SELECT dh_bool FROM level_rules WHERE league_level = :lvl LIMIT 1"
        ), {"lvl": team_level}).first()
        return bool(row[0]) if row else False
    except Exception:
        logger.warning("Could not check DH rule for level %d, defaulting to True",
                       team_level, exc_info=True)
        return True


# ---------------------------------------------------------------------------
# Per-team generation
# ---------------------------------------------------------------------------

def _generate_for_team(
    conn,
    team_id: int,
    org_id: int,
    league_year_id: int,
    use_dh: bool,
    overwrite: bool,
) -> bool:
    """
    Generate default gameplan for one team.
    Returns True if generated, False if skipped.
    """
    # Check if team already has a position plan
    if not overwrite:
        existing = conn.execute(text(
            "SELECT 1 FROM team_position_plan WHERE team_id = :tid LIMIT 1"
        ), {"tid": team_id}).first()
        if existing:
            return False

    # Load roster
    from services.game_payload import (
        _get_team_roster_player_ids,
        build_engine_player_views_bulk,
    )

    player_ids = _get_team_roster_player_ids(conn, team_id)
    if not player_ids:
        logger.warning("Team %d has no roster, skipping", team_id)
        return False

    players = build_engine_player_views_bulk(conn, player_ids)
    if not players:
        logger.warning("Team %d: no player data loaded, skipping", team_id)
        return False

    # Classify pitchers vs position players
    pitchers = {}
    position_players = {}
    for pid, p in players.items():
        if (p.get("ptype") or "").lower() == "pitcher":
            pitchers[pid] = p
        else:
            position_players[pid] = p

    # Clear existing data if overwriting
    if overwrite:
        _clear_team_gameplan(conn, team_id)

    # A. Pitching rotation (top N by ability)
    rotation_ids = _assign_rotation(conn, team_id, pitchers)

    # B. Bullpen (remaining pitchers)
    bullpen_pitcher_ids = {pid for pid in pitchers if pid not in rotation_ids}
    _assign_bullpen(conn, team_id, pitchers, bullpen_pitcher_ids)

    # C. Defensive positions
    _assign_defense(conn, team_id, position_players, use_dh)

    # D. Emergency pitcher (position player with best arm)
    _assign_emergency_pitcher(conn, team_id, position_players)

    # E. Refresh listed positions
    try:
        from services.listed_position import refresh_team
        refresh_team(conn, team_id, league_year_id)
    except Exception:
        logger.debug("listed position refresh failed for team %d", team_id)

    return True


def _clear_team_gameplan(conn, team_id: int):
    """Clear existing gameplan data for a team."""
    conn.execute(text(
        "DELETE FROM team_position_plan WHERE team_id = :tid"
    ), {"tid": team_id})

    # Clear rotation slots (need rotation_id first)
    rot = conn.execute(text(
        "SELECT id FROM team_pitching_rotation WHERE team_id = :tid"
    ), {"tid": team_id}).first()
    if rot:
        conn.execute(text(
            "DELETE FROM team_pitching_rotation_slots WHERE rotation_id = :rid"
        ), {"rid": rot[0]})
        conn.execute(text(
            "DELETE FROM team_pitching_rotation WHERE id = :rid"
        ), {"rid": rot[0]})

    conn.execute(text(
        "DELETE FROM team_bullpen_order WHERE team_id = :tid"
    ), {"tid": team_id})

    # Reset rotation state
    conn.execute(text("""
        UPDATE team_rotation_state SET current_slot = 0
        WHERE team_id = :tid
    """), {"tid": team_id})


# ---------------------------------------------------------------------------
# Rotation assignment
# ---------------------------------------------------------------------------

def _assign_rotation(conn, team_id: int,
                     pitchers: Dict[int, Dict]) -> set:
    """
    Assign top pitchers to a rotation by ability score.
    Returns set of pitcher IDs placed in rotation.
    """
    if not pitchers:
        return set()

    # Rank all pitchers by ability
    ranked = sorted(
        pitchers.items(),
        key=lambda kv: _compute_pitcher_ability_score(kv[1]),
        reverse=True,
    )

    rotation_size = min(DEFAULT_ROTATION_SIZE, len(ranked))
    rotation_pids = [pid for pid, _ in ranked[:rotation_size]]

    # Write team_pitching_rotation
    result = conn.execute(text("""
        INSERT INTO team_pitching_rotation (team_id, rotation_size)
        VALUES (:tid, :size)
        ON DUPLICATE KEY UPDATE rotation_size = VALUES(rotation_size)
    """), {"tid": team_id, "size": rotation_size})

    # Get rotation_id (handle both insert and update cases)
    rot_row = conn.execute(text(
        "SELECT id FROM team_pitching_rotation WHERE team_id = :tid"
    ), {"tid": team_id}).first()
    rotation_id = rot_row[0]

    # Clear and re-insert slots
    conn.execute(text(
        "DELETE FROM team_pitching_rotation_slots WHERE rotation_id = :rid"
    ), {"rid": rotation_id})

    for slot, pid in enumerate(rotation_pids, 1):
        conn.execute(text("""
            INSERT INTO team_pitching_rotation_slots (rotation_id, slot, player_id)
            VALUES (:rid, :slot, :pid)
        """), {"rid": rotation_id, "slot": slot, "pid": pid})

    # Init rotation state
    conn.execute(text("""
        INSERT INTO team_rotation_state (team_id, current_slot)
        VALUES (:tid, 0)
        ON DUPLICATE KEY UPDATE current_slot = 0
    """), {"tid": team_id})

    return set(rotation_pids)


# ---------------------------------------------------------------------------
# Bullpen assignment
# ---------------------------------------------------------------------------

def _assign_bullpen(conn, team_id: int,
                    pitchers: Dict[int, Dict],
                    bullpen_ids: set):
    """Assign remaining pitchers to bullpen with roles."""
    if not bullpen_ids:
        return

    # Rank by ability (best first)
    ranked = sorted(
        bullpen_ids,
        key=lambda pid: _compute_pitcher_ability_score(pitchers[pid]),
        reverse=True,
    )

    total = len(ranked)
    for slot, pid in enumerate(ranked, 1):
        role = _bullpen_role_for_slot(slot, total)
        conn.execute(text("""
            INSERT INTO team_bullpen_order (team_id, slot, player_id, role)
            VALUES (:tid, :slot, :pid, :role)
            ON DUPLICATE KEY UPDATE player_id = VALUES(player_id),
                                     role = VALUES(role)
        """), {"tid": team_id, "slot": slot, "pid": pid, "role": role})


# ---------------------------------------------------------------------------
# Defense assignment
# ---------------------------------------------------------------------------

def _assign_defense(conn, team_id: int,
                    position_players: Dict[int, Dict],
                    use_dh: bool):
    """Assign position players to defensive positions in priority order."""
    remaining = set(position_players.keys())

    for pos in _POSITION_PRIORITY_ORDER:
        if not remaining:
            break

        best_pid = None
        best_score = -1.0

        for pid in remaining:
            score = _score_for_position(position_players[pid], pos)
            if score > best_score:
                best_pid = pid
                best_score = score

        if best_pid is not None:
            conn.execute(text("""
                INSERT INTO team_position_plan
                    (team_id, position_code, vs_hand, player_id,
                     target_weight, priority, locked, lineup_role)
                VALUES (:tid, :pos, 'both', :pid, 1.0, 1, 0, 'balanced')
            """), {"tid": team_id, "pos": pos, "pid": best_pid})
            remaining.discard(best_pid)

    # DH assignment
    if use_dh and remaining:
        best_pid = None
        best_score = -1.0
        for pid in remaining:
            score = _score_for_position(position_players[pid], "dh")
            if score > best_score:
                best_pid = pid
                best_score = score

        if best_pid is not None:
            conn.execute(text("""
                INSERT INTO team_position_plan
                    (team_id, position_code, vs_hand, player_id,
                     target_weight, priority, locked, lineup_role)
                VALUES (:tid, 'dh', 'both', :pid, 1.0, 1, 0, 'balanced')
            """), {"tid": team_id, "pid": best_pid})
            remaining.discard(best_pid)


# ---------------------------------------------------------------------------
# Emergency pitcher
# ---------------------------------------------------------------------------

def _assign_emergency_pitcher(conn, team_id: int,
                              position_players: Dict[int, Dict]):
    """Pick the position player with the best arm as emergency pitcher."""
    if not position_players:
        return

    best_pid = max(
        position_players.keys(),
        key=lambda pid: _safe_float(position_players[pid].get("pthrowpower_base")),
    )

    # Upsert team_strategy with just emergency_pitcher_id
    conn.execute(text("""
        INSERT INTO team_strategy (team_id, emergency_pitcher_id)
        VALUES (:tid, :pid)
        ON DUPLICATE KEY UPDATE emergency_pitcher_id = VALUES(emergency_pitcher_id)
    """), {"tid": team_id, "pid": best_pid})
