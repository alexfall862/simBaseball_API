// features/market/txlog.js — transaction log, detail, rollback, bulk clear (port of legacy #section-tx-log).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { fmtDate, json } from '../../core/format.js';
import { dataTable, kvTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { field } from '../../ui/form.js';
import { openModal, confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { orgSelect, txContext, money } from './_shared.js';

const TX_TYPES = ['promote', 'demote', 'ir_place', 'ir_activate', 'release', 'buyout', 'signing', 'extension', 'trade',
  'renewal', 'arb_renewal', 'fa_offer', 'fa_offer_update', 'fa_auction_sign', 'draft_sign', 'draft_pick_trade'];

const TX_KIND = {
  promote: 'info', demote: 'info', ir_place: 'warning', ir_activate: 'warning',
  release: 'danger', buyout: 'danger', signing: 'success', extension: 'success', trade: 'primary',
  fa_auction_sign: 'success', draft_sign: 'success', draft_pick_trade: 'primary',
};

/** Types the backend refuses to bulk-delete (PROTECTED_TYPES). */
const PROTECTED = new Set(['release', 'trade', 'signing', 'extension', 'buyout', 'fa_auction_sign']);
const CLEARABLE = ['promote', 'demote', 'ir_place', 'ir_activate', 'renewal', 'arb_renewal', 'fa_offer', 'fa_offer_update'];

const label = (t) => String(t || '').replace(/_/g, ' ');

function orgOf(e, orgs) {
  return e.primary_org_abbrev || (e.primary_org_id ? orgs.name(e.primary_org_id) : '--');
}

function summary(e, orgs) {
  const d = e.details || {};
  const player = e.player_name || (e.player_id ? `#${e.player_id}` : '?');
  const org = orgOf(e, orgs);
  const org2 = e.secondary_org_abbrev || (e.secondary_org_id ? orgs.name(e.secondary_org_id) : null);
  switch (e.transaction_type) {
    case 'promote': return `${player} promoted L${d.from_level} → L${d.to_level} (${org})`;
    case 'demote': return `${player} demoted L${d.from_level} → L${d.to_level} (${org})`;
    case 'ir_place': return `${player} placed on IR (${org})`;
    case 'ir_activate': return `${player} activated from IR (${org})`;
    case 'release': return `${player} released by ${org} (${d.years_remaining || '?'}yr remaining)`;
    case 'buyout': return `${player} bought out by ${org} for ${d.buyout_amount != null ? money(d.buyout_amount) : '?'}`;
    case 'signing': return `${player} signed by ${org} (${d.years || '?'}yr, ${d.salaries ? money(d.salaries[0]) : '?'}/yr)`;
    case 'extension': return `${player} extended by ${org} (${d.years || '?'}yr)`;
    case 'trade': {
      const cash = d.cash_a_to_b ? `, ${money(d.cash_a_to_b)} cash` : '';
      return `Trade: ${org} ↔ ${org2 || '?'} (${(d.players_to_b || []).length} → / ${(d.players_to_a || []).length} ←${cash})`;
    }
    default: {
      const n = e.notes || '';
      return n.length > 80 ? `${n.slice(0, 80)}…` : (n || '--');
    }
  }
}

function detailRows(e, orgs) {
  const d = e.details || {};
  const rows = [
    ['Transaction ID', String(e.id)],
    ['Type', `${badge(label(e.transaction_type), TX_KIND[e.transaction_type] || 'secondary')}${(e.notes || '').includes('ROLLBACK') ? ` ${badge('ROLLED BACK', 'secondary')}` : ''}`],
    ['Time', esc(fmtDate(e.executed_at || e.created_at))],
    ['Player', esc(e.player_name || (e.player_id ? `Player #${e.player_id}` : 'N/A'))],
    ['Primary org', esc(e.primary_org_abbrev ? `${e.primary_org_abbrev} (#${e.primary_org_id})` : `${orgs.name(e.primary_org_id)}`)],
  ];
  if (e.secondary_org_id) rows.push(['Secondary org', esc(e.secondary_org_abbrev ? `${e.secondary_org_abbrev} (#${e.secondary_org_id})` : orgs.name(e.secondary_org_id))]);
  if (e.league_year_id != null) rows.push(['League year ID', esc(e.league_year_id)]);
  if (e.notes) rows.push(['Notes', esc(e.notes)]);
  const sal = (arr) => (arr || []).map(s => money(s)).join(' / ');
  switch (e.transaction_type) {
    case 'promote': case 'demote':
      rows.push(['Level change', `Level ${esc(d.from_level)} → Level ${esc(d.to_level)}`]); break;
    case 'release':
      rows.push(['Years remaining', esc(d.years_remaining ?? '--')], ['Level at release', esc(d.current_level ?? '--')], ['Affected detail IDs', esc((d.affected_detail_ids || []).join(', ') || '--')]); break;
    case 'buyout':
      rows.push(['Buyout amount', esc(d.buyout_amount != null ? money(d.buyout_amount) : '--')], ['Original contract', `#${esc(d.original_contract_id ?? '--')}`], ['Buyout contract', `#${esc(d.buyout_contract_id ?? '--')}`]); break;
    case 'signing':
      rows.push(['Years', esc(d.years ?? '--')]);
      if (d.salaries) rows.push(['Salaries', esc(sal(d.salaries))]);
      if (d.bonus) rows.push(['Bonus', esc(money(d.bonus))]);
      rows.push(['Level', esc(d.level_id ?? '--')]); break;
    case 'extension':
      rows.push(['Years', esc(d.years ?? '--')]);
      if (d.salaries) rows.push(['Salaries', esc(sal(d.salaries))]);
      if (d.bonus) rows.push(['Bonus', esc(money(d.bonus))]);
      rows.push(['Original contract', `#${esc(d.original_contract_id ?? '--')}`], ['Extension contract', `#${esc(d.extension_contract_id ?? '--')}`], ['Starts league year', esc(d.starts_league_year ?? '--')]); break;
    case 'trade': {
      if (d.players_to_b && d.players_to_b.length) rows.push([`Players to ${e.secondary_org_abbrev || 'Org B'}`, esc(d.players_to_b.map(p => `#${p}`).join(', '))]);
      if (d.players_to_a && d.players_to_a.length) rows.push([`Players to ${e.primary_org_abbrev || 'Org A'}`, esc(d.players_to_a.map(p => `#${p}`).join(', '))]);
      if (d.cash_a_to_b) rows.push(['Cash', esc(`${money(d.cash_a_to_b)} (${e.primary_org_abbrev || 'A'} → ${e.secondary_org_abbrev || 'B'})`)]);
      if (d.salary_retention && Object.keys(d.salary_retention).length) {
        rows.push(['Salary retention', Object.entries(d.salary_retention).map(([pid, info]) => esc(`Player #${pid}: ${((info.retention_pct || 0) * 100).toFixed(0)}% retained by Org #${info.retaining_org_id ?? '?'}`)).join('<br>')]);
      }
      if (d.share_mutations && d.share_mutations.length) rows.push(['Share mutations', `${d.share_mutations.length} contract-year transfers`]);
      break;
    }
    default: break;
  }
  return rows;
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <h3>Transaction log</h3>
        <div class="row">
          <select id="tl-type"><option value="">All types</option>${raw(TX_TYPES.map(t => `<option value="${t}">${esc(label(t))}</option>`).join(''))}</select>
          <select id="tl-org"></select>
          <input type="number" id="tl-player" placeholder="Player ID" title="Player ID" />
          <input type="number" id="tl-limit" value="50" min="1" max="500" placeholder="Limit" title="Limit" />
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div id="tl-table"></div>
    </div>

    <div class="card danger-zone">
      <h3>Bulk clear log entries</h3>
      <p class="text-muted small mb-2">Deletes transaction log entries by category for the current league year to reduce DB size (POST /transactions/log/bulk-delete). Trades, signings, extensions, releases, buyouts and auction signings are protected by the backend.</p>
      <div class="form-row">
        ${raw(field.select('bulk_types', 'Categories to clear', CLEARABLE.map(t => ({ value: t, label: label(t) })), { multiple: true }))}
        <button class="btn btn-danger" data-action="bulk">Clear selected</button>
      </div>
      <p class="text-muted small">Protected: ${[...PROTECTED].map(label).join(', ')}.</p>
      <pre class="result-box" id="tl-bulk-result"></pre>
    </div>`);

  const orgSel = await orgSelect(q(el, '#tl-org'), { signal: ctx.signal, placeholder: 'Any org' });
  const sel = q(el, '[name="bulk_types"]');
  sel.size = CLEARABLE.length;
  if (ctx.params.type) q(el, '#tl-type').value = ctx.params.type;
  if (ctx.params.player_id) q(el, '#tl-player').value = ctx.params.player_id;

  let entries = [];
  const table = dataTable(q(el, '#tl-table'), {
    rowKey: 'id', emptyText: 'No transactions found.', pageSize: 100,
    rowClass: r => ((r.notes || '').includes('ROLLBACK') ? 'text-muted' : ''),
    columns: [
      { key: 'id', title: 'ID', width: '70px', sortable: true },
      { key: 'executed_at', title: 'Time', nowrap: true, sortable: true, render: r => fmtDate(r.executed_at || r.created_at), sortValue: r => r.executed_at || r.created_at },
      { key: 'transaction_type', title: 'Type', html: true, sortable: true, render: r => badge(label(r.transaction_type), TX_KIND[r.transaction_type] || 'secondary') },
      { key: 'primary_org_id', title: 'Org', sortable: true, render: r => orgOf(r, orgSel) },
      { key: 'player_id', title: 'Player', render: r => r.player_name || (r.player_id ? `#${r.player_id}` : '--') },
      { key: '_s', title: 'Summary', render: r => summary(r, orgSel) },
      { key: '_a', title: '', html: true, nowrap: true, render: r => {
        const rolled = (r.notes || '').includes('ROLLBACK');
        return `<div class="row nowrap"><button class="btn btn-xs btn-secondary" data-action="detail" data-id="${r.id}">Detail</button>`
          + (rolled ? '<span class="text-muted small">rolled back</span>' : `<button class="btn btn-xs btn-danger" data-action="rollback" data-id="${r.id}">Rollback</button>`)
          + `<button class="btn btn-xs btn-ghost" data-action="delete" data-id="${r.id}" title="Delete log entry">&times;</button></div>`;
      } },
    ],
  });

  async function load() {
    table.setLoading();
    const params = {
      limit: q(el, '#tl-limit').value || 50,
      type: q(el, '#tl-type').value,
      org_id: orgSel.get(),
      player_id: q(el, '#tl-player').value,
    };
    ctx.setParams({ type: params.type || undefined, player_id: params.player_id || undefined });
    try {
      const rows = await api.get(v1('/transactions/log'), { signal: ctx.signal, params });
      entries = Array.isArray(rows) ? rows : [];
      table.setRows(entries);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }

  async function getEntry(id) {
    const cached = entries.find(x => x.id === id);
    if (cached) return cached;
    const rows = await api.get(v1('/transactions/log'), { params: { limit: 1, tx_id: id } });
    return Array.isArray(rows) && rows[0] ? rows[0] : null;
  }

  async function openDetail(id) {
    const e = await getEntry(id);
    if (!e) { toast.error(`Transaction #${id} not found`); return; }
    const body = `${kvTable(detailRows(e, orgSel), { html: true })}
      <details class="mt-2"><summary class="text-muted small">Raw JSON</summary><pre class="result-box mt-1">${esc(json(e))}</pre></details>`;
    const rolled = (e.notes || '').includes('ROLLBACK');
    openModal({ title: `Transaction #${id}`, body, size: 'lg', actions: [
      ...(rolled ? [] : [{ label: 'Rollback', cls: 'btn-danger', onClick: async (hh) => { if (await rollback(id)) hh.close(); } }]),
      { label: 'Close', cls: 'btn-secondary' },
    ] });
  }

  async function rollback(id) {
    const e = entries.find(x => x.id === id);
    const who = e ? (e.player_name || `Player #${e.player_id}`) : '';
    if (!await confirm({ title: `Rollback transaction #${id}?`, danger: true, confirmLabel: 'Rollback',
      message: e ? `Reverses the ${label(e.transaction_type)} of ${who}. Contract/share mutations and ledger entries are undone.` : 'This reverses the operation.' })) return false;
    const r = await api.post(v1('/transactions/rollback'), { transaction_id: id, executed_by: 'admin' });
    toast.success(`Transaction #${id} rolled back`);
    void r;
    await load();
    return true;
  }

  async function del(id) {
    if (!await confirm({ title: `Delete log entry #${id}?`, danger: true, confirmLabel: 'Delete', message: 'Only removes the log record, not the underlying data.' })) return;
    await api.del(v1(`/transactions/log/${id}`));
    toast.success(`Log entry #${id} deleted`);
    await load();
  }

  async function bulk() {
    const types = Array.from(sel.selectedOptions).map(o => o.value).filter(t => !PROTECTED.has(t));
    if (!types.length) { toast.warn('Select at least one category'); return; }
    const { league_year_id } = await txContext();
    if (!await confirm({ title: `Clear ${types.length} categor${types.length === 1 ? 'y' : 'ies'}?`, danger: true, typeToConfirm: 'CLEAR', confirmLabel: 'Clear',
      message: `Deletes all ${types.map(label).join(', ')} entries for league year ID ${league_year_id}.` })) return;
    const d = await api.post(v1('/transactions/log/bulk-delete'), { league_year_id, types });
    q(el, '#tl-bulk-result').textContent = `Deleted ${d.deleted_count} entries (types: ${(d.types || types).join(', ')}, league year ${d.league_year_id ?? league_year_id})`;
    toast.success(`Deleted ${d.deleted_count} log entries`);
    await load();
  }

  for (const id of ['#tl-type', '#tl-org', '#tl-limit']) on(q(el, id), 'change', load, ctx.signal);
  on(q(el, '#tl-player'), 'keydown', (e) => { if (e.key === 'Enter') load(); }, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action, id = Number(btn.dataset.id);
    try {
      if (a === 'refresh') await load();
      else if (a === 'detail') await openDetail(id);
      else if (a === 'rollback') await rollback(id);
      else if (a === 'delete') await del(id);
      else if (a === 'bulk') await bulk();
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await load();
}
