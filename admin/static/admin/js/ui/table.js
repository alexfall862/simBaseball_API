// ui/table.js — the one table renderer. Escapes by default.
//
//   const t = dataTable(el, {
//     columns: [
//       { key: 'name', title: 'Name', sortable: true },
//       { key: 'war', title: 'WAR', align: 'right', render: r => fmtNum(r.war, 1), sortValue: r => r.war },
//       { key: 'status', title: 'Status', html: true, render: r => badge(r.status) },
//       { key: '_act', title: '', html: true, render: r => `<button class="btn btn-sm" data-action="edit" data-id="${r.id}">Edit</button>` },
//     ],
//     rows, rowKey: 'id', pageSize: 50, emptyText: 'No rows', sortKey: 'war', sortDir: 'desc',
//     onRowClick(row, e) {}, rowClass(row) {}
//   });
//   t.setRows(newRows); t.setLoading(); t.setError(msg);
//
// Row action buttons use data-action; handle them with delegate(el, 'click', '[data-action]', ...).

import { esc } from '../core/html.js';

function cmp(a, b) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  const na = Number(a), nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb) && a !== '' && b !== '') return na - nb;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

export function dataTable(el, opts) {
  const state = {
    columns: opts.columns || [],
    rows: opts.rows || [],
    sortKey: opts.sortKey || null,
    sortDir: opts.sortDir || 'asc',
    page: 1,
    pageSize: opts.pageSize || 0,
    loading: false,
    error: null,
    emptyText: opts.emptyText || 'No data.',
    rowKey: opts.rowKey || null,
    compact: !!opts.compact,
    stickyHeader: opts.stickyHeader !== false,
    footer: opts.footer || null,          // (rows) => html string for a <tfoot>
    caption: opts.caption || null,
  };

  el.classList.add('table-container');

  function sorted() {
    if (!state.sortKey) return state.rows;
    const col = state.columns.find(c => c.key === state.sortKey);
    const getter = col && col.sortValue ? col.sortValue : (r => r[state.sortKey]);
    const dir = state.sortDir === 'desc' ? -1 : 1;
    return [...state.rows].sort((a, b) => dir * cmp(getter(a), getter(b)));
  }

  function paged(rows) {
    if (!state.pageSize) return rows;
    const start = (state.page - 1) * state.pageSize;
    return rows.slice(start, start + state.pageSize);
  }

  function cell(col, row, i) {
    let v;
    if (col.render) v = col.render(row, i);
    else v = row[col.key];
    if (v == null) v = col.empty != null ? col.empty : '';
    const content = col.html ? String(v) : esc(v);
    const cls = [col.align ? `text-${col.align}` : '', col.cellClass || '', col.nowrap ? 'nowrap' : ''].filter(Boolean).join(' ');
    const title = col.title_attr ? ` title="${esc(col.title_attr(row))}"` : '';
    return `<td${cls ? ` class="${cls}"` : ''}${title}>${content}</td>`;
  }

  function render() {
    const cols = state.columns.filter(c => !c.hidden);
    const all = sorted();
    const rows = paged(all);
    const totalPages = state.pageSize ? Math.max(1, Math.ceil(all.length / state.pageSize)) : 1;
    if (state.page > totalPages) state.page = totalPages;

    const head = cols.map(c => {
      const sortable = c.sortable !== false && (c.sortable || c.key);
      const active = state.sortKey === c.key;
      const arrow = active ? (state.sortDir === 'asc' ? ' ▲' : ' ▼') : '';
      const style = c.width ? ` style="width:${esc(c.width)}"` : '';
      const cls = [c.align ? `text-${c.align}` : '', sortable && c.sortable ? 'sortable' : '', active ? 'sorted' : ''].filter(Boolean).join(' ');
      return `<th${style}${cls ? ` class="${cls}"` : ''} data-sort="${c.sortable ? esc(c.key) : ''}">${esc(c.title ?? c.key)}${arrow}</th>`;
    }).join('');

    let body;
    if (state.loading) {
      body = `<tr><td colspan="${cols.length}" class="text-muted tbl-state"><span class="spinner spinner-sm"></span> Loading…</td></tr>`;
    } else if (state.error) {
      body = `<tr><td colspan="${cols.length}" class="text-danger tbl-state">${esc(state.error)}</td></tr>`;
    } else if (!rows.length) {
      body = `<tr><td colspan="${cols.length}" class="text-muted tbl-state">${esc(state.emptyText)}</td></tr>`;
    } else {
      body = rows.map((r, i) => {
        const key = state.rowKey ? ` data-key="${esc(r[state.rowKey])}"` : '';
        const rc = opts.rowClass ? opts.rowClass(r) : '';
        return `<tr${key}${rc ? ` class="${esc(rc)}"` : ''}>${cols.map(c => cell(c, r, i)).join('')}</tr>`;
      }).join('');
    }

    const foot = state.footer && !state.loading && !state.error && all.length ? `<tfoot>${state.footer(all)}</tfoot>` : '';
    const pager = state.pageSize && all.length > state.pageSize ? `
      <div class="tbl-pager">
        <button class="btn btn-sm btn-secondary" data-page="prev" ${state.page <= 1 ? 'disabled' : ''}>&lsaquo; Prev</button>
        <span class="text-muted">Page ${state.page} / ${totalPages} · ${all.length} rows</span>
        <button class="btn btn-sm btn-secondary" data-page="next" ${state.page >= totalPages ? 'disabled' : ''}>Next &rsaquo;</button>
      </div>` : (all.length && state.pageSize ? `<div class="tbl-pager"><span class="text-muted">${all.length} rows</span></div>` : '');

    el.innerHTML = `
      <table class="data-table${state.compact ? ' compact' : ''}${state.stickyHeader ? ' sticky' : ''}">
        ${state.caption ? `<caption>${esc(state.caption)}</caption>` : ''}
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
        ${foot}
      </table>${pager}`;
  }

  el.addEventListener('click', (e) => {
    const th = e.target.closest('th[data-sort]');
    if (th && th.dataset.sort) {
      const k = th.dataset.sort;
      if (state.sortKey === k) state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      else { state.sortKey = k; state.sortDir = 'asc'; }
      render();
      return;
    }
    const pg = e.target.closest('[data-page]');
    if (pg) {
      state.page += pg.dataset.page === 'next' ? 1 : -1;
      render();
      return;
    }
    if (opts.onRowClick && !e.target.closest('button, a, input, select, [data-action]')) {
      const tr = e.target.closest('tbody tr[data-key], tbody tr');
      if (tr && tr.parentElement.tagName === 'TBODY') {
        const idx = Array.from(tr.parentElement.children).indexOf(tr);
        const row = paged(sorted())[idx];
        if (row) opts.onRowClick(row, e, tr);
      }
    }
  });

  render();

  return {
    el,
    get rows() { return state.rows; },
    setRows(rows) { state.rows = rows || []; state.loading = false; state.error = null; render(); },
    setLoading() { state.loading = true; state.error = null; render(); },
    setError(msg) { state.loading = false; state.error = msg || 'Error'; render(); },
    setColumns(cols) { state.columns = cols; render(); },
    setSort(key, dir = 'asc') { state.sortKey = key; state.sortDir = dir; render(); },
    setPage(p) { state.page = p; render(); },
    refresh: render,
  };
}

/** Quick static table string (escaped). rows: array of arrays or objects w/ columns. */
export function simpleTable(columns, rows, { className = '' } = {}) {
  const head = columns.map(c => `<th>${esc(typeof c === 'string' ? c : c.title)}</th>`).join('');
  const body = rows.length ? rows.map(r => `<tr>${columns.map((c, i) => {
    const v = Array.isArray(r) ? r[i] : (typeof c === 'string' ? r[c] : (c.render ? c.render(r) : r[c.key]));
    const isHtml = typeof c === 'object' && c.html;
    return `<td>${isHtml ? String(v ?? '') : esc(v ?? '')}</td>`;
  }).join('')}</tr>`).join('')
    : `<tr><td colspan="${columns.length}" class="text-muted">No data.</td></tr>`;
  return `<div class="table-container"><table class="data-table ${esc(className)}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** Key/value rows using the legacy .kv-table markup. */
export function kvTable(pairs, { html = false } = {}) {
  return `<div class="kv-table">${pairs.map(([k, v]) => `
    <div class="kv-row"><div class="kv-key">${esc(k)}</div><div class="kv-val">${html ? String(v ?? '') : esc(v ?? '--')}</div></div>`).join('')}</div>`;
}
