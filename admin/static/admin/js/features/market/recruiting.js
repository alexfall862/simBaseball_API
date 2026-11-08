// features/market/recruiting.js — college recruiting: state/week controls, rankings, admin reports,
// scoped wipes and resets (merges legacy #section-recruiting + #section-recruiting-admin).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable, simpleTable } from '../../ui/table.js';
import { badge, kpi } from '../../ui/badge.js';
import { field, readForm } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { leagueYearSelect } from '../../ui/selectors.js';
import { mountChart, chartCanvas, color } from '../../ui/chart.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { stars, setStatus, windowStatusBadge } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>College recruiting</h3><p class="card-sub text-muted">Weeks advance manually (POST /recruiting/advance-week). Week 0 → 1 computes star rankings and opens the period; week 20 closes it. See docs/recruiting_admin_frontend_guide.md.</p></div>
        <div class="row">
          <select id="rec-ly"></select>
          <button class="btn btn-primary" data-action="advance">Advance week</button>
          <button class="btn btn-secondary" data-action="regenerate">Regenerate stars</button>
          <button class="btn btn-danger" data-action="wipe-stars">Wipe stars</button>
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div id="rec-status"></div>
      <div id="rec-progress"></div>
    </div>

    <div class="card" id="rec-state-card" hidden>
      <h3>Recruiting state</h3>
      <div class="row mb-2" id="rec-state-info"></div>
      <div class="grid-auto" id="rec-kpis"></div>
      <div class="grid-2">
        <div><h4 class="mb-1">Star distribution (pool / committed)</h4><div id="rec-star-chart"></div><div id="rec-star-table" class="mt-1"></div></div>
        <div><h4 class="mb-1">Recent commitments</h4><div id="rec-commitments"></div></div>
      </div>
    </div>

    <div class="card" id="rec-trend-card" hidden>
      <h3>Trends</h3>
      <div class="grid-2">
        <div><h4 class="mb-1">Weekly investment</h4><div id="rec-weekly-chart"></div></div>
        <div><h4 class="mb-1">Commitment pace</h4><div id="rec-pace-chart"></div></div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card" id="rec-leaderboard-card" hidden>
        <h3>Org leaderboard</h3>
        <p class="text-muted small mb-1">Click a row for the org drill-down.</p>
        <div id="rec-leaderboard"></div>
      </div>
      <div class="card" id="rec-demand-card" hidden>
        <div class="card-head">
          <h3>Most recruited players</h3>
          <div class="row">
            <select id="rec-demand-star"><option value="">All stars</option><option value="5">5-star</option><option value="4">4-star</option><option value="3">3-star</option><option value="2">2-star</option><option value="1">1-star</option></select>
            <input type="number" id="rec-demand-limit" value="50" min="10" max="200" title="Limit" />
          </div>
        </div>
        <div id="rec-demand"></div>
      </div>
    </div>

    <div class="card" id="rec-org-card" hidden>
      <div class="card-head"><h3 id="rec-org-title">Org detail</h3><button class="btn btn-sm btn-ghost" data-action="close-org">Close</button></div>
      <div class="grid-2">
        <div><h4 class="mb-1">Weekly spend</h4><div id="rec-org-chart"></div></div>
        <div><h4 class="mb-1">Commitments won</h4><div id="rec-org-commits"></div></div>
      </div>
      <h4 class="mb-1 mt-2">All invested players</h4>
      <div id="rec-org-players"></div>
    </div>

    <div class="card danger-zone">
      <h3>Admin controls</h3>
      <div class="grid-2">
        <div>
          <h4 class="mb-1">State &amp; week</h4>
          <div class="form-row">
            ${raw(field.number('target_week', 'Target week', { value: 1, min: 0, max: 21 }))}
            <button class="btn btn-primary" data-action="reset-week">Reset to week</button>
            <button class="btn btn-danger" data-action="full-reset">Full reset (keep rankings)</button>
          </div>
          <p class="text-muted small">Reset-to-week only rewinds the clock; investments and commitments stay. Full reset wipes investments, commitments and boards and returns to week 0.</p>
        </div>
        <div>
          <h4 class="mb-1">Scoped data wipes</h4>
          <div class="form-row">
            ${raw(field.number('wipe_org', 'Org ID (optional)', { placeholder: 'all orgs' }))}
            ${raw(field.number('wipe_player', 'Player ID (optional)', { placeholder: 'all players' }))}
          </div>
          <div class="button-group">
            <button class="btn btn-danger" data-action="wipe-investments">Wipe investments</button>
            <button class="btn btn-danger" data-action="wipe-commitments">Wipe commitments</button>
            <button class="btn btn-danger" data-action="wipe-boards">Wipe boards</button>
          </div>
          <div id="rec-wipe-status" class="mt-1"></div>
        </div>
      </div>
    </div>`);

  const statusEl = q(el, '#rec-status');
  const progress = progressWidget(q(el, '#rec-progress'));
  const ly = await leagueYearSelect(q(el, '#rec-ly'), { signal: ctx.signal, onChange: () => load() });
  const lyid = () => ly.get();
  const show = (id, on_) => { q(el, id).hidden = !on_; };

  const charts = {};
  const canvases = {
    star: chartCanvas(q(el, '#rec-star-chart'), { height: 220 }),
    weekly: chartCanvas(q(el, '#rec-weekly-chart'), { height: 260 }),
    pace: chartCanvas(q(el, '#rec-pace-chart'), { height: 260 }),
    org: chartCanvas(q(el, '#rec-org-chart'), { height: 220 }),
  };
  function chart(name, config) {
    if (charts[name]) { charts[name].update(config.data, config.options); return; }
    charts[name] = mountChart(canvases[name], config, ctx.signal);
  }

  const leaderboard = dataTable(q(el, '#rec-leaderboard'), {
    rowKey: 'org_id', emptyText: 'No investment activity yet.', compact: true, pageSize: 50, sortKey: 'total_points', sortDir: 'desc',
    onRowClick: (r) => loadOrgDetail(r.org_id),
    columns: [
      { key: 'org_abbrev', title: 'Org', sortable: true },
      { key: 'total_points', title: 'Points', align: 'right', sortable: true, render: r => fmtNum(r.total_points) },
      { key: 'players_targeted', title: 'Players', align: 'right', sortable: true },
      { key: 'weeks_active', title: 'Weeks', align: 'right', sortable: true },
      { key: 'budget_utilization_pct', title: 'Util %', align: 'right', sortable: true, render: r => `${r.budget_utilization_pct}%` },
      { key: 'commitments', title: 'Commits', align: 'right', sortable: true },
      { key: 'elite_commitments', title: 'Elite', align: 'right', sortable: true },
      { key: 'avg_commit_star', title: 'Avg ★', align: 'right', sortable: true },
    ],
  });
  const demand = dataTable(q(el, '#rec-demand'), {
    rowKey: 'player_id', emptyText: 'No investment activity yet.', compact: true, pageSize: 50,
    columns: [
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'ptype', title: 'Type', sortable: true },
      { key: 'star_rating', title: '★', sortable: true, render: r => r.star_rating ?? '-' },
      { key: 'rank_overall', title: 'Rank', align: 'right', sortable: true, render: r => r.rank_overall ?? '-' },
      { key: 'num_orgs', title: 'Orgs', align: 'right', sortable: true },
      { key: 'total_interest', title: 'Interest', align: 'right', sortable: true, render: r => fmtNum(r.total_interest) },
      { key: 'last_active_week', title: 'Last wk', align: 'right', sortable: true },
      { key: 'status', title: 'Status', html: true, sortable: true, render: r => (r.status === 'committed' ? badge((r.committed_to && r.committed_to.org_abbrev) || 'committed', 'success') : badge('open', 'warning')) },
    ],
  });
  const commitsTable = dataTable(q(el, '#rec-commitments'), {
    emptyText: 'No commitments yet.', compact: true,
    columns: [
      { key: 'week_committed', title: 'Week' },
      { key: 'player_name', title: 'Player' },
      { key: 'ptype', title: 'Type' },
      { key: 'star_rating', title: 'Stars', render: r => stars(r.star_rating) },
      { key: 'org_abbrev', title: 'School' },
      { key: 'points_total', title: 'Points', align: 'right' },
    ],
  });

  // ------------------------------------------------------------ loaders
  async function load() {
    const id = lyid();
    if (!id) return;
    ctx.setParams({ ly: id });
    const p = { league_year_id: id };
    const [stateR, summaryR, commitsR] = await Promise.allSettled([
      api.get(v1('/recruiting/state'), { params: p, signal: ctx.signal, quiet: true }),
      api.get(v1('/recruiting/admin/report/summary'), { params: p, signal: ctx.signal, quiet: true }),
      api.get(v1('/recruiting/commitments'), { params: { ...p, per_page: 20 }, signal: ctx.signal, quiet: true }),
    ]);
    if (stateR.status === 'rejected' && summaryR.status === 'rejected') {
      if (stateR.reason && stateR.reason.name === 'AbortError') return;
      setStatus(statusEl, (summaryR.reason && summaryR.reason.message) || 'Could not load recruiting state', 'danger');
      return;
    }
    const st = stateR.status === 'fulfilled' ? stateR.value : {};
    const s = summaryR.status === 'fulfilled' ? summaryR.value : null;
    const status = (s && s.status) || st.status || 'pending';
    const week = (s && s.current_week) ?? st.current_week ?? 0;
    const total = st.total_weeks || (s && s.total_weeks) || 20;
    show('#rec-state-card', true);
    setHtml(q(el, '#rec-state-info'), raw(`${windowStatusBadge(status)} <span>Week <strong>${esc(week)}</strong> / ${esc(total)}</span>`
      + (s ? ` <span class="text-muted">· pool ${fmtNum(s.pool_size)} · committed ${fmtNum(s.committed_count)} · remaining ${fmtNum(s.uncommitted_count)}</span>` : '')));
    q(el, '[name="target_week"]').value = Math.max(1, Number(week) || 1);

    if (s) {
      setHtml(q(el, '#rec-kpis'), raw([
        kpi({ label: 'Active orgs', value: fmtNum(s.active_orgs) }),
        kpi({ label: 'Players targeted', value: fmtNum(s.targeted_players) }),
        kpi({ label: 'Total points', value: fmtNum(s.total_points_invested) }),
        kpi({ label: 'Allocations', value: fmtNum(s.total_allocations) }),
        kpi({ label: 'Commitments', value: fmtNum(s.committed_count), sub: s.pool_size ? `${(s.committed_count / s.pool_size * 100).toFixed(1)}% of pool` : '' }),
        kpi({ label: 'Orgs committing', value: fmtNum(s.unique_orgs_committing) }),
        kpi({ label: 'Avg winning points', value: s.avg_winning_points ?? '--' }),
      ].join('')));
      const dist = s.star_distribution || {}, cbs = s.committed_by_star || {};
      const labels = [5, 4, 3, 2, 1];
      chart('star', { type: 'bar', data: { labels: labels.map(n => `${n}★`), datasets: [
        { label: 'Pool', data: labels.map(n => Number(dist[n] || 0)), backgroundColor: color(0, 0.7) },
        { label: 'Committed', data: labels.map(n => Number(cbs[n] || 0)), backgroundColor: color(1, 0.7) },
      ] }, options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      setHtml(q(el, '#rec-star-table'), raw(simpleTable(['Stars', 'Pool', 'Committed', '%'], labels.map(n => {
        const pool = Number(dist[n] || 0), comm = Number(cbs[n] || 0);
        return [stars(n), fmtNum(pool), fmtNum(comm), pool ? `${Math.round(comm / pool * 100)}%` : '0%'];
      }))));
      const weeks = s.weekly_trend || [], pace = s.commitment_pace || [];
      show('#rec-trend-card', weeks.length > 0 || pace.length > 0);
      if (weeks.length) {
        chart('weekly', { type: 'bar', data: { labels: weeks.map(w => `Wk ${w.week}`), datasets: [
          { label: 'Points spent', data: weeks.map(w => w.points_spent), backgroundColor: color(0, 0.7) },
          { label: 'Active orgs', data: weeks.map(w => w.active_orgs), type: 'line', borderColor: color(2), backgroundColor: color(2, 0.2), yAxisID: 'y1' },
        ] }, options: { scales: { y: { beginAtZero: true, title: { display: true, text: 'Points' } }, y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, title: { display: true, text: 'Orgs' } } } } });
      }
      if (pace.length) {
        let cum = 0;
        chart('pace', { type: 'bar', data: { labels: pace.map(w => `Wk ${w.week}`), datasets: [
          { label: 'Per week', data: pace.map(w => w.commitments), backgroundColor: color(1, 0.6) },
          { label: 'Cumulative', data: pace.map(w => { cum += w.commitments; return cum; }), type: 'line', borderColor: color(3), backgroundColor: color(3, 0.2) },
        ] }, options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
      }
      show('#rec-leaderboard-card', true);
      show('#rec-demand-card', true);
      loadLeaderboard(); loadDemand();
    } else {
      setHtml(q(el, '#rec-kpis'), '');
      show('#rec-trend-card', false); show('#rec-leaderboard-card', false); show('#rec-demand-card', false);
    }
    const c = commitsR.status === 'fulfilled' ? (commitsR.value.commitments || []) : [];
    commitsTable.setRows(c);
  }

  async function loadLeaderboard() {
    leaderboard.setLoading();
    try {
      const d = await api.get(v1('/recruiting/admin/report/org-leaderboard'), { params: { league_year_id: lyid() }, signal: ctx.signal, quiet: true });
      leaderboard.setRows(d.orgs || []);
    } catch (e) { if (e.name !== 'AbortError') leaderboard.setError(e.message); }
  }
  async function loadDemand() {
    demand.setLoading();
    try {
      const d = await api.get(v1('/recruiting/admin/report/player-demand'), { params: { league_year_id: lyid(), limit: q(el, '#rec-demand-limit').value || 50, star_rating: q(el, '#rec-demand-star').value }, signal: ctx.signal, quiet: true });
      demand.setRows(d.players || []);
    } catch (e) { if (e.name !== 'AbortError') demand.setError(e.message); }
  }
  async function loadOrgDetail(orgId) {
    const d = await api.get(v1(`/recruiting/admin/report/org-detail/${orgId}`), { params: { league_year_id: lyid() }, signal: ctx.signal });
    const card = q(el, '#rec-org-card');
    card.hidden = false;
    q(el, '#rec-org-title').textContent = `${d.org_abbrev} (org ${d.org_id}) — total ${fmtNum(d.total_invested)} pts`;
    const ws = d.weekly_spend || [];
    chart('org', { type: 'bar', data: { labels: ws.map(w => `Wk ${w.week}`), datasets: [{ label: 'Points', data: ws.map(w => w.points_spent), backgroundColor: color(0, 0.7) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, max: 100 } } } });
    setHtml(q(el, '#rec-org-commits'), raw(simpleTable(['Player', '★', 'Week', 'Points'], (d.commitments_won || []).map(c => [c.player_name, c.star_rating, c.week_committed, c.points_total]))));
    setHtml(q(el, '#rec-org-players'), raw(simpleTable([
      { key: 'player_name', title: 'Player' }, { key: 'ptype', title: 'Type' },
      { key: 'star_rating', title: '★', render: p => p.star_rating ?? '-' }, { key: 'total_invested', title: 'Invested' },
      { key: 'outcome', title: 'Outcome', html: true, render: p => (p.outcome === 'won' ? badge('Won', 'success') : p.outcome === 'lost' ? badge(`Lost → ${p.committed_to || '?'}`, 'danger') : badge('Active', 'warning')) },
    ], d.invested_players || [])));
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ------------------------------------------------------------ actions
  async function post(url, body, label, onDone) {
    await runTracked({ el: q(el, '#rec-progress'), widget: progress, label, signal: ctx.signal,
      start: () => api.post(v1(url), { league_year_id: lyid(), ...body }),
      onDone: (d) => { const msg = onDone(d); setStatus(statusEl, msg, 'success'); toast.success(msg); } });
    await load();
  }
  function wipeScope() {
    const f = readForm(q(el, '.danger-zone'));
    const body = {};
    if (f.wipe_org) body.org_id = f.wipe_org;
    if (f.wipe_player) body.player_id = f.wipe_player;
    const scope = [f.wipe_org ? `org ${f.wipe_org}` : null, f.wipe_player ? `player ${f.wipe_player}` : null].filter(Boolean).join(', ') || 'ALL orgs and players';
    return { body, scope };
  }
  async function wipe(endpoint, what) {
    const { body, scope } = wipeScope();
    if (!await confirm({ title: `Wipe ${what}?`, danger: true, typeToConfirm: 'WIPE', confirmLabel: 'Wipe',
      message: `Scope: ${scope}, league year ${lyid()}. Deleted rows cannot be recovered.` })) return;
    const d = await api.post(v1(`/recruiting/admin/${endpoint}`), { league_year_id: lyid(), ...body });
    setStatus(q(el, '#rec-wipe-status'), `${what} wiped: ${fmtNum(d.deleted)} rows (scope: ${d.scope || scope})`, 'success');
    toast.success(`${what} wiped (${fmtNum(d.deleted)} rows)`);
    await load();
  }

  on(q(el, '#rec-demand-star'), 'change', loadDemand, ctx.signal);
  on(q(el, '#rec-demand-limit'), 'change', loadDemand, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await load();
      else if (a === 'close-org') q(el, '#rec-org-card').hidden = true;
      else if (a === 'advance') {
        if (!await confirm({ title: 'Advance recruiting one week?', confirmLabel: 'Advance', message: 'Resolves this week\'s commitments. At week 0 this computes star rankings and opens the period; at the final week it closes recruiting.' })) return;
        await post('/recruiting/advance-week', {}, 'Advancing recruiting week…', (d) => {
          if (d.ranked_players) return `Ranked ${fmtNum(d.ranked_players)} players. Status: ${d.status}`;
          const commits = (d.commitments || []).length + (d.cleanup_commitments || []).length;
          let msg = `Advanced to week ${d.new_week}. Status: ${d.status}.`;
          if (commits) msg += ` ${commits} new commitments.`;
          if (d.uncommitted_count !== undefined) msg += ` ${fmtNum(d.uncommitted_count)} uncommitted.`;
          if (d.leftovers !== undefined) msg += ` ${d.leftovers} leftovers.`;
          return msg;
        });
      } else if (a === 'regenerate') {
        if (!await confirm({ title: 'Regenerate star rankings?', confirmLabel: 'Regenerate', message: 'Wipes and recomputes star rankings for this league year from current ratings.' })) return;
        await post('/recruiting/rankings/regenerate', {}, 'Regenerating star rankings…', (d) => `Regenerated stars for ${fmtNum(d.ranked_players)} players.`);
      } else if (a === 'wipe-stars') {
        if (!await confirm({ title: 'Wipe all star rankings?', danger: true, typeToConfirm: 'WIPE', confirmLabel: 'Wipe', message: `Deletes every star ranking for league year ${lyid()}. Cannot be undone.` })) return;
        await post('/recruiting/rankings/wipe', {}, 'Wiping star rankings…', (d) => `Wiped ${fmtNum(d.deleted)} star rankings.`);
      } else if (a === 'reset-week') {
        const week = Number(readForm(q(el, '.danger-zone')).target_week) || 1;
        if (!await confirm({ title: `Reset recruiting to week ${week}?`, confirmLabel: 'Reset', message: 'Rewinds the clock only; investments and commitments are NOT wiped.' })) return;
        await post('/recruiting/admin/reset-week', { target_week: week }, `Resetting to week ${week}…`, (d) => `Reset to week ${d.current_week} (${d.status})`);
      } else if (a === 'full-reset') {
        if (!await confirm({ title: 'Full recruiting reset?', danger: true, typeToConfirm: 'RESET', confirmLabel: 'Full reset',
          message: `Wipes all investments, commitments and boards for league year ${lyid()} and returns to week 0. Star rankings are preserved.` })) return;
        await post('/recruiting/admin/full-reset', {}, 'Resetting recruiting…', (d) => {
          const parts = Object.entries(d.deleted || {}).filter(([k]) => k !== 'state_reset').map(([k, v]) => `${k}: ${v}`);
          return `Full reset complete. ${parts.join(', ')}`;
        });
      } else if (a === 'wipe-investments') await wipe('wipe-investments', 'Investments');
      else if (a === 'wipe-commitments') await wipe('wipe-commitments', 'Commitments');
      else if (a === 'wipe-boards') await wipe('wipe-boards', 'Boards');
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      setStatus(statusEl, err.message, 'danger');
    }
  }, ctx.signal);

  if (ctx.params.ly && ly.rows.some(r => String(r.id) === String(ctx.params.ly))) ly.set(Number(ctx.params.ly));
  else await load();
}
