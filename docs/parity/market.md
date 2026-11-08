# Admin revamp parity — Market area

Legacy sections ported to `admin/static/admin/js/features/market/*.js`. Every legacy button / endpoint call is listed with where it lives now, or `dropped: reason`.

Shared helpers live in `features/market/_shared.js`:

| Legacy | New |
|---|---|
| `txOrgList` cache from `GET /api/v1/org_report/` (`populateTxOrgDropdown`) | `loadOrgs()` / `orgSelect()` — same endpoint. `/api/v1/organizations` was not used because it returns abbrev strings only (no ids). |
| `fetchTxContext()` → `txLeagueYearId = timestamp.SeasonID`, `txGameWeekId = timestamp.WeekID \|\| Week` | `txContext()` reads `store.get().ts` (same `/games/timestamp` payload; fetched via `refreshTimestamp()` if missing) → `{ league_year_id, game_week_id, week }` |
| per-tab "Year N salary" inputs | `salaryFields()` / `readSalaries()` |
| `.status-msg` text | `setStatus()` (alert box) + `toast` |

---

## section-tx-roster → `roster.js` (tab `market/roster`)

| Legacy control | Endpoint | New |
|---|---|---|
| Org select + "Load Roster" | `GET /transactions/roster-status/<org>`, `GET /transactions/roster/<org>`, `GET /transactions/signing-budget/<org>?league_year_id` | Org `orgSelect` (auto-loads on change) + "Load roster"; status chips, budget line, `dataTable` with level filter (client-side, as legacy) |
| Roster "Select" → Player Action card (promote / demote / ir_place / ir_activate / release / buyout / extend) | `POST /transactions/promote`, `/demote`, `/ir/place`, `/ir/activate`, `/release`, `/buyout`, `/extend` (same bodies: `league_year_id`, `executed_by:'admin'`, `contract_id`, `target_level_id`, `org_id`, `buyout_amount`+`game_week_id`, `years`+`salaries`+`bonus`+`game_week_id`) | "Action" button → `openModal` with the same action select and dynamic fields; release/buyout use `confirm({danger})` |
| Extension / buyout demand hint | `POST /fa-auction/compute-demands {player_id, league_year_id, demand_type, contract_id}` | Same, inside the modal |
| "Load Free Agents" | `GET /transactions/free-agents` | Same (table) |
| FA "Sign" → sign form | `POST /transactions/sign {player_id, org_id, years, salaries, bonus, level_id, league_year_id, game_week_id, executed_by}` | "Sign" → `openModal` form; reloads roster + FA list |

## section-tx-trades → `trades.js` (tab `market/trades`)

| Legacy control | Endpoint | New |
|---|---|---|
| (none in legacy — spec'd in `docs/trade_admin_frontend_guide.md`) Pending Approval queue | `GET /transactions/trade/proposals?status=counterparty_accepted` | **First card** "Pending approval" with count badge, Details / Approve / Reject per row |
| Proposals table + status filter + Refresh | `GET /transactions/trade/proposals[?status=]` | "All proposals" card; status filter (incl. `admin_rejected`, `expired`) + org filter (`org_id`) + Refresh |
| Approve | `PUT /transactions/trade/proposals/<id>/admin-approve {league_year_id, game_week_id, executed_by:'admin'}` (+ optional `note`) | `approve()` — confirm, then same body; admin note passed when entered in the detail modal |
| Reject | `PUT /transactions/trade/proposals/<id>/admin-reject {}` (+ optional `note`) | `reject()` — `promptText` for the optional note |
| Reject button on `proposed` rows | same | **dropped**: backend only accepts `counterparty_accepted` (legacy button always errored); Details still available |
| (new, from guide) Detail modal | `GET /transactions/trade/proposals/<id>`, `GET /transactions/roster/<a|b>`, `GET /transactions/roster-status/<a|b>` | `openDetail()` — player names/levels/salaries/retention, roster impact per level vs min/max, timeline, notes, approve/reject with admin note |
| Trade Builder: Org A / Org B rosters (checkboxes), cash, "Execute Trade (Admin)" | `GET /transactions/roster/<org>`, `POST /transactions/trade/execute {org_a_id, org_b_id, players_to_b, players_to_a, cash_a_to_b, league_year_id, game_week_id, executed_by}` | Same, plus per-player "Retain %" → `salary_retention {pid:{retention_pct}}` (guide field legacy never exposed) |

## section-tx-log → `txlog.js` (tab `market/txlog`)

| Legacy control | Endpoint | New |
|---|---|---|
| Filters type / org id / player id / limit + Refresh | `GET /transactions/log?limit&type&org_id&player_id` | Same (org is an `orgSelect` instead of a raw id box) |
| Detail (inline panel, cache-first, fallback `?limit=1&tx_id=`) | `GET /transactions/log?limit=1&tx_id=<id>` | `openDetail()` modal with the same type-specific kv rows + raw JSON `<details>` |
| Rollback | `POST /transactions/rollback {transaction_id, executed_by:'admin'}` | Same, `confirm({danger})`; also offered inside the detail modal |
| × delete log entry | `DELETE /transactions/log/<id>` | Same |
| Bulk Clear (multi-select, protected types disabled) | `POST /transactions/log/bulk-delete {league_year_id, types}` | Same; `confirm({danger, typeToConfirm:'CLEAR'})`; protected types listed, not selectable |

## section-roster-compliance → `compliance.js` (tab `market/compliance`)

| Legacy control | Endpoint | New |
|---|---|---|
| Org select ("All Organizations" = MLB orgs) + Load | `GET /transactions/roster-status/<org>` × N | Same fan-out via `Promise.all` |
| Summary cards (orgs / compliant / violations) | — | `kpi()` cards |
| Detail table + "Show violations only" | — | `dataTable` with `row-danger`/`row-warning`, violations-first sort, toggle |

## section-tx-eos → `eos.js` (tab `market/eos`)

| Legacy control | Endpoint | New |
|---|---|---|
| Season info alert | `/games/timestamp` | From `txContext()` + phase badge (live via `store.watch('ts')`) |
| "Process End of Season" | `POST /games/end-season {league_year_id}` | `confirm({danger, typeToConfirm:'END SEASON'})` → `runTracked`; same kv summary (`end_of_season` or top level); refreshes timestamp/summary |
| Service Time Overview (org select + Load) | `GET /transactions/contract-overview/<org>` | Same table (phase badges, expiring rows highlighted) |

## section-tx-amateur → `amateur.js` (tab `market/amateur`)

| Legacy control | Endpoint | New |
|---|---|---|
| "Scan Players" | `GET /admin/amateur-contracts-preview` | Same (KPI cards + breakdown table) |
| "Seed Amateur Contracts" | `POST /admin/seed-amateur-contracts` | `confirm({danger, typeToConfirm:'SEED'})` → `runTracked`, `api.post(..., {}, {admin:true})`; kv summary; rescan |
| "Populate Orgs" (org ids, pitchers/org, batters/org) | `POST /admin/populate-college-orgs {org_ids, pitchers_per_org, batters_per_org}` | Same, `{admin:true}`, result text |

## section-fa-auction → `fa-auction.js` (tab `market/fa`)

| Legacy control | Endpoint | New |
|---|---|---|
| Org select + "Load Board" | `GET /fa-auction/board?league_year_id&org_id` | Same (auto-loads on mount / org change) |
| Offer / Update → inline "modal" (years, bonus, level, salaries, totals, below-min warning, budget) | `GET /transactions/signing-budget/<org>?league_year_id`, `POST /fa-auction/<id>/offer {org_id, years, salaries, bonus, level_id, league_year_id, game_week_id, current_week, executed_by}` | `openModal` with the same fields, live totals/AAV warning, pre-filled from `my_offer` |
| "Advance Phases" | `POST /fa-auction/advance-phases {league_year_id, current_week}` | Same, `confirm({danger})`, result via `showResult` |
| (not in legacy UI; endpoint existed) Admin enter player | `POST /fa-auction/admin/enter-player {player_id, league_year_id, current_week}` | "Enter player…" (`promptText` + confirm) |
| Orphan sweep | `POST /fa-auction/admin/orphan-sweep` | Not in this section in legacy (lives in `#section-orphan-sweep`); linked to `#/system/orphans` |

## section-fa-market → `fa-market.js` (tab `market/fa-market`)

| Legacy control | Endpoint | New |
|---|---|---|
| "Load Market Data" | `GET /fa-auction/market-summary?league_year_id` | Auto-load + Refresh; KPIs ($/WAR, signings, avg years, avg AAV), WAR-tier bar chart via `mountChart`, recent signings `dataTable` |

## section-recruiting + section-recruiting-admin → `recruiting.js` (tab `market/recruiting`)

| Legacy control | Endpoint | New |
|---|---|---|
| League year select (both sections) | — | one `leagueYearSelect` (global) |
| "Compute Rankings" | `POST /recruiting/advance-week {league_year_id}` | **merged** into "Advance week" (legacy called the same endpoint; week 0→1 is what computes rankings) |
| "Advance Week" | `POST /recruiting/advance-week {league_year_id}` | "Advance week" (confirm → `runTracked`; message handles `ranked_players` / `new_week` / commitments / leftovers) |
| "Regenerate Stars" | `POST /recruiting/rankings/regenerate {league_year_id}` | Same |
| "Wipe Stars" | `POST /recruiting/rankings/wipe {league_year_id}` | `confirm({danger, typeToConfirm:'WIPE'})` |
| State card | `GET /recruiting/state?league_year_id` | Same (+ pool/committed/remaining from summary) |
| Star distribution chart | 5 × `GET /recruiting/rankings?star_rating=N&per_page=1` | Sourced from `report/summary.star_distribution` + `committed_by_star` (pool vs committed bars + table); the 5 extra ranking calls were dropped as redundant |
| Recent commitments | `GET /recruiting/commitments?league_year_id&per_page=20` | Same |
| Admin "Refresh" → summary report (KPIs, star table, weekly trend chart, commitment pace chart) | `GET /recruiting/admin/report/summary?league_year_id` | Same (`kpi` grid, charts via `mountChart`) |
| Org leaderboard (row click → org detail) | `GET /recruiting/admin/report/org-leaderboard?league_year_id` | `dataTable` with `onRowClick` |
| Player demand (star filter, limit) | `GET /recruiting/admin/report/player-demand?league_year_id&limit&star_rating` | Same |
| Org detail (weekly spend chart, commitments won, invested players) | `GET /recruiting/admin/report/org-detail/<org>?league_year_id` | Same, with Close button |
| "Reset to Week" | `POST /recruiting/admin/reset-week {league_year_id, target_week}` | Same (confirm) |
| "Full Reset (preserve rankings)" | `POST /recruiting/admin/full-reset {league_year_id}` | `confirm({danger, typeToConfirm:'RESET'})` |
| Wipe Investments / Commitments / Boards (optional org_id / player_id) | `POST /recruiting/admin/wipe-investments`, `/wipe-commitments`, `/wipe-boards` `{league_year_id, org_id?, player_id?}` | `confirm({danger, typeToConfirm:'WIPE'})`, scope shown |

## section-draft-admin → `draft.js` (tab `market/draft`)

| Legacy control | Endpoint | New |
|---|---|---|
| League year select + Refresh | `GET /draft/state?league_year_id` | Same; 400/404 = no draft → init card. Auto-refreshes every 10 s while `IN_PROGRESS` |
| Initialize (total rounds, seconds/pick, live rounds, snake) | `POST /draft/admin/initialize {league_year_id, total_rounds, seconds_per_pick, is_snake, live_rounds}` | Same (`runTracked`) |
| Start / Pause / Resume / Reset Timer | `POST /draft/admin/start`, `/pause`, `/resume`, `/reset-timer {league_year_id}` | Phase-dependent buttons |
| Run Auto Rounds | `POST /draft/admin/run-auto-rounds {league_year_id}` | Same (`runTracked`, shows `picks_made`) |
| Advance to Signing / Export / Complete | `POST /draft/admin/advance-signing`, `/export`, `/complete {league_year_id}` | Same with confirms (`export` also sends `executed_by:'admin'`, accepted by the handler) |
| Round strip + Round Mode editor (toggle LIVE/AUTO) | `GET /draft/round-modes?league_year_id`, `POST /draft/admin/round-modes {league_year_id, round_modes:{round:mode}}` | Same (strip as badges; editor buttons in SETUP) |
| Draft board + round filter | `GET /draft/board?league_year_id` | `dataTable`, current pick highlighted (`row-warning`) |
| Assign Pick | `POST /draft/admin/set-pick {league_year_id, round, pick_in_round, player_id}` | Same (confirm danger) |
| Rollback Pick | `POST /draft/admin/remove-pick {draft_pick_id}` | Same (confirm danger) |
| Signing table + status filter, Sign / Pass | `POST /draft/sign/<pick_id> {league_year_id}`, `POST /draft/pass/<pick_id>` | Same; Sign asks for an optional `bonus` (blank = slot value, per `docs/draft_frontend_guide.md` §9) and reports accepted / rejected / refused; shows `offers_made`, `bonus_agreed`, `class_year` |

## section-ifa-admin → `ifa.js` (tab `market/ifa`)

| Legacy control | Endpoint | New |
|---|---|---|
| League year select + Refresh | `GET /ifa/state?league_year_id` | Same |
| "Advance Week" (label changes at week 0 / complete) | `POST /ifa/advance-week {league_year_id}` | Same (confirm → `runTracked`, phase-transition summary) |
| "Reset Window" (double confirm) | `POST /ifa/reset {league_year_id}` | `confirm({danger, typeToConfirm:'RESET'})` |
| Bonus pools | `GET /ifa/pools?league_year_id` | `dataTable` (+ Used %, 70/90 % row tints) |
| Active auctions | `GET /ifa/board?league_year_id` | `dataTable` |
| Eligible players + star filter | `GET /ifa/eligible?league_year_id` | `dataTable`, client-side filter, "x of y shown" |
| Completed & expired auctions | `GET /ifa/history?league_year_id` | `dataTable` |

---

## Backend gaps / notes

- `GET /api/v1/organizations` returns only `org_abbrev` strings; an id-bearing lightweight org list endpoint would let `_shared.loadOrgs()` stop pulling the full `/org_report/` payload (teams dicts per org).
- `GET /transactions/trade/proposals` returns bare org ids; the UI maps them through the org cache. Proposal objects carry no player names, so the detail modal cross-references `/transactions/roster/<org>` (players no longer on the roster show as "not on roster").
- Admin trade **reject on `proposed`** status is not supported by the backend (only `counterparty_accepted`), so that legacy button was dropped.
- `POST /games/end-season` supports `force:true`; not exposed (legacy did not expose it either).
- Draft `/draft/state` signals "no draft" with a 400 validation error rather than a dedicated status; the tab treats 400/404 as "not initialized".
