# simsn-interface-v2 — change list for season 2

Backend changes in `simBaseball_API` (2026-11-08) that the interface needs to pick up, grouped by page. Each item names the API contract first; the interface file references are from the review of `CalebRose/simsn-interface-v2` (`src/` paths) and may have moved.

## 1. Season calendar (every page that keys on the season)

The league year now begins the moment `POST /games/end-season` runs: `timestamp` moves to Y+1 / week 0 / `OFFSEASON`, and free agency, the draft and recruiting run under the **new** `league_year_id`.

| API | Interface change |
|---|---|
| `GET /bootstrap/landing/{org}` → `SeasonContext` has `current_league_year_id` (the year the calendar is on) **and** `display_league_year_id` / `display_league_year` / `display_season_id` (the last season with results). | Standings, schedule/results, leaders and team stats pages: read `display_*` during the offseason, otherwise they show an empty Y+1. Use `current_league_year_id` for FA, draft, recruiting, contracts and budgets. |
| Timestamp WebSocket messages now carry `type: "timestamp"`. | `useWebsockets`: route on `type`; the draft hook can ignore non-draft messages and the second raw socket in `useBaseballDraftState` can be dropped. |
| Timestamp model field is `GamesCRan`. | Fix the constructor typo `GameCRan`. |

## 2. Draft room

| API | Interface change |
|---|---|
| `GET /draft/picks/{org}?league_year_id=` returns a **bare array** (was `{picks:[…]}`). Each entry adds `ask_bonus`, `class_year`, `offers_made`, `offers_remaining`, `offers[]`, `bonus_agreed`, `contract_id`. | `BaseballDraftPick[]` already typed as an array: remove any unwrap. Show `ask_bonus` and the offer history on *My Picks*. |
| `GET /draft/board` entries add `class_year`, `offers_made`, `bonus_agreed`; `picked_at` / `pick_deadline_at` end with `Z`. | Render class badge; `new Date(pick_deadline_at)` is now unambiguous UTC. |
| `GET /draft/eligible`: `viewing_org_id` optional; players carry flat `first_name/last_name/age/source/draft_rank/class_year` **and** `bio/ratings/potentials/scouting`. Pool = HS graduates + all college players, ranked 1..N. | `BaseballDraftee` dual shape; drop any "declared" filter; sort by `draft_rank`. |
| `POST /draft/sign/{pick_id}` body `{league_year_id, bonus?}` → 200 with `accepted: true|false`, `status` (`pending|signed|refused`), `offer_no`, `offers_remaining`, `ask_bonus`, `accept_probability`. 400 only for invalid requests (not pending, no offers left, over budget). | Signing tab: offer input (default slot value), show the ask, three attempts, "refused — returned to school" state. `sign_status: "refused"` is now real. |
| `POST /draft/trade/propose` `{league_year_id, proposing_org_id, receiving_org_id, picks_offered[], picks_requested[]}` → `{success, proposal_id}`; `GET /draft/trade/proposals?league_year_id&org_id[&status]` → bare array with `proposing_org_abbrev` / `receiving_org_abbrev` and pick briefs; `POST /draft/trade/accept|reject` `{proposal_id, org_id}`. | These are the four calls the draft room already makes; they exist now. New WS events `draft_trade_proposed`, `draft_trade_rejected`. |
| Server-side clock: expired picks are auto-picked by the API; CPU orgs (no owner/GM) pick instantly. | Stop client-side auto-pick calls; keep the countdown from `pick_deadline_at` and refresh on `draft_pick_made`. |

## 3. Free agency

| API | Interface change |
|---|---|
| `POST /fa-auction/{id}/offer` enforces `min_aav`, `min_years..max_years`, level 4–9, MLB org. | `FAOfferModal`: cap years at `demand.max_years` (not a hard 5) and floor AAV at `min_aav`; surface the 400 message. |
| `POST /transactions/sign` refuses players in an active auction (400). | Hide "sign directly" for players with `has_auction`. |
| `POST /games/end-free-agency` returns the timestamp plus `fa_close` (`signed_with_offers`, `expired_no_offers`, `fallback_deals`, `fallback[]`). Auctions may now be `expired`. Fallback contracts carry `fa_fallback: 1`. | Admin FA panel: show the close summary. Roster views: badge fallback players ("release at no cost before week 1"). `POST /transactions/release` on one during the offseason returns `fa_fallback_released: true`. |
| `FAOfferModal` sends `game_week_id` from `current_week_index`. | Rename to `season_week` when the API adds it; unchanged for now. |

## 4. Rosters, players and transactions

| API | Interface change |
|---|---|
| Retired players: `player_retirements` rows (`reason` ∈ `age`, `unsigned`, `unsigned_marginal`, `never_signed`, `hs_undrafted`, `college_undrafted`, `intam_aged_out`); they disappear from the FA pool, draft pool and WBC auto-rosters, their contracts are finished. Stats, awards and contract history are untouched. | Player page: show "Retired (year)" when a career has no active contract and a retirement row (`/stats/player` will carry `retired` once exposed; until then infer from the FA pool exclusion). |
| New transaction types in the feed: `college_enroll`, `walkon_enroll`, `retirement`, `fa_fallback`, `draft_refused`. | Add labels/icons in the transaction log component. |
| Graduation: HS seniors become college freshmen (committed), walk-ons at a random program with room, or retire; undrafted college seniors stay in the FA pool only above `undrafted_keep_ovr`, else retire; INTAM players age out at 23 into the FA pool under the same rule. | College roster pages: freshmen appear after end-season; no interface change beyond expecting them. FA pool: expect a small "undrafted" tier (last level 2/3). |

## 4b. Training camp (new, `docs/training_camp_frontend_guide.md`)

| API | Interface change |
|---|---|
| `GET /training-camp/options`; `GET /training-camp/focus?org_id&league_year_id`; `PUT` / `DELETE /training-camp/focus`; `GET /training-camp/results?org_id&league_year_id`. One focus skill + intensity (`regular` / `intense` / `max`) per player per season, set by the org holding the contract (pro levels 4–9, college programs). | New "Training Camp" tab on the team / program page: per-player skill dropdown (19 abilities + the player's pitches) and intensity selector with the risk text; `locked` rows read-only; results view after end-season with a backfire marker. No grades are exposed. |

## 4c. Ratings semantics (no endpoint change)

`displayovr` is a percentile inside the player's level/position cohort mapped to 20–80, not an absolute rating. It is now refreshed at end-season and when the draft completes; between those points it is stable. Progression trends should not be read from it.

## 5. Scouting

| API | Interface change |
|---|---|
| Action costs come from the DB (`scouting_config`), not the client table. | Replace `SCOUTING_ACTION_COSTS` with a fetch of the config (endpoint to be added: `GET /scouting/config`). |

## 6. Admin

Interface admin panels call `/admin/*` and `/draft/admin/*` with a session cookie; cross-origin they need the `X-Admin-Password` header until the Firebase-token auth lands (plan §7 E2).

## Delivery

Change list first (this document). PRs against the interface for the mechanical items (array unwrap, `Z` deadlines, `type` routing, draft trade calls, `GameCRan`) can follow on request.
