// ui/task-runner.js — one way to start a long operation and watch it.
//
//   // Poll a background task (games/tasks/{id}) until complete/failed:
//   const task = await pollTask(id, { signal, onProgress: t => ... });
//
//   // A progress widget bound to a container:
//   const p = progressWidget(el);  p.start('Running…', total);  p.update(n, total, 'text');  p.done(); p.fail(msg);
//
//   // Start + track in one go, from any button:
//   await runTracked({ el, label: 'Run season', start: () => api.post(...), signal, onDone(task) });
//   `start` may resolve to {task_id,...} (polled), {run_id} (polled via /admin/jobs/runs), or a plain
//   result (shown immediately).

import { api, v1, adm } from '../core/api.js';
import { esc } from '../core/html.js';
import { normStatus } from '../core/constants.js';
import { json } from '../core/format.js';

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    if (signal) signal.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')); }, { once: true });
  });
}

const TERMINAL_TASK = new Set(['complete', 'failed']);
const TERMINAL_RUN = new Set(['succeeded', 'failed', 'skipped', 'cancelled']);

export async function pollTask(taskId, { signal, interval = 2500, onProgress, includeResult = true } = {}) {
  for (;;) {
    const t = await api.get(v1(`/games/tasks/${taskId}`), { signal, quiet: true, params: includeResult ? { include_result: 'true' } : undefined });
    t.status = normStatus(t.status);
    if (onProgress) onProgress(t);
    if (TERMINAL_TASK.has(t.status)) return t;
    await sleep(interval, signal);
  }
}

export async function pollRun(runId, { signal, interval = 2500, onProgress } = {}) {
  for (;;) {
    const r = await api.get(adm(`/jobs/runs/${runId}`), { signal, quiet: true });
    const run = r.run || r;
    run.status = normStatus(run.status);
    if (onProgress) onProgress(run);
    if (TERMINAL_RUN.has(run.status)) return run;
    await sleep(interval, signal);
  }
}

export function progressWidget(el, { showResult = true } = {}) {
  el.classList.add('progress-widget');
  el.innerHTML = `
    <div class="progress-head"><span class="progress-label"></span><span class="progress-status text-muted"></span></div>
    <div class="progress-container"><div class="progress-fill"></div><span class="progress-text"></span></div>
    <pre class="result-box progress-result" style="display:none"></pre>`;
  const label = el.querySelector('.progress-label');
  const status = el.querySelector('.progress-status');
  const fill = el.querySelector('.progress-fill');
  const text = el.querySelector('.progress-text');
  const result = el.querySelector('.progress-result');
  el.style.display = 'none';

  const w = {
    el,
    start(lbl = 'Working…', total = 0) {
      el.style.display = '';
      el.classList.remove('is-done', 'is-failed');
      label.textContent = lbl;
      status.textContent = '';
      fill.style.width = total ? '0%' : '100%';
      fill.classList.toggle('indeterminate', !total);
      text.textContent = total ? `0 / ${total}` : '';
      result.style.display = 'none';
      result.textContent = '';
    },
    update(progress, total, msg) {
      if (total) {
        fill.classList.remove('indeterminate');
        const pct = Math.max(0, Math.min(100, Math.round((progress / total) * 100)));
        fill.style.width = `${pct}%`;
        text.textContent = msg || `${progress} / ${total}`;
      } else if (msg) {
        text.textContent = msg;
      }
    },
    status(msg) { status.textContent = msg || ''; },
    done(data, msg = 'Done') {
      el.classList.add('is-done');
      fill.classList.remove('indeterminate');
      fill.style.width = '100%';
      status.textContent = msg;
      if (showResult && data !== undefined) { result.style.display = ''; result.textContent = typeof data === 'string' ? data : json(data); }
    },
    fail(err, data) {
      el.classList.add('is-failed');
      fill.classList.remove('indeterminate');
      status.textContent = 'Failed';
      result.style.display = '';
      result.textContent = `${esc(err && err.message ? err.message : String(err))}${data ? '\n\n' + (typeof data === 'string' ? data : json(data)) : ''}`;
    },
    hide() { el.style.display = 'none'; },
    show() { el.style.display = ''; },
  };
  return w;
}

function taskProgressText(t) {
  const meta = t.metadata || {};
  const bits = [];
  if (t.total) bits.push(`${t.progress || 0} / ${t.total}`);
  if (meta.current) bits.push(String(meta.current));
  if (meta.message) bits.push(String(meta.message));
  return bits.join(' · ');
}

/**
 * Start an operation and render its progress into `el` (a progressWidget container).
 * Returns the final task/run/result, or throws.
 */
export async function runTracked({ el, label = 'Running…', start, signal, onDone, onFail, total = 0, widget } = {}) {
  const w = widget || progressWidget(el);
  w.start(label, total);
  let res;
  try {
    res = await start();
  } catch (e) {
    w.fail(e, e && e.body);
    if (onFail) onFail(e);
    throw e;
  }
  try {
    if (res && res.task_id) {
      const t = await pollTask(res.task_id, {
        signal,
        onProgress: (t) => w.update(t.progress || 0, t.total || res.total || total, taskProgressText(t)),
      });
      if (t.status === 'failed') {
        const e = new Error(t.error || 'Task failed');
        w.fail(e, t);
        if (onFail) onFail(e, t);
        throw e;
      }
      w.done(t.result !== undefined ? t.result : t, 'Complete');
      if (onDone) onDone(t);
      return t;
    }
    if (res && res.run_id) {
      const run = await pollRun(res.run_id, {
        signal,
        onProgress: (r) => {
          w.update(r.progress || 0, r.total || 0, r.status === 'queued' ? 'Queued — waiting for the scheduler to pick it up' : (r.stage || ''));
        },
      });
      if (run.status === 'failed') {
        const e = new Error(run.error || 'Job failed');
        w.fail(e, run.summary || run);
        if (onFail) onFail(e, run);
        throw e;
      }
      w.done(run.summary !== undefined && run.summary !== null ? run.summary : run, run.status === 'skipped' ? `Skipped: ${run.skip_reason || ''}` : 'Complete');
      if (onDone) onDone(run);
      return run;
    }
    w.done(res, 'Complete');
    if (onDone) onDone(res);
    return res;
  } catch (e) {
    if (e && e.name === 'AbortError') throw e;
    if (!el.classList.contains('is-failed')) w.fail(e, e && e.body);
    throw e;
  }
}

/** Bind a button so it disables itself while an async handler runs. */
export function busyButton(btn, handler) {
  btn.addEventListener('click', async (e) => {
    if (btn.disabled) return;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.classList.add('is-busy');
    try { await handler(e); } finally {
      btn.disabled = false;
      btn.classList.remove('is-busy');
      btn.textContent = orig;
    }
  });
}
