# services/job_scheduler.py
"""
Scheduled jobs runner.

Tables:  scheduled_jobs (definitions), job_runs (every execution),
         scheduler_state (leader + last tick, one row).

Model (mirrors services/draft_clock.py):
  * One daemon thread per process; MySQL GET_LOCK('simbb_job_scheduler') elects
    exactly one leader per database.  Followers retry every 15s.
  * The leader ticks every JOB_SCHEDULER_TICK_S (20s):
      1. reap runs whose heartbeat is stale  -> failed ("runner lost")
      2. if timestamp_state.run_cron is on, claim due scheduled jobs
         (atomic UPDATE ... WHERE next_run_at <= now) and queue a run
      3. pick queued runs (manual + scheduled, FIFO) and execute them on a
         small thread pool
  * Manual "run now" from the API inserts a queued run.  If no leader has
    ticked recently the API executes it inline in a worker thread; the
    queued->running claim is atomic so a run can never execute twice.

Env: JOB_SCHEDULER_DISABLED=1, JOB_SCHEDULER_TICK_S, JOB_SCHEDULER_WORKERS,
     JOB_SCHEDULER_STALE_S (default 600).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from services.jobs import (JobCancelled, JobContext, JobSkipped, apply_defaults, get_job,
                           list_jobs)

log = logging.getLogger("job_scheduler")

_LOCK_NAME = "simbb_job_scheduler"
_TICK_S = float(os.getenv("JOB_SCHEDULER_TICK_S", "20"))
_FOLLOWER_RETRY_S = 15.0
_WORKERS = int(os.getenv("JOB_SCHEDULER_WORKERS", "2"))
_STALE_S = int(os.getenv("JOB_SCHEDULER_STALE_S", "600"))
_HEARTBEAT_S = 15.0
_LEADER_FRESH_S = 90  # API treats the leader as alive if it ticked within this

_started = False
_start_lock = threading.Lock()
_schema_ready = False
_schema_lock = threading.Lock()
_WHO = f"{socket.gethostname()}:{os.getpid()}"

DEFAULT_TZ = os.getenv("JOB_SCHEDULER_TZ", "America/New_York")

RUN_TERMINAL = ("succeeded", "failed", "skipped", "cancelled")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS scheduled_jobs (
      id            INT AUTO_INCREMENT PRIMARY KEY,
      name          VARCHAR(120) NOT NULL,
      job_type      VARCHAR(64)  NOT NULL,
      params_json   TEXT NULL,
      schedule_kind VARCHAR(16)  NOT NULL DEFAULT 'manual',
      cron_expr     VARCHAR(64)  NULL,
      interval_s    INT NULL,
      run_at        DATETIME NULL,
      timezone      VARCHAR(64)  NOT NULL DEFAULT 'America/New_York',
      enabled       TINYINT(1)   NOT NULL DEFAULT 1,
      guards_json   TEXT NULL,
      next_run_at   DATETIME NULL,
      last_run_at   DATETIME NULL,
      last_status   VARCHAR(16)  NULL,
      runs_count    INT NOT NULL DEFAULT 0,
      created_at    DATETIME NOT NULL,
      updated_at    DATETIME NOT NULL,
      INDEX idx_sj_due (enabled, next_run_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_runs (
      id               INT AUTO_INCREMENT PRIMARY KEY,
      job_id           INT NULL,
      job_type         VARCHAR(64) NOT NULL,
      params_json      TEXT NULL,
      trigger_kind     VARCHAR(16) NOT NULL,
      status           VARCHAR(16) NOT NULL,
      skip_reason      VARCHAR(255) NULL,
      claimed_by       VARCHAR(64) NULL,
      heartbeat_at     DATETIME NULL,
      queued_at        DATETIME NOT NULL,
      started_at       DATETIME NULL,
      finished_at      DATETIME NULL,
      progress         INT NOT NULL DEFAULT 0,
      total            INT NOT NULL DEFAULT 0,
      stage            VARCHAR(255) NULL,
      cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
      task_id          VARCHAR(32) NULL,
      summary_json     MEDIUMTEXT NULL,
      log_text         MEDIUMTEXT NULL,
      error            TEXT NULL,
      INDEX idx_jr_job (job_id, queued_at),
      INDEX idx_jr_status (status, heartbeat_at),
      INDEX idx_jr_queued (status, queued_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_state (
      id            TINYINT PRIMARY KEY,
      leader        VARCHAR(64) NULL,
      last_tick_at  DATETIME NULL,
      started_at    DATETIME NULL
    )
    """,
]


def ensure_schema(engine) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with engine.begin() as conn:
            for ddl in _DDL:
                conn.execute(text(ddl))
            conn.execute(text("INSERT IGNORE INTO scheduler_state (id) VALUES (1)"))
        _schema_ready = True


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(microsecond=0)
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def compute_next_run(schedule_kind: str, cron_expr: Optional[str], interval_s: Optional[int],
                     run_at: Optional[datetime], tz_name: str, after: Optional[datetime] = None) -> Optional[datetime]:
    """Return the next fire time as naive UTC, or None for manual/one-off done."""
    now = after or utcnow()
    if schedule_kind == "manual":
        return None
    if schedule_kind == "once":
        if run_at is None:
            return None
        return run_at if run_at > now else None
    if schedule_kind == "interval":
        if not interval_s or interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        return now + timedelta(seconds=int(interval_s))
    if schedule_kind == "cron":
        if not cron_expr:
            raise ValueError("cron_expr is required for cron schedules")
        from croniter import croniter
        if not croniter.is_valid(cron_expr):
            raise ValueError(f"invalid cron expression '{cron_expr}'")
        return _cron_next_utc(cron_expr, tz_name or DEFAULT_TZ, now)
    raise ValueError(f"unknown schedule_kind '{schedule_kind}'")


def _cron_next_utc(cron_expr: str, tz_name: str, after_utc: datetime) -> datetime:
    """Next fire after `after_utc` (naive UTC) for a cron evaluated on the wall clock of tz_name.

    croniter keeps the UTC offset of an aware base datetime across a DST change
    (a 06:00 job would fire at 05:00 on the switch day), so we iterate on naive
    local wall-clock time and re-localize the result.
    """
    from croniter import croniter
    tz = ZoneInfo(tz_name)
    base_local = after_utc.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)
    nxt_local = croniter(cron_expr, base_local).get_next(datetime)
    return _to_utc_naive(nxt_local.replace(tzinfo=tz))


def cron_fire_times(cron_expr: str, tz_name: str, n: int, after_utc: Optional[datetime] = None) -> List[datetime]:
    """n successive fire times (naive UTC), DST-correct."""
    out: List[datetime] = []
    cur = after_utc or utcnow()
    for _ in range(n):
        cur = _cron_next_utc(cron_expr, tz_name or DEFAULT_TZ, cur)
        out.append(cur)
    return out


def next_fire_times(cron_expr: str, tz_name: str, n: int = 5, after: Optional[datetime] = None) -> List[str]:
    return [_iso(d) for d in cron_fire_times(cron_expr, tz_name, n, after)]


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def _loads(s: Optional[str], default):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return default


def _dumps(v) -> Optional[str]:
    if v is None:
        return None
    from services.task_store import DatabaseJSONEncoder
    return json.dumps(v, cls=DatabaseJSONEncoder)


def job_row_to_dict(r) -> Dict[str, Any]:
    d = dict(r)
    d["params"] = _loads(d.pop("params_json", None), {})
    d["guards"] = _loads(d.pop("guards_json", None), {})
    for k in ("run_at", "next_run_at", "last_run_at", "created_at", "updated_at"):
        d[k] = _iso(d.get(k))
    d["enabled"] = bool(d.get("enabled"))
    return d


def run_row_to_dict(r, include_log: bool = False) -> Dict[str, Any]:
    d = dict(r)
    d["params"] = _loads(d.pop("params_json", None), {})
    d["summary"] = _loads(d.pop("summary_json", None), None)
    if not include_log:
        d.pop("log_text", None)
    for k in ("heartbeat_at", "queued_at", "started_at", "finished_at"):
        d[k] = _iso(d.get(k))
    d["cancel_requested"] = bool(d.get("cancel_requested"))
    if d.get("started_at") and d.get("finished_at"):
        try:
            s = datetime.fromisoformat(d["started_at"].replace("Z", "+00:00"))
            f = datetime.fromisoformat(d["finished_at"].replace("Z", "+00:00"))
            d["duration_s"] = int((f - s).total_seconds())
        except Exception:  # noqa: BLE001
            d["duration_s"] = None
    return d


# ---------------------------------------------------------------------------
# Definitions CRUD (used by the admin API)
# ---------------------------------------------------------------------------
def create_job(engine, data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema(engine)
    spec = get_job(str(data.get("job_type") or ""))
    params = apply_defaults(spec, data.get("params") or {})
    kind = str(data.get("schedule_kind") or "manual")
    tz_name = str(data.get("timezone") or DEFAULT_TZ)
    ZoneInfo(tz_name)  # validate
    run_at = _parse_dt(data.get("run_at"))
    interval_s = int(data["interval_s"]) if data.get("interval_s") else None
    cron_expr = (data.get("cron_expr") or None)
    next_run = compute_next_run(kind, cron_expr, interval_s, run_at, tz_name)
    guards = data.get("guards") or {}
    if spec.phases and "require_phase" not in guards:
        guards["require_phase"] = list(spec.phases)
    guards.setdefault("skip_if_run_games", True)
    guards.setdefault("pause_on_failure", True)
    now = utcnow()
    with engine.begin() as conn:
        res = conn.execute(text("""
            INSERT INTO scheduled_jobs (name, job_type, params_json, schedule_kind, cron_expr, interval_s, run_at,
                                        timezone, enabled, guards_json, next_run_at, created_at, updated_at)
            VALUES (:name, :job_type, :params, :kind, :cron, :interval_s, :run_at, :tz, :enabled, :guards, :next_run, :now, :now)
        """), {"name": str(data.get("name") or spec.title)[:120], "job_type": spec.name, "params": _dumps(params),
               "kind": kind, "cron": cron_expr, "interval_s": interval_s, "run_at": run_at, "tz": tz_name,
               "enabled": 1 if data.get("enabled", True) else 0, "guards": _dumps(guards),
               "next_run": next_run, "now": now})
        job_id = int(res.lastrowid)
    return get_job_def(engine, job_id)


def update_job(engine, job_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema(engine)
    cur = get_job_def(engine, job_id)
    if not cur:
        raise KeyError("job not found")
    spec = get_job(str(data.get("job_type") or cur["job_type"]))
    params = apply_defaults(spec, data.get("params", cur["params"]) or {})
    kind = str(data.get("schedule_kind") or cur["schedule_kind"])
    tz_name = str(data.get("timezone") or cur["timezone"] or DEFAULT_TZ)
    ZoneInfo(tz_name)
    run_at = _parse_dt(data.get("run_at")) if "run_at" in data else _parse_dt(cur.get("run_at"))
    interval_s = (int(data["interval_s"]) if data.get("interval_s") else None) if "interval_s" in data else cur.get("interval_s")
    cron_expr = data.get("cron_expr", cur.get("cron_expr")) or None
    enabled = bool(data.get("enabled", cur["enabled"]))
    guards = data.get("guards", cur["guards"]) or {}
    next_run = compute_next_run(kind, cron_expr, interval_s, run_at, tz_name) if enabled else None
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE scheduled_jobs SET name=:name, job_type=:job_type, params_json=:params, schedule_kind=:kind,
                   cron_expr=:cron, interval_s=:interval_s, run_at=:run_at, timezone=:tz, enabled=:enabled,
                   guards_json=:guards, next_run_at=:next_run, updated_at=:now
            WHERE id=:id
        """), {"id": job_id, "name": str(data.get("name") or cur["name"])[:120], "job_type": spec.name,
               "params": _dumps(params), "kind": kind, "cron": cron_expr, "interval_s": interval_s,
               "run_at": run_at, "tz": tz_name, "enabled": 1 if enabled else 0, "guards": _dumps(guards),
               "next_run": next_run, "now": utcnow()})
    return get_job_def(engine, job_id)


def set_job_enabled(engine, job_id: int, enabled: bool) -> Dict[str, Any]:
    cur = get_job_def(engine, job_id)
    if not cur:
        raise KeyError("job not found")
    next_run = None
    if enabled:
        next_run = compute_next_run(cur["schedule_kind"], cur.get("cron_expr"), cur.get("interval_s"),
                                    _parse_dt(cur.get("run_at")), cur.get("timezone") or DEFAULT_TZ)
    with engine.begin() as conn:
        conn.execute(text("UPDATE scheduled_jobs SET enabled=:e, next_run_at=:n, updated_at=:now WHERE id=:id"),
                     {"e": 1 if enabled else 0, "n": next_run, "now": utcnow(), "id": job_id})
    return get_job_def(engine, job_id)


def delete_job(engine, job_id: int) -> bool:
    with engine.begin() as conn:
        res = conn.execute(text("DELETE FROM scheduled_jobs WHERE id=:id"), {"id": job_id})
        conn.execute(text("UPDATE job_runs SET job_id=NULL WHERE job_id=:id"), {"id": job_id})
    return res.rowcount > 0


def get_job_def(engine, job_id: int) -> Optional[Dict[str, Any]]:
    ensure_schema(engine)
    with engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM scheduled_jobs WHERE id=:id"), {"id": job_id}).mappings().first()
    return job_row_to_dict(r) if r else None


def list_job_defs(engine) -> List[Dict[str, Any]]:
    ensure_schema(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM scheduled_jobs ORDER BY enabled DESC, next_run_at IS NULL, next_run_at, id")).mappings().all()
    return [job_row_to_dict(r) for r in rows]


def _parse_dt(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return _to_utc_naive(v)
    s = str(v).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _to_utc_naive(dt)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def enqueue_run(engine, job_type: str, params: Optional[Dict[str, Any]], trigger_kind: str,
                job_id: Optional[int] = None) -> int:
    ensure_schema(engine)
    spec = get_job(job_type)
    params = apply_defaults(spec, params or {})
    with engine.begin() as conn:
        res = conn.execute(text("""
            INSERT INTO job_runs (job_id, job_type, params_json, trigger_kind, status, queued_at)
            VALUES (:job_id, :job_type, :params, :trigger, 'queued', :now)
        """), {"job_id": job_id, "job_type": spec.name, "params": _dumps(params), "trigger": trigger_kind,
               "now": utcnow()})
        return int(res.lastrowid)


def get_run(engine, run_id: int, include_log: bool = True) -> Optional[Dict[str, Any]]:
    ensure_schema(engine)
    with engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM job_runs WHERE id=:id"), {"id": run_id}).mappings().first()
    return run_row_to_dict(r, include_log=include_log) if r else None


def list_runs(engine, job_id: Optional[int] = None, status: Optional[str] = None, job_type: Optional[str] = None,
              limit: int = 50, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ensure_schema(engine)
    where = ["1=1"]
    p: Dict[str, Any] = {"limit": int(limit)}
    if job_id is not None:
        where.append("job_id = :job_id")
        p["job_id"] = job_id
    if status:
        where.append("status = :status")
        p["status"] = status
    if job_type:
        where.append("job_type = :job_type")
        p["job_type"] = job_type
    if since is not None:
        where.append("queued_at >= :since")
        p["since"] = since
    sql = f"""SELECT id, job_id, job_type, params_json, trigger_kind, status, skip_reason, claimed_by, heartbeat_at,
                     queued_at, started_at, finished_at, progress, total, stage, cancel_requested, task_id,
                     summary_json, error
              FROM job_runs WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT :limit"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), p).mappings().all()
    return [run_row_to_dict(r) for r in rows]


def request_cancel(engine, run_id: int) -> bool:
    with engine.begin() as conn:
        res = conn.execute(text("""
            UPDATE job_runs SET cancel_requested=1,
                   status = CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                   finished_at = CASE WHEN status='queued' THEN :now ELSE finished_at END
            WHERE id=:id AND status IN ('queued','running')
        """), {"id": run_id, "now": utcnow()})
    return res.rowcount > 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _claim_run(engine, run_id: int) -> Optional[Dict[str, Any]]:
    now = utcnow()
    with engine.begin() as conn:
        res = conn.execute(text("""
            UPDATE job_runs SET status='running', claimed_by=:who, started_at=:now, heartbeat_at=:now
            WHERE id=:id AND status='queued'
        """), {"who": _WHO, "now": now, "id": run_id})
        if res.rowcount != 1:
            return None
        r = conn.execute(text("SELECT * FROM job_runs WHERE id=:id"), {"id": run_id}).mappings().first()
    return dict(r) if r else None


def _finish_run(engine, run_id: int, status: str, *, summary=None, error: Optional[str] = None,
                skip_reason: Optional[str] = None, log_lines: Optional[List[str]] = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE job_runs SET status=:status, finished_at=:now, summary_json=:summary, error=:error,
                   skip_reason=:skip, log_text=:log, heartbeat_at=:now
            WHERE id=:id
        """), {"status": status, "now": utcnow(), "summary": _dumps(summary), "error": error,
               "skip": (skip_reason or None), "log": ("\n".join(log_lines) if log_lines else None), "id": run_id})


def _after_run(engine, run: Dict[str, Any], status: str) -> None:
    """Update the parent job's last_status/pause and enqueue chains."""
    job_id = run.get("job_id")
    if job_id:
        with engine.begin() as conn:
            conn.execute(text("UPDATE scheduled_jobs SET last_status=:s, runs_count=runs_count+1, updated_at=:now WHERE id=:id"),
                         {"s": status, "now": utcnow(), "id": job_id})
            if status == "failed":
                row = conn.execute(text("SELECT guards_json FROM scheduled_jobs WHERE id=:id"), {"id": job_id}).scalar()
                guards = _loads(row, {})
                if guards.get("pause_on_failure", True):
                    conn.execute(text("UPDATE scheduled_jobs SET enabled=0, next_run_at=NULL WHERE id=:id"), {"id": job_id})
                    log.warning("job %s paused after failure", job_id)
    if status == "succeeded":
        params = _loads(run.get("params_json"), {})
        for nxt in params.get("on_success", []) or []:
            try:
                if isinstance(nxt, str):
                    enqueue_run(engine, nxt, {}, "chain", None)
                elif isinstance(nxt, dict) and nxt.get("job_type"):
                    enqueue_run(engine, nxt["job_type"], nxt.get("params") or {}, "chain", None)
            except Exception as e:  # noqa: BLE001
                log.warning("chain enqueue failed for %s: %s", nxt, e)


def _broadcast(payload: Dict[str, Any]) -> None:
    try:
        from services.websocket_manager import ws_manager
        ws_manager.broadcast({"type": "job_run", **payload})
    except Exception:  # noqa: BLE001
        pass


def _check_guards(engine, run: Dict[str, Any], spec, ctx: JobContext) -> Optional[str]:
    guards: Dict[str, Any] = {}
    if run.get("job_id"):
        with engine.connect() as conn:
            g = conn.execute(text("SELECT guards_json FROM scheduled_jobs WHERE id=:id"), {"id": run["job_id"]}).scalar()
        guards = _loads(g, {})
    phases = guards.get("require_phase") if guards.get("require_phase") is not None else spec.phases
    if phases:
        phase = ctx.phase()
        if phase not in phases:
            return f"phase is {phase}; job requires {', '.join(phases)}"
    if guards.get("skip_if_run_games", True) and spec.group == "season" and ctx.timestamp().get("RunGames"):
        return "RunGames flag is set"
    max_runs = guards.get("max_runs")
    if max_runs and run.get("job_id"):
        with engine.connect() as conn:
            n = conn.execute(text("SELECT runs_count FROM scheduled_jobs WHERE id=:id"), {"id": run["job_id"]}).scalar()
        if n is not None and int(n) >= int(max_runs):
            return f"max_runs ({max_runs}) reached"
    return None


def execute_run(engine, run_id: int) -> Optional[str]:
    """Claim and execute one queued run. Returns the terminal status or None if not claimed."""
    ensure_schema(engine)
    run = _claim_run(engine, run_id)
    if not run:
        return None
    job_type = run["job_type"]
    try:
        spec = get_job(job_type)
    except KeyError as e:
        _finish_run(engine, run_id, "failed", error=str(e))
        _after_run(engine, run, "failed")
        return "failed"

    params = apply_defaults(spec, _loads(run.get("params_json"), {}))
    lines: List[str] = []
    stop_hb = threading.Event()

    def _log(msg: str) -> None:
        lines.append(f"{utcnow().isoformat()} {msg}")

    def _progress(n, total, stage) -> None:
        with engine.begin() as conn:
            conn.execute(text("UPDATE job_runs SET progress=:p, total=COALESCE(:t, total), stage=COALESCE(:s, stage), heartbeat_at=:now WHERE id=:id"),
                         {"p": int(n or 0), "t": int(total) if total is not None else None, "s": stage, "now": utcnow(), "id": run_id})

    def _cancelled() -> bool:
        with engine.connect() as conn:
            v = conn.execute(text("SELECT cancel_requested FROM job_runs WHERE id=:id"), {"id": run_id}).scalar()
        return bool(v)

    def _heartbeat() -> None:
        while not stop_hb.wait(_HEARTBEAT_S):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE job_runs SET heartbeat_at=:now WHERE id=:id"), {"now": utcnow(), "id": run_id})
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat failed for run %s: %s", run_id, e)

    hb = threading.Thread(target=_heartbeat, name=f"job-hb-{run_id}", daemon=True)
    hb.start()

    # Mirror the run in background_tasks so the existing task UI/polling see it.
    task_id = None
    task_store = None
    try:
        from services.task_store import get_task_store
        task_store = get_task_store()
        task_row = task_store.create_task(f"job:{job_type}", metadata={"run_id": run_id, "params": params})
        task_id = task_row["task_id"] if isinstance(task_row, dict) else str(task_row)
        task_store.set_running(task_id)
        with engine.begin() as conn:
            conn.execute(text("UPDATE job_runs SET task_id=:t WHERE id=:id"), {"t": task_id, "id": run_id})
    except Exception as e:  # noqa: BLE001
        log.warning("task mirror failed for run %s: %s", run_id, e)
        task_store = None

    ctx = JobContext(engine, params, run_id=run_id, log_fn=_log, progress_fn=_progress, cancel_fn=_cancelled)
    status = "failed"
    summary = None
    error = None
    skip_reason = None
    t0 = time.monotonic()
    _broadcast({"run_id": run_id, "job_type": job_type, "status": "running"})
    try:
        reason = _check_guards(engine, run, spec, ctx)
        if reason:
            raise JobSkipped(reason)
        if _cancelled():
            raise JobCancelled("cancelled before start")
        ctx.log(f"start {job_type} params={json.dumps(params, default=str)}")
        summary = spec.fn(ctx)
        status = "succeeded"
        ctx.log(f"done in {time.monotonic() - t0:.1f}s")
    except JobSkipped as e:
        status = "skipped"
        skip_reason = str(e)[:255]
        ctx.log(f"skipped: {skip_reason}")
    except JobCancelled as e:
        status = "cancelled"
        error = str(e)
        ctx.log(f"cancelled: {e}")
    except Exception as e:  # noqa: BLE001
        status = "failed"
        error = f"{type(e).__name__}: {e}"
        lines.append(traceback.format_exc())
        log.exception("job run %s (%s) failed", run_id, job_type)
    finally:
        stop_hb.set()

    try:
        _finish_run(engine, run_id, status, summary=summary, error=error, skip_reason=skip_reason, log_lines=lines)
    except Exception as e:  # noqa: BLE001
        log.exception("could not finish run %s: %s", run_id, e)
    if task_store and task_id:
        try:
            if status == "succeeded":
                task_store.set_complete(task_id, summary if summary is not None else {"ok": True})
            elif status == "skipped":
                task_store.set_complete(task_id, {"skipped": True, "reason": skip_reason})
            else:
                task_store.set_failed(task_id, error or status)
        except Exception:  # noqa: BLE001
            pass
    try:
        _after_run(engine, run, status)
    except Exception as e:  # noqa: BLE001
        log.exception("after-run hook failed for %s: %s", run_id, e)
    _broadcast({"run_id": run_id, "job_type": job_type, "status": status, "job_id": run.get("job_id")})
    return status


def run_inline_async(engine, run_id: int) -> None:
    """Execute a run on a detached thread in this process (API fallback when no leader is alive)."""
    threading.Thread(target=execute_run, args=(engine, run_id), name=f"job-inline-{run_id}", daemon=True).start()


# ---------------------------------------------------------------------------
# Leader loop
# ---------------------------------------------------------------------------
def start_job_scheduler(get_engine) -> bool:
    global _started
    if os.getenv("JOB_SCHEDULER_DISABLED", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("FLASK_ENV") == "development" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    t = threading.Thread(target=_run, args=(get_engine,), name="job-scheduler", daemon=True)
    t.start()
    return True


def _run(get_engine) -> None:
    time.sleep(3.0)
    while True:
        try:
            engine = get_engine()
            ensure_schema(engine)
        except Exception as e:  # noqa: BLE001
            log.warning("job scheduler: no engine yet (%s)", e)
            time.sleep(_FOLLOWER_RETRY_S)
            continue
        try:
            with engine.connect() as lock_conn:
                got = lock_conn.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": _LOCK_NAME}).scalar()
                if not got:
                    time.sleep(_FOLLOWER_RETRY_S)
                    continue
                log.info("job scheduler: this process is the leader (%s)", _WHO)
                try:
                    _lead(engine, lock_conn)
                finally:
                    try:
                        lock_conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": _LOCK_NAME})
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            log.warning("job scheduler: leader loop ended: %s", e)
            time.sleep(_FOLLOWER_RETRY_S)


def _run_cron_enabled(engine) -> bool:
    with engine.connect() as conn:
        v = conn.execute(text("SELECT run_cron FROM timestamp_state WHERE id = 1")).scalar()
    return bool(v)


def _reap_stale(engine) -> int:
    cutoff = utcnow() - timedelta(seconds=_STALE_S)
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, job_id, job_type, params_json FROM job_runs WHERE status='running' AND (heartbeat_at IS NULL OR heartbeat_at < :c)"),
                            {"c": cutoff}).mappings().all()
        for r in rows:
            conn.execute(text("UPDATE job_runs SET status='failed', error='runner lost (heartbeat stale)', finished_at=:now WHERE id=:id"),
                         {"now": utcnow(), "id": r["id"]})
    for r in rows:
        log.warning("reaped stale run %s (%s)", r["id"], r["job_type"])
        _after_run(engine, dict(r), "failed")
    return len(rows)


def _claim_due_jobs(engine) -> List[int]:
    """Atomically bump next_run_at on due jobs; queue a run for each one we won."""
    now = utcnow()
    with engine.connect() as conn:
        due = conn.execute(text("SELECT * FROM scheduled_jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= :now"),
                           {"now": now}).mappings().all()
    queued: List[int] = []
    for j in due:
        try:
            nxt = compute_next_run(j["schedule_kind"], j["cron_expr"], j["interval_s"], j["run_at"], j["timezone"] or DEFAULT_TZ, after=now)
        except Exception as e:  # noqa: BLE001
            log.warning("job %s: cannot compute next run (%s); disabling", j["id"], e)
            nxt = None
        with engine.begin() as conn:
            res = conn.execute(text("""
                UPDATE scheduled_jobs SET next_run_at=:nxt, last_run_at=:now, updated_at=:now,
                       enabled = CASE WHEN :nxt IS NULL THEN 0 ELSE enabled END
                WHERE id=:id AND enabled=1 AND next_run_at=:prev
            """), {"nxt": nxt, "now": now, "id": j["id"], "prev": j["next_run_at"]})
            if res.rowcount != 1:
                continue  # another leader won
        try:
            rid = enqueue_run(engine, j["job_type"], _loads(j["params_json"], {}), "schedule", int(j["id"]))
            queued.append(rid)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s: enqueue failed: %s", j["id"], e)
    return queued


def _pick_queued(engine, limit: int) -> List[int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM job_runs WHERE status='queued' ORDER BY id LIMIT :l"), {"l": int(limit)}).all()
    return [int(r[0]) for r in rows]


def _lead(engine, lock_conn) -> None:
    pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="job-worker")
    in_flight: Dict[int, Any] = {}
    with engine.begin() as conn:
        conn.execute(text("UPDATE scheduler_state SET leader=:who, started_at=:now, last_tick_at=:now WHERE id=1"),
                     {"who": _WHO, "now": utcnow()})
    try:
        while True:
            lock_conn.execute(text("SELECT 1"))
            try:
                for rid, fut in list(in_flight.items()):
                    if fut.done():
                        in_flight.pop(rid, None)
                _reap_stale(engine)
                if _run_cron_enabled(engine):
                    _claim_due_jobs(engine)
                free = max(0, _WORKERS - len(in_flight))
                if free:
                    for rid in _pick_queued(engine, free + len(in_flight)):
                        if rid in in_flight or free <= 0:
                            continue
                        in_flight[rid] = pool.submit(execute_run, engine, rid)
                        free -= 1
                with engine.begin() as conn:
                    conn.execute(text("UPDATE scheduler_state SET leader=:who, last_tick_at=:now WHERE id=1"),
                                 {"who": _WHO, "now": utcnow()})
            except Exception as e:  # noqa: BLE001
                log.exception("job scheduler tick failed: %s", e)
            time.sleep(_TICK_S)
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Status (for the API / command center)
# ---------------------------------------------------------------------------
def leader_alive(engine) -> bool:
    ensure_schema(engine)
    with engine.connect() as conn:
        r = conn.execute(text("SELECT last_tick_at FROM scheduler_state WHERE id=1")).scalar()
    if not r:
        return False
    return (utcnow() - r).total_seconds() < _LEADER_FRESH_S


def get_scheduler_status(engine) -> Dict[str, Any]:
    ensure_schema(engine)
    with engine.connect() as conn:
        st = conn.execute(text("SELECT leader, last_tick_at, started_at FROM scheduler_state WHERE id=1")).mappings().first()
        enabled = bool(conn.execute(text("SELECT run_cron FROM timestamp_state WHERE id = 1")).scalar())
        nxt = conn.execute(text("SELECT id, name, job_type, next_run_at FROM scheduled_jobs WHERE enabled=1 AND next_run_at IS NOT NULL ORDER BY next_run_at LIMIT 5")).mappings().all()
        running = conn.execute(text("SELECT COUNT(*) FROM job_runs WHERE status='running'")).scalar()
        queued = conn.execute(text("SELECT COUNT(*) FROM job_runs WHERE status='queued'")).scalar()
        failed_24h = conn.execute(text("SELECT COUNT(*) FROM job_runs WHERE status='failed' AND finished_at >= :c"),
                                  {"c": utcnow() - timedelta(hours=24)}).scalar()
        last = conn.execute(text("SELECT id, job_type, status, finished_at FROM job_runs WHERE status IN ('succeeded','failed','skipped','cancelled') ORDER BY id DESC LIMIT 5")).mappings().all()
    alive = bool(st and st["last_tick_at"] and (utcnow() - st["last_tick_at"]).total_seconds() < _LEADER_FRESH_S)
    next_runs = [{"job_id": r["id"], "name": r["name"], "job_type": r["job_type"], "at": _iso(r["next_run_at"]),
                  "in": _humanize(r["next_run_at"])} for r in nxt]
    return {
        "enabled": enabled,
        "leader": st["leader"] if alive and st else None,
        "leader_alive": alive,
        "last_tick_at": _iso(st["last_tick_at"]) if st else None,
        "tick_s": _TICK_S,
        "workers": _WORKERS,
        "running": int(running or 0),
        "queued": int(queued or 0),
        "failed_24h": int(failed_24h or 0),
        "next_runs": next_runs,
        "next_run": next_runs[0] if next_runs else None,
        "recent": [{"run_id": r["id"], "job_type": r["job_type"], "status": r["status"], "finished_at": _iso(r["finished_at"])} for r in last],
        "timezone": DEFAULT_TZ,
    }


def set_scheduler_enabled(enabled: bool) -> bool:
    from services.timestamp import update_timestamp
    return update_timestamp({"run_cron": bool(enabled)}, broadcast=True)


def _humanize(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    s = int((dt - utcnow()).total_seconds())
    past = s < 0
    s = abs(s)
    if s < 60:
        out = f"{s}s"
    elif s < 3600:
        out = f"{s // 60}m"
    elif s < 86400:
        out = f"{s // 3600}h {(s % 3600) // 60}m"
    else:
        out = f"{s // 86400}d {(s % 86400) // 3600}h"
    return f"{out} ago" if past else f"in {out}"


def registry_types() -> List[Dict[str, Any]]:
    return [s.to_dict() for s in list_jobs()]
