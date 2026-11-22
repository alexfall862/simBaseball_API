"""
How players value an offer (2026-11-22), the same for free agency and
extensions: a signing-bonus dollar counts 1.15 dollars toward the ask
(fa_config bonus_value_premium), and every season of a new MLB contract for
a veteran (6+ service years) pays at least the veteran minimum salary
($1M, the bonus does not count toward it).

Pure tests always run; database scenarios need SIMBB_TEST_DATABASE_URL (a
copy of the league database, e.g. the rehearsal copy after an FA close) and
run inside a transaction that is rolled back.
"""
import math
import os
from decimal import Decimal as D

import pytest


# ── pure ──────────────────────────────────────────────────────────────

def test_effective_value_counts_bonus_at_premium():
    from services.player_demands import effective_offer_value
    assert effective_offer_value(D("4000000"), D("10000000"), D("0.15")) == D("15500000.00")
    assert effective_offer_value(D("4000000"), D("0"), D("0.15")) == D("4000000.00")


def test_scoring_prefers_bonus_money():
    from services.fa_auction import _offer_attractiveness
    salary_only = {"id": 1, "years": 3, "bonus": 0, "total_value": 30_000_000, "aav": 10_000_000}
    bonus_heavy = {"id": 2, "years": 3, "bonus": 18_000_000, "total_value": 28_000_000,
                   "aav": 28_000_000 / 3}
    # 28M cash with an 18M bonus is worth 30.7M to the player
    ranked = _offer_attractiveness(30, [salary_only, bonus_heavy], premium=0.15)
    assert ranked[0]["id"] == 2
    # without the premium the larger cash offer wins
    ranked = _offer_attractiveness(30, [dict(salary_only), dict(bonus_heavy)], premium=0)
    assert ranked[0]["id"] == 1


# ── database ─────────────────────────────────────────────────────────

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")

FA_FINAL = """
    SELECT c.id, c.playerID, cts.orgID
    FROM contracts c
    JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
    JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
    JOIN player_service_time st ON st.player_id = c.playerID
    WHERE c.isFinished = 0 AND c.isActive = 1 AND c.isBuyout = 0
      AND c.current_level = 9 AND c.current_year = c.years AND st.mlb_service_years >= 6
      AND NOT EXISTS (SELECT 1 FROM contracts x WHERE x.playerID = c.playerID AND x.isExtension = 1
                      AND x.isFinished = 0 AND x.leagueYearSigned = c.leagueYearSigned + c.years)
    ORDER BY c.id LIMIT 1"""


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


def _ly(conn):
    from sqlalchemy import text
    return conn.execute(text(
        "SELECT id FROM league_years WHERE league_year = (SELECT season FROM timestamp_state WHERE id = 1)"
    )).scalar()


def _rich(conn, org):
    from sqlalchemy import text
    conn.execute(text("UPDATE organizations SET cash = COALESCE(cash, 0) + 500000000 WHERE id = :o"), {"o": org})


def _bonus_for(total, salaries_total, premium=D("0.15")):
    """Smallest whole-dollar bonus that brings the offer's value to ``total``."""
    return D(math.ceil((D(total) - D(salaries_total)) / (1 + premium)))


def _extension_case(conn):
    from sqlalchemy import text
    from services.player_demands import compute_extension_demand
    row = conn.execute(text(FA_FINAL)).mappings().first()
    if not row:
        pytest.skip("no extension-eligible contract")
    ly = _ly(conn)
    d = compute_extension_demand(conn, row["playerID"], row["id"], ly, 9)
    yrs = int(d["min_years"])
    ask_total = D(d["min_aav"]) * yrs
    _rich(conn, int(row["orgID"]))
    return row, ly, yrs, ask_total


def _extend(conn, row, ly, salaries, bonus):
    from services.transactions import extend_contract
    return extend_contract(conn, row["id"], int(row["orgID"]), len(salaries), salaries, bonus, ly, None, "test")


@db_only
def test_bonus_heavy_extension_meets_ask_for_less_cash(conn):
    row, ly, yrs, ask_total = _extension_case(conn)
    sal = [D("1000000")] * yrs
    bonus = _bonus_for(ask_total, sum(sal))
    cash = sum(sal) + bonus
    assert cash < ask_total
    # the same cash paid as salary falls short of the ask
    per = (cash / yrs).quantize(D("1"))
    with pytest.raises(ValueError, match="below player's minimum demand"):
        _extend(conn, row, ly, [per] * yrs, D("0"))
    assert _extend(conn, row, ly, sal, bonus)["extension_contract_id"]


@db_only
def test_extension_salary_must_meet_veteran_minimum(conn):
    row, ly, yrs, ask_total = _extension_case(conn)
    sal = [D("1000000")] * yrs
    sal[-1] = D("999999")
    with pytest.raises(ValueError, match="Veteran minimum salary"):
        _extend(conn, row, ly, sal, _bonus_for(ask_total, sum(sal)) + 1000000)


@db_only
def test_extension_bonus_respects_free_agent_reservations(conn, monkeypatch):
    import services.fa_auction as fa
    from services.transactions import _get_signing_budget
    row, ly, yrs, ask_total = _extension_case(conn)
    budget = _get_signing_budget(conn, int(row["orgID"]), ly)
    monkeypatch.setattr(fa, "reserved_commitments", lambda *a, **k: budget - D("1"))
    sal = [D("1000000")] * yrs
    with pytest.raises(ValueError, match="reserved by the club's active free-agent offers"):
        _extend(conn, row, ly, sal, _bonus_for(ask_total, sum(sal)))


def _fa_case(conn):
    from sqlalchemy import text
    from services.fa_auction import enter_auction
    ly = _ly(conn)
    pid = conn.execute(text("""
        SELECT a.player_id FROM fa_auction a
        JOIN player_service_time st ON st.player_id = a.player_id AND st.mlb_service_years >= 6
        WHERE a.league_year_id = :ly AND a.phase = 'expired' AND a.min_aav >= 2000000
        ORDER BY a.war_at_entry DESC LIMIT 1"""), {"ly": ly}).scalar()
    if not pid:
        pytest.skip("needs an expired veteran auction (database after an FA close)")
    a = enter_auction(conn, pid, ly, current_week=0)
    yrs = max(int(a["min_years"]), 1)
    ask_total = max(D(str(a["min_aav"])) * yrs, D(str(a["min_total_value"])))
    for org in (2, 3):
        _rich(conn, org)
    return ly, a["auction_id"], yrs, ask_total


def _offer(conn, ly, aid, org, salaries, bonus):
    from services.fa_auction import submit_offer
    return submit_offer(conn, aid, org, len(salaries), salaries, bonus, 9, ly, None, 0, "test")


@db_only
def test_fa_ask_counts_bonus_at_premium(conn):
    ly, aid, yrs, ask_total = _fa_case(conn)
    sal = [D("1000000")] * yrs
    bonus = _bonus_for(ask_total, sum(sal)) + 1
    cash = sum(sal) + bonus
    assert cash < ask_total
    with pytest.raises(ValueError, match="below player minimum"):
        _offer(conn, ly, aid, 3, [(cash / yrs).quantize(D("1"))] * yrs, D("0"))
    assert _offer(conn, ly, aid, 2, sal, bonus)["offer_id"]


@db_only
def test_fa_offer_salary_must_meet_veteran_minimum(conn):
    ly, aid, yrs, ask_total = _fa_case(conn)
    sal = [D("500000")] * yrs
    with pytest.raises(ValueError, match="Veteran minimum salary"):
        _offer(conn, ly, aid, 2, sal, _bonus_for(ask_total, sum(sal)) + 1000000)


@db_only
def test_later_stage_raise_is_judged_on_value(conn):
    from services.fa_auction import advance_auction_phases
    ly, aid, yrs, ask_total = _fa_case(conn)
    per = (ask_total / yrs).quantize(D("1")) + 1
    _offer(conn, ly, aid, 2, [per] * yrs, D("0"))
    advance_auction_phases(conn, 1, ly)
    from sqlalchemy import text
    assert conn.execute(text("SELECT phase FROM fa_auction WHERE id = :a"), {"a": aid}).scalar() == "listening"
    # restructured: less cash in total, more value to the player
    sal = [D("1000000")] * yrs
    bonus = _bonus_for(ask_total * D("1.02"), sum(sal))
    assert sum(sal) + bonus < per * yrs
    assert _offer(conn, ly, aid, 2, sal, bonus)["offer_id"]


@db_only
def test_floor_applies_only_to_mlb_veterans(conn):
    from sqlalchemy import text
    from services.player_demands import VETERAN_MIN_SALARY, veteran_min_salary_for
    vet = conn.execute(text("SELECT player_id FROM player_service_time WHERE mlb_service_years >= 6 LIMIT 1")).scalar()
    young = conn.execute(text("SELECT player_id FROM player_service_time WHERE mlb_service_years < 6 LIMIT 1")).scalar()
    if not (vet and young):
        pytest.skip("needs veteran and non-veteran service rows")
    assert veteran_min_salary_for(conn, vet, 9) == VETERAN_MIN_SALARY
    assert veteran_min_salary_for(conn, vet, 8) is None
    assert veteran_min_salary_for(conn, young, 9) is None
