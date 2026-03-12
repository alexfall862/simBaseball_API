# players/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select, and_, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine
import logging

players_bp = Blueprint("players", __name__)


def _reflect_players_table():
    """Reflect the simbbPlayers table and cache it on the blueprint."""
    if not hasattr(players_bp, "_players_table"):
        engine = get_engine()
        metadata = MetaData()
        players_bp._players_table = Table(
            "simbbPlayers",
            metadata,
            autoload_with=engine,
        )
    return players_bp._players_table


def _row_to_dict(row):
    # Generic: handles 100+ columns without listing them
    d = {}
    for key, value in row._mapping.items():
        # Convert Decimal to float for JSON serialization
        if hasattr(value, "is_finite"):
            value = float(value)
        d[key] = value
    return d


def _get_player_contract_info(conn, player_id):
    """
    Look up the holding org and current level for a player.
    Returns (holding_org_id, current_level) or (None, None).
    """
    row = conn.execute(
        text("""
            SELECT cts.orgID, c.current_level
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.playerID = :pid AND c.isActive = 1
            LIMIT 1
        """),
        {"pid": player_id},
    ).first()
    if row:
        return row[0], row[1]
    return None, None


@players_bp.get("/players")
def get_players():
    """
    Return all players, or at least their IDs.
    """
    try:
        engine = get_engine()
        players_table = _reflect_players_table()

        stmt = select(players_table.c.id).order_by(players_table.c.id)

        with engine.connect() as conn:
            rows = conn.execute(stmt).all()

        logging.getLogger("app").info("get_players: fetched %d rows", len(rows))
        return jsonify([row[0] for row in rows]), 200
    except SQLAlchemyError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "db_unavailable",
                        "message": "Database temporarily unavailable",
                    }
                }
            ),
            503,
        )


@players_bp.get("/players/<int:player_id>/")
def get_player(player_id):
    """
    Return a single player row by integer ID.

    Optional query param: ?viewing_org_id=X
    If provided, applies fog-of-war visibility based on the viewing org's
    scouting actions. If absent, returns raw values (admin/legacy behavior).
    """
    viewing_org_id = request.args.get("viewing_org_id", type=int)

    try:
        engine = get_engine()
        players_table = _reflect_players_table()

        stmt = select(players_table).where(players_table.c.id == player_id).limit(1)

        with engine.connect() as conn:
            row = conn.execute(stmt).first()

            if not row:
                return jsonify([]), 200

            player_dict = _row_to_dict(row)

            # Apply fog-of-war if viewing_org_id is provided
            if viewing_org_id:
                from services.attribute_visibility import (
                    get_visible_player,
                    _load_scouting_actions_single,
                    _apply_visibility,
                    determine_player_context,
                    fuzz_letter_grade,
                    fuzz_20_80,
                    base_to_letter_grade,
                    GRADE_LIST,
                    GRADE_INDEX,
                )

                holding_org_id, current_level = _get_player_contract_info(conn, player_id)

                if holding_org_id is not None:
                    unlocked = _load_scouting_actions_single(conn, viewing_org_id, player_id)
                    context = determine_player_context(viewing_org_id, holding_org_id, current_level)

                    # Apply fuzz to _base and _pot columns directly
                    fuzzed_dict = {}
                    for key, value in player_dict.items():
                        if key.endswith("_base") and value is not None:
                            if context == "college_recruiting":
                                # Hidden
                                fuzzed_dict[key] = None
                            elif context in ("college_roster", "pro_draft"):
                                # Letter grade (fuzzed)
                                from services.scouting_service import base_to_letter_grade as svc_btlg
                                true_grade = svc_btlg(value)
                                fuzzed_dict[key] = fuzz_letter_grade(
                                    true_grade, viewing_org_id, player_id, key
                                )
                            elif context == "pro_roster":
                                # Fuzzed 20-80 not applicable at raw level;
                                # use roster endpoints for 20-80 display
                                fuzzed_dict[key] = value
                            else:
                                fuzzed_dict[key] = value
                        elif key.endswith("_pot"):
                            from services.attribute_visibility import (
                                _PRECISE_POT_ACTIONS,
                            )
                            if unlocked & _PRECISE_POT_ACTIONS:
                                fuzzed_dict[key] = value  # precise
                            elif value:
                                fuzzed_dict[key] = fuzz_letter_grade(
                                    value, viewing_org_id, player_id, key
                                )
                            else:
                                fuzzed_dict[key] = "?"
                        else:
                            fuzzed_dict[key] = value

                    fuzzed_dict["visibility_context"] = {
                        "context": context,
                        "viewing_org_id": viewing_org_id,
                    }
                    return jsonify([fuzzed_dict]), 200

        return jsonify([player_dict]), 200
    except SQLAlchemyError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "db_unavailable",
                        "message": "Database temporarily unavailable",
                    }
                }
            ),
            503,
        )
