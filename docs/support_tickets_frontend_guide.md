# Support-Ticket Fixes — Frontend Integration Guide

**Audience:** frontend team (the player-facing SPA).
**What this covers:** the frontend work needed to complete the support-ticket fixes
made on the API side (2026-06-22). Backend tickets are tracked in
`docs/SUPPORT_TICKETS.md`; this guide is only the **frontend half** — the tickets whose
resolution needs a UI change.

Each item lists: **what changed in the API**, **what the frontend must do**, the exact
**endpoint/fields**, and **acceptance criteria**.

---

## TL;DR — frontend task checklist

**Wire up new/changed endpoints**
- [ ] Redshirt button → `POST /transactions/redshirt` (CBL-06)
- [ ] Waiver player card now has full data — render it (MLB-02)
- [ ] "Next starter" indicator → use `next_slot` from the rotation payload (MLB-11)
- [ ] Full stat export → pass `page_size=0` (MLB-17)
- [ ] Admin: "Run Week" one-click → `POST /games/run-week` (new orchestrator)

**Adopt new API behavior**
- [ ] Handle the new "invalid level" 400 on promote/demote; rethink "move to Unassigned" (MLB-20)
- [ ] Two-way pitcher as DH: allow a pitcher in the `dh` depth slot (MLB-22/26/28)
- [ ] Trust per-response `displayovr`; don't let a card fetch overwrite a roster row (MLB-24)

**Pure-frontend (data already in the API)**
- [ ] Handedness column on roster (MLB-09)
- [ ] Pitcher hitting potentials on the pitcher card (MLB-05)
- [ ] Scouting progress on My Board / My Commitments / Overview (MLB-06, CBL-13)
- [ ] Sortable Commitments table (CBL-12)
- [ ] Allow setting a recruit's points to 0 (CBL-04)
- [ ] Box-score → player profile modal stacking (MLB-08)
- [ ] Team-name tooltip on icon hover (MLB-16)
- [ ] Quick links on team page (MLB-04); Recruiting shortcut on homepage (MLB-25)
- [ ] Mobile: keep own scouted grades after navigating (CBL-02)

**Blocked on backend (do NOT start — needs API work first)**
- [ ] Designate backup/injury-replacement players (MLB-15)
- [ ] CBL gameplan shows no players / "No standings available" (CBL-01/03/05/10)

---

## 1. New / changed endpoints to wire up

### 1.1 Redshirt button → `POST /transactions/redshirt` (CBL-06)

**Was:** the Redshirt action opened a contract-renewal screen — there was no redshirt
endpoint at all. **Now:** a real endpoint exists.

```
POST /api/v1/transactions/redshirt
Body: { "contract_id": 12345, "league_year_id": 2026, "executed_by": "<user>" }
→ 200 { "transaction_id", "contract_id", "player_id", "is_redshirt": true,
        "years": 5, "player": { ...summary..., "current_level", "on_ir" } }
```

Errors (HTTP 400, `{"error":"validation","message":...}`): `"Player is already redshirted"`,
`"Cannot redshirt a finished contract"`, `"Invalid roster level…"`.

**Frontend:** point the Redshirt button at this endpoint (not the renewal modal). Show a
confirm ("Redshirt this player? Adds a year to their eligibility/contract."), then refresh
the roster row on success and surface the validation message on 400.

**Done when:** clicking Redshirt flags the player as redshirt and extends the contract a year,
with no contract-renewal screen.

---

### 1.2 Waiver player card now has full data (MLB-02)

**Was:** the waiver list/detail returned a slim shape (`player_id`, `name`, `age`,
`displayovr`) — not enough to render a player card, so no card popped. **Now:** each waiver
entry includes the standard display block.

`GET /api/v1/.../waivers` (list) and the detail endpoint now return, per entry:
```jsonc
{
  ...existing waiver fields (waiver_claim_id, contract_*, expires_week, bid_count, my_bid)...,
  "displayovr": 55,
  "bio": { ... }, "ratings": { ... }, "potentials": { ... },
  "visibility_context": { ... }   // fog-of-war state, same as everywhere else
}
```

**Frontend:** render the same player-card popup you use elsewhere from `bio`/`ratings`/
`potentials` when a waiver player is clicked.

**Done when:** clicking a waivered player opens the normal player card.

---

### 1.3 "Next starter" indicator → `next_slot` (MLB-11)

**Was:** the UI computed the next starter as `current_slot + 1`, which overran the rotation
(showed "Slot 6" for a 5-man rotation). **Now:** the API returns the correct value.

`GET` and `PUT /api/v1/gameplanning/team/{team_id}/rotation` now include:
```jsonc
{ "rotation_size": 5, "current_slot": 5, "next_slot": 1, "slots": [...] }
```
`current_slot` = the slot that **last** pitched; **`next_slot`** = who pitches next (already
wrapped at `rotation_size`; `null` if no rotation configured).

**Frontend:** mark the slot whose `slot === next_slot` as "(next)". Stop computing
`current_slot + 1`.

**Done when:** a 5-man rotation never shows "Slot 6"; the highlighted next starter matches who
actually starts.

---

### 1.4 Full stat export → `page_size=0` (MLB-17)

**Was:** stat exports were capped at 200 players. **Now:** the leaderboard endpoints accept
`page_size=0` = uncapped (the 200 cap still applies to normal paginated views).

`GET /api/v1/stats/batting|pitching|fielding?...&page_size=0` → returns **all** rows.

**Frontend:** the "Export" button should request `page_size=0` (keep the default page size for
the on-screen table). Expect a larger payload.

**Done when:** exporting stats yields every qualifying player, not the top 200.

---

### 1.5 Admin: one-click "Run Week" → `POST /games/run-week` (new orchestrator)

**New:** a single endpoint that simulates the week and runs all weekly admin tasks (books,
injuries, waivers, FA, positions) and advances — each step idempotency-guarded, so a
double-click is safe.

```
POST /api/v1/games/run-week
Body: { "league_year_id": 2026, "season_week": 6, "league_level": 9 }   // league_level optional (omit = all)
→ 200 { "status":"ok", "season_week":6, "steps": { "simulate": {"ran":true,"total_games":47},
                                                    "advance": {"ran":true} } }
On failure → { "status":"error", "failed_step":"simulate"|"advance", "message", "steps" }
```

**Frontend (admin panel):** replace the separate "Simulate Week" + "Advance Week" (+ books)
buttons with one **Run Week** button. Disable while in-flight; show per-step result from `steps`.
Re-clicking after a partial failure is safe (guards make completed steps no-ops).

**Done when:** one button runs a full week end-to-end and the admin no longer needs to chain
the old buttons (those still exist if you want a manual/advanced mode).

---

## 2. New API behavior to handle

### 2.1 Invalid roster level on promote/demote (MLB-20)

**Was:** moving a player to "Unassigned" set them to a level with no row, and the player
vanished from every roster. **Now:** `POST /transactions/promote` and `/demote` **reject** a
target level that doesn't exist, and activating from IR repairs an already-orphaned player.

New error: `400 { "error":"validation", "message":"Invalid roster level <N>: not a real level…" }`.

**Frontend:**
- Surface that message inline on a failed move.
- **Reconsider any "move to Unassigned" control.** If "Unassigned" maps to a non-level
  sentinel (e.g. 0), that action will now 400. Either remove it, or map it to a real level.
  (If you genuinely need an Unassigned bucket, that's a backend change — flag it; don't send a
  fake level.)
- `activate-from-IR` may now return a clear error if a player is in an unrecoverable invalid
  state — show the message instead of failing silently.

**Done when:** no UI action can move a player to a non-existent level, and any such attempt
shows a clear error.

### 2.2 Two-way pitcher as DH (MLB-22 / 26 / 28)

**Was:** non-designated pitchers randomly grabbed the DH slot over position players. **Now:** a
pitcher is eligible to DH **only** if the team explicitly places him in the `dh` depth-chart
slot — that's the deliberate "two-way (Ohtani)" designation. Otherwise pitchers never appear in
the batting lineup.

This is driven through the existing depth-chart endpoint:
```
PUT /api/v1/gameplanning/team/{team_id}/defense
Body: { "assignments": [ { "position_code": "dh", "player_id": <pitcher_id>,
                           "target_weight": 1.0, "priority": 1, ... }, ... ] }
```

**Frontend:**
- Allow a **pitcher to be dropped into the `dh` depth slot** in the gameplan UI (if the picker
  currently filters pitchers out of DH, stop filtering for the DH slot specifically).
- Optionally label it "Two-way / DH-eligible," and make clear that pitchers won't auto-DH
  unless placed here.

**Done when:** a user can designate a pitcher as DH and only then does that pitcher hit; the
random/unintuitive pitcher-at-DH behavior is gone.

### 2.3 OVR consistency on roster vs card (MLB-24)

**Was:** a player's OVR appeared to "change" a couple seconds after opening/closing their card.
**Now:** the API recomputes `displayovr` live and consistently on every endpoint. Any residual
flicker is the **frontend** mixing two values (a fuzzed roster-list value vs a precise card
value, on college rosters especially).

**Frontend:**
- Treat each response's `displayovr` as authoritative **for that view**; don't let a player-card
  fetch write its `displayovr` back into the roster-list row's state (they can legitimately
  differ when the card is precise/scouted and the list is fuzzed).
- Don't re-render the roster row from card data on close.

**Done when:** a roster row's OVR doesn't visibly change after opening/closing the card.

---

## 3. Pure-frontend tickets (API already returns the data)

### 3.1 Handedness on the roster page (MLB-09)
`bio.bat_hand` and `bio.pitch_hand` are already in every roster payload. Add a Bats/Throws
column (e.g. "L/L"). **Done when:** you can spot left-handed pitchers without opening profiles.

### 3.2 Pitcher hitting potentials (MLB-05)
The `potentials` object already includes hitting potentials for pitchers (`contact_pot`,
`power_pot`, `eye_pot`, `discipline_pot`, …), subject to normal scouting fuzz. Render them on
the pitcher card (they're just not displayed today). **Done when:** a pitcher card shows hitting
potentials.

### 3.3 Scouting progress on My Board / My Commitments / Overview (MLB-06, CBL-13)
The recruiting board/detail already return `your_points`, `your_points_this_week`, `status`
("Listening to Offers" → "May Sign this Week"), and `interest_gauge`; commitments return
`points_total`. Surface "how far along / how much you've invested" from these fields. No API
change. **Done when:** users can see scouting progress without extra clicks.

### 3.4 Sortable Commitments table (CBL-12)
Each commitment row carries `star_rating`, `week_committed`, and `competitor_team_ids` — enough
to client-sort. Add column sort (default stays Week Committed; let users sort 5-stars to top).
**Done when:** the Commitments table is sortable.

### 3.5 Allow setting a recruit's points to 0 (CBL-04)
The invest endpoint **accepts `points: 0`** and removes that investment (refunding the budget).
The UI currently drops or min-clamps 0 to 1 before POSTing. Stop clamping — send 0 to remove an
investment. **Done when:** a user can take a recruit back to 0 points and reallocate them.

### 3.6 Box-score → player profile modal stacking (MLB-08)
Opening a player profile from a box score and closing it currently closes the **whole** box
score. This is modal/overlay stacking — closing the inner modal should return to the box score,
not dismiss both. Pure frontend. **Done when:** closing a player profile returns to the box
score.

### 3.7 Team-name tooltip on icon hover (MLB-16)
Team `abbrev`/`name` are present in the relevant payloads. Add a hover tooltip on team icons.

### 3.8 Quick links (MLB-04) & Recruiting shortcut (MLB-25)
Navigation only — the target routes (roster, gameplan, recruiting) already exist. Add quick
links on each team's page and a recruiting shortcut on the homepage.

### 3.9 Mobile: own scouted grades revert to fuzzed (CBL-02)
On mobile, after scouting your own players, navigating away shows fuzzed grades again until you
re-tap the player. Fog-of-war fuzzes by design; the fix is to **pass `viewing_org_id`
consistently** on the list/detail calls (or stop caching the fuzzed list over the precise
values). **Done when:** scouted grades persist across navigation on mobile.

---

## 4. Blocked on backend — do not start yet

These tickets need an API change first; there is **no** frontend task until then.

- **MLB-15 — designate backup / injury-replacement players.** Needs a new `backup_only` flag on
  the depth chart (not built). Until the API exposes it, there's nothing to wire.
- **CBL-01 / 03 / 05 — CBL gameplan shows no players** and **CBL-10 — "No standings available."**
  Suspected backend cause (college level excluded by a `levels` join / a hardcoded `(4,9)` level
  filter, or `current_season_id` null). Needs backend investigation/fix before any frontend work.

When those land, this guide will be extended.

---

## Reference

- Backend ticket tracker + verdicts: `docs/SUPPORT_TICKETS.md`
- Bulk data export (separate effort): `docs/EXPORT_API.md`, `docs/play_by_play_frontend_guide.md`
