// features/timeline/view.js — the league-year timeline.

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, delegate, on, q } from '../../core/html.js';
import { store } from '../../core/store.js';
import { fmtDate, relTime, json } from '../../core/format.js';
import { SIM_LEVELS, levelName, phaseLabel } from '../../core/constants.js';
import { badge, statusBadge, phaseBadge, subweekPips, emptyState } from '../../ui/badge.js';
import { kvTable } from '../../ui/table.js';
import { leagueYearSelect, levelSelect } from '../../ui/selectors.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Timeline</h3><p class="card-sub text-muted">Sim weeks, postseason rounds and offseason steps for a league year, with job runs and the projected real-world date each week lands on at the current cadence.</p></div>
        <div class="row"><select id="tl-ly"></select><select id="tl-level"></select><button class="btn btn-sm btn-ghost" data-action="refresh">Refresh</button></div>
      </div>
      <div id="tl-summary" class="row mb-2"></div>
      <div class="tl-wrap" id="tl-wrap"></div>
      <div class="tl-legend"><span class="l-played">played</span><span>scheduled</span><span class="l-post">postseason</span><span class="l-now">now</span><span>● job run &nbsp; ○ planned fire</span></div>
    </div>
    <div class="grid-2">
      <div class="card" id="tl-detail"><h3>Week detail</h3><p class="text-muted">Click a week.</p></div>
      <div class="stack">
        <div class="card" id="tl-postseason"></div>
        <div class="card" id="tl-offseason"></div>
        <div class="card" id="tl-projection"></div>
      </div>
    </div>`);

  const lySel = q(el, '#tl-ly'), lvSel = q(el, '#tl-level');
  const lvl = levelSelect(lvSel, { levels: SIM_LEVELS, allowAll: true, allLabel: 'All levels', value: ctx.params.level || 9 });
  await leagueYearSelect(lySel, { global: true, value: ctx.params.league_year_id || null, signal: ctx.signal, onChange: () => load() });
  on(lvSel, 'change', load, ctx.signal);

  let data = null;
  let selected = null;

  async function load() {
    const wrap = q(el, '#tl-wrap');
    wrap.innerHTML = '<div class="text-muted small">Loading…</div>';
    try {
      data = await api.get(adm('/timeline'), { signal: ctx.signal, params: { league_year_id: lySel.value || undefined, league_level: lvl.get() == null ? 'all' : lvl.get() } });
      ctx.setParams({ league_year_id: lySel.value, level: lvl.get() == null ? 'all' : lvl.get() });
    } catch (e) { if (e.name !== 'AbortError') wrap.innerHTML = `<div class="text-danger">${html`${e.message}`}</div>`; return; }
    render();
  }

  function render() {
    const ly = data.league_year, now = data.now;
    const wd = (data.projection && data.projection.week_dates) || {};
    setHtml(q(el, '#tl-summary'), raw(`
      <span><strong>${ly.year}</strong> <span class="text-muted">(league_year_id ${ly.id})</span></span>
      ${now.is_current_year ? `${phaseBadge(now.phase)} <span>Week <strong>${now.week}</strong>/${now.total_weeks} ${subweekPips(now.subweeks)}</span>` : badge(ly.season_ended_at ? 'ended' : 'not current', 'secondary')}
      <span class="text-muted small">${data.league_level ? levelName(data.league_level) : 'all levels'} · ${ly.weeks_in_season} regular weeks${data.weeks.length > ly.weeks_in_season ? ` + ${data.weeks.length - ly.weeks_in_season} postseason` : ''}</span>`));

    const fires = {};
    for (const s of data.scheduled || []) for (const f of s.fires || []) { const d = f.slice(0, 10); fires[d] = (fires[d] || 0) + 1; }
    const dateToWeek = {};
    for (const [w, d] of Object.entries(wd)) dateToWeek[d] = Number(w);

    const cells = data.weeks.map(w => {
      const pct = w.scheduled ? Math.round((w.played / w.scheduled) * 100) : 0;
      const cls = ['tl-week', w.state, w.postseason ? 'postseason' : '', now.is_current_year && w.week === now.week ? 'now' : '', selected === w.week ? 'selected' : ''].filter(Boolean).join(' ');
      const runs = w.job_runs || [];
      const dots = runs.slice(0, 3).map(r => `<i class="${r.status === 'failed' ? 'fail' : ''}"></i>`).join('');
      const planned = wd[String(w.week)] && w.state !== 'played' && w.week >= (now.week || 0) ? '<i class="plan"></i>' : '';
      const tip = `Week ${w.week}${w.label ? ` (${w.label})` : ''}: ${w.played}/${w.scheduled} games${wd[String(w.week)] ? ` · projected ${wd[String(w.week)]}` : ''}${runs.length ? ` · ${runs.length} job run(s)` : ''}`;
      return `<div class="${cls}" style="--pct:${pct}%" data-week="${w.week}" title="${html`${tip}`}">${w.week}</div>`
        + `|${dots}${planned}|${wd[String(w.week)] ? wd[String(w.week)].slice(5) : ''}`;
    });
    // Build three aligned lanes from the encoded cells
    const weekCells = [], runCells = [], dateCells = [];
    for (const c of cells) { const [wk, runs, date] = c.split('|'); weekCells.push(wk); runCells.push(`<div class="tl-run">${runs}</div>`); dateCells.push(`<div class="tl-date">${date}</div>`); }
    setHtml(q(el, '#tl-wrap'), raw(`<div class="tl-track">${weekCells.join('')}</div><div class="tl-runs">${runCells.join('')}</div>${Object.keys(wd).length ? `<div class="tl-dates">${dateCells.join('')}</div>` : ''}`));

    // postseason
    const ps = data.postseason || { rounds: [] };
    setHtml(q(el, '#tl-postseason'), raw(`<h3>Postseason</h3>${ps.rounds.length ? `<div class="tl-steps">${ps.rounds.map(r => `<div class="tl-step ${r.status === 'complete' ? 'done' : ''} ${r.status === 'in_progress' ? 'current' : ''}"><span class="n">${html`${r.round}`}</span> ${statusBadge(r.status)} <span class="text-muted small">${r.complete}/${r.series} series${r.start_week ? ` · wk ${r.start_week}` : ''}${r.levels && r.levels.length > 1 ? ` · L${r.levels.join(',')}` : ''}</span></div>`).join('')}</div>` : emptyState('No bracket for this level/year yet.')}<div class="mt-1"><a class="btn btn-sm btn-ghost" href="#/season/playoffs">Playoffs tab</a></div>`));

    // offseason
    const oc = data.offseason;
    const m = data.market || {};
    const marketBits = [];
    if (m.fa) marketBits.push(`FA ${m.fa.locked ? 'locked' : 'open'}${m.fa.round != null ? ` · round ${m.fa.round}` : ''}`);
    if (m.draft) marketBits.push(`Draft ${m.draft.phase || '?'}${m.draft.current_round ? ` R${m.draft.current_round} P${m.draft.current_pick}` : ''}`);
    if (m.ifa) marketBits.push(`IFA ${m.ifa.status} wk ${m.ifa.current_week}/${m.ifa.total_weeks}`);
    if (m.recruiting) marketBits.push(`Recruiting ${m.recruiting.status} wk ${m.recruiting.current_week}/20`);
    setHtml(q(el, '#tl-offseason'), raw(`<h3>Offseason rollover</h3>${oc && oc.steps ? `<div class="tl-steps">${oc.steps.map(s => `<div class="tl-step ${s.done === true ? 'done' : ''} ${s.manual ? 'manual' : ''}" title="${html`${s.detail || ''}`}"><span class="n">${s.order}</span> ${html`${s.title}`} ${s.done === true ? badge('done', 'success') : s.not_built ? badge('n/a', 'danger') : s.manual ? badge('manual', 'warning') : badge('pending', 'pending')}</div>`).join('')}</div>` : emptyState('No checklist data.')}${marketBits.length ? `<div class="text-muted small mt-1">${marketBits.join(' · ')}</div>` : ''}<div class="mt-1"><a class="btn btn-sm btn-ghost" href="#/season/checklist">Checklist tab</a></div>`));

    // projection
    const p = data.projection;
    setHtml(q(el, '#tl-projection'), raw(`<h3>Projection</h3>${p ? `<p class="small">Basis: <strong>${html`${p.basis}`}</strong></p>${kvTable([
      ['Regular season ends', p.regular_season_end || '—'], ['Postseason starts', p.postseason_start || '—'],
      ['Weeks projected', Object.keys(p.week_dates).length],
    ])}` : `<p class="text-muted small">No enabled sim job (sim_next_subweek or run_week) to project from${now.is_current_year ? '' : ', or this is not the current league year'}. <a href="#/jobs/scheduled?new=1">Create one</a>.</p>`}
      ${(data.scheduled || []).length ? `<h4 class="mt-2 mb-1">Upcoming fires</h4><div class="small">${data.scheduled.map(s => `<div><strong>${html`${s.name}`}</strong> <span class="mono text-muted">${html`${s.job_type}`}</span>: ${s.fires.slice(0, 3).map(f => fmtDate(f)).join(', ')}${s.fires.length > 3 ? ` … (+${s.fires.length - 3})` : ''}</div>`).join('')}</div>` : ''}`));
    if (selected) renderDetail(selected);
  }

  function renderDetail(week) {
    const w = data.weeks.find(x => x.week === week);
    const box = q(el, '#tl-detail');
    if (!w) { setHtml(box, '<h3>Week detail</h3><p class="text-muted">Click a week.</p>'); return; }
    const wd = (data.projection && data.projection.week_dates) || {};
    setHtml(box, raw(`<div class="card-head"><h3>Week ${w.week}${w.label ? ` · ${html`${w.label}`}` : ''}</h3>${badge(w.state, w.state === 'played' ? 'success' : w.state === 'partial' ? 'warning' : 'secondary')}</div>
      ${kvTable([
        ['Games', `${w.played} / ${w.scheduled}`],
        ['Subweeks', ['a', 'b', 'c', 'd'].map(k => `${k.toUpperCase()} ${w.subweeks[k].played}/${w.subweeks[k].scheduled}`).join('  ')],
        ['Game types', Object.entries(w.types || {}).map(([k, v]) => `${k}: ${v}`).join(', ') || '—'],
        ['Last game played', w.last_played_at ? fmtDate(w.last_played_at) : '—'],
        ['Books run', w.books_run_at ? fmtDate(w.books_run_at) : (w.postseason ? 'n/a (postseason)' : 'not yet')],
        ['Injuries ticked', w.injuries_ticked_at ? fmtDate(w.injuries_ticked_at) : 'not yet'],
        ['Projected date', wd[String(w.week)] || '—'],
      ])}
      <h4 class="mt-2 mb-1">Job runs</h4>
      ${(w.job_runs || []).length ? `<div class="table-container"><table class="data-table compact"><thead><tr><th>Run</th><th>Job</th><th>Subweek</th><th>Status</th><th>Finished</th></tr></thead><tbody>${w.job_runs.map(r => `<tr><td><a href="#/jobs/runs?run=${r.run_id}">#${r.run_id}</a></td><td class="mono">${html`${r.job_type}`}</td><td>${r.subweek ? r.subweek.toUpperCase() : ''}</td><td>${statusBadge(r.status)}</td><td>${relTime(r.finished_at)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="text-muted small">No job runs recorded for this week.</p>'}`));
  }

  delegate(el, 'click', '.tl-week', (e, cell) => { selected = Number(cell.dataset.week); render(); }, ctx.signal);
  delegate(el, 'click', '[data-action="refresh"]', load, ctx.signal);
  store.watch('ts', () => { if (data) load(); }, ctx.signal, { immediate: false });
  await load();
}
