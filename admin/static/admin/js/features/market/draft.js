// features/market/draft.js — draft administration (port of legacy #section-draft-admin).
// Admin endpoints under /draft/admin/* require the admin session cookie, which api.js sends.

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { fmtDate, fmtNum } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm, promptText } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { leagueYearSelect, fillSelect } from '../../ui/selectors.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { money, setStatus, parseIdList } from './_shared.js';

const PHASE_KIND = { SETUP: 'warning', IN_PROGRESS: 'running', PAUSED: 'info', SIGNING: 'primary', COMPLETE: 'success' };
const SIGN_KIND = { signed: 'success', pending: 'warning', passed: 'danger', refused: 'danger' };
const signBadge = (s) => (s ? badge(s, SIGN_KIND[s] || 'secondary') : '<span class="text-muted">—</span>');

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Draft administration</h3><p class="card-sub text-muted">Lifecycle: SETUP → IN_PROGRESS (live/auto rounds) → SIGNING (bonus negotiation) → COMPLETE. See docs/draft_frontend_guide.md.</p></div>
        <div class="row"><select id="dft-ly"></select><button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button></div>
      </div>
      <div id="dft-status"></div>
      <div id="dft-progress"></div>
    </div>

    <div class="card" id="dft-state-card" hidden>
      <h3>Draft state</h3>
      <div class="row mb-2" id="dft-state-info"></div>
      <div class="row mb-2" id="dft-round-strip"></div>
      <div class="button-group" id="dft-actions"></div>
    </div>

    <div class="card" id="dft-init-card" hidden>
      <h3>Initialize new draft</h3>
      <p class="text-muted small mb-2">No draft exists for this league year. POST /draft/admin/initialize builds the pick order from reverse standings.</p>
      ${raw(formGrid([
        field.number('total_rounds', 'Total rounds', { value: 20, min: 1, max: 40 }),
        field.number('seconds_per_pick', 'Seconds per pick', { value: 60, min: 10, max: 600 }),
        field.text('live_rounds', 'Live rounds (comma-separated)', { value: '1,2,3', placeholder: '1,2,3' }),
        field.checkbox('is_snake', 'Snake draft'),
      ]))}
      <div class="button-group"><button class="btn btn-primary" data-action="initialize">Initialize draft</button></div>
    </div>

    <div class="card" id="dft-modes-card" hidden>
      <h3>Round mode configuration</h3>
      <p class="text-muted small mb-2">Click a round to toggle between ${raw(badge('LIVE', 'primary'))} and ${raw(badge('AUTO', 'pending'))}. Saved immediately (POST /draft/admin/round-modes).</p>
      <div class="button-group" id="dft-modes"></div>
    </div>

    <div class="card" id="dft-board-card" hidden>
      <div class="card-head">
        <h3>Draft board</h3>
        <div class="row"><label class="small text-muted">Round <select id="dft-round-filter"></select></label></div>
      </div>
      <div id="dft-board"></div>
    </div>

    <div class="card" id="dft-override-card" hidden>
      <h3>Pick overrides</h3>
      <div class="grid-2">
        <div>
          <h4 class="mb-1">Assign pick</h4>
          ${raw(formGrid([
            field.number('ov_round', 'Round', { min: 1, placeholder: 'Round' }),
            field.number('ov_pick', 'Pick in round', { min: 1, placeholder: 'Pick #' }),
            field.number('ov_player', 'Player ID', { min: 1, placeholder: 'Player ID' }),
          ]))}
          <button class="btn btn-warning" data-action="set-pick">Assign pick</button>
        </div>
        <div>
          <h4 class="mb-1">Rollback pick</h4>
          ${raw(formGrid([field.number('ov_pick_id', 'Draft pick ID', { min: 1, placeholder: 'Pick ID from board' })]))}
          <button class="btn btn-danger" data-action="remove-pick">Rollback pick</button>
        </div>
      </div>
    </div>

    <div class="card" id="dft-signing-card" hidden>
      <div class="card-head">
        <div><h3>Signing status</h3><p class="card-sub text-muted">Bonus negotiation: up to three offers per pick; the player's ask is only visible to the drafting org.</p></div>
        <div class="row"><label class="small text-muted">Status <select id="dft-sign-filter"><option value="">All</option><option value="pending">Pending</option><option value="signed">Signed</option><option value="passed">Passed</option><option value="refused">Refused</option></select></label></div>
      </div>
      <div id="dft-signing"></div>
    </div>`);

  const statusEl = q(el, '#dft-status');
  const progress = progressWidget(q(el, '#dft-progress'));
  const ly = await leagueYearSelect(q(el, '#dft-ly'), { signal: ctx.signal, onChange: () => load() });
  const lyid = () => ly.get();

  let state = null;
  let picks = [];
  let pollTimer = null;
  ctx.signal.addEventListener('abort', () => clearTimeout(pollTimer));

  const boardTable = dataTable(q(el, '#dft-board'), {
    rowKey: 'pick_id', emptyText: 'No picks.', pageSize: 100, compact: true,
    rowClass: r => (state && state.phase === 'IN_PROGRESS' && r.round === state.current_round && r.pick_in_round === state.current_pick ? 'row-warning' : ''),
    columns: [
      { key: 'pick_id', title: 'Pick ID', sortable: true },
      { key: 'round', title: 'Rd', sortable: true },
      { key: 'pick_in_round', title: 'Pick', sortable: true },
      { key: 'overall_pick', title: 'Overall', sortable: true },
      { key: 'current_org_id', title: 'Org', html: true, sortable: true, render: r => `${esc(r.current_org_id)}${r.current_org_id !== r.original_org_id ? ` <span class="text-warning small">(from ${esc(r.original_org_id)})</span>` : ''}` },
      { key: 'player_name', title: 'Player', html: true, sortable: true, render: r => (r.player_name ? esc(r.player_name) : '<span class="text-muted">—</span>') },
      { key: 'picked_at', title: 'Picked at', render: r => (r.picked_at ? fmtDate(r.picked_at) : '—') },
      { key: 'is_auto_pick', title: 'Auto', render: r => (r.is_auto_pick ? '⚙' : '') },
      { key: 'slot_value', title: 'Slot value', align: 'right', render: r => (r.slot_value != null ? money(r.slot_value) : '—'), sortValue: r => Number(r.slot_value) },
      { key: 'sign_status', title: 'Sign status', html: true, sortable: true, render: r => signBadge(r.sign_status) },
    ],
  });
  const signTable = dataTable(q(el, '#dft-signing'), {
    rowKey: 'pick_id', emptyText: 'No drafted players.', pageSize: 100, compact: true,
    columns: [
      { key: 'pick_id', title: 'Pick ID', sortable: true },
      { key: 'round', title: 'Rd', sortable: true },
      { key: 'pick_in_round', title: 'Pick', sortable: true },
      { key: 'current_org_id', title: 'Org', sortable: true },
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'class_year', title: 'Class', render: r => r.class_year || '' },
      { key: 'slot_value', title: 'Slot value', align: 'right', render: r => money(r.slot_value), sortValue: r => Number(r.slot_value) },
      { key: 'offers_made', title: 'Offers', align: 'right', render: r => `${r.offers_made ?? 0}/3` },
      { key: 'bonus_agreed', title: 'Bonus agreed', align: 'right', render: r => (r.bonus_agreed != null ? money(r.bonus_agreed) : '—') },
      { key: 'sign_status', title: 'Status', html: true, sortable: true, render: r => signBadge(r.sign_status) },
      { key: '_a', title: '', html: true, nowrap: true, render: r => (r.sign_status === 'pending'
        ? `<div class="row nowrap"><button class="btn btn-xs btn-primary" data-action="sign" data-id="${r.pick_id}">Sign</button><button class="btn btn-xs btn-secondary" data-action="pass" data-id="${r.pick_id}">Pass</button></div>` : '') },
    ],
  });

  const show = (id, on_) => { q(el, id).hidden = !on_; };

  async function load() {
    clearTimeout(pollTimer);
    const id = lyid();
    if (!id) return;
    ctx.setParams({ ly: id });
    try {
      state = await api.get(v1('/draft/state'), { params: { league_year_id: id }, signal: ctx.signal, quiet: true });
    } catch (e) {
      if (e.name === 'AbortError') return;
      state = null;
      if (e.status === 400 || e.status === 404) {
        setStatus(statusEl, '');
        for (const c of ['#dft-state-card', '#dft-modes-card', '#dft-board-card', '#dft-override-card', '#dft-signing-card']) show(c, false);
        show('#dft-init-card', true);
        return;
      }
      setStatus(statusEl, e.message, 'danger');
      return;
    }
    setStatus(statusEl, '');
    show('#dft-init-card', false);
    show('#dft-state-card', true);
    renderState();
    renderActions();
    show('#dft-modes-card', state.phase === 'SETUP');
    show('#dft-override-card', ['IN_PROGRESS', 'PAUSED', 'SIGNING'].includes(state.phase));
    show('#dft-board-card', state.phase !== 'SETUP');
    show('#dft-signing-card', state.phase === 'SIGNING' || state.phase === 'COMPLETE');
    const jobs = [loadRoundModes()];
    if (state.phase !== 'SETUP') jobs.push(loadBoard());
    await Promise.all(jobs);
    if (state.phase === 'IN_PROGRESS') pollTimer = setTimeout(load, 10000);
  }

  function renderState() {
    const s = state;
    const bits = [badge(s.phase, PHASE_KIND[s.phase] || 'secondary'),
      `<span>Round <strong>${esc(s.current_round)}</strong> / ${esc(s.total_rounds)}</span>`,
      `<span>Pick <strong>${esc(s.current_pick)}</strong> / ${esc(s.picks_per_round)}</span>`];
    if (s.seconds_remaining != null && s.phase === 'IN_PROGRESS') bits.push(`<span><strong>${esc(s.seconds_remaining)}s</strong> remaining</span>`);
    if (s.seconds_per_pick != null) bits.push(`<span class="text-muted small">${esc(s.seconds_per_pick)}s per pick${s.is_snake ? ' · snake' : ''}</span>`);
    if (s.current_round_mode === 'auto') bits.push(badge('AUTO ROUND', 'pending'));
    if (s.auto_rounds_locked) bits.push(badge('PREFS LOCKED', 'info'));
    setHtml(q(el, '#dft-state-info'), raw(bits.join(' ')));
  }

  function renderActions() {
    const b = (action, label, cls) => `<button class="btn ${cls}" data-action="${action}">${label}</button>`;
    let h = '';
    switch (state.phase) {
      case 'SETUP': h = b('start', 'Start draft', 'btn-primary'); break;
      case 'IN_PROGRESS':
        h = b('pause', 'Pause', 'btn-warning') + b('reset-timer', 'Reset timer', 'btn-secondary');
        if (state.current_round_mode === 'auto') h += b('run-auto', 'Run auto rounds', 'btn-primary');
        h += b('advance-signing', 'Advance to signing', 'btn-secondary');
        break;
      case 'PAUSED': h = b('resume', 'Resume', 'btn-primary') + b('advance-signing', 'Advance to signing', 'btn-secondary'); break;
      case 'SIGNING': h = b('export', 'Export draft', 'btn-warning') + b('complete', 'Complete draft', 'btn-secondary'); break;
      default: h = '<span class="text-muted">Draft complete.</span>';
    }
    setHtml(q(el, '#dft-actions'), raw(h));
  }

  async function loadRoundModes() {
    let rounds = [];
    try {
      const d = await api.get(v1('/draft/round-modes'), { params: { league_year_id: lyid() }, signal: ctx.signal, quiet: true });
      rounds = d.rounds || [];
    } catch (_) { rounds = []; }
    setHtml(q(el, '#dft-round-strip'), raw(rounds.map(r => {
      const cur = state && r.round === state.current_round && state.phase === 'IN_PROGRESS';
      return badge(`R${r.round}`, cur ? 'success' : (r.mode === 'live' ? 'primary' : 'pending'), { title: `Round ${r.round}: ${r.mode}${cur ? ' (current)' : ''}` });
    }).join(' ')));
    if (state && state.phase === 'SETUP') {
      setHtml(q(el, '#dft-modes'), raw(rounds.map(r =>
        `<button class="btn btn-sm ${r.mode === 'live' ? 'btn-primary' : 'btn-secondary'}" data-action="toggle-mode" data-round="${r.round}" data-mode="${esc(r.mode)}">R${r.round} ${esc(r.mode.toUpperCase())}</button>`).join('')));
    }
  }

  async function loadBoard() {
    boardTable.setLoading();
    try {
      const d = await api.get(v1('/draft/board'), { params: { league_year_id: lyid() }, signal: ctx.signal, quiet: true });
      picks = d.picks || [];
    } catch (e) { if (e.name !== 'AbortError') boardTable.setError(e.message); return; }
    const maxRound = picks.reduce((m, p) => Math.max(m, p.round), 0);
    const rf = q(el, '#dft-round-filter');
    const want = Array.from({ length: maxRound }, (_, i) => i + 1);
    if (rf.options.length !== want.length + 1) fillSelect(rf, want.map(r => ({ value: r, label: `Round ${r}` })), { placeholder: 'All rounds' });
    renderBoard();
    if (!q(el, '#dft-signing-card').hidden) renderSigning();
  }

  function renderBoard() {
    const r = q(el, '#dft-round-filter').value;
    boardTable.setRows(r ? picks.filter(p => p.round === Number(r)) : picks);
  }
  function renderSigning() {
    const f = q(el, '#dft-sign-filter').value;
    const drafted = picks.filter(p => p.player_id != null);
    signTable.setRows(f ? drafted.filter(p => p.sign_status === f) : drafted);
  }

  async function adminPost(action, okMsg, body = {}) {
    const r = await api.post(v1(`/draft/admin/${action}`), { league_year_id: lyid(), ...body });
    setStatus(statusEl, typeof okMsg === 'function' ? okMsg(r) : okMsg, 'success');
    toast.success(typeof okMsg === 'function' ? okMsg(r) : okMsg);
    await load();
    return r;
  }

  async function signPick(pickId) {
    const p = picks.find(x => x.pick_id === pickId);
    const v = await promptText({ title: `Sign pick ${pickId}${p ? ` — ${p.player_name}` : ''}`, label: 'Signing bonus offer ($). Blank = slot value.', type: 'number', value: p && p.slot_value != null ? String(Math.round(p.slot_value)) : '', okLabel: 'Make offer' });
    if (v === null) return;
    const body = { league_year_id: lyid(), executed_by: 'admin' };
    if (v !== '' && !Number.isNaN(Number(v))) body.bonus = Number(v);
    const d = await api.post(v1(`/draft/sign/${pickId}`), body);
    if (d.accepted === false) {
      const msg = `${d.player_name} rejected offer #${d.offer_no} (${money(d.offer)}; ask ${money(d.ask_bonus)}) — ${d.status === 'refused' ? 'REFUSED, returns to school' : `${d.offers_remaining} offer(s) left`}`;
      setStatus(statusEl, msg, 'warning');
      toast.warn(msg);
    } else {
      const msg = `Signed ${d.player_name} — ${d.years}yr, bonus ${money(d.bonus)}${d.ask_bonus != null ? ` (ask ${money(d.ask_bonus)})` : ''}`;
      setStatus(statusEl, msg, 'success');
      toast.success(msg);
    }
    await loadBoard();
  }

  on(q(el, '#dft-round-filter'), 'change', renderBoard, ctx.signal);
  on(q(el, '#dft-sign-filter'), 'change', renderSigning, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await load();
      else if (a === 'initialize') {
        const f = readForm(q(el, '#dft-init-card'));
        const live = parseIdList(f.live_rounds);
        if (!await confirm({ title: `Initialize draft for league year ${lyid()}?`, confirmLabel: 'Initialize', message: `${f.total_rounds} rounds, ${f.seconds_per_pick}s per pick, live rounds ${live.join(', ') || 'none'}${f.is_snake ? ', snake' : ''}.` })) return;
        await runTracked({ el: q(el, '#dft-progress'), widget: progress, label: 'Initializing draft…', signal: ctx.signal,
          start: () => api.post(v1('/draft/admin/initialize'), { league_year_id: lyid(), total_rounds: f.total_rounds, seconds_per_pick: f.seconds_per_pick, is_snake: !!f.is_snake, live_rounds: live }),
          onDone: (d) => setStatus(statusEl, `Draft initialized — ${fmtNum(d.total_picks)} picks, ${fmtNum(d.eligible_players)} eligible players`, 'success') });
        await load();
      } else if (a === 'start') await adminPost('start', 'Draft started');
      else if (a === 'pause') await adminPost('pause', 'Draft paused');
      else if (a === 'resume') await adminPost('resume', 'Draft resumed');
      else if (a === 'reset-timer') await adminPost('reset-timer', 'Timer reset');
      else if (a === 'advance-signing') {
        if (!await confirm({ title: 'Advance to signing phase?', danger: true, confirmLabel: 'Advance', message: 'No more picks can be made after this.' })) return;
        await adminPost('advance-signing', 'Advanced to signing');
      } else if (a === 'export') {
        if (!await confirm({ title: 'Export draft?', confirmLabel: 'Export', message: 'Moves signed players to their drafting orgs (no-op if signing already handled it).' })) return;
        await adminPost('export', 'Draft exported', { executed_by: 'admin' });
      } else if (a === 'complete') {
        if (!await confirm({ title: 'Mark draft complete?', danger: true, confirmLabel: 'Complete', message: 'Closes the signing window. Unsigned picks are passed.' })) return;
        await adminPost('complete', 'Draft completed');
      } else if (a === 'run-auto') {
        if (!await confirm({ title: 'Run all auto rounds?', confirmLabel: 'Run', message: 'Executes every remaining auto-round pick for all teams. This may take a moment.' })) return;
        await runTracked({ el: q(el, '#dft-progress'), widget: progress, label: 'Running auto rounds…', signal: ctx.signal,
          start: () => api.post(v1('/draft/admin/run-auto-rounds'), { league_year_id: lyid() }),
          onDone: (d) => setStatus(statusEl, `Auto rounds complete — ${fmtNum(d.picks_made)} picks made`, 'success') });
        await load();
      } else if (a === 'toggle-mode') {
        const round = Number(btn.dataset.round), newMode = btn.dataset.mode === 'live' ? 'auto' : 'live';
        btn.disabled = true;
        try {
          await api.post(v1('/draft/admin/round-modes'), { league_year_id: lyid(), round_modes: { [round]: newMode } });
          toast.success(`Round ${round} set to ${newMode.toUpperCase()}`);
          await loadRoundModes();
        } finally { btn.disabled = false; }
      } else if (a === 'set-pick') {
        const f = readForm(q(el, '#dft-override-card'));
        if (!f.ov_round || !f.ov_pick || !f.ov_player) { toast.warn('Fill in round, pick and player ID'); return; }
        if (!await confirm({ title: `Assign player ${f.ov_player} to R${f.ov_round} P${f.ov_pick}?`, danger: true, confirmLabel: 'Assign', message: 'Force-assigns the player to that pick slot, replacing any existing pick.' })) return;
        const d = await api.post(v1('/draft/admin/set-pick'), { league_year_id: lyid(), round: f.ov_round, pick_in_round: f.ov_pick, player_id: f.ov_player });
        setStatus(statusEl, `Pick assigned: player ${d.player_id} to pick ${d.pick_id}`, 'success');
        toast.success('Pick assigned');
        await load();
      } else if (a === 'remove-pick') {
        const f = readForm(q(el, '#dft-override-card'));
        if (!f.ov_pick_id) { toast.warn('Enter a draft pick ID'); return; }
        if (!await confirm({ title: `Rollback pick ${f.ov_pick_id}?`, danger: true, confirmLabel: 'Rollback', message: 'Clears the player assignment, voids a rookie contract if already signed, and resets signing status to pending.' })) return;
        await api.post(v1('/draft/admin/remove-pick'), { draft_pick_id: f.ov_pick_id });
        setStatus(statusEl, `Pick ${f.ov_pick_id} rolled back`, 'success');
        toast.success('Pick rolled back');
        await load();
      } else if (a === 'sign') await signPick(Number(btn.dataset.id));
      else if (a === 'pass') {
        const id = Number(btn.dataset.id);
        if (!await confirm({ title: `Pass on pick ${id}?`, danger: true, confirmLabel: 'Pass', message: 'The org forfeits the player; he returns to the amateur pool.' })) return;
        await api.post(v1(`/draft/pass/${id}`), {});
        setStatus(statusEl, `Passed on pick ${id}`, 'success');
        await loadBoard();
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      setStatus(statusEl, err.message, 'danger');
    }
  }, ctx.signal);

  if (ctx.params.ly && ly.rows.some(r => String(r.id) === String(ctx.params.ly))) ly.set(Number(ctx.params.ly));
  else await load();
}
