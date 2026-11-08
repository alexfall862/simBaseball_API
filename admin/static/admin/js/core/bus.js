// core/bus.js — tiny event bus. Used for api errors, ws events, toasts.

const listeners = new Map();

export const bus = {
  on(type, fn, signal) {
    if (!listeners.has(type)) listeners.set(type, new Set());
    listeners.get(type).add(fn);
    const off = () => listeners.get(type)?.delete(fn);
    if (signal) signal.addEventListener('abort', off, { once: true });
    return off;
  },
  emit(type, payload) {
    const set = listeners.get(type);
    if (!set) return;
    for (const fn of Array.from(set)) {
      try { fn(payload); } catch (e) { console.error(`bus handler for ${type} failed`, e); }
    }
  },
};
