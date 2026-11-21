# Offseason UX Checklist (interface)

For the `simsn-interface-v2` team. What the interface needs so clubs can run their offseason
with confidence: contracts, extensions, arbitration, free agency, the draft, amateur windows
and the preseason. Each item names the API it builds on; details are in the linked guides.
A shared, tickable copy of this list is published as an artifact ("Offseason UX Checklist").
College programs have their own list: `COLLEGE_OFFSEASON_UX_CHECKLIST.md`.

Based on the API as of 2026-11-21. Source of truth for contracts: `INTERFACE_CHANGES_SEASON_2.md`,
`free_agency_frontend_guide.md` (Season 2 changes), `contract_extensions_frontend_guide.md`,
`draft_frontend_guide.md`, `training_camp_frontend_guide.md`, `waiver_wire_frontend_guide.md`.

## Foundations

Shared pieces every offseason screen leans on.

- [ ] **Offseason hub** (`base-01`). One place that says, in plain words, where the league is ("Free agency, round 3"), what is open now, what comes next, with links to each action page.
  - `GET /games/timestamp: Phase, Season, FreeAgencyRound, IsOffSeason, IsFreeAgencyLocked, IsDraftTime, IsRecruitingLocked`
- [ ] **Live phase updates** (`base-02`). Route WebSocket messages on type "timestamp" and refresh the hub, banners and phase-gated buttons without a page reload.
  - `WebSocket message type "timestamp"`
- [ ] **Right season on every page** (`base-03`). During the offseason, standings, results, leaders and team stats read the display season; free agency, draft, recruiting, contracts and budgets use the current league year.
  - `GET /bootstrap/landing/{org} → SeasonContext.display_league_year_id / display_season_id / current_league_year_id`
- [ ] **Phase-aware actions** (`base-04`). Hide or disable actions that are not open, and say why and when they open ("Free agency opens after the season ends"). No button should lead to a phase error.
- [ ] **Notification center** (`base-05`). Unread badge, list and mark-as-read. Group free agency messages by their prefix ("Free agency:", "Free agency closed:") and link to the player or auction when possible.
  - `Bootstrap Notifications (club's MLB team)`
  - `PUT /notifications/{id}/read`
- [ ] **Transaction feed labels** (`base-06`). Labels and icons for every offseason transaction type so the feed reads as a story of the offseason.
  - `extension, fa_auction_sign, fa_fallback, arb_renewal, retirement, college_enroll, walkon_enroll, draft_refused`
- [ ] **Club money panel** (`base-07`). Wherever money is spent: cash available for signings, money held by the club's active free agency offers (bonus plus first-season salary of each active offer), and next season's committed payroll.
  - `GET /transactions/signing-budget/{org}`
  - `GET /fa-auction/board my_offer entries`
  - `GET /transactions/payroll-projection/{org}`
- [ ] **Terms explained in place** (`base-08`). Consistent money formatting ($11.4M), aligned numbers in tables, and short explanations on hover or tap for AAV, WAR, service years, arbitration and fallback deals.
- [ ] **Club token on free agency writes** (`base-09`). Send the club's token on offer and withdraw calls and show the 401 message if it is refused. Keep each club's token with that club's account only.
  - `Header X-Org-Token on POST /fa-auction/{id}/offer and DELETE /fa-auction/{id}/offer/{org}`
- [ ] **Phone width and accessibility** (`base-10`). Every offseason screen works at phone width, with visible keyboard focus and states that do not rely on color alone.

## Contracts and roster

What happens to each player when the season ends, and the actions clubs take before it does.

- [ ] **Contract status at a glance** (`con-01`). A chip per player: Minors, Pre-arbitration, Arbitration (year 1, 2 or 3), Free-agent eligible; years to arbitration and to free agency; a Final-year chip on expiring deals.
  - `GET /transactions/contract-overview/{org}: contract_phase, mlb_service_years, years_to_arb, years_to_fa, is_expiring`
- [ ] **What happens at season end** (`con-02`). Expiring contracts grouped by outcome: renews at $40k (minors), renews at $800k (pre-arbitration), arbitration renewal at 40%, 60% or 80% of market value, becomes a free agent, already extended.
  - `contract-overview: contract_phase, is_expiring, has_extension`
- [ ] **Extension flow** (`con-03`). Extend appears only where the player is eligible. The form shows his demand (minimum AAV, minimum years, WAR), a length picker from his minimum to 5 years, per-year salaries and bonus, with live AAV against the ask. A rejection keeps the form open: tries are unlimited. After signing, badge "Extended through YYYY".
  - `contract-overview: extension_eligible, has_extension, demand`
  - `POST /transactions/extend (400 codes: not_holder, not_mlb, not_final_year, not_fa_eligible, already_extended)`
  - `docs/contract_extensions_frontend_guide.md`
- [ ] **Arbitration explained** (`con-04`). For arbitration players: which arbitration year, and that the salary is set automatically when the season ends (40%, 60% or 80% of his market value). A projected figure needs backend request 2.
  - `contract-overview: contract_phase = arb_eligible, mlb_service_years`
- [ ] **Buyouts** (`con-05`). Buyout action showing the player's buyout price, with a confirmation step that states the cost before it is charged.
  - `POST /transactions/buyout`
  - `player demand type buyout`
- [ ] **Payroll outlook** (`con-06`). Obligations for the coming seasons, signed extensions included, so clubs see their commitments before they bid.
  - `GET /transactions/payroll-projection/{org}: per-season rows, is_extension`
- [ ] **Fallback players** (`con-07`). Badge players placed on a fallback deal at the free agency close and offer "Release at no cost before opening day". Until backend request 1 lands, read them from the fa_fallback transactions.
  - `POST /transactions/release → fa_fallback_released: true`
  - `transaction type fa_fallback`
- [ ] **Retired players** (`con-08`). Player pages show "Retired (year)"; retired players drop out of search and pickers. Needs backend request 3.
  - `Retirement reasons: age, unsigned, unsigned_marginal, never_signed, hs_undrafted, college_undrafted, intam_aged_out`
- [ ] **Releases and waivers** (`con-09`). The release confirmation explains waivers (one week, the club with the worst record among claimants wins) and what the club still owes if nobody claims him. A waiver wire page with claim and withdraw.
  - `docs/waiver_wire_frontend_guide.md`

## Free agency

Auctions run in rounds the commissioner advances by hand. Clubs must always know where an auction stands and what they can still do.

- [ ] **Auction stage stepper** (`fa-01`). Every auction shows four steps: Open, Listening, Final three, Signed. Next to it: the clubs bidding (names only, never amounts) and the club's own offer with its status.
  - `GET /fa-auction/board?league_year_id=&org_id=: phase, competing_teams, offer_count, my_offer`
- [ ] **Timing in rounds** (`fa-02`). Rounds are advanced by the commissioner, not by a clock. Say it plainly: "Once anyone bids, new clubs have until the next round to join." Show the round number and flag auctions where others bid and the club has not (last chance).
  - `Timestamp FreeAgencyRound`
  - `board phase and offer_count`
- [ ] **Live ask with history** (`fa-03`). Show the current ask. When it has fallen, show the starting ask struck through. After two rounds without an offer, note that the ask drops 10% at the next round (never below $1.6M).
  - `board: min_aav, initial_min_aav, ask_decay_steps, rounds_without_offer`
- [ ] **Free agent pool** (`fa-04`). Filters for position, age, WAR band, ask range, in an auction or not, and free agent tier; sort by WAR or ask; scouted ratings and scouting actions inline.
  - `GET /fa-auction/free-agent-pool (has_auction, fa_type, demand, auction)`
  - `docs/fog-of-war-frontend-guide.md`
- [ ] **Offer form that respects the rules** (`fa-05`). Length limited to the player's range, salaries prefilled at his ask, bonus field, live AAV and total, and checks before submit (AAV at least the ask, total at least the minimum total, level MLB or an affiliate).
  - `POST /fa-auction/{id}/offer`
  - `board: min_aav, min_total_value, min_years, max_years`
- [ ] **Commitment check before submit** (`fa-06`). "This offer holds $X (bonus plus first-season salary). You have $Y available." Disable submit when it does not fit; still show the server's message if it refuses.
  - `Signing budget minus held amounts (base-07)`
  - `400 message names cash and reserved amounts`
- [ ] **Improve-only after Open** (`fa-07`). After the Open stage the form only allows raising the yearly average, and says so.
- [ ] **Withdraw and re-offer** (`fa-08`). Withdraw is offered only during Open. A club that withdrew can offer again and is back in.
- [ ] **Offer status chips** (`fa-09`). One chip per status with a one-line meaning: active, outbid (missed the final three), withdrawn, won, lost, failed (won but could not be completed; the next offer signed).
  - `my_offer.status`
- [ ] **How this player chooses** (`fa-10`). Show how he weighs offers at his age (yearly salary versus total value: 30/70 at 28 or younger, 50/50 at 29–31, 70/30 at 32–33, 85/15 at 34+; bonus counts 5% extra) so clubs can shape their offer.
  - `board: age`
- [ ] **Round and close results** (`fa-11`). After each round and at the close: players the club signed, auctions it lost, and fallback players placed with it.
  - `Notifications`
  - `board my_offer status`
  - `transactions`
- [ ] **Market dashboard** (`fa-12`). Current price per WAR and how it was set (previous season's rate, the 15% cap), recent signings.
  - `GET /fa-auction/market-rate`
  - `GET /fa-auction/market-summary`
- [ ] **Direct signings** (`fa-13`). Players without an auction (tiers arb, pre_arb, milb_fa) get a Sign now action at the tier price. Hide it for players in an auction.
  - `POST /transactions/sign`
  - `pool fa_type, has_auction`
- [ ] **Every season's auctions** (`fa-14`). The board and pool include auctions opened in earlier seasons (players released in season). Do not filter them by league year on the client.
- [ ] **In-season free agency** (`fa-15`). The same screens work during the season, where a round is a game week.

## Draft

Contract changes from the season 2 change list, plus the signing negotiation.

- [ ] **Draft room data changes** (`dr-01`). Picks list is a bare array; draftees carry class year and draft rank; deadlines are UTC (ending in Z). Sort the pool by draft rank with class badges.
  - `GET /draft/picks/{org}`
  - `GET /draft/board`
  - `GET /draft/eligible`
  - `docs/INTERFACE_CHANGES_SEASON_2.md §2`
- [ ] **Server-run clock** (`dr-02`). Keep the countdown from pick_deadline_at and refresh on draft_pick_made; stop client-side auto-pick calls.
  - `pick_deadline_at`
  - `WebSocket draft_pick_made`
- [ ] **Signing negotiation** (`dr-03`). Show the player's ask, up to three offers with the result of each, and a clear "Refused, returned to school" end state.
  - `POST /draft/sign/{pick_id} → accepted, status, offers_remaining, ask_bonus, accept_probability`
- [ ] **Pick trades** (`dr-04`). Propose, accept and reject pick trades, with live updates.
  - `POST /draft/trade/propose|accept|reject`
  - `GET /draft/trade/proposals`
  - `WebSocket draft_trade_proposed, draft_trade_rejected`

## Recruiting and international

Twenty-week windows the admin advances by hand.

- [ ] **Recruiting window** (`am-01`). "Week X of 20", points left, commitments as they resolve, status labels and competitor logos.
  - `docs/recruiting_frontend_guide.md`
- [ ] **International signing window** (`am-02`). "Week X of 20", bonus pool left, auction stages per player, age-based level cap.
  - `docs/ifa_signing_frontend_guide.md`
- [ ] **College rosters after season end** (`am-03`). Expect incoming freshmen and walk-ons after the season ends, and graduating seniors gone. Make the turnover visible on program pages.

## Preseason and season wrap

The last offseason steps before opening day, and the season's history.

- [ ] **Training camp tab** (`pre-01`). One focus skill and an intensity per player, with the risk of each intensity; read-only once camp is applied; results without grades; a hint that it does little for players 29 and older.
  - `docs/training_camp_frontend_guide.md`
- [ ] **Ratings changed notice** (`pre-02`). Ratings change when the season ends (aging and development). The overall rating is a percentile within level and position, so do not present it as a trend line.
- [ ] **Awards** (`pre-03`). Awards on player pages and a season awards page.
  - `docs/awards_frontend_guide.md`

## Backend requests

Not available from the API yet. Raise these with the API team; the related interface items above note where a workaround exists.

- [ ] **1. Fallback flag on roster rows** (`gap-01`). Expose fa_fallback on roster and contract-overview rows so fallback players can be badged (con-07).
- [ ] **2. Projected renewal salaries** (`gap-02`). An estimate of next season's arbitration and pre-arbitration renewal salaries for the club's players (con-04).
- [ ] **3. Retired flag on players** (`gap-03`). A retired flag and year on /stats/player and roster or search results (con-08).
- [ ] **4. Held money per club** (`gap-04`). The total held by a club's active free agency offers, so the money panel need not add it up on the client (base-07).
- [ ] **5. Scouting costs endpoint** (`gap-05`). GET /scouting/config to replace the hard-coded scouting cost table.
- [ ] **6. Week field on offers** (`gap-06`). A season_week field to replace game_week_id taken from current_week_index on free agency offers.
