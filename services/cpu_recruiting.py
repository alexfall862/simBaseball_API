"""
CPU recruiting AI — automates weekly investments for non-user college orgs.

Runs at the start of each week advance, BEFORE resolve_recruiting_week,
so CPU allocations settle into the about-to-resolve week alongside user input.

Selection model:
  - CPU orgs target balanced classes: 5 position players + 5 pitchers.
  - Targets picked by weighted random (by star rating) from uncommitted HS pool.
  - Targets persist on recruiting_board across weeks; replaced only when they
    commit elsewhere or sign to this org.
  - Snipe-averse: when considering a NEW target already led by another org,
    CPU skips candidates where the leader is well ahead. Existing targets
    aren't dropped even if competition arrives.

Budget rules:
  - Spend full 100 pts/week until org has 10 commitments (5 POS + 5 PIT).
  - Allocate weighted toward higher-rated targets, capped at 20/player.
"""

import logging
import random
from collections import defaultdict
from sqlalchemy import text

from services.org_constants import USHS_ORG_ID

log = logging.getLogger(__name__)


# CPU behavior tuning -----------------------------------------------------
_TARGET_POS = 5               # desired position player commits per season
_TARGET_PIT = 5               # desired pitcher commits per season
_BOARD_OVERSHOOT = 2          # carry 2 extra targets per bucket (roster churn buffer)
_MAX_PER_PLAYER = 20          # engine cap — mirrors recruiting_config
_WEEKLY_BUDGET = 100          # engine default — mirrors recruiting_config

# Star weights for weighted random pick (higher = picked more often).
# Heavier on 2-3 star to keep the bulk of classes realistic while still
# letting programs land the occasional blue-chip.
_STAR_PICK_WEIGHT = {
    5: 1.0,
    4: 3.0,
    3: 8.0,
    2: 10.0,
    1: 4.0,
}

# Point-distribution weight by star (how aggressively CPU spends on a target).
_STAR_SPEND_WEIGHT = {
    5: 5.0,
    4: 4.0,
    3: 3.0,
    2: 2.0,
    1: 1.5,
}

# Snipe aversion: when adding a NEW target (not already on board), skip if
# another org's prior-week total already exceeds this fraction of the star
# tier's base threshold. Existing targets don't trip this check.
_SNIPE_AVERSION_THRESHOLD = 0.50


def run_cpu_recruiting(conn, league_year_id, week, config):
    """
    Allocate weekly recruiting points for every CPU college org.

    Called by advance_recruiting_week BEFORE resolve_recruiting_week so
    writes land in the week that's about to resolve.

    Returns: {"orgs_acted": int, "points_spent": int, "targets_added": int}
    """
    cpu_orgs = _fetch_cpu_college_orgs(conn)
    if not cpu_orgs:
        return {"orgs_acted": 0, "points_spent": 0, "targets_added": 0}

    # Pool once (shared across all CPU orgs) ----------------------------
    uncommitted_pool = _fetch_uncommitted_pool(conn, league_year_id)
    if not uncommitted_pool:
        return {"orgs_acted": 0, "points_spent": 0, "targets_added": 0}

    # Current prior-week leader per player (for snipe aversion) ---------
    leader_map = _fetch_leader_map(conn, league_year_id, week)

    # Star thresholds for snipe-aversion math ---------------------------
    star_base = {
        s: float(config.get(f"star{s}_base", 20 * s))
        for s in range(1, 6)
    }

    orgs_acted = 0
    total_points = 0
    total_added = 0

    for org_id in cpu_orgs:
        # How many commitments does this org already have, split by ptype?
        commits = _fetch_org_commits_by_ptype(conn, org_id, league_year_id)
        pos_need = max(0, _TARGET_POS - commits.get("Position", 0))
        pit_need = max(0, _TARGET_PIT - commits.get("Pitcher", 0))

        if pos_need == 0 and pit_need == 0:
            continue  # full class — skip

        # Load current board + prune committed/signed-elsewhere ---------
        board = _load_and_prune_board(conn, org_id, league_year_id,
                                       uncommitted_pool)

        pos_on_board = sum(1 for pid in board
                            if uncommitted_pool[pid]["ptype"] != "Pitcher")
        pit_on_board = sum(1 for pid in board
                            if uncommitted_pool[pid]["ptype"] == "Pitcher")

        # Refill board up to (need + overshoot) per bucket --------------
        pos_want = pos_need + _BOARD_OVERSHOOT - pos_on_board
        pit_want = pit_need + _BOARD_OVERSHOOT - pit_on_board

        added = 0
        if pos_want > 0:
            added += _add_targets(
                conn, org_id, league_year_id, board,
                uncommitted_pool, leader_map, star_base,
                ptype="Position", count=pos_want,
            )
        if pit_want > 0:
            added += _add_targets(
                conn, org_id, league_year_id, board,
                uncommitted_pool, leader_map, star_base,
                ptype="Pitcher", count=pit_want,
            )
        total_added += added

        if not board:
            continue

        # Allocate weekly budget across board ---------------------------
        spent = _allocate_week_points(
            conn, org_id, league_year_id, week, board, uncommitted_pool
        )
        if spent > 0:
            orgs_acted += 1
            total_points += spent

    return {
        "orgs_acted": orgs_acted,
        "points_spent": total_points,
        "targets_added": total_added,
    }


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _fetch_cpu_college_orgs(conn):
    """IDs of all college orgs with coach='AI' (i.e. non-user-controlled)."""
    rows = conn.execute(
        text("""
            SELECT id FROM organizations
            WHERE league = 'college' AND coach = 'AI'
            ORDER BY id
        """)
    ).all()
    return [int(r[0]) for r in rows]


def _fetch_uncommitted_pool(conn, league_year_id):
    """
    All HS players not yet committed, with star rating + ptype.
    Returns: {player_id: {"ptype": "Position"|"Pitcher", "star": int}}
    """
    rows = conn.execute(
        text("""
            SELECT p.id, p.ptype, COALESCE(rr.star_rating, 1) AS star
            FROM simbbPlayers p
            JOIN contracts c
                ON c.playerID = p.id AND c.isActive = 1
            JOIN contractDetails cd
                ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts
                ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            LEFT JOIN recruiting_rankings rr
                ON rr.player_id = p.id AND rr.league_year_id = :ly
            WHERE cts.orgID = :ushs
              AND p.id NOT IN (
                  SELECT player_id FROM recruiting_commitments
                  WHERE league_year_id = :ly
              )
        """),
        {"ushs": USHS_ORG_ID, "ly": league_year_id},
    ).all()

    pool = {}
    for r in rows:
        pid = int(r[0])
        ptype = r[1] or "Position"
        # Normalize: anything not 'Pitcher' treated as Position bucket
        bucket = "Pitcher" if ptype == "Pitcher" else "Position"
        pool[pid] = {"ptype": bucket, "star": int(r[2])}
    return pool


def _fetch_leader_map(conn, league_year_id, current_week):
    """
    Per player, the leading org and their prior-week total.
    Used for snipe aversion when CPU picks NEW targets.
    Returns: {player_id: (leader_org_id, leader_points)}
    """
    rows = conn.execute(
        text("""
            SELECT player_id, org_id, SUM(points) AS pts
            FROM recruiting_investments
            WHERE league_year_id = :ly AND week < :week
            GROUP BY player_id, org_id
        """),
        {"ly": league_year_id, "week": current_week},
    ).all()

    # Pick the max-points org per player
    best = {}
    for r in rows:
        pid, oid, pts = int(r[0]), int(r[1]), float(r[2])
        cur = best.get(pid)
        if cur is None or pts > cur[1]:
            best[pid] = (oid, pts)
    return best


def _fetch_org_commits_by_ptype(conn, org_id, league_year_id):
    """Return {'Position': N, 'Pitcher': M} for this org's commitments."""
    rows = conn.execute(
        text("""
            SELECT p.ptype, COUNT(*) AS cnt
            FROM recruiting_commitments rc
            JOIN simbbPlayers p ON p.id = rc.player_id
            WHERE rc.org_id = :org AND rc.league_year_id = :ly
            GROUP BY p.ptype
        """),
        {"org": org_id, "ly": league_year_id},
    ).all()

    out = {"Position": 0, "Pitcher": 0}
    for r in rows:
        pt = r[0] or "Position"
        bucket = "Pitcher" if pt == "Pitcher" else "Position"
        out[bucket] += int(r[1])
    return out


def _load_and_prune_board(conn, org_id, league_year_id, uncommitted_pool):
    """
    Load recruiting_board for this org, drop entries that are no longer in
    the uncommitted pool (player committed somewhere), and return the
    pruned list of player_ids.
    """
    rows = conn.execute(
        text("""
            SELECT player_id FROM recruiting_board
            WHERE org_id = :org AND league_year_id = :ly
        """),
        {"org": org_id, "ly": league_year_id},
    ).all()

    keep = []
    stale = []
    for r in rows:
        pid = int(r[0])
        if pid in uncommitted_pool:
            keep.append(pid)
        else:
            stale.append(pid)

    if stale:
        ph = ", ".join(str(pid) for pid in stale)
        conn.execute(
            text(f"""
                DELETE FROM recruiting_board
                WHERE org_id = :org AND league_year_id = :ly
                  AND player_id IN ({ph})
            """),
            {"org": org_id, "ly": league_year_id},
        )
    return keep


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------

def _add_targets(conn, org_id, league_year_id, board, pool,
                  leader_map, star_base, ptype, count):
    """
    Weighted-random pick up to `count` players of `ptype` from pool,
    excluding ones already on board, skipping snipe-risk candidates,
    and insert them into recruiting_board. Mutates `board` in place.
    Returns number of targets actually added.
    """
    candidates = [
        pid for pid, info in pool.items()
        if info["ptype"] == ptype and pid not in board
    ]
    if not candidates:
        return 0

    # Filter out snipe-risk players for NEW additions
    safe = []
    for pid in candidates:
        star = pool[pid]["star"]
        lead = leader_map.get(pid)
        if lead is not None and lead[0] != org_id:
            threshold = star_base.get(star, 20)
            if lead[1] >= threshold * _SNIPE_AVERSION_THRESHOLD:
                continue
        safe.append(pid)

    # If aversion filter empties the pool, relax and use full candidate list
    picks_from = safe if safe else candidates

    weights = [_STAR_PICK_WEIGHT.get(pool[pid]["star"], 1.0)
               for pid in picks_from]

    added = 0
    for _ in range(count):
        if not picks_from:
            break
        idx = _weighted_index(weights)
        pid = picks_from.pop(idx)
        weights.pop(idx)

        conn.execute(
            text("""
                INSERT INTO recruiting_board (org_id, league_year_id, player_id)
                VALUES (:org, :ly, :pid)
            """),
            {"org": org_id, "ly": league_year_id, "pid": pid},
        )
        board.append(pid)
        added += 1
    return added


def _weighted_index(weights):
    """Pick an index from `weights` proportional to value."""
    total = sum(weights)
    if total <= 0:
        return random.randrange(len(weights))
    r = random.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return i
    return len(weights) - 1


# ---------------------------------------------------------------------------
# Weekly point allocation
# ---------------------------------------------------------------------------

def _allocate_week_points(conn, org_id, league_year_id, week, board, pool):
    """
    Distribute _WEEKLY_BUDGET across board targets, weighted by star.
    Respects _MAX_PER_PLAYER cap. Writes into recruiting_investments for
    `week` (UPSERT — replaces any existing row for this org+player+week).
    Returns total points written.
    """
    if not board:
        return 0

    # Base weights by star
    weighted = [
        (pid, _STAR_SPEND_WEIGHT.get(pool[pid]["star"], 1.0))
        for pid in board
    ]
    total_w = sum(w for _, w in weighted)
    if total_w <= 0:
        return 0

    # Initial allocation (float) — then round and redistribute remainders
    raw = [(pid, _WEEKLY_BUDGET * w / total_w) for pid, w in weighted]
    alloc = {pid: min(_MAX_PER_PLAYER, int(round(pts))) for pid, pts in raw}

    # Adjust to exactly _WEEKLY_BUDGET (accounts for rounding + caps)
    _rebalance(alloc, _WEEKLY_BUDGET, pool, board)

    total_written = 0
    for pid, pts in alloc.items():
        if pts <= 0:
            continue
        conn.execute(
            text("""
                INSERT INTO recruiting_investments
                    (org_id, player_id, league_year_id, week, points)
                VALUES (:org, :pid, :ly, :week, :pts)
                ON DUPLICATE KEY UPDATE points = VALUES(points)
            """),
            {"org": org_id, "pid": pid, "ly": league_year_id,
             "week": week, "pts": pts},
        )
        total_written += pts
    return total_written


def _rebalance(alloc, budget, pool, board):
    """
    After rounding, nudge allocations so sum == budget, respecting the
    per-player cap. Distributes deltas toward/away from higher-star
    targets first.
    """
    current = sum(alloc.values())
    delta = budget - current
    if delta == 0:
        return

    # Order by star desc so high-value targets absorb extras / give up least
    ordered = sorted(
        board,
        key=lambda pid: -_STAR_SPEND_WEIGHT.get(pool[pid]["star"], 1.0),
    )

    if delta > 0:
        # Distribute surplus to highest-weighted players with headroom
        i = 0
        guard = 0
        while delta > 0 and guard < 10000:
            pid = ordered[i % len(ordered)]
            if alloc[pid] < _MAX_PER_PLAYER:
                alloc[pid] += 1
                delta -= 1
            i += 1
            guard += 1
    else:
        # Trim overage from lowest-weighted players first
        deficit = -delta
        rev = list(reversed(ordered))
        i = 0
        guard = 0
        while deficit > 0 and guard < 10000:
            pid = rev[i % len(rev)]
            if alloc[pid] > 0:
                alloc[pid] -= 1
                deficit -= 1
            i += 1
            guard += 1
