# services/listed_position.py
"""
Listed position derivation, storage, and override management.

Every rostered player gets a single listed position (e.g. "ss", "sp", "rp")
derived from three sources in priority order:

  1. override  — user explicitly sets via roster UI
  2. gameplan  — derived from team_position_plan / rotation on gameplan save
  3. auto      — derived from player ratings on season init / advance-week

The auto layer is the baseline for ALL teams.  Gameplan and override
layers are applied on top without clobbering each other.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)


def _resolve_league_year_id(conn) -> int:
    """Resolve current league_year_id from timestamp_state → league_years."""
    row = conn.execute(text(
        "SELECT id FROM league_years WHERE league_year = "
        "(SELECT season FROM timestamp_state WHERE id = 1)"
    )).first()
    if not row:
        raise ValueError("Cannot resolve league_year_id from timestamp_state")
    return int(row[0])


# ── constants ────────────────────────────────────────────────────────

VALID_POSITION_CODES = frozenset({
    "c", "fb", "sb", "tb", "ss", "lf", "cf", "rf", "dh", "sp", "rp",
})

POSITION_DISPLAY = {
    "c": "C", "fb": "1B", "sb": "2B", "tb": "3B", "ss": "SS",
    "lf": "LF", "cf": "CF", "rf": "RF", "dh": "DH",
    "sp": "SP", "rp": "RP",
}

# Position rating keys — same as services/lineups.py._POS_RATING_KEY
_POS_RATING_KEY = {
    "c": "c_rating",
    "fb": "fb_rating",
    "sb": "sb_rating",
    "tb": "tb_rating",
    "ss": "ss_rating",
    "lf": "lf_rating",
    "cf": "cf_rating",
    "rf": "rf_rating",
}

# Tie-break order (scarcity): C > SS > CF > 3B > 2B > LF > RF > 1B
_POSITION_PRIORITY = ["c", "ss", "cf", "tb", "sb", "lf", "rf", "fb"]

# Position weights for computing raw position ratings from base attributes.
# Imported at function level to avoid circular imports.
_position_weights_cache: Optional[dict] = None


def _get_position_weights():
    """Lazy-load default position weights from rosters module."""
    global _position_weights_cache
    if _position_weights_cache is None:
        from rosters import _DEFAULT_POSITION_WEIGHTS
        _position_weights_cache = _DEFAULT_POSITION_WEIGHTS
    return _position_weights_cache


# ── pure logic ───────────────────────────────────────────────────────

def _compute_raw_position_rating(player: dict, rating_type: str) -> Optional[float]:
    """
    Compute a single raw position rating for a player dict using the
    default position weights.  Mirrors _compute_derived_raw_ratings()
    but works on plain dicts instead of SQLAlchemy rows.
    """
    weights = _get_position_weights()
    wt_map = weights.get(rating_type)
    if not wt_map:
        return None

    total_w = 0.0
    total_v = 0.0
    for col, w in wt_map.items():
        if w <= 0:
            continue
        v = player.get(col)
        if v is None:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        total_v += num * w
        total_w += w
    if total_w <= 0:
        return None
    return total_v / total_w


def compute_auto_position(player: dict) -> str:
    """
    Determine the best-fit position for a player based on ratings.

    Position players: highest raw position rating wins, with
    _POSITION_PRIORITY breaking ties (scarce positions first).

    Pitchers: returns "sp" as default (caller refines to "rp" using
    rotation data).
    """
    ptype = (player.get("ptype") or "").strip().lower()
    if ptype == "pitcher":
        return "sp"  # caller refines based on rotation membership

    best_pos = "dh"  # fallback
    best_score = -1.0

    for pos in _POSITION_PRIORITY:
        rating_key = _POS_RATING_KEY[pos]
        score = _compute_raw_position_rating(player, rating_key)
        if score is not None and score > best_score:
            best_score = score
            best_pos = pos

    return best_pos


# ── team-level derivation ────────────────────────────────────────────

def derive_positions_for_team(
    conn, team_id: int, league_year_id: int
) -> List[dict]:
    """
    Derive listed positions for every rostered player on a team.

    Priority:
      1. team_position_plan → highest-priority entry per player
      2. team_pitching_rotation_slots → SP
      3. auto-derive from ratings → best position / RP

    Returns list of {player_id, team_id, position_code, source} dicts.
    """
    # Load roster: all players with active contracts on this team
    roster_rows = conn.execute(text("""
        SELECT p.id AS player_id, p.ptype,
               p.power_base, p.contact_base, p.eye_base, p.discipline_base,
               p.speed_base, p.baserunning_base, p.basereaction_base,
               p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
               p.throwacc_base, p.throwpower_base,
               p.catchframe_base, p.catchsequence_base,
               p.pendurance_base, p.pgencontrol_base, p.psequencing_base,
               p.pthrowpower_base, p.pickoff_base,
               p.pitch1_name, p.pitch1_consist_base, p.pitch1_pacc_base,
               p.pitch1_pbrk_base, p.pitch1_pcntrl_base,
               p.pitch2_name, p.pitch2_consist_base, p.pitch2_pacc_base,
               p.pitch2_pbrk_base, p.pitch2_pcntrl_base,
               p.pitch3_name, p.pitch3_consist_base, p.pitch3_pacc_base,
               p.pitch3_pbrk_base, p.pitch3_pcntrl_base,
               p.pitch4_name, p.pitch4_consist_base, p.pitch4_pacc_base,
               p.pitch4_pbrk_base, p.pitch4_pcntrl_base,
               p.pitch5_name, p.pitch5_consist_base, p.pitch5_pacc_base,
               p.pitch5_pbrk_base, p.pitch5_pcntrl_base
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        JOIN teams t ON t.orgID = cts.orgID AND t.team_level = c.current_level
        WHERE t.id = :tid
    """), {"tid": team_id}).all()

    if not roster_rows:
        return []

    # Build player dicts
    players = []
    for row in roster_rows:
        m = row._mapping
        players.append(dict(m))

    player_ids = [p["player_id"] for p in players]

    # Load gameplan: team_position_plan (highest priority per player)
    plan_map: Dict[int, str] = {}  # player_id -> position_code
    plan_rows = conn.execute(text("""
        SELECT player_id, position_code
        FROM team_position_plan
        WHERE team_id = :tid
        ORDER BY priority ASC
    """), {"tid": team_id}).all()
    for r in plan_rows:
        pid = r[0]
        if pid not in plan_map:  # first = highest priority
            plan_map[pid] = r[1]

    # Load rotation pitcher IDs
    rotation_pids: set = set()
    rot_rows = conn.execute(text("""
        SELECT tprs.player_id
        FROM team_pitching_rotation_slots tprs
        JOIN team_pitching_rotation tpr ON tpr.id = tprs.rotation_id
        WHERE tpr.team_id = :tid
    """), {"tid": team_id}).all()
    for r in rot_rows:
        rotation_pids.add(r[0])

    # Derive position for each player
    results = []
    for p in players:
        pid = p["player_id"]
        ptype = (p.get("ptype") or "").strip().lower()

        if ptype == "pitcher":
            # SP if in rotation, RP otherwise
            if pid in rotation_pids:
                pos = "sp"
                src = "gameplan" if rotation_pids else "auto"
            else:
                pos = "rp"
                src = "gameplan" if rotation_pids else "auto"
        elif pid in plan_map:
            # Position player with gameplan entry
            plan_pos = plan_map[pid]
            # Map "p" (pitcher slot in plan) to position context
            if plan_pos == "p":
                pos = "sp" if pid in rotation_pids else "rp"
            else:
                pos = plan_pos
            src = "gameplan"
        else:
            # Auto-derive from ratings
            pos = compute_auto_position(p)
            src = "auto"

        results.append({
            "player_id": pid,
            "team_id": team_id,
            "position_code": pos,
            "source": src,
        })

    return results


# ── bulk persistence ─────────────────────────────────────────────────

_UPSERT_BATCH_SIZE = 100


def bulk_upsert_positions(conn, positions: List[dict], league_year_id: int):
    """
    Bulk upsert listed positions.  Preserves rows with source='override'.
    Uses multi-row INSERT for performance.
    """
    if not positions:
        return

    for i in range(0, len(positions), _UPSERT_BATCH_SIZE):
        batch = positions[i:i + _UPSERT_BATCH_SIZE]
        value_clauses = []
        params = {"lyid": league_year_id}
        for j, pos in enumerate(batch):
            value_clauses.append(f"(:pid{j}, :tid{j}, :lyid, :pos{j}, :src{j})")
            params[f"pid{j}"] = pos["player_id"]
            params[f"tid{j}"] = pos["team_id"]
            params[f"pos{j}"] = pos["position_code"]
            params[f"src{j}"] = pos["source"]

        sql = f"""
            INSERT INTO player_listed_position
                (player_id, team_id, league_year_id, position_code, source)
            VALUES {', '.join(value_clauses)}
            AS new_row ON DUPLICATE KEY UPDATE
                position_code = IF(source = 'override', position_code, new_row.position_code),
                source = IF(source = 'override', source, new_row.source),
                updated_at = CURRENT_TIMESTAMP
        """
        conn.execute(text(sql), params)


def refresh_team(conn, team_id: int, league_year_id: int):
    """Derive and upsert listed positions for a single team."""
    positions = derive_positions_for_team(conn, team_id, league_year_id)
    bulk_upsert_positions(conn, positions, league_year_id)
    return len(positions)


def refresh_all_teams(conn, league_year_id: int):
    """
    Recompute listed positions for every team with active rosters.
    Called on season init and advance-week.
    """
    team_rows = conn.execute(text("""
        SELECT DISTINCT t.id
        FROM teams t
        JOIN contracts c ON 1=1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE c.isActive = 1
          AND t.orgID = cts.orgID
          AND t.team_level = c.current_level
    """)).all()

    total = 0
    for row in team_rows:
        tid = row[0]
        try:
            count = refresh_team(conn, tid, league_year_id)
            total += count
        except Exception:
            log.exception(f"Failed to refresh listed positions for team {tid}")

    log.info(f"Listed positions refreshed: {total} players across {len(team_rows)} teams")
    return total


# ── override management ──────────────────────────────────────────────

def set_override(
    conn, player_id: int, team_id: int, league_year_id: int, position_code: str
):
    """Set a user override for a player's listed position."""
    if position_code not in VALID_POSITION_CODES:
        raise ValueError(f"Invalid position_code: {position_code}")

    conn.execute(text("""
        INSERT INTO player_listed_position
            (player_id, team_id, league_year_id, position_code, source)
        VALUES (:pid, :tid, :lyid, :pos, 'override')
        ON DUPLICATE KEY UPDATE
            position_code = :pos,
            source = 'override',
            updated_at = CURRENT_TIMESTAMP
    """), {
        "pid": player_id,
        "tid": team_id,
        "lyid": league_year_id,
        "pos": position_code,
    })


def clear_override(
    conn, player_id: int, team_id: int, league_year_id: int
):
    """
    Remove a user override and recompute the derived position.
    """
    # Check current row
    row = conn.execute(text("""
        SELECT source FROM player_listed_position
        WHERE player_id = :pid AND team_id = :tid AND league_year_id = :lyid
    """), {"pid": player_id, "tid": team_id, "lyid": league_year_id}).first()

    if not row or row[0] != "override":
        return  # nothing to clear

    # Recompute for this team and upsert (will overwrite since no longer override)
    positions = derive_positions_for_team(conn, team_id, league_year_id)
    player_pos = [p for p in positions if p["player_id"] == player_id]
    if player_pos:
        conn.execute(text("""
            UPDATE player_listed_position
            SET position_code = :pos, source = :src, updated_at = CURRENT_TIMESTAMP
            WHERE player_id = :pid AND team_id = :tid AND league_year_id = :lyid
        """), {
            "pos": player_pos[0]["position_code"],
            "src": player_pos[0]["source"],
            "pid": player_id,
            "tid": team_id,
            "lyid": league_year_id,
        })
    else:
        # Player no longer on roster — delete the row
        conn.execute(text("""
            DELETE FROM player_listed_position
            WHERE player_id = :pid AND team_id = :tid AND league_year_id = :lyid
        """), {"pid": player_id, "tid": team_id, "lyid": league_year_id})


# ── queries ──────────────────────────────────────────────────────────

def get_listed_position(
    conn, player_id: int, team_id: int, league_year_id: int
) -> Optional[dict]:
    """Get a single player's listed position."""
    row = conn.execute(text("""
        SELECT position_code, source
        FROM player_listed_position
        WHERE player_id = :pid AND team_id = :tid AND league_year_id = :lyid
    """), {"pid": player_id, "tid": team_id, "lyid": league_year_id}).first()

    if not row:
        return None
    return {
        "position_code": row[0],
        "display": POSITION_DISPLAY.get(row[0], row[0]),
        "source": row[1],
    }


def get_listed_positions_for_team(
    conn, team_id: int, league_year_id: int
) -> Dict[int, str]:
    """
    Bulk-load listed positions for all players on a team.
    Returns {player_id: display_position} (e.g. {12345: "SS"}).
    """
    rows = conn.execute(text("""
        SELECT player_id, position_code
        FROM player_listed_position
        WHERE team_id = :tid AND league_year_id = :lyid
    """), {"tid": team_id, "lyid": league_year_id}).all()

    return {r[0]: POSITION_DISPLAY.get(r[1], r[1]) for r in rows}


def get_listed_positions_for_teams(
    conn, team_ids: list, league_year_id: int
) -> Dict[int, Dict[int, str]]:
    """
    Bulk-load listed positions for multiple teams.
    Returns {team_id: {player_id: display_position}}.
    """
    if not team_ids:
        return {}

    placeholders = ", ".join(f":tid{i}" for i in range(len(team_ids)))
    params = {"lyid": league_year_id}
    params.update({f"tid{i}": tid for i, tid in enumerate(team_ids)})

    rows = conn.execute(text(f"""
        SELECT team_id, player_id, position_code
        FROM player_listed_position
        WHERE team_id IN ({placeholders}) AND league_year_id = :lyid
    """), params).all()

    result: Dict[int, Dict[int, str]] = {}
    for r in rows:
        tid, pid, pos = r[0], r[1], r[2]
        result.setdefault(tid, {})[pid] = POSITION_DISPLAY.get(pos, pos)
    return result
