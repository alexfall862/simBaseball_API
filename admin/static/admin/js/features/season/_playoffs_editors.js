// features/season/_playoffs_editors.js — markup + DOM readers for the Playoffs
// tab's manual editors: playoff field/seeds (MLB AL/NL or flat MiLB), conference
// tournament seeds, the 64-team NCAA field, and the per-round matchup editor.
//
// Render functions return escaped markup strings; collect/validate functions
// read from a root element. State lives in the caller's mount() closure.

import { esc } from '../../core/html.js';
import { badge } from '../../ui/badge.js';

// ---------------------------------------------------------------- field / seed editor

function teamOptions(pool, selectedId) {
  return pool.map(p => `<option value="${esc(p.team_id)}"${p.team_id === selectedId ? ' selected' : ''}>${esc(p.team_abbrev)}</option>`).join('');
}

function recCells(pool, teamId) {
  const pe = pool.find(p => p.team_id === teamId) || {};
  return `<td class="rec-w">${esc(pe.wins ?? '-')}</td><td class="rec-l">${esc(pe.losses ?? '-')}</td><td class="rec-pct">${esc(pe.win_pct ?? '-')}</td>`;
}

/** One editable seed table. `group` tags the table so collectFieldTable can find it. */
export function renderFieldEditorTable(teams, pool, group) {
  let h = `<div class="table-container"><table class="data-table compact fe-table" data-group="${esc(group)}"><thead><tr><th style="width:90px">Seed</th><th>Team</th><th>W</th><th>L</th><th>Pct</th></tr></thead><tbody>`;
  (teams || []).forEach(t => {
    h += `<tr><td><input type="number" min="1" class="fe-seed" value="${esc(t.seed)}"></td>
      <td><select class="fe-team">${teamOptions(pool, t.team_id)}</select></td>${recCells(pool, t.team_id)}</tr>`;
  });
  return h + '</tbody></table></div>';
}

/** Field editor body for a /playoffs/field payload (format mlb | milb). */
export function renderFieldEditor(data) {
  if (data.format === 'mlb') {
    return ['AL', 'NL'].map(conf => {
      const confPool = (data.pool || []).filter(p => p.conference === conf);
      return `<h4 class="mt-1 mb-1">${conf}</h4>${renderFieldEditorTable(data.field[conf], confPool, conf)}`;
    }).join('');
  }
  return renderFieldEditorTable(data.field, data.pool || [], 'flat');
}

/** Live-update W/L/Pct cells when a team select changes. */
export function syncFieldRowRecord(selectEl, pool) {
  const row = selectEl.closest('tr');
  const pe = pool.find(p => p.team_id === parseInt(selectEl.value, 10));
  if (!row || !pe) return;
  const w = row.querySelector('.rec-w'), l = row.querySelector('.rec-l'), pct = row.querySelector('.rec-pct');
  if (w) w.textContent = pe.wins;
  if (l) l.textContent = pe.losses;
  if (pct) pct.textContent = pe.win_pct;
}

/** Renumber seeds 1..N within each table under root (ordered by current value). */
export function resequenceTables(root) {
  root.querySelectorAll('table').forEach(tbl => {
    Array.from(tbl.querySelectorAll('input[type=number]'))
      .map((el, i) => ({ el, v: parseInt(el.value, 10) || 0, i }))
      .sort((a, b) => a.v - b.v || a.i - b.i)
      .forEach((o, idx) => { o.el.value = idx + 1; });
  });
}

export function collectFieldTable(root, group, pool) {
  const tbl = root.querySelector(`.fe-table[data-group="${CSS.escape(group)}"]`);
  if (!tbl) return [];
  return Array.from(tbl.querySelectorAll('tbody tr')).map(tr => {
    const tid = parseInt(tr.querySelector('.fe-team').value, 10);
    const team = pool.find(p => p.team_id === tid);
    return { team_id: tid, seed: parseInt(tr.querySelector('.fe-seed').value, 10), team_abbrev: team ? team.team_abbrev : '' };
  });
}

export function seedsValid(list, size) {
  const s = list.map(t => t.seed).sort((a, b) => a - b);
  if (s.length !== size) return false;
  for (let i = 0; i < size; i++) if (s[i] !== i + 1) return false;
  return new Set(list.map(t => t.team_id)).size === size;
}

/**
 * Build the `field` body for POST /playoffs/generate from the editor.
 * Returns { field } or { error }.
 */
export function collectField(root, state) {
  if (state.format === 'mlb') {
    const field = {};
    for (const conf of ['AL', 'NL']) {
      const confPool = state.pool.filter(p => p.conference === conf);
      const teams = collectFieldTable(root, conf, confPool);
      if (!seedsValid(teams, 6)) return { error: `${conf}: seeds must be 1..6 with unique teams` };
      field[conf] = teams;
    }
    return { field };
  }
  const teams = collectFieldTable(root, 'flat', state.pool);
  if (!seedsValid(teams, 8)) return { error: 'Seeds must be 1..8 with unique teams' };
  return { field: teams };
}

// ---------------------------------------------------------------- conference tournament seeds

export function renderConfSeedEditor(fields) {
  const confs = Object.keys(fields || {}).sort();
  if (!confs.length) return '<p class="text-muted">No eligible conferences (each needs 2+ teams).</p>';
  return confs.map(conf => {
    const teams = fields[conf];
    let h = `<details class="mb-1" open><summary><strong>${esc(conf)}</strong> (${teams.length})</summary>`;
    h += `<div class="table-container"><table class="data-table compact ct-table" data-conf="${esc(conf)}"><thead><tr><th style="width:90px">Seed</th><th>Team</th><th>Conf</th><th>Overall</th></tr></thead><tbody>`;
    teams.forEach(t => {
      h += `<tr data-team="${esc(t.team_id)}" data-abbrev="${esc(t.team_abbrev)}"><td><input type="number" min="1" class="ct-seed" value="${esc(t.seed)}"></td>
        <td>${esc(t.team_abbrev)}</td><td>${esc(t.conf_wins)}-${esc(t.conf_losses)}</td><td>${esc(t.wins)}-${esc(t.losses)} (${esc(t.win_pct)})</td></tr>`;
    });
    return h + '</tbody></table></div></details>';
  }).join('');
}

/** Returns { fields } or { error }. */
export function collectConfSeeds(root) {
  const fields = {};
  for (const tbl of root.querySelectorAll('.ct-table[data-conf]')) {
    const conf = tbl.getAttribute('data-conf');
    const teams = Array.from(tbl.querySelectorAll('tbody tr')).map(r => ({
      team_id: parseInt(r.getAttribute('data-team'), 10),
      team_abbrev: r.getAttribute('data-abbrev'),
      seed: parseInt(r.querySelector('.ct-seed').value, 10),
    }));
    const size = teams.length;
    const s = teams.map(t => t.seed).sort((a, b) => a - b);
    let ok = s.length === size;
    for (let i = 0; i < size; i++) if (s[i] !== i + 1) ok = false;
    if (!ok) return { error: `${conf}: seeds must be 1..${size} with no gaps or duplicates` };
    fields[conf] = teams;
  }
  return { fields };
}

// ---------------------------------------------------------------- NCAA 64-team editor

export function ncaaTeamIndex(conferences) {
  const idx = {};
  Object.entries(conferences || {}).forEach(([conf, teams]) => teams.forEach(t => { idx[t.team_id] = { ...t, conference: conf }; }));
  return idx;
}

export function ncaaTeamOptions(conferences) {
  return Object.keys(conferences || {}).sort().map(conf =>
    `<optgroup label="${esc(conf)}">${conferences[conf].map(t =>
      `<option value="${esc(t.team_id)}">${esc(t.team_abbrev)} (${esc(t.wins)}-${esc(t.losses)}, ELO ${esc(t.elo)})</option>`).join('')}</optgroup>`).join('');
}

/** Conference champion dropdowns (auto-bids). */
export function renderNcaaChampions(field, conferences) {
  const champByConf = {};
  (field || []).forEach(t => { if (t.qualifier === 'auto_bid') champByConf[t.conference] = t.team_id; });
  const confs = Object.keys(conferences || {}).filter(c => c !== 'Independent').sort();
  return `<div class="form-grid">${confs.map(conf => {
    const cur = champByConf[conf];
    const opts = conferences[conf].map(t => `<option value="${esc(t.team_id)}"${t.team_id === cur ? ' selected' : ''}>${esc(t.team_abbrev)} (${esc(t.wins)}-${esc(t.losses)}, ELO ${esc(t.elo)})</option>`).join('');
    return `<div class="form-group"><label>${esc(conf)}</label><select class="ncaa-champ" data-conf="${esc(conf)}">${opts}</select></div>`;
  }).join('')}</div>`;
}

export function collectNcaaChampions(root) {
  const champs = {};
  root.querySelectorAll('.ncaa-champ').forEach(s => { if (s.value) champs[s.getAttribute('data-conf')] = parseInt(s.value, 10); });
  return champs;
}

/** 16 regional tables with a team select per slot. Caller sets select values afterwards. */
export function renderNcaaEditorField(field, optionsHtml) {
  const byReg = {};
  (field || []).forEach(t => { (byReg[t.regional_no] = byReg[t.regional_no] || []).push(t); });
  let h = '<div class="grid-4 mt-2">';
  Object.keys(byReg).map(Number).sort((a, b) => a - b).forEach(n => {
    const teams = byReg[n].slice().sort((a, b) => a.regional_seed - b.regional_seed);
    const nat = teams[0] && teams[0].national_seed ? ` · Nat #${esc(teams[0].national_seed)}` : '';
    h += `<div class="table-container"><table class="data-table compact"><thead><tr><th colspan="3">Regional ${n}${nat}</th></tr></thead><tbody>`;
    teams.forEach(t => {
      h += `<tr><td style="width:36px">#${esc(t.regional_seed)}</td><td><select class="ncaa-slot" data-reg="${n}" data-rseed="${esc(t.regional_seed)}">${optionsHtml}</select></td><td class="ncaa-meta small text-muted nowrap"></td></tr>`;
    });
    h += '</tbody></table></div>';
  });
  return h + '</div>';
}

export function applyNcaaSlotValues(root, field) {
  (field || []).forEach(t => {
    const sel = root.querySelector(`.ncaa-slot[data-reg="${t.regional_no}"][data-rseed="${t.regional_seed}"]`);
    if (sel) sel.value = String(t.team_id);
  });
}

export function refreshNcaaMeta(root, teamById) {
  root.querySelectorAll('.ncaa-slot').forEach(sel => {
    const meta = sel.closest('tr').querySelector('.ncaa-meta');
    const t = teamById[parseInt(sel.value, 10)];
    if (meta) meta.textContent = t ? `${t.wins}-${t.losses} · ELO ${t.elo}` : '';
  });
}

/** Flags rows whose team is used more than once (row-danger). Returns the duplicate count. */
export function highlightNcaaDuplicates(root) {
  const counts = {};
  const slots = Array.from(root.querySelectorAll('.ncaa-slot'));
  slots.forEach(s => { counts[s.value] = (counts[s.value] || 0) + 1; });
  let dups = 0;
  slots.forEach(s => {
    const dup = counts[s.value] > 1;
    s.closest('tr').classList.toggle('row-danger', dup);
    if (dup) dups++;
  });
  return dups;
}

/** Returns { field } (64 slots) or { error }. */
export function collectNcaaField(root) {
  const slots = Array.from(root.querySelectorAll('.ncaa-slot'));
  if (slots.length !== 64) return { error: 'Field is not fully built — click Suggest Field first.' };
  if (highlightNcaaDuplicates(root) > 0) return { error: 'A team is used more than once — fix the highlighted slots.' };
  return {
    field: slots.map(s => ({
      team_id: parseInt(s.value, 10),
      regional_no: parseInt(s.getAttribute('data-reg'), 10),
      regional_seed: parseInt(s.getAttribute('data-rseed'), 10),
    })),
  };
}

// ---------------------------------------------------------------- matchup editor (levels 5-9)

function matchupTeamSelect(pool, conf, selectedId, cls) {
  const opts = pool.filter(p => !conf || p.conference === conf).map(p => {
    const seed = p.seed ? ` (#${p.seed})` : '';
    return `<option value="${esc(p.team_id)}" data-seed="${esc(p.seed ?? '')}"${p.team_id === selectedId ? ' selected' : ''}>${esc(p.team_abbrev)}${esc(seed)}</option>`;
  }).join('');
  return `<select class="${cls}">${opts}</select>`;
}

export function renderMatchupEditor(st) {
  let h = `<div class="mb-1">${badge(`Round ${st.round}`, 'pending')}</div>`;
  h += '<div class="table-container"><table class="data-table compact"><thead><tr><th>Conf</th><th>#</th><th>Team A (home G1)</th><th style="width:80px">Seed</th><th>Team B</th><th style="width:80px">Seed</th><th>Bo</th><th>Status</th></tr></thead><tbody>';
  st.series.forEach(s => {
    const conf = s.conference || '';
    if (!s.editable) {
      h += `<tr><td>${esc(conf || '—')}</td><td>${esc(s.series_number)}</td><td>${esc(s.team_a.abbrev)}</td><td>${esc(s.team_a.seed ?? '')}</td>
        <td>${esc(s.team_b.abbrev)}</td><td>${esc(s.team_b.seed ?? '')}</td><td>${esc(s.series_length)}</td><td>${badge(s.status, 'success')}</td></tr>`;
      return;
    }
    h += `<tr class="po-mu-row" data-sid="${esc(s.series_id)}" data-conf="${esc(conf)}"><td>${esc(conf || '—')}</td><td>${esc(s.series_number)}</td>
      <td>${matchupTeamSelect(st.pool, s.conference, s.team_a.id, 'po-mu-a')}</td><td><input type="number" min="1" class="po-mu-seed-a" value="${esc(s.team_a.seed ?? '')}"></td>
      <td>${matchupTeamSelect(st.pool, s.conference, s.team_b.id, 'po-mu-b')}</td><td><input type="number" min="1" class="po-mu-seed-b" value="${esc(s.team_b.seed ?? '')}"></td>
      <td>${esc(s.series_length)}</td><td>${badge(s.status, 'pending')}</td></tr>`;
  });
  return h + '</tbody></table></div>';
}

/** When a team is picked, pre-fill its persisted seed (still editable). */
export function syncMatchupSeed(selectEl) {
  const seedCls = selectEl.classList.contains('po-mu-a') ? '.po-mu-seed-a' : '.po-mu-seed-b';
  const seed = (selectEl.selectedOptions[0] && selectEl.selectedOptions[0].dataset.seed) || '';
  const inp = selectEl.closest('tr').querySelector(seedCls);
  if (inp) inp.value = seed;
}

export function collectMatchupEdits(root, st) {
  const edits = [];
  root.querySelectorAll('.po-mu-row').forEach(row => {
    const sid = parseInt(row.dataset.sid, 10);
    const orig = st.series.find(s => s.series_id === sid);
    if (!orig) return;
    const a = parseInt(row.querySelector('.po-mu-a').value, 10);
    const b = parseInt(row.querySelector('.po-mu-b').value, 10);
    const sa = row.querySelector('.po-mu-seed-a').value;
    const sb = row.querySelector('.po-mu-seed-b').value;
    const seedA = sa === '' ? null : parseInt(sa, 10);
    const seedB = sb === '' ? null : parseInt(sb, 10);
    const changed = a !== orig.team_a.id || b !== orig.team_b.id || seedA !== orig.team_a.seed || seedB !== orig.team_b.seed;
    if (changed) edits.push({ series_id: sid, team_a_id: a, team_b_id: b, seed_a: seedA, seed_b: seedB });
  });
  return edits;
}
