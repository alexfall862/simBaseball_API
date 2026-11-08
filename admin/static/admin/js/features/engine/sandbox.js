// features/engine/sandbox.js — in-memory progression sandbox (port of legacy #section-pe-sandbox).
// POST /admin/progression-sandbox -> { config, tracked_abilities, results: { ability: { grade: {count, ages, avg, p10, p90, players:[{id, ptype, trajectory}]} } } }

import { api, adm } from '../../core/api.js';
import { html, raw, setHtml, on, q } from '../../core/html.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { dataTable } from '../../ui/table.js';
import { toast } from '../../ui/toast.js';
import { mountChart } from '../../ui/chart.js';
import { fillSelect } from '../../ui/selectors.js';
import { busyButton } from '../../ui/task-runner.js';
import { gradeColor, fx, show, setStatus } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Progression sandbox</h3><p class="card-sub text-muted">Simulates player progression in memory without touching the database. Generates synthetic players and charts their growth across seasons using the live <a href="#/engine/rating-config">growth curves</a>.</p></div>
      </div>
      ${raw(formGrid([
        field.number('count', 'Players', { value: 200, min: 10, max: 2000 }),
        field.number('seasons', 'Seasons', { value: 20, min: 1, max: 30 }),
        field.number('start_age', 'Start age', { value: 15, min: 14, max: 30 }),
        field.select('player_type', 'Player type', ['Both', 'Pitcher', 'Position'], { value: 'Both' }),
      ]))}
      <div class="button-group"><button class="btn btn-primary" id="btn-run">Run simulation</button></div>
      <div class="mt-1" id="sb-status"></div>
    </div>

    <div class="card" id="sb-chart-card" style="display:none">
      <div class="row mb-2">
        <div class="form-group"><label for="sb-ability">Ability</label><select id="sb-ability"></select></div>
        <label class="checkbox-label"><input type="checkbox" id="sb-bands" checked /> <span>P10–P90 bands</span></label>
        <label class="checkbox-label"><input type="checkbox" id="sb-players" /> <span>Individual players</span></label>
        <div class="form-group" id="sb-grade-wrap" style="display:none"><label for="sb-grade">Grade</label><select id="sb-grade"></select></div>
        <div class="form-group" id="sb-hl-wrap" style="display:none"><label for="sb-highlight">Highlight</label><select id="sb-highlight"></select></div>
      </div>
      <div class="chart-wrap" style="height:420px"><canvas id="sb-chart"></canvas></div>
      <p class="text-muted small mt-1">Click an individual player line to highlight it.</p>
    </div>

    <div class="card" id="sb-summary-card" style="display:none">
      <h3>Grade distribution</h3>
      <div id="sb-summary"></div>
    </div>`);

  const status = q(el, '#sb-status');
  const abilitySel = q(el, '#sb-ability');
  const bandsChk = q(el, '#sb-bands');
  const playersChk = q(el, '#sb-players');
  const gradeSel = q(el, '#sb-grade');
  const hlSel = q(el, '#sb-highlight');

  const summary = dataTable(q(el, '#sb-summary'), {
    rowKey: 'grade', emptyText: 'No grades.',
    columns: [
      { key: 'grade', title: 'Grade', html: true, render: r => `<strong style="color:${gradeColor(r.grade)}">${html`${r.grade}`}</strong>` },
      { key: 'count', title: 'Players', align: 'right', sortable: true },
      { key: 'finalAvg', title: 'Final avg', align: 'right', sortable: true, render: r => fx(r.finalAvg, 1) },
      { key: 'peakAvg', title: 'Peak avg', align: 'right', sortable: true, render: r => fx(r.peakAvg, 1) },
      { key: 'best', title: 'Best individual', align: 'right', sortable: true, render: r => fx(r.best, 1) },
      { key: 'worst', title: 'Worst individual', align: 'right', sortable: true, render: r => fx(r.worst, 1) },
    ],
  });

  // Per-mount state.
  let data = null;
  let chart = null;

  const gradeData = () => (data && data.results && data.results[abilitySel.value]) || null;

  function populateGradeFilter() {
    const gd = gradeData();
    if (!gd) return;
    const prev = gradeSel.value || '__all__';
    fillSelect(gradeSel, [{ value: '__all__', label: 'All' }, ...Object.keys(gd).map(g => ({ value: g, label: `${g} (${gd[g].count})` }))], { value: prev });
    populateHighlight();
  }

  function populateHighlight() {
    const gd = gradeData();
    if (!gd) return;
    const grades = gradeSel.value === '__all__' || !gradeSel.value ? Object.keys(gd) : [gradeSel.value];
    const players = [];
    for (const g of grades) {
      for (const p of (gd[g] && gd[g].players) || []) {
        players.push({ id: p.id, grade: g, ptype: p.ptype, peak: Math.max(...p.trajectory) });
      }
    }
    players.sort((a, b) => b.peak - a.peak);
    const prev = hlSel.value;
    fillSelect(hlSel, players.map(p => ({ value: p.id, label: `P${p.id} (${p.grade}, ${p.ptype}, peak ${p.peak.toFixed(0)})` })), { value: prev, placeholder: 'None' });
  }

  function render() {
    const gd = gradeData();
    if (!gd) return;
    const showBands = bandsChk.checked;
    const showPlayers = playersChk.checked;
    const gradeFilter = gradeSel.value || '__all__';
    const highlightId = showPlayers ? hlSel.value : '';
    const hasHighlight = showPlayers && highlightId !== '';
    const grades = Object.keys(gd);
    const datasets = [];

    if (showPlayers) {
      const toDraw = gradeFilter === '__all__' ? grades : [gradeFilter];
      for (const grade of toDraw) {
        const g = gd[grade];
        if (!g || !g.players) continue;
        const color = gradeColor(grade);
        for (const p of g.players) {
          const hl = hasHighlight && String(p.id) === highlightId;
          datasets.push({
            label: `_p${p.id}`,
            data: g.ages.map((age, i) => ({ x: age, y: p.trajectory[i] })),
            borderColor: hl ? color : color + (hasHighlight ? '20' : '40'),
            backgroundColor: 'transparent',
            borderWidth: hl ? 3 : 1, pointRadius: hl ? 3 : 0, tension: 0.3, fill: false,
            order: hl ? 0 : 2,
            _playerMeta: { id: p.id, grade, ptype: p.ptype },
          });
        }
      }
    }

    for (const grade of grades) {
      const g = gd[grade];
      const color = gradeColor(grade);
      datasets.push({
        label: grade,
        data: g.ages.map((age, i) => ({ x: age, y: g.avg[i] })),
        borderColor: showPlayers ? color + '30' : color,
        backgroundColor: showPlayers ? color + '30' : color,
        borderWidth: showPlayers ? 1.5 : 2.5, pointRadius: showPlayers ? 0 : 2, tension: 0.3, fill: false,
        order: showPlayers ? 3 : 1,
      });
      if (showBands) {
        datasets.push({
          label: `_${grade}_upper`, data: g.ages.map((age, i) => ({ x: age, y: g.p90[i] })),
          borderColor: 'transparent', backgroundColor: showPlayers ? color + '08' : color + '18',
          borderWidth: 0, pointRadius: 0, fill: '+1', showLine: true, order: showPlayers ? 4 : 3,
        });
        datasets.push({
          label: `_${grade}_lower`, data: g.ages.map((age, i) => ({ x: age, y: g.p10[i] })),
          borderColor: 'transparent', backgroundColor: 'transparent',
          borderWidth: 0, pointRadius: 0, fill: false, showLine: true, order: showPlayers ? 4 : 3,
        });
      }
    }

    if (chart) { chart.destroy(); chart = null; }
    chart = mountChart(q(el, '#sb-chart'), {
      type: 'line',
      data: { datasets },
      options: {
        animation: { duration: 0 },
        interaction: { mode: 'nearest', intersect: false },
        scales: {
          x: { type: 'linear', title: { display: true, text: 'Age' }, ticks: { stepSize: 1 } },
          y: { title: { display: true, text: 'Base value' } },
        },
        plugins: {
          legend: { labels: { filter: item => !item.text.startsWith('_') } },
          tooltip: {
            filter: item => !String(item.dataset.label || '').startsWith('_'),
            callbacks: {
              afterBody(items) {
                const ds = items[0] && items[0].dataset;
                return ds && ds._playerMeta ? `Player ${ds._playerMeta.id} | ${ds._playerMeta.grade} ${ds._playerMeta.ptype}` : '';
              },
            },
          },
        },
        onClick(_evt, elements, c) {
          if (!elements.length) return;
          const ds = c.data.datasets[elements[0].datasetIndex];
          if (ds && ds._playerMeta) { hlSel.value = String(ds._playerMeta.id); render(); }
        },
      },
    }, ctx.signal);

    summary.setRows(grades.map(grade => {
      const g = gd[grade];
      let best = -Infinity, worst = Infinity;
      for (const p of g.players || []) {
        const peak = Math.max(...p.trajectory);
        if (peak > best) best = peak;
        if (peak < worst) worst = peak;
      }
      return {
        grade, count: g.count,
        finalAvg: g.avg[g.avg.length - 1], peakAvg: Math.max(...g.avg),
        best: best > -Infinity ? best : null, worst: worst < Infinity ? worst : null,
      };
    }));
  }

  on(abilitySel, 'change', () => { populateGradeFilter(); render(); }, ctx.signal);
  on(bandsChk, 'change', render, ctx.signal);
  on(playersChk, 'change', () => {
    const s = playersChk.checked;
    show(q(el, '#sb-grade-wrap'), s);
    show(q(el, '#sb-hl-wrap'), s);
    if (s) populateGradeFilter();
    render();
  }, ctx.signal);
  on(gradeSel, 'change', () => { populateHighlight(); render(); }, ctx.signal);
  on(hlSel, 'change', render, ctx.signal);

  busyButton(q(el, '#btn-run'), async () => {
    const f = readForm(q(el, '.card'));
    const body = { count: f.count || 200, seasons: f.seasons || 20, start_age: f.start_age || 15, player_type: f.player_type || 'Both' };
    setStatus(status, `Simulating ${body.count} players over ${body.seasons} seasons…`);
    show(q(el, '#sb-chart-card'), false);
    show(q(el, '#sb-summary-card'), false);
    try {
      data = await api.post(adm('/progression-sandbox'), body, { signal: ctx.signal });
      setStatus(status, `Simulation complete — ${data.config.count} players, ${data.config.seasons} seasons.`, 'success');
      fillSelect(abilitySel, (data.tracked_abilities || []).map(a => ({ value: a, label: a })));
      gradeSel.innerHTML = '';
      populateGradeFilter();
      show(q(el, '#sb-chart-card'), true);
      show(q(el, '#sb-summary-card'), true);
      render();
      toast.success('Sandbox run complete');
    } catch (e) {
      if (e.name === 'AbortError') return;
      setStatus(status, `Error: ${e.message}`, 'danger');
    }
  });
}
