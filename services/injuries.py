# services/injuries.py

import json
import logging
import random
from typing import Dict, Any

from sqlalchemy import MetaData, Table, select, and_, update, insert
from sqlalchemy.sql import func

from db import get_engine
from rosters import _get_tables as _get_roster_tables

logger = logging.getLogger(__name__)

_metadata = None
_injury_tables = None

# Tunables for lingering injuries
LINGERING_INJURY_PROB = 0.25        # 25% chance to create a career injury
LINGERING_SEVERITY_FRACTION = 0.25  # 25% of the acute malus magnitude


def _get_injury_tables():
    """
    Reflect and cache the injury-related tables:

      - injury_types
      - player_injury_events
      - career_injuries
      - player_injury_state
    """
    global _metadata, _injury_tables
    if _injury_tables is not None:
        return _injury_tables

    engine = get_engine()
    md = MetaData()

    injury_types = Table("injury_types", md, autoload_with=engine)
    player_injury_events = Table("player_injury_events", md, autoload_with=engine)
    career_injuries = Table("career_injuries", md, autoload_with=engine)
    player_injury_state = Table("player_injury_state", md, autoload_with=engine)

    _metadata = md
    _injury_tables = {
        "injury_types": injury_types,
        "events": player_injury_events,
        "career": career_injuries,
        "state": player_injury_state,
    }
    return _injury_tables


def _normalize_json(value) -> Dict[str, Any]:
    """
    Ensure we always get a dict from a JSON column that might come back as
    a Python dict or a JSON-encoded string.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


# -------------------------------------------------------------------
# READ PATH: combine acute + career maluses for a player
# -------------------------------------------------------------------

def get_active_injury_malus(conn, player_id: int) -> Dict[str, float]:
    """
    Return a combined malus dict for a player, summing:

      - all active player_injury_events (weeks_remaining > 0)
      - all career_injuries (permanent lingerers)

    The returned dict maps attribute names to numeric deltas, e.g.:

      {
        "power_base": -8.3,
        "contact_base": -3.1,
        "stamina_delta": -100
      }

    This dict can then be applied to the player's base attributes and stamina.
    """
    tables = _get_injury_tables()
    events = tables["events"]
    career = tables["career"]

    total: Dict[str, float] = {}

    # --- Active events ---
    evt_stmt = (
        select(events.c.malus_json)
        .where(
            and_(
                events.c.player_id == player_id,
                events.c.weeks_remaining > 0,
            )
        )
    )
    for row in conn.execute(evt_stmt):
        data = _normalize_json(row.malus_json)
        for key, val in data.items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            total[key] = total.get(key, 0.0) + num

    # --- Career injuries ---
    car_stmt = (
        select(career.c.career_malus_json)
        .where(career.c.player_id == player_id)
    )
    for row in conn.execute(car_stmt):
        data = _normalize_json(row.career_malus_json)
        for key, val in data.items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            total[key] = total.get(key, 0.0) + num

    return total


# -------------------------------------------------------------------
# WEEKLY PROGRESSION: decrement weeks_remaining, spawn career injuries
# -------------------------------------------------------------------

def progress_injuries_one_week(conn, league_year_id: int | None = None) -> None:
    """
    Advance all current injuries by one week.

    - Decrements weeks_remaining on player_injury_events + player_injury_state.
    - When weeks_remaining reaches 0:
        * Marks player_injury_state as healthy.
        * If injury_types.career_eligible is true:
            - Rolls a chance for a lingering effect.
            - If triggered, inserts a career_injuries row with a scaled malus_json.

    `league_year_id` is currently unused here but kept for future filtering.
    """
    tables = _get_injury_tables()
    events = tables["events"]
    state = tables["state"]
    injury_types = tables["injury_types"]
    career = tables["career"]

    stmt = (
        select(
            state.c.player_id,
            state.c.current_event_id,
            state.c.weeks_remaining.label("state_weeks_remaining"),
            events.c.id.label("event_id"),
            events.c.weeks_remaining.label("event_weeks_remaining"),
            events.c.malus_json,
            injury_types.c.id.label("injury_type_id"),
            injury_types.c.career_eligible,
        )
        .select_from(
            state.join(events, state.c.current_event_id == events.c.id)
                 .join(injury_types, events.c.injury_type_id == injury_types.c.id)
        )
        .where(state.c.weeks_remaining > 0)
    )

    rows = conn.execute(stmt).mappings().all()
    if not rows:
        return

    for row in rows:
        player_id = row["player_id"]
        event_id = row["event_id"]
        state_weeks = row["state_weeks_remaining"]
        event_weeks = row["event_weeks_remaining"]
        career_eligible = bool(row["career_eligible"])
        malus_json = _normalize_json(row["malus_json"])

        new_state_weeks = max(int(state_weeks) - 1, 0)
        new_event_weeks = max(int(event_weeks) - 1, 0)

        conn.execute(
            events.update()
            .where(events.c.id == event_id)
            .values(weeks_remaining=new_event_weeks)
        )

        conn.execute(
            state.update()
            .where(state.c.player_id == player_id)
            .values(
                weeks_remaining=new_state_weeks,
                last_updated_at=func.now(),
            )
        )

        if new_state_weeks > 0:
            continue

        # Injury resolved
        conn.execute(
            state.update()
            .where(state.c.player_id == player_id)
            .values(
                status="healthy",
                current_event_id=None,
                weeks_remaining=0,
                last_updated_at=func.now(),
            )
        )

        if not career_eligible:
            continue

        if random.random() >= LINGERING_INJURY_PROB:
            continue

        # Scale down acute malus to create a career injury
        career_malus: Dict[str, float] = {}
        for key, val in malus_json.items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            scaled = num * LINGERING_SEVERITY_FRACTION
            if scaled != 0:
                career_malus[key] = scaled

        if not career_malus:
            continue

        conn.execute(
            career.insert().values(
                player_id=player_id,
                origin_event_id=event_id,
                career_malus_json=json.dumps(career_malus),
            )
        )

        logger.info(
            "Created career injury for player %s from event %s with malus %s",
            player_id,
            event_id,
            career_malus,
        )


# -------------------------------------------------------------------
# EVENT CREATION: from injury_types.impact_template_json -> malus_json
# -------------------------------------------------------------------

def create_injury_event_for_player(
    conn,
    player_id: int,
    injury_type_id: int,
    league_year_id: int | None = None,
    gamelist_id: int | None = None,
) -> int:
    """
    Create a player_injury_event for a player using the injury_type's
    impact_template_json and the player's current *_base attributes.

    injury_types.impact_template_json is expected to look like:

      {
        "contact":     {"min_pct": 0.5, "max_pct": 0.8},
        "stamina_pct": {"min_pct": 1.0, "max_pct": 1.0}
      }

    We interpret that as:
      - For "contact": malus = -pct * contact_base (applied as 'contact_base' delta)
      - For "stamina_pct": malus = -pct * 100 (stored as 'stamina_delta')

    Returns the new event_id.
    """
    tables = _get_injury_tables()
    injury_types = tables["injury_types"]
    events = tables["events"]
    state = tables["state"]

    # Load injury type
    it_row = conn.execute(
        select(injury_types).where(injury_types.c.id == injury_type_id)
    ).mappings().first()
    if not it_row:
        raise ValueError(f"injury_type_id {injury_type_id} not found")

    impact_template = _normalize_json(it_row["impact_template_json"])

    # Load player row
    roster_tables = _get_roster_tables()
    players = roster_tables["players"]

    p_row = conn.execute(
        select(players).where(players.c.id == player_id)
    ).mappings().first()
    if not p_row:
        raise ValueError(f"Player {player_id} not found in simbbPlayers")

    # Duration in weeks, use triangular distribution around mean_weeks
    min_weeks = int(it_row["min_weeks"])
    mean_weeks = int(it_row["mean_weeks"])
    max_weeks = int(it_row["max_weeks"])

    if min_weeks == max_weeks:
        weeks_assigned = min_weeks
    else:
        weeks_assigned = int(
            round(random.triangular(min_weeks, max_weeks, mean_weeks))
        )
        weeks_assigned = max(min_weeks, min(weeks_assigned, max_weeks))

    # Build concrete malus_json from template for this player
    malus: Dict[str, float] = {}

    for key, cfg in impact_template.items():
        cfg = cfg or {}
        min_pct = float(cfg.get("min_pct", 0.0))
        max_pct = float(cfg.get("max_pct", 0.0))
        if max_pct < min_pct:
            min_pct, max_pct = max_pct, min_pct

        pct = random.uniform(min_pct, max_pct)

        if key == "stamina_pct":
            stamina_delta = -pct * 100.0
            malus["stamina_delta"] = malus.get("stamina_delta", 0.0) + stamina_delta
            continue

        # Attribute like "contact", "power", etc.
        base_col = key if key.endswith("_base") else f"{key}_base"
        base_val = p_row.get(base_col)
        try:
            base_num = float(base_val) if base_val is not None else 0.0
        except (TypeError, ValueError):
            base_num = 0.0

        delta = -pct * base_num
        malus[base_col] = malus.get(base_col, 0.0) + delta

    # Insert event
    evt_result = conn.execute(
        events.insert().values(
            player_id=player_id,
            injury_type_id=injury_type_id,
            league_year_id=league_year_id,
            gamelist_id=gamelist_id,
            weeks_assigned=weeks_assigned,
            weeks_remaining=weeks_assigned,
            malus_json=json.dumps(malus),
        )
    )
    event_id = evt_result.inserted_primary_key[0]

    # Initialize or update player_injury_state
    st_row = conn.execute(
        select(state).where(state.c.player_id == player_id)
    ).mappings().first()

    if st_row is None or st_row["status"] == "healthy":
        conn.execute(
            state.insert().values(
                player_id=player_id,
                status="injured",
                current_event_id=event_id,
                weeks_remaining=weeks_assigned,
            )
        )
    else:
        conn.execute(
            state.update()
            .where(state.c.player_id == player_id)
            .values(
                status="injured",
                current_event_id=event_id,
                weeks_remaining=weeks_assigned,
            )
        )

    return event_id
