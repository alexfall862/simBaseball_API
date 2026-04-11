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

_VERSION = "2026-04-10a"  # diagnostic: confirm deployed code version

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#
# All player evaluation in this module reads pre-computed *_rating values off
# the player dict produced by services.game_payload.build_engine_player_views_bulk().
# Those ratings are weighted averages of base attributes using the active
# weight calibration profile (rating_overall_weights table). This is the same
# pipeline that drives displayovr, so any rating-based decision here will
# automatically follow the active calibration profile.

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

_FIELDING_POSITIONS = ["c", "fb", "sb", "tb", "ss", "lf", "cf", "rf"]

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
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _bullpen_role_for_slot(slot: int, total: int) -> str:
    """Assign a bullpen role based on slot position."""
    if slot == total:
        return "mop_up"
    return _BULLPEN_ROLES.get(slot, "long")


# ---------------------------------------------------------------------------
# Hungarian (Kuhn-Munkres / Jonker-Volgenant) assignment solver
# ---------------------------------------------------------------------------

def _hungarian_min(cost: List[List[float]]) -> List[int]:
    """
    Solve the rectangular assignment problem minimizing total cost.

    Returns a list `result` of length n_rows where result[i] is the column
    index assigned to row i, or -1 if row i is unassigned (which only happens
    when n_rows > n_cols).

    Implementation: O(n^3) Jonker-Volgenant variant of Hungarian, padding to
    a square matrix with a sentinel value larger than any real cost so dummy
    assignments are taken last. Pure Python; no numpy/scipy dependency.
    """
    n_rows = len(cost)
    if n_rows == 0:
        return []
    n_cols = len(cost[0]) if cost[0] else 0
    if n_cols == 0:
        return [-1] * n_rows

    n = max(n_rows, n_cols)

    # Build square cost matrix padded with a large sentinel so dummy
    # rows/cols are only used to soak up surplus capacity.
    max_real = 0.0
    seen_any = False
    for row in cost:
        for v in row:
            if not seen_any or v > max_real:
                max_real = v
                seen_any = True
    pad = (max_real + 1.0) if seen_any else 1.0

    c = [[pad] * n for _ in range(n)]
    for i in range(n_rows):
        row = cost[i]
        for j in range(n_cols):
            c[i][j] = row[j]

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = c[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0 != 0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    result = [-1] * n_rows
    for j in range(1, n + 1):
        i = p[j]
        if i != 0 and (i - 1) < n_rows and (j - 1) < n_cols:
            result[i - 1] = j - 1
    return result


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
    Assign top pitchers to a rotation by sp_rating (calibrated).
    Returns set of pitcher IDs placed in rotation.
    """
    if not pitchers:
        return set()

    # Rank all pitchers by their calibrated starter rating.
    ranked = sorted(
        pitchers.items(),
        key=lambda kv: _safe_float(kv[1].get("sp_rating")),
        reverse=True,
    )

    rotation_size = min(DEFAULT_ROTATION_SIZE, len(ranked))
    rotation_pids = [pid for pid, _ in ranked[:rotation_size]]

    # Write team_pitching_rotation
    result = conn.execute(text("""
        INSERT INTO team_pitching_rotation (team_id, rotation_size)
        VALUES (:tid, :size)
        AS new_row ON DUPLICATE KEY UPDATE rotation_size = new_row.rotation_size
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

    if rotation_pids:
        slot_params = [
            {"rid": rotation_id, "slot": slot, "pid": pid}
            for slot, pid in enumerate(rotation_pids, 1)
        ]
        conn.execute(text("""
            INSERT INTO team_pitching_rotation_slots (rotation_id, slot, player_id)
            VALUES (:rid, :slot, :pid)
        """), slot_params)

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
    """Assign remaining pitchers to bullpen with roles, ranked by rp_rating."""
    if not bullpen_ids:
        return

    # Rank by calibrated reliever rating (best first).
    ranked = sorted(
        bullpen_ids,
        key=lambda pid: _safe_float(pitchers[pid].get("rp_rating")),
        reverse=True,
    )

    total = len(ranked)
    bullpen_params = [
        {"tid": team_id, "slot": slot, "pid": pid,
         "role": _bullpen_role_for_slot(slot, total)}
        for slot, pid in enumerate(ranked, 1)
    ]
    if bullpen_params:
        conn.execute(text("""
            INSERT INTO team_bullpen_order (team_id, slot, player_id, role)
            VALUES (:tid, :slot, :pid, :role)
            AS new_row ON DUPLICATE KEY UPDATE player_id = new_row.player_id,
                                     role = new_row.role
        """), bullpen_params)


# ---------------------------------------------------------------------------
# Defense assignment
# ---------------------------------------------------------------------------

def _assign_defense(conn, team_id: int,
                    position_players: Dict[int, Dict],
                    use_dh: bool):
    """
    Assign position players to defensive positions using a globally optimal
    Hungarian assignment over the calibrated per-position ratings.

    Each player has a *_rating value per position (c_rating, ss_rating, ...)
    computed from the active weight calibration profile. We build a
    player x position value matrix and find the assignment that maximizes
    total team rating, so a player only ends up at C if their drop-off at
    every other position is larger than the next-best catcher's gap to them.
    """
    if not position_players:
        return

    positions = list(_FIELDING_POSITIONS)
    if use_dh:
        positions.append("dh")

    players = list(position_players.items())  # [(pid, p), ...]
    n_players = len(players)
    n_positions = len(positions)

    # Hungarian minimizes; negate ratings to maximize total team rating.
    cost: List[List[float]] = [[0.0] * n_positions for _ in range(n_players)]
    for i, (_, p) in enumerate(players):
        for j, pos in enumerate(positions):
            rating = _safe_float(p.get(_POS_RATING_KEY[pos]))
            cost[i][j] = -rating

    assignment = _hungarian_min(cost)

    defense_params = []
    for i, j in enumerate(assignment):
        if j < 0 or j >= n_positions:
            # Surplus player, no slot for them.
            continue
        pid = players[i][0]
        pos = positions[j]
        defense_params.append({"tid": team_id, "pos": pos, "pid": pid})

    # Batch INSERT all position assignments
    if defense_params:
        conn.execute(text("""
            INSERT INTO team_position_plan
                (team_id, position_code, vs_hand, player_id,
                 target_weight, priority, locked, lineup_role)
            VALUES (:tid, :pos, 'both', :pid, 1.0, 1, 0, 'balanced')
        """), defense_params)


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
        AS new_row ON DUPLICATE KEY UPDATE emergency_pitcher_id = new_row.emergency_pitcher_id
    """), {"tid": team_id, "pid": best_pid})
