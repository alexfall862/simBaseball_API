"""
Player progression logic.

Once per end-season every player ages one year and each progressed value
(19 abilities + 5 pitches x 4 sub-abilities) moves by a delta drawn from
``growth_curves`` keyed by (potential grade, age):

  1. (min, mode, max) for the attribute's potential grade at the new age
  2. an independent triangular draw per attribute (attributes are specific
     and their dice are unrelated, by design)
  3. age <= 19 floors the delta at -1
  4. base += delta; pitch OVRs are recomputed from the sub-abilities

Training camp (``services/training_camp``) can hand in ``grade_overrides``:
{player_id: {pot_column: effective_grade}} used for this pass only; the
stored potentials never change.

Players older than the table's last age (``MAX(growth_curves.age)``) only
age; nothing retires anyone here.
"""
import logging
import random
import statistics
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

from .constants import ALL_ABILITIES, PITCH_SLOTS, PITCH_SUB_ABILITIES

log = logging.getLogger(__name__)

YOUNG_FLOOR_AGE = 19
YOUNG_FLOOR = -1.0

GrowthParams = Tuple[float, float, float]          # (min, mode, max)
GrowthCache = Dict[Tuple[str, int], GrowthParams]


# ---------------------------------------------------------------------------
# Pure helpers (also used by the sandbox and the diagnostics)
# ---------------------------------------------------------------------------

def load_growth_cache(conn) -> GrowthCache:
    rows = conn.execute(
        text("SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves")
    ).all()
    return {(r[0], int(r[1])): (float(r[2]), float(r[3]), float(r[4])) for r in rows}


def table_age_range(cache: GrowthCache) -> Tuple[int, int]:
    ages = [age for (_g, age) in cache]
    if not ages:
        return (16, 45)
    return (min(ages), max(ages))


def sample_delta(params: GrowthParams, age: int, rng=random) -> float:
    """One attribute's yearly delta: an independent triangular draw from the
    table row, with the under-20 floor."""
    prog_min, prog_mode, prog_max = params
    if prog_min > prog_mode:
        prog_min = prog_mode
    if prog_mode > prog_max:
        prog_max = prog_mode
    delta = rng.triangular(prog_min, prog_max, prog_mode)
    if age <= YOUNG_FLOOR_AGE and delta < YOUNG_FLOOR:
        delta = YOUNG_FLOOR
    return delta


def _confine(value):
    """Round a base value to the nearest integer (display value)."""
    return int(round(value, 0))


def _progress_row(player, new_age: int, cache: GrowthCache,
                  overrides: Optional[Dict[str, str]],
                  rng=random) -> Dict[str, Any]:
    """Compute the UPDATE map for one player (age already incremented)."""
    updates: Dict[str, Any] = {"age": new_age}
    overrides = overrides or {}

    def grade_for(pot_col: str) -> Optional[str]:
        g = overrides.get(pot_col) or player[pot_col]
        return g if g else None

    for ability in ALL_ABILITIES:
        base_col = f"{ability}_base"
        pot_col = f"{ability}_pot"
        grade = grade_for(pot_col)
        if not grade:
            continue
        params = cache.get((grade, new_age))
        if not params:
            continue
        current = player[base_col] or 0.0
        updates[base_col] = current + sample_delta(params, new_age, rng)

    for slot in PITCH_SLOTS:
        sub_displays = []
        for sub in PITCH_SUB_ABILITIES:
            base_col = f"{slot}_{sub}_base"
            pot_col = f"{slot}_{sub}_pot"
            current = player[base_col] or 0.0
            grade = grade_for(pot_col)
            params = cache.get((grade, new_age)) if grade else None
            if params:
                new_base = current + sample_delta(params, new_age, rng)
                updates[base_col] = new_base
                sub_displays.append(_confine(new_base))
            else:
                sub_displays.append(_confine(current))
        updates[f"{slot}_ovr"] = round(statistics.mean(sub_displays), 2)
    return updates


def _write_updates(conn, player_id: int, updates: Dict[str, Any]) -> None:
    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    params = dict(updates)
    params["pid"] = player_id
    conn.execute(text(f"UPDATE simbbPlayers SET {set_clause} WHERE id = :pid"), params)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def progress_player(conn, player_id, grade_overrides: Optional[Dict[str, str]] = None):
    """Age one player by a year and progress every attribute."""
    player = conn.execute(
        text("SELECT * FROM simbbPlayers WHERE id = :pid"), {"pid": player_id}
    ).mappings().first()
    if not player:
        return
    cache = load_growth_cache(conn)
    min_age, max_age = table_age_range(cache)
    new_age = int(player["age"]) + 1
    if new_age < min_age or new_age > max_age:
        _write_updates(conn, player_id, {"age": new_age})
        return
    updates = _progress_row(player, new_age, cache, grade_overrides)
    _write_updates(conn, player_id, updates)


def progress_all_players(conn, max_age: Optional[int] = None,
                         grade_overrides: Optional[Dict[int, Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Age every player by one year and progress those inside the growth table's
    age range. Players above the table's last age only age.

    ``max_age``: if given, players at or above it are left untouched (legacy
    knob for the admin endpoint). ``grade_overrides``: training-camp
    effective grades for this pass.

    Returns {"progressed", "aged_only", "camp_players", "table_age_max"}.
    """
    overrides = grade_overrides or {}
    cache = load_growth_cache(conn)
    min_table_age, max_table_age = table_age_range(cache)
    log.info("progress_all_players: %d growth_curve entries, ages %d-%d",
             len(cache), min_table_age, max_table_age)

    if max_age is not None:
        players = conn.execute(
            text("SELECT * FROM simbbPlayers WHERE age < :max_age"), {"max_age": int(max_age)}
        ).mappings().all()
    else:
        players = conn.execute(text("SELECT * FROM simbbPlayers")).mappings().all()

    progressed = aged_only = camp_players = 0
    for player in players:
        pid = int(player["id"])
        new_age = int(player["age"] or 0) + 1
        if new_age < min_table_age or new_age > max_table_age:
            _write_updates(conn, pid, {"age": new_age})
            aged_only += 1
            continue
        ov = overrides.get(pid)
        if ov:
            camp_players += 1
        updates = _progress_row(player, new_age, cache, ov)
        _write_updates(conn, pid, updates)
        progressed += 1

    log.info("progress_all_players: progressed %d, aged only %d, camp %d",
             progressed, aged_only, camp_players)
    return {
        "progressed": progressed,
        "aged_only": aged_only,
        "camp_players": camp_players,
        "table_age_max": max_table_age,
    }
