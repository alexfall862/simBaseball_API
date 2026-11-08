// core/api.js — the one HTTP client.
//
//   const ts = await api.get(v1('/games/timestamp'));
//   await api.post(v1('/games/advance-week'));
//   await api.post(adm('/run-playoff-revenue'), { league_year: 2026 }, { admin: true });
//
// Throws ApiError on !r.ok, on {ok:false}, or on {error: ...} without ok:true.
// Emits 'api:error' on the bus unless { quiet: true } so main.js can toast.

import { V1, ADMIN } from './constants.js';
import { bus } from './bus.js';

export class ApiError extends Error {
  constructor(message, { status = 0, code = null, body = null, url = '' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.body = body;
    this.url = url;
  }
}

export const v1 = (p) => `${V1}${p.startsWith('/') ? p : '/' + p}`;
export const adm = (p) => `${ADMIN}${p.startsWith('/') ? p : '/' + p}`;

const PW_KEY = 'simbb_admin_pw';

export function getAdminPassword() {
  try { return sessionStorage.getItem(PW_KEY) || ''; } catch (_) { return ''; }
}
export function setAdminPassword(pw) {
  try {
    if (pw) sessionStorage.setItem(PW_KEY, pw);
    else sessionStorage.removeItem(PW_KEY);
  } catch (_) { /* private mode */ }
}

function buildUrl(path, params) {
  if (!params) return path;
  const u = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    u.searchParams.set(k, String(v));
  }
  return u.pathname + u.search;
}

function extractMessage(body, fallback) {
  if (!body) return fallback;
  if (typeof body === 'string') return body.slice(0, 300) || fallback;
  return body.message || body.detail || body.error || body.reason || fallback;
}

async function request(method, path, { body, params, admin = false, signal, quiet = false, raw = false, headers = {} } = {}) {
  const url = buildUrl(path, params);
  const init = { method, credentials: 'include', signal, headers: { Accept: 'application/json', ...headers } };
  if (body !== undefined && body !== null) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.headers['Content-Type'] = 'application/json';
      init.body = typeof body === 'string' ? body : JSON.stringify(body);
    }
  }
  if (admin) {
    const pw = getAdminPassword();
    if (pw) init.headers['X-Admin-Password'] = pw;
  }

  let r;
  try {
    r = await fetch(url, init);
  } catch (e) {
    if (e && e.name === 'AbortError') throw e;
    const err = new ApiError(`Network error: ${e.message}`, { url });
    if (!quiet) bus.emit('api:error', err);
    throw err;
  }

  if (raw) return r;

  const text = await r.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (_) { data = text; }
  }

  const bodyErr = data && typeof data === 'object' && !Array.isArray(data)
    && (data.ok === false || (data.error && data.ok !== true));

  if (!r.ok || bodyErr) {
    const msg = extractMessage(data, `${method} ${url} failed (${r.status})`);
    const err = new ApiError(msg, {
      status: r.status,
      code: data && typeof data === 'object' ? (data.error || data.code || null) : null,
      body: data,
      url,
    });
    if (r.status === 401) bus.emit('api:unauthorized', err);
    if (!quiet) bus.emit('api:error', err);
    throw err;
  }
  return data;
}

export const api = {
  get: (path, opts = {}) => request('GET', path, opts),
  post: (path, body, opts = {}) => request('POST', path, { ...opts, body: body === undefined ? {} : body }),
  put: (path, body, opts = {}) => request('PUT', path, { ...opts, body }),
  patch: (path, body, opts = {}) => request('PATCH', path, { ...opts, body }),
  del: (path, opts = {}) => request('DELETE', path, opts),
  /** Follow a server-described action {method, url, body, header}. */
  action: (a, opts = {}) => request((a.method || 'POST').toUpperCase(), a.url, {
    ...opts, body: a.body || {}, admin: !!a.header || opts.admin,
  }),
};
