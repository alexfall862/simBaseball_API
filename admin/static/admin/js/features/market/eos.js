// features/market/eos.js — end-of-season processing + service-time overview (port of legacy #section-tx-eos).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { dataTable, kvTable } from '../../ui/table.js';
import { badge, phaseBadge } from '../../ui/badge.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { refreshTimestamp, refreshSummary } from '../../main.js';
import { orgSelect, txContext, levelName, money } from './_shared.js';

const EOS_LABELS = {
  league_year: 'League year',
  service_time_credited: 'Service time credited',
  contracts_advanced: 'Contracts advanced',
  contracts_expired: 'Contracts expired',
  auto_renewed_minor: 'Auto-renewed (minor league)',
  auto_renewed_pre_arb: 'Auto-renewed (pre-arb MLB)',
  became_free_agents: 'Became free agents',
  extensions_activated: 'Extensions activated',
};

const CONTRACT_PHASE = {
  minor: ['Minor', 'success'], pre_arb: ['Pre-Arb', 'info'], arb_eligible: ['Arb', 'warning'], fa_eligible: ['FA eligible', 'danger'],
};

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card danger-zone">
      <h3>Run end of season</h3>
      <p class="text-muted small mb-2">Same one-shot End Season as Phase &amp; Week (POST /games/end-season): credits MLB service time, expires final-year contracts (extensions, auto-renewals, free agency), advances the rest, ages/progresses players, applies the offseason injury tick and switches to OFFSEASON. Refused until the World Series is complete; cannot be re-run.</p>
      <div class="alert alert-info" id="eos-info">Loading current season info…</div>
      <div class="button-group"><button class="btn btn-danger" data-action="run">Process end of season</button></div>
      <div id="eos-progress"></div>
      <div id="eos-result" class="mt-2" hidden><h4 class="mb-1">Processing summary</h4><div id="eos-kv"></div></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Service time overview</h3><p class="card-sub text-muted">GET /transactions/contract-overview/&lt;org&gt;: service years, contract phase, expiring flags.</p></div>
        <div class="row"><select id="eos-org"></select><button class="btn btn-secondary" data-action="load">Load</button></div>
      </div>
      <div id="eos-table"></div>
    </div>`);

  const progress = progressWidget(q(el, '#eos-progress'));
  const orgSel = await orgSelect(q(el, '#eos-org'), { signal: ctx.signal, onChange: (id) => { if (id) loadOverview(); } });

  const table = dataTable(q(el, '#eos-table'), {
    rowKey: 'contract_id', emptyText: 'Select an org to view.', pageSize: 100, sortKey: 'current_level', sortDir: 'desc',
    rowClass: r => (r.is_expiring ? 'row-warning' : ''),
    columns: [
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'position', title: 'Pos', render: r => r.position || '--' },
      { key: 'age', title: 'Age', sortable: true },
      { key: 'current_level', title: 'Level', sortable: true, render: r => levelName(r.current_level), sortValue: r => r.current_level },
      { key: 'mlb_service_years', title: 'Svc yrs', align: 'right', sortable: true },
      { key: 'contract_phase', title: 'Phase', html: true, sortable: true, render: r => { const p = CONTRACT_PHASE[r.contract_phase]; return p ? badge(p[0], p[1]) : badge(r.contract_phase || '--', 'secondary'); } },
      { key: 'years', title: 'Contract', render: r => `Yr ${r.current_year}/${r.years}${r.years_to_arb != null ? ` (${r.years_to_arb} to arb)` : ''}${r.years_to_fa != null ? ` (${r.years_to_fa} to FA)` : ''}` },
      { key: 'salary', title: 'Salary', align: 'right', sortable: true, render: r => money(r.salary), sortValue: r => Number(r.salary) },
      { key: 'is_expiring', title: 'Expiring', html: true, sortable: true, render: r => (r.is_expiring ? badge('Yes', 'danger') : 'No') },
    ],
  });

  async function renderInfo() {
    const c = await txContext();
    const ts = store.get().ts || {};
    setHtml(q(el, '#eos-info'), raw(`<strong>Current season:</strong> ${c.season ?? '--'} · league_year_id ${c.league_year_id} · week ${c.week} (game_week_id ${c.game_week_id}) ${phaseBadge(ts.Phase)}${ts.IsOffSeason ? ' ' + badge('offseason', 'warning') : ''}`));
  }
  store.watch('ts', () => { renderInfo().catch(() => {}); }, ctx.signal);

  async function loadOverview() {
    const orgId = orgSel.get();
    if (!orgId) { toast.warn('Select an organization'); return; }
    table.setLoading();
    try {
      const rows = await api.get(v1(`/transactions/contract-overview/${orgId}`), { signal: ctx.signal });
      table.setRows(Array.isArray(rows) ? rows : []);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }

  async function runEos() {
    const { league_year_id, season } = await txContext();
    if (!league_year_id) { toast.error('Could not determine the league year'); return; }
    if (!await confirm({
      title: `End season ${season ?? ''} (league_year_id ${league_year_id})?`, danger: true, typeToConfirm: 'END SEASON', confirmLabel: 'Process end of season',
      message: 'Runs the one-shot End Season: contract processing (service time, renewals, expirations, FA entry), player aging/progression, the offseason injury tick and the switch to OFFSEASON. It cannot be re-run.',
    })) return;
    const r = await runTracked({ el: q(el, '#eos-progress'), widget: progress, label: 'Processing end of season…', signal: ctx.signal,
      start: () => api.post(v1('/games/end-season'), { league_year_id }) });
    const eos = (r && (r.end_of_season || r.result && r.result.end_of_season)) || r || {};
    q(el, '#eos-result').hidden = false;
    setHtml(q(el, '#eos-kv'), raw(kvTable(Object.entries(EOS_LABELS).map(([k, label]) => [label, eos[k] !== undefined ? String(eos[k]) : '--']))));
    toast.success('End of season processed');
    await refreshTimestamp(); refreshSummary();
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    try {
      if (btn.dataset.action === 'run') await runEos();
      else if (btn.dataset.action === 'load') await loadOverview();
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);
}
