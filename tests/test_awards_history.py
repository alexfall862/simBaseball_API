"""
GET /awards/history (services.awards.get_awards_history), against a real
database inside one transaction that is rolled back.

Needs SIMBB_TEST_DATABASE_URL pointing at a copy of the league database
(the rehearsal copy works); skipped otherwise.
"""
import os

import pytest

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")


@pytest.fixture
def conn():
    from sqlalchemy import create_engine
    eng = create_engine(DB_URL, pool_pre_ping=True)
    with eng.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


def _history(conn, **kw):
    from services.awards import get_awards_history
    return get_awards_history(conn, **kw)


def test_championships_collapse_to_one_entry_per_team(conn):
    from sqlalchemy import text
    db = conn.execute(text("""
        SELECT league_year_id, award_code, sub_league, team_id, COUNT(*) AS n
        FROM player_awards
        WHERE league_level = 9 AND award_code IN ('pennant', 'world_series')
        GROUP BY league_year_id, award_code, sub_league, team_id
    """)).mappings().all()
    if not db:
        pytest.skip("no championship awards in this database")

    out = _history(conn)
    got = {}
    for s in out["seasons"]:
        for code, teams in s["championships"].items():
            for g in teams:
                key = (s["league_year_id"], code, g["sub_league"] or "", g["team"]["team_id"])
                assert key not in got, "team listed twice for one title"
                got[key] = g["roster_size"]
                assert "players" not in g  # only with include_rosters
    expected = {(r["league_year_id"], r["award_code"], r["sub_league"], r["team_id"]): r["n"]
                for r in db}
    assert got == expected

    # Team leaders count a title once per season, not once per rostered player.
    for t in out["leaders"]["teams"]:
        for title in t["titles"].values():
            assert title["count"] == len(title["years"])


def test_finalists_selections_and_filters(conn):
    from sqlalchemy import text
    ly = conn.execute(text("SELECT MAX(id) FROM league_years")).scalar()
    pids = conn.execute(text("SELECT id FROM simbbPlayers ORDER BY id LIMIT 3")).scalars().all()
    if ly is None or len(pids) < 3:
        pytest.skip("need a league year and 3 players")
    _history(conn)  # bootstrap awards schema before inserting

    # A ROY finalist (not a winner) and two AL All-Stars + one NL All-Star.
    conn.execute(text("""
        DELETE FROM player_awards
        WHERE league_year_id = :ly AND award_code IN ('roy', 'all_star')
    """), {"ly": ly})
    conn.execute(text("""
        INSERT INTO player_awards
            (player_id, league_year_id, league_level, award_code, sub_league,
             position_code, `rank`, is_winner)
        VALUES (:p0, :ly, 9, 'roy', 'AL', '', 2, 0),
               (:p0, :ly, 9, 'all_star', 'AL', '', 1, 1),
               (:p1, :ly, 9, 'all_star', 'AL', '', 1, 1),
               (:p2, :ly, 9, 'all_star', 'NL', '', 1, 1)
    """), {"ly": ly, "p0": pids[0], "p1": pids[1], "p2": pids[2]})

    def season(out):
        return next(s for s in out["seasons"] if s["league_year_id"] == ly)

    base = season(_history(conn))
    assert "roy" not in base["individual"]  # finalists hidden by default
    assert base["selections"]["all_star"]["AL"] == {"count": 2}
    assert base["selections"]["all_star"]["NL"] == {"count": 1}

    full = season(_history(conn, include_finalists=True, include_selections=True))
    roy = full["individual"]["roy"]
    assert [(r["player_id"], r["rank"], r["is_winner"]) for r in roy] == [(pids[0], 2, False)]
    assert {p["player_id"] for p in full["selections"]["all_star"]["AL"]["players"]} == set(pids[:2])

    # Finalists never count toward leaders; selections do.
    leaders = {p["player_id"]: p for p in _history(conn, leaders_limit=0)["leaders"]["players"]}
    assert "roy" not in leaders[pids[0]]["awards"]
    assert leaders[pids[0]]["awards"]["all_star"]["wins"] == 1

    only = _history(conn, award_codes=["all_star"])
    assert [t["code"] for t in only["award_types"]] == ["all_star"]
    assert all(not s["individual"] and not s["championships"] for s in only["seasons"])

    year = conn.execute(text("SELECT league_year FROM league_years WHERE id = :ly"),
                        {"ly": ly}).scalar()
    assert all(s["league_year"] > year
               for s in _history(conn, from_year=year + 1)["seasons"])


def test_unknown_award_code_rejected(conn):
    with pytest.raises(ValueError):
        _history(conn, award_codes=["not_a_trophy"])
