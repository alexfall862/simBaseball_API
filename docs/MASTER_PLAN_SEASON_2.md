# Season 2 Master Plan — API modernization, free agency tuning, draft completion, interface sync

**Status:** Workstream A (rollover blockers) and the pure-bug items of B1 were implemented on 2026-11-07 and verified with a rolled-back dry run against the live database (see §3a). Everything else is still planned. Decisions marked **[DECISION]** need an answer before the relevant workstream starts.

**Evidence base:** four read-only audits run on 2026-11-07 against this repo at `c2a10ee` and the interface repo `CalebRose/simsn-interface-v2` at `8abdc59` (merged 2026-11-07). Line references are to those commits. Live-database checks (section 0a) were run read-only on 2026-11-07 over Tailscale.

## 0a. Live database findings (2026-11-07, read-only)

| Check | Result | Consequence |
|---|---|---|
| Rollover state | End-season **not run**. All brackets complete (MLB WS, NCAA final). Timestamp at 2026 week 57, regular-season phase. `league_years` id 1 only; `bonuses_run_at`, `playoff_revenue_run_at`, `interest_run_at` all NULL. `season_ended_at` column does not exist yet (lazy ALTER). Postseason awards present (28 `world_series`, 57 `pennant`). | A1 is a code fix only; **no data repair needed**. Runbook step 2 done; steps 3–6 pending. |
| A1 blast radius | Active pro contracts: 4,300 one-year, **168 two-year and 180 three-year, all in year 1**. | Without A1, all 168 two-year deals end after one season and the 180 three-year deals lose a season. |
| Free agent class | Expiring MLB contracts: **155 FA-eligible (6+ service yrs, ages 27–34, avg 29.1)**, 382 pre-arb, **0 arbitration**. Minors: 47 FA-eligible, 3,716 pre-arb. | Arbitration logic won't run this offseason. The auction must handle ~200 players at once. |
| FA calibration data | **No auction has ever run** (`fa_auction`, `fa_auction_offers` empty). `fa_market_history` holds 49 direct signings averaging $28K AAV, 1 year, 0.0 WAR (minor-league fills). 81 `player_demands` rows, all release-tier, 0.0 WAR. | **There is no season-1 market data to tune from.** The market rate will sit at the $8M bootstrap. B2 tuning is done by dry-running demand generation on the 155-player class and judging the output, not by regression on history. |
| Human vs CPU orgs | **29 of 30 MLB orgs have a human** owner/GM/manager/scout. `organizations.coach` is `'AI'` for all 30 MLB orgs, so it is not a valid CPU signal at MLB level. College: 33 human of 310. | CPU bidding (B5) is low value for MLB. The real need is handling *inactive* humans (draft auto-pick, FA deadlines). A CPU check must use the owner/GM name columns, not `coach`. |
| Draft | `draft_state` and `draft_eligible_players` empty. `recruiting_rankings` has 8,864 rows for year 1 (the USHS class). | The runbook archives (step 6, deletes rankings) before the draft (step 8), which is why ranks fall to 99999. Decouple ranking from recruiting (C1). |
| Id spaces | `game_results.season` = 1 only; `seasons` id 2 = 2027. | `league_years` id 2 will also be 2027, so A9 won't misfire in season 2 by coincidence. Still worth fixing, lower priority. |
| Size | 4.2 GB, of which `game_results` is 3.2 GB. | A full snapshot is practical. Coolify's scheduled database backup is the easiest way to take one server-side. |

---

## 0. Where we stand

| Area | State |
|---|---|
| Season 1 gameplay | Complete through the MLB World Series (postseason ran to week 57). |
| Offseason rollover | End-season has **not** run (confirmed, see 0a). Nothing destructive has happened yet. |
| Hosting | API and DB moved from Railway to Coolify. Local dev reaches the DB over Tailscale. Frontend points at `https://simbaseball.afwh.app/api/v1/` and `wss://simbaseball.afwh.app/ws` (interface PR #307, 2026-10-13). |
| Interface | Baseball has a complete draft room (`components/Draft/BaseballDraft/*`), FA page (`Team/baseball/BaseballFreeAgencyPage.tsx`), IFA, waivers, scouting, recruiting, trades, admin sim panel. All built against this API's snake_case contract. Draft and FA models last touched 2026-04-08 / 2026-06-22. |
| Auth | Interface sends a Firebase ID token as `Authorization: Bearer` on every call. **The API never reads it.** Every non-admin route trusts `org_id` / `viewing_org_id` from the client. |
| Tests | One unit-test file (`tests/test_pbp_normalize.py`). Zero coverage of sim, contracts, FA, draft, playoffs, rollover. |
| Migrations | No runner, no `schema_migrations`. Numbered migrations deleted in `1f79300`; schema snapshot in `BaseballDB_structure/` is from 2026-03-29 and missing ~10 later tables/columns. |

### The findings that change the plan

1. **Contracts expire one season early.** `services/contract_ops.py:374-398` advances `current_year` and then expires `current_year == years` in the same pass. A 2-year deal signed in 2026 is advanced to year 2 and expired in one call. Verified in source.
2. **Offseason signings are stamped with the ending year.** `services/transactions.py:925-941` sets `leagueYearSigned` from the caller's `league_year_id`; books map year-1 salary onto the season that just finished, so it is never paid. Verified in source.
3. **FA auctions cannot progress in the offseason.** Phase advance requires `current_week > phase_started_week` (`services/fa_auction.py:471`), and the week does not move between end-season and start-new-season. `advance-fa-round` only increments a counter nothing reads. Verified in source.
4. **Market rate mixes units.** `$/WAR = Σ total_value / Σ WAR` (`market_pricing.py:83-101`) but demands use it as AAV per WAR. A 5-year deal records an implied rate 5× too high; arb renewals recorded mid-loop drag it down. Expect season-1 data to sit at a clamp.
5. **Draft is not finishable as-is.** Prospects rank 99999 (no ranking computed at draft time), signing leaves the amateur contract active (player on two orgs), no eligibility rules, no CPU picking, pick clock depends on polling, WS broadcasts only reach one gunicorn worker.
6. **Interface calls draft endpoints that don't exist**: `draft/trade/propose`, `draft/trade/proposals`, `draft/trade/accept`, `draft/trade/reject`. Backend has only `POST /draft/trade`. `GET /draft/picks/{org}` returns `{picks:[…]}` but the interface types it as a bare array.
7. **No end-user authentication.** Destructive routes (`wipe-season`, `end-season`, `start-new-season`, `transactions/rollback`, `recruiting/admin/full-reset`, `ifa/reset`, `playoffs/wipe`, `player-ops/generate`) are open to anyone who knows the URL. `/schema`, `/routes`, `/debug/db` are public.
8. **displayovr has not been recomputed after any subweek since 2026-04-10** (`game_payload.py:4224` calls un-imported `text(`; NameError swallowed). Known, still unfixed.
9. **Old Railway root DB password is in git history** (`c3ba500`, `12a54d6`) and in a comment on `.env` line 3. Dead if Railway is decommissioned; remove the comment regardless.

---

## 1. Workstreams

| # | Workstream | Goal | Must finish before | Size |
|---|---|---|---|---|
| **P0** | Preconditions | DB access, snapshot, state check, calibration data pull | anything else | hours |
| **A** | Rollover blockers | End-season, FA, draft and start-new-season produce correct season-2 data | runbook step 5 (end-season) | ~1 week |
| **B** | Free agency: correctness → tuning → consolidation | FA that actually completes in the offseason, prices sanely, records calibration data, has one auction engine | runbook step 7 | ~2 weeks |
| **C** | Draft: finish + interface sync | A draft that can be run live from the interface, with CPU teams, real rankings, correct contracts | runbook step 8 | ~2 weeks |
| **D** | New-year bootstrap | Retirements, new amateur class, year-2 tables, so season 2 has a talent pipeline | runbook step 13 | ~1.5 weeks |
| **E1** | Modernization foundations | Migration runner, test harness, config table, shared constants, dead-code removal | start of A (used by A–D) | ~1 week, parallel |
| **E2** | Modernization tier 2 | Auth, response-envelope/pagination normalization, WS fan-out, docs regen, split giant files | during season 2 (breaking changes coordinated with interface) | ongoing |
| **F** | Interface sync deliverables | Per-feature API contract doc + change list / PRs for `simsn-interface-v2` | with C (draft) and B (FA) | with each |

Recommended order: **P0 → E1 + A (parallel) → B → C → D → start season 2 → E2.**

---

## 2. P0 — Preconditions (do first, no code changes)

1. **Local DB access.** Enable "Make it publicly available" on the Coolify MySQL resource; add a `# Coolify public:` line to `.env` alongside the internal URL. Delete the Railway URL comment (contains a root password).
2. **Snapshot season 1.** `mysqldump` the whole DB before any further offseason step. `wipe-season` and `archive_season` delete `fa_market_history`, `player_demands`, `draft_eligible_players`, `recruiting_rankings` for the year; those are the calibration data.
3. **Determine rollover state.** Query `league_years` (`season_ended_at`, `*_run_at`), `timestamp_state`, `playoff_series` WS status, `fa_auction` phases, `draft_state`. This decides whether A1 is a code fix or a code fix **plus** a data repair.
4. **Calibration pull** (feeds B): `fa_market_history` by source; `fa_auction` × `fa_auction_offers` outcomes; `player_demands` vs signed AAV; contracts that expired at end of season 1 with `leagueYearSigned + years - 1 > 2026` (A1 blast radius); season-1 WAR distribution from both WAR models (`player_demands.get_player_war` vs `analytics.compute_*_war`).
5. **Refresh the schema snapshot** (`BaseballDB_structure/`) from the live DB so E1's migration baseline is real.

---

## 3. A — Rollover blockers

All are small, surgical fixes; none change game design. Each gets a regression test in E1's harness.

| ID | Item | Fix | Evidence |
|---|---|---|---|
| A1 | Contract expiry off-by-one | Select expiring contracts **before** advancing, or expire where `current_year == years` *then* advance the rest. If end-season already ran for season 1: repair script restoring wrongly-expired contracts (identify via `leagueYearSigned + years - 1 > 2026 AND isFinished=1`, finished at EOS). | `contract_ops.py:374-398` |
| A2 | Offseason `leagueYearSigned` | Introduce one helper `signing_league_year(conn)` = next league year when phase ∈ {OFFSEASON, FREE_AGENCY, DRAFT, RECRUITING}, else current. Use it in `sign_free_agent`, `extend_contract`, `_create_renewal_contract`, IFA signing, draft signing. Also fixes extension double-charged bonus (`books.py:171-209`) and payroll projection flip (`contract_ops.py:724-731`). **[DECISION A2]** confirm rule: "offseason signings belong to the upcoming season". | `transactions.py:925-941` |
| A3 | Auction phases in offseason | Make `advance-fa-round` the offseason clock: it calls `advance_auction_phases(current_week = free_agency_round)` and auctions entered at EOS get `phase_started_week = 0`. Keep `advance_week` driving in-season auctions. Give `end-free-agency` a terminal sweep (see B4). | `fa_auction.py:471`, `timestamp.py:643-667` |
| A4 | One failed signing blocks all finalizations | Wrap `_execute_auction_signing` per auction in try/except + savepoint; record failure on the auction row; continue. | `fa_auction.py:567` |
| A5 | Year-2 carry-over of auctions/demands | Board/pool/demand lookups should select **active** auctions regardless of `league_year_id`, or the FA start step migrates open auctions to the new year id. Orphan sweep must not create a second row for a player with an active auction. | `fa_auction.py:717,1136,1183,466-474` |
| A6 | `/transactions/end-of-season` bypasses the one-shot guard | Remove the route or make it call the same guarded path. Admin button at `app.js:4211` points here. | `transactions/__init__.py:727` |
| A7 | displayovr recompute NameError | Import `text` (or use `sa_text`) in `game_payload.py:4224`; add a timing-log assertion test. | `game_payload.py:4224` |
| A8 | `end-draft` 400 after `complete_draft` | Single owner of `is_draft_time`: `complete_draft` should not clear the flag (or `end_draft` should accept DRAFT-complete). | `draft.py:482`, `timestamp.py:696-739` |
| A9 | `game_results.season` filtered by `league_year_id` | ~10 sites in `games/__init__.py` (587, 794, 826, 1893, 2356, 2514, 2824) + `game_export.py:59`. Resolve through `seasons.year` like `build_week_payloads` does. Works today only because both id sequences start at 1. | arch audit §3.5 |
| A10 | Hardcoded 2026 / id-1 fallbacks | `timestamp.py:58,104,278-329,345,349,493,823`; `contract_ops.py:724-731`. Replace with `league_state` lookups; fail loudly instead of defaulting. | arch audit §9.1 |
| A11 | Weekly processing exists twice | `_run_all_levels_task` (`games/__init__.py:3287`) lacks postseason books-skip, `_ensure_postseason_game_week`, `league_state` sync. Make it call `advance_week`. | arch audit §1.6 |
| A12 | Waiver priority always lowest org_id | `_get_standings_priority` compares `game_results.season` (a `seasons.id`) with a calendar year. | `waivers.py:599-631` |

### 3a. Status (2026-11-07): A1–A12 implemented, not yet committed

| ID | Done | Notes |
|---|---|---|
| A1 | ✅ | Expiring set selected before advancing; only started contracts advance (`leagueYearSigned <= Y`). Dry run: 10,439 expired / 18,675 advanced (old code: 16,725 expired). |
| A2 | ✅ | `services/league_calendar.resolve_signing_year()` used by `sign_free_agent`, `buyout_player`, draft `sign_pick`, IFA signing. Offseason ⇒ Y+1, ledger gets Y+1 id and no game week, budget checked against Y+1. `start-free-agency` refuses until the Y+1 `league_years` row exists (runbook step 11 now precedes step 7). Year-start books skip contracts whose bonus already hit the ledger; signing budget no longer double-counts ledgered bonuses. Signing-time market WAR uses the season just played. |
| A3 | ✅ | `advance-fa-round` calls `advance_auction_phases(current_week=round)`; `start-free-agency` resets `phase_started_week=0` on active auctions. One phase per round. |
| A4 | ✅ | Per-auction SAVEPOINT in `advance_auction_phases`; failures returned in `errors[]`. Verified: a direct-signed player's auction failed without blocking the other. |
| A5 | partial | Orphan sweeps (3 copies) no longer create a second auction when one is active under another year. Board/pool/demand queries still filter by the requested year; full fix waits on decision B4. |
| A6 | ✅ | `/transactions/end-of-season` returns 410; admin Contracts button now calls `/games/end-season`. |
| A7 | ✅ | displayovr probe uses an imported `text`; probe failures are logged. |
| A8 | ✅ | `/games/start-draft` and `/games/end-draft` idempotent. |
| A9 | ✅ | `season_id_sql()` subquery at all 8 sites (rollback-week, rollback-to-week ×2, week-levels, results, export, pbp export, `game_export.build_where`). |
| A10 | partial | `LeagueYearID` no longer falls back to 1; payroll projection reads the sim clock. `ts.get("Season", 2026)` defaults remain (the row always has a season). |
| A11 | ✅ | `run-season-all` runner calls `advance_week()` instead of its own copy. |
| A12 | ✅ | Waiver priority resolves `seasons.id`. |
| B1 bugs | ✅ | Demand backfill commits; `has_auction` in SQL; `source='fa_auction'` written; contract-overview `demand` built from real columns; `computed_at` updated on refresh. Draft signing ends the amateur contract. |

**Calendar overhaul (2026-11-07, user decision):** end-season now creates the Y+1 league year if missing and moves the calendar to it immediately (season Y+1, week 0, offseason). Renewals, auctions, demands and arbitration market rows made at end-season are keyed to Y+1; demand/market WAR is priced on the last season with stats (`league_calendar.pricing_stats_league_year_id`). `start-new-season` now only runs year-start books and sets week 1, and refuses without a schedule. `SeasonContext` gained `display_league_year_id` / `display_season_id` (last played season) which the landing page uses for standings, schedule and leaders; the interface's stats and schedule pages still key on `current_league_year_id` and will show the empty new year during the offseason until they switch to the display fields (workstream F).

**Flagged by the dry run, not a bug in these fixes:** with expiry now correct, the 2,234 HS seniors and 2,211 college seniors expire and are then auto-renewed as 1-year `MINOR_SALARY` contracts at their school (the existing `level < 9` renewal path), so they stay enrolled as "5th years" and the class-year columns reset. That is workstream D3 (graduation) and must be designed before end-season is run for real.

---

## 4. B — Free agency

### B1. Correctness (before FA opens)
- A2–A5 above.
- **Offer validation**: enforce `aav >= min_aav`, `min_years <= years <= max_years`, level in 4–9, org is MLB. Today only `total >= min_aav × min_years` is checked (`fa_auction.py:258`). The interface already validates these client-side, so this is non-breaking.
- **Budget double-count**: `_get_signing_budget` subtracts this year's bonuses that the ledger already debited (`transactions.py:89-111`). Reserve bonus at offer time instead so finalize can't fail on budget.
- **Direct sign of an auctioned player**: `/transactions/sign` must refuse (or withdraw the auction) when an active auction exists; the guide promises this and the code doesn't do it.
- **Demand backfill on GET never commits** (`fa_auction/__init__.py:342,367`). Use `engine.begin()`.
- **Buyout → auction**: `buyout_player` never enters the player; guide says it does. Either wire it or fix the doc. **[DECISION B1]**
- **`has_auction` filter applied after pagination** (`fa_auction.py:1273`) → move into SQL.
- **Record `source='fa_auction'`** in `fa_market_history` (currently always `direct_signing`).

### B2. Pricing model fixes (tuning, informed by P0 data)
- **Unit fix**: define the market rate as **AAV per WAR** everywhere (`Σ aav·w / Σ war·w`). Re-derive season-1 rate from the snapshot and compare to the $8M bootstrap.
- **Stop the feedback loop**: compute the rate **once** at the start of `process_end_of_season` and pass it through; exclude `arb_renewal` rows from the market sample (they are formula outputs, not market signals). **[DECISION B2a]** include extensions in the sample? (recommend yes, with 0.9 weight since they're discounted by design).
- **One WAR model**: replace `player_demands.get_player_war` with `analytics.compute_*_war` (wOBA/FIP/positional) so leaderboard WAR == demand WAR. SUM across teams for traded players. Add a **multi-season blend** for demands: 50/30/20 over last three seasons, regress to 0 below 200 PA / 50 IP, fall back to prior season when the current one has few games (this is what makes in-season year-2 demands non-zero). **[DECISION B2b]** confirm blend weights or supply your own.
- **Age at entry**: take the demand snapshot *after* `progress_all_players` ages players, or add +1 at EOS.
- **Attractiveness scoring**: replace min-max normalisation with ratio-to-best so a $1 AAV edge can't beat a $50M total edge; deterministic tiebreak (`submitted_week, id` like IFA).
- **Arb**: add age multiplier (currently none), and a cap tied to the rate rather than a flat $20M.
- **Move every constant into a `fa_config` table** (mirror `ifa_config`): floors, clamps, lookback, year weights, age-offer weights, phase durations, top-N, arb percentages, replacement levels. Admin card to edit. Removes the five duplicate `FA_THRESHOLD`/`PRE_ARB_SALARY` definitions.

### B3. Calibration data (so season 2 can be tuned from evidence)
Add to `fa_market_history`: `auction_id`, `demand_min_aav`, `demand_min_years`, `bidder_count`, `closing_phase`, `position`, `displayovr_at_signing`, `prev_salary`, `prev_org_id`. Add `fa_auction.outcome` ∈ {signed, expired_no_offers, withdrawn, re-entered} and a `fa_auction_phase_log` table (auction_id, phase, week, offer_count). Store `attractiveness_score` and `eliminated_in_phase` on `fa_auction_offers`. Set `player_demands.computed_at` on update too. Add an admin **FA Outcomes** report in `services/analytics.py` (demand vs signed, by WAR tier/age/position, unsigned list).

### B4. End-of-FA behaviour **[DECISION B4]**
Today `end-free-agency` only flips a flag; auctions with zero offers stay open forever and players stay contract-less. Options:
- (a) **Expire + minor-league fallback**: unsigned MLB FAs sign 1-year MINOR_SALARY deals at level 4 with a CPU org that has roster room (recommended: keeps the league populated, mirrors real NRI deals).
- (b) **Carry into the season**: auctions stay open, in-season `advance_week` keeps driving them (needs A5).
- (c) **Retire** players above an age threshold who got no offers (pairs with D1).

### B5. CPU bidding **[DECISION B5]**
**Reprioritized after 0a: 29 of 30 MLB orgs are human-owned, so this is low value.** Replace with: a deadline-driven FA calendar so inactive humans don't stall auctions, and a CPU check based on owner/GM names rather than `coach`. The original proposal below is kept for reference.

No CPU org bids anywhere (FA, waivers, IFA). Minimum viable: in `advance_auction_phases`, each CPU org (`organizations.coach='AI'`) evaluates open auctions against roster-need by position/level and payroll room, and submits an offer at `min_aav × (1 + small premium)` for players above a WAR threshold. Recommend building this behind a config flag, default **off** for the first FA window so season-1 human behaviour can be observed cleanly; turn on for in-season FA.

### B6. Consolidation (after B1–B3; no behaviour change)
- One **auction engine** parameterised for FA and IFA (phase advance, submit/withdraw, finalize, tiebreak, expiry). IFA already has the better version of several pieces.
- One **demand builder**; one **free-agent definition** query (currently six copies); one **contract-creation** helper (five copies); one **transaction-log** writer (three + raw inserts); one **market-history** writer; one **constants module**.
- Rollback: make `arb_renewal` rollback find its market row; `signing` rollback delete its market row; stop hard-deleting withdrawn offers (status instead).
- Docs: rewrite `free_agency_frontend_guide.md`, delete `fa-pool-api-alignment.md` (implemented), fix `waiver_wire_frontend_guide.md:14,18`.

---

## 5. C — Draft

### C1. Make it correct
| Item | Fix |
|---|---|
| Ranking | Compute `draft_rank` at `initialize_draft` from a composite (reuse `recruiting._compute_recruiting_composite` / `ifa.compute_ifa_star_rankings`) over the pool itself; never depend on `recruiting_rankings`. Stop `season_archive` deleting `draft_eligible_players` for the active draft year. |
| Eligibility **[DECISION C1]** | Options: (a) tutorial rule: HS seniors (`current_year=4` / age 18), college juniors+ (age ≥ 21 or `current_year ≥ 3`), redshirts count; (b) everyone (today). Recommend (a). A "declare / return to school" step for college underclassmen is **not** recommended for season 2. |
| Signing | Finish the amateur contract when the draft contract is created (as IFA does, `ifa_signing.py:1171-1178`); set `contracts.bonus = slot_value` and debit the ledger; `UNIQUE(league_year_id, player_id)` on `draft_picks`; `SELECT … FOR UPDATE` on `draft_state` in `make_pick`. Rookie term and level **[DECISION C2]**: today 3 yrs at level 5 (A), 4 if ≤17. Tutorial says Rookie ball. Recommend: HS → level 4, college → level 5, 3-year minor deals at `MINOR_SALARY`, bonus = slot. |
| Undrafted / passed | Stay at amateur org (college players return; HS seniors move to the recruiting pool). Ties to D3. |
| CPU / idle teams | Only 1 MLB org has no human (see 0a), and `coach` is not a valid signal. Auto-pick immediately for orgs with no owner/GM name; for idle humans, auto-pick from their queue when the server-side clock expires. |
| Server-side clock | A background ticker (one per process, leader-elected via a DB row) expires picks on time and broadcasts; remove the dependence on client polling. |
| Admin overrides | `set-pick` advances the pointer and validates eligibility; `remove-pick` rewinds and voids the contract; both broadcast. |
| `export_draft` | Delete (no-op once signing finishes the amateur contract). |
| HS scouting | Allow MLB orgs the `draft_*` scouting actions on HS targets (`scouting_service.py:262-278`); stop leaking `composite_score`/`star_rating` on `/draft/eligible`. |
| Deadlines | Serialize `pick_deadline_at` as ISO-8601 with `Z`. |

### C2. Sync with the interface (the contract the UI already expects)
| Interface expects | Backend today | Action |
|---|---|---|
| `POST draft/trade/propose` `{league_year_id, proposing_org_id, receiving_org_id, picks_offered[], picks_requested[]}` → `{success, proposal_id}` | n/a | Build: `draft_trade_proposals` table + routes; on accept, call existing `trade_draft_pick` per pick, broadcast `draft_trade_completed`. |
| `GET draft/trade/proposals?org_id&league_year_id` → bare array with org abbrevs | n/a | Build. |
| `POST draft/trade/accept` / `reject` `{proposal_id}` | n/a | Build. |
| `GET draft/picks/{org}` → bare `BaseballDraftPick[]` | `{picks:[…]}` | **[DECISION C3]** change backend or ask interface to unwrap. Recommend change backend. |
| `GET draft/eligible` with `viewing_org_id` optional; flat `first_name/last_name` **and** `bio/ratings/potentials/scouting` | `viewing_org_id` required; reads `firstName` (may be null if live column is `firstname`) | Make optional (fall back to public fog); return both shapes; verify column name against live DB. |
| `sign_status: "refused"` | never set | Drop from doc for season 2 (refusals are out of scope). |
| WS: every message has `type`; draft hook ignores non-draft messages | timestamp broadcasts lack `type` | Add `type:"timestamp"`; broadcast **after commit**; see E2 for multi-worker fan-out. Until fan-out exists, run **1 gunicorn worker** during live drafts. |
| Admin draft panel in the interface calls `/draft/admin/*` with a session cookie | `CORS *` + cookies won't work cross-origin | E2 auth is the real fix; interim: admin routes also accept `X-Admin-Password`. |
| Pick clock countdown from `pick_deadline_at` | naive UTC without `Z` | C1 deadline fix. |

### C3. Docs
Rewrite `docs/draft_frontend_guide.md` from the implemented contract (it currently claims "backend is complete" and documents an older eligible-player shape).

---

## 6. D — New-year bootstrap (runbook steps 10–13, currently "NOT BUILT")

| Item | Proposal | Decision |
|---|---|---|
| D1 Retirements | At end-season after progression: retire if age ≥ 36 and no active pro contract, or age ≥ 40, or (age ≥ 33 and displayovr below a replacement threshold and unsigned). Write `player_retirements` row; keep stats/awards. | **[DECISION D1]** rule |
| D2 Amateur class | Annual generator run after the draft: HS freshmen (age 15, USA) to fill USHS back to its target size; INTAM 16-year-olds to refill the IFA pool; college freshmen come from HS graduation + recruiting commitments (convert `recruiting_commitments` → college contracts, which nothing does today). Reuse `player_engine/player_generation.py` + `seeding/amateur_contracts_seed.py` logic with `LEAGUE_YEAR` parameterised. | **[DECISION D2]** class sizes (recommend: whatever restores season-1 pool sizes) |
| D3 Graduation | HS `current_year=4` → draft pool or college commit; college `current_year=4` (or 5 with redshirt) → draft pool or free agent at level 4 "scraps". Replace the auto-renew of amateur contracts in `contract_ops.py:450-462`. | — |
| D4 Year-2 tables | `initialize-next-league-year` also creates `scouting_budgets`, `ifa_bonus_pools`, `recruiting_state`, `ifa_state`, and a `player_listed_position` refresh for Y+1. | — |
| D5 Checklist | Offseason Checklist rows 7–10 get real completion signals (FA: no active auctions; draft: `draft_state.phase=COMPLETE`; retirements/class: `league_years.rollover_run_at`). | — |

---

## 7. E — API modernization

### E1. Foundations (parallel with A; used by B–D)
1. **Migration runner**: `migrations/NNN_*.sql` + `schema_migrations` table + `python -m migrate` (and a guarded admin endpoint). Baseline 000 = refreshed live schema. Remove lazy `ALTER`/`CREATE` paths (`timestamp.py:432`, `stat_accumulator.py:322`, `awards.py:46`, `task_store.py:83`) and the three admin endpoints that import deleted modules (`admin/__init__.py:1198,1222,1484`).
2. **Test harness**: pytest + `conftest` with a MySQL test database (Docker) seeded from the baseline, an engine stub (`game_engine_client`) and fixtures for one org/roster. First tests: A1–A12 regressions, FA phase lifecycle, draft pick/sign, end-season idempotency. Add pytest to `requirements.txt`; GitHub Actions on push.
3. **Config table** `league_config` (key, value, type, description) replacing hardcoded tunables (B2 `fa_config` is the first consumer); `services/org_constants.py` used everywhere (`scouting/__init__.py:599,658` excludes orgs 341–342 today).
4. **Dead code / hygiene**: delete `_update_player_state_bulk`, `load_subweek_cache`, `_store_game_results`, `export_draft`, empty `app/blueprints/games.py`, `services/games.py`, `financials/__init__.py`; untrack `*.pyc`, `timing_log.txt`, `sim_failures.log`, `.claude/settings.local.json`; fix `.dockerignore`; pin Docker to Python 3.13 to match the venv.
5. **Secrets**: remove the Railway URL from `.env`; confirm the Railway DB is destroyed (password is in git history).

### E2. Tier 2 (during season 2; coordinate breaking items with the interface)
1. **Auth** **[DECISION E1]**: verify the Firebase ID token the interface already sends (`firebase-admin` or PyJWT against Google's JWKs, project id from env); map `uid` → org via a new `user_orgs` table (seeded from `org_report` owner/gm/manager/scout/coach names, which is how the interface resolves orgs today); decorator `@require_org(param="org_id")` on every mutation; `@require_admin` accepting session **or** token with admin claim. Roll out in **audit mode** first (log mismatches, don't reject). Lock `/schema`, `/routes`, `/debug/db`, and the `cash` field on `/api/v1/<org>/`.
2. **WebSocket fan-out**: either Redis pub/sub between workers, or a dedicated single-worker WS process (`/ws` routed separately by Coolify). Add `type` to all messages; stop sending empty keepalive strings.
3. **Response conventions**: one error envelope `{error:{code,message,details?}}`, one pagination shape (`page/per_page/total/pages`), ISO-8601 `Z` timestamps, money as numbers. Ship as `/api/v2` *or* per-endpoint with a version header, so the interface migrates feature by feature. **[DECISION E2]** v2 prefix vs in-place.
4. **Long requests → tasks**: `simulate-week`, `run-week`, `end-season`, `wipe-season`, `archive` return a task id (the `background_tasks` mechanism exists); make tasks survive worker recycle (DB-claimed, resumable) or move them to a worker process.
5. **Identifier cleanup**: one name for the week (`season_week`) and the year (`league_year_id`) in all request bodies; `SeasonID` in the timestamp documented as a league-year id or removed.
6. **Split giant files**: `games/__init__.py` (3.8k) into sim / schedule / export / phase blueprints; `admin/__init__.py` (4.6k) into admin sub-blueprints; `admin/static/admin/app.js` (13.6k) into modules.
7. **Connection budget**: one engine (drop the second in `app.py:1030`), pool sized to 4 workers × 8 threads under the 151 limit.
8. **Docs**: generate an API index from the route table; archive stale guides (`fog-of-war-frontend-guide.md`, `scouting-recruiting-frontend-guide.md`, `recruiting-system.md`, `fa-pool-api-alignment.md`); write `ARCHITECTURE.md` and `ENV.md`; fill `README.md`.
9. **Observability**: timing and failure logs to the DB or stdout (container FS is ephemeral); fix the JSON formatter dropping `extra=`; health check in Dockerfile.

---

## 8. F — Interface sync deliverables (for `simsn-interface-v2`)

Produced alongside B and C, as a change list the interface owner can act on (or as PRs from a fork, **[DECISION F1]**):

- **Draft**: trade-proposal endpoints land (C2); `draft/picks/{org}` shape; `BaseballDraftee` gets both flat and unified fields; WS `type` on timestamp messages so `useWebsockets` stops logging errors; the second raw socket in `useBaseballDraftState` can be dropped once one socket carries typed messages.
- **FA**: `FAOfferModal` hard-caps years at 5 and ignores `demand.max_years`; `WithdrawFAOffer` exists in the service but has no button; `game_week_id` is populated from `current_week_index` (a week number), which is what the API uses today but should be named `season_week`; FA tier filter should move server-side (`fa_type` query param, add to API).
- **Timestamp model**: constructor typo `GameCRan` → `GamesCRan`.
- **Scouting costs** hardcoded client-side (`SCOUTING_ACTION_COSTS`) disagree with the DB (`draft_attrs_precise` 20 vs 10, `draft_potential_precise` 15 vs 50): expose `GET /scouting/config` and read it.
- **Admin**: interface admin panels call unauthenticated routes; after E2 auth they will need the Firebase token path, which they already send.
- **Dead**: `BaseballDraftBoard.tsx`, 40 unused service methods. Informational.

---

## 9. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| A2 | Offseason signings count against the **upcoming** season? | Yes. |
| B1 | Should buyout automatically enter the player into an auction (as the guide says)? | Yes, via the waiver path like a release. |
| B2a | Include extensions in the market-rate sample? | Yes, weight 0.9. Exclude arb renewals. |
| B2b | Demand WAR blend 50/30/20 over three seasons, regress below 200 PA / 50 IP? | Yes, start there, tune from season-2 data. |
| B4 | Fate of unsigned FAs at `end-free-agency`? | (a) minor-league fallback deals with CPU orgs. |
| B5 | Build CPU bidding now? | **No** (29/30 MLB orgs are human). Build deadline-driven FA rounds instead. |
| C1 | Draft eligibility: tutorial rule (HS seniors, college juniors+) or everyone? | Tutorial rule. |
| C2 | Rookie contract: level/term/bonus? | HS→L4, college→L5, 3 yrs at MINOR_SALARY, bonus = slot, no negotiation in season 2. |
| C3 | Change `draft/picks/{org}` to a bare array (match interface) or ask interface to unwrap? | Change backend. |
| D1 | Retirement rule? | Age ≥ 36 unsigned, or ≥ 40, or ≥ 33 + below replacement + unsigned. |
| D2 | Amateur class sizes? | Refill each amateur pool to its season-1 size. |
| E1 | Enforce Firebase token server-side in season 2? | Yes, audit-mode first, then enforce. |
| E2 | Response-convention changes as `/api/v2` or in place? | `/api/v2` for changed endpoints only; v1 frozen. |
| F1 | Deliver interface changes as a written change list or as PRs from a fork? | Change list first; PRs for the mechanical items if wanted. |
| P0 | Has `end-season` already been run for season 1? | **Answered: no.** A1 needs no data repair. |

---

## 12. Offseason dress rehearsal (2026-11-08)

Full runbook (steps 2–13) executed through the real endpoints against a local copy of the live database (private MySQL on 127.0.0.1:3307, API on :8090; driver `C:\Users\Alex\simMLB_rehearsal\rehearse.py`, log `rehearsal_log.md`). 59 steps. Everything below was found by the rehearsal, not by reading code.

| # | Finding | Severity | Status |
|---|---|---|---|
| R1 | `financial_config` is **empty on the live DB**; playoff revenue and end-season (next-year creation) both refuse. | blocker | fixed: `migrations/seed_financial_config.sql` (apply to live before end-season) |
| R2 | `org_media_shares` had no rows for the new year → year-start books paid **$0 media revenue for 2027** (2.55B expected). | blocker | fixed: `initialize_next_league_year` carries the previous year's shares forward |
| R3 | `draft_slot_values` is **empty on the live DB** → every pick signed at the $60,000 fallback. | high | fixed: `migrations/seed_draft_slot_values.sql` (apply to live) |
| R4 | Recruiting `advance-week` crashed with a duplicate `recruiting_rankings` row: renewals left the finished contract `isActive = 1`, so joins on `isActive` returned two contracts per HS senior. | high | fixed: finishing a contract now also clears `isActive`; ranking query filters `isFinished = 0` |
| R5 | Season archive hit a lock-wait timeout deleting ledger detail (its own uncommitted summary inserts blocked the batch deletes), logged a warning, and still returned `ok: true`; 1.5M detail rows stayed. | high | fixed: summary rows committed before the delete; `ok` is false when any step warns |
| R6 | `player_listed_position` had no rows for the new year until the first `advance_week` → blank position labels in week 1. | medium | fixed: `start-new-season` refreshes listed positions |
| R7 | HS seniors (2,234) and college seniors (2,206) expired correctly and were then auto-renewed as 1-year minor deals at their school. | design gap | **F1 graduation** (not built) |
| R8 | Draft pool = all HS + all college (17,744); every `draft_rank` 99999, so the auto-draft took the lowest player ids. | design gap | **F2** (not built) |
| R9 | 150 of 155 auctions never received an offer and stay `open` into the season. | design gap | **F3 end-of-FA** decision pending |
| R10 | Market rate after end-season: $4.44M/WAR, pulled to the floor by 138 arbitration renewals recorded at 0.8 WAR / $3.4M. | tuning | **F3 pricing** |
| R11 | 64 players aged 36+ and nobody retires. | design gap | **F1 retirements** |
| R12 | `scouting_budgets`, `ifa_bonus_pools`, `ifa_state`, `recruiting_state` have no rows for the new year. Scouting budgets and recruiting state self-create on first use; IFA pools are allocated by `ifa/auction/start`/advance-week. | low | verified self-creating; no change |
| R13 | College schedule generator warned "pass 13 — no pairs found, 2 teams still need games" for 2027. | low | open (pre-existing) |
| R14 | Archive of one season takes ~12 min on the local copy (2.3M fielding lines, 1.5M ledger rows); fine as a one-off, but the request is synchronous. | note | E2 long-request tasks |
| R15 | Offseason checklist row 6 reads "done" for the new year trivially (nothing to archive yet). | cosmetic | open |
| R16 | 86 contracts finished during season 1 still carry `isActive = 1`. | low | fixed: `migrations/normalize_finished_contracts_inactive.sql` (apply to live) |
| R17 | Draft signings create contracts with `bonus = 0` (slot value is only spread over salary). | design gap | **F2** rookie contract decision |

**Third pass (after the fixes above): 59/59 steps OK.** 2027 media payouts 2.54B across 30 orgs; ledger detail for 2026 fully archived (268 s, was 724 s with the failure); recruiting rankings 8,864 for 2027; listed positions 28,965 for 2027; round-1 picks signed at the $5M slot.

### Before running the real rollover on the live database

1. Deploy this code to Coolify.
2. Apply, in order: `migrations/seed_financial_config.sql`, `migrations/seed_draft_slot_values.sql`, `migrations/add_draft_picks_player_unique.sql`, `migrations/normalize_finished_contracts_inactive.sql`, `migrations/season2_amateur_pipeline.sql` (the last one has non-idempotent `ALTER TABLE`s: apply exactly once).
3. Take a Coolify database backup.
4. ~~Build F1/F2~~ Built 2026-11-08 (§11a) and verified by the v2 rehearsal (§12b).

## 12b. Season-2 feature rehearsal (2026-11-08, `rehearse2.py`)

Fresh reload of the live dump + all five migrations, full runbook 2-13 through the real endpoints with database assertions after each stage. **84 steps, 0 failures.**

| Stage | Result |
|---|---|
| End-season (70 s) | 2,234 HS seniors graduated: 1,495 enrolled at their committed college, all 2,234 in the draft pool; 2,211 college seniors graduated to the pool; INTAM 832 re-upped / 862 aged out; **0** one-year HS/college renewals (R7 closed). 7 retirements (all 33-35, unsigned, below 40 OVR; nobody in the league is 40+ and no FA is 36+). HS pool refilled to 8,864 (2,234 generated at 15), INTAM to 6,722 (862 generated); HS age distribution 15/16/17/18 ≈ 2,2xx each. Draft pool 11,114 ranked 1..11,114 with class years (4,444 seniors incl. graduates, 2,204 juniors, 2,228 sophomores, 2,234 HS graduates, 4 redshirt freshmen). Scouting budgets 342, IFA pools 30, recruiting state created. |
| Archive (268 s) | ok; draft pool preserved. |
| FA | 5 offers + 1 competing offer; `end-free-agency` signed the 5 contested auctions immediately, expired the 150 without offers and parked all 150 on AAA fallback deals; a fallback player was released at no cost with no waiver entry. Market rate still the $8M default (no FA history with WAR ≥ 0.5 once arbitration rows are excluded — expected until real FA signings exist). |
| Draft | `initialize` reused the 11,114 snapshot; `/draft/eligible` ordered by consensus rank with `class_year`; round-20 pick-for-pick proposal between orgs 2 and 3 (wrong-org accept refused, correct accept swapped the picks); `pick_deadline_at` with `Z`; first live pick returned `ask_bonus` $6.5M (slot $5M × senior 1.0 × talent 1.3); the **server-side clock** auto-picked the rest of round 1 on a 1-second timer; 570 auto-round picks. Negotiation: 50 % lowball rejected (p = 0), offer at the ask accepted → contract with bonus = ask, one ledger entry, amateur contract ended; a sophomore lowballed three times at 61 % (p = 0.0088) was refused and kept his college contract; fourth offer → 400; over-budget offer → 400; admin remove-pick refunded the ledger entry and reset the negotiation. `complete`: the one CPU org signed its 20 picks at the ask, 579 human picks with no offers → `passed`, 1 `refused`; 739 unsigned HS graduates enrolled as walk-ons (0 generated: no program below the floor; rosters 27-44, mean 28.7). |
| Recruiting / schedule / start | 8,864 ranked; schedules for levels 9, 8, 7, 6, 5, 3; `start-new-season` → 2027 week 1, media books paid, no bonus double-booked. |

Notes from the run: (1) the retirement rule bites rarely with season-1 ages; thresholds live in `league_config`. (1b) Follow-up 2026-11-08: the first run placed all 739 unsigned HS graduates as walk-ons (rosters to 44) and left 2,200 undrafted college seniors + 862 aged-out INTAM players in the FA pool indefinitely; the user asked for place-if-needed-else-retire (HS) and assigned / kept / retired (college). Built as F1a/F1c above; results in §12c.

### 12c. v2 rehearsal re-run with the undrafted-player rules (2026-11-08, 87 steps, 0 failures)

Same reload + `rehearse2.py`, three new checks. End-season: 862 INTAM aged out → 382 kept as free agents (`displayovr` ≥ 65), 480 retired (`intam_aged_out`, age 22). Draft complete: 739 unsigned HS graduates → 739 placed at random on 199 programs that were below the target of 28 (max 10 to one program, 0 retired: 828 open slots > 739 graduates), no program with a walk-on ended above 28, 11 generated walk-ons for 6 programs still under the floor; 2,199 undrafted college seniors → 614 kept, 1,585 retired (`college_undrafted`, ages 23-24). Undrafted tier left in the FA pool: 615 ex-college + 382 ex-INTAM. Retirement leaves rows intact: all 2,072 retirees still have their `simbbPlayers` row, 1,564 of them have season stat rows. Retirement reasons so far: `unsigned_marginal` 7, `intam_aged_out` 480, `college_undrafted` 1,585. Knobs: `college_roster_target`, `undrafted_keep_ovr`, `never_signed_retire_age` in `league_config`. (2) 579 picks `passed` only because the rehearsal makes no human offers; in a real draft every human org must offer within the signing window or lose the pick. (3) The market rate needs real FA signings before it leaves the bootstrap value; the first real FA period provides them.

Calendar overhaul verified by the rehearsal: end-season created 2027 (inflation 3.74%), moved the clock to 2027 week 0, FA/draft/recruiting ran under 2027, the landing page kept showing 2026 standings and leaders through the offseason, five auctions signed for 2027 with the bonus booked under 2027 and no game week, invalid offers (AAV below demand) and direct signing of an auctioned player were refused, `start-new-season` refused until schedules existed and then set week 1.

## 11. Feature specs for season 2 (proposed 2026-11-08, approved and built 2026-11-08)

Decisions already taken by the user: offseason signings belong to the upcoming season and the calendar moves to Y+1 at end-season (done); college underclassmen do not declare but can be drafted, with a signing negotiation that can send them back to school. The user approved every proposal below on 2026-11-08 ("all of those suggestions make sense, go for it").

### 11a. Implementation status

| Feature | Status | Where |
|---|---|---|
| F1 graduation (HS → college commitment / draft pool; college seniors → draft pool; INTAM re-up / age-out) | **built** | `services/graduation.process_amateur_expiries`, called from `contract_ops.process_end_of_season` (amateur expiries no longer hit the minor-league renewal path) |
| F1 retirements (40+; 36+ unsigned; 33+ unsigned & `displayovr` < 40) | **built** | `graduation.process_retirements`, `player_retirements` table; retirees excluded from auctions, FA pool, draft pool, orphan sweep |
| F1 new classes (HS freshmen at 15, INTAM entrants at 15, refill to 8,864 / 6,722) | **built** | `graduation.generate_amateur_classes` after progression; `player_engine.generate_players(region_type=…)` |
| F1a college floor 25 + walk-ons at 19; unsigned HS graduates placed at random on programs below `college_roster_target` (28), surplus retires | **built** (random placement + retirement added 2026-11-08 on user request) | `graduation.enroll_hs_walkons` / `topup_college_rosters`, run by `draft.complete_draft` |
| F1c undrafted college seniors and aged-out INTAM players: kept as free agents (signable, WBC-eligible) at `displayovr` ≥ `undrafted_keep_ovr` (65), else retired; never-signed players retire at 25 | **built** 2026-11-08 | `graduation.retire_undrafted_seniors` (complete-draft), `process_amateur_expiries` (INTAM), `retirement_reason(ever_pro=)`; WBC auto-rosters skip retirees |
| F1 config | **built** | `league_config` table (`migrations/season2_amateur_pipeline.sql`), defaults in `services/league_config.py` |
| F2 eligibility (HS graduates + all college), consensus ranking | **built** | `graduation.build_draft_pool` / `rank_draft_pool`; `draft._populate_eligible_players` reuses the snapshot; archive keeps `draft_eligible_players` |
| F2a rookie contract (HS → L4, college → L5, 3 yrs minor salary, bonus = agreed, ledgered at signing) | **built** | `draft.sign_pick` |
| F2 bonus ask / 3 offers / deterministic acceptance / refusal returns to school | **built** | `draft.compute_bonus_ask`, `acceptance_probability`, `offer_roll`; `draft_signing.ask_bonus…`, `draft_signing_offers` |
| F2 complete-draft resolution (CPU orgs sign at ask; pending → refused/passed) | **built** | `draft._resolve_pending_signings` |
| F2b compensation pick for a refused R1/R2 pick | **not built** (kept out of scope per §10; revisit after season 2) | — |
| F2 server-side pick clock, CPU instant picks, `Z` deadlines | **built** | `services/draft_clock.py` (GET_LOCK leader), `draft._cpu_autopick_chain`, `draft._iso_z` |
| F2 trade proposals (`draft/trade/propose|proposals|accept|reject`), `draft/picks/{org}` bare array | **built** | `draft.create_/list_/accept_/reject_draft_trade_proposal`, `draft_trade_proposals` table |
| F2 HS scoutable by MLB orgs; composite/star not leaked | **open** | scouting_service action gating (small, next) |
| F3a end-of-FA: offers → signed now; no offers → `expired` + 1-yr fallback deal (AAA / L4), free offseason release | **built** | `fa_auction.close_free_agency_auctions`, `_fallback_sign`; `transactions.release_player` fast path; `contracts.fa_fallback` |
| F3 pricing: AAV/WAR, arb excluded, extensions 0.9, 50/30/20 blended WAR regressed below 200 PA / 50 IP, age multiplier on arb, ratio-to-best attractiveness, `fa_config` | **built** | `market_pricing.get_current_dollar_per_war`, `player_demands.get_blended_war`, `fa_auction._offer_attractiveness` |
| F4 year-2 tables at end-season | **built** | `graduation.bootstrap_year_tables` (scouting budgets, `ifa_state` + pools from Y standings, `recruiting_state`) + listed positions |
| F5 interface change list | **written** | `docs/INTERFACE_CHANGES_SEASON_2.md` |

Verification: `tests/test_draft_negotiation.py` (pure math + retirement rule, 16 tests) and the v2 dress rehearsal (`C:\Users\Alex\simMLB_rehearsal\rehearse2.py`, results in §12b).

### F1. Graduation and the amateur pipeline (D2 + D3) — must exist before end-season runs for real

**Why:** with contract expiry fixed, 2,234 HS seniors and 2,211 college seniors expire at end-season and are then auto-renewed as 1-year `MINOR_SALARY` contracts at their school (the `level < 9` renewal path), i.e. everyone becomes a fifth-year and class years reset.

**Mechanics, run inside `process_end_of_season` before the generic renewal step:**

| Who | What happens at end-season |
|---|---|
| HS player, `current_year < 4` | contract advances (already correct). |
| HS senior (`current_year = 4`) | amateur contract finishes. If he has a `recruiting_commitments` row → new college contract at that org: `years=4, current_year=1`, level 3, redshirt per the commitment; else he goes to the draft pool as source `hs` **and** stays in the recruiting pool (an undrafted/unsigned HS senior can still be recruited). |
| College player, `current_year < years` | contract advances. |
| College senior (`current_year = years`, 4 or 5 with redshirt) | amateur contract finishes; enters the draft pool as `college`. Undrafted/unsigned seniors become level-4 free agents ("scraps"). |
| Draft pool snapshot | `draft_eligible_players` is built here (HS seniors, **all** college players per the user's rule) with `draft_rank` computed from the composite at that moment; `season_archive` must stop deleting it. |

**New amateur class, run as the last step of end-season:**

- **HS freshmen:** generate `N_hs = target_hs_size − current HS count` 15-year-old USA players with `player_engine.generate_players(age=15)` and HS contracts `years=4, current_year=1` at USHS (340). Target = the pool size at the start of season 1 (8,864) unless configured otherwise.
- **INTAM:** generate 16-year-olds to refill the IFA pool to its season-1 size; INTAM contracts as `seed_amateur_contracts` does today.
- **College freshmen:** come only from HS graduation + commitments (no generation), so college roster sizes are driven by recruiting. A per-org floor (e.g. 25) is topped up with walk-ons generated at age 19 if recruiting left a program short. **[DECISION F1a]** floor value.
- All sizes live in `league_config` (E1) so they can be tuned without code.

**Retirements (D1)** run just before class generation so roster counts are final. Rule proposed: retire if age ≥ 40; or age ≥ 36 and no active pro contract; or age ≥ 33, no active contract and `displayovr` below the level-4 replacement threshold. Writes `player_retirements (player_id, league_year_id, age, reason)`; stats, awards and contracts history untouched. **[DECISION F1b]** thresholds.

### F2. Draft: eligibility, ranking, negotiation, return-to-school (C1)

- **Eligible:** HS seniors + every college player (freshman through redshirt senior). No declaring.
- **Ranking:** `draft_rank` from a composite of true ratings and potentials (reuse `recruiting._compute_recruiting_composite` / IFA star ranking), computed once at pool creation; ties by potential then id. Fog of war still applies to what orgs *see*; the rank itself is the "industry consensus" and is visible.
- **Rookie contract:** HS → level 4, college → level 5; 3 years at `MINOR_SALARY`; `bonus = agreed bonus` (ledgered, counts against the signing budget). **[DECISION F2a]** term/levels.
- **Bonus ask:** `ask = slot_value × class_mult × talent_mult`, where `class_mult` = 1.00 senior, 1.15 junior, 1.35 sophomore, 1.60 freshman, 1.10 HS senior; `talent_mult` = 0.9–1.3 from the composite rank within the pool. Stored on `draft_signing.ask_bonus` at pick time and visible to the drafting org only.
- **Negotiation window:** the SIGNING phase lasts N FA-style rounds (admin "Advance signing round"); an org submits up to 3 offers per pick (`draft_signing_offers`: amount, round). Each offer is answered immediately and deterministically (seeded by pick id + offer no.): accept if `offer ≥ ask`; otherwise accept with probability `p = clamp((offer/ask − 0.6) / 0.4, 0, 1) × willingness`, where `willingness` = 1.0 senior/HS, 0.6 junior, 0.35 sophomore, 0.2 freshman. A rejected third offer, or the window closing, = **refused**.
- **Refused:** `draft_signing.status = 'refused'`; the player's amateur contract keeps running (he returns to school; a HS senior falls back to his commitment / the recruiting pool); the pick is spent. Compensation pick next year for a refused round-1/2 pick: **[DECISION F2b]** yes/no.
- **Interface mapping:** the signing tab already models `pending/signed/passed/refused`; add `ask_bonus`, `offers[]`, and `POST /draft/sign/{pick_id}` takes `{league_year_id, bonus}` (current behaviour = offer at slot value).
- **Pool shape fix:** HS prospects must be scoutable by MLB orgs (`draft_*` actions on HS targets) and `composite_score` / `star_rating` must not leak past the fog.
- **Also:** server-side pick clock (background ticker, leader-elected via a DB row) and immediate auto-pick for orgs with no owner/GM name; trade proposals per §5 C2.

### F3. Free agency: end-of-window behaviour and pricing (B2, B4)

- **End of FA (B4):** on `end-free-agency`, every auction still `open` with no offers expires (`outcome = 'expired_no_offers'`). Expired MLB FAs get a 1-year `MINOR_SALARY` deal at level 8 (AAA) with the org that has the most roster room at that level, flagged `fa_fallback = 1` so the org can release him at no cost before week 1; minors FAs the same at level 4. **[DECISION F3a]** confirm, or choose carry-into-season / retire.
- **Pricing (B2):** rate = AAV per WAR; computed once per end-season run; arbitration rows excluded from the sample, extensions included at 0.9 weight; one WAR model (analytics) with SUM across teams; demand WAR = 50/30/20 blend of the last three seasons regressed to 0 below 200 PA / 50 IP; age multiplier applied to arbitration as well; ratio-to-best attractiveness with a deterministic tiebreak; all constants in `fa_config`. **[DECISION F3b]** blend weights.
- **In-season auctions:** continue to be driven by `advance_week`; a released/waived player enters an auction as today.

### F4. Year-2 bootstrap tables (D4)

`end-season` (now that it creates the next year) also creates: `scouting_budgets` for every org, `ifa_bonus_pools` + `ifa_state`, `recruiting_state`, and refreshes `player_listed_position` for the new year. The checklist's rows 7–10 get real completion signals.

### F5. Interface sync (F)

Change list for `simsn-interface-v2`, to be delivered as a document and, for the mechanical items, as a PR: use `SeasonContext.display_league_year_id` on stats/schedule/standings pages during the offseason; draft trade-proposal endpoints and `draft/picks/{org}` shape; `BaseballDraftee` dual shape; `FAOfferModal` honours `demand.max_years` (the API now enforces it); timestamp WS messages carry `type: "timestamp"`; `GameCRan` typo; scouting costs from the API.

## 10. Explicitly out of scope for season 2
- Bonus negotiation / draft refusals; draft lottery and compensation picks; future-year pick trading.
- Full CPU front-office AI beyond B5's minimal bidder and the draft auto-pick.
- Engine-side tickets (short games, pitching decisions, injury durations), tracked in `docs/SUPPORT_TICKETS.md`.
- Rewriting raw SQL into an ORM; storage-efficiency batches (separate maintenance window).

## 13. Progression QC, diagnostics and training camp (proposal 2026-11-08, for discussion)

### 13a. What progression does today (verified on the rehearsal copy)

- `player_engine/player_progression.progress_all_players` runs once inside end-season. Every player under 45 ages one year; each of the 39 progressed values (19 abilities + 5 pitches × 4 sub-abilities) rolls `triangular(min, mode, max)` from `growth_curves (grade, age)`, independently. Age ≤ 19 floors the roll at −1. Potential grades never change. Pitch OVRs are recomputed; nothing else is.
- `growth_curves` covers ages **16–45** for all 14 grades (30 rows each). Shape: growth 16–28 scaled by grade (A+ mode 30 at 16 → 4 at 28; C 16 → 0 at 27; D flat from 21; F −3/yr from 17; N −5/yr), a plateau 29–33 with mode 0 and max ≤ 2 for every grade, then a **grade-blind decline**: mode −1 at 34–36, −2 at 37–45, min −9, max 0, identical for A+ and F. Past 45 nothing changes (the loop only ages the player).
- The "cap of 40" is not the table: it is `retire_age_hard = 40` in `league_config` (F1). A 40-year-old is progressed normally; he is retired by rule.
- **displayovr is a cohort percentile, not an absolute rating.** `services/ovr_core.compute_displayovr` maps a weighted raw average of the base attributes to its percentile inside the (level, ptype, position) cohort, then to 20–80 through the inverse normal. If a whole cohort improves, nobody's displayovr moves. Trend diagnostics must use `raw_ovr` and the base attributes, never displayovr. It also means the F1/F1c thresholds are percentiles: 65 ≈ top 7 % of the level, 40 ≈ bottom 16 %.

### 13b. Defects found

| # | Finding | Evidence | Fix |
|---|---|---|---|
| P1 | **displayovr is never refreshed after progression.** Only the admin calibration endpoints call `recompute_stored_displayovr`. | Dry run on the post-rehearsal copy: 29,159 players recomputed, 20,000+ values change, shifts of −30…+40 at pro levels. Retirement (`unsigned_marginal`), the F1c keep thresholds, FA pool cards, waiver fallbacks and admin analytics all read the stale column. | Call `recompute_breakpoints` + `recompute_stored_displayovr` right after `progress_all_players` in end-season, and again at `complete_draft` (cohorts change when graduates and draftees move level). ~1 hour. |
| P2 | **Free agents are never recomputed.** `_load_all_active_players_as_display` joins `contracts.isActive = 1`; a player without a contract keeps the displayovr of his last cohort forever even though `compute_displayovr` has a `FREE_AGENT_LEVEL` peer group. | 3,096 contract-less players untouched in the dry run. | Include contract-less players with `is_free_agent=True` in the refresh. |
| P3 | **Decline is grade-blind and flat.** From 34 on, A+ and F lose the same −2/yr; after 45 attributes freeze. With the cap raised to 50 a 48-year-old on a contract would still be a viable player. | `growth_curves` rows 34–45. | Extend to 50 and give the tail a slope, see 13c. |
| P4 | **No rating history.** No snapshot table; `season_archive` keeps stats but no attributes. Year-over-year trends are impossible to show. | — | `player_rating_snapshots`, see 13d. |
| P5 | 39 independent rolls per year (a B-grade 22-year-old can lose 5 in contact and gain 12 in power the same offseason). | table ranges | **Not a defect** — intended: attributes are specific and roll independently (user decision 2026-11-08; a shared factor was built and rolled back). |
| P6 | Progression writes 32k single-row UPDATEs in one transaction (~70 s end-season). Works; not a defect, but snapshots and the recompute will add to it. | timing in §12b | Move progression + recompute + snapshot into the existing task runner later if end-season grows past ~3 min. |

### 13c. Extend the curve to 50 (proposal, numbers to tune in the sandbox)

1. `retire_age_hard` 40 → **50** (config only). Keep 36-unsigned, 33-marginal and 25-never-signed.
2. `progress_all_players`: `max_age` 45 → 51 and the `new_age > 45` guard → 50.
3. `growth_curves`: add ages 46–50 for every grade and reshape 33–50 so the decline is smooth and grade-aware:

| Age | mode (C grade) | min | max | grade factor on mode and min |
|---|---|---|---|---|
| 29–32 | 0 | −3 | +1 | — |
| 33 | −0.5 | −4 | +1 | A tier × 0.75, B × 0.9, C × 1.0, D × 1.1, F/N × 1.25 |
| 34–36 | −1 | −6 | 0 | same |
| 37–39 | −2 | −8 | 0 | same |
| 40–42 | −3 | −9 | 0 | same |
| 43–45 | −4 | −10 | 0 | same |
| 46–50 | −5 | −12 | 0 | same |

Effect: a C-grade 60 at 33 is ≈ 48 at 40 and ≈ 30 at 46; an A-grade 70 at 33 is ≈ 61 at 40 and ≈ 46 at 46, i.e. the rare 40-year-old stays usable and 46+ is marginal on his own. The sandbox (`services/progression_sandbox`) can chart these before they go in. Admin UI already has the growth-curve editor section for the table itself.

### 13d. Diagnostics the admin panel needs (true values; the fog only applies to org views)

**Data.** New table `player_rating_snapshots (id, player_id, league_year_id, stage ENUM('pre_progression','post_progression','post_camp'), age, level, org_id, ptype, raw_ovr DECIMAL(6,2), displayovr TINYINT, attrs JSON, created_at)`, written inside end-season before and after progression (and after the camp step if camp lands). ~32k rows × ~1.5 KB per stage ≈ 50 MB/stage; the archive step can thin `attrs` to the last 3 seasons and keep `raw_ovr` forever.

**Endpoints** under `/admin/analytics/progression-*`, all reading the snapshots:

| Endpoint | Shows | Answers |
|---|---|---|
| `table-vs-actual?season=` | per (grade, age): table mode and min/max vs. the realised mean, p10, p90 of attribute deltas; cells flagged when the realised mean is > 1 point off the mode | "is the table doing what it says?" |
| `age-profile?level=` | mean `raw_ovr` by age for each snapshot year, overlayed; peak age; share of players whose raw_ovr fell | "where is the peak, is the decline right?" |
| `drift` | league-wide mean/percentiles of `raw_ovr` per level per season, and the HS/INTAM entry-class mean per season | "is the system stationary?" (entry quality vs progression vs retirement must balance; a +1/season drift means generation or the table is off) |
| `outliers?season=&n=` | biggest raw_ovr gainers/losers this offseason with their expected band and z-score | bug detector; also the "feel-good" list |
| `player/{id}` | every snapshot for one player: age, level, raw_ovr, displayovr, all 39 bases with per-season delta and the table's expected band, camp bonuses if any | the diagnostic a user ticket needs ("my guy lost 12 in power") |
| `camp-effects?season=` (with 13e) | mean delta of camp-focus attributes vs non-focus across the league, by level | "is the camp slight but noticeable?" |

**Admin UI.** One new section "Progression" (dark theme, `.data-table`, Chart.js): grade selector + table-vs-actual chart with the realised band over the table band; age-profile lines per season; drift line per level; outlier table; player lookup with the 39-attribute trajectory table. The existing sandbox stays for what-if edits to the table.

### 13e. Training camp (proposal)

**Intent.** Slight but noticeable, long-horizon input: a four-year college product is a little better in the attribute his program emphasised; a long-tenured pro has his weaknesses smoothed over time. Not a second progression system.

**Mechanism.** The camp adds a **bias to the triangular mode** of chosen attributes in the yearly progression roll; it never replaces the roll and never changes potentials.

- Each org files one **camp plan per team** for the league year: pro orgs one per level (L4–L9), colleges one per program. A plan has `mode`: `focus` (named attributes) or `smooth` (the bonus goes to each player's weakest weighted attributes automatically), `focus_attrs` (up to `camp_max_focus`, default 2, from a fixed menu: contact, power, discipline, eye, speed, baserunning, fielding (catch+react+spot), throwing (power+acc), pitch control (pgencontrol + pcntrl subs), pitch movement (pbrk subs), pitch consistency, endurance, framing), and optional **individual plans** for up to `camp_individual_slots` (default 3) players with their own focus.
- **Budget of bias:** `camp_points_per_year` (default 1.5) split across the plan's focus attributes per player (two focus attributes → +0.75 each on the mode). Diminishing returns: bias × max(0, 1 − base/90) so an 80 cannot be pushed further. Four college years at +1.5 ≈ +5–6 in one attribute (≈ 0.5 SD on the 20–80 scale): visible, not dominant. A 10-year pro career on `smooth` lifts the weakest attribute by ~1/yr.
- **Age gating:** full bias to 29, half 30–33, zero 34+. Option for discussion: a `maintain` mode for veterans that halves the decline on one attribute instead (cheap to add, useful once the curve goes to 50).
- **Cost:** none in v1 (every team gets the same points; the choice is the strategy). If a cost is wanted later: ledger `entry_type = 'training_camp'` with a per-level fee in `financial_config`.
- **CPU orgs** default to `smooth`. **Window:** plans editable from start-new-season until end-season locks them; the camp step runs inside end-season between progression and the snapshot.
- **Tables:** `training_camp_plans (org_id, league_year_id, team_level NULL for college, mode, focus_attrs JSON, individual JSON, updated_by, updated_at, locked_at)`, `training_camp_effects (player_id, league_year_id, attr, bias_applied)` for diagnostics. Config keys in `league_config`: `camp_points_per_year`, `camp_max_focus`, `camp_individual_slots`, `camp_age_full`, `camp_age_half`.
- **Endpoints:** `GET /training-camp/options`, `GET|PUT /training-camp/plan?org_id&league_year_id[&team_level]`, `GET /training-camp/effects/{player_id}` (own org only, fuzz-safe: it shows the bias chosen, not the attribute's true value), `GET /admin/training-camp/summary`.
- **Interface:** a Training Camp card on the team page (pro: per level; college: program) with the attribute menu, mode toggle and the individual-plan list; a "camp" badge on roster rows. Attribute values stay fuzzed; the camp reveals nothing extra.

### 13f. Decisions taken (2026-11-08) and build status

| # | Decision | Status |
|---|---|---|
| G1 | Fix P1/P2: refresh `displayovr` + breakpoints after progression and at complete-draft; contract-less players refreshed against their last level's cohort | **built** (`ovr_core._load_free_agents_as_display`, hooks in `timestamp.end_regular_season` and `draft.complete_draft`) |
| G2 | Curve: extend 46–50 **with the age-45 values**; the potential-agnostic decline is intentional (older players have met their potential). **No automatic retirement on age**: `retire_age_hard` = 0 (rule disabled); 36-unsigned, 33-marginal and 25-never-signed stay | **built** (`migrations/season2_progression_camp.sql`; `progress_all_players` reads the table's age range instead of a 45 constant; players past the table only age) |
| G3 | Shared yearly development factor | **rejected and rolled back** (2026-11-08): attributes are specific and their dice must stay unrelated. `sample_delta` is the plain independent triangular draw; no config key. |
| G4 | Snapshots pre/post progression with all 39 bases + potentials, raw_ovr, displayovr | **built** (`services/progression_snapshots.take_snapshot`; retention thinning left for the archive step) |
| G5 | Diagnostics: table-vs-actual, age profile, drift, outliers, player trajectory, camp effects | **built** (`/admin/analytics/progression-*`, admin section *Progression → Diagnostics*) |
| G6 | Training camp: **one focus skill per player**, chosen by the org; the skill's potential grade is shifted for this progression pass only; intensities regular +1 / intense 75 % +2 · 25 % −2 / max 50 % +4 · 50 % −4 | **built** (`services/training_camp.py`, blueprint `/training-camp/*`, `docs/training_camp_frontend_guide.md`) |

Finding from the first snapshot pair: the growth table's **mode is not what players get on average**. A triangular(min, mode, max) draw averages (min+mode+max)/3; with the table's wide negative tails (e.g. B at 22: −5 / 7 / 12) the realised mean is 4.7, not 7. The table-vs-actual report therefore compares with the table mean and shows both numbers; if the modes were meant as the typical outcome, the min/max columns need narrowing (sandbox work, not code).

### 13g. Rehearsal results (v2 driver re-run, 2026-11-08: 106 steps, 1 driver-side threshold error, 0 API failures)

- **Camp:** six MLB players of org 1, two per intensity, focus `power`. Results rolled as designed: regular C- → C and A- → A; intense F → D (+2) twice; max B+ → A+ (+4, clamped) and one backfire B → C- (−4). Setting a focus from another org → 400; after end-season → 400 (camp locked). Org results view carries steps/backfire only, no grades.
- **End-season** now 134 s (was 70 s): pre snapshot 28,661 players, progression 29,148 (every player aged, table to 50), displayovr refresh 28,661 incl. 3,514 contract-less players, post snapshot, 333 (grade, age) curve cells. Complete-draft refresh 30,329 incl. 1,170 free agents.
- **Table vs actual:** 330 of 333 cells within 0.75 of the table mean. The 3 flagged cells are grade N at 17–19 (+0.8 above the mean): the age ≤ 19 floor of −1 clips N's −5 mode, by design.
- **Age profile** of the first pair: peak mean raw_ovr at 30 for MLB, 23 for college, 28 overall. **Drift baseline** (post, mean raw_ovr): L1 18.4 · L2 25.7 · L3 31.6 · L4 43.5 · L5 45.6 · L6 46.2 · L7 47.8 · L8 49.5 · L9 54.8 · no contract 36.0. Oldest player 39; no pure-age retirements.
- **Outliers:** top gainer a 16-year-old (+28.8, the age-16 "build" year), top loser a 37-year-old (−7.0, z −1.4): nothing anomalous.
- **Caveat found by the camp-effects report:** the camp shifts the *potential grade*, and from 29 on the growth table is potential-agnostic (plateau, then the same decline for every grade). A focus on a player aged 29+ therefore changes nothing; the six org-1 test players were all 30+, and their focus deltas equal their other attributes'. The camp as specified works for amateurs and pros through 28 (four college years ≈ +1 step on one skill every year). If the "long-tenured pro smooths a weakness" goal matters, the camp needs a second lever for the plateau/decline years (e.g. +1 on the mode of the focus skill, or halving its decline). **Open decision.**

### 13h. Original decision list (for reference)

| # | Question | Proposed default |
|---|---|---|
| G1 | Fix P1/P2 now (recompute after progression and at complete-draft, include free agents)? | yes, before the live rollover |
| G2 | Decline tail numbers and grade factors (13c) | as tabled; tune in the sandbox |
| G3 | Per-player yearly development factor (P5) | yes, 50/50 blend |
| G4 | Snapshot stages and retention | pre/post progression (+ post camp), full attrs for 3 seasons, raw_ovr forever |
| G5 | Camp: points 1.5, max 2 focus, 3 individual slots, free, age gate 29/33, `smooth` default for CPU | as listed |
| G6 | `maintain` mode for veterans | defer |

Effort: 13b fixes + 13c ≈ 1 day; 13d ≈ 2–3 days; 13e backend ≈ 2 days, interface ≈ 2–3 days.
