# admin/routes_timeline.py — one document for the Timeline view.
"""
GET /admin/timeline?league_year_id=L&league_level=9
GET /admin/logs?name=timing|sim_failures&lines=400
"""

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from flask import jsonify, request
from sqlalchemy import text

from admin import admin_bp, _require_admin

log = logging.getLogger(__name__)

POSTSEASON_WEEKS_GUESS = 8
ROUND_ORDER = ["WC", "WILD_CARD", "DS", "DIVISION", "CS", "CHAMPIONSHIP", "WS", "WORLD_SERIES",
               "REGIONAL", "SUPER_REGIONAL", "CWS", "CWS_FINAL", "FINAL"]


def _engine():
    from db import get_engine
    return get_engine()


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@admin_bp.get("/timeline")
def admin_timeline():
    guard = _require_admin()
    if guard:
        return guard
    eng = _engine()
    lyid = request.args.get("league_year_id", type=int)
    level = request.args.get("league_level", 9, type=int)
    if request.args.get("league_level") in ("all", "0", ""):
        level = None

    from services.timestamp import get_enhanced_timestamp
    ts = get_enhanced_timestamp() or {}

    with eng.connect() as conn:
        if not lyid:
            lyid = conn.execute(text("SELECT current_league_year_id FROM league_state WHERE id = 1")).scalar() \
                or ts.get("LeagueYearID")
        if not lyid:
            return jsonify(ok=False, error="no_league_year", message="No league year could be resolved"), 404
        ly = conn.execute(text("SELECT id, league_year, weeks_in_season, season_ended_at FROM league_years WHERE id=:i"),
                          {"i": lyid}).mappings().first()
        if not ly:
            return jsonify(ok=False, error="not_found", message=f"league_year_id {lyid} not found"), 404
        year = int(ly["league_year"])
        weeks_in_season = int(ly["weeks_in_season"] or 52)
        is_current = bool(ts.get("Season") == year)

        lvl_sql = " AND league_level = :lvl" if level else ""
        p = {"season": year, "lvl": level}

        sched = conn.execute(text(f"""
            SELECT season_week AS w, season_subweek AS sw, game_type, COUNT(*) AS n
            FROM gamelist WHERE season = :season{lvl_sql}
            GROUP BY season_week, season_subweek, game_type"""), p).mappings().all()
        played = conn.execute(text(f"""
            SELECT season_week AS w, season_subweek AS sw, game_type, COUNT(*) AS n, MAX(completed_at) AS last_at
            FROM game_results WHERE season = :season{lvl_sql}
            GROUP BY season_week, season_subweek, game_type"""), p).mappings().all()
        gws = conn.execute(text("SELECT week_index, label, books_run_at, injuries_ticked_at FROM game_weeks WHERE league_year_id=:i"),
                           {"i": lyid}).mappings().all()
        series = conn.execute(text("""
            SELECT round, status, start_week, series_length, wins_a, wins_b, league_level, COUNT(*) AS n
            FROM playoff_series WHERE league_year_id=:i AND (:lvl IS NULL OR league_level=:lvl)
            GROUP BY round, status, start_week, series_length, wins_a, wins_b, league_level"""),
            {"i": lyid, "lvl": level}).mappings().all()
        rec = conn.execute(text("SELECT current_week, status FROM recruiting_state WHERE league_year_id=:i"), {"i": lyid}).mappings().first()
        ifa = conn.execute(text("SELECT current_week, total_weeks, status FROM ifa_state WHERE league_year_id=:i"), {"i": lyid}).mappings().first()
        drf = conn.execute(text("SELECT phase, current_round, current_pick, total_rounds FROM draft_state WHERE league_year_id=:i"), {"i": lyid}).mappings().first()
        # Also the *next* league year's market state (offseason of Y rolls into Y+1 tables)
        nxt_ly = conn.execute(text("SELECT id, league_year FROM league_years WHERE league_year=:y"), {"y": year + 1}).mappings().first()
        rec_n = ifa_n = drf_n = None
        if nxt_ly:
            rec_n = conn.execute(text("SELECT current_week, status FROM recruiting_state WHERE league_year_id=:i"), {"i": nxt_ly["id"]}).mappings().first()
            ifa_n = conn.execute(text("SELECT current_week, total_weeks, status FROM ifa_state WHERE league_year_id=:i"), {"i": nxt_ly["id"]}).mappings().first()
            drf_n = conn.execute(text("SELECT phase, current_round, current_pick, total_rounds FROM draft_state WHERE league_year_id=:i"), {"i": nxt_ly["id"]}).mappings().first()

    # ---- weeks ----
    weeks: Dict[int, Dict[str, Any]] = {}
    max_week = weeks_in_season
    for r in sched:
        max_week = max(max_week, int(r["w"] or 0))
    for r in played:
        max_week = max(max_week, int(r["w"] or 0))
    for w in range(1, max_week + 1):
        weeks[w] = {"week": w, "scheduled": 0, "played": 0, "subweeks": {k: {"scheduled": 0, "played": 0} for k in "abcd"},
                    "types": defaultdict(int), "postseason": w > weeks_in_season, "last_played_at": None}
    for r in sched:
        w = int(r["w"] or 0)
        if w in weeks:
            weeks[w]["scheduled"] += int(r["n"])
            sw = (r["sw"] or "").lower()
            if sw in weeks[w]["subweeks"]:
                weeks[w]["subweeks"][sw]["scheduled"] += int(r["n"])
            weeks[w]["types"][r["game_type"] or "regular"] += int(r["n"])
            if (r["game_type"] or "regular") == "playoff":
                weeks[w]["postseason"] = True
    for r in played:
        w = int(r["w"] or 0)
        if w in weeks:
            weeks[w]["played"] += int(r["n"])
            sw = (r["sw"] or "").lower()
            if sw in weeks[w]["subweeks"]:
                weeks[w]["subweeks"][sw]["played"] += int(r["n"])
            la = r["last_at"]
            if la and (weeks[w]["last_played_at"] is None or la > weeks[w]["last_played_at"]):
                weeks[w]["last_played_at"] = la
    for g in gws:
        w = int(g["week_index"] or 0)
        if w in weeks:
            weeks[w]["label"] = g["label"]
            weeks[w]["books_run_at"] = _iso(g["books_run_at"])
            weeks[w]["injuries_ticked_at"] = _iso(g["injuries_ticked_at"])
    for w in weeks.values():
        w["types"] = dict(w["types"])
        w["last_played_at"] = _iso(w["last_played_at"])
        if w["scheduled"] == 0:
            w["state"] = "empty"
        elif w["played"] >= w["scheduled"]:
            w["state"] = "played"
        elif w["played"] > 0:
            w["state"] = "partial"
        else:
            w["state"] = "scheduled"

    # ---- job runs per week (from summaries) ----
    runs_by_week: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    try:
        from services.job_scheduler import list_runs
        for run in list_runs(eng, limit=400):
            s = run.get("summary") or {}
            w = s.get("week") or s.get("from_week")
            if w and int(w) in weeks and (not s.get("league_year_id") or int(s["league_year_id"]) == int(lyid)):
                runs_by_week[int(w)].append({"run_id": run["id"], "job_type": run["job_type"], "status": run["status"],
                                             "finished_at": run.get("finished_at"), "subweek": s.get("subweek")})
    except Exception as e:  # noqa: BLE001
        log.warning("timeline: runs failed: %s", e)
    for w, lst in runs_by_week.items():
        weeks[w]["job_runs"] = lst

    # ---- postseason rounds ----
    rounds: Dict[str, Dict[str, Any]] = {}
    for r in series:
        key = r["round"] or "?"
        d = rounds.setdefault(key, {"round": key, "series": 0, "complete": 0, "in_progress": 0, "pending": 0,
                                    "start_week": r["start_week"], "levels": set()})
        d["series"] += int(r["n"])
        st = (r["status"] or "").lower()
        if st in ("complete", "completed", "done"):
            d["complete"] += int(r["n"])
        elif st in ("in_progress", "active", "playing"):
            d["in_progress"] += int(r["n"])
        else:
            d["pending"] += int(r["n"])
        d["levels"].add(int(r["league_level"]))
    round_list = []
    for d in rounds.values():
        d["levels"] = sorted(d["levels"])
        d["status"] = "complete" if d["complete"] == d["series"] else ("in_progress" if d["in_progress"] or d["complete"] else "pending")
        round_list.append(d)
    round_list.sort(key=lambda d: (d["start_week"] or 999, ROUND_ORDER.index(d["round"]) if d["round"] in ROUND_ORDER else 99))

    # ---- offseason checklist ----
    checklist = None
    try:
        from admin import _build_offseason_checklist
        with eng.connect() as conn:
            checklist = _build_offseason_checklist(conn, int(lyid))
    except Exception as e:  # noqa: BLE001
        log.warning("timeline: checklist failed: %s", e)

    market = {
        "fa": {"round": ts.get("FreeAgencyRound"), "locked": ts.get("IsFreeAgencyLocked")} if is_current or ts.get("IsOffSeason") else None,
        "draft": dict(drf_n or drf) if (drf_n or drf) else None,
        "ifa": dict(ifa_n or ifa) if (ifa_n or ifa) else None,
        "recruiting": dict(rec_n or rec) if (rec_n or rec) else None,
        "next_league_year": dict(nxt_ly) if nxt_ly else None,
    }
    for k in ("draft", "ifa", "recruiting"):
        if market[k]:
            for kk, vv in list(market[k].items()):
                if hasattr(vv, "isoformat"):
                    market[k][kk] = _iso(vv)

    # ---- schedule projection ----
    scheduled, projection = _projection(eng, ts, weeks_in_season, max_week, is_current)

    now = {
        "is_current_year": is_current,
        "phase": ts.get("Phase"),
        "week": ts.get("Week"),
        "subweeks": {"a": bool(ts.get("GamesARan")), "b": bool(ts.get("GamesBRan")),
                     "c": bool(ts.get("GamesCRan")), "d": bool(ts.get("GamesDRan"))},
        "run_games": bool(ts.get("RunGames")),
        "total_weeks": ts.get("TotalWeeks"),
    }
    return jsonify(ok=True, league_year={"id": int(lyid), "year": year, "weeks_in_season": weeks_in_season,
                                         "season_ended_at": _iso(ly["season_ended_at"])},
                   league_level=level, now=now, weeks=[weeks[w] for w in sorted(weeks)],
                   postseason={"rounds": round_list, "first_week": weeks_in_season + 1},
                   offseason=checklist, market=market, scheduled=scheduled, projection=projection)


def _projection(eng, ts, weeks_in_season: int, max_week: int, is_current: bool):
    """Next fires for enabled jobs + a week->date projection from the sim cadence job."""
    scheduled: List[Dict[str, Any]] = []
    projection: Optional[Dict[str, Any]] = None
    try:
        from services.job_scheduler import list_job_defs, cron_fire_times, utcnow, _parse_dt, DEFAULT_TZ
        jobs = [j for j in list_job_defs(eng) if j["enabled"] and j.get("next_run_at")]
        sim_job = None
        for j in jobs:
            fires: List[datetime] = []
            tzname = j.get("timezone") or DEFAULT_TZ
            if j["schedule_kind"] == "cron" and j.get("cron_expr"):
                fires = cron_fire_times(j["cron_expr"], tzname, 400)
            elif j["schedule_kind"] == "interval" and j.get("interval_s"):
                t = _parse_dt(j["next_run_at"])
                for _ in range(400):
                    fires.append(t)
                    t = t + timedelta(seconds=int(j["interval_s"]))
            elif j["schedule_kind"] == "once":
                t = _parse_dt(j["next_run_at"])
                if t:
                    fires.append(t)
            scheduled.append({"job_id": j["id"], "name": j["name"], "job_type": j["job_type"],
                              "fires": [_iso(f) for f in fires[:30]], "timezone": tzname})
            if sim_job is None and j["job_type"] in ("sim_next_subweek", "run_week") and fires:
                sim_job = (j, fires)
        if sim_job and is_current and ts.get("Phase") == "REGULAR_SEASON":
            j, fires = sim_job
            tz = ZoneInfo(j.get("timezone") or DEFAULT_TZ)
            per_fire = 4 if j["job_type"] == "run_week" else 1
            week = int(ts.get("Week") or 1)
            done = sum(1 for k in ("GamesARan", "GamesBRan", "GamesCRan", "GamesDRan") if ts.get(k))
            # subweek slots remaining in current week
            remaining = 4 - done
            week_dates: Dict[str, str] = {}
            i = 0
            horizon = max(max_week, weeks_in_season + POSTSEASON_WEEKS_GUESS)
            cur_week = week
            slots_left = remaining
            while cur_week <= horizon and i < len(fires):
                if str(cur_week) not in week_dates and (cur_week != week or done == 0):
                    week_dates[str(cur_week)] = fires[i].replace(tzinfo=timezone.utc).astimezone(tz).date().isoformat()
                elif cur_week == week and done > 0:
                    week_dates.setdefault(str(cur_week), "in progress")
                slots_left -= per_fire
                i += 1
                if slots_left <= 0:
                    cur_week += 1
                    slots_left = 4
            projection = {
                "basis": f"{j['name']} ({'1 week' if per_fire == 4 else '1 subweek'} per fire)",
                "job_id": j["id"],
                "week_dates": week_dates,
                "regular_season_end": week_dates.get(str(weeks_in_season)),
                "postseason_start": week_dates.get(str(weeks_in_season + 1)),
            }
    except Exception as e:  # noqa: BLE001
        log.warning("timeline: projection failed: %s", e)
    return scheduled, projection


@admin_bp.get("/logs")
def admin_logs():
    guard = _require_admin()
    if guard:
        return guard
    name = request.args.get("name", "timing")
    lines = min(5000, request.args.get("lines", 400, type=int))
    files = {"timing": "timing_log.txt", "sim_failures": "sim_failures.log"}
    fn = files.get(name)
    if not fn:
        return jsonify(ok=False, error="unknown_log", available=list(files)), 400
    path = os.path.join(os.getcwd(), fn)
    if not os.path.exists(path):
        return jsonify(ok=True, name=name, path=path, exists=False, lines=[], size=0)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            # read the tail (up to ~2MB) then split
            f.seek(max(0, size - 2_000_000))
            data = f.read().decode("utf-8", errors="replace")
        out = data.splitlines()[-lines:]
        return jsonify(ok=True, name=name, path=path, exists=True, size=size, lines=out)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error="read_failed", message=str(e)), 500
