# Admin Frontend Revamp Plan

**Status:** APPROVED 2026-11-08 ("go for it"), recommended option taken on every **[DECIDE]** item. Implementation status (same day):

| Phase | State |
|---|---|
| 0 Foundation (shell, core, ui, Command Center, Simulate / Phase / Checklist) | **done** — `admin/static/admin/js/`, `admin/templates/admin/index.html`; legacy UI kept at `/admin/legacy` |
| 1 Jobs (tables, leader runner, registry, API, Jobs area) | **done** — `services/job_scheduler.py`, `services/jobs/`, `admin/routes_jobs.py`; see `docs/admin_jobs_scheduler.md` |
| 2 Timeline (+ long ops as jobs) | **done** — `admin/routes_timeline.py`, `features/timeline/view.js`; end-season / archive run as jobs from the Phase and Checklist tabs |
| 3 Season rest (playoffs, events, schedule) | ported — see `docs/parity/season.md` |
| 4 Market | ported — see `docs/parity/market.md` |
| 5 Analytics & Engine | ported — see `docs/parity/analytics.md`, `docs/parity/engine.md` |
| 6 Data, System, cleanup | ported (Finance tab added) — see `docs/parity/data-system.md`. **Legacy files not yet deleted**: `legacy.html`, `app.js`, `styles.css` stay until the parity tables have been eyeballed in a browser |
| Hardening | B3 summary, B6 route guard (`services/admin_auth.py`), B7 clear-run-games, B8 lowercase statuses in the UI: **done**. B4 done as "accept session on the `app.py` admin routes" (routes not physically moved). B9 (league_year vs league_year_id normalisation) **not done** |

Index of parity tables: `docs/admin_revamp_parity.md`.

**Scope:** the admin SPA served at `/admin` (`admin/templates/admin/index.html`, `admin/static/admin/app.js`, `admin/static/admin/styles.css`) plus the backend pieces the new UI needs: a scheduled-jobs ("cron") system, a league timeline endpoint, and a few consolidations in the admin blueprint.

---

## 1. Where we are

### 1.1 Frontend as built

| Fact | Detail |
|---|---|
| Files | 3: `index.html` 4,840 lines, `app.js` 13,743 lines, `styles.css` 835 lines |
| Structure | One IIFE. ~60 flat `<section id="section-X">` panels, 18 sidebar groups, no sub-tabs, no nesting |
| Routing | `goTo(section)` toggles `.active` and runs a 130-line `switch` of loaders (`app.js:405-611`). No hash/pushState. Reload always lands on the dashboard. Cross-links simulate clicks on nav items |
| State | ~100 module-level `let` variables, one per feature or chart. `window.App` assigned twice (`app.js:11041`, `13557`). ~10 functions hung on `window` for inline `onclick` |
| Network | ~240 raw `fetch().then(r=>r.json())` calls. No shared client. `r.ok` almost never checked, errors sniffed via `data.error`. `credentials:'include'` applied inconsistently. Six per-feature POST wrappers do the same thing (`radmPost`, `radmWipePost`, `dftAdminPost`, `_gpaPut`, `progFetch`, `_fetchDemand`) |
| Feedback | 70 `alert()`, 50 `confirm()`, 13 `prompt()`, JSON dumped into `<pre>`. No toast. `status-msg` class used 70 times, defined nowhere |
| Duplication | 4 league-year dropdown loaders hitting the same endpoint; 5 copies of the level-name map; 2 position maps; 2 HTML escapers (most templates don't escape at all); A-D subweek flags rendered in two places; two copy-pasted task polling loops with mixed `'complete'`/`'COMPLETE'` checks |
| Styling | 772 inline `style=` in HTML, 341 in JS templates, 332 `.style.` assignments. Badge classes inconsistent (`badge-complete` vs `badge-success`) |
| Dead code | Fallback "old HTML" branch in `renderTimestamp`; empty switch cases; 9 sections with no loader; ~20 sections missing from the `titles` map |
| Charts | 28 `new Chart(...)`, each with a global and a manual `destroy()` |
| Missing panels | Support tickets, scouting department, finances/books, trade approval queue as a first-class view, FA close summary, `fa_config` editor, FA outcomes report, Run Week button, training camp summary |

### 1.2 Backend as built (what the UI drives)

- **Admin blueprint** (`admin/__init__.py`, `/admin/*`): 104 routes, session-cookie auth via `_require_admin()`. Plus 11 `/admin/*` routes defined directly in `app.py:590-984` (books, seeding, sandbox) that use the `X-Admin-Password` header instead of the session.
- **Season operations** live in `games/__init__.py` under `/api/v1/games/*` (simulate-subweek, simulate-week, advance-week, run-week, run-season, end-season, start-new-season, phase start/end routes) and in `playoffs`, `recruiting`, `ifa_signing`, `fa_auction`, `transactions`, `player_ops`. **None of these check auth** except `/draft/admin/*`.
- **Long jobs**: `services/task_store.py` keeps a DB `background_tasks` table (pending/running/complete/failed, progress, gzip result, 1h TTL). Work runs in a daemon thread in whichever gunicorn worker took the request. Only `run-season`, `run-season-all` and synthetic games use it. `end-season` (~134 s) and `season/archive` (~268 s) are synchronous HTTP calls.
- **Calendar state**: `timestamp_state` row 1 (season, week, `games_a_ran..d`, offseason/FA/draft/recruiting flags, `run_games`, **`run_cron` (exists, unused)**) and `league_state` row 1 (current league year and game week). Phase is *derived* by `services/timestamp.get_current_phase()` and per-phase actions by `get_available_actions()`. Claim columns give idempotency: `league_years.season_ended_at / playoff_revenue_run_at / interest_run_at`, `game_weeks.books_run_at / injuries_ticked_at`.
- **Realtime**: `flask_sock` at `/ws`; `ws_manager.broadcast_timestamp()` on week/phase changes and draft events. Per-worker connection set, so broadcasts only reach clients on the same worker. Task progress is not pushed.
- **Periodic machinery**: only `services/draft_clock.py`: a daemon thread per process, MySQL `GET_LOCK('simbb_draft_clock')` leader election, 3 s tick. No APScheduler/Celery/cron anywhere.
- **Deployment**: gunicorn `-w 4 --threads 8 --timeout 45` (Dockerfile), moving to Coolify. No Node toolchain in the image.
- **The offseason is 13 ordered manual steps** (`_build_offseason_checklist`, `admin/__init__.py:4560`): WS complete → awards → playoff revenue → interest → end-season → archive → FA → draft → recruiting → retirements → init next year → schedule → start new season. FA/draft/recruiting have no completion signal. IFA has no step at all.
- **Cadence in practice**: one subweek per real day, `advance-week` after d. Recruiting: 20 advance-week calls. FA: repeated advance-fa-round, a bid signs on the third advance. Playoff rounds advanced by hand.

---

## 2. Goals

1. **One coherent shell**: ~8 top-level areas with sub-tabs, deep-linkable URLs, consistent dark theme using the existing CSS variables and `.data-table`.
2. **One way to do each thing**: a single API client, one table component, one task-runner component, one set of selectors (league year, level, team), one toast/confirm system.
3. **Operate the league from one screen**: a Command Center that shows phase, week, subweek flags, running jobs, next scheduled run, and anything stuck.
4. **Scheduled jobs**: define recurring or one-off jobs (daily subweek sim, advance after d, recruiting week, FA round, books), fire any job now, see run history and logs.
5. **Timeline**: a visual league-year calendar (sim weeks and offseason phases) overlaid with what has happened, what is scheduled, and projected real-world dates.
6. **Strangler migration**: the old UI stays reachable until each area reaches parity; nothing is big-banged.

Non-goals for this plan: redesigning player-facing frontends; changing sim mechanics; adding end-user auth (tracked separately in MASTER_PLAN §0 #7).

---

## 3. Architecture

### 3.1 Frontend stack **[DECIDE]**

**Recommended: Option A, native ES modules, no bundler.**

- Browsers load `admin/static/admin/js/main.js` as `type="module"`; each feature is a lazily `import()`-ed module. Flask keeps serving static files exactly as today, Dockerfile unchanged, Coolify deploy unchanged, cache-busting via a `?v=<git sha>` query injected in the template.
- Chart.js stays on the CDN as now.
- Trade-off: no TypeScript, no JSX. We get a plain-JS "micro-framework" of our own (~600 lines) instead. Given the repo is Python-first with a single developer and the current code is already vanilla JS, this is the lowest-risk path and still lets us delete 13k lines of spaghetti.

Option B: Vite + Preact + TypeScript. Better DX and type safety for a 60-panel app, but requires a Node stage in the Dockerfile (multi-stage build), a `package.json`, and a build step before every deploy. Reasonable if we expect this UI to keep growing for years. Not recommended for the first pass; the module layout below ports to it cleanly if we change our minds.

### 3.2 Frontend layout (Option A)

```
admin/static/admin/
  js/
    main.js                 boot: auth gate, router, shell, WS, store
    core/
      api.js                fetch wrapper (see 3.3)
      router.js             hash router: #/area/tab?query, lazy-loads feature
      store.js              tiny pub/sub store; holds timestamp/phase, tasks, jobs, selections
      ws.js                 reconnecting /ws client -> store
      constants.js          LEVEL_NAMES, POSITIONS, PHASES, SUBWEEKS (single source)
      format.js             esc(), fmtMoney(), fmtPct(), fmtDate(), relTime()
    ui/
      table.js              DataTable: columns spec, sort, paginate, row actions, empty/loading, .data-table
      modal.js / confirm.js replaces alert/confirm/prompt; async confirm({title, danger})
      toast.js              success/error/info with auto-dismiss
      task-runner.js        "Run" button -> POST -> progress bar, polls /games/tasks/{id} or /admin/jobs/runs/{id}, surfaces result/error
      selectors.js          LeagueYearSelect, LevelSelect, TeamSelect, bound to store, remembered per area
      chart.js              Chart.js lifecycle wrapper (mount/update/destroy per container)
      form.js               field builders, validation, JSON editor
      badge.js, kpi.js, tabs.js, empty-state.js
    features/
      command-center/
      season/               simulate, timestamp+phase, offseason-checklist, playoffs, special-events, schedule
      jobs/                 scheduled jobs, run history, background tasks, logs
      timeline/
      market/               fa-auction, fa-market, draft, ifa, recruiting, waivers, trades, tx-log, compliance, eos
      engine/               generate, progress, sandbox, progression-diag, training-camp, rating-config, growth-curves, calibration
      analytics/            stat analytics (14), stamina (5), rankings (5), gameplan-audit, batting-lab
      data/                 orgs, teams, players, game-viewer, sql, db-storage
      system/               health, cache, migrations, orphan-sweep, tutorial-cms, finance, settings
  css/
    tokens.css              CSS vars (existing dark theme: --bg-dark, --bg-card, --text-primary, ...)
    base.css, shell.css, components.css
    (no per-feature inline styles; features get a scoped class prefix)
templates/admin/index.html  ~120-line shell: sidebar, topbar, <main id="view">, modal/toast roots
```

Feature module contract:

```js
export default {
  id: 'season',                       // URL area
  title: 'Season',
  tabs: [{ id: 'simulate', title: 'Simulate', load: () => import('./simulate.js') }, ...],
};
// each tab module:
export async function mount(el, ctx) { ... }   // ctx = { store, api, params, signal }
export function unmount() { ... }              // charts destroyed, intervals cleared via ctx.signal
```

`ctx.signal` is an `AbortSignal` the router aborts on navigation; every poll loop and fetch in a tab is tied to it, which kills the "stray setInterval" class of bugs for good.

### 3.3 API client contract

```js
api.get(path, {params})      api.post(path, body, {admin:true})  api.put / api.del
```
- Prefixes `/api/v1` and `/admin` resolved by helper (`api.games('/simulate-week')`, `api.admin('/schedule/report')`).
- Always `credentials:'include'`; `admin:true` also attaches `X-Admin-Password` from a settings field stored in sessionStorage (for the 11 `app.py` routes until they are moved).
- Throws `ApiError{status, code, message, body}` on `!r.ok` **or** `body.ok===false` / `body.error`. Toast on error by default; opt out per call.
- Long-op convention: any 202 with `{task_id, poll_url}` returns a `Task` handle the task-runner component can watch.

### 3.4 Backend changes that the new UI depends on

| # | Change | Why | Size |
|---|---|---|---|
| B1 | **Scheduled jobs system** (section 4) | the headline feature | L |
| B2 | **Timeline endpoint** `GET /admin/timeline?league_year_id=` (section 5) | one read for the timeline view | M |
| B3 | **Command-center summary** `GET /admin/summary`: enhanced timestamp + running tasks + next 3 scheduled runs + alerts (RunGames stuck, failed runs, trades awaiting approval, checklist step due) | one call for the landing page | S |
| B4 | **Move the 11 `app.py` `/admin/*` routes into the admin blueprint** under session auth (keep header auth as an alternative so curl/runbook still work) | one auth model, one place | S |
| B5 | **Run long synchronous ops as jobs**: `end-season`, `season/archive`, `schedule/generate`, `transactions/end-of-season`, `recruiting/advance-week` (x20 helper) via the job runner (section 4.3). Existing sync routes stay; jobs are the additive path | gunicorn timeout is 45 s; archive is 268 s | M |
| B6 | **Admin auth on season-mutating `/api/v1` routes** (games run/advance/end/start/set-*, playoffs mutations, recruiting/ifa/fa admin advances, player-ops progress-all): a `require_admin_or_key()` decorator accepting session cookie *or* `X-Admin-Password` *or* an `ADMIN_API_KEY` | today anyone can POST end-season. The scheduler calls services directly so it is unaffected | S |
| B7 | **`POST /admin/sim/clear-run-games`** (clears a stuck `run_games` flag, logs when) | currently fixed with hand SQL; the UI hides sim buttons until it is cleared | S |
| B8 | Normalise task status casing to lowercase everywhere; add `GET /games/tasks?status=running` filter | kill the `'complete'`/`'COMPLETE'` checks | S |
| B9 | **Unify "league-year context"**: every admin GET accepts `league_year_id`; endpoints that take `league_year` (year number) also accept `league_year_id` and resolve | the Y vs L confusion is the runbook's #1 footgun | S |

B6 and B7 are behavioural changes to existing routes and need explicit sign-off **[DECIDE]**; everything else is additive.

---

## 4. Scheduled jobs ("cron") design

### 4.1 Tables

```sql
CREATE TABLE scheduled_jobs (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  name            VARCHAR(120) NOT NULL,
  job_type        VARCHAR(64)  NOT NULL,          -- key into the job registry (4.3)
  params_json     JSON NULL,                       -- job-type specific args
  schedule_kind   ENUM('cron','interval','once','manual') NOT NULL,
  cron_expr       VARCHAR(64) NULL,                -- 5-field, evaluated in `timezone`
  interval_s      INT NULL,
  run_at          DATETIME NULL,                   -- for 'once'
  timezone        VARCHAR(64) NOT NULL DEFAULT 'America/New_York',
  enabled         TINYINT(1) NOT NULL DEFAULT 1,
  guards_json     JSON NULL,                       -- {"require_phase":["REGULAR_SEASON"], "skip_if_run_games":true, "pause_on_failure":true, "max_runs":null}
  next_run_at     DATETIME NULL,                   -- UTC, recomputed after each run
  last_run_at     DATETIME NULL,
  last_status     VARCHAR(16) NULL,
  runs_count      INT NOT NULL DEFAULT 0,
  created_at      DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  INDEX (enabled, next_run_at)
);

CREATE TABLE job_runs (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  job_id          INT NULL,                        -- NULL for ad-hoc "fire this job type now"
  job_type        VARCHAR(64) NOT NULL,
  params_json     JSON NULL,
  trigger_kind    ENUM('schedule','manual','chain') NOT NULL,
  status          ENUM('queued','running','succeeded','failed','skipped') NOT NULL,
  skip_reason     VARCHAR(255) NULL,               -- guard that blocked it
  claimed_by      VARCHAR(64) NULL,                -- hostname:pid of the runner
  heartbeat_at    DATETIME NULL,
  started_at      DATETIME NULL, finished_at DATETIME NULL,
  task_id         VARCHAR(32) NULL,                -- background_tasks.id when the job wraps a task
  summary_json    JSON NULL,                       -- small structured result (games simmed, week advanced to, etc.)
  log_text        MEDIUMTEXT NULL,                 -- captured log lines
  error           TEXT NULL,
  INDEX (job_id, started_at), INDEX (status, heartbeat_at)
);
```

`timestamp_state.run_cron` becomes the **global scheduler switch** (already exists, already broadcast on the WS, nothing reads it today). Off = runner ticks but never claims.

### 4.2 Runner: `services/job_scheduler.py`

Copy the draft-clock shape exactly:

- One daemon thread per process, started from `create_app()` next to the draft clock. Leader election via `GET_LOCK('simbb_job_scheduler', 0)`; followers retry every 15 s. Env `JOB_SCHEDULER_DISABLED=1` and `JOB_SCHEDULER_TICK_S` (default 20).
- Each tick, as leader:
  1. If `run_cron=0` → sleep.
  2. **Reap** runs with `status='running'` and `heartbeat_at < NOW()-INTERVAL 10 MINUTE` → `failed`, error "runner lost"; if the job has `pause_on_failure` → `enabled=0`.
  3. **Claim** due jobs atomically: `UPDATE scheduled_jobs SET next_run_at=<next>, last_run_at=NOW() WHERE id=? AND enabled=1 AND next_run_at<=UTC_TIMESTAMP()` (rowcount 1 wins; safe even if a second leader briefly exists). Insert a `job_runs` row (`queued`, `trigger_kind='schedule'`).
  4. Hand each run to a small `ThreadPoolExecutor(max_workers=2)`; one job type never runs concurrently with itself (per-type `GET_LOCK('simbb_job_<type>')`).
- **Manual fire** (`POST /admin/jobs/<id>/run-now` or `POST /admin/jobs/run {job_type, params}`): the request handler inserts the `job_runs` row as `queued` with `trigger_kind='manual'` and returns `{run_id}`; the leader picks up queued manual runs on the next tick (≤20 s). Optional `?inline=1` for tests runs it in the request thread.
- **Execution wrapper**: creates a `background_tasks` row via `task_store` (so the existing task UI and polling work unchanged), attaches a logging handler that captures lines into `log_text`, heartbeats every 15 s, calls the registered function with `(ctx)` where `ctx` has `set_progress`, `log`, `params`, `engine`. Stores `summary_json`, marks succeeded/failed, recomputes `next_run_at` (via `croniter` **[DECIDE: add `croniter` to requirements vs. hand-roll a 5-field parser]**), broadcasts `{type:'job_run', ...}` over the WS.
- **Chaining**: a job may declare `on_success: [job_type,...]` in params; the wrapper enqueues them with `trigger_kind='chain'`. This gives "sim subweek, then if it was d, advance week" without a second cron entry.

### 4.3 Job registry (`services/jobs/__init__.py`)

Each job type is a Python function calling **existing service code directly** (not HTTP), decorated with metadata the UI uses to build its form:

```python
@job("sim_next_subweek", title="Simulate next subweek", phases=["REGULAR_SEASON"],
     params={"levels": {"type": "list[int]", "default": [9,8,7,6,5,3]},
             "auto_advance": {"type": "bool", "default": True}})
def sim_next_subweek(ctx): ...
```

Initial registry (all map 1:1 onto code that exists today):

| job_type | Calls | Notes |
|---|---|---|
| `sim_next_subweek` | `build_week_payloads(simulate=True, subweek=<first unset of a-d>)` then, if that was d and `auto_advance`, `advance_week()` | **The daily cron.** Skips with reason if `RunGames` set, if all four ran and `auto_advance=false`, or if phase ≠ REGULAR_SEASON. Postseason-aware: once week ≥ TotalWeeks it only sims pending playoff games and never advances a round unless `auto_advance_playoffs=true` |
| `sim_subweek` | one explicit `{week, subweek, levels}` | manual/one-off |
| `advance_week` | `timestamp.advance_week()` | guard: all four subweeks ran |
| `run_week` | `simulate_week` + `advance_week` (same as `/games/run-week`) | for a week-per-day cadence |
| `run_season` | existing `_run_season_task` / `_run_all_levels_task` | wraps existing tasks |
| `stamina_rest` | the stamina-rest service call | |
| `playoffs_process_and_advance` | `playoffs.process_and_advance(level)` | guard: current round complete |
| `fa_advance_round` | `timestamp.advance_fa_round()` | phase FREE_AGENCY |
| `fa_end` | `timestamp.end_free_agency()` | |
| `recruiting_advance_week` | `recruiting.advance_week(ly)` | phase RECRUITING; `times` param (1..20) |
| `ifa_advance_week` | `ifa_signing.advance_week(ly)` | |
| `draft_run_auto_rounds` | existing draft admin function | |
| `books_run_week` / `books_playoff_revenue` / `books_year_end_interest` / `init_next_league_year` | `financials.books.*` | claim-guarded already |
| `end_season` / `archive_season` / `start_new_season` / `schedule_generate` | existing functions | **long**, this is how they get off the request thread (B5) |
| `trade_queue_digest` | counts proposals awaiting approval → summary only | feeds the Command Center alert |
| `offseason_checklist_step` | `{step_key}` → runs that step's action | lets the checklist card use the same runner |

Phase guards use `timestamp.get_current_phase()`, so the registry and the UI agree on what is allowed when.

### 4.4 Admin API

```
GET    /admin/jobs                         list jobs (+ next_run_at, last_status)
POST   /admin/jobs                         create {name, job_type, params, schedule_kind, cron_expr|interval_s|run_at, timezone, guards}
GET    /admin/jobs/types                   registry: types, titles, phases, param schemas (UI builds forms from this)
GET    /admin/jobs/<id>  PUT  DELETE
POST   /admin/jobs/<id>/toggle             enabled on/off
POST   /admin/jobs/<id>/run-now            -> {run_id}
POST   /admin/jobs/run                     ad-hoc {job_type, params} -> {run_id}
GET    /admin/jobs/<id>/preview            dry-run: what would this do right now? (e.g. "week 14 subweek c, 6 levels, 93 games") and next 5 fire times
GET    /admin/jobs/runs?job_id=&status=&limit=
GET    /admin/jobs/runs/<run_id>           status, summary, log_text, linked task
POST   /admin/jobs/runs/<run_id>/cancel    best-effort flag the wrapper checks between stages
GET    /admin/scheduler                    leader host, run_cron flag, tick, last tick time
POST   /admin/scheduler/toggle             sets timestamp_state.run_cron
```

All under the admin blueprint session auth.

### 4.5 Presets shipped with the UI

- **Daily subweek**: `sim_next_subweek`, cron `0 6 * * *`, phase REGULAR_SEASON, auto_advance, pause_on_failure.
- **Weekday week**: `run_week`, cron `0 6 * * 1-5`.
- **Recruiting day**: `recruiting_advance_week`, cron `0 7 * * *`, phase RECRUITING.
- **FA round**: `fa_advance_round`, interval 24 h, phase FREE_AGENCY.
- **Sim to date** (one-off helper, not a job): given a target (e.g. "reach week 30 by Dec 15") it proposes a cron and shows the projected timeline before saving.

**[DECIDE]** Scope of automation for v1: only in-season sim jobs, or also FA/recruiting/playoff advances? The registry is cheap either way; the question is which ones you trust unattended.

---

## 5. Timeline view

### 5.1 Endpoint: `GET /admin/timeline?league_year_id=L`

Returns a single document the UI renders, built from data that already exists:

```json
{
  "league_year": {"id": 3, "year": 2027, "weeks_in_season": 52},
  "now": {"phase": "REGULAR_SEASON", "week": 14, "subweeks": {"a":true,"b":true,"c":false,"d":false}, "run_games": false},
  "segments": [
    {"kind":"regular", "weeks":[1,52], "label":"Regular season"},
    {"kind":"postseason", "weeks":[53,60], "rounds":[{"name":"WC","status":"complete"},{"name":"DS","status":"in_progress"}]},
    {"kind":"offseason", "steps":[ "...the 13 checklist steps with done/pending/manual..." ],
      "sub":[{"kind":"fa","round":3,"open_auctions":41}, {"kind":"draft","phase":"IN_PROGRESS","round":2,"pick":17},
             {"kind":"ifa","week":4}, {"kind":"recruiting","week":9,"of":20}]}
  ],
  "weeks": [ {"week":1, "games":{"scheduled":96,"played":96}, "books_run_at":"...", "injuries_ticked_at":"...", "job_runs":[12,13]} ],
  "scheduled": [ {"job_id":3,"name":"Daily subweek","fires":["2026-11-09T11:00Z"]} ],
  "projection": {"basis":"job 3 (1 subweek/day)", "week_dates": {"15":"2026-11-10", "52":"2027-04-10"}, "postseason_start":"2027-04-11"}
}
```

Sources: `league_years`, `game_weeks` (+ claim columns), `gamelist`/`game_results` counts per week, `timestamp_state`, `playoff_series`, `_build_offseason_checklist()`, `recruiting_state`, `ifa_state`, `draft_state`, FA auction phase counts, `scheduled_jobs` + `croniter` for the fire list, `job_runs` for history. Cached 10 s.

### 5.2 UI

- **Horizontal track** for the league year: regular weeks as cells (color = played / partial / scheduled / future), postseason rounds, then offseason step chips. "Now" marker. Hover = per-week games and books/injury ticks; click = side panel with that week's job runs and tasks.
- **Lower lane**: real-world date axis with planned job fires (hollow dots) and completed runs (filled, red if failed). Projected week→date mapping from the active sim job, so "when will the World Series start at this cadence?" is answered on screen.
- **Offseason mode**: when phase ≠ REGULAR_SEASON the track zooms into the 13 steps with their statuses and Run buttons (this replaces the current checklist card, same backend).
- Pure SVG + CSS; no new chart library.

---

## 6. Information architecture

| Area (URL) | Tabs | Replaces today's sections |
|---|---|---|
| **Command Center** `#/` | Status KPIs (phase, season, week, subweek A-D), alerts, running jobs/tasks, next scheduled fires, quick actions (sim next subweek, advance, open checklist), recent runs | `dashboard`, parts of `simulate`/`timestamp` |
| **Season** `#/season` | Simulate · Phase & Week · Offseason Checklist · Playoffs · Special Events (Awards, All-Star, WBC) · Schedule (Generator, Viewer) | `simulate`, `timestamp`, `playoffs`, `awards`, `allstar`, `wbc`, `schedule-gen`, `schedule-viewer` |
| **Jobs** `#/jobs` | Scheduled Jobs · Run History · Background Tasks · Logs (timing_log, sim_failures) | `tasks`, `synthetic` (moves to a "Run ad-hoc job" form) |
| **Timeline** `#/timeline` | (single view, section 5) | new |
| **Market** `#/market` | FA Auction · FA Market · Draft · IFA · Recruiting (+ admin) · Waivers · Trades (approval queue first) · Transactions Log · Roster Compliance · End of Season · Amateur Seeding | `fa-auction`, `fa-market`, `draft-admin`, `ifa-admin`, `recruiting`, `recruiting-admin`, `tx-*`, `roster-compliance` |
| **Engine** `#/engine` | Generate · Progress · Sandbox · Progression Diagnostics · Training Camp · Rating Config · Growth Curves · Weight Calibration | `pe-*`, `progression-diag`, `rating-config`, `weight-calibration` |
| **Analytics** `#/analytics` | Stats (14 as a sub-nav) · Stamina (5) · Rankings (5) · Gameplan Audit · Batting Lab | all `analytics-*`, `stamina-*`, `rankings-*`, `gameplan-audit`, `batting-lab` |
| **Data** `#/data` | Organizations · Teams · Players · Game Viewer · SQL Console · DB Storage | `organizations`, `teams`, `players`, `game-viewer`, `sql`, `db-storage` |
| **System** `#/system` | Health · Cache · Migrations · Orphan Sweep · Tutorial CMS · Finance (books runs, ledger) · Settings (admin password header, write mode, scheduler switch) | `health`, `cache`, `migrations`, `orphan-sweep`, `tutorial-content` |

Shell behaviours: sidebar collapses to icons; topbar shows phase badge, week, subweek A-D pips and a scheduler on/off pill on every page (fed by the store, updated by WS and a 15 s poll fallback); global league-year selector in the topbar that every tab reads from the store; `Ctrl+K` command palette over tabs and job types.

---

## 7. Migration plan (strangler)

Legacy UI stays at `/admin/legacy` (same files, moved) until Phase 6. New shell at `/admin`. Each phase ends with the listed sections removed from legacy.

| Phase | Deliverable | Depends on | Size |
|---|---|---|---|
| **0 – Foundation** | `core/*`, `ui/*`, shell, router, auth gate, store+WS, CSS tokens. Command Center (B3). Season → Simulate, Phase & Week, Offseason Checklist ported onto task-runner | B3 | M |
| **1 – Jobs** | Tables, runner, registry (in-season types first), admin API, Jobs area, preset wizard. Background Tasks tab reuses the task-runner | B1, B8 | L |
| **2 – Timeline** | B2 endpoint, Timeline area, offseason mode replaces the checklist card. Long ops moved to the runner (B5) | 1, B2, B5 | M |
| **3 – Season rest** | Playoffs (field editor, matchup editor, bracket PNG), Special Events, Schedule Generator/Viewer | 0 | M |
| **4 – Market** | FA, Draft, IFA, Recruiting, Waivers, Trades queue, Tx log, Compliance, EOS, Amateur. Add the missing panels from the docs (FA close summary, `fa_config` card, FA outcomes report, Run Week) | 0 | L |
| **5 – Analytics & Engine** | Mostly mechanical: table + chart components make the 24 analytics/stamina/rankings panels thin. Calibration, gameplan audit, batting lab, player engine, progression diag | 0 | M |
| **6 – Data, System, cleanup** | Orgs/Teams/Players, SQL console, tutorial CMS, finance tab (B4 routes), settings. Delete `/admin/legacy`, old `app.js`, old `index.html` | B4 | S |
| **Hardening (parallel)** | B6 auth on season routes, B7 clear-run-games, B9 league-year normalisation | sign-off | S |

Sizes are relative (S < M < L); Phases 1 and 4 are the big ones. Phases 3, 4 and 5 are independent of each other and can be interleaved with feature work.

Parity rule per section: every button in legacy has a counterpart, every endpoint it called is still called (or replaced by a job type), checked off in a `docs/admin_revamp_parity.md` checklist generated from the legacy inventory in section 1.

---

## 8. Conventions for the new code

- **Dark theme only**, via `tokens.css` variables; no inline `style=` except computed widths/positions. Tables use `.data-table`.
- **Escape everything** rendered from the API via `format.esc()`; the table component escapes by default and requires an explicit `html:true` column flag to opt out.
- **No `alert/confirm/prompt`**; use `toast`, `confirm()`, `modal.form()`.
- **No module-level mutable state** inside features; use the tab's local closure plus `store` for shared state.
- **Every poll loop** is a `pollTask(taskId, {signal})` or `pollRun(runId, {signal})` from `ui/task-runner.js`.
- **Destructive actions** (wipe, rollback, archive, end-season, delete job) go through `confirm({danger:true, typeToConfirm:'ARCHIVE'})`.
- **Selectors remember** last choice per area in `localStorage` (wrapped in try/catch).
- **Feature flags**: `window.ADMIN_FLAGS` from the template so a tab can ship dark and be switched on.

---

## 9. Testing

- `tests/test_job_scheduler.py`: next-run computation across DST, claim race (two threads, one wins), reaper marks stale runs, phase guards skip with reason, chain enqueues, `run_cron=0` claims nothing, `sim_next_subweek` picks the right subweek from flag combinations and advances only after d.
- `tests/test_timeline.py`: endpoint shape for regular season, postseason, and each offseason sub-phase using fixtures.
- Registry smoke test: every job type's function is importable and its param schema validates its defaults.
- Frontend: no test framework in Option A. A Playwright smoke script (`scripts/admin_smoke.py`, opt-in) that logs in, visits every tab, and asserts no console errors and no unhandled `ApiError`. Run against the rehearsal DB on 8090.

---

## 10. Risks

- **Multi-worker WS**: broadcasts reach one worker's clients. The store polls `/admin/summary` every 15 s as a fallback, so the UI is eventually consistent without a Redis pub/sub. (A single-worker deploy during live drafts is already the recommendation.)
- **Runner inside gunicorn**: `--max-requests 500` recycles workers; the leader lock is released on process exit and another worker takes over within 15 s, and in-flight runs are reaped and marked failed (never silently re-run). A job that is not idempotent therefore needs its own claim; `sim_next_subweek` is safe because it re-reads the flags. **[DECIDE]** Alternatively run the scheduler as a second Coolify service (`python -m services.job_scheduler`) with `JOB_SCHEDULER_DISABLED=1` on the web workers; cleaner, one more container.
- **Cron in local time**: DST edges; `croniter` handles them; tests cover them.
- **Scope creep**: the missing panels (support tickets admin, scouting department, finance) are listed but Phase 4/6 should ship parity first and add them as follow-ups.

---

## 11. Decisions needed before starting

1. Stack: Option A (ES modules, no bundler, recommended) or Option B (Vite + Preact + TS).
2. `croniter` dependency vs. hand-rolled parser (recommend `croniter`).
3. Default timezone for schedules (recommend `America/New_York`, editable per job).
4. v1 automation scope: in-season only, or also FA / recruiting / playoff advances unattended.
5. Approve B6 (auth on season-mutating `/api/v1` routes) and B7 (clear-run-games endpoint) as behaviour changes.
6. Scheduler placement: leader thread in web workers (recommended, matches draft clock) or a separate container.
7. Go/no-go on moving the 11 `app.py` admin routes into the blueprint (B4).
