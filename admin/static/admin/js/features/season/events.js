// features/season/events.js — Special Events: Awards, All-Star Game, WBC
// (port of legacy #section-awards, #section-allstar, #section-wbc) as three
// sub-tabs sharing one league-year selector.

import { api, v1, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, qa, esc } from '../../core/html.js';
import { SIM_LEVELS } from '../../core/constants.js';
import { json, fmtDate } from '../../core/format.js';
import { badge, statusBadge } from '../../ui/badge.js';
import { field, formGrid } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { leagueYearSelect, levelSelect } from '../../ui/selectors.js';
import { dataTable } from '../../ui/table.js';
import { subTabs } from '../../ui/tabs.js';
import { childSignal } from './_shared.js';

const SUBS = [
  { id: 'awards', title: 'Awards' },
  { id: 'allstar', title: 'All-Star Game' },
  { id: 'wbc', title: 'World Baseball Classic' },
];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="row between mb-1">
      <div id="ev-tabs"></div>
      <div class="row"><label class="small text-muted" for="ev-ly">League year</label><select id="ev-ly"></select></div>
    </div>
    <div id="ev-body"></div>`);

  let active = null;          // { controller, refresh }
  const body = q(el, '#ev-body');
  const ly = await leagueYearSelect(q(el, '#ev-ly'), { signal: ctx.signal, onChange: () => { if (active && active.refresh) active.refresh(); } });

  function open(id) {
    if (active) active.controller.abort();
    const controller = childSignal(ctx.signal);
    const sec = document.createElement('div');
    body.replaceChildren(sec);
    const deps = { signal: controller.signal, ly, params: ctx.params };
    const mounter = { awards: mountAwards, allstar: mountAllStar, wbc: mountWbc }[id] || mountAwards;
    active = { controller, refresh: null };
    Promise.resolve(mounter(sec, deps)).then(h => { if (active && active.controller === controller) active.refresh = h && h.refresh; });
  }

  const initial = SUBS.some(s => s.id === ctx.params.sub) ? ctx.params.sub : 'awards';
  subTabs(q(el, '#ev-tabs'), SUBS, { active: initial, signal: ctx.signal, onSelect: (id) => { if (ctx.setParams) ctx.setParams({ sub: id }); open(id); } });
  open(initial);
}

// ===================================================================== Awards

const AW_POS_MAP = { p: 'P', c: 'C', fb: '1B', sb: '2B', tb: '3B', ss: 'SS', lf: 'LF', cf: 'CF', rf: 'RF', dh: 'DH' };
const awPos = code => (code ? (AW_POS_MAP[String(code).toLowerCase()] || String(code).toUpperCase()) : null);
const AW_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'OF', 'DH', 'P', 'UT'];

async function mountAwards(sec, { signal, ly }) {
  setHtml(sec, html`
    <div class="card">
      <div class="card-head"><div><h3>Assign award</h3><p class="card-sub text-muted">MLB individual awards (MVP, Cy Young, Silver Slugger, Gold Glove, …). Pennants, World Series rings and All-Star selections are written automatically by the sim; use the board below to review or revoke them.</p></div></div>
      <div class="form-row">
        <div class="form-group"><label for="aw-code">Award</label><select id="aw-code"><option value="">Loading…</option></select></div>
        <div id="aw-sub-wrap"><div class="form-group"><label for="aw-sub">League</label><select id="aw-sub"><option value="AL">AL</option><option value="NL">NL</option></select></div></div>
        <div id="aw-pos-wrap" hidden><div class="form-group"><label for="aw-pos">Position</label><select id="aw-pos">${raw(AW_POSITIONS.map(p => `<option value="${p}">${p}</option>`).join(''))}</select></div></div>
        <div class="form-group"><label for="aw-rank">Rank</label><select id="aw-rank"><option value="1">1 — Winner</option><option value="2">2 — Finalist</option><option value="3">3 — Finalist</option><option value="4">4</option><option value="5">5</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="aw-q">Player (type a name)</label><input type="text" id="aw-q" placeholder="Search MLB rosters…" autocomplete="off"></div>
        <div class="form-group"><label>Selected</label><div class="form-static text-muted" id="aw-selected">none</div></div>
        <button class="btn btn-primary" data-action="assign">Assign Award</button>
      </div>
      <div id="aw-results"></div>
      <div id="aw-status" class="text-muted small mt-1"></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Season award board</h3>
        <div class="button-group">
          <button class="btn btn-sm btn-secondary" data-action="sync" title="Re-derive pennant / World Series awards from the completed playoff series">Sync Postseason Awards</button>
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>
        </div></div>
      <div id="aw-board"></div>
    </div>`);

  const st = { types: [], selected: null, hits: [], debounce: null };
  const $ = id => q(sec, `#${id}`);
  const setStatus = m => { $('aw-status').textContent = m || ''; };
  const awType = () => st.types.find(t => t.code === $('aw-code').value) || null;

  function toggleFields() {
    const t = awType();
    $('aw-sub-wrap').hidden = !(t && t.has_league_split);
    $('aw-pos-wrap').hidden = !(t && t.is_per_position);
    $('aw-q').placeholder = t && t.ptype_scope === 'pitcher' ? 'Search MLB pitchers…' : t && t.ptype_scope === 'hitter' ? 'Search MLB hitters…' : 'Search MLB rosters…';
  }

  function setSelected(p) {
    st.selected = p;
    const n = $('aw-selected');
    if (!p) { n.textContent = 'none'; n.classList.add('text-muted'); return; }
    n.classList.remove('text-muted');
    setHtml(n, html`<strong>${p.name}</strong> <span class="text-muted">(${p.team_abbrev || '—'}, ${p.ptype || ''}, id ${p.player_id})</span>`);
    $('aw-q').value = p.name;
  }

  async function search() {
    const term = $('aw-q').value.trim();
    const res = $('aw-results');
    if (term.length < 2) { setHtml(res, ''); return; }
    try {
      const d = await api.get(adm('/players/search'), { params: { q: term, league_level: 9, league_year_id: ly.get(), limit: 25 }, signal, quiet: true });
      const t = awType();
      st.hits = (d.players || []).filter(p => !t || t.ptype_scope === 'any' || !t.ptype_scope
        || (t.ptype_scope === 'pitcher' ? p.ptype === 'Pitcher' : t.ptype_scope === 'hitter' ? p.ptype !== 'Pitcher' : true));
      if (!st.hits.length) { setHtml(res, '<p class="text-muted small">No matching players on MLB rosters.</p>'); return; }
      const rows = st.hits.map(p => `<tr><td>${esc(p.name)}</td><td>${esc(p.team_abbrev || '—')}</td><td>${esc(p.ptype === 'Pitcher' ? 'P' : (awPos(p.primary_pos) || 'POS'))}</td><td>${esc(p.age ?? '')}</td><td><button class="btn btn-xs btn-secondary" data-action="pick" data-pid="${esc(p.player_id)}">Pick</button></td></tr>`).join('');
      setHtml(res, raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Name</th><th>Team</th><th>Pos</th><th>Age</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`));
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      setHtml(res, html`<p class="text-danger small">${e.message}</p>`);
    }
  }

  async function loadBoard() {
    const lyid = ly.get();
    const board = $('aw-board');
    if (!lyid) { setHtml(board, '<span class="text-muted">Pick a league year.</span>'); return; }
    setHtml(board, '<span class="text-muted">Loading…</span>');
    try {
      const d = await api.get(v1(`/awards/season/${lyid}`), { params: { league_level: 9 }, signal, quiet: true });
      const awards = d.awards || [];
      if (!awards.length) { setHtml(board, '<span class="text-muted">No awards recorded for this season yet.</span>'); return; }
      let out = '';
      awards.forEach(a => {
        const team = a.category === 'championship' || a.category === 'selection';
        const recips = (a.recipients || []).slice().sort((x, y) =>
          (x.sub_league || '').localeCompare(y.sub_league || '') || (x.position_code || '').localeCompare(y.position_code || '') || x.rank - y.rank || String(x.name).localeCompare(String(y.name)));
        out += `<h4 class="mt-2 mb-1">${esc(a.award_name)} <span class="text-muted small">· ${recips.length} recipient${recips.length === 1 ? '' : 's'}</span></h4>`;
        if (team) {   // roster-wide awards: summarize by team instead of listing 26 rows each
          const byTeam = {};
          recips.forEach(r => {
            const k = `${r.sub_league || ''}|${r.team_abbrev || r.team_id || '?'}`;
            byTeam[k] = byTeam[k] || { sub: r.sub_league, team: r.team_abbrev || r.team_id, n: 0 };
            byTeam[k].n++;
          });
          out += `<div class="table-container"><table class="data-table compact"><thead><tr><th>League</th><th>Team</th><th>Players</th></tr></thead><tbody>${Object.values(byTeam).map(t => `<tr><td>${esc(t.sub || '—')}</td><td>${esc(t.team)}</td><td>${t.n}</td></tr>`).join('')}</tbody></table></div>`;
          return;
        }
        out += `<div class="table-container"><table class="data-table compact"><thead><tr><th>League</th><th>Pos</th><th>Rank</th><th>Player</th><th>Team</th><th></th></tr></thead><tbody>${recips.map(r => `<tr>
          <td>${esc(r.sub_league || '—')}</td><td>${esc(r.position_code || '—')}</td><td>${r.is_winner ? badge('Winner', 'success') : esc(r.rank)}</td>
          <td>${esc(r.name)}</td><td>${esc(r.team_abbrev || '—')}</td>
          <td><button class="btn btn-xs btn-danger" data-action="revoke" data-id="${esc(r.award_id)}" data-label="${esc(`${a.award_name} — ${r.name}`)}">Revoke</button></td></tr>`).join('')}</tbody></table></div>`;
      });
      setHtml(board, raw(out));
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      setHtml(board, html`<span class="text-danger">${e.message}</span>`);
    }
  }

  async function assign() {
    const t = awType(), p = st.selected;
    if (!t) { setStatus('Pick an award type.'); return; }
    if (!p) { setStatus('Pick a player from the search results first.'); return; }
    const bodyData = {
      player_id: p.player_id, league_year_id: Number(ly.get()), award_code: t.code,
      sub_league: t.has_league_split ? $('aw-sub').value : '',
      position_code: t.is_per_position ? $('aw-pos').value : '',
      rank: Number($('aw-rank').value), created_by: 'admin_panel',
    };
    const label = `${bodyData.sub_league ? bodyData.sub_league + ' ' : ''}${t.name}${bodyData.position_code ? ' (' + bodyData.position_code + ')' : ''}${bodyData.rank > 1 ? ' — rank ' + bodyData.rank : ''}`;
    if (bodyData.rank === 1 && !await confirm({ title: `Assign ${label} to ${p.name}?`, message: 'Any existing winner in this slot will be replaced.' })) return;
    setStatus('Saving…');
    try {
      const j = await api.post(v1('/awards'), bodyData);
      setStatus(`Saved: ${label} → ${p.name} (award #${j.award_id}).`);
      toast.success(`${label} → ${p.name}`);
      setSelected(null); $('aw-q').value = ''; setHtml($('aw-results'), '');
      await loadBoard();
    } catch (e) { setStatus(`Error: ${e.message}`); }
  }

  async function syncPostseason() {
    setStatus('Syncing postseason awards…');
    try {
      const j = await api.post(v1('/awards/sync-postseason'), { league_year_id: Number(ly.get()) });
      const parts = (j.recorded || []).map(r => `${r.round}: ${r.award_code}${r.sub_league ? ' ' + r.sub_league : ''} × ${r.count}`);
      setStatus(`${j.series_found} completed CS/WS series found. ${parts.length ? parts.join('; ') : 'Nothing to record yet.'}`);
      await loadBoard();
    } catch (e) { setStatus(`Error: ${e.message}`); }
  }

  // --- wiring
  on($('aw-code'), 'change', toggleFields, signal);
  on($('aw-q'), 'input', () => { clearTimeout(st.debounce); st.debounce = setTimeout(search, 250); }, signal);
  on($('aw-q'), 'focus', () => { if ($('aw-q').value.trim().length >= 2 && !st.selected) search(); }, signal);
  signal.addEventListener('abort', () => clearTimeout(st.debounce), { once: true });
  delegate(sec, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'pick') {
        const p = st.hits.find(x => x.player_id === Number(btn.dataset.pid));
        setSelected(p || null); setHtml($('aw-results'), '');
        const mapped = p ? (p.ptype === 'Pitcher' ? 'P' : awPos(p.primary_pos)) : null;
        if (mapped && AW_POSITIONS.includes(mapped)) $('aw-pos').value = mapped;
      } else if (a === 'assign') await assign();
      else if (a === 'refresh') await loadBoard();
      else if (a === 'sync') await syncPostseason();
      else if (a === 'revoke') {
        if (!await confirm({ title: `Revoke ${btn.dataset.label}?`, danger: true, confirmLabel: 'Revoke' })) return;
        await api.del(v1(`/awards/${btn.dataset.id}`));
        setStatus(`Revoked ${btn.dataset.label}.`);
        toast.success(`Revoked ${btn.dataset.label}`);
        await loadBoard();
      }
    } catch (err) { if (err && err.name !== 'AbortError') setStatus(`Error: ${err.message}`); }
  }, signal);

  // --- initial loads
  api.get(v1('/awards/types'), { signal, quiet: true }).then(d => {
    st.types = d.award_types || [];
    // Individual trophies only — roster-wide awards are automatic.
    const opts = st.types.filter(t => !t.allows_multiple).map(t => `<option value="${esc(t.code)}">${esc(t.name)}</option>`).join('');
    setHtml($('aw-code'), raw(opts || '<option value="">No award types</option>'));
    toggleFields();
  }).catch(() => { setHtml($('aw-code'), '<option value="">Failed to load</option>'); });
  await loadBoard();
  return { refresh: () => { setSelected(null); loadBoard(); } };
}

// ===================================================================== All-Star

const AS_LINEUP = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];
const AS_SP = 12, AS_RP = 4, AS_BENCH = 11;

function allStarSide(side, title, label) {
  const inputs = (kind, n, ph) => Array.from({ length: n }, (_, i) =>
    `<input type="number" min="1" data-side="${side}" data-kind="${kind}" placeholder="${ph} ${i + 1}${kind === 'sp' && i === 0 ? ' (starter)' : ''}">`).join('');
  return `<div class="card">
    <h3>${title}</h3>
    ${formGrid([field.text(`as_${side}_label`, 'Team label', { value: label })])}
    <h4 class="mb-1">Starting lineup (9)</h4>
    <div class="table-container"><table class="data-table compact"><thead><tr><th style="width:70px">Pos</th><th>Player ID</th></tr></thead><tbody>
      ${AS_LINEUP.map(pos => `<tr><td>${pos}</td><td><input type="number" min="1" data-side="${side}" data-kind="lineup" data-pos="${pos}" placeholder="Player ID"></td></tr>`).join('')}
    </tbody></table></div>
    <h4 class="mt-2 mb-1">Starting pitchers (${AS_SP})</h4><div class="grid-4">${inputs('sp', AS_SP, 'SP')}</div>
    <h4 class="mb-1">Relief pitchers (${AS_RP})</h4><div class="grid-4">${inputs('rp', AS_RP, 'RP')}</div>
    <h4 class="mb-1">Bench (${AS_BENCH})</h4><div class="grid-4">${inputs('bench', AS_BENCH, 'Bench')}</div>
  </div>`;
}

async function mountAllStar(sec, { signal, ly }) {
  setHtml(sec, html`
    <div class="card">
      <div class="card-head">
        <div><h3>All-Star Game</h3><p class="card-sub text-muted">Manual roster entry: each side needs ${AS_SP} SP, ${AS_RP} RP, 9 lineup and ${AS_BENCH} bench player IDs. The game is simulated ad hoc (not scheduled). Creating rosters also writes durable all_star awards.</p></div>
        <div class="row">
          <select id="as-level" title="League level"></select>
          <input type="number" id="as-eid" min="1" placeholder="Event ID" style="width:120px" title="Event ID">
          <button class="btn btn-primary" data-action="create">Create Event</button>
          <button class="btn btn-warning" data-action="simulate">Simulate Game</button>
          <button class="btn btn-secondary" data-action="load">Load Rosters</button>
        </div>
      </div>
      <div id="as-status" class="text-muted small"></div>
      <div id="as-events" class="mt-1"></div>
    </div>
    <div class="grid-2">${raw(allStarSide('home', 'Home team', 'AL'))}${raw(allStarSide('away', 'Away team', 'NL'))}</div>
    <div class="card" id="as-result-card" hidden><h3>Game result</h3><div id="as-result"></div></div>
    <div class="card" id="as-rosters-card" hidden><h3>Rosters</h3><div id="as-rosters"></div></div>`);

  const $ = id => q(sec, `#${id}`);
  const setStatus = m => { $('as-status').textContent = m || ''; };
  levelSelect($('as-level'), { levels: SIM_LEVELS, value: 9, signal });
  const eid = () => Number($('as-eid').value) || null;

  function collectSide(side) {
    const ids = kind => qa(sec, `input[data-side="${side}"][data-kind="${kind}"]`).map(i => parseInt(i.value, 10)).filter(v => !Number.isNaN(v));
    const lineup = qa(sec, `input[data-side="${side}"][data-kind="lineup"]`).map(i => {
      const pid = parseInt(i.value, 10);
      return Number.isNaN(pid) ? null : { player_id: pid, position: i.dataset.pos };
    }).filter(Boolean);
    return { label: q(sec, `[name="as_${side}_label"]`).value.trim(), starting_pitchers: ids('sp'), relief_pitchers: ids('rp'), lineup, bench: ids('bench') };
  }

  function validate(home, away) {
    const errors = [];
    const need = (side, s) => {
      if (!s.label) errors.push(`${side}: team label required`);
      if (s.starting_pitchers.length !== AS_SP) errors.push(`${side}: need ${AS_SP} SP, got ${s.starting_pitchers.length}`);
      if (s.relief_pitchers.length !== AS_RP) errors.push(`${side}: need ${AS_RP} RP, got ${s.relief_pitchers.length}`);
      if (s.lineup.length !== 9) errors.push(`${side}: need 9 lineup, got ${s.lineup.length}`);
      if (s.bench.length !== AS_BENCH) errors.push(`${side}: need ${AS_BENCH} bench, got ${s.bench.length}`);
    };
    need('Home', home); need('Away', away);
    return errors;
  }

  async function loadEvents() {
    const lyid = ly.get();
    if (!lyid) return;
    try {
      const d = await api.get(v1('/special-events'), { params: { league_year_id: lyid, event_type: 'allstar' }, signal, quiet: true });
      const evs = (d.events || []).filter(e => e.event_type === 'allstar');
      if (!evs.length) { setHtml($('as-events'), '<span class="text-muted small">No All-Star events for this league year yet.</span>'); return; }
      const rows = evs.map(e => `<tr><td>${esc(e.id)}</td><td>${statusBadge(e.status)}</td><td>${esc(fmtDate(e.created_at))}</td><td>${esc(e.completed_at ? fmtDate(e.completed_at) : '—')}</td><td><button class="btn btn-xs btn-secondary" data-action="use" data-eid="${esc(e.id)}">Use</button></td></tr>`).join('');
      setHtml($('as-events'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Event</th><th>Status</th><th>Created</th><th>Completed</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`));
    } catch (_) { setHtml($('as-events'), ''); }
  }

  async function loadRosters(id) {
    try {
      const d = await api.get(v1(`/allstar/${id}/rosters`), { signal, quiet: true });
      if (!d.rosters) { $('as-rosters-card').hidden = true; return; }
      let out = '';
      for (const [label, players] of Object.entries(d.rosters)) {
        out += `<h4 class="mt-1 mb-1">${esc(label)} <span class="text-muted small">(${players.length} players)</span></h4>`;
        out += `<div class="table-container"><table class="data-table compact"><thead><tr><th>Name</th><th>Team</th><th>Pos</th><th>Starter</th></tr></thead><tbody>${players.map(p =>
          `<tr><td>${esc(p.name)}</td><td>${esc(p.team || '-')}</td><td>${esc(p.position)}</td><td>${p.is_starter ? badge('Yes', 'success') : ''}</td></tr>`).join('')}</tbody></table></div>`;
      }
      setHtml($('as-rosters'), raw(out)); $('as-rosters-card').hidden = false;
    } catch (e) { if (e && e.name !== 'AbortError') { $('as-rosters-card').hidden = true; setStatus(`Rosters: ${e.message}`); } }
  }

  async function loadResults(id) {
    try {
      const d = await api.get(v1(`/allstar/${id}/results`), { signal, quiet: true });
      const gr = d.game_result;
      if (!gr) { $('as-result-card').hidden = true; return; }
      setHtml($('as-result'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Home</th><th>Away</th><th>Score</th><th>Winner</th></tr></thead><tbody>
        <tr><td>${esc(gr.home_label)}</td><td>${esc(gr.away_label)}</td><td>${esc(gr.home_score)} - ${esc(gr.away_score)}</td><td>${badge(gr.winner_label, 'success')}</td></tr></tbody></table></div>`));
      $('as-result-card').hidden = false;
    } catch (_) { $('as-result-card').hidden = true; }
  }

  delegate(sec, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    btn.disabled = true;
    try {
      if (a === 'use') { $('as-eid').value = btn.dataset.eid; await Promise.all([loadRosters(Number(btn.dataset.eid)), loadResults(Number(btn.dataset.eid))]); }
      else if (a === 'create') {
        const home = collectSide('home'), away = collectSide('away');
        const errors = validate(home, away);
        if (errors.length) { setStatus(errors.join('; ')); return; }
        setStatus('Creating All-Star event…');
        const d = await api.post(v1('/allstar/create'), { league_year_id: Number(ly.get()), league_level: Number($('as-level').value), home, away });
        $('as-eid').value = d.event_id;
        setStatus(`Event ${d.event_id} created (level ${d.league_level}). Ready to simulate.`);
        toast.success(`All-Star event ${d.event_id} created`);
        await Promise.all([loadRosters(d.event_id), loadEvents()]);
      } else if (a === 'simulate') {
        const id = eid(); if (!id) { setStatus('Enter event ID first'); return; }
        if (!await confirm({ title: `Simulate All-Star game for event ${id}?` })) return;
        setStatus('Simulating All-Star game…');
        const d = await api.post(v1(`/allstar/${id}/simulate`), {});
        setStatus(`${d.home_label} ${d.home_score} - ${d.away_label} ${d.away_score} (Winner: ${d.winner_label})`);
        toast.success(`All-Star Game: ${d.winner_label} wins`);
        await Promise.all([loadResults(id), loadEvents()]);
      } else if (a === 'load') {
        const id = eid(); if (!id) { setStatus('Enter event ID'); return; }
        await Promise.all([loadRosters(id), loadResults(id)]);
      }
    } catch (err) { if (err && err.name !== 'AbortError') setStatus(`Error: ${err.message}`); }
    finally { if (btn.isConnected) btn.disabled = false; }
  }, signal);

  await loadEvents();
  return { refresh: loadEvents };
}

// ===================================================================== WBC

const WBC_ACTIONS = [
  { id: 'generate-rosters', label: 'Generate Rosters' },
  { id: 'generate-pool-games', label: 'Generate Pool Games' },
  { id: 'process-pool-results', label: 'Process Pool Results' },
  { id: 'generate-knockout', label: 'Generate Knockout' },
  { id: 'advance-knockout', label: 'Advance Knockout' },
  { id: 'cleanup', label: 'Cleanup', danger: true },
];

async function mountWbc(sec, { signal, ly }) {
  setHtml(sec, html`
    <div class="card">
      <div class="card-head">
        <div><h3>World Baseball Classic</h3><p class="card-sub text-muted">Country teams (virtual level 99) built from player nationalities: pool play, then knockout rounds.</p></div>
        <div class="row">
          <button class="btn btn-secondary" data-action="countries">Check Eligible Countries</button>
          <button class="btn btn-primary" data-action="create">Create Event</button>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="wbc-eid">Event ID</label><input type="number" id="wbc-eid" min="1" placeholder="Event ID" style="width:120px"></div>
        <div class="button-group">
          ${raw(WBC_ACTIONS.map(a => `<button class="btn ${a.danger ? 'btn-danger' : 'btn-secondary'}" data-action="wbc" data-ep="${a.id}">${a.label}</button>`).join(''))}
          <button class="btn btn-secondary" data-action="refresh">Refresh Teams</button>
        </div>
      </div>
      <div id="wbc-status" class="text-muted small"></div>
      <pre class="result-box mt-1" id="wbc-result"></pre>
      <div id="wbc-events" class="mt-1"></div>
    </div>
    <div class="card" id="wbc-countries-card" hidden><h3>Eligible countries</h3><div id="wbc-countries"></div></div>
    <div class="card" id="wbc-teams-card" hidden><h3>Teams / pool standings</h3><div id="wbc-teams"></div></div>`);

  const $ = id => q(sec, `#${id}`);
  const setStatus = m => { $('wbc-status').textContent = m || ''; };
  const eid = () => Number($('wbc-eid').value) || null;
  let teamsTable = null;

  async function loadEvents() {
    const lyid = ly.get();
    if (!lyid) return;
    try {
      const d = await api.get(v1('/special-events'), { params: { league_year_id: lyid, event_type: 'wbc' }, signal, quiet: true });
      const evs = (d.events || []).filter(e => e.event_type === 'wbc');
      if (!evs.length) { setHtml($('wbc-events'), '<span class="text-muted small">No WBC events for this league year yet.</span>'); return; }
      const rows = evs.map(e => `<tr><td>${esc(e.id)}</td><td>${statusBadge(e.status)}</td><td>${esc(fmtDate(e.created_at))}</td><td>${esc(e.completed_at ? fmtDate(e.completed_at) : '—')}</td><td><button class="btn btn-xs btn-secondary" data-action="use" data-eid="${esc(e.id)}">Use</button></td></tr>`).join('');
      setHtml($('wbc-events'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Event</th><th>Status</th><th>Created</th><th>Completed</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`));
    } catch (_) { setHtml($('wbc-events'), ''); }
  }

  async function loadTeams(id) {
    try {
      const d = await api.get(v1(`/wbc/${id}/teams`), { signal, quiet: true });
      const teams = d.teams || [];
      if (!teams.length) { $('wbc-teams-card').hidden = true; return; }
      if (!teamsTable) {
        teamsTable = dataTable($('wbc-teams'), {
          columns: [
            { key: 'country_name', title: 'Country', sortable: true },
            { key: 'country_code', title: 'Code' },
            { key: 'pool_group', title: 'Pool', sortable: true, empty: '-' },
            { key: 'pool_wins', title: 'W', sortable: true, align: 'right' },
            { key: 'pool_losses', title: 'L', sortable: true, align: 'right' },
            { key: 'eliminated', title: 'Status', html: true, render: t => (t.eliminated ? badge('Eliminated', 'danger') : badge('Active', 'success')) },
          ],
          rows: teams, rowKey: 'id', compact: true, rowClass: t => (t.eliminated ? 'row-muted' : ''), sortKey: 'pool_group',
        });
      } else teamsTable.setRows(teams);
      $('wbc-teams-card').hidden = false;
    } catch (e) { if (e && e.name !== 'AbortError') { $('wbc-teams-card').hidden = true; setStatus(`Teams: ${e.message}`); } }
  }

  delegate(sec, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    btn.disabled = true;
    try {
      if (a === 'use') { $('wbc-eid').value = btn.dataset.eid; await loadTeams(Number(btn.dataset.eid)); }
      else if (a === 'countries') {
        setStatus('Checking eligible countries…');
        const d = await api.get(v1('/wbc/eligible-countries'), { signal });
        const rows = (d.countries || []).map((c, i) => `<tr><td>${i + 1}</td><td>${esc(c.country)}</td><td>${esc(c.player_count)}</td></tr>`).join('');
        setHtml($('wbc-countries'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>#</th><th>Country</th><th>Players</th></tr></thead><tbody>${rows}</tbody></table></div>`));
        $('wbc-countries-card').hidden = false;
        setStatus(`Found ${(d.countries || []).length} eligible countries`);
      } else if (a === 'create') {
        if (!await confirm({ title: 'Create a WBC event?', message: `League year id ${ly.get()}. Builds country teams from eligible player nationalities.` })) return;
        setStatus('Creating WBC event…');
        const d = await api.post(v1('/wbc/create'), { league_year_id: Number(ly.get()) });
        $('wbc-eid').value = d.event_id;
        setStatus(`Event ${d.event_id} created with ${(d.teams || []).length} teams`);
        toast.success(`WBC event ${d.event_id} created`);
        await Promise.all([loadTeams(d.event_id), loadEvents()]);
      } else if (a === 'wbc') {
        const id = eid(); if (!id) { setStatus('Enter event ID'); return; }
        const ep = btn.dataset.ep;
        const def = WBC_ACTIONS.find(x => x.id === ep) || { label: ep };
        if (def.danger && !await confirm({ title: `${def.label} WBC event ${id}?`, danger: true, typeToConfirm: 'CLEANUP', confirmLabel: def.label, message: 'Removes the event’s generated data.' })) return;
        setStatus(`${def.label}…`);
        const d = await api.post(v1(`/wbc/${id}/${ep}`), {});
        $('wbc-result').textContent = json(d);
        setStatus(`${def.label}: done`);
        toast.success(`${def.label}: done`);
        await Promise.all([loadTeams(id), loadEvents()]);
      } else if (a === 'refresh') {
        const id = eid(); if (!id) { setStatus('Enter event ID'); return; }
        await loadTeams(id);
      }
    } catch (err) { if (err && err.name !== 'AbortError') setStatus(`Error: ${err.message}`); }
    finally { if (btn.isConnected) btn.disabled = false; }
  }, signal);

  await loadEvents();
  return { refresh: loadEvents };
}
