# Waiver Wire — Frontend Implementation Guide

Every mid-season player release now goes through a 1-week waiver period before the player can become a free agent. This document covers everything the frontend needs to build the waiver wire UI.

---

## How It Works

1. An org releases a player via `POST /transactions/release`
2. The player is placed on the **waiver wire** for exactly 1 game week
3. During that week, any other org can place a **waiver claim**
4. When the week expires (on the next `advance_week`):
   - **If claimed**: the org with the **worst record** among claimants wins. The full remaining contract transfers to them — all guaranteed years and salary, like a trade with 0% retention. The releasing org is completely off the hook.
   - **If unclaimed**: the old contract is finished (`isFinished=1`, remaining salary becomes dead money on the releasing org's books). The player enters the free agent pool with a tier-appropriate demand and can be signed by anyone.

### Claim Priority

When multiple orgs claim the same player, the winner is determined by **reverse standings order** — the team with the worst winning percentage at the player's last level wins. Ties are broken by fewest total wins, then by org ID. This intentionally favors weaker teams.

The frontend does not need to compute priority. The backend resolves it automatically and the result is visible after the week advances.

---

## Release Response (Changed)

The release endpoint response now includes waiver placement info.

```
POST /api/v1/transactions/release
```

```json
{
  "contract_id": 789,
  "org_id": 1,
  "league_year_id": 5
}
```

**Response:**

```json
{
  "transaction_id": 1020,
  "contract_id": 789,
  "player_id": 12345,
  "years_remaining_on_books": 2,
  "waiver": {
    "waiver_claim_id": 501,
    "expires_week": 16
  },
  "player": {
    "player_id": 12345,
    "player_name": "Joe Smith",
    "age": 28,
    "position": "Pitcher",
    "current_level": null,
    "on_ir": false
  }
}
```

After a successful release, show a confirmation that includes when the waiver expires: _"Joe Smith placed on waivers. Clears week 16."_

---

## Endpoints

All paths are under `/api/v1`.

### List Active Waivers

```
GET /transactions/waivers?league_year_id={leagueYearId}&org_id={orgId}
```

`league_year_id` is required. `org_id` is optional — when provided, each entry includes `my_bid` (whether this org has already placed a claim).

**Response:**

```json
{
  "ok": true,
  "count": 3,
  "waivers": [
    {
      "waiver_claim_id": 501,
      "player_id": 54321,
      "player_name": "Joe Smith",
      "ptype": "Pitcher",
      "age": 28,
      "displayovr": 62,
      "contract_id": 888,
      "contract_years": 4,
      "contract_current_year": 2,
      "contract_years_remaining": 2,
      "contract_salary": 8500000.00,
      "releasing_org_id": 5,
      "releasing_org_abbrev": "BOS",
      "placed_week": 15,
      "expires_week": 16,
      "last_level": 9,
      "service_years": 4,
      "fa_type": "arb",
      "bid_count": 2,
      "my_bid": true
    }
  ]
}
```

**Field notes:**

| Field | Type | Description |
|-------|------|-------------|
| `waiver_claim_id` | int | Use this as the ID for claim/withdraw/detail endpoints |
| `player_name` | string | Pre-formatted `"FirstName LastName"` |
| `contract_years` | int or null | Total contract length (e.g., 4 = a 4-year deal) |
| `contract_current_year` | int or null | Which year of the contract the player is in (1-based) |
| `contract_years_remaining` | int or null | Years left after this season (`contract_years - contract_current_year`) |
| `contract_salary` | float or null | Current-year salary. This is the gross salary for the current contract year — the claiming org takes on this and all future years at full value. |
| `releasing_org_abbrev` | string | The org that released the player (e.g., `"BOS"`) |
| `placed_week` | int | Week the player was released |
| `expires_week` | int | Week the waiver resolves (always `placed_week + 1`) |
| `last_level` | int | Level the player was at when released (4-9) |
| `service_years` | int | MLB service years at time of release |
| `fa_type` | string | One of `"mlb_fa"`, `"arb"`, `"pre_arb"`, `"milb_fa"` — see [FA Tiers](#what-fa_type-means) |
| `bid_count` | int | How many orgs have placed claims. Do NOT show which orgs. |
| `my_bid` | bool | Whether the viewing org has a pending claim. Only present when `org_id` is passed. |

### Single Waiver Detail

```
GET /transactions/waivers/{waiverClaimId}?org_id={orgId}
```

Same fields as the list entry, plus:

| Extra Field | Type | Description |
|-------------|------|-------------|
| `status` | string | `"active"`, `"claimed"`, or `"cleared"` |
| `claiming_org_id` | int or null | The org that won the claim (only set when `status == "claimed"`) |
| `resolved_at` | ISO string or null | Timestamp when the waiver was resolved |

### Place a Claim

```
POST /transactions/waivers/{waiverClaimId}/claim
```

```json
{ "org_id": 2 }
```

**Success:** `{ "ok": true, "bid_id": 9001, "waiver_claim_id": 501 }`

If the org already has a claim: `{ "ok": true, "bid_id": 9001, "waiver_claim_id": 501, "already_claimed": true }`

**Errors (400):**

| Error message | Cause |
|---------------|-------|
| `"Waiver claim {id} not found"` | Invalid waiver ID |
| `"Waiver claim {id} is no longer active (status=claimed)"` | Already resolved |
| `"Cannot claim your own released player"` | Self-claim attempt |

### Withdraw a Claim

```
DELETE /transactions/waivers/{waiverClaimId}/claim
```

```json
{ "org_id": 2 }
```

**Success:** `{ "ok": true, "withdrawn": true }`

**Error (400):** `"No bid found to withdraw"` — org didn't have a claim to withdraw.

---

## What `fa_type` Means

When a player clears waivers (no one claimed them), they enter the free agent pool. Their `fa_type` determines what kind of contract they expect and whether they go through the auction system:

| `fa_type` | Who | Demand floor | Signing method |
|-----------|-----|-------------|----------------|
| `mlb_fa` | 6+ MLB service years | WAR-based, min $1.6M AAV, multi-year | 3-phase auction (`/fa-auction/{id}/offer`) |
| `arb` | Level 9, 3-5 service years | $800,000 / 1 year | Direct signing (`/transactions/sign`) |
| `pre_arb` | Level 9, <3 service years | $800,000 / 1 year | Direct signing (`/transactions/sign`) |
| `milb_fa` | Last level 4-8 | $40,000 / 1 year | Direct signing (`/transactions/sign`) |

Key distinction: `mlb_fa` players enter the auction and require competitive bidding. All other tiers can be signed directly by any org — first come, first served, as long as the offer meets the demand floor.

The `fa_type` field also appears on every player in the free agent pool response (`GET /fa-auction/free-agent-pool`). Use it to determine which action button to show and which signing flow to use.

---

## What the Frontend Should Show

### On the Waiver Wire Page

A team's view of the waiver wire should answer three questions: _Who's available? Have I already claimed anyone? When do they expire?_

```
┌─────────────────────────────────────────────────────────────────────┐
│  Waiver Wire                                        Week 15 of 25  │
├────────┬─────┬──────┬─────┬─────────┬────────┬───────┬─────────────┤
│ Name   │ Age │ Type │ OVR │Released │Expires │Claims │   Action    │
├────────┼─────┼──────┼─────┼─────────┼────────┼───────┼─────────────┤
│ Smith  │  28 │  P   │ 62  │  BOS    │ Wk 16  │   2   │ [Withdraw]  │
│ Jones  │  24 │  B   │ 55  │  NYY    │ Wk 16  │   0   │ [Claim]     │
│ Brown  │  31 │  P   │ 48  │  LAD    │ Wk 16  │   1   │ [Claim]     │
└────────┴─────┴──────┴─────┴─────────┴────────┴───────┴─────────────┘
```

**Display rules:**

- Show **"Claim"** when `my_bid` is false
- Show **"Withdraw"** when `my_bid` is true
- **Hide the action button entirely** when `releasing_org_id` matches the viewing org (you released them — you can't claim your own player)
- Show `bid_count` so users can gauge competition, but **never reveal which orgs have claimed**
- Show `fa_type` as a small badge or tag on the player name (e.g., "MLB FA", "Arb", "Pre-Arb", "MiLB")
- Show `releasing_org_abbrev` so users know where the player came from

### On the Roster Page After a Release

After a successful release, the confirmation should mention the waiver period:

```
┌──────────────────────────────────────────────────────┐
│  ✓ Joe Smith released                                │
│                                                      │
│  Placed on waivers — clears after week 16.           │
│  Remaining salary ($4,200,000) stays on your books   │
│  unless another team claims him.                     │
└──────────────────────────────────────────────────────┘
```

Use `waiver.expires_week` from the release response for the week number. Use `years_remaining_on_books` to indicate financial exposure.

### On the Free Agent Pool Page

The pool now includes players who cleared waivers alongside traditional free agents. The `fa_type` field lets you differentiate them:

- Add a **tier filter** (dropdown or chip toggles) filtering on `fa_type`
- The **Action column** should vary by tier:
  - `mlb_fa` with active auction → "Offer" / "Update" (existing auction flow)
  - `mlb_fa` without auction yet → "View" (player just cleared, auction will open next week)
  - `arb` / `pre_arb` / `milb_fa` → "Sign" (direct signing modal)
- The **Demand column** always has data now — `demand` is guaranteed non-null for all pool players

### After a Week Advances

When the simulation advances a week, waivers may have resolved. Refresh:

1. **Waiver wire** — claimed/cleared players will be gone from the active list
2. **FA pool** — newly cleared players will appear with their `fa_type` and demand
3. **Roster** (for claiming orgs) — claimed players will appear on their roster with the transferred contract

---

## Signing a Player Who Cleared Waivers

For non-auction tiers (`arb`, `pre_arb`, `milb_fa`), use the existing direct signing endpoint:

```
POST /api/v1/transactions/sign
```

```json
{
  "player_id": 54321,
  "org_id": 1,
  "years": 1,
  "salaries": [800000],
  "bonus": 0,
  "level_id": 9,
  "league_year_id": 5,
  "game_week_id": 16
}
```

The `salaries` array must have exactly `years` entries. The total value must meet the player's `demand.min_aav`. Users can offer more than the minimum.

For `mlb_fa` players, the signing happens through the auction system as before — the player enters the auction automatically when they clear waivers, and orgs bid via `POST /fa-auction/{auctionId}/offer`.

---

## Lifecycle Summary

```
                        Player Released
                              │
                              ▼
                    ┌───────────────────┐
                    │   WAIVER WIRE     │
                    │   (1 game week)   │
                    │                   │
                    │  Any org can      │
                    │  place a claim    │
                    └────────┬──────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                ▼                         ▼
        Someone claimed            No one claimed
                │                         │
                ▼                         ▼
        Full contract              Old contract
        transfers to               finished
        worst-record               (dead money)
        claimant                          │
                                          ▼
                                ┌─────────────────┐
                                │   FA POOL        │
                                │                  │
                                │  mlb_fa → Auction│
                                │  arb    → Sign   │
                                │  pre_arb→ Sign   │
                                │  milb_fa→ Sign   │
                                └─────────────────┘
```
