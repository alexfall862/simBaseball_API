// main.js — boot: auth gate, shell chrome, router, live state.

import { api, v1, adm, setAdminPassword } from './core/api.js';
import { bus } from './core/bus.js';
import { store, prefs } from './core/store.js';
import { registerAreas, getAreas, startRouter, navigate, buildHash, remount } from './core/router.js';
import { startWs } from './core/ws.js';
import { esc, on } from './core/html.js';
import { phaseBadge, subweekPips, subweekFlagsFromTs } from './ui/badge.js';
import { toast } from './ui/toast.js';
import { leagueYearSelect } from './ui/selectors.js';
import { AREAS } from './features/index.js';

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- auth
async function checkAuth() {
  try {
    const me = await api.get(adm('/me'), { quiet: true });
    store.set({ auth: { admin: me.admin === true, writeMode: !!me.write_mode, checked: true } });
    return me.admin === true;
  } catch (_) {
    store.set({ auth: { admin: false, writeMode: false, checked: true } });
    return false;
  }
}

function showGate(show) {
  const g = $('login-gate');
  g.hidden = !show;
  if (show) setTimeout(() => $('login-password').focus(), 30);
}

function wireLogin() {
  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pw = $('login-password').value;
    $('login-err').textContent = '';
    try {
      await api.post(adm('/login'), { password: pw }, { quiet: true });
      setAdminPassword(pw);
      $('login-password').value = '';
      showGate(false);
      await afterLogin();
    } catch (err) {
      $('login-err').textContent = err.status === 401 ? 'Wrong password.' : (err.message || 'Login failed');
    }
  });
  $('btn-logout').addEventListener('click', async (e) => {
    e.preventDefault();
    try { await api.post(adm('/logout'), {}, { quiet: true }); } catch (_) { /* ignore */ }
    setAdminPassword('');
    store.set({ auth: { admin: false, writeMode: false, checked: true }, ts: null, summary: null });
    showGate(true);
  });
  bus.on('api:unauthorized', () => {
    if (!store.get().auth.admin) return;
    store.set({ auth: { ...store.get().auth, admin: false } });
    showGate(true);
  });
}

// ---------------------------------------------------------------- chrome
function renderSidebar(activeArea) {
  const nav = $('sidebar-nav');
  nav.innerHTML = getAreas().map(a => `
    <a class="nav-item${a.id === activeArea ? ' active' : ''}" href="${buildHash(a.id, a.tabs[0].id)}" data-area="${esc(a.id)}">
      <span class="nav-icon">${a.icon || '•'}</span><span class="nav-label">${esc(a.title)}</span>
      <span class="nav-count" data-count="${esc(a.id)}" hidden></span>
    </a>`).join('');
}

function renderTabs(route) {
  const bar = $('tabsbar');
  const area = route.areaDef;
  if (!area || area.tabs.length <= 1) { bar.innerHTML = ''; return; }
  bar.innerHTML = area.tabs.map(t => `<a href="${buildHash(area.id, t.id)}" class="${t.id === route.tab ? 'active' : ''}">${esc(t.title)}</a>`).join('');
  const active = bar.querySelector('a.active');
  if (active) active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function onRoute(route) {
  renderSidebar(route.area);
  renderTabs(route);
  const tabTitle = route.tabDef && route.areaDef.tabs.length > 1 ? route.tabDef.title : '';
  $('page-title').innerHTML = `${esc(route.areaDef.title)}${tabTitle ? `<small>/ ${esc(tabTitle)}</small>` : ''}`;
  document.title = `${tabTitle || route.areaDef.title} · SimBaseball Admin`;
  $('sidebar').classList.remove('open');
}

function renderTopbarStatus(ts) {
  const el = $('topbar-status');
  if (!ts) { el.innerHTML = '<span class="text-muted small">No timestamp</span>'; return; }
  const flags = subweekFlagsFromTs(ts);
  el.innerHTML = `
    ${phaseBadge(ts.Phase)}
    <span class="small"><strong>${esc(ts.Season ?? '--')}</strong> <span class="text-muted">·</span> Wk <strong>${esc(ts.Week ?? '--')}</strong><span class="text-muted">/${esc(ts.TotalWeeks ?? '--')}</span></span>
    ${ts.Phase === 'REGULAR_SEASON' || ts.Phase === 'PLAYOFFS' ? subweekPips(flags) : ''}
    ${ts.RunGames ? '<span class="badge badge-running" title="RunGames flag is set">Simulating</span>' : ''}`;
}

function renderSchedPill(s) {
  const pill = $('sched-pill');
  if (!s) { pill.className = 'sched-pill off'; pill.title = 'Scheduler status unknown'; return; }
  const on_ = !!s.enabled;
  pill.className = `sched-pill ${on_ ? 'on' : 'off'}`;
  pill.querySelector('.label').textContent = on_ ? (s.leader ? 'Scheduler on' : 'Scheduler on · no leader') : 'Scheduler off';
  pill.title = `${on_ ? 'Enabled' : 'Disabled'}${s.leader ? ` · leader ${s.leader}` : ''}${s.next_run ? ` · next ${s.next_run.name} ${s.next_run.in}` : ''}`;
}

function wireChrome() {
  $('menu-toggle').addEventListener('click', () => $('sidebar').classList.toggle('open'));
  const collapsed = prefs.get('sidebar_collapsed', false);
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  $('sidebar-collapse').textContent = collapsed ? '›' : '‹';
  $('sidebar-collapse').addEventListener('click', () => {
    const c = !document.body.classList.contains('sidebar-collapsed');
    document.body.classList.toggle('sidebar-collapsed', c);
    $('sidebar-collapse').textContent = c ? '›' : '‹';
    prefs.set('sidebar_collapsed', c);
  });
  $('sched-pill').addEventListener('click', () => navigate('jobs', 'scheduled'));
  $('btn-palette').addEventListener('click', openPalette);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  });
  store.watch('ts', renderTopbarStatus);
  store.watch('summary', (s) => {
    renderSchedPill(s && s.scheduler);
    const alerts = (s && s.alerts) || [];
    const c = $('sidebar-nav').querySelector('[data-count="home"]');
    if (c) { c.hidden = !alerts.length; c.textContent = alerts.length; }
  });
  store.watch('wsConnected', (ok) => { $('ws-dot').className = `status-dot ${ok ? 'online' : 'warn'}`; });
  store.watch('auth', (a) => { $('auth-dot').className = `status-dot ${a.admin ? 'online' : ''}`; });
  bus.on('api:error', (err) => {
    if (err.status === 401) return;
    toast.error(err.message || 'Request failed', { title: err.status ? `HTTP ${err.status}` : 'Error' });
  });
}

// ---------------------------------------------------------------- palette
function openPalette() {
  if (document.querySelector('.palette')) return;
  const items = [];
  for (const a of getAreas()) for (const t of a.tabs) items.push({ label: `${a.title} › ${t.title}`, hash: buildHash(a.id, t.id) });
  const wrap = document.createElement('div');
  wrap.className = 'palette';
  wrap.innerHTML = `<div class="palette-box"><input type="text" placeholder="Jump to… (type to filter)" /><div class="palette-list"></div></div>`;
  document.body.appendChild(wrap);
  const input = wrap.querySelector('input');
  const list = wrap.querySelector('.palette-list');
  let filtered = items, idx = 0;
  const render = () => {
    list.innerHTML = filtered.slice(0, 40).map((it, i) => `<div class="palette-item${i === idx ? ' active' : ''}" data-i="${i}"><span>${esc(it.label)}</span><span class="text-muted">${esc(it.hash)}</span></div>`).join('')
      || '<div class="palette-item text-muted">No matches</div>';
  };
  const close = () => wrap.remove();
  const go = (i) => { const it = filtered[i]; if (it) { close(); window.location.hash = it.hash; } };
  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    filtered = q ? items.filter(it => it.label.toLowerCase().includes(q)) : items;
    idx = 0; render();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowDown') { idx = Math.min(idx + 1, filtered.length - 1); render(); }
    else if (e.key === 'ArrowUp') { idx = Math.max(idx - 1, 0); render(); }
    else if (e.key === 'Enter') go(idx);
  });
  list.addEventListener('click', (e) => { const it = e.target.closest('.palette-item'); if (it && it.dataset.i) go(Number(it.dataset.i)); });
  wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });
  render();
  input.focus();
}

// ---------------------------------------------------------------- live state
export async function refreshTimestamp() {
  try {
    const ts = await api.get(v1('/games/timestamp'), { quiet: true });
    store.set({ ts });
    return ts;
  } catch (e) {
    return null;
  }
}

export async function refreshSummary() {
  try {
    const s = await api.get(adm('/summary'), { quiet: true });
    store.set({ summary: s });
    if (s.timestamp) store.set({ ts: s.timestamp });
    return s;
  } catch (e) {
    return null;
  }
}

let pollTimer = null;
function startPolling() {
  if (pollTimer) return;
  const tick = () => {
    if (document.hidden) return;
    refreshSummary();
  };
  pollTimer = setInterval(tick, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
}

bus.on('ws:job_run', () => { refreshSummary(); bus.emit('jobs:changed'); });

// ---------------------------------------------------------------- boot
async function afterLogin() {
  await refreshSummary();
  if (!store.get().ts) await refreshTimestamp();
  leagueYearSelect($('global-ly'), { global: true }).catch(() => {});
  startWs({ onTimestamp: refreshTimestamp });
  startPolling();
  await remount();
}

async function boot() {
  registerAreas(AREAS);
  wireLogin();
  wireChrome();
  const ok = await checkAuth();
  await startRouter($('view'), { onChange: onRoute });
  if (!ok) { showGate(true); return; }
  showGate(false);
  await afterLogin();
}

window.AdminApp = { store, navigate, refreshTimestamp, refreshSummary, bus };
boot().catch(e => { console.error('boot failed', e); toast.error(`Boot failed: ${e.message}`); });
