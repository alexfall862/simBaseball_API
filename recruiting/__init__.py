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

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text as sa_text

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
        return jsonify(error="database_error", message=str(e)), 500


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
                           o.abbreviation AS org_abbrev
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
