# FA Auction Phases — Frontend Validation & Error Handling Guide

This document covers every rule the frontend needs to enforce (or handle errors for) when an org owner interacts with the FA auction system. Use this to gate UI actions, disable buttons, and display the right error messages.

---

## Phase Overview

Every FA auction progresses through three phases, each lasting 1 game week:

```
Open ──> Listening ──> Finalize ──> Completed
```

Phase transitions are automatic (server-side, during week advancement). The frontend doesn't trigger them.

---

## What's Allowed in Each Phase

### Open Phase

| Action | Allowed? | Notes |
|--------|----------|-------|
| Submit new offer | Yes | Any org, first time |
| Update existing offer (raise AAV) | Yes | |
| Update existing offer (lower AAV) | Yes | Open is the only phase where you can lower |
| Withdraw offer | Yes | Open is the only phase where withdrawal is allowed |
| Change years/salary structure | Yes | Can freely restructure |

**Frontend:** Show "Make Offer" button for all orgs. Show "Update" and "Withdraw" for orgs with existing offers.

**Advancement rule:** Stays open indefinitely if 0 offers exist. Advances to Listening once at least 1 offer exists and the game week elapses.

### Listening Phase

| Action | Allowed? | Notes |
|--------|----------|-------|
| Submit new offer (never bid before) | **No** | Error: `"Listening phase: only existing bidders can update offers"` |
| Update existing offer (raise AAV) | Yes | AAV must be >= previous AAV |
| Update existing offer (lower AAV) | **No** | Error: `"Listening phase: new AAV must be >= old AAV"` |
| Withdraw offer | **No** | Error: `"Can only withdraw offers during 'open' phase"` |

**Frontend:**
- **Hide** the "Make Offer" button for orgs that didn't bid during Open
- **Hide** the "Withdraw" button
- Show "Increase Offer" for existing bidders
- Set the salary/bonus input minimums so that the computed AAV can't go below the current AAV

**At end of phase:** If more than 3 bidders, only the top 3 by attractiveness score survive. The rest are marked `outbid`. The frontend should update status badges accordingly when the board refreshes after a week advance.

### Finalize Phase

| Action | Allowed? | Notes |
|--------|----------|-------|
| Submit new offer | **No** | Error: `"Finalize phase: only existing bidders can update offers"` |
| Update offer (top 3, raise AAV) | Yes | Must be in top 3 (status = `active`) |
| Update offer (eliminated bidder) | **No** | Error: `"Your offer was eliminated — cannot update"` |
| Update offer (lower AAV) | **No** | Error: `"Finalize phase: new AAV must be >= old AAV"` |
| Withdraw offer | **No** | |

**Frontend:**
- Check `my_offer.status` — if `"outbid"`, disable all actions and show "Your offer was eliminated"
- If `my_offer.status` is `"active"`, show "Final Offer" or "Increase Offer" button
- Set AAV floor to current `my_offer.aav`

**At end of phase:** Winner is selected automatically. Auction becomes `completed`.

---

## Offer Validation Rules

These are enforced server-side but should be validated client-side for better UX:

### 1. Contract length
```
1 <= years <= 5
```
Error: `"Contract length must be 1-5 years"`

### 2. Salaries array matches years
```
salaries.length === years
```
Error: `"salaries length (X) must match years (Y)"`

### 3. Total value meets player minimum
```
sum(salaries) + bonus >= player.demand.min_total_value
```
Error: `"Total value (X) below player minimum (Y)"`

Note: The player's `min_total_value` is `min_aav * min_years`. You can also validate AAV directly:
```
(sum(salaries) + bonus) / years >= player.demand.min_aav
```

### 4. Bonus within budget
```
bonus <= available_budget
```
Error: `"Bonus (X) exceeds available budget (Y)"`

Check budget via `GET /api/v1/transactions/signing-budget/{orgId}?league_year_id={leagueYearId}`. Only the bonus is validated against cash — salary is future payroll and is not budget-checked at offer time.

### 5. AAV cannot decrease (Listening/Finalize only)
```
new_aav >= my_offer.aav  // when phase !== "open"
```
Errors:
- `"Listening phase: new AAV (X) must be >= old AAV (Y)"`
- `"Finalize phase: new AAV (X) must be >= old AAV (Y)"`

---

## How the Winner Is Chosen

Players evaluate offers using an **age-weighted attractiveness score** that blends AAV and effective total value. Bonus money receives a **5% premium** over salary — immediate cash is worth more to the player than future payments.

### Effective Total Value
```
effective_total = total_value + (bonus * 0.05)
```

A $10M bonus adds an extra $500K of perceived value compared to the same amount spread across salary years.

### Age Weights

| Player Age | AAV Weight | Total Value Weight | What the Player Prioritizes |
|-----------|-----------|-------------------|----------------------------|
| 28 and under | 30% | 70% | Long-term guaranteed money |
| 29-31 | 50% | 50% | Balanced |
| 32-33 | 70% | 30% | Per-year salary |
| 34+ | 85% | 15% | Almost pure AAV |

### What This Means for Offers

- **Young FAs:** Longer contracts with high total value win. Bonus helps but total years matter more.
- **Old FAs:** Short, high-AAV deals win. A 2yr/$14M deal beats a 4yr/$20M deal because $7M/yr > $5M/yr.
- **Bonus edge:** Between two otherwise identical offers, the one with a larger signing bonus wins because the effective total value is slightly higher.

### Strategy hints to show users

| Player Age | Hint Text |
|-----------|-----------|
| 28 and under | "This player values total guaranteed money — consider more years." |
| 29-31 | "This player weighs annual salary and total value equally." |
| 32-33 | "This player prioritizes annual salary over total years." |
| 34+ | "This player is focused on maximizing per-year pay." |
| Any | "Signing bonuses carry slightly more weight than salary — front-loading with bonus can give you an edge." |

---

## UI State Machine

For each auction entry on the board, determine the action state:

```js
function getAuctionAction(auction, myOrgId) {
  const phase = auction.phase;
  const myOffer = auction.my_offer;

  if (phase === 'completed' || phase === 'withdrawn') {
    return { action: 'none', label: 'Closed' };
  }

  if (!myOffer) {
    // No existing offer from this org
    if (phase === 'open') {
      return { action: 'new_offer', label: 'Make Offer' };
    }
    // Listening or Finalize — too late
    return { action: 'locked_out', label: 'Bidding Closed' };
  }

  // Has an existing offer
  if (myOffer.status === 'outbid') {
    return { action: 'eliminated', label: 'Eliminated' };
  }
  if (myOffer.status === 'withdrawn') {
    return { action: 'withdrawn', label: 'Withdrawn' };
  }

  // Active offer
  if (phase === 'open') {
    return { action: 'update_or_withdraw', label: 'Update Offer' };
  }
  // Listening or Finalize — can only raise
  return { action: 'raise_only', label: 'Increase Offer' };
}
```

### Button states by action

| Action | Offer Button | Withdraw Button | AAV Floor |
|--------|-------------|----------------|-----------|
| `new_offer` | "Make Offer" (enabled) | Hidden | `demand.min_aav` |
| `update_or_withdraw` | "Update Offer" (enabled) | "Withdraw" (enabled) | None (can lower in Open) |
| `raise_only` | "Increase Offer" (enabled) | Hidden | `my_offer.aav` |
| `locked_out` | Hidden or disabled | Hidden | N/A |
| `eliminated` | Disabled, show "Eliminated" badge | Hidden | N/A |
| `withdrawn` | Hidden | Hidden | N/A |
| `none` | Hidden | Hidden | N/A |

---

## Phase Badge Colors

```js
const phaseBadge = {
  open:      { color: 'green',  label: 'Open' },
  listening: { color: 'yellow', label: 'Listening' },
  finalize:  { color: 'red',    label: 'Final Round' },
  completed: { color: 'gray',   label: 'Signed' },
  withdrawn: { color: 'gray',   label: 'No Offers' },
};
```

---

## Offer Status Badges

For `my_offer.status`:

```js
const offerStatus = {
  active:    { color: 'green',  label: 'Active' },
  outbid:    { color: 'red',    label: 'Eliminated' },
  withdrawn: { color: 'gray',   label: 'Withdrawn' },
  won:       { color: 'green',  label: 'Won' },
  lost:      { color: 'red',    label: 'Lost' },
};
```

---

## Error Messages Reference

All errors come back as `{ "error": "message" }` with HTTP 400. These are user-readable — display them directly.

| Scenario | Error Message |
|----------|-------------|
| Auction not accepting offers | `"Auction is in phase 'X' — not accepting offers"` |
| New bidder in Listening | `"Listening phase: only existing bidders can update offers"` |
| New bidder in Finalize | `"Finalize phase: only existing bidders can update offers"` |
| Lowered AAV in Listening | `"Listening phase: new AAV (X) must be >= old AAV (Y)"` |
| Lowered AAV in Finalize | `"Finalize phase: new AAV (X) must be >= old AAV (Y)"` |
| Eliminated bidder updates | `"Your offer was eliminated — cannot update"` |
| Below minimum total | `"Total value (X) below player minimum (Y)"` |
| Bonus exceeds budget | `"Bonus (X) exceeds available budget (Y)"` |
| Wrong years | `"Contract length must be 1-5 years"` |
| Salaries mismatch | `"salaries length (X) must match years (Y)"` |
| Withdraw outside Open | `"Can only withdraw offers during 'open' phase"` |
| No offer to withdraw | `"No active offer found to withdraw"` |
| Auction not found | `"Auction X not found"` |

---

## Competitor Visibility Rules

| Data | Visible? |
|------|---------|
| Which teams are bidding | Yes — listed alphabetically in `competing_teams` |
| How many active offers | Yes — `offer_count` |
| Competitor offer amounts | **Never** — only your own `my_offer` shows values |
| Who won (after completion) | Yes — via completed auction detail |

The frontend should **never** attempt to display or sort by competitor offer values — they are intentionally hidden from the API response.

---

## Refresh Strategy

| Event | What to Refresh |
|-------|----------------|
| After submitting/updating an offer | Refresh the single auction entry or full board |
| After withdrawing | Refresh the single auction entry |
| After a game week advances | Refresh the entire board — phases may have changed, bids may have been eliminated |
| After scouting a player | Use the returned `player` object directly (no second API call needed) |
