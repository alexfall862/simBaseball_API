"""
Free agency durability (2026-11-21, docs/FREE_AGENCY_DIAGNOSTIC.md).

Pure rules always run. Database scenarios run against SIMBB_TEST_DATABASE_URL
(a copy of the league database, e.g. the rehearsal copy after End Season)
inside one transaction that is rolled back; skipped otherwise.
"""
import os
from decimal import Decimal

import pytest

from services.market_pricing import weighted_median, guard_rate
from services.fa_auction import lowered_ask, offer_commitment

D = Decimal


# ── pure rules ─────────────────────────────────────────────────────────

def test_weighted_median():
    assert weighted_median([]) is None
    assert weighted_median([(5, 1)]) == D(5)
    assert weighted_median([(1, 1), (2, 1), (100, 1)]) == D(2)          # outlier ignored
    assert weighted_median([(1, 1), (2, 1), (100, 5)]) == D(100)        # heavy weight wins
    assert weighted_median([(3, 0), (7, 1)]) == D(7)                    # zero weight dropped


def test_guard_rate_limits_change_and_band():
    lo, hi = D("4000000"), D("15000000")
    assert guard_rate(D("20000000"), D("8000000"), D("0.15"), lo, hi) == D("9200000.00")
    assert guard_rate(D("1000000"), D("8000000"), D("0.15"), lo, hi) == D("6800000.00")
    assert guard_rate(D("8500000"), D("8000000"), D("0.15"), lo, hi) == D("8500000.00")
    assert guard_rate(D("99000000"), None, D("0.15"), lo, hi) == D("15000000.00")
    assert guard_rate(D("14000000"), D("14000000"), D("0.15"), lo, hi) == D("14000000.00")


def test_lowered_ask_steps_and_floor():
    floor = D("1600000")
    step = lowered_ask(D("10000000"), 3, D("0.10"), floor)
    assert step == {"min_aav": D("9000000.00"), "min_total_value": D("27000000.00")}
    assert lowered_ask(D("1700000"), 2, D("0.10"), floor)["min_aav"] == floor
    assert lowered_ask(floor, 2, D("0.10"), floor) is None


def test_offer_commitment_unwraps_double_encoded_salaries():
    assert offer_commitment(D("500"), '"[1000.0, 2000.0]"', True) == D("1500.0")
    assert offer_commitment(D("500"), "[1000.0]", True) == D("1500.0")
    assert offer_commitment(D("500"), [1000.0], False) == D("500")


# ── database scenarios ────────────────────────────────────────────────

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")


@pytest.fixture
def ctx():
    from sqlalchemy import create_engine, text
    eng = create_engine(DB_URL, pool_pre_ping=True)
    with eng.connect() as conn:
        tx = conn.begin()
        try:
            season = conn.execute(text("SELECT season FROM timestamp_state")).scalar()
            ly = conn.execute(text("SELECT id FROM league_years WHERE league_year = :y"), {"y": season}).scalar()
            pool = [r[0] for r in conn.execute(text("""
                SELECT a.player_id FROM fa_auction a
                WHERE a.league_year_id = :ly AND a.phase = 'expired'
                ORDER BY a.war_at_entry DESC LIMIT 6"""), {"ly": ly}).all()]
            if len(pool) < 3:
                pytest.skip("needs a database after an FA close (expired auctions)")
            yield conn, ly, pool
        finally:
            tx.rollback()


def _auction(conn, ly, pid):
    from services.fa_auction import enter_auction
    a = enter_auction(conn, pid, ly, current_week=0)
    return a["auction_id"], D(str(a["min_aav"])), max(int(a["min_years"]), 1)


def _offer(conn, ly, aid, org, aav, yrs, bonus=D("0")):
    from services.fa_auction import submit_offer
    return submit_offer(conn, aid, org, yrs, [aav.quantize(D("1"))] * yrs, bonus, 9, ly, None, 0, "test")


def _phase(conn, aid):
    from sqlalchemy import text
    return conn.execute(text("SELECT phase, outcome, winning_offer_id FROM fa_auction WHERE id = :i"),
                        {"i": aid}).first()


@db_only
def test_failed_winner_falls_through_to_next_offer(ctx):
    from sqlalchemy import text
    from services.fa_auction import advance_auction_phases
    conn, ly, pool = ctx
    aid, ask, yrs = _auction(conn, ly, pool[0])
    o_best = _offer(conn, ly, aid, 2, ask * D("1.5"), yrs, bonus=D("1000000"))
    o_next = _offer(conn, ly, aid, 3, ask * D("1.2"), yrs)
    advance_auction_phases(conn, 1, ly)
    advance_auction_phases(conn, 2, ly)
    conn.execute(text("INSERT INTO org_ledger_entries (org_id, league_year_id, entry_type, amount, note) "
                      "VALUES (2, :ly, 'bonus', -900000000, 'test: spent elsewhere')"), {"ly": ly})
    advance_auction_phases(conn, 3, ly)
    ph = _phase(conn, aid)
    assert (ph[0], ph[1], ph[2]) == ("completed", "signed", o_next["offer_id"])
    assert conn.execute(text("SELECT status FROM fa_auction_offers WHERE id = :i"),
                        {"i": o_best["offer_id"]}).scalar() == "failed"


@db_only
def test_reoffer_after_withdraw_counts(ctx):
    from sqlalchemy import text
    from services.fa_auction import withdraw_offer
    conn, ly, pool = ctx
    aid, ask, yrs = _auction(conn, ly, pool[1])
    _offer(conn, ly, aid, 5, ask, yrs)
    withdraw_offer(conn, aid, 5)
    r = _offer(conn, ly, aid, 5, ask * D("1.1"), yrs)
    assert conn.execute(text("SELECT status FROM fa_auction_offers WHERE id = :i"),
                        {"i": r["offer_id"]}).scalar() == "active"


@db_only
def test_commitments_are_reserved_across_offers(ctx):
    from services.fa_auction import reserved_commitments
    from services.transactions import _get_signing_budget
    conn, ly, pool = ctx
    org = 6
    avail = _get_signing_budget(conn, org, ly) - reserved_commitments(conn, org)
    big = avail * D("0.6")
    a1, ask1, y1 = _auction(conn, ly, pool[0])
    _offer(conn, ly, a1, org, max(ask1, big), y1)
    a2, ask2, y2 = _auction(conn, ly, pool[1])
    with pytest.raises(ValueError, match="reserved"):
        _offer(conn, ly, a2, org, max(ask2, big), y2)


@db_only
def test_falling_asks_after_two_rounds(ctx):
    from sqlalchemy import text
    from services.fa_auction import advance_auction_phases
    conn, ly, pool = ctx
    aid, ask, _ = _auction(conn, ly, pool[2])
    seen = []
    for w in range(1, 5):
        advance_auction_phases(conn, 10 + w, ly)
        seen.append(D(str(conn.execute(text("SELECT min_aav FROM fa_auction WHERE id = :i"), {"i": aid}).scalar())))
    assert seen[0] == ask and seen[1] == ask
    assert seen[2] == max(D("1600000"), (ask * D("0.9")).quantize(D("0.01")))
    assert seen[3] <= seen[2]


@db_only
def test_close_resolves_every_year_and_leaves_nothing_active(ctx):
    from sqlalchemy import text
    from services.fa_auction import close_free_agency_auctions, get_auction_board
    conn, ly, pool = ctx
    season = conn.execute(text("SELECT season FROM timestamp_state")).scalar()
    prev = conn.execute(text("SELECT id FROM league_years WHERE league_year = :y"), {"y": season - 1}).scalar()
    pid = conn.execute(text("""
        SELECT p.id FROM simbbPlayers p JOIN player_service_time st ON st.player_id = p.id
        WHERE st.mlb_service_years >= 6
          AND NOT EXISTS (SELECT 1 FROM fa_auction a WHERE a.player_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM player_retirements r WHERE r.player_id = p.id)
        LIMIT 1""")).scalar()
    if not prev or not pid:
        pytest.skip("needs a previous league year and an FA-eligible player without an auction")
    aid, _, _ = _auction(conn, prev, pid)
    assert any(e["auction_id"] == aid for e in get_auction_board(conn, ly, None))
    out = close_free_agency_auctions(conn, ly, 20)
    assert _phase(conn, aid)[0:2] == ("expired", "expired_no_offers")
    assert any(d["player_id"] == pid for d in out["fallback"])
    assert conn.execute(text(
        "SELECT COUNT(*) FROM fa_auction WHERE phase IN ('open', 'listening', 'finalize')")).scalar() == 0
