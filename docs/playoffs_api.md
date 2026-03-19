# Playoffs API Reference

All endpoints are registered under the `/api/v1` prefix via the `playoffs_bp` blueprint.

---

## 1. Get Bracket State

The primary endpoint for rendering a bracket UI. Returns every series grouped by round, with team info, win counts, and completion status.

```
GET /api/v1/playoffs/bracket/{league_year_id}/{league_level}
```

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `league_year_id` | int | The league year ID (e.g. `1`, `2`) |
| `league_level` | int | `9` = MLB, `8` = AAA, `7` = AA, `6` = High-A, `5` = A, `3` = College |

### Response (200)

```jsonc
{
  "league_year_id": 1,
  "league_level": 9,
  "rounds": {
    "WC": [
      {
        "series_id": 1,
        "conference": "AL",           // "AL", "NL", or null (MiLB/WS/CWS)
        "team_a": {
          "id": 101,
          "abbrev": "NYY",
          "seed": 3
        },
        "team_b": {
          "id": 115,
          "abbrev": "MIN",
          "seed": 6
        },
        "wins_a": 2,
        "wins_b": 1,
        "series_length": 3,           // 1, 3, 5, or 7
        "status": "complete",         // "pending" | "active" | "complete"
        "winner": {                   // null if series not yet decided
          "id": 101,
          "abbrev": "NYY"
        }
      }
      // ... more series in this round
    ],
    "DS": [ /* ... */ ],
    "CS": [ /* ... */ ],
    "WS": [ /* ... */ ]
  },

  // Only present when league_level == 3 (College World Series)
  "cws_bracket": [
    {
      "team_id": 501,
      "team_abbrev": "LSU",
      "seed": 1,
      "qualification": "conf_champ",  // "conf_champ" | "at_large"
      "losses": 0,                    // 0 or 1 (2 = eliminated)
      "eliminated": false,
      "bracket_side": "winners"       // "winners" | "losers" | "eliminated"
    }
    // ... 8 teams total
  ]
}
```

### Round Keys by League Level

| Level | Rounds (in progression order) |
|-------|-------------------------------|
| 9 (MLB) | `WC` → `DS` → `CS` → `WS` |
| 5-8 (MiLB) | `QF` → `SF` → `F` |
| 3 (CWS) | `CWS_W1`, `CWS_W2`, `CWS_W3`, `CWS_L1`, `CWS_L2`, `CWS_L3`, `CWS_F1`, `CWS_F2` |

### Series Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Series created, no games played yet |
| `active` | At least one game played, not yet clinched |
| `complete` | A team has clinched (winner is set) |

### How to Derive Game Number

The current game number for an active series is `wins_a + wins_b + 1`. The clinch number (wins needed) is:

| `series_length` | Clinch at |
|-----------------|-----------|
| 1 | 1 win |
| 3 (Bo3) | 2 wins |
| 5 (Bo5) | 3 wins |
| 7 (Bo7) | 4 wins |

### Home-Field Patterns

Higher seed (`team_a`) hosts according to these patterns (1 = home, 0 = away):

| Series | Pattern (by game #) |
|--------|-------------------|
| Bo3 | H, H, H |
| Bo5 | H, H, A, A, H |
| Bo7 | H, H, A, A, A, H, H |

### Conference / Seeding Notes

- **MLB (level 9)**: Seeds 1-2 per conference get first-round byes (not in WC round). Seeds 3-6 play WC. DS matchups: #1 vs lowest surviving seed, #2 vs other.
- **MiLB (levels 5-8)**: Top 8 by record. QF: 1v8, 2v7, 3v6, 4v5. No conferences.
- **CWS (level 3)**: Conference champs + at-large bids. Double elimination. Use `cws_bracket` array for bracket-side tracking.

---

## 2. Get Pending Games

Returns unsimulated playoff games — useful for showing "up next" in the bracket UI or a schedule view.

```
GET /api/v1/playoffs/pending-games/{league_year_id}/{league_level}
```

### Response (200)

```jsonc
{
  "games": [
    {
      "game_id": 4521,
      "away_team": 115,
      "home_team": 101,
      "away_abbrev": "MIN",
      "home_abbrev": "NYY",
      "season_week": 53,
      "season_subweek": "b",
      "series_id": 1,
      "round": "WC",
      "series_number": 1,
      "wins_a": 1,                 // series state BEFORE this game
      "wins_b": 0,
      "series_length": 3,
      "series_status": "active"
    }
  ]
}
```

Games are ordered by `season_week`, `season_subweek`, `round`, `series_number`.

---

## 3. Get Special Events / Playoff Status Overview

High-level overview of which league levels have active playoffs, how many series are complete, etc.

```
GET /api/v1/special-events?league_year_id={lyid}&event_type=playoff
```

### Query Parameters (all optional)

| Param | Type | Description |
|-------|------|-------------|
| `league_year_id` | int | Filter to specific league year |
| `event_type` | string | `"playoff"`, `"allstar"`, or `"wbc"` |

### Response (200)

```jsonc
{
  "events": [
    {
      "id": null,                    // null for playoff entries
      "league_year_id": 1,
      "event_type": "playoff",
      "league_level": 9,
      "status": "in_progress",       // "in_progress" | "complete"
      "total_series": 13,
      "completed_series": 4,
      "latest_round": "DS",
      "created_at": null,
      "completed_at": null
    }
  ]
}
```

---

## 4. Game Results for Playoff Games

Playoff game results are stored in the standard `game_results` table with `game_type = 'playoff'`. They can be queried via the existing game results endpoints. Key fields per result:

```jsonc
{
  "game_id": 4520,
  "home_team_id": 101,
  "away_team_id": 115,
  "home_score": 5,
  "away_score": 3,
  "winning_team_id": 101,
  "losing_team_id": 115,
  "game_outcome": "HOME_WIN",     // "HOME_WIN" | "AWAY_WIN"
  "game_type": "playoff",
  "boxscore_json": { /* ... */ },
  "play_by_play_json": { /* ... */ },
  "completed_at": "2026-10-01 20:30:00"
}
```

To get all playoff results for a bracket, query `game_results` where `game_type = 'playoff'` and filter by season/league_level. The `game_id` in each pending game (endpoint #2) and the `game_id` in `game_results` are the same key, so you can match completed games to their series.

---

## Data Model Summary

### `playoff_series` (one row per matchup)

| Column | Type | Notes |
|--------|------|-------|
| `id` | int | Primary key |
| `league_year_id` | int | FK to league_years |
| `league_level` | int | 3, 5-9 |
| `round` | varchar(30) | WC, DS, CS, WS, QF, SF, F, CWS_W1, etc. |
| `series_number` | int | 1-based within a round+conference |
| `team_a_id` | int | Higher seed (home-field advantage) |
| `team_b_id` | int | Lower seed |
| `seed_a` | int | Seed number of team_a |
| `seed_b` | int | Seed number of team_b |
| `wins_a` | int | Games won by team_a |
| `wins_b` | int | Games won by team_b |
| `series_length` | int | 1, 3, 5, or 7 |
| `status` | varchar(20) | pending / active / complete |
| `winner_team_id` | int | NULL until clinched |
| `start_week` | int | Season week the series begins |
| `conference` | varchar(5) | AL, NL, or NULL |

### `cws_bracket` (one row per team, level 3 only)

| Column | Type | Notes |
|--------|------|-------|
| `team_id` | int | FK to teams |
| `seed` | int | 1-8 |
| `qualification` | varchar(20) | conf_champ / at_large |
| `losses` | int | 0-2 (2 = eliminated) |
| `eliminated` | tinyint | 0 or 1 |
| `bracket_side` | varchar(20) | winners / losers / eliminated |

---

## Frontend Rendering Guide

### MLB Bracket (level 9)

```
Wild Card (Bo3)                Division Series (Bo5)        Championship (Bo7)     World Series (Bo7)
┌─────────────┐
│ AL #3 vs #6 │─┐
└─────────────┘  ├──► AL DS1: #1 vs lowest WC ──┐
  (bye: AL #1)  ─┘                                ├──► ALCS ──┐
┌─────────────┐                                   │           │
│ AL #4 vs #5 │─┐                                 │           │
└─────────────┘  ├──► AL DS2: #2 vs other WC  ──┘           │
  (bye: AL #2)  ─┘                                            ├──► World Series
                                                              │
┌─────────────┐                                               │
│ NL #3 vs #6 │─┐                                            │
└─────────────┘  ├──► NL DS1: #1 vs lowest WC ──┐           │
  (bye: NL #1)  ─┘                                ├──► NLCS ──┘
┌─────────────┐                                   │
│ NL #4 vs #5 │─┐                                 │
└─────────────┘  ├──► NL DS2: #2 vs other WC  ──┘
  (bye: NL #2)  ─┘
```

To render:
1. Fetch `GET /playoffs/bracket/{lyid}/9`
2. `rounds.WC` → 4 series (2 AL, 2 NL), filter by `conference`
3. `rounds.DS` → 4 series (only present after WC completes + advance)
4. `rounds.CS` → 2 series (one per conference)
5. `rounds.WS` → 1 series (no conference)
6. Seeds 1 & 2 per conference are bye teams — they appear in DS but not WC. To show them in the bracket, query `rounds.DS` for their `seed_a` values.

### MiLB Bracket (levels 5-8)

```
Quarterfinals (Bo7)     Semifinals (Bo7)      Finals (Bo7)
┌──────────┐
│ #1 vs #8 │──┐
└──────────┘   ├──► SF1 ──┐
┌──────────┐   │          │
│ #4 vs #5 │──┘          ├──► Finals
└──────────┘              │
┌──────────┐              │
│ #2 vs #7 │──┐          │
└──────────┘   ├──► SF2 ──┘
┌──────────┐   │
│ #3 vs #6 │──┘
└──────────┘
```

### CWS Bracket (level 3) — Double Elimination

Use the `cws_bracket` array to track team positions. Teams with `losses: 0` are in winners bracket, `losses: 1` are in losers bracket, `eliminated: true` are out. Series rounds are named `CWS_W1`, `CWS_W2`, `CWS_L1`, `CWS_L2`, `CWS_F1`, etc.

---

## Polling / Live Updates

For a live bracket experience:

1. Poll `GET /playoffs/bracket/{lyid}/{level}` periodically (e.g. every 10-30s during simulation)
2. Check `wins_a`, `wins_b`, `status`, and `winner` fields for changes
3. Poll `GET /playoffs/pending-games/{lyid}/{level}` to show upcoming matchups
4. The `status` field transitions: `pending` → `active` → `complete`
5. When all series in `rounds[current_round]` have `status: "complete"`, the next round's data will appear after the admin advances the round
