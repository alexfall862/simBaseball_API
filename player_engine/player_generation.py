"""
Player generation logic.
Translates the old Player.__init__ pipeline into functions that query
the seed tables and INSERT into simbbPlayers.
"""
import random
import statistics
from sqlalchemy import text

from .constants import (
    ABILITY_CLASS_MAP,
    ALL_ABILITIES,
    PITCH_SLOTS,
    PITCH_SUB_ABILITIES,
    HANDEDNESS_OPTIONS,
    HANDEDNESS_WEIGHTS,
    ARM_ANGLE_OPTIONS,
    ARM_ANGLE_WEIGHTS,
    INJURY_RISK_OPTIONS,
    INJURY_RISK_WEIGHTS,
    DURABILITY_OPTIONS,
    DURABILITY_WEIGHTS,
    HEIGHT_MEAN,
    HEIGHT_STDDEV,
    WEIGHT_DENSITY_MEAN,
    WEIGHT_DENSITY_STDDEV,
    SPLITS_PULL_MEAN,
    SPLITS_PULL_STDDEV,
    SPLITS_PULL_MIN,
    SPLITS_PULL_MAX,
    SPLITS_CENTER_RATIO,
    SPLITS_OPPO_RATIO,
)
from .db_helpers import (
    pick_region,
    pick_city,
    pick_name,
    pick_potential,
    get_pitch_pool,
    get_extra_pitches,
    weighted_random_row,
    SeedCache,
)


def generate_player(conn, age=15, seed_cache=None, next_id=None):
    """
    Generate a complete new player and INSERT into simbbPlayers.
    Returns the new player's data as a dict.

    Args:
        conn: SQLAlchemy Core connection
        age: Starting age (default 15)
        seed_cache: Optional SeedCache for batch generation (avoids DB lookups)
        next_id: Explicit ID to assign (avoids relying on AUTO_INCREMENT)
    """
    ptype = _pick_position()

    # Location
    if seed_cache:
        region = seed_cache.pick_region()
        city_row = seed_cache.pick_city(region["id"])
    else:
        region = pick_region(conn)
        city_row = pick_city(conn, region["id"])
    if not region:
        raise RuntimeError("No regions found in seed data — is the regions table populated?")
    city = city_row["name"] if city_row else "Unknown"
    area = region["name"]
    intorusa = region["region_type"]

    # Name (uses name_pool to map US states -> "United States")
    if seed_cache:
        firstname, lastname = seed_cache.pick_name(region["name_pool"])
    else:
        firstname, lastname = pick_name(conn, region["name_pool"])

    # Physical attributes
    height = _generate_height()
    weight = _generate_weight(height)
    bat_hand, pitch_hand = _generate_handedness()
    arm_angle = _generate_arm_angle()
    injury_risk = _generate_injury_risk()
    durability = _generate_durability()

    # Splits
    left_split, center_split, right_split = _generate_splits()

    # Build the player dict with all columns
    player = {
        "ptype": ptype,
        "firstname": firstname,
        "lastname": lastname,
        "city": city,
        "area": area,
        "intorusa": intorusa,
        "age": age,
        "height": height,
        "weight": weight,
        "bat_hand": bat_hand,
        "pitch_hand": pitch_hand,
        "arm_angle": arm_angle,
        "injury_risk": injury_risk,
        "durability": durability,
        "left_split": left_split,
        "center_split": center_split,
        "right_split": right_split,
    }

    # Generate potentials for all standard abilities (base starts at 0)
    for ability_name, ability_class in ABILITY_CLASS_MAP.items():
        if seed_cache:
            pot = seed_cache.pick_potential(ptype, ability_class)
        else:
            pot = pick_potential(conn, ptype, ability_class)
        player[f"{ability_name}_base"] = 0.0
        player[f"{ability_name}_pot"] = pot

    # Generate pitch repertoire
    repertoire = _generate_pitch_repertoire(conn, seed_cache=seed_cache)
    for i, slot in enumerate(PITCH_SLOTS):
        pitch_name = repertoire[i]
        player[f"{slot}_name"] = pitch_name

        # Each pitch has 4 sub-abilities, all PitchAbility class
        sub_bases = []
        for sub in PITCH_SUB_ABILITIES:
            if seed_cache:
                pot = seed_cache.pick_potential(ptype, "PitchAbility")
            else:
                pot = pick_potential(conn, ptype, "PitchAbility")
            player[f"{slot}_{sub}_base"] = 0.0
            player[f"{slot}_{sub}_pot"] = pot
            sub_bases.append(0.0)

        # Pitch OVR = mean of sub-ability bases (all 0 at creation)
        player[f"{slot}_ovr"] = 0.0

    # Assign explicit ID if provided (table may lack AUTO_INCREMENT)
    if next_id is not None:
        player["id"] = next_id
    elif seed_cache is None:
        # Single-player generation without pre-fetched ID — compute it now
        max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM simbbPlayers")).scalar()
        player["id"] = max_id + 1

    # INSERT into simbbPlayers
    columns = ", ".join(player.keys())
    placeholders = ", ".join(f":{k}" for k in player.keys())
    conn.execute(
        text(f"INSERT INTO simbbPlayers ({columns}) VALUES ({placeholders})"),
        player,
    )

    return player


def generate_players(conn, count, age=15):
    """Generate multiple players. Preloads seed data for batch performance."""
    cache = SeedCache(conn)
    # Pre-fetch the next available ID so we don't rely on AUTO_INCREMENT
    max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM simbbPlayers")).scalar()
    next_id = max_id + 1
    players = []
    for _ in range(count):
        p = generate_player(conn, age=age, seed_cache=cache, next_id=next_id)
        next_id = p["id"] + 1
        players.append(p)
    return players


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------

def _pick_position():
    """50/50 Pitcher vs Position."""
    return random.choice(["Pitcher", "Position"])


def _generate_height():
    """Normal distribution: mean=72 inches, stddev=7/3."""
    return int(round(random.gauss(HEIGHT_MEAN, HEIGHT_STDDEV)))


def _generate_weight(height):
    """Weight derived from height with density factor: N(2.8, 0.8/3)."""
    density = random.gauss(WEIGHT_DENSITY_MEAN, WEIGHT_DENSITY_STDDEV)
    return int(round(height * density))


def _generate_handedness():
    """Weighted random: (bat_hand, pitch_hand)."""
    return random.choices(HANDEDNESS_OPTIONS, HANDEDNESS_WEIGHTS, k=1)[0]


def _generate_arm_angle():
    """Weighted random arm angle."""
    return random.choices(ARM_ANGLE_OPTIONS, ARM_ANGLE_WEIGHTS, k=1)[0]


def _generate_injury_risk():
    """Weighted random injury risk tier."""
    return random.choices(INJURY_RISK_OPTIONS, INJURY_RISK_WEIGHTS, k=1)[0]


def _generate_durability():
    """Weighted random durability tier."""
    return random.choices(DURABILITY_OPTIONS, DURABILITY_WEIGHTS, k=1)[0]


def _generate_splits():
    """
    Generate pull/center/oppo split percentages.
    Pull% from N(40, 10) clamped to [25, 55].
    Center and oppo derived from remaining percentage.
    """
    pull = round(max(min(random.gauss(SPLITS_PULL_MEAN, SPLITS_PULL_STDDEV),
                         SPLITS_PULL_MAX), SPLITS_PULL_MIN), 1)
    remainder = 100 - pull
    value_one = remainder * SPLITS_CENTER_RATIO
    value_two = remainder * SPLITS_OPPO_RATIO

    if value_two > pull:
        center = round(value_two, 1)
        oppo = round(value_one, 1)
    else:
        center = round(value_one, 1)
        oppo = round(value_two, 1)

    return pull, center, oppo


def _generate_pitch_repertoire(conn, seed_cache=None):
    """
    Build a 5-pitch repertoire:
      Slot 1: Fastball pool
      Slot 2: Off-speed pool
      Slot 3: Breaking pool
      Slots 4-5: Weighted random from remaining types
    Returns list of 5 pitch type names.
    """
    pitches = []

    # Slots 1-3 from their assigned pools
    for pool_num in [1, 2, 3]:
        if seed_cache:
            pool = seed_cache.get_pitch_pool(pool_num)
            weights = seed_cache.get_pitch_pool_weights(pool_num)
        else:
            pool = get_pitch_pool(conn, pool_num)
            weights = [p["weight"] for p in pool]
        if not pool:
            raise RuntimeError(f"No pitch types found for pool {pool_num} — is the pitch_types table populated?")
        chosen = random.choices(pool, weights, k=1)[0]
        pitches.append(chosen["name"])

    # Slots 4-5 from remaining pitch types
    for _ in range(2):
        if seed_cache:
            available = seed_cache.get_extra_pitches(pitches)
        else:
            available = get_extra_pitches(conn, pitches)
        if not available:
            break
        chosen = random.choices(
            available, [p["extra_weight"] if "extra_weight" in p else p["weight"] for p in available], k=1
        )[0]
        pitches.append(chosen["name"])

    return pitches
