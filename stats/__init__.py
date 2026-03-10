# stats/__init__.py
"""
Stats blueprint: leaderboards, player stats, team stats, splits, injuries, positions.
"""

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

stats_bp = Blueprint("stats", __name__)


# ---------------------------------------------------------------------------
# Batting leaderboard
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/batting")
def batting_leaderboard():
    """
    Batting leaderboard from player_batting_stats.

    Query params:
      league_year_id (required), league_level, team_id,
      sort (avg|hr|rbi|hits|sb|ops, default avg),
      min_ab (default 20), page, page_size (default 50)
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    league_level = request.args.get("league_level", type=int)
    team_id = request.args.get("team_id", type=int)
    sort = request.args.get("sort", "avg")
    min_ab = request.args.get("min_ab", 20, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    # Map sort param to SQL expression
    sort_map = {
        "avg": "IF(at_bats > 0, hits / at_bats, 0) DESC",
        "hr": "home_runs DESC",
        "rbi": "rbi DESC",
        "hits": "hits DESC",
        "sb": "stolen_bases DESC",
        "ops": "(IF(at_bats + walks > 0, (hits + walks) / (at_bats + walks), 0) + "
               "IF(at_bats > 0, (hits + doubles_hit + 2*triples + 3*home_runs) / at_bats, 0)) DESC",
    }
    order_by = sort_map.get(sort, sort_map["avg"])

    where_parts = ["bs.league_year_id = :lyid", "bs.at_bats >= :min_ab"]
    params = {"lyid": league_year_id, "min_ab": min_ab}

    if team_id:
        where_parts.append("bs.team_id = :tid")
        params["tid"] = team_id
    if league_level:
        where_parts.append("tm.league_level = :ll")
        params["ll"] = league_level

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                WHERE {where_sql}
            """), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT bs.player_id, bs.team_id, bs.games, bs.at_bats,
                       bs.runs, bs.hits, bs.doubles_hit, bs.triples,
                       bs.home_runs, bs.rbi, bs.walks, bs.strikeouts,
                       bs.stolen_bases, bs.caught_stealing,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       IF(bs.at_bats > 0, ROUND(bs.hits / bs.at_bats, 3), 0) AS avg,
                       IF(bs.at_bats + bs.walks > 0,
                          ROUND((bs.hits + bs.walks) / (bs.at_bats + bs.walks), 3), 0) AS obp,
                       IF(bs.at_bats > 0,
                          ROUND((bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs)
                                / bs.at_bats, 3), 0) AS slg
                FROM player_batting_stats bs
                JOIN simbbPlayers p ON p.id = bs.player_id
                JOIN teams tm ON tm.id = bs.team_id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        leaders = []
        for i, r in enumerate(rows):
            avg_val = float(r["avg"])
            obp_val = float(r["obp"])
            slg_val = float(r["slg"])
            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "ab": int(r["at_bats"]),
                "r": int(r["runs"]), "h": int(r["hits"]),
                "2b": int(r["doubles_hit"]), "3b": int(r["triples"]),
                "hr": int(r["home_runs"]), "rbi": int(r["rbi"]),
                "bb": int(r["walks"]), "so": int(r["strikeouts"]),
                "sb": int(r["stolen_bases"]), "cs": int(r["caught_stealing"]),
                "avg": f"{avg_val:.3f}",
                "obp": f"{obp_val:.3f}",
                "slg": f"{slg_val:.3f}",
                "ops": f"{obp_val + slg_val:.3f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
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
      sort (era|wins|so|saves|whip, default era),
      min_ip (default 10 = 30 outs), page, page_size
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    team_id = request.args.get("team_id", type=int)
    sort = request.args.get("sort", "era")
    min_ip_innings = request.args.get("min_ip", 10, type=int)
    min_ipo = min_ip_innings * 3  # convert IP to outs
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    sort_map = {
        "era": "IF(ps.innings_pitched_outs > 0, ps.earned_runs * 27.0 / ps.innings_pitched_outs, 99) ASC",
        "wins": "ps.wins DESC",
        "so": "ps.strikeouts DESC",
        "saves": "ps.saves DESC",
        "whip": "IF(ps.innings_pitched_outs > 0, (ps.walks + ps.hits_allowed) * 3.0 / ps.innings_pitched_outs, 99) ASC",
    }
    order_by = sort_map.get(sort, sort_map["era"])

    where_parts = ["ps.league_year_id = :lyid",
                    "ps.innings_pitched_outs >= :min_ipo"]
    params = {"lyid": league_year_id, "min_ipo": min_ipo}

    if team_id:
        where_parts.append("ps.team_id = :tid")
        params["tid"] = team_id

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_pitching_stats ps
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
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       IF(ps.innings_pitched_outs > 0,
                          ROUND(ps.earned_runs * 27.0 / ps.innings_pitched_outs, 2), 0) AS era,
                       IF(ps.innings_pitched_outs > 0,
                          ROUND((ps.walks + ps.hits_allowed) * 3.0
                                / ps.innings_pitched_outs, 2), 0) AS whip
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
            ip = f"{ipo // 3}.{ipo % 3}"
            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "g": int(r["games"]), "gs": int(r["games_started"]),
                "w": int(r["wins"]), "l": int(r["losses"]),
                "sv": int(r["saves"]), "ip": ip,
                "h": int(r["hits_allowed"]), "r": int(r["runs_allowed"]),
                "er": int(r["earned_runs"]), "bb": int(r["walks"]),
                "so": int(r["strikeouts"]), "hr": int(r["home_runs_allowed"]),
                "era": f"{float(r['era']):.2f}",
                "whip": f"{float(r['whip']):.2f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Fielding leaderboard
# ---------------------------------------------------------------------------

@stats_bp.get("/stats/fielding")
def fielding_leaderboard():
    """
    Fielding leaderboard from player_fielding_stats.

    Query params:
      league_year_id (required), position_code, team_id,
      sort (fpct|putouts|assists, default fpct),
      page, page_size
    """
    from sqlalchemy import text as sa_text

    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_field",
                       message="league_year_id is required"), 400

    position_code = request.args.get("position_code")
    team_id = request.args.get("team_id", type=int)
    sort = request.args.get("sort", "fpct")
    page = request.args.get("page", 1, type=int)
    page_size = min(request.args.get("page_size", 50, type=int), 200)

    sort_map = {
        "fpct": "IF(fs.putouts + fs.assists + fs.errors > 0, "
                "(fs.putouts + fs.assists) / (fs.putouts + fs.assists + fs.errors), 0) DESC",
        "putouts": "fs.putouts DESC",
        "assists": "fs.assists DESC",
    }
    order_by = sort_map.get(sort, sort_map["fpct"])

    where_parts = ["fs.league_year_id = :lyid"]
    params = {"lyid": league_year_id}

    if position_code:
        where_parts.append("fs.position_code = :pos")
        params["pos"] = position_code
    if team_id:
        where_parts.append("fs.team_id = :tid")
        params["tid"] = team_id

    where_sql = " AND ".join(where_parts)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            total = conn.execute(sa_text(f"""
                SELECT COUNT(*) FROM player_fielding_stats fs WHERE {where_sql}
            """), params).scalar()

            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            rows = conn.execute(sa_text(f"""
                SELECT fs.player_id, fs.team_id, fs.position_code,
                       fs.games, fs.innings, fs.putouts, fs.assists, fs.errors,
                       p.firstName, p.lastName,
                       tm.team_abbrev AS team_abbrev,
                       IF(fs.putouts + fs.assists + fs.errors > 0,
                          ROUND((fs.putouts + fs.assists)
                                / (fs.putouts + fs.assists + fs.errors), 3), 0) AS fpct
                FROM player_fielding_stats fs
                JOIN simbbPlayers p ON p.id = fs.player_id
                JOIN teams tm ON tm.id = fs.team_id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        leaders = []
        for i, r in enumerate(rows):
            leaders.append({
                "rank": offset + i + 1,
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}",
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "pos": r["position_code"],
                "g": int(r["games"]), "inn": int(r["innings"]),
                "po": int(r["putouts"]), "a": int(r["assists"]),
                "e": int(r["errors"]),
                "fpct": f"{float(r['fpct']):.3f}",
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return jsonify(leaders=leaders, total=total, page=page, pages=pages), 200

    except SQLAlchemyError as e:
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
            level_filter = "AND tm.league_level = :ll"
            params["ll"] = league_level

        with engine.connect() as conn:
            bat_rows = conn.execute(sa_text(f"""
                SELECT bs.team_id, tm.team_abbrev AS team_abbrev,
                       SUM(bs.games) AS g, SUM(bs.at_bats) AS ab,
                       SUM(bs.runs) AS r, SUM(bs.hits) AS h,
                       SUM(bs.doubles_hit) AS `2b`, SUM(bs.triples) AS `3b`,
                       SUM(bs.home_runs) AS hr, SUM(bs.rbi) AS rbi,
                       SUM(bs.walks) AS bb, SUM(bs.strikeouts) AS so,
                       SUM(bs.stolen_bases) AS sb,
                       IF(SUM(bs.at_bats) > 0,
                          ROUND(SUM(bs.hits) / SUM(bs.at_bats), 3), 0) AS avg
                FROM player_batting_stats bs
                JOIN teams tm ON tm.id = bs.team_id
                WHERE bs.league_year_id = :lyid {level_filter}
                GROUP BY bs.team_id, tm.team_abbrev
                ORDER BY avg DESC
            """), params).mappings().all()

            pit_rows = conn.execute(sa_text(f"""
                SELECT ps.team_id, tm.team_abbrev AS team_abbrev,
                       SUM(ps.innings_pitched_outs) AS ipo,
                       SUM(ps.earned_runs) AS er,
                       SUM(ps.walks) AS bb, SUM(ps.strikeouts) AS so,
                       SUM(ps.hits_allowed) AS ha,
                       IF(SUM(ps.innings_pitched_outs) > 0,
                          ROUND(SUM(ps.earned_runs) * 27.0
                                / SUM(ps.innings_pitched_outs), 2), 0) AS era,
                       IF(SUM(ps.innings_pitched_outs) > 0,
                          ROUND((SUM(ps.walks) + SUM(ps.hits_allowed)) * 3.0
                                / SUM(ps.innings_pitched_outs), 2), 0) AS whip
                FROM player_pitching_stats ps
                JOIN teams tm ON tm.id = ps.team_id
                WHERE ps.league_year_id = :lyid {level_filter}
                GROUP BY ps.team_id, tm.team_abbrev
                ORDER BY era ASC
            """), params).mappings().all()

        batting = [{
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "g": int(r["g"]), "ab": int(r["ab"]),
            "r": int(r["r"]), "h": int(r["h"]),
            "2b": int(r["2b"]), "3b": int(r["3b"]),
            "hr": int(r["hr"]), "rbi": int(r["rbi"]),
            "bb": int(r["bb"]), "so": int(r["so"]),
            "sb": int(r["sb"]),
            "avg": f"{float(r['avg']):.3f}",
        } for r in bat_rows]

        pitching = []
        for r in pit_rows:
            ipo = int(r["ipo"])
            pitching.append({
                "team_id": int(r["team_id"]),
                "team_abbrev": r["team_abbrev"],
                "ip": f"{ipo // 3}.{ipo % 3}",
                "er": int(r["er"]), "bb": int(r["bb"]),
                "so": int(r["so"]), "ha": int(r["ha"]),
                "era": f"{float(r['era']):.2f}",
                "whip": f"{float(r['whip']):.2f}",
            })

        return jsonify(batting=batting, pitching=pitching), 200

    except SQLAlchemyError as e:
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
                       bs.home_runs, bs.rbi, bs.walks, bs.strikeouts,
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
                "hr": int(r["home_runs"]), "rbi": int(r["rbi"]),
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
                "dec": "W" if int(r["win"]) else ("L" if int(r["loss"]) else
                       ("S" if int(r["save_recorded"]) else "")),
            } for r in gamelog_pit]

        return jsonify(result), 200

    except SQLAlchemyError as e:
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
        where_parts.append("t.orgID = :oid")
        params["oid"] = org_id
    if team_id:
        where_parts.append("c.team_id = :tid")
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
                       c.team_id, t.team_abbrev AS team_abbrev, t.orgID AS org_id
                FROM player_injury_state pis
                JOIN simbbPlayers p ON p.id = pis.player_id
                JOIN player_injury_events pie ON pie.id = pis.current_event_id
                JOIN injury_types it ON it.id = pie.injury_type_id
                LEFT JOIN contracts c ON c.player_id = pis.player_id
                    AND c.status = 'active'
                LEFT JOIN teams t ON t.id = c.team_id
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
        where_parts.append("t.orgID = :oid")
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
                       c.team_id, t.team_abbrev AS team_abbrev
                FROM player_injury_events pie
                JOIN simbbPlayers p ON p.id = pie.player_id
                LEFT JOIN injury_types it ON it.id = pie.injury_type_id
                LEFT JOIN contracts c ON c.player_id = pie.player_id
                    AND c.status = 'active'
                LEFT JOIN teams t ON t.id = c.team_id
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
        return jsonify(error="database_error", message=str(e)), 500
