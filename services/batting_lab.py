# services/batting_lab.py
"""
Batting Lab — micro-simulation harness for testing the batting system.

Constructs synthetic players at controlled attribute tiers, sends them
through the real Rust game engine, and aggregates the results.  No real
DB players are used; everything is fabricated in-memory so the test is
hermetic and fast.
"""

import json
import logging
import random
import time
from typing import Any, Dict, List

from sqlalchemy import text as sa_text

from db import get_engine
from services.game_payload import (
    get_game_constants,
    get_level_config_normalized,
    _get_level_rules_for_league,
    get_all_injury_types,
)
from services.game_engine_client import simulate_games_batch

logger = logging.getLogger(__name__)

# ── Attribute tiers ──────────────────────────────────────────────────
# Each tier sets ALL _base attributes to the same value so we can
# observe pure output differences driven by player quality.

TIERS = {
    "elite":        80,
    "above_avg":    65,
    "average":      50,
    "below_avg":    35,
    "poor":         20,
}

# Core batting _base attributes the engine reads
_BATTER_BASE_ATTRS = [
    "contact_base", "power_base", "eye_base", "discipline_base",
    "speed_base", "baserunning_base", "basereaction_base",
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    "throwacc_base", "throwpower_base", "catchframe_base",
    "catchsequence_base",
]

# Pitcher _base attributes
_PITCHER_BASE_ATTRS = [
    "pgencontrol_base", "pthrowpower_base", "psequencing_base",
    "pendurance_base", "pickoff_base",
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    "throwacc_base", "throwpower_base",
]

# Per-pitch attributes (5 pitch slots)
_PITCH_ATTRS = ["consist_base", "pacc_base", "pbrk_base", "pcntrl_base"]

POSITION_CODES = ["c", "fb", "sb", "tb", "ss", "lf", "cf", "rf", "dh", "p"]

DEFAULT_STRATEGY = {
    "plate_approach": "normal",
    "pitching_approach": "normal",
    "baserunning_approach": "normal",
    "usage_preference": "normal",
    "stealfreq": 1.87,
    "pickofffreq": 1.0,
    "pitchchoices": [1, 1, 1, 1, 1],
    "pitchpull": None,
    "pulltend": None,
}


# ── Synthetic player construction ────────────────────────────────────

def _make_batter(pid: int, tier_value: int, bat_hand: str = "R") -> Dict[str, Any]:
    """Create a synthetic batter dict the engine will accept."""
    p: Dict[str, Any] = {
        "id": pid,
        "firstname": "Test",
        "lastname": f"Batter{pid}",
        "ptype": "batter",
        "durability": "Normal",
        "injury_risk": "Normal",
        "bat_hand": bat_hand,
        "pitch_hand": None,
        "arm_angle": None,
        "left_split": 0, "center_split": 0, "right_split": 0,
        "pitch1_name": None, "pitch2_name": None, "pitch3_name": None,
        "pitch4_name": None, "pitch5_name": None,
        "stamina": 100,
        "defensive_xp_mod": {pos: 0.0 for pos in POSITION_CODES},
    }
    for attr in _BATTER_BASE_ATTRS:
        p[attr] = tier_value
    # Pitch attrs not relevant for batters but engine may expect them
    for i in range(1, 6):
        for suffix in _PITCH_ATTRS:
            p[f"pitch{i}_{suffix}"] = 0
    # Derived ratings — set position ratings to tier_value
    for pos in POSITION_CODES:
        p[f"{pos}_rating"] = float(tier_value) if pos != "p" else 0.0
    p["sp_rating"] = 0.0
    p["rp_rating"] = 0.0
    p.update(DEFAULT_STRATEGY)
    return p


def _make_pitcher(pid: int, tier_value: int, pitch_hand: str = "R") -> Dict[str, Any]:
    """Create a synthetic pitcher dict."""
    p: Dict[str, Any] = {
        "id": pid,
        "firstname": "Test",
        "lastname": f"Pitcher{pid}",
        "ptype": "pitcher",
        "durability": "Iron Man",
        "injury_risk": "Normal",
        "bat_hand": "R",
        "pitch_hand": pitch_hand,
        "arm_angle": "over_the_top",
        "left_split": 0, "center_split": 0, "right_split": 0,
        "pitch1_name": "Fastball", "pitch2_name": "Slider",
        "pitch3_name": "Changeup", "pitch4_name": "Curveball",
        "pitch5_name": None,
        "stamina": 100,
        "defensive_xp_mod": {pos: 0.0 for pos in POSITION_CODES},
    }
    for attr in _PITCHER_BASE_ATTRS:
        p[attr] = tier_value
    # Batter attrs at minimum
    for attr in _BATTER_BASE_ATTRS:
        if attr not in p:
            p[attr] = 20
    # Pitch slot attributes
    for i in range(1, 5):  # 4 pitches
        for suffix in _PITCH_ATTRS:
            p[f"pitch{i}_{suffix}"] = tier_value
    # 5th pitch empty
    for suffix in _PITCH_ATTRS:
        p[f"pitch5_{suffix}"] = 0
    # Derived ratings
    for pos in POSITION_CODES:
        p[f"{pos}_rating"] = 0.0
    p["sp_rating"] = float(tier_value)
    p["rp_rating"] = float(tier_value)
    p.update(DEFAULT_STRATEGY)
    # Override pitcher-specific strategy
    p["pitching_approach"] = "normal"
    p["usage_preference"] = "normal"
    return p


def _build_team_side(
    team_id: int,
    batter_tier: int,
    pitcher_tier: int,
    label: str,
) -> Dict[str, Any]:
    """
    Build a complete team side payload with 9 batters + 1 SP + 4 relievers.
    All synthetic — no DB lookups needed.
    """
    base_pid = team_id * 100  # ensure unique IDs per side

    # 9 position players (alternate L/R bat hands for realism)
    hands = ["R", "L", "R", "R", "L", "R", "L", "R", "R"]
    batters = []
    for i in range(9):
        batters.append(_make_batter(base_pid + i + 1, batter_tier, hands[i]))

    # SP + 4 relievers
    sp = _make_pitcher(base_pid + 10, pitcher_tier, "R")
    relievers = [
        _make_pitcher(base_pid + 11 + j, pitcher_tier, "R" if j % 2 == 0 else "L")
        for j in range(4)
    ]

    all_players = batters + [sp] + relievers

    # Lineup = 9 batter IDs in order
    lineup_ids = [b["id"] for b in batters]

    # Defense map: position -> player_id
    positions = ["c", "fb", "sb", "ss", "tb", "lf", "cf", "rf", "dh"]
    defense = {positions[i]: batters[i]["id"] for i in range(9)}

    return {
        "team_id": team_id,
        "team_abbrev": label[:3].upper(),
        "team_name": f"Lab {label}",
        "team_nickname": label,
        "org_id": team_id,
        "players": all_players,
        "starting_pitcher_id": sp["id"],
        "available_pitcher_ids": [r["id"] for r in relievers],
        "defense": defense,
        "lineup": lineup_ids,
        "bench": [],
        "pregame_injuries": [],
        "team_strategy": {},
        "bullpen_order": [],
        "vs_hand": "R",
    }


def _build_synthetic_game(
    game_id: int,
    league_level: int,
    batter_tier: int,
    pitcher_tier: int,
) -> Dict[str, Any]:
    """Build a single synthetic game core payload."""
    home = _build_team_side(901, batter_tier, pitcher_tier, "Home")
    away = _build_team_side(902, batter_tier, pitcher_tier, "Away")

    return {
        "game_id": game_id,
        "league_level_id": league_level,
        "league_year_id": 0,
        "season_week": 1,
        "season_subweek": "a",
        "ballpark": {
            "ballpark_name": "Lab Park",
            "pitch_break_mod": 1.0,
            "power_mod": 1.0,
        },
        "home_side": home,
        "away_side": away,
        "random_seed": str(game_id),
    }


# ── Tier sweep scenario ─────────────────────────────────────────────

def _aggregate_batting_stats(
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Aggregate batting stats from a list of engine results.
    Returns totals for all batters across all games.
    """
    totals: Dict[str, int] = {
        "games": 0,
        "plate_appearances": 0,
        "at_bats": 0,
        "hits": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "inside_the_park_hr": 0,
        "walks": 0,
        "strikeouts": 0,
        "runs": 0,
        "rbi": 0,
        "stolen_bases": 0,
    }
    score_home = 0
    score_away = 0

    for game_result in results:
        nested = game_result.get("result") or {}
        stats = game_result.get("stats") or nested.get("stats")
        if not stats:
            continue

        totals["games"] += 1

        # Scores
        home_score = game_result.get("home_score") or nested.get("home_score") or 0
        away_score = game_result.get("away_score") or nested.get("away_score") or 0
        score_home += int(home_score)
        score_away += int(away_score)

        batters = stats.get("batters") or {}
        for pid_str, b in batters.items():
            ab = int(b.get("at_bats", 0))
            bb = int(b.get("walks", 0))
            totals["at_bats"] += ab
            totals["walks"] += bb
            totals["plate_appearances"] += ab + bb
            totals["hits"] += int(b.get("hits", 0))
            totals["doubles"] += int(b.get("doubles", 0))
            totals["triples"] += int(b.get("triples", 0))
            totals["home_runs"] += int(b.get("home_runs", 0))
            totals["inside_the_park_hr"] += int(b.get("inside_the_park_hr", 0))
            totals["strikeouts"] += int(b.get("strikeouts", 0))
            totals["runs"] += int(b.get("runs", 0))
            totals["rbi"] += int(b.get("rbi", 0))
            totals["stolen_bases"] += int(b.get("stolen_bases", 0))

    totals["avg_score_home"] = round(score_home / max(1, totals["games"]), 2)
    totals["avg_score_away"] = round(score_away / max(1, totals["games"]), 2)

    return totals


def _compute_rate_stats(totals: Dict[str, Any]) -> Dict[str, Any]:
    """Compute AVG, OBP, SLG, OPS, ISO, K%, BB% from raw totals."""
    ab = totals.get("at_bats", 0) or 1
    pa = totals.get("plate_appearances", 0) or 1
    h = totals.get("hits", 0)
    d = totals.get("doubles", 0)
    t = totals.get("triples", 0)
    hr = totals.get("home_runs", 0)
    itphr = totals.get("inside_the_park_hr", 0)
    bb = totals.get("walks", 0)
    k = totals.get("strikeouts", 0)

    singles = h - d - t - hr
    avg = h / ab
    obp = (h + bb) / pa
    slg = (singles + 2 * d + 3 * t + 4 * hr) / ab
    iso = slg - avg
    ops = obp + slg
    k_pct = k / pa
    bb_pct = bb / pa

    return {
        "avg": round(avg, 3),
        "obp": round(obp, 3),
        "slg": round(slg, 3),
        "ops": round(ops, 3),
        "iso": round(iso, 3),
        "k_pct": round(k_pct * 100, 1),
        "bb_pct": round(bb_pct * 100, 1),
        "itphr": itphr,
        "itphr_pct": round(itphr / max(hr, 1) * 100, 1) if hr else 0.0,
    }


# ── Main run entrypoint ─────────────────────────────────────────────

def run_tier_sweep(
    conn,
    run_id: int,
    league_level: int,
    games_per_tier: int = 50,
) -> Dict[str, Any]:
    """
    Run a tier sweep: for each tier in TIERS, simulate games_per_tier
    games through the real engine, aggregate results, and persist them.

    Pitchers are held constant at 'average' (50) so batting tier is
    the only variable.

    Args:
        conn: Active DB connection (for loading game constants + storing results).
        run_id: The batting_lab_runs.id to write results into.
        league_level: The league level whose config tables to use.
        games_per_tier: Number of games per tier.

    Returns:
        Summary dict with per-tier results.
    """
    # Load engine config from DB
    game_constants = get_game_constants(conn)
    level_config = get_level_config_normalized(conn, league_level)
    level_configs = {str(league_level): level_config}
    rules = _get_level_rules_for_league(conn, league_level)
    rules_by_level = {str(league_level): rules}
    injury_types = get_all_injury_types(conn)

    pitcher_tier = 50  # constant control

    summary = {}

    for tier_name, tier_value in TIERS.items():
        logger.info(f"Batting Lab run {run_id}: simulating tier '{tier_name}' ({tier_value}) x{games_per_tier}")

        # Build game payloads for this tier
        games = []
        for g in range(games_per_tier):
            gid = -(run_id * 10000 + list(TIERS.keys()).index(tier_name) * 1000 + g + 1)
            core = _build_synthetic_game(gid, league_level, tier_value, pitcher_tier)
            games.append(core)

        # Send to engine in one batch
        try:
            results = simulate_games_batch(
                games=games,
                subweek="a",
                timeout=120,
                game_constants=game_constants,
                level_configs=level_configs,
                rules=rules_by_level,
                injury_types=injury_types,
                league_level=league_level,
            )
        except Exception as e:
            logger.exception(f"Engine call failed for tier {tier_name}")
            raise ValueError(f"Engine simulation failed for tier '{tier_name}': {e}")

        # Aggregate stats
        totals = _aggregate_batting_stats(results)
        rates = _compute_rate_stats(totals)

        scenario_key = f"tier_{tier_name}"

        # Persist to DB
        conn.execute(sa_text("""
            INSERT INTO batting_lab_results
                (run_id, scenario_key, tier_label, games_played,
                 plate_appearances, at_bats, hits, doubles_ct, triples_ct,
                 home_runs, inside_the_park_hr, walks, strikeouts, runs, rbi, stolen_bases,
                 avg_score_home, avg_score_away, raw_json)
            VALUES
                (:run_id, :scenario_key, :tier_label, :games_played,
                 :pa, :ab, :h, :d, :t, :hr, :itphr, :bb, :k, :r, :rbi, :sb,
                 :ash, :asa, :raw)
            ON DUPLICATE KEY UPDATE
                games_played = :u_games_played,
                plate_appearances = :u_pa,
                at_bats = :u_ab,
                hits = :u_h,
                doubles_ct = :u_d,
                triples_ct = :u_t,
                home_runs = :u_hr,
                inside_the_park_hr = :u_itphr,
                walks = :u_bb,
                strikeouts = :u_k,
                runs = :u_r,
                rbi = :u_rbi,
                stolen_bases = :u_sb,
                avg_score_home = :u_ash,
                avg_score_away = :u_asa,
                raw_json = :u_raw
        """), {
            "run_id": run_id,
            "scenario_key": scenario_key,
            "tier_label": tier_name,
            "games_played": totals["games"],
            "pa": totals["plate_appearances"],
            "ab": totals["at_bats"],
            "h": totals["hits"],
            "d": totals["doubles"],
            "t": totals["triples"],
            "hr": totals["home_runs"],
            "itphr": totals["inside_the_park_hr"],
            "bb": totals["walks"],
            "k": totals["strikeouts"],
            "r": totals["runs"],
            "rbi": totals["rbi"],
            "sb": totals["stolen_bases"],
            "ash": totals.get("avg_score_home", 0),
            "asa": totals.get("avg_score_away", 0),
            "raw": json.dumps(rates),
            "u_games_played": totals["games"],
            "u_pa": totals["plate_appearances"],
            "u_ab": totals["at_bats"],
            "u_h": totals["hits"],
            "u_d": totals["doubles"],
            "u_t": totals["triples"],
            "u_hr": totals["home_runs"],
            "u_itphr": totals["inside_the_park_hr"],
            "u_bb": totals["walks"],
            "u_k": totals["strikeouts"],
            "u_r": totals["runs"],
            "u_rbi": totals["rbi"],
            "u_sb": totals["stolen_bases"],
            "u_ash": totals.get("avg_score_home", 0),
            "u_asa": totals.get("avg_score_away", 0),
            "u_raw": json.dumps(rates),
        })

        summary[tier_name] = {**totals, **rates}
        logger.info(f"Batting Lab run {run_id}: tier '{tier_name}' → .{rates['avg']:.3f}/.{rates['obp']:.3f}/.{rates['slg']:.3f}")

    return summary


def execute_batting_lab_run(
    run_id: int,
    league_level: int,
    games_per_tier: int = 50,
) -> Dict[str, Any]:
    """
    Top-level function to execute a batting lab run.
    Manages its own connection and updates run status.
    """
    engine = get_engine()

    # Mark as running
    with engine.begin() as conn:
        conn.execute(sa_text(
            "UPDATE batting_lab_runs SET status = 'running' WHERE id = :id"
        ), {"id": run_id})

    try:
        with engine.begin() as conn:
            result = run_tier_sweep(conn, run_id, league_level, games_per_tier)

        # Mark complete
        with engine.begin() as conn:
            conn.execute(sa_text(
                "UPDATE batting_lab_runs SET status = 'complete', completed_at = NOW() WHERE id = :id"
            ), {"id": run_id})

        return {"status": "complete", "tiers": result}

    except Exception as e:
        logger.exception(f"Batting lab run {run_id} failed")
        with engine.begin() as conn:
            conn.execute(sa_text(
                "UPDATE batting_lab_runs SET status = 'error', error_message = :msg WHERE id = :id"
            ), {"id": run_id, "msg": str(e)[:2000]})
        raise


def get_run_results(conn, run_id: int) -> Dict[str, Any]:
    """Load results for a completed run."""
    run_row = conn.execute(sa_text(
        "SELECT id, label, league_level, games_per_scenario, scenario_type, status, error_message, created_at, completed_at "
        "FROM batting_lab_runs WHERE id = :id"
    ), {"id": run_id}).first()

    if not run_row:
        return None

    m = run_row._mapping
    run_info = {
        "id": m["id"],
        "label": m["label"],
        "league_level": m["league_level"],
        "games_per_scenario": m["games_per_scenario"],
        "scenario_type": m["scenario_type"],
        "status": m["status"],
        "error_message": m["error_message"],
        "created_at": str(m["created_at"]) if m["created_at"] else None,
        "completed_at": str(m["completed_at"]) if m["completed_at"] else None,
    }

    result_rows = conn.execute(sa_text(
        "SELECT scenario_key, tier_label, games_played, plate_appearances, at_bats, "
        "hits, doubles_ct, triples_ct, home_runs, inside_the_park_hr, walks, strikeouts, runs, rbi, "
        "stolen_bases, avg_score_home, avg_score_away, raw_json "
        "FROM batting_lab_results WHERE run_id = :id ORDER BY scenario_key"
    ), {"id": run_id}).all()

    tiers = []
    for r in result_rows:
        rm = r._mapping
        rates = {}
        if rm["raw_json"]:
            try:
                rates = json.loads(rm["raw_json"]) if isinstance(rm["raw_json"], str) else rm["raw_json"]
            except Exception:
                pass

        tiers.append({
            "scenario_key": rm["scenario_key"],
            "tier_label": rm["tier_label"],
            "games_played": rm["games_played"],
            "plate_appearances": rm["plate_appearances"],
            "at_bats": rm["at_bats"],
            "hits": rm["hits"],
            "doubles": rm["doubles_ct"],
            "triples": rm["triples_ct"],
            "home_runs": rm["home_runs"],
            "inside_the_park_hr": rm["inside_the_park_hr"],
            "walks": rm["walks"],
            "strikeouts": rm["strikeouts"],
            "runs": rm["runs"],
            "rbi": rm["rbi"],
            "stolen_bases": rm["stolen_bases"],
            "avg_score_home": rm["avg_score_home"],
            "avg_score_away": rm["avg_score_away"],
            **rates,
        })

    return {"run": run_info, "tiers": tiers}


def list_runs(conn, limit: int = 20) -> List[Dict[str, Any]]:
    """List recent batting lab runs."""
    rows = conn.execute(sa_text(
        "SELECT id, label, league_level, games_per_scenario, scenario_type, "
        "status, created_at, completed_at "
        "FROM batting_lab_runs ORDER BY id DESC LIMIT :lim"
    ), {"lim": limit}).all()

    return [{
        "id": r._mapping["id"],
        "label": r._mapping["label"],
        "league_level": r._mapping["league_level"],
        "games_per_scenario": r._mapping["games_per_scenario"],
        "scenario_type": r._mapping["scenario_type"],
        "status": r._mapping["status"],
        "created_at": str(r._mapping["created_at"]) if r._mapping["created_at"] else None,
        "completed_at": str(r._mapping["completed_at"]) if r._mapping["completed_at"] else None,
    } for r in rows]
