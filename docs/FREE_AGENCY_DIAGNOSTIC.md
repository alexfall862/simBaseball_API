# Free Agency — diagnostic and options (2026-11-21)

## Status: decisions and what was built (2026-11-21)

| # | Decision | Built |
|---|---|---|
| D1 | Fix | A failed winning signing is marked `failed`, the next-best offer signs; if none can, the auction reopens; the close expires it with a fallback deal. |
| D2 | Address | Active offers reserve bonus + first-season salary against cash (`fa_reserve_offer_commitments`, `fa_commitment_includes_salary`). No payroll budget or luxury tax (declined for now). |
| D3 | Address | Rate = weighted median of AAV ÷ blended WAR; ±15 % per season from the previous rate (first season anchored to the $8M default); signings and extensions record blended WAR. |
| D4 | Fix | A re-offer after withdrawing is active again. |
| D5 | Fix | Board, pool, entry and close handle active auctions of every season; one active auction per player. |
| D6 | Notifications yes; schedule no | Bidder and fallback-club notifications on the MLB team. Rounds stay manually triggered. |
| D7 | Keep open | Offers stay accepted year-round so clubs can sign free agents in season. No change. |
| D8 | Address | Per-club tokens (`X-Org-Token`) on offer and withdraw, `ORG_TOKEN_MODE` off / warn (default) / enforce, admin endpoints to issue and list. |
| D10 | Fix | Auction outcome, starting ask, rounds without offer, ask drops, bidder count, winning score, close week; offer score and failure reason; `GET /admin/analytics/fa-outcomes`. |
| 4a | Falling asks yes | −10 % per round from the third round without an offer, floor $1.6M (`fa_ask_decay_pct`, `fa_ask_decay_after_rounds`). |
| 4a–4d | Others not now | Signings feed, anti-snipe, player preferences, payroll budget / luxury tax, qualifying offers, incumbent rights, richer contracts, non-roster invites. |

Migration: `migrations/season2_fa_durability.sql` (7th in the chain). Tests: `tests/test_fa_durability.py`.

Assessment of the free agency (FA) process before the first offseason runs on
the live league. Sources: the code (`services/fa_auction.py`,
`services/market_pricing.py`, `services/player_demands.py`,
`services/timestamp.py`, `services/transactions.py`), the rehearsal copy of the
live database after a full season 1 → 2 rollover, and rolled-back probes on
that copy. Nothing in this document has been changed in code.

## 1. How it works today

### Who becomes a free agent

| Path | When | What happens |
|---|---|---|
| Contract expires, 6+ MLB service years | End Season | Contract finishes; player enters an **auction** with a computed demand. |
| Contract expires, under 6 years | End Season | Pre-arb and arbitration players are renewed automatically; minor-league deals renew at $40k. |
| Released, clears waivers, 6+ years | In season | Enters an auction (stamped with that season). |
| Released, clears waivers, under 6 years | In season | Direct-sign tier: $800k / 1 year (MLB) or $40k (minors), first club to sign wins. |
| Orphan sweep | End Season | FA-eligible players with no contract and no auction are entered. |

### What a player asks for

- **Minimum AAV** = blended WAR (50/30/20 over three seasons, regressed below
  200 PA / 50 IP) × market rate ($ per WAR) × age multiplier (1.10 under 27,
  1.00 at 27–30, −5 %/yr at 31–33, −10 %/yr from 34, floor 0.30); at least $1.6M.
- **Years**: 3–5 at 28 or younger, 2–4 at 29–31, 1–3 at 32–33, 1–2 from 34.
- **Market rate**: AAV ÷ WAR over the last three seasons' signings with
  WAR ≥ 0.5, arbitration renewals excluded, extensions at 0.9 weight; fewer
  than 5 signings → blended toward $8M; clamped to $4M–$15M. All in `fa_config`.

### The auction

```
open ──(first offer, then next round)──► listening ──(next round)──► finalize ──(next round)──► signed
 any MLB club may offer        existing bidders may raise      top 3 kept, may raise        best score wins
```

- An offer: 1–5 years, AAV and total ≥ the demand, years within the player's
  range, level 4–9, signing bonus ≤ the club's signing budget (cash plus
  ledger minus bonuses not yet charged).
- Winner: age-weighted score of AAV and total value (young players favour
  total, older players favour AAV), bonus counted at +5 %, ties to the earliest offer.
- The board shows which clubs are bidding, never their amounts.
- **Clock:** in the offseason each `advance-fa-round` moves every auction one
  phase (manual, or the `fa_advance_round` scheduled job); in season,
  `advance_week` does it. So after the first offer on a player, rival clubs
  have **one round** to join, two more to raise.
- **Close:** `end-free-agency` runs every auction with offers to a winner and
  parks every player without one on a 1-year $40k **fallback deal** at AAA
  (level 4 for minor leaguers) with the club that has the fewest players at
  that level. The club may release him at no cost before week 1.

### This offseason in numbers (live copy)

| | |
|---|---|
| Players entering FA auctions | 152 (avg age 29, avg blended WAR 1.0) |
| Market rate the live league will use | **$8M / WAR** (season 1 has no qualifying signings: all 59 market rows are $0–$40k with 0 WAR) |
| Asks at $8M by WAR band | ≤0: $1.6M (23) · 0–1: $4.4M (62) · 1–2: $11.4M (43) · 2–4: $19.5M (19) · 4+: $38M (5, max $46M) |
| Whole class at its asks | $1.36B per year, ≈ $45M per club |
| Club revenue 2026 | ≈ $182M each (media $82M + performance $82M + playoffs) |
| Club salary 2026 | ≈ $207M each → the average club already loses ≈ $25M a year |
| 2027 salary already committed | $102M–$262M (avg $181M) |
| Cash on hand | $34M–$410M (avg $184M), none negative |

## 2. Durability findings

Ranked by what can go wrong in the first offseason. "Verified" means
reproduced on the rehearsal copy in a rolled-back transaction.

| # | Severity | Finding |
|---|---|---|
| D1 | **High** | **A failed signing jams the auction (verified).** If the winning club's bonus no longer fits its budget when the auction resolves, the signing raises, the auction stays in `finalize`, and every later round retries the same winner. `end-free-agency` does not resolve it either: the player ends with no contract, no fallback deal and an auction that never closes. The runner-up is never tried. |
| D2 | **High** | **No commitment control.** Bonuses are checked one offer at a time against cash, never reserved across a club's concurrent offers, so a club can bid on ten players and win more than it can pay — which is exactly what triggers D1. Salary is not checked at all, roster maximums only warn, and nothing stops a club from going cash-negative (the average club already runs −$25M a season). |
| D3 | **High** | **The market rate is fragile and can only rise.** (a) It is a ratio of sums with small WAR denominators: in the rehearsal, three test extensions at $40M for sub-1-WAR players pushed the rate from $8M to the $15M ceiling and every demand in the class up ~1.9×. (b) The rate uses single-season WAR while demands use blended WAR, so the two sides measure different things. (c) Every winning bid is ≥ the demand, and the demand is rate × WAR, so next year's rate ≥ this year's whenever clubs compete; with no payroll limit it ratchets to the ceiling within a few seasons. |
| D4 | Medium | **A re-offer after a withdrawal is silently ignored (verified).** The API answers "updated" but the offer keeps status `withdrawn`, so it is never considered. One-line fix. |
| D5 | Medium | **Auctions from an earlier season are invisible and never closed** (plan item A5, partial). The board, pool and `end-free-agency` only look at the current league year. Season 1 has none, but every player released and unclaimed during season 2 creates one; at the next offseason, those without offers stay open forever, off the board, with no fallback. |
| D6 | Medium | **Pacing and visibility.** The clock is whoever clicks "advance round". One round is the entire window for rival clubs after a first bid. No notifications exist for being outbid, cut to the top 3, winning, losing or a player expiring (the `notifications` table and websocket exist but FA writes nothing). With 29 human owners this decides who gets players. |
| D7 | Low–Med | **No window gate (verified).** Offers are accepted at any time, including while FA is locked; in the offseason, bids placed before `start-free-agency` count. The client also supplies `current_week`. Decide whether offseason bidding should open only with the FA window. |
| D8 | Security | **Any caller can bid or withdraw for any club** by sending its `org_id` (known open item E1). In a live, competitive market between human owners this is the most exploitable gap. |
| D9 | Low | **Fallback volume.** In the rehearsal (few scripted bids) 147 of 152 players expired onto fallback deals, about 5 per club at AAA, assigned by roster count rather than choice. Clubs must release unwanted ones before week 1 to avoid paying them. Communicate it, or make fallback opt-in. |
| D10 | Data | **No calibration data is captured** (plan item B3 not built): no auction outcome, no phase log, no stored scores, no demand-vs-price fields, no FA outcomes report. The first offseason would leave nothing to tune season 2 with. |

## 3. Recommended before FA opens on the live league

Small, mechanical, no design change:

1. **D1** — on a failed signing, mark that offer `failed`, award the next-best
   active offer; if none can sign, expire the auction with a fallback deal.
   `end-free-agency` must never leave an auction active.
2. **D4** — reset the status to `active` when a club re-offers in the open phase.
3. **D5** — board, pool and close select active auctions regardless of year
   (or move them to the new year at `start-free-agency`).
4. **D10** — record outcome, closing phase, bidder count, demand at entry and
   winning score per auction; an admin FA outcomes report.
5. **Pacing** — schedule `fa_advance_round` on a fixed, published cadence
   (e.g. every 24 h) and tell owners how many rounds FA lasts.

Need a decision:

6. **D2** — reserve each offer's bonus against the budget while it is active
   (recommended), and decide whether a salary or payroll limit exists (see 4c).
7. **D3** — rate guard. Options, combinable: use the same blended WAR on both
   sides; median of per-signing AAV/WAR instead of a ratio of sums; ignore
   signings below 1 WAR; cap the year-over-year change (e.g. ±15 %); exclude
   extensions. Recommended minimum: same WAR on both sides + median + ±15 % cap.
8. **D7** — gate offseason offers to the FA window.
9. **D8** — at least a per-club token on the FA write endpoints if full auth (E1) is not ready.

## 4. Ways to extend free agency

### 4a. Make the market work better (durability-flavoured)

- **Demand decay.** A player without an offer lowers his ask each round (e.g.
  −10 % per round after round 2, never below the floor). Clears the market,
  cuts fallback volume, and creates a real "wait for a bargain" strategy.
- **Notifications and an FA feed.** Outbid, cut to top 3, won, lost, player
  signed elsewhere, player's ask dropped — through the existing notifications
  table and websocket. Plus a public signings ticker with live $/WAR.
- **Anti-snipe.** A new leading offer in `finalize` extends that auction by one round (at most once or twice).
- **Scheduled close.** FA runs a fixed number of rounds (e.g. 7); the schedule
  is visible to owners and enforced by the job scheduler.

### 4b. Give players preferences beyond money

Multiply the offer score by a few published factors so money is not the only lever:

- **Contender**: last season's win % or playoff result of the bidding club.
- **Playing time**: is there an open MLB starting role at his position on the bidding club?
- **Loyalty / hometown**: small bonus for his previous club.
- **Level**: an offer to an MLB roster beats a minor-league assignment.

Each factor small (±5–10 %) so money still dominates; show the factors on the auction card.

### 4c. League economics

- **Payroll budget per club** derived from revenue, with either a hard limit on
  new commitments or a **luxury tax** above a threshold (ledger entry, revenue
  shared to low-payroll clubs). This is the brake D3 is missing and protects
  clubs already losing money.
- **Revenue-anchored $/WAR**: set the rate from league revenue (e.g. a share of
  average revenue ÷ wins above replacement) instead of last year's prices.

### 4d. Contract and rights mechanics

- **Qualifying offer**: before FA, the former club may make a one-year offer at
  a league-set amount; if the player signs elsewhere, the former club receives
  a draft pick from the signing club (draft pick tables and pick trades already exist).
- **Incumbent rights**: an exclusive first round for the former club, or a
  right to match the winning offer.
- **Richer contracts**: player or club options, opt-outs, deferred money.
- **Non-roster invites** instead of forced fallback deals: unsigned players
  accept minor-league invites from clubs that offer them.

### Suggested order

Before FA: section 3 items 1–5, plus decisions 6–9. First in-season update:
notifications, demand decay, scheduled close. Season-2 design work: player
preferences, payroll budget or luxury tax, qualifying offers.
