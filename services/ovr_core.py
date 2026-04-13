# services/ovr_core.py
"""
Canonical displayovr system.

Single source of truth for computing displayovr from player attributes:
  - compute_raw_ovr()         — weighted average over attributes given weights
  - compute_displayovr()      — full pipeline: raw_ovr → percentile rank → 20-80
  - recompute_breakpoints()   — rebuild league-wide raw_ovr cutoffs per (level, ptype)
  - recompute_stored_displayovr() — refresh simbbPlayers.displayovr column
  - load_breakpoints()        — read cached breakpoints (60s in-process TTL)
  - load_weights()            — read cached weights (60s in-process TTL)

All endpoints (bootstrap, rosters, scouting, FA, waivers, admin) call
compute_displayovr() with either precise _base attributes or per-org fuzzed
_display attributes. The same formula and the same league-wide breakpoints
produce both the precise and the fuzzed displayovr — strict math consistency.
"""

import bisect
import json
import logging
import re
import threading
import time
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sa_text

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position code → rating type mapping
# ---------------------------------------------------------------------------
# Previously duplicated as:
#   _POS_CODE_TO_RATING        in attribute_visibility.py
#   _POS_CODE_TO_RATING_TYPE   in weight_calibration.py

POS_CODE_TO_RATING = {
    "c": "c_rating", "fb": "fb_rating", "sb": "sb_rating",
    "tb": "tb_rating", "ss": "ss_rating", "lf": "lf_rating",
    "cf": "cf_rating", "rf": "rf_rating", "dh": "dh_rating",
    "sp": "sp_rating", "rp": "rp_rating",
}


# ---------------------------------------------------------------------------
# Pitch component regex
# ---------------------------------------------------------------------------
# Previously duplicated in attribute_visibility.py, player_display.py,
# and rating_config.py.

PITCH_COMPONENT_RE = re.compile(r"^pitch\d+_(pacc|pbrk|pcntrl|consist)_base$")


# ---------------------------------------------------------------------------
# Percentile rank → 20-80 scale
# ---------------------------------------------------------------------------
# Maps a uniform percentile rank through the inverse standard-normal CDF so
# the discretized output follows a normal distribution centered at 50 with
# SD 10: each 10 points (two buckets of 5) equals one standard deviation, so
# 40/60 are ±1 SD, 30/70 are ±2 SD, 20/80 are ±3 SD. Tail buckets are rare
# by construction (~0.3% at 20/80, ~19.7% at 50) which matches the scouting-
# scale mental model of 80 being generational talent.

_STD_NORMAL = NormalDist()

def percentile_rank_to_20_80(rank: float) -> int:
    """Map a percentile rank (0.0-1.0) to 20-80 scale via inverse normal CDF.

    Output is rounded to the nearest multiple of 5 and clamped to [20, 80].
    The rank is clamped to [0.001, 0.999] so the extreme ends don't map to
    ±inf; in practice this means the literal top/bottom player in a cohort
    lands at 80/20.
    """
    rank = max(0.001, min(0.999, rank))
    z = _STD_NORMAL.inv_cdf(rank)
    score = int(round((50.0 + z * 10.0) / 5.0) * 5)
    return max(20, min(80, score))


# ---------------------------------------------------------------------------
# Weight resolution (position-specific → generic fallback)
# ---------------------------------------------------------------------------
# Previously duplicated as:
#   _resolve_ovr_weights()          in weight_calibration.py
#   inline Tier 2 logic             in attribute_visibility._derive_raw_ovr()

def resolve_ovr_weights(
    pos_code: Optional[str],
    ptype: str,
    all_weights: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    """
    Pick the best weight set for a player's displayovr calculation.

    1. If the player has a listed position, use matching position-specific
       weights (e.g. ss_rating for a SS) — if those weights exist.
    2. Otherwise fall back to pitcher_overall / position_overall.
    """
    if pos_code:
        rating_type = POS_CODE_TO_RATING.get(pos_code)
        if rating_type:
            pos_weights = all_weights.get(rating_type, {})
            if pos_weights:
                return pos_weights

    if ptype == "Pitcher":
        return all_weights.get("pitcher_overall", {})
    return all_weights.get("position_overall", {})


# ---------------------------------------------------------------------------
# Default position weights (hardcoded fallback)
# ---------------------------------------------------------------------------
# Previously _DEFAULT_POSITION_WEIGHTS in player_display.py.

# Attribute keys excluded when computing defense-only position ratings.
# These are the offensive (hitting eye/power/contact/discipline) and pure
# baserunning components. `speed_base` is intentionally retained because it
# contributes to defensive range in the outfield and middle infield.
DEFENSE_EXCLUDED_ATTR_KEYS: frozenset = frozenset({
    "power_base",
    "contact_base",
    "eye_base",
    "discipline_base",
    "basereaction_base",
    "baserunning_base",
})

# Position rating types that have a corresponding defense-only counterpart
# (the 9 fielding positions including DH; pitchers are excluded).
FIELDING_RATING_TYPES: frozenset = frozenset({
    "c_rating", "fb_rating", "sb_rating", "tb_rating", "ss_rating",
    "lf_rating", "cf_rating", "rf_rating", "dh_rating",
})

DEFAULT_POSITION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "c_rating": {
        "power_base": 0.025, "contact_base": 0.025, "eye_base": 0.025, "discipline_base": 0.025,
        "basereaction_base": 0.025, "baserunning_base": 0.025,
        "throwacc_base": 0.05, "throwpower_base": 0.05,
        "catchframe_base": 0.25, "catchsequence_base": 0.25,
        "fieldcatch_base": 0.05, "fieldreact_base": 0.15, "fieldspot_base": 0.05,
    },
    "fb_rating": {
        "power_base": 0.175, "contact_base": 0.175, "eye_base": 0.175, "discipline_base": 0.175,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.025,
        "throwacc_base": 0.025,
        "fieldcatch_base": 0.05, "fieldreact_base": 0.10, "fieldspot_base": 0.05,
    },
    "sb_rating": {
        "power_base": 0.1, "contact_base": 0.1, "eye_base": 0.1, "discipline_base": 0.1,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.050,
        "throwacc_base": 0.15, "throwpower_base": 0.05,
        "fieldcatch_base": 0.10, "fieldreact_base": 0.15, "fieldspot_base": 0.05,
    },
    "tb_rating": {
        "power_base": 0.125, "contact_base": 0.125, "eye_base": 0.125, "discipline_base": 0.125,
        "basereaction_base": 0.025, "baserunning_base": 0.025,
        "throwacc_base": 0.10, "throwpower_base": 0.10,
        "fieldcatch_base": 0.05, "fieldreact_base": 0.15, "fieldspot_base": 0.05,
    },
    "ss_rating": {
        "power_base": 0.0375, "contact_base": 0.0375, "eye_base": 0.0375, "discipline_base": 0.0375,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.10,
        "throwacc_base": 0.15, "throwpower_base": 0.15,
        "fieldcatch_base": 0.15, "fieldreact_base": 0.25, "fieldspot_base": 0.10,
    },
    "lf_rating": {
        "power_base": 0.1, "contact_base": 0.1, "eye_base": 0.1, "discipline_base": 0.1,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.10,
        "throwacc_base": 0.10, "throwpower_base": 0.05,
        "fieldcatch_base": 0.10, "fieldreact_base": 0.05, "fieldspot_base": 0.15,
    },
    "cf_rating": {
        "power_base": 0.025, "contact_base": 0.025, "eye_base": 0.025, "discipline_base": 0.025,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.15,
        "throwacc_base": 0.10, "throwpower_base": 0.15,
        "fieldcatch_base": 0.15, "fieldreact_base": 0.20, "fieldspot_base": 0.15,
    },
    "rf_rating": {
        "power_base": 0.1, "contact_base": 0.1, "eye_base": 0.1, "discipline_base": 0.1,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.10,
        "throwacc_base": 0.05, "throwpower_base": 0.10,
        "fieldcatch_base": 0.10, "fieldreact_base": 0.05, "fieldspot_base": 0.15,
    },
    "dh_rating": {
        "power_base": 0.10, "contact_base": 0.10, "eye_base": 0.10, "discipline_base": 0.10,
        "basereaction_base": 0.025, "baserunning_base": 0.025, "speed_base": 0.025,
    },
    "sp_rating": {
        "fieldcatch_base": 0.025, "fieldreact_base": 0.05, "fieldspot_base": 0.025,
        "pendurance_base": 0.20, "pgencontrol_base": 0.10, "psequencing_base": 0.20,
        "pthrowpower_base": 0.05, "pickoff_base": 0.05,
        "pitch1_ovr": 0.10, "pitch2_ovr": 0.10, "pitch3_ovr": 0.10,
        "pitch4_ovr": 0.05, "pitch5_ovr": 0.05,
    },
    "rp_rating": {
        "fieldcatch_base": 0.025, "fieldreact_base": 0.05, "fieldspot_base": 0.025,
        "pendurance_base": 0.05, "pgencontrol_base": 0.10, "psequencing_base": 0.025,
        "pthrowpower_base": 0.05, "pickoff_base": 0.025,
        "pitch1_ovr": 0.25, "pitch2_ovr": 0.20, "pitch3_ovr": 0.15,
        "pitch4_ovr": 0.10, "pitch5_ovr": 0.05,
    },
}


# ---------------------------------------------------------------------------
# Canonical displayovr pipeline
# ---------------------------------------------------------------------------
#
# All displayovr derivation goes through this section. Any code that wants
# a player's displayovr must call compute_displayovr() — there is no other
# correct path.
#
# Precise vs fuzzed:
#   - Precise: pass true _base attributes (key_suffix="_base")
#   - Fuzzed:  pass per-org fuzzed _display ratings (key_suffix="_display")
# Both use the same weights and the same league-wide breakpoints, so the
# fuzzed displayovr is mathematically derivable from the visible fuzzed attrs.
#
# Free agents:
#   - Pass force_level=9 to rank against the MLB peer group regardless of
#     the player's stored level.

# Free agent peer group (level=9 / MLB) for FA / waiver / unsigned players
FREE_AGENT_LEVEL = 9

# In-process TTL caches for weights and breakpoints. Both rebuild on weight
# activation, manual recompute, direct weight edits, and engine subweek hooks.
_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_weights_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}
_breakpoints_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}


def _now() -> float:
    return time.monotonic()


def invalidate_caches() -> None:
    """Clear the in-process weights and breakpoints caches."""
    with _cache_lock:
        _weights_cache["data"] = None
        _weights_cache["expires_at"] = 0.0
        _breakpoints_cache["data"] = None
        _breakpoints_cache["expires_at"] = 0.0


def load_weights(conn) -> Dict[str, Dict[str, float]]:
    """
    Load active overall weights from rating_overall_weights, with a 60s
    in-process TTL cache. Returns {} if the table is empty (callers must
    handle this — log a loud error and return None displayovr).
    """
    with _cache_lock:
        if _weights_cache["data"] is not None and _now() < _weights_cache["expires_at"]:
            return _weights_cache["data"]

    from services.rating_config import get_overall_weights
    weights = get_overall_weights(conn) or {}

    if not weights:
        log.error(
            "rating_overall_weights table is empty — displayovr cannot be computed. "
            "Activate a weight profile via POST /admin/calibration/activate/<id>."
        )

    with _cache_lock:
        _weights_cache["data"] = weights
        _weights_cache["expires_at"] = _now() + _CACHE_TTL_SECONDS
    return weights


def load_breakpoints(conn) -> Dict[Tuple, List[float]]:
    """
    Load league-wide raw_ovr breakpoints from displayovr_breakpoints, with a
    60s in-process TTL cache. Returns {} if the table has not been populated
    (callers must handle this — log a loud error and return None displayovr).

    Cache keys are (level, rating_type) tuples. All player types are pooled
    together per level so that cross-position ratings (e.g. a hitter's
    sp_rating) are ranked against the full population, not just same-ptype
    peers. The rating_type is 'displayovr' for the listed-position overall,
    or a position rating name like 'c_rating', 'sp_rating', etc.
    """
    with _cache_lock:
        if _breakpoints_cache["data"] is not None and _now() < _breakpoints_cache["expires_at"]:
            return _breakpoints_cache["data"]

    breakpoints: Dict[Tuple, List[float]] = {}
    try:
        rows = conn.execute(sa_text(
            "SELECT level, rating_type, raw_overalls_json "
            "FROM displayovr_breakpoints"
        )).all()
        for row in rows:
            level, rating_type, raw_json = row[0], row[1], row[2]
            try:
                arr = json.loads(raw_json) if raw_json else []
                if isinstance(arr, list):
                    key = (int(level), str(rating_type))
                    # Pool across ptype rows if multiple exist for the same
                    # (level, rating_type) — handles legacy data that still
                    # has separate ptype rows before the next recompute.
                    if key in breakpoints:
                        merged = breakpoints[key] + [float(x) for x in arr]
                        merged.sort()
                        breakpoints[key] = merged
                    else:
                        breakpoints[key] = [float(x) for x in arr]
            except (TypeError, ValueError, json.JSONDecodeError):
                log.warning(
                    "Skipping malformed displayovr_breakpoints row "
                    "(level=%s, rating_type=%s)", level, rating_type,
                )
    except Exception:
        log.exception("Failed to load displayovr_breakpoints")
        breakpoints = {}

    if not breakpoints:
        log.error(
            "displayovr_breakpoints table is empty — displayovr cannot be percentile-ranked. "
            "Run recompute_stored_displayovr() to populate it."
        )

    with _cache_lock:
        _breakpoints_cache["data"] = breakpoints
        _breakpoints_cache["expires_at"] = _now() + _CACHE_TTL_SECONDS
    return breakpoints


def compute_raw_ovr(
    attrs,
    ptype: str,
    listed_pos_code: Optional[str],
    weights: Dict[str, Dict[str, float]],
    key_suffix: str = "_base",
) -> Optional[float]:
    """
    Compute a single player's raw weighted-average overall.

    `attrs` is any mapping (DB row, ratings dict, etc.) keyed by attribute
    column names. `key_suffix` controls the lookup convention:
      - "_base"     for true raw attributes (e.g. "power_base")
      - "_display"  for per-org fuzzed 20-80 ratings (e.g. "power_display")

    For pitch{N}_ovr pseudo-keys in the weights, the 4 components
    (consist/pacc/pbrk/pcntrl) are averaged with equal weight using the
    same key_suffix.

    Returns None if no usable weights or attributes are available.
    """
    wts = resolve_ovr_weights(listed_pos_code, ptype, weights)
    if not wts:
        return None

    raw_sum = 0.0
    weight_sum = 0.0

    for attr_key, weight in wts.items():
        if weight <= 0:
            continue

        if attr_key.startswith("pitch") and attr_key.endswith("_ovr"):
            pitch_num = attr_key.replace("pitch", "").replace("_ovr", "")
            components = [
                f"pitch{pitch_num}_consist{key_suffix}",
                f"pitch{pitch_num}_pacc{key_suffix}",
                f"pitch{pitch_num}_pbrk{key_suffix}",
                f"pitch{pitch_num}_pcntrl{key_suffix}",
            ]
            vals = []
            for k in components:
                v = attrs.get(k) if hasattr(attrs, "get") else None
                if v is None:
                    continue
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not vals:
                continue
            attr_val = sum(vals) / len(vals)
        else:
            # _base keys are stored as-is; _base in weights → _display lookup
            # for fuzzed views
            if key_suffix != "_base" and attr_key.endswith("_base"):
                lookup_key = attr_key.replace("_base", key_suffix)
            else:
                lookup_key = attr_key
            v = attrs.get(lookup_key) if hasattr(attrs, "get") else None
            if v is None:
                continue
            try:
                attr_val = float(v)
            except (TypeError, ValueError):
                continue

        raw_sum += attr_val * weight
        weight_sum += weight

    if weight_sum <= 0:
        return None
    return raw_sum / weight_sum


def _percentile_rank_against(raw_ovr: float, sorted_breakpoints: List[float]) -> float:
    """
    Average tie-breaking percentile rank of raw_ovr against a sorted list.
    Returns a value in [0.0, 1.0].
    """
    n = len(sorted_breakpoints)
    if n == 0:
        return 0.5
    if n == 1:
        return 0.5
    # bisect to find rank_below and rank_equal in O(log n)
    rank_below = bisect.bisect_left(sorted_breakpoints, raw_ovr)
    rank_above_or_equal = bisect.bisect_right(sorted_breakpoints, raw_ovr)
    rank_equal = rank_above_or_equal - rank_below
    pct = (rank_below + (rank_equal - 1) / 2.0) / (n - 1)
    return max(0.0, min(1.0, pct))


def compute_displayovr(
    attrs,
    ptype: str,
    listed_pos_code: Optional[str],
    level: Optional[int],
    weights: Dict[str, Dict[str, float]],
    breakpoints: Dict[Tuple[int, str], List[float]],
    key_suffix: str = "_base",
    is_free_agent: bool = False,
) -> Optional[int]:
    """
    Canonical displayovr derivation. All endpoints route through this.

    Returns an integer in [20, 80] or None if weights, breakpoints, or
    attributes are insufficient to compute a value.
    """
    if not weights or not breakpoints:
        return None

    raw_ovr = compute_raw_ovr(attrs, ptype, listed_pos_code, weights, key_suffix=key_suffix)
    if raw_ovr is None:
        return None

    # Determine peer group level
    if is_free_agent or level is None:
        peer_level = FREE_AGENT_LEVEL
    else:
        try:
            peer_level = int(level)
        except (TypeError, ValueError):
            peer_level = FREE_AGENT_LEVEL

    sorted_bp = breakpoints.get((peer_level, "displayovr"))
    if not sorted_bp:
        # No breakpoints for this peer group — return None rather than guess
        return None

    pct_rank = _percentile_rank_against(raw_ovr, sorted_bp)
    return percentile_rank_to_20_80(pct_rank)


def compute_all_position_ratings(
    attrs,
    ptype: str,
    level,
    weights: Dict[str, Dict[str, float]],
    breakpoints: Dict[Tuple, List[float]],
    key_suffix: str = "_base",
    is_free_agent: bool = False,
) -> Dict[str, Optional[int]]:
    """
    Compute a player's rating at every position using the same pipeline as
    displayovr: weighted average -> percentile rank -> 20-80 scale.

    Returns {rating_type: 20-80 int or None} for all positions in
    POS_CODE_TO_RATING (c_rating, fb_rating, ... sp_rating, rp_rating).

    The value for the player's listed position will match their displayovr
    (same weights, same breakpoints, same math).
    """
    if not weights or not breakpoints:
        return {}

    if is_free_agent or level is None:
        peer_level = FREE_AGENT_LEVEL
    else:
        try:
            peer_level = int(level)
        except (TypeError, ValueError):
            peer_level = FREE_AGENT_LEVEL

    results: Dict[str, Optional[int]] = {}

    for pos_code, rating_type in POS_CODE_TO_RATING.items():
        raw_ovr = compute_raw_ovr(attrs, ptype, pos_code, weights, key_suffix=key_suffix)
        if raw_ovr is None:
            results[rating_type] = None
            continue

        sorted_bp = breakpoints.get((peer_level, rating_type))
        if not sorted_bp:
            results[rating_type] = None
            continue

        pct_rank = _percentile_rank_against(raw_ovr, sorted_bp)
        results[rating_type] = percentile_rank_to_20_80(pct_rank)

    return results


# ---------------------------------------------------------------------------
# Recompute breakpoints + stored displayovr
# ---------------------------------------------------------------------------

def _load_all_active_players_raw(conn, level: Optional[int] = None):
    """
    Load all active players as raw mappings (with _base attribute keys),
    plus current_level and listed_position. Returns a list of
    (player_id, level, ptype, listed_pos, raw_mapping) tuples.

    Uses raw _base values (universal 0-100ish scale) so that breakpoints
    and live rating computation are on the same absolute scale regardless
    of player type. This avoids the ptype-relative inflation that occurs
    when using per-ptype-scaled _display values.
    """
    level_filter = "AND c.current_level = :level" if level else ""
    params: Dict[str, Any] = {}
    if level:
        params["level"] = level

    rows = conn.execute(sa_text(f"""
        SELECT p.*, c.current_level
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        WHERE 1=1 {level_filter}
    """), params).mappings().all()

    if not rows:
        return []

    # Bulk-load listed positions for the current league year
    listed_positions: Dict[int, str] = {}
    try:
        ly_row = conn.execute(sa_text(
            "SELECT id FROM league_years WHERE league_year = "
            "(SELECT season FROM timestamp_state WHERE id = 1)"
        )).first()
        if ly_row:
            lp_rows = conn.execute(sa_text(
                "SELECT player_id, position_code FROM player_listed_position "
                "WHERE league_year_id = :lyid"
            ), {"lyid": int(ly_row[0])}).all()
            for lp in lp_rows:
                listed_positions[int(lp[0])] = str(lp[1])
    except Exception:
        log.exception("ovr_core: failed to load listed positions")

    out = []
    for row in rows:
        try:
            pid = int(row["id"])
            ptype = (row.get("ptype") or "").strip()
            if not ptype:
                continue
            player_level = int(row["current_level"])
        except (TypeError, ValueError, KeyError):
            continue

        listed_pos = listed_positions.get(pid)
        out.append((pid, player_level, ptype, listed_pos, dict(row)))

    return out


def recompute_breakpoints(conn) -> Dict[Tuple, List[float]]:
    """
    Rebuild league-wide raw_ovr breakpoints for every (level, rating_type)
    group using the active weights from rating_overall_weights and each active
    player's _display (20-80 scaled) ratings.

    All player types (Pitcher + Position) are pooled together per level.
    Position-specific weight profiles handle the differentiation — a hitter
    evaluated with SP weights will naturally score low and land near the bottom
    of the combined population. This avoids the cross-ptype inflation problem
    where a hitter ranked only against other hitters-as-SP appears average.

    Computes breakpoints for:
      - 'displayovr': each player evaluated at their listed position
      - per-position ratings (c_rating, sp_rating, ...): every player evaluated
        at every position

    Uses raw _base values (universal 0-100ish scale) so that all player
    types are on the same absolute scale. This avoids ptype-relative
    inflation that occurs with per-ptype-scaled _display values.

    Writes to the displayovr_breakpoints table. Returns the in-memory dict.
    Logs a loud error and returns {} if no weights are configured.
    """
    weights = load_weights(conn)
    if not weights:
        log.error("recompute_breakpoints: rating_overall_weights is empty; aborting")
        return {}

    players = _load_all_active_players_raw(conn)
    if not players:
        log.warning("recompute_breakpoints: no active players found")
        return {}

    # All ptypes pooled together per (level, rating_type).
    # Uses _base values so the scale is absolute across player types.
    groups: Dict[Tuple, List[float]] = {}

    # --- displayovr breakpoints (listed position) ---
    for pid, level, ptype, listed_pos, raw_mapping in players:
        raw_ovr = compute_raw_ovr(
            raw_mapping, ptype, listed_pos, weights, key_suffix="_base",
        )
        if raw_ovr is None:
            continue
        groups.setdefault((level, "displayovr"), []).append(raw_ovr)

    # --- Per-position breakpoints ---
    # Evaluate every player at every position so that position ratings use
    # the same percentile-rank math as displayovr.
    for pos_code, rating_type in POS_CODE_TO_RATING.items():
        for pid, level, ptype, listed_pos, raw_mapping in players:
            raw_ovr = compute_raw_ovr(
                raw_mapping, ptype, pos_code, weights, key_suffix="_base",
            )
            if raw_ovr is None:
                continue
            groups.setdefault((level, rating_type), []).append(raw_ovr)

    # Sort each group's breakpoints
    breakpoints: Dict[Tuple, List[float]] = {}
    for key, vals in groups.items():
        vals.sort()
        breakpoints[key] = vals

    # Persist to displayovr_breakpoints (DELETE + INSERT for simplicity)
    # ptype is stored as 'ALL' since we pool across player types.
    try:
        conn.execute(sa_text("DELETE FROM displayovr_breakpoints"))
        for (level, rating_type), vals in breakpoints.items():
            conn.execute(sa_text("""
                INSERT INTO displayovr_breakpoints
                    (level, ptype, rating_type, raw_overalls_json, player_count,
                     computed_at)
                VALUES (:level, 'ALL', :rating_type, :raw_json, :count, NOW())
            """), {
                "level": level,
                "rating_type": rating_type,
                "raw_json": json.dumps(vals),
                "count": len(vals),
            })
    except Exception:
        log.exception("recompute_breakpoints: failed to persist to displayovr_breakpoints")

    # Invalidate cache so the next read gets the fresh values
    invalidate_caches()
    return breakpoints


def recompute_stored_displayovr(conn, level: Optional[int] = None) -> Dict[str, Any]:
    """
    Full refresh: rebuild breakpoints, then recompute simbbPlayers.displayovr
    for every active player using compute_displayovr() against the fresh
    breakpoints. Uses raw _base values (same absolute scale as breakpoints).

    Returns {updated, by_level, error?}.
    """
    weights = load_weights(conn)
    if not weights:
        return {"updated": 0, "by_level": {}, "error": "no_overall_weights_configured"}

    # Rebuild breakpoints first (writes to DB and invalidates cache)
    breakpoints = recompute_breakpoints(conn)
    if not breakpoints:
        return {"updated": 0, "by_level": {}, "error": "no_breakpoints_computed"}

    # Re-load weights post-cache-invalidation (and to keep API symmetric)
    weights = load_weights(conn)

    players = _load_all_active_players_raw(conn, level=level)
    if not players:
        return {"updated": 0, "by_level": {}}

    updates: List[Tuple[int, str]] = []
    by_level: Dict[int, int] = {}

    for pid, player_level, ptype, listed_pos, raw_mapping in players:
        ovr = compute_displayovr(
            raw_mapping, ptype, listed_pos, player_level, weights, breakpoints,
            key_suffix="_base", is_free_agent=False,
        )
        if ovr is None:
            continue
        updates.append((pid, str(ovr)))
        by_level[player_level] = by_level.get(player_level, 0) + 1

    # Bulk UPDATE via CASE
    CHUNK = 500
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i:i + CHUNK]
        cases = " ".join(f"WHEN {pid} THEN '{ovr}'" for pid, ovr in chunk)
        ids = ", ".join(str(pid) for pid, _ in chunk)
        conn.execute(sa_text(
            f"UPDATE simbbPlayers SET displayovr = CASE id {cases} END "
            f"WHERE id IN ({ids})"
        ))

    return {"updated": len(updates), "by_level": by_level}
