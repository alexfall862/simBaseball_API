# IFA Signing Period — Frontend Guide

This document covers every endpoint, response shape, and workflow the frontend needs to implement the International Free Agent (IFA) signing period page: browsing eligible international prospects, managing bonus pool budgets, placing bids via per-player auctions, and tracking the 20-week signing window.

All endpoints are under `/api/v1`. All IFA endpoints are prefixed `/ifa/`.

---

## Table of Contents

1. [Concepts](#concepts)
2. [IFA State](#ifa-state)
3. [Bonus Pool Status](#bonus-pool-status)
4. [Eligible Players](#eligible-players)
5. [IFA Board (Main View)](#ifa-board-main-view)
6. [Auction Detail](#auction-detail)
7. [Starting an Auction](#starting-an-auction)
8. [Making an Offer](#making-an-offer)
9. [Withdrawing an Offer](#withdrawing-an-offer)
10. [Org's Active Offers](#orgs-active-offers)
11. [Scouting Integration](#scouting-integration)
12. [Admin: Advance Week](#admin-advance-week)
13. [Age-Based Level Restriction](#age-based-level-restriction)
14. [Endpoint Reference](#endpoint-reference)
15. [Full Workflow: IFA Lifecycle](#full-workflow-ifa-lifecycle)

---

## Concepts

### Who Can Sign

Only **MLB orgs** (org IDs 1-30) participate in IFA signing. College orgs cannot sign international players — those players are exclusive to the IFA system.

### International Amateur Pool

International amateur players live in org 339 (INTAM). Players age 16 and older become IFA-eligible. They do **not** enter the MLB draft — IFA signing is their only path to a pro organization.

### Bonus Pool Budget

Each MLB org receives a bonus pool allocation at the start of the IFA window, sized by **inverse standings** (worse teams get larger pools). The pool constrains total signing bonuses an org can commit during the window. Active (unsettled) offers count against the pool as committed funds.

Pool formula (default config):
- Worst team (rank 1): ~$7,500,000
- Best team (rank 30): ~$3,333,333
- Linear interpolation between

### Star Ratings & Slot Values

Every IFA-eligible player receives a 1-5 star rating based on a composite score of their attributes and potentials (same system as college recruiting). Star ratings determine the **slot value** — the minimum signing bonus a player will accept.

| Stars | Percentile | Default Slot Value |
|-------|-----------|-------------------|
| 5 | Top 1% | $5,000,000 |
| 4 | Next 2% | $2,500,000 |
| 3 | Next 7% | $1,000,000 |
| 2 | Next 30% | $300,000 |
| 1 | Bottom 60% | $100,000 |

Star ratings persist on the player as `recruit_stars`. Slot values are configurable via the `ifa_config` table.

### 3-Phase Auction

When any org expresses interest in an IFA player, a per-player auction begins. Each auction runs independently through three phases:

| Phase | Duration | Rules |
|-------|----------|-------|
| **Open** | 3 IFA weeks (stays open indefinitely with 0 offers) | Any MLB org can submit an offer |
| **Listening** | 3 IFA weeks | Only existing bidders can update; cannot decrease bonus |
| **Finalize** | 3 IFA weeks | Only top 3 bidders remain; cannot decrease bonus; winner signs at end |

Phase durations are configurable (default: 3 IFA weeks each). Multiple auctions can run concurrently at different phases.

**Key difference from Free Agency auctions:** IFA offers are **bonus-only** — there are no salary/years/level negotiations. Contract terms are fixed (5 years, $40k/year, level 4). The only variable is how much signing bonus you offer.

### IFA Window Lifecycle

The IFA window runs for 20 weeks on its own timeline, advanced by admin action (not tied to game simulation). This is the same pattern as college recruiting.

```
Week 0 (pending)  →  Rankings computed, pools allocated, status becomes 'active'
Weeks 1-19        →  Orgs start auctions, submit offers; phases advance each week
Week 20           →  Final phase advance, remaining auctions expire
Week 21+          →  Status 'complete', no more activity
```

Unsigned players remain in the INTAM pool for next year's IFA window.

### Fog of War

IFA players can be scouted through the existing INTAM scouting pool (`/scouting/intam-pool`). Without scouting, attributes are fuzzed via the standard fog-of-war system.

**Scouting actions available for IFA players:**

| Action | Cost | Effect |
|--------|------|--------|
| `draft_attrs_fuzzed` | 10 pts | Reveals narrowed attribute ranges |
| `draft_attrs_precise` | 20 pts | Reveals true 20-80 numeric attributes (requires `draft_attrs_fuzzed` first) |
| `draft_potential_precise` | 15 pts | Reveals true potential letter grades |

### Age-Based Level Cap

Players age 17 and younger **cannot be placed above level 4** by any mechanism (promotion, draft signing, or IFA signing). The IFA system signs players at level 4 by default, so this is automatically respected. However, if your UI shows promotion options for young IFA signees, disable any level > 4 for players 17 or under.

---

## IFA State

Check the current phase before rendering any IFA UI.

### Loading State

```
GET /api/v1/ifa/state?league_year_id={leagueYearId}
```

### Response

```json
{
  "league_year_id": 5,
  "current_week": 8,
  "total_weeks": 20,
  "status": "active"
}
```

| `status` | UI Behavior |
|----------|-------------|
| `"pending"` | Show "IFA signing window has not started yet" |
| `"active"` | Full IFA UI — board, eligible players, offer submission |
| `"complete"` | Read-only — show completed signings, disable offer buttons |

---

## Bonus Pool Status

Shows the org's budget breakdown.

### Loading Pool

```
GET /api/v1/ifa/pool/{orgId}?league_year_id={leagueYearId}
```

### Response

```json
{
  "org_id": 1,
  "total_pool": 6500000.00,
  "spent": 2500000.00,
  "committed": 1000000.00,
  "remaining": 3000000.00,
  "standing_rank": 8
}
```

| Field | Description |
|-------|-------------|
| `total_pool` | Total bonus pool allocation for this org |
| `spent` | Bonuses already paid on completed signings |
| `committed` | Sum of active (unsettled) offers — reserved but not yet spent |
| `remaining` | `total_pool - spent - committed` — what's actually available for new offers |
| `standing_rank` | Inverse standings rank (1 = worst team = largest pool) |

### Suggested Pool Display

```
┌─────────────────────────────────────────────────┐
│  IFA Bonus Pool           Standing Rank: #8     │
│                                                  │
│  Total Pool:    $6,500,000                       │
│  ████████████████████░░░░░░░░  46% remaining     │
│  Spent:         $2,500,000  (signed)             │
│  Committed:     $1,000,000  (active offers)      │
│  ─────────────────────────────                   │
│  Available:     $3,000,000                       │
└─────────────────────────────────────────────────┘
```

Display the pool prominently at the top of the IFA page. Update it after every offer submission or signing.

---

## Eligible Players

Browse international prospects available for signing. This lists all INTAM players age 16+ who haven't already been signed this year.

### Loading Eligible Players

```
GET /api/v1/ifa/eligible?league_year_id={leagueYearId}
```

### Response

```json
[
  {
    "player_id": 5432,
    "firstName": "Carlos",
    "lastName": "Martinez",
    "age": 16,
    "ptype": "Pitcher",
    "area": "Dominican Republic",
    "star_rating": 5,
    "slot_value": 5000000.00
  },
  {
    "player_id": 5433,
    "firstName": "Kenji",
    "lastName": "Tanaka",
    "age": 17,
    "ptype": "Position",
    "area": "Japan",
    "star_rating": 3,
    "slot_value": 1000000.00
  }
]
```

**Notes:**
- Sorted by `star_rating` descending, then `lastName` alphabetically.
- `slot_value` is the minimum bonus this player will accept.
- Players with an active auction (open/listening/finalize) still appear here. Cross-reference with the board to show auction status inline.
- Players with a `completed` auction for this year are excluded.

---

## IFA Board (Main View)

The primary IFA interface combining state, pool, and all active auctions.

### Loading the Board

```
GET /api/v1/ifa/board?league_year_id={leagueYearId}&org_id={orgId}
```

**Required params:** `league_year_id`. **Optional:** `org_id` (enables pool status and "my offer" visibility).

### Response

```json
{
  "state": {
    "league_year_id": 5,
    "current_week": 8,
    "total_weeks": 20,
    "status": "active"
  },
  "pool": {
    "org_id": 1,
    "total_pool": 6500000.00,
    "spent": 2500000.00,
    "committed": 1000000.00,
    "remaining": 3000000.00,
    "standing_rank": 8
  },
  "auctions": [
    {
      "auction_id": 101,
      "player_id": 5432,
      "firstName": "Carlos",
      "lastName": "Martinez",
      "age": 16,
      "ptype": "Pitcher",
      "area": "Dominican Republic",
      "phase": "listening",
      "star_rating": 5,
      "slot_value": 5000000.00,
      "entered_week": 2,
      "active_offers": 3,
      "competitors": ["BOS", "LAD", "NYY"],
      "my_offer": {
        "bonus": 5500000.00
      }
    },
    {
      "auction_id": 102,
      "player_id": 5433,
      "firstName": "Kenji",
      "lastName": "Tanaka",
      "age": 17,
      "ptype": "Position",
      "area": "Japan",
      "phase": "open",
      "star_rating": 3,
      "slot_value": 1000000.00,
      "entered_week": 5,
      "active_offers": 1,
      "competitors": [],
      "my_offer": null
    }
  ]
}
```

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | `"open"`, `"listening"`, or `"finalize"` |
| `slot_value` | float | Minimum acceptable bonus (based on star rating) |
| `active_offers` | int | Number of active bids on this player |
| `competitors` | string[] | Alphabetically sorted abbreviations of competing orgs (excludes viewer) |
| `my_offer` | object\|null | `{bonus}` if the viewer has an active offer. `null` otherwise. |
| `entered_week` | int | IFA week the auction started |

**Key display rules:**
- `competitors` is alphabetically sorted — do NOT reorder by bid amount (that info is hidden).
- Offer amounts from competitors are never revealed. Only the count and team names are shown.
- The viewer's own offer (`my_offer`) shows the exact bonus amount.

### Phase Badge Colors

```js
function getPhaseColor(phase) {
  if (phase === 'open')     return 'green';
  if (phase === 'listening') return 'yellow';
  if (phase === 'finalize')  return 'red';
  return 'gray';
}
```

### Suggested Board Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  IFA Signing Period  ·  Week 8 of 20                    Pool: $3.0M rem │
│                                                                          │
│  ACTIVE AUCTIONS                                                         │
├──────┬─────────┬────┬─────┬──────┬────────┬───────┬──────────┬──────────┤
│Stars │ Name    │Age │Type │ Slot │ Phase  │Offers │Competing │ My Offer │
├──────┼─────────┼────┼─────┼──────┼────────┼───────┼──────────┼──────────┤
│ 5*   │Martinez │ 16 │  P  │$5.0M │Listen. │  3    │BOS,LAD,NY│ $5.5M   │
│ 3*   │Tanaka   │ 17 │ Pos │$1.0M │ Open   │  1    │          │   —     │
└──────┴─────────┴────┴─────┴──────┴────────┴───────┴──────────┴──────────┘

  AVAILABLE PROSPECTS (no auction yet)
├──────┬─────────┬────┬─────┬──────┬──────────────────────────────────────┤
│Stars │ Name    │Age │Type │ Slot │                              Action  │
├──────┼─────────┼────┼─────┼──────┼──────────────────────────────────────┤
│ 4*   │Suzuki   │ 16 │ Pos │$2.5M │                       [Start Auction]│
│ 2*   │Perez    │ 18 │  P  │$300K │                       [Start Auction]│
└──────┴─────────┴────┴─────┴──────┴──────────────────────────────────────┘
```

- **Top section**: Active auctions sorted by star rating descending.
- **Bottom section**: Eligible players with no active auction. Show "Start Auction" button.
- Clicking a row in the top section opens the [Auction Detail](#auction-detail) modal.
- **Phase column**: Colored badge (green=Open, yellow=Listening, red=Finalize).
- **My Offer column**: Show bonus amount if active offer, "—" if none. Show "[Offer]" button if no offer, "[Update]" if has offer.

---

## Auction Detail

Shown when clicking an auction row on the board.

### Loading Detail

```
GET /api/v1/ifa/auction/{auctionId}?org_id={orgId}
```

`org_id` is optional but enables "my offer" visibility.

### Response

```json
{
  "auction_id": 101,
  "player_id": 5432,
  "firstName": "Carlos",
  "lastName": "Martinez",
  "age": 16,
  "ptype": "Pitcher",
  "area": "Dominican Republic",
  "phase": "listening",
  "star_rating": 5,
  "slot_value": 5000000.00,
  "entered_week": 2,
  "winning_offer_id": null,
  "offers": [
    {
      "offer_id": 201,
      "org_abbrev": "NYY",
      "status": "active",
      "submitted_week": 2,
      "bonus": 5500000.00,
      "is_mine": true
    },
    {
      "offer_id": 202,
      "org_abbrev": "BOS",
      "status": "active",
      "submitted_week": 3,
      "is_mine": false
    },
    {
      "offer_id": 203,
      "org_abbrev": "LAD",
      "status": "active",
      "submitted_week": 2,
      "is_mine": false
    }
  ]
}
```

**Visibility rules:**
- `bonus` is only included on offers where `is_mine` is `true`. Competitor bonus amounts are hidden.
- `status` for all offers is visible (active, outbid, withdrawn, won, lost).
- `winning_offer_id` is populated only when the auction phase is `"completed"`.

### Suggested Modal Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Carlos Martinez  ·  16  ·  Pitcher  ·  Dominican Republic   │
│  5 Stars  ·  Slot Value: $5,000,000                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  AUCTION STATUS: Listening  ·  Entered Week 2                 │
│                                                               │
│  OFFERS (3 active)                                            │
│  ┌────────┬──────────┬───────────┬──────────┐                │
│  │  Org   │  Status  │  Week     │  Bonus   │                │
│  ├────────┼──────────┼───────────┼──────────┤                │
│  │  NYY   │  Active  │  Week 2   │ $5.5M    │  ← your offer │
│  │  BOS   │  Active  │  Week 3   │  hidden  │                │
│  │  LAD   │  Active  │  Week 2   │  hidden  │                │
│  └────────┴──────────┴───────────┴──────────┘                │
│                                                               │
│  [Update Offer]    [Withdraw] (open phase only)               │
└──────────────────────────────────────────────────────────────┘
```

- **"Update Offer"** opens the offer form pre-filled with current bonus.
- **"Withdraw"** only shown and enabled if `phase === "open"`.
- If the viewer has no offer, show **"[Make Offer]"** instead.

---

## Starting an Auction

Any MLB org can start an auction for an eligible player who doesn't have one yet.

### Request

```
POST /api/v1/ifa/auction/start
```

```json
{
  "player_id": 5432,
  "league_year_id": 5
}
```

### Response (success)

```json
{
  "auction_id": 101,
  "player_id": 5432,
  "player_name": "Carlos Martinez",
  "phase": "open",
  "star_rating": 5,
  "slot_value": 5000000.00,
  "age": 16
}
```

### Error Responses (400)

```json
{ "error": "IFA signing window is not active" }
{ "error": "Player not found in INTAM pool" }
{ "error": "Player age 15 below IFA minimum 16" }
{ "error": "Player already has active auction (id=101)" }
```

**After starting:** The auction opens with phase `"open"`. The org that started it does NOT automatically have an offer — they still need to submit one via the offer endpoint.

---

## Making an Offer

### Submit or Update Offer

```
POST /api/v1/ifa/auction/{auctionId}/offer
```

```json
{
  "org_id": 1,
  "bonus": 5500000,
  "league_year_id": 5,
  "executed_by": "user"
}
```

**Important:** The only user input is `bonus`. Contract terms (years, salary, level) are fixed by config and not part of the offer.

### Response (success — new offer)

```json
{
  "offer_id": 201,
  "is_update": false,
  "bonus": 5500000.00,
  "phase": "open"
}
```

### Response (success — updated offer)

```json
{
  "offer_id": 201,
  "is_update": true,
  "bonus": 6000000.00,
  "phase": "listening"
}
```

### Error Responses (400)

```json
{ "error": "Only MLB organizations (1-30) can submit IFA offers" }
{ "error": "Auction is in phase 'completed', cannot accept offers" }
{ "error": "Bonus 4000000 below slot value 5000000" }
{ "error": "Listening phase: only orgs with existing active offers can update" }
{ "error": "Listening phase: cannot decrease bonus" }
{ "error": "Finalize phase: only top bidders with active offers can update" }
{ "error": "Bonus 8000000 exceeds available pool (3000000.00 remaining)" }
{ "error": "No IFA bonus pool found for org 1" }
```

### Offer Form

The offer form is simpler than Free Agency — only one field:

```
┌──────────────────────────────────────────────────┐
│  Offer for Carlos Martinez (5*)                   │
│                                                    │
│  Slot Value (minimum):  $5,000,000                 │
│                                                    │
│  Your Bonus Offer:  [$__________]                  │
│                                                    │
│  Pool Remaining:    $3,000,000                     │
│                                                    │
│  Contract Terms (fixed):                           │
│    · 5 years at $40,000/year                       │
│    · Assigned to Level 4 (Low Minors)              │
│                                                    │
│  [Submit Offer]                                    │
└──────────────────────────────────────────────────┘
```

### Client-Side Validation

Before submitting:
1. **Bonus >= slot_value**: `bonus >= auction.slot_value`
2. **Bonus <= remaining pool**: `bonus <= pool.remaining` (for new offers) or `bonus - my_current_bonus <= pool.remaining` (for updates)
3. **Bonus not decreased** (listening/finalize): `new_bonus >= my_offer.bonus`

Format the bonus input as a currency field. Show "Minimum: $X" hint based on slot value.

---

## Withdrawing an Offer

Only allowed during the **Open** phase.

```
DELETE /api/v1/ifa/auction/{auctionId}/offer/{orgId}
```

### Response (success)

```json
{ "withdrawn": true }
```

### Error Responses (400)

```json
{ "error": "Offers can only be withdrawn during open phase" }
{ "error": "No active offer found to withdraw" }
```

After withdrawal, the org's committed pool amount is freed. Refresh the pool status display.

---

## Org's Active Offers

View all offers the org has placed across all auctions this year.

### Loading Offers

```
GET /api/v1/ifa/offers/{orgId}?league_year_id={leagueYearId}
```

### Response

```json
[
  {
    "offer_id": 201,
    "auction_id": 101,
    "player_id": 5432,
    "firstName": "Carlos",
    "lastName": "Martinez",
    "age": 16,
    "ptype": "Pitcher",
    "bonus": 5500000.00,
    "status": "active",
    "auction_phase": "listening",
    "star_rating": 5,
    "slot_value": 5000000.00
  },
  {
    "offer_id": 205,
    "auction_id": 103,
    "player_id": 5440,
    "firstName": "Miguel",
    "lastName": "Perez",
    "age": 17,
    "ptype": "Position",
    "bonus": 300000.00,
    "status": "won",
    "auction_phase": "completed",
    "star_rating": 2,
    "slot_value": 300000.00
  }
]
```

### Suggested "My Offers" Panel

```
┌───────────────────────────────────────────────────────────────┐
│  MY IFA OFFERS                                                │
├──────┬─────────┬──────┬───────────┬──────────┬───────────────┤
│Stars │ Player  │Bonus │  Status   │ Auction  │    Action     │
├──────┼─────────┼──────┼───────────┼──────────┼───────────────┤
│ 5*   │Martinez │$5.5M │  Active   │Listening │   [Update]    │
│ 2*   │Perez    │$300K │   Won     │Completed │   Signed!     │
│ 3*   │Tanaka   │$1.2M │  Outbid   │Finalize  │      —        │
└──────┴─────────┴──────┴───────────┴──────────┴───────────────┘
```

### Offer Status Colors

```js
function getOfferStatusColor(status) {
  if (status === 'active')    return 'green';
  if (status === 'won')       return 'blue';
  if (status === 'outbid')    return 'orange';
  if (status === 'lost')      return 'red';
  if (status === 'withdrawn') return 'gray';
  return 'gray';
}
```

---

## Scouting Integration

IFA players are scouted through the existing INTAM scouting pool. The scouting page at `/scouting/intam-pool` now shows players age 16+ (previously 18+).

### Scouting an IFA Player

Use the existing scouting endpoints:

```
POST /api/v1/scouting/scout
```

```json
{
  "org_id": 1,
  "league_year_id": 5,
  "target_player_id": 5432,
  "action_type": "draft_attrs_fuzzed"
}
```

### Scouting Actions for IFA Players

| Action | Cost | Prerequisite | What It Reveals |
|--------|------|-------------|-----------------|
| `draft_attrs_fuzzed` | 10 pts | None | Narrowed attribute ranges |
| `draft_attrs_precise` | 20 pts | `draft_attrs_fuzzed` | True 20-80 numeric attributes |
| `draft_potential_precise` | 15 pts | None | True potential letter grades |

### Linking Scouting to the IFA Page

Consider adding a "Scout" button on the IFA board or auction detail modal that links to the INTAM scouting pool filtered to that player. Alternatively, embed a lightweight scouting action inline (same pattern as the FA page's inline scouting).

---

## Admin: Advance Week

The IFA window advances independently from game simulation, triggered by admin action.

### Advance One Week

```
POST /api/v1/ifa/advance-week
```

```json
{ "league_year_id": 5 }
```

### Response (Week 0 → 1: Initialization)

```json
{
  "league_year_id": 5,
  "previous_week": 0,
  "new_week": 1,
  "status": "active",
  "players_ranked": 342,
  "pools_allocated": 30
}
```

### Response (Weeks 1-19: Normal Advance)

```json
{
  "league_year_id": 5,
  "previous_week": 8,
  "new_week": 9,
  "status": "active",
  "phase_transitions": {
    "open_to_listening": 2,
    "listening_to_finalize": 1,
    "finalize_to_completed": 1,
    "still_open": 3
  }
}
```

### Response (Week 20: Final / Close)

```json
{
  "league_year_id": 5,
  "previous_week": 19,
  "new_week": 20,
  "status": "complete",
  "phase_transitions": {
    "open_to_listening": 0,
    "listening_to_finalize": 0,
    "finalize_to_completed": 2,
    "still_open": 0,
    "expired": 4
  }
}
```

### Error Responses (400)

```json
{ "error": "IFA signing window already complete" }
```

### Admin UI Suggestion

Add an "IFA Signing" section to the admin panel:

```
┌────────────────────────────────────────────────────┐
│  IFA Signing Period                                 │
│                                                      │
│  Status: Active   ·   Week 8 of 20                   │
│                                                      │
│  Active auctions: 7                                  │
│  Completed signings: 12                              │
│  Expired (unsigned): 0                               │
│                                                      │
│  [Advance to Week 9]                                 │
└────────────────────────────────────────────────────┘
```

After advancing, display the `phase_transitions` summary so the admin can see how many auctions moved between phases and how many signings completed.

---

## Age-Based Level Restriction

Players age 17 and younger cannot be promoted above level 4, regardless of how they were acquired. This is enforced server-side in three places:

1. **Promotions** — `promote_player()` raises a `ValueError` if target level > 4 and player age <= 17
2. **Draft signing** — `sign_pick()` caps the signing level at `min(DRAFT_TARGET_LEVEL, 4)` for players 17 and under
3. **Draft export** — `export_draft()` applies the same cap during bulk finalization

**Frontend implications:**
- When rendering promotion buttons/dropdowns for a player, check the player's age. If <= 17, disable or hide level options above 4.
- The API returns a clear error message if attempted: `"Players age 17 and younger cannot be promoted above level 4 (player age: 16, target level: 5)"`
- IFA signings are already at level 4 by default, so no special handling needed there.

---

## Endpoint Reference

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/ifa/state?league_year_id` | Any | Current IFA window state |
| GET | `/ifa/board?league_year_id&org_id` | Any | Full board: state + pool + active auctions |
| GET | `/ifa/pool/{orgId}?league_year_id` | Any | Org's bonus pool status |
| GET | `/ifa/offers/{orgId}?league_year_id` | Any | Org's active IFA offers |
| GET | `/ifa/auction/{auctionId}?org_id` | Any | Single auction detail |
| GET | `/ifa/eligible?league_year_id` | Any | Eligible INTAM players list |
| POST | `/ifa/auction/start` | MLB org | Start auction for a player |
| POST | `/ifa/auction/{auctionId}/offer` | MLB org | Submit or update offer |
| DELETE | `/ifa/auction/{auctionId}/offer/{orgId}` | MLB org | Withdraw offer (open phase only) |
| POST | `/ifa/advance-week` | Admin | Advance IFA window by one week |

All POST/DELETE endpoints return `400` with `{"error": "..."}` on validation failure.

---

## Full Workflow: IFA Lifecycle

### 1. Admin Opens the Window

Admin calls `POST /ifa/advance-week` for the first time (week 0 → 1):
- Star rankings computed for all INTAM players age 16+
- Bonus pools allocated based on inverse standings
- Status changes to `"active"`

### 2. Orgs Browse Prospects

- Load the board: `GET /ifa/board?league_year_id=5&org_id=1`
- Check pool budget in the response's `pool` object
- Browse eligible players (bottom section — no auction yet)
- Optionally scout players via `/scouting/intam-pool` to reveal precise attributes

### 3. Org Starts an Auction

- Click "Start Auction" on an eligible player
- `POST /ifa/auction/start` with `{player_id, league_year_id}`
- Auction opens in `"open"` phase

### 4. Orgs Submit Offers

- `POST /ifa/auction/{id}/offer` with `{org_id, bonus, league_year_id}`
- Bonus must meet slot value and fit within remaining pool
- Multiple orgs can bid on the same player

### 5. Admin Advances Weeks

Each `POST /ifa/advance-week` call:
- Increments the IFA week counter
- Processes auction phase transitions:
  - Open auctions with offers → Listening (after 3 weeks)
  - Listening → Finalize (eliminates non-top-3 offers)
  - Finalize → Completed (winner signs, contract created)

### 6. Orgs Update Offers in Later Phases

- **Listening**: Only existing bidders can update. Bonus cannot decrease.
- **Finalize**: Only top 3 bidders remain. Bonus cannot decrease. Last chance to outbid.

### 7. Signing Completes

When an auction completes (finalize phase ends):
- Winner's bonus is deducted from their pool (`spent` increases)
- Player's INTAM contract is terminated
- New contract created: 5 years, $40k/year, level 4, bonus = winning bid
- Player is now part of the signing org's minor league system

### 8. Window Closes (Week 20)

- All finalize-phase auctions complete normally (winners sign)
- All other active auctions expire (unsigned)
- Status changes to `"complete"`
- Unsigned players remain in INTAM for next year's window

### 9. UI State After Completion

- Board shows completed signings (read-only)
- All offer/auction buttons disabled
- Pool shows final spent/remaining breakdown
