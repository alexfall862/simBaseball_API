# Offseason Runbook — Season Rollover

This is the ordered procedure for closing a league year after the MLB postseason and starting the next one. The rollover is a set of independent manual endpoints with no built-in sequencing; this document is the sequence, and the **Offseason Checklist** card in the admin panel (Timestamp section) shows which steps have been detected as done.

Read the whole thing once before your first rollover. Several steps are one-shot and cannot be undone.

Terminology used below:

- **L** = `league_years.id` of the season that is ending (the first season is `L = 1`).
- **Y** = that row's `league_years.league_year` (e.g. `2026`).
- The `/admin/run-*` and `/admin/initialize-next-league-year` endpoints in `app.py` take **`league_year` = Y (the year number)**, not the id. The `/api/v1/games/*` and `/api/v1/awards/*` endpoints take **`league_year_id` = L**. Mixing these up is the easiest mistake to make.

---

## Table of Contents

1. [Checklist Card and Endpoint](#checklist-card-and-endpoint)
2. [Admin Password Header](#admin-password-header)
3. [The Steps, In Order](#the-steps-in-order)
4. [What Is Not Automated](#what-is-not-automated)
5. [If a Step Failed Halfway](#if-a-step-failed-halfway)
6. [Quick Reference](#quick-reference)

---

## Checklist Card and Endpoint

**Admin panel:** Timestamp section → *Offseason Checklist* card. Pick the league year that is ending, click **Refresh**. Each row shows a status pill:

| Pill | Meaning |
|------|---------|
| `done` | A database signal says the step ran. |
| `pending` | The signal is absent. |
| `manual` | No completion signal exists; the row shows the current phase flags and you confirm by hand. |
| `not built` | The step has no implementation in the API at all (see [What Is Not Automated](#what-is-not-automated)). |
| `unknown` | The detector query failed (missing table/column, DB error); the detail column shows the error. |

Steps 2, 3, 4 and 11 have a **Run** button that POSTs to the step's endpoint and then refreshes the card. Steps 5, 6, 12 and 13 already have their own UI (named in the Action column); the card just tells you when to use them.

**Endpoint (read-only):**

```
GET /admin/offseason/checklist?league_year_id=L
```

Requires the admin session (login through the admin panel). Omit `league_year_id` to default to `league_state.current_league_year_id`.

Response shape:

```json
{
  "ok": true,
  "league_year_id": 1,
  "league_year": 2026,
  "next_league_year": 2027,
  "next_league_year_id": null,
  "phase": "REGULAR_SEASON",
  "timestamp": { "Season": 2026, "Week": 53, "IsOffSeason": false,
                 "IsFreeAgencyLocked": true, "FreeAgencyRound": 0,
                 "IsDraftTime": false, "IsRecruitingLocked": true, "RunGames": false },
  "league_state": { "current_league_year_id": 1, "current_game_week_id": 52 },
  "league_years": [ { "id": 1, "league_year": 2026 } ],
  "steps": [
    { "key": "world_series", "order": 1, "title": "World Series complete",
      "done": false, "manual": false, "not_built": false,
      "detail": "World Series not complete. Series complete per round: WC 0/4, DS -/-, CS -/-, WS -/-",
      "action": null }
  ]
}
```

`done` is `true`, `false` or `null` (`null` = manual or could not evaluate). `action`, when present, is `{method, url, body, label, header?, confirm?, blocked?}`; `header: "X-Admin-Password"` means the endpoint needs the admin password header, `confirm: true` means the UI asks first because the step cannot be re-run, and `blocked` names the unmet prerequisite (the UI then hides the button).

---

## Admin Password Header

The endpoints defined in `app.py` (`/admin/run-playoff-revenue`, `/admin/run-year-end-interest`, `/admin/initialize-next-league-year`, and the other `/admin/run-*` books endpoints) do **not** use the admin session. They compare the `X-Admin-Password` request header against the `ADMIN_PASSWORD` environment variable and return `401` on mismatch. The checklist card reads the password from the admin login box (or prompts for it) and sends that header for you. From curl:

```bash
curl -X POST "$HOST/admin/run-year-end-interest" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Password: $ADMIN_PASSWORD" \
  -d '{"league_year": 2026}'
```

The endpoints under `/admin/` defined in `admin/__init__.py` (checklist, schedule, archive) and the `/api/v1/draft/admin/*` routes use the admin session cookie instead. Most other `/api/v1/` routes, including the phase transitions, currently have no authentication at all (tracked in `docs/MASTER_PLAN_SEASON_2.md`, workstream E2).

---

## The Steps, In Order

### 1. World Series complete

| | |
|---|---|
| **Where** | Playoffs section of the admin panel (create the MLB bracket, then sim it round by round). |
| **Done when** | `playoff_series` has a row with `league_year_id = L`, `league_level = 9`, `round = 'WS'`, `status = 'complete'`. |
| **Precondition** | Regular season finished for every MLB team (the bracket is seeded from standings). |
| **Irreversible?** | No, but re-running series overwrites results. |

The checklist also shows how many series in each round (`WC`, `DS`, `CS`, `WS`) are complete, and says so if no level-9 bracket exists yet. The MiLB and college brackets are not part of this gate.

### 2. Postseason awards recorded

| | |
|---|---|
| **Where** | Automatic: the sim writes `pennant` (CS winners) and `world_series` (WS winner) rows into `player_awards` when a series clinches. Backfill: `POST /api/v1/awards/sync-postseason` with `{"league_year_id": L}` — the card's **Backfill awards** button. |
| **Done when** | `player_awards` has `award_code = 'world_series'` rows for `league_year_id = L`. |
| **Precondition** | Step 1. The button is hidden until the WS is complete. |
| **Irreversible?** | No — the backfill is idempotent and can be re-run; individual awards can be revoked with `DELETE /api/v1/awards/<award_id>`. |

MVP, Cy Young, Silver Slugger and Gold Glove are **admin-entered** (see `docs/awards_frontend_guide.md`); they are not tracked by the checklist. Record them now if you want them, before the new season starts.

### 3. Playoff revenue books

| | |
|---|---|
| **Where** | `POST /admin/run-playoff-revenue` with `{"league_year": Y}` and the `X-Admin-Password` header — the card's **Run playoff revenue** button. |
| **Done when** | `league_years.playoff_revenue_run_at IS NOT NULL` for `id = L`. |
| **Precondition** | Step 1 (playoff gate revenue is computed from the playoff games actually played). The button is hidden until the WS is complete. |
| **Irreversible?** | It claims `playoff_revenue_run_at` atomically and refuses a second run; the ledger rows it creates (`playoff_gate`, `playoff_media` in `org_ledger_entries`) are not deleted automatically. |

### 4. Year-end interest

| | |
|---|---|
| **Where** | `POST /admin/run-year-end-interest` with `{"league_year": Y}` and the `X-Admin-Password` header — the card's **Run interest** button. |
| **Done when** | `league_years.interest_run_at IS NOT NULL` for `id = L`. |
| **Precondition** | Step 3, and all weekly books for the year have run — interest is computed on each org's net balance to date, so run it after every other Y ledger entry exists. |
| **Irreversible?** | Claims `interest_run_at` and refuses a second run; creates `interest_income` / `interest_expense` ledger rows. |

### 5. End Season

| | |
|---|---|
| **Where** | Timestamp section → *End Regular Season* card (`#btn-end-season`), which POSTs `/api/v1/games/end-season` with `{"league_year_id": L}` (optional `"force": true`). |
| **Done when** | `league_years.season_ended_at IS NOT NULL` for `id = L`. The column is added lazily on the first end-season call (`migrations/add_league_years_season_ended_at.sql` is the same DDL if you prefer to apply it by hand). Until it exists the checklist treats the step as not done. |
| **Precondition** | Step 1 — end-season refuses to run while the World Series is incomplete unless `force: true` is sent. The timestamp must be in `REGULAR_SEASON`, and `L` must be the year the timestamp is on. |
| **Irreversible?** | **Yes.** It creates the Y+1 `league_years` row and its `game_weeks` if they do not exist yet (same as step 11), resolves outstanding waivers, runs end-of-season contract processing (service time, expirations, FA eligibility), ages and progresses every player, applies a **16-week offseason injury tick** (injuries heal as if 16 weeks passed), and then **moves the calendar to Y+1**: `timestamp_state.season = Y+1`, `week = 0`, `OFFSEASON` flags, `league_state.current_league_year_id` = the new id. It is one-shot: a second call is refused because `season_ended_at` is already set. |

Do **not** use `force: true` for a normal rollover; it exists for leagues that deliberately skip the postseason.

**The new league year begins the moment the season ends.** Free agency, the draft and recruiting all run with the calendar already on Y+1, so every contract they create is for the season it will be played in, and auctions, demands and draft state are keyed by the new `league_year_id`. The landing page's standings, schedule and leaders keep showing the last season that was actually played (`SeasonContext.display_league_year_id`) until week 1 of Y+1 is simmed; `SeasonContext.current_league_year_id` is already Y+1.

Contract processing expires only contracts whose **completed** season was their final year (`current_year == years`) and then advances every other started contract by one year. (Until 2026-11-07 it advanced first and expired second, which ended every multi-year deal, HS class year and college class year one season early.) Players whose contracts expire with 6+ years of MLB service are entered into the FA auction pool with `phase_started_week = 0`; they wait there until step 7.

**Graduation, retirements and the new amateur class** (added 2026-11-08, `services/graduation.py`) run inside the same call, so the response's `end_of_season` block now also carries `graduation`, `retirements` and `draft_pool`, and the top level carries `amateur_classes`, `year_tables` and `listed_positions`:

| Who | What end-season does |
|---|---|
| HS senior (`current_year = 4`) | HS contract finishes. With a `recruiting_commitments` row (any year) he gets a 4-year college contract at that program for Y+1; either way he enters the Y+1 draft pool as `hs` / `hs_senior`. |
| College senior (`current_year = years`) | College contract finishes; enters the draft pool as `college` / `senior`. Undrafted or unsigned seniors are then plain free agents (level-4 pool). |
| INTAM player at contract end | Re-upped at org 339 until the `intam_age_out` age (23), then leaves the pool as a free agent. |
| Everyone 40+, 36+ without a pro contract, 33+ unsigned and below `retire_marginal_ovr` | Retired: open contracts finished, active auction withdrawn, row in `player_retirements`. Retirees never enter FA or the draft pool. |
| Draft pool | `draft_eligible_players` for Y+1 = HS graduates + **every** college player (nobody declares), with `class_year` and a consensus `draft_rank` from the ratings/potentials composite. The archive no longer deletes it. |
| Progression (2026-11-08) | Bracketed by true-value **rating snapshots** (`player_rating_snapshots`, stages `pre_progression` / `post_progression`); **training camp** focus skills (`training_camp_focus`) are rolled and applied as potential-grade overrides for this pass only (results in `training_camp_results`); every player ages, those inside the growth table (16–50) progress (independent triangular draw per attribute); then `displayovr` and its breakpoints are **refreshed** (also for players without a contract, against their last level), and `progression_curve_stats` is rebuilt for the admin *Progression → Diagnostics* page. Response keys: `snapshot_pre`, `training_camp`, `progression`, `displayovr_refresh`, `snapshot_post`, `curve_stats`. |
| New classes (after progression) | HS freshmen (US, age `hs_entry_age`) and INTAM entrants (international, `intam_entry_age`) are generated to refill both pools to `hs_pool_target` / `intam_pool_target`. |
| Year tables | `scouting_budgets` for every org, `ifa_state` + `ifa_bonus_pools` (from Y's standings), `recruiting_state`, `player_listed_position` for Y+1. |

All sizes and thresholds live in `league_config` (defaults in `services/league_config.py`). Schema: `migrations/season2_amateur_pipeline.sql` (apply before the real end-season).

The old `POST /api/v1/transactions/end-of-season` route, which ran the same contract processing without the one-shot guard, now returns `410 Gone`. The *Run End of Season* button in the Contracts section calls `/games/end-season` like this card does.

### 6. Archive Season

| | |
|---|---|
| **Where** | Timestamp section → *Season Archive* card (`#btn-season-archive`), `POST /admin/season/archive` with `{"league_year_id": L, "dry_run": false}`. |
| **Done when** | `game_batting_lines` and `player_fatigue_state` both have zero rows for `league_year_id = L` (there is no claim column; the archive deletes both tables' rows for the year). |
| **Precondition** | Step 5. Archiving deletes the per-game data that end-season and the awards/leaderboard views still read, so never archive first. |
| **Irreversible?** | **Yes.** It deletes per-game box-score lines, play-by-play, substitutions, fatigue state and ledger detail for the year. Accumulated season stats, standings and the schedule are preserved. |

Run it **once**, with **Dry Run unchecked**. Do a dry run first if you want to see the row counts. If the season was never simulated the detector will show `done` trivially (both counts are already zero).

### 7. Free Agency — manual, confirm complete

| | |
|---|---|
| **Where** | Timestamp section dynamic actions: `POST /api/v1/games/start-free-agency`, `POST /api/v1/games/advance-fa-round` (repeat), `POST /api/v1/games/end-free-agency`. Auction detail: `docs/free_agency_frontend_guide.md`, `docs/fa-auction-phases-frontend-guide.md`. |
| **Done when** | No completion signal exists. The card shows the phase and `is_free_agency_locked` / `free_agency_round` flags; when the phase is `FREE_AGENCY` it says "in progress". A locked window only means FA is not open now — it does not prove FA ran. |
| **Precondition** | Step 5 (players only become free agents through end-season contract processing; it also moves the calendar to Y+1, which is the year the auctions and signings belong to). |

**The FA rounds are the auction clock.** The offseason has no game weeks, so each `advance-fa-round` call moves every active auction one phase: an auction with at least one offer goes `open → listening` on the first advance after the offer, `listening → finalize` (top 3 offers kept) on the next, and is **signed on the one after that**. Starting from round 1 with bids placed, rounds 2, 3 and 4 complete the first wave; later bids need three more advances. Auctions with no offers stay `open` indefinitely. The response of `advance-fa-round` includes `auction_phases` with the counts per transition and an `errors` list (an auction whose signing failed — player signed elsewhere, bonus over budget — is reported there and does not block the others).

Offseason contracts (FA, buyout, draft, IFA) are stamped with `leagueYearSigned = Y+1` (the calendar year), their bonus ledger entry carries the Y+1 `league_year_id` with no game week, and the signing budget is checked against Y+1. Demands and market WAR are priced on the last season with stats (Y) until week 1 of Y+1 is played. Year-start books for Y+1 skip any contract whose bonus already has a ledger entry, so nothing is charged twice.

**`end-free-agency` resolves every auction still active.** Auctions with offers are run to a winner immediately; auctions that never drew an offer are marked `expired` and the player is parked on a **1-year fallback deal** (`contracts.fa_fallback = 1`, minor salary) at AAA (level 8) if he came off an MLB contract, otherwise at level 4, with the MLB org that has the fewest players at that level. The org can release him during the offseason at no cost (`POST /transactions/release` ends the contract outright, no waivers). The response carries `fa_close` with `signed_with_offers`, `expired_no_offers`, `fallback_deals` and the fallback list.

Pricing (2026-11-08): the market rate is **AAV per WAR** over the last three seasons, arbitration renewals excluded and extensions at 0.9 weight; demand and arbitration WAR is a 50/30/20 blend of the last three seasons, each regressed toward 0 below 200 PA / 50 IP; arbitration also applies the age multiplier. Constants live in `fa_config`.

### 8. Draft — manual, confirm complete

| | |
|---|---|
| **Where** | `POST /api/v1/games/start-draft`, then the Draft Admin section, then `POST /api/v1/games/end-draft`. See `docs/draft_frontend_guide.md`. |
| **Done when** | No completion signal exists. The card shows `is_draft_time`. |
| **Precondition** | Step 7 closed (`is_free_agency_locked = true`). |

`POST /games/start-draft` and `POST /games/end-draft` are idempotent: the Draft Admin's *Start* and *Complete* actions set and clear `is_draft_time` themselves, so calling the `/games` endpoints afterwards returns success instead of a 400.

**Pool and ranking.** `initialize` reuses the Y+1 snapshot end-season built (HS graduates + every college player, ranked); it only rebuilds from the live rosters if no snapshot exists. **Clock.** A server-side ticker (one leader per database) auto-picks expired picks; orgs with no owner and no GM name pick immediately in live rounds. **Signing is a negotiation** (`docs/draft_frontend_guide.md` §9): each pick carries a bonus ask (slot × class × talent); the org gets up to three offers (`POST /draft/sign/{pick_id}` with `bonus`); an accepted offer creates a 3-year minor-salary rookie deal (HS → level 4, college → level 5) with the bonus debited at once, and ends the amateur contract; a third rejection is a **refusal** and the player returns to school on his amateur contract. *Complete* resolves every remaining pick (CPU orgs sign at the ask; others become `refused` or `passed`), then settles the leftovers: unsigned HS graduates are placed at random on programs with roster room (below `college_roster_target`, default 28) and the surplus retires (`hs_undrafted`); undrafted college seniors stay in the FA pool only at `displayovr` ≥ `undrafted_keep_ovr` (default 65) and otherwise retire (`college_undrafted`); programs still below `college_roster_floor` are topped up with generated walk-ons. Pick-for-pick trade proposals: `POST /draft/trade/propose`, `GET /draft/trade/proposals`, `POST /draft/trade/accept|reject`.

### 9. Recruiting — manual, confirm complete

| | |
|---|---|
| **Where** | `POST /api/v1/games/start-recruiting`, `POST /api/v1/recruiting/advance-week` (repeat), `POST /api/v1/games/end-recruiting`. See `docs/recruiting_admin_frontend_guide.md`. |
| **Done when** | No completion signal exists. The card shows `is_recruiting_locked`. |
| **Precondition** | Step 8 ended (`is_draft_time = false`). |

### 10. Retirements and new amateur class — automatic (inside step 5)

Since 2026-11-08 retirements, graduation and the new HS / INTAM classes happen inside end-season (see step 5), and college walk-ons / undrafted-senior retirements are settled when the draft completes (step 8). Aged-out INTAM players (23) are kept as free agents only at `displayovr` ≥ `undrafted_keep_ovr`, else retired (`intam_aged_out`); any unsigned player who never held a pro contract retires at `never_signed_retire_age` (25). Retirement never deletes anything: the player row, his stats, awards and contract history stay; `player_retirements` is the only marker. Nothing to run here; check `player_retirements` for the year and the `amateur_classes` block of the end-season response if you want to confirm. Tune sizes and thresholds in `league_config`. Nobody retires on age alone (`retire_age_hard` = 0); the growth table runs to 50 and players beyond it only age.

### 11. Initialize next league year

| | |
|---|---|
| **Where** | `POST /admin/initialize-next-league-year` with `{"league_year": Y}` (the **current** year; it creates Y+1) and the `X-Admin-Password` header — the card's **Create Y+1** button, which asks for confirmation first. |
| **Done when** | A `league_years` row with `league_year = Y+1` exists **and** `game_weeks` has at least `weeks_in_season` rows for it. |
| **Precondition** | Step 4 (inflation is applied to the current year's `performance_budget` and `media_total`; do it after the Y books are final). Can technically run any time after step 1. **Step 5 runs it automatically** if the row does not exist yet, so this is now optional; run it by hand only if you want the inflated budgets fixed before ending the season. |
| **Irreversible?** | The endpoint refuses to run once the Y+1 row exists, so it cannot be re-run. If the row exists but `game_weeks` is short, insert the missing weeks by hand (`league_year_id`, `week_index`, `label`). |

When this step is done the card shows the new `league_years.id`, and the *Start New Season* card's **New League Year ID** input is pre-filled with it (unless you have already typed in that box).

### 12. Generate schedule for the new year

| | |
|---|---|
| **Where** | Schedule Generator section (`POST /admin/schedule/generate` with `{"league_year": Y+1, "league_level": <level>, "start_week": 1, "clear_existing": false}`), once per level you run (9, 8, 7, 6, 5, 3). |
| **Done when** | `gamelist` has rows with `season = (SELECT id FROM seasons WHERE year = Y+1)`. The card shows the per-level game counts. |
| **Precondition** | A `seasons` row for Y+1 must exist (the table is pre-seeded through 2044). Step 11 is not strictly required by the generator but do it first so the week ids line up. |
| **Irreversible?** | No — `clear_existing: true` or `POST /admin/schedule/clear` removes a level's schedule for the year. Do this only before step 13. |

Generate every level you intend to simulate; the checklist only requires at least one game to exist, so look at the per-level breakdown.

### 13. Start New Season

| | |
|---|---|
| **Where** | Timestamp section → *Start New Season* card (`#btn-start-new-season`), `POST /api/v1/games/start-new-season` with `{"league_year_id": <new id from step 11>}`. |
| **Done when** | `timestamp_state.season = Y+1` and `league_state.current_league_year_id` = the new id. |
| **Precondition** | Steps 5 and 12; the calendar is already on Y+1 (week 0) and must be in `OFFSEASON` with FA, draft and recruiting all closed (the card is hidden otherwise). The endpoint refuses if `gamelist` has no games for Y+1. |
| **Irreversible?** | It runs year-start books (media payouts, signing bonuses — each claims `media_run_at` / `bonuses_run_at` on the new row) and sets week 1, regular season. Going back means hand-editing `timestamp_state` and `league_state`. |

After this, the Offseason Checklist for the **old** year should read all `done` except rows 7-10, and selecting the new year should show a fresh, all-`pending` list.

---

## What Is Not Automated

Nothing creates these for year Y+1; check each before the first simulated week:

| Item | What to do |
|------|------------|
| **Retirements** | Not built. No player is retired automatically. |
| **New amateur class** (draft, IFA, college freshmen) | Not built. No players are generated. |
| `scouting_budgets` for Y+1 | Not created by `initialize-next-league-year`. Insert rows for every org for the new `league_year_id` (see `migrations/fix_scouting_budgets_2000.sql` for the shape). |
| `ifa_bonus_pools` for Y+1 | Not created. Insert per-org pools for the new year before the IFA signing period (`docs/ifa_signing_frontend_guide.md`). |
| `recruiting_state` for Y+1 | Not created. Reset/insert the recruiting state rows before `start-recruiting` in the next offseason. |
| Admin-entered awards (MVP, Cy Young, Silver Slugger, Gold Glove) | Enter through `POST /api/v1/awards` (body per `docs/awards_frontend_guide.md`) for year L if wanted. |
| Listed positions and default gameplans | Optional: the *Listed Positions* and *Default Gameplans* cards in the Timestamp section if rosters changed a lot. |

---

## If a Step Failed Halfway

Every one-shot step protects itself with a **claim column**: it sets the column with a single `UPDATE ... WHERE <col> IS NULL` before doing the work, so a retry is refused. If the work then failed part-way (DB timeout, deploy mid-request), the column is set but the work is incomplete. To re-run, inspect what was actually written, clean up if needed, then NULL the claim by hand:

| Step | Claim column | Re-run after |
|------|--------------|--------------|
| 3 Playoff revenue | `league_years.playoff_revenue_run_at` | `DELETE FROM org_ledger_entries WHERE league_year_id = L AND entry_type IN ('playoff_gate','playoff_media');` then `UPDATE league_years SET playoff_revenue_run_at = NULL WHERE id = L;` |
| 4 Year-end interest | `league_years.interest_run_at` | `DELETE FROM org_ledger_entries WHERE league_year_id = L AND entry_type IN ('interest_income','interest_expense');` then `UPDATE league_years SET interest_run_at = NULL WHERE id = L;` |
| 5 End Season | `league_years.season_ended_at` | `UPDATE league_years SET season_ended_at = NULL WHERE id = L;` — **only** if end-season genuinely did not finish. Its sub-steps (waivers, contracts, progression, injury tick) each log their own error into the response and are not individually re-runnable; running end-season twice ages every player twice and expires contracts twice. |
| 13 Start New Season (year-start books) | `league_years.media_run_at`, `league_years.bonuses_run_at` on the **new** row | Delete the `media` / `bonus`,`buyout` rows with `game_week_id IS NULL` for the new `league_year_id`, then NULL the matching column and call `POST /admin/run-year-start-books` or start-new-season again. |
| Weekly books (not a rollover step, same pattern) | `game_weeks.books_run_at` | NULL it for the week and re-run `POST /admin/run-week-books`. |

For steps with no claim column:

- **6 Archive** is safe to re-run; it deletes whatever is left.
- **11 Initialize next year**: if the `league_years` row was created but `game_weeks` was not, insert the weeks by hand rather than deleting the row (other tables may already reference the new id).
- **12 Schedule**: re-run the generator with `clear_existing: true` for the affected level.
- **2 Awards backfill** is idempotent; just run it again.

Use the SQL console in the admin panel (write mode on) for the `UPDATE`/`DELETE` statements, and refresh the checklist afterwards to confirm the row flipped back to `pending`.

---

## Quick Reference

```
 1. World Series complete       Playoffs section                          playoff_series WS complete
 2. Postseason awards           auto; POST /api/v1/awards/sync-postseason {league_year_id: L}
 3. Playoff revenue             POST /admin/run-playoff-revenue {league_year: Y}      [X-Admin-Password]
 4. Year-end interest           POST /admin/run-year-end-interest {league_year: Y}    [X-Admin-Password]
 5. End Season                  End Regular Season card -> POST /api/v1/games/end-season {league_year_id: L}   ONE-SHOT; creates Y+1 and moves the calendar to it
 6. Archive Season              Season Archive card (Dry Run OFF) -> POST /admin/season/archive           IRREVERSIBLE
 7. Free Agency                 start-free-agency / advance-fa-round* / end-free-agency   (confirm by hand; each round advances auctions one phase)
 8. Draft                       start-draft / Draft Admin / end-draft                     (confirm by hand)
 9. Recruiting                  start-recruiting / recruiting advance-week* / end-recruiting (confirm by hand)
10. Retirements + amateur class NOT BUILT
11. Initialize Y+1              done by step 5; POST /admin/initialize-next-league-year {league_year: Y} only to do it early
12. Schedule for Y+1            Schedule Generator, one run per level, league_year = Y+1
13. Start New Season            Start New Season card -> POST /api/v1/games/start-new-season {league_year_id: new id}
```
