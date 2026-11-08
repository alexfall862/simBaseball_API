// ui/form.js — form markup builders + value readers.
//
//   el.innerHTML = formGrid([
//     field.number('league_year_id', 'League Year ID', { value: 1, min: 1 }),
//     field.select('level', 'Level', [{value:9,label:'9 - MLB'}]),
//     field.checkbox('dry_run', 'Dry run', { checked: true }),
//     field.text('name', 'Name'), field.textarea('params', 'Params (JSON)'),
//   ]);
//   const values = readForm(el);   // {league_year_id: 1, level: 9, dry_run: true, ...} (numbers coerced)

import { esc } from '../core/html.js';

function attrs(o) {
  return Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== false)
    .map(([k, v]) => (v === true ? k : `${k}="${esc(v)}"`)).join(' ');
}

export const field = {
  text(name, label, { value = '', placeholder = '', help = '', required = false, width = '' } = {}) {
    return `<div class="form-group"${width ? ` style="max-width:${esc(width)}"` : ''}><label for="f-${esc(name)}">${esc(label)}</label>
      <input type="text" id="f-${esc(name)}" name="${esc(name)}" ${attrs({ value, placeholder, required })} />${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  password(name, label, o = {}) {
    return field.text(name, label, o).replace('type="text"', 'type="password"');
  },
  number(name, label, { value = '', min, max, step, placeholder = '', help = '', width = '' } = {}) {
    return `<div class="form-group"${width ? ` style="max-width:${esc(width)}"` : ''}><label for="f-${esc(name)}">${esc(label)}</label>
      <input type="number" id="f-${esc(name)}" name="${esc(name)}" data-type="number" ${attrs({ value, min, max, step, placeholder })} />${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  select(name, label, options, { value = null, placeholder = null, help = '', multiple = false } = {}) {
    const opts = (placeholder ? `<option value="">${esc(placeholder)}</option>` : '') + options.map(o => {
      const v = typeof o === 'object' ? o.value : o;
      const l = typeof o === 'object' ? o.label : o;
      const selected = value != null && (Array.isArray(value) ? value.map(String).includes(String(v)) : String(v) === String(value));
      return `<option value="${esc(v)}"${selected ? ' selected' : ''}>${esc(l)}</option>`;
    }).join('');
    return `<div class="form-group"><label for="f-${esc(name)}">${esc(label)}</label>
      <select id="f-${esc(name)}" name="${esc(name)}"${multiple ? ' multiple data-type="list"' : ''}>${opts}</select>${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  checkbox(name, label, { checked = false, help = '' } = {}) {
    return `<div class="form-group form-check"><label class="checkbox-label"><input type="checkbox" id="f-${esc(name)}" name="${esc(name)}" data-type="bool"${checked ? ' checked' : ''} /> <span>${esc(label)}</span></label>${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  textarea(name, label, { value = '', rows = 4, placeholder = '', help = '', mono = true } = {}) {
    return `<div class="form-group form-wide"><label for="f-${esc(name)}">${esc(label)}</label>
      <textarea id="f-${esc(name)}" name="${esc(name)}" rows="${rows}" ${attrs({ placeholder })}${mono ? ' class="mono"' : ''}>${esc(value)}</textarea>${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  json(name, label, { value = {}, rows = 6, help = '' } = {}) {
    const txt = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    return field.textarea(name, label, { value: txt, rows, help }).replace('<textarea ', '<textarea data-type="json" ');
  },
  datetime(name, label, { value = '', help = '' } = {}) {
    return `<div class="form-group"><label for="f-${esc(name)}">${esc(label)}</label>
      <input type="datetime-local" id="f-${esc(name)}" name="${esc(name)}" ${attrs({ value })} />${help ? `<small class="text-muted">${esc(help)}</small>` : ''}</div>`;
  },
  static(label, valueHtml) {
    return `<div class="form-group"><label>${esc(label)}</label><div class="form-static">${valueHtml}</div></div>`;
  },
};

export function formGrid(fields, { cols = null } = {}) {
  return `<div class="form-grid"${cols ? ` style="grid-template-columns:repeat(${Number(cols)},1fr)"` : ''}>${fields.join('')}</div>`;
}

export function formRow(fields) {
  return `<div class="form-row">${fields.join('')}</div>`;
}

/** Read all named inputs in root into an object with type coercion. */
export function readForm(root) {
  const out = {};
  root.querySelectorAll('[name]').forEach(inp => {
    const name = inp.getAttribute('name');
    const type = inp.dataset.type || inp.type;
    if (type === 'bool' || inp.type === 'checkbox') { out[name] = !!inp.checked; return; }
    if (type === 'list') { out[name] = Array.from(inp.selectedOptions).map(o => coerce(o.value)); return; }
    if (type === 'json') {
      const t = inp.value.trim();
      if (!t) { out[name] = null; return; }
      try { out[name] = JSON.parse(t); } catch (e) { throw new Error(`${name}: invalid JSON (${e.message})`); }
      return;
    }
    if (type === 'number' || inp.type === 'number') {
      out[name] = inp.value === '' ? null : Number(inp.value);
      return;
    }
    out[name] = inp.value;
  });
  return out;
}

function coerce(v) {
  if (v === '') return null;
  const n = Number(v);
  return Number.isNaN(n) ? v : n;
}

/** Write values into named inputs. */
export function writeForm(root, values) {
  for (const [k, v] of Object.entries(values || {})) {
    const inp = root.querySelector(`[name="${CSS.escape(k)}"]`);
    if (!inp) continue;
    if (inp.type === 'checkbox') inp.checked = !!v;
    else if (inp.dataset.type === 'json') inp.value = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
    else if (inp.multiple) Array.from(inp.options).forEach(o => { o.selected = Array.isArray(v) && v.map(String).includes(o.value); });
    else inp.value = v == null ? '' : String(v);
  }
}

/** Card wrapper markup. */
export function card(title, bodyHtml, { subtitle = '', actionsHtml = '', id = '', cls = '' } = {}) {
  return `<div class="card ${esc(cls)}"${id ? ` id="${esc(id)}"` : ''}>
    ${title || actionsHtml ? `<div class="card-head"><div>${title ? `<h3>${esc(title)}</h3>` : ''}${subtitle ? `<p class="text-muted card-sub">${esc(subtitle)}</p>` : ''}</div>${actionsHtml ? `<div class="card-actions">${actionsHtml}</div>` : ''}</div>` : ''}
    ${bodyHtml}
  </div>`;
}

export function button(label, { cls = 'btn-secondary', id = '', action = '', size = '', disabled = false, title = '', data = {} } = {}) {
  const d = Object.entries(data).map(([k, v]) => ` data-${esc(k)}="${esc(v)}"`).join('');
  return `<button type="button" class="btn ${esc(cls)}${size ? ` btn-${esc(size)}` : ''}"${id ? ` id="${esc(id)}"` : ''}${action ? ` data-action="${esc(action)}"` : ''}${disabled ? ' disabled' : ''}${title ? ` title="${esc(title)}"` : ''}${d}>${esc(label)}</button>`;
}
