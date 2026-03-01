# gameplanning/__init__.py
import json
import logging
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select, and_, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

gameplanning_bp = Blueprint("gameplanning", __name__)
log = logging.getLogger("app")


# ---------------------------------------------------------------------------
# Table reflection (cached on blueprint)
# ---------------------------------------------------------------------------
def _reflect_table(name: str):
    cache_key = f"_{name}"
    if not hasattr(gameplanning_bp, cache_key):
        engine = get_engine()
        md = MetaData()
        tbl = Table(name, md, autoload_with=engine)
        setattr(gameplanning_bp, cache_key, tbl)
    return getattr(gameplanning_bp, cache_key)


def _row_to_dict(row):
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# Defaults (match game_payload.py DEFAULT_PLAYER_STRATEGY)
# ---------------------------------------------------------------------------
DEFAULT_PLAYER_STRATEGY = {
    "plate_approach": "normal",
    "pitching_approach": "normal",
    "baserunning_approach": "normal",
    "usage_preference": "normal",
    "stealfreq": 1.87,
    "pickofffreq": 1.0,
    "pitchchoices": [1, 1, 1, 1, 1],
    "pitchpull": None,
    "pulltend": None,
}

DEFAULT_TEAM_STRATEGY = {
    "outfield_spacing": "normal",
    "infield_spacing": "normal",
    "bullpen_cutoff": 100,
    "bullpen_priority": "rest",
    "emergency_pitcher_id": None,
    "intentional_walk_list": [],
}

# ---------------------------------------------------------------------------
# Valid ENUM values
# ---------------------------------------------------------------------------
VALID_PLATE_APPROACH = {"normal", "aggressive", "patient", "contact", "power"}
VALID_PITCHING_APPROACH = {"normal", "aggressive", "finesse", "power", "location"}
VALID_BASERUNNING_APPROACH = {"normal", "aggressive", "cautious", "conservative"}
VALID_USAGE_PREFERENCE = {"normal", "only_fully_rested", "play_tired", "desperation"}
VALID_PULLTEND = {"normal", "quick", "long"}
VALID_OF_SPACING = {"normal", "deep", "shallow", "shift_pull", "shift_oppo"}
VALID_IF_SPACING = {"normal", "in", "double_play", "shift_pull", "shift_oppo"}
VALID_BP_PRIORITY = {"rest", "matchup", "best_available"}
VALID_LINEUP_ROLES = {"table_setter", "on_base", "balanced", "slugger", "bottom", "speed"}
VALID_POSITION_CODES = {"c", "fb", "sb", "tb", "ss", "lf", "cf", "rf", "dh", "p"}
VALID_VS_HAND = {"L", "R", "both"}
VALID_BP_ROLES = {"closer", "setup", "middle", "long", "mop_up"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_strategy(d: dict) -> dict:
    """Normalize a playerStrategies row for JSON output."""
    pitchchoices = d.get("pitchchoices")
    if pitchchoices is None:
        pitchchoices = DEFAULT_PLAYER_STRATEGY["pitchchoices"]
    elif isinstance(pitchchoices, str):
        try:
            pitchchoices = json.loads(pitchchoices)
        except (TypeError, json.JSONDecodeError):
            pitchchoices = DEFAULT_PLAYER_STRATEGY["pitchchoices"]

    return {
        "id": d.get("id"),
        "player_id": d.get("playerID"),
        "org_id": d.get("orgID"),
        "user_id": d.get("userID"),
        "plate_approach": d.get("plate_approach") or DEFAULT_PLAYER_STRATEGY["plate_approach"],
        "pitching_approach": d.get("pitching_approach") or DEFAULT_PLAYER_STRATEGY["pitching_approach"],
        "baserunning_approach": d.get("baserunning_approach") or DEFAULT_PLAYER_STRATEGY["baserunning_approach"],
        "usage_preference": d.get("usage_preference") or DEFAULT_PLAYER_STRATEGY["usage_preference"],
        "stealfreq": float(d["stealfreq"]) if d.get("stealfreq") is not None else DEFAULT_PLAYER_STRATEGY["stealfreq"],
        "pickofffreq": float(d["pickofffreq"]) if d.get("pickofffreq") is not None else DEFAULT_PLAYER_STRATEGY["pickofffreq"],
        "pitchchoices": pitchchoices,
        "pitchpull": int(d["pitchpull"]) if d.get("pitchpull") is not None else None,
        "pulltend": d.get("pulltend") or None,
    }


def _format_team_strategy(d: dict, team_id: int) -> dict:
    """Normalize a team_strategy row for JSON output."""
    iwl = d.get("intentional_walk_list")
    if iwl is None:
        iwl = []
    elif isinstance(iwl, str):
        try:
            iwl = json.loads(iwl)
        except (TypeError, json.JSONDecodeError):
            iwl = []

    return {
        "team_id": team_id,
        "outfield_spacing": d.get("outfield_spacing", DEFAULT_TEAM_STRATEGY["outfield_spacing"]),
        "infield_spacing": d.get("infield_spacing", DEFAULT_TEAM_STRATEGY["infield_spacing"]),
        "bullpen_cutoff": int(d.get("bullpen_cutoff") or DEFAULT_TEAM_STRATEGY["bullpen_cutoff"]),
        "bullpen_priority": d.get("bullpen_priority", DEFAULT_TEAM_STRATEGY["bullpen_priority"]),
        "emergency_pitcher_id": d.get("emergency_pitcher_id"),
        "intentional_walk_list": iwl,
    }


# ===================================================================
# 1. PLAYER STRATEGIES
# ===================================================================

@gameplanning_bp.get("/gameplanning/org/<int:org_id>/player-strategies")
def get_org_player_strategies(org_id: int):
    """All player strategies for an organization."""
    engine = get_engine()
    tbl = _reflect_table("playerStrategies")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(tbl).where(tbl.c.orgID == org_id)
            ).all()
        strategies = [_format_strategy(_row_to_dict(r)) for r in rows]
        return jsonify({"org_id": org_id, "strategies": strategies}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get player strategies db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.get("/gameplanning/org/<int:org_id>/player/<int:player_id>/strategy")
def get_player_strategy(org_id: int, player_id: int):
    """Single player strategy for org. Returns defaults if no row."""
    engine = get_engine()
    tbl = _reflect_table("playerStrategies")
    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(tbl).where(and_(tbl.c.playerID == player_id, tbl.c.orgID == org_id)).limit(1)
            ).first()
        if row:
            return jsonify(_format_strategy(_row_to_dict(row))), 200
        # Return defaults
        defaults = dict(DEFAULT_PLAYER_STRATEGY)
        defaults["player_id"] = player_id
        defaults["org_id"] = org_id
        defaults["id"] = None
        defaults["user_id"] = None
        return jsonify(defaults), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get player strategy db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/org/<int:org_id>/player/<int:player_id>/strategy")
def put_player_strategy(org_id: int, player_id: int):
    """Upsert a player's strategy."""
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    if user_id is None:
        return jsonify(error="validation_error", message="user_id is required"), 400

    # Validate optional fields
    errors = []
    if "stealfreq" in body and body["stealfreq"] is not None:
        try:
            sf = float(body["stealfreq"])
            if not 0 <= sf <= 100:
                errors.append("stealfreq must be 0-100")
        except (TypeError, ValueError):
            errors.append("stealfreq must be a number")

    if "pickofffreq" in body and body["pickofffreq"] is not None:
        try:
            pf = float(body["pickofffreq"])
            if not 0 <= pf <= 100:
                errors.append("pickofffreq must be 0-100")
        except (TypeError, ValueError):
            errors.append("pickofffreq must be a number")

    if "pitchchoices" in body and body["pitchchoices"] is not None:
        pc = body["pitchchoices"]
        if not isinstance(pc, list) or len(pc) != 5:
            errors.append("pitchchoices must be an array of exactly 5 numbers")

    if "plate_approach" in body and body["plate_approach"] not in VALID_PLATE_APPROACH:
        errors.append(f"plate_approach must be one of: {', '.join(sorted(VALID_PLATE_APPROACH))}")
    if "pitching_approach" in body and body["pitching_approach"] not in VALID_PITCHING_APPROACH:
        errors.append(f"pitching_approach must be one of: {', '.join(sorted(VALID_PITCHING_APPROACH))}")
    if "baserunning_approach" in body and body["baserunning_approach"] not in VALID_BASERUNNING_APPROACH:
        errors.append(f"baserunning_approach must be one of: {', '.join(sorted(VALID_BASERUNNING_APPROACH))}")
    if "usage_preference" in body and body["usage_preference"] not in VALID_USAGE_PREFERENCE:
        errors.append(f"usage_preference must be one of: {', '.join(sorted(VALID_USAGE_PREFERENCE))}")
    if "pulltend" in body and body["pulltend"] is not None and body["pulltend"] not in VALID_PULLTEND:
        errors.append(f"pulltend must be one of: {', '.join(sorted(VALID_PULLTEND))}")
    if "pitchpull" in body and body["pitchpull"] is not None:
        try:
            pp = int(body["pitchpull"])
            if pp <= 0:
                errors.append("pitchpull must be a positive integer")
        except (TypeError, ValueError):
            errors.append("pitchpull must be an integer")

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    # Build column values for upsert
    values = {}
    str_fields = ["plate_approach", "pitching_approach", "baserunning_approach", "usage_preference"]
    for f in str_fields:
        if f in body:
            values[f] = body[f]

    num_fields = {"stealfreq": float, "pickofffreq": float, "pitchpull": int}
    for f, cast in num_fields.items():
        if f in body:
            values[f] = cast(body[f]) if body[f] is not None else None

    if "pulltend" in body:
        values["pulltend"] = body["pulltend"]
    if "pitchchoices" in body:
        values["pitchchoices"] = json.dumps(body["pitchchoices"]) if body["pitchchoices"] is not None else None

    # Build UPDATE SET clause from provided fields
    if not values:
        # Nothing to update, but still do upsert to ensure row exists
        pass

    set_clause = ", ".join(f"{k} = VALUES({k})" for k in values) if values else "id = id"
    col_names = ["playerID", "orgID", "userID"] + list(values.keys())
    placeholders = ", ".join(f":{c}" for c in col_names)
    col_list = ", ".join(col_names)

    params = {"playerID": player_id, "orgID": org_id, "userID": user_id}
    params.update(values)

    sql = text(
        f"INSERT INTO playerStrategies ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {set_clause}"
    )

    engine = get_engine()
    tbl = _reflect_table("playerStrategies")
    try:
        with engine.connect() as conn:
            conn.execute(sql, params)
            conn.commit()
            # Fetch updated row
            row = conn.execute(
                select(tbl).where(
                    and_(tbl.c.playerID == player_id, tbl.c.orgID == org_id, tbl.c.userID == user_id)
                ).limit(1)
            ).first()
        if row:
            return jsonify(_format_strategy(_row_to_dict(row))), 200
        return jsonify(error="unexpected", message="Row not found after upsert"), 500
    except SQLAlchemyError:
        log.exception("gameplanning: put player strategy db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ===================================================================
# 2. TEAM STRATEGY
# ===================================================================

@gameplanning_bp.get("/gameplanning/team/<int:team_id>/strategy")
def get_team_strategy(team_id: int):
    """Team-level strategy settings. Returns defaults if no row."""
    engine = get_engine()
    tbl = _reflect_table("team_strategy")
    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).limit(1)
            ).first()
        if row:
            return jsonify(_format_team_strategy(_row_to_dict(row), team_id)), 200
        return jsonify(_format_team_strategy(DEFAULT_TEAM_STRATEGY, team_id)), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get team strategy db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/team/<int:team_id>/strategy")
def put_team_strategy(team_id: int):
    """Upsert team strategy."""
    body = request.get_json(silent=True) or {}
    errors = []

    if "outfield_spacing" in body and body["outfield_spacing"] not in VALID_OF_SPACING:
        errors.append(f"outfield_spacing must be one of: {', '.join(sorted(VALID_OF_SPACING))}")
    if "infield_spacing" in body and body["infield_spacing"] not in VALID_IF_SPACING:
        errors.append(f"infield_spacing must be one of: {', '.join(sorted(VALID_IF_SPACING))}")
    if "bullpen_priority" in body and body["bullpen_priority"] not in VALID_BP_PRIORITY:
        errors.append(f"bullpen_priority must be one of: {', '.join(sorted(VALID_BP_PRIORITY))}")
    if "bullpen_cutoff" in body:
        try:
            bc = int(body["bullpen_cutoff"])
            if bc <= 0:
                errors.append("bullpen_cutoff must be a positive integer")
        except (TypeError, ValueError):
            errors.append("bullpen_cutoff must be an integer")
    if "intentional_walk_list" in body and body["intentional_walk_list"] is not None:
        iwl = body["intentional_walk_list"]
        if not isinstance(iwl, list) or not all(isinstance(x, int) for x in iwl):
            errors.append("intentional_walk_list must be an array of integers")

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    values = {"team_id": team_id}
    field_map = {
        "outfield_spacing": str,
        "infield_spacing": str,
        "bullpen_cutoff": int,
        "bullpen_priority": str,
        "emergency_pitcher_id": lambda x: int(x) if x is not None else None,
    }
    for f, cast in field_map.items():
        if f in body:
            values[f] = cast(body[f])
    if "intentional_walk_list" in body:
        values["intentional_walk_list"] = json.dumps(body["intentional_walk_list"]) if body["intentional_walk_list"] is not None else None

    col_names = list(values.keys())
    placeholders = ", ".join(f":{c}" for c in col_names)
    col_list = ", ".join(col_names)
    set_parts = [f"{c} = VALUES({c})" for c in col_names if c != "team_id"]
    set_clause = ", ".join(set_parts) if set_parts else "id = id"

    sql = text(
        f"INSERT INTO team_strategy ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {set_clause}"
    )

    engine = get_engine()
    tbl = _reflect_table("team_strategy")
    try:
        with engine.connect() as conn:
            conn.execute(sql, values)
            conn.commit()
            row = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).limit(1)
            ).first()
        if row:
            return jsonify(_format_team_strategy(_row_to_dict(row), team_id)), 200
        return jsonify(error="unexpected", message="Row not found after upsert"), 500
    except SQLAlchemyError:
        log.exception("gameplanning: put team strategy db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ===================================================================
# 3. LINEUP ROLES
# ===================================================================

@gameplanning_bp.get("/gameplanning/team/<int:team_id>/lineup")
def get_lineup(team_id: int):
    """Batting order role configuration (9 slots)."""
    engine = get_engine()
    tbl = _reflect_table("team_lineup_roles")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).order_by(tbl.c.slot.asc())
            ).all()
        slots = []
        for r in rows:
            d = _row_to_dict(r)
            slots.append({
                "slot": d["slot"],
                "role": d["role"],
                "locked_player_id": d.get("locked_player_id"),
                "min_order": d.get("min_order"),
                "max_order": d.get("max_order"),
            })
        return jsonify({"team_id": team_id, "slots": slots}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get lineup db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/team/<int:team_id>/lineup")
def put_lineup(team_id: int):
    """Bulk replace lineup role configuration."""
    body = request.get_json(silent=True) or {}
    slots_data = body.get("slots")
    if not isinstance(slots_data, list) or not slots_data:
        return jsonify(error="validation_error", message="slots must be a non-empty array"), 400

    errors = []
    seen_slots = set()
    for i, s in enumerate(slots_data):
        slot_num = s.get("slot")
        if not isinstance(slot_num, int) or slot_num < 1 or slot_num > 9:
            errors.append(f"slots[{i}].slot must be an integer 1-9")
        elif slot_num in seen_slots:
            errors.append(f"duplicate slot number: {slot_num}")
        else:
            seen_slots.add(slot_num)

        role = s.get("role")
        if role not in VALID_LINEUP_ROLES:
            errors.append(f"slots[{i}].role must be one of: {', '.join(sorted(VALID_LINEUP_ROLES))}")

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    engine = get_engine()
    tbl = _reflect_table("team_lineup_roles")
    try:
        with engine.connect() as conn:
            conn.execute(tbl.delete().where(tbl.c.team_id == team_id))
            for s in slots_data:
                conn.execute(tbl.insert().values(
                    team_id=team_id,
                    slot=s["slot"],
                    role=s["role"],
                    locked_player_id=s.get("locked_player_id"),
                    min_order=s.get("min_order"),
                    max_order=s.get("max_order"),
                ))
            conn.commit()

            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).order_by(tbl.c.slot.asc())
            ).all()
        slots = [{
            "slot": _row_to_dict(r)["slot"],
            "role": _row_to_dict(r)["role"],
            "locked_player_id": _row_to_dict(r).get("locked_player_id"),
            "min_order": _row_to_dict(r).get("min_order"),
            "max_order": _row_to_dict(r).get("max_order"),
        } for r in rows]
        return jsonify({"team_id": team_id, "slots": slots}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: put lineup db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ===================================================================
# 4. DEFENSE PLAN
# ===================================================================

@gameplanning_bp.get("/gameplanning/team/<int:team_id>/defense")
def get_defense(team_id: int):
    """Defensive depth chart / position plan."""
    engine = get_engine()
    tbl = _reflect_table("team_position_plan")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id)
                .order_by(tbl.c.position_code, tbl.c.priority)
            ).all()
        assignments = []
        for r in rows:
            d = _row_to_dict(r)
            assignments.append({
                "id": d["id"],
                "position_code": d["position_code"],
                "vs_hand": d["vs_hand"],
                "player_id": d["player_id"],
                "target_weight": float(d["target_weight"]),
                "priority": d["priority"],
                "locked": bool(d.get("locked", 0)),
            })
        return jsonify({"team_id": team_id, "assignments": assignments}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get defense db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/team/<int:team_id>/defense")
def put_defense(team_id: int):
    """Bulk replace defensive assignments."""
    body = request.get_json(silent=True) or {}
    assignments_data = body.get("assignments")
    if not isinstance(assignments_data, list):
        return jsonify(error="validation_error", message="assignments must be an array"), 400

    errors = []
    for i, a in enumerate(assignments_data):
        if a.get("position_code") not in VALID_POSITION_CODES:
            errors.append(f"assignments[{i}].position_code must be one of: {', '.join(sorted(VALID_POSITION_CODES))}")
        if a.get("vs_hand") not in VALID_VS_HAND:
            errors.append(f"assignments[{i}].vs_hand must be one of: {', '.join(sorted(VALID_VS_HAND))}")
        if not isinstance(a.get("player_id"), int):
            errors.append(f"assignments[{i}].player_id is required (int)")
        tw = a.get("target_weight")
        if tw is not None:
            try:
                if float(tw) <= 0:
                    errors.append(f"assignments[{i}].target_weight must be > 0")
            except (TypeError, ValueError):
                errors.append(f"assignments[{i}].target_weight must be a number")

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    engine = get_engine()
    tbl = _reflect_table("team_position_plan")
    try:
        with engine.connect() as conn:
            conn.execute(tbl.delete().where(tbl.c.team_id == team_id))
            for a in assignments_data:
                conn.execute(tbl.insert().values(
                    team_id=team_id,
                    position_code=a["position_code"],
                    vs_hand=a.get("vs_hand", "both"),
                    player_id=a["player_id"],
                    target_weight=float(a.get("target_weight", 1.0)),
                    priority=int(a.get("priority", 1)),
                    locked=1 if a.get("locked") else 0,
                ))
            conn.commit()

            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id)
                .order_by(tbl.c.position_code, tbl.c.priority)
            ).all()
        assignments = [{
            "id": _row_to_dict(r)["id"],
            "position_code": _row_to_dict(r)["position_code"],
            "vs_hand": _row_to_dict(r)["vs_hand"],
            "player_id": _row_to_dict(r)["player_id"],
            "target_weight": float(_row_to_dict(r)["target_weight"]),
            "priority": _row_to_dict(r)["priority"],
            "locked": bool(_row_to_dict(r).get("locked", 0)),
        } for r in rows]
        return jsonify({"team_id": team_id, "assignments": assignments}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: put defense db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ===================================================================
# 5. PITCHING ROTATION
# ===================================================================

@gameplanning_bp.get("/gameplanning/team/<int:team_id>/rotation")
def get_rotation(team_id: int):
    """Pitching rotation config, slot assignments, and current state."""
    engine = get_engine()
    rotation_tbl = _reflect_table("team_pitching_rotation")
    slots_tbl = _reflect_table("team_pitching_rotation_slots")
    state_tbl = _reflect_table("team_rotation_state")

    try:
        with engine.connect() as conn:
            rot_row = conn.execute(
                select(rotation_tbl).where(rotation_tbl.c.team_id == team_id).limit(1)
            ).first()

            if not rot_row:
                return jsonify({
                    "team_id": team_id,
                    "rotation_size": None,
                    "current_slot": 0,
                    "last_game_id": None,
                    "slots": [],
                }), 200

            rot = _row_to_dict(rot_row)
            rotation_id = rot["id"]

            slot_rows = conn.execute(
                select(slots_tbl).where(slots_tbl.c.rotation_id == rotation_id)
                .order_by(slots_tbl.c.slot.asc())
            ).all()

            state_row = conn.execute(
                select(state_tbl).where(state_tbl.c.team_id == team_id).limit(1)
            ).first()
            state = _row_to_dict(state_row) if state_row else {}

        slots = [{"slot": _row_to_dict(r)["slot"], "player_id": int(_row_to_dict(r)["player_id"])} for r in slot_rows]

        return jsonify({
            "team_id": team_id,
            "rotation_size": rot["rotation_size"],
            "current_slot": state.get("current_slot", 0),
            "last_game_id": int(state["last_game_id"]) if state.get("last_game_id") is not None else None,
            "slots": slots,
        }), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get rotation db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/team/<int:team_id>/rotation")
def put_rotation(team_id: int):
    """Upsert pitching rotation and slot assignments."""
    body = request.get_json(silent=True) or {}
    rotation_size = body.get("rotation_size")
    slots_data = body.get("slots")

    if not isinstance(rotation_size, int) or rotation_size < 1 or rotation_size > 7:
        return jsonify(error="validation_error", message="rotation_size must be an integer 1-7"), 400
    if not isinstance(slots_data, list) or len(slots_data) != rotation_size:
        return jsonify(error="validation_error", message=f"slots must be an array of length {rotation_size}"), 400

    errors = []
    seen_slots = set()
    seen_players = set()
    for i, s in enumerate(slots_data):
        slot_num = s.get("slot")
        pid = s.get("player_id")
        if not isinstance(slot_num, int) or slot_num < 1 or slot_num > rotation_size:
            errors.append(f"slots[{i}].slot must be 1-{rotation_size}")
        elif slot_num in seen_slots:
            errors.append(f"duplicate slot: {slot_num}")
        else:
            seen_slots.add(slot_num)
        if not isinstance(pid, int):
            errors.append(f"slots[{i}].player_id is required (int)")
        elif pid in seen_players:
            errors.append(f"duplicate player_id: {pid}")
        else:
            seen_players.add(pid)

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    engine = get_engine()
    rotation_tbl = _reflect_table("team_pitching_rotation")
    slots_tbl = _reflect_table("team_pitching_rotation_slots")
    state_tbl = _reflect_table("team_rotation_state")

    try:
        with engine.connect() as conn:
            # Upsert rotation row
            existing = conn.execute(
                select(rotation_tbl.c.id).where(rotation_tbl.c.team_id == team_id).limit(1)
            ).first()

            if existing:
                rotation_id = existing[0]
                conn.execute(
                    rotation_tbl.update().where(rotation_tbl.c.id == rotation_id)
                    .values(rotation_size=rotation_size)
                )
            else:
                result = conn.execute(
                    rotation_tbl.insert().values(team_id=team_id, rotation_size=rotation_size)
                )
                rotation_id = result.lastrowid

            # Replace slots
            conn.execute(slots_tbl.delete().where(slots_tbl.c.rotation_id == rotation_id))
            for s in slots_data:
                conn.execute(slots_tbl.insert().values(
                    rotation_id=rotation_id,
                    slot=s["slot"],
                    player_id=s["player_id"],
                ))

            # Init state if missing
            state_exists = conn.execute(
                select(state_tbl.c.team_id).where(state_tbl.c.team_id == team_id).limit(1)
            ).first()
            if not state_exists:
                conn.execute(state_tbl.insert().values(team_id=team_id, current_slot=0))

            conn.commit()

            # Read back
            rot_row = conn.execute(
                select(rotation_tbl).where(rotation_tbl.c.team_id == team_id).limit(1)
            ).first()
            rot = _row_to_dict(rot_row)
            slot_rows = conn.execute(
                select(slots_tbl).where(slots_tbl.c.rotation_id == rot["id"])
                .order_by(slots_tbl.c.slot.asc())
            ).all()
            state_row = conn.execute(
                select(state_tbl).where(state_tbl.c.team_id == team_id).limit(1)
            ).first()
            state = _row_to_dict(state_row) if state_row else {}

        slots = [{"slot": _row_to_dict(r)["slot"], "player_id": int(_row_to_dict(r)["player_id"])} for r in slot_rows]
        return jsonify({
            "team_id": team_id,
            "rotation_size": rot["rotation_size"],
            "current_slot": state.get("current_slot", 0),
            "last_game_id": int(state["last_game_id"]) if state.get("last_game_id") is not None else None,
            "slots": slots,
        }), 200
    except SQLAlchemyError:
        log.exception("gameplanning: put rotation db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ===================================================================
# 6. BULLPEN ORDER
# ===================================================================

@gameplanning_bp.get("/gameplanning/team/<int:team_id>/bullpen")
def get_bullpen(team_id: int):
    """Ordered bullpen preference list."""
    engine = get_engine()
    tbl = _reflect_table("team_bullpen_order")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).order_by(tbl.c.slot.asc())
            ).all()
        pitchers = [{
            "slot": _row_to_dict(r)["slot"],
            "player_id": _row_to_dict(r)["player_id"],
            "role": _row_to_dict(r)["role"],
        } for r in rows]
        return jsonify({"team_id": team_id, "pitchers": pitchers}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: get bullpen db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


@gameplanning_bp.put("/gameplanning/team/<int:team_id>/bullpen")
def put_bullpen(team_id: int):
    """Bulk replace bullpen ordering."""
    body = request.get_json(silent=True) or {}
    pitchers_data = body.get("pitchers")
    if not isinstance(pitchers_data, list):
        return jsonify(error="validation_error", message="pitchers must be an array"), 400

    errors = []
    seen_slots = set()
    seen_players = set()
    for i, p in enumerate(pitchers_data):
        slot = p.get("slot")
        pid = p.get("player_id")
        role = p.get("role", "middle")

        if not isinstance(slot, int) or slot < 1:
            errors.append(f"pitchers[{i}].slot must be a positive integer")
        elif slot in seen_slots:
            errors.append(f"duplicate slot: {slot}")
        else:
            seen_slots.add(slot)

        if not isinstance(pid, int):
            errors.append(f"pitchers[{i}].player_id is required (int)")
        elif pid in seen_players:
            errors.append(f"duplicate player_id: {pid}")
        else:
            seen_players.add(pid)

        if role not in VALID_BP_ROLES:
            errors.append(f"pitchers[{i}].role must be one of: {', '.join(sorted(VALID_BP_ROLES))}")

    if errors:
        return jsonify(error="validation_error", message="; ".join(errors)), 400

    engine = get_engine()
    tbl = _reflect_table("team_bullpen_order")
    try:
        with engine.connect() as conn:
            conn.execute(tbl.delete().where(tbl.c.team_id == team_id))
            for p in pitchers_data:
                conn.execute(tbl.insert().values(
                    team_id=team_id,
                    slot=p["slot"],
                    player_id=p["player_id"],
                    role=p.get("role", "middle"),
                ))
            conn.commit()

            rows = conn.execute(
                select(tbl).where(tbl.c.team_id == team_id).order_by(tbl.c.slot.asc())
            ).all()
        pitchers = [{
            "slot": _row_to_dict(r)["slot"],
            "player_id": _row_to_dict(r)["player_id"],
            "role": _row_to_dict(r)["role"],
        } for r in rows]
        return jsonify({"team_id": team_id, "pitchers": pitchers}), 200
    except SQLAlchemyError:
        log.exception("gameplanning: put bullpen db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503
