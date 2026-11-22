"""
Contract extension rules (2026-11-21), against a real database inside one
transaction that is rolled back.

Eligible: MLB (level 9) contract in force and in its final season, player
FA-eligible (6+ service years), offered by the holding org, no extension yet.
A signed extension is stored pending (isActive=0, current_year=0) so the
player is still listed once.

Needs SIMBB_TEST_DATABASE_URL pointing at a copy of the league database
(the rehearsal copy works); skipped otherwise.
"""
import os
from decimal import Decimal

import pytest

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")

HOLD = """
    SELECT c.id, c.playerID, cts.orgID
    FROM contracts c
    JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
    JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
    LEFT JOIN player_service_time st ON st.player_id = c.playerID
    WHERE c.isFinished = 0 AND c.isActive = 1 AND c.isBuyout = 0 AND {cond}
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


def _row(conn, cond):
    from sqlalchemy import text
    r = conn.execute(text(HOLD.format(cond=cond))).mappings().first()
    if not r:
        pytest.skip(f"no contract matching: {cond}")
    return r


def _ly(conn):
    from sqlalchemy import text
    return conn.execute(text(
        "SELECT id FROM league_years WHERE league_year = (SELECT season FROM timestamp_state WHERE id = 1)"
    )).scalar()


def _extend(conn, row, org, aav="40000000", years=3):
    from services.transactions import extend_contract
    return extend_contract(conn, row["id"], org, years, [Decimal(aav)] * years,
                           Decimal("0"), _ly(conn), None, "test")


FA_FINAL = ("c.current_level = 9 AND c.current_year = c.years AND st.mlb_service_years >= 6 "
            "AND NOT EXISTS (SELECT 1 FROM contracts x WHERE x.playerID = c.playerID AND x.isExtension = 1 "
            "AND x.isFinished = 0 AND x.leagueYearSigned = c.leagueYearSigned + c.years)")


@pytest.mark.parametrize("cond,code", [
    ("c.current_level = 9 AND c.current_year = c.years AND st.mlb_service_years BETWEEN 3 AND 5", "not_fa_eligible"),
    ("c.current_level = 9 AND c.current_year = c.years AND COALESCE(st.mlb_service_years, 0) < 3", "not_fa_eligible"),
    ("c.current_level = 9 AND c.current_year < c.years AND st.mlb_service_years >= 6", "not_final_year"),
    ("c.current_level BETWEEN 4 AND 8 AND c.current_year = c.years", "not_mlb"),
])
def test_ineligible_contracts_are_refused_with_a_code(conn, cond, code):
    from services.transactions import ExtensionIneligible
    row = _row(conn, cond)
    with pytest.raises(ExtensionIneligible) as e:
        _extend(conn, row, row["orgID"])
    assert e.value.code == code


def test_only_the_holder_can_extend(conn):
    from services.transactions import ExtensionIneligible
    row = _row(conn, FA_FINAL)
    other = 1 if int(row["orgID"]) != 1 else 2
    with pytest.raises(ExtensionIneligible) as e:
        _extend(conn, row, other)
    assert e.value.code == "not_holder"


def test_low_offer_rejected_and_can_be_retried(conn):
    row = _row(conn, FA_FINAL)
    # below the veteran minimum salary ($1M a season)
    with pytest.raises(ValueError, match="Veteran minimum salary"):
        _extend(conn, row, row["orgID"], aav="900000")
    # above the floor but below the ask (the lowest extension ask is $1.44M)
    for aav in ("1000000", "1200000"):
        with pytest.raises(ValueError, match="below player's minimum demand"):
            _extend(conn, row, row["orgID"], aav=aav)
    assert _extend(conn, row, row["orgID"])["extension_contract_id"]


def test_signed_extension_is_pending_and_listed_once(conn):
    from sqlalchemy import text
    from services.transactions import ExtensionIneligible, extension_eligibility
    from services.contract_ops import get_org_contract_overview, get_player_contract_status
    row = _row(conn, FA_FINAL)
    pid, org = int(row["playerID"]), int(row["orgID"])
    held = text("""
        SELECT COUNT(*) FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE c.playerID = :p AND c.isActive = 1""")
    assert conn.execute(held, {"p": pid}).scalar() == 1
    assert extension_eligibility(conn, row["id"], org)["eligible"] is True

    res = _extend(conn, row, org)
    ext = conn.execute(text("SELECT isActive, current_year, isFinished FROM contracts WHERE id = :i"),
                       {"i": res["extension_contract_id"]}).mappings().first()
    assert dict(ext) == {"isActive": 0, "current_year": 0, "isFinished": 0}
    assert conn.execute(held, {"p": pid}).scalar() == 1

    ov = [e for e in get_org_contract_overview(conn, org) if e["player_id"] == pid]
    assert len(ov) == 1 and ov[0]["has_extension"] and not ov[0]["extension_eligible"]
    st = get_player_contract_status(conn, pid)
    assert st["contract_id"] == row["id"] and st["has_extension"] and not st["extension_eligible"]

    with pytest.raises(ExtensionIneligible) as e:
        _extend(conn, row, org)
    assert e.value.code == "already_extended"
