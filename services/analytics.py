# services/analytics.py
"""
Analytics service for attribute-vs-stat correlations and WAR computation.
Used by the admin panel tuning tools.
"""

import math
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attribute lists
# ---------------------------------------------------------------------------

BATTING_ATTRS = [
    "contact_base", "power_base", "eye_base", "discipline_base",
    "speed_base", "baserunning_base", "basereaction_base",
]

BATTING_STATS = [
    "AVG", "ISO", "BB_pct", "K_pct", "OBP", "SLG", "OPS", "SB_pct",
    "AB_per_HR", "BABIP", "XBH_pct", "BB_K",
]

PITCHING_CORE_ATTRS = [
    "pendurance_base", "pgencontrol_base", "psequencing_base",
    "pthrowpower_base", "pickoff_base",
]
PITCHING_AGG_ATTRS = ["avg_consist", "avg_pacc", "avg_pbrk", "avg_pcntrl"]
PITCHING_ATTRS = PITCHING_CORE_ATTRS + PITCHING_AGG_ATTRS

PITCHING_STATS = [
    "ERA", "WHIP", "K_per_9", "BB_per_9", "HR_per_9", "K_per_BB",
    "H_per_9", "IP_per_GS", "W_pct", "BABIP_against", "K_pct_p", "BB_pct_p",
]

DEFENSIVE_ATTRS = [
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
    "throwacc_base", "throwpower_base",
    "catchframe_base", "catchsequence_base",
]

DEFENSIVE_STATS = ["Fld_pct", "PO_per_Inn", "A_per_Inn", "E_per_Inn"]

# Display-friendly labels
ATTR_LABELS = {
    "contact_base": "Contact", "power_base": "Power", "eye_base": "Eye",
    "discipline_base": "Discipline", "speed_base": "Speed",
    "baserunning_base": "Baserunning", "basereaction_base": "Base Reaction",
    "pendurance_base": "Endurance", "pgencontrol_base": "Gen Control",
    "psequencing_base": "Sequencing", "pthrowpower_base": "Throw Power",
    "pickoff_base": "Pickoff",
    "avg_consist": "Avg Consistency", "avg_pacc": "Avg Accuracy",
    "avg_pbrk": "Avg Break", "avg_pcntrl": "Avg Control",
    "fieldcatch_base": "Field Catch", "fieldreact_base": "Field React",
    "fieldspot_base": "Field Spot", "throwacc_base": "Throw Acc",
    "throwpower_base": "Throw Power",
    "catchframe_base": "Catch Frame", "catchsequence_base": "Catch Sequence",
}

STAT_LABELS = {
    "AVG": "AVG", "ISO": "ISO", "BB_pct": "BB%", "K_pct": "K%",
    "OBP": "OBP", "SLG": "SLG", "OPS": "OPS", "SB_pct": "SB%",
    "AB_per_HR": "AB/HR", "BABIP": "BABIP", "XBH_pct": "XBH%", "BB_K": "BB/K",
    "ERA": "ERA", "WHIP": "WHIP", "K_per_9": "K/9", "BB_per_9": "BB/9",
    "HR_per_9": "HR/9", "K_per_BB": "K/BB",
    "H_per_9": "H/9", "IP_per_GS": "IP/GS", "W_pct": "W%",
    "BABIP_against": "BABIP Ag", "K_pct_p": "K%", "BB_pct_p": "BB%",
    "Fld_pct": "Fld%", "PO_per_Inn": "PO/Inn",
    "A_per_Inn": "A/Inn", "E_per_Inn": "E/Inn",
}

# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _pearson_r(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 if undefined."""
    n = len(xs)
    if n < 3:
        return 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _linear_regression(
    xs: List[float], ys: List[float]
) -> Tuple[float, float, float]:
    """Returns (slope, intercept, r)."""
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, 0.0
    r = _pearson_r(xs, ys)
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, 0.0, r
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept, r


# ---------------------------------------------------------------------------
# Batting stat derivation
# ---------------------------------------------------------------------------


def _derive_batting_stats(row: Dict[str, Any]) -> Dict[str, float]:
    """Derive rate stats from raw counting stats."""
    ab = float(row["at_bats"])
    h = float(row["hits"])
    d = float(row["doubles_hit"])
    t = float(row["triples"])
    hr = float(row["home_runs"])
    bb = float(row["walks"])
    so = float(row["strikeouts"])
    sb = float(row["stolen_bases"])
    cs = float(row["caught_stealing"])

    pa = ab + bb  # simplified PA (no HBP/SF in our data)
    avg = h / ab if ab > 0 else 0.0
    slg = (h + d + 2 * t + 3 * hr) / ab if ab > 0 else 0.0
    iso = slg - avg
    bb_pct = bb / pa if pa > 0 else 0.0
    k_pct = so / pa if pa > 0 else 0.0
    obp = (h + bb) / pa if pa > 0 else 0.0
    ops = obp + slg
    sb_pct = sb / (sb + cs) if (sb + cs) > 0 else 0.0

    ab_per_hr = ab / hr if hr > 0 else 0.0
    babip_denom = ab - so - hr
    babip = (h - hr) / babip_denom if babip_denom > 0 else 0.0
    xbh_pct = (d + t + hr) / ab if ab > 0 else 0.0
    bb_k = bb / so if so > 0 else bb * 1.0

    return {
        "AVG": avg, "ISO": iso, "BB_pct": bb_pct, "K_pct": k_pct,
        "OBP": obp, "SLG": slg, "OPS": ops, "SB_pct": sb_pct,
        "AB_per_HR": ab_per_hr, "BABIP": babip, "XBH_pct": xbh_pct, "BB_K": bb_k,
    }


# ---------------------------------------------------------------------------
# Pitching stat derivation
# ---------------------------------------------------------------------------


def _derive_pitching_stats(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Derive rate stats from raw pitching counts. Returns None if IPO == 0."""
    ipo = float(row["innings_pitched_outs"])
    if ipo == 0:
        return None
    er = float(row["earned_runs"])
    ha = float(row["hits_allowed"])
    bb = float(row["walks"])
    so = float(row["strikeouts"])
    hra = float(row["home_runs_allowed"])
    gs = float(row.get("games_started", 0) or 0)
    w = float(row.get("wins", 0) or 0)
    l = float(row.get("losses", 0) or 0)

    era = er * 27.0 / ipo
    whip = (bb + ha) * 3.0 / ipo
    k9 = so * 27.0 / ipo
    bb9 = bb * 27.0 / ipo
    hr9 = hra * 27.0 / ipo
    k_bb = so / bb if bb > 0 else so * 1.0
    h9 = ha * 27.0 / ipo
    ip_per_gs = (ipo / 3.0) / gs if gs > 0 else 0.0
    w_pct = w / (w + l) if (w + l) > 0 else 0.0

    # BABIP against: (H - HR) / (BF - SO - HR - BB) approx BF from IPO
    # Approximate BF = IPO/3 * 3 + H + BB (outs + hits + walks)
    babip_denom = ha - hra + (ipo / 3.0 * 3 - so - hra - ha)
    # Simplified: BIP = (ipo/3)*3 - SO + H - HR... let's use standard formula
    # BIP = AB - SO - HR, approximate AB = ipo/3*3 + H - BB (not perfect)
    # Safer: BIP ≈ (ipo/3*3) - SO - HR + (H - HR) = total outs excl SO + hits excl HR
    bip = (ipo / 3.0 * 3 - so) + (ha - hra)  # outs on contact + hits on contact
    babip_ag = (ha - hra) / bip if bip > 0 else 0.0

    # K% and BB% per batter faced; approximate BF = ipo/3*3 + H + BB
    bf_approx = ipo / 3.0 * 3 + ha + bb
    k_pct_p = so / bf_approx if bf_approx > 0 else 0.0
    bb_pct_p = bb / bf_approx if bf_approx > 0 else 0.0

    return {
        "ERA": era, "WHIP": whip, "K_per_9": k9,
        "BB_per_9": bb9, "HR_per_9": hr9, "K_per_BB": k_bb,
        "H_per_9": h9, "IP_per_GS": ip_per_gs, "W_pct": w_pct,
        "BABIP_against": babip_ag, "K_pct_p": k_pct_p, "BB_pct_p": bb_pct_p,
    }


def _avg_pitch_components(row: Dict[str, Any]) -> Dict[str, float]:
    """Average pitch component attributes across non-null pitch slots."""
    components = {"consist": [], "pacc": [], "pbrk": [], "pcntrl": []}
    for i in range(1, 6):
        name_key = f"pitch{i}_name"
        if row.get(name_key):
            for comp in components:
                val = row.get(f"pitch{i}_{comp}_base")
                if val is not None and val != 0:
                    components[comp].append(float(val))
    return {
        f"avg_{comp}": (sum(vals) / len(vals) if vals else 0.0)
        for comp, vals in components.items()
    }


# ---------------------------------------------------------------------------
# Defensive stat derivation
# ---------------------------------------------------------------------------


def _derive_defensive_stats(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Derive fielding rate stats. Returns None if innings == 0."""
    inn = float(row["innings"])
    po = float(row["putouts"])
    a = float(row["assists"])
    e = float(row["errors"])
    if inn == 0:
        return None
    total = po + a + e
    fld_pct = (po + a) / total if total > 0 else 1.0
    return {
        "Fld_pct": fld_pct,
        "PO_per_Inn": po / inn,
        "A_per_Inn": a / inn,
        "E_per_Inn": e / inn,
    }


# ---------------------------------------------------------------------------
# Correlation builders
# ---------------------------------------------------------------------------


def _build_correlation_result(
    rows: List[Dict[str, Any]],
    attr_list: List[str],
    stat_list: List[str],
    attr_extractor,
    stat_extractor,
    drill_attr: Optional[str] = None,
    drill_stat: Optional[str] = None,
):
    """
    Generic correlation builder.

    attr_extractor(row) -> dict of attr_name -> float
    stat_extractor(row) -> dict of stat_name -> float (or None to skip)
    """
    # Build parallel arrays of attribute values and stat values
    records = []
    for row in rows:
        attrs = attr_extractor(row)
        stats = stat_extractor(row)
        if stats is None:
            continue
        records.append({
            "attrs": attrs,
            "stats": stats,
            "name": f"{row.get('firstName', '')} {row.get('lastName', '')}".strip(),
            "player_id": int(row.get("player_id") or row.get("id", 0)),
        })

    n = len(records)
    if n < 3:
        return {"error": "not_enough_data", "n": n}

    # Drill-down mode: return scatter data for one attr/stat pair
    if drill_attr and drill_stat:
        xs = [r["attrs"].get(drill_attr, 0) for r in records]
        ys = [r["stats"].get(drill_stat, 0) for r in records]
        slope, intercept, r = _linear_regression(xs, ys)
        points = [
            {"x": round(r_["attrs"].get(drill_attr, 0), 3),
             "y": round(r_["stats"].get(drill_stat, 0), 4),
             "name": r_["name"],
             "player_id": r_["player_id"],
             "all_stats": {k: round(v, 4) for k, v in r_["stats"].items()},
             "all_attrs": {k: round(v, 1) for k, v in r_["attrs"].items()}}
            for r_ in records
        ]
        return {
            "attr": drill_attr,
            "attr_label": ATTR_LABELS.get(drill_attr, drill_attr),
            "stat": drill_stat,
            "stat_label": STAT_LABELS.get(drill_stat, drill_stat),
            "r": round(r, 4),
            "slope": round(slope, 6),
            "intercept": round(intercept, 6),
            "points": points,
            "n": n,
        }

    # Heatmap mode: compute R for all pairs
    r_matrix = []
    for attr in attr_list:
        row_r = []
        xs = [r["attrs"].get(attr, 0) for r in records]
        for stat in stat_list:
            ys = [r["stats"].get(stat, 0) for r in records]
            row_r.append(round(_pearson_r(xs, ys), 4))
        r_matrix.append(row_r)

    return {
        "attributes": attr_list,
        "attribute_labels": [ATTR_LABELS.get(a, a) for a in attr_list],
        "stats": stat_list,
        "stat_labels": [STAT_LABELS.get(s, s) for s in stat_list],
        "r_matrix": r_matrix,
        "n": n,
    }


# ---------------------------------------------------------------------------
# Public API: Batting correlations
# ---------------------------------------------------------------------------

# Pitch component columns needed for pitching queries
_PITCH_COLS = ", ".join(
    f"p.pitch{i}_{comp}_base, p.pitch{i}_name"
    for i in range(1, 6)
    for comp in ["consist", "pacc", "pbrk", "pcntrl"]
)
# Deduplicate pitch{i}_name (appears 4 times per slot)
_PITCH_SELECT_PARTS = []
for i in range(1, 6):
    _PITCH_SELECT_PARTS.append(f"p.pitch{i}_name")
    for comp in ["consist", "pacc", "pbrk", "pcntrl"]:
        _PITCH_SELECT_PARTS.append(f"p.pitch{i}_{comp}_base")
_PITCH_SELECT = ", ".join(_PITCH_SELECT_PARTS)


def batting_correlations(
    conn,
    league_year_id: int,
    league_level: int,
    min_ab: int = 50,
    drill_attr: Optional[str] = None,
    drill_stat: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute batting attribute vs stat correlations."""
    attr_cols = ", ".join(f"p.{a}" for a in BATTING_ATTRS)
    sql = sa_text(f"""
        SELECT bs.player_id, p.firstName, p.lastName,
               {attr_cols},
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.strikeouts,
               bs.stolen_bases, bs.caught_stealing
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = :level
          AND bs.at_bats >= :min_ab
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ab": min_ab,
    }).mappings().all()

    def attr_ext(row):
        return {a: float(row.get(a, 0) or 0) for a in BATTING_ATTRS}

    return _build_correlation_result(
        rows, BATTING_ATTRS, BATTING_STATS,
        attr_ext, _derive_batting_stats,
        drill_attr, drill_stat,
    )


# ---------------------------------------------------------------------------
# Public API: Pitching correlations
# ---------------------------------------------------------------------------


def pitching_correlations(
    conn,
    league_year_id: int,
    league_level: int,
    min_ipo: int = 60,
    drill_attr: Optional[str] = None,
    drill_stat: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute pitching attribute vs stat correlations."""
    core_cols = ", ".join(f"p.{a}" for a in PITCHING_CORE_ATTRS)
    sql = sa_text(f"""
        SELECT ps.player_id, p.firstName, p.lastName,
               {core_cols},
               {_PITCH_SELECT},
               ps.innings_pitched_outs, ps.hits_allowed, ps.earned_runs,
               ps.walks, ps.strikeouts, ps.home_runs_allowed,
               ps.games_started, ps.wins, ps.losses
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid
          AND tm.team_level = :level
          AND ps.innings_pitched_outs >= :min_ipo
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ipo": min_ipo,
    }).mappings().all()

    def attr_ext(row):
        d = {a: float(row.get(a, 0) or 0) for a in PITCHING_CORE_ATTRS}
        d.update(_avg_pitch_components(row))
        return d

    return _build_correlation_result(
        rows, PITCHING_ATTRS, PITCHING_STATS,
        attr_ext, _derive_pitching_stats,
        drill_attr, drill_stat,
    )


# ---------------------------------------------------------------------------
# Public API: Defensive correlations
# ---------------------------------------------------------------------------


def defensive_correlations(
    conn,
    league_year_id: int,
    league_level: int,
    position_code: Optional[str] = None,
    min_innings: int = 50,
    drill_attr: Optional[str] = None,
    drill_stat: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute defensive attribute vs stat correlations."""
    attr_cols = ", ".join(f"p.{a}" for a in DEFENSIVE_ATTRS)

    where = """
        fs.league_year_id = :lyid
        AND tm.team_level = :level
        AND fs.innings >= :min_inn
    """
    params = {"lyid": league_year_id, "level": league_level, "min_inn": min_innings}

    if position_code:
        where += " AND fs.position_code = :pos"
        params["pos"] = position_code

    sql = sa_text(f"""
        SELECT fs.player_id, p.firstName, p.lastName,
               {attr_cols},
               fs.innings, fs.putouts, fs.assists, fs.errors,
               fs.position_code
        FROM player_fielding_stats fs
        JOIN simbbPlayers p ON p.id = fs.player_id
        JOIN teams tm ON tm.id = fs.team_id
        WHERE {where}
    """)
    rows = conn.execute(sql, params).mappings().all()

    def attr_ext(row):
        return {a: float(row.get(a, 0) or 0) for a in DEFENSIVE_ATTRS}

    result = _build_correlation_result(
        rows, DEFENSIVE_ATTRS, DEFENSIVE_STATS,
        attr_ext, _derive_defensive_stats,
        drill_attr, drill_stat,
    )

    # Add available positions for the filter dropdown
    if "error" not in result and not drill_attr:
        pos_sql = sa_text("""
            SELECT DISTINCT fs.position_code
            FROM player_fielding_stats fs
            JOIN teams tm ON tm.id = fs.team_id
            WHERE fs.league_year_id = :lyid AND tm.team_level = :level
            ORDER BY fs.position_code
        """)
        pos_rows = conn.execute(pos_sql, {
            "lyid": league_year_id, "level": league_level,
        }).all()
        result["positions"] = [r[0] for r in pos_rows]

    return result


# ---------------------------------------------------------------------------
# Public API: WAR leaderboard
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "batting": 1.0, "baserunning": 1.0, "fielding": 1.0, "pitching": 1.0,
}
RUNS_PER_WIN = 10.0


def war_leaderboard(
    conn,
    league_year_id: int,
    league_level: int,
    replacement_pct: float = 0.80,
    min_ab: int = 50,
    min_ipo: int = 60,
    weights: Optional[Dict[str, float]] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Compute custom WAR leaderboard."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # --- Step 1: League averages ---
    lg = conn.execute(sa_text("""
        SELECT
            SUM(bs.hits + bs.walks) AS lg_on_base,
            SUM(bs.at_bats + bs.walks) AS lg_pa,
            SUM(bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs) AS lg_tb,
            SUM(bs.at_bats) AS lg_ab,
            SUM(bs.runs) AS lg_runs,
            SUM(bs.stolen_bases) AS lg_sb,
            SUM(bs.caught_stealing) AS lg_cs
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_pa = float(lg["lg_pa"] or 1)
    lg_ab = float(lg["lg_ab"] or 1)
    lg_runs = float(lg["lg_runs"] or 1)
    lg_obp = float(lg["lg_on_base"] or 0) / lg_pa if lg_pa > 0 else 0.0
    lg_slg = float(lg["lg_tb"] or 0) / lg_ab if lg_ab > 0 else 0.0
    lg_ops = lg_obp + lg_slg
    pa_per_run = lg_pa / lg_runs if lg_runs > 0 else 25.0

    repl_ops = lg_ops * replacement_pct

    # League pitching averages
    lg_pit = conn.execute(sa_text("""
        SELECT
            SUM(ps.earned_runs) AS lg_er,
            SUM(ps.innings_pitched_outs) AS lg_ipo
        FROM player_pitching_stats ps
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_ipo = float(lg_pit["lg_ipo"] or 1)
    lg_er = float(lg_pit["lg_er"] or 0)
    lg_era = lg_er * 27.0 / lg_ipo if lg_ipo > 0 else 4.50
    repl_era = lg_era / replacement_pct if replacement_pct > 0 else lg_era * 1.5

    # League fielding averages by position
    lg_fld_rows = conn.execute(sa_text("""
        SELECT fs.position_code,
               SUM(fs.errors) AS total_errors,
               SUM(fs.innings) AS total_innings
        FROM player_fielding_stats fs
        JOIN teams tm ON tm.id = fs.team_id
        WHERE fs.league_year_id = :lyid AND tm.team_level = :level
        GROUP BY fs.position_code
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    lg_err_rate = {}
    for fr in lg_fld_rows:
        pos = fr["position_code"]
        inn = float(fr["total_innings"] or 1)
        lg_err_rate[pos] = float(fr["total_errors"] or 0) / inn if inn > 0 else 0.0

    # --- Step 2: Position player WAR ---
    bat_sql = sa_text("""
        SELECT bs.player_id, p.firstName, p.lastName, p.ptype,
               tm.team_abbrev,
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.strikeouts,
               bs.stolen_bases, bs.caught_stealing, bs.runs
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = :level
          AND bs.at_bats >= :min_ab
    """)
    bat_rows = conn.execute(bat_sql, {
        "lyid": league_year_id, "level": league_level, "min_ab": min_ab,
    }).mappings().all()

    # Fielding data keyed by player_id -> best position
    fld_sql = sa_text("""
        SELECT fs.player_id, fs.position_code,
               fs.innings, fs.errors, fs.putouts, fs.assists
        FROM player_fielding_stats fs
        JOIN teams tm ON tm.id = fs.team_id
        WHERE fs.league_year_id = :lyid AND tm.team_level = :level
        ORDER BY fs.innings DESC
    """)
    fld_rows = conn.execute(fld_sql, {
        "lyid": league_year_id, "level": league_level,
    }).mappings().all()

    # Build fielding map: player_id -> primary position (most innings)
    player_fld: Dict[int, Dict[str, Any]] = {}
    for fr in fld_rows:
        pid = int(fr["player_id"])
        if pid not in player_fld:
            player_fld[pid] = {
                "position": fr["position_code"],
                "innings": float(fr["innings"] or 0),
                "errors": float(fr["errors"] or 0),
            }

    players = {}
    for row in bat_rows:
        pid = int(row["player_id"])
        ab = float(row["at_bats"])
        h = float(row["hits"])
        d = float(row["doubles_hit"])
        t = float(row["triples"])
        hr = float(row["home_runs"])
        bb = float(row["walks"])
        sb = float(row["stolen_bases"])
        cs = float(row["caught_stealing"])

        pa = ab + bb
        obp = (h + bb) / pa if pa > 0 else 0.0
        slg = (h + d + 2 * t + 3 * hr) / ab if ab > 0 else 0.0
        player_ops = obp + slg

        # Batting runs
        batting_runs = (player_ops - repl_ops) * pa / pa_per_run

        # Baserunning runs
        br_runs = (sb - 2.0 * cs) * 0.2

        # Fielding runs
        fld_runs = 0.0
        pos = "DH"
        fld_data = player_fld.get(pid)
        if fld_data and fld_data["innings"] > 0:
            pos = fld_data["position"]
            expected_err = lg_err_rate.get(pos, 0.0) * fld_data["innings"]
            fld_runs = (expected_err - fld_data["errors"]) * 0.8

        total_runs = (
            batting_runs * w["batting"]
            + br_runs * w["baserunning"]
            + fld_runs * w["fielding"]
        )
        war = total_runs / RUNS_PER_WIN

        players[pid] = {
            "player_id": pid,
            "name": f"{row['firstName']} {row['lastName']}".strip(),
            "team": row["team_abbrev"],
            "position": pos.upper(),
            "type": "position",
            "war": round(war, 2),
            "batting_runs": round(batting_runs, 1),
            "br_runs": round(br_runs, 1),
            "fld_runs": round(fld_runs, 1),
            "pit_runs": 0.0,
        }

    # --- Step 3: Pitcher WAR ---
    pit_sql = sa_text("""
        SELECT ps.player_id, p.firstName, p.lastName, p.ptype,
               tm.team_abbrev,
               ps.innings_pitched_outs, ps.earned_runs,
               ps.wins, ps.losses, ps.games_started
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid
          AND tm.team_level = :level
          AND ps.innings_pitched_outs >= :min_ipo
    """)
    pit_rows = conn.execute(pit_sql, {
        "lyid": league_year_id, "level": league_level, "min_ipo": min_ipo,
    }).mappings().all()

    for row in pit_rows:
        pid = int(row["player_id"])
        ipo = float(row["innings_pitched_outs"])
        er = float(row["earned_runs"])
        ip = ipo / 3.0

        player_era = er * 9.0 / ip if ip > 0 else 99.0
        pit_runs = (repl_era - player_era) * ip / 9.0

        total_runs = pit_runs * w["pitching"]
        war = total_runs / RUNS_PER_WIN

        gs = int(row["games_started"] or 0)
        pos = "SP" if gs > 0 else "RP"

        if pid in players:
            # Two-way player: add pitching to existing
            players[pid]["pit_runs"] = round(pit_runs, 1)
            players[pid]["war"] = round(
                players[pid]["war"] + war, 2
            )
            players[pid]["type"] = "two-way"
        else:
            players[pid] = {
                "player_id": pid,
                "name": f"{row['firstName']} {row['lastName']}".strip(),
                "team": row["team_abbrev"],
                "position": pos,
                "type": "pitcher",
                "war": round(war, 2),
                "batting_runs": 0.0,
                "br_runs": 0.0,
                "fld_runs": 0.0,
                "pit_runs": round(pit_runs, 1),
            }

    # --- Step 4: Sort and paginate ---
    all_players = sorted(players.values(), key=lambda p: p["war"], reverse=True)
    total = len(all_players)
    start = (page - 1) * page_size
    end = start + page_size
    page_players = all_players[start:end]

    for i, p in enumerate(page_players):
        p["rank"] = start + i + 1

    pages = (total + page_size - 1) // page_size if total else 0

    return {
        "leaders": page_players,
        "total": total,
        "page": page,
        "pages": pages,
        "league_averages": {
            "ops": round(lg_ops, 3),
            "era": round(lg_era, 2),
            "pa_per_run": round(pa_per_run, 1),
        },
        "replacement_pct": replacement_pct,
        "repl_ops": round(repl_ops, 3),
        "repl_era": round(repl_era, 2),
        "runs_per_win": RUNS_PER_WIN,
        "weights": w,
    }


# ---------------------------------------------------------------------------
# League years helper
# ---------------------------------------------------------------------------


def get_league_years(conn) -> List[Dict[str, Any]]:
    """Return all league years for dropdown population."""
    rows = conn.execute(sa_text(
        "SELECT id, league_year FROM league_years ORDER BY league_year DESC"
    )).mappings().all()
    return [{"id": int(r["id"]), "league_year": int(r["league_year"])} for r in rows]


# ===================================================================
# ADVANCED ANALYTICS — Multi-Regression, Sensitivity, xStats, etc.
# ===================================================================


# ---------------------------------------------------------------------------
# OLS multiple regression (pure Python, no numpy)
# ---------------------------------------------------------------------------


def _mat_mul(A, B):
    """Multiply matrices A (m×n) and B (n×p) -> (m×p)."""
    m, n, p = len(A), len(A[0]), len(B[0])
    return [[sum(A[i][k] * B[k][j] for k in range(n)) for j in range(p)] for i in range(m)]


def _mat_transpose(A):
    """Transpose matrix A."""
    return [list(row) for row in zip(*A)]


def _mat_inverse(A):
    """Invert square matrix via Gauss-Jordan elimination. Returns None if singular."""
    n = len(A)
    # Augment with identity
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for col in range(n):
        # Find pivot
        max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[max_row][col]) < 1e-12:
            return None  # singular
        aug[col], aug[max_row] = aug[max_row], aug[col]
        pivot = aug[col][col]
        aug[col] = [v / pivot for v in aug[col]]
        for row in range(n):
            if row != col:
                factor = aug[row][col]
                aug[row] = [aug[row][j] - factor * aug[col][j] for j in range(2 * n)]
    return [row[n:] for row in aug]


def _ols_regression(X_raw: List[List[float]], y: List[float]) -> Dict[str, Any]:
    """
    OLS multiple regression.

    X_raw: n×p matrix of predictor values (no intercept column — we add it).
    y: n-vector of response values.

    Returns dict with:
      betas: list of p coefficients (excluding intercept)
      intercept: float
      r_squared: float
      std_betas: list of p standardized coefficients (beta weights)
      predictions: list of n predicted values
      residuals: list of n residuals
    """
    n = len(y)
    p = len(X_raw[0]) if X_raw else 0
    if n < p + 2 or p == 0:
        return {"error": "insufficient_data", "n": n, "p": p}

    # Add intercept column (column 0)
    X = [[1.0] + row for row in X_raw]
    k = p + 1  # total columns including intercept

    Xt = _mat_transpose(X)
    XtX = _mat_mul(Xt, [[X[i][j] for j in range(k)] for i in range(n)])
    XtX_inv = _mat_inverse(XtX)
    if XtX_inv is None:
        return {"error": "singular_matrix", "n": n, "p": p}

    # β = (X'X)⁻¹ X'y
    Xty = [sum(X[i][j] * y[i] for i in range(n)) for j in range(k)]
    betas_full = [sum(XtX_inv[j][m] * Xty[m] for m in range(k)) for j in range(k)]

    intercept = betas_full[0]
    betas = betas_full[1:]

    # Predictions and residuals
    predictions = [sum(X[i][j] * betas_full[j] for j in range(k)) for i in range(n)]
    residuals = [y[i] - predictions[i] for i in range(n)]

    # R²
    y_mean = sum(y) / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    ss_res = sum(r ** 2 for r in residuals)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Standardized betas
    x_stds = []
    for j in range(p):
        col = [X_raw[i][j] for i in range(n)]
        col_mean = sum(col) / n
        col_std = math.sqrt(sum((v - col_mean) ** 2 for v in col) / n) if n > 0 else 1.0
        x_stds.append(col_std if col_std > 0 else 1.0)
    y_std = math.sqrt(sum((yi - y_mean) ** 2 for yi in y) / n) if n > 0 else 1.0
    y_std = y_std if y_std > 0 else 1.0

    std_betas = [betas[j] * x_stds[j] / y_std for j in range(p)]

    return {
        "betas": [round(b, 6) for b in betas],
        "intercept": round(intercept, 6),
        "r_squared": round(r_squared, 4),
        "std_betas": [round(sb, 4) for sb in std_betas],
        "predictions": predictions,
        "residuals": residuals,
    }


# ---------------------------------------------------------------------------
# Confidence / p-value helpers
# ---------------------------------------------------------------------------


def _t_cdf_approx(t_val: float, df: int) -> float:
    """Approximate two-tailed p-value from t-statistic using normal approx for large df."""
    # For df > 30, t-distribution ≈ normal
    # Use the error function approximation
    x = abs(t_val)
    # Approximation of 1 - Phi(x) for standard normal
    a1, a2, a3 = 0.254829592, -0.284496736, 1.421413741
    a4, a5 = -1.453152027, 1.061405429
    pp = 0.3275911
    tt = 1.0 / (1.0 + pp * x / math.sqrt(2))
    phi = 0.5 * (a1 * tt + a2 * tt**2 + a3 * tt**3 + a4 * tt**4 + a5 * tt**5) * math.exp(-x * x / 2)
    return 2.0 * phi  # two-tailed


def _r_to_p(r: float, n: int) -> float:
    """Convert Pearson r to approximate two-tailed p-value."""
    if n < 4 or abs(r) >= 1.0:
        return 1.0
    t_val = r * math.sqrt((n - 2) / (1.0 - r * r))
    return _t_cdf_approx(t_val, n - 2)


def _r_confidence_interval(r: float, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    """Fisher z-transform confidence interval for Pearson r."""
    if n < 4 or abs(r) >= 1.0:
        return (-1.0, 1.0)
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    # z-critical for 95% CI
    z_crit = 1.96 if alpha == 0.05 else 2.576
    lo_z = z - z_crit * se
    hi_z = z + z_crit * se
    lo_r = (math.exp(2 * lo_z) - 1) / (math.exp(2 * lo_z) + 1)
    hi_r = (math.exp(2 * hi_z) - 1) / (math.exp(2 * hi_z) + 1)
    return (round(lo_r, 4), round(hi_r, 4))


# ---------------------------------------------------------------------------
# Generic data loader (reuse across all advanced analytics)
# ---------------------------------------------------------------------------


def _load_batting_records(conn, league_year_id, league_level, min_ab=50):
    """Load batting records with attributes and derived stats."""
    attr_cols = ", ".join(f"p.{a}" for a in BATTING_ATTRS)
    sql = sa_text(f"""
        SELECT bs.player_id, p.firstName, p.lastName,
               {attr_cols},
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.strikeouts,
               bs.stolen_bases, bs.caught_stealing
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid AND tm.team_level = :level
          AND bs.at_bats >= :min_ab
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ab": min_ab,
    }).mappings().all()

    records = []
    for row in rows:
        stats = _derive_batting_stats(row)
        attrs = {a: float(row.get(a, 0) or 0) for a in BATTING_ATTRS}
        records.append({
            "player_id": int(row["player_id"]),
            "name": f"{row['firstName']} {row['lastName']}".strip(),
            "attrs": attrs,
            "stats": stats,
        })
    return records


def _load_pitching_records(conn, league_year_id, league_level, min_ipo=60):
    """Load pitching records with attributes and derived stats."""
    core_cols = ", ".join(f"p.{a}" for a in PITCHING_CORE_ATTRS)
    sql = sa_text(f"""
        SELECT ps.player_id, p.firstName, p.lastName,
               {core_cols},
               {_PITCH_SELECT},
               ps.innings_pitched_outs, ps.hits_allowed, ps.earned_runs,
               ps.walks, ps.strikeouts, ps.home_runs_allowed,
               ps.games_started, ps.wins, ps.losses
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = :level
          AND ps.innings_pitched_outs >= :min_ipo
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ipo": min_ipo,
    }).mappings().all()

    records = []
    for row in rows:
        stats = _derive_pitching_stats(row)
        if stats is None:
            continue
        attrs = {a: float(row.get(a, 0) or 0) for a in PITCHING_CORE_ATTRS}
        attrs.update(_avg_pitch_components(row))
        records.append({
            "player_id": int(row["player_id"]),
            "name": f"{row['firstName']} {row['lastName']}".strip(),
            "attrs": attrs,
            "stats": stats,
            "raw": dict(row),
        })
    return records


# ---------------------------------------------------------------------------
# 1. Multi-Attribute Regression
# ---------------------------------------------------------------------------


def multi_regression(
    conn,
    category: str,  # "batting" | "pitching"
    league_year_id: int,
    league_level: int,
    target_stat: str,
    min_threshold: int = 50,
) -> Dict[str, Any]:
    """
    Fit OLS regression: target_stat ~ all attributes.
    Returns betas, standardized betas, R², and per-player predictions.
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
        attr_list = BATTING_ATTRS
    else:
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)
        attr_list = PITCHING_ATTRS

    if len(records) < len(attr_list) + 2:
        return {"error": "not_enough_data", "n": len(records)}

    # Build X matrix and y vector
    X_raw = [[r["attrs"].get(a, 0) for a in attr_list] for r in records]
    y = [r["stats"].get(target_stat, 0) for r in records]

    result = _ols_regression(X_raw, y)
    if "error" in result:
        return result

    # Build coefficient table
    coefficients = []
    for i, attr in enumerate(attr_list):
        coefficients.append({
            "attribute": attr,
            "label": ATTR_LABELS.get(attr, attr),
            "beta": result["betas"][i],
            "std_beta": result["std_betas"][i],
            "abs_importance": round(abs(result["std_betas"][i]), 4),
        })
    coefficients.sort(key=lambda c: c["abs_importance"], reverse=True)

    # Relative importance (% of total |std_beta|)
    total_abs = sum(c["abs_importance"] for c in coefficients) or 1.0
    for c in coefficients:
        c["pct_importance"] = round(c["abs_importance"] / total_abs * 100, 1)

    # Top over/underperformers
    players_with_residuals = []
    for i, rec in enumerate(records):
        players_with_residuals.append({
            "player_id": rec["player_id"],
            "name": rec["name"],
            "actual": round(y[i], 4),
            "predicted": round(result["predictions"][i], 4),
            "residual": round(result["residuals"][i], 4),
        })
    players_with_residuals.sort(key=lambda p: p["residual"], reverse=True)

    return {
        "target_stat": target_stat,
        "stat_label": STAT_LABELS.get(target_stat, target_stat),
        "r_squared": result["r_squared"],
        "intercept": result["intercept"],
        "coefficients": coefficients,
        "n": len(records),
        "top_overperformers": players_with_residuals[:10],
        "top_underperformers": players_with_residuals[-10:][::-1],
        "residual_std": round(
            math.sqrt(sum(r ** 2 for r in result["residuals"]) / len(result["residuals"])), 4
        ) if result["residuals"] else 0,
    }


# ---------------------------------------------------------------------------
# 2. Attribute Sensitivity Curves
# ---------------------------------------------------------------------------


def sensitivity_curves(
    conn,
    category: str,  # "batting" | "pitching" | "defense"
    league_year_id: int,
    league_level: int,
    target_stat: str,
    attribute: str,
    min_threshold: int = 50,
    num_buckets: int = 10,
) -> Dict[str, Any]:
    """
    Bucket players by attribute deciles, compute mean stat per bucket.
    Shows the shape of the attribute→stat relationship.
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
    elif category == "pitching":
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)
    else:
        return {"error": "unsupported_category"}

    if len(records) < 10:
        return {"error": "not_enough_data", "n": len(records)}

    # Get attribute values
    vals = [(r["attrs"].get(attribute, 0), r["stats"].get(target_stat, 0)) for r in records]
    vals.sort(key=lambda v: v[0])

    # Create equal-width buckets based on attribute range
    attr_vals = [v[0] for v in vals]
    attr_min = min(attr_vals)
    attr_max = max(attr_vals)
    bucket_width = (attr_max - attr_min) / num_buckets if attr_max > attr_min else 1.0

    buckets = []
    for b in range(num_buckets):
        lo = attr_min + b * bucket_width
        hi = lo + bucket_width if b < num_buckets - 1 else attr_max + 0.01
        in_bucket = [v[1] for v in vals if lo <= v[0] < hi]
        if not in_bucket:
            buckets.append({
                "bucket": b,
                "range_lo": round(lo, 1),
                "range_hi": round(hi, 1),
                "label": f"{lo:.0f}-{hi:.0f}",
                "count": 0,
                "mean": None,
                "std": None,
            })
            continue
        mean = sum(in_bucket) / len(in_bucket)
        std = math.sqrt(sum((v - mean) ** 2 for v in in_bucket) / len(in_bucket)) if len(in_bucket) > 1 else 0
        buckets.append({
            "bucket": b,
            "range_lo": round(lo, 1),
            "range_hi": round(hi, 1),
            "label": f"{lo:.0f}-{hi:.0f}",
            "count": len(in_bucket),
            "mean": round(mean, 4),
            "std": round(std, 4),
        })

    # Marginal returns: stat change per bucket
    marginals = []
    for i in range(1, len(buckets)):
        prev = buckets[i - 1]["mean"]
        curr = buckets[i]["mean"]
        if prev is not None and curr is not None:
            marginals.append(round(curr - prev, 4))
        else:
            marginals.append(None)

    # Diminishing returns flag
    diminishing = False
    if len(marginals) >= 3:
        last_three = [m for m in marginals[-3:] if m is not None]
        first_three = [m for m in marginals[:3] if m is not None]
        if last_three and first_three:
            avg_early = sum(abs(m) for m in first_three) / len(first_three)
            avg_late = sum(abs(m) for m in last_three) / len(last_three)
            if avg_early > 0 and avg_late / avg_early < 0.3:
                diminishing = True

    return {
        "attribute": attribute,
        "attr_label": ATTR_LABELS.get(attribute, attribute),
        "target_stat": target_stat,
        "stat_label": STAT_LABELS.get(target_stat, target_stat),
        "buckets": buckets,
        "marginals": marginals,
        "diminishing_returns": diminishing,
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 3. Attribute Isolation / Controlled Comparison
# ---------------------------------------------------------------------------


def attribute_isolation(
    conn,
    category: str,
    league_year_id: int,
    league_level: int,
    target_stat: str,
    test_attr: str,
    control_attrs: List[str],
    min_threshold: int = 50,
) -> Dict[str, Any]:
    """
    Hold control_attrs approximately constant, measure test_attr's effect.
    Splits players into low/high on test_attr while matching on control_attrs.
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
    else:
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)

    if len(records) < 20:
        return {"error": "not_enough_data", "n": len(records)}

    # Split on test_attr median
    test_vals = sorted([r["attrs"].get(test_attr, 0) for r in records])
    median = test_vals[len(test_vals) // 2]

    low_group = [r for r in records if r["attrs"].get(test_attr, 0) < median]
    high_group = [r for r in records if r["attrs"].get(test_attr, 0) >= median]

    def group_stats(group):
        if not group:
            return None
        stat_vals = [r["stats"].get(target_stat, 0) for r in group]
        attr_val = [r["attrs"].get(test_attr, 0) for r in group]
        control_means = {
            a: round(sum(r["attrs"].get(a, 0) for r in group) / len(group), 1)
            for a in control_attrs
        }
        return {
            "count": len(group),
            "mean_stat": round(sum(stat_vals) / len(stat_vals), 4),
            "mean_attr": round(sum(attr_val) / len(attr_val), 1),
            "control_means": control_means,
        }

    low_stats = group_stats(low_group)
    high_stats = group_stats(high_group)

    effect = None
    if low_stats and high_stats:
        effect = round(high_stats["mean_stat"] - low_stats["mean_stat"], 4)

    return {
        "test_attr": test_attr,
        "test_attr_label": ATTR_LABELS.get(test_attr, test_attr),
        "target_stat": target_stat,
        "stat_label": STAT_LABELS.get(target_stat, target_stat),
        "control_attrs": control_attrs,
        "median_split": round(median, 1),
        "low_group": low_stats,
        "high_group": high_stats,
        "effect": effect,
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 4. Expected vs Actual (xStats)
# ---------------------------------------------------------------------------


def xstats_analysis(
    conn,
    category: str,
    league_year_id: int,
    league_level: int,
    min_threshold: int = 50,
) -> Dict[str, Any]:
    """
    For each stat, fit multi-regression on all attributes and return
    predicted vs actual for every player, plus residual diagnostics.
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
        attr_list = BATTING_ATTRS
        stat_list = BATTING_STATS
    else:
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)
        attr_list = PITCHING_ATTRS
        stat_list = PITCHING_STATS

    if len(records) < len(attr_list) + 2:
        return {"error": "not_enough_data", "n": len(records)}

    X_raw = [[r["attrs"].get(a, 0) for a in attr_list] for r in records]

    stat_models = {}
    for stat in stat_list:
        y = [r["stats"].get(stat, 0) for r in records]
        ols = _ols_regression(X_raw, y)
        if "error" in ols:
            continue

        # Residual diagnostics
        resids = ols["residuals"]
        resid_mean = sum(resids) / len(resids)
        resid_std = math.sqrt(sum((r - resid_mean) ** 2 for r in resids) / len(resids))

        stat_models[stat] = {
            "r_squared": ols["r_squared"],
            "resid_std": round(resid_std, 4),
        }

    # Per-player xStats table
    players = []
    for i, rec in enumerate(records):
        player_entry = {
            "player_id": rec["player_id"],
            "name": rec["name"],
            "stats": {},
        }
        for stat in stat_list:
            y = [r["stats"].get(stat, 0) for r in records]
            ols = _ols_regression(X_raw, y)
            if "error" in ols:
                continue
            actual = rec["stats"].get(stat, 0)
            predicted = ols["predictions"][i]
            player_entry["stats"][stat] = {
                "actual": round(actual, 4),
                "expected": round(predicted, 4),
                "residual": round(actual - predicted, 4),
            }
        players.append(player_entry)

    # Sort by total absolute residual (most unusual players)
    for p in players:
        p["total_abs_residual"] = round(
            sum(abs(s["residual"]) for s in p["stats"].values()), 4
        )
    players.sort(key=lambda p: p["total_abs_residual"], reverse=True)

    return {
        "category": category,
        "stat_models": stat_models,
        "stat_labels": {s: STAT_LABELS.get(s, s) for s in stat_list},
        "players": players[:50],  # top 50 most unusual
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 5. Interaction Effects
# ---------------------------------------------------------------------------


def interaction_analysis(
    conn,
    category: str,
    league_year_id: int,
    league_level: int,
    target_stat: str,
    attr_a: str,
    attr_b: str,
    min_threshold: int = 50,
) -> Dict[str, Any]:
    """
    Test if attr_a × attr_b interaction improves prediction of target_stat.
    Compares R² of (a, b) vs (a, b, a×b).
    Also returns a 2D heatmap of mean stat by (attr_a bucket, attr_b bucket).
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
    else:
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)

    if len(records) < 20:
        return {"error": "not_enough_data", "n": len(records)}

    y = [r["stats"].get(target_stat, 0) for r in records]

    # Model without interaction
    X_no_int = [[r["attrs"].get(attr_a, 0), r["attrs"].get(attr_b, 0)] for r in records]
    ols_no = _ols_regression(X_no_int, y)

    # Model with interaction
    X_with_int = [
        [r["attrs"].get(attr_a, 0), r["attrs"].get(attr_b, 0),
         r["attrs"].get(attr_a, 0) * r["attrs"].get(attr_b, 0)]
        for r in records
    ]
    ols_with = _ols_regression(X_with_int, y)

    r2_no = ols_no.get("r_squared", 0)
    r2_with = ols_with.get("r_squared", 0)
    r2_gain = round(r2_with - r2_no, 4)

    # 2D heatmap: 5×5 grid of mean stat
    a_vals = [r["attrs"].get(attr_a, 0) for r in records]
    b_vals = [r["attrs"].get(attr_b, 0) for r in records]
    a_min, a_max = min(a_vals), max(a_vals)
    b_min, b_max = min(b_vals), max(b_vals)
    a_step = (a_max - a_min) / 5 if a_max > a_min else 1
    b_step = (b_max - b_min) / 5 if b_max > b_min else 1

    grid = []
    a_labels = []
    b_labels = []
    for ai in range(5):
        a_lo = a_min + ai * a_step
        a_hi = a_lo + a_step if ai < 4 else a_max + 0.01
        a_labels.append(f"{a_lo:.0f}-{a_hi:.0f}")
        row = []
        for bi in range(5):
            b_lo = b_min + bi * b_step
            b_hi = b_lo + b_step if bi < 4 else b_max + 0.01
            if ai == 0:
                b_labels.append(f"{b_lo:.0f}-{b_hi:.0f}")
            in_cell = [
                r["stats"].get(target_stat, 0)
                for r in records
                if a_lo <= r["attrs"].get(attr_a, 0) < a_hi
                and b_lo <= r["attrs"].get(attr_b, 0) < b_hi
            ]
            cell_mean = round(sum(in_cell) / len(in_cell), 4) if in_cell else None
            row.append({"mean": cell_mean, "n": len(in_cell)})
        grid.append(row)

    return {
        "attr_a": attr_a,
        "attr_a_label": ATTR_LABELS.get(attr_a, attr_a),
        "attr_b": attr_b,
        "attr_b_label": ATTR_LABELS.get(attr_b, attr_b),
        "target_stat": target_stat,
        "stat_label": STAT_LABELS.get(target_stat, target_stat),
        "r2_without_interaction": r2_no,
        "r2_with_interaction": r2_with,
        "r2_gain": r2_gain,
        "interaction_beta": ols_with.get("betas", [0, 0, 0])[2] if not isinstance(ols_with.get("betas"), type(None)) else 0,
        "grid": grid,
        "a_labels": a_labels,
        "b_labels": b_labels,
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 6. Per-Stat Tuning Dashboard
# ---------------------------------------------------------------------------

# Real MLB benchmark ranges (approximate 2023 values)
MLB_BENCHMARKS = {
    "AVG": {"mean": 0.248, "std": 0.030, "label": "AVG"},
    "ISO": {"mean": 0.155, "std": 0.050, "label": "ISO"},
    "BB_pct": {"mean": 0.085, "std": 0.030, "label": "BB%"},
    "K_pct": {"mean": 0.225, "std": 0.050, "label": "K%"},
    "OBP": {"mean": 0.320, "std": 0.035, "label": "OBP"},
    "SLG": {"mean": 0.405, "std": 0.060, "label": "SLG"},
    "OPS": {"mean": 0.725, "std": 0.085, "label": "OPS"},
    "AB_per_HR": {"mean": 26.0, "std": 12.0, "label": "AB/HR"},
    "BABIP": {"mean": 0.300, "std": 0.030, "label": "BABIP"},
    "XBH_pct": {"mean": 0.080, "std": 0.025, "label": "XBH%"},
    "BB_K": {"mean": 0.400, "std": 0.150, "label": "BB/K"},
    "ERA": {"mean": 4.25, "std": 1.20, "label": "ERA"},
    "WHIP": {"mean": 1.30, "std": 0.20, "label": "WHIP"},
    "K_per_9": {"mean": 8.50, "std": 2.50, "label": "K/9"},
    "BB_per_9": {"mean": 3.20, "std": 1.00, "label": "BB/9"},
    "HR_per_9": {"mean": 1.25, "std": 0.50, "label": "HR/9"},
    "H_per_9": {"mean": 8.50, "std": 1.50, "label": "H/9"},
    "IP_per_GS": {"mean": 5.50, "std": 1.00, "label": "IP/GS"},
    "W_pct": {"mean": 0.500, "std": 0.100, "label": "W%"},
    "BABIP_against": {"mean": 0.300, "std": 0.030, "label": "BABIP Ag"},
    "K_pct_p": {"mean": 0.220, "std": 0.050, "label": "K%"},
    "BB_pct_p": {"mean": 0.080, "std": 0.025, "label": "BB%"},
}


def stat_tuning_dashboard(
    conn,
    category: str,
    league_year_id: int,
    league_level: int,
    target_stat: str,
    min_threshold: int = 50,
) -> Dict[str, Any]:
    """
    Single stat deep dive: all attributes ranked by correlation + regression weight,
    distribution comparison to MLB benchmarks, stat-vs-stat correlations.
    """
    if category == "batting":
        records = _load_batting_records(conn, league_year_id, league_level, min_threshold)
        attr_list = BATTING_ATTRS
        stat_list = BATTING_STATS
    else:
        records = _load_pitching_records(conn, league_year_id, league_level, min_threshold)
        attr_list = PITCHING_ATTRS
        stat_list = PITCHING_STATS

    if len(records) < 10:
        return {"error": "not_enough_data", "n": len(records)}

    target_vals = [r["stats"].get(target_stat, 0) for r in records]

    # Per-attribute rankings
    attr_rankings = []
    X_raw = [[r["attrs"].get(a, 0) for a in attr_list] for r in records]
    ols = _ols_regression(X_raw, target_vals)

    for i, attr in enumerate(attr_list):
        xs = [r["attrs"].get(attr, 0) for r in records]
        r = _pearson_r(xs, target_vals)
        p_val = _r_to_p(r, len(records))
        ci = _r_confidence_interval(r, len(records))
        attr_rankings.append({
            "attribute": attr,
            "label": ATTR_LABELS.get(attr, attr),
            "r": round(r, 4),
            "p_value": round(p_val, 4),
            "ci_lo": ci[0],
            "ci_hi": ci[1],
            "significant": p_val < 0.05,
            "std_beta": ols["std_betas"][i] if "std_betas" in ols else 0,
        })
    attr_rankings.sort(key=lambda a: abs(a["r"]), reverse=True)

    # Distribution stats
    dist_mean = sum(target_vals) / len(target_vals)
    dist_std = math.sqrt(sum((v - dist_mean) ** 2 for v in target_vals) / len(target_vals))
    dist_min = min(target_vals)
    dist_max = max(target_vals)
    sorted_vals = sorted(target_vals)
    dist_p25 = sorted_vals[len(sorted_vals) // 4]
    dist_p50 = sorted_vals[len(sorted_vals) // 2]
    dist_p75 = sorted_vals[3 * len(sorted_vals) // 4]

    distribution = {
        "mean": round(dist_mean, 4),
        "std": round(dist_std, 4),
        "min": round(dist_min, 4),
        "max": round(dist_max, 4),
        "p25": round(dist_p25, 4),
        "p50": round(dist_p50, 4),
        "p75": round(dist_p75, 4),
    }

    # Benchmark comparison
    bench = MLB_BENCHMARKS.get(target_stat)
    benchmark = None
    if bench:
        z_score = (dist_mean - bench["mean"]) / bench["std"] if bench["std"] > 0 else 0
        benchmark = {
            "mlb_mean": bench["mean"],
            "mlb_std": bench["std"],
            "sim_mean": round(dist_mean, 4),
            "sim_std": round(dist_std, 4),
            "z_deviation": round(z_score, 2),
            "status": "ok" if abs(z_score) < 1.5 else ("warning" if abs(z_score) < 2.5 else "critical"),
        }

    # Histogram buckets for distribution chart
    hist_buckets = 20
    hist_width = (dist_max - dist_min) / hist_buckets if dist_max > dist_min else 1
    histogram = []
    for b in range(hist_buckets):
        lo = dist_min + b * hist_width
        hi = lo + hist_width if b < hist_buckets - 1 else dist_max + 0.01
        count = sum(1 for v in target_vals if lo <= v < hi)
        histogram.append({
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "count": count,
        })

    # Stat-vs-stat correlations
    stat_correlations = []
    for other_stat in stat_list:
        if other_stat == target_stat:
            continue
        other_vals = [r["stats"].get(other_stat, 0) for r in records]
        r = _pearson_r(target_vals, other_vals)
        stat_correlations.append({
            "stat": other_stat,
            "label": STAT_LABELS.get(other_stat, other_stat),
            "r": round(r, 4),
        })
    stat_correlations.sort(key=lambda s: abs(s["r"]), reverse=True)

    return {
        "target_stat": target_stat,
        "stat_label": STAT_LABELS.get(target_stat, target_stat),
        "r_squared": ols.get("r_squared", 0),
        "attr_rankings": attr_rankings,
        "distribution": distribution,
        "benchmark": benchmark,
        "histogram": histogram,
        "stat_correlations": stat_correlations,
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 7. Player Archetype Validation
# ---------------------------------------------------------------------------

# Archetype definitions (attribute thresholds on 0-100 scale)
BATTING_ARCHETYPES = {
    "Power Hitter": {"power_base": (70, 100), "contact_base": (0, 55)},
    "Contact Hitter": {"contact_base": (70, 100), "power_base": (0, 50)},
    "Toolsy": {"power_base": (50, 100), "contact_base": (50, 100), "speed_base": (60, 100)},
    "Speedster": {"speed_base": (75, 100)},
    "Patient Hitter": {"discipline_base": (70, 100), "eye_base": (65, 100)},
    "Free Swinger": {"discipline_base": (0, 35), "power_base": (50, 100)},
}


def archetype_validation(
    conn,
    league_year_id: int,
    league_level: int,
    min_ab: int = 50,
) -> Dict[str, Any]:
    """
    Classify players into archetypes based on attributes,
    then compare their average stat profiles.
    """
    records = _load_batting_records(conn, league_year_id, league_level, min_ab)
    if len(records) < 20:
        return {"error": "not_enough_data", "n": len(records)}

    def matches_archetype(rec, criteria):
        for attr, (lo, hi) in criteria.items():
            val = rec["attrs"].get(attr, 0)
            if not (lo <= val <= hi):
                return False
        return True

    archetypes = {}
    for arch_name, criteria in BATTING_ARCHETYPES.items():
        members = [r for r in records if matches_archetype(r, criteria)]
        if not members:
            archetypes[arch_name] = {"count": 0, "avg_stats": {}, "avg_attrs": {}}
            continue

        avg_stats = {}
        for stat in BATTING_STATS:
            vals = [r["stats"].get(stat, 0) for r in members]
            avg_stats[stat] = round(sum(vals) / len(vals), 4)

        avg_attrs = {}
        for attr in BATTING_ATTRS:
            vals = [r["attrs"].get(attr, 0) for r in members]
            avg_attrs[attr] = round(sum(vals) / len(vals), 1)

        archetypes[arch_name] = {
            "count": len(members),
            "avg_stats": avg_stats,
            "avg_attrs": avg_attrs,
        }

    # League average for comparison
    lg_avg_stats = {}
    for stat in BATTING_STATS:
        vals = [r["stats"].get(stat, 0) for r in records]
        lg_avg_stats[stat] = round(sum(vals) / len(vals), 4)

    return {
        "archetypes": archetypes,
        "league_average": lg_avg_stats,
        "stat_labels": {s: STAT_LABELS.get(s, s) for s in BATTING_STATS},
        "attr_labels": {a: ATTR_LABELS.get(a, a) for a in BATTING_ATTRS},
        "n": len(records),
    }


# ---------------------------------------------------------------------------
# 8. Pitching Matchup / Pitch Type Analysis
# ---------------------------------------------------------------------------


def pitch_type_analysis(
    conn,
    league_year_id: int,
    league_level: int,
    min_ipo: int = 60,
) -> Dict[str, Any]:
    """
    Group pitchers by primary pitch type (pitch1_name) and show
    average outcomes and attribute profiles per group.
    """
    core_cols = ", ".join(f"p.{a}" for a in PITCHING_CORE_ATTRS)
    sql = sa_text(f"""
        SELECT ps.player_id, p.firstName, p.lastName,
               {core_cols},
               {_PITCH_SELECT},
               p.pitch1_name AS primary_pitch,
               ps.innings_pitched_outs, ps.hits_allowed, ps.earned_runs,
               ps.walks, ps.strikeouts, ps.home_runs_allowed,
               ps.games_started, ps.wins, ps.losses
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = :level
          AND ps.innings_pitched_outs >= :min_ipo
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_ipo": min_ipo,
    }).mappings().all()

    # Also count repertoire size per pitcher
    groups: Dict[str, List] = {}
    for row in rows:
        stats = _derive_pitching_stats(row)
        if stats is None:
            continue
        primary = row.get("primary_pitch") or "Unknown"
        attrs = {a: float(row.get(a, 0) or 0) for a in PITCHING_CORE_ATTRS}
        attrs.update(_avg_pitch_components(row))

        # Count pitches
        pitch_count = sum(1 for i in range(1, 6) if row.get(f"pitch{i}_name"))

        entry = {"stats": stats, "attrs": attrs, "pitch_count": pitch_count}
        groups.setdefault(primary, []).append(entry)

    pitch_types = {}
    for ptype, members in groups.items():
        avg_stats = {}
        for stat in PITCHING_STATS:
            vals = [m["stats"].get(stat, 0) for m in members]
            avg_stats[stat] = round(sum(vals) / len(vals), 4)

        avg_attrs = {}
        for attr in PITCHING_ATTRS:
            vals = [m["attrs"].get(attr, 0) for m in members]
            avg_attrs[attr] = round(sum(vals) / len(vals), 1)

        avg_repertoire = round(sum(m["pitch_count"] for m in members) / len(members), 1)

        pitch_types[ptype] = {
            "count": len(members),
            "avg_stats": avg_stats,
            "avg_attrs": avg_attrs,
            "avg_repertoire_size": avg_repertoire,
        }

    # Repertoire size analysis
    size_groups: Dict[int, List] = {}
    for row in rows:
        stats = _derive_pitching_stats(row)
        if stats is None:
            continue
        pitch_count = sum(1 for i in range(1, 6) if row.get(f"pitch{i}_name"))
        size_groups.setdefault(pitch_count, []).append(stats)

    repertoire_analysis = {}
    for size, members in sorted(size_groups.items()):
        avg_stats = {}
        for stat in PITCHING_STATS:
            vals = [m.get(stat, 0) for m in members]
            avg_stats[stat] = round(sum(vals) / len(vals), 4)
        repertoire_analysis[size] = {"count": len(members), "avg_stats": avg_stats}

    return {
        "pitch_types": pitch_types,
        "repertoire_analysis": repertoire_analysis,
        "stat_labels": {s: STAT_LABELS.get(s, s) for s in PITCHING_STATS},
        "attr_labels": {a: ATTR_LABELS.get(a, a) for a in PITCHING_ATTRS},
        "n": len(rows),
    }


# ---------------------------------------------------------------------------
# 9. Defensive Position-Specific Analysis
# ---------------------------------------------------------------------------


def defensive_position_importance(
    conn,
    league_year_id: int,
    league_level: int,
    min_innings: int = 50,
) -> Dict[str, Any]:
    """
    For each position, show which defensive attributes matter most
    (correlation + multi-regression) and error rate curves by decile.
    """
    attr_cols = ", ".join(f"p.{a}" for a in DEFENSIVE_ATTRS)
    sql = sa_text(f"""
        SELECT fs.player_id, p.firstName, p.lastName,
               {attr_cols},
               fs.innings, fs.putouts, fs.assists, fs.errors,
               fs.position_code
        FROM player_fielding_stats fs
        JOIN simbbPlayers p ON p.id = fs.player_id
        JOIN teams tm ON tm.id = fs.team_id
        WHERE fs.league_year_id = :lyid AND tm.team_level = :level
          AND fs.innings >= :min_inn
    """)
    rows = conn.execute(sql, {
        "lyid": league_year_id, "level": league_level, "min_inn": min_innings,
    }).mappings().all()

    # Group by position
    by_pos: Dict[str, List] = {}
    for row in rows:
        pos = row["position_code"]
        stats = _derive_defensive_stats(row)
        if stats is None:
            continue
        attrs = {a: float(row.get(a, 0) or 0) for a in DEFENSIVE_ATTRS}
        by_pos.setdefault(pos, []).append({"attrs": attrs, "stats": stats})

    positions = {}
    for pos, members in sorted(by_pos.items()):
        if len(members) < 5:
            continue

        # Correlation of each attribute with E/Inn (lower is better)
        e_per_inn = [m["stats"]["E_per_Inn"] for m in members]
        fld_pct = [m["stats"]["Fld_pct"] for m in members]

        attr_importance = []
        for attr in DEFENSIVE_ATTRS:
            xs = [m["attrs"].get(attr, 0) for m in members]
            r_err = _pearson_r(xs, e_per_inn)
            r_fld = _pearson_r(xs, fld_pct)
            p_err = _r_to_p(r_err, len(members))
            attr_importance.append({
                "attribute": attr,
                "label": ATTR_LABELS.get(attr, attr),
                "r_vs_error_rate": round(r_err, 4),
                "r_vs_fielding_pct": round(r_fld, 4),
                "p_value": round(p_err, 4),
                "significant": p_err < 0.05,
            })
        attr_importance.sort(key=lambda a: abs(a["r_vs_fielding_pct"]), reverse=True)

        positions[pos] = {
            "count": len(members),
            "attr_importance": attr_importance,
            "avg_fld_pct": round(sum(fld_pct) / len(fld_pct), 4),
            "avg_e_per_inn": round(sum(e_per_inn) / len(e_per_inn), 4),
        }

    return {
        "positions": positions,
        "attr_labels": {a: ATTR_LABELS.get(a, a) for a in DEFENSIVE_ATTRS},
        "n": len(rows),
    }


# ---------------------------------------------------------------------------
# Stamina Reports
# ---------------------------------------------------------------------------

_DURABILITY_RECOVERY_MULT = {
    "Iron Man":      1.5,
    "Dependable":    1.25,
    "Normal":        1.0,
    "Undependable":  0.75,
    "Tires Easily":  0.5,
}

_REST_RECOVERY_BASE = 5  # per subweek


def stamina_league_overview(conn, league_year_id, league_level=None):
    """League-wide stamina distribution across all players (pitchers + position)."""
    level_filter = "AND tm.team_level = :level" if league_level else ""
    params = {"lyid": league_year_id}
    if league_level:
        params["level"] = league_level

    # Pitchers
    pitcher_sql = sa_text(f"""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability, p.pendurance_base,
               pfs.stamina AS raw_stamina,
               COALESCE(pfs.stamina, 100) AS stamina,
               CASE WHEN pfs.player_id IS NOT NULL THEN 1 ELSE 0 END AS has_fatigue_data,
               tm.team_abbrev, tm.team_level, tm.id AS team_id,
               COALESCE(ps.games, 0) AS games,
               COALESCE(ps.games_started, 0) AS games_started,
               'pitcher' AS player_type
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = ps.league_year_id
        WHERE ps.league_year_id = :lyid
          AND ps.games > 0
          {level_filter}
    """)
    pitcher_rows = conn.execute(pitcher_sql, params).mappings().all()

    # Position players (batters who are not also pitchers)
    batter_sql = sa_text(f"""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability, p.pendurance_base,
               pfs.stamina AS raw_stamina,
               COALESCE(pfs.stamina, 100) AS stamina,
               CASE WHEN pfs.player_id IS NOT NULL THEN 1 ELSE 0 END AS has_fatigue_data,
               tm.team_abbrev, tm.team_level, tm.id AS team_id,
               COALESCE(bs.games, 0) AS games,
               0 AS games_started,
               'position' AS player_type
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = bs.league_year_id
        LEFT JOIN player_pitching_stats ps2
            ON ps2.player_id = p.id AND ps2.league_year_id = bs.league_year_id AND ps2.games > 0
        WHERE bs.league_year_id = :lyid
          AND bs.games > 0
          AND ps2.player_id IS NULL
          {level_filter}
    """)
    batter_rows = conn.execute(batter_sql, params).mappings().all()

    rows = list(pitcher_rows) + list(batter_rows)

    if not rows:
        empty_dist = [0] * 11
        empty_thresh = {"below_95": 0, "below_70": 0, "below_40": 0, "at_zero": 0}
        return {
            "pitcher_distribution": empty_dist, "position_distribution": list(empty_dist),
            "team_averages": [],
            "pitcher_thresholds": dict(empty_thresh),
            "position_thresholds": dict(empty_thresh),
            "total_players": 0, "total_pitchers": 0, "total_position": 0,
            "pitcher_avg_stamina": 0, "position_avg_stamina": 0,
            "pitchers_with_data": 0, "pitchers_no_data": 0,
            "position_with_data": 0, "position_no_data": 0,
        }

    # Separate distribution histograms (0-9, 10-19, ..., 90-100)
    # All players included; those without fatigue rows use COALESCE(stamina, 100)
    p_dist = [0] * 11
    b_dist = [0] * 11
    p_below_95 = p_below_70 = p_below_40 = p_at_zero = 0
    b_below_95 = b_below_70 = b_below_40 = b_at_zero = 0
    p_total_stam = b_total_stam = 0
    total_pitchers = total_position = 0
    p_with_data = p_no_data = 0
    b_with_data = b_no_data = 0
    team_data = {}

    for r in rows:
        s = int(r["stamina"])
        has_data = int(r["has_fatigue_data"]) == 1
        bucket = min(s // 10, 10)
        is_pitcher = r["player_type"] == "pitcher"

        if is_pitcher:
            total_pitchers += 1
            p_total_stam += s
            p_dist[bucket] += 1
            if s < 95: p_below_95 += 1
            if s < 70: p_below_70 += 1
            if s < 40: p_below_40 += 1
            if s == 0: p_at_zero += 1
            if has_data:
                p_with_data += 1
            else:
                p_no_data += 1
        else:
            total_position += 1
            b_total_stam += s
            b_dist[bucket] += 1
            if s < 95: b_below_95 += 1
            if s < 70: b_below_70 += 1
            if s < 40: b_below_40 += 1
            if s == 0: b_at_zero += 1
            if has_data:
                b_with_data += 1
            else:
                b_no_data += 1

        tid = int(r["team_id"])
        if tid not in team_data:
            team_data[tid] = {"team_abbrev": r["team_abbrev"],
                              "team_level": int(r["team_level"]),
                              "pitcher_staminas": [],
                              "position_staminas": [],
                              "pitcher_no_data": 0,
                              "position_no_data": 0}
        if is_pitcher:
            team_data[tid]["pitcher_staminas"].append(s)
            if not has_data:
                team_data[tid]["pitcher_no_data"] += 1
        else:
            team_data[tid]["position_staminas"].append(s)
            if not has_data:
                team_data[tid]["position_no_data"] += 1

    team_averages = []
    for tid, td in team_data.items():
        p_stams = td["pitcher_staminas"]
        b_stams = td["position_staminas"]
        team_averages.append({
            "team_id": tid,
            "team_abbrev": td["team_abbrev"],
            "team_level": td["team_level"],
            "pitcher_count": len(p_stams),
            "pitcher_tracked": len(p_stams) - td["pitcher_no_data"],
            "position_count": len(b_stams),
            "position_tracked": len(b_stams) - td["position_no_data"],
            "avg_pitcher_stamina": round(sum(p_stams) / len(p_stams), 1) if p_stams else None,
            "avg_position_stamina": round(sum(b_stams) / len(b_stams), 1) if b_stams else None,
            "pitcher_below_70": sum(1 for s in p_stams if s < 70),
            "pitcher_below_40": sum(1 for s in p_stams if s < 40),
            "position_below_70": sum(1 for s in b_stams if s < 70),
            "position_below_40": sum(1 for s in b_stams if s < 40),
        })
    team_averages.sort(key=lambda t: (t["avg_pitcher_stamina"] or 100))

    return {
        "pitcher_distribution": p_dist,
        "position_distribution": b_dist,
        "team_averages": team_averages,
        "pitcher_thresholds": {
            "below_95": p_below_95, "below_70": p_below_70,
            "below_40": p_below_40, "at_zero": p_at_zero,
        },
        "position_thresholds": {
            "below_95": b_below_95, "below_70": b_below_70,
            "below_40": b_below_40, "at_zero": b_at_zero,
        },
        "total_players": len(rows),
        "total_pitchers": total_pitchers,
        "total_position": total_position,
        "pitchers_with_data": p_with_data,
        "pitchers_no_data": p_no_data,
        "position_with_data": b_with_data,
        "position_no_data": b_no_data,
        "pitcher_avg_stamina": round(p_total_stam / total_pitchers, 1) if total_pitchers else 0,
        "position_avg_stamina": round(b_total_stam / total_position, 1) if total_position else 0,
    }


def stamina_team_detail(conn, league_year_id, team_id):
    """Per-player stamina detail for a single team (pitchers + position)."""
    # Pitchers
    pitcher_sql = sa_text("""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability, p.pendurance_base,
               COALESCE(pfs.stamina, 100) AS stamina,
               CASE WHEN pfs.player_id IS NOT NULL THEN 1 ELSE 0 END AS has_fatigue_data,
               pfs.last_updated_at,
               COALESCE(ps.games, 0) AS games,
               COALESCE(ps.games_started, 0) AS games_started,
               COALESCE(ps.innings_pitched_outs, 0) AS ipo,
               'pitcher' AS player_type
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = ps.league_year_id
        WHERE ps.league_year_id = :lyid
          AND ps.team_id = :tid
        ORDER BY ps.games_started DESC, ps.games DESC
    """)
    pitcher_rows = conn.execute(pitcher_sql, {"lyid": league_year_id, "tid": team_id}).mappings().all()

    # Position players
    batter_sql = sa_text("""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability, p.pendurance_base,
               COALESCE(pfs.stamina, 100) AS stamina,
               CASE WHEN pfs.player_id IS NOT NULL THEN 1 ELSE 0 END AS has_fatigue_data,
               pfs.last_updated_at,
               COALESCE(bs.games, 0) AS games,
               0 AS games_started,
               0 AS ipo,
               'position' AS player_type
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = bs.league_year_id
        LEFT JOIN player_pitching_stats ps2
            ON ps2.player_id = p.id AND ps2.league_year_id = bs.league_year_id AND ps2.games > 0
        WHERE bs.league_year_id = :lyid
          AND bs.team_id = :tid
          AND bs.games > 0
          AND ps2.player_id IS NULL
        ORDER BY bs.games DESC
    """)
    batter_rows = conn.execute(batter_sql, {"lyid": league_year_id, "tid": team_id}).mappings().all()

    pitchers = []
    for r in pitcher_rows:
        stamina = int(r["stamina"])
        has_data = int(r["has_fatigue_data"]) == 1
        dur = r["durability"] or "Normal"
        recovery_per_sw = round(_REST_RECOVERY_BASE * _DURABILITY_RECOVERY_MULT.get(dur, 1.0))
        if recovery_per_sw < 1:
            recovery_per_sw = 1

        def _subweeks_to(target, stam=stamina, rec=recovery_per_sw):
            if stam >= target:
                return 0
            gap = target - stam
            return (gap + rec - 1) // rec

        ipo = int(r["ipo"])
        pitchers.append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "stamina": stamina,
            "has_fatigue_data": has_data,
            "durability": dur,
            "pendurance_base": round(float(r["pendurance_base"] or 50), 1),
            "games": int(r["games"]),
            "games_started": int(r["games_started"]),
            "ip": f"{ipo // 3}.{ipo % 3}",
            "recovery_per_subweek": recovery_per_sw,
            "subweeks_to_70": _subweeks_to(70) if has_data else None,
            "subweeks_to_100": _subweeks_to(100) if has_data else None,
            "last_updated": str(r["last_updated_at"]) if r["last_updated_at"] else None,
            "player_type": "pitcher",
        })

    position_players = []
    for r in batter_rows:
        stamina = int(r["stamina"])
        has_data = int(r["has_fatigue_data"]) == 1
        dur = r["durability"] or "Normal"
        recovery_per_sw = round(_REST_RECOVERY_BASE * _DURABILITY_RECOVERY_MULT.get(dur, 1.0))
        if recovery_per_sw < 1:
            recovery_per_sw = 1
        games = int(r["games"])

        if has_data:
            # Estimate drain per game from observed stamina loss + estimated recovery received
            stamina_deficit = 100 - stamina
            est_recovery_received = games * recovery_per_sw
            est_drain_per_game = round((stamina_deficit + est_recovery_received) / games, 1) if games else 0
        else:
            est_drain_per_game = None

        def _subweeks_to(target, stam=stamina, rec=recovery_per_sw):
            if stam >= target:
                return 0
            gap = target - stam
            return (gap + rec - 1) // rec

        position_players.append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "stamina": stamina,
            "has_fatigue_data": has_data,
            "durability": dur,
            "games": games,
            "est_drain_per_game": est_drain_per_game,
            "recovery_per_subweek": recovery_per_sw,
            "subweeks_to_70": _subweeks_to(70) if has_data else None,
            "subweeks_to_100": _subweeks_to(100) if has_data else None,
            "last_updated": str(r["last_updated_at"]) if r["last_updated_at"] else None,
            "player_type": "position",
        })

    return {"pitchers": pitchers, "position_players": position_players, "team_id": team_id}


def stamina_availability_report(conn, league_year_id, league_level=None):
    """Per-team player availability at each usage threshold (pitchers + position)."""
    level_filter = "AND tm.team_level = :level" if league_level else ""
    params = {"lyid": league_year_id}
    if league_level:
        params["level"] = league_level

    # Pitchers
    pitcher_sql = sa_text(f"""
        SELECT p.id AS player_id,
               COALESCE(pfs.stamina, 100) AS stamina,
               COALESCE(strat.usage_preference, 'normal') AS usage_pref,
               tm.id AS team_id, tm.team_abbrev, tm.team_level,
               'pitcher' AS player_type
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = ps.league_year_id
        LEFT JOIN playerStrategies strat
            ON strat.playerID = p.id
        WHERE ps.league_year_id = :lyid
          AND ps.games > 0
          {level_filter}
    """)
    pitcher_rows = conn.execute(pitcher_sql, params).mappings().all()

    # Position players
    batter_sql = sa_text(f"""
        SELECT p.id AS player_id,
               COALESCE(pfs.stamina, 100) AS stamina,
               COALESCE(strat.usage_preference, 'normal') AS usage_pref,
               tm.id AS team_id, tm.team_abbrev, tm.team_level,
               'position' AS player_type
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = bs.league_year_id
        LEFT JOIN playerStrategies strat
            ON strat.playerID = p.id
        LEFT JOIN player_pitching_stats ps2
            ON ps2.player_id = p.id AND ps2.league_year_id = bs.league_year_id AND ps2.games > 0
        WHERE bs.league_year_id = :lyid
          AND bs.games > 0
          AND ps2.player_id IS NULL
          {level_filter}
    """)
    batter_rows = conn.execute(batter_sql, params).mappings().all()

    rows = list(pitcher_rows) + list(batter_rows)

    team_data = {}

    for r in rows:
        tid = int(r["team_id"])
        is_pitcher = r["player_type"] == "pitcher"
        if tid not in team_data:
            team_data[tid] = {
                "team_id": tid, "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "total_pitchers": 0, "total_position": 0,
                "pitcher_avail_95": 0, "pitcher_avail_70": 0, "pitcher_avail_40": 0,
                "position_avail_95": 0, "position_avail_70": 0, "position_avail_40": 0,
            }
        td = team_data[tid]
        s = int(r["stamina"])
        prefix = "pitcher" if is_pitcher else "position"
        if is_pitcher:
            td["total_pitchers"] += 1
        else:
            td["total_position"] += 1
        if s >= 95:
            td[f"{prefix}_avail_95"] += 1
        if s >= 70:
            td[f"{prefix}_avail_70"] += 1
        if s >= 40:
            td[f"{prefix}_avail_40"] += 1

    teams = []
    for td in team_data.values():
        if td["pitcher_avail_70"] < 3:
            danger = "critical"
        elif td["pitcher_avail_70"] < 5:
            danger = "warning"
        else:
            danger = "ok"
        # Position player danger
        if td["position_avail_70"] < 6:
            pos_danger = "critical"
        elif td["position_avail_70"] < 9:
            pos_danger = "warning"
        else:
            pos_danger = "ok"
        td["pitcher_danger"] = danger
        td["position_danger"] = pos_danger
        # Overall danger = worst of the two
        danger_order = {"critical": 0, "warning": 1, "ok": 2}
        td["danger_level"] = danger if danger_order[danger] < danger_order[pos_danger] else pos_danger
        teams.append(td)

    teams.sort(key=lambda t: (t["pitcher_avail_70"] + t["position_avail_70"]))
    return {"teams": teams}


def stamina_consumption_analysis(conn, league_year_id, league_level=None):
    """Per-player workload and stamina consumption analysis (pitchers + position)."""
    level_filter = "AND tm.team_level = :level" if league_level else ""
    params = {"lyid": league_year_id}
    if league_level:
        params["level"] = league_level

    # Pitchers
    p_sql = sa_text(f"""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability, p.pendurance_base,
               COALESCE(pfs.stamina, 100) AS stamina,
               ps.games, ps.games_started, ps.innings_pitched_outs AS ipo,
               tm.team_abbrev, tm.team_level
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = ps.league_year_id
        WHERE ps.league_year_id = :lyid
          AND ps.games > 0
          {level_filter}
        ORDER BY ps.games DESC
    """)
    p_rows = conn.execute(p_sql, params).mappings().all()

    pitchers = []
    p_total_games = sum(int(r["games"]) for r in p_rows) if p_rows else 0
    p_avg_games = p_total_games / len(p_rows) if p_rows else 0

    for r in p_rows:
        games = int(r["games"])
        gs = int(r["games_started"])
        ipo = int(r["ipo"])
        stamina = int(r["stamina"])
        pend = float(r["pendurance_base"] or 50)
        pend_mult = 1.3 - (pend / 100.0) * 0.6

        if gs > 0 and games > gs:
            avg_ipo_gs = ipo * 0.8 / gs if gs else 0
            avg_ipo_rp = ipo * 0.2 / (games - gs) if (games - gs) else 0
            est_drain = int((gs * (30 + avg_ipo_gs) + (games - gs) * (15 + avg_ipo_rp)) * pend_mult)
        elif gs > 0:
            avg_ipo = ipo / gs if gs else 0
            est_drain = int(gs * (30 + avg_ipo) * pend_mult)
        else:
            avg_ipo = ipo / games if games else 0
            est_drain = int(games * (15 + avg_ipo) * pend_mult)

        avg_cost = round(est_drain / games, 1) if games else 0
        overworked = stamina < 40 and games > p_avg_games

        pitchers.append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "team_abbrev": r["team_abbrev"],
            "team_level": int(r["team_level"]),
            "games": games, "gs": gs,
            "ip": f"{ipo // 3}.{ipo % 3}",
            "current_stamina": stamina,
            "durability": r["durability"] or "Normal",
            "pendurance_base": round(pend, 1),
            "est_total_consumed": est_drain,
            "avg_cost_per_game": avg_cost,
            "overworked": overworked,
        })

    pitchers.sort(key=lambda p: p["est_total_consumed"], reverse=True)

    # Position players
    b_sql = sa_text(f"""
        SELECT p.id AS player_id, p.firstName, p.lastName,
               p.durability,
               pfs.stamina AS raw_stamina,
               COALESCE(pfs.stamina, 100) AS stamina,
               CASE WHEN pfs.player_id IS NOT NULL THEN 1 ELSE 0 END AS has_fatigue_data,
               bs.games,
               tm.team_abbrev, tm.team_level
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        LEFT JOIN player_fatigue_state pfs
            ON pfs.player_id = p.id AND pfs.league_year_id = bs.league_year_id
        LEFT JOIN player_pitching_stats ps2
            ON ps2.player_id = p.id AND ps2.league_year_id = bs.league_year_id AND ps2.games > 0
        WHERE bs.league_year_id = :lyid
          AND bs.games > 0
          AND ps2.player_id IS NULL
          {level_filter}
        ORDER BY bs.games DESC
    """)
    b_rows = conn.execute(b_sql, params).mappings().all()

    position_players = []
    b_total_games = sum(int(r["games"]) for r in b_rows) if b_rows else 0
    b_avg_games = b_total_games / len(b_rows) if b_rows else 0

    for r in b_rows:
        games = int(r["games"])
        stamina = int(r["stamina"])
        has_data = int(r["has_fatigue_data"]) == 1
        dur = r["durability"] or "Normal"
        recovery_per_sw = round(_REST_RECOVERY_BASE * _DURABILITY_RECOVERY_MULT.get(dur, 1.0))
        if has_data:
            # Estimate net drain from observed deficit + recovery already received
            # Each subweek they get recovery, so total recovery received ≈ games * recovery_per_sw
            # (rough: ~1 game per subweek means they've had ~games subweeks of recovery)
            stamina_deficit = 100 - stamina
            est_recovery_received = games * recovery_per_sw
            est_drain = stamina_deficit + est_recovery_received
            avg_cost = round(est_drain / games, 1) if games else 0
        else:
            est_drain = None
            avg_cost = None
        fatigued = has_data and stamina < 70 and games > b_avg_games

        position_players.append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "team_abbrev": r["team_abbrev"],
            "team_level": int(r["team_level"]),
            "games": games,
            "current_stamina": stamina,
            "has_fatigue_data": has_data,
            "durability": dur,
            "recovery_per_subweek": recovery_per_sw,
            "est_total_consumed": est_drain,
            "avg_cost_per_game": avg_cost,
            "fatigued": fatigued,
        })

    position_players.sort(key=lambda p: (0 if p["has_fatigue_data"] else 1, p["current_stamina"]))

    return {
        "pitchers": pitchers,
        "pitcher_avg_games": round(p_avg_games, 1),
        "position_players": position_players,
        "position_avg_games": round(b_avg_games, 1),
    }


def stamina_flow_history(conn, league_year_id, team_id=None):
    """Reconstruct stamina flow per week from game pitching lines."""
    team_filter = "AND gpl.team_id = :tid" if team_id else ""
    params = {"lyid": league_year_id}
    if team_id:
        params["tid"] = team_id

    sql = sa_text(f"""
        SELECT gr.season_week, gr.season_subweek,
               gpl.player_id, gpl.innings_pitched_outs AS ipo,
               gpl.games_started AS gs
        FROM game_pitching_lines gpl
        JOIN game_results gr ON gr.game_id = gpl.game_id
        WHERE gpl.league_year_id = :lyid
          {team_filter}
        ORDER BY gr.season_week, gr.season_subweek
    """)
    rows = conn.execute(sql, params).mappings().all()

    # Get average durability multiplier for recovery estimates
    dur_sql_filter = "AND gpl.team_id = :tid" if team_id else ""
    dur_sql = sa_text(f"""
        SELECT AVG(
            CASE p.durability
                WHEN 'Iron Man' THEN 1.5
                WHEN 'Dependable' THEN 1.25
                WHEN 'Normal' THEN 1.0
                WHEN 'Undependable' THEN 0.75
                WHEN 'Tires Easily' THEN 0.5
                ELSE 1.0
            END
        ) AS avg_dur_mult
        FROM (
            SELECT DISTINCT gpl.player_id
            FROM game_pitching_lines gpl
            WHERE gpl.league_year_id = :lyid {dur_sql_filter}
        ) ids
        JOIN simbbPlayers p ON p.id = ids.player_id
    """)
    dur_row = conn.execute(dur_sql, params).mappings().first()
    avg_dur_mult = float(dur_row["avg_dur_mult"]) if dur_row and dur_row["avg_dur_mult"] else 1.0

    # Group by week; track per-subweek appearances per pitcher
    week_data = {}
    for r in rows:
        wk = int(r["season_week"])
        if wk not in week_data:
            week_data[wk] = {"drain": 0, "appearances": 0,
                             "unique_pitchers": set()}
        ipo = int(r["ipo"])
        gs = int(r["gs"])
        cost = (30 + ipo) if gs > 0 else (15 + ipo)
        week_data[wk]["drain"] += cost
        week_data[wk]["appearances"] += 1
        week_data[wk]["unique_pitchers"].add(int(r["player_id"]))

    if not week_data:
        return {"weeks": []}

    # Count total unique pitchers across all weeks for recovery estimate
    all_pitchers = set()
    for wd in week_data.values():
        all_pitchers |= wd["unique_pitchers"]
    total_pitchers = len(all_pitchers) if all_pitchers else 1

    # Recovery per subweek per pitcher (adjusted for avg durability)
    recovery_per_sw = _REST_RECOVERY_BASE * avg_dur_mult

    weeks = []
    running_avg = 100.0
    for wk in sorted(week_data.keys()):
        wd = week_data[wk]
        pitched_count = len(wd["unique_pitchers"])
        resting_count = max(0, total_pitchers - pitched_count)
        # 4 subweeks per week; each appearance uses 1 subweek (no recovery
        # that subweek). Resting pitchers get all 4 subweeks of recovery.
        # Pitched pitchers get (4 - appearances_that_week) subweeks.
        # Total recovery subweeks = total_pitchers * 4 - appearances
        total_recovery_subweeks = max(0, total_pitchers * 4 - wd["appearances"])
        est_recovery = round(total_recovery_subweeks * recovery_per_sw)
        net = est_recovery - wd["drain"]
        # Approximate avg stamina change per pitcher
        avg_change = net / total_pitchers
        running_avg = max(0, min(100, running_avg + avg_change))

        weeks.append({
            "week": wk,
            "total_drain": wd["drain"],
            "appearances": wd["appearances"],
            "pitchers_used": pitched_count,
            "pitchers_resting": resting_count,
            "est_recovery": est_recovery,
            "net_change": net,
            "projected_avg_stamina": round(running_avg, 1),
        })

    return {"weeks": weeks, "total_pitchers": total_pitchers,
            "avg_durability_mult": round(avg_dur_mult, 2)}


# ---------------------------------------------------------------------------
# Contact Type Batting Breakdown
# ---------------------------------------------------------------------------


def contact_type_breakdown(
    conn,
    league_year_id: int,
    league_level: int,
    min_ab: int = 30,
) -> Dict[str, Any]:
    """
    Analyse batting outcomes alongside configured contact odds and distance
    weights for a given level.  Returns:

    * **config** — the contact_odds and distance_weights currently stored in
      the DB for this league_level (what the engine uses).
    * **outcome_summary** — aggregate batting outcome rates (HR%, 2B%, 3B%,
      1B%, BABIP, K%, BB%, ISO, SLG) for the level.
    * **tiers** — players bucketed into power tiers (quintiles) with per-tier
      outcome rates so you can see how attribute distribution interacts with
      the contact config.
    * **player_leaders** — top-N players by ISO, barrel-proxy (HR/AB), BABIP
      for quick spot-checks.
    """

    # ── 1. Load configured contact odds & distance weights ──────────────
    odds_sql = sa_text("""
        SELECT ct.name AS contact_type, co.odds, ct.sort_order
        FROM level_contact_odds co
        JOIN contact_types ct ON ct.id = co.contact_type_id
        WHERE co.league_level = :level
        ORDER BY ct.sort_order
    """)
    odds_rows = conn.execute(odds_sql, {"level": league_level}).mappings().all()
    contact_odds = {r["contact_type"]: float(r["odds"]) for r in odds_rows}

    dist_sql = sa_text("""
        SELECT ct.name AS contact_type, dz.name AS distance_zone, dw.weight
        FROM level_distance_weights dw
        JOIN contact_types ct ON ct.id = dw.contact_type_id
        JOIN distance_zones dz ON dz.id = dw.distance_zone_id
        WHERE dw.league_level = :level
        ORDER BY ct.sort_order, dz.sort_order
    """)
    dist_rows = conn.execute(dist_sql, {"level": league_level}).mappings().all()
    distance_weights: Dict[str, Dict[str, float]] = {}
    for r in dist_rows:
        ct = r["contact_type"]
        distance_weights.setdefault(ct, {})[r["distance_zone"]] = float(r["weight"])

    # Normalise contact_odds to percentages
    total_odds = sum(contact_odds.values()) or 1.0
    contact_odds_pct = {k: round(v / total_odds * 100, 2) for k, v in contact_odds.items()}

    # ── 1b. Load fielding weights (contact type → outcome distribution) ─
    fw_sql = sa_text("""
        SELECT ct.name AS contact_type, fo.name AS outcome, fw.weight
        FROM level_fielding_weights fw
        JOIN contact_types ct ON ct.id = fw.contact_type_id
        JOIN fielding_outcomes fo ON fo.id = fw.fielding_outcome_id
        WHERE fw.league_level = :level
        ORDER BY ct.sort_order, fo.sort_order
    """)
    fw_rows = conn.execute(fw_sql, {"level": league_level}).mappings().all()
    fielding_weights: Dict[str, Dict[str, float]] = {}
    for r in fw_rows:
        ct = r["contact_type"]
        fielding_weights.setdefault(ct, {})[r["outcome"]] = float(r["weight"])

    # Compute expected outcome distribution from config:
    # For each outcome, sum(contact_odds_pct[ct] * fielding_weight_pct[ct][outcome])
    expected_outcomes: Dict[str, float] = {}
    if contact_odds_pct and fielding_weights:
        # Normalise fielding weights per contact type to percentages
        fw_pct: Dict[str, Dict[str, float]] = {}
        for ct, outcomes in fielding_weights.items():
            total_w = sum(outcomes.values()) or 1.0
            fw_pct[ct] = {o: v / total_w * 100 for o, v in outcomes.items()}

        all_outcomes = set()
        for fw in fw_pct.values():
            all_outcomes.update(fw.keys())

        for outcome in sorted(all_outcomes):
            expected = 0.0
            for ct, ct_pct in contact_odds_pct.items():
                expected += (ct_pct / 100.0) * fw_pct.get(ct, {}).get(outcome, 0.0)
            expected_outcomes[outcome] = round(expected, 2)

    # ── 2. Aggregate batting outcome rates for this level ───────────────
    agg_sql = sa_text("""
        SELECT
            COUNT(DISTINCT bs.player_id) AS n_batters,
            SUM(bs.at_bats) AS total_ab,
            SUM(bs.hits) AS total_h,
            SUM(bs.doubles_hit) AS total_2b,
            SUM(bs.triples) AS total_3b,
            SUM(bs.home_runs) AS total_hr,
            SUM(bs.inside_the_park_hr) AS total_itphr,
            SUM(bs.walks) AS total_bb,
            SUM(bs.strikeouts) AS total_k,
            SUM(bs.runs) AS total_r,
            SUM(bs.stolen_bases) AS total_sb,
            SUM(bs.caught_stealing) AS total_cs
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = :level
          AND bs.at_bats >= :min_ab
    """)
    agg = conn.execute(agg_sql, {
        "lyid": league_year_id, "level": league_level, "min_ab": min_ab,
    }).mappings().first()

    ab = float(agg["total_ab"] or 0)
    h = float(agg["total_h"] or 0)
    d = float(agg["total_2b"] or 0)
    t = float(agg["total_3b"] or 0)
    hr = float(agg["total_hr"] or 0)
    itphr = float(agg["total_itphr"] or 0)
    bb = float(agg["total_bb"] or 0)
    k = float(agg["total_k"] or 0)
    singles = h - d - t - hr

    pa = ab + bb
    outcome_summary = {}
    if ab > 0 and pa > 0:
        avg = h / ab
        slg = (singles + 2 * d + 3 * t + 4 * hr) / ab
        obp = (h + bb) / pa
        iso = slg - avg
        babip = (h - hr) / (ab - k - hr) if (ab - k - hr) > 0 else 0.0
        outcome_summary = {
            "n_batters": int(agg["n_batters"] or 0),
            "total_pa": int(pa),
            "total_ab": int(ab),
            "AVG": round(avg, 4),
            "OBP": round(obp, 4),
            "SLG": round(slg, 4),
            "OPS": round(obp + slg, 4),
            "ISO": round(iso, 4),
            "BABIP": round(babip, 4),
            "HR_pct": round((hr - itphr) / ab * 100, 2),
            "ITPHR_pct": round(itphr / ab * 100, 2),
            "2B_pct": round(d / ab * 100, 2),
            "3B_pct": round(t / ab * 100, 2),
            "1B_pct": round(singles / ab * 100, 2),
            "K_pct": round(k / pa * 100, 2),
            "BB_pct": round(bb / pa * 100, 2),
            "XBH_pct": round((d + t + hr) / ab * 100, 2),
            "HR_per_AB": round(ab / hr, 1) if hr > 0 else None,
            "SB_pct": round(
                float(agg["total_sb"]) / (float(agg["total_sb"]) + float(agg["total_cs"])) * 100, 1
            ) if (int(agg["total_sb"] or 0) + int(agg["total_cs"] or 0)) > 0 else None,
        }

    # ── 3. Power-tier breakdown ─────────────────────────────────────────
    player_sql = sa_text("""
        SELECT bs.player_id, p.firstName, p.lastName,
               p.power_base, p.contact_base,
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.inside_the_park_hr, bs.walks, bs.strikeouts
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = :level
          AND bs.at_bats >= :min_ab
        ORDER BY p.power_base DESC
    """)
    players = conn.execute(player_sql, {
        "lyid": league_year_id, "level": league_level, "min_ab": min_ab,
    }).mappings().all()

    # Build per-player derived stats
    player_data = []
    for row in players:
        p_ab = float(row["at_bats"])
        p_h = float(row["hits"])
        p_2b = float(row["doubles_hit"])
        p_3b = float(row["triples"])
        p_hr = float(row["home_runs"])
        p_itphr = float(row["inside_the_park_hr"] or 0)
        p_bb = float(row["walks"])
        p_k = float(row["strikeouts"])
        p_pa = p_ab + p_bb
        if p_ab == 0 or p_pa == 0:
            continue
        p_singles = p_h - p_2b - p_3b - p_hr
        p_avg = p_h / p_ab
        p_slg = (p_singles + 2 * p_2b + 3 * p_3b + 4 * p_hr) / p_ab
        p_iso = p_slg - p_avg
        p_babip = (p_h - p_hr) / (p_ab - p_k - p_hr) if (p_ab - p_k - p_hr) > 0 else 0.0

        player_data.append({
            "player_id": int(row["player_id"]),
            "name": f"{row['firstName']} {row['lastName']}".strip(),
            "power": float(row["power_base"] or 0),
            "contact": float(row["contact_base"] or 0),
            "ab": int(p_ab),
            "AVG": round(p_avg, 4),
            "SLG": round(p_slg, 4),
            "ISO": round(p_iso, 4),
            "BABIP": round(p_babip, 4),
            "HR_pct": round((p_hr - p_itphr) / p_ab * 100, 2),
            "ITPHR_pct": round(p_itphr / p_ab * 100, 2),
            "2B_pct": round(p_2b / p_ab * 100, 2),
            "3B_pct": round(p_3b / p_ab * 100, 2),
            "K_pct": round(p_k / p_pa * 100, 2),
            "BB_pct": round(p_bb / p_pa * 100, 2),
            "XBH_pct": round((p_2b + p_3b + p_hr) / p_ab * 100, 2),
        })

    # Bucket into power quintiles
    n = len(player_data)
    tiers = []
    if n >= 5:
        tier_size = n // 5
        tier_labels = ["Bottom 20%", "20-40%", "40-60%", "60-80%", "Top 20%"]
        # Sort by power ascending for quintile bucketing
        sorted_players = sorted(player_data, key=lambda p: p["power"])
        for i, label in enumerate(tier_labels):
            start = i * tier_size
            end = start + tier_size if i < 4 else n
            bucket = sorted_players[start:end]
            if not bucket:
                continue

            stats_to_avg = ["AVG", "SLG", "ISO", "BABIP", "HR_pct", "ITPHR_pct", "2B_pct",
                            "3B_pct", "K_pct", "BB_pct", "XBH_pct"]
            avg_stats = {}
            for stat in stats_to_avg:
                vals = [p[stat] for p in bucket]
                avg_stats[stat] = round(sum(vals) / len(vals), 4)

            power_vals = [p["power"] for p in bucket]
            contact_vals = [p["contact"] for p in bucket]
            tiers.append({
                "label": label,
                "count": len(bucket),
                "power_range": [round(min(power_vals), 1), round(max(power_vals), 1)],
                "avg_power": round(sum(power_vals) / len(power_vals), 1),
                "avg_contact": round(sum(contact_vals) / len(contact_vals), 1),
                "stats": avg_stats,
            })

    # ── 3b. Contact-tier breakdown ────────────────────────────────────
    contact_tiers = []
    if n >= 5:
        tier_size = n // 5
        tier_labels = ["Bottom 20%", "20-40%", "40-60%", "60-80%", "Top 20%"]
        sorted_by_contact = sorted(player_data, key=lambda p: p["contact"])
        for i, label in enumerate(tier_labels):
            start = i * tier_size
            end = start + tier_size if i < 4 else n
            bucket = sorted_by_contact[start:end]
            if not bucket:
                continue

            stats_to_avg = ["AVG", "SLG", "ISO", "BABIP", "HR_pct", "ITPHR_pct", "2B_pct",
                            "3B_pct", "K_pct", "BB_pct", "XBH_pct"]
            avg_stats = {}
            for stat in stats_to_avg:
                vals = [p[stat] for p in bucket]
                avg_stats[stat] = round(sum(vals) / len(vals), 4)

            power_vals = [p["power"] for p in bucket]
            contact_vals = [p["contact"] for p in bucket]
            contact_tiers.append({
                "label": label,
                "count": len(bucket),
                "contact_range": [round(min(contact_vals), 1), round(max(contact_vals), 1)],
                "avg_power": round(sum(power_vals) / len(power_vals), 1),
                "avg_contact": round(sum(contact_vals) / len(contact_vals), 1),
                "stats": avg_stats,
            })

    # ── 3c. Per-contact-type expected batting profile ─────────────────
    per_contact_type = []
    if fielding_weights and contact_odds_pct:
        for ct in sorted(contact_odds_pct.keys(),
                         key=lambda c: next(
                             (r["sort_order"] for r in odds_rows
                              if r["contact_type"] == c), 99)):
            fw = fielding_weights.get(ct, {})
            fw_total = sum(fw.values()) or 1.0
            fw_norm = {o: v / fw_total for o, v in fw.items()}

            # Map fielding outcomes to batting stat categories
            out_rate = fw_norm.get("out", 0)
            single_rate = fw_norm.get("single", 0)
            double_rate = fw_norm.get("double", 0)
            triple_rate = fw_norm.get("triple", 0)
            hr_rate = fw_norm.get("homerun", 0) + fw_norm.get("inside_the_park_hr", 0)
            itphr_rate = fw_norm.get("inside_the_park_hr", 0)
            hit_rate = single_rate + double_rate + triple_rate + hr_rate

            # Compute expected slash line for balls put in play as this contact type
            avg = hit_rate
            slg = (single_rate + 2 * double_rate + 3 * triple_rate + 4 * hr_rate) if hit_rate > 0 else 0
            iso = slg - avg if avg > 0 else 0

            per_contact_type.append({
                "contact_type": ct,
                "frequency_pct": contact_odds_pct.get(ct, 0),
                "out_pct": round(out_rate * 100, 2),
                "1B_pct": round(single_rate * 100, 2),
                "2B_pct": round(double_rate * 100, 2),
                "3B_pct": round(triple_rate * 100, 2),
                "HR_pct": round((hr_rate - itphr_rate) * 100, 2),
                "ITPHR_pct": round(itphr_rate * 100, 2),
                "hit_pct": round(hit_rate * 100, 2),
                "AVG": round(avg, 4),
                "SLG": round(slg, 4),
                "ISO": round(iso, 4),
            })

    # ── 4. Player leaders ───────────────────────────────────────────────
    top_n = 10
    leaders = {
        "iso": sorted(player_data, key=lambda p: p["ISO"], reverse=True)[:top_n],
        "hr_pct": sorted(player_data, key=lambda p: p["HR_pct"], reverse=True)[:top_n],
        "babip": sorted(player_data, key=lambda p: p["BABIP"], reverse=True)[:top_n],
        "xbh_pct": sorted(player_data, key=lambda p: p["XBH_pct"], reverse=True)[:top_n],
        "k_pct_low": sorted(player_data, key=lambda p: p["K_pct"])[:top_n],
    }

    return {
        "config": {
            "contact_odds": contact_odds,
            "contact_odds_pct": contact_odds_pct,
            "distance_weights": distance_weights,
            "fielding_weights": fielding_weights,
            "expected_outcomes": expected_outcomes,
        },
        "outcome_summary": outcome_summary,
        "tiers": tiers,
        "contact_tiers": contact_tiers,
        "per_contact_type": per_contact_type,
        "leaders": leaders,
        "n": len(player_data),
    }


# ===================================================================
# HR Depth Analysis — play-by-play home run breakdown
# ===================================================================


def hr_depth_analysis(
    conn,
    league_year_id: int,
    league_level: int,
    game_type: str = "regular",
) -> Dict[str, Any]:
    """
    Parse play-by-play JSON from game_results to break down home runs
    by Batted Ball (contact type) and Hit Depth.

    Returns cross-tabulation counts plus marginal totals for charting.
    """
    import json as _json

    # Resolve season IDs for this league_year_id
    season_sql = sa_text("""
        SELECT s.id
        FROM seasons s
        JOIN league_years ly ON ly.league_year = s.year
        WHERE ly.id = :lyid
    """)
    season_rows = conn.execute(season_sql, {"lyid": league_year_id}).all()
    season_ids = [r[0] for r in season_rows]
    if not season_ids:
        return {"total_hr": 0, "total_itphr": 0, "cross_tab": [],
                "by_contact_type": [], "by_hit_depth": [], "games_scanned": 0}

    # Fetch PBP blobs — only games that have PBP data
    placeholders = ", ".join(f":sid{i}" for i in range(len(season_ids)))
    params: Dict[str, Any] = {f"sid{i}": sid for i, sid in enumerate(season_ids)}
    params["level"] = league_level
    params["gtype"] = game_type

    pbp_sql = sa_text(f"""
        SELECT gr.play_by_play_json
        FROM game_results gr
        WHERE gr.season IN ({placeholders})
          AND gr.league_level = :level
          AND gr.game_type = :gtype
          AND gr.play_by_play_json IS NOT NULL
    """)
    rows = conn.execute(pbp_sql, params).all()

    # Parse all PBP and collect HR plays
    from collections import Counter

    cross_counter: Counter = Counter()  # (batted_ball, hit_depth) -> count
    hr_total = 0
    itphr_total = 0
    games_scanned = len(rows)

    for (pbp_raw,) in rows:
        if not pbp_raw:
            continue
        try:
            plays = _json.loads(pbp_raw) if isinstance(pbp_raw, str) else pbp_raw
        except (ValueError, TypeError):
            continue
        if not isinstance(plays, list):
            continue

        for play in plays:
            if not isinstance(play, dict):
                continue
            # Only look at plays where the at-bat ended
            if not play.get("AB_Over"):
                continue

            def_outcome = play.get("Defensive Outcome")
            is_hr = play.get("Is_Homerun", False)
            if not is_hr and def_outcome not in ("homerun", "inside_the_park_hr"):
                continue

            batted_ball = play.get("Batted Ball") or "unknown"
            hit_depth = play.get("Hit Depth") or "unknown"

            # Normalise None-string values
            if batted_ball in ("None", "none"):
                batted_ball = "unknown"
            if hit_depth in ("None", "none"):
                hit_depth = "unknown"

            cross_counter[(batted_ball, hit_depth)] += 1
            hr_total += 1
            if def_outcome == "inside_the_park_hr":
                itphr_total += 1

    # Build cross-tab rows
    cross_tab = []
    for (bb, hd), count in sorted(cross_counter.items(), key=lambda x: -x[1]):
        cross_tab.append({
            "batted_ball": bb,
            "hit_depth": hd,
            "count": count,
            "pct": round(count / hr_total * 100, 1) if hr_total else 0,
        })

    # Marginals — by contact type
    contact_counter: Counter = Counter()
    for (bb, _), count in cross_counter.items():
        contact_counter[bb] += count
    by_contact_type = [
        {"batted_ball": bb, "count": c,
         "pct": round(c / hr_total * 100, 1) if hr_total else 0}
        for bb, c in sorted(contact_counter.items(), key=lambda x: -x[1])
    ]

    # Marginals — by hit depth
    depth_counter: Counter = Counter()
    for (_, hd), count in cross_counter.items():
        depth_counter[hd] += count
    by_hit_depth = [
        {"hit_depth": hd, "count": c,
         "pct": round(c / hr_total * 100, 1) if hr_total else 0}
        for hd, c in sorted(depth_counter.items(), key=lambda x: -x[1])
    ]

    return {
        "total_hr": hr_total,
        "total_itphr": itphr_total,
        "games_scanned": games_scanned,
        "cross_tab": cross_tab,
        "by_contact_type": by_contact_type,
        "by_hit_depth": by_hit_depth,
    }
