// features/market/_shared.js — helpers shared by the Market tabs
// (org dropdown cache, league-year/game-week context, salary inputs, badges).

import { api, v1 } from '../../core/api.js';
import { esc } from '../../core/html.js';
import { store } from '../../core/store.js';
import { LEVEL_NAMES } from '../../core/constants.js';
import { fmtMoney } from '../../core/format.js';
import { badge, alertBox } from '../../ui/badge.js';
import { defaultLeagueYearId } from '../../ui/selectors.js';
import { refreshTimestamp } from '../../main.js';

export { badge };

/** Pro levels that take roster moves (legacy dropdowns), highest first. */
export const PRO_LEVELS = Object.freeze([9, 8, 7, 6, 5, 4]);
export const PRO_LEVEL_OPTIONS = PRO_LEVELS.map(l => ({ value: l, label: `${LEVEL_NAMES[l]} (${l})` }));

export function levelName(l) {
  if (l == null || l === '') return '--';
  return LEVEL_NAMES[l] || `L${l}`;
}

export const money = (v) => (v == null || v === '' ? '--' : fmtMoney(v));

// ---------------------------------------------------------------- orgs
// Legacy cached `txOrgList` from /api/v1/org_report/ (the /organizations
// endpoint only returns abbrev strings, which is useless for id-based
// dropdowns). One loader, shared by every Market tab.
let orgsPromise = null;

export async function loadOrgs({ force = false } = {}) {
  if (!orgsPromise || force) {
    orgsPromise = api.get(v1('/org_report/'), { quiet: true })
      .then(d => (Array.isArray(d) ? d : [])
        .map(o => ({ id: Number(o.id), org_abbrev: o.org_abbrev || `#${o.id}`, league: o.league || 'mlb' }))
        .sort((a, b) => a.org_abbrev.localeCompare(b.org_abbrev)))
      .catch(e => { orgsPromise = null; throw e; });
  }
  return orgsPromise;
}

export function orgOptions(orgs, { placeholder = 'Select org…' } = {}) {
  const mlb = orgs.filter(o => o.league === 'mlb');
  const other = orgs.filter(o => o.league !== 'mlb');
  const opt = o => `<option value="${o.id}">${esc(o.org_abbrev)}</option>`;
  return (placeholder != null ? `<option value="">${esc(placeholder)}</option>` : '')
    + (mlb.length ? `<optgroup label="MLB organizations">${mlb.map(opt).join('')}</optgroup>` : '')
    + (other.length ? `<optgroup label="Other organizations">${other.map(opt).join('')}</optgroup>` : '');
}

/** Fill a <select> with the cached org list. Returns { orgs, get(), set(id), name(id) }. */
export async function orgSelect(sel, { signal, onChange, placeholder = 'Select org…', value = null } = {}) {
  sel.disabled = true;
  sel.innerHTML = '<option value="">Loading…</option>';
  let orgs = [];
  try {
    orgs = await loadOrgs();
  } catch (_) {
    sel.innerHTML = '<option value="">Failed to load orgs</option>';
    sel.disabled = false;
    return { orgs: [], get: () => null, set() {}, name: (id) => (id == null ? '--' : `Org #${id}`) };
  }
  sel.innerHTML = orgOptions(orgs, { placeholder });
  if (value != null) sel.value = String(value);
  sel.disabled = false;
  const get = () => (sel.value ? Number(sel.value) : null);
  if (onChange) sel.addEventListener('change', () => onChange(get(), orgs.find(o => o.id === get()) || null), { signal });
  return { orgs, get, set: (id) => { sel.value = id == null ? '' : String(id); }, name: (id) => orgName(orgs, id) };
}

export function orgName(orgs, id) {
  const o = (orgs || []).find(x => x.id === Number(id));
  return o ? o.org_abbrev : (id == null ? '--' : `Org #${id}`);
}

// ---------------------------------------------------------------- context
/**
 * Legacy fetchTxContext(): league_year_id = timestamp.SeasonID, game_week_id =
 * timestamp.WeekID (falls back to Week). The timestamp lives in the store; it is
 * fetched once if the shell has not loaded it yet.
 */
export async function txContext() {
  let ts = store.get().ts;
  if (!ts) ts = await refreshTimestamp();
  ts = ts || {};
  const league_year_id = Number(ts.SeasonID || ts.LeagueYearID || defaultLeagueYearId() || 1);
  const game_week_id = Number(ts.WeekID || ts.Week || 1);
  return { league_year_id, game_week_id, week: Number(ts.Week || 0), season: ts.Season, phase: ts.Phase };
}

// ---------------------------------------------------------------- forms
/** Year-N salary inputs named sal_1..sal_N (read back with readSalaries). */
export function salaryFields(years, existing = [], { step = 1000 } = {}) {
  let out = '';
  for (let i = 1; i <= years; i++) {
    const v = existing && existing[i - 1] != null ? existing[i - 1] : '';
    out += `<div class="form-group"><label for="f-sal_${i}">Year ${i} salary ($)</label>`
      + `<input type="number" id="f-sal_${i}" name="sal_${i}" data-type="number" min="0" step="${Number(step)}" value="${esc(v)}" /></div>`;
  }
  return out;
}

export function readSalaries(root, years) {
  const out = [];
  for (let i = 1; i <= years; i++) {
    const inp = root.querySelector(`[name="sal_${i}"]`);
    out.push(inp && inp.value !== '' ? Number(inp.value) : 0);
  }
  return out;
}

export function parseIdList(text) {
  return String(text || '').split(/[,; ]+/).map(s => parseInt(s.trim(), 10)).filter(n => !Number.isNaN(n));
}

// ---------------------------------------------------------------- badges
const PHASE_KIND = { open: 'success', listening: 'warning', finalize: 'danger', completed: 'info', expired: 'secondary' };
export function auctionPhaseBadge(phase) { return badge(phase || '--', PHASE_KIND[phase] || 'secondary'); }

const WINDOW_KIND = { active: 'success', complete: 'info', completed: 'info', pending: 'warning' };
export function windowStatusBadge(status) { return badge(status || 'pending', WINDOW_KIND[status] || 'secondary'); }

export function stars(n) {
  n = Math.max(0, Math.min(5, Number(n) || 0));
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}

/** Inline status line (replaces legacy .status-msg). Empty message clears it. */
export function setStatus(el, message, kind = 'info') {
  if (!el) return;
  el.innerHTML = message ? alertBox(kind, message) : '';
}

export function playerName(p) {
  return p.player_name || [p.firstName, p.lastName].filter(Boolean).join(' ') || (p.player_id != null ? `#${p.player_id}` : '--');
}
