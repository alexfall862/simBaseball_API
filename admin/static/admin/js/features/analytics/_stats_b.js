// features/analytics/_stats_b.js — Stats reports, group B:
// stat tuning dashboard, archetypes, pitch types, defensive positions, contact breakdown, HR depth.

import { api, adm } from '../../core/api.js';
import { esc, setHtml, delegate, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { field, card } from '../../ui/form.js';
import { badge } from '../../ui/badge.js';
import { mountChart, chartCanvas, color, CHART_COLORS } from '../../ui/chart.js';
import { fx, pct, signed, signedClass, seqColor, heatCell, kpiRow, rawTable, notEnough } from './_shared.js';
import { catControls, initCat } from './_stats_a.js';

const vsLeague = (v, lg) => (v == null ? '<span class="text-muted">-</span>' : `<span class="${signedClass(v - (lg || 0))}">${fx(v, 3)}</span>`);

// ---------------------------------------------------------------------------
// Per-stat tuning dashboard
// ---------------------------------------------------------------------------

export const dashboardReport = {
  id: 'dashboard', title: 'Stat tuning',
  desc: 'Deep dive into a single stat: MLB benchmark, distribution histogram, attribute rankings and stat-vs-stat correlations.',
  controls: catControls({ stat: true }), init: initCat,
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/stat-dashboard'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, category: controls.category, target_stat: controls.target_stat, min_threshold: controls.min_threshold } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`${data.stat_label} — n = ${data.n}`);
    const b = data.benchmark, d = data.distribution;
    const bkind = b ? (b.status === 'ok' ? 'success' : b.status === 'warning' ? 'warning' : 'danger') : '';
    setHtml(body, `
      ${card('Benchmark comparison', b ? kpiRow([
        { label: 'MLB mean', value: fx(b.mlb_mean, 3) }, { label: 'Sim mean', value: fx(b.sim_mean, 3) },
        { label: 'MLB std', value: fx(b.mlb_std, 3) }, { label: 'Sim std', value: fx(d.std, 3) },
        { label: 'Z-deviation', value: fx(b.z_deviation, 2), kind: bkind }, { label: 'Status', value: String(b.status || '').toUpperCase(), kind: bkind },
      ]) : '<p class="text-muted">No MLB benchmark available for this stat.</p>')}
      ${card('Distribution', `${kpiRow([
        { label: 'Mean', value: fx(d.mean, 4) }, { label: 'Std', value: fx(d.std, 4) }, { label: 'Min', value: fx(d.min, 4) },
        { label: 'P25', value: fx(d.p25, 4) }, { label: 'P50', value: fx(d.p50, 4) }, { label: 'P75', value: fx(d.p75, 4) }, { label: 'Max', value: fx(d.max, 4) },
      ])}<div id="dash-hist"></div>`)}
      ${card('Attribute rankings', '<div id="dash-attrs"></div>', { subtitle: `Model R² = ${fx(data.r_squared, 4)}` })}
      ${card('Stat-vs-stat correlations', '<div id="dash-statcorr"></div>')}`);
    mountChart(chartCanvas(q(body, '#dash-hist'), { height: 300 }), {
      type: 'bar',
      data: { labels: data.histogram.map(h => fx(h.lo, 3)), datasets: [{ label: `${data.stat_label} distribution`, data: data.histogram.map(h => h.count), backgroundColor: color(0, 0.7), borderColor: color(0) }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: data.stat_label } }, y: { title: { display: true, text: 'Count' } } } },
    }, signal);
    dataTable(q(body, '#dash-attrs'), {
      rows: data.attr_rankings || [], compact: true,
      columns: [
        { key: 'label', title: 'Attribute', sortable: true },
        { key: 'r', title: 'R', align: 'right', sortable: true, html: true, render: r => signed(r.r, 4, { plus: false }) },
        { key: 'p_value', title: 'p-value', align: 'right', sortable: true, render: r => fx(r.p_value, 4) },
        { key: '_ci', title: '95% CI', align: 'right', render: r => `[${fx(r.ci_lo, 3)}, ${fx(r.ci_hi, 3)}]` },
        { key: 'std_beta', title: 'Std beta', align: 'right', sortable: true, render: r => fx(r.std_beta, 4) },
        { key: 'significant', title: 'Sig?', html: true, sortable: true, render: r => (r.significant ? badge('yes', 'success') : ''), sortValue: r => (r.significant ? 1 : 0) },
      ],
    });
    dataTable(q(body, '#dash-statcorr'), {
      rows: data.stat_correlations || [], compact: true, sortKey: 'r', sortDir: 'desc',
      columns: [
        { key: 'label', title: 'Stat', sortable: true },
        { key: 'r', title: 'R', align: 'right', sortable: true, html: true, render: r => signed(r.r, 4, { plus: false }) },
      ],
    });
  },
};

// ---------------------------------------------------------------------------
// Archetype validation
// ---------------------------------------------------------------------------

export const archetypesReport = {
  id: 'archetypes', title: 'Archetypes',
  desc: 'Classify players into archetypes (Power Hitter, Contact Hitter, Speedster, …) and compare their average stat profiles with the league average (footer).',
  controls: field.number('min_ab', 'Min AB', { value: 50, min: 1 }),
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/archetypes'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, min_ab: controls.min_ab } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    const keys = Object.keys(data.stat_labels || {});
    const lg = data.league_average || {};
    const rows = Object.entries(data.archetypes || {}).map(([name, a]) => ({ name, count: a.count, ...Object.fromEntries(keys.map(k => [`s_${k}`, a.avg_stats[k]])) }));
    setHtml(body, card('Archetype stat profiles', '<div id="arch-table"></div>', { subtitle: 'Green/red = above/below league average.' }));
    dataTable(q(body, '#arch-table'), {
      rows, compact: true, sortKey: 'count', sortDir: 'desc',
      columns: [
        { key: 'name', title: 'Archetype', sortable: true },
        { key: 'count', title: 'Count', align: 'right', sortable: true },
        ...keys.map(k => ({ key: `s_${k}`, title: data.stat_labels[k], align: 'right', sortable: true, html: true, render: r => vsLeague(r[`s_${k}`], lg[k]) })),
      ],
      footer: () => `<tr><td><strong>League average</strong></td><td class="text-right">-</td>${keys.map(k => `<td class="text-right">${fx(lg[k] || 0, 3)}</td>`).join('')}</tr>`,
    });
  },
};

// ---------------------------------------------------------------------------
// Pitch type & repertoire
// ---------------------------------------------------------------------------

export const pitchTypesReport = {
  id: 'pitchtypes', title: 'Pitch types',
  desc: 'Group pitchers by primary pitch type and repertoire size; compare average outcomes across pitch profiles.',
  controls: field.number('min_ipo', 'Min IPO', { value: 60, min: 1 }),
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/pitch-types'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, min_ipo: controls.min_ipo } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    const keys = Object.keys(data.stat_labels || {});
    const statCols = keys.map(k => ({ key: `s_${k}`, title: data.stat_labels[k], align: 'right', sortable: true, render: r => fx(r[`s_${k}`] || 0, 3) }));
    const flat = (obj, nameKey) => Object.entries(obj || {}).map(([name, info]) => ({ [nameKey]: name, count: info.count, avg_repertoire_size: info.avg_repertoire_size, ...Object.fromEntries(keys.map(k => [`s_${k}`, info.avg_stats[k]])) }));
    setHtml(body, `${card('By primary pitch', '<div id="pt-types"></div>')}${card('By repertoire size', '<div id="pt-rep"></div>')}`);
    dataTable(q(body, '#pt-types'), {
      rows: flat(data.pitch_types, 'ptype'), compact: true, sortKey: 'count', sortDir: 'desc',
      columns: [{ key: 'ptype', title: 'Primary pitch', sortable: true }, { key: 'count', title: 'Count', align: 'right', sortable: true }, { key: 'avg_repertoire_size', title: 'Avg repertoire', align: 'right', sortable: true }, ...statCols],
    });
    dataTable(q(body, '#pt-rep'), {
      rows: flat(data.repertoire_analysis, 'size'), compact: true, sortKey: 'size',
      columns: [{ key: 'size', title: 'Pitches', sortable: true }, { key: 'count', title: 'Count', align: 'right', sortable: true }, ...statCols],
    });
  },
};

// ---------------------------------------------------------------------------
// Position-specific defensive analysis
// ---------------------------------------------------------------------------

export const defPosReport = {
  id: 'defpos', title: 'Defensive positions',
  desc: 'For each position, which defensive attributes matter most (correlation with fielding % and error rate).',
  controls: field.number('min_innings', 'Min innings', { value: 50, min: 1 }),
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/defensive-positions'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, min_innings: controls.min_innings } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`n = ${data.n}`);
    const entries = Object.entries(data.positions || {}).sort((a, b) => a[0].localeCompare(b[0]));
    setHtml(body, entries.length ? entries.map(([pos, info]) => card(String(pos).toUpperCase(), `<div data-dp="${esc(pos)}"></div>`, { subtitle: `n = ${info.count} · avg Fld% ${fx(info.avg_fld_pct, 3)} · avg E/inn ${fx(info.avg_e_per_inn, 4)}` })).join('') : '<div class="card"><p class="text-muted">No positions returned.</p></div>');
    for (const [pos, info] of entries) {
      dataTable(q(body, `[data-dp="${CSS.escape(String(pos))}"]`), {
        rows: info.attr_importance || [], compact: true,
        columns: [
          { key: 'label', title: 'Attribute', sortable: true },
          { key: 'r_vs_fielding_pct', title: 'R vs Fld%', align: 'right', sortable: true, html: true, render: r => signed(r.r_vs_fielding_pct, 4, { plus: false }) },
          { key: 'r_vs_error_rate', title: 'R vs E/inn', align: 'right', sortable: true, html: true, render: r => signed(r.r_vs_error_rate, 4, { plus: false, invert: true }) },
          { key: 'p_value', title: 'p-value', align: 'right', sortable: true, render: r => fx(r.p_value, 4) },
          { key: 'significant', title: 'Sig?', html: true, render: r => (r.significant ? badge('yes', 'success') : '') },
        ],
      });
    }
  },
};

// ---------------------------------------------------------------------------
// Contact type breakdown
// ---------------------------------------------------------------------------

const TIER_SERIES = [
  { label: 'AVG', key: 'AVG', c: 1, axis: 'y1' }, { label: 'ISO', key: 'ISO', c: 3, axis: 'y1' }, { label: 'BABIP', key: 'BABIP', c: 4, axis: 'y1' },
  { label: 'HR%', key: 'HR_pct', c: 2, axis: 'y' }, { label: 'ITPHR%', key: 'ITPHR_pct', c: 8, axis: 'y' }, { label: 'K%', key: 'K_pct', c: 9, axis: 'y' }, { label: 'BB%', key: 'BB_pct', c: 5, axis: 'y' },
];

const TIER_COLUMNS = (first, second) => [
  { key: 'label', title: 'Tier', sortable: false },
  { key: 'count', title: 'Count', align: 'right' },
  { key: first.key, title: first.title, align: 'right' },
  { key: second.key, title: second.title, align: 'right' },
  ...[['AVG', 3], ['SLG', 3], ['ISO', 3]].map(([k, d]) => ({ key: k, title: k, align: 'right', render: r => fx(r.stats[k], d) })),
  ...[['HR_pct', 'HR%'], ['ITPHR_pct', 'ITPHR%'], ['2B_pct', '2B%'], ['3B_pct', '3B%'], ['XBH_pct', 'XBH%'], ['K_pct', 'K%'], ['BB_pct', 'BB%']].map(([k, t]) => ({ key: k, title: t, align: 'right', render: r => pct(r.stats[k]) })),
  { key: 'BABIP', title: 'BABIP', align: 'right', render: r => fx(r.stats.BABIP, 3) },
];

function tierChart(host, tiers, signal) {
  mountChart(chartCanvas(host, { height: 300 }), {
    type: 'line',
    data: { labels: tiers.map(t => t.label), datasets: TIER_SERIES.map(s => ({ label: s.label, data: tiers.map(t => t.stats[s.key]), borderColor: color(s.c), backgroundColor: color(s.c, 0.2), fill: false, tension: 0.3, pointRadius: 4, yAxisID: s.axis })) },
    options: { scales: {
      y: { position: 'left', beginAtZero: true, title: { display: true, text: 'Rate %' } },
      y1: { position: 'right', beginAtZero: true, title: { display: true, text: 'Slash' }, grid: { drawOnChartArea: false } },
    } },
  }, signal);
}

const LEADER_CATS = [['iso', 'ISO'], ['hr_pct', 'HR%'], ['babip', 'BABIP'], ['xbh_pct', 'XBH%'], ['k_pct_low', 'Lowest K%']];

export const contactReport = {
  id: 'contact', title: 'Contact breakdown',
  desc: 'Configured contact odds and distance weights alongside actual batting outcomes. Use it to tune level_contact_odds / level_distance_weights and verify the engine reflects changes.',
  controls: field.number('min_ab', 'Min AB', { value: 30, min: 1 }),
  async run({ body, signal, filters, controls, status }) {
    const data = await api.get(adm('/analytics/contact-breakdown'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, min_ab: controls.min_ab } });
    const ne = notEnough(data); if (ne) { status(ne, 'warning'); return; }
    status(`${data.n} qualifying batters`);
    const cfg = data.config || {}, os = data.outcome_summary || {};
    const odds = cfg.contact_odds || {}, pcts = cfg.contact_odds_pct || {};
    const types = Object.keys(odds);
    const dw = cfg.distance_weights || {};
    const dwTypes = Object.keys(dw);
    const zones = [...new Set(dwTypes.flatMap(ct => Object.keys(dw[ct])))];
    const expected = cfg.expected_outcomes || {};
    const outcomeMap = [['single', '1B%', '1B_pct'], ['double', '2B%', '2B_pct'], ['triple', '3B%', '3B_pct'], ['homerun', 'HR%', 'HR_pct'], ['inside_the_park_hr', 'ITPHR%', 'ITPHR_pct']].filter(o => expected[o[0]] !== undefined);
    const perType = data.per_contact_type || [];

    setHtml(body, `
      ${card('Contact odds configuration', `${rawTable(['Metric', ...types.map(esc)], [
        `<tr><td>Raw odds</td>${types.map(t => `<td class="text-right">${esc(odds[t])}</td>`).join('')}</tr>`,
        `<tr><td>Share %</td>${types.map(t => `<td class="text-right">${esc(pcts[t])}%</td>`).join('')}</tr>`,
      ])}<div id="ct-odds-chart" class="mt-2"></div>`, { subtitle: 'Raw odds and percentage share for each contact type at this level.' })}
      ${dwTypes.length ? card('Distance weight configuration', rawTable(['Contact type', ...zones.map(esc)], dwTypes.map(ct => `<tr><td><strong>${esc(ct)}</strong></td>${zones.map(z => heatCell(seqColor(Math.min(dw[ct][z] || 0, 1)), String(dw[ct][z] || 0))).join('')}</tr>`)), { subtitle: 'How each contact type distributes across distance zones.' }) : ''}
      ${outcomeMap.length && os.total_ab ? card('Expected vs actual outcomes', `<div id="ct-exp-chart"></div>${rawTable(['Metric', ...outcomeMap.map(o => esc(o[1]))], [
        `<tr><td><strong>Expected (config)</strong></td>${outcomeMap.map(o => `<td class="text-right">${pct(expected[o[0]], 2)}</td>`).join('')}</tr>`,
        `<tr><td><strong>Actual</strong></td>${outcomeMap.map(o => `<td class="text-right">${pct(os[o[2]] || 0, 2)}</td>`).join('')}</tr>`,
        `<tr><td><strong>Delta</strong></td>${outcomeMap.map(o => `<td class="text-right">${signed((os[o[2]] || 0) - expected[o[0]], 2, { suffix: '%' })}</td>`).join('')}</tr>`,
      ])}`, { subtitle: 'Expected rates from contact_odds × fielding_weights config vs actual batting outcomes.' }) : ''}
      ${card('Actual batting outcomes', `${kpiRow([['AVG', fx(os.AVG)], ['OBP', fx(os.OBP)], ['SLG', fx(os.SLG)], ['OPS', fx(os.OPS)], ['ISO', fx(os.ISO)], ['BABIP', fx(os.BABIP)], ['K%', pct(os.K_pct)], ['BB%', pct(os.BB_pct)]].map(([label, value]) => ({ label, value })))}<div id="ct-outcome-chart"></div>`, { subtitle: `n = ${data.n}, ${fmtNum(os.total_pa || 0)} PA` })}
      ${card('Outcomes by power tier', '<div id="ct-power-table"></div><div id="ct-power-chart" class="mt-2"></div>', { subtitle: 'Players bucketed into power quintiles.' })}
      ${card('Outcomes by contact tier', '<div id="ct-contact-table"></div><div id="ct-contact-chart" class="mt-2"></div>', { subtitle: 'Players bucketed into contact quintiles.' })}
      ${card('Expected batting line by contact type', '<div id="ct-bytype-table"></div><div id="ct-bytype-chart" class="mt-2"></div>', { subtitle: 'Derived from fielding weights config: expected outcome distribution when a ball is put in play as each contact type.' })}
      ${card('Player leaders', `<div class="button-group mb-1" id="ct-leader-btns">${LEADER_CATS.map(([k, l], i) => `<button type="button" class="btn btn-sm ${i === 0 ? 'btn-primary' : 'btn-secondary'}" data-leader="${k}">${l}</button>`).join('')}</div><div id="ct-leaders"></div>`)}`);

    // Charts
    mountChart(chartCanvas(q(body, '#ct-odds-chart'), { height: 260 }), {
      type: 'bar',
      data: { labels: types, datasets: [{ label: 'Contact odds share %', data: types.map(t => pcts[t]), backgroundColor: types.map((_, i) => color(i, 0.6)), borderColor: types.map((_, i) => color(i)), borderWidth: 1 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: '% of contacts' } } } },
    }, signal);
    const expHost = q(body, '#ct-exp-chart');
    if (expHost) {
      mountChart(chartCanvas(expHost, { height: 300 }), {
        type: 'bar',
        data: { labels: outcomeMap.map(o => o[1]), datasets: [
          { label: 'Expected (config)', data: outcomeMap.map(o => expected[o[0]]), backgroundColor: color(0, 0.5), borderColor: color(0), borderWidth: 1 },
          { label: 'Actual', data: outcomeMap.map(o => os[o[2]] || 0), backgroundColor: color(1, 0.5), borderColor: color(1), borderWidth: 1 },
        ] },
        options: { scales: { y: { beginAtZero: true, title: { display: true, text: '% of AB' } } } },
      }, signal);
    }
    const outLabels = ['1B%', '2B%', '3B%', 'HR%', 'ITPHR%', 'K%', 'BB%'];
    const outVals = [os['1B_pct'], os['2B_pct'], os['3B_pct'], os.HR_pct, os.ITPHR_pct || 0, os.K_pct, os.BB_pct];
    mountChart(chartCanvas(q(body, '#ct-outcome-chart'), { height: 300 }), {
      type: 'bar',
      data: { labels: outLabels, datasets: [{ label: 'Rate %', data: outVals, backgroundColor: outLabels.map((_, i) => color(i, 0.6)), borderColor: outLabels.map((_, i) => color(i)), borderWidth: 1 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: '% of PA/AB' } } } },
    }, signal);

    // Tiers
    const tiers = data.tiers || [], ctiers = data.contact_tiers || [];
    dataTable(q(body, '#ct-power-table'), { rows: tiers, compact: true, emptyText: 'Not enough players for tier analysis.', columns: TIER_COLUMNS({ key: 'avg_power', title: 'Avg power' }, { key: 'avg_contact', title: 'Avg contact' }) });
    if (tiers.length) tierChart(q(body, '#ct-power-chart'), tiers, signal);
    dataTable(q(body, '#ct-contact-table'), { rows: ctiers, compact: true, emptyText: 'Not enough players for tier analysis.', columns: TIER_COLUMNS({ key: 'avg_contact', title: 'Avg contact' }, { key: 'avg_power', title: 'Avg power' }) });
    if (ctiers.length) tierChart(q(body, '#ct-contact-chart'), ctiers, signal);

    // Per contact type
    dataTable(q(body, '#ct-bytype-table'), {
      rows: perType, compact: true, emptyText: 'No contact type data.',
      columns: [
        { key: 'contact_type', title: 'Contact type', html: true, render: r => `<strong>${esc(r.contact_type)}</strong>` },
        ...[['frequency_pct', 'Freq %'], ['out_pct', 'Out%'], ['1B_pct', '1B%'], ['2B_pct', '2B%'], ['3B_pct', '3B%'], ['HR_pct', 'HR%'], ['ITPHR_pct', 'ITPHR%'], ['hit_pct', 'Hit%']].map(([k, t]) => ({ key: k, title: t, align: 'right', render: r => `${r[k] ?? 0}%` })),
        ...['AVG', 'SLG', 'ISO'].map(k => ({ key: k, title: k, align: 'right', render: r => fx(r[k], 3) })),
      ],
    });
    if (perType.length) {
      const series = [['Out%', 'out_pct', 9], ['1B%', '1B_pct', 0], ['2B%', '2B_pct', 1], ['3B%', '3B_pct', 2], ['HR%', 'HR_pct', 3], ['ITPHR%', 'ITPHR_pct', 8]];
      mountChart(chartCanvas(q(body, '#ct-bytype-chart'), { height: 300 }), {
        type: 'bar',
        data: { labels: perType.map(t => t.contact_type), datasets: series.map(([label, k, c]) => ({ label, data: perType.map(t => t[k] || 0), backgroundColor: color(c, 0.6), borderColor: color(c), borderWidth: 1 })) },
        options: { plugins: { tooltip: { mode: 'index', intersect: false } }, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, max: 100, title: { display: true, text: '% of outcomes' } } } },
      }, signal);
    }

    // Leaders
    const leadersEl = q(body, '#ct-leaders');
    const leaderTable = dataTable(leadersEl, {
      rows: [], compact: true, pageSize: 50, emptyText: 'No leaders.',
      columns: [
        { key: '_i', title: '#', render: (r, i) => i + 1 },
        { key: 'name', title: 'Player', sortable: true },
        { key: 'power', title: 'Power', align: 'right', sortable: true }, { key: 'contact', title: 'Contact', align: 'right', sortable: true }, { key: 'ab', title: 'AB', align: 'right', sortable: true },
        ...['AVG', 'SLG', 'ISO'].map(k => ({ key: k, title: k, align: 'right', sortable: true, render: r => fx(r[k], 3) })),
        ...[['HR_pct', 'HR%'], ['ITPHR_pct', 'ITPHR%'], ['2B_pct', '2B%'], ['K_pct', 'K%'], ['BB_pct', 'BB%']].map(([k, t]) => ({ key: k, title: t, align: 'right', sortable: true, render: r => pct(r[k] || 0) })),
        { key: 'BABIP', title: 'BABIP', align: 'right', sortable: true, render: r => fx(r.BABIP, 3) },
      ],
    });
    const showLeaders = (cat) => leaderTable.setRows((data.leaders && data.leaders[cat]) || []);
    showLeaders('iso');
    delegate(body, 'click', '#ct-leader-btns [data-leader]', (e, btn) => {
      btn.parentElement.querySelectorAll('button').forEach(b => { b.classList.toggle('btn-primary', b === btn); b.classList.toggle('btn-secondary', b !== btn); });
      showLeaders(btn.dataset.leader);
    }, signal);
  },
};

// ---------------------------------------------------------------------------
// HR depth analysis
// ---------------------------------------------------------------------------

const CONTACT_COLOR_INDEX = { barrel: 3, solid: 2, flare: 1, burner: 0, topped: 4, under: 5, weak: 9, unknown: 9 };
const DEPTH_ORDER = ['homerun', 'deep_of', 'middle_of', 'shallow_of', 'deep_if', 'middle_if', 'shallow_if', 'mound', 'catcher', 'unknown'];
const contactColor = (ct, a = 1) => color(CONTACT_COLOR_INDEX[ct] ?? (Object.keys(CONTACT_COLOR_INDEX).length % CHART_COLORS.length), a);

export const hrDepthReport = {
  id: 'hr-depth', title: 'HR depth',
  desc: 'Home runs by contact type (batted ball) and hit depth from play-by-play data. Scans every game at the level, so it can take a moment.',
  controls: field.select('game_type', 'Game type', [['regular', 'Regular'], ['playoff', 'Playoff'], ['allstar', 'All-Star'], ['wbc', 'WBC']].map(([value, label]) => ({ value, label })), { value: 'regular' }),
  async run({ body, signal, filters, controls, status }) {
    status('Loading play-by-play data… this may take a moment.');
    const data = await api.get(adm('/analytics/hr-depth'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, game_type: controls.game_type } });
    status(`${fmtNum(data.games_scanned)} games scanned`);
    const total = data.total_hr || 0, itp = data.total_itphr || 0;
    const byContact = data.by_contact_type || [], byDepth = data.by_hit_depth || [], cross = data.cross_tab || [];
    const contactTypes = byContact.map(r => r.batted_ball);
    const depths = byDepth.map(r => r.hit_depth).sort((a, b) => ((DEPTH_ORDER.indexOf(a) + 1 || 99) - (DEPTH_ORDER.indexOf(b) + 1 || 99)));
    const lookup = {};
    for (const r of cross) lookup[`${r.batted_ball}|${r.hit_depth}`] = r.count;
    const maxCount = Math.max(1, ...cross.map(r => r.count));
    const rows = contactTypes.map(ct => {
      let rowTotal = 0;
      const cells = depths.map(hd => { const c = lookup[`${ct}|${hd}`] || 0; rowTotal += c; return heatCell(c ? `rgba(239, 68, 68, ${(c / maxCount * 0.6 + 0.05).toFixed(2)})` : 'transparent', c ? String(c) : ''); }).join('');
      return `<tr><td><strong>${esc(ct)}</strong></td>${cells}<td class="text-right"><strong>${rowTotal}</strong></td></tr>`;
    });
    rows.push(`<tr><td><strong>Total</strong></td>${depths.map(hd => `<td class="text-center"><strong>${contactTypes.reduce((s, ct) => s + (lookup[`${ct}|${hd}`] || 0), 0)}</strong></td>`).join('')}<td class="text-right"><strong>${total}</strong></td></tr>`);

    setHtml(body, `
      ${card('Summary', kpiRow([
        { label: 'Games scanned', value: fmtNum(data.games_scanned) }, { label: 'Total HRs', value: fmtNum(total) },
        { label: 'Inside-the-park', value: `${itp} (${total ? (itp / total * 100).toFixed(1) : '0.0'}%)` }, { label: 'Over-the-fence', value: fmtNum(total - itp) },
      ]))}
      <div class="grid-2">
        ${card('HRs by contact type', `<div id="hrd-contact-table"></div><div id="hrd-contact-chart" class="mt-2"></div>`)}
        ${card('HRs by hit depth', `<div id="hrd-depth-table"></div><div id="hrd-depth-chart" class="mt-2"></div>`)}
      </div>
      ${card('Cross-tab: contact type × hit depth', `${rawTable(['Contact type', ...depths.map(esc), 'Total'], rows)}<div id="hrd-cross-chart" class="mt-2"></div>`, { subtitle: 'Each cell is the HR count for that contact type + hit depth combination.' })}`);

    const breakdown = (el, rows_, key) => dataTable(el, { rows: rows_, compact: true, columns: [
      { key, title: key === 'batted_ball' ? 'Contact type' : 'Hit depth', html: true, render: r => `<strong>${esc(r[key])}</strong>` },
      { key: 'count', title: 'Count', align: 'right', sortable: true, render: r => fmtNum(r.count) },
      { key: 'pct', title: '% of HRs', align: 'right', sortable: true, render: r => `${r.pct}%` },
    ] });
    breakdown(q(body, '#hrd-contact-table'), byContact, 'batted_ball');
    breakdown(q(body, '#hrd-depth-table'), byDepth, 'hit_depth');

    mountChart(chartCanvas(q(body, '#hrd-contact-chart'), { height: 300 }), {
      type: 'doughnut',
      data: { labels: contactTypes, datasets: [{ data: byContact.map(r => r.count), backgroundColor: contactTypes.map(ct => contactColor(ct, 0.8)), borderColor: contactTypes.map(ct => contactColor(ct)), borderWidth: 1 }] },
      options: { plugins: { legend: { position: 'right' }, tooltip: { callbacks: { label: it => `${it.label}: ${fmtNum(it.raw)} (${total ? (it.raw / total * 100).toFixed(1) : 0}%)` } } } },
    }, signal);
    mountChart(chartCanvas(q(body, '#hrd-depth-chart'), { height: 300 }), {
      type: 'bar',
      data: { labels: byDepth.map(r => r.hit_depth), datasets: [{ label: 'HR count', data: byDepth.map(r => r.count), backgroundColor: byDepth.map((_, i) => color(i, 0.6)), borderColor: byDepth.map((_, i) => color(i)), borderWidth: 1 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: it => `${fmtNum(it.raw)} HRs (${total ? (it.raw / total * 100).toFixed(1) : 0}%)` } } }, scales: { y: { beginAtZero: true, title: { display: true, text: 'Count' } }, x: { ticks: { maxRotation: 45 } } } },
    }, signal);
    mountChart(chartCanvas(q(body, '#hrd-cross-chart'), { height: 350 }), {
      type: 'bar',
      data: { labels: depths, datasets: contactTypes.map(ct => ({ label: ct, data: depths.map(hd => lookup[`${ct}|${hd}`] || 0), backgroundColor: contactColor(ct, 0.6), borderColor: contactColor(ct), borderWidth: 1 })) },
      options: { plugins: { tooltip: { mode: 'index', intersect: false } }, scales: { x: { stacked: true, ticks: { maxRotation: 45 } }, y: { stacked: true, beginAtZero: true, title: { display: true, text: 'HR count' } } } },
    }, signal);
  },
};
