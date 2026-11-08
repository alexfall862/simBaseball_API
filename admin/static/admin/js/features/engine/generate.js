// features/engine/generate.js — player generation + seed-table status (port of legacy #section-pe-generate).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { dataTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { confirm } from '../../ui/modal.js';
import { busyButton } from '../../ui/task-runner.js';
import { setStatus } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Generate players</h3><p class="card-sub text-muted">Creates new players in the database with the player engine. Large batches (hundreds+) take a while; the response lists the first 500.</p></div>
      </div>
      ${raw(formGrid([
        field.number('count', 'Count', { value: 1, min: 1, max: 5000 }),
        field.number('age', 'Starting age', { value: 15, min: 14, max: 45 }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" id="btn-gen">Generate</button></div>
      <div class="mt-1" id="gen-status"></div>
      <div class="mt-1" id="gen-table"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Seed tables</h3><p class="card-sub text-muted">Row counts for the player-engine seed tables (names, regions, archetypes…). Generation needs every table populated.</p></div>
        <div class="card-actions"><button class="btn btn-sm btn-ghost" data-action="refresh-seed">Refresh</button></div>
      </div>
      <div id="seed-table"></div>
    </div>`);

  const genTable = dataTable(q(el, '#gen-table'), {
    rowKey: 'id', emptyText: 'No players generated yet.', pageSize: 100,
    columns: [
      { key: 'id', title: 'ID', sortable: true, width: '90px' },
      { key: 'name', title: 'Name', sortable: true, render: r => `${r.firstname || ''} ${r.lastname || ''}`.trim(), sortValue: r => `${r.lastname || ''} ${r.firstname || ''}` },
      { key: 'ptype', title: 'Type', sortable: true, html: true, render: r => badge(r.ptype || '?', r.ptype === 'Pitcher' ? 'info' : 'success') },
      { key: 'age', title: 'Age', sortable: true, align: 'right' },
      { key: 'area', title: 'Region', sortable: true },
    ],
  });

  const seedTable = dataTable(q(el, '#seed-table'), {
    rowKey: 'table', emptyText: 'No seed tables found.',
    columns: [
      { key: 'table', title: 'Table', html: true, render: r => `<code>${html`${r.table}`}</code>` },
      { key: 'rows', title: 'Rows', align: 'right', render: r => (r.rows >= 0 ? fmtNum(r.rows) : 'Error') },
      { key: 'status', title: 'Status', html: true, render: r => badge(r.rows > 0 ? 'Ready' : 'Empty', r.rows > 0 ? 'success' : 'danger') },
    ],
  });

  async function loadSeedStatus() {
    seedTable.setLoading();
    try {
      const tables = await api.get(v1('/player-ops/seed-status'), { signal: ctx.signal, quiet: true });
      seedTable.setRows(Array.isArray(tables) ? tables : []);
    } catch (e) {
      if (e.name !== 'AbortError') seedTable.setError(e.message);
    }
  }

  delegate(el, 'click', '[data-action="refresh-seed"]', () => loadSeedStatus(), ctx.signal);

  busyButton(q(el, '#btn-gen'), async () => {
    const f = readForm(el);
    const count = f.count || 1;
    const age = f.age || 15;
    if (count >= 500 && !await confirm({ title: `Generate ${count} players?`, message: `This writes ${count} new players (age ${age}) to the database and may take several minutes.` })) return;
    const status = q(el, '#gen-status');
    setStatus(status, `Generating ${count} player${count > 1 ? 's' : ''}…`);
    genTable.setLoading();
    try {
      const data = await api.post(v1('/player-ops/generate'), { count, age }, { signal: ctx.signal });
      let msg = `Generated ${data.created} player${data.created !== 1 ? 's' : ''}.`;
      if (data.truncated) msg += ` Showing first ${data.showing} in the table.`;
      setStatus(status, msg, 'success');
      genTable.setRows(data.players || []);
      toast.success(msg);
    } catch (e) {
      if (e.name === 'AbortError') return;
      setStatus(status, `Error: ${e.message}`, 'danger');
      genTable.setError('Generation failed');
    }
  });

  await loadSeedStatus();
}
