// features/season/schedule.js — Schedule generator + viewer (port of legacy
// #section-schedule-gen and #section-schedule-viewer) as two sub-tabs.
//
// Note: the /admin/schedule/* endpoints key on the calendar league YEAR
// (e.g. 2027), not league_year_id. The year inputs default to the year of the
// globally selected league year.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { store } from '../../core/store.js';
import { ALL_LEVELS, SUBWEEKS, levelName } from '../../core/constants.js';
import { badge, kpi, alertBox } from '../../ui/badge.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm, openModal } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { levelSelect, loadLeagueYears, defaultLeagueYearId } from '../../ui/selectors.js';
import { dataTable } from '../../ui/table.js';
import { subTabs } from '../../ui/tabs.js';
import { childSignal } from './_shared.js';

const SUBS = [
  { id: 'generator', title: 'Generator' },
  { id: 'viewer', title: 'Viewer' },
];

const GAMES_PER_LEVEL = { 9: 162, 8: 120, 7: 120, 6: 120, 5: 120, 4: 120, 3: 50 };
const SV_PAGE_SIZE = 200;

/** Calendar year of the globally selected league year (falls back to timestamp / today). */
async function defaultYear() {
  try {
    const rows = await loadLeagueYears();
    const id = defaultLeagueYearId();
    const row = rows.find(r => r.id === id) || rows[0];
    if (row && row.year) return row.year;
  } catch (_) { /* fall through */ }
  const ts = store.get().ts;
  return (ts && ts.Season) || new Date().getFullYear();
}

export async function mount(el, ctx) {
  setHtml(el, html`<div id="sc-tabs"></div><div id="sc-body"></div>`);
  const body = q(el, '#sc-body');
  const year = await defaultYear();
  let active = null;

  function open(id) {
    if (active) active.abort();
    active = childSignal(ctx.signal);
    const sec = document.createElement('div');
    body.replaceChildren(sec);
    (id === 'viewer' ? mountViewer : mountGenerator)(sec, { signal: active.signal, year, params: ctx.params });
  }

  const initial = SUBS.some(s => s.id === ctx.params.sub) ? ctx.params.sub : 'generator';
  subTabs(q(el, '#sc-tabs'), SUBS, { active: initial, signal: ctx.signal, onSelect: (id) => { if (ctx.setParams) ctx.setParams({ sub: id }); open(id); } });
  open(initial);
}

// ---------------------------------------------------------------- shared: add series card

function addSeriesCard(prefix, year, title, blurb) {
  return `<div class="card" id="${prefix}-card">
    <div class="card-head"><div><h3>${esc(title)}</h3><p class="card-sub text-muted">${esc(blurb)}</p></div></div>
    ${formGrid([
    field.number(`${prefix}_year`, 'League year', { value: year, min: 2000, max: 2100 }),
    `<div class="form-group"><label for="${prefix}-level">League level</label><select id="${prefix}-level" name="${prefix}_level"></select></div>`,
    field.number(`${prefix}_home`, 'Home team ID', { min: 1 }),
    field.number(`${prefix}_away`, 'Away team ID', { min: 1 }),
    field.number(`${prefix}_week`, 'Week', { value: 1, min: 1, max: 60 }),
    field.number(`${prefix}_games`, 'Games (1-4)', { value: 3, min: 1, max: 4 }),
  ])}
    <div class="button-group"><button class="btn btn-primary" data-action="${prefix}-add">Add Series</button></div>
    <pre class="result-box mt-2" id="${prefix}-result"></pre>
  </div>`;
}

async function addSeries(sec, prefix, afterOk) {
  const f = readForm(q(sec, `#${prefix}-card`));
  const out = q(sec, `#${prefix}-result`);
  if (!f[`${prefix}_home`] || !f[`${prefix}_away`]) { toast.warn('Home and away team IDs are required.'); return; }
  const payload = {
    league_year: f[`${prefix}_year`], league_level: Number(f[`${prefix}_level`]),
    home_team_id: f[`${prefix}_home`], away_team_id: f[`${prefix}_away`],
    week: f[`${prefix}_week`], games: f[`${prefix}_games`],
  };
  try {
    const d = await api.post(adm('/schedule/add-series'), payload);
    out.textContent = `Added ${d.games_added}-game series in week ${d.week}: team ${d.home_team_id} vs ${d.away_team_id}`;
    toast.success(`Added ${d.games_added}-game series in week ${d.week}`);
    if (afterOk) await afterOk();
  } catch (e) { out.textContent = `Failed: ${e.message}`; }
}

// ================================================================= Generator

async function mountGenerator(sec, { signal, year }) {
  setHtml(sec, html`
    <div class="card">
      <div class="card-head"><div><h3>Schedule report</h3><p class="card-sub text-muted">Current schedule status across all levels and seasons.</p></div>
        <button class="btn btn-sm btn-secondary" data-action="report">Refresh Report</button></div>
      <div id="sg-report"></div>
    </div>
    <div class="card" id="sg-gen-card">
      <div class="card-head"><div><h3>Generate schedule</h3><p class="card-sub text-muted">Generate a full season schedule for the selected level. MLB uses all 52 weeks (162 games); MiLB/Scraps (120 games) and College (50 games) use a configurable start week.</p></div></div>
      ${raw(formGrid([
        field.number('sg_year', 'League year', { value: year, min: 2000, max: 2100 }),
        `<div class="form-group"><label for="sg-level">League level</label><select id="sg-level" name="sg_level"></select></div>`,
        field.number('sg_start_week', 'Start week', { value: 1, min: 1, max: 52 }),
        field.number('sg_seed', 'Random seed (optional)', { placeholder: 'Leave empty for random' }),
        field.checkbox('sg_clear_existing', 'Clear existing schedule first'),
      ]))}
      <div class="button-group">
        <button class="btn btn-secondary" data-action="validate">Validate</button>
        <button class="btn btn-primary" data-action="generate">Generate</button>
        <button class="btn btn-danger" data-action="clear">Clear Schedule</button>
      </div>
      <div id="sg-alert" class="mt-2"></div>
      <pre class="result-box" id="sg-result"></pre>
    </div>
    ${raw(addSeriesCard('sga', year, 'Add single series', 'Insert a one-off series (playoffs, exhibitions, specialty matchups).'))}`);

  const $ = id => q(sec, `#${id}`);
  const lvl = levelSelect($('sg-level'), { levels: ALL_LEVELS, value: 9, signal, onChange: onLevelChange });
  levelSelect($('sga-level'), { levels: ALL_LEVELS, value: 9, signal });
  const reportTable = dataTable($('sg-report'), {
    columns: [
      { key: 'year', title: 'Year', sortable: true },
      { key: 'level', title: 'Level', sortable: true, render: r => `${r.level} - ${r.level_name}`, sortValue: r => r.level },
      { key: 'games', title: 'Games', align: 'right', sortable: true },
      { key: 'teams', title: 'Teams', align: 'right', sortable: true },
      { key: 'weeks', title: 'Weeks', align: 'right', sortable: true },
    ],
    rows: [], compact: true, emptyText: 'No schedules found in the database.', sortKey: 'year', sortDir: 'desc',
  });

  function onLevelChange() {
    const level = lvl.get();
    const sw = q(sec, '[name="sg_start_week"]');
    if (level === 9) { sw.value = '1'; sw.disabled = true; }
    else if (level === 3) { sw.value = '1'; sw.disabled = false; }
    else { sw.disabled = false; if (sw.value === '1') sw.value = '10'; }
  }

  function showResult(text, kind) {
    setHtml($('sg-alert'), kind ? raw(alertBox(kind, text.split('\n')[0])) : '');
    $('sg-result').textContent = text;
  }

  async function loadReport() {
    reportTable.setLoading();
    try {
      const d = await api.get(adm('/schedule/report'), { signal, quiet: true });
      const rows = [];
      for (const [yr, levels] of Object.entries(d.seasons || {})) {
        for (const [lk, info] of Object.entries(levels)) {
          rows.push({ year: Number(yr), level: Number(lk), level_name: info.level_name || levelName(Number(lk)), games: info.games, teams: info.teams, weeks: info.weeks });
        }
      }
      reportTable.setRows(rows);
    } catch (e) { if (e && e.name !== 'AbortError') reportTable.setError(e.message); }
  }

  delegate(sec, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    const f = readForm($('sg-gen-card'));
    f.sg_level = Number(f.sg_level);   // selects read back as strings
    const lvName = levelName(f.sg_level);
    btn.disabled = true;
    try {
      if (a === 'report') await loadReport();
      else if (a === 'validate') {
        const d = await api.get(adm('/schedule/validate'), { params: { league_year: f.sg_year, league_level: f.sg_level }, signal });
        let msg = `Valid: ${d.valid}\nTeams: ${d.team_count}\nExisting games: ${d.existing_games}`;
        if (d.errors && d.errors.length) msg += '\n\nErrors:\n- ' + d.errors.join('\n- ');
        if (d.warnings && d.warnings.length) msg += '\n\nWarnings:\n- ' + d.warnings.join('\n- ');
        showResult(msg, d.valid ? 'success' : 'danger');
      } else if (a === 'generate') {
        if (!await confirm({ title: `Generate ${lvName} schedule for ${f.sg_year}?`, confirmLabel: 'Generate',
          message: `${GAMES_PER_LEVEL[f.sg_level] || ''} games per team, starting week ${f.sg_level === 9 ? 1 : f.sg_start_week}. This may take a moment for large leagues.${f.sg_clear_existing ? '\n\nExisting schedule will be cleared first.' : ''}` })) return;
        showResult('Generating schedule…');
        const d = await api.post(adm('/schedule/generate'), {
          league_year: f.sg_year, league_level: f.sg_level, start_week: f.sg_start_week,
          seed: f.sg_seed == null ? null : f.sg_seed, clear_existing: !!f.sg_clear_existing,
        });
        let msg = `Schedule generated successfully.\n\nTotal games: ${d.total_games}\nTotal series: ${d.total_series}\nWeeks: ${d.weeks}`;
        if (d.start_week) msg += ` (starting week ${d.start_week})`;
        if (d.games_per_team) msg += `\nGames per team: ${d.games_per_team}`;
        showResult(msg, 'success');
        toast.success(`${lvName} ${f.sg_year}: ${d.total_games} games generated`);
        await loadReport();
      } else if (a === 'clear') {
        if (!await confirm({ title: `Delete ALL ${lvName} games for ${f.sg_year}?`, danger: true, typeToConfirm: 'CLEAR', confirmLabel: 'Clear schedule', message: 'This action cannot be undone.' })) return;
        showResult('Clearing schedule…');
        const d = await api.post(adm('/schedule/clear'), { league_year: f.sg_year, league_level: f.sg_level });
        showResult(`Cleared ${d.deleted} games.`, 'success');
        toast.success(`Cleared ${d.deleted} ${lvName} games`);
        await loadReport();
      } else if (a === 'sga-add') await addSeries(sec, 'sga', loadReport);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (a !== 'sga-add') showResult(`Failed: ${err.message}`, 'danger');
    } finally { if (btn.isConnected) btn.disabled = false; }
  }, signal);

  onLevelChange();
  await loadReport();
}

// ================================================================= Viewer

async function mountViewer(sec, { signal, year, params }) {
  setHtml(sec, html`
    <div class="card" id="sv-filter-card">
      <div class="card-head"><div><h3>Schedule viewer</h3><p class="card-sub text-muted">Browse and filter the game schedule. Edit individual games.</p></div></div>
      ${raw(formGrid([
        field.number('sv_year', 'Season year', { value: year, min: 2000, max: 2100 }),
        `<div class="form-group"><label for="sv-level">League level</label><select id="sv-level" name="sv_level"></select></div>`,
        field.number('sv_team', 'Team ID (optional)', { placeholder: 'Filter by team', value: params.team || '' }),
        field.number('sv_week_start', 'Week start', { placeholder: 'From week', min: 1 }),
        field.number('sv_week_end', 'Week end', { placeholder: 'To week', min: 1 }),
        '<div class="form-group"><label>&nbsp;</label><button class="btn btn-primary" data-action="load">Load Schedule</button></div>',
      ]))}
    </div>
    <div class="card" id="sv-summary-card" hidden><h3>Weeks summary</h3><div id="sv-summary"></div></div>
    <div class="card" id="sv-quality-card" hidden>
      <div class="card-head"><div><h3>Schedule quality</h3><p class="card-sub text-muted">Games per team and home/away balance for the selected level. Home % outside 40–60 is flagged.</p></div>
        <button class="btn btn-sm btn-secondary" data-action="quality">Load Quality Metrics</button></div>
      <div id="sv-quality-stats-wrap" hidden><div id="sv-quality-stats" class="grid-3"></div></div>
      <div id="sv-quality"></div>
    </div>
    <div class="card" id="sv-games-card" hidden>
      <div class="card-head"><h3>Games <span class="text-muted small" id="sv-total"></span></h3>
        <div class="row"><button class="btn btn-sm btn-secondary" data-action="prev" disabled>&lsaquo; Prev</button><span class="text-muted small" id="sv-page">Page 1</span><button class="btn btn-sm btn-secondary" data-action="next" disabled>Next &rsaquo;</button></div></div>
      <div id="sv-games"></div>
    </div>
    ${raw(addSeriesCard('sva', year, 'Quick add series', 'Add a single series directly to the schedule.'))}
    <div class="card" id="sv-swap-card">
      <div class="card-head"><div><h3>Swap OOC opponents</h3><p class="card-sub text-muted">Swap two teams' out-of-conference opponents in a given week/subweek so they play each other instead. The displaced opponents are paired together.</p></div></div>
      ${raw(formGrid([
        field.number('sw_team_a', 'Team A ID', { min: 1, placeholder: 'User team A' }),
        field.number('sw_team_b', 'Team B ID', { min: 1, placeholder: 'User team B' }),
        field.number('sw_week', 'Week', { min: 1, placeholder: 'Season week' }),
        field.select('sw_subweek', 'Subweek', SUBWEEKS.map(s => ({ value: s, label: s })), { value: 'a' }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" data-action="swap">Swap Opponents</button></div>
      <pre class="result-box mt-2" id="sv-swap-result"></pre>
    </div>`);

  const $ = id => q(sec, `#${id}`);
  const lvl = levelSelect($('sv-level'), { levels: ALL_LEVELS, allowAll: true, value: params.level ?? null, signal });
  levelSelect($('sva-level'), { levels: ALL_LEVELS, value: 9, signal });
  const st = { page: 1, total: 0 };
  let qualityTable = null;

  const gamesTable = dataTable($('sv-games'), {
    columns: [
      { key: 'id', title: 'ID', sortable: true },
      { key: 'season_week', title: 'Week', sortable: true },
      { key: 'season_subweek', title: 'Sub', sortable: true, empty: '' },
      { key: 'level_name', title: 'Level', html: true, render: g => badge(g.level_name, 'secondary') },
      { key: 'away', title: 'Away', html: true, render: g => `${esc(g.away_team_abbrev || g.away_team_name)} <span class="text-muted">(${esc(g.away_team_id)})</span>`, sortValue: g => g.away_team_abbrev || g.away_team_name, sortable: true },
      { key: 'score', title: 'Score', align: 'center', html: true, render: g => (g.game_outcome != null ? `${esc(g.away_score)} - ${esc(g.home_score)}` : '<span class="text-muted">--</span>') },
      { key: 'home', title: 'Home', html: true, render: g => `${esc(g.home_team_abbrev || g.home_team_name)} <span class="text-muted">(${esc(g.home_team_id)})</span>`, sortValue: g => g.home_team_abbrev || g.home_team_name, sortable: true },
      { key: 'game_outcome', title: 'Result', html: true, render: g => (g.game_outcome != null ? badge(g.game_outcome, g.game_outcome === 'CANCELLED' ? 'danger' : 'success') : badge('Pending', 'pending')), sortable: true },
      { key: '_act', title: '', html: true, render: g => `<button class="btn btn-xs btn-secondary" data-action="edit" data-id="${esc(g.id)}">Edit</button>` },
    ],
    rows: [], rowKey: 'id', compact: true, emptyText: 'No games found',
  });

  function filters() {
    const f = readForm($('sv-filter-card'));
    const level = f.sv_level === '' || f.sv_level == null ? undefined : Number(f.sv_level);
    return { season_year: f.sv_year, league_level: level, team_id: f.sv_team ?? undefined, week_start: f.sv_week_start ?? undefined, week_end: f.sv_week_end ?? undefined };
  }

  async function load() {
    const f = filters();
    if (!f.season_year) { toast.warn('Season year is required.'); return; }
    gamesTable.setLoading(); $('sv-games-card').hidden = false;
    try {
      const d = await api.get(adm('/schedule/viewer'), { params: { ...f, page: st.page, page_size: SV_PAGE_SIZE }, signal });
      const totalPages = Math.ceil(d.total / SV_PAGE_SIZE) || 1;
      st.total = d.total;
      // Weeks summary
      const weeks = d.weeks_summary || {};
      const weekNums = Object.keys(weeks).map(Number).sort((a, b) => a - b);
      if (weekNums.length) {
        setHtml($('sv-summary'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Week</th><th>Games</th><th>Series</th></tr></thead><tbody>${weekNums.map(w => `<tr><td>${w}</td><td>${esc(weeks[w].games)}</td><td>${esc(weeks[w].series_count)}</td></tr>`).join('')}</tbody></table></div>`));
        $('sv-summary-card').hidden = false;
      } else $('sv-summary-card').hidden = true;
      $('sv-quality-card').hidden = f.league_level == null;
      $('sv-total').textContent = `(${d.total} games)`;
      $('sv-page').textContent = `Page ${st.page} of ${totalPages}`;
      q(sec, '[data-action="prev"]').disabled = st.page <= 1;
      q(sec, '[data-action="next"]').disabled = st.page >= totalPages;
      gamesTable.setRows(d.games || []);
    } catch (e) { if (e && e.name !== 'AbortError') gamesTable.setError(e.message); }
  }

  async function loadQuality() {
    const f = filters();
    if (f.league_level == null) { toast.warn('Select a league level to view quality metrics.'); return; }
    const d = await api.get(adm('/schedule/quality'), { params: { season_year: f.season_year, league_level: f.league_level }, signal });
    setHtml($('sv-quality-stats'), raw(kpi({ label: 'Avg games / team', value: d.avg_games_per_team }) + kpi({ label: 'Std dev', value: d.std_games_per_team }) + kpi({ label: 'Teams', value: d.team_count })));
    $('sv-quality-stats-wrap').hidden = false;
    const teams = d.games_per_team || {};
    const rows = Object.keys(teams).map(tid => ({ team_id: tid, ...teams[tid] }));
    if (!qualityTable) {
      qualityTable = dataTable($('sv-quality'), {
        columns: [
          { key: 'team_name', title: 'Team', sortable: true },
          { key: 'team_abbrev', title: 'Abbrev', sortable: true },
          { key: 'total', title: 'Total', align: 'right', sortable: true },
          { key: 'home', title: 'Home', align: 'right', sortable: true },
          { key: 'away', title: 'Away', align: 'right', sortable: true },
          { key: 'home_pct', title: 'Home %', align: 'right', sortable: true, html: true, render: t => (t.home_pct < 40 || t.home_pct > 60 ? `<span class="text-danger">${esc(t.home_pct)}%</span>` : `${esc(t.home_pct)}%`) },
        ],
        rows, rowKey: 'team_id', compact: true, sortKey: 'total', sortDir: 'desc',
      });
    } else qualityTable.setRows(rows);
  }

  function editGame(g) {
    const h = openModal({
      title: `Edit game ${g.id}`,
      body: formGrid([
        field.number('home_team', 'Home team ID', { value: g.home_team_id, min: 1 }),
        field.number('away_team', 'Away team ID', { value: g.away_team_id, min: 1 }),
        field.number('season_week', 'Week', { value: g.season_week, min: 1 }),
        field.select('season_subweek', 'Subweek', SUBWEEKS.map(s => ({ value: s, label: s })), { value: g.season_subweek || 'a' }),
      ]),
      actions: [
        { label: 'Cancel', cls: 'btn-secondary', onClick: hh => hh.close() },
        { label: 'Save', cls: 'btn-primary', onClick: async (hh) => {
          const f = readForm(hh.body);
          await api.put(adm(`/schedule/game/${g.id}`), { home_team: f.home_team, away_team: f.away_team, season_week: f.season_week, season_subweek: f.season_subweek });
          toast.success(`Game ${g.id} updated`);
          hh.close(true);
          await load();
        } },
      ],
    });
    return h;
  }

  async function swapOoc() {
    const f = readForm($('sv-swap-card'));
    const out = $('sv-swap-result');
    if (!f.sw_team_a || !f.sw_team_b) { toast.warn('Both Team A and Team B IDs are required.'); return; }
    if (!f.sw_week) { toast.warn('Week is required.'); return; }
    try {
      const d = await api.post(adm('/schedule/swap-ooc'), { team_a_id: f.sw_team_a, team_b_id: f.sw_team_b, season_week: f.sw_week, season_subweek: f.sw_subweek });
      if (!d.swapped) { out.textContent = d.message || 'No swap needed.'; toast.info(d.message || 'No swap needed.'); return; }
      const g1 = d.game_1, g2 = d.game_2;
      out.textContent = `Swapped! Game ${g1.game_id}: ${g1.away} @ ${g1.home} | Game ${g2.game_id}: ${g2.away} @ ${g2.home}`;
      toast.success('Opponents swapped');
      if (!$('sv-games-card').hidden) await load();
    } catch (e) { out.textContent = `Failed: ${e.message}`; }
  }

  on($('sv-level'), 'change', () => { $('sv-quality-card').hidden = lvl.get() == null; }, signal);
  delegate(sec, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    btn.disabled = true;
    try {
      if (a === 'load') { st.page = 1; await load(); }
      else if (a === 'prev') { st.page = Math.max(1, st.page - 1); await load(); }
      else if (a === 'next') { st.page += 1; await load(); }
      else if (a === 'quality') await loadQuality();
      else if (a === 'edit') { const g = gamesTable.rows.find(r => r.id === Number(btn.dataset.id)); if (g) editGame(g); }
      else if (a === 'sva-add') await addSeries(sec, 'sva', () => ($('sv-games-card').hidden ? null : load()));
      else if (a === 'swap') await swapOoc();
    } catch (err) { /* api layer toasts */ }
    finally { if (btn.isConnected) btn.disabled = false; }
  }, signal);

  if (params.autoload === '1' || params.team) { st.page = 1; await load(); }
}
