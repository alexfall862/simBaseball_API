# services/stamina.py

from __future__ import annotations

from typing import Dict, Iterable

from sqlalchemy import MetaData, Table, select, and_

from db import get_engine

# -------------------------------------------------------------------
# Table reflection + cache
# -------------------------------------------------------------------

_METADATA = None
_TABLES = None


def _get_tables():
    """
    Reflect and cache the stamina-related table(s).

    Uses player_fatigue_state as defined in the DB:

      player_fatigue_state(
        player_id BIGINT UNSIGNED,
        league_year_id BIGINT UNSIGNED,
        stamina INT,
        last_game_id BIGINT UNSIGNED NULL,
        last_week_id BIGINT UNSIGNED NULL,
        last_updated_at DATETIME,
        PRIMARY KEY (player_id, league_year_id)
      )
    """
    global _METADATA, _TABLES
    if _TABLES is not None:
        return _TABLES

    engine = get_engine()
    md = MetaData()

    player_fatigue_state = Table("player_fatigue_state", md, autoload_with=engine)

    _METADATA = md
    _TABLES = {
        "player_fatigue_state": player_fatigue_state,
    }
    return _TABLES


def _clamp_stamina(val) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return 100
    if n < 0:
        return 0
    if n > 100:
        return 100
    return n


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def get_effective_stamina(conn, player_id: int, league_year_id: int) -> int:
    """
    Return the current stamina (0–100) for a single player in a given league_year.

    If there is no row in player_fatigue_state, treat the player as fully rested (100).

    This is used by:
      - rotation.pick_starting_pitcher
      - anywhere else that needs a single-player stamina query.
    """
    tables = _get_tables()
    fatigue = tables["player_fatigue_state"]

    row = (
        conn.execute(
            select(fatigue.c.stamina).where(
                and_(
                    fatigue.c.player_id == int(player_id),
                    fatigue.c.league_year_id == int(league_year_id),
                )
            )
        )
        .first()
    )

    if not row:
        return 100

    return _clamp_stamina(row[0])


def get_effective_stamina_bulk(
    conn,
    player_ids: Iterable[int],
    league_year_id: int,
) -> Dict[int, int]:
    """
    Bulk version of get_effective_stamina using a single IN() query.

    Returns:
      {player_id: stamina_int}

    Players with no row in player_fatigue_state are treated as fully rested (100).

    This is used by build_team_game_side to attach stamina for all roster players.
    """
    ids = [int(pid) for pid in player_ids]
    if not ids:
        return {}

    tables = _get_tables()
    fatigue = tables["player_fatigue_state"]

    rows = (
        conn.execute(
            select(fatigue.c.player_id, fatigue.c.stamina).where(
                and_(
                    fatigue.c.league_year_id == int(league_year_id),
                    fatigue.c.player_id.in_(ids),
                )
            )
        )
        .mappings()
        .all()
    )

    # Default fully rested unless we find a row
    out: Dict[int, int] = {pid: 100 for pid in ids}

    for row in rows:
        pid = int(row["player_id"])
        out[pid] = _clamp_stamina(row["stamina"])

    return out
