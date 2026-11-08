# services/training_camp.py
"""
Training camp: one focus skill per player per season, chosen by the org that
holds his contract (pro orgs at any level, college programs).

Effect: for the end-season progression pass only, the focus skill's
potential grade is shifted on the ladder N … A+ before the growth-curve
lookup. Stored potentials never change.

Intensities (steps on the 14-step ladder, from ``league_config``):
  regular  +1 step, no risk
  intense  75 %: +2 steps / 25 %: -2 steps
  max      50 %: +4 steps / 50 %: -4 steps

The roll is deterministic per (player, league year) so a re-run of
end-season cannot change an outcome. Results go to ``training_camp_results``
for the admin diagnostics and the org's own view.
"""
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from player_engine.constants import ALL_ABILITIES, PITCH_SLOTS, PITCH_SUB_ABILITIES
from services.league_config import get_league_config, cfg_int, cfg_float

log = logging.getLogger("app")

GRADE_LADDER = ["N", "F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
_GRADE_INDEX = {g: i for i, g in enumerate(GRADE_LADDER)}

ABILITY_LABELS: Dict[str, str] = {
    "contact": "Contact", "power": "Power", "discipline": "Discipline", "eye": "Eye",
    "basereaction": "Base reaction", "baserunning": "Baserunning", "speed": "Speed",
    "fieldcatch": "Fielding: hands", "fieldreact": "Fielding: reaction",
    "fieldspot": "Fielding: positioning", "throwpower": "Arm strength",
    "throwacc": "Arm accuracy", "pthrowpower": "Velocity",
    "catchframe": "Framing", "catchsequence": "Game calling",
    "pendurance": "Endurance", "pgencontrol": "Control", "pickoff": "Pickoff",
    "psequencing": "Sequencing",
}
INTENSITIES = ("regular", "intense", "max")
MIN_CAMP_LEVEL = 3          # college and up; HS / INTAM pools have no camp


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------

def shift_grade(grade: Optional[str], steps: int) -> Optional[str]:
    """Move a grade ``steps`` places on the ladder, clamped at both ends."""
    if not grade or grade not in _GRADE_INDEX:
        return grade
    idx = _GRADE_INDEX[grade] + int(steps)
    idx = max(0, min(len(GRADE_LADDER) - 1, idx))
    return GRADE_LADDER[idx]


def intensity_rules(cfg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    return {
        "regular": {"up": cfg_int(cfg, "camp_regular_steps", 1), "down": 0,
                    "backfire": 0.0},
        "intense": {"up": cfg_int(cfg, "camp_intense_steps", 2),
                    "down": cfg_int(cfg, "camp_intense_steps", 2),
                    "backfire": cfg_float(cfg, "camp_intense_backfire", 0.25)},
        "max": {"up": cfg_int(cfg, "camp_max_steps", 4),
                "down": cfg_int(cfg, "camp_max_steps", 4),
                "backfire": cfg_float(cfg, "camp_max_backfire", 0.50)},
    }


def resolve_intensity(intensity: str, roll: float, rules: Dict[str, Dict[str, float]]) -> Tuple[int, bool]:
    """(steps, backfired) for a uniform ``roll`` in [0, 1)."""
    r = rules[intensity]
    if roll < float(r["backfire"]):
        return -int(r["down"]), True
    return int(r["up"]), False


def camp_roll(player_id: int, league_year_id: int) -> float:
    return random.Random(f"camp:{int(player_id)}:{int(league_year_id)}").random()


def focus_pot_columns(attr: str) -> List[str]:
    """Potential columns a focus skill shifts: one for an ability, four for a pitch."""
    if attr in ALL_ABILITIES:
        return [f"{attr}_pot"]
    if attr in PITCH_SLOTS:
        return [f"{attr}_{sub}_pot" for sub in PITCH_SUB_ABILITIES]
    raise ValueError(f"unknown focus skill '{attr}'")


def options(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rules = intensity_rules(cfg or {})
    return {
        "skills": [{"attr": a, "label": ABILITY_LABELS.get(a, a), "kind": "ability"} for a in ALL_ABILITIES]
                  + [{"attr": s, "label": f"Pitch {s[-1]} (all four components)", "kind": "pitch"} for s in PITCH_SLOTS],
        "intensities": [
            {"intensity": "regular", "steps_up": rules["regular"]["up"], "steps_down": 0,
             "backfire_pct": 0, "description": "Potential one step better for this offseason. No risk."},
            {"intensity": "intense", "steps_up": rules["intense"]["up"], "steps_down": rules["intense"]["down"],
             "backfire_pct": round(rules["intense"]["backfire"] * 100),
             "description": "Two steps better, or two steps worse on a backfire."},
            {"intensity": "max", "steps_up": rules["max"]["up"], "steps_down": rules["max"]["down"],
             "backfire_pct": round(rules["max"]["backfire"] * 100),
             "description": "Four steps better (a C trains like a B+), or four steps worse on a backfire."},
        ],
        "grade_ladder": GRADE_LADDER,
    }


# ---------------------------------------------------------------------------
# Org-facing CRUD
# ---------------------------------------------------------------------------

def current_league_year_id(conn) -> Optional[int]:
    row = conn.execute(text(
        "SELECT id FROM league_years WHERE league_year = "
        "(SELECT season FROM timestamp_state WHERE id = 1)"
    )).first()
    return int(row[0]) if row else None


def _roster(conn, org_id: int) -> Dict[int, Dict[str, Any]]:
    """Players whose active contract the org holds (level >= 3)."""
    rows = conn.execute(text("""
        SELECT p.id, p.firstName, p.lastName, p.age, p.ptype, c.current_level,
               p.pitch1_name, p.pitch2_name, p.pitch3_name, p.pitch4_name, p.pitch5_name
        FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        JOIN simbbPlayers p ON p.id = c.playerID
        WHERE c.isFinished = 0 AND cts.orgID = :org AND c.current_level >= :lvl
        ORDER BY c.current_level DESC, p.lastName, p.firstName
    """), {"org": int(org_id), "lvl": MIN_CAMP_LEVEL}).mappings().all()
    return {int(r["id"]): dict(r) for r in rows}


def list_focus(conn, org_id: int, league_year_id: int) -> Dict[str, Any]:
    roster = _roster(conn, org_id)
    focus = {int(r["player_id"]): dict(r) for r in conn.execute(text("""
        SELECT player_id, attr, intensity, set_by, updated_at
        FROM training_camp_focus WHERE org_id = :org AND league_year_id = :ly
    """), {"org": int(org_id), "ly": int(league_year_id)}).mappings().all()}
    resolved = {int(r[0]) for r in conn.execute(text(
        "SELECT player_id FROM training_camp_results WHERE league_year_id = :ly"
    ), {"ly": int(league_year_id)}).all()}
    players = []
    for pid, r in roster.items():
        f = focus.get(pid)
        players.append({
            "player_id": pid, "name": f"{r['firstName']} {r['lastName']}",
            "age": r["age"], "ptype": r["ptype"], "level": int(r["current_level"]),
            "pitches": [r[f"pitch{i}_name"] for i in range(1, 6)],
            "focus_attr": f["attr"] if f else None,
            "focus_label": _label(f["attr"]) if f else None,
            "intensity": f["intensity"] if f else None,
            "locked": pid in resolved,
        })
    return {"org_id": int(org_id), "league_year_id": int(league_year_id),
            "players": players, "with_focus": len(focus)}


def _label(attr: str) -> str:
    if attr in ABILITY_LABELS:
        return ABILITY_LABELS[attr]
    if attr in PITCH_SLOTS:
        return f"Pitch {attr[-1]}"
    return attr


def set_focus(conn, org_id: int, league_year_id: int, player_id: int, attr: str,
              intensity: str, set_by: Optional[str] = None) -> Dict[str, Any]:
    if intensity not in INTENSITIES:
        raise ValueError(f"intensity must be one of {', '.join(INTENSITIES)}")
    focus_pot_columns(attr)                      # validates the skill
    if conn.execute(text(
        "SELECT 1 FROM training_camp_results WHERE player_id = :pid AND league_year_id = :ly"
    ), {"pid": int(player_id), "ly": int(league_year_id)}).first():
        raise ValueError("this season's camp has already been applied for the player")
    roster = _roster(conn, org_id)
    r = roster.get(int(player_id))
    if not r:
        raise ValueError("player is not on a roster this org controls (college or pro level)")
    if attr in PITCH_SLOTS and not r.get(f"{attr}_name"):
        raise ValueError(f"player has no {attr}")
    conn.execute(text("""
        INSERT INTO training_camp_focus (player_id, org_id, league_year_id, attr, intensity, set_by)
        VALUES (:pid, :org, :ly, :attr, :int, :by)
        ON DUPLICATE KEY UPDATE org_id = VALUES(org_id), attr = VALUES(attr),
                                intensity = VALUES(intensity), set_by = VALUES(set_by)
    """), {"pid": int(player_id), "org": int(org_id), "ly": int(league_year_id),
           "attr": attr, "int": intensity, "by": set_by})
    return {"player_id": int(player_id), "attr": attr, "label": _label(attr),
            "intensity": intensity, "league_year_id": int(league_year_id)}


def clear_focus(conn, org_id: int, league_year_id: int, player_id: int) -> bool:
    if conn.execute(text(
        "SELECT 1 FROM training_camp_results WHERE player_id = :pid AND league_year_id = :ly"
    ), {"pid": int(player_id), "ly": int(league_year_id)}).first():
        raise ValueError("this season's camp has already been applied for the player")
    n = conn.execute(text("""
        DELETE FROM training_camp_focus
        WHERE player_id = :pid AND org_id = :org AND league_year_id = :ly
    """), {"pid": int(player_id), "org": int(org_id), "ly": int(league_year_id)}).rowcount
    return n > 0


def org_results(conn, org_id: int, league_year_id: int) -> List[Dict[str, Any]]:
    """Fog-safe view for the org: what was trained and whether it backfired.
    Grades are not returned (potentials are scouted information)."""
    rows = conn.execute(text("""
        SELECT r.player_id, p.firstName, p.lastName, r.attr, r.intensity, r.steps, r.backfired
        FROM training_camp_results r JOIN simbbPlayers p ON p.id = r.player_id
        WHERE r.org_id = :org AND r.league_year_id = :ly
        ORDER BY p.lastName, p.firstName
    """), {"org": int(org_id), "ly": int(league_year_id)}).mappings().all()
    return [{"player_id": int(r["player_id"]), "name": f"{r['firstName']} {r['lastName']}",
             "attr": r["attr"], "label": _label(r["attr"]), "intensity": r["intensity"],
             "steps": int(r["steps"]), "backfired": bool(r["backfired"])} for r in rows]


# ---------------------------------------------------------------------------
# End-season hook
# ---------------------------------------------------------------------------

def prepare_camp(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Resolve every focus for the season: roll intensity, compute effective
    grades, record results. Returns {"overrides": {player_id: {pot_col:
    grade}}, "players", "backfired", "by_intensity"}. Idempotent: players
    with a result row already are re-used, not re-rolled.
    """
    cfg = get_league_config(conn)
    rules = intensity_rules(cfg)
    try:
        focus_rows = conn.execute(text("""
            SELECT f.player_id, f.org_id, f.attr, f.intensity
            FROM training_camp_focus f
            WHERE f.league_year_id = :ly
        """), {"ly": int(league_year_id)}).mappings().all()
    except Exception as e:  # table missing on an unmigrated DB
        log.warning("training camp skipped: %s", e)
        return {"overrides": {}, "players": 0, "backfired": 0, "by_intensity": {}, "skipped": str(e)}
    if not focus_rows:
        return {"overrides": {}, "players": 0, "backfired": 0, "by_intensity": {}}

    existing = {int(r["player_id"]): dict(r) for r in conn.execute(text("""
        SELECT player_id, steps, backfired, pot_columns, effective_grade
        FROM training_camp_results WHERE league_year_id = :ly
    """), {"ly": int(league_year_id)}).mappings().all()}

    pids = [int(r["player_id"]) for r in focus_rows]
    pot_cols_needed = sorted({c for r in focus_rows for c in focus_pot_columns(r["attr"])})
    grades: Dict[int, Dict[str, Optional[str]]] = {}
    for i in range(0, len(pids), 1000):
        chunk = pids[i:i + 1000]
        for row in conn.execute(text(
            f"SELECT id, {', '.join(pot_cols_needed)} FROM simbbPlayers WHERE id IN ({','.join(str(p) for p in chunk)})"
        )).mappings().all():
            grades[int(row["id"])] = {c: row[c] for c in pot_cols_needed}

    overrides: Dict[int, Dict[str, str]] = {}
    by_int: Dict[str, Dict[str, int]] = {}
    backfired_total = 0
    for r in focus_rows:
        pid = int(r["player_id"])
        cols = focus_pot_columns(r["attr"])
        g = grades.get(pid, {})
        prior = existing.get(pid)
        if prior:
            steps, backfired = int(prior["steps"]), bool(prior["backfired"])
        else:
            roll = camp_roll(pid, league_year_id)
            steps, backfired = resolve_intensity(r["intensity"], roll, rules)
        eff: Dict[str, str] = {}
        for c in cols:
            base = g.get(c)
            if base:
                eff[c] = shift_grade(base, steps)
        if eff:
            overrides[pid] = eff
        stat = by_int.setdefault(r["intensity"], {"players": 0, "backfired": 0})
        stat["players"] += 1
        if backfired:
            stat["backfired"] += 1
            backfired_total += 1
        if not prior:
            first = cols[0]
            conn.execute(text("""
                INSERT IGNORE INTO training_camp_results
                    (player_id, org_id, league_year_id, attr, intensity, base_grade,
                     effective_grade, steps, backfired, roll, pot_columns)
                VALUES (:pid, :org, :ly, :attr, :int, :bg, :eg, :steps, :bf, :roll, :cols)
            """), {"pid": pid, "org": int(r["org_id"]), "ly": int(league_year_id),
                   "attr": r["attr"], "int": r["intensity"], "bg": g.get(first),
                   "eg": eff.get(first), "steps": steps, "bf": 1 if backfired else 0,
                   "roll": round(roll, 4), "cols": json.dumps(cols)})
    log.info("training camp: %d players, %d backfired", len(focus_rows), backfired_total)
    return {"overrides": overrides, "players": len(focus_rows),
            "backfired": backfired_total, "by_intensity": by_int}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def admin_summary(conn, league_year_id: int) -> Dict[str, Any]:
    by_int = [dict(r) for r in conn.execute(text("""
        SELECT intensity, COUNT(*) AS players, SUM(backfired) AS backfired,
               ROUND(AVG(steps), 2) AS mean_steps
        FROM training_camp_results WHERE league_year_id = :ly GROUP BY intensity
    """), {"ly": int(league_year_id)}).mappings().all()]
    by_attr = [dict(r) for r in conn.execute(text("""
        SELECT attr, COUNT(*) AS players, SUM(backfired) AS backfired
        FROM training_camp_results WHERE league_year_id = :ly GROUP BY attr ORDER BY players DESC
    """), {"ly": int(league_year_id)}).mappings().all()]
    pending = conn.execute(text("""
        SELECT COUNT(*) FROM training_camp_focus f
        WHERE f.league_year_id = :ly
          AND NOT EXISTS (SELECT 1 FROM training_camp_results r
                          WHERE r.player_id = f.player_id AND r.league_year_id = f.league_year_id)
    """), {"ly": int(league_year_id)}).scalar() or 0
    for row in by_int + by_attr:
        for k, v in list(row.items()):
            if hasattr(v, "quantize") or isinstance(v, float):
                row[k] = float(v)
            elif v is not None and not isinstance(v, (int, str)):
                row[k] = int(v)
        if "attr" in row:
            row["label"] = _label(row["attr"])
    return {"league_year_id": int(league_year_id), "by_intensity": by_int,
            "by_attr": by_attr, "pending_focus": int(pending)}
