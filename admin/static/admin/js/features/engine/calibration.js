// features/engine/calibration.js — weight calibration, profiles, recompute displayovr, player preview
// (port of legacy #section-weight-calibration; endpoints /admin/calibration/*).

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q, qa, esc } from '../../core/html.js';
import { SIM_LEVELS, levelName } from '../../core/constants.js';
import { fmtNum, fmtDate } from '../../core/format.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { dataTable, simpleTable, kvTable } from '../../ui/table.js';
import { badge, kpi, alertBox, emptyState } from '../../ui/badge.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked, busyButton } from '../../ui/task-runner.js';
import { leagueYearSelect, levelSelect, fillSelect } from '../../ui/selectors.js';
import { RATING_TYPE_ORDER, POSITION_RATING_ORDER, ratingLabel, attrLabel, fx, scaleKind, show, setStatus } from './_shared.js';

const CONFIDENCE_KIND = Object.freeze({ high: 'success', moderate: 'warning', low: 'danger' });

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Run calibration</h3><p class="card-sub text-muted">Derives position weights from game stats via OLS regression and saves them as a new (inactive) profile. Requires a completed season with stats data.</p></div>
      </div>
      ${raw(formGrid([
        `<div class="form-group"><label for="cal-ly">League year</label><select id="cal-ly"></select></div>`,
        `<div class="form-group"><label for="cal-level">Level</label><select id="cal-level"></select></div>`,
        field.number('min_innings', 'Min innings (fielders)', { value: 50, min: 10, max: 500 }),
        field.number('min_at_bats', 'Min AB (DH)', { value: 100, min: 10, max: 700 }),
        field.number('min_ipo', 'Min IPO (pitchers)', { value: 60, min: 10, max: 500 }),
        field.text('name', 'Profile name (optional)', { placeholder: 'Auto-generated if blank' }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" id="btn-run">Run calibration</button></div>
      <div class="mt-1" id="cal-run-progress"></div>
      <div class="mt-2" id="cal-results-wrap" style="display:none">
        <h4 class="mb-1">Calibration results</h4>
        <div id="cal-results"></div>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Weight profiles</h3><p class="card-sub text-muted">Activate a profile to push its weights into the live rating system (rating_overall_weights) and recompute displayovr for all players. "View" opens the editor for all 13 rating types.</p></div>
        <div class="card-actions"><button class="btn btn-sm btn-ghost" data-action="refresh-profiles">Refresh</button></div>
      </div>
      <div id="cal-profiles"></div>
    </div>

    <div class="card" id="cal-detail-card" style="display:none">
      <div class="card-head">
        <div><h3 id="cal-detail-title">Profile detail</h3><p class="card-sub text-muted">Edit weights per rating type (columns). Save writes the profile; if it is the active profile, live weights and displayovr are recomputed in the same call.</p></div>
        <div class="card-actions">
          <button class="btn btn-sm btn-secondary" data-action="normalize">Normalize columns</button>
          <button class="btn btn-sm btn-primary" data-action="save-weights">Save changes</button>
          <button class="btn btn-sm btn-ghost" data-action="close-detail">Close</button>
        </div>
      </div>
      <div class="mt-1" id="cal-edit-status"></div>
      <div id="cal-detail"></div>
    </div>

    <div class="card" id="cal-compare-card" style="display:none">
      <div class="card-head"><div><h3>Profile comparison</h3></div></div>
      <div class="row mb-2">
        <div class="form-group"><label for="cal-cmp-a">Profile A</label><select id="cal-cmp-a"></select></div>
        <div class="form-group"><label for="cal-cmp-b">Profile B</label><select id="cal-cmp-b"></select></div>
        <div class="form-group"><label>&nbsp;</label><button class="btn btn-secondary" data-action="compare">Compare</button></div>
      </div>
      <div id="cal-compare"></div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head"><div><h3>Recompute display OVR</h3><p class="card-sub text-muted">Recompute displayovr for all players using the active weight profile. Runs automatically when a profile is activated or an active profile is edited.</p></div></div>
        <div class="row">
          <div class="form-group"><label for="cal-ovr-level">Level (optional)</label><select id="cal-ovr-level"></select></div>
          <div class="form-group"><label>&nbsp;</label><button class="btn btn-primary" id="btn-recompute">Recompute</button></div>
        </div>
        <div class="mt-1" id="cal-ovr-status"></div>
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Player preview</h3><p class="card-sub text-muted">Preview how the active weights compute ratings for one player. Pick level → org → team → player.</p></div></div>
        <div class="row">
          <div class="form-group"><label for="cal-prev-level">Level</label><select id="cal-prev-level"></select></div>
          <div class="form-group"><label for="cal-prev-org">Org</label><select id="cal-prev-org"><option value="">--</option></select></div>
          <div class="form-group"><label for="cal-prev-team">Team</label><select id="cal-prev-team"><option value="">--</option></select></div>
          <div class="form-group"><label for="cal-prev-player">Player</label><select id="cal-prev-player"><option value="">--</option></select></div>
          <div class="form-group"><label>&nbsp;</label><button class="btn btn-primary" id="btn-preview">Preview</button></div>
        </div>
        <div class="mt-1" id="cal-prev-status"></div>
      </div>
    </div>

    <div class="card" id="cal-prev-card" style="display:none">
      <div class="card-head"><div><h3 id="cal-prev-title">Player rating preview</h3></div></div>
      <div id="cal-prev"></div>
    </div>`);

  const lySel = await leagueYearSelect(q(el, '#cal-ly'), { signal: ctx.signal });
  const levelSel = levelSelect(q(el, '#cal-level'), { levels: SIM_LEVELS, value: 9 });
  const ovrLevelSel = levelSelect(q(el, '#cal-ovr-level'), { levels: SIM_LEVELS, allowAll: true });
  levelSelect(q(el, '#cal-prev-level'), { levels: SIM_LEVELS, allowAll: true, allLabel: 'Select…' });

  // Per-mount state.
  let profiles = [];
  let detail = { id: null, orig: null, types: [] };

  // ── Run calibration ──────────────────────────────────────────────────
  const runWidget = progressWidget(q(el, '#cal-run-progress'), { showResult: false });
  const resultsTable = dataTable(q(el, '#cal-results'), {
    rowKey: 'rt', emptyText: 'No positions calibrated.', compact: true,
    columns: [
      { key: 'rt', title: 'Position', render: r => ratingLabel(r.rt) },
      { key: 'n', title: 'N', align: 'right' },
      { key: 'confidence_level', title: 'Confidence', html: true, render: r => (r.confidence_level ? badge(r.confidence_level, CONFIDENCE_KIND[r.confidence_level] || 'secondary') : '—') },
      { key: 'offense_r2', title: 'Off R²', align: 'right', render: r => fx(r.offense_r2, 3, '—') },
      { key: 'offense_adj_r2', title: 'Off adj R²', align: 'right', render: r => fx(r.offense_adj_r2, 3, '—') },
      { key: 'defense_r2', title: 'Def R²', align: 'right', render: r => fx(r.defense_r2 ?? r.r2, 3, '—') },
      { key: 'defense_adj_r2', title: 'Def adj R²', align: 'right', render: r => fx(r.defense_adj_r2 ?? r.adj_r2, 3, '—') },
      { key: 'skipped', title: 'Status', html: true, render: r => badge(r.skipped ? 'Skipped' : 'OK', r.skipped ? 'warning' : 'success') },
      { key: 'warnings', title: 'Warnings', render: r => ((r.warnings || []).length ? `${r.warnings.length} warning(s)` : '—'), title_attr: r => (r.warnings || []).join('\n') },
    ],
  });

  busyButton(q(el, '#btn-run'), async () => {
    const f = readForm(q(el, '.card'));
    const body = {
      league_year_id: lySel.get(), league_level: levelSel.get(),
      config: { min_innings: f.min_innings || 50, min_at_bats: f.min_at_bats || 100, min_ipo: f.min_ipo || 60 },
    };
    if (f.name && f.name.trim()) body.name = f.name.trim();
    if (!body.league_year_id) { toast.warn('Pick a league year'); return; }
    if (!await confirm({ title: 'Run calibration?', message: `OLS regression on league year ${body.league_year_id}, level ${levelName(body.league_level)}. Creates a new inactive profile; nothing goes live until you activate it.` })) return;
    try {
      const d = await runTracked({
        el: q(el, '#cal-run-progress'), widget: runWidget, label: 'Running calibration…', signal: ctx.signal,
        start: () => api.post(adm('/calibration/run'), body, { signal: ctx.signal }),
      });
      runWidget.done(undefined, `Profile "${d.name}" created (ID ${d.profile_id})`);
      toast.success(`Profile "${d.name}" created`);
      const rows = POSITION_RATING_ORDER.filter(rt => d.positions && d.positions[rt]).map(rt => ({ rt, ...d.positions[rt] }));
      resultsTable.setRows(rows);
      show(q(el, '#cal-results-wrap'), true);
      await loadProfiles();
    } catch (e) { /* widget + api layer already reported */ }
  });

  // ── Profiles ─────────────────────────────────────────────────────────
  const profilesTable = dataTable(q(el, '#cal-profiles'), {
    rowKey: 'id', emptyText: 'No weight profiles yet. Run a calibration to create one.',
    rowClass: p => (p.is_active ? 'row-success' : ''),
    columns: [
      { key: 'name', title: 'Name', sortable: true },
      { key: 'source', title: 'Source', html: true, sortable: true, render: p => badge(p.source || '?', p.source === 'calibration' ? 'info' : 'secondary') },
      { key: 'league_level', title: 'Level', sortable: true, render: p => (p.league_level != null ? `${p.league_level} - ${levelName(p.league_level)}` : '—') },
      { key: 'is_active', title: 'Active', html: true, sortable: true, render: p => (p.is_active ? badge('Active', 'success') : '') },
      { key: 'created_at', title: 'Created', sortable: true, render: p => fmtDate(p.created_at) },
      { key: '_a', title: '', html: true, render: p => `<div class="row nowrap"><button class="btn btn-xs btn-secondary" data-action="view" data-id="${p.id}">View</button>${p.is_active ? '' : `<button class="btn btn-xs btn-warning" data-action="activate" data-id="${p.id}">Activate</button>`}</div>` },
    ],
  });

  async function loadProfiles() {
    profilesTable.setLoading();
    try {
      const d = await api.get(adm('/calibration/profiles'), { signal: ctx.signal });
      profiles = d.profiles || [];
      profilesTable.setRows(profiles);
      const opts = profiles.map(p => ({ value: p.id, label: p.name }));
      const a = q(el, '#cal-cmp-a'), b = q(el, '#cal-cmp-b');
      fillSelect(a, opts, { value: a.value });
      fillSelect(b, opts, { value: b.value || (opts[1] && opts[1].value) });
      show(q(el, '#cal-compare-card'), profiles.length >= 2);
    } catch (e) {
      if (e.name !== 'AbortError') profilesTable.setError(e.message);
    }
  }

  async function activateProfile(id) {
    const p = profiles.find(x => x.id === id);
    if (!await confirm({ title: `Activate "${p ? p.name : id}"?`, danger: true, confirmLabel: 'Activate',
      message: 'Updates the live rating weights and recomputes displayovr for all players. The previously active profile is deactivated.' })) return;
    const d = await api.post(adm(`/calibration/activate/${id}`), {}, { signal: ctx.signal });
    toast.success(`Activated — ${fmtNum(d.entries)} weight entries applied.${d.displayovr_updated ? ` DisplayOVR updated for ${fmtNum(d.displayovr_updated)} players.` : ''}`);
    await loadProfiles();
    if (detail.id === id) await viewProfile(id);
  }

  // ── Profile detail / weight editor ───────────────────────────────────
  async function viewProfile(id) {
    const card = q(el, '#cal-detail-card');
    const box = q(el, '#cal-detail');
    show(card, true);
    setHtml(box, '<span class="spinner spinner-sm"></span> Loading…');
    setStatus(q(el, '#cal-edit-status'), '');
    let p;
    try {
      p = (await api.get(adm(`/calibration/profiles/${id}`), { signal: ctx.signal })).profile;
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(box, raw(alertBox('danger', e.message)));
      return;
    }
    const weights = p.weights || {};
    const types = RATING_TYPE_ORDER.filter(rt => weights[rt]);
    detail = { id, orig: JSON.parse(JSON.stringify(weights)), types };
    q(el, '#cal-detail-title').textContent = `Profile: ${p.name} (${p.source})${p.is_active ? ' — active' : ''}`;
    const attrs = [...new Set(types.flatMap(rt => Object.keys(weights[rt] || {})))].sort();
    const missing = ['pitcher_overall', 'position_overall'].filter(rt => !weights[rt]);

    const head = `<tr><th>Attribute</th>${types.map(rt => `<th class="text-center" title="${esc(rt)}">${esc(ratingLabel(rt))}</th>`).join('')}</tr>`;
    const body = attrs.map(attr => `<tr><td class="small">${esc(attrLabel(attr))}</td>${types.map(rt => {
      const w = Number((weights[rt] || {})[attr] || 0);
      return `<td class="text-center"><input type="number" step="0.001" min="0" max="1" value="${w.toFixed(4)}" data-rt="${esc(rt)}" data-attr="${esc(attr)}" data-orig="${w}" class="cell-input mono small${w > 0 ? '' : ' text-muted'}" style="width:70px" /></td>`;
    }).join('')}</tr>`).join('');
    const sums = `<tr class="row-muted"><td><strong>Sum</strong></td>${types.map(rt => `<td class="text-center"><strong data-sum="${esc(rt)}">${Object.values(weights[rt] || {}).reduce((a, b) => a + Number(b || 0), 0).toFixed(3)}</strong></td>`).join('')}</tr>`;

    setHtml(box, html`
      ${missing.length ? raw(alertBox('warning', `This profile has no ${missing.join(' / ')} weights; players without a listed position fall back to code defaults. Re-run calibration to add them.`)) : ''}
      <div class="table-container" style="max-height:520px;overflow:auto">
        <table class="data-table compact sticky"><thead>${raw(head)}</thead><tbody>${raw(body)}${raw(sums)}</tbody></table>
      </div>
      ${p.calibration ? html`<details class="mt-2"><summary class="text-muted">Calibration details</summary><pre class="result-box mt-1">${JSON.stringify(p.calibration.results, null, 2)}</pre></details>` : ''}
      ${raw(kvTable([
        ['Description', p.description || '—'],
        ['Created', fmtDate(p.created_at)],
        ['Rating types', `${types.length} (${attrs.length} attributes)`],
      ]))}`);
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function recalcSums() {
    const box = q(el, '#cal-detail');
    for (const rt of detail.types) {
      let sum = 0;
      for (const inp of qa(box, `input[data-rt="${CSS.escape(rt)}"]`)) sum += parseFloat(inp.value) || 0;
      const cell = q(box, `[data-sum="${CSS.escape(rt)}"]`);
      if (cell) cell.textContent = sum.toFixed(3);
    }
  }

  on(q(el, '#cal-detail'), 'input', (e) => {
    const inp = e.target;
    if (!inp.dataset || !inp.dataset.rt) return;
    const changed = Math.abs((parseFloat(inp.value) || 0) - (parseFloat(inp.dataset.orig) || 0)) > 0.0001;
    inp.classList.toggle('text-warning', changed);
    inp.classList.toggle('text-muted', !changed && !(parseFloat(inp.value) > 0));
    recalcSums();
  }, ctx.signal);

  function readWeights() {
    const out = {};
    for (const inp of qa(q(el, '#cal-detail'), 'input[data-rt]')) {
      (out[inp.dataset.rt] = out[inp.dataset.rt] || {})[inp.dataset.attr] = parseFloat(inp.value) || 0;
    }
    return out;
  }

  async function saveWeights() {
    if (!detail.id) return;
    const weights = readWeights();
    const st = q(el, '#cal-edit-status');
    const p = profiles.find(x => x.id === detail.id);
    if (p && p.is_active && !await confirm({ title: 'Save weights of the ACTIVE profile?', danger: true, confirmLabel: 'Save & push live',
      message: 'This profile is live: the new weights are pushed to rating_overall_weights and displayovr is recomputed for all players immediately.' })) return;
    try {
      const res = await api.put(adm(`/calibration/profiles/${detail.id}/weights`), { weights }, { signal: ctx.signal });
      let msg = `Saved ${fmtNum(res.updated)} entries`;
      if (res.activated && res.recompute && res.recompute.updated != null) msg += ` — live: recomputed displayovr for ${fmtNum(res.recompute.updated)} players`;
      else if (!res.activated) msg += ' (profile is not active — activate to push to live)';
      setStatus(st, msg, 'success');
      toast.success(msg);
      detail.orig = JSON.parse(JSON.stringify(weights));
      for (const inp of qa(q(el, '#cal-detail'), 'input[data-rt]')) { inp.dataset.orig = inp.value; inp.classList.remove('text-warning'); }
    } catch (e) {
      if (e.name !== 'AbortError') setStatus(st, `Error: ${e.message}`, 'danger');
    }
  }

  function normalize() {
    const box = q(el, '#cal-detail');
    for (const rt of detail.types) {
      const inputs = qa(box, `input[data-rt="${CSS.escape(rt)}"]`);
      const sum = inputs.reduce((a, i) => a + (parseFloat(i.value) || 0), 0);
      if (sum > 0) inputs.forEach(i => { i.value = ((parseFloat(i.value) || 0) / sum).toFixed(4); i.dispatchEvent(new Event('input', { bubbles: true })); });
    }
    setStatus(q(el, '#cal-edit-status'), 'Normalized — remember to Save.', 'warning');
  }

  // ── Compare ──────────────────────────────────────────────────────────
  async function compare() {
    const a = q(el, '#cal-cmp-a').value, b = q(el, '#cal-cmp-b').value;
    const box = q(el, '#cal-compare');
    if (!a || !b || a === b) { toast.warn('Select two different profiles to compare.'); return; }
    setHtml(box, '<span class="spinner spinner-sm"></span> Loading…');
    try {
      const d = await api.get(adm('/calibration/compare'), { params: { a, b }, signal: ctx.signal });
      const sections = Object.entries(d.comparison || {}).map(([rt, entries]) => `
        <h4 class="mt-2 mb-1">${esc(ratingLabel(rt))}</h4>
        ${simpleTable([
          { title: 'Attribute', render: e => attrLabel(e.attribute) },
          { title: d.profile_a.name, render: e => fx(e.weight_a, 4) },
          { title: d.profile_b.name, render: e => fx(e.weight_b, 4) },
          { title: 'Delta', html: true, render: e => `<span class="${e.delta > 0 ? 'text-success' : e.delta < 0 ? 'text-warning' : ''}">${e.delta > 0 ? '+' : ''}${esc(fx(e.delta, 4))}</span>` },
        ], entries)}`).join('');
      setHtml(box, html`<p><strong>${d.profile_a.name}</strong> vs <strong>${d.profile_b.name}</strong></p>${raw(sections || emptyState('No differing weights.'))}`);
    } catch (e) {
      if (e.name !== 'AbortError') setHtml(box, raw(alertBox('danger', e.message)));
    }
  }

  // ── Recompute displayovr ─────────────────────────────────────────────
  busyButton(q(el, '#btn-recompute'), async () => {
    const level = ovrLevelSel.get();
    const st = q(el, '#cal-ovr-status');
    if (!await confirm({ title: 'Recompute display OVR?', message: `Recomputes displayovr for ${level ? levelName(level) : 'all levels'} using the active profile.` })) return;
    setStatus(st, 'Recomputing…');
    try {
      const d = await api.post(adm('/calibration/recompute-displayovr'), level ? { level } : {}, { signal: ctx.signal });
      const detailTxt = Object.entries(d.by_level || {}).map(([l, c]) => `L${l}: ${fmtNum(c)}`).join(', ');
      setStatus(st, `Updated ${fmtNum(d.updated)} players. ${detailTxt}`, 'success');
      toast.success(`DisplayOVR recomputed for ${fmtNum(d.updated)} players`);
    } catch (e) {
      if (e.name !== 'AbortError') setStatus(st, `Error: ${e.message}`, 'danger');
    }
  });

  // ── Player preview (cascade) ─────────────────────────────────────────
  const prevLevel = q(el, '#cal-prev-level'), prevOrg = q(el, '#cal-prev-org'), prevTeam = q(el, '#cal-prev-team'), prevPlayer = q(el, '#cal-prev-player');
  const filters = (params) => api.get(adm('/calibration/player-preview/filters'), { params, signal: ctx.signal });
  const reset = (...sels) => sels.forEach(s => fillSelect(s, [], { placeholder: '--' }));

  on(prevLevel, 'change', async () => {
    reset(prevOrg, prevTeam, prevPlayer);
    if (!prevLevel.value) return;
    const d = await filters({ level: prevLevel.value });
    fillSelect(prevOrg, (d.orgs || []).map(o => ({ value: o.id, label: o.abbrev })), { placeholder: '--' });
  }, ctx.signal);
  on(prevOrg, 'change', async () => {
    reset(prevTeam, prevPlayer);
    if (!prevOrg.value) return;
    const d = await filters({ org_id: prevOrg.value, level: prevLevel.value || undefined });
    fillSelect(prevTeam, (d.teams || []).map(t => ({ value: t.id, label: `${t.abbrev} (${t.level})` })), { placeholder: '--' });
  }, ctx.signal);
  on(prevTeam, 'change', async () => {
    reset(prevPlayer);
    if (!prevTeam.value) return;
    const d = await filters({ team_id: prevTeam.value });
    fillSelect(prevPlayer, (d.players || []).map(p => ({ value: p.id, label: `${p.name}${p.ptype === 'Pitcher' ? ' (P)' : ''}` })), { placeholder: '--' });
  }, ctx.signal);

  async function loadPreview(playerId) {
    const st = q(el, '#cal-prev-status');
    const card = q(el, '#cal-prev-card');
    show(card, false);
    if (!playerId) { setStatus(st, 'Select a player first.', 'warning'); return; }
    setStatus(st, 'Loading…');
    try {
      const d = await api.get(adm('/calibration/player-preview'), { params: { player_id: playerId }, signal: ctx.signal });
      setStatus(st, '');
      renderPreview(d);
      ctx.setParams({ player_id: playerId });
    } catch (e) {
      if (e.name !== 'AbortError') setStatus(st, `Error: ${e.message}`, 'danger');
    }
  }

  function renderPreview(d) {
    const p = d.player || {};
    const ov = d.overall || {};
    const isFallback = ov.type === 'pitcher_overall' || ov.type === 'position_overall';
    const typeLabel = isFallback ? `${ov.type === 'pitcher_overall' ? 'Pitcher' : 'Position'} overall (fallback)` : ratingLabel(ov.type);
    q(el, '#cal-prev-title').textContent = `${p.name} — ${p.ptype}${p.listed_position ? ` (${String(p.listed_position).toUpperCase()})` : ''} (${levelName(p.level)})`;
    const ratings = Object.entries(d.position_ratings || {}).map(([key, v]) => ({ key, ...v })).sort((a, b) => (b.scaled_20_80 || 0) - (a.scaled_20_80 || 0));
    const attrs = Object.entries(d.raw_attributes || {}).sort(([a], [b]) => a.localeCompare(b));
    setHtml(q(el, '#cal-prev'), html`
      <div class="grid-3 mb-2">
        ${raw(kpi({ label: 'Display OVR (computed)', value: d.displayovr ?? '—', sub: `stored: ${p.current_displayovr ?? 'null'}`, kind: 'info' }))}
        ${raw(kpi({ label: 'Weight type', value: typeLabel, sub: isFallback ? 'No listed position — generic fallback weights' : `listed position ${String(p.listed_position || '').toUpperCase()}`, kind: isFallback ? 'warning' : '' }))}
        ${raw(kpi({ label: 'Raw / 20-80', value: `${fx(ov.raw, 2, '—')} / ${ov.scaled_20_80 ?? '—'}`, sub: ov.peer_count != null ? `${fmtNum(ov.peer_count)} peers in cohort` : '' }))}
      </div>
      <h4 class="mb-1">Position ratings</h4>
      ${raw(simpleTable([
        { title: 'Rating', render: r => ratingLabel(r.key) },
        { title: 'Raw', render: r => fx(r.raw, 2) },
        { title: '20-80', html: true, render: r => (r.scaled_20_80 != null ? badge(r.scaled_20_80, scaleKind(r.scaled_20_80)) : '—') },
      ], ratings))}
      <details class="mt-2"><summary class="text-muted">Raw attributes (${attrs.length})</summary>
        <div class="grid-3 mt-1 small">${raw(attrs.map(([k, v]) => `<div><span class="text-muted">${esc(attrLabel(k))}:</span> ${esc(v)}</div>`).join(''))}</div>
      </details>
      <p class="mt-1"><a class="btn btn-xs btn-ghost" href="#/engine/diagnostics?pane=player&player_id=${p.id}">Progression trajectory</a></p>`);
    show(q(el, '#cal-prev-card'), true);
    q(el, '#cal-prev-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  busyButton(q(el, '#btn-preview'), () => loadPreview(Number(prevPlayer.value) || null));

  // ── Delegated actions ────────────────────────────────────────────────
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    const id = Number(btn.dataset.id);
    try {
      if (a === 'refresh-profiles') await loadProfiles();
      else if (a === 'view') await viewProfile(id);
      else if (a === 'activate') await activateProfile(id);
      else if (a === 'save-weights') await saveWeights();
      else if (a === 'normalize') normalize();
      else if (a === 'close-detail') { show(q(el, '#cal-detail-card'), false); detail = { id: null, orig: null, types: [] }; }
      else if (a === 'compare') await compare();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      // api layer already toasted
    }
  }, ctx.signal);

  await loadProfiles();
  if (ctx.params.profile) viewProfile(Number(ctx.params.profile)).catch(() => {});
  if (ctx.params.player_id) loadPreview(Number(ctx.params.player_id));
}
