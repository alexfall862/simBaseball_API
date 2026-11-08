// features/data/game-viewer.js — narrative play-by-play feed (port of legacy #section-game-viewer).
// GET /api/v1/games/<id>/play-by-play?format=v2&granularity=at_bat&include_events=0|1
// See docs/play_by_play_frontend_guide.md. MLB (level 9) only; archived seasons return no at-bats.

import { api, v1 } from '../../core/api.js';
import { html, raw, esc, setHtml, on, delegate, q } from '../../core/html.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { badge } from '../../ui/badge.js';
import { showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';

function halfLabel(h) {
  return h === 'top' ? 'Top' : h === 'bottom' ? 'Bot' : (h || '');
}

function eventLine(e) {
  if (e.kind === 'pitch') {
    const bits = [e.pitch, e.result, e.swing].filter(Boolean).join(' · ');
    return `${e.balls != null ? e.balls : 0}-${e.strikes != null ? e.strikes : 0}  ${bits || 'pitch'}`;
  }
  if (e.kind === 'steal') {
    const who = e.runner && e.runner.name ? e.runner.name : 'runner';
    return `steal (${who}): ${String(e.result || '').replace(/_/g, ' ')}`;
  }
  if (e.kind === 'pickoff') return `pickoff: ${String(e.result || '').replace(/_/g, ' ')}`;
  return e.kind || '';
}

/** Group at-bats by (inning, half) preserving order, then render one tight card per half-inning. */
function renderFeed(data, atBats, includeEvents) {
  const teams = data.teams || {};
  const away = teams.away || 'AWY';
  const home = teams.home || 'HOM';
  const groups = [];
  let cur = null;
  for (const ab of atBats) {
    const key = `${ab.inning}|${ab.half}`;
    if (!cur || cur.key !== key) { cur = { key, inning: ab.inning, half: ab.half, abs: [] }; groups.push(cur); }
    cur.abs.push(ab);
  }
  return groups.map(g => {
    const last = g.abs[g.abs.length - 1];
    const sc = last.score_after || {};
    const score = sc.away != null && sc.home != null ? `${away} ${sc.away} – ${home} ${sc.home}` : '';
    const abs = g.abs.map(ab => {
      const rbi = ab.rbi > 0 ? ` ${badge(`${ab.rbi} RBI`, 'success')}` : '';
      const events = includeEvents && Array.isArray(ab.events) && ab.events.length
        ? `<div class="small text-muted mono mt-1">${ab.events.map(e => `<div>${esc(eventLine(e))}</div>`).join('')}</div>` : '';
      return `<div class="mt-1"><div>${esc(ab.description || '')}${rbi}</div>${events}</div>`;
    }).join('');
    return `<div class="card tight">
      <div class="row between"><strong>${esc(halfLabel(g.half))} ${esc(g.inning)}</strong><span class="text-muted small mono">${esc(score)}</span></div>
      ${abs}
    </div>`;
  }).join('');
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Game viewer</h3><p class="card-sub text-muted">Read a game as a narrative play-by-play feed. MLB (level 9) games only — lower levels do not store play-by-play, and archived seasons have had it deleted.</p></div>
      </div>
      ${raw(formGrid([
        field.number('game_id', 'Game ID', { min: 1, placeholder: 'e.g. 12345', value: ctx.params.game || '' }),
        field.select('detail', 'Detail', [{ value: '0', label: 'Narrative only' }, { value: '1', label: 'Include pitch/event detail' }], { value: ctx.params.events || '0' }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" data-action="load">Load game</button><button class="btn btn-ghost" data-action="raw" hidden>Raw JSON</button></div>
      <div id="gv-status" class="text-muted small mt-1"></div>
    </div>
    <div id="gv-feed-card" hidden>
      <div class="card tight"><div class="row between"><h3 class="mb-0" id="gv-title">Play-by-play</h3><span class="text-muted small" id="gv-meta"></span></div></div>
      <div id="gv-feed"></div>
    </div>`);

  const status = q(el, '#gv-status');
  let lastData = null;

  async function load() {
    const f = readForm(el);
    const gid = f.game_id;
    if (!gid) { toast.warn('Enter a game ID'); return; }
    const includeEvents = f.detail === '1';
    ctx.setParams({ game: gid, events: f.detail });
    status.textContent = `Loading game ${gid}…`;
    q(el, '#gv-feed-card').hidden = true;
    q(el, '[data-action="raw"]').hidden = true;
    lastData = null;
    try {
      const data = await api.get(v1(`/games/${gid}/play-by-play`), {
        params: { format: 'v2', granularity: 'at_bat', include_events: includeEvents ? '1' : '0' }, signal: ctx.signal,
      });
      lastData = data;
      q(el, '[data-action="raw"]').hidden = false;
      const atBats = data.at_bats || [];
      if (!atBats.length) { status.textContent = `No play-by-play stored for game ${gid} (MLB-only; may be archived).`; return; }
      status.textContent = '';
      const teams = data.teams || {};
      q(el, '#gv-title').textContent = `Play-by-play — Game ${data.game_id ?? gid} (${teams.away || 'AWY'} @ ${teams.home || 'HOM'})`;
      q(el, '#gv-meta').textContent = `${atBats.length} plate appearances${includeEvents ? ' · with pitch events' : ''}`;
      setHtml(q(el, '#gv-feed'), raw(renderFeed(data, atBats, includeEvents)));
      q(el, '#gv-feed-card').hidden = false;
    } catch (e) {
      if (e.name !== 'AbortError') status.textContent = `Error: ${e.message}`;
    }
  }

  on(q(el, '[name="game_id"]'), 'keydown', (e) => { if (e.key === 'Enter') load(); }, ctx.signal);
  delegate(el, 'click', '[data-action]', (e, btn) => {
    if (btn.dataset.action === 'load') load();
    else if (btn.dataset.action === 'raw' && lastData) showResult(`Game ${lastData.game_id || ''} play-by-play`, lastData);
  }, ctx.signal);

  if (ctx.params.game) load();
}
