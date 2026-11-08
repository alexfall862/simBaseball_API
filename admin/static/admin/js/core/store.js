// core/store.js — minimal observable store.
//
//   store.get().ts                 current enhanced timestamp
//   store.set({ ts })              shallow merge + notify
//   store.subscribe(fn, signal)    fn(state, changedKeys)
//   store.watch('ts', fn, signal)  fn(value) when that key changes (and once immediately)

export function createStore(initial = {}) {
  let state = { ...initial };
  const subs = new Set();

  function notify(keys) {
    for (const fn of Array.from(subs)) {
      try { fn(state, keys); } catch (e) { console.error('store subscriber failed', e); }
    }
  }

  return {
    get: () => state,
    set(patch) {
      const keys = [];
      for (const [k, v] of Object.entries(patch)) {
        if (state[k] !== v) { keys.push(k); }
      }
      if (!keys.length) return;
      state = { ...state, ...patch };
      notify(keys);
    },
    subscribe(fn, signal) {
      subs.add(fn);
      const off = () => subs.delete(fn);
      if (signal) signal.addEventListener('abort', off, { once: true });
      return off;
    },
    watch(key, fn, signal, { immediate = true } = {}) {
      const off = this.subscribe((s, keys) => { if (keys.includes(key)) fn(s[key], s); }, signal);
      if (immediate) { try { fn(state[key], state); } catch (e) { console.error(e); } }
      return off;
    },
  };
}

export const store = createStore({
  auth: { admin: false, writeMode: false, checked: false },
  ts: null,               // enhanced timestamp from /api/v1/games/timestamp (PascalCase)
  summary: null,          // /admin/summary payload
  leagueYears: null,      // [{id, league_year}] once loaded
  leagueYearId: null,     // global selector value (string/number)
  scheduler: null,        // /admin/scheduler payload
  wsConnected: false,
  route: null,            // { area, tab, params }
});

/** Persisted preference helpers (safe in private mode). */
export const prefs = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(`simbb_admin:${key}`);
      return v == null ? fallback : JSON.parse(v);
    } catch (_) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`simbb_admin:${key}`, JSON.stringify(value)); } catch (_) { /* ignore */ }
  },
};
