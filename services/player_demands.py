# services/player_demands.py
"""
Player demand generation — computes WAR-based contract demands for
free agency, extensions, and buyouts, plus arbitration salary calculation.

Demands are cached in the player_demands table and refreshed on request.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text as sa_text

from services.market_pricing import (
    age_service_multiplier,
    get_current_dollar_per_war,
)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

PRE_ARB_SALARY   = Decimal("800000.00")
FA_DEMAND_FLOOR  = PRE_ARB_SALARY * 2              # $1.6M minimum AAV
ARB_SALARY_FLOOR = PRE_ARB_SALARY * Decimal("1.5") # $1.2M minimum arb salary
ARB_SALARY_CAP   = Decimal("20000000.00")           # $20M arb cap
RUNS_PER_WIN     = Decimal("10.0")

# Extension discount (security premium for the player)
EXTENSION_DISCOUNT = Decimal("0.90")

# ── Table reflection cache ───────────────────────────────────────────

_table_cache: Dict[int, Dict[str, Table]] = {}


def _t(conn) -> Dict[str, Table]:
    eid = id(conn.engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "demands":      Table("player_demands", md, autoload_with=conn.engine),
            "contracts":    Table("contracts", md, autoload_with=conn.engine),
            "details":      Table("contractDetails", md, autoload_with=conn.engine),
            "shares":       Table("contractTeamShare", md, autoload_with=conn.engine),
            "players":      Table("simbbPlayers", md, autoload_with=conn.engine),
            "service_time": Table("player_service_time", md, autoload_with=conn.engine),
            "league_years": Table("league_years", md, autoload_with=conn.engine),
            "teams":        Table("teams", md, autoload_with=conn.engine),
        }
    return _table_cache[eid]


# ── Single-player WAR ────────────────────────────────────────────────

def get_player_war(
    conn, player_id: int, league_year_id: int, league_level: int = 9,
) -> Decimal:
    """
    Compute WAR for a single player using the same component formula as
    analytics.war_leaderboard.  Returns Decimal("0.00") if insufficient data.
    """
    # League averages (same queries as analytics.py but for the level)
    lg = conn.execute(sa_text("""
        SELECT
            SUM(bs.hits + bs.walks) AS lg_on_base,
            SUM(bs.at_bats + bs.walks) AS lg_pa,
            SUM(bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs) AS lg_tb,
            SUM(bs.at_bats) AS lg_ab,
            SUM(bs.runs) AS lg_runs
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_pa  = float(lg["lg_pa"] or 1)
    lg_ab  = float(lg["lg_ab"] or 1)
    lg_runs = float(lg["lg_runs"] or 1)
    lg_obp = float(lg["lg_on_base"] or 0) / lg_pa if lg_pa > 0 else 0.0
    lg_slg = float(lg["lg_tb"] or 0) / lg_ab if lg_ab > 0 else 0.0
    lg_ops = lg_obp + lg_slg
    pa_per_run = lg_pa / lg_runs if lg_runs > 0 else 25.0
    repl_ops = lg_ops * 0.80

    # League pitching averages
    lg_pit = conn.execute(sa_text("""
        SELECT SUM(ps.earned_runs) AS lg_er,
               SUM(ps.innings_pitched_outs) AS lg_ipo
        FROM player_pitching_stats ps
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_ipo = float(lg_pit["lg_ipo"] or 1)
    lg_er  = float(lg_pit["lg_er"] or 0)
    lg_era = lg_er * 27.0 / lg_ipo if lg_ipo > 0 else 4.50
    repl_era = lg_era / 0.80

    # League fielding error rates by position
    fld_rows = conn.execute(sa_text("""
        SELECT fs.position_code,
               SUM(fs.errors) AS total_errors,
               SUM(fs.innings) AS total_innings
        FROM player_fielding_stats fs
        JOIN teams tm ON tm.id = fs.team_id
        WHERE fs.league_year_id = :lyid AND tm.team_level = :level
        GROUP BY fs.position_code
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    lg_err_rate = {}
    for fr in fld_rows:
        inn = float(fr["total_innings"] or 1)
        lg_err_rate[fr["position_code"]] = (
            float(fr["total_errors"] or 0) / inn if inn > 0 else 0.0
        )

    # Player batting stats
    bat = conn.execute(sa_text("""
        SELECT bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.stolen_bases, bs.caught_stealing
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.player_id = :pid AND bs.league_year_id = :lyid
              AND tm.team_level = :level
    """), {"pid": player_id, "lyid": league_year_id, "level": league_level}
    ).mappings().first()

    war = 0.0

    if bat and float(bat["at_bats"] or 0) > 0:
        ab = float(bat["at_bats"])
        h  = float(bat["hits"])
        d  = float(bat["doubles_hit"])
        tr = float(bat["triples"])
        hr = float(bat["home_runs"])
        bb = float(bat["walks"])
        sb = float(bat["stolen_bases"])
        cs = float(bat["caught_stealing"])

        pa  = ab + bb
        obp = (h + bb) / pa if pa > 0 else 0.0
        slg = (h + d + 2 * tr + 3 * hr) / ab if ab > 0 else 0.0
        batting_runs = (obp + slg - repl_ops) * pa / pa_per_run
        br_runs = (sb - 2.0 * cs) * 0.2

        # Fielding
        fld_runs = 0.0
        fld = conn.execute(sa_text("""
            SELECT fs.position_code, fs.innings, fs.errors
            FROM player_fielding_stats fs
            JOIN teams tm ON tm.id = fs.team_id
            WHERE fs.player_id = :pid AND fs.league_year_id = :lyid
                  AND tm.team_level = :level
            ORDER BY fs.innings DESC
            LIMIT 1
        """), {"pid": player_id, "lyid": league_year_id, "level": league_level}
        ).mappings().first()

        if fld and float(fld["innings"] or 0) > 0:
            pos = fld["position_code"]
            expected_err = lg_err_rate.get(pos, 0.0) * float(fld["innings"])
            fld_runs = (expected_err - float(fld["errors"])) * 0.8

        war += (batting_runs + br_runs + fld_runs) / 10.0

    # Pitching
    pit = conn.execute(sa_text("""
        SELECT ps.innings_pitched_outs, ps.earned_runs
        FROM player_pitching_stats ps
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.player_id = :pid AND ps.league_year_id = :lyid
              AND tm.team_level = :level
    """), {"pid": player_id, "lyid": league_year_id, "level": league_level}
    ).mappings().first()

    if pit and float(pit["innings_pitched_outs"] or 0) > 0:
        ipo = float(pit["innings_pitched_outs"])
        er  = float(pit["earned_runs"])
        ip  = ipo / 3.0
        player_era = er * 9.0 / ip if ip > 0 else 99.0
        pit_runs = (repl_era - player_era) * ip / 9.0
        war += pit_runs / 10.0

    return Decimal(str(round(war, 2)))


# ── Preferred contract years by age ──────────────────────────────────

def _preferred_years(age: int) -> tuple[int, int]:
    """Return (min_years, max_years) the player would accept."""
    if age <= 28:
        return (3, 5)
    elif age <= 31:
        return (2, 4)
    elif age <= 33:
        return (1, 3)
    else:
        return (1, 2)


# ── Player info helper ───────────────────────────────────────────────

def _get_player_info(conn, player_id: int) -> Dict[str, Any]:
    """Get age and service years for a player."""
    t = _t(conn)
    p = t["players"]
    st = t["service_time"]

    player = conn.execute(
        select(p.c.age).where(p.c.id == player_id)
    ).first()
    age = int(player._mapping["age"]) if player else 25

    svc = conn.execute(
        select(st.c.mlb_service_years).where(st.c.player_id == player_id)
    ).first()
    service_years = int(svc._mapping["mlb_service_years"]) if svc else 0

    return {"age": age, "service_years": service_years}


# ── Demand computation: Free Agency ─────────────────────────────────

def compute_fa_demand(
    conn, player_id: int, league_year_id: int, league_level: int = 9,
) -> Dict[str, Any]:
    """
    Generate FA minimum demands for a player based on WAR, age, and market.
    Upserts into the player_demands table.

    Returns dict with min_years, max_years, min_aav, min_total_value, war, etc.
    """
    t = _t(conn)
    demands = t["demands"]
    info = _get_player_info(conn, player_id)
    age = info["age"]
    service_years = info["service_years"]

    war = get_player_war(conn, player_id, league_year_id, league_level)
    dpw = get_current_dollar_per_war(conn, league_year_id)
    mult = age_service_multiplier(age, service_years=99)  # FA-eligible, use age only

    adjusted_aav = (war * dpw * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    adjusted_aav = max(adjusted_aav, FA_DEMAND_FLOOR)

    min_years, max_years = _preferred_years(age)
    min_total_value = (adjusted_aav * min_years).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Upsert
    existing = conn.execute(
        select(demands.c.id).where(and_(
            demands.c.player_id == player_id,
            demands.c.league_year_id == league_year_id,
            demands.c.demand_type == "fa",
        ))
    ).first()

    values = dict(
        player_id=player_id,
        league_year_id=league_year_id,
        demand_type="fa",
        war_snapshot=war,
        age_snapshot=age,
        service_years=service_years,
        min_years=min_years,
        max_years=max_years,
        min_aav=adjusted_aav,
        min_total_value=min_total_value,
        buyout_price=None,
        dollar_per_war=dpw,
    )

    if existing:
        conn.execute(
            demands.update()
            .where(demands.c.id == existing._mapping["id"])
            .values(**values)
        )
    else:
        conn.execute(demands.insert().values(**values))

    log.info(
        "fa_demand: player=%d war=%.2f aav=%s years=%d-%d total=%s",
        player_id, war, adjusted_aav, min_years, max_years, min_total_value,
    )
    return {
        "player_id": player_id,
        "demand_type": "fa",
        "war": float(war),
        "dollar_per_war": str(dpw),
        "min_aav": str(adjusted_aav),
        "min_years": min_years,
        "max_years": max_years,
        "min_total_value": str(min_total_value),
        "age": age,
        "service_years": service_years,
    }


# ── Demand computation: Extension ───────────────────────────────────

def compute_extension_demand(
    conn,
    player_id: int,
    contract_id: int,
    league_year_id: int,
    league_level: int = 9,
) -> Dict[str, Any]:
    """
    Generate extension demands: FA baseline * 90% discount for security.
    Upserts into player_demands.
    """
    t = _t(conn)
    demands = t["demands"]
    info = _get_player_info(conn, player_id)
    age = info["age"]
    service_years = info["service_years"]

    war = get_player_war(conn, player_id, league_year_id, league_level)
    dpw = get_current_dollar_per_war(conn, league_year_id)
    mult = age_service_multiplier(age, service_years=99)

    # Extension = FA baseline * discount
    fa_aav = (war * dpw * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fa_aav = max(fa_aav, FA_DEMAND_FLOOR)
    ext_aav = (fa_aav * EXTENSION_DISCOUNT).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    min_years = max(2, _preferred_years(age)[0] - 1)
    max_years = _preferred_years(age)[1]
    min_total_value = (ext_aav * min_years).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    existing = conn.execute(
        select(demands.c.id).where(and_(
            demands.c.player_id == player_id,
            demands.c.league_year_id == league_year_id,
            demands.c.demand_type == "extension",
        ))
    ).first()

    values = dict(
        player_id=player_id,
        league_year_id=league_year_id,
        demand_type="extension",
        war_snapshot=war,
        age_snapshot=age,
        service_years=service_years,
        min_years=min_years,
        max_years=max_years,
        min_aav=ext_aav,
        min_total_value=min_total_value,
        buyout_price=None,
        dollar_per_war=dpw,
    )

    if existing:
        conn.execute(
            demands.update()
            .where(demands.c.id == existing._mapping["id"])
            .values(**values)
        )
    else:
        conn.execute(demands.insert().values(**values))

    log.info(
        "extension_demand: player=%d war=%.2f ext_aav=%s years=%d-%d",
        player_id, war, ext_aav, min_years, max_years,
    )
    return {
        "player_id": player_id,
        "demand_type": "extension",
        "war": float(war),
        "dollar_per_war": str(dpw),
        "min_aav": str(ext_aav),
        "min_years": min_years,
        "max_years": max_years,
        "min_total_value": str(min_total_value),
        "age": age,
        "service_years": service_years,
    }


# ── Demand computation: Buyout ──────────────────────────────────────

def compute_buyout_demand(
    conn,
    player_id: int,
    contract_id: int,
    league_year_id: int,
    league_level: int = 9,
) -> Dict[str, Any]:
    """
    Generate buyout minimum price based on remaining guaranteed money
    vs. open-market value.
    """
    t = _t(conn)
    demands = t["demands"]
    contracts = t["contracts"]
    details = t["details"]
    info = _get_player_info(conn, player_id)
    age = info["age"]
    service_years = info["service_years"]

    war = get_player_war(conn, player_id, league_year_id, league_level)
    dpw = get_current_dollar_per_war(conn, league_year_id)
    mult = age_service_multiplier(age, service_years=99)
    fa_aav = max(
        (war * dpw * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        FA_DEMAND_FLOOR,
    )

    # Remaining guaranteed: sum of future year salaries on this contract
    contract_row = conn.execute(
        select(contracts.c.years, contracts.c.current_year)
        .where(contracts.c.id == contract_id)
    ).first()

    remaining_guaranteed = Decimal("0")
    if contract_row:
        cm = contract_row._mapping
        remaining_years = cm["years"] - cm["current_year"] + 1
        remaining = conn.execute(
            select(func.coalesce(func.sum(details.c.salary), 0))
            .where(and_(
                details.c.contractID == contract_id,
                details.c.year >= cm["current_year"],
            ))
        ).scalar_one()
        remaining_guaranteed = Decimal(str(remaining))
        current_salary = conn.execute(
            select(details.c.salary)
            .where(and_(
                details.c.contractID == contract_id,
                details.c.year == cm["current_year"],
            ))
        ).scalar_one_or_none()
        salary_floor = Decimal(str(current_salary)) if current_salary else FA_DEMAND_FLOOR
    else:
        remaining_years = 1
        salary_floor = FA_DEMAND_FLOOR

    # Buyout pricing logic
    if fa_aav > remaining_guaranteed:
        # Player could earn more on open market — discount buyout
        buyout_price = (remaining_guaranteed * Decimal("0.50")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        # Player is overpaid — demands more protection
        buyout_price = (remaining_guaranteed * Decimal("0.75")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    # Floor: at least 1 year's salary
    buyout_price = max(buyout_price, salary_floor)

    existing = conn.execute(
        select(demands.c.id).where(and_(
            demands.c.player_id == player_id,
            demands.c.league_year_id == league_year_id,
            demands.c.demand_type == "buyout",
        ))
    ).first()

    values = dict(
        player_id=player_id,
        league_year_id=league_year_id,
        demand_type="buyout",
        war_snapshot=war,
        age_snapshot=age,
        service_years=service_years,
        min_years=None,
        max_years=None,
        min_aav=None,
        min_total_value=None,
        buyout_price=buyout_price,
        dollar_per_war=dpw,
    )

    if existing:
        conn.execute(
            demands.update()
            .where(demands.c.id == existing._mapping["id"])
            .values(**values)
        )
    else:
        conn.execute(demands.insert().values(**values))

    log.info(
        "buyout_demand: player=%d war=%.2f remaining=%s buyout=%s",
        player_id, war, remaining_guaranteed, buyout_price,
    )
    return {
        "player_id": player_id,
        "demand_type": "buyout",
        "war": float(war),
        "dollar_per_war": str(dpw),
        "buyout_price": str(buyout_price),
        "remaining_guaranteed": str(remaining_guaranteed),
        "age": age,
        "service_years": service_years,
    }


# ── Arbitration salary ──────────────────────────────────────────────

def compute_arb_salary(
    conn, player_id: int, league_year_id: int, arb_year: int,
    league_level: int = 9,
) -> Decimal:
    """
    Compute arbitration salary for auto-renewal (no negotiation).

    arb_year: 1, 2, or 3 (first, second, third year of arbitration)
    """
    war = get_player_war(conn, player_id, league_year_id, league_level)
    dpw = get_current_dollar_per_war(conn, league_year_id)

    arb_pct = {1: Decimal("0.40"), 2: Decimal("0.60"), 3: Decimal("0.80")}
    pct = arb_pct.get(arb_year, Decimal("0.80"))

    salary = (war * dpw * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    salary = max(salary, ARB_SALARY_FLOOR)
    salary = min(salary, ARB_SALARY_CAP)

    log.info(
        "arb_salary: player=%d arb_year=%d war=%.2f salary=%s",
        player_id, arb_year, war, salary,
    )
    return salary


# ── Cached demand lookup ────────────────────────────────────────────

def get_player_demand(
    conn, player_id: int, league_year_id: int, demand_type: str,
) -> Optional[Dict[str, Any]]:
    """Read cached demand from player_demands table."""
    t = _t(conn)
    d = t["demands"]

    row = conn.execute(
        select(d).where(and_(
            d.c.player_id == player_id,
            d.c.league_year_id == league_year_id,
            d.c.demand_type == demand_type,
        ))
    ).first()

    if not row:
        return None

    m = row._mapping
    result = {
        "player_id": int(m["player_id"]),
        "demand_type": m["demand_type"],
        "war": float(m["war_snapshot"]),
        "dollar_per_war": str(m["dollar_per_war"]),
        "age": int(m["age_snapshot"]),
        "service_years": int(m["service_years"]),
        "computed_at": str(m["computed_at"]),
    }
    if demand_type in ("fa", "extension"):
        result.update({
            "min_years": int(m["min_years"]) if m["min_years"] else None,
            "max_years": int(m["max_years"]) if m["max_years"] else None,
            "min_aav": str(m["min_aav"]) if m["min_aav"] else None,
            "min_total_value": str(m["min_total_value"]) if m["min_total_value"] else None,
        })
    if demand_type == "buyout":
        result["buyout_price"] = str(m["buyout_price"]) if m["buyout_price"] else None

    return result


# ── Batch refresh ───────────────────────────────────────────────────

def refresh_all_fa_demands(
    conn, league_year_id: int, league_level: int = 9,
) -> Dict[str, int]:
    """
    Batch-compute FA demands for all current free agents at the given level.
    Returns summary {computed: N, skipped: N}.
    """
    # Find all FA-eligible players without active held contracts
    fa_players = conn.execute(sa_text("""
        SELECT DISTINCT p.id AS player_id
        FROM simbbPlayers p
        JOIN player_service_time st ON st.player_id = p.id
        WHERE st.mlb_service_years >= 6
          AND p.id NOT IN (
              SELECT c.playerID
              FROM contracts c
              JOIN contractDetails cd ON cd.contractID = c.id
              JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
              WHERE c.isFinished = 0 AND cts.isHolder = 1
          )
    """)).all()

    computed = 0
    for row in fa_players:
        pid = row[0]
        try:
            compute_fa_demand(conn, pid, league_year_id, league_level)
            computed += 1
        except Exception as e:
            log.warning("Failed to compute FA demand for player %d: %s", pid, e)

    return {"computed": computed, "total_fas": len(fa_players)}
