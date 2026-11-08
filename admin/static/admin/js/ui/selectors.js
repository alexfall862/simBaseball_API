// ui/selectors.js — the shared dropdowns. One loader each, cached in the store.
//
//   const ly = await leagueYearSelect(selectEl, { signal, onChange(id, row) });
//   levelSelect(selectEl, { levels: SIM_LEVELS, allowAll: true, value: 9 });
//   const ts = await teamSelect(selectEl, { signal, level: 9, onChange(id, row) });

import { api, adm } from '../core/api.js';
import { store, prefs } from '../core/store.js';
import { ALL_LEVELS, levelOptionLabel } from '../core/constants.js';
import { esc, on } from '../core/html.js';

let lyPromise = null;
let teamsPromise = null;

export async function loadLeagueYears({ force = false } = {}) {
  const cached = store.get().leagueYears;
  if (cached && !force) return cached;
  if (!lyPromise || force) {
    lyPromise = api.get(adm('/analytics/league-years'), { quiet: true })
      .then(d => {
        const rows = (d.league_years || d || []).map(r => ({
          id: Number(r.id ?? r.league_year_id),
          year: Number(r.league_year ?? r.year ?? r.season),
          ...r,
        })).sort((a, b) => b.year - a.year || b.id - a.id);
        store.set({ leagueYears: rows });
        return rows;
      })
      .finally(() => { lyPromise = null; });
  }
  return lyPromise;
}

export async function loadTeams({ force = false } = {}) {
  if (!teamsPromise || force) {
    teamsPromise = api.get(adm('/analytics/teams'), { quiet: true }).then(d => d.teams || []);
  }
  return teamsPromise;
}

/** Resolve the league year to use by default: global selector, else the timestamp's. */
export function defaultLeagueYearId() {
  const s = store.get();
  if (s.leagueYearId) return Number(s.leagueYearId);
  if (s.ts && s.ts.LeagueYearID) return Number(s.ts.LeagueYearID);
  const ly = s.leagueYears;
  return ly && ly.length ? ly[0].id : null;
}

function fill(sel, options, value, placeholder) {
  const cur = value != null ? String(value) : sel.value;
  sel.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : '')
    + options.map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
  if (cur && options.some(o => String(o.value) === String(cur))) sel.value = String(cur);
  else if (!placeholder && options.length) sel.value = String(options[0].value);
}

/**
 * League-year dropdown bound to the global selection unless { global:false }.
 * Returns { get(), set(id), rows }.
 */
export async function leagueYearSelect(sel, { signal, onChange, value = null, global = true, placeholder = null, labelFn = null } = {}) {
  sel.disabled = true;
  sel.innerHTML = '<option value="">Loading…</option>';
  let rows = [];
  try {
    rows = await loadLeagueYears();
  } catch (e) {
    sel.innerHTML = '<option value="">Failed to load years</option>';
    sel.disabled = false;
    return { get: () => null, set() {}, rows: [] };
  }
  const opts = rows.map(r => ({ value: r.id, label: labelFn ? labelFn(r) : `${r.year} (id ${r.id})` }));
  const initial = value != null ? value : (global ? defaultLeagueYearId() : null);
  fill(sel, opts, initial, placeholder);
  sel.disabled = false;

  const emit = () => {
    const id = sel.value ? Number(sel.value) : null;
    if (global && id) store.set({ leagueYearId: id });
    if (onChange) onChange(id, rows.find(r => r.id === id) || null);
  };
  on(sel, 'change', emit, signal);
  if (global) {
    store.watch('leagueYearId', (id) => {
      if (id && String(id) !== sel.value && opts.some(o => String(o.value) === String(id))) {
        sel.value = String(id);
        if (onChange) onChange(Number(id), rows.find(r => r.id === Number(id)) || null);
      }
    }, signal, { immediate: false });
  }
  return {
    rows,
    get: () => (sel.value ? Number(sel.value) : null),
    set: (id) => { sel.value = String(id); emit(); },
  };
}

export function levelSelect(sel, { levels = ALL_LEVELS, allowAll = false, allLabel = 'All levels', value = null, signal, onChange, remember = null } = {}) {
  const opts = levels.map(l => ({ value: l, label: levelOptionLabel(l) }));
  const initial = value != null ? value : (remember ? prefs.get(`level:${remember}`, null) : null);
  fill(sel, opts, initial, allowAll ? allLabel : null);
  if (onChange || remember) {
    on(sel, 'change', () => {
      const v = sel.value === '' ? null : Number(sel.value);
      if (remember) prefs.set(`level:${remember}`, v);
      if (onChange) onChange(v);
    }, signal);
  }
  return {
    get: () => (sel.value === '' ? null : Number(sel.value)),
    set: (v) => { sel.value = v == null ? '' : String(v); },
  };
}

export async function teamSelect(sel, { signal, level = null, value = null, onChange, placeholder = 'Select team…' } = {}) {
  sel.disabled = true;
  sel.innerHTML = '<option value="">Loading…</option>';
  let teams = [];
  try { teams = await loadTeams(); } catch (_) { teams = []; }
  const api_ = {
    teams,
    setLevel(lv) {
      const rows = lv == null ? teams : teams.filter(t => Number(t.team_level) === Number(lv));
      fill(sel, rows.map(t => ({ value: t.id, label: lv == null ? `${t.team_abbrev} (L${t.team_level})` : t.team_abbrev })), value, placeholder);
    },
    get: () => (sel.value ? Number(sel.value) : null),
    set: (id) => { sel.value = String(id); },
  };
  api_.setLevel(level);
  sel.disabled = false;
  if (onChange) on(sel, 'change', () => onChange(api_.get(), teams.find(t => t.id === api_.get()) || null), signal);
  return api_;
}

/** Generic select filler for ad-hoc option lists. */
export function fillSelect(sel, options, { value = null, placeholder = null } = {}) {
  fill(sel, options.map(o => (typeof o === 'object' ? o : { value: o, label: String(o) })), value, placeholder);
}
