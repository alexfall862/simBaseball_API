"""
Template-based scouting text report generation.

Each report covers batting, fielding, pitching (if pitcher), and athletic
profiles. Generated deterministically from player attributes — no DB storage.

Reports are 50-100 characters per section, designed for the HS scouting
tier (Action 1 unlock for college orgs scouting HS players).
"""


def _attr_tier(value, cap):
    """Map a raw attribute to a scouting descriptor tier."""
    ratio = (value or 0) / max(cap, 1)
    if ratio >= 0.80:
        return "elite"
    if ratio >= 0.60:
        return "plus"
    if ratio >= 0.40:
        return "solid"
    if ratio >= 0.25:
        return "developing"
    if ratio >= 0.10:
        return "raw"
    return "limited"


# -- Batting report templates --

_BATTING_TEMPLATES = {
    "elite":      "Exceptional bat speed and barrel control. Projects as a {power_desc} hitter.",
    "plus":       "Advanced swing mechanics with {power_desc} raw power. Quick hands.",
    "solid":      "Solid contact ability with {power_desc} pop. Developing approach.",
    "developing": "Shows flashes of contact ability. Bat speed is {power_desc}.",
    "raw":        "Very raw at the plate. Swing needs significant refinement.",
    "limited":    "Minimal offensive development so far. Projects as a bat-last player.",
}

_POWER_DESCRIPTORS = {
    "elite": "plus-plus",
    "plus": "plus",
    "solid": "average",
    "developing": "below-average",
    "raw": "limited",
    "limited": "well below-average",
}


# -- Fielding report templates --

_FIELDING_TEMPLATES = {
    "elite":      "Gold glove caliber defender. {arm_desc} arm. Instinctive routes.",
    "plus":       "Above-average defender with {arm_desc} arm. Sure hands.",
    "solid":      "Reliable glove with {arm_desc} arm strength. Adequate range.",
    "developing": "Developing defender. {arm_desc} arm accuracy. Needs reps.",
    "raw":        "Below-average defender. Rough around the edges in the field.",
    "limited":    "Defensive liability at this stage. Needs major development.",
}

_ARM_DESCRIPTORS = {
    "elite": "Cannon",
    "plus": "Strong",
    "solid": "Average",
    "developing": "Below-average",
    "raw": "Fringe",
    "limited": "Weak",
}


# -- Pitching report templates --

_PITCHING_TEMPLATES = {
    "elite":      "Electric stuff. Dominant {velocity_desc} with {control_desc} command.",
    "plus":       "Plus arm with {velocity_desc} velocity. {control_desc} zone control.",
    "solid":      "Solid repertoire. {velocity_desc} and {control_desc} command.",
    "developing": "Arm strength is {velocity_desc}. Command is {control_desc}.",
    "raw":        "Raw arm. Stuff is {velocity_desc} with {control_desc} control.",
    "limited":    "Limited pitchability. Needs significant mechanical work.",
}

_VELOCITY_DESCRIPTORS = {
    "elite": "explosive fastball",
    "plus": "lively fastball",
    "solid": "average velocity",
    "developing": "fringe velocity",
    "raw": "below-average velocity",
    "limited": "soft velocity",
}

_CONTROL_DESCRIPTORS = {
    "elite": "pinpoint",
    "plus": "above-average",
    "solid": "adequate",
    "developing": "inconsistent",
    "raw": "erratic",
    "limited": "poor",
}


# -- Athletic profile templates --

_ATHLETIC_TEMPLATES = {
    "elite":      "Premium athlete. {speed_desc} runner with explosive first step.",
    "plus":       "Good athlete. {speed_desc} speed and above-average agility.",
    "solid":      "Average athlete. {speed_desc} on the bases.",
    "developing": "Below-average athleticism. {speed_desc} runner.",
    "raw":        "Limited athlete. Below-average foot speed.",
    "limited":    "Poor athleticism. Well below-average runner.",
}

_SPEED_DESCRIPTORS = {
    "elite": "Plus-plus",
    "plus": "Plus",
    "solid": "Average",
    "developing": "Below-average",
    "raw": "Well below-average",
    "limited": "Poor",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_text_report(player, level):
    """
    Generate a template-based text scouting report from attributes.

    Args:
        player: dict from simbbPlayers row
        level: 'hs', 'college', or 'intam'

    Returns:
        dict with 'batting', 'fielding', 'athletic', and optionally 'pitching'
        keys — each a string of ~50-100 characters.
    """
    cap = {"hs": 25, "college": 50, "intam": 50}.get(level, 25)
    ptype = player.get("ptype", "Position")

    report = {}

    # Batting profile
    contact_tier = _attr_tier(player.get("contact_base", 0), cap)
    power_tier = _attr_tier(player.get("power_base", 0), cap)
    tmpl = _BATTING_TEMPLATES[contact_tier]
    report["batting"] = tmpl.format(power_desc=_POWER_DESCRIPTORS[power_tier])

    # Fielding profile
    field_avg = (
        (player.get("fieldcatch_base", 0) or 0)
        + (player.get("fieldreact_base", 0) or 0)
        + (player.get("fieldspot_base", 0) or 0)
    ) / 3
    field_tier = _attr_tier(field_avg, cap)
    arm_tier = _attr_tier(player.get("throwacc_base", 0), cap)
    report["fielding"] = _FIELDING_TEMPLATES[field_tier].format(
        arm_desc=_ARM_DESCRIPTORS[arm_tier]
    )

    # Pitching profile (pitchers only)
    if ptype == "Pitcher":
        velo_tier = _attr_tier(player.get("pthrowpower_base", 0), cap)
        ctrl_tier = _attr_tier(player.get("pgencontrol_base", 0), cap)
        pitch_avg = (
            (player.get("pthrowpower_base", 0) or 0)
            + (player.get("pgencontrol_base", 0) or 0)
            + (player.get("psequencing_base", 0) or 0)
        ) / 3
        pitch_tier = _attr_tier(pitch_avg, cap)
        report["pitching"] = _PITCHING_TEMPLATES[pitch_tier].format(
            velocity_desc=_VELOCITY_DESCRIPTORS[velo_tier],
            control_desc=_CONTROL_DESCRIPTORS[ctrl_tier],
        )

    # Athletic profile
    speed_tier = _attr_tier(player.get("speed_base", 0), cap)
    ath_avg = (
        (player.get("speed_base", 0) or 0)
        + (player.get("baserunning_base", 0) or 0)
    ) / 2
    ath_tier = _attr_tier(ath_avg, cap)
    report["athletic"] = _ATHLETIC_TEMPLATES[ath_tier].format(
        speed_desc=_SPEED_DESCRIPTORS[speed_tier]
    )

    return report
