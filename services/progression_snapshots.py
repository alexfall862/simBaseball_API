# services/progression_snapshots.py
"""
True-value rating snapshots around each progression, and the admin
diagnostics built on them.

``take_snapshot`` writes one row per player (age, level, org, raw_ovr,
displayovr, all base attributes and potentials as JSON) for a
(league_year_id, stage). ``compute_curve_stats`` turns the pre/post pair into
realised deltas per (potential grade, age) for the table-vs-actual report.
Training camp runs in the preseason, outside that pair; its own
``post_camp`` snapshot covers only the camp players of the season.

raw_ovr is the weighted average of the *base* attributes
(``ovr_core.compute_raw_ovr``), an absolute number. displayovr is a cohort
percentile and cannot show trends; it is stored only for reference.
"""
import json
import logging
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from player_engine.constants import ALL_ABILITIES, PITCH_SLOTS, PITCH_SUB_ABILITIES

log = logging.getLogger("app")

BASE_COLS: List[str] = [f"{a}_base" for a in ALL_ABILITIES] + \
    [f"{s}_{sub}_base" for s in PITCH_SLOTS for sub in PITCH_SUB_ABILITIES]
POT_COLS: List[str] = [c[:-5] + "_pot" for c in BASE_COLS]
STAGES = ("pre_progression", "post_progression", "post_camp")


def _pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def take_snapshot(conn, league_year_id: int, stage: str,
                  player_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """Snapshot every non-retired player, or only ``player_ids``."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    if player_ids is not None and not player_ids:
        return {"stage": stage, "players": 0}
    id_sql = "" if player_ids is None else \
        f" AND p.id IN ({','.join(str(int(x)) for x in player_ids)})"
    del_sql = "" if player_ids is None else \
        f" AND player_id IN ({','.join(str(int(x)) for x in player_ids)})"
    from services.ovr_core import load_weights, compute_raw_ovr

    weights = load_weights(conn)
    listed: Dict[int, str] = {}
    try:
        for pid, code in conn.execute(text(
            "SELECT player_id, position_code FROM player_listed_position WHERE league_year_id = :ly"
        ), {"ly": int(league_year_id)}).all():
            listed[int(pid)] = str(code)
    except Exception:
        log.exception("snapshot: listed positions unavailable")

    rows = conn.execute(text("""
        SELECT p.*, h.current_level AS _level, h.orgID AS _org
        FROM simbbPlayers p
        LEFT JOIN (
            SELECT c.playerID, c.current_level, cts.orgID
            FROM contracts c
            JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
            JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id AND cts.isHolder = 1
            JOIN (SELECT playerID, MAX(id) AS max_cid FROM contracts WHERE isFinished = 0 GROUP BY playerID) m
                 ON m.max_cid = c.id
        ) h ON h.playerID = p.id
        WHERE NOT EXISTS (SELECT 1 FROM player_retirements r WHERE r.player_id = p.id){id_sql}
    """.replace("{id_sql}", id_sql))).mappings().all()

    conn.execute(text(
        "DELETE FROM player_rating_snapshots WHERE league_year_id = :ly AND stage = :st" + del_sql
    ), {"ly": int(league_year_id), "st": stage})

    batch: List[Dict[str, Any]] = []
    insert = text("""
        INSERT INTO player_rating_snapshots
            (player_id, league_year_id, stage, age, level, org_id, ptype, raw_ovr, displayovr, attrs)
        VALUES (:pid, :ly, :st, :age, :lvl, :org, :pt, :raw, :dovr, :attrs)
    """)
    written = 0
    for row in rows:
        pid = int(row["id"])
        ptype = (row.get("ptype") or "").strip() or None
        raw = None
        if weights and ptype:
            try:
                raw = compute_raw_ovr(row, ptype, listed.get(pid), weights, key_suffix="_base")
            except Exception:
                raw = None
        try:
            dovr = int(str(row["displayovr"]).strip()) if row.get("displayovr") is not None else None
        except ValueError:
            dovr = None
        attrs = {
            "bases": {c: (round(float(row[c]), 2) if row.get(c) is not None else None) for c in BASE_COLS},
            "pots": {c: row.get(c) for c in POT_COLS},
        }
        batch.append({"pid": pid, "ly": int(league_year_id), "st": stage,
                      "age": int(row["age"] or 0), "lvl": row["_level"], "org": row["_org"],
                      "pt": ptype, "raw": None if raw is None else round(float(raw), 3),
                      "dovr": dovr, "attrs": json.dumps(attrs)})
        if len(batch) >= 500:
            conn.execute(insert, batch)
            written += len(batch)
            batch = []
    if batch:
        conn.execute(insert, batch)
        written += len(batch)
    log.info("rating snapshot %s for league year %d: %d players", stage, league_year_id, written)
    return {"stage": stage, "players": written}


def _load_stage(conn, league_year_id: int, stage: str) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for r in conn.execute(text("""
        SELECT player_id, age, level, ptype, raw_ovr, displayovr, attrs
        FROM player_rating_snapshots WHERE league_year_id = :ly AND stage = :st
    """), {"ly": int(league_year_id), "st": stage}).mappings().all():
        a = r["attrs"]
        if isinstance(a, (str, bytes)):
            a = json.loads(a)
        out[int(r["player_id"])] = {"age": int(r["age"]), "level": r["level"], "ptype": r["ptype"],
                                    "raw_ovr": _f(r["raw_ovr"]), "displayovr": r["displayovr"],
                                    "bases": a.get("bases", {}), "pots": a.get("pots", {})}
    return out


def compute_curve_stats(conn, league_year_id: int) -> Dict[str, Any]:
    """Realised per-(grade, age) deltas from the pre/post pair of this year."""
    pre = _load_stage(conn, league_year_id, "pre_progression")
    post = _load_stage(conn, league_year_id, "post_progression")
    if not pre or not post:
        return {"rows": 0, "error": "both snapshots are required"}
    table = {(g, int(a)): (float(mn), float(md), float(mx)) for g, a, mn, md, mx in conn.execute(text(
        "SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves")).all()}

    buckets: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    for pid, b in post.items():
        a = pre.get(pid)
        if not a:
            continue
        age = b["age"]
        for col in BASE_COLS:
            v0, v1 = a["bases"].get(col), b["bases"].get(col)
            grade = b["pots"].get(col[:-5] + "_pot")
            if v0 is None or v1 is None or not grade:
                continue
            buckets[(grade, age)].append(float(v1) - float(v0))

    conn.execute(text("DELETE FROM progression_curve_stats WHERE league_year_id = :ly"),
                 {"ly": int(league_year_id)})
    rows = []
    for (grade, age), vals in buckets.items():
        vals.sort()
        t = table.get((grade, age), (None, None, None))
        rows.append({"ly": int(league_year_id), "g": grade, "age": age, "n": len(vals),
                     "mean": round(statistics.fmean(vals), 3), "p10": round(_pct(vals, 0.1), 3),
                     "p50": round(_pct(vals, 0.5), 3), "p90": round(_pct(vals, 0.9), 3),
                     "tmin": t[0], "tmode": t[1], "tmax": t[2]})
    if rows:
        conn.execute(text("""
            INSERT INTO progression_curve_stats
                (league_year_id, grade, age, n, mean_delta, p10, p50, p90, table_min, table_mode, table_max)
            VALUES (:ly, :g, :age, :n, :mean, :p10, :p50, :p90, :tmin, :tmode, :tmax)
        """), rows)
    log.info("progression curve stats for %d: %d (grade, age) cells", league_year_id, len(rows))
    return {"rows": len(rows), "players_paired": sum(1 for p in post if p in pre)}


# ---------------------------------------------------------------------------
# Diagnostics (read-only)
# ---------------------------------------------------------------------------

def snapshot_years(conn) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(text("""
        SELECT s.league_year_id, ly.league_year, s.stage, COUNT(*) AS players, MIN(s.created_at) AS taken_at
        FROM player_rating_snapshots s JOIN league_years ly ON ly.id = s.league_year_id
        GROUP BY s.league_year_id, ly.league_year, s.stage ORDER BY ly.league_year, s.stage
    """)).mappings().all()]


def table_vs_actual(conn, league_year_id: int, grade: Optional[str] = None) -> Dict[str, Any]:
    sql = """
        SELECT grade, age, n, mean_delta, p10, p50, p90, table_min, table_mode, table_max
        FROM progression_curve_stats WHERE league_year_id = :ly
    """
    params: Dict[str, Any] = {"ly": int(league_year_id)}
    if grade:
        sql += " AND grade = :g"
        params["g"] = grade
    sql += " ORDER BY grade, age"
    rows = []
    for r in conn.execute(text(sql), params).mappings().all():
        d = {k: (_f(v) if k not in ("grade", "age", "n") else v) for k, v in r.items()}
        d["age"] = int(d["age"]); d["n"] = int(d["n"])
        # A triangular(min, mode, max) draw averages (min+mode+max)/3, not the
        # mode; that is the number the realised mean has to be compared with.
        if d["table_mode"] is None:
            d["table_mean"] = None
        else:
            d["table_mean"] = round((d["table_min"] + d["table_mode"] + d["table_max"]) / 3.0, 3)
        d["off_by"] = None if d["table_mean"] is None else round(d["mean_delta"] - d["table_mean"], 3)
        d["flag"] = bool(d["off_by"] is not None and abs(d["off_by"]) > 0.75 and d["n"] >= 30)
        rows.append(d)
    grades = sorted({r["grade"] for r in conn.execute(text(
        "SELECT DISTINCT grade FROM progression_curve_stats WHERE league_year_id = :ly"), {"ly": int(league_year_id)}).mappings().all()})
    return {"league_year_id": int(league_year_id), "grade": grade, "grades": grades, "cells": rows,
            "flagged": sum(1 for r in rows if r["flag"])}


def age_profile(conn, level: Optional[int] = None) -> Dict[str, Any]:
    lvl_sql = "AND s.level = :lvl" if level else ""
    params: Dict[str, Any] = {}
    if level:
        params["lvl"] = int(level)
    series = defaultdict(list)
    for r in conn.execute(text(f"""
        SELECT ly.league_year, s.age, COUNT(*) AS n, AVG(s.raw_ovr) AS mean_raw
        FROM player_rating_snapshots s JOIN league_years ly ON ly.id = s.league_year_id
        WHERE s.stage = 'post_progression' AND s.raw_ovr IS NOT NULL {lvl_sql}
        GROUP BY ly.league_year, s.age ORDER BY ly.league_year, s.age
    """), params).mappings().all():
        series[int(r["league_year"])].append({"age": int(r["age"]), "n": int(r["n"]),
                                              "mean_raw": round(float(r["mean_raw"]), 2)})
    declined = []
    for r in conn.execute(text(f"""
        SELECT ly.league_year, b.age,
               COUNT(*) AS n,
               SUM(b.raw_ovr < a.raw_ovr) AS declined,
               AVG(b.raw_ovr - a.raw_ovr) AS mean_delta
        FROM player_rating_snapshots a
        JOIN player_rating_snapshots b ON b.player_id = a.player_id AND b.league_year_id = a.league_year_id
             AND b.stage = 'post_progression'
        JOIN league_years ly ON ly.id = a.league_year_id
        WHERE a.stage = 'pre_progression' AND a.raw_ovr IS NOT NULL AND b.raw_ovr IS NOT NULL
              {lvl_sql.replace('s.level', 'b.level')}
        GROUP BY ly.league_year, b.age ORDER BY ly.league_year, b.age
    """), params).mappings().all():
        declined.append({"league_year": int(r["league_year"]), "age": int(r["age"]), "n": int(r["n"]),
                         "share_declined": round(float(r["declined"]) / float(r["n"]), 3) if r["n"] else None,
                         "mean_delta": round(float(r["mean_delta"]), 3)})
    peaks = {}
    for yr, pts in series.items():
        if pts:
            best = max(pts, key=lambda p: p["mean_raw"] if p["n"] >= 20 else -1e9)
            peaks[yr] = best["age"]
    return {"level": level, "series": dict(series), "peak_age": peaks, "deltas": declined}


def drift(conn) -> Dict[str, Any]:
    rows = conn.execute(text("""
        SELECT ly.league_year, s.stage, s.level, s.raw_ovr
        FROM player_rating_snapshots s JOIN league_years ly ON ly.id = s.league_year_id
        WHERE s.raw_ovr IS NOT NULL
    """)).all()
    groups: Dict[Tuple[int, str, Optional[int]], List[float]] = defaultdict(list)
    for yr, stage, lvl, raw in rows:
        groups[(int(yr), str(stage), None if lvl is None else int(lvl))].append(float(raw))
    out = []
    for (yr, stage, lvl), vals in sorted(groups.items(), key=lambda k: (k[0][0], k[0][1], k[0][2] or 0)):
        vals.sort()
        out.append({"league_year": yr, "stage": stage, "level": lvl, "n": len(vals),
                    "mean": round(statistics.fmean(vals), 2), "sd": round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0.0,
                    "p25": round(_pct(vals, 0.25), 2), "p50": round(_pct(vals, 0.5), 2), "p75": round(_pct(vals, 0.75), 2)})
    return {"rows": out}


def outliers(conn, league_year_id: int, n: int = 25) -> Dict[str, Any]:
    rows = conn.execute(text("""
        SELECT a.player_id, p.firstName, p.lastName, p.ptype, b.age, b.level, b.org_id, o.org_abbrev,
               a.raw_ovr AS raw_pre, b.raw_ovr AS raw_post, (b.raw_ovr - a.raw_ovr) AS delta
        FROM player_rating_snapshots a
        JOIN player_rating_snapshots b ON b.player_id = a.player_id AND b.league_year_id = a.league_year_id
             AND b.stage = 'post_progression'
        JOIN simbbPlayers p ON p.id = a.player_id
        LEFT JOIN organizations o ON o.id = b.org_id
        WHERE a.league_year_id = :ly AND a.stage = 'pre_progression'
          AND a.raw_ovr IS NOT NULL AND b.raw_ovr IS NOT NULL
    """), {"ly": int(league_year_id)}).mappings().all()
    if not rows:
        return {"league_year_id": int(league_year_id), "gainers": [], "losers": [], "cohorts": 0}
    cohorts: Dict[Tuple[int, Optional[int]], List[float]] = defaultdict(list)
    for r in rows:
        cohorts[(int(r["age"]), None if r["level"] is None else int(r["level"]))].append(float(r["delta"]))
    stats = {k: (statistics.fmean(v), statistics.pstdev(v) if len(v) > 1 else 1.0) for k, v in cohorts.items()}
    items = []
    for r in rows:
        key = (int(r["age"]), None if r["level"] is None else int(r["level"]))
        mean, sd = stats[key]
        d = float(r["delta"])
        z = (d - mean) / sd if sd > 1e-9 else 0.0
        items.append({"player_id": int(r["player_id"]), "name": f"{r['firstName']} {r['lastName']}",
                      "ptype": r["ptype"], "age": int(r["age"]), "level": r["level"],
                      "org": r["org_abbrev"], "raw_pre": round(float(r["raw_pre"]), 2),
                      "raw_post": round(float(r["raw_post"]), 2), "delta": round(d, 2),
                      "cohort_mean": round(mean, 2), "z": round(z, 2)})
    items.sort(key=lambda x: x["delta"])
    return {"league_year_id": int(league_year_id), "cohorts": len(cohorts),
            "losers": items[:n], "gainers": list(reversed(items[-n:]))}


def _table_exists(conn, name: str) -> bool:
    try:
        conn.execute(text(f"SELECT 1 FROM {name} LIMIT 1"))
        return True
    except Exception:
        return False


def player_trajectory(conn, player_id: int) -> Dict[str, Any]:
    snaps = conn.execute(text("""
        SELECT s.league_year_id, ly.league_year, s.stage, s.age, s.level, s.org_id, o.org_abbrev,
               s.raw_ovr, s.displayovr, s.attrs, s.created_at
        FROM player_rating_snapshots s
        JOIN league_years ly ON ly.id = s.league_year_id
        LEFT JOIN organizations o ON o.id = s.org_id
        WHERE s.player_id = :pid ORDER BY ly.league_year, s.stage
    """), {"pid": int(player_id)}).mappings().all()
    p = conn.execute(text(
        "SELECT id, firstName, lastName, age, ptype, displayovr FROM simbbPlayers WHERE id = :pid"
    ), {"pid": int(player_id)}).mappings().first()
    if not p:
        raise ValueError("player not found")
    table = {(g, int(a)): (float(mn), float(md), float(mx)) for g, a, mn, md, mx in conn.execute(text(
        "SELECT grade, age, prog_min, prog_mode, prog_max FROM growth_curves")).all()}
    camp = {}
    if _table_exists(conn, "training_camp_results"):
        for r in conn.execute(text("""
            SELECT league_year_id, attr, intensity, steps, backfired, base_grade, effective_grade
            FROM training_camp_results WHERE player_id = :pid""" ), {"pid": int(player_id)}).mappings().all():
            camp[int(r["league_year_id"])] = {k: (int(v) if k in ("steps", "backfired") else v) for k, v in r.items() if k != "league_year_id"}

    seasons: List[Dict[str, Any]] = []
    by_year: Dict[int, Dict[str, Any]] = {}
    for s in snaps:
        a = s["attrs"]
        if isinstance(a, (str, bytes)):
            a = json.loads(a)
        y = by_year.setdefault(int(s["league_year_id"]), {"league_year_id": int(s["league_year_id"]),
                                                          "league_year": int(s["league_year"]),
                                                          "camp": camp.get(int(s["league_year_id"]))})
        y[s["stage"]] = {"age": int(s["age"]), "level": s["level"], "org": s["org_abbrev"],
                         "raw_ovr": _f(s["raw_ovr"]), "displayovr": s["displayovr"],
                         "bases": a.get("bases", {}), "pots": a.get("pots", {})}
    for ly_id in sorted(by_year, key=lambda k: by_year[k]["league_year"]):
        y = by_year[ly_id]
        pre, post = y.get("pre_progression"), y.get("post_progression")
        attrs = []
        if pre and post:
            age = post["age"]
            for col in BASE_COLS:
                v0, v1 = pre["bases"].get(col), post["bases"].get(col)
                grade = post["pots"].get(col[:-5] + "_pot")
                band = table.get((grade, age)) if grade else None
                delta = None if v0 is None or v1 is None else round(float(v1) - float(v0), 2)
                attrs.append({"attr": col[:-5], "grade": grade, "pre": v0, "post": v1, "delta": delta,
                              "band": None if not band else {"min": band[0], "mode": band[1], "max": band[2]},
                              "outside_band": bool(band and delta is not None and
                                                   (delta < band[0] - 0.01 or delta > band[2] + 0.01))})
        camp_snap = y.get("post_camp")
        seasons.append({"league_year_id": ly_id, "league_year": y["league_year"], "camp": y["camp"],
                        "post_camp": None if not camp_snap else {k: camp_snap[k] for k in ("age", "level", "org", "raw_ovr", "displayovr")},
                        "pre": None if not pre else {k: pre[k] for k in ("age", "level", "org", "raw_ovr", "displayovr")},
                        "post": None if not post else {k: post[k] for k in ("age", "level", "org", "raw_ovr", "displayovr")},
                        "attributes": attrs})
    return {"player": {"id": int(p["id"]), "name": f"{p['firstName']} {p['lastName']}", "age": p["age"],
                       "ptype": p["ptype"], "displayovr": p["displayovr"]},
            "seasons": seasons}


def camp_effects(conn, league_year_id: int) -> Dict[str, Any]:
    """
    What the preseason camp of ``league_year_id`` did to ratings: the
    applied delta per focus column (replayed die at the shifted grade minus
    the same die at the natural grade), by intensity/outcome and by age band.
    """
    empty = {"league_year_id": int(league_year_id), "players": 0, "by_outcome": {}, "by_age": []}
    if not _table_exists(conn, "training_camp_results"):
        return empty
    try:
        rows = conn.execute(text("""
            SELECT player_id, intensity, steps, backfired, effect
            FROM training_camp_results WHERE league_year_id = :ly
        """), {"ly": int(league_year_id)}).mappings().all()
    except Exception:
        return empty
    by_outcome: Dict[str, List[float]] = defaultdict(list)
    by_outcome_players: Dict[str, int] = defaultdict(int)
    by_outcome_zero: Dict[str, int] = defaultdict(int)
    bands = (("<=22", 0, 22), ("23-25", 23, 25), ("26-28", 26, 28), ("29+", 29, 999))
    by_age: Dict[str, List[float]] = defaultdict(list)
    players = 0
    for r in rows:
        e = r["effect"]
        if isinstance(e, (str, bytes)):
            e = json.loads(e)
        if not e:
            continue
        players += 1
        key = r["intensity"] + (":backfired" if r["backfired"] else ":success")
        deltas = [float(v) for v in (e.get("deltas") or {}).values()]
        by_outcome_players[key] += 1
        if not any(abs(v) > 1e-9 for v in deltas):
            by_outcome_zero[key] += 1
        by_outcome[key].extend(deltas)
        age = int(e.get("age") or 0)
        for label, lo, hi in bands:
            if lo <= age <= hi:
                by_age[label].extend(deltas)
                break

    def _agg(v: List[float]) -> Dict[str, Any]:
        if not v:
            return {"n": 0, "mean": None, "min": None, "max": None}
        return {"n": len(v), "mean": round(statistics.fmean(v), 3),
                "min": round(min(v), 3), "max": round(max(v), 3)}

    out = {}
    for key in sorted(by_outcome_players):
        out[key] = {"players": by_outcome_players[key], "no_effect": by_outcome_zero[key],
                    **_agg(by_outcome[key])}
    return {"league_year_id": int(league_year_id), "players": players, "by_outcome": out,
            "by_age": [{"band": label, **_agg(by_age[label])} for label, _, _ in bands]}
