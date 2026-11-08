// core/constants.js — single source of truth for shared lookups.

export const V1 = '/api/v1';
export const ADMIN = '/admin';

export const LEVEL_NAMES = Object.freeze({
  9: 'MLB',
  8: 'AAA',
  7: 'AA',
  6: 'High-A',
  5: 'A',
  4: 'Scraps',
  3: 'College',
  2: 'High School',
  1: 'International',
});

/** Levels that have a schedule and are simulated, highest first. */
export const SIM_LEVELS = Object.freeze([9, 8, 7, 6, 5, 3]);

/** Every pro/college level incl. Scraps, highest first. */
export const ALL_LEVELS = Object.freeze([9, 8, 7, 6, 5, 4, 3]);

export const SUBWEEKS = Object.freeze(['a', 'b', 'c', 'd']);

export const PHASES = Object.freeze({
  REGULAR_SEASON: { label: 'Regular Season', badge: 'success' },
  PLAYOFFS:       { label: 'Playoffs',       badge: 'running' },
  OFFSEASON:      { label: 'Offseason',      badge: 'warning' },
  FREE_AGENCY:    { label: 'Free Agency',    badge: 'info' },
  DRAFT:          { label: 'Draft',          badge: 'running' },
  RECRUITING:     { label: 'Recruiting',     badge: 'pending' },
});

export function phaseLabel(phase) {
  return (PHASES[phase] && PHASES[phase].label) || phase || 'Unknown';
}

export function phaseBadgeKind(phase) {
  return (PHASES[phase] && PHASES[phase].badge) || 'secondary';
}

export const POSITIONS = Object.freeze({
  1: 'P', 2: 'C', 3: '1B', 4: '2B', 5: '3B', 6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH',
  SP: 'SP', RP: 'RP', C: 'C', '1B': '1B', '2B': '2B', '3B': '3B', SS: 'SS', LF: 'LF', CF: 'CF', RF: 'RF', DH: 'DH',
  // gameplanning position codes (defense / lineup payloads)
  c: 'C', fb: '1B', sb: '2B', tb: '3B', ss: 'SS', lf: 'LF', cf: 'CF', rf: 'RF', dh: 'DH', p: 'P', sp: 'SP', rp: 'RP',
});

export function positionLabel(code) {
  if (code == null) return '';
  return POSITIONS[code] ?? POSITIONS[String(code).toLowerCase()] ?? String(code).toUpperCase();
}

export function levelName(level) {
  return LEVEL_NAMES[level] || `Level ${level}`;
}

export function levelOptionLabel(level) {
  return `${level} - ${levelName(level)}`;
}

/** Task statuses as the backend reports them (lowercase canonical). */
export const TASK_STATUS = Object.freeze({
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETE: 'complete',
  FAILED: 'failed',
});

export function normStatus(s) {
  return String(s || '').toLowerCase();
}
