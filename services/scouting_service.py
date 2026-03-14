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
COLLEGE_ORG_MAX = 342
MLB_ORG_MIN = 1
MLB_ORG_MAX = 30

# All valid scouting action types
ALL_ACTION_TYPES = frozenset({
    "hs_report",
    "recruit_potential_fuzzed",
    "recruit_potential_precise",
    "college_potential_precise",
    "draft_attrs_fuzzed",
    "draft_attrs_precise",
    "draft_potential_precise",
    "pro_attrs_precise",
    "pro_potential_precise",
})

# Prerequisite chains: action_type -> required prior action
_PREREQUISITES = {
    "recruit_potential_fuzzed": "hs_report",
    "recruit_potential_precise": "recruit_potential_fuzzed",
    "draft_attrs_precise": "draft_attrs_fuzzed",
}

# Permission rules: action_type -> (allowed_org_range, target_pool_check)
# Encoded as functions in _validate_scouting_permission

# Cost config keys (map action_type -> scouting_config key with fallback)
_COST_CONFIG_KEYS = {
    "hs_report":                 ("hs_report_cost",                 10),
    "recruit_potential_fuzzed":   ("recruit_potential_fuzzed_cost",   15),
    "recruit_potential_precise":  ("recruit_potential_precise_cost",  25),
    "college_potential_precise":  ("college_potential_precise_cost",  15),
    "draft_attrs_fuzzed":        ("draft_attrs_fuzzed_cost",         10),
    "draft_attrs_precise":       ("draft_attrs_precise_cost",        20),
    "draft_potential_precise":   ("draft_potential_precise_cost",     15),
    "pro_attrs_precise":         ("pro_attrs_precise_cost",          15),
    "pro_potential_precise":     ("pro_potential_precise_cost",       15),
}

# 20-80 score -> letter grade mapping (kept for backward compat imports)
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
    if action_type not in ALL_ACTION_TYPES:
        raise ValueError(f"Unknown action_type: {action_type}")

    config = get_scouting_config(conn)

    # Resolve cost from config (with hardcoded fallback)
    config_key, fallback = _COST_CONFIG_KEYS[action_type]
    cost = int(config.get(config_key, fallback))

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

    # Check prerequisites
    prereq = _PREREQUISITES.get(action_type)
    if prereq:
        has_prereq = conn.execute(
            text("""
                SELECT id FROM scouting_actions
                WHERE org_id = :org_id AND player_id = :pid AND action_type = :atype
            """),
            {"org_id": org_id, "pid": player_id, "atype": prereq},
        ).first()
        if not has_prereq:
            raise ValueError(
                f"Must unlock '{prereq}' before '{action_type}'"
            )

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
    - hs_report / recruit_potential_*: college orgs (31-338) on HS players (org 340)
    - college_potential_precise: any org on college players (orgs 31-338)
    - draft_attrs_* / draft_potential_precise: MLB orgs (1-30) on college (31-338) or INTAM (339)
    - pro_attrs_precise / pro_potential_precise: any org on pro players (levels 4-9)
    """
    # Find the player's current holding org and level
    player_info = conn.execute(
        text("""
            SELECT cts.orgID, c.current_level
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.playerID = :pid AND c.isActive = 1
            LIMIT 1
        """),
        {"pid": player_id},
    ).first()

    if not player_info:
        raise ValueError(f"Player {player_id} not found or has no active contract")

    target_org_id = player_info[0]
    target_level = player_info[1]

    # HS recruiting actions: college orgs only, on HS players
    if action_type in ("hs_report", "recruit_potential_fuzzed", "recruit_potential_precise"):
        if not (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX):
            raise ValueError("Only college organizations can scout HS players")
        if target_org_id != USHS_ORG_ID:
            raise ValueError("HS scouting actions only apply to USHS players")

    # College potential: any org, on college players
    elif action_type == "college_potential_precise":
        if not (COLLEGE_ORG_MIN <= target_org_id <= COLLEGE_ORG_MAX):
            raise ValueError("College potential scouting only applies to college players")

    # Draft scouting: MLB orgs, on college/INTAM players
    elif action_type in ("draft_attrs_fuzzed", "draft_attrs_precise", "draft_potential_precise"):
        if not (MLB_ORG_MIN <= org_id <= MLB_ORG_MAX):
            raise ValueError("Only MLB organizations can draft-scout college/INTAM players")
        if not (COLLEGE_ORG_MIN <= target_org_id <= INTAM_ORG_ID):
            raise ValueError("Draft scouting only applies to college or INTAM players")

    # Pro roster scouting: any org, on pro-level players
    elif action_type in ("pro_attrs_precise", "pro_potential_precise"):
        if not (4 <= (target_level or 0) <= 9):
            raise ValueError("Pro scouting only applies to players at pro levels (4-9)")


# ---------------------------------------------------------------------------
# Visibility determination
# ---------------------------------------------------------------------------

def get_player_scouting_visibility(conn, org_id, player_id):
    """
    Determine what data the given org can see for a given player.

    Returns:
        {
            pool: 'hs' | 'college' | 'intam' | 'pro' | 'none',
            unlocked: [action_type, ...],
            available_actions: [action_type, ...],
        }
    """
    # Find player's current holding org and level
    player_info = conn.execute(
        text("""
            SELECT p.id, p.ptype, p.age, cts.orgID AS holding_org, c.current_level
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
        exists = conn.execute(
            text("SELECT id FROM simbbPlayers WHERE id = :pid"),
            {"pid": player_id},
        ).first()
        if not exists:
            return {"pool": "none", "unlocked": [], "available_actions": []}
        return {"pool": "pro", "unlocked": [], "available_actions": []}

    m = player_info._mapping
    holding_org = m["holding_org"]
    current_level = m["current_level"]

    # Determine pool
    if holding_org == USHS_ORG_ID:
        pool = "hs"
    elif COLLEGE_ORG_MIN <= holding_org <= COLLEGE_ORG_MAX:
        pool = "college"
    elif holding_org == INTAM_ORG_ID:
        pool = "intam"
    else:
        pool = "pro"

    # Get unlocked actions for this org + player
    actions = conn.execute(
        text("""
            SELECT action_type FROM scouting_actions
            WHERE org_id = :org_id AND player_id = :pid
        """),
        {"org_id": org_id, "pid": player_id},
    ).all()
    unlocked = [r[0] for r in actions]
    unlocked_set = set(unlocked)

    # Build available actions based on pool and org type
    available = []

    if pool == "hs" and COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX:
        # College recruiting pipeline
        if "hs_report" not in unlocked_set:
            available.append("hs_report")
        if "hs_report" in unlocked_set and "recruit_potential_fuzzed" not in unlocked_set:
            available.append("recruit_potential_fuzzed")
        if "recruit_potential_fuzzed" in unlocked_set and "recruit_potential_precise" not in unlocked_set:
            available.append("recruit_potential_precise")

    elif pool in ("college", "intam"):
        # College potential (any org)
        if "college_potential_precise" not in unlocked_set:
            available.append("college_potential_precise")

        # Draft scouting (MLB orgs only)
        if MLB_ORG_MIN <= org_id <= MLB_ORG_MAX:
            if "draft_attrs_fuzzed" not in unlocked_set:
                available.append("draft_attrs_fuzzed")
            if "draft_attrs_fuzzed" in unlocked_set and "draft_attrs_precise" not in unlocked_set:
                available.append("draft_attrs_precise")
            if "draft_potential_precise" not in unlocked_set:
                available.append("draft_potential_precise")

    elif pool == "pro":
        # Pro roster scouting (any org)
        if "pro_attrs_precise" not in unlocked_set:
            available.append("pro_attrs_precise")
        if "pro_potential_precise" not in unlocked_set:
            available.append("pro_potential_precise")

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
# Letter grade conversion (kept for backward compat, canonical version
# now lives in services/attribute_visibility.py)
# ---------------------------------------------------------------------------

def base_to_letter_grade(value, mean=30.0, std=12.0):
    """
    Convert a numeric _base value to a letter grade.

    Uses the 20-80 scouting scale (z-score -> scale) then maps to grade.
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
