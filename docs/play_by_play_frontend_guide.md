# Play-by-Play API — Frontend Integration Guide

**Audience:** frontend team.
**What this covers:** the modernized play-by-play (PBP) endpoints, the v2 response
shape, how to render a narrative feed, and migration/back-compat notes.

---

## TL;DR

- PBP is now exposed in a clean, versioned **v2** shape: at-bats with a ready-to-render
  **`description`** string, normalized `snake_case` fields, real `null`/arrays, and a
  human-readable result vocabulary.
- One transform powers **both** endpoints, so single-game and bulk-export PBP are identical in shape.
- The old **raw** engine dump is still the default on the per-game endpoint — nothing you have
  today breaks. Opt into v2 with `?format=v2`.
- **MLB (level 9) only.** PBP is not stored for other levels.

---

## What changed (and why)

The engine emits PBP as a raw array where **each element is one action** (a pitch, a pickoff
attempt, or a steal attempt) with ~66 keys. That raw data is hostile to a UI:

- inconsistent key naming (`"Inning Half"`, `"AB_Over"`, `"Is_Homerun"` all in one object),
- the string `"None"` used instead of `null`,
- some fields are **stringified Python lists** (one, `Error List`, is even malformed/unparseable),
- the full 9-player fielding roster repeated on **every** action,
- no human-readable summary anywhere.

The new layer normalizes all of that server-side and adds a generated `description` per at-bat.
You consume clean JSON; you never touch raw engine fields.

> Security note: the normalizer reads only an explicit allowlist of fields. Engine-internal data
> (player ratings, probabilities, RNG, model internals) **cannot** appear in the response.

---

## Endpoints

### A. Single game — `GET /api/v1/games/{game_id}/play-by-play`

For a game detail view / pop-up.

| Param | Default | Values | Meaning |
|---|---|---|---|
| `format` | `raw` | `raw` \| `v2` | **Use `v2`.** `raw` returns the legacy engine blob unchanged. |
| `granularity` | `at_bat` | `at_bat` \| `action` | group into at-bats, or a flat action list (v2 only) |
| `include_events` | `1` | `0` \| `1` | include the per-pitch/steal `events` stream inside each at-bat |
| `inning` | — | int | filter to one inning (v2 only) |
| `half` | — | `top` \| `bottom` | filter to one half (v2 only) |

```
GET /api/v1/games/58231/play-by-play?format=v2
GET /api/v1/games/58231/play-by-play?format=v2&include_events=1&inning=9
```

### B. Bulk / incremental — `GET /api/v1/games/export/play-by-play`

For syncing many games (NDJSON stream, one game per line, incremental via `since=`). Requires an
export API key. Same v2 shape per game. Full contract in **`docs/EXPORT_API.md`** — read that for
the streaming/cursor model.

```
GET /api/v1/games/export/play-by-play?league_year_id=2026&since=58000
```

Both endpoints return the **same per-game object** described below. Use A for "show me this game,"
B for "pull all new games."

---

## v2 response shape (`granularity=at_bat`)

```jsonc
{
  "schema_version": 2,
  "game_id": 58231,
  "teams": { "home": "ATL", "away": "WAS" },
  "at_bats": [
    {
      "seq": 7,                       // stable per-game order index
      "inning": 1,
      "half": "bottom",               // "top" | "bottom"
      "outs_before": 2,
      "outs_after": 2,
      "batter":  { "id": 2002, "name": "Jordan Park" },
      "pitcher": { "id": 1009, "name": "Max Knox" },
      "result": "single",             // normalized enum, see vocab below; null if none
      "result_detail": {              // null unless the ball was put in play
        "batted_ball": "flare",       // contact tier
        "air_or_ground": "air",
        "hit_depth": "deep_if",
        "hit_direction": "right",
        "fielder": { "id": 1009, "name": "Max Knox" },
        "errors": ["catching error by Max Knox"]   // [] when none
      },
      "rbi": 0,
      "runs_scored": [ { "id": 2002 } ],            // runners who scored on the at-bat
      "runners_after": {                            // base state after the at-bat
        "1B": { "id": 2002, "name": "Jordan Park" },
        "2B": null,
        "3B": null
      },
      "score_after": { "home": 0, "away": 0 },      // cumulative after the at-bat
      "events": [ /* present only when include_events=1; see below */ ],
      "description": "Jordan Park singles (flare to right)."
    }
  ]
}
```

### The `events` stream (only when `include_events=1`)

An ordered, mixed-`kind` list of the actions within the at-bat. **Lean, flat shape** — the
enclosing at-bat already carries batter/pitcher/inning/result, so an event is just the delta:

```jsonc
// pitch
{ "kind": "pitch", "balls": 1, "strikes": 0, "pitch": "Fastball", "swing": "Looking", "result": "Ball" }
// steal / pickoff (interleave within an at-bat; never end it)
{ "kind": "steal",   "result": "caught_stealing", "runner": { "id": 2003, "name": "Casey Reed" } }
{ "kind": "pickoff", "result": "unsuccessful_pickoff", "runner": null }
```

- For a **pitch**, `result`/`swing` are engine strings (`"Ball"`, `"Strike"`, `"Looking"`; for a
  batted ball `result` is the contact tier, e.g. `"flare"`, `"solid"`, `"burner"`). `pitch` is the
  pitch type (`"Fastball"`, `"Slider"`, …). These are raw engine vocabulary — treat as display
  labels, not a fixed enum.
- For **steal/pickoff**, `result` is the baserunning enum and `runner` is the actor
  (**may be `null`** — see Caveats).

### `granularity=action`

Returns `"actions": [ ... ]` instead of `"at_bats"` — a flat list of the **full** normalized
actions (each standalone, carrying its own `inning`, `half`, `batter`, `pitcher`, `count`,
`score_after`, etc.). Use this for analytics/debugging, not for narrative rendering.

---

## Result vocabulary

`at_bats[].result` (normalized `snake_case`), observed values:

| Category | Values |
|---|---|
| Hits | `single`, `double`, `triple`, `home_run`, `inside_the_park_hr` |
| Outs | `strikeout`, `groundout`, `flyout`, `out` (generic fallback) |
| On base (no hit) | `walk`, `hbp` |
| `null` | at-bat had no plate result (e.g. the half-inning ended on a caught stealing) |

Baserunning `events[].result`: `stolen_base`, `caught_stealing`, `unsuccessful_pickoff`
(and other engine outcomes, lowercased with spaces → `_`). This list is not closed — render
unknown values by replacing `_` with spaces, or just use `description`.

---

## Rendering recipe (narrative feed)

The simplest correct render: group at-bats by `(inning, half)` and print `description`.

```js
const res = await fetch(`/api/v1/games/${gameId}/play-by-play?format=v2&include_events=0`,
  { credentials: 'include' }).then(r => r.json());

// group consecutive at-bats by half-inning (they arrive in order)
const groups = [];
for (const ab of res.at_bats) {
  const key = `${ab.inning}|${ab.half}`;
  if (!groups.length || groups.at(-1).key !== key) {
    groups.push({ key, inning: ab.inning, half: ab.half, abs: [] });
  }
  groups.at(-1).abs.push(ab);
}

for (const g of groups) {
  const last = g.abs.at(-1);
  renderHalfInningHeader(g.half, g.inning, last.score_after); // {home, away}
  for (const ab of g.abs) {
    renderLine(ab.description, ab.rbi);    // description is display-ready
  }
}
```

Notes:
- `description` is display-ready; you don't need to build sentences yourself.
- `rbi > 0` is a good "highlight" signal; `result === 'home_run'` likewise.
- For a pitch-by-pitch drill-down, request `include_events=1` and render each at-bat's `events`
  (pitch → `${balls}-${strikes} ${pitch} ${result}`).
- This API does **not** return a linescore. For the inning-by-inning R/H/E grid use the boxscore
  endpoint (`GET /api/v1/games/{id}/boxscore`), which has `linescore`.

A working reference implementation lives in the admin SPA "Game Viewer"
(`admin/static/admin/app.js`, `renderGamePbp` / `_gvEventRow`).

---

## Backwards compatibility

- The per-game endpoint **defaults to `raw`** — existing callers that don't pass `format` get the
  exact legacy payload. Opt into the new shape with `?format=v2`.
- No stored data was migrated or altered. v2 is computed on read from the same stored blob, so it
  works identically on games from earlier this season as on new ones.
- `schema_version: 2` is on every v2 response — branch on it if you need to.

---

## Caveats

1. **MLB only.** PBP is stored for level 9 only. Other levels return an empty `at_bats` (and the
   per-game endpoint returns `play_by_play: []` in raw mode). Box scores cover all levels.
2. **Archived games.** Older games may have had PBP cleared by season archiving — the feed comes
   back empty even for MLB. Handle empty `at_bats` gracefully (e.g. "Play-by-play not available").
3. **Steal/pickoff `runner` may be `null`.** The engine records the batter at the plate, not the
   runner who's the actor, so it can't always be resolved. The `description` degrades to
   "Runner …"; prefer rendering `description` for these until the engine emits the runner id.
4. **Pitch `result`/`swing`/`pitch` are raw engine strings** (mixed case, open vocabulary). Use as
   labels; don't assume a fixed enum. The normalized, closed enums are `at_bats[].result` and the
   baserunning `events[].result`.

---

## Quick reference

| Need | Call |
|---|---|
| One game, narrative | `…/games/{id}/play-by-play?format=v2` |
| One game, with pitch detail | `…/games/{id}/play-by-play?format=v2&include_events=1` |
| One inning only | `…&inning=9&half=bottom` |
| Flat actions (analytics) | `…?format=v2&granularity=action` |
| Sync many games | `…/games/export/play-by-play?since=<watermark>` (NDJSON; see EXPORT_API.md) |
| Linescore / R-H-E | `…/games/{id}/boxscore` |
| Legacy raw blob | `…/games/{id}/play-by-play` (default) |
