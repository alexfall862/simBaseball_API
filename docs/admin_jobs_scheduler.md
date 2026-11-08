# Admin Jobs & Scheduler

Scheduled and on-demand execution of league operations (simulate a subweek, advance the week, run books, advance recruiting, end/archive a season, …) from the admin UI. Implemented 2026-11-08 as part of the admin frontend revamp (`docs/ADMIN_FRONTEND_REVAMP_PLAN.md`, section 4).

## Concepts

| Term | Meaning |
|---|---|
| **Job type** | A Python function registered in `services/jobs/__init__.py` with `@job(...)`. It calls existing service code directly (never HTTP). Metadata (title, allowed phases, param schema) drives the UI forms. `GET /admin/jobs/types` lists them. |
| **Scheduled job** | A row in `scheduled_jobs`: a job type + params + a schedule (`cron`, `interval`, `once`, `manual`) + guards. |
| **Run** | A row in `job_runs`: one execution (queued → running → succeeded / failed / skipped / cancelled) with progress, summary JSON, captured log lines and error. Each run also mirrors itself into `background_tasks` as `job:<type>` so the Background Tasks tab shows it. |
| **Scheduler switch** | `timestamp_state.run_cron`. Off = due jobs are not claimed. Manual "Run now" always works. Toggle: UI topbar pill, Settings, or `POST /admin/scheduler/toggle`. |
| **Leader** | Exactly one process per database runs due jobs, elected with MySQL `GET_LOCK('simbb_job_scheduler')` (same pattern as the draft clock). Followers retry every 15 s. `scheduler_state` records the leader and its last tick. |

## Runtime

* Started from `create_app()` (`services/job_scheduler.start_job_scheduler`). Env:
  * `JOB_SCHEDULER_DISABLED=1` – do not start the thread (e.g. on web workers when a dedicated scheduler container runs it).
  * `JOB_SCHEDULER_TICK_S` (20) – leader tick; `JOB_SCHEDULER_WORKERS` (2) – concurrent runs; `JOB_SCHEDULER_STALE_S` (600) – a running run with no heartbeat for this long is marked failed ("runner lost").
  * `JOB_SCHEDULER_TZ` (America/New_York) – default timezone for new schedules.
* Each leader tick: reap stale runs → if `run_cron` on, atomically claim due jobs (`UPDATE … WHERE next_run_at = <seen>`) and queue a run each → execute queued runs (manual + scheduled, FIFO) on the worker pool → write `scheduler_state.last_tick_at`.
* `POST …/run-now` queues a run; if no leader has ticked in 90 s the API executes it on a thread in the web worker instead. The queued→running claim is atomic, so a run never executes twice.
* Cron expressions are evaluated on the wall clock of the job's timezone and are DST-correct (a `0 6 * * *` job fires at 06:00 local on the switch day too).
* Guards (per job, JSON in `guards_json`): `require_phase` (list; defaults to the job type's phases), `skip_if_run_games` (default true, season group only), `pause_on_failure` (default true: the job is disabled after a failed run), `max_runs`.
* Chaining: `params.on_success = ["advance_week", {"job_type": "...", "params": {...}}]` queues follow-ups when a run succeeds.
* Every run broadcasts `{type: "job_run", run_id, job_type, status}` over the `/ws` socket.

## Job types (initial registry)

| group | job_type | notes |
|---|---|---|
| season | `sim_next_subweek` | **The daily cron.** Sims the first incomplete subweek; after d advances the week when `auto_advance`. Skips if RunGames is set or phase ≠ REGULAR_SEASON. Optional `auto_advance_playoffs` + `playoff_levels`. Has a preview. |
| season | `sim_subweek`, `advance_week`, `run_week`, `playoffs_process_and_advance` | explicit equivalents of the Simulate/Playoffs buttons |
| market | `fa_advance_round`, `fa_end`, `fa_advance_phases`, `recruiting_advance_week` (`times`), `ifa_advance_week`, `draft_auto_pick_expired` | |
| finance | `books_run_week`, `books_playoff_revenue`, `books_year_end_interest`, `books_year_start` | take `league_year` (the year number), resolved from the current league year when blank |
| rollover | `end_season`, `archive_season`, `schedule_generate`, `start_new_season`, `init_next_league_year`, `phase_action`, `offseason_checklist_step` | the long ones run here instead of inside a 45 s HTTP request |
| digest | `trade_queue_digest` | read-only; feeds the Command Center |

Adding a job type: write a function `fn(ctx) -> dict` in `services/jobs/__init__.py`, decorate it with `@job(name, title=..., phases=[...], params={...}, group=...)`, optionally add `@preview_for(name)`. `ctx` gives `params`, `engine`, `log()`, `set_progress()`, `check_cancel()`, `skip(reason)`, `timestamp()`, `league_year_id()`, `league_year()`.

## HTTP API (admin session required)

```
GET    /admin/jobs                      POST /admin/jobs
GET    /admin/jobs/types
GET    /admin/jobs/<id>                 PUT /admin/jobs/<id>      DELETE /admin/jobs/<id>
POST   /admin/jobs/<id>/toggle          {enabled}
POST   /admin/jobs/<id>/run-now         -> 202 {run_id, inline, poll_url}
POST   /admin/jobs/run                  {job_type, params} -> 202 {run_id}
POST   /admin/jobs/preview              {job_type, params, schedule_kind, cron_expr, timezone, ...}
GET    /admin/jobs/runs                 ?job_id=&status=&job_type=&hours=&limit=
GET    /admin/jobs/runs/<run_id>        (?log=0 to omit the log)
POST   /admin/jobs/runs/<run_id>/cancel
GET    /admin/scheduler                 POST /admin/scheduler/toggle {enabled}
```

Create body example:

```json
{"name": "Daily subweek", "job_type": "sim_next_subweek", "schedule_kind": "cron",
 "cron_expr": "0 6 * * *", "timezone": "America/New_York",
 "params": {"auto_advance": true}, "guards": {"pause_on_failure": true}}
```

## UI

* **Jobs › Scheduled Jobs** – scheduler status + switch, job table (toggle, Run now, Preview, Edit, Runs, delete), presets (Daily subweek, Weekday week, Recruiting day, FA round daily, Playoff round check), ad-hoc "run any job once".
* **Jobs › Run History** – filters, live refresh, detail modal with params / summary / log, cancel, re-run.
* **Jobs › Background Tasks** – `background_tasks` rows (incl. mirrored job runs) and the synthetic-game smoke test.
* **Jobs › Logs** – tail of `timing_log.txt` and `sim_failures.log` (`GET /admin/logs`).
* **Command Center** – next fires, recent runs, failed-run alerts; **Timeline** – planned fires and completed runs per week, projected real-world dates from the active sim job.

## Related changes shipped with it

* `GET /admin/summary` (command center), `GET /admin/timeline`, `GET /admin/logs`, `POST /admin/sim/clear-run-games` (clears a stuck `run_games` flag; refuses while a task or run is active).
* Admin route guard (`services/admin_auth.py`): season-mutating `/api/v1` routes now require the admin session, `X-Admin-Password` or `X-Admin-Key: $ADMIN_API_KEY`. Disabled when neither `ADMIN_PASSWORD` nor `ADMIN_API_KEY` is configured, or with `ADMIN_ROUTE_GUARD=off`. The protected list is explicit in `PROTECTED`.
* The `/admin/run-*-books`, `/admin/run-playoff-revenue`, `/admin/initialize-next-league-year`, `/admin/seed-contracts`, `/admin/simulate-fake-season` routes in `app.py` accept the admin session cookie as well as the password header.
* New dependency: `croniter==2.0.5`.

## Operations notes

* Tables are created on first use (`ensure_schema`): `scheduled_jobs`, `job_runs`, `scheduler_state`.
* Worker recycling (`--max-requests`) is safe: the lock is released on exit, another worker becomes leader within 15 s, in-flight runs are reaped as failed after `JOB_SCHEDULER_STALE_S` and never silently re-run. `sim_next_subweek` re-reads the subweek flags so a retry picks up where it left off.
* To run the scheduler as its own container: start the web workers with `JOB_SCHEDULER_DISABLED=1` and one extra process with the normal app (it will win the lock).
