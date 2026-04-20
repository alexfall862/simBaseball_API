# Scouting Department Expansion — Frontend Integration Spec

## Overview

MLB organizations (org_id 1-30) can spend cash to expand their scouting department, gaining additional scouting points beyond the base 2000. Each successive tier yields diminishing returns, creating a strategic tradeoff between scouting investment and payroll spending.

College orgs are **not eligible** — they stay at the flat 2000 base.

### Cash Requirement

Teams must have a **positive cash balance sufficient to cover the purchase**. The system checks the org's net cash position (seed capital + all ledger entries) and rejects the purchase if the org can't afford it. Teams that are cash-negative or too close to zero cannot expand their scouting department — this creates additional financial pressure to maintain liquidity.

---

## Endpoints

All endpoints are under `/api/v1/scouting/department/`.

### 1. GET `/scouting/department/<org_id>?league_year_id=<id>`

Returns full department status, purchase history, and tier schedule.

**Response (MLB org, eligible):**
```json
{
  "eligible": true,
  "base_budget": 2000,
  "bonus_points": 3500,
  "total_budget": 5500,
  "current_tier": 2,
  "max_tier": 11,
  "next_tier": {
    "tier": 3,
    "cost": 3000000,
    "points_gained": 1500
  },
  "purchases": [
    {
      "id": 1,
      "tier": 1,
      "bonus_points": 2000,
      "cash_cost": 3000000.0,
      "rolled_back": false,
      "created_at": "2026-04-19T12:00:00"
    },
    {
      "id": 2,
      "tier": 2,
      "bonus_points": 1500,
      "cash_cost": 3000000.0,
      "rolled_back": false,
      "created_at": "2026-04-19T12:05:00"
    }
  ],
  "tier_schedule": [
    { "tier": 1,  "cost": 3000000,  "points_gained": 2000, "cumulative_total": 4000,  "cumulative_cost": 3000000,  "cost_per_point": 1500 },
    { "tier": 2,  "cost": 3000000,  "points_gained": 1500, "cumulative_total": 5500,  "cumulative_cost": 6000000,  "cost_per_point": 2000 },
    { "tier": 3,  "cost": 3000000,  "points_gained": 1500, "cumulative_total": 7000,  "cumulative_cost": 9000000,  "cost_per_point": 2000 },
    { "tier": 4,  "cost": 3000000,  "points_gained": 1000, "cumulative_total": 8000,  "cumulative_cost": 12000000, "cost_per_point": 3000 },
    { "tier": 5,  "cost": 3000000,  "points_gained": 1000, "cumulative_total": 9000,  "cumulative_cost": 15000000, "cost_per_point": 3000 },
    { "tier": 6,  "cost": 5000000,  "points_gained": 1000, "cumulative_total": 10000, "cumulative_cost": 20000000, "cost_per_point": 5000 },
    { "tier": 7,  "cost": 5000000,  "points_gained": 1000, "cumulative_total": 11000, "cumulative_cost": 25000000, "cost_per_point": 5000 },
    { "tier": 8,  "cost": 5000000,  "points_gained": 1000, "cumulative_total": 12000, "cumulative_cost": 30000000, "cost_per_point": 5000 },
    { "tier": 9,  "cost": 7000000,  "points_gained": 1000, "cumulative_total": 13000, "cumulative_cost": 37000000, "cost_per_point": 7000 },
    { "tier": 10, "cost": 7000000,  "points_gained": 1000, "cumulative_total": 14000, "cumulative_cost": 44000000, "cost_per_point": 7000 },
    { "tier": 11, "cost": 10000000, "points_gained": 1000, "cumulative_total": 15000, "cumulative_cost": 54000000, "cost_per_point": 10000 }
  ]
}
```

**Response (college org or non-eligible):**
```json
{
  "eligible": false,
  "reason": "Only MLB organizations can expand scouting departments",
  "base_budget": 2000,
  "total_budget": 2000
}
```

---

### 2. POST `/scouting/department/purchase`

Purchase the next tier. Sequential — you must buy tier N before tier N+1.

**Request body:**
```json
{
  "org_id": 5,
  "league_year_id": 1,
  "executed_by": "user123"
}
```

`executed_by` is optional, used for audit logging.

**Success response (200):**
```json
{
  "status": "purchased",
  "tier": 3,
  "bonus_points": 1500,
  "cash_cost": 3000000.0,
  "new_total_budget": 7000,
  "remaining_cash": 42500000.0
}
```

**Error responses (400):**
```json
{ "error": "validation", "message": "Insufficient funds: need $3,000,000, have $1,200,000" }
{ "error": "validation", "message": "Already at maximum scouting department tier (11)" }
{ "error": "validation", "message": "Only MLB organizations can expand scouting departments" }
```

---

### 3. POST `/scouting/department/rollback` (Admin Only)

Undo the most recent purchase (LIFO — last in, first out). Only succeeds if the org hasn't already spent points that would put them over the new lower budget.

**This endpoint is for the admin panel only — it should not be exposed in the user-facing frontend.**

**Request body:**
```json
{
  "org_id": 5,
  "league_year_id": 1,
  "executed_by": "admin"
}
```

**Success response (200):**
```json
{
  "status": "rolled_back",
  "tier_removed": 3,
  "refunded_points": 1500,
  "refunded_cash": 3000000.0,
  "new_total_budget": 5500,
  "remaining_cash": 45500000.0
}
```

**Error responses (400):**
```json
{ "error": "validation", "message": "No active scouting department purchases to roll back" }
{ "error": "validation", "message": "Cannot roll back: 6200 points already spent, rollback would reduce budget to 5500" }
```

---

### 4. Existing Budget Endpoint (unchanged)

**GET `/scouting/budget/<org_id>?league_year_id=<id>`**

`total_points` already reflects department expansion bonuses — no changes needed to existing budget display code.

```json
{
  "org_id": 5,
  "league_year_id": 1,
  "total_points": 7000,
  "spent_points": 1240,
  "remaining_points": 5760
}
```

---

## User-Facing UI

### Scouting Department Panel

Suggested location: alongside or within the existing scouting budget display for MLB orgs.

**Key elements:**

1. **Budget bar** — show base (2000) + bonus as a stacked/segmented progress bar
   - Gray segment: base budget (always 2000)
   - Highlighted segment: purchased bonus points
   - Filled portion: spent points
   - Label: "1,240 / 7,000 points used"

2. **Upgrade button** — prominent CTA when `next_tier` is not null
   - Label: "Expand Department — $3M for +1,500 pts"
   - Disabled states:
     - `next_tier` is null → "Max Tier Reached"
     - Insufficient cash → "Insufficient Funds ($X needed)"
   - Confirmation dialog before purchase (this spends real org cash)
   - After purchase: show success feedback with new budget total

3. **Tier progress indicator** — show current tier vs max
   - e.g., "Tier 2 / 11" with pips or a step indicator
   - Compact: just "Scouting Dept: Tier 2"

4. **Tier schedule table** — expandable/collapsible reference showing all 11 tiers
   - Columns: Tier, Cost, Points Gained, Cumulative Total, $/Point
   - Highlight the current tier row
   - Dim rows above current (already purchased)
   - The `tier_schedule` array in the status response is ready to render directly

5. **Purchase history** — expandable log showing what the org has bought this season
   - Show tier, points gained, cost, date
   - Rolled-back entries (admin action) shown with strikethrough or muted style

### Visibility Rules

- **College orgs (31-338):** Hide the entire department panel. The status endpoint returns `eligible: false` — use this to conditionally render.
- **MLB orgs at max tier:** Show the panel but replace the upgrade button with a "Max Tier" badge.
- **No purchases yet:** Show the panel with the upgrade button and the tier schedule, emphasizing that the base 2000 is free.

### Points Report Section

To give users a breakdown of their scouting economy, combine data from two endpoints:

| Data | Source |
|---|---|
| Total / spent / remaining points | `GET /scouting/budget/<org_id>` |
| Department tier & bonus breakdown | `GET /scouting/department/<org_id>` |
| Per-player spending history | `GET /scouting/actions/<org_id>` |

**Suggested report layout:**

```
Scouting Budget                          Tier 2 / 11
[=========>-----------------------------] 1,240 / 5,500 pts
  Base: 2,000  |  Bonus: +3,500  |  Spent: 1,240

Next upgrade: Tier 3 — $3,000,000 for +1,500 pts
[Expand Department]

--- Spending Breakdown ---
  Pro Scouting:     42 actions    620 pts
  Draft Scouting:   18 actions    420 pts
  Potential Unlocks: 4 actions    200 pts
                              ----------
                    Total:      1,240 pts

--- Tier Schedule ---
  Tier   Cost        Points    Total    $/Point
  1*     $3,000,000  +2,000    4,000    $1,500
  2*     $3,000,000  +1,500    5,500    $2,000
  3      $3,000,000  +1,500    7,000    $2,000
  ...
  11     $10,000,000 +1,000    15,000   $10,000

  * = purchased
```

The spending breakdown by action type is not directly returned by the status endpoint — compute it client-side by grouping the actions list from `GET /scouting/actions/<org_id>` by `action_type` and summing `points_spent`.

### Scouting Action Costs (for reference display)

These are the current costs users see when scouting players. Useful for a "cost reference" tooltip or help section:

| Action | Cost | Context |
|---|---|---|
| HS Report | 2 | College orgs scouting HS players |
| Recruit Potential (fuzzed) | 10 | College orgs, requires HS Report |
| Recruit Potential (precise) | 50 | College orgs, requires fuzzed |
| College Potential (precise) | 15 | Any org on college players |
| Draft Attrs (fuzzed) | 10 | MLB orgs on college/INTAM prospects |
| Draft Attrs (precise) | 10 | MLB orgs, requires fuzzed |
| Draft Potential (precise) | 50 | MLB orgs on college/INTAM prospects |
| Pro Attrs (precise) | 10 | Any org on pro players (levels 4-9) |
| Pro Potential (precise) | 50 | Any org on pro players (levels 4-9) |

Full scout of one player: **60-70 pts** depending on context.

---

## Typical Flows

### Purchase Flow (User-Facing)
1. Frontend loads department status via GET
2. Renders upgrade button with next tier info
3. User clicks upgrade → confirmation dialog shows cost, points gained, and remaining cash after purchase
4. POST to `/scouting/department/purchase`
5. On success: refresh department status and budget display
6. On error: show validation message from response (insufficient funds, max tier, etc.)

### Admin Rollback Flow (Admin Panel Only)
1. Admin navigates to org's scouting management page
2. Admin clicks "Undo Last Upgrade"
3. Confirmation dialog warns about point/cash changes
4. POST to `/scouting/department/rollback`
5. On success: refresh department status and budget display
6. On 400 with "points already spent" message: show error explaining they need to have enough unspent points to undo

### Page Load
1. Fetch budget and department status in parallel
2. If `eligible === false`, hide department panel
3. Render budget bar, tier indicator, and upgrade button based on state
