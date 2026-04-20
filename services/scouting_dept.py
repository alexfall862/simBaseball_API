# services/scouting_dept.py
"""
Scouting department expansion purchases.

Pro orgs (1-30) can spend cash to increase their annual scouting point
budget beyond the base 2000.  Each successive tier yields diminishing
returns, modelling institutional friction in growing a scouting operation.

All functions take a SQLAlchemy Core connection (caller manages tx).
"""

import json
import logging
from decimal import Decimal

from sqlalchemy import MetaData, Table, and_, func, select, text

from services.org_constants import MLB_ORG_MIN, MLB_ORG_MAX

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier schedule
# ---------------------------------------------------------------------------
# (tier_number, cash_cost, bonus_points)
# Cumulative points: 2000 base + sum(bonus) through that tier.
TIERS = [
    (1,   3_000_000,  2000),
    (2,   3_000_000,  1500),
    (3,   3_000_000,  1500),
    (4,   3_000_000,  1000),
    (5,   3_000_000,  1000),
    (6,   5_000_000,  1000),
    (7,   5_000_000,  1000),
    (8,   5_000_000,  1000),
    (9,   7_000_000,  1000),
    (10,  7_000_000,  1000),
    (11, 10_000_000,  1000),
]

MAX_TIER = len(TIERS)
MAX_BONUS = sum(t[2] for t in TIERS)        # 13000
BASE_BUDGET = 2000
MAX_TOTAL = BASE_BUDGET + MAX_BONUS          # 15000

# Fast lookup by tier number
_TIER_MAP = {t[0]: {"cost": t[1], "points": t[2]} for t in TIERS}

# Cumulative schedule for status display
_CUMULATIVE = []
_running_pts = BASE_BUDGET
_running_cost = 0
for _t, _c, _p in TIERS:
    _running_pts += _p
    _running_cost += _c
    _CUMULATIVE.append({
        "tier": _t,
        "cost": _c,
        "points_gained": _p,
        "cumulative_total": _running_pts,
        "cumulative_cost": _running_cost,
        "cost_per_point": round(_c / _p),
    })


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

_table_cache = {}


def _get_tables(engine):
    eid = id(engine)
    if eid not in _table_cache:
        md = MetaData()
        _table_cache[eid] = {
            "purchases": Table("scouting_dept_purchases", md, autoload_with=engine),
            "budgets": Table("scouting_budgets", md, autoload_with=engine),
            "orgs": Table("organizations", md, autoload_with=engine),
            "ledger": Table("org_ledger_entries", md, autoload_with=engine),
            "tx_log": Table("transaction_log", md, autoload_with=engine),
            "ly": Table("league_years", md, autoload_with=engine),
        }
    return _table_cache[eid]


def _tables(conn):
    return _get_tables(conn.engine)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_current_tier(conn, org_id, league_year_id):
    """Return the highest active (non-rolled-back) tier purchased, or 0."""
    t = _tables(conn)
    row = conn.execute(
        select(func.coalesce(func.max(t["purchases"].c.tier), 0))
        .where(and_(
            t["purchases"].c.org_id == org_id,
            t["purchases"].c.league_year_id == league_year_id,
            t["purchases"].c.rolled_back == 0,
        ))
    ).scalar_one()
    return int(row)


def get_purchased_bonus(conn, org_id, league_year_id):
    """Total bonus points from active purchases for this org+year."""
    t = _tables(conn)
    return conn.execute(
        select(func.coalesce(func.sum(t["purchases"].c.bonus_points), 0))
        .where(and_(
            t["purchases"].c.org_id == org_id,
            t["purchases"].c.league_year_id == league_year_id,
            t["purchases"].c.rolled_back == 0,
        ))
    ).scalar_one()


def get_dept_status(conn, org_id, league_year_id):
    """
    Full status payload for the frontend.

    Returns dict with current tier, total budget, next tier info,
    purchase history, and the full tier schedule.
    """
    if not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
        return {
            "eligible": False,
            "reason": "Only MLB organizations can expand scouting departments",
            "base_budget": BASE_BUDGET,
            "total_budget": BASE_BUDGET,
        }

    current_tier = get_current_tier(conn, org_id, league_year_id)
    bonus = int(get_purchased_bonus(conn, org_id, league_year_id))

    # Purchase history
    t = _tables(conn)
    history_rows = conn.execute(
        select(
            t["purchases"].c.id,
            t["purchases"].c.tier,
            t["purchases"].c.bonus_points,
            t["purchases"].c.cash_cost,
            t["purchases"].c.rolled_back,
            t["purchases"].c.created_at,
        )
        .where(and_(
            t["purchases"].c.org_id == org_id,
            t["purchases"].c.league_year_id == league_year_id,
        ))
        .order_by(t["purchases"].c.tier)
    ).all()

    history = [
        {
            "id": r[0],
            "tier": r[1],
            "bonus_points": r[2],
            "cash_cost": float(r[3]),
            "rolled_back": bool(r[4]),
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in history_rows
    ]

    # Next tier info
    next_tier = None
    if current_tier < MAX_TIER:
        nt = _TIER_MAP[current_tier + 1]
        next_tier = {
            "tier": current_tier + 1,
            "cost": nt["cost"],
            "points_gained": nt["points"],
        }

    return {
        "eligible": True,
        "base_budget": BASE_BUDGET,
        "bonus_points": bonus,
        "total_budget": BASE_BUDGET + bonus,
        "current_tier": current_tier,
        "max_tier": MAX_TIER,
        "next_tier": next_tier,
        "purchases": history,
        "tier_schedule": _CUMULATIVE,
    }


# ---------------------------------------------------------------------------
# Cash helpers
# ---------------------------------------------------------------------------

def _get_available_cash(conn, org_id, league_year_id):
    """Net cash available (mirrors _get_signing_budget in transactions.py)."""
    t = _tables(conn)
    orgs = t["orgs"]
    ledger = t["ledger"]
    ly = t["ly"]

    cash = conn.execute(
        select(func.coalesce(orgs.c.cash, 0)).where(orgs.c.id == org_id)
    ).scalar_one()

    ly_row = conn.execute(
        select(ly.c.league_year).where(ly.c.id == league_year_id)
    ).first()
    league_year_val = ly_row._mapping["league_year"] if ly_row else 0

    ledger_balance = conn.execute(
        select(func.coalesce(func.sum(ledger.c.amount), 0))
        .select_from(ledger.join(ly, ledger.c.league_year_id == ly.c.id))
        .where(and_(
            ledger.c.org_id == org_id,
            ly.c.league_year <= league_year_val,
        ))
    ).scalar_one()

    return Decimal(str(cash)) + Decimal(str(ledger_balance))


# ---------------------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------------------

def purchase_next_tier(conn, org_id, league_year_id, executed_by=None):
    """
    Buy the next scouting department tier.

    Validates:
      - org is MLB (1-30)
      - not already at max tier
      - sufficient cash

    Performs:
      - inserts ledger entry (negative amount)
      - inserts transaction_log entry
      - inserts scouting_dept_purchases row
      - increases scouting_budgets.total_points

    Returns result dict for the endpoint.
    Raises ValueError on validation failures.
    """
    if not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
        raise ValueError("Only MLB organizations can expand scouting departments")

    current_tier = get_current_tier(conn, org_id, league_year_id)
    if current_tier >= MAX_TIER:
        raise ValueError(
            f"Already at maximum scouting department tier ({MAX_TIER})"
        )

    next_tier_num = current_tier + 1
    tier_info = _TIER_MAP[next_tier_num]
    cost = Decimal(str(tier_info["cost"]))
    bonus = tier_info["points"]

    # Cash check
    available = _get_available_cash(conn, org_id, league_year_id)
    if available < cost:
        raise ValueError(
            f"Insufficient funds: need ${cost:,.0f}, have ${available:,.0f}"
        )

    t = _tables(conn)

    # 1) Ledger entry (negative = money out)
    ledger_result = conn.execute(
        t["ledger"].insert().values(
            org_id=org_id,
            league_year_id=league_year_id,
            entry_type="scouting_purchase",
            amount=-cost,
            note=f"Scouting dept expansion tier {next_tier_num} (+{bonus} pts)",
        )
    )
    ledger_entry_id = ledger_result.lastrowid

    # 2) Transaction log
    details = {
        "tier": next_tier_num,
        "bonus_points": bonus,
        "cash_cost": float(cost),
        "ledger_entry_id": ledger_entry_id,
    }
    tx_result = conn.execute(
        t["tx_log"].insert().values(
            transaction_type="scouting_purchase",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            details=json.dumps(details),
            executed_by=executed_by,
            notes=f"Scouting dept tier {next_tier_num}",
        )
    )
    tx_log_id = tx_result.lastrowid

    # 3) Purchase record
    conn.execute(
        t["purchases"].insert().values(
            org_id=org_id,
            league_year_id=league_year_id,
            tier=next_tier_num,
            bonus_points=bonus,
            cash_cost=cost,
            ledger_entry_id=ledger_entry_id,
            transaction_log_id=tx_log_id,
        )
    )

    # 4) Increase scouting_budgets.total_points
    _sync_budget_total(conn, org_id, league_year_id)

    new_total = BASE_BUDGET + int(get_purchased_bonus(conn, org_id, league_year_id))

    return {
        "status": "purchased",
        "tier": next_tier_num,
        "bonus_points": bonus,
        "cash_cost": float(cost),
        "new_total_budget": new_total,
        "remaining_cash": float(_get_available_cash(conn, org_id, league_year_id)),
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_last_purchase(conn, org_id, league_year_id, executed_by=None):
    """
    Undo the most recent (highest tier) active purchase.

    Only allowed if the org hasn't spent points from that tier's bonus
    (i.e., spent_points <= total_points - bonus_of_last_tier).

    Performs:
      - deletes ledger entry
      - marks purchase as rolled_back
      - logs rollback in transaction_log
      - decreases scouting_budgets.total_points
    """
    if not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
        raise ValueError("Only MLB organizations have scouting dept purchases")

    t = _tables(conn)

    # Find the most recent active purchase
    last = conn.execute(
        select(t["purchases"])
        .where(and_(
            t["purchases"].c.org_id == org_id,
            t["purchases"].c.league_year_id == league_year_id,
            t["purchases"].c.rolled_back == 0,
        ))
        .order_by(t["purchases"].c.tier.desc())
        .limit(1)
    ).first()

    if not last:
        raise ValueError("No active scouting department purchases to roll back")

    purchase = dict(last._mapping)

    # Check that rolling back won't put spent > total
    budget_row = conn.execute(
        select(t["budgets"])
        .where(and_(
            t["budgets"].c.org_id == org_id,
            t["budgets"].c.league_year_id == league_year_id,
        ))
    ).first()

    if budget_row:
        b = dict(budget_row._mapping)
        new_total = b["total_points"] - purchase["bonus_points"]
        if b["spent_points"] > new_total:
            raise ValueError(
                f"Cannot roll back: {b['spent_points']} points already spent, "
                f"rollback would reduce budget to {new_total}"
            )

    # 1) Delete ledger entry
    if purchase["ledger_entry_id"]:
        conn.execute(
            t["ledger"].delete().where(
                t["ledger"].c.id == purchase["ledger_entry_id"]
            )
        )

    # 2) Mark purchase as rolled back
    conn.execute(
        t["purchases"].update()
        .where(t["purchases"].c.id == purchase["id"])
        .values(rolled_back=1)
    )

    # 3) Log rollback in transaction_log
    conn.execute(
        t["tx_log"].insert().values(
            transaction_type="scouting_purchase",
            league_year_id=league_year_id,
            primary_org_id=org_id,
            details=json.dumps({
                "rollback": True,
                "original_purchase_id": purchase["id"],
                "tier": purchase["tier"],
                "refunded_points": purchase["bonus_points"],
                "refunded_cash": float(purchase["cash_cost"]),
            }),
            executed_by=executed_by,
            notes=f"ROLLBACK of scouting dept tier {purchase['tier']}",
        )
    )

    # 4) Sync budget total
    _sync_budget_total(conn, org_id, league_year_id)

    new_total = BASE_BUDGET + int(get_purchased_bonus(conn, org_id, league_year_id))

    return {
        "status": "rolled_back",
        "tier_removed": purchase["tier"],
        "refunded_points": purchase["bonus_points"],
        "refunded_cash": float(purchase["cash_cost"]),
        "new_total_budget": new_total,
        "remaining_cash": float(_get_available_cash(conn, org_id, league_year_id)),
    }


# ---------------------------------------------------------------------------
# Budget sync
# ---------------------------------------------------------------------------

def _sync_budget_total(conn, org_id, league_year_id):
    """
    Ensure scouting_budgets.total_points = base + sum(active purchase bonuses).
    Creates the budget row if it doesn't exist yet.
    """
    from services.scouting_service import get_or_create_budget
    get_or_create_budget(conn, org_id, league_year_id)

    bonus = int(get_purchased_bonus(conn, org_id, league_year_id))
    new_total = BASE_BUDGET + bonus

    t = _tables(conn)
    conn.execute(
        t["budgets"].update()
        .where(and_(
            t["budgets"].c.org_id == org_id,
            t["budgets"].c.league_year_id == league_year_id,
        ))
        .values(total_points=new_total)
    )
