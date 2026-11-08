// features/market/amateur.js — amateur contract seeding + populate college orgs (port of legacy #section-tx-amateur).
// These are app.py / admin blueprint endpoints; called with { admin: true } so the password header rides along.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { fmtNum } from '../../core/format.js';
import { simpleTable, kvTable } from '../../ui/table.js';
import { kpi } from '../../ui/badge.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked } from '../../ui/task-runner.js';
import { parseIdList } from './_shared.js';

const SEED_LABELS = {
  hs_contracts: 'HS contracts created',
  intam_contracts: 'INTAM contracts created',
  college_contracts: 'College contracts created',
  total_contracts: 'Total contracts',
  redshirt_count: 'Redshirt players',
  details_created: 'Contract detail rows',
  shares_created: 'Team share rows',
  skipped_no_age: 'Skipped (no age)',
  skipped_zero_years: 'Skipped (zero years)',
};

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Amateur player need</h3><p class="card-sub text-muted">Scan uncontracted players by category to see how many need HS, INTAM and College assignments (GET /admin/amateur-contracts-preview).</p></div>
        <div class="row"><button class="btn btn-secondary" data-action="scan">Scan players</button></div>
      </div>
      <div id="am-preview" hidden>
        <div class="grid-3" id="am-cards"></div>
        <h4 class="mb-1">Breakdown</h4>
        <div id="am-breakdown"></div>
      </div>
    </div>

    <div class="card">
      <h3>Seed amateur contracts</h3>
      <p class="text-muted small mb-2">Creates contracts for all uncontracted players, assigning them to HS, INTAM and College organizations. Idempotent: running again only processes newly uncontracted players (POST /admin/seed-amateur-contracts).</p>
      <div class="alert alert-info">Requires <code>ALLOW_CONTRACT_SEEDING=true</code> on the server.</div>
      <div class="button-group"><button class="btn btn-warning" data-action="seed">Seed amateur contracts</button></div>
      <div id="am-seed-progress"></div>
      <div id="am-seed-result" class="mt-2" hidden><h4 class="mb-1">Seeding summary</h4><div id="am-seed-kv"></div></div>
    </div>

    <div class="card">
      <h3>Populate college orgs</h3>
      <p class="text-muted small mb-2">Generate players and create college contracts for specific organizations without touching existing rosters (POST /admin/populate-college-orgs).</p>
      ${raw(formGrid([
        field.text('org_ids', 'Org IDs (comma-separated)', { placeholder: '341, 342' }),
        field.number('pitchers_per_org', 'Pitchers / org', { value: 17, min: 1, max: 30 }),
        field.number('batters_per_org', 'Batters / org', { value: 17, min: 1, max: 30 }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" data-action="populate">Populate orgs</button></div>
      <div id="am-pop-progress"></div>
      <pre class="result-box mt-2" id="am-pop-result"></pre>
    </div>`);

  const seedProgress = progressWidget(q(el, '#am-seed-progress'));
  const popProgress = progressWidget(q(el, '#am-pop-progress'));

  async function scan(btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
    try {
      const d = await api.get(adm('/amateur-contracts-preview'), { signal: ctx.signal, admin: true });
      const hs = d.hs || {}, iy = d.intam_young || {}, io = d.intam_older || {}, col = d.college || {};
      const assignable = (hs.total || 0) + (iy.total || 0) + (io.total || 0) + (col.total || 0);
      q(el, '#am-preview').hidden = false;
      setHtml(q(el, '#am-cards'), raw([
        kpi({ label: 'Total uncontracted', value: fmtNum(d.total_uncontracted), sub: `${fmtNum(assignable)} assignable, ${fmtNum(d.skipped || 0)} skipped` }),
        kpi({ label: 'College eligible', value: fmtNum(col.total), sub: `${col.avg_pitchers_per_org ?? '--'} P / ${col.avg_batters_per_org ?? '--'} B per org (target ${col.target_per_org ?? '--'})` }),
        kpi({ label: 'Pre-professional', value: fmtNum((hs.total || 0) + (iy.total || 0) + (io.total || 0)), sub: `${fmtNum(hs.total || 0)} HS + ${fmtNum((iy.total || 0) + (io.total || 0))} INTAM` }),
      ].join('')));
      const rows = [
        ['High School', hs.org, '15-17', hs.pitchers, hs.batters, hs.total, 'USA only, contracts expire at 18'],
        ['INTAM (young)', iy.org, iy.age_range, iy.pitchers, iy.batters, iy.total, 'International, expire at 18'],
        ['INTAM (older)', io.org, io.age_range, io.pitchers, io.batters, io.total, 'International, expire at 23'],
        ['College', `${col.orgs_available ?? '--'} orgs`, '18-23', col.pitchers, col.batters, col.total, `~20% redshirt (+1yr), target ${col.target_per_org ?? '--'}/org`],
      ].map(r => r.map((v, i) => (i >= 3 && i <= 5 ? fmtNum(v) : (v ?? '--'))));
      setHtml(q(el, '#am-breakdown'), raw(simpleTable(['Category', 'Org', 'Age range', 'Pitchers', 'Batters', 'Total', 'Notes'], rows)));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Scan players'; }
    }
  }

  async function seed() {
    if (!await confirm({ title: 'Seed amateur contracts?', danger: true, typeToConfirm: 'SEED', confirmLabel: 'Seed',
      message: 'Creates contracts for every uncontracted amateur player (HS, INTAM, College). Idempotent, but the new contracts are only reversible by hand.' })) return;
    const r = await runTracked({ el: q(el, '#am-seed-progress'), widget: seedProgress, label: 'Seeding amateur contracts…', signal: ctx.signal,
      start: () => api.post(adm('/seed-amateur-contracts'), {}, { admin: true }) });
    const d = (r && r.details) || r || {};
    q(el, '#am-seed-result').hidden = false;
    setHtml(q(el, '#am-seed-kv'), raw(kvTable(Object.entries(SEED_LABELS).map(([k, label]) => [label, d[k] !== undefined ? fmtNum(d[k]) : '--']))));
    toast.success('Amateur contracts seeded');
    scan().catch(() => {});
  }

  async function populate() {
    const f = readForm(el);
    const orgIds = parseIdList(f.org_ids);
    const out = q(el, '#am-pop-result');
    if (!orgIds.length) { toast.warn('Enter at least one valid org ID'); return; }
    const pitchers = Number(f.pitchers_per_org) || 17, batters = Number(f.batters_per_org) || 17;
    const total = orgIds.length * (pitchers + batters);
    if (!await confirm({ title: `Populate ${orgIds.length} org(s)?`, confirmLabel: 'Populate',
      message: `Generates ${total} players (${pitchers} P + ${batters} B per org) and creates college contracts for orgs ${orgIds.join(', ')}.` })) return;
    const d = await runTracked({ el: q(el, '#am-pop-progress'), widget: popProgress, label: `Generating ${total} players…`, signal: ctx.signal,
      start: () => api.post(adm('/populate-college-orgs'), { org_ids: orgIds, pitchers_per_org: pitchers, batters_per_org: batters }, { admin: true }) });
    const lines = [`Done — ${fmtNum(d.total_players_generated)} players, ${fmtNum(d.total_contracts)} contracts`, ''];
    for (const [orgId, info] of Object.entries(d.per_org || {})) lines.push(`  Org ${orgId}: ${info.players} players, ${info.contracts} contracts`);
    lines.push('', `Details rows: ${fmtNum(d.total_details)}`, `Share rows: ${fmtNum(d.total_shares)}`);
    out.textContent = lines.join('\n');
    toast.success('College orgs populated');
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    try {
      if (btn.dataset.action === 'scan') await scan(btn);
      else if (btn.dataset.action === 'seed') await seed();
      else if (btn.dataset.action === 'populate') await populate();
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);
}
