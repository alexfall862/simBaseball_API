// core/router.js — hash router with lazy-loaded feature areas.
//
// URL shape:  #/<area>/<tab>?k=v&k2=v2
// Each area:  { id, title, icon, tabs: [{ id, title, load: () => import('...') }] }
// Each tab module exports:  mount(el, ctx) and optionally unmount()
// ctx = { signal, params, area, tab, navigate, setParams }

import { store } from './store.js';

const areas = new Map();
let order = [];
let current = { controller: null, module: null, areaId: null, tabId: null };
let viewEl = null;
let onRouteChange = null;

export function registerAreas(list) {
  order = list.map(a => a.id);
  for (const a of list) areas.set(a.id, a);
}

export function getAreas() {
  return order.map(id => areas.get(id));
}

export function parseHash(hash = window.location.hash) {
  const h = hash.replace(/^#\/?/, '');
  const [pathPart, queryPart = ''] = h.split('?');
  const [area = '', tab = ''] = pathPart.split('/').filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(queryPart).entries());
  return { area, tab, params };
}

export function buildHash(area, tab, params) {
  let h = `#/${area}`;
  if (tab) h += `/${tab}`;
  const qs = params ? new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  ).toString() : '';
  if (qs) h += `?${qs}`;
  return h;
}

export function navigate(area, tab, params) {
  window.location.hash = buildHash(area, tab, params);
}

/** Update query params of the current route without remounting. */
export function setParams(params, { replace = true } = {}) {
  const r = store.get().route || parseHash();
  const merged = { ...(r.params || {}), ...params };
  const h = buildHash(r.area, r.tab, merged);
  if (replace) history.replaceState(null, '', h);
  else window.location.hash = h;
  store.set({ route: { ...r, params: merged } });
}

async function resolve() {
  const parsed = parseHash();
  const area = areas.get(parsed.area) || areas.get(order[0]);
  if (!area) return;
  const tab = area.tabs.find(t => t.id === parsed.tab) || area.tabs[0];
  if (!tab) return;

  // Normalise URL if we fell back to defaults
  const want = buildHash(area.id, tab.id, parsed.params);
  if (window.location.hash !== want) {
    history.replaceState(null, '', want);
  }

  const sameTab = current.areaId === area.id && current.tabId === tab.id && current.module;
  const route = { area: area.id, tab: tab.id, params: parsed.params, areaDef: area, tabDef: tab };
  store.set({ route });
  if (onRouteChange) onRouteChange(route);

  if (sameTab) {
    // Only params changed; let the tab react through store.watch('route') if it wants.
    return;
  }

  // Tear down previous
  if (current.controller) current.controller.abort();
  if (current.module && typeof current.module.unmount === 'function') {
    try { current.module.unmount(); } catch (e) { console.error('unmount failed', e); }
  }
  current = { controller: new AbortController(), module: null, areaId: area.id, tabId: tab.id };
  const { signal } = current.controller;

  viewEl.innerHTML = '<div class="view-loading"><div class="spinner"></div></div>';
  let mod;
  try {
    mod = await tab.load();
  } catch (e) {
    console.error(`failed to load ${area.id}/${tab.id}`, e);
    viewEl.innerHTML = `<div class="card"><h3>Failed to load view</h3><pre class="result-box">${String(e && e.stack || e)}</pre></div>`;
    return;
  }
  if (signal.aborted) return;
  current.module = mod;

  const el = document.createElement('div');
  el.className = `view view-${area.id} view-${area.id}-${tab.id}`;
  viewEl.innerHTML = '';
  viewEl.appendChild(el);

  const ctx = {
    signal,
    params: parsed.params,
    area: area.id,
    tab: tab.id,
    navigate,
    setParams,
    el,
  };
  try {
    await mod.mount(el, ctx);
  } catch (e) {
    if (e && e.name === 'AbortError') return;
    console.error(`mount failed for ${area.id}/${tab.id}`, e);
    el.insertAdjacentHTML('afterbegin',
      `<div class="alert alert-danger"><strong>View error:</strong> ${String(e && e.message || e)}</div>`);
  }
}

export function startRouter(mountEl, { onChange } = {}) {
  viewEl = mountEl;
  onRouteChange = onChange || null;
  window.addEventListener('hashchange', () => { resolve(); });
  if (!window.location.hash) {
    history.replaceState(null, '', buildHash(order[0], areas.get(order[0]).tabs[0].id));
  }
  return resolve();
}

/** Force a remount of the current tab (e.g. after login). */
export function remount() {
  current.areaId = null;
  current.tabId = null;
  return resolve();
}
