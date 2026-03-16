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
    Parse a malus JSON blob into {attr_name: multiplier, ...}.

    All values are **multiplicative** factors (0.7 = keep 70%, 0.0 = zeroed).

    Handles two formats:
      - Flat (normalized):  {"speed": 0.7, "stamina_pct": 0.0}
      - Nested (engine):    {"speed": {"original": 75, "modified": 52.5, "multiplier": 0.7}}
    """
    if not raw:
        return {}

    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}

    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for attr, val in data.items():
            if isinstance(val, dict):
                # Nested engine format — extract multiplier
                m = val.get("multiplier")
                if m is not None:
                    try:
                        out[attr] = float(m)
                    except (TypeError, ValueError):
                        continue
            else:
                try:
                    out[attr] = float(val)
                except (TypeError, ValueError):
                    continue
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

      - ALL active injury events (weeks_remaining > 0)
      - All career_injuries.career_malus_json rows

    All values are **multiplicative** factors.  Multiple injuries are combined
    by multiplying their factors together (e.g. two injuries each with
    speed=0.7 → combined speed=0.49).

    Returns:
      {
        player_id: {
          "speed": 0.49,
          "contact": 0.7,
          "stamina_pct": 0.0,
          ...
        },
        ...
      }

    Only attributes with a factor != 1.0 are included.
    """
    ids = [int(pid) for pid in player_ids]
    if not ids:
        return {}

    tables = _get_tables()
    state = tables["player_injury_state"]
    events = tables["player_injury_events"]
    career = tables["career_injuries"]

    # 1) Find which players are currently injured
    state_rows = (
        conn.execute(
            select(
                state.c.player_id,
                state.c.status,
            ).where(
                state.c.player_id.in_(ids),
                state.c.status == "injured",
            )
        )
        .mappings()
        .all()
    )

    injured_pids = [int(row["player_id"]) for row in state_rows]

    # 2) Load malus_json for ALL active injury events (weeks_remaining > 0)
    #    for those injured players — not just the single current_event_id.
    event_malus_by_player: Dict[int, list] = {}
    if injured_pids:
        event_rows = (
            conn.execute(
                select(
                    events.c.player_id,
                    events.c.malus_json,
                ).where(
                    events.c.player_id.in_(injured_pids),
                    events.c.weeks_remaining > 0,
                )
            )
            .mappings()
            .all()
        )
        for row in event_rows:
            pid = int(row["player_id"])
            parsed = _parse_malus_json(row["malus_json"])
            if parsed:
                event_malus_by_player.setdefault(pid, []).append(parsed)

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

    # Apply ALL active event maluses — multiplicative combination.
    # Each malus value is a factor (0.7 = keep 70%).  Multiple injuries
    # stack by multiplication: two 0.7 factors → 0.49.
    for pid, malus_list in event_malus_by_player.items():
        dst = out.setdefault(pid, {})
        for effects in malus_list:
            for attr, factor in effects.items():
                dst[attr] = dst.get(attr, 1.0) * factor

    # Apply career malus (also multiplicative)
    for row in career_rows:
        pid = int(row["player_id"])
        effects = _parse_malus_json(row["career_malus_json"])
        if not effects:
            continue
        dst = out.setdefault(pid, {})
        for attr, factor in effects.items():
            dst[attr] = dst.get(attr, 1.0) * factor

    # Strip out no-op entries (factor == 1.0) to keep return value clean
    for pid in list(out):
        out[pid] = {k: v for k, v in out[pid].items() if v != 1.0}

    return out


def get_active_injury_malus(conn, player_id: int) -> Dict[str, float]:
    """
    Convenience single-player wrapper around the bulk function.

    Existing call sites (e.g. single-player paths) can continue to use this.
    """
    res = get_active_injury_malus_bulk(conn, [player_id])
    return res.get(int(player_id), {})
