// core/html.js — escape-by-default tagged template.
//
//   import { html, raw, esc } from '../core/html.js';
//   el.innerHTML = html`<td>${row.name}</td>${raw(badge('ok', 'success'))}`;
//
// Interpolated values are HTML-escaped unless wrapped in raw(). Arrays are
// joined with '' (each element escaped/raw independently). null/undefined
// render as ''.

class Raw {
  constructor(s) { this.s = String(s == null ? '' : s); }
  toString() { return this.s; }
}

export function raw(s) {
  return s instanceof Raw ? s : new Raw(s);
}

export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function render(v) {
  if (v == null || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(render).join('');
  return esc(v);
}

export function html(strings, ...vals) {
  let out = '';
  for (let i = 0; i < strings.length; i++) {
    out += strings[i];
    if (i < vals.length) out += render(vals[i]);
  }
  return new Raw(out);
}

/** Build a DOM element from an html`` result (or string). */
export function el(markup) {
  const t = document.createElement('template');
  t.innerHTML = String(markup).trim();
  return t.content.firstElementChild;
}

/** Set innerHTML from an html`` result (or string). */
export function setHtml(node, markup) {
  if (!node) return;
  node.innerHTML = String(markup);
  return node;
}

/** querySelector shorthand scoped to a root. */
export function q(root, sel) {
  return root.querySelector(sel);
}
export function qa(root, sel) {
  return Array.from(root.querySelectorAll(sel));
}

/** Attach a listener that is removed when `signal` aborts. */
export function on(node, type, handler, signal, opts) {
  if (!node) return;
  node.addEventListener(type, handler, { ...(opts || {}), signal });
}

/** Delegated listener: on(root, 'click', '[data-action]', (e, target) => ...) */
export function delegate(root, type, selector, handler, signal) {
  on(root, type, (e) => {
    const t = e.target.closest(selector);
    if (t && root.contains(t)) handler(e, t);
  }, signal);
}
