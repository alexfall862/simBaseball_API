# services/market_pricing.py
"""
Market pricing engine — computes $/WAR from historical signings and provides
age/service-based multipliers for contract demand generation.

Bootstrap: when fewer than MIN_HISTORY_FOR_MARKET signings exist in the
rolling lookback window, the engine blends real data with DEFAULT_DOLLAR_PER_WAR.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text as sa_text

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

DEFAULT_DOLLAR_PER_WAR = Decimal("8000000.00")   # $8M/WAR bootstrap
MIN_DOLLAR_PER_WAR    = Decimal("4000000.00")
MAX_DOLLAR_PER_WAR    = Decimal("15000000.00")

MIN_HISTORY_FOR_MARKET = 5       # minimum signings to use market rate
MARKET_LOOKBACK_YEARS  = 3       # rolling window in league_years

# Year weights for the rolling window (most recent = highest weight)
_YEAR_WEIGHTS = {0: Decimal("1.0"), 1: Decimal("0.7"), 2: Decimal("0.4")}

# ── Table reflection cache ───────────────────────────────────────────

_table_cache: Dict[int, Dict[str, Table]] = {}


def _t(conn) -> Dict[str, Table]:
    eid = id(conn.engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "market":       Table("fa_market_history", md, autoload_with=conn.engine),
            "league_years": Table("league_years", md, autoload_with=conn.engine),
            "players":      Table("simbbPlayers", md, autoload_with=conn.engine),
        }
    return _table_cache[eid]


# ── Public API ───────────────────────────────────────────────────────

def get_current_dollar_per_war(conn, league_year_id: int) -> Decimal:
    """
    Compute $/WAR from fa_market_history using a rolling 3-year weighted window.

    Returns a Decimal clamped between MIN and MAX_DOLLAR_PER_WAR.
    If fewer than MIN_HISTORY_FOR_MARKET signings, blends with bootstrap.
    """
    t = _t(conn)
    mh = t["market"]
    ly = t["league_years"]

    # Resolve current league_year value
    row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    if not row:
        return DEFAULT_DOLLAR_PER_WAR
    current_year = row._mapping["league_year"]

    # Fetch signings in the lookback window with WAR >= 0.5
    signings = conn.execute(sa_text("""
        SELECT mh.war_at_signing, mh.total_value, ly.league_year
        FROM fa_market_history mh
        JOIN league_years ly ON ly.id = mh.league_year_id
        WHERE ly.league_year BETWEEN :start_year AND :end_year
          AND mh.war_at_signing >= 0.5
    """), {
        "start_year": current_year - MARKET_LOOKBACK_YEARS + 1,
        "end_year":   current_year,
    }).mappings().all()

    if not signings:
        return DEFAULT_DOLLAR_PER_WAR

    # Weighted $/WAR: sum(value * weight) / sum(war * weight)
    weighted_value = Decimal("0")
    weighted_war   = Decimal("0")
    count = 0
    for s in signings:
        years_ago = current_year - s["league_year"]
        w = _YEAR_WEIGHTS.get(years_ago, Decimal("0.3"))
        val = Decimal(str(s["total_value"]))
        war = Decimal(str(s["war_at_signing"]))
        weighted_value += val * w
        weighted_war   += war * w
        count += 1

    if weighted_war <= 0:
        return DEFAULT_DOLLAR_PER_WAR

    market_rate = (weighted_value / weighted_war).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Blend with default if insufficient history
    if count < MIN_HISTORY_FOR_MARKET:
        blend = Decimal(str(count)) / Decimal(str(MIN_HISTORY_FOR_MARKET))
        market_rate = (
            market_rate * blend + DEFAULT_DOLLAR_PER_WAR * (Decimal("1") - blend)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Clamp
    market_rate = max(MIN_DOLLAR_PER_WAR, min(MAX_DOLLAR_PER_WAR, market_rate))
    return market_rate


def age_service_multiplier(age: int, service_years: int = 99) -> Decimal:
    """
    Multiplier applied to base $/WAR for a specific player's age and service.

    - Under 27: 1.10 (youth premium)
    - 27-30: 1.00 (prime)
    - 31-33: -5% per year over 30
    - 34+: -10% per year over 30 (accelerated decline)
    - Arb-eligible (service 3-5): 40%/60%/80% of FA rate
    """
    # Arb-eligible players get a fraction of FA rate
    if 3 <= service_years < 6:
        arb_year = service_years - 3 + 1  # 1, 2, or 3
        arb_pct = {1: Decimal("0.40"), 2: Decimal("0.60"), 3: Decimal("0.80")}
        return arb_pct.get(arb_year, Decimal("0.80"))

    if age < 27:
        return Decimal("1.10")
    elif age <= 30:
        return Decimal("1.00")
    elif age <= 33:
        years_over = age - 30
        return Decimal("1.00") - Decimal("0.05") * years_over
    else:
        years_over = age - 30
        return max(Decimal("0.30"), Decimal("1.00") - Decimal("0.10") * years_over)


def record_signing_to_market(
    conn,
    player_id: int,
    contract_id: int,
    war: Decimal,
    total_value: Decimal,
    aav: Decimal,
    years: int,
    bonus: Decimal,
    age: int,
    service_years: int,
    league_year_id: int,
    source: str,
) -> int:
    """Insert a row into fa_market_history. Returns the new row ID."""
    t = _t(conn)
    mh = t["market"]

    result = conn.execute(mh.insert().values(
        player_id=player_id,
        league_year_id=league_year_id,
        war_at_signing=war,
        total_value=total_value,
        aav=aav,
        years=years,
        bonus=bonus,
        age_at_signing=age,
        service_years=service_years,
        contract_id=contract_id,
        source=source,
    ))
    new_id = result.lastrowid
    log.info(
        "market_history: player=%d contract=%d war=%.2f value=%s source=%s",
        player_id, contract_id, war, total_value, source,
    )
    return new_id


def delete_market_history_entry(conn, entry_id: int) -> None:
    """Delete a single market history row (for rollback)."""
    t = _t(conn)
    conn.execute(t["market"].delete().where(t["market"].c.id == entry_id))


def get_market_summary(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Return market stats for display:
    - current $/WAR
    - total signings in window
    - average contract length
    - by-WAR-tier breakdown
    """
    t = _t(conn)
    ly = t["league_years"]

    row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    if not row:
        return {"dollar_per_war": str(DEFAULT_DOLLAR_PER_WAR), "signings": 0}
    current_year = row._mapping["league_year"]

    dollar_per_war = get_current_dollar_per_war(conn, league_year_id)

    # Aggregate stats
    stats = conn.execute(sa_text("""
        SELECT
            COUNT(*)                     AS total_signings,
            AVG(mh.years)               AS avg_years,
            AVG(mh.aav)                 AS avg_aav,
            AVG(mh.total_value)         AS avg_total_value,
            SUM(CASE WHEN mh.war_at_signing < 1 THEN 1 ELSE 0 END)  AS tier_0_1,
            SUM(CASE WHEN mh.war_at_signing >= 1 AND mh.war_at_signing < 2 THEN 1 ELSE 0 END) AS tier_1_2,
            SUM(CASE WHEN mh.war_at_signing >= 2 AND mh.war_at_signing < 3 THEN 1 ELSE 0 END) AS tier_2_3,
            SUM(CASE WHEN mh.war_at_signing >= 3 AND mh.war_at_signing < 4 THEN 1 ELSE 0 END) AS tier_3_4,
            SUM(CASE WHEN mh.war_at_signing >= 4 THEN 1 ELSE 0 END)  AS tier_4_plus
        FROM fa_market_history mh
        JOIN league_years ly ON ly.id = mh.league_year_id
        WHERE ly.league_year BETWEEN :start_year AND :end_year
    """), {
        "start_year": current_year - MARKET_LOOKBACK_YEARS + 1,
        "end_year":   current_year,
    }).mappings().first()

    # Recent signings
    recent = conn.execute(sa_text("""
        SELECT mh.player_id, p.firstName, p.lastName,
               mh.war_at_signing, mh.total_value, mh.aav,
               mh.years, mh.source, mh.age_at_signing
        FROM fa_market_history mh
        JOIN simbbPlayers p ON p.id = mh.player_id
        JOIN league_years ly ON ly.id = mh.league_year_id
        WHERE ly.league_year BETWEEN :start_year AND :end_year
        ORDER BY mh.created_at DESC
        LIMIT 20
    """), {
        "start_year": current_year - MARKET_LOOKBACK_YEARS + 1,
        "end_year":   current_year,
    }).mappings().all()

    return {
        "dollar_per_war": str(dollar_per_war),
        "total_signings": int(stats["total_signings"] or 0),
        "avg_years":      round(float(stats["avg_years"] or 0), 1),
        "avg_aav":        str(round(Decimal(str(stats["avg_aav"] or 0)), 2)),
        "avg_total_value": str(round(Decimal(str(stats["avg_total_value"] or 0)), 2)),
        "war_tiers": {
            "0-1": int(stats["tier_0_1"] or 0),
            "1-2": int(stats["tier_1_2"] or 0),
            "2-3": int(stats["tier_2_3"] or 0),
            "3-4": int(stats["tier_3_4"] or 0),
            "4+":  int(stats["tier_4_plus"] or 0),
        },
        "recent_signings": [
            {
                "player_id": int(r["player_id"]),
                "name": f"{r['firstName']} {r['lastName']}".strip(),
                "war": float(r["war_at_signing"]),
                "total_value": str(r["total_value"]),
                "aav": str(r["aav"]),
                "years": int(r["years"]),
                "age": int(r["age_at_signing"]),
                "source": r["source"],
            }
            for r in recent
        ],
    }
