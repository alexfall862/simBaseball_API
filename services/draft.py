# services/draft.py
"""
Draft system business logic.

Every public function takes a `conn` (caller manages commit/rollback),
validates preconditions, and mutates draft tables as needed.
"""

import json
import logging
import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text, update

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
            "draft_state": Table("draft_state", md, autoload_with=engine),
            "draft_picks": Table("draft_picks", md, autoload_with=engine),
            "draft_eligible": Table("draft_eligible_players", md, autoload_with=engine),
            "draft_signing": Table("draft_signing", md, autoload_with=engine),
            "draft_slot_values": Table("draft_slot_values", md, autoload_with=engine),
            "draft_pick_trades": Table("draft_pick_trades", md, autoload_with=engine),
            "contracts": Table("contracts", md, autoload_with=engine),
            "details": Table("contractDetails", md, autoload_with=engine),
            "shares": Table("contractTeamShare", md, autoload_with=engine),
            "players": Table("simbbPlayers", md, autoload_with=engine),
            "teams": Table("teams", md, autoload_with=engine),
            "tx_log": Table("transaction_log", md, autoload_with=engine),
        }
    return _table_cache[eid]


def _t(conn) -> Dict[str, Table]:
    return _get_tables(conn.engine)


from services.org_constants import (
    COLLEGE_ORG_MIN,
    INTAM_ORG_ID, USHS_ORG_ID,
    is_college_org,
)

# Default minor league level for drafted players
DRAFT_TARGET_LEVEL = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_transaction(conn, *, transaction_type: str, league_year_id: int,
                     primary_org_id: int, secondary_org_id: int = None,
                     contract_id: int = None, player_id: int = None,
                     details: dict, executed_by: str = None,
                     notes: str = None) -> int:
    """Insert a row into transaction_log and return its id."""
    t = _t(conn)
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


def _get_draft_state(conn, league_year_id: int) -> Dict[str, Any]:
    """Fetch draft_state row or raise ValueError."""
    row = conn.execute(text(
        "SELECT * FROM draft_state WHERE league_year_id = :lyid"
    ), {"lyid": league_year_id}).mappings().first()
    if not row:
        raise ValueError(f"No draft state for league_year_id={league_year_id}")
    return dict(row)


def _broadcast(event_type: str, **data):
    """Best-effort WebSocket broadcast."""
    try:
        from services.websocket_manager import ws_manager
        ws_manager.broadcast({"type": event_type, **data})
    except Exception:
        logger.debug("WS broadcast failed for %s", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# 1. Draft Order from Standings
# ---------------------------------------------------------------------------

def _compute_draft_order(conn, league_year_id: int) -> List[int]:
    """
    Compute draft order from MLB standings (worst-to-best).

    Returns list of 30 org_ids sorted by win_pct ascending (worst first).
    Teams with the same record are tie-broken by org_id ascending.
    """
    sql = text("""
        SELECT
            t.orgID AS org_id,
            t.id AS team_id,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level = 9
        ORDER BY
            CASE WHEN (COALESCE(w.wins, 0) + COALESCE(l.losses, 0)) = 0
                 THEN 0.0
                 ELSE COALESCE(w.wins, 0) / (COALESCE(w.wins, 0) + COALESCE(l.losses, 0))
            END ASC,
            t.orgID ASC
    """)
    rows = conn.execute(sql, {"lyid": league_year_id}).mappings().all()
    return [r["org_id"] for r in rows]


# ---------------------------------------------------------------------------
# 2. Draft Initialization
# ---------------------------------------------------------------------------

def initialize_draft(conn, league_year_id: int, total_rounds: int = 20,
                     seconds_per_pick: int = 60, is_snake: bool = False
                     ) -> Dict[str, Any]:
    """
    Create draft state, populate pick slots, and build eligible player pool.

    Must be called before start_draft(). Idempotent — raises if already exists.
    """
    existing = conn.execute(text(
        "SELECT id FROM draft_state WHERE league_year_id = :lyid"
    ), {"lyid": league_year_id}).first()
    if existing:
        raise ValueError(f"Draft already initialized for league_year_id={league_year_id}")

    # 1. Compute draft order (worst-to-best MLB teams)
    draft_order = _compute_draft_order(conn, league_year_id)
    picks_per_round = len(draft_order)
    if picks_per_round == 0:
        raise ValueError("No MLB teams found for draft order computation")

    # 2. Create draft_state
    conn.execute(text("""
        INSERT INTO draft_state
            (league_year_id, total_rounds, picks_per_round, is_snake,
             seconds_per_pick, phase, current_round, current_pick)
        VALUES (:lyid, :rounds, :ppr, :snake, :spp, 'SETUP', 1, 1)
    """), {
        "lyid": league_year_id,
        "rounds": total_rounds,
        "ppr": picks_per_round,
        "snake": 1 if is_snake else 0,
        "spp": seconds_per_pick,
    })

    # 3. Populate draft_picks — apply any pre-draft pick trades
    traded = _get_pretrade_map(conn, league_year_id)

    overall = 0
    for rnd in range(1, total_rounds + 1):
        if is_snake and rnd % 2 == 0:
            order = list(reversed(draft_order))
        else:
            order = list(draft_order)
        for pick_idx, org_id in enumerate(order, 1):
            overall += 1
            current_owner = traded.get((rnd, pick_idx), org_id)
            conn.execute(text("""
                INSERT INTO draft_picks
                    (league_year_id, round, pick_in_round, overall_pick,
                     original_org_id, current_org_id)
                VALUES (:lyid, :rnd, :pir, :ovr, :orig, :curr)
            """), {
                "lyid": league_year_id,
                "rnd": rnd,
                "pir": pick_idx,
                "ovr": overall,
                "orig": org_id,
                "curr": current_owner,
            })

    # 4. Populate draft-eligible players
    eligible_count = _populate_eligible_players(conn, league_year_id)

    # 5. Pre-create draft_signing rows with slot values
    _create_signing_rows(conn, league_year_id)

    return {
        "league_year_id": league_year_id,
        "total_rounds": total_rounds,
        "picks_per_round": picks_per_round,
        "total_picks": overall,
        "eligible_players": eligible_count,
        "draft_order": draft_order,
    }


def _get_pretrade_map(conn, league_year_id: int) -> Dict:
    """
    Build a map of (round, pick_in_round) -> to_org_id for pre-draft pick trades.
    """
    rows = conn.execute(text("""
        SELECT round, pick_in_round, to_org_id
        FROM draft_pick_trades
        WHERE league_year_id = :lyid AND pick_in_round IS NOT NULL
    """), {"lyid": league_year_id}).mappings().all()
    result = {}
    for r in rows:
        result[(r["round"], r["pick_in_round"])] = r["to_org_id"]
    return result


def _populate_eligible_players(conn, league_year_id: int) -> int:
    """
    Populate draft_eligible_players from college and HS pools.
    (INTAM players now bypass the draft via the IFA signing system.)
    Ranks by recruiting_rankings composite_score if available.
    """
    # Insert college players
    conn.execute(text("""
        INSERT INTO draft_eligible_players (player_id, league_year_id, source)
        SELECT p.id, :lyid, 'college'
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE (cts.orgID BETWEEN :cmin AND 338 OR cts.orgID IN (341, 342))
        ON DUPLICATE KEY UPDATE source = 'college'
    """), {"lyid": league_year_id, "cmin": COLLEGE_ORG_MIN})

    # Insert HS players
    conn.execute(text("""
        INSERT INTO draft_eligible_players (player_id, league_year_id, source)
        SELECT p.id, :lyid, 'hs'
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE cts.orgID = :hs_org
        ON DUPLICATE KEY UPDATE source = 'hs'
    """), {"lyid": league_year_id, "hs_org": USHS_ORG_ID})

    # Update ranks from recruiting_rankings if available
    conn.execute(text("""
        UPDATE draft_eligible_players dep
        JOIN recruiting_rankings rr
            ON rr.player_id = dep.player_id AND rr.league_year_id = dep.league_year_id
        SET dep.draft_rank = rr.rank_overall
        WHERE dep.league_year_id = :lyid
    """), {"lyid": league_year_id})

    # For players without a recruiting rank, assign ranks based on overall rating
    # (power + contact + eye + discipline as a rough composite)
    conn.execute(text("""
        UPDATE draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        SET dep.draft_rank = 99999
        WHERE dep.league_year_id = :lyid AND dep.draft_rank IS NULL
    """), {"lyid": league_year_id})

    count = conn.execute(text(
        "SELECT COUNT(*) FROM draft_eligible_players WHERE league_year_id = :lyid"
    ), {"lyid": league_year_id}).scalar()
    return count


def _create_signing_rows(conn, league_year_id: int):
    """Pre-create draft_signing rows with slot values for all picks."""
    conn.execute(text("""
        INSERT INTO draft_signing (draft_pick_id, slot_value)
        SELECT src.id, src.sv
        FROM (
            SELECT dp.id, COALESCE(
                dsv_pick.slot_value,
                dsv_round.slot_value,
                60000.00
            ) AS sv
            FROM draft_picks dp
            LEFT JOIN draft_slot_values dsv_pick
                ON dsv_pick.round = dp.round AND dsv_pick.pick_in_round = dp.pick_in_round
            LEFT JOIN draft_slot_values dsv_round
                ON dsv_round.round = dp.round AND dsv_round.pick_in_round IS NULL
            WHERE dp.league_year_id = :lyid
        ) AS src
        ON DUPLICATE KEY UPDATE slot_value = src.sv
    """), {"lyid": league_year_id})


# ---------------------------------------------------------------------------
# 3. Draft Lifecycle
# ---------------------------------------------------------------------------

def start_draft(conn, league_year_id: int) -> Dict[str, Any]:
    """Set phase to IN_PROGRESS, set timer for first pick."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "SETUP":
        raise ValueError(f"Cannot start draft: phase is {state['phase']}")

    deadline = datetime.utcnow() + timedelta(seconds=state["seconds_per_pick"])
    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'IN_PROGRESS', pick_deadline_at = :deadline
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id, "deadline": deadline})

    # Flip global timestamp flag
    from services.timestamp import set_phase_flags
    set_phase_flags(is_draft_time=True)

    _broadcast("draft_state_change",
               phase="IN_PROGRESS",
               current_round=state["current_round"],
               current_pick=state["current_pick"],
               pick_deadline_at=deadline.isoformat())

    return get_draft_state(conn, league_year_id)


def pause_draft(conn, league_year_id: int) -> Dict[str, Any]:
    """Pause the draft timer."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "IN_PROGRESS":
        raise ValueError(f"Cannot pause: phase is {state['phase']}")

    remaining = 0
    if state["pick_deadline_at"]:
        delta = state["pick_deadline_at"] - datetime.utcnow()
        remaining = max(0, int(delta.total_seconds()))

    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'PAUSED', paused_remaining_s = :rem, pick_deadline_at = NULL
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id, "rem": remaining})

    _broadcast("draft_state_change", phase="PAUSED",
               current_round=state["current_round"],
               current_pick=state["current_pick"])

    return get_draft_state(conn, league_year_id)


def resume_draft(conn, league_year_id: int) -> Dict[str, Any]:
    """Resume a paused draft."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "PAUSED":
        raise ValueError(f"Cannot resume: phase is {state['phase']}")

    remaining = state["paused_remaining_s"] or state["seconds_per_pick"]
    deadline = datetime.utcnow() + timedelta(seconds=remaining)

    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'IN_PROGRESS', pick_deadline_at = :deadline,
            paused_remaining_s = NULL
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id, "deadline": deadline})

    _broadcast("draft_state_change", phase="IN_PROGRESS",
               current_round=state["current_round"],
               current_pick=state["current_pick"],
               pick_deadline_at=deadline.isoformat())

    return get_draft_state(conn, league_year_id)


def advance_to_signing(conn, league_year_id: int) -> Dict[str, Any]:
    """Move draft to SIGNING phase."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] not in ("IN_PROGRESS", "PAUSED"):
        raise ValueError(f"Cannot advance to signing: phase is {state['phase']}")

    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'SIGNING', pick_deadline_at = NULL, paused_remaining_s = NULL
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id})

    _broadcast("draft_state_change", phase="SIGNING",
               current_round=state["current_round"],
               current_pick=state["current_pick"])

    return get_draft_state(conn, league_year_id)


def complete_draft(conn, league_year_id: int) -> Dict[str, Any]:
    """Mark draft as COMPLETE."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "SIGNING":
        raise ValueError(f"Cannot complete: phase is {state['phase']}")

    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'COMPLETE'
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id})

    from services.timestamp import set_phase_flags
    set_phase_flags(is_draft_time=False)

    _broadcast("draft_state_change", phase="COMPLETE",
               current_round=state["current_round"],
               current_pick=state["current_pick"])

    return get_draft_state(conn, league_year_id)


# ---------------------------------------------------------------------------
# 4. Pick Selection
# ---------------------------------------------------------------------------

def make_pick(conn, league_year_id: int, org_id: int, player_id: int,
              is_auto: bool = False) -> Dict[str, Any]:
    """
    Record a draft pick.

    Validates: draft is IN_PROGRESS, it's this org's turn, player is eligible
    and not already picked.
    """
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "IN_PROGRESS":
        raise ValueError(f"Draft is not in progress (phase={state['phase']})")

    # Get current pick slot
    pick_row = conn.execute(text("""
        SELECT * FROM draft_picks
        WHERE league_year_id = :lyid
          AND round = :rnd AND pick_in_round = :pir
    """), {
        "lyid": league_year_id,
        "rnd": state["current_round"],
        "pir": state["current_pick"],
    }).mappings().first()

    if not pick_row:
        raise ValueError("Current pick slot not found")

    if pick_row["player_id"] is not None:
        raise ValueError("Current pick already made")

    if not is_auto and pick_row["current_org_id"] != org_id:
        raise ValueError(
            f"It is not org {org_id}'s turn. "
            f"Current pick belongs to org {pick_row['current_org_id']}"
        )

    # Validate player is eligible and not already picked
    eligible = conn.execute(text("""
        SELECT dep.id FROM draft_eligible_players dep
        WHERE dep.player_id = :pid AND dep.league_year_id = :lyid
    """), {"pid": player_id, "lyid": league_year_id}).first()
    if not eligible:
        raise ValueError(f"Player {player_id} is not draft-eligible")

    already_picked = conn.execute(text("""
        SELECT id FROM draft_picks
        WHERE league_year_id = :lyid AND player_id = :pid
    """), {"lyid": league_year_id, "pid": player_id}).first()
    if already_picked:
        raise ValueError(f"Player {player_id} has already been drafted")

    # Record the pick
    now = datetime.utcnow()
    conn.execute(text("""
        UPDATE draft_picks
        SET player_id = :pid, picked_at = :now, is_auto_pick = :auto
        WHERE id = :pick_id
    """), {
        "pid": player_id,
        "pick_id": pick_row["id"],
        "now": now,
        "auto": 1 if is_auto else 0,
    })

    # Get player name for broadcast
    player_name = conn.execute(text(
        "SELECT CONCAT(firstName, ' ', lastName) FROM simbbPlayers WHERE id = :pid"
    ), {"pid": player_id}).scalar() or "Unknown"

    picking_org = pick_row["current_org_id"] if is_auto else org_id

    # Advance to next pick
    advanced = _advance_to_next_pick(conn, state)

    result = {
        "pick_id": pick_row["id"],
        "round": state["current_round"],
        "pick_in_round": state["current_pick"],
        "overall_pick": pick_row["overall_pick"],
        "org_id": picking_org,
        "player_id": player_id,
        "player_name": player_name,
        "is_auto_pick": is_auto,
        "draft_complete": advanced.get("draft_complete", False),
    }

    _broadcast("draft_pick_made", **result)
    return result


def _advance_to_next_pick(conn, state: Dict) -> Dict:
    """Advance current_round/current_pick. Returns info about new state."""
    rnd = state["current_round"]
    pick = state["current_pick"]
    total_rounds = state["total_rounds"]
    ppr = state["picks_per_round"]

    if pick < ppr:
        next_round = rnd
        next_pick = pick + 1
    elif rnd < total_rounds:
        next_round = rnd + 1
        next_pick = 1
    else:
        # Draft is complete — all picks made
        conn.execute(text("""
            UPDATE draft_state
            SET pick_deadline_at = NULL
            WHERE league_year_id = :lyid
        """), {"lyid": state["league_year_id"]})
        return {"draft_complete": True}

    deadline = datetime.utcnow() + timedelta(seconds=state["seconds_per_pick"])
    conn.execute(text("""
        UPDATE draft_state
        SET current_round = :rnd, current_pick = :pick,
            pick_deadline_at = :deadline
        WHERE league_year_id = :lyid
    """), {
        "lyid": state["league_year_id"],
        "rnd": next_round,
        "pick": next_pick,
        "deadline": deadline,
    })

    return {"draft_complete": False, "round": next_round, "pick": next_pick}


def auto_pick(conn, league_year_id: int) -> Dict[str, Any]:
    """Select the highest-ranked available player for the current pick."""
    best = conn.execute(text("""
        SELECT dep.player_id
        FROM draft_eligible_players dep
        LEFT JOIN draft_picks dp
            ON dp.player_id = dep.player_id AND dp.league_year_id = dep.league_year_id
        WHERE dep.league_year_id = :lyid
          AND dp.id IS NULL
        ORDER BY dep.draft_rank ASC, dep.player_id ASC
        LIMIT 1
    """), {"lyid": league_year_id}).first()

    if not best:
        raise ValueError("No eligible players remaining for auto-pick")

    state = _get_draft_state(conn, league_year_id)
    pick_row = conn.execute(text("""
        SELECT current_org_id FROM draft_picks
        WHERE league_year_id = :lyid AND round = :rnd AND pick_in_round = :pir
    """), {
        "lyid": league_year_id,
        "rnd": state["current_round"],
        "pir": state["current_pick"],
    }).mappings().first()

    return make_pick(conn, league_year_id,
                     org_id=pick_row["current_org_id"],
                     player_id=best[0],
                     is_auto=True)


def check_timer_expiry(conn, league_year_id: int) -> List[Dict]:
    """
    Check if the current pick's timer has expired. If so, auto-pick
    in a loop until caught up. Returns list of auto-picks made.
    """
    auto_picks = []
    for _ in range(100):  # safety cap
        state = _get_draft_state(conn, league_year_id)
        if state["phase"] != "IN_PROGRESS":
            break
        if state["pick_deadline_at"] is None:
            break
        if state["pick_deadline_at"] > datetime.utcnow():
            break
        try:
            result = auto_pick(conn, league_year_id)
            auto_picks.append(result)
            if result.get("draft_complete"):
                break
        except ValueError:
            break
    return auto_picks


# ---------------------------------------------------------------------------
# 5. Signing Phase
# ---------------------------------------------------------------------------

def sign_pick(conn, draft_pick_id: int, league_year_id: int,
              executed_by: str = None) -> Dict[str, Any]:
    """
    Sign a drafted player — create contract, update signing status.
    """
    # Get the pick + signing info
    row = conn.execute(text("""
        SELECT dp.*, ds.slot_value, ds.status AS sign_status,
               p.firstName, p.lastName
        FROM draft_picks dp
        JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        JOIN simbbPlayers p ON p.id = dp.player_id
        WHERE dp.id = :pick_id
    """), {"pick_id": draft_pick_id}).mappings().first()

    if not row:
        raise ValueError(f"Draft pick {draft_pick_id} not found")
    if row["player_id"] is None:
        raise ValueError("No player selected for this pick")
    if row["sign_status"] != "pending":
        raise ValueError(f"Signing status is '{row['sign_status']}', expected 'pending'")

    org_id = row["current_org_id"]
    player_id = row["player_id"]
    slot_value = row["slot_value"]

    # Create contract (rookie deal: 3 years, salary = slot_value / 3 per year)
    t = _t(conn)
    years = 3
    per_year = Decimal(str(slot_value)) / years

    # Players age 17 and younger cannot be placed above level 4
    player_age = conn.execute(
        text("SELECT age FROM simbbPlayers WHERE id = :pid"),
        {"pid": player_id},
    ).scalar()
    signing_level = DRAFT_TARGET_LEVEL
    if player_age is not None and int(player_age) <= 17:
        signing_level = min(signing_level, 4)

    # Get current league_year value for signing
    ly_val = conn.execute(text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).scalar()

    result = conn.execute(
        t["contracts"].insert().values(
            playerID=player_id,
            years=years,
            current_year=1,
            isExtension=0,
            isBuyout=0,
            bonus=0,
            signingOrg=org_id,
            leagueYearSigned=ly_val,
            isFinished=0,
            current_level=signing_level,
            onIR=0,
        )
    )
    contract_id = result.lastrowid

    for yr in range(1, years + 1):
        det_result = conn.execute(
            t["details"].insert().values(
                contractID=contract_id,
                year=yr,
                salary=per_year,
            )
        )
        conn.execute(
            t["shares"].insert().values(
                contractDetailsID=det_result.lastrowid,
                orgID=org_id,
                isHolder=1,
                salary_share=Decimal("1.00"),
            )
        )

    # Update signing status
    now = datetime.utcnow()
    conn.execute(text("""
        UPDATE draft_signing
        SET status = 'signed', signed_at = :now, contract_id = :cid
        WHERE draft_pick_id = :pick_id
    """), {"now": now, "cid": contract_id, "pick_id": draft_pick_id})

    # Log transaction
    tx_id = _log_transaction(
        conn,
        transaction_type="draft_sign",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=player_id,
        details={
            "round": row["round"],
            "pick_in_round": row["pick_in_round"],
            "overall_pick": row["overall_pick"],
            "slot_value": float(slot_value),
            "years": years,
            "per_year": float(per_year),
        },
        executed_by=executed_by,
    )

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": player_id,
        "player_name": f"{row['firstName']} {row['lastName']}",
        "org_id": org_id,
        "slot_value": float(slot_value),
        "years": years,
    }


def pass_on_pick(conn, draft_pick_id: int) -> Dict[str, Any]:
    """Pass on signing a drafted player."""
    row = conn.execute(text("""
        SELECT ds.status FROM draft_signing ds
        WHERE ds.draft_pick_id = :pick_id
    """), {"pick_id": draft_pick_id}).mappings().first()

    if not row:
        raise ValueError(f"No signing record for pick {draft_pick_id}")
    if row["status"] != "pending":
        raise ValueError(f"Cannot pass: status is '{row['status']}'")

    conn.execute(text("""
        UPDATE draft_signing SET status = 'passed'
        WHERE draft_pick_id = :pick_id
    """), {"pick_id": draft_pick_id})

    return {"draft_pick_id": draft_pick_id, "status": "passed"}


# ---------------------------------------------------------------------------
# 6. Pick Trading
# ---------------------------------------------------------------------------

def trade_draft_pick(conn, league_year_id: int, pick_id: int,
                     from_org_id: int, to_org_id: int,
                     trade_proposal_id: int = None) -> Dict[str, Any]:
    """
    Trade a draft pick from one org to another.
    Updates current_org_id on the pick and records the trade.
    """
    pick = conn.execute(text("""
        SELECT * FROM draft_picks WHERE id = :pid
    """), {"pid": pick_id}).mappings().first()

    if not pick:
        raise ValueError(f"Draft pick {pick_id} not found")
    if pick["current_org_id"] != from_org_id:
        raise ValueError(f"Org {from_org_id} does not own pick {pick_id}")
    if pick["player_id"] is not None:
        raise ValueError("Cannot trade a pick that has already been used")

    conn.execute(text("""
        UPDATE draft_picks SET current_org_id = :to_org
        WHERE id = :pid
    """), {"to_org": to_org_id, "pid": pick_id})

    conn.execute(text("""
        INSERT INTO draft_pick_trades
            (league_year_id, round, pick_in_round, from_org_id, to_org_id,
             trade_proposal_id)
        VALUES (:lyid, :rnd, :pir, :from_org, :to_org, :tp_id)
    """), {
        "lyid": league_year_id,
        "rnd": pick["round"],
        "pir": pick["pick_in_round"],
        "from_org": from_org_id,
        "to_org": to_org_id,
        "tp_id": trade_proposal_id,
    })

    _log_transaction(
        conn,
        transaction_type="draft_pick_trade",
        league_year_id=league_year_id,
        primary_org_id=from_org_id,
        secondary_org_id=to_org_id,
        details={
            "round": pick["round"],
            "pick_in_round": pick["pick_in_round"],
            "overall_pick": pick["overall_pick"],
        },
    )

    _broadcast("draft_trade_completed",
               round=pick["round"],
               pick_in_round=pick["pick_in_round"],
               from_org_id=from_org_id,
               to_org_id=to_org_id)

    return {
        "pick_id": pick_id,
        "round": pick["round"],
        "pick_in_round": pick["pick_in_round"],
        "from_org_id": from_org_id,
        "to_org_id": to_org_id,
    }


# ---------------------------------------------------------------------------
# 7. Read Queries
# ---------------------------------------------------------------------------

def get_draft_state(conn, league_year_id: int) -> Dict[str, Any]:
    """Get current draft state."""
    state = _get_draft_state(conn, league_year_id)
    # Compute seconds remaining
    seconds_remaining = None
    if state["pick_deadline_at"] and state["phase"] == "IN_PROGRESS":
        delta = state["pick_deadline_at"] - datetime.utcnow()
        seconds_remaining = max(0, int(delta.total_seconds()))
    elif state["phase"] == "PAUSED":
        seconds_remaining = state["paused_remaining_s"]

    return {
        "league_year_id": league_year_id,
        "phase": state["phase"],
        "current_round": state["current_round"],
        "current_pick": state["current_pick"],
        "total_rounds": state["total_rounds"],
        "picks_per_round": state["picks_per_round"],
        "seconds_per_pick": state["seconds_per_pick"],
        "is_snake": bool(state["is_snake"]),
        "pick_deadline_at": (state["pick_deadline_at"].isoformat()
                             if state["pick_deadline_at"] else None),
        "seconds_remaining": seconds_remaining,
    }


def get_draft_board(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """Get full draft board with player info."""
    rows = conn.execute(text("""
        SELECT
            dp.id AS pick_id,
            dp.round,
            dp.pick_in_round,
            dp.overall_pick,
            dp.original_org_id,
            dp.current_org_id,
            dp.player_id,
            dp.picked_at,
            dp.is_auto_pick,
            p.firstName,
            p.lastName,
            ds.slot_value,
            ds.status AS sign_status
        FROM draft_picks dp
        LEFT JOIN simbbPlayers p ON p.id = dp.player_id
        LEFT JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.league_year_id = :lyid
        ORDER BY dp.overall_pick
    """), {"lyid": league_year_id}).mappings().all()

    return [{
        "pick_id": r["pick_id"],
        "round": r["round"],
        "pick_in_round": r["pick_in_round"],
        "overall_pick": r["overall_pick"],
        "original_org_id": r["original_org_id"],
        "current_org_id": r["current_org_id"],
        "player_id": r["player_id"],
        "player_name": (f"{r['firstName']} {r['lastName']}"
                        if r["player_id"] else None),
        "picked_at": r["picked_at"].isoformat() if r["picked_at"] else None,
        "is_auto_pick": bool(r["is_auto_pick"]),
        "slot_value": float(r["slot_value"]) if r["slot_value"] else None,
        "sign_status": r["sign_status"],
    } for r in rows]


_SOURCE_LEVEL_MAP = {"college": 3, "hs": 1, "intam": 2}
_SOURCE_ORG_MAP = {"hs": 340, "intam": 339}


def get_eligible_players(conn, league_year_id: int,
                         source: str = None,
                         search: str = None,
                         available_only: bool = True,
                         limit: int = 100,
                         offset: int = 0,
                         viewing_org_id: int = None) -> Dict[str, Any]:
    """Get draft-eligible players with optional filters and full attributes."""
    from services.player_display import load_display_context, build_player_display
    from services.attribute_visibility import get_visible_players_batch

    conditions = ["dep.league_year_id = :lyid"]
    params: Dict[str, Any] = {"lyid": league_year_id, "lim": limit, "off": offset}

    if source:
        conditions.append("dep.source = :source")
        params["source"] = source

    if search:
        conditions.append(
            "(p.firstName LIKE :search OR p.lastName LIKE :search)"
        )
        params["search"] = f"%{search}%"

    if available_only:
        conditions.append("dp_picked.id IS NULL")

    where = " AND ".join(conditions)

    rows = conn.execute(text(f"""
        SELECT
            p.*,
            dep.source,
            dep.draft_rank,
            rr.composite_score,
            rr.star_rating,
            cts_hold.orgID AS holding_org_id,
            c_hold.current_level
        FROM draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        LEFT JOIN recruiting_rankings rr
            ON rr.player_id = dep.player_id AND rr.league_year_id = dep.league_year_id
        LEFT JOIN draft_picks dp_picked
            ON dp_picked.player_id = dep.player_id
            AND dp_picked.league_year_id = dep.league_year_id
            AND dp_picked.player_id IS NOT NULL
        LEFT JOIN contracts c_hold
            ON c_hold.playerID = p.id AND c_hold.isFinished = 0
        LEFT JOIN contractDetails cd_hold
            ON cd_hold.contractID = c_hold.id AND cd_hold.year = 1
        LEFT JOIN contractTeamShare cts_hold
            ON cts_hold.contractDetailsID = cd_hold.id AND cts_hold.isHolder = 1
        WHERE {where}
        ORDER BY dep.draft_rank ASC, dep.player_id ASC
        LIMIT :lim OFFSET :off
    """), params).mappings().all()

    total = conn.execute(text(f"""
        SELECT COUNT(*)
        FROM draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        LEFT JOIN recruiting_rankings rr
            ON rr.player_id = dep.player_id AND rr.league_year_id = dep.league_year_id
        LEFT JOIN draft_picks dp_picked
            ON dp_picked.player_id = dep.player_id
            AND dp_picked.league_year_id = dep.league_year_id
            AND dp_picked.player_id IS NOT NULL
        WHERE {where}
    """), params).scalar()

    # -- Build display dicts with full attributes --
    ctx = load_display_context(conn)
    players = []
    holding_org_ids = {}
    player_levels = {}

    for r in rows:
        row_dict = dict(r)
        pid = row_dict["id"]

        # Determine current_level from contract join or source default
        level = row_dict.get("current_level")
        if level is None:
            level = _SOURCE_LEVEL_MAP.get(row_dict.get("source"), 3)
        row_dict["current_level"] = level

        # Holding org from contract join, or source-based default
        hold_org = row_dict.get("holding_org_id")
        if hold_org is None:
            hold_org = _SOURCE_ORG_MAP.get(row_dict.get("source"))
        if hold_org is not None:
            holding_org_ids[pid] = hold_org
        player_levels[pid] = level

        display = build_player_display(row_dict, ctx)
        display["source"] = row_dict.get("source")
        display["draft_rank"] = row_dict.get("draft_rank")
        display["composite_score"] = (float(row_dict["composite_score"])
                                      if row_dict.get("composite_score") else None)
        display["star_rating"] = row_dict.get("star_rating")
        # Backward compat fields
        display["player_id"] = pid
        display["first_name"] = row_dict.get("firstName")
        display["last_name"] = row_dict.get("lastName")
        display["age"] = row_dict.get("age")
        display["pitcher_role"] = row_dict.get("pitcherRole")
        players.append(display)

    # -- Apply fog-of-war if viewing_org_id provided --
    if viewing_org_id is not None and players:
        players = get_visible_players_batch(
            conn,
            players,
            viewing_org_id,
            holding_org_ids,
            player_levels,
            ctx["dist_by_level"],
            ctx["col_cats"],
            position_weights=ctx["position_weights"],
        )

    return {
        "players": players,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_org_picks(conn, org_id: int, league_year_id: int) -> List[Dict]:
    """Get all picks owned by a specific org."""
    rows = conn.execute(text("""
        SELECT
            dp.id AS pick_id, dp.round, dp.pick_in_round, dp.overall_pick,
            dp.original_org_id, dp.current_org_id,
            dp.player_id, dp.picked_at, dp.is_auto_pick,
            p.firstName, p.lastName,
            ds.slot_value, ds.status AS sign_status
        FROM draft_picks dp
        LEFT JOIN simbbPlayers p ON p.id = dp.player_id
        LEFT JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.league_year_id = :lyid AND dp.current_org_id = :oid
        ORDER BY dp.overall_pick
    """), {"lyid": league_year_id, "oid": org_id}).mappings().all()

    return [{
        "pick_id": r["pick_id"],
        "round": r["round"],
        "pick_in_round": r["pick_in_round"],
        "overall_pick": r["overall_pick"],
        "original_org_id": r["original_org_id"],
        "current_org_id": r["current_org_id"],
        "player_id": r["player_id"],
        "player_name": (f"{r['firstName']} {r['lastName']}"
                        if r["player_id"] else None),
        "picked_at": r["picked_at"].isoformat() if r["picked_at"] else None,
        "is_auto_pick": bool(r["is_auto_pick"]),
        "slot_value": float(r["slot_value"]) if r["slot_value"] else None,
        "sign_status": r["sign_status"],
    } for r in rows]


# ---------------------------------------------------------------------------
# 8. Admin Overrides
# ---------------------------------------------------------------------------

def admin_set_pick(conn, league_year_id: int, round_num: int,
                   pick_in_round: int, player_id: int) -> Dict[str, Any]:
    """Admin override: force-assign a player to a specific pick slot."""
    pick = conn.execute(text("""
        SELECT * FROM draft_picks
        WHERE league_year_id = :lyid AND round = :rnd AND pick_in_round = :pir
    """), {"lyid": league_year_id, "rnd": round_num, "pir": pick_in_round}
    ).mappings().first()

    if not pick:
        raise ValueError(f"Pick slot R{round_num}P{pick_in_round} not found")

    # Check player not already drafted
    already = conn.execute(text("""
        SELECT id FROM draft_picks
        WHERE league_year_id = :lyid AND player_id = :pid
    """), {"lyid": league_year_id, "pid": player_id}).first()
    if already:
        raise ValueError(f"Player {player_id} already drafted")

    now = datetime.utcnow()
    conn.execute(text("""
        UPDATE draft_picks
        SET player_id = :pid, picked_at = :now, is_auto_pick = 0
        WHERE id = :pick_id
    """), {"pid": player_id, "now": now, "pick_id": pick["id"]})

    return {"pick_id": pick["id"], "player_id": player_id, "set_by": "admin"}


def admin_remove_pick(conn, draft_pick_id: int) -> Dict[str, Any]:
    """Admin override: undo a pick."""
    conn.execute(text("""
        UPDATE draft_picks
        SET player_id = NULL, picked_at = NULL, is_auto_pick = 0
        WHERE id = :pid
    """), {"pid": draft_pick_id})

    # Reset signing status
    conn.execute(text("""
        UPDATE draft_signing
        SET status = 'pending', signed_at = NULL, contract_id = NULL
        WHERE draft_pick_id = :pid
    """), {"pid": draft_pick_id})

    return {"draft_pick_id": draft_pick_id, "removed": True}


def admin_reset_timer(conn, league_year_id: int) -> Dict[str, Any]:
    """Reset the timer on the current pick."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "IN_PROGRESS":
        raise ValueError(f"Cannot reset timer: phase is {state['phase']}")

    deadline = datetime.utcnow() + timedelta(seconds=state["seconds_per_pick"])
    conn.execute(text("""
        UPDATE draft_state SET pick_deadline_at = :deadline
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id, "deadline": deadline})

    return {"pick_deadline_at": deadline.isoformat(),
            "seconds_remaining": state["seconds_per_pick"]}


# ---------------------------------------------------------------------------
# 9. Export / Finalization
# ---------------------------------------------------------------------------

def export_draft(conn, league_year_id: int,
                 executed_by: str = None) -> Dict[str, Any]:
    """
    Finalize the draft: for all signed picks, move the player's contract
    from their amateur org to the drafting org's minor league system.

    Uses bulk JOINed queries instead of per-pick lookups (~3 queries total
    vs ~4N for N signed picks).
    """
    # Single JOINed query: signed picks + player age + contract year + detail ID
    signed = conn.execute(text("""
        SELECT dp.id AS pick_id, dp.current_org_id, dp.player_id,
               ds.contract_id, dp.round, dp.pick_in_round,
               p.age AS player_age,
               c.current_year,
               cd.id AS detail_id
        FROM draft_picks dp
        JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        JOIN simbbPlayers p ON p.id = dp.player_id
        JOIN contracts c ON c.id = ds.contract_id
        LEFT JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        WHERE dp.league_year_id = :lyid AND ds.status = 'signed'
    """), {"lyid": league_year_id}).mappings().all()

    if not signed:
        return {"exported": 0, "players": []}

    # Batch UPDATE contracts — set current_level based on player age
    for row in signed:
        target = DRAFT_TARGET_LEVEL
        if row["player_age"] is not None and int(row["player_age"]) <= 17:
            target = min(target, 4)
        conn.execute(text("""
            UPDATE contracts SET current_level = :level WHERE id = :cid
        """), {"level": target, "cid": row["contract_id"]})

    # Batch UPDATE holder org on contractTeamShare
    share_params = []
    for row in signed:
        if row["detail_id"] is not None:
            share_params.append({
                "org_id": row["current_org_id"],
                "det_id": row["detail_id"],
            })
    if share_params:
        conn.execute(text("""
            UPDATE contractTeamShare
            SET orgID = :org_id
            WHERE contractDetailsID = :det_id AND isHolder = 1
        """), share_params)

    moved = [{
        "player_id": row["player_id"],
        "org_id": row["current_org_id"],
        "contract_id": row["contract_id"],
        "round": row["round"],
        "pick_in_round": row["pick_in_round"],
    } for row in signed]

    return {
        "exported": len(moved),
        "players": moved,
    }
