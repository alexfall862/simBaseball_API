// features/engine/diagnostics.js — progression diagnostics from the end-season rating snapshots
// (port of legacy #section-progression-diag; endpoints /admin/analytics/progression-*).
// Sub-tabs: table-vs-actual curves · age profile · league drift · outliers · training camp · player trajectory.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q, esc } from '../../core/html.js';
import { ALL_LEVELS, levelName } from '../../core/constants.js';
import { fmtNum } from '../../core/format.js';
import { dataTable, simpleTable, kvTable } from '../../ui/table.js';
import { badge, alertBox, emptyState } from '../../ui/badge.js';
import { mountChart, color } from '../../ui/chart.js';
import { leagueYearSelect, levelSelect, fillSelect, defaultLeagueYearId } from '../../ui/selectors.js';
import { subTabs } from '../../ui/tabs.js';
import { busyButton } from '../../ui/task-runner.js';
import { fx, setStatus } from './_shared.js';

const SNAPSHOT_LEVELS = Object.freeze([...ALL_LEVELS, 2, 1]);
const TABS = [
  { id: 'curves', title: 'Table vs actual' },
  { id: 'age', title: 'Age profile' },
  { id: 'drift', title: 'League drift' },
  { id: 'outliers', title: 'Outliers' },
  { id: 'camp', title: 'Training camp' },
  { id: 'player', title: 'Player trajectory' },
];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Progression diagnostics</h3>
          <p class="card-sub text-muted">True values from the end-season rating snapshots (before and after progression). <strong>raw_ovr</strong> is the absolute weighted attribute average and is what the trends use; <strong>displayovr</strong> is a cohort percentile and cannot show a trend.</p></div>
      </div>
      <div class="row">
        <div class="form-group"><label for="pd-ly">Season (snapshots)</label><select id="pd-ly"></select></div>
        <div class="form-group"><label for="pd-level">Level</label><select id="pd-level"></select></div>
        <div class="form-group"><label for="pd-grade">Potential grade</label><select id="pd-grade"></select></div>
        <div class="form-group"><label>&nbsp;</label><button class="btn btn-primary" id="btn-load">Load</button></div>
      </div>
      <div id="pd-status"></div>
    </div>

    <div id="pd-tabs"></div>

    <div class="card pd-pane" data-pane="curves">
      <h4>Growth table vs realised deltas (selected grade, by age)</h4>
      <p class="text-muted small">A triangular(min, mode, max) draw averages (min+mode+max)/3, so the realised mean is compared with the <em>table mean</em>, not the mode. Cells are flagged when they are off by more than the tolerance.</p>
      <div class="chart-wrap" style="height:280px"><canvas id="pd-curve-chart"></canvas></div>
      <div class="mt-2" id="pd-curve-table"></div>
    </div>

    <div class="card pd-pane" data-pane="age" style="display:none">
      <h4>Age profile: mean raw_ovr by age, one line per season</h4>
      <div class="chart-wrap" style="height:280px"><canvas id="pd-age-chart"></canvas></div>
      <div class="text-muted small mt-1" id="pd-age-peaks"></div>
    </div>

    <div class="card pd-pane" data-pane="drift" style="display:none">
      <h4>League drift: mean raw_ovr per level after progression</h4>
      <p class="text-muted small">Entry quality, progression and retirement must balance; a steady +1/season drift means generation or the growth table is off.</p>
      <div class="chart-wrap" style="height:280px"><canvas id="pd-drift-chart"></canvas></div>
      <div class="mt-2" id="pd-drift-table"></div>
    </div>

    <div class="card pd-pane" data-pane="outliers" style="display:none">
      <h4>Offseason outliers (raw_ovr change vs the same age and level)</h4>
      <div class="grid-2">
        <div><h5 class="mb-1">Biggest gainers</h5><div id="pd-gainers"></div></div>
        <div><h5 class="mb-1">Biggest losers</h5><div id="pd-losers"></div></div>
      </div>
    </div>

    <div class="card pd-pane" data-pane="camp" style="display:none">
      <h4>Training camp</h4>
      <p class="text-muted small">One focus skill per player, chosen by the org; the skill's potential grade is shifted for the progression pass. From age 29 the growth table is potential-agnostic, so a focus on a 29+ player changes nothing.</p>
      <div id="pd-camp"></div>
    </div>

    <div class="card pd-pane" data-pane="player" style="display:none">
      <h4>Player trajectory</h4>
      <div class="row">
        <div class="form-group"><label for="pd-pid">Player ID</label><input type="number" id="pd-pid" min="1" style="width:140px" /></div>
        <div class="form-group"><label>&nbsp;</label><button class="btn btn-secondary" id="btn-player">Load</button></div>
      </div>
      <div class="mt-2" id="pd-player"></div>
    </div>`);

  const status = q(el, '#pd-status');
  const gradeSel = q(el, '#pd-grade');
  const levelSel = levelSelect(q(el, '#pd-level'), { levels: SNAPSHOT_LEVELS, allowAll: true, remember: 'prog-diag', signal: ctx.signal });

  // Snapshot inventory → annotate the league-year dropdown.
  let snapYears = {};
  try {
    const d = await api.get(adm('/analytics/progression-years'), { signal: ctx.signal, quiet: true });
    for (const y of d.years || []) {
      const e = snapYears[y.league_year_id] || (snapYears[y.league_year_id] = { ly: y.league_year, stages: [] });
      e.stages.push(`${String(y.stage).replace('_progression', '')} ${fmtNum(y.players)}`);
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    setHtml(status, raw(alertBox('warning', `Could not load snapshot inventory: ${e.message}`)));
  }
  const snapIds = Object.keys(snapYears).map(Number).sort((a, b) => (snapYears[b].ly - snapYears[a].ly) || (b - a));
  const globalLy = defaultLeagueYearId();
  const initialLy = snapYears[globalLy] ? globalLy : (snapIds[0] || globalLy);
  const ly = await leagueYearSelect(q(el, '#pd-ly'), {
    signal: ctx.signal, global: false, value: initialLy,
    labelFn: r => `${r.year}${snapYears[r.id] ? ` (${snapYears[r.id].stages.join(', ')})` : ' (no snapshots)'}`,
  });
  if (!snapIds.length) setHtml(status, raw(alertBox('info', 'No snapshots yet; end-season writes them.')));

  // Per-mount state.
  const data = { curves: null, age: null, drift: null, outliers: null, camp: null, player: null };
  const charts = { curves: null, age: null, drift: null };
  const panes = Object.fromEntries(TABS.map(t => [t.id, q(el, `.pd-pane[data-pane="${t.id}"]`)]));

  const tabs = subTabs(q(el, '#pd-tabs'), TABS, {
    active: ctx.params.pane && TABS.some(t => t.id === ctx.params.pane) ? ctx.params.pane : 'curves',
    signal: ctx.signal,
    onSelect: (id) => { showPane(id); ctx.setParams({ pane: id }); },
  });

  function showPane(id) {
    for (const [k, p] of Object.entries(panes)) p.style.display = k === id ? '' : 'none';
    renderPane(id);
  }

  function swapChart(key, canvas, config) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
    charts[key] = mountChart(canvas, config, ctx.signal);
  }

  function renderPane(id) {
    if (id === 'curves') renderCurve();
    else if (id === 'age') renderAge();
    else if (id === 'drift') renderDrift();
    else if (id === 'outliers') renderOutliers();
    else if (id === 'camp') renderCamp();
    else if (id === 'player') renderPlayer();
  }

  // ── Loaders ────────────────────────────────────────────────────────────
  async function loadYear() {
    const lyid = ly.get();
    if (!lyid) return;
    const level = levelSel.get();
    setStatus(status, 'Loading…');
    const get = (path, params) => api.get(adm(`/analytics/${path}`), { signal: ctx.signal, params });
    const results = await Promise.allSettled([
      get('progression-curves', { league_year_id: lyid }),
      get('progression-age-profile', { level }),
      get('progression-drift'),
      get('progression-outliers', { league_year_id: lyid, n: 15 }),
      get('progression-camp', { league_year_id: lyid }),
    ]);
    if (ctx.signal.aborted) return;
    const [curves, age, drift, outliers, camp] = results.map(r => (r.status === 'fulfilled' ? r.value : null));
    data.curves = curves; data.age = age; data.drift = drift; data.outliers = outliers; data.camp = camp;
    data.level = level;
    if (curves) {
      const prev = gradeSel.value;
      const grades = curves.grades || [];
      fillSelect(gradeSel, grades.map(g => ({ value: g, label: g })), { value: grades.includes(prev) ? prev : (grades.includes('B') ? 'B' : grades[0]) });
    }
    const failed = results.filter(r => r.status === 'rejected').length;
    const cells = curves && curves.cells ? curves.cells.length : 0;
    setStatus(status, failed ? `${failed} of 5 reports failed (see toasts).` : `Loaded ${snapYears[lyid] ? snapYears[lyid].ly : lyid}: ${cells} curve cells, level ${level ? levelName(level) : 'all'}.`, failed ? 'warning' : 'muted');
    renderPane(tabs.active);
  }

  // ── Renderers ──────────────────────────────────────────────────────────
  function renderCurve() {
    const d = data.curves;
    const table = q(el, '#pd-curve-table');
    if (!d) { setHtml(table, raw(emptyState('Load a season to see the curves.'))); return; }
    const grade = gradeSel.value;
    const cells = (d.cells || []).filter(c => c.grade === grade).sort((a, b) => a.age - b.age);
    swapChart('curves', q(el, '#pd-curve-chart'), {
      type: 'line',
      data: {
        labels: cells.map(c => c.age),
        datasets: [
          { label: 'Table mode', data: cells.map(c => c.table_mode), borderColor: '#f1c40f', backgroundColor: '#f1c40f', borderDash: [6, 3], borderWidth: 1, pointRadius: 0 },
          { label: 'Table mean (expected)', data: cells.map(c => c.table_mean), borderColor: '#f39c12', backgroundColor: '#f39c12', borderWidth: 2, pointRadius: 0 },
          { label: 'Table min', data: cells.map(c => c.table_min), borderColor: '#7f8c8d', backgroundColor: '#7f8c8d', borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
          { label: 'Table max', data: cells.map(c => c.table_max), borderColor: '#7f8c8d', backgroundColor: '#7f8c8d', borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
          { label: 'Realised mean', data: cells.map(c => c.mean_delta), borderColor: '#3498db', backgroundColor: '#3498db', borderWidth: 2, pointRadius: 2 },
          { label: 'Realised p10', data: cells.map(c => c.p10), borderColor: 'rgba(52,152,219,0.4)', backgroundColor: 'rgba(52,152,219,0.4)', borderWidth: 1, pointRadius: 0 },
          { label: 'Realised p90', data: cells.map(c => c.p90), borderColor: 'rgba(52,152,219,0.4)', borderWidth: 1, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(52,152,219,0.12)' },
        ],
      },
      options: {
        animation: { duration: 0 },
        scales: { x: { title: { display: true, text: 'Age after progression' } }, y: { title: { display: true, text: 'Yearly delta' } } },
      },
    });
    setHtml(table, raw(simpleTable([
      { title: 'Age', key: 'age' }, { title: 'n', key: 'n' },
      { title: 'Table mode', key: 'table_mode' }, { title: 'Table mean', key: 'table_mean' }, { title: 'Realised mean', key: 'mean_delta' },
      { title: 'Off by', html: true, render: c => (c.flag ? `<span class="text-danger">${esc(fx(c.off_by))}</span>` : esc(fx(c.off_by))) },
      { title: 'p10', key: 'p10' }, { title: 'p50', key: 'p50' }, { title: 'p90', key: 'p90' },
    ], cells)));
  }

  function renderAge() {
    const d = data.age;
    const peaks = q(el, '#pd-age-peaks');
    if (!d) { peaks.textContent = 'Load a season to see the age profile.'; return; }
    const years = Object.keys(d.series || {}).sort();
    const ages = [...new Set(years.flatMap(y => d.series[y].map(p => p.age)))].sort((a, b) => a - b);
    swapChart('age', q(el, '#pd-age-chart'), {
      type: 'line',
      data: {
        labels: ages,
        datasets: years.map((y, i) => {
          const byAge = Object.fromEntries(d.series[y].map(p => [p.age, p.mean_raw]));
          return { label: String(y), data: ages.map(a => byAge[a] ?? null), borderColor: color(i), backgroundColor: color(i, 0.2), borderWidth: 2, pointRadius: 2, spanGaps: true };
        }),
      },
      options: { animation: { duration: 0 }, scales: { x: { title: { display: true, text: 'Age' } }, y: { title: { display: true, text: 'Mean raw_ovr' } } } },
    });
    const peakTxt = Object.entries(d.peak_age || {}).map(([y, a]) => `${y}: peak age ${a}`).join(' · ');
    peaks.textContent = peakTxt || (years.length ? '' : 'No snapshot series for this level.');
  }

  function renderDrift() {
    const d = data.drift;
    const table = q(el, '#pd-drift-table');
    if (!d) { setHtml(table, raw(emptyState('Load a season to see the drift.'))); return; }
    const level = data.level;
    const rows = (d.rows || []).filter(r => r.stage === 'post_progression' && (!level || String(r.level) === String(level)));
    const years = [...new Set(rows.map(r => r.league_year))].sort();
    const levels = [...new Set(rows.map(r => r.level))].sort((a, b) => (a ?? 0) - (b ?? 0));
    swapChart('drift', q(el, '#pd-drift-chart'), {
      type: 'line',
      data: {
        labels: years,
        datasets: levels.map((lvl, i) => ({
          label: lvl == null ? 'No contract' : `${lvl} - ${levelName(lvl)}`,
          data: years.map(y => (rows.find(r => r.level === lvl && r.league_year === y) || {}).mean ?? null),
          borderColor: color(i), backgroundColor: color(i, 0.2), borderWidth: 2, pointRadius: 3, spanGaps: true,
        })),
      },
      options: { animation: { duration: 0 }, scales: { y: { title: { display: true, text: 'Mean raw_ovr (post)' } } } },
    });
    const cols = [{ title: 'Level', html: true, render: r => (r.level == null ? '<span class="text-muted">No contract</span>' : `${r.level} - ${esc(levelName(r.level))}`) },
      ...years.map(y => ({ title: String(y), render: r => fx(r[y], 1) }))];
    const tableRows = levels.map(lvl => {
      const o = { level: lvl };
      for (const y of years) o[y] = (rows.find(r => r.level === lvl && r.league_year === y) || {}).mean;
      return o;
    });
    setHtml(table, raw(simpleTable(cols, tableRows)));
  }

  function outlierTable(container) {
    return dataTable(container, {
      rowKey: 'player_id', emptyText: 'Load a season.', compact: true,
      columns: [
        { key: 'name', title: 'Player', html: true, render: x => `<a href="#" data-action="pick-player" data-pid="${esc(x.player_id)}">${esc(x.name)}</a>` },
        { key: 'age', title: 'Age', align: 'right' },
        { key: 'level', title: 'Lvl', render: x => (x.level ?? '-') },
        { key: 'org', title: 'Org', render: x => (x.org ?? '-') },
        { key: 'raw_pre', title: 'raw pre', align: 'right', render: x => fx(x.raw_pre, 1) },
        { key: 'raw_post', title: 'raw post', align: 'right', render: x => fx(x.raw_post, 1) },
        { key: 'delta', title: 'Δ', align: 'right', sortable: true, html: true, render: x => `<strong class="${x.delta > 0 ? 'text-success' : x.delta < 0 ? 'text-danger' : ''}">${esc(fx(x.delta, 1))}</strong>` },
        { key: 'cohort_mean', title: 'cohort Δ', align: 'right', render: x => fx(x.cohort_mean, 1) },
        { key: 'z', title: 'z', align: 'right', sortable: true, render: x => fx(x.z, 2) },
        { key: 'camp', title: 'Camp', render: x => (x.camp ? `${x.camp.attr} / ${x.camp.intensity}${x.camp.backfired ? ' (backfired)' : ''}` : '') },
      ],
      rows: [],
    });
  }
  const gainersTable = outlierTable(q(el, '#pd-gainers'));
  const losersTable = outlierTable(q(el, '#pd-losers'));

  function renderOutliers() {
    const d = data.outliers;
    if (!d) return;
    gainersTable.setRows(d.gainers || []);
    losersTable.setRows(d.losers || []);
  }

  function renderCamp() {
    const d = data.camp;
    const box = q(el, '#pd-camp');
    if (!d) { setHtml(box, raw(emptyState('Load a season to see camp results.'))); return; }
    const s = d.summary || {}, e = d.effects || {};
    const effectRows = Object.entries(e.by_intensity || {}).map(([k, v]) => ({
      outcome: k,
      n: v.focus && v.focus.n, focus: v.focus && v.focus.mean, focus_vs_mode: v.focus_vs_mode && v.focus_vs_mode.mean,
      other: v.other && v.other.mean, other_vs_mode: v.other_vs_mode && v.other_vs_mode.mean,
    }));
    setHtml(box, html`
      <div class="grid-2 mb-2">
        ${raw(kvTable([
          ['Focus set but not yet applied', fmtNum(s.pending_focus ?? 0)],
          ['Players with a camp result this season', fmtNum(e.players ?? 0)],
        ]))}
        <div></div>
      </div>
      <h5 class="mb-1">By intensity</h5>
      ${raw(simpleTable([
        { title: 'Intensity', key: 'intensity' }, { title: 'Players', key: 'players' }, { title: 'Backfired', key: 'backfired' },
        { title: 'Mean steps', render: r => fx(r.mean_steps, 2) },
      ], s.by_intensity || []))}
      <h5 class="mb-1 mt-2">Effect: mean yearly delta of the focus skill vs the same players' other attributes</h5>
      ${raw(simpleTable([
        { title: 'Outcome', key: 'outcome' }, { title: 'n focus attrs', key: 'n' },
        { title: 'Focus Δ', render: r => fx(r.focus) }, { title: 'Focus Δ − table mode', render: r => fx(r.focus_vs_mode) },
        { title: 'Other Δ', render: r => fx(r.other) }, { title: 'Other Δ − table mode', render: r => fx(r.other_vs_mode) },
      ], effectRows))}
      <h5 class="mb-1 mt-2">Skills chosen</h5>
      ${raw(simpleTable([
        { title: 'Skill', render: r => r.label || r.attr }, { title: 'Players', key: 'players' }, { title: 'Backfired', key: 'backfired' },
      ], s.by_attr || []))}`);
  }

  function renderPlayer() {
    const d = data.player;
    const box = q(el, '#pd-player');
    if (!d) { setHtml(box, raw(emptyState('Enter a player ID (or click a name in Outliers).'))); return; }
    const p = d.player || {};
    const seasons = d.seasons || [];
    let out = html`<div class="row mb-2"><strong>${p.name}</strong> ${raw(badge(p.ptype || '?', p.ptype === 'Pitcher' ? 'info' : 'success'))} <span class="text-muted">age ${p.age} · displayovr ${p.displayovr ?? '-'} · id ${p.id ?? ''}</span>
      <a class="btn btn-xs btn-ghost" href="#/data/players?player_id=${p.id ?? ''}">Open in Players</a></div>`.toString();
    if (!seasons.length) { setHtml(box, raw(out + emptyState('No snapshots for this player.'))); return; }
    const delta = s => ((s.pre && s.post && s.pre.raw_ovr != null && s.post.raw_ovr != null) ? (s.post.raw_ovr - s.pre.raw_ovr).toFixed(2) : '-');
    out += simpleTable([
      { title: 'Season', key: 'league_year' },
      { title: 'Age', render: s => (s.post && s.post.age) ?? (s.pre && s.pre.age) ?? '-' },
      { title: 'Level', render: s => (s.post && s.post.level) ?? (s.pre && s.pre.level) ?? '-' },
      { title: 'Org', render: s => (s.post && s.post.org) ?? (s.pre && s.pre.org) ?? '-' },
      { title: 'raw pre', render: s => (s.pre && s.pre.raw_ovr) ?? '-' },
      { title: 'raw post', render: s => (s.post && s.post.raw_ovr) ?? '-' },
      { title: 'Δ', render: delta },
      { title: 'Camp', render: s => (s.camp ? `${s.camp.attr} / ${s.camp.intensity} ${s.camp.base_grade}→${s.camp.effective_grade}${s.camp.backfired ? ' (backfired)' : ''}` : '') },
    ], seasons);
    const last = [...seasons].reverse().find(s => s.attributes && s.attributes.length);
    if (last) {
      out += `<h5 class="mb-1 mt-2">Attributes, ${esc(last.league_year)} offseason (band = growth table for the grade at that age)</h5>`;
      out += simpleTable([
        { title: 'Attribute', key: 'attr' },
        { title: 'Grade', render: a => a.grade ?? '-' },
        { title: 'Pre', render: a => a.pre ?? '-' },
        { title: 'Post', render: a => a.post ?? '-' },
        { title: 'Δ', html: true, render: a => (a.outside_band ? `<span class="text-danger">${esc(a.delta)}</span>` : esc(a.delta ?? '-')) },
        { title: 'Band min / mode / max', render: a => (a.band ? `${a.band.min} / ${a.band.mode} / ${a.band.max}` : '-') },
      ], last.attributes);
    }
    setHtml(box, raw(out));
  }

  async function loadPlayer(pid) {
    const box = q(el, '#pd-player');
    if (!pid) { data.player = null; renderPlayer(); return; }
    setHtml(box, '<span class="spinner spinner-sm"></span> Loading…');
    try {
      data.player = await api.get(adm(`/analytics/progression-player/${pid}`), { signal: ctx.signal });
      ctx.setParams({ player_id: pid });
      renderPlayer();
    } catch (e) {
      if (e.name === 'AbortError') return;
      setHtml(box, raw(alertBox('danger', e.message)));
    }
  }

  // ── Wiring ─────────────────────────────────────────────────────────────
  on(gradeSel, 'change', renderCurve, ctx.signal);
  busyButton(q(el, '#btn-load'), loadYear);
  busyButton(q(el, '#btn-player'), () => loadPlayer(Number(q(el, '#pd-pid').value) || null));
  on(q(el, '#pd-pid'), 'keydown', (e) => { if (e.key === 'Enter') loadPlayer(Number(e.target.value) || null); }, ctx.signal);
  delegate(el, 'click', '[data-action="pick-player"]', (e, a) => {
    e.preventDefault();
    q(el, '#pd-pid').value = a.dataset.pid;
    tabs.set('player');
    loadPlayer(Number(a.dataset.pid));
  }, ctx.signal);

  showPane(tabs.active);
  if (ctx.params.player_id) { q(el, '#pd-pid').value = ctx.params.player_id; loadPlayer(Number(ctx.params.player_id)); }
  if (snapIds.length && ly.get()) await loadYear().catch(() => {});
}
