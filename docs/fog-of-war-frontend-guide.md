# Fog-of-War Attribute Visibility System — Frontend Integration Guide

## Table of Contents

1. [Concept Overview](#1-concept-overview)
2. [How Fuzz Works](#2-how-fuzz-works)
3. [Visibility Contexts](#3-visibility-contexts)
4. [Scouting Action Types](#4-scouting-action-types)
5. [Display Format Reference](#5-display-format-reference)
6. [Endpoint Changes](#6-endpoint-changes)
7. [Scouting Workflow Sequences](#7-scouting-workflow-sequences)
8. [Response Shape Reference](#8-response-shape-reference)
9. [Frontend Rendering Rules](#9-frontend-rendering-rules)
10. [Migration Notes & Backward Compatibility](#10-migration-notes--backward-compatibility)
11. [Constants Reference](#11-constants-reference)

---

## 1. Concept Overview

Every organization now sees a **different, deterministic version** of player attributes and potentials. By default, all values are "fuzzed" — shifted from the true value by 1-3 steps. Organizations spend **scouting points** to progressively sharpen the picture, from hidden → fuzzed → precise.

Key properties:
- **Org-specific**: Org 5 and Org 12 see different fuzzed values for the same player's same attribute
- **Deterministic**: The same org always sees the same fuzzed value — it doesn't change between requests
- **Computed on the fly**: Fuzzed values are never stored. The backend computes them from true values + a hash of `(org_id, player_id, attribute_name)`
- **Cacheable**: Because fuzz is deterministic, the frontend can cache responses until a new scouting action is performed
- **Backward compatible**: Endpoints without `viewing_org_id` return true values (admin/legacy mode)

---

## 2. How Fuzz Works

### Letter Grade Fuzz
The 13-grade scale: `F, D-, D, D+, C-, C, C+, B-, B, B+, A-, A, A+`

A fuzzed grade is shifted 1-3 positions up or down from the true grade. The direction and magnitude are determined by a hash of `(org_id, player_id, attribute_name)`.

Example: True grade `B+` (index 9)
- Org 5 might see `A-` (shifted +1)
- Org 12 might see `B-` (shifted -2)
- Org 5 will **always** see `A-` for this player's this attribute

Boundary behavior: grades clamp at `F` and `A+`. A true `A+` fuzzed up still shows `A+`. A true `F` fuzzed down still shows `F`.

### 20-80 Fuzz
20-80 scores are offset by 5, 10, or 15 points (1-3 steps of 5). Direction is also deterministic.

Example: True score `60`
- Org 5 might see `70` (shifted +10)
- Org 12 might see `45` (shifted -15)

Boundary behavior: scores clamp to `[20, 80]`.

### Potential Fuzz
Potentials (`_pot` columns) use the same letter grade fuzz. When hidden, they display as `"?"`.

---

## 3. Visibility Contexts

The backend classifies every (viewing_org, player) relationship into one of four contexts:

| Context | When | Attribute Display | Potential Display |
|---|---|---|---|
| `college_recruiting` | College org (31-338) viewing HS player (org 340) | **Hidden** (`null`) | `?` → fuzzed grade → precise |
| `college_roster` | Any org viewing a college player (orgs 31-338) | **Fuzzed letter grades** (ceiling — cannot unlock further) | Fuzzed grade → precise |
| `pro_draft` | MLB org (1-30) viewing college/INTAM player | Fuzzed letter grades → **fuzzed 20-80** → **precise 20-80** | Fuzzed grade → precise |
| `pro_roster` | Any org viewing a pro player (levels 4-9) | **Fuzzed 20-80** → **precise 20-80** | Fuzzed grade → precise |

### Context Determination Logic
```
if player's holding org == 340 (USHS):
    context = "college_recruiting"
elif player's holding org in [31-338] (College) or 339 (INTAM):
    if viewing org in [1-30] (MLB):
        context = "pro_draft"
    else:
        context = "college_roster"
elif player's level in [4-9]:
    context = "pro_roster"
```

---

## 4. Scouting Action Types

### Complete List

| Action Type | Cost | Who Can Use | Target Players | Prerequisite |
|---|---|---|---|---|
| `hs_report` | 10 | College orgs (31-338) | HS (org 340) | None |
| `recruit_potential_fuzzed` | 15 | College orgs (31-338) | HS (org 340) | `hs_report` |
| `recruit_potential_precise` | 25 | College orgs (31-338) | HS (org 340) | `recruit_potential_fuzzed` |
| `college_potential_precise` | 15 | Any org | College (orgs 31-338) | None |
| `draft_attrs_fuzzed` | 10 | MLB orgs (1-30) | College/INTAM | None |
| `draft_attrs_precise` | 20 | MLB orgs (1-30) | College/INTAM | `draft_attrs_fuzzed` |
| `draft_potential_precise` | 15 | MLB orgs (1-30) | College/INTAM | None |
| `pro_attrs_precise` | 15 | Any org | Pro (levels 4-9) | None |
| `pro_potential_precise` | 15 | Any org | Pro (levels 4-9) | None |

Costs are configurable via the `scouting_config` table (admin-tunable). The values above are defaults.

### Prerequisite Chains (visual)

**College Recruiting (HS players):**
```
hs_report (10 pts)
  └─→ recruit_potential_fuzzed (15 pts)
        └─→ recruit_potential_precise (25 pts)
```

**Pro Draft Scouting (College/INTAM):**
```
draft_attrs_fuzzed (10 pts)
  └─→ draft_attrs_precise (20 pts)

draft_potential_precise (15 pts)      ← independent, no prerequisite
college_potential_precise (15 pts)    ← independent, no prerequisite
```

**Pro Roster Scouting:**
```
pro_attrs_precise (15 pts)            ← independent
pro_potential_precise (15 pts)        ← independent
```

### Carryover Rule
When a player transitions contexts (e.g., gets drafted from college to a pro roster), **all previously unlocked scouting actions for that org still apply**. If org 5 unlocked `draft_attrs_precise` during the draft process, they continue to see precise attributes when the player moves to their pro roster — no need to re-scout with `pro_attrs_precise`.

### Available Actions
The `visibility.available_actions` array in responses tells the frontend which actions the viewing org can currently perform on a player. This accounts for:
- Which actions are already unlocked
- Which prerequisites are met
- Whether the org type is permitted for that action
- The player's current pool

Use this array to render "Scout" buttons — only show actions that appear in `available_actions`.

---

## 5. Display Format Reference

The `visibility_context.display_format` field (on roster/ratings endpoints) or `display_format` field (on scouting player endpoint) tells the frontend how to render attribute values:

| Format | Value Type | When | Rendering |
|---|---|---|---|
| `"hidden"` | `null` | College recruiting, attrs not scoutable | Show `—` or empty |
| `"letter_grade"` | `string` (e.g., `"B+"`) | College roster view, unscouted draft prospects | Show the letter grade directly |
| `"20-80"` | `int` (e.g., `65`) | Pro roster precise, scouted draft prospects | Show numeric 20-80 score |
| `"20-80-fuzzed"` | `int` (e.g., `65`) | Pro roster default, fuzzed draft attrs | Show numeric score with fuzz indicator |

### Recommended Visual Treatment

| Format | Color/Style | Badge/Icon |
|---|---|---|
| `"hidden"` | Dimmed/muted | Lock icon or `—` |
| `"letter_grade"` | Normal text, grade-colored | Optional: tilde `~` prefix to indicate fuzz |
| `"20-80"` precise | Bold, confidence-colored | Checkmark or solid circle |
| `"20-80"` fuzzed | Normal text | `~` prefix or dashed underline to indicate fuzz |

### Potential Display
Potentials always display as letter grades, but have three states:

| State | Value | Rendering |
|---|---|---|
| Hidden | `"?"` | Show `?` |
| Fuzzed | `"B+"` (a letter grade, but not the true one) | Show grade with fuzz indicator |
| Precise | `"B+"` (the true grade) | Show grade with confidence indicator |

Use `visibility_context.potentials_precise` (boolean) to distinguish fuzzed from precise letter grades.

---

## 6. Endpoint Changes

### New Parameter: `viewing_org_id`

Added to these endpoints as an **optional query parameter**:

| Endpoint | Parameter |
|---|---|
| `GET /api/v1/ratings/teams` | `?viewing_org_id=<int>` |
| `GET /api/v1/orgs/<org>/ratings` | `?viewing_org_id=<int>` |
| `GET /api/v1/orgs/<org>/roster` | `?viewing_org_id=<int>` |
| `GET /api/v1/players/<id>/` | `?viewing_org_id=<int>` |
| `GET /api/v1/scouting/pro-pool` | `?viewing_org_id=<int>` |
| `GET /api/v1/scouting/college-pool` | `?viewing_org_id=<int>` |

The scouting player endpoint already uses `org_id` as a required query param, which serves the same purpose.

**How to pass it**: Use the org ID from the authenticated user's organization assignment (from `useAuthStore()` → `currentUser` → organization memberships → `mlbOrganization.id` or `collegeOrganization.id`).

**When to pass it**: Always, for non-admin views. The frontend should include `viewing_org_id` on every roster/ratings/player request where the user is viewing as their organization. Omit it only for admin dashboards or league-wide analytics.

### New Endpoint: `POST /api/v1/scouting/action/batch`

Batch-unlock the same action type for multiple players in one request.

**Request:**
```json
POST /api/v1/scouting/action/batch
Content-Type: application/json

{
  "org_id": 5,
  "league_year_id": 1,
  "player_ids": [101, 102, 103, 104, 105],
  "action_type": "pro_attrs_precise"
}
```

**Response (200):**
```json
{
  "successes": [101, 103, 105],
  "already_unlocked": [102],
  "errors": [
    { "player_id": 104, "error": "Insufficient scouting points: need 15, have 10" }
  ],
  "budget": {
    "total_points": 1000,
    "spent_points": 955,
    "remaining_points": 45
  }
}
```

**Notes:**
- Maximum 200 players per batch
- Processes in a single transaction — if a budget error occurs partway through, all prior successes in the batch still commit
- `already_unlocked` players cost nothing
- Use this for "Scout Entire Roster" or "Scout All Draft Prospects" buttons
- After a batch call, re-fetch the roster/pool data to see updated fuzzed → precise values

### Updated Endpoint: `POST /api/v1/scouting/action`

Now accepts all 9 action types (previously only accepted 3).

**Request:**
```json
POST /api/v1/scouting/action
Content-Type: application/json

{
  "org_id": 5,
  "league_year_id": 1,
  "player_id": 101,
  "action_type": "draft_attrs_fuzzed"
}
```

**Response (200 — newly unlocked):**
```json
{
  "status": "unlocked",
  "action_type": "draft_attrs_fuzzed",
  "player_id": 101,
  "points_spent": 10,
  "points_remaining": 490
}
```

**Response (200 — already unlocked):**
```json
{
  "status": "already_unlocked",
  "action_type": "draft_attrs_fuzzed",
  "player_id": 101,
  "points_spent": 0,
  "points_remaining": 500
}
```

**Error responses (400):**
```json
{ "error": "validation", "message": "Must unlock 'hs_report' before 'recruit_potential_fuzzed'" }
{ "error": "validation", "message": "Insufficient scouting points: need 15, have 10" }
{ "error": "validation", "message": "Only college organizations can scout HS players" }
{ "error": "validation", "message": "Only MLB organizations can draft-scout college/INTAM players" }
{ "error": "validation", "message": "Pro scouting only applies to players at pro levels (4-9)" }
```

### Updated Endpoint: `GET /api/v1/scouting/player/<player_id>`

Response now includes fog-of-war-aware data. Key changes:

1. **`letter_grades`** object values are now **fuzzed per viewing org** (previously used global conversion)
2. **`potentials`** object values can now be `"?"` (hidden), a fuzzed letter grade, or the precise letter grade
3. **New `display_format` field**: `"20-80"`, `"20-80-fuzzed"`, or absent (for letter grade / hidden contexts)
4. **`visibility.available_actions`** now returns the expanded set of 9 action types
5. **`visibility.pool`** now returns `"pro"` instead of `"mlb_fa"` for pro-level players

### Updated Endpoint: `GET /api/v1/scouting/budget/<org_id>`

No changes to the endpoint itself, but the budget system now covers 9 action types instead of 3, so `spent_points` will reflect spending on the new action types.

---

## 7. Scouting Workflow Sequences

### Workflow A: College Recruiting an HS Player

```
1. User (college org 100) opens /scouting/college-pool?viewing_org_id=100
   → Sees list of HS players
   → All _base attributes shown as fuzzed letter grades
   → All _pot values shown as "?"
   → No "Scout" buttons yet (pool listing doesn't show per-player actions)

2. User clicks a player → GET /scouting/player/500?org_id=100&league_year_id=1
   → Response:
     pool: "hs"
     bio: { ... }
     generated_stats: { avg: .312, hr: 5, ... }
     potentials: { power_pot: "?", contact_pot: "?", ... }
     visibility.available_actions: ["hs_report"]

3. User clicks "Scout Report" → POST /scouting/action
   { org_id: 100, league_year_id: 1, player_id: 500, action_type: "hs_report" }
   → Cost: 10 pts
   → Re-fetch player:
     text_report: "Exceptional bat speed and barrel control..."
     visibility.available_actions: ["recruit_potential_fuzzed"]

4. User clicks "Scout Potential" → POST /scouting/action
   { ..., action_type: "recruit_potential_fuzzed" }
   → Cost: 15 pts
   → Re-fetch player:
     potentials: { power_pot: "A-", contact_pot: "B+", ... }  ← FUZZED (1-3 steps off)
     visibility.available_actions: ["recruit_potential_precise"]

5. User clicks "Precise Potential" → POST /scouting/action
   { ..., action_type: "recruit_potential_precise" }
   → Cost: 25 pts
   → Re-fetch player:
     potentials: { power_pot: "A", contact_pot: "B+", ... }  ← TRUE values
     visibility.available_actions: []
```

Total cost for full HS scouting: **50 points** per player.

### Workflow B: MLB Draft Scouting a College Player

```
1. User (MLB org 5) opens /scouting/pro-pool?viewing_org_id=5
   → College players: _base shown as fuzzed letter grades, _pot fuzzed
   → INTAM players: same + counting_stats

2. User clicks a player → GET /scouting/player/800?org_id=5&league_year_id=1
   → Response:
     pool: "college"
     letter_grades: { contact: "B+", power: "A-", ... }  ← FUZZED per org 5
     potentials: { contact_pot: "B", power_pot: "A", ... }  ← FUZZED
     visibility.available_actions: ["college_potential_precise", "draft_attrs_fuzzed", "draft_potential_precise"]

3. User clicks "Scout Attributes (Fuzzed)" → POST /scouting/action
   { ..., action_type: "draft_attrs_fuzzed" }
   → Cost: 10 pts
   → Re-fetch player:
     attributes: { contact_base: 42.5, power_base: 61.0, ... }  ← raw values
     display_format: "20-80-fuzzed"
     → Frontend converts using Level 5 (Single-A) distributions, then applies fuzz
     visibility.available_actions: ["college_potential_precise", "draft_attrs_precise", "draft_potential_precise"]

4. User clicks "Scout Attributes (Precise)" → POST /scouting/action
   { ..., action_type: "draft_attrs_precise" }
   → Cost: 20 pts
   → Re-fetch player:
     attributes: { contact_base: 42.5, power_base: 61.0, ... }
     display_format: "20-80"  ← precise, no fuzz
     visibility.available_actions: ["college_potential_precise", "draft_potential_precise"]

5. User clicks "Precise Potential" → POST /scouting/action
   { ..., action_type: "draft_potential_precise" }
   → Cost: 15 pts
   → potentials now show TRUE values
```

Total cost for full draft scouting: **45 points** per player.

### Workflow C: Scouting Your Own (or Rival) Pro Roster

```
1. User (MLB org 5) opens /orgs/NYY/roster?viewing_org_id=5
   → All players shown with fuzzed 20-80 attributes and fuzzed potentials
   → visibility_context.display_format: "20-80"
   → visibility_context.attributes_precise: false

2. User clicks "Scout All" → POST /scouting/action/batch
   { org_id: 5, league_year_id: 1, player_ids: [1,2,3,...,25], action_type: "pro_attrs_precise" }
   → Cost: 15 pts × 25 = 375 pts
   → Re-fetch roster:
     All players now show precise 20-80 attributes
     visibility_context.attributes_precise: true

3. Repeat with "pro_potential_precise" for potentials
   → Cost: 15 pts × 25 = 375 pts
```

Total cost for full roster scouting: **750 points** for 25 players (attrs + potentials).

---

## 8. Response Shape Reference

### Roster/Ratings Player Object (with fog-of-war)

```typescript
interface PlayerWithVisibility {
  id: number;
  org_abbrev: string;
  league_level: string;       // "mlb", "aaa", etc.
  current_level: number;      // 4-9
  team_abbrev: string;

  bio: {
    firstname: string;
    lastname: string;
    age: number;
    ptype: "Pitcher" | "Position";
    // ... other biographical fields
    // NOTE: _base columns appear here as raw values
    // (used internally by visibility service)
  };

  ratings: {
    // When display_format = "20-80":
    power_display: number | null;     // 20-80 scale (fuzzed or precise)
    contact_display: number | null;
    // ...all *_display keys

    // When display_format = "letter_grade":
    power_display: string;            // "A+", "B-", etc. (fuzzed)
    contact_display: string;
    // ...

    // When display_format = "hidden":
    power_display: null;
    contact_display: null;
    // ...

    // Derived ratings (always numeric when visible, recomputed from fuzzed bases):
    c_rating: number | null;
    fb_rating: number | null;
    sb_rating: number | null;
    tb_rating: number | null;
    ss_rating: number | null;
    lf_rating: number | null;
    cf_rating: number | null;
    rf_rating: number | null;
    dh_rating: number | null;
    pitch1_ovr: number | null;
    pitch2_ovr: number | null;
    pitch3_ovr: number | null;
    pitch4_ovr: number | null;
    pitch5_ovr: number | null;
  };

  potentials: {
    power_pot: string;   // "A+", "B-", or "?"
    contact_pot: string;
    // ...all *_pot keys
  };

  contract: {
    id: number;
    years: number;
    current_year: number;
    // ...
  };

  // ONLY PRESENT when viewing_org_id was provided:
  visibility_context?: {
    context: "college_recruiting" | "college_roster" | "pro_draft" | "pro_roster";
    display_format: "hidden" | "letter_grade" | "20-80";
    attributes_precise: boolean;
    potentials_precise: boolean;
  };
}
```

### Scouting Player Object

```typescript
interface ScoutedPlayer {
  bio: {
    id: number;
    firstname: string;
    lastname: string;
    age: number;
    ptype: "Pitcher" | "Position";
    area: string;
    city: string;
    height: number;
    weight: number;
    bat_hand: string;
    pitch_hand: string;
    arm_angle: string;
    durability: string;
    injury_risk: string;
    pitch1_name: string;
    pitch2_name: string;
    pitch3_name: string;
    pitch4_name: string;
    pitch5_name: string;
  };

  // Present for HS players:
  generated_stats?: object;       // always present for HS
  text_report?: string;           // present if "hs_report" unlocked
  counting_stats?: object;        // present for INTAM players

  // Present for college/INTAM/pro:
  letter_grades?: {               // fuzzed letter grades (college/intam default view)
    contact: string;              // NOTE: key is attr name WITHOUT _base suffix
    power: string;
    // ...
  };

  attributes?: {                  // present if draft_attrs_* or pro context
    contact_base: number;         // raw numeric values
    power_base: number;
    // ...
    pitch1_ovr: number;
    // ...
  };

  display_format?: "20-80" | "20-80-fuzzed";  // how to interpret attributes

  potentials: {
    contact_pot: string;          // "?", fuzzed grade, or precise grade
    power_pot: string;
    // ...
  };

  visibility: {
    pool: "hs" | "college" | "intam" | "pro" | "none";
    unlocked: string[];           // action types already unlocked
    available_actions: string[];  // action types the org can still perform
  };
}
```

---

## 9. Frontend Rendering Rules

### Decision Tree for Attribute Rendering

```
IF visibility_context is absent:
  → Render as precise 20-80 (admin/legacy mode)

ELSE IF visibility_context.display_format == "hidden":
  → Render "—" or lock icon for all attributes
  → No color coding, no tooltips

ELSE IF visibility_context.display_format == "letter_grade":
  → Render the letter grade string directly
  → Color-code by grade (A+ = green, F = red)
  → Show fuzz indicator (e.g., "~B+" or a tilde icon)

ELSE IF visibility_context.display_format == "20-80":
  IF visibility_context.attributes_precise:
    → Render numeric value with confidence styling (bold, solid underline)
    → Color-code: 80 = elite blue, 50 = average, 20 = poor red
  ELSE:
    → Render numeric value with fuzz indicator
    → Color-code same, but muted/desaturated
    → Optional: show "±15" range tooltip
```

### Decision Tree for Potential Rendering

```
IF value == "?":
  → Render "?" in muted style

ELSE IF visibility_context.potentials_precise (or visibility_context absent):
  → Render grade with confidence styling

ELSE:
  → Render grade with fuzz indicator (tilde, dashed border, etc.)
```

### Detecting Data Type Changes

The `ratings.*_display` fields will contain **different data types** depending on context:
- `number` when display_format is `"20-80"`
- `string` when display_format is `"letter_grade"`
- `null` when display_format is `"hidden"`

The frontend should check `visibility_context.display_format` **before** trying to render ratings, not the data type of individual values.

### Scouting Action Buttons

Only show scouting action buttons from the `visibility.available_actions` array. Map each action to a user-friendly label:

```javascript
const ACTION_LABELS = {
  "hs_report":                "Scout Report",
  "recruit_potential_fuzzed": "Scout Potential (Estimate)",
  "recruit_potential_precise":"Scout Potential (Precise)",
  "college_potential_precise":"Precise Potential",
  "draft_attrs_fuzzed":       "Scout Attributes (Estimate)",
  "draft_attrs_precise":      "Scout Attributes (Precise)",
  "draft_potential_precise":  "Precise Potential",
  "pro_attrs_precise":        "Precise Attributes",
  "pro_potential_precise":    "Precise Potential",
};
```

Show the cost next to each button (costs are in the budget endpoint or can be hardcoded from the defaults table in section 4).

---

## 10. Migration Notes & Backward Compatibility

### What Changed

| Before | After |
|---|---|
| 3 action types: `hs_report`, `hs_potential`, `pro_numeric` | 9 action types (see section 4) |
| All roster/player endpoints return true values | With `viewing_org_id`, returns fuzzed values |
| Pool names: `"mlb_fa"` | Pool name: `"pro"` |
| Letter grades not fuzzed per org | Letter grades fuzzed deterministically per org |
| No batch scouting | `POST /scouting/action/batch` |

### Data Migration

Existing scouting actions are migrated:
- `hs_potential` → `recruit_potential_precise`
- `pro_numeric` → `draft_attrs_precise`

Players who had `hs_potential` unlocked now have `recruit_potential_precise`, which means they already have precise potentials. They do **not** have `recruit_potential_fuzzed` — but since precise is the higher tier, the fuzzed tier is effectively bypassed.

### Backward Compatibility

All existing API calls continue to work unchanged:
- Endpoints **without** `viewing_org_id` return the same true-value responses as before
- The `/scouting/player` endpoint with `org_id` now applies fog-of-war (this is a **breaking change** for the scouting player endpoint specifically — it previously returned unmasked data for some tiers)
- The `/scouting/action` endpoint now accepts 9 action types; the old `hs_potential` and `pro_numeric` types are **no longer valid** and will return a validation error

### Frontend Migration Steps

1. Update all roster/ratings/player API calls to include `viewing_org_id` from the user's auth context
2. Update the scouting action form to use new action type names
3. Add rendering logic for `visibility_context` in player cards/modals
4. Add batch scouting UI for roster-level "Scout All" functionality
5. Handle the `display_format` field to switch between numeric and letter-grade rendering

---

## 11. Constants Reference

### Organization ID Ranges
```
MLB:      1 – 30
College:  31 – 338
INTAM:    339
USHS:     340
```

### League Levels
```
1 = High School
2 = International Amateur
3 = College
4 = Scraps (low minor league)
5 = Single-A
6 = High-A
7 = Double-A
8 = Triple-A
9 = MLB
```

### Grade Scale (13 grades, low to high)
```
F, D-, D, D+, C-, C, C+, B-, B, B+, A-, A, A+
```

### 20-80 to Letter Grade Mapping
```
80+ → A+    65+ → B+    50+ → C+    35+ → D+
75+ → A     60+ → B     45+ → C     30+ → D
70+ → A-    55+ → B-    40+ → C-    25+ → D-
                                      20+ → F
```

### Default Scouting Costs
```
hs_report:                 10 pts
recruit_potential_fuzzed:   15 pts
recruit_potential_precise:  25 pts
college_potential_precise:  15 pts
draft_attrs_fuzzed:         10 pts
draft_attrs_precise:        20 pts
draft_potential_precise:    15 pts
pro_attrs_precise:          15 pts
pro_potential_precise:      15 pts
```

### Default Budgets (per org per league year)
```
MLB orgs:     1000 points
College orgs:  500 points
```
