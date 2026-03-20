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
            players.c.firstname,
            players.c.lastname,
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
            "player_name": f"{a['firstname']} {a['lastname']}".strip(),
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

    # Enrich with fuzzed player attributes and scouting status
    if result and viewer_org_id:
        try:
            player_ids = [e["player_id"] for e in result]
            # Load player attributes
            attr_rows = conn.execute(
                select(players).where(players.c.id.in_(player_ids))
            ).all()
            attr_map = {}
            for r in attr_rows:
                m = dict(r._mapping)
                pid = m["id"]
                ratings = {}
                for key, val in m.items():
                    if key.endswith("_base") or key.endswith("_pot"):
                        ratings[key] = val
                attr_map[pid] = ratings

            # Apply fog-of-war fuzz
            rating_dicts = [{"id": pid, **attrs} for pid, attrs in attr_map.items()]
            try:
                from scouting import _apply_pool_fuzz
                _apply_pool_fuzz(rating_dicts, viewer_org_id, "pro")
            except Exception:
                pass
            fuzzed_map = {d["id"]: {k: v for k, v in d.items() if k != "id"} for d in rating_dicts}

            # Load scouting actions
            scouting_map = {}
            try:
                from services.attribute_visibility import _load_scouting_actions_batch
                actions = _load_scouting_actions_batch(conn, viewer_org_id, player_ids)
                for pid, acts in actions.items():
                    act_types = set(acts) if isinstance(acts, (list, set)) else set()
                    scouting_map[pid] = {
                        "attrs_precise": "pro_attrs_precise" in act_types,
                        "pots_precise": "pro_potential_precise" in act_types,
                        "available_actions": _available_pro_actions(act_types),
                    }
            except Exception:
                pass

            # Attach to entries
            for entry in result:
                pid = entry["player_id"]
                entry["ratings"] = fuzzed_map.get(pid, {})
                entry["display_format"] = "letter_grade"
                entry["scouting"] = scouting_map.get(pid, {
                    "attrs_precise": False,
                    "pots_precise": False,
                    "available_actions": ["pro_attrs_precise", "pro_potential_precise"],
                })
        except Exception as e:
            log.warning("Auction board rating enrichment failed: %s", e)

    return result


def get_auction_detail(
    conn, auction_id: int, viewer_org_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Single auction detail with same view rules as the board."""
    t = _t(conn)
    auc = t["auction"]
    players = t["players"]

    auction = conn.execute(
        select(auc, players.c.firstname, players.c.lastname, players.c.ptype)
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
        "player_name": f"{a['firstname']} {a['lastname']}".strip(),
        "phase": a["phase"],
        "war": float(a["war_at_entry"]),
        "age": int(a["age_at_entry"]),
    }


# ── Free agent pool (paginated, fuzzed) ─────────────────────────────

def get_free_agent_pool(
    conn,
    viewing_org_id: int,
    league_year_id: int,
    page: int = 1,
    per_page: int = 50,
    filters: Optional[Dict[str, Any]] = None,
    sort: str = "lastname",
    sort_dir: str = "asc",
) -> Dict[str, Any]:
    """
    Paginated list of unsigned non-amateur players with fog-of-war
    fuzzed attributes, auction status, demand summaries, and scouting info.

    Excludes INTAM (org 339) and HS (org 340) players.
    """
    t = _t(conn)
    contracts = t["contracts"]
    details_tbl = Table("contractDetails", MetaData(), autoload_with=conn.engine)
    shares = Table("contractTeamShare", MetaData(), autoload_with=conn.engine)
    players = t["players"]
    auc = t["auction"]
    offers = t["offers"]
    demands_tbl = t["demands"]
    orgs = t["organizations"]

    filters = filters or {}

    # Use raw SQL for the free agent query — much faster than NOT IN subquery.
    # Finds players who have contract history but no active holder,
    # excludes amateur levels (< 3), and does pagination in one shot.
    filters = filters or {}

    # Build WHERE fragments for filters
    filter_clauses = []
    params: Dict[str, Any] = {"ly": league_year_id}

    if filters.get("ptype"):
        filter_clauses.append("AND p.ptype = :ptype")
        params["ptype"] = filters["ptype"]
    if filters.get("area"):
        filter_clauses.append("AND p.area = :area")
        params["area"] = filters["area"]
    if filters.get("min_age"):
        filter_clauses.append("AND p.age >= :min_age")
        params["min_age"] = filters["min_age"]
    if filters.get("max_age"):
        filter_clauses.append("AND p.age <= :max_age")
        params["max_age"] = filters["max_age"]
    if filters.get("search") and len(filters["search"]) >= 2:
        filter_clauses.append("AND (p.firstname LIKE :search OR p.lastname LIKE :search)")
        params["search"] = f"%{filters['search']}%"

    filter_sql = "\n        ".join(filter_clauses)

    # Sort
    allowed_sorts = {
        "lastname", "firstname", "age", "ptype", "area", "displayovr",
    }
    if sort not in allowed_sorts and not sort.endswith("_base") and not sort.endswith("_pot"):
        sort = "lastname"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"
    order_sql = f"p.{sort} {sort_dir}" if sort in allowed_sorts else f"p.lastname ASC"
    # For _base/_pot sorts, validate column exists to prevent injection
    if sort.endswith("_base") or sort.endswith("_pot"):
        # Validate against reflected table
        if hasattr(players.c, sort):
            order_sql = f"p.{sort} {sort_dir}"
        else:
            order_sql = "p.lastname ASC"

    # Main query: EXISTS/NOT EXISTS to find players with contracts but not currently held
    count_sql = sa_text(f"""
        SELECT COUNT(DISTINCT p.id)
        FROM simbbPlayers p
        INNER JOIN (
            SELECT playerID, MAX(id) AS max_cid FROM contracts GROUP BY playerID
        ) latest ON latest.playerID = p.id
        INNER JOIN contracts c_last ON c_last.id = latest.max_cid
        WHERE EXISTS (SELECT 1 FROM contracts c_any WHERE c_any.playerID = p.id)
          AND NOT EXISTS (
            SELECT 1 FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
            WHERE c.playerID = p.id AND c.isFinished = 0 AND cts.isHolder = 1
          )
          AND c_last.current_level >= 3
          {filter_sql}
    """)

    total = conn.execute(count_sql, params).scalar() or 0

    offset_val = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset_val

    data_sql = sa_text(f"""
        SELECT p.*, c_last.current_level AS last_level, o.org_abbrev AS last_org_abbrev
        FROM simbbPlayers p
        INNER JOIN (
            SELECT playerID, MAX(id) AS max_cid FROM contracts GROUP BY playerID
        ) latest ON latest.playerID = p.id
        INNER JOIN contracts c_last ON c_last.id = latest.max_cid
        INNER JOIN contractDetails cd_last ON cd_last.contractID = c_last.id AND cd_last.year = 1
        INNER JOIN contractTeamShare cts_last ON cts_last.contractDetailsID = cd_last.id
        INNER JOIN organizations o ON o.id = cts_last.orgID
        WHERE EXISTS (SELECT 1 FROM contracts c_any WHERE c_any.playerID = p.id)
          AND NOT EXISTS (
            SELECT 1 FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
            WHERE c.playerID = p.id AND c.isFinished = 0 AND cts.isHolder = 1
          )
          AND c_last.current_level >= 3
          {filter_sql}
        ORDER BY {order_sql}
        LIMIT :limit OFFSET :offset
    """)

    rows = conn.execute(data_sql, params).mappings().all()

    player_ids = [int(r["id"]) for r in rows]
    if not player_ids:
        pages = 0 if total == 0 else (total + per_page - 1) // per_page
        return {"total": total, "page": page, "per_page": per_page, "pages": pages, "players": []}

    # Build player dicts, keeping only relevant columns
    bio_keys = {
        "id", "firstname", "lastname", "age", "ptype",
        "area", "height", "weight", "bat_hand", "pitch_hand",
        "arm_angle", "durability", "injury_risk", "displayovr",
        "last_level", "last_org_abbrev",
    }
    filtered_list = []
    for r in rows:
        m = dict(r)
        p = {}
        for key, val in m.items():
            if key in bio_keys or key.endswith("_base") or key.endswith("_pot"):
                p[key] = val
            elif key.startswith("pitch") and (key.endswith("_name") or key.endswith("_ovr")):
                p[key] = val
        p["last_level"] = int(m["last_level"]) if m.get("last_level") else None
        p["last_org_abbrev"] = m.get("last_org_abbrev")
        filtered_list.append(p)

    # Apply fog-of-war fuzz
    try:
        from scouting import _apply_pool_fuzz
        _apply_pool_fuzz(filtered_list, viewing_org_id, "pro")
    except Exception as e:
        log.warning("Pool fuzz failed, serving unfuzzed: %s", e)

    # Attach auction data
    auction_rows = conn.execute(
        select(
            auc.c.id.label("auction_id"),
            auc.c.player_id,
            auc.c.phase,
            auc.c.min_aav,
            auc.c.min_total_value,
        )
        .where(and_(
            auc.c.player_id.in_(player_ids),
            auc.c.league_year_id == league_year_id,
            auc.c.phase.in_(["open", "listening", "finalize"]),
        ))
    ).mappings().all()
    auction_map = {int(r["player_id"]): dict(r) for r in auction_rows}

    # Offer counts per auction
    auction_ids = [r["auction_id"] for r in auction_rows]
    offer_counts = {}
    viewer_offers = {}
    if auction_ids:
        oc_rows = conn.execute(
            select(
                offers.c.auction_id,
                func.count().label("cnt"),
            )
            .where(and_(
                offers.c.auction_id.in_(auction_ids),
                offers.c.status == "active",
            ))
            .group_by(offers.c.auction_id)
        ).mappings().all()
        offer_counts = {int(r["auction_id"]): int(r["cnt"]) for r in oc_rows}

        if viewing_org_id:
            vo_rows = conn.execute(
                select(offers)
                .where(and_(
                    offers.c.auction_id.in_(auction_ids),
                    offers.c.org_id == viewing_org_id,
                ))
            ).mappings().all()
            for r in vo_rows:
                viewer_offers[int(r["auction_id"])] = {
                    "offer_id": int(r["id"]),
                    "years": int(r["years"]),
                    "bonus": float(r["bonus"]),
                    "total_value": float(r["total_value"]),
                    "aav": float(r["aav"]),
                    "status": r["status"],
                }

    # Attach demand summaries
    demand_rows = conn.execute(
        select(demands_tbl)
        .where(and_(
            demands_tbl.c.player_id.in_(player_ids),
            demands_tbl.c.league_year_id == league_year_id,
            demands_tbl.c.demand_type == "fa",
        ))
    ).mappings().all()
    demand_map = {int(r["player_id"]): r for r in demand_rows}

    # Batch-load service time for fa_type derivation
    st_tbl = Table("player_service_time", MetaData(), autoload_with=conn.engine)
    st_rows = conn.execute(
        select(st_tbl.c.player_id, st_tbl.c.mlb_service_years)
        .where(st_tbl.c.player_id.in_(player_ids))
    ).mappings().all()
    service_time_map = {int(r["player_id"]): int(r["mlb_service_years"]) for r in st_rows}

    # Attach scouting visibility
    scouting_map = {}
    if viewing_org_id:
        try:
            from services.attribute_visibility import _load_scouting_actions_batch
            actions = _load_scouting_actions_batch(conn, viewing_org_id, player_ids)
            for pid, acts in actions.items():
                act_types = set(acts) if isinstance(acts, (list, set)) else set()
                scouting_map[pid] = {
                    "unlocked": sorted(act_types),
                    "attrs_precise": "pro_attrs_precise" in act_types,
                    "pots_precise": "pro_potential_precise" in act_types,
                    "available_actions": _available_pro_actions(act_types),
                }
        except Exception as e:
            log.warning("Scouting visibility load failed: %s", e)

    # Assemble response
    result_players = []
    for p in filtered_list:
        pid = p["id"]
        svc = service_time_map.get(pid, 0)
        last_lvl = p.get("last_level") or 9

        # Derive fa_type
        from services.waivers import _derive_fa_type
        p["fa_type"] = _derive_fa_type(last_lvl, svc)

        auc_data = auction_map.get(pid)
        auction_info = None
        if auc_data:
            aid = int(auc_data["auction_id"])
            auction_info = {
                "auction_id": aid,
                "phase": auc_data["phase"],
                "min_aav": float(auc_data["min_aav"]),
                "offer_count": offer_counts.get(aid, 0),
                "my_offer": viewer_offers.get(aid),
            }

        demand_row = demand_map.get(pid)
        demand_info = None
        if demand_row:
            demand_info = {
                "min_aav": str(demand_row["min_aav"]) if demand_row["min_aav"] else None,
                "min_years": int(demand_row["min_years"]) if demand_row["min_years"] else None,
                "max_years": int(demand_row["max_years"]) if demand_row["max_years"] else None,
                "war": float(demand_row["war_snapshot"]),
            }
        elif p["fa_type"] != "mlb_fa":
            # Backfill demand for non-MLB-FA players missing demand records
            try:
                from services.waivers import _insert_tier_demand
                _insert_tier_demand(conn, pid, league_year_id, last_lvl, svc)
                min_aav = "40000" if last_lvl < 9 else "800000"
                demand_info = {
                    "min_aav": min_aav,
                    "min_years": 1,
                    "max_years": 1,
                    "war": 0.0,
                }
            except Exception as e:
                log.warning("Demand backfill failed for player %d: %s", pid, e)

        p["auction"] = auction_info
        p["demand"] = demand_info
        p["scouting"] = scouting_map.get(pid, {
            "unlocked": [],
            "attrs_precise": False,
            "pots_precise": False,
            "available_actions": ["pro_attrs_precise", "pro_potential_precise"],
        })
        result_players.append(p)

    # Apply has_auction filter if requested (post-query since it depends on auction join)
    if filters.get("has_auction"):
        result_players = [p for p in result_players if p["auction"] is not None]

    pages = (total + per_page - 1) // per_page if total else 0
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "players": result_players,
    }


def _available_pro_actions(unlocked: set) -> List[str]:
    """Return scouting actions available for a pro-level free agent."""
    available = []
    if "pro_attrs_precise" not in unlocked:
        available.append("pro_attrs_precise")
    if "pro_potential_precise" not in unlocked:
        available.append("pro_potential_precise")
    return available


# ── Player detail (full profile) ────────────────────────────────────

def get_free_agent_detail(
    conn,
    player_id: int,
    viewing_org_id: int,
    league_year_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Full profile for a free agent — combines scouted attributes,
    contract history, demand data, auction status, and stats summary.
    """
    t = _t(conn)
    players = t["players"]
    contracts = t["contracts"]
    details_tbl = Table("contractDetails", MetaData(), autoload_with=conn.engine)
    shares = Table("contractTeamShare", MetaData(), autoload_with=conn.engine)
    orgs = t["organizations"]
    demands_tbl = t["demands"]

    # Load player
    player = conn.execute(
        select(players).where(players.c.id == player_id)
    ).first()
    if not player:
        return None

    pm = dict(player._mapping)

    # Bio
    bio = {
        k: pm.get(k) for k in (
            "id", "firstname", "lastname", "age", "ptype", "area",
            "height", "weight", "bat_hand", "pitch_hand", "arm_angle",
            "durability", "injury_risk", "displayovr",
        )
    }

    # Attributes (fuzzed or precise based on scouting)
    attributes = {}
    potentials = {}
    for key, val in pm.items():
        if key.endswith("_base"):
            attributes[key] = val
        elif key.endswith("_pot"):
            potentials[key] = val
        elif key.startswith("pitch") and (key.endswith("_name") or key.endswith("_ovr")):
            attributes[key] = val

    # Scouting visibility
    scouting_info = {"unlocked": [], "attrs_precise": False, "pots_precise": False,
                     "available_actions": ["pro_attrs_precise", "pro_potential_precise"]}
    display_format = "letter_grade"
    try:
        from services.attribute_visibility import _load_scouting_actions_batch, fuzz_letter_grade
        from services.scouting_service import base_to_letter_grade
        actions = _load_scouting_actions_batch(conn, viewing_org_id, [player_id])
        act_types = set(actions.get(player_id, []))
        scouting_info = {
            "unlocked": sorted(act_types),
            "attrs_precise": "pro_attrs_precise" in act_types,
            "pots_precise": "pro_potential_precise" in act_types,
            "available_actions": _available_pro_actions(act_types),
        }

        if "pro_attrs_precise" in act_types:
            display_format = "20-80"
            # Keep raw numeric values
        else:
            display_format = "letter_grade"
            # Fuzz base attrs to letter grades
            for key in list(attributes.keys()):
                if key.endswith("_base"):
                    raw = attributes[key]
                    true_grade = base_to_letter_grade(raw)
                    attributes[key] = fuzz_letter_grade(
                        true_grade, viewing_org_id, player_id, key
                    )

        if "pro_potential_precise" in act_types:
            pass  # keep precise potentials
        else:
            for key in list(potentials.keys()):
                true_pot = potentials[key]
                if true_pot:
                    potentials[key] = fuzz_letter_grade(
                        true_pot, viewing_org_id, player_id, key
                    )
                else:
                    potentials[key] = "?"
    except Exception as e:
        log.warning("Scouting visibility failed for player %d: %s", player_id, e)

    # Contract history
    history_rows = conn.execute(sa_text("""
        SELECT c.id, c.years, c.leagueYearSigned, c.isExtension, c.isBuyout,
               c.bonus, cd.salary, o.org_abbrev
        FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = 1
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
        JOIN organizations o ON o.id = c.signingOrg
        WHERE c.playerID = :pid
        ORDER BY c.leagueYearSigned DESC
    """), {"pid": player_id}).mappings().all()

    contract_history = [
        {
            "org": r["org_abbrev"],
            "years": int(r["years"]),
            "salary": float(r["salary"]),
            "bonus": float(r["bonus"]),
            "signed_year": int(r["leagueYearSigned"]),
            "is_extension": bool(r["isExtension"]),
            "is_buyout": bool(r["isBuyout"]),
        }
        for r in history_rows
    ]

    # Demand data
    demand_info = None
    try:
        from services.player_demands import get_player_demand, compute_fa_demand
        demand = get_player_demand(conn, player_id, league_year_id, "fa")
        if not demand:
            demand = compute_fa_demand(conn, player_id, league_year_id)
        if demand:
            demand_info = {
                "min_aav": demand.get("min_aav"),
                "min_years": demand.get("min_years"),
                "max_years": demand.get("max_years"),
                "war": demand.get("war"),
            }
    except Exception as e:
        log.warning("Demand computation failed for player %d: %s", player_id, e)

    # Auction status
    auction_info = None
    try:
        auc_row = conn.execute(
            select(t["auction"])
            .where(and_(
                t["auction"].c.player_id == player_id,
                t["auction"].c.league_year_id == league_year_id,
                t["auction"].c.phase.in_(["open", "listening", "finalize"]),
            ))
        ).first()
        if auc_row:
            auction_info = get_auction_detail(conn, int(auc_row._mapping["id"]), viewing_org_id)
    except Exception as e:
        log.warning("Auction lookup failed for player %d: %s", player_id, e)

    # Stats summary (last season)
    stats_summary = {"batting": None, "pitching": None}
    try:
        bat = conn.execute(sa_text("""
            SELECT at_bats, hits, doubles_hit, triples, home_runs,
                   walks, strikeouts, runs, stolen_bases, caught_stealing
            FROM player_batting_stats
            WHERE player_id = :pid AND league_year_id = :ly
            LIMIT 1
        """), {"pid": player_id, "ly": league_year_id}).mappings().first()
        if bat and bat["at_bats"] and int(bat["at_bats"]) > 0:
            ab = int(bat["at_bats"])
            h = int(bat["hits"])
            stats_summary["batting"] = {
                "avg": f".{round(h * 1000 / ab):03d}" if ab > 0 else ".000",
                "hr": int(bat["home_runs"]),
                "rbi": 0,  # RBI not in batting stats table directly
                "ab": ab,
                "hits": h,
                "walks": int(bat["walks"]),
                "sb": int(bat["stolen_bases"]),
            }
        pit = conn.execute(sa_text("""
            SELECT innings_pitched_outs, earned_runs, wins, losses,
                   strikeouts, walks
            FROM player_pitching_stats
            WHERE player_id = :pid AND league_year_id = :ly
            LIMIT 1
        """), {"pid": player_id, "ly": league_year_id}).mappings().first()
        if pit and pit["innings_pitched_outs"] and int(pit["innings_pitched_outs"]) > 0:
            ipo = int(pit["innings_pitched_outs"])
            ip = ipo / 3.0
            er = int(pit["earned_runs"])
            stats_summary["pitching"] = {
                "era": round(er * 9.0 / ip, 2) if ip > 0 else 0.0,
                "ip": round(ip, 1),
                "wins": int(pit["wins"]),
                "losses": int(pit["losses"]),
                "strikeouts": int(pit["strikeouts"]),
            }
    except Exception as e:
        log.warning("Stats summary failed for player %d: %s", player_id, e)

    return {
        "bio": bio,
        "attributes": attributes,
        "potentials": potentials,
        "display_format": display_format,
        "contract_history": contract_history,
        "demand": demand_info,
        "auction": auction_info,
        "scouting": scouting_info,
        "stats_summary": stats_summary,
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
