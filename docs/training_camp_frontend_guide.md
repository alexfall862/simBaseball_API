# Training Camp — frontend guide

Each organization picks **one focus skill and an intensity per player** for the
coming season. Camp runs in the **preseason**, after free agency, trades and the
draft and before opening day. It takes the focus skill's progression roll from
the end-season that just happened and re-evaluates it as if the potential had
been a few steps better (or worse, on a backfire) on the grade ladder
`N F D- D D+ C- C C+ B- B B+ A- A A+`. Same luck, different grade; the
difference is added to the rating. Stored potentials never change.

Timeline for a season Y+1:

1. End-season Y: everyone ages and progresses at their natural potential. The
   offseason market works on these fresh ratings.
2. Offseason: focus for Y+1 is open. Players move between orgs.
3. Preseason camp (admin step): every focus is applied and focus for Y+1 locks.
4. Opening day of Y+1.

| Intensity | Effect this offseason | Risk |
|---|---|---|
| `regular` | potential +1 step (a C trains like a C+) | none |
| `intense` | +2 steps | 25 % chance of −2 steps instead |
| `max` | +4 steps (a C trains like a B+) | 50 % chance of −4 steps instead |

The outcome is rolled once per player and season (deterministic), so the
result an org sees after camp is final. Steps and thresholds live in
`league_config` (`camp_*` keys) and are returned by the options endpoint.

Who can set a focus: the org holding the player's active contract — pro orgs
for players at any level 4–9, college programs for their roster (level 3).
HS and international amateur pools have no camp. A focus can be changed or
removed until camp is applied; afterwards the endpoints return 400.

A focus belongs to the org that set it. If the player changes orgs before
camp, that focus is skipped and the new org can set its own (the PUT replaces
the old row). The roster list only shows focus rows the requesting org owns.

Which season: `league_year_id` is the season about to be **played**. Omit it
and the API uses the current timestamp season, which is Y+1 from the moment
end-season Y finishes. During the regular season the current season's camp is
already applied, so the window effectively runs from end-season to preseason.

All routes are under `/api/v1`.

## 1. Options

```
GET /training-camp/options
```

```json
{
  "skills": [
    { "attr": "contact", "label": "Contact", "kind": "ability" },
    { "attr": "pgencontrol", "label": "Control", "kind": "ability" },
    { "attr": "pitch1", "label": "Pitch 1 (all four components)", "kind": "pitch" }
  ],
  "intensities": [
    { "intensity": "regular", "steps_up": 1, "steps_down": 0, "backfire_pct": 0,  "description": "..." },
    { "intensity": "intense", "steps_up": 2, "steps_down": 2, "backfire_pct": 25, "description": "..." },
    { "intensity": "max",     "steps_up": 4, "steps_down": 4, "backfire_pct": 50, "description": "..." }
  ],
  "grade_ladder": ["N","F","D-","D","D+","C-","C","C+","B-","B","B+","A-","A","A+"]
}
```

19 ability skills plus `pitch1`…`pitch5`. A pitch slot shifts all four of that
pitch's components (accuracy, control, break, consistency) and is only valid
for a player who throws that pitch (see `pitches` in the roster list).

## 2. Roster with current focus

```
GET /training-camp/focus?org_id=12&league_year_id=5
```

```json
{
  "org_id": 12, "league_year_id": 5, "camp_applied": false, "camp_applied_at": null, "with_focus": 3,
  "players": [
    { "player_id": 3200, "name": "Mike Johnson", "age": 24, "ptype": "Pitcher", "level": 9,
      "pitches": ["Fastball", "Slider", "Changeup", null, null],
      "focus_attr": "pitch2", "focus_label": "Pitch 2", "intensity": "intense", "locked": false }
  ]
}
```

`locked: true` (and `camp_applied: true`) means this season's camp has already
been applied; editing is closed for every player.

## 3. Set a focus (one or many)

```
PUT /training-camp/focus
{ "org_id": 12, "league_year_id": 5, "player_id": 3200, "attr": "pitch2", "intensity": "intense", "set_by": "gm@example.com" }

PUT /training-camp/focus
{ "org_id": 12, "league_year_id": 5,
  "items": [ { "player_id": 3200, "attr": "power", "intensity": "regular" },
             { "player_id": 3201, "attr": "speed", "intensity": "max" } ] }
```

Response `{ "success": true, "league_year_id": 5, "set": [ { "player_id": 3200, "attr": "pitch2", "label": "Pitch 2", "intensity": "intense", "league_year_id": 5 } ] }`.

400 `validation` when: the player is not on a roster this org controls, the
skill is unknown, the pitch slot is empty, the intensity is not one of the
three, or the camp has already been applied this season. A bulk call is all or
nothing.

## 4. Clear a focus

```
DELETE /training-camp/focus
{ "org_id": 12, "league_year_id": 5, "player_id": 3200 }
→ { "success": true, "removed": true, "league_year_id": 5 }
```

## 5. Results (after camp)

```
GET /training-camp/results?org_id=12&league_year_id=5
```

```json
{ "league_year_id": 5,
  "results": [ { "player_id": 3200, "name": "Mike Johnson", "attr": "pitch2", "label": "Pitch 2",
                 "intensity": "intense", "steps": -2, "backfired": true } ] }
```

Fog-of-war: this view says what was trained and whether it backfired, never
the grades involved or the true rating change. Potentials remain scouted information; the only visible
effect is the (fuzzed) rating change on the player card.

## UI suggestions

- A "Training Camp" tab on the team page (pro: per level roster; college: the
  program): one row per player with a skill dropdown (abilities, then the
  player's pitches by name) and an intensity selector showing the risk text
  from the options endpoint.
- Roster badge for players with a focus; after camp show the result with a
  success/backfire marker.
- Disable editing when `camp_applied` is true.
- From age 29 the growth table is nearly the same for every potential: at 29–33
  only an F-potential skill still gains a little (F has a lower mode there), and
  from 34 camp changes nothing. A hint on 29+ rows avoids wasted picks.
