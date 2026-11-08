// features/system/orphans.js — FA orphan sweep (port of legacy #section-orphan-sweep) plus the
// debug "cancel orphan auction" endpoint that had no legacy UI.
//   GET  /admin/fa-orphan-scan                        → {ok, league_year_id, count, players:[...]}
//   POST /api/v1/fa-auction/admin/orphan-sweep        {league_year_id} → {entered, errors, players, error_details}
//   POST /admin/debug/cancel-orphan-auction/<player_id> → {ok, message, cancelled_auction_ids, ...}

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, esc, setHtml, delegate, on, q } from '../../core/html.js';
import { json } from '../../core/format.js';
import { levelName } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { kpi, badge } from '../../ui/badge.js';
import { confirm, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>FA orphan sweep</h3><p class="card-sub text-muted">Finds FA-eligible players (6+ MLB service years) with no active contract, no open auction and no active waiver claim — stuck in limbo — and enters them into the FA auction pool for the current league year.</p></div>
      </div>
      <div class="grid-3" id="orph-kpis">
        ${raw(kpi({ label: 'Orphans found', value: '--', id: 'orph-found' }))}
        ${raw(kpi({ label: 'Entered into auction', value: '--', id: 'orph-entered' }))}
        ${raw(kpi({ label: 'Errors', value: '--', id: 'orph-errors' }))}
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="scan">Scan for orphans</button>
        <button class="btn btn-warning" data-action="fix" disabled>Fix all orphans</button>
        <span class="text-muted small" id="orph-status"></span>
      </div>
      <div id="orph-progress"></div>
    </div>
    <div class="card" id="orph-results" hidden>
      <div class="card-head"><h3>Orphaned players</h3><span class="text-muted small" id="orph-ly"></span></div>
      <div id="orph-table"></div>
    </div>
    <div class="card" id="orph-fix-card" hidden>
      <div class="card-head"><h3>Fix results</h3><button class="btn btn-sm btn-ghost" data-action="fix-raw">Open in modal</button></div>
      <pre class="result-box" id="orph-fix-result"></pre>
    </div>
    <div class="card danger-zone">
      <h3>Cancel orphan auction</h3>
      <p class="text-muted small mb-2">The inverse problem: a player who already holds an active contract but still has an open auction. Marks the auction(s) completed and the active offers lost. Refuses (400) when the player has no held contract. <code>POST /admin/debug/cancel-orphan-auction/&lt;player_id&gt;</code></p>
      ${raw(formGrid([field.number('cancel_player_id', 'Player ID', { min: 1, placeholder: 'e.g. 52480' })]))}
      <button class="btn btn-danger" data-action="cancel">Cancel auction(s)</button>
      <div id="orph-cancel-progress"></div>
    </div>`);

  let scan = null;
  const status = q(el, '#orph-status');
  const progress = progressWidget(q(el, '#orph-progress'));
  const cancelProgress = progressWidget(q(el, '#orph-cancel-progress'));

  const table = dataTable(q(el, '#orph-table'), {
    rowKey: 'player_id', compact: true, sortKey: 'service_years', sortDir: 'desc', emptyText: 'No orphaned players.',
    columns: [
      { key: 'player_id', title: 'Player ID', cellClass: 'mono', sortable: true },
      { key: 'name', title: 'Name', sortable: true, html: true, render: r => `<strong>${esc(r.name)}</strong>` },
      { key: 'age', title: 'Age', align: 'right', sortable: true, render: r => r.age ?? '--' },
      { key: 'ptype', title: 'Type', render: r => r.ptype || '--' },
      { key: 'service_years', title: 'Service yrs', align: 'right', sortable: true },
      { key: 'last_level', title: 'Last level', render: r => (r.last_level ? levelName(r.last_level) : '--'), sortValue: r => r.last_level },
      { key: '_status', title: 'Status', html: true, render: r => (r._entered ? badge('Entered', 'success') : r._error ? badge('Error', 'danger', { title: r._error }) : badge('Orphaned', 'warning')) },
    ],
  });

  function setKpi(id, value, kind = '') {
    const card = q(el, `#${id}`);
    card.className = `stat-card${kind ? ` stat-${kind}` : ''}`;
    q(card, '.stat-value').textContent = value;
  }

  async function doScan() {
    status.textContent = 'Scanning…';
    setKpi('orph-found', '--'); setKpi('orph-entered', '--'); setKpi('orph-errors', '--');
    q(el, '#orph-results').hidden = true;
    q(el, '#orph-fix-card').hidden = true;
    q(el, '[data-action="fix"]').disabled = true;
    scan = null;
    try {
      scan = await api.get(adm('/fa-orphan-scan'), { signal: ctx.signal });
      setKpi('orph-found', String(scan.count), scan.count ? 'warning' : 'success');
      q(el, '#orph-ly').textContent = `league_year_id ${scan.league_year_id}`;
      status.textContent = scan.count === 0
        ? 'No orphaned players found.'
        : `Found ${scan.count} orphaned player(s). Review below, then click "Fix all orphans" to enter them into the FA auction.`;
      table.setRows(scan.players || []);
      q(el, '#orph-results').hidden = false;
      q(el, '[data-action="fix"]').disabled = !scan.count;
    } catch (e) {
      if (e.name !== 'AbortError') status.textContent = `Error: ${e.message}`;
    }
  }

  async function doFix() {
    if (!scan || !scan.league_year_id) { toast.warn('Run a scan first'); return; }
    if (!await confirm({
      title: 'Enter orphans into the FA auction?', danger: true, confirmLabel: 'Fix all orphans',
      message: `This opens an FA auction for ${scan.count} player(s) in league_year_id ${scan.league_year_id}. The server re-scans and may include players found since the scan.`,
    })) return;
    status.textContent = 'Fixing orphans…';
    q(el, '[data-action="fix"]').disabled = true;
    try {
      const d = await runTracked({ el: q(el, '#orph-progress'), widget: progress, label: 'Entering orphans into auction…', signal: ctx.signal,
        start: () => api.post(v1('/fa-auction/admin/orphan-sweep'), { league_year_id: scan.league_year_id }, { signal: ctx.signal }) });
      setKpi('orph-entered', String(d.entered ?? 0), 'success');
      setKpi('orph-errors', String(d.errors ?? 0), d.errors ? 'danger' : '');
      status.textContent = `Done. Entered ${d.entered} player(s) into auction.${d.errors > 0 ? ` ${d.errors} error(s).` : ''}`;
      q(el, '#orph-fix-result').textContent = json(d);
      q(el, '#orph-fix-card').hidden = false;
      const entered = new Set((d.players || []).map(p => p.player_id));
      const errs = new Map((d.error_details || []).map(x => [x.player_id, x.error]));
      table.setRows((scan.players || []).map(p => ({ ...p, _entered: entered.has(p.player_id), _error: errs.get(p.player_id) || null })));
      toast.success(`Entered ${d.entered} orphan(s) into the FA auction`);
    } catch (e) {
      if (e.name === 'AbortError') return;
      status.textContent = `Error: ${e.message}`;
      q(el, '[data-action="fix"]').disabled = false;
    }
  }

  async function doCancel() {
    const pid = readForm(el).cancel_player_id;
    if (!pid) { toast.warn('Enter a player ID'); return; }
    if (!await confirm({
      title: `Cancel open auctions for player ${pid}?`, danger: true, typeToConfirm: 'CANCEL', confirmLabel: 'Cancel auctions',
      message: 'Marks every open/listening/finalize auction for this player completed and all active offers lost. Only allowed when the player already holds an active contract.',
    })) return;
    try {
      const d = await runTracked({ el: q(el, '#orph-cancel-progress'), widget: cancelProgress, label: `Cancelling auctions for player ${pid}…`, signal: ctx.signal,
        start: () => api.post(adm(`/debug/cancel-orphan-auction/${pid}`), {}, { signal: ctx.signal }) });
      toast.success(d.message || 'Done');
    } catch (e) { if (e.name === 'AbortError') return; }
  }

  on(q(el, '[name="cancel_player_id"]'), 'keydown', (e) => { if (e.key === 'Enter') doCancel(); }, ctx.signal);
  delegate(el, 'click', '[data-action]', (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'scan') doScan();
    else if (a === 'fix') doFix();
    else if (a === 'cancel') doCancel();
    else if (a === 'fix-raw') showResult('Orphan sweep result', q(el, '#orph-fix-result').textContent);
  }, ctx.signal);
}
