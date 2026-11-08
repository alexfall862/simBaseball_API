// features/market/trades.js — admin trade queue, proposals, direct trade builder
// (port of legacy #section-tx-trades + docs/trade_admin_frontend_guide.md).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { fmtDate, json } from '../../core/format.js';
import { dataTable, kvTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { field, readForm } from '../../ui/form.js';
import { openModal, confirm, promptText } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { orgSelect, txContext, levelName, money } from './_shared.js';

const STATUS = {
  proposed: ['Proposed', 'secondary'],
  counterparty_accepted: ['Awaiting admin', 'warning'],
  counterparty_rejected: ['Rejected (CP)', 'danger'],
  admin_rejected: ['Rejected (admin)', 'danger'],
  executed: ['Executed', 'success'],
  cancelled: ['Cancelled', 'secondary'],
  expired: ['Expired', 'secondary'],
};
const statusBadge = (s) => { const d = STATUS[s] || [s || '--', 'secondary']; return badge(d[0], d[1]); };

function packageSummary(p) {
  const pr = p.proposal || {};
  const toB = (pr.players_to_b || []).length, toA = (pr.players_to_a || []).length;
  const bits = [`${toB} player${toB === 1 ? '' : 's'} → / ${toA} ←`];
  if (pr.cash_a_to_b) bits.push(`${pr.cash_a_to_b > 0 ? 'A pays B' : 'B pays A'} ${money(Math.abs(pr.cash_a_to_b))}`);
  const ret = pr.salary_retention && Object.keys(pr.salary_retention).length;
  if (ret) bits.push(`${ret} retention`);
  return bits.join(' · ');
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Pending approval <span id="tq-count"></span></h3><p class="card-sub text-muted">Proposals both orgs agreed to (status counterparty_accepted). Approve executes the trade immediately; reject vetoes it.</p></div>
        <div class="row"><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
      </div>
      <div id="tq-table"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <h3>All proposals</h3>
        <div class="row">
          <select id="tp-status"><option value="">All statuses</option>${raw(Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${esc(v[0])}</option>`).join(''))}</select>
          <select id="tp-org"></select>
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div id="tp-table"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Direct trade builder</h3><p class="card-sub text-muted">Admin-executed trade that bypasses the proposal workflow (POST /transactions/trade/execute). Tick players on each side; optional per-player salary retention (% kept by the sending org).</p></div>
      </div>
      <div class="grid-2">
        <div>
          <div class="row mb-1"><strong>Organization A</strong><select id="tb-org-a"></select></div>
          <div id="tb-roster-a"></div>
        </div>
        <div>
          <div class="row mb-1"><strong>Organization B</strong><select id="tb-org-b"></select></div>
          <div id="tb-roster-b"></div>
        </div>
      </div>
      <div class="form-row mt-2">
        ${raw(field.number('cash_a_to_b', 'Cash A → B ($, negative = B pays A)', { value: 0, step: 10000 }))}
        <button class="btn btn-warning" data-action="execute">Execute trade (admin)</button>
      </div>
      <div id="tb-summary" class="text-muted small mb-1"></div>
      <pre class="result-box" id="tb-result"></pre>
    </div>`);

  const orgFilter = await orgSelect(q(el, '#tp-org'), { signal: ctx.signal, placeholder: 'Any org', onChange: () => loadAll() });
  const orgs = orgFilter;
  const orgA = await orgSelect(q(el, '#tb-org-a'), { signal: ctx.signal, onChange: (id) => loadSide('a', id) });
  const orgB = await orgSelect(q(el, '#tb-org-b'), { signal: ctx.signal, onChange: (id) => loadSide('b', id) });

  // ------------------------------------------------------------ queue + proposals
  const propCols = (queue) => [
    { key: 'id', title: '#', width: '60px', sortable: true },
    { key: 'proposing_org_id', title: 'From', sortable: true, render: r => orgs.name(r.proposing_org_id) },
    { key: 'receiving_org_id', title: 'To', sortable: true, render: r => orgs.name(r.receiving_org_id) },
    { key: '_pkg', title: 'Package', render: r => packageSummary(r) },
    ...(queue ? [] : [{ key: 'status', title: 'Status', html: true, sortable: true, render: r => statusBadge(r.status) }]),
    { key: 'proposed_at', title: 'Proposed', sortable: true, render: r => fmtDate(r.proposed_at || r.created_at), sortValue: r => r.proposed_at || r.created_at },
    ...(queue ? [{ key: 'counterparty_acted_at', title: 'Accepted', render: r => fmtDate(r.counterparty_acted_at) },
      { key: 'counterparty_note', title: 'CP note', render: r => r.counterparty_note || '' }] : []),
    { key: '_a', title: '', html: true, nowrap: true, render: r => `<div class="row nowrap"><button class="btn btn-xs btn-secondary" data-action="detail" data-id="${r.id}">Details</button>`
      + (r.status === 'counterparty_accepted' ? `<button class="btn btn-xs btn-primary" data-action="approve" data-id="${r.id}">Approve</button><button class="btn btn-xs btn-danger" data-action="reject" data-id="${r.id}">Reject</button>` : '')
      + '</div>' },
  ];
  const queueTable = dataTable(q(el, '#tq-table'), { rowKey: 'id', emptyText: 'Nothing awaiting admin approval.', columns: propCols(true), sortKey: 'proposed_at', sortDir: 'asc' });
  const propTable = dataTable(q(el, '#tp-table'), { rowKey: 'id', emptyText: 'No proposals match.', pageSize: 50, columns: propCols(false) });
  let proposals = [];

  async function loadQueue() {
    queueTable.setLoading();
    try {
      const rows = await api.get(v1('/transactions/trade/proposals'), { signal: ctx.signal, params: { status: 'counterparty_accepted' } });
      const list = Array.isArray(rows) ? rows : [];
      queueTable.setRows(list);
      setHtml(q(el, '#tq-count'), raw(list.length ? badge(String(list.length), 'warning') : ''));
    } catch (e) { if (e.name !== 'AbortError') queueTable.setError(e.message); }
  }
  async function loadProposals() {
    propTable.setLoading();
    try {
      const rows = await api.get(v1('/transactions/trade/proposals'), { signal: ctx.signal, params: { status: q(el, '#tp-status').value, org_id: orgFilter.get() } });
      proposals = Array.isArray(rows) ? rows : [];
      propTable.setRows(proposals);
    } catch (e) { if (e.name !== 'AbortError') propTable.setError(e.message); }
  }
  const loadAll = () => Promise.all([loadQueue(), loadProposals()]);

  async function getProposal(id) {
    return proposals.find(p => p.id === id) || queueTable.rows.find(p => p.id === id) || api.get(v1(`/transactions/trade/proposals/${id}`));
  }

  async function approve(id, note) {
    const p = await getProposal(id);
    if (!await confirm({ title: `Approve trade #${id}?`, confirmLabel: 'Approve & execute',
      message: `${orgs.name(p.proposing_org_id)} ↔ ${orgs.name(p.receiving_org_id)}: ${packageSummary(p)}. This immediately executes the trade — players and salary obligations are transferred.` })) return false;
    const { league_year_id, game_week_id } = await txContext();
    const body = { league_year_id, game_week_id, executed_by: 'admin' };
    if (note) body.note = note;
    const r = await api.put(v1(`/transactions/trade/proposals/${id}/admin-approve`), body);
    toast.success(`Trade #${id} executed (transaction ${r && r.trade_result ? r.trade_result.transaction_id : '?'})`);
    await loadAll();
    return true;
  }

  async function reject(id, note) {
    if (note === undefined) {
      note = await promptText({ title: `Reject trade #${id}`, label: 'Admin note (optional, shown to both orgs)', okLabel: 'Reject' });
      if (note === null) return false;
    }
    const r = await api.put(v1(`/transactions/trade/proposals/${id}/admin-reject`), note ? { note } : {});
    void r;
    toast.info(`Trade #${id} rejected`);
    await loadAll();
    return true;
  }

  // ------------------------------------------------------------ detail modal
  async function openDetail(id) {
    const p = await getProposal(id);
    if (!p) { toast.error(`Proposal #${id} not found`); return; }
    const pr = p.proposal || {};
    const a = p.proposing_org_id, b = p.receiving_org_id;
    const [rosA, rosB, stA, stB] = await Promise.all([
      api.get(v1(`/transactions/roster/${a}`), { quiet: true }).catch(() => []),
      api.get(v1(`/transactions/roster/${b}`), { quiet: true }).catch(() => []),
      api.get(v1(`/transactions/roster-status/${a}`), { quiet: true }).catch(() => []),
      api.get(v1(`/transactions/roster-status/${b}`), { quiet: true }).catch(() => []),
    ]);
    const byId = (list) => new Map((Array.isArray(list) ? list : []).map(x => [Number(x.player_id), x]));
    const mA = byId(rosA), mB = byId(rosB);
    const ret = pr.salary_retention || {};
    const playerCard = (pid, m) => {
      const pl = m.get(Number(pid));
      const r = ret[String(pid)] || ret[pid];
      return `<li><strong>${pl ? esc(pl.player_name) : `Player #${esc(pid)}`}</strong>${pl ? ` <span class="text-muted">(${esc(pl.position)})</span> · ${esc(levelName(pl.current_level))} · ${esc(money(pl.salary))}/yr` : ' <span class="text-muted">not on roster</span>'}${r ? ` · ${badge(`${Math.round((r.retention_pct || 0) * 100)}% retained`, 'info')}` : ''}</li>`;
    };
    const list = (ids, m) => (ids && ids.length ? `<ul class="stack">${ids.map(pid => playerCard(pid, m)).join('')}</ul>` : '<p class="text-muted">—</p>');

    // roster impact at each affected level
    const impact = (status, roster, outIds, inIds, inRoster) => {
      const lv = new Map();
      for (const pid of outIds || []) { const pl = roster.get(Number(pid)); if (pl) lv.set(pl.current_level, (lv.get(pl.current_level) || 0) - 1); }
      for (const pid of inIds || []) { const pl = inRoster.get(Number(pid)); if (pl) lv.set(pl.current_level, (lv.get(pl.current_level) || 0) + 1); }
      return Array.from(lv.entries()).map(([level, delta]) => {
        const s = (Array.isArray(status) ? status : []).find(x => Number(x.level_id) === Number(level));
        if (!s) return `${esc(levelName(level))}: ${delta > 0 ? '+' : ''}${delta}`;
        const after = s.count + delta;
        const bad = (s.max_roster && after > s.max_roster) || (s.min_roster && after < s.min_roster);
        return `${esc(levelName(level))}: ${s.count} → ${after} ${bad ? badge(`outside ${s.min_roster}-${s.max_roster}`, 'danger') : `<span class="text-muted">within ${s.min_roster}-${s.max_roster}</span>`}`;
      }).join('<br>') || '<span class="text-muted">no roster change</span>';
    };

    const body = `
      <div class="row mb-2">${statusBadge(p.status)} <span class="text-muted small">league year ${esc(p.league_year_id)}</span></div>
      <div class="grid-2">
        <div><h4 class="mb-1">${esc(orgs.name(a))} sends to ${esc(orgs.name(b))}</h4>${list(pr.players_to_b, mA)}</div>
        <div><h4 class="mb-1">${esc(orgs.name(b))} sends to ${esc(orgs.name(a))}</h4>${list(pr.players_to_a, mB)}</div>
      </div>
      ${kvTable([
        ['Cash', pr.cash_a_to_b ? esc(`${orgs.name(pr.cash_a_to_b > 0 ? a : b)} pays ${orgs.name(pr.cash_a_to_b > 0 ? b : a)} ${money(Math.abs(pr.cash_a_to_b))}`) : 'none'],
        [`Roster impact · ${esc(orgs.name(a))}`, impact(stA, mA, pr.players_to_b, pr.players_to_a, mB)],
        [`Roster impact · ${esc(orgs.name(b))}`, impact(stB, mB, pr.players_to_a, pr.players_to_b, mA)],
        ['Proposed', esc(fmtDate(p.proposed_at))],
        ['Counterparty acted', `${esc(fmtDate(p.counterparty_acted_at))}${p.counterparty_note ? ` — “${esc(p.counterparty_note)}”` : ''}`],
        ['Admin acted', `${esc(fmtDate(p.admin_acted_at))}${p.admin_note ? ` — “${esc(p.admin_note)}”` : ''}`],
        ['Executed', esc(fmtDate(p.executed_at))],
      ], { html: true })}
      ${p.status === 'counterparty_accepted' ? field.textarea('admin_note', 'Admin note (optional)', { rows: 2, mono: false }) : ''}
      <details class="mt-2"><summary class="text-muted small">Raw JSON</summary><pre class="result-box mt-1">${esc(json(p))}</pre></details>`;

    const actions = [];
    if (p.status === 'counterparty_accepted') {
      actions.push({ label: 'Approve trade', cls: 'btn-primary', onClick: async (hh) => { if (await approve(id, (readForm(hh.body).admin_note || '').trim())) hh.close(); } });
      actions.push({ label: 'Reject trade', cls: 'btn-danger', onClick: async (hh) => {
        const note = (readForm(hh.body).admin_note || '').trim();
        if (!await confirm({ title: `Reject trade #${id}?`, danger: true, confirmLabel: 'Reject', message: 'Both orgs will see the rejection. This cannot be undone.' })) return;
        if (await reject(id, note)) hh.close();
      } });
    }
    actions.push({ label: 'Close', cls: 'btn-secondary' });
    openModal({ title: `Trade proposal #${id}`, body, size: 'lg', actions });
  }

  // ------------------------------------------------------------ direct builder
  const sides = { a: { rows: [], picked: new Map() }, b: { rows: [], picked: new Map() } };
  const sideTables = {};
  for (const side of ['a', 'b']) {
    sideTables[side] = dataTable(q(el, `#tb-roster-${side}`), {
      rowKey: 'player_id', emptyText: 'Select an organization.', compact: true,
      columns: [
        { key: '_c', title: '', width: '32px', html: true, render: r => `<input type="checkbox" data-pick="${side}" value="${r.player_id}"${sides[side].picked.has(r.player_id) ? ' checked' : ''} />` },
        { key: 'player_name', title: 'Player' },
        { key: 'position', title: 'Pos' },
        { key: 'current_level', title: 'Level', render: r => levelName(r.current_level) },
        { key: 'salary', title: 'Salary', align: 'right', render: r => money(r.salary) },
        { key: '_r', title: 'Retain %', html: true, render: r => `<input type="number" min="0" max="100" step="5" data-ret="${side}" data-pid="${r.player_id}" value="${sides[side].picked.get(r.player_id) ?? 0}" title="Salary % retained by the sending org"${sides[side].picked.has(r.player_id) ? '' : ' disabled'} />` },
      ],
    });
  }

  async function loadSide(side, orgId) {
    const t = sideTables[side];
    sides[side].picked.clear();
    sides[side].rows = [];
    if (!orgId) { t.setRows([]); renderSummary(); return; }
    t.setLoading();
    try {
      const rows = await api.get(v1(`/transactions/roster/${orgId}`), { signal: ctx.signal });
      sides[side].rows = Array.isArray(rows) ? rows : [];
      t.setRows(sides[side].rows);
    } catch (e) { if (e.name !== 'AbortError') t.setError(e.message); }
    renderSummary();
  }

  function renderSummary() {
    const nA = sides.a.picked.size, nB = sides.b.picked.size;
    q(el, '#tb-summary').textContent = (nA || nB) ? `${nA} player(s) A → B, ${nB} player(s) B → A` : '';
  }

  on(el, 'change', (e) => {
    const cb = e.target.closest('input[data-pick]');
    if (cb) {
      const side = cb.dataset.pick, pid = Number(cb.value);
      const retInp = el.querySelector(`input[data-ret="${side}"][data-pid="${pid}"]`);
      if (cb.checked) { sides[side].picked.set(pid, retInp ? Number(retInp.value) || 0 : 0); if (retInp) retInp.disabled = false; }
      else { sides[side].picked.delete(pid); if (retInp) retInp.disabled = true; }
      renderSummary();
      return;
    }
    const ri = e.target.closest('input[data-ret]');
    if (ri) {
      const side = ri.dataset.ret, pid = Number(ri.dataset.pid);
      if (sides[side].picked.has(pid)) sides[side].picked.set(pid, Math.max(0, Math.min(100, Number(ri.value) || 0)));
    }
  }, ctx.signal);

  async function executeTrade() {
    const aId = orgA.get(), bId = orgB.get();
    if (!aId || !bId) { toast.warn('Select both organizations'); return; }
    if (aId === bId) { toast.warn('Cannot trade with the same org'); return; }
    const toB = Array.from(sides.a.picked.keys()), toA = Array.from(sides.b.picked.keys());
    if (!toA.length && !toB.length) { toast.warn('Select at least one player'); return; }
    const retention = {};
    for (const [pid, pct] of [...sides.a.picked, ...sides.b.picked]) if (pct > 0) retention[String(pid)] = { retention_pct: pct / 100 };
    const cash = Number(readForm(el).cash_a_to_b) || 0;
    if (!await confirm({ title: 'Execute trade?', danger: true, confirmLabel: 'Execute',
      message: `${toB.length} player(s) ${orgs.name(aId)} → ${orgs.name(bId)}, ${toA.length} player(s) ${orgs.name(bId)} → ${orgs.name(aId)}${cash ? `, cash ${money(Math.abs(cash))} ${cash > 0 ? 'A → B' : 'B → A'}` : ''}${Object.keys(retention).length ? `, ${Object.keys(retention).length} retention clause(s)` : ''}. Players are transferred immediately; this bypasses the proposal workflow.` })) return;
    const { league_year_id, game_week_id } = await txContext();
    const body = { org_a_id: aId, org_b_id: bId, players_to_b: toB, players_to_a: toA, cash_a_to_b: cash, league_year_id, game_week_id, executed_by: 'admin' };
    if (Object.keys(retention).length) body.salary_retention = retention;
    const out = q(el, '#tb-result');
    out.textContent = 'Executing trade…';
    try {
      const r = await api.post(v1('/transactions/trade/execute'), body);
      out.textContent = json(r);
      toast.success(`Trade executed (transaction ${r.transaction_id})`);
      await Promise.all([loadSide('a', aId), loadSide('b', bId), loadAll()]);
    } catch (e) {
      out.textContent = `Error: ${e.message}`;
    }
  }

  on(q(el, '#tp-status'), 'change', loadProposals, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action, id = Number(btn.dataset.id);
    try {
      if (a === 'refresh') await loadAll();
      else if (a === 'detail') await openDetail(id);
      else if (a === 'approve') await approve(id);
      else if (a === 'reject') await reject(id);
      else if (a === 'execute') await executeTrade();
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await loadAll();
  if (ctx.params.proposal) openDetail(Number(ctx.params.proposal)).catch(() => {});
}
