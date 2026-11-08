// features/engine/rating-config.js — rating scale config + attribute analysis + growth curves
// (port of legacy #section-rating-config; endpoints /admin/rating-config*, /admin/growth-curves).

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, on, delegate, q, qa, esc } from '../../core/html.js';
import { LEVEL_NAMES, levelName } from '../../core/constants.js';
import { fmtNum } from '../../core/format.js';
import { kpi } from '../../ui/badge.js';
import { dataTable } from '../../ui/table.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { busyButton } from '../../ui/task-runner.js';
import { levelSelect, fillSelect } from '../../ui/selectors.js';
import { levelBadge, ptypeBadge, attrCategoryClass, cellInput, fx, show, setStatus } from './_shared.js';

const ALL_CONFIG_LEVELS = Object.freeze(Object.keys(LEVEL_NAMES).map(Number).sort((a, b) => b - a));

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="grid-2" id="rc-kpis">
      ${raw(kpi({ label: 'Config status', value: '--', sub: 'Not loaded', id: 'rc-kpi-status' }))}
      ${raw(kpi({ label: 'Levels configured', value: '--', sub: '--', id: 'rc-kpi-levels' }))}
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Analyze player data</h3><p class="card-sub text-muted">Computes mean/std and quartiles for every attribute at every level from current player data and writes them to the config table. Edit the values below afterwards.</p></div>
      </div>
      <div class="alert alert-info"><strong>When to analyze:</strong> after importing new players, completing a draft, processing trades, or whenever you want fresh baseline numbers. Levels with no players are skipped.</div>
      <div class="button-group"><button class="btn btn-warning" id="btn-seed">Analyze &amp; populate</button></div>
      <pre class="result-box mt-2" id="rc-seed-result" style="display:none"></pre>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Level scale config</h3><p class="card-sub text-muted">One mean and std dev per level/type, applied uniformly to all attributes at that level for the 20-80 conversion. 20/50/80 columns show mean ∓ 3σ.</p></div>
        <div class="card-actions">
          <button class="btn btn-sm btn-secondary" data-action="load-config">Load current</button>
          <button class="btn btn-sm btn-warning" id="btn-save-config" style="display:none">Save changes</button>
        </div>
      </div>
      <div id="rc-config-table"></div>
      <div class="mt-1" id="rc-config-status"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Attribute analysis (reference)</h3><p class="card-sub text-muted">Read-only breakdown from the last analysis. Use these numbers to inform the mean/std choices above.</p></div>
      </div>
      <div class="row mb-2">
        <div class="form-group"><label for="rc-ptype">Player type</label><select id="rc-ptype"><option value="">All types</option><option value="Pitcher">Pitcher</option><option value="Position">Position</option></select></div>
        <div class="form-group"><label for="rc-level">Level</label><select id="rc-level"></select></div>
        <div class="form-group"><label for="rc-attr">Search attribute</label><input type="text" id="rc-attr" placeholder="e.g. power, pitch_pacc" /></div>
        <div class="form-group"><label>&nbsp;</label><button class="btn btn-secondary" data-action="load-analysis">Load</button></div>
      </div>
      <div id="rc-analysis-table"></div>
    </div>

    <div class="card">
      <h3>Overall rating weights</h3>
      <p class="text-muted">Overall rating weights are managed from <a href="#/engine/calibration">Weight Calibration</a>. Open a profile there to edit all 13 rating types (pitcher_overall, position_overall and the 11 position-specifics) in one place.</p>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Growth curves (progression engine)</h3><p class="card-sub text-muted">Drive <strong>both</strong> real progression and the <a href="#/engine/sandbox">sandbox</a>. Each row is a (grade, age) → triangular(min, mode, max) delta applied per season. Note: a triangular draw averages (min+mode+max)/3, not the mode.</p></div>
        <div class="card-actions">
          <div class="form-group"><select id="gc-grade"><option value="">All grades</option></select></div>
          <button class="btn btn-sm btn-secondary" data-action="load-gc">Load curves</button>
          <button class="btn btn-sm btn-warning" id="btn-save-gc" style="display:none">Save changes</button>
        </div>
      </div>
      <div id="gc-table"></div>
      <div class="mt-1" id="gc-status"></div>
    </div>`);

  levelSelect(q(el, '#rc-level'), { levels: ALL_CONFIG_LEVELS, allowAll: true });

  // ── Summary KPIs ─────────────────────────────────────────────────────
  function summarize(levels) {
    const ptypes = Object.keys(levels || {});
    const levelSet = new Set();
    let attrRows = 0;
    for (const lv of Object.values(levels || {})) {
      for (const [lvl, attrs] of Object.entries(lv)) { levelSet.add(lvl); attrRows += Object.keys(attrs).length; }
    }
    setHtml(q(el, '#rc-kpis'), raw(
      kpi({ label: 'Config status', value: ptypes.length ? 'Seeded' : 'Empty', sub: ptypes.length ? `${ptypes.length} player types` : 'Run analyze to populate', kind: ptypes.length ? 'success' : 'warning' })
      + kpi({ label: 'Levels configured', value: levelSet.size, sub: `${fmtNum(attrRows)} attribute rows` })));
  }

  async function fetchConfig(params) {
    const d = await api.get(adm('/rating-config'), { signal: ctx.signal, params });
    return d.levels || {};
  }

  // ── Level scale config (editable) ────────────────────────────────────
  const configTable = dataTable(q(el, '#rc-config-table'), {
    rowKey: 'key', emptyText: 'Click "Load current" to view.',
    columns: [
      { key: 'ptype', title: 'Type', html: true, render: r => ptypeBadge(r.ptype) },
      { key: 'levelId', title: 'Level', html: true, render: r => levelBadge(r.levelId) },
      { key: 'mean', title: 'Mean', html: true, render: r => cellInput({ value: r.mean != null ? r.mean.toFixed(2) : '', cls: 'rc-mean', data: { ptype: r.ptype, level: r.levelId, orig: r.mean != null ? r.mean : '' } }).replace('<input ', r.uniform ? '<input ' : '<input placeholder="varies" ') },
      { key: 'std', title: 'Std dev', html: true, render: r => cellInput({ value: r.std != null ? r.std.toFixed(2) : '', min: 0, cls: 'rc-std', data: { ptype: r.ptype, level: r.levelId, orig: r.std != null ? r.std : '' } }).replace('<input ', r.uniform ? '<input ' : '<input placeholder="varies" ') },
      { key: 'lo', title: '20', html: true, cellClass: 'text-muted', render: r => `<span class="rc-20">${r.std > 0 ? fx(r.mean - 3 * r.std, 1) : '--'}</span>` },
      { key: 'mid', title: '50', html: true, render: r => `<strong class="rc-50">${r.mean != null ? fx(r.mean, 1) : '--'}</strong>` },
      { key: 'hi', title: '80', html: true, cellClass: 'text-muted', render: r => `<span class="rc-80">${r.std > 0 ? fx(r.mean + 3 * r.std, 1) : '--'}</span>` },
    ],
  });

  async function loadConfig() {
    configTable.setLoading();
    show(q(el, '#btn-save-config'), false);
    try {
      const levels = await fetchConfig();
      summarize(levels);
      const rows = [];
      for (const ptype of Object.keys(levels).sort()) {
        for (const levelId of Object.keys(levels[ptype]).sort((a, b) => Number(a) - Number(b))) {
          const attrs = levels[ptype][levelId];
          const vals = Object.values(attrs);
          if (!vals.length) continue;
          const uniform = vals.every(v => Math.abs(v.mean - vals[0].mean) < 0.001 && Math.abs(v.std - vals[0].std) < 0.001);
          rows.push({ key: `${ptype}|${levelId}`, ptype, levelId: Number(levelId), mean: uniform ? vals[0].mean : null, std: uniform ? vals[0].std : null, uniform });
        }
      }
      configTable.setRows(rows);
      if (!rows.length) configTable.setError('No config data. Run "Analyze & populate" first.');
      show(q(el, '#btn-save-config'), rows.length > 0);
      setStatus(q(el, '#rc-config-status'), '');
    } catch (e) {
      if (e.name !== 'AbortError') configTable.setError(e.message);
    }
  }

  // Live recompute of the 20/50/80 columns while editing.
  on(q(el, '#rc-config-table'), 'input', (e) => {
    const tr = e.target.closest('tr');
    if (!tr || !e.target.classList.contains('cell-input')) return;
    const m = parseFloat(q(tr, '.rc-mean').value) || 0;
    const s = parseFloat(q(tr, '.rc-std').value) || 0;
    q(tr, '.rc-20').textContent = s > 0 ? (m - 3 * s).toFixed(1) : '--';
    q(tr, '.rc-50').textContent = m.toFixed(1);
    q(tr, '.rc-80').textContent = s > 0 ? (m + 3 * s).toFixed(1) : '--';
  }, ctx.signal);

  busyButton(q(el, '#btn-save-config'), async () => {
    const levels = [];
    const means = qa(el, '#rc-config-table .rc-mean');
    const stds = qa(el, '#rc-config-table .rc-std');
    means.forEach((mi, i) => {
      const si = stds[i];
      const newMean = parseFloat(mi.value), newStd = parseFloat(si.value);
      if (Number.isNaN(newMean) || Number.isNaN(newStd)) return;
      const om = parseFloat(mi.dataset.orig), os = parseFloat(si.dataset.orig);
      if (!Number.isNaN(om) && !Number.isNaN(os) && Math.abs(newMean - om) < 0.001 && Math.abs(newStd - os) < 0.001) return;
      levels.push({ level_id: Number(mi.dataset.level), ptype: mi.dataset.ptype, mean_value: newMean, std_dev: newStd });
    });
    const st = q(el, '#rc-config-status');
    if (!levels.length) { setStatus(st, 'No changes detected.', 'muted'); return; }
    if (!await confirm({ title: `Save ${levels.length} level(s)?`, message: 'Sets the mean/std of every attribute at those levels. The 20-80 display of all affected players changes immediately.' })) return;
    try {
      const d = await api.put(adm('/rating-config/levels'), { levels }, { signal: ctx.signal });
      setStatus(st, `Saved. ${fmtNum(d.updated)} attribute row(s) updated across ${levels.length} level(s).`, 'success');
      toast.success('Level scale config saved');
      means.forEach(i => { i.dataset.orig = i.value; });
      stds.forEach(i => { i.dataset.orig = i.value; });
    } catch (e) {
      if (e.name !== 'AbortError') setStatus(st, `Error: ${e.message}`, 'danger');
    }
  });

  // ── Analyze & populate ───────────────────────────────────────────────
  busyButton(q(el, '#btn-seed'), async () => {
    if (!await confirm({ title: 'Analyze & populate?', message: 'Recomputes mean/std and quartiles for every attribute at every level from current player data and overwrites rating_scale_config. Hand-edited level means are replaced.', danger: true, confirmLabel: 'Analyze' })) return;
    const box = q(el, '#rc-seed-result');
    show(box, true);
    box.textContent = 'Seeding config from player data…';
    try {
      const d = await api.post(adm('/rating-config/seed'), {}, { signal: ctx.signal });
      const levels = d.levels || {}, counts = d.player_counts || {};
      let details = '';
      for (const ptype of Object.keys(levels).sort()) {
        details += `\n${ptype}:\n` + Object.entries(levels[ptype]).sort(([a], [b]) => Number(a) - Number(b))
          .map(([lvl, n]) => `  Level ${lvl} (${levelName(lvl)}): ${n} attributes from ${(counts[ptype] || {})[Number(lvl)] || 0} players`).join('\n');
      }
      box.textContent = `Success. ${fmtNum(d.rows_written)} rows written.\n${details}`;
      toast.success(`Rating config seeded: ${fmtNum(d.rows_written)} rows`);
      await loadConfig();
    } catch (e) {
      if (e.name !== 'AbortError') box.textContent = `Error: ${e.message}`;
    }
  });

  // ── Attribute analysis ───────────────────────────────────────────────
  let analysis = null;
  const analysisTable = dataTable(q(el, '#rc-analysis-table'), {
    rowKey: 'key', emptyText: 'Click "Load" to view data.', pageSize: 100,
    columns: [
      { key: 'ptype', title: 'Type', html: true, sortable: true, render: r => ptypeBadge(r.ptype) },
      { key: 'levelId', title: 'Level', html: true, sortable: true, render: r => levelBadge(r.levelId) },
      { key: 'attrKey', title: 'Attribute', html: true, sortable: true, render: r => `<code class="${attrCategoryClass(r.attrKey)}">${esc(r.attrKey)}</code>` },
      { key: 'p25', title: 'P25', align: 'right', cellClass: 'text-muted', sortable: true, render: r => fx(r.p25, 1) },
      { key: 'median', title: 'Median', align: 'right', cellClass: 'text-muted', sortable: true, render: r => fx(r.median, 1) },
      { key: 'p75', title: 'P75', align: 'right', cellClass: 'text-muted', sortable: true, render: r => fx(r.p75, 1) },
      { key: 'mean', title: 'Seed mean', align: 'right', sortable: true, render: r => fx(r.mean, 2) },
      { key: 'std', title: 'Seed std', align: 'right', sortable: true, render: r => fx(r.std, 2) },
    ],
  });

  function renderAnalysis() {
    if (!analysis) return;
    const term = (q(el, '#rc-attr').value || '').toLowerCase().trim();
    const rows = [];
    for (const ptype of Object.keys(analysis).sort()) {
      for (const levelId of Object.keys(analysis[ptype]).sort((a, b) => Number(a) - Number(b))) {
        for (const attrKey of Object.keys(analysis[ptype][levelId]).sort()) {
          if (term && !attrKey.toLowerCase().includes(term)) continue;
          rows.push({ key: `${ptype}|${levelId}|${attrKey}`, ptype, levelId: Number(levelId), attrKey, ...analysis[ptype][levelId][attrKey] });
        }
      }
    }
    analysisTable.setRows(rows);
    if (!rows.length) analysisTable.setError(term ? 'No matching attributes.' : 'No data. Run "Analyze & populate" first.');
  }

  async function loadAnalysis() {
    analysisTable.setLoading();
    try {
      analysis = await fetchConfig({ level: q(el, '#rc-level').value, ptype: q(el, '#rc-ptype').value });
      renderAnalysis();
    } catch (e) {
      if (e.name !== 'AbortError') analysisTable.setError(e.message);
    }
  }
  on(q(el, '#rc-attr'), 'input', renderAnalysis, ctx.signal);

  // ── Growth curves (editable) ─────────────────────────────────────────
  let curves = null;
  const gcTable = dataTable(q(el, '#gc-table'), {
    rowKey: 'key', emptyText: 'Click "Load curves" to view.',
    columns: [
      { key: 'grade', title: 'Grade' },
      { key: 'age', title: 'Age', align: 'right' },
      { key: 'prog_min', title: 'Min', html: true, render: r => cellInput({ value: r.prog_min, cls: 'gc-input', data: { grade: r.grade, age: r.age, field: 'prog_min', orig: r.prog_min } }) },
      { key: 'prog_mode', title: 'Mode', html: true, render: r => cellInput({ value: r.prog_mode, cls: 'gc-input', data: { grade: r.grade, age: r.age, field: 'prog_mode', orig: r.prog_mode } }) },
      { key: 'prog_max', title: 'Max', html: true, render: r => cellInput({ value: r.prog_max, cls: 'gc-input', data: { grade: r.grade, age: r.age, field: 'prog_max', orig: r.prog_max } }) },
      { key: 'mean', title: 'Mean (min+mode+max)/3', align: 'right', cellClass: 'text-muted', html: true, render: r => `<span class="gc-mean">${fx((r.prog_min + r.prog_mode + r.prog_max) / 3, 2)}</span>` },
    ],
  });

  function renderCurves() {
    if (!curves) return;
    const filter = q(el, '#gc-grade').value;
    const grades = filter ? [filter] : Object.keys(curves).sort();
    const rows = [];
    for (const grade of grades) for (const r of curves[grade] || []) rows.push({ key: `${grade}|${r.age}`, grade, ...r });
    gcTable.setRows(rows);
  }

  async function loadCurves() {
    gcTable.setLoading();
    setStatus(q(el, '#gc-status'), '');
    try {
      const d = await api.get(adm('/growth-curves'), { signal: ctx.signal });
      curves = d.curves || {};
      const sel = q(el, '#gc-grade');
      fillSelect(sel, (d.grades || []).map(g => ({ value: g, label: g })), { value: sel.value, placeholder: 'All grades' });
      renderCurves();
      show(q(el, '#btn-save-gc'), true);
    } catch (e) {
      if (e.name !== 'AbortError') gcTable.setError(e.message);
    }
  }
  on(q(el, '#gc-grade'), 'change', renderCurves, ctx.signal);
  on(q(el, '#gc-table'), 'input', (e) => {
    const tr = e.target.closest('tr');
    if (!tr || !e.target.classList.contains('gc-input')) return;
    const v = f => parseFloat(q(tr, `[data-field="${f}"]`).value) || 0;
    q(tr, '.gc-mean').textContent = ((v('prog_min') + v('prog_mode') + v('prog_max')) / 3).toFixed(2);
  }, ctx.signal);

  busyButton(q(el, '#btn-save-gc'), async () => {
    const map = {};
    let changed = 0;
    for (const inp of qa(el, '#gc-table .gc-input')) {
      const key = `${inp.dataset.grade}|${inp.dataset.age}`;
      const row = map[key] || (map[key] = { grade: inp.dataset.grade, age: Number(inp.dataset.age), _changed: false });
      const val = parseFloat(inp.value) || 0;
      row[inp.dataset.field] = val;
      if (Math.abs(val - (parseFloat(inp.dataset.orig) || 0)) > 1e-9) row._changed = true;
    }
    const updates = Object.values(map).filter(r => r._changed).map(({ _changed, ...r }) => r);
    changed = updates.length;
    const st = q(el, '#gc-status');
    if (!changed) { setStatus(st, 'No changes detected.', 'muted'); return; }
    if (!await confirm({ title: `Save ${changed} growth-curve row(s)?`, message: 'Changes apply to the next progression pass (end-season) and to the sandbox immediately.' })) return;
    try {
      const d = await api.put(adm('/growth-curves'), { updates }, { signal: ctx.signal });
      setStatus(st, `Saved. ${fmtNum(d.updated)} row(s) updated. Re-run the sandbox to see the effect.`, 'success');
      toast.success('Growth curves saved');
      await loadCurves();
    } catch (e) {
      if (e.name !== 'AbortError') setStatus(st, `Error: ${e.message}`, 'danger');
    }
  });

  // ── Buttons ──────────────────────────────────────────────────────────
  delegate(el, 'click', '[data-action]', (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'load-config') loadConfig();
    else if (a === 'load-analysis') loadAnalysis();
    else if (a === 'load-gc') loadCurves();
  }, ctx.signal);

  // Summary cards on entry (legacy loaded the config to fill them).
  try { summarize(await fetchConfig()); } catch (e) { /* unauthenticated or empty — cards stay at defaults */ }
}
