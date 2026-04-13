# services/player_display.py
"""
Shared player display builder — single source of truth for transforming
raw player data into the standard display shape used by roster, FA pool,
IFA board, and draft pool endpoints.

Public API:
    load_display_context(conn) → dict   (col_cats, dist_by_level, position_weights)
    build_player_display(mapping, ctx)  → dict with bio, ratings, potentials
"""

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────

from services.ovr_core import PITCH_COMPONENT_RE  # noqa: E402, F811
from services.ovr_core import DEFAULT_POSITION_WEIGHTS as _DEFAULT_POSITION_WEIGHTS  # noqa: E402

# ── Level ID → name mapping ─────────────────────────────────────────
# Distribution config is keyed by level name ("mlb", "aaa", etc.)
# but many queries produce numeric level IDs. This maps between them.
_LEVEL_ID_TO_NAME = {
    1: "high school", 2: "intam", 3: "college", 4: "scraps",
    5: "a", 6: "higha", 7: "aa", 8: "aaa", 9: "mlb", 99: "wbc",
}


def _resolve_level_key(raw_level):
    """Convert a numeric level ID to the string name used in distribution config."""
    if raw_level is None:
        return None
    if isinstance(raw_level, str):
        return raw_level
    try:
        return _LEVEL_ID_TO_NAME.get(int(raw_level), raw_level)
    except (TypeError, ValueError):
        return raw_level


# ── Column category cache ───────────────────────────────────────────

_col_cats_cache: Optional[Dict[str, List[str]]] = None


def get_player_column_categories(engine=None) -> Dict[str, List[str]]:
    """
    Categorize simbbPlayers columns into:
      - rating: numeric attributes (endswith _base)
      - derived: attributes derived from other columns (_rating, pitchN_ovr)
      - pot: potential grade columns (endswith _pot)
      - bio: everything else (id, names, biographical, pitchN_name, etc.)

    Result is cached after first call.  Pass engine on first call.
    """
    global _col_cats_cache
    if _col_cats_cache is not None:
        return _col_cats_cache

    if engine is None:
        raise ValueError("engine required on first call to get_player_column_categories")

    from sqlalchemy import MetaData, Table
    md = MetaData()
    players = Table("simbbPlayers", md, autoload_with=engine)

    rating_cols = []
    derived_cols = []
    pot_cols = []
    bio_cols = []

    for col in players.c:
        name = col.name
        if name.endswith("_pot"):
            pot_cols.append(name)
        elif name.endswith("_base"):
            rating_cols.append(name)
        elif name.endswith("_rating") or re.match(r"^pitch\d+_ovr$", name):
            derived_cols.append(name)
        else:
            bio_cols.append(name)

    _col_cats_cache = {
        "rating": rating_cols,
        "derived": derived_cols,
        "pot": pot_cols,
        "bio": bio_cols,
    }
    return _col_cats_cache


def clear_column_cache():
    """Clear the column category cache (for tests or schema changes)."""
    global _col_cats_cache
    _col_cats_cache = None


# ── 20-80 scaling ──────────────────────────────────────────────────

def to_20_80(raw_val, mean, std):
    """
    Map a raw numeric value into a 20-80 scouting scale, clamped and
    rounded to nearest 5.  50 at mean, 80 at +3σ, 20 at -3σ.
    """
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


# ── Derived raw ratings ────────────────────────────────────────────

def compute_derived_raw_ratings(
    mapping: Dict[str, Any],
    position_weights: Optional[Dict] = None,
) -> Dict[str, Optional[float]]:
    """
    Compute raw (0-100ish) derived ratings for:
      - pitch1_ovr ... pitch5_ovr  (equal-weight average of components)
      - c_rating, fb_rating, etc.  (from position_weights or defaults)
      - *_def_rating               (defense-only counterparts)

    Accepts a plain dict (or any mapping supporting .get()).

    NOTE: The *_rating position ratings produced here are RAW weighted
    averages. For DISPLAY purposes (bootstrap, rosters, scouting), use
    ovr_core.compute_all_position_ratings() instead, which runs the
    same percentile-rank pipeline as displayovr. This function's *_rating
    output is still used by:
      - game_payload.py (engine payloads need raw 0-100 values)
      - listed_position.py (auto-position logic uses raw comparisons)
      - rating_config.py seed (population distributions for breakpoints)
    """
    derived: Dict[str, Optional[float]] = {}

    def _w_avg(components):
        total_w = 0.0
        total_v = 0.0
        for col, w in components.items():
            if w <= 0:
                continue
            v = derived.get(col)  # check derived first (for pitch_ovr refs)
            if v is None:
                v = mapping.get(col)
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            total_v += num * w
            total_w += w
        if total_w <= 0:
            return None
        return total_v / total_w

    # Pitch overalls
    for i in range(1, 6):
        prefix = f"pitch{i}_"
        if mapping.get(prefix + "name") is None:
            continue
        raw = _w_avg({
            prefix + "consist_base": 0.25,
            prefix + "pacc_base":    0.25,
            prefix + "pbrk_base":    0.25,
            prefix + "pcntrl_base":  0.25,
        })
        if raw is not None:
            derived[f"pitch{i}_ovr"] = raw

    # Position ratings (raw weighted averages — used by engine + seeding,
    # NOT for display; see docstring above)
    weights = position_weights or _DEFAULT_POSITION_WEIGHTS
    for rating_type, wt_map in weights.items():
        derived[rating_type] = _w_avg(wt_map)

    # Defense-only position ratings (parallel fields).
    # For each fielding position, compute a second weighted average using
    # the same calibrated weights but with offensive and pure-baserunning
    # attribute keys stripped out. _w_avg re-normalizes by the surviving
    # weights, so the ratio between the kept defensive components is
    # preserved exactly. These power "where to play" decisions in
    # default_gameplan without the offense double-count problem.
    from services.ovr_core import (
        DEFENSE_EXCLUDED_ATTR_KEYS,
        FIELDING_RATING_TYPES,
    )
    for rating_type, wt_map in weights.items():
        if rating_type not in FIELDING_RATING_TYPES:
            continue
        def_key = rating_type.replace("_rating", "_def_rating")
        if rating_type == "dh_rating":
            derived[def_key] = None
            continue
        def_wt_map = {
            k: w for k, w in wt_map.items()
            if k not in DEFENSE_EXCLUDED_ATTR_KEYS
        }
        derived[def_key] = _w_avg(def_wt_map) if def_wt_map else None

    return derived


# ── Distribution + weight loaders ──────────────────────────────────

def load_position_weights(conn) -> Optional[Dict]:
    """Load position rating weights from DB, or None to use defaults."""
    try:
        from services.rating_config import get_overall_weights, POSITION_RATING_TYPES
        all_weights = get_overall_weights(conn)
        pos = {k: v for k, v in all_weights.items() if k in POSITION_RATING_TYPES}
        if pos:
            return pos
        log.warning("No position weights in rating_overall_weights; using hardcoded defaults")
        return None
    except Exception:
        log.warning("Failed to load position weights; using hardcoded defaults", exc_info=True)
        return None


def load_dist_by_level(conn, col_cats):
    """
    Load pre-computed distributions from rating_scale_config.
    Falls back to on-the-fly computation if the config table is empty.

    Returns (dist_by_level dict, source string "config" | "computed").
    The dict is keyed by ptype then level:
        { ptype: { league_level: { attr: { "mean", "std" } } } }
    """
    try:
        from services.rating_config import get_rating_config_by_level_name
        config = get_rating_config_by_level_name(conn)
        if config:
            return config, "config"
    except Exception:
        pass

    # Fallback: empty distributions (will result in None ratings)
    return {}, "computed"


# ── Public API ─────────────────────────────────────────────────────

def load_display_context(conn) -> Dict[str, Any]:
    """
    One-call loader for everything needed to build player display dicts.
    Call once per request, pass the result to build_player_display().
    """
    col_cats = get_player_column_categories(conn.engine)
    dist_by_level, _source = load_dist_by_level(conn, col_cats)
    position_weights = load_position_weights(conn)

    # Load displayovr weights and breakpoints for position rating computation
    ovr_weights = None
    breakpoints = None
    try:
        from services.ovr_core import load_weights, load_breakpoints
        ovr_weights = load_weights(conn)
        breakpoints = load_breakpoints(conn)
    except Exception:
        log.warning("load_display_context: failed to load ovr weights/breakpoints",
                    exc_info=True)

    return {
        "col_cats": col_cats,
        "dist_by_level": dist_by_level,
        "position_weights": position_weights,
        "ovr_weights": ovr_weights,
        "breakpoints": breakpoints,
    }


def build_player_display(
    mapping: Dict[str, Any],
    ctx: Dict[str, Any],
    listed_pos_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transform a raw player mapping into the standard display shape:

    {
      "id": int,
      "displayovr": ...,
      "bio": { firstname, lastname, age, ... pitch1_name..pitch5_name },
      "ratings": { contact_display, power_display, ..., c_rating, sp_rating, pitch1_ovr, ... },
      "potentials": { contact_pot, power_pot, ... },
    }

    Position ratings (c_rating, sp_rating, etc.) are computed via the
    canonical displayovr pipeline (percentile-rank against breakpoints)
    when ovr_weights and breakpoints are available in ctx.

    Level for distribution lookup uses the fallback chain:
        mapping["league_level"] → mapping["current_level"] → mapping["last_level"]
    """
    col_cats = ctx["col_cats"]
    dist_by_level = ctx["dist_by_level"]
    position_weights = ctx["position_weights"]
    ovr_weights = ctx.get("ovr_weights")
    breakpoints = ctx.get("breakpoints")

    rating_cols = col_cats["rating"]
    pot_cols = col_cats["pot"]
    bio_cols = col_cats["bio"]

    raw_level = (
        mapping.get("league_level")
        or mapping.get("current_level")
        or mapping.get("last_level")
    )
    level_key = _resolve_level_key(raw_level)
    current_level = mapping.get("current_level")
    ptype = (mapping.get("ptype") or "").strip()

    # Distribution lookup: ptype → level → attr → {mean, std}
    ptype_dist = dist_by_level.get(ptype) or dist_by_level.get("all") or {}
    dist_for_level = ptype_dist.get(level_key, {})

    # --- Bio ---
    bio = {}
    for name in bio_cols:
        bio[name] = mapping.get(name)

    # --- Base 20-80 ratings (_base → _display) ---
    ratings = {}
    for col in rating_cols:
        val = mapping.get(col)

        # Use pooled pitch distribution for pitch components
        m_pitch = PITCH_COMPONENT_RE.match(col)
        if m_pitch:
            component = m_pitch.group(1)
            dist_key = f"pitch_{component}"
        else:
            dist_key = col

        d = dist_for_level.get(dist_key)
        if not d or d.get("mean") is None:
            scaled = None
        else:
            scaled = to_20_80(val, d["mean"], d["std"])

        out_name = col.replace("_base", "_display")
        ratings[out_name] = scaled

    # --- Derived ratings: pitch overalls + defense-only ratings ---
    # Position ratings (*_rating) are now computed below via the displayovr
    # pipeline. This path only produces pitch_ovr and *_def_rating values.
    from services.rating_config import is_derived_rating, to_20_80_percentile

    raw_derived = compute_derived_raw_ratings(mapping, position_weights)
    for attr_name, raw_val in raw_derived.items():
        if attr_name.endswith("_rating"):
            # Skip old z-score position ratings — replaced by displayovr pipeline
            continue
        d = dist_for_level.get(attr_name)
        if not d or d.get("mean") is None:
            scaled = None
        elif is_derived_rating(attr_name) and d.get("percentiles"):
            scaled = to_20_80_percentile(raw_val, d["percentiles"])
        else:
            scaled = to_20_80(raw_val, d["mean"], d["std"])

        ratings[attr_name] = scaled

    # --- Position ratings via canonical displayovr pipeline ---
    # Uses _display values with ptype-split breakpoints. Cross-ptype
    # ratings are null (pitchers get null for fielding, hitters for pitching).
    if ovr_weights and breakpoints:
        from services.ovr_core import compute_all_position_ratings
        pos_ratings = compute_all_position_ratings(
            ratings, ptype, current_level, ovr_weights, breakpoints,
            key_suffix="_display",
        )
        ratings.update(pos_ratings)

    # --- Potentials ---
    potentials = {}
    for col in pot_cols:
        potentials[col] = mapping.get(col)

    return {
        "id": mapping.get("id"),
        "displayovr": mapping.get("displayovr"),
        "bio": bio,
        "ratings": ratings,
        "potentials": potentials,
    }
