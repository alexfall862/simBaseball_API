# services/timestamp.py
"""
Timestamp service for managing global simulation state.

The timestamp is a single-row table (ID=1) that tracks the current state
of the simulation: what season/week we're in, which games have run, and
various phase flags.

This state is broadcast to all connected WebSocket clients whenever it changes.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from sqlalchemy import MetaData, Table, select, update
from db import get_engine

logger = logging.getLogger(__name__)

# Module-level cache for reflected table
_TIMESTAMP_TABLE = None
_TIMESTAMP_METADATA = None


def _get_timestamp_table():
    """
    Reflect and cache the timestamp_state table.
    """
    global _TIMESTAMP_TABLE, _TIMESTAMP_METADATA

    if _TIMESTAMP_TABLE is not None:
        return _TIMESTAMP_TABLE

    engine = get_engine()
    md = MetaData()

    _TIMESTAMP_TABLE = Table("timestamp_state", md, autoload_with=engine)
    _TIMESTAMP_METADATA = md

    return _TIMESTAMP_TABLE


def get_current_timestamp() -> Optional[Dict[str, Any]]:
    """
    Fetch the current timestamp state from the database.

    Returns:
        Dictionary with timestamp fields formatted for frontend consumption,
        or None if no timestamp exists.

    The returned dict uses PascalCase keys to match frontend expectations:
    {
        "ID": 1,
        "CreatedAt": "2025-01-15T10:30:00Z",
        "UpdatedAt": "2025-11-30T14:22:00Z",
        "Season": 2026,
        "SeasonID": 1,
        "Week": 15,
        "WeekID": 45,
        "GamesARan": true,
        ...
    }
    """
    engine = get_engine()
    ts_table = _get_timestamp_table()

    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(ts_table).where(ts_table.c.id == 1)
            ).mappings().first()

            if not row:
                logger.warning("No timestamp row found (ID=1)")
                return None

            # Convert to frontend format (PascalCase)
            return _format_timestamp_for_frontend(dict(row))

    except Exception as e:
        logger.exception(f"Failed to fetch timestamp: {e}")
        return None


def _format_timestamp_for_frontend(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert database row (snake_case) to frontend format (PascalCase).
    """
    def format_datetime(dt) -> Optional[str]:
        if dt is None:
            return None
        if isinstance(dt, str):
            return dt
        if isinstance(dt, datetime):
            return dt.isoformat() + "Z"
        return str(dt)

    return {
        "ID": row.get("id", 1),
        "CreatedAt": format_datetime(row.get("created_at")),
        "UpdatedAt": format_datetime(row.get("updated_at")),
        "Season": row.get("season", 2026),
        "SeasonID": row.get("season_id", 1),
        "Week": row.get("week", 1),
        "WeekID": row.get("week_id"),
        "GamesARan": bool(row.get("games_a_ran", False)),
        "GamesBRan": bool(row.get("games_b_ran", False)),
        "GamesCRan": bool(row.get("games_c_ran", False)),
        "GamesDRan": bool(row.get("games_d_ran", False)),
        "IsOffSeason": bool(row.get("is_offseason", False)),
        "IsRecruitingLocked": bool(row.get("is_recruiting_locked", True)),
        "IsFreeAgencyLocked": bool(row.get("is_free_agency_locked", True)),
        "IsDraftTime": bool(row.get("is_draft_time", False)),
        "RunGames": bool(row.get("run_games", False)),
        "RunCron": bool(row.get("run_cron", False)),
        "RecruitingSynced": bool(row.get("recruiting_synced", True)),
        "GMActionsCompleted": bool(row.get("gm_actions_completed", True)),
        "FreeAgencyRound": row.get("free_agency_round", 0),
    }


def update_timestamp(updates: Dict[str, Any], broadcast: bool = True) -> bool:
    """
    Update the timestamp state and optionally broadcast to WebSocket clients.

    Args:
        updates: Dictionary of fields to update (snake_case keys).
                 Valid fields: season, season_id, week, week_id,
                 games_a_ran, games_b_ran, games_c_ran, games_d_ran,
                 is_offseason, is_recruiting_locked, is_free_agency_locked,
                 is_draft_time, run_games, run_cron, recruiting_synced,
                 gm_actions_completed, free_agency_round
        broadcast: If True, broadcast updated state to all WebSocket clients

    Returns:
        True if update succeeded, False otherwise
    """
    if not updates:
        logger.warning("update_timestamp called with empty updates")
        return False

    engine = get_engine()
    ts_table = _get_timestamp_table()

    # Whitelist of allowed fields
    allowed_fields = {
        "season", "season_id", "week", "week_id",
        "games_a_ran", "games_b_ran", "games_c_ran", "games_d_ran",
        "is_offseason", "is_recruiting_locked", "is_free_agency_locked",
        "is_draft_time", "run_games", "run_cron", "recruiting_synced",
        "gm_actions_completed", "free_agency_round"
    }

    # Filter to only allowed fields
    filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

    if not filtered_updates:
        logger.warning(f"No valid fields in updates: {updates.keys()}")
        return False

    try:
        with engine.connect() as conn:
            stmt = (
                update(ts_table)
                .where(ts_table.c.id == 1)
                .values(**filtered_updates)
            )
            result = conn.execute(stmt)
            conn.commit()

            if result.rowcount == 0:
                logger.error("Timestamp update affected 0 rows - does ID=1 exist?")
                return False

            logger.info(f"Timestamp updated: {filtered_updates}")

            # Broadcast to WebSocket clients
            if broadcast:
                from services.websocket_manager import ws_manager
                ws_manager.broadcast_timestamp()

            return True

    except Exception as e:
        logger.exception(f"Failed to update timestamp: {e}")
        return False


def set_subweek_completed(subweek: str, broadcast: bool = True) -> bool:
    """
    Mark a subweek as completed.

    Args:
        subweek: The subweek to mark complete ('a', 'b', 'c', or 'd')
        broadcast: If True, broadcast updated state to WebSocket clients

    Returns:
        True if update succeeded, False otherwise
    """
    subweek = subweek.lower()
    field_map = {
        "a": "games_a_ran",
        "b": "games_b_ran",
        "c": "games_c_ran",
        "d": "games_d_ran",
    }

    if subweek not in field_map:
        logger.error(f"Invalid subweek: {subweek}")
        return False

    return update_timestamp({field_map[subweek]: True}, broadcast=broadcast)


def set_run_games(running: bool, broadcast: bool = True) -> bool:
    """
    Set the RunGames flag (indicates simulation is actively running).

    Args:
        running: True if simulation is running, False when complete
        broadcast: If True, broadcast updated state to WebSocket clients

    Returns:
        True if update succeeded, False otherwise
    """
    return update_timestamp({"run_games": running}, broadcast=broadcast)


def advance_week(broadcast: bool = True) -> bool:
    """
    Advance to the next week and reset all game completion flags.

    Args:
        broadcast: If True, broadcast updated state to WebSocket clients

    Returns:
        True if update succeeded, False otherwise
    """
    engine = get_engine()
    ts_table = _get_timestamp_table()

    try:
        with engine.connect() as conn:
            # Get current week
            row = conn.execute(
                select(ts_table.c.week).where(ts_table.c.id == 1)
            ).first()

            if not row:
                logger.error("No timestamp row found")
                return False

            current_week = row[0]
            new_week = current_week + 1

            # Update week and reset game flags
            stmt = (
                update(ts_table)
                .where(ts_table.c.id == 1)
                .values(
                    week=new_week,
                    games_a_ran=False,
                    games_b_ran=False,
                    games_c_ran=False,
                    games_d_ran=False,
                )
            )
            conn.execute(stmt)
            conn.commit()

            logger.info(f"Advanced from week {current_week} to week {new_week}")

            # Broadcast to WebSocket clients
            if broadcast:
                from services.websocket_manager import ws_manager
                ws_manager.broadcast_timestamp()

            return True

    except Exception as e:
        logger.exception(f"Failed to advance week: {e}")
        return False


def reset_week_games(broadcast: bool = True) -> bool:
    """
    Reset all game completion flags without advancing the week.

    Args:
        broadcast: If True, broadcast updated state to WebSocket clients

    Returns:
        True if update succeeded, False otherwise
    """
    return update_timestamp(
        {
            "games_a_ran": False,
            "games_b_ran": False,
            "games_c_ran": False,
            "games_d_ran": False,
        },
        broadcast=broadcast
    )
