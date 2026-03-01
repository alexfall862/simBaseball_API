# services/transactions.py
"""
Transaction system business logic.

Every public function takes a `conn` (caller manages commit/rollback),
validates preconditions, mutates contract tables, writes ledger entries,
and inserts a transaction_log row.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text, update, literal

logger = logging.getLogger("app")


# ---------------------------------------------------------------------------
# Table reflection (cached per-engine)
# ---------------------------------------------------------------------------

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
            "teams": Table("teams", md, autoload_with=engine),
            "ledger": Table("org_ledger_entries", md, autoload_with=engine),
            "league_years": Table("league_years", md, autoload_with=engine),
            "game_weeks": Table("game_weeks", md, autoload_with=engine),
            "tx_log": Table("transaction_log", md, autoload_with=engine),
            "trade_proposals": Table("trade_proposals", md, autoload_with=engine),
        }
    return _table_cache[eid]


def _tables_from_conn(conn) -> Dict[str, Table]:
    return _get_tables(conn.engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_all_player_contracts(conn, player_id: int) -> List[Dict[str, Any]]:
    """Return all active contracts for a player (original + extensions)."""
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    rows = conn.execute(
        select(contracts)
        .where(and_(
            contracts.c.playerID == player_id,
            contracts.c.isFinished == 0,
        ))
    ).all()
    return [dict(r._mapping) for r in rows]


def _get_signing_budget(conn, org_id: int, league_year_id: int) -> Decimal:
    """Cash on hand minus sum of already-committed signing bonuses for the year."""
    t = _tables_from_conn(conn)
    orgs = t["organizations"]
    ledger = t["ledger"]
    ly = t["league_years"]

    # Seed capital
    cash = conn.execute(
        select(func.coalesce(orgs.c.cash, 0)).where(orgs.c.id == org_id)
    ).scalar_one()

    # Current league_year value
    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    league_year_val = ly_row._mapping["league_year"] if ly_row else 0

    # Net ledger balance up to this year
    ledger_balance = conn.execute(
        select(func.coalesce(func.sum(ledger.c.amount), 0))
        .select_from(ledger.join(ly, ledger.c.league_year_id == ly.c.id))
        .where(and_(
            ledger.c.org_id == org_id,
            ly.c.league_year <= league_year_val,
        ))
    ).scalar_one()

    # Committed bonuses this year (contracts signed this year with bonus > 0)
    contracts = t["contracts"]
    committed = conn.execute(
        select(func.coalesce(func.sum(contracts.c.bonus), 0))
        .where(and_(
            contracts.c.signingOrg == org_id,
            contracts.c.leagueYearSigned == league_year_val,
            contracts.c.bonus > 0,
        ))
    ).scalar_one()

    total_balance = Decimal(str(cash)) + Decimal(str(ledger_balance))
    return total_balance - Decimal(str(committed))


def _get_roster_count(conn, org_id: int, level_id: int) -> Dict[str, Any]:
    """Return {count, max_roster, over_limit} for an org at a level."""
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]
    levels = t["levels"]

    # Count active players held by this org at this level
    league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

    count = conn.execute(
        select(func.count(func.distinct(contracts.c.playerID)))
        .select_from(
            contracts
            .join(details, details.c.contractID == contracts.c.id)
            .join(shares, shares.c.contractDetailsID == details.c.id)
        )
        .where(and_(
            contracts.c.current_level == level_id,
            contracts.c.isFinished == 0,
            shares.c.orgID == org_id,
            shares.c.isHolder == 1,
        ))
    ).scalar_one()

    # Get max_roster for this level
    max_roster = conn.execute(
        select(levels.c.max_roster).where(levels.c.id == level_id)
    ).scalar_one_or_none()

    return {
        "count": int(count),
        "max_roster": int(max_roster) if max_roster is not None else None,
        "over_limit": max_roster is not None and int(count) > int(max_roster),
    }


def _log_transaction(conn, *, transaction_type: str, league_year_id: int,
                     primary_org_id: int, secondary_org_id: int = None,
                     contract_id: int = None, player_id: int = None,
                     details: dict, executed_by: str = None,
                     notes: str = None) -> int:
    """Insert a row into transaction_log and return its id."""
    t = _tables_from_conn(conn)
    result = conn.execute(
        t["tx_log"].insert().values(
            transaction_type=transaction_type,
            league_year_id=league_year_id,
            primary_org_id=primary_org_id,
            secondary_org_id=secondary_org_id,
            contract_id=contract_id,
            player_id=player_id,
            details=json.dumps(details),
            executed_by=executed_by,
            notes=notes,
        )
    )
    return result.lastrowid


def _get_contract_or_raise(conn, contract_id: int) -> Dict[str, Any]:
    """Fetch a single contract row or raise ValueError."""
    t = _tables_from_conn(conn)
    row = conn.execute(
        select(t["contracts"]).where(t["contracts"].c.id == contract_id)
    ).first()
    if not row:
        raise ValueError(f"Contract {contract_id} not found")
    return dict(row._mapping)


def _get_holder_org(conn, contract_id: int) -> Optional[int]:
    """Find the current holder org for a contract (current year share with isHolder=1)."""
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]

    c = _get_contract_or_raise(conn, contract_id)
    detail_row = conn.execute(
        select(details.c.id)
        .where(and_(
            details.c.contractID == contract_id,
            details.c.year == c["current_year"],
        ))
    ).first()
    if not detail_row:
        return None

    holder = conn.execute(
        select(shares.c.orgID)
        .where(and_(
            shares.c.contractDetailsID == detail_row._mapping["id"],
            shares.c.isHolder == 1,
        ))
    ).first()
    return holder._mapping["orgID"] if holder else None


# ---------------------------------------------------------------------------
# 2a. Core Roster Moves
# ---------------------------------------------------------------------------

def promote_player(conn, contract_id: int, target_level_id: int,
                   league_year_id: int, executed_by: str = None) -> Dict[str, Any]:
    """Move player to a higher level."""
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)

    if c["isFinished"]:
        raise ValueError("Cannot promote on a finished contract")

    current_level = c["current_level"]
    if target_level_id <= current_level:
        raise ValueError(
            f"Target level {target_level_id} must be higher than current {current_level}"
        )

    org_id = _get_holder_org(conn, contract_id)
    if org_id is None:
        raise ValueError("No holder org found for this contract")

    conn.execute(
        update(t["contracts"])
        .where(t["contracts"].c.id == contract_id)
        .values(current_level=target_level_id)
    )

    roster = _get_roster_count(conn, org_id, target_level_id)

    tx_id = _log_transaction(
        conn,
        transaction_type="promote",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={
            "from_level": current_level,
            "to_level": target_level_id,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": c["playerID"],
        "from_level": current_level,
        "to_level": target_level_id,
        "roster_warning": roster if roster["over_limit"] else None,
    }


def demote_player(conn, contract_id: int, target_level_id: int,
                  league_year_id: int, executed_by: str = None) -> Dict[str, Any]:
    """Move player to a lower level."""
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)

    if c["isFinished"]:
        raise ValueError("Cannot demote on a finished contract")

    current_level = c["current_level"]
    if target_level_id >= current_level:
        raise ValueError(
            f"Target level {target_level_id} must be lower than current {current_level}"
        )

    org_id = _get_holder_org(conn, contract_id)
    if org_id is None:
        raise ValueError("No holder org found for this contract")

    conn.execute(
        update(t["contracts"])
        .where(t["contracts"].c.id == contract_id)
        .values(current_level=target_level_id)
    )

    tx_id = _log_transaction(
        conn,
        transaction_type="demote",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={
            "from_level": current_level,
            "to_level": target_level_id,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": c["playerID"],
        "from_level": current_level,
        "to_level": target_level_id,
    }


def place_on_ir(conn, contract_id: int, league_year_id: int,
                executed_by: str = None) -> Dict[str, Any]:
    """Place a player on the injured reserve."""
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)

    if c["isFinished"]:
        raise ValueError("Cannot IR a finished contract")
    if c.get("onIR"):
        raise ValueError("Player is already on IR")

    org_id = _get_holder_org(conn, contract_id)
    if org_id is None:
        raise ValueError("No holder org found for this contract")

    conn.execute(
        update(t["contracts"])
        .where(t["contracts"].c.id == contract_id)
        .values(onIR=1)
    )

    tx_id = _log_transaction(
        conn,
        transaction_type="ir_place",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={"level": c["current_level"]},
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": c["playerID"],
    }


def activate_from_ir(conn, contract_id: int, league_year_id: int,
                     executed_by: str = None) -> Dict[str, Any]:
    """Activate a player from the injured reserve."""
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)

    if not c.get("onIR"):
        raise ValueError("Player is not on IR")

    org_id = _get_holder_org(conn, contract_id)
    if org_id is None:
        raise ValueError("No holder org found for this contract")

    conn.execute(
        update(t["contracts"])
        .where(t["contracts"].c.id == contract_id)
        .values(onIR=0)
    )

    roster = _get_roster_count(conn, org_id, c["current_level"])

    tx_id = _log_transaction(
        conn,
        transaction_type="ir_activate",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={"level": c["current_level"]},
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": c["playerID"],
        "roster_warning": roster if roster["over_limit"] else None,
    }


# ---------------------------------------------------------------------------
# 2b. Release
# ---------------------------------------------------------------------------

def release_player(conn, contract_id: int, org_id: int,
                   league_year_id: int, executed_by: str = None) -> Dict[str, Any]:
    """
    Release a player. Guaranteed money: contract stays active, salary flows.
    Set isHolder=0 on all remaining year shares for this org.
    """
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)

    if c["isFinished"]:
        raise ValueError("Contract is already finished")

    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]

    # Get all detail IDs for remaining years (current_year onward)
    detail_rows = conn.execute(
        select(details.c.id, details.c.year)
        .where(and_(
            details.c.contractID == contract_id,
            details.c.year >= c["current_year"],
        ))
    ).all()

    detail_ids = [r._mapping["id"] for r in detail_rows]

    if detail_ids:
        conn.execute(
            update(shares)
            .where(and_(
                shares.c.contractDetailsID.in_(detail_ids),
                shares.c.orgID == org_id,
            ))
            .values(isHolder=0)
        )

    tx_id = _log_transaction(
        conn,
        transaction_type="release",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={
            "years_remaining": len(detail_ids),
            "current_level": c["current_level"],
            "affected_detail_ids": detail_ids,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": c["playerID"],
        "years_remaining_on_books": len(detail_ids),
    }


# ---------------------------------------------------------------------------
# 2c. Buyout
# ---------------------------------------------------------------------------

def buyout_player(conn, contract_id: int, org_id: int,
                  buyout_amount: Decimal, league_year_id: int,
                  game_week_id: int, executed_by: str = None) -> Dict[str, Any]:
    """
    Buy out a player's contract.
    Original contract -> isFinished=1. New 1-year buyout contract created.
    Immediate ledger entry for the buyout amount.
    """
    t = _tables_from_conn(conn)
    c = _get_contract_or_raise(conn, contract_id)
    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]
    ledger = t["ledger"]
    ly = t["league_years"]

    if c["isFinished"]:
        raise ValueError("Contract is already finished")

    # Get current league_year value
    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    league_year_val = ly_row._mapping["league_year"]

    # 1. Finish the original contract
    conn.execute(
        update(contracts)
        .where(contracts.c.id == contract_id)
        .values(isFinished=1)
    )

    # 2. Create new buyout contract
    result = conn.execute(
        contracts.insert().values(
            playerID=c["playerID"],
            years=1,
            current_year=1,
            isExtension=0,
            isBuyout=1,
            bonus=buyout_amount,
            signingOrg=org_id,
            leagueYearSigned=league_year_val,
            isFinished=0,
            current_level=c["current_level"],
            onIR=0,
        )
    )
    new_contract_id = result.lastrowid

    # 3. Create contractDetails (year=1, salary=0)
    result = conn.execute(
        details.insert().values(
            contractID=new_contract_id,
            year=1,
            salary=Decimal("0.00"),
        )
    )
    new_detail_id = result.lastrowid

    # 4. Create contractTeamShare (isHolder=0 — player is released)
    conn.execute(
        shares.insert().values(
            contractDetailsID=new_detail_id,
            orgID=org_id,
            isHolder=0,
            salary_share=Decimal("1.00"),
        )
    )

    # 5. Immediate ledger entry
    ledger_result = conn.execute(
        ledger.insert().values(
            org_id=org_id,
            league_year_id=league_year_id,
            game_week_id=game_week_id,
            entry_type="buyout",
            amount=-buyout_amount,
            contract_id=new_contract_id,
            player_id=c["playerID"],
            note=f"Buyout of contract {contract_id}",
        )
    )

    tx_id = _log_transaction(
        conn,
        transaction_type="buyout",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=c["playerID"],
        details={
            "original_contract_id": contract_id,
            "buyout_contract_id": new_contract_id,
            "buyout_amount": float(buyout_amount),
            "ledger_entry_id": ledger_result.lastrowid,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "original_contract_id": contract_id,
        "buyout_contract_id": new_contract_id,
        "buyout_amount": float(buyout_amount),
        "player_id": c["playerID"],
    }


# ---------------------------------------------------------------------------
# 2d. Free Agents
# ---------------------------------------------------------------------------

def get_free_agents(conn) -> List[Dict[str, Any]]:
    """
    Return players who have no active contract with isHolder=1.
    Includes players with all contracts isFinished=1 and released players.
    """
    t = _tables_from_conn(conn)
    players = t["players"]
    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]

    # Subquery: player_ids who have at least one active holder
    held_subq = (
        select(contracts.c.playerID)
        .select_from(
            contracts
            .join(details, details.c.contractID == contracts.c.id)
            .join(shares, shares.c.contractDetailsID == details.c.id)
        )
        .where(and_(
            contracts.c.isFinished == 0,
            shares.c.isHolder == 1,
        ))
        .group_by(contracts.c.playerID)
        .subquery()
    )

    # Players NOT in the held subquery who DO have at least one contract
    has_contract_subq = (
        select(contracts.c.playerID)
        .group_by(contracts.c.playerID)
        .subquery()
    )

    rows = conn.execute(
        select(
            players.c.id,
            players.c.firstName,
            players.c.lastName,
            players.c.age,
            players.c.position,
        )
        .where(and_(
            players.c.id.in_(select(has_contract_subq.c.playerID)),
            players.c.id.notin_(select(held_subq.c.playerID)),
        ))
        .order_by(players.c.lastName, players.c.firstName)
    ).all()

    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# 2e. Sign Free Agent
# ---------------------------------------------------------------------------

def sign_free_agent(conn, player_id: int, org_id: int, years: int,
                    salaries: List[Decimal], bonus: Decimal,
                    level_id: int, league_year_id: int,
                    game_week_id: int, executed_by: str = None) -> Dict[str, Any]:
    """
    Sign a free agent to a new contract.

    Validates: player is actually free, years 1-5, salaries length matches,
    bonus within signing budget.
    """
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    details_tbl = t["details"]
    shares_tbl = t["shares"]
    ledger = t["ledger"]
    ly = t["league_years"]

    # Validate years
    if not 1 <= years <= 5:
        raise ValueError("Contract length must be 1-5 years")
    if len(salaries) != years:
        raise ValueError(f"salaries list length ({len(salaries)}) must match years ({years})")

    # Validate player is a free agent
    held = conn.execute(
        select(func.count())
        .select_from(
            contracts
            .join(details_tbl, details_tbl.c.contractID == contracts.c.id)
            .join(shares_tbl, shares_tbl.c.contractDetailsID == details_tbl.c.id)
        )
        .where(and_(
            contracts.c.playerID == player_id,
            contracts.c.isFinished == 0,
            shares_tbl.c.isHolder == 1,
        ))
    ).scalar_one()
    if held > 0:
        raise ValueError("Player is not a free agent — they have an active holder")

    # Validate bonus budget
    budget = _get_signing_budget(conn, org_id, league_year_id)
    if Decimal(str(bonus)) > budget:
        raise ValueError(
            f"Signing bonus ({bonus}) exceeds available budget ({budget})"
        )

    # Get league_year value
    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    league_year_val = ly_row._mapping["league_year"]

    # Create contract
    result = conn.execute(
        contracts.insert().values(
            playerID=player_id,
            years=years,
            current_year=1,
            isExtension=0,
            isBuyout=0,
            bonus=bonus,
            signingOrg=org_id,
            leagueYearSigned=league_year_val,
            isFinished=0,
            current_level=level_id,
            onIR=0,
        )
    )
    new_contract_id = result.lastrowid

    # Create contractDetails + contractTeamShare for each year
    for yr in range(1, years + 1):
        det_result = conn.execute(
            details_tbl.insert().values(
                contractID=new_contract_id,
                year=yr,
                salary=salaries[yr - 1],
            )
        )
        conn.execute(
            shares_tbl.insert().values(
                contractDetailsID=det_result.lastrowid,
                orgID=org_id,
                isHolder=1,
                salary_share=Decimal("1.00"),
            )
        )

    # Immediate ledger entry for signing bonus
    ledger_entry_id = None
    if bonus > 0:
        ledger_result = conn.execute(
            ledger.insert().values(
                org_id=org_id,
                league_year_id=league_year_id,
                game_week_id=game_week_id,
                entry_type="bonus",
                amount=-Decimal(str(bonus)),
                contract_id=new_contract_id,
                player_id=player_id,
                note=f"Signing bonus for FA signing (contract {new_contract_id})",
            )
        )
        ledger_entry_id = ledger_result.lastrowid

    roster = _get_roster_count(conn, org_id, level_id)

    tx_id = _log_transaction(
        conn,
        transaction_type="signing",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=new_contract_id,
        player_id=player_id,
        details={
            "years": years,
            "salaries": [float(s) for s in salaries],
            "bonus": float(bonus),
            "level_id": level_id,
            "ledger_entry_id": ledger_entry_id,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": new_contract_id,
        "player_id": player_id,
        "years": years,
        "bonus": float(bonus),
        "roster_warning": roster if roster["over_limit"] else None,
    }


# ---------------------------------------------------------------------------
# 2f. Contract Extension
# ---------------------------------------------------------------------------

def extend_contract(conn, contract_id: int, org_id: int, years: int,
                    salaries: List[Decimal], bonus: Decimal,
                    league_year_id: int, game_week_id: int,
                    executed_by: str = None) -> Dict[str, Any]:
    """
    Extend an existing contract. Creates a new contract row (isExtension=1)
    starting the year after the current contract ends.
    """
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    details_tbl = t["details"]
    shares_tbl = t["shares"]
    ledger = t["ledger"]
    ly = t["league_years"]

    c = _get_contract_or_raise(conn, contract_id)

    if c["isFinished"]:
        raise ValueError("Cannot extend a finished contract")
    if not 1 <= years <= 5:
        raise ValueError("Extension length must be 1-5 years")
    if len(salaries) != years:
        raise ValueError(f"salaries length ({len(salaries)}) must match years ({years})")

    # Validate bonus budget
    budget = _get_signing_budget(conn, org_id, league_year_id)
    if Decimal(str(bonus)) > budget:
        raise ValueError(
            f"Signing bonus ({bonus}) exceeds available budget ({budget})"
        )

    # Extension starts the year after original contract ends
    end_year = c["leagueYearSigned"] + c["years"]

    # Create extension contract
    result = conn.execute(
        contracts.insert().values(
            playerID=c["playerID"],
            years=years,
            current_year=1,
            isExtension=1,
            isBuyout=0,
            bonus=bonus,
            signingOrg=org_id,
            leagueYearSigned=end_year,
            isFinished=0,
            current_level=c["current_level"],
            onIR=0,
        )
    )
    ext_contract_id = result.lastrowid

    for yr in range(1, years + 1):
        det_result = conn.execute(
            details_tbl.insert().values(
                contractID=ext_contract_id,
                year=yr,
                salary=salaries[yr - 1],
            )
        )
        conn.execute(
            shares_tbl.insert().values(
                contractDetailsID=det_result.lastrowid,
                orgID=org_id,
                isHolder=1,
                salary_share=Decimal("1.00"),
            )
        )

    # Immediate ledger entry for bonus
    ext_ledger_entry_id = None
    if bonus > 0:
        ledger_result = conn.execute(
            ledger.insert().values(
                org_id=org_id,
                league_year_id=league_year_id,
                game_week_id=game_week_id,
                entry_type="bonus",
                amount=-Decimal(str(bonus)),
                contract_id=ext_contract_id,
                player_id=c["playerID"],
                note=f"Extension bonus (extends contract {contract_id})",
            )
        )
        ext_ledger_entry_id = ledger_result.lastrowid

    tx_id = _log_transaction(
        conn,
        transaction_type="extension",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=ext_contract_id,
        player_id=c["playerID"],
        details={
            "original_contract_id": contract_id,
            "extension_contract_id": ext_contract_id,
            "years": years,
            "salaries": [float(s) for s in salaries],
            "bonus": float(bonus),
            "starts_league_year": end_year,
            "ledger_entry_id": ext_ledger_entry_id,
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "original_contract_id": contract_id,
        "extension_contract_id": ext_contract_id,
        "player_id": c["playerID"],
        "years": years,
        "bonus": float(bonus),
        "starts_league_year": end_year,
    }


# ---------------------------------------------------------------------------
# 2g. Trade Execution
# ---------------------------------------------------------------------------

def execute_trade(conn, trade_details: Dict[str, Any], league_year_id: int,
                  game_week_id: int, executed_by: str = None) -> Dict[str, Any]:
    """
    Execute a trade between two orgs.

    trade_details:
        org_a_id, org_b_id,
        players_to_b: [player_id, ...],
        players_to_a: [player_id, ...],
        salary_retention: {str(player_id): {retaining_org_id, retention_pct}},
        cash_a_to_b: float (positive = A sends to B)
    """
    t = _tables_from_conn(conn)
    contracts = t["contracts"]
    details_tbl = t["details"]
    shares_tbl = t["shares"]
    ledger = t["ledger"]
    ly = t["league_years"]

    org_a = trade_details["org_a_id"]
    org_b = trade_details["org_b_id"]
    players_to_b = trade_details.get("players_to_b", [])
    players_to_a = trade_details.get("players_to_a", [])
    retention_map = trade_details.get("salary_retention", {})
    cash_a_to_b = Decimal(str(trade_details.get("cash_a_to_b", 0)))

    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    league_year_val = ly_row._mapping["league_year"]

    share_mutations = []

    def _move_player(player_id: int, from_org: int, to_org: int):
        """Transfer all active contracts for a player from one org to another."""
        player_contracts = _get_all_player_contracts(conn, player_id)
        if not player_contracts:
            raise ValueError(f"No active contracts found for player {player_id}")

        retention_info = retention_map.get(str(player_id), {})
        retention_pct = Decimal(str(retention_info.get("retention_pct", 0)))

        for pc in player_contracts:
            # Get future-year details (current_year onward)
            future_details = conn.execute(
                select(details_tbl.c.id, details_tbl.c.year)
                .where(and_(
                    details_tbl.c.contractID == pc["id"],
                    details_tbl.c.year >= pc["current_year"],
                ))
            ).all()

            for fd in future_details:
                detail_id = fd._mapping["id"]

                # Snapshot old share state before mutation
                old_share_row = conn.execute(
                    select(shares_tbl.c.salary_share, shares_tbl.c.isHolder)
                    .where(and_(
                        shares_tbl.c.contractDetailsID == detail_id,
                        shares_tbl.c.orgID == from_org,
                    ))
                ).first()
                old_salary_share = float(old_share_row._mapping["salary_share"]) if old_share_row else 1.0
                old_is_holder = int(old_share_row._mapping["isHolder"]) if old_share_row else 1

                # Update old org share: isHolder=0, salary_share=retention_pct
                conn.execute(
                    update(shares_tbl)
                    .where(and_(
                        shares_tbl.c.contractDetailsID == detail_id,
                        shares_tbl.c.orgID == from_org,
                    ))
                    .values(
                        isHolder=0,
                        salary_share=retention_pct,
                    )
                )

                # Insert new org share: isHolder=1
                new_share = Decimal("1.00") - retention_pct
                new_share_result = conn.execute(
                    shares_tbl.insert().values(
                        contractDetailsID=detail_id,
                        orgID=to_org,
                        isHolder=1,
                        salary_share=new_share,
                    )
                )

                share_mutations.append({
                    "detail_id": detail_id,
                    "player_id": player_id,
                    "old_org": from_org,
                    "new_org": to_org,
                    "old_salary_share": old_salary_share,
                    "old_isHolder": old_is_holder,
                    "new_share_id": new_share_result.lastrowid,
                })

    # Move players A→B
    for pid in players_to_b:
        _move_player(pid, org_a, org_b)

    # Move players B→A
    for pid in players_to_a:
        _move_player(pid, org_b, org_a)

    # Cash considerations
    trade_ledger_ids = []
    if cash_a_to_b != 0:
        r1 = conn.execute(
            ledger.insert().values(
                org_id=org_a,
                league_year_id=league_year_id,
                game_week_id=game_week_id,
                entry_type="trade_cash",
                amount=-cash_a_to_b,
                contract_id=None,
                player_id=None,
                note=f"Trade cash (org {org_a} → org {org_b})",
            )
        )
        trade_ledger_ids.append(r1.lastrowid)
        r2 = conn.execute(
            ledger.insert().values(
                org_id=org_b,
                league_year_id=league_year_id,
                game_week_id=game_week_id,
                entry_type="trade_cash",
                amount=cash_a_to_b,
                contract_id=None,
                player_id=None,
                note=f"Trade cash (org {org_a} → org {org_b})",
            )
        )
        trade_ledger_ids.append(r2.lastrowid)

    # Merge rollback data into trade_details for the log
    rollback_details = {
        **trade_details,
        "share_mutations": share_mutations,
        "ledger_entry_ids": trade_ledger_ids,
    }

    tx_id = _log_transaction(
        conn,
        transaction_type="trade",
        league_year_id=league_year_id,
        primary_org_id=org_a,
        secondary_org_id=org_b,
        details=rollback_details,
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "org_a_id": org_a,
        "org_b_id": org_b,
        "players_to_b": players_to_b,
        "players_to_a": players_to_a,
        "cash_a_to_b": float(cash_a_to_b),
    }


# ---------------------------------------------------------------------------
# 2h. Trade Proposal Workflow
# ---------------------------------------------------------------------------

def create_trade_proposal(conn, proposing_org_id: int, receiving_org_id: int,
                          league_year_id: int,
                          proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new trade proposal."""
    t = _tables_from_conn(conn)
    result = conn.execute(
        t["trade_proposals"].insert().values(
            proposing_org_id=proposing_org_id,
            receiving_org_id=receiving_org_id,
            league_year_id=league_year_id,
            status="proposed",
            proposal=json.dumps(proposal),
        )
    )
    return {"proposal_id": result.lastrowid, "status": "proposed"}


def get_trade_proposals(conn, org_id: int = None,
                        status: str = None) -> List[Dict[str, Any]]:
    """List trade proposals with optional filters."""
    t = _tables_from_conn(conn)
    tp = t["trade_proposals"]
    stmt = select(tp)

    conditions = []
    if org_id is not None:
        conditions.append(
            (tp.c.proposing_org_id == org_id) | (tp.c.receiving_org_id == org_id)
        )
    if status is not None:
        conditions.append(tp.c.status == status)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(tp.c.proposed_at.desc())
    rows = conn.execute(stmt).all()
    results = []
    for r in rows:
        d = dict(r._mapping)
        if isinstance(d.get("proposal"), str):
            d["proposal"] = json.loads(d["proposal"])
        results.append(d)
    return results


def get_trade_proposal(conn, proposal_id: int) -> Dict[str, Any]:
    """Get a single trade proposal by ID."""
    t = _tables_from_conn(conn)
    tp = t["trade_proposals"]
    row = conn.execute(
        select(tp).where(tp.c.id == proposal_id)
    ).first()
    if not row:
        raise ValueError(f"Trade proposal {proposal_id} not found")
    d = dict(row._mapping)
    if isinstance(d.get("proposal"), str):
        d["proposal"] = json.loads(d["proposal"])
    return d


def _update_proposal_status(conn, proposal_id: int, new_status: str,
                            valid_from: List[str],
                            note: str = None,
                            timestamp_col: str = None) -> Dict[str, Any]:
    """Generic status transition for trade proposals."""
    t = _tables_from_conn(conn)
    tp = t["trade_proposals"]
    current = get_trade_proposal(conn, proposal_id)

    if current["status"] not in valid_from:
        raise ValueError(
            f"Cannot transition from '{current['status']}' to '{new_status}'"
        )

    values = {"status": new_status}
    if note is not None:
        if timestamp_col == "admin_acted_at":
            values["admin_note"] = note
        else:
            values["counterparty_note"] = note
    if timestamp_col:
        values[timestamp_col] = datetime.utcnow()

    conn.execute(
        update(tp).where(tp.c.id == proposal_id).values(**values)
    )
    return get_trade_proposal(conn, proposal_id)


def accept_trade_proposal(conn, proposal_id: int,
                          note: str = None) -> Dict[str, Any]:
    return _update_proposal_status(
        conn, proposal_id, "counterparty_accepted",
        valid_from=["proposed"],
        note=note, timestamp_col="counterparty_acted_at",
    )


def reject_trade_proposal(conn, proposal_id: int,
                          note: str = None) -> Dict[str, Any]:
    return _update_proposal_status(
        conn, proposal_id, "counterparty_rejected",
        valid_from=["proposed"],
        note=note, timestamp_col="counterparty_acted_at",
    )


def cancel_trade_proposal(conn, proposal_id: int) -> Dict[str, Any]:
    return _update_proposal_status(
        conn, proposal_id, "cancelled",
        valid_from=["proposed", "counterparty_accepted"],
    )


def admin_reject_trade(conn, proposal_id: int,
                       note: str = None) -> Dict[str, Any]:
    return _update_proposal_status(
        conn, proposal_id, "admin_rejected",
        valid_from=["counterparty_accepted"],
        note=note, timestamp_col="admin_acted_at",
    )


def admin_approve_trade(conn, proposal_id: int, league_year_id: int,
                        game_week_id: int, note: str = None,
                        executed_by: str = None) -> Dict[str, Any]:
    """Admin approves a trade proposal → auto-executes it."""
    t = _tables_from_conn(conn)
    tp = t["trade_proposals"]
    proposal = get_trade_proposal(conn, proposal_id)

    if proposal["status"] != "counterparty_accepted":
        raise ValueError(
            f"Cannot admin-approve from status '{proposal['status']}'"
        )

    # Build trade_details from the proposal
    prop_data = proposal["proposal"]
    trade_details = {
        "org_a_id": proposal["proposing_org_id"],
        "org_b_id": proposal["receiving_org_id"],
        "players_to_b": prop_data.get("players_to_b", []),
        "players_to_a": prop_data.get("players_to_a", []),
        "salary_retention": prop_data.get("salary_retention", {}),
        "cash_a_to_b": prop_data.get("cash_a_to_b", 0),
    }

    # Execute the trade
    trade_result = execute_trade(
        conn, trade_details, league_year_id, game_week_id, executed_by
    )

    # Update proposal status
    conn.execute(
        update(tp).where(tp.c.id == proposal_id).values(
            status="executed",
            admin_acted_at=datetime.utcnow(),
            executed_at=datetime.utcnow(),
            admin_note=note,
        )
    )

    return {
        "proposal_id": proposal_id,
        "status": "executed",
        "trade_result": trade_result,
    }


# ---------------------------------------------------------------------------
# 2i. Transaction Log & Roster Status (read helpers)
# ---------------------------------------------------------------------------

def get_transaction_log(conn, org_id: int = None, transaction_type: str = None,
                        league_year_id: int = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
    """Query the transaction audit log with optional filters."""
    t = _tables_from_conn(conn)
    tx = t["tx_log"]
    stmt = select(tx)

    conditions = []
    if org_id is not None:
        conditions.append(
            (tx.c.primary_org_id == org_id) | (tx.c.secondary_org_id == org_id)
        )
    if transaction_type is not None:
        conditions.append(tx.c.transaction_type == transaction_type)
    if league_year_id is not None:
        conditions.append(tx.c.league_year_id == league_year_id)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(tx.c.executed_at.desc()).limit(limit)
    rows = conn.execute(stmt).all()
    results = []
    for r in rows:
        d = dict(r._mapping)
        if isinstance(d.get("details"), str):
            d["details"] = json.loads(d["details"])
        results.append(d)
    return results


def get_org_roster(conn, org_id: int) -> List[Dict[str, Any]]:
    """Return all active players held by an org with contract info."""
    t = _tables_from_conn(conn)
    c = t["contracts"]
    d = t["details"]
    s = t["shares"]
    p = t["players"]

    # Get all active contracts where this org is the holder.
    # Join to the first detail row (year=1) for salary display.
    q = (
        select(
            c.c.id.label("contract_id"),
            c.c.playerID,
            c.c.current_level,
            c.c.onIR,
            p.c.firstName,
            p.c.lastName,
            p.c.position,
            d.c.salary,
        )
        .select_from(
            c.join(d, d.c.contractID == c.c.id)
            .join(s, s.c.contractDetailsID == d.c.id)
            .join(p, c.c.playerID == p.c.id)
        )
        .where(
            and_(
                s.c.orgID == org_id,
                s.c.isHolder == 1,
                c.c.isFinished == 0,
                d.c.year == 1,
            )
        )
        .order_by(c.c.current_level.desc(), p.c.lastName, p.c.firstName)
    )
    rows = conn.execute(q).all()
    return [
        {
            "contract_id": r._mapping["contract_id"],
            "player_id": r._mapping["playerID"],
            "player_name": f"{r._mapping['firstName']} {r._mapping['lastName']}",
            "position": r._mapping["position"],
            "current_level": r._mapping["current_level"],
            "onIR": r._mapping["onIR"],
            "salary": float(r._mapping["salary"]) if r._mapping["salary"] else 0,
        }
        for r in rows
    ]


def get_roster_status(conn, org_id: int) -> List[Dict[str, Any]]:
    """Return roster count vs limit for each level for an org."""
    t = _tables_from_conn(conn)
    levels = t["levels"]
    rows = conn.execute(
        select(levels.c.id, levels.c.name, levels.c.max_roster)
        .order_by(levels.c.id.desc())
    ).all()

    result = []
    for r in rows:
        lm = r._mapping
        level_id = lm["id"]
        roster = _get_roster_count(conn, org_id, level_id)
        result.append({
            "level_id": level_id,
            "level_name": lm["name"],
            "count": roster["count"],
            "max_roster": roster["max_roster"],
            "over_limit": roster["over_limit"],
        })
    return result


# ---------------------------------------------------------------------------
# 3. Transaction Rollback
# ---------------------------------------------------------------------------

def _delete_contract_chain(conn, contract_id: int):
    """Delete a contract and all its details + shares (child-first order)."""
    t = _tables_from_conn(conn)
    details = t["details"]
    shares = t["shares"]
    contracts = t["contracts"]

    detail_ids = [
        r._mapping["id"]
        for r in conn.execute(
            select(details.c.id).where(details.c.contractID == contract_id)
        ).all()
    ]
    if detail_ids:
        conn.execute(
            shares.delete().where(shares.c.contractDetailsID.in_(detail_ids))
        )
    conn.execute(details.delete().where(details.c.contractID == contract_id))
    conn.execute(contracts.delete().where(contracts.c.id == contract_id))


def rollback_transaction(conn, transaction_id: int,
                         executed_by: str = None) -> Dict[str, Any]:
    """
    Reverse a previously executed transaction using data captured in its
    details JSON. Inserts a new log entry noting the rollback.
    """
    t = _tables_from_conn(conn)
    tx_log = t["tx_log"]
    contracts = t["contracts"]
    shares = t["shares"]
    ledger = t["ledger"]

    # Fetch the transaction
    row = conn.execute(
        select(tx_log).where(tx_log.c.id == transaction_id)
    ).first()
    if not row:
        raise ValueError(f"Transaction {transaction_id} not found")

    tx = dict(row._mapping)
    tx_type = tx["transaction_type"]
    details = tx["details"]
    if isinstance(details, str):
        details = json.loads(details)

    contract_id = tx.get("contract_id")

    if tx_type in ("promote", "demote"):
        from_level = details["from_level"]
        conn.execute(
            update(contracts)
            .where(contracts.c.id == contract_id)
            .values(current_level=from_level)
        )

    elif tx_type == "ir_place":
        conn.execute(
            update(contracts)
            .where(contracts.c.id == contract_id)
            .values(onIR=0)
        )

    elif tx_type == "ir_activate":
        conn.execute(
            update(contracts)
            .where(contracts.c.id == contract_id)
            .values(onIR=1)
        )

    elif tx_type == "release":
        affected_ids = details.get("affected_detail_ids", [])
        if affected_ids:
            conn.execute(
                update(shares)
                .where(and_(
                    shares.c.contractDetailsID.in_(affected_ids),
                    shares.c.orgID == tx["primary_org_id"],
                ))
                .values(isHolder=1)
            )

    elif tx_type == "buyout":
        buyout_cid = details.get("buyout_contract_id")
        original_cid = details.get("original_contract_id")
        ledger_eid = details.get("ledger_entry_id")

        if buyout_cid:
            _delete_contract_chain(conn, buyout_cid)
        if ledger_eid:
            conn.execute(ledger.delete().where(ledger.c.id == ledger_eid))
        if original_cid:
            conn.execute(
                update(contracts)
                .where(contracts.c.id == original_cid)
                .values(isFinished=0)
            )

    elif tx_type == "signing":
        ledger_eid = details.get("ledger_entry_id")
        if contract_id:
            _delete_contract_chain(conn, contract_id)
        if ledger_eid:
            conn.execute(ledger.delete().where(ledger.c.id == ledger_eid))

    elif tx_type == "extension":
        ext_cid = details.get("extension_contract_id")
        ledger_eid = details.get("ledger_entry_id")
        if ext_cid:
            _delete_contract_chain(conn, ext_cid)
        if ledger_eid:
            conn.execute(ledger.delete().where(ledger.c.id == ledger_eid))

    elif tx_type == "trade":
        # Reverse share mutations
        for mut in details.get("share_mutations", []):
            new_share_id = mut.get("new_share_id")
            if new_share_id:
                conn.execute(
                    shares.delete().where(shares.c.id == new_share_id)
                )
            conn.execute(
                update(shares)
                .where(and_(
                    shares.c.contractDetailsID == mut["detail_id"],
                    shares.c.orgID == mut["old_org"],
                ))
                .values(
                    isHolder=mut["old_isHolder"],
                    salary_share=Decimal(str(mut["old_salary_share"])),
                )
            )

        # Delete cash ledger entries
        for lid in details.get("ledger_entry_ids", []):
            conn.execute(ledger.delete().where(ledger.c.id == lid))

    else:
        raise ValueError(f"Rollback not supported for transaction type '{tx_type}'")

    # Log the rollback
    rollback_tx_id = _log_transaction(
        conn,
        transaction_type=tx_type,
        league_year_id=tx["league_year_id"],
        primary_org_id=tx["primary_org_id"],
        secondary_org_id=tx.get("secondary_org_id"),
        contract_id=contract_id,
        player_id=tx.get("player_id"),
        details={"rolled_back_transaction_id": transaction_id},
        executed_by=executed_by,
        notes=f"ROLLBACK of transaction {transaction_id}",
    )

    return {
        "rollback_transaction_id": rollback_tx_id,
        "rolled_back_transaction_id": transaction_id,
        "transaction_type": tx_type,
    }
