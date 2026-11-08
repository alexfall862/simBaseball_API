// core/format.js — formatting helpers (pure functions).

export { esc } from './html.js';

export function fmtNum(n, digits = 0) {
  if (n == null || n === '' || Number.isNaN(Number(n))) return '--';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMoney(n, { compact = false } = {}) {
  if (n == null || Number.isNaN(Number(n))) return '--';
  const v = Number(n);
  if (compact) {
    const abs = Math.abs(v);
    if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  }
  return v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

export function fmtPct(n, digits = 1) {
  if (n == null || Number.isNaN(Number(n))) return '--';
  return `${(Number(n) * 100).toFixed(digits)}%`;
}

export function fmtRate(n, digits = 3) {
  if (n == null || Number.isNaN(Number(n))) return '--';
  const s = Number(n).toFixed(digits);
  return s.startsWith('0.') ? s.slice(1) : s;
}

export function toDate(v) {
  if (v == null || v === '') return null;
  if (v instanceof Date) return v;
  if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v);
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(v, { time = true } = {}) {
  const d = toDate(v);
  if (!d) return '--';
  const opts = time
    ? { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { year: 'numeric', month: 'short', day: 'numeric' };
  return d.toLocaleString(undefined, opts);
}

export function relTime(v) {
  const d = toDate(v);
  if (!d) return '--';
  const diff = (d.getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  const units = [[60, 's'], [3600, 'm'], [86400, 'h'], [604800, 'd'], [Infinity, 'w']];
  let n, u;
  if (abs < 60) { n = Math.round(abs); u = 's'; }
  else if (abs < 3600) { n = Math.round(abs / 60); u = 'm'; }
  else if (abs < 86400) { n = Math.round(abs / 3600); u = 'h'; }
  else if (abs < 604800) { n = Math.round(abs / 86400); u = 'd'; }
  else { n = Math.round(abs / 604800); u = 'w'; }
  void units;
  return diff < 0 ? `${n}${u} ago` : `in ${n}${u}`;
}

export function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '--';
  const s = Math.round(Number(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return `${m}m ${r}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function json(v) {
  try { return JSON.stringify(v, null, 2); } catch (_) { return String(v); }
}

export function titleCase(s) {
  return String(s || '').replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}
