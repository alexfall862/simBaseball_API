// features/data/teams.js — team browser (port of legacy #section-teams): team row + active roster.

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q } from '../../core/html.js';
import { fillSelect } from '../../ui/selectors.js';
import { dataTable } from '../../ui/table.js';
import { showResult } from '../../ui/modal.js';
import { json } from '../../core/format.js';
import { objectKv, unwrapList, firstRow, columnsFromRows } from './_shared.js';

function teamOption(t) {
  if (typeof t === 'string') return { value: t, label: t };
  const id = t.team_abbrev || t.team_id || t.id || t.abbreviation;
  return { value: id, label: t.name || t.team_name || t.team_abbrev || String(id) };
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Teams</h3><p class="card-sub text-muted">List: <code>GET /api/v1/teams</code>, detail: <code>GET /api/v1/teams/&lt;abbrev&gt;/</code>, roster: <code>GET /api/v1/teams/&lt;abbrev&gt;/players</code>.</p></div>
        <button class="btn btn-sm btn-ghost" data-action="refresh">Refresh list</button>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="team-select">Team</label><select id="team-select"><option value="">Loading…</option></select></div>
      </div>
      <div id="team-status" class="text-muted small"></div>
    </div>
    <div class="card" id="team-detail-card" hidden>
      <div class="card-head"><h3 id="team-detail-title">Team details</h3>
        <div class="row"><button class="btn btn-sm btn-secondary" data-action="players">View players</button><button class="btn btn-sm btn-ghost" data-action="raw-team">Raw JSON</button></div></div>
      <div id="team-detail"></div>
    </div>
    <div class="card" id="team-players-card" hidden>
      <div class="card-head"><h3 id="team-players-title">Team players</h3><div class="row"><span id="team-players-meta" class="text-muted small"></span><button class="btn btn-sm btn-ghost" data-action="raw-players">Raw JSON</button></div></div>
      <div id="team-players"></div>
    </div>`);

  const sel = q(el, '#team-select');
  const status = q(el, '#team-status');
  let teamRow = null;
  let playersData = null;

  async function loadList() {
    sel.disabled = true;
    try {
      const d = await api.get(v1('/teams'), { signal: ctx.signal });
      const opts = unwrapList(d, 'teams').map(teamOption);
      fillSelect(sel, opts, { value: ctx.params.team || null, placeholder: 'Select a team…' });
      status.textContent = `${opts.length} teams`;
      if (sel.value) await loadDetail();
    } catch (e) {
      if (e.name !== 'AbortError') { sel.innerHTML = '<option value="">Failed to load</option>'; status.textContent = e.message; }
    } finally { sel.disabled = false; }
  }

  async function loadDetail() {
    const abbrev = sel.value;
    const card = q(el, '#team-detail-card');
    q(el, '#team-players-card').hidden = true;
    teamRow = null; playersData = null;
    if (!abbrev) { card.hidden = true; return; }
    ctx.setParams({ team: abbrev });
    card.hidden = false;
    q(el, '#team-detail-title').textContent = `Team details — ${abbrev}`;
    setHtml(q(el, '#team-detail'), '<p class="text-muted">Loading…</p>');
    try {
      const d = await api.get(v1(`/teams/${encodeURIComponent(abbrev)}/`), { signal: ctx.signal });
      teamRow = firstRow(d);
      setHtml(q(el, '#team-detail'), raw(teamRow ? objectKv(teamRow) : '<p class="text-muted">No data for this team.</p>'));
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(q(el, '#team-detail'), html`<p class="text-danger">${e.message}</p>`);
    }
  }

  async function loadPlayers() {
    const abbrev = sel.value;
    if (!abbrev) return;
    const card = q(el, '#team-players-card');
    const box = q(el, '#team-players');
    card.hidden = false;
    q(el, '#team-players-title').textContent = `Team players — ${abbrev}`;
    q(el, '#team-players-meta').textContent = '';
    setHtml(box, '<p class="text-muted">Loading…</p>');
    try {
      playersData = await api.get(v1(`/teams/${encodeURIComponent(abbrev)}/players`), { signal: ctx.signal });
      const rows = unwrapList(playersData, 'players');
      if (rows.length && typeof rows[0] === 'object') {
        q(el, '#team-players-meta').textContent = `${rows.length} players`;
        dataTable(box, { columns: columnsFromRows(rows), rows, pageSize: 50, compact: true, emptyText: 'No players.' });
      } else {
        q(el, '#team-players-meta').textContent = rows.length ? `${rows.length} entries` : '';
        setHtml(box, html`<pre class="result-box">${json(playersData)}</pre>`);
      }
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(box, html`<p class="text-danger">${e.message}</p>`);
    }
  }

  on(sel, 'change', loadDetail, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'refresh') await loadList();
      else if (a === 'players') await loadPlayers();
      else if (a === 'raw-team' && teamRow) showResult(`Team ${sel.value}`, teamRow);
      else if (a === 'raw-players' && playersData) showResult(`Players ${sel.value}`, playersData);
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await loadList();
}
