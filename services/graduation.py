# services/graduation.py
"""
Amateur pipeline for the end of a season.

Runs inside / right after ``contract_ops.process_end_of_season``:

  * ``process_amateur_expiries``  – HS seniors graduate (to their college
    commitment or to the draft pool), college seniors graduate to the draft
    pool, INTAM players re-up or age out.
  * ``process_retirements``       – age / contract based retirements.
  * ``build_draft_pool``          – snapshot of draft-eligible players
    (HS graduates + every college player) with class year and a composite
    rank ("industry consensus").
  * ``generate_amateur_classes``  – new HS freshmen and INTAM entrants to
    refill both pools to their configured size (after player progression).
  * ``enroll_hs_walkons`` / ``retire_undrafted_seniors`` /
    ``topup_college_rosters`` – after the draft: unsigned HS graduates are
    placed at random on programs with room (below ``college_roster_target``)
    and the surplus retires; undrafted college seniors are kept as free
    agents (WBC-eligible) only above ``undrafted_keep_ovr``, the rest retire;
    programs still below the roster floor are topped up with generated
    walk-ons.
  * ``bootstrap_year_tables``     – per-year rows every subsystem expects
    (scouting budgets, IFA state/pools, recruiting state).

All functions take an open SQLAlchemy Core connection and write with raw SQL.
"""

import json
import logging
import random
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import text

from services.league_config import get_league_config, cfg_int
from services.org_constants import (
    INTAM_ORG_ID, USHS_ORG_ID, COLLEGE_ORG_MIN, COLLEGE_ORG_MAX, is_college_org,
)

log = logging.getLogger("app")

AMATEUR_SALARY = Decimal("40000.00")
HS_LEVEL, INTAM_LEVEL, COLLEGE_LEVEL = 1, 2, 3
HS_YEARS = 4
COLLEGE_YEARS = 4

# class_year labels stored on draft_eligible_players / draft_signing
CLASS_HS_SENIOR = "hs_senior"
CLASS_SENIOR = "senior"
CLASS_JUNIOR = "junior"
CLASS_SOPHOMORE = "sophomore"
CLASS_FRESHMAN = "freshman"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _college_org_sql(alias: str = "cts") -> str:
    return (f"(({alias}.orgID BETWEEN {COLLEGE_ORG_MIN} AND {COLLEGE_ORG_MAX}) "
            f"AND {alias}.orgID NOT IN ({INTAM_ORG_ID}, {USHS_ORG_ID}))")


def create_amateur_contract(conn, player_id: int, org_id: int, level: int,
                            years: int, league_year_val: int,
                            current_year: int = 1) -> int:
    """Create a 0-bonus amateur contract (HS / INTAM / college) and return its id."""
    res = conn.execute(text("""
        INSERT INTO contracts
            (playerID, years, current_year, isExtension, isBuyout, isActive,
             bonus, signingOrg, current_level, leagueYearSigned, isFinished, onIR)
        VALUES (:pid, :years, :cy, 0, 0, 1, 0.00, :org, :level, :ly, 0, 0)
    """), {"pid": player_id, "years": years, "cy": current_year,
           "org": org_id, "level": level, "ly": league_year_val})
    contract_id = res.lastrowid
    for yr in range(1, years + 1):
        det = conn.execute(text("""
            INSERT INTO contractDetails (contractID, year, salary)
            VALUES (:cid, :yr, :sal)
        """), {"cid": contract_id, "yr": yr, "sal": AMATEUR_SALARY})
        conn.execute(text("""
            INSERT INTO contractTeamShare (contractDetailsID, orgID, isHolder, salary_share)
            VALUES (:did, :org, 1, 1.00)
        """), {"did": det.lastrowid, "org": org_id})
    return contract_id


def _finish_contracts(conn, contract_ids: Sequence[int]) -> int:
    ids = [int(i) for i in contract_ids]
    if not ids:
        return 0
    total = 0
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        total += conn.execute(text(
            "UPDATE contracts SET isFinished = 1, isActive = 0 WHERE id IN (%s)"
            % ",".join(str(c) for c in chunk)
        )).rowcount
    return total


def _log_tx(conn, tx_type: str, league_year_id: int, org_id: int,
            player_id: Optional[int], contract_id: Optional[int],
            details: Dict[str, Any], notes: Optional[str] = None) -> None:
    """Best-effort transaction_log insert (the enum may not include new types
    on a database that has not been migrated)."""
    try:
        with conn.begin_nested():
            conn.execute(text("""
                INSERT INTO transaction_log
                    (transaction_type, league_year_id, primary_org_id, contract_id,
                     player_id, details, executed_by, notes)
                VALUES (:tt, :ly, :org, :cid, :pid, :details, 'system', :notes)
            """), {"tt": tx_type, "ly": league_year_id, "org": org_id,
                   "cid": contract_id, "pid": player_id,
                   "details": json.dumps(details), "notes": notes})
    except Exception as e:  # pragma: no cover - depends on DB state
        log.debug("transaction_log %s skipped: %s", tx_type, e)


def _pool_insert(conn, league_year_id: int, rows: List[Dict[str, Any]]) -> None:
    """Insert draft pool rows; existing (player, year) rows are left alone."""
    if not rows:
        return
    conn.execute(text("""
        INSERT IGNORE INTO draft_eligible_players
            (player_id, league_year_id, source, class_year)
        VALUES (:pid, :ly, :source, :class_year)
    """), [{"pid": r["player_id"], "ly": league_year_id,
            "source": r["source"], "class_year": r["class_year"]} for r in rows])


def class_year_for_remaining(remaining_years: int) -> str:
    """College class from the eligibility remaining AFTER the current season."""
    if remaining_years <= 0:
        return CLASS_SENIOR
    if remaining_years == 1:
        return CLASS_JUNIOR
    if remaining_years == 2:
        return CLASS_SOPHOMORE
    return CLASS_FRESHMAN


# ---------------------------------------------------------------------------
# 1. Amateur contract expiries (HS / college graduation, INTAM age-out)
# ---------------------------------------------------------------------------

def process_amateur_expiries(conn, expiring: Iterable[Dict[str, Any]],
                             league_year_id: int, next_league_year_id: int,
                             next_league_year_val: int) -> Dict[str, Any]:
    """
    Handle the expiring amateur contracts (levels 1-3) of the season that
    just finished.

    ``expiring`` rows need: contract_id, playerID, current_level, years.
    Returns a summary with counts.
    """
    cfg = get_league_config(conn)
    age_out = cfg_int(cfg, "intam_age_out", 23)

    summary = {
        "hs_graduated": 0, "hs_enrolled_college": 0, "hs_to_draft_pool": 0,
        "college_graduated": 0, "intam_reupped": 0, "intam_aged_out": 0,
    }
    rows = [dict(r) for r in expiring]
    if not rows:
        return summary

    # Finish every expiring amateur contract in bulk first.
    _finish_contracts(conn, [r["contract_id"] for r in rows])

    pool_rows: List[Dict[str, Any]] = []
    hs_rows = [r for r in rows if int(r["current_level"]) == HS_LEVEL]
    col_rows = [r for r in rows if int(r["current_level"]) == COLLEGE_LEVEL]
    intam_rows = [r for r in rows if int(r["current_level"]) == INTAM_LEVEL]

    # -- HS seniors: commitment -> college contract; everyone -> draft pool --
    if hs_rows:
        pids = [int(r["playerID"]) for r in hs_rows]
        commit_by_pid: Dict[int, int] = {}
        for i in range(0, len(pids), 1000):
            chunk = pids[i:i + 1000]
            for pid, org in conn.execute(text(f"""
                SELECT rc.player_id, rc.org_id
                FROM recruiting_commitments rc
                JOIN (
                    SELECT player_id, MAX(id) AS max_id
                    FROM recruiting_commitments
                    WHERE player_id IN ({",".join(str(p) for p in chunk)})
                    GROUP BY player_id
                ) latest ON latest.max_id = rc.id
            """)).all():
                commit_by_pid[int(pid)] = int(org)

        for r in hs_rows:
            pid = int(r["playerID"])
            summary["hs_graduated"] += 1
            org = commit_by_pid.get(pid)
            if org and is_college_org(org):
                cid = create_amateur_contract(
                    conn, pid, org, COLLEGE_LEVEL, COLLEGE_YEARS, next_league_year_val)
                _log_tx(conn, "college_enroll", next_league_year_id, org, pid, cid,
                        {"from": "hs_commitment", "years": COLLEGE_YEARS},
                        "HS graduate enrolled at committed college")
                summary["hs_enrolled_college"] += 1
            pool_rows.append({"player_id": pid, "source": "hs",
                              "class_year": CLASS_HS_SENIOR})
            summary["hs_to_draft_pool"] += 1

    # -- College seniors: draft pool as seniors (no contract) --
    for r in col_rows:
        summary["college_graduated"] += 1
        pool_rows.append({"player_id": int(r["playerID"]), "source": "college",
                          "class_year": CLASS_SENIOR})

    # -- INTAM: re-up until age_out, then leave the pool: kept as a free
    #    agent when good enough (undrafted_keep_ovr), otherwise retired --
    if intam_rows:
        keep_ovr = cfg_int(cfg, "undrafted_keep_ovr", 65)
        pids = [int(r["playerID"]) for r in intam_rows]
        ages: Dict[int, int] = {}
        ovrs: Dict[int, Optional[int]] = {}
        for i in range(0, len(pids), 1000):
            chunk = pids[i:i + 1000]
            for pid, age, ovr in conn.execute(text(
                "SELECT id, age, displayovr FROM simbbPlayers WHERE id IN (%s)"
                % ",".join(str(p) for p in chunk)
            )).all():
                ages[int(pid)] = int(age or 0)
                ovrs[int(pid)] = _parse_ovr(ovr)
        retire_items: List[Dict[str, Any]] = []
        for r in intam_rows:
            pid = int(r["playerID"])
            next_age = ages.get(pid, age_out) + 1      # age during the new season
            years = age_out - next_age
            if years >= 1:
                create_amateur_contract(conn, pid, INTAM_ORG_ID, INTAM_LEVEL,
                                        years, next_league_year_val)
                summary["intam_reupped"] += 1
            else:
                summary["intam_aged_out"] += 1
                ovr = ovrs.get(pid)
                if ovr is not None and ovr >= keep_ovr:
                    summary["intam_aged_out_kept"] = summary.get("intam_aged_out_kept", 0) + 1
                else:
                    retire_items.append({"player_id": pid, "age": ages.get(pid, 0),
                                         "reason": "intam_aged_out"})
        if retire_items:
            _retire_players(conn, league_year_id, retire_items,
                            "Aged out of the international amateur pool unsigned")
            summary["intam_retired"] = len(retire_items)

    _pool_insert(conn, next_league_year_id, pool_rows)
    log.info("graduation: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# 2. Retirements
# ---------------------------------------------------------------------------

def retirement_reason(age: int, has_pro_contract: bool, ovr: Optional[int],
                      cfg: Dict[str, Any], ever_pro: bool = True) -> Optional[str]:
    """Pure rule: return the retirement reason or None (player plays on).

    ``ever_pro`` is False for a player who never held a pro (level >= 4)
    contract: an undrafted graduate kept in the free-agent pool retires once
    he reaches ``never_signed_retire_age`` without ever being signed.
    """
    hard = cfg_int(cfg, "retire_age_hard", 40)
    unsigned = cfg_int(cfg, "retire_age_unsigned", 36)
    marginal = cfg_int(cfg, "retire_age_marginal", 33)
    marginal_ovr = cfg_int(cfg, "retire_marginal_ovr", 40)
    never_signed = cfg_int(cfg, "never_signed_retire_age", 25)
    if hard > 0 and age >= hard:          # 0 disables the pure-age rule
        return "age"
    if has_pro_contract:
        return None
    if age >= unsigned:
        return "unsigned"
    if age >= marginal and ovr is not None and ovr < marginal_ovr:
        return "unsigned_marginal"
    if not ever_pro and age >= never_signed:
        return "never_signed"
    return None


def _parse_ovr(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _retire_players(conn, league_year_id: int, items: Sequence[Dict[str, Any]],
                    notes: str = "Retired after the season") -> Dict[str, int]:
    """Record retirements for ``items`` ({player_id, age, reason}): finish any
    open contract, withdraw an active auction, insert player_retirements,
    log a ``retirement`` transaction. The player row and all his stats stay.
    Returns counts by reason."""
    by_reason: Dict[str, int] = {}
    for item in items:
        pid = int(item["player_id"])
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        # Holder org (if any) for the log, then finish everything open.
        holder = conn.execute(text("""
            SELECT cts.orgID, c.id FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.playerID = :pid AND c.isFinished = 0
            ORDER BY c.id DESC LIMIT 1
        """), {"pid": pid}).first()
        conn.execute(text(
            "UPDATE contracts SET isFinished = 1, isActive = 0 "
            "WHERE playerID = :pid AND isFinished = 0"), {"pid": pid})
        conn.execute(text(
            "UPDATE fa_auction SET phase = 'withdrawn' "
            "WHERE player_id = :pid AND phase IN ('open','listening','finalize')"),
            {"pid": pid})
        conn.execute(text("""
            INSERT IGNORE INTO player_retirements (player_id, league_year_id, age, reason)
            VALUES (:pid, :ly, :age, :reason)
        """), {"pid": pid, "ly": league_year_id, "age": int(item.get("age") or 0),
               "reason": item["reason"]})
        _log_tx(conn, "retirement", league_year_id,
                int(holder[0]) if holder else 0, pid,
                int(holder[1]) if holder else None,
                {"age": int(item.get("age") or 0), "reason": item["reason"]},
                notes)
    return by_reason


def process_retirements(conn, league_year_id: int,
                        protect_ids: Iterable[int] = ()) -> Dict[str, Any]:
    """
    Retire players per ``retirement_reason``. Ages are the ones of the season
    just played (run BEFORE player progression). Finishes any open contract
    of a retiree, withdraws his active auction, records player_retirements.
    Returns {"retired": n, "player_ids": [...], "by_reason": {...}}.
    """
    cfg = get_league_config(conn)
    min_age = min([v for v in (cfg_int(cfg, "retire_age_hard", 0),
                                cfg_int(cfg, "retire_age_unsigned", 36),
                                cfg_int(cfg, "retire_age_marginal", 33),
                                cfg_int(cfg, "never_signed_retire_age", 25)) if v > 0] or [25])
    protect = {int(p) for p in protect_ids}

    try:
        conn.execute(text("SELECT 1 FROM player_retirements LIMIT 1"))
    except Exception:
        log.warning("player_retirements table missing; retirements skipped")
        return {"retired": 0, "player_ids": [], "by_reason": {}, "skipped": "no table"}

    rows = conn.execute(text("""
        SELECT p.id, p.age, p.displayovr,
               EXISTS (
                   SELECT 1 FROM contracts c
                   JOIN contractDetails cd ON cd.contractID = c.id
                   JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
                        AND cts.isHolder = 1
                   WHERE c.playerID = p.id AND c.isFinished = 0
                     AND c.current_level >= 4
               ) AS has_pro,
               EXISTS (
                   SELECT 1 FROM contracts c2
                   WHERE c2.playerID = p.id AND c2.isFinished = 0
                     AND c2.current_level <= 3
               ) AS is_amateur,
               EXISTS (
                   SELECT 1 FROM contracts c3
                   WHERE c3.playerID = p.id AND c3.current_level >= 4
               ) AS ever_pro
        FROM simbbPlayers p
        WHERE p.age >= :min_age
          AND EXISTS (SELECT 1 FROM contracts c4 WHERE c4.playerID = p.id)
          AND NOT EXISTS (SELECT 1 FROM player_retirements r WHERE r.player_id = p.id)
    """), {"min_age": min_age}).mappings().all()

    retired: List[Dict[str, Any]] = []
    for r in rows:
        pid = int(r["id"])
        if pid in protect or r["is_amateur"]:
            continue
        reason = retirement_reason(int(r["age"] or 0), bool(r["has_pro"]),
                                   _parse_ovr(r["displayovr"]), cfg,
                                   ever_pro=bool(r["ever_pro"]))
        if reason:
            retired.append({"player_id": pid, "age": int(r["age"] or 0), "reason": reason})

    by_reason = _retire_players(conn, league_year_id, retired)

    log.info("retirements: %d (%s)", len(retired), by_reason)
    return {"retired": len(retired), "player_ids": [r["player_id"] for r in retired],
            "by_reason": by_reason}


# ---------------------------------------------------------------------------
# 3. Draft pool snapshot + ranking
# ---------------------------------------------------------------------------

def build_draft_pool(conn, league_year_id: int,
                     include_active_hs_seniors: bool = False) -> int:
    """
    Add every active college player to the draft pool for ``league_year_id``
    (HS / college graduates were added by ``process_amateur_expiries``) and
    rank the pool. ``include_active_hs_seniors`` is the fallback for a draft
    initialized without end-season having run (HS contracts in their final
    year count as seniors). Returns the pool size.
    """
    conn.execute(text(f"""
        INSERT IGNORE INTO draft_eligible_players (player_id, league_year_id, source, class_year)
        SELECT c.playerID, :ly, 'college',
               CASE
                   WHEN c.years - c.current_year <= 0 THEN '{CLASS_SENIOR}'
                   WHEN c.years - c.current_year = 1 THEN '{CLASS_JUNIOR}'
                   WHEN c.years - c.current_year = 2 THEN '{CLASS_SOPHOMORE}'
                   ELSE '{CLASS_FRESHMAN}'
               END
        FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE c.isFinished = 0 AND c.current_level = {COLLEGE_LEVEL}
          AND {_college_org_sql("cts")}
    """), {"ly": league_year_id})

    if include_active_hs_seniors:
        conn.execute(text(f"""
            INSERT IGNORE INTO draft_eligible_players (player_id, league_year_id, source, class_year)
            SELECT c.playerID, :ly, 'hs', '{CLASS_HS_SENIOR}'
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            WHERE c.isFinished = 0 AND c.current_level = {HS_LEVEL}
              AND cts.orgID = {USHS_ORG_ID} AND c.current_year >= c.years
        """), {"ly": league_year_id})

    # Retired players never belong in a draft pool.
    try:
        conn.execute(text("""
            DELETE dep FROM draft_eligible_players dep
            JOIN player_retirements r ON r.player_id = dep.player_id
            WHERE dep.league_year_id = :ly
        """), {"ly": league_year_id})
    except Exception:
        pass

    return rank_draft_pool(conn, league_year_id)


_RANK_ATTR_SQL = """
    p.id, p.ptype,
    p.contact_base, p.power_base, p.discipline_base, p.eye_base, p.speed_base,
    p.baserunning_base, p.throwpower_base, p.throwacc_base,
    p.fieldcatch_base, p.fieldreact_base, p.fieldspot_base,
    p.pendurance_base, p.pgencontrol_base, p.pthrowpower_base, p.psequencing_base,
    p.pitch1_pacc_base, p.pitch1_pbrk_base, p.pitch1_pcntrl_base, p.pitch1_consist_base,
    p.pitch2_pacc_base, p.pitch2_pbrk_base, p.pitch2_pcntrl_base, p.pitch2_consist_base,
    p.contact_pot, p.power_pot, p.discipline_pot, p.eye_pot, p.speed_pot,
    p.pendurance_pot, p.pgencontrol_pot, p.pthrowpower_pot, p.psequencing_pot
"""


def rank_draft_pool(conn, league_year_id: int) -> int:
    """Compute composite + draft_rank (1 = best) for the whole pool. Returns size."""
    from services.recruiting import (
        _compute_recruiting_composite, _group_pot_avg, _POS_GROUPS, _PIT_GROUPS,
        _POS_POT_ATTRS, _PIT_POT_ATTRS,
    )
    rows = conn.execute(text(f"""
        SELECT {_RANK_ATTR_SQL}
        FROM draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        WHERE dep.league_year_id = :ly
    """), {"ly": league_year_id}).mappings().all()
    if not rows:
        return 0

    scored = []
    for m in rows:
        is_pit = (m["ptype"] or "Position") == "Pitcher"
        comp = _compute_recruiting_composite(m, _PIT_GROUPS if is_pit else _POS_GROUPS)
        pot = _group_pot_avg(m, _PIT_POT_ATTRS if is_pit else _POS_POT_ATTRS)
        scored.append((int(m["id"]), comp, pot))
    # best first; ties by potential, then lowest id
    scored.sort(key=lambda x: (-x[1], -x[2], x[0]))

    for i in range(0, len(scored), 500):
        chunk = scored[i:i + 500]
        rank_cases = " ".join(f"WHEN {pid} THEN {i + j + 1}" for j, (pid, _, _) in enumerate(chunk))
        comp_cases = " ".join(f"WHEN {pid} THEN {comp:.4f}" for pid, comp, _ in chunk)
        ids = ",".join(str(pid) for pid, _, _ in chunk)
        conn.execute(text(f"""
            UPDATE draft_eligible_players
            SET draft_rank = CASE player_id {rank_cases} END,
                composite  = CASE player_id {comp_cases} END
            WHERE league_year_id = :ly AND player_id IN ({ids})
        """), {"ly": league_year_id})
    return len(scored)


# ---------------------------------------------------------------------------
# 4. New amateur classes (after progression)
# ---------------------------------------------------------------------------

def _count_pool(conn, org_id: int, level: int) -> int:
    return int(conn.execute(text("""
        SELECT COUNT(*) FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE c.isFinished = 0 AND c.current_level = :lvl AND cts.orgID = :org
    """), {"lvl": level, "org": org_id}).scalar() or 0)


def generate_amateur_classes(conn, next_league_year_id: int,
                             next_league_year_val: int) -> Dict[str, Any]:
    """Refill the HS and INTAM pools to their configured sizes with new players."""
    from player_engine.player_generation import generate_players

    cfg = get_league_config(conn)
    hs_target = cfg_int(cfg, "hs_pool_target", 8864)
    hs_age = cfg_int(cfg, "hs_entry_age", 15)
    intam_target = cfg_int(cfg, "intam_pool_target", 6722)
    intam_age = cfg_int(cfg, "intam_entry_age", 15)
    age_out = cfg_int(cfg, "intam_age_out", 23)

    hs_now = _count_pool(conn, USHS_ORG_ID, HS_LEVEL)
    intam_now = _count_pool(conn, INTAM_ORG_ID, INTAM_LEVEL)
    hs_need = max(0, hs_target - hs_now)
    intam_need = max(0, intam_target - intam_now)

    summary = {"hs_before": hs_now, "hs_generated": 0,
               "intam_before": intam_now, "intam_generated": 0}

    if hs_need:
        players = generate_players(conn, hs_need, age=hs_age, region_type="usa")
        for p in players:
            create_amateur_contract(conn, int(p["id"]), USHS_ORG_ID, HS_LEVEL,
                                    HS_YEARS, next_league_year_val)
        summary["hs_generated"] = len(players)

    if intam_need:
        players = generate_players(conn, intam_need, age=intam_age,
                                   region_type="international")
        # Seeding convention: a young INTAM contract runs to age 18, then a
        # second one to age_out (handled by process_amateur_expiries).
        years = max(1, min(18, age_out) - intam_age)
        for p in players:
            create_amateur_contract(conn, int(p["id"]), INTAM_ORG_ID, INTAM_LEVEL,
                                    years, next_league_year_val)
        summary["intam_generated"] = len(players)

    log.info("amateur classes: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# 5. After the draft: walk-ons and roster floor
# ---------------------------------------------------------------------------

def _college_roster_sizes(conn) -> Dict[int, int]:
    sizes: Dict[int, int] = {}
    for org_id, in conn.execute(text(
        "SELECT id FROM organizations WHERE id BETWEEN :lo AND :hi"
    ), {"lo": COLLEGE_ORG_MIN, "hi": COLLEGE_ORG_MAX}).all():
        if is_college_org(int(org_id)):
            sizes[int(org_id)] = 0
    for org_id, n in conn.execute(text(f"""
        SELECT cts.orgID, COUNT(*) FROM contracts c
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
        WHERE c.isFinished = 0 AND c.current_level = {COLLEGE_LEVEL}
          AND {_college_org_sql("cts")}
        GROUP BY cts.orgID
    """)).all():
        sizes[int(org_id)] = int(n)
    return sizes


def enroll_hs_walkons(conn, league_year_id: int, league_year_val: int) -> Dict[str, Any]:
    """
    HS graduates in this year's draft pool who ended up with no contract
    (uncommitted and undrafted / unsigned / refused) are placed, best-ranked
    first, on a program chosen at random among those that need players
    (roster below ``college_roster_target``). Once no program has room the
    rest retire (reason ``hs_undrafted``).
    """
    cfg = get_league_config(conn)
    target = cfg_int(cfg, "college_roster_target", 28)
    rows = conn.execute(text("""
        SELECT dep.player_id, p.age
        FROM draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        WHERE dep.league_year_id = :ly AND dep.source = 'hs'
          AND NOT EXISTS (SELECT 1 FROM contracts c
                          WHERE c.playerID = dep.player_id AND c.isFinished = 0)
          AND NOT EXISTS (SELECT 1 FROM player_retirements r
                          WHERE r.player_id = dep.player_id)
        ORDER BY dep.draft_rank, dep.player_id
    """), {"ly": league_year_id}).all()
    if not rows:
        return {"hs_walkons": 0, "hs_retired": 0}

    sizes = _college_roster_sizes(conn)
    room: Dict[int, int] = {org: target - n for org, n in sizes.items() if n < target}
    open_orgs = sorted(room)
    rng = random.Random(f"walkons:{league_year_id}")

    placed = 0
    retire_items: List[Dict[str, Any]] = []
    for pid, age in rows:
        pid = int(pid)
        if not open_orgs:
            retire_items.append({"player_id": pid, "age": int(age or 0),
                                 "reason": "hs_undrafted"})
            continue
        idx = rng.randrange(len(open_orgs))
        org = open_orgs[idx]
        cid = create_amateur_contract(conn, pid, org, COLLEGE_LEVEL, COLLEGE_YEARS,
                                      league_year_val)
        _log_tx(conn, "walkon_enroll", league_year_id, org, pid, cid,
                {"from": "hs_undrafted"}, "Unsigned HS graduate enrolled as a walk-on")
        placed += 1
        room[org] -= 1
        if room[org] <= 0:
            open_orgs.pop(idx)

    if retire_items:
        _retire_players(conn, league_year_id, retire_items,
                        "Undrafted out of high school with no college spot")
    log.info("hs walk-ons enrolled: %d, retired: %d (target %d)",
             placed, len(retire_items), target)
    return {"hs_walkons": placed, "hs_retired": len(retire_items)}


def retire_undrafted_seniors(conn, league_year_id: int) -> Dict[str, Any]:
    """
    College seniors in this year's draft pool who left school without a pro
    contract: kept in the system as free agents (signable, WBC-eligible) when
    ``displayovr`` >= ``undrafted_keep_ovr``, otherwise retired
    (reason ``college_undrafted``).
    """
    cfg = get_league_config(conn)
    keep_ovr = cfg_int(cfg, "undrafted_keep_ovr", 65)
    rows = conn.execute(text(f"""
        SELECT dep.player_id, p.age, p.displayovr
        FROM draft_eligible_players dep
        JOIN simbbPlayers p ON p.id = dep.player_id
        WHERE dep.league_year_id = :ly AND dep.source = 'college'
          AND dep.class_year = '{CLASS_SENIOR}'
          AND NOT EXISTS (SELECT 1 FROM contracts c
                          WHERE c.playerID = dep.player_id AND c.isFinished = 0)
          AND NOT EXISTS (SELECT 1 FROM player_retirements r
                          WHERE r.player_id = dep.player_id)
    """), {"ly": league_year_id}).all()
    kept = 0
    retire_items: List[Dict[str, Any]] = []
    for pid, age, ovr_raw in rows:
        ovr = _parse_ovr(ovr_raw)
        if ovr is not None and ovr >= keep_ovr:
            kept += 1
        else:
            retire_items.append({"player_id": int(pid), "age": int(age or 0),
                                 "reason": "college_undrafted"})
    if retire_items:
        _retire_players(conn, league_year_id, retire_items,
                        "Left college undrafted and unsigned")
    log.info("undrafted college seniors: kept %d, retired %d (keep ovr >= %d)",
             kept, len(retire_items), keep_ovr)
    return {"college_undrafted_kept": kept, "college_undrafted_retired": len(retire_items)}


def topup_college_rosters(conn, league_year_id: int, league_year_val: int) -> Dict[str, Any]:
    """Generate walk-ons for programs still below the configured roster floor."""
    from player_engine.player_generation import generate_players

    cfg = get_league_config(conn)
    floor = cfg_int(cfg, "college_roster_floor", 25)
    age = cfg_int(cfg, "walkon_age", 19)
    sizes = _college_roster_sizes(conn)
    needs = {org: floor - n for org, n in sizes.items() if n < floor}
    total = sum(needs.values())
    if not total:
        return {"generated_walkons": 0, "programs_topped_up": 0}
    players = generate_players(conn, total, age=age, region_type="usa")
    it = iter(players)
    for org, need in needs.items():
        for _ in range(need):
            p = next(it)
            create_amateur_contract(conn, int(p["id"]), org, COLLEGE_LEVEL,
                                    COLLEGE_YEARS, league_year_val)
    log.info("college floor top-up: %d walk-ons for %d programs", total, len(needs))
    return {"generated_walkons": total, "programs_topped_up": len(needs)}


# ---------------------------------------------------------------------------
# 6. Per-year rows for the other subsystems
# ---------------------------------------------------------------------------

def bootstrap_year_tables(conn, new_league_year_id: int,
                          standings_league_year_id: int) -> Dict[str, Any]:
    """scouting_budgets for every org, ifa_state + ifa_bonus_pools (from the
    finished season's standings), recruiting_state."""
    out: Dict[str, Any] = {}
    try:
        from services.scouting_service import get_or_create_budget
        created = 0
        for org_id, in conn.execute(text("SELECT id FROM organizations ORDER BY id")).all():
            before = conn.execute(text(
                "SELECT 1 FROM scouting_budgets WHERE org_id = :o AND league_year_id = :ly"
            ), {"o": org_id, "ly": new_league_year_id}).first()
            if not before:
                get_or_create_budget(conn, int(org_id), new_league_year_id)
                created += 1
        out["scouting_budgets_created"] = created
    except Exception as e:
        out["scouting_budgets_error"] = str(e)

    try:
        from services.ifa_signing import allocate_bonus_pools, get_ifa_config
        from services.recruiting import _cfg_int as _rc_int
        ifa_cfg = get_ifa_config(conn)
        conn.execute(text("""
            INSERT IGNORE INTO ifa_state (league_year_id, current_week, total_weeks, status)
            VALUES (:ly, 0, :tw, 'pending')
        """), {"ly": new_league_year_id, "tw": _rc_int(ifa_cfg, "ifa_weeks", 20)})
        pools = allocate_bonus_pools(conn, new_league_year_id,
                                     standings_league_year_id=standings_league_year_id)
        out["ifa_bonus_pools"] = len(pools)
    except Exception as e:
        out["ifa_error"] = str(e)

    try:
        conn.execute(text("""
            INSERT IGNORE INTO recruiting_state (league_year_id, current_week, status)
            VALUES (:ly, 0, 'pending')
        """), {"ly": new_league_year_id})
        out["recruiting_state"] = "ok"
    except Exception as e:
        out["recruiting_state_error"] = str(e)
    return out
