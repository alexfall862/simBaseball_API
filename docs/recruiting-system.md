# College Recruiting System — Frontend Implementation Guide

## Overview

A **weighted lottery recruiting system** where 308 college organizations (org IDs 31–338) compete over a 20-week window to sign high school players (org 340) using recruiting points. All endpoints are under `/api/v1/recruiting/`.

### Key Concepts

| Concept | Description |
|---|---|
| **Star Rankings** | Public 1–5 star ratings computed from player attributes. Percentile-based: 50% are 1-star, 20% are 2-star, 20% are 3-star, 8% are 4-star, 2% are 5-star. |
| **Weekly Budget** | Each college org gets **100 points per week** (use-it-or-lose-it, not banked). Max **20 points per player per week**. |
| **Commitment** | When total interest from all schools crosses a star-based threshold, a weighted lottery determines the winner. Higher investment = better odds (superlinear `points^1.3`). |
| **Anti-Sniping** | If a new school reaches 80% of the leader's cumulative points within the last 2 weeks, the commitment threshold gets a 1.3x multiplier, delaying the commitment. |
| **Week 20 Cleanup** | All remaining players with any investment auto-commit to their point leader. Uninvested players remain in the HS pool (leftovers). |
| **Fog of War** | Schools see their own exact investment, a fuzzed "interest gauge" for total interest, and competitor count — but NOT other schools' specific investments or commitment probability. |

### Recruiting Lifecycle

```
pending → [Compute Rankings] → active (week 1)
   ↓
active (weeks 1–19): schools invest → end-of-week resolution → commitments
   ↓
active (week 20): final resolution + cleanup → all invested players committed
   ↓
complete
```

Each week advancement is triggered by an admin action (`POST /recruiting/advance-week`), not automatically.

---

## Org ID Reference

| Range | Type | Can Recruit? |
|---|---|---|
| 1–30 | MLB orgs | No (draft scouting only) |
| 31–338 | College orgs | **Yes** — these are the recruiting participants |
| 339 | INTAM | No |
| 340 | US High School | No (these are the recruitment targets) |

---

## API Endpoints

All endpoints prefixed with `/api/v1`. All return JSON. Errors return `{ error: string, message: string }` with appropriate HTTP status codes.

---

### 1. `GET /recruiting/rankings`

**Public star rankings, paginated.**

Every school and every user sees the same rankings — star ratings are not subject to fog of war.

#### Query Parameters

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `league_year_id` | int | **Yes** | — | The league year to query |
| `page` | int | No | 1 | Page number (1-indexed) |
| `per_page` | int | No | 50 | Results per page (max 200) |
| `star_rating` | int | No | — | Filter by star rating (1–5) |
| `ptype` | string | No | — | Filter by player type (`"Pitcher"` or `"Position"`) |
| `search` | string | No | — | Search by first or last name (partial match) |

#### Response

```json
{
  "players": [
    {
      "player_id": 12345,
      "player_name": "John Smith",
      "ptype": "Pitcher",
      "age": 17,
      "star_rating": 5,
      "rank_overall": 1,
      "rank_by_ptype": 1
    }
  ],
  "page": 1,
  "per_page": 50,
  "total": 1200,
  "total_pages": 24
}
```

#### Notes

- Rankings only exist after the first `advance-week` call (which computes them).
- `rank_overall` is the global rank across all player types.
- `rank_by_ptype` is the rank within the player's type (Pitcher or Position).
- Returns empty `players: []` with `total: 0` if rankings haven't been computed yet.

---

### 2. `GET /recruiting/state`

**Current recruiting phase state.**

Use this to determine what UI to show — whether recruiting is pending, active, or complete, and what week it's on.

#### Query Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `league_year_id` | int | **Yes** | The league year to query |

#### Response

```json
{
  "league_year_id": 5,
  "current_week": 7,
  "status": "active",
  "total_weeks": 20
}
```

#### Status Values

| Status | Meaning | UI Implications |
|---|---|---|
| `"pending"` | Rankings not yet computed | Show "Recruiting not started" message. No invest/board endpoints will work. |
| `"active"` | Recruiting is in progress | Show invest UI, board, rankings. `current_week` indicates which week is accepting investments. |
| `"complete"` | All 20 weeks resolved | Show final results. Investment endpoints will reject. |

#### Notes

- If no `recruiting_state` row exists for the year, returns `{ current_week: 0, status: "pending" }`.
- `total_weeks` comes from `recruiting_config` table (default 20).

---

### 3. `POST /recruiting/invest`

**Submit weekly recruiting point investments.**

This is the core interaction — a college org allocates their weekly 100-point budget across HS players.

#### Request Body

```json
{
  "org_id": 45,
  "league_year_id": 5,
  "week": 7,
  "investments": [
    { "player_id": 12345, "points": 20 },
    { "player_id": 12346, "points": 15 },
    { "player_id": 12347, "points": 10 }
  ]
}
```

#### Response

```json
{
  "accepted": [
    { "player_id": 12345, "points": 20 },
    { "player_id": 12346, "points": 15 }
  ],
  "errors": [
    { "player_id": 12347, "error": "Player already committed" }
  ],
  "budget_remaining": 65
}
```

#### Validation Rules

| Rule | Error Message |
|---|---|
| `org_id` not in range 31–338 | `"Only college organizations can recruit"` |
| Recruiting not active | `"Recruiting is not active (status: ...)"` |
| `week` doesn't match current week | `"Current week is X, not Y"` |
| `points` <= 0 | `"Points must be positive"` |
| `points` > 20 (per player per week) | `"Max 20 per player per week"` |
| Total exceeds 100 weekly budget | `"Exceeds weekly budget"` |
| Player not in HS pool (org 340) | `"Player not in HS pool"` |
| Player already committed | `"Player already committed"` |

#### Important Behavior

- **Idempotent re-submission**: If you POST for the same `(org_id, player_id, week)`, it **replaces** the previous investment for that player (not adds to it). This allows "change my mind" within a week.
- **Partial success**: Investments are processed in order. If one fails validation, earlier ones are still accepted. Check both `accepted` and `errors` arrays.
- `budget_remaining` reflects the org's remaining weekly budget after all accepted investments.

---

### 4. `POST /recruiting/advance-week`

**Admin action: advance recruiting by one week.**

This is an admin-only endpoint that drives the recruiting lifecycle forward.

#### Request Body

```json
{
  "league_year_id": 5
}
```

#### Response (varies by week)

**First call (week 0 → 1, initialization):**

```json
{
  "previous_week": 0,
  "new_week": 1,
  "status": "active",
  "ranked_players": 1200
}
```

**Weeks 1–19 (normal resolution):**

```json
{
  "previous_week": 7,
  "new_week": 8,
  "status": "active",
  "commitments": [
    {
      "player_id": 12345,
      "org_id": 45,
      "week": 7,
      "points_total": 120,
      "star_rating": 3
    }
  ],
  "uncommitted_count": 847
}
```

**Week 20 (final resolution + cleanup):**

```json
{
  "previous_week": 20,
  "new_week": 21,
  "status": "complete",
  "commitments": [...],
  "uncommitted_count": 0,
  "cleanup_commitments": [...],
  "leftovers": 312
}
```

**Already complete:**

```json
{
  "status": "complete",
  "message": "Recruiting already complete"
}
```

#### What Happens Each Week

| Transition | Action |
|---|---|
| 0 → 1 | Compute star rankings for all HS players, set status to `"active"` |
| 1 → 2 through 19 → 20 | Resolve previous week's investments: check thresholds, run lottery for eligible players, record commitments |
| 20 → 21 | Final resolution + cleanup: remaining invested players go to their point leader, uninvested stay as leftovers |
| > 20 | No-op, returns `"complete"` |

---

### 5. `GET /recruiting/board/<org_id>`

**Org's recruiting board with fog-of-war.**

This is the primary view for a college org — shows all players they've invested in, with their investment totals and fuzzed competitive intelligence.

#### Path Parameters

| Param | Type | Description |
|---|---|---|
| `org_id` | int | College org ID (must be 31–338) |

#### Query Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `league_year_id` | int | **Yes** | The league year to query |

#### Response

```json
{
  "players": [
    {
      "player_id": 12345,
      "player_name": "John Smith",
      "ptype": "Pitcher",
      "star_rating": 4,
      "rank_overall": 37,
      "your_points": 80,
      "interest_gauge": "High",
      "competitor_count": 5,
      "status": "uncommitted"
    },
    {
      "player_id": 12346,
      "player_name": "Mike Jones",
      "ptype": "Position",
      "star_rating": 3,
      "rank_overall": 156,
      "your_points": 40,
      "interest_gauge": "Medium",
      "competitor_count": 2,
      "status": "committed",
      "committed_to": {
        "org_id": 72,
        "org_abbrev": "DUKE",
        "week_committed": 5
      }
    }
  ]
}
```

#### Field Details

| Field | Description |
|---|---|
| `your_points` | This org's cumulative investment across all weeks (exact, not fuzzed) |
| `interest_gauge` | Fuzzed bucket: `"Low"`, `"Medium"`, `"High"`, or `"Very High"`. **Different orgs see different gauges for the same player** due to deterministic per-org fuzzing (shifted ±1 tier). |
| `competitor_count` | Exact count of how many other schools have invested in this player (but not who or how much) |
| `status` | `"uncommitted"` or `"committed"` |
| `committed_to` | Only present when `status === "committed"`. Shows which school won (public info). |

#### Sort Order

Results are sorted: uncommitted players first (by star rating descending, then rank), then committed players.

#### Notes

- Returns `{ players: [] }` if the org hasn't invested in anyone yet.
- Returns 400 if `org_id` is not a college org (31–338).

---

### 6. `GET /recruiting/player/<player_id>`

**Single player recruiting detail with fog-of-war.**

Detailed view of one player's recruiting status, optionally from a specific org's perspective.

#### Path Parameters

| Param | Type | Description |
|---|---|---|
| `player_id` | int | The player to query |

#### Query Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `league_year_id` | int | **Yes** | The league year to query |
| `viewing_org_id` | int | No | If provided, includes that org's exact investment and org-specific fuzzed gauge |

#### Response (with `viewing_org_id`)

```json
{
  "player_id": 12345,
  "player_name": "John Smith",
  "ptype": "Pitcher",
  "star_rating": 4,
  "rank_overall": 37,
  "rank_by_ptype": 12,
  "status": "uncommitted",
  "interest_gauge": "High",
  "competitor_count": 5,
  "your_investment": 80
}
```

#### Response (committed player)

```json
{
  "player_id": 12346,
  "player_name": "Mike Jones",
  "ptype": "Position",
  "star_rating": 3,
  "rank_overall": 156,
  "rank_by_ptype": 89,
  "status": "committed",
  "commitment": {
    "org_id": 72,
    "org_abbrev": "DUKE",
    "week_committed": 5,
    "points_total": 120
  },
  "interest_gauge": "Very High",
  "competitor_count": 3,
  "your_investment": 40
}
```

#### Notes

- Returns 404 if the player isn't in the rankings for the given league year.
- `your_investment` is only included when `viewing_org_id` is provided.
- `interest_gauge` is fuzzed per `viewing_org_id`. If `viewing_org_id` is omitted, the unfuzzed bucket is returned (useful for admin/debug).
- `commitment` object is only present when `status === "committed"`. Commitment info is public.

---

### 7. `GET /recruiting/commitments`

**Public commitment list, paginated.**

All commitments are public — every school can see who committed where and when.

#### Query Parameters

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `league_year_id` | int | **Yes** | — | The league year to query |
| `page` | int | No | 1 | Page number |
| `per_page` | int | No | 50 | Results per page (max 200) |
| `org_id` | int | No | — | Filter by committing school |
| `star_rating` | int | No | — | Filter by star rating |
| `week` | int | No | — | Filter by commitment week |

#### Response

```json
{
  "commitments": [
    {
      "player_id": 12345,
      "player_name": "John Smith",
      "ptype": "Pitcher",
      "org_id": 45,
      "org_abbrev": "UNC",
      "star_rating": 4,
      "week_committed": 3,
      "points_total": 120
    }
  ],
  "page": 1,
  "per_page": 50,
  "total": 87,
  "total_pages": 2
}
```

#### Notes

- Sorted by `week_committed ASC`, then `star_rating DESC`.
- `points_total` is the winning school's cumulative investment (not the total from all schools).

---

## Fog of War — What Each Org Can See

| Data | Visibility | Details |
|---|---|---|
| Star rankings | **Public** | All orgs see the same 1–5 star ratings and ranks |
| Your own investment | **Exact** | Cumulative points your org has invested in a player |
| Interest gauge | **Fuzzed** | Bucket label shifted ±1 tier per org via deterministic hash. Two orgs viewing the same player may see "Medium" vs "High" |
| Competitor count | **Exact count** | "5 other schools are recruiting this player" — but no names or amounts |
| Commitments | **Public** | Player X committed to school Y in week Z — visible to everyone |
| Other schools' investments | **Hidden** | You never see how much another school has invested |
| Commitment probability | **Hidden** | Not exposed |

### Interest Gauge Buckets

The true interest level maps to buckets based on total points from all schools:

| Total Interest (all schools) | True Bucket |
|---|---|
| 0–49 | Low |
| 50–149 | Medium |
| 150–299 | High |
| 300+ | Very High |

Each org sees this shifted ±1 tier via a deterministic hash of `(org_id, player_id, "interest")`. The shift direction is consistent per org-player pair across the entire recruiting window.

---

## Commitment Mechanics

### Threshold Formula

Each week, for each uncommitted player with investment:

```
threshold = star_base - (week * star_decay)
threshold = max(threshold, 0)
```

Default thresholds (admin-tunable via `recruiting_config`):

| Star | Base | Decay/week | Week 1 Threshold | Week 10 | Week 20 |
|---|---|---|---|---|---|
| 5-star | 300 | 12 | 288 | 180 | 60 |
| 4-star | 200 | 8 | 192 | 120 | 40 |
| 3-star | 120 | 5 | 115 | 70 | 20 |
| 2-star | 60 | 2.5 | 57.5 | 35 | 10 |
| 1-star | 20 | 1 | 19 | 10 | 0 |

If `total_interest >= threshold` → **weighted lottery** fires.

### Weighted Lottery

```
weight = cumulative_points ^ 1.3  (superlinear)
```

School with 200 points has `200^1.3 ≈ 1,036` weight vs school with 100 points at `100^1.3 ≈ 501`. Roughly 2:1 odds, not quite proportional — heavy investment is rewarded.

### Anti-Sniping

If **any non-leader school** reaches 80% of the leader's cumulative points AND that school's first investment was within the last 2 weeks:

```
effective_threshold = threshold * 1.3
```

This delays commitment, giving the original leader time to respond.

### Week 20 Cleanup

- Players with any investment: auto-commit to whoever has the most cumulative points (no lottery — point leader wins outright)
- Players with zero investment: remain in HS pool as leftovers

---

## Configuration (Admin-Tunable)

All values stored in `recruiting_config` table. Defaults shown:

| Key | Default | Description |
|---|---|---|
| `points_per_week` | 100 | Weekly recruiting budget per school |
| `max_points_per_player_per_week` | 20 | Per-player weekly cap |
| `recruiting_weeks` | 20 | Total weeks in recruiting window |
| `lottery_exponent` | 1.3 | Superlinear exponent for lottery weighting |
| `snipe_threshold_pct` | 0.80 | % of leader's points that triggers anti-snipe |
| `snipe_cooldown_weeks` | 2 | How recently a school must have started investing to be a "sniper" |
| `snipe_threshold_mult` | 1.3 | Threshold multiplier when anti-snipe triggers |
| `star5_base` / `star5_decay` | 300 / 12 | 5-star commitment threshold parameters |
| `star4_base` / `star4_decay` | 200 / 8 | 4-star threshold |
| `star3_base` / `star3_decay` | 120 / 5 | 3-star threshold |
| `star2_base` / `star2_decay` | 60 / 2.5 | 2-star threshold |
| `star1_base` / `star1_decay` | 20 / 1 | 1-star threshold |

---

## Database Schema

### `recruiting_rankings`

Star rankings, recomputed each recruiting cycle.

| Column | Type | Description |
|---|---|---|
| `id` | INT PK | Auto-increment |
| `player_id` | INT FK → simbbPlayers | |
| `league_year_id` | INT FK → league_years | |
| `composite_score` | FLOAT | Raw composite score |
| `star_rating` | TINYINT | 1–5 |
| `rank_overall` | INT | Global rank |
| `rank_by_ptype` | INT | Rank within Pitcher/Position |

Unique: `(player_id, league_year_id)`

### `recruiting_investments`

Per-org, per-week point allocations.

| Column | Type | Description |
|---|---|---|
| `id` | INT PK | Auto-increment |
| `org_id` | INT FK → organizations | The investing school |
| `player_id` | INT FK → simbbPlayers | Target player |
| `league_year_id` | INT FK → league_years | |
| `week` | INT | Week number (1–20) |
| `points` | INT | Points invested this week |
| `created_at` | TIMESTAMP | |

Unique: `(org_id, player_id, league_year_id, week)`

### `recruiting_commitments`

Final commitments (public).

| Column | Type | Description |
|---|---|---|
| `id` | INT PK | Auto-increment |
| `player_id` | INT FK → simbbPlayers | |
| `org_id` | INT FK → organizations | Winning school |
| `league_year_id` | INT FK → league_years | |
| `week_committed` | INT | Which week the commitment happened |
| `points_total` | INT | Winner's cumulative investment |
| `star_rating` | TINYINT | Star rating at time of commitment |
| `created_at` | TIMESTAMP | |

Unique: `(player_id, league_year_id)`

### `recruiting_state`

Recruiting phase tracker.

| Column | Type | Description |
|---|---|---|
| `league_year_id` | INT PK FK → league_years | |
| `current_week` | INT | 0 = pending, 1–20 = active, 21 = complete |
| `status` | ENUM | `'pending'`, `'active'`, `'complete'` |

### `recruiting_config`

Admin-tunable parameters (key-value).

| Column | Type | Description |
|---|---|---|
| `id` | INT PK | |
| `config_key` | VARCHAR(64) UNIQUE | Config parameter name |
| `config_value` | VARCHAR(255) | Value (stored as string, parsed as int/float) |
| `description` | VARCHAR(255) | Human-readable description |

---

## Typical Frontend Flows

### 1. Recruiting Dashboard (any user)

```
1. GET /recruiting/state?league_year_id=X
   → Show status badge (pending/active/complete) and current week

2. GET /recruiting/rankings?league_year_id=X&per_page=50
   → Star rankings table with filters (star, ptype, search)

3. GET /recruiting/commitments?league_year_id=X
   → Public commitment feed
```

### 2. Org Recruiting Board (college org user)

```
1. GET /recruiting/state?league_year_id=X
   → Check if active + get current week

2. GET /recruiting/board/{org_id}?league_year_id=X
   → Show all players this org is tracking with interest gauges

3. For each player detail:
   GET /recruiting/player/{pid}?league_year_id=X&viewing_org_id={org_id}
```

### 3. Weekly Investment Submission

```
1. GET /recruiting/state?league_year_id=X
   → Confirm status=active, get current_week

2. User allocates points to players (max 20 each, max 100 total)

3. POST /recruiting/invest
   Body: { org_id, league_year_id, week: current_week, investments: [...] }

4. Check response.errors for any rejected investments
   Show response.budget_remaining
```

### 4. Browse Rankings + Scout

```
1. GET /recruiting/rankings?league_year_id=X&star_rating=5&per_page=20
   → Top prospects

2. Click player → GET /recruiting/player/{pid}?league_year_id=X&viewing_org_id={org_id}
   → Show fuzzed interest, competitor count, your investment

3. Optional: cross-reference with scouting endpoints
   GET /scouting/college-pool?league_year_id=X (for attribute visibility)
```

---

## Error Handling

All errors follow the standard pattern:

```json
{
  "error": "error_type",
  "message": "Human-readable description"
}
```

| HTTP Status | `error` Value | When |
|---|---|---|
| 400 | `"missing_param"` | Required query/body param missing |
| 400 | `"validation_error"` | Business rule violation (wrong org type, wrong week, budget exceeded, etc.) |
| 404 | `"not_found"` | Player not in rankings |
| 500 | `"database_error"` | Database failure |

---

## Season Wipe

All recruiting tables are wiped during season reset (`POST /games/wipe-season`):

- `recruiting_investments`
- `recruiting_commitments`
- `recruiting_rankings`
- `recruiting_state`

This means recruiting starts fresh each league year.

---

## Relationship to Scouting System

Recruiting and scouting are **independent but complementary** systems:

- **Scouting** reveals player attributes (fuzzed grades, precise stats) via scouting points. Endpoints: `/scouting/*`
- **Recruiting** determines which school a player commits to via recruiting points. Endpoints: `/recruiting/*`

A college org can use scouting to evaluate prospects and then use recruiting to compete for them. The two point budgets are separate (`scouting_budgets` vs the weekly 100-point recruiting budget).

Scouting unlocks (e.g., `hs_report`, `recruit_potential_fuzzed`) carry over — they persist across recruiting weeks and don't need to be re-purchased.
