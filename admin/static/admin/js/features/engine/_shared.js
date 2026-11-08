// features/engine/_shared.js — constants + small helpers shared by the Player Engine tabs.
// Constants only at module level; no mutable state.

import { esc } from '../../core/html.js';
import { badge } from '../../ui/badge.js';
import { levelName } from '../../core/constants.js';

/** Grade colour palette (consistent across the sandbox + diagnostics charts). */
export const GRADE_COLORS = Object.freeze({
  'A+': '#0d6a3a', 'A': '#16a34a', 'A-': '#4ade80',
  'B+': '#0e7490', 'B': '#06b6d4', 'B-': '#67e8f9',
  'C+': '#ca8a04', 'C': '#facc15', 'C-': '#fde68a',
  'D+': '#ea580c', 'D': '#f97316', 'D-': '#fdba74',
  'F': '#dc2626', 'N': '#9ca3af',
});

export function gradeColor(grade) {
  return GRADE_COLORS[grade] || '#6b7280';
}

/** The 13 weighted rating types: 2 generic overalls + 11 position-specifics. */
export const RATING_TYPE_ORDER = Object.freeze([
  'pitcher_overall', 'position_overall',
  'sp_rating', 'rp_rating',
  'c_rating', 'fb_rating', 'sb_rating', 'tb_rating', 'ss_rating',
  'lf_rating', 'cf_rating', 'rf_rating', 'dh_rating',
]);

/** Position-specific rating types only (calibration result rows). */
export const POSITION_RATING_ORDER = Object.freeze([
  'c_rating', 'fb_rating', 'sb_rating', 'tb_rating', 'ss_rating',
  'lf_rating', 'cf_rating', 'rf_rating', 'dh_rating', 'sp_rating', 'rp_rating',
]);

export const RATING_LABELS = Object.freeze({
  pitcher_overall: 'P (default)', position_overall: 'Pos (default)',
  c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
  ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
  dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
  pitch1_ovr: 'P1 OVR', pitch2_ovr: 'P2 OVR', pitch3_ovr: 'P3 OVR',
  pitch4_ovr: 'P4 OVR', pitch5_ovr: 'P5 OVR',
});

export function ratingLabel(rt) {
  return RATING_LABELS[rt] || rt;
}

/** "power_base" -> "power", "pitch_pacc_base" -> "pitch pacc". */
export function attrLabel(key) {
  return String(key || '').replace(/_base$/, '').replace(/_/g, ' ');
}

/** Fixed-decimal formatter that tolerates null. */
export function fx(v, digits = 2, empty = '--') {
  if (v == null || v === '' || Number.isNaN(Number(v))) return empty;
  return Number(v).toFixed(digits);
}

/** Legacy level colour groups: amateur/info, low minors/warning, high minors/pending, MLB/success. */
export function levelBadgeKind(level) {
  const n = Number(level);
  if (!n) return 'secondary';
  if (n <= 3) return 'info';
  if (n <= 6) return 'warning';
  if (n <= 8) return 'pending';
  return 'success';
}

export function levelBadge(level) {
  return badge(levelName(level), levelBadgeKind(level));
}

export function ptypeBadge(ptype) {
  return badge(ptype || '?', ptype === 'Pitcher' ? 'info' : 'success');
}

/** Legacy attribute category colouring in the analysis table. */
export function attrCategoryClass(attrKey) {
  const k = String(attrKey || '');
  if (k.endsWith('_rating')) return 'text-warning';
  if (k.startsWith('pitch_')) return 'text-success';
  if (k.includes('_ovr')) return 'text-warning';
  return '';
}

/** Badge kind for a 20-80 value. */
export function scaleKind(v) {
  if (v == null) return 'secondary';
  if (v >= 60) return 'success';
  if (v >= 45) return 'warning';
  return 'danger';
}

/** Compact numeric input for editable tables. Attributes are escaped. */
export function cellInput({ value = '', step = '0.1', min, max, cls = '', data = {} } = {}) {
  const d = Object.entries(data).map(([k, v]) => ` data-${esc(k)}="${esc(v)}"`).join('');
  return `<input type="number" step="${esc(step)}"${min != null ? ` min="${esc(min)}"` : ''}${max != null ? ` max="${esc(max)}"` : ''} class="cell-input ${esc(cls)}" value="${esc(value)}" style="width:80px"${d} />`;
}

/** Show/hide a block. */
export function show(node, visible = true) {
  if (node) node.style.display = visible ? '' : 'none';
}

/** A one-line status message helper for a text container. */
export function setStatus(node, text, kind = 'muted') {
  if (!node) return;
  node.className = `small text-${kind}`;
  node.textContent = text || '';
}
