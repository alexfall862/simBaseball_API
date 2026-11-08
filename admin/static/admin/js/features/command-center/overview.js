// features/command-center/overview.js — the landing page.

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { relTime, fmtDate } from '../../core/format.js';
import { phaseLabel } from '../../core/constants.js';
import { kpi, phaseBadge, statusBadge, subweekPips, subweekFlagsFromTs, emptyState } from '../../ui/badge.js';
import { dataTable } from '../../ui/table.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { refreshSummary, refreshTimestamp } from '../../main.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="grid-4" id="cc-kpis"></div>
    <div class="grid-2">
      <div class="stack">
        <div class="card">
          <div class="card-head"><h3>Quick actions</h3><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
          <div class="button-group" id="cc-actions"></div>
          <div id="cc-progress"></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Needs attention</h3></div>
          <div class="action-list alert-list" id="cc-alerts"></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Next scheduled runs</h3><a class="btn btn-sm btn-ghost" href="#/jobs/scheduled">Manage</a></div>
          <div id="cc-next"></div>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><h3>Running now</h3><a class="btn btn-sm btn-ghost" href="#/jobs/tasks">All tasks</a></div>
          <div id="cc-tasks"></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Recent job runs</h3><a class="btn btn-sm btn-ghost" href="#/jobs/runs">History</a></div>
          <div id="cc-recent"></div>
        </div>
      </div>
    </div>`);

  const progress = progressWidget(q(el, '#cc-progress'));
  const nextTbl = dataTable(q(el, '#cc-next'), {
    compact: true, emptyText: 'No enabled schedules.',
    columns: [
      { key: 'name', title: 'Job' },
      { key: 'job_type', title: 'Type', cellClass: 'mono' },
      { key: 'in', title: 'Fires', render: r => `${r.in || ''}`, title_attr: r => fmtDate(r.at) },
    ],
  });
  const recentTbl = dataTable(q(el, '#cc-recent'), {
    compact: true, emptyText: 'No runs yet.',
    columns: [
      { key: 'job_type', title: 'Type', cellClass: 'mono' },
      { key: 'status', title: 'Status', html: true, render: r => statusBadge(r.status) },
      { key: 'finished_at', title: 'Finished', render: r => relTime(r.finished_at) },
      { key: '_a', title: '', html: true, render: r => `<a class="btn btn-xs btn-ghost" href="#/jobs/runs?run=${r.run_id}">View</a>` },
    ],
  });
  const tasksTbl = dataTable(q(el, '#cc-tasks'), {
    compact: true, emptyText: 'Nothing running.',
    columns: [
      { key: 'task_type', title: 'Task', cellClass: 'mono' },
      { key: 'status', title: 'Status', html: true, render: r => statusBadge(r.status) },
      { key: 'progress', title: 'Progress', render: r => (r.total ? `${r.progress} / ${r.total}` : (r.progress || '')) },
      { key: 'created_at', title: 'Started', render: r => relTime(r.created_at) },
    ],
  });

  function render(s) {
    const ts = store.get().ts || (s && s.timestamp);
    const sched = s && s.scheduler;
    const flags = subweekFlagsFromTs(ts);
    setHtml(q(el, '#cc-kpis'), raw([
      kpi({ label: 'Phase', value: ts ? phaseLabel(ts.Phase) : '--', sub: ts ? `Season ${ts.Season ?? '--'}` : 'No timestamp' }),
      `<div class="stat-card"><div class="stat-label">Week</div><div class="stat-value">${ts ? `${ts.Week ?? '--'}<span class="text-muted" style="font-size:1rem"> / ${ts.TotalWeeks ?? '--'}</span>` : '--'}</div><div class="stat-sub">${ts && (ts.Phase === 'REGULAR_SEASON' || ts.Phase === 'PLAYOFFS') ? subweekPips(flags) : (ts ? phaseBadge(ts.Phase) : '')}</div></div>`,
      kpi({ label: 'Scheduler', value: sched ? (sched.enabled ? 'On' : 'Off') : '--',
        sub: sched ? (sched.leader_alive ? `leader ${sched.leader}` : 'no runner alive') : 'unknown',
        kind: sched ? (sched.enabled ? (sched.leader_alive ? 'success' : 'warning') : '') : '' }),
      kpi({ label: 'Active', value: s ? `${(s.tasks && s.tasks.running) || 0} / ${(sched && sched.running) || 0}` : '--',
        sub: 'tasks / job runs running', kind: s && ((s.tasks && s.tasks.running) || (sched && sched.running)) ? 'info' : '' }),
    ].join('')));

    const actions = [];
    if (ts && ts.Phase === 'REGULAR_SEASON') {
      const pending = ['a', 'b', 'c', 'd'].filter(k => !flags[k]);
      if (!ts.RunGames && pending.length) actions.push(`<button class="btn btn-warning" data-action="sim-next">Sim subweek ${pending[0].toUpperCase()}</button>`);
      if (!pending.length) actions.push(`<button class="btn btn-primary" data-action="advance">Advance to week ${(ts.Week || 0) + 1}</button>`);
      if (ts.RunGames) actions.push(`<button class="btn btn-danger" data-action="clear-rg">Clear stuck RunGames</button>`);
    }
    actions.push('<a class="btn btn-secondary" href="#/season/simulate">Simulate</a>');
    if (ts && ts.Phase !== 'REGULAR_SEASON') actions.push('<a class="btn btn-secondary" href="#/season/checklist">Offseason checklist</a>');
    actions.push('<a class="btn btn-ghost" href="#/timeline/view">Timeline</a>');
    setHtml(q(el, '#cc-actions'), raw(actions.join('')));

    const alerts = (s && s.alerts) || [];
    setHtml(q(el, '#cc-alerts'), alerts.length ? raw(alerts.map(a => `
      <div class="action-item ${a.level === 'danger' ? 'danger' : a.level === 'info' ? 'info' : ''}">
        <div><div class="title">${html`${a.title}`}</div><div class="meta">${html`${a.detail || ''}`}</div></div>
        <div class="row">
          ${a.clearable ? '<button class="btn btn-sm btn-danger" data-action="clear-rg">Clear flag</button>' : ''}
          ${a.action ? `<a class="btn btn-sm btn-secondary" href="#/${a.action.area}/${a.action.tab}${a.action.params ? '?' + new URLSearchParams(a.action.params) : ''}">Open</a>` : ''}
        </div>
      </div>`).join('')) : raw(emptyState('All clear.')));

    nextTbl.setRows((sched && sched.next_runs) || []);
    recentTbl.setRows((sched && sched.recent) || []);
    tasksTbl.setRows((s && s.tasks && s.tasks.items) || []);
  }

  store.watch('summary', render, ctx.signal);
  store.watch('ts', () => render(store.get().summary), ctx.signal, { immediate: false });

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'refresh') { await refreshSummary(); toast.info('Refreshed'); return; }
    if (a === 'sim-next') {
      await runTracked({ el: q(el, '#cc-progress'), widget: progress, label: 'Simulating next subweek…', signal: ctx.signal,
        start: () => api.post(adm('/jobs/run'), { job_type: 'sim_next_subweek', params: { auto_advance: false } }) });
      await refreshTimestamp(); await refreshSummary();
      return;
    }
    if (a === 'advance') {
      if (!await confirm({ title: 'Advance week?', message: 'Runs books, injuries, waivers, FA phases, then week + 1.' })) return;
      await runTracked({ el: q(el, '#cc-progress'), widget: progress, label: 'Advancing week…', signal: ctx.signal,
        start: () => api.post(v1('/games/advance-week')) });
      await refreshTimestamp(); await refreshSummary();
      return;
    }
    if (a === 'clear-rg') {
      if (!await confirm({ title: 'Clear RunGames flag?', danger: true, message: 'Only do this if no simulation is actually running. It re-enables the sim buttons.' })) return;
      await api.post(adm('/sim/clear-run-games'));
      toast.success('RunGames flag cleared');
      await refreshTimestamp(); await refreshSummary();
    }
  }, ctx.signal);

  if (!store.get().summary) refreshSummary();
}
