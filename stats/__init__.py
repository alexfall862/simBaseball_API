# stats/__init__.py
"""
Stats blueprint: leaderboards, player stats, team stats, splits, injuries, positions.
"""

import logging
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

logger = logging.getLogger(__name__)

stats_bp = Blueprint("stats", __name__)


# ---------------------------------------------------------------------------
# Batting leaderboard
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/batting")
def batting_leaderboard():
    """
    Batting leaderboard from player_batting_stats.

    Query params:
      league_year_id (required), league_level, team_id, position,
      sort (any stat key, default avg), order (asc|desc),
      min_pa (default 0), page, page_size (default 50)
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    position = request.args.get("position")
    sort = request.args.get("sort", "avg")
    order = request.args.get("order", "").lower()
    min_pa = request.args.get("min_pa", 0, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    # SQL expressions for every sortable stat
    _pa = "(bs.at_bats + bs.walks)"
    _avg = "IF(bs.at_bats > 0, bs.hits / bs.at_bats, 0)"
    _obp = f"IF({_pa} > 0, (bs.hits + bs.walks) / {_pa}, 0)"
    _slg = ("IF(bs.at_bats > 0, (bs.hits + bs.doubles_hit "
            "+ 2*bs.triples + 3*bs.home_runs) / bs.at_bats, 0)")
    _iso = f"IF(bs.at_bats > 0, (bs.doubles_hit + 2*bs.triples + 3*bs.home_runs) / bs.at_bats, 0)"
    _ops = f"({_obp} + {_slg})"
    _babip = ("IF(bs.at_bats - bs.strikeouts - bs.home_runs > 0, "
              "(bs.hits - bs.home_runs) / (bs.at_bats - bs.strikeouts - bs.home_runs), 0)")
    _bb_pct = f"IF({_pa} > 0, bs.walks / {_pa}, 0)"
    _k_pct = f"IF({_pa} > 0, bs.strikeouts / {_pa}, 0)"
    _bb_k = "IF(bs.strikeouts > 0, bs.walks / bs.strikeouts, 0)"
    _ab_hr = "IF(bs.home_runs > 0, bs.at_bats / bs.home_runs, 0)"
    _xbh_pct = ("IF(bs.at_bats > 0, (bs.doubles_hit + bs.triples "
                "+ bs.home_runs) / bs.at_bats, 0)")
    _sb_pct = ("IF(bs.stolen_bases + bs.caught_stealing > 0, "
               "bs.stolen_bases / (bs.stolen_bases + bs.caught_stealing), 0)")
    _tb = "(bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs)"

    # Default sort direction: DESC for counting/rate stats, ASC for ab_hr/k_pct
    asc_defaults = {"ab_hr", "k_pct"}
    if not order:
        order = "ASC" if sort in asc_defaults else "DESC"
    else:
        order = "ASC" if order == "asc" else "DESC"

    sort_expr_map = {
        "avg": _avg, "obp": _obp, "slg": _slg, "ops": _ops,
        "iso": _iso, "babip": _babip,
        "bb_pct": _bb_pct, "k_pct": _k_pct, "bb_k": _bb_k,
        "ab_hr": _ab_hr, "xbh_pct": _xbh_pct, "sb_pct": _sb_pct,
        "g": "bs.games", "ab": "bs.at_bats", "pa": _pa,
        "r": "bs.runs", "h": "bs.hits", "2b": "bs.doubles_hit",
        "3b": "bs.triples", "hr": "bs.home_runs", "rbi": "bs.rbi",
        "bb": "bs.walks", "so": "bs.strikeouts",
        "sb": "bs.stolen_bases", "cs": "bs.caught_stealing",
        "tb": _tb,
    }
    sort_expr = sort_expr_map.get(sort, _avg)
    order_by = f"{sort_expr} {order}"

    where_parts = ["bs.league_year_id = :lyid",
                    f"{_pa} >= :min_pa"]
    params = {"lyid": league_year_id, "min_pa": min_pa}

    if team_id:
        where_parts.append("bs.team_id = :tid")
        params["tid"] = team_id
    if league_level:
        where_parts.append("tm.team_level = :ll")
        params["ll"] = league_level

    join_pos = ""
    if position:
        join_pos = ("JOIN player_fielding_stats fs_pos "
                    "ON fs_pos.player_id = bs.player_id "
                    "AND fs_pos.league_year_id = bs.league_year_id "
                    "AND fs_pos.team_id = bs.team_id "
                    "AND fs_pos.position_code = :pos")
        params["pos"] = position

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                {join_pos}
                WHERE {where_sql}
            """), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT bs.player_id, bs.team_id, bs.games, bs.at_bats,
                       bs.runs, bs.hits, bs.doubles_hit, bs.triples,
                       bs.home_runs, bs.inside_the_park_hr,
                       bs.rbi, bs.walks, bs.strikeouts,
                       bs.stolen_bases, bs.caught_stealing,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level
                FROM player_batting_stats bs
                JOIN simbbPlayers p ON p.id = bs.player_id
                JOIN teams tm ON tm.id = bs.team_id
                {join_pos}
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        leaders = []
        for i, r in enumerate(rows):
            ab = int(r["at_bats"])
            h = int(r["hits"])
            bb = int(r["walks"])
            so = int(r["strikeouts"])
            hr = int(r["home_runs"])
            itphr = int(r["inside_the_park_hr"])
            d = int(r["doubles_hit"])
            t = int(r["triples"])
            sb = int(r["stolen_bases"])
            cs = int(r["caught_stealing"])
            pa = ab + bb
            tb = h + d + 2 * t + 3 * hr

            avg_val = h / ab if ab else 0
            obp_val = (h + bb) / pa if pa else 0
            slg_val = tb / ab if ab else 0
            iso_val = slg_val - avg_val
            ops_val = obp_val + slg_val
            babip_denom = ab - so - hr
            babip_val = (h - hr) / babip_denom if babip_denom > 0 else 0
            bb_pct = bb / pa if pa else 0
            k_pct = so / pa if pa else 0
            bb_k = bb / so if so else 0
            ab_hr = ab / hr if hr else 0
            xbh_pct = (d + t + hr) / ab if ab else 0
            sb_pct = sb / (sb + cs) if (sb + cs) else 0

            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": int(r["games"]), "ab": ab, "pa": pa,
                "r": int(r["runs"]), "h": h,
                "2b": d, "3b": t,
                "hr": hr, "itphr": itphr, "rbi": int(r["rbi"]),
                "bb": bb, "so": so,
                "sb": sb, "cs": cs, "tb": tb,
                "avg": f"{avg_val:.3f}",
                "obp": f"{obp_val:.3f}",
                "slg": f"{slg_val:.3f}",
                "ops": f"{ops_val:.3f}",
                "iso": f"{iso_val:.3f}",
                "babip": f"{babip_val:.3f}",
                "bb_pct": f"{bb_pct:.3f}",
                "k_pct": f"{k_pct:.3f}",
                "bb_k": f"{bb_k:.2f}",
                "ab_hr": f"{ab_hr:.1f}",
                "xbh_pct": f"{xbh_pct:.3f}",
                "sb_pct": f"{sb_pct:.3f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Pitching leaderboard
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/pitching")
def pitching_leaderboard():
    """
    Pitching leaderboard from player_pitching_stats.

    Query params:
      league_year_id (required), league_level, team_id,
      role (starter|reliever — filters by GS),
      sort (any stat key, default era), order (asc|desc),
      min_ip (default 0, in innings), page, page_size
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    role = request.args.get("role", "").lower()
    sort = request.args.get("sort", "era")
    order = request.args.get("order", "").lower()
    min_ip_innings = request.args.get("min_ip", 0, type=int)
    min_ipo = min_ip_innings * 3
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    # SQL expressions for derived stats
    _ipo = "ps.innings_pitched_outs"
    _bf = f"({_ipo} / 3 * 3 + ps.hits_allowed + ps.walks)"  # approx batters faced
    _era = f"IF({_ipo} > 0, ps.earned_runs * 27.0 / {_ipo}, 99)"
    _whip = f"IF({_ipo} > 0, (ps.walks + ps.hits_allowed) * 3.0 / {_ipo}, 99)"
    _k9 = f"IF({_ipo} > 0, ps.strikeouts * 27.0 / {_ipo}, 0)"
    _bb9 = f"IF({_ipo} > 0, ps.walks * 27.0 / {_ipo}, 0)"
    _hr9 = f"IF({_ipo} > 0, ps.home_runs_allowed * 27.0 / {_ipo}, 0)"
    _h9 = f"IF({_ipo} > 0, ps.hits_allowed * 27.0 / {_ipo}, 0)"
    _k_bb = "IF(ps.walks > 0, ps.strikeouts / ps.walks, 0)"
    _w_pct = "IF(ps.wins + ps.losses > 0, ps.wins / (ps.wins + ps.losses), 0)"
    _k_pct = f"IF({_bf} > 0, ps.strikeouts / {_bf}, 0)"
    _bb_pct = f"IF({_bf} > 0, ps.walks / {_bf}, 0)"
    _babip = (f"IF({_bf} - ps.strikeouts - ps.home_runs_allowed > 0, "
              f"(ps.hits_allowed - ps.home_runs_allowed) / "
              f"({_bf} - ps.strikeouts - ps.home_runs_allowed), 0)")
    _ip_gs = f"IF(ps.games_started > 0, ({_ipo} / 3.0) / ps.games_started, 0)"

    # Default direction: ASC for rate stats where lower is better
    asc_defaults = {"era", "whip", "bb9", "hr9", "h9", "bb_pct"}
    if not order:
        order = "ASC" if sort in asc_defaults else "DESC"
    else:
        order = "ASC" if order == "asc" else "DESC"

    sort_expr_map = {
        "era": _era, "whip": _whip,
        "k9": _k9, "bb9": _bb9, "hr9": _hr9, "h9": _h9,
        "k_bb": _k_bb, "w_pct": _w_pct,
        "k_pct": _k_pct, "bb_pct": _bb_pct,
        "babip": _babip, "ip_gs": _ip_gs,
        "g": "ps.games", "gs": "ps.games_started",
        "w": "ps.wins", "l": "ps.losses", "sv": "ps.saves",
        "ip": _ipo, "h": "ps.hits_allowed", "r": "ps.runs_allowed",
        "er": "ps.earned_runs", "bb": "ps.walks",
        "so": "ps.strikeouts", "hr": "ps.home_runs_allowed",
    }
    sort_expr = sort_expr_map.get(sort, _era)
    order_by = f"{sort_expr} {order}"

    where_parts = ["ps.league_year_id = :lyid",
                    f"{_ipo} >= :min_ipo"]
    params = {"lyid": league_year_id, "min_ipo": min_ipo}

    if team_id:
        where_parts.append("ps.team_id = :tid")
        params["tid"] = team_id
    if league_level:
        where_parts.append("tm.team_level = :ll")
        params["ll"] = league_level
    if role == "starter":
        where_parts.append("ps.games_started > 0")
    elif role == "reliever":
        where_parts.append("ps.games_started = 0")

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                WHERE {where_sql}
            """), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT ps.player_id, ps.team_id, ps.games, ps.games_started,
                       ps.wins, ps.losses, ps.saves,
                       ps.innings_pitched_outs, ps.hits_allowed,
                       ps.runs_allowed, ps.earned_runs,
                       ps.walks, ps.strikeouts, ps.home_runs_allowed,
                       ps.inside_the_park_hr_allowed,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level
                FROM player_pitching_stats ps
                JOIN simbbPlayers p ON p.id = ps.player_id
                JOIN teams tm ON tm.id = ps.team_id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        leaders = []
        for i, r in enumerate(rows):
            ipo = int(r["innings_pitched_outs"])
            g = int(r["games"])
            gs = int(r["games_started"])
            w = int(r["wins"])
            l = int(r["losses"])
            sv = int(r["saves"])
            h = int(r["hits_allowed"])
            ra = int(r["runs_allowed"])
            er = int(r["earned_runs"])
            bb = int(r["walks"])
            so = int(r["strikeouts"])
            hra = int(r["home_runs_allowed"])
            itphra = int(r["inside_the_park_hr_allowed"])

            ip_f = ipo / 3.0
            bf = int(ip_f) * 3 + h + bb  # approx batters faced
            bip = bf - so - hra

            era_val = er * 27.0 / ipo if ipo else 0
            whip_val = (bb + h) * 3.0 / ipo if ipo else 0
            k9_val = so * 27.0 / ipo if ipo else 0
            bb9_val = bb * 27.0 / ipo if ipo else 0
            hr9_val = hra * 27.0 / ipo if ipo else 0
            h9_val = h * 27.0 / ipo if ipo else 0
            k_bb_val = so / bb if bb else 0
            w_pct_val = w / (w + l) if (w + l) else 0
            k_pct_val = so / bf if bf else 0
            bb_pct_val = bb / bf if bf else 0
            babip_val = (h - hra) / bip if bip > 0 else 0
            ip_gs_val = ip_f / gs if gs else 0

            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": g, "gs": gs,
                "w": w, "l": l, "sv": sv,
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": h, "r": ra, "er": er,
                "bb": bb, "so": so, "hr": hra, "itphr": itphra,
                "era": f"{era_val:.2f}",
                "whip": f"{whip_val:.2f}",
                "k9": f"{k9_val:.1f}",
                "bb9": f"{bb9_val:.1f}",
                "hr9": f"{hr9_val:.1f}",
                "h9": f"{h9_val:.1f}",
                "k_bb": f"{k_bb_val:.2f}",
                "w_pct": f"{w_pct_val:.3f}",
                "k_pct": f"{k_pct_val:.3f}",
                "bb_pct": f"{bb_pct_val:.3f}",
                "babip": f"{babip_val:.3f}",
                "ip_gs": f"{ip_gs_val:.1f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Fielding leaderboard
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/fielding")
def fielding_leaderboard():
    """
    Fielding leaderboard from player_fielding_stats.

    Query params:
      league_year_id (required), league_level, position_code, team_id,
      sort (any stat key, default fpct), order (asc|desc),
      min_inn (default 0), page, page_size
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    league_level = request.args.get("league_level", type=int)
    position_code = request.args.get("position_code")
    team_id = request.args.get("team_id", type=int)
    sort = request.args.get("sort", "fpct")
    order = request.args.get("order", "").lower()
    min_inn = request.args.get("min_inn", 0, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    _tc = "(fs.putouts + fs.assists + fs.errors)"
    _fpct = f"IF({_tc} > 0, (fs.putouts + fs.assists) / {_tc}, 0)"
    _tc_g = "IF(fs.games > 0, (fs.putouts + fs.assists + fs.errors) / fs.games, 0)"
    _rf_g = "IF(fs.games > 0, (fs.putouts + fs.assists) / fs.games, 0)"
    _po_inn = "IF(fs.innings > 0, fs.putouts / fs.innings, 0)"
    _a_inn = "IF(fs.innings > 0, fs.assists / fs.innings, 0)"
    _e_inn = "IF(fs.innings > 0, fs.errors / fs.innings, 0)"

    asc_defaults = {"e", "e_inn"}
    if not order:
        order = "ASC" if sort in asc_defaults else "DESC"
    else:
        order = "ASC" if order == "asc" else "DESC"

    sort_expr_map = {
        "fpct": _fpct, "tc": _tc, "tc_g": _tc_g, "rf_g": _rf_g,
        "po_inn": _po_inn, "a_inn": _a_inn, "e_inn": _e_inn,
        "g": "fs.games", "inn": "fs.innings",
        "po": "fs.putouts", "a": "fs.assists", "e": "fs.errors",
    }
    sort_expr = sort_expr_map.get(sort, _fpct)
    order_by = f"{sort_expr} {order}"

    where_parts = ["fs.league_year_id = :lyid",
                    "fs.innings >= :min_inn"]
    params = {"lyid": league_year_id, "min_inn": min_inn}

    if position_code:
        where_parts.append("fs.position_code = :pos")
        params["pos"] = position_code
    if team_id:
        where_parts.append("fs.team_id = :tid")
        params["tid"] = team_id
    if league_level:
        where_parts.append("tm.team_level = :ll")
        params["ll"] = league_level

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_fielding_stats fs
                JOIN teams tm ON tm.id = fs.team_id
                WHERE {where_sql}
            """), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT fs.player_id, fs.team_id, fs.position_code,
                       fs.games, fs.innings, fs.putouts, fs.assists, fs.errors,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level
                FROM player_fielding_stats fs
                JOIN simbbPlayers p ON p.id = fs.player_id
                JOIN teams tm ON tm.id = fs.team_id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        leaders = []
        for i, r in enumerate(rows):
            g = int(r["games"])
            inn = int(r["innings"])
            po = int(r["putouts"])
            a = int(r["assists"])
            e = int(r["errors"])
            tc = po + a + e

            fpct_val = (po + a) / tc if tc else 0
            tc_g_val = tc / g if g else 0
            rf_g_val = (po + a) / g if g else 0
            po_inn_val = po / inn if inn else 0
            a_inn_val = a / inn if inn else 0
            e_inn_val = e / inn if inn else 0

            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "pos": r["position_code"],
                "g": g, "inn": inn,
                "po": po, "a": a, "e": e,
                "tc": tc,
                "fpct": f"{fpct_val:.3f}",
                "tc_g": f"{tc_g_val:.1f}",
                "rf_g": f"{rf_g_val:.1f}",
                "po_inn": f"{po_inn_val:.2f}",
                "a_inn": f"{a_inn_val:.2f}",
                "e_inn": f"{e_inn_val:.2f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Team aggregate stats
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/team")
def team_stats():
    """
    Team aggregate batting and pitching stats.

    Query params: league_year_id (required), league_level
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    league_level = request.args.get("league_level", type=int)

    engine = get_engine()
    try:
        params = {"lyid": league_year_id}
        level_filter = ""
        if league_level:
            level_filter = "AND tm.team_level = :ll"
            params["ll"] = league_level

        with engine.connect() as conn:
            bat_rows = conn.execute(sa_text(f"""
                SELECT bs.team_id, tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level,
                       SUM(bs.games) AS g, SUM(bs.at_bats) AS ab,
                       SUM(bs.runs) AS r, SUM(bs.hits) AS h,
                       SUM(bs.doubles_hit) AS `2b`, SUM(bs.triples) AS `3b`,
                       SUM(bs.home_runs) AS hr,
                       SUM(bs.inside_the_park_hr) AS itphr,
                       SUM(bs.rbi) AS rbi,
                       SUM(bs.walks) AS bb, SUM(bs.strikeouts) AS so,
                       SUM(bs.stolen_bases) AS sb,
                       SUM(bs.caught_stealing) AS cs
                FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                WHERE bs.league_year_id = :lyid {level_filter}
                GROUP BY bs.team_id, tm.team_abbrev, tm.team_level
                ORDER BY SUM(bs.runs) DESC
            """), params).mappings().all()

            pit_rows = conn.execute(sa_text(f"""
                SELECT ps.team_id, tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level,
                       SUM(ps.games) AS g,
                       SUM(ps.innings_pitched_outs) AS ipo,
                       SUM(ps.wins) AS w, SUM(ps.losses) AS l,
                       SUM(ps.saves) AS sv,
                       SUM(ps.hits_allowed) AS ha,
                       SUM(ps.runs_allowed) AS ra,
                       SUM(ps.earned_runs) AS er,
                       SUM(ps.walks) AS bb, SUM(ps.strikeouts) AS so,
                       SUM(ps.home_runs_allowed) AS hra,
                       SUM(ps.inside_the_park_hr_allowed) AS itphra
                FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                WHERE ps.league_year_id = :lyid {level_filter}
                GROUP BY ps.team_id, tm.team_abbrev, tm.team_level
                ORDER BY SUM(ps.earned_runs) * 27.0 / GREATEST(SUM(ps.innings_pitched_outs), 1) ASC
            """), params).mappings().all()

        batting = []
        for r in bat_rows:
            ab = int(r["ab"])
            h = int(r["h"])
            bb = int(r["bb"])
            so = int(r["so"])
            hr = int(r["hr"])
            itphr = int(r["itphr"])
            d = int(r["2b"])
            t = int(r["3b"])
            sb = int(r["sb"])
            cs = int(r["cs"])
            pa = ab + bb
            tb = h + d + 2 * t + 3 * hr
            avg_val = h / ab if ab else 0
            obp_val = (h + bb) / pa if pa else 0
            slg_val = tb / ab if ab else 0
            ops_val = obp_val + slg_val
            babip_denom = ab - so - hr
            babip_val = (h - hr) / babip_denom if babip_denom > 0 else 0
            batting.append({
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": int(r["g"]), "ab": ab, "pa": pa,
                "r": int(r["r"]), "h": h,
                "2b": d, "3b": t,
                "hr": hr, "itphr": itphr, "rbi": int(r["rbi"]),
                "bb": bb, "so": so,
                "sb": sb, "cs": cs, "tb": tb,
                "avg": f"{avg_val:.3f}",
                "obp": f"{obp_val:.3f}",
                "slg": f"{slg_val:.3f}",
                "ops": f"{ops_val:.3f}",
                "babip": f"{babip_val:.3f}",
            })

        pitching = []
        for r in pit_rows:
            ipo = int(r["ipo"])
            w = int(r["w"])
            l = int(r["l"])
            h = int(r["ha"])
            er = int(r["er"])
            bb = int(r["bb"])
            so = int(r["so"])
            hra = int(r["hra"])
            itphra = int(r["itphra"])
            ip_f = ipo / 3.0
            era_val = er * 27.0 / ipo if ipo else 0
            whip_val = (bb + h) * 3.0 / ipo if ipo else 0
            k9_val = so * 27.0 / ipo if ipo else 0
            bb9_val = bb * 27.0 / ipo if ipo else 0
            hr9_val = hra * 27.0 / ipo if ipo else 0
            pitching.append({
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": int(r["g"]),
                "w": w, "l": l, "sv": int(r["sv"]),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": h, "r": int(r["ra"]),
                "er": er, "bb": bb, "so": so, "hr": hra, "itphr": itphra,
                "era": f"{era_val:.2f}",
                "whip": f"{whip_val:.2f}",
                "k9": f"{k9_val:.1f}",
                "bb9": f"{bb9_val:.1f}",
                "hr9": f"{hr9_val:.1f}",
            })

        return jsonify(batting=batting, pitching=pitching), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Single player stats + game log
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/player/<int:player_id>")
def player_stats(player_id: int):
    """
    Single player's season stats across all seasons.
    Optionally include per-game log via ?include=gamelog.
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    include_gamelog = request.args.get("include", "") == "gamelog"

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # Player info
            player = conn.execute(sa_text(
                "SELECT id, firstName, lastName FROM simbbPlayers WHERE id = :pid"
            ), {"pid": player_id}).mappings().first()

            if not player:
                return jsonify(error="not_found",
                               message=f"Player {player_id} not found"), 404

            # Batting stats
            bat_where = "bs.player_id = :pid"
            bat_params = {"pid": player_id}
            if league_year_id:
                bat_where += " AND bs.league_year_id = :lyid"
                bat_params["lyid"] = league_year_id

            batting = conn.execute(sa_text(f"""
                SELECT bs.league_year_id, bs.team_id, bs.games, bs.at_bats,
                       bs.runs, bs.hits, bs.doubles_hit, bs.triples,
                       bs.home_runs, bs.inside_the_park_hr,
                       bs.rbi, bs.walks, bs.strikeouts,
                       bs.stolen_bases, bs.caught_stealing,
                       tm.team_abbrev AS team_abbrev
                FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                WHERE {bat_where}
                ORDER BY bs.league_year_id
            """), bat_params).mappings().all()

            # Pitching stats
            pit_where = "ps.player_id = :pid"
            pit_params = {"pid": player_id}
            if league_year_id:
                pit_where += " AND ps.league_year_id = :lyid"
                pit_params["lyid"] = league_year_id

            pitching = conn.execute(sa_text(f"""
                SELECT ps.league_year_id, ps.team_id, ps.games, ps.games_started,
                       ps.wins, ps.losses, ps.saves,
                       ps.innings_pitched_outs, ps.hits_allowed,
                       ps.runs_allowed, ps.earned_runs,
                       ps.walks, ps.strikeouts, ps.home_runs_allowed,
                       ps.inside_the_park_hr_allowed,
                       tm.team_abbrev AS team_abbrev
                FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                WHERE {pit_where}
                ORDER BY ps.league_year_id
            """), pit_params).mappings().all()

            # Fielding stats
            fld_where = "fs.player_id = :pid"
            fld_params = {"pid": player_id}
            if league_year_id:
                fld_where += " AND fs.league_year_id = :lyid"
                fld_params["lyid"] = league_year_id

            fielding = conn.execute(sa_text(f"""
                SELECT fs.league_year_id, fs.team_id, fs.position_code,
                       fs.games, fs.innings, fs.putouts, fs.assists, fs.errors,
                       tm.team_abbrev AS team_abbrev
                FROM player_fielding_stats fs
                JOIN teams tm ON tm.id = fs.team_id
                WHERE {fld_where}
                ORDER BY fs.league_year_id
            """), fld_params).mappings().all()

            # Current injury status
            current_injury = conn.execute(sa_text("""
                SELECT pis.weeks_remaining,
                       it.name AS injury_name, it.code AS injury_code,
                       pie.weeks_assigned
                FROM player_injury_state pis
                JOIN player_injury_events pie ON pie.id = pis.current_event_id
                JOIN injury_types it ON it.id = pie.injury_type_id
                WHERE pis.player_id = :pid
                  AND pis.status = 'injured'
                  AND pis.weeks_remaining > 0
            """), {"pid": player_id}).mappings().first()

            # Injury history
            inj_where = "pie.player_id = :pid"
            inj_params = {"pid": player_id}
            if league_year_id:
                inj_where += " AND pie.league_year_id = :lyid"
                inj_params["lyid"] = league_year_id

            injury_history = conn.execute(sa_text(f"""
                SELECT pie.id AS event_id, pie.league_year_id,
                       pie.weeks_assigned, pie.weeks_remaining,
                       pie.created_at,
                       it.name AS injury_name, it.code AS injury_code
                FROM player_injury_events pie
                JOIN injury_types it ON it.id = pie.injury_type_id
                WHERE {inj_where}
                ORDER BY pie.created_at DESC
            """), inj_params).mappings().all()

            # Game log (optional)
            gamelog_bat = []
            gamelog_pit = []
            if include_gamelog:
                gl_where = "gbl.player_id = :pid"
                gl_params = {"pid": player_id}
                if league_year_id:
                    gl_where += " AND gbl.league_year_id = :lyid"
                    gl_params["lyid"] = league_year_id

                gamelog_bat = conn.execute(sa_text(f"""
                    SELECT gbl.game_id, gbl.team_id, gbl.at_bats, gbl.runs,
                           gbl.hits, gbl.doubles_hit, gbl.triples, gbl.home_runs,
                           gbl.inside_the_park_hr,
                           gbl.rbi, gbl.walks, gbl.strikeouts,
                           gbl.stolen_bases, gbl.caught_stealing,
                           gr.season_week, gr.season_subweek,
                           CASE WHEN gr.home_team_id = gbl.team_id
                                THEN at2.team_abbrev
                                ELSE CONCAT('@', ht.team_abbrev)
                           END AS opponent
                    FROM game_batting_lines gbl
                    JOIN game_results gr ON gr.game_id = gbl.game_id
                    JOIN teams ht ON ht.id = gr.home_team_id
                    JOIN teams at2 ON at2.id = gr.away_team_id
                    WHERE {gl_where}
                    ORDER BY gr.season_week, gr.season_subweek
                """), gl_params).mappings().all()

                gp_where = "gpl.player_id = :pid"
                gp_params = {"pid": player_id}
                if league_year_id:
                    gp_where += " AND gpl.league_year_id = :lyid"
                    gp_params["lyid"] = league_year_id

                gamelog_pit = conn.execute(sa_text(f"""
                    SELECT gpl.game_id, gpl.team_id, gpl.games_started,
                           gpl.win, gpl.loss, gpl.save_recorded,
                           gpl.innings_pitched_outs, gpl.hits_allowed,
                           gpl.runs_allowed, gpl.earned_runs,
                           gpl.walks, gpl.strikeouts, gpl.home_runs_allowed,
                           gpl.inside_the_park_hr_allowed,
                           gr.season_week, gr.season_subweek,
                           CASE WHEN gr.home_team_id = gpl.team_id
                                THEN at2.team_abbrev
                                ELSE CONCAT('@', ht.team_abbrev)
                           END AS opponent
                    FROM game_pitching_lines gpl
                    JOIN game_results gr ON gr.game_id = gpl.game_id
                    JOIN teams ht ON ht.id = gr.home_team_id
                    JOIN teams at2 ON at2.id = gr.away_team_id
                    WHERE {gp_where}
                    ORDER BY gr.season_week, gr.season_subweek
                """), gp_params).mappings().all()

        def _bat_season(r):
            ab = int(r["at_bats"])
            h = int(r["hits"])
            bb = int(r["walks"])
            return {
                "league_year_id": int(r["league_year_id"]),
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "ab": ab,
                "r": int(r["runs"]), "h": h,
                "2b": int(r["doubles_hit"]), "3b": int(r["triples"]),
                "hr": int(r["home_runs"]), "itphr": int(r["inside_the_park_hr"]),
                "rbi": int(r["rbi"]),
                "bb": bb, "so": int(r["strikeouts"]),
                "sb": int(r["stolen_bases"]), "cs": int(r["caught_stealing"]),
                "avg": f"{h / ab:.3f}" if ab else ".000",
                "obp": f"{(h + bb) / (ab + bb):.3f}" if (ab + bb) else ".000",
            }

        def _pit_season(r):
            ipo = int(r["innings_pitched_outs"])
            er = int(r["earned_runs"])
            return {
                "league_year_id": int(r["league_year_id"]),
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "gs": int(r["games_started"]),
                "w": int(r["wins"]), "l": int(r["losses"]),
                "sv": int(r["saves"]),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": er, "bb": int(r["walks"]),
                "so": int(r["strikeouts"]), "hr": int(r["home_runs_allowed"]),
                "itphr": int(r["inside_the_park_hr_allowed"]),
                "era": f"{er * 27.0 / ipo:.2f}" if ipo else "0.00",
            }

        result = {
            "player_id": player_id,
            "name": f"{player['firstName']} {player['lastName']}",
            "current_injury": {
                "injury_name": current_injury["injury_name"],
                "injury_code": current_injury["injury_code"],
                "weeks_remaining": int(current_injury["weeks_remaining"]),
                "weeks_assigned": int(current_injury["weeks_assigned"]),
            } if current_injury else None,
            "injury_history": [{
                "event_id": int(r["event_id"]),
                "league_year_id": int(r["league_year_id"]),
                "injury_name": r["injury_name"],
                "injury_code": r["injury_code"],
                "weeks_assigned": int(r["weeks_assigned"]) if r["weeks_assigned"] else 0,
                "weeks_remaining": int(r["weeks_remaining"]) if r["weeks_remaining"] else 0,
                "created_at": str(r["created_at"]) if r["created_at"] else None,
            } for r in injury_history],
            "batting": [_bat_season(r) for r in batting],
            "pitching": [_pit_season(r) for r in pitching],
            "fielding": [{
                "league_year_id": int(r["league_year_id"]),
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "pos": r["position_code"],
                "g": int(r["games"]), "inn": int(r["innings"]),
                "po": int(r["putouts"]), "a": int(r["assists"]),
                "e": int(r["errors"]),
            } for r in fielding],
        }

        if include_gamelog:
            result["gamelog_batting"] = [{
                "game_id": int(r["game_id"]),
                "week": int(r["season_week"]),
                "subweek": r["season_subweek"],
                "opponent": r["opponent"],
                "ab": int(r["at_bats"]), "r": int(r["runs"]),
                "h": int(r["hits"]), "2b": int(r["doubles_hit"]),
                "3b": int(r["triples"]), "hr": int(r["home_runs"]),
                "itphr": int(r["inside_the_park_hr"]),
                "rbi": int(r["rbi"]), "bb": int(r["walks"]),
                "so": int(r["strikeouts"]),
            } for r in gamelog_bat]

            result["gamelog_pitching"] = [{
                "game_id": int(r["game_id"]),
                "week": int(r["season_week"]),
                "subweek": r["season_subweek"],
                "opponent": r["opponent"],
                "gs": int(r["games_started"]),
                "ip": f"{int(r['innings_pitched_outs']) // 3}.{int(r['innings_pitched_outs']) % 3}",
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": int(r["earned_runs"]), "bb": int(r["walks"]),
                "so": int(r["strikeouts"]),
                "hr": int(r["home_runs_allowed"]),
                "itphr": int(r["inside_the_park_hr_allowed"]),
                "dec": "W" if int(r["win"]) else ("L" if int(r["loss"]) else
                       ("S" if int(r["save_recorded"]) else "")),
            } for r in gamelog_pit]

        return jsonify(result), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Injuries
# ---------------------------------------------------------------------------

@stats_bp.get("/injuries")
def injury_report():
    """
    League-wide injury report. Only returns currently injured players.
    Healed players are automatically removed from player_injury_state
    on advance_week; historical data lives in player_injury_events.

    Query params: league_year_id, org_id, team_id
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    org_id = request.args.get("org_id", type=int)
    team_id = request.args.get("team_id", type=int)

    where_parts = ["pis.status = 'injured'", "pis.weeks_remaining > 0"]
    params = {}

    if org_id:
        where_parts.append("cts.orgID = :oid")
        params["oid"] = org_id
    if team_id:
        where_parts.append("t.id = :tid")
        params["tid"] = team_id
    if league_year_id:
        where_parts.append("pie.league_year_id = :lyid")
        params["lyid"] = league_year_id

    where_sql = " WHERE " + " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(f"""
                SELECT pis.player_id, pis.weeks_remaining,
                       p.firstName, p.lastName,
                       it.name AS injury_name, it.code AS injury_code,
                       pie.weeks_assigned, pie.league_year_id,
                       t.id AS team_id, t.team_abbrev AS team_abbrev, t.orgID AS org_id
                FROM player_injury_state pis
                JOIN simbbPlayers p ON p.id = pis.player_id
                JOIN player_injury_events pie ON pie.id = pis.current_event_id
                JOIN injury_types it ON it.id = pie.injury_type_id
                LEFT JOIN contracts c ON c.playerID = pis.player_id
                    AND c.isActive = 1
                LEFT JOIN contractDetails cd ON cd.contractID = c.id
                    AND cd.year = c.current_year
                LEFT JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
                    AND cts.isHolder = 1
                LEFT JOIN teams t ON t.orgID = cts.orgID
                    AND t.team_level = c.current_level
                {where_sql}
                ORDER BY pis.weeks_remaining DESC
            """), params).mappings().all()

        injuries = [{
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "team_id": int(r["team_id"]) if r["team_id"] else None,
            "team_abbrev": r["team_abbrev"],
            "org_id": int(r["org_id"]) if r["org_id"] else None,
            "injury_name": r["injury_name"],
            "injury_code": r["injury_code"],
            "weeks_remaining": int(r["weeks_remaining"]),
            "weeks_assigned": int(r["weeks_assigned"]) if r["weeks_assigned"] else 0,
        } for r in rows]

        return jsonify(injuries=injuries, total=len(injuries)), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


@stats_bp.get("/injuries/history")
def injury_history():
    """
    Injury history from player_injury_events.

    Query params: league_year_id, player_id, org_id
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    player_id = request.args.get("player_id", type=int)
    org_id = request.args.get("org_id", type=int)

    where_parts = []
    params = {}

    if league_year_id:
        where_parts.append("pie.league_year_id = :lyid")
        params["lyid"] = league_year_id
    if player_id:
        where_parts.append("pie.player_id = :pid")
        params["pid"] = player_id
    if org_id:
        where_parts.append("cts.orgID = :oid")
        params["oid"] = org_id

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(f"""
                SELECT pie.id, pie.player_id, pie.league_year_id,
                       pie.weeks_assigned, pie.weeks_remaining,
                       pie.created_at,
                       p.firstName, p.lastName,
                       it.name AS injury_name, it.code AS injury_code,
                       t.id AS team_id, t.team_abbrev AS team_abbrev
                FROM player_injury_events pie
                JOIN simbbPlayers p ON p.id = pie.player_id
                LEFT JOIN injury_types it ON it.id = pie.injury_type_id
                LEFT JOIN contracts c ON c.playerID = pie.player_id
                    AND c.isActive = 1
                LEFT JOIN contractDetails cd ON cd.contractID = c.id
                    AND cd.year = c.current_year
                LEFT JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
                    AND cts.isHolder = 1
                LEFT JOIN teams t ON t.orgID = cts.orgID
                    AND t.team_level = c.current_level
                {where_sql}
                ORDER BY pie.created_at DESC
            """), params).mappings().all()

        events = [{
            "event_id": int(r["id"]),
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "team_abbrev": r["team_abbrev"],
            "injury_name": r["injury_name"],
            "injury_code": r["injury_code"],
            "league_year_id": int(r["league_year_id"]),
            "weeks_assigned": int(r["weeks_assigned"]) if r["weeks_assigned"] else 0,
            "weeks_remaining": int(r["weeks_remaining"]) if r["weeks_remaining"] else 0,
            "created_at": str(r["created_at"]) if r["created_at"] else None,
        } for r in rows]

        return jsonify(events=events, total=len(events)), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Position usage
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/positions")
def position_usage():
    """
    Position usage data from player_position_usage_week.

    Query params: league_year_id (required), team_id, player_id, season_week
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    team_id = request.args.get("team_id", type=int)
    player_id = request.args.get("player_id", type=int)
    season_week = request.args.get("season_week", type=int)

    where_parts = ["pu.league_year_id = :lyid"]
    params = {"lyid": league_year_id}

    if team_id:
        where_parts.append("pu.team_id = :tid")
        params["tid"] = team_id
    if player_id:
        where_parts.append("pu.player_id = :pid")
        params["pid"] = player_id
    if season_week:
        where_parts.append("pu.season_week = :sw")
        params["sw"] = season_week

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(f"""
                SELECT pu.player_id, pu.team_id, pu.position_code,
                       SUM(pu.starts_this_week) AS total_starts,
                       SUM(CASE WHEN pu.vs_hand = 'L' THEN pu.starts_this_week ELSE 0 END) AS vs_l,
                       SUM(CASE WHEN pu.vs_hand = 'R' THEN pu.starts_this_week ELSE 0 END) AS vs_r,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev
                FROM player_position_usage_week pu
                JOIN simbbPlayers p ON p.id = pu.player_id
                JOIN teams tm ON tm.id = pu.team_id
                WHERE {where_sql}
                GROUP BY pu.player_id, pu.team_id, pu.position_code,
                         p.firstName, p.lastName, tm.team_abbrev
                ORDER BY total_starts DESC
            """), params).mappings().all()

        positions = [{
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "position_code": r["position_code"],
            "starts": int(r["total_starts"]),
            "vs_l_starts": int(r["vs_l"]),
            "vs_r_starts": int(r["vs_r"]),
        } for r in rows]

        return jsonify(positions=positions, total=len(positions)), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/splits")
def player_splits():
    """
    VS-hand splits from player_position_usage_week.

    Query params: league_year_id (required), player_id or team_id
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    player_id = request.args.get("player_id", type=int)
    team_id = request.args.get("team_id", type=int)

    where_parts = ["pu.league_year_id = :lyid"]
    params = {"lyid": league_year_id}

    if player_id:
        where_parts.append("pu.player_id = :pid")
        params["pid"] = player_id
    if team_id:
        where_parts.append("pu.team_id = :tid")
        params["tid"] = team_id

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(f"""
                SELECT pu.player_id, pu.position_code, pu.vs_hand,
                       SUM(pu.starts_this_week) AS total_starts,
                       p.firstName, p.lastName
                FROM player_position_usage_week pu
                JOIN simbbPlayers p ON p.id = pu.player_id
                WHERE {where_sql}
                GROUP BY pu.player_id, pu.position_code, pu.vs_hand,
                         p.firstName, p.lastName
                ORDER BY pu.player_id, pu.position_code, pu.vs_hand
            """), params).mappings().all()

        splits = [{
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}",
            "position_code": r["position_code"],
            "vs_hand": r["vs_hand"],
            "starts": int(r["total_starts"]),
        } for r in rows]

        return jsonify(splits=splits, total=len(splits)), 200

    except SQLAlchemyError as e:
        logger.exception("Stats endpoint error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500
