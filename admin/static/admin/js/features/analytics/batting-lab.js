// features/analytics/batting-lab.js — synthetic tier-sweep games (port of legacy #section-batting-lab).
// Endpoints: GET /admin/batting-lab/runs, GET /admin/batting-lab/results/<id>, POST /admin/batting-lab/run (synchronous).

import { api, adm } from '../../core/api.js';
import { html, raw, esc, setHtml, delegate, q } from '../../core/html.js';
import { SIM_LEVELS, levelName } from '../../core/constants.js';
import { fmtDate } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { field, formRow, readForm } from '../../ui/form.js';
import { statusBadge } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { levelSelect } from '../../ui/selectors.js';
import { mountChart, chartCanvas, color } from '../../ui/chart.js';
import { childScope, fx, pct } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Batting lab</h3><p class="card-sub text-muted">Run synthetic games through the engine to test batting outcomes by batter attribute tier. Pitchers are held constant at average (50); only batter attributes vary. The run is synchronous and may take a minute.</p></div>
      </div>
      ${raw(formRow([
        '<div class="form-group"><label for="blab-level">League level</label><select id="blab-level" name="league_level"></select></div>',
        field.number('games_per_tier', 'Games per tier', { value: 50, min: 1, max: 500 }),
        field.text('label', 'Label (optional)', { placeholder: 'e.g. baseline v2' }),
        '<div class="form-group"><label>&nbsp;</label><button type="button" class="btn btn-primary" data-action="run">Run tier sweep</button></div>',
      ]))}
      <div id="blab-progress"></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Run history</h3><button type="button" class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button></div>
      <div id="blab-history"></div>
    </div>
    <div class="card" id="blab-results" hidden>
      <div class="card-head"><div><h3 id="blab-results-title">Results</h3><p class="card-sub" id="blab-results-info"></p></div></div>
      <div class="grid-2">
        <div><h4 class="mb-1">Slash lines by tier</h4><div id="blab-slash"></div></div>
        <div><h4 class="mb-1">Rate stats by tier</h4><div id="blab-rate"></div></div>
      </div>
      <div id="blab-table" class="mt-2"></div>
    </div>`);

  levelSelect(q(el, '#blab-level'), { levels: SIM_LEVELS, value: ctx.params.level || 9, signal: ctx.signal });
  const progress = progressWidget(q(el, '#blab-progress'));
  const resultsScope = childScope(ctx.signal);

  const history = dataTable(q(el, '#blab-history'), {
    rows: [], rowKey: 'id', compact: true, pageSize: 25, sortKey: 'id', sortDir: 'desc', emptyText: 'No runs yet. Configure and click "Run tier sweep" above.',
    columns: [
      { key: 'id', title: 'ID', sortable: true, width: '60px' },
      { key: 'label', title: 'Label', sortable: true, render: r => r.label || '-' },
      { key: 'league_level', title: 'Level', sortable: true, render: r => `${r.league_level} - ${levelName(r.league_level)}` },
      { key: 'games_per_scenario', title: 'Games/tier', align: 'right', sortable: true },
      { key: 'status', title: 'Status', html: true, sortable: true, render: r => statusBadge(r.status) },
      { key: 'created_at', title: 'Created', sortable: true, render: r => fmtDate(r.created_at) },
      { key: '_a', title: '', html: true, render: r => (r.status === 'complete' ? `<button type="button" class="btn btn-xs btn-secondary" data-action="view" data-id="${r.id}">View</button>` : '') },
    ],
  });

  async function loadHistory() {
    try {
      const d = await api.get(adm('/batting-lab/runs'), { signal: ctx.signal, quiet: true });
      history.setRows(d.runs || []);
    } catch (e) { if (e.name !== 'AbortError') history.setError(e.message); }
  }

  async function loadResults(runId) {
    const d = await api.get(adm(`/batting-lab/results/${runId}`), { signal: ctx.signal });
    const run = d.run || {}, tiers = d.tiers || [];
    const signal = resultsScope.next();
    const card = q(el, '#blab-results');
    card.hidden = false;
    q(el, '#blab-results-title').textContent = `Results: ${run.label || `Run #${run.id}`} (${levelName(run.league_level)}, ${run.games_per_scenario} games/tier)`;
    setHtml(q(el, '#blab-results-info'), raw(`${statusBadge(run.status)} ${run.completed_at ? `<span class="text-muted small">${esc(fmtDate(run.completed_at))}</span>` : ''}`));
    ctx.setParams({ run: runId });
    for (const id of ['#blab-slash', '#blab-rate']) q(el, id).innerHTML = '';
    if (!tiers.length) { setHtml(q(el, '#blab-table'), '<p class="text-muted">No tier results.</p>'); return; }
    const labels = tiers.map(t => t.tier_label);
    mountChart(chartCanvas(q(el, '#blab-slash'), { height: 260 }), {
      type: 'bar',
      data: { labels, datasets: [
        { label: 'AVG', data: tiers.map(t => t.avg || 0), backgroundColor: color(0) },
        { label: 'OBP', data: tiers.map(t => t.obp || 0), backgroundColor: color(1) },
        { label: 'SLG', data: tiers.map(t => t.slg || 0), backgroundColor: color(2) },
      ] },
      options: { scales: { y: { beginAtZero: true, max: 0.7 }, x: { grid: { display: false } } } },
    }, signal);
    mountChart(chartCanvas(q(el, '#blab-rate'), { height: 260 }), {
      type: 'bar',
      data: { labels, datasets: [
        { label: 'K%', data: tiers.map(t => t.k_pct || 0), backgroundColor: color(3) },
        { label: 'BB%', data: tiers.map(t => t.bb_pct || 0), backgroundColor: color(4) },
      ] },
      options: { scales: { y: { beginAtZero: true, ticks: { callback: v => `${v}%` } }, x: { grid: { display: false } } } },
    }, signal);
    const n = (key, title) => ({ key, title, align: 'right', sortable: true });
    dataTable(q(el, '#blab-table'), {
      rows: tiers, compact: true, rowKey: 'tier_label',
      columns: [
        { key: 'tier_label', title: 'Tier', html: true, render: r => `<strong>${esc(r.tier_label)}</strong>` },
        n('games_played', 'G'), n('plate_appearances', 'PA'), n('at_bats', 'AB'), n('hits', 'H'), n('doubles', '2B'), n('triples', '3B'), n('home_runs', 'HR'),
        { key: 'inside_the_park_hr', title: 'ITPHR', align: 'right', sortable: true, render: r => r.inside_the_park_hr || 0 },
        n('walks', 'BB'), n('strikeouts', 'K'),
        ...['avg', 'obp', 'slg', 'ops', 'iso'].map(k => ({ key: k, title: k.toUpperCase(), align: 'right', sortable: true, render: r => fx(r[k] || 0, 3) })),
        { key: 'k_pct', title: 'K%', align: 'right', sortable: true, render: r => pct(r.k_pct || 0) },
        { key: 'bb_pct', title: 'BB%', align: 'right', sortable: true, render: r => pct(r.bb_pct || 0) },
        { key: '_rpg', title: 'R/G', align: 'right', sortable: true, render: r => fx((r.runs || 0) / (r.games_played || 1), 1), sortValue: r => (r.runs || 0) / (r.games_played || 1) },
      ],
    });
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await loadHistory();
      else if (a === 'view') await loadResults(Number(btn.dataset.id));
      else if (a === 'run') {
        const f = readForm(el);
        const body = { league_level: Number(f.league_level), games_per_tier: f.games_per_tier, label: f.label || '' };
        btn.disabled = true;
        try {
          const res = await runTracked({ el: q(el, '#blab-progress'), widget: progress, label: `Running tier sweep at ${levelName(body.league_level)} (${body.games_per_tier} games/tier)…`, signal: ctx.signal,
            start: () => api.post(adm('/batting-lab/run'), body) });
          toast.success(res && res.message ? res.message : 'Tier sweep complete');
          await loadHistory();
          if (res && res.run_id) await loadResults(res.run_id);
        } finally { btn.disabled = false; }
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      // toast already shown by api layer
    }
  }, ctx.signal);

  await loadHistory();
  if (ctx.params.run) loadResults(Number(ctx.params.run)).catch(() => {});
}
