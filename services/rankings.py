# services/rankings.py
"""
Team ranking systems: ELO, RPI, Pythagorean W-L, and Power Rankings.
All computed on-the-fly from game_results and player stats — no persistent tables.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_season_id(conn, league_year_id: int) -> int:
    """league_year_id -> league_years.league_year -> seasons.year -> seasons.id"""
    row = conn.execute(
        sa_text("SELECT league_year FROM league_years WHERE id = :id"),
        {"id": league_year_id},
    ).first()
    if not row:
        raise ValueError(f"league_year_id {league_year_id} not found")
    year = row[0]
    row2 = conn.execute(
        sa_text("SELECT id FROM seasons WHERE year = :yr"),
        {"yr": year},
    ).first()
    if not row2:
        raise ValueError(f"No season row for year {year}")
    return row2[0]


def _load_game_results(conn, season_id: int, league_level: int) -> List[dict]:
    """Load all regular-season game results for a season+level, chronologically."""
    rows = conn.execute(sa_text("""
        SELECT gr.game_id, gr.season_week, gr.season_subweek,
               gr.home_team_id, gr.away_team_id,
               gr.home_score, gr.away_score,
               gr.winning_team_id, gr.losing_team_id,
               gr.game_outcome
        FROM game_results gr
        WHERE gr.season = :sid
          AND gr.league_level = :level
          AND gr.game_type = 'regular'
          AND gr.game_outcome IN ('HOME_WIN', 'AWAY_WIN')
        ORDER BY gr.season_week ASC, gr.season_subweek ASC, gr.game_id ASC
    """), {"sid": season_id, "level": league_level}).all()

    return [
        {
            "game_id": int(r[0]), "season_week": int(r[1]), "season_subweek": r[2],
            "home_team_id": int(r[3]), "away_team_id": int(r[4]),
            "home_score": int(r[5] or 0), "away_score": int(r[6] or 0),
            "winning_team_id": int(r[7]) if r[7] else None,
            "losing_team_id": int(r[8]) if r[8] else None,
            "game_outcome": r[9],
        }
        for r in rows
    ]


def _load_teams_at_level(conn, league_level: int) -> Dict[int, dict]:
    """Load all teams at a given level.  Returns {team_id: {...}}."""
    rows = conn.execute(sa_text("""
        SELECT id, orgID, team_abbrev, team_level, conference, division,
               color_one, color_two
        FROM teams
        WHERE team_level = :level
    """), {"level": league_level}).all()
    return {
        int(r[0]): {
            "team_id": int(r[0]), "org_id": int(r[1]), "team_abbrev": r[2],
            "team_level": int(r[3]), "conference": r[4], "division": r[5],
            "color_one": r[6], "color_two": r[7],
        }
        for r in rows
    }


def _normalize_values(values: Dict[int, float]) -> Dict[int, float]:
    """Normalize a {key: value} dict to 0-100 scale.  All-same -> 50."""
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi - lo < 1e-9:
        return {k: 50.0 for k in values}
    return {k: (v - lo) / (hi - lo) * 100.0 for k, v in values.items()}


# ---------------------------------------------------------------------------
# 1. ELO Ratings
# ---------------------------------------------------------------------------

def compute_elo_ratings(
    conn,
    league_year_id: int,
    league_level: int,
    k_factor: int = 32,
) -> Dict[str, Any]:
    """Compute ELO ratings by replaying all regular-season games."""
    k_factor = max(10, min(64, k_factor))
    season_id = _resolve_season_id(conn, league_year_id)
    games = _load_game_results(conn, season_id, league_level)
    teams_map = _load_teams_at_level(conn, league_level)

    # Init ELO at 1500 for all teams
    elo: Dict[int, float] = {tid: 1500.0 for tid in teams_map}
    wins: Dict[int, int] = {tid: 0 for tid in teams_map}
    losses: Dict[int, int] = {tid: 0 for tid in teams_map}

    # Track weekly snapshots for chart
    history: Dict[int, List[dict]] = {tid: [] for tid in teams_map}
    last_week = None

    def _snapshot_week(week):
        for tid in teams_map:
            history[tid].append({"week": week, "elo": round(elo.get(tid, 1500.0), 1)})

    for g in games:
        # Snapshot at start of each new week
        if g["season_week"] != last_week:
            if last_week is not None:
                _snapshot_week(last_week)
            last_week = g["season_week"]

        home = g["home_team_id"]
        away = g["away_team_id"]
        if home not in elo:
            elo[home] = 1500.0
        if away not in elo:
            elo[away] = 1500.0

        # Expected scores
        e_home = 1.0 / (1.0 + 10.0 ** ((elo[away] - elo[home]) / 400.0))
        e_away = 1.0 - e_home

        # Actual scores
        if g["winning_team_id"] == home:
            s_home, s_away = 1.0, 0.0
            wins.setdefault(home, 0)
            losses.setdefault(away, 0)
            wins[home] = wins.get(home, 0) + 1
            losses[away] = losses.get(away, 0) + 1
        else:
            s_home, s_away = 0.0, 1.0
            wins.setdefault(away, 0)
            losses.setdefault(home, 0)
            wins[away] = wins.get(away, 0) + 1
            losses[home] = losses.get(home, 0) + 1

        elo[home] += k_factor * (s_home - e_home)
        elo[away] += k_factor * (s_away - e_away)

    # Final snapshot
    if last_week is not None:
        _snapshot_week(last_week)

    # Compute trend (change over last 2 weeks)
    trends: Dict[int, float] = {}
    for tid, hist in history.items():
        if len(hist) >= 3:
            trends[tid] = round(hist[-1]["elo"] - hist[-3]["elo"], 1)
        elif len(hist) >= 2:
            trends[tid] = round(hist[-1]["elo"] - hist[-2]["elo"], 1)
        else:
            trends[tid] = 0.0

    # Build ranked team list
    team_list = []
    for tid, info in teams_map.items():
        w = wins.get(tid, 0)
        l = losses.get(tid, 0)
        gp = w + l
        team_list.append({
            **info,
            "elo": round(elo.get(tid, 1500.0), 1),
            "wins": w,
            "losses": l,
            "games_played": gp,
            "win_pct": round(w / gp, 3) if gp > 0 else 0.0,
            "trend": trends.get(tid, 0.0),
        })
    team_list.sort(key=lambda t: t["elo"], reverse=True)
    for i, t in enumerate(team_list):
        t["rank"] = i + 1

    return {
        "teams": team_list,
        "history": {str(tid): hist for tid, hist in history.items()},
        "k_factor": k_factor,
        "level": league_level,
    }


# ---------------------------------------------------------------------------
# 2. RPI (Rating Percentage Index)
# ---------------------------------------------------------------------------

def compute_rpi(
    conn,
    league_year_id: int,
    league_level: int,
) -> Dict[str, Any]:
    """Compute RPI with standard 25/50/25 weighting."""
    season_id = _resolve_season_id(conn, league_year_id)
    games = _load_game_results(conn, season_id, league_level)
    teams_map = _load_teams_at_level(conn, league_level)

    # Build per-team records and opponent lists
    team_wins: Dict[int, int] = {tid: 0 for tid in teams_map}
    team_losses: Dict[int, int] = {tid: 0 for tid in teams_map}
    # opponent_results[tid] = list of (opponent_id, did_this_team_win)
    opponent_results: Dict[int, List[Tuple[int, bool]]] = {tid: [] for tid in teams_map}

    for g in games:
        home, away = g["home_team_id"], g["away_team_id"]
        winner = g["winning_team_id"]
        for tid in (home, away):
            if tid not in team_wins:
                team_wins[tid] = 0
                team_losses[tid] = 0
                opponent_results[tid] = []

        if winner == home:
            team_wins[home] += 1
            team_losses[away] += 1
            opponent_results[home].append((away, True))
            opponent_results[away].append((home, False))
        else:
            team_wins[away] += 1
            team_losses[home] += 1
            opponent_results[away].append((home, True))
            opponent_results[home].append((away, False))

    # Win percentage
    def _wp(tid):
        w, l = team_wins.get(tid, 0), team_losses.get(tid, 0)
        return w / (w + l) if (w + l) > 0 else 0.0

    # OWP: avg opponent win% excluding games against this team
    def _owp(tid):
        opps = opponent_results.get(tid, [])
        if not opps:
            return 0.0
        owp_vals = []
        for opp_id, _ in opps:
            # Opponent record excluding games vs tid
            ow = sum(1 for oid, won in opponent_results.get(opp_id, []) if oid != tid and won)
            ol = sum(1 for oid, won in opponent_results.get(opp_id, []) if oid != tid and not won)
            owp_vals.append(ow / (ow + ol) if (ow + ol) > 0 else 0.0)
        return sum(owp_vals) / len(owp_vals)

    # OOWP: avg of opponents' OWP
    owp_cache: Dict[int, float] = {}
    for tid in teams_map:
        owp_cache[tid] = _owp(tid)

    def _oowp(tid):
        opps = opponent_results.get(tid, [])
        if not opps:
            return 0.0
        seen_opps = []
        for opp_id, _ in opps:
            seen_opps.append(owp_cache.get(opp_id, 0.0))
        return sum(seen_opps) / len(seen_opps) if seen_opps else 0.0

    team_list = []
    for tid, info in teams_map.items():
        wp = _wp(tid)
        owp = owp_cache[tid]
        oowp = _oowp(tid)
        rpi = 0.25 * wp + 0.50 * owp + 0.25 * oowp
        w = team_wins.get(tid, 0)
        l = team_losses.get(tid, 0)
        team_list.append({
            **info,
            "rpi": round(rpi, 4),
            "wp": round(wp, 4),
            "owp": round(owp, 4),
            "oowp": round(oowp, 4),
            "sos": round(owp, 4),
            "wins": w,
            "losses": l,
            "games_played": w + l,
        })
    team_list.sort(key=lambda t: t["rpi"], reverse=True)
    for i, t in enumerate(team_list):
        t["rank"] = i + 1

    return {"teams": team_list, "level": league_level}


# ---------------------------------------------------------------------------
# 3. Pythagorean W-L + Team Stats
# ---------------------------------------------------------------------------

def compute_pythagorean(
    conn,
    league_year_id: int,
    league_level: int,
    exponent: float = 1.83,
) -> Dict[str, Any]:
    """Pythagorean expected wins + team batting/pitching stats."""
    season_id = _resolve_season_id(conn, league_year_id)
    games = _load_game_results(conn, season_id, league_level)
    teams_map = _load_teams_at_level(conn, league_level)

    # Aggregate runs scored/allowed and W-L
    rs: Dict[int, int] = {tid: 0 for tid in teams_map}
    ra: Dict[int, int] = {tid: 0 for tid in teams_map}
    wins: Dict[int, int] = {tid: 0 for tid in teams_map}
    losses: Dict[int, int] = {tid: 0 for tid in teams_map}

    for g in games:
        home, away = g["home_team_id"], g["away_team_id"]
        hs, aws = g["home_score"], g["away_score"]
        for tid in (home, away):
            rs.setdefault(tid, 0)
            ra.setdefault(tid, 0)
            wins.setdefault(tid, 0)
            losses.setdefault(tid, 0)
        rs[home] += hs
        ra[home] += aws
        rs[away] += aws
        ra[away] += hs
        if g["winning_team_id"] == home:
            wins[home] += 1
            losses[away] += 1
        else:
            wins[away] += 1
            losses[home] += 1

    # Team batting stats
    batting_stats = _team_batting_stats(conn, league_year_id, league_level)
    pitching_stats = _team_pitching_stats(conn, league_year_id, league_level)

    team_list = []
    for tid, info in teams_map.items():
        w, l = wins.get(tid, 0), losses.get(tid, 0)
        gp = w + l
        r_s, r_a = rs.get(tid, 0), ra.get(tid, 0)
        # Pythagorean
        if r_s + r_a > 0:
            pyth = (r_s ** exponent) / (r_s ** exponent + r_a ** exponent)
        else:
            pyth = 0.5
        exp_w = round(pyth * gp, 1) if gp > 0 else 0.0
        exp_l = round(gp - exp_w, 1) if gp > 0 else 0.0
        luck = round(w - exp_w, 1)

        team_list.append({
            **info,
            "wins": w, "losses": l, "games_played": gp,
            "win_pct": round(w / gp, 3) if gp > 0 else 0.0,
            "runs_scored": r_s, "runs_allowed": r_a,
            "run_diff": r_s - r_a,
            "r_per_g": round(r_s / gp, 2) if gp > 0 else 0.0,
            "ra_per_g": round(r_a / gp, 2) if gp > 0 else 0.0,
            "pyth_pct": round(pyth, 4),
            "expected_wins": exp_w, "expected_losses": exp_l,
            "luck": luck,
            "batting": batting_stats.get(tid, {}),
            "pitching": pitching_stats.get(tid, {}),
        })
    team_list.sort(key=lambda t: t["pyth_pct"], reverse=True)
    for i, t in enumerate(team_list):
        t["rank"] = i + 1

    return {"teams": team_list, "exponent": exponent, "level": league_level}


def _team_batting_stats(conn, league_year_id: int, league_level: int) -> Dict[int, dict]:
    """Aggregate team batting: AVG, OPS, HR, R/G."""
    rows = conn.execute(sa_text("""
        SELECT pbs.team_id,
               SUM(pbs.at_bats) AS ab,
               SUM(pbs.hits) AS h,
               SUM(pbs.doubles_hit) AS d,
               SUM(pbs.triples) AS t,
               SUM(pbs.home_runs) AS hr,
               SUM(pbs.walks) AS bb,
               SUM(pbs.runs) AS r,
               SUM(pbs.games) AS g
        FROM player_batting_stats pbs
        JOIN teams tm ON tm.id = pbs.team_id AND tm.team_level = :level
        WHERE pbs.league_year_id = :lyid
        GROUP BY pbs.team_id
    """), {"lyid": league_year_id, "level": league_level}).all()

    result = {}
    for r in rows:
        tid = r[0]
        ab = int(r[1] or 0)
        h = int(r[2] or 0)
        d = int(r[3] or 0)
        t = int(r[4] or 0)
        hr = int(r[5] or 0)
        bb = int(r[6] or 0)
        runs = int(r[7] or 0)
        g = int(r[8] or 0)
        avg = round(h / ab, 3) if ab > 0 else 0.0
        slg = round((h - d - t - hr + 2 * d + 3 * t + 4 * hr) / ab, 3) if ab > 0 else 0.0
        obp = round((h + bb) / (ab + bb), 3) if (ab + bb) > 0 else 0.0
        ops = round(obp + slg, 3)
        r_per_g = round(runs / g, 2) if g > 0 else 0.0
        result[tid] = {"avg": avg, "ops": ops, "hr": hr, "r_per_g": r_per_g}
    return result


def _team_pitching_stats(conn, league_year_id: int, league_level: int) -> Dict[int, dict]:
    """Aggregate team pitching: ERA, WHIP, K/9."""
    rows = conn.execute(sa_text("""
        SELECT pps.team_id,
               SUM(pps.innings_pitched_outs) AS ipo,
               SUM(pps.earned_runs) AS er,
               SUM(pps.hits_allowed) AS ha,
               SUM(pps.walks) AS bb,
               SUM(pps.strikeouts) AS k
        FROM player_pitching_stats pps
        JOIN teams tm ON tm.id = pps.team_id AND tm.team_level = :level
        WHERE pps.league_year_id = :lyid
        GROUP BY pps.team_id
    """), {"lyid": league_year_id, "level": league_level}).all()

    result = {}
    for r in rows:
        tid = r[0]
        ipo = int(r[1] or 0)
        er = int(r[2] or 0)
        ha = int(r[3] or 0)
        bb = int(r[4] or 0)
        k = int(r[5] or 0)
        ip = ipo / 3.0 if ipo > 0 else 0.0
        era = round(er * 9.0 / ip, 2) if ip > 0 else 0.0
        whip = round((ha + bb) / ip, 3) if ip > 0 else 0.0
        k9 = round(k * 9.0 / ip, 1) if ip > 0 else 0.0
        result[tid] = {"era": era, "whip": whip, "k_per_9": k9}
    return result


# ---------------------------------------------------------------------------
# 4. Power Rankings
# ---------------------------------------------------------------------------

_DEFAULT_POWER_WEIGHTS = {
    "elo": 0.30, "recent": 0.25, "run_diff": 0.20, "roster_ovr": 0.25,
}


def compute_power_rankings(
    conn,
    league_year_id: int,
    league_level: int,
    weights: Optional[Dict[str, float]] = None,
    recent_weeks: int = 3,
) -> Dict[str, Any]:
    """Composite power rankings from ELO, recent record, run diff, roster OVR."""
    w = weights or dict(_DEFAULT_POWER_WEIGHTS)
    recent_weeks = max(1, min(8, recent_weeks))

    # Reuse ELO computation
    elo_data = compute_elo_ratings(conn, league_year_id, league_level)
    elo_by_id = {t["team_id"]: t["elo"] for t in elo_data["teams"]}
    record_by_id = {t["team_id"]: t for t in elo_data["teams"]}

    # Recent record from game_results
    season_id = _resolve_season_id(conn, league_year_id)
    games = _load_game_results(conn, season_id, league_level)
    teams_map = _load_teams_at_level(conn, league_level)

    # Find max week
    max_week = max((g["season_week"] for g in games), default=0)
    cutoff_week = max(1, max_week - recent_weeks + 1)

    recent_wins: Dict[int, int] = {tid: 0 for tid in teams_map}
    recent_games: Dict[int, int] = {tid: 0 for tid in teams_map}
    total_rs: Dict[int, int] = {tid: 0 for tid in teams_map}
    total_ra: Dict[int, int] = {tid: 0 for tid in teams_map}
    total_gp: Dict[int, int] = {tid: 0 for tid in teams_map}

    for g in games:
        home, away = g["home_team_id"], g["away_team_id"]
        for tid in (home, away):
            total_rs.setdefault(tid, 0)
            total_ra.setdefault(tid, 0)
            total_gp.setdefault(tid, 0)
            recent_wins.setdefault(tid, 0)
            recent_games.setdefault(tid, 0)

        total_rs[home] += g["home_score"]
        total_ra[home] += g["away_score"]
        total_rs[away] += g["away_score"]
        total_ra[away] += g["home_score"]
        total_gp[home] += 1
        total_gp[away] += 1

        if g["season_week"] >= cutoff_week:
            recent_games[home] = recent_games.get(home, 0) + 1
            recent_games[away] = recent_games.get(away, 0) + 1
            if g["winning_team_id"] == home:
                recent_wins[home] = recent_wins.get(home, 0) + 1
            else:
                recent_wins[away] = recent_wins.get(away, 0) + 1

    # Per-game run differential
    run_diff_pg: Dict[int, float] = {}
    for tid in teams_map:
        gp = total_gp.get(tid, 0)
        if gp > 0:
            run_diff_pg[tid] = (total_rs.get(tid, 0) - total_ra.get(tid, 0)) / gp
        else:
            run_diff_pg[tid] = 0.0

    # Recent win%
    recent_pct: Dict[int, float] = {}
    for tid in teams_map:
        rg = recent_games.get(tid, 0)
        recent_pct[tid] = recent_wins.get(tid, 0) / rg if rg > 0 else 0.0

    # Roster OVR
    roster_ovr = _compute_team_ovr_bulk(conn, league_level)

    # Normalize each component to 0-100
    norm_elo = _normalize_values(elo_by_id)
    norm_recent = _normalize_values(recent_pct)
    norm_rdiff = _normalize_values(run_diff_pg)
    norm_ovr = _normalize_values(roster_ovr)

    team_list = []
    for tid, info in teams_map.items():
        ne = norm_elo.get(tid, 50.0)
        nr = norm_recent.get(tid, 50.0)
        nd = norm_rdiff.get(tid, 50.0)
        no = norm_ovr.get(tid, 50.0)
        composite = (w["elo"] * ne + w["recent"] * nr +
                     w["run_diff"] * nd + w["roster_ovr"] * no)
        rec = record_by_id.get(tid, {})
        team_list.append({
            **info,
            "composite_score": round(composite, 2),
            "components": {
                "elo": {"raw": round(elo_by_id.get(tid, 1500.0), 1), "normalized": round(ne, 1)},
                "recent": {"raw": round(recent_pct.get(tid, 0.0), 3), "normalized": round(nr, 1)},
                "run_diff": {"raw": round(run_diff_pg.get(tid, 0.0), 2), "normalized": round(nd, 1)},
                "roster_ovr": {"raw": round(roster_ovr.get(tid, 0.0), 1), "normalized": round(no, 1)},
            },
            "wins": rec.get("wins", 0),
            "losses": rec.get("losses", 0),
            "games_played": rec.get("games_played", 0),
        })
    team_list.sort(key=lambda t: t["composite_score"], reverse=True)
    for i, t in enumerate(team_list):
        t["rank"] = i + 1

    return {
        "teams": team_list,
        "weights": w,
        "recent_weeks": recent_weeks,
        "level": league_level,
    }


# ---------------------------------------------------------------------------
# Team OVR computation
# ---------------------------------------------------------------------------

def _compute_team_ovr_bulk(conn, league_level: int) -> Dict[int, float]:
    """
    Average player OVR per team at a given level.
    Uses position-specific weights when a player has a listed position,
    falling back to pitcher_overall / position_overall otherwise.
    """
    from services.weight_calibration import _resolve_ovr_weights

    # Load overall weights
    try:
        wt_rows = conn.execute(sa_text(
            "SELECT rating_type, attribute_key, weight "
            "FROM rating_overall_weights ORDER BY rating_type, attribute_key"
        )).all()
    except Exception:
        logger.warning("rating_overall_weights not found, using attribute averages")
        return _compute_team_ovr_simple(conn, league_level)

    wt_map: Dict[str, Dict[str, float]] = {}
    for r in wt_rows:
        wt_map.setdefault(str(r[0]), {})[str(r[1])] = float(r[2])

    pitcher_wt = wt_map.get("pitcher_overall", {})
    position_wt = wt_map.get("position_overall", {})

    # Resolve current league_year_id for listed-position lookup
    ly_row = conn.execute(sa_text(
        "SELECT id FROM league_years WHERE league_year = "
        "(SELECT season FROM timestamp_state WHERE id = 1)"
    )).first()
    league_year_id = int(ly_row[0]) if ly_row else None

    # Bulk-load listed positions
    listed_positions: Dict[int, str] = {}
    if league_year_id is not None:
        lp_rows = conn.execute(sa_text(
            "SELECT player_id, position_code FROM player_listed_position "
            "WHERE league_year_id = :lyid"
        ), {"lyid": league_year_id}).all()
        for lp in lp_rows:
            listed_positions[int(lp[0])] = str(lp[1])

    # Load all active players at this level
    rows = conn.execute(sa_text("""
        SELECT p.id, p.ptype, tm.id AS team_id,
               p.contact_base, p.power_base, p.eye_base, p.discipline_base,
               p.speed_base, p.baserunning_base, p.basereaction_base,
               p.pendurance_base, p.pgencontrol_base, p.psequencing_base,
               p.pthrowpower_base, p.pickoff_base,
               p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
               p.throwacc_base, p.throwpower_base,
               p.catchframe_base, p.catchsequence_base,
               p.pitch1_consist_base, p.pitch1_pacc_base, p.pitch1_pbrk_base, p.pitch1_pcntrl_base,
               p.pitch2_consist_base, p.pitch2_pacc_base, p.pitch2_pbrk_base, p.pitch2_pcntrl_base,
               p.pitch3_consist_base, p.pitch3_pacc_base, p.pitch3_pbrk_base, p.pitch3_pcntrl_base,
               p.pitch4_consist_base, p.pitch4_pacc_base, p.pitch4_pbrk_base, p.pitch4_pcntrl_base,
               p.pitch5_consist_base, p.pitch5_pacc_base, p.pitch5_pbrk_base, p.pitch5_pcntrl_base,
               p.pitch1_name, p.pitch2_name, p.pitch3_name, p.pitch4_name, p.pitch5_name
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        JOIN teams tm ON tm.orgID = cts.orgID AND tm.team_level = c.current_level
        WHERE c.current_level = :level
    """), {"level": league_level}).all()

    # Column names for dict-like access
    col_names = [
        "id", "ptype", "team_id",
        "contact_base", "power_base", "eye_base", "discipline_base",
        "speed_base", "baserunning_base", "basereaction_base",
        "pendurance_base", "pgencontrol_base", "psequencing_base",
        "pthrowpower_base", "pickoff_base",
        "fieldcatch_base", "fieldreact_base", "fieldspot_base",
        "throwacc_base", "throwpower_base",
        "catchframe_base", "catchsequence_base",
        "pitch1_consist_base", "pitch1_pacc_base", "pitch1_pbrk_base", "pitch1_pcntrl_base",
        "pitch2_consist_base", "pitch2_pacc_base", "pitch2_pbrk_base", "pitch2_pcntrl_base",
        "pitch3_consist_base", "pitch3_pacc_base", "pitch3_pbrk_base", "pitch3_pcntrl_base",
        "pitch4_consist_base", "pitch4_pacc_base", "pitch4_pbrk_base", "pitch4_pcntrl_base",
        "pitch5_consist_base", "pitch5_pacc_base", "pitch5_pbrk_base", "pitch5_pcntrl_base",
        "pitch1_name", "pitch2_name", "pitch3_name", "pitch4_name", "pitch5_name",
    ]

    # Compute per-player OVR and aggregate by team
    team_ovrs: Dict[int, List[float]] = {}
    for row in rows:
        m = {col_names[i]: row[i] for i in range(len(col_names))}
        tid = m["team_id"]
        pid = int(m["id"])
        ptype = m["ptype"]

        # Compute pitch overalls (derived ratings)
        derived: Dict[str, float] = {}
        for n in range(1, 6):
            prefix = f"pitch{n}_"
            if m.get(prefix + "name") is None:
                continue
            comps = []
            for suffix in ("consist_base", "pacc_base", "pbrk_base", "pcntrl_base"):
                v = m.get(prefix + suffix)
                if v is not None:
                    comps.append((float(v), 0.25))
            if comps:
                tw = sum(c[1] for c in comps)
                tv = sum(c[0] * c[1] for c in comps)
                if tw > 0:
                    derived[f"pitch{n}_ovr"] = tv / tw

        # Position-aware weight selection
        wts = _resolve_ovr_weights(
            pid, ptype, listed_positions, wt_map,
            pitcher_wt, position_wt,
        )
        if not wts:
            continue

        # Weighted average
        components = []
        for attr_key, weight in wts.items():
            if weight <= 0:
                continue
            val = derived.get(attr_key)
            if val is None:
                raw = m.get(attr_key)
                if raw is not None:
                    val = float(raw)
            if val is not None:
                components.append((val, weight))

        if not components:
            continue
        total_w = sum(c[1] for c in components)
        total_v = sum(c[0] * c[1] for c in components)
        if total_w > 0:
            ovr = total_v / total_w
            team_ovrs.setdefault(tid, []).append(ovr)

    # Average per team
    return {tid: round(sum(vals) / len(vals), 1) for tid, vals in team_ovrs.items() if vals}


def _compute_team_ovr_simple(conn, league_level: int) -> Dict[int, float]:
    """Fallback: average key attributes per team (no weight table needed)."""
    rows = conn.execute(sa_text("""
        SELECT tm.id AS team_id,
               AVG(CASE WHEN p.ptype = 'Position' THEN
                   (COALESCE(p.contact_base,0) + COALESCE(p.power_base,0) +
                    COALESCE(p.eye_base,0) + COALESCE(p.speed_base,0) +
                    COALESCE(p.fieldreact_base,0)) / 5.0
               ELSE
                   (COALESCE(p.pendurance_base,0) + COALESCE(p.pgencontrol_base,0) +
                    COALESCE(p.psequencing_base,0) + COALESCE(p.pthrowpower_base,0)) / 4.0
               END) AS avg_ovr
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        JOIN teams tm ON tm.orgID = cts.orgID AND tm.team_level = c.current_level
        WHERE c.current_level = :level
        GROUP BY tm.id
    """), {"level": league_level}).all()
    return {r[0]: round(float(r[1]), 1) for r in rows if r[1] is not None}


# ---------------------------------------------------------------------------
# 5. Race Chart (cumulative W-L over time)
# ---------------------------------------------------------------------------

def compute_race_chart(
    conn,
    league_year_id: int,
    league_level: int,
) -> Dict[str, Any]:
    """
    Cumulative wins-minus-losses per team per week.

    Level 9 (MLB): grouped by division (e.g. "AL East").
    Levels 4-8 (MiLB): single group, all teams together.
    Level 3 (College): grouped by conference.
    """
    season_id = _resolve_season_id(conn, league_year_id)
    games = _load_game_results(conn, season_id, league_level)
    teams_map = _load_teams_at_level(conn, league_level)

    # Determine grouping
    if league_level == 9:
        # MLB: group by "conference division" e.g. "AL East"
        def group_key(info):
            return f"{info.get('conference', '?')} {info.get('division', '?')}"
    elif league_level == 3:
        # College: group by conference
        def group_key(info):
            return info.get("conference") or "Independent"
    else:
        # MiLB: single group
        def group_key(info):
            return "All Teams"

    # Build per-team cumulative W-L by week
    # First collect all weeks and per-team weekly deltas
    all_weeks = sorted({g["season_week"] for g in games})
    weekly_delta: Dict[int, Dict[int, int]] = {
        tid: {w: 0 for w in all_weeks} for tid in teams_map
    }

    for g in games:
        home, away = g["home_team_id"], g["away_team_id"]
        week = g["season_week"]
        if g["winning_team_id"] == home:
            weekly_delta.setdefault(home, {}).setdefault(week, 0)
            weekly_delta.setdefault(away, {}).setdefault(week, 0)
            weekly_delta[home][week] = weekly_delta[home].get(week, 0) + 1
            weekly_delta[away][week] = weekly_delta[away].get(week, 0) - 1
        elif g["winning_team_id"] == away:
            weekly_delta.setdefault(away, {}).setdefault(week, 0)
            weekly_delta.setdefault(home, {}).setdefault(week, 0)
            weekly_delta[away][week] = weekly_delta[away].get(week, 0) + 1
            weekly_delta[home][week] = weekly_delta[home].get(week, 0) - 1

    # Build cumulative series per team
    team_series: Dict[int, List[dict]] = {}
    for tid in teams_map:
        cumulative = 0
        series = []
        for week in all_weeks:
            cumulative += weekly_delta.get(tid, {}).get(week, 0)
            series.append({"week": week, "value": cumulative})
        team_series[tid] = series

    # Group teams
    groups: Dict[str, List[dict]] = {}
    for tid, info in teams_map.items():
        gk = group_key(info)
        final_val = team_series[tid][-1]["value"] if team_series[tid] else 0
        groups.setdefault(gk, []).append({
            **info,
            "series": team_series[tid],
            "final_value": final_val,
        })

    # Sort teams within each group by final value descending
    for gk in groups:
        groups[gk].sort(key=lambda t: t["final_value"], reverse=True)

    # Sort group keys
    if league_level == 9:
        # AL East, AL Central, AL West, NL East, NL Central, NL West
        div_order = {"East": 0, "Central": 1, "West": 2}
        sorted_keys = sorted(groups.keys(), key=lambda k: (
            0 if k.startswith("AL") else 1,
            div_order.get(k.split()[-1], 9),
        ))
    else:
        sorted_keys = sorted(groups.keys())

    return {
        "groups": {k: groups[k] for k in sorted_keys},
        "weeks": all_weeks,
        "level": league_level,
        "group_type": "division" if league_level == 9 else
                      "conference" if league_level == 3 else "level",
    }
