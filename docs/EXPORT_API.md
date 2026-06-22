# SimMLB Game Data Export API

A bulk, incremental export of completed game data — game results, full box scores
(per-player batting/pitching/fielding lines + substitutions), and MLB play-by-play.
Designed so you can fetch everything you need in **one request per refresh** instead of
crawling per-game endpoints.

- **Base URL:** `https://<your-app>.up.railway.app/api/v1`
- **Method:** all endpoints are `GET`.
- **Returns:** JSON, NDJSON (newline-delimited JSON), or CSV depending on the endpoint/`format`.

---

## Authentication

Send your API key in any one of these (in priority order):

```
Authorization: Bearer YOUR_KEY
X-Export-Key: YOUR_KEY
?api_key=YOUR_KEY            # query string, handy for quick tests
```

- Missing/invalid key → `401 {"error":"unauthorized"}`.
- Exceeding the rate limit → `429 {"error":"rate_limited"}`. Back off and retry.

Rate limit: a token bucket (default ~60 requests/min, bursts up to 20). Because the API is
**incremental**, you should rarely approach it — poll the cursor, then pull only new games.

---

## The incremental model (read this first)

Every game has a numeric `game_id` that only ever increases. Use it as a watermark:

1. **Check for new data** with `/games/export/cursor` → it returns `max_game_id`.
2. If it's higher than the last `game_id` you stored, **pull** with `since=<your stored game_id>`
   on any data endpoint. You only receive games newer than `since`.
3. Store the new `max_game_id` (returned in the response / the final NDJSON line, and as the
   `X-Max-Game-Id` header on CSV). Repeat next refresh.
4. If a pull returns `has_more: true`, immediately pull again with `since=<new max_game_id>` to
   page through the backlog until `has_more` is `false`.

This means you never re-download or re-process a game you already have.

### Common parameters (most endpoints)

| Param | Default | Meaning |
|---|---|---|
| `since` | `0` | Only games with `game_id > since`. Your watermark. |
| `limit` | varies | Max games returned this call. `0` = uncapped (stream everything). |
| `league_year_id` | — | Season filter (recommended — also speeds the query). |
| `season_week` | — | Filter to one week. |
| `league_level` | — | `9` = MLB, `3` = college, etc. |
| `team_id` | — | Games where this team was home or away. |
| `game_type` | `regular` | `regular`, `playoff`, `allstar`, `wbc`, or `all`. |
| `format` | varies | `json`, `ndjson`, or `csv` (per endpoint). |

Only **completed** games are returned.

### NDJSON format

Streaming endpoints return `application/x-ndjson`: **one JSON object per line.** Parse line by
line (don't wait for the whole body). The **final line** is a metadata object:

```json
{"_meta": {"max_game_id": 58231, "count": 142, "has_more": false}}
```

Since games stream in ascending `game_id` order, the last game's `game_id` is also your new
watermark.

---

## Endpoints

### 1. `GET /games/export/cursor` — "is there new data?"

Cheap check. Returns the highest `game_id` and match count for your filter.

```
GET /games/export/cursor?league_year_id=2026
→ {"max_game_id": 58231, "count": 1420}
```

Params: `league_year_id`, `season_week`, `league_level`, `team_id`, `game_type`.

---

### 2. `GET /games/export` — per-game team totals

One row per game with **home/away aggregate** stats. Smallest payload; good for standings/ranking.

Params: common params above + `format=json` (default) or `csv`. `limit` default `1000`.

**JSON response:**
```json
{ "games": [ { ...game row... } ], "count": 142, "max_game_id": 58231, "has_more": false }
```

**Each game row:**
`game_id, season, season_week, season_subweek, league_level, game_type, completed_at, venue,
home_team_id, home_team_abbrev, home_team_name, away_team_id, away_team_abbrev, away_team_name,
home_runs, away_runs, home_at_bats, away_at_bats, home_hits, away_hits, home_doubles,
away_doubles, home_triples, away_triples, home_home_runs, away_home_runs, home_walks, away_walks,
home_hit_by_pitch, away_hit_by_pitch, home_strikeouts, away_strikeouts, home_steals, away_steals,
home_caught_stealing, away_caught_stealing, home_sacrifice_flies,
away_sacrifice_flies, home_innings_pitched, away_innings_pitched, home_innings_pitched_outs,
away_innings_pitched_outs, home_earned_runs, away_earned_runs`

Notes: `home_runs`/`away_runs` are **final scores** (home runs are `home_home_runs`).
`*_innings_pitched` is `"X.Y"` notation (Y = thirds, 0–2); `*_innings_pitched_outs` is the raw
out count (use this for math). CSV adds the `X-Max-Game-Id` response header.

```
GET /games/export?league_year_id=2026&format=csv&limit=0      # full season as CSV
GET /games/export?league_year_id=2026&since=58000             # only new games
```

---

### 3. `GET /games/export/boxscores` — full structured box scores (all levels)

One game per NDJSON line, each with linescore + per-player lines + substitutions. This replaces
crawling `/boxscore` per game.

Params: common params + `format=ndjson` (default) or `json`. `limit` default `1000`.

**Each game object:**
```jsonc
{
  "game_id": 58231, "season": 2026, "season_week": 6, "season_subweek": "b",
  "league_level": 9, "game_type": "regular", "completed_at": "2026-05-03 14:22:10",
  "venue": "Truist Park",
  "home_team": { "id": 12, "abbrev": "ATL", "name": "Atlanta Braves", "score": 5, "won": true },
  "away_team": { "id": 30, "abbrev": "WAS", "name": "Washington Nationals", "score": 3, "won": false },
  "game_outcome": "...",
  "linescore": {
    "innings": [ {"home":0,"away":1}, ... ],   // null for non-MLB (no play-by-play stored)
    "home": { "R": 5, "H": 10, "E": 0 },
    "away": { "R": 3, "H": 7,  "E": 1 }
  },
  "batting":  { "home": [ <batting line> ], "away": [ ... ] },
  "pitching": { "home": [ <pitching line> ], "away": [ ... ] },
  "fielding": { "home": [ <fielding line> ], "away": [ ... ] },
  "substitutions": [ <sub> ]
}
```

**Batting line:** `player_id, team_id, name, at_bats, runs, hits, doubles_hit, triples,
home_runs, inside_the_park_hr, rbi, walks, hbp, strikeouts, stolen_bases, caught_stealing,
plate_appearances` — plus (when available) `sacrifice_flies, gidp, ground_balls, fly_balls,
popups, contact_barrel, contact_solid, contact_flare, contact_burner, contact_under,
contact_topped, contact_weak`.

**Pitching line:** `player_id, team_id, name, pitch_appearance_order, games_started, win, loss,
save_recorded, hold, blown_save, quality_start, innings_pitched_outs, innings_pitched (X.Y),
hits_allowed, runs_allowed, earned_runs, walks, strikeouts, home_runs_allowed,
inside_the_park_hr_allowed, pitches_thrown, balls, strikes, hbp, wildpitches` — plus (when
available) `batters_faced, sacrifice_flies_allowed, gidp_induced, ground_balls_allowed,
fly_balls_allowed, popups_allowed, inherited_runners, inherited_runners_scored, contact_*`.

**Fielding line:** `player_id, team_id, name, position_code, innings, putouts, assists, errors`
— plus (when available) `double_plays`.

**Substitution:** `inning, half, sub_type, player_in_id, player_in_name, player_out_id,
player_out_name, new_position, entry_score_diff, entry_runners_on, entry_inning, entry_outs,
entry_is_save_situation`.

```
GET /games/export/boxscores?league_year_id=2026&since=58000          # NDJSON, new games
GET /games/export/boxscores?league_year_id=2026&season_week=6&format=json
```

---

### 4. `GET /games/export/play-by-play` — pitch-by-pitch (MLB only)

Normalized per-action play-by-play. **MLB (level 9) only** — play-by-play is not stored for
other levels. One game per NDJSON line.

Params: `league_year_id`, `season_week`, `team_id`, `since` (0), `limit` (default `500`,
`0`=uncapped), `granularity` (`at_bat` default | `action`), `include_events` (`0`|`1`),
`format` (`ndjson` default | `json`).

- `granularity=at_bat` (default): plays grouped into at-bats with a `result`, `result_detail`,
  base/score state, and a human-readable `description`. Set `include_events=1` to also get the
  ordered pitch/pickoff/steal stream inside each at-bat.
- `granularity=action`: a flat list of normalized individual actions (richer, standalone — each
  carries its own inning/half/batter/pitcher/score context).

**Event shapes** (inside `at_bats[].events`, lean projections):
- pitch: `{ "kind": "pitch", "balls", "strikes", "pitch", "swing", "result" }` — `result`/`swing`
  are the *pitch-level* engine strings (e.g. `"Ball"`, `"Looking"`; for a batted ball `result` is
  the contact tier like `"flare"`). `pitch` is the pitch type (e.g. `"Fastball"`).
- steal / pickoff: `{ "kind", "result", "runner" }` — `result` is the baserunning enum
  (`"stolen_base"`, `"caught_stealing"`, `"unsuccessful_pickoff"`, …); `runner` is the actor and
  **may be `null`** (the engine does not yet emit the runner id for these — see Notes).

**Each game object (`at_bat` granularity):**
```jsonc
{
  "schema_version": 2, "game_id": 58231, "teams": { "home": "ATL", "away": "WAS" },
  "at_bats": [
    {
      "seq": 7, "inning": 1, "half": "bottom", "outs_before": 2, "outs_after": 2,
      "batter": { "id": 2002, "name": "Jordan Park" },
      "pitcher": { "id": 1009, "name": "Max Knox" },
      "result": "single",
      "result_detail": { "batted_ball": "flare", "air_or_ground": "air",
                         "hit_depth": "deep_if", "hit_direction": "right",
                         "fielder": { "id": 1009, "name": "Max Knox" }, "errors": [] },
      "rbi": 0, "runs_scored": [],
      "runners_after": { "1B": {"id":2002,"name":"Jordan Park"}, "2B": null, "3B": null },
      "score_after": { "home": 0, "away": 0 },
      "events": [   // only when include_events=1; ordered, mixed kinds
        { "kind": "pitch", "balls": 1, "strikes": 0, "pitch": "Fastball",
          "swing": "Looking", "result": "Ball" },
        { "kind": "steal", "result": "caught_stealing", "runner": { "id": 2003, "name": "Casey Reed" } }
      ],
      "description": "Jordan Park singles (flare to deep right)."
    }
  ]
}
```

```
GET /games/export/play-by-play?league_year_id=2026&since=58000
GET /games/export/play-by-play?league_year_id=2026&granularity=at_bat&include_events=1&limit=10
```

---

## Recommended refresh loop (pseudocode)

```python
cursor = load_saved_cursor()            # 0 on first run
latest = GET("/games/export/cursor", league_year_id=2026)["max_game_id"]
if latest > cursor:
    while True:
        resp = GET("/games/export/boxscores", league_year_id=2026, since=cursor)  # NDJSON
        for line in resp.iter_lines():
            obj = json.loads(line)
            if "_meta" in obj:
                cursor = obj["_meta"]["max_game_id"]
                more = obj["_meta"]["has_more"]
            else:
                process(obj)
        save_cursor(cursor)
        if not more:
            break
```

## Notes & limits

- Only **completed** games appear.
- Play-by-play is **MLB only**; all other data (box scores, lines, subs) covers every level.
- Streaming endpoints default to NDJSON — parse line by line for constant memory.
- `format=json` responses are gzip-compressed when you send `Accept-Encoding: gzip`. NDJSON
  streams are sent uncompressed (streamed line-by-line for low latency); if bandwidth matters
  more than streaming for a given pull, request `format=json` to get a single compressed payload.
- Player/team identity is included inline (ids + names); no separate lookup needed.
- The API exposes only public, frontend-visible stats — no scouting/attribute data.
- Steal/pickoff `runner` may be `null`: the engine currently records the batter at the plate, not
  the runner who is the actor, so the actor can't always be resolved. Render these from
  `description` (which degrades to "Runner …") until the engine emits the runner id.
