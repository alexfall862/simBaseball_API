// features/season/phase.js — phase & week control (port of legacy #section-timestamp minus the checklist).

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { json } from '../../core/format.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { ACTION_CONFIG, phaseBadge, subweekPips, subweekFlagsFromTs } from './_shared.js';
import { kvTable } from '../../ui/table.js';
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
      <div class="card-head"><h3>Simulation state</h3><div class="row" id="ph-state"></div></div>
      <div class="grid-3" id="ph-kpis"></div>
      <div id="ph-kv"></div>
    </div>
    <div class="card">
      <h3>Actions available now</h3>
      <div class="button-group" id="ph-actions"></div>
      <div id="ph-progress"></div>
    </div>
    <div class="grid-2">
      <div class="card" id="card-set-week">
        <h3>Jump to week</h3>
        ${raw(formGrid([field.number('week', 'Week number', { value: 1, min: 0 })]))}
        <button class="btn btn-primary" data-action="set-week">Set week</button>
      </div>
      <div class="card" id="card-set-phase">
        <h3>Phase override</h3>
        <p class="text-muted small mb-2">Directly set phase flags. Blank = no change. Use with caution.</p>
        ${raw(formGrid([
          field.select('is_offseason', 'Is offseason', [{ value: '', label: '— no change —' }, { value: 'true', label: 'true' }, { value: 'false', label: 'false' }]),
          field.select('is_free_agency_locked', 'FA locked', [{ value: '', label: '— no change —' }, { value: 'true', label: 'true' }, { value: 'false', label: 'false' }]),
          field.select('is_draft_time', 'Draft time', [{ value: '', label: '— no change —' }, { value: 'true', label: 'true' }, { value: 'false', label: 'false' }]),
          field.select('is_recruiting_locked', 'Recruiting locked', [{ value: '', label: '— no change —' }, { value: 'true', label: 'true' }, { value: 'false', label: 'false' }]),
          field.number('free_agency_round', 'FA round', { placeholder: '— no change —', min: 0 }),
        ]))}
        <button class="btn btn-danger" data-action="set-phase">Apply override</button>
      </div>
    </div>
    <div class="grid-2">
      <div class="card danger-zone" id="card-end-season">
        <h3>End regular season</h3>
        <p class="text-muted small mb-2">One-shot rollover: contracts, graduation/retirements, draft pool, training camp, progression, new amateur classes, Y+1 tables, calendar → offseason. Runs as a job (2–3 min) so it survives the request timeout. Refuses unless the MLB World Series is complete.</p>
        ${raw(formGrid([field.number('eos_league_year_id', 'League year ID (ending)', { value: lyid, min: 1 }), field.checkbox('eos_force', 'Force (skip World Series check)')]))}
        <button class="btn btn-danger" data-action="end-season">End season</button>
        <div id="eos-progress"></div>
      </div>
      <div class="card" id="card-new-season">
        <h3>Start new season</h3>
        <p class="text-muted small mb-2">Runs year-start books, refreshes listed positions and sets week 1. Needs a generated schedule and FA/draft/recruiting closed.</p>
        ${raw(formGrid([field.number('new_league_year_id', 'New league year ID', { value: lyid + 1, min: 1 })]))}
        <button class="btn btn-primary" data-action="new-season">Start new season</button>
        <div id="nss-progress"></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <h3>Listed positions</h3>
        <p class="text-muted small mb-2">Auto-fill listed positions for all teams (mid-season or if positions weren't populated on season init).</p>
        <button class="btn btn-primary" data-action="fill-positions">Fill all listed positions</button>
        <pre class="result-box mt-2" id="lp-result"></pre>
      </div>
      <div class="card">
        <h3>Default gameplans</h3>
        <p class="text-muted small mb-2">Generate default defense, rotation and bullpen for every team at a level. Skips teams that already have one unless overwrite is checked.</p>
        ${raw(formGrid([
          `<div class="form-group"><label for="gp-level">Team level</label><select id="gp-level" name="gp_level"></select></div>`,
          field.number('gp_league_year_id', 'League year ID', { value: lyid, min: 1 }),
          field.checkbox('gp_overwrite', 'Overwrite existing'),
        ]))}
        <button class="btn btn-primary" data-action="gen-gameplans">Generate default gameplans</button>
        <pre class="result-box mt-2" id="gp-result"></pre>
      </div>
    </div>`);

  levelSelect(q(el, '#gp-level'), { levels: ALL_LEVELS.filter(l => l !== 4), value: 9 });
  const progress = progressWidget(q(el, '#ph-progress'));
  const eosProgress = progressWidget(q(el, '#eos-progress'));
  const nssProgress = progressWidget(q(el, '#nss-progress'));

  function render(ts) {
    if (!ts) { setHtml(q(el, '#ph-state'), '<span class="text-muted">No timestamp</span>'); return; }
    const flags = subweekFlagsFromTs(ts);
    const all = flags.a && flags.b && flags.c && flags.d;
    setHtml(q(el, '#ph-state'), raw(`${phaseBadge(ts.Phase)} <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>`));
    setHtml(q(el, '#ph-kpis'), raw(`
      <div class="stat-card"><div class="stat-label">Season</div><div class="stat-value">${ts.Season ?? '--'}</div><div class="stat-sub">Season ID ${ts.SeasonID ?? '--'} · league year ID ${ts.LeagueYearID ?? '--'}</div></div>
      <div class="stat-card"><div class="stat-label">Week</div><div class="stat-value">${ts.Week ?? '--'} <span class="text-muted" style="font-size:1rem">/ ${ts.TotalWeeks ?? '--'}</span></div><div class="stat-sub">${ts.RunGames ? 'Simulating…' : all ? 'All games complete' : 'Ready'}</div></div>
      <div class="stat-card"><div class="stat-label">Subweeks</div><div class="stat-value">${subweekPips(flags, { size: 'lg' })}</div><div class="stat-sub">${ts.RunGames ? '<span class="badge badge-running">RunGames set</span>' : '&nbsp;'}</div></div>`));
    setHtml(q(el, '#ph-kv'), raw(kvTable([
      ['Phase', ts.Phase], ['Offseason', ts.IsOffSeason], ['FA locked', ts.IsFreeAgencyLocked], ['FA round', ts.FreeAgencyRound],
      ['Draft time', ts.IsDraftTime], ['Recruiting locked', ts.IsRecruitingLocked], ['Recruiting synced', ts.RecruitingSynced],
      ['Run games', ts.RunGames], ['Run cron (scheduler)', ts.RunCron], ['Available actions', (ts.AvailableActions || []).join(', ')],
    ])));
    const actions = ts.AvailableActions || [];
    const buttons = actions.map(a => {
      const c = ACTION_CONFIG[a];
      if (!c) return '';
      if (c.href) return `<a class="btn ${c.cls}" href="${c.href}">${c.label}</a>`;
      if (c.card) return `<button class="btn ${c.cls}" data-action="scroll" data-card="card-${c.card}">${c.label}</button>`;
      return `<button class="btn ${c.cls}" data-action="ts-action" data-key="${a}">${c.label}</button>`;
    }).join('');
    setHtml(q(el, '#ph-actions'), raw(buttons || '<span class="text-muted">No actions available in the current state.</span>'));
    q(el, '#card-end-season').classList.toggle('is-available', actions.includes('end_season'));
    q(el, '#card-new-season').classList.toggle('is-available', actions.includes('start_new_season'));
    const wk = q(el, '[name="week"]'); if (wk && !wk.dataset.touched && ts.Week != null) wk.value = ts.Week;
    const eos = q(el, '[name="eos_league_year_id"]'); if (eos && !eos.dataset.touched && ts.LeagueYearID) eos.value = ts.LeagueYearID;
  }
  store.watch('ts', render, ctx.signal);
  el.addEventListener('input', (e) => { if (e.target.name) e.target.dataset.touched = '1'; }, { signal: ctx.signal });

  const after = async () => { await refreshTimestamp(); refreshSummary(); };

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') { await after(); return; }
      if (a === 'scroll') { const c = q(el, `#${btn.dataset.card}`); if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'start' }); c.classList.add('flash'); } return; }
      if (a === 'ts-action') {
        const c = ACTION_CONFIG[btn.dataset.key];
        if (c.confirm && !await confirm({ title: c.label, message: c.confirm, danger: !!c.danger })) return;
        await runTracked({ el: q(el, '#ph-progress'), widget: progress, label: `${c.label}…`, signal: ctx.signal, start: () => api.post(v1(c.endpoint)) });
        await after();
      } else if (a === 'set-week') {
        const f = readForm(q(el, '#card-set-week'));
        if (f.week == null) return;
        if (!await confirm({ title: `Set week to ${f.week}?`, message: 'This only changes the calendar pointer; it does not simulate or roll anything back.' })) return;
        const r = await api.post(v1('/games/set-week'), { week: f.week });
        toast.success(`Week set to ${f.week}`); void r;
        await after();
      } else if (a === 'set-phase') {
        const f = readForm(q(el, '#card-set-phase'));
        const body = {};
        for (const k of ['is_offseason', 'is_free_agency_locked', 'is_draft_time', 'is_recruiting_locked']) if (f[k] !== '') body[k] = f[k] === 'true';
        if (f.free_agency_round != null) body.free_agency_round = f.free_agency_round;
        if (!Object.keys(body).length) { toast.warn('Nothing to change'); return; }
        if (!await confirm({ title: 'Apply phase override?', danger: true, detail: json(body) })) return;
        await api.post(v1('/games/set-phase'), body);
        toast.success('Phase flags updated');
        await after();
      } else if (a === 'end-season') {
        const f = readForm(q(el, '#card-end-season'));
        if (!await confirm({ title: 'End the regular season?', danger: true, typeToConfirm: 'END SEASON', confirmLabel: 'End season',
          message: `League year ID ${f.eos_league_year_id}${f.eos_force ? ' (FORCED)' : ''}. One-shot and irreversible. Takes 2–3 minutes.` })) return;
        await runTracked({ el: q(el, '#eos-progress'), widget: eosProgress, label: 'Ending season (job)…', signal: ctx.signal,
          start: () => api.post(adm('/jobs/run'), { job_type: 'end_season', params: { league_year_id: f.eos_league_year_id, force: f.eos_force } }) });
        await after();
      } else if (a === 'new-season') {
        const f = readForm(q(el, '#card-new-season'));
        if (!await confirm({ title: 'Start the new season?', message: `New league year ID ${f.new_league_year_id}. Runs year-start financials and resets to week 1.` })) return;
        await runTracked({ el: q(el, '#nss-progress'), widget: nssProgress, label: 'Starting new season…', signal: ctx.signal,
          start: () => api.post(v1('/games/start-new-season'), { league_year_id: f.new_league_year_id }) });
        await after();
      } else if (a === 'fill-positions') {
        const r = await api.post(adm('/fill-listed-positions'));
        q(el, '#lp-result').textContent = r.ok ? `Done — ${r.total} players updated.` : json(r);
      } else if (a === 'gen-gameplans') {
        const f = readForm(el);
        const r = await api.post(adm('/generate-default-gameplans'), { team_level: f.gp_level, league_year_id: f.gp_league_year_id, overwrite: f.gp_overwrite });
        let msg = `Done — ${r.teams_processed} teams processed, ${r.teams_skipped} skipped.`;
        if (r.errors && r.errors.length) msg += `\n${r.errors.length} errors:\n` + r.errors.map(x => `  Team ${x.team_id}: ${x.message}`).join('\n');
        q(el, '#gp-result').textContent = msg;
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);
}
