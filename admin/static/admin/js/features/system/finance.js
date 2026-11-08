// features/system/finance.js — books operations (NEW tab; the legacy UI never exposed these).
//
// All POST /admin/run-* endpoints in app.py authenticate with X-Admin-Password (api.post ... {admin:true})
// and take `league_year` = the season NUMBER (e.g. 2026), not league_years.id. They return
// {status:'ok', details:{...}} or {error, message}.
//
// Read side: GET /api/v1/orgs/<abbrev>/financial_summary?league_year= and GET /api/v1/financial_summary?league_year=.

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, esc, setHtml, delegate, on, q } from '../../core/html.js';
import { fmtNum, json } from '../../core/format.js';
import { dataTable, kvTable } from '../../ui/table.js';
import { confirm, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { fillSelect } from '../../ui/selectors.js';
import { seasonYear, adminPasswordBanner } from './_shared.js';

const OPS = Object.freeze([
  { key: 'run-year-start-books', title: 'Year-start books', cls: 'btn-primary',
    desc: 'Opens the ledger for the league year: initial balances and season budget lines for every organization. Run once after the schedule exists.' },
  { key: 'run-week-books', title: 'Week books', cls: 'btn-primary', extra: 'week_index',
    desc: 'Posts one week of revenue/expenses (gate, payroll share, etc.) for every org. Normally run by the sim pipeline; re-run here for a specific week_index when a week was skipped.' },
  { key: 'run-season-books', title: 'Full season books', cls: 'btn-secondary',
    desc: 'Runs the week books for every week of the league year in one go. Use when rebuilding a season ledger from scratch.' },
  { key: 'run-year-end-interest', title: 'Year-end interest', cls: 'btn-warning', danger: true, typeToConfirm: 'INTEREST',
    desc: 'Applies year-end interest on each org balance (debt interest / cash yield). One-shot per league year — running it twice double-charges.' },
  { key: 'run-playoff-revenue', title: 'Playoff revenue', cls: 'btn-warning', danger: true, typeToConfirm: 'PLAYOFF',
    desc: 'Credits playoff gate/bonus revenue to the teams that played postseason games. One-shot per league year, after the World Series.' },
  { key: 'initialize-next-league-year', title: 'Initialize next league year', cls: 'btn-danger', danger: true, typeToConfirm: 'NEXT YEAR',
    desc: 'Carries balances forward and creates the opening books for league_year + 1. Pass the CURRENT year. One-shot and not reversible; see Season → Offseason Checklist for where this sits in the rollover.' },
]);

function opCard(op) {
  return `<div class="card${op.danger ? ' danger-zone' : ''}" id="fin-${op.key}">
    <h3>${esc(op.title)}</h3>
    <p class="text-muted small mb-2">${esc(op.desc)}</p>
    <div class="row">
      ${op.extra === 'week_index' ? `<div class="form-group"><label for="f-week-${esc(op.key)}">week_index</label><input type="number" id="f-week-${esc(op.key)}" data-week min="1" placeholder="1" style="width:110px" /></div>` : ''}
      <button class="btn ${esc(op.cls)}" data-action="run" data-key="${esc(op.key)}">Run</button>
      <code class="small text-muted">POST /admin/${esc(op.key)}</code>
    </div>
    <div class="fin-progress"></div>
  </div>`;
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div id="fin-pw"></div>
    <div class="card tight">
      <div class="row between">
        <div class="row">
          <div class="form-group"><label for="fin-year">League year (season number)</label><input type="number" id="fin-year" min="1900" max="3000" style="width:140px" value="${seasonYear() || ''}" /></div>
          <span class="text-muted small">Applies to every operation below. This is the year (e.g. 2026), not <code>league_years.id</code>.</span>
        </div>
      </div>
    </div>
    <div class="grid-2" id="fin-ops">${raw(OPS.map(opCard).join(''))}</div>
    <div class="card">
      <div class="card-head">
        <div><h3>Financial summary</h3><p class="card-sub text-muted">Read-only. League-wide: <code>GET /api/v1/financial_summary?league_year=</code>. One org: <code>GET /api/v1/orgs/&lt;abbrev&gt;/financial_summary?league_year=</code>.</p></div>
        <div class="row">
          <select id="fin-org"><option value="">All organizations</option></select>
          <button class="btn btn-sm btn-secondary" data-action="summary">Load</button>
          <button class="btn btn-sm btn-ghost" data-action="summary-raw" hidden>Raw JSON</button>
        </div>
      </div>
      <div id="fin-totals"></div>
      <div id="fin-summary"><p class="text-muted small">Pick a league year and click Load.</p></div>
    </div>`);

  adminPasswordBanner(q(el, '#fin-pw'));
  const widgets = new Map();
  for (const op of OPS) widgets.set(op.key, progressWidget(q(el, `#fin-${op.key} .fin-progress`)));
  let summaryData = null;

  api.get(v1('/organizations'), { quiet: true, signal: ctx.signal }).then(d => {
    const list = Array.isArray(d) ? d : (d.organizations || []);
    const opts = list.map(o => (typeof o === 'string' ? { value: o, label: o } : { value: o.org_abbrev || o.id, label: o.org_abbrev || o.name || o.id }));
    fillSelect(q(el, '#fin-org'), opts, { placeholder: 'All organizations' });
  }).catch(() => {});

  function year() {
    const y = Number(q(el, '#fin-year').value);
    if (!y) { toast.warn('Enter the league year (e.g. 2026)'); return null; }
    return y;
  }

  async function runOp(op, btn) {
    const y = year();
    if (!y) return;
    const body = { league_year: y };
    if (op.extra === 'week_index') {
      const w = Number(q(el, `#fin-${op.key} [data-week]`).value);
      if (!w) { toast.warn('week_index is required'); return; }
      body.week_index = w;
    }
    const ok = await confirm({
      title: `${op.title} for ${y}?`, danger: !!op.danger, typeToConfirm: op.typeToConfirm || null, confirmLabel: 'Run',
      message: op.danger ? 'One-shot operation. Running it twice for the same league year posts the entries twice.' : '',
      detail: `POST /admin/${op.key}\n${json(body)}`,
    });
    if (!ok) return;
    btn.disabled = true;
    try {
      await runTracked({ el: q(el, `#fin-${op.key} .fin-progress`), widget: widgets.get(op.key), label: `${op.title} (${y})…`, signal: ctx.signal,
        start: () => api.post(adm(`/${op.key}`), body, { admin: true, signal: ctx.signal }) });
      toast.success(`${op.title} finished`);
    } catch (e) { if (e && e.name === 'AbortError') return; }
    finally { btn.disabled = false; }
  }

  function moneyish(v) {
    return typeof v === 'number' ? fmtNum(v, Number.isInteger(v) ? 0 : 2) : (v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));
  }

  async function loadSummary() {
    const y = year();
    if (!y) return;
    const org = q(el, '#fin-org').value;
    const box = q(el, '#fin-summary');
    setHtml(q(el, '#fin-totals'), '');
    setHtml(box, '<p class="text-muted">Loading…</p>');
    q(el, '[data-action="summary-raw"]').hidden = true;
    try {
      if (org) {
        summaryData = await api.get(v1(`/orgs/${encodeURIComponent(org)}/financial_summary`), { params: { league_year: y }, signal: ctx.signal });
        setHtml(box, raw(kvTable(Object.entries(summaryData).map(([k, v]) => [k, moneyish(v)]))));
      } else {
        summaryData = await api.get(v1('/financial_summary'), { params: { league_year: y }, signal: ctx.signal });
        const t = summaryData.league_totals || {};
        setHtml(q(el, '#fin-totals'), raw(kvTable(Object.entries(t).map(([k, v]) => [`league ${k}`, moneyish(v)]))));
        const rows = Object.entries(summaryData.orgs || {}).map(([abbrev, s]) => ({ org: abbrev, ...(s || {}) }));
        const keys = ['org', ...Array.from(new Set(rows.flatMap(r => Object.keys(r)))).filter(k => k !== 'org')];
        dataTable(box, {
          rows, compact: true, sortKey: 'org', rowKey: 'org', emptyText: 'No organizations in the summary.',
          columns: keys.map(k => ({ key: k, title: k, sortable: true, align: k === 'org' ? undefined : 'right', render: r => moneyish(r[k]), sortValue: r => r[k] })),
        });
      }
      q(el, '[data-action="summary-raw"]').hidden = false;
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(box, html`<p class="text-danger">${e.message}</p>`);
    }
  }

  on(q(el, '#fin-year'), 'keydown', (e) => { if (e.key === 'Enter') loadSummary(); }, ctx.signal);
  delegate(el, 'click', '[data-action]', (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'run') { const op = OPS.find(o => o.key === btn.dataset.key); if (op) runOp(op, btn); }
    else if (a === 'summary') loadSummary();
    else if (a === 'summary-raw' && summaryData) showResult('Financial summary', summaryData);
  }, ctx.signal);
}
