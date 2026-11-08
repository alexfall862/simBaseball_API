// features/system/_shared.js — helpers shared by the System area tabs.

import { api, adm, getAdminPassword } from '../../core/api.js';
import { raw, setHtml } from '../../core/html.js';
import { store } from '../../core/store.js';
import { alertBox } from '../../ui/badge.js';

/** Current season number (league year, e.g. 2026) from the live timestamp, or null. */
export function seasonYear() {
  const ts = store.get().ts;
  return ts && ts.Season ? Number(ts.Season) : null;
}

/**
 * Render a write-mode banner into `node` and keep it in sync with the store.
 * Also refreshes the flag from /admin/me once. Returns () => boolean (current flag).
 */
export function writeModeBanner(node, signal, { what = 'Saving changes' } = {}) {
  store.watch('auth', (a) => {
    const on_ = !!(a && a.writeMode);
    setHtml(node, on_ ? '' : raw(
      `<div class="alert alert-warning"><strong>Write mode is OFF.</strong> ${what} requires write mode (the server answers 403 <code>write_mode_disabled</code>). Enable it in <a href="#/system/settings">System → Settings</a>.</div>`));
  }, signal);
  api.get(adm('/me'), { quiet: true, signal })
    .then(me => store.set({ auth: { ...store.get().auth, writeMode: !!me.write_mode } }))
    .catch(() => {});
  return () => !!store.get().auth.writeMode;
}

/** Banner shown when no X-Admin-Password value is stored for this tab. */
export function adminPasswordBanner(node) {
  setHtml(node, getAdminPassword() ? '' : raw(
    `<div class="alert alert-warning"><strong>No admin password stored.</strong> These endpoints authenticate with the <code>X-Admin-Password</code> header. It is saved at login; if it is missing, set it in <a href="#/system/settings">System → Settings</a>.</div>`));
}

/** Flatten a nested {module: {key: bool}} map into [['module.key', bool], ...]. */
export function flattenFlags(obj, prefix = '') {
  const out = [];
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...flattenFlags(v, key));
    else out.push([key, v]);
  }
  return out;
}

export { alertBox };
