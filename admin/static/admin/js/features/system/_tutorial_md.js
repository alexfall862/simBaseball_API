// features/system/_tutorial_md.js — tutorial markdown helpers used by tutorial.js:
// insert templates, the approximate preview renderer and the custom-block validator.
// Ported from the legacy app.js (_TUT_TEMPLATES, _tutMdToHtml, _tutValidate); the preview
// uses the shell's component classes instead of inline styles. No external markdown library
// was used by the legacy UI either — this is a minimal renderer for headings, lists,
// paragraphs, inline bold/italic/code/glossary and the ::: custom blocks.

import { esc } from '../../core/html.js';
import { badge } from '../../ui/badge.js';

export const BLOCK_TYPES = ['rating', 'callout', 'compare', 'link', 'detail', 'player-example', 'league'];
const OPEN_RE = /^:::(rating|callout|compare|link|detail|player-example|league)\b(.*)/;

export const TEMPLATES = Object.freeze({
  glossary: '[term]{definition}',
  rating: ':::rating\nattribute: \nscale: 20-80\nexample: 50\ndescription: \n:::\n',
  'callout-tip': ':::callout type=tip\n\n:::\n',
  'callout-info': ':::callout type=info\n\n:::\n',
  'callout-warning': ':::callout type=warning\n\n:::\n',
  'callout-important': ':::callout type=important\n\n:::\n',
  compare: ':::compare\n| | Option A | Option B |\n|---|---|---|\n| Metric | Value | Value |\n:::\n',
  link: ':::link\ntarget: team\nlabel: Go to your team →\nleague: auto\n:::\n',
  detail: ':::detail title=""\n\n:::\n',
  'player-hitter': ':::player-example\nposition: CF\nattributes:\n  contact: 50\n  power: 50\n  eye: 50\n  speed: 50\n  fielding: 50\ncaption: ""\n:::\n',
  'player-pitcher': ':::player-example\nposition: SP\nattributes:\n  stuff: 50\n  control: 50\n  stamina: 50\n  velocity: 50\ncaption: ""\n:::\n',
  'league-mlb': ':::league filter=MLB\n\n:::\n',
  'league-college': ':::league filter=College\n\n:::\n',
});

/** Toolbar definition: [key, label, title]. Groups are separated by null. */
export const INSERT_BUTTONS = Object.freeze([
  ['glossary', 'Glossary', 'Glossary tooltip [term]{definition}'], null,
  ['rating', 'Rating', 'Rating visualizer scale bar'],
  ['player-hitter', 'Player (Hitter)', 'Mock hitter player card'],
  ['player-pitcher', 'Player (Pitcher)', 'Mock pitcher player card'], null,
  ['callout-tip', 'Tip', 'Green tip callout'],
  ['callout-info', 'Info', 'Blue info callout'],
  ['callout-warning', 'Warning', 'Amber warning callout'],
  ['callout-important', 'Important', 'Red important callout'], null,
  ['compare', 'Compare', 'Responsive comparison table'],
  ['link', 'Sim Link', 'Sim navigation button'],
  ['detail', 'Detail', 'Collapsible detail section'], null,
  ['league-mlb', 'MLB Only', 'MLB-only content block'],
  ['league-college', 'College Only', 'College-only content block'],
]);

/** Insert a template at the textarea caret, starting on a fresh line. */
export function insertTemplate(ta, key) {
  const template = TEMPLATES[key];
  if (!ta || !template) return;
  const start = ta.selectionStart, end = ta.selectionEnd, text = ta.value;
  const prefix = (start > 0 && text[start - 1] !== '\n') ? '\n\n' : (start > 1 && text[start - 2] !== '\n') ? '\n' : '';
  ta.value = text.slice(0, start) + prefix + template + text.slice(end);
  const pos = start + prefix.length + template.indexOf('\n') + 1;
  ta.selectionStart = ta.selectionEnd = pos;
  ta.focus();
}

// ---------------------------------------------------------------- preview

function inline(text) {
  let s = esc(text);
  s = s.replace(/\[([^\]]+)\]\{([^}]+)\}/g, '<abbr title="$2">$1</abbr>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  return s;
}

function basicMd(text) {
  let out = '';
  for (const para of text.split(/\n{2,}/)) {
    const t = para.trim();
    if (!t) continue;
    if (t.startsWith('#### ')) out += `<h4>${inline(t.slice(5))}</h4>`;
    else if (t.startsWith('### ')) out += `<h3>${inline(t.slice(4))}</h3>`;
    else if (t.startsWith('## ')) out += `<h2>${inline(t.slice(3))}</h2>`;
    else if (/^[-*] /m.test(t)) out += `<ul>${t.split('\n').filter(l => /^[-*] /.test(l)).map(l => `<li>${inline(l.replace(/^[-*] /, ''))}</li>`).join('')}</ul>`;
    else if (/^\d+\. /m.test(t)) out += `<ol>${t.split('\n').filter(l => /^\d+\. /.test(l)).map(l => `<li>${inline(l.replace(/^\d+\. /, ''))}</li>`).join('')}</ol>`;
    else out += `<p>${inline(t.replace(/\n/g, ' '))}</p>`;
  }
  return out;
}

function parseFields(lines) {
  const f = {};
  for (const line of lines) { const m = line.match(/^(\w[\w-]*):\s*(.+)/); if (m) f[m[1]] = m[2].trim(); }
  return f;
}

function renderRating(lines) {
  const f = parseFields(lines);
  const [min, max] = String(f.scale || '20-80').split('-').map(Number);
  const example = parseInt(f.example || '50', 10);
  const pct = Math.max(0, Math.min(100, ((example - min) / ((max - min) || 1)) * 100));
  const kind = pct < 30 ? 'danger' : pct < 50 ? 'warning' : pct < 75 ? 'primary' : 'success';
  return `<div class="card tight">
    <div class="row between"><strong>${esc(f.attribute || '?')}</strong>${badge(String(example), kind)}</div>
    <div class="progress-container mt-1" style="height:8px"><div class="progress-fill" style="width:${pct}%"></div></div>
    <div class="row between small text-muted"><span>${esc(min)}</span><span>${esc(max)}</span></div>
    <div class="small">${esc(f.description || '')}</div>
  </div>`;
}

function renderCallout(args, content) {
  const m = args.match(/type=(\w+)/);
  const ctype = m ? m[1] : 'info';
  const kind = { tip: 'success', info: 'info', warning: 'warning', important: 'danger' }[ctype] || 'info';
  const label = ctype.charAt(0).toUpperCase() + ctype.slice(1);
  return `<div class="alert alert-${kind}"><strong>${esc(label)}</strong><div class="mt-1">${inline(content.trim())}</div></div>`;
}

function renderCompare(lines) {
  const rows = lines.filter(l => l.trim().startsWith('|'));
  if (rows.length < 2) return '<p class="text-muted small">Compare block: no table found</p>';
  let out = '<div class="table-container"><table class="data-table compact">';
  rows.forEach((line, idx) => {
    if (line.replace(/[|\-\s]/g, '').length === 0) return;
    const cells = line.split('|').slice(1, -1).map(c => c.trim());
    const tag = idx === 0 ? 'th' : 'td';
    out += `<tr>${cells.map(c => `<${tag}>${inline(c)}</${tag}>`).join('')}</tr>`;
  });
  return `${out}</table></div>`;
}

function renderLink(lines) {
  const f = parseFields(lines);
  return `<div class="row"><span class="btn btn-primary btn-sm">${esc(f.label || 'Link')} →</span><span class="small text-muted">→ ${esc(f.target || '?')} (${esc(f.league || 'auto')})</span></div>`;
}

function renderDetail(args, content) {
  const m = args.match(/title="([^"]*)"/);
  return `<details class="card tight"><summary>${esc(m ? m[1] : 'Details')}</summary><div class="mt-1 small">${basicMd(content)}</div></details>`;
}

function renderPlayerCard(lines) {
  const f = parseFields(lines);
  const caption = String(f.caption || '').replace(/^"|"$/g, '');
  const attrs = [];
  let inAttrs = false;
  for (const line of lines) {
    if (line.trim().startsWith('attributes:')) { inAttrs = true; continue; }
    if (!inAttrs) continue;
    const am = line.match(/^\s+(\w+):\s*(\d+)/);
    if (am) attrs.push([am[1], parseInt(am[2], 10)]); else inAttrs = false;
  }
  const rows = attrs.map(([k, v]) => {
    const kind = v >= 65 ? 'primary' : v >= 55 ? 'success' : v >= 45 ? 'secondary' : 'danger';
    return `<div class="kv-row"><div class="kv-key">${esc(k)}</div><div class="kv-val">${badge(String(v), kind)}</div></div>`;
  }).join('');
  return `<div class="card tight">
    <div class="row">${badge(f.position || '??', 'primary')}<span class="small text-muted">Example player</span></div>
    <div class="kv-table mt-1">${rows}</div>
    ${caption ? `<p class="small text-muted mt-1"><em>${esc(caption)}</em></p>` : ''}
  </div>`;
}

function renderLeague(args, content) {
  const m = args.match(/filter=(\w+)/);
  const league = m ? m[1] : '?';
  return `<div class="card tight">${badge(league, league === 'MLB' ? 'primary' : 'success')}<div class="mt-1 small">${basicMd(content)}</div></div>`;
}

function renderBlock(type, args, lines) {
  const content = lines.join('\n');
  switch (type) {
    case 'rating': return renderRating(lines);
    case 'callout': return renderCallout(args, content);
    case 'compare': return renderCompare(lines);
    case 'link': return renderLink(lines);
    case 'detail': return renderDetail(args, content);
    case 'player-example': return renderPlayerCard(lines);
    case 'league': return renderLeague(args, content);
    default: return `<p class="text-muted small">Unknown block: ${esc(type)}</p>`;
  }
}

/** Render tutorial markdown (with ::: custom blocks) into trusted preview HTML. */
export function renderMarkdown(md) {
  const lines = String(md || '').split('\n');
  let out = '';
  let buf = [];
  const flush = () => { if (buf.length) { out += basicMd(buf.join('\n')); buf = []; } };
  let i = 0;
  while (i < lines.length) {
    const m = lines[i].match(OPEN_RE);
    if (m) {
      flush();
      const body = [];
      i++;
      while (i < lines.length && lines[i].trim() !== ':::') { body.push(lines[i]); i++; }
      i++;
      out += renderBlock(m[1], m[2].trim(), body);
    } else { buf.push(lines[i]); i++; }
  }
  flush();
  return out;
}

// ---------------------------------------------------------------- validation

function validateBlock(type, args, lines, lineNum, errors) {
  const fields = parseFields(lines);
  switch (type) {
    case 'rating':
      for (const f of ['attribute', 'scale', 'example', 'description']) if (!fields[f]) errors.push(`Line ${lineNum}: :::rating missing required field "${f}"`);
      break;
    case 'callout': {
      const m = args.match(/type=(\w+)/);
      if (!m) errors.push(`Line ${lineNum}: :::callout missing type= (tip|info|warning|important)`);
      else if (!['tip', 'info', 'warning', 'important'].includes(m[1])) errors.push(`Line ${lineNum}: :::callout type="${m[1]}" is not valid (use tip|info|warning|important)`);
      break;
    }
    case 'compare':
      if (lines.filter(l => l.trim().startsWith('|')).length < 2) errors.push(`Line ${lineNum}: :::compare must contain a markdown table`);
      break;
    case 'link':
      for (const f of ['target', 'label', 'league']) if (!fields[f]) errors.push(`Line ${lineNum}: :::link missing required field "${f}"`);
      break;
    case 'detail':
      if (!/title="[^"]*"/.test(args)) errors.push(`Line ${lineNum}: :::detail missing title="..." attribute`);
      break;
    case 'player-example':
      if (!fields.position) errors.push(`Line ${lineNum}: :::player-example missing "position" field`);
      if (!lines.some(l => /^\s+\w+:\s*\d+/.test(l))) errors.push(`Line ${lineNum}: :::player-example has no attributes`);
      break;
    case 'league': {
      const m = args.match(/filter=(\w+)/);
      if (!m) errors.push(`Line ${lineNum}: :::league missing filter= (MLB|College)`);
      else if (!['MLB', 'College'].includes(m[1])) errors.push(`Line ${lineNum}: :::league filter="${m[1]}" is not valid (use MLB|College)`);
      break;
    }
    default: break;
  }
}

/** Returns a list of human-readable validation errors (empty when the markdown is fine). */
export function validateMarkdown(md) {
  const errors = [];
  const lines = String(md || '').split('\n');
  const stack = [];
  lines.forEach((line, i) => {
    const open = line.match(OPEN_RE);
    if (open) stack.push({ type: open[1], args: open[2].trim(), line: i + 1 });
    else if (line.trim() === ':::' && stack.length) {
      const b = stack.pop();
      validateBlock(b.type, b.args, lines.slice(b.line, i), b.line, errors);
    } else if (line.trim() === ':::') errors.push(`Line ${i + 1}: Closing ::: without a matching opening block`);
  });
  for (const b of stack) errors.push(`Line ${b.line}: :::${b.type} block never closed (missing :::)`);
  lines.forEach((ln, i) => {
    if (/\[[^\]]*\]\{/.test(ln) && !/\[[^\]]*\]\{[^}]*\}/.test(ln)) errors.push(`Line ${i + 1}: Glossary tooltip has unclosed {definition}`);
  });
  return errors;
}
