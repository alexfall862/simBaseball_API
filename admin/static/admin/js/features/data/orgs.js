// features/data/orgs.js — organization browser (port of legacy #section-organizations)
// plus the per-org financial summary (GET /api/v1/orgs/<abbrev>/financial_summary).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q } from '../../core/html.js';
import { fillSelect } from '../../ui/selectors.js';
import { showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { objectKv, seasonYear, unwrapList, firstRow } from './_shared.js';

function orgOption(o) {
  if (typeof o === 'string') return { value: o, label: o };
  const id = o.org_abbrev || o.abbreviation || o.organization_id || o.id;
  return { value: id, label: o.name || o.organization_name || o.org_abbrev || o.abbreviation || `Org ${id}` };
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Organizations</h3><p class="card-sub text-muted">Pick an organization to see its <code>organizations</code> row. List: <code>GET /api/v1/organizations</code>, detail: <code>GET /api/v1/&lt;abbrev&gt;/</code>.</p></div>
        <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh list</button>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="org-select">Organization</label><select id="org-select"><option value="">Loading…</option></select></div>
      </div>
      <div id="org-status" class="text-muted small"></div>
    </div>
    <div class="card" id="org-detail-card" hidden>
      <div class="card-head"><h3 id="org-detail-title">Organization details</h3><button class="btn btn-sm btn-ghost" data-action="raw-org">Raw JSON</button></div>
      <div id="org-detail"></div>
    </div>
    <div class="card" id="org-fin-card" hidden>
      <div class="card-head">
        <div><h3>Financial summary</h3><p class="card-sub text-muted"><code>GET /api/v1/orgs/&lt;abbrev&gt;/financial_summary?league_year=YYYY</code> — league year is the season number, not the id.</p></div>
        <div class="row">
          <input type="number" id="org-fin-year" min="1900" max="3000" placeholder="league year" style="width:130px" />
          <button class="btn btn-sm btn-secondary" data-action="load-fin">Load</button>
          <button class="btn btn-sm btn-ghost" data-action="raw-fin" hidden>Raw JSON</button>
        </div>
      </div>
      <div id="org-fin"><p class="text-muted small">Enter a league year and click Load.</p></div>
    </div>`);

  const sel = q(el, '#org-select');
  const status = q(el, '#org-status');
  let orgRow = null;
  let finData = null;

  async function loadList() {
    sel.disabled = true;
    status.textContent = '';
    try {
      const d = await api.get(v1('/organizations'), { signal: ctx.signal });
      const opts = unwrapList(d, 'organizations').map(orgOption);
      fillSelect(sel, opts, { value: ctx.params.org || null, placeholder: 'Select an organization…' });
      status.textContent = `${opts.length} organizations`;
      if (sel.value) await loadDetail();
    } catch (e) {
      if (e.name !== 'AbortError') { sel.innerHTML = '<option value="">Failed to load</option>'; status.textContent = e.message; }
    } finally { sel.disabled = false; }
  }

  async function loadDetail() {
    const abbrev = sel.value;
    const card = q(el, '#org-detail-card');
    const fin = q(el, '#org-fin-card');
    orgRow = null; finData = null;
    if (!abbrev) { card.hidden = true; fin.hidden = true; return; }
    ctx.setParams({ org: abbrev });
    card.hidden = false;
    q(el, '#org-detail-title').textContent = `Organization details — ${abbrev}`;
    setHtml(q(el, '#org-detail'), '<p class="text-muted">Loading…</p>');
    try {
      const d = await api.get(v1(`/${encodeURIComponent(abbrev)}/`), { signal: ctx.signal });
      orgRow = firstRow(d);
      setHtml(q(el, '#org-detail'), raw(orgRow ? objectKv(orgRow) : '<p class="text-muted">No data for this organization.</p>'));
      fin.hidden = false;
      const y = q(el, '#org-fin-year');
      if (!y.value && seasonYear()) y.value = seasonYear();
      setHtml(q(el, '#org-fin'), '<p class="text-muted small">Enter a league year and click Load.</p>');
      q(el, '[data-action="raw-fin"]').hidden = true;
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(q(el, '#org-detail'), html`<p class="text-danger">${e.message}</p>`);
    }
  }

  async function loadFinancials() {
    const abbrev = sel.value;
    const year = Number(q(el, '#org-fin-year').value);
    if (!abbrev) return;
    if (!year) { toast.warn('Enter a league year (e.g. 2026)'); return; }
    setHtml(q(el, '#org-fin'), '<p class="text-muted">Loading…</p>');
    try {
      finData = await api.get(v1(`/orgs/${encodeURIComponent(abbrev)}/financial_summary`), { params: { league_year: year }, signal: ctx.signal });
      setHtml(q(el, '#org-fin'), raw(objectKv(finData)));
      q(el, '[data-action="raw-fin"]').hidden = false;
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(q(el, '#org-fin'), html`<p class="text-danger">${e.message}</p>`);
    }
  }

  on(sel, 'change', loadDetail, ctx.signal);
  on(q(el, '#org-fin-year'), 'keydown', (e) => { if (e.key === 'Enter') loadFinancials(); }, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await loadList();
      else if (a === 'load-fin') await loadFinancials();
      else if (a === 'raw-org' && orgRow) showResult(`Organization ${sel.value}`, orgRow);
      else if (a === 'raw-fin' && finData) showResult(`Financial summary ${sel.value}`, finData);
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await loadList();
}
