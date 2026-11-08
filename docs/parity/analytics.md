# Admin revamp parity — Analytics area

Legacy sources: `admin/static/admin/app.js` (Analytics 5109–6694, Stamina 6844–7317, Batting Lab 10455–10646, Gameplan Audit 11257–11749, Rankings 12051–12573, wiring at 271–343) and `admin/templates/admin/legacy.html` (sections `analytics-*` 2098–2812, `gameplan-audit` 3324–3424, `stamina-*` 3480–3618, `rankings-*` 3621–3779, `batting-lab` 4537–4596).

New home: `admin/static/admin/js/features/analytics/`

| File | Role |
|---|---|
| `_shared.js` | `reportTabs()` sub-tab shell with shared filter bar (league year / level / team) and per-report controls + Load; `childScope()` nested AbortControllers; formatting + heat-cell helpers; `rangeField()` |
| `stats.js` | Analytics tab: 14 reports as `subTabs`; active report in URL `?report=` |
| `_stats_a.js` | batting / pitching / defense correlations, WAR, regression, sensitivity, xStats, interactions; the stat/attr option lists |
| `_stats_b.js` | stat tuning dashboard, archetypes, pitch types, defensive positions, contact breakdown, HR depth |
| `stamina.js` | 5 stamina reports as `subTabs` |
| `rankings.js` | 5 rankings as `subTabs` |
| `gameplans.js` | gameplan audit overview + per-team viewer/editor |
| `batting-lab.js` | tier-sweep runner, run history, results |

Routes: `#/analytics/stats?report=<id>`, `#/analytics/stamina?report=<id>`, `#/analytics/rankings?report=<id>`, `#/analytics/gameplans?level=&team_id=`, `#/analytics/batting-lab?run=`. The shell also writes `league_year_id`, `level`, `team_id` after each load so a report URL is shareable.

## Shared controls (de-duplicated)

| Legacy | New |
|---|---|
| `loadAnalyticsLeagueYears()` (5116), `loadStaminaLeagueYears()` (6867), `loadRankingsLeagueYears()` (12059) — 3 copies of `GET /admin/analytics/league-years` | one `leagueYearSelect()` per tab (ui/selectors.js, cached in the store, bound to the global year) |
| 24 hand-written `<select>` level lists (`an-*-level`, `stam-*-level`, `rank-*-level`, `gpa-level`, `blab-level`) | `levelSelect()` with `ALL_LEVELS` / `SIM_LEVELS` from core/constants.js. Stamina lists had non-existent levels 1 and 2; dropped |
| team loader inside `loadStaminaLeagueYears` — `GET /admin/analytics/teams` | `teamSelect()` (shared loader) |
| per-section `*-status` text nodes | one status line in the shell; API errors also toast via api.js |
| `BATTING_STATS` / `PITCHING_STATS` / `BATTING_ATTRS` / `PITCHING_ATTRS`, `populateStatDropdown`, `populateAttrDropdown` | `_stats_a.js` exports the lists; `catControls()` + `initCat()` refill stat/attr selects when the category changes |
| `correlationColor()` (light-theme white→green/red) | `heatColor()` / `seqColor()` translucent overlays for the dark theme |

Behaviour: Stats reports load on the **Load** button (or Enter in a control), as before. Stamina and Rankings reports are cheap, so they also auto-load when the sub-tab is selected or a shared filter changes (`auto: true`). Switching sub-tabs aborts the previous report's scope, which destroys its charts and in-flight fetches.

`not_enough_data`: the backend answers `{ok:true, error:"not_enough_data", n}`; api.js does not throw on it, so each report checks `notEnough(data)` and shows the legacy "Not enough data (n=…)" hint.

## Stats (14 reports) — `stats.js` + `_stats_a.js` / `_stats_b.js`

| Legacy control / element | Endpoint | New location | Notes |
|---|---|---|---|
| `btn-an-bat-load`, `an-bat-min-ab` | `GET /admin/analytics/batting-correlations?league_year_id&league_level&min_ab` | report `batting`, control Min AB | heatmap via `rawTable` + `heatCell` |
| heatmap cell `onclick=App.drillCorrelation('batting',…)` | same + `drill_attr&drill_stat` | delegated click on `td[data-attr]` | scatter via `mountChart`, regression line dataset |
| `btn-an-bat-back` | — | `data-action="corr-back"` | toggles heat/scatter cards |
| scatter point click → `renderPlayerDetail` | — | chart `onClick` → kpi rows of `all_stats` / `all_attrs` | adds "Open player" link to `#/data/players?player_id=` |
| `btn-an-pit-load`, `an-pit-min-ipo`, back, drill | `GET /admin/analytics/pitching-correlations?…&min_ipo` | report `pitching` | |
| `btn-an-def-load`, `an-def-pos`, `an-def-min-inn`, back, drill | `GET /admin/analytics/defensive-analysis?…&min_innings[&position_code]` | report `defense`; Position select filled from `data.positions` after load (`fillSelect`) | |
| `btn-an-war-load`, `an-war-min-ab`, `an-war-min-ipo`, sliders `an-war-repl/wb/wbr/wf/wp` with `*-val` spans | `GET /admin/analytics/war-leaderboard?…&min_ab&min_ipo&replacement_pct&w_batting&w_baserunning&w_fielding&w_pitching&page&page_size` | report `war`; `rangeField()` sliders with live `<output>` | `replacement_pct` sent as fraction (value/100) as before |
| `btn-war-prev` / `btn-war-next`, `an-war-page-info`, `warPage` | same endpoint paged 50 | **dropped**: the report fetches `page_size=200` for every page (cap 15 pages = 3000 players, noted in status) and `dataTable` pages 50/sorts client-side | sortable on every numeric column |
| `an-war-avgs` league context cards | — | `kpiRow` (Lg wOBA/OPS/ERA/FIP, Repl wOBA/FIP, R/PA, cFIP) | |
| `btn-an-reg-load`, `an-reg-cat/stat/min` | `GET /admin/analytics/multi-regression?…&category&target_stat&min_threshold` | report `regression` | coefficients + over/under tables (`dataTable`) |
| `btn-an-sens-load`, `an-sens-cat/attr/stat/min` | `GET /admin/analytics/sensitivity?…&category&target_stat&attribute&min_threshold` | report `sensitivity` | bar+line dual-axis chart; diminishing-returns badge |
| `btn-an-xs-load`, `an-xs-cat/min` | `GET /admin/analytics/xstats?…&category&min_threshold` | report `xstats` | model-fit table with Good/Moderate/Weak badge; players table (pageSize 30, hover = actual/expected) |
| `btn-an-int-load`, `an-int-cat/attr-a/attr-b/stat/min` | `GET /admin/analytics/interactions?…&category&target_stat&attr_a&attr_b&min_threshold` | report `interactions` | R² kpis + significance badge; grid heat scale now normalised min→max of cell means (legacy used `mean*2-0.5`) |
| `btn-an-dash-load`, `an-dash-cat/stat/min` | `GET /admin/analytics/stat-dashboard?…&category&target_stat&min_threshold` | report `dashboard` ("Stat tuning") | benchmark kpis, distribution kpis + histogram, attribute rankings, stat-vs-stat |
| `btn-an-arch-load`, `an-arch-min` | `GET /admin/analytics/archetypes?…&min_ab` | report `archetypes` | league-average row moved to the table footer; cells coloured vs league |
| `btn-an-pt-load`, `an-pt-min` | `GET /admin/analytics/pitch-types?…&min_ipo` | report `pitchtypes` | two sortable tables |
| `btn-an-dp-load`, `an-dp-min` | `GET /admin/analytics/defensive-positions?…&min_innings` | report `defpos` | one card per position |
| `btn-an-ct-load`, `an-ct-min-ab` | `GET /admin/analytics/contact-breakdown?…&min_ab` | report `contact` | all 8 cards: odds (table+chart), distance weights (heat table), expected vs actual (chart+table), outcomes (kpis+chart), power tiers, contact tiers (tables+line charts), per contact type (table+stacked bar), leaders |
| `.an-ct-leader-btn` ×5 (`iso, hr_pct, babip, xbh_pct, k_pct_low`) | — (client-side from `data.leaders`) | button group `#ct-leader-btns [data-leader]`; active = `btn-primary` | |
| `btn-an-hrd-load`, `an-hrd-gtype` | `GET /admin/analytics/hr-depth?league_year_id&league_level&game_type` | report `hr-depth` | summary kpis, doughnut + bar + cross-tab heat table + stacked bar |

Legacy `App.drillCorrelation` global and the `showAnalyticsView` id juggling are gone; all state is inside `mount()`/`run()`.

## Stamina (5 reports) — `stamina.js`

| Legacy control | Endpoint | New location | Notes |
|---|---|---|---|
| `btn-stam-ov-load`, `stam-ov-level` | `GET /admin/analytics/stamina-overview?league_year_id[&league_level]` | report `overview` (level optional) | 5 summary values → kpis; dual histogram → `mountChart`; team table → `dataTable` (tracked/total labels kept) |
| `btn-stam-tm-load`, `stam-tm-team` | `GET /admin/analytics/stamina-team?league_year_id&team_id` | report `team` (team required) | `staminaBar()` uses `.progress-container/.progress-fill`; untracked rows `row-muted` |
| `btn-stam-av-load`, `stam-av-level` | `GET /admin/analytics/stamina-availability?league_year_id[&league_level]` | report `availability` | CRITICAL/WARNING/OK badges |
| `btn-stam-con-load`, `stam-con-level` | `GET /admin/analytics/stamina-consumption?league_year_id[&league_level]` | report `consumption` | OVERWORKED → `row-danger`, FATIGUED → `row-warning`, NO DATA → `row-muted` |
| `btn-stam-fl-load`, `stam-fl-team` (optional) | `GET /admin/analytics/stamina-flow?league_year_id[&team_id]` | report `flow` | line chart (dual axis) + table |

## Rankings (5) — `rankings.js`

| Legacy control | Endpoint | New location | Notes |
|---|---|---|---|
| `btn-rank-elo-load`, `rank-elo-k` | `GET /admin/analytics/rankings-elo?league_year_id&league_level&k_factor` | report `elo` | table row click / legend click highlight a team (dim others), as before; highlighted row gets `row-success` instead of inline background |
| `btn-rank-pow-load`, `rank-pow-weeks` | `GET /admin/analytics/rankings-power?…&recent_weeks` | report `power` | stacked horizontal bar + table; raw component values in cell tooltips |
| `btn-rank-rpi-load` | `GET /admin/analytics/rankings-rpi?…` | report `rpi` | |
| `btn-rank-pyth-load`, `rank-pyth-exp` | `GET /admin/analytics/rankings-pythagorean?…&exponent` | report `pythagorean` | actual vs expected wins chart + table |
| `btn-rank-race-load` | `GET /admin/analytics/rankings-race?…` | report `race` | one card/chart per group; `raceCharts[]` global replaced by the run scope |

Team colours use `t.color_one` when present, else the shared chart palette (legacy 30-colour palettes dropped).

## Gameplan audit — `gameplans.js`

| Legacy control | Endpoint | New location | Notes |
|---|---|---|---|
| `btn-gpa-load`, `gpa-level` | `GET /admin/gameplan-audit[?level=]` | Load button / level change (`SIM_LEVELS`, All) | overview is a sortable `dataTable` with Y/N badges and View buttons; `?team_id=` in URL reopens the team |
| row `onclick=window._gpaViewTeam(id)` | — | `data-action="view"` | global removed |
| `btn-gpa-edit-toggle` | — | `data-action="toggle-edit"` | roster fetched lazily: `GET /admin/gameplan-audit/roster?team_id=` |
| Close button (inline onclick) | — | `data-action="close"` | |
| `.gpa-save-btn[data-section=defense]` + `+ Add Row` + per-row X | `PUT /api/v1/gameplanning/team/<id>/defense {assignments}` | `data-action="save"` / `def-add` / `rm-row` | same body shape |
| rotation size select + slot selects, save | `PUT /api/v1/gameplanning/team/<id>/rotation {rotation_size, slots}` | `#gpa-rot-size` change resizes slots | |
| bullpen rows, `+ Add Pitcher`, save | `PUT /api/v1/gameplanning/team/<id>/bullpen {pitchers}` | `bp-add` / `rm-row` | |
| strategy form, save | `PUT /api/v1/gameplanning/team/<id>/strategy {...}` | `form-grid` | |
| lineup 9 rows, save | `PUT /api/v1/gameplanning/team/<id>/lineup {slots}` | | |
| `btn-gpa-ps-load` | `GET /admin/gameplan-audit/player-strategies?team_id=` | `data-action="ps-load"` | |
| per-row Save (`window._gpaSaveOnePlayer`) | `PUT /api/v1/gameplanning/org/<org>/player/<pid>/strategy` | `data-action="ps-save"` | global removed |
| Save All Strategies | same, one PUT per row | `data-action="save" data-section="playerstrat"` | `Promise.allSettled`, reports saved/total, toasts failures |
| after save: `GET /admin/gameplan-audit?team_id=` refresh | same | `refreshTeam()` also updates the overview row | |
| `_GPA_POS_LABEL` map | — | **dropped** per rule 9; `posLabel()` uses `POSITIONS` from constants and upper-cases unknown codes (`fb`, `sb`, `tb` render as FB/SB/TB) — see gaps |

## Batting lab — `batting-lab.js`

| Legacy control | Endpoint | New location | Notes |
|---|---|---|---|
| `btn-blab-run`, `blab-level`, `blab-games`, `blab-label` | `POST /admin/batting-lab/run {league_level, games_per_tier, label}` | `data-action="run"` through `runTracked` (synchronous call, indeterminate progress) | result message toasted; history reloaded; results opened |
| `loadBlabHistory()` on section open | `GET /admin/batting-lab/runs` | on mount + Refresh button; `dataTable` pageSize 25 | |
| `App.loadBlabResults(id)` View buttons | `GET /admin/batting-lab/results/<id>` | `data-action="view"`; `?run=` restores | two charts via `mountChart` (results scope), sortable table |

## Dropped / changed on purpose

- WAR server-side Prev/Next paging → client-side `dataTable` paging over all fetched pages.
- Light-theme inline colours (`#4caf50`, `#f44336`, `background:#f0f0f0`, `#fdf2f2`, …) → `text-success/danger/warning`, `row-*` classes, `badge`. Only data-derived values (heat-cell backgrounds, stamina bar widths) remain inline.
- Per-section global chart variables (`analyticsScatterChart`, `sensitivityChart`, `dashHistChart`, `contact*Chart`, `hrd*Chart`, `staminaOverviewChart`, `staminaFlowChart`, `rank*Chart`, `raceCharts`, `blab*Chart`) → `mountChart` bound to per-run scopes.
- `window._gpaViewTeam`, `window._gpaSaveOnePlayer`, `App.drillCorrelation`, `App.loadBlabResults` globals → delegated `data-action` handlers.
- Stamina level lists containing levels 1/2 → `ALL_LEVELS`.

## Backend gaps / follow-ups (not changed here)

1. **Gameplan position labels**: `/admin/gameplan-audit` defense assignments carry only `position_code` (`c, fb, sb, tb, ss, lf, cf, rf, dh, p`). `core/constants.js` `POSITIONS` has no entries for `fb/sb/tb`, so those render as `FB/SB/TB`. Either add the gameplanning codes to `POSITIONS` in constants (core is out of scope for this port) or return a `position_label` in the payload.
2. **WAR leaderboard** caps `page_size` at 200; a `page_size=0`/"all" option (or a `limit` param) would let the client avoid the multi-page fetch loop.
3. **Gameplanning enumerations** (`LINEUP_ROLES`, `BP_ROLES`, spacing, approaches, usage, pull tendency) are duplicated as constants in `gameplans.js`; a `GET /api/v1/gameplanning/enums` would remove the duplication.
4. `not_enough_data` is returned with `ok:true`; returning `ok:false` with a 422 would let api.js surface it uniformly (would also need the legacy UI updated).
