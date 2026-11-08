// ui/modal.js — modal dialogs. Replaces confirm()/prompt().
//
//   const ok = await confirm({ title: 'Wipe season?', message: '...', danger: true, typeToConfirm: 'WIPE' });
//   const name = await promptText({ title: 'Job name', value: 'Daily subweek' });
//   const h = openModal({ title, body: html`...` or Node, actions: [{label, cls, onClick(h)}] });

import { esc } from '../core/html.js';

let stack = [];

function root() {
  let r = document.getElementById('modal-root');
  if (!r) {
    r = document.createElement('div');
    r.id = 'modal-root';
    document.body.appendChild(r);
  }
  return r;
}

export function openModal({ title = '', body = '', actions = [], size = 'md', onClose = null, closeOnBackdrop = true } = {}) {
  const r = root();
  const wrap = document.createElement('div');
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `
    <div class="modal modal-${size}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <h3 class="modal-title">${esc(title)}</h3>
        <button class="modal-x" aria-label="Close">&times;</button>
      </div>
      <div class="modal-body"></div>
      <div class="modal-foot"></div>
    </div>`;
  const bodyEl = wrap.querySelector('.modal-body');
  if (body instanceof Node) bodyEl.appendChild(body);
  else bodyEl.innerHTML = String(body);

  const footEl = wrap.querySelector('.modal-foot');
  const handle = {
    el: wrap,
    body: bodyEl,
    foot: footEl,
    close(result) {
      if (!wrap.isConnected) return;
      wrap.classList.remove('modal-in');
      setTimeout(() => wrap.remove(), 150);
      stack = stack.filter(h => h !== handle);
      document.body.classList.toggle('modal-open', stack.length > 0);
      if (onClose) onClose(result);
    },
    setActions(list) {
      footEl.innerHTML = '';
      for (const a of list) {
        const b = document.createElement('button');
        b.className = `btn ${a.cls || 'btn-secondary'}`;
        b.textContent = a.label;
        if (a.id) b.id = a.id;
        if (a.disabled) b.disabled = true;
        b.addEventListener('click', async () => {
          if (a.onClick) {
            b.disabled = true;
            try { await a.onClick(handle, b); } finally { if (wrap.isConnected) b.disabled = false; }
          }
          if (a.close !== false && !a.onClick) handle.close(a.value);
        });
        footEl.appendChild(b);
      }
      footEl.style.display = list.length ? '' : 'none';
    },
  };
  handle.setActions(actions);

  wrap.querySelector('.modal-x').addEventListener('click', () => handle.close(undefined));
  if (closeOnBackdrop) {
    wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) handle.close(undefined); });
  }
  const onKey = (e) => {
    if (e.key === 'Escape' && stack[stack.length - 1] === handle) handle.close(undefined);
  };
  document.addEventListener('keydown', onKey);
  const origClose = handle.close.bind(handle);
  handle.close = (res) => { document.removeEventListener('keydown', onKey); origClose(res); };

  r.appendChild(wrap);
  stack.push(handle);
  document.body.classList.add('modal-open');
  requestAnimationFrame(() => wrap.classList.add('modal-in'));
  const first = wrap.querySelector('input, select, textarea, button.btn');
  if (first) setTimeout(() => first.focus(), 50);
  return handle;
}

export function confirm({ title = 'Are you sure?', message = '', detail = '', danger = false,
  confirmLabel = 'Confirm', cancelLabel = 'Cancel', typeToConfirm = null } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(!!v); } };
    const body = `
      ${message ? `<p class="modal-msg">${esc(message)}</p>` : ''}
      ${detail ? `<pre class="result-box modal-detail">${esc(detail)}</pre>` : ''}
      ${typeToConfirm ? `
        <label class="form-group" style="margin-top:12px">
          <span>Type <code>${esc(typeToConfirm)}</code> to confirm</span>
          <input type="text" id="confirm-type" autocomplete="off" />
        </label>` : ''}`;
    const h = openModal({
      title, body, size: 'sm',
      onClose: (v) => done(v === true),
      actions: [
        { label: cancelLabel, cls: 'btn-secondary', onClick: (hh) => hh.close(false) },
        { label: confirmLabel, cls: danger ? 'btn-danger' : 'btn-primary', id: 'confirm-ok',
          disabled: !!typeToConfirm, onClick: (hh) => hh.close(true) },
      ],
    });
    if (typeToConfirm) {
      const inp = h.body.querySelector('#confirm-type');
      const ok = h.foot.querySelector('#confirm-ok');
      inp.addEventListener('input', () => { ok.disabled = inp.value.trim() !== typeToConfirm; });
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !ok.disabled) h.close(true); });
    } else {
      const ok = h.foot.querySelector('#confirm-ok');
      setTimeout(() => ok && ok.focus(), 60);
    }
  });
}

export function promptText({ title = 'Enter a value', label = '', value = '', placeholder = '', type = 'text',
  okLabel = 'OK', password = false } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    const h = openModal({
      title, size: 'sm',
      body: `<label class="form-group">${label ? `<span>${esc(label)}</span>` : ''}
        <input type="${password ? 'password' : esc(type)}" id="prompt-input" value="${esc(value)}" placeholder="${esc(placeholder)}" /></label>`,
      onClose: (v) => done(v === undefined ? null : v),
      actions: [
        { label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close(null) },
        { label: okLabel, cls: 'btn-primary', onClick: (hh) => hh.close(hh.body.querySelector('#prompt-input').value) },
      ],
    });
    const inp = h.body.querySelector('#prompt-input');
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') h.close(inp.value); });
  });
}

/** Show a JSON/text result in a modal (for big payloads). */
export function showResult(title, data) {
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  return openModal({
    title, size: 'lg',
    body: `<pre class="result-box" style="max-height:60vh">${esc(text)}</pre>`,
    actions: [{ label: 'Close', cls: 'btn-secondary' }],
  });
}
