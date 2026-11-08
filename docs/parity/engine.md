# Admin revamp parity — Player Engine area (`#/engine/*`)

Legacy sources: `admin/static/admin/app.js` (rating config 2339–2830, player engine 3889–4024, sandbox 4317–4623, calibration 10647–11256, progression diagnostics 13568–13743) and `admin/templates/admin/legacy.html` (`section-rating-config`, `section-pe-generate`, `section-pe-progress`, `section-pe-sandbox`, `section-weight-calibration`, `section-progression-diag`).

New modules: `admin/static/admin/js/features/engine/{generate,progress,sandbox,diagnostics,rating-config,calibration,_shared}.js`.

Conventions applied everywhere: `api.*` (no `fetch`), `confirm()` modals instead of `window.confirm`, `toast` instead of `alert`, `dataTable`/`simpleTable`/`kvTable` for tables, `mountChart(canvas, cfg, ctx.signal)` for every Chart.js instance (no globals, no manual `destroy()` on re-entry), `leagueYearSelect`/`levelSelect` for dropdowns, `runTracked` for long operations. No Python changes were made.

## Generate (`#/engine/generate`) — legacy `section-pe-generate`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| Generate (count, starting age) | `POST /api/v1/player-ops/generate` `{count, age}` | `generate.js` "Generate" — same body; results in a sortable `dataTable` (first 500, truncation note kept); a confirm is added when count ≥ 500 |
| Seed table status (auto on section load) | `GET /api/v1/player-ops/seed-status` | `generate.js` loads on mount; "Refresh" button added |

## Progress (`#/engine/progress`) — legacy `section-pe-progress`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| Progress All Players (max age, `window.confirm`) | `POST /api/v1/player-ops/progress-all` `{max_age}` | `progress.js` — `confirm({danger, typeToConfirm:'PROGRESS'})`, runs through `runTracked` (plain result), `max_age` omitted when the field is cleared (backend accepts null = age everyone) |
| Progress (single player id) | `POST /api/v1/player-ops/progress/<id>` | `progress.js` — same; response JSON shown in a result box |

## Sandbox (`#/engine/sandbox`) — legacy `section-pe-sandbox`

| Legacy control | Endpoint | Now |
|---|---|---|
| Run Simulation (players, seasons, start age, player type) | `POST /admin/progression-sandbox` `{count, seasons, start_age, player_type}` | `sandbox.js` — same body (the optional `tracked_abilities` the backend accepts was never sent by legacy; still not sent) |
| Ability select, P10–P90 bands, Individual players, Grade filter, Highlight player, click-line-to-highlight | (client-side) | all kept; chart via `mountChart`, re-mounted on every option change; `GRADE_COLORS` moved to `_shared.js` |
| Grade Distribution table | (client-side) | `dataTable` (sortable) |

## Progression Diagnostics (`#/engine/diagnostics`) — legacy `section-progression-diag`

Sub-tabs (`subTabs`): Table vs actual · Age profile · League drift · Outliers · Training camp · Player trajectory. Charts render only on the visible pane and are re-mounted on tab switch. Route params: `?pane=<id>&player_id=<n>`.

| Legacy control | Endpoint | Now |
|---|---|---|
| Season (snapshots) dropdown | `GET /admin/analytics/progression-years` | `leagueYearSelect` (global:false) labelled with snapshot stage counts; years without snapshots are labelled "(no snapshots)"; default = global year if it has snapshots, else newest snapshot year |
| Level filter (1–9, All) | — | `levelSelect` with `[...ALL_LEVELS, 2, 1]` (names from `constants.js`) |
| Potential grade select | from curves payload | same (defaults to `B`) |
| Load | `GET progression-curves?league_year_id`, `GET progression-age-profile?level`, `GET progression-drift`, `GET progression-outliers?league_year_id&n=15`, `GET progression-camp?league_year_id` | all five fetched in parallel (`Promise.allSettled`), same params |
| Growth table vs realised chart + table | — | pane "Table vs actual" (flagged `off_by` in red) |
| Age profile chart + peak ages | — | pane "Age profile" |
| League drift chart | — | pane "League drift" + a level × season table (added) |
| Outlier gainers / losers tables, click name → player trajectory | — | pane "Outliers" (`dataTable`, sortable on Δ and z); click switches to the Player pane and loads |
| Training camp summary + effects + skills chosen | `GET /admin/analytics/progression-camp` | pane "Training camp" (same three tables + kv summary) |
| Player trajectory (player id → Load) | `GET /admin/analytics/progression-player/<id>` | pane "Player trajectory"; Enter key loads; link to `#/data/players?player_id=` added |

Training camp admin route check: there is **no** `GET /admin/training-camp/summary`. The only admin-side camp data is `/admin/analytics/progression-camp` (wraps `services.training_camp.admin_summary` + `camp_effects`), which is what the "Training camp" sub-tab uses. The `training_camp` blueprint (`/api/v1/training-camp/options|focus|results`) is org-scoped (requires `org_id`) and is not an admin view, so it was not ported here.

## Rating Config (`#/engine/rating-config`) — legacy `section-rating-config`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| Config Status / Levels Configured stat cards (auto) | `GET /admin/rating-config` | `kpi()` cards, loaded on mount (silently ignores 401/empty like legacy) |
| Analyze & Populate | `POST /admin/rating-config/seed` | same; `confirm({danger})` added; result text identical (rows written + per-level/ptype detail); refreshes cards + level table |
| Load Current (level scale config) | `GET /admin/rating-config` | `dataTable` with editable mean/std inputs, "varies" placeholder when attributes differ, live 20/50/80 recompute |
| Save Changes (level scale) | `PUT /admin/rating-config/levels` `{levels:[{level_id, ptype, mean_value, std_dev}]}` | same body, changed rows only (as legacy); confirm added |
| Attribute Analysis Load (ptype, level, attribute search) | `GET /admin/rating-config?level=&ptype=` | same params; search filters client-side; `dataTable` paged at 100, sortable |
| Overall Rating Weights (info card) | — | kept as a card linking to `#/engine/calibration` |
| Load Curves (grade filter) | `GET /admin/growth-curves` | `dataTable` with editable min/mode/max; grade filter kept; added a read-only "Mean (min+mode+max)/3" column (master plan §13f finding) |
| Save Changes (growth curves) | `PUT /admin/growth-curves` `{updates:[{grade, age, prog_min, prog_mode, prog_max}]}` | same body shape. **Behaviour change:** legacy sent every rendered row; the new tab sends only rows whose values changed (no-op otherwise). Confirm added. |
| — | `PUT /admin/rating-config` (per-attribute updates) | dropped: never called by the legacy UI (backend only) |

## Weight Calibration (`#/engine/calibration`) — legacy `section-weight-calibration`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| League Year dropdown | `GET /admin/analytics/league-years` | `leagueYearSelect` (shared loader, global selection) |
| Level dropdowns (9,8,7,6,5,3) | — | `levelSelect` with `SIM_LEVELS` |
| Run Calibration (min innings / AB / IPO, name) | `POST /admin/calibration/run` `{league_year_id, league_level, config:{min_innings, min_at_bats, min_ipo}, name?}` | same body; confirm added; runs via `runTracked`; results `dataTable` (position, N, confidence badge, Off/Def R², adj R², status, warnings tooltip) |
| Refresh Profiles (auto on entry) | `GET /admin/calibration/profiles` | `dataTable`, active row highlighted; also fills the Compare selects; Compare card shown when ≥2 profiles |
| View (profile) | `GET /admin/calibration/profiles/<id>` | detail card: attribute × 13-rating-type editable grid with sums row, changed cells marked, calibration details collapsible. Heat-map cell backgrounds dropped (inline colour styles are not allowed in the new shell); zero weights are muted, edited cells highlighted instead |
| Save Changes (weights) | `PUT /admin/calibration/profiles/<id>/weights` `{weights}` | same; extra confirm when the profile is active (the call pushes live + recomputes displayovr) |
| Normalize Columns | (client-side) | same |
| Activate (`window.confirm` + `alert`) | `POST /admin/calibration/activate/<id>` | `confirm({danger})` + toast with entries / displayovr count; refreshes list and open detail |
| Compare (A vs B) | `GET /admin/calibration/compare?a=&b=` | same; per-rating-type tables with signed delta |
| Recompute Display OVR (level optional) | `POST /admin/calibration/recompute-displayovr` `{level?}` | same; confirm added; per-level counts shown |
| Player Preview cascade level → org → team → player | `GET /admin/calibration/player-preview/filters?level= / ?org_id=&level= / ?team_id=` | same three calls, same params |
| Preview | `GET /admin/calibration/player-preview?player_id=` | kpi cards (computed displayovr vs stored, weight type + fallback warning, raw/20-80 + peer count), position ratings table with 20-80 badges, raw attributes collapsible, link to the player's progression trajectory |
| — | `POST /admin/calibration/profiles` (create manual profile) | dropped: no legacy UI for it; could be added as "New manual profile" later |
| — | `GET /admin/calibration/displayovr-debug` | dropped: diagnostic endpoint, never surfaced in legacy |
| `window.App.viewCalProfile / activateCalProfile` globals | — | replaced by `data-action` delegation |

## Backend gaps / notes (no Python edited)

1. `POST /admin/progression-sandbox` lives in `app.py` (session check), unlike the other `/admin/*` routes on the blueprint; it returns `{error, message}` on failure (handled by `api.js`). Count max in the UI is kept at 2000 (legacy) although the backend allows 30050.
2. `POST /api/v1/player-ops/progress-all` and `/generate` are synchronous; for 5000-player generations or a full progression pass they can exceed the proxy timeout. A `{task_id}` response (or a job type) would let `runTracked` poll instead — the UI is already written against `runTracked`.
3. `GET /admin/calibration/run` can be slow too (OLS over a season); same remark.
4. Progression Diagnostics has no admin endpoint for per-org training-camp focus lists; only the league-wide summary via `progression-camp`. If an admin camp view is wanted, a `GET /admin/training-camp/summary?league_year_id=` (or `org_id` filter on the existing `/api/v1/training-camp/focus` without the org guard) is needed.
5. `GET /admin/rating-config` returns the full table (all attributes × levels × ptypes) for the summary cards; a lightweight `?summary=1` would save a few hundred KB per mount.
