"""
Fog-of-war attribute visibility system.

Single source of truth for "what does org X see for player Y?"
All fuzz is computed on the fly via deterministic hashing — never stored in DB.
The DB stores only true values + which scouting actions each org has unlocked.

Contexts:
  college_recruiting  — college org viewing HS player (pre-signing)
  college_roster      — any org viewing a college-level player
  pro_draft           — MLB org viewing college/INTAM player
  pro_roster          — any org viewing a pro player (levels 4-9)
"""

import hashlib
import logging
from sqlalchemy import text

log = logging.getLogger(__name__)

from services.org_constants import (
    INTAM_ORG_ID, USHS_ORG_ID,
    MLB_ORG_MIN, MLB_ORG_MAX,
    is_college_org,
)

# Pro levels (scraps=4 through mlb=9)
PRO_LEVEL_MIN = 4
PRO_LEVEL_MAX = 9

# College level
COLLEGE_LEVEL = 3

# ---------------------------------------------------------------------------
# Grade / scale constants
# ---------------------------------------------------------------------------
GRADE_LIST = [
    "F", "D-", "D", "D+", "C-", "C", "C+",
    "B-", "B", "B+", "A-", "A", "A+",
]
GRADE_INDEX = {g: i for i, g in enumerate(GRADE_LIST)}

# 20-80 score -> letter grade mapping (for converting raw -> letter)
_GRADE_THRESHOLDS = [
    (80, "A+"), (75, "A"), (70, "A-"),
    (65, "B+"), (60, "B"), (55, "B-"),
    (50, "C+"), (45, "C"), (40, "C-"),
    (35, "D+"), (30, "D"), (25, "D-"),
    (20, "F"),
]

from services.ovr_core import PITCH_COMPONENT_RE  # noqa: E402

# Letter grade → midpoint 20-80 score (for deriving displayovr from letter grades)
_GRADE_TO_SCORE = {
    "A+": 80, "A": 75, "A-": 70,
    "B+": 65, "B": 60, "B-": 55,
    "C+": 50, "C": 45, "C-": 40,
    "D+": 35, "D": 30, "D-": 25,
    "F": 20,
}

from services.ovr_core import POS_CODE_TO_RATING as _POS_CODE_TO_RATING  # noqa: E402

# Actions that grant precise attribute visibility (carryover-eligible)
_PRECISE_ATTR_ACTIONS = frozenset({
    "draft_attrs_precise",
    "pro_attrs_precise",
})

# Actions that grant precise potential visibility (carryover-eligible)
_PRECISE_POT_ACTIONS = frozenset({
    "recruit_potential_precise",
    "college_potential_precise",
    "draft_potential_precise",
    "pro_potential_precise",
})

# Actions that grant fuzzed 20-80 attributes
_FUZZED_NUMERIC_ACTIONS = frozenset({
    "draft_attrs_fuzzed",
})

# Level 5 key for draft prospect 20-80 conversion
DRAFT_DISPLAY_LEVEL = "a"  # Single-A (string key for distribution config)
DRAFT_DISPLAY_LEVEL_ID = 5  # Numeric level ID for breakpoint lookup


# ---------------------------------------------------------------------------
# Deterministic fuzz functions
# ---------------------------------------------------------------------------

def _fuzz_seed(org_id, player_id, attr_name):
    """
    Deterministic hash producing a stable integer for a given
    (org, player, attribute) triple.  Same inputs always produce
    the same output.  Different orgs see different fuzz.
    """
    raw = f"{org_id}:{player_id}:{attr_name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def _fuzz_magnitude_step(seed):
    """
    Map a seed to a magnitude step (1, 2, or 3) with a normal-shaped
    distribution: 70% / 25% / 5%.  Uses the low two bytes of the seed
    so the direction bit (bit 16) stays independent.
    """
    bucket = seed % 100
    if bucket < 70:
        return 1
    if bucket < 95:
        return 2
    return 3


def fuzz_letter_grade(true_grade, org_id, player_id, attr_name):
    """
    Shift a letter grade by 1-3 positions in GRADE_LIST.
    Direction and magnitude are deterministic per (org, player, attr).
    Magnitude is weighted 70/25/5 toward smaller shifts.
    """
    true_idx = GRADE_INDEX.get(true_grade)
    if true_idx is None:
        return "?"

    seed = _fuzz_seed(org_id, player_id, attr_name)
    magnitude = _fuzz_magnitude_step(seed)
    direction = 1 if (seed >> 16) % 2 == 0 else -1

    fuzzed_idx = true_idx + (direction * magnitude)
    fuzzed_idx = max(0, min(len(GRADE_LIST) - 1, fuzzed_idx))
    return GRADE_LIST[fuzzed_idx]


def fuzz_20_80(true_score, org_id, player_id, attr_name):
    """
    Offset a 20-80 score by 5, 10, or 15 (1-3 steps of 5).
    Direction and magnitude are deterministic per (org, player, attr).
    Magnitude is weighted 70/25/5 toward smaller shifts.
    """
    if true_score is None:
        return None

    seed = _fuzz_seed(org_id, player_id, attr_name)
    magnitude = _fuzz_magnitude_step(seed) * 5
    direction = 1 if (seed >> 16) % 2 == 0 else -1

    fuzzed = true_score + (direction * magnitude)
    return max(20, min(80, fuzzed))


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _to_20_80(raw_val, mean, std):
    """Map a raw numeric value into a 20-80 scouting scale."""
    if raw_val is None or mean is None:
        return None
    try:
        x = float(raw_val)
    except (TypeError, ValueError):
        return None

    if std is None or std <= 0:
        z = 0.0
    else:
        z = (x - mean) / std

    z = max(-3.0, min(3.0, z))
    raw_score = 50.0 + (z / 3.0) * 30.0
    raw_score = max(20.0, min(80.0, raw_score))
    score = int(round(raw_score / 5.0) * 5)
    return max(20, min(80, score))


def _score_to_letter(score):
    """Convert a 20-80 integer score to a letter grade."""
    if score is None:
        return "?"
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def base_to_letter_grade(value, mean=30.0, std=12.0):
    """Convert a numeric _base value to a letter grade via 20-80 scale."""
    score = _to_20_80(value, mean, std)
    return _score_to_letter(score)


# ---------------------------------------------------------------------------
# Context determination
# ---------------------------------------------------------------------------

def determine_player_context(viewing_org_id, holding_org_id, player_level):
    """
    Classify the viewing relationship into a context string.

    Returns one of:
      'college_recruiting' — college org viewing HS player
      'college_roster'     — any org viewing a college player
      'pro_draft'          — MLB org viewing college/INTAM player
      'pro_roster'         — any org viewing a pro player (levels 4-9)
    """
    # HS player
    if holding_org_id == USHS_ORG_ID:
        if is_college_org(viewing_org_id):
            return "college_recruiting"
        # Non-college orgs viewing HS: still show recruiting-style hidden view
        return "college_recruiting"

    # College or INTAM player
    if is_college_org(holding_org_id) or holding_org_id == INTAM_ORG_ID:
        if MLB_ORG_MIN <= viewing_org_id <= MLB_ORG_MAX:
            return "pro_draft"
        return "college_roster"

    # Pro player (levels 4-9)
    if PRO_LEVEL_MIN <= (player_level or 0) <= PRO_LEVEL_MAX:
        return "pro_roster"

    # Fallback: treat as pro roster
    return "pro_roster"


# ---------------------------------------------------------------------------
# Batch scouting action loader
# ---------------------------------------------------------------------------

def _load_scouting_actions_batch(conn, org_id, player_ids):
    """
    Load all scouting actions for (org_id, player_ids) in a single query.

    Returns: {player_id: set(action_type, ...), ...}
    """
    if not player_ids:
        return {}

    # Use explicit placeholders — SQLAlchemy text() with IN :tuple
    # does not reliably expand on all MySQL drivers.
    placeholders = ", ".join(f":pid{i}" for i in range(len(player_ids)))
    params = {"org_id": org_id}
    params.update({f"pid{i}": pid for i, pid in enumerate(player_ids)})

    rows = conn.execute(
        text(
            f"SELECT player_id, action_type FROM scouting_actions "
            f"WHERE org_id = :org_id AND player_id IN ({placeholders})"
        ),
        params,
    ).all()

    result = {}
    for pid, atype in rows:
        result.setdefault(pid, set()).add(atype)
    return result


def _load_scouting_actions_single(conn, org_id, player_id):
    """Load scouting actions for a single (org, player) pair."""
    rows = conn.execute(
        text("""
            SELECT action_type FROM scouting_actions
            WHERE org_id = :org_id AND player_id = :pid
        """),
        {"org_id": org_id, "pid": player_id},
    ).all()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Derived rating computation (from fuzzed base values)
# ---------------------------------------------------------------------------

def _recompute_pitch_ovrs_from_display(base_values):
    """
    Recompute pitch{1-5}_ovr from fuzzed/precise _display component values.

    Used by fog-of-war to derive pitch overalls consistent with visible
    component attributes. Returns {pitch{N}_ovr: int or None}.
    """
    derived = {}
    for i in range(1, 6):
        prefix = f"pitch{i}_"
        comps = [
            base_values.get(prefix + comp + "_display")
            for comp in ("consist", "pacc", "pbrk", "pcntrl")
        ]
        vals = []
        for v in comps:
            if v is None:
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        derived[f"pitch{i}_ovr"] = int(round(avg / 5.0) * 5)
    return derived


# DEPRECATED: _compute_derived_from_values
# The old function computed both pitch overalls AND position ratings from
# display values using a simple weighted average. Position ratings are now
# computed via the canonical displayovr pipeline (compute_all_position_ratings
# in ovr_core.py) which uses percentile-ranking against league breakpoints.
# Pitch overalls are handled by _recompute_pitch_ovrs_from_display above.
# The old function is retained below (commented out) for reference.
#
# def _compute_derived_from_values(base_values, position_weights=None):
#     """..."""
#     ...  # see git history for the original implementation


# ---------------------------------------------------------------------------
# Derived displayovr from visible ratings
# ---------------------------------------------------------------------------

# NOTE: _derive_raw_ovr and percentile_rank_displayovr were deleted in the
# canonical displayovr refactor. All displayovr derivation now goes through
# services.ovr_core.compute_displayovr() in _apply_visibility below.


# ---------------------------------------------------------------------------
# Core visibility application
# ---------------------------------------------------------------------------

def _apply_visibility(
    player_dict,
    viewing_org_id,
    holding_org_id,
    player_level,
    unlocked_actions,
    dist_config,
    col_cats,
    position_weights=None,
    ovr_weights=None,
    listed_pos_code=None,
    breakpoints=None,
    force_free_agent=False,
):
    """
    Apply fog-of-war to a player dict (output of _build_player_with_ratings).

    Mutates and returns the player_dict with:
      - ratings: fuzzed/masked/precise based on context + unlocked actions
      - potentials: fuzzed/masked/precise based on context + unlocked actions
      - visibility_context: metadata about what the org can see

    dist_config: {ptype: {level: {attr: {mean, std}}}} from rating_scale_config
    """
    player_id = player_dict.get("id")
    context = determine_player_context(viewing_org_id, holding_org_id, player_level)

    # Check carryover: any precise action from any context applies
    has_precise_attrs = bool(unlocked_actions & _PRECISE_ATTR_ACTIONS)
    has_precise_pot = bool(unlocked_actions & _PRECISE_POT_ACTIONS)
    has_fuzzed_numeric = bool(unlocked_actions & _FUZZED_NUMERIC_ACTIONS)

    ratings = player_dict.get("ratings", {})
    potentials = player_dict.get("potentials", {})
    bio = player_dict.get("bio", {})
    # Support both nested-bio shape (build_player_display) and flat shape (bootstrap)
    ptype = (bio.get("ptype") or player_dict.get("ptype") or "").strip()
    rating_cols = col_cats.get("rating", [])
    pot_cols = col_cats.get("pot", [])

    # Determine the level key for distribution lookups
    level_key = player_dict.get("league_level") or player_dict.get("current_level")

    # Get distribution for this player's ptype + level
    ptype_dist = dist_config.get(ptype) or dist_config.get("all") or {}
    dist_for_level = ptype_dist.get(level_key, {})

    # For draft prospects, use Level 5 (Single-A) distributions
    draft_dist = ptype_dist.get(DRAFT_DISPLAY_LEVEL, {})

    # We need raw _base values from bio for letter grade / re-conversion.
    # The original _build_player_with_ratings puts _base cols in bio,
    # and the 20-80 values in ratings as *_display keys.

    if context == "college_recruiting":
        # Attributes: hidden
        for col in rating_cols:
            out_name = col.replace("_base", "_display")
            ratings[out_name] = None
        # Clear derived ratings too
        for key in list(ratings.keys()):
            if key.endswith("_rating") or key.endswith("_ovr"):
                ratings[key] = None

        # Potentials: ? / fuzzed / precise
        if has_precise_pot:
            pass  # keep potentials as-is (precise)
        elif "recruit_potential_fuzzed" in unlocked_actions:
            for col in pot_cols:
                true_pot = potentials.get(col)
                if true_pot:
                    potentials[col] = fuzz_letter_grade(
                        true_pot, viewing_org_id, player_id, col
                    )
                else:
                    potentials[col] = "?"
        else:
            for col in pot_cols:
                potentials[col] = "?"

        display_format = "hidden"
        attrs_precise = False
        pot_precise = has_precise_pot

    elif context == "college_roster":
        # Attributes: fuzzed letter grades (ceiling — can never be precise)
        letter_ratings = {}
        for col in rating_cols:
            raw_val = bio.get(col)
            out_name = col.replace("_base", "_display")

            # Get distribution for letter grade conversion
            m_pitch = PITCH_COMPONENT_RE.match(col)
            if m_pitch:
                dist_key = f"pitch_{m_pitch.group(1)}"
            else:
                dist_key = col
            d = dist_for_level.get(dist_key, {})
            mean = d.get("mean", 30.0)
            std = d.get("std", 12.0)

            # Convert raw -> 20-80 -> letter grade -> fuzz
            true_grade = base_to_letter_grade(raw_val, mean, std)
            fuzzed = fuzz_letter_grade(
                true_grade, viewing_org_id, player_id, col
            )
            letter_ratings[out_name] = fuzzed

        ratings = letter_ratings
        # Clear derived ratings (letter grade context has no numeric derived)
        for key in list(ratings.keys()):
            if key.endswith("_rating") or key.endswith("_ovr"):
                pass  # these won't exist in letter_ratings dict
        # No derived ratings in letter grade mode

        # Potentials: fuzzed or precise
        if has_precise_pot:
            pass  # keep as-is
        else:
            for col in pot_cols:
                true_pot = potentials.get(col)
                if true_pot:
                    potentials[col] = fuzz_letter_grade(
                        true_pot, viewing_org_id, player_id, col
                    )
                else:
                    potentials[col] = "?"

        display_format = "letter_grade"
        attrs_precise = False
        pot_precise = has_precise_pot

    elif context == "pro_draft":
        # Compute position ratings from _base values (bio has raw attributes
        # for the build_player_display shape; player_dict top-level for bootstrap).
        # Use _base so all ptypes are on the same absolute scale.
        from services.ovr_core import compute_all_position_ratings as _cap_draft
        _raw_src = player_dict.get("_raw_base") or bio or player_dict
        _precise_pos = _cap_draft(
            _raw_src, ptype, DRAFT_DISPLAY_LEVEL_ID,
            ovr_weights or {}, breakpoints or {},
            key_suffix="_base",
        )

        if has_precise_attrs:
            # Precise 20-80 at draft level (Level 5) baseline
            # Re-convert raw values using Level 5 distributions
            for col in rating_cols:
                raw_val = bio.get(col)
                out_name = col.replace("_base", "_display")
                m_pitch = PITCH_COMPONENT_RE.match(col)
                if m_pitch:
                    dist_key = f"pitch_{m_pitch.group(1)}"
                else:
                    dist_key = col
                d = draft_dist.get(dist_key, {})
                if d:
                    ratings[out_name] = _to_20_80(raw_val, d.get("mean"), d.get("std"))
                else:
                    ratings[out_name] = None

            # Pitch overalls from display components
            pitch_ovrs = _recompute_pitch_ovrs_from_display(ratings)
            ratings.update(pitch_ovrs)
            # Position ratings from _base (precise)
            ratings.update(_precise_pos)
            display_format = "20-80"
            attrs_precise = True

        elif has_fuzzed_numeric:
            # Fuzzed 20-80 at Level 5 baseline
            for col in rating_cols:
                raw_val = bio.get(col)
                out_name = col.replace("_base", "_display")
                m_pitch = PITCH_COMPONENT_RE.match(col)
                if m_pitch:
                    dist_key = f"pitch_{m_pitch.group(1)}"
                else:
                    dist_key = col
                d = draft_dist.get(dist_key, {})
                if d:
                    true_score = _to_20_80(raw_val, d.get("mean"), d.get("std"))
                    ratings[out_name] = fuzz_20_80(
                        true_score, viewing_org_id, player_id, col
                    )
                else:
                    ratings[out_name] = None

            # Pitch overalls from fuzzed display components
            pitch_ovrs = _recompute_pitch_ovrs_from_display(ratings)
            ratings.update(pitch_ovrs)
            # Position ratings: fuzz the precise _base-derived values directly
            for key, val in _precise_pos.items():
                if val is not None:
                    ratings[key] = fuzz_20_80(val, viewing_org_id, player_id, key)
                else:
                    ratings[key] = val
            display_format = "20-80"
            attrs_precise = False

        else:
            # Default: fuzzed letter grades (college public view)
            letter_ratings = {}
            for col in rating_cols:
                raw_val = bio.get(col)
                out_name = col.replace("_base", "_display")
                m_pitch = PITCH_COMPONENT_RE.match(col)
                if m_pitch:
                    dist_key = f"pitch_{m_pitch.group(1)}"
                else:
                    dist_key = col
                d = dist_for_level.get(dist_key, {})
                mean = d.get("mean", 30.0)
                std = d.get("std", 12.0)
                true_grade = base_to_letter_grade(raw_val, mean, std)
                fuzzed = fuzz_letter_grade(
                    true_grade, viewing_org_id, player_id, col
                )
                letter_ratings[out_name] = fuzzed
            ratings = letter_ratings
            display_format = "letter_grade"
            attrs_precise = False

        # Potentials: fuzzed or precise
        if has_precise_pot:
            pass
        else:
            for col in pot_cols:
                true_pot = potentials.get(col)
                if true_pot:
                    potentials[col] = fuzz_letter_grade(
                        true_pot, viewing_org_id, player_id, col
                    )
                else:
                    potentials[col] = "?"

        pot_precise = has_precise_pot

    elif context == "pro_roster":
        if has_precise_attrs:
            # Keep true 20-80 ratings as-is (already computed by _build_player_with_ratings).
            # Position ratings were computed from _base values at build time
            # and are already correct.
            display_format = "20-80"
            attrs_precise = True
        else:
            # Save original values that must be fuzzed directly (not recomputed
            # from fuzzed components): pitch_ovr and position ratings.
            saved_direct_fuzz = {}
            for i in range(1, 6):
                key = f"pitch{i}_ovr"
                if ratings.get(key) is not None:
                    saved_direct_fuzz[key] = ratings[key]
            for key, val in list(ratings.items()):
                if key.endswith("_rating") and val is not None:
                    saved_direct_fuzz[key] = val

            # Fuzz the existing 20-80 base attribute ratings
            for key, val in list(ratings.items()):
                if val is None:
                    continue
                if key.endswith("_display"):
                    attr_name = key.replace("_display", "_base")
                    ratings[key] = fuzz_20_80(val, viewing_org_id, player_id, attr_name)

            # Fuzz pitch_ovr and position ratings directly from their precise
            # values (computed from _base at build time). This avoids recomputing
            # from fuzzed _display values which are on a ptype-relative scale.
            for key, val in saved_direct_fuzz.items():
                ratings[key] = fuzz_20_80(val, viewing_org_id, player_id, key)

            display_format = "20-80"
            attrs_precise = False

        # Potentials: fuzzed or precise
        if has_precise_pot:
            pass
        else:
            for col in pot_cols:
                true_pot = potentials.get(col)
                if true_pot:
                    potentials[col] = fuzz_letter_grade(
                        true_pot, viewing_org_id, player_id, col
                    )
                else:
                    potentials[col] = "?"

        pot_precise = has_precise_pot

    else:
        # Unknown context: show everything fuzzed as pro_roster
        display_format = "20-80"
        attrs_precise = False
        pot_precise = False

    player_dict["ratings"] = ratings
    player_dict["potentials"] = potentials

    # --- displayovr: canonical compute_displayovr() against league breakpoints ---
    # Uses raw _base values (from bio or player_dict top-level) so that the
    # computation matches the _base-scale breakpoints. For fuzzed contexts,
    # the precise displayovr is computed then fuzzed directly.
    from services.ovr_core import compute_displayovr

    if display_format == "hidden":
        displayovr_value = None
    else:
        is_fa = bool(force_free_agent)
        peer_level = level_key

        # Source _base values: _raw_base dict (bootstrap shape), bio
        # (build_player_display shape), or player_dict top-level
        _raw_for_ovr = player_dict.get("_raw_base") or bio or player_dict

        displayovr_value = compute_displayovr(
            _raw_for_ovr,
            ptype,
            listed_pos_code,
            peer_level,
            ovr_weights or {},
            breakpoints or {},
            key_suffix="_base",
            is_free_agent=is_fa,
        )

        # For fuzzed contexts, fuzz the displayovr value directly
        if displayovr_value is not None and not attrs_precise:
            displayovr_value = fuzz_20_80(
                displayovr_value, viewing_org_id, player_id, "displayovr"
            )

    player_dict["displayovr"] = displayovr_value
    bio_for_disp = player_dict.get("bio")
    if isinstance(bio_for_disp, dict) and "displayovr" in bio_for_disp:
        bio_for_disp["displayovr"] = displayovr_value

    player_dict["visibility_context"] = {
        "context": context,
        "display_format": display_format,
        "attributes_precise": attrs_precise,
        "potentials_precise": pot_precise,
    }

    # Strip internal _raw_base dict — not for frontend consumption
    player_dict.pop("_raw_base", None)

    return player_dict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_ovr_weights(conn):
    """Load overall weights via the canonical ovr_core cache."""
    try:
        from services.ovr_core import load_weights
        return load_weights(conn)
    except Exception:
        log.exception("_load_ovr_weights failed")
        return {}


def _load_breakpoints(conn):
    """Load displayovr breakpoints via the canonical ovr_core cache."""
    try:
        from services.ovr_core import load_breakpoints
        return load_breakpoints(conn)
    except Exception:
        log.exception("_load_breakpoints failed")
        return {}


def _load_listed_positions_batch(conn, player_ids):
    """Bulk-load listed positions: {player_id: position_code}."""
    if not player_ids:
        return {}
    try:
        ly_row = conn.execute(text(
            "SELECT id FROM league_years WHERE league_year = "
            "(SELECT season FROM timestamp_state WHERE id = 1)"
        )).first()
        if not ly_row:
            return {}
        lyid = int(ly_row[0])
        rows = conn.execute(text(
            "SELECT player_id, position_code FROM player_listed_position "
            "WHERE league_year_id = :lyid"
        ), {"lyid": lyid}).all()
        return {int(r[0]): str(r[1]) for r in rows}
    except Exception:
        return {}


def get_visible_player(
    conn,
    player_dict,
    viewing_org_id,
    holding_org_id,
    player_level,
    dist_config,
    col_cats,
    position_weights=None,
    force_free_agent=False,
):
    """
    Apply fog-of-war to a single player dict.

    player_dict: output of rosters._build_player_with_ratings()
    viewing_org_id: the org requesting the data
    holding_org_id: org that holds this player's contract
    player_level: current_level from contract
    dist_config: {ptype: {level: {attr: {mean, std}}}}
    col_cats: {rating: [...], pot: [...], bio: [...], derived: [...]}
    force_free_agent: rank against MLB peer group regardless of player_level
    """
    player_id = player_dict.get("id")
    unlocked = _load_scouting_actions_single(conn, viewing_org_id, player_id)
    ovr_weights = _load_ovr_weights(conn)
    breakpoints = _load_breakpoints(conn)
    listed_positions = _load_listed_positions_batch(conn, [player_id])
    return _apply_visibility(
        player_dict, viewing_org_id, holding_org_id, player_level,
        unlocked, dist_config, col_cats, position_weights,
        ovr_weights=ovr_weights,
        listed_pos_code=listed_positions.get(player_id),
        breakpoints=breakpoints,
        force_free_agent=force_free_agent,
    )


def get_visible_players_batch(
    conn,
    player_dicts,
    viewing_org_id,
    holding_org_ids,
    player_levels,
    dist_config,
    col_cats,
    position_weights=None,
    force_free_agent=False,
):
    """
    Apply fog-of-war to a list of player dicts.

    player_dicts: list of outputs from rosters._build_player_with_ratings()
    holding_org_ids: dict {player_id: holding_org_id}
    player_levels: dict {player_id: current_level}
    dist_config: {ptype: {level: {attr: {mean, std}}}}
    force_free_agent: rank all players against MLB peer group (used by FA/waivers)

    Uses a single batch query for scouting actions. displayovr is computed
    via the canonical ovr_core.compute_displayovr() inside _apply_visibility.
    """
    player_ids = [p.get("id") for p in player_dicts if p.get("id") is not None]
    actions_by_player = _load_scouting_actions_batch(conn, viewing_org_id, player_ids)

    # Load once for the whole batch (cached in ovr_core, ~free)
    ovr_weights = _load_ovr_weights(conn)
    breakpoints = _load_breakpoints(conn)
    listed_positions = _load_listed_positions_batch(conn, player_ids)

    results = []
    for pd in player_dicts:
        pid = pd.get("id")
        unlocked = actions_by_player.get(pid, set())
        h_org = holding_org_ids.get(pid, 0)
        p_level = player_levels.get(pid, 0)
        result = _apply_visibility(
            pd, viewing_org_id, h_org, p_level,
            unlocked, dist_config, col_cats, position_weights,
            ovr_weights=ovr_weights,
            listed_pos_code=listed_positions.get(pid),
            breakpoints=breakpoints,
            force_free_agent=force_free_agent,
        )
        results.append(result)

    return results


# NOTE: fuzz_displayovr was deleted in the canonical displayovr refactor.
# All endpoints (including lightweight listings like waivers) now route
# through services.ovr_core.compute_displayovr() against the per-org
# fuzzed attributes produced by _apply_visibility.
