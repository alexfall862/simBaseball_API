# draft/__init__.py
"""
Draft system blueprint — pick selection, signing, trading, admin controls.
All public endpoints under /draft/, admin endpoints under /draft/admin/.
"""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request, session
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.draft import (
    initialize_draft,
    start_draft,
    pause_draft,
    resume_draft,
    advance_to_signing,
    complete_draft,
    make_pick,
    auto_pick,
    check_timer_expiry,
    sign_pick,
    pass_on_pick,
    trade_draft_pick,
    get_draft_state,
    get_draft_board,
    get_eligible_players,
    get_org_picks,
    admin_set_pick,
    admin_remove_pick,
    admin_reset_timer,
    export_draft,
    set_round_modes,
    get_round_modes,
    set_team_prefs,
    get_team_prefs,
    execute_auto_rounds,
)

draft_bp = Blueprint("draft", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_serial(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _require_json(*keys):
    body = request.get_json(silent=True) or {}
    missing = [k for k in keys if k not in body]
    if missing:
        return None, (jsonify(error="missing_fields", fields=missing), 400)
    return body, None


def _require_admin():
    if session.get("admin") is True:
        return None
    return jsonify(error="unauthorized"), 401


def _lyid_from(body=None):
    """Get league_year_id from body or query params."""
    if body and "league_year_id" in body:
        return int(body["league_year_id"])
    return request.args.get("league_year_id", type=int)


def _check_expiry_if_active(conn, lyid):
    """Lazy timer enforcement — auto-pick expired picks before processing."""
    try:
        check_timer_expiry(conn, lyid)
    except (ValueError, SQLAlchemyError):
        pass


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------

@draft_bp.get("/draft/state")
def api_draft_state():
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            _check_expiry_if_active(conn, lyid)
            result = get_draft_state(conn, lyid)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.get("/draft/board")
def api_draft_board():
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            _check_expiry_if_active(conn, lyid)
            result = get_draft_board(conn, lyid)
        return jsonify(picks=result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.get("/draft/eligible")
def api_draft_eligible():
    lyid = request.args.get("league_year_id", type=int)
    viewing_org_id = request.args.get("viewing_org_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    if not viewing_org_id:
        return jsonify(error="missing_param",
                       message="viewing_org_id query param is required"), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = get_eligible_players(
                conn, lyid,
                source=request.args.get("source"),
                search=request.args.get("search"),
                available_only=request.args.get("available_only", "true").lower() != "false",
                limit=request.args.get("limit", 100, type=int),
                offset=request.args.get("offset", 0, type=int),
                viewing_org_id=viewing_org_id,
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.get("/draft/picks/<int:org_id>")
def api_org_picks(org_id):
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = get_org_picks(conn, org_id, lyid)
        return jsonify(picks=result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/pick")
def api_make_pick():
    body, err = _require_json("org_id", "player_id", "league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            _check_expiry_if_active(conn, int(body["league_year_id"]))
            result = make_pick(
                conn,
                league_year_id=int(body["league_year_id"]),
                org_id=int(body["org_id"]),
                player_id=int(body["player_id"]),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/sign/<int:pick_id>")
def api_sign_pick(pick_id):
    body = request.get_json(silent=True) or {}
    lyid = _lyid_from(body)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = sign_pick(conn, pick_id, lyid,
                               executed_by=body.get("executed_by"))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/pass/<int:pick_id>")
def api_pass_pick(pick_id):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = pass_on_pick(conn, pick_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/trade")
def api_draft_trade():
    body, err = _require_json("league_year_id", "pick_id", "from_org_id", "to_org_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = trade_draft_pick(
                conn,
                league_year_id=int(body["league_year_id"]),
                pick_id=int(body["pick_id"]),
                from_org_id=int(body["from_org_id"]),
                to_org_id=int(body["to_org_id"]),
                trade_proposal_id=body.get("trade_proposal_id"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# ---------------------------------------------------------------------------
# Admin Endpoints
# ---------------------------------------------------------------------------

@draft_bp.post("/draft/admin/initialize")
def api_admin_init_draft():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            live_rounds = body.get("live_rounds")
            if live_rounds is not None:
                live_rounds = [int(r) for r in live_rounds]
            result = initialize_draft(
                conn,
                league_year_id=int(body["league_year_id"]),
                total_rounds=int(body.get("total_rounds", 20)),
                seconds_per_pick=int(body.get("seconds_per_pick", 60)),
                is_snake=bool(body.get("is_snake", False)),
                live_rounds=live_rounds,
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/start")
def api_admin_start():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = start_draft(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/pause")
def api_admin_pause():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = pause_draft(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/resume")
def api_admin_resume():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = resume_draft(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/reset-timer")
def api_admin_reset_timer():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = admin_reset_timer(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/set-pick")
def api_admin_set_pick():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id", "round", "pick_in_round", "player_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = admin_set_pick(
                conn,
                league_year_id=int(body["league_year_id"]),
                round_num=int(body["round"]),
                pick_in_round=int(body["pick_in_round"]),
                player_id=int(body["player_id"]),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/remove-pick")
def api_admin_remove_pick():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("draft_pick_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = admin_remove_pick(conn, int(body["draft_pick_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/advance-signing")
def api_admin_advance_signing():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = advance_to_signing(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/export")
def api_admin_export():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = export_draft(
                conn, int(body["league_year_id"]),
                executed_by=body.get("executed_by"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/complete")
def api_admin_complete():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = complete_draft(conn, int(body["league_year_id"]))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


# ---------------------------------------------------------------------------
# Round Mode & Auto-Draft Preference Endpoints
# ---------------------------------------------------------------------------

@draft_bp.get("/draft/round-modes")
def api_round_modes():
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = get_round_modes(conn, lyid)
        return jsonify(rounds=result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/round-modes")
def api_admin_round_modes():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id", "round_modes")
    if err:
        return err
    try:
        modes = {int(k): v for k, v in body["round_modes"].items()}
        engine = get_engine()
        with engine.begin() as conn:
            result = set_round_modes(conn, int(body["league_year_id"]), modes)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.get("/draft/prefs/<int:org_id>")
def api_get_team_prefs(org_id):
    lyid = request.args.get("league_year_id", type=int)
    if not lyid:
        return jsonify(error="missing_fields", fields=["league_year_id"]), 400
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = get_team_prefs(conn, lyid, org_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/prefs")
def api_set_team_prefs():
    body, err = _require_json("league_year_id", "org_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = set_team_prefs(
                conn,
                league_year_id=int(body["league_year_id"]),
                org_id=int(body["org_id"]),
                pitcher_quota=body.get("pitcher_quota"),
                hitter_quota=body.get("hitter_quota"),
                queue=body.get("queue"),
            )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500


@draft_bp.post("/draft/admin/run-auto-rounds")
def api_admin_run_auto_rounds():
    guard = _require_admin()
    if guard:
        return guard
    body, err = _require_json("league_year_id")
    if err:
        return err
    try:
        engine = get_engine()
        with engine.begin() as conn:
            results = execute_auto_rounds(conn, int(body["league_year_id"]))
        return jsonify(picks_made=len(results), picks=results), 200
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except SQLAlchemyError:
        return jsonify(error="db_error", message="Database error"), 500
