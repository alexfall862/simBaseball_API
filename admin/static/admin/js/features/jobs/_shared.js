// features/jobs/_shared.js — job type registry cache + param form rendering.

import { api, adm } from '../../core/api.js';
import { esc } from '../../core/html.js';
import { field } from '../../ui/form.js';
import { LEVEL_NAMES } from '../../core/constants.js';

let typesCache = null;

export async function loadTypes({ force = false } = {}) {
  if (typesCache && !force) return typesCache;
  const d = await api.get(adm('/jobs/types'), { quiet: true });
  typesCache = { types: d.types || [], defaultTimezone: d.default_timezone || 'America/New_York' };
  return typesCache;
}

export function typeByName(name) {
  return typesCache && typesCache.types.find(t => t.job_type === name);
}

/** Render param inputs for a job type. Values are read back with readParams(). */
export function paramFields(spec, values = {}) {
  const out = [];
  for (const [key, meta] of Object.entries(spec.params || {})) {
    const label = `${meta.label || key}${meta.optional ? '' : ''}`;
    const val = values[key] !== undefined ? values[key] : meta.default;
    const help = meta.help || '';
    if (meta.choices) {
      const opts = meta.choices.map(c => ({ value: c, label: key.includes('level') && LEVEL_NAMES[c] ? `${c} - ${LEVEL_NAMES[c]}` : String(c) }));
      out.push(field.select(`p_${key}`, label, opts, { value: val, placeholder: meta.optional ? '— none —' : null, help }).replace('<select ', `<select data-ptype="${esc(meta.type || 'str')}" `));
    } else if (meta.type === 'bool') {
      out.push(field.checkbox(`p_${key}`, label, { checked: !!val, help }));
    } else if (meta.type === 'int') {
      out.push(field.number(`p_${key}`, label, { value: val ?? '', help, placeholder: meta.optional ? 'optional' : '' }));
    } else if (meta.type === 'list[int]') {
      out.push(field.text(`p_${key}`, label, { value: Array.isArray(val) ? val.join(',') : (val ?? ''), help: `${help} Comma-separated.`.trim() }).replace('<input ', '<input data-ptype="list[int]" '));
    } else {
      out.push(field.text(`p_${key}`, label, { value: val ?? '', help }));
    }
  }
  return out;
}

export function readParams(root, spec) {
  const out = {};
  for (const [key, meta] of Object.entries(spec.params || {})) {
    const inp = root.querySelector(`[name="p_${CSS.escape(key)}"]`);
    if (!inp) continue;
    if (meta.type === 'bool') { out[key] = !!inp.checked; continue; }
    const v = inp.value;
    if (v === '' || v == null) { if (!meta.optional && meta.default === undefined && !meta.choices) continue; continue; }
    if (meta.type === 'int') out[key] = Number(v);
    else if (meta.type === 'list[int]') out[key] = v.split(/[,; ]+/).filter(Boolean).map(Number);
    else out[key] = v;
  }
  return out;
}

export function scheduleLabel(j) {
  if (j.schedule_kind === 'cron') return `cron ${j.cron_expr} (${j.timezone})`;
  if (j.schedule_kind === 'interval') return `every ${humanSeconds(j.interval_s)}`;
  if (j.schedule_kind === 'once') return `once at ${j.run_at || '?'}`;
  return 'manual';
}

export function humanSeconds(s) {
  s = Number(s || 0);
  if (s % 86400 === 0) return `${s / 86400}d`;
  if (s % 3600 === 0) return `${s / 3600}h`;
  if (s % 60 === 0) return `${s / 60}m`;
  return `${s}s`;
}

export const PRESETS = [
  { name: 'Daily subweek', job_type: 'sim_next_subweek', schedule_kind: 'cron', cron_expr: '0 6 * * *',
    params: { auto_advance: true }, desc: 'One subweek every morning at 06:00; advances the week after subweek d.' },
  { name: 'Weekday week', job_type: 'run_week', schedule_kind: 'cron', cron_expr: '0 6 * * 1-5',
    params: {}, desc: 'A full sim week (a–d + advance) every weekday at 06:00.' },
  { name: 'Recruiting day', job_type: 'recruiting_advance_week', schedule_kind: 'cron', cron_expr: '0 7 * * *',
    params: { times: 1 }, desc: 'One recruiting week per day at 07:00 while recruiting is open.' },
  { name: 'FA round daily', job_type: 'fa_advance_round', schedule_kind: 'interval', interval_s: 86400,
    params: {}, desc: 'Advance every open FA auction one phase every 24h while free agency is open.' },
  { name: 'Playoff round check', job_type: 'playoffs_process_and_advance', schedule_kind: 'cron', cron_expr: '30 6 * * *',
    params: { league_level: 9 }, desc: 'After the morning sim, advance the MLB bracket if the round finished.' },
];
