// features/analytics/stamina.js — stamina reports (port of legacy #section-stamina-*).
// overview · team detail · availability · consumption · flow history, as subTabs.

import { api, adm } from '../../core/api.js';
import { esc, setHtml, q } from '../../core/html.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { card } from '../../ui/form.js';
import { badge } from '../../ui/badge.js';
import { mountChart, chartCanvas, color } from '../../ui/chart.js';
import { reportTabs, signed, kpiRow } from './_shared.js';

const STAMINA_BINS = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-99', '100'];

function staminaKind(v) {
  if (v == null) return 'muted';
  return v >= 70 ? 'success' : v >= 40 ? 'warning' : 'danger';
}

/** Mini bar + coloured value. Width is data-derived, so it is inline. */
export function staminaBar(val, hasData = true) {
  if (!hasData || val == null) return '<span class="text-muted">N/A</span>';
  const v = Math.max(0, Math.min(100, Number(val)));
  return `<div class="row nowrap"><div class="progress-container" style="width:80px;height:10px"><div class="progress-fill" style="width:${v}%"></div></div><span class="text-${staminaKind(v)}"><strong>${esc(val)}</strong></span></div>`;
}

const staminaText = (v) => (v == null ? '<span class="text-muted">-</span>' : `<span class="text-${staminaKind(v)}"><strong>${esc(v)}</strong></span>`);
const dangerBadge = (level) => (level === 'critical' ? badge('CRITICAL', 'danger') : level === 'warning' ? badge('WARNING', 'warning') : badge('OK', 'success'));
const plusRec = (p) => (p.recovery_per_subweek == null ? '-' : `+${p.recovery_per_subweek}`);
const dash = (v) => (v == null ? '-' : v);

// ---------------------------------------------------------------------------

const overview = {
  id: 'overview', title: 'Overview', levelOptional: true, auto: true,
  desc: 'League-wide stamina distribution and per-team averages. Pitchers and position players are tracked separately; players without a fatigue row count as "no data".',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/stamina-overview'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level } });
    const pt = d.pitcher_thresholds || {}, bt = d.position_thresholds || {};
    const noData = (d.pitchers_no_data || 0) + (d.position_no_data || 0);
    setHtml(body, `
      ${kpiRow([
        { label: 'Players', value: `${d.total_pitchers || 0} P / ${d.total_position || 0} Pos` },
        { label: 'Avg stamina', value: `P ${d.pitcher_avg_stamina ?? 'N/A'} | Pos ${d.position_avg_stamina ?? 'N/A'}`, sub: noData ? `Tracked ${d.pitchers_with_data || 0}P + ${d.position_with_data || 0}Pos · no data ${d.pitchers_no_data || 0}P + ${d.position_no_data || 0}Pos` : 'All players tracked' },
        { label: 'Below 70', value: `P ${pt.below_70 || 0} | Pos ${bt.below_70 || 0}`, kind: 'warning' },
        { label: 'Below 40', value: `P ${pt.below_40 || 0} | Pos ${bt.below_40 || 0}`, kind: 'danger' },
        { label: 'At zero', value: `P ${pt.at_zero || 0} | Pos ${bt.at_zero || 0}`, kind: 'danger' },
      ])}
      ${card('Stamina distribution', '<div id="st-ov-chart"></div>', { subtitle: 'Tracked players only.' })}
      ${card('Team averages', '<div id="st-ov-table"></div>', { subtitle: 'Tracked/total shown when some players have no fatigue row.' })}`);
    mountChart(chartCanvas(q(body, '#st-ov-chart'), { height: 260 }), {
      type: 'bar',
      data: { labels: STAMINA_BINS, datasets: [
        { label: 'Pitchers', data: d.pitcher_distribution || [], backgroundColor: color(0, 0.7), borderColor: color(0), borderWidth: 1 },
        { label: 'Position players', data: d.position_distribution || [], backgroundColor: color(1, 0.7), borderColor: color(1), borderWidth: 1 },
      ] },
      options: { scales: { y: { beginAtZero: true, title: { display: true, text: 'Players' } } } },
    }, signal);
    const tracked = (t, c) => (t < c ? `${t}/${c}` : String(c));
    dataTable(q(body, '#st-ov-table'), {
      rows: d.team_averages || [], compact: true, rowKey: 'team_id', sortKey: 'avg_pitcher_stamina', emptyText: 'No teams.',
      columns: [
        { key: 'team_abbrev', title: 'Team', sortable: true },
        { key: 'team_level', title: 'Lvl', sortable: true },
        { key: 'pitcher_count', title: 'P tracked', align: 'right', render: r => tracked(r.pitcher_tracked, r.pitcher_count) },
        { key: 'avg_pitcher_stamina', title: 'P avg', align: 'right', sortable: true, html: true, render: r => staminaText(r.avg_pitcher_stamina) },
        { key: 'pitcher_below_70', title: 'P <70', align: 'right', sortable: true, cellClass: 'text-warning', render: r => r.pitcher_below_70 || 0 },
        { key: 'pitcher_below_40', title: 'P <40', align: 'right', sortable: true, cellClass: 'text-danger', render: r => r.pitcher_below_40 || 0 },
        { key: 'position_count', title: 'Pos tracked', align: 'right', render: r => tracked(r.position_tracked, r.position_count) },
        { key: 'avg_position_stamina', title: 'Pos avg', align: 'right', sortable: true, html: true, render: r => staminaText(r.avg_position_stamina) },
        { key: 'position_below_70', title: 'Pos <70', align: 'right', sortable: true, cellClass: 'text-warning', render: r => r.position_below_70 || 0 },
        { key: 'position_below_40', title: 'Pos <40', align: 'right', sortable: true, cellClass: 'text-danger', render: r => r.position_below_40 || 0 },
      ],
    });
  },
};

const team = {
  id: 'team', title: 'Team detail', uses: ['leagueYear', 'team'], teamRequired: true, auto: true,
  desc: 'Every rostered player on one team with current stamina, recovery per subweek and subweeks needed to reach 70 / 100.',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/stamina-team'), { signal, params: { league_year_id: filters.lyid, team_id: filters.teamId } });
    const pos = d.position_players || [];
    const posTracked = pos.filter(p => p.has_fatigue_data).length;
    setHtml(body, `${card('Pitchers', '<div id="st-tm-p"></div>')}${pos.length ? card('Position players', '<div id="st-tm-b"></div>', { subtitle: posTracked < pos.length ? `${posTracked}/${pos.length} have fatigue tracking data` : '' }) : ''}`);
    const common = [
      { key: 'name', title: 'Name', sortable: true },
      { key: 'stamina', title: 'Stamina', sortable: true, html: true, render: r => staminaBar(r.stamina, r.has_fatigue_data), sortValue: r => (r.has_fatigue_data ? r.stamina : null) },
      { key: 'durability', title: 'Durability', sortable: true },
    ];
    const tail = [
      { key: 'recovery_per_subweek', title: 'Rec/SW', align: 'right', sortable: true, render: plusRec },
      { key: 'subweeks_to_70', title: 'SW to 70', align: 'right', sortable: true, render: r => dash(r.subweeks_to_70) },
      { key: 'subweeks_to_100', title: 'SW to 100', align: 'right', sortable: true, render: r => dash(r.subweeks_to_100) },
    ];
    const rowClass = r => (r.has_fatigue_data ? '' : 'row-muted');
    dataTable(q(body, '#st-tm-p'), {
      rows: d.pitchers || [], compact: true, rowKey: 'player_id', sortKey: 'stamina', rowClass, emptyText: 'No pitchers.',
      columns: [...common,
        { key: 'pendurance_base', title: 'Endurance', align: 'right', sortable: true },
        { key: 'games', title: 'G', align: 'right', sortable: true }, { key: 'games_started', title: 'GS', align: 'right', sortable: true }, { key: 'ip', title: 'IP', align: 'right', sortable: true },
        ...tail],
    });
    if (pos.length) {
      dataTable(q(body, '#st-tm-b'), {
        rows: pos, compact: true, rowKey: 'player_id', sortKey: 'stamina', rowClass,
        columns: [...common,
          { key: 'games', title: 'G', align: 'right', sortable: true },
          { key: 'est_drain_per_game', title: 'Est. drain/G', align: 'right', sortable: true, html: true, render: r => (r.est_drain_per_game == null ? '<span class="text-muted">N/A</span>' : esc(r.est_drain_per_game)) },
          ...tail],
      });
    }
  },
};

const availability = {
  id: 'availability', title: 'Availability', levelOptional: true, auto: true,
  desc: 'How many players per team clear each usage threshold (≥95 only-fully-rested, ≥70 normal, ≥40 play-tired).',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/stamina-availability'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level } });
    setHtml(body, card('Availability by team', '<div id="st-av"></div>'));
    const grp = (prefix, totalKey, label) => [
      { key: totalKey, title: `${label} total`, align: 'right', sortable: true },
      { key: `${prefix}_avail_95`, title: `${label} ≥95`, align: 'right', sortable: true },
      { key: `${prefix}_avail_70`, title: `${label} ≥70`, align: 'right', sortable: true, html: true, render: r => `<strong>${esc(r[`${prefix}_avail_70`])}</strong>` },
      { key: `${prefix}_avail_40`, title: `${label} ≥40`, align: 'right', sortable: true, html: true, render: r => (r[`${prefix}_avail_40`] < r[totalKey] ? `<span class="text-danger">${esc(r[`${prefix}_avail_40`])}</span>` : esc(r[`${prefix}_avail_40`])) },
      { key: `${prefix}_danger`, title: `${label} status`, html: true, sortable: true, render: r => dangerBadge(r[`${prefix}_danger`]) },
    ];
    dataTable(q(body, '#st-av'), {
      rows: d.teams || [], compact: true, rowKey: 'team_id', emptyText: 'No teams.',
      columns: [
        { key: 'team_abbrev', title: 'Team', sortable: true, html: true, render: r => `<strong>${esc(r.team_abbrev)}</strong>` },
        { key: 'team_level', title: 'Lvl', sortable: true },
        ...grp('pitcher', 'total_pitchers', 'P'), ...grp('position', 'total_position', 'Pos'),
      ],
    });
  },
};

const consumption = {
  id: 'consumption', title: 'Consumption', levelOptional: true, auto: true,
  desc: 'Estimated stamina drained over the season per player; flags overworked pitchers and fatigued position players.',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/stamina-consumption'), { signal, params: { league_year_id: filters.lyid, league_level: filters.level } });
    const pos = d.position_players || [];
    const untracked = pos.filter(p => !p.has_fatigue_data).length;
    setHtml(body, `
      ${card('Pitchers', '<div id="st-con-p"></div>', { subtitle: `Avg games: ${d.pitcher_avg_games ?? '-'}` })}
      ${pos.length ? card('Position players', '<div id="st-con-b"></div>', { subtitle: `Avg games: ${d.position_avg_games ?? '-'}${untracked ? ` — ${untracked} players have no fatigue data (engine stamina_cost not yet reporting)` : ''}` }) : ''}`);
    const na = (v) => (v == null ? '<span class="text-muted">N/A</span>' : esc(v));
    dataTable(q(body, '#st-con-p'), {
      rows: d.pitchers || [], compact: true, rowKey: 'player_id', sortKey: 'est_total_consumed', sortDir: 'desc', rowClass: r => (r.overworked ? 'row-danger' : ''), emptyText: 'No pitchers.',
      columns: [
        { key: 'name', title: 'Name', sortable: true }, { key: 'team_abbrev', title: 'Team', sortable: true },
        { key: 'games', title: 'G', align: 'right', sortable: true }, { key: 'gs', title: 'GS', align: 'right', sortable: true }, { key: 'ip', title: 'IP', align: 'right', sortable: true },
        { key: 'current_stamina', title: 'Stamina', sortable: true, html: true, render: r => staminaBar(r.current_stamina) },
        { key: 'durability', title: 'Durability', sortable: true }, { key: 'pendurance_base', title: 'Endur.', align: 'right', sortable: true },
        { key: 'est_total_consumed', title: 'Est. drain', align: 'right', sortable: true }, { key: 'avg_cost_per_game', title: 'Avg/G', align: 'right', sortable: true },
        { key: 'overworked', title: 'Flag', html: true, sortable: true, render: r => (r.overworked ? badge('OVERWORKED', 'danger') : ''), sortValue: r => (r.overworked ? 1 : 0) },
      ],
    });
    if (pos.length) {
      dataTable(q(body, '#st-con-b'), {
        rows: pos, compact: true, rowKey: 'player_id', sortKey: 'est_total_consumed', sortDir: 'desc',
        rowClass: r => (r.fatigued ? 'row-warning' : r.has_fatigue_data ? '' : 'row-muted'),
        columns: [
          { key: 'name', title: 'Name', sortable: true }, { key: 'team_abbrev', title: 'Team', sortable: true },
          { key: 'games', title: 'G', align: 'right', sortable: true },
          { key: 'current_stamina', title: 'Stamina', sortable: true, html: true, render: r => staminaBar(r.current_stamina, r.has_fatigue_data), sortValue: r => (r.has_fatigue_data ? r.current_stamina : null) },
          { key: 'durability', title: 'Durability', sortable: true },
          { key: 'recovery_per_subweek', title: 'Rec/SW', align: 'right', sortable: true, render: plusRec },
          { key: 'est_total_consumed', title: 'Est. total drain', align: 'right', sortable: true, html: true, render: r => na(r.est_total_consumed) },
          { key: 'avg_cost_per_game', title: 'Avg/G', align: 'right', sortable: true, html: true, render: r => na(r.avg_cost_per_game) },
          { key: 'fatigued', title: 'Flag', html: true, render: r => (r.fatigued ? badge('FATIGUED', 'warning') : !r.has_fatigue_data ? badge('NO DATA', 'secondary') : '') },
        ],
      });
    }
  },
};

const flow = {
  id: 'flow', title: 'Flow history', uses: ['leagueYear', 'team'], auto: true,
  desc: 'Week-by-week pitcher drain vs estimated recovery and the projected average stamina. Leave team empty for all teams.',
  async run({ body, signal, filters }) {
    const d = await api.get(adm('/analytics/stamina-flow'), { signal, params: { league_year_id: filters.lyid, team_id: filters.teamId } });
    const weeks = d.weeks || [];
    if (!weeks.length) { setHtml(body, '<div class="card"><p class="text-muted">No data.</p></div>'); return; }
    setHtml(body, `${card('Stamina flow', '<div id="st-fl-chart"></div>', { subtitle: `${d.total_pitchers ?? '-'} pitchers` })}${card('By week', '<div id="st-fl-table"></div>')}`);
    mountChart(chartCanvas(q(body, '#st-fl-chart'), { height: 320 }), {
      type: 'line',
      data: { labels: weeks.map(w => `Wk ${w.week}`), datasets: [
        { label: 'Projected avg stamina', data: weeks.map(w => w.projected_avg_stamina), borderColor: color(0), backgroundColor: color(0, 0.12), fill: true, tension: 0.3 },
        { label: 'Total drain', data: weeks.map(w => w.total_drain), borderColor: color(3), backgroundColor: color(3, 0.1), borderDash: [5, 5], yAxisID: 'y1' },
        { label: 'Est recovery', data: weeks.map(w => w.est_recovery), borderColor: color(1), backgroundColor: color(1, 0.1), borderDash: [5, 5], yAxisID: 'y1' },
      ] },
      options: { scales: {
        y: { beginAtZero: true, max: 100, title: { display: true, text: 'Avg stamina' } },
        y1: { position: 'right', beginAtZero: true, title: { display: true, text: 'Drain / recovery' }, grid: { drawOnChartArea: false } },
      } },
    }, signal);
    dataTable(q(body, '#st-fl-table'), {
      rows: weeks, compact: true, rowKey: 'week',
      columns: [
        { key: 'week', title: 'Week', sortable: true }, { key: 'appearances', title: 'Appearances', align: 'right', sortable: true },
        { key: 'pitchers_used', title: 'Pitchers used', align: 'right', sortable: true }, { key: 'pitchers_resting', title: 'Resting', align: 'right', sortable: true },
        { key: 'total_drain', title: 'Total drain', align: 'right', sortable: true, cellClass: 'text-danger' },
        { key: 'est_recovery', title: 'Est recovery', align: 'right', sortable: true, cellClass: 'text-success' },
        { key: 'net_change', title: 'Net', align: 'right', sortable: true, html: true, render: r => signed(r.net_change, 0) },
        { key: 'projected_avg_stamina', title: 'Proj avg', align: 'right', sortable: true, html: true, render: r => staminaText(r.projected_avg_stamina) },
      ],
    });
  },
};

export async function mount(el, ctx) {
  await reportTabs(el, ctx, {
    title: 'Stamina',
    sub: 'Fatigue tracking from player_fatigue_state: distribution, team detail, availability vs usage thresholds, consumption and weekly flow.',
    reports: [overview, team, availability, consumption, flow],
    filters: { leagueYear: true, level: { levels: ALL_LEVELS, allowAll: true, allLabel: 'All levels' }, team: { placeholder: 'All teams' } },
  });
}
