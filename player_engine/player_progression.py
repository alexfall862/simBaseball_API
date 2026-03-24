"""
Player progression logic.
Translates the old ProgressAbility pipeline into functions that query
growth_curves and UPDATE simbbPlayers.
"""
import random
import statistics
from sqlalchemy import text

from .constants import ALL_ABILITIES, PITCH_SLOTS, PITCH_SUB_ABILITIES
from .db_helpers import get_growth_params


def progress_player(conn, player_id):
    """
    Age a player by 1 year and apply progression to all abilities.

    For each ability:
      1. Look up (grade, age) in growth_curves -> (min, mode, max)
      2. Sample delta from triangular(min, mode, max)
      3. Apply age-based floor (age <= 19: delta >= -1)
      4. base += delta

    Also recalculates pitch OVR values (mean of 4 sub-ability bases, rounded).

    Args:
        conn: SQLAlchemy Core connection
        player_id: ID in simbbPlayers
    """
    # Fetch the player's current state
    result = conn.execute(
        text("SELECT * FROM simbbPlayers WHERE id = :pid"),
        {"pid": player_id},
    )
    player = result.mappings().first()
    if not player:
        return

    new_age = player["age"] + 1

    # If the player is outside growth table range (16-45), just age them
    if new_age < 16 or new_age > 45:
        conn.execute(
            text("UPDATE simbbPlayers SET age = :age WHERE id = :pid"),
            {"age": new_age, "pid": player_id},
        )
        return

    updates = {"age": new_age}

    # Progress all standard abilities
    for ability in ALL_ABILITIES:
        base_col = f"{ability}_base"
        pot_col = f"{ability}_pot"
        current_base = player[base_col] or 0.0
        grade = player[pot_col]
        if grade:
            delta = _yearly_progression(conn, new_age, grade)
            updates[base_col] = current_base + delta

    # Progress all pitch sub-abilities and recalculate OVR
    for slot in PITCH_SLOTS:
        sub_displays = []
        for sub in PITCH_SUB_ABILITIES:
            base_col = f"{slot}_{sub}_base"
            pot_col = f"{slot}_{sub}_pot"
            current_base = player[base_col] or 0.0
            grade = player[pot_col]
            if grade:
                delta = _yearly_progression(conn, new_age, grade)
                new_base = current_base + delta
                updates[base_col] = new_base
                sub_displays.append(_confine(new_base))
            else:
                sub_displays.append(_confine(current_base))

        # Pitch OVR = mean of the 4 confined sub-ability values
        updates[f"{slot}_ovr"] = round(statistics.mean(sub_displays), 2)

    # Build and execute the UPDATE
    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    updates["pid"] = player_id
    conn.execute(
        text(f"UPDATE simbbPlayers SET {set_clause} WHERE id = :pid"),
        updates,
    )


def progress_all_players(conn, max_age=45):
    """
    Progress every active player in simbbPlayers.
    Players at or above max_age are skipped (handle retirement separately).
    Returns the number of players progressed.

    Uses bulk queries: preloads the entire growth_curves table and all
    player rows, computes deltas in Python, then writes updates in
    chunked batches.  This replaces ~200k individual DB queries with ~5.
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. Preload entire growth_curves table into memory (~600 rows)
    gc_rows = conn.execute(
        text("SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves")
    ).all()
    growth_cache = {}
    for r in gc_rows:
        growth_cache[(r[0], int(r[1]))] = (float(r[2]), float(r[3]), float(r[4]))
    logger.info("progress_all_players: loaded %d growth_curve entries", len(growth_cache))

    # 2. Bulk-load all eligible players
    players = conn.execute(
        text("SELECT * FROM simbbPlayers WHERE age < :max_age"),
        {"max_age": max_age},
    ).mappings().all()

    if not players:
        return 0

    logger.info("progress_all_players: progressing %d players", len(players))

    # Helper: sample delta using cached growth params (no DB call)
    def _sample_delta(age, grade):
        params = growth_cache.get((grade, age))
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

    # 3. Compute updates for all players in Python
    _CHUNK_SIZE = 200
    total_progressed = 0

    for chunk_start in range(0, len(players), _CHUNK_SIZE):
        chunk = players[chunk_start:chunk_start + _CHUNK_SIZE]
        for player in chunk:
            player_id = player["id"]
            new_age = player["age"] + 1

            if new_age < 16 or new_age > 45:
                # Outside growth range — just age
                conn.execute(
                    text("UPDATE simbbPlayers SET age = :age WHERE id = :pid"),
                    {"age": new_age, "pid": player_id},
                )
                total_progressed += 1
                continue

            updates = {"age": new_age}

            # Standard abilities
            for ability in ALL_ABILITIES:
                base_col = f"{ability}_base"
                pot_col = f"{ability}_pot"
                current_base = player[base_col] or 0.0
                grade = player[pot_col]
                if grade:
                    delta = _sample_delta(new_age, grade)
                    updates[base_col] = current_base + delta

            # Pitch sub-abilities and OVR recalc
            for slot in PITCH_SLOTS:
                sub_displays = []
                for sub in PITCH_SUB_ABILITIES:
                    base_col = f"{slot}_{sub}_base"
                    pot_col = f"{slot}_{sub}_pot"
                    current_base = player[base_col] or 0.0
                    grade = player[pot_col]
                    if grade:
                        delta = _sample_delta(new_age, grade)
                        new_base = current_base + delta
                        updates[base_col] = new_base
                        sub_displays.append(_confine(new_base))
                    else:
                        sub_displays.append(_confine(current_base))
                updates[f"{slot}_ovr"] = round(statistics.mean(sub_displays), 2)

            # Execute UPDATE for this player
            set_clause = ", ".join(f"{col} = :{col}" for col in updates)
            updates["pid"] = player_id
            conn.execute(
                text(f"UPDATE simbbPlayers SET {set_clause} WHERE id = :pid"),
                updates,
            )
            total_progressed += 1

    logger.info("progress_all_players: completed %d players", total_progressed)
    return total_progressed


def _yearly_progression(conn, age, grade):
    """
    Sample a single year's progression delta for a given age and potential grade.
    Uses triangular distribution with parameters from growth_curves table.
    Applies age-based floor: age <= 19 clamps delta to >= -1.
    """
    prog_min, prog_mode, prog_max = get_growth_params(conn, grade, age)

    # triangular requires left <= mode <= right
    # The growth table data guarantees this, but guard against edge cases
    if prog_min > prog_mode:
        prog_min = prog_mode
    if prog_mode > prog_max:
        prog_max = prog_mode

    delta = random.triangular(prog_min, prog_max, prog_mode)

    # Age-based floor: young players don't regress much
    if age <= 19 and delta < -1:
        delta = -1.0

    return delta


def _confine(value):
    """Round a base value to the nearest integer (display value)."""
    return int(round(value, 0))
