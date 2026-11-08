# Admin revamp parity — Season area: Playoffs, Special Events, Schedule (`#/season/{playoffs,events,schedule}`)

Legacy sources: `admin/static/admin/app.js` (schedule generator 4624–4847, schedule viewer 4848–5108 + button wiring 355–368, `loadSpecialEventLeagueYears` 7322, awards 7339–7561, playoffs 7562–9012, all-star 9013–9133, WBC 9134–9216) and `admin/templates/admin/legacy.html` (`section-schedule-gen` 2991–3092, `section-schedule-viewer` 3093–3285, `section-playoffs` 3782–3920, `section-awards` 3921–3985, `section-allstar` 3986–4150, `section-wbc` 4151–4186).

New modules: `admin/static/admin/js/features/season/{playoffs,events,schedule}.js`, helpers `_playoffs_bracket.js` (bracket tables + canvas PNG export), `_playoffs_editors.js` (field/seed, conference-seed, NCAA 64-team and matchup editors), `_shared.js` (`childSignal` added for sub-tab teardown).

Conventions applied everywhere: `api.*` (no `fetch`; `data.error` handling is done by `ApiError`), `confirm()` modals instead of `window.confirm`, `openModal` instead of `prompt()`, `toast` instead of `alert`, `dataTable`/escaped markup for tables, `leagueYearSelect`/`levelSelect` for dropdowns (replaces `loadSpecialEventLeagueYears` and the hard-coded level `<option>` lists), every listener/timer tied to `ctx.signal` (sub-tabs get a child `AbortController`). No Python changes were made. Every endpoint below was verified against `playoffs/__init__.py`, `awards/__init__.py`, `allstar/__init__.py`, `wbc/__init__.py` and `admin/__init__.py`.

Summary: **71 legacy controls/calls ported, 1 replaced by a link (stamina rest), 0 dropped.** Behaviour additions are marked *(added)*.

## Playoffs (`#/season/playoffs`) — legacy `section-playoffs`

Header: league year (`leagueYearSelect`, global) + level (`levelSelect`, `SIM_LEVELS` 9/8/7/6/5/3, remembered, `?level=` deep link). *(added)* bracket, pending games, status banner, matchup editor, WS rule and skeleton are loaded automatically on mount and on every year/level change (legacy required "Refresh").

| Legacy button / action | Endpoint | Now |
|---|---|---|
| `po-lyid` league year select (`loadSpecialEventLeagueYears`) | `GET /admin/analytics/league-years` | `leagueYearSelect` (cached in store) |
| `po-level` change → show/hide conf-tournament controls, relabel Preview button, hide editors | (client) | `onLevelChange()` — same + auto reload |
| Preview / Edit Field (`btn-po-preview`) levels 5–9 | `GET /api/v1/playoffs/field/<ly>/<level>` | "Preview / Edit Field" → field editor card (MLB AL/NL tables or flat MiLB table; W/L/Pct live-update on team swap) |
| Preview button at level 3 ("Set CWS Field Manually") | — | opens the NCAA 64-team editor (same as legacy) |
| `format === 'ncaa'` read-only field preview | same | `renderNcaaField` in "Playoff Field" card |
| Generate Bracket (`btn-po-generate`) | `POST /api/v1/playoffs/generate` `{league_year_id, league_level}` | "Generate Bracket" — status + toast, renders returned `field`, reloads |
| Generate from Edited Field (`btn-po-generate-edited`) | `POST /api/v1/playoffs/generate` `{…, field}` | "Generate from Edited Field" — seed validation 1..6 per conf (MLB) / 1..8 (MiLB) kept |
| Auto-resequence Seeds (`btn-po-resequence`) | (client) | same |
| Reset to Computed (`btn-po-fieldedit-reset`) | re-runs preview | same |
| Cancel (`btn-po-fieldedit-cancel`) | (client) | same |
| Process Results (`btn-po-process`) | `POST /api/v1/playoffs/process-results` | "Process Results" |
| Advance Round (`btn-po-advance`) | `POST /api/v1/playoffs/advance` | "Advance Round" |
| Process & Advance (`btn-po-procadv`) | `POST /api/v1/playoffs/process-and-advance` | "Process & Advance" — same college/MLB summary text |
| Health Check (`btn-po-health`) | `GET /api/v1/playoffs/health/<ly>/<level>` | "Health Check" — `alertBox` on ok, severity-badged table otherwise |
| Rest Week (Stamina) (`btn-po-rest`, `prompt` + dry-run preview + `confirm`) | `POST /api/v1/games/stamina-rest` | **replaced by a link** to `#/season/simulate` (Stamina rest card: level, subweeks, full reset, dry run). Not duplicated per task brief. |
| Refresh (`btn-po-refresh`) | bracket + pending GETs | "Refresh" |
| Wipe Playoffs (`btn-po-wipe`, `window.confirm`) | `POST /api/v1/playoffs/wipe` | "Wipe Playoffs" — `confirm({danger, typeToConfirm:'WIPE'})`, hides bracket/pending/field cards |
| Status banner (`loadPlayoffStatus`) | `GET /api/v1/playoffs/status/<ly>/<level>` | `alertBox` (simulate→warning, advance→info, complete→success) with series counts |
| Bracket card (`loadPlayoffBracket`) | `GET /api/v1/playoffs/bracket/<ly>/<level>` | `renderMainBracket` (rounds, CWS_* labels, CWS bracket table + champion line), `renderNcaaBracket` for level 3 |
| Conference Tournaments card (per-conf `<details>`, round labels Final/Semifinal/…) | same payload `conf_tournaments` | `renderConfTournaments` |
| Per-conference PNG button (`.btn-png-conf`) | `GET /api/v1/playoffs/bracket-skeleton/<ly>/<level>` (cached, re-fetched if missing) | `data-action="png-conf"` — same |
| Download PNG (`btn-po-png`) — level 3 downloads all NCAA-stage brackets staggered | skeleton | "Download PNG" — same (canvas code ported verbatim to `_playoffs_bracket.js`) |
| Download All PNGs (`btn-bracket-png-all`) | skeleton | "Download All PNGs" — same |
| Pending Games card + per-row Move (`.btn-resched`) | `GET /api/v1/playoffs/pending-games/<ly>/<level>`, `POST /api/v1/playoffs/reschedule-game` `{game_id, season_week, season_subweek}` | same table + Move button |
| World Series home-field select + Save Rule (`btn-po-ws-home-save`, MLB only) | `GET /api/v1/playoffs/settings/9?league_year_id=`, `POST /api/v1/playoffs/settings/9` `{ws_home_field}` | same, incl. All-Star-result info text |
| Adjust Matchups card (latest editable round), team select pre-fills seed, Reset (`btn-po-matchups-reset`), Save (`btn-po-matchups-save`, `window.confirm`) | `GET /api/v1/playoffs/matchups/<ly>/<level>`, `POST /api/v1/playoffs/set-matchups` `{league_year_id, league_level, round, matchups}` | same; save uses `confirm({danger})` with the pairing summary |
| Preview / Edit Seeds (`btn-ct-preview`) | `GET /api/v1/playoffs/conf-tournaments/field/<ly>` | "Preview / Edit Conf Seeds" → per-conference `<details>` seed tables |
| Generate from Edited Seeds (`btn-ct-generate-edited`) | `POST /api/v1/playoffs/conf-tournaments/generate` `{league_year_id, fields}` | same validation (1..N per conf) |
| Auto-resequence / Reset / Cancel (`btn-ct-resequence`, `btn-ct-fieldedit-reset`, `btn-ct-fieldedit-cancel`) | (client) | same |
| Generate Conf Tournaments (`btn-ct-generate`) | `POST /api/v1/playoffs/conf-tournaments/generate` `{league_year_id}` | same |
| Advance Conf Tournaments (`btn-ct-advance`) | `POST /api/v1/playoffs/conf-tournaments/advance` | same summary text |
| Wipe Conf Tournaments (`btn-ct-wipe`, `window.confirm`) | `POST /api/v1/playoffs/conf-tournaments/wipe` | `confirm({danger, typeToConfirm:'WIPE'})` |
| NCAA editor: Suggest Field (`btn-ncaa-suggest`), ranking select, champion dropdowns | `POST /api/v1/playoffs/ncaa/suggest` `{league_year_id, ranking, champions}` | same; duplicate teams highlighted with `row-danger` (legacy: red outline) |
| NCAA editor: Generate Bracket from This Field (`btn-ncaa-generate`, `window.confirm`) | `POST /api/v1/playoffs/generate` `{league_year_id, league_level: 3, field}` | same (64-slot check + duplicate check kept) |
| NCAA editor: Close (`btn-ncaa-cancel`) | (client) | same |

## Special Events (`#/season/events`) — one league-year selector, three sub-tabs (`?sub=awards|allstar|wbc`)

### Awards — legacy `section-awards`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| `aw-lyid` season select (`initAwardsSection`) | `GET /admin/analytics/league-years` | shared `leagueYearSelect` in tab header; changing it clears the selection and reloads the board |
| Award type select (individual trophies only), League/Position field toggling, placeholder by `ptype_scope` | `GET /api/v1/awards/types` | same |
| Player search (debounced 250 ms, scoped by pitcher/hitter, click to select, pre-select position) | `GET /admin/players/search?q=&league_level=9&league_year_id=&limit=25` | same; results are an inline table with "Pick" buttons instead of an absolutely-positioned dropdown (no custom CSS allowed) |
| Assign Award (`btn-aw-assign`, `window.confirm` for rank 1) | `POST /api/v1/awards` `{player_id, league_year_id, award_code, sub_league, position_code, rank, created_by:'admin_panel'}` | same body; `confirm()` for rank 1 |
| Sync Postseason Awards (`btn-aw-sync-postseason`) | `POST /api/v1/awards/sync-postseason` `{league_year_id}` | same summary text |
| Refresh (`btn-aw-refresh`) / board (team awards summarised by team) | `GET /api/v1/awards/season/<ly>?league_level=9` | same |
| Revoke (`.aw-revoke`, `window.confirm`) | `DELETE /api/v1/awards/<award_id>` | `confirm({danger})` |

### All-Star Game — legacy `section-allstar`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| `as-lyid` / `as-level` selects | league-years | shared `leagueYearSelect`; `levelSelect(SIM_LEVELS)` |
| Roster entry: label, 9 lineup (C…DH), 12 SP, 4 RP, 11 bench per side; count validation | (client) | generated from `AS_LINEUP`/constants, same `data-pos` payload shape and the same 12/4/9/11 validation |
| Create Event (`btn-as-create`) | `POST /api/v1/allstar/create` `{league_year_id, league_level, home, away}` | same; fills Event ID |
| Simulate Game (`btn-as-simulate`) | `POST /api/v1/allstar/<id>/simulate` | same, behind a `confirm()` |
| Load Rosters (`btn-as-refresh`) | `GET /api/v1/allstar/<id>/rosters`, `GET /api/v1/allstar/<id>/results` | same |
| *(added)* existing All-Star events for the year with "Use" button | `GET /api/v1/special-events?league_year_id=&event_type=allstar` | lets you find the event ID without the DB |

### World Baseball Classic — legacy `section-wbc`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| `wbc-lyid` select | league-years | shared `leagueYearSelect` |
| Check Eligible Countries (`btn-wbc-countries`) | `GET /api/v1/wbc/eligible-countries` | same |
| Create Event (`btn-wbc-create`) | `POST /api/v1/wbc/create` `{league_year_id}` | same, behind a `confirm()`; fills Event ID |
| Generate Rosters / Generate Pool Games / Process Pool Results / Generate Knockout / Advance Knockout (`wbcAction`) | `POST /api/v1/wbc/<id>/{generate-rosters,generate-pool-games,process-pool-results,generate-knockout,advance-knockout}` | same; full JSON response in a result box (legacy showed the first 200 chars) |
| Cleanup (`btn-wbc-cleanup`) | `POST /api/v1/wbc/<id>/cleanup` | same, `confirm({danger, typeToConfirm:'CLEANUP'})` |
| Refresh Teams (`btn-wbc-refresh`) / teams table (eliminated rows dimmed) | `GET /api/v1/wbc/<id>/teams` | sortable `dataTable`, `row-muted` for eliminated |
| *(added)* existing WBC events for the year with "Use" button | `GET /api/v1/special-events?league_year_id=&event_type=wbc` | |

## Schedule (`#/season/schedule`) — sub-tabs Generator / Viewer (`?sub=generator|viewer`)

Year inputs default to the calendar year of the globally selected league year (legacy hard-coded 2027). The `/admin/schedule/*` endpoints key on `league_year`/`season_year` (calendar year), exactly as legacy sent them.

### Generator — legacy `section-schedule-gen`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| Refresh Report (`btn-sched-report`) | `GET /admin/schedule/report` | sortable `dataTable`; *(added)* auto-loads on mount |
| Level select with game counts ("9 - MLB (162 games)") + start-week rule (MLB locked to 1, MiLB default 10, College 1) | (client) | `levelSelect(ALL_LEVELS)`; game counts moved to the card blurb and the Generate confirm; start-week rule ported |
| Validate (`btn-sched-validate`) | `GET /admin/schedule/validate?league_year=&league_level=` | same text in result box + success/danger `alertBox` |
| Generate (`btn-sched-generate`, `window.confirm`) | `POST /admin/schedule/generate` `{league_year, league_level, start_week, seed, clear_existing}` | `confirm()`; same result text; report reloads |
| Clear Schedule (`btn-sched-clear`, `window.confirm`) | `POST /admin/schedule/clear` `{league_year, league_level}` | `confirm({danger, typeToConfirm:'CLEAR'})` |
| Add Series (`btn-sched-add-series`) | `POST /admin/schedule/add-series` `{league_year, league_level, home_team_id, away_team_id, week, games}` | shared `addSeriesCard` helper, same body |

### Viewer — legacy `section-schedule-viewer`

| Legacy button / action | Endpoint | Now |
|---|---|---|
| Load Schedule (`btn-sv-load`), Prev/Next (`btn-sv-prev/next`, page size 200) | `GET /admin/schedule/viewer?season_year=&league_level=&team_id=&week_start=&week_end=&page=&page_size=200` | same server-side paging; games in a `dataTable` (client sort within the page); `?team=` / `?level=` / `?autoload=1` deep links *(added)* |
| Weeks summary card | same payload `weeks_summary` | same |
| Quality card shown only when a level is selected; Load Quality Metrics (`btn-sv-quality`) | `GET /admin/schedule/quality?season_year=&league_level=` | `kpi` tiles + sortable `dataTable`; home % outside 40–60 in `text-danger` |
| Edit game (`App.editGame`, four `prompt()`s) | `PUT /admin/schedule/game/<id>` `{home_team, away_team, season_week, season_subweek}` | `openModal` form with the same four fields |
| Quick Add Series (`btn-sv-add-series`) | `POST /admin/schedule/add-series` | shared `addSeriesCard`; reloads the games table if loaded |
| Swap Opponents (`btn-sv-swap-ooc`) | `POST /admin/schedule/swap-ooc` `{team_a_id, team_b_id, season_week, season_subweek}` | same, incl. `swapped:false` message path |

## Notes / gaps

- **Stamina rest** is the only control not reproduced in place; it is a link to the Simulate tab, which already has the full form (dry run included).
- The legacy awards search dropdown floated over the form via inline absolute positioning; the port renders results inline because `css/` is off-limits for this work. Functionally identical.
- Fixed pixel widths remain inline only on a handful of narrow table-cell inputs/`<th>` (seed/week/event-id inputs), matching what `ui/table.js` itself does for column widths.
- No backend changes were needed. `GET /api/v1/special-events` (already in `playoffs/__init__.py`, unused by legacy) is now used to list existing All-Star/WBC events.
