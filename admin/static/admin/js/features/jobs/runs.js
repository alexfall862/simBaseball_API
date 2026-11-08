// features/jobs/runs.js — job run history with live refresh and a detail modal.

import { api, adm } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { fmtDate, relTime, fmtDuration, json } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { statusBadge, badge } from '../../ui/badge.js';
import { openModal, confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { loadTypes } from './_shared.js';

export async function mount(el, ctx) {
  const { types } = await loadTypes();
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <h3>Run history</h3>
        <div class="row">
          <select id="f-status"><option value="">Any status</option>${raw(['queued', 'running', 'succeeded', 'failed', 'skipped', 'cancelled'].map(s => `<option value="${s}">${s}</option>`).join(''))}</select>
          <select id="f-type"><option value="">Any job type</option>${raw(types.map(t => `<option value="${t.job_type}">${html`${t.title}`}</option>`).join(''))}</select>
          <select id="f-hours"><option value="">All time</option><option value="24">Last 24h</option><option value="168">Last 7d</option></select>
          <label class="checkbox-label small"><input type="checkbox" id="f-auto" checked /> auto-refresh</label>
          <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div id="runs-table"></div>
    </div>`);

  const fStatus = q(el, '#f-status'), fType = q(el, '#f-type'), fHours = q(el, '#f-hours'), fAuto = q(el, '#f-auto');
  if (ctx.params.status) fStatus.value = ctx.params.status;
  if (ctx.params.job_type) fType.value = ctx.params.job_type;
  const jobId = ctx.params.job_id ? Number(ctx.params.job_id) : null;

  const table = dataTable(q(el, '#runs-table'), {
    rowKey: 'id', emptyText: 'No runs match.', pageSize: 50,
    rowClass: r => (r.status === 'failed' ? 'row-danger' : r.status === 'running' ? 'row-warning' : ''),
    columns: [
      { key: 'id', title: '#', width: '60px' },
      { key: 'job_type', title: 'Job', html: true, render: r => `<span class="mono">${html`${r.job_type}`}</span>${r.job_id ? `<div class="text-muted small">job #${r.job_id}</div>` : ''}` },
      { key: 'trigger_kind', title: 'Trigger', html: true, render: r => badge(r.trigger_kind, r.trigger_kind === 'schedule' ? 'info' : 'secondary') },
      { key: 'status', title: 'Status', html: true, render: r => `${statusBadge(r.status)}${r.status === 'running' && r.total ? `<div class="text-muted small">${r.progress}/${r.total} ${html`${r.stage || ''}`}</div>` : ''}${r.skip_reason ? `<div class="text-muted small">${html`${r.skip_reason}`}</div>` : ''}` },
      { key: 'queued_at', title: 'Queued', render: r => relTime(r.queued_at), title_attr: r => fmtDate(r.queued_at) },
      { key: 'duration_s', title: 'Duration', render: r => (r.duration_s != null ? fmtDuration(r.duration_s) : (r.status === 'running' ? '…' : '')) },
      { key: 'error', title: 'Error', html: true, render: r => (r.error ? `<span class="text-danger small">${html`${String(r.error).slice(0, 120)}`}</span>` : '') },
      { key: '_a', title: '', html: true, render: r => `<div class="row nowrap"><button class="btn btn-xs btn-secondary" data-action="view" data-id="${r.id}">Details</button>${['queued', 'running'].includes(r.status) ? `<button class="btn btn-xs btn-danger" data-action="cancel" data-id="${r.id}">Cancel</button>` : ''}</div>` },
    ],
  });

  let timer = null;
  async function load() {
    try {
      const d = await api.get(adm('/jobs/runs'), { signal: ctx.signal, quiet: true, params: { status: fStatus.value, job_type: fType.value, hours: fHours.value, job_id: jobId, limit: 300 } });
      table.setRows(d.runs || []);
      const active = (d.runs || []).some(r => r.status === 'running' || r.status === 'queued');
      clearTimeout(timer);
      if (fAuto.checked) timer = setTimeout(load, active ? 3000 : 15000);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }
  ctx.signal.addEventListener('abort', () => clearTimeout(timer));
  for (const f of [fStatus, fType, fHours]) on(f, 'change', load, ctx.signal);
  on(fAuto, 'change', load, ctx.signal);
  bus.on('jobs:changed', load, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action; const id = Number(btn.dataset.id);
    if (a === 'refresh') return load();
    if (a === 'cancel') {
      if (!await confirm({ title: `Cancel run #${id}?`, message: 'Queued runs are cancelled immediately; running jobs stop at their next checkpoint.' })) return;
      await api.post(adm(`/jobs/runs/${id}/cancel`)); toast.info('Cancel requested'); return load();
    }
    if (a === 'view') return openRun(id);
  }, ctx.signal);

  async function openRun(id) {
    const d = await api.get(adm(`/jobs/runs/${id}`));
    const r = d.run;
    const body = document.createElement('div');
    const render = (run) => {
      body.innerHTML = `
        <div class="row mb-2">${statusBadge(run.status)} ${badge(run.trigger_kind, 'secondary')} <span class="mono">${html`${run.job_type}`}</span> ${run.job_id ? `<a href="#/jobs/scheduled">job #${run.job_id}</a>` : ''} ${run.task_id ? `<span class="text-muted small">task ${html`${run.task_id}`}</span>` : ''}</div>
        <div class="kv-table mb-2">
          <div class="kv-row"><div class="kv-key">Queued</div><div class="kv-val">${fmtDate(run.queued_at)}</div></div>
          <div class="kv-row"><div class="kv-key">Started / finished</div><div class="kv-val">${fmtDate(run.started_at)} → ${fmtDate(run.finished_at)} ${run.duration_s != null ? `(${fmtDuration(run.duration_s)})` : ''}</div></div>
          <div class="kv-row"><div class="kv-key">Runner</div><div class="kv-val">${html`${run.claimed_by || '—'}`}${run.stage ? ` · ${html`${run.stage}`}` : ''}</div></div>
          ${run.skip_reason ? `<div class="kv-row"><div class="kv-key">Skipped</div><div class="kv-val">${html`${run.skip_reason}`}</div></div>` : ''}
          ${run.error ? `<div class="kv-row"><div class="kv-key">Error</div><div class="kv-val text-danger">${html`${run.error}`}</div></div>` : ''}
        </div>
        <h4 class="mb-1">Params</h4><pre class="result-box mb-2">${html`${json(run.params)}`}</pre>
        <h4 class="mb-1">Summary</h4><pre class="result-box mb-2">${html`${run.summary != null ? json(run.summary) : '—'}`}</pre>
        <h4 class="mb-1">Log</h4><div class="log-view">${html`${run.log_text || '(no log lines)'}`}</div>`;
    };
    render(r);
    const h = openModal({ title: `Run #${id}`, body, size: 'lg', actions: [
      { label: 'Re-run with same params', cls: 'btn-warning', onClick: async (hh) => {
        if (!await confirm({ title: 'Re-run?', message: `Queue ${r.job_type} again with the same parameters.` })) return;
        await api.post(adm('/jobs/run'), { job_type: r.job_type, params: r.params }); toast.success('Queued'); hh.close(); load();
      } },
      { label: 'Close', cls: 'btn-secondary' },
    ] });
    // live refresh while running
    let t = null;
    const tick = async () => {
      if (!h.el.isConnected) return;
      const dd = await api.get(adm(`/jobs/runs/${id}`), { quiet: true });
      render(dd.run);
      if (['queued', 'running'].includes(dd.run.status)) t = setTimeout(tick, 2500);
    };
    if (['queued', 'running'].includes(r.status)) t = setTimeout(tick, 2500);
    ctx.signal.addEventListener('abort', () => clearTimeout(t));
  }

  await load();
  if (ctx.params.run) openRun(Number(ctx.params.run)).catch(() => {});
}
