// features/index.js — the area/tab registry. Each tab is lazy-loaded.
// Keep this file free of feature imports other than dynamic import().

export const AREAS = [
  {
    id: 'home', title: 'Command Center', icon: '◉',
    tabs: [
      { id: 'overview', title: 'Overview', load: () => import('./command-center/overview.js') },
    ],
  },
  {
    id: 'season', title: 'Season', icon: '⚾',
    tabs: [
      { id: 'simulate', title: 'Simulate', load: () => import('./season/simulate.js') },
      { id: 'phase', title: 'Phase & Week', load: () => import('./season/phase.js') },
      { id: 'checklist', title: 'Offseason Checklist', load: () => import('./season/checklist.js') },
      { id: 'playoffs', title: 'Playoffs', load: () => import('./season/playoffs.js') },
      { id: 'events', title: 'Special Events', load: () => import('./season/events.js') },
      { id: 'schedule', title: 'Schedule', load: () => import('./season/schedule.js') },
    ],
  },
  {
    id: 'jobs', title: 'Jobs', icon: '⏱',
    tabs: [
      { id: 'scheduled', title: 'Scheduled Jobs', load: () => import('./jobs/scheduled.js') },
      { id: 'runs', title: 'Run History', load: () => import('./jobs/runs.js') },
      { id: 'tasks', title: 'Background Tasks', load: () => import('./jobs/tasks.js') },
      { id: 'logs', title: 'Logs', load: () => import('./jobs/logs.js') },
    ],
  },
  {
    id: 'timeline', title: 'Timeline', icon: '▤',
    tabs: [
      { id: 'view', title: 'Timeline', load: () => import('./timeline/view.js') },
    ],
  },
  {
    id: 'market', title: 'Market', icon: '⇄',
    tabs: [
      { id: 'fa', title: 'FA Auction', load: () => import('./market/fa-auction.js') },
      { id: 'fa-market', title: 'FA Market', load: () => import('./market/fa-market.js') },
      { id: 'draft', title: 'Draft', load: () => import('./market/draft.js') },
      { id: 'ifa', title: 'IFA', load: () => import('./market/ifa.js') },
      { id: 'recruiting', title: 'Recruiting', load: () => import('./market/recruiting.js') },
      { id: 'trades', title: 'Trades', load: () => import('./market/trades.js') },
      { id: 'roster', title: 'Roster Moves', load: () => import('./market/roster.js') },
      { id: 'txlog', title: 'Transactions Log', load: () => import('./market/txlog.js') },
      { id: 'compliance', title: 'Roster Compliance', load: () => import('./market/compliance.js') },
      { id: 'eos', title: 'End of Season', load: () => import('./market/eos.js') },
      { id: 'amateur', title: 'Amateur Seeding', load: () => import('./market/amateur.js') },
    ],
  },
  {
    id: 'engine', title: 'Player Engine', icon: '⚙',
    tabs: [
      { id: 'generate', title: 'Generate', load: () => import('./engine/generate.js') },
      { id: 'progress', title: 'Progress', load: () => import('./engine/progress.js') },
      { id: 'sandbox', title: 'Sandbox', load: () => import('./engine/sandbox.js') },
      { id: 'diagnostics', title: 'Progression Diagnostics', load: () => import('./engine/diagnostics.js') },
      { id: 'rating-config', title: 'Rating Config', load: () => import('./engine/rating-config.js') },
      { id: 'calibration', title: 'Weight Calibration', load: () => import('./engine/calibration.js') },
    ],
  },
  {
    id: 'analytics', title: 'Analytics', icon: '📈',
    tabs: [
      { id: 'stats', title: 'Stats', load: () => import('./analytics/stats.js') },
      { id: 'stamina', title: 'Stamina', load: () => import('./analytics/stamina.js') },
      { id: 'rankings', title: 'Rankings', load: () => import('./analytics/rankings.js') },
      { id: 'gameplans', title: 'Gameplan Audit', load: () => import('./analytics/gameplans.js') },
      { id: 'batting-lab', title: 'Batting Lab', load: () => import('./analytics/batting-lab.js') },
    ],
  },
  {
    id: 'data', title: 'Data', icon: '▦',
    tabs: [
      { id: 'orgs', title: 'Organizations', load: () => import('./data/orgs.js') },
      { id: 'teams', title: 'Teams', load: () => import('./data/teams.js') },
      { id: 'players', title: 'Players', load: () => import('./data/players.js') },
      { id: 'game', title: 'Game Viewer', load: () => import('./data/game-viewer.js') },
      { id: 'sql', title: 'SQL Console', load: () => import('./data/sql.js') },
      { id: 'storage', title: 'DB Storage', load: () => import('./data/storage.js') },
    ],
  },
  {
    id: 'system', title: 'System', icon: '🛠',
    tabs: [
      { id: 'health', title: 'Health', load: () => import('./system/health.js') },
      { id: 'cache', title: 'Cache', load: () => import('./system/cache.js') },
      { id: 'migrations', title: 'Migrations', load: () => import('./system/migrations.js') },
      { id: 'orphans', title: 'Orphan Sweep', load: () => import('./system/orphans.js') },
      { id: 'finance', title: 'Finance', load: () => import('./system/finance.js') },
      { id: 'tutorial', title: 'Tutorial CMS', load: () => import('./system/tutorial.js') },
      { id: 'settings', title: 'Settings', load: () => import('./system/settings.js') },
    ],
  },
];
