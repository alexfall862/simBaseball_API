# admin/routes_summary.py — one read for the Command Center.
"""
GET /admin/summary
{
  timestamp: <enhanced timestamp>,
  tasks: {running: n, pending: n, items: [...up to 8 active]},
  scheduler: <get_scheduler_status>,
  alerts: [{kind, level, title, detail, action:{area, tab, params}}],
  checklist: {league_year_id, next_step: {...}} | null,
  trades_awaiting: n,
  db: {ok: bool, latency_ms}
}
POST /admin/sim/clear-run-games   clears a stuck timestamp_state.run_games flag
"""

import logging
import time

from flask import jsonify
from sqlalchemy import text

from admin import admin_bp, _require_admin

log = logging.getLogger(__name__)


def _engine():
    from db import get_engine
    return get_engine()


@admin_bp.get("/summary")
def admin_summary():
    guard = _require_admin()
    if guard:
        return guard
    eng = _engine()
    out = {"ok": True, "alerts": []}

    # DB ping
    t0 = time.monotonic()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        out["db"] = {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        out["db"] = {"ok": False, "error": str(e)}
        out["alerts"].append({"kind": "db", "level": "danger", "title": "Database unreachable", "detail": str(e)})

    # Timestamp
    ts = None
    try:
        from services.timestamp import get_enhanced_timestamp
        ts = get_enhanced_timestamp()
    except Exception as e:  # noqa: BLE001
        log.warning("summary: timestamp failed: %s", e)
    out["timestamp"] = ts

    # Tasks
    active = []
    try:
        from services.task_store import get_task_store
        tasks = get_task_store().list_tasks()
        active = [t for t in tasks if str(t.get("status", "")).lower() in ("running", "pending")]
        out["tasks"] = {"running": sum(1 for t in active if str(t["status"]).lower() == "running"),
                        "pending": sum(1 for t in active if str(t["status"]).lower() == "pending"),
                        "items": active[:8]}
    except Exception as e:  # noqa: BLE001
        out["tasks"] = {"running": 0, "pending": 0, "items": [], "error": str(e)}

    # Scheduler
    try:
        from services.job_scheduler import get_scheduler_status
        sched = get_scheduler_status(eng)
        out["scheduler"] = sched
        if sched.get("failed_24h"):
            out["alerts"].append({"kind": "jobs", "level": "danger",
                                  "title": f"{sched['failed_24h']} job run(s) failed in the last 24h",
                                  "detail": "Open Run History to see the error and re-run.",
                                  "action": {"area": "jobs", "tab": "runs", "params": {"status": "failed"}}})
        if sched.get("enabled") and not sched.get("leader_alive"):
            out["alerts"].append({"kind": "jobs", "level": "warning", "title": "Scheduler is enabled but no runner is alive",
                                  "detail": "No process has ticked recently. Check JOB_SCHEDULER_DISABLED and the app logs.",
                                  "action": {"area": "jobs", "tab": "scheduled"}})
    except Exception as e:  # noqa: BLE001
        out["scheduler"] = None
        log.warning("summary: scheduler status failed: %s", e)

    # Stuck RunGames
    if ts and ts.get("RunGames") and not any(str(t.get("status", "")).lower() == "running" for t in active):
        running_jobs = (out.get("scheduler") or {}).get("running", 0)
        if not running_jobs:
            out["alerts"].append({"kind": "run_games", "level": "warning",
                                  "title": "RunGames flag is set but nothing is running",
                                  "detail": "A simulation probably crashed mid-run. Clear the flag to re-enable sim buttons.",
                                  "action": {"area": "season", "tab": "simulate"}, "clearable": True})

    # Trades awaiting approval
    try:
        with eng.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM trade_proposals WHERE status = 'counterparty_accepted'")).scalar()
        out["trades_awaiting"] = int(n or 0)
        if n:
            out["alerts"].append({"kind": "trades", "level": "info", "title": f"{n} trade(s) awaiting admin approval",
                                  "detail": "Both sides accepted; approve or reject in Market › Trades.",
                                  "action": {"area": "market", "tab": "trades"}})
    except Exception:  # noqa: BLE001
        out["trades_awaiting"] = None

    # Offseason checklist (next pending step) when not in regular season
    out["checklist"] = None
    try:
        if ts and ts.get("Phase") != "REGULAR_SEASON" or (ts and _mlb_ws_done(eng, ts)):
            from admin import _build_offseason_checklist
            lyid = None
            with eng.connect() as conn:
                try:
                    lyid = conn.execute(text("SELECT current_league_year_id FROM league_state WHERE id = 1")).scalar()
                except Exception:  # noqa: BLE001
                    lyid = None
                if not lyid and ts and ts.get("LeagueYearID"):
                    lyid = ts["LeagueYearID"]
                if lyid:
                    data = _build_offseason_checklist(conn, int(lyid))
                    steps = data.get("steps", [])
                    nxt = next((s for s in steps if s.get("done") is not True and not s.get("not_built")), None)
                    out["checklist"] = {"league_year_id": data.get("league_year_id"), "league_year": data.get("league_year"),
                                        "done": sum(1 for s in steps if s.get("done") is True), "total": len(steps),
                                        "next_step": nxt}
                    if nxt:
                        out["alerts"].append({"kind": "checklist", "level": "info",
                                              "title": f"Offseason step {nxt.get('order')}: {nxt.get('title')}",
                                              "detail": (nxt.get("detail") or "")[:200],
                                              "action": {"area": "season", "tab": "checklist"}})
    except Exception as e:  # noqa: BLE001
        log.warning("summary: checklist failed: %s", e)

    return jsonify(out)


def _mlb_ws_done(eng, ts) -> bool:
    try:
        from services.timestamp import _mlb_postseason_complete
        return bool(_mlb_postseason_complete(ts.get("Season", 0)))
    except Exception:  # noqa: BLE001
        return False


@admin_bp.post("/sim/clear-run-games")
def admin_clear_run_games():
    """Clear a stuck RunGames flag (the sim crashed mid-run). Refuses while a run/task is active."""
    guard = _require_admin()
    if guard:
        return guard
    eng = _engine()
    try:
        from services.task_store import get_task_store
        if any(str(t.get("status", "")).lower() == "running" for t in get_task_store().list_tasks()):
            return jsonify(ok=False, error="busy", message="A background task is still running."), 409
    except Exception:  # noqa: BLE001
        pass
    try:
        with eng.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM job_runs WHERE status='running'")).scalar()
        if n:
            return jsonify(ok=False, error="busy", message=f"{n} job run(s) still running."), 409
    except Exception:  # noqa: BLE001
        pass
    from services.timestamp import set_run_games
    ok = set_run_games(False, broadcast=True)
    log.warning("admin cleared RunGames flag")
    return jsonify(ok=bool(ok))
