# Frontend Statistics Expansion Guide

This document covers every API change from the statistics expansion across all 4 phases. Use it to update the **user-facing frontend** (the game client) to consume new fields, build new views, and wire up new endpoints.

**Two frontends exist:**
- **User-facing frontend** (separate repo) — this guide is for you. Consumes `/stats/*` endpoints.
- **Admin panel** (vanilla JS SPA in this API repo at `admin/static/`) — consumes `/admin/analytics/*` endpoints (WAR leaderboard, correlations, stamina reports). Admin updates are handled separately in this repo.

---

## Table of Contents

1. [Changes to Existing Endpoints](#1-changes-to-existing-endpoints)
2. [New Endpoints](#2-new-endpoints)
3. [New Stats Glossary](#3-new-stats-glossary)
4. [Implementation Plan](#4-implementation-plan)
5. [Stat Formatting Reference](#5-stat-formatting-reference)
6. [File-by-File Impact Map](#6-file-by-file-impact-map)

---

## 1. Changes to Existing Endpoints

These endpoints already existed but now return additional fields. Any frontend code consuming them should be updated to display the new data.

### 1.1 `GET /stats/batting` — Batting Leaderboard

**New fields added to each item in `leaders[]`:**

| Field | Type | Phase | Description |
|-------|------|-------|-------------|
| `hbp` | int | 1 | Hit by pitch (counting) |
| `woba` | string "0.XXX" | 2 | Weighted On-Base Average |
| `wrc_plus` | int | 2 | Weighted Runs Created Plus (100 = league avg) |
| `rc` | string "X.X" | 2 | Runs Created |
| `sec_a` | string "0.XXX" | 2 | Secondary Average |
| `pss` | string "X.X" | 2 | Power/Speed Score |
| `sf` | int | 3 | Sacrifice flies |
| `gidp` | int | 3 | Grounded into double play |
| `gb_pct` | string "0.XXX" | 3 | Ground ball rate |
| `fb_pct` | string "0.XXX" | 3 | Fly ball rate |
| `hr_fb` | string "0.XXX" | 3 | Home run / fly ball ratio |
| `barrel_pct` | string "0.XXX" | 3 | Barrel contact rate |
| `hard_hit_pct` | string "0.XXX" | 3 | Hard hit rate (barrel + solid) |
| `soft_pct` | string "0.XXX" | 5 | Soft contact rate (topped + weak) |
| `med_pct` | string "0.XXX" | 5 | Medium contact rate (flare + burner + under) |
| `ld_pct` | string "0.XXX" | 5 | Line drive rate (barrel + solid + flare) |
| `contact_pct` | string "0.XXX" | 5 | Contact rate (1 - K/AB) |
| `ops_plus` | int | 5 | OPS+ (100 = league average) |

**Changed fields:**

| Field | Change | Phase |
|-------|--------|-------|
| `pa` | Now calculated as `AB + BB + HBP` (was `AB + BB`) | 1 |
| `obp` | Now includes HBP: `(H+BB+HBP)/(AB+BB+HBP)` | 1 |
| All rate stats (`bb_pct`, `k_pct`) | Use corrected PA denominator | 1 |

**New sortable keys:** `hbp`, `woba`, `rc`, `sec_a`, `sf`, `gidp`, `gb_pct`

---

### 1.2 `GET /stats/pitching` — Pitching Leaderboard

**New fields added to each item in `leaders[]`:**

| Field | Type | Phase | Description |
|-------|------|-------|-------------|
| `hbp` | int | 1 | Hit batters |
| `wp` | int | 1 | Wild pitches |
| `pitches` | int | 1 | Total pitches thrown |
| `balls` | int | 1 | Balls thrown |
| `strikes` | int | 1 | Strikes thrown |
| `str_pct` | string "0.XXX" | 1 | Strike percentage |
| `p_ip` | string "X.X" | 1 | Pitches per inning |
| `fip` | string "X.XX" | 2 | Fielding Independent Pitching |
| `gb_pct` | string "0.XXX" | 3 | Ground ball rate allowed |
| `fb_pct` | string "0.XXX" | 3 | Fly ball rate allowed |
| `hr_fb` | string "0.XXX" | 3 | HR/FB ratio |
| `barrel_pct` | string "0.XXX" | 3 | Barrel rate allowed |
| `hard_hit_pct` | string "0.XXX" | 3 | Hard hit rate allowed |
| `ir` | int | 3 | Inherited runners |
| `irs` | int | 3 | Inherited runners scored |
| `ir_pct` | string "0.XXX" | 3 | Inherited runner scoring rate |
| `gidp_induced` | int | 3 | GIDP induced |
| `bf` | int | 3 | Batters faced (exact from engine) |

**Changed fields:**

| Field | Change | Phase |
|-------|--------|-------|
| `k_pct`, `bb_pct` | Use corrected BF denominator (`IPO + H + BB + HBP`) | 1 |
| `babip` | Uses corrected BIP formula | 1 |

**New sortable keys:** `hbp`, `wp`, `pitches`, `str_pct`, `p_ip`, `fip`, `gb_pct`

---

### 1.3 `GET /stats/player/<id>` — Single Player Stats

**`batting[]` items — new fields:**

| Field | Type | Phase |
|-------|------|-------|
| `pa` | int | 1 |
| `hbp` | int | 1 |

**`pitching[]` items — new fields:**

| Field | Type | Phase |
|-------|------|-------|
| `hbp` | int | 1 |
| `wp` | int | 1 |
| `pitches` | int | 1 |
| `str_pct` | string | 1 |
| `p_ip` | string | 1 |

**Changed:** `obp` now includes HBP in both batting and pitching season helpers.

---

### 1.4 `GET /stats/team` — Team Aggregate Stats

**`batting[]` items — new fields:**

| Field | Type | Phase |
|-------|------|-------|
| `hbp` | int | 1 |

**`pitching[]` — no new fields yet** (team pitching kept minimal). `hbp`, `pitches`, `wp` are available in the DB but not yet surfaced in team aggregates.

**Changed:** PA and OBP corrected to include HBP.

---

### 1.5 `GET /admin/analytics/war-leaderboard` — WAR Leaderboard

**Completely reworked response.** The WAR model changed from OPS/ERA-based to wOBA/FIP-based.

**New fields per player in `leaders[]`:**

| Field | Type | Description |
|-------|------|-------------|
| `pos_adj` | float | Positional adjustment runs (C: +12.5 ... DH: -17.5, prorated) |
| `woba` | float | Player's wOBA |
| `wrc_plus` | float | Player's wRC+ |
| `fip` | float | Player's FIP (pitchers/two-way only) |

**Changed fields:**

| Field | Before | After |
|-------|--------|-------|
| `batting_runs` | OPS-based | wOBA-based: `(wOBA - replwOBA) / wOBA_scale * PA` |
| `pit_runs` | ERA-based | FIP-based: `(replFIP - playerFIP) * IP / 9` |
| `war` | Sum of old components | Includes positional adjustment |

**`league_averages` object — new structure:**

```json
{
  "ops": 0.750,
  "woba": 0.320,
  "r_pa": 0.110,
  "era": 4.50,
  "fip": 4.20,
  "fip_constant": 3.17
}
```

**Replacement level fields changed:**

| Before | After |
|--------|-------|
| `repl_ops` | `repl_woba` |
| `repl_era` | `repl_fip` |

---

### 1.6 `GET /admin/analytics/batting-correlations` — Batting Correlations

**New derived stats available for correlation:**

| Stat Key | Description | Phase |
|----------|-------------|-------|
| `wOBA` | Weighted On-Base Average | 2 |
| `RC` | Runs Created | 2 |
| `SecA` | Secondary Average | 2 |
| `PSS` | Power/Speed Score | 2 |
| `GB_pct` | Ground ball rate | 3 |
| `FB_pct` | Fly ball rate | 3 |
| `PU_pct` | Popup rate | 3 |
| `Barrel_pct` | Barrel contact rate | 3 |
| `HardHit_pct` | Hard hit rate | 3 |
| `GIDP_pct` | GIDP rate | 3 |
| `HR_FB` | Home run / fly ball ratio | 3 |

These appear in the correlation matrix alongside the existing stats.

---

### 1.7 `GET /admin/analytics/pitching-correlations` — Pitching Correlations

**New derived stats available:**

| Stat Key | Description | Phase |
|----------|-------------|-------|
| `FIP` | Fielding Independent Pitching | 2 |
| `GB_pct` | Ground ball rate allowed | 3 |
| `FB_pct` | Fly ball rate allowed | 3 |
| `Barrel_pct` | Barrel rate allowed | 3 |
| `HardHit_pct` | Hard hit rate allowed | 3 |
| `HR_FB` | HR/FB ratio | 3 |
| `IR_pct` | Inherited runner scoring rate | 3 |
| `GIDP_rate` | GIDP rate induced | 3 |

---

## 2. New Endpoints

These endpoints are entirely new and need new frontend views/components.

### 2.1 `GET /stats/player/<id>/gamelog?league_year_id=X`

**Purpose:** Game-by-game batting and pitching log with running season stats.

**Response:**
```json
{
  "batting": [
    {
      "game_id": 12345,
      "week": 3, "subweek": "b",
      "opponent": "NYY" or "@BOS",
      "result": "W 5-3",
      "pos": "ss", "bo": 2,
      "ab": 4, "r": 1, "h": 2, "2b": 1, "3b": 0, "hr": 0,
      "rbi": 1, "bb": 0, "so": 1,
      "sb": 0, "cs": 0, "hbp": 0, "pa": 4,
      "avg": "0.312",
      "obp": "0.375",
      "ops": "0.845"
    }
  ],
  "pitching": [
    {
      "game_id": 12345,
      "week": 3, "subweek": "b",
      "opponent": "@BOS",
      "dec": "W",
      "gs": 1,
      "ip": "7.0",
      "h": 5, "r": 2, "er": 2, "bb": 1, "so": 8, "hr": 1,
      "hbp": 0, "pitches": 98,
      "era": "3.24"
    }
  ]
}
```

**Key features:**
- `avg`, `obp`, `ops` are **running season totals** (cumulative through each game), not per-game values
- `result` shows W/L and final score
- `dec` for pitchers includes "H" (hold) in addition to W/L/S
- `opponent` prefixed with "@" for away games
- Ordered chronologically by week/subweek

**Suggested UI:** Scrollable table with one row per game. Optional line chart overlay showing running AVG/OPS trend. Click a row to jump to the boxscore.

---

### 2.2 `GET /stats/player/<id>/career`

**Purpose:** Season-by-season stats with a career totals row.

**Response:**
```json
{
  "player_id": 12345,
  "name": "John Smith",
  "batting": [
    {"season": 1, "team": "NYY", "level": 9, "g": 150, "ab": 550, ...rate stats...},
    {"season": 2, "team": "NYY", "level": 9, "g": 145, "ab": 530, ...rate stats...},
    {"season": "Career", "team": null, "level": null, "g": 295, "ab": 1080, ...rate stats...}
  ],
  "pitching": [
    ...same structure...
  ]
}
```

**Key features:**
- Last row has `"season": "Career"` (string, not int) with `team` and `level` null
- Rate stats (AVG, OBP, SLG, OPS, ERA, WHIP) are calculated from career totals, not averaged across seasons
- Includes `sf` (sacrifice flies) for proper OBP denominator
- Includes `team_level` so you can show level progression (minors → MLB)

**Suggested UI:** Table with season rows, bolded career totals row at bottom. Optional WAR trajectory chart (requires separate WAR endpoint call per season).

---

### 2.3 `GET /stats/player/<id>/splits?league_year_id=X`

**Purpose:** Home/away and opponent-by-opponent batting/pitching splits.

**Response:**
```json
{
  "batting_home_away": {
    "home": {"g": 75, "ab": 280, "avg": ".305", "obp": ".372", "slg": ".510", "ops": ".882", ...},
    "away": {"g": 72, "ab": 265, "avg": ".275", "obp": ".340", "slg": ".445", "ops": ".785", ...}
  },
  "batting_vs_opponent": [
    {"opponent": "BOS", "g": 18, "ab": 65, "avg": ".338", ...},
    {"opponent": "TBR", "g": 17, "ab": 60, "avg": ".250", ...},
    ...
  ],
  "pitching_home_away": {
    "home": {"g": 15, "ip": "95.1", "era": "3.02", ...},
    "away": {"g": 14, "ip": "88.0", "era": "4.15", ...}
  }
}
```

**Key features:**
- `batting_home_away` is a dict keyed by `"home"` / `"away"`, not an array
- `batting_vs_opponent` sorted by AB descending (most-faced opponents first)
- Pitching splits do not include vs-opponent (low sample size per matchup)

**Suggested UI:** Two-row comparison table for home/away. Separate expandable table for vs-opponent. Color-code cells where the split difference is significant (e.g., OPS diff > .100).

---

### 2.4 `GET /stats/distribution?league_year_id=X&league_level=9&stat=avg`

**Purpose:** League-wide histogram for any stat, with optional player highlight.

**Query params:**

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `league_year_id` | yes | — | |
| `league_level` | yes | — | |
| `stat` | yes | — | batting: avg, obp, slg, ops, iso, babip; pitching: era, whip, k9, bb9, fip |
| `category` | no | batting | "batting" or "pitching" |
| `min_pa` | no | 50 | Batting qualifying threshold |
| `min_ip` | no | 10 | Pitching qualifying threshold (innings) |
| `buckets` | no | 20 | Number of histogram bins (max 100) |
| `player_id` | no | — | Highlight this player's position |

**Response:**
```json
{
  "histogram": [
    {"min": 0.200, "max": 0.215, "count": 3},
    {"min": 0.215, "max": 0.230, "count": 8},
    ...
  ],
  "stat": "avg",
  "category": "batting",
  "count": 245,
  "mean": 0.2654,
  "median": 0.2680,
  "min": 0.1820,
  "max": 0.3560,
  "player": {
    "player_id": 12345,
    "value": 0.3120,
    "percentile": 88.2
  }
}
```

**Key features:**
- `histogram` array has exactly `buckets` entries (default 20)
- Each bucket has `min` (inclusive), `max` (exclusive, except last), `count`
- `player` object only present if `player_id` was provided AND the player qualifies
- `percentile` is the percentage of qualifying players at or below this value

**Suggested UI:** Bar chart (Chart.js) with the player's bin highlighted. Show mean/median lines as vertical markers. Display percentile rank prominently ("88th percentile").

---

## 3. New Stats Glossary

### Batting Stats (for tooltips / info popovers)

| Abbrev | Name | Formula | Phase |
|--------|------|---------|-------|
| PA | Plate Appearances | AB + BB + HBP (+ SF when available) | 1 |
| HBP | Hit By Pitch | — | 1 |
| wOBA | Weighted On-Base Average | `(0.69*BB + 0.72*HBP + 0.88*1B + 1.24*2B + 1.57*3B + 2.00*HR) / PA` | 2 |
| wRC+ | Weighted Runs Created Plus | 100 = league average. 150 = 50% above average. | 2 |
| RC | Runs Created | `(H + BB) * TB / (AB + BB)` | 2 |
| SecA | Secondary Average | `(TB - H + BB + SB - CS) / AB` | 2 |
| PSS | Power/Speed Score | `2 * HR * SB / (HR + SB)` | 2 |
| FIP | Fielding Independent Pitching | `(13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP` | 2 |
| SF | Sacrifice Flies | — | 3 |
| GIDP | Grounded Into Double Play | — | 3 |
| GB% | Ground Ball Rate | Ground balls / balls in play | 3 |
| FB% | Fly Ball Rate | Fly balls / balls in play | 3 |
| HR/FB | Home Run / Fly Ball | HR / fly balls | 3 |
| Barrel% | Barrel Rate | Barrel contacts / total contacts | 3 |
| HardHit% | Hard Hit Rate | (Barrel + Solid) / total contacts | 3 |
| IR | Inherited Runners | Runners on base when reliever entered | 3 |
| IRS | Inherited Runners Scored | How many of those runners scored | 3 |
| IR% | Inherited Runner Scoring Rate | IRS / IR | 3 |
| BF | Batters Faced | Exact count from engine | 3 |
| Str% | Strike Percentage | Strikes / pitches thrown | 1 |
| P/IP | Pitches Per Inning | Pitches thrown / IP | 1 |

### Contact Quality Types (from engine)

The engine classifies every batted ball by contact quality:

| Type | Typical Outcome | Maps To |
|------|----------------|---------|
| barrel | Hard line drive / HR | Hard hit |
| solid | Line drive / hard grounder | Hard hit |
| flare | Bloop single / shallow fly | Medium |
| burner | Sharp grounder | Medium |
| under | Fly ball / popup | Soft |
| topped | Weak grounder | Soft |
| weak | Weak contact / easy out | Soft |

**Hard hit = barrel + solid.** The other five are "not hard hit."

---

## 4. Implementation Plan

### Priority 1: Types and Service Layer

**Files:** `baseballStatsModels.ts`, `baseballService.tsx`

This unblocks everything else. Do this first.

**Type updates (baseballStatsModels.ts):**
- Add new fields to `BattingLeaderRow`: `hbp`, `woba`, `wrc_plus`, `rc`, `sec_a`, `pss`, `sf`, `gidp`, `gb_pct`, `fb_pct`, `hr_fb`, `barrel_pct`, `hard_hit_pct`
- Add new fields to `PitchingLeaderRow`: `hbp`, `wp`, `pitches`, `balls`, `strikes`, `str_pct`, `p_ip`, `fip`, `gb_pct`, `fb_pct`, `hr_fb`, `barrel_pct`, `hard_hit_pct`, `ir`, `irs`, `ir_pct`, `gidp_induced`, `bf`
- Add new fields to `PlayerStatsSeason` (batting): `pa`, `hbp`
- Add new fields to `PlayerPitchingSeason`: `hbp`, `wp`, `pitches`, `str_pct`, `p_ip`
- Add new fields to `TeamBattingRow`: `hbp`
- Update `BattingSortField` union with new sortable keys: `"hbp"`, `"woba"`, `"rc"`, `"sec_a"`, `"sf"`, `"gidp"`, `"gb_pct"`
- Update `PitchingSortField` union with: `"hbp"`, `"wp"`, `"pitches"`, `"str_pct"`, `"p_ip"`, `"fip"`, `"gb_pct"`
- Create new types:
  - `GamelogBattingRow` — fields from Section 2.1
  - `GamelogPitchingRow` — fields from Section 2.1
  - `CareerBattingSeason` — fields from Section 2.2 (note: `season` is `number | "Career"`)
  - `CareerPitchingSeason` — fields from Section 2.2
  - `BattingSplitRow` — fields from Section 2.3
  - `PitchingSplitRow` — fields from Section 2.3
  - `StatDistributionResponse` — fields from Section 2.4
  - `HistogramBucket` — `{ min: number, max: number, count: number }`

**Service functions (baseballService.tsx):**
- `GetPlayerGamelog(playerId, leagueYearId)` → `GET /stats/player/<id>/gamelog`
- `GetPlayerCareer(playerId)` → `GET /stats/player/<id>/career`
- `GetPlayerSplits(playerId, leagueYearId)` → `GET /stats/player/<id>/splits`
- `GetStatDistribution(params)` → `GET /stats/distribution`

No changes needed to existing service calls — `GetBattingLeaderboard`, `GetPitchingLeaderboard`, `GetPlayerStats`, `GetTeamStats` will automatically receive the new fields since the API is additive.

### Priority 2: Update Leaderboard Tables

**Files:** `BaseballBattingTable.tsx`, `BaseballPitchingTable.tsx`, `BaseballStatsPage.tsx`

**BaseballBattingTable.tsx:**
1. Add column definitions for all new fields (see Section 1.1)
2. Implement column visibility toggle — 30+ columns is too many for a default view. Suggested defaults:
   - **Standard:** G, AB, R, H, 2B, 3B, HR, RBI, BB, SO, SB, AVG, OBP, SLG, OPS
   - **Advanced:** wOBA, wRC+, ISO, BABIP, BB%, K%
   - **Batted ball:** GB%, FB%, HR/FB, Barrel%, HardHit%
   - **Counting:** PA, HBP, SF, GIDP, RC, SecA, PSS

**BaseballPitchingTable.tsx:**
1. Add column definitions for all new fields (see Section 1.2)
2. Same visibility toggle pattern. Suggested groups:
   - **Standard:** G, GS, W, L, SV, IP, H, ER, BB, SO, ERA, WHIP
   - **Advanced:** FIP, K/9, BB/9, K%, BB%, K/BB, BABIP
   - **Batted ball:** GB%, FB%, HR/FB, Barrel%, HardHit%
   - **Pitch data:** Pitches, Str%, P/IP, HBP, WP
   - **Reliever:** HLD, BS, IR, IRS, IR%

**BaseballStatsPage.tsx:**
1. Add new sort field options to state (new keys from `BattingSortField`/`PitchingSortField`)
2. Wire up column visibility toggle state and persistence (localStorage)
3. Update qualifying minimum logic if implementing auto-calculation (3.1 PA/team game for batting, 1.0 IP/team game for pitching)

### Priority 3: Update Player Modal Stats Tab

**File:** `Modals.tsx` (~line 3560-3579)

The player stats modal uses `GetPlayerStats()` which now returns new fields. Updates:

1. Add `pa` and `hbp` to the batting stats display
2. Add `hbp`, `wp`, `pitches`, `str_pct`, `p_ip` to pitching display
3. **This is the natural place to add navigation to the new views.** Add tabs or links:
   - "Game Log" → new GamelogView component (Priority 4)
   - "Career" → new CareerView component (Priority 5)
   - "Splits" → new SplitsView component (Priority 6)
   - "Distribution" → link to stat distribution view for this player

### Priority 4: Build Player Game Log View

**New component.** Fetches `GET /stats/player/<id>/gamelog?league_year_id=X`.

- Table of per-game rows ordered chronologically
- Running AVG/OBP/OPS columns show season progression (these are cumulative, not per-game)
- Optional Chart.js line chart showing running AVG and/or OPS over time
- `result` field shows "W 5-3" / "L 2-4" — display as a badge
- `dec` for pitchers includes "H" (hold) in addition to W/L/S
- `opponent` prefixed with "@" for away games
- Click row to link to boxscore

### Priority 5: Build Career Stats View

**New component.** Fetches `GET /stats/player/<id>/career`.

- Table with one row per season + bolded career totals row
- Last row has `"season": "Career"` (string, not int) — check type when rendering
- Show team abbreviation and level per row
- Rate stats (AVG, OBP, SLG, OPS / ERA, WHIP) per season and career
- Career totals are calculated from sum of counting stats, not averaged across seasons

### Priority 6: Build Split Stats View

**New component.** Fetches `GET /stats/player/<id>/splits?league_year_id=X`.

- Home/Away comparison table (2 rows side by side)
- `batting_home_away` is a dict keyed by `"home"` / `"away"`, not an array
- Vs-opponent table below (sortable, one row per opponent, sorted by AB desc)
- Color-code notable differences (e.g., home OPS 100+ points higher)

### Priority 7: Build Stat Distribution View

**New component.** Fetches `GET /stats/distribution?...`.

- Stat selector dropdown (AVG, OBP, OPS, ERA, FIP, etc.)
- Category toggle (Batting / Pitching)
- Chart.js bar chart rendering the histogram
- Highlighted bin for the viewed player
- Display: percentile rank, mean, median
- Qualifying minimum input (adjustable)

### Priority 8: Update Team Stats Table

**File:** `BaseballTeamStatsTable.tsx`

- Team batting now includes `hbp` and corrected PA/OBP values
- Add `hbp` column to team batting table
- No new pitching fields surfaced in team stats yet (available in DB but not in API response)

### Priority 9: Update CSV Export

**File:** `rosterCsvExport.ts`

- Add new fields to `BATTING_STAT_HEADERS` and `PITCHING_STAT_HEADERS` arrays
- Update row-building functions to include new stat values
- Without this update, exports will silently omit new stats

### Priority 10 (Optional): Roster Table Inline Stats

**File:** `BaseballRosterTable.tsx`

- Uses `PlayerStatsMap` with `BattingLeaderRow`/`PitchingLeaderRow` types
- Existing inline stats (AVG, OBP, etc.) will automatically show corrected values from the API
- If you want to surface any new stats inline on the roster (e.g., wOBA, FIP), add columns here
- This can stay as-is if you prefer — the corrected values flow through automatically

---

## 5. Stat Formatting Reference

All string-formatted stats from the API are pre-formatted. Parse as-is for display.

| Format | Examples | Stats |
|--------|----------|-------|
| `"0.XXX"` | `"0.312"`, `".000"` | AVG, OBP, SLG, ISO, BABIP, BB%, K%, SB%, XBH%, wOBA, SecA, GB%, FB%, Barrel%, HardHit%, HR/FB, IR%, Str% |
| `"X.XX"` | `"3.24"`, `"1.15"` | ERA, WHIP, FIP, K/BB, W% |
| `"X.X"` | `"8.5"`, `"15.3"` | K/9, BB/9, HR/9, H/9, IP/GS, AB/HR, P/IP, RC, PSS |
| `"X.X"` (IP) | `"7.0"`, `"6.2"` | IP (innings.outs, NOT decimal) |
| integer | `100`, `150` | wRC+, all counting stats |
| `"0.XXXX"` | `"0.2654"` | Distribution endpoint values (mean, median, etc.) |

**Note on IP format:** `"6.2"` means 6 innings and 2 outs (= 6.667 innings), NOT 6.2 innings. This is standard baseball notation. For sorting/arithmetic, convert: `ip_float = Math.floor(ip) + (ip % 1) * 10 / 3`.

---

## Endpoint Summary Table

| Endpoint | Status | Method | Frontend |
|----------|--------|--------|----------|
| `/stats/batting` | Updated | GET | User |
| `/stats/pitching` | Updated | GET | User |
| `/stats/fielding` | Unchanged | GET | User |
| `/stats/team` | Updated | GET | User |
| `/stats/player/<id>` | Updated | GET | User |
| `/stats/player/<id>/gamelog` | **New** | GET | User |
| `/stats/player/<id>/career` | **New** | GET | User |
| `/stats/player/<id>/splits` | **New** | GET | User |
| `/stats/distribution` | **New** | GET | User |
| `/admin/analytics/war-leaderboard` | Updated | GET | Admin (in API repo) |
| `/admin/analytics/batting-correlations` | Updated | GET | Admin (in API repo) |
| `/admin/analytics/pitching-correlations` | Updated | GET | Admin (in API repo) |

---

## 6. File-by-File Impact Map

Every file in the user-facing frontend that needs changes, with what and why.

| File | Priority | Change Type | What To Do |
|------|----------|-------------|------------|
| `baseballStatsModels.ts` | 1 | Type updates | Add new fields to `BattingLeaderRow`, `PitchingLeaderRow`, `PlayerStatsSeason`, `PlayerPitchingSeason`, `TeamBattingRow`. Update `BattingSortField`/`PitchingSortField` unions. Create new types: `GamelogBattingRow`, `GamelogPitchingRow`, `CareerBattingSeason`, `CareerPitchingSeason`, `BattingSplitRow`, `PitchingSplitRow`, `StatDistributionResponse`, `HistogramBucket`. |
| `baseballService.tsx` | 1 | New functions | Add `GetPlayerGamelog()`, `GetPlayerCareer()`, `GetPlayerSplits()`, `GetStatDistribution()`. Existing calls need no changes (API is additive). |
| `BaseballBattingTable.tsx` | 2 | Column additions | Add column definitions for 13 new batting fields. Implement column visibility toggle with grouped presets (Standard/Advanced/Batted Ball/Counting). |
| `BaseballPitchingTable.tsx` | 2 | Column additions | Add column definitions for 19 new pitching fields. Same visibility toggle with presets (Standard/Advanced/Batted Ball/Pitch Data/Reliever). |
| `BaseballStatsPage.tsx` | 2 | State updates | Add new sort field options, column visibility toggle state + localStorage persistence, optional qualifying minimum logic. |
| `Modals.tsx` | 3 | Stats tab update | Add `pa`/`hbp` to batting display, `hbp`/`wp`/`pitches`/`str_pct`/`p_ip` to pitching display. Add navigation tabs/links to new gamelog, career, and splits views. |
| *(new)* `PlayerGamelogView.tsx` | 4 | New component | Game-by-game table with running AVG/OBP/OPS, optional line chart. |
| *(new)* `PlayerCareerView.tsx` | 5 | New component | Season-by-season table with career totals row. |
| *(new)* `PlayerSplitsView.tsx` | 6 | New component | Home/away comparison + vs-opponent table. |
| *(new)* `StatDistributionView.tsx` | 7 | New component | Histogram chart with player percentile highlight. |
| `BaseballTeamStatsTable.tsx` | 8 | Column addition | Add `hbp` to team batting columns. Corrected PA/OBP values flow automatically. |
| `rosterCsvExport.ts` | 9 | Header updates | Add new fields to `BATTING_STAT_HEADERS` and `PITCHING_STAT_HEADERS`. Update row-building functions. Without this, CSV exports silently omit new stats. |
| `BaseballRosterTable.tsx` | 10 (optional) | No change required | Corrected stat values (OBP, PA) flow automatically. Only needs changes if you want to surface new stats (wOBA, FIP) inline on the roster view. |
