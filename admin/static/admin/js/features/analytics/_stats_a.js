// features/analytics/_stats_a.js — Stats reports, group A:
// batting/pitching/defense correlations (heatmap + scatter drill), WAR leaderboard,
// multi-regression, sensitivity curves, xStats residuals, interaction effects.

import { api, adm } from '../../core/api.js';
import { esc, setHtml, delegate, on, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { field, card } from '../../ui/form.js';
import { badge } from '../../ui/badge.js';
import { fillSelect } from '../../ui/selectors.js';
import { mountChart, chartCanvas, color } from '../../ui/chart.js';
import { fx, signed, signedClass, heatColor, seqColor, heatCell, kpiRow, rawTable, notEnough, rangeField } from './_shared.js';

// ---------------------------------------------------------------------------
// Stat / attribute option lists (analytics-specific; these are not the level or position maps)
// ---------------------------------------------------------------------------

export const BATTING_STATS = [
  ['AVG', 'AVG'], ['ISO', 'ISO'], ['BB_pct', 'BB%'], ['K_pct', 'K%'], ['OBP', 'OBP'], ['SLG', 'SLG'], ['OPS', 'OPS'],
  ['SB_pct', 'SB%'], ['AB_per_HR', 'AB/HR'], ['BABIP', 'BABIP'], ['XBH_pct', 'XBH%'], ['BB_K', 'BB/K'], ['wOBA', 'wOBA'],
  ['RC', 'RC'], ['SecA', 'SecA'], ['PSS', 'PSS'], ['GB_pct', 'GB%'], ['FB_pct', 'FB%'], ['PU_pct', 'PU%'],
  ['Barrel_pct', 'Barrel%'], ['HardHit_pct', 'HardHit%'], ['Soft_pct', 'Soft%'], ['Med_pct', 'Med%'], ['LD_pct', 'LD%'],
  ['Contact_pct', 'Contact%'], ['GIDP_pct', 'GIDP%'], ['HR_FB', 'HR/FB'],
].map(([value, label]) => ({ value, label }));

export const PITCHING_STATS = [
  ['ERA', 'ERA'], ['WHIP', 'WHIP'], ['K_per_9', 'K/9'], ['BB_per_9', 'BB/9'], ['HR_per_9', 'HR/9'], ['K_per_BB', 'K/BB'],
  ['H_per_9', 'H/9'], ['IP_per_GS', 'IP/GS'], ['W_pct', 'W%'], ['BABIP_against', 'BABIP Ag'], ['K_pct_p', 'K%'], ['BB_pct_p', 'BB%'],
  ['FIP', 'FIP'], ['xFIP', 'xFIP'], ['K_BB_pct', 'K-BB%'], ['LOB_pct', 'LOB%'], ['WP_per_9', 'WP/9'], ['GB_pct', 'GB%'],
  ['FB_pct', 'FB%'], ['Barrel_pct', 'Barrel%'], ['HardHit_pct', 'HardHit%'], ['Soft_pct', 'Soft%'], ['LD_pct', 'LD%'],
  ['HR_FB', 'HR/FB'], ['IR_pct', 'IR%'], ['GIDP_rate', 'GIDP Rate'],
].map(([value, label]) => ({ value, label }));

export const BATTING_ATTRS = [
  ['contact_base', 'Contact'], ['power_base', 'Power'], ['eye_base', 'Eye'], ['discipline_base', 'Discipline'],
  ['speed_base', 'Speed'], ['baserunning_base', 'Baserunning'], ['basereaction_base', 'Base Reaction'],
].map(([value, label]) => ({ value, label }));

export const PITCHING_ATTRS = [
  ['pendurance_base', 'Endurance'], ['pgencontrol_base', 'Gen Control'], ['psequencing_base', 'Sequencing'],
  ['pthrowpower_base', 'Throw Power'], ['pickoff_base', 'Pickoff'], ['avg_consist', 'Avg Consistency'],
  ['avg_pacc', 'Avg Accuracy'], ['avg_pbrk', 'Avg Break'], ['avg_pcntrl', 'Avg Control'],
].map(([value, label]) => ({ value, label }));

const LABELS = Object.fromEntries([...BATTING_STATS, ...PITCHING_STATS, ...BATTING_ATTRS, ...PITCHING_ATTRS].map(o => [o.value, o.label]));
export const labelOf = (key) => LABELS[key] || key;

const CATEGORY = [{ value: 'batting', label: 'Batting' }, { value: 'pitching', label: 'Pitching' }];

/** Category + optional stat/attr selects + min threshold. */
export function catControls({ stat = true, attrs = [], min = 50 } = {}) {
  const out = [field.select('category', 'Category', CATEGORY, { value: 'batting' })];
  for (const [name, label] of attrs) out.push(field.select(name, label, []));
  if (stat) out.push(field.select('target_stat', 'Target stat', []));
  out.push(field.number('min_threshold', 'Min threshold', { value: min, min: 1 }));
  return out.join('');
}

/** Fill the stat/attr selects for the chosen category and keep them in sync. */
export function initCat(controlsEl, signal) {
  const refill = () => {
    const cat = q(controlsEl, '[name="category"]').value;
    const stats = cat === 'pitching' ? PITCHING_STATS : BATTING_STATS;
    const attrs = cat === 'pitching' ? PITCHING_ATTRS : BATTING_ATTRS;
    const st = q(controlsEl, '[name="target_stat"]');
    if (st) fillSelect(st, stats);
    for (const sel of controlsEl.querySelectorAll('[name="attribute"], [name="attr_a"], [name="attr_b"]')) fillSelect(sel, attrs);
    const b = q(controlsEl, '[name="attr_b"]');
    if (b && attrs.length > 1) b.value = String(attrs[1].value);
  };
  refill();
  on(q(controlsEl, '[name="category"]'), 'change', refill, signal);
}

// ---------------------------------------------------------------------------
// Correlation heatmap + scatter drill-down (batting / pitching / defense)
// ---------------------------------------------------------------------------

function renderHeatmap(body, data) {
  const attrs = data.attribute_labels || data.attributes;
  const stats = data.stat_labels || data.stats;
  const rows = (data.r_matrix || []).map((row, ai) => `<tr><td class="nowrap"><strong>${esc(attrs[ai])}</strong></td>${row.map((r, si) =>
    heatCell(heatColor(r), Number(r).toFixed(2), { title: `${attrs[ai]} vs ${stats[si]} — click to drill`, attrs: `data-attr="${esc(data.attributes[ai])}" data-stat="${esc(data.stats[si])}" role="button"` })).join('')}</tr>`);
  setHtml(body, `
    ${card('Correlation heatmap', `<p class="text-muted small mb-1">Click a cell to drill down into a scatter plot.</p>${rawTable(['', ...stats.map(s => esc(s))], rows)}`, { subtitle: `n = ${data.n}`, id: 'corr-heat' })}
    <div class="card" id="corr-scatter" hidden>
      <div class="card-head"><div><h3 id="corr-sc-title"></h3><p class="card-sub text-muted mono" id="corr-sc-info"></p></div>
        <button type="button" class="btn btn-sm btn-secondary" data-action="corr-back">Back to heatmap</button></div>
      <div id="corr-sc-chart"></div>
      <div id="corr-sc-detail" class="mt-2" hidden></div>
    </div>`);
}

function renderPlayerDetail(el, pt) {
  const stats = Object.entries(pt.all_stats || {}).map(([k, v]) => ({ label: labelOf(k), value: k === 'AB_per_HR' ? fx(v, 1) : fx(v, 3) }));
  const attrs = Object.entries(pt.all_attrs || {}).map(([k, v]) => ({ label: labelOf(k), value: fx(v, 0) }));
  setHtml(el, `
    <div class="row mb-1"><h4>${esc(pt.name)}</h4><span class="text-muted small">Player ID ${esc(pt.player_id)}</span>
      <a class="btn btn-xs btn-ghost" href="#/data/players?player_id=${esc(pt.player_id)}">Open player</a></div>
    ${stats.length ? `<h5 class="mb-1">Stats</h5>${kpiRow(stats)}` : ''}
    ${attrs.length ? `<h5 class="mb-1">Attributes</h5>${kpiRow(attrs)}` : ''}`);
  el.hidden = false;
}

function renderScatter(body, data, signal) {
  q(body, '#corr-heat').hidden = true;
  const card_ = q(body, '#corr-scatter');
  card_.hidden = false;
  q(body, '#corr-sc-title').textContent = `${data.attr_label} vs ${data.stat_label}`;
  q(body, '#corr-sc-info').textContent = `R = ${fx(data.r, 4)} | y = ${fx(data.slope, 4)}x + ${fx(data.intercept, 4)} | n = ${data.n}`;
  const detail = q(body, '#corr-sc-detail');
  detail.hidden = true; detail.innerHTML = '';
  const host = q(body, '#corr-sc-chart');
  host.innerHTML = '';
  const xs = data.points.map(p => p.x);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  return mountChart(chartCanvas(host, { height: 420 }), {
    type: 'scatter',
    data: { datasets: [
      { label: 'Players', data: data.points.map(p => ({ x: p.x, y: p.y })), backgroundColor: color(0, 0.55), borderColor: color(0), pointRadius: 4, pointHoverRadius: 7 },
      { label: 'Regression', type: 'line', data: [{ x: minX, y: data.slope * minX + data.intercept }, { x: maxX, y: data.slope * maxX + data.intercept }], borderColor: color(3), borderWidth: 2, pointRadius: 0, fill: false },
    ] },
    options: {
      onClick(evt, elements) {
        if (!elements.length || elements[0].datasetIndex !== 0) { detail.hidden = true; return; }
        renderPlayerDetail(detail, data.points[elements[0].index]);
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => (c.datasetIndex === 0 ? `${data.points[c.dataIndex].name}: (${fx(c.raw.x, 1)}, ${fx(c.raw.y, 4)})` : '') } },
      },
      scales: { x: { type: 'linear', title: { display: true, text: data.attr_label } }, y: { title: { display: true, text: data.stat_label } } },
    },
  }, signal);
}

function correlationReport(cfg) {
  return {
    id: cfg.id, title: cfg.title, desc: cfg.desc, controls: cfg.controls,
    async run({ body, signal, filters, controls, status, controlsEl }) {
      const base = () => ({ league_year_id: filters.lyid, league_level: filters.level, ...cfg.params(controls) });
      const data = await api.get(adm(`/analytics/${cfg.endpoint}`), { params: base(), signal });
      const ne = notEnough(data, cfg.hint);
      if (ne) { status(ne, 'warning'); return; }
      if (cfg.after) cfg.after(data, controlsEl);
      status(`n = ${data.n}`);
      renderHeatmap(body, data);
      let scatter = null;
      delegate(body, 'click', 'td[data-attr]', async (e, td) => {
        status('Loading scatter…');
        const drill = await api.get(adm(`/analytics/${cfg.endpoint}`), { params: { ...base(), drill_attr: td.dataset.attr, drill_stat: td.dataset.stat }, signal });
        if (scatter) scatter.destroy();
        scatter = renderScatter(body, drill, signal);
        status(`n = ${drill.n}`);
      }, signal);
      delegate(body, 'click', '[data-action="corr-back"]', () => { q(body, '#corr-scatter').hidden = true; q(body, '#corr-heat').hidden = false; }, signal);
    },
  };
}

export const battingCorr = correlationReport({
  id: 'batting', title: 'Batting correlations', endpoint: 'batting-correlations',
  desc: 'How player batting attributes correlate with offensive outcomes.',
  controls: field.number('min_ab', 'Min AB', { value: 50, min: 1 }),
  params: (c) => ({ min_ab: c.min_ab }), hint: 'Lower min AB.',
});

export const pitchingCorr = correlationReport({
  id: 'pitching', title: 'Pitching correlations', endpoint: 'pitching-correlations',
  desc: 'How pitcher attributes correlate with pitching outcomes.',
  controls: field.number('min_ipo', 'Min IPO', { value: 60, min: 1 }),
  params: (c) => ({ min_ipo: c.min_ipo }), hint: 'Lower min IPO.',
});

export const defenseCorr = correlationReport({
  id: 'defense', title: 'Defensive analysis', endpoint: 'defensive-analysis',
  desc: 'How fielding attributes correlate with defensive performance.',
  controls: field.select('position_code', 'Position', [], { placeholder: 'All' }) + field.number('min_innings', 'Min innings', { value: 50, min: 1 }),
  params: (c) => ({ min_innings: c.min_innings, position_code: c.position_code || undefined }), hint: 'Lower min innings.',
  after(data, controlsEl) {
    const sel = q(controlsEl, '[name="position_code"]');
    if (sel && data.positions) fillSelect(sel, data.positions.map(p => ({ value: p, label: String(p).toUpperCase() })), { placeholder: 'All' });
  },
});

// ---------------------------------------------------------------------------
// WAR leaderboard
// ---------------------------------------------------------------------------

const WAR_PAGE_SIZE = 200;   // backend cap; the table pages client-side
const WAR_MAX_PAGES = 15;

export const warReport = {
  id: 'war', title: 'WAR leaderboard',
  desc: 'Custom WAR with adjustable component weights and replacement baseline. All qualifying players are fetched; sort and page in the table.',
  controls: [
    field.number('min_ab', 'Min AB', { value: 50, min: 1 }),
    field.number('min_ipo', 'Min IPO', { value: 60, min: 1 }),
    rangeField('replacement_pct', 'Replacement %', { value: 80, min: 50, max: 95, step: 1 }),
    rangeField('w_batting', 'Batting', { value: 1, min: 0, max: 2, step: 0.1 }),
    rangeField('w_baserunning', 'Baserunning', { value: 1, min: 0, max: 2, step: 0.1 }),
    rangeField('w_fielding', 'Fielding', { value: 1, min: 0, max: 2, step: 0.1 }),
    rangeField('w_pitching', 'Pitching', { value: 1, min: 0, max: 2, step: 0.1 }),
  ].join(''),
  async run({ body, signal, filters, controls, status }) {
    const params = {
      league_year_id: filters.lyid, league_level: filters.level, min_ab: controls.min_ab, min_ipo: controls.min_ipo,
      replacement_pct: controls.replacement_pct / 100, w_batting: controls.w_batting, w_baserunning: controls.w_baserunning,
      w_fielding: controls.w_fielding, w_pitching: controls.w_pitching, page_size: WAR_PAGE_SIZE,
    };
    const first = await api.get(adm('/analytics/war-leaderboard'), { params: { ...params, page: 1 }, signal });
    let leaders = first.leaders || [];
    const pages = Math.min(first.pages || 1, WAR_MAX_PAGES);
    if (pages > 1) {
      status(`Loading ${pages} pages…`);
      const rest = await Promise.all(Array.from({ length: pages - 1 }, (_, i) => api.get(adm('/analytics/war-leaderboard'), { params: { ...params, page: i + 2 }, signal })));
      for (const r of rest) leaders = leaders.concat(r.leaders || []);
    }
    status(`${leaders.length} of ${first.total} players${(first.pages || 1) > WAR_MAX_PAGES ? ` (capped at ${WAR_MAX_PAGES * WAR_PAGE_SIZE})` : ''}`);
    const la = first.league_averages || {};
    setHtml(body, `
      ${card('League context', kpiRow([
        { label: 'Lg wOBA', value: fx(la.woba, 3) }, { label: 'Lg OPS', value: fx(la.ops, 3) }, { label: 'Lg ERA', value: fx(la.era, 2) }, { label: 'Lg FIP', value: fx(la.fip, 2) },
        { label: 'Repl wOBA', value: fx(first.repl_woba, 3) }, { label: 'Repl FIP', value: fx(first.repl_fip, 2) }, { label: 'R/PA', value: fx(la.r_pa, 4) }, { label: 'cFIP', value: fx(la.fip_constant, 2) },
      ]))}
      <div class="card"><div id="war-table"></div></div>`);
    const num = (key, title, d = 1) => ({ key, title, align: 'right', sortable: true, render: r => fx(r[key], d), sortValue: r => r[key] });
    dataTable(q(body, '#war-table'), {
      rows: leaders, rowKey: 'player_id', pageSize: 50, sortKey: 'war', sortDir: 'desc', compact: true, emptyText: 'No qualifying players.',
      columns: [
        { key: 'rank', title: '#', sortable: true, width: '50px' },
        { key: 'name', title: 'Name', sortable: true },
        { key: 'team', title: 'Team', sortable: true },
        { key: 'position', title: 'Pos', sortable: true },
        { key: 'type', title: 'Type', sortable: true },
        { key: 'war', title: 'WAR', align: 'right', sortable: true, html: true, render: r => `<span class="${signedClass(r.war)}"><strong>${fx(r.war, 1)}</strong></span>`, sortValue: r => r.war },
        num('batting_runs', 'Bat'), num('br_runs', 'BR'), num('fld_runs', 'Fld'), num('pos_adj', 'Pos adj'), num('pit_runs', 'Pit'),
        num('woba', 'wOBA', 3),
        { key: 'wrc_plus', title: 'wRC+', align: 'right', sortable: true, render: r => (r.wrc_plus == null ? '--' : fmtNum(Math.round(r.wrc_plus))), sortValue: r => r.wrc_plus },
        num('fip', 'FIP', 2),
      ],
    });
  },
};

// ---------------------------------------------------------------------------
// Multi-regression
// ---------------------------------------------------------------------------

function perfTable(el, rows) {
  dataTable(el, {
    rows, compact: true, sortKey: 'residual', emptyText: 'None.',
    columns: [
      { key: 'name', title: 'Player', sortable: true },
      { key: 'actual', title: 'Actual', align: 'right', sortable: true, render: r => fx(r.actual, 4) },
      { key: 'predicted', title: 'Predicted', align: 'right', sortable: true, render: r => fx(r.predicted, 4) },
      { key: 'residual', title: 'Residual', align: 'right', sortable: true, html: true, render: r => signed(r.residual, 4) },
    ],
  });
}

export const regressionReport = {
  id: 'regression', title: 'Multi-regression',
  desc: 'Fit all attributes simultaneously to a target stat: independent contribution of each attribute, R², and over/underperformers.',
  controls: catControls({ stat: true }), init: initCat,
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/multi-regression'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, category: controls.category, target_stat: controls.target_stat, min_threshold: controls.min_threshold } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    setHtml(body, `
      ${card('Coefficients', '<div id="reg-coef"></div>', { subtitle: `R² = ${fx(data.r_squared, 4)}` })}
      <div class="grid-2">
        ${card('Top overperformers', '<div id="reg-over"></div>')}
        ${card('Top underperformers', '<div id="reg-under"></div>')}
      </div>`);
    dataTable(q(body, '#reg-coef'), {
      rows: data.coefficients || [], compact: true, sortKey: 'pct_importance', sortDir: 'desc',
      columns: [
        { key: 'label', title: 'Attribute', sortable: true },
        { key: 'beta', title: 'Beta', align: 'right', sortable: true, render: r => fx(r.beta, 4) },
        { key: 'std_beta', title: 'Std beta', align: 'right', sortable: true, html: true, render: r => signed(r.std_beta, 4, { plus: false }) },
        { key: 'pct_importance', title: 'Importance', align: 'right', sortable: true, render: r => `${r.pct_importance}%` },
      ],
    });
    perfTable(q(body, '#reg-over'), data.top_overperformers || []);
    perfTable(q(body, '#reg-under'), data.top_underperformers || []);
  },
};

// ---------------------------------------------------------------------------
// Sensitivity curves
// ---------------------------------------------------------------------------

export const sensitivityReport = {
  id: 'sensitivity', title: 'Sensitivity curves',
  desc: 'Bucket players by attribute deciles and plot the mean stat per bucket: linearity, diminishing returns and ceiling effects.',
  controls: catControls({ stat: true, attrs: [['attribute', 'Attribute']] }), init: initCat,
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/sensitivity'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, category: controls.category, target_stat: controls.target_stat, attribute: controls.attribute, min_threshold: controls.min_threshold } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    setHtml(body, card(`${data.attr_label} → ${data.stat_label}`, `<div class="mb-1">${data.diminishing_returns ? badge('Diminishing returns detected', 'warning') : badge('No diminishing-returns flag', 'secondary')}</div><div id="sens-chart"></div>`));
    mountChart(chartCanvas(q(body, '#sens-chart'), { height: 350 }), {
      type: 'bar',
      data: { labels: data.buckets.map(b => b.label), datasets: [
        { label: `${data.stat_label} (mean)`, data: data.buckets.map(b => b.mean), backgroundColor: color(0, 0.7), borderColor: color(0), yAxisID: 'y' },
        { label: 'Player count', type: 'line', data: data.buckets.map(b => b.count), borderColor: color(2), backgroundColor: color(2, 0.15), yAxisID: 'y1', pointRadius: 3 },
      ] },
      options: { scales: { y: { position: 'left', title: { display: true, text: data.stat_label } }, y1: { position: 'right', title: { display: true, text: 'Count' }, grid: { drawOnChartArea: false } } } },
    }, signal);
  },
};

// ---------------------------------------------------------------------------
// xStats / residuals
// ---------------------------------------------------------------------------

export const xstatsReport = {
  id: 'xstats', title: 'xStats / residuals',
  desc: 'Predict each player\'s expected stats from attributes via multi-regression; shows model fit per stat and the most unusual players.',
  controls: catControls({ stat: false }),
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/xstats'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, category: controls.category, min_threshold: controls.min_threshold } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    const stats = Object.keys(data.stat_models || {});
    const lbl = (s) => (data.stat_labels && data.stat_labels[s]) || s;
    setHtml(body, `${card('Model fit by stat', '<div id="xs-models"></div>')}${card('Most unusual players', '<div id="xs-players"></div>', { subtitle: 'Highest total absolute residual; hover a cell for actual vs expected.' })}`);
    dataTable(q(body, '#xs-models'), {
      rows: stats.map(s => ({ stat: lbl(s), ...data.stat_models[s] })), compact: true, sortKey: 'r_squared', sortDir: 'desc',
      columns: [
        { key: 'stat', title: 'Stat', sortable: true },
        { key: 'r_squared', title: 'R²', align: 'right', sortable: true, render: r => fx(r.r_squared, 4) },
        { key: 'resid_std', title: 'Residual std', align: 'right', sortable: true, render: r => fx(r.resid_std, 4) },
        { key: '_q', title: 'Fit', html: true, render: r => (r.r_squared >= 0.5 ? badge('Good', 'success') : r.r_squared >= 0.2 ? badge('Moderate', 'warning') : badge('Weak', 'danger')), sortValue: r => r.r_squared },
      ],
    });
    dataTable(q(body, '#xs-players'), {
      rows: data.players || [], compact: true, pageSize: 30, sortKey: 'total_abs_residual', sortDir: 'desc', rowKey: 'player_id',
      columns: [
        { key: 'name', title: 'Player', sortable: true },
        { key: 'total_abs_residual', title: 'Total |resid|', align: 'right', sortable: true, render: r => fx(r.total_abs_residual, 3) },
        ...stats.map(s => ({
          key: `s_${s}`, title: lbl(s), align: 'right', sortable: true, html: true,
          render: r => { const st = r.stats && r.stats[s]; return st ? signed(st.residual, 3) : '<span class="text-muted">-</span>'; },
          sortValue: r => (r.stats && r.stats[s] ? r.stats[s].residual : null),
          title_attr: r => { const st = r.stats && r.stats[s]; return st ? `Actual ${fx(st.actual, 3)}, expected ${fx(st.expected, 3)}` : ''; },
        })),
      ],
    });
  },
};

// ---------------------------------------------------------------------------
// Interaction effects
// ---------------------------------------------------------------------------

export const interactionsReport = {
  id: 'interactions', title: 'Interaction effects',
  desc: 'Do two attributes together predict a stat better than separately? Shows R² gain from the interaction term and a 2D performance grid.',
  controls: catControls({ stat: true, attrs: [['attr_a', 'Attribute A'], ['attr_b', 'Attribute B']] }), init: initCat,
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/interactions'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, category: controls.category, target_stat: controls.target_stat, attr_a: controls.attr_a, attr_b: controls.attr_b, min_threshold: controls.min_threshold } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    const means = data.grid.flat().map(c => c.mean).filter(v => v != null);
    const lo = Math.min(...means), hi = Math.max(...means), span = hi - lo || 1;
    const rows = data.grid.map((row, ri) => `<tr><td><strong>${esc(data.a_labels[ri])}</strong></td>${row.map(cell => (cell.mean == null
      ? '<td class="text-center text-muted">-</td>'
      : heatCell(seqColor((cell.mean - lo) / span), fx(cell.mean, 3), { title: `n = ${cell.n}` }))).join('')}</tr>`);
    const sig = data.r2_gain > 0.01;
    setHtml(body, card(`${data.attr_a_label} × ${data.attr_b_label} → ${data.stat_label}`, `
      ${kpiRow([
        { label: 'R² without interaction', value: fx(data.r2_without_interaction, 4) },
        { label: 'R² with interaction', value: fx(data.r2_with_interaction, 4) },
        { label: 'R² gain', value: `${data.r2_gain > 0 ? '+' : ''}${fx(data.r2_gain, 4)}`, kind: sig ? 'success' : data.r2_gain > 0 ? 'warning' : '' },
      ])}
      <div class="mb-1">${sig ? badge('Significant interaction', 'success') : badge('No significant interaction', 'secondary')}</div>
      ${rawTable([`${esc(data.attr_a_label)} \\ ${esc(data.attr_b_label)}`, ...data.b_labels.map(esc)], rows)}`));
  },
};
