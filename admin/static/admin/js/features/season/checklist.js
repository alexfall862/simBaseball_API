// features/season/checklist.js — ordered offseason rollover steps (+ season archive).

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { json } from '../../core/format.js';
import { phaseBadge, badge } from './_shared.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { refreshTimestamp, refreshSummary } from '../../main.js';

const STEP_LINKS = {
  world_series: { href: '#/season/playoffs', label: 'Playoffs tab' },
  end_season: { href: '#/season/phase', label: 'Phase & Week → End season' },
  archive_season: { scroll: 'card-archive', label: 'Season archive (below)' },
  schedule: { href: '#/season/schedule', label: 'Schedule tab' },
  start_new_season: { href: '#/season/phase', label: 'Phase & Week → Start new season' },
  free_agency: { href: '#/market/fa', label: 'Market → FA Auction' },
  draft: { href: '#/market/draft', label: 'Market → Draft' },
  recruiting: { href: '#/market/recruiting', label: 'Market → Recruiting' },
};

function stepStatus(s) {
  if (s.not_built) return badge('not built', 'danger');
  if (s.done === true) return badge('done', 'success');
  if (s.manual) return badge('manual', 'warning');
  if (s.done === false) return badge('pending', 'pending');
  return badge('unknown', 'secondary');
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Offseason checklist</h3><p class="card-sub text-muted">Ordered rollover steps for the league year that is ending. Work top to bottom. Steps marked manual have no completion signal. Full procedure: docs/OFFSEASON_RUNBOOK.md.</p></div>
        <div class="row"><span id="oc-phase"></span><select id="oc-ly" title="League year that is ending"></select><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
      </div>
      <div class="text-muted small mb-2" id="oc-summary"></div>
      <div class="table-container"><table class="data-table"><thead><tr><th style="width:36px">#</th><th style="width:90px">Status</th><th>Step</th><th>Detail</th><th style="width:220px">Action</th></tr></thead><tbody id="oc-body"><tr><td colspan="5" class="text-muted tbl-state">Loading…</td></tr></tbody></table></div>
      <div id="oc-progress"></div>
    </div>
    <div class="card danger-zone" id="card-archive">
      <h3>Season archive</h3>
      <p class="text-muted small mb-2">Deletes a finished season's ephemeral data (per-game lines, play-by-play, substitutions, fatigue, ledger detail). Keeps accumulated stats, standings and schedules. Runs as a job (4–5 min). Never run before End Season.</p>
      ${raw(formGrid([field.number('archive_league_year_id', 'League year ID', { min: 1 }), field.checkbox('archive_dry_run', 'Dry run (count only)', { checked: true })]))}
      <button class="btn btn-danger" data-action="archive">Archive season</button>
      <div id="archive-progress"></div>
    </div>`);

  const progress = progressWidget(q(el, '#oc-progress'));
  const archiveProgress = progressWidget(q(el, '#archive-progress'));
  const sel = q(el, '#oc-ly');
  let data = null;

  async function load() {
    const body = q(el, '#oc-body');
    body.innerHTML = '<tr><td colspan="5" class="text-muted tbl-state">Loading…</td></tr>';
    try {
      data = await api.get(adm('/offseason/checklist'), { params: { league_year_id: sel.value || undefined }, signal: ctx.signal });
    } catch (e) {
      body.innerHTML = `<tr><td colspan="5" class="text-danger tbl-state">${html`${e.message}`}</td></tr>`;
      return;
    }
    if (Array.isArray(data.league_years)) {
      const want = data.league_years.map(ly => String(ly.id)).join(',');
      const have = Array.from(sel.options).map(o => o.value).join(',');
      if (want !== have) setHtml(sel, raw(data.league_years.map(ly => `<option value="${ly.id}">${ly.league_year} (id ${ly.id})</option>`).join('')));
      sel.value = String(data.league_year_id);
    }
    setHtml(q(el, '#oc-phase'), raw(phaseBadge(data.phase)));
    const ts = data.timestamp || {};
    const done = (data.steps || []).filter(s => s.done === true).length;
    q(el, '#oc-summary').textContent =
      `Ending ${data.league_year} (league_year_id ${data.league_year_id}); ${data.next_league_year_id ? `next league_year_id = ${data.next_league_year_id} (${data.next_league_year})` : `league year ${data.next_league_year} not created yet`}. ` +
      `Timestamp: Season ${ts.Season ?? '--'}, Week ${ts.Week ?? '--'}, offseason=${ts.IsOffSeason}, fa_locked=${ts.IsFreeAgencyLocked}, fa_round=${ts.FreeAgencyRound}, draft=${ts.IsDraftTime}, recruiting_locked=${ts.IsRecruitingLocked}. ${done}/${(data.steps || []).length} steps done.`;
    const arch = q(el, '[name="archive_league_year_id"]');
    if (arch && !arch.value && data.league_year_id) arch.value = data.league_year_id;

    body.innerHTML = (data.steps || []).map(s => {
      let action = '<span class="text-muted">—</span>';
      if (s.action) {
        action = s.action.blocked
          ? `<span class="text-muted small" title="${html`${s.action.blocked}`}">blocked: ${html`${s.action.blocked}`}</span>`
          : `<button class="btn btn-sm ${s.action.confirm ? 'btn-danger' : 'btn-primary'}" data-action="run-step" data-key="${html`${s.key}`}">${html`${s.action.label || 'Run'}`}</button>`;
      } else if (STEP_LINKS[s.key]) {
        const l = STEP_LINKS[s.key];
        action = l.href ? `<a class="btn btn-sm btn-ghost" href="${l.href}">${l.label}</a>` : `<button class="btn btn-sm btn-ghost" data-action="scroll" data-card="${l.scroll}">${l.label}</button>`;
      } else if (s.manual) {
        action = '<span class="text-muted small">confirm by hand</span>';
      }
      return `<tr class="${s.done === true ? 'row-success' : ''}"><td>${s.order}</td><td>${stepStatus(s)}</td><td><strong>${html`${s.title}`}</strong></td><td class="small">${html`${s.detail || ''}`}</td><td>${action}</td></tr>`;
    }).join('');
  }

  on(sel, 'change', load, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') { await load(); return; }
      if (a === 'scroll') { const c = q(el, `#${btn.dataset.card}`); if (c) c.scrollIntoView({ behavior: 'smooth' }); return; }
      if (a === 'run-step') {
        const step = (data && data.steps || []).find(s => s.key === btn.dataset.key);
        if (!step || !step.action || step.action.blocked) return;
        const act = step.action;
        if (!await confirm({ title: `Run step ${step.order}: ${step.title}?`, danger: !!act.confirm,
          message: act.confirm ? 'This creates the next league year (league_years row + game_weeks) and CANNOT be re-run.' : '',
          detail: `${act.method || 'POST'} ${act.url}\n${json(act.body || {})}` })) return;
        await runTracked({ el: q(el, '#oc-progress'), widget: progress, label: `Step ${step.order}: ${act.label || 'Run'}…`, signal: ctx.signal,
          start: () => api.action(act, { admin: true }) });
        toast.success(`Step ${step.order} finished`);
        await load(); await refreshTimestamp(); refreshSummary();
      } else if (a === 'archive') {
        const f = readForm(q(el, '#card-archive'));
        if (!f.archive_league_year_id) { toast.warn('League year ID is required'); return; }
        if (!f.archive_dry_run && !await confirm({ title: 'Archive season?', danger: true, typeToConfirm: 'ARCHIVE', confirmLabel: 'Archive',
          message: `League year ID ${f.archive_league_year_id}. Irreversible. Make sure End Season has already run for this year.` })) return;
        await runTracked({ el: q(el, '#archive-progress'), widget: archiveProgress, label: f.archive_dry_run ? 'Counting rows (dry run)…' : 'Archiving (job)…', signal: ctx.signal,
          start: () => api.post(adm('/jobs/run'), { job_type: 'archive_season', params: { league_year_id: f.archive_league_year_id, dry_run: f.archive_dry_run } }) });
        await load();
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await load();
}
