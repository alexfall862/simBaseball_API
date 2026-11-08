// features/market/fa-auction.js — FA auction board + offer modal + admin phase/entry controls
// (port of legacy #section-fa-auction).

import { api, v1 } from '../../core/api.js';
import { html, setHtml, delegate, q } from '../../core/html.js';
import { fmtNum, json } from '../../core/format.js';
import { dataTable, kvTable } from '../../ui/table.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { openModal, confirm, promptText, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { orgSelect, txContext, money, auctionPhaseBadge, salaryFields, readSalaries, PRO_LEVEL_OPTIONS } from './_shared.js';

const OFFER_LEVELS = PRO_LEVEL_OPTIONS.filter(o => o.value >= 5);

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Free agent auction board</h3><p class="card-sub text-muted">Open auctions for the current league year (GET /fa-auction/board). Pick an organization to see its offers and bid on its behalf.</p></div>
        <div class="row">
          <select id="fa-org" title="Acting organization"></select>
          <button class="btn btn-secondary" data-action="load">Load board</button>
          <button class="btn btn-warning" data-action="advance" title="Admin: manually advance every open auction one phase">Advance phases</button>
          <button class="btn btn-ghost" data-action="enter" title="Admin: manually enter a player into the auction">Enter player…</button>
          <a class="btn btn-ghost" href="#/system/orphans" title="Scan FA-eligible players with no contract/auction/waiver">Orphan sweep →</a>
        </div>
      </div>
      <div class="text-muted small mb-1" id="fa-ctx"></div>
      <div id="fa-table"></div>
    </div>
    <pre class="result-box" id="fa-result"></pre>`);

  const orgSel = await orgSelect(q(el, '#fa-org'), { signal: ctx.signal, placeholder: 'No org (view only)', onChange: () => load() });
  if (ctx.params.org) orgSel.set(ctx.params.org);
  let board = [];

  const table = dataTable(q(el, '#fa-table'), {
    rowKey: 'auction_id', emptyText: 'No active auctions.', pageSize: 100, sortKey: 'war', sortDir: 'desc',
    columns: [
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'age', title: 'Age', sortable: true },
      { key: 'player_type', title: 'Type', sortable: true },
      { key: 'war', title: 'WAR', align: 'right', sortable: true, render: r => fmtNum(r.war, 1) },
      { key: 'min_aav', title: 'Min AAV', align: 'right', sortable: true, render: r => money(r.min_aav) },
      { key: 'phase', title: 'Phase', html: true, sortable: true, render: r => auctionPhaseBadge(r.phase) },
      { key: 'offer_count', title: '# Offers', align: 'right', sortable: true },
      { key: 'competing_teams', title: 'Competing', render: r => (r.competing_teams || []).join(', ') || '—' },
      { key: 'my_offer', title: 'Your offer', render: r => (r.my_offer ? `${money(r.my_offer.aav)} / ${r.my_offer.years}y` : '—') },
      { key: '_a', title: '', html: true, render: r => `<button class="btn btn-xs btn-primary" data-action="offer" data-id="${r.auction_id}">${r.my_offer ? 'Update' : 'Offer'}</button>` },
    ],
  });

  async function load() {
    const orgId = orgSel.get();
    ctx.setParams({ org: orgId || undefined });
    table.setLoading();
    const c = await txContext();
    q(el, '#fa-ctx').textContent = `League year ID ${c.league_year_id} · week ${c.week} (game_week_id ${c.game_week_id})${orgId ? ` · acting as ${orgSel.name(orgId)}` : ''}`;
    try {
      const rows = await api.get(v1('/fa-auction/board'), { signal: ctx.signal, params: { league_year_id: c.league_year_id, org_id: orgId } });
      board = Array.isArray(rows) ? rows : [];
      table.setRows(board);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }

  // ------------------------------------------------------------ offer modal
  async function openOffer(a) {
    const orgId = orgSel.get();
    if (!orgId) { toast.warn('Select your organization first'); return; }
    const ex = a.my_offer || null;
    const c = await txContext();
    const body = document.createElement('div');
    body.innerHTML = `
      <div class="mb-2">${kvTable([
        ['Player WAR', fmtNum(a.war, 1)], ['Min AAV', money(a.min_aav)], ['Phase', auctionPhaseBadge(a.phase)], ['Your budget', '<span data-budget>…</span>'],
      ], { html: true })}</div>
      ${formGrid([
        field.number('years', 'Years', { value: ex ? ex.years : 1, min: 1, max: 5 }),
        field.number('bonus', 'Signing bonus ($)', { value: ex ? ex.bonus : 0, min: 0, step: 100000 }),
        field.select('level_id', 'Assign to level', OFFER_LEVELS, { value: ex ? ex.level_id : 9 }),
      ])}
      <div class="form-grid" data-sal>${salaryFields(ex ? ex.years : 1, ex ? ex.salaries : [], { step: 100000 })}</div>
      <div class="row mb-1"><span>Total value: <strong data-total>$0</strong></span><span>AAV: <strong data-aav>$0</strong></span></div>
      <div class="alert alert-warning" data-warn hidden></div>
      <pre class="result-box" data-result></pre>`;

    api.get(v1(`/transactions/signing-budget/${orgId}`), { params: { league_year_id: c.league_year_id }, quiet: true })
      .then(d => { body.querySelector('[data-budget]').textContent = money(d.available_budget || 0); })
      .catch(() => { body.querySelector('[data-budget]').textContent = 'N/A'; });

    const yearsInp = body.querySelector('[name="years"]');
    const totals = () => {
      const years = Math.max(1, Number(yearsInp.value) || 1);
      const bonus = Number(body.querySelector('[name="bonus"]').value) || 0;
      const sal = readSalaries(body, years).reduce((s, v) => s + v, 0);
      const total = sal + bonus, aav = total / years;
      body.querySelector('[data-total]').textContent = money(total);
      body.querySelector('[data-aav]').textContent = money(Math.round(aav));
      const warn = body.querySelector('[data-warn]');
      if (sal > 0 && aav < Number(a.min_aav)) { warn.textContent = `AAV (${money(Math.round(aav))}) is below the player minimum (${money(a.min_aav)})`; warn.hidden = false; }
      else warn.hidden = true;
    };
    yearsInp.addEventListener('change', () => {
      const yrs = Math.max(1, Math.min(5, Number(yearsInp.value) || 1));
      yearsInp.value = yrs;
      body.querySelector('[data-sal]').innerHTML = salaryFields(yrs, [], { step: 100000 });
      totals();
    });
    body.addEventListener('input', totals);
    totals();

    openModal({
      title: `${ex ? 'Update' : 'Make'} offer: ${a.player_name} (${orgSel.name(orgId)})`, body, size: 'lg',
      actions: [
        { label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close() },
        { label: 'Submit offer', cls: 'btn-primary', onClick: async (hh) => {
          const f = readForm(body);
          const years = Math.max(1, Number(f.years) || 1);
          const payload = {
            org_id: orgId, years, salaries: readSalaries(body, years), bonus: Number(f.bonus) || 0, level_id: Number(f.level_id) || 9,
            league_year_id: c.league_year_id, game_week_id: c.game_week_id, current_week: c.week, executed_by: 'admin',
          };
          const out = body.querySelector('[data-result]');
          out.textContent = 'Submitting…';
          try {
            const r = await api.post(v1(`/fa-auction/${a.auction_id}/offer`), payload);
            q(el, '#fa-result').textContent = json(r);
            toast.success(`Offer submitted for ${a.player_name}`);
            hh.close();
            await load();
          } catch (e) { out.textContent = `Error: ${e.message}`; }
        } },
      ],
    });
  }

  async function advancePhases() {
    const c = await txContext();
    if (!await confirm({ title: 'Advance all FA auction phases?', danger: true, confirmLabel: 'Advance',
      message: `open → listening → finalize → signed, for every open auction in league year ${c.league_year_id} (current week ${c.week}). Finalize-phase auctions sign their winning offer.` })) return;
    const r = await api.post(v1('/fa-auction/advance-phases'), { league_year_id: c.league_year_id, current_week: c.week });
    q(el, '#fa-result').textContent = json(r);
    showResult('Phase advance result', r);
    await load();
  }

  async function enterPlayer() {
    const v = await promptText({ title: 'Enter player into FA auction', label: 'Player ID', type: 'number', okLabel: 'Enter' });
    if (v === null || v === '') return;
    const playerId = Number(v);
    if (!playerId) { toast.warn('Invalid player ID'); return; }
    const c = await txContext();
    if (!await confirm({ title: `Enter player #${playerId}?`, confirmLabel: 'Enter', message: `Creates an open auction in league year ${c.league_year_id} (current week ${c.week}). Use this for players who cleared waivers or finished contracts but never entered auction.` })) return;
    const r = await api.post(v1('/fa-auction/admin/enter-player'), { player_id: playerId, league_year_id: c.league_year_id, current_week: c.week });
    q(el, '#fa-result').textContent = json(r);
    toast.success(`Player #${playerId} entered into auction`);
    await load();
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'load') await load();
      else if (a === 'advance') await advancePhases();
      else if (a === 'enter') await enterPlayer();
      else if (a === 'offer') { const row = board.find(x => String(x.auction_id) === btn.dataset.id); if (row) await openOffer(row); }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await load();
}
