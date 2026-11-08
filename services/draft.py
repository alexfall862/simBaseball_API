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
            "draft_round_modes": Table("draft_round_modes", md, autoload_with=engine),
            "draft_team_prefs": Table("draft_team_prefs", md, autoload_with=engine),
            "draft_player_queue": Table("draft_player_queue", md, autoload_with=engine),
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
DRAFT_TARGET_LEVEL = 5          # college draftees -> A (level 5)
DRAFT_HS_LEVEL = 4              # HS draftees -> level 4
ROOKIE_YEARS = 3
ROOKIE_SALARY = Decimal("40000.00")   # MINOR_SALARY
MAX_SIGNING_OFFERS = 3

# Bonus ask = slot_value * class_mult * talent_mult. Underclassmen ask for
# more (they can go back to school) and are less willing to take a discount.
CLASS_MULT = {
    "senior": Decimal("1.00"), "junior": Decimal("1.15"),
    "sophomore": Decimal("1.35"), "freshman": Decimal("1.60"),
    "hs_senior": Decimal("1.10"),
}
WILLINGNESS = {
    "senior": 1.0, "hs_senior": 1.0, "junior": 0.6,
    "sophomore": 0.35, "freshman": 0.2,
}
TALENT_MULT_TOP = Decimal("1.30")
TALENT_MULT_BOTTOM = Decimal("0.90")


def talent_multiplier(draft_rank: Optional[int], pool_size: int) -> Decimal:
    """1.30 for the consensus #1, sliding linearly to 0.90 for the last."""
    if not draft_rank or pool_size <= 1:
        return Decimal("1.00")
    frac = Decimal(max(0, min(pool_size - 1, int(draft_rank) - 1))) / Decimal(pool_size - 1)
    return (TALENT_MULT_TOP - (TALENT_MULT_TOP - TALENT_MULT_BOTTOM) * frac).quantize(
        Decimal("0.0001"))


def compute_bonus_ask(slot_value, class_year: Optional[str],
                      draft_rank: Optional[int], pool_size: int) -> Decimal:
    cls = CLASS_MULT.get((class_year or "senior").lower(), Decimal("1.00"))
    ask = Decimal(str(slot_value)) * cls * talent_multiplier(draft_rank, pool_size)
    return ask.quantize(Decimal("0.01"))


def acceptance_probability(offer, ask, class_year: Optional[str]) -> float:
    """1.0 at/above the ask; below it, linear from 60% of the ask (0) to the
    ask (1), scaled by the class willingness."""
    offer = float(offer)
    ask = float(ask) if ask else 0.0
    if ask <= 0 or offer >= ask:
        return 1.0
    base = (offer / ask - 0.6) / 0.4
    base = max(0.0, min(1.0, base))
    return base * WILLINGNESS.get((class_year or "senior").lower(), 1.0)


def offer_roll(draft_pick_id: int, offer_no: int) -> float:
    """Deterministic [0,1) roll for a pick's n-th offer (replayable)."""
    import random as _random
    return _random.Random(f"draft-offer:{draft_pick_id}:{offer_no}").random()


def _is_cpu_org(conn, org_id: int) -> bool:
    """An MLB org with neither an owner nor a GM name is CPU-controlled."""
    row = conn.execute(text(
        "SELECT owner_name, gm_name FROM organizations WHERE id = :o"
    ), {"o": org_id}).first()
    if not row:
        return False
    return not ((row[0] or "").strip() or (row[1] or "").strip())


def _set_signing_ask(conn, draft_pick_id: int, player_id: int,
                     league_year_id: int) -> Dict[str, Any]:
    """Compute and store ask/class/willingness on the pick's signing row."""
    pool_size = conn.execute(text(
        "SELECT COUNT(*) FROM draft_eligible_players WHERE league_year_id = :ly"
    ), {"ly": league_year_id}).scalar() or 0
    dep = conn.execute(text("""
        SELECT class_year, draft_rank FROM draft_eligible_players
        WHERE league_year_id = :ly AND player_id = :pid
    """), {"ly": league_year_id, "pid": player_id}).mappings().first()
    class_year = (dep["class_year"] if dep and dep["class_year"] else None)
    if class_year is None:
        class_year = _class_year_from_contract(conn, player_id)
    rank = dep["draft_rank"] if dep else None
    slot = conn.execute(text(
        "SELECT slot_value FROM draft_signing WHERE draft_pick_id = :pid"
    ), {"pid": draft_pick_id}).scalar()
    if slot is None:
        return {}
    ask = compute_bonus_ask(slot, class_year, rank, int(pool_size))
    will = WILLINGNESS.get(class_year, 1.0)
    conn.execute(text("""
        UPDATE draft_signing
        SET ask_bonus = :ask, class_year = :cy, willingness = :will,
            offers_made = 0, bonus_agreed = NULL, resolved_at = NULL
        WHERE draft_pick_id = :pid
    """), {"ask": ask, "cy": class_year, "will": will, "pid": draft_pick_id})
    return {"ask_bonus": float(ask), "class_year": class_year, "willingness": will}


def _class_year_from_contract(conn, player_id: int) -> str:
    """Fallback class from the player's active amateur contract."""
    row = conn.execute(text("""
        SELECT current_level, years, current_year FROM contracts
        WHERE playerID = :pid AND isFinished = 0 AND current_level <= 3
        ORDER BY id DESC LIMIT 1
    """), {"pid": player_id}).first()
    if not row:
        return "senior"
    level, years, cy = int(row[0]), int(row[1]), int(row[2])
    if level == 1:
        return "hs_senior"
    remaining = years - cy
    if remaining <= 0:
        return "senior"
    if remaining == 1:
        return "junior"
    if remaining == 2:
        return "sophomore"
    return "freshman"


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


def _get_draft_state(conn, league_year_id: int,
                     for_update: bool = False) -> Dict[str, Any]:
    """Fetch draft_state row or raise ValueError.

    ``for_update=True`` locks the row for the rest of the transaction so two
    concurrent pick submissions serialize on it (the second one then sees the
    advanced pointer and is refused instead of double-picking the slot)."""
    row = conn.execute(text(
        "SELECT * FROM draft_state WHERE league_year_id = :lyid"
        + (" FOR UPDATE" if for_update else "")
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
# Round Mode Helpers
# ---------------------------------------------------------------------------

def _get_round_mode(conn, league_year_id: int, round_num: int) -> str:
    """Return 'live' or 'auto' for a given round.  Defaults to 'live'."""
    row = conn.execute(text(
        "SELECT mode FROM draft_round_modes "
        "WHERE league_year_id = :lyid AND `round` = :rnd"
    ), {"lyid": league_year_id, "rnd": round_num}).scalar()
    return row or "live"


def _is_auto_round(conn, league_year_id: int, round_num: int) -> bool:
    return _get_round_mode(conn, league_year_id, round_num) == "auto"


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
                     seconds_per_pick: int = 60, is_snake: bool = False,
                     live_rounds: List[int] = None) -> Dict[str, Any]:
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

    # 6. Populate round modes (default: rounds 1-3 live, rest auto)
    if live_rounds is None:
        live_rounds = [1, 2, 3]
    live_set = set(live_rounds)
    for rnd in range(1, total_rounds + 1):
        mode = "live" if rnd in live_set else "auto"
        conn.execute(text("""
            INSERT INTO draft_round_modes (league_year_id, `round`, mode)
            VALUES (:lyid, :rnd, :mode)
        """), {"lyid": league_year_id, "rnd": rnd, "mode": mode})

    return {
        "league_year_id": league_year_id,
        "total_rounds": total_rounds,
        "picks_per_round": picks_per_round,
        "total_picks": overall,
        "eligible_players": eligible_count,
        "draft_order": draft_order,
        "live_rounds": sorted(live_set),
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
    Draft pool = HS graduates of the season just finished + every college
    player (freshman through redshirt senior; nobody declares), ranked by a
    composite of true ratings and potentials ("industry consensus").

    End-season builds this snapshot (``graduation.build_draft_pool``) when
    the seniors graduate. If it exists we only make sure it is ranked; if
    end-season has not run (tests, ad-hoc drafts) we build it from the
    active rosters, treating HS contracts in their final year as seniors.
    """
    from services.graduation import build_draft_pool, rank_draft_pool

    existing = conn.execute(text(
        "SELECT COUNT(*) FROM draft_eligible_players WHERE league_year_id = :lyid"
    ), {"lyid": league_year_id}).scalar() or 0
    if existing:
        unranked = conn.execute(text("""
            SELECT COUNT(*) FROM draft_eligible_players
            WHERE league_year_id = :lyid AND (draft_rank IS NULL OR draft_rank >= 99999)
        """), {"lyid": league_year_id}).scalar() or 0
        if unranked:
            rank_draft_pool(conn, league_year_id)
        return int(existing)

    return build_draft_pool(conn, league_year_id, include_active_hs_seniors=True)


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
    """Set phase to IN_PROGRESS, set timer for first pick (or no timer if auto)."""
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "SETUP":
        raise ValueError(f"Cannot start draft: phase is {state['phase']}")

    round_1_auto = _is_auto_round(conn, league_year_id, 1)

    if round_1_auto:
        # No timer — admin must call run-auto-rounds to proceed
        conn.execute(text("""
            UPDATE draft_state
            SET phase = 'IN_PROGRESS', pick_deadline_at = NULL
            WHERE league_year_id = :lyid
        """), {"lyid": league_year_id})
    else:
        deadline = datetime.utcnow() + timedelta(
            seconds=state["seconds_per_pick"])
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
               current_pick=state["current_pick"])

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
    """
    Close the signing window and mark the draft COMPLETE.

    1. CPU-controlled orgs sign their pending picks at the ask.
    2. Every other pending pick is resolved: ``refused`` if the org made
       offers that were turned down, ``passed`` if it never made one. The
       player keeps his amateur contract (returns to school).
    3. Unsigned HS graduates without a college commitment are placed at
       random on programs with roster room (``college_roster_target``); the
       surplus retires. Undrafted college seniors stay in the system as
       free agents only above ``undrafted_keep_ovr``; the rest retire.
       Programs still below the roster floor are topped up with generated
       walk-ons.
    """
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "SIGNING":
        raise ValueError(f"Cannot complete: phase is {state['phase']}")

    resolution = _resolve_pending_signings(conn, league_year_id)

    conn.execute(text("""
        UPDATE draft_state
        SET phase = 'COMPLETE'
        WHERE league_year_id = :lyid
    """), {"lyid": league_year_id})

    post: Dict[str, Any] = {}
    try:
        from services.graduation import (
            enroll_hs_walkons, retire_undrafted_seniors, topup_college_rosters,
        )
        from services.league_calendar import resolve_league_year
        ly_val = resolve_league_year(conn, league_year_id)
        post.update(enroll_hs_walkons(conn, league_year_id, ly_val))
        post.update(retire_undrafted_seniors(conn, league_year_id))
        post.update(topup_college_rosters(conn, league_year_id, ly_val))
    except Exception as e:
        logger.exception("complete_draft: post-draft amateur resolution failed")
        post["error"] = str(e)

    # Draftees, walk-ons and graduates changed level cohorts: refresh the
    # stored displayovr (a cohort percentile) and its breakpoints.
    try:
        from services.ovr_core import recompute_stored_displayovr
        post["displayovr_refresh"] = recompute_stored_displayovr(conn)
    except Exception as e:
        logger.exception("complete_draft: displayovr refresh failed")
        post["displayovr_refresh_error"] = str(e)

    from services.timestamp import set_phase_flags
    set_phase_flags(is_draft_time=False)

    _broadcast("draft_state_change", phase="COMPLETE",
               current_round=state["current_round"],
               current_pick=state["current_pick"])

    out = get_draft_state(conn, league_year_id)
    out["signing_resolution"] = resolution
    out["post_draft"] = post
    return out


def _resolve_pending_signings(conn, league_year_id: int) -> Dict[str, Any]:
    """CPU orgs sign at the ask; remaining pending picks become refused/passed."""
    summary = {"cpu_signed": 0, "cpu_failed": 0, "refused": 0, "passed": 0}
    pending = conn.execute(text("""
        SELECT dp.id AS pick_id, dp.current_org_id, ds.ask_bonus, ds.slot_value,
               ds.offers_made
        FROM draft_picks dp
        JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.league_year_id = :lyid AND dp.player_id IS NOT NULL
          AND ds.status = 'pending'
        ORDER BY dp.overall_pick
    """), {"lyid": league_year_id}).mappings().all()

    for p in pending:
        if _is_cpu_org(conn, int(p["current_org_id"])):
            try:
                with conn.begin_nested():
                    res = sign_pick(conn, int(p["pick_id"]), league_year_id,
                                    executed_by="cpu",
                                    bonus=p["ask_bonus"] or p["slot_value"])
                if res.get("accepted"):
                    summary["cpu_signed"] += 1
                    continue
            except Exception as e:
                logger.warning("cpu signing failed for pick %s: %s", p["pick_id"], e)
                summary["cpu_failed"] += 1
        status = "refused" if int(p["offers_made"] or 0) > 0 else "passed"
        conn.execute(text("""
            UPDATE draft_signing SET status = :st, resolved_at = :now
            WHERE draft_pick_id = :pid AND status = 'pending'
        """), {"st": status, "now": datetime.utcnow(), "pid": p["pick_id"]})
        summary[status] += 1
    return summary


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
    state = _get_draft_state(conn, league_year_id, for_update=True)
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

    # Bonus ask for the signing phase (visible to the drafting org)
    ask = _set_signing_ask(conn, pick_row["id"], player_id, league_year_id)

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
        "auto_round_next": advanced.get("auto_round", False),
        "ask_bonus": ask.get("ask_bonus"),
        "class_year": ask.get("class_year"),
    }

    _broadcast("draft_pick_made", **{k: v for k, v in result.items()
                                     if k not in ("ask_bonus",)})

    # A CPU-controlled org on the clock in a live round picks immediately.
    if (not advanced.get("draft_complete") and not advanced.get("auto_round")
            and not is_auto):
        _cpu_autopick_chain(conn, league_year_id)
    return result


def _cpu_autopick_chain(conn, league_year_id: int, max_picks: int = 60) -> int:
    """While the org on the clock has no owner/GM, auto-pick for it."""
    made = 0
    for _ in range(max_picks):
        state = _get_draft_state(conn, league_year_id)
        if state["phase"] != "IN_PROGRESS":
            break
        if _is_auto_round(conn, league_year_id, state["current_round"]):
            break
        row = conn.execute(text("""
            SELECT current_org_id, player_id FROM draft_picks
            WHERE league_year_id = :lyid AND `round` = :rnd AND pick_in_round = :pir
        """), {"lyid": league_year_id, "rnd": state["current_round"],
               "pir": state["current_pick"]}).first()
        if not row or row[1] is not None or not _is_cpu_org(conn, int(row[0])):
            break
        try:
            auto_pick(conn, league_year_id)
            made += 1
        except ValueError:
            break
    return made


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

    # Check if next round is auto — skip timer if so
    next_is_auto = _is_auto_round(
        conn, state["league_year_id"], next_round)

    if next_is_auto:
        conn.execute(text("""
            UPDATE draft_state
            SET current_round = :rnd, current_pick = :pick,
                pick_deadline_at = NULL
            WHERE league_year_id = :lyid
        """), {
            "lyid": state["league_year_id"],
            "rnd": next_round,
            "pick": next_pick,
        })
        return {"draft_complete": False, "round": next_round,
                "pick": next_pick, "auto_round": True}
    else:
        deadline = datetime.utcnow() + timedelta(
            seconds=state["seconds_per_pick"])
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
        return {"draft_complete": False, "round": next_round,
                "pick": next_pick}


def _smart_auto_pick(conn, league_year_id: int, org_id: int) -> int:
    """
    Preference-aware player selection for auto-picks.

    Three-tier logic checked in order:
      1. Highest-priority available player from the team's queue
      2. BPA within the position type (pitcher/hitter) that still has
         unfilled quota
      3. Pure BPA fallback (original behaviour)

    Returns a player_id.
    """
    # --- Layer 1: Player Queue ---
    queued = conn.execute(text("""
        SELECT dpq.player_id
        FROM draft_player_queue dpq
        JOIN draft_eligible_players dep
            ON dep.player_id = dpq.player_id
           AND dep.league_year_id = dpq.league_year_id
        LEFT JOIN draft_picks dp
            ON dp.player_id = dpq.player_id
           AND dp.league_year_id = dpq.league_year_id
           AND dp.player_id IS NOT NULL
        WHERE dpq.league_year_id = :lyid
          AND dpq.org_id = :oid
          AND dp.id IS NULL
        ORDER BY dpq.priority ASC
        LIMIT 1
    """), {"lyid": league_year_id, "oid": org_id}).scalar()

    if queued:
        return queued

    # --- Layer 2: Positional Quota (pitcher / hitter) ---
    prefs = conn.execute(text(
        "SELECT pitcher_quota, hitter_quota FROM draft_team_prefs "
        "WHERE league_year_id = :lyid AND org_id = :oid"
    ), {"lyid": league_year_id, "oid": org_id}).mappings().first()

    if prefs and (prefs["pitcher_quota"] > 0 or prefs["hitter_quota"] > 0):
        counts = conn.execute(text("""
            SELECT
                SUM(CASE WHEN p.ptype = 'Pitcher' THEN 1 ELSE 0 END) AS pitchers_drafted,
                SUM(CASE WHEN p.ptype != 'Pitcher' OR p.ptype IS NULL
                         THEN 1 ELSE 0 END) AS hitters_drafted
            FROM draft_picks dp
            JOIN simbbPlayers p ON p.id = dp.player_id
            WHERE dp.league_year_id = :lyid
              AND dp.current_org_id = :oid
              AND dp.player_id IS NOT NULL
        """), {"lyid": league_year_id, "oid": org_id}).mappings().first()

        pitchers_drafted = int(counts["pitchers_drafted"] or 0)
        hitters_drafted = int(counts["hitters_drafted"] or 0)

        pitcher_need = prefs["pitcher_quota"] - pitchers_drafted
        hitter_need = prefs["hitter_quota"] - hitters_drafted

        # Pick the type with more remaining need; tie goes to pitcher
        target_type = None
        if pitcher_need > 0 and hitter_need > 0:
            target_type = "pitcher" if pitcher_need >= hitter_need else "hitter"
        elif pitcher_need > 0:
            target_type = "pitcher"
        elif hitter_need > 0:
            target_type = "hitter"

        if target_type:
            ptype_cond = ("p.ptype = 'Pitcher'" if target_type == "pitcher"
                          else "(p.ptype != 'Pitcher' OR p.ptype IS NULL)")

            typed_pick = conn.execute(text(f"""
                SELECT dep.player_id
                FROM draft_eligible_players dep
                JOIN simbbPlayers p ON p.id = dep.player_id
                LEFT JOIN draft_picks dp
                    ON dp.player_id = dep.player_id
                   AND dp.league_year_id = dep.league_year_id
                   AND dp.player_id IS NOT NULL
                WHERE dep.league_year_id = :lyid
                  AND dp.id IS NULL
                  AND {ptype_cond}
                ORDER BY dep.draft_rank ASC, dep.player_id ASC
                LIMIT 1
            """), {"lyid": league_year_id}).scalar()

            if typed_pick:
                return typed_pick

    # --- Layer 3: Pure BPA fallback ---
    bpa = conn.execute(text("""
        SELECT dep.player_id
        FROM draft_eligible_players dep
        LEFT JOIN draft_picks dp
            ON dp.player_id = dep.player_id
           AND dp.league_year_id = dep.league_year_id
           AND dp.player_id IS NOT NULL
        WHERE dep.league_year_id = :lyid
          AND dp.id IS NULL
        ORDER BY dep.draft_rank ASC, dep.player_id ASC
        LIMIT 1
    """), {"lyid": league_year_id}).scalar()

    if not bpa:
        raise ValueError("No eligible players remaining for auto-pick")

    return bpa


def auto_pick(conn, league_year_id: int) -> Dict[str, Any]:
    """Select a player for the current pick using preference-aware logic."""
    state = _get_draft_state(conn, league_year_id)
    pick_row = conn.execute(text("""
        SELECT current_org_id FROM draft_picks
        WHERE league_year_id = :lyid AND `round` = :rnd AND pick_in_round = :pir
    """), {
        "lyid": league_year_id,
        "rnd": state["current_round"],
        "pir": state["current_pick"],
    }).mappings().first()

    player_id = _smart_auto_pick(conn, league_year_id, pick_row["current_org_id"])

    return make_pick(conn, league_year_id,
                     org_id=pick_row["current_org_id"],
                     player_id=player_id,
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
            # Stop at auto-round boundary — admin triggers manually
            if result.get("auto_round_next"):
                break
        except ValueError:
            break
    return auto_picks


# ---------------------------------------------------------------------------
# 5. Signing Phase
# ---------------------------------------------------------------------------

def sign_pick(conn, draft_pick_id: int, league_year_id: int,
              executed_by: str = None, bonus=None) -> Dict[str, Any]:
    """
    Make a signing-bonus offer to a drafted player.

    ``bonus`` defaults to the pick's slot value. The answer is immediate and
    deterministic for (pick, offer number): accepted outright at or above
    the player's ask, otherwise with ``acceptance_probability``. Up to
    ``MAX_SIGNING_OFFERS`` offers per pick; a rejected final offer refuses
    the player, who returns to school on his amateur contract.

    On acceptance: 3-year minor-salary rookie deal (HS -> level 4, college
    -> level 5), bonus = the agreed amount, debited from the org's ledger
    now (counts against the signing budget), amateur contract finished.

    Returns ``{"accepted": bool, ...}``; the HTTP status is 200 either way.
    """
    row = conn.execute(text("""
        SELECT dp.*, ds.slot_value, ds.status AS sign_status, ds.ask_bonus,
               ds.class_year, ds.offers_made,
               p.firstName, p.lastName, p.age
        FROM draft_picks dp
        JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        JOIN simbbPlayers p ON p.id = dp.player_id
        WHERE dp.id = :pick_id
        FOR UPDATE
    """), {"pick_id": draft_pick_id}).mappings().first()

    if not row:
        raise ValueError(f"Draft pick {draft_pick_id} not found")
    if row["player_id"] is None:
        raise ValueError("No player selected for this pick")
    if row["sign_status"] != "pending":
        raise ValueError(f"Signing status is '{row['sign_status']}', expected 'pending'")

    org_id = int(row["current_org_id"])
    player_id = int(row["player_id"])
    slot_value = Decimal(str(row["slot_value"]))
    offers_made = int(row["offers_made"] or 0)
    if offers_made >= MAX_SIGNING_OFFERS:
        raise ValueError("No offers remaining for this pick")

    # Ask may be missing for picks made before the negotiation existed.
    if row["ask_bonus"] is None:
        _set_signing_ask(conn, draft_pick_id, player_id, int(row["league_year_id"]))
        ask_row = conn.execute(text(
            "SELECT ask_bonus, class_year FROM draft_signing WHERE draft_pick_id = :p"
        ), {"p": draft_pick_id}).first()
        ask = Decimal(str(ask_row[0] or slot_value))
        class_year = ask_row[1] or "senior"
    else:
        ask = Decimal(str(row["ask_bonus"]))
        class_year = row["class_year"] or "senior"

    offer_amt = Decimal(str(bonus)) if bonus is not None else slot_value
    if offer_amt < 0:
        raise ValueError("Bonus offer cannot be negative")

    # The rookie deal belongs to the upcoming season (the draft runs in the
    # offseason); resolve the year it is booked against.
    from services.league_calendar import resolve_signing_year
    league_year_id, ly_val = resolve_signing_year(conn, league_year_id)

    # Budget check against the year the bonus is booked in.
    from services.transactions import _get_signing_budget
    budget = _get_signing_budget(conn, org_id, league_year_id)
    if offer_amt > budget:
        raise ValueError(
            f"Signing bonus offer ({offer_amt}) exceeds available budget ({budget})")

    offer_no = offers_made + 1
    prob = acceptance_probability(offer_amt, ask, class_year)
    roll = offer_roll(draft_pick_id, offer_no)
    accepted = roll < prob
    now = datetime.utcnow()

    conn.execute(text("""
        INSERT INTO draft_signing_offers
            (draft_pick_id, offer_no, amount, accept_prob, roll, result)
        VALUES (:pid, :no, :amt, :prob, :roll, :res)
    """), {"pid": draft_pick_id, "no": offer_no, "amt": offer_amt,
           "prob": round(prob, 4), "roll": round(roll, 4),
           "res": "accepted" if accepted else "rejected"})

    base = {
        "draft_pick_id": draft_pick_id,
        "player_id": player_id,
        "player_name": f"{row['firstName']} {row['lastName']}",
        "org_id": org_id,
        "slot_value": float(slot_value),
        "ask_bonus": float(ask),
        "class_year": class_year,
        "offer_no": offer_no,
        "offer": float(offer_amt),
        "accept_probability": round(prob, 4),
    }

    if not accepted:
        refused = offer_no >= MAX_SIGNING_OFFERS
        conn.execute(text("""
            UPDATE draft_signing
            SET offers_made = :n, status = :st, resolved_at = :ra
            WHERE draft_pick_id = :pid
        """), {"n": offer_no, "st": "refused" if refused else "pending",
               "ra": now if refused else None, "pid": draft_pick_id})
        if refused:
            _log_transaction(
                conn, transaction_type="draft_refused", league_year_id=league_year_id,
                primary_org_id=org_id, player_id=player_id,
                details={"offers": offer_no, "ask_bonus": float(ask),
                         "last_offer": float(offer_amt), "class_year": class_year},
                executed_by=executed_by,
                notes="Draftee refused to sign and returns to school",
            )
        base.update({
            "accepted": False,
            "status": "refused" if refused else "pending",
            "offers_remaining": max(0, MAX_SIGNING_OFFERS - offer_no),
        })
        return base

    # ── Accepted: rookie contract ────────────────────────────────────
    t = _t(conn)
    years = ROOKIE_YEARS
    signing_level = DRAFT_HS_LEVEL if class_year == "hs_senior" else DRAFT_TARGET_LEVEL
    if row["age"] is not None and int(row["age"]) <= 17:
        signing_level = min(signing_level, DRAFT_HS_LEVEL)

    # End the player's amateur (HS / college) contract. Without this the
    # player stayed on his school's roster as well as the drafting org's.
    conn.execute(text("""
        UPDATE contracts
        SET isFinished = 1, isActive = 0
        WHERE playerID = :pid AND isFinished = 0 AND current_level <= 3
    """), {"pid": player_id})

    result = conn.execute(
        t["contracts"].insert().values(
            playerID=player_id,
            years=years,
            current_year=1,
            isExtension=0,
            isBuyout=0,
            isActive=1,
            bonus=offer_amt,
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
                salary=ROOKIE_SALARY,
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

    # Bonus debited now (year-start books skip contracts that already have a
    # ledger bonus entry, so it is not charged twice).
    ledger_entry_id = None
    if offer_amt > 0:
        led = conn.execute(text("""
            INSERT INTO org_ledger_entries
                (org_id, league_year_id, game_week_id, entry_type, amount,
                 contract_id, player_id, note)
            VALUES (:org, :ly, NULL, 'bonus', :amt, :cid, :pid, :note)
        """), {"org": org_id, "ly": league_year_id, "amt": -offer_amt,
               "cid": contract_id, "pid": player_id,
               "note": f"Draft signing bonus (contract {contract_id})"})
        ledger_entry_id = led.lastrowid

    conn.execute(text("""
        UPDATE draft_signing
        SET status = 'signed', signed_at = :now, resolved_at = :now,
            contract_id = :cid, offers_made = :n, bonus_agreed = :amt
        WHERE draft_pick_id = :pick_id
    """), {"now": now, "cid": contract_id, "n": offer_no, "amt": offer_amt,
           "pick_id": draft_pick_id})

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
            "ask_bonus": float(ask),
            "bonus": float(offer_amt),
            "offer_no": offer_no,
            "years": years,
            "per_year": float(ROOKIE_SALARY),
            "level": signing_level,
            "ledger_entry_id": ledger_entry_id,
        },
        executed_by=executed_by,
    )

    base.update({
        "accepted": True,
        "status": "signed",
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "bonus": float(offer_amt),
        "years": years,
        "level": signing_level,
        "offers_remaining": 0,
    })
    return base


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
# 6b. Pick trade proposals (interface: draft/trade/propose|proposals|accept|reject)
# ---------------------------------------------------------------------------

def _org_abbrev_map(conn, org_ids: List[int]) -> Dict[int, str]:
    if not org_ids:
        return {}
    rows = conn.execute(text(
        "SELECT id, org_abbrev FROM organizations WHERE id IN (%s)"
        % ",".join(str(int(i)) for i in set(org_ids))
    )).all()
    return {int(r[0]): r[1] for r in rows}


def _picks_brief(conn, pick_ids: List[int]) -> List[Dict[str, Any]]:
    if not pick_ids:
        return []
    rows = conn.execute(text(
        "SELECT id, `round`, pick_in_round, overall_pick, current_org_id, player_id "
        "FROM draft_picks WHERE id IN (%s) ORDER BY overall_pick"
        % ",".join(str(int(i)) for i in pick_ids)
    )).mappings().all()
    return [{"pick_id": int(r["id"]), "round": int(r["round"]),
             "pick_in_round": int(r["pick_in_round"]),
             "overall_pick": int(r["overall_pick"]),
             "current_org_id": int(r["current_org_id"]),
             "used": r["player_id"] is not None} for r in rows]


def _validate_pick_ownership(conn, league_year_id: int, pick_ids: List[int],
                             org_id: int, label: str) -> None:
    for p in _picks_brief(conn, pick_ids):
        if p["current_org_id"] != org_id:
            raise ValueError(f"{label}: pick {p['pick_id']} is not owned by org {org_id}")
        if p["used"]:
            raise ValueError(f"{label}: pick {p['pick_id']} has already been used")
    found = {p["pick_id"] for p in _picks_brief(conn, pick_ids)}
    missing = [i for i in pick_ids if int(i) not in found]
    if missing:
        raise ValueError(f"{label}: unknown pick ids {missing}")
    rows = conn.execute(text(
        "SELECT id FROM draft_picks WHERE id IN (%s) AND league_year_id = :ly"
        % ",".join(str(int(i)) for i in pick_ids)
    ), {"ly": league_year_id}).all() if pick_ids else []
    if len(rows) != len(set(int(i) for i in pick_ids)):
        raise ValueError(f"{label}: picks must belong to league_year_id {league_year_id}")


def create_draft_trade_proposal(conn, league_year_id: int, proposing_org_id: int,
                                receiving_org_id: int, picks_offered: List[int],
                                picks_requested: List[int]) -> Dict[str, Any]:
    if proposing_org_id == receiving_org_id:
        raise ValueError("Cannot propose a trade with yourself")
    picks_offered = [int(i) for i in (picks_offered or [])]
    picks_requested = [int(i) for i in (picks_requested or [])]
    if not picks_offered and not picks_requested:
        raise ValueError("A proposal needs at least one pick on either side")
    _validate_pick_ownership(conn, league_year_id, picks_offered, proposing_org_id,
                             "picks_offered")
    _validate_pick_ownership(conn, league_year_id, picks_requested, receiving_org_id,
                             "picks_requested")
    res = conn.execute(text("""
        INSERT INTO draft_trade_proposals
            (league_year_id, proposing_org_id, receiving_org_id,
             picks_offered, picks_requested, status)
        VALUES (:ly, :po, :ro, :off, :req, 'proposed')
    """), {"ly": league_year_id, "po": proposing_org_id, "ro": receiving_org_id,
           "off": json.dumps(picks_offered), "req": json.dumps(picks_requested)})
    proposal_id = res.lastrowid
    _broadcast("draft_trade_proposed", proposal_id=proposal_id,
               proposing_org_id=proposing_org_id, receiving_org_id=receiving_org_id)
    return {"success": True, "proposal_id": proposal_id}


def _proposal_row(conn, proposal_id: int) -> Dict[str, Any]:
    row = conn.execute(text(
        "SELECT * FROM draft_trade_proposals WHERE id = :id FOR UPDATE"
    ), {"id": proposal_id}).mappings().first()
    if not row:
        raise ValueError(f"Proposal {proposal_id} not found")
    d = dict(row)
    for k in ("picks_offered", "picks_requested"):
        v = d.get(k)
        d[k] = json.loads(v) if isinstance(v, str) else (v or [])
    return d


def _proposal_view(conn, d: Dict[str, Any]) -> Dict[str, Any]:
    abbrevs = _org_abbrev_map(conn, [d["proposing_org_id"], d["receiving_org_id"]])
    return {
        "proposal_id": int(d["id"]),
        "league_year_id": int(d["league_year_id"]),
        "proposing_org_id": int(d["proposing_org_id"]),
        "proposing_org_abbrev": abbrevs.get(int(d["proposing_org_id"])),
        "receiving_org_id": int(d["receiving_org_id"]),
        "receiving_org_abbrev": abbrevs.get(int(d["receiving_org_id"])),
        "picks_offered": _picks_brief(conn, d["picks_offered"]),
        "picks_requested": _picks_brief(conn, d["picks_requested"]),
        "status": d["status"],
        "created_at": _iso_z(d.get("created_at")),
        "resolved_at": _iso_z(d.get("resolved_at")),
    }


def list_draft_trade_proposals(conn, league_year_id: int, org_id: Optional[int] = None,
                               status: Optional[str] = None) -> List[Dict[str, Any]]:
    conds = ["league_year_id = :ly"]
    params: Dict[str, Any] = {"ly": league_year_id}
    if org_id is not None:
        conds.append("(proposing_org_id = :org OR receiving_org_id = :org)")
        params["org"] = org_id
    if status:
        conds.append("status = :st")
        params["st"] = status
    rows = conn.execute(text(
        "SELECT * FROM draft_trade_proposals WHERE %s ORDER BY created_at DESC, id DESC"
        % " AND ".join(conds)), params).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("picks_offered", "picks_requested"):
            v = d.get(k)
            d[k] = json.loads(v) if isinstance(v, str) else (v or [])
        out.append(_proposal_view(conn, d))
    return out


def accept_draft_trade_proposal(conn, proposal_id: int,
                                acting_org_id: Optional[int] = None) -> Dict[str, Any]:
    d = _proposal_row(conn, proposal_id)
    if d["status"] != "proposed":
        raise ValueError(f"Proposal is {d['status']}, not open")
    if acting_org_id is not None and int(acting_org_id) != int(d["receiving_org_id"]):
        raise ValueError("Only the receiving org can accept this proposal")
    lyid = int(d["league_year_id"])
    # Re-validate ownership at acceptance time (picks may have been used/traded)
    _validate_pick_ownership(conn, lyid, d["picks_offered"], int(d["proposing_org_id"]),
                             "picks_offered")
    _validate_pick_ownership(conn, lyid, d["picks_requested"], int(d["receiving_org_id"]),
                             "picks_requested")
    for pid in d["picks_offered"]:
        trade_draft_pick(conn, lyid, int(pid), int(d["proposing_org_id"]),
                         int(d["receiving_org_id"]), trade_proposal_id=proposal_id)
    for pid in d["picks_requested"]:
        trade_draft_pick(conn, lyid, int(pid), int(d["receiving_org_id"]),
                         int(d["proposing_org_id"]), trade_proposal_id=proposal_id)
    conn.execute(text("""
        UPDATE draft_trade_proposals SET status = 'accepted', resolved_at = :now
        WHERE id = :id
    """), {"now": datetime.utcnow(), "id": proposal_id})
    # Any other open proposal touching these picks is now stale
    touched = set(int(p) for p in d["picks_offered"] + d["picks_requested"])
    for other in list_draft_trade_proposals(conn, lyid, status="proposed"):
        ids = {p["pick_id"] for p in other["picks_offered"] + other["picks_requested"]}
        if ids & touched:
            conn.execute(text("""
                UPDATE draft_trade_proposals SET status = 'cancelled', resolved_at = :now
                WHERE id = :id AND status = 'proposed'
            """), {"now": datetime.utcnow(), "id": other["proposal_id"]})
    d["status"] = "accepted"
    return {"success": True, **_proposal_view(conn, _proposal_row(conn, proposal_id))}


def reject_draft_trade_proposal(conn, proposal_id: int,
                                acting_org_id: Optional[int] = None) -> Dict[str, Any]:
    d = _proposal_row(conn, proposal_id)
    if d["status"] != "proposed":
        raise ValueError(f"Proposal is {d['status']}, not open")
    if acting_org_id is not None and int(acting_org_id) not in (
            int(d["receiving_org_id"]), int(d["proposing_org_id"])):
        raise ValueError("Only the orgs involved can reject/cancel this proposal")
    new_status = ("cancelled" if acting_org_id is not None
                  and int(acting_org_id) == int(d["proposing_org_id"]) else "rejected")
    conn.execute(text("""
        UPDATE draft_trade_proposals SET status = :st, resolved_at = :now WHERE id = :id
    """), {"st": new_status, "now": datetime.utcnow(), "id": proposal_id})
    _broadcast("draft_trade_rejected", proposal_id=proposal_id, status=new_status)
    return {"success": True, **_proposal_view(conn, _proposal_row(conn, proposal_id))}


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
        "pick_deadline_at": _iso_z(state["pick_deadline_at"]),
        "seconds_remaining": seconds_remaining,
        "current_round_mode": _get_round_mode(
            conn, league_year_id, state["current_round"]),
        "auto_rounds_locked": bool(state.get("auto_rounds_locked", 0)),
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
            ds.status AS sign_status,
            ds.class_year,
            ds.offers_made,
            ds.bonus_agreed
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
        "picked_at": _iso_z(r["picked_at"]),
        "is_auto_pick": bool(r["is_auto_pick"]),
        "slot_value": float(r["slot_value"]) if r["slot_value"] else None,
        "sign_status": r["sign_status"],
        "class_year": r["class_year"],
        "offers_made": int(r["offers_made"] or 0),
        "bonus_agreed": float(r["bonus_agreed"]) if r["bonus_agreed"] is not None else None,
    } for r in rows]


def _iso_z(dt) -> Optional[str]:
    """Naive UTC datetime -> ISO-8601 with an explicit Z."""
    if not dt:
        return None
    s = dt.isoformat()
    return s if s.endswith("Z") or "+" in s else s + "Z"


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
            dep.class_year,
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
        display["class_year"] = row_dict.get("class_year")
        display["composite_score"] = (float(row_dict["composite_score"])
                                      if row_dict.get("composite_score") else None)
        display["star_rating"] = row_dict.get("star_rating")
        # Backward compat fields
        display["player_id"] = pid
        display["first_name"] = row_dict.get("firstName") or row_dict.get("firstname")
        display["last_name"] = row_dict.get("lastName") or row_dict.get("lastname")
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
    """All picks owned by an org, with the (org-private) bonus ask and the
    offers made so far on each pick."""
    rows = conn.execute(text("""
        SELECT
            dp.id AS pick_id, dp.round, dp.pick_in_round, dp.overall_pick,
            dp.original_org_id, dp.current_org_id,
            dp.player_id, dp.picked_at, dp.is_auto_pick,
            p.firstName, p.lastName,
            ds.slot_value, ds.status AS sign_status, ds.ask_bonus, ds.class_year,
            ds.offers_made, ds.bonus_agreed, ds.contract_id
        FROM draft_picks dp
        LEFT JOIN simbbPlayers p ON p.id = dp.player_id
        LEFT JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.league_year_id = :lyid AND dp.current_org_id = :oid
        ORDER BY dp.overall_pick
    """), {"lyid": league_year_id, "oid": org_id}).mappings().all()

    offers_by_pick: Dict[int, List[Dict[str, Any]]] = {}
    pick_ids = [int(r["pick_id"]) for r in rows]
    if pick_ids:
        try:
            for o in conn.execute(text(
                "SELECT draft_pick_id, offer_no, amount, result, created_at "
                "FROM draft_signing_offers WHERE draft_pick_id IN (%s) "
                "ORDER BY draft_pick_id, offer_no" % ",".join(str(i) for i in pick_ids)
            )).mappings().all():
                offers_by_pick.setdefault(int(o["draft_pick_id"]), []).append({
                    "offer_no": int(o["offer_no"]),
                    "amount": float(o["amount"]),
                    "result": o["result"],
                    "created_at": _iso_z(o["created_at"]),
                })
        except Exception:
            logger.debug("draft_signing_offers not readable", exc_info=True)

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
        "picked_at": _iso_z(r["picked_at"]),
        "is_auto_pick": bool(r["is_auto_pick"]),
        "slot_value": float(r["slot_value"]) if r["slot_value"] else None,
        "sign_status": r["sign_status"],
        "ask_bonus": float(r["ask_bonus"]) if r["ask_bonus"] is not None else None,
        "class_year": r["class_year"],
        "offers_made": int(r["offers_made"] or 0),
        "offers_remaining": max(0, MAX_SIGNING_OFFERS - int(r["offers_made"] or 0))
                            if r["player_id"] else None,
        "offers": offers_by_pick.get(int(r["pick_id"]), []),
        "bonus_agreed": float(r["bonus_agreed"]) if r["bonus_agreed"] is not None else None,
        "contract_id": r["contract_id"],
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

    state = _get_draft_state(conn, league_year_id, for_update=True)
    if state["phase"] == "COMPLETE":
        raise ValueError("Draft is complete; picks can no longer be changed")
    if pick["player_id"] is not None:
        raise ValueError(
            f"Pick slot R{round_num}P{pick_in_round} already holds player "
            f"{pick['player_id']}; remove it first"
        )

    eligible = conn.execute(text("""
        SELECT 1 FROM draft_eligible_players
        WHERE player_id = :pid AND league_year_id = :lyid
    """), {"pid": player_id, "lyid": league_year_id}).first()
    if not eligible:
        raise ValueError(f"Player {player_id} is not draft-eligible")

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

    player_name = conn.execute(text(
        "SELECT CONCAT(firstName, ' ', lastName) FROM simbbPlayers WHERE id = :pid"
    ), {"pid": player_id}).scalar() or "Unknown"

    _set_signing_ask(conn, pick["id"], player_id, league_year_id)

    # If the admin filled the slot the draft is waiting on, move the pointer
    # on exactly as a normal pick would (otherwise the draft stalls on it).
    advanced: Dict[str, Any] = {}
    is_current = (state["phase"] == "IN_PROGRESS"
                  and int(state["current_round"]) == int(round_num)
                  and int(state["current_pick"]) == int(pick_in_round))
    if is_current:
        advanced = _advance_to_next_pick(conn, state)

    result = {
        "pick_id": pick["id"],
        "round": int(round_num),
        "pick_in_round": int(pick_in_round),
        "overall_pick": pick["overall_pick"],
        "org_id": pick["current_org_id"],
        "player_id": player_id,
        "player_name": player_name,
        "is_auto_pick": False,
        "draft_complete": advanced.get("draft_complete", False),
        "auto_round_next": advanced.get("auto_round", False),
        "set_by": "admin",
        "pointer_advanced": is_current,
    }
    _broadcast("draft_pick_made", **{k: v for k, v in result.items()
                                     if k not in ("set_by", "pointer_advanced")})
    return result


def admin_remove_pick(conn, draft_pick_id: int) -> Dict[str, Any]:
    """Admin override: undo a pick.

    Voids the rookie contract if the pick was already signed and restores
    the player's amateur contract; if the pick is the most recent one made,
    the draft pointer rewinds to it so the draft resumes there."""
    pick = conn.execute(text("""
        SELECT dp.*, ds.status AS sign_status, ds.contract_id
        FROM draft_picks dp
        LEFT JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.id = :pid
    """), {"pid": draft_pick_id}).mappings().first()
    if not pick:
        raise ValueError(f"Draft pick {draft_pick_id} not found")
    if pick["player_id"] is None:
        return {"draft_pick_id": draft_pick_id, "removed": False,
                "note": "pick slot was already empty"}

    state = _get_draft_state(conn, int(pick["league_year_id"]), for_update=True)
    player_id = int(pick["player_id"])
    contract_voided = None

    if pick["contract_id"]:
        conn.execute(text("""
            UPDATE contracts SET isFinished = 1, isActive = 0 WHERE id = :cid
        """), {"cid": pick["contract_id"]})
        # The bonus was debited at signing: take the ledger entry back.
        conn.execute(text("""
            DELETE FROM org_ledger_entries
            WHERE contract_id = :cid AND entry_type = 'bonus'
        """), {"cid": pick["contract_id"]})
        # Reinstate the amateur contract sign_pick ended (most recent one).
        conn.execute(text("""
            UPDATE contracts SET isFinished = 0, isActive = 1
            WHERE playerID = :pid AND current_level <= 3
            ORDER BY id DESC LIMIT 1
        """), {"pid": player_id})
        contract_voided = int(pick["contract_id"])

    conn.execute(text("""
        UPDATE draft_picks
        SET player_id = NULL, picked_at = NULL, is_auto_pick = 0
        WHERE id = :pid
    """), {"pid": draft_pick_id})

    # Reset signing status and the negotiation history
    conn.execute(text("""
        UPDATE draft_signing
        SET status = 'pending', signed_at = NULL, contract_id = NULL,
            ask_bonus = NULL, class_year = NULL, willingness = NULL,
            offers_made = 0, bonus_agreed = NULL, resolved_at = NULL
        WHERE draft_pick_id = :pid
    """), {"pid": draft_pick_id})
    conn.execute(text(
        "DELETE FROM draft_signing_offers WHERE draft_pick_id = :pid"
    ), {"pid": draft_pick_id})

    # Rewind the pointer if this was the last pick made.
    rewound = False
    if state["phase"] in ("IN_PROGRESS", "PAUSED"):
        prev = conn.execute(text("""
            SELECT round, pick_in_round FROM draft_picks
            WHERE league_year_id = :lyid AND player_id IS NOT NULL
            ORDER BY overall_pick DESC LIMIT 1
        """), {"lyid": pick["league_year_id"]}).first()
        last_made_overall = conn.execute(text("""
            SELECT MAX(overall_pick) FROM draft_picks
            WHERE league_year_id = :lyid AND player_id IS NOT NULL
        """), {"lyid": pick["league_year_id"]}).scalar()
        if last_made_overall is None or int(pick["overall_pick"]) > int(last_made_overall):
            # Removed pick was at or past the frontier: resume from it.
            conn.execute(text("""
                UPDATE draft_state
                SET current_round = :rnd, current_pick = :pir
                WHERE league_year_id = :lyid
            """), {"rnd": pick["round"], "pir": pick["pick_in_round"],
                   "lyid": pick["league_year_id"]})
            rewound = True
            _broadcast("draft_state_change", phase=state["phase"],
                       current_round=int(pick["round"]),
                       current_pick=int(pick["pick_in_round"]))

    return {
        "draft_pick_id": draft_pick_id,
        "removed": True,
        "player_id": player_id,
        "contract_voided": contract_voided,
        "pointer_rewound": rewound,
    }


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
# 8b. Round Mode & Team Preference CRUD
# ---------------------------------------------------------------------------

def set_round_modes(conn, league_year_id: int,
                    round_modes: Dict[int, str]) -> Dict[str, Any]:
    """
    Configure which rounds are live vs auto.  SETUP phase only.
    round_modes: {round_number: 'live' | 'auto'}
    """
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "SETUP":
        raise ValueError(f"Cannot set round modes: phase is {state['phase']}")

    for rnd, mode in round_modes.items():
        if mode not in ("live", "auto"):
            raise ValueError(f"Invalid mode '{mode}' for round {rnd}")
        if rnd < 1 or rnd > state["total_rounds"]:
            raise ValueError(
                f"Round {rnd} out of range (1-{state['total_rounds']})")
        conn.execute(text("""
            INSERT INTO draft_round_modes (league_year_id, `round`, mode)
            VALUES (:lyid, :rnd, :mode)
            AS new_row ON DUPLICATE KEY UPDATE mode = new_row.mode
        """), {"lyid": league_year_id, "rnd": rnd, "mode": mode})

    return {"league_year_id": league_year_id,
            "rounds_configured": len(round_modes)}


def get_round_modes(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """Return live/auto mode for every round (fills defaults for missing rows)."""
    state = _get_draft_state(conn, league_year_id)
    rows = conn.execute(text(
        "SELECT `round`, mode FROM draft_round_modes "
        "WHERE league_year_id = :lyid ORDER BY `round`"
    ), {"lyid": league_year_id}).mappings().all()
    mode_map = {r["round"]: r["mode"] for r in rows}
    return [
        {"round": rnd, "mode": mode_map.get(rnd, "live")}
        for rnd in range(1, state["total_rounds"] + 1)
    ]


def set_team_prefs(conn, league_year_id: int, org_id: int,
                   pitcher_quota: int = None, hitter_quota: int = None,
                   queue: List[int] = None) -> Dict[str, Any]:
    """
    Set or update auto-draft preferences for a team.

    - pitcher_quota / hitter_quota: target counts for auto rounds
    - queue: ordered list of player_ids (first = highest priority)

    Raises if auto rounds have already started (locked).
    """
    state = _get_draft_state(conn, league_year_id)
    if state.get("auto_rounds_locked"):
        raise ValueError(
            "Auto-draft preferences are locked — auto rounds have begun")

    # -- Upsert quotas --
    if pitcher_quota is not None or hitter_quota is not None:
        existing = conn.execute(text(
            "SELECT pitcher_quota, hitter_quota FROM draft_team_prefs "
            "WHERE league_year_id = :lyid AND org_id = :oid"
        ), {"lyid": league_year_id, "oid": org_id}).mappings().first()

        pq = (pitcher_quota if pitcher_quota is not None
              else (existing["pitcher_quota"] if existing else 0))
        hq = (hitter_quota if hitter_quota is not None
              else (existing["hitter_quota"] if existing else 0))

        conn.execute(text("""
            INSERT INTO draft_team_prefs
                (league_year_id, org_id, pitcher_quota, hitter_quota)
            VALUES (:lyid, :oid, :pq, :hq)
            AS new_row ON DUPLICATE KEY UPDATE
                pitcher_quota = new_row.pitcher_quota,
                hitter_quota  = new_row.hitter_quota
        """), {"lyid": league_year_id, "oid": org_id, "pq": pq, "hq": hq})

    # -- Replace queue --
    if queue is not None:
        if queue:
            # Validate all player_ids are draft-eligible
            placeholders = ",".join(str(int(pid)) for pid in queue)
            eligible = conn.execute(text(f"""
                SELECT player_id FROM draft_eligible_players
                WHERE league_year_id = :lyid
                  AND player_id IN ({placeholders})
            """), {"lyid": league_year_id}).scalars().all()
            eligible_set = set(eligible)
            invalid = [pid for pid in queue if pid not in eligible_set]
            if invalid:
                raise ValueError(f"Players not draft-eligible: {invalid}")

        conn.execute(text(
            "DELETE FROM draft_player_queue "
            "WHERE league_year_id = :lyid AND org_id = :oid"
        ), {"lyid": league_year_id, "oid": org_id})

        for priority, player_id in enumerate(queue, 1):
            conn.execute(text("""
                INSERT INTO draft_player_queue
                    (league_year_id, org_id, player_id, priority)
                VALUES (:lyid, :oid, :pid, :pri)
            """), {"lyid": league_year_id, "oid": org_id,
                   "pid": player_id, "pri": priority})

    return {"org_id": org_id, "league_year_id": league_year_id,
            "updated": True}


def get_team_prefs(conn, league_year_id: int,
                   org_id: int) -> Dict[str, Any]:
    """Return current auto-draft preferences for a team (quotas + queue)."""
    prefs = conn.execute(text(
        "SELECT pitcher_quota, hitter_quota, locked FROM draft_team_prefs "
        "WHERE league_year_id = :lyid AND org_id = :oid"
    ), {"lyid": league_year_id, "oid": org_id}).mappings().first()

    queue = conn.execute(text(
        "SELECT player_id, priority FROM draft_player_queue "
        "WHERE league_year_id = :lyid AND org_id = :oid "
        "ORDER BY priority ASC"
    ), {"lyid": league_year_id, "oid": org_id}).mappings().all()

    return {
        "org_id": org_id,
        "pitcher_quota": prefs["pitcher_quota"] if prefs else 0,
        "hitter_quota": prefs["hitter_quota"] if prefs else 0,
        "locked": bool(prefs["locked"]) if prefs else False,
        "queue": [{"player_id": q["player_id"], "priority": q["priority"]}
                  for q in queue],
    }


# ---------------------------------------------------------------------------
# 8c. Auto-Round Execution
# ---------------------------------------------------------------------------

def execute_auto_rounds(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """
    Execute all picks in consecutive auto rounds starting from the current
    position.  Called by admin via the run-auto-rounds endpoint.

    Locks preferences on first call, then iterates through every pick in
    each auto round using _smart_auto_pick.
    """
    state = _get_draft_state(conn, league_year_id)
    if state["phase"] != "IN_PROGRESS":
        raise ValueError(
            f"Cannot run auto rounds: phase is {state['phase']}")
    if not _is_auto_round(conn, league_year_id, state["current_round"]):
        raise ValueError(
            f"Round {state['current_round']} is not an auto round")

    # Lock preferences if not already locked
    if not state.get("auto_rounds_locked"):
        conn.execute(text(
            "UPDATE draft_state SET auto_rounds_locked = 1 "
            "WHERE league_year_id = :lyid"
        ), {"lyid": league_year_id})
        conn.execute(text(
            "UPDATE draft_team_prefs SET locked = 1 "
            "WHERE league_year_id = :lyid"
        ), {"lyid": league_year_id})

    _broadcast("auto_rounds_started", league_year_id=league_year_id,
               starting_round=state["current_round"])

    results = []
    safety_cap = state["total_rounds"] * state["picks_per_round"]

    for _ in range(safety_cap):
        state = _get_draft_state(conn, league_year_id)

        if state["phase"] != "IN_PROGRESS":
            break

        # Stop if we've left auto-round territory
        if not _is_auto_round(conn, league_year_id, state["current_round"]):
            break

        # Get current pick's org
        pick_row = conn.execute(text("""
            SELECT id, current_org_id, player_id FROM draft_picks
            WHERE league_year_id = :lyid
              AND `round` = :rnd AND pick_in_round = :pir
        """), {
            "lyid": league_year_id,
            "rnd": state["current_round"],
            "pir": state["current_pick"],
        }).mappings().first()

        if not pick_row or pick_row["player_id"] is not None:
            break

        player_id = _smart_auto_pick(
            conn, league_year_id, pick_row["current_org_id"])
        result = make_pick(conn, league_year_id,
                           org_id=pick_row["current_org_id"],
                           player_id=player_id,
                           is_auto=True)
        results.append(result)

        if result.get("draft_complete"):
            break

    _broadcast("auto_rounds_completed", league_year_id=league_year_id,
               picks_made=len(results))

    return results


# ---------------------------------------------------------------------------
# 9. Export / Finalization
# ---------------------------------------------------------------------------

def export_draft(conn, league_year_id: int,
                 executed_by: str = None) -> Dict[str, Any]:
    """
    No-op kept for the admin panel. sign_pick() now ends the amateur
    contract and books the rookie deal to the drafting org directly, so
    there is nothing left to export.
    """
    signed = conn.execute(text("""
        SELECT COUNT(*) FROM draft_picks dp
        JOIN draft_signing ds ON ds.draft_pick_id = dp.id
        WHERE dp.league_year_id = :lyid AND ds.status = 'signed'
    """), {"lyid": league_year_id}).scalar() or 0
    return {"exported": 0, "players": [], "signed_picks": int(signed),
            "note": "Export is no longer needed: signing a pick moves the player."}


def _export_draft_legacy(conn, league_year_id: int,
                         executed_by: str = None) -> Dict[str, Any]:
    """
    (Legacy, unused) Finalize the draft: for all signed picks, move the
    player's contract from their amateur org to the drafting org's system.

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
