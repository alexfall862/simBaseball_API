# services/weight_calibration.py
"""
Position weight calibration via OLS regression on game performance data.

Derives attribute-to-position weights statistically by regressing player
attributes against on-field performance metrics (OPS for offense, fielding
runs for defense, ERA for pitching).  Results are stored as named profiles
that can be compared and activated.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from services.analytics import (
    _ols_regression,
    BATTING_ATTRS,
    DEFENSIVE_ATTRS,
    PITCHING_CORE_ATTRS,
    PITCHING_AGG_ATTRS,
    PITCHING_ATTRS,
    _avg_pitch_components,
    _PITCH_SELECT,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Position code (fielding_stats) -> rating_type (weight table)
_POS_RATING_MAP = {
    "c": "c_rating", "fb": "fb_rating", "sb": "sb_rating",
    "tb": "tb_rating", "ss": "ss_rating", "lf": "lf_rating",
    "cf": "cf_rating", "rf": "rf_rating", "dh": "dh_rating",
}

_FIELD_POSITIONS = ["c", "fb", "sb", "tb", "ss", "lf", "cf", "rf"]

# Offense attrs used for position player regressions
OFFENSE_ATTRS = list(BATTING_ATTRS)  # 7 attrs

# Defense attrs — base set (no catcher-specific)
DEFENSE_ATTRS_BASE = [
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    "throwacc_base", "throwpower_base",
]

# Defense attrs — catcher variant (adds catchframe + catchsequence)
DEFENSE_ATTRS_CATCHER = DEFENSE_ATTRS_BASE + [
    "catchframe_base", "catchsequence_base",
]

# Default offense/defense blend ratios per position
DEFAULT_BLEND: Dict[str, Tuple[float, float]] = {
    "c_rating":  (0.15, 0.85),
    "fb_rating": (0.70, 0.30),
    "sb_rating": (0.40, 0.60),
    "tb_rating": (0.50, 0.50),
    "ss_rating": (0.30, 0.70),
    "lf_rating": (0.60, 0.40),
    "cf_rating": (0.30, 0.70),
    "rf_rating": (0.55, 0.45),
    "dh_rating": (1.00, 0.00),
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_position_player_data(
    conn, position_code: str, league_year_id: int, league_level: int,
    min_innings: int, lg_err_rate: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Load players who played a given position with enough innings,
    joined with their batting stats and base attributes.
    """
    offense_cols = ", ".join(f"p.{a}" for a in OFFENSE_ATTRS)
    defense_attrs = DEFENSE_ATTRS_CATCHER if position_code == "c" else DEFENSE_ATTRS_BASE
    defense_cols = ", ".join(f"p.{a}" for a in defense_attrs)

    sql = text(f"""
        SELECT fs.player_id,
               {offense_cols}, {defense_cols},
               fs.innings, fs.errors, fs.putouts, fs.assists,
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.strikeouts,
               bs.stolen_bases, bs.caught_stealing
        FROM player_fielding_stats fs
        JOIN simbbPlayers p ON p.id = fs.player_id
        JOIN teams tm ON tm.id = fs.team_id
        JOIN player_batting_stats bs
            ON bs.player_id = fs.player_id
            AND bs.league_year_id = fs.league_year_id
            AND bs.team_id = fs.team_id
        WHERE fs.league_year_id = :lyid
          AND tm.team_level = :level
          AND fs.position_code = :pos
          AND fs.innings >= :min_inn
          AND bs.at_bats >= 20
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level,
        "pos": position_code, "min_inn": min_innings,
    }).mappings().all()

    err_rate = lg_err_rate.get(position_code, 0.0)

    records = []
    for row in rows:
        # OPS
        ab = float(row["at_bats"])
        h = float(row["hits"])
        d = float(row["doubles_hit"])
        t = float(row["triples"])
        hr = float(row["home_runs"])
        bb = float(row["walks"])
        pa = ab + bb
        obp = (h + bb) / pa if pa > 0 else 0.0
        slg = (h + d + 2 * t + 3 * hr) / ab if ab > 0 else 0.0
        ops = obp + slg

        # Fielding runs
        inn = float(row["innings"])
        errors = float(row["errors"])
        expected_err = err_rate * inn
        fld_runs = (expected_err - errors) * 0.8

        records.append({
            "player_id": int(row["player_id"]),
            "offense_attrs": [float(row.get(a, 0) or 0) for a in OFFENSE_ATTRS],
            "defense_attrs": [float(row.get(a, 0) or 0) for a in defense_attrs],
            "ops": ops,
            "fld_runs": fld_runs,
        })

    return records


def _load_pitcher_data(
    conn, pitcher_type: str, league_year_id: int, league_level: int,
    min_ipo: int,
) -> List[Dict[str, Any]]:
    """
    Load SP or RP pitcher data with attributes and ERA.
    pitcher_type: "SP" (games_started > 0) or "RP" (games_started = 0).
    """
    core_cols = ", ".join(f"p.{a}" for a in PITCHING_CORE_ATTRS)
    gs_filter = "ps.games_started > 0" if pitcher_type == "SP" else "ps.games_started = 0"

    sql = text(f"""
        SELECT ps.player_id,
               {core_cols},
               {_PITCH_SELECT},
               p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
               ps.innings_pitched_outs, ps.earned_runs,
               ps.games_started
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid
          AND tm.team_level = :level
          AND ps.innings_pitched_outs >= :min_ipo
          AND {gs_filter}
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ipo": min_ipo,
    }).mappings().all()

    # Pitcher attrs: core + pitch averages + fielding subset
    pitcher_attr_keys = list(PITCHING_ATTRS) + [
        "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    ]

    records = []
    for row in rows:
        ipo = float(row["innings_pitched_outs"])
        er = float(row["earned_runs"])
        ip = ipo / 3.0
        era = er * 9.0 / ip if ip > 0 else 99.0

        # Build attrs dict
        attrs = {a: float(row.get(a, 0) or 0) for a in PITCHING_CORE_ATTRS}
        attrs.update(_avg_pitch_components(row))
        for fa in ["fieldcatch_base", "fieldreact_base", "fieldspot_base"]:
            attrs[fa] = float(row.get(fa, 0) or 0)

        records.append({
            "player_id": int(row["player_id"]),
            "attrs": attrs,
            "attr_values": [attrs.get(k, 0.0) for k in pitcher_attr_keys],
            "era": era,
        })

    return records, pitcher_attr_keys


def _load_league_error_rates(
    conn, league_year_id: int, league_level: int,
) -> Dict[str, float]:
    """League-wide error rate per position (errors / innings)."""
    rows = conn.execute(text("""
        SELECT fs.position_code,
               SUM(fs.errors) AS total_errors,
               SUM(fs.innings) AS total_innings
        FROM player_fielding_stats fs
        JOIN teams tm ON tm.id = fs.team_id
        WHERE fs.league_year_id = :lyid AND tm.team_level = :level
        GROUP BY fs.position_code
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    rates = {}
    for r in rows:
        inn = float(r["total_innings"] or 1)
        rates[r["position_code"]] = float(r["total_errors"] or 0) / inn if inn > 0 else 0.0
    return rates


# ---------------------------------------------------------------------------
# Normalization & blending
# ---------------------------------------------------------------------------

def _normalize_betas(
    std_betas: List[float], attr_names: List[str],
    negate: bool = False,
) -> Tuple[Dict[str, float], List[str]]:
    """
    Convert standardized betas to normalized weights (sum = 1.0).
    Uses absolute values.  Returns (weights_dict, warnings_list).
    """
    warnings = []
    values = list(std_betas)

    if negate:
        values = [-v for v in values]

    # Flag significantly negative betas (before abs)
    for i, v in enumerate(values):
        if v < -0.1:
            warnings.append(
                f"{attr_names[i]}: negative beta ({v:.3f}) — "
                "attribute may hurt performance at this position"
            )

    abs_vals = [abs(v) for v in values]
    total = sum(abs_vals)

    if total <= 0:
        # All betas are zero — uniform weights
        n = len(attr_names)
        return {a: round(1.0 / n, 6) for a in attr_names}, warnings

    weights = {a: round(abs_vals[i] / total, 6) for i, a in enumerate(attr_names)}
    return weights, warnings


def _blend_weights(
    offense_weights: Dict[str, float],
    defense_weights: Dict[str, float],
    offense_pct: float,
    defense_pct: float,
) -> Dict[str, float]:
    """
    Blend offense and defense weight dicts by their respective percentages.
    Each input dict should already sum to 1.0.
    """
    combined = {}
    for attr, w in offense_weights.items():
        combined[attr] = w * offense_pct
    for attr, w in defense_weights.items():
        combined[attr] = combined.get(attr, 0.0) + w * defense_pct

    # Normalize to exactly 1.0 (handle rounding)
    total = sum(combined.values())
    if total > 0:
        combined = {a: round(v / total, 6) for a, v in combined.items()}

    return combined


# ---------------------------------------------------------------------------
# Per-position calibration
# ---------------------------------------------------------------------------

def _calibrate_position(
    conn, position_code: str, league_year_id: int, league_level: int,
    min_innings: int, blend: Tuple[float, float],
    lg_err_rate: Dict[str, float],
) -> Dict[str, Any]:
    """
    Calibrate weights for a single fielding position.
    Returns: {rating_type, weights, offense_r2, defense_r2, n, warnings}
    """
    rating_type = _POS_RATING_MAP[position_code]
    offense_pct, defense_pct = blend
    defense_attrs = DEFENSE_ATTRS_CATCHER if position_code == "c" else DEFENSE_ATTRS_BASE

    records = _load_position_player_data(
        conn, position_code, league_year_id, league_level,
        min_innings, lg_err_rate,
    )

    result = {
        "rating_type": rating_type,
        "position_code": position_code,
        "n": len(records),
        "offense_r2": None,
        "defense_r2": None,
        "weights": {},
        "warnings": [],
    }

    if len(records) < max(len(OFFENSE_ATTRS), len(defense_attrs)) + 2:
        result["warnings"].append(
            f"Insufficient data: {len(records)} players "
            f"(need {max(len(OFFENSE_ATTRS), len(defense_attrs)) + 2})"
        )
        result["skipped"] = True
        return result

    # Offensive regression: attrs -> OPS
    offense_X = [r["offense_attrs"] for r in records]
    offense_y = [r["ops"] for r in records]
    off_result = _ols_regression(offense_X, offense_y)

    if "error" in off_result:
        result["warnings"].append(f"Offense regression failed: {off_result['error']}")
        offense_weights = {a: 1.0 / len(OFFENSE_ATTRS) for a in OFFENSE_ATTRS}
        result["offense_r2"] = 0.0
    else:
        offense_weights, off_warns = _normalize_betas(
            off_result["std_betas"], OFFENSE_ATTRS
        )
        result["offense_r2"] = off_result["r_squared"]
        result["warnings"].extend(off_warns)

    # DH: offense only
    if position_code == "dh" or defense_pct <= 0:
        result["weights"] = offense_weights
        return result

    # Defensive regression: attrs -> fielding runs
    defense_X = [r["defense_attrs"] for r in records]
    defense_y = [r["fld_runs"] for r in records]
    def_result = _ols_regression(defense_X, defense_y)

    if "error" in def_result:
        result["warnings"].append(f"Defense regression failed: {def_result['error']}")
        defense_weights = {a: 1.0 / len(defense_attrs) for a in defense_attrs}
        result["defense_r2"] = 0.0
    else:
        defense_weights, def_warns = _normalize_betas(
            def_result["std_betas"], defense_attrs
        )
        result["defense_r2"] = def_result["r_squared"]
        result["warnings"].extend(def_warns)

    # Blend
    result["weights"] = _blend_weights(
        offense_weights, defense_weights, offense_pct, defense_pct
    )

    return result


def _calibrate_pitcher(
    conn, pitcher_type: str, league_year_id: int, league_level: int,
    min_ipo: int,
) -> Dict[str, Any]:
    """
    Calibrate weights for SP or RP.
    Returns: {rating_type, weights, r2, n, warnings}
    """
    rating_type = "sp_rating" if pitcher_type == "SP" else "rp_rating"

    records, attr_keys = _load_pitcher_data(
        conn, pitcher_type, league_year_id, league_level, min_ipo,
    )

    result = {
        "rating_type": rating_type,
        "position_code": pitcher_type.lower(),
        "n": len(records),
        "r2": None,
        "weights": {},
        "warnings": [],
    }

    if len(records) < len(attr_keys) + 2:
        result["warnings"].append(
            f"Insufficient data: {len(records)} pitchers "
            f"(need {len(attr_keys) + 2})"
        )
        result["skipped"] = True
        return result

    # Regression: attrs -> ERA (negate betas since lower ERA = better)
    X = [r["attr_values"] for r in records]
    y = [r["era"] for r in records]
    reg_result = _ols_regression(X, y)

    if "error" in reg_result:
        result["warnings"].append(f"Regression failed: {reg_result['error']}")
        result["r2"] = 0.0
        result["weights"] = {a: round(1.0 / len(attr_keys), 6) for a in attr_keys}
    else:
        weights, warns = _normalize_betas(
            reg_result["std_betas"], attr_keys, negate=True
        )
        result["r2"] = reg_result["r_squared"]
        result["weights"] = weights
        result["warnings"].extend(warns)

    return result


# ---------------------------------------------------------------------------
# Main calibration entry point
# ---------------------------------------------------------------------------

def run_calibration(
    conn,
    league_year_id: int,
    league_level: int,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run full calibration across all positions + SP/RP.

    config options:
        min_innings: int (default 50)
        min_ipo: int (default 60)
        blend_ratios: dict of {rating_type: [offense_pct, defense_pct]}
        name: str (profile name)

    Returns: {profile_id, positions: {rating_type: calibration_result}}
    """
    config = config or {}
    min_innings = int(config.get("min_innings", 50))
    min_ipo = int(config.get("min_ipo", 60))
    blend_overrides = config.get("blend_ratios", {})
    profile_name = config.get("name", f"Calibrated (LY{league_year_id} L{league_level})")

    # Load league error rates for fielding runs
    lg_err_rate = _load_league_error_rates(conn, league_year_id, league_level)

    positions_result = {}

    # Position players
    for pos_code in _FIELD_POSITIONS + ["dh"]:
        rating_type = _POS_RATING_MAP[pos_code]
        blend = blend_overrides.get(rating_type)
        if blend:
            blend = (float(blend[0]), float(blend[1]))
        else:
            blend = DEFAULT_BLEND[rating_type]

        try:
            cal = _calibrate_position(
                conn, pos_code, league_year_id, league_level,
                min_innings, blend, lg_err_rate,
            )
            positions_result[rating_type] = cal
        except Exception as e:
            log.exception(f"Calibration failed for {pos_code}")
            positions_result[rating_type] = {
                "rating_type": rating_type,
                "position_code": pos_code,
                "n": 0, "skipped": True,
                "warnings": [f"Exception: {str(e)}"],
                "weights": {},
            }

    # Pitchers
    for ptype in ["SP", "RP"]:
        try:
            cal = _calibrate_pitcher(
                conn, ptype, league_year_id, league_level, min_ipo,
            )
            positions_result[cal["rating_type"]] = cal
        except Exception as e:
            rt = "sp_rating" if ptype == "SP" else "rp_rating"
            log.exception(f"Calibration failed for {ptype}")
            positions_result[rt] = {
                "rating_type": rt,
                "position_code": ptype.lower(),
                "n": 0, "skipped": True,
                "warnings": [f"Exception: {str(e)}"],
                "weights": {},
            }

    # Create profile
    conn.execute(text("""
        INSERT INTO weight_profiles
            (name, description, source, league_year_id, league_level)
        VALUES (:name, :desc, 'calibrated', :lyid, :level)
    """), {
        "name": profile_name,
        "desc": f"OLS regression calibration from league_year {league_year_id}, level {league_level}",
        "lyid": league_year_id,
        "level": league_level,
    })
    profile_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    # Insert weight entries
    for rating_type, cal in positions_result.items():
        if cal.get("skipped"):
            continue
        for attr_key, weight in cal.get("weights", {}).items():
            conn.execute(text("""
                INSERT INTO weight_profile_entries
                    (profile_id, rating_type, attribute_key, weight)
                VALUES (:pid, :rt, :ak, :w)
            """), {
                "pid": profile_id,
                "rt": rating_type,
                "ak": attr_key,
                "w": weight,
            })

    # Log calibration run
    # Strip non-serializable data from results
    results_clean = {}
    for rt, cal in positions_result.items():
        results_clean[rt] = {
            k: v for k, v in cal.items()
            if k != "weights"  # weights are in the profile entries
        }

    conn.execute(text("""
        INSERT INTO calibration_runs (profile_id, config_json, results_json)
        VALUES (:pid, :cfg, :res)
    """), {
        "pid": profile_id,
        "cfg": json.dumps(config),
        "res": json.dumps(results_clean),
    })

    return {
        "profile_id": int(profile_id),
        "name": profile_name,
        "positions": positions_result,
    }


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

def activate_profile(conn, profile_id: int):
    """
    Activate a weight profile: set is_active=1, write entries
    to rating_overall_weights (the live table consumed by rosters).
    """
    # Deactivate all
    conn.execute(text("UPDATE weight_profiles SET is_active = 0"))

    # Activate target
    conn.execute(text(
        "UPDATE weight_profiles SET is_active = 1 WHERE id = :pid"
    ), {"pid": profile_id})

    # Load profile entries
    entries = conn.execute(text("""
        SELECT rating_type, attribute_key, weight
        FROM weight_profile_entries
        WHERE profile_id = :pid
    """), {"pid": profile_id}).all()

    if not entries:
        return {"activated": profile_id, "entries": 0}

    # Collect which rating_types this profile covers
    rating_types = set()
    for e in entries:
        rating_types.add(e[0])

    # Clear existing position weights for those rating types
    for rt in rating_types:
        conn.execute(text(
            "DELETE FROM rating_overall_weights WHERE rating_type = :rt"
        ), {"rt": rt})

    # Insert new weights
    for e in entries:
        conn.execute(text("""
            INSERT INTO rating_overall_weights (rating_type, attribute_key, weight)
            VALUES (:rt, :ak, :w)
            ON DUPLICATE KEY UPDATE weight = :w, updated_at = CURRENT_TIMESTAMP
        """), {"rt": e[0], "ak": e[1], "w": float(e[2])})

    return {"activated": profile_id, "entries": len(entries)}


def get_profiles(conn) -> List[Dict[str, Any]]:
    """List all weight profiles."""
    rows = conn.execute(text("""
        SELECT id, name, description, source, is_active,
               league_year_id, league_level, created_at
        FROM weight_profiles
        ORDER BY created_at DESC
    """)).mappings().all()

    return [dict(r) for r in rows]


def get_profile_detail(conn, profile_id: int) -> Dict[str, Any]:
    """Get a profile with all its weight entries grouped by rating_type."""
    profile = conn.execute(text("""
        SELECT id, name, description, source, is_active,
               league_year_id, league_level, created_at
        FROM weight_profiles WHERE id = :pid
    """), {"pid": profile_id}).mappings().first()

    if not profile:
        return None

    entries = conn.execute(text("""
        SELECT rating_type, attribute_key, weight
        FROM weight_profile_entries
        WHERE profile_id = :pid
        ORDER BY rating_type, attribute_key
    """), {"pid": profile_id}).mappings().all()

    weights_by_type: Dict[str, Dict[str, float]] = {}
    for e in entries:
        weights_by_type.setdefault(e["rating_type"], {})[e["attribute_key"]] = float(e["weight"])

    # Load calibration run if exists
    cal_run = conn.execute(text("""
        SELECT config_json, results_json, created_at
        FROM calibration_runs WHERE profile_id = :pid
        ORDER BY created_at DESC LIMIT 1
    """), {"pid": profile_id}).mappings().first()

    result = dict(profile)
    result["weights"] = weights_by_type
    if cal_run:
        result["calibration"] = {
            "config": json.loads(cal_run["config_json"] or "{}"),
            "results": json.loads(cal_run["results_json"] or "{}"),
            "created_at": str(cal_run["created_at"]),
        }

    return result


def compare_profiles(
    conn, profile_id_a: int, profile_id_b: int,
) -> Dict[str, Any]:
    """Compare two profiles side-by-side."""
    a = get_profile_detail(conn, profile_id_a)
    b = get_profile_detail(conn, profile_id_b)

    if not a or not b:
        return {"error": "profile_not_found"}

    all_types = sorted(set(list(a["weights"].keys()) + list(b["weights"].keys())))

    comparison = {}
    for rt in all_types:
        aw = a["weights"].get(rt, {})
        bw = b["weights"].get(rt, {})
        all_attrs = sorted(set(list(aw.keys()) + list(bw.keys())))

        entries = []
        for attr in all_attrs:
            va = aw.get(attr, 0.0)
            vb = bw.get(attr, 0.0)
            entries.append({
                "attribute": attr,
                "weight_a": round(va, 6),
                "weight_b": round(vb, 6),
                "delta": round(vb - va, 6),
            })
        comparison[rt] = entries

    return {
        "profile_a": {"id": a["id"], "name": a["name"], "source": a["source"]},
        "profile_b": {"id": b["id"], "name": b["name"], "source": b["source"]},
        "comparison": comparison,
    }


def create_manual_profile(
    conn, name: str, description: str, weights: Dict[str, Dict[str, float]],
) -> int:
    """Create a manual profile from user-specified weights."""
    conn.execute(text("""
        INSERT INTO weight_profiles (name, description, source)
        VALUES (:name, :desc, 'manual')
    """), {"name": name, "desc": description})

    profile_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    for rating_type, attr_weights in weights.items():
        for attr_key, weight in attr_weights.items():
            conn.execute(text("""
                INSERT INTO weight_profile_entries
                    (profile_id, rating_type, attribute_key, weight)
                VALUES (:pid, :rt, :ak, :w)
            """), {
                "pid": profile_id,
                "rt": rating_type,
                "ak": attr_key,
                "w": float(weight),
            })

    return int(profile_id)
