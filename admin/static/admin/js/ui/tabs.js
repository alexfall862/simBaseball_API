// ui/tabs.js — in-view sub-navigation (for areas like Analytics with 14 reports).
//
//   const t = subTabs(el, [{id:'batting', title:'Batting'}, ...], { active, signal, onSelect(id) });
//   t.set('pitching')

import { esc } from '../core/html.js';
import { on } from '../core/html.js';

export function subTabs(el, items, { active = null, signal, onSelect, vertical = false } = {}) {
  el.classList.add('subtabs');
  if (vertical) el.classList.add('subtabs-vertical');
  let current = active || (items[0] && items[0].id);

  function render() {
    el.innerHTML = items.map(it => `<button class="subtab${it.id === current ? ' active' : ''}" data-id="${esc(it.id)}" type="button">${esc(it.title)}</button>`).join('');
  }
  render();
  on(el, 'click', (e) => {
    const b = e.target.closest('.subtab');
    if (!b) return;
    if (b.dataset.id === current) return;
    current = b.dataset.id;
    render();
    if (onSelect) onSelect(current);
  }, signal);

  return {
    get active() { return current; },
    set(id, { silent = false } = {}) {
      if (!items.find(i => i.id === id)) return;
      current = id;
      render();
      if (!silent && onSelect) onSelect(current);
    },
  };
}

/** Collapsible card section. */
export function collapsible(el, { title, open = true, body = '' } = {}) {
  el.classList.add('card', 'collapsible');
  el.innerHTML = `<div class="collapsible-head"><h3>${esc(title)}</h3><button class="btn btn-sm btn-secondary" type="button">${open ? 'Hide' : 'Show'}</button></div>
    <div class="collapsible-body" ${open ? '' : 'style="display:none"'}>${body}</div>`;
  const btn = el.querySelector('.collapsible-head button');
  const bodyEl = el.querySelector('.collapsible-body');
  btn.addEventListener('click', () => {
    const hidden = bodyEl.style.display === 'none';
    bodyEl.style.display = hidden ? '' : 'none';
    btn.textContent = hidden ? 'Hide' : 'Show';
  });
  return bodyEl;
}
