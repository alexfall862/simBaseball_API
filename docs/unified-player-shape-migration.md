# Unified Player Response Shape — Frontend Migration Guide

## What Changed

All player-listing API endpoints now return the **same structural shape** for player attributes. Previously, the roster endpoints used `ratings` / `potentials` nesting with `_display` suffix and 20-80 scaling, while the FA pool used flat `_base` / `_pot` fields, the IFA board used its own flat format, and the draft pool returned no attributes at all.

Now every endpoint produces:

```
bio:        { firstname, lastname, age, ptype, ... }
ratings:    { contact_display, power_display, ..., c_rating, ss_rating, sp_rating, pitch1_ovr, ... }
potentials: { contact_pot, power_pot, ... }
```

This means you can delete per-context table implementations and reuse one set of components everywhere.

---

## Affected Endpoints

| Endpoint | What Changed |
|----------|-------------|
| `GET /fa-auction/free-agent-pool` | Flat `_base`/`_pot` fields replaced with nested `bio`, `ratings`, `potentials` |
| `GET /fa-auction/player-detail/{id}` | `attributes` key renamed to `ratings`; `display_format` removed |
| `GET /fa-auction/board` | `ratings`/`potentials` now use `_display` suffix + position ratings instead of flat `_base` |
| `GET /ifa/eligible` | Flat attribute fields replaced with nested `bio`, `ratings`, `potentials` |
| `GET /ifa/board` | Same restructuring as eligible |
| `GET /draft/eligible` | **Now includes player attributes** (previously returned only name/age/rank) |
| Roster endpoints (`/ratings/teams`, etc.) | **No change** — these already used this shape |

---

## Breaking Changes

### 1. Field access paths changed

**Before (FA pool):**
```js
player.contact_base    // "A-" or 65
player.power_base      // "A" or 72
player.contact_pot     // "A"
player.firstname       // "Aaron"
player.age             // 34
```

**After (all endpoints):**
```js
player.ratings.contact_display   // 65 (20-80 scale, fuzzed or precise)
player.ratings.power_display     // 72
player.potentials.contact_pot    // "A"
player.bio.firstname             // "Aaron"
player.bio.age                   // 34
```

### 2. Suffix changed: `_base` → `_display`

All base attribute keys now use `_display` suffix instead of `_base`. This matches the roster convention.

| Old Key | New Key | Location |
|---------|---------|----------|
| `contact_base` | `contact_display` | `player.ratings` |
| `power_base` | `power_display` | `player.ratings` |
| `speed_base` | `speed_display` | `player.ratings` |
| `pendurance_base` | `pendurance_display` | `player.ratings` |
| _(all other `_base`)_ | _(same pattern)_ | `player.ratings` |

### 3. Bio fields are now nested

Fields like `firstname`, `lastname`, `age`, `ptype`, `area`, `height`, `weight`, `bat_hand`, `pitch_hand`, `arm_angle`, `durability`, `injury_risk` are now under `player.bio` instead of flat on the player object.

`pitch1_name` through `pitch5_name` are also in `player.bio`.

### 4. `displayovr` and `id` remain at top level

```js
player.id          // 12345
player.displayovr  // 72
player.bio         // { firstname, lastname, age, ... }
player.ratings     // { contact_display, c_rating, pitch1_ovr, ... }
player.potentials  // { contact_pot, power_pot, ... }
```

### 5. `display_format` removed from FA detail

The `display_format` field (`"letter_grade"` / `"20-80"`) is gone. Instead, check `scouting.attrs_precise`:
- `false` → ratings are fuzzed 20-80 values
- `true` → ratings are precise 20-80 values

### 6. `attributes` key renamed to `ratings` (FA detail only)

The player detail endpoint previously returned `attributes`. It's now `ratings` to match every other endpoint.

---

## New Fields Available

These fields are **new** on FA pool, IFA, and draft endpoints — previously only available on the roster:

### Position Ratings (in `ratings`)

| Key | Position |
|-----|----------|
| `c_rating` | Catcher |
| `fb_rating` | First Base |
| `sb_rating` | Second Base |
| `tb_rating` | Third Base |
| `ss_rating` | Shortstop |
| `lf_rating` | Left Field |
| `cf_rating` | Center Field |
| `rf_rating` | Right Field |
| `dh_rating` | Designated Hitter |
| `sp_rating` | Starting Pitcher |
| `rp_rating` | Relief Pitcher |

These are 20-80 scaled derived ratings computed from weighted averages of base attributes. They tell you how well-suited a player is for each position/role. `null` when inapplicable (e.g., `sp_rating` is null for a pure position player with no pitching attributes).

### Pitch Overalls (in `ratings`)

| Key | Description |
|-----|-------------|
| `pitch1_ovr` | Overall rating for pitch 1 |
| `pitch2_ovr` through `pitch5_ovr` | Same for pitches 2-5 |

Computed as the average of the four pitch components (consistency, accuracy, break, control). `null` if the player doesn't have that pitch slot.

### Additional Base Attributes (in `ratings`)

These were in the roster but missing from FA/IFA:

| Key | Attribute |
|-----|-----------|
| `baserunning_display` | Baserunning aggressiveness |
| `basereaction_display` | Base reaction time |
| `fieldspot_display` | Fielding positioning |
| `catchframe_display` | Catcher framing |
| `catchsequence_display` | Catcher pitch sequencing |
| `pickoff_display` | Pitcher pickoff ability |

### Draft Pool — Now Has Attributes

The draft eligible endpoint (`GET /draft/eligible`) previously returned only `player_id`, `first_name`, `last_name`, `age`, `pitcher_role`, `source`, `draft_rank`, `composite_score`, `star_rating`.

It now returns the full `bio`, `ratings`, `potentials` shape with fog-of-war applied. Pass `viewing_org_id` as a query parameter to get visibility-appropriate values:

```
GET /api/v1/draft/eligible?league_year_id=5&viewing_org_id=1
```

The old flat fields (`player_id`, `first_name`, `last_name`, `age`, `pitcher_role`) are still present at the top level alongside the new nested structure for backward compat during migration.

---

## Context-Specific Fields

These fields are **only** on certain endpoints and should be handled per-context:

| Field | Endpoints | Purpose |
|-------|-----------|---------|
| `contract` | Roster only | Active contract details |
| `org_abbrev`, `team_abbrev`, `league_level` | Roster only | Current assignment |
| `fa_type` | FA pool | Tier: `mlb_fa`, `arb`, `pre_arb`, `milb_fa` |
| `auction` | FA pool, FA detail | Active auction state |
| `demand` | FA pool, FA detail | Player's contract demands |
| `scouting` | FA pool, FA detail, IFA, auction board | Scouting unlock state |
| `last_level`, `last_org_abbrev` | FA pool | Last known assignment |
| `listed_position` | FA pool, auction board | Display position (e.g., "RF", "SP") |
| `star_rating`, `slot_value` | IFA | International prospect evaluation |
| `source`, `draft_rank`, `composite_score` | Draft | Draft classification |

---

## Fog-of-War Behavior

All endpoints now use the same visibility system. The behavior depends on the viewing context:

| Context | Who's Looking | What Happens |
|---------|--------------|-------------|
| **Pro roster** (FA pool, roster) | Any org viewing a pro player | 20-80 values are fuzzed unless `pro_attrs_precise` is unlocked via scouting |
| **Pro draft** (IFA, draft pool) | MLB org viewing college/INTAM player | Different fuzz rules; requires `draft_attrs_precise` / `draft_potential_precise` |

Scouting actions are checked per-player. If a player has been scouted by the viewing org, their ratings/potentials are precise. Otherwise, they're deterministically fuzzed (same org always sees the same fuzz for a given player).

---

## Migration Checklist

- [ ] Update data access from `player.contact_base` to `player.ratings.contact_display` (and all other `_base` → `_display` renames)
- [ ] Update bio field access from `player.firstname` to `player.bio.firstname` (and all other bio fields)
- [ ] Update potentials access from `player.contact_pot` to `player.potentials.contact_pot` (if previously flat)
- [ ] Replace `display_format` checks with `scouting.attrs_precise` boolean
- [ ] Replace `attributes` references with `ratings` (FA detail endpoint)
- [ ] Add position rating columns to tables where desired (`c_rating`, `ss_rating`, `sp_rating`, etc.)
- [ ] Add pitch overall columns for pitcher views (`pitch1_ovr`, etc.)
- [ ] Delete `FAPoolTable` / duplicate table implementations (~500 lines)
- [ ] Reuse `AllPlayersTable`, `PositionTable`, `PitcherTable` from roster system
- [ ] Add `viewing_org_id` query param to draft eligible calls for fog-of-war
- [ ] Test scouting flow: scout a player on FA page, verify ratings switch from fuzzed to precise

---

## Example: Shared Table Component Usage

```jsx
// Before: separate components per context
<FAPoolTable players={faPlayers} />     // custom FA table
<RosterTable players={rosterPlayers} /> // separate roster table

// After: one component, different action buttons
<PlayerTable
  players={players}
  actions={context === 'fa' ? <FAActions /> : <RosterActions />}
/>
```

The `PlayerTable` component reads from `player.bio`, `player.ratings`, and `player.potentials` regardless of whether the data came from the roster, FA pool, IFA, or draft endpoint.
