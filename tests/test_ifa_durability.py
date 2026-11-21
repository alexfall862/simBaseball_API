"""
International signing fixes (2026-11-21): bonus charged at signing, one
auction cannot stop the week, failed winners fall through, the window keeps
End Season's pools. Database scenarios run against SIMBB_TEST_DATABASE_URL
(a copy of the league database with a pending IFA window, e.g. the rehearsal
copy after End Season) inside a transaction that is rolled back.
"""
import os
from decimal import Decimal

import pytest

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")


@pytest.fixture
def ctx():
    from sqlalchemy import create_engine, text
    eng = create_engine(DB_URL, pool_pre_ping=True)
    with eng.connect() as conn:
        tx = conn.begin()
        try:
            season = conn.execute(text("SELECT season FROM timestamp_state")).scalar()
            ly = conn.execute(text("SELECT id FROM league_years WHERE league_year = :y"), {"y": season}).scalar()
            st = conn.execute(text("SELECT status FROM ifa_state WHERE league_year_id = :ly"), {"ly": ly}).scalar()
            if st != "pending":
                pytest.skip("needs a pending IFA window for the current league year")
            pids = [int(r[0]) for r in conn.execute(text("""
                SELECT p.id FROM simbbPlayers p
                JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
                JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
                JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1 AND cts.orgID = 339
                WHERE p.age >= 16 AND p.recruit_stars = 3 ORDER BY p.id LIMIT 3""")).all()]
            if len(pids) < 3:
                pytest.skip("needs three 3-star international players")
            yield conn, ly, pids
        finally:
            tx.rollback()


def _open_with_offers(conn, ly, pids, offers):
    """Open the window, start auctions and place offers [(player_idx, org, extra)]."""
    from sqlalchemy import text
    from services import ifa_signing as ifa
    ifa.advance_ifa_week(conn, ly)
    aids = {}
    for i, pid in enumerate(pids):
        aids[i] = ifa.start_ifa_auction(conn, pid, ly, 1, org_id=1)["auction_id"]
    for i, org, extra in offers:
        slot = Decimal(str(conn.execute(text("SELECT slot_value FROM ifa_auction WHERE id = :a"),
                                        {"a": aids[i]}).scalar()))
        ifa.submit_ifa_offer(conn, aids[i], org, slot + extra, ly, 1)
    return aids


def _phase(conn, aid):
    from sqlalchemy import text
    return conn.execute(text("SELECT phase FROM ifa_auction WHERE id = :a"), {"a": aid}).scalar()


def test_opening_the_window_keeps_end_season_pools(ctx):
    from sqlalchemy import text
    from services import ifa_signing as ifa
    conn, ly, _ = ctx
    q = text("SELECT org_id, total_pool FROM ifa_bonus_pools WHERE league_year_id = :ly ORDER BY org_id")
    before = conn.execute(q, {"ly": ly}).all()
    out = ifa.advance_ifa_week(conn, ly)
    assert out["pools_kept"] is True
    assert conn.execute(q, {"ly": ly}).all() == before


def test_signing_is_active_and_charges_cash_once(ctx):
    from sqlalchemy import text
    from services import ifa_signing as ifa
    conn, ly, pids = ctx
    aids = _open_with_offers(conn, ly, pids, [(0, 1, Decimal("0"))])
    for _ in range(9):
        ifa.advance_ifa_week(conn, ly)
    assert _phase(conn, aids[0]) == "completed"
    c = conn.execute(text("""
        SELECT id, isActive, current_level, bonus, leagueYearSigned FROM contracts
        WHERE playerID = :p AND isFinished = 0 ORDER BY id DESC LIMIT 1"""), {"p": pids[0]}).mappings().first()
    assert c["isActive"] == 1 and c["current_level"] == 4
    rows = conn.execute(text("""
        SELECT l.amount, ly.league_year FROM org_ledger_entries l JOIN league_years ly ON ly.id = l.league_year_id
        WHERE l.contract_id = :c AND l.entry_type = 'bonus'"""), {"c": c["id"]}).all()
    assert len(rows) == 1
    assert Decimal(str(rows[0][0])) == -Decimal(str(c["bonus"]))
    assert int(rows[0][1]) == int(c["leagueYearSigned"])


def test_failed_winner_falls_through_and_one_auction_cannot_stop_the_week(ctx, monkeypatch):
    from sqlalchemy import text
    from services import ifa_signing as ifa
    conn, ly, pids = ctx
    aids = _open_with_offers(conn, ly, pids, [
        (0, 1, Decimal("0")),
        (1, 2, Decimal("1000")), (1, 3, Decimal("0")),
        (2, 4, Decimal("0")),
    ])
    real_exec, real_one = ifa._execute_ifa_signing, ifa._advance_one_ifa_auction

    def flaky(conn_, auction_id, offer_id, *a, **k):
        org = conn_.execute(text("SELECT org_id FROM ifa_auction_offers WHERE id = :i"), {"i": offer_id}).scalar()
        if int(org) == 2:
            raise RuntimeError("simulated failure")
        return real_exec(conn_, auction_id, offer_id, *a, **k)

    def exploding(conn_, a, *args, **kw):
        if int(a["id"]) == aids[2]:
            raise RuntimeError("simulated crash")
        return real_one(conn_, a, *args, **kw)

    monkeypatch.setattr(ifa, "_execute_ifa_signing", flaky)
    monkeypatch.setattr(ifa, "_advance_one_ifa_auction", exploding)
    errors = 0
    for _ in range(9):
        errors += len(ifa.advance_ifa_week(conn, ly).get("phase_transitions", {}).get("errors", []))
    assert errors >= 1
    assert _phase(conn, aids[0]) == "completed"
    assert _phase(conn, aids[1]) == "completed"
    st = dict(conn.execute(text("SELECT org_id, status FROM ifa_auction_offers WHERE auction_id = :a"),
                           {"a": aids[1]}).all())
    assert st[2] == "failed" and st[3] == "won"


def test_retired_player_auction_is_expired(ctx):
    from sqlalchemy import text
    from services import ifa_signing as ifa
    conn, ly, pids = ctx
    aids = _open_with_offers(conn, ly, pids, [(0, 1, Decimal("0"))])
    for _ in range(7):
        ifa.advance_ifa_week(conn, ly)
    conn.execute(text("INSERT INTO player_retirements (player_id, league_year_id, reason, age) "
                      "VALUES (:p, :ly, 'age', 30)"), {"p": pids[0], "ly": ly})
    for _ in range(2):
        ifa.advance_ifa_week(conn, ly)
    assert _phase(conn, aids[0]) == "expired"
