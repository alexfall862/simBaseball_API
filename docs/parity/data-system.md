# Admin revamp parity — Data & System areas

Legacy source: `admin/static/admin/app.js` + `admin/templates/admin/legacy.html` (still served at `/admin/legacy`).
New shell: `admin/static/admin/js/features/data/*.js` and `js/features/system/*.js` (hash routes `#/data/<tab>`, `#/system/<tab>`).

Conventions in the new tabs: every request goes through `core/api.js` (errors toast automatically), destructive
actions go through `confirm({ danger: true, typeToConfirm })`, long operations through `runTracked`, tables through
`ui/table.js dataTable`, write-mode gating reads `store.get().auth.writeMode` (refreshed from `GET /admin/me` on mount).

## Data › Organizations (`#/data/orgs`, `features/data/orgs.js`)

| Legacy control / call | Now |
|---|---|
| `#org-select` populated from `GET /api/v1/organizations` | Same endpoint; handles both `[abbrev,…]` and `[{…}]` shapes. Selection is deep-linked as `?org=` |
| `#btn-refresh-orgs` | "Refresh list" button |
| `GET /api/v1/<org>/` → kv-table of the row | Same endpoint → `kvTable`; nested values JSON-encoded; "Raw JSON" modal |
| — (new) | Financial summary card: `GET /api/v1/orgs/<abbrev>/financial_summary?league_year=YYYY` (year defaults to timestamp Season) |

## Data › Teams (`#/data/teams`, `features/data/teams.js`)

| Legacy control / call | Now |
|---|---|
| `#team-select` from `GET /api/v1/teams` | Same; deep-linked `?team=` |
| `#btn-refresh-teams` | "Refresh list" |
| `GET /api/v1/teams/<abbrev>/` → kv-table | Same → `kvTable` + Raw JSON |
| `#btn-team-players` → `GET /api/v1/teams/<abbrev>/players` → `<pre>` JSON | Same endpoint → `dataTable` (columns from row keys, paged 50) when the payload is a list of objects; `<pre>` JSON fallback; Raw JSON modal |

## Data › Players (`#/data/players`, `features/data/players.js`)

| Legacy control / call | Now |
|---|---|
| `#player-id` + `#btn-lookup-player` → `GET /api/v1/players/<id>` → `<pre>` JSON | **Backend endpoint no longer exists** (removed in the canonical displayovr refactor, see `players/__init__.py`). Replaced by: "Season stats" `GET /api/v1/stats/player/<id>?league_year_id=`, "Career" `GET /api/v1/stats/player/<id>/career`, "Scouting view" `GET /api/v1/scouting/player/<id>?org_id=&league_year_id=`. Result shown as JSON (`result-box`) + modal. An info alert points to the SQL console for the raw `simbbPlayers` row. Deep-linked `?id=` |
| — (requested) | Roster name search: `GET /admin/players/search?q=&league_level=&league_year_id=&limit=` → `dataTable` with Stats / Scouting row actions. Level select remembers its value; league-year select is the global one |

## Data › Game Viewer (`#/data/game`, `features/data/game-viewer.js`)

| Legacy control / call | Now |
|---|---|
| `#gv-game-id`, `#gv-pitches` (narrative / pitch detail), `#btn-gv-load`, Enter key | Same inputs (`game_id`, `detail`), Load button, Enter key; deep-linked `?game=&events=` and auto-loads from the URL |
| `GET /api/v1/games/<id>/play-by-play?format=v2&granularity=at_bat&include_events=0/1` | Identical request |
| Half-inning grouping, score line, RBI chip, pitch/steal/pickoff event rows | Same grouping/logic. Legacy `.gv-*` CSS lives only in `styles.css` (legacy), so the feed is rendered with shell classes (`card tight`, `row between`, `badge`, `mono`) instead |
| "No play-by-play stored (MLB-only; may be archived)" message | Kept |
| — (new) | Raw JSON modal |

## Data › SQL Console (`#/data/sql`, `features/data/sql.js`)

| Legacy control / call | Now |
|---|---|
| `SQL_PRESETS` client list (9 queries) + `#btn-run-preset` | Same 9 presets in an "Console presets" optgroup; "Run preset" and "Insert into editor" buttons |
| `GET /admin/presets` + `GET /admin/run_preset?key=` (server presets; defined in `admin/__init__.py` but **never wired in the legacy UI**) | Loaded into a second optgroup "Server presets"; run via `GET /admin/run_preset?key=` |
| `#sql-mode` (read / write), `#sql-limit`, `#sql-dry` | `mode`, `limit`, `dry_run` fields (same defaults: read, 100, dry run on) |
| `#sql-query` textarea, `#btn-run-sql` | `textarea.mono` + Run button + Ctrl/Cmd+Enter |
| `POST /admin/run_sql {sql, mode, limit, dry_run}` | Identical body |
| Result `<pre>` with `N rows returned:` + JSON | `dataTable` built from the union of row keys (paged 50, display capped at 500 with a note); `explain` dry-run plans as a table; `rowcount` as a success alert; anything else as JSON. "Raw JSON" modal keeps the old full-payload view |
| Write-mode gating (server-side 403 `write_disabled`) | Visible banner (warning when off, danger when on) bound to `store.auth.writeMode`; write mode with dry run off requires `confirm({danger, typeToConfirm:'WRITE'})`; write requests are refused client-side when the flag is off |
| "Unauthorized - please login first" handling | Done by `api.js` (401 → `api:unauthorized`) |

## Data › DB Storage (`#/data/storage`, `features/data/storage.js`)

| Legacy control / call | Now |
|---|---|
| `#btn-db-storage-load` → `GET /admin/db-storage` | Auto-loads on mount; "Refresh" button |
| Summary stat cards (tables, rows, data, index, total) | `kpi()` cards in `grid-auto` |
| Tables table with share bar (inline-styled divs) | Sortable `dataTable` (default total_mb desc), share bar reuses `.progress-container/.progress-fill`; table-name filter box added |

## System › Health (`#/system/health`, `features/system/health.js`)

| Legacy control / call | Now |
|---|---|
| `GET /healthz` → indicator + `#db-info` JSON | Liveness card: badge + JSON (+ formatted server time) |
| `#btn-check-health` | "Refresh all" (re-runs all three probes) |
| `GET /routes` (text) → `<pre>` | Parsed into a sortable `dataTable` (methods / rule / endpoint) with text filter + method filter |
| — (new) | Readiness card: `GET /readyz` (503 degraded body is shown rather than toasted) |

## System › Cache (`#/system/cache`, `features/system/cache.js`)

| Legacy control / call | Now |
|---|---|
| Explanatory text + warning alert | Kept |
| Status / Last cleared stat cards | `kpi()` cards; "Last cleared" is per tab mount (legacy was per page load) |
| `#btn-clear-cache` → `POST /admin/clear-caches` | Same, behind a non-destructive `confirm()`; result in `result-box`; `cleared` map flattened (`module.key`) into a kv table with cleared/was-empty badges. Legacy `Object.values(cleared).some(v===true)` ignored the nested shape; new code flattens it |
| "What gets cached" static table | Kept (`simpleTable`) |
| `clearCachesFromSim()` / `#sim-cache-status` badge on the Simulate section | Not part of this area — Season › Simulate owns that button |

## System › Migrations (`#/system/migrations`, `features/system/migrations.js`)

| Legacy control / call | Now |
|---|---|
| `#btn-migrate-amateur` → `POST /admin/migrations/fix-amateur-contracts` | Card (danger zone) → `confirm({danger, typeToConfirm:'MIGRATE'})` → `runTracked` |
| `POST /admin/migrations/add-recruiting-columns`, `add-ncaa-tournament`, `add-waiver-tables` (**no legacy UI**) | Cards with the same confirm flow |
| Green/red result colouring | `runTracked` progress widget (done / failed states) |

## System › Orphan Sweep (`#/system/orphans`, `features/system/orphans.js`)

| Legacy control / call | Now |
|---|---|
| Found / Entered / Errors stat cards | `kpi()` cards |
| `#btn-orphan-scan` → `GET /admin/fa-orphan-scan` | Same; table via `dataTable` (level names from `core/constants.js`) |
| `#btn-orphan-fix` → `confirm()` → `POST /api/v1/fa-auction/admin/orphan-sweep {league_year_id}` | Same body; `confirm({danger:true})`; `runTracked`; row badges updated to Entered / Error (per-player `error_details` shown as badge title) |
| Fix results `<pre>` | Kept + modal |
| `POST /admin/debug/cancel-orphan-auction/<player_id>` (**no legacy UI**) | Danger-zone card, `confirm({danger, typeToConfirm:'CANCEL'})` |

## System › Finance (`#/system/finance`, `features/system/finance.js`) — NEW, no legacy panel

| Endpoint | Now |
|---|---|
| `POST /admin/run-year-start-books {league_year}` | Card → confirm → `api.post(..., {admin:true})` via `runTracked` |
| `POST /admin/run-week-books {league_year, week_index}` | Card with `week_index` input |
| `POST /admin/run-season-books {league_year}` | Card |
| `POST /admin/run-year-end-interest {league_year}` | Card, `confirm({danger, typeToConfirm:'INTEREST'})` |
| `POST /admin/run-playoff-revenue {league_year}` | Card, `confirm({danger, typeToConfirm:'PLAYOFF'})` |
| `POST /admin/initialize-next-league-year {league_year}` | Card, `confirm({danger, typeToConfirm:'NEXT YEAR'})` |
| `GET /api/v1/financial_summary?league_year=` / `GET /api/v1/orgs/<abbrev>/financial_summary?league_year=` | Read-only summary card (league table with totals, or one org as kv) |
| `POST /admin/seed-contracts`, `POST /admin/simulate-fake-season` | **Not surfaced** — env-gated (`ALLOW_CONTRACT_SEEDING`) bootstrap/dev tools, outside the books scope requested |

All books endpoints take the season **number** (e.g. 2026), shared via one "League year" input defaulting to the timestamp's Season. A banner warns when no `X-Admin-Password` is stored.

## System › Tutorial CMS (`#/system/tutorial`, `features/system/tutorial.js` + `_tutorial_md.js`)

| Legacy control / call | Now |
|---|---|
| Toolbar: Refresh, + New Category, Edit Glossary, status text | Same |
| `GET /admin/tutorial/manifest` → category cards with article tables | Same; cards use `card-head` / `data-table compact`; tags and league filters as badges |
| Per category: Edit (4 sequential `prompt()`s), + Article, Delete (`confirm`) | Edit opens a modal form (title, icon select, description, league filter, order) → `PUT /admin/tutorial/category/<id>`; Delete uses `confirm({danger, typeToConfirm:'DELETE'})` → `DELETE /admin/tutorial/category/<id>` |
| `POST /admin/tutorial/category` (new category form view) | Modal form with the same icon list and league options |
| Per article: Edit, Dup (`prompt()` for new slug) | Edit opens the editor; Dup uses `promptText()` then `GET` + `POST /admin/tutorial/article/<cat>` with the same body |
| Editor: metadata fields (id read-only, title, summary, tags, league filter, related), INSERT toolbar (14 templates), validation bar, split markdown/preview, Save (top + bottom), Delete, Back | All kept (`formGrid`, `textarea.mono`, `grid-2`). Tab inserts two spaces; Ctrl/Cmd+S saves. Deep-link `?cat=&art=` opens an article |
| `PUT /admin/tutorial/article/<cat>/<art>` body `{title, summary, tags, leagueFilter, relatedArticles, lastUpdated, markdown}` | Identical; client-side `validateMarkdown` must pass first (same rules as legacy `_tutValidate`) |
| `DELETE /admin/tutorial/article/<cat>/<art>` | `confirm({danger, typeToConfirm:'DELETE'})` |
| New article view → `POST /admin/tutorial/article/<cat>` | Same fields and body |
| Glossary editor rows + Add Term + Save → `PUT /admin/tutorial/glossary {glossary}` | Same (rows are `form-row`s; empty terms dropped) |
| `PUT /admin/tutorial/reorder` (**endpoint existed, legacy had no UI**; order was only editable via the category prompt) | ▲/▼ buttons on categories and articles renumber 1..n and call `PUT /admin/tutorial/reorder` |
| Live preview (`_tutMdToHtml`, custom renderer with inline styles) | Ported to `_tutorial_md.js renderMarkdown()` using shell classes (`alert-*` callouts, `data-table` compare, `details.card` detail, `progress-fill` rating bar, `kv-table` player card, `abbr` glossary). Legacy used no external markdown library (no marked/showdown CDN in `legacy.html`) |
| Write-mode requirement (server 403 `write_mode_disabled`) | Banner from `writeModeBanner()`; write actions refuse client-side when the flag is off |
| `window.App.tut*` globals for inline `onclick` | Dropped: replaced by `data-action` delegation |

## Dropped / intentionally not reproduced

| Item | Reason |
|---|---|
| `GET /api/v1/players/<id>` raw player lookup | Endpoint removed server-side; replaced as described above |
| Inline `onclick="App.…"` handlers, `alert()/confirm()/prompt()` | Shell rules: `data-action` delegation, `toast`, `confirm()`, `promptText()`, modal forms |
| Legacy `.gv-*`, `.status-indicator`, `.tut-glossary-row` styles | Only exist in `styles.css` (legacy); new tabs use `css/components.css` classes |
| Cache "Last cleared" persisting across sections of the same page load | New shell remounts tabs; the value is per mount (the server response is the source of truth anyway) |
