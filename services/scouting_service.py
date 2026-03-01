"""
Scouting system business logic.

Manages scouting budgets, action tracking, visibility determination,
and permission validation. All functions take a SQLAlchemy Core connection.
"""

from sqlalchemy import text

# Org ID boundaries
INTAM_ORG_ID = 339
USHS_ORG_ID = 340
COLLEGE_ORG_MIN = 31
COLLEGE_ORG_MAX = 338
MLB_ORG_MIN = 1
MLB_ORG_MAX = 30

# 20-80 score -> letter grade mapping
_GRADE_THRESHOLDS = [
    (80, "A+"), (75, "A"), (70, "A-"),
    (65, "B+"), (60, "B"), (55, "B-"),
    (50, "C+"), (45, "C"), (40, "C-"),
    (35, "D+"), (30, "D"), (25, "D-"),
    (20, "F"),
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_scouting_config(conn):
    """Read scouting_config into a {key: value} dict."""
    rows = conn.execute(
        text("SELECT config_key, config_value FROM scouting_config")
    ).all()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

def get_or_create_budget(conn, org_id, league_year_id):
    """
    Ensure a scouting_budgets row exists for (org_id, league_year_id).
    Auto-creates with the default budget from scouting_config if missing.
    Returns dict with total_points, spent_points.
    """
    row = conn.execute(
        text("""
            SELECT id, org_id, league_year_id, total_points, spent_points
            FROM scouting_budgets
            WHERE org_id = :org_id AND league_year_id = :ly_id
        """),
        {"org_id": org_id, "ly_id": league_year_id},
    ).first()

    if row:
        return dict(row._mapping)

    config = get_scouting_config(conn)

    # MLB orgs get larger budget than college
    if MLB_ORG_MIN <= org_id <= MLB_ORG_MAX:
        total = int(config.get("mlb_budget_per_year", 1000))
    else:
        total = int(config.get("college_budget_per_year", 500))

    conn.execute(
        text("""
            INSERT INTO scouting_budgets (org_id, league_year_id, total_points, spent_points)
            VALUES (:org_id, :ly_id, :total, 0)
        """),
        {"org_id": org_id, "ly_id": league_year_id, "total": total},
    )

    return {
        "org_id": org_id,
        "league_year_id": league_year_id,
        "total_points": total,
        "spent_points": 0,
    }


# ---------------------------------------------------------------------------
# Scouting actions
# ---------------------------------------------------------------------------

def perform_scouting_action(conn, org_id, league_year_id, player_id, action_type):
    """
    Execute a scouting action: validate -> check budget -> deduct -> record.

    Returns result dict with status and remaining budget.
    Raises ValueError on validation failures.
    """
    config = get_scouting_config(conn)

    cost_map = {
        "hs_report": int(config.get("hs_report_cost", 10)),
        "hs_potential": int(config.get("hs_potential_cost", 25)),
        "pro_numeric": int(config.get("pro_numeric_cost", 15)),
    }
    cost = cost_map.get(action_type)
    if cost is None:
        raise ValueError(f"Unknown action_type: {action_type}")

    # Idempotent: already unlocked -> return without charging
    existing = conn.execute(
        text("""
            SELECT id FROM scouting_actions
            WHERE org_id = :org_id AND player_id = :pid AND action_type = :atype
        """),
        {"org_id": org_id, "pid": player_id, "atype": action_type},
    ).first()

    if existing:
        budget = get_or_create_budget(conn, org_id, league_year_id)
        return {
            "status": "already_unlocked",
            "action_type": action_type,
            "player_id": player_id,
            "points_spent": 0,
            "points_remaining": budget["total_points"] - budget["spent_points"],
        }

    # Prerequisite: hs_potential requires hs_report first
    if action_type == "hs_potential":
        has_report = conn.execute(
            text("""
                SELECT id FROM scouting_actions
                WHERE org_id = :org_id AND player_id = :pid AND action_type = 'hs_report'
            """),
            {"org_id": org_id, "pid": player_id},
        ).first()
        if not has_report:
            raise ValueError("Must unlock scouting report before viewing potentials")

    # Permission check
    _validate_scouting_permission(conn, org_id, player_id, action_type)

    # Budget check
    budget = get_or_create_budget(conn, org_id, league_year_id)
    remaining = budget["total_points"] - budget["spent_points"]
    if remaining < cost:
        raise ValueError(
            f"Insufficient scouting points: need {cost}, have {remaining}"
        )

    # Deduct points
    conn.execute(
        text("""
            UPDATE scouting_budgets
            SET spent_points = spent_points + :cost
            WHERE org_id = :org_id AND league_year_id = :ly_id
        """),
        {"cost": cost, "org_id": org_id, "ly_id": league_year_id},
    )

    # Record action
    conn.execute(
        text("""
            INSERT INTO scouting_actions
                (org_id, league_year_id, player_id, action_type, points_spent)
            VALUES (:org_id, :ly_id, :pid, :atype, :cost)
        """),
        {
            "org_id": org_id,
            "ly_id": league_year_id,
            "pid": player_id,
            "atype": action_type,
            "cost": cost,
        },
    )

    return {
        "status": "unlocked",
        "action_type": action_type,
        "player_id": player_id,
        "points_spent": cost,
        "points_remaining": remaining - cost,
    }


def _validate_scouting_permission(conn, org_id, player_id, action_type):
    """
    Validate that the org is allowed to perform this action on this player.

    Rules:
    - hs_report / hs_potential: college orgs (31-338) on USHS players (org 340)
    - pro_numeric: MLB orgs (1-30) on college (31-338) or INTAM (339) players
    """
    # Find the player's current holding org
    player_org = conn.execute(
        text("""
            SELECT cts.orgID
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.playerID = :pid AND c.isActive = 1
            LIMIT 1
        """),
        {"pid": player_id},
    ).first()

    if not player_org:
        raise ValueError(f"Player {player_id} not found or has no active contract")

    target_org_id = player_org[0]

    if action_type in ("hs_report", "hs_potential"):
        if org_id < COLLEGE_ORG_MIN or org_id > COLLEGE_ORG_MAX:
            raise ValueError("Only college organizations can scout HS players")
        if target_org_id != USHS_ORG_ID:
            raise ValueError("HS scouting actions only apply to USHS players")

    elif action_type == "pro_numeric":
        if org_id < MLB_ORG_MIN or org_id > MLB_ORG_MAX:
            raise ValueError("Only MLB organizations can scout college/INTAM players")
        if target_org_id < COLLEGE_ORG_MIN or target_org_id > INTAM_ORG_ID:
            raise ValueError("Pro scouting only applies to college or INTAM players")


# ---------------------------------------------------------------------------
# Visibility determination
# ---------------------------------------------------------------------------

def get_player_scouting_visibility(conn, org_id, player_id):
    """
    Determine what data the given org can see for a given player.

    Returns:
        {
            pool: 'hs' | 'college' | 'intam' | 'mlb_fa' | 'none',
            unlocked: [action_type, ...],
            available_actions: [action_type, ...],
        }
    """
    # Find player's current holding org
    player_info = conn.execute(
        text("""
            SELECT p.id, p.ptype, p.age, cts.orgID AS holding_org
            FROM simbbPlayers p
            JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE p.id = :pid
            LIMIT 1
        """),
        {"pid": player_id},
    ).first()

    if not player_info:
        # No active contract — could be MLB free agent or unknown
        exists = conn.execute(
            text("SELECT id FROM simbbPlayers WHERE id = :pid"),
            {"pid": player_id},
        ).first()
        if not exists:
            return {"pool": "none", "unlocked": [], "available_actions": []}
        return {"pool": "mlb_fa", "unlocked": [], "available_actions": []}

    m = player_info._mapping
    holding_org = m["holding_org"]

    # Determine pool
    if holding_org == USHS_ORG_ID:
        pool = "hs"
    elif COLLEGE_ORG_MIN <= holding_org <= COLLEGE_ORG_MAX:
        pool = "college"
    elif holding_org == INTAM_ORG_ID:
        pool = "intam"
    else:
        pool = "mlb_fa"

    # Get unlocked actions for this org + player
    actions = conn.execute(
        text("""
            SELECT action_type FROM scouting_actions
            WHERE org_id = :org_id AND player_id = :pid
        """),
        {"org_id": org_id, "pid": player_id},
    ).all()
    unlocked = [r[0] for r in actions]

    # Build available actions
    available = []
    if pool == "hs" and COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX:
        if "hs_report" not in unlocked:
            available.append("hs_report")
        if "hs_report" in unlocked and "hs_potential" not in unlocked:
            available.append("hs_potential")
    elif pool in ("college", "intam") and MLB_ORG_MIN <= org_id <= MLB_ORG_MAX:
        if "pro_numeric" not in unlocked:
            available.append("pro_numeric")

    return {
        "pool": pool,
        "unlocked": unlocked,
        "available_actions": available,
    }


def get_org_scouting_actions(conn, org_id, league_year_id):
    """List all scouting actions by an org in a given league year."""
    rows = conn.execute(
        text("""
            SELECT sa.id, sa.player_id, sa.action_type, sa.points_spent, sa.created_at,
                   p.firstname, p.lastname, p.ptype, p.age
            FROM scouting_actions sa
            JOIN simbbPlayers p ON p.id = sa.player_id
            WHERE sa.org_id = :org_id AND sa.league_year_id = :ly_id
            ORDER BY sa.created_at DESC
        """),
        {"org_id": org_id, "ly_id": league_year_id},
    ).all()

    return [
        {
            "id": r[0],
            "player_id": r[1],
            "action_type": r[2],
            "points_spent": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "player_name": f"{r[5]} {r[6]}",
            "ptype": r[7],
            "age": r[8],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Letter grade conversion (for college/INTAM free tier)
# ---------------------------------------------------------------------------

def base_to_letter_grade(value, mean=30.0, std=12.0):
    """
    Convert a numeric _base value to a letter grade.

    Uses the 20-80 scouting scale (z-score → scale) then maps to grade.
    Default mean/std are approximate values for amateur-level attributes.
    """
    try:
        x = float(value or 0)
    except (TypeError, ValueError):
        return "F"

    if std <= 0:
        z = 0.0
    else:
        z = (x - mean) / std

    z = max(-3.0, min(3.0, z))
    score = 50.0 + (z / 3.0) * 30.0
    score = int(round(max(20.0, min(80.0, score)) / 5.0) * 5)
    score = max(20, min(80, score))

    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"
