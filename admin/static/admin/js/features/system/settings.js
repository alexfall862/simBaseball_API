// features/system/settings.js — session, admin password header, write mode, scheduler switch.

import { api, adm, getAdminPassword, setAdminPassword } from '../../core/api.js';
import { html, raw, setHtml, delegate, q } from '../../core/html.js';
import { store, prefs } from '../../core/store.js';
import { kvTable } from '../../ui/table.js';
import { field, formGrid, readForm } from '../../ui/form.js';
import { toast } from '../../ui/toast.js';
import { refreshSummary } from '../../main.js';

export async function mount(el, ctx) {
  const me = await api.get(adm('/me'));
  setHtml(el, html`
    <div class="grid-2">
      <div class="card">
        <h3>Session</h3>
        ${raw(kvTable([['Admin session', me.admin ? 'yes' : 'no'], ['Write mode', me.write_mode ? 'ON' : 'off'], ['Cookie secure', String(me.secure)], ['SameSite', String(me.samesite)], ['Asset version', window.ADMIN_ASSET_V || '']]))}
        <div class="mt-2 row">
          <label class="checkbox-label"><input type="checkbox" id="write-mode" ${me.write_mode ? 'checked' : ''} /> <span>Write mode (destructive SQL console statements)</span></label>
        </div>
      </div>
      <div class="card">
        <h3>Admin password header</h3>
        <p class="text-muted small mb-2">A few endpoints (books, playoff revenue, seeding) authenticate with <code>X-Admin-Password</code> instead of the session. The value is kept in this tab's sessionStorage only. It is filled automatically at login.</p>
        ${raw(formGrid([field.password('pw', 'Password', { value: getAdminPassword() ? '••••••••' : '' })]))}
        <div class="button-group"><button class="btn btn-primary" data-action="save-pw">Save</button><button class="btn btn-secondary" data-action="clear-pw">Clear</button></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <h3>Scheduler</h3>
        <p class="text-muted small mb-2">Global switch for scheduled jobs (<code>timestamp_state.run_cron</code>). Manual runs are unaffected.</p>
        <label class="checkbox-label"><input type="checkbox" id="sched" /> <span>Scheduler enabled</span></label>
        <div class="mt-2"><a class="btn btn-sm btn-ghost" href="#/jobs/scheduled">Manage jobs</a></div>
      </div>
      <div class="card">
        <h3>Interface</h3>
        <div class="button-group">
          <button class="btn btn-secondary" data-action="reset-prefs">Reset remembered selections</button>
          <a class="btn btn-ghost" href="/admin/legacy" target="_blank" rel="noopener">Open legacy UI</a>
        </div>
      </div>
    </div>`);

  store.watch('summary', (s) => { const cb = q(el, '#sched'); if (cb && s && s.scheduler) cb.checked = !!s.scheduler.enabled; }, ctx.signal);

  q(el, '#write-mode').addEventListener('change', async (e) => {
    try { const r = await api.post(adm('/write-mode'), { enabled: e.target.checked }); toast.success(r.write_mode ? 'Write mode ON' : 'Write mode off'); store.set({ auth: { ...store.get().auth, writeMode: !!r.write_mode } }); }
    catch (_) { e.target.checked = !e.target.checked; }
  }, { signal: ctx.signal });
  q(el, '#sched').addEventListener('change', async (e) => {
    try { await api.post(adm('/scheduler/toggle'), { enabled: e.target.checked }); toast.success(e.target.checked ? 'Scheduler enabled' : 'Scheduler disabled'); refreshSummary(); }
    catch (_) { e.target.checked = !e.target.checked; }
  }, { signal: ctx.signal });

  delegate(el, 'click', '[data-action]', (e, btn) => {
    const a = btn.dataset.action;
    if (a === 'save-pw') { const v = readForm(el).pw; if (v && v !== '••••••••') { setAdminPassword(v); toast.success('Saved for this session'); } }
    if (a === 'clear-pw') { setAdminPassword(''); q(el, '[name="pw"]').value = ''; toast.info('Cleared'); }
    if (a === 'reset-prefs') { try { Object.keys(localStorage).filter(k => k.startsWith('simbb_admin:')).forEach(k => localStorage.removeItem(k)); } catch (_) { /* ignore */ } toast.success('Preferences reset'); }
  }, ctx.signal);
}
