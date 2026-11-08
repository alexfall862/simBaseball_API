// features/market/fa-market.js — contract market dashboard: $/WAR, WAR tiers, recent signings
// (port of legacy #section-fa-market).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { kpi, badge } from '../../ui/badge.js';
import { mountChart, chartCanvas } from '../../ui/chart.js';
import { txContext, money } from './_shared.js';

const TIERS = ['0-1', '1-2', '2-3', '3-4', '4+'];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Contract market dashboard</h3><p class="card-sub text-muted">GET /fa-auction/market-summary — market $/WAR and the 3-year signing window that prices free-agent demands.</p></div>
        <div class="row"><span class="text-muted small" id="mk-ctx"></span><button class="btn btn-sm btn-secondary" data-action="load">Refresh</button></div>
      </div>
      <div class="grid-4" id="mk-cards"></div>
    </div>
    <div class="grid-2">
      <div class="card"><h3>WAR tier distribution</h3><div id="mk-chart"></div></div>
      <div class="card"><h3>Recent signings</h3><div id="mk-recent"></div></div>
    </div>`);

  const canvas = chartCanvas(q(el, '#mk-chart'), { height: 260 });
  let chart = null;
  const recent = dataTable(q(el, '#mk-recent'), {
    rowKey: 'player_id', emptyText: 'No signings yet.', pageSize: 25, compact: true, sortKey: 'aav', sortDir: 'desc',
    columns: [
      { key: 'name', title: 'Player', sortable: true },
      { key: 'age', title: 'Age', sortable: true },
      { key: 'war', title: 'WAR', align: 'right', sortable: true, render: r => fmtNum(r.war, 1) },
      { key: 'years', title: 'Yrs', align: 'right', sortable: true },
      { key: 'aav', title: 'AAV', align: 'right', sortable: true, render: r => money(r.aav), sortValue: r => Number(r.aav) },
      { key: 'total_value', title: 'Total', align: 'right', sortable: true, render: r => money(r.total_value), sortValue: r => Number(r.total_value) },
      { key: 'source', title: 'Source', html: true, sortable: true, render: r => badge(r.source || '--', r.source === 'fa_auction' ? 'info' : 'secondary') },
    ],
  });

  async function load() {
    const c = await txContext();
    q(el, '#mk-ctx').textContent = `League year ID ${c.league_year_id}`;
    recent.setLoading();
    let d;
    try {
      d = await api.get(v1('/fa-auction/market-summary'), { signal: ctx.signal, params: { league_year_id: c.league_year_id } });
    } catch (e) { if (e.name !== 'AbortError') recent.setError(e.message); return; }
    setHtml(q(el, '#mk-cards'), raw([
      kpi({ label: 'Current $/WAR', value: money(d.dollar_per_war), sub: d.start_year && d.end_year ? `window ${d.start_year}–${d.end_year}` : '' }),
      kpi({ label: 'Signings (3yr window)', value: fmtNum(d.total_signings || d.signings || 0) }),
      kpi({ label: 'Avg contract length', value: d.avg_years != null ? `${d.avg_years}y` : '--' }),
      kpi({ label: 'Avg AAV', value: money(d.avg_aav), sub: d.avg_total_value != null ? `avg total ${money(d.avg_total_value)}` : '' }),
    ].join('')));
    recent.setRows(d.recent_signings || []);
    const tiers = d.war_tiers || {};
    const data = { labels: TIERS.map(t => `${t} WAR`), datasets: [{ label: 'Signings', data: TIERS.map(t => Number(tiers[t] || 0)) }] };
    if (chart) chart.update(data);
    else chart = mountChart(canvas, { type: 'bar', data, options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } }, ctx.signal);
  }

  delegate(el, 'click', '[data-action="load"]', () => load().catch(() => {}), ctx.signal);
  await load();
}
