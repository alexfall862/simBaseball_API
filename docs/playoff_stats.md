# Postseason stats (frontend note)

Playoff games no longer count toward regular-season totals.

## Tables

| Regular season           | Postseason (playoff games only)   |
|--------------------------|-----------------------------------|
| `player_batting_stats`   | `player_batting_stats_playoff`    |
| `player_pitching_stats`  | `player_pitching_stats_playoff`   |
| `player_fielding_stats`  | `player_fielding_stats_playoff`   |

* The `_playoff` tables are exact clones (`CREATE TABLE ... LIKE`) and are keyed
  the same way: `(player_id, league_year_id, team_id)` for batting/pitching and
  `(player_id, league_year_id, team_id, position_code)` for fielding.
* Routing is by `gamelist.game_type`: `regular` -> regular tables, `playoff` ->
  `_playoff` tables, `allstar` / `wbc` -> neither (box scores only).
* Per-game box score tables (`game_batting_lines`, `game_pitching_lines`,
  `game_fielding_lines`, `game_substitutions`) are unchanged and hold every game
  type; the gamelog endpoints keep working as before.
* Re-simulating a playoff game reverses and re-applies the `_playoff` tables.
* Migration: `migrations/add_playoff_stat_tables.sql` (the API also creates the
  tables automatically the first time a playoff game is accumulated).

## API

### Leaderboards: `stat_type` query param

`GET /stats/batting`, `GET /stats/pitching`, `GET /stats/fielding` accept an
optional `stat_type`:

| value     | reads from            |
|-----------|-----------------------|
| `regular` | regular tables (**default**) |
| `playoff` | `_playoff` tables     |

Any other value returns `400 {"error": "invalid_type"}`. All other params
(`league_year_id`, `league_level`, `team_id`, `position`, `sort`, `min_pa`,
paging, ...) behave identically. The response now echoes `"stat_type"` next to
`leaders`/`total`/`page`/`pages`.

Leaderboards default to the regular season, so existing calls are unaffected.
Example: `GET /stats/batting?league_year_id=3&league_level=9&stat_type=playoff&sort=ops`

Notes for `stat_type=playoff`:

* `min_pa` / `min_ip` / `min_inn` thresholds apply to the postseason totals, so
  use small values (or 0).
* League-average context (wOBA/wRC+, FIP constant) is computed from the
  postseason pool itself; WAR replacement level still comes from the regular
  season context, so treat postseason WAR as indicative only.
* Before the first playoff game of a database's life the tables may not exist
  yet; the request then returns `500 database_error` until a playoff game has
  been simulated or the migration has been applied.

### Player page: `postseason` key

`GET /stats/player/<id>` (optionally `?league_year_id=`) now also returns

```json
"postseason": {
  "batting":  [ ...same row shape as "batting"  ],
  "pitching": [ ...same row shape as "pitching" ],
  "fielding": [ ...same row shape as "fielding" ]
}
```

Rows are per `league_year_id` + `team_id` (+ `pos` for fielding), exactly like
the top-level arrays. The arrays are empty when the player has no playoff games
(or the tables do not exist yet); the endpoint never fails because of them.
