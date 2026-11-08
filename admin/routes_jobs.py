# admin/routes_jobs.py — scheduled jobs API (registered on admin_bp).
"""
GET    /admin/jobs                  list definitions
POST   /admin/jobs                  create
GET    /admin/jobs/types            registry (job types + param schemas)
GET    /admin/jobs/<id>             one definition (+ recent runs)
PUT    /admin/jobs/<id>             update
DELETE /admin/jobs/<id>             delete
POST   /admin/jobs/<id>/toggle      {enabled}
POST   /admin/jobs/<id>/run-now     -> {run_id}
POST   /admin/jobs/run              ad-hoc {job_type, params} -> {run_id}
POST   /admin/jobs/preview          {job_type, params, cron_expr?, timezone?} -> what it would do + next fires
GET    /admin/jobs/runs             ?job_id=&status=&job_type=&limit=
GET    /admin/jobs/runs/<run_id>    full run incl. log
POST   /admin/jobs/runs/<run_id>/cancel
GET    /admin/scheduler             status
POST   /admin/scheduler/toggle      {enabled}
"""

import logging
from datetime import timedelta

from flask import jsonify, request

from admin import admin_bp, _require_admin

log = logging.getLogger(__name__)


def _engine():
    from db import get_engine
    return get_engine()


def _body():
    return request.get_json(force=True, silent=True) or {}


@admin_bp.get("/jobs")
def jobs_list():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import list_job_defs
    return jsonify(ok=True, jobs=list_job_defs(_engine()))


@admin_bp.get("/jobs/types")
def jobs_types():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import registry_types, DEFAULT_TZ
    return jsonify(ok=True, types=registry_types(), default_timezone=DEFAULT_TZ)


@admin_bp.post("/jobs")
def jobs_create():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import create_job
    try:
        return jsonify(ok=True, job=create_job(_engine(), _body())), 201
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400


@admin_bp.get("/jobs/<int:job_id>")
def jobs_get(job_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import get_job_def, list_runs
    eng = _engine()
    job = get_job_def(eng, job_id)
    if not job:
        return jsonify(ok=False, error="not_found"), 404
    return jsonify(ok=True, job=job, runs=list_runs(eng, job_id=job_id, limit=20))


@admin_bp.put("/jobs/<int:job_id>")
def jobs_update(job_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import update_job
    try:
        return jsonify(ok=True, job=update_job(_engine(), job_id, _body()))
    except KeyError as e:
        return jsonify(ok=False, error="not_found", message=str(e)), 404
    except ValueError as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400


@admin_bp.delete("/jobs/<int:job_id>")
def jobs_delete(job_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import delete_job
    if not delete_job(_engine(), job_id):
        return jsonify(ok=False, error="not_found"), 404
    return jsonify(ok=True)


@admin_bp.post("/jobs/<int:job_id>/toggle")
def jobs_toggle(job_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import set_job_enabled
    try:
        return jsonify(ok=True, job=set_job_enabled(_engine(), job_id, bool(_body().get("enabled", True))))
    except KeyError:
        return jsonify(ok=False, error="not_found"), 404
    except ValueError as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400


def _start_run(job_type, params, trigger, job_id=None):
    from services.job_scheduler import enqueue_run, leader_alive, run_inline_async
    eng = _engine()
    run_id = enqueue_run(eng, job_type, params, trigger, job_id)
    inline = False
    if request.args.get("inline") == "1" or not leader_alive(eng):
        run_inline_async(eng, run_id)
        inline = True
    return run_id, inline


@admin_bp.post("/jobs/<int:job_id>/run-now")
def jobs_run_now(job_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import get_job_def
    job = get_job_def(_engine(), job_id)
    if not job:
        return jsonify(ok=False, error="not_found"), 404
    params = dict(job["params"] or {})
    params.update(_body().get("params") or {})
    try:
        run_id, inline = _start_run(job["job_type"], params, "manual", job_id)
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400
    return jsonify(ok=True, run_id=run_id, inline=inline, poll_url=f"/admin/jobs/runs/{run_id}"), 202


@admin_bp.post("/jobs/run")
def jobs_run_adhoc():
    guard = _require_admin()
    if guard:
        return guard
    b = _body()
    if not b.get("job_type"):
        return jsonify(ok=False, error="validation", message="job_type is required"), 400
    try:
        run_id, inline = _start_run(str(b["job_type"]), b.get("params") or {}, "manual", None)
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400
    return jsonify(ok=True, run_id=run_id, inline=inline, poll_url=f"/admin/jobs/runs/{run_id}"), 202


@admin_bp.post("/jobs/preview")
def jobs_preview():
    guard = _require_admin()
    if guard:
        return guard
    from services.jobs import get_job, apply_defaults, JobContext
    from services.job_scheduler import next_fire_times, DEFAULT_TZ, compute_next_run, _parse_dt, _iso
    b = _body()
    out = {"ok": True}
    try:
        spec = get_job(str(b.get("job_type") or ""))
        params = apply_defaults(spec, b.get("params") or {})
        out["params"] = params
        ctx = JobContext(_engine(), params)
        out["phase"] = ctx.phase()
        if spec.phases and ctx.phase() not in spec.phases:
            out["guard"] = f"would skip: phase is {ctx.phase()}, job requires {', '.join(spec.phases)}"
        if spec.preview:
            out["preview"] = spec.preview(ctx)
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, error="validation", message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        out["preview_error"] = str(e)
    tz = b.get("timezone") or DEFAULT_TZ
    kind = b.get("schedule_kind")
    try:
        if kind == "cron" and b.get("cron_expr"):
            out["next_fires"] = next_fire_times(b["cron_expr"], tz, n=5)
        elif kind in ("interval", "once"):
            nxt = compute_next_run(kind, None, int(b["interval_s"]) if b.get("interval_s") else None,
                                   _parse_dt(b.get("run_at")), tz)
            out["next_fires"] = [_iso(nxt)] if nxt else []
    except Exception as e:  # noqa: BLE001
        out["schedule_error"] = str(e)
    return jsonify(out)


@admin_bp.get("/jobs/runs")
def jobs_runs():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import list_runs, utcnow
    since = None
    hours = request.args.get("hours", type=int)
    if hours:
        since = utcnow() - timedelta(hours=hours)
    runs = list_runs(_engine(), job_id=request.args.get("job_id", type=int), status=request.args.get("status"),
                     job_type=request.args.get("job_type"), limit=min(500, request.args.get("limit", 50, type=int)),
                     since=since)
    return jsonify(ok=True, runs=runs)


@admin_bp.get("/jobs/runs/<int:run_id>")
def jobs_run_get(run_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import get_run
    run = get_run(_engine(), run_id, include_log=request.args.get("log", "1") != "0")
    if not run:
        return jsonify(ok=False, error="not_found"), 404
    return jsonify(ok=True, run=run)


@admin_bp.post("/jobs/runs/<int:run_id>/cancel")
def jobs_run_cancel(run_id: int):
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import request_cancel
    return jsonify(ok=request_cancel(_engine(), run_id))


@admin_bp.get("/scheduler")
def scheduler_status():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import get_scheduler_status
    return jsonify(ok=True, scheduler=get_scheduler_status(_engine()))


@admin_bp.post("/scheduler/toggle")
def scheduler_toggle():
    guard = _require_admin()
    if guard:
        return guard
    from services.job_scheduler import set_scheduler_enabled, get_scheduler_status
    set_scheduler_enabled(bool(_body().get("enabled", True)))
    return jsonify(ok=True, scheduler=get_scheduler_status(_engine()))
