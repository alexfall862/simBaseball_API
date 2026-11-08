// features/season/playoffs.js — Playoffs (port of legacy #section-playoffs).
//
// Bracket lifecycle per league year + level: preview/edit the field, generate,
// process results, advance rounds, health check, wipe. College (level 3) adds
// conference tournaments and the manual 64-team NCAA field editor. MLB adds the
// World Series home-field rule. Levels 5-9 expose a per-round matchup editor.
// Bracket PNG export is drawn client-side from /playoffs/bracket-skeleton.
//
// Stamina rest (legacy "Rest Week" button) lives on the Simulate tab; this tab
// links to it instead of duplicating the form.

import { api, v1 } from '../../core/api.js';
import { html, raw, setHtml, delegate, q, esc } from '../../core/html.js';
import { SIM_LEVELS, levelName } from '../../core/constants.js';
import { badge, alertBox } from '../../ui/badge.js';
import { confirm } from '../../ui/modal.js';
import { toast } from '../../ui/toast.js';
import { leagueYearSelect, levelSelect } from '../../ui/selectors.js';
import * as B from './_playoffs_bracket.js';
import * as E from './_playoffs_editors.js';

const BANNER_KIND = { simulate: 'warning', advance: 'info', complete: 'success', none: 'info' };

export async function mount(el, ctx) {
  setHtml(el, html`
    <div class="card">
      <div class="card-head">
        <div><h3>Playoffs</h3><p class="card-sub text-muted">Generate and run the postseason for one level at a time. Games are simulated from the <a href="#/season/simulate">Simulate</a> tab; come back here to process results and advance rounds.</p></div>
        <div class="row">
          <select id="po-ly" title="League year"></select>
          <select id="po-level" title="League level"></select>
          <button class="btn btn-sm btn-secondary" data-action="refresh">Refresh</button>
        </div>
      </div>
      <div class="button-group">
        <button class="btn btn-secondary" data-action="preview" id="btn-po-preview">Preview / Edit Field</button>
        <button class="btn btn-primary" data-action="generate">Generate Bracket</button>
        <button class="btn btn-secondary" data-action="process">Process Results</button>
        <button class="btn btn-secondary" data-action="advance">Advance Round</button>
        <button class="btn btn-primary" data-action="procadv">Process &amp; Advance</button>
        <button class="btn btn-secondary" data-action="health">Health Check</button>
        <a class="btn btn-ghost" href="#/season/simulate" title="Apply rest-only stamina recovery to every roster at this level (Simulate tab → Stamina rest)">Rest Week (Stamina) →</a>
        <button class="btn btn-danger" data-action="wipe">Wipe Playoffs</button>
      </div>
      <div id="ct-controls" class="mt-1" hidden>
        <div class="button-group">
          <button class="btn btn-secondary" data-action="ct-preview">Preview / Edit Conf Seeds</button>
          <button class="btn btn-primary" data-action="ct-generate">Generate Conf Tournaments</button>
          <button class="btn btn-secondary" data-action="ct-advance">Advance Conf Tournaments</button>
          <button class="btn btn-danger" data-action="ct-wipe">Wipe Conf Tournaments</button>
        </div>
      </div>
      <div id="po-ws" class="mt-1" hidden>
        <div class="form-row mb-0">
          <div class="form-group"><label for="po-ws-home">World Series home field</label>
            <select id="po-ws-home"><option value="seed">Better seed</option><option value="allstar">All-Star Game winner</option></select></div>
          <button class="btn btn-secondary" data-action="ws-save">Save Rule</button>
          <span id="po-ws-info" class="text-muted small"></span>
        </div>
      </div>
      <div id="po-banner" class="mt-2"></div>
      <div id="po-health" class="mt-1"></div>
      <div id="po-status" class="text-muted small mt-1"></div>
    </div>

    <div class="card" id="po-fieldedit-card" hidden>
      <div class="card-head"><div><h3>Edit Field &amp; Seeds</h3><p class="card-sub text-muted">Adjust seeds and swap teams, then generate the bracket from your edits. Seeds must be 1..N with no gaps or duplicates.</p></div></div>
      <div id="po-fieldedit"></div>
      <div class="button-group mt-2">
        <button class="btn btn-primary" data-action="fe-generate">Generate from Edited Field</button>
        <button class="btn btn-secondary" data-action="fe-resequence">Auto-resequence Seeds</button>
        <button class="btn btn-secondary" data-action="fe-reset">Reset to Computed</button>
        <button class="btn btn-ghost" data-action="fe-cancel">Cancel</button>
      </div>
      <div id="po-fieldedit-status" class="text-muted small mt-1"></div>
    </div>

    <div class="card" id="ct-fieldedit-card" hidden>
      <div class="card-head"><div><h3>Edit Conference Seeds</h3><p class="card-sub text-muted">Reorder seeds within each conference, then generate. All teams qualify; seeds must be 1..N per conference.</p></div></div>
      <div id="ct-fieldedit"></div>
      <div class="button-group mt-2">
        <button class="btn btn-primary" data-action="ct-fe-generate">Generate from Edited Seeds</button>
        <button class="btn btn-secondary" data-action="ct-fe-resequence">Auto-resequence Seeds</button>
        <button class="btn btn-secondary" data-action="ct-fe-reset">Reset to Computed</button>
        <button class="btn btn-ghost" data-action="ct-fe-cancel">Cancel</button>
      </div>
      <div id="ct-fieldedit-status" class="text-muted small mt-1"></div>
    </div>

    <div class="card" id="ncaa-editor-card" hidden>
      <div class="card-head">
        <div><h3>Manual CWS Field (64 Teams)</h3><p class="card-sub text-muted">Assign conference champions and a ranking metric, click <strong>Suggest Field</strong> to auto-build the 64-team bracket, then fine-tune any slot. The 16 regionals below are exactly what gets generated.</p></div>
        <button class="btn btn-sm btn-ghost" data-action="ncaa-close">Close</button>
      </div>
      <div class="form-row">
        <div class="form-group"><label for="ncaa-ranking">Rank / suggest by</label>
          <select id="ncaa-ranking"><option value="elo">ELO</option><option value="power">Power Ranking</option><option value="record">Record (win %)</option></select></div>
        <button class="btn btn-secondary" data-action="ncaa-suggest">Suggest Field</button>
        <button class="btn btn-primary" data-action="ncaa-generate">Generate Bracket from This Field</button>
        <span id="ncaa-editor-status" class="text-muted small"></span>
      </div>
      <details class="mb-1"><summary><strong>Conference Champions (auto-bids)</strong></summary>
        <p class="text-muted small mt-1 mb-1">Each conference's champion gets an automatic bid. Change them, then click <strong>Suggest Field</strong> to rebuild.</p>
        <div id="ncaa-champs"></div>
      </details>
      <div id="ncaa-field"></div>
    </div>

    <div class="card" id="po-field-card" hidden><h3>Playoff Field</h3><div id="po-field"></div></div>

    <div class="card" id="ct-bracket-card" hidden>
      <div class="card-head"><h3>Conference Tournaments</h3><button class="btn btn-sm btn-secondary" data-action="png-all">Download All PNGs</button></div>
      <div id="ct-bracket"></div>
    </div>

    <div class="card" id="po-pending-card" hidden>
      <div class="card-head"><div><h3>Pending Games</h3><p class="card-sub text-muted">Scheduled playoff games without a result. Move a game to another week/subweek if the schedule needs adjusting.</p></div></div>
      <div id="po-pending"></div>
    </div>

    <div class="card" id="po-matchups-card" hidden>
      <div class="card-head">
        <div><h3>Adjust Matchups</h3><p class="card-sub text-muted">Rewrite the pairings of series that have not started. Team A hosts game 1. Saving deletes the unplayed game 1 rows of any changed series and re-creates them.</p></div>
        <div class="button-group"><button class="btn btn-sm btn-secondary" data-action="mu-reset">Reset</button><button class="btn btn-sm btn-warning" data-action="mu-save">Save Matchups</button></div>
      </div>
      <div id="po-matchups"></div>
      <div id="po-matchups-status" class="text-muted small mt-1"></div>
    </div>

    <div class="card" id="po-bracket-card" hidden>
      <div class="card-head"><h3>Bracket</h3><button class="btn btn-sm btn-secondary" data-action="png-main">Download PNG</button></div>
      <div id="po-bracket"></div>
    </div>`);

  // ------------------------------------------------------------ state
  const st = { skeleton: null, fieldEdit: null, ctEdit: null, ncaa: null, matchup: null };
  const sig = ctx.signal;
  const $ = (id) => q(el, `#${id}`);
  const show = (id, visible) => { const c = $(id); if (c) c.hidden = !visible; };
  const setStatus = (msg) => { $('po-status').textContent = msg || ''; };
  const setText = (id, msg) => { const n = $(id); if (n) n.textContent = msg || ''; };

  let ly = null;   // assigned once league years load; guarded below
  const lvl = levelSelect($('po-level'), {
    levels: SIM_LEVELS, value: ctx.params.level ?? null, remember: 'playoffs', signal: sig,
    onChange: (v) => { if (ctx.setParams) ctx.setParams({ level: v }); onLevelChange(); },
  });
  ly = await leagueYearSelect($('po-ly'), { signal: sig, onChange: () => onLevelChange() });
  const cur = () => ({ lyid: ly ? ly.get() : null, level: lvl.get() });
  const levelLabel = () => `${levelName(lvl.get())} (${lvl.get()})`;
  const idBody = () => ({ league_year_id: Number(ly.get()), league_level: Number(lvl.get()) });

  // ------------------------------------------------------------ loaders
  async function loadStatus(lyid, level) {
    const banner = $('po-banner');
    try {
      const d = await api.get(v1(`/playoffs/status/${lyid}/${level}`), { signal: sig, quiet: true });
      if (!d.has_bracket) { setHtml(banner, ''); return; }
      setHtml(banner, raw(alertBox(BANNER_KIND[d.next_action] || 'info', d.message, { title: `${d.complete_series}/${d.total_series} series complete ·` })));
    } catch (_) { setHtml(banner, ''); }
  }

  async function loadWsHomeField(lyid, level) {
    if (String(level) !== '9') { show('po-ws', false); return; }
    try {
      const d = await api.get(v1('/playoffs/settings/9'), { params: { league_year_id: lyid }, signal: sig, quiet: true });
      $('po-ws-home').value = d.ws_home_field || 'seed';
      setText('po-ws-info', wsHomeInfoText(d));
      show('po-ws', true);
    } catch (_) { show('po-ws', false); }
  }

  async function loadMatchups(lyid, level) {
    st.matchup = null;
    try {
      const d = await api.get(v1(`/playoffs/matchups/${lyid}/${level}`), { signal: sig, quiet: true });
      const rounds = (d.rounds || []).filter(r => r.series.some(s => s.editable));
      if (!d.supported || !rounds.length) { show('po-matchups-card', false); return; }
      const rnd = rounds[rounds.length - 1];   // latest round with an unplayed series
      st.matchup = { lyid, level, round: rnd.round, series: rnd.series, pool: d.pool || [] };
      setHtml($('po-matchups'), raw(E.renderMatchupEditor(st.matchup)));
      setText('po-matchups-status', '');
      show('po-matchups-card', true);
    } catch (_) { show('po-matchups-card', false); }
  }

  async function loadSkeleton(lyid, level) {
    st.skeleton = null;
    try {
      st.skeleton = await api.get(v1(`/playoffs/bracket-skeleton/${lyid}/${level}`), { signal: sig, quiet: true });
    } catch (_) { st.skeleton = null; }
    return st.skeleton;
  }

  async function loadBracket(lyid, level) {
    loadStatus(lyid, level);
    loadMatchups(lyid, level);
    loadWsHomeField(lyid, level);
    loadSkeleton(lyid, level);
    let data;
    try {
      data = await api.get(v1(`/playoffs/bracket/${lyid}/${level}`), { signal: sig, quiet: true });
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      show('po-bracket-card', false); show('ct-bracket-card', false);
      setStatus(`Bracket load failed: ${e.message}`);
      return;
    }
    // Conference tournaments (college only)
    if (data.conf_tournaments && Object.keys(data.conf_tournaments).length) {
      setHtml($('ct-bracket'), raw(B.renderConfTournaments(data.conf_tournaments)));
      show('ct-bracket-card', true);
    } else {
      show('ct-bracket-card', false);
    }
    // NCAA 64-team stages
    if (String(level) === '3' && data.ncaa) {
      setHtml($('po-bracket'), raw(B.renderNcaaBracket(data.ncaa)));
      show('po-bracket-card', true);
      return;
    }
    if (!data.rounds || !Object.keys(data.rounds).length) { show('po-bracket-card', false); return; }
    setHtml($('po-bracket'), raw(B.renderMainBracket(data)));
    show('po-bracket-card', true);
  }

  async function loadPending(lyid, level) {
    let d;
    try { d = await api.get(v1(`/playoffs/pending-games/${lyid}/${level}`), { signal: sig, quiet: true }); }
    catch (_) { show('po-pending-card', false); return; }
    const games = d.games || [];
    if (!games.length) { show('po-pending-card', false); return; }
    const rows = games.map(g => {
      const subOpts = ['a', 'b', 'c', 'd'].map(s => `<option value="${s}"${s === g.season_subweek ? ' selected' : ''}>${s}</option>`).join('');
      return `<tr data-gid="${esc(g.game_id)}"><td>${esc(g.game_id)}</td><td>${esc(g.round)}</td><td>${esc(g.away_abbrev)} @ ${esc(g.home_abbrev)}</td>
        <td class="nowrap">${esc(g.wins_a)}-${esc(g.wins_b)} (Bo${esc(g.series_length)})</td>
        <td class="nowrap"><span class="row">wk <input type="number" min="1" class="resched-week" value="${esc(g.season_week)}" style="width:72px"> <select class="resched-sub">${subOpts}</select>
          <button class="btn btn-sm btn-secondary" data-action="resched" data-gid="${esc(g.game_id)}">Move</button></span></td></tr>`;
    }).join('');
    setHtml($('po-pending'), raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th>Game ID</th><th>Round</th><th>Matchup</th><th>Series</th><th>Reschedule</th></tr></thead><tbody>${rows}</tbody></table></div>`));
    show('po-pending-card', true);
  }

  async function reload() {
    const { lyid, level } = cur();
    if (!lyid || !level) return;
    await Promise.all([loadBracket(lyid, level), loadPending(lyid, level)]);
  }

  function onLevelChange() {
    const level = lvl.get();
    show('ct-controls', String(level) === '3');
    $('btn-po-preview').textContent = String(level) === '3' ? 'Set CWS Field Manually' : 'Preview / Edit Field';
    ['po-fieldedit-card', 'ct-fieldedit-card', 'po-field-card', 'ncaa-editor-card'].forEach(id => show(id, false));
    setHtml($('po-banner'), ''); setHtml($('po-health'), ''); setStatus('');
    st.fieldEdit = null; st.ctEdit = null; st.ncaa = null;
    reload();
  }

  // ------------------------------------------------------------ actions
  async function withSkeleton() {
    if (st.skeleton && st.skeleton.brackets) return st.skeleton;
    const { lyid, level } = cur();
    const sk = await loadSkeleton(lyid, level);
    if (!sk || !sk.brackets) toast.warn('Could not load the bracket skeleton — generate a bracket first.');
    return sk;
  }

  async function exportMainPng() {
    const sk = await withSkeleton(); if (!sk) return;
    const level = lvl.get();
    if (String(level) === '3') {
      const ncaa = (sk.brackets || []).filter(b => b.key.startsWith('REG') || ['SUPER', 'MCWS_A', 'MCWS_B', 'FINAL'].includes(b.key));
      if (!ncaa.length) { toast.warn('No bracket to export yet — generate the bracket first.'); return; }
      B.downloadStaggered(ncaa.map(b => B.renderSkeletonBracket(b, level)));
      toast.info(`Downloading ${ncaa.length} bracket image(s)…`);
      return;
    }
    const main = (sk.brackets || []).find(b => b.key === 'main');
    if (!main) { toast.warn('No bracket to export yet — generate the bracket first.'); return; }
    const out = B.renderSkeletonBracket(main, level);
    B.downloadCanvasPng(out.canvas, out.filename);
  }

  async function exportConfPng(conf) {
    const sk = await withSkeleton(); if (!sk) return;
    const b = (sk.brackets || []).find(x => x.key === conf);
    if (!b) { toast.warn(`No bracket data for ${conf}`); return; }
    const out = B.renderSkeletonBracket(b, lvl.get());
    B.downloadCanvasPng(out.canvas, out.filename);
  }

  async function exportAllPngs() {
    const sk = await withSkeleton(); if (!sk) return;
    const brackets = sk.brackets || [];
    if (!brackets.length) { toast.warn('No brackets to export yet — generate the bracket first.'); return; }
    B.downloadStaggered(brackets.map(b => B.renderSkeletonBracket(b, lvl.get())));
    toast.info(`Downloading ${brackets.length} bracket image(s)…`);
  }

  async function openFieldEditor() {
    const { lyid, level } = cur();
    if (String(level) === '3') { setStatus(''); await openNcaaEditor(); return; }
    setStatus('Loading field…');
    const data = await api.get(v1(`/playoffs/field/${lyid}/${level}`), { signal: sig });
    setStatus('');
    if (data.format === 'ncaa') {   // read-only server-computed field
      st.fieldEdit = null; show('po-fieldedit-card', false);
      setHtml($('po-field'), raw(B.renderNcaaField(data.field))); show('po-field-card', true);
      return;
    }
    st.fieldEdit = { format: data.format, level: Number(level), pool: data.pool || [] };
    setHtml($('po-fieldedit'), raw(E.renderFieldEditor(data)));
    setText('po-fieldedit-status', '');
    show('po-fieldedit-card', true);
  }

  async function generateFromEditedField() {
    if (!st.fieldEdit) return;
    const res = E.collectField($('po-fieldedit'), st.fieldEdit);
    if (res.error) { setText('po-fieldedit-status', res.error); return; }
    setText('po-fieldedit-status', 'Generating…');
    try {
      const d = await api.post(v1('/playoffs/generate'), { league_year_id: Number(ly.get()), league_level: st.fieldEdit.level, field: res.field });
      setText('po-fieldedit-status', `Created ${(d.series_created || []).length} series`);
      toast.success(`Bracket generated: ${(d.series_created || []).length} series`);
      show('po-fieldedit-card', false); st.fieldEdit = null;
      await reload();
    } catch (e) { setText('po-fieldedit-status', `Error: ${e.message}`); }
  }

  async function openConfSeedEditor() {
    setStatus('Loading conference fields…');
    const d = await api.get(v1(`/playoffs/conf-tournaments/field/${ly.get()}`), { signal: sig });
    setStatus('');
    st.ctEdit = { fields: d.fields || {} };
    setHtml($('ct-fieldedit'), raw(E.renderConfSeedEditor(d.fields)));
    setText('ct-fieldedit-status', '');
    show('ct-fieldedit-card', true);
  }

  async function generateConfFromEdited() {
    if (!st.ctEdit) return;
    const res = E.collectConfSeeds($('ct-fieldedit'));
    if (res.error) { setText('ct-fieldedit-status', res.error); return; }
    setText('ct-fieldedit-status', 'Generating…');
    try {
      const d = await api.post(v1('/playoffs/conf-tournaments/generate'), { league_year_id: Number(ly.get()), fields: res.fields });
      setText('ct-fieldedit-status', `Created ${d.total_series} series across ${(d.conferences || []).length} conferences`);
      toast.success(`Conference tournaments generated (${d.total_series} series)`);
      show('ct-fieldedit-card', false); st.ctEdit = null;
      await reload();
    } catch (e) { setText('ct-fieldedit-status', `Error: ${e.message}`); }
  }

  async function openNcaaEditor() {
    show('ncaa-editor-card', true);
    setHtml($('ncaa-champs'), '');
    setHtml($('ncaa-field'), '<p class="text-muted">Loading suggestion…</p>');
    await ncaaSuggest();
  }

  async function ncaaSuggest() {
    setText('ncaa-editor-status', 'Building suggestion…');
    try {
      const d = await api.post(v1('/playoffs/ncaa/suggest'), {
        league_year_id: Number(ly.get()), ranking: $('ncaa-ranking').value, champions: E.collectNcaaChampions($('ncaa-champs')),
      });
      setText('ncaa-editor-status', '');
      st.ncaa = { conferences: d.conferences, teamById: E.ncaaTeamIndex(d.conferences), optionsHtml: E.ncaaTeamOptions(d.conferences), ranking: d.ranking };
      setHtml($('ncaa-champs'), raw(E.renderNcaaChampions(d.field, d.conferences)));
      const fieldEl = $('ncaa-field');
      setHtml(fieldEl, raw(E.renderNcaaEditorField(d.field, st.ncaa.optionsHtml)));
      E.applyNcaaSlotValues(fieldEl, d.field);
      E.refreshNcaaMeta(fieldEl, st.ncaa.teamById);
      E.highlightNcaaDuplicates(fieldEl);
    } catch (e) { setText('ncaa-editor-status', `Error: ${e.message}`); }
  }

  async function ncaaGenerate() {
    const res = E.collectNcaaField($('ncaa-field'));
    if (res.error) { setText('ncaa-editor-status', res.error); return; }
    if (!await confirm({ title: 'Generate the CWS bracket from this 64-team field?', message: 'Wipe any existing College bracket first if one exists.' })) return;
    setText('ncaa-editor-status', 'Generating…');
    try {
      const d = await api.post(v1('/playoffs/generate'), { league_year_id: Number(ly.get()), league_level: 3, field: res.field });
      setText('ncaa-editor-status', `Created ${(d.series_created || []).length} regional games.`);
      toast.success(`NCAA bracket generated: ${(d.series_created || []).length} regional games`);
      show('ncaa-editor-card', false);
      await reload();
    } catch (e) { setText('ncaa-editor-status', `Error: ${e.message}`); }
  }

  async function saveMatchups() {
    const mu = st.matchup; if (!mu) return;
    const edits = E.collectMatchupEdits($('po-matchups'), mu);
    if (!edits.length) { setText('po-matchups-status', 'No changes to save.'); return; }
    const abbrev = id => (mu.pool.find(p => p.team_id === id) || {}).team_abbrev || id;
    const summary = edits.map(e => `${abbrev(e.team_a_id)} vs ${abbrev(e.team_b_id)}`).join(', ');
    if (!await confirm({ title: `Rewrite ${edits.length} ${mu.round} series?`, danger: true, confirmLabel: 'Save matchups',
      message: `${summary}\n\nUnplayed game 1 rows for these series will be deleted and re-created.` })) return;
    setText('po-matchups-status', 'Saving matchups…');
    try {
      const d = await api.post(v1('/playoffs/set-matchups'), { league_year_id: Number(mu.lyid), league_level: Number(mu.level), round: mu.round, matchups: edits });
      const parts = (d.updated || []).map(u => `${u.team_a.abbrev} (#${u.team_a.seed}) vs ${u.team_b.abbrev} (#${u.team_b.seed}) — G1 wk ${u.game_1.week}${u.game_1.subweek}`);
      setText('po-matchups-status', parts.length ? `Updated ${mu.round}: ${parts.join(' · ')}` : (d.message || 'Saved.'));
      toast.success('Matchups saved');
      await reload();
    } catch (e) { setText('po-matchups-status', `Error: ${e.message}`); }
  }

  async function healthCheck() {
    const { lyid, level } = cur();
    const div = $('po-health');
    setHtml(div, '<span class="text-muted small">Checking bracket health…</span>');
    try {
      const d = await api.get(v1(`/playoffs/health/${lyid}/${level}`), { signal: sig });
      if (d.ok) { setHtml(div, raw(alertBox('success', 'No bracket integrity issues found.'))); return; }
      const rows = (d.issues || []).map(i => `<tr><td>${badge(i.severity, i.severity === 'error' ? 'danger' : 'warning')}</td><td>${esc(i.message)}</td></tr>`).join('');
      setHtml(div, raw(`<div class="table-container"><table class="data-table compact"><thead><tr><th style="width:90px">Severity</th><th>Issue</th></tr></thead><tbody>${rows}</tbody></table></div>`));
    } catch (e) { setHtml(div, raw(alertBox('danger', e.message))); }
  }

  function summarizeProcAdv(d, level) {
    const parts = [`Processed ${d.processed} result(s)`];
    const adv = d.advanced || {};
    if (String(level) === '3') {
      if (adv.cws && adv.cws.status === 'complete') parts.push('CWS complete');
      else if (adv.cws && adv.cws.rounds_advanced && adv.cws.rounds_advanced.length) parts.push(`CWS → ${adv.cws.rounds_advanced.join(', ')}`);
      if (adv.conf && adv.conf.advanced && adv.conf.advanced.length) parts.push(`${adv.conf.advanced.length} conf(s) advanced`);
      if (adv.conf && adv.conf.completed && adv.conf.completed.length) parts.push(`${adv.conf.completed.length} conf(s) complete`);
    } else if (adv.status === 'complete') parts.push(adv.message || 'Complete');
    else if (adv.round_advanced) parts.push(`Advanced to ${adv.round_advanced}`);
    return parts.join(' · ');
  }

  /** Run a header action: status line while running, result text + toast after. */
  async function act(label, fn) {
    setStatus(label);
    try {
      const msg = await fn();
      if (msg) { setStatus(msg); toast.success(msg); }
      await reload();
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      setStatus(`Error: ${e.message}`);
    }
  }

  // ------------------------------------------------------------ wiring
  delegate(el, 'change', 'select.fe-team', (e, sel) => { if (st.fieldEdit) E.syncFieldRowRecord(sel, st.fieldEdit.pool); }, sig);
  delegate(el, 'change', '.ncaa-slot', () => { if (st.ncaa) { E.refreshNcaaMeta($('ncaa-field'), st.ncaa.teamById); E.highlightNcaaDuplicates($('ncaa-field')); } }, sig);
  delegate(el, 'change', '.po-mu-a, .po-mu-b', (e, sel) => E.syncMatchupSeed(sel), sig);

  delegate(el, 'click', '[data-action]', async (e, btn) => {
    const a = btn.dataset.action;
    const { lyid, level } = cur();
    if (!lyid) { toast.warn('Pick a league year first.'); return; }
    btn.disabled = true;
    try {
      switch (a) {
        case 'refresh': await reload(); break;
        case 'preview': await openFieldEditor(); break;
        case 'generate':
          await act('Generating bracket…', async () => {
            const d = await api.post(v1('/playoffs/generate'), idBody());
            if (d.field) {
              setHtml($('po-field'), raw(String(level) === '3' ? B.renderNcaaField(d.field) : B.renderPlayoffField(d.field)));
              show('po-field-card', true);
            }
            return `Created ${(d.series_created || []).length} series`;
          });
          break;
        case 'process':
          await act('Processing playoff results…', async () => {
            const d = await api.post(v1('/playoffs/process-results'), idBody());
            return `Processed ${d.processed} game result(s)`;
          });
          break;
        case 'advance':
          await act('Advancing round…', async () => {
            const d = await api.post(v1('/playoffs/advance'), idBody());
            return d.status === 'complete' ? d.message : `Advanced to ${d.round_advanced}`;
          });
          break;
        case 'procadv':
          await act('Processing results and advancing…', async () => summarizeProcAdv(await api.post(v1('/playoffs/process-and-advance'), idBody()), level));
          break;
        case 'health': await healthCheck(); break;
        case 'wipe':
          if (!await confirm({ title: `Wipe all playoff data for ${levelLabel()}?`, danger: true, typeToConfirm: 'WIPE', confirmLabel: 'Wipe',
            message: 'Deletes playoff series, games and results for this league year and level. Season stats are kept.' })) break;
          await act('Wiping playoffs…', async () => {
            const d = await api.post(v1('/playoffs/wipe'), idBody());
            const parts = [];
            if (d.playoff_series) parts.push(`${d.playoff_series} series`);
            if (d.gamelist) parts.push(`${d.gamelist} games`);
            if (d.game_results) parts.push(`${d.game_results} results`);
            ['po-bracket-card', 'po-pending-card', 'po-field-card'].forEach(id => show(id, false));
            return `Wiped: ${parts.join(', ') || 'nothing to wipe'}`;
          });
          break;
        case 'ct-preview': await openConfSeedEditor(); break;
        case 'ct-generate':
          await act('Generating conference tournaments…', async () => {
            const d = await api.post(v1('/playoffs/conf-tournaments/generate'), { league_year_id: Number(lyid) });
            return `Created ${d.total_series} series across ${(d.conferences || []).length} conferences`;
          });
          break;
        case 'ct-advance':
          await act('Advancing conference tournaments…', async () => {
            const d = await api.post(v1('/playoffs/conf-tournaments/advance'), { league_year_id: Number(lyid) });
            const parts = [];
            if (d.advanced && d.advanced.length) parts.push(`${d.advanced.length} conf(s) advanced`);
            if (d.completed && d.completed.length) parts.push(`${d.completed.length} conf(s) complete`);
            if (d.no_action && d.no_action.length) parts.push(`${d.no_action.length} no action`);
            return parts.join(', ') || 'No changes';
          });
          break;
        case 'ct-wipe':
          if (!await confirm({ title: 'Wipe all conference tournament data?', danger: true, typeToConfirm: 'WIPE', confirmLabel: 'Wipe', message: 'CWS data will be kept.' })) break;
          await act('Wiping conference tournaments…', async () => {
            const d = await api.post(v1('/playoffs/conf-tournaments/wipe'), { league_year_id: Number(lyid) });
            const parts = [];
            if (d.playoff_series) parts.push(`${d.playoff_series} series`);
            if (d.gamelist) parts.push(`${d.gamelist} games`);
            show('ct-bracket-card', false);
            return `Wiped: ${parts.join(', ') || 'nothing to wipe'}`;
          });
          break;
        case 'fe-generate': await generateFromEditedField(); break;
        case 'fe-resequence': E.resequenceTables($('po-fieldedit')); break;
        case 'fe-reset': await openFieldEditor(); break;
        case 'fe-cancel': show('po-fieldedit-card', false); st.fieldEdit = null; break;
        case 'ct-fe-generate': await generateConfFromEdited(); break;
        case 'ct-fe-resequence': E.resequenceTables($('ct-fieldedit')); break;
        case 'ct-fe-reset': await openConfSeedEditor(); break;
        case 'ct-fe-cancel': show('ct-fieldedit-card', false); st.ctEdit = null; break;
        case 'ncaa-suggest': await ncaaSuggest(); break;
        case 'ncaa-generate': await ncaaGenerate(); break;
        case 'ncaa-close': show('ncaa-editor-card', false); break;
        case 'mu-reset': if (st.matchup) { setHtml($('po-matchups'), raw(E.renderMatchupEditor(st.matchup))); setText('po-matchups-status', ''); } break;
        case 'mu-save': await saveMatchups(); break;
        case 'ws-save': {
          setText('po-ws-info', 'Saving…');
          try {
            await api.post(v1('/playoffs/settings/9'), { ws_home_field: $('po-ws-home').value });
            toast.success('World Series home-field rule saved');
            await loadWsHomeField(lyid, 9);
          } catch (err) { setText('po-ws-info', `Error: ${err.message}`); }
          break;
        }
        case 'png-main': await exportMainPng(); break;
        case 'png-all': await exportAllPngs(); break;
        case 'png-conf': e.preventDefault(); e.stopPropagation(); await exportConfPng(btn.dataset.conf); break;
        case 'resched': {
          const row = btn.closest('tr');
          const gid = Number(btn.dataset.gid);
          const week = Number(row.querySelector('.resched-week').value);
          const subweek = row.querySelector('.resched-sub').value;
          setStatus(`Rescheduling game ${gid}…`);
          try {
            const d = await api.post(v1('/playoffs/reschedule-game'), { game_id: gid, season_week: week, season_subweek: subweek });
            setStatus(`Game ${gid} moved to week ${d.season_week}${d.season_subweek}`);
            toast.success(`Game ${gid} moved to week ${d.season_week}${d.season_subweek}`);
            await loadPending(lyid, level);
          } catch (err) { setStatus(`Error: ${err.message}`); }
          break;
        }
        default: break;
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      setStatus(`Error: ${err.message}`);   // api layer already toasted
    } finally {
      if (btn.isConnected) btn.disabled = false;
    }
  }, sig);

  onLevelChange();
}

function wsHomeInfoText(data) {
  const asg = data.allstar_result;
  const asgTxt = asg
    ? (asg.winner_label === 'tie'
      ? `All-Star Game ended in a tie (${asg.home_score}-${asg.away_score}).`
      : `All-Star Game: ${asg.winner_label} won ${asg.winner_score}-${asg.loser_score}.`)
    : 'No completed All-Star Game this year.';
  if (data.ws_home_field !== 'allstar') return `Current rule: better seed. ${asgTxt}`;
  if (asg && (asg.winner_label === 'AL' || asg.winner_label === 'NL')) {
    return `Current rule: All-Star winner. ${asgTxt} The ${asg.winner_label} champion will host games 1, 2, 6, 7.`;
  }
  return `Current rule: All-Star winner. ${asgTxt} Will fall back to better seed.`;
}
