# Play-by-Play: Audit, Raw Schema, and v2 Normalization Design

Status: **Phases 2–4 implemented.** Only the §5 engine-owner questions remain open
(they affect quality of steal/pickoff narration, not the pipeline).
Source of truth for the raw schema: `pbp_sample.json` (one MLB game, 219 action-entries).

Implemented:
- `services/pbp_normalize.py` — pure transform (classify → normalize → group → describe).
  Reads ONLY an explicit **allowlist** of raw keys (`_is_allowed_key`); engine-internal
  fields (Interaction_Data, At_Bat_Modifiers, ratings/RNG/probability tables, Pre_R*,
  Catch Probability) can never leak into the export. Never raises on real data.
- `tests/test_pbp_normalize.py` — 15 tests (incl. allowlist/no-leak guards);
  run `python tests/test_pbp_normalize.py` or pytest.
- `GET /games/<id>/play-by-play?format=v2&granularity=at_bat|action&include_events=0|1`
  plus `?inning=`/`?half=` filters. Default stays `raw` for back-compat.
- Frontend **Game Viewer** section (admin SPA): game-id input → inning-grouped narrative
  feed with optional per-pitch/event detail. `app.js` + `styles.css` (dark theme).
- `game_payload.py`: consolidated the duplicated ingestion into `_prepare_result_json()` and
  fixed the `Catch Probability` strip-key typo (now actually stripped).

---

## 1. Current state (audit)

### Storage
- The Rust engine returns a `play_by_play` array. Each element is **one pitch/action**, not an
  at-bat. A 9-inning game is ~200–250 entries, 66 keys each.
- Before storage, `services/game_payload.py::_trim_play_by_play()` strips 7 engine-internal keys
  (`At_Bat_Modifiers`, `Interaction_Data`, `Timing_Diagnostics`, `Catch_Probability`,
  `Pre_R1/R2/R3`) and the trimmed blob is stored as a JSON string in
  `game_results.play_by_play_json`.
- Stored **MLB (level 9) only** — by design, to bound storage across the many simulated levels.
  Ingestion logic is duplicated across the bulk and single paths (game_payload.py ~2323 / ~2495).

### Export
- `GET /games/<id>/play-by-play` — returns the stored blob verbatim (no transform/filter/paging).
- `GET /games/<id>/boxscore?include_pbp=1` — embeds the blob; derives the linescore by diffing
  cumulative `Home Score`/`Away Score` per half-inning (`_build_linescore`).

### Consumption
- No narrative/text is generated anywhere. The frontend never renders plays as prose.
- Only `services/analytics.py::hr_depth` reads individual plays (server-side scan).

### Retention
- `services/season_archive.py`: MiLB PBP+boxscore nulled; MLB regular PBP nulled on archive;
  playoffs retained.

### Defects driving this work
1. **Stringified Python `repr()` instead of JSON** (worst offender):
   - `"Outcomes": "['solid', 'center right', 'Fastball']"` — always a string.
   - `"Defensive Actions": "['home run']"`.
   - `"Error List": "['starter Max Knox catching error!', starter Max Knox]"` — **not valid Python**
     (unquoted elements); effectively unparseable, data is lost to consumers.
2. **Type variance / sentinel strings:** `Targeted Defender` is a player object 54× but the string
   `"None"` 165×. Many fields use the string `"None"` where `null` is meant
   (`Batted Ball`, `Hit Depth`, `Air or Ground`, …), while `Catch Probability` uses real `null`.
3. **Redundancy = the real size cost:** all 9 fielders (`Catcher`→`Right Field`) plus
   `Batter`/`Pitcher` are repeated as full `{player_id, player_name}` objects on **every pitch**.
4. **Inconsistent key naming:** space-separated PascalCase (`"Inning Half"`, `"Batted Ball"`) mixed
   with snake/Pascal (`"AB_Over"`, `"Is_Homerun"`, `"Pre_R1"`). Not JSON-idiomatic, hard to parse.
5. **No version, no per-at-bat grouping, no stable schema doc** for external consumers.
6. **Minor bug:** `_PBP_STRIP_KEYS` lists `"Catch_Probability"` (underscore) but the field is
   `"Catch Probability"` (space) — the entry never matches. Harmless (tiny float) but shows the
   strip set was never validated against real keys.

---

## 2. Raw per-action schema (66 keys)

**The unit is an action, not always a pitch.** Three action types share the same 66-key shape:

| Action | Discriminator | `Outcomes` | `AB_Over` | Notes |
|---|---|---|---|---|
| Pitch | neither flag set | real tuple string | may be `true` | advances ball/strike count |
| Pickoff attempt | `Is_Pickoff: true` | `"None"` | always `false` | no count change; `Defensive Outcome` e.g. `unsuccessful pickoff` |
| Steal attempt | `Is_StealAttempt: true` | `"None"` | always `false` | `Defensive Outcome` = `stolen base` / `caught stealing`; same batter stays at plate |

Baserunning actions **interleave within an at-bat** — only a pitch ever ends one (`AB_Over: true`).
Sample game: 209 pitches, 5 pickoffs, 5 steals. Discriminate via the flags; `Outcomes == "None"`
also signals a non-pitch action.

Grouped by purpose. Naming and types are **as emitted** (warts included).

### Context
| Key | Type | Notes |
|---|---|---|
| `ID` | int | sequential pitch index within the game |
| `Inning` | int | |
| `Inning Half` | `"Top"`/`"Bottom"` | |
| `Home Team` / `Away Team` | str | abbrev |
| `Home Score` / `Away Score` | int | cumulative after this action |
| `Ball Count` / `Strike Count` | int | count **after** this pitch |
| `Out Count` | int | outs at start of action |
| `Outs this Action` | int | outs recorded on this action |
| `Pre_Outs` | int | outs before action (redundant w/ `Out Count`) |

### Participants (full `{player_id, player_name}` objects, repeated every pitch)
`Batter`, `Pitcher`, `Catcher`, `First Base`, `Second Base`, `Third Base`, `Shortstop`,
`Left Field`, `Center Field`, `Right Field`, `Targeted Defender` (object **or** `"None"`).

### Pitch / contact outcome
| Key | Type | Notes |
|---|---|---|
| `Outcomes` | **stringified list** | e.g. `"['Ball','Looking','Fastball']"` → `[pitch_result, look/swing/contact, pitch_type]` |
| `Batted Ball` | str/`"None"` | contact tier (`solid`, `flare`, …) |
| `Air or Ground` | str/`"None"` | |
| `Hit Depth` | str/`"None"` | `deep_of`, `deep_if`, … |
| `Hit Direction` | str/`"None"` | |
| `Hit Situation` | str/`"None"` | `routine_if`, … |
| `Catch Probability` | float/`null` | |
| `Defensive Outcome` | str/`"None"` | **at-bat result enum** — see below |
| `Defensive Actions` | **stringified list** | |
| `Error List` | **stringified, malformed** | unparseable |
| `Error_Count` | int | |

### Baserunners & scoring
| Key | Type | Notes |
|---|---|---|
| `On First` / `On Second` / `On Third` | obj/`null` | runner **after** the action |
| `Home` | list[obj] | runners who scored this action |
| `Runners_Scored` | int | |
| `Runners_Scored_IDs` | list[int] | |
| `Pre_R1` / `Pre_R2` / `Pre_R3` | obj/`null` | runners before (stripped before storage) |

### Boolean event flags
`Is_Walk`, `Is_Strikeout`, `Is_InPlay`, `Is_Hit`, `Is_HBP`, `Is_Pickoff`, `Is_StealAttempt`,
`Is_StealSuccess`, `Is_Liveball`, `Is_WildPitch`, `Is_Foul`, `Is_Single`, `Is_Double`,
`Is_Triple`, `Is_Homerun`, `AB_Over`, `Is_DP_Opportunity`, `Is_DP`, `Is_TP_Opportunity`, `Is_TP`.
`WP_Descriptions`: list[str].

### Engine diagnostics (stripped before storage; present in raw sample)
`At_Bat_Modifiers`, `Interaction_Data` (large pitch-physics block), `Timing_Diagnostics`.

### `Defensive Outcome` observed vocabulary
`None`, `walk`, `strikeout`, `out`, `single`, `double`, `triple`, `homerun`,
`inside_the_park_hr`, `stolen base`, `caught stealing`, `unsuccessful pickoff`.
*(Not exhaustive — confirm full enum with engine: triple/HBP/sac/DP/error variants.)*

---

## 3. Proposed v2 normalized shape (normalize-on-read)

Two granularities from the same transform, both `snake_case`, real `null`, real arrays, with a
generated `description`. Raw blob remains the stored source of truth.

### At-bat view (default for UI / recaps)
Groups **actions** into at-bats (split on `AB_Over`, which only a pitch sets). Each at-bat holds an
ordered `events` stream — pitches plus any interleaved pickoff/steal attempts. Event detail is
optional (`include_events=1`); the at-bat summary fields are always present.

```jsonc
{
  "schema_version": 2,
  "game_id": 12345,
  "teams": { "home": "HOM", "away": "AWY" },
  "at_bats": [
    {
      "seq": 7,
      "inning": 1, "half": "bottom",
      "outs_before": 2, "outs_after": 2,
      "batter":  { "id": 2002, "name": "Jordan Park" },
      "pitcher": { "id": 1009, "name": "Max Knox" },
      "result": "single",                  // normalized from Defensive Outcome / Is_* flags
      "result_detail": {                   // null unless ball in play
        "batted_ball": "flare", "air_or_ground": "air",
        "hit_depth": "deep_if", "hit_direction": "right",
        "fielder": { "id": 1009, "name": "Max Knox" },
        "errors": ["catching error by Max Knox"]   // parsed from Error List / Defensive Actions
      },
      "rbi": 0,
      "runs_scored": [],                    // [{id,name}]
      "runners_before": { "1B": null, "2B": null, "3B": null },
      "runners_after":  { "1B": {"id":2002,"name":"Jordan Park"}, "2B": null, "3B": null },
      "score_after": { "home": 0, "away": 0 },
      "events": [                           // optional; include_events=1; ordered, mixed types
        { "kind": "pitch",   "balls": 1, "strikes": 0, "pitch": "Fastball",
          "swing": "take", "result": "ball" },
        { "kind": "pickoff", "result": "unsuccessful_pickoff", "runner": {"id":2002,"name":"Jordan Park"} },
        { "kind": "steal",   "result": "caught_stealing",
          "runner": {"id":2003,"name":"Casey Reed"} }
      ],
      "description": "Jordan Park reaches on a single (flare to deep right), error on Max Knox."
    }
  ]
}
```

`kind` is the normalized action type (`pitch` | `pickoff` | `steal`), derived from
`Is_Pickoff` / `Is_StealAttempt` (else pitch). Pickoff/steal events carry the **runner** as the
actor, not the batter at the plate.

### Action view (`granularity=action`)
Flat list of normalized actions (one v2 object per raw entry, tagged with `kind`) for
analytics/debugging — same field hygiene, no regrouping.

### Normalization rules
- Classify each action: `Is_Pickoff` → `pickoff`, `Is_StealAttempt` → `steal`, else `pitch`.
- For `pitch`, parse `Outcomes` → `{pitch, swing, result}` once, safely (`ast.literal_eval` with
  fallback; never trust it's valid). For `pickoff`/`steal`, `Outcomes` is `"None"` — skip it and
  derive `result` from `Defensive Outcome`.
- For `pickoff`/`steal`, resolve the **runner** (the actor) — see open item 6.
- Parse/repair `Error List` + `Defensive Actions` into a clean `errors: string[]`; on malformed
  input, degrade to `[]` and log — never propagate the broken string.
- Map every `"None"` sentinel → `null`; coerce `Targeted Defender` `"None"` → `null`.
- Collapse the repeated fielder roster: emit the defense **once per game** (or per substitution),
  reference fielders by id elsewhere — kills the dominant redundancy.
- `result`: single normalized enum derived from `Defensive Outcome` + `Is_*` flags
  (snake_case: `single`, `double`, `home_run`, `strikeout`, `walk`, `hbp`, `groundout`, `flyout`,
  `stolen_base`, `caught_stealing`, …).
- `description`: template per `result` (pure function, unit-tested).

---

## 4. Build plan

**Phase 1 — Contract (this doc).** Confirm open items below with engine owner.

**Phase 2 — `services/pbp_normalize.py`** (pure, no DB, unit-tested):
- `normalize_pitch(raw) -> dict`, `group_at_bats(pitches) -> list`, `describe(at_bat) -> str`,
  safe parsers for `Outcomes` / `Error List` / `Defensive Actions`.
- Consolidate the duplicated ingestion blocks in `game_payload.py` while here; fix the
  `Catch_Probability` strip-key typo.

**Phase 3 — Exports:**
- `GET /games/<id>/play-by-play?format=v2&granularity=at_bat|action&include_events=0|1`
  plus `?inning=`/`?half=` filters. Default stays `raw` until clients migrate, then flip.
- `boxscore include_pbp` emits v2 on request (linescore unchanged).
- Repoint `analytics.hr_depth` at the normalized accessor (single source for engine field names).

**Phase 4 — Frontend:** narrative at-bat feed in the SPA, collapsible by inning, using
`description` + structured fields.

---

## 5. Open items for engine owner
1. **Full `Defensive Outcome` enum** (and HBP / sacrifice / triple-play / error variants) so
   `result` mapping + descriptions are complete.
2. **`Outcomes` tuple contract** — confirm it's always `[pitch_result, swing/look, pitch_type]`.
3. **`Error List` format** — can the engine emit a real JSON array instead of `str(list)`? If so,
   fixing it at the source removes the unparseable-data risk entirely.
4. **`Out Count` vs `Pre_Outs` vs `Outs this Action`** — confirm exact semantics for `outs_before`.
5. **`Home` field** — confirm it is always "runners who scored this action."
6. **Runner identity on pickoff/steal** — these actions carry the `Batter` at the plate, not the
   runner being thrown out / stealing. Can the engine emit the actor's player id, or must we infer
   it from the `Pre_R1/R2/R3` → `On First/Second/Third` diff? Also confirm the full
   pickoff/steal `Defensive Outcome` enum (successful pickoff, pickoff-caught-stealing, etc.).
