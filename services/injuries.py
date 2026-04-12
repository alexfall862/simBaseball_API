# services/injuries.py

from __future__ import annotations

import json
import logging
from typing import Dict, Any, Iterable

from sqlalchemy import MetaData, Table, select, and_

from db import get_engine

logger = logging.getLogger(__name__)

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

    logger.debug(
        "get_active_injury_malus_bulk: %d injured players, %d have event malus data",
        len(injured_pids), len(event_malus_by_player),
    )

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

    non_empty = {pid: v for pid, v in out.items() if v}
    logger.debug(
        "get_active_injury_malus_bulk: returning non-empty malus for %d players",
        len(non_empty),
    )

    return out


def get_active_injury_malus(conn, player_id: int) -> Dict[str, float]:
    """
    Convenience single-player wrapper around the bulk function.

    Existing call sites (e.g. single-player paths) can continue to use this.
    """
    res = get_active_injury_malus_bulk(conn, [player_id])
    return res.get(int(player_id), {})


# -------------------------------------------------------------------
# Injury history (active + healed) for display
# -------------------------------------------------------------------

def get_injury_history_bulk(
    conn,
    player_ids: Iterable[int],
    league_year_id: int | None = None,
    limit_per_player: int | None = None,
) -> Dict[int, list]:
    """
    Bulk-load full injury history for a set of players.

    Unlike get_active_injury_malus_bulk, this does NOT filter on
    weeks_remaining > 0 — it returns healed injuries too, so the frontend
    can render a timeline. Ordered newest-first by event id.

    Each row is enriched with:
      - injury_name / injury_code from injury_types
      - source ('pregame' | 'ingame') from the event row itself
      - game context (season_week, season_subweek, opponent_team_id) joined
        from gamelist when gamelist_id is present
      - status: 'active' if weeks_remaining > 0 else 'healed'

    Returns:
      {
        player_id: [
          {
            "event_id": int,
            "injury_type_id": int,
            "injury_name": str,
            "injury_code": str,
            "source": "pregame" | "ingame",
            "status": "active" | "healed",
            "weeks_assigned": int,
            "weeks_remaining": int,
            "effects": {"contact": 0.7, ...},
            "gamelist_id": int | None,
            "season_week": int | None,
            "season_subweek": str | None,
            "opponent_team_id": int | None,  # opponent of the injured player's team
            "created_at": iso8601 str,
          },
          ...
        ],
        ...
      }

    Players with no events get an empty list.
    """
    from sqlalchemy import text as sa_text

    ids = [int(pid) for pid in player_ids]
    if not ids:
        return {}

    placeholders = ", ".join(f":p{i}" for i in range(len(ids)))
    params: Dict[str, Any] = {f"p{i}": pid for i, pid in enumerate(ids)}

    where_clauses = [f"pie.player_id IN ({placeholders})"]
    if league_year_id is not None:
        where_clauses.append("pie.league_year_id = :lyid")
        params["lyid"] = int(league_year_id)

    # We join gamelist twice-in-one via LEFT JOIN so we can report the
    # opponent relative to whichever side the injured player was on. The
    # injured player's team isn't stored on the event directly, so we
    # derive it via simbbPlayers.orgID → but that's not stable across team
    # moves. Simpler: just expose both home/away team ids and let the
    # frontend figure out which is the opponent.
    sql = sa_text(f"""
        SELECT
            pie.id             AS event_id,
            pie.player_id,
            pie.injury_type_id,
            pie.gamelist_id,
            pie.source,
            pie.weeks_assigned,
            pie.weeks_remaining,
            pie.malus_json,
            pie.created_at,
            it.code            AS injury_code,
            it.name            AS injury_name,
            it.timeframe       AS injury_timeframe,
            gl.season_week,
            gl.season_subweek,
            gl.home_team       AS game_home_team,
            gl.away_team       AS game_away_team
        FROM player_injury_events pie
        JOIN injury_types it ON it.id = pie.injury_type_id
        LEFT JOIN gamelist gl ON gl.id = pie.gamelist_id
        WHERE {" AND ".join(where_clauses)}
        ORDER BY pie.player_id ASC, pie.id DESC
    """)

    rows = conn.execute(sql, params).mappings().all()

    out: Dict[int, list] = {pid: [] for pid in ids}
    counts: Dict[int, int] = {}

    for r in rows:
        pid = int(r["player_id"])
        if limit_per_player is not None and counts.get(pid, 0) >= limit_per_player:
            continue
        weeks_remaining = int(r["weeks_remaining"])
        out.setdefault(pid, []).append({
            "event_id": int(r["event_id"]),
            "injury_type_id": int(r["injury_type_id"]),
            "injury_name": r["injury_name"],
            "injury_code": r["injury_code"],
            "source": r["source"] or ("pregame" if r["injury_timeframe"] == "pregame" else "ingame"),
            "status": "active" if weeks_remaining > 0 else "healed",
            "weeks_assigned": int(r["weeks_assigned"]),
            "weeks_remaining": weeks_remaining,
            "effects": _parse_malus_json(r["malus_json"]),
            "gamelist_id": int(r["gamelist_id"]) if r["gamelist_id"] is not None else None,
            "season_week": int(r["season_week"]) if r["season_week"] is not None else None,
            "season_subweek": r["season_subweek"],
            "game_home_team": int(r["game_home_team"]) if r["game_home_team"] is not None else None,
            "game_away_team": int(r["game_away_team"]) if r["game_away_team"] is not None else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] is not None else None,
        })
        counts[pid] = counts.get(pid, 0) + 1

    return out
