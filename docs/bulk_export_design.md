# Bulk Game-Data Export Suite — Design

Status: **IMPLEMENTED (2026-06-22).** All four tiers, the v2 normalizer, and the
auth/rate-limit wrapper are built (compile-clean; normalizer unit-tested 15/15).
Not yet runtime-tested against a live DB. Endpoints:
`GET /api/v1/games/export{,/cursor,/boxscores,/play-by-play}`. Heavy logic lives in
`services/game_export.py`; PBP normalization in `services/pbp_normalize.py`; routes +
auth in `games/__init__.py`. Auth via env: `EXPORT_API_KEYS` (comma-separated; enforced
only when set), `EXPORT_RATE_PER_MIN` (default 60), `EXPORT_BURST` (default 20).
The `Catch Probability` strip typo was already corrected in `game_payload.py:149`.

Driver: a power user ("Ezaco") runs a third-party ranking/analytics tool that currently
crawls per-game endpoints (`/games/<id>/boxscore`, `/games/<id>/play-by-play`) **one game
at a time**, creating heavy, repeated DB load. Goal: expose as much *frontend-available*
game data as possible, as easily parseable as possible, in as few requests as possible —
while **never** exposing anything not shown to players (raw/non-fuzzied attributes, ballpark
hitting weights, engine internals, RNG).

Companion docs: `docs/play_by_play_schema.md` (PBP raw schema + v2 normalization — this design
depends on it), `docs/SUPPORT_TICKETS.md` (MLB-10/MLB-17 origin).

Confirmed product decisions (2026-06-22):
- PBP delivered in the **normalized v2 shape** (build `services/pbp_normalize.py`).
- PBP is **MLB-only** (matches what's stored; no new storage for other levels).
- Export suite is gated by an **API key + rate limit**.
- This document is **plan-only**; implement after sign-off.

---

## 1. Architecture — a tiered suite on one shared contract

Four endpoints, all under `/api/v1/games/export*`, sharing one incremental contract. Tiered
(not one mega-payload) because PBP is ~388 KB/game while structured lines are bytes — bundling
would force a PBP download even when only box scores are wanted, defeating the traffic goal.

| Tier | Endpoint | Payload | Levels | Status |
|---|---|---|---|---|
| 0 | `GET /games/export/cursor` | just `max_game_id` + counts | all | NEW |
| 1 | `GET /games/export` | per-game home/away aggregates | all | **built** |
| 2 | `GET /games/export/boxscores` | per-game structured: lines + subs + fielding + linescore | all | NEW |
| 3 | `GET /games/export/play-by-play` | normalized v2 per-action | MLB only | NEW |

### Shared contract (all tiers)
- **Incremental watermark:** `since=<game_id>` → returns only `game_id > since`, ordered
  `game_id ASC`; response carries `max_game_id` (body) and `X-Max-Game-Id` (header). `game_id`
  is gap-free (autoincrement on `gamelist.id` = `game_results.game_id`). This is the primary
  long-term load reducer: historical games are never re-pulled or re-processed.
- **Filters:** `league_year_id` (→ `game_results.season`; also scopes line-table aggregates for
  index use), `season_week`, `league_level`, `team_id`, `game_type` (default `regular`, `all`
  for every type).
- **Paging:** `limit` (default 1000; `limit=0` = uncapped). `has_more` true when a full page is
  returned. Keyset on `game_id` (no OFFSET).
- **Streaming + format:** tiers 2–3 stream **NDJSON** (`application/x-ndjson`, one game object
  per line) so neither server nor client buffers the whole set; `?format=json` returns a single
  array for small pulls; `?format=csv` (flat tiers only) for spreadsheet use. Honor
  `Accept-Encoding: gzip` (PBP compresses ~10×).
- **Auth + rate limit:** see §5.

### Why this cuts Ezaco's long-term load
1. `cursor` lets him cheaply check for new data before pulling anything.
2. `since=` means he only ever transfers/parses **new** games.
3. NDJSON streaming = constant memory on both ends.
4. gzip on PBP.
5. Serve stored blobs / single grouped queries — no per-game re-assembly.

---

## 2. The safety model — strict allowlist, not denylist

**Non-negotiable:** every field in every tier is chosen from an explicit **allowlist** below.
We do **not** echo stored rows/blobs wholesale. Rationale:
- The raw engine PBP embeds private internals — `Interaction_Data`, `At_Bat_Modifiers`,
  `Timing_Diagnostics` (raw non-fuzzied ratings like `adv_contact`/`pitch_ovr`, probability
  tables, RNG/decision values). These are stripped at storage **by a denylist that has a bug**
  (`_PBP_STRIP_KEYS` lists `Catch_Probability` but the real key is `Catch Probability` (space),
  so that internal float currently leaks) — see `services/game_payload.py:145-153`. A denylist
  also silently leaks any *new* internal field the engine later adds.
- An allowlist guarantees only the enumerated public fields ever leave the building, regardless
  of what the engine emits or how storage trims it.

Game stat data is otherwise safe to export with **no per-org fuzzing**: fog-of-war
(`rosters/__init__.py:_apply_fog_of_war`) applies only to player *attributes*, and box-score
endpoints never select attributes — only `firstName`/`lastName` for display.

### Columns excluded everywhere (and why)
- `stamina_cost` (batting/pitching lines) — engine-internal fatigue input, never shown to
  players (omitted by the boxscore today).
- `league_year_id` (all line/sub tables) — internal FK, redundant with `game_results.season`.
- `random_seed` (`gamelist`) — engine RNG seed.
- `boxscore_json`, `play_by_play_json` raw blobs — replaced by structured/normalized output.
- All PBP engine-diagnostic blocks + `Catch Probability` (see §4).
- Internal autoincrement `id` on each line/sub table (use `game_id` + `player_id`).

---

## 3. Tier 2 — `/games/export/boxscores` (structured, all levels)

One NDJSON object per game. Replaces the bulk of the per-game `/boxscore` crawl and surfaces
data **no endpoint currently exposes** (`game_fielding_lines`, batted-ball/contact columns).

```jsonc
{
  "game_id": 58231, "season": 2026, "season_week": 6, "season_subweek": "b",
  "league_level": 9, "game_type": "regular", "completed_at": "2026-05-03 14:22:10",
  "venue": "Truist Park",
  "home_team": { "id": 12, "abbrev": "ATL", "name": "Atlanta Braves", "score": 5,
                 "won": true },
  "away_team": { "id": 30, "abbrev": "WAS", "name": "Washington Nationals", "score": 3,
                 "won": false },
  "linescore": { "innings": [ {"home":0,"away":1}, ... ],
                 "home": {"R":5,"H":10,"E":0}, "away": {"R":3,"H":7,"E":1} },
  "batting":  { "home": [ <batting line>, ... ], "away": [ ... ] },
  "pitching": { "home": [ <pitching line>, ... ], "away": [ ... ] },
  "fielding": { "home": [ <fielding line>, ... ], "away": [ ... ] },
  "substitutions": [ <sub>, ... ]
}
```

`linescore` is derived from PBP for MLB; for non-MLB (no PBP) ship `innings: null` and the
team R/H/E totals from the line aggregates. Names from a single `simbbPlayers` join keyed by
the game's player_ids (no per-row query).

### Allowlists (source → exported fields)

**batting line** (`game_batting_lines`, schema `railway_game_batting_lines.sql`):
`player_id, name, team_id, position_code, batting_order, plate_appearances, at_bats, runs,
hits, doubles_hit, triples, home_runs, inside_the_park_hr, rbi, walks, hbp, strikeouts,
stolen_bases, caught_stealing` — plus, **if the expansion migration is applied** (presence-check
via `information_schema`, as the built endpoint already does): `sacrifice_flies, gidp,
ground_balls, fly_balls, popups, contact_barrel, contact_solid, contact_flare, contact_burner,
contact_under, contact_topped, contact_weak`.
Exclude: `stamina_cost`, `league_year_id`, `id`.

**pitching line** (`game_pitching_lines`): `player_id, name, team_id, pitch_appearance_order,
games_started, win, loss, save_recorded, hold, blown_save, quality_start, innings_pitched_outs,
innings_pitched (X.Y string), hits_allowed, runs_allowed, earned_runs, walks, strikeouts,
home_runs_allowed, inside_the_park_hr_allowed, pitches_thrown, balls, strikes, hbp, wildpitches`
— plus migration: `batters_faced, sacrifice_flies_allowed, gidp_induced, ground_balls_allowed,
fly_balls_allowed, popups_allowed, inherited_runners, inherited_runners_scored, contact_*_allowed`.
Exclude: `stamina_cost`, `league_year_id`, `id`.

**fielding line** (`game_fielding_lines` — *not exposed by any current endpoint*):
`player_id, name, team_id, position_code, innings, putouts, assists, errors` — plus migration
`double_plays`. Exclude: `league_year_id`, `id`.

**substitution** (`game_substitutions`): `inning, half, sub_type, player_in_id, player_in_name,
player_out_id, player_out_name, new_position, entry_score_diff, entry_runners_on, entry_inning,
entry_outs, entry_is_save_situation`. Exclude: `league_year_id`, `id`.

**game meta** (`game_results`): `game_id, season, season_week, season_subweek, league_level,
game_type, completed_at, home/away_team_id, home/away_score, winning_team_id, game_outcome`,
venue via `teams.ballpark_name`. Exclude: `boxscore_json`, `play_by_play_json`.

Query shape: one keyset query over `game_results` (filtered + `since`), then **one** batched
query per line table `WHERE game_id IN (<page>)` (or a join), grouped in Python by `game_id`
and home/away team — no N+1.

---

## 4. Tier 3 — `/games/export/play-by-play` (normalized v2, MLB only)

Built on `services/pbp_normalize.py` (the Phase-2 module proposed in
`docs/play_by_play_schema.md`). Per game, the stored `play_by_play_json` is normalized to the
**v2 at-bat / action shape** (snake_case, real arrays, `null` not `"None"`, parsed `Outcomes`,
repaired `Error List`, generated `description`). NDJSON, one game per line:

```jsonc
{ "schema_version": 2, "game_id": 58231, "teams": {"home":"ATL","away":"WAS"},
  "at_bats": [ { "seq": 7, "inning": 1, "half": "bottom", "batter": {...},
                 "pitcher": {...}, "result": "single", "result_detail": {...},
                 "runs_scored": [...], "runners_after": {...}, "score_after": {...},
                 "events": [ {"kind":"pitch", ...} ],   // include_events=1
                 "description": "..." } ] }
```

Params: `since`, `league_year_id`, `season_week`, `team_id`, `granularity=at_bat|action`,
`include_events=0|1`, `format=ndjson|json`. Always MLB; reject/ignore non-MLB levels with a
clear note (no PBP stored).

### PBP allowlist (the only fields the normalizer may read from a raw action)
Context: `ID, Inning, Inning Half, Home Team, Away Team, Home Score, Away Score, Ball Count,
Strike Count, Out Count, Outs this Action, Pre_Outs`.
Participants (`{player_id, player_name}`): `Batter, Pitcher, Catcher, First Base, Second Base,
Third Base, Shortstop, Left Field, Center Field, Right Field, Targeted Defender`.
Outcome: `Outcomes` (parsed), `Batted Ball, Air or Ground, Hit Depth, Hit Direction,
Hit Situation, Defensive Outcome, Defensive Actions` (parsed), `Error List` (parsed/repaired),
`Error_Count`.
Baserunners: `On First, On Second, On Third, Home, Runners_Scored, Runners_Scored_IDs`.
Flags: all `Is_*`, `AB_Over`, `WP_Descriptions`.

**Explicitly NOT read / never exported:** `Interaction_Data`, `At_Bat_Modifiers`,
`Timing_Diagnostics`, `Pre_R1/R2/R3`, and **`Catch Probability`** (internal model float; strip
it for export and fix the denylist typo at the storage layer as a side cleanup).

Because the normalizer builds output from this allowlist, no engine internal can leak even
though the stored denylist is imperfect.

> Dependency: the v2 `result`/description mapping has open items for the engine owner
> (full `Defensive Outcome` enum, `Error List` source format, pickoff/steal runner identity) —
> see `docs/play_by_play_schema.md` §5. The normalizer ships with safe fallbacks (degrade to
> `[]`/`null`, never propagate malformed data) so it is not blocked on those answers.

---

## 5. Auth + rate limiting

The games blueprint currently has **no auth** (`app.py:202`); existing `before_request` hooks
do request-id, a rate-limit log, and pool-pressure log only (`app.py:395-430`). For a heavy
third-party consumer:

- **API key:** require `Authorization: Bearer <key>` (or `X-Export-Key`) on `/games/export*`.
  Validate against a small `export_api_keys` table (`key_hash, label, active, created_at`) or,
  minimally, an env-configured key set. Keys are revocable and attributable.
- **Rate limit:** per-key (and per-IP fallback) limit on the export routes — e.g. token bucket,
  N requests/minute + a concurrency cap of 1–2 (these are DB-heavy). Reuse/extend the existing
  rate-limit hook rather than adding a new dependency.
- Apply only to `/games/export*`, leaving the rest of `/api/v1/games` unchanged.
- Document the key handoff + limits for Ezaco.

---

## 6. Build plan (after sign-off)

1. **Tier 0 + 2** — `cursor` + `boxscores`: allowlisted SELECTs, batched line queries, NDJSON
   streaming, `information_schema` guard for migration columns, CSV for flat tiers. Highest
   value, all levels, lowest risk.
2. **`services/pbp_normalize.py`** — pure, unit-tested normalizer (Phase 2 of the PBP doc);
   consolidate the duplicated ingestion blocks and fix the `Catch Probability` strip typo while
   there.
3. **Tier 3** — `play-by-play` export on the normalizer, NDJSON + gzip.
4. **Auth + rate limit** (§5) wrapping the suite before sharing the URL externally.
5. Docs: publish the field dictionary + the incremental-pull recipe for Ezaco.

## 7. Open items
- Confirm the `export_api_keys` storage choice (table vs env) and the rate-limit numbers.
- Engine-owner answers for the v2 PBP open items (`play_by_play_schema.md` §5) — not blocking,
  improve `result`/`description` fidelity.
- Decide whether `/games/export/boxscores` should also offer flat CSV sub-views
  (`/export/batting-lines`, `/export/pitching-lines`, `/export/fielding-lines`) for
  spreadsheet users, or whether NDJSON suffices.
- Retention interaction: `season_archive.py` nulls MLB regular-season PBP on archive — confirm
  the PBP export is expected to return empty for archived past seasons (it will).
