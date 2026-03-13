# Scouting & Recruiting — Frontend Integration Guide

## Table of Contents

1. [Data Shape Comparison: Rosters vs Scouting Pools](#1-data-shape-comparison)
2. [Current Shape Differences (and What We're Changing)](#2-current-shape-differences)
3. [Scouting Player Modal — Full Detail](#3-scouting-player-modal)
4. [Draft Scouting Page — Data Sources](#4-draft-scouting-page)
5. [HS Generated Stats — How They Work](#5-hs-generated-stats)
6. [Recruiting System — Endpoint Reference](#6-recruiting-system)

---

## 1. Data Shape Comparison

### Roster Endpoint Shape (`GET /api/v1/orgs/<abbrev>/roster`)

Player objects are **nested** into four sections:

```json
{
  "id": 12345,
  "org_abbrev": "NYY",
  "league_level": "mlb",
  "current_level": 9,
  "team_abbrev": "NYY",

  "bio": {
    "id": 12345,
    "firstname": "Aaron",
    "lastname": "Judge",
    "age": 28,
    "ptype": "Position",
    "area": "USA",
    "city": "Linden",
    "intorusa": "USA",
    "height": 82,
    "weight": 282,
    "bat_hand": "R",
    "pitch_hand": null,
    "arm_angle": null,
    "durability": "Iron Man",
    "injury_risk": "Low",
    "displayovr": "80",
    "left_split": 0.12,
    "center_split": 0.45,
    "right_split": 0.43,
    "pitch1_name": null,
    "pitch2_name": null,
    "contact_base": 72.1,
    "power_base": 78.9
  },

  "ratings": {
    "contact_display": 65,
    "power_display": 70,
    "pitch1_ovr": null,
    "c_rating": 40,
    "fb_rating": 55
  },

  "potentials": {
    "contact_pot": "A",
    "power_pot": "A+"
  },

  "contract": {
    "id": 5001,
    "years": 6,
    "current_year": 2,
    "current_year_detail": {
      "base_salary": 15000000,
      "salary_share": 0.65
    }
  }
}
```

### Current Scouting Pool Shape (`GET /api/v1/scouting/college-pool`, etc.)

Player objects are **flat** — all fields at root level:

```json
{
  "id": 12345,
  "firstname": "John",
  "lastname": "Smith",
  "age": 17,
  "ptype": "Pitcher",
  "area": "USA",
  "city": "Dallas",
  "intorusa": "USA",
  "height": 74,
  "weight": 185,
  "bat_hand": "R",
  "pitch_hand": "R",
  "arm_angle": "Over the Top",
  "durability": "Normal",
  "injury_risk": "Low",
  "displayovr": "55",
  "left_split": 0.33,
  "center_split": 0.34,
  "right_split": 0.33,
  "contact_base": null,
  "power_base": null,
  "contact_pot": "?",
  "power_pot": "?",
  "pitch1_name": "Fastball",
  "pitch1_ovr": null,
  "pitch1_consist_base": null,
  "org_id": 340,
  "org_abbrev": "USHS"
}
```

### Key Differences

| Aspect | Roster Endpoint | Scouting Pool Endpoints |
|---|---|---|
| **Structure** | Nested: `bio`, `ratings`, `potentials`, `contract` | Flat: all fields at root |
| **Attribute display** | `_display` keys (20-80 scale) in `ratings` | Raw `_base` values (or `null` / fuzzed letter grades) |
| **Derived ratings** | `c_rating`, `fb_rating`, `pitch1_ovr` in `ratings` | `pitch1_ovr` at root, no position ratings |
| **Contract data** | Full contract object | Not included |
| **Org metadata** | `org_abbrev`, `league_level`, `team_abbrev` at root | `org_id`, `org_abbrev` at root |
| **Potential format** | Letter grades in `potentials` dict | Letter grades at root (`_pot` suffix) |

---

## 2. Current Shape Differences (and What We're Changing)

### What the Pool Endpoints Will NOT Include (by design)

These fields are specific to the roster context and don't belong in scouting pools:

- **`contract`** — HS/college/INTAM players don't have salary contracts
- **`team_abbrev`** — scouting targets aren't on "teams" in the roster sense
- **`league_level`** (string) — pools already imply the level context

### What the Pool Endpoints DO Include That Roster Doesn't

- **`org_id`** — the holding organization ID (340 for HS, 31-338 for college, etc.)
- **Pool-level metadata**: `age_counts` (college-pool), `level_counts` (mlb-pool)

### Attribute Representation by Pool

The fog-of-war system means attribute values vary by pool and viewing context:

| Pool | `_base` fields | `_pot` fields | Notes |
|---|---|---|---|
| **HS** (college-pool) | `null` | `"?"` | Attributes hidden; must unlock via scouting actions |
| **College** (pro-pool) | Fuzzed letter grade (`"B+"`, `"C-"`) | Fuzzed letter grade | Deterministic per viewing org |
| **INTAM** (intam-pool, pro-pool) | Fuzzed letter grade | Fuzzed letter grade | Same fuzzing as college |
| **Pro** (mlb-pool) | Fuzzed letter grade | Fuzzed letter grade | Same fuzzing as college |
| **Own roster** (roster endpoint) | Numeric 20-80 in `ratings` | Precise letter grade | Full visibility for your own players |

**The fuzzing is deterministic**: Org 45 viewing Player 12345's `contact_base` will always see the same fuzzed grade, every time. But Org 72 will see a different fuzzed grade for the same player+attribute.

---

## 3. Scouting Player Modal

### Endpoint: `GET /api/v1/scouting/player/<player_id>?org_id=X&league_year_id=X`

This is the full detail endpoint when a user clicks a player card. The response shape depends on the player's pool and the requesting org's unlocked scouting actions.

### Response Shape

```json
{
  "bio": {
    "id": 12345,
    "firstname": "John",
    "lastname": "Smith",
    "age": 17,
    "ptype": "Pitcher",
    "area": "USA",
    "city": "Dallas",
    "intorusa": "USA",
    "height": 74,
    "weight": 185,
    "bat_hand": "R",
    "pitch_hand": "R",
    "arm_angle": "Over the Top",
    "durability": "Normal",
    "injury_risk": "Low",
    "pitch1_name": "Fastball",
    "pitch2_name": "Curveball",
    "pitch3_name": null,
    "pitch4_name": null,
    "pitch5_name": null
  },

  "visibility": {
    "pool": "hs",
    "unlocked": ["hs_report", "recruit_potential_fuzzed"],
    "available_actions": ["recruit_potential_precise"]
  },

  // --- Pool-specific sections (see below) ---
}
```

### HS Pool Player (college org viewing)

| Section | When Visible | Content |
|---|---|---|
| `bio` | Always | Name, age, ptype, physical traits, pitch names |
| `generated_stats` | Always | Simulated season batting/pitching/fielding stats |
| `text_report` | After `hs_report` unlocked ($10) | Prose scouting report with sections: batting, fielding, athletic, pitching |
| `potentials` | Tiered: `"?"` → fuzzed → precise | Based on `recruit_potential_fuzzed` ($15) / `recruit_potential_precise` ($25) |

```json
{
  "bio": { ... },
  "generated_stats": {
    "batting": {
      "games": 28, "at_bats": 90, "hits": 27, "doubles": 6,
      "triples": 1, "home_runs": 4, "rbi": 18, "runs": 16,
      "walks": 8, "strikeouts": 21, "stolen_bases": 3, "caught_stealing": 1,
      "avg": 0.300, "obp": 0.368, "slg": 0.456
    },
    "fielding": {
      "games": 28, "innings": 182, "putouts": 95, "assists": 45,
      "errors": 3, "fielding_pct": 0.978
    }
  },
  "text_report": {
    "batting": "Exceptional bat speed and barrel control. Projects as a plus hitter.",
    "fielding": "Solid defender with accurate arm. Reliable positioning.",
    "athletic": "Plus runner with good first-step quickness.",
    "pitching": null
  },
  "potentials": {
    "contact_pot": "B+",
    "power_pot": "?",
    "speed_pot": "A-"
  },
  "visibility": {
    "pool": "hs",
    "unlocked": ["hs_report", "recruit_potential_fuzzed"],
    "available_actions": ["recruit_potential_precise"]
  }
}
```

### College/INTAM Pool Player (any org viewing)

| Section | When Visible | Content |
|---|---|---|
| `bio` | Always | Name, age, ptype, physical traits, pitch names |
| `letter_grades` | Always | Fuzzed letter grades for all `_base` attributes (key is attr name without `_base` suffix) |
| `counting_stats` | INTAM only, always | Generated season stats |
| `attributes` | After `draft_attrs_fuzzed` ($10) or `draft_attrs_precise` ($20) | Raw numeric `_base` values + `pitch_ovr` values |
| `display_format` | With attributes | `"20-80"` (precise) or `"20-80-fuzzed"` (fuzzed unlock) |
| `potentials` | Tiered | Fuzzed by default, precise after `draft_potential_precise` ($15) or `college_potential_precise` ($15) |

```json
{
  "bio": { ... },
  "letter_grades": {
    "contact": "B+",
    "power": "C",
    "discipline": "B-",
    "eye": "C+",
    "speed": "B",
    "pendurance": "A-",
    "pgencontrol": "B",
    "pitch1_consist": "B+",
    "pitch1_pacc": "A-",
    "pitch1_pbrk": "B",
    "pitch1_pcntrl": "B+"
  },
  "attributes": {
    "contact_base": 45.2,
    "power_base": 38.7,
    "pitch1_ovr": 62.3
  },
  "display_format": "20-80",
  "potentials": {
    "contact_pot": "A",
    "power_pot": "B+"
  },
  "counting_stats": {
    "batting": { ... },
    "fielding": { ... }
  },
  "visibility": {
    "pool": "college",
    "unlocked": ["draft_attrs_precise", "draft_potential_precise"],
    "available_actions": []
  }
}
```

### Pro Pool Player (any org viewing)

| Section | When Visible | Content |
|---|---|---|
| `bio` | Always | Name, age, ptype, physical traits, pitch names |
| `attributes` | Always (fuzzed or precise) | Raw numeric `_base` values + `pitch_ovr` values |
| `display_format` | Always | `"20-80"` after `pro_attrs_precise` ($15), otherwise `"20-80-fuzzed"` |
| `potentials` | Always (fuzzed or precise) | Precise after `pro_potential_precise` ($15) |

```json
{
  "bio": { ... },
  "attributes": {
    "contact_base": 72.1,
    "power_base": 68.4,
    "pitch1_ovr": 75.2,
    "c_rating": null,
    "fb_rating": null
  },
  "display_format": "20-80-fuzzed",
  "potentials": {
    "contact_pot": "A-",
    "power_pot": "B+"
  },
  "visibility": {
    "pool": "pro",
    "unlocked": [],
    "available_actions": ["pro_attrs_precise", "pro_potential_precise"]
  }
}
```

### Scouting Action Cost Summary

Use `visibility.available_actions` to show "Unlock" buttons in the modal.

| Action | Cost | Who Can Use | Target | Prerequisite |
|---|---|---|---|---|
| `hs_report` | 10 | College orgs (31-338) | HS players (org 340) | None |
| `recruit_potential_fuzzed` | 15 | College orgs | HS players | `hs_report` |
| `recruit_potential_precise` | 25 | College orgs | HS players | `recruit_potential_fuzzed` |
| `college_potential_precise` | 15 | Any org | College players (31-338) | None |
| `draft_attrs_fuzzed` | 10 | MLB orgs (1-30) | College/INTAM players | None |
| `draft_attrs_precise` | 20 | MLB orgs | College/INTAM players | `draft_attrs_fuzzed` |
| `draft_potential_precise` | 15 | MLB orgs | College/INTAM players | None |
| `pro_attrs_precise` | 15 | Any org | Pro players (levels 4-9) | None |
| `pro_potential_precise` | 15 | Any org | Pro players | None |

### Performing a Scouting Action

```
POST /api/v1/scouting/action
Body: { "org_id": 45, "league_year_id": 5, "player_id": 12345, "action_type": "hs_report" }

Response: {
  "status": "unlocked",        // or "already_unlocked"
  "action_type": "hs_report",
  "player_id": 12345,
  "points_spent": 10,          // 0 if already_unlocked
  "points_remaining": 490
}
```

### Checking Scouting Budget

```
GET /api/v1/scouting/budget?org_id=45&league_year_id=5

Response: {
  "org_id": 45,
  "league_year_id": 5,
  "total_points": 500,
  "spent_points": 10
}
```

---

## 4. Draft Scouting Page

The "draft scouting" page shows college-eligible and INTAM players that MLB teams can evaluate for the draft.

### Primary Data Source: `GET /api/v1/scouting/pro-pool`

This is the combined pool endpoint that returns both college AND INTAM players.

#### Query Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `league_year_id` | int | required | League year |
| `viewing_org_id` | int | recommended | MLB org viewing (controls fog-of-war fuzz) |
| `page` | int | 1 | Page number |
| `per_page` | int | 50 | Results per page (max 200) |
| `ptype` | string | — | `"Pitcher"` or `"Position"` |
| `area` | string | — | Filter by area/country |
| `search` | string | — | Name search (min 2 chars) |
| `min_age` / `max_age` | int | — | Age range filter |
| `org_id` | int | — | Filter by holding org (e.g., `339` for INTAM only) |
| `sort` | string | `"lastname"` | Sort column (see allowed sorts below) |
| `dir` | string | `"asc"` | Sort direction |

#### Response

```json
{
  "total": 2400,
  "page": 1,
  "per_page": 50,
  "pages": 48,
  "players": [
    {
      "id": 23456,
      "firstname": "Carlos",
      "lastname": "Martinez",
      "age": 21,
      "ptype": "Pitcher",
      "area": "Dominican Republic",
      "displayovr": "62",
      "contact_base": "C+",
      "power_base": "B-",
      "contact_pot": "B",
      "power_pot": "A-",
      "pitch1_name": "Fastball",
      "pitch1_ovr": null,
      "org_id": 339,
      "org_abbrev": "INTAM"
    }
  ]
}
```

Note: `_base` fields are fuzzed letter grades when `viewing_org_id` is provided. Without it, they're raw numeric values (admin/debug only).

### Alternative: Separate Pool Endpoints

If you want to show INTAM and college players in separate tabs:

- **INTAM only:** `GET /api/v1/scouting/intam-pool?league_year_id=X&viewing_org_id=Y`
- **College eligible:** Use pro-pool with org filter: `GET /api/v1/scouting/pro-pool?league_year_id=X&viewing_org_id=Y&org_id=31` (or iterate 31-338)

The `pro-pool` endpoint returns BOTH college and INTAM together, which is usually what the draft page wants.

### Allowed Sort Columns

```
lastname, firstname, age, ptype, area, height, weight, displayovr,
contact_base, power_base, discipline_base, eye_base, speed_base,
baserunning_base, basereaction_base, throwpower_base, throwacc_base,
fieldcatch_base, fieldreact_base, fieldspot_base, catchframe_base,
catchsequence_base, pendurance_base, pgencontrol_base, pthrowpower_base,
psequencing_base, pickoff_base
```

---

## 5. HS Generated Stats

### How They Work

HS stats are **not from real games** — they are **deterministically generated on-the-fly** from the player's base attributes. There is no "PoolPlayer" class or stored stat table for HS players.

### Generation Process

1. Player's `_base` attributes are read from `simbbPlayers`
2. A random seed is set to `player_id` (deterministic: same player always produces same stats)
3. Attributes are normalized against a level-specific cap
4. Statistical formulas convert attributes to realistic season lines
5. Gaussian noise is added (but deterministic via the seed)

### What Drives the Stats

**For Position Players:**

| Attribute | Drives |
|---|---|
| `contact_base` | Batting average, hit rate |
| `discipline_base` | Walk rate |
| `eye_base` | Strikeout avoidance |
| `power_base` | HR rate, doubles, triples, slugging |
| `speed_base` | Stolen bases, triples |
| `fieldcatch_base` + `fieldreact_base` + `fieldspot_base` | Putouts, assists, errors, fielding % |
| `throwacc_base` | Throwing errors |

**For Pitchers:**

| Attribute | Drives |
|---|---|
| `pgencontrol_base` | Walk rate (BB/9) |
| `psequencing_base` | Hit avoidance (H/9) |
| `pthrowpower_base` | Strikeout rate (K/9) |
| `pendurance_base` | Innings per start |
| Pitch component OVRs | Composite quality factor affecting all pitching stats |

### Level Parameters

| Level | Games | AB/game | Starts | IP/start | Attr Cap |
|---|---|---|---|---|---|
| HS | 28 | 3.2 | 15 | 5.0 | 25 |
| College | 56 | 3.8 | 16 | 5.5 | 50 |
| INTAM | 50 | 3.6 | 15 | 5.0 | 50 |

The `attr_cap` controls normalization — HS stats are scaled against a lower cap (25) reflecting narrower ability distribution, while college/INTAM use 50.

### Where Generated Stats Appear

| Endpoint | When |
|---|---|
| `GET /scouting/player/<id>` | Always for HS pool (`generated_stats` section) |
| `GET /scouting/player/<id>` | INTAM pool only (`counting_stats` section) |
| Pool list endpoints | NOT included — stats are per-player detail only |

### Important: Stats Are Fake but Consistent

- Same `player_id` = same stats every time (deterministic seed)
- Stats reflect relative attribute strength (high `power_base` = more HRs)
- They are NOT from actual simulated games — no game engine involvement
- HS players don't play in the game simulation at all

---

## 6. Recruiting System

For the full recruiting system reference, see [recruiting-system.md](recruiting-system.md).

### Quick Reference: Recruiting Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/recruiting/rankings` | GET | Public star rankings (paginated) |
| `/recruiting/state` | GET | Current week/status |
| `/recruiting/invest` | POST | Submit weekly point investments |
| `/recruiting/advance-week` | POST | Admin: advance one week |
| `/recruiting/board/<org_id>` | GET | Org's recruiting board (fog-of-war) |
| `/recruiting/player/<pid>` | GET | Single player detail (fog-of-war) |
| `/recruiting/commitments` | GET | Public commitment list |

### Recruiting vs Scouting — How They Interact

These are **independent but complementary** systems with separate point budgets:

| System | Budget | Resets | Purpose |
|---|---|---|---|
| **Scouting** | 500-1000 pts/year (lump sum) | Each league year | Reveal hidden attributes and potentials |
| **Recruiting** | 100 pts/week (use-it-or-lose-it) | Each league year + each week | Compete to sign HS players |

**Typical flow for a college org:**

1. Browse HS pool via `/scouting/college-pool` — see names, ages, pitches, physical traits
2. Spend scouting points to unlock reports + potentials via `/scouting/action`
3. View star rankings via `/recruiting/rankings` (public, no cost)
4. Invest recruiting points weekly via `/recruiting/invest`
5. Monitor your board via `/recruiting/board/<org_id>`
6. See who committed via `/recruiting/commitments`

### Recruiting Player Detail

The recruiting player endpoint (`/recruiting/player/<pid>`) returns recruiting-specific data:

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

This is **separate from** the scouting player modal. To show full player info + recruiting data in the same view, make both calls:

```
GET /scouting/player/12345?org_id=45&league_year_id=5     → attributes, potentials, stats
GET /recruiting/player/12345?league_year_id=5&viewing_org_id=45  → star rating, investment, interest
```

---

## Appendix: Scouting Action Unlock Progression by Pool

### HS Player (College Org Viewing)

```
Base visibility:
  bio ✓  |  generated_stats ✓  |  attributes ✗  |  potentials: "?"

  ↓ Unlock "hs_report" (10 pts)

  bio ✓  |  generated_stats ✓  |  text_report ✓  |  potentials: "?"

  ↓ Unlock "recruit_potential_fuzzed" (15 pts, requires hs_report)

  bio ✓  |  generated_stats ✓  |  text_report ✓  |  potentials: fuzzed grades

  ↓ Unlock "recruit_potential_precise" (25 pts, requires fuzzed)

  bio ✓  |  generated_stats ✓  |  text_report ✓  |  potentials: precise grades
```

### College/INTAM Player (MLB Org Viewing)

```
Base visibility:
  bio ✓  |  letter_grades: fuzzed  |  attributes ✗  |  potentials: fuzzed

  ↓ Unlock "draft_attrs_fuzzed" (10 pts)

  bio ✓  |  letter_grades ✓  |  attributes: numeric (fuzzed display)  |  potentials: fuzzed

  ↓ Unlock "draft_attrs_precise" (20 pts, requires fuzzed)

  bio ✓  |  letter_grades ✓  |  attributes: numeric (precise 20-80)  |  potentials: fuzzed

  ↓ Unlock "draft_potential_precise" (15 pts, no prerequisite)

  bio ✓  |  letter_grades ✓  |  attributes ✓  |  potentials: precise grades
```

### Pro Player (Any Org Viewing)

```
Base visibility:
  bio ✓  |  attributes: numeric (fuzzed display)  |  potentials: fuzzed

  ↓ Unlock "pro_attrs_precise" (15 pts)

  bio ✓  |  attributes: numeric (precise 20-80)  |  potentials: fuzzed

  ↓ Unlock "pro_potential_precise" (15 pts)

  bio ✓  |  attributes: precise  |  potentials: precise grades
```
