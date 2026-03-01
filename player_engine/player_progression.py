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
    """
    result = conn.execute(
        text("SELECT id FROM simbbPlayers WHERE age < :max_age"),
        {"max_age": max_age},
    )
    player_ids = [row["id"] for row in result.mappings().all()]

    for pid in player_ids:
        progress_player(conn, pid)

    return len(player_ids)


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
