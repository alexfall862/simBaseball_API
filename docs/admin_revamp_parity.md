# Admin revamp — parity index

Each legacy section of `admin/templates/admin/legacy.html` + `admin/static/admin/app.js` was ported to a tab module under `admin/static/admin/js/features/`. The per-area tables below list every legacy button / action / endpoint and where it lives now (or why it was dropped).

| Area | Parity table | New tabs |
|---|---|---|
| Command Center, Season (Simulate, Phase & Week, Checklist), Jobs, Timeline, Settings | this file, below | `features/command-center/`, `features/season/{simulate,phase,checklist}.js`, `features/jobs/`, `features/timeline/`, `features/system/settings.js` |
| Season: Playoffs, Special Events, Schedule | [parity/season.md](parity/season.md) | `features/season/{playoffs,events,schedule}.js` |
| Market | [parity/market.md](parity/market.md) | `features/market/*.js` |
| Player Engine | [parity/engine.md](parity/engine.md) | `features/engine/*.js` |
| Analytics | [parity/analytics.md](parity/analytics.md) | `features/analytics/*.js` |
| Data & System | [parity/data-system.md](parity/data-system.md) | `features/data/*.js`, `features/system/*.js` |

## Core tabs (ported directly during Phase 0–2)

| Legacy section / control | Endpoint | New location |
|---|---|---|
| dashboard: season/week/tasks/db cards, quick actions | `/games/timestamp`, `/games/tasks`, `/healthz` → `GET /admin/summary` | Command Center |
| simulate: phase badge, A–D flags, Sim Subweek a–d, Sim All Remaining, Advance, Reset Week | `/games/simulate-subweek`, `/games/simulate-week`, `/games/advance-week`, `/games/reset-week` | Season › Simulate (state bar) |
| simulate: Engine Config Cache clear | `POST /admin/clear-caches` | Season › Simulate |
| simulate: Manual Simulation preview/run (level loader `/schedule/week-levels` replaced by static levelSelect) | `GET /games/simulate-week/<y>/<w>`, `POST /games/simulate-week`, `POST /games/simulate-subweek` | Season › Simulate |
| simulate: Run Season / Run All Levels + progress | `/games/run-season`, `/games/run-season-all`, `/games/tasks/<id>` | Season › Simulate (runTracked) |
| simulate: Wipe Season, Rollback to Week | `/games/wipe-season`, `/games/rollback-to-week` | Season › Simulate › Danger zone (typeToConfirm) |
| playoffs panel: Rest Week (Stamina) | `/games/stamina-rest` | Season › Simulate › Stamina rest |
| timestamp: state, AvailableActions buttons, Jump to Week, Phase Override | `/games/timestamp`, `/games/<action>`, `/games/set-week`, `/games/set-phase` | Season › Phase & Week |
| timestamp: End Regular Season | `POST /games/end-season` → job `end_season` | Season › Phase & Week (runs as a job) |
| timestamp: Start New Season | `POST /games/start-new-season` | Season › Phase & Week |
| timestamp: Listed Positions, Default Gameplans | `/admin/fill-listed-positions`, `/admin/generate-default-gameplans` | Season › Phase & Week |
| timestamp: Offseason Checklist + Run buttons | `GET /admin/offseason/checklist`, step actions | Season › Offseason Checklist |
| timestamp: Season Archive | `POST /admin/season/archive` → job `archive_season` | Season › Offseason Checklist (runs as a job) |
| tasks: table, download, delete | `/games/tasks*` | Jobs › Background Tasks |
| synthetic: async/sync generation + progress | `/games/debug/synthetic(-async)` | Jobs › Background Tasks |
| (new) scheduled jobs, run history, logs | `/admin/jobs*`, `/admin/logs` | Jobs |
| (new) timeline | `/admin/timeline` | Timeline |
| sidebar: login/logout, write-mode toggle | `/admin/login`, `/admin/logout`, `/admin/me`, `/admin/write-mode` | login gate, System › Settings |
| dashboard: API endpoint list card | — | dropped (static text) |
