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

# Market-sample weights by signing source. Arbitration renewals are formula
# prices (a fraction of the market rate), not market evidence: including them
# dragged the rate to the floor. Extensions are real but carry a security
# discount, hence the lower weight (configurable in fa_config).
_EXCLUDED_SOURCES = ("arb_renewal",)


def weighted_median(pairs) -> Optional[Decimal]:
    """Weighted median of (value, weight) pairs; None when empty."""
    pts = sorted((Decimal(str(v)), Decimal(str(w))) for v, w in pairs if Decimal(str(w)) > 0)
    if not pts:
        return None
    half = sum(w for _, w in pts) / 2
    acc = Decimal("0")
    for v, w in pts:
        acc += w
        if acc >= half:
            return v
    return pts[-1][0]


def guard_rate(raw: Decimal, anchor: Optional[Decimal], max_change: Decimal,
               lo: Decimal, hi: Decimal) -> Decimal:
    """Limit a raw rate to +/- max_change around the anchor (the previous
    season's rate), then to the absolute [lo, hi] band."""
    rate = Decimal(str(raw))
    if anchor is not None and max_change > 0:
        rate = max(anchor * (1 - max_change), min(anchor * (1 + max_change), rate))
    return max(lo, min(hi, rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


_RATE_MEMO: Dict[tuple, Dict[str, Any]] = {}


def market_rate_breakdown(conn, league_year_id: int, _depth: int = 0) -> Dict[str, Any]:
    """
    The $ per WAR rate for a league year, with how it was reached.

    - sample: signings of the last ``market_lookback_years`` seasons with
      WAR >= 0.5; arbitration renewals excluded; extensions weighted by
      ``market_extension_weight``; seasons weighted 1.0 / 0.7 / 0.4
    - raw rate: weighted **median** of each signing's AAV / WAR
      (``market_rate_method = median``) or the ratio of sums (``ratio``)
    - thin sample (< ``market_min_history``): blended toward the anchor
    - anchor: the previous season's rate, or ``dollar_per_war_default`` for
      the first season; the rate moves at most ``market_rate_max_change``
      from it, so a handful of outlier signings cannot reprice the league
    - finally clamped to [dollar_per_war_min, dollar_per_war_max]

    Memoised per (league year, market history contents, config).
    """
    from services.league_config import get_fa_config, cfg_dec, cfg_int

    cfg = get_fa_config(conn)
    default_rate = cfg_dec(cfg, "dollar_per_war_default", DEFAULT_DOLLAR_PER_WAR)
    min_rate = cfg_dec(cfg, "dollar_per_war_min", MIN_DOLLAR_PER_WAR)
    max_rate = cfg_dec(cfg, "dollar_per_war_max", MAX_DOLLAR_PER_WAR)
    min_history = cfg_int(cfg, "market_min_history", MIN_HISTORY_FOR_MARKET)
    lookback = cfg_int(cfg, "market_lookback_years", MARKET_LOOKBACK_YEARS)
    ext_weight = cfg_dec(cfg, "market_extension_weight", "0.9")
    max_change = cfg_dec(cfg, "market_rate_max_change", "0.15")
    method = str(cfg.get("market_rate_method") or "median").lower()

    sig = conn.execute(sa_text(
        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM fa_market_history"
    )).first()
    key = (id(conn.engine), int(league_year_id), int(sig[0]), int(sig[1]),
           tuple(sorted((k, str(v)) for k, v in cfg.items())))
    if key in _RATE_MEMO:
        return _RATE_MEMO[key]

    t = _t(conn)
    ly = t["league_years"]
    row = conn.execute(select(ly.c.league_year).where(ly.c.id == league_year_id)).first()
    if not row:
        return {"league_year_id": int(league_year_id), "rate": default_rate, "raw_rate": None,
                "anchor": None, "signings": 0, "method": method, "limited": False}
    current_year = int(row._mapping["league_year"])

    anchor = default_rate
    prev = conn.execute(select(ly.c.id).where(ly.c.league_year == current_year - 1)).first()
    if prev and _depth < 50:
        anchor = Decimal(str(market_rate_breakdown(conn, int(prev[0]), _depth + 1)["rate"]))

    signings = conn.execute(sa_text("""
        SELECT mh.war_at_signing, mh.aav, mh.total_value, mh.years, mh.source,
               ly.league_year
        FROM fa_market_history mh
        JOIN league_years ly ON ly.id = mh.league_year_id
        WHERE ly.league_year BETWEEN :start_year AND :end_year
          AND mh.war_at_signing >= 0.5
    """), {"start_year": current_year - lookback + 1, "end_year": current_year}).mappings().all()

    samples = []
    for s in signings:
        source = (s["source"] or "").lower()
        if source in _EXCLUDED_SOURCES:
            continue
        w = _YEAR_WEIGHTS.get(current_year - int(s["league_year"]), Decimal("0.3"))
        if source == "extension":
            w = w * ext_weight
        aav = s["aav"]
        if aav is None:
            aav = Decimal(str(s["total_value"])) / (int(s["years"] or 1) or 1)
        war = Decimal(str(s["war_at_signing"]))
        samples.append((Decimal(str(aav)), war, w))

    target = anchor
    count = len(samples)
    if count == 0:
        raw = target
    else:
        if method == "ratio":
            raw = sum(a * w for a, _, w in samples) / sum(v * w for _, v, w in samples)
        else:
            raw = weighted_median([(a / v, w) for a, v, w in samples])
        if count < min_history:
            blend = Decimal(count) / Decimal(min_history)
            raw = raw * blend + target * (1 - blend)
    raw = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rate = guard_rate(raw, anchor, max_change, min_rate, max_rate)
    unlimited = max(min_rate, min(max_rate, raw))
    out = {
        "league_year_id": int(league_year_id), "league_year": current_year,
        "rate": rate, "raw_rate": raw, "anchor": anchor, "signings": count,
        "method": method, "max_change": max_change,
        "limited": rate != unlimited.quantize(Decimal("0.01")),
    }
    if len(_RATE_MEMO) > 500:
        _RATE_MEMO.clear()
    _RATE_MEMO[key] = out
    return out


def get_current_dollar_per_war(conn, league_year_id: int) -> Decimal:
    """$ per WAR for a league year (see ``market_rate_breakdown``)."""
    return Decimal(str(market_rate_breakdown(conn, league_year_id)["rate"]))


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
