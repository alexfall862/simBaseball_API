// features/analytics/_shared.js — shared helpers for the Analytics area.
//
//   reportTabs(el, ctx, { title, sub, reports, filters })   sub-tab shell with a shared filter bar
//   childScope(signal)                                      nested AbortController for per-report/per-run cleanup
//   fx / pct / signed / heatColor / heatCell / kpiRow        formatting + heat-map cells
//   rangeField(name, label, {min,max,step,value})            slider with live value readout (readForm → number)

import { html, raw, setHtml, on, delegate, q, esc } from '../../core/html.js';
import { ALL_LEVELS } from '../../core/constants.js';
import { kpi } from '../../ui/badge.js';
import { subTabs } from '../../ui/tabs.js';
import { readForm } from '../../ui/form.js';
import { leagueYearSelect, levelSelect, teamSelect } from '../../ui/selectors.js';

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** Fixed-decimal number or '--'. */
export function fx(v, d = 3) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '--';
  return Number(v).toFixed(d);
}

/** Percentage string from an already-percent value (12.3 -> "12.3%"). */
export function pct(v, d = 1) {
  const s = fx(v, d);
  return s === '--' ? s : `${s}%`;
}

/** CSS text class for a signed value (positive good unless invert). */
export function signedClass(v, { invert = false } = {}) {
  if (v == null || Number.isNaN(Number(v)) || Number(v) === 0) return 'text-muted';
  const pos = Number(v) > 0;
  return (invert ? !pos : pos) ? 'text-success' : 'text-danger';
}

/** Coloured, sign-prefixed value as an html string (wrap in raw() or use html:true). */
export function signed(v, d = 1, { invert = false, suffix = '', plus = true } = {}) {
  if (v == null || Number.isNaN(Number(v))) return '<span class="text-muted">--</span>';
  const n = Number(v);
  return `<span class="${signedClass(n, { invert })}"><strong>${plus && n > 0 ? '+' : ''}${n.toFixed(d)}${esc(suffix)}</strong></span>`;
}

/** Diverging heat colour for a correlation in [-1, 1] on the dark theme. */
export function heatColor(r) {
  const n = Number(r);
  if (Number.isNaN(n) || n === 0) return 'transparent';
  const a = Math.min(Math.abs(n), 1) * 0.7 + 0.05;
  return n > 0 ? `rgba(16, 185, 129, ${a.toFixed(2)})` : `rgba(239, 68, 68, ${a.toFixed(2)})`;
}

/** Sequential heat colour for a value in [0, 1]. */
export function seqColor(t) {
  const n = Math.max(0, Math.min(1, Number(t) || 0));
  return n === 0 ? 'transparent' : `rgba(59, 130, 246, ${(n * 0.65 + 0.05).toFixed(2)})`;
}

/** A heat-coloured <td>. Background is data-derived, so it is the one place inline colour is allowed. */
export function heatCell(colour, text, { title = '', attrs = '' } = {}) {
  return `<td class="text-center" style="background:${colour}"${title ? ` title="${esc(title)}"` : ''}${attrs ? ` ${attrs}` : ''}>${esc(text)}</td>`;
}

/** Row of KPI stat cards. items: [{label, value, sub, kind}] */
export function kpiRow(items) {
  return `<div class="grid-auto">${items.map(kpi).join('')}</div>`;
}

/** Generic static table from column titles + pre-built row html strings (already escaped). */
export function rawTable(headCells, rowsHtml, { compact = true, id = '' } = {}) {
  return `<div class="table-container"${id ? ` id="${esc(id)}"` : ''}><table class="data-table${compact ? ' compact' : ''}"><thead><tr>${headCells.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rowsHtml.join('') || `<tr><td colspan="${headCells.length}" class="text-muted tbl-state">No data.</td></tr>`}</tbody></table></div>`;
}

/**
 * The backend returns {ok:true, error:'not_enough_data', n} for thin samples; api.js does not throw on it.
 * Returns a message when that happened, else null.
 */
export function notEnough(data, hint = 'Lower the minimum threshold.') {
  if (data && data.error === 'not_enough_data') return `Not enough data (n=${data.n ?? 0}). ${hint}`;
  return null;
}

/** Slider with a live readout. readForm() coerces it to a number via data-type. */
export function rangeField(name, label, { value = 0, min = 0, max = 100, step = 1, help = '' } = {}) {
  return `<div class="form-group"><label for="f-${esc(name)}">${esc(label)} <output class="mono" for="f-${esc(name)}">${esc(value)}</output></label>
    <input type="range" id="f-${esc(name)}" name="${esc(name)}" data-type="number" min="${esc(min)}" max="${esc(max)}" step="${esc(step)}" value="${esc(value)}" />${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
}

/** Plain select form-group with an id (for selectors.js to fill). */
export function selectGroup(id, label) {
  return `<div class="form-group" data-filter="${esc(id)}"><label for="${esc(id)}">${esc(label)}</label><select id="${esc(id)}"></select></div>`;
}

// ---------------------------------------------------------------------------
// Abort scopes
// ---------------------------------------------------------------------------

/**
 * A child AbortController chained to a parent signal. `next()` aborts the previous
 * controller and hands out a fresh signal; everything bound to the old one (charts,
 * listeners, in-flight fetches) is torn down.
 */
export function childScope(parent) {
  let ctrl = null;
  const abort = () => { if (ctrl) { ctrl.abort(); ctrl = null; } };
  if (parent) parent.addEventListener('abort', abort, { once: true });
  return {
    next() { abort(); ctrl = new AbortController(); return ctrl.signal; },
    get signal() { if (!ctrl) ctrl = new AbortController(); return ctrl.signal; },
    abort,
  };
}

// ---------------------------------------------------------------------------
// Report tab shell
// ---------------------------------------------------------------------------

/**
 * Mounts a card with a shared filter bar (league year / level / team), a subTabs strip
 * and a per-report controls row with a Load button, plus a body container below.
 *
 * reports: [{
 *   id, title, desc?, controls?: html string of form-groups,
 *   uses?: ['leagueYear','level','team'] (default leagueYear+level),
 *   levelOptional?, teamRequired?, auto? (run on select / filter change),
 *   init?(controlsEl, signal, shell), run({ body, signal, filters, controls, status, controlsEl })
 * }]
 * filters: { leagueYear: true, level: { levels, allowAll, allLabel, value }, team: { placeholder } }
 */
export async function reportTabs(el, ctx, { title, sub = '', reports, filters = {}, param = 'report' }) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>${title}</h3>${sub ? raw(`<p class="card-sub text-muted">${esc(sub)}</p>`) : ''}</div>
        <div class="form-row mb-0" id="rt-filters">
          ${filters.leagueYear ? raw(selectGroup('rt-ly', 'League year')) : ''}
          ${filters.level ? raw(selectGroup('rt-level', 'Level')) : ''}
          ${filters.team ? raw(selectGroup('rt-team', 'Team')) : ''}
        </div>
      </div>
      <div id="rt-tabs"></div>
      <p class="text-muted small mb-1" id="rt-desc" hidden></p>
      <div class="form-row mb-0" id="rt-controls" hidden></div>
      <div class="row mt-1">
        <button type="button" class="btn btn-primary btn-sm" data-action="rt-load">Load</button>
        <span class="text-muted small" id="rt-status"></span>
      </div>
    </div>
    <div id="rt-body"></div>`);

  const lySel = q(el, '#rt-ly'), lvSel = q(el, '#rt-level'), tmSel = q(el, '#rt-team');
  const body = q(el, '#rt-body'), controls = q(el, '#rt-controls'), statusEl = q(el, '#rt-status'), descEl = q(el, '#rt-desc');
  const loadBtn = q(el, '[data-action="rt-load"]');

  const lvOpts = filters.level || {};
  const lvl = lvSel ? levelSelect(lvSel, {
    levels: lvOpts.levels || ALL_LEVELS, allowAll: !!lvOpts.allowAll, allLabel: lvOpts.allLabel || 'All levels',
    value: ctx.params.level != null && ctx.params.level !== 'all' ? ctx.params.level : (lvOpts.value ?? null), signal: ctx.signal,
  }) : null;
  const ly = lySel ? await leagueYearSelect(lySel, { signal: ctx.signal, value: ctx.params.league_year_id || null }) : null;
  const tm = tmSel ? await teamSelect(tmSel, { signal: ctx.signal, value: ctx.params.team_id || null, placeholder: (filters.team && filters.team.placeholder) || 'Select team…' }) : null;

  const reportScope = childScope(ctx.signal);   // controls listeners for the active report
  const runScope = childScope(ctx.signal);      // charts/fetches of the current run
  let active = null;

  function setStatus(msg, kind = 'muted') {
    statusEl.textContent = msg || '';
    statusEl.className = `small text-${kind === 'error' ? 'danger' : kind}`;
  }

  function currentFilters() {
    return { lyid: ly ? ly.get() : null, level: lvl ? lvl.get() : null, teamId: tm ? tm.get() : null };
  }

  const shell = { run, select, setStatus, filters: currentFilters, get active() { return active; } };

  function select(id) {
    const rep = reports.find(r => r.id === id);
    if (!rep) return;
    active = rep;
    runScope.abort();
    const sig = reportScope.next();
    body.innerHTML = '';
    setStatus('');
    descEl.textContent = rep.desc || '';
    descEl.hidden = !rep.desc;
    controls.innerHTML = rep.controls || '';
    controls.hidden = !rep.controls;
    const uses = rep.uses || ['leagueYear', 'level'];
    for (const [key, sel] of [['leagueYear', lySel], ['level', lvSel], ['team', tmSel]]) {
      if (sel) sel.closest('.form-group').hidden = !uses.includes(key);
    }
    if (rep.init) rep.init(controls, sig, shell);
    ctx.setParams({ [param]: id });
    if (rep.auto) run();
  }

  async function run() {
    if (!active) return;
    const f = currentFilters();
    const uses = active.uses || ['leagueYear', 'level'];
    if (uses.includes('leagueYear') && !f.lyid) { setStatus('Select a league year.', 'warning'); return; }
    if (uses.includes('level') && f.level == null && !active.levelOptional) { setStatus('Select a level.', 'warning'); return; }
    if (uses.includes('team') && !f.teamId && active.teamRequired) { setStatus('Select a team.', 'warning'); return; }
    let c = {};
    try { c = readForm(controls); } catch (e) { setStatus(e.message, 'error'); return; }
    const signal = runScope.next();
    body.innerHTML = '';
    setStatus('Loading…');
    loadBtn.disabled = true;
    try {
      await active.run({ body, signal, filters: f, controls: c, status: setStatus, controlsEl: controls, shell });
      if (statusEl.textContent === 'Loading…') setStatus('');
      ctx.setParams({ [param]: active.id, league_year_id: f.lyid, level: f.level, team_id: f.teamId });
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      setStatus(e && e.message ? e.message : String(e), 'error');
    } finally {
      loadBtn.disabled = false;
    }
  }

  const ids = reports.map(r => r.id);
  const initial = ids.includes(ctx.params[param]) ? ctx.params[param] : ids[0];
  subTabs(q(el, '#rt-tabs'), reports.map(r => ({ id: r.id, title: r.title })), { active: initial, signal: ctx.signal, onSelect: select });

  on(loadBtn, 'click', run, ctx.signal);
  on(controls, 'keydown', (e) => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); run(); } }, ctx.signal);
  on(controls, 'input', (e) => {
    if (e.target.type === 'range') {
      const out = controls.querySelector(`output[for="${CSS.escape(e.target.id)}"]`);
      if (out) out.textContent = e.target.value;
    }
  }, ctx.signal);
  for (const sel of [lySel, lvSel, tmSel]) {
    if (sel) on(sel, 'change', () => { if (active && active.auto) run(); }, ctx.signal);
  }
  delegate(el, 'click', '[data-action="rt-rerun"]', run, ctx.signal);

  select(initial);
  return shell;
}
