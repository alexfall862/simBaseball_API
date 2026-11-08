// features/jobs/tasks.js — background_tasks table (port of legacy #section-tasks + synthetic games).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { fmtDate, relTime, json } from '../../core/format.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { statusBadge } from '../../ui/badge.js';
import { confirm, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { levelSelect } from '../../ui/selectors.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head"><h3>Background tasks</h3><div class="row"><label class="checkbox-label small"><input type="checkbox" id="t-auto" checked /> auto-refresh</label><button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button></div></div>
      <p class="text-muted small mb-2">Rows in <code>background_tasks</code> (1h TTL). Job runs mirror themselves here as <code>job:&lt;type&gt;</code>.</p>
      <div id="tasks-table"></div>
    </div>
    <div class="card">
      <h3>Synthetic games (engine smoke test)</h3>
      <p class="text-muted small mb-2">Generate random matchups and run them through the engine without touching league data.</p>
      ${raw(formGrid([
        field.number('count', 'Games', { value: 10, min: 1, max: 500 }),
        `<div class="form-group"><label for="syn-level">Level</label><select id="syn-level" name="level"></select></div>`,
        field.number('seed', 'Seed (sync only)', { placeholder: 'optional' }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" data-action="syn-async">Run async (task)</button><button class="btn btn-secondary" data-action="syn-sync">Run sync</button></div>
      <div id="syn-progress"></div>
    </div>`);

  levelSelect(q(el, '#syn-level'), { levels: ALL_LEVELS, value: 9 });
  const synProgress = progressWidget(q(el, '#syn-progress'));

  const table = dataTable(q(el, '#tasks-table'), {
    rowKey: 'task_id', emptyText: 'No tasks.', sortKey: 'created_at', sortDir: 'desc',
    columns: [
      { key: 'task_id', title: 'ID', html: true, render: r => `<code>${html`${r.task_id}`}</code>` },
      { key: 'task_type', title: 'Type', cellClass: 'mono' },
      { key: 'status', title: 'Status', html: true, render: r => statusBadge(r.status) },
      { key: 'progress', title: 'Progress', render: r => (r.total ? `${r.progress}/${r.total} (${Math.round((r.progress / r.total) * 100)}%)` : `${r.progress || 0}`), sortValue: r => r.progress },
      { key: 'created_at', title: 'Created', render: r => relTime(r.created_at), title_attr: r => fmtDate(r.created_at), sortValue: r => r.created_at },
      { key: 'error', title: 'Error', html: true, render: r => (r.error ? `<span class="text-danger small">${html`${String(r.error).slice(0, 100)}`}</span>` : '') },
      { key: '_a', title: '', html: true, render: r => `<div class="row nowrap">
          <button class="btn btn-xs btn-secondary" data-action="view" data-id="${html`${r.task_id}`}">Result</button>
          ${String(r.status).toLowerCase() === 'complete' ? `<a class="btn btn-xs btn-primary" href="${v1(`/games/tasks/${r.task_id}/download`)}" target="_blank" rel="noopener">Download</a>` : ''}
          <button class="btn btn-xs btn-danger" data-action="delete" data-id="${html`${r.task_id}`}">✕</button></div>` },
    ],
  });

  let timer = null;
  async function load() {
    try {
      const d = await api.get(v1('/games/tasks'), { signal: ctx.signal, quiet: true });
      const rows = d.tasks || [];
      table.setRows(rows);
      clearTimeout(timer);
      const active = rows.some(t => ['running', 'pending'].includes(String(t.status).toLowerCase()));
      if (q(el, '#t-auto').checked) timer = setTimeout(load, active ? 3000 : 15000);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }
  ctx.signal.addEventListener('abort', () => clearTimeout(timer));
  on(q(el, '#t-auto'), 'change', load, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action; const id = btn.dataset.id;
    try {
      if (a === 'refresh') return load();
      if (a === 'delete') { if (!await confirm({ title: `Delete task ${id}?` })) return; await api.del(v1(`/games/tasks/${id}`)); toast.success('Deleted'); return load(); }
      if (a === 'view') { const t = await api.get(v1(`/games/tasks/${id}`), { params: { include_result: 'true' } }); showResult(`Task ${id}`, t); return; }
      if (a === 'syn-async' || a === 'syn-sync') {
        const f = readForm(el);
        const params = { count: f.count, level: f.level };
        if (a === 'syn-sync' && f.seed) params.seed = f.seed;
        await runTracked({ el: q(el, '#syn-progress'), widget: synProgress, label: a === 'syn-async' ? 'Generating synthetic games (task)…' : 'Generating synthetic games…', signal: ctx.signal,
          start: () => api.get(v1(a === 'syn-async' ? '/games/debug/synthetic-async' : '/games/debug/synthetic'), { params }) });
        load();
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await load();
}
