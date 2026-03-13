# Inside-the-Park Home Run (ITPHR) — Frontend Integration Guide

## Overview

The engine now distinguishes between over-the-fence home runs and inside-the-park home runs (ITPHR). A new field `itphr` appears across all stat endpoints. The existing `hr` field continues to count **all** home runs (both types combined), so no existing formulas (SLG, ISO, OPS, etc.) need to change.

**Key rule:** `itphr` is always a subset of `hr`. A player with `hr: 12, itphr: 3` hit 9 over-the-fence HRs and 3 inside-the-park HRs.

---

## Affected Endpoints & Field Names

### 1. Game Box Scores (`/api/v1/games/<id>/box`)

**Batter lines** — new field `itphr` (integer):
```json
{
  "id": 1234,
  "name": "John Smith",
  "ab": 4, "r": 1, "h": 2, "2b": 0, "3b": 0,
  "hr": 1, "itphr": 1,
  "rbi": 2, "bb": 0, "so": 1, "sb": 0, "cs": 0
}
```

**Pitcher lines** — new field `itphr` (integer, = inside-the-park HRs allowed):
```json
{
  "id": 5678,
  "name": "Jane Doe",
  "ip": "6.2", "h": 5, "r": 3, "er": 2,
  "bb": 2, "so": 7, "hr": 1, "itphr": 0
}
```

### 2. Batting Leaderboard (`/api/v1/stats/batting`)

New field `itphr` in each player row.

### 3. Pitching Leaderboard (`/api/v1/stats/pitching`)

New field `itphr` in each player row (= ITPHR allowed).

### 4. Team Stats (`/api/v1/stats/team-stats`)

New field `itphr` in both the batting and pitching aggregates per team.

### 5. Player Stats (`/api/v1/stats/player/<id>`)

**Season batting** — `itphr` in each season row.

**Season pitching** — `itphr` in each season row (= ITPHR allowed).

**Gamelog batting** (`gamelog_batting` array) — `itphr` per game.

**Gamelog pitching** (`gamelog_pitching` array) — `itphr` per game (= ITPHR allowed).

### 6. Batting Lab Results (`/api/v1/batting-lab/runs/<id>`)

Each tier result now includes:
- `inside_the_park_hr` — raw count
- `itphr` — in rate stats
- `itphr_pct` — ITPHR as a percentage of total HRs

### 7. Analytics — Contact Type Breakdown (`/admin/analytics/batting-analysis`)

Per-contact-type data now includes `ITPHR_pct` alongside the existing `HR_pct`. The `HR_pct` value now includes both over-the-fence and ITPHR combined.

---

## Display Recommendations

### Stat Tables (Leaderboards, Box Scores, Season Stats)

- **Default:** Show `HR` column as-is (already includes all HRs). No change needed.
- **Optional detail:** Add an `ITPHR` column or show it as a tooltip/hover on the HR cell.
- **Suggested format:** If showing both, display as `HR` and `ITPHR` columns side by side, or show `HR (ITPHR)` like `12 (3)`.

### Player Profile / Season Lines

- Show `ITPHR` as a secondary stat below or beside HR.
- Consider a small indicator icon when `itphr > 0` in a game log entry.

### Gamelog

- If `itphr > 0` for a game, consider highlighting or annotating the HR cell.
- Example: `HR: 2 (1 ITPHR)` or use a superscript/badge.

### Batting Lab

- The `itphr_pct` field shows what percentage of all HRs were inside-the-park. This is useful for analyzing whether the engine's ITPHR rate is reasonable across tiers.
- Consider showing this as a chart comparing ITPHR% across tier levels.

### Analytics Contact Breakdown

- `HR_pct` = total HR rate (over-the-fence + ITPHR).
- `ITPHR_pct` = just the inside-the-park portion.
- Display both in the contact type table to give visibility into the ITPHR mechanic.

---

## Formulas — No Changes Needed

All standard baseball formulas should continue using `hr` (the all-inclusive count):

| Formula | Uses `hr` | Uses `itphr` |
|---------|-----------|--------------|
| SLG     | Yes       | No           |
| ISO     | Yes       | No           |
| OPS     | Yes       | No           |
| BABIP   | Yes (subtract from hits) | No |
| wOBA    | Yes       | No           |

`itphr` is purely informational/diagnostic — it does not affect any rate stat calculations.

---

## Backward Compatibility

- `itphr` defaults to `0` for all historical data (games played before the engine update).
- The field is always present in the response — no null checks needed.
- Existing code that ignores `itphr` will continue to work correctly since `hr` still represents the total.

---

## Summary of New Fields by Endpoint

| Endpoint | Batting Field | Pitching Field |
|----------|--------------|----------------|
| Box scores | `itphr` | `itphr` |
| Batting leaderboard | `itphr` | — |
| Pitching leaderboard | — | `itphr` |
| Team stats | `itphr` (batting & pitching) | `itphr` |
| Player seasons | `itphr` | `itphr` |
| Player gamelog | `itphr` | `itphr` |
| Batting lab | `inside_the_park_hr`, `itphr`, `itphr_pct` | — |
| Analytics contact breakdown | `ITPHR_pct` | — |
