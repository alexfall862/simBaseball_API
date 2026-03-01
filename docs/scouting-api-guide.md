# Scouting, Recruiting, Draft & Free Agency — Frontend Implementation Guide

Base URL: `/api/v1`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Organization & Player Pools](#2-organization--player-pools)
3. [Scouting Visibility Model](#3-scouting-visibility-model)
4. [High School Recruiting (College Orgs)](#4-high-school-recruiting-college-orgs)
5. [Pro Scouting & Draft (MLB Orgs)](#5-pro-scouting--draft-mlb-orgs)
6. [MLB Free Agency](#6-mlb-free-agency)
7. [Scouting Budget & Action History](#7-scouting-budget--action-history)
8. [Contract Management Endpoints](#8-contract-management-endpoints)
9. [Full Workflow Examples](#9-full-workflow-examples)
10. [Data Reference](#10-data-reference)

---

## 1. System Overview

Three parallel systems feed player acquisition:

| System | Who uses it | Source pool | Key endpoints |
|--------|------------|-------------|---------------|
| **HS Recruiting** | College orgs (31-338) | HS players at org 340 | `college-pool`, `scouting/player`, `scouting/action`, `sign` |
| **Pro Scouting / Draft** | MLB orgs (1-30) | College (31-338) + INTAM 18+ (339) | `pro-pool`, `scouting/player`, `scouting/action`, `sign` |
| **MLB Free Agency** | MLB orgs (1-30) | Unsigned MLB-level players | `free-agents`, `scouting/player`, `signing-budget`, `sign` |

All three share the same **scouting budget** (per org per league year) and the same **signing** endpoint. The difference is what information is visible by default and what must be unlocked with scouting points.

---

## 2. Organization & Player Pools

| Pool | Org IDs | Level ID | Description |
|------|---------|----------|-------------|
| High School (HS) | 340 (USHS) | 1 | US players ages 15-17. Single org, single team. |
| International Amateur (INTAM) | 339 | 2 | International players. Ages 15-17 not scout-eligible. Ages 18+ are. |
| College | 31-338 (308 orgs) | 3 | US players ages 18-23. Each org is one school. |
| MLB | 1-30 | 4-9 | 30 MLB organizations with farm systems (Scraps/A/High-A/AA/AAA/MLB). |

Player assignment is tracked via the contract chain: `contracts` → `contractDetails` → `contractTeamShare`. The `contractTeamShare.isHolder = 1` flag determines which org currently holds a player.

---

## 3. Scouting Visibility Model

### What each org type can see by default, and what they can unlock:

### HS Players (scouted by College orgs)

| Tier | What's visible | Cost | action_type |
|------|---------------|------|-------------|
| **Default** | Bio + deterministic season stats (slash line, fielding, pitching). Attributes = hidden. Potentials = hidden. | Free | — |
| **Action 1** | + Text scouting report (batting/fielding/pitching/athletic profiles, ~50-100 chars each) | 10 pts | `hs_report` |
| **Action 2** | + Potential letter grades (A+ through F) for all abilities | 25 pts | `hs_potential` |

Numeric attribute values (`_base` columns) are **never** visible until the player joins the college team.

### College Players (scouted by MLB orgs)

| Tier | What's visible | Cost | action_type |
|------|---------------|------|-------------|
| **Default** | Bio + all attributes as letter grades. Potentials hidden. | Free | — |
| **Action 1** | + Actual numeric attribute values | 15 pts | `pro_numeric` |

### INTAM Players age 18+ (scouted by MLB orgs)

| Tier | What's visible | Cost | action_type |
|------|---------------|------|-------------|
| **Default** | Bio + letter grades + counting stats (position: slash line, pitcher: W-L/ERA/K/BB/IP) | Free | — |
| **Action 1** | + Actual numeric attribute values | 15 pts | `pro_numeric` |

### MLB Free Agents

| Tier | What's visible | Cost |
|------|---------------|------|
| **Default** | Everything: bio, numeric attributes, potential grades | Free |

### Action prerequisites

- `hs_potential` requires `hs_report` to be unlocked first
- Actions are **permanent** — once unlocked, the info stays visible across league years
- Re-submitting an already-unlocked action returns `"already_unlocked"` without charging points

---

## 4. High School Recruiting (College Orgs)

This section covers everything a college org frontend needs to recruit HS players.

### 4.1 Browse HS Players

#### `GET /scouting/college-pool`

Paginated list of all HS players (org 340). Supports "Class of" tabs via the `age` filter.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `per_page` | int | 50 | Results per page (max 200) |
| `sort` | string | `lastname` | Sort column ([see allowed list](#allowed-sort-columns)) |
| `dir` | string | `asc` | Sort direction: `asc` or `desc` |
| `age` | int | — | Filter by age class (e.g., `17` for seniors, `16` for juniors) |
| `ptype` | string | — | Filter: `Pitcher` or `Position` |
| `area` | string | — | Region filter (exact match, e.g., `California`) |
| `search` | string | — | Name search (min 2 chars, searches firstname and lastname with LIKE) |

**Response:**

```json
{
  "total": 985,
  "page": 1,
  "per_page": 50,
  "pages": 20,
  "age_counts": {
    "15": 1050,
    "16": 1020,
    "17": 985
  },
  "players": [
    {
      "id": 1234,
      "firstname": "John",
      "lastname": "Smith",
      "age": 17,
      "ptype": "Position",
      "area": "Texas",
      "city": "Houston",
      "intorusa": "usa",
      "height": 74,
      "weight": 210,
      "bat_hand": "R",
      "pitch_hand": "R",
      "arm_angle": "3/4's",
      "durability": "Normal",
      "injury_risk": "Normal",
      "displayovr": null,
      "left_split": 40.0,
      "center_split": 35.0,
      "right_split": 25.0,
      "org_id": 340,
      "org_abbrev": "USHS",
      "current_level": 1,
      "contact_base": 15.2,
      "contact_pot": "B+",
      "power_base": 12.8,
      "power_pot": "A-",
      "...": "all other _base, _pot, pitch name/ovr columns"
    }
  ]
}
```

**Frontend notes:**
- `age_counts` always reflects the **full HS population** (ignoring the `age` filter), so you can render tab badges: `Seniors (985) | Juniors (1020) | Sophomores (1050)`
- The `players` array contains **raw attribute data** — the pool endpoint does NOT mask data. You must either:
  - (a) Use `/scouting/player/<id>` for individual player views (recommended — it pre-masks data), or
  - (b) Hide `_base` and `_pot` columns in the table view and only show bio + stats columns
- For the table/list view, show: name, age, area, ptype, height, weight, bat/pitch hand — do NOT show `_base` or `_pot` values for HS players

### 4.2 View Individual HS Player

#### `GET /scouting/player/<player_id>?org_id=<college_org>&league_year_id=<ly_id>`

Returns player data **pre-masked** to the requesting org's scouting visibility. This is the endpoint to use for the player detail/card view.

Both `org_id` and `league_year_id` are required query params.

**HS Player — Default (no scouting actions):**

```json
{
  "bio": {
    "id": 1234,
    "firstname": "John",
    "lastname": "Smith",
    "age": 17,
    "ptype": "Position",
    "area": "Texas",
    "city": "Houston",
    "intorusa": "usa",
    "height": 74,
    "weight": 210,
    "bat_hand": "R",
    "pitch_hand": "R",
    "arm_angle": "3/4's",
    "durability": "Normal",
    "injury_risk": "Normal",
    "pitch1_name": "4-Seam Fastball",
    "pitch2_name": "Curveball",
    "pitch3_name": "Changeup",
    "pitch4_name": "Slider",
    "pitch5_name": "Cutter"
  },
  "generated_stats": {
    "batting": {
      "games": 28,
      "at_bats": 89,
      "hits": 24,
      "doubles": 5,
      "triples": 1,
      "home_runs": 2,
      "rbi": 12,
      "runs": 14,
      "walks": 8,
      "strikeouts": 22,
      "stolen_bases": 4,
      "caught_stealing": 1,
      "avg": 0.270,
      "obp": 0.330,
      "slg": 0.427
    },
    "fielding": {
      "games": 28,
      "innings": 182,
      "putouts": 65,
      "assists": 38,
      "errors": 5,
      "fielding_pct": 0.954
    }
  },
  "visibility": {
    "pool": "hs",
    "unlocked": [],
    "available_actions": ["hs_report"]
  }
}
```

**What to render:**
- Bio section with all bio fields
- Stats table from `generated_stats`
- All attribute slots show `?`
- All potential slots show `?`
- Show a "Scout Report" button (10 pts) since `available_actions` includes `"hs_report"`

**HS Player — After `hs_report` unlocked:**

Same as above, plus `text_report`:

```json
{
  "bio": { "..." },
  "generated_stats": { "..." },
  "text_report": {
    "batting": "Solid contact ability with average pop. Developing approach.",
    "fielding": "Above-average defender with strong arm. Sure hands.",
    "athletic": "Good athlete. Plus speed and above-average agility."
  },
  "visibility": {
    "pool": "hs",
    "unlocked": ["hs_report"],
    "available_actions": ["hs_potential"]
  }
}
```

For pitchers, `text_report` also includes `"pitching"`:

```json
{
  "text_report": {
    "batting": "...",
    "fielding": "...",
    "pitching": "Plus arm with lively fastball velocity. Above-average zone control.",
    "athletic": "..."
  }
}
```

**What to render:**
- Everything from default tier
- Text report cards for each profile section
- Attributes still show `?`
- Show an "Unlock Potentials" button (25 pts) since `available_actions` includes `"hs_potential"`

**HS Player — After `hs_potential` unlocked:**

Same as above, plus `potentials`:

```json
{
  "bio": { "..." },
  "generated_stats": { "..." },
  "text_report": { "..." },
  "potentials": {
    "contact_pot": "B+",
    "power_pot": "A-",
    "discipline_pot": "C+",
    "eye_pot": "B",
    "speed_pot": "A",
    "baserunning_pot": "B-",
    "basereaction_pot": "C",
    "fieldcatch_pot": "B",
    "fieldreact_pot": "B+",
    "fieldspot_pot": "C+",
    "throwpower_pot": "B-",
    "throwacc_pot": "C+",
    "catchframe_pot": "D+",
    "catchsequence_pot": "D",
    "pendurance_pot": "F",
    "pgencontrol_pot": "F",
    "pthrowpower_pot": "D-",
    "psequencing_pot": "F",
    "pickoff_pot": "F",
    "pitch1_pacc_pot": "D",
    "pitch1_pcntrl_pot": "D-",
    "pitch1_pbrk_pot": "D",
    "pitch1_consist_pot": "D+",
    "...": "through pitch5"
  },
  "visibility": {
    "pool": "hs",
    "unlocked": ["hs_report", "hs_potential"],
    "available_actions": []
  }
}
```

**What to render:**
- Everything from report tier
- Potential letter grades next to each ability name
- Attributes STILL show `?` (numeric values never visible for HS players)
- No more actions available — `available_actions` is empty

### 4.3 Unlock HS Player Information

#### `POST /scouting/action`

Spend scouting points to unlock player information.

**Request Body:**

```json
{
  "org_id": 50,
  "league_year_id": 1,
  "player_id": 1234,
  "action_type": "hs_report"
}
```

`action_type` values for HS recruiting:
- `"hs_report"` — Unlock text scouting report (10 pts)
- `"hs_potential"` — Unlock potential grades (25 pts, requires `hs_report` first)

**Success Response (200):**

```json
{
  "status": "unlocked",
  "action_type": "hs_report",
  "player_id": 1234,
  "points_spent": 10,
  "points_remaining": 490
}
```

**Already Unlocked (200):**

```json
{
  "status": "already_unlocked",
  "action_type": "hs_report",
  "player_id": 1234,
  "points_spent": 0,
  "points_remaining": 490
}
```

**Error Responses (400):**

```json
{ "error": "validation", "message": "Insufficient scouting points: need 25, have 15" }
{ "error": "validation", "message": "Must unlock scouting report before viewing potentials" }
{ "error": "validation", "message": "Only college organizations can scout HS players" }
{ "error": "validation", "message": "HS scouting actions only apply to USHS players" }
{ "error": "missing_fields", "fields": ["player_id", "action_type"] }
```

### 4.4 Sign HS Player to College

After scouting, sign the player using the standard signing endpoint.

#### `POST /transactions/sign`

**Request Body:**

```json
{
  "player_id": 1234,
  "org_id": 50,
  "years": 4,
  "salaries": [0, 0, 0, 0],
  "bonus": 0,
  "level_id": 3,
  "league_year_id": 1,
  "game_week_id": 1,
  "executed_by": "coach_username"
}
```

**Response (200):**

```json
{
  "transaction_id": 42,
  "contract_id": 789,
  "player_id": 1234,
  "years": 4,
  "bonus": 0.0,
  "roster_warning": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `transaction_id` | int | ID in transaction_log |
| `contract_id` | int | New contract ID |
| `player_id` | int | The signed player |
| `years` | int | Contract length |
| `bonus` | float | Signing bonus paid |
| `roster_warning` | object or null | Non-null if roster is over limit after signing |

---

## 5. Pro Scouting & Draft (MLB Orgs)

This section covers everything an MLB org frontend needs to scout college/INTAM players for the draft or international signing.

### 5.1 Browse Draft-Eligible Players

#### `GET /scouting/pro-pool`

Paginated list of players available for pro scouting: INTAM age 18+ and all College players.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `per_page` | int | 50 | Results per page (max 200) |
| `sort` | string | `lastname` | Sort column ([see allowed list](#allowed-sort-columns)) |
| `dir` | string | `asc` | Sort direction: `asc` or `desc` |
| `ptype` | string | — | Filter: `Pitcher` or `Position` |
| `min_age` | int | — | Minimum age filter |
| `max_age` | int | — | Maximum age filter |
| `area` | string | — | Region filter (exact match) |
| `search` | string | — | Name search (min 2 chars) |
| `org_id` | int | — | Filter to a specific college org (e.g., `45` for one school) |

**Response:**

```json
{
  "total": 8542,
  "page": 1,
  "per_page": 50,
  "pages": 171,
  "pool_counts": {
    "college": 6200,
    "intam": 2342
  },
  "players": [
    {
      "id": 5678,
      "firstname": "Carlos",
      "lastname": "Martinez",
      "age": 21,
      "ptype": "Pitcher",
      "area": "Dominican Republic",
      "city": "Santo Domingo",
      "intorusa": "international",
      "height": 75,
      "weight": 195,
      "bat_hand": "R",
      "pitch_hand": "R",
      "arm_angle": "Overhead",
      "durability": "Dependable",
      "injury_risk": "Normal",
      "displayovr": null,
      "left_split": 30.0,
      "center_split": 45.0,
      "right_split": 25.0,
      "org_id": 339,
      "org_abbrev": "INTAM",
      "current_level": 2,
      "contact_base": 22.1,
      "contact_pot": "D+",
      "power_base": 18.5,
      "power_pot": "C-",
      "pgencontrol_base": 38.7,
      "pgencontrol_pot": "B",
      "pthrowpower_base": 42.3,
      "pthrowpower_pot": "A-",
      "...": "all other _base, _pot, pitch name/ovr columns",
      "pitch1_name": "4-Seam Fastball",
      "pitch1_ovr": 45.2,
      "pitch2_name": "Slider",
      "pitch2_ovr": 32.1,
      "org_id": 339,
      "org_abbrev": "INTAM",
      "current_level": 2
    }
  ]
}
```

**Frontend notes:**
- `pool_counts` always reflects the full unfiltered pool (useful for tab badges: "College (6200) | INTAM (2342)")
- The `players` array contains **raw attribute data** — the pool endpoint does NOT mask data
- For the table/list view: show `_base` values as **letter grades** (not numeric), since that's the default visibility tier for college/INTAM players. Use the [letter grade conversion table](#letter-grade-thresholds) to convert on the client, or use `/scouting/player/<id>` for pre-converted data
- Hide `_pot` columns entirely in the table view

### 5.2 View Individual College/INTAM Player

#### `GET /scouting/player/<player_id>?org_id=<mlb_org>&league_year_id=<ly_id>`

**College Player — Default (no scouting):**

```json
{
  "bio": {
    "id": 5678,
    "firstname": "Jake",
    "lastname": "Williams",
    "age": 21,
    "ptype": "Position",
    "area": "Florida",
    "city": "Miami",
    "intorusa": "usa",
    "height": 73,
    "weight": 205,
    "bat_hand": "L",
    "pitch_hand": "R",
    "arm_angle": "3/4's",
    "durability": "Normal",
    "injury_risk": "Normal",
    "pitch1_name": "4-Seam Fastball",
    "pitch2_name": "Curveball",
    "pitch3_name": "Changeup",
    "pitch4_name": null,
    "pitch5_name": null
  },
  "letter_grades": {
    "contact": "B",
    "power": "C+",
    "discipline": "C",
    "eye": "B-",
    "speed": "A-",
    "baserunning": "B",
    "basereaction": "C+",
    "fieldcatch": "B+",
    "fieldreact": "B",
    "fieldspot": "C",
    "throwpower": "C+",
    "throwacc": "B-",
    "catchframe": "D",
    "catchsequence": "D+",
    "pendurance": "F",
    "pgencontrol": "F",
    "pthrowpower": "D-",
    "psequencing": "F",
    "pickoff": "F",
    "pitch1_pacc": "D",
    "pitch1_pcntrl": "D",
    "pitch1_pbrk": "D-",
    "pitch1_consist": "D",
    "...": "through pitch5 sub-abilities"
  },
  "visibility": {
    "pool": "college",
    "unlocked": [],
    "available_actions": ["pro_numeric"]
  }
}
```

**What to render:**
- Bio section
- Attribute grid with letter grades (e.g., "Contact: B", "Power: C+")
- No numeric values shown
- Show an "Unlock Numbers" button (15 pts) since `available_actions` includes `"pro_numeric"`

**College Player — After `pro_numeric` unlocked:**

```json
{
  "bio": { "..." },
  "letter_grades": { "...same as above..." },
  "attributes": {
    "contact_base": 42.5,
    "power_base": 38.1,
    "discipline_base": 28.3,
    "eye_base": 35.7,
    "speed_base": 44.2,
    "baserunning_base": 36.8,
    "basereaction_base": 30.1,
    "fieldcatch_base": 40.5,
    "fieldreact_base": 37.2,
    "fieldspot_base": 29.0,
    "throwpower_base": 32.4,
    "throwacc_base": 35.8,
    "catchframe_base": 12.0,
    "catchsequence_base": 14.5,
    "pendurance_base": 5.0,
    "pgencontrol_base": 3.2,
    "pthrowpower_base": 8.1,
    "psequencing_base": 4.0,
    "pickoff_base": 2.5,
    "pitch1_ovr": 45.2,
    "pitch2_ovr": 32.1,
    "pitch3_ovr": 28.0,
    "pitch4_ovr": 0.0,
    "pitch5_ovr": 0.0
  },
  "visibility": {
    "pool": "college",
    "unlocked": ["pro_numeric"],
    "available_actions": []
  }
}
```

**What to render:**
- Bio section
- Attribute grid with BOTH letter grade and numeric value (e.g., "Contact: B (42.5)")
- `letter_grades` is still included for convenience
- No more actions — `available_actions` is empty

**INTAM Player — Default (no scouting):**

Same as college, plus `counting_stats`:

```json
{
  "bio": { "..." },
  "letter_grades": { "..." },
  "counting_stats": {
    "batting": {
      "games": 50,
      "at_bats": 180,
      "hits": 52,
      "doubles": 10,
      "triples": 2,
      "home_runs": 5,
      "rbi": 25,
      "runs": 28,
      "walks": 15,
      "strikeouts": 40,
      "stolen_bases": 8,
      "caught_stealing": 3,
      "avg": 0.289,
      "obp": 0.344,
      "slg": 0.456
    },
    "fielding": {
      "games": 50,
      "innings": 325,
      "putouts": 120,
      "assists": 75,
      "errors": 8,
      "fielding_pct": 0.961
    }
  },
  "visibility": {
    "pool": "intam",
    "unlocked": [],
    "available_actions": ["pro_numeric"]
  }
}
```

For INTAM **pitchers**, `counting_stats` contains `pitching` + scaled-down `batting`:

```json
{
  "counting_stats": {
    "pitching": {
      "games": 15,
      "games_started": 15,
      "wins": 6,
      "losses": 4,
      "era": 3.85,
      "innings_pitched": 78.5,
      "innings_pitched_outs": 235,
      "hits_allowed": 72,
      "runs_allowed": 35,
      "earned_runs": 33,
      "walks": 28,
      "strikeouts": 65,
      "home_runs_allowed": 6,
      "saves": 0,
      "k_per_9": 7.5,
      "bb_per_9": 3.2,
      "whip": 1.27
    },
    "batting": { "...scaled-down pitcher batting line..." }
  }
}
```

**INTAM Player — After `pro_numeric` unlocked:**

Same structure as college numeric unlock: adds `attributes` dict with all `_base` values and pitch OVRs.

### 5.3 Unlock Pro Scouting Data

#### `POST /scouting/action`

**Request Body:**

```json
{
  "org_id": 1,
  "league_year_id": 1,
  "player_id": 5678,
  "action_type": "pro_numeric"
}
```

**Success Response (200):**

```json
{
  "status": "unlocked",
  "action_type": "pro_numeric",
  "player_id": 5678,
  "points_spent": 15,
  "points_remaining": 985
}
```

**Error Responses (400):**

```json
{ "error": "validation", "message": "Only MLB organizations can scout college/INTAM players" }
{ "error": "validation", "message": "Pro scouting only applies to college or INTAM players" }
{ "error": "validation", "message": "Insufficient scouting points: need 15, have 10" }
```

### 5.4 Draft/Sign a Scouted Player

Use the same signing endpoint as free agency:

#### `POST /transactions/sign`

```json
{
  "player_id": 5678,
  "org_id": 1,
  "years": 6,
  "salaries": [500000, 500000, 500000, 500000, 500000, 500000],
  "bonus": 2000000,
  "level_id": 5,
  "league_year_id": 1,
  "game_week_id": 1,
  "executed_by": "gm_username"
}
```

Response is the same as [section 6.4](#64-sign-a-free-agent).

---

## 6. MLB Free Agency

This section covers the MLB free agent workflow. Free agents have **full visibility** — no scouting points needed.

### 6.1 Browse Free Agents

#### `GET /transactions/free-agents`

Returns all unsigned players (no active held contract).

**Response (200):**

```json
[
  {
    "player_id": 9999,
    "player_name": "Mike Johnson",
    "age": 28,
    "position": "Position"
  },
  {
    "player_id": 10001,
    "player_name": "David Chen",
    "age": 31,
    "position": "Pitcher"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | int | Player ID |
| `player_name` | string | `"Firstname Lastname"` |
| `age` | int | Player age |
| `position` | string | `"Position"` or `"Pitcher"` |

**Note:** This endpoint returns a minimal list. To get full player data, call `/scouting/player/<id>` or `/players/<id>/` for each player.

### 6.2 View Free Agent Profile

#### `GET /scouting/player/<player_id>?org_id=<mlb_org>&league_year_id=<ly_id>`

For MLB free agents, returns **full visibility** with no scouting needed:

```json
{
  "bio": {
    "id": 9999,
    "firstname": "Mike",
    "lastname": "Johnson",
    "age": 28,
    "ptype": "Position",
    "area": "Georgia",
    "city": "Atlanta",
    "intorusa": "usa",
    "height": 75,
    "weight": 220,
    "bat_hand": "R",
    "pitch_hand": "R",
    "arm_angle": "3/4's",
    "durability": "Iron Man",
    "injury_risk": "Safe",
    "pitch1_name": "4-Seam Fastball",
    "pitch2_name": "Curveball",
    "pitch3_name": "Changeup",
    "pitch4_name": null,
    "pitch5_name": null
  },
  "attributes": {
    "contact_base": 55.3,
    "power_base": 48.7,
    "discipline_base": 42.1,
    "eye_base": 50.0,
    "speed_base": 38.5,
    "baserunning_base": 35.2,
    "basereaction_base": 40.0,
    "fieldcatch_base": 52.1,
    "fieldreact_base": 45.0,
    "fieldspot_base": 48.3,
    "throwpower_base": 44.7,
    "throwacc_base": 46.2,
    "catchframe_base": 10.0,
    "catchsequence_base": 12.0,
    "pendurance_base": 5.0,
    "pgencontrol_base": 3.0,
    "pthrowpower_base": 8.0,
    "psequencing_base": 4.0,
    "pickoff_base": 2.0,
    "pitch1_ovr": 20.0,
    "pitch2_ovr": 15.0,
    "pitch3_ovr": 12.0,
    "pitch4_ovr": 0.0,
    "pitch5_ovr": 0.0
  },
  "potentials": {
    "contact_pot": "A-",
    "power_pot": "B+",
    "discipline_pot": "B",
    "eye_pot": "A",
    "speed_pot": "B-",
    "...": "all _pot columns"
  },
  "visibility": {
    "pool": "mlb_fa",
    "unlocked": [],
    "available_actions": []
  }
}
```

**What to render:** Full player card — numeric attributes, potential grades, bio. No unlock buttons needed.

### 6.3 Alternatively: Raw Player Data

#### `GET /players/<player_id>/`

Returns the complete raw database row for a player (all 100+ columns from `simbbPlayers`). Use this for players already on your roster, or if you need columns not included in the scouting player endpoint.

**Response (200):**

```json
[
  {
    "id": 9999,
    "firstname": "Mike",
    "lastname": "Johnson",
    "age": 28,
    "ptype": "Position",
    "contact_base": 55.3,
    "contact_pot": "A-",
    "...": "every column from simbbPlayers"
  }
]
```

Note: Returns an **array** with a single element (or empty array if not found).

### 6.4 Check Signing Budget

#### `GET /transactions/signing-budget/<org_id>?league_year_id=<ly_id>`

Check how much money (not scouting points) an org has available for signing contracts.

**Response (200):**

```json
{
  "org_id": 1,
  "available_budget": 15000000.00
}
```

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | int | Organization ID |
| `available_budget` | float | Available signing bonus budget (dollars). Calculated as seed capital + ledger balance - committed bonuses this year. |

### 6.5 Sign a Free Agent

#### `POST /transactions/sign`

**Request Body:**

```json
{
  "player_id": 9999,
  "org_id": 1,
  "years": 3,
  "salaries": [5000000, 5500000, 6000000],
  "bonus": 1000000,
  "level_id": 9,
  "league_year_id": 1,
  "game_week_id": 1,
  "executed_by": "gm_username"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `player_id` | int | Yes | Player to sign |
| `org_id` | int | Yes | Signing organization |
| `years` | int | Yes | Contract length |
| `salaries` | array of numbers | Yes | Per-year salary amounts. Array length must match `years`. |
| `bonus` | number | Yes | Signing bonus (can be 0) |
| `level_id` | int | Yes | Level to assign player to (1=HS, 2=INTAM, 3=College, 4=Scraps, 5=A, 6=High-A, 7=AA, 8=AAA, 9=MLB) |
| `league_year_id` | int | Yes | Current league year (body or query param) |
| `game_week_id` | int | Yes | Current game week (body or query param) |
| `executed_by` | string | No | Username performing the action |

**Response (200):**

```json
{
  "transaction_id": 42,
  "contract_id": 789,
  "player_id": 9999,
  "years": 3,
  "bonus": 1000000.0,
  "roster_warning": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `transaction_id` | int | ID in `transaction_log` table |
| `contract_id` | int | The new contract created |
| `player_id` | int | The signed player |
| `years` | int | Contract length |
| `bonus` | float | Signing bonus amount |
| `roster_warning` | object or null | Non-null if the org's roster at the target level is now over the limit. Contains roster count details. |

**Error Responses:**

```json
{ "error": "missing_fields", "fields": ["player_id", "org_id", "years", "salaries", "bonus"] }
{ "error": "missing_fields", "fields": ["league_year_id", "game_week_id", "level_id"] }
{ "error": "validation", "message": "Player already has an active contract" }
{ "error": "validation", "message": "Salary array length must match years" }
```

---

## 7. Scouting Budget & Action History

### 7.1 Check Scouting Budget

#### `GET /scouting/budget/<org_id>?league_year_id=<ly_id>`

Check an org's scouting point balance. Budget is auto-created on first access.

**Response (200):**

```json
{
  "org_id": 50,
  "league_year_id": 1,
  "total_points": 500,
  "spent_points": 35,
  "remaining_points": 465
}
```

### Budget defaults

| Org Type | Points Per Year | Can Scout |
|----------|----------------|-----------|
| MLB (1-30) | 1000 | College and INTAM 18+ players |
| College (31-338) | 500 | HS players |

### Action costs

| Action | Cost | Target Pool | Who Can Use |
|--------|------|-------------|-------------|
| `hs_report` | 10 pts | HS | College orgs |
| `hs_potential` | 25 pts | HS | College orgs |
| `pro_numeric` | 15 pts | College / INTAM | MLB orgs |

### Budget math examples

**College org (500 pts/year):**
- Full scout 1 HS player (report + potentials) = 35 pts → can fully scout ~14 players
- Report-only on 50 players = 500 pts → then selectively unlock potentials

**MLB org (1000 pts/year):**
- Unlock numeric attributes on 1 player = 15 pts → can fully scout ~66 players

### Configurable values

All costs and budget amounts are in the `scouting_config` table (admin-tunable, no code deploy needed):

| Config Key | Default | Description |
|------------|---------|-------------|
| `mlb_budget_per_year` | 1000 | Points per MLB org per year |
| `college_budget_per_year` | 500 | Points per college org per year |
| `hs_report_cost` | 10 | Text report unlock cost |
| `hs_potential_cost` | 25 | Potential grades unlock cost |
| `pro_numeric_cost` | 15 | Numeric attributes unlock cost |

Budget resets per league year. A new row is auto-created when any endpoint first accesses that org's budget for a given league year.

### 7.2 Scouting Action History

#### `GET /scouting/actions/<org_id>?league_year_id=<ly_id>`

List all scouting actions taken by an org in a league year, with current budget.

**Response (200):**

```json
{
  "org_id": 50,
  "league_year_id": 1,
  "budget": {
    "total_points": 500,
    "spent_points": 35,
    "remaining_points": 465
  },
  "actions": [
    {
      "id": 1,
      "player_id": 1234,
      "action_type": "hs_report",
      "points_spent": 10,
      "created_at": "2026-03-01T12:00:00",
      "player_name": "John Smith",
      "ptype": "Position",
      "age": 17
    },
    {
      "id": 2,
      "player_id": 1234,
      "action_type": "hs_potential",
      "points_spent": 25,
      "created_at": "2026-03-01T12:05:00",
      "player_name": "John Smith",
      "ptype": "Position",
      "age": 17
    }
  ]
}
```

---

## 8. Contract Management Endpoints

These endpoints are relevant when evaluating players for signing or managing your roster.

### 8.1 Contract Status (Single Player)

#### `GET /transactions/contract-status/<player_id>`

Get enriched contract + service time info for a specific player.

**Response (200):**

```json
{
  "player_id": 9999,
  "player_name": "Mike Johnson",
  "age": 28,
  "contract_id": 456,
  "current_level": 9,
  "years": 5,
  "current_year": 3,
  "years_remaining": 2,
  "salary": 5500000.0,
  "is_extension": false,
  "on_ir": false,
  "mlb_service_years": 4,
  "contract_phase": "arb_eligible",
  "years_to_arb": 0,
  "years_to_fa": 2,
  "is_expiring": false,
  "has_extension": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | int | Player ID |
| `player_name` | string | Full name |
| `age` | int | Current age |
| `contract_id` | int | Active contract ID |
| `current_level` | int | Level ID (1-9) |
| `years` | int | Total contract years |
| `current_year` | int | Which year of contract |
| `years_remaining` | int | Years left on deal |
| `salary` | float | Current year salary |
| `is_extension` | bool | Whether this is an extension contract |
| `on_ir` | bool | Currently on injured reserve |
| `mlb_service_years` | int | MLB-level service time |
| `contract_phase` | string | `"minor"`, `"pre_arb"`, `"arb_eligible"`, or `"fa_eligible"` |
| `years_to_arb` | int or null | Years until arbitration eligibility |
| `years_to_fa` | int or null | Years until free agency eligibility |
| `is_expiring` | bool | True if in final year of contract |
| `has_extension` | bool | Whether an extension contract exists |

**Error (404):** `{ "error": "not_found", "message": "No active contract found" }`

### 8.2 Org Contract Overview

#### `GET /transactions/contract-overview/<org_id>`

All active contracts held by an org, sorted by level (DESC) then name.

**Response (200):**

```json
[
  {
    "player_id": 9999,
    "player_name": "Mike Johnson",
    "age": 28,
    "position": "Position",
    "contract_id": 456,
    "current_level": 9,
    "years": 5,
    "current_year": 3,
    "years_remaining": 2,
    "salary": 5500000.0,
    "on_ir": false,
    "mlb_service_years": 4,
    "contract_phase": "arb_eligible",
    "years_to_arb": 0,
    "years_to_fa": 2,
    "is_expiring": false
  },
  { "...more players..." }
]
```

### 8.3 Payroll Projection

#### `GET /transactions/payroll-projection/<org_id>`

Multi-year salary projection for an org. Useful when evaluating how much cap space exists for free agent signings.

### 8.4 Release a Player

#### `POST /transactions/release`

Release a player from their contract, making them a free agent.

**Request Body:**

```json
{
  "contract_id": 456,
  "org_id": 1,
  "league_year_id": 1,
  "executed_by": "gm_username"
}
```

### 8.5 Transaction Log

#### `GET /transactions/log`

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `org_id` | int | — | Filter to specific org |
| `type` | string | — | Filter by transaction type |
| `league_year_id` | int | — | Filter to specific league year |
| `limit` | int | 100 | Max results returned |

---

## 9. Full Workflow Examples

### College recruiting an HS player

```
1. GET /scouting/budget/50?league_year_id=1
   → 500 pts total, 0 spent

2. GET /scouting/college-pool?age=17&ptype=Position&sort=lastname&page=1
   → Browse senior position players. See their names, bio, area.
   → Pick a player to investigate (id: 1234)

3. GET /scouting/player/1234?org_id=50&league_year_id=1
   → See bio + deterministic season stats. Attributes hidden. Potentials hidden.
   → visibility.available_actions = ["hs_report"]

4. POST /scouting/action
   { "org_id": 50, "league_year_id": 1, "player_id": 1234, "action_type": "hs_report" }
   → Spend 10 pts. Status: "unlocked"

5. GET /scouting/player/1234?org_id=50&league_year_id=1
   → Now includes text_report (batting, fielding, athletic profiles)
   → visibility.available_actions = ["hs_potential"]

6. POST /scouting/action
   { "org_id": 50, "league_year_id": 1, "player_id": 1234, "action_type": "hs_potential" }
   → Spend 25 pts. Status: "unlocked"

7. GET /scouting/player/1234?org_id=50&league_year_id=1
   → Now includes text_report + potentials (letter grades for all abilities)
   → visibility.available_actions = [] (fully scouted)

8. POST /transactions/sign
   { "player_id": 1234, "org_id": 50, "years": 4, "salaries": [0,0,0,0],
     "bonus": 0, "level_id": 3, "league_year_id": 1, "game_week_id": 1 }
   → Player signed to college org

9. GET /scouting/budget/50?league_year_id=1
   → 500 total, 35 spent, 465 remaining
```

### MLB org scouting a college player

```
1. GET /scouting/pro-pool?ptype=Pitcher&sort=pthrowpower_base&dir=desc&page=1
   → Browse top pitchers by throw power.
   → Frontend shows _base values as letter grades in table view.

2. GET /scouting/player/5678?org_id=1&league_year_id=1
   → See bio + letter grades for all attributes.
   → visibility.available_actions = ["pro_numeric"]

3. POST /scouting/action
   { "org_id": 1, "league_year_id": 1, "player_id": 5678, "action_type": "pro_numeric" }
   → Spend 15 pts. Status: "unlocked"

4. GET /scouting/player/5678?org_id=1&league_year_id=1
   → Now includes letter_grades + attributes (actual numeric values)
   → visibility.available_actions = []

5. POST /transactions/sign
   { "player_id": 5678, "org_id": 1, "years": 6,
     "salaries": [500000,500000,500000,500000,500000,500000],
     "bonus": 2000000, "level_id": 5,
     "league_year_id": 1, "game_week_id": 1 }
   → Player drafted/signed to MLB org's A-ball team
```

### MLB org signing an INTAM player

```
1. GET /scouting/pro-pool?min_age=18&search=Martinez&page=1
   → Find INTAM players matching search.

2. GET /scouting/player/6789?org_id=1&league_year_id=1
   → Bio + letter grades + counting_stats (slash line or W-L/ERA/K/BB/IP)
   → visibility.pool = "intam", available_actions = ["pro_numeric"]

3. POST /scouting/action
   { "org_id": 1, "league_year_id": 1, "player_id": 6789, "action_type": "pro_numeric" }
   → 15 pts → "unlocked"

4. GET /scouting/player/6789?org_id=1&league_year_id=1
   → Now includes full numeric attributes alongside letter grades + stats

5. GET /transactions/signing-budget/1?league_year_id=1
   → Check financial budget: { "available_budget": 15000000.00 }

6. POST /transactions/sign
   { "player_id": 6789, "org_id": 1, "years": 5,
     "salaries": [500000,500000,500000,500000,500000],
     "bonus": 3000000, "level_id": 5,
     "league_year_id": 1, "game_week_id": 1 }
   → Signed
```

### Signing an MLB free agent

```
1. GET /transactions/free-agents
   → List of unsigned players: [{ player_id, player_name, age, position }]

2. GET /scouting/player/9999?org_id=1&league_year_id=1
   → Full visibility: bio + attributes + potentials. No scouting needed.
   → visibility.pool = "mlb_fa", available_actions = []

3. GET /transactions/signing-budget/1?league_year_id=1
   → { "available_budget": 15000000.00 }

4. GET /transactions/contract-overview/1
   → Check current roster contracts to plan for the signing

5. POST /transactions/sign
   { "player_id": 9999, "org_id": 1, "years": 3,
     "salaries": [5000000, 5500000, 6000000], "bonus": 1000000,
     "level_id": 9, "league_year_id": 1, "game_week_id": 1 }
   → { "transaction_id": 42, "contract_id": 789, "roster_warning": null }
```

---

## 10. Data Reference

### Bio fields (always visible)

| Field | Type | Example |
|-------|------|---------|
| `id` | int | 1234 |
| `firstname` | string | "John" |
| `lastname` | string | "Smith" |
| `age` | int | 20 |
| `ptype` | string | "Position" or "Pitcher" |
| `area` | string | "California" |
| `city` | string | "Los Angeles" |
| `intorusa` | string | "usa" or "international" |
| `height` | int | 73 (inches) |
| `weight` | int | 205 (lbs) |
| `bat_hand` | string | "R", "L", or "S" (switch) |
| `pitch_hand` | string | "R" or "L" |
| `arm_angle` | string | "3/4's", "Overhead", "Sidearm", "Submarine" |
| `durability` | string | "Iron Man", "Dependable", "Normal", "Undependable", "Tires Easily" |
| `injury_risk` | string | "Safe", "Dependable", "Normal", "Risky", "Volatile" |
| `pitch1_name` through `pitch5_name` | string or null | "4-Seam Fastball", "Slider", etc. |

### Standard abilities (19 total)

| Ability | Column Prefix | Class | Applies To |
|---------|---------------|-------|------------|
| Contact | `contact` | Batting | Position |
| Power | `power` | Batting | Position |
| Discipline | `discipline` | Batting | Position |
| Eye | `eye` | Batting | Position |
| Speed | `speed` | Athletic | Both |
| Baserunning | `baserunning` | Athletic | Both |
| Base Reaction | `basereaction` | Athletic | Both |
| Field Catch | `fieldcatch` | Fielding | Position |
| Field React | `fieldreact` | Fielding | Position |
| Field Spot | `fieldspot` | Fielding | Position |
| Throw Power | `throwpower` | Throwing | Position |
| Throw Accuracy | `throwacc` | Throwing | Position |
| Catch Framing | `catchframe` | Catching | Catcher |
| Catch Sequencing | `catchsequence` | Catching | Catcher |
| P. Endurance | `pendurance` | Pitching | Pitcher |
| P. Gen Control | `pgencontrol` | Pitching | Pitcher |
| P. Throw Power | `pthrowpower` | Pitching | Pitcher |
| P. Sequencing | `psequencing` | Pitching | Pitcher |
| Pickoff | `pickoff` | Pitching | Pitcher |

Each ability has two DB columns:
- `{ability}_base` — numeric value (float, 0-80+ range)
- `{ability}_pot` — potential grade (string: A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)

### Pitch sub-abilities (5 pitches x 4 each = 20)

Each pitch slot (`pitch1` through `pitch5`) has:
- `{slot}_pacc_base` / `_pot` — Pitch Accuracy
- `{slot}_pcntrl_base` / `_pot` — Pitch Control
- `{slot}_pbrk_base` / `_pot` — Pitch Break
- `{slot}_consist_base` / `_pot` — Consistency
- `{slot}_ovr` — Overall (computed from the 4 sub-ability base values)
- `{slot}_name` — Pitch type name (e.g., "4-Seam Fastball", "Slider")

### Potential grade scale (best to worst)

```
A+  A  A-  B+  B  B-  C+  C  C-  D+  D  D-  F
```

### Letter grade thresholds

For converting `_base` numeric values to letter grades (used in college/INTAM default visibility). Based on the 20-80 scouting scale:

| 20-80 Score | Letter Grade |
|-------------|-------------|
| 80 | A+ |
| 75 | A |
| 70 | A- |
| 65 | B+ |
| 60 | B |
| 55 | B- |
| 50 | C+ |
| 45 | C |
| 40 | C- |
| 35 | D+ |
| 30 | D |
| 25 | D- |
| 20 | F |

The backend converts raw `_base` values to the 20-80 scale using z-scores: `score = 50 + (z / 3) * 30`, rounded to nearest 5, clamped to 20-80. Default parameters: mean=30, std=12.

### Generated stat fields

**Position Player Batting:**
`games, at_bats, hits, doubles, triples, home_runs, rbi, runs, walks, strikeouts, stolen_bases, caught_stealing, avg, obp, slg`

**Pitcher:**
`games, games_started, wins, losses, era, innings_pitched, innings_pitched_outs, hits_allowed, runs_allowed, earned_runs, walks, strikeouts, home_runs_allowed, saves, k_per_9, bb_per_9, whip`

**Fielding:**
`games, innings, putouts, assists, errors, fielding_pct`

Stats are **deterministic** — the same player ID always produces identical stats on every call. No database storage; generated on-the-fly from player attributes.

### Level IDs

| ID | Level |
|----|-------|
| 1 | High School |
| 2 | INTAM |
| 3 | College |
| 4 | Scraps |
| 5 | A |
| 6 | High-A |
| 7 | AA |
| 8 | AAA |
| 9 | MLB |

### Allowed sort columns

Both pool endpoints accept these values for the `sort` parameter:

```
lastname, firstname, age, ptype, area, height, weight, displayovr,
contact_base, power_base, discipline_base, eye_base, speed_base,
baserunning_base, basereaction_base, throwpower_base, throwacc_base,
fieldcatch_base, fieldreact_base, fieldspot_base,
catchframe_base, catchsequence_base,
pendurance_base, pgencontrol_base, pthrowpower_base,
psequencing_base, pickoff_base
```

Any unrecognized sort value falls back to `lastname`.

### Error response format

All error responses follow this shape:

```json
{
  "error": "error_code",
  "message": "Human-readable description"
}
```

Common error codes: `missing_fields`, `validation`, `not_found`, `db_error`

### Quick endpoint reference

| Method | Endpoint | Section | Purpose |
|--------|----------|---------|---------|
| GET | `/scouting/college-pool` | [4.1](#41-browse-hs-players) | Browse HS players for college recruiting |
| GET | `/scouting/pro-pool` | [5.1](#51-browse-draft-eligible-players) | Browse college/INTAM players for pro scouting |
| GET | `/scouting/player/<id>` | [4.2](#42-view-individual-hs-player), [5.2](#52-view-individual-collegeintam-player), [6.2](#62-view-free-agent-profile) | Visibility-masked player profile |
| POST | `/scouting/action` | [4.3](#43-unlock-hs-player-information), [5.3](#53-unlock-pro-scouting-data) | Spend scouting points to unlock data |
| GET | `/scouting/budget/<org_id>` | [7.1](#71-check-scouting-budget) | Check scouting point balance |
| GET | `/scouting/actions/<org_id>` | [7.2](#72-scouting-action-history) | Scouting action history |
| GET | `/transactions/free-agents` | [6.1](#61-browse-free-agents) | List unsigned MLB players |
| GET | `/transactions/signing-budget/<org_id>` | [6.4](#64-check-signing-budget) | Check financial signing budget |
| POST | `/transactions/sign` | [4.4](#44-sign-hs-player-to-college), [5.4](#54-draftsign-a-scouted-player), [6.5](#65-sign-a-free-agent) | Sign any player to a contract |
| GET | `/transactions/contract-status/<player_id>` | [8.1](#81-contract-status-single-player) | Player contract + service time |
| GET | `/transactions/contract-overview/<org_id>` | [8.2](#82-org-contract-overview) | All org contracts |
| GET | `/transactions/log` | [8.5](#85-transaction-log) | Transaction history |
| POST | `/transactions/release` | [8.4](#84-release-a-player) | Release player from contract |
| GET | `/players/<id>/` | [6.3](#63-alternatively-raw-player-data) | Raw player data (all columns) |
