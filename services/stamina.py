# services/stamina.py

import logging
from typing import Iterable, Dict, Any

from sqlalchemy import MetaData, Table, select, and_
from sqlalchemy.sql import func

from db import get_engine
from rosters import _get_tables as _get_roster_tables
from services.injuries import get_active_injury_malus

logger = logging.getLogger(__name__)

_metadata = None
_stamina_tables = None


def _get_stamina_tables():
    """
    Reflect and cache player_fatigue_state and players (for durability).
    """
    global _metadata, _stamina_tables
    if _stamina_tables is not None:
        return _stamina_tables

    engine = get_engine()
    md = MetaData()

    fatigue = Table("player_fatigue_state", md, autoload_with=engine)
    players = _get_roster_tables()["players"]

    _metadata = md
    _stamina_tables = {
        "fatigue": fatigue,
        "players": players,
    }
    return _stamina_tables


def _clamp_stamina(value: float) -> int:
    return max(0, min(int(round(value)), 100))


def get_effective_stamina(conn, player_id: int, league_year_id: int) -> int:
    """
    Return the final stamina value (0–100) for a player going into this game.

    Logic:
      - Base stamina is from player_fatigue_state (player_id, league_year_id),
        defaulting to 100 if no row exists yet.
      - Injury malus JSON may contain a 'stamina_delta' key that is added on top.
      - Result is clamped to [0, 100].
    """
    tables = _get_stamina_tables()
    fatigue = tables["fatigue"]

    stmt = (
        select(fatigue.c.stamina)
        .where(
            and_(
                fatigue.c.player_id == player_id,
                fatigue.c.league_year_id == league_year_id,
            )
        )
    )
    base_stamina = conn.execute(stmt).scalar_one_or_none()
    if base_stamina is None:
        base_stamina = 100

    malus = get_active_injury_malus(conn, player_id)
    stamina_delta = float(malus.get("stamina_delta", 0.0))

    final_stamina = _clamp_stamina(base_stamina + stamina_delta)
    return final_stamina


def apply_game_usage_fatigue(
    conn,
    league_year_id: int,
    usage_rows: Iterable[Dict[str, Any]],
) -> None:
    """
    Apply fatigue after a canonical game based on player usage.

    usage_rows is expected to be an iterable of dicts like:
      {
        "player_id": int,
        "role": "starter" | "reliever" | "position",
        "innings_pitched": float,
        "plate_appearances": int,
      }

    This is a first-pass heuristic; tune once engine usage data is finalized.
    """
    tables = _get_stamina_tables()
    fatigue = tables["fatigue"]

    for usage in usage_rows:
        pid = usage["player_id"]
        role = (usage.get("role") or "").lower()
        ip = float(usage.get("innings_pitched", 0.0) or 0.0)
        pa = int(usage.get("plate_appearances", 0) or 0)

        if role == "starter":
            drain = 25 + ip * 5  # e.g. 5 IP → 50 drain
        elif role == "reliever":
            drain = 10 + ip * 4
        else:
            # Position players: modest drain scaled by PA
            drain = min(25, 5 + pa * 1.5)

        drain = max(0, drain)

        stmt = (
            select(fatigue.c.stamina)
            .where(
                and_(
                    fatigue.c.player_id == pid,
                    fatigue.c.league_year_id == league_year_id,
                )
            )
        )
        current = conn.execute(stmt).scalar_one_or_none()
        if current is None:
            current = 100

        new_val = _clamp_stamina(current - drain)

        updated = conn.execute(
            fatigue.update()
            .where(
                and_(
                    fatigue.c.player_id == pid,
                    fatigue.c.league_year_id == league_year_id,
                )
            )
            .values(
                stamina=new_val,
                last_game_id=None,  # set if you want
                last_week_id=None,
                last_updated_at=func.now(),
            )
        )
        if updated.rowcount == 0:
            conn.execute(
                fatigue.insert().values(
                    player_id=pid,
                    league_year_id=league_year_id,
                    stamina=new_val,
                    last_game_id=None,
                    last_week_id=None,
                )
            )


def regen_weekly_stamina(conn, league_year_id: int) -> None:
    """
    Weekly regen step, to be called when you advance the league week.

    Simple v1 logic:
      - Base regen amount by durability:
          'Iron Man'   -> +40
          'Normal'     -> +30
          'Needs Rest' -> +20
      - You can extend this to factor in actual games played this week.
    """
    tables = _get_stamina_tables()
    fatigue = tables["fatigue"]
    players = tables["players"]

    DUR_REGEN = {
        "Iron Man": 40,
        "Normal": 30,
        "Needs Rest": 20,
    }

    stmt = (
        select(
            fatigue.c.player_id,
            fatigue.c.stamina,
            players.c.durability,
        )
        .select_from(
            fatigue.join(players, fatigue.c.player_id == players.c.id)
        )
        .where(fatigue.c.league_year_id == league_year_id)
    )

    rows = conn.execute(stmt).mappings().all()
    for row in rows:
        pid = row["player_id"]
        stamina = int(row["stamina"])
        durability = (row["durability"] or "").strip()

        regen = DUR_REGEN.get(durability, 30)
        new_val = _clamp_stamina(stamina + regen)

        conn.execute(
            fatigue.update()
            .where(
                and_(
                    fatigue.c.player_id == pid,
                    fatigue.c.league_year_id == league_year_id,
                )
            )
            .values(
                stamina=new_val,
                last_week_id=None,
                last_updated_at=func.now(),
            )
        )
