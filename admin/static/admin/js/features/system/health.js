// features/system/health.js — liveness/readiness probes and the route table (port of legacy #section-health).
//   GET /healthz  → {status:'ok', time}
//   GET /readyz   → {status:'ready'} | 503 {status:'degraded', error}
//   GET /routes   → text/plain "METHODS  rule  -> endpoint" per line

import { api } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q } from '../../core/html.js';
import { fmtDate, json } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';

function parseRoutes(text) {
  return String(text || '').split('\n').map(l => l.trim()).filter(Boolean).map(line => {
    const m = line.match(/^(\S+)\s+(\S+)\s+->\s+(\S+)$/);
    if (!m) return { methods: '', rule: line, endpoint: '' };
    const methods = m[1].split(',').filter(x => x !== 'HEAD' && x !== 'OPTIONS').join(',');
    return { methods, rule: m[2], endpoint: m[3] };
  });
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="grid-2">
      <div class="card">
        <div class="card-head"><h3>Liveness <span class="text-muted small">/healthz</span></h3><span id="hz-badge"></span></div>
        <pre class="result-box" id="hz-box">Checking…</pre>
      </div>
      <div class="card">
        <div class="card-head"><h3>Readiness <span class="text-muted small">/readyz</span></h3><span id="rz-badge"></span></div>
        <p class="text-muted small mb-1">Runs <code>SELECT 1</code> against the database.</p>
        <pre class="result-box" id="rz-box">Checking…</pre>
      </div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h3>Routes <span class="text-muted small">/routes</span></h3><p class="card-sub text-muted" id="rt-meta"></p></div>
        <div class="row">
          <input type="text" id="rt-filter" placeholder="filter rule / endpoint…" style="width:220px" />
          <select id="rt-method"><option value="">All methods</option><option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option></select>
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh all</button>
        </div>
      </div>
      <div id="rt-table"></div>
    </div>`);

  let routes = [];
  const table = dataTable(q(el, '#rt-table'), {
    sortKey: 'rule', compact: true, pageSize: 100, emptyText: 'No routes.',
    columns: [
      { key: 'methods', title: 'Methods', html: true, nowrap: true, render: r => r.methods.split(',').filter(Boolean).map(m => badge(m, m === 'GET' ? 'info' : m === 'DELETE' ? 'danger' : 'primary')).join(' ') },
      { key: 'rule', title: 'Rule', sortable: true, cellClass: 'mono' },
      { key: 'endpoint', title: 'Endpoint', sortable: true, cellClass: 'mono small' },
    ],
  });

  function applyFilter() {
    const f = q(el, '#rt-filter').value.trim().toLowerCase();
    const m = q(el, '#rt-method').value;
    table.setRows(routes.filter(r => (!f || r.rule.toLowerCase().includes(f) || r.endpoint.toLowerCase().includes(f)) && (!m || r.methods.split(',').includes(m))));
  }

  async function checkHealth() {
    try {
      const d = await api.get('/healthz', { quiet: true, signal: ctx.signal });
      const ok = d && d.status === 'ok';
      setHtml(q(el, '#hz-badge'), raw(badge(ok ? 'healthy' : (d && d.status) || 'unhealthy', ok ? 'success' : 'danger')));
      q(el, '#hz-box').textContent = `${json(d)}${d && d.time ? `\n\nserver time: ${fmtDate(d.time)}` : ''}`;
    } catch (e) {
      if (e.name === 'AbortError') return;
      setHtml(q(el, '#hz-badge'), raw(badge('error', 'danger')));
      q(el, '#hz-box').textContent = `Error: ${e.message}`;
    }
  }

  async function checkReady() {
    try {
      const d = await api.get('/readyz', { quiet: true, signal: ctx.signal });
      setHtml(q(el, '#rz-badge'), raw(badge(d.status || 'ready', d.status === 'ready' ? 'success' : 'warning')));
      q(el, '#rz-box').textContent = json(d);
    } catch (e) {
      if (e.name === 'AbortError') return;
      setHtml(q(el, '#rz-badge'), raw(badge(e.body && e.body.status ? e.body.status : 'error', 'danger')));
      q(el, '#rz-box').textContent = e.body ? json(e.body) : `Error: ${e.message}`;
    }
  }

  async function loadRoutes() {
    table.setLoading();
    try {
      const text = await api.get('/routes', { quiet: true, signal: ctx.signal, headers: { Accept: 'text/plain' } });
      routes = parseRoutes(typeof text === 'string' ? text : json(text));
      q(el, '#rt-meta').textContent = `${routes.length} rules registered on the Flask app.`;
      applyFilter();
    } catch (e) {
      if (e.name !== 'AbortError') table.setError(`Could not load routes: ${e.message}`);
    }
  }

  on(q(el, '#rt-filter'), 'input', applyFilter, ctx.signal);
  on(q(el, '#rt-method'), 'change', applyFilter, ctx.signal);
  delegate(el, 'click', '[data-action="refresh"]', () => { checkHealth(); checkReady(); loadRoutes(); }, ctx.signal);

  await Promise.all([checkHealth(), checkReady(), loadRoutes()]);
}
