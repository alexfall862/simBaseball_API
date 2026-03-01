# services/rating_config.py
"""
Pre-computed 20-80 scouting scale configuration.

Stores mean / stddev for each rating attribute at each level in the
`rating_scale_config` table.  Roster endpoints read from this table
instead of recomputing distributions on every request.

Also manages configurable overall rating weights for pitcher and
position player overalls via the `rating_overall_weights` table.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from db import get_engine

logger = logging.getLogger("app")

PITCH_COMPONENT_RE = re.compile(r"^pitch\d+_(pacc|pbrk|pcntrl|consist)_base$")


# ------------------------------------------------------------------
# 20-80 conversion (shared utility)
# ------------------------------------------------------------------

def to_20_80(raw_val, mean, std) -> Optional[int]:
    """
    Map a raw numeric value into a 20-80 scouting scale.

    - 50  = mean
    - 80  = +3 standard deviations
    - 20  = -3 standard deviations
    - Rounded to nearest 5, clamped [20, 80].
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


# ------------------------------------------------------------------
# Read scale config
# ------------------------------------------------------------------

def get_rating_config(conn, level_id: Optional[int] = None) -> Dict[int, Dict[str, Dict[str, float]]]:
    """
    Read rating_scale_config into:
        { level_id: { attribute_key: { "mean": float, "std": float } } }
    """
    sql = "SELECT level_id, attribute_key, mean_value, std_dev FROM rating_scale_config"
    params = {}
    if level_id is not None:
        sql += " WHERE level_id = :level_id"
        params["level_id"] = level_id

    rows = conn.execute(text(sql), params).all()

    config: Dict[int, Dict[str, Dict[str, float]]] = {}
    for r in rows:
        lvl = int(r[0])
        attr = str(r[1])
        config.setdefault(lvl, {})[attr] = {
            "mean": float(r[2]),
            "std": float(r[3]),
        }
    return config


def get_rating_config_by_level_name(conn) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Same as get_rating_config but keyed by league_level string
    (e.g. "mlb", "aaa") for use in roster endpoints.
    """
    sql = """
        SELECT rc.level_id, l.league_level, rc.attribute_key,
               rc.mean_value, rc.std_dev
        FROM rating_scale_config rc
        JOIN levels l ON l.id = rc.level_id
    """
    rows = conn.execute(text(sql)).all()

    config: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in rows:
        level_name = str(r[1])
        attr = str(r[2])
        config.setdefault(level_name, {})[attr] = {
            "mean": float(r[3]),
            "std": float(r[4]),
        }
    return config


# ------------------------------------------------------------------
# Overall rating weights (read / write)
# ------------------------------------------------------------------

def get_overall_weights(conn) -> Dict[str, Dict[str, float]]:
    """
    Read rating_overall_weights into:
        { rating_type: { attribute_key: weight } }
    e.g. { "pitcher_overall": {"pendurance_base": 0.12, ...}, ... }
    """
    sql = "SELECT rating_type, attribute_key, weight FROM rating_overall_weights ORDER BY rating_type, attribute_key"
    rows = conn.execute(text(sql)).all()

    weights: Dict[str, Dict[str, float]] = {}
    for r in rows:
        rt = str(r[0])
        ak = str(r[1])
        weights.setdefault(rt, {})[ak] = float(r[2])
    return weights


def update_overall_weight(conn, rating_type: str, attribute_key: str, weight: float):
    """Update a single overall weight row."""
    conn.execute(text("""
        INSERT INTO rating_overall_weights (rating_type, attribute_key, weight)
        VALUES (:rt, :ak, :w)
        ON DUPLICATE KEY UPDATE weight = :w, updated_at = CURRENT_TIMESTAMP
    """), {"rt": rating_type, "ak": attribute_key, "w": weight})


# ------------------------------------------------------------------
# Seed / refresh config from live player data
# ------------------------------------------------------------------

def seed_rating_config(conn) -> Dict[str, Any]:
    """
    Compute population mean & stddev for every base attribute, derived
    rating, and overall rating at every level, then UPSERT into
    rating_scale_config.

    Uses a deduplicated subquery to ensure each player appears exactly
    once per level.
    """
    # 1. Fetch one row per player with their contract-based level.
    #    The subquery deduplicates in case of multiple team shares.
    player_sql = text("""
        SELECT p.*, sub.current_level
        FROM simbbPlayers p
        JOIN (
            SELECT DISTINCT c.playerID, c.current_level
            FROM contracts c
            JOIN contractDetails cd
              ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts
              ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.isActive = 1
        ) sub ON sub.playerID = p.id
    """)
    rows = conn.execute(player_sql).all()

    if not rows:
        logger.warning("seed_rating_config: no active players found")
        return {"rows_written": 0, "levels": {}, "player_counts": {}}

    # 2. Identify column categories from first row
    col_names = list(rows[0]._mapping.keys())
    base_cols = [c for c in col_names if c.endswith("_base")]

    # 3. Load overall weights from DB (if table exists)
    overall_weights = {}
    try:
        overall_weights = get_overall_weights(conn)
    except Exception:
        logger.info("seed_rating_config: rating_overall_weights table not found, skipping overalls")

    # 4. Accumulate values by level — one pass through all players
    level_attr_values: Dict[int, Dict[str, List[float]]] = {}
    player_counts: Dict[int, int] = {}

    for row in rows:
        m = row._mapping
        level = m.get("current_level")
        if level is None:
            continue
        level = int(level)

        player_counts[level] = player_counts.get(level, 0) + 1
        bucket = level_attr_values.setdefault(level, {})

        # --- Base attributes ---
        for col in base_cols:
            val = m.get(col)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue

            mp = PITCH_COMPONENT_RE.match(col)
            if mp:
                dist_key = f"pitch_{mp.group(1)}"
            else:
                dist_key = col
            bucket.setdefault(dist_key, []).append(num)

        # --- Derived ratings (position ratings & pitch overalls) ---
        raw_derived = _compute_derived_for_seed(m, base_cols)
        for attr_name, val in raw_derived.items():
            if val is not None:
                bucket.setdefault(attr_name, []).append(val)

        # --- Overall ratings from configurable weights ---
        for rating_type, wt_map in overall_weights.items():
            ovr_val = _compute_overall_for_player(m, raw_derived, wt_map)
            if ovr_val is not None:
                bucket.setdefault(rating_type, []).append(ovr_val)

    # 5. Compute mean/std and UPSERT
    upsert_sql = text("""
        INSERT INTO rating_scale_config (level_id, attribute_key, mean_value, std_dev)
        VALUES (:level_id, :attribute_key, :mean_value, :std_dev)
        ON DUPLICATE KEY UPDATE
            mean_value = VALUES(mean_value),
            std_dev    = VALUES(std_dev),
            updated_at = CURRENT_TIMESTAMP
    """)

    total_rows = 0
    levels_summary: Dict[int, int] = {}

    for level_id, attrs in sorted(level_attr_values.items()):
        attr_count = 0
        for attr_key, vals in sorted(attrs.items()):
            if not vals:
                continue

            mean = sum(vals) / len(vals)
            if len(vals) == 1:
                std = 0.0
            else:
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                std = math.sqrt(var)

            conn.execute(upsert_sql, {
                "level_id": level_id,
                "attribute_key": attr_key,
                "mean_value": round(mean, 6),
                "std_dev": round(std, 6),
            })
            attr_count += 1

        levels_summary[level_id] = attr_count
        total_rows += attr_count

    logger.info(
        "seed_rating_config: wrote %d rows across %d levels, player counts: %s",
        total_rows, len(levels_summary), player_counts,
    )
    return {
        "rows_written": total_rows,
        "levels": levels_summary,
        "player_counts": player_counts,
    }


# ------------------------------------------------------------------
# Overall rating computation for a single player
# ------------------------------------------------------------------

def _compute_overall_for_player(
    m, raw_derived: Dict[str, Optional[float]], wt_map: Dict[str, float]
) -> Optional[float]:
    """
    Compute a single overall value for one player using the given weights.
    Weights can reference _base columns (from m) or derived keys (from raw_derived).
    """
    components = []
    for attr_key, weight in wt_map.items():
        if weight <= 0:
            continue
        # Try derived first (pitch1_ovr, c_rating, etc.), then raw columns
        val = raw_derived.get(attr_key)
        if val is None:
            val = _safe_float(m.get(attr_key))
        if val is not None:
            components.append((val, weight))

    return _weighted(components)


# ------------------------------------------------------------------
# Lightweight derived-rating computation for seeding
# ------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _weighted(components: List[Tuple[Optional[float], float]]) -> Optional[float]:
    """Weighted average, skipping None values.  Returns None if all are None."""
    total_w = 0.0
    total_v = 0.0
    for val, weight in components:
        if val is not None and weight > 0:
            total_v += val * weight
            total_w += weight
    if total_w <= 0:
        return None
    return total_v / total_w


def _compute_derived_for_seed(m, base_cols) -> Dict[str, Optional[float]]:
    """
    Compute raw derived ratings (position ratings & pitch overalls)
    from a player's base attributes.  Mirrors the weighting in
    rosters/_compute_derived_raw_ratings exactly.
    """
    derived = {}

    def g(col):
        return _safe_float(m.get(col))

    # -- Pitch overalls (equal-weight avg of 4 components) --
    for n in range(1, 6):
        prefix = f"pitch{n}_"
        if m.get(prefix + "name") is None:
            continue
        ovr = _weighted([
            (g(prefix + "consist_base"), 0.25),
            (g(prefix + "pacc_base"), 0.25),
            (g(prefix + "pbrk_base"), 0.25),
            (g(prefix + "pcntrl_base"), 0.25),
        ])
        if ovr is not None:
            derived[f"pitch{n}_ovr"] = ovr

    # Common base values
    power = g("power_base")
    contact = g("contact_base")
    discipline = g("discipline_base")
    eye = g("eye_base")
    speed = g("speed_base")
    baserunning = g("baserunning_base")
    basereaction = g("basereaction_base")
    throwacc = g("throwacc_base")
    throwpower = g("throwpower_base")
    fieldcatch = g("fieldcatch_base")
    fieldreact = g("fieldreact_base")
    fieldspot = g("fieldspot_base")
    catchframe = g("catchframe_base")
    catchsequence = g("catchsequence_base")
    pendurance = g("pendurance_base")
    pgencontrol = g("pgencontrol_base")
    psequencing = g("psequencing_base")
    pthrowpower = g("pthrowpower_base")
    pickoff = g("pickoff_base")

    # Position ratings use DB-stored pitch_ovr (matching rosters behavior)
    p1 = g("pitch1_ovr")
    p2 = g("pitch2_ovr")
    p3 = g("pitch3_ovr")
    p4 = g("pitch4_ovr")
    p5 = g("pitch5_ovr")

    # -- Catcher --  (batting 10%, base 5%, throw 10%, catcher 50%, field 25%)
    derived["c_rating"] = _weighted([
        (power, 0.025), (contact, 0.025), (eye, 0.025), (discipline, 0.025),
        (basereaction, 0.025), (baserunning, 0.025),
        (throwacc, 0.05), (throwpower, 0.05),
        (catchframe, 0.25), (catchsequence, 0.25),
        (fieldcatch, 0.05), (fieldreact, 0.15), (fieldspot, 0.05),
    ])

    # -- First Base --  (batting 70%, base 7.5%, throw 2.5%, field 20%)
    derived["fb_rating"] = _weighted([
        (power, 0.175), (contact, 0.175), (eye, 0.175), (discipline, 0.175),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.025),
        (throwacc, 0.025),
        (fieldcatch, 0.05), (fieldreact, 0.10), (fieldspot, 0.05),
    ])

    # -- Second Base --  (batting 40%, base 10%, throw 20%, field 30%)
    derived["sb_rating"] = _weighted([
        (power, 0.1), (contact, 0.1), (eye, 0.1), (discipline, 0.1),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.050),
        (throwacc, 0.15), (throwpower, 0.05),
        (fieldcatch, 0.10), (fieldreact, 0.15), (fieldspot, 0.05),
    ])

    # -- Third Base --  (batting 50%, base 5%, throw 20%, field 25%)
    derived["tb_rating"] = _weighted([
        (power, 0.125), (contact, 0.125), (eye, 0.125), (discipline, 0.125),
        (basereaction, 0.025), (baserunning, 0.025),
        (throwacc, 0.10), (throwpower, 0.10),
        (fieldcatch, 0.05), (fieldreact, 0.15), (fieldspot, 0.05),
    ])

    # -- Shortstop --  (batting 15%, base 15%, throw 30%, field 40%)
    derived["ss_rating"] = _weighted([
        (power, 0.0375), (contact, 0.0375), (eye, 0.0375), (discipline, 0.0375),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.10),
        (throwacc, 0.15), (throwpower, 0.15),
        (fieldcatch, 0.15), (fieldreact, 0.25), (fieldspot, 0.10),
    ])

    # -- Left Field --  (batting 40%, base 15%, throw 15%, field 30%)
    derived["lf_rating"] = _weighted([
        (power, 0.1), (contact, 0.1), (eye, 0.1), (discipline, 0.1),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.10),
        (throwacc, 0.10), (throwpower, 0.05),
        (fieldcatch, 0.10), (fieldreact, 0.05), (fieldspot, 0.15),
    ])

    # -- Center Field --  (batting 10%, base 15%, throw 25%, field 50%)
    derived["cf_rating"] = _weighted([
        (power, 0.025), (contact, 0.025), (eye, 0.025), (discipline, 0.025),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.15),
        (throwacc, 0.10), (throwpower, 0.15),
        (fieldcatch, 0.15), (fieldreact, 0.20), (fieldspot, 0.15),
    ])

    # -- Right Field --  (batting 40%, base 15%, throw 15%, field 30%)
    derived["rf_rating"] = _weighted([
        (power, 0.1), (contact, 0.1), (eye, 0.1), (discipline, 0.1),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.10),
        (throwacc, 0.05), (throwpower, 0.10),
        (fieldcatch, 0.10), (fieldreact, 0.05), (fieldspot, 0.15),
    ])

    # -- Designated Hitter --  (batting + base only)
    derived["dh_rating"] = _weighted([
        (power, 0.10), (contact, 0.10), (eye, 0.10), (discipline, 0.10),
        (basereaction, 0.025), (baserunning, 0.025), (speed, 0.025),
    ])

    # -- Starting Pitcher --  (field 10%, pitching 60%, pitch quality 40%)
    derived["sp_rating"] = _weighted([
        (fieldcatch, 0.025), (fieldreact, 0.05), (fieldspot, 0.025),
        (pendurance, 0.20), (pgencontrol, 0.10), (psequencing, 0.20),
        (pthrowpower, 0.05), (pickoff, 0.05),
        (p1, 0.10), (p2, 0.10), (p3, 0.10), (p4, 0.05), (p5, 0.05),
    ])

    # -- Relief Pitcher --  (field 10%, pitching 25%, pitch quality 75%)
    derived["rp_rating"] = _weighted([
        (fieldcatch, 0.025), (fieldreact, 0.05), (fieldspot, 0.025),
        (pendurance, 0.05), (pgencontrol, 0.10), (psequencing, 0.025),
        (pthrowpower, 0.05), (pickoff, 0.025),
        (p1, 0.25), (p2, 0.20), (p3, 0.15), (p4, 0.10), (p5, 0.05),
    ])

    return derived
