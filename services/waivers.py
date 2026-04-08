# services/waivers.py
"""
Waiver wire system — handles mid-season player releases.

When a player is released, they sit on waivers for 1 week. Any org can place
a claim during that period. On expiry, the claimant with the worst record
(reverse standings order) wins and takes on the full remaining contract.
If no one claims, the contract is finished and the player enters the FA pool
with tier-appropriate demands.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    MetaData, Table, and_, func, select, text as sa_text, update,
)

from services.attribute_visibility import fuzz_displayovr

log = logging.getLogger(__name__)


def _fuzz_ovr(true_ovr, org_id, player_id):
    """Fuzz displayovr if an org_id is provided, else return raw."""
    if org_id is None:
        return true_ovr
    return fuzz_displayovr(true_ovr, org_id, player_id)


# ── Constants (mirror contract_ops.py) ────────────────────────────────
MINOR_SALARY = Decimal("40000")
PRE_ARB_SALARY = Decimal("800000")
FA_THRESHOLD = 6

# ── Table reflection cache ────────────────────────────────────────────

_table_cache: Dict[int, Dict[str, Table]] = {}


def _t(conn) -> Dict[str, Table]:
    eid = id(conn.engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "waiver_claims":     Table("waiver_claims", md, autoload_with=conn.engine),
            "waiver_bids":       Table("waiver_claim_bids", md, autoload_with=conn.engine),
            "contracts":         Table("contracts", md, autoload_with=conn.engine),
            "details":           Table("contractDetails", md, autoload_with=conn.engine),
            "shares":            Table("contractTeamShare", md, autoload_with=conn.engine),
            "players":           Table("simbbPlayers", md, autoload_with=conn.engine),
            "service_time":      Table("player_service_time", md, autoload_with=conn.engine),
            "demands":           Table("player_demands", md, autoload_with=conn.engine),
            "game_results":      Table("game_results", md, autoload_with=conn.engine),
            "teams":             Table("teams", md, autoload_with=conn.engine),
            "organizations":     Table("organizations", md, autoload_with=conn.engine),
            "tx_log":            Table("transaction_log", md, autoload_with=conn.engine),
        }
    return _table_cache[eid]


# ── Waiver placement ─────────────────────────────────────────────────

def place_on_waivers(
    conn,
    player_id: int,
    contract_id: int,
    releasing_org_id: int,
    league_year_id: int,
    current_week: int,
    transaction_id: int,
    last_level: int,
    service_years: int,
) -> Dict[str, Any]:
    """
    Place a released player on the waiver wire for 1 week.
    Called from release_player() in transactions.py.
    """
    t = _t(conn)
    wc = t["waiver_claims"]

    # Prevent duplicate active waiver for same player
    existing = conn.execute(
        select(wc.c.id).where(and_(
            wc.c.player_id == player_id,
            wc.c.status == "active",
        ))
    ).first()
    if existing:
        return {
            "waiver_claim_id": existing._mapping["id"],
            "already_active": True,
        }

    expires_week = current_week + 1

    result = conn.execute(wc.insert().values(
        player_id=player_id,
        contract_id=contract_id,
        releasing_org_id=releasing_org_id,
        league_year_id=league_year_id,
        placed_week=current_week,
        expires_week=expires_week,
        status="active",
        transaction_id=transaction_id,
        last_level=last_level,
        service_years=service_years,
    ))
    waiver_claim_id = result.lastrowid

    log.info(
        "place_on_waivers: player=%d contract=%d org=%d week=%d expires=%d",
        player_id, contract_id, releasing_org_id, current_week, expires_week,
    )
    return {
        "waiver_claim_id": waiver_claim_id,
        "expires_week": expires_week,
    }


# ── Waiver claim bidding ─────────────────────────────────────────────

def submit_waiver_claim(
    conn, waiver_claim_id: int, org_id: int,
) -> Dict[str, Any]:
    """Place a waiver claim on behalf of an org."""
    t = _t(conn)
    wc = t["waiver_claims"]
    bids = t["waiver_bids"]

    # Validate waiver exists and is active
    claim = conn.execute(
        select(wc).where(wc.c.id == waiver_claim_id)
    ).first()
    if not claim:
        raise ValueError(f"Waiver claim {waiver_claim_id} not found")

    cm = claim._mapping
    if cm["status"] != "active":
        raise ValueError(f"Waiver claim {waiver_claim_id} is no longer active (status={cm['status']})")

    if cm["releasing_org_id"] == org_id:
        raise ValueError("Cannot claim your own released player")

    # Check for duplicate bid
    existing = conn.execute(
        select(bids.c.id).where(and_(
            bids.c.waiver_claim_id == waiver_claim_id,
            bids.c.org_id == org_id,
        ))
    ).first()
    if existing:
        return {"bid_id": existing._mapping["id"], "already_claimed": True}

    result = conn.execute(bids.insert().values(
        waiver_claim_id=waiver_claim_id,
        org_id=org_id,
    ))
    log.info("waiver_claim_bid: waiver=%d org=%d", waiver_claim_id, org_id)
    return {"bid_id": result.lastrowid, "waiver_claim_id": waiver_claim_id}


def withdraw_waiver_claim(
    conn, waiver_claim_id: int, org_id: int,
) -> Dict[str, Any]:
    """Withdraw a previously placed waiver claim."""
    t = _t(conn)
    bids = t["waiver_bids"]

    result = conn.execute(
        bids.delete().where(and_(
            bids.c.waiver_claim_id == waiver_claim_id,
            bids.c.org_id == org_id,
        ))
    )
    if result.rowcount == 0:
        raise ValueError("No bid found to withdraw")

    log.info("waiver_claim_withdraw: waiver=%d org=%d", waiver_claim_id, org_id)
    return {"withdrawn": True}


# ── Weekly waiver processing ──────────────────────────────────────────

def process_expired_waivers(
    conn, current_week: int, league_year_id: int,
) -> Dict[str, Any]:
    """
    Resolve all waivers whose expiry week has passed.
    Called from advance_week() and end_regular_season().

    - If bids exist: worst-record org wins, contract transfers (full, 0% retention)
    - If no bids: contract finished, player enters FA pool with tier-based demand
    """
    t = _t(conn)
    wc = t["waiver_claims"]

    expired = conn.execute(
        select(wc).where(and_(
            wc.c.status == "active",
            wc.c.expires_week <= current_week,
        ))
    ).mappings().all()

    summary = {"processed": 0, "claimed": 0, "cleared": 0, "details": []}

    for claim in expired:
        try:
            result = _resolve_waiver(conn, claim, league_year_id)
            summary["processed"] += 1
            if result["outcome"] == "claimed":
                summary["claimed"] += 1
            else:
                summary["cleared"] += 1
            summary["details"].append(result)
        except Exception as e:
            log.exception(
                "Failed to resolve waiver %d for player %d: %s",
                claim["id"], claim["player_id"], e,
            )

    if summary["processed"]:
        log.info("process_expired_waivers: week=%d %s", current_week, summary)
    return summary


def _resolve_waiver(
    conn, claim: dict, league_year_id: int,
) -> Dict[str, Any]:
    """Resolve a single expired waiver claim."""
    t = _t(conn)
    wc = t["waiver_claims"]
    bids = t["waiver_bids"]

    waiver_id = claim["id"]
    player_id = claim["player_id"]
    contract_id = claim["contract_id"]

    # Get all bids
    bid_rows = conn.execute(
        select(bids).where(bids.c.waiver_claim_id == waiver_id)
        .order_by(bids.c.created_at.asc())
    ).mappings().all()

    if bid_rows:
        return _resolve_waiver_claimed(conn, claim, bid_rows, league_year_id)
    else:
        return _resolve_waiver_cleared(conn, claim, league_year_id)


def _resolve_waiver_claimed(
    conn, claim: dict, bid_rows: list, league_year_id: int,
) -> Dict[str, Any]:
    """Award the waiver claim to the org with the worst record."""
    t = _t(conn)
    wc = t["waiver_claims"]

    waiver_id = claim["id"]
    player_id = claim["player_id"]
    contract_id = claim["contract_id"]
    releasing_org_id = claim["releasing_org_id"]
    last_level = claim["last_level"]

    claimant_org_ids = [b["org_id"] for b in bid_rows]

    # Determine priority: worst record wins
    standings = _get_standings_priority(
        conn, claimant_org_ids, league_year_id, last_level,
    )
    # standings is sorted worst-first; first entry wins
    # If an org has no games (e.g. expansion), they have 0 wins = worst record
    winning_org_id = standings[0]["org_id"]

    # Transfer contract: full transfer, 0% retention
    _transfer_contract(conn, contract_id, releasing_org_id, winning_org_id)

    # Log transaction
    tx_id = _log_tx(conn,
        transaction_type="waiver_claim",
        league_year_id=league_year_id,
        primary_org_id=winning_org_id,
        secondary_org_id=releasing_org_id,
        contract_id=contract_id,
        player_id=player_id,
        details={
            "waiver_claim_id": waiver_id,
            "total_claimants": len(claimant_org_ids),
            "claimant_org_ids": claimant_org_ids,
        },
    )

    # Update waiver claim record
    conn.execute(
        update(wc).where(wc.c.id == waiver_id).values(
            status="claimed",
            claiming_org_id=winning_org_id,
            resolved_at=datetime.utcnow(),
            claim_transaction_id=tx_id,
        )
    )

    log.info(
        "waiver_claimed: waiver=%d player=%d winner_org=%d (of %d claimants)",
        waiver_id, player_id, winning_org_id, len(claimant_org_ids),
    )
    return {
        "outcome": "claimed",
        "waiver_claim_id": waiver_id,
        "player_id": player_id,
        "claiming_org_id": winning_org_id,
        "transaction_id": tx_id,
    }


def _resolve_waiver_cleared(
    conn, claim: dict, league_year_id: int,
) -> Dict[str, Any]:
    """No one claimed — finish contract, create demand, enter FA pool."""
    t = _t(conn)
    wc = t["waiver_claims"]
    contracts = t["contracts"]

    waiver_id = claim["id"]
    player_id = claim["player_id"]
    contract_id = claim["contract_id"]
    last_level = claim["last_level"]
    service_years = claim["service_years"]

    # Finish the old contract (dead money stays on old org's books)
    conn.execute(
        update(contracts).where(contracts.c.id == contract_id)
        .values(isFinished=1)
    )

    # Update waiver claim record FIRST — ensures the player is never stuck
    # with an "active" waiver if the auction entry fails below
    conn.execute(
        update(wc).where(wc.c.id == waiver_id).values(
            status="cleared",
            resolved_at=datetime.utcnow(),
        )
    )

    # Generate demand and optionally enter auction
    if service_years >= FA_THRESHOLD:
        # Full FA — use existing auction system
        from services.fa_auction import enter_auction
        enter_auction(conn, player_id, league_year_id, current_week=claim["expires_week"])
    else:
        # Lower-tier FA — insert demand directly, no auction needed
        _insert_tier_demand(conn, player_id, league_year_id, last_level, service_years)

    fa_type = _derive_fa_type(last_level, service_years)
    log.info(
        "waiver_cleared: waiver=%d player=%d fa_type=%s contract=%d finished",
        waiver_id, player_id, fa_type, contract_id,
    )
    return {
        "outcome": "cleared",
        "waiver_claim_id": waiver_id,
        "player_id": player_id,
        "fa_type": fa_type,
    }


# ── Contract transfer (waiver claim) ─────────────────────────────────

def _transfer_contract(
    conn, contract_id: int, from_org_id: int, to_org_id: int,
):
    """
    Transfer a contract from one org to another (full, 0% retention).
    Mirrors the _move_player pattern from execute_trade in transactions.py.
    """
    t = _t(conn)
    contracts = t["contracts"]
    details = t["details"]
    shares = t["shares"]

    c_row = conn.execute(
        select(contracts.c.current_year).where(contracts.c.id == contract_id)
    ).first()
    if not c_row:
        raise ValueError(f"Contract {contract_id} not found")
    current_year = c_row._mapping["current_year"]

    # Get future-year detail IDs
    future_details = conn.execute(
        select(details.c.id).where(and_(
            details.c.contractID == contract_id,
            details.c.year >= current_year,
        ))
    ).all()

    for fd in future_details:
        detail_id = fd._mapping["id"]

        # Old org: isHolder=0, salary_share=0 (full transfer)
        conn.execute(
            update(shares).where(and_(
                shares.c.contractDetailsID == detail_id,
                shares.c.orgID == from_org_id,
            )).values(isHolder=0, salary_share=Decimal("0"))
        )

        # New org: create share with isHolder=1, salary_share=1.0
        conn.execute(shares.insert().values(
            contractDetailsID=detail_id,
            orgID=to_org_id,
            isHolder=1,
            salary_share=Decimal("1.00"),
        ))


# ── Demand generation for non-FA tiers ───────────────────────────────

def _insert_tier_demand(
    conn, player_id: int, league_year_id: int,
    last_level: int, service_years: int,
):
    """
    Insert a player_demands row for a non-MLB-FA player who cleared waivers.
    MiLB = $40K/1yr, pre-arb/arb MLB = $800K/1yr.
    """
    t = _t(conn)
    demands = t["demands"]

    if last_level < 9:
        min_aav = MINOR_SALARY
    else:
        min_aav = PRE_ARB_SALARY

    # Upsert: check for existing demand first
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
        war_snapshot=Decimal("0"),
        age_snapshot=0,
        service_years=service_years,
        min_years=1,
        max_years=1,
        min_aav=min_aav,
        min_total_value=min_aav,
        buyout_price=None,
        dollar_per_war=Decimal("0"),
    )

    if existing:
        conn.execute(
            demands.update().where(demands.c.id == existing._mapping["id"])
            .values(**values)
        )
    else:
        conn.execute(demands.insert().values(**values))

    log.info(
        "tier_demand: player=%d level=%d svc=%d aav=%s",
        player_id, last_level, service_years, min_aav,
    )


def _derive_fa_type(last_level: int, service_years: int) -> str:
    """Derive the FA tier category for a player."""
    if service_years >= FA_THRESHOLD:
        return "mlb_fa"
    elif last_level < 9:
        return "milb_fa"
    elif service_years < 3:
        return "pre_arb"
    else:
        return "arb"


# ── Standings priority for waiver claims ──────────────────────────────

def _get_standings_priority(
    conn, org_ids: List[int], league_year_id: int, team_level: int,
) -> List[Dict[str, Any]]:
    """
    Return claimant orgs sorted by worst record (lowest win_pct first).
    Ties broken by: fewest total wins, then org_id ascending (deterministic).
    Orgs with no games have win_pct=0 (worst possible, highest priority).
    """
    if not org_ids:
        return []

    # Get season from league_year_id
    season_row = conn.execute(sa_text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).first()
    if not season_row:
        # Fallback: treat everyone as equal, use org_id order
        return [{"org_id": oid, "wins": 0, "losses": 0, "win_pct": 0.0}
                for oid in org_ids]
    season = season_row[0]

    # Query wins/losses per org at the relevant team level
    # Build IN clause with numbered params for pymysql compatibility
    org_params = {f"org_{i}": oid for i, oid in enumerate(org_ids)}
    org_placeholders = ", ".join(f":org_{i}" for i in range(len(org_ids)))
    rows = conn.execute(sa_text(f"""
        SELECT
            t.orgID AS org_id,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = :season AND game_type = 'regular'
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = :season AND game_type = 'regular'
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level = :level AND t.orgID IN ({org_placeholders})
    """), {"season": season, "level": team_level, **org_params}).mappings().all()

    # Build standings map
    standings_map: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        oid = r["org_id"]
        wins = int(r["wins"])
        losses = int(r["losses"])
        total = wins + losses
        win_pct = wins / total if total > 0 else 0.0
        # If org already seen (shouldn't happen with team_level filter), take first
        if oid not in standings_map:
            standings_map[oid] = {
                "org_id": oid, "wins": wins, "losses": losses, "win_pct": win_pct,
            }

    # Include orgs with no games at all
    for oid in org_ids:
        if oid not in standings_map:
            standings_map[oid] = {
                "org_id": oid, "wins": 0, "losses": 0, "win_pct": 0.0,
            }

    # Sort: worst record first (lowest win_pct), then fewest wins, then org_id
    result = sorted(
        standings_map.values(),
        key=lambda x: (x["win_pct"], x["wins"], x["org_id"]),
    )
    return result


# ── Waiver wire display ──────────────────────────────────────────────

def get_waiver_wire(
    conn, league_year_id: int, org_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Return all active waiver entries with player info.
    If org_id is provided, include whether that org has a pending bid.
    """
    t = _t(conn)
    wc = t["waiver_claims"]
    players = t["players"]
    orgs = t["organizations"]
    bids = t["waiver_bids"]

    rows = conn.execute(sa_text("""
        SELECT wc.*, p.firstName, p.lastName, p.ptype, p.age, p.displayovr,
               o.org_abbrev AS releasing_org_abbrev
        FROM waiver_claims wc
        JOIN simbbPlayers p ON p.id = wc.player_id
        JOIN organizations o ON o.id = wc.releasing_org_id
        WHERE wc.league_year_id = :lyid AND wc.status = 'active'
        ORDER BY wc.expires_week ASC, wc.created_at ASC
    """), {"lyid": league_year_id}).mappings().all()

    # Count bids per waiver
    waiver_ids = [r["id"] for r in rows]
    bid_counts: Dict[int, int] = {}
    my_bids: set = set()
    if waiver_ids:
        bc_rows = conn.execute(
            select(bids.c.waiver_claim_id, func.count().label("cnt"))
            .where(bids.c.waiver_claim_id.in_(waiver_ids))
            .group_by(bids.c.waiver_claim_id)
        ).mappings().all()
        bid_counts = {r["waiver_claim_id"]: int(r["cnt"]) for r in bc_rows}

        if org_id:
            my_bid_rows = conn.execute(
                select(bids.c.waiver_claim_id)
                .where(and_(
                    bids.c.waiver_claim_id.in_(waiver_ids),
                    bids.c.org_id == org_id,
                ))
            ).all()
            my_bids = {r._mapping["waiver_claim_id"] for r in my_bid_rows}

    result = []
    for r in rows:
        wid = r["id"]
        result.append({
            "waiver_claim_id": wid,
            "player_id": r["player_id"],
            "player_name": f"{r['firstName']} {r['lastName']}",
            "ptype": r["ptype"],
            "age": r["age"],
            "displayovr": _fuzz_ovr(r["displayovr"], org_id, r["player_id"]),
            "contract_id": r["contract_id"],
            "releasing_org_id": r["releasing_org_id"],
            "releasing_org_abbrev": r["releasing_org_abbrev"],
            "placed_week": r["placed_week"],
            "expires_week": r["expires_week"],
            "last_level": r["last_level"],
            "service_years": r["service_years"],
            "fa_type": _derive_fa_type(r["last_level"], r["service_years"]),
            "bid_count": bid_counts.get(wid, 0),
            "my_bid": wid in my_bids,
        })
    return result


def get_waiver_detail(
    conn, waiver_claim_id: int, org_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Return a single waiver entry with full details."""
    t = _t(conn)
    bids = t["waiver_bids"]

    row = conn.execute(sa_text("""
        SELECT wc.*, p.firstName, p.lastName, p.ptype, p.age, p.displayovr,
               o.org_abbrev AS releasing_org_abbrev
        FROM waiver_claims wc
        JOIN simbbPlayers p ON p.id = wc.player_id
        JOIN organizations o ON o.id = wc.releasing_org_id
        WHERE wc.id = :wid
    """), {"wid": waiver_claim_id}).mappings().first()

    if not row:
        return None

    result = {
        "waiver_claim_id": row["id"],
        "player_id": row["player_id"],
        "player_name": f"{row['firstName']} {row['lastName']}",
        "ptype": row["ptype"],
        "age": row["age"],
        "displayovr": _fuzz_ovr(row["displayovr"], org_id, row["player_id"]),
        "contract_id": row["contract_id"],
        "releasing_org_id": row["releasing_org_id"],
        "releasing_org_abbrev": row["releasing_org_abbrev"],
        "placed_week": row["placed_week"],
        "expires_week": row["expires_week"],
        "last_level": row["last_level"],
        "service_years": row["service_years"],
        "fa_type": _derive_fa_type(row["last_level"], row["service_years"]),
        "status": row["status"],
        "claiming_org_id": row["claiming_org_id"],
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
    }

    # Check if this org has a bid
    if org_id:
        my_bid = conn.execute(
            select(bids.c.id).where(and_(
                bids.c.waiver_claim_id == waiver_claim_id,
                bids.c.org_id == org_id,
            ))
        ).first()
        result["my_bid"] = my_bid is not None

    return result


# ── Transaction logging helper ────────────────────────────────────────

def _log_tx(conn, *, transaction_type: str, league_year_id: int,
            primary_org_id: int, secondary_org_id: int = None,
            contract_id: int = None, player_id: int = None,
            details: dict = None, executed_by: str = None) -> int:
    """Log a transaction and return its ID."""
    import json
    t = _t(conn)
    result = conn.execute(t["tx_log"].insert().values(
        transaction_type=transaction_type,
        league_year_id=league_year_id,
        primary_org_id=primary_org_id,
        secondary_org_id=secondary_org_id,
        contract_id=contract_id,
        player_id=player_id,
        details=json.dumps(details) if details else None,
        executed_by=executed_by,
    ))
    return result.lastrowid
