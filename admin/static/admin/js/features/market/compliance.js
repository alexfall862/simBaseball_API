// features/market/compliance.js — league-wide roster compliance (port of legacy #section-roster-compliance).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { dataTable } from '../../ui/table.js';
import { badge, kpi } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { orgSelect, levelName } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>League-wide roster compliance</h3><p class="card-sub text-muted">Every organization against its roster minimums and maximums per level (GET /transactions/roster-status/&lt;org&gt;). "All organizations" checks every MLB org.</p></div>
        <div class="row">
          <select id="rc-org"></select>
          <button class="btn btn-primary" data-action="load">Load</button>
        </div>
      </div>
      <div id="rc-summary-wrap" hidden><div class="grid-3" id="rc-summary"></div></div>
    </div>
    <div class="card" id="rc-detail" hidden>
      <div class="card-head">
        <h3>Detail by organization</h3>
        <label class="checkbox-label small"><input type="checkbox" id="rc-violations" /> Show violations only</label>
      </div>
      <div id="rc-table"></div>
    </div>`);

  const orgSel = await orgSelect(q(el, '#rc-org'), { signal: ctx.signal, placeholder: 'All organizations (MLB)' });
  let data = [];

  const table = dataTable(q(el, '#rc-table'), {
    emptyText: 'No data.', pageSize: 100,
    rowClass: r => (r.over_limit ? 'row-danger' : r.under_limit ? 'row-warning' : ''),
    columns: [
      { key: 'org_abbrev', title: 'Organization', sortable: true, html: true, render: r => `<strong>${html`${r.org_abbrev}`}</strong>` },
      { key: 'level_id', title: 'Level', sortable: true, render: r => r.level_name, sortValue: r => r.level_id },
      { key: 'count', title: 'Count', align: 'right', sortable: true },
      { key: 'min_roster', title: 'Min', align: 'right', render: r => (r.min_roster != null ? r.min_roster : '--') },
      { key: 'max_roster', title: 'Max', align: 'right', render: r => (r.max_roster != null ? r.max_roster : '--') },
      { key: '_s', title: 'Status', html: true, render: r => (r.over_limit ? badge('OVER', 'danger') : r.under_limit ? badge('UNDER', 'warning') : badge('OK', 'success')), sortValue: r => (r.over_limit || r.under_limit ? 0 : 1), sortable: true },
    ],
  });

  function renderTable() {
    const only = q(el, '#rc-violations').checked;
    let rows = only ? data.filter(r => r.over_limit || r.under_limit) : data;
    rows = [...rows].sort((a, b) => {
      const av = a.over_limit || a.under_limit ? 0 : 1, bv = b.over_limit || b.under_limit ? 0 : 1;
      if (av !== bv) return av - bv;
      const oc = a.org_abbrev.localeCompare(b.org_abbrev);
      return oc !== 0 ? oc : b.level_id - a.level_id;
    });
    table.setRows(rows);
  }

  function renderSummary() {
    const totalOrgs = new Set(data.map(r => r.org_id)).size;
    const over = data.filter(r => r.over_limit), under = data.filter(r => r.under_limit);
    const bad = new Set([...over, ...under].map(r => r.org_id)).size;
    const violations = over.length + under.length;
    q(el, '#rc-summary-wrap').hidden = false;
    setHtml(q(el, '#rc-summary'), raw([
      kpi({ label: 'Organizations', value: totalOrgs }),
      kpi({ label: 'Fully compliant', value: totalOrgs - bad, kind: totalOrgs - bad === totalOrgs ? 'success' : '' }),
      kpi({ label: 'Violations', value: violations, sub: `${over.length} over / ${under.length} under`, kind: violations ? 'danger' : 'success' }),
    ].join('')));
  }

  async function load() {
    const orgId = orgSel.get();
    const targets = orgId ? orgSel.orgs.filter(o => o.id === orgId) : orgSel.orgs.filter(o => o.league === 'mlb');
    if (!targets.length) { toast.warn('No organizations to check'); return; }
    q(el, '#rc-detail').hidden = false;
    q(el, '#rc-summary-wrap').hidden = true;
    table.setLoading();
    const results = await Promise.all(targets.map(org =>
      api.get(v1(`/transactions/roster-status/${org.id}`), { signal: ctx.signal, quiet: true })
        .then(levels => (Array.isArray(levels) ? levels : [])
          .filter(l => l.max_roster > 0 || l.min_roster > 0)
          .map(l => ({
            org_id: org.id, org_abbrev: org.org_abbrev,
            level_id: Number(l.level_id), level_name: levelName(l.level_id),
            count: l.count, min_roster: l.min_roster, max_roster: l.max_roster,
            over_limit: !!l.over_limit, under_limit: !!l.under_limit,
          })))
        .catch(e => { if (e.name === 'AbortError') throw e; return []; })));
    data = results.flat();
    renderSummary();
    renderTable();
  }

  on(q(el, '#rc-violations'), 'change', renderTable, ctx.signal);
  delegate(el, 'click', '[data-action="load"]', () => load().catch(() => {}), ctx.signal);
}
