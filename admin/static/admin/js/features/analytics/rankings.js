// features/analytics/rankings.js — team rankings (port of legacy #section-rankings-*).
// ELO · power · RPI · Pythagorean · race chart, as subTabs.

import { api, adm } from '../../core/api.js';
import { esc, setHtml, q } from '../../core/html.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { field, card } from '../../ui/form.js';
import { mountChart, chartCanvas, color } from '../../ui/chart.js';
import { reportTabs, fx, signed } from './_shared.js';

const teamLabel = (t) => t.team_abbrev || String(t.team_id);
const teamColor = (t, i) => t.color_one || color(i);

function rgba(hex, alpha) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// ---------------------------------------------------------------------------

const elo = {
  id: 'elo', title: 'ELO', auto: true,
  desc: 'ELO ratings recomputed from game results. Click a table row or a legend entry to highlight one team on the chart.',
  controls: field.number('k_factor', 'K-factor', { value: 32, min: 10, max: 64 }),
  async run({ body, signal, filters, controls }) {
    const d = await api.get(adm('/analytics/rankings-elo'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, k_factor: controls.k_factor } });
    const teams = d.teams || [], history = d.history || {};
    setHtml(body, `${card('ELO over time', '<div id="rk-elo-chart"></div>', { subtitle: 'Click a legend entry or a table row to highlight a team.' })}${card('Ratings', '<div id="rk-elo-table"></div>')}`);

    const dsTeam = [];        // dataset index -> team_id
    const baseColor = [];
    const datasets = [];
    teams.forEach((t, i) => {
      const hist = history[String(t.team_id)] || [];
      if (!hist.length) return;
      const c = teamColor(t, i);
      dsTeam.push(t.team_id); baseColor.push(c);
      datasets.push({ label: teamLabel(t), data: hist.map(h => ({ x: h.week, y: h.elo })), borderColor: c, backgroundColor: c, fill: false, tension: 0.3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.5 });
    });
    const weeks = [...new Set(Object.values(history).flatMap(h => h.map(p => p.week)))].sort((a, b) => a - b);
    let highlighted = null;

    const chart = mountChart(chartCanvas(q(body, '#rk-elo-chart'), { height: Math.max(360, Math.min(560, teams.length * 14)) }), {
      type: 'line',
      data: { datasets },
      options: {
        parsing: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 10, font: { size: 10 }, padding: 6 }, onClick: (e, item) => toggle(dsTeam[item.datasetIndex]) },
        },
        scales: {
          x: { type: 'linear', ticks: { stepSize: 1, callback: v => `Wk ${v}` }, min: weeks[0], max: weeks[weeks.length - 1] },
          y: { title: { display: true, text: 'ELO' } },
        },
      },
    }, signal);

    const table = dataTable(q(body, '#rk-elo-table'), {
      rows: teams, compact: true, rowKey: 'team_id', sortKey: 'rank',
      rowClass: r => (highlighted === r.team_id ? 'row-success' : ''),
      onRowClick: r => toggle(r.team_id),
      columns: [
        { key: 'rank', title: 'Rank', sortable: true, width: '60px' },
        { key: 'team_abbrev', title: 'Team', sortable: true, html: true, render: r => `<strong>${esc(teamLabel(r))}</strong>` },
        { key: 'elo', title: 'ELO', align: 'right', sortable: true, html: true, render: r => `<strong>${esc(r.elo)}</strong>` },
        { key: 'wins', title: 'W', align: 'right', sortable: true }, { key: 'losses', title: 'L', align: 'right', sortable: true },
        { key: 'win_pct', title: 'Win%', align: 'right', sortable: true, render: r => fx(r.win_pct, 3) },
        { key: 'trend', title: 'Trend', align: 'right', sortable: true, html: true, render: r => `<span class="${r.trend > 0 ? 'text-success' : r.trend < 0 ? 'text-danger' : 'text-muted'}">${r.trend > 0 ? '▲' : r.trend < 0 ? '▼' : '–'} ${fx(Math.abs(r.trend || 0), 1)}</span>` },
      ],
    });

    function toggle(teamId) {
      if (teamId == null || !chart.chart) return;
      highlighted = highlighted === teamId ? null : teamId;
      const idx = highlighted == null ? null : dsTeam.indexOf(highlighted);
      chart.chart.data.datasets.forEach((ds, i) => {
        if (idx === null) { ds.borderColor = baseColor[i]; ds.borderWidth = 1.5; ds.pointRadius = 0; ds.order = 0; }
        else if (i === idx) { ds.borderColor = baseColor[i]; ds.borderWidth = 3; ds.pointRadius = 2; ds.order = -1; }
        else { ds.borderColor = rgba(baseColor[i], 0.12); ds.borderWidth = 1; ds.pointRadius = 0; ds.order = 1; }
      });
      chart.chart.update();
      table.refresh();
    }
  },
};

const power = {
  id: 'power', title: 'Power', auto: true,
  desc: 'Composite score from ELO, recent record, run differential and roster OVR. Hover a component for its raw value.',
  controls: field.number('recent_weeks', 'Recent weeks', { value: 3, min: 1, max: 8 }),
  async run({ body, signal, filters, controls }) {
    const d = await api.get(adm('/analytics/rankings-power'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, recent_weeks: controls.recent_weeks } });
    const teams = d.teams || [], w = d.weights || {};
    const wp = (k) => `${((w[k] || 0) * 100).toFixed(0)}%`;
    setHtml(body, `${card('Power rankings breakdown', '<div id="rk-pow-chart"></div>')}${card('Rankings', '<div id="rk-pow-table"></div>', { subtitle: `Weights: ELO ${wp('elo')} | Recent ${wp('recent')} | Run diff ${wp('run_diff')} | Roster OVR ${wp('roster_ovr')}` })}`);
    const comp = (k, title, rawFmt) => ({
      key: `c_${k}`, title, align: 'right', sortable: true,
      render: r => { const c = r.components && r.components[k]; return c && c.normalized != null ? fx(c.normalized, 1) : '-'; },
      sortValue: r => (r.components && r.components[k] ? r.components[k].normalized : null),
      title_attr: r => { const c = r.components && r.components[k]; return c ? rawFmt(c.raw) : ''; },
    });
    dataTable(q(body, '#rk-pow-table'), {
      rows: teams, compact: true, rowKey: 'team_id', sortKey: 'rank',
      columns: [
        { key: 'rank', title: 'Rank', sortable: true, width: '60px' },
        { key: 'team_abbrev', title: 'Team', sortable: true, html: true, render: r => `<strong>${esc(teamLabel(r))}</strong>` },
        { key: 'composite_score', title: 'Score', align: 'right', sortable: true, html: true, render: r => `<strong>${fx(r.composite_score, 1)}</strong>` },
        { key: 'wins', title: 'W-L', align: 'right', sortable: true, render: r => `${r.wins}-${r.losses}` },
        comp('elo', 'ELO', v => `Raw: ${v}`), comp('recent', 'Recent', v => `Win%: ${fx(v, 3)}`), comp('run_diff', 'Run diff', v => `Per game: ${v}`), comp('roster_ovr', 'Roster OVR', v => `Raw: ${v}`),
      ],
    });
    const part = (k) => teams.map(t => ((t.components && t.components[k] && t.components[k].normalized) || 0) * (w[k] || 0));
    mountChart(chartCanvas(q(body, '#rk-pow-chart'), { height: Math.max(300, teams.length * 22) }), {
      type: 'bar',
      data: { labels: teams.map(teamLabel), datasets: [
        { label: `ELO (${wp('elo')})`, data: part('elo'), backgroundColor: color(0, 0.8) },
        { label: `Recent (${wp('recent')})`, data: part('recent'), backgroundColor: color(1, 0.8) },
        { label: `Run diff (${wp('run_diff')})`, data: part('run_diff'), backgroundColor: color(2, 0.8) },
        { label: `Roster OVR (${wp('roster_ovr')})`, data: part('roster_ovr'), backgroundColor: color(4, 0.8) },
      ] },
      options: { indexAxis: 'y', scales: { x: { stacked: true, title: { display: true, text: 'Composite score' } }, y: { stacked: true } } },
    }, signal);
  },
};

const rpi = {
  id: 'rpi', title: 'RPI', auto: true,
  desc: 'Rating Percentage Index: 25% win% + 50% opponents\' win% + 25% opponents\' opponents\' win%.',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/rankings-rpi'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level } });
    setHtml(body, card('RPI', '<div id="rk-rpi"></div>'));
    const n3 = (k, title) => ({ key: k, title, align: 'right', sortable: true, render: r => fx(r[k], 3) });
    dataTable(q(body, '#rk-rpi'), {
      rows: d.teams || [], compact: true, rowKey: 'team_id', sortKey: 'rank',
      columns: [
        { key: 'rank', title: 'Rank', sortable: true, width: '60px' },
        { key: 'team_abbrev', title: 'Team', sortable: true, html: true, render: r => `<strong>${esc(teamLabel(r))}</strong>` },
        { key: 'rpi', title: 'RPI', align: 'right', sortable: true, html: true, render: r => `<strong>${fx(r.rpi, 4)}</strong>` },
        n3('wp', 'Win%'), n3('owp', 'OWP'), n3('oowp', 'OOWP'), n3('sos', 'SOS'),
        { key: 'wins', title: 'W', align: 'right', sortable: true }, { key: 'losses', title: 'L', align: 'right', sortable: true },
      ],
    });
  },
};

const pyth = {
  id: 'pythagorean', title: 'Pythagorean', auto: true,
  desc: 'Expected wins from runs scored/allowed; Luck = actual − expected.',
  controls: field.number('exponent', 'Exponent', { value: 1.83, min: 1, max: 3, step: 0.01 }),
  async run({ body, signal, filters, controls }) {
    const d = await api.get(adm('/analytics/rankings-pythagorean'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level, exponent: controls.exponent } });
    const teams = d.teams || [];
    setHtml(body, `${card('Actual vs Pythagorean expected wins', '<div id="rk-pyth-chart"></div>')}${card('Pythagorean W-L', '<div id="rk-pyth-table"></div>')}`);
    const sub = (grp, k, d_) => ({ key: `${grp}_${k}`, title: k.toUpperCase(), align: 'right', sortable: true, render: r => fx(r[grp] && r[grp][k], d_), sortValue: r => (r[grp] ? r[grp][k] : null) });
    dataTable(q(body, '#rk-pyth-table'), {
      rows: teams, compact: true, rowKey: 'team_id', sortKey: 'rank',
      columns: [
        { key: 'rank', title: 'Rank', sortable: true, width: '60px' },
        { key: 'team_abbrev', title: 'Team', sortable: true, html: true, render: r => `<strong>${esc(teamLabel(r))}</strong>` },
        { key: 'wins', title: 'W-L', align: 'right', sortable: true, render: r => `${r.wins}-${r.losses}` },
        { key: 'win_pct', title: 'Win%', align: 'right', sortable: true, render: r => fx(r.win_pct, 3) },
        { key: 'runs_scored', title: 'RS', align: 'right', sortable: true }, { key: 'runs_allowed', title: 'RA', align: 'right', sortable: true },
        { key: 'run_diff', title: 'Diff', align: 'right', sortable: true, html: true, render: r => signed(r.run_diff, 0) },
        { key: 'r_per_g', title: 'R/G', align: 'right', sortable: true },
        { key: 'pyth_pct', title: 'Pyth%', align: 'right', sortable: true, render: r => fx(r.pyth_pct, 3) },
        { key: 'expected_wins', title: 'ExpW', align: 'right', sortable: true },
        { key: 'luck', title: 'Luck', align: 'right', sortable: true, html: true, render: r => signed(r.luck, 1) },
        sub('batting', 'avg', 3), sub('batting', 'ops', 3), sub('pitching', 'era', 2), sub('pitching', 'whip', 3),
      ],
    });
    const sorted = [...teams].sort((a, b) => b.wins - a.wins);
    mountChart(chartCanvas(q(body, '#rk-pyth-chart'), { height: 360 }), {
      type: 'bar',
      data: { labels: sorted.map(teamLabel), datasets: [
        { label: 'Actual wins', data: sorted.map(t => t.wins), backgroundColor: color(0, 0.8), borderColor: color(0), borderWidth: 1 },
        { label: 'Expected wins', data: sorted.map(t => t.expected_wins), backgroundColor: color(2, 0.6), borderColor: color(2), borderWidth: 1, borderDash: [5, 5] },
      ] },
      options: { scales: { y: { title: { display: true, text: 'Wins' } } } },
    }, signal);
  },
};

const race = {
  id: 'race', title: 'Race chart', auto: true,
  desc: 'Cumulative games above/below .500 over the season. MLB: by division. College: by conference. MiLB: all teams.',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/rankings-race'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level } });
    const groups = d.groups || {}, weekLabels = (d.weeks || []).map(w => `Wk ${w}`);
    const names = Object.keys(groups);
    if (!names.length) { setHtml(body, '<div class="card"><p class="text-muted">No race data.</p></div>'); return; }
    setHtml(body, names.map((g, i) => card(g, `<div id="rk-race-${i}"></div>`)).join(''));
    names.forEach((g, gi) => {
      const teams = groups[g] || [];
      mountChart(chartCanvas(q(body, `#rk-race-${gi}`), { height: 280 }), {
        type: 'line',
        data: { labels: weekLabels, datasets: teams.map((t, i) => { const c = teamColor(t, i); return { label: teamLabel(t), data: (t.series || []).map(p => p.value), borderColor: c, backgroundColor: c, fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2.5 }; }) },
        options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } }, scales: { y: { title: { display: true, text: 'Games above/below .500' } } } },
      }, signal);
    });
  },
};

export async function mount(el, ctx) {
  await reportTabs(el, ctx, {
    title: 'Rankings',
    sub: 'Team strength measures computed from results in gamelist/game_results.',
    reports: [elo, power, rpi, pyth, race],
    filters: { leagueYear: true, level: { levels: ALL_LEVELS, value: 9 } },
  });
}
