"""
Ability classification and static weight tables that don't need DB lookups.
These map directly to the old Player.py ability classes and generator weights.
"""

# Maps each player ability column prefix -> the ability_class used for
# potential_weights lookups in the DB.
ABILITY_CLASS_MAP = {
    # Ability (general batting/fielding/athletic)
    "contact": "Ability",
    "power": "Ability",
    "discipline": "Ability",
    "eye": "Ability",
    "basereaction": "Ability",
    "baserunning": "Ability",
    "speed": "Ability",
    "fieldcatch": "Ability",
    "fieldreact": "Ability",
    "fieldspot": "Ability",
    # ThrowAbility
    "throwpower": "ThrowAbility",
    "throwacc": "ThrowAbility",
    "pthrowpower": "ThrowAbility",
    # CatchAbility
    "catchframe": "CatchAbility",
    "catchsequence": "CatchAbility",
    # PitchAbility
    "pendurance": "PitchAbility",
    "pgencontrol": "PitchAbility",
    "pickoff": "PitchAbility",
    "psequencing": "PitchAbility",
}

# All standard ability column prefixes (non-pitch)
ALL_ABILITIES = list(ABILITY_CLASS_MAP.keys())

# Pitch slots and their sub-ability suffixes
PITCH_SLOTS = ["pitch1", "pitch2", "pitch3", "pitch4", "pitch5"]
PITCH_SUB_ABILITIES = ["pacc", "pcntrl", "pbrk", "consist"]

# Handedness options: (bat_hand, pitch_hand) with weights
HANDEDNESS_OPTIONS = [
    ("L", "L"),
    ("R", "R"),
    ("L", "R"),
    ("R", "L"),
    ("S", "L"),
    ("S", "R"),
]
HANDEDNESS_WEIGHTS = [20, 60, 5, 5, 5, 5]

# Arm angle options with weights
ARM_ANGLE_OPTIONS = ["3/4's", "Overhead", "Sidearm", "Submarine"]
ARM_ANGLE_WEIGHTS = [4, 4, 1, 0.25]

# Injury risk tiers with weights
INJURY_RISK_OPTIONS = ["Safe", "Dependable", "Normal", "Risky", "Volatile"]
INJURY_RISK_WEIGHTS = [0.025, 0.1, 0.75, 0.1, 0.025]

# Durability tiers with weights
DURABILITY_OPTIONS = ["Iron Man", "Dependable", "Normal", "Undependable", "Tires Easily"]
DURABILITY_WEIGHTS = [0.025, 0.1, 0.75, 0.1, 0.025]

# Height/weight distribution parameters
HEIGHT_MEAN = 72      # inches
HEIGHT_STDDEV = 7 / 3
WEIGHT_DENSITY_MEAN = 2.8
WEIGHT_DENSITY_STDDEV = 0.8 / 3

# Splits generation parameters
SPLITS_PULL_MEAN = 40
SPLITS_PULL_STDDEV = 10
SPLITS_PULL_MIN = 25
SPLITS_PULL_MAX = 55
SPLITS_CENTER_RATIO = 4.08 / 7
SPLITS_OPPO_RATIO = 2.92 / 7
