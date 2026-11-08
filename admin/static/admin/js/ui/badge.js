// ui/badge.js — small inline html builders (return strings; wrap with raw() in html``).

import { esc } from '../core/html.js';
import { phaseLabel, phaseBadgeKind, normStatus } from '../core/constants.js';

export function badge(text, kind = 'secondary', { title = '' } = {}) {
  return `<span class="badge badge-${esc(kind)}"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}</span>`;
}

export function boolBadge(v, { yes = 'Yes', no = 'No' } = {}) {
  return badge(v ? yes : no, v ? 'success' : 'pending');
}

export function phaseBadge(phase) {
  return badge(phaseLabel(phase), phaseBadgeKind(phase));
}

const STATUS_KIND = {
  pending: 'pending', queued: 'pending',
  running: 'running', in_progress: 'running', active: 'running',
  complete: 'success', completed: 'success', succeeded: 'success', success: 'success', done: 'success', ok: 'success',
  failed: 'danger', error: 'danger', not_built: 'danger',
  skipped: 'secondary', cancelled: 'secondary', canceled: 'secondary', disabled: 'secondary', unknown: 'secondary',
  manual: 'warning', warning: 'warning', paused: 'warning',
};

export function statusBadge(status) {
  const s = normStatus(status);
  return badge(s || 'unknown', STATUS_KIND[s] || 'secondary');
}

export function kpi({ label, value, sub = '', kind = '', id = '' }) {
  return `<div class="stat-card${kind ? ` stat-${esc(kind)}` : ''}"${id ? ` id="${esc(id)}"` : ''}>
    <div class="stat-label">${esc(label)}</div>
    <div class="stat-value">${esc(value ?? '--')}</div>
    ${sub !== null ? `<div class="stat-sub">${esc(sub)}</div>` : ''}
  </div>`;
}

/** A–D subweek pips. flags = {a:true,b:false,...} */
export function subweekPips(flags, { size = '' } = {}) {
  return `<span class="pips${size ? ` pips-${esc(size)}` : ''}">${['a', 'b', 'c', 'd'].map(k =>
    `<span class="pip ${flags && flags[k] ? 'pip-on' : ''}" title="Subweek ${k.toUpperCase()}: ${flags && flags[k] ? 'complete' : 'pending'}">${k.toUpperCase()}</span>`
  ).join('')}</span>`;
}

export function subweekFlagsFromTs(ts) {
  return ts ? { a: !!ts.GamesARan, b: !!ts.GamesBRan, c: !!ts.GamesCRan, d: !!ts.GamesDRan } : { a: false, b: false, c: false, d: false };
}

export function spinner(size = '') {
  return `<span class="spinner${size ? ` spinner-${esc(size)}` : ''}"></span>`;
}

export function emptyState(text, { icon = '' } = {}) {
  return `<div class="empty-state">${icon ? `<div class="empty-icon">${esc(icon)}</div>` : ''}<div class="text-muted">${esc(text)}</div></div>`;
}

export function alertBox(kind, message, { title = '' } = {}) {
  return `<div class="alert alert-${esc(kind)}">${title ? `<strong>${esc(title)}</strong> ` : ''}${esc(message)}</div>`;
}
