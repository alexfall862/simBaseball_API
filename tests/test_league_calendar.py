"""
Unit tests for services/league_calendar.py using a fake connection.

Run:  python -m pytest tests/test_league_calendar.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.league_calendar import (  # noqa: E402
    pricing_stats_league_year_id,
    resolve_league_year,
    resolve_league_year_id,
    resolve_season_id,
    resolve_signing_year,
    season_id_sql,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeConn:
    """Routes SQL by substring to canned rows; records bound params."""

    def __init__(self, league_years, calendar_year, seasons=None, years_with_stats=()):
        # league_years: {id: year}; calendar_year: timestamp_state.season
        self.league_years = league_years
        self.calendar_year = calendar_year
        self.seasons = seasons or {}
        self.years_with_stats = set(years_with_stats)
        self.calls = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "FROM timestamp_state" in sql:
            return _Result((self.calendar_year,))
        if "player_batting_stats" in sql:
            candidates = [(yr, lid) for lid, yr in self.league_years.items()
                          if yr <= params["yr"] and yr in self.years_with_stats]
            if not candidates:
                return _Result(None)
            return _Result((max(candidates)[1],))
        if "JOIN seasons s" in sql:
            yr = self.league_years.get(params["id"])
            sid = self.seasons.get(yr)
            return _Result((sid,) if sid is not None else None)
        if "FROM league_years WHERE id" in sql:
            yr = self.league_years.get(params["id"])
            return _Result((yr,) if yr is not None else None)
        if "FROM league_years WHERE league_year" in sql:
            for lid, yr in self.league_years.items():
                if yr == params["yr"]:
                    return _Result((lid,))
            return _Result(None)
        raise AssertionError(f"unexpected SQL: {sql}")


def test_resolve_league_year_and_id():
    c = FakeConn({1: 2026, 2: 2027}, 2026)
    assert resolve_league_year(c, 1) == 2026
    assert resolve_league_year_id(c, 2027) == 2
    assert resolve_league_year_id(c, 2030) is None
    with pytest.raises(ValueError):
        resolve_league_year(c, 99)


def test_resolve_season_id_maps_through_year():
    c = FakeConn({1: 2026, 2: 2027}, 2026, seasons={2026: 1, 2027: 2})
    assert resolve_season_id(c, 2) == 2
    with pytest.raises(ValueError):
        resolve_season_id(c, 3)


def test_signing_year_matches_calendar_in_season():
    c = FakeConn({1: 2026, 2: 2027}, 2026)
    assert resolve_signing_year(c, 1) == (1, 2026)


def test_signing_year_uses_calendar_when_caller_is_behind():
    # After end-season the calendar is on 2027; a caller still passing the
    # finished season's id gets the calendar year.
    c = FakeConn({1: 2026, 2: 2027}, 2027)
    assert resolve_signing_year(c, 1) == (2, 2027)
    assert resolve_signing_year(c, 2) == (2, 2027)


def test_signing_year_requires_calendar_row():
    c = FakeConn({1: 2026}, 2027)
    with pytest.raises(ValueError) as ei:
        resolve_signing_year(c, 1)
    assert "2027" in str(ei.value)


def test_pricing_stats_year_falls_back_to_last_played_season():
    # 2027 offseason: no 2027 stats yet -> price on 2026
    c = FakeConn({1: 2026, 2: 2027}, 2027, years_with_stats=[2026])
    assert pricing_stats_league_year_id(c, 2) == 1
    # mid-2027: partial 2027 stats exist -> use 2027
    c2 = FakeConn({1: 2026, 2: 2027}, 2027, years_with_stats=[2026, 2027])
    assert pricing_stats_league_year_id(c2, 2) == 2
    # nothing played at all -> requested id unchanged
    c3 = FakeConn({1: 2026}, 2026)
    assert pricing_stats_league_year_id(c3, 1) == 1


def test_season_id_sql_binds_named_param():
    frag = season_id_sql("lyid")
    assert frag.startswith("(SELECT s.id FROM seasons s")
    assert ":lyid" in frag and frag.endswith("LIMIT 1)")
