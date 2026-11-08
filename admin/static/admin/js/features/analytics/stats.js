// features/analytics/stats.js — the 14 analytics reports (port of legacy #section-analytics-*).
// One tab, sub-navigation via subTabs; the active report id lives in the URL (?report=).

import { ALL_LEVELS } from '../../core/constants.js';
import { reportTabs } from './_shared.js';
import { battingCorr, pitchingCorr, defenseCorr, warReport, regressionReport, sensitivityReport, xstatsReport, interactionsReport } from './_stats_a.js';
import { dashboardReport, archetypesReport, pitchTypesReport, defPosReport, contactReport, hrDepthReport } from './_stats_b.js';

const REPORTS = [
  battingCorr, pitchingCorr, defenseCorr, warReport,
  regressionReport, sensitivityReport, xstatsReport, interactionsReport,
  dashboardReport, archetypesReport, pitchTypesReport, defPosReport,
  contactReport, hrDepthReport,
];

export async function mount(el, ctx) {
  await reportTabs(el, ctx, {
    title: 'Stats analytics',
    sub: 'Attribute ↔ outcome diagnostics for engine tuning. Pick a report, set the shared league year / level and the report\'s own thresholds, then Load.',
    reports: REPORTS,
    filters: { leagueYear: true, level: { levels: ALL_LEVELS, value: 9 } },
  });
}
