// ui/toast.js — non-blocking notifications. Replaces alert().

import { esc } from '../core/html.js';

let root = null;

function ensureRoot() {
  if (root) return root;
  root = document.getElementById('toast-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'toast-root';
    document.body.appendChild(root);
  }
  return root;
}

function show(kind, message, { timeout = 5000, title = null, sticky = false } = {}) {
  const r = ensureRoot();
  const t = document.createElement('div');
  t.className = `toast toast-${kind}`;
  t.setAttribute('role', 'status');
  t.innerHTML = `
    ${title ? `<div class="toast-title">${esc(title)}</div>` : ''}
    <div class="toast-msg">${esc(message)}</div>
    <button class="toast-close" aria-label="Dismiss">&times;</button>`;
  const remove = () => {
    t.classList.add('toast-out');
    setTimeout(() => t.remove(), 200);
  };
  t.querySelector('.toast-close').addEventListener('click', remove);
  r.appendChild(t);
  requestAnimationFrame(() => t.classList.add('toast-in'));
  if (!sticky) setTimeout(remove, kind === 'error' ? Math.max(timeout, 8000) : timeout);
  return { close: remove, el: t };
}

export const toast = {
  success: (m, o) => show('success', m, o),
  error: (m, o) => show('error', m, o),
  info: (m, o) => show('info', m, o),
  warn: (m, o) => show('warning', m, o),
};
