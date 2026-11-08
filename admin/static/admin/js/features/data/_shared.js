// features/data/_shared.js — helpers shared by the Data area tabs.

import { kvTable } from '../../ui/table.js';
import { store } from '../../core/store.js';

/** Stringify a cell value for display (objects become JSON). */
export function cellText(v) {
  if (v == null) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** kvTable markup for an arbitrary object; nested values are JSON-encoded. */
export function objectKv(obj) {
  const pairs = Object.entries(obj || {}).map(([k, v]) => [k, cellText(v)]);
  return pairs.length ? kvTable(pairs) : '<p class="text-muted">No data.</p>';
}

/** dataTable columns derived from the union of keys over a row list (first `max` keys). */
export function columnsFromRows(rows, { max = 80 } = {}) {
  const keys = [];
  for (const r of rows || []) {
    for (const k of Object.keys(r || {})) if (!keys.includes(k)) keys.push(k);
    if (keys.length >= max) break;
  }
  return keys.slice(0, max).map(k => ({
    key: k, title: k, sortable: true, nowrap: true,
    render: r => cellText(r[k]),
    sortValue: r => r[k],
  }));
}

/** Current season number (league year, e.g. 2026) from the live timestamp, or null. */
export function seasonYear() {
  const ts = store.get().ts;
  return ts && ts.Season ? Number(ts.Season) : null;
}

/** Unwrap the v1 list endpoints, which return either a bare array or {<key>: [...]}. */
export function unwrapList(data, key) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data[key])) return data[key];
  return [];
}

/** The v1 detail endpoints return [] or [row]; normalise to the row or null. */
export function firstRow(data) {
  if (Array.isArray(data)) return data.length ? data[0] : null;
  return data && typeof data === 'object' ? data : null;
}
