# migrations/add_recruiting_columns.py
"""
Add signing_tendency and recruit_stars columns to simbbPlayers.

Changes:
  - signing_tendency VARCHAR(20) NOT NULL DEFAULT 'Signs Normal'
    Weighted random assignment for HS players (org 340):
    Signs Very Early 5%, Signs Early 15%, Signs Normal 50%, Signs Late 20%, Signs Very Late 10%
  - recruit_stars TINYINT NULL
    One-time backfill for existing college players (orgs 31-342 excl 339,340)
    using composite scoring with distribution: 5★ 2%, 4★ 4%, 3★ 14%, 2★ 60%, 1★ 20%

Run via: POST /admin/migrations/add-recruiting-columns
"""

import logging
import random

from sqlalchemy import text

from db import get_engine

log = logging.getLogger("app")

USHS_ORG_ID = 340
INTAM_ORG_ID = 339
COLLEGE_ORG_MIN = 31
COLLEGE_ORG_MAX = 342

# Signing tendency weighted distribution
_TENDENCY_WEIGHTS = [
    ("Signs Very Early", 5),
    ("Signs Early", 15),
    ("Signs Normal", 50),
    ("Signs Late", 20),
    ("Signs Very Late", 10),
]
_TENDENCY_VALUES = [t for t, _ in _TENDENCY_WEIGHTS]
_TENDENCY_CUM_WEIGHTS = []
_running = 0
for _, w in _TENDENCY_WEIGHTS:
    _running += w
    _TENDENCY_CUM_WEIGHTS.append(_running)

# College star distribution (different from HS)
_COLLEGE_STAR_THRESHOLDS = [
    (0.02, 5),   # Top 2%
    (0.06, 4),   # Next 4%
    (0.20, 3),   # Next 14%
    (0.80, 2),   # Next 60%
    (1.00, 1),   # Bottom 20%
]

# Grade -> numeric value for pot bonus (same as recruiting.py)
_GRADE_VAL = {
    "A+": 6, "A": 5, "A-": 4,
    "B+": 3, "B": 2, "B-": 1,
    "C+": 0, "C": -1, "C-": -2,
    "D+": -3, "D": -4, "D-": -5,
    "F": -6,
}

# Position player attributes for composite scoring
_POS_BASE_ATTRS = [
    "contact_base", "power_base", "discipline_base",
    "eye_base", "speed_base", "baserunning_base",
    "throwpower_base", "throwacc_base",
    "fieldcatch_base", "fieldreact_base", "fieldspot_base",
]
_POS_POT_ATTRS = [
    "contact_pot", "power_pot", "discipline_pot",
    "eye_pot", "speed_pot",
]

# Pitcher attributes for composite scoring
_PIT_BASE_ATTRS = [
    "pendurance_base", "pgencontrol_base", "pthrowpower_base",
    "psequencing_base",
    "pitch1_pacc_base", "pitch1_pbrk_base",
    "pitch1_pcntrl_base", "pitch1_consist_base",
    "pitch2_pacc_base", "pitch2_pbrk_base",
    "pitch2_pcntrl_base", "pitch2_consist_base",
    "throwpower_base", "throwacc_base",
]
_PIT_POT_ATTRS = [
    "pendurance_pot", "pgencontrol_pot", "pthrowpower_pot",
    "psequencing_pot",
]


def _compute_composite(m, base_attrs, pot_attrs):
    """Compute composite score from base attributes + pot bonus."""
    base_sum = 0.0
    base_count = 0
    for key in base_attrs:
        val = m.get(key)
        if val is not None:
            try:
                base_sum += float(val)
                base_count += 1
            except (TypeError, ValueError):
                pass
    base_avg = base_sum / max(base_count, 1)

    pot_bonus = 0.0
    pot_count = 0
    for key in pot_attrs:
        g = m.get(key)
        if g and g in _GRADE_VAL:
            pot_bonus += _GRADE_VAL[g]
            pot_count += 1
    pot_avg = (pot_bonus / max(pot_count, 1)) * 2

    return base_avg + pot_avg


def _assign_college_stars(scored_list):
    """
    Assign star ratings using college distribution to a sorted (desc) list
    of (pid, ptype, composite).
    """
    total = len(scored_list)
    result = []
    for idx, (pid, ptype, comp) in enumerate(scored_list):
        pct = idx / max(total, 1)
        star = 1
        for upper_bound, s in _COLLEGE_STAR_THRESHOLDS:
            if pct < upper_bound:
                star = s
                break
        result.append({"player_id": pid, "ptype": ptype, "star": star})
    return result


def _pick_tendency():
    """Weighted random signing tendency."""
    r = random.randint(1, 100)
    for val, cum in zip(_TENDENCY_VALUES, _TENDENCY_CUM_WEIGHTS):
        if r <= cum:
            return val
    return "Signs Normal"


def migrate_add_recruiting_columns(engine=None):
    """
    Add signing_tendency + recruit_stars columns and backfill.
    Returns summary dict with counts.
    """
    if engine is None:
        engine = get_engine()

    with engine.begin() as conn:
        # ── Step 1: Add columns if they don't exist ──

        # Check existing columns
        existing = conn.execute(
            text("SHOW COLUMNS FROM simbbPlayers")
        ).all()
        col_names = {r[0] for r in existing}

        if "signing_tendency" not in col_names:
            conn.execute(text(
                "ALTER TABLE simbbPlayers "
                "ADD COLUMN signing_tendency VARCHAR(20) NOT NULL DEFAULT 'Signs Normal'"
            ))
            log.info("Added signing_tendency column")

        if "recruit_stars" not in col_names:
            conn.execute(text(
                "ALTER TABLE simbbPlayers "
                "ADD COLUMN recruit_stars TINYINT NULL"
            ))
            log.info("Added recruit_stars column")

        # ── Step 2: Backfill signing_tendency for HS players ──

        hs_players = conn.execute(
            text("""
                SELECT p.id
                FROM simbbPlayers p
                JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
                JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
                JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
                WHERE cts.orgID = :ushs
                  AND p.signing_tendency = 'Signs Normal'
            """),
            {"ushs": USHS_ORG_ID},
        ).all()

        tendency_count = 0
        for (pid,) in hs_players:
            tendency = _pick_tendency()
            if tendency != "Signs Normal":
                conn.execute(
                    text("UPDATE simbbPlayers SET signing_tendency = :t WHERE id = :pid"),
                    {"t": tendency, "pid": pid},
                )
                tendency_count += 1

        log.info("Backfilled signing_tendency for %d HS players (non-Normal)", tendency_count)

        # ── Step 3: Backfill recruit_stars for college players ──

        college_attr_cols = ", ".join([
            "p.id", "p.ptype",
            *[f"p.{a}" for a in _POS_BASE_ATTRS],
            *[f"p.{a}" for a in _POS_POT_ATTRS],
            *[f"p.{a}" for a in _PIT_BASE_ATTRS],
            *[f"p.{a}" for a in _PIT_POT_ATTRS],
        ])

        college_rows = conn.execute(
            text(f"""
                SELECT {college_attr_cols}
                FROM simbbPlayers p
                JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
                JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
                JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
                WHERE cts.orgID BETWEEN :cmin AND :cmax
                  AND cts.orgID NOT IN (:intam, :ushs)
                  AND p.recruit_stars IS NULL
            """),
            {
                "cmin": COLLEGE_ORG_MIN, "cmax": COLLEGE_ORG_MAX,
                "intam": INTAM_ORG_ID, "ushs": USHS_ORG_ID,
            },
        ).all()

        if college_rows:
            pos_scored = []
            pit_scored = []
            for r in college_rows:
                m = r._mapping
                ptype = m["ptype"] or "Position"
                if ptype == "Pitcher":
                    comp = _compute_composite(m, _PIT_BASE_ATTRS, _PIT_POT_ATTRS)
                    pit_scored.append((m["id"], ptype, comp))
                else:
                    comp = _compute_composite(m, _POS_BASE_ATTRS, _POS_POT_ATTRS)
                    pos_scored.append((m["id"], ptype, comp))

            pos_scored.sort(key=lambda x: x[2], reverse=True)
            pit_scored.sort(key=lambda x: x[2], reverse=True)

            pos_ranked = _assign_college_stars(pos_scored)
            pit_ranked = _assign_college_stars(pit_scored)
            all_ranked = pos_ranked + pit_ranked

            for r in all_ranked:
                conn.execute(
                    text("UPDATE simbbPlayers SET recruit_stars = :star WHERE id = :pid"),
                    {"star": r["star"], "pid": r["player_id"]},
                )

            log.info("Backfilled recruit_stars for %d college players", len(all_ranked))
        else:
            all_ranked = []
            log.info("No college players to backfill recruit_stars")

        summary = {
            "hs_tendency_updated": tendency_count,
            "hs_tendency_total": len(hs_players),
            "college_stars_backfilled": len(all_ranked),
        }
        log.info("migrate_add_recruiting_columns: done — %s", summary)
        return summary
