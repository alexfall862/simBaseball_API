// features/market/ifa.js — IFA signing period administration (port of legacy #section-ifa-admin).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { leagueYearSelect } from '../../ui/selectors.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { money, stars, setStatus, auctionPhaseBadge, windowStatusBadge, playerName } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>IFA signing administration</h3><p class="card-sub text-muted">International amateur window: weeks advance manually; each advance ranks players (week 0→1), allocates bonus pools and moves auctions open → listening → finalize → signed.</p></div>
        <div class="row"><select id="ifa-ly"></select><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
      </div>
      <div id="ifa-status"></div>
      <div id="ifa-progress"></div>
    </div>

    <div class="card" id="ifa-state-card" hidden>
      <h3>Window state</h3>
      <div class="row mb-2" id="ifa-state-info"></div>
      <div class="button-group">
        <button class="btn btn-warning" data-action="advance" id="ifa-advance">Advance week</button>
        <button class="btn btn-danger" data-action="reset">Reset window</button>
      </div>
    </div>

    <div class="card" id="ifa-pools-card" hidden><h3>Bonus pools</h3><div id="ifa-pools"></div></div>
    <div class="card" id="ifa-auctions-card" hidden><h3>Active auctions</h3><div id="ifa-auctions"></div></div>
    <div class="card" id="ifa-eligible-card" hidden>
      <div class="card-head">
        <h3>Eligible players (no active auction)</h3>
        <div class="row"><label class="small text-muted">Stars <select id="ifa-star"><option value="">All</option><option value="5">5-star</option><option value="4">4-star</option><option value="3">3-star</option><option value="2">2-star</option><option value="1">1-star</option></select></label><span class="text-muted small" id="ifa-eligible-count"></span></div>
      </div>
      <div id="ifa-eligible"></div>
    </div>
    <div class="card" id="ifa-history-card" hidden><h3>Completed &amp; expired auctions</h3><div id="ifa-history"></div></div>`);

  const statusEl = q(el, '#ifa-status');
  const progress = progressWidget(q(el, '#ifa-progress'));
  const ly = await leagueYearSelect(q(el, '#ifa-ly'), { signal: ctx.signal, onChange: () => load() });
  const lyid = () => ly.get();
  let state = null;
  let eligible = [];

  const poolsTable = dataTable(q(el, '#ifa-pools'), {
    rowKey: 'org_id', emptyText: 'No pools allocated yet.', compact: true, sortKey: 'standing_rank', pageSize: 50,
    rowClass: r => { const pct = r.total_pool > 0 ? (r.spent + r.committed) / r.total_pool : 0; return pct >= 0.9 ? 'row-danger' : pct >= 0.7 ? 'row-warning' : ''; },
    columns: [
      { key: 'standing_rank', title: 'Rank', sortable: true },
      { key: 'team_abbrev', title: 'Org', sortable: true },
      { key: 'total_pool', title: 'Total pool', align: 'right', sortable: true, render: r => money(r.total_pool) },
      { key: 'spent', title: 'Spent', align: 'right', sortable: true, render: r => money(r.spent) },
      { key: 'committed', title: 'Committed', align: 'right', sortable: true, render: r => money(r.committed) },
      { key: 'remaining', title: 'Remaining', align: 'right', sortable: true, render: r => money(r.remaining) },
      { key: '_u', title: 'Used', align: 'right', render: r => (r.total_pool > 0 ? `${Math.round((r.spent + r.committed) / r.total_pool * 100)}%` : '--'), sortValue: r => (r.total_pool > 0 ? (r.spent + r.committed) / r.total_pool : 0), sortable: true },
    ],
  });
  const auctionsTable = dataTable(q(el, '#ifa-auctions'), {
    rowKey: 'auction_id', emptyText: 'No active auctions.', compact: true, pageSize: 100, sortKey: 'slot_value', sortDir: 'desc',
    columns: [
      { key: '_n', title: 'Player', sortable: true, render: r => playerName(r), sortValue: r => playerName(r) },
      { key: 'ptype', title: 'Type', sortable: true },
      { key: 'age', title: 'Age', sortable: true },
      { key: 'star_rating', title: 'Stars', sortable: true, render: r => stars(r.star_rating) },
      { key: 'slot_value', title: 'Slot', align: 'right', sortable: true, render: r => money(r.slot_value) },
      { key: 'phase', title: 'Phase', html: true, sortable: true, render: r => auctionPhaseBadge(r.phase) },
      { key: 'entered_week', title: 'Entered wk', sortable: true },
      { key: 'active_offers', title: 'Offers', align: 'right', sortable: true },
      { key: 'competitors', title: 'Competitors', render: r => ((r.competitors || []).length ? r.competitors.join(', ') : '—') },
    ],
  });
  const eligibleTable = dataTable(q(el, '#ifa-eligible'), {
    rowKey: 'player_id', emptyText: 'No eligible players.', compact: true, pageSize: 100, sortKey: 'slot_value', sortDir: 'desc',
    columns: [
      { key: '_n', title: 'Player', sortable: true, render: r => playerName(r), sortValue: r => playerName(r) },
      { key: 'player_id', title: 'ID' },
      { key: 'ptype', title: 'Type', sortable: true },
      { key: 'age', title: 'Age', sortable: true },
      { key: 'area', title: 'Area', sortable: true, render: r => r.area || '—' },
      { key: 'star_rating', title: 'Stars', sortable: true, render: r => stars(r.star_rating) },
      { key: 'slot_value', title: 'Slot value', align: 'right', sortable: true, render: r => money(r.slot_value) },
    ],
  });
  const historyTable = dataTable(q(el, '#ifa-history'), {
    rowKey: 'auction_id', emptyText: 'No completed auctions.', compact: true, pageSize: 100,
    columns: [
      { key: '_n', title: 'Player', sortable: true, render: r => playerName(r), sortValue: r => playerName(r) },
      { key: 'ptype', title: 'Type', sortable: true },
      { key: 'star_rating', title: 'Stars', sortable: true, render: r => stars(r.star_rating) },
      { key: 'slot_value', title: 'Slot', align: 'right', sortable: true, render: r => money(r.slot_value) },
      { key: 'phase', title: 'Result', html: true, sortable: true, render: r => (r.phase === 'completed' ? badge('Signed', 'success') : badge('Expired', 'secondary')) },
      { key: 'winner_abbrev', title: 'Winner', sortable: true, render: r => r.winner_abbrev || '—' },
      { key: 'winning_bonus', title: 'Bonus', align: 'right', sortable: true, render: r => (r.winning_bonus != null ? money(r.winning_bonus) : '—'), sortValue: r => Number(r.winning_bonus) },
    ],
  });

  const show = (id, on_) => { q(el, id).hidden = !on_; };

  async function load() {
    const id = lyid();
    if (!id) return;
    ctx.setParams({ ly: id });
    try {
      state = await api.get(v1('/ifa/state'), { params: { league_year_id: id }, signal: ctx.signal, quiet: true });
    } catch (e) {
      if (e.name === 'AbortError') return;
      setStatus(statusEl, e.message, 'danger');
      for (const c of ['#ifa-state-card', '#ifa-pools-card', '#ifa-auctions-card', '#ifa-eligible-card', '#ifa-history-card']) show(c, false);
      return;
    }
    setStatus(statusEl, '');
    show('#ifa-state-card', true);
    setHtml(q(el, '#ifa-state-info'), raw(`${windowStatusBadge(state.status)} <span>Week <strong>${esc(state.current_week)}</strong> / ${esc(state.total_weeks)}</span>`));
    const adv = q(el, '#ifa-advance');
    adv.disabled = state.status === 'complete';
    adv.textContent = state.status === 'complete' ? 'Window complete'
      : (Number(state.current_week) === 0 ? 'Initialize window (week 0 → 1)' : `Advance to week ${Number(state.current_week) + 1}`);

    const p = { league_year_id: id };
    const [pools, board, elig, hist] = await Promise.allSettled([
      api.get(v1('/ifa/pools'), { params: p, signal: ctx.signal, quiet: true }),
      api.get(v1('/ifa/board'), { params: p, signal: ctx.signal, quiet: true }),
      api.get(v1('/ifa/eligible'), { params: p, signal: ctx.signal, quiet: true }),
      api.get(v1('/ifa/history'), { params: p, signal: ctx.signal, quiet: true }),
    ]);
    const poolRows = pools.status === 'fulfilled' && Array.isArray(pools.value) ? pools.value : [];
    show('#ifa-pools-card', poolRows.length > 0); poolsTable.setRows(poolRows);
    const auctions = board.status === 'fulfilled' ? (board.value.auctions || []) : [];
    show('#ifa-auctions-card', auctions.length > 0); auctionsTable.setRows(auctions);
    eligible = elig.status === 'fulfilled' && Array.isArray(elig.value) ? elig.value : [];
    show('#ifa-eligible-card', eligible.length > 0); renderEligible();
    const histRows = hist.status === 'fulfilled' && Array.isArray(hist.value) ? hist.value : [];
    show('#ifa-history-card', histRows.length > 0); historyTable.setRows(histRows);
  }

  function renderEligible() {
    const star = q(el, '#ifa-star').value;
    const rows = star ? eligible.filter(p => Number(p.star_rating) === Number(star)) : eligible;
    q(el, '#ifa-eligible-count').textContent = `${fmtNum(rows.length)} of ${fmtNum(eligible.length)} shown`;
    eligibleTable.setRows(rows);
  }
  on(q(el, '#ifa-star'), 'change', renderEligible, ctx.signal);

  async function advance() {
    if (!state) return;
    const wk = Number(state.current_week);
    if (!await confirm({ title: wk === 0 ? 'Initialize the IFA window?' : `Advance IFA to week ${wk + 1}?`, confirmLabel: 'Advance',
      message: wk === 0 ? 'Ranks the international amateur pool and allocates bonus pools by inverse standings.' : 'Processes phase transitions (open → listening → finalize → signed) and expiries.' })) return;
    await runTracked({ el: q(el, '#ifa-progress'), widget: progress, label: 'Advancing IFA week…', signal: ctx.signal,
      start: () => api.post(v1('/ifa/advance-week'), { league_year_id: lyid() }),
      onDone: (d) => {
        let msg = `Advanced to week ${d.new_week} (${d.status})`;
        if (d.players_ranked) msg += ` — ${fmtNum(d.players_ranked)} players ranked`;
        if (d.pools_allocated) msg += `, ${d.pools_allocated} pools allocated`;
        const pt = d.phase_transitions;
        if (pt) {
          const parts = [];
          if (pt.open_to_listening) parts.push(`${pt.open_to_listening} → listening`);
          if (pt.listening_to_finalize) parts.push(`${pt.listening_to_finalize} → finalize`);
          if (pt.finalize_to_completed) parts.push(`${pt.finalize_to_completed} signed`);
          if (pt.expired) parts.push(`${pt.expired} expired`);
          if (parts.length) msg += ` — ${parts.join(', ')}`;
        }
        setStatus(statusEl, msg, 'success');
        toast.success(msg);
      } });
    await load();
  }

  async function reset() {
    if (!await confirm({ title: `Reset the IFA window for league year ${lyid()}?`, danger: true, typeToConfirm: 'RESET', confirmLabel: 'Reset window',
      message: 'Reverses every IFA signing, deletes all auctions, offers, pools and rankings, and returns the window to week 0. This cannot be undone.' })) return;
    await runTracked({ el: q(el, '#ifa-progress'), widget: progress, label: 'Resetting IFA window…', signal: ctx.signal,
      start: () => api.post(v1('/ifa/reset'), { league_year_id: lyid() }),
      onDone: (d) => {
        const parts = [];
        if (d.contracts_reversed) parts.push(`${d.contracts_reversed} signings reversed`);
        if (d.auctions_deleted) parts.push(`${d.auctions_deleted} auctions deleted`);
        if (d.offers_deleted) parts.push(`${d.offers_deleted} offers deleted`);
        if (d.pools_deleted) parts.push(`${d.pools_deleted} pools deleted`);
        if (d.rankings_cleared) parts.push(`${d.rankings_cleared} rankings cleared`);
        setStatus(statusEl, `IFA window reset. ${parts.join(', ') || 'Nothing to clean up.'}`, 'success');
      } });
    toast.success('IFA window reset');
    await load();
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    try {
      const a = btn.dataset.action;
      if (a === 'refresh') await load();
      else if (a === 'advance') await advance();
      else if (a === 'reset') await reset();
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  if (ctx.params.ly && ly.rows.some(r => String(r.id) === String(ctx.params.ly))) ly.set(Number(ctx.params.ly));
  else await load();
}
