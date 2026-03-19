# services/fa_auction.py
"""
Free agency auction system — 3-phase competitive bidding.

Phases (each lasts 1 game week):
  1. Open     — any org can submit an offer
  2. Listening — only existing bidders can increase their AAV
  3. Finalize — only top 3 bidders can increase AAV; winner signs at end

Phase transitions are triggered by advance_auction_phases(), called from
timestamp.advance_week().
"""

import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text as sa_text, update

log = logging.getLogger(__name__)

# ── Table reflection cache ───────────────────────────────────────────

_table_cache: Dict[int, Dict[str, Table]] = {}


def _t(conn) -> Dict[str, Table]:
    eid = id(conn.engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "auction":      Table("fa_auction", md, autoload_with=conn.engine),
            "offers":       Table("fa_auction_offers", md, autoload_with=conn.engine),
            "demands":      Table("player_demands", md, autoload_with=conn.engine),
            "contracts":    Table("contracts", md, autoload_with=conn.engine),
            "details":      Table("contractDetails", md, autoload_with=conn.engine),
            "shares":       Table("contractTeamShare", md, autoload_with=conn.engine),
            "players":      Table("simbbPlayers", md, autoload_with=conn.engine),
            "organizations": Table("organizations", md, autoload_with=conn.engine),
            "service_time": Table("player_service_time", md, autoload_with=conn.engine),
            "league_years": Table("league_years", md, autoload_with=conn.engine),
            "ledger":       Table("org_ledger_entries", md, autoload_with=conn.engine),
            "tx_log":       Table("transaction_log", md, autoload_with=conn.engine),
        }
    return _table_cache[eid]


# ── Enter auction ───────────────────────────────────────────────────

def enter_auction(
    conn,
    player_id: int,
    league_year_id: int,
    current_week: int,
) -> Dict[str, Any]:
    """
    Place a player into the FA auction pool (phase='open').
    Computes FA demands and stores them alongside the auction row.
    """
    t = _t(conn)
    auc = t["auction"]
    players = t["players"]
    st = t["service_time"]

    # Check not already in an active auction
    existing = conn.execute(
        select(auc.c.id).where(and_(
            auc.c.player_id == player_id,
            auc.c.league_year_id == league_year_id,
            auc.c.phase.in_(["open", "listening", "finalize"]),
        ))
    ).first()
    if existing:
        return {"auction_id": existing._mapping["id"], "already_active": True}

    # Compute demands
    from services.player_demands import compute_fa_demand
    demand = compute_fa_demand(conn, player_id, league_year_id)

    # Player info
    p_row = conn.execute(
        select(players.c.age).where(players.c.id == player_id)
    ).first()
    age = int(p_row._mapping["age"]) if p_row else 25

    svc_row = conn.execute(
        select(st.c.mlb_service_years).where(st.c.player_id == player_id)
    ).first()
    service_years = int(svc_row._mapping["mlb_service_years"]) if svc_row else 0

    result = conn.execute(auc.insert().values(
        player_id=player_id,
        league_year_id=league_year_id,
        phase="open",
        phase_started_week=current_week,
        entered_week=current_week,
        min_total_value=Decimal(demand["min_total_value"]),
        min_aav=Decimal(demand["min_aav"]),
        min_years=demand["min_years"],
        max_years=demand["max_years"],
        war_at_entry=Decimal(str(demand["war"])),
        age_at_entry=age,
        service_years=service_years,
    ))
    auction_id = result.lastrowid

    log.info(
        "enter_auction: player=%d auction=%d min_aav=%s phase=open",
        player_id, auction_id, demand["min_aav"],
    )
    return {
        "auction_id": auction_id,
        "player_id": player_id,
        "phase": "open",
        "min_aav": demand["min_aav"],
        "min_total_value": demand["min_total_value"],
        "min_years": demand["min_years"],
        "max_years": demand["max_years"],
        "war": demand["war"],
    }


# ── Submit / update offer ───────────────────────────────────────────

def submit_offer(
    conn,
    auction_id: int,
    org_id: int,
    years: int,
    salaries: List[Decimal],
    bonus: Decimal,
    level_id: int,
    league_year_id: int,
    game_week_id: int,
    current_week: int,
    executed_by: str = None,
) -> Dict[str, Any]:
    """
    Submit or update an offer on an auction.

    Validates phase rules, minimum demands, and cash balance.
    """
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]
    tx_log = t["tx_log"]

    # Load auction
    auction = conn.execute(
        select(auc).where(auc.c.id == auction_id)
    ).first()
    if not auction:
        raise ValueError(f"Auction {auction_id} not found")
    a = auction._mapping
    phase = a["phase"]

    if phase not in ("open", "listening", "finalize"):
        raise ValueError(f"Auction is in phase '{phase}' — not accepting offers")

    # Validate years
    if not 1 <= years <= 5:
        raise ValueError("Contract length must be 1-5 years")
    if len(salaries) != years:
        raise ValueError(f"salaries length ({len(salaries)}) must match years ({years})")

    total_value = sum(salaries) + bonus
    aav = total_value / years if years else total_value

    # Check minimum demand
    if total_value < a["min_total_value"]:
        raise ValueError(
            f"Total value ({total_value}) below player minimum ({a['min_total_value']})"
        )

    # Validate cash balance for bonus
    from services.transactions import _get_signing_budget
    budget = _get_signing_budget(conn, org_id, league_year_id)
    if bonus > budget:
        raise ValueError(f"Bonus ({bonus}) exceeds available budget ({budget})")

    # Check existing offer for this org
    existing_offer = conn.execute(
        select(offers).where(and_(
            offers.c.auction_id == auction_id,
            offers.c.org_id == org_id,
        ))
    ).first()

    is_update = existing_offer is not None

    if phase == "listening":
        if not is_update:
            raise ValueError("Listening phase: only existing bidders can update offers")
        old_aav = existing_offer._mapping["aav"]
        if aav < old_aav:
            raise ValueError(
                f"Listening phase: new AAV ({aav}) must be >= old AAV ({old_aav})"
            )

    if phase == "finalize":
        if not is_update:
            raise ValueError("Finalize phase: only existing bidders can update offers")
        if existing_offer._mapping["status"] != "active":
            raise ValueError("Your offer was eliminated — cannot update")
        old_aav = existing_offer._mapping["aav"]
        if aav < old_aav:
            raise ValueError(
                f"Finalize phase: new AAV ({aav}) must be >= old AAV ({old_aav})"
            )

    if is_update:
        old_values = {
            "years": int(existing_offer._mapping["years"]),
            "salaries": json.loads(existing_offer._mapping["salaries_json"])
                        if isinstance(existing_offer._mapping["salaries_json"], str)
                        else existing_offer._mapping["salaries_json"],
            "bonus": float(existing_offer._mapping["bonus"]),
            "total_value": float(existing_offer._mapping["total_value"]),
            "aav": float(existing_offer._mapping["aav"]),
        }
        conn.execute(
            update(offers)
            .where(offers.c.id == existing_offer._mapping["id"])
            .values(
                years=years,
                bonus=bonus,
                total_value=total_value,
                aav=aav,
                salaries_json=json.dumps([float(s) for s in salaries]),
                level_id=level_id,
                last_updated_week=current_week,
            )
        )
        offer_id = int(existing_offer._mapping["id"])

        # Log update
        conn.execute(tx_log.insert().values(
            transaction_type="fa_offer_update",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            player_id=int(a["player_id"]),
            details=json.dumps({
                "auction_id": auction_id,
                "offer_id": offer_id,
                "old": old_values,
                "new": {
                    "years": years,
                    "salaries": [float(s) for s in salaries],
                    "bonus": float(bonus),
                    "total_value": float(total_value),
                    "aav": float(aav),
                },
            }),
            executed_by=executed_by,
        ))
    else:
        result = conn.execute(offers.insert().values(
            auction_id=auction_id,
            org_id=org_id,
            years=years,
            bonus=bonus,
            total_value=total_value,
            aav=aav,
            salaries_json=json.dumps([float(s) for s in salaries]),
            level_id=level_id,
            submitted_week=current_week,
            last_updated_week=current_week,
            status="active",
        ))
        offer_id = result.lastrowid

        # Log new offer
        conn.execute(tx_log.insert().values(
            transaction_type="fa_offer",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            player_id=int(a["player_id"]),
            details=json.dumps({
                "auction_id": auction_id,
                "offer_id": offer_id,
                "was_new_offer": True,
                "years": years,
                "salaries": [float(s) for s in salaries],
                "bonus": float(bonus),
                "total_value": float(total_value),
                "aav": float(aav),
            }),
            executed_by=executed_by,
        ))

    log.info(
        "offer: auction=%d org=%d aav=%s total=%s %s",
        auction_id, org_id, aav, total_value,
        "updated" if is_update else "new",
    )

    return {
        "offer_id": offer_id,
        "auction_id": auction_id,
        "org_id": org_id,
        "years": years,
        "bonus": float(bonus),
        "total_value": float(total_value),
        "aav": float(aav),
        "is_update": is_update,
        "phase": phase,
    }


# ── Withdraw offer ──────────────────────────────────────────────────

def withdraw_offer(conn, auction_id: int, org_id: int) -> Dict[str, Any]:
    """Withdraw an offer. Only allowed in 'open' phase."""
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]

    auction = conn.execute(
        select(auc.c.phase).where(auc.c.id == auction_id)
    ).first()
    if not auction:
        raise ValueError(f"Auction {auction_id} not found")
    if auction._mapping["phase"] != "open":
        raise ValueError("Can only withdraw offers during 'open' phase")

    result = conn.execute(
        update(offers)
        .where(and_(
            offers.c.auction_id == auction_id,
            offers.c.org_id == org_id,
        ))
        .values(status="withdrawn")
    )
    if result.rowcount == 0:
        raise ValueError("No active offer found to withdraw")

    return {"withdrawn": True, "auction_id": auction_id, "org_id": org_id}


# ── Phase transitions ───────────────────────────────────────────────

def advance_auction_phases(
    conn, current_week: int, league_year_id: int,
) -> Dict[str, Any]:
    """
    Process phase transitions for all active auctions.
    Called from timestamp.advance_week().

    Returns summary of transitions made.
    """
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]

    summary = {"open_to_listening": 0, "listening_to_finalize": 0,
               "finalize_to_completed": 0, "still_open": 0}

    active_auctions = conn.execute(
        select(auc).where(auc.c.phase.in_(["open", "listening", "finalize"]))
    ).all()

    for row in active_auctions:
        a = row._mapping
        auction_id = int(a["id"])
        phase = a["phase"]
        started = int(a["phase_started_week"])

        # Phase must have lasted at least 1 week
        if current_week <= started:
            if phase == "open":
                summary["still_open"] += 1
            continue

        if phase == "open":
            # Need at least 1 offer to transition
            offer_count = conn.execute(
                select(func.count()).where(and_(
                    offers.c.auction_id == auction_id,
                    offers.c.status == "active",
                ))
            ).scalar_one()

            if offer_count == 0:
                summary["still_open"] += 1
                continue

            conn.execute(
                update(auc)
                .where(auc.c.id == auction_id)
                .values(phase="listening", phase_started_week=current_week)
            )
            summary["open_to_listening"] += 1
            log.info("auction %d: open -> listening (week %d)", auction_id, current_week)

        elif phase == "listening":
            # Eliminate non-top-3 offers
            active_offers = conn.execute(
                select(offers.c.id, offers.c.total_value)
                .where(and_(
                    offers.c.auction_id == auction_id,
                    offers.c.status == "active",
                ))
                .order_by(offers.c.total_value.desc())
            ).all()

            if len(active_offers) > 3:
                keep_ids = {r._mapping["id"] for r in active_offers[:3]}
                for r in active_offers[3:]:
                    conn.execute(
                        update(offers)
                        .where(offers.c.id == r._mapping["id"])
                        .values(status="outbid")
                    )

            conn.execute(
                update(auc)
                .where(auc.c.id == auction_id)
                .values(phase="finalize", phase_started_week=current_week)
            )
            summary["listening_to_finalize"] += 1
            log.info("auction %d: listening -> finalize (week %d)", auction_id, current_week)

        elif phase == "finalize":
            # Winner = highest total_value among active offers
            winner = conn.execute(
                select(offers)
                .where(and_(
                    offers.c.auction_id == auction_id,
                    offers.c.status == "active",
                ))
                .order_by(offers.c.total_value.desc())
                .limit(1)
            ).first()

            if not winner:
                log.warning("auction %d: finalize with no active offers", auction_id)
                conn.execute(
                    update(auc)
                    .where(auc.c.id == auction_id)
                    .values(phase="withdrawn")
                )
                continue

            _execute_auction_signing(
                conn, auction_id, int(winner._mapping["id"]),
                league_year_id, current_week,
            )
            summary["finalize_to_completed"] += 1
            log.info("auction %d: finalize -> completed (week %d)", auction_id, current_week)

    return summary


# ── Execute auction signing ─────────────────────────────────────────

def _execute_auction_signing(
    conn,
    auction_id: int,
    winning_offer_id: int,
    league_year_id: int,
    current_week: int,
) -> Dict[str, Any]:
    """
    Execute the winning auction bid as a contract signing.
    Reuses sign_free_agent() from services.transactions.
    """
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]
    tx_log = t["tx_log"]

    # Load winning offer
    offer = conn.execute(
        select(offers).where(offers.c.id == winning_offer_id)
    ).first()
    if not offer:
        raise ValueError(f"Offer {winning_offer_id} not found")
    o = offer._mapping

    # Load auction
    auction = conn.execute(
        select(auc).where(auc.c.id == auction_id)
    ).first()
    a = auction._mapping

    # Parse salaries
    salaries_raw = o["salaries_json"]
    if isinstance(salaries_raw, str):
        salaries_list = json.loads(salaries_raw)
    else:
        salaries_list = salaries_raw
    salaries = [Decimal(str(s)) for s in salaries_list]

    # Get game_week_id for the current week
    ly_row = conn.execute(sa_text(
        "SELECT id FROM game_weeks WHERE league_year_id = :ly AND week_number = :w LIMIT 1"
    ), {"ly": league_year_id, "w": current_week}).first()
    game_week_id = ly_row[0] if ly_row else None

    # Sign via existing mechanism
    from services.transactions import sign_free_agent
    signing_result = sign_free_agent(
        conn,
        player_id=int(a["player_id"]),
        org_id=int(o["org_id"]),
        years=int(o["years"]),
        salaries=salaries,
        bonus=Decimal(str(o["bonus"])),
        level_id=int(o["level_id"]),
        league_year_id=league_year_id,
        game_week_id=game_week_id,
        executed_by="fa_auction",
    )

    # Mark auction completed
    conn.execute(
        update(auc)
        .where(auc.c.id == auction_id)
        .values(
            phase="completed",
            winning_offer_id=winning_offer_id,
            phase_started_week=current_week,
        )
    )

    # Mark winning offer
    conn.execute(
        update(offers)
        .where(offers.c.id == winning_offer_id)
        .values(status="won")
    )

    # Mark all other active offers as lost
    conn.execute(
        update(offers)
        .where(and_(
            offers.c.auction_id == auction_id,
            offers.c.id != winning_offer_id,
            offers.c.status == "active",
        ))
        .values(status="lost")
    )

    # Log the auction signing
    conn.execute(tx_log.insert().values(
        transaction_type="fa_auction_sign",
        league_year_id=league_year_id,
        primary_org_id=int(o["org_id"]),
        contract_id=signing_result["contract_id"],
        player_id=int(a["player_id"]),
        details=json.dumps({
            "auction_id": auction_id,
            "offer_id": winning_offer_id,
            "signing_transaction_id": signing_result["transaction_id"],
            "contract_id": signing_result["contract_id"],
        }),
        executed_by="fa_auction",
    ))

    log.info(
        "auction_signing: auction=%d player=%d org=%d contract=%d",
        auction_id, int(a["player_id"]), int(o["org_id"]),
        signing_result["contract_id"],
    )
    return signing_result


# ── Auction board (fuzzied view) ────────────────────────────────────

def get_auction_board(
    conn,
    league_year_id: int,
    viewer_org_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Return all active auctions with fuzzied competitor info.
    Own offer: exact. Competitors: teams listed alphabetically, amounts NOT shown.
    """
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]
    players = t["players"]
    orgs = t["organizations"]

    auctions = conn.execute(
        select(
            auc,
            players.c.firstName,
            players.c.lastName,
            players.c.ptype,
        )
        .select_from(auc.join(players, players.c.id == auc.c.player_id))
        .where(and_(
            auc.c.league_year_id == league_year_id,
            auc.c.phase.in_(["open", "listening", "finalize"]),
        ))
        .order_by(auc.c.war_at_entry.desc())
    ).all()

    result = []
    for row in auctions:
        a = row._mapping
        auction_id = int(a["id"])

        # Get all offers for this auction
        all_offers = conn.execute(
            select(
                offers.c.id,
                offers.c.org_id,
                offers.c.total_value,
                offers.c.aav,
                offers.c.years,
                offers.c.bonus,
                offers.c.salaries_json,
                offers.c.status,
                offers.c.level_id,
            )
            .where(and_(
                offers.c.auction_id == auction_id,
                offers.c.status.in_(["active", "outbid"]),
            ))
        ).all()

        # Count active offers
        active_count = sum(1 for o in all_offers if o._mapping["status"] == "active")

        # Get competing org names (alphabetically)
        competing_org_ids = [int(o._mapping["org_id"]) for o in all_offers
                           if o._mapping["status"] == "active"]
        org_names = []
        if competing_org_ids:
            org_rows = conn.execute(
                select(orgs.c.id, orgs.c.org_abbrev)
                .where(orgs.c.id.in_(competing_org_ids))
                .order_by(orgs.c.org_abbrev)
            ).all()
            org_names = [r._mapping["org_abbrev"] for r in org_rows]

        # Viewer's own offer (exact details)
        my_offer = None
        if viewer_org_id:
            for o in all_offers:
                if int(o._mapping["org_id"]) == viewer_org_id:
                    om = o._mapping
                    salaries = om["salaries_json"]
                    if isinstance(salaries, str):
                        salaries = json.loads(salaries)
                    my_offer = {
                        "offer_id": int(om["id"]),
                        "years": int(om["years"]),
                        "bonus": float(om["bonus"]),
                        "total_value": float(om["total_value"]),
                        "aav": float(om["aav"]),
                        "salaries": salaries,
                        "level_id": int(om["level_id"]),
                        "status": om["status"],
                    }
                    break

        entry = {
            "auction_id": auction_id,
            "player_id": int(a["player_id"]),
            "player_name": f"{a['firstName']} {a['lastName']}".strip(),
            "player_type": a["ptype"],
            "war": float(a["war_at_entry"]),
            "age": int(a["age_at_entry"]),
            "phase": a["phase"],
            "min_aav": float(a["min_aav"]),
            "min_total_value": float(a["min_total_value"]),
            "min_years": int(a["min_years"]),
            "max_years": int(a["max_years"]),
            "offer_count": active_count,
            "competing_teams": org_names,  # alphabetical, no amounts
            "my_offer": my_offer,
            "entered_week": int(a["entered_week"]),
        }
        result.append(entry)

    return result


def get_auction_detail(
    conn, auction_id: int, viewer_org_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Single auction detail with same view rules as the board."""
    t = _t(conn)
    auc = t["auction"]
    players = t["players"]

    auction = conn.execute(
        select(auc, players.c.firstName, players.c.lastName, players.c.ptype)
        .select_from(auc.join(players, players.c.id == auc.c.player_id))
        .where(auc.c.id == auction_id)
    ).first()
    if not auction:
        return None

    a = auction._mapping
    board = get_auction_board(conn, int(a["league_year_id"]), viewer_org_id)
    for entry in board:
        if entry["auction_id"] == auction_id:
            return entry

    # Auction exists but not in active phases — return basic info
    return {
        "auction_id": auction_id,
        "player_id": int(a["player_id"]),
        "player_name": f"{a['firstName']} {a['lastName']}".strip(),
        "phase": a["phase"],
        "war": float(a["war_at_entry"]),
        "age": int(a["age_at_entry"]),
    }


# ── Rollback helpers ────────────────────────────────────────────────

def rollback_auction_offer(conn, details: dict) -> None:
    """Rollback an fa_offer transaction (delete the offer row)."""
    t = _t(conn)
    offers = t["offers"]
    offer_id = details.get("offer_id")
    if offer_id:
        conn.execute(offers.delete().where(offers.c.id == offer_id))


def rollback_auction_offer_update(conn, details: dict) -> None:
    """Rollback an fa_offer_update — restore old values."""
    t = _t(conn)
    offers = t["offers"]
    offer_id = details.get("offer_id")
    old = details.get("old", {})
    if offer_id and old:
        conn.execute(
            update(offers)
            .where(offers.c.id == offer_id)
            .values(
                years=old["years"],
                bonus=Decimal(str(old["bonus"])),
                total_value=Decimal(str(old["total_value"])),
                aav=Decimal(str(old["aav"])),
                salaries_json=json.dumps(old["salaries"]),
            )
        )


def rollback_auction_signing(conn, details: dict) -> None:
    """
    Rollback an fa_auction_sign:
    1. Reset auction to 'finalize'
    2. Restore all offers to 'active'
    3. The underlying signing rollback is handled separately by the caller
    """
    t = _t(conn)
    auc = t["auction"]
    offers = t["offers"]
    auction_id = details.get("auction_id")

    if auction_id:
        conn.execute(
            update(auc)
            .where(auc.c.id == auction_id)
            .values(phase="finalize", winning_offer_id=None)
        )
        conn.execute(
            update(offers)
            .where(and_(
                offers.c.auction_id == auction_id,
                offers.c.status.in_(["won", "lost"]),
            ))
            .values(status="active")
        )
