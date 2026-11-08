// features/season/simulate.js — simulation control (port of legacy #section-simulate).

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { SIM_LEVELS, ALL_LEVELS } from '../../core/constants.js';
import { json } from '../../core/format.js';
import { phaseBadge, subweekPips, subweekFlagsFromTs } from './_shared.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { levelSelect, defaultLeagueYearId } from '../../ui/selectors.js';
import { refreshTimestamp, refreshSummary } from '../../main.js';

export async function mount(el, ctx) {
  const lyid = defaultLeagueYearId() || 1;
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Simulation control</h3><p class="card-sub text-muted">Subweeks run a→d; advance after d. These buttons call the sim synchronously; for unattended runs use <a href="#/jobs/scheduled">Jobs</a>.</p></div>
        <div class="row" id="sim-state"></div>
      </div>
      <div class="row mb-2" id="sim-flags"></div>
      <div class="button-group" id="sim-buttons"></div>
      <div id="sim-progress"></div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Manual simulation</h3>
        <p class="text-muted small mb-2">Override year/week/level. Preview builds payloads without sending them to the engine.</p>
        ${raw(formGrid([
          field.number('league_year_id', 'League year ID', { value: lyid, min: 1 }),
          field.number('season_week', 'Season week', { value: 1, min: 1 }),
          `<div class="form-group"><label for="sim-level">League level</label><select id="sim-level" name="league_level"></select></div>`,
          field.select('subweek', 'Subweek', [{ value: '', label: 'Whole week (a–d)' }, 'a', 'b', 'c', 'd'], { value: '' }),
        ]))}
        <div class="button-group">
          <button class="btn btn-secondary" data-action="preview">Preview (no engine)</button>
          <button class="btn btn-warning" data-action="run-manual">Run simulation</button>
        </div>
        <div id="manual-progress"></div>
      </div>
      <div class="card">
        <h3>Run season (background)</h3>
        <p class="text-muted small mb-2">Simulates a week range as a background task. "All levels" runs 9→3 for each week.</p>
        ${raw(formGrid([
          field.number('rs_league_year_id', 'League year ID', { value: lyid, min: 1 }),
          `<div class="form-group"><label for="rs-level">League level</label><select id="rs-level" name="rs_level"></select></div>`,
          field.number('rs_start', 'Start week', { value: 1, min: 1 }),
          field.number('rs_end', 'End week', { value: 52, min: 1 }),
        ]))}
        <div class="button-group">
          <button class="btn btn-warning" data-action="run-season">Run single level</button>
          <button class="btn btn-danger" data-action="run-all">Run all levels</button>
        </div>
        <div id="season-progress"></div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Stamina rest</h3>
        <p class="text-muted small mb-2">Apply N rest subweeks of recovery to every rostered player at a level (e.g. the break before the postseason).</p>
        ${raw(formGrid([
          field.number('st_league_year_id', 'League year ID', { value: lyid, min: 1 }),
          `<div class="form-group"><label for="st-level">League level</label><select id="st-level" name="st_level"></select></div>`,
          field.number('st_subweeks', 'Rest subweeks', { value: 4, min: 1, max: 16 }),
          field.checkbox('st_full_reset', 'Full reset to 100'),
          field.checkbox('st_dry_run', 'Dry run', { checked: true }),
        ]))}
        <div class="button-group"><button class="btn btn-primary" data-action="stamina-rest">Apply rest</button></div>
        <pre class="result-box mt-2" id="st-result"></pre>
      </div>
      <div class="card">
        <h3>Engine config cache</h3>
        <p class="text-muted small mb-2">Changed contact odds, distance weights or other config tables? Clear caches so the next sim picks them up.</p>
        <div class="button-group"><button class="btn btn-warning" data-action="clear-cache">Clear caches</button></div>
        <pre class="result-box mt-2" id="cache-result"></pre>
      </div>
    </div>

    <div class="card danger-zone">
      <h3>Danger zone</h3>
      <div class="grid-2">
        <div>
          <h4 class="mb-1">Wipe season data</h4>
          <p class="text-muted small mb-2">Deletes all simulation results, stats, fatigue and injuries for a season. Keeps the schedule.</p>
          ${raw(formGrid([
            field.number('wipe_league_year_id', 'League year ID', { value: lyid, min: 1 }),
            `<div class="form-group"><label for="wipe-level">League level</label><select id="wipe-level" name="wipe_level"></select></div>`,
          ]))}
          <button class="btn btn-danger" data-action="wipe">Wipe season</button>
          <pre class="result-box mt-2" id="wipe-result"></pre>
        </div>
        <div>
          <h4 class="mb-1">Rollback to week</h4>
          <p class="text-muted small mb-2">Deletes all simulation output from the target week onward (results, stats, finances, injuries, waivers, FA auctions).</p>
          ${raw(formGrid([
            field.number('rb_league_year_id', 'League year ID', { value: lyid, min: 1 }),
            field.number('rb_week', 'Target week', { value: 1, min: 1 }),
          ]))}
          <button class="btn btn-danger" data-action="rollback">Rollback</button>
          <pre class="result-box mt-2" id="rb-result"></pre>
        </div>
      </div>
    </div>`);

  levelSelect(q(el, '#sim-level'), { levels: SIM_LEVELS, allowAll: true, remember: 'simulate' });
  levelSelect(q(el, '#rs-level'), { levels: ALL_LEVELS, value: 9 });
  levelSelect(q(el, '#st-level'), { levels: SIM_LEVELS, value: 9 });
  levelSelect(q(el, '#wipe-level'), { levels: ALL_LEVELS, allowAll: true });

  const simProgress = progressWidget(q(el, '#sim-progress'));
  const manualProgress = progressWidget(q(el, '#manual-progress'));
  const seasonProgress = progressWidget(q(el, '#season-progress'));

  function renderState(ts) {
    const stateEl = q(el, '#sim-state');
    const flagsEl = q(el, '#sim-flags');
    const btnEl = q(el, '#sim-buttons');
    if (!ts) { setHtml(stateEl, '<span class="text-muted">No timestamp</span>'); setHtml(btnEl, ''); return; }
    const flags = subweekFlagsFromTs(ts);
    setHtml(stateEl, raw(`${phaseBadge(ts.Phase)} <span class="badge badge-secondary">Week ${ts.Week ?? '--'} / ${ts.TotalWeeks ?? '--'}</span>${ts.RunGames ? ' <span class="badge badge-running">Simulating</span>' : ''}`));
    setHtml(flagsEl, raw(`${subweekPips(flags, { size: 'lg' })} <span class="text-muted small">League year ${ts.LeagueYearID ?? '--'} · Season ${ts.Season ?? '--'}</span>`));
    const b = [];
    if (ts.Phase === 'REGULAR_SEASON' || ts.Phase === 'PLAYOFFS') {
      const pending = ['a', 'b', 'c', 'd'].filter(k => !flags[k]);
      if (!ts.RunGames) {
        pending.forEach(k => b.push(`<button class="btn btn-warning" data-action="sim-sub" data-sw="${k}">Sim subweek ${k.toUpperCase()}</button>`));
        if (pending.length > 1) b.push('<button class="btn btn-warning" data-action="sim-rest">Sim all remaining</button>');
      }
      if (!pending.length) b.push(`<button class="btn btn-primary" data-action="advance">Advance to week ${(ts.Week || 0) + 1}</button>`);
      if (pending.length < 4) b.push('<button class="btn btn-secondary" data-action="reset-week">Reset week games</button>');
      if (ts.RunGames) b.push('<button class="btn btn-danger" data-action="clear-rg">Clear stuck RunGames flag</button>');
      if ((ts.AvailableActions || []).includes('end_season')) b.push('<a class="btn btn-danger" href="#/season/phase">End season →</a>');
    } else {
      b.push('<a class="btn btn-secondary" href="#/season/phase">Phase & Week →</a>');
      b.push('<a class="btn btn-secondary" href="#/season/checklist">Offseason checklist →</a>');
    }
    setHtml(btnEl, raw(b.join('') || '<span class="text-muted">No simulation actions available.</span>'));
    // keep manual form in sync
    const wk = q(el, '[name="season_week"]');
    if (wk && !wk.dataset.touched && ts.Week) wk.value = ts.Week;
    const ly = q(el, '[name="league_year_id"]');
    if (ly && !ly.dataset.touched && ts.LeagueYearID) ly.value = ts.LeagueYearID;
  }
  store.watch('ts', renderState, ctx.signal);
  on(el, 'input', (e) => { if (e.target.name) e.target.dataset.touched = '1'; }, ctx.signal);

  const after = async () => { await refreshTimestamp(); refreshSummary(); };

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    const ts = store.get().ts || {};
    try {
      if (a === 'sim-sub') {
        const sw = btn.dataset.sw;
        await runTracked({ el: q(el, '#sim-progress'), widget: simProgress, label: `Simulating week ${ts.Week} subweek ${sw.toUpperCase()}…`, signal: ctx.signal,
          start: () => api.post(v1('/games/simulate-subweek'), { league_year_id: ts.LeagueYearID, season_week: ts.Week, subweek: sw }),
          onDone: (r) => { const n = r && r.subweeks && r.subweeks[sw] ? r.subweeks[sw].length : 0; toast.success(`Subweek ${sw.toUpperCase()}: ${n} game(s) simulated`); } });
        await after();
      } else if (a === 'sim-rest') {
        await runTracked({ el: q(el, '#sim-progress'), widget: simProgress, label: `Simulating remaining subweeks of week ${ts.Week}…`, signal: ctx.signal,
          start: () => api.post(v1('/games/simulate-week'), { league_year_id: ts.LeagueYearID, season_week: ts.Week }) });
        await after();
      } else if (a === 'advance') {
        if (!await confirm({ title: `Advance to week ${(ts.Week || 0) + 1}?`, message: 'Runs weekly books, injury tick, waiver expiry, FA phase advance and listed positions.' })) return;
        await runTracked({ el: q(el, '#sim-progress'), widget: simProgress, label: 'Advancing week…', signal: ctx.signal, start: () => api.post(v1('/games/advance-week')) });
        await after();
      } else if (a === 'reset-week') {
        if (!await confirm({ title: 'Reset week games?', danger: true, message: 'Clears the subweek completion flags for the current week so games can be re-simulated.' })) return;
        await runTracked({ el: q(el, '#sim-progress'), widget: simProgress, label: 'Resetting week…', signal: ctx.signal, start: () => api.post(v1('/games/reset-week')) });
        await after();
      } else if (a === 'clear-rg') {
        if (!await confirm({ title: 'Clear RunGames flag?', danger: true, message: 'Only if no simulation is actually running.' })) return;
        await api.post(adm('/sim/clear-run-games'));
        toast.success('Flag cleared');
        await after();
      } else if (a === 'preview' || a === 'run-manual') {
        const f = readForm(q(el, '.grid-2 .card'));
        const body = { league_year_id: f.league_year_id, season_week: f.season_week };
        if (f.league_level) body.league_level = f.league_level;
        if (a === 'preview') {
          await runTracked({ el: q(el, '#manual-progress'), widget: manualProgress, label: 'Building payloads…', signal: ctx.signal,
            start: () => api.get(v1(`/games/simulate-week/${body.league_year_id}/${body.season_week}`), { params: body.league_level ? { league_level: body.league_level } : undefined }) });
        } else {
          if (!await confirm({ title: 'Run simulation?', message: `Week ${body.season_week}${f.subweek ? ` subweek ${f.subweek}` : ''}, level ${body.league_level || 'all'}, league year ${body.league_year_id}.` })) return;
          const url = f.subweek ? v1('/games/simulate-subweek') : v1('/games/simulate-week');
          if (f.subweek) body.subweek = f.subweek;
          await runTracked({ el: q(el, '#manual-progress'), widget: manualProgress, label: 'Simulating…', signal: ctx.signal, start: () => api.post(url, body) });
          await after();
        }
      } else if (a === 'run-season' || a === 'run-all') {
        const f = readForm(el);
        const all = a === 'run-all';
        const weeks = f.rs_end - f.rs_start + 1;
        if (!await confirm({ title: all ? 'Run ALL levels?' : `Run level ${f.rs_level}?`, danger: all,
          message: `Weeks ${f.rs_start}–${f.rs_end} (${weeks} week(s)${all ? ' × 7 levels' : ''}) for league year ${f.rs_league_year_id}. This runs in the background and may take a long time.` })) return;
        const body = { league_year_id: f.rs_league_year_id, start_week: f.rs_start, end_week: f.rs_end };
        if (!all) body.league_level = f.rs_level;
        await runTracked({ el: q(el, '#season-progress'), widget: seasonProgress, label: all ? 'Running all levels…' : `Running level ${f.rs_level}…`, signal: ctx.signal,
          start: () => api.post(v1(all ? '/games/run-season-all' : '/games/run-season'), body) });
        await after();
      } else if (a === 'stamina-rest') {
        const f = readForm(el);
        const body = { league_year_id: f.st_league_year_id, league_level: f.st_level, subweeks: f.st_subweeks, full_reset: f.st_full_reset, dry_run: f.st_dry_run };
        if (!f.st_dry_run && !await confirm({ title: 'Apply stamina rest?', message: `${f.st_full_reset ? 'Reset everyone to 100' : `${f.st_subweeks} rest subweek(s)`} at level ${f.st_level}.` })) return;
        const r = await api.post(v1('/games/stamina-rest'), body);
        q(el, '#st-result').textContent = json(r);
      } else if (a === 'clear-cache') {
        const r = await api.post(adm('/clear-caches'));
        q(el, '#cache-result').textContent = json(r);
        toast.success('Caches cleared');
      } else if (a === 'wipe') {
        const f = readForm(el);
        if (!await confirm({ title: 'Wipe season data?', danger: true, typeToConfirm: 'WIPE', confirmLabel: 'Wipe',
          message: `League year ${f.wipe_league_year_id}, level ${f.wipe_level || 'ALL'}. Deletes results, stats, fatigue and injuries. The schedule is kept.` })) return;
        const body = { league_year_id: f.wipe_league_year_id };
        if (f.wipe_level) body.league_level = f.wipe_level;
        const r = await api.post(v1('/games/wipe-season'), body);
        q(el, '#wipe-result').textContent = json(r);
        await after();
      } else if (a === 'rollback') {
        const f = readForm(el);
        if (!await confirm({ title: `Rollback to week ${f.rb_week}?`, danger: true, typeToConfirm: 'ROLLBACK', confirmLabel: 'Rollback',
          message: `Deletes ALL simulation data from week ${f.rb_week} onward for league year ${f.rb_league_year_id}.` })) return;
        const r = await api.post(v1('/games/rollback-to-week'), { league_year_id: f.rb_league_year_id, target_week: f.rb_week });
        q(el, '#rb-result').textContent = json(r);
        await after();
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      // toast already shown by api layer
    }
  }, ctx.signal);
}
