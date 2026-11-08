// core/ws.js — reconnecting WebSocket client. Server pushes {type:'timestamp', ...row}
// on week/phase changes, {type:'draft_*'} draft events, and {type:'job_run', ...}
// from the job scheduler. We refetch the enhanced timestamp rather than merge the
// raw row, and re-emit everything on the bus.

import { bus } from './bus.js';
import { store } from './store.js';

let sock = null;
let backoff = 1000;
let refetchTimer = null;
let refetchFn = null;

function scheduleRefetch() {
  if (!refetchFn) return;
  clearTimeout(refetchTimer);
  refetchTimer = setTimeout(() => { refetchFn().catch(() => {}); }, 300);
}

function connect() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${window.location.host}/ws`;
  try {
    sock = new WebSocket(url);
  } catch (e) {
    retry();
    return;
  }
  sock.onopen = () => {
    backoff = 1000;
    store.set({ wsConnected: true });
    bus.emit('ws:open');
  };
  sock.onmessage = (ev) => {
    if (!ev.data) return; // keepalive ping
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_) { return; }
    if (!msg || typeof msg !== 'object') return;
    bus.emit('ws:message', msg);
    if (msg.type) bus.emit(`ws:${msg.type}`, msg);
    if (msg.type === 'timestamp' || !msg.type) scheduleRefetch();
  };
  sock.onclose = () => {
    store.set({ wsConnected: false });
    retry();
  };
  sock.onerror = () => { try { sock.close(); } catch (_) { /* noop */ } };
}

function retry() {
  setTimeout(connect, backoff);
  backoff = Math.min(backoff * 2, 30000);
}

export function startWs({ onTimestamp } = {}) {
  refetchFn = onTimestamp || null;
  if (sock) return;
  connect();
}
