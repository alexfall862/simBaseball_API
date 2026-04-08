"""
College recruiting system — weighted lottery.

Manages star rankings, weekly point investments, commitment resolution,
and fog-of-war interest gauges. All functions take a SQLAlchemy Core connection.
"""

import hashlib
import random
from sqlalchemy import text

from services.org_constants import (
    INTAM_ORG_ID, USHS_ORG_ID,
    is_college_org,
)

# Star distribution (cumulative upper bound from TOP -> star)
# Applied separately within position players and pitchers
# Top 1% -> 5 star, next 2% -> 4 star, next 7% -> 3 star,
# next 30% -> 2 star, bottom 60% -> 1 star
_STAR_THRESHOLDS = [
    (0.01, 5),
    (0.03, 4),   # 0.01 + 0.02
    (0.10, 3),   # 0.03 + 0.07
    (0.40, 2),   # 0.10 + 0.30
    (1.00, 1),   # 0.40 + 0.60
]

# Interest gauge buckets for fog-of-war
_INTEREST_BUCKETS = ["Low", "Medium", "High", "Very High"]

# Recruiting status progression — driven by total_interest / threshold ratio
_RECRUITING_STAGES = [
    (0.90, "May Sign this Week"),
    (0.70, "May Sign Soon"),
    (0.50, "Narrowing to Top 3"),
    (0.30, "Locking Down Top 5"),
    (0.10, "Listening to Offers"),
]

# Signing tendency threshold modifiers (applied to star_base)
_TENDENCY_MULT = {
    "Signs Very Early": 0.90,
    "Signs Early":      0.95,
    "Signs Normal":     1.00,
    "Signs Late":       1.05,
    "Signs Very Late":  1.10,
}


def _get_recruiting_stage(total_interest, threshold, committed_org_abbrev=None):
    """Derive recruiting status from interest/threshold ratio."""
    if committed_org_abbrev:
        return f"Signed to {committed_org_abbrev}"
    if total_interest <= 0:
        return "Open"
    if threshold <= 0:
        # Threshold fully decayed — any interest means imminent signing
        return "May Sign this Week"
    ratio = total_interest / threshold
    for cutoff, label in _RECRUITING_STAGES:
        if ratio >= cutoff:
            return label
    return "Open"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_recruiting_config(conn):
    """Read recruiting_config into a {key: value} dict."""
    rows = conn.execute(
        text("SELECT config_key, config_value FROM recruiting_config")
    ).all()
    return {r[0]: r[1] for r in rows}


def _cfg_int(config, key, fallback):
    return int(float(config.get(key, fallback)))


def _cfg_float(config, key, fallback):
    return float(config.get(key, fallback))


# ---------------------------------------------------------------------------
# Star rankings
# ---------------------------------------------------------------------------

def _assign_stars(scored_list):
    """
    Assign star ratings to a sorted (desc) list of (pid, ptype, composite).
    Uses _STAR_THRESHOLDS distribution applied within the group.
    Returns list of dicts with star assigned.
    """
    total = len(scored_list)
    result = []
    for idx, (pid, ptype, comp) in enumerate(scored_list):
        pct = idx / max(total, 1)  # 0 = best
        star = 1
        for upper_bound, s in _STAR_THRESHOLDS:
            if pct < upper_bound:
                star = s
                break
        result.append({
            "player_id": pid,
            "ptype": ptype,
            "composite": comp,
            "star": star,
        })
    return result


# Grade -> numeric value for pot bonus
_GRADE_VAL = {
    "A+": 6, "A": 5, "A-": 4,
    "B+": 3, "B": 2, "B-": 1,
    "C+": 0, "C": -1, "C-": -2,
    "D+": -3, "D": -4, "D-": -5,
    "F": -6,
}

# Position player attributes for composite scoring
_POS_BASE_ATTRS = [
    "contact_base", "power_base", "discipline_base",
    "eye_base", "speed_base", "baserunning_base",
    "throwpower_base", "throwacc_base",
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
]
_POS_POT_ATTRS = [
    "contact_pot", "power_pot", "discipline_pot",
    "eye_pot", "speed_pot",
]

# Pitcher attributes for composite scoring
_PIT_BASE_ATTRS = [
    "pendurance_base", "pgencontrol_base", "pthrowpower_base",
    "psequencing_base",
    "pitch1_pacc_base", "pitch1_pbrk_base",
    "pitch1_pcntrl_base", "pitch1_consist_base",
    "pitch2_pacc_base", "pitch2_pbrk_base",
    "pitch2_pcntrl_base", "pitch2_consist_base",
    "throwpower_base", "throwacc_base",
]
_PIT_POT_ATTRS = [
    "pendurance_pot", "pgencontrol_pot", "pthrowpower_pot",
    "psequencing_pot",
]


def _compute_composite(m, base_attrs, pot_attrs):
    """Compute composite score from base attributes + pot bonus."""
    base_sum = 0.0
    base_count = 0
    for key in base_attrs:
        val = m.get(key)
        if val is not None:
            try:
                base_sum += float(val)
                base_count += 1
            except (TypeError, ValueError):
                pass
    base_avg = base_sum / max(base_count, 1)

    pot_bonus = 0.0
    pot_count = 0
    for key in pot_attrs:
        g = m.get(key)
        if g and g in _GRADE_VAL:
            pot_bonus += _GRADE_VAL[g]
            pot_count += 1
    pot_avg = (pot_bonus / max(pot_count, 1)) * 2

    return base_avg + pot_avg


# ── Public aliases for cross-module reuse (IFA signing) ──────────────────
GRADE_VAL = _GRADE_VAL
POS_BASE_ATTRS = _POS_BASE_ATTRS
POS_POT_ATTRS = _POS_POT_ATTRS
PIT_BASE_ATTRS = _PIT_BASE_ATTRS
PIT_POT_ATTRS = _PIT_POT_ATTRS
compute_composite = _compute_composite
assign_stars = _assign_stars
STAR_THRESHOLDS = _STAR_THRESHOLDS


def compute_star_rankings(conn, league_year_id):
    """
    Compute composite scores for all HS players (org 340) and assign
    star ratings using separate distributions for position players
    and pitchers so each group has equal star representation.

    Distribution per group: 5-star 1%, 4-star 2%, 3-star 7%, 2-star 30%, 1-star 60%.

    Returns count of ranked players.
    """
    rows = conn.execute(
        text("""
            SELECT p.id, p.ptype,
                   p.contact_base, p.power_base, p.discipline_base,
                   p.eye_base, p.speed_base, p.baserunning_base,
                   p.throwpower_base, p.throwacc_base,
                   p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
                   p.pendurance_base, p.pgencontrol_base, p.pthrowpower_base,
                   p.psequencing_base,
                   p.pitch1_pacc_base, p.pitch1_pbrk_base,
                   p.pitch1_pcntrl_base, p.pitch1_consist_base,
                   p.pitch2_pacc_base, p.pitch2_pbrk_base,
                   p.pitch2_pcntrl_base, p.pitch2_consist_base,
                   p.contact_pot, p.power_pot, p.discipline_pot,
                   p.eye_pot, p.speed_pot,
                   p.pendurance_pot, p.pgencontrol_pot,
                   p.pthrowpower_pot, p.psequencing_pot
            FROM simbbPlayers p
            JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE cts.orgID = :ushs
        """),
        {"ushs": USHS_ORG_ID},
    ).all()

    if not rows:
        return 0

    # Split by ptype, score with ptype-appropriate attributes
    pos_scored = []
    pit_scored = []
    for r in rows:
        m = r._mapping
        ptype = m["ptype"] or "Position"
        if ptype == "Pitcher":
            comp = _compute_composite(m, _PIT_BASE_ATTRS, _PIT_POT_ATTRS)
            pit_scored.append((m["id"], ptype, comp))
        else:
            comp = _compute_composite(m, _POS_BASE_ATTRS, _POS_POT_ATTRS)
            pos_scored.append((m["id"], ptype, comp))

    # Sort each group by composite descending, assign stars independently
    pos_scored.sort(key=lambda x: x[2], reverse=True)
    pit_scored.sort(key=lambda x: x[2], reverse=True)

    pos_ranked = _assign_stars(pos_scored)
    pit_ranked = _assign_stars(pit_scored)

    # Merge and sort by composite for overall ranking
    all_ranked = pos_ranked + pit_ranked
    all_ranked.sort(key=lambda x: x["composite"], reverse=True)

    # Assign overall rank and ptype rank
    ptype_counters = {}
    for idx, r in enumerate(all_ranked):
        r["rank_overall"] = idx + 1
        pt = r["ptype"] or "Unknown"
        ptype_counters[pt] = ptype_counters.get(pt, 0) + 1
        r["rank_by_ptype"] = ptype_counters[pt]

    # Clear old rankings for this year and insert fresh
    conn.execute(
        text("DELETE FROM recruiting_rankings WHERE league_year_id = :ly"),
        {"ly": league_year_id},
    )

    # Batch INSERT rankings + batch UPDATE star ratings (executemany)
    if all_ranked:
        ranking_params = [{
            "pid": r["player_id"],
            "ly": league_year_id,
            "comp": round(r["composite"], 4),
            "star": r["star"],
            "rank": r["rank_overall"],
            "rpt": r["rank_by_ptype"],
        } for r in all_ranked]
        conn.execute(
            text("""
                INSERT INTO recruiting_rankings
                    (player_id, league_year_id, composite_score,
                     star_rating, rank_overall, rank_by_ptype)
                VALUES (:pid, :ly, :comp, :star, :rank, :rpt)
            """),
            ranking_params,
        )

        # Batch UPDATE star ratings using chunked CASE expressions
        # instead of one UPDATE per player (~44k individual statements).
        _CHUNK = 500
        for i in range(0, len(all_ranked), _CHUNK):
            chunk = all_ranked[i:i + _CHUNK]
            cases = " ".join(
                f"WHEN {r['player_id']} THEN {r['star']}" for r in chunk
            )
            pids = ",".join(str(r["player_id"]) for r in chunk)
            conn.execute(
                text(f"""
                    UPDATE simbbPlayers
                    SET recruit_stars = CASE id {cases} END
                    WHERE id IN ({pids})
                """)
            )

    return len(all_ranked)


def wipe_star_rankings(conn, league_year_id):
    """Delete all star rankings for a league year. Returns count deleted."""
    result = conn.execute(
        text("DELETE FROM recruiting_rankings WHERE league_year_id = :ly"),
        {"ly": league_year_id},
    )
    return result.rowcount


# ---------------------------------------------------------------------------
# Investment submission
# ---------------------------------------------------------------------------

def submit_weekly_investments(conn, org_id, league_year_id, week, investments):
    """
    Validate and record weekly recruiting point investments.

    investments: list of {"player_id": int, "points": int}

    Returns: {"accepted": [...], "errors": [...], "budget_remaining": int}
    """
    config = get_recruiting_config(conn)
    max_per_player = _cfg_int(config, "max_points_per_player_per_week", 20)
    weekly_budget = _cfg_int(config, "points_per_week", 100)

    # Validate org is a college org
    if not is_college_org(org_id):
        raise ValueError("Only college organizations can recruit")

    # Validate recruiting is active and correct week
    state = conn.execute(
        text("""
            SELECT current_week, status FROM recruiting_state
            WHERE league_year_id = :ly
        """),
        {"ly": league_year_id},
    ).first()

    if not state:
        raise ValueError("Recruiting has not been initialized for this year")
    if state[1] != "active":
        raise ValueError(f"Recruiting is not active (status: {state[1]})")
    if state[0] != week:
        raise ValueError(f"Current week is {state[0]}, not {week}")

    # Check total points this week for this org (already spent)
    existing_total = conn.execute(
        text("""
            SELECT COALESCE(SUM(points), 0)
            FROM recruiting_investments
            WHERE org_id = :org AND league_year_id = :ly AND week = :week
        """),
        {"org": org_id, "ly": league_year_id, "week": week},
    ).scalar()

    accepted = []
    errors = []
    points_used = existing_total

    for inv in investments:
        pid = inv["player_id"]
        pts = inv["points"]

        # Validate points
        if pts < 0:
            errors.append({"player_id": pid, "error": "Points cannot be negative"})
            continue
        if pts > max_per_player:
            errors.append({"player_id": pid, "error": f"Max {max_per_player} per player per week"})
            continue

        # Check existing investment this week for this player
        existing_inv = conn.execute(
            text("""
                SELECT points FROM recruiting_investments
                WHERE org_id = :org AND player_id = :pid
                  AND league_year_id = :ly AND week = :week
            """),
            {"org": org_id, "pid": pid, "ly": league_year_id, "week": week},
        ).first()

        # pts == 0 means remove this investment
        if pts == 0:
            if existing_inv:
                conn.execute(
                    text("""
                        DELETE FROM recruiting_investments
                        WHERE org_id = :org AND player_id = :pid
                          AND league_year_id = :ly AND week = :week
                    """),
                    {"org": org_id, "pid": pid,
                     "ly": league_year_id, "week": week},
                )
                points_used -= existing_inv[0]
            accepted.append({"player_id": pid, "points": 0})
            continue

        # Verify player is in HS pool and not committed
        player_check = conn.execute(
            text("""
                SELECT cts.orgID
                FROM contracts c
                JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
                JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
                WHERE c.playerID = :pid AND c.isActive = 1
                LIMIT 1
            """),
            {"pid": pid},
        ).first()

        if not player_check or player_check[0] != USHS_ORG_ID:
            errors.append({"player_id": pid, "error": "Player not in HS pool"})
            continue

        # Check not already committed
        committed = conn.execute(
            text("""
                SELECT id FROM recruiting_commitments
                WHERE player_id = :pid AND league_year_id = :ly
            """),
            {"pid": pid, "ly": league_year_id},
        ).first()

        if committed:
            errors.append({"player_id": pid, "error": "Player already committed"})
            continue

        if existing_inv:
            # Replace existing investment (adjust budget tracking)
            old_pts = existing_inv[0]
            net_change = pts - old_pts
            if points_used + net_change > weekly_budget:
                errors.append({"player_id": pid, "error": "Exceeds weekly budget"})
                continue

            conn.execute(
                text("""
                    UPDATE recruiting_investments
                    SET points = :pts
                    WHERE org_id = :org AND player_id = :pid
                      AND league_year_id = :ly AND week = :week
                """),
                {"pts": pts, "org": org_id, "pid": pid,
                 "ly": league_year_id, "week": week},
            )
            points_used += net_change
        else:
            # Check budget for new investment
            if points_used + pts > weekly_budget:
                errors.append({"player_id": pid, "error": "Exceeds weekly budget"})
                continue

            conn.execute(
                text("""
                    INSERT INTO recruiting_investments
                        (org_id, player_id, league_year_id, week, points)
                    VALUES (:org, :pid, :ly, :week, :pts)
                """),
                {"org": org_id, "pid": pid, "ly": league_year_id,
                 "week": week, "pts": pts},
            )
            points_used += pts

        accepted.append({"player_id": pid, "points": pts})

    return {
        "accepted": accepted,
        "errors": errors,
        "budget_remaining": weekly_budget - points_used,
    }


# ---------------------------------------------------------------------------
# Weekly resolution
# ---------------------------------------------------------------------------

def resolve_recruiting_week(conn, league_year_id, week, config=None):
    """
    Resolve one week of recruiting: check commitment thresholds,
    run weighted lottery for any that meet threshold.

    Returns: {"commitments": [...], "uncommitted_count": int}
    """
    if config is None:
        config = get_recruiting_config(conn)

    exponent = _cfg_float(config, "lottery_exponent", 1.3)
    snipe_pct = _cfg_float(config, "snipe_threshold_pct", 0.80)
    snipe_weeks = _cfg_int(config, "snipe_cooldown_weeks", 2)
    snipe_mult = _cfg_float(config, "snipe_threshold_mult", 1.3)

    # Star thresholds
    star_config = {}
    for s in range(1, 6):
        star_config[s] = {
            "base": _cfg_float(config, f"star{s}_base", 20 * s),
            "decay": _cfg_float(config, f"star{s}_decay", s),
        }

    # Get all uncommitted players with investments this year
    invested_players = conn.execute(
        text("""
            SELECT DISTINCT ri.player_id
            FROM recruiting_investments ri
            WHERE ri.league_year_id = :ly
              AND ri.player_id NOT IN (
                  SELECT player_id FROM recruiting_commitments
                  WHERE league_year_id = :ly
              )
        """),
        {"ly": league_year_id},
    ).all()

    # Batch-fetch signing_tendency for all invested players
    tendency_map = {}
    if invested_players:
        pids = [r[0] for r in invested_players]
        ph = ", ".join([f":t{i}" for i in range(len(pids))])
        tparams = {f"t{i}": pid for i, pid in enumerate(pids)}
        tend_rows = conn.execute(
            text(f"""
                SELECT id, signing_tendency FROM simbbPlayers
                WHERE id IN ({ph})
            """),
            tparams,
        ).all()
        tendency_map = {r[0]: r[1] for r in tend_rows}

    # Pre-fetch star ratings for all invested players (1 query vs N)
    star_map = {}
    if invested_players:
        pids = [r[0] for r in invested_players]
        ph = ", ".join([f":s{i}" for i in range(len(pids))])
        sparams = {f"s{i}": pid for i, pid in enumerate(pids)}
        sparams["ly"] = league_year_id
        star_rows = conn.execute(
            text(f"""
                SELECT player_id, star_rating FROM recruiting_rankings
                WHERE league_year_id = :ly AND player_id IN ({ph})
            """),
            sparams,
        ).all()
        star_map = {r[0]: r[1] for r in star_rows}

    # Pre-fetch all investment totals grouped by player+org (1 query vs N)
    from collections import defaultdict
    investments_by_player = defaultdict(list)
    if invested_players:
        pids = [r[0] for r in invested_players]
        ph = ", ".join([f":i{i}" for i in range(len(pids))])
        iparams = {f"i{i}": pid for i, pid in enumerate(pids)}
        iparams["ly"] = league_year_id
        inv_rows = conn.execute(
            text(f"""
                SELECT player_id, org_id, SUM(points) AS total_pts,
                       MIN(week) AS first_week
                FROM recruiting_investments
                WHERE league_year_id = :ly AND player_id IN ({ph})
                GROUP BY player_id, org_id
                ORDER BY player_id, total_pts DESC
            """),
            iparams,
        ).all()
        for r in inv_rows:
            investments_by_player[r[0]].append((r[1], r[2], r[3]))

    commitments = []
    uncommitted_count = 0

    for (player_id,) in invested_players:
        star = star_map.get(player_id, 1)
        sc = star_config.get(star, star_config[1])

        # Apply signing tendency modifier to base threshold
        tendency = tendency_map.get(player_id, "Signs Normal")
        modified_base = sc["base"] * _TENDENCY_MULT.get(tendency, 1.0)
        threshold = max(modified_base - (week * sc["decay"]), 0)

        # Use pre-fetched investments
        org_totals = investments_by_player.get(player_id, [])

        if not org_totals:
            continue

        total_interest = float(sum(r[1] for r in org_totals))
        leader_pts = float(org_totals[0][1])

        # Anti-snipe check
        snipe_active = False
        for r in org_totals:
            oid, pts, first_wk = r[0], float(r[1]), r[2]
            if oid == org_totals[0][0]:
                continue  # skip leader
            if pts >= snipe_pct * leader_pts:
                # Check if this org only started investing recently
                if first_wk > (week - snipe_weeks):
                    snipe_active = True
                    break

        if snipe_active:
            threshold *= snipe_mult

        # Check if threshold met
        if total_interest >= threshold:
            # Run weighted lottery
            weights = []
            for r in org_totals:
                oid, pts = r[0], r[1]
                weights.append((oid, pts ** exponent))

            winner_org = _weighted_lottery(weights)

            # Find winner's total points
            winner_pts = 0
            for r in org_totals:
                if r[0] == winner_org:
                    winner_pts = r[1]
                    break

            conn.execute(
                text("""
                    INSERT INTO recruiting_commitments
                        (player_id, org_id, league_year_id,
                         week_committed, points_total, star_rating)
                    VALUES (:pid, :org, :ly, :week, :pts, :star)
                """),
                {
                    "pid": player_id, "org": winner_org,
                    "ly": league_year_id, "week": week,
                    "pts": winner_pts, "star": star,
                },
            )
            commitments.append({
                "player_id": player_id,
                "org_id": winner_org,
                "week": week,
                "points_total": winner_pts,
                "star_rating": star,
            })
        else:
            uncommitted_count += 1

    return {
        "commitments": commitments,
        "uncommitted_count": uncommitted_count,
    }


def resolve_week_20_cleanup(conn, league_year_id, config=None):
    """
    Week 20 cleanup: all remaining players with ANY investment
    commit to their point leader. Uninvested players are leftovers.

    Returns: {"commitments": [...], "leftovers": int}
    """
    # Get all uncommitted invested players
    remaining = conn.execute(
        text("""
            SELECT DISTINCT ri.player_id
            FROM recruiting_investments ri
            WHERE ri.league_year_id = :ly
              AND ri.player_id NOT IN (
                  SELECT player_id FROM recruiting_commitments
                  WHERE league_year_id = :ly
              )
        """),
        {"ly": league_year_id},
    ).all()

    commitments = []
    for (player_id,) in remaining:
        # Find point leader
        leader = conn.execute(
            text("""
                SELECT org_id, SUM(points) AS total_pts
                FROM recruiting_investments
                WHERE player_id = :pid AND league_year_id = :ly
                GROUP BY org_id
                ORDER BY total_pts DESC
                LIMIT 1
            """),
            {"pid": player_id, "ly": league_year_id},
        ).first()

        if not leader:
            continue

        # Get star rating
        star_row = conn.execute(
            text("""
                SELECT star_rating FROM recruiting_rankings
                WHERE player_id = :pid AND league_year_id = :ly
            """),
            {"pid": player_id, "ly": league_year_id},
        ).first()
        star = star_row[0] if star_row else 1

        conn.execute(
            text("""
                INSERT INTO recruiting_commitments
                    (player_id, org_id, league_year_id,
                     week_committed, points_total, star_rating)
                VALUES (:pid, :org, :ly, 20, :pts, :star)
            """),
            {
                "pid": player_id, "org": leader[0],
                "ly": league_year_id, "pts": leader[1],
                "star": star,
            },
        )
        commitments.append({
            "player_id": player_id,
            "org_id": leader[0],
            "week": 20,
            "points_total": leader[1],
            "star_rating": star,
        })

    # Count leftovers (HS players with no investment at all)
    leftover_count = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM simbbPlayers p
            JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE cts.orgID = :ushs
              AND p.id NOT IN (
                  SELECT player_id FROM recruiting_commitments
                  WHERE league_year_id = :ly
              )
        """),
        {"ushs": USHS_ORG_ID, "ly": league_year_id},
    ).scalar()

    return {
        "commitments": commitments,
        "leftovers": leftover_count or 0,
    }


# ---------------------------------------------------------------------------
# Week advancement orchestrator
# ---------------------------------------------------------------------------

def advance_recruiting_week(conn, league_year_id):
    """
    Advance recruiting by one week.

    - Week 0 -> 1: compute star rankings, set status='active'
    - Week 1-19: resolve completed week's commitments
    - Week 20: resolve + cleanup (remaining go to leader)
    - Week > 20: set status='complete'

    Returns summary dict.
    """
    config = get_recruiting_config(conn)
    total_weeks = _cfg_int(config, "recruiting_weeks", 20)

    # Get or create recruiting state
    state = conn.execute(
        text("""
            SELECT current_week, status FROM recruiting_state
            WHERE league_year_id = :ly
        """),
        {"ly": league_year_id},
    ).first()

    if not state:
        conn.execute(
            text("""
                INSERT INTO recruiting_state (league_year_id, current_week, status)
                VALUES (:ly, 0, 'pending')
            """),
            {"ly": league_year_id},
        )
        current_week = 0
        status = "pending"
    else:
        current_week = state[0]
        status = state[1]

    if status == "complete":
        return {"status": "complete", "message": "Recruiting already complete"}

    new_week = current_week + 1
    result = {"previous_week": current_week, "new_week": new_week}

    if current_week == 0:
        # Initialize: compute star rankings
        ranked_count = compute_star_rankings(conn, league_year_id)
        result["ranked_players"] = ranked_count

        conn.execute(
            text("""
                UPDATE recruiting_state
                SET current_week = 1, status = 'active'
                WHERE league_year_id = :ly
            """),
            {"ly": league_year_id},
        )
        result["status"] = "active"
        result["new_week"] = 1
        return result

    # Resolve the just-completed week
    week_result = resolve_recruiting_week(
        conn, league_year_id, current_week, config
    )
    result["commitments"] = week_result["commitments"]
    result["uncommitted_count"] = week_result["uncommitted_count"]

    if current_week >= total_weeks:
        # Week 20 cleanup
        cleanup = resolve_week_20_cleanup(conn, league_year_id, config)
        result["cleanup_commitments"] = cleanup["commitments"]
        result["leftovers"] = cleanup["leftovers"]

        conn.execute(
            text("""
                UPDATE recruiting_state
                SET current_week = :week, status = 'complete'
                WHERE league_year_id = :ly
            """),
            {"week": new_week, "ly": league_year_id},
        )
        result["status"] = "complete"
    else:
        conn.execute(
            text("""
                UPDATE recruiting_state
                SET current_week = :week
                WHERE league_year_id = :ly
            """),
            {"week": new_week, "ly": league_year_id},
        )
        result["status"] = "active"

    return result


# ---------------------------------------------------------------------------
# Player recruiting status (fog-of-war)
# ---------------------------------------------------------------------------

def get_player_recruiting_status(conn, player_id, league_year_id,
                                  viewing_org_id=None):
    """
    Get recruiting status for a player with fog-of-war.

    Returns: {
        star_rating, rank_overall, rank_by_ptype, ptype,
        status (activity-based progression label),
        commitment (if committed): {org_id, week, org_name},
        interest_gauge (fuzzed per viewing_org),
        competitor_team_ids,
        your_investment (if viewing_org_id provided),
    }
    """
    # Fetch current week + config for status computation
    state_row = conn.execute(
        text("SELECT current_week FROM recruiting_state WHERE league_year_id = :ly"),
        {"ly": league_year_id},
    ).first()
    current_week = state_row[0] if state_row else 0

    config = get_recruiting_config(conn)
    star_cfg = {}
    for s in range(1, 6):
        star_cfg[s] = {
            "base": _cfg_float(config, f"star{s}_base", 20 * s),
            "decay": _cfg_float(config, f"star{s}_decay", s),
        }

    # Star ranking + signing_tendency
    ranking = conn.execute(
        text("""
            SELECT rr.star_rating, rr.rank_overall, rr.rank_by_ptype,
                   rr.composite_score, p.ptype, p.firstname, p.lastname,
                   p.signing_tendency
            FROM recruiting_rankings rr
            JOIN simbbPlayers p ON p.id = rr.player_id
            WHERE rr.player_id = :pid AND rr.league_year_id = :ly
        """),
        {"pid": player_id, "ly": league_year_id},
    ).first()

    signing_tendency = "Signs Normal"
    if not ranking:
        # Fall back to base player info when rankings haven't been generated
        player = conn.execute(
            text("""
                SELECT id, firstname, lastname, ptype, signing_tendency
                FROM simbbPlayers WHERE id = :pid
            """),
            {"pid": player_id},
        ).first()
        if not player:
            return None
        pm = player._mapping
        signing_tendency = pm.get("signing_tendency", "Signs Normal")
        result = {
            "player_id": player_id,
            "player_name": f"{pm['firstname']} {pm['lastname']}",
            "ptype": pm["ptype"],
            "star_rating": None,
            "rank_overall": None,
            "rank_by_ptype": None,
        }
    else:
        m = ranking._mapping
        signing_tendency = m.get("signing_tendency", "Signs Normal")
        result = {
            "player_id": player_id,
            "player_name": f"{m['firstname']} {m['lastname']}",
            "ptype": m["ptype"],
            "star_rating": m["star_rating"],
            "rank_overall": m["rank_overall"],
            "rank_by_ptype": m["rank_by_ptype"],
        }

    # Commitment status
    commitment = conn.execute(
        text("""
            SELECT rc.org_id, rc.week_committed, rc.points_total,
                   o.org_abbrev AS org_abbrev
            FROM recruiting_commitments rc
            JOIN organizations o ON o.id = rc.org_id
            WHERE rc.player_id = :pid AND rc.league_year_id = :ly
        """),
        {"pid": player_id, "ly": league_year_id},
    ).first()

    # Competitor team IDs and total interest
    org_investments = conn.execute(
        text("""
            SELECT ri.org_id, t.id AS team_id, SUM(ri.points) AS total_pts
            FROM recruiting_investments ri
            JOIN teams t ON t.orgID = ri.org_id AND t.team_level = 3
            WHERE ri.player_id = :pid AND ri.league_year_id = :ly
            GROUP BY ri.org_id, t.id
        """),
        {"pid": player_id, "ly": league_year_id},
    ).all()

    total_interest = sum(float(r[2]) for r in org_investments)

    # Filter to orgs with >50% of leader's points
    if org_investments:
        max_pts = max(float(r[2]) for r in org_investments)
        half = max_pts * 0.50
        result["competitor_team_ids"] = [
            int(r[1]) for r in org_investments
            if r[0] != viewing_org_id and float(r[2]) >= half
        ]
    else:
        result["competitor_team_ids"] = []

    # Status: signed or activity-based progression
    if commitment:
        cm = commitment._mapping
        result["status"] = f"Signed to {cm['org_abbrev']}"
        result["commitment"] = {
            "org_id": cm["org_id"],
            "org_abbrev": cm["org_abbrev"],
            "week_committed": cm["week_committed"],
            "points_total": cm["points_total"],
        }
    else:
        star = result["star_rating"] or 1
        sc = star_cfg.get(star, star_cfg[1])
        modified_base = sc["base"] * _TENDENCY_MULT.get(signing_tendency, 1.0)
        threshold = max(modified_base - (current_week * sc["decay"]), 0)
        result["status"] = _get_recruiting_stage(total_interest, threshold)

    # Interest gauge (fuzzed per viewing org)
    result["interest_gauge"] = _fuzz_interest_gauge(
        total_interest, viewing_org_id, player_id
    )

    # Viewing org's own investment
    if viewing_org_id is not None:
        own_pts = conn.execute(
            text("""
                SELECT COALESCE(SUM(points), 0)
                FROM recruiting_investments
                WHERE org_id = :org AND player_id = :pid
                  AND league_year_id = :ly
            """),
            {"org": viewing_org_id, "pid": player_id, "ly": league_year_id},
        ).scalar()
        result["your_investment"] = own_pts

    return result


# ---------------------------------------------------------------------------
# Org recruiting board
# ---------------------------------------------------------------------------

def get_org_recruiting_board(conn, org_id, league_year_id):
    """
    Get an org's full recruiting board: all players on the explicit board
    OR invested in, with cumulative points, star rating, and fuzzed
    interest gauges. Status reflects per-player activity progression.
    """
    # Fetch current week + config for status computation
    state_row = conn.execute(
        text("SELECT current_week FROM recruiting_state WHERE league_year_id = :ly"),
        {"ly": league_year_id},
    ).first()
    current_week = state_row[0] if state_row else 0

    config = get_recruiting_config(conn)
    star_config = {}
    for s in range(1, 6):
        star_config[s] = {
            "base": _cfg_float(config, f"star{s}_base", 20 * s),
            "decay": _cfg_float(config, f"star{s}_decay", s),
        }

    # Players explicitly added to the recruiting_board table
    board_rows = conn.execute(
        text("""
            SELECT player_id FROM recruiting_board
            WHERE org_id = :org AND league_year_id = :ly
        """),
        {"org": org_id, "ly": league_year_id},
    ).all()
    board_pids = {r[0] for r in board_rows}

    # Players this org has invested in
    invested = conn.execute(
        text("""
            SELECT ri.player_id, SUM(ri.points) AS your_points
            FROM recruiting_investments ri
            WHERE ri.org_id = :org AND ri.league_year_id = :ly
            GROUP BY ri.player_id
        """),
        {"org": org_id, "ly": league_year_id},
    ).all()
    your_points = {r[0]: int(r[1]) for r in invested}

    # Merge both sources
    player_ids = list(board_pids | set(your_points.keys()))

    if not player_ids:
        return []

    # Batch fetch rankings
    placeholders = ", ".join([f":p{i}" for i in range(len(player_ids))])
    params = {"ly": league_year_id}
    params.update({f"p{i}": pid for i, pid in enumerate(player_ids)})

    rankings = conn.execute(
        text(f"""
            SELECT rr.player_id, rr.star_rating, rr.rank_overall,
                   p.firstname, p.lastname, p.ptype
            FROM recruiting_rankings rr
            JOIN simbbPlayers p ON p.id = rr.player_id
            WHERE rr.league_year_id = :ly
              AND rr.player_id IN ({placeholders})
        """),
        params,
    ).all()
    rank_map = {r[0]: r._mapping for r in rankings}

    # Also fetch basic player info + signing_tendency for all board players
    player_info = conn.execute(
        text(f"""
            SELECT id, firstname, lastname, ptype, signing_tendency
            FROM simbbPlayers
            WHERE id IN ({placeholders})
        """),
        params,
    ).all()
    player_info_map = {r[0]: r._mapping for r in player_info}

    # Batch fetch commitments
    commitments = conn.execute(
        text(f"""
            SELECT rc.player_id, rc.org_id, rc.week_committed,
                   o.org_abbrev AS org_abbrev
            FROM recruiting_commitments rc
            JOIN organizations o ON o.id = rc.org_id
            WHERE rc.league_year_id = :ly
              AND rc.player_id IN ({placeholders})
        """),
        params,
    ).all()
    commit_map = {r[0]: r._mapping for r in commitments}

    # Batch fetch per-org investment totals with team IDs for competitor logos
    interest_rows = conn.execute(
        text(f"""
            SELECT ri.player_id, ri.org_id, t.id AS team_id,
                   SUM(ri.points) AS total_pts
            FROM recruiting_investments ri
            JOIN teams t ON t.orgID = ri.org_id AND t.team_level = 3
            WHERE ri.league_year_id = :ly
              AND ri.player_id IN ({placeholders})
            GROUP BY ri.player_id, ri.org_id, t.id
        """),
        params,
    ).all()
    # per_player_orgs: {player_id: [(org_id, team_id, total_pts), ...]}
    per_player_orgs = {}
    for r in interest_rows:
        per_player_orgs.setdefault(r[0], []).append(
            (int(r[1]), int(r[2]), int(r[3]))
        )

    board = []
    for pid in player_ids:
        rm = rank_map.get(pid)
        pi = player_info_map.get(pid)
        if not rm and not pi:
            continue

        if rm:
            entry = {
                "player_id": pid,
                "player_name": f"{rm['firstname']} {rm['lastname']}",
                "ptype": rm["ptype"],
                "star_rating": rm["star_rating"],
                "rank_overall": rm["rank_overall"],
                "your_points": your_points.get(pid, 0),
            }
        else:
            # Board player without rankings yet
            entry = {
                "player_id": pid,
                "player_name": f"{pi['firstname']} {pi['lastname']}",
                "ptype": pi["ptype"],
                "star_rating": None,
                "rank_overall": None,
                "your_points": your_points.get(pid, 0),
            }

        entry["on_board"] = pid in board_pids

        # Interest gauge (fuzzed) + competitor team IDs (>50% of leader)
        org_pts_list = per_player_orgs.get(pid, [])
        total_pts = sum(pts for _, _, pts in org_pts_list)
        entry["interest_gauge"] = _fuzz_interest_gauge(
            total_pts, org_id, pid
        )
        if org_pts_list:
            max_pts = max(pts for _, _, pts in org_pts_list)
            half = max_pts * 0.50
            entry["competitor_team_ids"] = [
                tid for oid, tid, pts in org_pts_list
                if oid != org_id and pts >= half
            ]
        else:
            entry["competitor_team_ids"] = []

        # Status: activity-based progression or signed
        cm = commit_map.get(pid)
        if cm:
            entry["status"] = f"Signed to {cm['org_abbrev']}"
            entry["committed_to"] = {
                "org_id": cm["org_id"],
                "org_abbrev": cm["org_abbrev"],
                "week_committed": cm["week_committed"],
            }
        else:
            # Compute threshold for this player's star tier + tendency
            star = entry["star_rating"] or 1
            sc = star_config.get(star, star_config[1])
            pi_info = player_info_map.get(pid)
            tendency = (pi_info["signing_tendency"]
                        if pi_info and "signing_tendency" in pi_info.keys()
                        else "Signs Normal")
            modified_base = sc["base"] * _TENDENCY_MULT.get(tendency, 1.0)
            threshold = max(modified_base - (current_week * sc["decay"]), 0)
            entry["status"] = _get_recruiting_stage(total_pts, threshold)
            entry["committed_to"] = None

        board.append(entry)

    # Sort: non-signed first (by star desc), then signed
    board.sort(key=lambda x: (
        0 if not x["status"].startswith("Signed") else 1,
        -(x["star_rating"] or 0),
        x["rank_overall"] or 999999,
    ))

    return board


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fuzz_seed(org_id, player_id, key):
    """Deterministic hash for fog-of-war fuzzing."""
    raw = f"{org_id}:{player_id}:{key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def _fuzz_interest_gauge(total_interest, org_id, player_id):
    """
    Convert total interest into a fuzzed bucket label.

    True buckets based on total interest:
      0-49: Low, 50-149: Medium, 150-299: High, 300+: Very High

    Then shift ±1 tier per org for fog-of-war.
    """
    if total_interest < 50:
        true_idx = 0
    elif total_interest < 150:
        true_idx = 1
    elif total_interest < 300:
        true_idx = 2
    else:
        true_idx = 3

    if org_id is None:
        return _INTEREST_BUCKETS[true_idx]

    seed = _fuzz_seed(org_id, player_id, "interest")
    direction = 1 if (seed % 2 == 0) else -1
    fuzzed_idx = true_idx + direction
    fuzzed_idx = max(0, min(len(_INTEREST_BUCKETS) - 1, fuzzed_idx))
    return _INTEREST_BUCKETS[fuzzed_idx]


def _weighted_lottery(weights):
    """
    Given list of (org_id, weight), pick a winner via weighted random draw.
    """
    total = sum(w for _, w in weights)
    if total <= 0:
        return weights[0][0] if weights else None

    r = random.random() * total
    cumulative = 0.0
    for org_id, w in weights:
        cumulative += w
        if r <= cumulative:
            return org_id

    # Fallback (shouldn't reach here)
    return weights[-1][0]


# ---------------------------------------------------------------------------
# Board management
# ---------------------------------------------------------------------------

def add_to_recruiting_board(conn, org_id, league_year_id, player_id):
    """
    Add a player to an org's recruiting board.
    Returns "added" or "already_on_board".
    """
    existing = conn.execute(
        text("""
            SELECT id FROM recruiting_board
            WHERE org_id = :org AND league_year_id = :ly AND player_id = :pid
        """),
        {"org": org_id, "ly": league_year_id, "pid": player_id},
    ).first()

    if existing:
        return "already_on_board"

    conn.execute(
        text("""
            INSERT INTO recruiting_board (org_id, league_year_id, player_id)
            VALUES (:org, :ly, :pid)
        """),
        {"org": org_id, "ly": league_year_id, "pid": player_id},
    )
    return "added"


def remove_from_recruiting_board(conn, org_id, league_year_id, player_id):
    """
    Remove a player from an org's recruiting board.
    Returns "removed" or "not_on_board".
    """
    result = conn.execute(
        text("""
            DELETE FROM recruiting_board
            WHERE org_id = :org AND league_year_id = :ly AND player_id = :pid
        """),
        {"org": org_id, "ly": league_year_id, "pid": player_id},
    )
    return "removed" if result.rowcount > 0 else "not_on_board"


def get_recruiting_board_ids(conn, org_id, league_year_id):
    """Return set of player_ids on an org's recruiting board."""
    rows = conn.execute(
        text("""
            SELECT player_id FROM recruiting_board
            WHERE org_id = :org AND league_year_id = :ly
        """),
        {"org": org_id, "ly": league_year_id},
    ).all()
    return {r[0] for r in rows}
