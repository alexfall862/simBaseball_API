// features/data/assignments.js — who runs which org.
// Pending join requests (MLB + college) and the seat grid (MLB owner/GM/manager/scout,
// college coach). Backend: admin/routes_assignments.py (GET/POST /admin/assignments/*).

import { api, adm } from '../../core/api.js';
import { html, raw, esc, setHtml, on, delegate, q } from '../../core/html.js';
import { dataTable } from '../../ui/table.js';
import { subTabs } from '../../ui/tabs.js';
import { openModal, confirm } from '../../ui/modal.js';
import { badge } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { fmtDate } from '../../core/format.js';

const LEAGUES = [{ id: 'mlb', title: 'MLB' }, { id: 'college', title: 'College' }];

function orgLabel(o) {
  if (!o) return '';
  return o.team_name ? `${o.org_abbrev} — ${o.team_name}` : (o.org_abbrev || `Org ${o.org_id}`);
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Pending requests</h3><p class="card-sub text-muted">Users asking to join an org. Approving here refuses if the seat was filled since the request was made (you can choose to replace the holder).</p></div>
        <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button>
      </div>
      <div id="asg-pending"></div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h3>Seats</h3><p class="card-sub text-muted">Click a seat to assign, clear, or move its holder. Values are the username strings stored on <code>organizations</code>; a vacant college coach is stored as <code>AI</code>.</p></div>
      </div>
      <div class="form-row">
        <div id="asg-league"></div>
        <div class="form-group"><label for="asg-filter">Filter</label><input type="search" id="asg-filter" placeholder="org, team or username" /></div>
        <div class="form-group"><label for="asg-show">Show</label>
          <select id="asg-show">
            <option value="all">All orgs</option>
            <option value="filled">Orgs with a user</option>
            <option value="vacant">Orgs with a vacant seat</option>
          </select>
        </div>
      </div>
      <div id="asg-status" class="text-muted small"></div>
      <div id="asg-table" class="mt-1"></div>
    </div>`);

  let data = { mlb: [], college: [], pending: [], roles: { mlb: {}, college: {} } };
  let league = LEAGUES.some(l => l.id === ctx.params.league) ? ctx.params.league : 'mlb';

  const orgById = () => {
    const m = new Map();
    for (const lg of ['mlb', 'college']) for (const o of data[lg] || []) m.set(o.org_id, { ...o, league: lg });
    return m;
  };

  /** Every seat a username holds, across both leagues. */
  function seatsOf(username) {
    const out = [];
    if (!username) return out;
    const u = username.toLowerCase();
    for (const lg of ['mlb', 'college']) {
      for (const o of data[lg] || []) {
        for (const [role, holder] of Object.entries(o.seats || {})) {
          if (holder && holder.toLowerCase() === u) out.push({ league: lg, org: o, role });
        }
      }
    }
    return out;
  }
  const seatText = (s) => `${data.roles[s.league][s.role] || s.role} of ${s.org.org_abbrev}`;

  // ---- pending table --------------------------------------------------------
  const pendingTable = dataTable(q(el, '#asg-pending'), {
    emptyText: 'No pending requests.',
    sortKey: 'created_at',
    columns: [
      { key: 'league', title: 'League', sortable: true, render: r => r.league.toUpperCase() },
      { key: 'username', title: 'User', sortable: true },
      { key: 'org', title: 'Org', sortable: true, render: r => orgLabel(r) || `Org ${r.org_id}`, sortValue: r => r.org_abbrev },
      { key: 'role', title: 'Seat', sortable: true, render: r => (data.roles[r.league] || {})[r.role] || r.role },
      { key: 'created_at', title: 'Requested', sortable: true, nowrap: true, render: r => (r.created_at ? fmtDate(r.created_at) : '') },
      {
        key: 'seat_holder', title: 'Seat now', html: true,
        render: r => (r.seat_holder ? badge(`held by ${r.seat_holder}`, 'warning') : badge('vacant', 'success')),
      },
      {
        key: '_other', title: 'User already holds', html: true,
        render: r => {
          const s = seatsOf(r.username);
          return s.length ? esc(s.map(seatText).join(', ')) : '<span class="text-muted">—</span>';
        },
      },
      {
        key: '_act', title: '', html: true, nowrap: true,
        render: r => `<div class="button-group">
          <button class="btn btn-xs btn-primary" data-action="approve" data-league="${esc(r.league)}" data-id="${r.id}">Approve</button>
          <button class="btn btn-xs btn-ghost" data-action="reject" data-league="${esc(r.league)}" data-id="${r.id}">Reject</button></div>`,
      },
    ],
  });

  // ---- seat grid ------------------------------------------------------------
  const seatTable = dataTable(q(el, '#asg-table'), {
    rowKey: 'org_id', sortKey: 'org', emptyText: 'No organizations match.', columns: [],
  });
  function seatCell(o, role) {
    const holder = o.seats[role];
    const multi = holder && seatsOf(holder).length > 1;
    const lbl = holder ? esc(holder) : '<span class="text-muted">+ assign</span>';
    const flag = multi ? ` ${badge('multi', 'info', { title: seatsOf(holder).map(seatText).join(', ') })}` : '';
    return `<button class="btn btn-xs btn-ghost" data-action="seat" data-org="${o.org_id}" data-role="${esc(role)}">${lbl}</button>${flag}`;
  }

  function seatColumns() {
    const roles = Object.entries(data.roles[league] || {});
    return [
      { key: 'org', title: 'Org', sortable: true, render: orgLabel, sortValue: r => r.org_abbrev },
      ...roles.map(([role, title]) => ({
        key: `seat_${role}`, title, sortable: true, html: true, nowrap: true,
        render: r => seatCell(r, role),
        sortValue: r => r.seats[role] || null,
      })),
      {
        key: 'has_token', title: 'API token', sortable: true, html: true,
        render: r => (r.has_token ? badge('issued', 'secondary') : '<span class="text-muted">—</span>'),
        sortValue: r => (r.has_token ? 1 : 0),
      },
    ];
  }

  function visibleOrgs() {
    const f = q(el, '#asg-filter').value.trim().toLowerCase();
    const show = q(el, '#asg-show').value;
    return (data[league] || []).filter(o => {
      const holders = Object.values(o.seats);
      if (show === 'filled' && !holders.some(Boolean)) return false;
      if (show === 'vacant' && holders.every(Boolean)) return false;
      if (!f) return true;
      return [o.org_abbrev, o.team_name, ...holders].some(v => v && String(v).toLowerCase().includes(f));
    });
  }

  function renderSeats() {
    seatTable.setColumns(seatColumns());
    const rows = visibleOrgs();
    seatTable.setRows(rows);
    const all = data[league] || [];
    const users = new Set(all.flatMap(o => Object.values(o.seats).filter(Boolean)));
    q(el, '#asg-status').textContent = `${rows.length} of ${all.length} orgs shown · ${users.size} distinct users seated`;
  }

  async function load() {
    pendingTable.setLoading();
    try {
      data = await api.get(adm('/assignments'), { signal: ctx.signal });
      pendingTable.setRows(data.pending || []);
      renderSeats();
    } catch (e) {
      if (e.name !== 'AbortError') { pendingTable.setError(e.message); q(el, '#asg-status').textContent = e.message; }
    }
  }

  const tabs = subTabs(q(el, '#asg-league'), LEAGUES, {
    active: league, signal: ctx.signal,
    onSelect: (id) => { league = id; ctx.setParams({ league: id }); seatTable.setSort('org'); renderSeats(); },
  });
  void tabs;

  // ---- actions --------------------------------------------------------------
  function tokenReminder(abbrev) {
    toast.warn(`${abbrev} has an API token issued. Seats don't rotate it — rotate the token if the previous holder had it.`);
  }

  /** POST that asks to replace the holder on a seat_taken 409, then retries with overwrite. */
  async function postWithOverwrite(url, body, what) {
    try {
      return await api.post(url, body, { quiet: true, signal: ctx.signal });
    } catch (e) {
      if (e.code !== 'seat_taken') { toast.error(e.message); throw e; }
      const ok = await confirm({
        title: 'Seat is taken', danger: true, confirmLabel: 'Replace holder',
        message: `${e.message} ${what} will remove ${e.body && e.body.holder ? e.body.holder : 'them'} from the seat.`,
      });
      if (!ok) return null;
      return api.post(url, { ...body, overwrite: true }, { signal: ctx.signal });
    }
  }

  async function approve(lg, id) {
    const r = (data.pending || []).find(p => p.league === lg && p.id === id);
    if (!r) return;
    const res = await postWithOverwrite(adm(`/assignments/requests/${lg}/${id}/approve`), {}, 'Approving');
    if (!res) return;
    toast.success(`${res.username} is now ${(data.roles[lg] || {})[res.role] || res.role} of ${res.org_abbrev}`
      + (res.displaced ? ` (replaced ${res.displaced})` : ''));
    await load();
  }

  async function reject(lg, id) {
    const r = (data.pending || []).find(p => p.league === lg && p.id === id);
    if (!r) return;
    const ok = await confirm({
      title: 'Reject request', danger: true, confirmLabel: 'Reject',
      message: `Reject ${r.username}'s request for ${(data.roles[lg] || {})[r.role] || r.role} of ${r.org_abbrev || 'org ' + r.org_id}? The request is deleted.`,
    });
    if (!ok) return;
    await api.post(adm(`/assignments/requests/${lg}/${id}/reject`), {}, { signal: ctx.signal });
    toast.success('Request rejected');
    await load();
  }

  function openSeat(orgId, role) {
    const org = orgById().get(orgId);
    if (!org) return;
    const lg = org.league;
    const roleTitle = data.roles[lg][role] || role;
    const holder = org.seats[role] || '';

    const h = openModal({
      title: `${roleTitle} — ${orgLabel(org)}`,
      body: html`
        <p>Current: ${holder ? raw(`<strong>${esc(holder)}</strong>`) : raw('<span class="text-muted">vacant</span>')}</p>
        ${holder && seatsOf(holder).length > 1 ? raw(`<p class="text-muted small">${esc(holder)} also holds: ${esc(seatsOf(holder).filter(s => !(s.org.org_id === orgId && s.role === role)).map(seatText).join(', '))}</p>`) : ''}
        <label class="form-group"><span>${holder ? 'Replace with username' : 'Assign username'}</span>
          <input type="text" id="seat-user" autocomplete="off" placeholder="username" /></label>
        <p id="seat-hint" class="text-muted small"></p>`,
      actions: [],
    });
    const inp = h.body.querySelector('#seat-user');
    const hint = h.body.querySelector('#seat-hint');
    on(inp, 'input', () => {
      const s = seatsOf(inp.value.trim());
      hint.textContent = s.length ? `Already holds: ${s.map(seatText).join(', ')}` : '';
    }, ctx.signal);

    const save = async () => {
      const username = inp.value.trim();
      if (!username) { toast.warn('Enter a username (or use Clear seat)'); return; }
      if (username === holder) { h.close(); return; }
      const res = await postWithOverwrite(adm('/assignments/set'), { org_id: orgId, role, username }, 'Saving');
      if (!res) return;
      h.close();
      toast.success(`${username} is now ${roleTitle} of ${org.org_abbrev}` + (res.previous ? ` (replaced ${res.previous})` : ''));
      if (res.previous && res.has_token) tokenReminder(org.org_abbrev);
      await load();
    };
    on(inp, 'keydown', (e) => { if (e.key === 'Enter') save(); }, ctx.signal);

    const actions = [{ label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close() }];
    if (holder) {
      actions.push({
        label: 'Clear seat', cls: 'btn-danger', onClick: async (hh) => {
          const ok = await confirm({
            title: 'Clear seat', danger: true, confirmLabel: 'Clear',
            message: `Remove ${holder} as ${roleTitle} of ${org.org_abbrev}?${lg === 'college' ? ' The org goes back to AI control.' : ''}`,
          });
          if (!ok) return;
          const res = await api.post(adm('/assignments/set'), { org_id: orgId, role, username: '' }, { signal: ctx.signal });
          hh.close();
          toast.success(`Cleared ${roleTitle} of ${org.org_abbrev}`);
          if (res.has_token) tokenReminder(org.org_abbrev);
          await load();
        },
      });
      actions.push({ label: 'Move to…', cls: 'btn-secondary', onClick: (hh) => { hh.close(); openMove(org, role, holder); } });
    }
    actions.push({ label: holder ? 'Replace' : 'Assign', cls: 'btn-primary', onClick: save });
    h.setActions(actions);
    setTimeout(() => inp.focus(), 60);
  }

  function openMove(fromOrg, fromRole, username) {
    const all = [...(data.mlb || []).map(o => ({ ...o, league: 'mlb' })), ...(data.college || []).map(o => ({ ...o, league: 'college' }))];
    const opts = all.map(o => `<option value="${o.org_id}"${o.org_id === fromOrg.org_id ? ' selected' : ''}>${esc((o.league === 'mlb' ? 'MLB · ' : 'College · ') + orgLabel(o))}</option>`).join('');
    const h = openModal({
      title: `Move ${username}`,
      body: `<p class="text-muted small">From ${esc(data.roles[fromOrg.league][fromRole])} of ${esc(fromOrg.org_abbrev)}. The old seat is cleared in the same step.</p>
        <label class="form-group"><span>Target org</span><select id="mv-org">${opts}</select></label>
        <label class="form-group"><span>Target seat</span><select id="mv-role"></select></label>
        <p id="mv-hint" class="text-muted small"></p>`,
      actions: [],
    });
    const orgSel = h.body.querySelector('#mv-org');
    const roleSel = h.body.querySelector('#mv-role');
    const hint = h.body.querySelector('#mv-hint');
    const target = () => all.find(o => o.org_id === Number(orgSel.value));
    const fillRoles = () => {
      const t = target();
      roleSel.innerHTML = Object.entries(data.roles[t.league]).map(([r, title]) =>
        `<option value="${esc(r)}"${t.org_id === fromOrg.org_id && r === fromRole ? ' disabled' : ''}>${esc(title)}${t.seats[r] ? ` (${esc(t.seats[r])})` : ' (vacant)'}</option>`).join('');
      const firstOk = [...roleSel.options].find(op => !op.disabled);
      if (firstOk) roleSel.value = firstOk.value;
      showHint();
    };
    const showHint = () => {
      const t = target();
      const cur = t && t.seats[roleSel.value];
      hint.textContent = cur && cur !== username ? `${cur} currently holds this seat and will be removed.` : '';
    };
    on(orgSel, 'change', fillRoles, ctx.signal);
    on(roleSel, 'change', showHint, ctx.signal);
    fillRoles();

    h.setActions([
      { label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close() },
      {
        label: 'Move', cls: 'btn-primary', onClick: async (hh) => {
          const t = target();
          const toRole = roleSel.value;
          if (!t || !toRole) return;
          const res = await postWithOverwrite(adm('/assignments/move'), {
            username, from_org_id: fromOrg.org_id, from_role: fromRole, to_org_id: t.org_id, to_role: toRole,
          }, 'Moving');
          if (!res) return;
          hh.close();
          toast.success(`${username} moved to ${data.roles[t.league][toRole]} of ${t.org_abbrev}` + (res.displaced ? ` (replaced ${res.displaced})` : ''));
          if (res.from_has_token) tokenReminder(fromOrg.org_abbrev);
          await load();
        },
      },
    ]);
  }

  on(q(el, '#asg-filter'), 'input', renderSeats, ctx.signal);
  on(q(el, '#asg-show'), 'change', renderSeats, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await load();
      else if (a === 'approve') await approve(btn.dataset.league, Number(btn.dataset.id));
      else if (a === 'reject') await reject(btn.dataset.league, Number(btn.dataset.id));
      else if (a === 'seat') openSeat(Number(btn.dataset.org), btn.dataset.role);
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await load();
}
