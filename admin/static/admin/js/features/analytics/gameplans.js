// features/analytics/gameplans.js — gameplan audit overview + per-team editor
// (port of legacy #section-gameplan-audit). Reads /admin/gameplan-audit*, writes /api/v1/gameplanning/*.

import { api, adm, v1 } from '../../core/api.js';
import { html, raw, esc, setHtml, delegate, on, q, qa } from '../../core/html.js';
import { SIM_LEVELS, POSITIONS, levelName } from '../../core/constants.js';
import { fmtDate } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { badge, boolBadge } from '../../ui/badge.js';
import { toast } from '../../ui/toast.js';
import { levelSelect } from '../../ui/selectors.js';

// Gameplanning enumerations (option lists for the editor; mirror the engine's accepted values).
const DEF_POS_CODES = ['c', 'fb', 'sb', 'tb', 'ss', 'lf', 'cf', 'rf', 'dh', 'p'];
const LINEUP_ROLES = ['balanced', 'table_setter', 'on_base', 'slugger', 'speed', 'bottom'];
const BP_ROLES = ['closer', 'setup', 'middle', 'long', 'mop_up'];
const OF_SPACING = ['normal', 'deep', 'shallow', 'shift_pull', 'shift_oppo'];
const IF_SPACING = ['normal', 'in', 'double_play', 'shift_pull', 'shift_oppo'];
const BP_PRIORITY = ['rest', 'matchup', 'best_available'];
const PLATE = ['normal', 'aggressive', 'patient', 'contact', 'power'];
const PITCHING = ['normal', 'aggressive', 'finesse', 'power', 'location'];
const BASERUN = ['normal', 'aggressive', 'cautious', 'conservative'];
const USAGE = ['normal', 'only_fully_rested', 'play_tired', 'desperation'];
const PULLTEND = ['normal', 'quick', 'long'];
const BP_ROLE_KIND = { closer: 'danger', setup: 'warning', middle: 'info', long: 'success', mop_up: 'secondary' };

// Position label: the audit payload only carries codes (c/fb/sb/tb/…). POSITIONS knows the
// standard abbreviations; fb/sb/tb fall back to upper-case until constants (or the payload) carry them.
const posLabel = (code) => POSITIONS[String(code || '').toUpperCase()] || String(code || '').toUpperCase();

const opts = (arr, selected) => arr.map(v => `<option value="${esc(v)}"${String(v) === String(selected) ? ' selected' : ''}>${esc(v)}</option>`).join('');
const playerOpts = (players, selectedId, { none = '--' } = {}) => `<option value="">${esc(none)}</option>${players.map(p => `<option value="${p.id}"${Number(p.id) === Number(selectedId) ? ' selected' : ''}>${esc(p.name)} (${p.id})</option>`).join('')}`;
const numIn = (f, value, attrs) => `<input type="number" class="gpa-inp" data-f="${f}" value="${value == null ? '' : esc(value)}" ${attrs} style="width:64px" />`;
const empty = (msg) => `<p class="text-muted small">${esc(msg)}</p>`;
const tbl = (head, rows) => `<div class="table-container"><table class="data-table compact"><thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;

const SECTIONS = [
  ['defense', 'Defensive depth chart', 'Save defense'], ['rotation', 'Pitching rotation', 'Save rotation'], ['bullpen', 'Bullpen order', 'Save bullpen'],
  ['strategy', 'Team strategy', 'Save strategy'], ['lineup', 'Lineup roles', 'Save lineup'], ['playerstrat', 'Player strategies', 'Save all strategies'],
];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Gameplan audit</h3><p class="card-sub text-muted">Gameplan submissions across all organizations and levels: depth charts, rotations, bullpens, team strategy, lineup roles and player strategies. Open a team to inspect or edit.</p></div>
        <div class="form-row mb-0">
          <div class="form-group"><label for="gpa-level">Level</label><select id="gpa-level"></select></div>
          <button type="button" class="btn btn-primary btn-sm" data-action="load">Load</button>
          <span id="gpa-status" class="text-muted small"></span>
        </div>
      </div>
      <div id="gpa-overview"></div>
    </div>
    <div class="card" id="gpa-detail" hidden>
      <div class="card-head">
        <h3 id="gpa-title">Team detail</h3>
        <div class="row">
          <button type="button" class="btn btn-primary btn-sm" data-action="toggle-edit">Edit mode</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="close">Close</button>
        </div>
      </div>
      <div id="gpa-edit-status" class="small text-muted mb-1"></div>
      ${raw(SECTIONS.map(([id, title, save]) => `
        <div class="row between mt-2 mb-1"><h4>${esc(title)}</h4><button type="button" class="btn btn-primary btn-xs gpa-save" data-action="save" data-section="${id}" hidden>${esc(save)}</button></div>
        <div id="gpa-${id}"></div>`).join(''))}
    </div>`);

  const lvl = levelSelect(q(el, '#gpa-level'), { levels: SIM_LEVELS, allowAll: true, allLabel: 'All levels', value: ctx.params.level ?? null, signal: ctx.signal });
  const statusEl = q(el, '#gpa-status'), editStatus = q(el, '#gpa-edit-status'), detail = q(el, '#gpa-detail');
  const teams = new Map();
  let teamId = null, orgId = null, roster = null, editMode = false, overviewTable = null;

  const setEditStatus = (msg, kind = 'muted') => { editStatus.textContent = msg || ''; editStatus.className = `small mb-1 text-${kind === 'error' ? 'danger' : kind}`; };
  const sec = (id) => q(el, `#gpa-${id}`);
  const current = () => teams.get(teamId);

  // ---------------------------------------------------------------- overview

  async function load() {
    statusEl.textContent = 'Loading…';
    detail.hidden = true;
    const d = await api.get(adm('/gameplan-audit'), { signal: ctx.signal, params: { level: lvl.get() } });
    teams.clear();
    for (const t of d.teams || []) teams.set(t.team_id, t);
    statusEl.textContent = `${d.count ?? teams.size} teams loaded`;
    ctx.setParams({ level: lvl.get() });
    const chk = (k) => ({ key: `c_${k}`, title: k === 'team_strategy' ? 'Strategy' : k === 'lineup_roles' ? 'Lineup' : k === 'player_strategies' ? 'Player strats' : k[0].toUpperCase() + k.slice(1), html: true, align: 'center', sortable: true, render: r => boolBadge(r.completeness && r.completeness[k], { yes: 'Y', no: 'N' }), sortValue: r => (r.completeness && r.completeness[k] ? 1 : 0) });
    const host = q(el, '#gpa-overview');
    overviewTable = dataTable(host, {
      rows: [...teams.values()], rowKey: 'team_id', compact: true, pageSize: 60, sortKey: 'team_level', sortDir: 'desc', emptyText: 'No teams.',
      columns: [
        { key: 'org_abbrev', title: 'Org', sortable: true, html: true, render: r => `<strong>${esc(r.org_abbrev)}</strong>` },
        { key: 'team_abbrev', title: 'Team', sortable: true },
        { key: 'team_level', title: 'Level', sortable: true, render: r => `${r.level_name || levelName(r.team_level)} (${r.team_level})` },
        chk('defense'), chk('rotation'), chk('bullpen'), chk('team_strategy'), chk('lineup_roles'), chk('player_strategies'),
        { key: 'most_recent_update', title: 'Last updated', sortable: true, render: r => (r.most_recent_update ? fmtDate(r.most_recent_update, { time: false }) : '-') },
        { key: '_a', title: '', html: true, render: r => `<button type="button" class="btn btn-xs btn-secondary" data-action="view" data-id="${r.team_id}">View</button>` },
      ],
    });
    if (ctx.params.team_id && teams.has(Number(ctx.params.team_id))) viewTeam(Number(ctx.params.team_id));
  }

  async function refreshTeam(id) {
    const d = await api.get(adm('/gameplan-audit'), { signal: ctx.signal, params: { team_id: id }, quiet: true });
    if (d.teams && d.teams[0]) { teams.set(id, d.teams[0]); if (overviewTable) overviewTable.setRows([...teams.values()]); }
  }

  // ---------------------------------------------------------------- detail

  async function viewTeam(id) {
    const t = teams.get(id);
    if (!t) return;
    if (id !== teamId) roster = null;
    teamId = id; orgId = t.org_id;
    ctx.setParams({ team_id: id });
    q(el, '#gpa-title').textContent = `${t.org_abbrev} ${t.team_abbrev} (${t.level_name || levelName(t.team_level)}) — gameplan ${editMode ? 'editor' : 'detail'}`;
    setEditStatus('');
    detail.hidden = false;
    if (editMode && !roster) {
      setEditStatus('Loading roster…');
      const r = await api.get(adm('/gameplan-audit/roster'), { signal: ctx.signal, params: { team_id: id } });
      roster = r.players || [];
      setEditStatus('');
    }
    renderAll(t);
    detail.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function setEditMode(on) {
    editMode = on;
    const btn = q(el, '[data-action="toggle-edit"]');
    btn.textContent = on ? 'View mode' : 'Edit mode';
    btn.className = `btn btn-sm ${on ? 'btn-warning' : 'btn-primary'}`;
    qa(el, '.gpa-save').forEach(b => { b.hidden = !on; });
    if (teamId) viewTeam(teamId);
  }

  function renderAll(t) {
    renderDefense(t); renderRotation(t); renderBullpen(t); renderStrategy(t); renderLineup(t); renderPlayerStrats(t);
  }

  const pitchers = () => (roster || []).filter(p => p.ptype === 'Pitcher');

  // --- defense
  function defRow(d) {
    return `<tr>
      <td><select class="gpa-inp" data-f="position_code">${opts(DEF_POS_CODES, d.position_code)}</select></td>
      <td><select class="gpa-inp" data-f="vs_hand">${opts(['both', 'L', 'R'], d.vs_hand)}</select></td>
      <td><select class="gpa-inp" data-f="player_id">${playerOpts(roster || [], d.player_id)}</select></td>
      <td>${numIn('target_weight', d.target_weight, 'step="0.1" min="0.1" max="10"')}</td>
      <td>${numIn('priority', d.priority, 'min="1" max="9"')}</td>
      <td class="text-center"><input type="checkbox" class="gpa-inp" data-f="locked"${d.locked ? ' checked' : ''} /></td>
      <td><select class="gpa-inp" data-f="lineup_role">${opts(LINEUP_ROLES, d.lineup_role || 'balanced')}</select></td>
      <td>${numIn('min_order', d.min_order, 'min="1" max="9"')}</td>
      <td>${numIn('max_order', d.max_order, 'min="1" max="9"')}</td>
      <td><button type="button" class="btn btn-xs btn-danger" data-action="rm-row" title="Remove">×</button></td>
    </tr>`;
  }
  function renderDefense(t) {
    const rows = [...((t.defense && t.defense.assignments) || [])].sort((a, b) => ((DEF_POS_CODES.indexOf(a.position_code) + 1 || 99) - (DEF_POS_CODES.indexOf(b.position_code) + 1 || 99)) || a.priority - b.priority);
    if (!editMode) {
      setHtml(sec('defense'), rows.length ? tbl(['Pos', 'vs hand', 'Player', 'Wt', 'Pri', 'Lock', 'Role', 'Order'], rows.map(d => `<tr><td><strong>${esc(posLabel(d.position_code))}</strong></td><td>${d.vs_hand === 'both' ? 'All' : `vs ${esc(d.vs_hand)}HP`}</td><td>${esc(d.player_name)} <span class="text-muted small">(${d.player_id})</span></td><td>${esc(d.target_weight)}</td><td>${esc(d.priority)}</td><td>${d.locked ? badge('Y', 'success') : '-'}</td><td>${esc(d.lineup_role || 'balanced')}</td><td>${(d.min_order || d.max_order) ? `${d.min_order || '?'}-${d.max_order || '?'}` : '-'}</td></tr>`)) : empty('No defense plan.'));
      return;
    }
    setHtml(sec('defense'), `<div id="gpa-def-edit">${tbl(['Pos', 'vs hand', 'Player', 'Wt', 'Pri', 'Lock', 'Role', 'Min', 'Max', ''], rows.map(defRow))}</div><button type="button" class="btn btn-xs btn-secondary mt-1" data-action="def-add">+ Add row</button>`);
  }
  function saveDefense() {
    const assignments = [];
    for (const tr of qa(sec('defense'), 'tbody tr')) {
      const g = f => tr.querySelector(`[data-f="${f}"]`);
      const pid = parseInt(g('player_id').value, 10);
      if (!pid) continue;
      assignments.push({
        position_code: g('position_code').value, vs_hand: g('vs_hand').value, player_id: pid,
        target_weight: parseFloat(g('target_weight').value) || 1.0, priority: parseInt(g('priority').value, 10) || 1,
        locked: g('locked').checked, lineup_role: g('lineup_role').value,
        min_order: g('min_order').value ? parseInt(g('min_order').value, 10) : null, max_order: g('max_order').value ? parseInt(g('max_order').value, 10) : null,
      });
    }
    return put(`/gameplanning/team/${teamId}/defense`, { assignments }, 'Defense');
  }

  // --- rotation
  function renderRotation(t) {
    const rot = t.rotation || {}, slots = rot.slots || [];
    if (!editMode) {
      setHtml(sec('rotation'), `${slots.length ? tbl(['Slot', 'Pitcher'], slots.map(s => `<tr><td>${s.slot}${s.slot === rot.next_slot ? ` ${badge('next', 'info')}` : ''}</td><td>${esc(s.player_name)} <span class="text-muted small">(${s.player_id})</span></td></tr>`)) : empty('No rotation.')}<p class="text-muted small mt-1">Size ${rot.rotation_size || 0} · current slot ${rot.current_slot || 0} · updated ${rot.rotation_updated ? fmtDate(rot.rotation_updated) : '-'}</p>`);
      return;
    }
    const size = rot.rotation_size || 5;
    setHtml(sec('rotation'), `<div class="form-row"><div class="form-group"><label for="gpa-rot-size">Rotation size</label><select id="gpa-rot-size">${opts([1, 2, 3, 4, 5, 6, 7], size)}</select></div></div><div class="stack" id="gpa-rot-slots">${Array.from({ length: size }, (_, i) => rotSlot(i, slots[i] ? slots[i].player_id : null)).join('')}</div>`);
  }
  const rotSlot = (i, pid) => `<div class="row"><strong>${i + 1}.</strong> <select class="gpa-rot-pitcher">${playerOpts(pitchers(), pid)}</select></div>`;
  function resizeRotation(n) {
    const host = q(el, '#gpa-rot-slots');
    const cur = qa(host, '.gpa-rot-pitcher').length;
    if (n > cur) for (let i = cur; i < n; i++) host.insertAdjacentHTML('beforeend', rotSlot(i, null));
    else qa(host, ':scope > .row').slice(n).forEach(d => d.remove());
  }
  function saveRotation() {
    const size = parseInt(q(el, '#gpa-rot-size').value, 10);
    const slots = qa(el, '.gpa-rot-pitcher').slice(0, size).map((s, i) => ({ slot: i + 1, player_id: s.value ? parseInt(s.value, 10) : 0 }));
    return put(`/gameplanning/team/${teamId}/rotation`, { rotation_size: size, slots }, 'Rotation');
  }

  // --- bullpen
  const bpRow = (i, pid, role) => `<div class="row gpa-bp-row"><strong>${i + 1}.</strong> <select class="gpa-bp-pitcher">${playerOpts(pitchers(), pid)}</select> <select class="gpa-bp-role">${opts(BP_ROLES, role)}</select> <button type="button" class="btn btn-xs btn-danger" data-action="rm-row" title="Remove">×</button></div>`;
  function renderBullpen(t) {
    const bps = (t.bullpen && t.bullpen.pitchers) || [];
    if (!editMode) {
      setHtml(sec('bullpen'), bps.length ? tbl(['Slot', 'Pitcher', 'Role'], bps.map(b => `<tr><td>${b.slot}</td><td>${esc(b.player_name)} <span class="text-muted small">(${b.player_id})</span></td><td>${badge(b.role, BP_ROLE_KIND[b.role] || 'secondary')}</td></tr>`)) : empty('No bullpen.'));
      return;
    }
    setHtml(sec('bullpen'), `<div class="stack" id="gpa-bp-rows">${bps.map((b, i) => bpRow(i, b.player_id, b.role)).join('')}</div><button type="button" class="btn btn-xs btn-secondary mt-1" data-action="bp-add">+ Add pitcher</button>`);
  }
  function saveBullpen() {
    const pitchers_ = [];
    qa(el, '.gpa-bp-row').forEach((row, i) => {
      const pid = parseInt(row.querySelector('.gpa-bp-pitcher').value, 10);
      if (pid) pitchers_.push({ slot: i + 1, player_id: pid, role: row.querySelector('.gpa-bp-role').value });
    });
    return put(`/gameplanning/team/${teamId}/bullpen`, { pitchers: pitchers_ }, 'Bullpen');
  }

  // --- team strategy
  function renderStrategy(t) {
    const s = t.team_strategy || {};
    if (!editMode) {
      setHtml(sec('strategy'), t.team_strategy ? `<div class="kv-table">${[
        ['OF spacing', s.outfield_spacing], ['IF spacing', s.infield_spacing], ['BP cutoff', `${s.bullpen_cutoff} pitches`], ['BP priority', s.bullpen_priority],
        ['Emergency P', s.emergency_pitcher_name || 'None'], ['IBB list', (s.intentional_walk_list || []).length ? s.intentional_walk_list.join(', ') : 'None'], ['Updated', s.updated_at ? fmtDate(s.updated_at) : '-'],
      ].map(([k, v]) => `<div class="kv-row"><div class="kv-key">${esc(k)}</div><div class="kv-val">${esc(v ?? '-')}</div></div>`).join('')}</div>` : empty('No strategy.'));
      return;
    }
    setHtml(sec('strategy'), `<div class="form-grid">
      <div class="form-group"><label for="gpa-strat-of">OF spacing</label><select id="gpa-strat-of">${opts(OF_SPACING, s.outfield_spacing || 'normal')}</select></div>
      <div class="form-group"><label for="gpa-strat-if">IF spacing</label><select id="gpa-strat-if">${opts(IF_SPACING, s.infield_spacing || 'normal')}</select></div>
      <div class="form-group"><label for="gpa-strat-cutoff">BP cutoff (pitches)</label><input type="number" id="gpa-strat-cutoff" value="${esc(s.bullpen_cutoff || 100)}" min="50" max="150" /></div>
      <div class="form-group"><label for="gpa-strat-bp">BP priority</label><select id="gpa-strat-bp">${opts(BP_PRIORITY, s.bullpen_priority || 'rest')}</select></div>
      <div class="form-group"><label for="gpa-strat-ep">Emergency pitcher</label><select id="gpa-strat-ep">${playerOpts(roster || [], s.emergency_pitcher_id, { none: 'None' })}</select></div>
      <div class="form-group"><label for="gpa-strat-ibb">IBB list (player IDs)</label><input type="text" id="gpa-strat-ibb" value="${esc((s.intentional_walk_list || []).join(','))}" placeholder="123,456" /></div>
    </div>`);
  }
  function saveStrategy() {
    const ibbRaw = q(el, '#gpa-strat-ibb').value.trim();
    const ep = q(el, '#gpa-strat-ep').value;
    return put(`/gameplanning/team/${teamId}/strategy`, {
      outfield_spacing: q(el, '#gpa-strat-of').value, infield_spacing: q(el, '#gpa-strat-if').value,
      bullpen_cutoff: parseInt(q(el, '#gpa-strat-cutoff').value, 10), bullpen_priority: q(el, '#gpa-strat-bp').value,
      emergency_pitcher_id: ep ? parseInt(ep, 10) : null,
      intentional_walk_list: ibbRaw ? ibbRaw.split(',').map(x => parseInt(x.trim(), 10)).filter(n => !Number.isNaN(n)) : [],
    }, 'Strategy');
  }

  // --- lineup roles
  function renderLineup(t) {
    const slots = (t.lineup_roles && t.lineup_roles.slots) || [];
    if (!editMode) {
      setHtml(sec('lineup'), slots.length ? tbl(['#', 'Role', 'Locked'], slots.map(l => `<tr><td>${l.slot}</td><td>${esc(l.role)}</td><td>${esc(l.locked_player_name || '-')}</td></tr>`)) : empty('No lineup roles.'));
      return;
    }
    setHtml(sec('lineup'), tbl(['#', 'Role', 'Locked player'], Array.from({ length: 9 }, (_, i) => {
      const s = slots.find(x => x.slot === i + 1) || { role: 'balanced', locked_player_id: null };
      return `<tr><td>${i + 1}</td><td><select class="gpa-lu-role" data-slot="${i + 1}">${opts(LINEUP_ROLES, s.role)}</select></td><td><select class="gpa-lu-lock" data-slot="${i + 1}">${playerOpts(roster || [], s.locked_player_id, { none: 'None' })}</select></td></tr>`;
    })));
  }
  function saveLineup() {
    const slots = Array.from({ length: 9 }, (_, i) => {
      const lock = q(el, `.gpa-lu-lock[data-slot="${i + 1}"]`).value;
      return { slot: i + 1, role: q(el, `.gpa-lu-role[data-slot="${i + 1}"]`).value, locked_player_id: lock ? parseInt(lock, 10) : null };
    });
    return put(`/gameplanning/team/${teamId}/lineup`, { slots }, 'Lineup');
  }

  // --- player strategies
  function renderPlayerStrats(t) {
    const ps = t.player_strategies || {};
    if (!editMode) {
      setHtml(sec('playerstrat'), ps.total_strategies > 0 ? `<div class="kv-table">${[
        ['Total', ps.total_strategies], ['Custom usage', ps.custom_usage_preference], ['Custom plate', ps.custom_plate_approach], ['Custom pitching', ps.custom_pitching_approach], ['Custom baserunning', ps.custom_baserunning_approach],
      ].map(([k, v]) => `<div class="kv-row"><div class="kv-key">${esc(k)}</div><div class="kv-val">${esc(v ?? '-')}</div></div>`).join('')}</div>` : empty('No player strategies.'));
      return;
    }
    setHtml(sec('playerstrat'), '<button type="button" class="btn btn-xs btn-secondary" data-action="ps-load">Load player strategies</button><div id="gpa-ps-table" class="mt-1"></div>');
  }
  async function loadPlayerStrats() {
    setEditStatus('Loading player strategies…');
    const d = await api.get(adm('/gameplan-audit/player-strategies'), { signal: ctx.signal, params: { team_id: teamId } });
    const strats = d.strategies || [];
    if (!strats.length) { setEditStatus('No player strategies found for this team', 'warning'); return; }
    setEditStatus(`${strats.length} strategies loaded`, 'success');
    const sel = (f, arr, v, extra = '') => `<select class="gpa-ps" data-f="${f}">${extra}${opts(arr, v)}</select>`;
    setHtml(q(el, '#gpa-ps-table'), tbl(['Player', 'Type', 'Plate', 'Pitching', 'Baserun', 'Usage', 'Steal%', 'Pick%', 'Pull#', 'Leash', ''], strats.map(s => {
      const isP = s.ptype === 'Pitcher';
      return `<tr data-pid="${s.player_id}">
        <td class="small">${esc(s.player_name)}</td><td>${isP ? 'P' : 'Pos'}</td>
        <td>${sel('plate_approach', PLATE, s.plate_approach)}</td>
        <td>${isP ? sel('pitching_approach', PITCHING, s.pitching_approach) : '-'}</td>
        <td>${sel('baserunning_approach', BASERUN, s.baserunning_approach)}</td>
        <td>${sel('usage_preference', USAGE, s.usage_preference)}</td>
        <td><input type="number" class="gpa-ps" data-f="stealfreq" value="${esc(s.stealfreq)}" step="0.1" min="0" max="100" style="width:64px" /></td>
        <td>${isP ? `<input type="number" class="gpa-ps" data-f="pickofffreq" value="${esc(s.pickofffreq)}" step="0.1" min="0" max="100" style="width:64px" />` : '-'}</td>
        <td>${isP ? `<input type="number" class="gpa-ps" data-f="pitchpull" value="${s.pitchpull == null ? '' : esc(s.pitchpull)}" min="1" style="width:64px" />` : '-'}</td>
        <td>${isP ? sel('pulltend', PULLTEND, s.pulltend || '', '<option value="">default</option>') : '-'}</td>
        <td><button type="button" class="btn btn-xs btn-secondary" data-action="ps-save">Save</button></td>
      </tr>`;
    })));
  }
  function stratBody(tr) {
    const body = {};
    for (const inp of tr.querySelectorAll('.gpa-ps')) {
      const f = inp.dataset.f;
      body[f] = inp.type === 'number' ? (inp.value ? parseFloat(inp.value) : null) : (inp.value || null);
    }
    return body;
  }
  async function savePlayer(tr, btn) {
    const pid = Number(tr.dataset.pid);
    await api.put(v1(`/gameplanning/org/${orgId}/player/${pid}/strategy`), stratBody(tr), { signal: ctx.signal });
    if (btn) { btn.textContent = 'Saved'; setTimeout(() => { btn.textContent = 'Save'; }, 1500); }
  }
  async function saveAllPlayers() {
    const rows = qa(el, '#gpa-ps-table tbody tr');
    if (!rows.length) { setEditStatus('Load player strategies first', 'warning'); return; }
    setEditStatus(`Saving ${rows.length} strategies…`);
    const results = await Promise.allSettled(rows.map(tr => api.put(v1(`/gameplanning/org/${orgId}/player/${tr.dataset.pid}/strategy`), stratBody(tr), { signal: ctx.signal, quiet: true })));
    const ok = results.filter(r => r.status === 'fulfilled').length;
    setEditStatus(`Saved ${ok}/${rows.length} strategies`, ok === rows.length ? 'success' : 'error');
    if (ok < rows.length) toast.error(`${rows.length - ok} player strategy save(s) failed`);
    refreshTeam(teamId);
  }

  // --- generic PUT
  async function put(path, body, label) {
    setEditStatus(`Saving ${label}…`);
    try {
      await api.put(v1(path), body, { signal: ctx.signal });
    } catch (e) {
      if (e.name !== 'AbortError') setEditStatus(`${label} error: ${e.message}`, 'error');
      throw e;
    }
    setEditStatus(`${label} saved`, 'success');
    toast.success(`${label} saved`);
    await refreshTeam(teamId);
  }

  // ---------------------------------------------------------------- events

  on(q(el, '#gpa-level'), 'change', () => { if (teams.size) load(); }, ctx.signal);
  delegate(el, 'change', '#gpa-rot-size', (e, s) => resizeRotation(parseInt(s.value, 10)), ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'load') await load();
      else if (a === 'view') await viewTeam(Number(btn.dataset.id));
      else if (a === 'close') { detail.hidden = true; ctx.setParams({ team_id: null }); }
      else if (a === 'toggle-edit') setEditMode(!editMode);
      else if (a === 'rm-row') btn.closest('tr, .gpa-bp-row').remove();
      else if (a === 'def-add') q(el, '#gpa-def-edit tbody').insertAdjacentHTML('beforeend', defRow({ position_code: 'c', vs_hand: 'both', player_id: null, target_weight: 1.0, priority: 1, locked: false, lineup_role: 'balanced' }));
      else if (a === 'bp-add') { const host = q(el, '#gpa-bp-rows'); host.insertAdjacentHTML('beforeend', bpRow(qa(host, '.gpa-bp-row').length, null, 'middle')); }
      else if (a === 'ps-load') await loadPlayerStrats();
      else if (a === 'ps-save') { btn.disabled = true; try { await savePlayer(btn.closest('tr'), btn); } finally { btn.disabled = false; } }
      else if (a === 'save') {
        const s = btn.dataset.section;
        btn.disabled = true;
        try {
          if (s === 'defense') await saveDefense();
          else if (s === 'rotation') await saveRotation();
          else if (s === 'bullpen') await saveBullpen();
          else if (s === 'strategy') await saveStrategy();
          else if (s === 'lineup') await saveLineup();
          else if (s === 'playerstrat') await saveAllPlayers();
        } finally { btn.disabled = false; }
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (a === 'load') statusEl.textContent = err.message || 'Error';
      // api layer already toasted
    }
  }, ctx.signal);

  await load().catch(() => {});
}
