# ifa_signing/__init__.py
"""
IFA Signing Period blueprint — endpoints for the international free agent
signing window, per-player auctions, and bonus pool management.
"""

from decimal import Decimal

from flask import Blueprint, jsonify, request

from db import get_engine

ifa_signing_bp = Blueprint("ifa_signing", __name__)


# ── IFA state ─────────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/state", methods=["GET"])
def ifa_state():
    """GET /ifa/state?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import get_ifa_state
    with engine.connect() as conn:
        state = get_ifa_state(conn, league_year_id)
    return jsonify(state)


# ── IFA board ─────────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/board", methods=["GET"])
def ifa_board():
    """GET /ifa/board?league_year_id=X&org_id=Y"""
    league_year_id = request.args.get("league_year_id", type=int)
    viewer_org_id = request.args.get("org_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import get_ifa_board
    with engine.connect() as conn:
        board = get_ifa_board(conn, league_year_id, viewer_org_id)
    return jsonify(board)


# ── Pool status ───────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/pool/<int:org_id>", methods=["GET"])
def ifa_pool(org_id):
    """GET /ifa/pool/<org_id>?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import get_ifa_pool_status
    with engine.connect() as conn:
        pool = get_ifa_pool_status(conn, league_year_id, org_id)
    if not pool:
        return jsonify({"error": "Pool not found for this org/year"}), 404
    return jsonify(pool)


# ── Org's offers ──────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/offers/<int:org_id>", methods=["GET"])
def ifa_offers(org_id):
    """GET /ifa/offers/<org_id>?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import get_org_ifa_offers
    with engine.connect() as conn:
        offers = get_org_ifa_offers(conn, league_year_id, org_id)
    return jsonify(offers)


# ── Auction detail ────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/auction/<int:auction_id>", methods=["GET"])
def ifa_auction_detail(auction_id):
    """GET /ifa/auction/<id>?org_id=Y"""
    viewer_org_id = request.args.get("org_id", type=int)

    engine = get_engine()
    from services.ifa_signing import get_ifa_auction_detail
    with engine.connect() as conn:
        detail = get_ifa_auction_detail(conn, auction_id, viewer_org_id)
    if not detail:
        return jsonify({"error": "Auction not found"}), 404
    return jsonify(detail)


# ── Eligible players ──────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/eligible", methods=["GET"])
def ifa_eligible():
    """GET /ifa/eligible?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import get_ifa_eligible_players
    with engine.connect() as conn:
        players = get_ifa_eligible_players(conn, league_year_id)
    return jsonify(players)


# ── Start auction ─────────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/auction/start", methods=["POST"])
def ifa_start_auction():
    """POST /ifa/auction/start {player_id, league_year_id}"""
    data = request.get_json(force=True)
    for field in ("player_id", "league_year_id"):
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    engine = get_engine()
    from services.ifa_signing import start_ifa_auction, get_ifa_state

    try:
        with engine.begin() as conn:
            state = get_ifa_state(conn, data["league_year_id"])
            result = start_ifa_auction(
                conn,
                player_id=data["player_id"],
                league_year_id=data["league_year_id"],
                current_week=state.get("current_week", 1),
                org_id=data.get("org_id"),
            )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Submit/update offer ──────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/auction/<int:auction_id>/offer", methods=["POST"])
def ifa_submit_offer(auction_id):
    """POST /ifa/auction/<id>/offer {org_id, bonus, league_year_id}"""
    data = request.get_json(force=True)
    for field in ("org_id", "bonus", "league_year_id"):
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    engine = get_engine()
    from services.ifa_signing import submit_ifa_offer, get_ifa_state

    try:
        with engine.begin() as conn:
            state = get_ifa_state(conn, data["league_year_id"])
            result = submit_ifa_offer(
                conn,
                auction_id=auction_id,
                org_id=data["org_id"],
                bonus=Decimal(str(data["bonus"])),
                league_year_id=data["league_year_id"],
                current_week=state.get("current_week", 1),
                executed_by=data.get("executed_by", "user"),
            )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Withdraw offer ───────────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/auction/<int:auction_id>/offer/<int:org_id>", methods=["DELETE"])
def ifa_withdraw_offer(auction_id, org_id):
    """DELETE /ifa/auction/<id>/offer/<org_id>"""
    engine = get_engine()
    from services.ifa_signing import withdraw_ifa_offer

    try:
        with engine.begin() as conn:
            result = withdraw_ifa_offer(conn, auction_id, org_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Advance week (admin) ─────────────────────────────────────────────

@ifa_signing_bp.route("/ifa/advance-week", methods=["POST"])
def ifa_advance_week():
    """POST /ifa/advance-week {league_year_id}"""
    data = request.get_json(force=True)
    league_year_id = data.get("league_year_id")
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.ifa_signing import advance_ifa_week

    try:
        with engine.begin() as conn:
            result = advance_ifa_week(conn, league_year_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
