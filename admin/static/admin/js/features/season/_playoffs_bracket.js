// features/season/_playoffs_bracket.js — bracket rendering helpers for the
// Playoffs tab: HTML tables for the live bracket (MLB/MiLB rounds, CWS table,
// conference tournaments, NCAA 64-team stages, playoff field previews) and the
// client-side canvas PNG export built from /playoffs/bracket-skeleton.
//
// Everything here is pure: functions take data and return markup strings
// (already escaped) or a <canvas>. No DOM lookups, no module state.

import { esc } from '../../core/html.js';
import { badge } from '../../ui/badge.js';

// ---------------------------------------------------------------- labels

export const CWS_ROUND_LABELS = Object.freeze({
  CWS_W1: 'Winners — Round 1', CWS_W2: 'Winners — Round 2', CWS_W3: 'Winners — Final',
  CWS_L1: 'Losers — Round 1', CWS_L2: 'Losers — Round 2', CWS_L3: 'Losers — Round 3',
  CWS_L4: 'Losers — Final', CWS_F1: 'Championship', CWS_F2: 'Championship (if necessary)',
});

const NCAA_DE_ORDER = ['G1', 'WF', 'LB', 'L2', 'RF', 'RF2'];
const NCAA_DE_LABELS = {
  G1: 'Round 1', WF: "Winners' Final", LB: 'Elimination',
  L2: "Losers' Final", RF: 'Final', RF2: 'If Necessary',
};

export function bracketTitleForLevel(level) {
  const lvl = String(level);
  if (lvl === '9') return 'MLB Playoffs';
  if (lvl === '3') return 'NCAA Tournament';
  const names = { 5: 'Single-A', 6: 'High-A', 7: 'Double-A', 8: 'Triple-A' };
  return (names[lvl] || `Level ${lvl}`) + ' Playoffs';
}

export function ctRoundLabel(roundKey, totalRounds) {
  const n = parseInt(String(roundKey).replace('CT_R', ''), 10);
  if (n === totalRounds) return 'Final';
  if (n === totalRounds - 1) return 'Semifinal';
  if (n === totalRounds - 2) return 'Quarterfinal';
  return `Round ${n}`;
}

// ---------------------------------------------------------------- series tables

function seriesBadge(s) {
  if (s.status === 'complete') return badge('Complete', 'success');
  const gp = (s.wins_a || 0) + (s.wins_b || 0);
  return badge(`Game ${gp + 1} of ${s.series_length}`, 'warning');
}

function matchupText(s) {
  const a = s.team_a || {}, b = s.team_b || {};
  return `${esc(a.abbrev || 'TBD')} (#${esc(a.seed || '-')}) vs ${esc(b.abbrev || 'TBD')} (#${esc(b.seed || '-')})`;
}

function seriesRow(s) {
  const score = s.series_length > 1
    ? `<td class="nowrap">${esc(s.wins_a)} - ${esc(s.wins_b)} (Bo${esc(s.series_length)})</td>`
    : '<td>—</td>';
  return `<tr><td>${matchupText(s)}</td>${score}<td>${seriesBadge(s)}</td><td>${s.winner ? esc(s.winner.abbrev) : '-'}</td></tr>`;
}

export function seriesTable(list) {
  const body = (list || []).map(seriesRow).join('') || '<tr><td colspan="4" class="text-muted tbl-state">No series.</td></tr>';
  return `<div class="table-container"><table class="data-table compact"><thead><tr><th>Matchup</th><th>Score</th><th>Status</th><th>Winner</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

/** Main bracket (MLB, MiLB, plus legacy flat CWS rounds): one table per round. */
export function renderMainBracket(data) {
  let out = '';
  for (const [round, series] of Object.entries(data.rounds || {})) {
    out += `<h4 class="mt-2 mb-1">${esc(CWS_ROUND_LABELS[round] || round)}</h4>`;
    out += seriesTable(series);
  }
  if (Array.isArray(data.cws_bracket) && data.cws_bracket.length) {
    const alive = data.cws_bracket.filter(t => !t.eliminated);
    if (data.cws_bracket.length > 1 && alive.length === 1) {
      out += `<p class="mt-2"><strong>CWS Champion: ${esc(alive[0].team_abbrev)}</strong></p>`;
    }
    out += '<h4 class="mt-2 mb-1">CWS Bracket</h4>';
    out += '<div class="table-container"><table class="data-table compact"><thead><tr><th>Seed</th><th>Team</th><th>Qual</th><th>Losses</th><th>Side</th></tr></thead><tbody>';
    data.cws_bracket.forEach(t => {
      out += `<tr class="${t.eliminated ? 'row-muted' : ''}"><td>#${esc(t.seed)}</td><td>${esc(t.team_abbrev)}</td><td>${esc(t.qualification)}</td><td>${esc(t.losses)}</td><td>${esc(t.bracket_side)}</td></tr>`;
    });
    out += '</tbody></table></div>';
  }
  return out;
}

/** Conference tournaments (college): one collapsible per conference with a PNG button. */
export function renderConfTournaments(confTournaments) {
  let out = '';
  const entries = Object.entries(confTournaments || {}).sort((a, b) => a[0].localeCompare(b[0]));
  for (const [conf, cdata] of entries) {
    const roundNames = Object.keys(cdata.rounds || {}).sort();
    const totalRounds = cdata.total_rounds || roundNames.length;
    const finalSeries = (cdata.rounds || {})[`CT_R${totalRounds}`] || [];
    const champ = finalSeries.length === 1 && finalSeries[0].winner ? finalSeries[0].winner.abbrev : null;
    out += `<details class="mb-1"><summary><strong>${esc(conf)}</strong>${champ ? ` — Champion: ${esc(champ)}` : ''} <button type="button" class="btn btn-xs btn-secondary" data-action="png-conf" data-conf="${esc(conf)}">PNG</button></summary>`;
    for (const rnd of roundNames) {
      out += `<h5 class="mt-1 mb-1">${esc(ctRoundLabel(rnd, totalRounds))}</h5>`;
      out += '<div class="table-container"><table class="data-table compact"><thead><tr><th>Matchup</th><th>Status</th><th>Winner</th></tr></thead><tbody>';
      (cdata.rounds[rnd] || []).forEach(s => {
        out += `<tr><td>${matchupText(s)}</td><td>${s.status === 'complete' ? badge('Complete', 'success') : badge('Pending', 'warning')}</td><td>${s.winner ? esc(s.winner.abbrev) : '-'}</td></tr>`;
      });
      out += '</tbody></table></div>';
    }
    out += '</details>';
  }
  return out;
}

function deGroupTables(rounds) {
  let out = '';
  NCAA_DE_ORDER.forEach(suf => {
    const key = Object.keys(rounds || {}).find(k => k.endsWith('_' + suf));
    if (!key) return;
    out += `<h5 class="mt-1 mb-1">${esc(NCAA_DE_LABELS[suf])}</h5>${seriesTable(rounds[key])}`;
  });
  return out;
}

/** NCAA 64-team tournament: regionals → super regionals → MCWS → finals. */
export function renderNcaaBracket(ncaa) {
  let out = '';
  if (ncaa.champion) out += `<p class="mb-2"><strong>National Champion: ${esc(ncaa.champion.abbrev)}</strong></p>`;
  out += '<h4 class="mb-1">Regionals</h4>';
  (ncaa.regionals || []).forEach(r => {
    const started = Object.keys(r.rounds || {}).length > 0;
    const status = (r.complete && r.champion) ? ` — Champion: ${esc(r.champion.abbrev)}` : (started ? ' — in progress' : ' — not started');
    const teams = (r.teams || []).map(t => `#${esc(t.regional_seed)} ${esc(t.team_abbrev)}${t.eliminated ? ' <span class="text-muted">(out)</span>' : ''}`).join(' · ');
    out += `<details class="mb-1"><summary><strong>Regional ${esc(r.regional_no)}</strong>${r.national_seed ? ` · Nat #${esc(r.national_seed)}` : ''} — ${esc(r.host || 'TBD')}${status}</summary>`;
    out += `<p class="text-muted small mt-1 mb-1">${teams}</p>${deGroupTables(r.rounds || {})}</details>`;
  });
  if ((ncaa.super_regionals || []).length) {
    out += `<h4 class="mt-2 mb-1">Super Regionals (Best of 3)</h4>${seriesTable(ncaa.super_regionals)}`;
  }
  const mA = ncaa.mcws && ncaa.mcws.A, mB = ncaa.mcws && ncaa.mcws.B;
  const hasMcws = (mA && Object.keys(mA.rounds || {}).length) || (mB && Object.keys(mB.rounds || {}).length);
  if (hasMcws) {
    out += '<h4 class="mt-2 mb-1">College World Series — Omaha</h4>';
    [['A', mA], ['B', mB]].forEach(([side, m]) => {
      if (!m) return;
      const champ = (m.complete && m.champion) ? ` — Champion: ${esc(m.champion.abbrev)}` : '';
      out += `<h5 class="mt-1 mb-1">Bracket ${side}${champ}</h5>${deGroupTables(m.rounds || {})}`;
    });
  }
  if (ncaa.final) out += `<h4 class="mt-2 mb-1">MCWS Finals (Best of 3)</h4>${seriesTable([ncaa.final])}`;
  return out;
}

// ---------------------------------------------------------------- field previews

function fieldTable(teams) {
  let out = '<div class="table-container"><table class="data-table compact"><thead><tr><th>Seed</th><th>Team</th><th>W</th><th>L</th><th>Pct</th><th>Qual</th></tr></thead><tbody>';
  (teams || []).forEach(t => {
    out += `<tr><td>#${esc(t.seed)}</td><td>${esc(t.team_abbrev)}</td><td>${esc(t.wins)}</td><td>${esc(t.losses)}</td><td>${esc(t.win_pct)}</td><td>${esc(t.qualifier)}</td></tr>`;
  });
  return out + '</tbody></table></div>';
}

/** Read-only field after generation: MiLB array or MLB {AL, NL}. */
export function renderPlayoffField(field) {
  if (Array.isArray(field)) return fieldTable(field);
  return Object.entries(field || {}).map(([conf, teams]) => `<h4 class="mt-1 mb-1">${esc(conf)}</h4>${fieldTable(teams)}`).join('');
}

/** Read-only 64-team NCAA field grouped by regional. */
export function renderNcaaField(field) {
  const byReg = {};
  (field || []).forEach(t => {
    if (t == null || t.regional_no == null) return;
    (byReg[t.regional_no] = byReg[t.regional_no] || []).push(t);
  });
  let out = '<p class="text-muted small mb-2">64-team NCAA field — conference auto-bids + at-large. National seeds 1–16 (bold) anchor the 16 regionals.</p><div class="grid-4">';
  Object.keys(byReg).map(Number).sort((a, b) => a - b).forEach(n => {
    const teams = byReg[n].slice().sort((a, b) => a.regional_seed - b.regional_seed);
    const host = teams[0] || {};
    out += `<div class="table-container"><table class="data-table compact"><thead><tr><th colspan="3">Regional ${n}${host.national_seed ? ` · Nat #${esc(host.national_seed)}` : ''}</th></tr></thead><tbody>`;
    teams.forEach(t => {
      const name = t.regional_seed === 1 ? `<strong>${esc(t.team_abbrev)}</strong>` : esc(t.team_abbrev);
      out += `<tr><td>#${esc(t.regional_seed)}</td><td>${name}</td><td>${esc(t.wins)}-${esc(t.losses)}</td></tr>`;
    });
    out += '</tbody></table></div>';
  });
  return out + '</div>';
}

// ---------------------------------------------------------------- PNG export
//
// Brackets are drawn from the /playoffs/bracket-skeleton payload, which has
// the COMPLETE shape (every round through the final, TBD slots for rounds not
// yet created). Connector lines are only drawn for clean single-elim trees
// (kind === 'tree'); MLB and conference brackets re-seed each round, so they
// render as labelled columns.

function skTeamCell(team, wins) {
  if (!team) return { abbrev: 'TBD', seed: null, wins: null, tbd: true };
  return { abbrev: team.abbrev, seed: team.seed, wins };
}

function skSlotToCard(slot) {
  return {
    a: skTeamCell(slot.team_a, slot.wins_a),
    b: skTeamCell(slot.team_b, slot.wins_b),
    winner: slot.winner ? slot.winner.abbrev : null,
    showScore: slot.series_length > 1 && slot.status !== 'not_created',
    games: slot.games || [],
  };
}

export function skeletonRounds(bracket) {
  return (bracket.rounds || []).map(r => ({ label: r.label, series: (r.matches || []).map(skSlotToCard) }));
}

export function slug(s) {
  return String(s).replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '') || 'bracket';
}

/** Render one skeleton bracket to {canvas, filename}. */
export function renderSkeletonBracket(bracket, level) {
  const title = bracket.key === 'main' ? bracketTitleForLevel(level) : bracket.title;
  const canvas = drawBracketCanvas(title, skeletonRounds(bracket), { connectors: bracket.kind === 'tree' });
  return { canvas, filename: `bracket_${slug(title)}.png` };
}

export function downloadCanvasPng(canvas, filename) {
  canvas.toBlob(blob => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'image/png');
}

/** Browsers throttle rapid programmatic saves — stagger multi-file downloads. */
export function downloadStaggered(items, gapMs = 400) {
  items.forEach((b, i) => setTimeout(() => downloadCanvasPng(b.canvas, b.filename), i * gapMs));
}

const CARD_LEFT_W = 100;   // seed + abbrev zone
const GAME_CELL_W = 18;    // per-game score column width

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawTeamRow(ctx, x, y, w, h, team, isWinner) {
  const cy = y + h / 2;
  ctx.textBaseline = 'middle';
  ctx.font = '500 11px system-ui, sans-serif';
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'left';
  ctx.fillText(team.seed ? String(team.seed) : '-', x + 11, cy);
  ctx.font = (isWinner ? '700 ' : '500 ') + '14px system-ui, sans-serif';
  ctx.fillStyle = team.tbd ? '#6b7280' : (isWinner ? '#34d399' : '#e5e7eb');
  ctx.fillText(team.abbrev || 'TBD', x + 34, cy);
}

function drawScores(ctx, sx, y, h, s) {
  const topCy = y + h / 4;
  const botCy = y + h * 3 / 4;
  if (s.games && s.games.length) {
    ctx.font = '600 12px system-ui, sans-serif';
    ctx.textAlign = 'center';
    s.games.forEach((g, i) => {
      const cx = sx + 4 + i * GAME_CELL_W + GAME_CELL_W / 2;
      ctx.fillStyle = g.win_a ? '#34d399' : '#9ca3af';
      ctx.fillText(String(g.a), cx, topCy);
      ctx.fillStyle = g.win_b ? '#34d399' : '#9ca3af';
      ctx.fillText(String(g.b), cx, botCy);
    });
  } else if (s.showScore) {
    ctx.font = '700 13px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillStyle = s.winner === s.a.abbrev ? '#34d399' : '#9ca3af';
    if (s.a.wins != null) ctx.fillText(String(s.a.wins), sx + 6, topCy);
    ctx.fillStyle = s.winner === s.b.abbrev ? '#34d399' : '#9ca3af';
    if (s.b.wins != null) ctx.fillText(String(s.b.wins), sx + 6, botCy);
  }
}

function drawCard(ctx, x, y, w, h, s) {
  roundRectPath(ctx, x, y, w, h, 6);
  ctx.fillStyle = '#1b2433';
  ctx.fill();
  ctx.strokeStyle = '#374151';
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x, y + h / 2);
  ctx.lineTo(x + w, y + h / 2);
  ctx.strokeStyle = '#374151';
  ctx.stroke();
  drawTeamRow(ctx, x, y, CARD_LEFT_W, h / 2, s.a, s.winner === s.a.abbrev);
  drawTeamRow(ctx, x, y + h / 2, CARD_LEFT_W, h / 2, s.b, s.winner === s.b.abbrev);
  const hasScores = (s.games && s.games.length) || s.showScore;
  if (hasScores && w > CARD_LEFT_W + 4) {
    ctx.beginPath();
    ctx.moveTo(x + CARD_LEFT_W, y + 6);
    ctx.lineTo(x + CARD_LEFT_W, y + h - 6);
    ctx.strokeStyle = '#2b3647';
    ctx.stroke();
    drawScores(ctx, x + CARD_LEFT_W, y, h, s);
  }
}

/**
 * Draw a bracket to an off-screen canvas.
 * rounds = [{label, series: [{a, b, winner, showScore, games}]}]
 */
export function drawBracketCanvas(title, rounds, opts) {
  const allowConnectors = !opts || opts.connectors !== false;
  const SC = 2;
  const pad = 36;
  const cardH = 56, colGap = 64, vGap = 22;
  const titleH = 52, labelH = 28;
  let maxGames = 0, anyWins = false;
  rounds.forEach(r => r.series.forEach(c => {
    maxGames = Math.max(maxGames, (c.games || []).length);
    if (c.showScore) anyWins = true;
  }));
  const scoreW = maxGames > 0 ? (8 + maxGames * GAME_CELL_W) : (anyWins ? 24 : 0);
  const cardW = CARD_LEFT_W + scoreW + 8;
  const numRounds = rounds.length;
  const maxCards = Math.max(1, ...rounds.map(r => r.series.length));
  const slotH = cardH + vGap;
  const contentH = maxCards * slotH;

  const titleFont = '700 24px system-ui, sans-serif';
  const labelFont = '600 13px system-ui, sans-serif';
  const colsW = numRounds * cardW + Math.max(0, numRounds - 1) * colGap;
  const measureCtx = document.createElement('canvas').getContext('2d');
  measureCtx.font = titleFont;
  let neededW = Math.max(colsW, measureCtx.measureText(title).width);
  measureCtx.font = labelFont;
  rounds.forEach((r, i) => {
    const right = i * (cardW + colGap) + measureCtx.measureText(r.label.toUpperCase()).width;
    if (right > neededW) neededW = right;
  });
  const W = pad * 2 + Math.ceil(neededW);
  const H = pad * 2 + titleH + labelH + contentH;

  const canvas = document.createElement('canvas');
  canvas.width = Math.round(W * SC);
  canvas.height = Math.round(H * SC);
  const ctx = canvas.getContext('2d');
  ctx.scale(SC, SC);

  ctx.fillStyle = '#0f1623';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#f3f4f6';
  ctx.font = titleFont;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.fillText(title, pad, pad + 14);
  ctx.fillStyle = '#3b82f6';
  ctx.fillRect(pad, pad + 34, 48, 3);

  const contentTop = pad + titleH + labelH;
  const xOf = r => pad + r * (cardW + colGap);

  // Only a clean single-elimination tree (each round = half the previous)
  // gets connector lines; anything irregular is drawn as plain columns.
  let cleanTree = allowConnectors && numRounds > 1;
  for (let i = 1; i < numRounds && cleanTree; i++) {
    if (rounds[i - 1].series.length !== rounds[i].series.length * 2) { cleanTree = false; break; }
  }

  const positions = [];
  for (let r = 0; r < numRounds; r++) {
    const n = rounds[r].series.length;
    const col = [];
    if (cleanTree && r > 0) {
      const prev = positions[r - 1];
      for (let i = 0; i < n; i++) col.push((prev[2 * i] + prev[2 * i + 1]) / 2);
    } else {
      const top = contentTop + (contentH - n * slotH) / 2;
      for (let i = 0; i < n; i++) col.push(top + i * slotH + cardH / 2);
    }
    positions.push(col);
  }

  ctx.font = labelFont;
  ctx.fillStyle = '#9ca3af';
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  for (let r = 0; r < numRounds; r++) ctx.fillText(rounds[r].label.toUpperCase(), xOf(r), contentTop - 12);

  if (cleanTree) {
    ctx.strokeStyle = '#374151';
    ctx.lineWidth = 1.5;
    for (let r = 0; r < numRounds - 1; r++) {
      const x1 = xOf(r) + cardW;
      const x2 = xOf(r + 1);
      const midX = (x1 + x2) / 2;
      for (let i = 0; i < positions[r].length; i++) {
        const y1 = positions[r][i];
        const target = positions[r + 1][Math.floor(i / 2)];
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(midX, y1);
        ctx.lineTo(midX, target);
        ctx.lineTo(x2, target);
        ctx.stroke();
      }
    }
  }

  for (let r = 0; r < numRounds; r++) {
    rounds[r].series.forEach((s, i) => drawCard(ctx, xOf(r), positions[r][i] - cardH / 2, cardW, cardH, s));
  }
  return canvas;
}
