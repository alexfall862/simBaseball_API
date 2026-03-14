# services/timestamp.py
"""
Timestamp service for managing global simulation state.

The timestamp is a single-row table (ID=1) that tracks the current state
of the simulation: what season/week we're in, which games have run, and
various phase flags.

This state is broadcast to all connected WebSocket clients whenever it changes.
"""

import logging
from typing import Dict, Any, Optional, List
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


# --- Phase derivation ---

# Fallback if no schedule exists yet
_DEFAULT_SEASON_WEEKS = 52


def _get_total_season_weeks(season: int) -> int:
    """
    Query the actual max scheduled week from gamelist for the given season.
    Falls back to _DEFAULT_SEASON_WEEKS if no games exist.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            row = conn.execute(
                text("SELECT MAX(season_week) FROM gamelist WHERE season = :s"),
                {"s": season},
            ).first()
            if row and row[0]:
                return int(row[0])
    except Exception:
        logger.debug("Could not query max season_week, using default")
    return _DEFAULT_SEASON_WEEKS


def get_current_phase(ts: Dict[str, Any]) -> str:
    """
    Derive the current simulation phase from timestamp flags.

    Args:
        ts: PascalCase timestamp dict (from _format_timestamp_for_frontend or
            get_current_timestamp).

    Returns:
        One of: REGULAR_SEASON, OFFSEASON, FREE_AGENCY, DRAFT, RECRUITING
    """
    if not ts.get("IsOffSeason"):
        return "REGULAR_SEASON"

    # Offseason sub-phases (check most specific first)
    if not ts.get("IsFreeAgencyLocked"):
        return "FREE_AGENCY"
    if ts.get("IsDraftTime"):
        return "DRAFT"
    if not ts.get("IsRecruitingLocked"):
        return "RECRUITING"

    return "OFFSEASON"


def get_available_actions(ts: Dict[str, Any], phase: str) -> List[str]:
    """
    Return the list of actions available in the current phase.

    Args:
        ts: PascalCase timestamp dict.
        phase: The current phase string from get_current_phase().

    Returns:
        List of action name strings the frontend can offer.
    """
    actions: List[str] = []

    if phase == "REGULAR_SEASON":
        all_ran = (
            ts.get("GamesARan")
            and ts.get("GamesBRan")
            and ts.get("GamesCRan")
            and ts.get("GamesDRan")
        )
        any_ran = (
            ts.get("GamesARan")
            or ts.get("GamesBRan")
            or ts.get("GamesCRan")
            or ts.get("GamesDRan")
        )

        if not ts.get("RunGames"):
            actions.append("simulate_week")

        if all_ran:
            actions.append("advance_week")

        if any_ran:
            actions.append("reset_week")

        actions.append("set_week")

        total_weeks = _get_total_season_weeks(ts.get("Season", 2026))
        if ts.get("Week", 0) >= total_weeks and all_ran:
            actions.append("end_season")

    elif phase == "OFFSEASON":
        actions.append("start_free_agency")
        actions.append("start_draft")
        actions.append("start_recruiting")
        actions.append("start_new_season")
        actions.append("set_week")

    elif phase == "FREE_AGENCY":
        actions.append("advance_fa_round")
        actions.append("end_free_agency")

    elif phase == "DRAFT":
        actions.append("end_draft")

    elif phase == "RECRUITING":
        actions.append("end_recruiting")

    # Always available
    actions.append("set_phase")

    return actions


def get_enhanced_timestamp() -> Optional[Dict[str, Any]]:
    """
    Get timestamp with derived Phase and AvailableActions for the frontend.

    Returns:
        Enhanced timestamp dict with Phase, AvailableActions, TotalWeeks,
        LeagueYearID, or None if no timestamp exists.
    """
    ts = get_current_timestamp()
    if ts is None:
        return None

    phase = get_current_phase(ts)
    actions = get_available_actions(ts, phase)

    ts["Phase"] = phase
    ts["AvailableActions"] = actions
    ts["TotalWeeks"] = _get_total_season_weeks(ts.get("Season", 2026))

    # Resolve LeagueYearID from Season (year number)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            row = conn.execute(
                text("SELECT id FROM league_years WHERE league_year = :yr"),
                {"yr": ts.get("Season", 2026)},
            ).first()
            ts["LeagueYearID"] = row[0] if row else 1
    except Exception:
        ts["LeagueYearID"] = 1

    return ts


# --- Week / phase management ---


def set_week(week: int, broadcast: bool = True) -> bool:
    """
    Jump to a specific week number (admin tool).
    Resets all game completion flags for the new week.

    Args:
        week: Target week number (1-based).
        broadcast: If True, broadcast updated state to WebSocket clients.

    Returns:
        True if update succeeded, False otherwise.
    """
    if week < 1:
        logger.error(f"set_week: invalid week {week}")
        return False

    return update_timestamp(
        {
            "week": week,
            "games_a_ran": False,
            "games_b_ran": False,
            "games_c_ran": False,
            "games_d_ran": False,
        },
        broadcast=broadcast,
    )


def set_phase_flags(
    is_offseason: bool = None,
    is_free_agency_locked: bool = None,
    is_draft_time: bool = None,
    is_recruiting_locked: bool = None,
    free_agency_round: int = None,
    broadcast: bool = True,
) -> bool:
    """
    Directly set phase-related flags (admin tool).

    Only provided (non-None) fields are updated.

    Args:
        is_offseason: Whether the sim is in offseason.
        is_free_agency_locked: Whether FA is locked.
        is_draft_time: Whether draft is active.
        is_recruiting_locked: Whether recruiting is locked.
        free_agency_round: Current FA round number.
        broadcast: If True, broadcast updated state.

    Returns:
        True if update succeeded, False otherwise.
    """
    updates: Dict[str, Any] = {}

    if is_offseason is not None:
        updates["is_offseason"] = is_offseason
    if is_free_agency_locked is not None:
        updates["is_free_agency_locked"] = is_free_agency_locked
    if is_draft_time is not None:
        updates["is_draft_time"] = is_draft_time
    if is_recruiting_locked is not None:
        updates["is_recruiting_locked"] = is_recruiting_locked
    if free_agency_round is not None:
        updates["free_agency_round"] = free_agency_round

    if not updates:
        logger.warning("set_phase_flags called with no updates")
        return False

    return update_timestamp(updates, broadcast=broadcast)


# --- Lifecycle transitions ---


def end_regular_season(league_year_id: int) -> Dict[str, Any]:
    """
    Transition from regular season to offseason.

    Steps:
      1. Run end-of-season contract processing (service time, expirations, FA eligibility)
      2. Progress all players (age +1, ability changes)
      3. Set timestamp flags to OFFSEASON

    Args:
        league_year_id: The league year to process.

    Returns:
        Summary dict with results from each step.

    Raises:
        ValueError: If not currently in REGULAR_SEASON phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "REGULAR_SEASON":
        raise ValueError(f"Cannot end regular season: currently in {phase}")

    engine = get_engine()
    summary: Dict[str, Any] = {"phase_transition": "REGULAR_SEASON -> OFFSEASON"}

    # 1. End-of-season contract processing
    try:
        from services.contract_ops import process_end_of_season
        with engine.begin() as conn:
            eos_result = process_end_of_season(conn, league_year_id)
        summary["end_of_season"] = eos_result
        logger.info(f"End-of-season contracts processed: {eos_result}")
    except Exception as e:
        logger.exception("end_regular_season: contract processing failed")
        summary["end_of_season_error"] = str(e)

    # 2. Player progression
    try:
        from player_engine.player_progression import progress_all_players
        with engine.begin() as conn:
            prog_result = progress_all_players(conn)
        summary["progression"] = prog_result
        logger.info(f"Player progression complete: {prog_result}")
    except Exception as e:
        logger.exception("end_regular_season: player progression failed")
        summary["progression_error"] = str(e)

    # 3. Flip to offseason
    update_timestamp(
        {
            "is_offseason": True,
            "is_free_agency_locked": True,
            "is_draft_time": False,
            "is_recruiting_locked": True,
            "free_agency_round": 0,
            "run_games": False,
            "games_a_ran": False,
            "games_b_ran": False,
            "games_c_ran": False,
            "games_d_ran": False,
        },
        broadcast=True,
    )
    summary["timestamp_updated"] = True

    logger.info(f"Regular season ended for league_year {league_year_id}")
    return summary


def start_free_agency() -> bool:
    """
    Open the free agency window.

    Sets is_free_agency_locked=False and resets free_agency_round to 1.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in OFFSEASON or FREE_AGENCY phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase not in ("OFFSEASON", "FREE_AGENCY"):
        raise ValueError(f"Cannot start free agency: currently in {phase}")

    return update_timestamp(
        {"is_free_agency_locked": False, "free_agency_round": 1},
        broadcast=True,
    )


def advance_fa_round() -> Dict[str, Any]:
    """
    Advance to the next free agency round.

    Returns:
        Dict with old_round and new_round.

    Raises:
        ValueError: If not in FREE_AGENCY phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "FREE_AGENCY":
        raise ValueError(f"Cannot advance FA round: currently in {phase}")

    old_round = ts.get("FreeAgencyRound", 0)
    new_round = old_round + 1

    update_timestamp({"free_agency_round": new_round}, broadcast=True)

    logger.info(f"Free agency advanced from round {old_round} to {new_round}")
    return {"old_round": old_round, "new_round": new_round}


def end_free_agency() -> bool:
    """
    Close the free agency window.

    Sets is_free_agency_locked=True.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in FREE_AGENCY phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "FREE_AGENCY":
        raise ValueError(f"Cannot end free agency: currently in {phase}")

    return update_timestamp(
        {"is_free_agency_locked": True},
        broadcast=True,
    )


def start_draft() -> bool:
    """
    Open the draft phase.

    Sets is_draft_time=True.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in OFFSEASON phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "OFFSEASON":
        raise ValueError(f"Cannot start draft: currently in {phase}")

    return update_timestamp({"is_draft_time": True}, broadcast=True)


def end_draft() -> bool:
    """
    Close the draft phase.

    Sets is_draft_time=False.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in DRAFT phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "DRAFT":
        raise ValueError(f"Cannot end draft: currently in {phase}")

    return update_timestamp({"is_draft_time": False}, broadcast=True)


def start_recruiting() -> bool:
    """
    Open the recruiting window.

    Sets is_recruiting_locked=False and recruiting_synced=False.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in OFFSEASON phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "OFFSEASON":
        raise ValueError(f"Cannot start recruiting: currently in {phase}")

    return update_timestamp(
        {"is_recruiting_locked": False, "recruiting_synced": False},
        broadcast=True,
    )


def end_recruiting() -> bool:
    """
    Close the recruiting window.

    Sets is_recruiting_locked=True and recruiting_synced=True.

    Returns:
        True if succeeded.

    Raises:
        ValueError: If not in RECRUITING phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "RECRUITING":
        raise ValueError(f"Cannot end recruiting: currently in {phase}")

    return update_timestamp(
        {"is_recruiting_locked": True, "recruiting_synced": True},
        broadcast=True,
    )


def start_new_season(league_year_id: int) -> Dict[str, Any]:
    """
    Transition from offseason to a new regular season.

    Steps:
      1. Run year-start financial books
      2. Reset timestamp to week 1, regular season

    Args:
        league_year_id: The new league year id.

    Returns:
        Summary dict.

    Raises:
        ValueError: If not in OFFSEASON phase.
    """
    ts = get_current_timestamp()
    if ts is None:
        raise ValueError("No timestamp state found")

    phase = get_current_phase(ts)
    if phase != "OFFSEASON":
        raise ValueError(
            f"Cannot start new season: currently in {phase}. "
            "All offseason phases (FA, draft, recruiting) must be completed first."
        )

    engine = get_engine()
    league_year = ts.get("Season", 2026)
    summary: Dict[str, Any] = {"phase_transition": "OFFSEASON -> REGULAR_SEASON"}

    # 1. Year-start financial books
    try:
        from financials.books import run_year_start_books
        books_result = run_year_start_books(engine, league_year)
        summary["year_start_books"] = books_result
        logger.info(f"Year-start books: {books_result}")
    except Exception as e:
        logger.exception("start_new_season: year-start books failed")
        summary["year_start_books_error"] = str(e)

    # 2. Reset to regular season
    new_season = league_year + 1
    update_timestamp(
        {
            "season": new_season,
            "season_id": league_year_id,
            "week": 1,
            "is_offseason": False,
            "is_free_agency_locked": True,
            "is_draft_time": False,
            "is_recruiting_locked": True,
            "free_agency_round": 0,
            "run_games": False,
            "games_a_ran": False,
            "games_b_ran": False,
            "games_c_ran": False,
            "games_d_ran": False,
            "gm_actions_completed": False,
            "recruiting_synced": True,
        },
        broadcast=True,
    )
    summary["new_season"] = new_season
    summary["timestamp_updated"] = True

    logger.info(f"New season {new_season} started (league_year_id={league_year_id})")
    return summary


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
            # Get current week and season (year number for financial books)
            row = conn.execute(
                select(ts_table.c.week, ts_table.c.season).where(ts_table.c.id == 1)
            ).first()

            if not row:
                logger.error("No timestamp row found")
                return False

            current_week = row[0]
            league_year = row[1]
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

            # Decrement injury weeks and clean up healed players
            try:
                healed = _tick_injuries(engine)
                logger.info(f"Injury tick for week {current_week}: {healed} players healed")
            except Exception as e:
                logger.exception(f"Injury tick failed for week {current_week}, continuing")

            # Run financial books for the completed week
            try:
                from financials.books import run_week_books
                books_result = run_week_books(engine, league_year, current_week)
                logger.info(f"Week books for week {current_week}: {books_result}")
            except Exception as e:
                logger.exception(f"Week books failed for week {current_week}, continuing")

            # Refresh listed positions for all teams
            try:
                from sqlalchemy import text as _text
                from services.listed_position import refresh_all_teams
                ly_row = conn.execute(
                    _text("SELECT id FROM league_years WHERE league_year = :yr"),
                    {"yr": league_year},
                ).first()
                if ly_row:
                    refresh_all_teams(conn, int(ly_row[0]))
                    conn.commit()
                    logger.info(f"Listed positions refreshed for week {new_week}")
            except Exception:
                logger.exception("Listed position refresh failed, continuing")

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


def _tick_injuries(engine) -> int:
    """
    Decrement weeks_remaining on all injured players by 1.
    Players who reach 0 are healed: their player_injury_state row is deleted
    (historical data lives in player_injury_events).

    Also decrements weeks_remaining on the corresponding player_injury_events row.

    Returns:
        Number of players healed this tick.
    """
    from sqlalchemy import text as sa_text

    with engine.begin() as conn:
        # Decrement weeks on injury events that are still active
        conn.execute(sa_text("""
            UPDATE player_injury_events pie
            JOIN player_injury_state pis ON pis.current_event_id = pie.id
            SET pie.weeks_remaining = GREATEST(pie.weeks_remaining - 1, 0)
            WHERE pis.status = 'injured' AND pie.weeks_remaining > 0
        """))

        # Decrement weeks on injury state
        conn.execute(sa_text("""
            UPDATE player_injury_state
            SET weeks_remaining = GREATEST(weeks_remaining - 1, 0)
            WHERE status = 'injured' AND weeks_remaining > 0
        """))

        # Delete healed players (weeks_remaining hit 0)
        result = conn.execute(sa_text("""
            DELETE FROM player_injury_state
            WHERE status = 'injured' AND weeks_remaining <= 0
        """))
        healed = result.rowcount

        # Also clean up any stale healthy rows (shouldn't exist, but belt-and-suspenders)
        conn.execute(sa_text("""
            DELETE FROM player_injury_state
            WHERE status = 'healthy'
        """))

    return healed
