# Player Awards — Frontend Guide

This document covers the new **awards** system: the trophies users vote for (MVP, Cy Young, Silver Slugger, Gold Glove, etc.) plus All-Star selections. Awards persist **across seasons**, so a player accumulates a career award history the frontend can display.

All endpoints are under `/api/v1`.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Changes to existing player data — `GET /stats/player/<id>`](#changes-to-existing-player-data)
3. [New endpoints](#new-endpoints)
4. [Award catalog (`award_types`)](#award-catalog)
5. [Display recipes](#display-recipes)

---

## Concepts

- **Awards persist across seasons.** Each award row is tied to a `league_year_id` (the season it was won). A player who wins MVP in three different seasons has three rows. This is exactly like the existing `batting` / `pitching` season arrays.
- **MLB only (for now).** Awards are issued at `league_level = 9`. The field is on every row so MiLB can be enabled later without a frontend change.
- **AL / NL split.** Most awards have **two winners per season** — one for each sub-league. The `sub_league` field is `"AL"` or `"NL"`. (League-wide awards, if any are added, use `null`.)
- **Per-position awards.** Silver Slugger and Gold Glove have one winner **per fielding position per league** — e.g. AL Silver Slugger at SS. Those rows carry a `position_code` (`"C"`, `"1B"`, `"SS"`, `"DH"`, …). All other awards have `position_code = null`.
- **Winners vs. finalists.** `rank = 1` and `is_winner = true` is the winner. Finalists/runners-up (if entered) have `rank` 2, 3, … and `is_winner = false`. For headline displays, filter to `is_winner`.
- **All-Star selections are awards too.** A player selected to an All-Star roster gets an `all_star` award (one per season per league). Unlike single-winner trophies, `all_star` has **many recipients per league** (`allows_multiple`). This is written automatically when an All-Star roster is created — no manual entry needed.

---

## Changes to existing player data

### `GET /stats/player/<int:player_id>`

The per-player career endpoint gains **three new top-level keys**. Everything else is unchanged.

```jsonc
{
  "player_id": 5012,
  "name": "Jose Ramirez",
  "current_injury": null,
  "injury_history": [ ... ],   // unchanged
  "batting":  [ ... ],         // unchanged
  "pitching": [ ... ],         // unchanged
  "fielding": [ ... ],         // unchanged

  // ── NEW ──────────────────────────────────────────────
  "awards": [
    {
      "award_id": 134,
      "award_code": "mvp",
      "award_name": "Most Valuable Player",
      "category": "major",
      "league_year_id": 3,
      "league_level": 9,
      "sub_league": "AL",
      "position_code": null,
      "team_id": 12,
      "team_abbrev": "CLE",
      "rank": 1,
      "is_winner": true,
      "vote_points": 388.0,
      "vote_share": 0.92
    },
    {
      "award_id": 102,
      "award_code": "silver_slugger",
      "award_name": "Silver Slugger",
      "category": "batting",
      "league_year_id": 3,
      "league_level": 9,
      "sub_league": "AL",
      "position_code": "3B",
      "team_id": 12,
      "team_abbrev": "CLE",
      "rank": 1,
      "is_winner": true,
      "vote_points": null,
      "vote_share": null
    },
    {
      "award_id": 77,
      "award_code": "all_star",
      "award_name": "All-Star Selection",
      "category": "selection",
      "league_year_id": 2,
      "league_level": 9,
      "sub_league": "AL",
      "position_code": null,
      "team_id": 12,
      "team_abbrev": "CLE",
      "rank": 1,
      "is_winner": true,
      "vote_points": null,
      "vote_share": null
    }
  ],

  "award_summary": {
    "mvp":            { "name": "Most Valuable Player", "wins": 1 },
    "silver_slugger": { "name": "Silver Slugger",       "wins": 1 },
    "all_star":       { "name": "All-Star Selection",   "wins": 1 }
  },

  "total_awards": 3
}
```

**Field notes**

| Field | Notes |
|-------|-------|
| `awards` | Array, **newest season first**. When the request includes `?league_year_id=N`, this array is filtered to that season; otherwise it's the full career. |
| `award_summary` | Career win counts keyed by `award_code`. **Always whole-career**, even when `?league_year_id=` is supplied — use it for the headline "3× MVP" line. Only counts rows where `is_winner = true`. |
| `total_awards` | Career total of winning awards (sum of `award_summary` wins). |
| `sub_league` | `"AL"` / `"NL"` / `null`. |
| `position_code` | Set only for per-position awards (Silver Slugger, Gold Glove); `null` otherwise. |
| `vote_points` / `vote_share` | Optional tally detail; may be `null`. `vote_share` is 0–1. |

> Backward compatibility: these are purely additive. Existing consumers that ignore the new keys are unaffected.

---

## New endpoints

### `GET /awards/player/<int:player_id>`

The canonical source for a player's career awards (same data embedded in `/stats/player`, served standalone for award-only views).

```jsonc
{
  "player_id": 5012,
  "awards": [ /* same award objects as above, newest season first */ ],
  "summary": { "mvp": { "name": "Most Valuable Player", "wins": 3 }, ... },
  "total_wins": 5
}
```

### `GET /awards/season/<int:league_year_id>`

A season's full award board (the "and the winner is…" page), grouped by award. Optional `?league_level=9` (default 9).

```jsonc
{
  "league_year_id": 3,
  "league_level": 9,
  "awards": [
    {
      "award_code": "mvp",
      "award_name": "Most Valuable Player",
      "category": "major",
      "recipients": [
        { "player_id": 5012, "name": "Jose Ramirez", "sub_league": "AL",
          "position_code": null, "team_id": 12, "team_abbrev": "CLE",
          "rank": 1, "is_winner": true, "vote_points": 388.0, "vote_share": 0.92 },
        { "player_id": 6001, "name": "Ronald Acuna", "sub_league": "NL",
          "position_code": null, "team_id": 20, "team_abbrev": "ATL",
          "rank": 1, "is_winner": true, "vote_points": 401.0, "vote_share": 0.95 }
      ]
    },
    { "award_code": "silver_slugger", "award_name": "Silver Slugger", "category": "batting",
      "recipients": [ /* up to 2 leagues × N positions */ ] }
  ]
}
```

### `GET /awards/types`

The award catalog — use it to build admin dropdowns and to render labels/grouping without hardcoding. See [Award catalog](#award-catalog).

### `POST /awards`  *(admin / commissioner)*

Record or update a single award. Re-posting the same `(season, award, league, position, player)` updates in place. For single-winner awards, posting a new winner to an occupied slot **replaces** the previous winner.

```jsonc
// Request body
{
  "player_id": 5012,
  "league_year_id": 3,
  "award_code": "mvp",
  "sub_league": "AL",            // required for league-split awards
  "position_code": "3B",         // required for silver_slugger / gold_glove only
  "rank": 1,                     // optional, default 1
  "is_winner": true,             // optional, defaults to (rank === 1)
  "league_level": 9,             // optional, default 9
  "team_id": 12,                 // optional — auto-snapshotted from active contract if omitted
  "vote_points": 388.0,          // optional
  "vote_share": 0.92,            // optional (0–1)
  "metadata": { "note": "..." }, // optional
  "created_by": "commissioner"   // optional
}
// → 201 { "award_id": 134, "award_code": "mvp", "player_id": 5012, "league_year_id": 3 }
```

Validation errors return `400 { "error": "validation_error", "message": "..." }`. Common cases:
- league-split award without `sub_league`
- per-position award without `position_code` (or a position on a non-positional award)
- unknown `award_code`

### `DELETE /awards/<int:award_id>`  *(admin)*

Revoke a single award. `200 { "deleted": true, "award_id": N }`, or `404` if not found.

---

## Award catalog

`GET /awards/types` returns:

```jsonc
{
  "award_types": [
    { "code": "mvp", "name": "Most Valuable Player", "category": "major",
      "ptype_scope": "any", "has_league_split": true, "is_per_position": false,
      "allows_multiple": false, "sort_order": 10, "description": "..." },
    ...
  ]
}
```

Seeded set:

| code | name | category | league split | per-position | multiple | scope |
|------|------|----------|:---:|:---:|:---:|------|
| `mvp` | Most Valuable Player | major | ✅ | – | – | any |
| `cy_young` | Cy Young Award | pitching | ✅ | – | – | pitcher |
| `roy` | Rookie of the Year | major | ✅ | – | – | any |
| `reliever` | Reliever of the Year | pitching | ✅ | – | – | pitcher |
| `comeback` | Comeback Player | major | ✅ | – | – | any |
| `silver_slugger` | Silver Slugger | batting | ✅ | ✅ | – | hitter |
| `gold_glove` | Gold Glove | fielding | ✅ | ✅ | – | any |
| `all_star` | All-Star Selection | selection | ✅ | – | ✅ | any |

The set is **data-driven** — new trophies can be added server-side without a frontend change. Render labels from `name`, group with `category`, and use the flags to decide which form fields (sub-league / position) to show in admin entry.

---

## Display recipes

**Headline badge line** (player profile): use `award_summary`. Render `3× MVP · 2× Silver Slugger · 4× All-Star`. Pluralize from `wins`.

**Awards timeline** (player profile): group `awards` by `league_year_id` (already sorted newest-first). Within a season, render each award with `award_name`, and append the qualifier when present: `sub_league` and/or `position_code` → e.g. *"AL Silver Slugger (3B)"*, *"NL Cy Young"*.

**Distinguish trophies from selections:** filter `award_code === "all_star"` into a separate "Selections" count; treat the rest as trophies. Or branch on `category === "selection"`.

**Finalists:** if you display vote results, `is_winner === false` rows are finalists — sort by `rank` ascending under each award/league.

**Season board page:** drive entirely off `GET /awards/season/<id>`; each `awards[].recipients` already carries names, teams, league, and position.
