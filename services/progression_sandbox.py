# services/progression_sandbox.py
"""
In-memory progression sandbox for testing growth curves without DB writes.

Generates synthetic players, progresses them N seasons, and returns
aggregated statistics suitable for charting in the admin UI.
"""

import random
import statistics
import logging
from collections import defaultdict

from sqlalchemy import text

from db import get_engine
from player_engine.constants import ABILITY_CLASS_MAP, ALL_ABILITIES

log = logging.getLogger("app")


def run_progression_sandbox(
    count=200,
    seasons=20,
    start_age=15,
    player_type="Both",
    tracked_abilities=None,
    engine=None,
):
    """
    Run an in-memory progression simulation.

    1. Loads growth_curves and potential_weights from DB (read-only)
    2. Generates synthetic players purely in memory
    3. Progresses them through N seasons
    4. Returns aggregated results by ability, grade, and age

    Returns dict with config, tracked_abilities, and results ready for charting.
    """
    if engine is None:
        engine = get_engine()

    with engine.connect() as conn:
        growth_curves = _load_growth_curves(conn)
        potential_weights = _load_potential_weights(conn)

    if not tracked_abilities:
        tracked_abilities = [
            "contact", "power", "discipline", "eye",
            "speed", "fieldcatch", "fieldreact",
            "pendurance", "pgencontrol",
        ]

    # Filter to valid abilities
    tracked_abilities = [a for a in tracked_abilities if a in ABILITY_CLASS_MAP]

    log.info(
        "sandbox: generating %d players (age=%d, type=%s) for %d seasons",
        count, start_age, player_type, seasons,
    )

    players = _generate_synthetic_players(
        count, start_age, player_type, potential_weights, tracked_abilities,
    )

    results = _run_simulation(
        players, seasons, start_age, growth_curves, tracked_abilities,
    )

    return {
        "config": {
            "count": count,
            "seasons": seasons,
            "start_age": start_age,
            "player_type": player_type,
        },
        "tracked_abilities": tracked_abilities,
        "results": results,
    }


# ── Data loading (read-only) ──────────────────────────────────────────


def _load_growth_curves(conn):
    """Load all growth curve parameters into {(grade, age): (min, mode, max)}."""
    rows = conn.execute(
        text("SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves")
    ).mappings().all()
    curves = {}
    for r in rows:
        curves[(r["grade"], int(r["age"]))] = (
            float(r["prog_min"]),
            float(r["prog_mode"]),
            float(r["prog_max"]),
        )
    return curves


def _load_potential_weights(conn):
    """Load potential weights into {(player_type, ability_class): [(grade, weight), ...]}."""
    rows = conn.execute(
        text(
            "SELECT player_type, ability_class, grade, weight "
            "FROM potential_weights WHERE weight > 0"
        )
    ).mappings().all()
    weights = defaultdict(list)
    for r in rows:
        key = (r["player_type"], r["ability_class"])
        weights[key].append((r["grade"], float(r["weight"])))
    return dict(weights)


# ── In-memory player generation ───────────────────────────────────────


def _pick_potential_inmem(potential_weights, player_type, ability_class):
    """Pick a potential grade using in-memory weights."""
    key = (player_type, ability_class)
    options = potential_weights.get(key, [])
    if not options:
        return "F"
    grades, weights = zip(*options)
    return random.choices(grades, weights=weights, k=1)[0]


def _generate_synthetic_players(count, start_age, player_type, potential_weights, tracked_abilities):
    """Generate synthetic players in memory (no DB writes)."""
    players = []
    for _ in range(count):
        if player_type == "Both":
            ptype = random.choice(["Pitcher", "Position"])
        else:
            ptype = player_type

        abilities = {}
        for ability in tracked_abilities:
            aclass = ABILITY_CLASS_MAP.get(ability, "Ability")
            grade = _pick_potential_inmem(potential_weights, ptype, aclass)
            abilities[ability] = {"base": 0.0, "pot": grade}

        players.append({
            "ptype": ptype,
            "age": start_age,
            "abilities": abilities,
        })
    return players


# ── In-memory progression ─────────────────────────────────────────────


def _progress_ability_inmem(growth_curves, age, grade):
    """Sample progression delta using in-memory growth curves."""
    params = growth_curves.get((grade, age))
    if not params:
        return 0.0
    prog_min, prog_mode, prog_max = params

    if prog_min > prog_mode:
        prog_min = prog_mode
    if prog_mode > prog_max:
        prog_max = prog_mode

    delta = random.triangular(prog_min, prog_max, prog_mode)

    if age <= 19 and delta < -1:
        delta = -1.0

    return delta


def _run_simulation(players, seasons, start_age, growth_curves, tracked_abilities):
    """
    Run progression for N seasons and collect aggregated results
    plus per-player trajectories for individual variance analysis.

    Returns: {ability: {grade: {ages, avg, p10-p90, count, players: [{id, trajectory}]}}}
    """
    # snapshots[ability][grade][age] = [base_values...]
    snapshots = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    # per-player tracking: trajectories[ability][player_index] = {grade, values: {age: base}}
    trajectories = defaultdict(dict)

    for pi, player in enumerate(players):
        for ability in tracked_abilities:
            ab = player["abilities"][ability]
            trajectories[ability][pi] = {
                "grade": ab["pot"],
                "ptype": player["ptype"],
                "values": {},
            }

    for season in range(seasons):
        current_age = start_age + season + 1

        for pi, player in enumerate(players):
            player["age"] = current_age
            for ability in tracked_abilities:
                ab = player["abilities"][ability]

                if 16 <= current_age <= 45:
                    delta = _progress_ability_inmem(
                        growth_curves, current_age, ab["pot"],
                    )
                    ab["base"] += delta

                snapshots[ability][ab["pot"]][current_age].append(ab["base"])
                trajectories[ability][pi]["values"][current_age] = round(ab["base"], 2)

    # Aggregate into chartable data
    results = {}
    for ability in tracked_abilities:
        results[ability] = {}
        for grade in sorted(snapshots[ability].keys()):
            ages = sorted(snapshots[ability][grade].keys())
            avg_vals = []
            p10_vals = []
            p25_vals = []
            p75_vals = []
            p90_vals = []

            for age in ages:
                values = sorted(snapshots[ability][grade][age])
                n = len(values)
                if not n:
                    continue
                avg_vals.append(round(statistics.mean(values), 2))
                p10_vals.append(round(values[max(0, int(n * 0.10))], 2))
                p25_vals.append(round(values[max(0, int(n * 0.25))], 2))
                p75_vals.append(round(values[min(n - 1, int(n * 0.75))], 2))
                p90_vals.append(round(values[min(n - 1, int(n * 0.90))], 2))

            if not avg_vals:
                continue

            # Collect individual player trajectories for this grade
            grade_players = []
            for pi, tdata in trajectories[ability].items():
                if tdata["grade"] != grade:
                    continue
                traj = [tdata["values"].get(a, 0.0) for a in ages]
                grade_players.append({
                    "id": pi,
                    "ptype": tdata["ptype"],
                    "trajectory": traj,
                })

            results[ability][grade] = {
                "ages": ages,
                "avg": avg_vals,
                "p10": p10_vals,
                "p25": p25_vals,
                "p75": p75_vals,
                "p90": p90_vals,
                "count": len(grade_players),
                "players": grade_players,
            }

    return results
