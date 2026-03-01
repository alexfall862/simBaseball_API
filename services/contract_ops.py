"""
Contract operations service — service time tracking, end-of-season processing,
payroll projections, and contract status queries for the frontend.
"""
import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    MetaData, Table, and_, func, literal, select, text, update,
)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

MINOR_SALARY = Decimal("40000.00")
PRE_ARB_SALARY = Decimal("800000.00")

ARB_THRESHOLD = 3   # service years to become arb-eligible
FA_THRESHOLD = 6    # service years to become FA-eligible

# ── Table reflection cache ───────────────────────────────────────────

_table_cache: Dict[int, Dict[str, Table]] = {}


def _get_tables(engine) -> Dict[str, Table]:
    eid = id(engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "contracts": Table("contracts", md, autoload_with=engine),
            "details": Table("contractDetails", md, autoload_with=engine),
            "shares": Table("contractTeamShare", md, autoload_with=engine),
            "players": Table("simbbPlayers", md, autoload_with=engine),
            "organizations": Table("organizations", md, autoload_with=engine),
            "levels": Table("levels", md, autoload_with=engine),
            "league_years": Table("league_years", md, autoload_with=engine),
            "tx_log": Table("transaction_log", md, autoload_with=engine),
            "service_time": Table("player_service_time", md, autoload_with=engine),
        }
    return _table_cache[eid]


def _t(conn) -> Dict[str, Table]:
    return _get_tables(conn.engine)


# ── Contract phase helpers ───────────────────────────────────────────

def _determine_phase(level: int, service_years: int) -> str:
    """Return the contract phase string for a player."""
    if level < 9:
        return "minor"
    if service_years < ARB_THRESHOLD:
        return "pre_arb"
    if service_years < FA_THRESHOLD:
        return "arb_eligible"
    return "fa_eligible"


# ── Public: single-player contract status ────────────────────────────

def get_player_contract_status(conn, player_id: int) -> Optional[Dict[str, Any]]:
    """
    Return enriched contract + service-time info for one player.
    Returns None if the player has no active held contract.
    """
    t = _t(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    p = t["players"]
    st = t["service_time"]

    # Active contract where this player is held
    row = conn.execute(
        select(
            c.c.id.label("contract_id"),
            c.c.playerID,
            c.c.years,
            c.c.current_year,
            c.c.current_level,
            c.c.isExtension,
            c.c.leagueYearSigned,
            c.c.onIR,
            p.c.firstname,
            p.c.lastname,
            p.c.age,
            d.c.salary,
        )
        .select_from(
            c.join(d, and_(d.c.contractID == c.c.id, d.c.year == c.c.current_year))
            .join(s, s.c.contractDetailsID == d.c.id)
            .join(p, p.c.id == c.c.playerID)
        )
        .where(and_(
            c.c.playerID == player_id,
            c.c.isFinished == 0,
            s.c.isHolder == 1,
        ))
        .limit(1)
    ).first()

    if not row:
        return None
    m = row._mapping

    # Service time
    st_row = conn.execute(
        select(st.c.mlb_service_years)
        .where(st.c.player_id == player_id)
    ).first()
    service_years = st_row._mapping["mlb_service_years"] if st_row else 0

    # Extension check
    end_year = m["leagueYearSigned"] + m["years"]
    ext_exists = conn.execute(
        select(func.count())
        .select_from(c)
        .where(and_(
            c.c.playerID == player_id,
            c.c.isExtension == 1,
            c.c.isFinished == 0,
            c.c.leagueYearSigned == end_year,
        ))
    ).scalar_one() > 0

    phase = _determine_phase(m["current_level"], service_years)
    years_remaining = m["years"] - m["current_year"]

    return {
        "player_id": m["playerID"],
        "player_name": f"{m['firstname']} {m['lastname']}",
        "age": m["age"],
        "contract_id": m["contract_id"],
        "current_level": m["current_level"],
        "years": m["years"],
        "current_year": m["current_year"],
        "years_remaining": years_remaining,
        "salary": float(m["salary"]) if m["salary"] else 0,
        "is_extension": bool(m["isExtension"]),
        "on_ir": bool(m["onIR"]),
        "mlb_service_years": service_years,
        "contract_phase": phase,
        "years_to_arb": max(0, ARB_THRESHOLD - service_years) if phase in ("minor", "pre_arb") else None,
        "years_to_fa": max(0, FA_THRESHOLD - service_years) if phase != "fa_eligible" else None,
        "is_expiring": m["current_year"] == m["years"],
        "has_extension": ext_exists,
    }


# ── Public: org-wide contract overview ───────────────────────────────

def get_org_contract_overview(conn, org_id: int) -> List[Dict[str, Any]]:
    """
    Return contract status for every active player held by an org.
    Sorted by level (desc) then last name.
    """
    t = _t(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    p = t["players"]
    st = t["service_time"]

    rows = conn.execute(
        select(
            c.c.id.label("contract_id"),
            c.c.playerID,
            c.c.years,
            c.c.current_year,
            c.c.current_level,
            c.c.isExtension,
            c.c.leagueYearSigned,
            c.c.onIR,
            p.c.firstname,
            p.c.lastname,
            p.c.age,
            p.c.ptype,
            d.c.salary,
            func.coalesce(st.c.mlb_service_years, 0).label("mlb_service_years"),
        )
        .select_from(
            c.join(d, and_(d.c.contractID == c.c.id, d.c.year == c.c.current_year))
            .join(s, s.c.contractDetailsID == d.c.id)
            .join(p, p.c.id == c.c.playerID)
            .outerjoin(st, st.c.player_id == c.c.playerID)
        )
        .where(and_(
            s.c.orgID == org_id,
            s.c.isHolder == 1,
            c.c.isFinished == 0,
        ))
        .order_by(c.c.current_level.desc(), p.c.lastname, p.c.firstname)
    ).all()

    results = []
    for row in rows:
        m = row._mapping
        svc = m["mlb_service_years"]
        phase = _determine_phase(m["current_level"], svc)
        years_remaining = m["years"] - m["current_year"]

        results.append({
            "player_id": m["playerID"],
            "player_name": f"{m['firstname']} {m['lastname']}",
            "age": m["age"],
            "position": m["ptype"],
            "contract_id": m["contract_id"],
            "current_level": m["current_level"],
            "years": m["years"],
            "current_year": m["current_year"],
            "years_remaining": years_remaining,
            "salary": float(m["salary"]) if m["salary"] else 0,
            "on_ir": bool(m["onIR"]),
            "mlb_service_years": svc,
            "contract_phase": phase,
            "years_to_arb": max(0, ARB_THRESHOLD - svc) if phase in ("minor", "pre_arb") else None,
            "years_to_fa": max(0, FA_THRESHOLD - svc) if phase != "fa_eligible" else None,
            "is_expiring": m["current_year"] == m["years"],
        })

    return results


# ── Public: end-of-season processing ─────────────────────────────────

def process_end_of_season(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Run full end-of-season contract processing:
      1. Credit MLB service time
      2. Advance mid-contract current_year
      3. Process expiring contracts (extensions, auto-renewal, FA)
    Returns a summary dict.
    """
    t = _t(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    st = t["service_time"]
    ly = t["league_years"]

    # Resolve league_year value
    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    if not ly_row:
        raise ValueError(f"league_year_id {league_year_id} not found")
    league_year_val = ly_row._mapping["league_year"]

    summary = {
        "league_year": league_year_val,
        "service_time_credited": 0,
        "contracts_advanced": 0,
        "contracts_expired": 0,
        "auto_renewed_minor": 0,
        "auto_renewed_pre_arb": 0,
        "became_free_agents": 0,
        "extensions_activated": 0,
    }

    # ── Step 1: Credit service time ──────────────────────────────────
    # Find all players at MLB level (9) with active held contracts
    mlb_players = conn.execute(
        select(func.distinct(c.c.playerID))
        .select_from(
            c.join(d, d.c.contractID == c.c.id)
            .join(s, s.c.contractDetailsID == d.c.id)
        )
        .where(and_(
            c.c.current_level == 9,
            c.c.isFinished == 0,
            s.c.isHolder == 1,
        ))
    ).all()

    for row in mlb_players:
        pid = row[0]
        # UPSERT: insert if not exists, increment if not already credited this year
        existing = conn.execute(
            select(st.c.mlb_service_years, st.c.last_accrual_year)
            .where(st.c.player_id == pid)
        ).first()

        if existing is None:
            conn.execute(st.insert().values(
                player_id=pid,
                mlb_service_years=1,
                last_accrual_year=league_year_val,
            ))
            summary["service_time_credited"] += 1
        elif existing._mapping["last_accrual_year"] != league_year_val:
            conn.execute(
                update(st)
                .where(st.c.player_id == pid)
                .values(
                    mlb_service_years=st.c.mlb_service_years + 1,
                    last_accrual_year=league_year_val,
                )
            )
            summary["service_time_credited"] += 1

    # ── Step 2: Advance mid-contract players ─────────────────────────
    result = conn.execute(
        update(c)
        .where(and_(
            c.c.isFinished == 0,
            c.c.current_year < c.c.years,
        ))
        .values(current_year=c.c.current_year + 1)
    )
    summary["contracts_advanced"] = result.rowcount

    # ── Step 3: Process expiring contracts ───────────────────────────
    # All contracts in their final year (current_year == years, not yet finished)
    expiring = conn.execute(
        select(
            c.c.id.label("contract_id"),
            c.c.playerID,
            c.c.years,
            c.c.current_level,
            c.c.leagueYearSigned,
        )
        .where(and_(
            c.c.isFinished == 0,
            c.c.current_year == c.c.years,
        ))
    ).all()

    for row in expiring:
        m = row._mapping
        contract_id = m["contract_id"]
        player_id = m["playerID"]
        level = m["current_level"]
        end_year = m["leagueYearSigned"] + m["years"]

        summary["contracts_expired"] += 1

        # Check for extension
        ext = conn.execute(
            select(c.c.id)
            .where(and_(
                c.c.playerID == player_id,
                c.c.isExtension == 1,
                c.c.isFinished == 0,
                c.c.leagueYearSigned == end_year,
                c.c.id != contract_id,
            ))
        ).first()

        if ext:
            # Extension takes over — just finish the old contract
            conn.execute(
                update(c).where(c.c.id == contract_id).values(isFinished=1)
            )
            summary["extensions_activated"] += 1
            continue

        # No extension — determine renewal or FA
        # Get current holder org
        holder_row = conn.execute(
            select(s.c.orgID)
            .select_from(
                d.join(s, s.c.contractDetailsID == d.c.id)
            )
            .where(and_(
                d.c.contractID == contract_id,
                d.c.year == m["years"],
                s.c.isHolder == 1,
            ))
        ).first()
        holder_org = holder_row._mapping["orgID"] if holder_row else None

        # Get service time
        st_row = conn.execute(
            select(st.c.mlb_service_years).where(st.c.player_id == player_id)
        ).first()
        service_years = st_row._mapping["mlb_service_years"] if st_row else 0

        if level < 9:
            # Minor league auto-renewal
            if holder_org:
                _create_renewal_contract(
                    conn, contract_id, player_id, holder_org,
                    MINOR_SALARY, level, end_year, league_year_id,
                )
                summary["auto_renewed_minor"] += 1
            else:
                conn.execute(
                    update(c).where(c.c.id == contract_id).values(isFinished=1)
                )
                summary["became_free_agents"] += 1

        elif service_years < ARB_THRESHOLD:
            # Pre-arb MLB auto-renewal
            if holder_org:
                _create_renewal_contract(
                    conn, contract_id, player_id, holder_org,
                    PRE_ARB_SALARY, level, end_year, league_year_id,
                )
                summary["auto_renewed_pre_arb"] += 1
            else:
                conn.execute(
                    update(c).where(c.c.id == contract_id).values(isFinished=1)
                )
                summary["became_free_agents"] += 1

        else:
            # Arb-eligible or FA-eligible — becomes free agent
            conn.execute(
                update(c).where(c.c.id == contract_id).values(isFinished=1)
            )
            summary["became_free_agents"] += 1

    log.info(
        "end_of_season: year=%d credited=%d advanced=%d expired=%d "
        "renewed_minor=%d renewed_prearb=%d fa=%d ext=%d",
        league_year_val,
        summary["service_time_credited"],
        summary["contracts_advanced"],
        summary["contracts_expired"],
        summary["auto_renewed_minor"],
        summary["auto_renewed_pre_arb"],
        summary["became_free_agents"],
        summary["extensions_activated"],
    )
    return summary


# ── Private: create renewal contract ─────────────────────────────────

def _create_renewal_contract(
    conn,
    old_contract_id: int,
    player_id: int,
    org_id: int,
    salary: Decimal,
    level: int,
    league_year_val: int,
    league_year_id: int,
) -> int:
    """
    Create a 1-year renewal contract, finish the old one, and log it.
    Returns the new contract ID.
    """
    t = _t(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    tx = t["tx_log"]

    # Finish old contract
    conn.execute(
        update(c).where(c.c.id == old_contract_id).values(isFinished=1)
    )

    # Create new 1-year contract
    result = conn.execute(
        c.insert().values(
            playerID=player_id,
            years=1,
            current_year=1,
            isExtension=0,
            isBuyout=0,
            bonus=Decimal("0.00"),
            signingOrg=org_id,
            leagueYearSigned=league_year_val,
            isFinished=0,
            current_level=level,
            onIR=0,
        )
    )
    new_id = result.lastrowid

    # Create detail row
    det_result = conn.execute(
        d.insert().values(
            contractID=new_id,
            year=1,
            salary=salary,
        )
    )

    # Create share row
    conn.execute(
        s.insert().values(
            contractDetailsID=det_result.lastrowid,
            orgID=org_id,
            isHolder=1,
            salary_share=Decimal("1.00"),
        )
    )

    # Log the renewal
    conn.execute(
        tx.insert().values(
            transaction_type="renewal",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            contract_id=new_id,
            player_id=player_id,
            details=json.dumps({
                "old_contract_id": old_contract_id,
                "new_contract_id": new_id,
                "salary": float(salary),
                "level": level,
            }),
            notes=f"Auto-renewal of contract {old_contract_id}",
        )
    )

    return new_id


# ── Public: payroll projection ────────────────────────────────────────

def get_payroll_projection(conn, org_id: int) -> Dict[str, Any]:
    """
    Return multi-year salary projection for an org.

    Includes all active contracts where the org appears in contractTeamShare
    (both as holder and as retained-salary payer). Returns per-player salary
    schedules, year totals, and dead-money entries.
    """
    t = _t(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    p = t["players"]
    st = t["service_time"]
    ly = t["league_years"]

    # Get current league year
    current_ly_row = conn.execute(
        select(ly.c.league_year)
        .order_by(ly.c.league_year.desc())
        .limit(1)
    ).first()
    current_league_year = current_ly_row._mapping["league_year"] if current_ly_row else 2026

    # Big query: all contract detail rows for this org's active contracts
    league_year_expr = (c.c.leagueYearSigned + d.c.year - 1).label("league_year")
    team_owes_expr = func.round(d.c.salary * s.c.salary_share, 2).label("team_owes")

    rows = conn.execute(
        select(
            c.c.id.label("contract_id"),
            c.c.playerID,
            c.c.years,
            c.c.current_year,
            c.c.current_level,
            c.c.isExtension,
            c.c.isBuyout,
            c.c.bonus,
            c.c.leagueYearSigned,
            d.c.year.label("contract_year"),
            d.c.salary.label("gross_salary"),
            s.c.orgID,
            s.c.isHolder,
            s.c.salary_share,
            team_owes_expr,
            league_year_expr,
            p.c.firstname,
            p.c.lastname,
            p.c.age,
            p.c.ptype,
            func.coalesce(st.c.mlb_service_years, 0).label("mlb_service_years"),
        )
        .select_from(
            c.join(d, d.c.contractID == c.c.id)
            .join(s, s.c.contractDetailsID == d.c.id)
            .join(p, p.c.id == c.c.playerID)
            .outerjoin(st, st.c.player_id == c.c.playerID)
        )
        .where(and_(
            c.c.isFinished == 0,
            s.c.orgID == org_id,
            d.c.year >= c.c.current_year,
        ))
        .order_by(league_year_expr, d.c.salary.desc())
    ).all()

    # Separate into held contracts (active roster) and retained salary (dead money)
    # Key: (contract_id, player_id) → player info + salary_schedule list
    held_players: Dict[int, Dict[str, Any]] = {}  # keyed by contract_id
    dead_money: Dict[int, Dict[str, Any]] = {}     # keyed by contract_id
    year_totals: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {"total_salary": 0.0, "player_count": set()}
    )

    for row in rows:
        m = row._mapping
        contract_id = m["contract_id"]
        is_holder = bool(m["isHolder"])
        l_year = m["league_year"]
        owes = float(m["team_owes"]) if m["team_owes"] else 0.0

        schedule_entry = {
            "league_year": l_year,
            "contract_year": m["contract_year"],
            "gross_salary": float(m["gross_salary"]) if m["gross_salary"] else 0.0,
            "team_share": float(m["salary_share"]) if m["salary_share"] else 1.0,
            "team_owes": owes,
            "is_current": m["contract_year"] == m["current_year"],
        }

        if is_holder:
            if contract_id not in held_players:
                svc = m["mlb_service_years"]
                phase = _determine_phase(m["current_level"], svc)
                held_players[contract_id] = {
                    "player_id": m["playerID"],
                    "player_name": f"{m['firstname']} {m['lastname']}",
                    "position": m["ptype"],
                    "age": m["age"],
                    "contract_id": contract_id,
                    "is_extension": bool(m["isExtension"]),
                    "is_buyout": bool(m["isBuyout"]),
                    "contract_phase": phase,
                    "mlb_service_years": svc,
                    "current_level": m["current_level"],
                    "bonus": float(m["bonus"]) if m["bonus"] else 0.0,
                    "salary_schedule": [],
                }
            held_players[contract_id]["salary_schedule"].append(schedule_entry)
        else:
            # Dead money — retained salary from trades
            if contract_id not in dead_money:
                dead_money[contract_id] = {
                    "player_id": m["playerID"],
                    "player_name": f"{m['firstname']} {m['lastname']}",
                    "contract_id": contract_id,
                    "remaining": [],
                }
            dead_money[contract_id]["remaining"].append({
                "league_year": l_year,
                "team_owes": owes,
            })

        # Aggregate year totals (both held and retained count toward payroll)
        year_totals[l_year]["total_salary"] += owes
        year_totals[l_year]["player_count"].add(m["playerID"])

    # Convert year_totals sets to counts and sort
    sorted_totals = {}
    for yr in sorted(year_totals.keys()):
        sorted_totals[str(yr)] = {
            "total_salary": round(year_totals[yr]["total_salary"], 2),
            "player_count": len(year_totals[yr]["player_count"]),
        }

    return {
        "org_id": org_id,
        "current_league_year": current_league_year,
        "players": list(held_players.values()),
        "year_totals": sorted_totals,
        "dead_money": list(dead_money.values()),
    }
