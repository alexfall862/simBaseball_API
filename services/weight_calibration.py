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


def _confidence_level(n: int, p: int) -> str:
    """Sample size confidence: high (n>=10p), moderate (n>=3p), low (n>=p+2)."""
    if n >= 10 * p:
        return "high"
    elif n >= 3 * p:
        return "moderate"
    return "low"


def _vif_warnings(vif: List[float], attr_names: List[str]) -> List[str]:
    """Generate warnings for high VIF (multicollinearity)."""
    warnings = []
    for i, v in enumerate(vif):
        if v > 10.0:
            warnings.append(f"{attr_names[i]}: VIF={v:.1f} — severe multicollinearity")
        elif v > 5.0:
            warnings.append(f"{attr_names[i]}: VIF={v:.1f} — moderate multicollinearity")
    return warnings


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

    n = len(records)
    p_max = max(len(OFFENSE_ATTRS), len(defense_attrs))

    result = {
        "rating_type": rating_type,
        "position_code": position_code,
        "n": n,
        "confidence_level": _confidence_level(n, p_max),
        "offense_r2": None,
        "offense_adj_r2": None,
        "defense_r2": None,
        "defense_adj_r2": None,
        "weights": {},
        "warnings": [],
    }

    if n < p_max + 2:
        result["warnings"].append(
            f"Insufficient data: {n} players "
            f"(need {p_max + 2})"
        )
        result["skipped"] = True
        return result

    # Ridge fallback for small samples
    off_ridge = 0.1 if n < 5 * len(OFFENSE_ATTRS) else 0.0
    def_ridge = 0.1 if n < 5 * len(defense_attrs) else 0.0

    # Offensive regression: attrs -> OPS
    offense_X = [r["offense_attrs"] for r in records]
    offense_y = [r["ops"] for r in records]
    off_result = _ols_regression(offense_X, offense_y, ridge_lambda=off_ridge)

    if "error" in off_result:
        result["warnings"].append(f"Offense regression failed: {off_result['error']}")
        offense_weights = {a: 1.0 / len(OFFENSE_ATTRS) for a in OFFENSE_ATTRS}
        result["offense_r2"] = 0.0
        result["offense_adj_r2"] = 0.0
    else:
        offense_weights, off_warns = _normalize_betas(
            off_result["std_betas"], OFFENSE_ATTRS
        )
        result["offense_r2"] = off_result["r_squared"]
        result["offense_adj_r2"] = off_result["adj_r_squared"]
        result["warnings"].extend(off_warns)
        if off_result.get("vif"):
            result["warnings"].extend(_vif_warnings(off_result["vif"], OFFENSE_ATTRS))
        if off_ridge > 0:
            result["warnings"].append(f"Offense: Ridge regression used (lambda={off_ridge}, small sample)")

    # DH: offense only
    if position_code == "dh" or defense_pct <= 0:
        result["weights"] = offense_weights
        return result

    # Defensive regression: attrs -> fielding runs
    defense_X = [r["defense_attrs"] for r in records]
    defense_y = [r["fld_runs"] for r in records]
    def_result = _ols_regression(defense_X, defense_y, ridge_lambda=def_ridge)

    if "error" in def_result:
        result["warnings"].append(f"Defense regression failed: {def_result['error']}")
        defense_weights = {a: 1.0 / len(defense_attrs) for a in defense_attrs}
        result["defense_r2"] = 0.0
        result["defense_adj_r2"] = 0.0
    else:
        defense_weights, def_warns = _normalize_betas(
            def_result["std_betas"], defense_attrs
        )
        result["defense_r2"] = def_result["r_squared"]
        result["defense_adj_r2"] = def_result["adj_r_squared"]
        result["warnings"].extend(def_warns)
        if def_result.get("vif"):
            result["warnings"].extend(_vif_warnings(def_result["vif"], defense_attrs))
        if def_ridge > 0:
            result["warnings"].append(f"Defense: Ridge regression used (lambda={def_ridge}, small sample)")

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

    n = len(records)
    p = len(attr_keys)

    result = {
        "rating_type": rating_type,
        "position_code": pitcher_type.lower(),
        "n": n,
        "confidence_level": _confidence_level(n, p),
        "r2": None,
        "adj_r2": None,
        "weights": {},
        "warnings": [],
    }

    if n < p + 2:
        result["warnings"].append(
            f"Insufficient data: {n} pitchers "
            f"(need {p + 2})"
        )
        result["skipped"] = True
        return result

    # Ridge fallback for small samples
    ridge = 0.1 if n < 5 * p else 0.0

    # Regression: attrs -> ERA (negate betas since lower ERA = better)
    X = [r["attr_values"] for r in records]
    y = [r["era"] for r in records]
    reg_result = _ols_regression(X, y, ridge_lambda=ridge)

    if "error" in reg_result:
        result["warnings"].append(f"Regression failed: {reg_result['error']}")
        result["r2"] = 0.0
        result["adj_r2"] = 0.0
        result["weights"] = {a: round(1.0 / p, 6) for a in attr_keys}
    else:
        weights, warns = _normalize_betas(
            reg_result["std_betas"], attr_keys, negate=True
        )
        result["r2"] = reg_result["r_squared"]
        result["adj_r2"] = reg_result["adj_r_squared"]
        result["weights"] = weights
        result["warnings"].extend(warns)
        if reg_result.get("vif"):
            result["warnings"].extend(_vif_warnings(reg_result["vif"], attr_keys))
        if ridge > 0:
            result["warnings"].append(f"Ridge regression used (lambda={ridge}, small sample)")

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
    # Use the default if name is missing OR explicitly None (dict.get only
    # falls back when the key is absent, not when the value is None).
    profile_name = config.get("name") or f"Calibrated (LY{league_year_id} L{league_level})"

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

    # Collect all position-specific weights into a single dict so we can
    # synthesize the generic pitcher_overall / position_overall backstops
    # from them and persist all 13 rating types in the profile.
    weights_by_type: Dict[str, Dict[str, float]] = {}
    for rating_type, cal in positions_result.items():
        if cal.get("skipped"):
            continue
        wts = cal.get("weights", {})
        if wts:
            weights_by_type[rating_type] = dict(wts)

    # Synthesize pitcher_overall + position_overall as initial seed values.
    # These are persisted in weight_profile_entries like any other rating
    # type so admins can edit them in the profile UI without losing the
    # values on subsequent profile activations.
    backstops = _synthesize_backstop_weights(weights_by_type)
    for bs_rt, bs_weights in backstops.items():
        weights_by_type[bs_rt] = bs_weights

    # Insert all weight entries (11 position-specific + 2 generic backstops)
    for rating_type, attr_weights in weights_by_type.items():
        for attr_key, weight in attr_weights.items():
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

_POSITION_PLAYER_RATINGS = frozenset({
    "c_rating", "fb_rating", "sb_rating", "tb_rating", "ss_rating",
    "lf_rating", "cf_rating", "rf_rating", "dh_rating",
})
_PITCHER_RATINGS = frozenset({"sp_rating", "rp_rating"})


def _synthesize_backstop_weights(
    weights_by_type: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """
    Derive generic pitcher_overall / position_overall backstop weights by
    averaging across the position-specific weights in a profile.

    These backstops are used for players without an assigned listed position.
    Only generates a backstop if the profile does not already include
    pitcher_overall / position_overall explicitly.
    """
    result: Dict[str, Dict[str, float]] = {}

    # position_overall = average of all position-player rating weights
    if "position_overall" not in weights_by_type:
        pos_sets = [
            wt for rt, wt in weights_by_type.items()
            if rt in _POSITION_PLAYER_RATINGS and wt
        ]
        if pos_sets:
            all_attrs: set = set()
            for wt in pos_sets:
                all_attrs.update(wt.keys())
            avg: Dict[str, float] = {}
            for attr in all_attrs:
                vals = [wt.get(attr, 0.0) for wt in pos_sets]
                avg[attr] = sum(vals) / len(pos_sets)
            # Normalize so weights sum to 1.0
            total = sum(avg.values())
            if total > 0:
                avg = {k: v / total for k, v in avg.items()}
            result["position_overall"] = avg

    # pitcher_overall = average of SP + RP weights
    if "pitcher_overall" not in weights_by_type:
        pit_sets = [
            wt for rt, wt in weights_by_type.items()
            if rt in _PITCHER_RATINGS and wt
        ]
        if pit_sets:
            all_attrs_p: set = set()
            for wt in pit_sets:
                all_attrs_p.update(wt.keys())
            avg_p: Dict[str, float] = {}
            for attr in all_attrs_p:
                vals = [wt.get(attr, 0.0) for wt in pit_sets]
                avg_p[attr] = sum(vals) / len(pit_sets)
            total_p = sum(avg_p.values())
            if total_p > 0:
                avg_p = {k: v / total_p for k, v in avg_p.items()}
            result["pitcher_overall"] = avg_p

    return result


def activate_profile(conn, profile_id: int):
    """
    Activate a weight profile: set is_active=1, write all profile entries
    to rating_overall_weights (the live table consumed by rosters).

    The profile is the single source of truth — every rating type that
    exists in weight_profile_entries (including pitcher_overall and
    position_overall) is written verbatim. There is no synthesis or
    auto-overwrite path: manual edits to pitcher_overall/position_overall
    in the profile editor are preserved across activations.
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
    weights_by_type: Dict[str, Dict[str, float]] = {}
    for e in entries:
        rt = str(e[0])
        rating_types.add(rt)
        weights_by_type.setdefault(rt, {})[str(e[1])] = float(e[2])

    # Clear existing weights for all rating types in this profile
    for rt in rating_types:
        conn.execute(text(
            "DELETE FROM rating_overall_weights WHERE rating_type = :rt"
        ), {"rt": rt})

    # Insert all profile weights into the live table
    insert_count = 0
    for rt, attr_weights in weights_by_type.items():
        for ak, w in attr_weights.items():
            conn.execute(text("""
                INSERT INTO rating_overall_weights (rating_type, attribute_key, weight)
                VALUES (:rt, :ak, :w)
                ON DUPLICATE KEY UPDATE weight = :w, updated_at = CURRENT_TIMESTAMP
            """), {"rt": rt, "ak": ak, "w": w})
            insert_count += 1

    return {
        "activated": profile_id,
        "entries": insert_count,
        "rating_types": sorted(rating_types),
    }


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


def update_profile_weights(
    conn, profile_id: int, weights: Dict[str, Dict[str, float]],
) -> int:
    """
    Replace all weight entries for an existing profile.
    Marks the profile source as 'manual' if it was 'calibrated'.
    """
    # Verify profile exists
    row = conn.execute(text(
        "SELECT id, source FROM weight_profiles WHERE id = :pid"
    ), {"pid": profile_id}).first()
    if not row:
        raise ValueError(f"Profile {profile_id} not found")

    # Update source to manual if was calibrated
    if row[1] == "calibrated":
        conn.execute(text(
            "UPDATE weight_profiles SET source = 'manual' WHERE id = :pid"
        ), {"pid": profile_id})

    # Delete existing entries and re-insert
    conn.execute(text(
        "DELETE FROM weight_profile_entries WHERE profile_id = :pid"
    ), {"pid": profile_id})

    count = 0
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
            count += 1

    return count


# NOTE: _resolve_ovr_weights, _compute_raw_ovr_for_row, _POS_CODE_TO_RATING_TYPE,
# _percentile_rank_to_20_80, and recompute_displayovr were deleted in the canonical
# displayovr refactor. Use services.ovr_core.compute_displayovr() and
# services.ovr_core.recompute_stored_displayovr() instead.
