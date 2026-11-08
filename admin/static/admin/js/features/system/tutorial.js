// features/system/tutorial.js — tutorial content CMS (port of legacy #section-tutorial-content).
//
//   GET    /admin/tutorial/manifest                       {ok, manifest:{categories:[...], glossary:{}}}
//   GET    /admin/tutorial/article/<cat>/<art>            {ok, article, markdown, frontmatter}
//   PUT    /admin/tutorial/article/<cat>/<art>            {title, summary, tags, leagueFilter, relatedArticles, lastUpdated, markdown}
//   POST   /admin/tutorial/article/<cat>                  {id, title, summary, tags, leagueFilter, relatedArticles?, lastUpdated, markdown}
//   DELETE /admin/tutorial/article/<cat>/<art>
//   POST   /admin/tutorial/category                       {id, title, icon, description, leagueFilter}
//   PUT    /admin/tutorial/category/<cat>                 {title?, description?, icon?, order?, leagueFilter?}
//   DELETE /admin/tutorial/category/<cat>
//   PUT    /admin/tutorial/glossary                       {glossary:{term: definition}}
//   PUT    /admin/tutorial/reorder                        {categories:[{id,order}], articles:{cat:[{id,order}]}}
// All writes need session write mode (403 write_mode_disabled otherwise).

import { api, adm } from '../../core/api.js';
import { html, raw, esc, setHtml, on, delegate, q, qa } from '../../core/html.js';
import { field, formGrid, readForm, writeForm } from '../../ui/form.js';
import { badge } from '../../ui/badge.js';
import { confirm, openModal, promptText } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { writeModeBanner } from './_shared.js';
import { INSERT_BUTTONS, insertTemplate, renderMarkdown, validateMarkdown } from './_tutorial_md.js';

const LEAGUE_OPTS = [{ value: '', label: 'Both (null)' }, { value: 'MLB', label: 'MLB' }, { value: 'College', label: 'College' }];
const ICON_OPTS = ['compass - Getting Started', 'chart - Attributes / Stats', 'bat - Hitting', 'target - Pitching', 'glove - Fielding', 'clipboard - Roster',
  'brain - Strategy', 'handshake - Free Agency', 'arrows - Trades', 'podium - Draft', 'megaphone - Recruiting', 'bank - Financials', 'calendar - Season',
  'bandage - Injuries', 'trophy - Playoffs', 'globe - International'].map(s => ({ value: s.split(' - ')[0], label: s }));

const today = () => new Date().toISOString().slice(0, 10);
const splitList = (s) => String(s || '').split(',').map(t => t.trim()).filter(Boolean);
const byOrder = (a, b) => (a.order ?? 0) - (b.order ?? 0);
const leagueBadge = (lf) => (lf ? badge(lf, lf === 'MLB' ? 'primary' : 'success') : '');

export async function mount(el, ctx) {
  setHtml(el, html`
    <div id="tut-banner"></div>
    <div class="card tight">
      <div class="row between">
        <div class="row">
          <button class="btn btn-secondary btn-sm" data-action="refresh">Refresh</button>
          <button class="btn btn-primary btn-sm" data-action="cat-new">+ New category</button>
          <button class="btn btn-secondary btn-sm" data-action="glossary">Edit glossary</button>
        </div>
        <span id="tut-status" class="text-muted small"></span>
      </div>
    </div>

    <div id="tut-list"></div>

    <div id="tut-editor" hidden>
      <div class="card tight">
        <div class="row between">
          <div class="row"><button class="btn btn-secondary btn-sm" data-action="back">← Back</button><h3 class="mb-0" id="tut-editor-title">Edit article</h3><span id="tut-save-status" class="text-muted small"></span></div>
          <div class="row"><button class="btn btn-primary" data-action="save">Save</button><button class="btn btn-danger" data-action="art-delete">Delete</button></div>
        </div>
      </div>
      <div class="card" id="tut-meta">
        ${raw(formGrid([
          field.text('art_id', 'Article ID (slug)'),
          field.text('art_title', 'Title'),
          field.text('art_summary', 'Summary'),
          field.text('art_tags', 'Tags (comma-separated)', { placeholder: 'beginner, hitting, attributes' }),
          field.select('art_league', 'League filter', LEAGUE_OPTS),
          field.text('art_related', 'Related articles (category/article, comma-sep)', { placeholder: 'hitting/contact-vs-power, roster/setting-your-lineup' }),
        ]))}
      </div>
      <div class="card tight">
        <div class="row"><span class="text-muted small">INSERT:</span>
          ${raw(INSERT_BUTTONS.map(b => (b ? `<button class="btn btn-sm btn-ghost" data-action="insert" data-key="${esc(b[0])}" title="${esc(b[2])}">${esc(b[1])}</button>` : '<span class="text-muted">|</span>')).join(''))}
        </div>
      </div>
      <div id="tut-validation"></div>
      <div class="grid-2">
        <div class="card"><h3>Markdown</h3><textarea id="tut-md" class="mono" rows="30" spellcheck="false"></textarea></div>
        <div class="card"><h3>Preview <span class="text-muted small">approximate rendering</span></h3><div id="tut-preview"></div></div>
      </div>
      <div class="card tight"><div class="row"><button class="btn btn-primary" data-action="save">Save</button><span id="tut-save-status-2" class="text-muted small"></span></div></div>
    </div>

    <div id="tut-new-article" hidden>
      <div class="card">
        <h3>Create new article</h3>
        ${raw(formGrid([
          field.text('na_cat', 'Category'),
          field.text('na_id', 'Article ID (slug)', { placeholder: 'my-article', help: 'lowercase letters, digits and hyphens' }),
          field.text('na_title', 'Title'),
          field.text('na_summary', 'Summary'),
          field.text('na_tags', 'Tags (comma-separated)'),
          field.select('na_league', 'League filter', LEAGUE_OPTS),
          field.textarea('na_markdown', 'Markdown content', { rows: 14 }),
        ]))}
        <div class="button-group"><button class="btn btn-primary" data-action="art-create">Create article</button><button class="btn btn-secondary" data-action="back">Cancel</button></div>
      </div>
    </div>

    <div id="tut-glossary" hidden>
      <div class="card">
        <div class="card-head">
          <div class="row"><button class="btn btn-secondary btn-sm" data-action="back">← Back</button><h3 class="mb-0">Edit glossary</h3></div>
          <button class="btn btn-primary" data-action="gl-save">Save glossary</button>
        </div>
        <p class="text-muted small mb-2">Each row is a term and its definition. The frontend uses these for inline tooltips. Rows with an empty term are dropped on save.</p>
        <div id="tut-gl-rows"></div>
        <button class="btn btn-secondary btn-sm" data-action="gl-add">+ Add term</button>
      </div>
    </div>`);

  const canWrite = writeModeBanner(q(el, '#tut-banner'), ctx.signal, { what: 'Saving, creating, deleting or reordering tutorial content' });
  q(el, '[name="art_id"]').readOnly = true;
  q(el, '[name="na_cat"]').readOnly = true;

  let manifest = null;
  let editing = null;            // { cat, art }
  let previewTimer = null;
  ctx.signal.addEventListener('abort', () => clearTimeout(previewTimer));

  const status = (msg) => { q(el, '#tut-status').textContent = msg || ''; };
  const saveStatus = (msg, cls = 'text-muted') => {
    for (const id of ['#tut-save-status', '#tut-save-status-2']) { const n = q(el, id); n.textContent = msg || ''; n.className = `${cls} small`; }
  };
  const cats = () => (manifest && manifest.categories ? manifest.categories.slice().sort(byOrder) : []);
  const findCat = (id) => (manifest && manifest.categories || []).find(c => c.id === id);

  function showView(view) {
    for (const v of ['list', 'editor', 'new-article', 'glossary']) q(el, `#tut-${v}`).hidden = v !== view;
    if (view !== 'editor') editing = null;
  }

  // ---------------------------------------------------------------- list
  function renderList() {
    const list = q(el, '#tut-list');
    const sorted = cats();
    if (!sorted.length) { setHtml(list, '<div class="card"><p class="text-muted">No categories yet.</p></div>'); return; }
    setHtml(list, raw(sorted.map((cat, ci) => {
      const arts = (cat.articles || []).slice().sort(byOrder);
      const rows = arts.map((a, ai) => `<tr>
          <td class="text-muted">${esc(a.order)}</td>
          <td><strong>${esc(a.title)}</strong></td>
          <td><code>${esc(a.id)}</code></td>
          <td>${(a.tags || []).map(t => badge(t, 'secondary')).join(' ')}</td>
          <td>${leagueBadge(a.leagueFilter) || '<span class="text-muted">—</span>'}</td>
          <td class="nowrap">
            <button class="btn btn-xs btn-ghost" data-action="art-move" data-cat="${esc(cat.id)}" data-art="${esc(a.id)}" data-dir="-1" ${ai === 0 ? 'disabled' : ''} title="Move up">▲</button>
            <button class="btn btn-xs btn-ghost" data-action="art-move" data-cat="${esc(cat.id)}" data-art="${esc(a.id)}" data-dir="1" ${ai === arts.length - 1 ? 'disabled' : ''} title="Move down">▼</button>
            <button class="btn btn-xs btn-secondary" data-action="art-open" data-cat="${esc(cat.id)}" data-art="${esc(a.id)}">Edit</button>
            <button class="btn btn-xs btn-secondary" data-action="art-dup" data-cat="${esc(cat.id)}" data-art="${esc(a.id)}">Dup</button>
          </td></tr>`).join('');
      return `<div class="card">
        <div class="card-head">
          <div><h3>${esc(cat.title)} ${leagueBadge(cat.leagueFilter)} <span class="text-muted small">${esc(cat.icon || '')} · order ${esc(cat.order)}</span></h3><p class="card-sub text-muted">${esc(cat.description || '')}</p></div>
          <div class="card-actions">
            <button class="btn btn-xs btn-ghost" data-action="cat-move" data-cat="${esc(cat.id)}" data-dir="-1" ${ci === 0 ? 'disabled' : ''} title="Move up">▲</button>
            <button class="btn btn-xs btn-ghost" data-action="cat-move" data-cat="${esc(cat.id)}" data-dir="1" ${ci === sorted.length - 1 ? 'disabled' : ''} title="Move down">▼</button>
            <button class="btn btn-sm btn-secondary" data-action="cat-edit" data-cat="${esc(cat.id)}">Edit</button>
            <button class="btn btn-sm btn-primary" data-action="art-new" data-cat="${esc(cat.id)}">+ Article</button>
            <button class="btn btn-sm btn-danger" data-action="cat-delete" data-cat="${esc(cat.id)}">Delete</button>
          </div>
        </div>
        ${arts.length ? `<div class="table-container"><table class="data-table compact"><thead><tr><th>#</th><th>Title</th><th>ID</th><th>Tags</th><th>League</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<p class="text-muted small">No articles yet.</p>'}
      </div>`;
    }).join('')));
  }

  async function loadManifest() {
    status('Loading…');
    showView('list');
    try {
      const d = await api.get(adm('/tutorial/manifest'), { signal: ctx.signal });
      manifest = d.manifest || { categories: [], glossary: {} };
      renderList();
      const n = (manifest.categories || []).reduce((s, c) => s + (c.articles || []).length, 0);
      status(`${(manifest.categories || []).length} categories, ${n} articles`);
    } catch (e) { if (e.name !== 'AbortError') status(`Error: ${e.message}`); }
  }

  // ---------------------------------------------------------------- reorder
  async function reorder(body) {
    if (!canWrite()) { toast.warn('Write mode is off'); return; }
    await api.put(adm('/tutorial/reorder'), body, { signal: ctx.signal });
    toast.success('Order saved');
    await loadManifest();
  }

  function moveCategory(catId, dir) {
    const sorted = cats();
    const i = sorted.findIndex(c => c.id === catId);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= sorted.length) return;
    [sorted[i], sorted[j]] = [sorted[j], sorted[i]];
    return reorder({ categories: sorted.map((c, k) => ({ id: c.id, order: k + 1 })) });
  }

  function moveArticle(catId, artId, dir) {
    const cat = findCat(catId);
    if (!cat) return;
    const arts = (cat.articles || []).slice().sort(byOrder);
    const i = arts.findIndex(a => a.id === artId);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= arts.length) return;
    [arts[i], arts[j]] = [arts[j], arts[i]];
    return reorder({ articles: { [catId]: arts.map((a, k) => ({ id: a.id, order: k + 1 })) } });
  }

  // ---------------------------------------------------------------- editor
  function renderPreview() { setHtml(q(el, '#tut-preview'), raw(renderMarkdown(q(el, '#tut-md').value))); }
  function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(renderPreview, 250); }

  function showValidation(errors) {
    const bar = q(el, '#tut-validation');
    if (!errors.length) { setHtml(bar, ''); return; }
    setHtml(bar, raw(`<div class="alert alert-danger"><strong>${errors.length} issue${errors.length > 1 ? 's' : ''} found:</strong><ul class="small mt-1">${errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>`));
  }

  async function openArticle(catId, artId) {
    status('Loading article…');
    try {
      const d = await api.get(adm(`/tutorial/article/${encodeURIComponent(catId)}/${encodeURIComponent(artId)}`), { signal: ctx.signal });
      const art = d.article || {};
      editing = { cat: catId, art: artId };
      writeForm(q(el, '#tut-meta'), {
        art_id: artId, art_title: art.title || '', art_summary: art.summary || '', art_tags: (art.tags || []).join(', '),
        art_league: art.leagueFilter || '', art_related: (art.relatedArticles || []).join(', '),
      });
      q(el, '#tut-md').value = d.markdown || '';
      q(el, '#tut-editor-title').textContent = `Edit: ${art.title || artId}`;
      saveStatus('');
      showValidation([]);
      showView('editor');
      editing = { cat: catId, art: artId };
      renderPreview();
      status('');
    } catch (e) { if (e.name !== 'AbortError') status(`Error: ${e.message}`); }
  }

  async function saveArticle() {
    if (!editing) return;
    const markdown = q(el, '#tut-md').value;
    const errors = validateMarkdown(markdown);
    showValidation(errors);
    if (errors.length) { saveStatus(`${errors.length} validation error(s) — fix before saving`, 'text-danger'); return; }
    if (!canWrite()) { toast.warn('Write mode is off'); return; }
    const f = readForm(q(el, '#tut-meta'));
    const body = {
      title: String(f.art_title || '').trim(), summary: String(f.art_summary || '').trim(), tags: splitList(f.art_tags),
      leagueFilter: f.art_league || null, relatedArticles: splitList(f.art_related), lastUpdated: today(), markdown,
    };
    saveStatus('Saving…');
    try {
      await api.put(adm(`/tutorial/article/${encodeURIComponent(editing.cat)}/${encodeURIComponent(editing.art)}`), body, { signal: ctx.signal });
      saveStatus('Saved ✓', 'text-success');
      toast.success('Article saved');
    } catch (e) { if (e.name !== 'AbortError') saveStatus(`Error: ${e.message}`, 'text-danger'); }
  }

  async function deleteArticle() {
    if (!editing) return;
    const { cat, art } = editing;
    if (!await confirm({ title: 'Delete article?', danger: true, typeToConfirm: 'DELETE', confirmLabel: 'Delete',
      message: `Deletes "${art}" from "${cat}" and removes its markdown file. This cannot be undone.` })) return;
    try {
      await api.del(adm(`/tutorial/article/${encodeURIComponent(cat)}/${encodeURIComponent(art)}`), { signal: ctx.signal });
      toast.success('Article deleted');
      await loadManifest();
    } catch (e) { if (e.name !== 'AbortError') return; }
  }

  async function duplicateArticle(catId, artId) {
    status('Loading article for duplication…');
    try {
      const d = await api.get(adm(`/tutorial/article/${encodeURIComponent(catId)}/${encodeURIComponent(artId)}`), { signal: ctx.signal });
      status('');
      const newId = await promptText({ title: 'Duplicate article', label: 'New article ID (slug)', value: `${artId}-copy` });
      if (!newId || !newId.trim()) return;
      const art = d.article || {};
      await api.post(adm(`/tutorial/article/${encodeURIComponent(catId)}`), {
        id: newId.trim(), title: `${art.title || artId} (Copy)`, summary: art.summary || '', tags: art.tags || [],
        leagueFilter: art.leagueFilter || null, relatedArticles: art.relatedArticles || [], lastUpdated: today(), markdown: d.markdown || '',
      }, { signal: ctx.signal });
      toast.success('Duplicated');
      await loadManifest();
    } catch (e) { if (e.name !== 'AbortError') status(''); }
  }

  // ---------------------------------------------------------------- new article
  function newArticleView(catId) {
    writeForm(q(el, '#tut-new-article'), { na_cat: catId, na_id: '', na_title: '', na_summary: '', na_tags: '', na_league: '', na_markdown: '' });
    showView('new-article');
  }

  async function createArticle() {
    const f = readForm(q(el, '#tut-new-article'));
    const id = String(f.na_id || '').trim(), title = String(f.na_title || '').trim();
    if (!id || !title) { toast.warn('ID and Title are required'); return; }
    if (!canWrite()) { toast.warn('Write mode is off'); return; }
    try {
      await api.post(adm(`/tutorial/article/${encodeURIComponent(f.na_cat)}`), {
        id, title, summary: String(f.na_summary || '').trim(), tags: splitList(f.na_tags), leagueFilter: f.na_league || null,
        lastUpdated: today(), markdown: f.na_markdown || '',
      }, { signal: ctx.signal });
      toast.success(`Article ${id} created`);
      await loadManifest();
    } catch (e) { if (e.name !== 'AbortError') return; }
  }

  // ---------------------------------------------------------------- categories
  function categoryModal({ title, values, okLabel, onSave, withId }) {
    const fields = [];
    if (withId) fields.push(field.text('c_id', 'Category ID (slug)', { placeholder: 'my-category' }));
    fields.push(field.text('c_title', 'Title', { placeholder: 'My Category' }), field.select('c_icon', 'Icon key', ICON_OPTS),
      field.text('c_description', 'Description', { placeholder: 'Short description for the card' }), field.select('c_league', 'League filter', LEAGUE_OPTS));
    if (!withId) fields.push(field.number('c_order', 'Order', { min: 1 }));
    const h = openModal({
      title, body: formGrid(fields),
      actions: [
        { label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close() },
        { label: okLabel, cls: 'btn-primary', onClick: async (hh) => { const f = readForm(hh.body); if (await onSave(f) !== false) hh.close(); } },
      ],
    });
    writeForm(h.body, values);
  }

  function newCategory() {
    categoryModal({
      title: 'Create new category', okLabel: 'Create category', withId: true, values: { c_icon: 'compass', c_league: '' },
      onSave: async (f) => {
        const id = String(f.c_id || '').trim(), title = String(f.c_title || '').trim();
        if (!id || !title) { toast.warn('ID and Title are required'); return false; }
        if (!canWrite()) { toast.warn('Write mode is off'); return false; }
        try {
          await api.post(adm('/tutorial/category'), { id, title, icon: f.c_icon || 'compass', description: String(f.c_description || '').trim(), leagueFilter: f.c_league || null }, { signal: ctx.signal });
          toast.success(`Category ${id} created`);
          await loadManifest();
        } catch (e) { return false; }
      },
    });
  }

  function editCategory(catId) {
    const cat = findCat(catId);
    if (!cat) return;
    categoryModal({
      title: `Edit category: ${cat.title}`, okLabel: 'Save', withId: false,
      values: { c_title: cat.title || '', c_icon: cat.icon || 'compass', c_description: cat.description || '', c_league: cat.leagueFilter || '', c_order: cat.order ?? '' },
      onSave: async (f) => {
        if (!canWrite()) { toast.warn('Write mode is off'); return false; }
        try {
          await api.put(adm(`/tutorial/category/${encodeURIComponent(catId)}`), {
            title: String(f.c_title || '').trim() || cat.title, description: String(f.c_description || '').trim(), icon: f.c_icon || cat.icon,
            order: f.c_order || cat.order, leagueFilter: f.c_league || null,
          }, { signal: ctx.signal });
          toast.success('Category updated');
          await loadManifest();
        } catch (e) { return false; }
      },
    });
  }

  async function deleteCategory(catId) {
    const cat = findCat(catId);
    if (!cat) return;
    const count = (cat.articles || []).length;
    if (!await confirm({ title: 'Delete category?', danger: true, typeToConfirm: 'DELETE', confirmLabel: 'Delete',
      message: `Deletes "${cat.title}" and its ${count} article(s), including their markdown files. This cannot be undone.` })) return;
    try {
      await api.del(adm(`/tutorial/category/${encodeURIComponent(catId)}`), { signal: ctx.signal });
      toast.success('Category deleted');
      await loadManifest();
    } catch (e) { if (e.name !== 'AbortError') return; }
  }

  // ---------------------------------------------------------------- glossary
  const glossaryRow = (term, def) => `<div class="form-row tut-gl-row">
      <div class="form-group"><label>Term</label><input type="text" class="tut-gl-term" value="${esc(term)}" placeholder="Term" /></div>
      <div class="form-group"><label>Definition</label><input type="text" class="tut-gl-def" value="${esc(def)}" placeholder="Definition" size="60" /></div>
      <button class="btn btn-danger btn-sm" data-action="gl-remove" title="Remove row">×</button>
    </div>`;

  function openGlossary() {
    if (!manifest) return;
    setHtml(q(el, '#tut-gl-rows'), raw(Object.entries(manifest.glossary || {}).map(([t, d]) => glossaryRow(t, d)).join('')));
    showView('glossary');
  }

  async function saveGlossary() {
    if (!canWrite()) { toast.warn('Write mode is off'); return; }
    const glossary = {};
    for (const row of qa(el, '.tut-gl-row')) {
      const term = q(row, '.tut-gl-term').value.trim();
      if (term) glossary[term] = q(row, '.tut-gl-def').value.trim();
    }
    try {
      await api.put(adm('/tutorial/glossary'), { glossary }, { signal: ctx.signal });
      manifest.glossary = glossary;
      toast.success(`Glossary saved (${Object.keys(glossary).length} terms)`);
      status('Glossary saved ✓');
      showView('list');
    } catch (e) { if (e.name !== 'AbortError') return; }
  }

  // ---------------------------------------------------------------- wiring
  const ta = q(el, '#tut-md');
  on(ta, 'input', schedulePreview, ctx.signal);
  on(ta, 'keydown', (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = ta.selectionStart;
      ta.value = `${ta.value.slice(0, s)}  ${ta.value.slice(ta.selectionEnd)}`;
      ta.selectionStart = ta.selectionEnd = s + 2;
      schedulePreview();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveArticle(); }
  }, ctx.signal);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action, d = btn.dataset;
    try {
      switch (a) {
        case 'refresh': case 'back': await loadManifest(); break;
        case 'cat-new': newCategory(); break;
        case 'cat-edit': editCategory(d.cat); break;
        case 'cat-delete': await deleteCategory(d.cat); break;
        case 'cat-move': await moveCategory(d.cat, Number(d.dir)); break;
        case 'art-new': newArticleView(d.cat); break;
        case 'art-create': await createArticle(); break;
        case 'art-open': await openArticle(d.cat, d.art); break;
        case 'art-dup': await duplicateArticle(d.cat, d.art); break;
        case 'art-move': await moveArticle(d.cat, d.art, Number(d.dir)); break;
        case 'art-delete': await deleteArticle(); break;
        case 'save': await saveArticle(); break;
        case 'insert': insertTemplate(ta, d.key); schedulePreview(); break;
        case 'glossary': openGlossary(); break;
        case 'gl-add': q(el, '#tut-gl-rows').insertAdjacentHTML('beforeend', glossaryRow('', '')); break;
        case 'gl-remove': btn.closest('.tut-gl-row').remove(); break;
        case 'gl-save': await saveGlossary(); break;
        default: break;
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  await loadManifest();
  if (ctx.params.cat && ctx.params.art) await openArticle(ctx.params.cat, ctx.params.art);
}
