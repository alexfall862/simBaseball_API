# Support Tickets — Half-Season Feedback Triage

Source: forum feedback threads, captured as `SUPPORT_MLB_Notes.pdf` (SimMLB Interface
Feedback Thread) and `SUPPORT_College_Notes.pdf` (SimCBL Interface Feedback).

Logged & investigated: 2026-06-22. This repo is the **backend API**; the player-facing
SPA is a separate frontend repo not present here. "Pure-frontend" verdicts mean the data
exists in the API but the fix lives in the frontend.

## Status legend

- 🔴 **Confirmed bug (API)** — reproducible root cause in this repo, needs a code fix.
- 🟠 **Likely engine-side** — the Rust game engine, not this API. API passes the value through.
- 🟣 **Pure frontend** — backend already returns the needed data; fix is in the SPA.
- 🔵 **Feature (needs backend)** — new endpoint/field/column required.
- ⚪ **Feature (frontend-only)** — navigation/display add, no backend work.
- 🟡 **Design question** — behaves as coded; product decision needed before any change.
- ❓ **Cannot determine** — needs runtime data / the frontend repo to confirm.

## Resolution log — 2026-06-22

Fixes applied this pass (all compile-checked; not yet runtime-tested):

| Ticket | Change | Files |
|--------|--------|-------|
| MLB-07 | IR players excluded from active-roster counts (`COALESCE(onIR,0)=0`) | `services/transactions.py` |
| MLB-17 | Stat leaderboards uncapped via `page_size=0` (default 200 kept) | `stats/__init__.py` |
| CBL-07 | Recruiting submit processes reductions before increases | `services/recruiting.py` |
| CBL-11 | Lottery eligibility floored at 50%-of-leader (`lottery_floor_pct`) | `services/recruiting.py` |
| MLB-20 | `_assert_valid_level` guards promote/demote; activate repairs orphaned level | `services/transactions.py` |
| MLB-22/26/28 | DH pool excludes non-designated pitchers; two-way via `dh` plan row | `services/lineups.py` |
| MLB-11 | API returns correct `next_slot`; admin indicator uses it | `gameplanning/__init__.py`, `admin/static/admin/app.js` |
| MLB-02 | Waiver list/detail return full bio/ratings/potentials card | `services/waivers.py` |
| MLB-18/19/29 (guard) | `_tick_injuries` claims `game_weeks.injuries_ticked_at` (no double-tick) | `services/timestamp.py`, `games/__init__.py`, new migration |
| CBL-06 | New `POST /transactions/redshirt` (flag + extend a year) | `services/transactions.py`, `transactions/__init__.py` |
| Mgmt button | New `POST /games/run-week` sync orchestrator (sim → advance, guarded) | `games/__init__.py` |
| Ezaco export | New `GET /games/export` (per-game home/away aggregates, `since=`, CSV/JSON) | `games/__init__.py` |

New migration to apply: `migrations/add_game_weeks_injuries_ticked_at.sql`. The
export's `sacrifice_flies` column comes from `migrations/add_engine_expansion_columns.sql`
(confirm applied to the live DB). Engine-side clusters (short innings, decisions,
fast healing) remain for the Rust team.

Items below marked 🟠 (engine-side), 🟣/⚪ (frontend), or 🟡 (design) were investigated
only — no API code change.

---

## Priority summary (confirmed API bugs)

| # | Ticket | Area | Root cause | Key location |
|---|--------|------|-----------|--------------|
| 1 | INJ-IR-ROSTER (MLB-07) | Roster | IR players still counted in active-roster total | `services/transactions.py:114-154` |
| 2 | INJ-ACTIVATE-DISAPPEAR (MLB-20) | Roster | Activating from "Unassigned" orphans player (no level row; INNER JOIN drops them) | `services/transactions.py:400-442`, `rosters/__init__.py:441-444` |
| 3 | OVR-CHANGES-ONLOAD (MLB-24) | Ratings | Stored `displayovr` column vs live recompute diverge between endpoints | `services/player_display.py:401` vs `scouting/__init__.py:1998` |
| 4 | LINEUP-PITCHER-BATTING / DH-SHUFFLE (MLB-22/26/28) | Lineups | DH pool/selector never excludes pitchers | `services/lineups.py:923-971` |
| 5 | REC-BUDGET-REALLOC (CBL-07) | Recruiting | Budget gate uses old allocation; fails when increase precedes decrease in one save | `services/recruiting.py:448,537-541` |
| 6 | REC-AI-COMPETITOR (CBL-11/MLB-03) | Recruiting | Lottery has no point floor; competitor display hides sub-50% orgs that can still win | `services/recruiting.py:696-701` vs `1049-1056` |
| 7 | EXPORT-200CAP (MLB-17) | Stats | Hardcoded `min(page_size, 200)` cap on all leaderboards/exports | `stats/__init__.py:46,451,807` |
| 8 | WAIVER-NO-CARD (MLB-02) | Waivers | Waiver list returns slim shape without `bio`/`ratings`/`potentials` | `services/waivers.py:669-690` |
| 9 | ROT-NEXT-SLOT6 (MLB-11) | Rotation | "Next starter" indicator off by one (`current_slot` = slot that *last* pitched) | `services/rotation.py:555,873` |
| 10 | REDSHIRT-CONTRACT (CBL-06) | Roster | No redshirt-apply endpoint exists at all | (missing; only in `seeding/`) |

**Likely engine-side clusters to escalate to the Rust team:** short-innings/early-end games
(MLB-12/13, CBL-08), missing decisions & invalid starter wins (MLB-23/27), and fast injury
healing (MLB-18/19/29) — the API stores all of these verbatim from the engine.

---

## MLB thread (`SUPPORT_MLB_Notes.pdf`)

### MLB-01 — Can't revert a saved rotation; "duplicate player_id: 0"
- **Reporter/date:** kgreene829, Apr 15 · **Type:** Bug · **Status:** 🟢 Already fixed
- Once a rotation is saved you can't return to fewer configured slots; >1 blank slot throws
  `Failed to save: duplicate player_id: 0`.
- **Finding:** Fixed in commit `bd2cce7` — `put_rotation` now exempts blank slots from the
  duplicate check: `gameplanning/__init__.py:908-911` (`elif pid != 0 and pid in seen_players`).
  No DB unique constraint on player_id. **Note:** the identical un-fixed pattern still exists in
  `put_bullpen` at `gameplanning/__init__.py:1044` (no `!= 0` guard) — worth a follow-up.
- **Next step:** Confirm reporter is on a build with `bd2cce7`; if still failing, stale frontend validation.

### MLB-02 — Waivered players have no player card
- **Reporter/date:** kgreene829, Apr 16 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** `get_waiver_wire`/`get_waiver_detail` return a slim shape (`player_id`,
  `player_name`, `ptype`, `age`, `displayovr`) with no `bio`/`ratings`/`potentials` — unlike the
  FA pool which attaches `build_player_display`. `services/waivers.py:669-690,723-745`;
  compare `services/fa_auction.py:1104-1107`.
- **Next step:** Enrich waiver endpoints with `load_display_context`/`build_player_display`.

### MLB-03 — Recruiting competitor visibility (point threshold)
- **Reporter/date:** (partial, ~Apr 18) · **Type:** Bug/Feature · **Status:** 🔴 See REC-AI-COMPETITOR (CBL-11)
- Fragment about competitor display updating on save/reload and only showing teams within a
  point threshold of the leader. Same root cause as CBL-11.

### MLB-04 — Quick links on each team page (gameplan/roster)
- **Reporter/date:** subsequent, Apr 18 · **Type:** Feature · **Status:** ⚪ Frontend-only
- **Finding:** Target endpoints exist (`transactions/__init__.py:536` roster, gameplan routes).
  Navigation add only.

### MLB-05 — No way to see a pitcher's hitting potentials
- **Reporter/date:** Fireballer34, Apr 18 · **Type:** Bug/Feature · **Status:** 🟣 Pure frontend
- **Finding:** `build_player_display` returns all `_pot` columns (incl. hitting pots) for pitchers,
  subject to scouting fuzz; nothing filters by ptype. `services/player_display.py:394-396`,
  `attribute_visibility.py:460-467`. Frontend just isn't rendering them on pitcher cards.

### MLB-06 — Show scouting progress on My Board / My Commitments
- **Reporter/date:** subsequent, Apr 20 · **Type:** Feature · **Status:** 🟣 Pure frontend (data ready)
- **Finding:** Board/detail already return `your_points`, `your_points_this_week`, `status`,
  `interest_gauge`. `services/recruiting.py:1257-1258,1093-1106`. Display add only.

### MLB-07 — IR players still count against roster size
- **Reporter/date:** Jieret, Apr 21 (seconded by nemolee.exe) · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** `_get_roster_count()` counts held players with no `onIR` filter; `place_on_ir()`
  sets `onIR=1` but leaves `current_level` unchanged, so the player still counts → spurious
  "Over limit". Same omission in `get_org_roster_summary`. `services/transactions.py:114-154,
  356-375,1614-1662`.
- **Next step:** Add `AND COALESCE(onIR,0)=0` to the count query (confirm IR-exempt rule first).

### MLB-08 — Exiting player profile from a box score closes the whole box score
- **Reporter/date:** Minnow, Apr 21 01:46 · **Type:** Bug · **Status:** 🟣 Pure frontend (modal stacking)
- No backend involvement — modal/overlay dismissal behavior in the SPA.

### MLB-09 — Show handedness on the roster page
- **Reporter/date:** Minnow, Apr 21 01:57 · **Type:** Feature · **Status:** 🟣 Pure frontend (data ready)
- **Finding:** `bat_hand`/`pitch_hand` already returned in roster `bio`
  (`railway_simbbPlayers.sql:62-63`; scouting whitelist `scouting/__init__.py:1341`). Display add only.

### MLB-10 — Game-result CSV export
- **Reporter/date:** Ezaco, Apr 22 · **Type:** Feature · **Status:** 🔵 Feature (needs backend)
- **Finding:** No CSV/export route exists. Most requested fields stored in
  `game_batting_lines`/`game_pitching_lines`/`game_results`, **except** `sacrifice_flies` (only in
  season-accum `player_batting_stats`) and `venue` (not on `game_results`).
- **Next step:** Thin CSV endpoint aggregating game-line tables; decide whether to add the 2 missing cols.

### MLB-11 — "Next starter" shows Slot 6 in a 5-man rotation; reliever starts
- **Reporter/date:** Jieret, Apr 25 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API, display/semantics)
- **Finding:** `current_slot` stores the slot that *last* pitched, not the next; true next is
  `(current_slot % size) + 1` (`services/rotation.py:555`), but the "(next)" label uses
  `current_slot` directly (`admin/static/admin/app.js:9854`) → off by one. The reliever start is a
  related effect: when the scheduled SP is below stamina threshold, a bullpen spot-starter is
  chosen (`rotation.py:595-603`).
- **Next step:** Compute the indicator as `(current_slot % rotation_size) + 1`.

### MLB-12 — Won a game with pitchers throwing only 8.3 IP
- **Reporter/date:** Fireballer34, Apr 25 · **Type:** Bug · **Status:** 🟠 Likely engine-side
- **Finding:** API stores `innings_pitched_outs` (integer outs) and renders `outs//3 . outs%3`;
  `%3` can only be 0/1/2, so the API **cannot** emit ".3". An 8.3/early total must originate from
  the engine's out count. No regulation-innings validation exists in `_store_game_results`.
  `games/__init__.py:1883-1884`, `services/game_payload.py:2269-2354`.
- **Next step:** Dump engine `stats.pitchers[*].innings_pitched_outs` for the game; fix in engine.

### MLB-13 — Tex pitchers only threw 8.2 IP (2nd Atl @ Tex)
- **Reporter/date:** anonemuss, Apr 28 · **Type:** Bug · **Status:** 🟠 Likely engine-side (same as MLB-12)

### MLB-14 — MLB free agency leaders not randomized
- **Reporter/date:** kgreene829, Apr 29 11:39 · **Type:** Bug · **Status:** 🟡 Design question / 🔵 Feature
- **Finding:** MLB FA winner is fully deterministic (highest age-weighted attractiveness, no
  random) — `services/fa_auction.py:558-559,40-85`. Recruiting (the "other league") *does*
  randomize via `_weighted_lottery` (`services/recruiting.py:701`). Ticket is accurate; current
  behavior is by design.
- **Next step:** Product call on whether to add a weighted-lottery/jitter to FA at `fa_auction.py:558`.

### MLB-15 — Designate backups / injury replacements
- **Reporter/date:** kgreene829, Apr 29 11:46 · **Type:** Feature · **Status:** 🔵 Feature (needs backend)
- **Finding:** Depth chart supports multiple players per position via `priority`/`target_weight`,
  but no "backup-only / never starts" flag; any priority-2 entry with non-zero weight still starts
  sometimes. `railway_team_position_plan.sql:33-58`, `gameplanning/__init__.py:734`.
- **Next step:** Add a `backup_only` flag (or treat `target_weight=0` as replacement-only) and propagate to payload.

### MLB-16 — Team-name tooltip on icon hover
- **Reporter/date:** subsequent, Apr 29 03:10 · **Type:** Feature · **Status:** ⚪ Frontend-only (data ready)
- **Finding:** `team_abbrev`/`team_name` available (`/teams`, most payloads). Verify the specific
  icon payload includes name; otherwise display-only.

### MLB-17 — Stat export capped at top 200 players
- **Reporter/date:** (partial, Apr 29 03:48) · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** Hardcoded `page_size = min(..., 200)` on batting/pitching/fielding leaderboards
  (`stats/__init__.py:46,451,807`) and the results list (`games/__init__.py:2055`).
- **Next step:** Add an export/all mode (e.g. `page_size=0` → uncapped) or a dedicated export route.

### MLB-18 — Injured "2 weeks" player healed already
- **Reporter/date:** Ezaco, Apr 30 08:52 · **Type:** Bug · **Status:** 🟠 Likely engine-side (see cluster)

### MLB-19 — Injured player healed 10 weeks in ~5
- **Reporter/date:** Fireballer34, Apr 30 07:24 · **Type:** Bug · **Status:** 🟠 Likely engine-side (see cluster)

### MLB-29 — Kit Garcia (#42139) healthy wk15, 27-week injury from wk2 *(injury-heal cluster)*
- **Reporter/date:** Ezaco, May 26 01:02 · **Type:** Bug · **Status:** 🟠 Likely engine-side
- **Cluster finding (MLB-18/19/29):** API stores engine's `duration_weeks` verbatim as
  `weeks_remaining` (`services/game_payload.py:2842,2881-2882`) and decrements exactly **once per
  game-week** (`services/timestamp.py:1043`); `_tick_injuries` is called once per week from
  `advance_week()` and the season runner only. No subweek/units bug, no double-decrement in
  standard flows. Reports are a consistent ~2×, consistent with the **engine reporting
  `duration_weeks` at ~half** the configured `injury_types.json` weeks (collarbone = 20/40/60w, so
  27w is in range). Caveat: running both a season-runner pass *and* a manual `advance_week` for the
  same week would double-tick.
- **Next step:** Log engine `duration_weeks` vs configured `mean_weeks` at `game_payload.py:2842`;
  confirm engine-side halving, and audit the operator workflow for a double `advance_week`.

### MLB-20 — Activated-from-Unassigned player disappeared
- **Reporter/date:** LordLittlebutt, May 1 08:24 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** No `levels` row for an "Unassigned"/0 sentinel (`railway_levels.sql` has ids
  1-9,99). Roster/ratings queries INNER JOIN `levels` (`rosters/__init__.py:441-444`) and drop
  null-level rows (`:858-861`). `activate_from_ir()` flips `onIR=0` but never restores/validates
  `current_level` (`services/transactions.py:400-442`); `demote_player()` doesn't validate the
  target level. So IR → Unassigned → activate orphans the player off every roster view.
- **Next step:** Define canonical "Unassigned" (real reserve level + LEFT JOIN, or reject/repair invalid `current_level`).

### MLB-21 — Player OVR pulls from current roster position rating
- **Reporter/date:** Ezaco, May 1 12:42 · **Type:** Bug · **Status:** 🟡 Design question (working as coded)
- **Finding:** OVR is an attribute-weighted average (`compute_raw_ovr`), but the weight set **and**
  percentile breakpoints are keyed to the player's *listed position* (`services/ovr_core.py:110-115,
  462-468`) — deliberately ("so displayovr == that position's rating"). So OVR is position-relative
  by design, which feeds the OVR-changes symptom (MLB-24).
- **Next step:** Product call: position-relative vs a fixed best-position overall.

### MLB-22 — Pitcher batting every day over position players
- **Reporter/date:** Ezaco, ~May · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** Field positions correctly exclude pitchers (`services/lineups.py:697-700`), but the
  **DH path does not** — `_build_dh_pool` (`:959-971`) and `_select_dh_player` (`:923-956`) never
  filter `ptype`, so a bullpen pitcher in the remaining pool can be picked as DH. Same in the cache
  variant (`:1182-1190`).
- **Next step:** Add `ptype != 'pitcher'` filter to the DH pool/selector (keep an opt-in for true two-way players).

### MLB-23 — Texas pitchers got no decisions (Tex @ Oak)
- **Reporter/date:** anonemuss, May 4 10:40 · **Type:** Bug · **Status:** 🟠 Likely engine-side
- **Finding:** API never assigns W/L; per-pitcher `win`/`loss` come straight from the engine
  (`services/stat_accumulator.py:594-595,1052-1053,1326-1327`). No code repairs a missing decision.
- **Next step:** Inspect engine payload for that game; fix decision assignment in engine.

### MLB-24 — Player OVR changes after opening/closing a card
- **Reporter/date:** subsequent + bundy, May 5 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** Two endpoints return different OVR for the same player. Roster-list path returns the
  **stored** `simbbPlayers.displayovr` column (`services/player_display.py:401`), refreshed only on
  weight activation / subweek; the player-card & fog paths **recompute live** every request
  (`scouting/__init__.py:1998-2009`, `attribute_visibility.py:651`). Between refreshes the stored
  value lags the live recompute → the value "changes" when the card path overwrites it. The
  "2-3 seconds" matches a second async fetch swapping stored→live.
- **Next step:** Single source of truth — always recompute inline (drop stored passthrough at
  `player_display.py:401`) or route roster lists through `compute_displayovr()`.

### MLB-25 — Recruiting shortcut on homepage
- **Reporter/date:** subsequent, May 9 10:16 · **Type:** Feature · **Status:** ⚪ Frontend-only (routes exist)

### MLB-26 — Pitchers slot in at DH / random-position shuffle on fatigue
- **Reporter/date:** Dearden, May 11 08:08 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** Same DH-pool root cause as MLB-22: the fatigue fallback Tier 3 fills DH from the
  unfiltered pool (incl. pitchers) even when utility players exist (`services/lineups.py:941-956`).
  Field-position fallback does stay within non-pitchers (`:806-822`), so the random *position*
  shuffles are position players, but DH specifically can grab a pitcher.
- **Next step:** Same fix as MLB-22; ensure utility players are preferred before any desperation tier.

### MLB-27 — Starter credited with a win on 2.2 IP (should be No Decision)
- **Reporter/date:** Minnow, May 12 11:03 · **Type:** Bug · **Status:** 🟠 Likely engine-side
- **Finding:** API does not enforce the 5-IP starter-win rule and does not override the engine's
  decision — trusts `p.get("win",0)` verbatim (`services/stat_accumulator.py:594,1052,1326`).
  Holds/saves the reporter saw as correct are also pass-through.
- **Next step:** Fix decision logic in the engine. (An API sanity-override would be a behavioral
  change requiring explicit approval per the no-unauthorized-edits rule.)

### MLB-28 — Lineups with pitchers in batting slots only work as DH
- **Reporter/date:** (partial, May 15 05:39) · **Type:** Bug · **Status:** 🔴 Confirmed bug (API, by-design limitation)
- **Finding:** No "force start" path for pitchers in field batting slots — `_choose_player_for_position`
  unconditionally drops pitchers from every field position with no override for force/locked/weight
  flags (`services/lineups.py:696-700`); schema has no force-start column. A pitcher can only enter
  the order via DH, matching "only works in DH".
- **Next step:** If pitchers-batting is intended, add an explicit allow path for plan rows forcing a
  pitcher at a field slot; otherwise document as DH-only.

### MLB-30 — Two blown saves on the same team (STBK @ NCAT, Wk16)
- **Reporter/date:** (subsequent), May 26 03:20 · **Type:** Bug · **Status:** 🟠 Likely engine-side (probably not a bug)
- **Finding:** API passes `blown_save` through per pitcher (`services/stat_accumulator.py:598`;
  box score `games/__init__.py:1909`). Two different relievers each blowing a save in one game is
  **legal** baseball, so likely not a bug.
- **Next step:** Confirm the two BS are on two distinct player_ids in genuine save situations; if so, no action.

### MLB-31 — Starting pitcher keeps pitching as closer (not in bullpen)
- **Reporter/date:** Fireballer34, May 26 03:45 · **Type:** Bug · **Status:** 🟠 Likely engine-side
- **Finding:** API excludes configured rotation pitchers from the bullpen list
  (`services/game_payload.py:1656-1658`) but appends any non-rotation pitcher as a fallback
  (`:1663-1669`); the actual closer/role pick is done by the engine. If the SP is in the rotation
  slots, the API already excludes him → engine bug; if not, it's expected fallback.
- **Next step:** Verify the SP's player_id is in `team_pitching_rotation_slots`; if yes, engine-side.

### MLB-32 — Minnow post, May 8 08:48 (edited) — content not captured
- **Reporter/date:** Minnow, May 8 · **Type:** Unknown · **Status:** ❓ Needs source
- The post body fell in the gap between PDF page captures (pages 11→12 show only the reply
  buttons). **Next step:** Re-capture/screenshot this post to log its content.

---

## College / CBL thread (`SUPPORT_College_Notes.pdf`)

### CBL-01 — CBL lineups slow to load (MLB was instant)
- **Reporter/date:** nemolee.exe, Apr 16 · **Type:** Bug/Perf · **Status:** 🔴 Confirmed perf smell (+ see CBL-05)
- **Finding:** Every roster/ratings request rebuilds league-wide distributions on cache-miss — a
  full-league scan of all active players (`rosters/__init__.py:646-655`, returns `"computed"`) when
  `rating_scale_config` is empty, plus per-request weight/breakpoint reloads.
- **Next step:** Populate `rating_scale_config` so the full-table fallback never runs, or cache `dist_by_level`.

### CBL-02 — Own scouted players revert to fuzzed grades on mobile
- **Reporter/date:** Sarge, Apr 16 · **Type:** Bug · **Status:** 🟡 Design question (fuzzing is by design)
- **Finding:** Fog-of-war fuzzes a team's *own* roster by design — `determine_player_context` has no
  own-org bypass (`services/attribute_visibility.py:198-226`); only `viewing_org_id is None`
  (admin/legacy) returns true values. So the roster list is correctly fuzzed; "real grades on click"
  means the detail path omits `viewing_org_id` or the SPA caches precise data — a frontend
  inconsistency.
- **Next step:** Product call — if teams should fully know their own players, add an own-org bypass
  in `determine_player_context`; otherwise fix the frontend to pass `viewing_org_id` consistently.

### CBL-03 — Gameplan shows nothing for CBL ("under gameplan, nothing shows up")
- **Reporter/date:** nemolee.exe, Apr 16 · **Type:** Bug · **Status:** ❓ See GP-NOPOPULATE (CBL-05)

### CBL-04 — Can't set a recruit's points back to 0 (resets; min 1)
- **Reporter/date:** Ezaco, Apr 19 · **Type:** Bug · **Status:** 🟣 Pure frontend (backend handles 0)
- **Finding:** Invest service treats `pts == 0` as "remove": DELETEs the row and refunds the budget
  (`services/recruiting.py:472-486`); only `pts < 0` is rejected (`:455`); endpoint passes the array
  through untouched (`recruiting/__init__.py:249`). Symptom is the frontend dropping/min-clamping 0
  before POST.
- **Next step:** Inspect the frontend invest payload for a truthy `if (points)` filter or `Math.max(1, …)`.

### CBL-05 — Gameplan doesn't populate players (CBL)
- **Reporter/date:** Spoof, Apr 20 09:44 · **Type:** Bug · **Status:** ❓ Cannot determine (one real API hazard)
- **Finding:** Gameplan config itself is level-agnostic; player population comes from rosters
  endpoints. **Two college-specific hazards:** (1) `_build_ratings_base_stmt` INNER-joins `levels`
  on `current_level` (`rosters/__init__.py:441-444`) — if there's no `levels` row `id=3` (College),
  all college players are silently dropped; (2) `get_org_ratings`/`get_league_ratings` hardcode
  `level_filter=(4,9)` (`:788,898`), excluding college entirely. MLB (level 9) is unaffected.
- **Next step:** Confirm a `levels` row exists for `id=3`, and check which endpoint the CBL frontend
  hits — if it's org/league ratings, the `(4,9)` filter is the bug. (Covers CBL-01/03/05.)

### CBL-06 — Redshirt button opens contract-renewal screen
- **Reporter/date:** Spoof, Apr 20 12:18 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API — endpoint missing)
- **Finding:** No runtime redshirt-apply endpoint exists anywhere. `redshirt` appears only in
  `seeding/amateur_contracts_seed.py` (one-time league gen) and admin display labels. The button has
  no real action to call.
- **Next step:** Add a redshirt transaction endpoint (toggle redshirt/extension flag, extend years),
  then point the frontend at it.

### CBL-07 — Can't reallocate freed recruiting points; "Exceeds weekly budget"
- **Reporter/date:** Ezaco (quote reply) · **Type:** Bug · **Status:** 🔴 Confirmed bug (API)
- **Finding:** `submit_weekly_investments` seeds `points_used = existing_total` (full prior spend),
  then validates each investment incrementally in array order (`services/recruiting.py:448,522,539`).
  If a save raises player B before lowering player A, B's check still includes A's old allocation →
  "Exceeds weekly budget" (`:540`). Failure depends entirely on input ordering.
- **Next step:** Pre-compute the net delta of the whole batch (or apply all reductions/deletes
  before increases) before the per-player budget gate.

### CBL-08 — Won a game with pitchers throwing only 8.2 IP (college)
- **Reporter/date:** Fireballer34, Apr 25 11:48 · **Type:** Bug · **Status:** 🟠 Likely engine-side (same as MLB-12/13)

### CBL-09 — Note: college pitchers may throw fewer innings due to lower stamina
- **Reporter/date:** Fireballer34, Apr 25 11:49 · **Type:** Note/hypothesis · **Status:** ℹ️ Informational
- Reporter's own speculation on CBL-08. Stamina recovery is `base_recovery_pitcher` per subweek ×
  durability (`services/game_payload.py:3066-3077`); related to CBL-14.

### CBL-10 — "No standings available" on CBL dashboard
- **Reporter/date:** PoopyRhinoPickle, Apr 27 · **Type:** Bug · **Status:** ❓ Appears correct in API
- **Finding:** `_get_standings` includes college (`WHERE t.team_level >= 3`, grouped by conference)
  and uses `game_type='regular'` which college games default to (`bootstrap/__init__.py:1987-2122`,
  `schedule_generator.add_series`). Plausible non-code causes: `current_season_id` None (early
  return `[]`), no completed college regular games yet, or the SPA expecting a separate `/standings`
  route (only in the bootstrap payload).
- **Next step:** Verify the bootstrap response has `Standings` entries with `team_level=3` and a
  non-null `current_season_id` for a CBL org; if present, it's frontend rendering/filtering.

### CBL-11 — AI small teams win recruits with few points / not shown as competitors
- **Reporter/date:** Viselli, May 23 · **Type:** Bug · **Status:** 🔴 Confirmed bug (API, design mismatch)
- **Finding:** Two real issues: (1) the commitment lottery weights *every* investing org by
  `pts ** exponent` with **no floor** (`services/recruiting.py:696-701`, `_weighted_lottery`), so a
  ~half-points org can win; (2) competitor display filters to orgs `>= 50%` of the leader
  (`:1049-1056,1280-1286,548-554`) and only counts `week < current_week` investments (`:1040`), so a
  sub-50%/late-surge org is hidden yet can still win. Display threshold and win-eligibility are
  inconsistent. (Same underlying issue as MLB-03.)
- **Next step:** Product call — cap lottery eligibility to the display threshold, or lower the display
  threshold so any lottery-eligible org appears.

### CBL-12 — Make Commitments table sortable
- **Reporter/date:** Ezaco, Jun 4 · **Type:** Feature · **Status:** 🟣 Pure frontend (or small backend param)
- **Finding:** Commitments endpoint reads no `sort`/`dir` param; order hardcoded
  `ORDER BY week_committed ASC, star_rating DESC` (`recruiting/__init__.py:465-474`,
  `services/recruiting.py:517`). Each row carries `star_rating`/`week_committed`/`competitor_team_ids`,
  so the frontend can client-sort. Optionally add a whitelisted `sort` param.

### CBL-13 — Recruiting overview enhancements
- **Reporter/date:** TuscanSota, Jun 4 · **Type:** Feature · **Status:** 🟣 Pure frontend (data ready) / 🟡 partial
- Three asks: (a) recruit progress from Overview — data already returned (see MLB-06); (b) see which
  teams recruit which recruits without adding to board — the competitor list is server-pre-filtered
  to ≥50% (`services/recruiting.py:548-554`), so showing *all* recruiters is a product/threshold
  decision tied to CBL-11; (c) filter non-contending teams in competitors view — client-side on
  existing `competitor_team_ids`.

### CBL-14 — 3 designated college starters, but only 1 started in a series
- **Reporter/date:** PoopyRhinoPickle, Jun 8 · **Type:** Bug/Question · **Status:** ❓ Cannot determine (tuning-suspect)
- **Finding:** Rotation advancement math is correct (`next = (current_slot % size)+1`,
  `services/rotation.py:651-654`). Two plausible API contributors: (1) when the scheduled starter is
  below the stamina threshold (default `normal`=70), the code prefers a **bullpen spot-starter over
  the next rested rotation arm** (`rotation.py:595-603`); (2) if per-game engine `stamina_cost` drain
  exceeds ~4 subweeks of recovery (`game_payload.py:2961-2979,3066-3077`), a college SP never climbs
  back to threshold. Drain magnitude is engine-side.
- **Next step:** Inspect `player_fatigue_state` for the 3 SPs across the week vs engine `stamina_cost`;
  if drain > recovery, raise college recovery / lower threshold — and consider trying the next
  rotation arm before a bullpen spot-starter.

---

## Cross-references / duplicate clusters

- **Short-innings / early-end games:** MLB-12, MLB-13, CBL-08 → engine out-counting; no API regulation-innings validation.
- **Pitching decisions:** MLB-23 (no decisions), MLB-27 (invalid SP win), MLB-30 (two BS) → all engine pass-through.
- **Fast injury healing:** MLB-18, MLB-19, MLB-29 → engine likely halving `duration_weeks`.
- **Pitcher in batting order:** MLB-22, MLB-26, MLB-28 → DH pool doesn't exclude pitchers (`services/lineups.py`).
- **OVR inconsistency:** MLB-21 (position-relative by design) explains MLB-24 (stored vs live divergence).
- **Recruiting points/budget:** CBL-04 (frontend), CBL-07 (API order-of-ops).
- **Recruiting AI competitors:** MLB-03, CBL-11, CBL-13(b) → lottery floor vs display threshold mismatch.
- **CBL gameplan/roster empty:** CBL-01, CBL-03, CBL-05 → `levels` join / `(4,9)` level filter.
- **Rotation / starter selection:** MLB-01 (fixed), MLB-11 (next-slot label), MLB-31 (SP as closer), CBL-14 (stamina tuning).
