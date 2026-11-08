"""
Training camp blueprint: an org picks one focus skill and an intensity per
player for the season about to be played; the preseason camp step
(POST /admin/training-camp/apply) applies it before opening day.

GET    /training-camp/options
GET    /training-camp/focus?org_id=&league_year_id=
PUT    /training-camp/focus      {org_id, league_year_id?, player_id, attr, intensity, set_by?}
                                 or {org_id, league_year_id?, items: [{player_id, attr, intensity}, ...]}
DELETE /training-camp/focus      {org_id, league_year_id?, player_id}
GET    /training-camp/results?org_id=&league_year_id=
"""
import logging

from flask import Blueprint, jsonify, request

from db import get_engine
from services import training_camp as tc
from services.league_config import get_league_config

training_camp_bp = Blueprint("training_camp", __name__)
log = logging.getLogger("app")


def _ly(conn, value):
    if value:
        return int(value)
    ly = tc.current_league_year_id(conn)
    if not ly:
        raise ValueError("league_year_id is required (no current season)")
    return ly


@training_camp_bp.get("/training-camp/options")
def camp_options():
    engine = get_engine()
    with engine.connect() as conn:
        cfg = get_league_config(conn)
    return jsonify(tc.options(cfg))


@training_camp_bp.get("/training-camp/focus")
def camp_focus_list():
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify(error="validation", message="org_id is required"), 400
    engine = get_engine()
    try:
        with engine.connect() as conn:
            ly = _ly(conn, request.args.get("league_year_id"))
            return jsonify(tc.list_focus(conn, org_id, ly))
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400


@training_camp_bp.put("/training-camp/focus")
def camp_focus_set():
    body = request.get_json(silent=True) or {}
    org_id = body.get("org_id")
    if not org_id:
        return jsonify(error="validation", message="org_id is required"), 400
    items = body.get("items")
    if items is None:
        items = [{"player_id": body.get("player_id"), "attr": body.get("attr"),
                  "intensity": body.get("intensity", "regular")}]
    engine = get_engine()
    try:
        with engine.begin() as conn:
            ly = _ly(conn, body.get("league_year_id"))
            out = []
            for it in items:
                if not it.get("player_id") or not it.get("attr"):
                    raise ValueError("each item needs player_id and attr")
                out.append(tc.set_focus(conn, int(org_id), ly, int(it["player_id"]),
                                        str(it["attr"]), str(it.get("intensity") or "regular"),
                                        body.get("set_by")))
        return jsonify(success=True, league_year_id=ly, set=out)
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
    except Exception as e:
        log.exception("training camp set_focus failed")
        return jsonify(error="server_error", message=str(e)), 500


@training_camp_bp.delete("/training-camp/focus")
def camp_focus_clear():
    body = request.get_json(silent=True) or {}
    org_id, pid = body.get("org_id"), body.get("player_id")
    if not org_id or not pid:
        return jsonify(error="validation", message="org_id and player_id are required"), 400
    engine = get_engine()
    try:
        with engine.begin() as conn:
            ly = _ly(conn, body.get("league_year_id"))
            removed = tc.clear_focus(conn, int(org_id), ly, int(pid))
        return jsonify(success=True, removed=removed, league_year_id=ly)
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400


@training_camp_bp.get("/training-camp/results")
def camp_results():
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify(error="validation", message="org_id is required"), 400
    engine = get_engine()
    try:
        with engine.connect() as conn:
            ly = _ly(conn, request.args.get("league_year_id"))
            return jsonify(league_year_id=ly, results=tc.org_results(conn, org_id, ly))
    except ValueError as e:
        return jsonify(error="validation", message=str(e)), 400
