# fa_auction/__init__.py
"""
FA Auction blueprint — endpoints for the 3-phase free agency auction,
player demands, and market summary.
"""

import json
from decimal import Decimal

from flask import Blueprint, jsonify, request

from db import get_engine

fa_auction_bp = Blueprint("fa_auction", __name__)


# ── Auction board ───────────────────────────────────────────────────

@fa_auction_bp.route("/fa-auction/board", methods=["GET"])
def auction_board():
    """GET /fa-auction/board?league_year_id=X&org_id=Y"""
    league_year_id = request.args.get("league_year_id", type=int)
    viewer_org_id = request.args.get("org_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.fa_auction import get_auction_board
    with engine.connect() as conn:
        board = get_auction_board(conn, league_year_id, viewer_org_id)
    return jsonify(board)


@fa_auction_bp.route("/fa-auction/<int:auction_id>", methods=["GET"])
def auction_detail(auction_id):
    """GET /fa-auction/<id>?org_id=Y"""
    viewer_org_id = request.args.get("org_id", type=int)

    engine = get_engine()
    from services.fa_auction import get_auction_detail
    with engine.connect() as conn:
        detail = get_auction_detail(conn, auction_id, viewer_org_id)
    if not detail:
        return jsonify({"error": "Auction not found"}), 404
    return jsonify(detail)


# ── Submit offer ────────────────────────────────────────────────────

@fa_auction_bp.route("/fa-auction/<int:auction_id>/offer", methods=["POST"])
def submit_offer_endpoint(auction_id):
    """POST /fa-auction/<id>/offer"""
    data = request.get_json(force=True)
    required = ["org_id", "years", "salaries", "bonus", "level_id",
                "league_year_id", "game_week_id"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    engine = get_engine()
    from services.fa_auction import submit_offer

    try:
        with engine.begin() as conn:
            result = submit_offer(
                conn,
                auction_id=auction_id,
                org_id=data["org_id"],
                years=data["years"],
                salaries=[Decimal(str(s)) for s in data["salaries"]],
                bonus=Decimal(str(data["bonus"])),
                level_id=data["level_id"],
                league_year_id=data["league_year_id"],
                game_week_id=data["game_week_id"],
                current_week=data.get("current_week", 0),
                executed_by=data.get("executed_by", "user"),
            )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Withdraw offer ──────────────────────────────────────────────────

@fa_auction_bp.route(
    "/fa-auction/<int:auction_id>/offer/<int:org_id>", methods=["DELETE"]
)
def withdraw_offer_endpoint(auction_id, org_id):
    """DELETE /fa-auction/<id>/offer/<org_id>"""
    engine = get_engine()
    from services.fa_auction import withdraw_offer

    try:
        with engine.begin() as conn:
            result = withdraw_offer(conn, auction_id, org_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Market summary ──────────────────────────────────────────────────

@fa_auction_bp.route("/fa-auction/market-summary", methods=["GET"])
def market_summary():
    """GET /fa-auction/market-summary?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.market_pricing import get_market_summary
    with engine.connect() as conn:
        summary = get_market_summary(conn, league_year_id)
    return jsonify(summary)


# ── Admin: manual phase advance ─────────────────────────────────────

@fa_auction_bp.route("/fa-auction/advance-phases", methods=["POST"])
def advance_phases_endpoint():
    """POST /fa-auction/advance-phases  (admin manual trigger)"""
    data = request.get_json(force=True)
    current_week = data.get("current_week", 0)
    league_year_id = data.get("league_year_id")
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.fa_auction import advance_auction_phases
    with engine.begin() as conn:
        result = advance_auction_phases(conn, current_week, league_year_id)
    return jsonify(result)


# ── Player demands ──────────────────────────────────────────────────

@fa_auction_bp.route("/fa-auction/player-demand/<int:player_id>", methods=["GET"])
def player_demand(player_id):
    """GET /fa-auction/player-demand/<id>?league_year_id=X&type=fa|extension|buyout"""
    league_year_id = request.args.get("league_year_id", type=int)
    demand_type = request.args.get("type", "fa")
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400
    if demand_type not in ("fa", "extension", "buyout"):
        return jsonify({"error": "type must be fa, extension, or buyout"}), 400

    engine = get_engine()
    from services.player_demands import get_player_demand
    with engine.connect() as conn:
        demand = get_player_demand(conn, player_id, league_year_id, demand_type)
    if not demand:
        return jsonify({"error": "No demand computed for this player"}), 404
    return jsonify(demand)


@fa_auction_bp.route("/fa-auction/compute-demands", methods=["POST"])
def compute_demands():
    """POST /fa-auction/compute-demands  {player_id, league_year_id, demand_type, ?contract_id}"""
    data = request.get_json(force=True)
    player_id = data.get("player_id")
    league_year_id = data.get("league_year_id")
    demand_type = data.get("demand_type", "fa")

    if not player_id or not league_year_id:
        return jsonify({"error": "player_id and league_year_id required"}), 400

    engine = get_engine()
    from services.player_demands import (
        compute_fa_demand, compute_extension_demand, compute_buyout_demand,
    )

    try:
        with engine.begin() as conn:
            if demand_type == "fa":
                result = compute_fa_demand(conn, player_id, league_year_id)
            elif demand_type == "extension":
                contract_id = data.get("contract_id")
                if not contract_id:
                    return jsonify({"error": "contract_id required for extension"}), 400
                result = compute_extension_demand(
                    conn, player_id, contract_id, league_year_id,
                )
            elif demand_type == "buyout":
                contract_id = data.get("contract_id")
                if not contract_id:
                    return jsonify({"error": "contract_id required for buyout"}), 400
                result = compute_buyout_demand(
                    conn, player_id, contract_id, league_year_id,
                )
            else:
                return jsonify({"error": "demand_type must be fa, extension, or buyout"}), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@fa_auction_bp.route("/fa-auction/market-rate", methods=["GET"])
def market_rate():
    """GET /fa-auction/market-rate?league_year_id=X"""
    league_year_id = request.args.get("league_year_id", type=int)
    if not league_year_id:
        return jsonify({"error": "league_year_id required"}), 400

    engine = get_engine()
    from services.market_pricing import get_current_dollar_per_war
    with engine.connect() as conn:
        dpw = get_current_dollar_per_war(conn, league_year_id)
    return jsonify({"dollar_per_war": str(dpw)})
