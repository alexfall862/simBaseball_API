# services/ifa_signing.py
"""
International Free Agent (IFA) Signing Period.

MLB orgs (1-30) compete to sign international amateur prospects (org 339)
via bonus-pool-constrained, per-player 3-phase auctions over a 20-week window.

All public functions take a SQLAlchemy Core `conn`; caller manages
commit / rollback.
"""

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import MetaData, Table, and_, func, select, text, update

from services.org_constants import (
    MLB_ORG_MIN, MLB_ORG_MAX,
    INTAM_ORG_ID,
)
from services.recruiting import (
    compute_composite,
    assign_stars,
    POS_BASE_ATTRS, POS_POT_ATTRS,
    PIT_BASE_ATTRS, PIT_POT_ATTRS,
)

log = logging.getLogger("app")

IFA_TARGET_LEVEL = 4

# ---------------------------------------------------------------------------
# Table reflection (cached per-engine)
# ---------------------------------------------------------------------------

_table_cache: Dict[int, Dict[str, Table]] = {}


def _get_tables(engine) -> Dict[str, Table]:
    eid = id(engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "ifa_state":    Table("ifa_state", md, autoload_with=engine),
            "pools":        Table("ifa_bonus_pools", md, autoload_with=engine),
            "auction":      Table("ifa_auction", md, autoload_with=engine),
            "offers":       Table("ifa_auction_offers", md, autoload_with=engine),
            "config":       Table("ifa_config", md, autoload_with=engine),
            "contracts":    Table("contracts", md, autoload_with=engine),
            "details":      Table("contractDetails", md, autoload_with=engine),
            "shares":       Table("contractTeamShare", md, autoload_with=engine),
            "players":      Table("simbbPlayers", md, autoload_with=engine),
            "rankings":     Table("recruiting_rankings", md, autoload_with=engine),
            "tx_log":       Table("transaction_log", md, autoload_with=engine),
        }
    return _table_cache[eid]


def _t(conn) -> Dict[str, Table]:
    return _get_tables(conn.engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_transaction(conn, *, transaction_type: str, league_year_id: int,
                     primary_org_id: int, secondary_org_id: int = None,
                     contract_id: int = None, player_id: int = None,
                     details: dict, executed_by: str = None,
                     notes: str = None) -> int:
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_ifa_config(conn) -> Dict[str, str]:
    """Read ifa_config into a {key: value} dict."""
    rows = conn.execute(
        text("SELECT config_key, config_value FROM ifa_config")
    ).all()
    return {r[0]: r[1] for r in rows}


def _cfg_int(config, key, fallback):
    return int(float(config.get(key, fallback)))


def _cfg_dec(config, key, fallback):
    return Decimal(config.get(key, str(fallback)))


def _cfg_float(config, key, fallback):
    return float(config.get(key, fallback))


def _slot_value_for_star(config, star: int) -> Decimal:
    """Look up slot value for a star rating from config."""
    return _cfg_dec(config, f"slot_{star}star", 100000)


# ---------------------------------------------------------------------------
# Star rankings for INTAM players
# ---------------------------------------------------------------------------

_PLAYER_ATTRS_SQL = """
    SELECT p.id, p.ptype, p.age,
           p.contact_base, p.power_base, p.discipline_base,
           p.eye_base, p.speed_base, p.baserunning_base,
           p.throwpower_base, p.throwacc_base,
           p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
           p.pendurance_base, p.pgencontrol_base, p.pthrowpower_base,
           p.psequencing_base,
           p.pitch1_pacc_base, p.pitch1_pbrk_base,
           p.pitch1_pcntrl_base, p.pitch1_consist_base,
           p.pitch2_pacc_base, p.pitch2_pbrk_base,
           p.pitch2_pcntrl_base, p.pitch2_consist_base,
           p.contact_pot, p.power_pot, p.discipline_pot,
           p.eye_pot, p.speed_pot,
           p.pendurance_pot, p.pgencontrol_pot,
           p.pthrowpower_pot, p.psequencing_pot
    FROM simbbPlayers p
    JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
    JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
    JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
    WHERE cts.orgID = :intam AND p.age >= :min_age
"""


def compute_ifa_star_rankings(conn, league_year_id: int, min_age: int = 16) -> int:
    """
    Compute composite scores for INTAM players (org 339) age >= min_age
    and assign star ratings. Persists to recruit_stars + recruiting_rankings.

    Returns count of ranked players.
    """
    rows = conn.execute(
        text(_PLAYER_ATTRS_SQL),
        {"intam": INTAM_ORG_ID, "min_age": min_age},
    ).all()

    if not rows:
        return 0

    pos_scored = []
    pit_scored = []
    for r in rows:
        m = r._mapping
        ptype = m["ptype"] or "Position"
        if ptype == "Pitcher":
            comp = compute_composite(m, PIT_BASE_ATTRS, PIT_POT_ATTRS)
            pit_scored.append((m["id"], ptype, comp))
        else:
            comp = compute_composite(m, POS_BASE_ATTRS, POS_POT_ATTRS)
            pos_scored.append((m["id"], ptype, comp))

    pos_scored.sort(key=lambda x: x[2], reverse=True)
    pit_scored.sort(key=lambda x: x[2], reverse=True)

    pos_ranked = assign_stars(pos_scored)
    pit_ranked = assign_stars(pit_scored)

    all_ranked = pos_ranked + pit_ranked
    all_ranked.sort(key=lambda x: x["composite"], reverse=True)

    ptype_counters = {}
    for idx, r in enumerate(all_ranked):
        r["rank_overall"] = idx + 1
        pt = r["ptype"] or "Unknown"
        ptype_counters[pt] = ptype_counters.get(pt, 0) + 1
        r["rank_by_ptype"] = ptype_counters[pt]

    # Clear old INTAM rankings for this year (only INTAM player IDs)
    intam_pids = [r["player_id"] for r in all_ranked]
    if intam_pids:
        conn.execute(
            text("""
                DELETE FROM recruiting_rankings
                WHERE league_year_id = :ly AND player_id IN :pids
            """),
            {"ly": league_year_id, "pids": tuple(intam_pids)},
        )

    # Batch INSERT rankings + batch UPDATE star ratings (executemany)
    if all_ranked:
        ranking_params = [{
            "pid": r["player_id"],
            "ly": league_year_id,
            "comp": round(r["composite"], 4),
            "star": r["star"],
            "rank": r["rank_overall"],
            "rpt": r["rank_by_ptype"],
        } for r in all_ranked]
        conn.execute(
            text("""
                INSERT INTO recruiting_rankings
                    (player_id, league_year_id, composite_score,
                     star_rating, rank_overall, rank_by_ptype)
                VALUES (:pid, :ly, :comp, :star, :rank, :rpt)
            """),
            ranking_params,
        )

        star_params = [{"star": r["star"], "pid": r["player_id"]} for r in all_ranked]
        conn.execute(
            text("UPDATE simbbPlayers SET recruit_stars = :star WHERE id = :pid"),
            star_params,
        )

    log.info("IFA star rankings: ranked %d INTAM players", len(all_ranked))
    return len(all_ranked)


# ---------------------------------------------------------------------------
# Bonus pool allocation
# ---------------------------------------------------------------------------

def _compute_inverse_standings(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """Return MLB orgs sorted worst-to-best (same logic as draft order)."""
    sql = text("""
        SELECT
            t.orgID AS org_id,
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
    return [dict(r) for r in rows]


def allocate_bonus_pools(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """
    Allocate IFA bonus pools based on inverse standings.
    Worst team gets base * spread, best team gets base / spread,
    linear interpolation between.

    Returns list of {org_id, total_pool, standing_rank}.
    """
    config = get_ifa_config(conn)
    base = _cfg_dec(config, "base_pool_amount", 5_000_000)
    spread = _cfg_float(config, "pool_spread_factor", 1.5)

    standings = _compute_inverse_standings(conn, league_year_id)
    n = len(standings)
    if n == 0:
        return []

    results = []
    for rank_idx, row in enumerate(standings):
        org_id = row["org_id"]
        # rank_idx 0 = worst team (biggest pool)
        t = rank_idx / max(n - 1, 1)
        pool = base * Decimal(str(spread * (1 - t) + (1.0 / spread) * t))
        pool = pool.quantize(Decimal("0.01"))
        standing_rank = rank_idx + 1

        conn.execute(text("""
            INSERT INTO ifa_bonus_pools (league_year_id, org_id, total_pool, spent, standing_rank)
            VALUES (:ly, :org, :pool, 0, :rank)
            ON DUPLICATE KEY UPDATE total_pool = :pool, standing_rank = :rank
        """), {"ly": league_year_id, "org": org_id, "pool": pool, "rank": standing_rank})

        results.append({"org_id": org_id, "total_pool": float(pool), "standing_rank": standing_rank})

    log.info("IFA bonus pools allocated for %d orgs (year %d)", n, league_year_id)
    return results


# ---------------------------------------------------------------------------
# Pool status
# ---------------------------------------------------------------------------

def get_ifa_pool_status(conn, league_year_id: int, org_id: int) -> Optional[Dict[str, Any]]:
    """Return pool breakdown: total, spent, committed (active offers), remaining."""
    pool_row = conn.execute(text("""
        SELECT total_pool, spent, standing_rank
        FROM ifa_bonus_pools
        WHERE league_year_id = :ly AND org_id = :org
    """), {"ly": league_year_id, "org": org_id}).first()

    if not pool_row:
        return None

    m = pool_row._mapping
    total = Decimal(str(m["total_pool"]))
    spent = Decimal(str(m["spent"]))

    # Sum of active (unsettled) offers
    committed = conn.execute(text("""
        SELECT COALESCE(SUM(o.bonus), 0)
        FROM ifa_auction_offers o
        JOIN ifa_auction a ON a.id = o.auction_id
        WHERE o.org_id = :org AND o.status = 'active'
          AND a.league_year_id = :ly
    """), {"org": org_id, "ly": league_year_id}).scalar()
    committed = Decimal(str(committed))

    return {
        "org_id": org_id,
        "total_pool": float(total),
        "spent": float(spent),
        "committed": float(committed),
        "remaining": float(total - spent - committed),
        "standing_rank": int(m["standing_rank"]),
    }


def get_all_ifa_pools(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """Return all bonus pools for a league year with committed amounts (admin view)."""
    rows = conn.execute(text("""
        SELECT bp.org_id, bp.total_pool, bp.spent, bp.standing_rank,
               org.team_abbrev
        FROM ifa_bonus_pools bp
        JOIN organizations org ON org.id = bp.org_id
        WHERE bp.league_year_id = :ly
        ORDER BY bp.standing_rank ASC
    """), {"ly": league_year_id}).all()

    result = []
    for r in rows:
        m = r._mapping
        total = Decimal(str(m["total_pool"]))
        spent = Decimal(str(m["spent"]))

        committed = conn.execute(text("""
            SELECT COALESCE(SUM(o.bonus), 0)
            FROM ifa_auction_offers o
            JOIN ifa_auction a ON a.id = o.auction_id
            WHERE o.org_id = :org AND o.status = 'active'
              AND a.league_year_id = :ly
        """), {"org": m["org_id"], "ly": league_year_id}).scalar()
        committed = Decimal(str(committed))

        result.append({
            "org_id": int(m["org_id"]),
            "team_abbrev": m["team_abbrev"],
            "total_pool": float(total),
            "spent": float(spent),
            "committed": float(committed),
            "remaining": float(total - spent - committed),
            "standing_rank": int(m["standing_rank"]),
        })
    return result


def get_ifa_auction_history(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """Return completed and expired auctions for a league year (admin view)."""
    rows = conn.execute(text("""
        SELECT ia.*, p.firstName, p.lastName, p.age, p.ptype,
               wo.org_id AS winner_org_id, wo.bonus AS winning_bonus,
               worg.team_abbrev AS winner_abbrev
        FROM ifa_auction ia
        JOIN simbbPlayers p ON p.id = ia.player_id
        LEFT JOIN ifa_auction_offers wo ON wo.id = ia.winning_offer_id
        LEFT JOIN organizations worg ON worg.id = wo.org_id
        WHERE ia.league_year_id = :ly AND ia.phase IN ('completed', 'expired')
        ORDER BY ia.updated_at DESC
    """), {"ly": league_year_id}).all()

    return [{
        "auction_id": int(r._mapping["id"]),
        "player_id": int(r._mapping["player_id"]),
        "firstName": r._mapping["firstName"],
        "lastName": r._mapping["lastName"],
        "age": int(r._mapping["age"]),
        "ptype": r._mapping["ptype"],
        "phase": r._mapping["phase"],
        "star_rating": int(r._mapping["star_rating"]),
        "slot_value": float(r._mapping["slot_value"]),
        "winner_abbrev": r._mapping["winner_abbrev"],
        "winning_bonus": float(r._mapping["winning_bonus"]) if r._mapping["winning_bonus"] else None,
    } for r in rows]


# ---------------------------------------------------------------------------
# Eligible players
# ---------------------------------------------------------------------------

def get_ifa_eligible_players(conn, league_year_id: int) -> List[Dict[str, Any]]:
    """
    INTAM players age >= min_age who don't have a completed/expired auction this year.
    """
    config = get_ifa_config(conn)
    min_age = _cfg_int(config, "min_age", 16)

    rows = conn.execute(text("""
        SELECT p.id, p.firstName, p.lastName, p.age, p.ptype,
               p.recruit_stars, p.area
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE cts.orgID = :intam AND p.age >= :min_age
          AND p.id NOT IN (
              SELECT ia.player_id FROM ifa_auction ia
              WHERE ia.league_year_id = :ly AND ia.phase IN ('completed', 'expired')
          )
        ORDER BY COALESCE(p.recruit_stars, 0) DESC, p.lastName
    """), {"intam": INTAM_ORG_ID, "min_age": min_age, "ly": league_year_id}).all()

    config_for_slots = config
    result = []
    for r in rows:
        m = r._mapping
        star = int(m["recruit_stars"]) if m["recruit_stars"] else 1
        result.append({
            "player_id": int(m["id"]),
            "firstName": m["firstName"],
            "lastName": m["lastName"],
            "age": int(m["age"]),
            "ptype": m["ptype"],
            "area": m["area"],
            "star_rating": star,
            "slot_value": float(_slot_value_for_star(config_for_slots, star)),
        })

    return result


# ---------------------------------------------------------------------------
# Auction lifecycle
# ---------------------------------------------------------------------------

def start_ifa_auction(
    conn, player_id: int, league_year_id: int, current_week: int,
    org_id: int = None,
) -> Dict[str, Any]:
    """Start a per-player IFA auction. Only MLB orgs (1-30) can trigger."""
    if org_id is not None and not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
        raise ValueError("Only MLB organizations (1-30) can start IFA auctions")

    # Validate IFA window is active
    state = _get_ifa_state(conn, league_year_id)
    if not state or state["status"] != "active":
        raise ValueError("IFA signing window is not active")

    # Check player is INTAM, age eligible
    config = get_ifa_config(conn)
    min_age = _cfg_int(config, "min_age", 16)

    player = conn.execute(text("""
        SELECT p.id, p.age, p.recruit_stars, p.firstName, p.lastName
        FROM simbbPlayers p
        JOIN contracts c ON c.playerID = p.id AND c.isFinished = 0
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE p.id = :pid AND cts.orgID = :intam
    """), {"pid": player_id, "intam": INTAM_ORG_ID}).first()

    if not player:
        raise ValueError("Player not found in INTAM pool")
    pm = player._mapping
    if int(pm["age"]) < min_age:
        raise ValueError(f"Player age {pm['age']} below IFA minimum {min_age}")

    # Check not already in active auction
    existing = conn.execute(text("""
        SELECT id, phase FROM ifa_auction
        WHERE player_id = :pid AND league_year_id = :ly
          AND phase NOT IN ('completed', 'expired', 'withdrawn')
    """), {"pid": player_id, "ly": league_year_id}).first()
    if existing:
        raise ValueError(f"Player already has active auction (id={existing._mapping['id']})")

    star = int(pm["recruit_stars"]) if pm["recruit_stars"] else 1
    slot = _slot_value_for_star(config, star)

    result = conn.execute(text("""
        INSERT INTO ifa_auction
            (player_id, league_year_id, phase, phase_started_week, entered_week,
             slot_value, star_rating, age_at_entry)
        VALUES (:pid, :ly, 'open', :week, :week, :slot, :star, :age)
    """), {
        "pid": player_id, "ly": league_year_id, "week": current_week,
        "slot": slot, "star": star, "age": int(pm["age"]),
    })
    auction_id = result.lastrowid

    log.info("IFA auction started: player %d (%s %s), star=%d, slot=%s",
             player_id, pm["firstName"], pm["lastName"], star, slot)

    return {
        "auction_id": auction_id,
        "player_id": player_id,
        "player_name": f"{pm['firstName']} {pm['lastName']}",
        "phase": "open",
        "star_rating": star,
        "slot_value": float(slot),
        "age": int(pm["age"]),
    }


def submit_ifa_offer(
    conn, auction_id: int, org_id: int, bonus: Decimal,
    league_year_id: int, current_week: int,
    executed_by: str = None,
) -> Dict[str, Any]:
    """Submit or update an IFA offer. Validates phase rules and pool budget."""
    if not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
        raise ValueError("Only MLB organizations (1-30) can submit IFA offers")

    bonus = Decimal(str(bonus))

    # Load auction
    auc = conn.execute(text("""
        SELECT * FROM ifa_auction WHERE id = :aid
    """), {"aid": auction_id}).first()
    if not auc:
        raise ValueError("Auction not found")
    a = auc._mapping

    if a["phase"] not in ("open", "listening", "finalize"):
        raise ValueError(f"Auction is in phase '{a['phase']}', cannot accept offers")

    # Bonus must meet slot value
    if bonus < Decimal(str(a["slot_value"])):
        raise ValueError(f"Bonus {bonus} below slot value {a['slot_value']}")

    # Check for existing offer by this org
    existing_offer = conn.execute(text("""
        SELECT id, bonus, status FROM ifa_auction_offers
        WHERE auction_id = :aid AND org_id = :org
    """), {"aid": auction_id, "org": org_id}).first()

    # Phase-specific rules
    if a["phase"] == "listening":
        if not existing_offer or existing_offer._mapping["status"] != "active":
            raise ValueError("Listening phase: only orgs with existing active offers can update")
        if bonus < Decimal(str(existing_offer._mapping["bonus"])):
            raise ValueError("Listening phase: cannot decrease bonus")

    elif a["phase"] == "finalize":
        if not existing_offer or existing_offer._mapping["status"] != "active":
            raise ValueError("Finalize phase: only top bidders with active offers can update")
        if bonus < Decimal(str(existing_offer._mapping["bonus"])):
            raise ValueError("Finalize phase: cannot decrease bonus")

    # Pool budget check
    pool_status = get_ifa_pool_status(conn, league_year_id, org_id)
    if not pool_status:
        raise ValueError(f"No IFA bonus pool found for org {org_id}")

    # If updating, free up old offer amount first
    available = Decimal(str(pool_status["remaining"]))
    if existing_offer and existing_offer._mapping["status"] == "active":
        available += Decimal(str(existing_offer._mapping["bonus"]))

    if bonus > available:
        raise ValueError(
            f"Bonus {bonus} exceeds available pool "
            f"({float(available):.2f} remaining)"
        )

    if existing_offer and existing_offer._mapping["status"] == "active":
        # Update existing offer
        old_bonus = float(existing_offer._mapping["bonus"])
        conn.execute(text("""
            UPDATE ifa_auction_offers
            SET bonus = :bonus, last_updated_week = :week
            WHERE id = :oid
        """), {"bonus": bonus, "week": current_week, "oid": existing_offer._mapping["id"]})

        _log_transaction(
            conn,
            transaction_type="ifa_offer_update",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            player_id=int(a["player_id"]),
            details={
                "auction_id": auction_id,
                "offer_id": int(existing_offer._mapping["id"]),
                "old_bonus": old_bonus,
                "new_bonus": float(bonus),
            },
            executed_by=executed_by,
        )

        return {
            "offer_id": int(existing_offer._mapping["id"]),
            "is_update": True,
            "bonus": float(bonus),
            "phase": a["phase"],
        }
    elif existing_offer and existing_offer._mapping["status"] == "withdrawn":
        # Reactivate a previously withdrawn offer with the new bonus
        conn.execute(text("""
            UPDATE ifa_auction_offers
            SET bonus = :bonus, status = 'active', last_updated_week = :week
            WHERE id = :oid
        """), {"bonus": bonus, "week": current_week, "oid": existing_offer._mapping["id"]})

        offer_id = int(existing_offer._mapping["id"])
        _log_transaction(
            conn,
            transaction_type="ifa_offer",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            player_id=int(a["player_id"]),
            details={
                "auction_id": auction_id,
                "offer_id": offer_id,
                "bonus": float(bonus),
                "reactivated": True,
            },
            executed_by=executed_by,
        )

        return {
            "offer_id": offer_id,
            "is_update": False,
            "bonus": float(bonus),
            "phase": a["phase"],
        }
    else:
        # New offer
        result = conn.execute(text("""
            INSERT INTO ifa_auction_offers
                (auction_id, org_id, bonus, submitted_week, last_updated_week, status)
            VALUES (:aid, :org, :bonus, :week, :week, 'active')
        """), {"aid": auction_id, "org": org_id, "bonus": bonus, "week": current_week})
        offer_id = result.lastrowid

        _log_transaction(
            conn,
            transaction_type="ifa_offer",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            player_id=int(a["player_id"]),
            details={
                "auction_id": auction_id,
                "offer_id": offer_id,
                "bonus": float(bonus),
            },
            executed_by=executed_by,
        )

        return {
            "offer_id": offer_id,
            "is_update": False,
            "bonus": float(bonus),
            "phase": a["phase"],
        }


def withdraw_ifa_offer(conn, auction_id: int, org_id: int) -> Dict[str, Any]:
    """Withdraw an offer. Only allowed in open phase."""
    auc = conn.execute(text(
        "SELECT phase FROM ifa_auction WHERE id = :aid"
    ), {"aid": auction_id}).first()
    if not auc:
        raise ValueError("Auction not found")
    if auc._mapping["phase"] != "open":
        raise ValueError("Offers can only be withdrawn during open phase")

    result = conn.execute(text("""
        UPDATE ifa_auction_offers
        SET status = 'withdrawn'
        WHERE auction_id = :aid AND org_id = :org AND status = 'active'
    """), {"aid": auction_id, "org": org_id})
    if result.rowcount == 0:
        raise ValueError("No active offer found to withdraw")

    return {"withdrawn": True}


# ---------------------------------------------------------------------------
# IFA state helpers
# ---------------------------------------------------------------------------

def _get_ifa_state(conn, league_year_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(text("""
        SELECT * FROM ifa_state WHERE league_year_id = :ly
    """), {"ly": league_year_id}).first()
    if not row:
        return None
    return dict(row._mapping)


def get_ifa_state(conn, league_year_id: int) -> Dict[str, Any]:
    """Public accessor for IFA window state."""
    state = _get_ifa_state(conn, league_year_id)
    if not state:
        config = get_ifa_config(conn)
        total_weeks = _cfg_int(config, "ifa_weeks", 20)
        return {"league_year_id": league_year_id, "current_week": 0,
                "total_weeks": total_weeks, "status": "pending"}
    return {
        "league_year_id": league_year_id,
        "current_week": int(state["current_week"]),
        "total_weeks": int(state["total_weeks"]),
        "status": state["status"],
    }


# ---------------------------------------------------------------------------
# Week advancement
# ---------------------------------------------------------------------------

def advance_ifa_week(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Advance the IFA signing window by one week.
    Called by admin endpoint, separate from game simulation.

    Week 0 → 1: initialize (compute rankings, allocate pools, set active)
    Weeks 1-19: advance auction phases
    Week 20: final advance + expire remaining auctions + set complete
    """
    config = get_ifa_config(conn)
    total_weeks = _cfg_int(config, "ifa_weeks", 20)

    state = _get_ifa_state(conn, league_year_id)
    if not state:
        conn.execute(text("""
            INSERT INTO ifa_state (league_year_id, current_week, total_weeks, status)
            VALUES (:ly, 0, :tw, 'pending')
        """), {"ly": league_year_id, "tw": total_weeks})
        state = _get_ifa_state(conn, league_year_id)

    current_week = int(state["current_week"])
    status = state["status"]

    if status == "complete":
        raise ValueError("IFA signing window already complete")

    result = {"league_year_id": league_year_id, "previous_week": current_week}

    if current_week == 0:
        # Initialization
        min_age = _cfg_int(config, "min_age", 16)
        ranked = compute_ifa_star_rankings(conn, league_year_id, min_age)
        pools = allocate_bonus_pools(conn, league_year_id)

        conn.execute(text("""
            UPDATE ifa_state
            SET current_week = 1, status = 'active'
            WHERE league_year_id = :ly
        """), {"ly": league_year_id})

        result.update({
            "new_week": 1,
            "status": "active",
            "players_ranked": ranked,
            "pools_allocated": len(pools),
        })

    elif current_week < total_weeks:
        new_week = current_week + 1
        # Advance auction phases
        phase_result = _advance_ifa_auction_phases(conn, new_week, league_year_id, config)

        new_status = "active"
        if new_week >= total_weeks:
            # Final week: expire remaining auctions
            expired = _expire_remaining_auctions(conn, league_year_id, current_week=new_week)
            new_status = "complete"
            phase_result["expired"] = expired

        conn.execute(text("""
            UPDATE ifa_state
            SET current_week = :week, status = :status
            WHERE league_year_id = :ly
        """), {"week": new_week, "status": new_status, "ly": league_year_id})

        result.update({
            "new_week": new_week,
            "status": new_status,
            "phase_transitions": phase_result,
        })

    else:
        raise ValueError(f"IFA week {current_week} already at or past total {total_weeks}")

    return result


def _advance_ifa_auction_phases(
    conn, current_week: int, league_year_id: int, config: dict,
) -> Dict[str, int]:
    """
    Process phase transitions for all active IFA auctions.
    Mirrors advance_auction_phases() from fa_auction.py but uses
    configurable phase_duration_weeks instead of 1 week per phase.
    """
    phase_duration = _cfg_int(config, "phase_duration_weeks", 3)

    summary = {
        "open_to_listening": 0,
        "listening_to_finalize": 0,
        "finalize_to_completed": 0,
        "still_open": 0,
    }

    active_auctions = conn.execute(text("""
        SELECT * FROM ifa_auction
        WHERE league_year_id = :ly AND phase IN ('open', 'listening', 'finalize')
    """), {"ly": league_year_id}).all()

    for row in active_auctions:
        a = row._mapping
        auction_id = int(a["id"])
        phase = a["phase"]
        started = int(a["phase_started_week"])

        # Phase must have lasted at least phase_duration weeks
        if current_week - started < phase_duration:
            if phase == "open":
                summary["still_open"] += 1
            continue

        if phase == "open":
            # Need at least 1 active offer to transition
            offer_count = conn.execute(text("""
                SELECT COUNT(*) FROM ifa_auction_offers
                WHERE auction_id = :aid AND status = 'active'
            """), {"aid": auction_id}).scalar()

            if offer_count == 0:
                summary["still_open"] += 1
                continue

            conn.execute(text("""
                UPDATE ifa_auction
                SET phase = 'listening', phase_started_week = :week
                WHERE id = :aid
            """), {"week": current_week, "aid": auction_id})
            summary["open_to_listening"] += 1
            log.info("IFA auction %d: open -> listening (week %d)", auction_id, current_week)

        elif phase == "listening":
            # Eliminate non-top-3 offers
            active_offers = conn.execute(text("""
                SELECT id, bonus FROM ifa_auction_offers
                WHERE auction_id = :aid AND status = 'active'
                ORDER BY bonus DESC
            """), {"aid": auction_id}).all()

            if len(active_offers) > 3:
                for r in active_offers[3:]:
                    conn.execute(text("""
                        UPDATE ifa_auction_offers SET status = 'outbid' WHERE id = :oid
                    """), {"oid": r._mapping["id"]})

            conn.execute(text("""
                UPDATE ifa_auction
                SET phase = 'finalize', phase_started_week = :week
                WHERE id = :aid
            """), {"week": current_week, "aid": auction_id})
            summary["listening_to_finalize"] += 1
            log.info("IFA auction %d: listening -> finalize (week %d)", auction_id, current_week)

        elif phase == "finalize":
            # Winner = highest bonus among active offers
            winner = conn.execute(text("""
                SELECT * FROM ifa_auction_offers
                WHERE auction_id = :aid AND status = 'active'
                ORDER BY bonus DESC, submitted_week ASC, id ASC
                LIMIT 1
            """), {"aid": auction_id}).first()

            if not winner:
                log.warning("IFA auction %d: finalize with no active offers", auction_id)
                conn.execute(text("""
                    UPDATE ifa_auction SET phase = 'withdrawn' WHERE id = :aid
                """), {"aid": auction_id})
                continue

            _execute_ifa_signing(
                conn, auction_id, int(winner._mapping["id"]),
                league_year_id, current_week,
            )
            summary["finalize_to_completed"] += 1
            log.info("IFA auction %d: finalize -> completed (week %d)", auction_id, current_week)

    return summary


def _expire_remaining_auctions(conn, league_year_id: int, current_week: int = 0) -> int:
    """
    At window close: force-complete finalize auctions that have active
    offers (highest bidder wins), then expire everything else.
    """
    # First: force-complete any finalize-phase auctions with active offers
    finalize_auctions = conn.execute(text("""
        SELECT id FROM ifa_auction
        WHERE league_year_id = :ly AND phase = 'finalize'
    """), {"ly": league_year_id}).all()

    for row in finalize_auctions:
        aid = int(row._mapping["id"])
        winner = conn.execute(text("""
            SELECT * FROM ifa_auction_offers
            WHERE auction_id = :aid AND status = 'active'
            ORDER BY bonus DESC, submitted_week ASC, id ASC
            LIMIT 1
        """), {"aid": aid}).first()
        if winner:
            _execute_ifa_signing(
                conn, aid, int(winner._mapping["id"]),
                league_year_id, current_week=current_week,
            )
            log.info("IFA window close: force-completed finalize auction %d", aid)

    # Then expire remaining non-completed auctions (open/listening only now)
    result = conn.execute(text("""
        UPDATE ifa_auction
        SET phase = 'expired'
        WHERE league_year_id = :ly AND phase IN ('open', 'listening', 'finalize')
    """), {"ly": league_year_id})
    expired = result.rowcount

    # Mark any active offers on expired auctions as lost
    conn.execute(text("""
        UPDATE ifa_auction_offers o
        JOIN ifa_auction a ON a.id = o.auction_id
        SET o.status = 'lost'
        WHERE a.league_year_id = :ly AND a.phase = 'expired' AND o.status = 'active'
    """), {"ly": league_year_id})

    if expired:
        log.info("IFA window close: expired %d auctions", expired)
    return expired


# ---------------------------------------------------------------------------
# Signing execution
# ---------------------------------------------------------------------------

def _execute_ifa_signing(
    conn, auction_id: int, winning_offer_id: int,
    league_year_id: int, current_week: int,
) -> Dict[str, Any]:
    """
    Execute the winning IFA offer as a contract signing.

    1. Terminate old INTAM contract
    2. Create new contract at IFA_TARGET_LEVEL
    3. Debit bonus pool
    4. Mark auction completed
    5. Log transaction
    """
    config = get_ifa_config(conn)
    years = _cfg_int(config, "ifa_contract_years", 5)
    salary_per_year = _cfg_dec(config, "ifa_salary_per_year", 40000)
    target_level = _cfg_int(config, "ifa_target_level", IFA_TARGET_LEVEL)

    # Load auction + offer
    auc_row = conn.execute(text(
        "SELECT * FROM ifa_auction WHERE id = :aid"
    ), {"aid": auction_id}).first()
    a = auc_row._mapping

    offer_row = conn.execute(text(
        "SELECT * FROM ifa_auction_offers WHERE id = :oid"
    ), {"oid": winning_offer_id}).first()
    o = offer_row._mapping

    player_id = int(a["player_id"])
    org_id = int(o["org_id"])
    bonus = Decimal(str(o["bonus"]))

    # Get league_year value for contract
    ly_val = conn.execute(text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).scalar()

    # 1. Terminate old INTAM contract
    conn.execute(text("""
        UPDATE contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        SET c.isFinished = 1
        WHERE c.playerID = :pid AND cts.orgID = :intam AND c.isFinished = 0
    """), {"pid": player_id, "intam": INTAM_ORG_ID})

    # 2. Create new contract
    t = _t(conn)
    contract_result = conn.execute(
        t["contracts"].insert().values(
            playerID=player_id,
            years=years,
            current_year=1,
            isExtension=0,
            isBuyout=0,
            bonus=bonus,
            signingOrg=org_id,
            leagueYearSigned=ly_val,
            isFinished=0,
            current_level=target_level,
            onIR=0,
        )
    )
    contract_id = contract_result.lastrowid

    for yr in range(1, years + 1):
        det_result = conn.execute(
            t["details"].insert().values(
                contractID=contract_id,
                year=yr,
                salary=salary_per_year,
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

    # 3. Debit bonus pool
    conn.execute(text("""
        UPDATE ifa_bonus_pools
        SET spent = spent + :bonus
        WHERE league_year_id = :ly AND org_id = :org
    """), {"bonus": bonus, "ly": league_year_id, "org": org_id})

    # 4. Mark auction completed, offers won/lost
    conn.execute(text("""
        UPDATE ifa_auction
        SET phase = 'completed', winning_offer_id = :woid
        WHERE id = :aid
    """), {"woid": winning_offer_id, "aid": auction_id})

    conn.execute(text("""
        UPDATE ifa_auction_offers
        SET status = 'won'
        WHERE id = :woid
    """), {"woid": winning_offer_id})

    conn.execute(text("""
        UPDATE ifa_auction_offers
        SET status = 'lost'
        WHERE auction_id = :aid AND id != :woid AND status = 'active'
    """), {"aid": auction_id, "woid": winning_offer_id})

    # 5. Log transaction
    tx_id = _log_transaction(
        conn,
        transaction_type="ifa_signing",
        league_year_id=league_year_id,
        primary_org_id=org_id,
        contract_id=contract_id,
        player_id=player_id,
        details={
            "auction_id": auction_id,
            "offer_id": winning_offer_id,
            "bonus": float(bonus),
            "star_rating": int(a["star_rating"]),
            "slot_value": float(a["slot_value"]),
            "contract_years": years,
            "target_level": target_level,
        },
        executed_by="ifa_signing",
    )

    log.info("IFA signing: player %d -> org %d, bonus=%s, contract=%d",
             player_id, org_id, bonus, contract_id)

    return {
        "transaction_id": tx_id,
        "contract_id": contract_id,
        "player_id": player_id,
        "org_id": org_id,
        "bonus": float(bonus),
    }


# ---------------------------------------------------------------------------
# Board / read endpoints
# ---------------------------------------------------------------------------

def get_ifa_board(
    conn, league_year_id: int, viewer_org_id: int = None,
) -> Dict[str, Any]:
    """
    Return full IFA board: state, viewer pool status, and all active/available
    auctions with anonymised competitor info.
    """
    state = get_ifa_state(conn, league_year_id)
    pool_status = None
    if viewer_org_id:
        pool_status = get_ifa_pool_status(conn, league_year_id, viewer_org_id)

    # Active auctions
    auctions_raw = conn.execute(text("""
        SELECT ia.*, p.firstName, p.lastName, p.age, p.ptype, p.area
        FROM ifa_auction ia
        JOIN simbbPlayers p ON p.id = ia.player_id
        WHERE ia.league_year_id = :ly
          AND ia.phase IN ('open', 'listening', 'finalize')
        ORDER BY ia.star_rating DESC, ia.slot_value DESC
    """), {"ly": league_year_id}).all()

    auctions = []
    for row in auctions_raw:
        m = row._mapping
        auction_id = int(m["id"])

        # Count active offers + get viewer's offer
        offers = conn.execute(text("""
            SELECT o.org_id, o.bonus, o.status, org.team_abbrev
            FROM ifa_auction_offers o
            JOIN organizations org ON org.id = o.org_id
            WHERE o.auction_id = :aid AND o.status = 'active'
            ORDER BY o.bonus DESC
        """), {"aid": auction_id}).all()

        active_count = len(offers)
        my_offer = None
        competitor_orgs = []

        for of in offers:
            om = of._mapping
            if viewer_org_id and int(om["org_id"]) == viewer_org_id:
                my_offer = {"bonus": float(om["bonus"])}
            else:
                if om["team_abbrev"]:
                    competitor_orgs.append(om["team_abbrev"])

        competitor_orgs.sort()

        auctions.append({
            "auction_id": auction_id,
            "player_id": int(m["player_id"]),
            "firstName": m["firstName"],
            "lastName": m["lastName"],
            "age": int(m["age"]),
            "ptype": m["ptype"],
            "area": m["area"],
            "phase": m["phase"],
            "star_rating": int(m["star_rating"]),
            "slot_value": float(m["slot_value"]),
            "entered_week": int(m["entered_week"]),
            "active_offers": active_count,
            "competitors": competitor_orgs,
            "my_offer": my_offer,
        })

    return {
        "state": state,
        "pool": pool_status,
        "auctions": auctions,
    }


def get_ifa_auction_detail(
    conn, auction_id: int, viewer_org_id: int = None,
) -> Optional[Dict[str, Any]]:
    """Single auction detail with offer info."""
    row = conn.execute(text("""
        SELECT ia.*, p.firstName, p.lastName, p.age, p.ptype, p.area
        FROM ifa_auction ia
        JOIN simbbPlayers p ON p.id = ia.player_id
        WHERE ia.id = :aid
    """), {"aid": auction_id}).first()

    if not row:
        return None

    m = row._mapping
    offers_raw = conn.execute(text("""
        SELECT o.*, org.team_abbrev
        FROM ifa_auction_offers o
        JOIN organizations org ON org.id = o.org_id
        WHERE o.auction_id = :aid
        ORDER BY o.submitted_week ASC, o.id ASC
    """), {"aid": auction_id}).all()

    offers = []
    for o in offers_raw:
        om = o._mapping
        offer_info = {
            "offer_id": int(om["id"]),
            "org_abbrev": om["team_abbrev"],
            "status": om["status"],
            "submitted_week": int(om["submitted_week"]),
        }
        # Only reveal bonus for viewer's own offer
        if viewer_org_id and int(om["org_id"]) == viewer_org_id:
            offer_info["bonus"] = float(om["bonus"])
            offer_info["is_mine"] = True
        else:
            offer_info["is_mine"] = False
        offers.append(offer_info)

    return {
        "auction_id": int(m["id"]),
        "player_id": int(m["player_id"]),
        "firstName": m["firstName"],
        "lastName": m["lastName"],
        "age": int(m["age"]),
        "ptype": m["ptype"],
        "area": m["area"],
        "phase": m["phase"],
        "star_rating": int(m["star_rating"]),
        "slot_value": float(m["slot_value"]),
        "entered_week": int(m["entered_week"]),
        "winning_offer_id": int(m["winning_offer_id"]) if m["winning_offer_id"] else None,
        "offers": offers,
    }


def get_org_ifa_offers(
    conn, league_year_id: int, org_id: int,
) -> List[Dict[str, Any]]:
    """Return all IFA offers by this org for the current league year."""
    rows = conn.execute(text("""
        SELECT o.*, ia.player_id, ia.phase AS auction_phase,
               ia.star_rating, ia.slot_value,
               p.firstName, p.lastName, p.age, p.ptype
        FROM ifa_auction_offers o
        JOIN ifa_auction ia ON ia.id = o.auction_id
        JOIN simbbPlayers p ON p.id = ia.player_id
        WHERE o.org_id = :org AND ia.league_year_id = :ly
        ORDER BY o.bonus DESC
    """), {"org": org_id, "ly": league_year_id}).all()

    return [{
        "offer_id": int(r._mapping["id"]),
        "auction_id": int(r._mapping["auction_id"]),
        "player_id": int(r._mapping["player_id"]),
        "firstName": r._mapping["firstName"],
        "lastName": r._mapping["lastName"],
        "age": int(r._mapping["age"]),
        "ptype": r._mapping["ptype"],
        "bonus": float(r._mapping["bonus"]),
        "status": r._mapping["status"],
        "auction_phase": r._mapping["auction_phase"],
        "star_rating": int(r._mapping["star_rating"]),
        "slot_value": float(r._mapping["slot_value"]),
    } for r in rows]
