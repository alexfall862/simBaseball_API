// features/jobs/scheduled.js — scheduled job definitions + scheduler switch.

import { api, adm } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { html, raw, setHtml, delegate, on, q, qa } from '../../core/html.js';
import { store } from '../../core/store.js';
import { fmtDate, relTime, json } from '../../core/format.js';
import { PHASES } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { badge, statusBadge, boolBadge, emptyState } from '../../ui/badge.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { openModal, confirm, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { loadTypes, typeByName, paramFields, readParams, scheduleLabel, PRESETS } from './_shared.js';
import { refreshSummary } from '../../main.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Scheduler</h3><p class="card-sub text-muted">One leader process runs due jobs (MySQL lock election). The switch is <code>timestamp_state.run_cron</code>; manual "Run now" works even when it is off.</p></div>
        <div class="row" id="sch-status"></div>
      </div>
      <div class="grid-4" id="sch-kpis"></div>
    </div>
    <div class="card">
      <div class="card-head">
        <h3>Scheduled jobs</h3>
        <div class="row">
          <button class="btn btn-sm btn-secondary" data-action="presets">Add preset…</button>
          <button class="btn btn-sm btn-primary" data-action="new">New job</button>
          <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div id="jobs-table"></div>
      <div id="jobs-progress"></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Run any job once</h3><p class="card-sub text-muted">Fire a job type right now without saving a schedule.</p></div>
      <div class="row mb-2"><select id="adhoc-type" class="select-lg"></select><button class="btn btn-sm btn-secondary" data-action="adhoc-preview">Preview</button><button class="btn btn-sm btn-warning" data-action="adhoc-run">Run now</button></div>
      <div id="adhoc-params" class="form-grid"></div>
      <pre class="result-box" id="adhoc-preview-box"></pre>
      <div id="adhoc-progress"></div>
    </div>`);

  const { types, defaultTimezone } = await loadTypes();
  const progress = progressWidget(q(el, '#jobs-progress'));
  const adhocProgress = progressWidget(q(el, '#adhoc-progress'));

  const table = dataTable(q(el, '#jobs-table'), {
    rowKey: 'id', emptyText: 'No scheduled jobs yet. Add a preset or create one.',
    columns: [
      { key: 'enabled', title: '', html: true, width: '40px', render: r => `<input type="checkbox" data-action="toggle" data-id="${r.id}" ${r.enabled ? 'checked' : ''} title="${r.enabled ? 'Enabled' : 'Disabled'}" />` },
      { key: 'name', title: 'Name', html: true, render: r => `<strong>${html`${r.name}`}</strong><div class="text-muted small mono">${html`${r.job_type}`}</div>` },
      { key: 'schedule', title: 'Schedule', render: r => scheduleLabel(r) },
      { key: 'next_run_at', title: 'Next run', html: true, render: r => r.enabled && r.next_run_at ? `<span title="${fmtDate(r.next_run_at)}">${relTime(r.next_run_at)}</span><div class="text-muted small">${fmtDate(r.next_run_at)}</div>` : '<span class="text-muted">—</span>' },
      { key: 'last_status', title: 'Last', html: true, render: r => r.last_status ? `${statusBadge(r.last_status)}<div class="text-muted small">${relTime(r.last_run_at)} · ${r.runs_count} run(s)</div>` : '<span class="text-muted">never</span>' },
      { key: 'guards', title: 'Guards', html: true, render: r => guardChips(r.guards) },
      { key: '_a', title: '', html: true, render: r => `<div class="row nowrap">
          <button class="btn btn-xs btn-warning" data-action="run" data-id="${r.id}">Run now</button>
          <button class="btn btn-xs btn-ghost" data-action="preview" data-id="${r.id}">Preview</button>
          <button class="btn btn-xs btn-secondary" data-action="edit" data-id="${r.id}">Edit</button>
          <a class="btn btn-xs btn-ghost" href="#/jobs/runs?job_id=${r.id}">Runs</a>
          <button class="btn btn-xs btn-danger" data-action="delete" data-id="${r.id}">✕</button></div>` },
    ],
  });

  function guardChips(g) {
    if (!g) return '';
    const bits = [];
    if (g.require_phase && g.require_phase.length) bits.push(badge(g.require_phase.map(p => (PHASES[p] && PHASES[p].label) || p).join('/'), 'info'));
    if (g.skip_if_run_games) bits.push(badge('skip if RunGames', 'secondary'));
    if (g.pause_on_failure) bits.push(badge('pause on fail', 'secondary'));
    if (g.max_runs) bits.push(badge(`max ${g.max_runs}`, 'secondary'));
    return `<div class="row" style="gap:4px">${bits.join('')}</div>`;
  }

  let jobs = [];
  async function load() {
    table.setLoading();
    try {
      const d = await api.get(adm('/jobs'), { signal: ctx.signal });
      jobs = d.jobs || [];
      table.setRows(jobs);
    } catch (e) { table.setError(e.message); }
    renderStatus(store.get().summary && store.get().summary.scheduler);
  }

  function renderStatus(s) {
    const st = q(el, '#sch-status');
    if (!s) { setHtml(st, '<span class="text-muted">status unavailable</span>'); return; }
    setHtml(st, raw(`
      <label class="checkbox-label"><input type="checkbox" data-action="sched-toggle" ${s.enabled ? 'checked' : ''} /> <span>Scheduler ${s.enabled ? 'on' : 'off'}</span></label>
      ${s.leader_alive ? badge(`leader ${s.leader}`, 'success') : badge('no runner alive', 'warning')}`));
    setHtml(q(el, '#sch-kpis'), raw(`
      <div class="stat-card"><div class="stat-label">Running</div><div class="stat-value">${s.running}</div><div class="stat-sub">${s.queued} queued</div></div>
      <div class="stat-card ${s.failed_24h ? 'stat-danger' : ''}"><div class="stat-label">Failed (24h)</div><div class="stat-value">${s.failed_24h}</div><div class="stat-sub"><a href="#/jobs/runs?status=failed">history</a></div></div>
      <div class="stat-card"><div class="stat-label">Next fire</div><div class="stat-value" style="font-size:1.1rem">${s.next_run ? html`${s.next_run.name}` : '—'}</div><div class="stat-sub">${s.next_run ? `${s.next_run.in} · ${fmtDate(s.next_run.at)}` : 'nothing scheduled'}</div></div>
      <div class="stat-card"><div class="stat-label">Runner</div><div class="stat-value" style="font-size:1.1rem">${s.leader_alive ? 'alive' : 'offline'}</div><div class="stat-sub">tick ${s.tick_s}s · ${s.workers} workers · last ${relTime(s.last_tick_at)}</div></div>`));
  }
  store.watch('summary', (s) => renderStatus(s && s.scheduler), ctx.signal);
  bus.on('jobs:changed', load, ctx.signal);

  // ---- ad-hoc runner ----
  const adhocSel = q(el, '#adhoc-type');
  setHtml(adhocSel, raw(groupedTypeOptions(types)));
  const renderAdhocParams = () => { const spec = typeByName(adhocSel.value); setHtml(q(el, '#adhoc-params'), raw(spec ? paramFields(spec).join('') : '')); q(el, '#adhoc-preview-box').textContent = spec ? spec.description : ''; };
  on(adhocSel, 'change', renderAdhocParams, ctx.signal);
  renderAdhocParams();

  // ---- actions ----
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    const id = btn.dataset.id ? Number(btn.dataset.id) : null;
    const job = id ? jobs.find(j => j.id === id) : null;
    try {
      if (a === 'refresh') { await load(); await refreshSummary(); return; }
      if (a === 'new') { await openJobEditor(null); return; }
      if (a === 'edit' && job) { await openJobEditor(job); return; }
      if (a === 'presets') { await openPresets(); return; }
      if (a === 'delete' && job) {
        if (!await confirm({ title: `Delete "${job.name}"?`, danger: true, message: 'Run history is kept.' })) return;
        await api.del(adm(`/jobs/${id}`)); toast.success('Deleted'); await load(); return;
      }
      if (a === 'run' && job) {
        if (job.job_type.match(/end_season|archive|start_new_season|init_next|fa_end/) && !await confirm({ title: `Run "${job.name}" now?`, danger: true, message: 'This job type is irreversible.' })) return;
        await runTracked({ el: q(el, '#jobs-progress'), widget: progress, label: `Running ${job.name}…`, signal: ctx.signal, start: () => api.post(adm(`/jobs/${id}/run-now`)) });
        await load(); refreshSummary(); return;
      }
      if (a === 'preview' && job) {
        const p = await api.post(adm('/jobs/preview'), { job_type: job.job_type, params: job.params, schedule_kind: job.schedule_kind, cron_expr: job.cron_expr, interval_s: job.interval_s, run_at: job.run_at, timezone: job.timezone });
        showResult(`Preview: ${job.name}`, p); return;
      }
      if (a === 'adhoc-preview') {
        const spec = typeByName(adhocSel.value);
        const p = await api.post(adm('/jobs/preview'), { job_type: spec.job_type, params: readParams(el, spec) });
        q(el, '#adhoc-preview-box').textContent = json(p); return;
      }
      if (a === 'adhoc-run') {
        const spec = typeByName(adhocSel.value);
        const params = readParams(el, spec);
        if (spec.dangerous && !await confirm({ title: `Run ${spec.title}?`, danger: true, message: spec.description, detail: json(params) })) return;
        await runTracked({ el: q(el, '#adhoc-progress'), widget: adhocProgress, label: `Running ${spec.title}…`, signal: ctx.signal, start: () => api.post(adm('/jobs/run'), { job_type: spec.job_type, params }) });
        refreshSummary(); bus.emit('jobs:changed'); return;
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  delegate(el, 'change', '[data-action="toggle"]', async (e, cb) => {
    const id = Number(cb.dataset.id);
    try { await api.post(adm(`/jobs/${id}/toggle`), { enabled: cb.checked }); toast.success(cb.checked ? 'Enabled' : 'Disabled'); await load(); refreshSummary(); }
    catch (_) { cb.checked = !cb.checked; }
  }, ctx.signal);
  delegate(el, 'change', '[data-action="sched-toggle"]', async (e, cb) => {
    try { await api.post(adm('/scheduler/toggle'), { enabled: cb.checked }); toast.success(cb.checked ? 'Scheduler enabled' : 'Scheduler disabled'); await refreshSummary(); }
    catch (_) { cb.checked = !cb.checked; }
  }, ctx.signal);

  // ---- editor modal ----
  async function openJobEditor(job, preset = null) {
    const init = job || preset || { name: '', job_type: types[0].job_type, schedule_kind: 'cron', cron_expr: '0 6 * * *', timezone: defaultTimezone, params: {}, guards: { skip_if_run_games: true, pause_on_failure: true }, enabled: true };
    const body = document.createElement('div');
    const h = openModal({ title: job ? `Edit job #${job.id}` : 'New scheduled job', body, size: 'lg', actions: [
      { label: 'Cancel', cls: 'btn-secondary', onClick: hh => hh.close() },
      { label: 'Preview', cls: 'btn-ghost', onClick: async () => { const d = collect(); if (!d) return; const p = await api.post(adm('/jobs/preview'), d); q(body, '#ed-preview').textContent = json(p); } },
      { label: job ? 'Save' : 'Create', cls: 'btn-primary', onClick: async (hh) => {
        const d = collect(); if (!d) return;
        if (job) await api.put(adm(`/jobs/${job.id}`), d); else await api.post(adm('/jobs'), d);
        toast.success(job ? 'Saved' : 'Created'); hh.close(); await load(); refreshSummary();
      } },
    ] });

    function render() {
      const spec = typeByName(q(body, '[name="job_type"]') ? q(body, '[name="job_type"]').value : init.job_type) || typeByName(init.job_type);
      const kind = q(body, '[name="schedule_kind"]') ? q(body, '[name="schedule_kind"]').value : init.schedule_kind;
      const cur = collectRaw();
      body.innerHTML = `
        ${formGrid([
          field.text('name', 'Name', { value: cur.name ?? init.name ?? '' }),
          `<div class="form-group"><label for="f-job_type">Job type</label><select id="f-job_type" name="job_type">${groupedTypeOptions(types, cur.job_type || init.job_type)}</select></div>`,
          field.select('schedule_kind', 'Schedule', [{ value: 'cron', label: 'Cron' }, { value: 'interval', label: 'Interval' }, { value: 'once', label: 'Once' }, { value: 'manual', label: 'Manual only' }], { value: kind }),
          field.text('timezone', 'Timezone', { value: cur.timezone || init.timezone || defaultTimezone }),
        ])}
        <p class="text-muted small mb-2" id="ed-desc">${html`${spec ? spec.description : ''}`}</p>
        ${kind === 'cron' ? formGrid([field.text('cron_expr', 'Cron expression (min hour dom mon dow)', { value: cur.cron_expr || init.cron_expr || '0 6 * * *', help: 'e.g. "0 6 * * *" daily 06:00 · "0 6 * * 1-5" weekdays · "*/30 * * * *" every 30 min' })]) : ''}
        ${kind === 'interval' ? formGrid([field.number('interval_s', 'Interval (seconds)', { value: cur.interval_s || init.interval_s || 86400, min: 60, help: '3600 = hourly, 86400 = daily' })]) : ''}
        ${kind === 'once' ? formGrid([field.datetime('run_at', 'Run at (your local time)', { value: cur.run_at || toLocalInput(init.run_at) })]) : ''}
        <h4 class="mb-1">Parameters</h4>
        <div class="form-grid" id="ed-params">${spec ? paramFields(spec, cur.params || init.params || {}).join('') : ''}</div>
        <h4 class="mb-1">Guards</h4>
        ${formGrid([
          field.select('g_require_phase', 'Require phase', Object.entries(PHASES).map(([k, v]) => ({ value: k, label: v.label })), { value: (cur.guards && cur.guards.require_phase) || (init.guards && init.guards.require_phase) || (spec && spec.phases) || [], multiple: true, help: 'Skip the run when the league is not in one of these phases. Empty = any.' }),
          field.checkbox('g_skip_if_run_games', 'Skip if RunGames flag is set', { checked: (cur.guards ? cur.guards.skip_if_run_games : (init.guards ? init.guards.skip_if_run_games : true)) !== false }),
          field.checkbox('g_pause_on_failure', 'Disable the job after a failed run', { checked: (cur.guards ? cur.guards.pause_on_failure : (init.guards ? init.guards.pause_on_failure : true)) !== false }),
          field.number('g_max_runs', 'Max runs (blank = unlimited)', { value: (cur.guards && cur.guards.max_runs) || (init.guards && init.guards.max_runs) || '' }),
          field.checkbox('enabled', 'Enabled', { checked: cur.enabled !== undefined ? cur.enabled : init.enabled !== false }),
        ])}
        <pre class="result-box" id="ed-preview"></pre>`;
      q(body, '[name="job_type"]').addEventListener('change', render);
      q(body, '[name="schedule_kind"]').addEventListener('change', render);
    }
    function collectRaw() {
      if (!body.querySelector('[name="name"]')) return {};
      const f = readForm(body);
      const spec = typeByName(f.job_type);
      return { name: f.name, job_type: f.job_type, schedule_kind: f.schedule_kind, timezone: f.timezone, cron_expr: f.cron_expr, interval_s: f.interval_s,
        run_at: f.run_at, params: spec ? readParams(body, spec) : {}, enabled: f.enabled,
        guards: { require_phase: f.g_require_phase || [], skip_if_run_games: f.g_skip_if_run_games, pause_on_failure: f.g_pause_on_failure, max_runs: f.g_max_runs || null } };
    }
    function collect() {
      const d = collectRaw();
      if (!d.name) { toast.warn('Name is required'); return null; }
      if (d.schedule_kind === 'cron' && !d.cron_expr) { toast.warn('Cron expression is required'); return null; }
      if (d.schedule_kind === 'once' && d.run_at) d.run_at = new Date(d.run_at).toISOString();
      return d;
    }
    render();
    void h;
  }

  async function openPresets() {
    const body = document.createElement('div');
    body.className = 'action-list';
    body.innerHTML = PRESETS.map((p, i) => `<div class="action-item"><div><div class="title">${html`${p.name}`} <span class="text-muted mono small">${html`${p.job_type}`}</span></div><div class="meta">${html`${p.desc}`}</div></div><button class="btn btn-sm btn-primary" data-preset="${i}">Use</button></div>`).join('');
    const h = openModal({ title: 'Presets', body, size: 'md', actions: [{ label: 'Close', cls: 'btn-secondary' }] });
    body.addEventListener('click', (e) => {
      const b = e.target.closest('[data-preset]'); if (!b) return;
      const p = PRESETS[Number(b.dataset.preset)];
      const spec = typeByName(p.job_type);
      h.close();
      openJobEditor(null, { ...p, timezone: defaultTimezone, enabled: true, guards: { require_phase: spec ? spec.phases : null, skip_if_run_games: true, pause_on_failure: true } });
    });
  }

  await load();
  if (ctx.params.new === '1') openJobEditor(null);
}

function groupedTypeOptions(types, selected = null) {
  const groups = {};
  for (const t of types) (groups[t.group] = groups[t.group] || []).push(t);
  return Object.entries(groups).map(([g, list]) => `<optgroup label="${g}">${list.map(t => `<option value="${t.job_type}" ${t.job_type === selected ? 'selected' : ''}>${html`${t.title}`}</option>`).join('')}</optgroup>`).join('');
}

function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
