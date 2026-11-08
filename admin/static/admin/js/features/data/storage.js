// features/data/storage.js — database storage report (port of legacy #section-db-storage).
// GET /admin/db-storage → {ok, tables:[{table_name, table_rows, data_mb, index_mb, total_mb, free_mb}], summary:{...}}

import { api, adm } from '../../core/api.js';
import { html, raw, esc, setHtml, on, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { kpi } from '../../ui/badge.js';

const num = (v) => (v == null || v === '' ? 0 : Number(v) || 0);

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Database storage report</h3><p class="card-sub text-muted">Size and row count of every table (<code>information_schema.tables</code>; row counts are InnoDB estimates). <code>GET /admin/db-storage</code>.</p></div>
        <div class="row"><input type="text" id="dbs-filter" placeholder="filter tables…" style="width:180px" /><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
      </div>
      <div id="dbs-status" class="text-muted small"></div>
    </div>
    <div class="grid-auto" id="dbs-summary"></div>
    <div class="card">
      <h3>Tables</h3>
      <div id="dbs-table"></div>
    </div>`);

  let tables = [];
  let maxMb = 0.01;
  const table = dataTable(q(el, '#dbs-table'), {
    rowKey: 'table_name', sortKey: 'total_mb', sortDir: 'desc', compact: true, emptyText: 'No tables.',
    columns: [
      { key: 'table_name', title: 'Table', sortable: true, html: true, render: r => `<strong>${esc(r.table_name)}</strong>` },
      { key: 'table_rows', title: 'Rows', align: 'right', sortable: true, render: r => fmtNum(r.table_rows), sortValue: r => num(r.table_rows) },
      { key: 'data_mb', title: 'Data (MB)', align: 'right', sortable: true, render: r => fmtNum(r.data_mb, 2), sortValue: r => num(r.data_mb) },
      { key: 'index_mb', title: 'Index (MB)', align: 'right', sortable: true, render: r => fmtNum(r.index_mb, 2), sortValue: r => num(r.index_mb) },
      { key: 'total_mb', title: 'Total (MB)', align: 'right', sortable: true, html: true, render: r => `<strong>${esc(fmtNum(r.total_mb, 2))}</strong>`, sortValue: r => num(r.total_mb) },
      { key: 'free_mb', title: 'Free (MB)', align: 'right', sortable: true, render: r => fmtNum(r.free_mb, 2), sortValue: r => num(r.free_mb) },
      { key: '_share', title: 'Share', html: true, width: '140px', render: r => {
        const pct = Math.max(0, Math.min(100, Math.round((num(r.total_mb) / maxMb) * 100)));
        return `<div class="progress-container" style="height:10px" title="${pct}% of the largest table"><div class="progress-fill" style="width:${pct}%"></div></div>`;
      } },
    ],
  });

  function applyFilter() {
    const f = q(el, '#dbs-filter').value.trim().toLowerCase();
    table.setRows(f ? tables.filter(t => String(t.table_name).toLowerCase().includes(f)) : tables);
  }

  async function load() {
    const status = q(el, '#dbs-status');
    status.textContent = 'Loading…';
    table.setLoading();
    try {
      const d = await api.get(adm('/db-storage'), { signal: ctx.signal });
      tables = d.tables || [];
      maxMb = Math.max(...tables.map(t => num(t.total_mb)), 0.01);
      const s = d.summary || {};
      setHtml(q(el, '#dbs-summary'), raw([
        kpi({ label: 'Tables', value: fmtNum(s.table_count) }),
        kpi({ label: 'Total rows', value: fmtNum(s.total_rows), sub: 'estimated' }),
        kpi({ label: 'Data', value: `${fmtNum(s.total_data_mb, 1)} MB` }),
        kpi({ label: 'Indexes', value: `${fmtNum(s.total_index_mb, 1)} MB` }),
        kpi({ label: 'Total', value: `${fmtNum(s.total_mb, 1)} MB`, kind: 'info' }),
      ].join('')));
      status.textContent = `Loaded ${tables.length} tables at ${new Date().toLocaleTimeString()}`;
      applyFilter();
    } catch (e) {
      if (e.name === 'AbortError') return;
      status.textContent = `Error: ${e.message}`;
      table.setError(e.message);
    }
  }

  on(q(el, '#dbs-filter'), 'input', applyFilter, ctx.signal);
  on(el, 'click', (e) => { if (e.target.closest('[data-action="refresh"]')) load(); }, ctx.signal);
  await load();
}
