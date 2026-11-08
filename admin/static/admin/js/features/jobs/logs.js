// features/jobs/logs.js — tail of timing_log.txt and sim_failures.log.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, on, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <h3>Logs</h3>
        <div class="row">
          <select id="log-name"><option value="timing">timing_log.txt</option><option value="sim_failures">sim_failures.log</option></select>
          <select id="log-lines"><option value="200">200 lines</option><option value="400" selected>400 lines</option><option value="1000">1000 lines</option><option value="5000">5000 lines</option></select>
          <input type="text" id="log-filter" placeholder="filter…" style="width:160px" />
          <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div class="text-muted small mb-1" id="log-meta"></div>
      <div class="log-view" id="log-view">Loading…</div>
    </div>`);

  let lines = [];
  const view = q(el, '#log-view');
  function render() {
    const f = q(el, '#log-filter').value.trim().toLowerCase();
    const shown = f ? lines.filter(l => l.toLowerCase().includes(f)) : lines;
    view.textContent = shown.join('\n') || '(empty)';
    view.scrollTop = view.scrollHeight;
  }
  async function load() {
    try {
      const d = await api.get(adm('/logs'), { params: { name: q(el, '#log-name').value, lines: q(el, '#log-lines').value }, signal: ctx.signal });
      lines = d.lines || [];
      q(el, '#log-meta').textContent = d.exists ? `${d.path} · ${fmtNum(d.size)} bytes · showing last ${lines.length} lines` : `${d.path} does not exist yet`;
      render();
    } catch (e) { if (e.name !== 'AbortError') view.textContent = e.message; }
  }
  on(q(el, '#log-name'), 'change', load, ctx.signal);
  on(q(el, '#log-lines'), 'change', load, ctx.signal);
  on(q(el, '#log-filter'), 'input', render, ctx.signal);
  on(el, 'click', (e) => { if (e.target.closest('[data-action="refresh"]')) load(); }, ctx.signal);
  await load();
}
