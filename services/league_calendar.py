"""
League calendar helpers: which league year / season a given operation
belongs to.

Three identifier spaces exist in the schema and are easy to confuse:

  * ``league_years.id``          - the API's ``league_year_id`` (L)
  * ``league_years.league_year`` - the calendar year value (Y: 2026, 2027, ...)
  * ``seasons.id``               - what ``gamelist.season`` and
                                   ``game_results.season`` store

All three were 1 / 2026 / 1 for the first season, which hid several places
that filtered one with another. Resolve through these helpers instead of
passing an id across spaces.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)


def resolve_league_year(conn, league_year_id: int) -> int:
    """league_years.id -> calendar year value. Raises if the row is missing."""
    row = conn.execute(
        text("SELECT league_year FROM league_years WHERE id = :id"),
        {"id": int(league_year_id)},
    ).first()
    if not row:
        raise ValueError(f"league_year_id {league_year_id} not found")
    return int(row[0])


def resolve_league_year_id(conn, league_year: int) -> Optional[int]:
    """Calendar year value -> league_years.id, or None if not initialized."""
    row = conn.execute(
        text("SELECT id FROM league_years WHERE league_year = :yr"),
        {"yr": int(league_year)},
    ).first()
    return int(row[0]) if row else None


def resolve_season_id(conn, league_year_id: int) -> int:
    """
    league_years.id -> seasons.id (the value stored in gamelist.season and
    game_results.season). Raises if either row is missing.
    """
    row = conn.execute(text("""
        SELECT s.id
        FROM league_years ly
        JOIN seasons s ON s.year = ly.league_year
        WHERE ly.id = :id
        LIMIT 1
    """), {"id": int(league_year_id)}).first()
    if not row:
        raise ValueError(
            f"No seasons row matches league_year_id {league_year_id}"
        )
    return int(row[0])


def season_id_sql(param: str) -> str:
    """
    SQL fragment yielding ``seasons.id`` for the ``league_years.id`` bound to
    ``:<param>``. Use it wherever a query filters ``gamelist.season`` or
    ``game_results.season`` by a league_year_id::

        "WHERE gr.season = " + season_id_sql("lyid") + " AND ..."
    """
    return (
        f"(SELECT s.id FROM seasons s JOIN league_years ly "
        f"ON ly.league_year = s.year WHERE ly.id = :{param} LIMIT 1)"
    )


def season_id_or_none(conn, league_year_id: Optional[int]) -> Optional[int]:
    """Lenient variant for optional query filters: None in, None out."""
    if league_year_id is None:
        return None
    try:
        return resolve_season_id(conn, league_year_id)
    except ValueError:
        return None


def is_offseason(conn) -> bool:
    row = conn.execute(
        text("SELECT is_offseason FROM timestamp_state WHERE id = 1")
    ).first()
    return bool(row and row[0])


def resolve_signing_year(conn, league_year_id: int) -> Tuple[int, int]:
    """
    Return ``(league_year_id, league_year)`` that a contract signed *now*
    belongs to: the sim calendar's current year, or the requested year if
    that is later.

    End-season moves the calendar to the new league year immediately, so the
    whole offseason (free agency, draft, recruiting) already runs under the
    season the contracts are for. This helper exists for callers that still
    pass the id of the season that just finished (a stale frontend context,
    an admin script): ``contracts.leagueYearSigned`` must be the upcoming
    year or the weekly books (which map salary by ``leagueYearSigned + year
    - 1``) never pay year 1 of the deal.
    """
    requested_year = resolve_league_year(conn, league_year_id)

    ts = conn.execute(
        text("SELECT season FROM timestamp_state WHERE id = 1")
    ).first()
    if not ts or ts[0] is None:
        return int(league_year_id), requested_year

    calendar_year = int(ts[0])
    if requested_year >= calendar_year:
        return int(league_year_id), requested_year

    cal_id = resolve_league_year_id(conn, calendar_year)
    if cal_id is None:
        raise ValueError(
            f"The sim calendar is on {calendar_year} but league_years has no "
            f"row for it; cannot book a contract against it."
        )
    return cal_id, calendar_year


def pricing_stats_league_year_id(conn, league_year_id: int) -> int:
    """
    The league year whose *stats* should price a contract requested for
    ``league_year_id``: the latest year, no later than the requested one,
    that has any batting stats.

    After end-season the calendar is already on the new year, which has no
    stats until week 1 is played; demands, market WAR and arbitration must
    keep using the season that was just completed. Mid-season the requested
    year has (partial) stats and is used as-is.
    """
    requested_year = resolve_league_year(conn, league_year_id)
    row = conn.execute(text("""
        SELECT ly.id
        FROM league_years ly
        WHERE ly.league_year <= :yr
          AND EXISTS (SELECT 1 FROM player_batting_stats bs
                      WHERE bs.league_year_id = ly.id)
        ORDER BY ly.league_year DESC
        LIMIT 1
    """), {"yr": requested_year}).first()
    return int(row[0]) if row else int(league_year_id)
