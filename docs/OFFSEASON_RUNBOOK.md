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

The endpoints under `/admin/` defined in `admin/__init__.py` (checklist, schedule, archive) and everything under `/api/v1/` use the admin session cookie instead.

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
| **Irreversible?** | **Yes.** It resolves outstanding waivers, runs end-of-season contract processing (service time, expirations, FA eligibility), ages and progresses every player, applies a **16-week offseason injury tick** (injuries heal as if 16 weeks passed), and flips the timestamp to `OFFSEASON`. It is one-shot: a second call is refused because `season_ended_at` is already set. |

Do **not** use `force: true` for a normal rollover; it exists for leagues that deliberately skip the postseason.

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
| **Precondition** | Step 5 (players only become free agents through end-season contract processing). |

### 8. Draft — manual, confirm complete

| | |
|---|---|
| **Where** | `POST /api/v1/games/start-draft`, then the Draft Admin section, then `POST /api/v1/games/end-draft`. See `docs/draft_frontend_guide.md`. |
| **Done when** | No completion signal exists. The card shows `is_draft_time`. |
| **Precondition** | Step 7 closed (`is_free_agency_locked = true`). |

### 9. Recruiting — manual, confirm complete

| | |
|---|---|
| **Where** | `POST /api/v1/games/start-recruiting`, `POST /api/v1/recruiting/advance-week` (repeat), `POST /api/v1/games/end-recruiting`. See `docs/recruiting_admin_frontend_guide.md`. |
| **Done when** | No completion signal exists. The card shows `is_recruiting_locked`. |
| **Precondition** | Step 8 ended (`is_draft_time = false`). |

### 10. Retirements and new amateur class — NOT BUILT

There is **no retirement logic** and **no amateur-class generation** in the API. Nothing ages players out, and no new draft/IFA/college class is created for year Y+1. Until this is built, either accept a shrinking talent pool or handle it by hand (SQL inserts / external generator) before step 13. The card renders this row as a warning so it is not forgotten.

### 11. Initialize next league year

| | |
|---|---|
| **Where** | `POST /admin/initialize-next-league-year` with `{"league_year": Y}` (the **current** year; it creates Y+1) and the `X-Admin-Password` header — the card's **Create Y+1** button, which asks for confirmation first. |
| **Done when** | A `league_years` row with `league_year = Y+1` exists **and** `game_weeks` has at least `weeks_in_season` rows for it. |
| **Precondition** | Step 4 (inflation is applied to the current year's `performance_budget` and `media_total`; do it after the Y books are final). Can technically run any time after step 1. |
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
| **Precondition** | Steps 5, 11 and 12; the timestamp must be in `OFFSEASON` with FA, draft and recruiting all closed (the card is hidden otherwise). |
| **Irreversible?** | It runs year-start books (media payouts, signing bonuses — each claims `media_run_at` / `bonuses_run_at` on the new row) and moves the timestamp to week 1 of Y+1. Going back means hand-editing `timestamp_state` and `league_state`. |

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
 5. End Season                  End Regular Season card -> POST /api/v1/games/end-season {league_year_id: L}   ONE-SHOT
 6. Archive Season              Season Archive card (Dry Run OFF) -> POST /admin/season/archive           IRREVERSIBLE
 7. Free Agency                 start-free-agency / advance-fa-round* / end-free-agency   (confirm by hand)
 8. Draft                       start-draft / Draft Admin / end-draft                     (confirm by hand)
 9. Recruiting                  start-recruiting / recruiting advance-week* / end-recruiting (confirm by hand)
10. Retirements + amateur class NOT BUILT
11. Initialize Y+1              POST /admin/initialize-next-league-year {league_year: Y}  [X-Admin-Password]  ONE-SHOT
12. Schedule for Y+1            Schedule Generator, one run per level, league_year = Y+1
13. Start New Season            Start New Season card -> POST /api/v1/games/start-new-season {league_year_id: new id}
```
