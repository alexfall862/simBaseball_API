// features/season/_shared.js — helpers shared by the Season tabs.

export { phaseBadge, subweekPips, subweekFlagsFromTs, statusBadge, badge } from '../../ui/badge.js';

/** Legacy ACTION_CONFIG: server AvailableActions -> button/endpoint. */
export const ACTION_CONFIG = {
  simulate_week:      { label: 'Simulate week',        cls: 'btn-warning',   href: '#/season/simulate' },
  advance_week:       { label: 'Advance week',         cls: 'btn-warning',   endpoint: '/games/advance-week' },
  reset_week:         { label: 'Reset week games',     cls: 'btn-secondary', endpoint: '/games/reset-week', confirm: 'Clear the subweek completion flags for this week?' },
  end_season:         { label: 'End season',           cls: 'btn-danger',    card: 'end-season' },
  start_free_agency:  { label: 'Start free agency',    cls: 'btn-primary',   endpoint: '/games/start-free-agency', confirm: 'Open the free agency window?' },
  advance_fa_round:   { label: 'Advance FA round',     cls: 'btn-warning',   endpoint: '/games/advance-fa-round', confirm: 'Advance every open auction one phase?' },
  end_free_agency:    { label: 'End free agency',      cls: 'btn-secondary', endpoint: '/games/end-free-agency', confirm: 'Close free agency? Offers sign; empty auctions expire with fallback deals.', danger: true },
  start_draft:        { label: 'Start draft',          cls: 'btn-primary',   endpoint: '/games/start-draft', confirm: 'Open the draft phase?' },
  end_draft:          { label: 'End draft',            cls: 'btn-secondary', endpoint: '/games/end-draft', confirm: 'End the draft phase?' },
  start_recruiting:   { label: 'Start recruiting',     cls: 'btn-primary',   endpoint: '/games/start-recruiting', confirm: 'Open college recruiting?' },
  end_recruiting:     { label: 'End recruiting',       cls: 'btn-secondary', endpoint: '/games/end-recruiting', confirm: 'Close college recruiting?' },
  start_new_season:   { label: 'Start new season',     cls: 'btn-primary',   card: 'new-season' },
  set_week:           { label: 'Jump to week',         cls: 'btn-ghost',     card: 'set-week' },
  set_phase:          { label: 'Phase override',       cls: 'btn-ghost',     card: 'set-phase' },
};

/**
 * A child AbortController that aborts with its parent. Use it for
 * sub-sections (subTabs) that are torn down before the tab itself.
 */
export function childSignal(parentSignal) {
  const c = new AbortController();
  if (parentSignal) {
    if (parentSignal.aborted) c.abort();
    else parentSignal.addEventListener('abort', () => c.abort(), { once: true });
  }
  return c;
}
