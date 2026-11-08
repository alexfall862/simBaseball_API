// features/data/sql.js — SQL console (port of legacy #section-sql).
//
//   POST /admin/run_sql {sql, mode:'read'|'write', limit, dry_run}
//   GET  /admin/presets            server presets {presets:[{key,label,mode}]}
//   GET  /admin/run_preset?key=    run a server preset
//
// Read mode allows SELECT/SHOW/DESCRIBE/EXPLAIN. Write mode additionally needs the session
// write-mode switch (System → Settings); the server returns 403 write_disabled otherwise.
// Rows are capped server-side at ADMIN_MAX_ROWS (default 500).

import { api, adm } from '../../core/api.js';
import { html, raw, esc, setHtml, on, delegate, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { json } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { field, formRow, readForm } from '../../ui/form.js';
import { confirm, showResult } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { alertBox } from '../../ui/badge.js';
import { columnsFromRows } from './_shared.js';

const MAX_DISPLAY_ROWS = 500;

/** Client-side presets carried over from the legacy console (app.js SQL_PRESETS). */
const SQL_PRESETS = Object.freeze([
  { name: 'All Players (limit 100)', query: 'SELECT * FROM simbbPlayers LIMIT 100' },
  { name: 'All Teams', query: 'SELECT * FROM simbbTeams' },
  { name: 'All Organizations', query: 'SELECT * FROM simbbOrganizations' },
  { name: 'Game Schedule', query: 'SELECT * FROM simbbSchedule LIMIT 100' },
  { name: 'Level Configs', query: 'SELECT * FROM simbbLevelConfigs' },
  { name: 'Catch Rates', query: 'SELECT * FROM simbbCatchRates' },
  { name: 'Player Stats (Batting)', query: 'SELECT * FROM simbbPlayerStatsBatting LIMIT 100' },
  { name: 'Player Stats (Pitching)', query: 'SELECT * FROM simbbPlayerStatsPitching LIMIT 100' },
  { name: 'Background Tasks', query: 'SELECT id, status, task_type, progress, total, created_at FROM background_tasks ORDER BY created_at DESC LIMIT 50' },
]);

function writeBanner(on_) {
  return on_
    ? alertBox('danger', 'Write statements (INSERT/UPDATE/DELETE/…) will execute against the live database when dry run is off.', { title: 'Write mode ON.' })
    : `<div class="alert alert-warning"><strong>Write mode is OFF.</strong> Only read statements will run; write mode requests are rejected with 403. Enable it in <a href="#/system/settings">System → Settings</a>.</div>`;
}

export async function mount(el, ctx) {
  setHtml(el, html`
    <div id="sql-banner"></div>
    <div class="card" id="sql-form">
      <div class="card-head">
        <div><h3>SQL console</h3><p class="card-sub text-muted"><code>POST /admin/run_sql</code>. SELECTs without a LIMIT get one appended; the server caps rows at <code>ADMIN_MAX_ROWS</code> (500).</p></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="sql-preset">Preset</label><select id="sql-preset"><option value="">Loading…</option></select></div>
        <button class="btn btn-secondary" data-action="run-preset">Run preset</button>
        <button class="btn btn-ghost" data-action="insert-preset" title="Copy the preset SQL into the editor without running it">Insert into editor</button>
      </div>
      ${raw(formRow([
        field.select('mode', 'Mode', [{ value: 'read', label: 'Read-only' }, { value: 'write', label: 'Write (needs write mode)' }], { value: 'read' }),
        field.number('limit', 'Row limit', { value: 100, min: 1, max: 5000, width: '120px' }),
        field.checkbox('dry_run', 'Dry run (writes → EXPLAIN only)', { checked: true }),
      ]))}
      ${raw(field.textarea('sql', 'Query', { rows: 8, placeholder: 'SELECT * FROM simbbPlayers LIMIT 10;', mono: true }))}
      <div class="row">
        <button class="btn btn-primary" data-action="run">Run query</button>
        <span class="text-muted small"><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> runs the query</span>
      </div>
    </div>
    <div class="card">
      <div class="card-head">
        <h3>Result</h3>
        <div class="row"><span id="sql-meta" class="text-muted small"></span><button class="btn btn-sm btn-ghost" data-action="raw" hidden>Raw JSON</button></div>
      </div>
      <div id="sql-result"><p class="text-muted">No query executed yet.</p></div>
    </div>`);

  const presetSel = q(el, '#sql-preset');
  const resultEl = q(el, '#sql-result');
  const meta = q(el, '#sql-meta');
  const rawBtn = q(el, '[data-action="raw"]');
  let serverPresets = [];
  let lastData = null;

  // Write-mode banner follows the store; refresh the flag from /admin/me on mount.
  store.watch('auth', (a) => setHtml(q(el, '#sql-banner'), raw(writeBanner(a && a.writeMode))), ctx.signal);
  api.get(adm('/me'), { quiet: true, signal: ctx.signal })
    .then(me => store.set({ auth: { ...store.get().auth, writeMode: !!me.write_mode } }))
    .catch(() => {});

  async function loadPresets() {
    try {
      const d = await api.get(adm('/presets'), { quiet: true, signal: ctx.signal });
      serverPresets = d.presets || [];
    } catch (e) { if (e.name === 'AbortError') return; serverPresets = []; }
    const client = SQL_PRESETS.map((p, i) => `<option value="c:${i}">${esc(p.name)}</option>`).join('');
    const server = serverPresets.map(p => `<option value="s:${esc(p.key)}">${esc(p.label)} (${esc(p.mode)})</option>`).join('');
    presetSel.innerHTML = `<option value="">-- Select preset --</option>`
      + `<optgroup label="Console presets">${client}</optgroup>`
      + (server ? `<optgroup label="Server presets (/admin/run_preset)">${server}</optgroup>` : '');
  }

  function renderResult(data) {
    lastData = data;
    rawBtn.hidden = false;
    if (data && Array.isArray(data.rows)) {
      const rows = data.rows;
      const shown = rows.length > MAX_DISPLAY_ROWS ? rows.slice(0, MAX_DISPLAY_ROWS) : rows;
      const total = data.count != null ? data.count : rows.length;
      meta.textContent = `${total} row${total === 1 ? '' : 's'} returned${shown.length < rows.length ? ` · showing first ${MAX_DISPLAY_ROWS}` : ''}`;
      if (!rows.length) { setHtml(resultEl, '<p class="text-muted">Query returned no rows.</p>'); return; }
      dataTable(resultEl, { columns: columnsFromRows(rows), rows: shown, pageSize: 50, compact: true });
      return;
    }
    if (data && Array.isArray(data.explain)) {
      meta.textContent = 'Dry run — EXPLAIN plan (nothing was written)';
      if (!data.explain.length) { setHtml(resultEl, '<p class="text-muted">EXPLAIN returned no rows.</p>'); return; }
      dataTable(resultEl, { columns: columnsFromRows(data.explain), rows: data.explain, compact: true });
      return;
    }
    if (data && data.rowcount != null) {
      meta.textContent = '';
      setHtml(resultEl, raw(alertBox('success', `Statement executed · ${data.rowcount} row(s) affected.`)));
      return;
    }
    meta.textContent = '';
    setHtml(resultEl, html`<pre class="result-box">${json(data)}</pre>`);
  }

  function showError(e) {
    meta.textContent = '';
    rawBtn.hidden = !(e && e.body);
    lastData = e && e.body ? e.body : null;
    setHtml(resultEl, html`<div class="alert alert-danger mb-0"><strong>Error:</strong> ${e.message}</div>`);
  }

  async function run() {
    const f = readForm(q(el, '#sql-form'));
    const sql = String(f.sql || '').trim();
    if (!sql) { toast.warn('Enter a query'); return; }
    const mode = f.mode === 'write' ? 'write' : 'read';
    const limit = f.limit || 100;
    const dryRun = !!f.dry_run;
    if (mode === 'write') {
      if (!store.get().auth.writeMode) { toast.warn('Write mode is off. Enable it in System → Settings first.'); return; }
      if (!dryRun && !await confirm({
        title: 'Execute write statement?', danger: true, typeToConfirm: 'WRITE', confirmLabel: 'Execute',
        message: 'Dry run is off: this statement will modify the live database.', detail: sql.slice(0, 2000),
      })) return;
    }
    meta.textContent = 'Executing…';
    setHtml(resultEl, '<p class="text-muted">Executing…</p>');
    try {
      renderResult(await api.post(adm('/run_sql'), { sql, mode, limit, dry_run: dryRun }, { signal: ctx.signal, quiet: true }));
    } catch (e) { if (e.name !== 'AbortError') showError(e); }
  }

  function selectedPreset() {
    const v = presetSel.value;
    if (!v) { toast.warn('Select a preset'); return null; }
    const [kind, key] = [v.slice(0, 1), v.slice(2)];
    if (kind === 'c') return { client: SQL_PRESETS[Number(key)] };
    return { server: serverPresets.find(p => p.key === key) };
  }

  async function runPreset(insertOnly) {
    const p = selectedPreset();
    if (!p) return;
    if (p.client) {
      q(el, '[name="sql"]').value = p.client.query;
      q(el, '[name="mode"]').value = 'read';
      if (!insertOnly) await run();
      return;
    }
    if (!p.server) return;
    if (insertOnly) { toast.info('Server presets keep their SQL on the server; run them directly.'); return; }
    meta.textContent = `Running preset ${p.server.key}…`;
    setHtml(resultEl, '<p class="text-muted">Executing…</p>');
    try {
      renderResult(await api.get(adm('/run_preset'), { params: { key: p.server.key }, signal: ctx.signal, quiet: true }));
    } catch (e) { if (e.name !== 'AbortError') showError(e); }
  }

  on(q(el, '[name="sql"]'), 'keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(); } }, ctx.signal);
  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'run') await run();
      else if (a === 'run-preset') await runPreset(false);
      else if (a === 'insert-preset') await runPreset(true);
      else if (a === 'raw' && lastData) showResult('SQL result', lastData);
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await loadPresets();
}
