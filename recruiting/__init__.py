# recruiting/__init__.py
"""
College recruiting endpoints — weighted lottery system.

Endpoints:
  GET  /recruiting/rankings          — public star rankings
  POST /recruiting/rankings/wipe     — admin: delete all rankings for year
  POST /recruiting/rankings/regenerate — admin: recompute rankings for year
  GET  /recruiting/state             — current recruiting phase state
  POST /recruiting/invest            — submit weekly investments
  POST /recruiting/advance-week      — admin: advance recruiting one week
  GET  /recruiting/board/<org_id>    — org's recruiting board (fog-of-war)
  POST /recruiting/board/add         — add player to board
  POST /recruiting/board/remove      — remove player from board
  GET  /recruiting/player/<pid>      — single player detail (fog-of-war)
  GET  /recruiting/commitments       — public commitment list
"""

import logging

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text as sa_text

log = logging.getLogger(__name__)

from db import get_engine
from services.recruiting import (
    get_recruiting_config,
    compute_star_rankings,
    wipe_star_rankings,
    submit_weekly_investments,
    advance_recruiting_week,
    get_player_recruiting_status,
    get_org_recruiting_board,
    add_to_recruiting_board,
    remove_from_recruiting_board,
    get_recruiting_board_ids,
    COLLEGE_ORG_MIN,
    COLLEGE_ORG_MAX,
)

recruiting_bp = Blueprint("recruiting", __name__)

# Pagination defaults
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


# ---------------------------------------------------------------------------
# GET /recruiting/rankings
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/rankings")
def rankings():
    """
    Public star rankings, paginated.
    Query params: league_year_id, page, per_page, star_rating, ptype, search
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param", message="league_year_id required"), 400

    page = max(1, request.args.get("page", DEFAULT_PAGE, type=int))
    per_page = min(MAX_PER_PAGE, max(1, request.args.get("per_page", DEFAULT_PER_PAGE, type=int)))
    star_filter = request.args.get("star_rating", type=int)
    ptype_filter = request.args.get("ptype")
    search = request.args.get("search", "").strip()

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # Build query
            where_clauses = ["rr.league_year_id = :ly"]
            params = {"ly": league_year_id}

            if star_filter:
                where_clauses.append("rr.star_rating = :star")
                params["star"] = star_filter
            if ptype_filter:
                where_clauses.append("p.ptype = :ptype")
                params["ptype"] = ptype_filter
            if search:
                where_clauses.append(
                    "(p.firstname LIKE :search OR p.lastname LIKE :search)"
                )
                params["search"] = f"%{search}%"

            where_sql = " AND ".join(where_clauses)

            # Count
            count_row = conn.execute(
                sa_text(f"""
                    SELECT COUNT(*)
                    FROM recruiting_rankings rr
                    JOIN simbbPlayers p ON p.id = rr.player_id
                    WHERE {where_sql}
                """),
                params,
            ).scalar()

            # Paginated results
            offset = (page - 1) * per_page
            params["limit"] = per_page
            params["offset"] = offset

            rows = conn.execute(
                sa_text(f"""
                    SELECT rr.player_id, rr.star_rating, rr.rank_overall,
                           rr.rank_by_ptype, rr.composite_score,
                           p.firstname, p.lastname, p.ptype, p.age
                    FROM recruiting_rankings rr
                    JOIN simbbPlayers p ON p.id = rr.player_id
                    WHERE {where_sql}
                    ORDER BY rr.rank_overall ASC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            ).all()

            players = []
            for r in rows:
                m = r._mapping
                players.append({
                    "player_id": m["player_id"],
                    "player_name": f"{m['firstname']} {m['lastname']}",
                    "ptype": m["ptype"],
                    "age": m["age"],
                    "star_rating": m["star_rating"],
                    "rank_overall": m["rank_overall"],
                    "rank_by_ptype": m["rank_by_ptype"],
                })

        total_pages = max(1, -(-count_row // per_page))  # ceiling division
        return jsonify(
            players=players,
            page=page,
            per_page=per_page,
            total=count_row,
            total_pages=total_pages,
        )

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/rankings/wipe
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/rankings/wipe")
def rankings_wipe():
    """Admin: wipe all star rankings for a league year."""
    data = request.get_json(silent=True) or {}
    league_year_id = data.get("league_year_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            deleted = wipe_star_rankings(conn, league_year_id)
        return jsonify(status="wiped", deleted=deleted,
                       league_year_id=league_year_id)

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/rankings/regenerate
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/rankings/regenerate")
def rankings_regenerate():
    """Admin: wipe and recompute star rankings for a league year."""
    data = request.get_json(silent=True) or {}
    league_year_id = data.get("league_year_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            ranked_count = compute_star_rankings(conn, league_year_id)
        return jsonify(status="regenerated", ranked_players=ranked_count,
                       league_year_id=league_year_id)

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/state
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/state")
def state():
    """Current recruiting phase state."""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param", message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa_text("""
                    SELECT current_week, status
                    FROM recruiting_state
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()

            if not row:
                return jsonify(
                    league_year_id=league_year_id,
                    current_week=0,
                    status="pending",
                )

            config = get_recruiting_config(conn)

            return jsonify(
                league_year_id=league_year_id,
                current_week=row[0],
                status=row[1],
                total_weeks=int(config.get("recruiting_weeks", 20)),
            )

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/invest
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/invest")
def invest():
    """
    Submit weekly recruiting investments.
    Body: {org_id, league_year_id, investments: [{player_id, points}, ...]}
    """
    data = request.get_json(force=True)
    org_id = data.get("org_id")
    league_year_id = data.get("league_year_id")
    week = data.get("week")
    investments = data.get("investments", [])

    if not all([org_id, league_year_id, week]):
        return jsonify(error="missing_param",
                       message="org_id, league_year_id, and week required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = submit_weekly_investments(
                conn, int(org_id), int(league_year_id),
                int(week), investments
            )
        return jsonify(result)

    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/investments/<org_id>
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/investments/<int:org_id>")
def get_investments(org_id: int):
    """
    Current week's investments for an org, plus budget info.
    Query params: league_year_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    if not (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX):
        return jsonify(error="validation_error",
                       message="Only college orgs can recruit"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # Get recruiting state
            state = conn.execute(
                sa_text("""
                    SELECT current_week, status FROM recruiting_state
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()

            current_week = state[0] if state else 0
            status = state[1] if state else "pending"

            # Get config for budget limits
            config_rows = conn.execute(
                sa_text("SELECT config_key, config_value FROM recruiting_config")
            ).all()
            config = {r[0]: r[1] for r in config_rows}
            weekly_budget = int(config.get("points_per_week", 100))
            max_per_player = int(config.get("max_points_per_player_per_week", 20))

            # This week's investments
            week_rows = conn.execute(
                sa_text("""
                    SELECT ri.player_id, ri.points,
                           p.firstname, p.lastname, p.ptype
                    FROM recruiting_investments ri
                    JOIN simbbPlayers p ON p.id = ri.player_id
                    WHERE ri.org_id = :org
                      AND ri.league_year_id = :ly
                      AND ri.week = :week
                    ORDER BY ri.points DESC
                """),
                {"org": org_id, "ly": league_year_id, "week": current_week},
            ).all()

            investments = []
            spent = 0
            for r in week_rows:
                pts = int(r[1])
                spent += pts
                investments.append({
                    "player_id": r[0],
                    "points": pts,
                    "player_name": f"{r[2]} {r[3]}",
                    "ptype": r[4],
                })

        return jsonify(
            current_week=current_week,
            status=status,
            weekly_budget=weekly_budget,
            max_per_player=max_per_player,
            spent=spent,
            budget_remaining=weekly_budget - spent,
            investments=investments,
        )

    except SQLAlchemyError as e:
        log.exception("get_investments db error org=%s ly=%s", org_id, league_year_id)
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("get_investments error org=%s ly=%s", org_id, league_year_id)
        return jsonify(error="server_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/advance-week
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/advance-week")
def advance_week():
    """
    Admin action: advance recruiting by one week.
    Body: {league_year_id}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = advance_recruiting_week(conn, int(league_year_id))
        return jsonify(result)

    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/board/<org_id>
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/board/<int:org_id>")
def board(org_id: int):
    """
    Org's recruiting board with fog-of-war interest gauges.
    Query params: league_year_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    if not (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX):
        return jsonify(error="validation_error",
                       message="Only college orgs have recruiting boards"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            players = get_org_recruiting_board(conn, org_id, league_year_id)
            board_ids = get_recruiting_board_ids(conn, org_id, league_year_id)
        return jsonify(
            players=players,
            board_player_ids=sorted(board_ids),
        )

    except SQLAlchemyError as e:
        log.exception("recruiting board db error org=%s ly=%s", org_id, league_year_id)
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("recruiting board error org=%s ly=%s", org_id, league_year_id)
        return jsonify(error="server_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/player/<player_id>
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/player/<int:player_id>")
def player_detail(player_id: int):
    """
    Single player recruiting detail with fog-of-war.
    Query params: league_year_id, viewing_org_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    viewing_org_id = request.args.get("viewing_org_id", type=int)

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_player_recruiting_status(
                conn, player_id, league_year_id, viewing_org_id
            )

        if result is None:
            return jsonify(error="not_found",
                           message="Player not found in rankings"), 404

        return jsonify(result)

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/commitments
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/commitments")
def commitments():
    """
    Public: all commitments, paginated.
    Query params: league_year_id, page, per_page, org_id, star_rating, week
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    page = max(1, request.args.get("page", DEFAULT_PAGE, type=int))
    per_page = min(MAX_PER_PAGE, max(1, request.args.get("per_page", DEFAULT_PER_PAGE, type=int)))
    org_filter = request.args.get("org_id", type=int)
    star_filter = request.args.get("star_rating", type=int)
    week_filter = request.args.get("week", type=int)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            where_clauses = ["rc.league_year_id = :ly"]
            params = {"ly": league_year_id}

            if org_filter:
                where_clauses.append("rc.org_id = :org")
                params["org"] = org_filter
            if star_filter:
                where_clauses.append("rc.star_rating = :star")
                params["star"] = star_filter
            if week_filter:
                where_clauses.append("rc.week_committed = :week")
                params["week"] = week_filter

            where_sql = " AND ".join(where_clauses)

            count_row = conn.execute(
                sa_text(f"""
                    SELECT COUNT(*)
                    FROM recruiting_commitments rc
                    WHERE {where_sql}
                """),
                params,
            ).scalar()

            offset = (page - 1) * per_page
            params["limit"] = per_page
            params["offset"] = offset

            rows = conn.execute(
                sa_text(f"""
                    SELECT rc.player_id, rc.org_id, rc.week_committed,
                           rc.points_total, rc.star_rating,
                           p.firstname, p.lastname, p.ptype,
                           o.org_abbrev AS org_abbrev
                    FROM recruiting_commitments rc
                    JOIN simbbPlayers p ON p.id = rc.player_id
                    JOIN organizations o ON o.id = rc.org_id
                    WHERE {where_sql}
                    ORDER BY rc.week_committed ASC, rc.star_rating DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            ).all()

            result = []
            for r in rows:
                m = r._mapping
                result.append({
                    "player_id": m["player_id"],
                    "player_name": f"{m['firstname']} {m['lastname']}",
                    "ptype": m["ptype"],
                    "org_id": m["org_id"],
                    "org_abbrev": m["org_abbrev"],
                    "star_rating": m["star_rating"],
                    "week_committed": m["week_committed"],
                    "points_total": m["points_total"],
                })

        total_pages = max(1, -(-count_row // per_page))
        return jsonify(
            commitments=result,
            page=page,
            per_page=per_page,
            total=count_row,
            total_pages=total_pages,
        )

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/board/add
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/board/add")
def board_add():
    """Add a player to an org's recruiting board."""
    data = request.get_json(silent=True) or {}
    org_id = data.get("org_id")
    league_year_id = data.get("league_year_id")
    player_id = data.get("player_id")

    if not all([org_id, league_year_id, player_id]):
        return jsonify(error="missing_param",
                       message="org_id, league_year_id, and player_id required"), 400

    if not (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX):
        return jsonify(error="validation_error",
                       message="Only college orgs have recruiting boards"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            status = add_to_recruiting_board(conn, org_id, league_year_id, player_id)
        return jsonify(status=status, player_id=player_id)

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/board/remove
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/board/remove")
def board_remove():
    """Remove a player from an org's recruiting board."""
    data = request.get_json(silent=True) or {}
    org_id = data.get("org_id")
    league_year_id = data.get("league_year_id")
    player_id = data.get("player_id")

    if not all([org_id, league_year_id, player_id]):
        return jsonify(error="missing_param",
                       message="org_id, league_year_id, and player_id required"), 400

    if not (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX):
        return jsonify(error="validation_error",
                       message="Only college orgs have recruiting boards"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            status = remove_from_recruiting_board(conn, org_id, league_year_id, player_id)
        return jsonify(status=status, player_id=player_id)

    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ===========================================================================
# ADMIN MANAGEMENT ENDPOINTS
# ===========================================================================


# ---------------------------------------------------------------------------
# POST /recruiting/admin/reset-week
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/admin/reset-week")
def admin_reset_week():
    """
    Reset recruiting state to a specific week (default 1).
    Does NOT wipe investments/commitments — just rewinds the clock.
    Body: {league_year_id, target_week (optional, default 1)}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")
    target_week = data.get("target_week", 1)

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    target_week = int(target_week)
    if target_week < 0:
        return jsonify(error="validation_error",
                       message="target_week must be >= 0"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            status = "active" if target_week >= 1 else "pending"
            conn.execute(
                sa_text("""
                    INSERT INTO recruiting_state (league_year_id, current_week, status)
                    VALUES (:ly, :week, :status)
                    ON DUPLICATE KEY UPDATE current_week = :week, status = :status
                """),
                {"ly": league_year_id, "week": target_week, "status": status},
            )
        return jsonify(
            ok=True,
            league_year_id=league_year_id,
            current_week=target_week,
            status=status,
        )
    except SQLAlchemyError as e:
        log.exception("admin reset-week error")
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/admin/wipe-investments
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/admin/wipe-investments")
def admin_wipe_investments():
    """
    Wipe recruiting investments. Scoped by league_year_id, optionally
    filtered by org_id and/or player_id.
    Body: {league_year_id, org_id?, player_id?}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")
    org_id = data.get("org_id")
    player_id = data.get("player_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            where = ["league_year_id = :ly"]
            params = {"ly": league_year_id}

            if org_id:
                where.append("org_id = :org")
                params["org"] = int(org_id)
            if player_id:
                where.append("player_id = :pid")
                params["pid"] = int(player_id)

            where_sql = " AND ".join(where)
            r = conn.execute(
                sa_text(f"DELETE FROM recruiting_investments WHERE {where_sql}"),
                params,
            )
        scope = "all"
        if org_id and player_id:
            scope = f"org {org_id} + player {player_id}"
        elif org_id:
            scope = f"org {org_id}"
        elif player_id:
            scope = f"player {player_id}"

        return jsonify(ok=True, deleted=r.rowcount, scope=scope)

    except SQLAlchemyError as e:
        log.exception("admin wipe-investments error")
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/admin/wipe-commitments
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/admin/wipe-commitments")
def admin_wipe_commitments():
    """
    Wipe recruiting commitments. Scoped by league_year_id, optionally
    filtered by org_id and/or player_id.
    Body: {league_year_id, org_id?, player_id?}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")
    org_id = data.get("org_id")
    player_id = data.get("player_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            where = ["league_year_id = :ly"]
            params = {"ly": league_year_id}

            if org_id:
                where.append("org_id = :org")
                params["org"] = int(org_id)
            if player_id:
                where.append("player_id = :pid")
                params["pid"] = int(player_id)

            where_sql = " AND ".join(where)
            r = conn.execute(
                sa_text(f"DELETE FROM recruiting_commitments WHERE {where_sql}"),
                params,
            )
        scope = "all"
        if org_id and player_id:
            scope = f"org {org_id} + player {player_id}"
        elif org_id:
            scope = f"org {org_id}"
        elif player_id:
            scope = f"player {player_id}"

        return jsonify(ok=True, deleted=r.rowcount, scope=scope)

    except SQLAlchemyError as e:
        log.exception("admin wipe-commitments error")
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/admin/wipe-boards
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/admin/wipe-boards")
def admin_wipe_boards():
    """
    Wipe recruiting boards. Scoped by league_year_id, optionally by org_id.
    Body: {league_year_id, org_id?}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")
    org_id = data.get("org_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            where = ["league_year_id = :ly"]
            params = {"ly": league_year_id}

            if org_id:
                where.append("org_id = :org")
                params["org"] = int(org_id)

            where_sql = " AND ".join(where)
            r = conn.execute(
                sa_text(f"DELETE FROM recruiting_board WHERE {where_sql}"),
                params,
            )
        scope = f"org {org_id}" if org_id else "all"
        return jsonify(ok=True, deleted=r.rowcount, scope=scope)

    except SQLAlchemyError as e:
        log.exception("admin wipe-boards error")
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /recruiting/admin/full-reset
# ---------------------------------------------------------------------------
@recruiting_bp.post("/recruiting/admin/full-reset")
def admin_full_reset():
    """
    Full recruiting reset: wipe investments, commitments, boards, and
    reset state to pending (week 0). Rankings are preserved.
    Body: {league_year_id}
    """
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")

    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        deleted = {}
        with engine.begin() as conn:
            for tbl in ("recruiting_investments", "recruiting_commitments",
                        "recruiting_board"):
                r = conn.execute(
                    sa_text(f"DELETE FROM {tbl} WHERE league_year_id = :ly"),
                    {"ly": league_year_id},
                )
                deleted[tbl] = r.rowcount

            conn.execute(
                sa_text("""
                    INSERT INTO recruiting_state (league_year_id, current_week, status)
                    VALUES (:ly, 0, 'pending')
                    ON DUPLICATE KEY UPDATE current_week = 0, status = 'pending'
                """),
                {"ly": league_year_id},
            )
            deleted["state_reset"] = True

        return jsonify(ok=True, deleted=deleted)

    except SQLAlchemyError as e:
        log.exception("admin full-reset error")
        return jsonify(error="database_error", message=str(e)), 500


# ===========================================================================
# ADMIN REPORTING ENDPOINTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /recruiting/admin/report/summary
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/admin/report/summary")
def admin_report_summary():
    """
    High-level recruiting dashboard: state, counts, star distribution,
    budget utilization, commitment pace.
    Query params: league_year_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # State
            state = conn.execute(
                sa_text("""
                    SELECT current_week, status FROM recruiting_state
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()
            current_week = state[0] if state else 0
            status = state[1] if state else "pending"

            # Pool size
            pool_count = conn.execute(
                sa_text("""
                    SELECT COUNT(DISTINCT rr.player_id)
                    FROM recruiting_rankings rr
                    WHERE rr.league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).scalar() or 0

            # Star distribution
            star_rows = conn.execute(
                sa_text("""
                    SELECT star_rating, COUNT(*) AS cnt
                    FROM recruiting_rankings
                    WHERE league_year_id = :ly
                    GROUP BY star_rating
                    ORDER BY star_rating DESC
                """),
                {"ly": league_year_id},
            ).all()
            star_distribution = {int(r[0]): int(r[1]) for r in star_rows}

            # Commitment stats
            commit_stats = conn.execute(
                sa_text("""
                    SELECT COUNT(*) AS total,
                           COUNT(DISTINCT org_id) AS unique_orgs,
                           AVG(points_total) AS avg_points
                    FROM recruiting_commitments
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()
            committed_count = int(commit_stats[0]) if commit_stats else 0
            unique_orgs_committing = int(commit_stats[1]) if commit_stats else 0
            avg_winning_points = round(float(commit_stats[2] or 0), 1)

            # Commitments by star
            commit_by_star = conn.execute(
                sa_text("""
                    SELECT star_rating, COUNT(*) AS cnt
                    FROM recruiting_commitments
                    WHERE league_year_id = :ly
                    GROUP BY star_rating
                    ORDER BY star_rating DESC
                """),
                {"ly": league_year_id},
            ).all()
            committed_by_star = {int(r[0]): int(r[1]) for r in commit_by_star}

            # Investment activity
            invest_stats = conn.execute(
                sa_text("""
                    SELECT COUNT(DISTINCT org_id) AS active_orgs,
                           COUNT(DISTINCT player_id) AS targeted_players,
                           SUM(points) AS total_points,
                           COUNT(*) AS total_allocations
                    FROM recruiting_investments
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()
            active_orgs = int(invest_stats[0]) if invest_stats else 0
            targeted_players = int(invest_stats[1]) if invest_stats else 0
            total_points = int(invest_stats[2] or 0)
            total_allocations = int(invest_stats[3]) if invest_stats else 0

            # Weekly investment trend
            weekly_trend = conn.execute(
                sa_text("""
                    SELECT week, COUNT(DISTINCT org_id) AS orgs,
                           SUM(points) AS points,
                           COUNT(DISTINCT player_id) AS players
                    FROM recruiting_investments
                    WHERE league_year_id = :ly
                    GROUP BY week
                    ORDER BY week
                """),
                {"ly": league_year_id},
            ).all()
            weeks = [
                {"week": int(r[0]), "active_orgs": int(r[1]),
                 "points_spent": int(r[2]), "players_targeted": int(r[3])}
                for r in weekly_trend
            ]

            # Commitment pace (by week)
            commit_pace = conn.execute(
                sa_text("""
                    SELECT week_committed, COUNT(*) AS cnt
                    FROM recruiting_commitments
                    WHERE league_year_id = :ly
                    GROUP BY week_committed
                    ORDER BY week_committed
                """),
                {"ly": league_year_id},
            ).all()
            commitment_pace = [
                {"week": int(r[0]), "commitments": int(r[1])}
                for r in commit_pace
            ]

        return jsonify(
            current_week=current_week,
            status=status,
            pool_size=pool_count,
            star_distribution=star_distribution,
            committed_count=committed_count,
            uncommitted_count=pool_count - committed_count,
            unique_orgs_committing=unique_orgs_committing,
            avg_winning_points=avg_winning_points,
            committed_by_star=committed_by_star,
            active_orgs=active_orgs,
            targeted_players=targeted_players,
            total_points_invested=total_points,
            total_allocations=total_allocations,
            weekly_trend=weeks,
            commitment_pace=commitment_pace,
        )

    except SQLAlchemyError as e:
        log.exception("admin report summary error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("admin report summary error")
        return jsonify(error="server_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/admin/report/org-leaderboard
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/admin/report/org-leaderboard")
def admin_report_org_leaderboard():
    """
    Org-level recruiting leaderboard: points spent, commitments won,
    star quality, budget utilization per org.
    Query params: league_year_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # Get current week for utilization calc
            state = conn.execute(
                sa_text("""
                    SELECT current_week FROM recruiting_state
                    WHERE league_year_id = :ly
                """),
                {"ly": league_year_id},
            ).first()
            current_week = int(state[0]) if state else 0

            config_rows = conn.execute(
                sa_text("SELECT config_key, config_value FROM recruiting_config")
            ).all()
            config = {r[0]: r[1] for r in config_rows}
            weekly_budget = int(config.get("points_per_week", 100))
            max_possible = weekly_budget * max(current_week, 1)

            # Investment totals per org
            inv_rows = conn.execute(
                sa_text("""
                    SELECT ri.org_id, o.org_abbrev,
                           SUM(ri.points) AS total_points,
                           COUNT(DISTINCT ri.player_id) AS players_targeted,
                           COUNT(DISTINCT ri.week) AS weeks_active
                    FROM recruiting_investments ri
                    JOIN organizations o ON o.id = ri.org_id
                    WHERE ri.league_year_id = :ly
                    GROUP BY ri.org_id, o.org_abbrev
                    ORDER BY total_points DESC
                """),
                {"ly": league_year_id},
            ).all()

            # Commitment counts per org
            commit_rows = conn.execute(
                sa_text("""
                    SELECT org_id,
                           COUNT(*) AS total_commits,
                           SUM(CASE WHEN star_rating >= 4 THEN 1 ELSE 0 END) AS elite_commits,
                           AVG(star_rating) AS avg_star
                    FROM recruiting_commitments
                    WHERE league_year_id = :ly
                    GROUP BY org_id
                """),
                {"ly": league_year_id},
            ).all()
            commit_map = {
                int(r[0]): {
                    "commits": int(r[1]),
                    "elite_commits": int(r[2]),
                    "avg_star": round(float(r[3] or 0), 2),
                }
                for r in commit_rows
            }

            orgs = []
            for r in inv_rows:
                oid = int(r[0])
                total_pts = int(r[2])
                cm = commit_map.get(oid, {"commits": 0, "elite_commits": 0, "avg_star": 0})
                orgs.append({
                    "org_id": oid,
                    "org_abbrev": r[1],
                    "total_points": total_pts,
                    "players_targeted": int(r[3]),
                    "weeks_active": int(r[4]),
                    "budget_utilization_pct": round(total_pts / max_possible * 100, 1)
                        if max_possible else 0,
                    "commitments": cm["commits"],
                    "elite_commitments": cm["elite_commits"],
                    "avg_commit_star": cm["avg_star"],
                })

            # Add orgs with commitments but no investments (edge case)
            inv_org_ids = {o["org_id"] for o in orgs}
            for oid, cm in commit_map.items():
                if oid not in inv_org_ids:
                    abbrev_row = conn.execute(
                        sa_text("SELECT org_abbrev FROM organizations WHERE id = :oid"),
                        {"oid": oid},
                    ).first()
                    orgs.append({
                        "org_id": oid,
                        "org_abbrev": abbrev_row[0] if abbrev_row else f"ORG-{oid}",
                        "total_points": 0,
                        "players_targeted": 0,
                        "weeks_active": 0,
                        "budget_utilization_pct": 0,
                        "commitments": cm["commits"],
                        "elite_commitments": cm["elite_commits"],
                        "avg_commit_star": cm["avg_star"],
                    })

        return jsonify(
            current_week=current_week,
            max_possible_points=max_possible,
            orgs=orgs,
        )

    except SQLAlchemyError as e:
        log.exception("admin report org-leaderboard error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("admin report org-leaderboard error")
        return jsonify(error="server_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/admin/report/player-demand
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/admin/report/player-demand")
def admin_report_player_demand():
    """
    Most-recruited players: total interest, org count, star rating,
    commitment status. Sorted by total interest descending.
    Query params: league_year_id, limit (default 50), star_rating
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    limit = min(200, max(1, request.args.get("limit", 50, type=int)))
    star_filter = request.args.get("star_rating", type=int)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            star_where = ""
            params = {"ly": league_year_id, "lim": limit}
            if star_filter:
                star_where = "AND rr.star_rating = :star"
                params["star"] = star_filter

            rows = conn.execute(
                sa_text(f"""
                    SELECT ri.player_id,
                           p.firstname, p.lastname, p.ptype,
                           rr.star_rating, rr.rank_overall,
                           COUNT(DISTINCT ri.org_id) AS num_orgs,
                           SUM(ri.points) AS total_interest,
                           MAX(ri.week) AS last_active_week
                    FROM recruiting_investments ri
                    JOIN simbbPlayers p ON p.id = ri.player_id
                    LEFT JOIN recruiting_rankings rr
                        ON rr.player_id = ri.player_id
                        AND rr.league_year_id = ri.league_year_id
                    WHERE ri.league_year_id = :ly
                        {star_where}
                    GROUP BY ri.player_id, p.firstname, p.lastname, p.ptype,
                             rr.star_rating, rr.rank_overall
                    ORDER BY total_interest DESC
                    LIMIT :lim
                """),
                params,
            ).all()

            # Batch fetch commitment status
            pids = [int(r[0]) for r in rows]
            commit_map = {}
            if pids:
                ph = ", ".join([f":cp{i}" for i in range(len(pids))])
                cp = {"ly": league_year_id}
                cp.update({f"cp{i}": pid for i, pid in enumerate(pids)})
                cm_rows = conn.execute(
                    sa_text(f"""
                        SELECT rc.player_id, rc.org_id, o.org_abbrev, rc.week_committed
                        FROM recruiting_commitments rc
                        JOIN organizations o ON o.id = rc.org_id
                        WHERE rc.league_year_id = :ly
                          AND rc.player_id IN ({ph})
                    """),
                    cp,
                ).all()
                commit_map = {int(r[0]): {
                    "org_id": int(r[1]),
                    "org_abbrev": r[2],
                    "week": int(r[3]),
                } for r in cm_rows}

            players = []
            for r in rows:
                pid = int(r[0])
                entry = {
                    "player_id": pid,
                    "player_name": f"{r[1]} {r[2]}",
                    "ptype": r[3],
                    "star_rating": int(r[4]) if r[4] else None,
                    "rank_overall": int(r[5]) if r[5] else None,
                    "num_orgs": int(r[6]),
                    "total_interest": int(r[7]),
                    "last_active_week": int(r[8]),
                    "status": "committed" if pid in commit_map else "uncommitted",
                    "committed_to": commit_map.get(pid),
                }
                players.append(entry)

        return jsonify(players=players, total=len(players))

    except SQLAlchemyError as e:
        log.exception("admin report player-demand error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("admin report player-demand error")
        return jsonify(error="server_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# GET /recruiting/admin/report/org-detail/<org_id>
# ---------------------------------------------------------------------------
@recruiting_bp.get("/recruiting/admin/report/org-detail/<int:org_id>")
def admin_report_org_detail(org_id: int):
    """
    Detailed recruiting activity for a single org: per-week spend,
    per-player investments, commitments won/lost.
    Query params: league_year_id
    """
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify(error="missing_param",
                       message="league_year_id required"), 400

    engine = get_engine()
    try:
        with engine.connect() as conn:
            # Org info
            org_row = conn.execute(
                sa_text("SELECT org_abbrev FROM organizations WHERE id = :oid"),
                {"oid": org_id},
            ).first()
            org_abbrev = org_row[0] if org_row else f"ORG-{org_id}"

            # Per-week spend
            weekly = conn.execute(
                sa_text("""
                    SELECT week, SUM(points) AS spent,
                           COUNT(DISTINCT player_id) AS players
                    FROM recruiting_investments
                    WHERE org_id = :org AND league_year_id = :ly
                    GROUP BY week
                    ORDER BY week
                """),
                {"org": org_id, "ly": league_year_id},
            ).all()
            weekly_spend = [
                {"week": int(r[0]), "points_spent": int(r[1]),
                 "players_targeted": int(r[2])}
                for r in weekly
            ]

            # Per-player cumulative
            player_rows = conn.execute(
                sa_text("""
                    SELECT ri.player_id,
                           p.firstname, p.lastname, p.ptype,
                           rr.star_rating,
                           SUM(ri.points) AS total_invested
                    FROM recruiting_investments ri
                    JOIN simbbPlayers p ON p.id = ri.player_id
                    LEFT JOIN recruiting_rankings rr
                        ON rr.player_id = ri.player_id
                        AND rr.league_year_id = ri.league_year_id
                    WHERE ri.org_id = :org AND ri.league_year_id = :ly
                    GROUP BY ri.player_id, p.firstname, p.lastname, p.ptype,
                             rr.star_rating
                    ORDER BY total_invested DESC
                """),
                {"org": org_id, "ly": league_year_id},
            ).all()

            # Commitments won by this org
            won = conn.execute(
                sa_text("""
                    SELECT rc.player_id, p.firstname, p.lastname,
                           rc.star_rating, rc.week_committed, rc.points_total
                    FROM recruiting_commitments rc
                    JOIN simbbPlayers p ON p.id = rc.player_id
                    WHERE rc.org_id = :org AND rc.league_year_id = :ly
                    ORDER BY rc.star_rating DESC
                """),
                {"org": org_id, "ly": league_year_id},
            ).all()
            commitments_won = [
                {"player_id": int(r[0]),
                 "player_name": f"{r[1]} {r[2]}",
                 "star_rating": int(r[3]),
                 "week_committed": int(r[4]),
                 "points_total": int(r[5])}
                for r in won
            ]

            # Build invested_players with outcome tracking
            won_pids = {int(r[0]) for r in won}
            invested_players = []
            for r in player_rows:
                pid = int(r[0])
                invested_players.append({
                    "player_id": pid,
                    "player_name": f"{r[1]} {r[2]}",
                    "ptype": r[3],
                    "star_rating": int(r[4]) if r[4] else None,
                    "total_invested": int(r[5]),
                    "outcome": "won" if pid in won_pids else "active",
                })

            # Check which invested players committed elsewhere
            invested_pids = [p["player_id"] for p in invested_players
                             if p["outcome"] == "active"]
            if invested_pids:
                ph = ", ".join([f":ip{i}" for i in range(len(invested_pids))])
                ip_params = {"ly": league_year_id}
                ip_params.update({f"ip{i}": pid for i, pid in enumerate(invested_pids)})
                lost_rows = conn.execute(
                    sa_text(f"""
                        SELECT rc.player_id, rc.org_id, o.org_abbrev
                        FROM recruiting_commitments rc
                        JOIN organizations o ON o.id = rc.org_id
                        WHERE rc.league_year_id = :ly
                          AND rc.player_id IN ({ph})
                    """),
                    ip_params,
                ).all()
                lost_map = {int(r[0]): r[2] for r in lost_rows}
                for p in invested_players:
                    if p["player_id"] in lost_map:
                        p["outcome"] = "lost"
                        p["committed_to"] = lost_map[p["player_id"]]

        total_invested = sum(p["total_invested"] for p in invested_players)

        return jsonify(
            org_id=org_id,
            org_abbrev=org_abbrev,
            total_invested=total_invested,
            weekly_spend=weekly_spend,
            invested_players=invested_players,
            commitments_won=commitments_won,
        )

    except SQLAlchemyError as e:
        log.exception("admin report org-detail error")
        return jsonify(error="database_error", message=str(e)), 500
    except Exception as e:
        log.exception("admin report org-detail error")
        return jsonify(error="server_error", message=str(e)), 500
