// features/system/cache.js — in-memory config cache manager (port of legacy #section-cache).
// POST /admin/clear-caches → {ok, cleared:{game_payload:{core_tables:true,...}, rosters:{...}}}

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, q } from '../../core/html.js';
import { fmtDate, json } from '../../core/format.js';
import { simpleTable, kvTable } from '../../ui/table.js';
import { kpi, badge } from '../../ui/badge.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { busyButton } from '../../ui/task-runner.js';
import { flattenFlags } from './_shared.js';

const CACHED = [
  ['Level Config', '<code>level_contact_odds</code>, <code>level_distance_weights</code>, <code>level_catch_rates</code>, <code>level_batting_config</code>, <code>level_game_config</code>', 'Hit outcomes, ball distance, fielding, batting mechanics'],
  ['Game Constants', '<code>contact_types</code>, <code>distance_zones</code>, <code>hit_outcome_types</code>, <code>pitch_types</code>', 'Reference lookups used by the engine'],
  ['Level Rules', '<code>level_rules</code>', 'DH rules, roster limits, innings per game'],
  ['Core Tables', 'SQLAlchemy table reflection metadata', 'Schema-level cache; clear if columns were added/removed'],
  ['Injury Types', '<code>injury_types</code>', 'Injury classification and duration ranges'],
];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head"><div><h3>Cache manager</h3><p class="card-sub text-muted">The API caches configuration tables in memory. After editing values directly in the database (level configs, contact odds, distance weights, catch rates, …) clear the caches so the next simulation picks them up.</p></div></div>
      <div class="alert alert-warning"><strong>Changed config and not seeing results?</strong> If you modified <code>level_distance_weights</code>, <code>level_contact_odds</code>, <code>level_catch_rates</code>, <code>level_batting_config</code>, <code>level_game_config</code> or another engine config table, clear caches before the next sim.</div>
      <div class="grid-2 mb-2" id="cache-kpis">
        ${raw(kpi({ label: 'Cache status', value: 'Unknown', sub: 'Click "Clear all caches" to flush and inspect', id: 'cache-status' }))}
        ${raw(kpi({ label: 'Last cleared (this tab)', value: '--', sub: '', id: 'cache-last' }))}
      </div>
      <div class="button-group"><button class="btn btn-warning" id="btn-clear">Clear all caches</button></div>
      <div class="mt-2" id="cache-detail"></div>
      <pre class="result-box mt-1" id="cache-result"></pre>
    </div>
    <div class="card">
      <h3>What gets cached</h3>
      ${raw(simpleTable([{ title: 'Cache', key: 0 }, { title: 'DB tables affected', key: 1, html: true }, { title: 'Impact', key: 2 }], CACHED))}
    </div>`);

  function setKpi(id, value, sub, kind) {
    const card = q(el, `#${id}`);
    card.className = `stat-card${kind ? ` stat-${kind}` : ''}`;
    q(card, '.stat-value').textContent = value;
    q(card, '.stat-sub').textContent = sub || '';
  }

  busyButton(q(el, '#btn-clear'), async () => {
    if (!await confirm({ title: 'Clear all in-memory caches?', message: 'Harmless; the next request reloads config from the database. Do not run while a simulation is mid-flight.', confirmLabel: 'Clear caches' })) return;
    q(el, '#cache-result').textContent = 'Clearing caches…';
    try {
      const d = await api.post(adm('/clear-caches'), {}, { signal: ctx.signal });
      const flags = flattenFlags(d.cleared || {});
      const hadData = flags.some(([, v]) => v === true);
      setKpi('cache-status', hadData ? 'Cleared' : 'Already empty', `${flags.filter(([, v]) => v === true).length} of ${flags.length} caches had data`, hadData ? 'success' : '');
      const now = new Date();
      setKpi('cache-last', now.toLocaleTimeString(), fmtDate(now, { time: false }), 'info');
      setHtml(q(el, '#cache-detail'), raw(flags.length
        ? kvTable(flags.map(([k, v]) => [k, badge(v === true ? 'cleared' : v === false ? 'was empty' : String(v), v === true ? 'success' : 'secondary')]), { html: true })
        : ''));
      q(el, '#cache-result').textContent = json(d);
      toast.success(hadData ? 'Caches cleared' : 'Caches were already empty');
    } catch (e) {
      if (e.name === 'AbortError') return;
      setKpi('cache-status', 'Error', e.message, 'danger');
      q(el, '#cache-result').textContent = `Error: ${e.message}`;
    }
  });
}
