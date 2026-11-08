// features/engine/progress.js — batch + single player progression (port of legacy #section-pe-progress).

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, q } from '../../core/html.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { progressWidget, runTracked, busyButton } from '../../ui/task-runner.js';
import { setStatus } from './_shared.js';

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card danger-zone">
      <div class="card-head">
        <div><h3>Batch progression</h3><p class="card-sub text-muted">Progress every player in the database by one year. End-season already does this (with snapshots and a displayovr refresh); run it here only for testing or recovery.</p></div>
      </div>
      <div class="alert alert-warning">Major operation: ages and re-rolls ~30k players in one transaction. It does not write rating snapshots, so the Progression Diagnostics tab will not see this pass.</div>
      ${raw(formGrid([
        field.number('max_age', 'Max age', { value: 45, min: 16, max: 60, help: 'Players older than this are skipped. Leave empty to age everyone (players past the growth table only age).' }),
      ]))}
      <div class="button-group"><button class="btn btn-danger" id="btn-all">Progress all players</button></div>
      <div class="mt-1" id="all-progress"></div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h3>Single player progression</h3><p class="card-sub text-muted">Progress one player by one year. Useful to test a growth-curve change on a known player.</p></div>
      </div>
      ${raw(formGrid([
        field.number('player_id', 'Player ID', { placeholder: 'e.g. 42', min: 1 }),
      ]))}
      <div class="button-group"><button class="btn btn-secondary" id="btn-one">Progress player</button></div>
      <div class="mt-1" id="one-status"></div>
      <pre class="result-box mt-1" id="one-result" style="display:none"></pre>
    </div>`);

  const allWidget = progressWidget(q(el, '#all-progress'), { showResult: true });

  busyButton(q(el, '#btn-all'), async () => {
    const f = readForm(el);
    const maxAge = f.max_age;
    const ok = await confirm({
      title: 'Progress ALL players?',
      danger: true,
      typeToConfirm: 'PROGRESS',
      confirmLabel: 'Progress all',
      message: maxAge != null
        ? `Every player aged under ${maxAge} is progressed by one year. This may take a minute or more.`
        : 'Every player is progressed by one year (no age cap). This may take a minute or more.',
    });
    if (!ok) return;
    const body = maxAge != null ? { max_age: maxAge } : {};
    try {
      await runTracked({
        el: q(el, '#all-progress'), widget: allWidget, label: 'Running batch progression…', signal: ctx.signal,
        start: () => api.post(v1('/player-ops/progress-all'), body, { signal: ctx.signal }),
        onDone: (r) => toast.success(`Progressed ${r && r.progressed != null ? r.progressed : '?'} player(s)`),
      });
    } catch (e) { /* widget + api layer already reported */ }
  });

  busyButton(q(el, '#btn-one'), async () => {
    const f = readForm(el);
    const pid = f.player_id;
    const status = q(el, '#one-status');
    const result = q(el, '#one-result');
    result.style.display = 'none';
    if (!pid || pid < 1) { setStatus(status, 'Enter a valid player ID.', 'warning'); return; }
    setStatus(status, `Progressing player ${pid}…`);
    try {
      const data = await api.post(v1(`/player-ops/progress/${pid}`), {}, { signal: ctx.signal });
      setStatus(status, `Player ${data.player_id ?? pid} progressed successfully.`, 'success');
      result.style.display = '';
      result.textContent = JSON.stringify(data, null, 2);
      toast.success(`Player ${data.player_id ?? pid} progressed`);
    } catch (e) {
      if (e.name === 'AbortError') return;
      setStatus(status, `Error: ${e.message}`, 'danger');
    }
  });
}
