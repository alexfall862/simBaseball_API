// features/market/roster.js — roster moves + free-agent signing (port of legacy #section-tx-roster).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q, esc } from '../../core/html.js';
import { json } from '../../core/format.js';
import { dataTable } from '../../ui/table.js';
import { badge } from '../../ui/badge.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { openModal, confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { fillSelect } from '../../ui/selectors.js';
import { orgSelect, txContext, levelName, money, PRO_LEVELS, PRO_LEVEL_OPTIONS, salaryFields, readSalaries } from './_shared.js';

const ACTIONS = [
  { value: 'promote', label: 'Promote' },
  { value: 'demote', label: 'Demote' },
  { value: 'ir_place', label: 'Place on IR' },
  { value: 'ir_activate', label: 'Activate from IR' },
  { value: 'release', label: 'Release' },
  { value: 'buyout', label: 'Buyout' },
  { value: 'extend', label: 'Extend contract' },
];

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="grid-2">
      <div class="card">
        <h3>Organization</h3>
        <div class="row">
          <select id="rm-org"></select>
          <button class="btn btn-secondary" data-action="load">Load roster</button>
        </div>
        <p class="text-muted small mt-1" id="rm-budget"></p>
      </div>
      <div class="card">
        <h3>Roster status</h3>
        <div id="rm-status" class="text-muted small">Select an org to view roster counts.</div>
      </div>
    </div>

    <div class="card" id="rm-roster-card" hidden>
      <div class="card-head">
        <h3>Roster</h3>
        <div class="row"><label class="small text-muted">Level <select id="rm-level"></select></label></div>
      </div>
      <div id="rm-roster"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Free agent signing</h3><p class="card-sub text-muted">Signs the player to the organization selected above (POST /transactions/sign).</p></div>
        <div class="row"><button class="btn btn-secondary" data-action="load-fa">Load free agents</button></div>
      </div>
      <div id="rm-fa"></div>
    </div>

    <pre class="result-box" id="rm-result"></pre>`);

  const orgSel = await orgSelect(q(el, '#rm-org'), { signal: ctx.signal, onChange: () => { if (orgSel.get()) loadRoster(); } });
  if (ctx.params.org) orgSel.set(ctx.params.org);
  fillSelect(q(el, '#rm-level'), PRO_LEVELS.map(l => ({ value: l, label: levelName(l) })), { placeholder: 'All levels' });

  let players = [];
  const rosterTable = dataTable(q(el, '#rm-roster'), {
    rowKey: 'contract_id', emptyText: 'No players found.', pageSize: 100, sortKey: 'current_level', sortDir: 'desc',
    columns: [
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'position', title: 'Pos', sortable: true },
      { key: 'current_level', title: 'Level', sortable: true, render: r => levelName(r.current_level), sortValue: r => r.current_level },
      { key: 'contract_id', title: 'Contract', html: true, render: r => `<code>${esc(r.contract_id)}</code>` },
      { key: 'salary', title: 'Salary', align: 'right', sortable: true, render: r => money(r.salary), sortValue: r => Number(r.salary) },
      { key: 'onIR', title: 'IR', html: true, render: r => (r.onIR ? badge('IR', 'danger') : '<span class="text-muted">--</span>') },
      { key: '_a', title: '', html: true, render: r => `<button class="btn btn-xs btn-primary" data-action="select" data-id="${r.contract_id}">Action</button>` },
    ],
  });
  const faTable = dataTable(q(el, '#rm-fa'), {
    rowKey: 'player_id', emptyText: 'Click "Load free agents".', pageSize: 100,
    columns: [
      { key: 'player_name', title: 'Player', sortable: true },
      { key: 'position', title: 'Pos', sortable: true },
      { key: 'age', title: 'Age', sortable: true, render: r => r.age ?? '--' },
      { key: 'player_id', title: 'ID' },
      { key: '_a', title: '', html: true, render: r => `<button class="btn btn-xs btn-primary" data-action="sign" data-id="${r.player_id}">Sign</button>` },
    ],
  });
  let freeAgents = [];

  function applyLevelFilter() {
    const lv = q(el, '#rm-level').value;
    rosterTable.setRows(lv ? players.filter(p => Number(p.current_level) === Number(lv)) : players);
  }
  on(q(el, '#rm-level'), 'change', applyLevelFilter, ctx.signal);

  async function loadRoster() {
    const orgId = orgSel.get();
    if (!orgId) { toast.warn('Select an organization first'); return; }
    ctx.setParams({ org: orgId });
    q(el, '#rm-roster-card').hidden = false;
    rosterTable.setLoading();
    const statusEl = q(el, '#rm-status');
    statusEl.textContent = 'Loading…';
    const { league_year_id } = await txContext();
    const [status, roster, budget] = await Promise.allSettled([
      api.get(v1(`/transactions/roster-status/${orgId}`), { signal: ctx.signal, quiet: true }),
      api.get(v1(`/transactions/roster/${orgId}`), { signal: ctx.signal, quiet: true }),
      api.get(v1(`/transactions/signing-budget/${orgId}`), { signal: ctx.signal, quiet: true, params: { league_year_id } }),
    ]);
    if (status.status === 'fulfilled' && Array.isArray(status.value)) {
      const parts = status.value.filter(l => l.max_roster > 0).map(l => {
        const flag = l.over_limit ? ` ${badge('OVER', 'danger')}` : (l.under_limit ? ` ${badge('UNDER', 'warning')}` : '');
        return `<span><strong>${esc(levelName(l.level_id))}:</strong> ${l.count}/${l.max_roster}${flag}</span>`;
      });
      setHtml(statusEl, raw(`<div class="row">${parts.join('<span class="text-muted">|</span>') || '<span class="text-muted">No roster limits configured.</span>'}</div>`));
    } else {
      statusEl.textContent = 'Could not load roster status';
    }
    if (roster.status === 'fulfilled') {
      players = Array.isArray(roster.value) ? roster.value : [];
      applyLevelFilter();
    } else {
      players = [];
      rosterTable.setError(roster.reason && roster.reason.message);
    }
    q(el, '#rm-budget').textContent = budget.status === 'fulfilled'
      ? `Signing budget: ${money(budget.value.available_budget || 0)}` : '';
  }

  async function loadFreeAgents() {
    faTable.setLoading();
    try {
      const rows = await api.get(v1('/transactions/free-agents'), { signal: ctx.signal });
      freeAgents = Array.isArray(rows) ? rows : [];
      faTable.setRows(freeAgents);
    } catch (e) { if (e.name !== 'AbortError') faTable.setError(e.message); }
  }

  // ------------------------------------------------------------ player action modal
  function openPlayerAction(p) {
    const orgId = orgSel.get();
    const body = document.createElement('div');
    body.innerHTML = `
      <div class="form-grid">
        ${field.select('action', 'Action', ACTIONS, { placeholder: 'Select action…' })}
        <div data-grp="level" hidden>${field.select('target_level_id', 'Target level', PRO_LEVEL_OPTIONS, { value: p.current_level === 9 ? 8 : 9 })}</div>
        <div data-grp="buyout" hidden>${field.number('buyout_amount', 'Buyout amount ($)', { min: 0, step: 1000 })}</div>
      </div>
      <div data-grp="buyout" hidden class="text-muted small mb-2" data-demand="buyout"></div>
      <div data-grp="extend" hidden>
        <div data-demand="extension" class="mb-2"></div>
        ${formGrid([
          field.number('years', 'Extension years', { value: 1, min: 1, max: 5 }),
          field.number('bonus', 'Signing bonus ($)', { value: 0, min: 0, step: 1000 }),
        ])}
        <div class="form-grid" data-sal>${salaryFields(1)}</div>
      </div>
      <pre class="result-box" data-result></pre>`;

    const grp = (name) => Array.from(body.querySelectorAll(`[data-grp="${name}"]`));
    const actionSel = body.querySelector('[name="action"]');
    const yearsInp = body.querySelector('[name="years"]');

    const fetchDemand = async (type) => {
      const target = body.querySelector(`[data-demand="${type}"]`);
      if (!target || !p.player_id) return;
      target.textContent = 'Loading player demand…';
      const { league_year_id } = await txContext();
      try {
        const d = await api.post(v1('/fa-auction/compute-demands'), {
          player_id: p.player_id, league_year_id, demand_type: type, contract_id: p.contract_id,
        }, { quiet: true, signal: ctx.signal });
        if (type === 'buyout') target.innerHTML = `Player demands <strong>${esc(money(d.buyout_price))}</strong> minimum buyout (WAR ${esc(d.war)})`;
        else target.innerHTML = `<div class="alert alert-info">Player demands <strong>${esc(money(d.min_aav))}</strong> min AAV, ${esc(d.min_years)}–${esc(d.max_years)} years (WAR ${esc(d.war)})</div>`;
      } catch (e) {
        target.textContent = `Demand unavailable: ${e.message}`;
      }
    };

    actionSel.addEventListener('change', () => {
      const a = actionSel.value;
      grp('level').forEach(n => { n.hidden = !(a === 'promote' || a === 'demote'); });
      grp('buyout').forEach(n => { n.hidden = a !== 'buyout'; });
      grp('extend').forEach(n => { n.hidden = a !== 'extend'; });
      if (a === 'extend') fetchDemand('extension');
      if (a === 'buyout') fetchDemand('buyout');
    });
    yearsInp.addEventListener('change', () => {
      const yrs = Math.max(1, Math.min(5, Number(yearsInp.value) || 1));
      yearsInp.value = yrs;
      body.querySelector('[data-sal]').innerHTML = salaryFields(yrs);
    });

    const h = openModal({
      title: `Player action: ${p.player_name}`, body, size: 'lg',
      actions: [
        { label: 'Close', cls: 'btn-secondary', onClick: (hh) => hh.close() },
        { label: 'Execute', cls: 'btn-warning', onClick: async () => {
          const f = readForm(body);
          const a = f.action;
          if (!a) { toast.warn('Select an action'); return; }
          const { league_year_id, game_week_id } = await txContext();
          const base = { league_year_id, executed_by: 'admin', contract_id: p.contract_id };
          let url, payload;
          switch (a) {
            case 'promote': url = '/transactions/promote'; payload = { ...base, target_level_id: f.target_level_id }; break;
            case 'demote': url = '/transactions/demote'; payload = { ...base, target_level_id: f.target_level_id }; break;
            case 'ir_place': url = '/transactions/ir/place'; payload = base; break;
            case 'ir_activate': url = '/transactions/ir/activate'; payload = base; break;
            case 'release':
              if (!await confirm({ title: `Release ${p.player_name}?`, danger: true, confirmLabel: 'Release', message: 'The contract is terminated and the player leaves the organization. Use the transaction log to roll back.' })) return;
              url = '/transactions/release'; payload = { ...base, org_id: orgId }; break;
            case 'buyout':
              if (!await confirm({ title: `Buy out ${p.player_name}?`, danger: true, confirmLabel: 'Buyout', message: `Buyout amount ${money(f.buyout_amount || 0)}.` })) return;
              url = '/transactions/buyout'; payload = { ...base, org_id: orgId, buyout_amount: Number(f.buyout_amount) || 0, game_week_id }; break;
            case 'extend': {
              const years = Number(f.years) || 1;
              url = '/transactions/extend';
              payload = { ...base, org_id: orgId, years, salaries: readSalaries(body, years), bonus: Number(f.bonus) || 0, game_week_id };
              break;
            }
            default: toast.error(`Unknown action ${a}`); return;
          }
          const resEl = body.querySelector('[data-result]');
          resEl.textContent = 'Executing…';
          try {
            const r = await api.post(v1(url), payload);
            resEl.textContent = json(r);
            q(el, '#rm-result').textContent = json(r);
            toast.success(`${ACTIONS.find(x => x.value === a).label}: ${p.player_name}`);
            loadRoster();
          } catch (e) {
            resEl.textContent = `Error: ${e.message}`;
          }
        } },
      ],
    });
    void h;
  }

  // ------------------------------------------------------------ FA signing modal
  function openSign(fa) {
    const orgId = orgSel.get();
    if (!orgId) { toast.warn('Select an organization first (org selector above)'); return; }
    const body = document.createElement('div');
    body.innerHTML = `
      ${formGrid([
        field.number('years', 'Years', { value: 1, min: 1, max: 5 }),
        field.number('bonus', 'Bonus ($)', { value: 0, min: 0, step: 1000 }),
        field.select('level_id', 'Assign level', PRO_LEVEL_OPTIONS, { value: 9 }),
      ])}
      <div class="form-grid" data-sal>${salaryFields(1)}</div>
      <pre class="result-box" data-result></pre>`;
    const yearsInp = body.querySelector('[name="years"]');
    yearsInp.addEventListener('change', () => {
      const yrs = Math.max(1, Math.min(5, Number(yearsInp.value) || 1));
      yearsInp.value = yrs;
      body.querySelector('[data-sal]').innerHTML = salaryFields(yrs);
    });
    openModal({
      title: `Sign ${fa.player_name} → ${orgSel.name(orgId)}`, body, size: 'lg',
      actions: [
        { label: 'Cancel', cls: 'btn-secondary', onClick: (hh) => hh.close() },
        { label: 'Sign player', cls: 'btn-primary', onClick: async (hh) => {
          const f = readForm(body);
          const years = Number(f.years) || 1;
          const { league_year_id, game_week_id } = await txContext();
          const resEl = body.querySelector('[data-result]');
          resEl.textContent = 'Signing…';
          try {
            const r = await api.post(v1('/transactions/sign'), {
              player_id: fa.player_id, org_id: orgId, years, salaries: readSalaries(body, years),
              bonus: Number(f.bonus) || 0, level_id: Number(f.level_id), league_year_id, game_week_id, executed_by: 'admin',
            });
            q(el, '#rm-result').textContent = json(r);
            toast.success(`Signed ${fa.player_name}`);
            hh.close();
            loadRoster();
            loadFreeAgents();
          } catch (e) {
            resEl.textContent = `Error: ${e.message}`;
          }
        } },
      ],
    });
  }

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    try {
      if (a === 'load') await loadRoster();
      else if (a === 'load-fa') await loadFreeAgents();
      else if (a === 'select') {
        const p = players.find(x => String(x.contract_id) === btn.dataset.id);
        if (p) openPlayerAction(p);
      } else if (a === 'sign') {
        const fa = freeAgents.find(x => String(x.player_id) === btn.dataset.id);
        if (fa) openSign(fa);
      }
    } catch (err) { if (err && err.name === 'AbortError') return; }
  }, ctx.signal);

  if (orgSel.get()) loadRoster();
}
