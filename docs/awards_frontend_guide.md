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
6. [Year-over-year Awards History page — `GET /awards/history`](#year-over-year-awards-history-page)

---

## Concepts

- **Awards persist across seasons.** Each award row is tied to a `league_year_id` (the season it was won). A player who wins MVP in three different seasons has three rows. This is exactly like the existing `batting` / `pitching` season arrays.
- **MLB only (for now).** Awards are issued at `league_level = 9`. The field is on every row so MiLB can be enabled later without a frontend change.
- **AL / NL split.** Most awards have **two winners per season** — one for each sub-league. The `sub_league` field is `"AL"` or `"NL"`. (League-wide awards, if any are added, use `null`.)
- **Per-position awards.** Silver Slugger and Gold Glove have one winner **per fielding position per league** — e.g. AL Silver Slugger at SS. Those rows carry a `position_code` (`"C"`, `"1B"`, `"SS"`, `"DH"`, …). All other awards have `position_code = null`.
- **Winners vs. finalists.** `rank = 1` and `is_winner = true` is the winner. Finalists/runners-up (if entered) have `rank` 2, 3, … and `is_winner = false`. For headline displays, filter to `is_winner`.
- **All-Star selections are awards too.** A player selected to an All-Star roster gets an `all_star` award (one per season per league). Unlike single-winner trophies, `all_star` has **many recipients per league** (`allows_multiple`). This is written automatically when an All-Star roster is created — no manual entry needed.
- **Pennants and World Series rings are team awards.** When a Championship Series clinches, every player on the winning roster gets a `pennant` award (`sub_league` = `"AL"` or `"NL"`). When the World Series clinches, every player on the champion's roster gets a `world_series` award (league-wide, `sub_league` is `null`). Both are `category: "championship"` and `allows_multiple`. They are written automatically by the playoff engine; `metadata` on the row carries `series_id`, `opponent_team_id` and `series_result` (e.g. `"4-2"`). Rosters are snapshotted at the moment the series ends.

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
| `pennant` | League Pennant | championship | ✅ | – | ✅ | any |
| `world_series` | World Series Champion | championship | – | – | ✅ | any |
| `all_star` | All-Star Selection | selection | ✅ | – | ✅ | any |

The set is **data-driven** — new trophies can be added server-side without a frontend change. Render labels from `name`, group with `category`, and use the flags to decide which form fields (sub-league / position) to show in admin entry.

---

## Display recipes

**Headline badge line** (player profile): use `award_summary`. Render `3× MVP · 2× Silver Slugger · 4× All-Star`. Pluralize from `wins`.

**Awards timeline** (player profile): group `awards` by `league_year_id` (already sorted newest-first). Within a season, render each award with `award_name`, and append the qualifier when present: `sub_league` and/or `position_code` → e.g. *"AL Silver Slugger (3B)"*, *"NL Cy Young"*.

**Distinguish trophies from selections:** filter `award_code === "all_star"` into a separate "Selections" count; treat the rest as trophies. Or branch on `category === "selection"`.

**Championships:** `category === "championship"` rows (`pennant`, `world_series`) are team honours rather than individual trophies. Typical rendering is a ring/pennant badge line on the profile (`2× World Series Champion · 3× AL Pennant`) and a "Championships" section on the team page. Team pages can list a season's champions from `GET /awards/season/<id>` by grouping `world_series` / `pennant` recipients by `team_id`.

**Manual entry for team awards:** `POST /awards/team` with `{team_id, league_year_id, award_code, sub_league?}` gives the whole current roster the award in one call (`player_ids` overrides the roster). `POST /awards/sync-postseason` with `{league_year_id}` re-derives pennants and rings from the completed playoff series if the automatic write was missed.

**Finalists:** if you display vote results, `is_winner === false` rows are finalists — sort by `rank` ascending under each award/league.

**Season board page:** drive entirely off `GET /awards/season/<id>`; each `awards[].recipients` already carries names, teams, league, and position.

---

## Year-over-year Awards History page

*Added 2026-11-21.* One call returns every season's winners for every award, plus career leaderboards, which is enough to drive a full "Awards History" page with no per-season requests. Public read (no admin session needed), same as the other `GET /awards/*` routes.

### Which endpoint to use where

| Need | Endpoint |
|------|----------|
| History grid / timelines / leaderboards (this page) | `GET /awards/history` |
| Drill into one season, including finalists and vote tallies | `GET /awards/season/<league_year_id>` |
| One player's award shelf (modal tab, profile badges) | `GET /awards/player/<player_id>`, or the `awards` / `award_summary` keys already on `GET /stats/player/<player_id>` |
| Labels, grouping, display order | `award_types` inside the history response (identical to `GET /awards/types`, plus a `kind` field) |

### `GET /awards/history`

| Query param | Default | Meaning |
|-------------|---------|---------|
| `league_level` | `9` | Awards are only issued at MLB today. |
| `award_code` | all | Comma list to restrict, e.g. `mvp,cy_young`. An unknown code returns `400 validation_error`. |
| `from_year`, `to_year` | none | Inclusive bounds on the season's `league_year` (e.g. `2026`), not on `league_year_id`. |
| `include_finalists` | off | `1` also returns `rank > 1` / `is_winner: false` rows under `individual`. |
| `include_rosters` | off | `1` adds `players: [...]` to each championship team (≈28 per team). |
| `include_selections` | off | `1` adds `players: [...]` to each All-Star bucket. |
| `leaders_limit` | `25` | Cap on `leaders.players`; `0` = no cap. |

Booleans accept `1` / `true` / `yes`. A malformed integer is ignored and falls back to its default (no 400).

#### Response

```jsonc
{
  "league_level": 9,

  // The award catalog in DISPLAY ORDER (sort_order), filtered by ?award_code.
  // `kind` tells you which bucket of each season holds that award.
  "award_types": [
    { "code": "mvp", "name": "Most Valuable Player", "category": "major",
      "kind": "individual", "has_league_split": true, "is_per_position": false,
      "allows_multiple": false, "ptype_scope": "any", "sort_order": 10, "description": "..." },
    { "code": "silver_slugger", "kind": "individual", "is_per_position": true, ... },
    { "code": "pennant",       "kind": "championship", "has_league_split": true,  ... },
    { "code": "world_series",  "kind": "championship", "has_league_split": false, ... },
    { "code": "all_star",      "kind": "selection", ... }
  ],

  // Newest season first. Seasons with no awards (after filters) are omitted.
  "seasons": [
    {
      "league_year_id": 1,
      "league_year": 2026,

      // kind = individual: one winner per (award, league, position) slot.
      // Keyed by award_code; each value is a list sorted by league → position → rank.
      "individual": {
        "mvp": [
          { "award_id": 212, "player_id": 51708, "name": "Leonard Wickham",
            "first_name": "Leonard", "last_name": "Wickham", "ptype": "Position",
            "sub_league": "AL", "position_code": null,
            "rank": 1, "is_winner": true, "vote_points": null, "vote_share": null,
            "team": { "team_id": 14, "team_abbrev": "OAK", "team_city": "Oakland",
                      "team_name": "Oakland", "color_one": "#00352D", "color_two": "#EFB318" } },
          { "award_id": 191, "player_id": 51454, "name": "Tim Newman", "sub_league": "NL", ... }
        ],
        "silver_slugger": [ /* up to 2 leagues × N positions, position_code set */ ],
        "gold_glove":     [ /* same */ ]
      },

      // kind = championship: ONE entry per team (not per rostered player).
      "championships": {
        "pennant": [
          { "sub_league": "AL", "roster_size": 28, "series_result": "4-1",
            "team":     { "team_id": 19, "team_abbrev": "MIN", ... },
            "opponent": { "team_id": 2,  "team_abbrev": "TEX", ... } },
          { "sub_league": "NL", ... }
        ],
        "world_series": [
          { "sub_league": null, "roster_size": 28, "series_result": "4-2",
            "team": { "team_abbrev": "MIN", ... }, "opponent": { "team_abbrev": "CIN", ... },
            "players": [ /* only with ?include_rosters=1:
                            { player_id, name, first_name, last_name, ptype } */ ] }
        ]
      },

      // kind = selection: counts per league ("AL"/"NL"; "ALL" for an unsplit type).
      "selections": {
        "all_star": {
          "AL": { "count": 36, "players": [ /* only with ?include_selections=1:
                                                { player_id, name, ..., team } */ ] },
          "NL": { "count": 36 }
        }
      }
    }
  ],

  // Career leaderboards over the same filtered window (winners only; finalists never count).
  "leaders": {
    "players": [
      { "player_id": 51708, "name": "Leonard Wickham", "first_name": "...", "last_name": "...",
        "ptype": "Position",
        "trophies": 2,          // individual-award wins
        "selections": 0,        // All-Star selections
        "awards": { "mvp":            { "wins": 1, "years": [2026] },
                    "silver_slugger": { "wins": 1, "years": [2026] } } }
    ],                          // sorted trophies desc, then selections desc, then name
    "teams": [
      { "team_id": 19, "team_abbrev": "MIN", "team_city": "Minneapolis", "team_name": "Minnesota",
        "color_one": "#E41831", "color_two": "#02193E",
        "titles": { "world_series": { "count": 1, "years": [2026] },
                    "pennant":      { "count": 1, "years": [2026] } } }
    ]                           // sorted World Series titles desc, then all titles desc
  }
}
```

#### Field notes

- **Key order is not display order.** The API serialises object keys alphabetically, so `individual` / `championships` / `selections` come back as `cy_young, gold_glove, mvp, ...`. Always iterate `award_types` (already in `sort_order`) and look each code up in the season. Missing key = nobody won that award that season (e.g. `roy`, `comeback`, which are entered by hand).
- **`team` is the snapshot at award time** (the team the player was on when the award was recorded), not their current team. It can be `null` for a hand-entered award on a player with no active contract.
- **Championship `series_result` / `opponent`** come from the playoff engine. They are `null` for a title entered by hand through `POST /awards/team` without metadata. `series_result` is from the winner's side ("4-2").
- **Gold Glove includes `P`.** Each league has one Gold Glove per position, pitcher included (9 per league). Silver Slugger has 8 per league (no `P`, and `DH` only if it is entered).
- `ptype` is `"Pitcher"` or `"Position"`. Use it for an icon or to choose the modal's default tab.

### Building the page

**1. Season × Award grid (the main view).** Rows = `seasons` (newest first). Columns = `award_types` where `kind !== "selection"`, each split into AL / NL sub-columns when `has_league_split`. Cell = the matching entry from `season.individual[code]` (filter `sub_league`) or `season.championships[code]`. Render the player name + team abbrev chip (tint with `team.color_one`), or the team for championships. Leave per-position awards (`is_per_position`) out of the main grid and give them their own tab (see 3), otherwise the grid becomes 30+ columns.

**2. Award timeline ("change over time" for one trophy).** Either filter client-side, or call `?award_code=mvp`. Plot `league_year` on the x-axis and show AL and NL winners side by side per year. Repeat winners are easy to highlight: `leaders.players[].awards[code].wins > 1`, or count `player_id` occurrences across seasons.

**3. Positional awards tab.** For `silver_slugger` / `gold_glove`: rows = positions, columns = seasons, cell = winner per league. Group `season.individual[code]` by `position_code` then `sub_league`. Build the row list from the `position_code` values actually present (they are admin-entered) and sort them in a fixed order such as `C, 1B, 2B, 3B, SS, LF, CF, RF, DH, P`. Season 2026 has no `DH` Silver Slugger, for example.

**4. Champions banner / dynasty view.** Read `season.championships.world_series[0]` and `.pennant` per season for a "2026: MIN def. CIN 4-2" line. `leaders.teams` gives the "most titles" table directly. Season-by-season All-Star counts per team can be built with `?award_code=all_star&include_selections=1`.

**5. Career leaderboard.** `leaders.players` is ready-made: "Most decorated players", showing `trophies`, `selections` and the per-award badges `awards[code].wins` with `years`. Pass `leaders_limit=0` to page or filter client-side.

### Opening the player modal on click

Every player object in this response (individual winners, championship rosters, All-Star lists, leaders) carries `player_id`. That is the only key the existing player modal needs:

| Modal content | Call | Notes |
|---------------|------|-------|
| Stats tab + award shelf (`GetPlayerStats()` in `Modals.tsx`) | `GET /stats/player/<player_id>` | Season stats plus `awards`, `award_summary`, `total_awards`. Already includes this player's full award history, so the modal can render a trophy case with no extra call. |
| Ratings / bio (scouting modal) | `GET /scouting/player/<player_id>?org_id=<viewer org>&league_year_id=<current>` | Fog-of-war applies for the viewing org. Use the **current** `league_year_id`, not the award season's. |
| Game log for the award season | `GET /stats/player/<player_id>/gamelog?league_year_id=<season.league_year_id>` | Good for a "season in review" link from an award cell. |

Suggested behaviour: clicking a name in any cell opens the existing player modal with `player_id`; passing the cell's `league_year_id` as context lets the modal open on the season that award was won. Team chips (`team.team_id`) can link to the existing team page.

> **Known issue:** `GET /stats/player/<id>/career` currently returns a 500 (its SQL orders by a `league_years.season` column that does not exist). Don't wire a "Career" tab to it until that is fixed. `/stats/player/<id>` works.

### Caching

The data only changes when an admin records an award or a postseason series clinches, so caching the unfiltered response for the session (or a few minutes) is safe. The full payload is small: about 50 individual winners + 3 champion teams per season without the `include_*` flags.
