# transactions/__init__.py
"""
Transaction system blueprint — trades, roster moves, signings, extensions.
All endpoints under /transactions/.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.transactions import (
    promote_player,
    demote_player,
    place_on_ir,
    activate_from_ir,
    release_player,
    buyout_player,
    get_free_agents,
    sign_free_agent,
    extend_contract,
    execute_trade,
    create_trade_proposal,
    get_trade_proposals,
    get_trade_proposal,
    accept_trade_proposal,
    reject_trade_proposal,
    cancel_trade_proposal,
    admin_reject_trade,
    admin_approve_trade,
    get_transaction_log,
    get_org_roster,
    get_roster_status,
    rollback_transaction,
    _get_signing_budget,
)

transactions_bp = Blueprint("transactions", __name__)


def _json_serial(obj):
    """JSON serializer for objects not handled by default."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _require_json(*keys):
    """Extract required keys from JSON body, raise 400 if missing."""
    body = request.get_json(silent=True) or {}
    missing = [k for k in keys if k not in body]
    if missing:
        return None, (
            jsonify(error="missing_fields", fields=missing),
            400,
        )
    return body, None


def _league_year_id_from_body(body):
    """Get league_year_id from body, with fallback to query param."""
    return body.get("league_year_id") or request.args.get("league_year_id", type=int)


# -----------------------------------------------------------------------
# Core Roster Moves
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/promote")
def api_promote():
    body, err = _require_json("contract_id", "target_level_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = promote_player(
                conn,
                contract_id=int(body["contract_id"]),
                target_level_id=int(body["target_level_id"]),
                league_year_id=int(lyid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.post("/transactions/demote")
def api_demote():
    body, err = _require_json("contract_id", "target_level_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = demote_player(
                conn,
                contract_id=int(body["contract_id"]),
                target_level_id=int(body["target_level_id"]),
                league_year_id=int(lyid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.post("/transactions/ir/place")
def api_ir_place():
    body, err = _require_json("contract_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = place_on_ir(
                conn,
                contract_id=int(body["contract_id"]),
                league_year_id=int(lyid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.post("/transactions/ir/activate")
def api_ir_activate():
    body, err = _require_json("contract_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = activate_from_ir(
                conn,
                contract_id=int(body["contract_id"]),
                league_year_id=int(lyid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Release & Buyout
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/release")
def api_release():
    body, err = _require_json("contract_id", "org_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = release_player(
                conn,
                contract_id=int(body["contract_id"]),
                org_id=int(body["org_id"]),
                league_year_id=int(lyid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.post("/transactions/buyout")
def api_buyout():
    body, err = _require_json("contract_id", "org_id", "buyout_amount")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    gwid = body.get("game_week_id") or request.args.get("game_week_id", type=int)
    if not lyid or not gwid:
        return jsonify(error="missing_fields", fields=["league_year_id", "game_week_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = buyout_player(
                conn,
                contract_id=int(body["contract_id"]),
                org_id=int(body["org_id"]),
                buyout_amount=Decimal(str(body["buyout_amount"])),
                league_year_id=int(lyid),
                game_week_id=int(gwid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except (ValueError, InvalidOperation) as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Free Agents & Signing
# -----------------------------------------------------------------------

@transactions_bp.get("/transactions/free-agents")
def api_free_agents():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            agents = get_free_agents(conn)
        return jsonify(agents), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.get("/transactions/signing-budget/<int:org_id>")
def api_signing_budget(org_id: int):
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.connect() as conn:
            budget = _get_signing_budget(conn, org_id, lyid)
        return jsonify({"org_id": org_id, "available_budget": float(budget)}), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.post("/transactions/sign")
def api_sign():
    body, err = _require_json("player_id", "org_id", "years", "salaries", "bonus")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    gwid = body.get("game_week_id") or request.args.get("game_week_id", type=int)
    level_id = body.get("level_id")
    if not lyid or not gwid or not level_id:
        return jsonify(error="missing_fields",
                       fields=["league_year_id", "game_week_id", "level_id"]), 400
    try:
        salaries = [Decimal(str(s)) for s in body["salaries"]]
        engine = get_engine()
        with engine.begin() as conn:
            result = sign_free_agent(
                conn,
                player_id=int(body["player_id"]),
                org_id=int(body["org_id"]),
                years=int(body["years"]),
                salaries=salaries,
                bonus=Decimal(str(body["bonus"])),
                level_id=int(level_id),
                league_year_id=int(lyid),
                game_week_id=int(gwid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except (ValueError, InvalidOperation) as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Contract Extension
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/extend")
def api_extend():
    body, err = _require_json("contract_id", "org_id", "years", "salaries", "bonus")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    gwid = body.get("game_week_id") or request.args.get("game_week_id", type=int)
    if not lyid or not gwid:
        return jsonify(error="missing_fields",
                       fields=["league_year_id", "game_week_id"]), 400
    try:
        salaries = [Decimal(str(s)) for s in body["salaries"]]
        engine = get_engine()
        with engine.begin() as conn:
            result = extend_contract(
                conn,
                contract_id=int(body["contract_id"]),
                org_id=int(body["org_id"]),
                years=int(body["years"]),
                salaries=salaries,
                bonus=Decimal(str(body["bonus"])),
                league_year_id=int(lyid),
                game_week_id=int(gwid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except (ValueError, InvalidOperation) as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Trade — Admin Direct Execute
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/trade/execute")
def api_trade_execute():
    body, err = _require_json("org_a_id", "org_b_id")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    gwid = body.get("game_week_id") or request.args.get("game_week_id", type=int)
    if not lyid or not gwid:
        return jsonify(error="missing_fields",
                       fields=["league_year_id", "game_week_id"]), 400
    try:
        trade_details = {
            "org_a_id": int(body["org_a_id"]),
            "org_b_id": int(body["org_b_id"]),
            "players_to_b": body.get("players_to_b", []),
            "players_to_a": body.get("players_to_a", []),
            "salary_retention": body.get("salary_retention", {}),
            "cash_a_to_b": body.get("cash_a_to_b", 0),
        }
        engine = get_engine()
        with engine.begin() as conn:
            result = execute_trade(
                conn, trade_details,
                league_year_id=int(lyid),
                game_week_id=int(gwid),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Trade — Proposal Workflow
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/trade/propose")
def api_trade_propose():
    body, err = _require_json("proposing_org_id", "receiving_org_id", "proposal")
    if err:
        return err
    lyid = _league_year_id_from_body(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = create_trade_proposal(
                conn,
                proposing_org_id=int(body["proposing_org_id"]),
                receiving_org_id=int(body["receiving_org_id"]),
                league_year_id=int(lyid),
                proposal=body["proposal"],
            )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.get("/transactions/trade/proposals")
def api_trade_proposals_list():
    org_id = request.args.get("org_id", type=int)
    status = request.args.get("status")
    try:
        engine = get_engine()
        with engine.connect() as conn:
            proposals = get_trade_proposals(conn, org_id=org_id, status=status)
        return jsonify(proposals), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.get("/transactions/trade/proposals/<int:proposal_id>")
def api_trade_proposal_detail(proposal_id: int):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            proposal = get_trade_proposal(conn, proposal_id)
        return jsonify(proposal), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.put("/transactions/trade/proposals/<int:proposal_id>/accept")
def api_trade_accept(proposal_id: int):
    body = request.get_json(silent=True) or {}
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = accept_trade_proposal(conn, proposal_id, note=body.get("note"))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.put("/transactions/trade/proposals/<int:proposal_id>/reject")
def api_trade_reject(proposal_id: int):
    body = request.get_json(silent=True) or {}
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = reject_trade_proposal(conn, proposal_id, note=body.get("note"))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.put("/transactions/trade/proposals/<int:proposal_id>/admin-approve")
def api_trade_admin_approve(proposal_id: int):
    body = request.get_json(silent=True) or {}
    lyid = _league_year_id_from_body(body)
    gwid = body.get("game_week_id") or request.args.get("game_week_id", type=int)
    if not lyid or not gwid:
        return jsonify(error="missing_fields",
                       fields=["league_year_id", "game_week_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = admin_approve_trade(
                conn, proposal_id,
                league_year_id=int(lyid),
                game_week_id=int(gwid),
                note=body.get("note"),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.put("/transactions/trade/proposals/<int:proposal_id>/admin-reject")
def api_trade_admin_reject(proposal_id: int):
    body = request.get_json(silent=True) or {}
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = admin_reject_trade(conn, proposal_id, note=body.get("note"))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.put("/transactions/trade/proposals/<int:proposal_id>/cancel")
def api_trade_cancel(proposal_id: int):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = cancel_trade_proposal(conn, proposal_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Transaction Log & Roster Status
# -----------------------------------------------------------------------

@transactions_bp.get("/transactions/log")
def api_transaction_log():
    org_id = request.args.get("org_id", type=int)
    tx_type = request.args.get("type")
    lyid = request.args.get("league_year_id", type=int)
    limit = request.args.get("limit", 100, type=int)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            log = get_transaction_log(
                conn, org_id=org_id, transaction_type=tx_type,
                league_year_id=lyid, limit=limit,
            )
        return jsonify(log), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.get("/transactions/roster/<int:org_id>")
def api_org_roster(org_id: int):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            roster = get_org_roster(conn, org_id)
        return jsonify(roster), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@transactions_bp.get("/transactions/roster-status/<int:org_id>")
def api_roster_status(org_id: int):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            status = get_roster_status(conn, org_id)
        return jsonify(status), 200
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# -----------------------------------------------------------------------
# Rollback
# -----------------------------------------------------------------------

@transactions_bp.post("/transactions/rollback")
def api_rollback():
    body, err = _require_json("transaction_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = rollback_transaction(
                conn,
                transaction_id=int(body["transaction_id"]),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500
