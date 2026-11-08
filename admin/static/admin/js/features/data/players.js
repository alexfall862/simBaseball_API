// features/data/players.js — player search + lookup (port of legacy #section-players).
//
// The legacy tab called GET /api/v1/players/<id>, which was removed in the canonical displayovr
// refactor (see players/__init__.py). This tab uses the admin roster search plus the stats and
// scouting endpoints instead.

import { api, v1, adm } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q } from '../../core/html.js';
import { json } from '../../core/format.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { dataTable } from '../../ui/table.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { levelSelect, leagueYearSelect } from '../../ui/selectors.js';
import { badge } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { showResult } from '../../ui/modal.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Roster search</h3><p class="card-sub text-muted"><code>GET /admin/players/search</code> — name search over active rosters at one level (2+ characters, max 50 rows).</p></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="ps-q">Name</label><input type="text" id="ps-q" placeholder="e.g. Smith" autocomplete="off" /></div>
        <div class="form-group"><label for="ps-level">Level</label><select id="ps-level"></select></div>
        <div class="form-group"><label for="ps-ly">League year</label><select id="ps-ly"></select></div>
        <div class="form-group"><label for="ps-limit">Limit</label><select id="ps-limit"><option value="25">25</option><option value="50">50</option></select></div>
        <button class="btn btn-primary" data-action="search">Search</button>
      </div>
      <div id="ps-table"></div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h3>Player lookup</h3><p class="card-sub text-muted">Season stats: <code>GET /api/v1/stats/player/&lt;id&gt;</code>. Scouting view: <code>GET /api/v1/scouting/player/&lt;id&gt;?org_id=&amp;league_year_id=</code> (fog-of-war as seen by that org).</p></div>
      </div>
      <div class="alert alert-info small">The legacy <code>GET /api/v1/players/&lt;id&gt;</code> raw-row endpoint no longer exists; use the SQL console (<code>SELECT * FROM simbbPlayers WHERE id = …</code>) for the raw row.</div>
      ${raw(formGrid([
        field.number('player_id', 'Player ID', { min: 1, placeholder: 'e.g. 52480' }),
        field.number('org_id', 'Viewing org ID (scouting view)', { min: 1, placeholder: 'optional' }),
      ]))}
      <div class="button-group">
        <button class="btn btn-primary" data-action="stats">Season stats</button>
        <button class="btn btn-secondary" data-action="career">Career</button>
        <button class="btn btn-secondary" data-action="scouting">Scouting view</button>
        <button class="btn btn-ghost" data-action="raw" hidden>Open in modal</button>
      </div>
      <div class="text-muted small mt-1" id="pl-meta"></div>
      <pre class="result-box mt-1" id="pl-result"></pre>
    </div>`);

  levelSelect(q(el, '#ps-level'), { levels: ALL_LEVELS, value: 9, remember: 'players-search', signal: ctx.signal });
  const ly = await leagueYearSelect(q(el, '#ps-ly'), { signal: ctx.signal });
  if (ctx.params.id) q(el, '[name="player_id"]').value = ctx.params.id;

  const table = dataTable(q(el, '#ps-table'), {
    rowKey: 'player_id', emptyText: 'Type at least 2 characters and search.', compact: true,
    columns: [
      { key: 'player_id', title: 'ID', cellClass: 'mono' },
      { key: 'name', title: 'Name', sortable: true },
      { key: 'ptype', title: 'Type', html: true, render: r => badge(r.ptype || '--', r.ptype === 'Pitcher' ? 'info' : 'secondary') },
      { key: 'primary_pos', title: 'Pos', render: r => r.primary_pos || '--' },
      { key: 'age', title: 'Age', align: 'right', sortable: true },
      { key: 'team_abbrev', title: 'Team', render: r => r.team_abbrev || '--', sortable: true },
      { key: '_a', title: '', html: true, render: r => `<div class="row nowrap"><button class="btn btn-xs btn-secondary" data-action="pick" data-id="${html`${r.player_id}`}">Stats</button><button class="btn btn-xs btn-ghost" data-action="pick-scout" data-id="${html`${r.player_id}`}">Scouting</button></div>` },
    ],
  });

  let lastResult = null;
  let lastTitle = '';
  const meta = q(el, '#pl-meta');
  const out = q(el, '#pl-result');

  async function search() {
    const qv = q(el, '#ps-q').value.trim();
    if (qv.length < 2) { toast.warn('Enter at least 2 characters'); return; }
    table.setLoading();
    try {
      const d = await api.get(adm('/players/search'), {
        params: { q: qv, league_level: q(el, '#ps-level').value, league_year_id: ly.get() || undefined, limit: q(el, '#ps-limit').value },
        signal: ctx.signal,
      });
      table.setRows(d.players || []);
    } catch (e) { if (e.name !== 'AbortError') table.setError(e.message); }
  }

  function playerId() {
    const id = readForm(el).player_id;
    if (!id) { toast.warn('Enter a player ID'); return null; }
    ctx.setParams({ id });
    return id;
  }

  async function show(title, loader) {
    meta.textContent = 'Loading…';
    out.textContent = '';
    q(el, '[data-action="raw"]').hidden = true;
    try {
      lastResult = await loader();
      lastTitle = title;
      const p = lastResult && (lastResult.player || lastResult);
      const name = p && (p.name || [p.firstName, p.lastName].filter(Boolean).join(' '));
      meta.textContent = `${title}${name ? ` — ${name}` : ''}`;
      out.textContent = json(lastResult);
      q(el, '[data-action="raw"]').hidden = false;
    } catch (e) {
      if (e.name === 'AbortError') return;
      meta.textContent = '';
      out.textContent = `Error: ${e.message}`;
    }
  }

  on(q(el, '#ps-q'), 'keydown', (e) => { if (e.key === 'Enter') search(); }, ctx.signal);
  on(q(el, '[name="player_id"]'), 'keydown', (e) => { if (e.key === 'Enter') q(el, '[data-action="stats"]').click(); }, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'search') return search();
    if (a === 'pick' || a === 'pick-scout') {
      q(el, '[name="player_id"]').value = btn.dataset.id;
      q(el, a === 'pick' ? '[data-action="stats"]' : '[data-action="scouting"]').click();
      return;
    }
    if (a === 'raw' && lastResult) { showResult(lastTitle, lastResult); return; }
    const id = playerId();
    if (!id) return;
    const lyid = ly.get() || undefined;
    if (a === 'stats') return show(`Season stats for player ${id}`, () => api.get(v1(`/stats/player/${id}`), { params: { league_year_id: lyid }, signal: ctx.signal }));
    if (a === 'career') return show(`Career for player ${id}`, () => api.get(v1(`/stats/player/${id}/career`), { signal: ctx.signal }));
    if (a === 'scouting') {
      const orgId = readForm(el).org_id;
      if (!orgId) { toast.warn('Scouting view needs a viewing org ID'); return; }
      if (!lyid) { toast.warn('Scouting view needs a league year'); return; }
      return show(`Scouting view of player ${id} (org ${orgId})`, () => api.get(v1(`/scouting/player/${id}`), { params: { org_id: orgId, league_year_id: lyid }, signal: ctx.signal }));
    }
  }, ctx.signal);
}
