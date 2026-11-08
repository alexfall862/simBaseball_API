# Admin SPA — module contracts

Native ES modules, no bundler. Served by Flask from `admin/static/admin/`. Entry: `js/main.js`, shell template: `admin/templates/admin/index.html`. The legacy single-file UI is still served at `/admin/legacy` (`legacy.html` + `app.js` + `styles.css`) until every section has been ported.

## Layout

```
js/
  main.js               boot, auth gate, sidebar/tabs/topbar, polling, palette
  core/
    api.js              api.get/post/put/del, v1('/games/x'), adm('/jobs'), ApiError, admin password header
    router.js           hash router  #/<area>/<tab>?k=v ; navigate(area, tab, params); setParams()
    store.js            store.get()/set()/watch(key, fn, signal); prefs.get/set (localStorage)
    ws.js               reconnecting /ws; emits bus 'ws:<type>'
    bus.js              bus.on(type, fn, signal) / bus.emit
    constants.js        LEVEL_NAMES, SIM_LEVELS, ALL_LEVELS, SUBWEEKS, PHASES, phaseLabel()
    html.js             html`` (escapes), raw(), esc(), el(), setHtml(), on(), delegate(), q(), qa()
    format.js           fmtNum, fmtMoney, fmtPct, fmtRate, fmtDate, relTime, fmtDuration, json, titleCase
  ui/
    table.js            dataTable(el, {columns, rows, ...}) -> {setRows, setLoading, setError}; simpleTable(); kvTable()
    form.js             field.text/number/select/checkbox/textarea/json/datetime, formGrid, formRow, readForm, writeForm, card(), button()
    modal.js            openModal, confirm({danger, typeToConfirm}), promptText, showResult
    toast.js            toast.success/error/info/warn
    badge.js            badge, statusBadge, phaseBadge, boolBadge, kpi, subweekPips, subweekFlagsFromTs, spinner, emptyState, alertBox
    task-runner.js      pollTask, pollRun, progressWidget, runTracked({el, label, start, signal}), busyButton
    selectors.js        leagueYearSelect, levelSelect, teamSelect, loadLeagueYears, loadTeams, defaultLeagueYearId, fillSelect
    chart.js            mountChart(canvas, config, signal), chartCanvas(parent, {height}), color(i)
    tabs.js             subTabs(el, items, {onSelect, signal}), collapsible
  features/
    index.js            AREAS registry (area -> tabs -> lazy import)
    <area>/<tab>.js     one module per tab
```

## Tab module contract

```js
import { api, v1, adm } from '../../core/api.js';
import { html, raw, setHtml, on, delegate } from '../../core/html.js';
import { store } from '../../core/store.js';

export async function mount(el, ctx) {
  // ctx = { signal, params, area, tab, navigate, setParams, el }
  // - render markup into `el` (use html`` so values are escaped)
  // - bind listeners with on(node, 'click', fn, ctx.signal) or delegate(el, 'click', '[data-action]', fn, ctx.signal)
  // - pass ctx.signal to api calls, pollTask/runTracked, mountChart, store.watch
  // - read the league year via store.get().leagueYearId / defaultLeagueYearId(), or mount a leagueYearSelect
}
export function unmount() {}   // optional; signal abort already stops polls/listeners/charts
```

## Rules

1. **No `fetch`.** Always `api.*`. Errors throw `ApiError` and toast automatically; pass `{ quiet: true }` to suppress and handle yourself.
2. **No `alert/confirm/prompt`.** Use `toast`, `confirm()`, `promptText()`, `showResult()`.
3. **No inline `style=` for layout/colour.** Use classes from `css/components.css` (card, grid-2/3/4, form-grid, form-group, button-group, btn-*, badge-*, data-table, kv-table, result-box, alert-*, row, stack, mt-1/2, text-muted...). Only computed widths/heights may be inline.
4. **Escape everything.** `html``` escapes interpolations; wrap trusted markup in `raw()`. `dataTable` escapes cells unless the column has `html: true`.
5. **No module-level mutable state** across mounts except caches that are safe to share. Keep per-mount state inside `mount()`.
6. **Every poll/interval/listener/chart is tied to `ctx.signal`.** No bare `setInterval` without clearing on abort. Use `pollTask`/`runTracked`.
7. **Long operations** go through `runTracked({ el: progressContainer, label, start: () => api.post(...), signal })`. It handles `{task_id}` (polls `/api/v1/games/tasks/<id>`), `{run_id}` (polls `/admin/jobs/runs/<id>`), or a plain result.
8. **Destructive actions** use `confirm({ danger: true, typeToConfirm: 'WIPE' })`.
9. **Lookups** come from `core/constants.js`. Never redefine level names, phase labels, or position maps.
10. **Selectors** come from `ui/selectors.js`. Never hand-roll a league-year dropdown loader.
11. **Password-header endpoints** (`/admin/run-*-books`, `/admin/run-playoff-revenue`, etc.) are called with `api.post(url, body, { admin: true })`. The header value is the login password, stored in sessionStorage at login.
12. Keep each tab module self-contained. Shared helpers for one area go in `features/<area>/_shared.js`.

## Parity

When porting a legacy section, every button and every endpoint call in the legacy code must have a counterpart in the new tab (or be replaced by a job type). Record it in `docs/admin_revamp_parity.md`.
