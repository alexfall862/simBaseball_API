# services/injuries.py

from __future__ import annotations

import json
from typing import Dict, Any, Iterable

from sqlalchemy import MetaData, Table, select, and_

from db import get_engine

# -------------------------------------------------------------------
# Table reflection + cache
# -------------------------------------------------------------------

_METADATA = None
_TABLES = None


def _get_tables():
    """
    Reflect and cache the injury-related tables.

    We expect at least:

      player_injury_state(
        player_id BIGINT UNSIGNED PK,
        status ENUM('healthy','injured'),
        current_event_id BIGINT UNSIGNED NULL,
        weeks_remaining INT,
        last_updated_at DATETIME
      )

      player_injury_events(
        id BIGINT UNSIGNED PK,
        player_id BIGINT UNSIGNED,
        injury_type_id BIGINT UNSIGNED,
        league_year_id BIGINT UNSIGNED NULL,
        gamelist_id BIGINT UNSIGNED NULL,
        weeks_assigned INT,
        weeks_remaining INT,
        malus_json JSON NOT NULL
      )

      career_injuries(
        id BIGINT UNSIGNED PK,
        player_id BIGINT UNSIGNED,
        origin_event_id BIGINT UNSIGNED,
        career_malus_json JSON NOT NULL
      )
    """
    global _METADATA, _TABLES
    if _TABLES is not None:
        return _TABLES

    engine = get_engine()
    md = MetaData()

    player_injury_state = Table("player_injury_state", md, autoload_with=engine)
    player_injury_events = Table("player_injury_events", md, autoload_with=engine)
    career_injuries = Table("career_injuries", md, autoload_with=engine)

    _METADATA = md
    _TABLES = {
        "player_injury_state": player_injury_state,
        "player_injury_events": player_injury_events,
        "career_injuries": career_injuries,
    }
    return _TABLES


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _parse_malus_json(raw) -> Dict[str, float]:
    """
    Parse a malus JSON blob into {attr_name: delta_float, ...}.

    We assume malus_json/career_malus_json are already realized *additive* deltas
    keyed by simbbPlayers column names, e.g.:

      {"contact_base": -5.0, "power_base": -2.5}

    If your malus_json uses a slightly different shape, adapt this function.
    """
    if not raw:
        return {}

    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}

    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for attr, delta in data.items():
            try:
                d = float(delta)
            except (TypeError, ValueError):
                continue
            out[attr] = out.get(attr, 0.0) + d
    return out


# -------------------------------------------------------------------
# Public API: bulk + single
# -------------------------------------------------------------------

def get_active_injury_malus_bulk(
    conn,
    player_ids: Iterable[int],
) -> Dict[int, Dict[str, float]]:
    """
    Bulk-load active injury maluses for many players.

    For each player_id, we combine:

      - Their *current* injury event malus (if status='injured' and weeks_remaining > 0)
      - All career_injuries.career_malus_json rows

    Returns:
      {
        player_id: {
          "contact_base": -5.0,
          "power_base": -2.0,
          ...
        },
        ...
      }
    """
    ids = [int(pid) for pid in player_ids]
    if not ids:
        return {}

    tables = _get_tables()
    state = tables["player_injury_state"]
    events = tables["player_injury_events"]
    career = tables["career_injuries"]

    # 1) Current state rows for injured players
    state_rows = (
        conn.execute(
            select(
                state.c.player_id,
                state.c.status,
                state.c.current_event_id,
                state.c.weeks_remaining,
            ).where(state.c.player_id.in_(ids))
        )
        .mappings()
        .all()
    )

    # Map player_id -> current_event_id for active injuries
    active_event_by_player: Dict[int, int] = {}
    active_event_ids: set[int] = set()

    for row in state_rows:
        if row["status"] != "injured":
            continue
        # Defensive: also check weeks_remaining > 0
        try:
            w = int(row["weeks_remaining"])
        except (TypeError, ValueError):
            w = 0
        if w <= 0:
            continue

        ev_id = row["current_event_id"]
        if ev_id is None:
            continue

        pid = int(row["player_id"])
        ev_id = int(ev_id)
        active_event_by_player[pid] = ev_id
        active_event_ids.add(ev_id)

    # 2) Load malus_json for those events
    event_malus_by_id: Dict[int, Dict[str, float]] = {}
    if active_event_ids:
        event_rows = (
            conn.execute(
                select(events.c.id, events.c.malus_json).where(
                    events.c.id.in_(list(active_event_ids))
                )
            )
            .mappings()
            .all()
        )
        for row in event_rows:
            ev_id = int(row["id"])
            event_malus_by_id[ev_id] = _parse_malus_json(row["malus_json"])

    # 3) Load career injuries (always apply)
    career_rows = (
        conn.execute(
            select(career.c.player_id, career.c.career_malus_json).where(
                career.c.player_id.in_(ids)
            )
        )
        .mappings()
        .all()
    )

    out: Dict[int, Dict[str, float]] = {pid: {} for pid in ids}

    # Apply current event malus
    for pid, ev_id in active_event_by_player.items():
        effects = event_malus_by_id.get(ev_id) or {}
        if not effects:
            continue
        dst = out.setdefault(pid, {})
        for attr, delta in effects.items():
            dst[attr] = dst.get(attr, 0.0) + delta

    # Apply career malus
    for row in career_rows:
        pid = int(row["player_id"])
        effects = _parse_malus_json(row["career_malus_json"])
        if not effects:
            continue
        dst = out.setdefault(pid, {})
        for attr, delta in effects.items():
            dst[attr] = dst.get(attr, 0.0) + delta

    return out


def get_active_injury_malus(conn, player_id: int) -> Dict[str, float]:
    """
    Convenience single-player wrapper around the bulk function.

    Existing call sites (e.g. single-player paths) can continue to use this.
    """
    res = get_active_injury_malus_bulk(conn, [player_id])
    return res.get(int(player_id), {})
