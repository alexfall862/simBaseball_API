// features/system/migrations.js — one-shot schema/data migrations exposed by admin/__init__.py.
// The legacy panel only had "Fix amateur contract years"; the other three endpoints existed
// without UI and are surfaced here as well. All are POST /admin/migrations/<name> and return
// {ok:true, ...result} or {ok:false, error:'migration_failed', message}.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';

const MIGRATIONS = Object.freeze([
  {
    key: 'fix-amateur-contracts', title: 'Fix amateur contract years', danger: true,
    desc: 'Recalculates years and current_year for all active HS and College contracts so the frontend can derive class year correctly. Also moves 18-year-old college players back to HS.',
    bullets: ['HS contracts → 4-year, current_year = age − 14', 'College (non-RS) → 4-year, current_year = age − 18', 'College (redshirt) → 5-year, current_year = age − 18', 'Rebuilds contractDetails + contractTeamShare rows'],
  },
  {
    key: 'add-recruiting-columns', title: 'Add recruiting columns', danger: false,
    desc: 'Adds signing_tendency and recruit_stars columns to the player table and backfills them.',
    bullets: ['Idempotent — safe to re-run if the columns already exist'],
  },
  {
    key: 'add-ncaa-tournament', title: 'Add NCAA tournament schema', danger: false,
    desc: 'Creates playoff_seeds (if missing) and adds the multi-stage tracking columns to cws_bracket for the 64-team college postseason.',
    bullets: ['Idempotent — checks for existing tables/columns first'],
  },
  {
    key: 'add-waiver-tables', title: 'Add waiver wire tables', danger: false,
    desc: 'Creates the waiver wire tables and extends the transaction_log enum with the waiver event types.',
    bullets: ['Idempotent — safe to re-run'],
  },
]);

function migrationCard(m) {
  return `<div class="card${m.danger ? ' danger-zone' : ''}" id="mig-${m.key}">
    <h3>${html`${m.title}`}</h3>
    <p class="text-muted small mb-1">${html`${m.desc}`}</p>
    <ul class="small text-muted mb-2 cron-preview">${m.bullets.map(b => `<li>${html`${b}`}</li>`).join('')}</ul>
    <div class="row"><button class="btn ${m.danger ? 'btn-danger' : 'btn-primary'}" data-action="run" data-key="${html`${m.key}`}">Run migration</button><code class="small text-muted">POST /admin/migrations/${html`${m.key}`}</code></div>
    <div class="mig-progress"></div>
  </div>`;
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="alert alert-info">Migrations run synchronously inside the request and modify the schema or rewrite rows. Take a database backup first, run them once, and never while a simulation is running.</div>
    ${raw(MIGRATIONS.map(migrationCard).join(''))}`);

  const widgets = new Map();
  for (const m of MIGRATIONS) widgets.set(m.key, progressWidget(q(el, `#mig-${m.key} .mig-progress`)));

  delegate(el, 'click', '[data-action="run"]', async (e, btn) => {
    const m = MIGRATIONS.find(x => x.key === btn.dataset.key);
    if (!m) return;
    if (!await confirm({
      title: `Run migration: ${m.title}?`, danger: true, typeToConfirm: 'MIGRATE', confirmLabel: 'Run migration',
      message: m.danger ? 'This rewrites contract rows for every HS/College player and cannot be undone automatically.' : 'This alters the database schema. It is idempotent but still needs a backup.',
      detail: `POST /admin/migrations/${m.key}`,
    })) return;
    btn.disabled = true;
    try {
      await runTracked({ el: q(el, `#mig-${m.key} .mig-progress`), widget: widgets.get(m.key), label: `${m.title}…`, signal: ctx.signal,
        start: () => api.post(adm(`/migrations/${m.key}`), {}, { signal: ctx.signal }) });
      toast.success(`${m.title} finished`);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
    } finally { btn.disabled = false; }
  }, ctx.signal);
}
