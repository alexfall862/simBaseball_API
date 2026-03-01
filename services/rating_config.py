# services/rating_config.py
"""
Pre-computed 20-80 scouting scale configuration.

Stores mean / stddev for each rating attribute at each level, split by
player type (Pitcher vs Position), in the `rating_scale_config` table.
Roster endpoints read from this table instead of recomputing distributions
on every request.

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

# Canonical ptype values stored in rating_scale_config
PTYPE_PITCHER = "Pitcher"
PTYPE_POSITION = "Position"

# Position rating types stored in rating_overall_weights (configurable weights)
POSITION_RATING_TYPES = frozenset({
    "c_rating", "fb_rating", "sb_rating", "tb_rating", "ss_rating",
    "lf_rating", "cf_rating", "rf_rating", "dh_rating",
    "sp_rating", "rp_rating",
})


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

def get_rating_config(
    conn,
    level_id: Optional[int] = None,
    ptype: Optional[str] = None,
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    Read rating_scale_config into:
        { ptype: { level_id: { attribute_key: { "mean", "std", "p25", "median", "p75" } } } }

    Optional filters narrow the result set.
    """
    sql = "SELECT level_id, ptype, attribute_key, mean_value, std_dev, p25, median, p75 FROM rating_scale_config WHERE 1=1"
    params: dict = {}
    if level_id is not None:
        sql += " AND level_id = :level_id"
        params["level_id"] = level_id
    if ptype is not None:
        sql += " AND ptype = :ptype"
        params["ptype"] = ptype

    rows = conn.execute(text(sql), params).all()

    config: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for r in rows:
        lvl = int(r[0])
        pt = str(r[1])
        attr = str(r[2])
        config.setdefault(pt, {}).setdefault(lvl, {})[attr] = {
            "mean": float(r[3]),
            "std": float(r[4]),
            "p25": float(r[5]) if r[5] is not None else None,
            "median": float(r[6]) if r[6] is not None else None,
            "p75": float(r[7]) if r[7] is not None else None,
        }
    return config


def get_rating_config_by_level_name(conn, ptype: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, Dict[str, float]]]]:
    """
    Same as get_rating_config but keyed by league_level string
    (e.g. "mlb", "aaa") for use in roster endpoints.

    Returns: { ptype: { league_level: { attribute_key: { "mean", "std" } } } }
    """
    sql = """
        SELECT rc.level_id, rc.ptype, l.league_level, rc.attribute_key,
               rc.mean_value, rc.std_dev
        FROM rating_scale_config rc
        JOIN levels l ON l.id = rc.level_id
    """
    params: dict = {}
    if ptype is not None:
        sql += " WHERE rc.ptype = :ptype"
        params["ptype"] = ptype

    rows = conn.execute(text(sql), params).all()

    config: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
    for r in rows:
        pt = str(r[1])
        level_name = str(r[2])
        attr = str(r[3])
        config.setdefault(pt, {}).setdefault(level_name, {})[attr] = {
            "mean": float(r[4]),
            "std": float(r[5]),
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
# Admin config editing
# ------------------------------------------------------------------

def update_config_rows(conn, updates: List[Dict[str, Any]]) -> int:
    """
    Bulk-update mean_value / std_dev for existing config rows.

    Each update dict: { "level_id", "ptype", "attribute_key", "mean_value", "std_dev" }
    Returns count of rows affected.
    """
    sql = text("""
        UPDATE rating_scale_config
        SET mean_value = :mean_value, std_dev = :std_dev
        WHERE level_id = :level_id AND ptype = :ptype AND attribute_key = :attribute_key
    """)
    count = 0
    for u in updates:
        result = conn.execute(sql, {
            "level_id": u["level_id"],
            "ptype": u["ptype"],
            "attribute_key": u["attribute_key"],
            "mean_value": float(u["mean_value"]),
            "std_dev": float(u["std_dev"]),
        })
        count += result.rowcount
    return count


def bulk_set_config(conn, level_id: int, ptype: str, mean_value: float, std_dev: float) -> int:
    """
    Set the SAME mean_value and std_dev for ALL attributes at a given level/ptype.
    Returns count of rows affected.
    """
    result = conn.execute(text("""
        UPDATE rating_scale_config
        SET mean_value = :mean, std_dev = :std
        WHERE level_id = :level_id AND ptype = :ptype
    """), {"level_id": level_id, "ptype": ptype, "mean": mean_value, "std": std_dev})
    return result.rowcount


# ------------------------------------------------------------------
# Seed / refresh config from live player data
# ------------------------------------------------------------------

# Map overall weight rating_type → which ptype should compute it
_OVERALL_PTYPE_MAP = {
    "pitcher_overall": PTYPE_PITCHER,
    "position_overall": PTYPE_POSITION,
}

def seed_rating_config(conn) -> Dict[str, Any]:
    """
    Compute population mean & stddev for every base attribute, derived
    rating, and overall rating at every level, SPLIT BY PLAYER TYPE,
    then UPSERT into rating_scale_config.

    Distributions are computed separately for Pitcher vs Position players
    at each level. This avoids bimodal distributions caused by mixing
    player types (e.g., pitchers have low power_base which would drag
    down the combined mean and inflate stddev).
    """
    # 1. Fetch one row per player with their contract-based level.
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

    # 2. Identify base columns from first row
    col_names = list(rows[0]._mapping.keys())
    base_cols = [c for c in col_names if c.endswith("_base")]

    # 3. Load overall weights from DB (if table exists)
    all_weights: Dict[str, Dict[str, float]] = {}
    try:
        all_weights = get_overall_weights(conn)
    except Exception:
        logger.info("seed_rating_config: rating_overall_weights table not found, skipping overalls")

    # Split into position rating weights vs pure overall weights
    position_weights = {k: v for k, v in all_weights.items() if k in POSITION_RATING_TYPES}
    overall_weights = {k: v for k, v in all_weights.items() if k not in POSITION_RATING_TYPES}

    # 4. Accumulate values by (level, ptype) — one pass through all players
    #    Key: (level_id, ptype) → { attr_key → [values] }
    bucket_values: Dict[Tuple[int, str], Dict[str, List[float]]] = {}
    player_counts: Dict[str, Dict[int, int]] = {}  # ptype → level → count

    for row in rows:
        m = row._mapping
        level = m.get("current_level")
        ptype = (m.get("ptype") or "").strip()
        if level is None or ptype not in (PTYPE_PITCHER, PTYPE_POSITION):
            continue
        level = int(level)

        player_counts.setdefault(ptype, {})
        player_counts[ptype][level] = player_counts[ptype].get(level, 0) + 1

        bkey = (level, ptype)
        bucket = bucket_values.setdefault(bkey, {})

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

        # --- Derived ratings (pitch overalls + position ratings from DB weights) ---
        raw_derived = _compute_derived_for_seed(m, base_cols, position_weights)
        for attr_name, val in raw_derived.items():
            if val is not None:
                bucket.setdefault(attr_name, []).append(val)

        # --- Overall ratings from configurable weights ---
        # Only compute the overall that matches this player's ptype
        for rating_type, wt_map in overall_weights.items():
            expected_ptype = _OVERALL_PTYPE_MAP.get(rating_type)
            if expected_ptype and expected_ptype != ptype:
                continue
            ovr_val = _compute_overall_for_player(m, raw_derived, wt_map)
            if ovr_val is not None:
                bucket.setdefault(rating_type, []).append(ovr_val)

    # 5. Clear old data and write fresh
    conn.execute(text("DELETE FROM rating_scale_config"))

    insert_sql = text("""
        INSERT INTO rating_scale_config
            (level_id, ptype, attribute_key, mean_value, std_dev, p25, median, p75)
        VALUES
            (:level_id, :ptype, :attribute_key, :mean_value, :std_dev, :p25, :median, :p75)
    """)

    total_rows = 0
    levels_summary: Dict[str, Dict[int, int]] = {}  # ptype → level → attr_count

    for (level_id, ptype), attrs in sorted(bucket_values.items()):
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

            # Quartiles
            sorted_vals = sorted(vals)
            p25 = _percentile(sorted_vals, 25)
            median = _percentile(sorted_vals, 50)
            p75 = _percentile(sorted_vals, 75)

            conn.execute(insert_sql, {
                "level_id": level_id,
                "ptype": ptype,
                "attribute_key": attr_key,
                "mean_value": round(mean, 6),
                "std_dev": round(std, 6),
                "p25": round(p25, 4),
                "median": round(median, 4),
                "p75": round(p75, 4),
            })
            attr_count += 1

        levels_summary.setdefault(ptype, {})[level_id] = attr_count
        total_rows += attr_count

    logger.info(
        "seed_rating_config: wrote %d rows, player counts: %s",
        total_rows, player_counts,
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

def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Compute percentile from a pre-sorted list using linear interpolation."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    k = (pct / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)


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


def _compute_derived_for_seed(
    m, base_cols, position_weights: Dict[str, Dict[str, float]]
) -> Dict[str, Optional[float]]:
    """
    Compute raw derived ratings (pitch overalls + position ratings)
    from a player's base attributes.

    Pitch overalls are always an equal-weight average of 4 components.
    Position ratings use configurable weights from rating_overall_weights.
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

    # -- Position ratings from configurable weights --
    for rating_type, wt_map in position_weights.items():
        val = _compute_overall_for_player(m, derived, wt_map)
        if val is not None:
            derived[rating_type] = val

    return derived
