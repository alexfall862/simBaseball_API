# services/training_camp.py
"""
Training camp: one focus skill per player per season, chosen by the org that
holds his contract (pro orgs at any level, college programs).

Timing: camp runs in the preseason, after free agency, trades and the draft
and before opening day (``apply_camp``, one admin step per season). Focus is
keyed by the league year about to be played and can be set from the moment
end-season moves the calendar to that year until camp is applied.

Effect: camp replays the focus skill's progression die from the end-season
that just ran, at the potential grade shifted on the ladder N … A+, and adds
the difference to the rating. Every attribute's end-season die is seeded
(``player_progression.attr_uniform``), so the result is exactly what that
progression would have produced at the shifted grade: same luck, different
grade. The offseason market therefore works on fresh post-progression ratings
and the camp adjustment is small. Stored potentials never change.

Intensities (steps on the 14-step ladder, from ``league_config``):
  regular  +1 step, no risk
  intense  75 %: +2 steps / 25 %: -2 steps
  max      50 %: +4 steps / 50 %: -4 steps

A focus only applies if the org that set it still holds the player's
contract (level >= 3) when camp runs. The intensity roll is deterministic
per (player, league year). Results go to ``training_camp_results``; the run
itself to ``training_camp_runs``, which also locks the season's focus.
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
LOCKED_MSG = "training camp for this season has already been applied"


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


def replay_delta(prog_league_year_id: int, player_id: int, base_col: str, new_age: int,
                 natural_grade: Optional[str], effective_grade: Optional[str],
                 cache) -> Optional[float]:
    """
    Camp adjustment for one column: the end-season die for (year, player,
    column) evaluated at the effective grade minus the same die at the
    natural grade. None when the column was not progressed (no grade, or
    the age is outside the growth table).
    """
    from player_engine.player_progression import attr_uniform, sample_delta
    if not natural_grade or not effective_grade:
        return None
    p_nat = cache.get((natural_grade, int(new_age)))
    p_eff = cache.get((effective_grade, int(new_age)))
    if not p_nat or not p_eff:
        return None
    u = attr_uniform(prog_league_year_id, player_id, base_col)
    return sample_delta(p_eff, new_age, u=u) - sample_delta(p_nat, new_age, u=u)


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
# Season state
# ---------------------------------------------------------------------------

def current_league_year_id(conn) -> Optional[int]:
    row = conn.execute(text(
        "SELECT id FROM league_years WHERE league_year = "
        "(SELECT season FROM timestamp_state WHERE id = 1)"
    )).first()
    return int(row[0]) if row else None


def previous_league_year_id(conn, league_year_id: int) -> Optional[int]:
    row = conn.execute(text("""
        SELECT p.id FROM league_years c
        JOIN league_years p ON p.league_year = c.league_year - 1
        WHERE c.id = :ly
    """), {"ly": int(league_year_id)}).first()
    return int(row[0]) if row else None


def camp_run(conn, league_year_id: int) -> Optional[Dict[str, Any]]:
    """The applied-camp record for the season, or None if camp has not run."""
    try:
        row = conn.execute(text("""
            SELECT league_year_id, prog_league_year_id, players, applied, skipped, applied_at, summary
            FROM training_camp_runs WHERE league_year_id = :ly
        """), {"ly": int(league_year_id)}).mappings().first()
    except Exception:          # table missing on an unmigrated DB
        return None
    if not row:
        return None
    out = dict(row)
    out["applied_at"] = str(out["applied_at"]) if out["applied_at"] else None
    s = out.get("summary")
    out["summary"] = json.loads(s) if isinstance(s, (str, bytes)) else s
    return out


def _assert_open(conn, league_year_id: int) -> None:
    if camp_run(conn, league_year_id):
        raise ValueError(LOCKED_MSG)


# ---------------------------------------------------------------------------
# Org-facing CRUD
# ---------------------------------------------------------------------------

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
    run = camp_run(conn, league_year_id)
    locked = run is not None
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
            "locked": locked,
        })
    return {"org_id": int(org_id), "league_year_id": int(league_year_id),
            "camp_applied": locked, "camp_applied_at": run["applied_at"] if run else None,
            "players": players, "with_focus": sum(1 for pid in focus if pid in roster)}


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
    _assert_open(conn, league_year_id)
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
    _assert_open(conn, league_year_id)
    n = conn.execute(text("""
        DELETE FROM training_camp_focus
        WHERE player_id = :pid AND org_id = :org AND league_year_id = :ly
    """), {"pid": int(player_id), "org": int(org_id), "ly": int(league_year_id)}).rowcount
    return n > 0


def org_results(conn, org_id: int, league_year_id: int) -> List[Dict[str, Any]]:
    """Fog-safe view for the org: what was trained and whether it backfired.
    Grades and true rating deltas are not returned (scouted information)."""
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
# Preseason step
# ---------------------------------------------------------------------------

def _season_started(conn, league_year_id: int) -> Optional[str]:
    """Reason string when the camp year's regular season is already under way."""
    ts = conn.execute(text("""
        SELECT season, week, is_offseason, games_a_ran, games_b_ran, games_c_ran, games_d_ran
        FROM timestamp_state WHERE id = 1
    """)).mappings().first()
    year = conn.execute(text("SELECT league_year FROM league_years WHERE id = :ly"),
                        {"ly": int(league_year_id)}).scalar()
    if not ts or year is None:
        return None
    if int(ts["season"]) > int(year):
        return f"the calendar is already past {year}"
    if int(ts["season"]) == int(year) and not ts["is_offseason"]:
        ran = any(ts[k] for k in ("games_a_ran", "games_b_ran", "games_c_ran", "games_d_ran"))
        if int(ts["week"] or 0) > 1 or ran:
            return f"the {year} regular season is under way (week {ts['week']})"
    return None


def apply_camp(conn, league_year_id: int, force: bool = False) -> Dict[str, Any]:
    """
    Run the preseason camp for ``league_year_id`` (the season about to be
    played). Replays the previous end-season's dice for every focus skill at
    the shifted grade, records results, takes a ``post_camp`` snapshot of the
    camp players and refreshes displayovr. One-shot per season: a second
    call returns the stored run without changing anything.
    """
    from player_engine.player_progression import load_growth_cache, pitch_ovr

    ly = int(league_year_id)
    prior = camp_run(conn, ly)
    if prior:
        return {"already_applied": True, **prior}
    if not force:
        started = _season_started(conn, ly)
        if started:
            raise ValueError(f"camp is a preseason step and {started}; pass force=true to apply anyway")

    prog_ly = previous_league_year_id(conn, ly)
    if not prog_ly:
        raise ValueError("no previous league year: there is no end-season progression to replay")
    pre_age = {int(pid): int(age) for pid, age in conn.execute(text("""
        SELECT player_id, age FROM player_rating_snapshots
        WHERE league_year_id = :p AND stage = 'pre_progression'
    """), {"p": prog_ly}).all()}
    if not pre_age:
        raise ValueError(f"no pre-progression snapshot for league year id {prog_ly}: "
                         "end-season must run (with the seeded progression) before camp")

    cfg = get_league_config(conn)
    rules = intensity_rules(cfg)
    focus_rows = conn.execute(text("""
        SELECT player_id, org_id, attr, intensity FROM training_camp_focus
        WHERE league_year_id = :ly ORDER BY player_id
    """), {"ly": ly}).mappings().all()
    pids = [int(r["player_id"]) for r in focus_rows]

    holders: Dict[int, Tuple[int, int]] = {}
    players: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(pids), 1000):
        ids = ",".join(str(p) for p in pids[i:i + 1000])
        for pid, org, lvl in conn.execute(text(f"""
            SELECT c.playerID, cts.orgID, c.current_level
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.isFinished = 0 AND c.playerID IN ({ids})
        """)).all():
            holders[int(pid)] = (int(org), int(lvl))
        for row in conn.execute(text(f"SELECT * FROM simbbPlayers WHERE id IN ({ids})")).mappings().all():
            players[int(row["id"])] = dict(row)

    cache = load_growth_cache(conn)
    applied: List[int] = []
    skipped: List[Dict[str, Any]] = []
    by_int: Dict[str, Dict[str, int]] = {}
    backfired_total = no_effect = 0
    for f in focus_rows:
        pid, org = int(f["player_id"]), int(f["org_id"])
        h = holders.get(pid)
        p = players.get(pid)
        if not p or not h or h[0] != org or h[1] < MIN_CAMP_LEVEL:
            skipped.append({"player_id": pid, "org_id": org, "reason": "org no longer holds the player"})
            continue
        if pid not in pre_age:
            skipped.append({"player_id": pid, "org_id": org, "reason": "not progressed last offseason"})
            continue
        new_age = pre_age[pid] + 1
        roll = camp_roll(pid, ly)
        steps, backfired = resolve_intensity(f["intensity"], roll, rules)
        cols = focus_pot_columns(f["attr"])
        updates: Dict[str, float] = {}
        deltas: Dict[str, float] = {}
        for pot_col in cols:
            base_col = pot_col[:-4] + "_base"
            nat = p.get(pot_col)
            d = replay_delta(prog_ly, pid, base_col, new_age, nat, shift_grade(nat, steps), cache)
            if d is None:
                continue
            deltas[base_col] = round(d, 4)
            updates[base_col] = float(p.get(base_col) or 0.0) + d
        if f["attr"] in PITCH_SLOTS and updates:
            subs = [f"{f['attr']}_{s}_base" for s in PITCH_SUB_ABILITIES]
            updates[f"{f['attr']}_ovr"] = pitch_ovr(updates.get(c, p.get(c)) for c in subs)
        if updates:
            set_sql = ", ".join(f"{c} = :{c}" for c in updates)
            conn.execute(text(f"UPDATE simbbPlayers SET {set_sql} WHERE id = :pid"), {**updates, "pid": pid})
        if not any(abs(v) > 1e-9 for v in deltas.values()):
            no_effect += 1
        first = cols[0]
        conn.execute(text("""
            INSERT INTO training_camp_results
                (player_id, org_id, league_year_id, prog_league_year_id, attr, intensity, base_grade,
                 effective_grade, steps, backfired, roll, pot_columns, effect)
            VALUES (:pid, :org, :ly, :pl, :attr, :int, :bg, :eg, :steps, :bf, :roll, :cols, :eff)
        """), {"pid": pid, "org": org, "ly": ly, "pl": prog_ly, "attr": f["attr"],
               "int": f["intensity"], "bg": p.get(first), "eg": shift_grade(p.get(first), steps),
               "steps": steps, "bf": 1 if backfired else 0, "roll": round(roll, 4),
               "cols": json.dumps(cols), "eff": json.dumps({"age": new_age, "deltas": deltas})})
        applied.append(pid)
        stat = by_int.setdefault(f["intensity"], {"players": 0, "backfired": 0})
        stat["players"] += 1
        if backfired:
            stat["backfired"] += 1
            backfired_total += 1

    summary: Dict[str, Any] = {
        "league_year_id": ly, "prog_league_year_id": prog_ly,
        "players": len(focus_rows), "applied": len(applied), "skipped": len(skipped),
        "backfired": backfired_total, "no_effect": no_effect, "by_intensity": by_int,
        "skipped_detail": skipped[:200],
    }
    if applied:
        from services.progression_snapshots import take_snapshot
        summary["snapshot"] = take_snapshot(conn, ly, "post_camp", player_ids=applied)
        from services.ovr_core import recompute_stored_displayovr
        summary["displayovr_refresh"] = recompute_stored_displayovr(conn)
    conn.execute(text("""
        INSERT INTO training_camp_runs
            (league_year_id, prog_league_year_id, players, applied, skipped, summary)
        VALUES (:ly, :pl, :n, :a, :s, :sum)
    """), {"ly": ly, "pl": prog_ly, "n": len(focus_rows), "a": len(applied), "s": len(skipped),
           "sum": json.dumps(summary, default=str)})
    log.info("training camp %d: %d applied, %d skipped, %d backfired, %d no effect",
             ly, len(applied), len(skipped), backfired_total, no_effect)
    return summary


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
    run = camp_run(conn, league_year_id)
    pending = 0
    if not run:
        pending = conn.execute(text(
            "SELECT COUNT(*) FROM training_camp_focus WHERE league_year_id = :ly"
        ), {"ly": int(league_year_id)}).scalar() or 0
    for row in by_int + by_attr:
        for k, v in list(row.items()):
            if hasattr(v, "quantize") or isinstance(v, float):
                row[k] = float(v)
            elif v is not None and not isinstance(v, (int, str)):
                row[k] = int(v)
        if "attr" in row:
            row["label"] = _label(row["attr"])
    return {"league_year_id": int(league_year_id), "by_intensity": by_int,
            "by_attr": by_attr, "pending_focus": int(pending),
            "applied": run is not None,
            "applied_at": run["applied_at"] if run else None,
            "skipped": int(run["skipped"]) if run else 0,
            "skipped_detail": (run.get("summary") or {}).get("skipped_detail", []) if run else []}
