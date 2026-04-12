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
    org_id = request.args.get("org_id", type=int)
    position = request.args.get("position")
    sort = request.args.get("sort", "avg")
    order = request.args.get("order", "").lower()
    min_pa = request.args.get("min_pa", 0, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    # SQL expressions for every sortable stat
    _pa = "(bs.at_bats + bs.walks + bs.hbp)"
    _avg = "IF(bs.at_bats > 0, bs.hits / bs.at_bats, 0)"
    _obp = f"IF({_pa} > 0, (bs.hits + bs.walks + bs.hbp) / {_pa}, 0)"
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
    _singles = "(bs.hits - bs.doubles_hit - bs.triples - bs.home_runs)"
    _woba = (f"IF({_pa} > 0, "
             f"(0.690*bs.walks + 0.722*bs.hbp + 0.878*{_singles} "
             f"+ 1.242*bs.doubles_hit + 1.568*bs.triples + 2.004*bs.home_runs) "
             f"/ {_pa}, 0)")
    _rc = (f"IF(bs.at_bats + bs.walks > 0, "
           f"(bs.hits + bs.walks) * {_tb} / (bs.at_bats + bs.walks), 0)")
    _sec_a = (f"IF(bs.at_bats > 0, "
              f"({_tb} - bs.hits + bs.walks + bs.stolen_bases - bs.caught_stealing) "
              f"/ bs.at_bats, 0)")

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
        "tb": _tb, "hbp": "bs.hbp",
        "woba": _woba, "rc": _rc, "sec_a": _sec_a,
        "sf": "bs.sacrifice_flies", "gidp": "bs.gidp",
        "gb_pct": "IF(bs.ground_balls + bs.fly_balls + bs.popups > 0, bs.ground_balls / (bs.ground_balls + bs.fly_balls + bs.popups), 0)",
    }
    sort_expr = sort_expr_map.get(sort, _avg)
    order_by = f"{sort_expr} {order}"

    where_parts = ["bs.league_year_id = :lyid",
                    f"{_pa} >= :min_pa"]
    params = {"lyid": league_year_id, "min_pa": min_pa}

    if team_id:
        where_parts.append("bs.team_id = :tid")
        params["tid"] = team_id
    if org_id:
        where_parts.append("tm.orgID = :org_id")
        params["org_id"] = org_id
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
                       bs.plate_appearances, bs.hbp,
                       bs.sacrifice_flies, bs.gidp,
                       bs.ground_balls, bs.fly_balls, bs.popups,
                       bs.contact_barrel, bs.contact_solid, bs.contact_flare,
                       bs.contact_burner, bs.contact_under, bs.contact_topped, bs.contact_weak,
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

            # Bulk-load listed positions for players in results
            from services.listed_position import POSITION_DISPLAY
            player_ids = [int(r["player_id"]) for r in rows]
            pos_map = {}
            if player_ids:
                ph = ", ".join(f":pid{i}" for i in range(len(player_ids)))
                pp = {f"pid{i}": pid for i, pid in enumerate(player_ids)}
                pp["lyid2"] = league_year_id
                pos_rows = conn.execute(sa_text(f"""
                    SELECT player_id, position_code
                    FROM player_listed_position
                    WHERE player_id IN ({ph}) AND league_year_id = :lyid2
                """), pp).all()
                for pr in pos_rows:
                    pos_map[int(pr[0])] = POSITION_DISPLAY.get(pr[1], pr[1])

            # League averages for wRC+ (need league_level filter)
            lg_params = {"lyid": league_year_id}
            lg_level_filter = ""
            if league_level:
                lg_level_filter = "AND tm.team_level = :ll"
                lg_params["ll"] = league_level
            lg_avg = conn.execute(sa_text(f"""
                SELECT SUM(bs.hits) AS h, SUM(bs.doubles_hit) AS d2,
                       SUM(bs.triples) AS d3, SUM(bs.home_runs) AS hr,
                       SUM(bs.walks) AS bb, SUM(bs.hbp) AS hbp,
                       SUM(bs.at_bats) AS ab, SUM(bs.runs) AS r,
                       SUM(bs.at_bats + bs.walks + bs.hbp) AS pa
                FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                WHERE bs.league_year_id = :lyid {lg_level_filter}
            """), lg_params).mappings().first()

            from services.analytics import WOBA_WEIGHTS, WOBA_SCALE, compute_war_context, compute_batting_war
            _lg_pa = float(lg_avg["pa"] or 1)
            _lg_h = float(lg_avg["h"] or 0)
            _lg_1b = _lg_h - float(lg_avg["d2"] or 0) - float(lg_avg["d3"] or 0) - float(lg_avg["hr"] or 0)
            _lg_woba = ((WOBA_WEIGHTS["bb"] * float(lg_avg["bb"] or 0)
                         + WOBA_WEIGHTS["hbp"] * float(lg_avg["hbp"] or 0)
                         + WOBA_WEIGHTS["1b"] * _lg_1b
                         + WOBA_WEIGHTS["2b"] * float(lg_avg["d2"] or 0)
                         + WOBA_WEIGHTS["3b"] * float(lg_avg["d3"] or 0)
                         + WOBA_WEIGHTS["hr"] * float(lg_avg["hr"] or 0))
                        / _lg_pa) if _lg_pa > 0 else 0.320
            _lg_r_pa = float(lg_avg["r"] or 0) / _lg_pa if _lg_pa > 0 else 0.110
            _lg_ab = float(lg_avg["ab"] or 1)
            _lg_obp = (_lg_h + float(lg_avg["bb"] or 0) + float(lg_avg["hbp"] or 0)) / _lg_pa if _lg_pa > 0 else 0.320
            _lg_slg = (_lg_h + float(lg_avg["d2"] or 0) + 2 * float(lg_avg["d3"] or 0) + 3 * float(lg_avg["hr"] or 0)) / _lg_ab if _lg_ab > 0 else 0.400

            # WAR context
            _war_ctx = compute_war_context(conn, league_year_id, league_level or 9)

            # Fielding data for WAR
            _fld_map = {}
            if player_ids:
                fld_ph = ", ".join(f":fp{i}" for i in range(len(player_ids)))
                fld_pp = {f"fp{i}": pid for i, pid in enumerate(player_ids)}
                fld_pp["lyid3"] = league_year_id
                fld_qry = conn.execute(sa_text(f"""
                    SELECT player_id, position_code, games, innings,
                           errors, putouts, assists, double_plays
                    FROM player_fielding_stats
                    WHERE player_id IN ({fld_ph}) AND league_year_id = :lyid3
                    ORDER BY innings DESC
                """), fld_pp).mappings().all()
                for fr in fld_qry:
                    fpid = int(fr["player_id"])
                    if fpid not in _fld_map:
                        _fld_map[fpid] = {
                            "position": fr["position_code"],
                            "games": float(fr["games"] or 0),
                            "innings": float(fr["innings"] or 0),
                            "errors": float(fr["errors"] or 0),
                            "putouts": float(fr["putouts"] or 0),
                            "assists": float(fr["assists"] or 0),
                            "double_plays": float(fr["double_plays"] or 0),
                        }

        leaders = []
        for i, r in enumerate(rows):
            pid = int(r["player_id"])
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
            hbp = int(r.get("hbp", 0) or 0)
            pa = ab + bb + hbp
            tb = h + d + 2 * t + 3 * hr

            avg_val = h / ab if ab else 0
            obp_val = (h + bb + hbp) / pa if pa else 0
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

            # wOBA
            singles = h - d - t - hr
            woba_num = (WOBA_WEIGHTS["bb"] * bb + WOBA_WEIGHTS["hbp"] * hbp
                        + WOBA_WEIGHTS["1b"] * singles + WOBA_WEIGHTS["2b"] * d
                        + WOBA_WEIGHTS["3b"] * t + WOBA_WEIGHTS["hr"] * hr)
            woba_val = woba_num / pa if pa else 0

            # wRC+
            wrc_plus = 0
            if _lg_r_pa > 0 and WOBA_SCALE > 0 and pa > 0:
                wrc_per_pa = (woba_val - _lg_woba) / WOBA_SCALE + _lg_r_pa
                wrc_plus = (wrc_per_pa / _lg_r_pa) * 100.0

            # OPS+
            ops_plus = round(100 * (obp_val / _lg_obp + slg_val / _lg_slg - 1)) if _lg_obp > 0 and _lg_slg > 0 else 0

            # Runs Created, Secondary Average, Power/Speed
            rc = ((h + bb) * tb) / (ab + bb) if (ab + bb) else 0
            sec_a = (tb - h + bb + sb - cs) / ab if ab else 0
            pss = (2.0 * hr * sb) / (hr + sb) if (hr + sb) else 0

            # Batted ball rates
            bip_total = int(r.get("ground_balls", 0) or 0) + int(r.get("fly_balls", 0) or 0) + int(r.get("popups", 0) or 0)
            gb_pct = int(r.get("ground_balls", 0) or 0) / bip_total if bip_total else 0
            fb_pct = int(r.get("fly_balls", 0) or 0) / bip_total if bip_total else 0
            hr_fb_val = hr / int(r.get("fly_balls", 0) or 0) if int(r.get("fly_balls", 0) or 0) else 0

            # Contact quality
            c_barrel = int(r.get("contact_barrel", 0) or 0)
            c_solid = int(r.get("contact_solid", 0) or 0)
            c_total = sum(int(r.get(f"contact_{t}", 0) or 0) for t in ("barrel", "solid", "flare", "burner", "under", "topped", "weak"))
            barrel_pct_val = c_barrel / c_total if c_total else 0
            hard_hit_val = (c_barrel + c_solid) / c_total if c_total else 0

            sf = int(r.get("sacrifice_flies", 0) or 0)
            gidp_val = int(r.get("gidp", 0) or 0)

            # Contact quality breakdown
            c_topped = int(r.get("contact_topped", 0) or 0)
            c_weak = int(r.get("contact_weak", 0) or 0)
            c_burner = int(r.get("contact_burner", 0) or 0)
            c_under = int(r.get("contact_under", 0) or 0)
            c_flare = int(r.get("contact_flare", 0) or 0)
            soft_pct = (c_topped + c_weak) / c_total if c_total else 0
            med_pct = (c_flare + c_burner + c_under) / c_total if c_total else 0
            ld_pct_val = (c_barrel + c_solid + c_flare) / c_total if c_total else 0
            contact_pct = (ab - so) / ab if ab else 0

            # bWAR
            _war_row = {"at_bats": ab, "hits": h, "doubles_hit": d, "triples": t,
                        "home_runs": hr, "walks": bb, "strikeouts": so,
                        "stolen_bases": sb, "caught_stealing": cs,
                        "hbp": hbp, "gidp": gidp_val, "games": int(r["games"])}
            _bwar = compute_batting_war(_war_row, _fld_map.get(pid), _war_ctx)

            leaders.append({
                "rank": offset + i + 1,
                "player_id": pid,
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "position": pos_map.get(pid),
                "g": int(r["games"]), "ab": ab, "pa": pa,
                "r": int(r["runs"]), "h": h,
                "2b": d, "3b": t,
                "hr": hr, "itphr": itphr, "rbi": int(r["rbi"]),
                "bb": bb, "so": so,
                "sb": sb, "cs": cs, "tb": tb, "hbp": hbp,
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
                "woba": f"{woba_val:.3f}",
                "wrc_plus": round(wrc_plus),
                "ops_plus": ops_plus,
                "bwar": _bwar["war"],
                "rc": f"{rc:.1f}",
                "sec_a": f"{sec_a:.3f}",
                "pss": f"{pss:.1f}",
                "sf": sf, "gidp": gidp_val,
                "gb_pct": f"{gb_pct:.3f}",
                "fb_pct": f"{fb_pct:.3f}",
                "hr_fb": f"{hr_fb_val:.3f}",
                "barrel_pct": f"{barrel_pct_val:.3f}",
                "hard_hit_pct": f"{hard_hit_val:.3f}",
                "soft_pct": f"{soft_pct:.3f}",
                "med_pct": f"{med_pct:.3f}",
                "ld_pct": f"{ld_pct_val:.3f}",
                "contact_pct": f"{contact_pct:.3f}",
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
    org_id = request.args.get("org_id", type=int)
    role = request.args.get("role", "").lower()
    sort = request.args.get("sort", "era")
    order = request.args.get("order", "").lower()
    min_ip_innings = request.args.get("min_ip", 0, type=int)
    min_ipo = min_ip_innings * 3
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    # SQL expressions for derived stats
    _ipo = "ps.innings_pitched_outs"
    _bf = f"({_ipo} + ps.hits_allowed + ps.walks + ps.hbp)"
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
    asc_defaults = {"era", "whip", "bb9", "hr9", "h9", "bb_pct", "fip"}
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
        "hbp": "ps.hbp", "wp": "ps.wildpitches",
        "pitches": "ps.pitches_thrown",
        "str_pct": f"IF(ps.pitches_thrown > 0, ps.strikes / ps.pitches_thrown, 0)",
        "p_ip": f"IF({_ipo} > 0, ps.pitches_thrown / ({_ipo} / 3.0), 0)",
    }
    sort_expr = sort_expr_map.get(sort, _era)
    order_by = f"{sort_expr} {order}"

    where_parts = ["ps.league_year_id = :lyid",
                    f"{_ipo} >= :min_ipo"]
    params = {"lyid": league_year_id, "min_ipo": min_ipo}

    if team_id:
        where_parts.append("ps.team_id = :tid")
        params["tid"] = team_id
    if org_id:
        where_parts.append("tm.orgID = :org_id")
        params["org_id"] = org_id
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
                       ps.holds, ps.blown_saves, ps.quality_starts,
                       ps.innings_pitched_outs, ps.hits_allowed,
                       ps.runs_allowed, ps.earned_runs,
                       ps.walks, ps.strikeouts, ps.home_runs_allowed,
                       ps.inside_the_park_hr_allowed,
                       ps.pitches_thrown, ps.balls, ps.strikes,
                       ps.hbp, ps.wildpitches,
                       ps.batters_faced, ps.sacrifice_flies_allowed, ps.gidp_induced,
                       ps.ground_balls_allowed, ps.fly_balls_allowed, ps.popups_allowed,
                       ps.inherited_runners, ps.inherited_runners_scored,
                       ps.contact_barrel, ps.contact_solid, ps.contact_flare,
                       ps.contact_burner, ps.contact_under, ps.contact_topped, ps.contact_weak,
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

            # Compute league FIP constant
            fip_params = {"lyid": league_year_id}
            fip_level_filter = ""
            if league_level:
                fip_level_filter = "AND tm.team_level = :ll"
                fip_params["ll"] = league_level
            fip_lg = conn.execute(sa_text(f"""
                SELECT SUM(ps.earned_runs) AS er, SUM(ps.innings_pitched_outs) AS ipo,
                       SUM(ps.home_runs_allowed) AS hra, SUM(ps.walks) AS bb,
                       SUM(ps.strikeouts) AS so, SUM(ps.hbp) AS hbp,
                       SUM(ps.fly_balls_allowed) AS fb_a
                FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                WHERE ps.league_year_id = :lyid {fip_level_filter}
            """), fip_params).mappings().first()
            _fip_ip = float(fip_lg["ipo"] or 1) / 3.0
            _fip_era = float(fip_lg["er"] or 0) * 9.0 / _fip_ip if _fip_ip > 0 else 4.50
            _fip_const = (_fip_era - (13.0 * float(fip_lg["hra"] or 0)
                          + 3.0 * (float(fip_lg["bb"] or 0) + float(fip_lg["hbp"] or 0))
                          - 2.0 * float(fip_lg["so"] or 0)) / _fip_ip) if _fip_ip > 0 else 3.17

            from services.analytics import compute_war_context, compute_pitching_war
            _war_ctx = compute_war_context(conn, league_year_id, league_level or 9)

        leaders = []
        for i, r in enumerate(rows):
            ipo = int(r["innings_pitched_outs"])
            g = int(r["games"])
            gs = int(r["games_started"])
            w = int(r["wins"])
            l = int(r["losses"])
            sv = int(r["saves"])
            hld = int(r.get("holds") or 0)
            bs = int(r.get("blown_saves") or 0)
            qs = int(r.get("quality_starts") or 0)
            h = int(r["hits_allowed"])
            ra = int(r["runs_allowed"])
            er = int(r["earned_runs"])
            bb = int(r["walks"])
            so = int(r["strikeouts"])
            hra = int(r["home_runs_allowed"])
            itphra = int(r["inside_the_park_hr_allowed"])
            hbp = int(r.get("hbp", 0) or 0)
            wp = int(r.get("wildpitches", 0) or 0)
            pitches = int(r.get("pitches_thrown", 0) or 0)
            balls = int(r.get("balls", 0) or 0)
            strikes = int(r.get("strikes", 0) or 0)

            ip_f = ipo / 3.0
            bf = ipo + h + bb + hbp
            bip = bf - so - bb - hbp - hra

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
            fip_val = ((13.0 * hra + 3.0 * (bb + hbp) - 2.0 * so)
                       / ip_f + _fip_const) if ip_f > 0 else 0

            # Batted ball rates
            gb_a = int(r.get("ground_balls_allowed", 0) or 0)
            fb_a = int(r.get("fly_balls_allowed", 0) or 0)
            pu_a = int(r.get("popups_allowed", 0) or 0)
            bip_total_p = gb_a + fb_a + pu_a
            gb_pct_p = gb_a / bip_total_p if bip_total_p else 0
            fb_pct_p = fb_a / bip_total_p if bip_total_p else 0
            hr_fb_p = hra / fb_a if fb_a else 0

            # Contact quality
            c_barrel_p = int(r.get("contact_barrel", 0) or 0)
            c_solid_p = int(r.get("contact_solid", 0) or 0)
            c_total_p = sum(int(r.get(f"contact_{t}", 0) or 0) for t in ("barrel", "solid", "flare", "burner", "under", "topped", "weak"))
            barrel_pct_p = c_barrel_p / c_total_p if c_total_p else 0
            hard_hit_p = (c_barrel_p + c_solid_p) / c_total_p if c_total_p else 0

            # Inherited runners, GIDP
            ir = int(r.get("inherited_runners", 0) or 0)
            irs = int(r.get("inherited_runners_scored", 0) or 0)
            ir_pct = irs / ir if ir else 0
            gidp_ind = int(r.get("gidp_induced", 0) or 0)
            real_bf = int(r.get("batters_faced", 0) or 0)

            # xFIP
            _lg_hr_fb_rate = float(fip_lg["hra"] or 0) / float(fip_lg["fb_a"] or 1) if float(fip_lg.get("fb_a") or 0) > 0 else 0
            xfip_val = ((13.0 * _lg_hr_fb_rate * fb_a + 3.0 * (bb + hbp) - 2.0 * so) / ip_f + _fip_const) if ip_f > 0 and fb_a > 0 else fip_val

            # K-BB%
            k_bb_pct_val = k_pct_val - bb_pct_val

            # LOB%
            lob_num = h + bb + hbp - ra
            lob_den = h + bb + hbp - 1.4 * hra
            lob_pct_val = lob_num / lob_den if lob_den > 0 else 0

            # WP/9
            wp9_val = wp * 27.0 / ipo if ipo else 0

            # Soft%, LD%
            c_topped_p = int(r.get("contact_topped", 0) or 0)
            c_weak_p = int(r.get("contact_weak", 0) or 0)
            c_flare_p = int(r.get("contact_flare", 0) or 0)
            soft_pct_p = (c_topped_p + c_weak_p) / c_total_p if c_total_p else 0
            ld_pct_p = (c_barrel_p + c_solid_p + c_flare_p) / c_total_p if c_total_p else 0

            # pWAR
            _pwar_row = {"innings_pitched_outs": ipo, "home_runs_allowed": hra,
                         "walks": bb, "strikeouts": so, "hbp": hbp}
            _pwar = compute_pitching_war(_pwar_row, _war_ctx)

            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": g, "gs": gs,
                "w": w, "l": l, "sv": sv,
                "hld": hld, "bs": bs, "qs": qs,
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": h, "r": ra, "er": er,
                "bb": bb, "so": so, "hr": hra, "itphr": itphra,
                "hbp": hbp, "wp": wp,
                "pitches": pitches, "balls": balls, "strikes": strikes,
                "str_pct": f"{(strikes / pitches if pitches else 0):.3f}",
                "p_ip": f"{(pitches / ip_f if ip_f else 0):.1f}",
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
                "fip": f"{fip_val:.2f}",
                "era_minus": round(era_val / _fip_era * 100) if _fip_era > 0 and ipo > 0 else 0,
                "fip_minus": round(fip_val / _fip_era * 100) if _fip_era > 0 and ipo > 0 else 0,
                "pwar": _pwar["war"],
                "xfip": f"{xfip_val:.2f}",
                "k_bb_pct": f"{k_bb_pct_val:.3f}",
                "lob_pct": f"{lob_pct_val:.3f}",
                "wp9": f"{wp9_val:.1f}",
                "soft_pct": f"{soft_pct_p:.3f}",
                "ld_pct": f"{ld_pct_p:.3f}",
                "gb_pct": f"{gb_pct_p:.3f}",
                "fb_pct": f"{fb_pct_p:.3f}",
                "hr_fb": f"{hr_fb_p:.3f}",
                "barrel_pct": f"{barrel_pct_p:.3f}",
                "hard_hit_pct": f"{hard_hit_p:.3f}",
                "ir": ir, "irs": irs,
                "ir_pct": f"{ir_pct:.3f}",
                "gidp_induced": gidp_ind,
                "bf": real_bf if real_bf else bf,
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
        "dp": "fs.double_plays",
        "rf": "IF(fs.innings > 0, (fs.putouts + fs.assists) * 9.0 / fs.innings, 0)",
        "dp_g": "IF(fs.games > 0, fs.double_plays / fs.games, 0)",
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
                       fs.double_plays,
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

            from services.analytics import compute_war_context, compute_fielding_war
            _war_ctx = compute_war_context(conn, league_year_id, league_level or 9)

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
            dp = int(r.get("double_plays", 0) or 0)
            rf_val = (po + a) * 9.0 / inn if inn else 0
            dp_g_val = dp / g if g else 0

            _fld_data = {"position": r["position_code"], "games": g, "innings": inn,
                         "errors": e, "putouts": po, "assists": a, "double_plays": dp}
            _fwar = compute_fielding_war(_fld_data, _war_ctx)

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
                "dp": dp,
                "rf": f"{rf_val:.1f}",
                "dp_g": f"{dp_g_val:.2f}",
                "fwar": _fwar["fwar"],
                "err_runs": _fwar["err_runs"],
                "range_runs": _fwar["range_runs"],
                "dp_runs": _fwar["dp_runs"],
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
                       SUM(bs.caught_stealing) AS cs,
                       SUM(bs.plate_appearances) AS pa,
                       SUM(bs.hbp) AS hbp
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
                       SUM(ps.holds) AS hld,
                       SUM(ps.blown_saves) AS bs,
                       SUM(ps.quality_starts) AS qs,
                       SUM(ps.hits_allowed) AS ha,
                       SUM(ps.runs_allowed) AS ra,
                       SUM(ps.earned_runs) AS er,
                       SUM(ps.walks) AS bb, SUM(ps.strikeouts) AS so,
                       SUM(ps.home_runs_allowed) AS hra,
                       SUM(ps.inside_the_park_hr_allowed) AS itphra,
                       SUM(ps.hbp) AS hbp,
                       SUM(ps.pitches_thrown) AS pitches,
                       SUM(ps.wildpitches) AS wp
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
            hbp = int(r.get("hbp", 0) or 0)
            pa = ab + bb + hbp
            tb = h + d + 2 * t + 3 * hr
            avg_val = h / ab if ab else 0
            obp_val = (h + bb + hbp) / pa if pa else 0
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
                "sb": sb, "cs": cs, "tb": tb, "hbp": hbp,
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
                "hld": int(r.get("hld") or 0),
                "bs": int(r.get("bs") or 0),
                "qs": int(r.get("qs") or 0),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": h, "r": int(r["ra"]),
                "er": er, "bb": bb, "so": so, "hr": hra, "itphr": itphra,
                "era": f"{era_val:.2f}",
                "whip": f"{whip_val:.2f}",
                "k9": f"{k9_val:.1f}",
                "bb9": f"{bb9_val:.1f}",
                "hr9": f"{hr9_val:.1f}",
            })

        # --- Team Fielding ---
        with engine.connect() as conn:
            fld_rows = conn.execute(sa_text(f"""
                SELECT fs.team_id, tm.team_abbrev AS team_abbrev,
                       tm.team_level AS team_level,
                       SUM(fs.games) AS g,
                       SUM(fs.innings) AS inn,
                       SUM(fs.putouts) AS po,
                       SUM(fs.assists) AS a,
                       SUM(fs.errors) AS e,
                       SUM(fs.double_plays) AS dp
                FROM player_fielding_stats fs
                JOIN teams tm ON tm.id = fs.team_id
                WHERE fs.league_year_id = :lyid {level_filter}
                GROUP BY fs.team_id, tm.team_abbrev, tm.team_level
                ORDER BY SUM(fs.errors) ASC
            """), params).mappings().all()

            # Defensive efficiency: 1 - (H - HR) / (BF - SO - HR - BB - HBP)
            # Uses pitching data for BF components, batting data for context
            pit_def = {}
            for r in pit_rows:
                tid = int(r["team_id"])
                ipo = int(r["ipo"])
                ha = int(r["ha"]); hra = int(r["hra"])
                bb_p = int(r["bb"]); so_p = int(r["so"])
                hbp_p = int(r.get("hbp", 0) or 0)
                bip = (ipo + ha + bb_p + hbp_p) - so_p - bb_p - hbp_p - hra
                h_on_contact = ha - hra
                pit_def[tid] = {"bip": bip, "h_contact": h_on_contact,
                                "ipo": ipo, "ra": int(r["ra"]), "er": int(r["er"])}

        fielding = []
        for r in fld_rows:
            tid = int(r["team_id"])
            inn = int(r["inn"])
            po = int(r["po"]); a = int(r["a"]); e = int(r["e"])
            dp = int(r["dp"]); g = int(r["g"])
            tc = po + a + e
            fpct = (po + a) / tc if tc > 0 else 1.0
            rf = (po + a) * 9.0 / inn if inn > 0 else 0
            dp_g = dp / g if g > 0 else 0
            e_g = e / g if g > 0 else 0

            # Defensive efficiency from pitching data
            pd = pit_def.get(tid, {})
            bip = pd.get("bip", 0)
            def_eff = 1.0 - (pd.get("h_contact", 0) / bip) if bip > 0 else 0

            fielding.append({
                "team_id": tid,
                "team_abbrev": r["team_abbrev"],
                "team_level": int(r["team_level"]),
                "g": g, "inn": inn,
                "po": po, "a": a, "e": e, "dp": dp,
                "tc": tc,
                "fpct": f"{fpct:.3f}",
                "rf": f"{rf:.1f}",
                "dp_g": f"{dp_g:.2f}",
                "e_g": f"{e_g:.2f}",
                "def_eff": f"{def_eff:.3f}",
            })

        return jsonify(batting=batting, pitching=pitching, fielding=fielding), 200

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
                       bs.plate_appearances, bs.hbp,
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
                       ps.holds, ps.blown_saves, ps.quality_starts,
                       ps.innings_pitched_outs, ps.hits_allowed,
                       ps.runs_allowed, ps.earned_runs,
                       ps.walks, ps.strikeouts, ps.home_runs_allowed,
                       ps.inside_the_park_hr_allowed,
                       ps.pitches_thrown, ps.balls, ps.strikes,
                       ps.hbp, ps.wildpitches,
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
            hbp = int(r.get("hbp", 0) or 0)
            pa = ab + bb + hbp
            return {
                "league_year_id": int(r["league_year_id"]),
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "ab": ab, "pa": pa,
                "r": int(r["runs"]), "h": h,
                "2b": int(r["doubles_hit"]), "3b": int(r["triples"]),
                "hr": int(r["home_runs"]), "itphr": int(r["inside_the_park_hr"]),
                "rbi": int(r["rbi"]),
                "bb": bb, "so": int(r["strikeouts"]),
                "sb": int(r["stolen_bases"]), "cs": int(r["caught_stealing"]),
                "hbp": hbp,
                "avg": f"{h / ab:.3f}" if ab else ".000",
                "obp": f"{(h + bb + hbp) / pa:.3f}" if pa else ".000",
            }

        def _pit_season(r):
            ipo = int(r["innings_pitched_outs"])
            er = int(r["earned_runs"])
            hbp = int(r.get("hbp", 0) or 0)
            pitches = int(r.get("pitches_thrown", 0) or 0)
            wp = int(r.get("wildpitches", 0) or 0)
            ip_f = ipo / 3.0
            return {
                "league_year_id": int(r["league_year_id"]),
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "gs": int(r["games_started"]),
                "w": int(r["wins"]), "l": int(r["losses"]),
                "sv": int(r["saves"]),
                "hld": int(r.get("holds") or 0),
                "bs": int(r.get("blown_saves") or 0),
                "qs": int(r.get("quality_starts") or 0),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": er, "bb": int(r["walks"]),
                "so": int(r["strikeouts"]), "hr": int(r["home_runs_allowed"]),
                "itphr": int(r["inside_the_park_hr_allowed"]),
                "hbp": hbp, "wp": wp, "pitches": pitches,
                "era": f"{er * 27.0 / ipo:.2f}" if ipo else "0.00",
                "str_pct": f"{(int(r.get('strikes', 0) or 0) / pitches if pitches else 0):.3f}",
                "p_ip": f"{(pitches / ip_f if ip_f else 0):.1f}",
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
                       t.id AS team_id, t.team_abbrev AS team_abbrev, t.orgID AS org_id,
                       c.current_level, c.onIR
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
            "current_level": int(r["current_level"]) if r["current_level"] else None,
            "on_ir": bool(r["onIR"]) if r["onIR"] is not None else False,
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
                       t.id AS team_id, t.team_abbrev AS team_abbrev,
                       c.current_level, c.onIR
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
            "current_level": int(r["current_level"]) if r["current_level"] else None,
            "on_ir": bool(r["onIR"]) if r["onIR"] is not None else False,
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


# ---------------------------------------------------------------------------
# Phase 4A: Player game log (dedicated endpoint with running stats)
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/player/<int:player_id>/gamelog")
def player_gamelog(player_id: int):
    """
    Per-game batting and pitching lines for a player with running AVG/OPS.

    Query params: league_year_id (required)
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            bat_rows = conn.execute(sa_text("""
                SELECT gbl.game_id, gbl.team_id, gbl.position_code,
                       gbl.batting_order,
                       gbl.at_bats, gbl.runs, gbl.hits, gbl.doubles_hit,
                       gbl.triples, gbl.home_runs, gbl.inside_the_park_hr,
                       gbl.rbi, gbl.walks, gbl.strikeouts,
                       gbl.stolen_bases, gbl.caught_stealing,
                       gbl.plate_appearances, gbl.hbp,
                       gr.season_week, gr.season_subweek,
                       CASE WHEN gr.home_team_id = gbl.team_id
                            THEN at2.team_abbrev
                            ELSE CONCAT('@', ht.team_abbrev)
                       END AS opponent,
                       gr.home_score, gr.away_score,
                       CASE WHEN gr.home_team_id = gbl.team_id
                            THEN gr.home_score ELSE gr.away_score END AS team_score,
                       CASE WHEN gr.home_team_id = gbl.team_id
                            THEN gr.away_score ELSE gr.home_score END AS opp_score
                FROM game_batting_lines gbl
                JOIN game_results gr ON gr.game_id = gbl.game_id
                JOIN teams ht ON ht.id = gr.home_team_id
                JOIN teams at2 ON at2.id = gr.away_team_id
                WHERE gbl.player_id = :pid AND gbl.league_year_id = :lyid
                ORDER BY gr.season_week, gr.season_subweek
            """), {"pid": player_id, "lyid": league_year_id}).mappings().all()

            pit_rows = conn.execute(sa_text("""
                SELECT gpl.game_id, gpl.team_id,
                       gpl.games_started, gpl.win, gpl.loss, gpl.save_recorded,
                       gpl.hold, gpl.blown_save,
                       gpl.innings_pitched_outs, gpl.hits_allowed,
                       gpl.runs_allowed, gpl.earned_runs,
                       gpl.walks, gpl.strikeouts, gpl.home_runs_allowed,
                       gpl.inside_the_park_hr_allowed,
                       gpl.pitches_thrown, gpl.balls, gpl.strikes,
                       gpl.hbp, gpl.wildpitches,
                       gr.season_week, gr.season_subweek,
                       CASE WHEN gr.home_team_id = gpl.team_id
                            THEN at2.team_abbrev
                            ELSE CONCAT('@', ht.team_abbrev)
                       END AS opponent
                FROM game_pitching_lines gpl
                JOIN game_results gr ON gr.game_id = gpl.game_id
                JOIN teams ht ON ht.id = gr.home_team_id
                JOIN teams at2 ON at2.id = gr.away_team_id
                WHERE gpl.player_id = :pid AND gpl.league_year_id = :lyid
                ORDER BY gr.season_week, gr.season_subweek
            """), {"pid": player_id, "lyid": league_year_id}).mappings().all()

        # Build batting game log with running totals
        batting = []
        cum_ab = cum_h = cum_bb = cum_hbp = cum_tb = 0
        for r in bat_rows:
            ab = int(r["at_bats"]); h = int(r["hits"]); bb = int(r["walks"])
            hbp = int(r.get("hbp", 0) or 0)
            d = int(r["doubles_hit"]); t = int(r["triples"]); hr = int(r["home_runs"])
            tb = h + d + 2 * t + 3 * hr
            cum_ab += ab; cum_h += h; cum_bb += bb; cum_hbp += hbp; cum_tb += tb
            cum_pa = cum_ab + cum_bb + cum_hbp
            run_avg = cum_h / cum_ab if cum_ab else 0
            run_obp = (cum_h + cum_bb + cum_hbp) / cum_pa if cum_pa else 0
            run_slg = cum_tb / cum_ab if cum_ab else 0
            batting.append({
                "game_id": int(r["game_id"]),
                "week": int(r["season_week"]), "subweek": r["season_subweek"],
                "opponent": r["opponent"],
                "result": f"{'W' if r['team_score'] > r['opp_score'] else 'L'} {r['team_score']}-{r['opp_score']}",
                "pos": r["position_code"], "bo": int(r["batting_order"]),
                "ab": ab, "r": int(r["runs"]), "h": h,
                "2b": d, "3b": t, "hr": hr,
                "rbi": int(r["rbi"]), "bb": bb, "so": int(r["strikeouts"]),
                "sb": int(r["stolen_bases"]), "cs": int(r["caught_stealing"]),
                "hbp": hbp, "pa": int(r.get("plate_appearances", 0) or 0),
                "avg": f"{run_avg:.3f}", "obp": f"{run_obp:.3f}",
                "ops": f"{(run_obp + run_slg):.3f}",
            })

        # Build pitching game log
        pitching = []
        for r in pit_rows:
            ipo = int(r["innings_pitched_outs"])
            er = int(r["earned_runs"])
            dec = ("W" if int(r["win"]) else ("L" if int(r["loss"]) else
                   ("S" if int(r["save_recorded"]) else
                   ("H" if int(r.get("hold", 0) or 0) else ""))))
            pitching.append({
                "game_id": int(r["game_id"]),
                "week": int(r["season_week"]), "subweek": r["season_subweek"],
                "opponent": r["opponent"],
                "dec": dec,
                "gs": int(r["games_started"]),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": er, "bb": int(r["walks"]), "so": int(r["strikeouts"]),
                "hr": int(r["home_runs_allowed"]),
                "hbp": int(r.get("hbp", 0) or 0),
                "pitches": int(r.get("pitches_thrown", 0) or 0),
                "era": f"{er * 27.0 / ipo:.2f}" if ipo else "0.00",
            })

        return jsonify(batting=batting, pitching=pitching), 200

    except SQLAlchemyError as e:
        logger.exception("Stats gamelog error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Phase 4C: Career stats (aggregate across all seasons)
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/player/<int:player_id>/career")
def player_career(player_id: int):
    """
    Career batting/pitching stats: one row per season + career totals row.
    """
    from sqlalchemy import text as sa_text

    engine = get_engine()
    try:
        with engine.connect() as conn:
            player = conn.execute(sa_text(
                "SELECT id, firstName, lastName FROM simbbPlayers WHERE id = :pid"
            ), {"pid": player_id}).mappings().first()
            if not player:
                return jsonify(error="not_found",
                               message=f"Player {player_id} not found"), 404

            bat_rows = conn.execute(sa_text("""
                SELECT bs.league_year_id, ly.season,
                       tm.team_abbrev, tm.team_level,
                       bs.games, bs.at_bats, bs.runs, bs.hits, bs.doubles_hit,
                       bs.triples, bs.home_runs, bs.inside_the_park_hr,
                       bs.rbi, bs.walks, bs.strikeouts,
                       bs.stolen_bases, bs.caught_stealing,
                       bs.plate_appearances, bs.hbp, bs.sacrifice_flies
                FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                JOIN league_years ly ON ly.id = bs.league_year_id
                WHERE bs.player_id = :pid
                ORDER BY ly.season, tm.team_level
            """), {"pid": player_id}).mappings().all()

            pit_rows = conn.execute(sa_text("""
                SELECT ps.league_year_id, ly.season,
                       tm.team_abbrev, tm.team_level,
                       ps.games, ps.games_started, ps.wins, ps.losses, ps.saves,
                       ps.holds, ps.blown_saves, ps.quality_starts,
                       ps.innings_pitched_outs, ps.hits_allowed,
                       ps.runs_allowed, ps.earned_runs,
                       ps.walks, ps.strikeouts, ps.home_runs_allowed,
                       ps.inside_the_park_hr_allowed,
                       ps.pitches_thrown, ps.hbp, ps.wildpitches
                FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                JOIN league_years ly ON ly.id = ps.league_year_id
                WHERE ps.player_id = :pid
                ORDER BY ly.season, tm.team_level
            """), {"pid": player_id}).mappings().all()

        def _bat_row(r):
            ab = int(r["at_bats"]); h = int(r["hits"]); bb = int(r["walks"])
            hbp = int(r.get("hbp", 0) or 0); sf = int(r.get("sacrifice_flies", 0) or 0)
            pa = ab + bb + hbp + sf
            d = int(r["doubles_hit"]); t = int(r["triples"]); hr = int(r["home_runs"])
            tb = h + d + 2 * t + 3 * hr
            slg = tb / ab if ab else 0
            obp = (h + bb + hbp) / (ab + bb + hbp + sf) if (ab + bb + hbp + sf) else 0
            return {
                "season": int(r["season"]) if "season" in r else None,
                "team": r.get("team_abbrev"),
                "level": int(r["team_level"]) if "team_level" in r else None,
                "g": int(r["games"]), "ab": ab, "pa": pa,
                "r": int(r["runs"]), "h": h, "2b": d, "3b": t,
                "hr": hr, "rbi": int(r["rbi"]),
                "bb": bb, "so": int(r["strikeouts"]),
                "sb": int(r["stolen_bases"]), "cs": int(r["caught_stealing"]),
                "hbp": hbp, "sf": sf,
                "avg": f"{h / ab:.3f}" if ab else ".000",
                "obp": f"{obp:.3f}", "slg": f"{slg:.3f}",
                "ops": f"{(obp + slg):.3f}",
            }

        def _pit_row(r):
            ipo = int(r["innings_pitched_outs"]); er = int(r["earned_runs"])
            return {
                "season": int(r["season"]) if "season" in r else None,
                "team": r.get("team_abbrev"),
                "level": int(r["team_level"]) if "team_level" in r else None,
                "g": int(r["games"]), "gs": int(r["games_started"]),
                "w": int(r["wins"]), "l": int(r["losses"]), "sv": int(r["saves"]),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": er, "bb": int(r["walks"]), "so": int(r["strikeouts"]),
                "hr": int(r["home_runs_allowed"]),
                "era": f"{er * 27.0 / ipo:.2f}" if ipo else "0.00",
                "whip": f"{(int(r['walks']) + int(r['hits_allowed'])) * 3.0 / ipo:.2f}" if ipo else "0.00",
            }

        batting = [_bat_row(r) for r in bat_rows]
        pitching = [_pit_row(r) for r in pit_rows]

        # Career totals
        if len(batting) > 1:
            tot = {}
            sum_keys = ["g", "ab", "pa", "r", "h", "2b", "3b", "hr", "rbi",
                        "bb", "so", "sb", "cs", "hbp", "sf"]
            for k in sum_keys:
                tot[k] = sum(s[k] for s in batting)
            ab = tot["ab"]; h = tot["h"]; bb = tot["bb"]; hbp = tot["hbp"]
            sf = tot["sf"]
            d = tot["2b"]; t = tot["3b"]; hr = tot["hr"]
            tb = h + d + 2 * t + 3 * hr
            obp_d = ab + bb + hbp + sf
            obp = (h + bb + hbp) / obp_d if obp_d else 0
            slg = tb / ab if ab else 0
            tot.update({
                "season": "Career", "team": None, "level": None,
                "avg": f"{h / ab:.3f}" if ab else ".000",
                "obp": f"{obp:.3f}", "slg": f"{slg:.3f}",
                "ops": f"{(obp + slg):.3f}",
            })
            batting.append(tot)

        if len(pitching) > 1:
            tot = {}
            sum_keys = ["g", "gs", "w", "l", "sv", "h", "r", "er", "bb", "so", "hr"]
            for k in sum_keys:
                tot[k] = sum(s[k] for s in pitching)
            total_ipo = sum(int(r["innings_pitched_outs"]) for r in pit_rows)
            tot.update({
                "season": "Career", "team": None, "level": None,
                "ip": f"{total_ipo // 3}.{total_ipo % 3}",
                "era": f"{tot['er'] * 27.0 / total_ipo:.2f}" if total_ipo else "0.00",
                "whip": f"{(tot['bb'] + tot['h']) * 3.0 / total_ipo:.2f}" if total_ipo else "0.00",
            })
            pitching.append(tot)

        return jsonify(
            player_id=player_id,
            name=f"{player['firstName']} {player['lastName']}",
            batting=batting, pitching=pitching,
        ), 200

    except SQLAlchemyError as e:
        logger.exception("Stats career error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Phase 4D: Split stats (home/away, by opponent)
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/player/<int:player_id>/splits")
def player_splits(player_id: int):
    """
    Batting and pitching splits: home/away and by opponent.

    Query params: league_year_id (required)
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            bat_ha = conn.execute(sa_text("""
                SELECT
                    CASE WHEN gr.home_team_id = gbl.team_id THEN 'home' ELSE 'away' END AS split,
                    SUM(gbl.at_bats) AS ab, SUM(gbl.hits) AS h,
                    SUM(gbl.doubles_hit) AS d2, SUM(gbl.triples) AS d3,
                    SUM(gbl.home_runs) AS hr, SUM(gbl.rbi) AS rbi,
                    SUM(gbl.walks) AS bb, SUM(gbl.strikeouts) AS so,
                    SUM(gbl.stolen_bases) AS sb, SUM(gbl.caught_stealing) AS cs,
                    SUM(gbl.hbp) AS hbp, SUM(gbl.plate_appearances) AS pa,
                    COUNT(*) AS g
                FROM game_batting_lines gbl
                JOIN game_results gr ON gr.game_id = gbl.game_id
                WHERE gbl.player_id = :pid AND gbl.league_year_id = :lyid
                GROUP BY split
            """), {"pid": player_id, "lyid": league_year_id}).mappings().all()

            bat_opp = conn.execute(sa_text("""
                SELECT
                    CASE WHEN gr.home_team_id = gbl.team_id
                         THEN gr.away_team_id ELSE gr.home_team_id END AS opp_id,
                    opp.team_abbrev AS opponent,
                    SUM(gbl.at_bats) AS ab, SUM(gbl.hits) AS h,
                    SUM(gbl.doubles_hit) AS d2, SUM(gbl.triples) AS d3,
                    SUM(gbl.home_runs) AS hr, SUM(gbl.rbi) AS rbi,
                    SUM(gbl.walks) AS bb, SUM(gbl.strikeouts) AS so,
                    SUM(gbl.hbp) AS hbp, SUM(gbl.plate_appearances) AS pa,
                    COUNT(*) AS g
                FROM game_batting_lines gbl
                JOIN game_results gr ON gr.game_id = gbl.game_id
                JOIN teams opp ON opp.id = CASE WHEN gr.home_team_id = gbl.team_id
                     THEN gr.away_team_id ELSE gr.home_team_id END
                WHERE gbl.player_id = :pid AND gbl.league_year_id = :lyid
                GROUP BY opp_id, opp.team_abbrev
                ORDER BY SUM(gbl.at_bats) DESC
            """), {"pid": player_id, "lyid": league_year_id}).mappings().all()

            pit_ha = conn.execute(sa_text("""
                SELECT
                    CASE WHEN gr.home_team_id = gpl.team_id THEN 'home' ELSE 'away' END AS split,
                    SUM(gpl.innings_pitched_outs) AS ipo,
                    SUM(gpl.hits_allowed) AS ha, SUM(gpl.earned_runs) AS er,
                    SUM(gpl.walks) AS bb, SUM(gpl.strikeouts) AS so,
                    SUM(gpl.home_runs_allowed) AS hra,
                    SUM(gpl.hbp) AS hbp,
                    COUNT(*) AS g
                FROM game_pitching_lines gpl
                JOIN game_results gr ON gr.game_id = gpl.game_id
                WHERE gpl.player_id = :pid AND gpl.league_year_id = :lyid
                GROUP BY split
            """), {"pid": player_id, "lyid": league_year_id}).mappings().all()

        def _bat_split(r):
            ab = int(r["ab"]); h = int(r["h"]); bb = int(r["bb"])
            hbp = int(r.get("hbp", 0) or 0)
            pa = ab + bb + hbp
            d = int(r["d2"]); t = int(r["d3"]); hr = int(r["hr"])
            tb = h + d + 2 * t + 3 * hr
            slg = tb / ab if ab else 0
            obp = (h + bb + hbp) / pa if pa else 0
            return {
                "g": int(r["g"]), "ab": ab, "pa": pa,
                "h": h, "2b": d, "3b": t, "hr": hr,
                "rbi": int(r["rbi"]), "bb": bb, "so": int(r["so"]),
                "sb": int(r.get("sb", 0) or 0), "cs": int(r.get("cs", 0) or 0),
                "hbp": hbp,
                "avg": f"{h / ab:.3f}" if ab else ".000",
                "obp": f"{obp:.3f}", "slg": f"{slg:.3f}",
                "ops": f"{(obp + slg):.3f}",
            }

        def _pit_split(r):
            ipo = int(r["ipo"]); er = int(r["er"])
            return {
                "g": int(r["g"]),
                "ip": f"{ipo // 3}.{ipo % 3}",
                "h": int(r["ha"]), "er": er,
                "bb": int(r["bb"]), "so": int(r["so"]),
                "hr": int(r["hra"]),
                "era": f"{er * 27.0 / ipo:.2f}" if ipo else "0.00",
            }

        batting_ha = {r["split"]: _bat_split(r) for r in bat_ha}
        batting_vs = [{**_bat_split(r), "opponent": r["opponent"]} for r in bat_opp]
        pitching_ha = {r["split"]: _pit_split(r) for r in pit_ha}

        return jsonify(
            batting_home_away=batting_ha,
            batting_vs_opponent=batting_vs,
            pitching_home_away=pitching_ha,
        ), 200

    except SQLAlchemyError as e:
        logger.exception("Stats splits error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Phase 4E: Stat distribution (league-wide histogram)
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/distribution")
def stat_distribution():
    """
    Bucketed histogram of a stat across the league for a given season.

    Query params:
      league_year_id (required), league_level (required),
      stat (e.g. avg, obp, ops, era, whip, fip — required),
      category (batting|pitching, default batting),
      min_pa / min_ip (qualifying thresholds),
      buckets (number of histogram bins, default 20),
      player_id (optional — highlight this player's percentile)
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    league_level = request.args.get("league_level", type=int)
    stat = request.args.get("stat", "")
    category = request.args.get("category", "batting")
    buckets = min(request.args.get("buckets", 20, type=int), 100)
    highlight_pid = request.args.get("player_id", type=int)

    if not league_year_id or not league_level or not stat:
        return jsonify(error="missing_field",
                       message="league_year_id, league_level, and stat are required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            if category == "pitching":
                min_ip = request.args.get("min_ip", 10, type=int)
                min_ipo = min_ip * 3
                rows = conn.execute(sa_text("""
                    SELECT ps.player_id,
                           ps.innings_pitched_outs, ps.hits_allowed, ps.earned_runs,
                           ps.walks, ps.strikeouts, ps.home_runs_allowed,
                           ps.games_started, ps.wins, ps.losses, ps.hbp,
                           ps.batters_faced
                    FROM player_pitching_stats ps
                    JOIN teams tm ON tm.id = ps.team_id
                    WHERE ps.league_year_id = :lyid AND tm.team_level = :level
                      AND ps.innings_pitched_outs >= :min_ipo
                """), {"lyid": league_year_id, "level": league_level,
                       "min_ipo": min_ipo}).mappings().all()

                _ipo = lambda r: float(r["innings_pitched_outs"])  # noqa: E731
                stat_map = {
                    "era": lambda r: float(r["earned_runs"]) * 27.0 / _ipo(r) if _ipo(r) else None,
                    "whip": lambda r: (float(r["walks"]) + float(r["hits_allowed"])) * 3.0 / _ipo(r) if _ipo(r) else None,
                    "k9": lambda r: float(r["strikeouts"]) * 27.0 / _ipo(r) if _ipo(r) else None,
                    "bb9": lambda r: float(r["walks"]) * 27.0 / _ipo(r) if _ipo(r) else None,
                    "fip": lambda r: ((13.0 * float(r["home_runs_allowed"])
                                       + 3.0 * (float(r["walks"]) + float(r.get("hbp", 0) or 0))
                                       - 2.0 * float(r["strikeouts"]))
                                      / (_ipo(r) / 3.0) + 3.17) if _ipo(r) else None,
                }
            else:
                min_pa = request.args.get("min_pa", 50, type=int)
                rows = conn.execute(sa_text("""
                    SELECT bs.player_id,
                           bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
                           bs.home_runs, bs.walks, bs.strikeouts,
                           bs.stolen_bases, bs.caught_stealing,
                           bs.plate_appearances, bs.hbp
                    FROM player_batting_stats bs
                    JOIN teams tm ON tm.id = bs.team_id
                    WHERE bs.league_year_id = :lyid AND tm.team_level = :level
                      AND (bs.at_bats + bs.walks + bs.hbp) >= :min_pa
                """), {"lyid": league_year_id, "level": league_level,
                       "min_pa": min_pa}).mappings().all()

                def _obp_calc(r):
                    _pa = float(r["at_bats"]) + float(r["walks"]) + float(r.get("hbp", 0) or 0)
                    return (float(r["hits"]) + float(r["walks"]) + float(r.get("hbp", 0) or 0)) / _pa if _pa else None

                def _slg_calc(r):
                    ab = float(r["at_bats"])
                    return (float(r["hits"]) + float(r["doubles_hit"]) + 2 * float(r["triples"])
                            + 3 * float(r["home_runs"])) / ab if ab else None

                stat_map = {
                    "avg": lambda r: float(r["hits"]) / float(r["at_bats"]) if float(r["at_bats"]) else None,
                    "obp": _obp_calc,
                    "slg": _slg_calc,
                    "ops": lambda r: ((_obp_calc(r) or 0) + (_slg_calc(r) or 0)) or None,
                    "iso": lambda r: (float(r["doubles_hit"]) + 2 * float(r["triples"])
                                      + 3 * float(r["home_runs"])) / float(r["at_bats"]) if float(r["at_bats"]) else None,
                    "babip": lambda r: ((float(r["hits"]) - float(r["home_runs"]))
                                        / (float(r["at_bats"]) - float(r["strikeouts"]) - float(r["home_runs"]))
                                        if (float(r["at_bats"]) - float(r["strikeouts"]) - float(r["home_runs"])) > 0
                                        else None),
                }

        calc = stat_map.get(stat)
        if not calc:
            return jsonify(error="invalid_stat",
                           message=f"Unknown stat '{stat}'. Available: {list(stat_map.keys())}"), 400

        values = []
        highlight_val = None
        for r in rows:
            v = calc(r)
            if v is not None:
                values.append(v)
                if highlight_pid and int(r["player_id"]) == highlight_pid:
                    highlight_val = v

        if not values:
            return jsonify(histogram=[], stat=stat, count=0), 200

        min_v = min(values); max_v = max(values)
        if min_v == max_v:
            return jsonify(
                histogram=[{"min": min_v, "max": max_v, "count": len(values)}],
                stat=stat, count=len(values),
                mean=round(sum(values) / len(values), 4),
            ), 200

        step = (max_v - min_v) / buckets
        bins = [0] * buckets
        for v in values:
            idx = min(int((v - min_v) / step), buckets - 1)
            bins[idx] += 1

        histogram = [{"min": round(min_v + i * step, 4),
                      "max": round(min_v + (i + 1) * step, 4),
                      "count": c} for i, c in enumerate(bins)]

        mean = sum(values) / len(values)
        sorted_vals = sorted(values)
        median = sorted_vals[len(sorted_vals) // 2]

        result = {
            "histogram": histogram, "stat": stat, "category": category,
            "count": len(values),
            "mean": round(mean, 4), "median": round(median, 4),
            "min": round(min_v, 4), "max": round(max_v, 4),
        }

        if highlight_pid and highlight_val is not None:
            pct_rank = sum(1 for v in values if v <= highlight_val) / len(values) * 100
            result["player"] = {
                "player_id": highlight_pid,
                "value": round(highlight_val, 4),
                "percentile": round(pct_rank, 1),
            }

        return jsonify(result), 200

    except SQLAlchemyError as e:
        logger.exception("Stats distribution error: %s", e)
        return jsonify(error="database_error", message=str(e)), 500
