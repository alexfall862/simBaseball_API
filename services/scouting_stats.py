"""
Deterministic stat generation from player attributes.

Uses player ID as random seed so the same player always produces the same
stat line. No DB dependency — pure functions operating on player dicts.

Stats are scaled by level (HS/college/INTAM) with level-appropriate season
lengths and attribute caps.
"""

import random

# Level-specific season parameters
LEVEL_PARAMS = {
    "hs": {
        "games": 28,
        "ab_per_game": 3.2,
        "ip_per_start": 5.0,
        "starts": 15,
        "attr_cap": 25,
    },
    "college": {
        "games": 56,
        "ab_per_game": 3.8,
        "ip_per_start": 5.5,
        "starts": 16,
        "attr_cap": 50,
    },
    "intam": {
        "games": 50,
        "ab_per_game": 3.6,
        "ip_per_start": 5.0,
        "starts": 15,
        "attr_cap": 50,
    },
}


def _norm(val, cap):
    """Normalize a raw attribute value into [0, 1] given the level cap."""
    return max(0.0, min(1.0, (val or 0) / max(cap, 1)))


# ---------------------------------------------------------------------------
# Position player batting
# ---------------------------------------------------------------------------

def _generate_batting(player, level, rng):
    """
    Generate a full-season batting line.

    Attribute mapping:
        contact_base    -> AVG
        discipline_base -> BB%
        eye_base        -> K% (inverse — higher eye = fewer K)
        power_base      -> HR%, doubles, ISO
        speed_base      -> SB, triples
    """
    p = LEVEL_PARAMS[level]
    cap = p["attr_cap"]
    games = p["games"]

    contact = _norm(player.get("contact_base", 0), cap)
    power = _norm(player.get("power_base", 0), cap)
    disc = _norm(player.get("discipline_base", 0), cap)
    eye = _norm(player.get("eye_base", 0), cap)
    speed = _norm(player.get("speed_base", 0), cap)

    total_ab = int(games * p["ab_per_game"])

    # Walk rate: 3% base + 15% * discipline
    bb_rate = 0.03 + 0.15 * disc
    walks = max(0, int(total_ab * bb_rate + rng.gauss(0, 1)))

    hbp = rng.randint(0, max(1, int(total_ab * 0.01)))
    pa = total_ab + walks + hbp

    # AVG: .150 base + .250 * contact (range ~.150-.400)
    avg = 0.150 + 0.250 * contact + rng.gauss(0, 0.020)
    avg = max(0.080, min(0.500, avg))
    hits = max(0, int(total_ab * avg))

    # K rate: 35% base - 20% * eye
    k_rate = max(0.05, min(0.45, 0.35 - 0.20 * eye))
    strikeouts = max(0, int(total_ab * k_rate + rng.gauss(0, 1)))

    # HR rate: 0.5% base + 5% * power
    hr_rate = 0.005 + 0.05 * power
    home_runs = max(0, int(total_ab * hr_rate + rng.gauss(0, 0.5)))

    # Doubles: 4% base + 6% * (contact*0.6 + power*0.4)
    dbl_rate = 0.04 + 0.06 * (contact * 0.6 + power * 0.4)
    doubles = max(0, int(total_ab * dbl_rate + rng.gauss(0, 0.5)))

    # Triples: rare, speed-influenced
    triples = max(0, int(total_ab * (0.005 + 0.015 * speed) + rng.gauss(0, 0.3)))

    # Ensure hits >= extra-base hits
    extra_base = home_runs + doubles + triples
    if extra_base > hits:
        hits = extra_base + rng.randint(1, 4)

    singles = hits - doubles - triples - home_runs

    # RBI
    rbi = max(0, int(home_runs * 2.5 + (hits - home_runs) * 0.35 + rng.gauss(0, 3)))

    # Runs
    runs = max(0, int(hits * 0.45 + walks * 0.30 + speed * games * 0.08 + rng.gauss(0, 2)))

    # Stolen bases
    sb = max(0, int(speed * games * 0.15 + rng.gauss(0, 2)))
    cs = max(0, int(sb * (0.35 - 0.15 * speed) + rng.gauss(0, 0.5)))

    computed_avg = round(hits / max(total_ab, 1), 3)
    computed_obp = round((hits + walks + hbp) / max(pa, 1), 3)
    computed_slg = round(
        (singles + doubles * 2 + triples * 3 + home_runs * 4) / max(total_ab, 1), 3
    )

    return {
        "games": games,
        "at_bats": total_ab,
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "home_runs": home_runs,
        "rbi": rbi,
        "runs": runs,
        "walks": walks,
        "strikeouts": strikeouts,
        "stolen_bases": sb,
        "caught_stealing": cs,
        "avg": computed_avg,
        "obp": computed_obp,
        "slg": computed_slg,
    }


# ---------------------------------------------------------------------------
# Pitcher stats
# ---------------------------------------------------------------------------

def _generate_pitching(player, level, rng):
    """
    Generate a full-season pitching line.

    Attribute mapping:
        pgencontrol_base  -> BB/9, WHIP
        psequencing_base  -> ERA, H/9
        pthrowpower_base  -> K/9
        pendurance_base   -> IP/start
        pitch1-3 OVR avg  -> overall effectiveness modifier
    """
    p = LEVEL_PARAMS[level]
    cap = p["attr_cap"]
    starts = p["starts"]

    control = _norm(player.get("pgencontrol_base", 0), cap)
    sequencing = _norm(player.get("psequencing_base", 0), cap)
    velocity = _norm(player.get("pthrowpower_base", 0), cap)
    endurance = _norm(player.get("pendurance_base", 0), cap)

    # Average pitch quality from top 3 pitches
    pitch_ovrs = [float(player.get(f"pitch{i}_ovr", 0) or 0) for i in range(1, 4)]
    pitch_quality = _norm(sum(pitch_ovrs) / max(len(pitch_ovrs), 1), cap)

    # IP per start: base + 2.0 * endurance
    ip_per = p["ip_per_start"] + 2.0 * endurance
    total_ip = max(starts * 2.0, starts * ip_per + rng.gauss(0, 2))

    # K/9: 3 + 9 * velocity
    k9 = max(2.0, min(14.0, 3.0 + 9.0 * velocity + rng.gauss(0, 0.5)))
    strikeouts = max(0, int(total_ip * k9 / 9))

    # BB/9: 7 - 5 * control
    bb9 = max(1.0, min(9.0, 7.0 - 5.0 * control + rng.gauss(0, 0.3)))
    walks = max(0, int(total_ip * bb9 / 9))

    # H/9: 12 - 5 * (sequencing*0.6 + pitch_quality*0.4)
    h9 = max(5.0, min(14.0, 12.0 - 5.0 * (sequencing * 0.6 + pitch_quality * 0.4) + rng.gauss(0, 0.5)))
    hits_allowed = max(0, int(total_ip * h9 / 9))

    # ERA: 8 - 6 * (sequencing*0.4 + control*0.3 + pitch_quality*0.3)
    era = max(1.50, min(10.0, 8.0 - 6.0 * (sequencing * 0.4 + control * 0.3 + pitch_quality * 0.3) + rng.gauss(0, 0.5)))
    earned_runs = max(0, int(total_ip * era / 9))

    # HR allowed
    hr_allowed = max(0, int(total_ip * (1.8 - 1.2 * pitch_quality) / 9))

    runs_allowed = earned_runs + rng.randint(0, max(1, int(earned_runs * 0.15)))

    # W-L from ERA
    era_norm = max(0.0, min(1.0, (era - 2.0) / 6.0))
    win_pct = max(0.10, min(0.85, 0.30 + 0.40 * (1 - era_norm) + rng.gauss(0, 0.05)))
    decisions = int(starts * 0.70)
    wins = int(decisions * win_pct)
    losses = decisions - wins

    ip_display = round(total_ip, 1)
    total_outs = int(total_ip * 3)

    return {
        "games": starts,
        "games_started": starts,
        "wins": wins,
        "losses": losses,
        "era": round(era, 2),
        "innings_pitched": ip_display,
        "innings_pitched_outs": total_outs,
        "hits_allowed": hits_allowed,
        "runs_allowed": runs_allowed,
        "earned_runs": earned_runs,
        "walks": walks,
        "strikeouts": strikeouts,
        "home_runs_allowed": hr_allowed,
        "saves": 0,
        "k_per_9": round(k9, 1),
        "bb_per_9": round(bb9, 1),
        "whip": round((hits_allowed + walks) / max(total_ip, 1), 2),
    }


# ---------------------------------------------------------------------------
# Fielding stats
# ---------------------------------------------------------------------------

def _generate_fielding(player, level, rng):
    """
    Generate a full-season fielding line.

    Attribute mapping:
        fieldcatch_base -> putouts
        fieldreact_base -> assists (range)
        fieldspot_base  -> error avoidance (positioning)
        throwacc_base   -> error avoidance (throwing)
    """
    p = LEVEL_PARAMS[level]
    cap = p["attr_cap"]
    games = p["games"]

    catching = _norm(player.get("fieldcatch_base", 0), cap)
    reaction = _norm(player.get("fieldreact_base", 0), cap)
    spot = _norm(player.get("fieldspot_base", 0), cap)
    throw_acc = _norm(player.get("throwacc_base", 0), cap)

    innings = int(games * 6.5)

    # Putouts: 2-5 per game
    putouts = max(0, int(games * (2.0 + 3.0 * catching) + rng.gauss(0, 3)))

    # Assists: 1-4 per game
    assists = max(0, int(games * (1.0 + 3.0 * reaction) + rng.gauss(0, 2)))

    # Errors: inversely related to fielding skills
    combined = spot * 0.4 + catching * 0.3 + throw_acc * 0.3
    errors = max(0, int(games * (0.4 - 0.35 * combined) + rng.gauss(0, 1.5)))

    total_chances = putouts + assists + errors
    fpct = round((putouts + assists) / max(total_chances, 1), 3)

    return {
        "games": games,
        "innings": innings,
        "putouts": putouts,
        "assists": assists,
        "errors": errors,
        "fielding_pct": fpct,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_scouting_stats(player, level):
    """
    Generate a complete deterministic season stat line for a player.

    Uses player['id'] as the random seed — same player always produces
    the same stats.

    Args:
        player: dict from simbbPlayers row
        level: 'hs', 'college', or 'intam'

    Returns:
        dict with 'batting' and/or 'pitching' and 'fielding' sub-dicts
    """
    player_id = player.get("id", 0)
    rng = random.Random(player_id)

    ptype = player.get("ptype", "Position")
    result = {}

    if ptype == "Position":
        result["batting"] = _generate_batting(player, level, rng)
        result["fielding"] = _generate_fielding(player, level, rng)
    else:
        result["pitching"] = _generate_pitching(player, level, rng)
        # Pitchers also bat in amateur ball — scaled-down line
        bat_rng = random.Random(player_id + 100000)
        batting = _generate_batting(player, level, bat_rng)
        batting["at_bats"] = int(batting["at_bats"] * 0.3)
        batting["hits"] = int(batting["hits"] * 0.2)
        batting["home_runs"] = max(0, int(batting["home_runs"] * 0.1))
        batting["doubles"] = max(0, int(batting["doubles"] * 0.2))
        batting["triples"] = max(0, int(batting["triples"] * 0.2))
        singles = batting["hits"] - batting["doubles"] - batting["triples"] - batting["home_runs"]
        singles = max(0, singles)
        batting["rbi"] = max(0, int(batting["rbi"] * 0.2))
        batting["runs"] = max(0, int(batting["runs"] * 0.2))
        batting["walks"] = max(0, int(batting["walks"] * 0.3))
        batting["strikeouts"] = max(0, int(batting["strikeouts"] * 0.3))
        batting["stolen_bases"] = max(0, int(batting["stolen_bases"] * 0.2))
        batting["caught_stealing"] = max(0, int(batting["caught_stealing"] * 0.2))
        ab = max(batting["at_bats"], 1)
        pa = ab + batting["walks"]
        batting["avg"] = round(batting["hits"] / ab, 3)
        batting["obp"] = round((batting["hits"] + batting["walks"]) / max(pa, 1), 3)
        batting["slg"] = round(
            (singles + batting["doubles"] * 2 + batting["triples"] * 3 + batting["home_runs"] * 4) / ab, 3
        )
        result["batting"] = batting

    return result
