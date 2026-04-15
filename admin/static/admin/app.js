// admin/static/admin/app.js
// SimBaseball Admin Dashboard

(function () {
  'use strict';

  const API_BASE = '/api/v1';
  const ADMIN_BASE = '/admin';

  // State
  let isAuthenticated = false;
  let currentSection = 'dashboard';
  let taskPollInterval = null;
  let syntheticTaskId = null;

  // Schedule Viewer state
  let svCurrentPage = 1;
  const svPageSize = 200;

  // Transaction state
  let txLeagueYearId = null;
  let txGameWeekId = null;
  let txSelectedPlayer = null;   // { contract_id, player_id, player_name, ... }
  let txSelectedFA = null;       // { player_id, player_name, ... }
  let txOrgList = [];            // cached org list for dropdowns

  // SQL Presets
  const SQL_PRESETS = [
    { name: 'All Players (limit 100)', query: 'SELECT * FROM simbbPlayers LIMIT 100' },
    { name: 'All Teams', query: 'SELECT * FROM simbbTeams' },
    { name: 'All Organizations', query: 'SELECT * FROM simbbOrganizations' },
    { name: 'Game Schedule', query: 'SELECT * FROM simbbSchedule LIMIT 100' },
    { name: 'Level Configs', query: 'SELECT * FROM simbbLevelConfigs' },
    { name: 'Catch Rates', query: 'SELECT * FROM simbbCatchRates' },
    { name: 'Player Stats (Batting)', query: 'SELECT * FROM simbbPlayerStatsBatting LIMIT 100' },
    { name: 'Player Stats (Pitching)', query: 'SELECT * FROM simbbPlayerStatsPitching LIMIT 100' },
    { name: 'Background Tasks', query: 'SELECT id, status, task_type, progress, total, created_at FROM background_tasks ORDER BY created_at DESC LIMIT 50' },
  ];

  // DOM Elements
  const elements = {};

  // Initialize
  function init() {
    cacheElements();
    setupEventListeners();
    _setupTutorialListeners();
    loadSqlPresets();
    checkAuth();
    refreshDashboard();
  }

  function cacheElements() {
    elements.sidebar = document.getElementById('sidebar');
    elements.menuToggle = document.getElementById('menu-toggle');
    elements.pageTitle = document.getElementById('page-title');
    elements.adminPassword = document.getElementById('admin-password');
    elements.btnLogin = document.getElementById('btn-login');
    elements.btnLogout = document.getElementById('btn-logout');
    elements.authStatus = document.getElementById('auth-status');
    elements.authText = document.getElementById('auth-text');
  }

  function setupEventListeners() {
    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        if (section) goTo(section);
      });
    });

    // Mobile menu toggle
    elements.menuToggle.addEventListener('click', () => {
      elements.sidebar.classList.toggle('open');
    });

    // Auth
    elements.btnLogin.addEventListener('click', login);
    elements.btnLogout.addEventListener('click', logout);

    // Write mode toggle
    document.getElementById('write-mode-cb').addEventListener('change', (e) => {
      const enabled = e.target.checked;
      fetch(`${ADMIN_BASE}/write-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ enabled }),
      })
        .then(r => r.json())
        .then(data => { _updateWriteLabel(data.write_mode); })
        .catch(() => { e.target.checked = !enabled; });
    });
    elements.adminPassword.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') login();
    });

    // Synthetic Games
    document.getElementById('btn-syn-async').addEventListener('click', () => runSynthetic(true));
    document.getElementById('btn-syn-sync').addEventListener('click', () => runSynthetic(false));

    // Tasks
    document.getElementById('btn-refresh-tasks').addEventListener('click', loadTasks);

    // Simulate Week
    document.getElementById('btn-sim-preview').addEventListener('click', () => runSimulation(false));
    document.getElementById('btn-sim-run').addEventListener('click', () => runSimulation(true));
    document.getElementById('btn-run-season').addEventListener('click', runSeason);
    document.getElementById('btn-run-all-levels').addEventListener('click', runAllLevels);
    document.getElementById('btn-wipe-season').addEventListener('click', wipeSeason);
    document.getElementById('btn-rollback-to-week').addEventListener('click', rollbackToWeek);

    // Timestamp
    const _tsListeners = {
      'btn-refresh-timestamp': loadTimestamp,
      'btn-set-week': tsSetWeek,
      'btn-set-phase': tsSetPhase,
      'btn-end-season': tsEndSeason,
      'btn-start-new-season': tsStartNewSeason,
    };
    for (const [id, fn] of Object.entries(_tsListeners)) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', fn);
    }

    // Listed Positions
    const btnFillLP = document.getElementById('btn-fill-listed-positions');
    if (btnFillLP) btnFillLP.addEventListener('click', fillListedPositions);

    // Default Gameplans
    const btnGenGP = document.getElementById('btn-generate-gameplans');
    if (btnGenGP) btnGenGP.addEventListener('click', generateDefaultGameplans);

    // Season Archive
    const btnArchive = document.getElementById('btn-season-archive');
    if (btnArchive) btnArchive.addEventListener('click', archiveSeason);

    // Weight Calibration
    const _calListeners = {
      'btn-cal-run': runCalibration,
      'btn-cal-load-profiles': loadCalibrationProfiles,
      'btn-cal-compare': compareCalibrationProfiles,
    };
    for (const [id, fn] of Object.entries(_calListeners)) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', fn);
    }

    // Organizations
    document.getElementById('btn-refresh-orgs').addEventListener('click', loadOrganizations);
    document.getElementById('org-select').addEventListener('change', loadOrgDetail);

    // Teams
    document.getElementById('btn-refresh-teams').addEventListener('click', loadTeams);
    document.getElementById('team-select').addEventListener('change', loadTeamDetail);
    document.getElementById('btn-team-players').addEventListener('click', loadTeamPlayers);

    // Players
    document.getElementById('btn-lookup-player').addEventListener('click', lookupPlayer);
    document.getElementById('player-id').addEventListener('keypress', (e) => {
      if (e.key === 'Enter') lookupPlayer();
    });

    // Cache
    document.getElementById('btn-clear-cache').addEventListener('click', clearCaches);
    document.getElementById('btn-sim-clear-cache').addEventListener('click', clearCachesFromSim);

    // SQL
    document.getElementById('btn-run-sql').addEventListener('click', runSql);
    document.getElementById('btn-run-preset').addEventListener('click', runSqlPreset);

    // Health
    document.getElementById('btn-check-health').addEventListener('click', checkHealth);

    // Migrations
    document.getElementById('btn-migrate-amateur').addEventListener('click', runMigrateAmateur);

    // Rating Config
    document.getElementById('btn-seed-config').addEventListener('click', seedRatingConfig);
    document.getElementById('btn-load-config').addEventListener('click', loadLevelConfig);
    document.getElementById('btn-save-config').addEventListener('click', saveLevelConfig);
    document.getElementById('btn-load-analysis').addEventListener('click', loadAnalysis);
    document.getElementById('rc-attr-filter').addEventListener('input', filterAnalysisTable);

    // Growth Curves
    document.getElementById('btn-load-gc').addEventListener('click', loadGrowthCurves);
    document.getElementById('btn-save-gc').addEventListener('click', saveGrowthCurves);
    document.getElementById('gc-grade-filter').addEventListener('change', filterGrowthCurves);

    // Transactions — Roster Moves
    document.getElementById('btn-tx-load-roster').addEventListener('click', () => {
      const orgId = document.getElementById('tx-org-select').value;
      if (orgId) loadOrgRoster(parseInt(orgId));
    });
    document.getElementById('tx-action-type').addEventListener('change', onActionTypeChange);
    document.getElementById('btn-tx-execute-action').addEventListener('click', executeRosterAction);
    document.getElementById('tx-ext-years').addEventListener('change', renderExtSalaryInputs);
    document.getElementById('btn-tx-load-fa').addEventListener('click', loadFreeAgents);
    document.getElementById('btn-tx-sign').addEventListener('click', signFreeAgent);
    document.getElementById('tx-sign-years').addEventListener('change', renderSignSalaryInputs);
    document.getElementById('tx-roster-level-filter').addEventListener('change', () => {
      const orgId = document.getElementById('tx-org-select').value;
      if (orgId) loadOrgRoster(parseInt(orgId));
    });

    // Transactions — Trades
    document.getElementById('tx-trade-org-a').addEventListener('change', () => {
      const orgId = document.getElementById('tx-trade-org-a').value;
      if (orgId) loadTradeOrgRoster('a', parseInt(orgId));
    });
    document.getElementById('tx-trade-org-b').addEventListener('change', () => {
      const orgId = document.getElementById('tx-trade-org-b').value;
      if (orgId) loadTradeOrgRoster('b', parseInt(orgId));
    });
    document.getElementById('btn-tx-execute-trade').addEventListener('click', executeTrade);
    document.getElementById('btn-tx-load-proposals').addEventListener('click', loadTradeProposals);

    // Transactions — Log
    document.getElementById('btn-tx-load-log').addEventListener('click', loadTransactionLog);
    document.getElementById('btn-tx-bulk-delete').addEventListener('click', bulkDeleteTxLog);

    // Amateur Seeding
    document.getElementById('btn-amateur-preview').addEventListener('click', loadAmateurPreview);
    document.getElementById('btn-amateur-seed').addEventListener('click', runAmateurSeed);
    document.getElementById('btn-populate-college').addEventListener('click', populateCollegeOrgs);

    // End of Season
    document.getElementById('btn-eos-run').addEventListener('click', runEndOfSeason);
    document.getElementById('btn-eos-load-overview').addEventListener('click', () => {
      const orgId = document.getElementById('eos-org-select').value;
      if (orgId) loadServiceOverview(parseInt(orgId));
    });

    // Player Engine — Generation
    document.getElementById('btn-pe-generate').addEventListener('click', generatePlayers);

    // Player Engine — Progression
    document.getElementById('btn-pe-progress-all').addEventListener('click', progressAll);
    document.getElementById('btn-pe-progress-one').addEventListener('click', progressSingle);

    // Player Engine — Sandbox
    document.getElementById('btn-sandbox-run').addEventListener('click', runSandbox);
    document.getElementById('sandbox-ability-select').addEventListener('change', () => {
      populateSandboxGradeFilter();
      renderSandboxChart();
    });
    document.getElementById('sandbox-show-bands').addEventListener('change', renderSandboxChart);
    document.getElementById('sandbox-show-players').addEventListener('change', onTogglePlayerOverlay);
    document.getElementById('sandbox-grade-filter').addEventListener('change', () => {
      updateHighlightDropdown();
      renderSandboxChart();
    });
    document.getElementById('sandbox-highlight-player').addEventListener('change', renderSandboxChart);

    // Analytics
    document.getElementById('btn-an-bat-load').addEventListener('click', loadBattingCorrelations);
    document.getElementById('btn-an-bat-back').addEventListener('click', () => showAnalyticsView('bat', 'heatmap'));
    document.getElementById('btn-an-pit-load').addEventListener('click', loadPitchingCorrelations);
    document.getElementById('btn-an-pit-back').addEventListener('click', () => showAnalyticsView('pit', 'heatmap'));
    document.getElementById('btn-an-def-load').addEventListener('click', loadDefensiveAnalysis);
    document.getElementById('btn-an-def-back').addEventListener('click', () => showAnalyticsView('def', 'heatmap'));
    document.getElementById('btn-an-war-load').addEventListener('click', loadWarLeaderboard);
    document.getElementById('btn-war-prev').addEventListener('click', () => { warPage--; loadWarLeaderboard(); });
    document.getElementById('btn-war-next').addEventListener('click', () => { warPage++; loadWarLeaderboard(); });
    // WAR slider labels
    ['repl', 'wb', 'wbr', 'wf', 'wp'].forEach(key => {
      const el = document.getElementById(`an-war-${key}`);
      if (el) el.addEventListener('input', () => {
        const suffix = key === 'repl' ? '%' : '';
        document.getElementById(`an-war-${key}-val`).textContent = el.value + suffix;
      });
    });

    // Analytics (advanced)
    document.getElementById('btn-an-reg-load').addEventListener('click', loadMultiRegression);
    document.getElementById('an-reg-cat').addEventListener('change', () => populateStatDropdown('an-reg'));
    document.getElementById('btn-an-sens-load').addEventListener('click', loadSensitivity);
    document.getElementById('an-sens-cat').addEventListener('change', () => { populateAttrDropdown('an-sens'); populateStatDropdown('an-sens'); });
    document.getElementById('btn-an-xs-load').addEventListener('click', loadXStats);
    document.getElementById('btn-an-int-load').addEventListener('click', loadInteractions);
    document.getElementById('an-int-cat').addEventListener('change', () => { populateAttrDropdown('an-int'); populateStatDropdown('an-int'); });
    document.getElementById('btn-an-dash-load').addEventListener('click', loadStatDashboard);
    document.getElementById('an-dash-cat').addEventListener('change', () => populateStatDropdown('an-dash'));
    document.getElementById('btn-an-arch-load').addEventListener('click', loadArchetypes);
    document.getElementById('btn-an-pt-load').addEventListener('click', loadPitchTypes);
    document.getElementById('btn-an-dp-load').addEventListener('click', loadDefensivePositions);
    document.getElementById('btn-an-ct-load').addEventListener('click', loadContactBreakdown);
    document.querySelectorAll('.an-ct-leader-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.an-ct-leader-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderContactLeaders(btn.dataset.leader);
      });
    });

    // Weight Calibration extras
    document.getElementById('btn-cal-recompute-ovr').addEventListener('click', recomputeDisplayOvr);
    document.getElementById('btn-cal-preview').addEventListener('click', loadPlayerPreview);
    initPlayerPreviewCascade();

    // Gameplan Audit
    document.getElementById('btn-gpa-load').addEventListener('click', loadGameplanAudit);
    document.getElementById('btn-gpa-edit-toggle').addEventListener('click', () => _gpaSetEditMode(!_gpaEditMode));
    document.querySelectorAll('.gpa-save-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const section = btn.dataset.section;
        if (section === 'defense') _gpaSaveDefense();
        else if (section === 'rotation') _gpaSaveRotation();
        else if (section === 'bullpen') _gpaSaveBullpen();
        else if (section === 'strategy') _gpaSaveStrategy();
        else if (section === 'lineup') _gpaSaveLineup();
        else if (section === 'playerstrat') _gpaSaveAllPlayerStrats();
      });
    });

    // Stamina
    document.getElementById('btn-stam-ov-load').addEventListener('click', loadStaminaOverview);
    document.getElementById('btn-stam-tm-load').addEventListener('click', loadStaminaTeamDetail);
    document.getElementById('btn-stam-av-load').addEventListener('click', loadStaminaAvailability);
    document.getElementById('btn-stam-con-load').addEventListener('click', loadStaminaConsumption);
    document.getElementById('btn-stam-fl-load').addEventListener('click', loadStaminaFlow);

    // Rankings
    document.getElementById('btn-rank-elo-load').addEventListener('click', loadRankingsElo);
    document.getElementById('btn-rank-pow-load').addEventListener('click', loadRankingsPower);
    document.getElementById('btn-rank-rpi-load').addEventListener('click', loadRankingsRpi);
    document.getElementById('btn-rank-pyth-load').addEventListener('click', loadRankingsPyth);
    document.getElementById('btn-rank-race-load').addEventListener('click', loadRankingsRace);

    // DB Storage
    document.getElementById('btn-db-storage-load').addEventListener('click', loadDbStorage);

    // FA Orphan Sweep
    const btnOrphanScan = document.getElementById('btn-orphan-scan');
    if (btnOrphanScan) btnOrphanScan.addEventListener('click', scanForOrphans);
    const btnOrphanFix = document.getElementById('btn-orphan-fix');
    if (btnOrphanFix) btnOrphanFix.addEventListener('click', fixOrphans);

    // Schedule Generator
    document.getElementById('btn-sched-report').addEventListener('click', loadScheduleReport);
    document.getElementById('btn-sched-validate').addEventListener('click', validateSchedule);
    document.getElementById('btn-sched-generate').addEventListener('click', generateSchedule);
    document.getElementById('btn-sched-clear').addEventListener('click', clearSchedule);
    document.getElementById('btn-sched-add-series').addEventListener('click', addScheduleSeries);
    document.getElementById('sched-level').addEventListener('change', onSchedLevelChange);

    // Schedule Viewer
    document.getElementById('btn-sv-load').addEventListener('click', () => { svCurrentPage = 1; loadScheduleViewer(); });
    document.getElementById('btn-sv-prev').addEventListener('click', () => { svCurrentPage--; loadScheduleViewer(); });
    document.getElementById('btn-sv-next').addEventListener('click', () => { svCurrentPage++; loadScheduleViewer(); });
    document.getElementById('btn-sv-quality').addEventListener('click', loadScheduleQuality);
    document.getElementById('btn-sv-add-series').addEventListener('click', addViewerSeries);
    document.getElementById('btn-sv-swap-ooc').addEventListener('click', swapOocOpponents);

    // Arrow key navigation for sandbox chart
    document.addEventListener('keydown', (e) => {
      if (currentSection !== 'pe-sandbox' || !sandboxData) return;

      const abilitySelect = document.getElementById('sandbox-ability-select');
      const hlSelect = document.getElementById('sandbox-highlight-player');
      const showPlayers = document.getElementById('sandbox-show-players').checked;

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        const opts = Array.from(abilitySelect.options);
        let idx = abilitySelect.selectedIndex;
        idx = e.key === 'ArrowUp' ? idx - 1 : idx + 1;
        if (idx < 0) idx = opts.length - 1;
        if (idx >= opts.length) idx = 0;
        abilitySelect.selectedIndex = idx;
        populateSandboxGradeFilter();
        renderSandboxChart();
      }

      if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && showPlayers) {
        e.preventDefault();
        const opts = Array.from(hlSelect.options);
        if (opts.length <= 1) return;
        let idx = hlSelect.selectedIndex;
        idx = e.key === 'ArrowLeft' ? idx - 1 : idx + 1;
        if (idx < 0) idx = opts.length - 1;
        if (idx >= opts.length) idx = 0;
        hlSelect.selectedIndex = idx;
        renderSandboxChart();
      }
    });
  }

  // Navigation
  function goTo(section) {
    currentSection = section;

    // Update nav items
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.section === section);
    });

    // Update sections
    document.querySelectorAll('.section').forEach(sec => {
      sec.classList.toggle('active', sec.id === `section-${section}`);
    });

    // Update title
    const titles = {
      dashboard: 'Dashboard',
      synthetic: 'Synthetic Games',
      tasks: 'Background Tasks',
      simulate: 'Simulate Week',
      timestamp: 'Timestamp',
      organizations: 'Organizations',
      teams: 'Teams',
      players: 'Players',
      cache: 'Cache Manager',
      sql: 'SQL Console',
      health: 'System Health',
      'rating-config': 'Rating Config',
      'tx-roster': 'Roster Moves',
      'tx-trades': 'Trades',
      'tx-log': 'Transaction Log',
      'roster-compliance': 'Roster Compliance',
      'pe-generate': 'Player Generation',
      'pe-progress': 'Player Progression',
      'pe-sandbox': 'Progression Sandbox',
      'tx-eos': 'End of Season',
      'tx-amateur': 'Amateur Seeding',
      'schedule-gen': 'Schedule Generator',
      'schedule-viewer': 'Schedule Viewer',
      migrations: 'Migrations',
      'analytics-batting': 'Batting Correlations',
      'analytics-pitching': 'Pitching Correlations',
      'analytics-defense': 'Defensive Analysis',
      'analytics-war': 'WAR Leaderboard',
      'analytics-regression': 'Multi-Regression',
      'analytics-sensitivity': 'Sensitivity Curves',
      'analytics-xstats': 'xStats / Residuals',
      'analytics-interactions': 'Interaction Effects',
      'analytics-dashboard': 'Stat Tuning Dashboard',
      'analytics-archetypes': 'Archetype Validation',
      'analytics-pitchtypes': 'Pitch Type Analysis',
      'analytics-defpos': 'Defensive Positions',
      'stamina-overview': 'Stamina Overview',
      'stamina-team': 'Team Stamina Detail',
      'stamina-availability': 'Pitcher Availability',
      'stamina-consumption': 'Consumption Analysis',
      'stamina-flow': 'Stamina Flow History',
      'db-storage': 'DB Storage',
      'batting-lab': 'Batting Lab',
      'recruiting-admin': 'Recruiting Admin',
      'draft-admin': 'Draft Administration',
      'ifa-admin': 'IFA Administration',
      'gameplan-audit': 'Gameplan Audit',
      'tutorial-content': 'Tutorial Editor',
    };
    elements.pageTitle.textContent = titles[section] || section;

    // Load section data
    switch (section) {
      case 'dashboard':
        refreshDashboard();
        break;
      case 'tasks':
        loadTasks();
        break;
      case 'simulate':
        refreshSimState();
        break;
      case 'timestamp':
        loadTimestamp();
        break;
      case 'organizations':
        loadOrganizations();
        break;
      case 'teams':
        loadTeams();
        break;
      case 'health':
        checkHealth();
        loadRoutes();
        break;
      case 'rating-config':
        loadRatingConfigSummary();
        break;
      case 'tx-roster':
        loadRosterMoves();
        break;
      case 'tx-trades':
        loadTradeBuilder();
        break;
      case 'tx-log':
        loadTransactionLog();
        break;
      case 'roster-compliance':
        loadRosterCompliance();
        break;
      case 'tx-eos':
        loadEndOfSeason();
        break;
      case 'tx-amateur':
        loadAmateurPreview();
        break;
      case 'pe-generate':
        loadGeneration();
        break;
      case 'pe-progress':
        loadProgression();
        break;
      case 'pe-sandbox':
        break;
      case 'schedule-gen':
        loadScheduleReport();
        break;
      case 'schedule-viewer':
        break;
      case 'analytics-batting':
      case 'analytics-pitching':
      case 'analytics-defense':
      case 'analytics-war':
      case 'analytics-regression':
      case 'analytics-sensitivity':
      case 'analytics-xstats':
      case 'analytics-interactions':
      case 'analytics-dashboard':
      case 'analytics-archetypes':
      case 'analytics-pitchtypes':
      case 'analytics-defpos':
      case 'analytics-contact':
      case 'analytics-hr-depth':
        loadAnalyticsLeagueYears(section);
        break;
      case 'weight-calibration':
        loadCalibrationInit();
        break;
      case 'stamina-overview':
      case 'stamina-team':
      case 'stamina-availability':
      case 'stamina-consumption':
      case 'stamina-flow':
        loadStaminaLeagueYears(section);
        break;
      case 'rankings-elo':
      case 'rankings-power':
      case 'rankings-rpi':
      case 'rankings-pyth':
      case 'rankings-race':
        loadRankingsLeagueYears(section);
        break;
      case 'playoffs':
        loadSpecialEventLeagueYears('po-lyid');
        break;
      case 'allstar':
        loadSpecialEventLeagueYears('as-lyid');
        break;
      case 'wbc':
        loadSpecialEventLeagueYears('wbc-lyid');
        break;
      case 'recruiting':
        loadSpecialEventLeagueYears('rec-lyid');
        loadRecruitingState();
        break;
      case 'recruiting-admin':
        loadSpecialEventLeagueYears('radm-lyid');
        loadRecruitingAdmin();
        break;
      case 'draft-admin':
        loadSpecialEventLeagueYears('dft-lyid');
        loadDraftAdmin();
        break;
      case 'ifa-admin':
        loadSpecialEventLeagueYears('ifa-lyid');
        loadIfaAdmin();
        break;
      case 'batting-lab':
        loadBlabHistory();
        break;
      case 'gameplan-audit':
        break;
      case 'tutorial-content':
        loadTutorialManifest();
        break;
    }

    // Close mobile sidebar
    elements.sidebar.classList.remove('open');
  }

  // Auth - uses session-based login via /admin/login
  function login() {
    const password = elements.adminPassword.value;

    fetch(`${ADMIN_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
      credentials: 'include',  // Important for session cookies
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          isAuthenticated = true;
          updateAuthUI();
          alert('Logged in successfully');
        } else {
          throw new Error(data.error || 'Login failed');
        }
      })
      .catch(err => {
        alert('Login failed: ' + err.message);
      });
  }

  function logout() {
    fetch(`${ADMIN_BASE}/logout`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(() => {
        isAuthenticated = false;
        updateAuthUI();
      })
      .catch(() => {
        isAuthenticated = false;
        updateAuthUI();
      });
  }

  function updateAuthUI() {
    const statusDot = elements.authStatus.querySelector('.status-dot');
    const writeToggle = document.getElementById('write-mode-toggle');
    if (isAuthenticated) {
      statusDot.classList.remove('offline');
      statusDot.classList.add('online');
      elements.authText.textContent = 'Authenticated';
      elements.btnLogin.style.display = 'none';
      elements.btnLogout.style.display = 'inline-block';
      elements.adminPassword.style.display = 'none';
      writeToggle.style.display = '';
    } else {
      statusDot.classList.remove('online');
      statusDot.classList.add('offline');
      elements.authText.textContent = 'Not logged in';
      elements.btnLogin.style.display = 'inline-block';
      elements.btnLogout.style.display = 'none';
      elements.adminPassword.style.display = 'inline-block';
      writeToggle.style.display = 'none';
    }
  }

  function checkAuth() {
    // Check if session is still valid by calling /admin/me
    fetch(`${ADMIN_BASE}/me`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.admin === true) {
          isAuthenticated = true;
          updateAuthUI();
          // Sync write mode checkbox
          const cb = document.getElementById('write-mode-cb');
          cb.checked = !!data.write_mode;
          _updateWriteLabel(cb.checked);
        }
      })
      .catch(() => {
        // Not logged in, that's fine
      });
  }

  function _updateWriteLabel(on) {
    const label = document.getElementById('write-mode-label');
    label.textContent = on ? 'Write Mode ON' : 'Write Mode';
    label.style.color = on ? '#ff9800' : '#bbb';
  }

  // Dashboard
  function refreshDashboard() {
    // Load timestamp
    fetch(`${API_BASE}/games/timestamp`)
      .then(r => r.json())
      .then(data => {
        document.getElementById('dash-season').textContent = `Season ${data.season || '--'}`;
        document.getElementById('dash-week').textContent = `Week ${data.week || '--'}`;
      })
      .catch(() => {
        document.getElementById('dash-season').textContent = 'Error';
        document.getElementById('dash-week').textContent = 'Could not load';
      });

    // Load tasks count
    fetch(`${API_BASE}/games/tasks`)
      .then(r => r.json())
      .then(data => {
        const tasks = data.tasks || [];
        const running = tasks.filter(t => t.status === 'running' || t.status === 'pending').length;
        document.getElementById('dash-tasks').textContent = running;
      })
      .catch(() => {
        document.getElementById('dash-tasks').textContent = '--';
      });

    // Check DB - use /healthz endpoint
    fetch('/healthz')
      .then(r => r.json())
      .then(data => {
        document.getElementById('dash-db').textContent = data.status === 'ok' ? 'OK' : 'Error';
        document.getElementById('dash-db-status').textContent = data.status || 'Unknown';
      })
      .catch(() => {
        document.getElementById('dash-db').textContent = 'Error';
        document.getElementById('dash-db-status').textContent = 'Could not connect';
      });
  }

  // Synthetic Games
  function runSynthetic(async) {
    const count = parseInt(document.getElementById('syn-count').value) || 100;
    const level = parseInt(document.getElementById('syn-level').value) || 9;
    const seed = document.getElementById('syn-seed').value || null;

    if (async) {
      // Async mode
      let url = `${API_BASE}/games/debug/synthetic-async?count=${count}&level=${level}`;
      if (seed) url += `&seed=${seed}`;

      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (data.task_id) {
            syntheticTaskId = data.task_id;
            showSyntheticProgress();
            pollSyntheticTask();
          } else {
            alert('Error starting task: ' + JSON.stringify(data));
          }
        })
        .catch(err => alert('Error: ' + err.message));
    } else {
      // Sync mode
      if (count > 200) {
        if (!confirm('Warning: Generating more than 200 games synchronously may cause timeouts. Continue?')) {
          return;
        }
      }

      const url = `${API_BASE}/games/debug/synthetic?count=${count}&level=${level}${seed ? '&seed=' + seed : ''}`;

      showSyntheticProgress();
      document.getElementById('syn-status').textContent = 'Generating (sync mode)...';

      fetch(url)
        .then(r => r.json())
        .then(data => {
          document.getElementById('syn-progress-bar').style.width = '100%';
          document.getElementById('syn-progress-text').textContent = `${data.length || 0} games`;
          document.getElementById('syn-progress-pct').textContent = '100%';
          document.getElementById('syn-status').textContent = 'Complete!';

          // Create download blob
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const downloadUrl = URL.createObjectURL(blob);
          document.getElementById('syn-download-link').href = downloadUrl;
          document.getElementById('syn-download-link').download = `synthetic_${count}_games.json`;
          document.getElementById('syn-download-group').style.display = 'flex';
        })
        .catch(err => {
          document.getElementById('syn-status').textContent = 'Error: ' + err.message;
        });
    }
  }

  function showSyntheticProgress() {
    document.getElementById('syn-progress-card').style.display = 'block';
    document.getElementById('syn-progress-bar').style.width = '0%';
    document.getElementById('syn-progress-text').textContent = '0 / 0';
    document.getElementById('syn-progress-pct').textContent = '0%';
    document.getElementById('syn-status').textContent = 'Starting...';
    document.getElementById('syn-download-group').style.display = 'none';
  }

  function pollSyntheticTask() {
    if (taskPollInterval) clearInterval(taskPollInterval);

    taskPollInterval = setInterval(() => {
      fetch(`${API_BASE}/games/tasks/${syntheticTaskId}`)
        .then(r => r.json())
        .then(data => {
          const progress = data.progress || 0;
          const total = data.total || 1;
          const pct = Math.round((progress / total) * 100);

          document.getElementById('syn-progress-bar').style.width = pct + '%';
          document.getElementById('syn-progress-text').textContent = `${progress} / ${total}`;
          document.getElementById('syn-progress-pct').textContent = pct + '%';
          document.getElementById('syn-status').textContent = `Status: ${data.status}`;

          if (data.status === 'complete') {
            clearInterval(taskPollInterval);
            document.getElementById('syn-download-link').href = `${API_BASE}/games/tasks/${syntheticTaskId}/download`;
            document.getElementById('syn-download-link').removeAttribute('download');
            document.getElementById('syn-download-group').style.display = 'flex';
          } else if (data.status === 'failed') {
            clearInterval(taskPollInterval);
            document.getElementById('syn-status').textContent = 'Failed: ' + (data.error || 'Unknown error');
          }
        })
        .catch(err => {
          document.getElementById('syn-status').textContent = 'Poll error: ' + err.message;
        });
    }, 1000);
  }

  // Tasks
  function loadTasks() {
    const tbody = document.getElementById('tasks-tbody');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Loading...</td></tr>';

    fetch(`${API_BASE}/games/tasks`)
      .then(r => r.json())
      .then(data => {
        const tasks = data.tasks || [];
        if (tasks.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No tasks found</td></tr>';
          return;
        }

        tbody.innerHTML = tasks.map(task => {
          const pct = task.total > 0 ? Math.round((task.progress / task.total) * 100) : 0;
          const created = new Date(task.created_at * 1000).toLocaleString();
          const statusClass = {
            pending: 'badge-info',
            running: 'badge-warning',
            complete: 'badge-success',
            failed: 'badge-danger',
          }[task.status] || '';

          let actions = '';
          if (task.status === 'complete') {
            actions = `<a href="${API_BASE}/games/tasks/${task.task_id}/download" class="btn btn-sm btn-primary" target="_blank">Download</a>`;
          }
          actions += ` <button class="btn btn-sm btn-danger" onclick="App.deleteTask('${task.task_id}')">Delete</button>`;

          return `
            <tr>
              <td><code>${task.task_id}</code></td>
              <td>${task.task_type}</td>
              <td><span class="badge ${statusClass}">${task.status}</span></td>
              <td>${task.progress}/${task.total} (${pct}%)</td>
              <td>${created}</td>
              <td>${actions}</td>
            </tr>
          `;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function deleteTask(taskId) {
    if (!confirm(`Delete task ${taskId}?`)) return;

    fetch(`${API_BASE}/games/tasks/${taskId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(() => loadTasks())
      .catch(err => alert('Error: ' + err.message));
  }

  // Simulation — dynamic level loader
  function loadSimLevels() {
    const year = document.getElementById('sim-year').value;
    const week = document.getElementById('sim-week').value;
    const sel = document.getElementById('sim-level');

    if (!year || !week) return;

    sel.innerHTML = '<option value="">Loading...</option>';

    fetch(`${API_BASE}/schedule/week-levels?league_year_id=${year}&season_week=${week}`, {
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        const levels = data.levels || [];
        sel.innerHTML = '<option value="">All levels</option>';
        levels.forEach(l => {
          sel.innerHTML += `<option value="${l.level}">${l.level} - ${l.name}</option>`;
        });
        if (levels.length === 0) {
          sel.innerHTML = '<option value="">No games scheduled</option>';
        }
      })
      .catch(() => {
        sel.innerHTML = '<option value="">Error loading levels</option>';
      });
  }

  document.getElementById('sim-year').addEventListener('change', loadSimLevels);
  document.getElementById('sim-week').addEventListener('change', loadSimLevels);
  loadSimLevels();  // initial load

  function runSimulation(execute) {
    const year = document.getElementById('sim-year').value;
    const week = document.getElementById('sim-week').value;
    const level = document.getElementById('sim-level').value;

    const resultBox = document.getElementById('sim-result');
    resultBox.textContent = 'Loading...';

    if (execute) {
      // POST — send JSON body
      const body = { league_year_id: parseInt(year), season_week: parseInt(week) };
      if (level) body.league_level = parseInt(level);

      fetch(`${API_BASE}/games/simulate-week`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
        .then(r => r.json())
        .then(data => {
          resultBox.textContent = JSON.stringify(data, null, 2);
          refreshSimState(); // refresh state bar after manual sim
        })
        .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
    } else {
      // GET — path params
      let url = `${API_BASE}/games/simulate-week/${year}/${week}`;
      if (level) url += `?league_level=${level}`;

      fetch(url, { credentials: 'include' })
        .then(r => r.json())
        .then(data => {
          resultBox.textContent = JSON.stringify(data, null, 2);
          refreshSimState(); // refresh state bar after sim
        })
        .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
    }
  }

  // ── Shared timestamp data ───────────────────────────────────────────
  let _tsData = null;

  // ── Simulate Section — state-aware control bar ─────────────────────
  function refreshSimState() {
    fetch(`${API_BASE}/games/timestamp`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        _tsData = data;
        renderSimState(data);
        // Also sync the manual sim inputs
        if (data.Week) document.getElementById('sim-week').value = data.Week;
        if (data.LeagueYearID) document.getElementById('sim-year').value = data.LeagueYearID;
        loadSimLevels();
      })
      .catch(err => {
        console.error('refreshSimState failed:', err);
      });
  }

  function renderSimState(ts) {
    const phase = ts.Phase || 'UNKNOWN';
    const phaseBadge = document.getElementById('sim-phase-badge');
    const weekBadge = document.getElementById('sim-week-badge');

    if (phaseBadge) {
      phaseBadge.textContent = PHASE_LABEL[phase] || phase;
      phaseBadge.className = 'badge ' + (PHASE_BADGE_CLASS[phase] || 'badge-pending');
    }
    if (weekBadge) {
      weekBadge.textContent = `Week ${ts.Week || '--'} / ${ts.TotalWeeks || '--'}`;
    }

    // Game flags
    const flagsEl = document.getElementById('sim-game-flags');
    if (flagsEl) {
      const flags = [
        ['Games A', ts.GamesARan], ['Games B', ts.GamesBRan],
        ['Games C', ts.GamesCRan], ['Games D', ts.GamesDRan],
      ];
      flagsEl.innerHTML = flags.map(([label, val]) => `
        <div class="kv-row">
          <div class="kv-key">${label}</div>
          <div class="kv-val"><span class="badge ${val ? 'badge-success' : 'badge-pending'}">${val ? 'Complete' : 'Pending'}</span></div>
        </div>
      `).join('');
    }

    // Action buttons
    const btnContainer = document.getElementById('sim-action-buttons');
    if (!btnContainer) return;

    const allRan = ts.GamesARan && ts.GamesBRan && ts.GamesCRan && ts.GamesDRan;
    const anyRan = ts.GamesARan || ts.GamesBRan || ts.GamesCRan || ts.GamesDRan;
    const running = ts.RunGames;

    const buttons = [];

    if (phase === 'REGULAR_SEASON' || phase === 'PLAYOFFS') {
      // Per-subweek buttons
      const subweeks = [
        { key: 'a', flag: ts.GamesARan },
        { key: 'b', flag: ts.GamesBRan },
        { key: 'c', flag: ts.GamesCRan },
        { key: 'd', flag: ts.GamesDRan },
      ];
      const pendingSw = subweeks.filter(s => !s.flag);
      if (!running && pendingSw.length > 0) {
        // Individual subweek buttons
        pendingSw.forEach(s => {
          buttons.push(`<button class="btn btn-warning" onclick="simSubweek('${s.key}')">Sim Subweek ${s.key.toUpperCase()}</button>`);
        });
        // Run all remaining button
        if (pendingSw.length > 1) {
          buttons.push(`<button class="btn btn-warning" onclick="simQuickRun()">Sim All Remaining</button>`);
        }
      }
      if (allRan) {
        buttons.push(`<button class="btn btn-primary" onclick="simAdvanceWeek()">Advance to Week ${(ts.Week || 0) + 1}</button>`);
      }
      if (anyRan) {
        buttons.push(`<button class="btn btn-secondary" onclick="simResetWeek()">Reset Week Games</button>`);
      }
      if (ts.Week >= (ts.TotalWeeks || 25) && allRan) {
        buttons.push(`<button class="btn btn-danger" onclick="document.querySelector('[data-section=timestamp]').click()">End Season &rarr;</button>`);
      }
    } else {
      buttons.push(`<button class="btn btn-secondary" onclick="document.querySelector('[data-section=timestamp]').click()">Go to Timestamp &rarr;</button>`);
    }

    btnContainer.innerHTML = buttons.length
      ? `<div class="button-group">${buttons.join('')}</div>`
      : '<p class="text-muted">No simulation actions available.</p>';
  }

  function simSubweek(sw) {
    const ts = _tsData;
    if (!ts) return;
    const resultBox = document.getElementById('sim-action-result');
    resultBox.style.display = 'block';
    resultBox.textContent = `Simulating subweek ${sw.toUpperCase()} of week ${ts.Week}...`;

    const body = { league_year_id: ts.LeagueYearID, season_week: ts.Week, subweek: sw };

    fetch(`${API_BASE}/games/simulate-subweek`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          const count = (data.subweeks && data.subweeks[sw]) ? data.subweeks[sw].length : 0;
          resultBox.textContent = `Subweek ${sw.toUpperCase()}: ${count} game(s) simulated`;
        }
        refreshSimState();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }
  window.simSubweek = simSubweek;

  function simQuickRun() {
    const ts = _tsData;
    if (!ts) return;
    const resultBox = document.getElementById('sim-action-result');
    resultBox.style.display = 'block';
    resultBox.textContent = `Simulating week ${ts.Week}...`;

    const body = { league_year_id: ts.LeagueYearID, season_week: ts.Week };

    fetch(`${API_BASE}/games/simulate-week`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        refreshSimState();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }
  window.simQuickRun = simQuickRun;

  function simAdvanceWeek() {
    const resultBox = document.getElementById('sim-action-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Advancing week...';

    fetch(`${API_BASE}/games/advance-week`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        refreshSimState();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }
  window.simAdvanceWeek = simAdvanceWeek;

  function simResetWeek() {
    const resultBox = document.getElementById('sim-action-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Resetting week games...';

    fetch(`${API_BASE}/games/reset-week`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        refreshSimState();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }
  window.simResetWeek = simResetWeek;

  // Timestamp — phase-aware UI

  const PHASE_BADGE_CLASS = {
    REGULAR_SEASON: 'badge-success',
    PLAYOFFS: 'badge-running',
    OFFSEASON: 'badge-warning',
    FREE_AGENCY: 'badge-info',
    DRAFT: 'badge-running',
    RECRUITING: 'badge-pending',
  };

  const PHASE_LABEL = {
    REGULAR_SEASON: 'Regular Season',
    PLAYOFFS: 'Playoffs',
    OFFSEASON: 'Offseason',
    FREE_AGENCY: 'Free Agency',
    DRAFT: 'Draft',
    RECRUITING: 'Recruiting',
  };

  const ACTION_CONFIG = {
    simulate_week:      { label: 'Simulate Week',       cls: 'btn-warning',   endpoint: null },
    advance_week:       { label: 'Advance Week',        cls: 'btn-warning',   endpoint: '/games/advance-week' },
    reset_week:         { label: 'Reset Week Games',    cls: 'btn-secondary', endpoint: '/games/reset-week' },
    end_season:         { label: 'End Season',          cls: 'btn-danger',    endpoint: null, card: 'ts-end-season-card' },
    start_free_agency:  { label: 'Start Free Agency',   cls: 'btn-primary',   endpoint: '/games/start-free-agency' },
    advance_fa_round:   { label: 'Advance FA Round',    cls: 'btn-warning',   endpoint: '/games/advance-fa-round' },
    end_free_agency:    { label: 'End Free Agency',     cls: 'btn-secondary', endpoint: '/games/end-free-agency' },
    start_draft:        { label: 'Start Draft',         cls: 'btn-primary',   endpoint: '/games/start-draft' },
    end_draft:          { label: 'End Draft',           cls: 'btn-secondary', endpoint: '/games/end-draft' },
    start_recruiting:   { label: 'Start Recruiting',    cls: 'btn-primary',   endpoint: '/games/start-recruiting' },
    end_recruiting:     { label: 'End Recruiting',      cls: 'btn-secondary', endpoint: '/games/end-recruiting' },
    start_new_season:   { label: 'Start New Season',    cls: 'btn-primary',   endpoint: null, card: 'ts-new-season-card' },
    set_phase:          { label: 'Phase Override',      cls: 'btn-secondary', endpoint: null, scroll: 'btn-set-phase' },
  };

  function loadTimestamp() {
    fetch(`${API_BASE}/games/timestamp`)
      .then(r => r.json())
      .then(data => {
        _tsData = data;
        renderTimestamp(data);
      })
      .catch(err => {
        const badge = document.getElementById('ts-phase-badge');
        if (badge) {
          badge.textContent = 'Error';
          badge.className = 'badge badge-danger';
        }
        console.error('loadTimestamp failed:', err);
      });
  }

  function renderTimestamp(ts) {
    // Phase badge
    const badge = document.getElementById('ts-phase-badge');
    const phase = ts.Phase || 'UNKNOWN';
    if (!badge) {
      // Fallback: old HTML without new elements — dump raw JSON
      const container = document.getElementById('timestamp-data');
      if (container) {
        container.innerHTML = Object.entries(ts).map(([k, v]) =>
          `<div class="kv-row"><div class="kv-key">${k}</div><div class="kv-val">${JSON.stringify(v)}</div></div>`
        ).join('');
      }
      return;
    }
    badge.textContent = PHASE_LABEL[phase] || phase;
    badge.className = 'badge ' + (PHASE_BADGE_CLASS[phase] || 'badge-pending');

    // Overview cards
    document.getElementById('ts-season').textContent = ts.Season || '--';
    document.getElementById('ts-season-sub').textContent = `Season ID: ${ts.SeasonID || '--'}`;
    document.getElementById('ts-week').textContent = `${ts.Week || '--'} / ${ts.TotalWeeks || '--'}`;
    document.getElementById('ts-week-sub').textContent = ts.RunGames ? 'Simulating...' : (ts.GamesARan && ts.GamesBRan && ts.GamesCRan && ts.GamesDRan ? 'All games complete' : 'Ready');

    // Game flags
    const flagsContainer = document.getElementById('ts-game-flags');
    const flags = [
      ['Games A', ts.GamesARan], ['Games B', ts.GamesBRan],
      ['Games C', ts.GamesCRan], ['Games D', ts.GamesDRan],
    ];
    flagsContainer.innerHTML = flags.map(([label, val]) => `
      <div class="kv-row">
        <div class="kv-key">${label}</div>
        <div class="kv-val"><span class="badge ${val ? 'badge-success' : 'badge-pending'}">${val ? 'Complete' : 'Pending'}</span></div>
      </div>
    `).join('');

    // Dynamic action buttons
    const actionsContainer = document.getElementById('ts-actions-container');
    const actions = ts.AvailableActions || [];
    const buttons = [];

    // Show/hide special cards
    document.getElementById('ts-end-season-card').style.display = actions.includes('end_season') ? 'block' : 'none';
    document.getElementById('ts-new-season-card').style.display = actions.includes('start_new_season') && phase === 'OFFSEASON' ? 'block' : 'none';

    for (const action of actions) {
      const cfg = ACTION_CONFIG[action];
      if (!cfg) continue;

      // Skip actions that have their own card (end_season, start_new_season)
      // but keep set_phase as a scroll-to link
      if (cfg.card) continue;

      if (cfg.endpoint) {
        buttons.push(`<button class="btn ${cfg.cls}" onclick="tsAction('${cfg.endpoint}', '${cfg.label}')">${cfg.label}</button>`);
      } else if (cfg.scroll) {
        buttons.push(`<button class="btn ${cfg.cls}" onclick="document.getElementById('${cfg.scroll}').scrollIntoView({behavior:'smooth'})">${cfg.label}</button>`);
      } else if (action === 'simulate_week') {
        buttons.push(`<button class="btn ${cfg.cls}" onclick="document.querySelector('[data-section=simulate]').click()">${cfg.label}</button>`);
      }
    }

    actionsContainer.innerHTML = buttons.length
      ? `<div class="button-group">${buttons.join('')}</div>`
      : '<p class="text-muted">No actions available in current state.</p>';
  }

  // Generic action caller for simple POST endpoints
  function tsAction(endpoint, label) {
    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = `${label}...`;

    fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        loadTimestamp();
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }
  // Expose to inline onclick
  window.tsAction = tsAction;

  function tsSetWeek() {
    const week = parseInt(document.getElementById('ts-set-week').value, 10);
    if (!week || week < 1) return;

    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = `Setting week to ${week}...`;

    fetch(`${API_BASE}/games/set-week`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ week }),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        loadTimestamp();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  function tsSetPhase() {
    const body = {};
    const offseason = document.getElementById('ts-offseason').value;
    const faLocked = document.getElementById('ts-fa-locked').value;
    const draftTime = document.getElementById('ts-draft-time').value;
    const recruitLocked = document.getElementById('ts-recruiting-locked').value;
    const faRound = document.getElementById('ts-fa-round').value;

    if (offseason !== '') body.is_offseason = offseason === 'true';
    if (faLocked !== '') body.is_free_agency_locked = faLocked === 'true';
    if (draftTime !== '') body.is_draft_time = draftTime === 'true';
    if (recruitLocked !== '') body.is_recruiting_locked = recruitLocked === 'true';
    if (faRound !== '') body.free_agency_round = parseInt(faRound, 10);

    if (Object.keys(body).length === 0) return;

    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = 'Applying phase override...';

    fetch(`${API_BASE}/games/set-phase`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        loadTimestamp();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  function tsEndSeason() {
    const yearId = parseInt(document.getElementById('ts-eos-year').value, 10);
    if (!yearId) return;

    if (!confirm('End the regular season? This runs contract processing and player progression.')) return;

    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = 'Ending season...';

    fetch(`${API_BASE}/games/end-season`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: yearId }),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        loadTimestamp();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  function tsStartNewSeason() {
    const yearId = parseInt(document.getElementById('ts-new-year').value, 10);
    if (!yearId) return;

    if (!confirm('Start a new season? This runs year-start financials and resets to week 1.')) return;

    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = 'Starting new season...';

    fetch(`${API_BASE}/games/start-new-season`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: yearId }),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        loadTimestamp();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  // Listed Positions — manual fill
  function fillListedPositions() {
    const resultBox = document.getElementById('listed-pos-result');
    resultBox.textContent = 'Filling listed positions...';

    fetch(`${ADMIN_BASE}/fill-listed-positions`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = data.ok
          ? `Done — ${data.total} players updated.`
          : `Error: ${data.message || 'unknown'}`;
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  // Default Gameplan Generation
  function generateDefaultGameplans() {
    const resultBox = document.getElementById('gameplan-gen-result');
    const level = document.getElementById('gp-level').value;
    const lyid = document.getElementById('gp-league-year').value;
    const overwrite = document.getElementById('gp-overwrite').checked;

    resultBox.textContent = `Generating default gameplans for level ${level}...`;

    fetch(`${ADMIN_BASE}/generate-default-gameplans`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        team_level: parseInt(level),
        league_year_id: parseInt(lyid),
        overwrite,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          let msg = `Done — ${data.teams_processed} teams processed, ${data.teams_skipped} skipped.`;
          if (data.errors && data.errors.length > 0) {
            msg += `\n${data.errors.length} errors:\n` +
              data.errors.map(e => `  Team ${e.team_id}: ${e.message}`).join('\n');
          }
          resultBox.textContent = msg;
        } else {
          resultBox.textContent = `Error: ${data.message || 'unknown'}`;
        }
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  // Season Archive
  function archiveSeason() {
    const resultBox = document.getElementById('season-archive-result');
    const lyid = document.getElementById('archive-league-year-id').value;
    const dryRun = document.getElementById('archive-dry-run').checked;

    if (!lyid) { resultBox.textContent = 'Please enter a League Year ID.'; return; }

    resultBox.textContent = dryRun
      ? `Counting rows for league_year_id ${lyid} (dry run)...`
      : `Archiving season data for league_year_id ${lyid}...`;

    fetch(`${ADMIN_BASE}/season/archive`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(lyid),
        dry_run: dryRun,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          const mode = data.dry_run ? 'DRY RUN' : 'ARCHIVED';
          let lines = [`${mode} — Season ${data.league_year} (ly_id ${data.league_year_id})\n`];
          if (data.tables) {
            lines.push('Tables:');
            for (const [table, info] of Object.entries(data.tables)) {
              if (typeof info === 'object' && info !== null) {
                const parts = Object.entries(info).map(([k, v]) => `${k}: ${v}`).join(', ');
                lines.push(`  ${table}: ${parts}`);
              }
            }
          }
          if (data.warnings && data.warnings.length > 0) {
            lines.push(`\nWarnings (${data.warnings.length}):`);
            data.warnings.forEach(w => lines.push(`  - ${w}`));
          }
          if (data.preserved) {
            lines.push(`\nPreserved: ${data.preserved.join(', ')}`);
          }
          resultBox.textContent = lines.join('\n');
        } else {
          resultBox.textContent = `Error: ${data.message || 'unknown'}`;
        }
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  // Run Season (background task with polling)
  let _seasonPollId = null;

  function runSeason() {
    const year = document.getElementById('season-run-year').value;
    const level = document.getElementById('season-run-level').value;
    const startWeek = document.getElementById('season-run-start').value;
    const endWeek = document.getElementById('season-run-end').value;
    const resultBox = document.getElementById('season-run-result');
    const progressWrap = document.getElementById('season-progress-wrap');
    const progressBar = document.getElementById('season-progress-bar');
    const progressText = document.getElementById('season-progress-text');

    if (!confirm(`Run season weeks ${startWeek}–${endWeek} for level ${level}? This may take a while.`)) return;

    resultBox.textContent = 'Starting...';
    progressWrap.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = '0 / 0';

    fetch(`${API_BASE}/games/run-season`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(year),
        league_level: parseInt(level),
        start_week: parseInt(startWeek),
        end_week: parseInt(endWeek),
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = 'Error: ' + (data.message || data.error);
          progressWrap.style.display = 'none';
          return;
        }
        const taskId = data.task_id;
        const total = data.total;
        resultBox.textContent = `Task started: ${taskId} (${total} weeks)`;
        progressText.textContent = `0 / ${total}`;

        // Poll for progress
        if (_seasonPollId) clearInterval(_seasonPollId);
        _seasonPollId = setInterval(() => {
          fetch(`${API_BASE}/games/tasks/${taskId}`, { credentials: 'include' })
            .then(r => {
              if (!r.ok) { clearInterval(_seasonPollId); _seasonPollId = null; return null; }
              return r.json();
            })
            .then(task => {
              if (!task) return;
              const progress = task.progress || 0;
              const pct = total > 0 ? Math.round((progress / total) * 100) : 0;
              progressBar.style.width = pct + '%';
              progressText.textContent = `${progress} / ${total} weeks`;

              if (task.status === 'complete' || task.status === 'COMPLETE') {
                clearInterval(_seasonPollId);
                _seasonPollId = null;
                progressBar.style.width = '100%';
                progressText.textContent = `${total} / ${total} weeks`;
                resultBox.textContent = JSON.stringify(task, null, 2);
                loadTimestamp();
              } else if (task.status === 'failed' || task.status === 'FAILED') {
                clearInterval(_seasonPollId);
                _seasonPollId = null;
                resultBox.textContent = 'FAILED: ' + (task.error || 'Unknown error');
                loadTimestamp();
              }
            })
            .catch(() => { clearInterval(_seasonPollId); _seasonPollId = null; });
        }, 3000);
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
        progressWrap.style.display = 'none';
      });
  }

  // Run All Levels (background task with polling)
  function runAllLevels() {
    const year = document.getElementById('season-run-year').value;
    const startWeek = document.getElementById('season-run-start').value;
    const endWeek = document.getElementById('season-run-end').value;
    const resultBox = document.getElementById('season-run-result');
    const progressWrap = document.getElementById('season-progress-wrap');
    const progressBar = document.getElementById('season-progress-bar');
    const progressText = document.getElementById('season-progress-text');

    const totalWeeks = parseInt(endWeek) - parseInt(startWeek) + 1;
    const totalSteps = totalWeeks * 7; // 7 levels

    if (!confirm(`Run ALL levels (9-3) for weeks ${startWeek}–${endWeek}? That's ${totalSteps} level-weeks. This will take a while.`)) return;

    resultBox.textContent = 'Starting all levels...';
    progressWrap.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = '0 / 0';

    fetch(`${API_BASE}/games/run-season-all`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(year),
        start_week: parseInt(startWeek),
        end_week: parseInt(endWeek),
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = 'Error: ' + (data.message || data.error);
          progressWrap.style.display = 'none';
          return;
        }
        const taskId = data.task_id;
        const total = data.total;
        resultBox.textContent = `Task started: ${taskId} (${total} level-weeks across 7 levels)`;
        progressText.textContent = `0 / ${total}`;

        if (_seasonPollId) clearInterval(_seasonPollId);
        _seasonPollId = setInterval(() => {
          fetch(`${API_BASE}/games/tasks/${taskId}`, { credentials: 'include' })
            .then(r => {
              if (!r.ok) { clearInterval(_seasonPollId); _seasonPollId = null; return null; }
              return r.json();
            })
            .then(task => {
              if (!task) return;
              const progress = task.progress || 0;
              const pct = total > 0 ? Math.round((progress / total) * 100) : 0;
              progressBar.style.width = pct + '%';

              const currentLevel = Math.floor(progress / totalWeeks);
              const levelNames = ['MLB', 'AAA', 'AA', 'High-A', 'A', 'Scraps', 'College'];
              const levelLabel = currentLevel < levelNames.length ? levelNames[currentLevel] : 'Done';
              progressText.textContent = `${progress} / ${total} (${levelLabel})`;

              if (task.status === 'complete' || task.status === 'COMPLETE') {
                clearInterval(_seasonPollId);
                _seasonPollId = null;
                progressBar.style.width = '100%';
                progressText.textContent = `${total} / ${total} (Complete)`;
                resultBox.textContent = JSON.stringify(task, null, 2);
                loadTimestamp();
              } else if (task.status === 'failed' || task.status === 'FAILED') {
                clearInterval(_seasonPollId);
                _seasonPollId = null;
                resultBox.textContent = 'FAILED: ' + (task.error || 'Unknown error');
                loadTimestamp();
              }
            })
            .catch(() => { clearInterval(_seasonPollId); _seasonPollId = null; });
        }, 3000);
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
        progressWrap.style.display = 'none';
      });
  }

  // Wipe Season
  function wipeSeason() {
    const year = document.getElementById('wipe-year').value;
    const level = document.getElementById('wipe-level').value;
    const resultBox = document.getElementById('wipe-result');

    const confirmation = prompt(
      'This will delete ALL simulation results, stats, fatigue, and injuries ' +
      'for this season. Type WIPE to confirm.'
    );
    if (confirmation !== 'WIPE') {
      resultBox.textContent = 'Wipe cancelled.';
      return;
    }

    resultBox.textContent = 'Wiping...';

    const body = { league_year_id: parseInt(year) };
    if (level) body.league_level = parseInt(level);

    fetch(`${API_BASE}/games/wipe-season`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        refreshSimState();
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // Rollback to Week
  function rollbackToWeek() {
    const year = document.getElementById('rollback-year').value;
    const week = document.getElementById('rollback-week').value;
    const resultBox = document.getElementById('rollback-to-week-result');

    const confirmation = prompt(
      `This will delete ALL simulation data from week ${week} onward ` +
      '(game results, stats, finances, injuries, waivers, FA auctions). ' +
      'Type ROLLBACK to confirm.'
    );
    if (confirmation !== 'ROLLBACK') {
      resultBox.textContent = 'Rollback cancelled.';
      return;
    }

    resultBox.textContent = 'Rolling back...';

    fetch(`${API_BASE}/games/rollback-to-week`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(year),
        target_week: parseInt(week),
      }),
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
        refreshSimState();
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // Organizations
  function loadOrganizations() {
    const select = document.getElementById('org-select');
    select.innerHTML = '<option value="">Loading...</option>';

    fetch(`${API_BASE}/organizations`)
      .then(r => r.json())
      .then(data => {
        const orgs = Array.isArray(data) ? data : (data.organizations || []);
        if (typeof orgs[0] === 'string') {
          // Array of abbreviations
          select.innerHTML = '<option value="">Select an organization...</option>' +
            orgs.map(abbr => `<option value="${abbr}">${abbr}</option>`).join('');
        } else {
          // Array of objects
          select.innerHTML = '<option value="">Select an organization...</option>' +
            orgs.map(org => `<option value="${org.organization_id || org.abbreviation || org.id}">${org.name || org.organization_name || org.abbreviation || 'Org ' + (org.organization_id || org.id)}</option>`).join('');
        }
      })
      .catch(err => {
        select.innerHTML = `<option value="">Error: ${err.message}</option>`;
      });
  }

  function loadOrgDetail() {
    const orgId = document.getElementById('org-select').value;
    const card = document.getElementById('org-detail-card');
    const detail = document.getElementById('org-detail');

    if (!orgId) {
      card.style.display = 'none';
      return;
    }

    card.style.display = 'block';
    detail.innerHTML = '<div class="kv-row"><div class="kv-key">Loading...</div></div>';

    // Try both endpoint formats
    fetch(`${API_BASE}/${encodeURIComponent(orgId)}/`)
      .then(r => {
        if (!r.ok) throw new Error('Not found');
        return r.json();
      })
      .then(data => {
        const item = Array.isArray(data) ? data[0] : data;
        if (!item) {
          detail.innerHTML = '<div class="kv-row"><div class="kv-key">No data</div></div>';
          return;
        }
        detail.innerHTML = Object.entries(item).map(([key, val]) => `
          <div class="kv-row">
            <div class="kv-key">${key}</div>
            <div class="kv-val">${typeof val === 'object' ? JSON.stringify(val) : val}</div>
          </div>
        `).join('');
      })
      .catch(err => {
        detail.innerHTML = `<div class="kv-row"><div class="kv-key">Error</div><div class="kv-val">${err.message}</div></div>`;
      });
  }

  // Teams
  function loadTeams() {
    const select = document.getElementById('team-select');
    select.innerHTML = '<option value="">Loading...</option>';

    fetch(`${API_BASE}/teams`)
      .then(r => r.json())
      .then(data => {
        const teams = Array.isArray(data) ? data : (data.teams || []);
        select.innerHTML = '<option value="">Select a team...</option>' +
          teams.map(team => {
            // Handle both string abbreviations and object formats
            if (typeof team === 'string') {
              return `<option value="${team}">${team}</option>`;
            }
            const id = team.team_abbrev || team.team_id || team.id || team.abbreviation;
            const name = team.name || team.team_name || team.team_abbrev || id;
            return `<option value="${id}">${name}</option>`;
          }).join('');
      })
      .catch(err => {
        select.innerHTML = `<option value="">Error: ${err.message}</option>`;
      });
  }

  function loadTeamDetail() {
    const teamId = document.getElementById('team-select').value;
    const card = document.getElementById('team-detail-card');
    const detail = document.getElementById('team-detail');
    const playersCard = document.getElementById('team-players-card');

    if (!teamId) {
      card.style.display = 'none';
      playersCard.style.display = 'none';
      return;
    }

    card.style.display = 'block';
    playersCard.style.display = 'none';
    detail.innerHTML = '<div class="kv-row"><div class="kv-key">Loading...</div></div>';

    fetch(`${API_BASE}/teams/${teamId}/`)
      .then(r => r.json())
      .then(data => {
        const item = Array.isArray(data) ? data[0] : data;
        if (!item) {
          detail.innerHTML = '<div class="kv-row"><div class="kv-key">No data</div></div>';
          return;
        }
        detail.innerHTML = Object.entries(item).map(([key, val]) => `
          <div class="kv-row">
            <div class="kv-key">${key}</div>
            <div class="kv-val">${typeof val === 'object' ? JSON.stringify(val) : val}</div>
          </div>
        `).join('');
      })
      .catch(err => {
        detail.innerHTML = `<div class="kv-row"><div class="kv-key">Error</div><div class="kv-val">${err.message}</div></div>`;
      });
  }

  function loadTeamPlayers() {
    const teamId = document.getElementById('team-select').value;
    if (!teamId) return;

    const card = document.getElementById('team-players-card');
    const pre = document.getElementById('team-players');

    card.style.display = 'block';
    pre.textContent = 'Loading...';

    fetch(`${API_BASE}/teams/${teamId}/players`)
      .then(r => r.json())
      .then(data => {
        pre.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        pre.textContent = 'Error: ' + err.message;
      });
  }

  // Players
  function lookupPlayer() {
    const playerId = document.getElementById('player-id').value;
    if (!playerId) {
      alert('Please enter a player ID');
      return;
    }

    const card = document.getElementById('player-detail-card');
    const pre = document.getElementById('player-detail');

    card.style.display = 'block';
    pre.textContent = 'Loading...';

    fetch(`${API_BASE}/players/${playerId}`)
      .then(r => r.json())
      .then(data => {
        pre.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        pre.textContent = 'Error: ' + err.message;
      });
  }

  // Cache
  let lastCacheCleared = null;

  function clearCachesCore() {
    return fetch(`${ADMIN_BASE}/clear-caches`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => {
        if (r.status === 401) {
          throw new Error('Unauthorized - please login first');
        }
        return r.json();
      })
      .then(data => {
        if (data.ok) {
          lastCacheCleared = new Date();
          updateCacheStatusDisplay(data.cleared);
        }
        return data;
      });
  }

  function updateCacheStatusDisplay(cleared) {
    // Update Cache Manager page
    const statusVal = document.getElementById('cache-status-value');
    const statusSub = document.getElementById('cache-status-sub');
    const lastVal = document.getElementById('cache-last-cleared');
    const lastSub = document.getElementById('cache-last-cleared-sub');

    if (statusVal) {
      const hadData = cleared && Object.values(cleared).some(v => v === true);
      statusVal.textContent = hadData ? 'Cleared' : 'Already Empty';
      statusSub.textContent = cleared
        ? Object.entries(cleared).map(([k, v]) => `${k}: ${v ? 'cleared' : 'empty'}`).join(', ')
        : '';
    }
    if (lastVal && lastCacheCleared) {
      lastVal.textContent = lastCacheCleared.toLocaleTimeString();
      lastSub.textContent = lastCacheCleared.toLocaleDateString();
    }

    // Update sim page badge
    const simBadge = document.getElementById('sim-cache-status');
    if (simBadge) {
      simBadge.textContent = 'Caches Clear';
      simBadge.className = 'badge badge-success';
    }
  }

  function clearCaches() {
    const resultBox = document.getElementById('cache-result');
    resultBox.textContent = 'Clearing caches...';

    clearCachesCore()
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  function clearCachesFromSim() {
    const btn = document.getElementById('btn-sim-clear-cache');
    const badge = document.getElementById('sim-cache-status');
    btn.disabled = true;
    btn.textContent = 'Clearing...';
    badge.textContent = 'Clearing...';
    badge.className = 'badge badge-warning';

    clearCachesCore()
      .then(data => {
        btn.disabled = false;
        btn.textContent = 'Clear Caches';
        if (data.ok) {
          badge.textContent = 'Caches Clear';
          badge.className = 'badge badge-success';
        } else {
          badge.textContent = 'Error';
          badge.className = 'badge badge-danger';
        }
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Clear Caches';
        badge.textContent = 'Error';
        badge.className = 'badge badge-danger';
      });
  }

  // SQL
  function loadSqlPresets() {
    const select = document.getElementById('sql-preset');
    select.innerHTML = '<option value="">-- Select preset --</option>' +
      SQL_PRESETS.map((p, i) => `<option value="${i}">${p.name}</option>`).join('');
  }

  function runSqlPreset() {
    const idx = document.getElementById('sql-preset').value;
    if (idx === '') return;

    const preset = SQL_PRESETS[parseInt(idx)];
    if (preset) {
      document.getElementById('sql-query').value = preset.query;
      runSql();
    }
  }

  function runSql() {
    const query = document.getElementById('sql-query').value.trim();
    if (!query) {
      alert('Please enter a query');
      return;
    }

    const mode = document.getElementById('sql-mode').value;
    const limit = parseInt(document.getElementById('sql-limit').value) || 100;
    const dryRun = document.getElementById('sql-dry').checked;

    const resultBox = document.getElementById('sql-result');
    resultBox.textContent = 'Executing...';

    fetch(`${ADMIN_BASE}/run_sql`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sql: query,
        mode,
        limit,
        dry_run: dryRun,
      }),
    })
      .then(r => {
        if (r.status === 401) {
          throw new Error('Unauthorized - please login first');
        }
        return r.json();
      })
      .then(data => {
        if (data.error) {
          resultBox.textContent = 'Error: ' + (data.error.message || data.error);
        } else if (data.rows) {
          resultBox.textContent = `${data.rows.length} rows returned:\n\n` + JSON.stringify(data.rows, null, 2);
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // Health
  function checkHealth() {
    const indicator = document.getElementById('health-indicator');
    const text = document.getElementById('health-text');
    const dbInfo = document.getElementById('db-info');

    text.textContent = 'Checking...';
    indicator.className = 'status-indicator';

    fetch('/healthz')
      .then(r => r.json())
      .then(data => {
        if (data.status === 'ok') {
          indicator.classList.add('healthy');
          text.textContent = 'Healthy';
        } else {
          indicator.classList.add('unhealthy');
          text.textContent = data.status || 'Unhealthy';
        }
        dbInfo.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        indicator.classList.add('unhealthy');
        text.textContent = 'Error';
        dbInfo.textContent = 'Error: ' + err.message;
      });
  }

  // ── Migrations ──────────────────────────────────────────
  function runMigrateAmateur() {
    const btn = document.getElementById('btn-migrate-amateur');
    const resultBox = document.getElementById('migrate-amateur-result');
    btn.disabled = true;
    btn.textContent = 'Running...';
    resultBox.style.display = 'block';
    resultBox.textContent = 'Migration in progress...';

    fetch('/admin/migrations/fix-amateur-contracts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        btn.disabled = false;
        btn.textContent = 'Run Migration';
        if (data.ok) {
          resultBox.textContent = JSON.stringify(data, null, 2);
          resultBox.style.color = '#4caf50';
        } else {
          resultBox.textContent = 'Error: ' + (data.message || JSON.stringify(data));
          resultBox.style.color = '#f44336';
        }
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Run Migration';
        resultBox.textContent = 'Request failed: ' + err.message;
        resultBox.style.color = '#f44336';
      });
  }

  function loadRoutes() {
    const routesList = document.getElementById('routes-list');
    routesList.textContent = 'Loading...';

    fetch('/routes')
      .then(r => r.text())
      .then(text => {
        routesList.textContent = text;
      })
      .catch(err => {
        routesList.textContent = 'Could not load routes: ' + err.message;
      });
  }

  // Rating Config
  const LEVEL_NAMES = {
    '1': 'High School', '2': "Int'l Amateur", '3': 'College',
    '4': 'Scraps', '5': 'A', '6': 'High-A',
    '7': 'AA', '8': 'AAA', '9': 'MLB',
  };

  function loadRatingConfigSummary() {
    // Quick check: load config to populate stat cards
    fetch(`${ADMIN_BASE}/rating-config`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Login required');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.levels) throw new Error('No config data');
        const levels = data.levels; // { ptype: { level_id: { attr: {mean,std} } } }
        const ptypeCount = Object.keys(levels).length;
        let levelSet = new Set();
        let attrCount = 0;
        for (const ptypeLevels of Object.values(levels)) {
          for (const [lvl, attrs] of Object.entries(ptypeLevels)) {
            levelSet.add(lvl);
            attrCount += Object.keys(attrs).length;
          }
        }
        document.getElementById('rc-status').textContent = ptypeCount > 0 ? 'Seeded' : 'Empty';
        document.getElementById('rc-status-sub').textContent = ptypeCount > 0 ? `${ptypeCount} player types` : 'Run seed to populate';
        document.getElementById('rc-levels-count').textContent = levelSet.size;
        document.getElementById('rc-attrs-count').textContent = `${attrCount} total rows`;
      })
      .catch(() => {
        document.getElementById('rc-status').textContent = 'Unknown';
        document.getElementById('rc-status-sub').textContent = 'Login to check';
        document.getElementById('rc-levels-count').textContent = '--';
        document.getElementById('rc-attrs-count').textContent = '--';
      });
  }

  function seedRatingConfig() {
    const resultBox = document.getElementById('rc-seed-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Seeding config from player data...';

    const btn = document.getElementById('btn-seed-config');
    btn.disabled = true;
    btn.textContent = 'Seeding...';

    fetch(`${ADMIN_BASE}/rating-config/seed`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (data.ok) {
          const levels = data.levels || {};  // { ptype: { level_id: attr_count } }
          const playerCounts = data.player_counts || {};

          let details = '';
          for (const [ptype, ptypeLevels] of Object.entries(levels).sort()) {
            const ptypePlayers = playerCounts[ptype] || {};
            details += `\n${ptype}:\n`;
            details += Object.entries(ptypeLevels)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([lvl, count]) => {
                const pc = ptypePlayers[Number(lvl)] || 0;
                return `  Level ${lvl} (${LEVEL_NAMES[lvl] || '?'}): ${count} attributes from ${pc} players`;
              })
              .join('\n');
          }

          resultBox.textContent =
            `Success! ${data.rows_written} rows written.\n` + details;

          // Refresh the summary cards
          loadRatingConfigSummary();
        } else {
          resultBox.textContent = 'Error: ' + (data.message || JSON.stringify(data));
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      })
      .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Analyze & Populate';
      });
  }

  // ---------------------------------------------------------------------------
  // Level Scale Config — one mean/std per (ptype, level)
  // ---------------------------------------------------------------------------

  function loadLevelConfig() {
    const tbody = document.getElementById('rc-config-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';

    fetch(`${ADMIN_BASE}/rating-config`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.levels) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No config data. Run "Analyze & Populate" first.</td></tr>';
          return;
        }
        renderLevelConfigTable(data.levels);
        document.getElementById('btn-save-config').style.display = 'inline-block';
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function renderLevelConfigTable(levels) {
    // levels = { ptype: { level_id: { attr: {mean, std, ...} } } }
    // Collapse to one row per (ptype, level) — take mean/std from first attribute
    const tbody = document.getElementById('rc-config-tbody');
    const rows = [];

    for (const ptype of Object.keys(levels).sort()) {
      const ptypeLevels = levels[ptype];
      for (const levelId of Object.keys(ptypeLevels).sort((a, b) => Number(a) - Number(b))) {
        const attrs = ptypeLevels[levelId];
        const attrKeys = Object.keys(attrs);
        if (attrKeys.length === 0) continue;

        // Check if all attrs share the same mean/std (post bulk-set) or vary (post seed)
        const vals = attrKeys.map(k => attrs[k]);
        const firstMean = vals[0].mean;
        const firstStd = vals[0].std;
        const uniform = vals.every(v =>
          Math.abs(v.mean - firstMean) < 0.001 && Math.abs(v.std - firstStd) < 0.001
        );

        rows.push({
          ptype,
          levelId,
          levelName: LEVEL_NAMES[levelId] || `Level ${levelId}`,
          mean: uniform ? firstMean : null,
          std: uniform ? firstStd : null,
          uniform,
        });
      }
    }

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No levels found</td></tr>';
      return;
    }

    const inputStyle = 'width:80px;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text-primary);font-size:0.85rem;text-align:right';

    tbody.innerHTML = rows.map(r => {
      const ptypeBadge = r.ptype === 'Pitcher' ? 'badge-info' : 'badge-success';
      const meanVal = r.mean != null ? r.mean.toFixed(2) : '';
      const stdVal = r.std != null ? r.std.toFixed(2) : '';
      const low = r.std > 0 ? (r.mean - 3 * r.std).toFixed(1) : '--';
      const mid = r.mean != null ? r.mean.toFixed(1) : '--';
      const high = r.std > 0 ? (r.mean + 3 * r.std).toFixed(1) : '--';
      const placeholder = r.uniform ? '' : 'placeholder="varies"';
      return `
        <tr>
          <td><span class="badge ${ptypeBadge}">${r.ptype}</span></td>
          <td><span class="badge badge-${getLevelBadge(r.levelId)}">${r.levelName}</span></td>
          <td>
            <input type="number" step="0.1"
              class="rc-mean-input rc-scale-input"
              data-ptype="${r.ptype}" data-level="${r.levelId}"
              data-orig="${r.mean != null ? r.mean : ''}"
              value="${meanVal}" ${placeholder}
              style="${inputStyle}"
            />
          </td>
          <td>
            <input type="number" step="0.1" min="0"
              class="rc-std-input rc-scale-input"
              data-ptype="${r.ptype}" data-level="${r.levelId}"
              data-orig="${r.std != null ? r.std : ''}"
              value="${stdVal}" ${placeholder}
              style="${inputStyle}"
            />
          </td>
          <td class="text-muted rc-col-20">${low}</td>
          <td><strong class="rc-col-50">${mid}</strong></td>
          <td class="text-muted rc-col-80">${high}</td>
        </tr>
      `;
    }).join('');

    // Live recompute 20/50/80
    tbody.querySelectorAll('.rc-scale-input').forEach(input => {
      input.addEventListener('input', function () {
        const tr = this.closest('tr');
        const m = parseFloat(tr.querySelector('.rc-mean-input').value) || 0;
        const s = parseFloat(tr.querySelector('.rc-std-input').value) || 0;
        tr.querySelector('.rc-col-20').textContent = s > 0 ? (m - 3 * s).toFixed(1) : '--';
        tr.querySelector('.rc-col-50').textContent = m.toFixed(1);
        tr.querySelector('.rc-col-80').textContent = s > 0 ? (m + 3 * s).toFixed(1) : '--';
      });
    });
  }

  function saveLevelConfig() {
    const tbody = document.getElementById('rc-config-tbody');
    const meanInputs = tbody.querySelectorAll('.rc-mean-input');
    const stdInputs = tbody.querySelectorAll('.rc-std-input');
    const resultBox = document.getElementById('rc-save-result');

    // Collect rows that have values
    const levels = [];
    meanInputs.forEach((input, i) => {
      const stdInput = stdInputs[i];
      const newMean = parseFloat(input.value);
      const newStd = parseFloat(stdInput.value);
      if (isNaN(newMean) || isNaN(newStd)) return;

      const origMean = parseFloat(input.dataset.orig);
      const origStd = parseFloat(stdInput.dataset.orig);
      if (!isNaN(origMean) && !isNaN(origStd) &&
          Math.abs(newMean - origMean) < 0.001 && Math.abs(newStd - origStd) < 0.001) return;

      levels.push({
        level_id: parseInt(input.dataset.level),
        ptype: input.dataset.ptype,
        mean_value: newMean,
        std_dev: newStd,
      });
    });

    if (levels.length === 0) {
      resultBox.style.display = 'block';
      resultBox.textContent = 'No changes detected.';
      return;
    }

    const btn = document.getElementById('btn-save-config');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    resultBox.style.display = 'block';
    resultBox.textContent = `Saving ${levels.length} level(s)...`;

    fetch(`${ADMIN_BASE}/rating-config/levels`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ levels }),
    })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (data.ok) {
          resultBox.textContent = `Saved! ${data.updated} attribute row(s) updated across ${levels.length} level(s).`;
          // Update orig values
          meanInputs.forEach(input => { input.dataset.orig = input.value; });
          stdInputs.forEach(input => { input.dataset.orig = input.value; });
        } else {
          resultBox.textContent = 'Error: ' + (data.message || JSON.stringify(data));
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      })
      .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Save Changes';
      });
  }

  // ---------------------------------------------------------------------------
  // Attribute Analysis — read-only reference table
  // ---------------------------------------------------------------------------

  let analysisData = null;

  function loadAnalysis() {
    const levelFilter = document.getElementById('rc-level-filter').value;
    const ptypeFilter = document.getElementById('rc-ptype-filter').value;
    const tbody = document.getElementById('rc-analysis-tbody');
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Loading...</td></tr>';

    let url = `${ADMIN_BASE}/rating-config`;
    const params = [];
    if (levelFilter) params.push(`level=${levelFilter}`);
    if (ptypeFilter) params.push(`ptype=${encodeURIComponent(ptypeFilter)}`);
    if (params.length) url += '?' + params.join('&');

    fetch(url, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.levels) {
          tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No data. Run "Analyze & Populate" first.</td></tr>';
          return;
        }
        analysisData = data.levels;
        renderAnalysisTable();
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function renderAnalysisTable() {
    if (!analysisData) return;

    const searchTerm = (document.getElementById('rc-attr-filter').value || '').toLowerCase().trim();
    const tbody = document.getElementById('rc-analysis-tbody');

    const rows = [];
    for (const ptype of Object.keys(analysisData).sort()) {
      const ptypeLevels = analysisData[ptype];
      for (const levelId of Object.keys(ptypeLevels).sort((a, b) => Number(a) - Number(b))) {
        const attrs = ptypeLevels[levelId];
        for (const attrKey of Object.keys(attrs).sort()) {
          if (searchTerm && !attrKey.toLowerCase().includes(searchTerm)) continue;
          const d = attrs[attrKey];
          rows.push({ ptype, levelId, attrKey, ...d });
        }
      }
    }

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No matching attributes</td></tr>';
      return;
    }

    const fmtQ = (v) => v != null ? v.toFixed(1) : '--';
    tbody.innerHTML = rows.map(r => {
      const ptypeBadge = r.ptype === 'Pitcher' ? 'badge-info' : 'badge-success';
      const attrClass = getAttrCategoryClass(r.attrKey);
      return `
        <tr>
          <td><span class="badge ${ptypeBadge}">${r.ptype}</span></td>
          <td><span class="badge badge-${getLevelBadge(r.levelId)}">${LEVEL_NAMES[r.levelId] || r.levelId}</span></td>
          <td><code class="${attrClass}">${r.attrKey}</code></td>
          <td class="text-muted">${fmtQ(r.p25)}</td>
          <td class="text-muted">${fmtQ(r.median)}</td>
          <td class="text-muted">${fmtQ(r.p75)}</td>
          <td>${r.mean.toFixed(2)}</td>
          <td>${r.std.toFixed(2)}</td>
        </tr>
      `;
    }).join('');
  }

  function filterAnalysisTable() {
    if (analysisData) renderAnalysisTable();
  }

  function getLevelBadge(levelId) {
    const n = Number(levelId);
    if (n <= 3) return 'info';
    if (n <= 6) return 'warning';
    if (n <= 8) return 'pending';
    return 'success';
  }

  function getAttrCategoryClass(attrKey) {
    if (attrKey.endsWith('_rating')) return 'text-warning';
    if (attrKey.startsWith('pitch_')) return 'text-success';
    if (attrKey.includes('_ovr')) return 'text-warning';
    return '';
  }

  // NOTE: Overall Weights editing was moved to the Weight Calibration page
  // (see viewCalProfile / saveProfileWeights below) so all 13 rating types
  // are managed in one place. The standalone loadOverallWeights /
  // saveOverallWeights functions and the /rating-config/overall-weights
  // endpoints were deleted.

  // ── Growth Curves ───────────────────────────────────────────────────

  let _gcData = null; // cached full dataset

  function loadGrowthCurves() {
    const tbody = document.getElementById('gc-tbody');
    const gradeSelect = document.getElementById('gc-grade-filter');
    const resultBox = document.getElementById('gc-result');
    resultBox.style.display = 'none';
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Loading…</td></tr>';

    fetch(`${ADMIN_BASE}/growth-curves`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (!data.ok) throw new Error(data.message || 'Failed to load');
        _gcData = data.curves;

        // Populate grade filter dropdown
        const current = gradeSelect.value;
        gradeSelect.innerHTML = '<option value="">All</option>';
        data.grades.forEach(g => {
          const opt = document.createElement('option');
          opt.value = g;
          opt.textContent = g;
          gradeSelect.appendChild(opt);
        });
        gradeSelect.value = current;

        renderGrowthCurves();
        document.getElementById('btn-save-gc').style.display = '';
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">${err.message}</td></tr>`;
      });
  }

  function renderGrowthCurves() {
    if (!_gcData) return;
    const tbody = document.getElementById('gc-tbody');
    const filter = document.getElementById('gc-grade-filter').value;
    const grades = filter ? [filter] : Object.keys(_gcData).sort();

    let html = '';
    for (const grade of grades) {
      const rows = _gcData[grade] || [];
      for (const r of rows) {
        html += `<tr>
          <td>${grade}</td>
          <td>${r.age}</td>
          <td><input type="number" step="0.1" class="gc-input" data-grade="${grade}" data-age="${r.age}" data-field="prog_min" value="${r.prog_min}" style="width:70px" /></td>
          <td><input type="number" step="0.1" class="gc-input" data-grade="${grade}" data-age="${r.age}" data-field="prog_mode" value="${r.prog_mode}" style="width:70px" /></td>
          <td><input type="number" step="0.1" class="gc-input" data-grade="${grade}" data-age="${r.age}" data-field="prog_max" value="${r.prog_max}" style="width:70px" /></td>
        </tr>`;
      }
    }
    tbody.innerHTML = html || '<tr><td colspan="5" class="text-center text-muted">No data</td></tr>';
  }

  function filterGrowthCurves() {
    renderGrowthCurves();
  }

  function saveGrowthCurves() {
    const inputs = document.querySelectorAll('.gc-input');
    const resultBox = document.getElementById('gc-result');
    const btn = document.getElementById('btn-save-gc');

    // Collect changes into a map keyed by grade+age
    const updateMap = {};
    inputs.forEach(inp => {
      const key = `${inp.dataset.grade}|${inp.dataset.age}`;
      if (!updateMap[key]) {
        updateMap[key] = { grade: inp.dataset.grade, age: parseInt(inp.dataset.age) };
      }
      updateMap[key][inp.dataset.field] = parseFloat(inp.value) || 0;
    });

    const updates = Object.values(updateMap);
    if (!updates.length) return;

    btn.disabled = true;
    btn.textContent = 'Saving…';
    resultBox.style.display = 'block';
    resultBox.textContent = `Saving ${updates.length} row(s)…`;
    resultBox.style.color = '';

    fetch(`${ADMIN_BASE}/growth-curves`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates }),
    })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (data.ok) {
          resultBox.textContent = `Saved! ${data.updated} row(s) updated. Re-run the sandbox to see the effect.`;
          resultBox.style.color = '#4caf50';
          loadGrowthCurves(); // refresh
        } else {
          resultBox.textContent = 'Error: ' + (data.message || JSON.stringify(data));
          resultBox.style.color = '#f44336';
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
        resultBox.style.color = '#f44336';
      })
      .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Save Changes';
      });
  }

  // -----------------------------------------------------------------------
  // Transactions — Shared Helpers
  // -----------------------------------------------------------------------

  function fetchTxContext() {
    // Fetch current timestamp to populate league_year_id and game_week_id
    return fetch(`${API_BASE}/games/timestamp`)
      .then(r => r.json())
      .then(data => {
        txLeagueYearId = data.SeasonID || data.league_year_id || 1;
        txGameWeekId = data.WeekID || data.Week || data.game_week_id || 1;
        return data;
      })
      .catch(() => {
        // fallback
        txLeagueYearId = txLeagueYearId || 1;
        txGameWeekId = txGameWeekId || 1;
      });
  }

  function populateTxOrgDropdown(selectId) {
    const sel = document.getElementById(selectId);
    if (txOrgList.length > 0) {
      renderOrgOptions(sel, txOrgList);
      return Promise.resolve();
    }
    sel.innerHTML = '<option value="">Loading...</option>';
    // Use org_report which returns objects with numeric id + org_abbrev
    return fetch(`${API_BASE}/org_report/`)
      .then(r => r.json())
      .then(data => {
        txOrgList = Array.isArray(data) ? data : [];
        renderOrgOptions(sel, txOrgList);
      })
      .catch(() => {
        sel.innerHTML = '<option value="">Error loading orgs</option>';
      });
  }

  function renderOrgOptions(sel, orgs) {
    const sorted = [...orgs].sort((a, b) =>
      (a.org_abbrev || '').localeCompare(b.org_abbrev || '')
    );
    // MLB orgs first, then the rest
    const mlb = sorted.filter(o => o.league === 'mlb');
    const other = sorted.filter(o => o.league !== 'mlb');
    sel.innerHTML = '<option value="">Select org...</option>';
    if (mlb.length) {
      sel.innerHTML += '<optgroup label="MLB Organizations">' +
        mlb.map(o => `<option value="${o.id}">${o.org_abbrev}</option>`).join('') +
        '</optgroup>';
    }
    if (other.length) {
      sel.innerHTML += '<optgroup label="Other Organizations">' +
        other.map(o => `<option value="${o.id}">${o.org_abbrev}</option>`).join('') +
        '</optgroup>';
    }
  }

  // -----------------------------------------------------------------------
  // Transactions — Roster Moves
  // -----------------------------------------------------------------------

  function loadRosterMoves() {
    fetchTxContext();
    populateTxOrgDropdown('tx-org-select');
    // Reset state
    txSelectedPlayer = null;
    document.getElementById('tx-action-card').style.display = 'none';
    document.getElementById('tx-roster-card').style.display = 'none';
  }

  function loadOrgRoster(orgId) {
    const tbody = document.getElementById('tx-roster-tbody');
    const card = document.getElementById('tx-roster-card');
    const statusDiv = document.getElementById('tx-roster-status');
    card.style.display = 'block';
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';
    document.getElementById('tx-action-card').style.display = 'none';
    txSelectedPlayer = null;

    // Load roster status
    fetch(`${API_BASE}/transactions/roster-status/${orgId}`)
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) {
          statusDiv.innerHTML = data
            .filter(l => l.max_roster > 0)
            .map(l => {
              let flag = '';
              if (l.over_limit) flag = ' <span style="color:var(--danger)">OVER</span>';
              else if (l.under_limit) flag = ' <span style="color:var(--warning)">UNDER</span>';
              return `<span><strong>${l.level_name}:</strong> ${l.count}/${l.max_roster}${flag}</span>`;
            })
            .join(' &nbsp;|&nbsp; ');
        }
      })
      .catch(() => { statusDiv.textContent = 'Could not load roster status'; });

    // Load roster players
    const levelFilter = document.getElementById('tx-roster-level-filter').value;
    fetch(`${API_BASE}/transactions/roster/${orgId}`)
      .then(r => r.json())
      .then(players => {
        let filtered = players;
        if (levelFilter) {
          filtered = players.filter(p => p.current_level === parseInt(levelFilter));
        }
        if (filtered.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No players found</td></tr>';
          return;
        }
        tbody.innerHTML = filtered.map(p => {
          const levelNames = { 9: 'MLB', 8: 'AAA', 7: 'AA', 6: 'High-A', 5: 'A', 4: 'Scraps' };
          return `<tr>
            <td>${p.player_name}</td>
            <td>${p.position}</td>
            <td>${levelNames[p.current_level] || p.current_level}</td>
            <td><code>${p.contract_id}</code></td>
            <td>$${Number(p.salary).toLocaleString()}</td>
            <td>${p.onIR ? '<span class="badge badge-danger">IR</span>' : '--'}</td>
            <td><button class="btn btn-sm btn-primary" onclick="App.selectPlayer(${p.contract_id}, '${p.player_name.replace(/'/g, "\\'")}', ${p.current_level}, ${p.onIR ? 1 : 0}, ${p.player_id})">Select</button></td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });

    // Update signing budget display
    fetch(`${API_BASE}/transactions/signing-budget/${orgId}?league_year_id=${txLeagueYearId || 1}`)
      .then(r => r.json())
      .then(data => {
        document.getElementById('tx-signing-budget').textContent =
          `Signing budget: $${Number(data.available_budget || 0).toLocaleString()}`;
      })
      .catch(() => {});
  }

  function selectPlayer(contractId, playerName, currentLevel, onIR, playerId) {
    txSelectedPlayer = { contract_id: contractId, player_name: playerName, current_level: currentLevel, onIR: onIR, player_id: playerId };
    const card = document.getElementById('tx-action-card');
    card.style.display = 'block';
    document.getElementById('tx-action-player-name').textContent = playerName;
    document.getElementById('tx-action-type').value = '';
    document.getElementById('tx-target-level-group').style.display = 'none';
    document.getElementById('tx-buyout-group').style.display = 'none';
    document.getElementById('tx-extend-group').style.display = 'none';
    document.getElementById('tx-action-result').style.display = 'none';
  }

  function onActionTypeChange() {
    const action = document.getElementById('tx-action-type').value;
    document.getElementById('tx-target-level-group').style.display =
      (action === 'promote' || action === 'demote') ? 'block' : 'none';
    document.getElementById('tx-buyout-group').style.display =
      action === 'buyout' ? 'block' : 'none';
    document.getElementById('tx-extend-group').style.display =
      action === 'extend' ? 'block' : 'none';
    if (action === 'extend') {
      renderExtSalaryInputs();
      _fetchDemand('extension', 'tx-ext-demand');
    }
    if (action === 'buyout') {
      _fetchDemand('buyout', 'tx-buyout-demand');
    }
  }

  function _fetchDemand(demandType, targetElId) {
    if (!txSelectedPlayer || !txSelectedPlayer.player_id) return;
    const el = document.getElementById(targetElId);
    el.style.display = 'block';
    el.textContent = 'Loading player demand...';
    fetch(`${API_BASE}/fa-auction/compute-demands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        player_id: txSelectedPlayer.player_id,
        league_year_id: txLeagueYearId || 1,
        demand_type: demandType,
        contract_id: txSelectedPlayer.contract_id,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          el.textContent = 'Demand unavailable: ' + data.error;
          return;
        }
        if (demandType === 'buyout') {
          el.innerHTML = `Player demands: <strong>$${Number(data.buyout_price).toLocaleString()}</strong> minimum buyout (WAR: ${data.war})`;
        } else {
          el.innerHTML = `Player demands: <strong>$${Number(data.min_aav).toLocaleString()}</strong> min AAV, ` +
            `${data.min_years}-${data.max_years} years (WAR: ${data.war})`;
        }
      })
      .catch(() => { el.textContent = 'Could not load demand'; });
  }

  function renderExtSalaryInputs() {
    const years = parseInt(document.getElementById('tx-ext-years').value) || 1;
    const container = document.getElementById('tx-ext-salaries');
    container.innerHTML = '';
    for (let i = 1; i <= years; i++) {
      container.innerHTML += `<div class="form-group"><label>Year ${i} Salary ($)</label><input type="number" id="tx-ext-sal-${i}" min="0" step="1000" value="0" /></div>`;
    }
  }

  function renderSignSalaryInputs() {
    const years = parseInt(document.getElementById('tx-sign-years').value) || 1;
    const container = document.getElementById('tx-sign-salaries');
    container.innerHTML = '';
    for (let i = 1; i <= years; i++) {
      container.innerHTML += `<div class="form-group"><label>Year ${i} Salary ($)</label><input type="number" id="tx-sign-sal-${i}" min="0" step="1000" value="0" /></div>`;
    }
  }

  function executeRosterAction() {
    if (!txSelectedPlayer) { alert('No player selected'); return; }
    const action = document.getElementById('tx-action-type').value;
    if (!action) { alert('Select an action'); return; }
    const resultBox = document.getElementById('tx-action-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Executing...';

    const orgId = parseInt(document.getElementById('tx-org-select').value);
    const base = { league_year_id: txLeagueYearId, executed_by: 'admin' };
    let url, body;

    switch (action) {
      case 'promote':
        url = '/transactions/promote';
        body = { ...base, contract_id: txSelectedPlayer.contract_id, target_level_id: parseInt(document.getElementById('tx-target-level').value) };
        break;
      case 'demote':
        url = '/transactions/demote';
        body = { ...base, contract_id: txSelectedPlayer.contract_id, target_level_id: parseInt(document.getElementById('tx-target-level').value) };
        break;
      case 'ir_place':
        url = '/transactions/ir/place';
        body = { ...base, contract_id: txSelectedPlayer.contract_id };
        break;
      case 'ir_activate':
        url = '/transactions/ir/activate';
        body = { ...base, contract_id: txSelectedPlayer.contract_id };
        break;
      case 'release':
        if (!confirm(`Release ${txSelectedPlayer.player_name}? This cannot be easily undone.`)) return;
        url = '/transactions/release';
        body = { ...base, contract_id: txSelectedPlayer.contract_id, org_id: orgId };
        break;
      case 'buyout':
        if (!confirm(`Buyout ${txSelectedPlayer.player_name}?`)) return;
        url = '/transactions/buyout';
        body = { ...base, contract_id: txSelectedPlayer.contract_id, org_id: orgId, buyout_amount: parseFloat(document.getElementById('tx-buyout-amount').value) || 0, game_week_id: txGameWeekId };
        break;
      case 'extend': {
        const years = parseInt(document.getElementById('tx-ext-years').value) || 1;
        const salaries = [];
        for (let i = 1; i <= years; i++) {
          salaries.push(parseFloat(document.getElementById(`tx-ext-sal-${i}`).value) || 0);
        }
        url = '/transactions/extend';
        body = { ...base, contract_id: txSelectedPlayer.contract_id, org_id: orgId, years: years, salaries: salaries, bonus: parseFloat(document.getElementById('tx-ext-bonus').value) || 0, game_week_id: txGameWeekId };
        break;
      }
      default:
        resultBox.textContent = 'Unknown action: ' + action;
        return;
    }

    fetch(`${API_BASE}${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          // Reload roster
          loadOrgRoster(orgId);
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // -----------------------------------------------------------------------
  // Transactions — Free Agents
  // -----------------------------------------------------------------------

  function loadFreeAgents() {
    const tbody = document.getElementById('tx-fa-tbody');
    const wrap = document.getElementById('tx-fa-table-wrap');
    wrap.style.display = 'block';
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Loading...</td></tr>';
    document.getElementById('tx-sign-form').style.display = 'none';

    fetch(`${API_BASE}/transactions/free-agents`)
      .then(r => r.json())
      .then(players => {
        if (!players.length) {
          tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No free agents found</td></tr>';
          return;
        }
        tbody.innerHTML = players.map(p => `<tr>
          <td>${p.player_name}</td>
          <td>${p.position}</td>
          <td>${p.age || '--'}</td>
          <td><button class="btn btn-sm btn-primary" onclick="App.selectFA(${p.player_id}, '${p.player_name.replace(/'/g, "\\'")}')">Sign</button></td>
        </tr>`).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function selectFA(playerId, playerName) {
    txSelectedFA = { player_id: playerId, player_name: playerName };
    const form = document.getElementById('tx-sign-form');
    form.style.display = 'block';
    document.getElementById('tx-sign-player-name').textContent = playerName;
    document.getElementById('tx-sign-years').value = 1;
    document.getElementById('tx-sign-bonus').value = 0;
    document.getElementById('tx-sign-result').style.display = 'none';
    renderSignSalaryInputs();
  }

  function signFreeAgent() {
    if (!txSelectedFA) { alert('No free agent selected'); return; }
    const orgId = parseInt(document.getElementById('tx-org-select').value);
    if (!orgId) { alert('Select an organization first (in the org selector above)'); return; }

    const years = parseInt(document.getElementById('tx-sign-years').value) || 1;
    const salaries = [];
    for (let i = 1; i <= years; i++) {
      salaries.push(parseFloat(document.getElementById(`tx-sign-sal-${i}`).value) || 0);
    }
    const resultBox = document.getElementById('tx-sign-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Signing...';

    fetch(`${API_BASE}/transactions/sign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        player_id: txSelectedFA.player_id,
        org_id: orgId,
        years: years,
        salaries: salaries,
        bonus: parseFloat(document.getElementById('tx-sign-bonus').value) || 0,
        level_id: parseInt(document.getElementById('tx-sign-level').value),
        league_year_id: txLeagueYearId,
        game_week_id: txGameWeekId,
        executed_by: 'admin',
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          loadOrgRoster(orgId);
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // -----------------------------------------------------------------------
  // Transactions — Trade Builder
  // -----------------------------------------------------------------------

  function loadTradeBuilder() {
    fetchTxContext();
    populateTxOrgDropdown('tx-trade-org-a');
    populateTxOrgDropdown('tx-trade-org-b');
    loadTradeProposals();
  }

  function loadTradeOrgRoster(side, orgId) {
    const tbody = document.getElementById(`tx-trade-roster-${side}`);
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Loading...</td></tr>';

    fetch(`${API_BASE}/transactions/roster/${orgId}`)
      .then(r => r.json())
      .then(players => {
        if (!players.length) {
          tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No players</td></tr>';
          return;
        }
        tbody.innerHTML = players.map(p => `<tr>
          <td><input type="checkbox" class="trade-check-${side}" value="${p.player_id}" data-contract="${p.contract_id}" /></td>
          <td>${p.player_name}</td>
          <td>${p.position}</td>
          <td>${{ 9: 'MLB', 8: 'AAA', 7: 'AA', 6: 'High-A', 5: 'A', 4: 'Scraps' }[p.current_level] || p.current_level}</td>
        </tr>`).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function executeTrade() {
    const orgA = parseInt(document.getElementById('tx-trade-org-a').value);
    const orgB = parseInt(document.getElementById('tx-trade-org-b').value);
    if (!orgA || !orgB) { alert('Select both organizations'); return; }
    if (orgA === orgB) { alert('Cannot trade with same org'); return; }

    const playersToB = [];
    document.querySelectorAll('.trade-check-a:checked').forEach(cb => {
      playersToB.push(parseInt(cb.value));
    });
    const playersToA = [];
    document.querySelectorAll('.trade-check-b:checked').forEach(cb => {
      playersToA.push(parseInt(cb.value));
    });

    if (playersToA.length === 0 && playersToB.length === 0) {
      alert('Select at least one player to trade');
      return;
    }

    if (!confirm(`Execute trade: ${playersToB.length} player(s) to Org B, ${playersToA.length} player(s) to Org A?`)) return;

    const resultBox = document.getElementById('tx-trade-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Executing trade...';

    fetch(`${API_BASE}/transactions/trade/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        org_a_id: orgA,
        org_b_id: orgB,
        players_to_b: playersToB,
        players_to_a: playersToA,
        cash_a_to_b: parseFloat(document.getElementById('tx-trade-cash').value) || 0,
        league_year_id: txLeagueYearId,
        game_week_id: txGameWeekId,
        executed_by: 'admin',
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          // Reload both rosters
          loadTradeOrgRoster('a', orgA);
          loadTradeOrgRoster('b', orgB);
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // -----------------------------------------------------------------------
  // Transactions — Trade Proposals
  // -----------------------------------------------------------------------

  function loadTradeProposals() {
    const tbody = document.getElementById('tx-proposals-tbody');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Loading...</td></tr>';

    const statusFilter = document.getElementById('tx-proposal-status-filter').value;
    let url = `${API_BASE}/transactions/trade/proposals`;
    if (statusFilter) url += `?status=${statusFilter}`;

    fetch(url)
      .then(r => r.json())
      .then(proposals => {
        if (!proposals.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No proposals found</td></tr>';
          return;
        }
        tbody.innerHTML = proposals.map(p => {
          const statusBadge = {
            proposed: 'badge-info',
            counterparty_accepted: 'badge-warning',
            admin_approved: 'badge-success',
            executed: 'badge-success',
            counterparty_rejected: 'badge-danger',
            admin_rejected: 'badge-danger',
            cancelled: 'badge-secondary',
          }[p.status] || '';

          let actions = '';
          if (p.status === 'counterparty_accepted') {
            actions = `<button class="btn btn-sm btn-primary" onclick="App.adminApproveProposal(${p.id})">Approve</button> `;
            actions += `<button class="btn btn-sm btn-danger" onclick="App.adminRejectProposal(${p.id})">Reject</button>`;
          } else if (p.status === 'proposed') {
            actions = `<button class="btn btn-sm btn-secondary" onclick="App.adminRejectProposal(${p.id})">Reject</button>`;
          }

          const created = p.created_at ? new Date(p.created_at).toLocaleDateString() : '--';
          return `<tr>
            <td>${p.id}</td>
            <td>${p.proposing_org_id}</td>
            <td>${p.receiving_org_id}</td>
            <td><span class="badge ${statusBadge}">${p.status}</span></td>
            <td>${created}</td>
            <td>${actions}</td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function adminApproveProposal(proposalId) {
    if (!confirm(`Approve and execute trade proposal #${proposalId}?`)) return;
    const resultBox = document.getElementById('tx-proposal-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Approving...';

    fetch(`${API_BASE}/transactions/trade/proposals/${proposalId}/admin-approve`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        league_year_id: txLeagueYearId,
        game_week_id: txGameWeekId,
        executed_by: 'admin',
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          loadTradeProposals();
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  function adminRejectProposal(proposalId) {
    if (!confirm(`Reject trade proposal #${proposalId}?`)) return;
    const resultBox = document.getElementById('tx-proposal-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Rejecting...';

    fetch(`${API_BASE}/transactions/trade/proposals/${proposalId}/admin-reject`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          resultBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          loadTradeProposals();
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // -----------------------------------------------------------------------
  // Transactions — Transaction Log
  // -----------------------------------------------------------------------

  // ── Transaction Log helpers ──────────────────────────────────────

  const TX_TYPE_BADGES = {
    promote: 'badge-info', demote: 'badge-info',
    ir_place: 'badge-warning', ir_activate: 'badge-warning',
    release: 'badge-danger', buyout: 'badge-danger',
    signing: 'badge-success', extension: 'badge-success',
    trade: 'badge-primary',
  };

  function _txSummary(e) {
    const d = e.details || {};
    const player = e.player_name || `#${e.player_id}`;
    const org = e.primary_org_abbrev || `Org #${e.primary_org_id}`;
    const org2 = e.secondary_org_abbrev || (e.secondary_org_id ? `Org #${e.secondary_org_id}` : null);
    switch (e.transaction_type) {
      case 'promote':
        return `${player} promoted L${d.from_level} &rarr; L${d.to_level} (${org})`;
      case 'demote':
        return `${player} demoted L${d.from_level} &rarr; L${d.to_level} (${org})`;
      case 'ir_place':
        return `${player} placed on IR (${org})`;
      case 'ir_activate':
        return `${player} activated from IR (${org})`;
      case 'release':
        return `${player} released by ${org} (${d.years_remaining || '?'}yr remaining)`;
      case 'buyout': {
        const amt = d.buyout_amount != null ? `$${Number(d.buyout_amount).toLocaleString()}` : '?';
        return `${player} bought out by ${org} for ${amt}`;
      }
      case 'signing': {
        const yrs = d.years || '?';
        const sal = d.salaries ? `$${Number(d.salaries[0]).toLocaleString()}` : '?';
        return `${player} signed by ${org} (${yrs}yr, ${sal}/yr)`;
      }
      case 'extension': {
        const yrs = d.years || '?';
        return `${player} extended by ${org} (${yrs}yr)`;
      }
      case 'trade': {
        const toB = (d.players_to_b || []).length;
        const toA = (d.players_to_a || []).length;
        const cash = d.cash_a_to_b ? `, $${Number(d.cash_a_to_b).toLocaleString()} cash` : '';
        return `Trade: ${org} &harr; ${org2 || '?'} (${toB} &rarr; / ${toA} &larr;${cash})`;
      }
      default: {
        const notes = e.notes || '';
        return notes.length > 60 ? notes.substring(0, 60) + '...' : notes || '--';
      }
    }
  }

  function _txDetailHtml(e) {
    const d = e.details || {};
    const player = e.player_name || (e.player_id ? `Player #${e.player_id}` : 'N/A');
    const org = e.primary_org_abbrev ? `${e.primary_org_abbrev} (#${e.primary_org_id})` : `Org #${e.primary_org_id || 'N/A'}`;
    const ts = e.executed_at ? new Date(e.executed_at).toLocaleString() : (e.created_at ? new Date(e.created_at).toLocaleString() : '--');
    const notes = e.notes || '';
    const isRollback = notes.includes('ROLLBACK');

    let html = `<div class="kv-table">
      <div class="kv-row"><div class="kv-key">Transaction ID</div><div class="kv-val">${e.id}</div></div>
      <div class="kv-row"><div class="kv-key">Type</div><div class="kv-val"><span class="badge ${TX_TYPE_BADGES[e.transaction_type] || ''}">${e.transaction_type}</span>${isRollback ? ' <span class="badge badge-secondary">ROLLED BACK</span>' : ''}</div></div>
      <div class="kv-row"><div class="kv-key">Time</div><div class="kv-val">${ts}</div></div>
      <div class="kv-row"><div class="kv-key">Player</div><div class="kv-val">${player}</div></div>
      <div class="kv-row"><div class="kv-key">Primary Org</div><div class="kv-val">${org}</div></div>`;

    if (e.secondary_org_id) {
      const org2 = e.secondary_org_abbrev ? `${e.secondary_org_abbrev} (#${e.secondary_org_id})` : `Org #${e.secondary_org_id}`;
      html += `<div class="kv-row"><div class="kv-key">Secondary Org</div><div class="kv-val">${org2}</div></div>`;
    }
    if (notes) {
      html += `<div class="kv-row"><div class="kv-key">Notes</div><div class="kv-val">${notes}</div></div>`;
    }

    // Type-specific details
    switch (e.transaction_type) {
      case 'promote':
      case 'demote':
        html += `<div class="kv-row"><div class="kv-key">Level Change</div><div class="kv-val">Level ${d.from_level} &rarr; Level ${d.to_level}</div></div>`;
        break;
      case 'release':
        html += `<div class="kv-row"><div class="kv-key">Years Remaining</div><div class="kv-val">${d.years_remaining || '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Level at Release</div><div class="kv-val">${d.current_level || '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Affected Detail IDs</div><div class="kv-val">${(d.affected_detail_ids || []).join(', ') || '--'}</div></div>`;
        break;
      case 'buyout':
        html += `<div class="kv-row"><div class="kv-key">Buyout Amount</div><div class="kv-val">$${d.buyout_amount != null ? Number(d.buyout_amount).toLocaleString() : '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Original Contract</div><div class="kv-val">#${d.original_contract_id || '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Buyout Contract</div><div class="kv-val">#${d.buyout_contract_id || '--'}</div></div>`;
        break;
      case 'signing':
        html += `<div class="kv-row"><div class="kv-key">Years</div><div class="kv-val">${d.years || '--'}</div></div>`;
        if (d.salaries) {
          html += `<div class="kv-row"><div class="kv-key">Salaries</div><div class="kv-val">${d.salaries.map(s => '$' + Number(s).toLocaleString()).join(' / ')}</div></div>`;
        }
        if (d.bonus) {
          html += `<div class="kv-row"><div class="kv-key">Bonus</div><div class="kv-val">$${Number(d.bonus).toLocaleString()}</div></div>`;
        }
        html += `<div class="kv-row"><div class="kv-key">Level</div><div class="kv-val">${d.level_id || '--'}</div></div>`;
        break;
      case 'extension':
        html += `<div class="kv-row"><div class="kv-key">Years</div><div class="kv-val">${d.years || '--'}</div></div>`;
        if (d.salaries) {
          html += `<div class="kv-row"><div class="kv-key">Salaries</div><div class="kv-val">${d.salaries.map(s => '$' + Number(s).toLocaleString()).join(' / ')}</div></div>`;
        }
        if (d.bonus) {
          html += `<div class="kv-row"><div class="kv-key">Bonus</div><div class="kv-val">$${Number(d.bonus).toLocaleString()}</div></div>`;
        }
        html += `<div class="kv-row"><div class="kv-key">Original Contract</div><div class="kv-val">#${d.original_contract_id || '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Extension Contract</div><div class="kv-val">#${d.extension_contract_id || '--'}</div></div>`;
        html += `<div class="kv-row"><div class="kv-key">Starts League Year</div><div class="kv-val">${d.starts_league_year || '--'}</div></div>`;
        break;
      case 'trade': {
        if (d.players_to_b && d.players_to_b.length) {
          html += `<div class="kv-row"><div class="kv-key">Players to ${e.secondary_org_abbrev || 'Org B'}</div><div class="kv-val">${d.players_to_b.map(p => `#${p}`).join(', ')}</div></div>`;
        }
        if (d.players_to_a && d.players_to_a.length) {
          html += `<div class="kv-row"><div class="kv-key">Players to ${e.primary_org_abbrev || 'Org A'}</div><div class="kv-val">${d.players_to_a.map(p => `#${p}`).join(', ')}</div></div>`;
        }
        if (d.cash_a_to_b) {
          html += `<div class="kv-row"><div class="kv-key">Cash</div><div class="kv-val">$${Number(d.cash_a_to_b).toLocaleString()} (${e.primary_org_abbrev || 'A'} &rarr; ${e.secondary_org_abbrev || 'B'})</div></div>`;
        }
        if (d.salary_retention && Object.keys(d.salary_retention).length) {
          const retRows = Object.entries(d.salary_retention).map(([pid, info]) =>
            `Player #${pid}: ${(info.retention_pct * 100).toFixed(0)}% retained by Org #${info.retaining_org_id}`
          ).join('<br>');
          html += `<div class="kv-row"><div class="kv-key">Salary Retention</div><div class="kv-val">${retRows}</div></div>`;
        }
        if (d.share_mutations && d.share_mutations.length) {
          html += `<div class="kv-row"><div class="kv-key">Share Mutations</div><div class="kv-val">${d.share_mutations.length} contract-year transfers</div></div>`;
        }
        break;
      }
    }
    html += `</div>`;
    return html;
  }

  function loadTransactionLog() {
    fetchTxContext();
    const tbody = document.getElementById('tx-log-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';

    const typeFilter = document.getElementById('tx-log-type-filter').value;
    const orgFilter = document.getElementById('tx-log-org-filter').value;
    const playerFilter = document.getElementById('tx-log-player-filter').value;
    const limit = document.getElementById('tx-log-limit').value || 50;

    let url = `${API_BASE}/transactions/log?limit=${limit}`;
    if (typeFilter) url += `&type=${typeFilter}`;
    if (orgFilter) url += `&org_id=${orgFilter}`;
    if (playerFilter) url += `&player_id=${playerFilter}`;

    fetch(url)
      .then(r => r.json())
      .then(entries => {
        if (!entries.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No transactions found</td></tr>';
          return;
        }
        // Cache entries for detail view without re-fetching
        window._txLogCache = {};
        entries.forEach(e => { window._txLogCache[e.id] = e; });

        tbody.innerHTML = entries.map(e => {
          const ts = e.executed_at ? new Date(e.executed_at).toLocaleString()
                   : e.created_at ? new Date(e.created_at).toLocaleString() : '--';
          const typeBadge = TX_TYPE_BADGES[e.transaction_type] || '';
          const notes = e.notes || '';
          const isRollback = notes.includes('ROLLBACK');
          const orgLabel = e.primary_org_abbrev || (e.primary_org_id ? `#${e.primary_org_id}` : '--');
          const playerLabel = e.player_name || (e.player_id ? `#${e.player_id}` : '--');
          const summary = _txSummary(e);

          return `<tr${isRollback ? ' style="opacity: 0.5"' : ''}>
            <td>${e.id}</td>
            <td style="white-space: nowrap">${ts}</td>
            <td><span class="badge ${typeBadge}">${e.transaction_type}</span></td>
            <td>${orgLabel}</td>
            <td>${playerLabel}</td>
            <td>${summary}</td>
            <td style="white-space: nowrap">
              <button class="btn btn-sm btn-secondary" onclick="App.viewTxDetail(${e.id})">Detail</button>
              ${!isRollback ? `<button class="btn btn-sm btn-danger" onclick="App.rollbackTx(${e.id})">Rollback</button>` : '<span class="text-muted" style="font-size: 0.8em">rolled back</span>'}
              <button class="btn btn-sm" style="opacity:0.6" onclick="App.deleteTxEntry(${e.id})" title="Delete log entry">&times;</button>
            </td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function viewTxDetail(txId) {
    const panel = document.getElementById('tx-log-detail-panel');
    const titleEl = document.getElementById('tx-detail-title');
    const summaryEl = document.getElementById('tx-detail-summary');
    const rawEl = document.getElementById('tx-log-detail');

    panel.style.display = 'block';
    summaryEl.innerHTML = '<span class="text-muted">Loading...</span>';
    rawEl.textContent = '';
    titleEl.textContent = `Transaction #${txId}`;

    // Try cache first, otherwise fetch
    const cached = window._txLogCache && window._txLogCache[txId];
    if (cached) {
      _renderTxDetail(cached, summaryEl, rawEl);
      return;
    }

    fetch(`${API_BASE}/transactions/log?limit=1&tx_id=${txId}`)
      .then(r => r.json())
      .then(entries => {
        if (entries.length > 0) {
          _renderTxDetail(entries[0], summaryEl, rawEl);
        } else {
          summaryEl.innerHTML = '<span class="text-danger">Transaction not found</span>';
        }
      })
      .catch(() => {
        summaryEl.innerHTML = '<span class="text-danger">Could not load detail</span>';
      });
  }

  function _renderTxDetail(entry, summaryEl, rawEl) {
    summaryEl.innerHTML = _txDetailHtml(entry);
    rawEl.textContent = JSON.stringify(entry, null, 2);
  }

  function closeTxDetail() {
    document.getElementById('tx-log-detail-panel').style.display = 'none';
  }

  function rollbackTx(txId) {
    // Get info from cache for a better confirmation message
    const cached = window._txLogCache && window._txLogCache[txId];
    let msg = `Rollback transaction #${txId}?`;
    if (cached) {
      const player = cached.player_name || `Player #${cached.player_id}`;
      msg = `Rollback ${cached.transaction_type} of ${player}?\n\nThis will reverse the operation.`;
    }
    if (!confirm(msg)) return;

    const panel = document.getElementById('tx-log-detail-panel');
    const summaryEl = document.getElementById('tx-detail-summary');
    const rawEl = document.getElementById('tx-log-detail');
    const titleEl = document.getElementById('tx-detail-title');

    panel.style.display = 'block';
    titleEl.textContent = `Rolling back #${txId}...`;
    summaryEl.innerHTML = '<span class="text-warning">Processing rollback...</span>';
    rawEl.textContent = '';

    fetch(`${API_BASE}/transactions/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ transaction_id: txId, executed_by: 'admin' }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          titleEl.textContent = `Rollback Failed`;
          summaryEl.innerHTML = `<span class="text-danger">Error: ${data.message || data.error}</span>`;
        } else {
          titleEl.textContent = `Rollback Successful`;
          summaryEl.innerHTML = `<span class="text-success">Transaction #${txId} has been rolled back.</span>`;
          rawEl.textContent = JSON.stringify(data, null, 2);
          loadTransactionLog();
        }
      })
      .catch(err => {
        titleEl.textContent = `Rollback Failed`;
        summaryEl.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
      });
  }

  function deleteTxEntry(txId) {
    if (!confirm(`Delete transaction log entry #${txId}? This only removes the log record, not the underlying data.`)) return;
    fetch(`${API_BASE}/transactions/log/${txId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          loadTransactionLog();
        } else {
          alert('Error: ' + (data.message || data.error));
        }
      })
      .catch(err => alert('Error: ' + err.message));
  }

  function bulkDeleteTxLog() {
    const sel = document.getElementById('tx-bulk-types');
    const types = Array.from(sel.selectedOptions).map(o => o.value);
    if (!types.length) { alert('Select at least one category'); return; }

    const lyId = txLeagueYearId;
    if (!lyId) {
      fetchTxContext();
      alert('League year not loaded yet — try again');
      return;
    }

    if (!confirm(`Delete all ${types.join(', ')} entries for league year ${lyId}?`)) return;

    const resultEl = document.getElementById('tx-bulk-result');
    resultEl.style.display = 'block';
    resultEl.textContent = 'Deleting...';

    fetch(`${API_BASE}/transactions/log/bulk-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ league_year_id: lyId, types }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          resultEl.textContent = `Deleted ${data.deleted_count} entries (types: ${data.types.join(', ')})`;
          loadTransactionLog();
        } else {
          resultEl.textContent = 'Error: ' + (data.message || data.error);
        }
      })
      .catch(err => { resultEl.textContent = 'Error: ' + err.message; });
  }

  // -----------------------------------------------------------------------
  // Roster Compliance
  // -----------------------------------------------------------------------

  function loadRosterCompliance() {
    populateTxOrgDropdown('compliance-org-select');
    document.getElementById('compliance-summary-card').style.display = 'none';
    document.getElementById('compliance-detail-card').style.display = 'none';

    document.getElementById('btn-compliance-load').onclick = () => {
      const orgId = document.getElementById('compliance-org-select').value;
      fetchComplianceData(orgId || null);
    };
    document.getElementById('compliance-violations-only').onchange = () => {
      renderComplianceTable();
    };
  }

  let complianceData = [];

  function fetchComplianceData(orgId) {
    const summaryCard = document.getElementById('compliance-summary-card');
    const detailCard = document.getElementById('compliance-detail-card');
    const tbody = document.getElementById('compliance-tbody');
    summaryCard.style.display = 'none';
    detailCard.style.display = 'block';
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Loading...</td></tr>';

    const orgsToFetch = orgId
      ? [txOrgList.find(o => o.id === parseInt(orgId))].filter(Boolean)
      : txOrgList.filter(o => o.league === 'mlb');

    if (!orgsToFetch.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No organizations found</td></tr>';
      return;
    }

    const levelNames = { 9: 'MLB', 8: 'AAA', 7: 'AA', 6: 'High-A', 5: 'A', 4: 'Scraps', 3: 'College' };

    Promise.all(orgsToFetch.map(org =>
      fetch(`${API_BASE}/transactions/roster-status/${org.id}`)
        .then(r => r.json())
        .then(levels => {
          if (!Array.isArray(levels)) return [];
          return levels
            .filter(l => l.max_roster > 0 || l.min_roster > 0)
            .map(l => ({
              org_id: org.id,
              org_abbrev: org.org_abbrev,
              level_id: l.level_id,
              level_name: levelNames[l.level_id] || l.level_name,
              count: l.count,
              min_roster: l.min_roster,
              max_roster: l.max_roster,
              over_limit: l.over_limit,
              under_limit: l.under_limit,
            }));
        })
        .catch(() => [])
    )).then(results => {
      complianceData = results.flat();
      renderComplianceSummary();
      renderComplianceTable();
    });
  }

  function renderComplianceSummary() {
    const card = document.getElementById('compliance-summary-card');
    const container = document.getElementById('compliance-summary');
    card.style.display = 'block';

    const totalOrgs = new Set(complianceData.map(r => r.org_id)).size;
    const overRows = complianceData.filter(r => r.over_limit);
    const underRows = complianceData.filter(r => r.under_limit);
    const compliantOrgs = totalOrgs - new Set([
      ...overRows.map(r => r.org_id),
      ...underRows.map(r => r.org_id),
    ]).size;

    container.innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Organizations</div>
        <div class="stat-value">${totalOrgs}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Fully Compliant</div>
        <div class="stat-value" style="color: ${compliantOrgs === totalOrgs ? 'var(--success)' : 'var(--text-primary)'}">${compliantOrgs}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Violations</div>
        <div class="stat-value" style="color: ${(overRows.length + underRows.length) > 0 ? 'var(--danger)' : 'var(--success)'}">${overRows.length + underRows.length}</div>
        <div class="stat-sub">${overRows.length} over / ${underRows.length} under</div>
      </div>
    `;
  }

  function renderComplianceTable() {
    const tbody = document.getElementById('compliance-tbody');
    const violationsOnly = document.getElementById('compliance-violations-only').checked;

    let rows = complianceData;
    if (violationsOnly) {
      rows = rows.filter(r => r.over_limit || r.under_limit);
    }

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">${violationsOnly ? 'No violations found' : 'No data'}</td></tr>`;
      return;
    }

    // Sort: violations first, then by org + level
    rows = [...rows].sort((a, b) => {
      const aViolation = a.over_limit || a.under_limit ? 0 : 1;
      const bViolation = b.over_limit || b.under_limit ? 0 : 1;
      if (aViolation !== bViolation) return aViolation - bViolation;
      const orgCmp = a.org_abbrev.localeCompare(b.org_abbrev);
      if (orgCmp !== 0) return orgCmp;
      return b.level_id - a.level_id;
    });

    tbody.innerHTML = rows.map(r => {
      let statusBadge, rowStyle;
      if (r.over_limit) {
        statusBadge = '<span class="badge badge-danger">OVER</span>';
        rowStyle = 'background: rgba(239, 68, 68, 0.08);';
      } else if (r.under_limit) {
        statusBadge = '<span class="badge badge-warning">UNDER</span>';
        rowStyle = 'background: rgba(245, 158, 11, 0.08);';
      } else {
        statusBadge = '<span class="badge badge-success">OK</span>';
        rowStyle = '';
      }
      return `<tr style="${rowStyle}">
        <td><strong>${r.org_abbrev}</strong></td>
        <td>${r.level_name}</td>
        <td>${r.count}</td>
        <td>${r.min_roster != null ? r.min_roster : '--'}</td>
        <td>${r.max_roster != null ? r.max_roster : '--'}</td>
        <td>${statusBadge}</td>
      </tr>`;
    }).join('');
  }

  // ── Player Engine: Generation ──────────────────────────────────────

  function loadGeneration() {
    // Load seed table status whenever this section is entered
    loadSeedStatus();
  }

  function loadSeedStatus() {
    const tbody = document.getElementById('pe-seed-tbody');
    tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Loading…</td></tr>';
    fetch(`${API_BASE}/player-ops/seed-status`)
      .then(r => r.json())
      .then(tables => {
        if (!tables.length) {
          tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No seed tables found</td></tr>';
          return;
        }
        tbody.innerHTML = tables.map(t => {
          const ok = t.rows > 0;
          return `<tr>
            <td><code>${t.table}</code></td>
            <td>${t.rows >= 0 ? t.rows.toLocaleString() : 'Error'}</td>
            <td><span class="badge ${ok ? 'badge-success' : 'badge-danger'}">${ok ? 'Ready' : 'Empty'}</span></td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="3" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function generatePlayers() {
    const count = parseInt(document.getElementById('pe-gen-count').value) || 1;
    const age = parseInt(document.getElementById('pe-gen-age').value) || 15;
    const statusEl = document.getElementById('pe-gen-status');
    const tbody = document.getElementById('pe-gen-tbody');

    statusEl.textContent = `Generating ${count} player${count > 1 ? 's' : ''}…`;
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Working…</td></tr>';

    fetch(`${API_BASE}/player-ops/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count, age }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(`${r.status}: ${t.slice(0, 300)}`); });
        return r.json();
      })
      .then(data => {
        if (data.error) {
          statusEl.textContent = `Error: ${data.message}`;
          tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">Generation failed</td></tr>';
          return;
        }
        let msg = `Generated ${data.created} player${data.created > 1 ? 's' : ''}.`;
        if (data.truncated) msg += ` Showing first ${data.showing} in table.`;
        statusEl.textContent = msg;
        if (!data.players || !data.players.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No results</td></tr>';
          return;
        }
        tbody.innerHTML = data.players.map(p => `<tr>
          <td>${p.id}</td>
          <td>${p.firstname} ${p.lastname}</td>
          <td>${p.ptype}</td>
          <td>${p.age}</td>
          <td>${p.area}</td>
        </tr>`).join('');
      })
      .catch(err => {
        statusEl.textContent = `Error: ${err.message}`;
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">Request failed</td></tr>';
      });
  }

  // ── Player Engine: Progression ────────────────────────────────────

  function loadProgression() {
    // Clear previous statuses on section load
    document.getElementById('pe-prog-all-status').textContent = '';
    document.getElementById('pe-prog-one-status').textContent = '';
  }

  function progressAll() {
    const maxAge = parseInt(document.getElementById('pe-prog-max-age').value) || 45;
    if (!confirm(`Progress ALL players (under age ${maxAge}) by one year? This may take a while.`)) return;

    const statusEl = document.getElementById('pe-prog-all-status');
    statusEl.textContent = 'Running batch progression…';

    fetch(`${API_BASE}/player-ops/progress-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_age: maxAge }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          statusEl.textContent = `Error: ${data.message}`;
          return;
        }
        statusEl.textContent = `Done — progressed ${data.progressed} player${data.progressed !== 1 ? 's' : ''}.`;
      })
      .catch(err => {
        statusEl.textContent = `Error: ${err.message}`;
      });
  }

  function progressSingle() {
    const pid = parseInt(document.getElementById('pe-prog-pid').value);
    if (!pid || pid < 1) {
      document.getElementById('pe-prog-one-status').textContent = 'Enter a valid player ID.';
      return;
    }

    const statusEl = document.getElementById('pe-prog-one-status');
    statusEl.textContent = `Progressing player ${pid}…`;

    fetch(`${API_BASE}/player-ops/progress/${pid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          statusEl.textContent = `Error: ${data.message}`;
          return;
        }
        statusEl.textContent = `Player ${data.player_id} progressed successfully.`;
      })
      .catch(err => {
        statusEl.textContent = `Error: ${err.message}`;
      });
  }

  // ── End of Season ──────────────────────────────────────────────────

  // ── Amateur Seeding ──────────────────────────────────────────
  function loadAmateurPreview() {
    const btn = document.getElementById('btn-amateur-preview');
    btn.disabled = true;
    btn.textContent = 'Scanning...';

    fetch(`${ADMIN_BASE}/amateur-contracts-preview`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;
        btn.textContent = 'Scan Players';

        if (data.error) {
          alert('Error: ' + data.message);
          return;
        }

        document.getElementById('amateur-preview').style.display = 'block';

        // Summary cards
        const cards = document.getElementById('amateur-summary-cards');
        const total = (data.hs.total || 0) + (data.intam_young.total || 0) + (data.intam_older.total || 0) + (data.college.total || 0);
        cards.innerHTML = `
          <div class="stat-card">
            <div class="stat-label">Total Uncontracted</div>
            <div class="stat-value">${data.total_uncontracted.toLocaleString()}</div>
            <div class="stat-sub">${total.toLocaleString()} assignable, ${data.skipped} skipped</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">College Eligible</div>
            <div class="stat-value">${data.college.total.toLocaleString()}</div>
            <div class="stat-sub">${data.college.avg_pitchers_per_org} P / ${data.college.avg_batters_per_org} B per org (target ${data.college.target_per_org})</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Pre-Professional</div>
            <div class="stat-value">${(data.hs.total + data.intam_young.total + data.intam_older.total).toLocaleString()}</div>
            <div class="stat-sub">${data.hs.total} HS + ${data.intam_young.total + data.intam_older.total} INTAM</div>
          </div>
        `;

        // Breakdown table
        const tbody = document.getElementById('amateur-breakdown-tbody');
        tbody.innerHTML = [
          { cat: 'High School', org: data.hs.org, range: '15-17', p: data.hs.pitchers, b: data.hs.batters, t: data.hs.total, notes: 'USA only, contracts expire at 18' },
          { cat: 'INTAM (Young)', org: data.intam_young.org, range: data.intam_young.age_range, p: data.intam_young.pitchers, b: data.intam_young.batters, t: data.intam_young.total, notes: 'International, expire at 18' },
          { cat: 'INTAM (Older)', org: data.intam_older.org, range: data.intam_older.age_range, p: data.intam_older.pitchers, b: data.intam_older.batters, t: data.intam_older.total, notes: 'International, expire at 23' },
          { cat: 'College', org: `${data.college.orgs_available} orgs`, range: '18-23', p: data.college.pitchers, b: data.college.batters, t: data.college.total, notes: `~20% redshirt (+1yr), target ${data.college.target_per_org}/org` },
        ].map(r => `
          <tr>
            <td><strong>${r.cat}</strong></td>
            <td>${r.org}</td>
            <td>${r.range}</td>
            <td>${r.p.toLocaleString()}</td>
            <td>${r.b.toLocaleString()}</td>
            <td><strong>${r.t.toLocaleString()}</strong></td>
            <td class="text-muted">${r.notes}</td>
          </tr>
        `).join('');
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Scan Players';
        alert('Error: ' + err.message);
      });
  }

  function runAmateurSeed() {
    if (!confirm('This will create contracts for all uncontracted amateur players (HS, INTAM, College). Continue?')) {
      return;
    }

    const btn = document.getElementById('btn-amateur-seed');
    btn.disabled = true;
    btn.textContent = 'Seeding...';

    fetch(`${ADMIN_BASE}/seed-amateur-contracts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;
        btn.textContent = 'Seed Amateur Contracts';

        if (data.error) {
          alert(`Error: ${data.message}`);
          return;
        }

        const d = data.details || data;
        const resultDiv = document.getElementById('amateur-seed-kv');
        const card = document.getElementById('amateur-seed-result');
        card.style.display = 'block';

        const labels = {
          hs_contracts: 'HS Contracts Created',
          intam_contracts: 'INTAM Contracts Created',
          college_contracts: 'College Contracts Created',
          total_contracts: 'Total Contracts',
          redshirt_count: 'Redshirt Players',
          details_created: 'Contract Detail Rows',
          shares_created: 'Team Share Rows',
          skipped_no_age: 'Skipped (No Age)',
          skipped_zero_years: 'Skipped (Zero Years)',
        };

        resultDiv.innerHTML = Object.entries(labels).map(([key, label]) => `
          <div class="kv-row">
            <div class="kv-key">${label}</div>
            <div class="kv-val">${d[key] !== undefined ? d[key].toLocaleString() : '--'}</div>
          </div>
        `).join('');

        // Refresh the preview
        loadAmateurPreview();
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Seed Amateur Contracts';
        alert('Error: ' + err.message);
      });
  }

  function populateCollegeOrgs() {
    const resultBox = document.getElementById('populate-college-result');
    const orgIdsRaw = document.getElementById('pop-org-ids').value.trim();
    const pitchers = parseInt(document.getElementById('pop-pitchers').value) || 17;
    const batters = parseInt(document.getElementById('pop-batters').value) || 17;

    if (!orgIdsRaw) { resultBox.textContent = 'Please enter org IDs.'; return; }

    const orgIds = orgIdsRaw.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
    if (orgIds.length === 0) { resultBox.textContent = 'Invalid org IDs.'; return; }

    const totalPlayers = orgIds.length * (pitchers + batters);
    if (!confirm(`This will generate ${totalPlayers} players across ${orgIds.length} org(s) and create college contracts. Continue?`)) {
      return;
    }

    resultBox.textContent = `Generating ${totalPlayers} players for orgs ${orgIds.join(', ')}...`;

    fetch(`${ADMIN_BASE}/populate-college-orgs`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        org_ids: orgIds,
        pitchers_per_org: pitchers,
        batters_per_org: batters,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          let lines = [`Done — ${data.total_players_generated} players, ${data.total_contracts} contracts\n`];
          if (data.per_org) {
            for (const [orgId, info] of Object.entries(data.per_org)) {
              lines.push(`  Org ${orgId}: ${info.players} players, ${info.contracts} contracts`);
            }
          }
          lines.push(`\nDetails rows: ${data.total_details}`);
          lines.push(`Share rows: ${data.total_shares}`);
          resultBox.textContent = lines.join('\n');
        } else {
          resultBox.textContent = `Error: ${data.message || 'unknown'}`;
        }
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  function loadEndOfSeason() {
    fetchTxContext().then(() => {
      const info = document.getElementById('eos-season-info');
      info.innerHTML = `<strong>Current Season:</strong> League Year ID ${txLeagueYearId} &nbsp;|&nbsp; Week ${txGameWeekId}`;
    });
    populateTxOrgDropdown('eos-org-select');
    document.getElementById('eos-result-card').style.display = 'none';
  }

  function runEndOfSeason() {
    if (!txLeagueYearId) {
      alert('Could not determine league year. Please wait for season info to load.');
      return;
    }
    if (!confirm('This will process ALL end-of-season contract operations (service time, renewals, expirations). Continue?')) {
      return;
    }

    const btn = document.getElementById('btn-eos-run');
    btn.disabled = true;
    btn.textContent = 'Processing...';

    fetch(`${API_BASE}/transactions/end-of-season`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: txLeagueYearId }),
    })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;
        btn.textContent = 'Process End of Season';

        if (data.error) {
          alert(`Error: ${data.message}`);
          return;
        }

        const resultDiv = document.getElementById('eos-result');
        const card = document.getElementById('eos-result-card');
        card.style.display = 'block';

        const labels = {
          league_year: 'League Year',
          service_time_credited: 'Service Time Credited',
          contracts_advanced: 'Contracts Advanced',
          contracts_expired: 'Contracts Expired',
          auto_renewed_minor: 'Auto-Renewed (Minor League)',
          auto_renewed_pre_arb: 'Auto-Renewed (Pre-Arb MLB)',
          became_free_agents: 'Became Free Agents',
          extensions_activated: 'Extensions Activated',
        };

        resultDiv.innerHTML = Object.entries(labels).map(([key, label]) => `
          <div class="kv-row">
            <div class="kv-key">${label}</div>
            <div class="kv-val">${data[key] !== undefined ? data[key] : '--'}</div>
          </div>
        `).join('');
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Process End of Season';
        alert('Error: ' + err.message);
      });
  }

  function loadServiceOverview(orgId) {
    const tbody = document.getElementById('eos-overview-tbody');
    tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">Loading...</td></tr>';

    fetch(`${API_BASE}/transactions/contract-overview/${orgId}`)
      .then(r => r.json())
      .then(players => {
        if (!Array.isArray(players) || players.length === 0) {
          tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">No active players found</td></tr>';
          return;
        }

        const levelNames = { 9: 'MLB', 8: 'AAA', 7: 'AA', 6: 'High-A', 5: 'A', 4: 'Scraps' };
        const phaseBadge = (phase) => {
          const colors = {
            minor: 'background:#2d7a4f;color:#fff',
            pre_arb: 'background:#2563eb;color:#fff',
            arb_eligible: 'background:#d97706;color:#fff',
            fa_eligible: 'background:#dc2626;color:#fff',
          };
          const labels = {
            minor: 'Minor',
            pre_arb: 'Pre-Arb',
            arb_eligible: 'Arb',
            fa_eligible: 'FA Eligible',
          };
          const style = colors[phase] || 'background:#666;color:#fff';
          return `<span style="padding:2px 8px;border-radius:4px;font-size:0.8em;${style}">${labels[phase] || phase}</span>`;
        };

        tbody.innerHTML = players.map(p => {
          const salary = p.salary ? `$${Number(p.salary).toLocaleString()}` : '--';
          return `<tr>
            <td>${p.player_name}</td>
            <td>${p.position || '--'}</td>
            <td>${p.age}</td>
            <td>${levelNames[p.current_level] || p.current_level}</td>
            <td>${p.mlb_service_years}</td>
            <td>${phaseBadge(p.contract_phase)}</td>
            <td>Yr ${p.current_year}/${p.years}${p.years_to_arb != null ? ` (${p.years_to_arb} to arb)` : ''}${p.years_to_fa != null ? ` (${p.years_to_fa} to FA)` : ''}</td>
            <td>${salary}</td>
            <td>${p.is_expiring ? '<span style="color:var(--danger)">Yes</span>' : 'No'}</td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">Error: ${err.message}</td></tr>`;
      });
  }

  // ── Progression Sandbox ──────────────────────────────────────────────

  // Grade color palette (consistent across charts)
  const GRADE_COLORS = {
    'A+': '#0d6a3a', 'A': '#16a34a', 'A-': '#4ade80',
    'B+': '#0e7490', 'B': '#06b6d4', 'B-': '#67e8f9',
    'C+': '#ca8a04', 'C': '#facc15', 'C-': '#fde68a',
    'D+': '#ea580c', 'D': '#f97316', 'D-': '#fdba74',
    'F': '#dc2626', 'N': '#9ca3af',
  };

  let sandboxData = null;
  let sandboxChart = null;

  function runSandbox() {
    const count = parseInt(document.getElementById('sandbox-count').value) || 200;
    const seasons = parseInt(document.getElementById('sandbox-seasons').value) || 20;
    const startAge = parseInt(document.getElementById('sandbox-start-age').value) || 15;
    const ptype = document.getElementById('sandbox-ptype').value;
    const statusEl = document.getElementById('sandbox-status');
    const btn = document.getElementById('btn-sandbox-run');

    btn.disabled = true;
    statusEl.textContent = `Simulating ${count} players over ${seasons} seasons...`;
    document.getElementById('sandbox-chart-card').style.display = 'none';
    document.getElementById('sandbox-summary-card').style.display = 'none';

    fetch(`${ADMIN_BASE}/progression-sandbox`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        count,
        seasons,
        start_age: startAge,
        player_type: ptype,
      }),
    })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;

        if (data.error) {
          statusEl.textContent = `Error: ${data.message}`;
          return;
        }

        sandboxData = data;
        statusEl.textContent = `Simulation complete — ${data.config.count} players, ${data.config.seasons} seasons.`;

        // Populate ability dropdown
        const abilitySelect = document.getElementById('sandbox-ability-select');
        abilitySelect.innerHTML = data.tracked_abilities.map(a =>
          `<option value="${a}">${a}</option>`
        ).join('');

        // Populate grade filter dropdown from available grades
        populateSandboxGradeFilter();

        document.getElementById('sandbox-chart-card').style.display = 'block';
        document.getElementById('sandbox-summary-card').style.display = 'block';

        renderSandboxChart();
      })
      .catch(err => {
        btn.disabled = false;
        statusEl.textContent = `Error: ${err.message}`;
      });
  }

  function populateSandboxGradeFilter() {
    if (!sandboxData) return;
    const ability = document.getElementById('sandbox-ability-select').value;
    const gradeData = sandboxData.results[ability];
    if (!gradeData) return;

    const gradeSelect = document.getElementById('sandbox-grade-filter');
    const grades = Object.keys(gradeData);
    gradeSelect.innerHTML = '<option value="__all__">All</option>' +
      grades.map(g => `<option value="${g}">${g} (${gradeData[g].count})</option>`).join('');

    // Reset highlight dropdown
    updateHighlightDropdown();
  }

  function updateHighlightDropdown() {
    const hlSelect = document.getElementById('sandbox-highlight-player');
    const gradeFilter = document.getElementById('sandbox-grade-filter').value;
    const ability = document.getElementById('sandbox-ability-select').value;
    const gradeData = sandboxData?.results[ability];
    if (!gradeData) return;

    let players = [];
    const gradesToShow = gradeFilter === '__all__' ? Object.keys(gradeData) : [gradeFilter];
    for (const g of gradesToShow) {
      if (!gradeData[g]?.players) continue;
      for (const p of gradeData[g].players) {
        const peak = Math.max(...p.trajectory);
        players.push({ id: p.id, grade: g, ptype: p.ptype, peak });
      }
    }

    // Sort by peak descending so best performers are on top
    players.sort((a, b) => b.peak - a.peak);

    hlSelect.innerHTML = '<option value="">None</option>' +
      players.map(p =>
        `<option value="${p.id}">P${p.id} (${p.grade}, ${p.ptype}, peak ${p.peak.toFixed(0)})</option>`
      ).join('');
  }

  function onTogglePlayerOverlay() {
    const show = document.getElementById('sandbox-show-players').checked;
    document.getElementById('sandbox-grade-filter-label').style.display = show ? '' : 'none';
    document.getElementById('sandbox-highlight-label').style.display = show ? '' : 'none';
    if (show) {
      populateSandboxGradeFilter();
    }
    renderSandboxChart();
  }

  function renderSandboxChart() {
    if (!sandboxData) return;

    const ability = document.getElementById('sandbox-ability-select').value;
    const showBands = document.getElementById('sandbox-show-bands').checked;
    const showPlayers = document.getElementById('sandbox-show-players').checked;
    const gradeFilter = document.getElementById('sandbox-grade-filter').value;
    const highlightId = document.getElementById('sandbox-highlight-player').value;
    const gradeData = sandboxData.results[ability];
    if (!gradeData) return;

    // Re-populate grade filter when ability changes
    const gradeSelect = document.getElementById('sandbox-grade-filter');
    if (gradeSelect.options.length <= 1) populateSandboxGradeFilter();

    // Destroy old chart
    if (sandboxChart) {
      sandboxChart.destroy();
      sandboxChart = null;
    }

    const datasets = [];
    const grades = Object.keys(gradeData);

    // When individual overlay is active, dim aggregate elements
    const hasIndividualView = showPlayers;
    const hasHighlight = showPlayers && highlightId !== '';

    // Draw individual player lines first (behind aggregate)
    if (showPlayers) {
      const gradesToDraw = gradeFilter === '__all__' ? grades : [gradeFilter];

      for (const grade of gradesToDraw) {
        const gd = gradeData[grade];
        if (!gd?.players) continue;
        const color = GRADE_COLORS[grade] || '#6b7280';

        for (const p of gd.players) {
          const isHighlighted = hasHighlight && String(p.id) === highlightId;
          datasets.push({
            label: `_p${p.id}`,
            data: gd.ages.map((age, i) => ({ x: age, y: p.trajectory[i] })),
            borderColor: isHighlighted ? color : color + (hasHighlight ? '20' : '40'),
            backgroundColor: 'transparent',
            borderWidth: isHighlighted ? 3 : 1,
            pointRadius: isHighlighted ? 3 : 0,
            tension: 0.3,
            fill: false,
            order: isHighlighted ? 0 : 2,
            _playerMeta: { id: p.id, grade, ptype: p.ptype },
          });
        }
      }
    }

    // Aggregate lines — dimmed when individual overlay is active
    for (const grade of grades) {
      const gd = gradeData[grade];
      const color = GRADE_COLORS[grade] || '#6b7280';

      datasets.push({
        label: grade,
        data: gd.ages.map((age, i) => ({ x: age, y: gd.avg[i] })),
        borderColor: hasIndividualView ? color + '30' : color,
        backgroundColor: hasIndividualView ? color + '30' : color,
        borderWidth: hasIndividualView ? 1.5 : 2.5,
        pointRadius: hasIndividualView ? 0 : 2,
        tension: 0.3,
        fill: false,
        order: hasIndividualView ? 3 : 1,
      });

      if (showBands) {
        datasets.push({
          label: `_${grade}_upper`,
          data: gd.ages.map((age, i) => ({ x: age, y: gd.p90[i] })),
          borderColor: 'transparent',
          backgroundColor: hasIndividualView ? color + '08' : color + '18',
          borderWidth: 0,
          pointRadius: 0,
          fill: '+1',
          showLine: true,
          order: hasIndividualView ? 4 : 3,
        });
        datasets.push({
          label: `_${grade}_lower`,
          data: gd.ages.map((age, i) => ({ x: age, y: gd.p10[i] })),
          borderColor: 'transparent',
          backgroundColor: 'transparent',
          borderWidth: 0,
          pointRadius: 0,
          fill: false,
          showLine: true,
          order: hasIndividualView ? 4 : 3,
        });
      }
    }

    const ctx = document.getElementById('sandbox-chart').getContext('2d');
    sandboxChart = new Chart(ctx, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: {
          mode: 'nearest',
          intersect: false,
        },
        scales: {
          x: {
            type: 'linear',
            title: { display: true, text: 'Age' },
            ticks: { stepSize: 1 },
          },
          y: {
            title: { display: true, text: 'Base Value' },
          },
        },
        plugins: {
          legend: {
            labels: {
              filter: item => !item.text.startsWith('_'),
            },
          },
          tooltip: {
            filter: item => !item.dataset.label.startsWith('_'),
            callbacks: {
              afterBody: function (items) {
                // Show player info when hovering a highlighted player
                const ds = items[0]?.dataset;
                if (ds?._playerMeta) {
                  return `Player ${ds._playerMeta.id} | ${ds._playerMeta.grade} ${ds._playerMeta.ptype}`;
                }
                return '';
              },
            },
          },
        },
        onClick: function (_evt, elements) {
          if (!elements.length) return;
          const ds = sandboxChart.data.datasets[elements[0].datasetIndex];
          if (ds._playerMeta) {
            // Click a player line to highlight it
            document.getElementById('sandbox-highlight-player').value = String(ds._playerMeta.id);
            renderSandboxChart();
          }
        },
      },
    });

    renderSandboxSummary(gradeData);
  }

  function renderSandboxSummary(gradeData) {
    const tbody = document.getElementById('sandbox-grade-tbody');
    const rows = [];

    for (const [grade, gd] of Object.entries(gradeData)) {
      const finalAvg = gd.avg[gd.avg.length - 1];
      const peakAvg = Math.max(...gd.avg);

      // Compute best/worst individual by peak value
      let bestPeak = -Infinity, worstPeak = Infinity;
      if (gd.players) {
        for (const p of gd.players) {
          const peak = Math.max(...p.trajectory);
          if (peak > bestPeak) bestPeak = peak;
          if (peak < worstPeak) worstPeak = peak;
        }
      }

      rows.push(`<tr>
        <td><span style="color: ${GRADE_COLORS[grade] || '#6b7280'}; font-weight: 600;">${grade}</span></td>
        <td>${gd.count}</td>
        <td>${finalAvg.toFixed(1)}</td>
        <td>${peakAvg.toFixed(1)}</td>
        <td>${bestPeak > -Infinity ? bestPeak.toFixed(1) : '--'}</td>
        <td>${worstPeak < Infinity ? worstPeak.toFixed(1) : '--'}</td>
      </tr>`);
    }

    tbody.innerHTML = rows.join('');
  }

  // ---------------------------------------------------------------------------
  // Schedule Generator
  // ---------------------------------------------------------------------------

  function onSchedLevelChange() {
    const level = parseInt(document.getElementById('sched-level').value);
    const startWeekInput = document.getElementById('sched-start-week');
    if (level === 9) {
      startWeekInput.value = '1';
      startWeekInput.disabled = true;
    } else if (level === 3) {
      startWeekInput.value = '1';
      startWeekInput.disabled = false;
    } else {
      startWeekInput.disabled = false;
      if (startWeekInput.value === '1') startWeekInput.value = '10';
    }
  }

  function loadScheduleReport() {
    const container = document.getElementById('sched-report-container');
    container.innerHTML = '<p class="text-muted">Loading...</p>';

    fetch(`${ADMIN_BASE}/schedule/report`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) {
          container.innerHTML = `<p class="text-error">${data.message || data.error}</p>`;
          return;
        }

        const seasons = data.seasons || {};
        const years = Object.keys(seasons).sort();

        if (years.length === 0) {
          container.innerHTML = '<p class="text-muted">No schedules found in the database.</p>';
          return;
        }

        let html = '<table class="data-table"><thead><tr><th>Year</th><th>Level</th><th>Games</th><th>Teams</th><th>Weeks</th></tr></thead><tbody>';
        for (const year of years) {
          const levels = seasons[year];
          const levelKeys = Object.keys(levels).sort((a, b) => parseInt(b) - parseInt(a));
          for (const lk of levelKeys) {
            const info = levels[lk];
            html += `<tr>
              <td>${year}</td>
              <td>${info.level_name || LEVEL_NAMES[lk] || lk}</td>
              <td>${info.games}</td>
              <td>${info.teams}</td>
              <td>${info.weeks}</td>
            </tr>`;
          }
        }
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(err => {
        container.innerHTML = `<p class="text-error">Error: ${err.message}</p>`;
      });
  }

  function _showSchedResult(text, isError) {
    const box = document.getElementById('sched-result');
    box.style.display = 'block';
    box.textContent = text;
    box.style.color = isError ? '#f44336' : '#4caf50';
  }

  function validateSchedule() {
    const year = document.getElementById('sched-year').value;
    const level = document.getElementById('sched-level').value;

    fetch(`${ADMIN_BASE}/schedule/validate?league_year=${year}&league_level=${level}`, {
      credentials: 'include',
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        let msg = `Valid: ${data.valid}\nTeams: ${data.team_count}\nExisting games: ${data.existing_games}`;
        if (data.errors && data.errors.length) msg += '\n\nErrors:\n- ' + data.errors.join('\n- ');
        if (data.warnings && data.warnings.length) msg += '\n\nWarnings:\n- ' + data.warnings.join('\n- ');
        _showSchedResult(msg, !data.valid);
      })
      .catch(err => _showSchedResult('Error: ' + err.message, true));
  }

  function generateSchedule() {
    const year = document.getElementById('sched-year').value;
    const level = document.getElementById('sched-level').value;
    const startWeek = document.getElementById('sched-start-week').value;
    const seedVal = document.getElementById('sched-seed').value;
    const clearExisting = document.getElementById('sched-clear-existing').checked;

    const levelName = LEVEL_NAMES[level] || level;
    if (!confirm(`Generate ${levelName} schedule for ${year}?\n\nThis may take a moment for large leagues.${clearExisting ? '\n\nExisting schedule will be cleared first.' : ''}`)) {
      return;
    }

    _showSchedResult('Generating schedule...', false);

    fetch(`${ADMIN_BASE}/schedule/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        league_year: parseInt(year),
        league_level: parseInt(level),
        start_week: parseInt(startWeek),
        seed: seedVal ? parseInt(seedVal) : null,
        clear_existing: clearExisting,
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) {
          _showSchedResult('Failed: ' + (data.message || data.error), true);
          return;
        }
        let msg = 'Schedule generated successfully!\n\n';
        msg += `Total games: ${data.total_games}\n`;
        msg += `Total series: ${data.total_series}\n`;
        msg += `Weeks: ${data.weeks}`;
        if (data.start_week) msg += ` (starting week ${data.start_week})`;
        if (data.games_per_team) msg += `\nGames per team: ${data.games_per_team}`;
        _showSchedResult(msg, false);
        loadScheduleReport();
      })
      .catch(err => _showSchedResult('Error: ' + err.message, true));
  }

  function clearSchedule() {
    const year = document.getElementById('sched-year').value;
    const level = document.getElementById('sched-level').value;
    const levelName = LEVEL_NAMES[level] || level;

    if (!confirm(`Delete ALL ${levelName} games for ${year}?\n\nThis action cannot be undone.`)) {
      return;
    }

    _showSchedResult('Clearing schedule...', false);

    fetch(`${ADMIN_BASE}/schedule/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        league_year: parseInt(year),
        league_level: parseInt(level),
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) {
          _showSchedResult('Failed: ' + (data.message || data.error), true);
          return;
        }
        _showSchedResult(`Cleared ${data.deleted} games.`, false);
        loadScheduleReport();
      })
      .catch(err => _showSchedResult('Error: ' + err.message, true));
  }

  function addScheduleSeries() {
    const year = document.getElementById('sched-add-year').value;
    const level = document.getElementById('sched-add-level').value;
    const home = document.getElementById('sched-add-home').value;
    const away = document.getElementById('sched-add-away').value;
    const week = document.getElementById('sched-add-week').value;
    const games = document.getElementById('sched-add-games').value;

    if (!home || !away) {
      alert('Home and Away team IDs are required.');
      return;
    }

    const resultBox = document.getElementById('sched-add-result');

    fetch(`${ADMIN_BASE}/schedule/add-series`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        league_year: parseInt(year),
        league_level: parseInt(level),
        home_team_id: parseInt(home),
        away_team_id: parseInt(away),
        week: parseInt(week),
        games: parseInt(games),
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        resultBox.style.display = 'block';
        if (!data.ok) {
          resultBox.textContent = 'Failed: ' + (data.message || data.error);
          resultBox.style.color = '#f44336';
          return;
        }
        resultBox.textContent = `Added ${data.games_added}-game series in week ${data.week}: team ${data.home_team_id} vs ${data.away_team_id}`;
        resultBox.style.color = '#4caf50';
        loadScheduleReport();
      })
      .catch(err => {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Error: ' + err.message;
        resultBox.style.color = '#f44336';
      });
  }

  // ── Schedule Viewer ──────────────────────────────────────────────

  function loadScheduleViewer() {
    const year = document.getElementById('sv-year').value;
    const level = document.getElementById('sv-level').value;
    const team = document.getElementById('sv-team').value;
    const weekStart = document.getElementById('sv-week-start').value;
    const weekEnd = document.getElementById('sv-week-end').value;

    let url = `${ADMIN_BASE}/schedule/viewer?season_year=${year}&page=${svCurrentPage}&page_size=${svPageSize}`;
    if (level) url += `&league_level=${level}`;
    if (team) url += `&team_id=${team}`;
    if (weekStart) url += `&week_start=${weekStart}`;
    if (weekEnd) url += `&week_end=${weekEnd}`;

    fetch(url, { credentials: 'include' })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) { alert('Error: ' + (data.message || data.error)); return; }

        const totalPages = Math.ceil(data.total / svPageSize) || 1;

        // Weeks summary
        const summaryCard = document.getElementById('sv-summary-card');
        const summaryContainer = document.getElementById('sv-summary-container');
        const weeks = data.weeks_summary || {};
        const weekNums = Object.keys(weeks).map(Number).sort((a, b) => a - b);

        if (weekNums.length > 0) {
          let shtml = '<table class="data-table"><thead><tr><th>Week</th><th>Games</th><th>Series</th></tr></thead><tbody>';
          for (const w of weekNums) {
            shtml += `<tr><td>${w}</td><td>${weeks[w].games}</td><td>${weeks[w].series_count}</td></tr>`;
          }
          shtml += '</tbody></table>';
          summaryContainer.innerHTML = shtml;
          summaryCard.style.display = '';
        } else {
          summaryCard.style.display = 'none';
        }

        // Show quality card only when a level is selected
        document.getElementById('sv-quality-card').style.display = level ? '' : 'none';

        // Games table
        const gamesCard = document.getElementById('sv-games-card');
        const tbody = document.getElementById('sv-games-tbody');
        gamesCard.style.display = '';

        document.getElementById('sv-total-label').textContent = `(${data.total} games)`;
        document.getElementById('sv-page-label').textContent = `Page ${svCurrentPage} of ${totalPages}`;
        document.getElementById('btn-sv-prev').disabled = svCurrentPage <= 1;
        document.getElementById('btn-sv-next').disabled = svCurrentPage >= totalPages;

        if (data.games.length === 0) {
          tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#888">No games found</td></tr>';
          return;
        }

        tbody.innerHTML = data.games.map(g => {
          const hasResult = g.game_outcome != null;
          const scoreText = hasResult
            ? `${g.away_score} - ${g.home_score}`
            : '<span class="text-muted">--</span>';
          const resultText = hasResult
            ? `<span style="color:${g.game_outcome === 'CANCELLED' ? '#f44336' : '#4caf50'}">${g.game_outcome}</span>`
            : '<span class="text-muted">Pending</span>';
          return `<tr>
            <td>${g.id}</td>
            <td>${g.season_week}</td>
            <td>${g.season_subweek || ''}</td>
            <td><span class="badge">${g.level_name}</span></td>
            <td>${g.away_team_abbrev || g.away_team_name} <span class="text-muted">(${g.away_team_id})</span></td>
            <td style="text-align:center">${scoreText}</td>
            <td>${g.home_team_abbrev || g.home_team_name} <span class="text-muted">(${g.home_team_id})</span></td>
            <td>${resultText}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="App.editGame(${g.id}, ${g.home_team_id}, ${g.away_team_id}, ${g.season_week}, '${g.season_subweek || ''}')">Edit</button>
            </td>
          </tr>`;
        }).join('');
      })
      .catch(err => alert('Schedule viewer error: ' + err.message));
  }

  function loadScheduleQuality() {
    const year = document.getElementById('sv-year').value;
    const level = document.getElementById('sv-level').value;

    if (!level) { alert('Select a league level to view quality metrics.'); return; }

    fetch(`${ADMIN_BASE}/schedule/quality?season_year=${year}&league_level=${level}`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) { alert('Error: ' + (data.message || data.error)); return; }

        document.getElementById('sv-quality-stats').style.display = '';
        document.getElementById('sv-avg-games').textContent = data.avg_games_per_team;
        document.getElementById('sv-std-games').textContent = data.std_games_per_team;
        document.getElementById('sv-team-count').textContent = data.team_count;

        const teams = data.games_per_team;
        const tids = Object.keys(teams).sort((a, b) => teams[b].total - teams[a].total);

        const container = document.getElementById('sv-quality-table-container');
        container.style.display = '';
        const tbody = document.getElementById('sv-quality-tbody');

        tbody.innerHTML = tids.map(tid => {
          const t = teams[tid];
          const cls = t.home_pct < 40 || t.home_pct > 60 ? 'style="color:#f44336"' : '';
          return `<tr>
            <td>${t.team_name}</td>
            <td>${t.team_abbrev}</td>
            <td>${t.total}</td>
            <td>${t.home}</td>
            <td>${t.away}</td>
            <td ${cls}>${t.home_pct}%</td>
          </tr>`;
        }).join('');
      })
      .catch(err => alert('Quality metrics error: ' + err.message));
  }

  function editGame(gameId, homeTeam, awayTeam, week, subweek) {
    const newHome = prompt('Home Team ID:', homeTeam);
    if (newHome === null) return;
    const newAway = prompt('Away Team ID:', awayTeam);
    if (newAway === null) return;
    const newWeek = prompt('Week:', week);
    if (newWeek === null) return;
    const newSub = prompt('Subweek (a/b/c/d):', subweek);
    if (newSub === null) return;

    fetch(`${ADMIN_BASE}/schedule/game/${gameId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        home_team: parseInt(newHome),
        away_team: parseInt(newAway),
        season_week: parseInt(newWeek),
        season_subweek: newSub,
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        if (!data.ok) { alert('Update failed: ' + (data.message || data.error)); return; }
        alert('Game updated.');
        loadScheduleViewer();
      })
      .catch(err => alert('Edit error: ' + err.message));
  }

  function addViewerSeries() {
    const year = document.getElementById('sv-add-year').value;
    const level = document.getElementById('sv-add-level').value;
    const home = document.getElementById('sv-add-home').value;
    const away = document.getElementById('sv-add-away').value;
    const week = document.getElementById('sv-add-week').value;
    const games = document.getElementById('sv-add-games').value;

    if (!home || !away) { alert('Home and Away team IDs are required.'); return; }

    const resultBox = document.getElementById('sv-add-result');

    fetch(`${ADMIN_BASE}/schedule/add-series`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        league_year: parseInt(year),
        league_level: parseInt(level),
        home_team_id: parseInt(home),
        away_team_id: parseInt(away),
        week: parseInt(week),
        games: parseInt(games),
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        resultBox.style.display = 'block';
        if (!data.ok) {
          resultBox.textContent = 'Failed: ' + (data.message || data.error);
          resultBox.style.color = '#f44336';
          return;
        }
        resultBox.textContent = `Added ${data.games_added}-game series in week ${data.week}`;
        resultBox.style.color = '#4caf50';
        loadScheduleViewer();
      })
      .catch(err => {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Error: ' + err.message;
        resultBox.style.color = '#f44336';
      });
  }

  function swapOocOpponents() {
    const teamA = document.getElementById('sv-swap-team-a').value;
    const teamB = document.getElementById('sv-swap-team-b').value;
    const week = document.getElementById('sv-swap-week').value;
    const subweek = document.getElementById('sv-swap-subweek').value;

    if (!teamA || !teamB) { alert('Both Team A and Team B IDs are required.'); return; }
    if (!week) { alert('Week is required.'); return; }

    const resultBox = document.getElementById('sv-swap-result');

    fetch(`${ADMIN_BASE}/schedule/swap-ooc`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        team_a_id: parseInt(teamA),
        team_b_id: parseInt(teamB),
        season_week: parseInt(week),
        season_subweek: subweek,
      }),
    })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw new Error(r.status + ': ' + t.slice(0, 300)); });
        return r.json();
      })
      .then(data => {
        resultBox.style.display = 'block';
        if (!data.ok) {
          resultBox.textContent = 'Failed: ' + (data.message || data.error);
          resultBox.style.color = '#f44336';
          return;
        }
        if (!data.swapped) {
          resultBox.textContent = data.message || 'No swap needed.';
          resultBox.style.color = '#ff9800';
          return;
        }
        const g1 = data.game_1;
        const g2 = data.game_2;
        resultBox.textContent =
          `Swapped! Game ${g1.game_id}: ${g1.away} @ ${g1.home} | Game ${g2.game_id}: ${g2.away} @ ${g2.home}`;
        resultBox.style.color = '#4caf50';
        loadScheduleViewer();
      })
      .catch(err => {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Error: ' + err.message;
        resultBox.style.color = '#f44336';
      });
  }

  // ---------------------------------------------------------------------------
  // Analytics
  // ---------------------------------------------------------------------------

  let analyticsScatterChart = null;
  let warPage = 1;

  function loadAnalyticsLeagueYears(section) {
    // Map section to its dropdown id prefix
    const prefixMap = {
      'analytics-batting': 'an-bat',
      'analytics-pitching': 'an-pit',
      'analytics-defense': 'an-def',
      'analytics-war': 'an-war',
      'analytics-regression': 'an-reg',
      'analytics-sensitivity': 'an-sens',
      'analytics-xstats': 'an-xs',
      'analytics-interactions': 'an-int',
      'analytics-dashboard': 'an-dash',
      'analytics-archetypes': 'an-arch',
      'analytics-pitchtypes': 'an-pt',
      'analytics-defpos': 'an-dp',
      'analytics-contact': 'an-ct',
      'analytics-hr-depth': 'an-hrd',
    };
    const prefix = prefixMap[section];
    if (!prefix) return;
    const sel = document.getElementById(`${prefix}-lyid`);
    if (!sel || sel.options.length > 1) return; // already loaded
    fetch(`${ADMIN_BASE}/analytics/league-years`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        sel.innerHTML = '';
        data.league_years.forEach(ly => {
          const opt = document.createElement('option');
          opt.value = ly.id;
          opt.textContent = ly.league_year;
          sel.appendChild(opt);
        });
        // Populate stat/attr dropdowns for sections that have them
        const needsStatDropdown = ['an-reg', 'an-sens', 'an-dash', 'an-int'];
        const needsAttrDropdown = ['an-sens', 'an-int'];
        if (needsStatDropdown.includes(prefix)) populateStatDropdown(prefix);
        if (needsAttrDropdown.includes(prefix)) populateAttrDropdown(prefix);
      })
      .catch(() => {});
  }

  function correlationColor(r) {
    const abs = Math.min(Math.abs(r), 1);
    const intensity = Math.round(abs * 200);
    if (r > 0) return `rgb(${255 - intensity}, 255, ${255 - intensity})`;
    if (r < 0) return `rgb(255, ${255 - intensity}, ${255 - intensity})`;
    return '#ffffff';
  }

  function showAnalyticsView(prefix, view) {
    document.getElementById(`an-${prefix}-heatmap-card`).style.display = view === 'heatmap' ? '' : 'none';
    document.getElementById(`an-${prefix}-scatter-card`).style.display = view === 'scatter' ? '' : 'none';
  }

  function renderCorrelationHeatmap(prefix, data, type) {
    const container = document.getElementById(`an-${prefix}-heatmap`);
    const nSpan = document.getElementById(`an-${prefix}-n`);
    nSpan.textContent = `(n=${data.n})`;

    const attrs = data.attribute_labels || data.attributes;
    const stats = data.stat_labels || data.stats;
    const matrix = data.r_matrix;

    let html = '<table class="data-table" style="font-size: 12px;">';
    html += '<thead><tr><th></th>';
    stats.forEach(s => { html += `<th style="text-align: center; min-width: 55px;">${s}</th>`; });
    html += '</tr></thead><tbody>';

    matrix.forEach((row, ai) => {
      html += `<tr><td style="font-weight: 600; white-space: nowrap;">${attrs[ai]}</td>`;
      row.forEach((r, si) => {
        const bg = correlationColor(r);
        const textColor = Math.abs(r) > 0.6 ? '#000' : '#333';
        html += `<td style="text-align: center; background: ${bg}; color: ${textColor}; cursor: pointer; padding: 6px 4px;"
                     onclick="App.drillCorrelation('${type}', '${data.attributes[ai]}', '${data.stats[si]}')"
                     title="${data.attributes[ai]} vs ${data.stats[si]}">${r.toFixed(2)}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;

    document.getElementById(`an-${prefix}-heatmap-card`).style.display = '';
    document.getElementById(`an-${prefix}-scatter-card`).style.display = 'none';
  }

  function renderCorrelationScatter(prefix, data) {
    const canvas = document.getElementById(`an-${prefix}-scatter-canvas`);
    const titleEl = document.getElementById(`an-${prefix}-scatter-title`);
    const infoEl = document.getElementById(`an-${prefix}-scatter-info`);
    const detailEl = document.getElementById(`an-${prefix}-scatter-detail`);

    titleEl.textContent = `${data.attr_label} vs ${data.stat_label}`;
    infoEl.textContent = `R = ${data.r.toFixed(4)} | y = ${data.slope.toFixed(4)}x + ${data.intercept.toFixed(4)} | n = ${data.n}`;
    if (detailEl) { detailEl.style.display = 'none'; detailEl.innerHTML = ''; }

    if (analyticsScatterChart) {
      analyticsScatterChart.destroy();
      analyticsScatterChart = null;
    }

    // Build regression line endpoints
    const xs = data.points.map(p => p.x);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const regLine = [
      { x: minX, y: data.slope * minX + data.intercept },
      { x: maxX, y: data.slope * maxX + data.intercept },
    ];

    analyticsScatterChart = new Chart(canvas, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'Players',
            data: data.points.map(p => ({ x: p.x, y: p.y })),
            backgroundColor: 'rgba(54, 162, 235, 0.5)',
            pointRadius: 4,
            pointHoverRadius: 7,
          },
          {
            label: 'Regression',
            data: regLine,
            type: 'line',
            borderColor: 'rgba(255, 99, 132, 0.8)',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: function(evt, elements) {
          if (!detailEl) return;
          if (!elements.length || elements[0].datasetIndex !== 0) {
            detailEl.style.display = 'none';
            return;
          }
          const idx = elements[0].index;
          const pt = data.points[idx];
          renderPlayerDetail(detailEl, pt, data.attr_label, data.stat_label);
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: function(ctx) {
                if (ctx.datasetIndex === 0) {
                  const pt = data.points[ctx.dataIndex];
                  return `${pt.name}: (${pt.x.toFixed(1)}, ${pt.y.toFixed(4)})`;
                }
                return '';
              }
            }
          },
          legend: { display: false },
        },
        scales: {
          x: { title: { display: true, text: data.attr_label } },
          y: { title: { display: true, text: data.stat_label } },
        },
      },
    });

    showAnalyticsView(prefix, 'scatter');
  }

  function renderPlayerDetail(container, pt, attrLabel, statLabel) {
    const statLabels = Object.assign({},
      ...BATTING_STATS.map(s => ({ [s.value]: s.label })),
      ...PITCHING_STATS.map(s => ({ [s.value]: s.label })),
    );
    const attrLabelsMap = Object.assign({},
      ...BATTING_ATTRS.map(a => ({ [a.value]: a.label })),
      ...PITCHING_ATTRS.map(a => ({ [a.value]: a.label })),
    );

    let html = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
      <h4 style="margin:0;">${pt.name}</h4>
      <span class="text-muted" style="font-size:13px;">Player ID: ${pt.player_id}</span>
    </div>`;

    // Stats table
    if (pt.all_stats && Object.keys(pt.all_stats).length) {
      html += '<div style="margin-bottom:10px;"><strong>Stats</strong></div>';
      html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
      for (const [key, val] of Object.entries(pt.all_stats)) {
        const label = statLabels[key] || key;
        const fmt = (key === 'AB_per_HR') ? val.toFixed(1) : val.toFixed(3);
        html += `<div class="stat-card" style="min-width:70px;"><div class="stat-label">${label}</div><div class="stat-value">${fmt}</div></div>`;
      }
      html += '</div>';
    }

    // Attributes table
    if (pt.all_attrs && Object.keys(pt.all_attrs).length) {
      html += '<div style="margin-top:10px;margin-bottom:10px;"><strong>Attributes</strong></div>';
      html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
      for (const [key, val] of Object.entries(pt.all_attrs)) {
        const label = attrLabelsMap[key] || key;
        html += `<div class="stat-card" style="min-width:70px;"><div class="stat-label">${label}</div><div class="stat-value">${val.toFixed(0)}</div></div>`;
      }
      html += '</div>';
    }

    container.innerHTML = html;
    container.style.display = '';
  }

  function drillCorrelation(type, attr, stat) {
    const prefixMap = { batting: 'bat', pitching: 'pit', defense: 'def' };
    const prefix = prefixMap[type];
    const endpointMap = {
      batting: 'batting-correlations',
      pitching: 'pitching-correlations',
      defense: 'defensive-analysis',
    };

    const lyid = document.getElementById(`an-${prefix}-lyid`).value;
    const level = document.getElementById(`an-${prefix}-level`).value;

    let minParam = '';
    if (type === 'batting') minParam = `&min_ab=${document.getElementById('an-bat-min-ab').value}`;
    else if (type === 'pitching') minParam = `&min_ipo=${document.getElementById('an-pit-min-ipo').value}`;
    else if (type === 'defense') {
      minParam = `&min_innings=${document.getElementById('an-def-min-inn').value}`;
      const pos = document.getElementById('an-def-pos').value;
      if (pos) minParam += `&position_code=${pos}`;
    }

    const url = `${ADMIN_BASE}/analytics/${endpointMap[type]}?league_year_id=${lyid}&league_level=${level}${minParam}&drill_attr=${attr}&drill_stat=${stat}`;
    document.getElementById(`an-${prefix}-status`).textContent = 'Loading scatter data...';

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        document.getElementById(`an-${prefix}-status`).textContent = '';
        if (!data.ok) {
          document.getElementById(`an-${prefix}-status`).textContent = 'Error: ' + (data.message || data.error);
          return;
        }
        renderCorrelationScatter(prefix, data);
      })
      .catch(err => {
        document.getElementById(`an-${prefix}-status`).textContent = 'Error: ' + err.message;
      });
  }

  function loadBattingCorrelations() {
    const lyid = document.getElementById('an-bat-lyid').value;
    const level = document.getElementById('an-bat-level').value;
    const minAb = document.getElementById('an-bat-min-ab').value;
    const status = document.getElementById('an-bat-status');
    status.textContent = 'Loading...';

    fetch(`${ADMIN_BASE}/analytics/batting-correlations?league_year_id=${lyid}&league_level=${level}&min_ab=${minAb}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        status.textContent = '';
        if (!data.ok) { status.textContent = 'Error: ' + (data.message || data.error); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n}). Lower min AB.`; return; }
        renderCorrelationHeatmap('bat', data, 'batting');
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadPitchingCorrelations() {
    const lyid = document.getElementById('an-pit-lyid').value;
    const level = document.getElementById('an-pit-level').value;
    const minIpo = document.getElementById('an-pit-min-ipo').value;
    const status = document.getElementById('an-pit-status');
    status.textContent = 'Loading...';

    fetch(`${ADMIN_BASE}/analytics/pitching-correlations?league_year_id=${lyid}&league_level=${level}&min_ipo=${minIpo}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        status.textContent = '';
        if (!data.ok) { status.textContent = 'Error: ' + (data.message || data.error); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n}). Lower min IPO.`; return; }
        renderCorrelationHeatmap('pit', data, 'pitching');
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadDefensiveAnalysis() {
    const lyid = document.getElementById('an-def-lyid').value;
    const level = document.getElementById('an-def-level').value;
    const pos = document.getElementById('an-def-pos').value;
    const minInn = document.getElementById('an-def-min-inn').value;
    const status = document.getElementById('an-def-status');
    status.textContent = 'Loading...';

    let url = `${ADMIN_BASE}/analytics/defensive-analysis?league_year_id=${lyid}&league_level=${level}&min_innings=${minInn}`;
    if (pos) url += `&position_code=${pos}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        status.textContent = '';
        if (!data.ok) { status.textContent = 'Error: ' + (data.message || data.error); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n}). Lower min innings.`; return; }
        // Populate position dropdown if available
        if (data.positions) {
          const posSel = document.getElementById('an-def-pos');
          const current = posSel.value;
          posSel.innerHTML = '<option value="">All</option>';
          data.positions.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p.toUpperCase();
            posSel.appendChild(opt);
          });
          posSel.value = current;
        }
        renderCorrelationHeatmap('def', data, 'defense');
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadWarLeaderboard() {
    const lyid = document.getElementById('an-war-lyid').value;
    const level = document.getElementById('an-war-level').value;
    const minAb = document.getElementById('an-war-min-ab').value;
    const minIpo = document.getElementById('an-war-min-ipo').value;
    const repl = document.getElementById('an-war-repl').value;
    const wb = document.getElementById('an-war-wb').value;
    const wbr = document.getElementById('an-war-wbr').value;
    const wf = document.getElementById('an-war-wf').value;
    const wp = document.getElementById('an-war-wp').value;
    const status = document.getElementById('an-war-status');
    status.textContent = 'Loading...';

    const url = `${ADMIN_BASE}/analytics/war-leaderboard?league_year_id=${lyid}&league_level=${level}`
      + `&min_ab=${minAb}&min_ipo=${minIpo}&replacement_pct=${repl / 100}`
      + `&w_batting=${wb}&w_baserunning=${wbr}&w_fielding=${wf}&w_pitching=${wp}`
      + `&page=${warPage}&page_size=50`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        status.textContent = '';
        if (!data.ok) { status.textContent = 'Error: ' + (data.message || data.error); return; }
        renderWarTable(data);
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function renderWarTable(data) {
    // League averages
    const avgsDiv = document.getElementById('an-war-avgs');
    const la = data.league_averages;
    avgsDiv.innerHTML = `
      <div class="stat-card"><div class="stat-label">Lg wOBA</div><div class="stat-value">${la.woba.toFixed(3)}</div></div>
      <div class="stat-card"><div class="stat-label">Lg OPS</div><div class="stat-value">${la.ops.toFixed(3)}</div></div>
      <div class="stat-card"><div class="stat-label">Lg ERA</div><div class="stat-value">${la.era.toFixed(2)}</div></div>
      <div class="stat-card"><div class="stat-label">Lg FIP</div><div class="stat-value">${la.fip.toFixed(2)}</div></div>
      <div class="stat-card"><div class="stat-label">Repl wOBA</div><div class="stat-value">${data.repl_woba.toFixed(3)}</div></div>
      <div class="stat-card"><div class="stat-label">Repl FIP</div><div class="stat-value">${data.repl_fip.toFixed(2)}</div></div>
      <div class="stat-card"><div class="stat-label">R/PA</div><div class="stat-value">${la.r_pa.toFixed(4)}</div></div>
      <div class="stat-card"><div class="stat-label">cFIP</div><div class="stat-value">${la.fip_constant.toFixed(2)}</div></div>
    `;
    document.getElementById('an-war-avgs-card').style.display = '';

    // Table
    const tbody = document.getElementById('an-war-tbody');
    tbody.innerHTML = '';
    data.leaders.forEach(p => {
      const warColor = p.war > 0 ? '#4caf50' : (p.war < 0 ? '#f44336' : '#999');
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${p.rank}</td>
        <td>${p.name}</td>
        <td>${p.team}</td>
        <td>${p.position}</td>
        <td>${p.type}</td>
        <td style="font-weight: 700; color: ${warColor}">${p.war.toFixed(1)}</td>
        <td>${p.batting_runs.toFixed(1)}</td>
        <td>${p.br_runs.toFixed(1)}</td>
        <td>${p.fld_runs.toFixed(1)}</td>
        <td>${(p.pos_adj || 0).toFixed(1)}</td>
        <td>${p.pit_runs.toFixed(1)}</td>
        <td>${(p.woba || 0).toFixed(3)}</td>
        <td>${Math.round(p.wrc_plus || 0)}</td>
        <td>${p.fip != null ? p.fip.toFixed(2) : '—'}</td>
      `;
      tbody.appendChild(tr);
    });
    document.getElementById('an-war-table-card').style.display = '';

    // Pagination
    document.getElementById('an-war-page-info').textContent = `Page ${data.page} of ${data.pages} (${data.total} players)`;
    document.getElementById('btn-war-prev').disabled = data.page <= 1;
    document.getElementById('btn-war-next').disabled = data.page >= data.pages;
    warPage = data.page;
  }

  // --- Dropdown population helpers ---

  const BATTING_STATS = [
    { value: 'AVG', label: 'AVG' }, { value: 'ISO', label: 'ISO' },
    { value: 'BB_pct', label: 'BB%' }, { value: 'K_pct', label: 'K%' },
    { value: 'OBP', label: 'OBP' }, { value: 'SLG', label: 'SLG' },
    { value: 'OPS', label: 'OPS' }, { value: 'SB_pct', label: 'SB%' },
    { value: 'AB_per_HR', label: 'AB/HR' }, { value: 'BABIP', label: 'BABIP' },
    { value: 'XBH_pct', label: 'XBH%' }, { value: 'BB_K', label: 'BB/K' },
    { value: 'wOBA', label: 'wOBA' }, { value: 'RC', label: 'RC' },
    { value: 'SecA', label: 'SecA' }, { value: 'PSS', label: 'PSS' },
    { value: 'GB_pct', label: 'GB%' }, { value: 'FB_pct', label: 'FB%' },
    { value: 'PU_pct', label: 'PU%' }, { value: 'Barrel_pct', label: 'Barrel%' },
    { value: 'HardHit_pct', label: 'HardHit%' }, { value: 'Soft_pct', label: 'Soft%' },
    { value: 'Med_pct', label: 'Med%' }, { value: 'LD_pct', label: 'LD%' },
    { value: 'Contact_pct', label: 'Contact%' }, { value: 'GIDP_pct', label: 'GIDP%' },
    { value: 'HR_FB', label: 'HR/FB' },
  ];
  const PITCHING_STATS = [
    { value: 'ERA', label: 'ERA' }, { value: 'WHIP', label: 'WHIP' },
    { value: 'K_per_9', label: 'K/9' }, { value: 'BB_per_9', label: 'BB/9' },
    { value: 'HR_per_9', label: 'HR/9' }, { value: 'K_per_BB', label: 'K/BB' },
    { value: 'H_per_9', label: 'H/9' }, { value: 'IP_per_GS', label: 'IP/GS' },
    { value: 'W_pct', label: 'W%' }, { value: 'BABIP_against', label: 'BABIP Ag' },
    { value: 'K_pct_p', label: 'K%' }, { value: 'BB_pct_p', label: 'BB%' },
    { value: 'FIP', label: 'FIP' }, { value: 'xFIP', label: 'xFIP' },
    { value: 'K_BB_pct', label: 'K-BB%' }, { value: 'LOB_pct', label: 'LOB%' },
    { value: 'WP_per_9', label: 'WP/9' },
    { value: 'GB_pct', label: 'GB%' }, { value: 'FB_pct', label: 'FB%' },
    { value: 'Barrel_pct', label: 'Barrel%' }, { value: 'HardHit_pct', label: 'HardHit%' },
    { value: 'Soft_pct', label: 'Soft%' }, { value: 'LD_pct', label: 'LD%' },
    { value: 'HR_FB', label: 'HR/FB' },
    { value: 'IR_pct', label: 'IR%' }, { value: 'GIDP_rate', label: 'GIDP Rate' },
  ];
  const BATTING_ATTRS = [
    { value: 'contact_base', label: 'Contact' }, { value: 'power_base', label: 'Power' },
    { value: 'eye_base', label: 'Eye' }, { value: 'discipline_base', label: 'Discipline' },
    { value: 'speed_base', label: 'Speed' }, { value: 'baserunning_base', label: 'Baserunning' },
    { value: 'basereaction_base', label: 'Base Reaction' },
  ];
  const PITCHING_ATTRS = [
    { value: 'pendurance_base', label: 'Endurance' }, { value: 'pgencontrol_base', label: 'Gen Control' },
    { value: 'psequencing_base', label: 'Sequencing' }, { value: 'pthrowpower_base', label: 'Throw Power' },
    { value: 'pickoff_base', label: 'Pickoff' },
    { value: 'avg_consist', label: 'Avg Consistency' }, { value: 'avg_pacc', label: 'Avg Accuracy' },
    { value: 'avg_pbrk', label: 'Avg Break' }, { value: 'avg_pcntrl', label: 'Avg Control' },
  ];

  function populateStatDropdown(prefix) {
    const catEl = document.getElementById(`${prefix}-cat`);
    const statEl = document.getElementById(`${prefix}-stat`);
    if (!catEl || !statEl) return;
    const cat = catEl.value;
    const items = cat === 'pitching' ? PITCHING_STATS : BATTING_STATS;
    statEl.innerHTML = '';
    items.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.value;
      opt.textContent = s.label;
      statEl.appendChild(opt);
    });
  }

  function populateAttrDropdown(prefix) {
    const catEl = document.getElementById(`${prefix}-cat`);
    if (!catEl) return;
    const cat = catEl.value;
    const items = cat === 'pitching' ? PITCHING_ATTRS : BATTING_ATTRS;
    // Some pages have single attr dropdown, some have attr-a / attr-b
    const ids = [`${prefix}-attr`, `${prefix}-attr-a`, `${prefix}-attr-b`];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = '';
      items.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a.value;
        opt.textContent = a.label;
        el.appendChild(opt);
      });
    });
  }

  // --- Multi-Regression ---

  function loadMultiRegression() {
    const lyid = document.getElementById('an-reg-lyid').value;
    const level = document.getElementById('an-reg-level').value;
    const cat = document.getElementById('an-reg-cat').value;
    const stat = document.getElementById('an-reg-stat').value;
    const min = document.getElementById('an-reg-min').value;
    const status = document.getElementById('an-reg-status');
    if (!stat) { populateStatDropdown('an-reg'); status.textContent = 'Select a target stat'; return; }
    status.textContent = 'Loading...';
    document.getElementById('an-reg-results').style.display = 'none';
    document.getElementById('an-reg-performers').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, category: cat, target_stat: stat, min_threshold: min });
    fetch(`${ADMIN_BASE}/analytics/multi-regression?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `n=${data.n}`;
        document.getElementById('an-reg-r2').textContent = `(R² = ${data.r_squared.toFixed(4)})`;

        // Coefficient table
        let html = '<table class="data-table"><thead><tr><th>Attribute</th><th>Beta</th><th>Std Beta</th><th>Importance %</th></tr></thead><tbody>';
        data.coefficients.forEach(c => {
          const color = c.std_beta > 0 ? '#4caf50' : (c.std_beta < 0 ? '#f44336' : '#999');
          html += `<tr><td>${c.label}</td><td>${c.beta.toFixed(4)}</td><td style="color:${color};font-weight:600">${c.std_beta.toFixed(4)}</td><td>${c.pct_importance}%</td></tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('an-reg-coeff-table').innerHTML = html;
        document.getElementById('an-reg-results').style.display = '';

        // Over/underperformers
        const renderPerf = (arr) => {
          let t = '<table class="data-table"><thead><tr><th>Player</th><th>Actual</th><th>Predicted</th><th>Residual</th></tr></thead><tbody>';
          arr.forEach(p => {
            const rc = p.residual > 0 ? '#4caf50' : '#f44336';
            t += `<tr><td>${p.name}</td><td>${p.actual.toFixed(4)}</td><td>${p.predicted.toFixed(4)}</td><td style="color:${rc};font-weight:600">${p.residual > 0 ? '+' : ''}${p.residual.toFixed(4)}</td></tr>`;
          });
          return t + '</tbody></table>';
        };
        document.getElementById('an-reg-over').innerHTML = renderPerf(data.top_overperformers);
        document.getElementById('an-reg-under').innerHTML = renderPerf(data.top_underperformers);
        document.getElementById('an-reg-performers').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Sensitivity Curves ---

  let sensitivityChart = null;

  function loadSensitivity() {
    const lyid = document.getElementById('an-sens-lyid').value;
    const level = document.getElementById('an-sens-level').value;
    const cat = document.getElementById('an-sens-cat').value;
    const attr = document.getElementById('an-sens-attr').value;
    const stat = document.getElementById('an-sens-stat').value;
    const min = document.getElementById('an-sens-min').value;
    const status = document.getElementById('an-sens-status');
    if (!attr || !stat) { populateAttrDropdown('an-sens'); populateStatDropdown('an-sens'); status.textContent = 'Select attribute and stat'; return; }
    status.textContent = 'Loading...';
    document.getElementById('an-sens-chart-card').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, category: cat, target_stat: stat, attribute: attr, min_threshold: min });
    fetch(`${ADMIN_BASE}/analytics/sensitivity?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `n=${data.n}`;
        document.getElementById('an-sens-title').textContent = `${data.attr_label} → ${data.stat_label}`;

        // Flags
        const flagsDiv = document.getElementById('an-sens-flags');
        flagsDiv.innerHTML = data.diminishing_returns
          ? '<span style="background:#ff9800;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">Diminishing Returns Detected</span>'
          : '';

        // Chart
        const canvas = document.getElementById('an-sens-chart');
        if (sensitivityChart) { sensitivityChart.destroy(); sensitivityChart = null; }
        const labels = data.buckets.map(b => b.label);
        const means = data.buckets.map(b => b.mean);
        const counts = data.buckets.map(b => b.count);

        sensitivityChart = new Chart(canvas, {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: data.stat_label + ' (mean)',
                data: means,
                backgroundColor: 'rgba(54, 162, 235, 0.7)',
                yAxisID: 'y',
              },
              {
                label: 'Player Count',
                data: counts,
                type: 'line',
                borderColor: '#ff9800',
                backgroundColor: 'rgba(255, 152, 0, 0.1)',
                yAxisID: 'y1',
                pointRadius: 3,
              },
            ],
          },
          options: {
            responsive: true,
            scales: {
              y: { position: 'left', title: { display: true, text: data.stat_label } },
              y1: { position: 'right', title: { display: true, text: 'Count' }, grid: { drawOnChartArea: false } },
            },
          },
        });
        document.getElementById('an-sens-chart-card').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- xStats / Residuals ---

  function loadXStats() {
    const lyid = document.getElementById('an-xs-lyid').value;
    const level = document.getElementById('an-xs-level').value;
    const cat = document.getElementById('an-xs-cat').value;
    const min = document.getElementById('an-xs-min').value;
    const status = document.getElementById('an-xs-status');
    status.textContent = 'Loading...';
    document.getElementById('an-xs-models').style.display = 'none';
    document.getElementById('an-xs-players').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, category: cat, min_threshold: min });
    fetch(`${ADMIN_BASE}/analytics/xstats?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `n=${data.n}`;

        // Model fit table
        let mhtml = '<table class="data-table"><thead><tr><th>Stat</th><th>R²</th><th>Residual Std</th><th>Fit Quality</th></tr></thead><tbody>';
        for (const [stat, model] of Object.entries(data.stat_models)) {
          const label = data.stat_labels[stat] || stat;
          const r2 = model.r_squared;
          const quality = r2 >= 0.5 ? 'Good' : (r2 >= 0.2 ? 'Moderate' : 'Weak');
          const qColor = r2 >= 0.5 ? '#4caf50' : (r2 >= 0.2 ? '#ff9800' : '#f44336');
          mhtml += `<tr><td>${label}</td><td>${r2.toFixed(4)}</td><td>${model.resid_std.toFixed(4)}</td><td style="color:${qColor};font-weight:600">${quality}</td></tr>`;
        }
        mhtml += '</tbody></table>';
        document.getElementById('an-xs-models-table').innerHTML = mhtml;
        document.getElementById('an-xs-models').style.display = '';

        // Top unusual players
        const stats = Object.keys(data.stat_models);
        let phtml = '<table class="data-table" style="font-size:12px;"><thead><tr><th>Player</th><th>Total |Resid|</th>';
        stats.forEach(s => { phtml += `<th>${data.stat_labels[s] || s}</th>`; });
        phtml += '</tr></thead><tbody>';
        data.players.slice(0, 30).forEach(p => {
          phtml += `<tr><td>${p.name}</td><td style="font-weight:600">${p.total_abs_residual.toFixed(3)}</td>`;
          stats.forEach(s => {
            const st = p.stats[s];
            if (!st) { phtml += '<td>-</td>'; return; }
            const rc = st.residual > 0 ? '#4caf50' : '#f44336';
            phtml += `<td title="Actual: ${st.actual.toFixed(3)}, xStat: ${st.expected.toFixed(3)}"><span style="color:${rc}">${st.residual > 0 ? '+' : ''}${st.residual.toFixed(3)}</span></td>`;
          });
          phtml += '</tr>';
        });
        phtml += '</tbody></table>';
        document.getElementById('an-xs-players-table').innerHTML = phtml;
        document.getElementById('an-xs-players').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Interaction Effects ---

  function loadInteractions() {
    const lyid = document.getElementById('an-int-lyid').value;
    const level = document.getElementById('an-int-level').value;
    const cat = document.getElementById('an-int-cat').value;
    const attrA = document.getElementById('an-int-attr-a').value;
    const attrB = document.getElementById('an-int-attr-b').value;
    const stat = document.getElementById('an-int-stat').value;
    const min = document.getElementById('an-int-min').value;
    const status = document.getElementById('an-int-status');
    if (!attrA || !attrB || !stat) { populateAttrDropdown('an-int'); populateStatDropdown('an-int'); status.textContent = 'Select attributes and stat'; return; }
    status.textContent = 'Loading...';
    document.getElementById('an-int-results').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, category: cat, target_stat: stat, attr_a: attrA, attr_b: attrB, min_threshold: min });
    fetch(`${ADMIN_BASE}/analytics/interactions?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `n=${data.n}`;
        document.getElementById('an-int-title').textContent = `${data.attr_a_label} × ${data.attr_b_label} → ${data.stat_label}`;

        // R² comparison
        const gainColor = data.r2_gain > 0.01 ? '#4caf50' : (data.r2_gain > 0 ? '#ff9800' : '#999');
        const significant = data.r2_gain > 0.01;
        document.getElementById('an-int-r2-info').innerHTML =
          `<div style="display:flex;gap:24px;flex-wrap:wrap;">` +
          `<div><strong>R² without interaction:</strong> ${data.r2_without_interaction.toFixed(4)}</div>` +
          `<div><strong>R² with interaction:</strong> ${data.r2_with_interaction.toFixed(4)}</div>` +
          `<div><strong>R² gain:</strong> <span style="color:${gainColor};font-weight:700">${data.r2_gain > 0 ? '+' : ''}${data.r2_gain.toFixed(4)}</span></div>` +
          `<div>${significant ? '<span style="background:#4caf50;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">Significant Interaction</span>' : '<span style="background:#999;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">No Significant Interaction</span>'}</div>` +
          `</div>`;

        // 2D Grid
        let ghtml = `<table class="data-table" style="font-size:12px;"><thead><tr><th>${data.attr_a_label} \\ ${data.attr_b_label}</th>`;
        data.b_labels.forEach(bl => { ghtml += `<th>${bl}</th>`; });
        ghtml += '</tr></thead><tbody>';
        data.grid.forEach((row, ri) => {
          ghtml += `<tr><td style="font-weight:600">${data.a_labels[ri]}</td>`;
          row.forEach(cell => {
            if (cell.mean === null) {
              ghtml += '<td style="background:#eee;color:#999">-</td>';
            } else {
              const bg = correlationColor(cell.mean * 2 - 0.5); // rough color scale
              ghtml += `<td style="background:${bg}" title="n=${cell.n}">${cell.mean.toFixed(3)}</td>`;
            }
          });
          ghtml += '</tr>';
        });
        ghtml += '</tbody></table>';
        document.getElementById('an-int-grid').innerHTML = ghtml;
        document.getElementById('an-int-results').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Stat Tuning Dashboard ---

  let dashHistChart = null;

  function loadStatDashboard() {
    const lyid = document.getElementById('an-dash-lyid').value;
    const level = document.getElementById('an-dash-level').value;
    const cat = document.getElementById('an-dash-cat').value;
    const stat = document.getElementById('an-dash-stat').value;
    const min = document.getElementById('an-dash-min').value;
    const status = document.getElementById('an-dash-status');
    if (!stat) { populateStatDropdown('an-dash'); status.textContent = 'Select a stat'; return; }
    status.textContent = 'Loading...';
    ['an-dash-benchmark', 'an-dash-dist', 'an-dash-attrs', 'an-dash-statcorr'].forEach(id => {
      document.getElementById(id).style.display = 'none';
    });

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, category: cat, target_stat: stat, min_threshold: min });
    fetch(`${ADMIN_BASE}/analytics/stat-dashboard?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `${data.stat_label} — n=${data.n}`;

        // Benchmark
        const bench = data.benchmark;
        const benchDiv = document.getElementById('an-dash-bench-content');
        if (bench) {
          const statusColor = bench.status === 'ok' ? '#4caf50' : (bench.status === 'warning' ? '#ff9800' : '#f44336');
          benchDiv.innerHTML = `
            <div style="display:flex;gap:16px;flex-wrap:wrap;">
              <div class="stat-card"><div class="stat-label">MLB Mean</div><div class="stat-value">${bench.mlb_mean.toFixed(3)}</div></div>
              <div class="stat-card"><div class="stat-label">Sim Mean</div><div class="stat-value">${bench.sim_mean.toFixed(3)}</div></div>
              <div class="stat-card"><div class="stat-label">MLB Std</div><div class="stat-value">${bench.mlb_std.toFixed(3)}</div></div>
              <div class="stat-card"><div class="stat-label">Sim Std</div><div class="stat-value">${data.distribution.std.toFixed(3)}</div></div>
              <div class="stat-card"><div class="stat-label">Z-Deviation</div><div class="stat-value" style="color:${statusColor}">${bench.z_deviation.toFixed(2)}</div></div>
              <div class="stat-card"><div class="stat-label">Status</div><div class="stat-value" style="color:${statusColor};text-transform:uppercase">${bench.status}</div></div>
            </div>`;
          document.getElementById('an-dash-benchmark').style.display = '';
        } else {
          benchDiv.innerHTML = '<p class="text-muted">No MLB benchmark available for this stat.</p>';
          document.getElementById('an-dash-benchmark').style.display = '';
        }

        // Distribution stats
        const d = data.distribution;
        document.getElementById('an-dash-dist-stats').innerHTML = `
          <div style="display:flex;gap:16px;flex-wrap:wrap;">
            <div class="stat-card"><div class="stat-label">Mean</div><div class="stat-value">${d.mean.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">Std</div><div class="stat-value">${d.std.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">Min</div><div class="stat-value">${d.min.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">P25</div><div class="stat-value">${d.p25.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">P50</div><div class="stat-value">${d.p50.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">P75</div><div class="stat-value">${d.p75.toFixed(4)}</div></div>
            <div class="stat-card"><div class="stat-label">Max</div><div class="stat-value">${d.max.toFixed(4)}</div></div>
          </div>`;

        // Histogram
        const canvas = document.getElementById('an-dash-hist-canvas');
        if (dashHistChart) { dashHistChart.destroy(); dashHistChart = null; }
        const histLabels = data.histogram.map(h => h.lo.toFixed(3));
        const histCounts = data.histogram.map(h => h.count);
        dashHistChart = new Chart(canvas, {
          type: 'bar',
          data: {
            labels: histLabels,
            datasets: [{
              label: data.stat_label + ' Distribution',
              data: histCounts,
              backgroundColor: 'rgba(54, 162, 235, 0.7)',
            }],
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
              x: { title: { display: true, text: data.stat_label } },
              y: { title: { display: true, text: 'Count' } },
            },
          },
        });
        document.getElementById('an-dash-dist').style.display = '';

        // Attribute rankings
        document.getElementById('an-dash-r2').textContent = `(Model R² = ${data.r_squared.toFixed(4)})`;
        let ahtml = '<table class="data-table"><thead><tr><th>Attribute</th><th>R</th><th>p-value</th><th>95% CI</th><th>Std Beta</th><th>Sig?</th></tr></thead><tbody>';
        data.attr_rankings.forEach(a => {
          const rColor = a.r > 0 ? '#4caf50' : (a.r < 0 ? '#f44336' : '#999');
          const sigIcon = a.significant ? '&#10004;' : '';
          ahtml += `<tr><td>${a.label}</td><td style="color:${rColor};font-weight:600">${a.r.toFixed(4)}</td>` +
            `<td>${a.p_value.toFixed(4)}</td><td>[${a.ci_lo.toFixed(3)}, ${a.ci_hi.toFixed(3)}]</td>` +
            `<td>${a.std_beta.toFixed(4)}</td><td style="color:#4caf50">${sigIcon}</td></tr>`;
        });
        ahtml += '</tbody></table>';
        document.getElementById('an-dash-attr-table').innerHTML = ahtml;
        document.getElementById('an-dash-attrs').style.display = '';

        // Stat-vs-stat correlations
        let shtml = '<table class="data-table"><thead><tr><th>Stat</th><th>R</th></tr></thead><tbody>';
        data.stat_correlations.forEach(s => {
          const rc = s.r > 0 ? '#4caf50' : (s.r < 0 ? '#f44336' : '#999');
          shtml += `<tr><td>${s.label}</td><td style="color:${rc};font-weight:600">${s.r.toFixed(4)}</td></tr>`;
        });
        shtml += '</tbody></table>';
        document.getElementById('an-dash-statcorr-table').innerHTML = shtml;
        document.getElementById('an-dash-statcorr').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Archetype Validation ---

  function loadArchetypes() {
    const lyid = document.getElementById('an-arch-lyid').value;
    const level = document.getElementById('an-arch-level').value;
    const min = document.getElementById('an-arch-min').value;
    const status = document.getElementById('an-arch-status');
    status.textContent = 'Loading...';
    document.getElementById('an-arch-results').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, min_ab: min });
    fetch(`${ADMIN_BASE}/analytics/archetypes?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        if (data.error === 'not_enough_data') { status.textContent = `Not enough data (n=${data.n})`; return; }
        status.textContent = `n=${data.n}`;

        const statKeys = Object.keys(data.stat_labels);
        let html = '<table class="data-table" style="font-size:12px;"><thead><tr><th>Archetype</th><th>Count</th>';
        statKeys.forEach(s => { html += `<th>${data.stat_labels[s]}</th>`; });
        html += '</tr></thead><tbody>';

        // League average row
        html += '<tr style="background:#f0f0f0;font-weight:600"><td>League Average</td><td>-</td>';
        statKeys.forEach(s => { html += `<td>${(data.league_average[s] || 0).toFixed(3)}</td>`; });
        html += '</tr>';

        for (const [name, arch] of Object.entries(data.archetypes)) {
          html += `<tr><td style="font-weight:600">${name}</td><td>${arch.count}</td>`;
          statKeys.forEach(s => {
            const val = arch.avg_stats[s];
            if (val === undefined) { html += '<td>-</td>'; return; }
            const lgVal = data.league_average[s] || 0;
            const diff = val - lgVal;
            const color = diff > 0 ? '#4caf50' : (diff < 0 ? '#f44336' : '#999');
            html += `<td style="color:${color}">${val.toFixed(3)}</td>`;
          });
          html += '</tr>';
        }
        html += '</tbody></table>';
        document.getElementById('an-arch-table').innerHTML = html;
        document.getElementById('an-arch-results').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Pitch Type Analysis ---

  function loadPitchTypes() {
    const lyid = document.getElementById('an-pt-lyid').value;
    const level = document.getElementById('an-pt-level').value;
    const min = document.getElementById('an-pt-min').value;
    const status = document.getElementById('an-pt-status');
    status.textContent = 'Loading...';
    document.getElementById('an-pt-types').style.display = 'none';
    document.getElementById('an-pt-rep').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, min_ipo: min });
    fetch(`${ADMIN_BASE}/analytics/pitch-types?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        status.textContent = `n=${data.n}`;

        const statKeys = Object.keys(data.stat_labels);

        // Pitch type table
        let html = '<table class="data-table" style="font-size:12px;"><thead><tr><th>Primary Pitch</th><th>Count</th><th>Avg Repertoire</th>';
        statKeys.forEach(s => { html += `<th>${data.stat_labels[s]}</th>`; });
        html += '</tr></thead><tbody>';
        for (const [ptype, info] of Object.entries(data.pitch_types).sort((a, b) => b[1].count - a[1].count)) {
          html += `<tr><td style="font-weight:600">${ptype}</td><td>${info.count}</td><td>${info.avg_repertoire_size}</td>`;
          statKeys.forEach(s => {
            html += `<td>${(info.avg_stats[s] || 0).toFixed(3)}</td>`;
          });
          html += '</tr>';
        }
        html += '</tbody></table>';
        document.getElementById('an-pt-types-table').innerHTML = html;
        document.getElementById('an-pt-types').style.display = '';

        // Repertoire analysis
        let rhtml = '<table class="data-table" style="font-size:12px;"><thead><tr><th>Pitches</th><th>Count</th>';
        statKeys.forEach(s => { rhtml += `<th>${data.stat_labels[s]}</th>`; });
        rhtml += '</tr></thead><tbody>';
        for (const [size, info] of Object.entries(data.repertoire_analysis)) {
          rhtml += `<tr><td style="font-weight:600">${size}</td><td>${info.count}</td>`;
          statKeys.forEach(s => {
            rhtml += `<td>${(info.avg_stats[s] || 0).toFixed(3)}</td>`;
          });
          rhtml += '</tr>';
        }
        rhtml += '</tbody></table>';
        document.getElementById('an-pt-rep-table').innerHTML = rhtml;
        document.getElementById('an-pt-rep').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Defensive Position Importance ---

  function loadDefensivePositions() {
    const lyid = document.getElementById('an-dp-lyid').value;
    const level = document.getElementById('an-dp-level').value;
    const min = document.getElementById('an-dp-min').value;
    const status = document.getElementById('an-dp-status');
    status.textContent = 'Loading...';
    document.getElementById('an-dp-results').style.display = 'none';

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, min_innings: min });
    fetch(`${ADMIN_BASE}/analytics/defensive-positions?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        status.textContent = `n=${data.n}`;

        const tablesDiv = document.getElementById('an-dp-tables');
        let html = '';
        for (const [pos, info] of Object.entries(data.positions).sort((a, b) => a[0].localeCompare(b[0]))) {
          html += `<h4 style="margin-top:16px;">${pos} <span class="text-muted" style="font-size:13px">(n=${info.count}, Avg Fld%=${info.avg_fld_pct.toFixed(3)}, Avg E/Inn=${info.avg_e_per_inn.toFixed(4)})</span></h4>`;
          html += '<table class="data-table" style="font-size:12px;"><thead><tr><th>Attribute</th><th>R vs Fld%</th><th>R vs E/Inn</th><th>p-value</th><th>Sig?</th></tr></thead><tbody>';
          info.attr_importance.forEach(a => {
            const fldColor = a.r_vs_fielding_pct > 0 ? '#4caf50' : (a.r_vs_fielding_pct < 0 ? '#f44336' : '#999');
            const errColor = a.r_vs_error_rate < 0 ? '#4caf50' : (a.r_vs_error_rate > 0 ? '#f44336' : '#999');
            const sigIcon = a.significant ? '&#10004;' : '';
            html += `<tr><td>${a.label}</td><td style="color:${fldColor};font-weight:600">${a.r_vs_fielding_pct.toFixed(4)}</td>` +
              `<td style="color:${errColor};font-weight:600">${a.r_vs_error_rate.toFixed(4)}</td>` +
              `<td>${a.p_value.toFixed(4)}</td><td style="color:#4caf50">${sigIcon}</td></tr>`;
          });
          html += '</tbody></table>';
        }
        tablesDiv.innerHTML = html;
        document.getElementById('an-dp-results').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // --- Contact Type Breakdown ---

  let _contactData = null;
  let contactOddsChart = null;
  let contactOutcomeChart = null;
  let contactExpectedChart = null;
  let contactPowerTierChart = null;
  let contactContactTierChart = null;

  function loadContactBreakdown() {
    const lyid = document.getElementById('an-ct-lyid').value;
    const level = document.getElementById('an-ct-level').value;
    const minAb = document.getElementById('an-ct-min-ab').value;
    const status = document.getElementById('an-ct-status');
    status.textContent = 'Loading...';

    ['an-ct-odds-card', 'an-ct-dist-card', 'an-ct-expected-card', 'an-ct-outcome-card', 'an-ct-tiers-card', 'an-ct-contact-tiers-card', 'an-ct-bytype-card', 'an-ct-leaders-card']
      .forEach(id => document.getElementById(id).style.display = 'none');

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, min_ab: minAb });
    fetch(`${ADMIN_BASE}/analytics/contact-breakdown?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        status.textContent = `${data.n} qualifying batters`;
        _contactData = data;

        renderContactOdds(data.config);
        renderDistanceWeights(data.config);
        renderExpectedVsActual(data.config, data.outcome_summary);
        renderOutcomeSummary(data.outcome_summary, data.n);
        renderPowerTiers(data.tiers);
        renderContactTiers(data.contact_tiers);
        renderPerContactType(data.per_contact_type || []);
        renderContactLeaders('iso');

        ['an-ct-odds-card', 'an-ct-dist-card', 'an-ct-expected-card', 'an-ct-outcome-card', 'an-ct-tiers-card', 'an-ct-contact-tiers-card', 'an-ct-bytype-card', 'an-ct-leaders-card']
          .forEach(id => document.getElementById(id).style.display = '');
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function renderContactOdds(config) {
    const types = Object.keys(config.contact_odds);
    const odds = config.contact_odds;
    const pcts = config.contact_odds_pct;

    // Table
    const header = document.getElementById('an-ct-odds-header');
    header.innerHTML = '<th>Metric</th>' + types.map(t => `<th>${t}</th>`).join('');
    const tbody = document.getElementById('an-ct-odds-tbody');
    tbody.innerHTML = `
      <tr><td>Raw Odds</td>${types.map(t => `<td>${odds[t]}</td>`).join('')}</tr>
      <tr><td>Share %</td>${types.map(t => `<td>${pcts[t]}%</td>`).join('')}</tr>
    `;

    // Chart
    const ctx = document.getElementById('an-ct-odds-chart').getContext('2d');
    if (contactOddsChart) contactOddsChart.destroy();
    const colors = ['#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#6b7280'];
    contactOddsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: types,
        datasets: [{
          label: 'Contact Odds Share %',
          data: types.map(t => pcts[t]),
          backgroundColor: types.map((_, i) => colors[i % colors.length] + '88'),
          borderColor: types.map((_, i) => colors[i % colors.length]),
          borderWidth: 1,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: '% of contacts', color: '#999' },
               ticks: { color: '#999' }, grid: { color: '#333' } },
          x: { ticks: { color: '#999' }, grid: { color: '#333' } }
        }
      }
    });
  }

  function renderDistanceWeights(config) {
    const dw = config.distance_weights;
    const contactTypes = Object.keys(dw);
    if (!contactTypes.length) return;

    const zones = [...new Set(contactTypes.flatMap(ct => Object.keys(dw[ct])))];
    const header = document.getElementById('an-ct-dist-header');
    header.innerHTML = '<th>Contact Type</th>' + zones.map(z => `<th>${z}</th>`).join('');

    const tbody = document.getElementById('an-ct-dist-tbody');
    tbody.innerHTML = contactTypes.map(ct => {
      const cells = zones.map(z => {
        const val = dw[ct][z] || 0;
        const intensity = Math.min(val, 1);
        const bg = `rgba(59, 130, 246, ${intensity * 0.5})`;
        return `<td style="background:${bg}">${val}</td>`;
      }).join('');
      return `<tr><td style="font-weight:600">${ct}</td>${cells}</tr>`;
    }).join('');
  }

  function renderExpectedVsActual(config, os) {
    const expected = config.expected_outcomes || {};
    if (!Object.keys(expected).length || !os.total_ab) return;

    // Map fielding outcome names to actual stat fields
    const outcomeMap = [
      { key: 'single',  label: '1B%',  actualKey: '1B_pct' },
      { key: 'double',  label: '2B%',  actualKey: '2B_pct' },
      { key: 'triple',  label: '3B%',  actualKey: '3B_pct' },
      { key: 'homerun', label: 'HR%',  actualKey: 'HR_pct' },
      { key: 'inside_the_park_hr', label: 'ITPHR%', actualKey: 'ITPHR_pct' },
    ];
    // Filter to outcomes that exist in the config
    const items = outcomeMap.filter(o => expected[o.key] !== undefined);

    const labels = items.map(o => o.label);
    const expectedVals = items.map(o => expected[o.key]);
    const actualVals = items.map(o => os[o.actualKey] || 0);

    // Table
    const header = document.getElementById('an-ct-expected-header');
    header.innerHTML = '<th>Metric</th>' + labels.map(l => `<th>${l}</th>`).join('');
    const tbody = document.getElementById('an-ct-expected-tbody');
    tbody.innerHTML = `
      <tr><td style="font-weight:600">Expected (config)</td>${expectedVals.map(v => `<td>${v.toFixed(2)}%</td>`).join('')}</tr>
      <tr><td style="font-weight:600">Actual</td>${actualVals.map(v => `<td>${v.toFixed(2)}%</td>`).join('')}</tr>
      <tr><td style="font-weight:600">Delta</td>${items.map((o, i) => {
        const d = actualVals[i] - expectedVals[i];
        const color = d > 0 ? '#10b981' : d < 0 ? '#ef4444' : '#999';
        return `<td style="color:${color}">${d > 0 ? '+' : ''}${d.toFixed(2)}%</td>`;
      }).join('')}</tr>
    `;

    // Grouped bar chart
    const ctx = document.getElementById('an-ct-expected-chart').getContext('2d');
    if (contactExpectedChart) contactExpectedChart.destroy();
    contactExpectedChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Expected (config)',
            data: expectedVals,
            backgroundColor: 'rgba(59, 130, 246, 0.5)',
            borderColor: '#3b82f6',
            borderWidth: 1,
          },
          {
            label: 'Actual',
            data: actualVals,
            backgroundColor: 'rgba(16, 185, 129, 0.5)',
            borderColor: '#10b981',
            borderWidth: 1,
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#ccc' } } },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: '% of AB', color: '#999' },
               ticks: { color: '#999' }, grid: { color: '#333' } },
          x: { ticks: { color: '#999' }, grid: { color: '#333' } }
        }
      }
    });
  }

  function renderOutcomeSummary(os, n) {
    document.getElementById('an-ct-n').textContent = `(n=${n}, ${os.total_pa?.toLocaleString() || 0} PA)`;

    const statsDiv = document.getElementById('an-ct-outcome-stats');
    const statCards = [
      ['AVG', os.AVG?.toFixed(3)], ['OBP', os.OBP?.toFixed(3)],
      ['SLG', os.SLG?.toFixed(3)], ['OPS', os.OPS?.toFixed(3)],
      ['ISO', os.ISO?.toFixed(3)], ['BABIP', os.BABIP?.toFixed(3)],
      ['K%', os.K_pct?.toFixed(1) + '%'], ['BB%', os.BB_pct?.toFixed(1) + '%'],
    ];
    statsDiv.innerHTML = statCards.map(([label, val]) =>
      `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value">${val || '--'}</div></div>`
    ).join('');

    // Outcome distribution chart
    const ctx = document.getElementById('an-ct-outcome-chart').getContext('2d');
    if (contactOutcomeChart) contactOutcomeChart.destroy();

    const labels = ['1B%', '2B%', '3B%', 'HR%', 'ITPHR%', 'K%', 'BB%'];
    const values = [os['1B_pct'], os['2B_pct'], os['3B_pct'], os.HR_pct, os.ITPHR_pct || 0, os.K_pct, os.BB_pct];
    const barColors = ['#10b981', '#3b82f6', '#8b5cf6', '#ef4444', '#fb923c', '#f59e0b', '#06b6d4'];

    contactOutcomeChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Rate %',
          data: values,
          backgroundColor: barColors.map(c => c + '88'),
          borderColor: barColors,
          borderWidth: 1,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: '% of PA/AB', color: '#999' },
               ticks: { color: '#999' }, grid: { color: '#333' } },
          x: { ticks: { color: '#999' }, grid: { color: '#333' } }
        }
      }
    });
  }

  function _renderTierChart(canvasId, tiers, labelKey, chartRef) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    if (chartRef) chartRef.destroy();
    const labels = tiers.map(t => t.label);
    const datasets = [
      { label: 'AVG',   key: 'AVG',    color: '#10b981', yAxis: 'y1' },
      { label: 'ISO',   key: 'ISO',    color: '#ef4444', yAxis: 'y1' },
      { label: 'BABIP', key: 'BABIP',  color: '#8b5cf6', yAxis: 'y1' },
      { label: 'HR%',   key: 'HR_pct', color: '#f59e0b', yAxis: 'y' },
      { label: 'ITPHR%', key: 'ITPHR_pct', color: '#fb923c', yAxis: 'y' },
      { label: 'K%',    key: 'K_pct',  color: '#6b7280', yAxis: 'y' },
      { label: 'BB%',   key: 'BB_pct', color: '#06b6d4', yAxis: 'y' },
    ];
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: datasets.map(ds => ({
          label: ds.label,
          data: tiers.map(t => t.stats[ds.key]),
          borderColor: ds.color,
          backgroundColor: ds.color + '33',
          fill: false,
          tension: 0.3,
          pointRadius: 4,
          yAxisID: ds.yAxis,
        }))
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#ccc' } } },
        scales: {
          y: {
            position: 'left', beginAtZero: true,
            title: { display: true, text: 'Rate %', color: '#999' },
            ticks: { color: '#999' }, grid: { color: '#333' },
          },
          y1: {
            position: 'right', beginAtZero: true,
            title: { display: true, text: 'Slash', color: '#999' },
            ticks: { color: '#999' }, grid: { drawOnChartArea: false },
          },
          x: { ticks: { color: '#999' }, grid: { color: '#333' } }
        }
      }
    });
  }

  function renderPowerTiers(tiers) {
    const tbody = document.getElementById('an-ct-tiers-tbody');
    if (!tiers.length) {
      tbody.innerHTML = '<tr><td colspan="15" class="text-center text-muted">Not enough players for tier analysis</td></tr>';
      return;
    }
    tbody.innerHTML = tiers.map(t => {
      const s = t.stats;
      return `<tr>
        <td style="font-weight:600">${t.label}</td>
        <td>${t.count}</td>
        <td>${t.avg_power}</td>
        <td>${t.avg_contact}</td>
        <td>${s.AVG?.toFixed(3) || '--'}</td>
        <td>${s.SLG?.toFixed(3) || '--'}</td>
        <td>${s.ISO?.toFixed(3) || '--'}</td>
        <td>${s.HR_pct?.toFixed(1) || '--'}%</td>
        <td>${s.ITPHR_pct?.toFixed(1) || '--'}%</td>
        <td>${s['2B_pct']?.toFixed(1) || '--'}%</td>
        <td>${s['3B_pct']?.toFixed(1) || '--'}%</td>
        <td>${s.XBH_pct?.toFixed(1) || '--'}%</td>
        <td>${s.K_pct?.toFixed(1) || '--'}%</td>
        <td>${s.BB_pct?.toFixed(1) || '--'}%</td>
        <td>${s.BABIP?.toFixed(3) || '--'}</td>
      </tr>`;
    }).join('');
    contactPowerTierChart = _renderTierChart('an-ct-power-tier-chart', tiers, 'power', contactPowerTierChart);
  }

  function renderContactTiers(tiers) {
    const tbody = document.getElementById('an-ct-contact-tiers-tbody');
    if (!tiers || !tiers.length) {
      tbody.innerHTML = '<tr><td colspan="15" class="text-center text-muted">Not enough players for tier analysis</td></tr>';
      return;
    }
    tbody.innerHTML = tiers.map(t => {
      const s = t.stats;
      return `<tr>
        <td style="font-weight:600">${t.label}</td>
        <td>${t.count}</td>
        <td>${t.avg_contact}</td>
        <td>${t.avg_power}</td>
        <td>${s.AVG?.toFixed(3) || '--'}</td>
        <td>${s.SLG?.toFixed(3) || '--'}</td>
        <td>${s.ISO?.toFixed(3) || '--'}</td>
        <td>${s.HR_pct?.toFixed(1) || '--'}%</td>
        <td>${s.ITPHR_pct?.toFixed(1) || '--'}%</td>
        <td>${s['2B_pct']?.toFixed(1) || '--'}%</td>
        <td>${s['3B_pct']?.toFixed(1) || '--'}%</td>
        <td>${s.XBH_pct?.toFixed(1) || '--'}%</td>
        <td>${s.K_pct?.toFixed(1) || '--'}%</td>
        <td>${s.BB_pct?.toFixed(1) || '--'}%</td>
        <td>${s.BABIP?.toFixed(3) || '--'}</td>
      </tr>`;
    }).join('');
    contactContactTierChart = _renderTierChart('an-ct-contact-tier-chart', tiers, 'contact', contactContactTierChart);
  }

  let contactByTypeChart = null;
  function renderPerContactType(types) {
    const tbody = document.getElementById('an-ct-bytype-tbody');
    if (!types || !types.length) {
      tbody.innerHTML = '<tr><td colspan="12" class="text-center text-muted">No contact type data</td></tr>';
      return;
    }

    tbody.innerHTML = types.map(t => `<tr>
      <td><strong>${t.contact_type}</strong></td>
      <td>${t.frequency_pct}%</td>
      <td>${t.out_pct}%</td>
      <td>${t['1B_pct']}%</td>
      <td>${t['2B_pct']}%</td>
      <td>${t['3B_pct']}%</td>
      <td>${t.HR_pct}%</td>
      <td>${t.ITPHR_pct || 0}%</td>
      <td><strong>${t.hit_pct}%</strong></td>
      <td>${t.AVG.toFixed(3)}</td>
      <td>${t.SLG.toFixed(3)}</td>
      <td>${t.ISO.toFixed(3)}</td>
    </tr>`).join('');

    // Stacked bar chart: outcome distribution per contact type
    const labels = types.map(t => t.contact_type);
    const ctx = document.getElementById('an-ct-bytype-chart').getContext('2d');
    if (contactByTypeChart) contactByTypeChart.destroy();

    contactByTypeChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Out%', data: types.map(t => t.out_pct), backgroundColor: '#6b728088', borderColor: '#6b7280', borderWidth: 1 },
          { label: '1B%', data: types.map(t => t['1B_pct']), backgroundColor: '#3b82f688', borderColor: '#3b82f6', borderWidth: 1 },
          { label: '2B%', data: types.map(t => t['2B_pct']), backgroundColor: '#22c55e88', borderColor: '#22c55e', borderWidth: 1 },
          { label: '3B%', data: types.map(t => t['3B_pct']), backgroundColor: '#f59e0b88', borderColor: '#f59e0b', borderWidth: 1 },
          { label: 'HR%', data: types.map(t => t.HR_pct), backgroundColor: '#ef444488', borderColor: '#ef4444', borderWidth: 1 },
          { label: 'ITPHR%', data: types.map(t => t.ITPHR_pct || 0), backgroundColor: '#fb923c88', borderColor: '#fb923c', borderWidth: 1 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#9ca3af' } },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: { stacked: true, ticks: { color: '#9ca3af' }, grid: { color: '#333' } },
          y: { stacked: true, beginAtZero: true, max: 100,
               title: { display: true, text: '% of outcomes', color: '#999' },
               ticks: { color: '#9ca3af' }, grid: { color: '#333' } },
        },
      },
    });
  }

  function renderContactLeaders(category) {
    if (!_contactData) return;
    const players = _contactData.leaders[category] || [];
    const tbody = document.getElementById('an-ct-leaders-tbody');
    tbody.innerHTML = players.map((p, i) => `<tr>
      <td>${i + 1}</td>
      <td>${p.name}</td>
      <td>${p.power}</td>
      <td>${p.contact}</td>
      <td>${p.ab}</td>
      <td>${p.AVG?.toFixed(3)}</td>
      <td>${p.SLG?.toFixed(3)}</td>
      <td>${p.ISO?.toFixed(3)}</td>
      <td>${p.HR_pct?.toFixed(1)}%</td>
      <td>${p.ITPHR_pct?.toFixed(1) || '0.0'}%</td>
      <td>${p['2B_pct']?.toFixed(1)}%</td>
      <td>${p.K_pct?.toFixed(1)}%</td>
      <td>${p.BB_pct?.toFixed(1)}%</td>
    </tr>`).join('');
  }

  // --- HR Depth Analysis ---

  let hrdContactChart = null;
  let hrdDepthChart = null;
  let hrdHeatmapChart = null;

  const CONTACT_COLORS = {
    barrel: '#ef4444', solid: '#f59e0b', flare: '#10b981', burner: '#3b82f6',
    topped: '#8b5cf6', under: '#06b6d4', weak: '#6b7280', unknown: '#374151',
  };
  const DEPTH_ORDER = ['homerun', 'deep_of', 'middle_of', 'shallow_of', 'deep_if', 'middle_if', 'shallow_if', 'mound', 'catcher', 'unknown'];

  function loadHrDepth() {
    const lyid = document.getElementById('an-hrd-lyid')?.value;
    const level = document.getElementById('an-hrd-level')?.value;
    const gtype = document.getElementById('an-hrd-gtype')?.value;
    const status = document.getElementById('an-hrd-status');
    if (!lyid || !level) { status.textContent = 'Select league year and level.'; return; }
    status.textContent = 'Loading play-by-play data... this may take a moment.';

    ['an-hrd-summary-card', 'an-hrd-contact-card', 'an-hrd-depth-card', 'an-hrd-cross-card']
      .forEach(id => document.getElementById(id).style.display = 'none');

    const params = new URLSearchParams({ league_year_id: lyid, league_level: level, game_type: gtype });
    fetch(`/admin/analytics/hr-depth?${params}`, { credentials: 'include' })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => {
        if (!data.ok) { status.textContent = data.message || 'Error'; return; }
        status.textContent = '';
        renderHrdSummary(data);
        renderHrdContactType(data.by_contact_type, data.total_hr);
        renderHrdHitDepth(data.by_hit_depth, data.total_hr);
        renderHrdCrossTab(data.cross_tab, data.by_contact_type, data.by_hit_depth, data.total_hr);
        ['an-hrd-summary-card', 'an-hrd-contact-card', 'an-hrd-depth-card', 'an-hrd-cross-card']
          .forEach(id => document.getElementById(id).style.display = '');
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function renderHrdSummary(data) {
    const statsDiv = document.getElementById('an-hrd-summary-stats');
    const itphrPct = data.total_hr > 0 ? (data.total_itphr / data.total_hr * 100).toFixed(1) : '0.0';
    const cards = [
      ['Games Scanned', data.games_scanned.toLocaleString()],
      ['Total HRs', data.total_hr.toLocaleString()],
      ['Inside-the-Park', `${data.total_itphr} (${itphrPct}%)`],
      ['Over-the-Fence', (data.total_hr - data.total_itphr).toLocaleString()],
    ];
    statsDiv.innerHTML = cards.map(([label, val]) =>
      `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value">${val}</div></div>`
    ).join('');
  }

  function renderHrdContactType(byContact, totalHr) {
    const tbody = document.getElementById('an-hrd-contact-tbody');
    tbody.innerHTML = byContact.map(r => `<tr>
      <td><strong>${r.batted_ball}</strong></td>
      <td>${r.count.toLocaleString()}</td>
      <td>${r.pct}%</td>
    </tr>`).join('');

    const ctx = document.getElementById('an-hrd-contact-chart').getContext('2d');
    if (hrdContactChart) hrdContactChart.destroy();
    const labels = byContact.map(r => r.batted_ball);
    const values = byContact.map(r => r.count);
    const colors = labels.map(l => (CONTACT_COLORS[l] || '#6b7280') + 'cc');
    const borders = labels.map(l => CONTACT_COLORS[l] || '#6b7280');

    hrdContactChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: colors, borderColor: borders, borderWidth: 1 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { color: '#ccc', padding: 12 } },
          tooltip: {
            callbacks: {
              label: item => `${item.label}: ${item.raw.toLocaleString()} (${(item.raw / totalHr * 100).toFixed(1)}%)`,
            },
          },
        },
      },
    });
  }

  function renderHrdHitDepth(byDepth, totalHr) {
    const tbody = document.getElementById('an-hrd-depth-tbody');
    tbody.innerHTML = byDepth.map(r => `<tr>
      <td><strong>${r.hit_depth}</strong></td>
      <td>${r.count.toLocaleString()}</td>
      <td>${r.pct}%</td>
    </tr>`).join('');

    const ctx = document.getElementById('an-hrd-depth-chart').getContext('2d');
    if (hrdDepthChart) hrdDepthChart.destroy();
    const depthColors = ['#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#a78bfa'];

    hrdDepthChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: byDepth.map(r => r.hit_depth),
        datasets: [{
          label: 'HR Count',
          data: byDepth.map(r => r.count),
          backgroundColor: byDepth.map((_, i) => depthColors[i % depthColors.length] + '88'),
          borderColor: byDepth.map((_, i) => depthColors[i % depthColors.length]),
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: item => `${item.raw.toLocaleString()} HRs (${(item.raw / totalHr * 100).toFixed(1)}%)`,
            },
          },
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: 'Count', color: '#999' },
               ticks: { color: '#999' }, grid: { color: '#333' } },
          x: { ticks: { color: '#999', maxRotation: 45 }, grid: { color: '#333' } },
        },
      },
    });
  }

  function renderHrdCrossTab(crossTab, byContact, byDepth, totalHr) {
    // Build a pivot: rows = contact types, cols = hit depths
    const contactTypes = byContact.map(r => r.batted_ball);
    const hitDepths = byDepth.map(r => r.hit_depth);
    // Sort depths by DEPTH_ORDER where possible
    hitDepths.sort((a, b) => {
      const ia = DEPTH_ORDER.indexOf(a), ib = DEPTH_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });

    // Build lookup
    const lookup = {};
    crossTab.forEach(r => { lookup[`${r.batted_ball}|${r.hit_depth}`] = r.count; });

    // Header
    const header = document.getElementById('an-hrd-cross-header');
    header.innerHTML = '<th>Contact Type</th>' + hitDepths.map(d => `<th>${d}</th>`).join('') + '<th>Total</th>';

    // Body
    const tbody = document.getElementById('an-hrd-cross-tbody');
    // Find max for heat coloring
    const allCounts = crossTab.map(r => r.count);
    const maxCount = Math.max(...allCounts, 1);

    tbody.innerHTML = contactTypes.map(ct => {
      let rowTotal = 0;
      const cells = hitDepths.map(hd => {
        const count = lookup[`${ct}|${hd}`] || 0;
        rowTotal += count;
        const intensity = count / maxCount;
        const bg = count > 0 ? `rgba(239, 68, 68, ${(intensity * 0.6 + 0.05).toFixed(2)})` : 'transparent';
        return `<td style="background: ${bg}; text-align: center">${count || ''}</td>`;
      }).join('');
      return `<tr><td><strong>${ct}</strong></td>${cells}<td style="font-weight: 600">${rowTotal}</td></tr>`;
    }).join('');

    // Totals row
    const totalsRow = hitDepths.map(hd => {
      let colTotal = 0;
      contactTypes.forEach(ct => { colTotal += lookup[`${ct}|${hd}`] || 0; });
      return `<td style="font-weight: 600; text-align: center">${colTotal}</td>`;
    }).join('');
    tbody.innerHTML += `<tr><td style="font-weight: 600">Total</td>${totalsRow}<td style="font-weight: 600">${totalHr}</td></tr>`;

    // Stacked bar chart: contact types stacked, x-axis = hit depth
    const ctx = document.getElementById('an-hrd-heatmap-chart').getContext('2d');
    if (hrdHeatmapChart) hrdHeatmapChart.destroy();

    const datasets = contactTypes.map(ct => ({
      label: ct,
      data: hitDepths.map(hd => lookup[`${ct}|${hd}`] || 0),
      backgroundColor: (CONTACT_COLORS[ct] || '#6b7280') + '88',
      borderColor: CONTACT_COLORS[ct] || '#6b7280',
      borderWidth: 1,
    }));

    hrdHeatmapChart = new Chart(ctx, {
      type: 'bar',
      data: { labels: hitDepths, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#ccc' } },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: { stacked: true, ticks: { color: '#9ca3af', maxRotation: 45 }, grid: { color: '#333' } },
          y: { stacked: true, beginAtZero: true,
               title: { display: true, text: 'HR Count', color: '#999' },
               ticks: { color: '#9ca3af' }, grid: { color: '#333' } },
        },
      },
    });
  }

  // Wire up HR Depth load button
  document.getElementById('btn-an-hrd-load')?.addEventListener('click', loadHrDepth);

  // --- DB Storage ---

  function loadDbStorage() {
    const status = document.getElementById('db-storage-status');
    status.textContent = 'Loading...';
    document.getElementById('db-storage-summary').style.display = 'none';
    document.getElementById('db-storage-table-card').style.display = 'none';

    fetch(`${ADMIN_BASE}/db-storage`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = 'Error: ' + (data.error || data.message); return; }
        status.textContent = '';
        const s = data.summary;

        // Summary cards
        document.getElementById('db-storage-summary-content').innerHTML = `
          <div class="stat-card"><div class="stat-label">Tables</div><div class="stat-value">${s.table_count}</div></div>
          <div class="stat-card"><div class="stat-label">Total Rows</div><div class="stat-value">${s.total_rows.toLocaleString()}</div></div>
          <div class="stat-card"><div class="stat-label">Data</div><div class="stat-value">${s.total_data_mb} MB</div></div>
          <div class="stat-card"><div class="stat-label">Indexes</div><div class="stat-value">${s.total_index_mb} MB</div></div>
          <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value">${s.total_mb} MB</div></div>
        `;
        document.getElementById('db-storage-summary').style.display = '';

        // Table
        let html = '<table class="data-table"><thead><tr><th>Table</th><th>Rows</th><th>Data (MB)</th><th>Index (MB)</th><th>Total (MB)</th><th>Free (MB)</th><th></th></tr></thead><tbody>';
        const maxMb = Math.max(...data.tables.map(t => parseFloat(t.total_mb) || 0), 0.01);
        data.tables.forEach(t => {
          const pct = ((parseFloat(t.total_mb) || 0) / maxMb * 100).toFixed(0);
          html += `<tr>
            <td style="font-weight:600">${t.table_name}</td>
            <td style="text-align:right">${(t.table_rows || 0).toLocaleString()}</td>
            <td style="text-align:right">${t.data_mb}</td>
            <td style="text-align:right">${t.index_mb}</td>
            <td style="text-align:right;font-weight:600">${t.total_mb}</td>
            <td style="text-align:right">${t.free_mb}</td>
            <td style="width:120px"><div style="background:#e0e0e0;border-radius:3px;height:14px;"><div style="background:#4caf50;border-radius:3px;height:14px;width:${pct}%"></div></div></td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('db-storage-table').innerHTML = html;
        document.getElementById('db-storage-table-card').style.display = '';
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // ---------------------------------------------------------------------------
  // FA Orphan Sweep
  // ---------------------------------------------------------------------------

  let _orphanScanData = null;

  function scanForOrphans() {
    const status = document.getElementById('orphan-sweep-status');
    status.textContent = 'Scanning...';
    document.getElementById('orphan-found-count').textContent = '--';
    document.getElementById('orphan-entered-count').textContent = '--';
    document.getElementById('orphan-error-count').textContent = '--';
    document.getElementById('orphan-results-card').style.display = 'none';
    document.getElementById('orphan-fix-results-card').style.display = 'none';
    document.getElementById('btn-orphan-fix').disabled = true;

    fetch(`${ADMIN_BASE}/fa-orphan-scan`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          status.textContent = 'Error: ' + (data.error || data.message);
          return;
        }
        _orphanScanData = data;
        document.getElementById('orphan-found-count').textContent = data.count;
        status.textContent = data.count === 0
          ? 'No orphaned players found.'
          : `Found ${data.count} orphaned player(s). Review below, then click "Fix All Orphans" to enter them into the FA auction.`;

        if (data.count > 0) {
          document.getElementById('btn-orphan-fix').disabled = false;

          const levelNames = {
            1: 'HS', 2: 'INTAM', 3: 'College', 4: 'Scraps',
            5: 'A', 6: 'High-A', 7: 'AA', 8: 'AAA', 9: 'MLB',
          };
          const tbody = document.getElementById('orphan-results-body');
          tbody.innerHTML = data.players.map(p => `
            <tr>
              <td>${p.player_id}</td>
              <td style="font-weight:600">${p.name}</td>
              <td>${p.age || '--'}</td>
              <td>${p.ptype || '--'}</td>
              <td>${p.service_years}</td>
              <td>${levelNames[p.last_level] || p.last_level || '--'}</td>
              <td><span class="badge badge-warning">Orphaned</span></td>
            </tr>
          `).join('');
          document.getElementById('orphan-results-card').style.display = '';
        }
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function fixOrphans() {
    if (!_orphanScanData || !_orphanScanData.league_year_id) {
      alert('Run a scan first.');
      return;
    }
    if (!confirm(`This will enter ${_orphanScanData.count} player(s) into the FA auction. Continue?`)) {
      return;
    }

    const status = document.getElementById('orphan-sweep-status');
    status.textContent = 'Fixing orphans...';
    document.getElementById('btn-orphan-fix').disabled = true;

    fetch(`${API_BASE}/fa-auction/admin/orphan-sweep`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: _orphanScanData.league_year_id }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = 'Error: ' + data.error;
          return;
        }
        document.getElementById('orphan-entered-count').textContent = data.entered;
        document.getElementById('orphan-error-count').textContent = data.errors;
        status.textContent = `Done. Entered ${data.entered} player(s) into auction.` +
          (data.errors > 0 ? ` ${data.errors} error(s).` : '');

        const resultBox = document.getElementById('orphan-fix-result');
        resultBox.textContent = JSON.stringify(data, null, 2);
        document.getElementById('orphan-fix-results-card').style.display = '';

        // Update table badges
        if (data.players) {
          const enteredIds = new Set(data.players.map(p => p.player_id));
          document.querySelectorAll('#orphan-results-body tr').forEach(row => {
            const pid = parseInt(row.cells[0].textContent);
            if (enteredIds.has(pid)) {
              row.cells[6].innerHTML = '<span class="badge badge-success">Entered</span>';
            }
          });
        }
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // ---------------------------------------------------------------------------
  // Stamina Reports
  // ---------------------------------------------------------------------------

  let staminaOverviewChart = null;
  let staminaFlowChart = null;

  function staminaColor(val) {
    if (val >= 70) return '#27ae60';
    if (val >= 40) return '#e67e22';
    return '#e74c3c';
  }

  function staminaBar(val) {
    const c = staminaColor(val);
    return `<div style="display:flex;align-items:center;gap:6px">
      <div style="width:80px;background:#e0e0e0;border-radius:3px;height:14px">
        <div style="background:${c};border-radius:3px;height:14px;width:${val}%"></div>
      </div>
      <span style="color:${c};font-weight:600">${val}</span>
    </div>`;
  }

  function loadStaminaLeagueYears(section) {
    const prefixMap = {
      'stamina-overview': 'stam-ov',
      'stamina-team': 'stam-tm',
      'stamina-availability': 'stam-av',
      'stamina-consumption': 'stam-con',
      'stamina-flow': 'stam-fl',
    };
    const prefix = prefixMap[section];
    if (!prefix) return;
    const sel = document.getElementById(`${prefix}-lyid`);
    if (!sel || sel.options.length > 1) return;

    fetch(`${ADMIN_BASE}/analytics/league-years`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        sel.innerHTML = '';
        (data.league_years || []).forEach(ly => {
          const o = document.createElement('option');
          o.value = ly.id;
          o.textContent = ly.league_year;
          sel.appendChild(o);
        });
        // For team sections, also load team dropdown
        if (section === 'stamina-team' || section === 'stamina-flow') {
          const teamSel = document.getElementById(`${prefix}-team`);
          if (teamSel && teamSel.options.length <= 1) {
            fetch(`${ADMIN_BASE}/analytics/teams`, { credentials: 'include' })
              .then(r => r.json())
              .then(td => {
                if (!td.ok) return;
                const teams = td.teams || [];
                if (section === 'stamina-flow') {
                  teamSel.innerHTML = '<option value="">All Teams</option>';
                } else {
                  teamSel.innerHTML = '';
                }
                teams.forEach(t => {
                  const o = document.createElement('option');
                  o.value = t.id;
                  o.textContent = `${t.team_abbrev} (Lvl ${t.team_level})`;
                  teamSel.appendChild(o);
                });
              });
          }
        }
      });
  }

  function loadStaminaOverview() {
    const lyid = document.getElementById('stam-ov-lyid').value;
    const level = document.getElementById('stam-ov-level').value;
    const status = document.getElementById('stam-ov-status');
    status.textContent = 'Loading...';
    document.getElementById('stam-ov-summary').style.display = 'none';

    let url = `${ADMIN_BASE}/analytics/stamina-overview?league_year_id=${lyid}`;
    if (level) url += `&league_level=${level}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('stam-ov-summary').style.display = '';

        // Summary cards — separate pitcher vs position, show data coverage
        const pt = data.pitcher_thresholds || {};
        const bt = data.position_thresholds || {};
        const pTracked = data.pitchers_with_data || 0;
        const pNoData = data.pitchers_no_data || 0;
        const bTracked = data.position_with_data || 0;
        const bNoData = data.position_no_data || 0;
        document.getElementById('stam-ov-total').textContent =
          `${data.total_pitchers || 0} pitchers / ${data.total_position || 0} position`;
        document.getElementById('stam-ov-avg').innerHTML =
          `P: ${data.pitcher_avg_stamina ?? 'N/A'}  |  Pos: ${data.position_avg_stamina ?? 'N/A'}` +
          (pNoData + bNoData > 0
            ? `<br><small style="color:#999">Tracked: ${pTracked}P + ${bTracked}Pos | No data: ${pNoData}P + ${bNoData}Pos</small>`
            : '');
        document.getElementById('stam-ov-b70').textContent =
          `P: ${pt.below_70 || 0}  |  Pos: ${bt.below_70 || 0}`;
        document.getElementById('stam-ov-b40').textContent =
          `P: ${pt.below_40 || 0}  |  Pos: ${bt.below_40 || 0}`;
        document.getElementById('stam-ov-zero').textContent =
          `P: ${pt.at_zero || 0}  |  Pos: ${bt.at_zero || 0}`;

        // Dual histogram — pitchers vs position players
        if (staminaOverviewChart) staminaOverviewChart.destroy();
        const ctx = document.getElementById('stam-ov-chart').getContext('2d');
        const labels = ['0-9','10-19','20-29','30-39','40-49','50-59','60-69','70-79','80-89','90-99','100'];
        staminaOverviewChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: 'Pitchers',
                data: data.pitcher_distribution,
                backgroundColor: 'rgba(52, 152, 219, 0.7)',
                borderColor: 'rgba(52, 152, 219, 1)',
                borderWidth: 1,
              },
              {
                label: 'Position Players',
                data: data.position_distribution,
                backgroundColor: 'rgba(46, 204, 113, 0.7)',
                borderColor: 'rgba(46, 204, 113, 1)',
                borderWidth: 1,
              }
            ]
          },
          options: {
            responsive: true,
            plugins: { title: { display: true, text: 'Stamina Distribution (tracked players only)' } },
            scales: { y: { beginAtZero: true, title: { display: true, text: 'Players' } } }
          }
        });

        // Team averages table — separate pitcher/position columns
        let html = `<table class="data-table"><thead><tr>
          <th>Team</th><th>Lvl</th>
          <th>P Tracked</th><th>P Avg</th><th>P &lt;70</th><th>P &lt;40</th>
          <th>Pos Tracked</th><th>Pos Avg</th><th>Pos &lt;70</th><th>Pos &lt;40</th>
        </tr></thead><tbody>`;
        data.team_averages.forEach(t => {
          const pLabel = t.pitcher_tracked < t.pitcher_count
            ? `${t.pitcher_tracked}/${t.pitcher_count}`
            : `${t.pitcher_count}`;
          const bLabel = t.position_tracked < t.position_count
            ? `${t.position_tracked}/${t.position_count}`
            : `${t.position_count}`;
          html += `<tr>
            <td>${t.team_abbrev}</td>
            <td>${t.team_level}</td>
            <td>${pLabel}</td>
            <td style="color:${staminaColor(t.avg_pitcher_stamina || 100)};font-weight:600">${t.avg_pitcher_stamina ?? '<span style="color:#999">-</span>'}</td>
            <td style="color:#e67e22">${t.pitcher_below_70 || 0}</td>
            <td style="color:#e74c3c">${t.pitcher_below_40 || 0}</td>
            <td>${bLabel}</td>
            <td style="color:${staminaColor(t.avg_position_stamina || 100)};font-weight:600">${t.avg_position_stamina ?? '<span style="color:#999">-</span>'}</td>
            <td style="color:#e67e22">${t.position_below_70 || 0}</td>
            <td style="color:#e74c3c">${t.position_below_40 || 0}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('stam-ov-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadStaminaTeamDetail() {
    const lyid = document.getElementById('stam-tm-lyid').value;
    const tid = document.getElementById('stam-tm-team').value;
    const status = document.getElementById('stam-tm-status');
    if (!tid) { status.textContent = 'Select a team'; return; }
    status.textContent = 'Loading...';
    document.getElementById('stam-tm-results').style.display = 'none';

    fetch(`${ADMIN_BASE}/analytics/stamina-team?league_year_id=${lyid}&team_id=${tid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('stam-tm-results').style.display = '';

        let html = '<h4 style="margin:8px 0 4px">Pitchers</h4>';
        html += `<table class="data-table"><thead><tr>
          <th>Name</th><th>Stamina</th><th>Durability</th><th>Endurance</th>
          <th>G</th><th>GS</th><th>IP</th>
          <th>Rec/SW</th><th>SW to 70</th><th>SW to 100</th>
        </tr></thead><tbody>`;
        data.pitchers.forEach(p => {
          const stam = p.has_fatigue_data ? staminaBar(p.stamina) : '<span style="color:#bbb">N/A</span>';
          html += `<tr style="${!p.has_fatigue_data ? 'opacity:0.6' : ''}">
            <td>${p.name}</td>
            <td>${stam}</td>
            <td>${p.durability}</td>
            <td>${p.pendurance_base}</td>
            <td>${p.games}</td>
            <td>${p.games_started}</td>
            <td>${p.ip}</td>
            <td>+${p.recovery_per_subweek}</td>
            <td>${p.subweeks_to_70 ?? '-'}</td>
            <td>${p.subweeks_to_100 ?? '-'}</td>
          </tr>`;
        });
        html += '</tbody></table>';

        // Position players
        if (data.position_players && data.position_players.length > 0) {
          const posTracked = data.position_players.filter(p => p.has_fatigue_data).length;
          const posTotal = data.position_players.length;
          html += '<h4 style="margin:16px 0 4px">Position Players</h4>';
          if (posTracked < posTotal) {
            html += `<p style="color:#999;font-size:13px;margin-bottom:4px">${posTracked}/${posTotal} have fatigue tracking data</p>`;
          }
          html += `<table class="data-table"><thead><tr>
            <th>Name</th><th>Stamina</th><th>Durability</th>
            <th>G</th><th>Est. Drain/G</th>
            <th>Rec/SW</th><th>SW to 70</th><th>SW to 100</th>
          </tr></thead><tbody>`;
          data.position_players.forEach(p => {
            const stam = p.has_fatigue_data ? staminaBar(p.stamina) : '<span style="color:#bbb">N/A</span>';
            const drain = p.est_drain_per_game !== null ? p.est_drain_per_game : '<span style="color:#bbb">N/A</span>';
            html += `<tr style="${!p.has_fatigue_data ? 'opacity:0.6' : ''}">
              <td>${p.name}</td>
              <td>${stam}</td>
              <td>${p.durability}</td>
              <td>${p.games}</td>
              <td>${drain}</td>
              <td>+${p.recovery_per_subweek}</td>
              <td>${p.subweeks_to_70 ?? '-'}</td>
              <td>${p.subweeks_to_100 ?? '-'}</td>
            </tr>`;
          });
          html += '</tbody></table>';
        }

        document.getElementById('stam-tm-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadStaminaAvailability() {
    const lyid = document.getElementById('stam-av-lyid').value;
    const level = document.getElementById('stam-av-level').value;
    const status = document.getElementById('stam-av-status');
    status.textContent = 'Loading...';
    document.getElementById('stam-av-results').style.display = 'none';

    let url = `${ADMIN_BASE}/analytics/stamina-availability?league_year_id=${lyid}`;
    if (level) url += `&league_level=${level}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('stam-av-results').style.display = '';

        const dangerBadge = (level) => {
          if (level === 'critical') return '<span class="badge badge-danger">CRITICAL</span>';
          if (level === 'warning') return '<span class="badge badge-warning">WARNING</span>';
          return '<span class="badge badge-success">OK</span>';
        };
        let html = `<table class="data-table"><thead><tr>
          <th>Team</th><th>Lvl</th>
          <th>P Total</th><th>P &ge;95</th><th>P &ge;70</th><th>P &ge;40</th><th>P Status</th>
          <th>Pos Total</th><th>Pos &ge;95</th><th>Pos &ge;70</th><th>Pos &ge;40</th><th>Pos Status</th>
        </tr></thead><tbody>`;
        data.teams.forEach(t => {
          html += `<tr>
            <td><strong>${t.team_abbrev}</strong></td>
            <td>${t.team_level}</td>
            <td>${t.total_pitchers}</td>
            <td>${t.pitcher_avail_95}</td>
            <td><strong>${t.pitcher_avail_70}</strong></td>
            <td class="${t.pitcher_avail_40 < t.total_pitchers ? 'text-danger' : ''}">${t.pitcher_avail_40}</td>
            <td>${dangerBadge(t.pitcher_danger)}</td>
            <td>${t.total_position}</td>
            <td>${t.position_avail_95}</td>
            <td><strong>${t.position_avail_70}</strong></td>
            <td class="${t.position_avail_40 < t.total_position ? 'text-danger' : ''}">${t.position_avail_40}</td>
            <td>${dangerBadge(t.position_danger)}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('stam-av-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadStaminaConsumption() {
    const lyid = document.getElementById('stam-con-lyid').value;
    const level = document.getElementById('stam-con-level').value;
    const status = document.getElementById('stam-con-status');
    status.textContent = 'Loading...';
    document.getElementById('stam-con-results').style.display = 'none';

    let url = `${ADMIN_BASE}/analytics/stamina-consumption?league_year_id=${lyid}`;
    if (level) url += `&league_level=${level}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('stam-con-results').style.display = '';

        // Pitchers section
        let html = '<h4 style="margin:0 0 4px">Pitchers</h4>';
        html += `<p style="margin-bottom:8px">Avg games: <strong>${data.pitcher_avg_games}</strong></p>`;
        html += `<table class="data-table"><thead><tr>
          <th>Name</th><th>Team</th><th>G</th><th>GS</th><th>IP</th>
          <th>Stamina</th><th>Durability</th><th>Endur.</th>
          <th>Est. Drain</th><th>Avg/G</th><th>Flag</th>
        </tr></thead><tbody>`;
        data.pitchers.forEach(p => {
          const flag = p.overworked
            ? '<span style="background:#e74c3c;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px">OVERWORKED</span>'
            : '';
          html += `<tr style="${p.overworked ? 'background:#fdf2f2' : ''}">
            <td>${p.name}</td>
            <td>${p.team_abbrev}</td>
            <td>${p.games}</td>
            <td>${p.gs}</td>
            <td>${p.ip}</td>
            <td>${staminaBar(p.current_stamina)}</td>
            <td>${p.durability}</td>
            <td>${p.pendurance_base}</td>
            <td>${p.est_total_consumed}</td>
            <td>${p.avg_cost_per_game}</td>
            <td>${flag}</td>
          </tr>`;
        });
        html += '</tbody></table>';

        // Position players section
        if (data.position_players && data.position_players.length > 0) {
          const tracked = data.position_players.filter(p => p.has_fatigue_data).length;
          const untracked = data.position_players.length - tracked;
          html += '<h4 style="margin:16px 0 4px">Position Players</h4>';
          html += `<p style="margin-bottom:8px">Avg games: <strong>${data.position_avg_games}</strong>`;
          if (untracked > 0) {
            html += ` &mdash; <span style="color:#999">${untracked} players have no fatigue data (engine stamina_cost not yet reporting)</span>`;
          }
          html += '</p>';
          html += `<table class="data-table"><thead><tr>
            <th>Name</th><th>Team</th><th>G</th>
            <th>Stamina</th><th>Durability</th><th>Rec/SW</th>
            <th>Est. Total Drain</th><th>Avg/G</th><th>Flag</th>
          </tr></thead><tbody>`;
          data.position_players.forEach(p => {
            const flag = p.fatigued
              ? '<span style="background:#e67e22;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px">FATIGUED</span>'
              : (!p.has_fatigue_data ? '<span style="color:#bbb;font-size:11px">NO DATA</span>' : '');
            const drainText = p.est_total_consumed !== null ? p.est_total_consumed : '<span style="color:#bbb">N/A</span>';
            const avgText = p.avg_cost_per_game !== null ? p.avg_cost_per_game : '<span style="color:#bbb">N/A</span>';
            const stam = p.has_fatigue_data ? staminaBar(p.current_stamina) : '<span style="color:#bbb">N/A</span>';
            html += `<tr style="${p.fatigued ? 'background:#fef9e7' : (!p.has_fatigue_data ? 'opacity:0.6' : '')}">
              <td>${p.name}</td>
              <td>${p.team_abbrev}</td>
              <td>${p.games}</td>
              <td>${stam}</td>
              <td>${p.durability}</td>
              <td>+${p.recovery_per_subweek}</td>
              <td>${drainText}</td>
              <td>${avgText}</td>
              <td>${flag}</td>
            </tr>`;
          });
          html += '</tbody></table>';
        }

        document.getElementById('stam-con-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function loadStaminaFlow() {
    const lyid = document.getElementById('stam-fl-lyid').value;
    const tid = document.getElementById('stam-fl-team').value;
    const status = document.getElementById('stam-fl-status');
    status.textContent = 'Loading...';
    document.getElementById('stam-fl-results').style.display = 'none';

    let url = `${ADMIN_BASE}/analytics/stamina-flow?league_year_id=${lyid}`;
    if (tid) url += `&team_id=${tid}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('stam-fl-results').style.display = '';

        const weeks = data.weeks || [];
        if (!weeks.length) {
          document.getElementById('stam-fl-table').innerHTML = '<p>No data</p>';
          return;
        }

        // Chart
        if (staminaFlowChart) staminaFlowChart.destroy();
        const ctx = document.getElementById('stam-fl-chart').getContext('2d');
        staminaFlowChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: weeks.map(w => `Wk ${w.week}`),
            datasets: [
              {
                label: 'Projected Avg Stamina',
                data: weeks.map(w => w.projected_avg_stamina),
                borderColor: '#2980b9',
                backgroundColor: 'rgba(41,128,185,0.1)',
                fill: true,
                tension: 0.3,
              },
              {
                label: 'Total Drain',
                data: weeks.map(w => w.total_drain),
                borderColor: '#e74c3c',
                borderDash: [5, 5],
                yAxisID: 'y1',
              },
              {
                label: 'Est Recovery',
                data: weeks.map(w => w.est_recovery),
                borderColor: '#27ae60',
                borderDash: [5, 5],
                yAxisID: 'y1',
              }
            ]
          },
          options: {
            responsive: true,
            plugins: { title: { display: true, text: `Stamina Flow (${data.total_pitchers} pitchers)` } },
            scales: {
              y: { beginAtZero: true, max: 100, title: { display: true, text: 'Avg Stamina' } },
              y1: { position: 'right', beginAtZero: true, title: { display: true, text: 'Drain / Recovery' }, grid: { drawOnChartArea: false } }
            }
          }
        });

        // Table
        let html = `<table class="data-table"><thead><tr>
          <th>Week</th><th>Appearances</th><th>Pitchers Used</th><th>Resting</th>
          <th>Total Drain</th><th>Est Recovery</th><th>Net</th><th>Proj Avg</th>
        </tr></thead><tbody>`;
        weeks.forEach(w => {
          const netColor = w.net_change >= 0 ? '#27ae60' : '#e74c3c';
          html += `<tr>
            <td>${w.week}</td>
            <td>${w.appearances}</td>
            <td>${w.pitchers_used}</td>
            <td>${w.pitchers_resting}</td>
            <td style="color:#e74c3c">${w.total_drain}</td>
            <td style="color:#27ae60">${w.est_recovery}</td>
            <td style="color:${netColor};font-weight:600">${w.net_change > 0 ? '+' : ''}${w.net_change}</td>
            <td style="color:${staminaColor(w.projected_avg_stamina)};font-weight:600">${w.projected_avg_stamina}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('stam-fl-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  // Export public API
  // =====================================================================
  // Special Events: Playoffs, All-Star, WBC
  // =====================================================================

  function loadSpecialEventLeagueYears(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel || sel.options.length > 1) return;
    fetch(`${ADMIN_BASE}/analytics/league-years`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        sel.innerHTML = '';
        (data.league_years || []).forEach(ly => {
          const o = document.createElement('option');
          o.value = ly.id;
          o.textContent = ly.league_year;
          sel.appendChild(o);
        });
      });
  }

  // --- Playoffs ---
  document.getElementById('btn-po-generate')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const level = document.getElementById('po-level').value;
    const status = document.getElementById('po-status');
    status.textContent = 'Generating bracket...';
    fetch(`${API_BASE}/playoffs/generate`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid), league_level: parseInt(level) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message}`; return; }
      status.textContent = `Created ${(data.series_created || []).length} series`;
      if (data.field) renderPlayoffField(data.field);
      loadPlayoffBracket(lyid, level);
      loadPendingGames(lyid, level);
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-po-process')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const level = document.getElementById('po-level').value;
    const status = document.getElementById('po-status');
    status.textContent = 'Processing playoff results...';
    fetch(`${API_BASE}/playoffs/process-results`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid), league_level: parseInt(level) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      status.textContent = `Processed ${data.processed} game result(s)`;
      loadPlayoffBracket(lyid, level);
      loadPendingGames(lyid, level);
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-po-wipe')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const level = document.getElementById('po-level').value;
    const levelLabel = document.getElementById('po-level').selectedOptions[0]?.textContent || level;
    const status = document.getElementById('po-status');
    if (!confirm(`Wipe all playoff data for ${levelLabel}? This deletes series, games, and results. Season stats are kept.`)) return;
    status.textContent = 'Wiping playoffs...';
    fetch(`${API_BASE}/playoffs/wipe`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid), league_level: parseInt(level) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      const parts = [];
      if (data.playoff_series) parts.push(`${data.playoff_series} series`);
      if (data.gamelist) parts.push(`${data.gamelist} games`);
      if (data.game_results) parts.push(`${data.game_results} results`);
      status.textContent = `Wiped: ${parts.join(', ') || 'nothing to wipe'}`;
      document.getElementById('po-bracket-card').style.display = 'none';
      document.getElementById('po-pending-card').style.display = 'none';
      document.getElementById('po-field-card').style.display = 'none';
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-po-advance')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const level = document.getElementById('po-level').value;
    const status = document.getElementById('po-status');
    status.textContent = 'Advancing round...';
    fetch(`${API_BASE}/playoffs/advance`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid), league_level: parseInt(level) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      status.textContent = data.status === 'complete' ? data.message : `Advanced to ${data.round_advanced}`;
      loadPlayoffBracket(lyid, level);
      loadPendingGames(lyid, level);
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-po-refresh')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const level = document.getElementById('po-level').value;
    loadPlayoffBracket(lyid, level);
    loadPendingGames(lyid, level);
  });

  // --- Conference Tournament controls (show only for College / level 3) ---
  function updateCtControlsVisibility() {
    const level = document.getElementById('po-level')?.value;
    const ct = document.getElementById('ct-controls');
    if (ct) ct.style.display = level === '3' ? 'flex' : 'none';
  }
  document.getElementById('po-level')?.addEventListener('change', updateCtControlsVisibility);
  updateCtControlsVisibility();

  document.getElementById('btn-ct-generate')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const status = document.getElementById('po-status');
    status.textContent = 'Generating conference tournaments...';
    fetch(`${API_BASE}/playoffs/conf-tournaments/generate`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      status.textContent = `Created ${data.total_series} series across ${(data.conferences || []).length} conferences`;
      loadPlayoffBracket(lyid, '3');
      loadPendingGames(lyid, '3');
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-ct-advance')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const status = document.getElementById('po-status');
    status.textContent = 'Advancing conference tournaments...';
    fetch(`${API_BASE}/playoffs/conf-tournaments/advance`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      const parts = [];
      if (data.advanced?.length) parts.push(`${data.advanced.length} conf(s) advanced`);
      if (data.completed?.length) parts.push(`${data.completed.length} conf(s) complete`);
      if (data.no_action?.length) parts.push(`${data.no_action.length} no action`);
      status.textContent = parts.join(', ') || 'No changes';
      loadPlayoffBracket(lyid, '3');
      loadPendingGames(lyid, '3');
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-ct-wipe')?.addEventListener('click', () => {
    const lyid = document.getElementById('po-lyid').value;
    const status = document.getElementById('po-status');
    if (!confirm('Wipe all conference tournament data? CWS data will be kept.')) return;
    status.textContent = 'Wiping conference tournaments...';
    fetch(`${API_BASE}/playoffs/conf-tournaments/wipe`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      const parts = [];
      if (data.playoff_series) parts.push(`${data.playoff_series} series`);
      if (data.gamelist) parts.push(`${data.gamelist} games`);
      status.textContent = `Wiped: ${parts.join(', ') || 'nothing to wipe'}`;
      document.getElementById('ct-bracket-card').style.display = 'none';
      loadPlayoffBracket(lyid, '3');
      loadPendingGames(lyid, '3');
    }).catch(e => status.textContent = e.message);
  });

  function loadPlayoffBracket(lyid, level) {
    fetch(`${API_BASE}/playoffs/bracket/${lyid}/${level}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        // --- Conference Tournaments (level 3 only) ---
        const ctCard = document.getElementById('ct-bracket-card');
        const ctDiv = document.getElementById('ct-bracket');
        if (data.conf_tournaments && Object.keys(data.conf_tournaments).length > 0) {
          ctCard.style.display = '';
          let ctHtml = '';
          for (const [conf, cdata] of Object.entries(data.conf_tournaments).sort((a, b) => a[0].localeCompare(b[0]))) {
            const roundNames = Object.keys(cdata.rounds).sort();
            const totalRounds = roundNames.length;
            // Find if conference is complete (last round has a winner)
            const lastRound = roundNames[roundNames.length - 1];
            const lastSeries = cdata.rounds[lastRound] || [];
            const confWinner = lastSeries.length === 1 && lastSeries[0].winner ? lastSeries[0].winner.abbrev : null;
            const confStatus = confWinner ? ` — Champion: ${confWinner}` : '';
            ctHtml += `<details style="margin-bottom:8px"><summary style="cursor:pointer;font-weight:600">${conf}${confStatus}</summary>`;
            for (const rnd of roundNames) {
              const rndNum = parseInt(rnd.replace('CT_R', ''));
              let label = rnd;
              if (rndNum === totalRounds) label = 'Final';
              else if (rndNum === totalRounds - 1) label = 'Semifinal';
              else if (rndNum === totalRounds - 2) label = 'Quarterfinal';
              else label = `Round ${rndNum}`;
              ctHtml += `<h6 style="margin-top:8px;margin-left:12px">${label}</h6>`;
              ctHtml += '<table class="data-table" style="margin-left:12px"><thead><tr><th>Matchup</th><th>Status</th><th>Winner</th></tr></thead><tbody>';
              (cdata.rounds[rnd] || []).forEach(s => {
                const statusBadge = s.status === 'complete'
                  ? '<span class="badge badge-success">Complete</span>'
                  : '<span class="badge badge-warning">Pending</span>';
                ctHtml += `<tr>
                  <td>${s.team_a.abbrev} (#${s.team_a.seed || '-'}) vs ${s.team_b.abbrev} (#${s.team_b.seed || '-'})</td>
                  <td>${statusBadge}</td>
                  <td>${s.winner ? s.winner.abbrev : '-'}</td>
                </tr>`;
              });
              ctHtml += '</tbody></table>';
            }
            ctHtml += '</details>';
          }
          ctDiv.innerHTML = ctHtml;
        } else if (ctCard) {
          ctCard.style.display = 'none';
        }

        // --- Main Bracket (CWS rounds, MLB, MiLB) ---
        const card = document.getElementById('po-bracket-card');
        const div = document.getElementById('po-bracket');
        if (!data.rounds || Object.keys(data.rounds).length === 0) {
          card.style.display = 'none';
          return;
        }
        card.style.display = '';
        let html = '';
        for (const [round, series] of Object.entries(data.rounds)) {
          html += `<h5 style="margin-top:16px">${round}</h5>`;
          html += '<table class="data-table"><thead><tr><th>Matchup</th><th>Score</th><th>Status</th><th>Winner</th></tr></thead><tbody>';
          series.forEach(s => {
            const scoreA = s.wins_a, scoreB = s.wins_b;
            const gamesPlayed = scoreA + scoreB;
            const statusBadge = s.status === 'complete'
              ? '<span class="badge badge-success">Complete</span>'
              : `<span class="badge badge-warning">Game ${gamesPlayed + 1} of ${s.series_length}</span>`;
            html += `<tr>
              <td>${s.team_a.abbrev} (#${s.team_a.seed || '-'}) vs ${s.team_b.abbrev} (#${s.team_b.seed || '-'})</td>
              <td>${scoreA} - ${scoreB} (Bo${s.series_length})</td>
              <td>${statusBadge}</td>
              <td>${s.winner ? s.winner.abbrev : '-'}</td>
            </tr>`;
          });
          html += '</tbody></table>';
        }

        if (data.cws_bracket) {
          html += '<h5 style="margin-top:16px">CWS Bracket</h5>';
          html += '<table class="data-table"><thead><tr><th>Seed</th><th>Team</th><th>Qual</th><th>Losses</th><th>Side</th></tr></thead><tbody>';
          data.cws_bracket.forEach(t => {
            const elim = t.eliminated ? ' style="opacity:0.4"' : '';
            html += `<tr${elim}><td>#${t.seed}</td><td>${t.team_abbrev}</td><td>${t.qualification}</td><td>${t.losses}</td><td>${t.bracket_side}</td></tr>`;
          });
          html += '</tbody></table>';
        }

        div.innerHTML = html;
      });
  }

  function loadPendingGames(lyid, level) {
    fetch(`${API_BASE}/playoffs/pending-games/${lyid}/${level}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('po-pending-card');
        const div = document.getElementById('po-pending');
        if (!data.games || data.games.length === 0) {
          card.style.display = 'none';
          return;
        }
        card.style.display = '';
        let html = '<table class="data-table"><thead><tr><th>Game ID</th><th>Round</th><th>Matchup</th><th>Series</th><th>Week</th><th>Subweek</th></tr></thead><tbody>';
        data.games.forEach(g => {
          const series = `${g.wins_a}-${g.wins_b} (Bo${g.series_length})`;
          html += `<tr>
            <td>${g.game_id}</td>
            <td>${g.round}</td>
            <td>${g.away_abbrev} @ ${g.home_abbrev}</td>
            <td>${series}</td>
            <td>${g.season_week}</td>
            <td>${g.season_subweek}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        div.innerHTML = html;
      });
  }

  function renderPlayoffField(field) {
    const card = document.getElementById('po-field-card');
    const div = document.getElementById('po-field');
    card.style.display = '';
    let html = '';
    if (Array.isArray(field)) {
      // MiLB / CWS field
      html += '<table class="data-table"><thead><tr><th>Seed</th><th>Team</th><th>W</th><th>L</th><th>Pct</th><th>Qual</th></tr></thead><tbody>';
      field.forEach(t => {
        html += `<tr><td>#${t.seed}</td><td>${t.team_abbrev}</td><td>${t.wins}</td><td>${t.losses}</td><td>${t.win_pct}</td><td>${t.qualifier}</td></tr>`;
      });
      html += '</tbody></table>';
    } else {
      // MLB field (AL/NL)
      for (const [conf, teams] of Object.entries(field)) {
        html += `<h5>${conf}</h5>`;
        html += '<table class="data-table"><thead><tr><th>Seed</th><th>Team</th><th>W</th><th>L</th><th>Pct</th><th>Qual</th></tr></thead><tbody>';
        teams.forEach(t => {
          html += `<tr><td>#${t.seed}</td><td>${t.team_abbrev}</td><td>${t.wins}</td><td>${t.losses}</td><td>${t.win_pct}</td><td>${t.qualifier}</td></tr>`;
        });
        html += '</tbody></table>';
      }
    }
    div.innerHTML = html;
  }

  // --- All-Star ---
  function collectAllStarSide(prefix) {
    const label = document.getElementById(`as-${prefix}-label`).value.trim();
    const spInputs = document.querySelectorAll(`.as-${prefix}-sp`);
    const rpInputs = document.querySelectorAll(`.as-${prefix}-rp`);
    const lineupInputs = document.querySelectorAll(`.as-${prefix}-lineup`);
    const benchInputs = document.querySelectorAll(`.as-${prefix}-bench`);

    const starting_pitchers = Array.from(spInputs).map(el => parseInt(el.value)).filter(v => !isNaN(v));
    const relief_pitchers = Array.from(rpInputs).map(el => parseInt(el.value)).filter(v => !isNaN(v));
    const lineup = Array.from(lineupInputs).map(el => {
      const pid = parseInt(el.value);
      return isNaN(pid) ? null : { player_id: pid, position: el.dataset.pos };
    }).filter(Boolean);
    const bench = Array.from(benchInputs).map(el => parseInt(el.value)).filter(v => !isNaN(v));

    return { label, starting_pitchers, relief_pitchers, lineup, bench };
  }

  document.getElementById('btn-as-create')?.addEventListener('click', () => {
    const lyid = document.getElementById('as-lyid').value;
    const level = document.getElementById('as-level').value;
    const status = document.getElementById('as-status');

    const home = collectAllStarSide('home');
    const away = collectAllStarSide('away');

    // Quick validation
    const errors = [];
    if (!home.label) errors.push('Home team label required');
    if (!away.label) errors.push('Away team label required');
    if (home.starting_pitchers.length !== 12) errors.push(`Home: need 12 SP, got ${home.starting_pitchers.length}`);
    if (away.starting_pitchers.length !== 12) errors.push(`Away: need 12 SP, got ${away.starting_pitchers.length}`);
    if (home.relief_pitchers.length !== 4) errors.push(`Home: need 4 RP, got ${home.relief_pitchers.length}`);
    if (away.relief_pitchers.length !== 4) errors.push(`Away: need 4 RP, got ${away.relief_pitchers.length}`);
    if (home.lineup.length !== 9) errors.push(`Home: need 9 lineup, got ${home.lineup.length}`);
    if (away.lineup.length !== 9) errors.push(`Away: need 9 lineup, got ${away.lineup.length}`);
    if (home.bench.length !== 11) errors.push(`Home: need 11 bench, got ${home.bench.length}`);
    if (away.bench.length !== 11) errors.push(`Away: need 11 bench, got ${away.bench.length}`);

    if (errors.length) {
      status.textContent = errors.join('; ');
      return;
    }

    status.textContent = 'Creating All-Star event...';
    fetch(`${API_BASE}/allstar/create`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(lyid),
        league_level: parseInt(level),
        home, away,
      }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message}`; return; }
      document.getElementById('as-eid').value = data.event_id;
      status.textContent = `Event ${data.event_id} created (level ${data.league_level}). Ready to simulate.`;
      loadAllStarRosters(data.event_id);
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-as-simulate')?.addEventListener('click', () => {
    const eid = document.getElementById('as-eid').value;
    const status = document.getElementById('as-status');
    if (!eid) { status.textContent = 'Enter event ID first'; return; }
    status.textContent = 'Simulating All-Star game...';
    fetch(`${API_BASE}/allstar/${eid}/simulate`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message}`; return; }
      status.textContent = `${data.home_label} ${data.home_score} - ${data.away_label} ${data.away_score} (Winner: ${data.winner_label})`;
      loadAllStarResults(parseInt(eid));
    }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-as-refresh')?.addEventListener('click', () => {
    const eid = document.getElementById('as-eid').value;
    if (!eid) { document.getElementById('as-status').textContent = 'Enter event ID'; return; }
    loadAllStarRosters(parseInt(eid));
    loadAllStarResults(parseInt(eid));
  });

  function loadAllStarRosters(eventId) {
    fetch(`${API_BASE}/allstar/${eventId}/rosters`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('as-rosters-card');
        const div = document.getElementById('as-rosters');
        if (!data.rosters) { card.style.display = 'none'; return; }
        card.style.display = '';
        let html = '';
        for (const [label, players] of Object.entries(data.rosters)) {
          html += `<h5>${label} (${players.length} players)</h5>`;
          html += '<table class="data-table"><thead><tr><th>Name</th><th>Team</th><th>Pos</th><th>Starter</th></tr></thead><tbody>';
          players.forEach(p => {
            html += `<tr><td>${p.name}</td><td>${p.team || '-'}</td><td>${p.position}</td>
              <td>${p.is_starter ? '<span class="badge badge-success">Yes</span>' : ''}</td></tr>`;
          });
          html += '</tbody></table>';
        }
        div.innerHTML = html;
      });
  }

  function loadAllStarResults(eventId) {
    fetch(`${API_BASE}/allstar/${eventId}/results`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('as-result-card');
        const div = document.getElementById('as-result');
        if (!data.game_result) { card.style.display = 'none'; return; }
        card.style.display = '';
        const gr = data.game_result;
        div.innerHTML = `<table class="data-table"><thead><tr><th>Home</th><th>Away</th><th>Score</th><th>Winner</th></tr></thead><tbody>
          <tr><td>${gr.home_label}</td><td>${gr.away_label}</td><td>${gr.home_score} - ${gr.away_score}</td>
          <td><span class="badge badge-success">${gr.winner_label}</span></td></tr></tbody></table>`;
      });
  }

  // --- WBC ---
  document.getElementById('btn-wbc-countries')?.addEventListener('click', () => {
    const status = document.getElementById('wbc-status');
    status.textContent = 'Checking eligible countries...';
    fetch(`${API_BASE}/wbc/eligible-countries`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('wbc-countries-card');
        const div = document.getElementById('wbc-countries');
        card.style.display = '';
        let html = '<table class="data-table"><thead><tr><th>#</th><th>Country</th><th>Players</th></tr></thead><tbody>';
        (data.countries || []).forEach((c, i) => {
          html += `<tr><td>${i + 1}</td><td>${c.country}</td><td>${c.player_count}</td></tr>`;
        });
        html += '</tbody></table>';
        div.innerHTML = html;
        status.textContent = `Found ${(data.countries || []).length} eligible countries`;
      }).catch(e => status.textContent = e.message);
  });

  document.getElementById('btn-wbc-create')?.addEventListener('click', () => {
    const lyid = document.getElementById('wbc-lyid').value;
    const status = document.getElementById('wbc-status');
    status.textContent = 'Creating WBC event...';
    fetch(`${API_BASE}/wbc/create`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message}`; return; }
      document.getElementById('wbc-eid').value = data.event_id;
      status.textContent = `Event ${data.event_id} created with ${(data.teams || []).length} teams`;
      loadWbcTeams(data.event_id);
    }).catch(e => status.textContent = e.message);
  });

  function wbcAction(endpoint, method = 'POST') {
    const eid = document.getElementById('wbc-eid').value;
    const status = document.getElementById('wbc-status');
    if (!eid) { status.textContent = 'Enter event ID'; return; }
    status.textContent = 'Processing...';
    fetch(`${API_BASE}/wbc/${eid}/${endpoint}`, {
      method, credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = `Error: ${data.message || data.error}`; return; }
      status.textContent = JSON.stringify(data).substring(0, 200);
      loadWbcTeams(eid);
    }).catch(e => status.textContent = e.message);
  }

  document.getElementById('btn-wbc-rosters')?.addEventListener('click', () => wbcAction('generate-rosters'));
  document.getElementById('btn-wbc-pool-games')?.addEventListener('click', () => wbcAction('generate-pool-games'));
  document.getElementById('btn-wbc-pool-results')?.addEventListener('click', () => wbcAction('process-pool-results'));
  document.getElementById('btn-wbc-knockout')?.addEventListener('click', () => wbcAction('generate-knockout'));
  document.getElementById('btn-wbc-advance')?.addEventListener('click', () => wbcAction('advance-knockout'));
  document.getElementById('btn-wbc-cleanup')?.addEventListener('click', () => wbcAction('cleanup'));
  document.getElementById('btn-wbc-refresh')?.addEventListener('click', () => {
    const eid = document.getElementById('wbc-eid').value;
    if (eid) loadWbcTeams(eid);
  });

  function loadWbcTeams(eventId) {
    fetch(`${API_BASE}/wbc/${eventId}/teams`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('wbc-teams-card');
        const div = document.getElementById('wbc-teams');
        const teams = data.teams || [];
        if (!teams.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        let html = '<table class="data-table"><thead><tr><th>Country</th><th>Code</th><th>Pool</th><th>W</th><th>L</th><th>Status</th></tr></thead><tbody>';
        teams.forEach(t => {
          const elim = t.eliminated ? ' style="opacity:0.4"' : '';
          html += `<tr${elim}><td>${t.country_name}</td><td>${t.country_code}</td><td>${t.pool_group || '-'}</td>
            <td>${t.pool_wins}</td><td>${t.pool_losses}</td>
            <td>${t.eliminated ? '<span class="badge badge-danger">Eliminated</span>' : '<span class="badge badge-success">Active</span>'}</td></tr>`;
        });
        html += '</tbody></table>';
        div.innerHTML = html;
      });
  }

  // ======================================================================
  // Recruiting
  // ======================================================================
  let recStarChart = null;

  function loadRecruitingState() {
    const lyid = document.getElementById('rec-lyid')?.value;
    if (!lyid) return;

    // Load state
    fetch(`${API_BASE}/recruiting/state?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('rec-state-card');
        card.style.display = '';
        const info = document.getElementById('rec-state-info');
        const totalWeeks = data.total_weeks || 20;
        info.innerHTML = `
          <div style="display:flex;gap:24px;flex-wrap:wrap">
            <div><strong>Status:</strong> <span class="badge badge-${data.status === 'active' ? 'success' : data.status === 'complete' ? 'info' : 'warning'}">${data.status || 'pending'}</span></div>
            <div><strong>Current Week:</strong> ${data.current_week || 0} / ${totalWeeks}</div>
          </div>
        `;
      })
      .catch(() => {});

    // Load rankings star distribution
    fetch(`${API_BASE}/recruiting/rankings?league_year_id=${lyid}&per_page=1`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.total > 0) {
          loadStarDistribution(lyid);
        }
      })
      .catch(() => {});

    // Load recent commitments
    fetch(`${API_BASE}/recruiting/commitments?league_year_id=${lyid}&per_page=20`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const container = document.getElementById('rec-commitments-table');
        if (!data.commitments || data.commitments.length === 0) {
          container.innerHTML = '<p style="color:var(--text-secondary)">No commitments yet.</p>';
          return;
        }
        let html = '<table class="data-table"><thead><tr><th>Week</th><th>Player</th><th>Type</th><th>Stars</th><th>School</th><th>Points</th></tr></thead><tbody>';
        data.commitments.forEach(c => {
          const stars = '\u2605'.repeat(c.star_rating) + '\u2606'.repeat(5 - c.star_rating);
          html += `<tr><td>${c.week_committed}</td><td>${c.player_name}</td><td>${c.ptype}</td><td>${stars}</td><td>${c.org_abbrev}</td><td>${c.points_total}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  function loadStarDistribution(lyid) {
    // Fetch counts per star rating
    const promises = [1, 2, 3, 4, 5].map(star =>
      fetch(`${API_BASE}/recruiting/rankings?league_year_id=${lyid}&star_rating=${star}&per_page=1`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => ({ star, count: d.total || 0 }))
    );

    Promise.all(promises).then(results => {
      const labels = results.map(r => r.star + '\u2605');
      const counts = results.map(r => r.count);
      const canvas = document.getElementById('rec-star-chart');
      if (!canvas) return;

      if (recStarChart) recStarChart.destroy();

      recStarChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Players',
            data: counts,
            backgroundColor: ['#6b7280', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444'],
          }],
        },
        options: {
          responsive: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { color: '#9ca3af' }, grid: { color: '#374151' } },
            x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
          },
        },
      });
    });
  }

  // Compute Rankings button
  document.getElementById('btn-rec-compute')?.addEventListener('click', () => {
    const lyid = document.getElementById('rec-lyid').value;
    if (!lyid) return;
    const status = document.getElementById('rec-status');
    status.textContent = 'Computing rankings...';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/recruiting/advance-week`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.message || 'Error';
          status.className = 'status-msg error';
        } else {
          const msg = data.ranked_players
            ? `Ranked ${data.ranked_players} players. Status: ${data.status}`
            : `Week ${data.new_week}: ${(data.commitments || []).length} commitments, ${data.uncommitted_count || 0} uncommitted. Status: ${data.status}`;
          status.textContent = msg;
          status.className = 'status-msg success';
          loadRecruitingState();
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // Advance Week button
  document.getElementById('btn-rec-advance')?.addEventListener('click', () => {
    const lyid = document.getElementById('rec-lyid').value;
    if (!lyid) return;
    const status = document.getElementById('rec-status');
    status.textContent = 'Advancing week...';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/recruiting/advance-week`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.message || 'Error';
          status.className = 'status-msg error';
        } else {
          let msg = `Advanced to week ${data.new_week}. Status: ${data.status}.`;
          const commits = (data.commitments || []).length + (data.cleanup_commitments || []).length;
          if (commits > 0) msg += ` ${commits} new commitments.`;
          if (data.leftovers !== undefined) msg += ` ${data.leftovers} leftovers.`;
          status.textContent = msg;
          status.className = 'status-msg success';
          loadRecruitingState();
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // Regenerate Stars button
  document.getElementById('btn-rec-regenerate')?.addEventListener('click', () => {
    const lyid = document.getElementById('rec-lyid').value;
    if (!lyid) return;
    const status = document.getElementById('rec-status');
    status.textContent = 'Regenerating star rankings...';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/recruiting/rankings/regenerate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.message || 'Error';
          status.className = 'status-msg error';
        } else {
          status.textContent = `Regenerated stars for ${data.ranked_players} players.`;
          status.className = 'status-msg success';
          loadRecruitingState();
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // Wipe Stars button
  document.getElementById('btn-rec-wipe')?.addEventListener('click', () => {
    const lyid = document.getElementById('rec-lyid').value;
    if (!lyid) return;
    if (!confirm('Wipe all star rankings for this league year? This cannot be undone.')) return;
    const status = document.getElementById('rec-status');
    status.textContent = 'Wiping star rankings...';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/recruiting/rankings/wipe`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.message || 'Error';
          status.className = 'status-msg error';
        } else {
          status.textContent = `Wiped ${data.deleted} star rankings.`;
          status.className = 'status-msg success';
          loadRecruitingState();
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // Refresh button
  document.getElementById('btn-rec-refresh')?.addEventListener('click', () => {
    loadRecruitingState();
  });

  // Re-load state when league year changes
  document.getElementById('rec-lyid')?.addEventListener('change', () => {
    loadRecruitingState();
  });

  // ======================================================================
  // Recruiting Admin
  // ======================================================================
  let radmWeeklyChart = null;
  let radmPaceChart = null;
  let radmOrgDetailChart = null;

  function radmLyid() { return document.getElementById('radm-lyid')?.value; }

  function loadRecruitingAdmin() {
    const lyid = radmLyid();
    if (!lyid) return;
    const status = document.getElementById('radm-status');
    status.textContent = 'Loading…';
    status.className = 'status-msg info';

    // Load summary report
    fetch(`${API_BASE}/recruiting/admin/report/summary?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.error) { status.textContent = data.message; status.className = 'status-msg error'; return; }
        status.textContent = '';
        status.className = '';

        // State card
        const stateCard = document.getElementById('radm-state-card');
        stateCard.style.display = '';
        document.getElementById('radm-state-info').innerHTML =
          `<span class="badge badge-${data.status === 'active' ? 'success' : data.status === 'complete' ? 'info' : 'warning'}">${data.status}</span> ` +
          `Week <strong>${data.current_week}</strong> &mdash; ` +
          `Pool: ${data.pool_size} &bull; Committed: ${data.committed_count} &bull; Remaining: ${data.uncommitted_count}`;

        // Wipe card
        document.getElementById('radm-wipe-card').style.display = '';

        // Summary grid
        const summCard = document.getElementById('radm-summary-card');
        summCard.style.display = '';
        const grid = document.getElementById('radm-summary-grid');
        const stats = [
          ['Active Orgs', data.active_orgs],
          ['Players Targeted', data.targeted_players],
          ['Total Points', data.total_points_invested.toLocaleString()],
          ['Total Allocations', data.total_allocations.toLocaleString()],
          ['Commitments', data.committed_count],
          ['Unique Orgs Committing', data.unique_orgs_committing],
          ['Avg Winning Points', data.avg_winning_points],
        ];
        grid.innerHTML = stats.map(([label, val]) =>
          `<div style="background:var(--bg-dark);padding:12px;border-radius:6px;text-align:center">
            <div style="font-size:1.4em;font-weight:bold;color:var(--accent)">${val}</div>
            <div style="font-size:.85em;color:var(--text-secondary)">${label}</div>
          </div>`
        ).join('');

        // Star distribution in summary
        const starDist = data.star_distribution || {};
        const commitByStar = data.committed_by_star || {};
        if (Object.keys(starDist).length) {
          let starHtml = '<div style="margin-top:12px"><h5>Star Distribution (Pool / Committed)</h5><table class="data-table"><thead><tr><th>Stars</th><th>Pool</th><th>Committed</th><th>%</th></tr></thead><tbody>';
          for (let s = 5; s >= 1; s--) {
            const pool = starDist[s] || 0;
            const comm = commitByStar[s] || 0;
            const pct = pool > 0 ? Math.round(comm / pool * 100) : 0;
            starHtml += `<tr><td>${'★'.repeat(s)}</td><td>${pool}</td><td>${comm}</td><td>${pct}%</td></tr>`;
          }
          starHtml += '</tbody></table></div>';
          grid.innerHTML += starHtml;
        }

        // Weekly trend chart
        const weeks = data.weekly_trend || [];
        if (weeks.length) {
          if (radmWeeklyChart) radmWeeklyChart.destroy();
          radmWeeklyChart = new Chart(document.getElementById('radm-weekly-chart'), {
            type: 'bar',
            data: {
              labels: weeks.map(w => `Wk ${w.week}`),
              datasets: [
                { label: 'Points Spent', data: weeks.map(w => w.points_spent), backgroundColor: 'rgba(54,162,235,.7)' },
                { label: 'Active Orgs', data: weeks.map(w => w.active_orgs), type: 'line', borderColor: '#ff9f40', yAxisID: 'y1', fill: false },
              ]
            },
            options: {
              responsive: true,
              plugins: { legend: { labels: { color: '#ccc' } } },
              scales: {
                x: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.05)' } },
                y: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.08)' }, title: { display: true, text: 'Points', color: '#aaa' } },
                y1: { position: 'right', ticks: { color: '#aaa' }, grid: { drawOnChartArea: false }, title: { display: true, text: 'Orgs', color: '#aaa' } },
              }
            }
          });
        }

        // Commitment pace chart
        const pace = data.commitment_pace || [];
        if (pace.length) {
          if (radmPaceChart) radmPaceChart.destroy();
          let cumulative = 0;
          const cumData = pace.map(p => { cumulative += p.commitments; return cumulative; });
          radmPaceChart = new Chart(document.getElementById('radm-pace-chart'), {
            type: 'line',
            data: {
              labels: pace.map(p => `Wk ${p.week}`),
              datasets: [
                { label: 'Per Week', data: pace.map(p => p.commitments), backgroundColor: 'rgba(75,192,192,.5)', type: 'bar' },
                { label: 'Cumulative', data: cumData, borderColor: '#ff6384', fill: false },
              ]
            },
            options: {
              responsive: true,
              plugins: { legend: { labels: { color: '#ccc' } } },
              scales: {
                x: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.05)' } },
                y: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.08)' } },
              }
            }
          });
        }

        // Load leaderboard + demand
        loadRadmLeaderboard();
        loadRadmDemand();
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  }

  function loadRadmLeaderboard() {
    const lyid = radmLyid();
    if (!lyid) return;
    fetch(`${API_BASE}/recruiting/admin/report/org-leaderboard?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.error) return;
        const card = document.getElementById('radm-leaderboard-card');
        card.style.display = '';
        const container = document.getElementById('radm-leaderboard-table');
        if (!data.orgs || !data.orgs.length) { container.innerHTML = '<p style="color:var(--text-secondary)">No investment activity yet.</p>'; return; }
        let html = '<table class="data-table"><thead><tr><th>Org</th><th>Points</th><th>Players</th><th>Weeks</th><th>Util%</th><th>Commits</th><th>Elite</th><th>Avg★</th></tr></thead><tbody>';
        data.orgs.forEach(o => {
          html += `<tr style="cursor:pointer" data-org="${o.org_id}">
            <td>${o.org_abbrev}</td><td>${o.total_points.toLocaleString()}</td><td>${o.players_targeted}</td>
            <td>${o.weeks_active}</td><td>${o.budget_utilization_pct}%</td>
            <td>${o.commitments}</td><td>${o.elite_commitments}</td><td>${o.avg_commit_star}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;

        // Click to drill into org detail
        container.querySelectorAll('tr[data-org]').forEach(tr => {
          tr.addEventListener('click', () => loadRadmOrgDetail(parseInt(tr.dataset.org)));
        });
      });
  }

  function loadRadmDemand() {
    const lyid = radmLyid();
    if (!lyid) return;
    const star = document.getElementById('radm-demand-star')?.value || '';
    const limit = document.getElementById('radm-demand-limit')?.value || 50;
    let url = `${API_BASE}/recruiting/admin/report/player-demand?league_year_id=${lyid}&limit=${limit}`;
    if (star) url += `&star_rating=${star}`;
    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.error) return;
        const card = document.getElementById('radm-demand-card');
        card.style.display = '';
        const container = document.getElementById('radm-demand-table');
        if (!data.players || !data.players.length) { container.innerHTML = '<p style="color:var(--text-secondary)">No investment activity yet.</p>'; return; }
        let html = '<table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>★</th><th>Rank</th><th>Orgs</th><th>Interest</th><th>Last Wk</th><th>Status</th></tr></thead><tbody>';
        data.players.forEach(p => {
          const statusBadge = p.status === 'committed'
            ? `<span class="badge badge-success">${p.committed_to?.org_abbrev || 'committed'}</span>`
            : '<span class="badge badge-warning">open</span>';
          html += `<tr><td>${p.player_name}</td><td>${p.ptype}</td><td>${p.star_rating ?? '-'}</td>
            <td>${p.rank_overall ?? '-'}</td><td>${p.num_orgs}</td><td>${p.total_interest.toLocaleString()}</td>
            <td>${p.last_active_week}</td><td>${statusBadge}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      });
  }

  function loadRadmOrgDetail(orgId) {
    const lyid = radmLyid();
    if (!lyid) return;
    fetch(`${API_BASE}/recruiting/admin/report/org-detail/${orgId}?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.error) return;
        const card = document.getElementById('radm-orgdetail-card');
        card.style.display = '';
        card.scrollIntoView({ behavior: 'smooth' });
        document.getElementById('radm-orgdetail-title').textContent = `${data.org_abbrev} (Org ${data.org_id}) — Total: ${data.total_invested.toLocaleString()} pts`;

        // Weekly spend chart
        const ws = data.weekly_spend || [];
        if (ws.length) {
          if (radmOrgDetailChart) radmOrgDetailChart.destroy();
          radmOrgDetailChart = new Chart(document.getElementById('radm-orgdetail-chart'), {
            type: 'bar',
            data: {
              labels: ws.map(w => `Wk ${w.week}`),
              datasets: [{ label: 'Points', data: ws.map(w => w.points_spent), backgroundColor: 'rgba(54,162,235,.7)' }]
            },
            options: {
              responsive: true,
              plugins: { legend: { display: false } },
              scales: {
                x: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.05)' } },
                y: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,.08)' }, max: 100 },
              }
            }
          });
        }

        // Commitments won
        const commDiv = document.getElementById('radm-orgdetail-commits');
        if (data.commitments_won.length) {
          let chtml = '<table class="data-table"><thead><tr><th>Player</th><th>★</th><th>Week</th><th>Points</th></tr></thead><tbody>';
          data.commitments_won.forEach(c => {
            chtml += `<tr><td>${c.player_name}</td><td>${c.star_rating}</td><td>${c.week_committed}</td><td>${c.points_total}</td></tr>`;
          });
          chtml += '</tbody></table>';
          commDiv.innerHTML = chtml;
        } else {
          commDiv.innerHTML = '<p style="color:var(--text-secondary)">No commitments won yet.</p>';
        }

        // All invested players
        const plDiv = document.getElementById('radm-orgdetail-players');
        if (data.invested_players.length) {
          let phtml = '<table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>★</th><th>Invested</th><th>Outcome</th></tr></thead><tbody>';
          data.invested_players.forEach(p => {
            let badge = '';
            if (p.outcome === 'won') badge = '<span class="badge badge-success">Won</span>';
            else if (p.outcome === 'lost') badge = `<span class="badge badge-danger">Lost → ${p.committed_to}</span>`;
            else badge = '<span class="badge badge-warning">Active</span>';
            phtml += `<tr><td>${p.player_name}</td><td>${p.ptype}</td><td>${p.star_rating ?? '-'}</td><td>${p.total_invested}</td><td>${badge}</td></tr>`;
          });
          phtml += '</tbody></table>';
          plDiv.innerHTML = phtml;
        } else {
          plDiv.innerHTML = '<p style="color:var(--text-secondary)">No investments.</p>';
        }
      });
  }

  // Admin action helpers
  function radmPost(endpoint, extraBody, successMsg) {
    const lyid = radmLyid();
    if (!lyid) return;
    const status = document.getElementById('radm-status');
    status.textContent = 'Processing…';
    status.className = 'status-msg info';
    const body = { league_year_id: parseInt(lyid), ...extraBody };
    fetch(`${API_BASE}/recruiting/admin/${endpoint}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.message;
          status.className = 'status-msg error';
        } else {
          status.textContent = typeof successMsg === 'function' ? successMsg(data) : successMsg;
          status.className = 'status-msg success';
          loadRecruitingAdmin();
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  }

  function radmWipePost(endpoint, successMsg) {
    const lyid = radmLyid();
    if (!lyid) return;
    const wipeStatus = document.getElementById('radm-wipe-status');
    const orgVal = document.getElementById('radm-wipe-org')?.value;
    const playerVal = document.getElementById('radm-wipe-player')?.value;
    const body = { league_year_id: parseInt(lyid) };
    if (orgVal) body.org_id = parseInt(orgVal);
    if (playerVal) body.player_id = parseInt(playerVal);

    wipeStatus.textContent = 'Processing…';
    wipeStatus.className = 'status-msg info';
    fetch(`${API_BASE}/recruiting/admin/${endpoint}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          wipeStatus.textContent = data.message;
          wipeStatus.className = 'status-msg error';
        } else {
          wipeStatus.textContent = `${successMsg}: ${data.deleted} rows (scope: ${data.scope})`;
          wipeStatus.className = 'status-msg success';
          loadRecruitingAdmin();
        }
      })
      .catch(e => { wipeStatus.textContent = e.message; wipeStatus.className = 'status-msg error'; });
  }

  // Button handlers
  document.getElementById('btn-radm-refresh')?.addEventListener('click', loadRecruitingAdmin);

  document.getElementById('radm-lyid')?.addEventListener('change', loadRecruitingAdmin);

  document.getElementById('btn-radm-reset-week')?.addEventListener('click', () => {
    const week = parseInt(document.getElementById('radm-target-week')?.value || 1);
    if (!confirm(`Reset recruiting to week ${week}? This does NOT wipe investments or commitments.`)) return;
    radmPost('reset-week', { target_week: week }, d => `Reset to week ${d.current_week} (${d.status})`);
  });

  document.getElementById('btn-radm-full-reset')?.addEventListener('click', () => {
    if (!confirm('Full reset: wipe all investments, commitments, and boards? Rankings are preserved.')) return;
    radmPost('full-reset', {}, d => {
      const parts = Object.entries(d.deleted).filter(([k]) => k !== 'state_reset').map(([k, v]) => `${k}: ${v}`);
      return `Full reset complete. ${parts.join(', ')}`;
    });
  });

  document.getElementById('btn-radm-wipe-investments')?.addEventListener('click', () => {
    if (!confirm('Wipe investments with the selected scope?')) return;
    radmWipePost('wipe-investments', 'Investments wiped');
  });

  document.getElementById('btn-radm-wipe-commitments')?.addEventListener('click', () => {
    if (!confirm('Wipe commitments with the selected scope?')) return;
    radmWipePost('wipe-commitments', 'Commitments wiped');
  });

  document.getElementById('btn-radm-wipe-boards')?.addEventListener('click', () => {
    if (!confirm('Wipe boards with the selected scope?')) return;
    radmWipePost('wipe-boards', 'Boards wiped');
  });

  // Re-filter demand on filter change
  document.getElementById('radm-demand-star')?.addEventListener('change', loadRadmDemand);
  document.getElementById('radm-demand-limit')?.addEventListener('change', loadRadmDemand);

  // ======================================================================
  // Draft Administration
  // ======================================================================

  function dftLyid() { return document.getElementById('dft-lyid')?.value; }
  const dftFmt = v => '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

  // --- Phase badge helpers ---
  const DFT_PHASE_BADGE = {
    SETUP: 'warning', IN_PROGRESS: 'running', PAUSED: 'info',
    SIGNING: 'primary', COMPLETE: 'success',
  };

  function loadDraftAdmin() {
    const lyid = dftLyid();
    if (!lyid) return;
    const status = document.getElementById('dft-status');
    status.textContent = 'Loading\u2026';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/draft/state?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(state => {
        if (state.error) {
          // No draft exists yet — show init card
          status.textContent = '';
          status.className = '';
          document.getElementById('dft-state-card').style.display = 'none';
          document.getElementById('dft-init-card').style.display = '';
          document.getElementById('dft-round-mode-card').style.display = 'none';
          document.getElementById('dft-board-card').style.display = 'none';
          document.getElementById('dft-override-card').style.display = 'none';
          document.getElementById('dft-signing-card').style.display = 'none';
          return;
        }
        status.textContent = '';
        status.className = '';
        document.getElementById('dft-init-card').style.display = 'none';
        document.getElementById('dft-state-card').style.display = '';

        // State info
        const badgeCls = DFT_PHASE_BADGE[state.phase] || 'pending';
        let info = `<span class="badge badge-${badgeCls}">${state.phase}</span> `;
        info += `Round <strong>${state.current_round}</strong> / ${state.total_rounds}`;
        info += ` &mdash; Pick <strong>${state.current_pick}</strong> / ${state.picks_per_round}`;
        if (state.seconds_remaining != null && state.phase === 'IN_PROGRESS') {
          info += ` &mdash; <strong>${state.seconds_remaining}s</strong> remaining`;
        }
        if (state.current_round_mode === 'auto') {
          info += ' &mdash; <span class="badge badge-pending">AUTO ROUND</span>';
        }
        if (state.auto_rounds_locked) {
          info += ' &mdash; <span class="badge badge-info">PREFS LOCKED</span>';
        }
        document.getElementById('dft-state-info').innerHTML = info;

        // Phase-dependent action buttons
        renderDftActions(state);

        // Load round strip
        loadDftRoundStrip(lyid, state);

        // Show round mode editor during SETUP
        if (state.phase === 'SETUP') {
          document.getElementById('dft-round-mode-card').style.display = '';
        } else {
          document.getElementById('dft-round-mode-card').style.display = 'none';
        }

        // Show override card when draft is in progress or signing
        if (['IN_PROGRESS', 'PAUSED', 'SIGNING'].includes(state.phase)) {
          document.getElementById('dft-override-card').style.display = '';
        } else {
          document.getElementById('dft-override-card').style.display = 'none';
        }

        // Load board if draft has started
        if (state.phase !== 'SETUP') {
          loadDftBoard(lyid, state);
        } else {
          document.getElementById('dft-board-card').style.display = 'none';
        }

        // Show signing card during SIGNING phase
        if (state.phase === 'SIGNING') {
          document.getElementById('dft-signing-card').style.display = '';
          loadDftSigningTable(lyid);
        } else {
          document.getElementById('dft-signing-card').style.display = 'none';
        }
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  }

  function renderDftActions(state) {
    const container = document.getElementById('dft-actions');
    let html = '';
    const btn = (id, label, cls) => `<button id="${id}" class="btn ${cls}">${label}</button>`;

    switch (state.phase) {
      case 'SETUP':
        html = btn('btn-dft-start', 'Start Draft', 'btn-primary');
        break;
      case 'IN_PROGRESS':
        html = btn('btn-dft-pause', 'Pause', 'btn-warning');
        html += btn('btn-dft-reset-timer', 'Reset Timer', 'btn-secondary');
        if (state.current_round_mode === 'auto') {
          html += btn('btn-dft-run-auto', 'Run Auto Rounds', 'btn-primary');
        }
        html += btn('btn-dft-advance-signing', 'Advance to Signing', 'btn-secondary');
        break;
      case 'PAUSED':
        html = btn('btn-dft-resume', 'Resume', 'btn-primary');
        html += btn('btn-dft-advance-signing', 'Advance to Signing', 'btn-secondary');
        break;
      case 'SIGNING':
        html = btn('btn-dft-export', 'Export Draft', 'btn-warning');
        html += btn('btn-dft-complete', 'Complete Draft', 'btn-secondary');
        break;
    }
    container.innerHTML = html;

    // Wire up action buttons
    document.getElementById('btn-dft-start')?.addEventListener('click', () => dftAdminPost('start', 'Draft started'));
    document.getElementById('btn-dft-pause')?.addEventListener('click', () => dftAdminPost('pause', 'Draft paused'));
    document.getElementById('btn-dft-resume')?.addEventListener('click', () => dftAdminPost('resume', 'Draft resumed'));
    document.getElementById('btn-dft-reset-timer')?.addEventListener('click', () => dftAdminPost('reset-timer', 'Timer reset'));
    document.getElementById('btn-dft-advance-signing')?.addEventListener('click', () => {
      if (!confirm('Advance to signing phase? No more picks can be made.')) return;
      dftAdminPost('advance-signing', 'Advanced to signing');
    });
    document.getElementById('btn-dft-export')?.addEventListener('click', () => {
      if (!confirm('Export draft? This moves signed players to their drafting orgs.')) return;
      dftAdminPost('export', 'Draft exported');
    });
    document.getElementById('btn-dft-complete')?.addEventListener('click', () => {
      if (!confirm('Mark draft as complete?')) return;
      dftAdminPost('complete', 'Draft completed');
    });
    document.getElementById('btn-dft-run-auto')?.addEventListener('click', () => {
      if (!confirm('Run all auto rounds? This will execute all remaining auto-round picks.')) return;
      const status = document.getElementById('dft-status');
      status.textContent = 'Running auto rounds\u2026 (this may take a moment)';
      status.className = 'status-msg info';
      fetch(`${API_BASE}/draft/admin/run-auto-rounds`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league_year_id: parseInt(dftLyid()) }),
      }).then(r => r.json()).then(data => {
        if (data.error) { status.textContent = data.message || data.error; status.className = 'status-msg error'; return; }
        status.textContent = `Auto rounds complete \u2014 ${data.picks_made} picks made`;
        status.className = 'status-msg success';
        loadDraftAdmin();
      }).catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
    });
  }

  function dftAdminPost(action, successMsg) {
    const lyid = dftLyid();
    if (!lyid) return;
    const status = document.getElementById('dft-status');
    status.textContent = 'Processing\u2026';
    status.className = 'status-msg info';
    fetch(`${API_BASE}/draft/admin/${action}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = data.message || data.error; status.className = 'status-msg error'; return; }
      status.textContent = successMsg;
      status.className = 'status-msg success';
      loadDraftAdmin();
    }).catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  }

  // --- Round strip & mode editor ---

  function loadDftRoundStrip(lyid, state) {
    fetch(`${API_BASE}/draft/round-modes?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const rounds = data.rounds || [];
        // Top-level read-only strip
        const strip = document.getElementById('dft-round-strip');
        strip.innerHTML = rounds.map(r => {
          const isCurrent = r.round === state.current_round && state.phase === 'IN_PROGRESS';
          const cls = r.mode === 'live' ? 'badge-primary' : 'badge-pending';
          const border = isCurrent ? 'border:2px solid var(--success);' : '';
          return `<span class="badge ${cls}" style="cursor:default;${border}">R${r.round}</span>`;
        }).join('');

        // Editable grid (SETUP phase)
        if (state.phase === 'SETUP') {
          const grid = document.getElementById('dft-round-mode-grid');
          grid.innerHTML = rounds.map(r => {
            const cls = r.mode === 'live' ? 'btn-primary' : 'btn-secondary';
            return `<button class="btn btn-sm ${cls}" data-round="${r.round}" data-mode="${r.mode}" style="min-width:52px">R${r.round}</button>`;
          }).join('');
          // Toggle on click
          grid.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
              const rnd = btn.dataset.round;
              const newMode = btn.dataset.mode === 'live' ? 'auto' : 'live';
              const modeStatus = document.getElementById('dft-round-mode-status');
              fetch(`${API_BASE}/draft/admin/round-modes`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ league_year_id: parseInt(lyid), round_modes: { [rnd]: newMode } }),
              }).then(r => r.json()).then(data => {
                if (data.error) { modeStatus.textContent = data.message || data.error; modeStatus.className = 'status-msg error'; return; }
                btn.dataset.mode = newMode;
                btn.className = `btn btn-sm ${newMode === 'live' ? 'btn-primary' : 'btn-secondary'}`;
                modeStatus.textContent = `Round ${rnd} set to ${newMode.toUpperCase()}`;
                modeStatus.className = 'status-msg success';
                // Also update the read-only strip
                loadDftRoundStrip(lyid, state);
              }).catch(e => { modeStatus.textContent = e.message; modeStatus.className = 'status-msg error'; });
            });
          });
        }
      })
      .catch(() => {});
  }

  // --- Draft board ---

  function loadDftBoard(lyid, state) {
    document.getElementById('dft-board-card').style.display = '';
    fetch(`${API_BASE}/draft/board?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const picks = data.picks || [];
        if (!picks.length) return;

        // Populate round filter
        const maxRound = Math.max(...picks.map(p => p.round));
        const roundFilter = document.getElementById('dft-board-round-filter');
        if (roundFilter.options.length <= 1) {
          for (let r = 1; r <= maxRound; r++) {
            const o = document.createElement('option');
            o.value = r;
            o.textContent = `Round ${r}`;
            roundFilter.appendChild(o);
          }
        }

        renderDftBoard(picks, state);
      })
      .catch(() => {});
  }

  function renderDftBoard(picks, state) {
    const filterRound = document.getElementById('dft-board-round-filter')?.value;
    const filtered = filterRound ? picks.filter(p => p.round === parseInt(filterRound)) : picks;

    const container = document.getElementById('dft-board-table');
    let html = '<table class="data-table"><thead><tr>';
    html += '<th>Pick ID</th><th>Rd</th><th>Pick</th><th>Overall</th><th>Org</th>';
    html += '<th>Player</th><th>Picked At</th><th>Auto</th><th>Slot Value</th><th>Sign Status</th>';
    html += '</tr></thead><tbody>';

    filtered.forEach(p => {
      const isCurrent = p.round === state.current_round && p.pick_in_round === state.current_pick && state.phase === 'IN_PROGRESS';
      const rowStyle = isCurrent ? ' style="background:rgba(59,130,246,0.15)"' : '';
      const traded = p.current_org_id !== p.original_org_id ? ` <span style="color:var(--warning);font-size:0.75rem">(from ${p.original_org_id})</span>` : '';
      const autoIcon = p.is_auto_pick ? '\u2699' : '';
      const signBadge = p.sign_status ? `<span class="badge badge-${p.sign_status === 'signed' ? 'success' : p.sign_status === 'pending' ? 'warning' : 'danger'}">${p.sign_status}</span>` : '\u2014';

      html += `<tr${rowStyle}>`;
      html += `<td>${p.pick_id}</td>`;
      html += `<td>${p.round}</td>`;
      html += `<td>${p.pick_in_round}</td>`;
      html += `<td>${p.overall_pick}</td>`;
      html += `<td>${p.current_org_id}${traded}</td>`;
      html += `<td>${p.player_name || '<span style="color:var(--text-muted)">\u2014</span>'}</td>`;
      html += `<td>${p.picked_at ? new Date(p.picked_at).toLocaleTimeString() : '\u2014'}</td>`;
      html += `<td>${autoIcon}</td>`;
      html += `<td>${p.slot_value != null ? dftFmt(p.slot_value) : '\u2014'}</td>`;
      html += `<td>${signBadge}</td>`;
      html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;

    // Store picks for board filter re-render
    container._allPicks = picks;
    container._state = state;
  }

  // --- Signing table ---

  function loadDftSigningTable(lyid) {
    fetch(`${API_BASE}/draft/board?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const picks = (data.picks || []).filter(p => p.player_id != null);
        const filterStatus = document.getElementById('dft-sign-filter')?.value;
        const filtered = filterStatus ? picks.filter(p => p.sign_status === filterStatus) : picks;

        const container = document.getElementById('dft-signing-table');
        let html = '<table class="data-table"><thead><tr>';
        html += '<th>Pick ID</th><th>Rd</th><th>Pick</th><th>Org</th><th>Player</th>';
        html += '<th>Slot Value</th><th>Status</th><th>Actions</th>';
        html += '</tr></thead><tbody>';

        filtered.forEach(p => {
          const signBadge = `<span class="badge badge-${p.sign_status === 'signed' ? 'success' : p.sign_status === 'pending' ? 'warning' : 'danger'}">${p.sign_status}</span>`;
          const actions = p.sign_status === 'pending'
            ? `<button class="btn btn-sm btn-primary" onclick="window._dftSign(${p.pick_id})">Sign</button> <button class="btn btn-sm btn-secondary" onclick="window._dftPass(${p.pick_id})">Pass</button>`
            : '\u2014';

          html += `<tr>`;
          html += `<td>${p.pick_id}</td><td>${p.round}</td><td>${p.pick_in_round}</td>`;
          html += `<td>${p.current_org_id}</td><td>${p.player_name}</td>`;
          html += `<td>${dftFmt(p.slot_value)}</td><td>${signBadge}</td>`;
          html += `<td>${actions}</td></tr>`;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  // Global handlers for inline sign/pass buttons
  window._dftSign = function(pickId) {
    const lyid = dftLyid();
    if (!lyid || !confirm(`Sign pick ${pickId}?`)) return;
    fetch(`${API_BASE}/draft/sign/${pickId}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    }).then(r => r.json()).then(data => {
      const status = document.getElementById('dft-status');
      if (data.error) { status.textContent = data.message || data.error; status.className = 'status-msg error'; return; }
      status.textContent = `Signed ${data.player_name} \u2014 ${data.years}yr / ${dftFmt(data.slot_value)}`;
      status.className = 'status-msg success';
      loadDftSigningTable(lyid);
    }).catch(e => { document.getElementById('dft-status').textContent = e.message; });
  };

  window._dftPass = function(pickId) {
    if (!confirm(`Pass on pick ${pickId}?`)) return;
    fetch(`${API_BASE}/draft/pass/${pickId}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    }).then(r => r.json()).then(data => {
      const status = document.getElementById('dft-status');
      if (data.error) { status.textContent = data.message || data.error; status.className = 'status-msg error'; return; }
      status.textContent = `Passed on pick ${pickId}`;
      status.className = 'status-msg success';
      loadDftSigningTable(dftLyid());
    }).catch(e => { document.getElementById('dft-status').textContent = e.message; });
  };

  // --- Event Listeners ---

  document.getElementById('btn-dft-refresh')?.addEventListener('click', loadDraftAdmin);
  document.getElementById('dft-lyid')?.addEventListener('change', loadDraftAdmin);

  document.getElementById('dft-board-round-filter')?.addEventListener('change', () => {
    const container = document.getElementById('dft-board-table');
    if (container._allPicks) renderDftBoard(container._allPicks, container._state);
  });

  document.getElementById('dft-sign-filter')?.addEventListener('change', () => {
    const lyid = dftLyid();
    if (lyid) loadDftSigningTable(lyid);
  });

  // Initialize draft
  document.getElementById('btn-dft-initialize')?.addEventListener('click', () => {
    const lyid = dftLyid();
    if (!lyid) return;
    const status = document.getElementById('dft-status');
    const liveStr = document.getElementById('dft-live-rounds').value;
    const liveRounds = liveStr.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));

    status.textContent = 'Initializing draft\u2026';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/draft/admin/initialize`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(lyid),
        total_rounds: parseInt(document.getElementById('dft-total-rounds').value),
        seconds_per_pick: parseInt(document.getElementById('dft-seconds-per-pick').value),
        is_snake: document.getElementById('dft-snake').value === 'true',
        live_rounds: liveRounds,
      }),
    }).then(r => r.json()).then(data => {
      if (data.error) { status.textContent = data.message || data.error; status.className = 'status-msg error'; return; }
      status.textContent = `Draft initialized \u2014 ${data.total_picks} picks, ${data.eligible_players} eligible players`;
      status.className = 'status-msg success';
      loadDraftAdmin();
    }).catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // Set pick override
  document.getElementById('btn-dft-set-pick')?.addEventListener('click', () => {
    const lyid = dftLyid();
    if (!lyid) return;
    const round = document.getElementById('dft-set-round').value;
    const pick = document.getElementById('dft-set-pick').value;
    const playerId = document.getElementById('dft-set-player').value;
    if (!round || !pick || !playerId) { alert('Fill in round, pick, and player ID'); return; }
    if (!confirm(`Assign player ${playerId} to R${round}P${pick}?`)) return;

    const overrideStatus = document.getElementById('dft-override-status');
    fetch(`${API_BASE}/draft/admin/set-pick`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_year_id: parseInt(lyid),
        round: parseInt(round),
        pick_in_round: parseInt(pick),
        player_id: parseInt(playerId),
      }),
    }).then(r => r.json()).then(data => {
      if (data.error) { overrideStatus.textContent = data.message || data.error; overrideStatus.className = 'status-msg error'; return; }
      overrideStatus.textContent = `Pick assigned: player ${data.player_id} to pick ${data.pick_id}`;
      overrideStatus.className = 'status-msg success';
      loadDraftAdmin();
    }).catch(e => { overrideStatus.textContent = e.message; overrideStatus.className = 'status-msg error'; });
  });

  // Remove pick (rollback)
  document.getElementById('btn-dft-remove-pick')?.addEventListener('click', () => {
    const pickId = document.getElementById('dft-remove-pick-id').value;
    if (!pickId) { alert('Enter a draft pick ID'); return; }
    if (!confirm(`Rollback pick ${pickId}? This will clear the player assignment and reset signing status to pending.`)) return;

    const overrideStatus = document.getElementById('dft-override-status');
    fetch(`${API_BASE}/draft/admin/remove-pick`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft_pick_id: parseInt(pickId) }),
    }).then(r => r.json()).then(data => {
      if (data.error) { overrideStatus.textContent = data.message || data.error; overrideStatus.className = 'status-msg error'; return; }
      overrideStatus.textContent = `Pick ${pickId} rolled back successfully`;
      overrideStatus.className = 'status-msg success';
      loadDraftAdmin();
    }).catch(e => { overrideStatus.textContent = e.message; overrideStatus.className = 'status-msg error'; });
  });

  // ======================================================================
  // IFA Administration
  // ======================================================================

  function ifaLyid() { return document.getElementById('ifa-lyid')?.value; }

  function loadIfaAdmin() {
    const lyid = ifaLyid();
    if (!lyid) return;
    const status = document.getElementById('ifa-status');
    status.textContent = 'Loading\u2026';
    status.className = 'status-msg info';

    // Load state first, then conditionally load the rest
    fetch(`${API_BASE}/ifa/state?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(state => {
        if (state.error) { status.textContent = state.error; status.className = 'status-msg error'; return; }
        status.textContent = '';
        status.className = '';

        // State card
        const stateCard = document.getElementById('ifa-state-card');
        stateCard.style.display = '';
        const badgeClass = state.status === 'active' ? 'success' : state.status === 'complete' ? 'info' : 'warning';
        const advBtn = document.getElementById('btn-ifa-advance-week');
        advBtn.disabled = state.status === 'complete';
        advBtn.textContent = state.current_week === 0 ? 'Initialize Window (Week 0 \u2192 1)' : `Advance to Week ${state.current_week + 1}`;
        if (state.status === 'complete') advBtn.textContent = 'Window Complete';

        document.getElementById('ifa-state-info').innerHTML =
          `<span class="badge badge-${badgeClass}">${state.status}</span> ` +
          `Week <strong>${state.current_week}</strong> / ${state.total_weeks}`;

        // Load pools, board, eligible, and history
        loadIfaPools(lyid);
        loadIfaActiveAuctions(lyid);
        loadIfaEligible(lyid);
        loadIfaHistory(lyid);
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  }

  function loadIfaPools(lyid) {
    fetch(`${API_BASE}/ifa/pools?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(pools => {
        const card = document.getElementById('ifa-pools-card');
        if (!pools || !pools.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        const container = document.getElementById('ifa-pools-table');
        const fmt = v => '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
        let html = '<table class="data-table"><thead><tr><th>Rank</th><th>Org</th><th>Total Pool</th><th>Spent</th><th>Committed</th><th>Remaining</th></tr></thead><tbody>';
        pools.forEach(p => {
          const pct = p.total_pool > 0 ? Math.round((p.spent + p.committed) / p.total_pool * 100) : 0;
          const rowClass = pct >= 90 ? 'style="color:var(--danger)"' : pct >= 70 ? 'style="color:var(--warning)"' : '';
          html += `<tr ${rowClass}><td>${p.standing_rank}</td><td>${p.team_abbrev}</td><td>${fmt(p.total_pool)}</td><td>${fmt(p.spent)}</td><td>${fmt(p.committed)}</td><td>${fmt(p.remaining)}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  function loadIfaActiveAuctions(lyid) {
    fetch(`${API_BASE}/ifa/board?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const card = document.getElementById('ifa-auctions-card');
        const auctions = data.auctions || [];
        if (!auctions.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        const container = document.getElementById('ifa-auctions-table');
        const fmt = v => '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
        const phaseColor = p => p === 'open' ? 'success' : p === 'listening' ? 'warning' : 'danger';
        let html = '<table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>Age</th><th>Stars</th><th>Slot</th><th>Phase</th><th>Entered Wk</th><th>Offers</th><th>Competitors</th></tr></thead><tbody>';
        auctions.forEach(a => {
          html += `<tr>
            <td>${a.firstName} ${a.lastName}</td><td>${a.ptype}</td><td>${a.age}</td>
            <td>${'\u2605'.repeat(a.star_rating)}</td><td>${fmt(a.slot_value)}</td>
            <td><span class="badge badge-${phaseColor(a.phase)}">${a.phase}</span></td>
            <td>${a.entered_week}</td><td>${a.active_offers}</td>
            <td>${a.competitors.length ? a.competitors.join(', ') : '\u2014'}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  function loadIfaEligible(lyid) {
    fetch(`${API_BASE}/ifa/eligible?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(players => {
        const card = document.getElementById('ifa-eligible-card');
        if (!players || !players.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        const container = document.getElementById('ifa-eligible-table');
        const starFilter = document.getElementById('ifa-star-filter')?.value;
        const filtered = starFilter ? players.filter(p => p.star_rating === parseInt(starFilter)) : players;
        const fmt = v => '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
        let html = `<p style="color:var(--text-secondary);margin-bottom:8px">${filtered.length} of ${players.length} players shown</p>`;
        html += '<table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>Age</th><th>Area</th><th>Stars</th><th>Slot Value</th></tr></thead><tbody>';
        filtered.forEach(p => {
          html += `<tr><td>${p.firstName} ${p.lastName}</td><td>${p.ptype}</td><td>${p.age}</td><td>${p.area || '\u2014'}</td><td>${'\u2605'.repeat(p.star_rating)}</td><td>${fmt(p.slot_value)}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  function loadIfaHistory(lyid) {
    fetch(`${API_BASE}/ifa/history?league_year_id=${lyid}`, { credentials: 'include' })
      .then(r => r.json())
      .then(history => {
        const card = document.getElementById('ifa-history-card');
        if (!history || !history.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        const container = document.getElementById('ifa-history-table');
        const fmt = v => v != null ? '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 }) : '\u2014';
        let html = '<table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>Stars</th><th>Slot</th><th>Result</th><th>Winner</th><th>Bonus</th></tr></thead><tbody>';
        history.forEach(h => {
          const resultBadge = h.phase === 'completed'
            ? '<span class="badge badge-success">Signed</span>'
            : '<span class="badge badge-secondary">Expired</span>';
          html += `<tr><td>${h.firstName} ${h.lastName}</td><td>${h.ptype}</td><td>${'\u2605'.repeat(h.star_rating)}</td><td>${fmt(h.slot_value)}</td><td>${resultBadge}</td><td>${h.winner_abbrev || '\u2014'}</td><td>${fmt(h.winning_bonus)}</td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(() => {});
  }

  // IFA button handlers
  document.getElementById('btn-ifa-refresh')?.addEventListener('click', loadIfaAdmin);
  document.getElementById('ifa-lyid')?.addEventListener('change', loadIfaAdmin);
  document.getElementById('ifa-star-filter')?.addEventListener('change', () => {
    const lyid = ifaLyid();
    if (lyid) loadIfaEligible(lyid);
  });

  document.getElementById('btn-ifa-advance-week')?.addEventListener('click', () => {
    const lyid = ifaLyid();
    if (!lyid) return;
    if (!confirm('Advance the IFA signing window by one week? This will process phase transitions.')) return;
    const status = document.getElementById('ifa-status');
    status.textContent = 'Advancing week\u2026';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/ifa/advance-week`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.error;
          status.className = 'status-msg error';
          return;
        }
        let msg = `Advanced to week ${data.new_week} (${data.status})`;
        if (data.players_ranked) msg += ` \u2014 ${data.players_ranked} players ranked`;
        if (data.pools_allocated) msg += `, ${data.pools_allocated} pools allocated`;
        if (data.phase_transitions) {
          const pt = data.phase_transitions;
          const parts = [];
          if (pt.open_to_listening) parts.push(`${pt.open_to_listening} \u2192 listening`);
          if (pt.listening_to_finalize) parts.push(`${pt.listening_to_finalize} \u2192 finalize`);
          if (pt.finalize_to_completed) parts.push(`${pt.finalize_to_completed} signed`);
          if (pt.expired) parts.push(`${pt.expired} expired`);
          if (parts.length) msg += ` \u2014 ${parts.join(', ')}`;
        }
        status.textContent = msg;
        status.className = 'status-msg success';
        loadIfaAdmin();
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  document.getElementById('btn-ifa-reset')?.addEventListener('click', () => {
    const lyid = ifaLyid();
    if (!lyid) return;
    if (!confirm('RESET the entire IFA window? This will reverse all signings, delete all auctions/offers/pools, and return to week 0.')) return;
    if (!confirm('Are you sure? This cannot be undone.')) return;
    const status = document.getElementById('ifa-status');
    status.textContent = 'Resetting IFA window\u2026';
    status.className = 'status-msg info';

    fetch(`${API_BASE}/ifa/reset`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league_year_id: parseInt(lyid) }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.textContent = data.error;
          status.className = 'status-msg error';
          return;
        }
        const parts = [];
        if (data.contracts_reversed) parts.push(`${data.contracts_reversed} signings reversed`);
        if (data.auctions_deleted) parts.push(`${data.auctions_deleted} auctions deleted`);
        if (data.offers_deleted) parts.push(`${data.offers_deleted} offers deleted`);
        if (data.pools_deleted) parts.push(`${data.pools_deleted} pools deleted`);
        if (data.rankings_cleared) parts.push(`${data.rankings_cleared} rankings cleared`);
        status.textContent = `IFA window reset. ${parts.join(', ') || 'Nothing to clean up.'}`;
        status.className = 'status-msg success';
        loadIfaAdmin();
      })
      .catch(e => { status.textContent = e.message; status.className = 'status-msg error'; });
  });

  // ======================================================================
  // Batting Lab
  // ======================================================================
  let blabSlashChart = null;
  let blabRateChart = null;

  function loadBlabHistory() {
    fetch('/admin/batting-lab/runs', { credentials: 'include' })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        const div = document.getElementById('blab-history-table');
        if (!data.ok || !data.runs || data.runs.length === 0) {
          div.innerHTML = '<p style="color:var(--text-secondary)">No runs yet. Configure and click "Run Tier Sweep" above.</p>';
          return;
        }
        let html = '<table class="data-table"><thead><tr>' +
          '<th>ID</th><th>Label</th><th>Level</th><th>Games/Tier</th><th>Status</th><th>Created</th><th>Action</th>' +
          '</tr></thead><tbody>';
        data.runs.forEach(r => {
          const statusCls = r.status === 'complete' ? 'badge-success' :
            r.status === 'running' ? 'badge-warning' :
            r.status === 'error' ? 'badge-danger' : '';
          html += `<tr>
            <td>${r.id}</td>
            <td>${r.label || '-'}</td>
            <td>${r.league_level}</td>
            <td>${r.games_per_scenario}</td>
            <td><span class="badge ${statusCls}">${r.status}</span></td>
            <td>${r.created_at ? r.created_at.substring(0, 16) : '-'}</td>
            <td>${r.status === 'complete' ? `<button class="btn btn-sm btn-secondary" onclick="App.loadBlabResults(${r.id})">View</button>` : ''}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        div.innerHTML = html;
      })
      .catch(() => {});
  }

  function loadBlabResults(runId) {
    fetch(`/admin/batting-lab/results/${runId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;

        const card = document.getElementById('blab-results-card');
        card.style.display = '';

        const run = data.run;
        document.getElementById('blab-results-title').textContent =
          `Results: ${run.label || 'Run #' + run.id} (Level ${run.league_level}, ${run.games_per_scenario} games/tier)`;

        const info = document.getElementById('blab-results-info');
        info.innerHTML = `<span class="badge badge-success">${run.status}</span>` +
          (run.completed_at ? ` <span style="color:var(--text-secondary);margin-left:8px">${run.completed_at.substring(0, 16)}</span>` : '');

        const tiers = data.tiers || [];
        if (tiers.length === 0) return;

        // ── Slash line chart (AVG / OBP / SLG grouped bar) ──
        const tierLabels = tiers.map(t => t.tier_label);
        const avgData = tiers.map(t => t.avg || 0);
        const obpData = tiers.map(t => t.obp || 0);
        const slgData = tiers.map(t => t.slg || 0);

        const slashCanvas = document.getElementById('blab-slash-chart');
        if (blabSlashChart) blabSlashChart.destroy();
        blabSlashChart = new Chart(slashCanvas, {
          type: 'bar',
          data: {
            labels: tierLabels,
            datasets: [
              { label: 'AVG', data: avgData, backgroundColor: '#3b82f6' },
              { label: 'OBP', data: obpData, backgroundColor: '#10b981' },
              { label: 'SLG', data: slgData, backgroundColor: '#f59e0b' },
            ],
          },
          options: {
            responsive: false,
            plugins: { legend: { labels: { color: '#9ca3af' } } },
            scales: {
              y: { beginAtZero: true, max: 0.7, ticks: { color: '#9ca3af' }, grid: { color: '#374151' } },
              x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
            },
          },
        });

        // ── Rate chart (K%, BB%) ──
        const kData = tiers.map(t => t.k_pct || 0);
        const bbData = tiers.map(t => t.bb_pct || 0);

        const rateCanvas = document.getElementById('blab-rate-chart');
        if (blabRateChart) blabRateChart.destroy();
        blabRateChart = new Chart(rateCanvas, {
          type: 'bar',
          data: {
            labels: tierLabels,
            datasets: [
              { label: 'K%', data: kData, backgroundColor: '#ef4444' },
              { label: 'BB%', data: bbData, backgroundColor: '#8b5cf6' },
            ],
          },
          options: {
            responsive: false,
            plugins: { legend: { labels: { color: '#9ca3af' } } },
            scales: {
              y: { beginAtZero: true, ticks: { color: '#9ca3af', callback: v => v + '%' }, grid: { color: '#374151' } },
              x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
            },
          },
        });

        // ── Data table ──
        let html = '<table class="data-table"><thead><tr>' +
          '<th>Tier</th><th>G</th><th>PA</th><th>AB</th><th>H</th><th>2B</th><th>3B</th><th>HR</th><th>ITPHR</th>' +
          '<th>BB</th><th>K</th><th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th><th>ISO</th>' +
          '<th>K%</th><th>BB%</th><th>R/G</th>' +
          '</tr></thead><tbody>';
        tiers.forEach(t => {
          const gp = t.games_played || 1;
          const rpg = ((t.runs || 0) / gp).toFixed(1);
          html += `<tr>
            <td><strong>${t.tier_label}</strong></td>
            <td>${t.games_played}</td>
            <td>${t.plate_appearances}</td>
            <td>${t.at_bats}</td>
            <td>${t.hits}</td>
            <td>${t.doubles}</td>
            <td>${t.triples}</td>
            <td>${t.home_runs}</td>
            <td>${t.inside_the_park_hr || 0}</td>
            <td>${t.walks}</td>
            <td>${t.strikeouts}</td>
            <td>${(t.avg || 0).toFixed(3)}</td>
            <td>${(t.obp || 0).toFixed(3)}</td>
            <td>${(t.slg || 0).toFixed(3)}</td>
            <td>${(t.ops || 0).toFixed(3)}</td>
            <td>${(t.iso || 0).toFixed(3)}</td>
            <td>${(t.k_pct || 0).toFixed(1)}%</td>
            <td>${(t.bb_pct || 0).toFixed(1)}%</td>
            <td>${rpg}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('blab-results-table').innerHTML = html;

        // Scroll to results
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      })
      .catch(() => {});
  }

  // Run button
  document.getElementById('btn-blab-run')?.addEventListener('click', () => {
    const level = document.getElementById('blab-level').value;
    const games = document.getElementById('blab-games').value;
    const label = document.getElementById('blab-label').value;
    const status = document.getElementById('blab-status');

    status.textContent = 'Running tier sweep... this may take a minute.';
    status.className = 'status-msg info';

    fetch('/admin/batting-lab/run', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        league_level: parseInt(level),
        games_per_tier: parseInt(games),
        label: label,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          status.textContent = data.message || 'Complete';
          status.className = 'status-msg success';
          loadBlabHistory();
          if (data.run_id) loadBlabResults(data.run_id);
        } else {
          status.textContent = data.message || 'Error';
          status.className = 'status-msg error';
        }
      })
      .catch(e => {
        status.textContent = 'Request failed: ' + e.message;
        status.className = 'status-msg error';
      });
  });

  // ===========================================================================
  // Weight Calibration
  // ===========================================================================

  function loadCalibrationInit() {
    // Populate league year dropdown
    const sel = document.getElementById('cal-lyid');
    if (!sel || sel.options.length > 1) {
      loadCalibrationProfiles();
      return;
    }
    fetch(`${ADMIN_BASE}/analytics/league-years`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        sel.innerHTML = '';
        (data.league_years || []).forEach(ly => {
          const opt = document.createElement('option');
          opt.value = ly.id;
          opt.textContent = `${ly.league_year} (ID ${ly.id})`;
          sel.appendChild(opt);
        });
      })
      .catch(() => {});
    loadCalibrationProfiles();
  }

  function runCalibration() {
    const resultBox = document.getElementById('cal-run-result');
    resultBox.style.display = 'block';
    resultBox.textContent = 'Running calibration...';

    const body = {
      league_year_id: parseInt(document.getElementById('cal-lyid').value, 10),
      league_level: parseInt(document.getElementById('cal-level').value, 10),
      config: {
        min_innings: parseInt(document.getElementById('cal-min-inn').value, 10) || 50,
        min_at_bats: parseInt(document.getElementById('cal-min-ab').value, 10) || 100,
        min_ipo: parseInt(document.getElementById('cal-min-ipo').value, 10) || 60,
      },
    };
    const name = document.getElementById('cal-name').value.trim();
    if (name) body.name = name;

    fetch(`${ADMIN_BASE}/calibration/run`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          resultBox.textContent = 'Error: ' + (data.message || 'unknown');
          return;
        }
        resultBox.textContent = `Profile "${data.name}" created (ID ${data.profile_id})`;
        renderCalibrationResults(data.positions);
        loadCalibrationProfiles();
      })
      .catch(err => { resultBox.textContent = 'Error: ' + err.message; });
  }

  function renderCalibrationResults(positions) {
    const card = document.getElementById('cal-results-card');
    const tbody = document.getElementById('cal-results-tbody');
    card.style.display = '';
    tbody.innerHTML = '';

    const posOrder = [
      'c_rating', 'fb_rating', 'sb_rating', 'tb_rating', 'ss_rating',
      'lf_rating', 'cf_rating', 'rf_rating', 'dh_rating', 'sp_rating', 'rp_rating',
    ];
    const posLabels = {
      c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
      ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
      dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
    };

    const confColors = { high: '#4caf50', moderate: '#ff9800', low: '#f44336' };

    for (const rt of posOrder) {
      const cal = positions[rt];
      if (!cal) continue;
      const tr = document.createElement('tr');
      const status = cal.skipped ? 'Skipped' : 'OK';
      const statusCls = cal.skipped ? 'color: var(--warning)' : 'color: var(--success, #4caf50)';
      const conf = cal.confidence_level || '—';
      const confClr = confColors[conf] || 'inherit';
      const offR2 = cal.offense_r2 != null ? cal.offense_r2.toFixed(3) : '—';
      const offAdjR2 = cal.offense_adj_r2 != null ? cal.offense_adj_r2.toFixed(3) : '—';
      const defR2 = cal.defense_r2 != null ? cal.defense_r2.toFixed(3) : (cal.r2 != null ? cal.r2.toFixed(3) : '—');
      const defAdjR2 = cal.defense_adj_r2 != null ? cal.defense_adj_r2.toFixed(3) : (cal.adj_r2 != null ? cal.adj_r2.toFixed(3) : '—');
      const warns = (cal.warnings || []);
      const warnTip = warns.length > 0 ? warns.join('\n') : '';
      tr.innerHTML = `
        <td>${posLabels[rt] || rt}</td>
        <td>${cal.n || 0}</td>
        <td style="color:${confClr}">${conf}</td>
        <td>${offR2}</td>
        <td>${offAdjR2}</td>
        <td>${defR2}</td>
        <td>${defAdjR2}</td>
        <td style="${statusCls}">${status}</td>
        <td title="${warnTip.replace(/"/g, '&quot;')}">${warns.length > 0 ? warns.length + ' warning(s)' : '—'}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  function loadCalibrationProfiles() {
    const tbody = document.getElementById('cal-profiles-tbody');
    if (!tbody) return;

    fetch(`${ADMIN_BASE}/calibration/profiles`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        tbody.innerHTML = '';

        // Also populate compare dropdowns
        const selA = document.getElementById('cal-compare-a');
        const selB = document.getElementById('cal-compare-b');
        if (selA) selA.innerHTML = '';
        if (selB) selB.innerHTML = '';

        (data.profiles || []).forEach(p => {
          const tr = document.createElement('tr');
          const activeBadge = p.is_active ? '<span style="color: var(--success, #4caf50); font-weight: bold;">Active</span>' : '';
          const level = p.league_level != null ? p.league_level : '—';
          tr.innerHTML = `
            <td>${p.name}</td>
            <td>${p.source}</td>
            <td>${level}</td>
            <td>${activeBadge}</td>
            <td>${p.created_at || ''}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="App.viewCalProfile(${p.id})">View</button>
              ${!p.is_active ? `<button class="btn btn-sm btn-warning" onclick="App.activateCalProfile(${p.id})">Activate</button>` : ''}
            </td>
          `;
          tbody.appendChild(tr);

          // Populate compare selects
          if (selA) {
            const optA = document.createElement('option');
            optA.value = p.id;
            optA.textContent = p.name;
            selA.appendChild(optA);
          }
          if (selB) {
            const optB = document.createElement('option');
            optB.value = p.id;
            optB.textContent = p.name;
            selB.appendChild(optB);
          }
        });

        // Show compare card if 2+ profiles
        const compareCard = document.getElementById('cal-compare-card');
        if (compareCard) {
          compareCard.style.display = (data.profiles || []).length >= 2 ? '' : 'none';
        }
      })
      .catch(() => {});
  }

  let _calViewProfileId = null;
  let _calOrigWeights = null;

  function viewCalProfile(profileId) {
    const card = document.getElementById('cal-detail-card');
    const title = document.getElementById('cal-detail-title');
    const content = document.getElementById('cal-detail-content');
    card.style.display = '';
    content.innerHTML = '<p class="text-muted">Loading...</p>';
    _calViewProfileId = profileId;

    fetch(`${ADMIN_BASE}/calibration/profiles/${profileId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          content.innerHTML = '<p class="text-muted">Failed to load.</p>';
          return;
        }
        const p = data.profile;
        title.textContent = `Profile: ${p.name} (${p.source})`;
        _calOrigWeights = JSON.parse(JSON.stringify(p.weights || {}));

        const weights = p.weights || {};
        // 13 rating types: 11 position-specifics + 2 generic overalls.
        // Generic overalls are shown alongside position-specifics so admins
        // can edit all weight knobs in one place.
        const posOrder = [
          'pitcher_overall', 'position_overall',
          'sp_rating', 'rp_rating',
          'c_rating', 'fb_rating', 'sb_rating', 'tb_rating', 'ss_rating',
          'lf_rating', 'cf_rating', 'rf_rating', 'dh_rating',
        ];
        const posLabels = {
          pitcher_overall: 'P (default)', position_overall: 'Pos (default)',
          c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
          ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
          dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
        };
        // Show every type that has weights in the profile. For older profiles
        // missing pitcher_overall/position_overall, the column header will not
        // appear — admins should re-run calibration or seed those rows manually.
        const activePosTypes = posOrder.filter(rt => weights[rt]);

        const allAttrs = new Set();
        for (const rt of activePosTypes) {
          for (const attr of Object.keys(weights[rt] || {})) allAttrs.add(attr);
        }
        const attrList = [...allAttrs].sort();

        let html = '<div style="margin-bottom:8px">';
        html += '<button class="btn btn-primary" id="btn-cal-save-weights">Save Changes</button> ';
        html += '<button class="btn btn-secondary" id="btn-cal-normalize">Normalize Columns</button>';
        html += ' <span id="cal-edit-status" style="color:var(--text-secondary);font-size:0.85em"></span>';
        html += '</div>';

        html += '<div class="table-wrap" style="max-height:500px;overflow:auto"><table class="data-table"><thead><tr><th>Attribute</th>';
        for (const rt of activePosTypes) {
          html += `<th>${posLabels[rt]}</th>`;
        }
        html += '</tr></thead><tbody>';

        for (const attr of attrList) {
          html += `<tr><td style="font-size:0.85em">${attr.replace(/_base$/, '').replace(/_/g, ' ')}</td>`;
          for (const rt of activePosTypes) {
            const w = weights[rt][attr] || 0;
            const orig = (_calOrigWeights[rt] || {})[attr] || 0;
            const changed = Math.abs(w - orig) > 0.0001;
            const intensity = Math.min(w * 4, 1.0);
            const bg = w > 0 ? `rgba(76, 175, 80, ${intensity})` : '';
            const border = changed ? 'border:1px solid #ff9800' : '';
            html += `<td style="text-align:center;padding:2px;background:${bg};${border}">`;
            html += `<input type="number" step="0.001" min="0" max="1" value="${w.toFixed(4)}" `;
            html += `data-rt="${rt}" data-attr="${attr}" `;
            html += `style="width:65px;text-align:center;background:transparent;color:inherit;border:none;font-size:0.85em">`;
            html += '</td>';
          }
          html += '</tr>';
        }

        // Sum row
        html += '<tr style="font-weight:bold;border-top:2px solid var(--border)"><td>Sum</td>';
        for (const rt of activePosTypes) {
          const sum = Object.values(weights[rt] || {}).reduce((a, b) => a + b, 0);
          html += `<td style="text-align:center" id="cal-sum-${rt}">${sum.toFixed(3)}</td>`;
        }
        html += '</tr></tbody></table></div>';

        if (p.calibration) {
          html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:var(--text-secondary)">Calibration Details</summary>';
          html += `<pre class="result-box">${JSON.stringify(p.calibration.results, null, 2)}</pre>`;
          html += '</details>';
        }

        content.innerHTML = html;

        // Wire save button
        document.getElementById('btn-cal-save-weights').addEventListener('click', () => {
          const inputs = content.querySelectorAll('input[data-rt]');
          const newWeights = {};
          inputs.forEach(inp => {
            const rt = inp.dataset.rt;
            const attr = inp.dataset.attr;
            newWeights[rt] = newWeights[rt] || {};
            newWeights[rt][attr] = parseFloat(inp.value) || 0;
          });

          fetch(`${ADMIN_BASE}/calibration/profiles/${_calViewProfileId}/weights`, {
            method: 'PUT', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ weights: newWeights }),
          })
            .then(r => r.json())
            .then(res => {
              const st = document.getElementById('cal-edit-status');
              if (res.ok) {
                let msg = `Saved ${res.updated} entries`;
                if (res.activated && res.recompute && res.recompute.updated != null) {
                  msg += ` — live: recomputed displayovr for ${res.recompute.updated} players`;
                } else if (!res.activated) {
                  msg += ' (profile is not active — activate to push to live)';
                }
                st.textContent = msg;
                st.style.color = '#4caf50';
                _calOrigWeights = JSON.parse(JSON.stringify(newWeights));
              } else {
                st.textContent = `Error: ${res.message || 'unknown'}`;
                st.style.color = '#f44336';
              }
            })
            .catch(err => {
              document.getElementById('cal-edit-status').textContent = 'Error: ' + err.message;
            });
        });

        // Wire normalize button
        document.getElementById('btn-cal-normalize').addEventListener('click', () => {
          for (const rt of activePosTypes) {
            const inputs = content.querySelectorAll(`input[data-rt="${rt}"]`);
            let sum = 0;
            inputs.forEach(inp => { sum += parseFloat(inp.value) || 0; });
            if (sum > 0) {
              inputs.forEach(inp => {
                inp.value = ((parseFloat(inp.value) || 0) / sum).toFixed(4);
              });
            }
            const sumCell = document.getElementById(`cal-sum-${rt}`);
            if (sumCell) sumCell.textContent = '1.000';
          }
          document.getElementById('cal-edit-status').textContent = 'Normalized — remember to Save';
          document.getElementById('cal-edit-status').style.color = '#ff9800';
        });
      })
      .catch(err => { content.innerHTML = '<p class="text-muted">Error: ' + err.message + '</p>'; });
  }

  function activateCalProfile(profileId) {
    if (!confirm('Activate this profile? This will update live rating weights and recompute displayovr for all players.')) return;

    fetch(`${ADMIN_BASE}/calibration/activate/${profileId}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          const ovrMsg = data.displayovr_updated ? ` DisplayOVR updated for ${data.displayovr_updated} players.` : '';
          alert(`Activated — ${data.entries} weight entries applied.${ovrMsg}`);
          loadCalibrationProfiles();
        } else {
          alert('Error: ' + (data.message || 'unknown'));
        }
      })
      .catch(err => alert('Error: ' + err.message));
  }

  function compareCalibrationProfiles() {
    const a = document.getElementById('cal-compare-a').value;
    const b = document.getElementById('cal-compare-b').value;
    if (!a || !b || a === b) {
      alert('Select two different profiles to compare.');
      return;
    }

    const content = document.getElementById('cal-compare-content');
    content.innerHTML = '<p class="text-muted">Loading...</p>';

    fetch(`${ADMIN_BASE}/calibration/compare?a=${a}&b=${b}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          content.innerHTML = '<p class="text-muted">Failed to load.</p>';
          return;
        }

        const posLabels = {
          c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
          ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
          dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
        };

        let html = `<p><strong>${data.profile_a.name}</strong> vs <strong>${data.profile_b.name}</strong></p>`;
        const comparison = data.comparison || {};

        for (const [rt, entries] of Object.entries(comparison)) {
          html += `<h4 style="margin-top: 12px;">${posLabels[rt] || rt}</h4>`;
          html += '<div class="table-wrap"><table class="data-table"><thead><tr>';
          html += `<th>Attribute</th><th>${data.profile_a.name}</th><th>${data.profile_b.name}</th><th>Delta</th>`;
          html += '</tr></thead><tbody>';

          for (const e of entries) {
            const deltaColor = e.delta > 0 ? 'color: var(--success, #4caf50)' : e.delta < 0 ? 'color: var(--warning, #ff9800)' : '';
            html += `<tr>
              <td>${e.attribute.replace(/_base$/, '').replace(/_/g, ' ')}</td>
              <td>${e.weight_a.toFixed(4)}</td>
              <td>${e.weight_b.toFixed(4)}</td>
              <td style="${deltaColor}">${e.delta > 0 ? '+' : ''}${e.delta.toFixed(4)}</td>
            </tr>`;
          }
          html += '</tbody></table></div>';
        }

        content.innerHTML = html;
      })
      .catch(err => { content.innerHTML = '<p class="text-muted">Error: ' + err.message + '</p>'; });
  }

  window.App = {
    goTo,
    refreshDashboard,
    deleteTask,
    selectPlayer,
    selectFA,
    adminApproveProposal,
    adminRejectProposal,
    viewTxDetail,
    closeTxDetail,
    rollbackTx,
    deleteTxEntry,
    editGame,
    drillCorrelation,
    loadBlabResults,
    viewCalProfile,
    activateCalProfile,
  };

  // -----------------------------------------------------------------------
  // Recompute DisplayOVR
  // -----------------------------------------------------------------------

  function recomputeDisplayOvr() {
    const level = document.getElementById('cal-ovr-level').value;
    const status = document.getElementById('cal-ovr-status');
    status.textContent = 'Recomputing...';
    status.style.color = 'var(--text-secondary)';

    const body = level ? { level: parseInt(level) } : {};

    fetch(`${ADMIN_BASE}/calibration/recompute-displayovr`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          const byLevel = data.by_level || {};
          const detail = Object.entries(byLevel).map(([l, c]) => `L${l}: ${c}`).join(', ');
          status.textContent = `Updated ${data.updated} players. ${detail}`;
          status.style.color = '#4caf50';
        } else {
          status.textContent = `Error: ${data.error || data.message || 'unknown'}`;
          status.style.color = '#f44336';
        }
      })
      .catch(err => {
        status.textContent = 'Error: ' + err.message;
        status.style.color = '#f44336';
      });
  }

  // -----------------------------------------------------------------------
  // Player Preview
  // -----------------------------------------------------------------------

  function loadPlayerPreviewFilters(params) {
    const qs = new URLSearchParams(params || {}).toString();
    return fetch(`${ADMIN_BASE}/calibration/player-preview/filters?${qs}`, { credentials: 'include' })
      .then(r => r.json());
  }

  function initPlayerPreviewCascade() {
    const levelSel = document.getElementById('cal-prev-level');
    const orgSel = document.getElementById('cal-prev-org');
    const teamSel = document.getElementById('cal-prev-team');
    const playerSel = document.getElementById('cal-prev-player');

    levelSel.addEventListener('change', () => {
      orgSel.innerHTML = '<option value="">--</option>';
      teamSel.innerHTML = '<option value="">--</option>';
      playerSel.innerHTML = '<option value="">--</option>';
      if (!levelSel.value) return;
      loadPlayerPreviewFilters({ level: levelSel.value }).then(data => {
        if (!data.ok) return;
        (data.orgs || []).forEach(o => {
          orgSel.innerHTML += `<option value="${o.id}">${o.abbrev}</option>`;
        });
      });
    });

    orgSel.addEventListener('change', () => {
      teamSel.innerHTML = '<option value="">--</option>';
      playerSel.innerHTML = '<option value="">--</option>';
      if (!orgSel.value) return;
      const p = { org_id: orgSel.value };
      if (levelSel.value) p.level = levelSel.value;
      loadPlayerPreviewFilters(p).then(data => {
        if (!data.ok) return;
        (data.teams || []).forEach(t => {
          teamSel.innerHTML += `<option value="${t.id}">${t.abbrev} (${t.level})</option>`;
        });
      });
    });

    teamSel.addEventListener('change', () => {
      playerSel.innerHTML = '<option value="">--</option>';
      if (!teamSel.value) return;
      loadPlayerPreviewFilters({ team_id: teamSel.value }).then(data => {
        if (!data.ok) return;
        (data.players || []).forEach(p => {
          const tag = p.ptype === 'Pitcher' ? ' (P)' : '';
          playerSel.innerHTML += `<option value="${p.id}">${p.name}${tag}</option>`;
        });
      });
    });
  }

  function loadPlayerPreview() {
    const playerId = document.getElementById('cal-prev-player').value;
    const status = document.getElementById('cal-prev-status');
    const resultCard = document.getElementById('cal-prev-result');
    resultCard.style.display = 'none';

    if (!playerId) {
      status.textContent = 'Select a player first';
      return;
    }
    status.textContent = 'Loading...';

    fetch(`${ADMIN_BASE}/calibration/player-preview?player_id=${playerId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          status.textContent = `Error: ${data.message || 'unknown'}`;
          return;
        }
        status.textContent = '';
        renderPlayerPreview(data);
      })
      .catch(err => { status.textContent = 'Error: ' + err.message; });
  }

  function renderPlayerPreview(data) {
    const card = document.getElementById('cal-prev-result');
    const title = document.getElementById('cal-prev-title');
    const content = document.getElementById('cal-prev-content');

    const p = data.player;
    const posDisplay = p.listed_position ? p.listed_position.toUpperCase() : null;
    title.textContent = `${p.name} — ${p.ptype}${posDisplay ? ' (' + posDisplay + ')' : ''} (Level ${p.level})`;

    let html = '';

    // Overall display
    const ovrTypeLabels = {
      pitcher_overall: 'Pitcher Overall (fallback)',
      position_overall: 'Position Overall (fallback)',
      c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
      ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
      dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
    };
    const ovrTypeLabel = ovrTypeLabels[data.overall.type] || data.overall.type;
    const isFallback = data.overall.type === 'pitcher_overall' || data.overall.type === 'position_overall';

    html += `<div style="display:flex;gap:24px;align-items:center;margin-bottom:16px;flex-wrap:wrap">`;
    html += `<div style="text-align:center;padding:12px 24px;background:var(--bg-card);border-radius:8px;border:2px solid #2196f3">`;
    html += `<div style="font-size:2em;font-weight:bold;color:#2196f3">${data.displayovr || '—'}</div>`;
    html += `<div style="font-size:0.85em;color:var(--text-secondary)">Display OVR</div>`;
    html += `</div>`;
    html += `<div style="font-size:0.9em;color:var(--text-secondary)">`;
    html += `Weight type: <strong${isFallback ? ' style="color:var(--warning,#ff9800)"' : ''}>${ovrTypeLabel}</strong><br>`;
    html += `Raw: ${data.overall.raw} | 20-80: ${data.overall.scaled_20_80}<br>`;
    html += `Current stored: ${p.current_displayovr || 'null'}`;
    if (isFallback) {
      html += `<br><span style="color:var(--warning,#ff9800);font-size:0.85em">No listed position — using generic fallback weights</span>`;
    }
    html += `</div></div>`;

    // Position ratings table
    html += '<h5>Position Ratings</h5>';
    html += '<div class="table-wrap"><table class="data-table"><thead><tr><th>Rating</th><th>Raw</th><th>20-80</th></tr></thead><tbody>';

    const posLabels = {
      c_rating: 'C', fb_rating: '1B', sb_rating: '2B', tb_rating: '3B',
      ss_rating: 'SS', lf_rating: 'LF', cf_rating: 'CF', rf_rating: 'RF',
      dh_rating: 'DH', sp_rating: 'SP', rp_rating: 'RP',
      pitch1_ovr: 'P1 OVR', pitch2_ovr: 'P2 OVR', pitch3_ovr: 'P3 OVR',
      pitch4_ovr: 'P4 OVR', pitch5_ovr: 'P5 OVR',
    };

    const ratings = data.position_ratings || {};
    const sorted = Object.entries(ratings).sort((a, b) => {
      const sa = (a[1].scaled_20_80 || 0);
      const sb = (b[1].scaled_20_80 || 0);
      return sb - sa;
    });

    for (const [key, val] of sorted) {
      const label = posLabels[key] || key;
      const scaledColor = val.scaled_20_80 >= 60 ? '#4caf50' : val.scaled_20_80 >= 45 ? '#ff9800' : '#f44336';
      html += `<tr>`;
      html += `<td>${label}</td>`;
      html += `<td>${val.raw}</td>`;
      html += `<td style="color:${scaledColor};font-weight:bold">${val.scaled_20_80 != null ? val.scaled_20_80 : '—'}</td>`;
      html += `</tr>`;
    }
    html += '</tbody></table></div>';

    // Raw attributes (compact 3-col layout)
    html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:var(--text-secondary)">Raw Attributes</summary>';
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;font-size:0.85em;margin-top:8px">';
    const attrs = data.raw_attributes || {};
    for (const [key, val] of Object.entries(attrs).sort()) {
      const label = key.replace(/_base$/, '').replace(/_/g, ' ');
      html += `<div><span style="color:var(--text-secondary)">${label}:</span> ${val}</div>`;
    }
    html += '</div></details>';

    content.innerHTML = html;
    card.style.display = '';
    card.scrollIntoView({ behavior: 'smooth' });
  }

  // -----------------------------------------------------------------------
  // Gameplan Audit & Editor
  // -----------------------------------------------------------------------

  let _gpaData = null;
  let _gpaTeamId = null;
  let _gpaOrgId = null;
  let _gpaRoster = null;
  let _gpaEditMode = false;

  const _GPA_POS_ORDER = ['c','fb','sb','tb','ss','lf','cf','rf','dh'];
  const _GPA_POS_LABEL = {c:'C',fb:'1B',sb:'2B',tb:'3B',ss:'SS',lf:'LF',cf:'CF',rf:'RF',dh:'DH',p:'P'};
  const _GPA_ROLES = ['balanced','table_setter','on_base','slugger','speed','bottom'];
  const _GPA_BP_ROLES = ['closer','setup','middle','long','mop_up'];
  const _GPA_OF_SPACING = ['normal','deep','shallow','shift_pull','shift_oppo'];
  const _GPA_IF_SPACING = ['normal','in','double_play','shift_pull','shift_oppo'];
  const _GPA_BP_PRIORITY = ['rest','matchup','best_available'];
  const _GPA_PLATE = ['normal','aggressive','patient','contact','power'];
  const _GPA_PITCHING = ['normal','aggressive','finesse','power','location'];
  const _GPA_BASERUN = ['normal','aggressive','cautious','conservative'];
  const _GPA_USAGE = ['normal','only_fully_rested','play_tired','desperation'];
  const _GPA_PULLTEND = ['normal','quick','long'];

  function _gpaOpts(arr, selected) {
    return arr.map(v => `<option value="${v}"${v === selected ? ' selected' : ''}>${v}</option>`).join('');
  }
  function _gpaPlayerOpts(players, selectedId, filterPtype) {
    const filtered = filterPtype ? players.filter(p => p.ptype === filterPtype) : players;
    return '<option value="">--</option>' +
      filtered.map(p => `<option value="${p.id}"${p.id === selectedId ? ' selected' : ''}>${p.name} (${p.id})</option>`).join('');
  }
  function _gpaStatus(msg, color) {
    const el = document.getElementById('gpa-edit-status');
    el.textContent = msg;
    el.style.color = color || 'var(--text-secondary)';
  }

  function loadGameplanAudit() {
    const level = document.getElementById('gpa-level').value;
    const status = document.getElementById('gpa-status');
    status.textContent = 'Loading...';
    document.getElementById('gpa-overview').style.display = 'none';
    document.getElementById('gpa-detail').style.display = 'none';

    let url = `${ADMIN_BASE}/gameplan-audit`;
    if (level) url += `?level=${level}`;

    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = `Error: ${data.error || 'unknown'}`; return; }
        _gpaData = {};
        (data.teams || []).forEach(t => { _gpaData[t.team_id] = t; });
        status.textContent = `${data.count} teams loaded`;
        renderGameplanOverview(data.teams || []);
      })
      .catch(err => { status.textContent = `Fetch error: ${err}`; });
  }

  function renderGameplanOverview(teams) {
    const tbody = document.querySelector('#gpa-overview-table tbody');
    const check = v => v ? '<span style="color:#4caf50">Y</span>' : '<span style="color:#f44336">N</span>';
    tbody.innerHTML = teams.map(t => {
      const c = t.completeness || {};
      const ts = t.most_recent_update ? new Date(t.most_recent_update).toLocaleDateString() : '-';
      return `<tr>
        <td><strong>${t.org_abbrev}</strong></td><td>${t.team_abbrev}</td>
        <td>${t.level_name} (${t.team_level})</td>
        <td style="text-align:center">${check(c.defense)}</td>
        <td style="text-align:center">${check(c.rotation)}</td>
        <td style="text-align:center">${check(c.bullpen)}</td>
        <td style="text-align:center">${check(c.team_strategy)}</td>
        <td style="text-align:center">${check(c.lineup_roles)}</td>
        <td style="text-align:center">${check(c.player_strategies)}</td>
        <td>${ts}</td>
        <td><button class="btn btn-secondary" style="padding:2px 8px;font-size:0.8em" onclick="window._gpaViewTeam(${t.team_id})">View</button></td>
      </tr>`;
    }).join('');
    document.getElementById('gpa-overview').style.display = '';
  }

  function _gpaLoadRoster(teamId) {
    return fetch(`${ADMIN_BASE}/gameplan-audit/roster?team_id=${teamId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { _gpaRoster = data.ok ? data.players : []; return _gpaRoster; });
  }

  function _gpaSetEditMode(on) {
    _gpaEditMode = on;
    const btn = document.getElementById('btn-gpa-edit-toggle');
    btn.textContent = on ? 'View Mode' : 'Edit Mode';
    btn.className = on ? 'btn btn-warning' : 'btn btn-primary';
    document.querySelectorAll('.gpa-save-btn').forEach(b => { b.style.display = on ? '' : 'none'; });
    if (_gpaTeamId) window._gpaViewTeam(_gpaTeamId);
  }

  window._gpaViewTeam = function(teamId) {
    const t = _gpaData && _gpaData[teamId];
    if (!t) return;
    _gpaTeamId = teamId;
    _gpaOrgId = t.org_id;

    document.getElementById('gpa-detail-title').textContent =
      `${t.org_abbrev} ${t.team_abbrev} (${t.level_name}) - Gameplan ${_gpaEditMode ? 'Editor' : 'Detail'}`;
    _gpaStatus('');

    if (_gpaEditMode && !_gpaRoster) {
      _gpaStatus('Loading roster...', 'var(--text-secondary)');
      _gpaLoadRoster(teamId).then(() => { _gpaRenderAll(t); _gpaStatus(''); });
    } else {
      _gpaRenderAll(t);
    }

    document.getElementById('gpa-detail').style.display = '';
    document.getElementById('gpa-detail').scrollIntoView({ behavior: 'smooth' });
  };

  function _gpaRenderAll(t) {
    _gpaRenderDefense(t);
    _gpaRenderRotation(t);
    _gpaRenderBullpen(t);
    _gpaRenderStrategy(t);
    _gpaRenderLineup(t);
    _gpaRenderPlayerStrats(t);
  }

  // --- Defense ---
  function _gpaRenderDefense(t) {
    const el = document.getElementById('gpa-defense-content');
    const rows = (t.defense && t.defense.assignments) || [];
    const sorted = [...rows].sort((a, b) => {
      const ai = _GPA_POS_ORDER.indexOf(a.position_code);
      const bi = _GPA_POS_ORDER.indexOf(b.position_code);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || a.priority - b.priority;
    });

    if (!_gpaEditMode) {
      el.innerHTML = sorted.length ? '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Pos</th><th>vs Hand</th><th>Player</th><th>Wt</th><th>Pri</th><th>Lock</th><th>Role</th><th>Order</th></tr></thead><tbody>' +
        sorted.map(d => {
          const ord = (d.min_order||d.max_order) ? `${d.min_order||'?'}-${d.max_order||'?'}` : '-';
          return `<tr><td><strong>${_GPA_POS_LABEL[d.position_code]||d.position_code}</strong></td><td>${d.vs_hand==='both'?'All':'vs '+d.vs_hand+'HP'}</td><td>${d.player_name} <span style="color:var(--text-secondary);font-size:0.8em">(${d.player_id})</span></td><td>${d.target_weight}</td><td>${d.priority}</td><td>${d.locked?'<span style="color:#4caf50">Y</span>':'-'}</td><td>${d.lineup_role||'balanced'}</td><td>${ord}</td></tr>`;
        }).join('') + '</tbody></table></div>' : '<span style="color:var(--text-secondary)">No defense plan</span>';
      return;
    }
    const roster = _gpaRoster || [];
    let html = '<div style="overflow-x:auto;max-height:400px"><table class="data-table" id="gpa-def-edit"><thead><tr><th>Pos</th><th>vs Hand</th><th>Player</th><th>Wt</th><th>Pri</th><th>Lock</th><th>Role</th><th>Min</th><th>Max</th><th></th></tr></thead><tbody>';
    sorted.forEach((d, i) => {
      html += `<tr data-idx="${i}">
        <td><select class="gpa-inp" data-f="position_code">${_gpaOpts([...new Set([..._GPA_POS_ORDER,'p'])], d.position_code)}</select></td>
        <td><select class="gpa-inp" data-f="vs_hand">${_gpaOpts(['both','L','R'], d.vs_hand)}</select></td>
        <td><select class="gpa-inp" data-f="player_id">${_gpaPlayerOpts(roster, d.player_id)}</select></td>
        <td><input type="number" class="gpa-inp" data-f="target_weight" value="${d.target_weight}" step="0.1" min="0.1" max="10" style="width:50px"></td>
        <td><input type="number" class="gpa-inp" data-f="priority" value="${d.priority}" min="1" max="9" style="width:40px"></td>
        <td><input type="checkbox" class="gpa-inp" data-f="locked" ${d.locked?'checked':''}></td>
        <td><select class="gpa-inp" data-f="lineup_role">${_gpaOpts(_GPA_ROLES, d.lineup_role||'balanced')}</select></td>
        <td><input type="number" class="gpa-inp" data-f="min_order" value="${d.min_order||''}" min="1" max="9" style="width:40px"></td>
        <td><input type="number" class="gpa-inp" data-f="max_order" value="${d.max_order||''}" min="1" max="9" style="width:40px"></td>
        <td><button class="btn btn-danger" style="padding:1px 6px;font-size:0.8em" onclick="this.closest('tr').remove()">X</button></td>
      </tr>`;
    });
    html += '</tbody></table></div>';
    html += '<button class="btn btn-secondary" style="margin-top:6px;padding:2px 10px;font-size:0.85em" id="btn-gpa-def-add">+ Add Row</button>';
    el.innerHTML = html;
    document.getElementById('btn-gpa-def-add').addEventListener('click', () => {
      const tbody = document.querySelector('#gpa-def-edit tbody');
      const idx = tbody.rows.length;
      const tr = document.createElement('tr'); tr.dataset.idx = idx;
      tr.innerHTML = `<td><select class="gpa-inp" data-f="position_code">${_gpaOpts(_GPA_POS_ORDER,'c')}</select></td>
        <td><select class="gpa-inp" data-f="vs_hand">${_gpaOpts(['both','L','R'],'both')}</select></td>
        <td><select class="gpa-inp" data-f="player_id">${_gpaPlayerOpts(roster, null)}</select></td>
        <td><input type="number" class="gpa-inp" data-f="target_weight" value="1.0" step="0.1" min="0.1" max="10" style="width:50px"></td>
        <td><input type="number" class="gpa-inp" data-f="priority" value="1" min="1" max="9" style="width:40px"></td>
        <td><input type="checkbox" class="gpa-inp" data-f="locked"></td>
        <td><select class="gpa-inp" data-f="lineup_role">${_gpaOpts(_GPA_ROLES,'balanced')}</select></td>
        <td><input type="number" class="gpa-inp" data-f="min_order" value="" min="1" max="9" style="width:40px"></td>
        <td><input type="number" class="gpa-inp" data-f="max_order" value="" min="1" max="9" style="width:40px"></td>
        <td><button class="btn btn-danger" style="padding:1px 6px;font-size:0.8em" onclick="this.closest('tr').remove()">X</button></td>`;
      tbody.appendChild(tr);
    });
  }

  function _gpaSaveDefense() {
    const rows = document.querySelectorAll('#gpa-def-edit tbody tr');
    const assignments = [];
    rows.forEach(tr => {
      const g = f => tr.querySelector(`[data-f="${f}"]`);
      const pid = parseInt(g('player_id').value);
      if (!pid) return;
      assignments.push({
        position_code: g('position_code').value,
        vs_hand: g('vs_hand').value,
        player_id: pid,
        target_weight: parseFloat(g('target_weight').value) || 1.0,
        priority: parseInt(g('priority').value) || 1,
        locked: g('locked').checked,
        lineup_role: g('lineup_role').value,
        min_order: g('min_order').value ? parseInt(g('min_order').value) : null,
        max_order: g('max_order').value ? parseInt(g('max_order').value) : null,
      });
    });
    _gpaPut(`/gameplanning/team/${_gpaTeamId}/defense`, { assignments }, 'Defense');
  }

  // --- Rotation ---
  function _gpaRenderRotation(t) {
    const el = document.getElementById('gpa-rotation-content');
    const rot = t.rotation || {};
    const slots = rot.slots || [];

    if (!_gpaEditMode) {
      let html = slots.length ? '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Slot</th><th>Pitcher</th></tr></thead><tbody>' +
        slots.map(s => `<tr><td>${s.slot}${s.slot===rot.current_slot?' <span style="color:#2196f3">(next)</span>':''}</td><td>${s.player_name} (${s.player_id})</td></tr>`).join('') +
        '</tbody></table></div>' : '<span style="color:var(--text-secondary)">No rotation</span>';
      html += `<div style="color:var(--text-secondary);font-size:0.85em;margin-top:4px">Size: ${rot.rotation_size||0} | Slot: ${rot.current_slot||0} | Updated: ${rot.rotation_updated||'-'}</div>`;
      el.innerHTML = html;
      return;
    }
    const pitchers = (_gpaRoster||[]).filter(p => p.ptype === 'Pitcher');
    const size = rot.rotation_size || 5;
    let html = `<div style="margin-bottom:6px"><label>Rotation Size: </label><select id="gpa-rot-size">`;
    for (let i = 1; i <= 7; i++) html += `<option value="${i}"${i===size?' selected':''}>${i}</option>`;
    html += '</select></div>';
    html += '<div id="gpa-rot-slots">';
    for (let i = 0; i < size; i++) {
      const s = slots[i];
      html += `<div style="margin:4px 0"><strong>${i+1}.</strong> <select class="gpa-rot-pitcher">${_gpaPlayerOpts(pitchers, s?s.player_id:null, null)}</select></div>`;
    }
    html += '</div>';
    el.innerHTML = html;
    document.getElementById('gpa-rot-size').addEventListener('change', function() {
      const newSize = parseInt(this.value);
      const container = document.getElementById('gpa-rot-slots');
      const current = container.querySelectorAll('.gpa-rot-pitcher').length;
      if (newSize > current) {
        for (let i = current; i < newSize; i++) {
          const div = document.createElement('div'); div.style.margin = '4px 0';
          div.innerHTML = `<strong>${i+1}.</strong> <select class="gpa-rot-pitcher">${_gpaPlayerOpts(pitchers, null, null)}</select>`;
          container.appendChild(div);
        }
      } else {
        const divs = container.querySelectorAll('div');
        for (let i = divs.length - 1; i >= newSize; i--) divs[i].remove();
      }
    });
  }

  function _gpaSaveRotation() {
    const size = parseInt(document.getElementById('gpa-rot-size').value);
    const selects = document.querySelectorAll('.gpa-rot-pitcher');
    const slots = [];
    selects.forEach((sel, i) => {
      if (i < size) slots.push({ slot: i + 1, player_id: sel.value ? parseInt(sel.value) : 0 });
    });
    _gpaPut(`/gameplanning/team/${_gpaTeamId}/rotation`, { rotation_size: size, slots }, 'Rotation');
  }

  // --- Bullpen ---
  function _gpaRenderBullpen(t) {
    const el = document.getElementById('gpa-bullpen-content');
    const bps = (t.bullpen && t.bullpen.pitchers) || [];
    const roleColors = {closer:'#f44336',setup:'#ff9800',middle:'#2196f3',long:'#4caf50',mop_up:'#9e9e9e'};

    if (!_gpaEditMode) {
      el.innerHTML = bps.length ? '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>Slot</th><th>Pitcher</th><th>Role</th></tr></thead><tbody>' +
        bps.map(b => `<tr><td>${b.slot}</td><td>${b.player_name} (${b.player_id})</td><td><span style="color:${roleColors[b.role]||'inherit'}">${b.role}</span></td></tr>`).join('') +
        '</tbody></table></div>' : '<span style="color:var(--text-secondary)">No bullpen</span>';
      return;
    }
    const pitchers = (_gpaRoster||[]).filter(p => p.ptype === 'Pitcher');
    let html = '<div id="gpa-bp-rows">';
    bps.forEach((b, i) => {
      html += `<div style="margin:4px 0" class="gpa-bp-row"><strong>${i+1}.</strong> <select class="gpa-bp-pitcher">${_gpaPlayerOpts(pitchers, b.player_id, null)}</select> <select class="gpa-bp-role">${_gpaOpts(_GPA_BP_ROLES, b.role)}</select> <button class="btn btn-danger" style="padding:1px 6px;font-size:0.8em" onclick="this.parentElement.remove()">X</button></div>`;
    });
    html += '</div>';
    html += '<button class="btn btn-secondary" style="margin-top:6px;padding:2px 10px;font-size:0.85em" id="btn-gpa-bp-add">+ Add Pitcher</button>';
    el.innerHTML = html;
    document.getElementById('btn-gpa-bp-add').addEventListener('click', () => {
      const container = document.getElementById('gpa-bp-rows');
      const idx = container.querySelectorAll('.gpa-bp-row').length;
      const div = document.createElement('div'); div.className = 'gpa-bp-row'; div.style.margin = '4px 0';
      div.innerHTML = `<strong>${idx+1}.</strong> <select class="gpa-bp-pitcher">${_gpaPlayerOpts(pitchers, null, null)}</select> <select class="gpa-bp-role">${_gpaOpts(_GPA_BP_ROLES, 'middle')}</select> <button class="btn btn-danger" style="padding:1px 6px;font-size:0.8em" onclick="this.parentElement.remove()">X</button>`;
      container.appendChild(div);
    });
  }

  function _gpaSaveBullpen() {
    const rows = document.querySelectorAll('.gpa-bp-row');
    const pitchers = [];
    rows.forEach((row, i) => {
      const pid = parseInt(row.querySelector('.gpa-bp-pitcher').value);
      if (!pid) return;
      pitchers.push({ slot: i + 1, player_id: pid, role: row.querySelector('.gpa-bp-role').value });
    });
    _gpaPut(`/gameplanning/team/${_gpaTeamId}/bullpen`, { pitchers }, 'Bullpen');
  }

  // --- Team Strategy ---
  function _gpaRenderStrategy(t) {
    const el = document.getElementById('gpa-strategy-content');
    const s = t.team_strategy || {};

    if (!_gpaEditMode) {
      if (t.team_strategy) {
        el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
          <div><strong>OF Spacing:</strong> ${s.outfield_spacing}</div><div><strong>IF Spacing:</strong> ${s.infield_spacing}</div>
          <div><strong>BP Cutoff:</strong> ${s.bullpen_cutoff} pitches</div><div><strong>BP Priority:</strong> ${s.bullpen_priority}</div>
          <div><strong>Emergency P:</strong> ${s.emergency_pitcher_name||'None'}</div>
          <div><strong>IBB List:</strong> ${(s.intentional_walk_list||[]).length?s.intentional_walk_list.join(', '):'None'}</div>
          <div><strong>Updated:</strong> ${s.updated_at||'-'}</div></div>`;
      } else {
        el.innerHTML = '<span style="color:var(--text-secondary)">No strategy</span>';
      }
      return;
    }
    const roster = _gpaRoster || [];
    el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;font-size:0.9em">
      <div><label>OF Spacing</label><br><select id="gpa-strat-of">${_gpaOpts(_GPA_OF_SPACING, s.outfield_spacing||'normal')}</select></div>
      <div><label>IF Spacing</label><br><select id="gpa-strat-if">${_gpaOpts(_GPA_IF_SPACING, s.infield_spacing||'normal')}</select></div>
      <div><label>BP Cutoff</label><br><input type="number" id="gpa-strat-cutoff" value="${s.bullpen_cutoff||100}" min="50" max="150" style="width:70px"></div>
      <div><label>BP Priority</label><br><select id="gpa-strat-bp">${_gpaOpts(_GPA_BP_PRIORITY, s.bullpen_priority||'rest')}</select></div>
      <div><label>Emergency P</label><br><select id="gpa-strat-ep"><option value="">None</option>${roster.map(p=>`<option value="${p.id}"${p.id===s.emergency_pitcher_id?' selected':''}>${p.name}</option>`).join('')}</select></div>
      <div><label>IBB List (IDs)</label><br><input type="text" id="gpa-strat-ibb" value="${(s.intentional_walk_list||[]).join(',')}" style="width:140px" placeholder="123,456"></div>
    </div>`;
  }

  function _gpaSaveStrategy() {
    const ibbRaw = document.getElementById('gpa-strat-ibb').value.trim();
    const ibb = ibbRaw ? ibbRaw.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)) : [];
    const epVal = document.getElementById('gpa-strat-ep').value;
    _gpaPut(`/gameplanning/team/${_gpaTeamId}/strategy`, {
      outfield_spacing: document.getElementById('gpa-strat-of').value,
      infield_spacing: document.getElementById('gpa-strat-if').value,
      bullpen_cutoff: parseInt(document.getElementById('gpa-strat-cutoff').value),
      bullpen_priority: document.getElementById('gpa-strat-bp').value,
      emergency_pitcher_id: epVal ? parseInt(epVal) : null,
      intentional_walk_list: ibb,
    }, 'Strategy');
  }

  // --- Lineup Roles ---
  function _gpaRenderLineup(t) {
    const el = document.getElementById('gpa-lineup-content');
    const slots = (t.lineup_roles && t.lineup_roles.slots) || [];

    if (!_gpaEditMode) {
      el.innerHTML = slots.length ? '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>#</th><th>Role</th><th>Locked</th></tr></thead><tbody>' +
        slots.map(l => `<tr><td>${l.slot}</td><td>${l.role}</td><td>${l.locked_player_name||'-'}</td></tr>`).join('') +
        '</tbody></table></div>' : '<span style="color:var(--text-secondary)">No lineup roles</span>';
      return;
    }
    const roster = _gpaRoster || [];
    let html = '<div style="overflow-x:auto"><table class="data-table"><thead><tr><th>#</th><th>Role</th><th>Locked Player</th></tr></thead><tbody>';
    for (let i = 1; i <= 9; i++) {
      const s = slots.find(x => x.slot === i) || { slot: i, role: 'balanced', locked_player_id: null };
      html += `<tr><td>${i}</td><td><select class="gpa-lu-role" data-slot="${i}">${_gpaOpts(_GPA_ROLES, s.role)}</select></td>
        <td><select class="gpa-lu-lock" data-slot="${i}"><option value="">None</option>${roster.map(p=>`<option value="${p.id}"${p.id===s.locked_player_id?' selected':''}>${p.name}</option>`).join('')}</select></td></tr>`;
    }
    html += '</tbody></table></div>';
    el.innerHTML = html;
  }

  function _gpaSaveLineup() {
    const slots = [];
    for (let i = 1; i <= 9; i++) {
      const role = document.querySelector(`.gpa-lu-role[data-slot="${i}"]`).value;
      const lockVal = document.querySelector(`.gpa-lu-lock[data-slot="${i}"]`).value;
      slots.push({ slot: i, role, locked_player_id: lockVal ? parseInt(lockVal) : null });
    }
    _gpaPut(`/gameplanning/team/${_gpaTeamId}/lineup`, { slots }, 'Lineup');
  }

  // --- Player Strategies ---
  function _gpaRenderPlayerStrats(t) {
    const el = document.getElementById('gpa-playerstrat-content');
    const ps = t.player_strategies || {};

    if (!_gpaEditMode) {
      if (ps.total_strategies > 0) {
        el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
          <div><strong>Total:</strong> ${ps.total_strategies}</div><div><strong>Custom Usage:</strong> ${ps.custom_usage_preference}</div>
          <div><strong>Custom Plate:</strong> ${ps.custom_plate_approach}</div><div><strong>Custom Pitching:</strong> ${ps.custom_pitching_approach}</div>
          <div><strong>Custom Baserunning:</strong> ${ps.custom_baserunning_approach}</div></div>`;
      } else {
        el.innerHTML = '<span style="color:var(--text-secondary)">No player strategies</span>';
      }
      return;
    }
    el.innerHTML = '<button class="btn btn-secondary" id="btn-gpa-ps-load" style="padding:2px 10px;font-size:0.85em">Load Player Strategies</button><div id="gpa-ps-table" style="margin-top:8px"></div>';
    document.getElementById('btn-gpa-ps-load').addEventListener('click', () => {
      _gpaStatus('Loading player strategies...', 'var(--text-secondary)');
      fetch(`${ADMIN_BASE}/gameplan-audit/player-strategies?team_id=${_gpaTeamId}`, { credentials: 'include' })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(data => {
          if (!data.ok) { _gpaStatus(`Error: ${data.message || data.error || 'unknown'}`, '#f44336'); return; }
          const strats = data.strategies || [];
          if (!strats.length) { _gpaStatus('No player strategies found for this team', '#ff9800'); return; }
          _gpaStatus(`${strats.length} strategies loaded`, '#4caf50');
          let html = '<div style="overflow-x:auto;max-height:500px"><table class="data-table"><thead><tr><th>Player</th><th>Type</th><th>Plate</th><th>Pitching</th><th>Baserun</th><th>Usage</th><th>Steal%</th><th>Pick%</th><th>Pull#</th><th>Leash</th><th></th></tr></thead><tbody>';
          strats.forEach(s => {
            const isPit = s.ptype === 'Pitcher';
            html += `<tr data-pid="${s.player_id}" data-ptype="${s.ptype}">
              <td style="font-size:0.85em">${s.player_name}</td>
              <td>${isPit?'P':'Pos'}</td>
              <td><select class="gpa-ps" data-f="plate_approach">${_gpaOpts(_GPA_PLATE, s.plate_approach)}</select></td>
              <td>${isPit?`<select class="gpa-ps" data-f="pitching_approach">${_gpaOpts(_GPA_PITCHING, s.pitching_approach)}</select>`:'-'}</td>
              <td><select class="gpa-ps" data-f="baserunning_approach">${_gpaOpts(_GPA_BASERUN, s.baserunning_approach)}</select></td>
              <td><select class="gpa-ps" data-f="usage_preference">${_gpaOpts(_GPA_USAGE, s.usage_preference)}</select></td>
              <td><input type="number" class="gpa-ps" data-f="stealfreq" value="${s.stealfreq}" step="0.1" min="0" max="100" style="width:55px"></td>
              <td>${isPit?`<input type="number" class="gpa-ps" data-f="pickofffreq" value="${s.pickofffreq}" step="0.1" min="0" max="100" style="width:55px">`:'-'}</td>
              <td>${isPit?`<input type="number" class="gpa-ps" data-f="pitchpull" value="${s.pitchpull||''}" min="1" style="width:50px">`:'-'}</td>
              <td>${isPit?`<select class="gpa-ps" data-f="pulltend"><option value="">default</option>${_gpaOpts(_GPA_PULLTEND, s.pulltend||'')}</select>`:'-'}</td>
              <td><button class="btn btn-secondary" style="padding:1px 6px;font-size:0.8em" onclick="window._gpaSaveOnePlayer(this)">Save</button></td>
            </tr>`;
          });
          html += '</tbody></table></div>';
          document.getElementById('gpa-ps-table').innerHTML = html;
        })
        .catch(err => { _gpaStatus(`Failed to load strategies: ${err}`, '#f44336'); });
    });
  }

  window._gpaSaveOnePlayer = function(btn) {
    const tr = btn.closest('tr');
    const pid = parseInt(tr.dataset.pid);
    const body = {};
    tr.querySelectorAll('.gpa-ps').forEach(inp => {
      const f = inp.dataset.f;
      if (inp.type === 'number') body[f] = inp.value ? parseFloat(inp.value) : null;
      else body[f] = inp.value || null;
    });
    fetch(`/api/v1/gameplanning/org/${_gpaOrgId}/player/${pid}/strategy`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json()).then(data => {
      if (data.error) _gpaStatus(`Player ${pid}: ${data.message}`, '#f44336');
      else { btn.textContent = 'Saved'; setTimeout(() => { btn.textContent = 'Save'; }, 1500); }
    }).catch(err => _gpaStatus(`Error: ${err}`, '#f44336'));
  };

  function _gpaSaveAllPlayerStrats() {
    const rows = document.querySelectorAll('#gpa-ps-table tbody tr');
    if (!rows.length) { _gpaStatus('Load player strategies first', '#ff9800'); return; }
    let saved = 0, total = rows.length;
    _gpaStatus(`Saving ${total} strategies...`, 'var(--text-secondary)');
    rows.forEach(tr => {
      const pid = parseInt(tr.dataset.pid);
      const body = {};
      tr.querySelectorAll('.gpa-ps').forEach(inp => {
        const f = inp.dataset.f;
        if (inp.type === 'number') body[f] = inp.value ? parseFloat(inp.value) : null;
        else body[f] = inp.value || null;
      });
      fetch(`/api/v1/gameplanning/org/${_gpaOrgId}/player/${pid}/strategy`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json()).then(() => {
        saved++;
        if (saved >= total) _gpaStatus(`Saved ${saved}/${total} strategies`, '#4caf50');
      }).catch(() => { saved++; });
    });
  }

  // --- Generic PUT helper ---
  function _gpaPut(path, body, label) {
    _gpaStatus(`Saving ${label}...`, 'var(--text-secondary)');
    fetch(`/api/v1${path}`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          _gpaStatus(`${label} error: ${data.message || data.error}`, '#f44336');
        } else {
          _gpaStatus(`${label} saved`, '#4caf50');
          // Refresh audit data for this team
          fetch(`${ADMIN_BASE}/gameplan-audit?team_id=${_gpaTeamId}`, { credentials: 'include' })
            .then(r => r.json()).then(d => {
              if (d.ok && d.teams && d.teams[0]) {
                _gpaData[_gpaTeamId] = d.teams[0];
              }
            });
        }
      })
      .catch(err => _gpaStatus(`${label} error: ${err}`, '#f44336'));
  }

  // -----------------------------------------------------------------------
  // FA Auction Board
  // -----------------------------------------------------------------------

  let _faAucState = { auctionId: null, playerName: '', minAav: 0, war: 0, phase: '', orgId: null };

  function faLoadBoard() {
    const orgId = document.getElementById('fa-auc-org').value;
    _faAucState.orgId = orgId ? parseInt(orgId) : null;
    fetchTxContext().then(() => {
      const lyId = txLeagueYearId || 1;
      const url = `${API_BASE}/fa-auction/board?league_year_id=${lyId}` +
                  (orgId ? `&org_id=${orgId}` : '');
      fetch(url, { credentials: 'include' })
        .then(r => r.json())
        .then(data => {
          const tbody = document.getElementById('fa-auc-tbody');
          if (!Array.isArray(data) || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center">No active auctions</td></tr>';
            return;
          }
          tbody.innerHTML = data.map(a => {
            const phaseBadge = { open: 'badge-success', listening: 'badge-warning', finalize: 'badge-danger' };
            const myOffer = a.my_offer
              ? `$${Number(a.my_offer.aav).toLocaleString()} / ${a.my_offer.years}y`
              : '—';
            const competing = a.competing_teams.join(', ') || '—';
            const btnLabel = a.my_offer ? 'Update' : 'Offer';
            return `<tr>
              <td>${a.player_name}</td>
              <td>${a.age}</td>
              <td>${a.player_type}</td>
              <td>${a.war.toFixed(1)}</td>
              <td>$${Number(a.min_aav).toLocaleString()}</td>
              <td><span class="badge ${phaseBadge[a.phase] || ''}">${a.phase}</span></td>
              <td>${a.offer_count}</td>
              <td>${competing}</td>
              <td>${myOffer}</td>
              <td><button class="btn btn-primary btn-sm"
                    onclick="App.faOpenOffer(${a.auction_id}, '${a.player_name.replace(/'/g,"\\'")}', ${a.min_aav}, ${a.war}, '${a.phase}', ${JSON.stringify(a.my_offer).replace(/"/g,'&quot;')})">${btnLabel}</button></td>
            </tr>`;
          }).join('');
        })
        .catch(err => {
          document.getElementById('fa-auc-tbody').innerHTML =
            `<tr><td colspan="10">Error: ${err}</td></tr>`;
        });
    });
  }

  function faOpenOffer(auctionId, playerName, minAav, war, phase, existingOffer) {
    _faAucState.auctionId = auctionId;
    _faAucState.playerName = playerName;
    _faAucState.minAav = minAav;
    _faAucState.war = war;
    _faAucState.phase = phase;

    document.getElementById('fa-offer-player-name').textContent = playerName;
    document.getElementById('fa-offer-war').textContent = war.toFixed(1);
    document.getElementById('fa-offer-min-aav').textContent = '$' + Number(minAav).toLocaleString();
    document.getElementById('fa-offer-phase').textContent = phase;

    // Pre-fill from existing offer or defaults
    if (existingOffer) {
      document.getElementById('fa-offer-years').value = existingOffer.years;
      document.getElementById('fa-offer-bonus').value = existingOffer.bonus;
      document.getElementById('fa-offer-level').value = existingOffer.level_id;
    } else {
      document.getElementById('fa-offer-years').value = 1;
      document.getElementById('fa-offer-bonus').value = 0;
      document.getElementById('fa-offer-level').value = 9;
    }

    faRenderSalaryInputs(existingOffer);
    faUpdateTotals();

    // Load budget
    const orgId = _faAucState.orgId;
    if (orgId) {
      fetch(`${API_BASE}/transactions/signing-budget/${orgId}?league_year_id=${txLeagueYearId || 1}`,
            { credentials: 'include' })
        .then(r => r.json())
        .then(d => {
          document.getElementById('fa-offer-budget').textContent =
            '$' + Number(d.available_budget || 0).toLocaleString();
        })
        .catch(() => {
          document.getElementById('fa-offer-budget').textContent = 'N/A';
        });
    }

    document.getElementById('fa-offer-modal').style.display = 'block';
    document.getElementById('fa-offer-result').style.display = 'none';
    document.getElementById('fa-offer-warning').style.display = 'none';
  }

  function faRenderSalaryInputs(existingOffer) {
    const years = parseInt(document.getElementById('fa-offer-years').value) || 1;
    const container = document.getElementById('fa-offer-salaries');
    container.innerHTML = '';
    for (let i = 1; i <= years; i++) {
      const existing = existingOffer && existingOffer.salaries ? existingOffer.salaries[i - 1] : '';
      container.innerHTML += `<div class="form-group">
        <label>Year ${i} Salary ($)</label>
        <input type="number" id="fa-sal-${i}" min="0" step="100000"
               value="${existing || ''}" oninput="App.faUpdateTotals()" />
      </div>`;
    }
  }

  function faUpdateTotals() {
    const years = parseInt(document.getElementById('fa-offer-years').value) || 1;
    const bonus = parseFloat(document.getElementById('fa-offer-bonus').value) || 0;
    let totalSalary = 0;
    for (let i = 1; i <= years; i++) {
      totalSalary += parseFloat(document.getElementById(`fa-sal-${i}`)?.value || 0);
    }
    const total = totalSalary + bonus;
    const aav = years > 0 ? total / years : 0;
    document.getElementById('fa-offer-total').textContent = '$' + total.toLocaleString();
    document.getElementById('fa-offer-aav').textContent = '$' + Math.round(aav).toLocaleString();

    // Warning if below minimum
    const warn = document.getElementById('fa-offer-warning');
    if (aav < _faAucState.minAav && totalSalary > 0) {
      warn.textContent = `AAV ($${Math.round(aav).toLocaleString()}) is below player minimum ($${Number(_faAucState.minAav).toLocaleString()})`;
      warn.style.display = 'block';
    } else {
      warn.style.display = 'none';
    }
  }

  function faSubmitOffer() {
    const orgId = _faAucState.orgId;
    if (!orgId) { alert('Select your organization first'); return; }

    const years = parseInt(document.getElementById('fa-offer-years').value) || 1;
    const bonus = parseFloat(document.getElementById('fa-offer-bonus').value) || 0;
    const levelId = parseInt(document.getElementById('fa-offer-level').value) || 9;
    const salaries = [];
    for (let i = 1; i <= years; i++) {
      salaries.push(parseFloat(document.getElementById(`fa-sal-${i}`)?.value || 0));
    }

    fetch(`${API_BASE}/fa-auction/${_faAucState.auctionId}/offer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        org_id: parseInt(orgId),
        years, salaries, bonus,
        level_id: levelId,
        league_year_id: txLeagueYearId || 1,
        game_week_id: txGameWeekId || 1,
        current_week: txGameWeekId || 0,
        executed_by: 'admin',
      }),
    })
      .then(r => r.json())
      .then(data => {
        const res = document.getElementById('fa-offer-result');
        res.style.display = 'block';
        if (data.error) {
          res.textContent = 'Error: ' + data.error;
        } else {
          res.textContent = JSON.stringify(data, null, 2);
          faLoadBoard(); // refresh
        }
      })
      .catch(err => {
        document.getElementById('fa-offer-result').style.display = 'block';
        document.getElementById('fa-offer-result').textContent = 'Error: ' + err;
      });
  }

  function faAdvancePhases() {
    if (!confirm('Advance all FA auction phases? This may finalize signings.')) return;
    fetchTxContext().then(() => {
      fetch(`${API_BASE}/fa-auction/advance-phases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          league_year_id: txLeagueYearId || 1,
          current_week: txGameWeekId || 0,
        }),
      })
        .then(r => r.json())
        .then(data => {
          alert(JSON.stringify(data, null, 2));
          faLoadBoard();
        })
        .catch(err => alert('Error: ' + err));
    });
  }

  // -----------------------------------------------------------------------
  // Market Dashboard
  // -----------------------------------------------------------------------

  function faLoadMarket() {
    fetchTxContext().then(() => {
      const lyId = txLeagueYearId || 1;
      fetch(`${API_BASE}/fa-auction/market-summary?league_year_id=${lyId}`,
            { credentials: 'include' })
        .then(r => r.json())
        .then(data => {
          document.getElementById('fa-market-data').style.display = 'block';

          // Summary cards
          const cards = document.getElementById('fa-market-summary-cards');
          cards.innerHTML = `
            <div class="card">
              <div class="card-value">$${Number(data.dollar_per_war).toLocaleString()}</div>
              <div class="card-label">Current $/WAR</div>
            </div>
            <div class="card">
              <div class="card-value">${data.total_signings}</div>
              <div class="card-label">Signings (3yr window)</div>
            </div>
            <div class="card">
              <div class="card-value">${data.avg_years}y</div>
              <div class="card-label">Avg Contract Length</div>
            </div>
          `;

          // Recent signings table
          const tbody = document.getElementById('fa-market-recent-tbody');
          if (data.recent_signings && data.recent_signings.length > 0) {
            tbody.innerHTML = data.recent_signings.map(s => `<tr>
              <td>${s.name}</td>
              <td>${s.age}</td>
              <td>${s.war.toFixed(1)}</td>
              <td>${s.years}</td>
              <td>$${Number(s.aav).toLocaleString()}</td>
              <td>$${Number(s.total_value).toLocaleString()}</td>
              <td>${s.source}</td>
            </tr>`).join('');
          } else {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center">No signings yet</td></tr>';
          }

          // WAR tier chart
          if (data.war_tiers && typeof Chart !== 'undefined') {
            const ctx = document.getElementById('fa-market-tiers-chart');
            if (ctx._chart) ctx._chart.destroy();
            ctx._chart = new Chart(ctx.getContext('2d'), {
              type: 'bar',
              data: {
                labels: ['0-1 WAR', '1-2 WAR', '2-3 WAR', '3-4 WAR', '4+ WAR'],
                datasets: [{
                  label: 'Signings',
                  data: [data.war_tiers['0-1'], data.war_tiers['1-2'], data.war_tiers['2-3'],
                         data.war_tiers['3-4'], data.war_tiers['4+']],
                  backgroundColor: 'rgba(59, 130, 246, 0.7)',
                  borderColor: 'rgba(59, 130, 246, 1)',
                  borderWidth: 1,
                }],
              },
              options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                  y: { beginAtZero: true, ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                  x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                },
              },
            });
          }
        })
        .catch(err => {
          document.getElementById('fa-market-data').style.display = 'block';
          document.getElementById('fa-market-summary-cards').innerHTML =
            `<div class="card"><div class="card-value">Error</div><div class="card-label">${err}</div></div>`;
        });
    });
  }

  // -----------------------------------------------------------------------
  // FA Auction event wiring
  // -----------------------------------------------------------------------

  (function wireAuction() {
    const btn = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
    btn('btn-fa-load-board', faLoadBoard);
    btn('btn-fa-advance-phases', faAdvancePhases);
    btn('btn-fa-submit-offer', faSubmitOffer);
    btn('btn-fa-cancel-offer', () => { document.getElementById('fa-offer-modal').style.display = 'none'; });
    btn('btn-fa-load-market', faLoadMarket);

    const yearsInput = document.getElementById('fa-offer-years');
    if (yearsInput) {
      yearsInput.addEventListener('change', () => { faRenderSalaryInputs(null); faUpdateTotals(); });
    }
    const bonusInput = document.getElementById('fa-offer-bonus');
    if (bonusInput) bonusInput.addEventListener('input', faUpdateTotals);

    // Populate org dropdown
    populateTxOrgDropdown('fa-auc-org');
  })();

  // -----------------------------------------------------------------------
  // Rankings
  // -----------------------------------------------------------------------

  let rankEloChart = null;
  let rankPowChart = null;
  let rankPythChart = null;

  function loadRankingsLeagueYears(section) {
    const prefixMap = {
      'rankings-elo': 'rank-elo',
      'rankings-power': 'rank-pow',
      'rankings-rpi': 'rank-rpi',
      'rankings-pyth': 'rank-pyth',
      'rankings-race': 'rank-race',
    };
    const prefix = prefixMap[section];
    if (!prefix) return;
    const sel = document.getElementById(`${prefix}-lyid`);
    if (!sel || sel.options.length > 1) return;

    fetch(`${ADMIN_BASE}/analytics/league-years`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) return;
        sel.innerHTML = '';
        (data.league_years || []).forEach(ly => {
          const o = document.createElement('option');
          o.value = ly.id;
          o.textContent = ly.league_year;
          sel.appendChild(o);
        });
      });
  }

  // ---- ELO ----
  function loadRankingsElo() {
    const lyid = document.getElementById('rank-elo-lyid').value;
    const level = document.getElementById('rank-elo-level').value;
    const k = document.getElementById('rank-elo-k').value;
    const status = document.getElementById('rank-elo-status');
    status.textContent = 'Loading...';
    document.getElementById('rank-elo-results').style.display = 'none';

    fetch(`${ADMIN_BASE}/analytics/rankings-elo?league_year_id=${lyid}&league_level=${level}&k_factor=${k}`,
      { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.message || data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('rank-elo-results').style.display = '';

        // Table — rows are clickable to highlight team on chart
        const teams = data.teams || [];
        let html = '<table class="data-table"><thead><tr>' +
          '<th>Rank</th><th>Team</th><th>ELO</th><th>W</th><th>L</th><th>Win%</th><th>Trend</th>' +
          '</tr></thead><tbody>';
        teams.forEach((t, i) => {
          const trendColor = t.trend > 0 ? 'var(--success)' : t.trend < 0 ? 'var(--danger)' : 'var(--text-secondary)';
          const trendArrow = t.trend > 0 ? '&#9650;' : t.trend < 0 ? '&#9660;' : '&#8211;';
          html += `<tr data-elo-idx="${i}" style="cursor:pointer">
            <td>${t.rank}</td>
            <td><strong>${t.team_abbrev || t.team_id}</strong></td>
            <td><strong>${t.elo}</strong></td>
            <td>${t.wins}</td><td>${t.losses}</td>
            <td>${t.win_pct.toFixed(3)}</td>
            <td style="color:${trendColor}">${trendArrow} ${Math.abs(t.trend).toFixed(1)}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('rank-elo-table').innerHTML = html;

        // Chart: ELO over time — all teams, click to highlight
        if (rankEloChart) rankEloChart.destroy();
        const ctx = document.getElementById('rank-elo-chart').getContext('2d');
        const history = data.history || {};
        const datasets = [];
        const palette = [
          '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899',
          '#06b6d4','#84cc16','#f97316','#6366f1','#14b8a6','#e11d48',
          '#a855f7','#22c55e','#eab308','#0ea5e9','#d946ef','#64748b',
          '#fb923c','#2dd4bf','#c084fc','#fbbf24','#34d399','#f472b6',
          '#38bdf8','#a3e635','#fb7185','#818cf8','#4ade80','#facc15',
        ];
        const DIM_ALPHA = 0.12;
        const FULL_WIDTH = 3;
        const DIM_WIDTH = 1;

        // Store original colors per dataset index for highlight toggling
        const teamColors = [];
        teams.forEach((t, i) => {
          const tid = String(t.team_id);
          const hist = history[tid] || [];
          if (hist.length === 0) return;
          const color = t.color_one || palette[i % palette.length];
          teamColors.push(color);
          datasets.push({
            label: t.team_abbrev || tid,
            data: hist.map(h => ({ x: h.week, y: h.elo })),
            borderColor: color,
            backgroundColor: color,
            fill: false,
            tension: 0.3,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderWidth: 1.5,
          });
        });

        const allWeeks = [...new Set(Object.values(history).flatMap(h => h.map(p => p.week)))].sort((a,b) => a-b);

        // Helper: dim a hex color
        function dimColor(hex, alpha) {
          const r = parseInt(hex.slice(1,3),16);
          const g = parseInt(hex.slice(3,5),16);
          const b = parseInt(hex.slice(5,7),16);
          return `rgba(${r},${g},${b},${alpha})`;
        }

        let highlightedIdx = null; // null = no highlight (all normal)

        function applyHighlight(chart, idx) {
          chart.data.datasets.forEach((ds, i) => {
            if (idx === null) {
              // Reset all to normal
              ds.borderColor = teamColors[i];
              ds.borderWidth = 1.5;
              ds.pointRadius = 0;
              ds.order = 0;
            } else if (i === idx) {
              // Highlighted team
              ds.borderColor = teamColors[i];
              ds.borderWidth = FULL_WIDTH;
              ds.pointRadius = 2;
              ds.order = -1; // draw on top
            } else {
              // Dimmed teams
              ds.borderColor = dimColor(teamColors[i], DIM_ALPHA);
              ds.borderWidth = DIM_WIDTH;
              ds.pointRadius = 0;
              ds.order = 1;
            }
          });
          chart.update();
        }

        rankEloChart = new Chart(ctx, {
          type: 'line',
          data: { labels: allWeeks.map(w => `Wk ${w}`), datasets },
          options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              title: { display: true, text: 'ELO Rating Over Time — click legend to highlight', color: '#f3f4f6' },
              legend: {
                labels: { color: '#9ca3af', boxWidth: 10, font: { size: 10 }, padding: 6 },
                position: 'right',
                onClick: function(e, legendItem, legend) {
                  const idx = legendItem.datasetIndex;
                  if (highlightedIdx === idx) {
                    // Clicking same team again: reset
                    highlightedIdx = null;
                  } else {
                    highlightedIdx = idx;
                  }
                  applyHighlight(legend.chart, highlightedIdx);
                },
              },
            },
            scales: {
              x: { ticks: { color: '#9ca3af', maxRotation: 45 }, grid: { color: '#1f2937' } },
              y: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' },
                   title: { display: true, text: 'ELO', color: '#9ca3af' } },
            },
          },
        });

        // Wire table row clicks to highlight
        document.querySelectorAll('#rank-elo-table tr[data-elo-idx]').forEach(row => {
          row.addEventListener('click', () => {
            const idx = parseInt(row.dataset.eloIdx, 10);
            if (highlightedIdx === idx) {
              highlightedIdx = null;
            } else {
              highlightedIdx = idx;
            }
            applyHighlight(rankEloChart, highlightedIdx);
            // Highlight the active row visually
            document.querySelectorAll('#rank-elo-table tr[data-elo-idx]').forEach(r => {
              r.style.background = '';
            });
            if (highlightedIdx !== null) {
              row.style.background = 'var(--bg-hover)';
            }
          });
        });
      })
      .catch(err => { status.textContent = 'Error: ' + err; });
  }

  // ---- Power Rankings ----
  function loadRankingsPower() {
    const lyid = document.getElementById('rank-pow-lyid').value;
    const level = document.getElementById('rank-pow-level').value;
    const weeks = document.getElementById('rank-pow-weeks').value;
    const status = document.getElementById('rank-pow-status');
    status.textContent = 'Loading...';
    document.getElementById('rank-pow-results').style.display = 'none';

    fetch(`${ADMIN_BASE}/analytics/rankings-power?league_year_id=${lyid}&league_level=${level}&recent_weeks=${weeks}`,
      { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.message || data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('rank-pow-results').style.display = '';

        const teams = data.teams || [];
        const weights = data.weights || {};

        // Table
        let html = '<table class="data-table"><thead><tr>' +
          '<th>Rank</th><th>Team</th><th>Score</th><th>W-L</th>' +
          '<th>ELO</th><th>Recent</th><th>Run Diff</th><th>Roster OVR</th>' +
          '</tr></thead><tbody>';
        teams.forEach(t => {
          const c = t.components || {};
          html += `<tr>
            <td>${t.rank}</td>
            <td><strong>${t.team_abbrev || t.team_id}</strong></td>
            <td><strong>${t.composite_score.toFixed(1)}</strong></td>
            <td>${t.wins}-${t.losses}</td>
            <td title="Raw: ${c.elo?.raw}">${c.elo?.normalized?.toFixed(1) ?? '-'}</td>
            <td title="Win%: ${c.recent?.raw?.toFixed(3)}">${c.recent?.normalized?.toFixed(1) ?? '-'}</td>
            <td title="Per game: ${c.run_diff?.raw}">${c.run_diff?.normalized?.toFixed(1) ?? '-'}</td>
            <td title="Raw: ${c.roster_ovr?.raw}">${c.roster_ovr?.normalized?.toFixed(1) ?? '-'}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        html += `<div style="margin-top:8px;color:var(--text-muted);font-size:0.85em">` +
          `Weights: ELO ${(weights.elo*100).toFixed(0)}% | Recent ${(weights.recent*100).toFixed(0)}% | ` +
          `Run Diff ${(weights.run_diff*100).toFixed(0)}% | Roster OVR ${(weights.roster_ovr*100).toFixed(0)}%</div>`;
        document.getElementById('rank-pow-table').innerHTML = html;

        // Horizontal bar chart
        if (rankPowChart) rankPowChart.destroy();
        const ctx = document.getElementById('rank-pow-chart').getContext('2d');
        const labels = teams.map(t => t.team_abbrev || t.team_id);
        rankPowChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: `ELO (${(weights.elo*100).toFixed(0)}%)`,
                data: teams.map(t => (t.components?.elo?.normalized || 0) * (weights.elo || 0)),
                backgroundColor: 'rgba(59, 130, 246, 0.8)',
              },
              {
                label: `Recent (${(weights.recent*100).toFixed(0)}%)`,
                data: teams.map(t => (t.components?.recent?.normalized || 0) * (weights.recent || 0)),
                backgroundColor: 'rgba(16, 185, 129, 0.8)',
              },
              {
                label: `Run Diff (${(weights.run_diff*100).toFixed(0)}%)`,
                data: teams.map(t => (t.components?.run_diff?.normalized || 0) * (weights.run_diff || 0)),
                backgroundColor: 'rgba(245, 158, 11, 0.8)',
              },
              {
                label: `Roster OVR (${(weights.roster_ovr*100).toFixed(0)}%)`,
                data: teams.map(t => (t.components?.roster_ovr?.normalized || 0) * (weights.roster_ovr || 0)),
                backgroundColor: 'rgba(139, 92, 246, 0.8)',
              },
            ],
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            plugins: {
              title: { display: true, text: 'Power Rankings Breakdown', color: '#f3f4f6' },
              legend: { labels: { color: '#9ca3af' } },
            },
            scales: {
              x: { stacked: true, ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' },
                   title: { display: true, text: 'Composite Score', color: '#9ca3af' } },
              y: { stacked: true, ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' } },
            },
          },
        });
      })
      .catch(err => { status.textContent = 'Error: ' + err; });
  }

  // ---- RPI ----
  function loadRankingsRpi() {
    const lyid = document.getElementById('rank-rpi-lyid').value;
    const level = document.getElementById('rank-rpi-level').value;
    const status = document.getElementById('rank-rpi-status');
    status.textContent = 'Loading...';
    document.getElementById('rank-rpi-results').style.display = 'none';

    fetch(`${ADMIN_BASE}/analytics/rankings-rpi?league_year_id=${lyid}&league_level=${level}`,
      { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.message || data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('rank-rpi-results').style.display = '';

        const teams = data.teams || [];
        let html = '<table class="data-table"><thead><tr>' +
          '<th>Rank</th><th>Team</th><th>RPI</th><th>Win%</th>' +
          '<th>OWP</th><th>OOWP</th><th>SOS</th><th>W</th><th>L</th>' +
          '</tr></thead><tbody>';
        teams.forEach(t => {
          html += `<tr>
            <td>${t.rank}</td>
            <td><strong>${t.team_abbrev || t.team_id}</strong></td>
            <td><strong>${t.rpi.toFixed(4)}</strong></td>
            <td>${t.wp.toFixed(3)}</td>
            <td>${t.owp.toFixed(3)}</td>
            <td>${t.oowp.toFixed(3)}</td>
            <td>${t.sos.toFixed(3)}</td>
            <td>${t.wins}</td><td>${t.losses}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('rank-rpi-table').innerHTML = html;
      })
      .catch(err => { status.textContent = 'Error: ' + err; });
  }

  // ---- Pythagorean ----
  function loadRankingsPyth() {
    const lyid = document.getElementById('rank-pyth-lyid').value;
    const level = document.getElementById('rank-pyth-level').value;
    const exp = document.getElementById('rank-pyth-exp').value;
    const status = document.getElementById('rank-pyth-status');
    status.textContent = 'Loading...';
    document.getElementById('rank-pyth-results').style.display = 'none';

    fetch(`${ADMIN_BASE}/analytics/rankings-pythagorean?league_year_id=${lyid}&league_level=${level}&exponent=${exp}`,
      { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.message || data.error || 'Error'; return; }
        status.textContent = '';
        document.getElementById('rank-pyth-results').style.display = '';

        const teams = data.teams || [];

        // Table
        let html = '<table class="data-table"><thead><tr>' +
          '<th>Rank</th><th>Team</th><th>W-L</th><th>Win%</th>' +
          '<th>RS</th><th>RA</th><th>Diff</th><th>R/G</th>' +
          '<th>Pyth%</th><th>ExpW</th><th>Luck</th>' +
          '<th>AVG</th><th>OPS</th><th>ERA</th><th>WHIP</th>' +
          '</tr></thead><tbody>';
        teams.forEach(t => {
          const b = t.batting || {};
          const p = t.pitching || {};
          const luckColor = t.luck > 0 ? 'var(--success)' : t.luck < 0 ? 'var(--danger)' : 'var(--text-secondary)';
          const diffColor = t.run_diff > 0 ? 'var(--success)' : t.run_diff < 0 ? 'var(--danger)' : 'var(--text-secondary)';
          html += `<tr>
            <td>${t.rank}</td>
            <td><strong>${t.team_abbrev || t.team_id}</strong></td>
            <td>${t.wins}-${t.losses}</td>
            <td>${t.win_pct.toFixed(3)}</td>
            <td>${t.runs_scored}</td>
            <td>${t.runs_allowed}</td>
            <td style="color:${diffColor}">${t.run_diff > 0 ? '+' : ''}${t.run_diff}</td>
            <td>${t.r_per_g}</td>
            <td>${t.pyth_pct.toFixed(3)}</td>
            <td>${t.expected_wins}</td>
            <td style="color:${luckColor};font-weight:bold">${t.luck > 0 ? '+' : ''}${t.luck}</td>
            <td>${b.avg?.toFixed(3) ?? '-'}</td>
            <td>${b.ops?.toFixed(3) ?? '-'}</td>
            <td>${p.era?.toFixed(2) ?? '-'}</td>
            <td>${p.whip?.toFixed(3) ?? '-'}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('rank-pyth-table').innerHTML = html;

        // Bar chart: actual vs expected wins
        if (rankPythChart) rankPythChart.destroy();
        const ctx = document.getElementById('rank-pyth-chart').getContext('2d');
        // Sort by actual wins for chart
        const sorted = [...teams].sort((a, b) => b.wins - a.wins);
        rankPythChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: sorted.map(t => t.team_abbrev || t.team_id),
            datasets: [
              {
                label: 'Actual Wins',
                data: sorted.map(t => t.wins),
                backgroundColor: 'rgba(59, 130, 246, 0.8)',
                borderColor: 'rgba(59, 130, 246, 1)',
                borderWidth: 1,
              },
              {
                label: 'Expected Wins',
                data: sorted.map(t => t.expected_wins),
                backgroundColor: 'rgba(245, 158, 11, 0.6)',
                borderColor: 'rgba(245, 158, 11, 1)',
                borderWidth: 1,
                borderDash: [5, 5],
              },
            ],
          },
          options: {
            responsive: true,
            plugins: {
              title: { display: true, text: 'Actual vs Pythagorean Expected Wins', color: '#f3f4f6' },
              legend: { labels: { color: '#9ca3af' } },
            },
            scales: {
              x: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' } },
              y: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' },
                   title: { display: true, text: 'Wins', color: '#9ca3af' } },
            },
          },
        });
      })
      .catch(err => { status.textContent = 'Error: ' + err; });
  }

  // ---- Race Chart ----
  let raceCharts = [];

  function loadRankingsRace() {
    const lyid = document.getElementById('rank-race-lyid').value;
    const level = document.getElementById('rank-race-level').value;
    const status = document.getElementById('rank-race-status');
    status.textContent = 'Loading...';
    const resultsDiv = document.getElementById('rank-race-results');
    resultsDiv.style.display = 'none';
    resultsDiv.innerHTML = '';
    raceCharts.forEach(c => c.destroy());
    raceCharts = [];

    fetch(`${ADMIN_BASE}/analytics/rankings-race?league_year_id=${lyid}&league_level=${level}`,
      { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { status.textContent = data.message || data.error || 'Error'; return; }
        status.textContent = '';
        resultsDiv.style.display = '';

        const groups = data.groups || {};
        const weeks = (data.weeks || []);
        const weekLabels = weeks.map(w => `Wk ${w}`);
        const palette = [
          '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
          '#ec4899','#06b6d4','#84cc16','#f97316','#6366f1',
          '#14b8a6','#e11d48','#a855f7','#22c55e','#eab308',
          '#0ea5e9','#d946ef','#64748b','#fb923c','#2dd4bf',
          '#c084fc','#fbbf24','#34d399','#f472b6','#38bdf8',
          '#a3e635','#fb7185','#818cf8','#4ade80','#facc15',
        ];

        const groupKeys = Object.keys(groups);

        groupKeys.forEach(groupName => {
          const teams = groups[groupName];
          const card = document.createElement('div');
          card.className = 'card';
          card.style.marginBottom = '16px';

          const title = document.createElement('h4');
          title.style.color = 'var(--text-primary)';
          title.style.marginBottom = '8px';
          title.textContent = groupName;
          card.appendChild(title);

          const canvas = document.createElement('canvas');
          canvas.height = 280;
          card.appendChild(canvas);

          resultsDiv.appendChild(card);

          const datasets = teams.map((t, i) => {
            const color = t.color_one || palette[i % palette.length];
            return {
              label: t.team_abbrev || String(t.team_id),
              data: (t.series || []).map(p => p.value),
              borderColor: color,
              backgroundColor: color,
              fill: false,
              tension: 0.3,
              pointRadius: 0,
              borderWidth: 2.5,
            };
          });

          const chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: { labels: weekLabels, datasets },
            options: {
              responsive: true,
              interaction: { mode: 'index', intersect: false },
              plugins: {
                legend: {
                  labels: { color: '#9ca3af', boxWidth: 12, font: { size: 11 } },
                  position: 'bottom',
                },
              },
              scales: {
                x: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' } },
                y: {
                  ticks: { color: '#9ca3af' },
                  grid: { color: '#1f2937' },
                  title: { display: true, text: 'Games Above/Below .500', color: '#9ca3af' },
                },
              },
            },
          });
          raceCharts.push(chart);
        });
      })
      .catch(err => { status.textContent = 'Error: ' + err; });
  }

  // ─── Tutorial Content Management ──────────────────────────────────────────

  let _tutManifest = null;
  let _tutEditingCat = null;
  let _tutEditingArt = null;

  function _tutStatus(msg) {
    const el = document.getElementById('tut-status');
    if (el) el.textContent = msg;
  }

  function _tutShowView(view) {
    // view: 'list' | 'editor' | 'new-category' | 'glossary' | 'new-article'
    document.getElementById('tut-categories-list').style.display = view === 'list' ? '' : 'none';
    document.getElementById('tut-article-editor').style.display = view === 'editor' ? '' : 'none';
    document.getElementById('tut-new-category-form').style.display = view === 'new-category' ? '' : 'none';
    document.getElementById('tut-glossary-editor').style.display = view === 'glossary' ? '' : 'none';
    document.getElementById('tut-new-article-form').style.display = view === 'new-article' ? '' : 'none';
  }

  function loadTutorialManifest() {
    _tutStatus('Loading…');
    _tutShowView('list');
    fetch(`${ADMIN_BASE}/tutorial/manifest`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { _tutStatus('Error: ' + (data.error || 'unknown')); return; }
        _tutManifest = data.manifest;
        _renderTutorialCategories();
        _tutStatus(`${_tutManifest.categories.length} categories, ${_tutManifest.categories.reduce((s,c) => s + (c.articles||[]).length, 0)} articles`);
      })
      .catch(err => _tutStatus('Error: ' + err));
  }

  function _renderTutorialCategories() {
    const container = document.getElementById('tut-categories-list');
    const cats = (_tutManifest.categories || []).slice().sort((a,b) => a.order - b.order);
    if (!cats.length) {
      container.innerHTML = '<div class="card"><p class="text-muted">No categories yet.</p></div>';
      return;
    }

    let html = '';
    for (const cat of cats) {
      const leagueBadge = cat.leagueFilter
        ? `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:${cat.leagueFilter==='MLB'?'var(--accent)':'var(--success)'};color:#fff;margin-left:8px">${cat.leagueFilter}</span>`
        : '';
      const articles = (cat.articles || []).slice().sort((a,b) => a.order - b.order);

      html += `<div class="card" style="margin-bottom:12px">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
          <h3 style="margin:0">${_esc(cat.title)}</h3>
          <span class="text-muted">${_esc(cat.icon)}</span>
          ${leagueBadge}
          <span class="text-muted" style="font-size:12px">order: ${cat.order}</span>
          <div style="margin-left:auto;display:flex;gap:8px">
            <button class="btn btn-secondary btn-sm" onclick="App.tutEditCategory('${cat.id}')">Edit</button>
            <button class="btn btn-primary btn-sm" onclick="App.tutNewArticle('${cat.id}')">+ Article</button>
            <button class="btn btn-danger btn-sm" onclick="App.tutDeleteCategory('${cat.id}')">Delete</button>
          </div>
        </div>
        <p class="text-muted" style="margin-bottom:12px">${_esc(cat.description)}</p>`;

      if (articles.length) {
        html += `<table class="data-table"><thead><tr>
          <th>#</th><th>Title</th><th>ID</th><th>Tags</th><th>League</th><th>Action</th>
        </tr></thead><tbody>`;
        for (const art of articles) {
          const artLeague = art.leagueFilter || '—';
          html += `<tr>
            <td>${art.order}</td>
            <td>${_esc(art.title)}</td>
            <td><code>${_esc(art.id)}</code></td>
            <td>${(art.tags||[]).map(t => `<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;background:var(--bg-input);margin:1px">${_esc(t)}</span>`).join(' ')}</td>
            <td>${artLeague}</td>
            <td style="white-space:nowrap"><button class="btn btn-secondary btn-sm" onclick="App.tutOpenArticle('${cat.id}','${art.id}')">Edit</button> <button class="btn btn-secondary btn-sm" onclick="App.tutDuplicateArticle('${cat.id}','${art.id}')">Dup</button></td>
          </tr>`;
        }
        html += '</tbody></table>';
      } else {
        html += '<p class="text-muted" style="font-size:13px">No articles yet.</p>';
      }

      html += '</div>';
    }
    container.innerHTML = html;
  }

  function _esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Open article for editing ──
  function tutOpenArticle(catId, artId) {
    _tutStatus('Loading article…');
    fetch(`${ADMIN_BASE}/tutorial/article/${catId}/${artId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { _tutStatus('Error: ' + (data.error || 'unknown')); return; }
        _tutEditingCat = catId;
        _tutEditingArt = artId;
        const art = data.article;
        document.getElementById('tut-art-id').value = artId;
        document.getElementById('tut-art-title').value = art.title || '';
        document.getElementById('tut-art-summary').value = art.summary || '';
        document.getElementById('tut-art-tags').value = (art.tags || []).join(', ');
        document.getElementById('tut-art-league').value = art.leagueFilter || '';
        document.getElementById('tut-art-related').value = (art.relatedArticles || []).join(', ');
        document.getElementById('tut-art-markdown').value = data.markdown || '';
        document.getElementById('tut-editor-title').textContent = 'Edit: ' + (art.title || artId);
        document.getElementById('tut-save-status').textContent = '';
        document.getElementById('tut-validation-bar').style.display = 'none';
        _tutShowView('editor');
        _tutRenderPreview();
        _tutStatus('');
      })
      .catch(err => _tutStatus('Error: ' + err));
  }

  // ── Save article ──
  function tutSaveArticle() {
    if (!_tutEditingCat || !_tutEditingArt) return;
    const saveStatus = document.getElementById('tut-save-status');
    const saveStatusBottom = document.getElementById('tut-save-status-bottom');
    const _setStatus = (msg, color) => {
      if (saveStatus) { saveStatus.textContent = msg; saveStatus.style.color = color || ''; }
      if (saveStatusBottom) { saveStatusBottom.textContent = msg; saveStatusBottom.style.color = color || ''; }
    };

    // Validate first
    const markdown = document.getElementById('tut-art-markdown').value;
    const errors = _tutValidate(markdown);
    _tutShowValidation(errors);
    if (errors.length) {
      _setStatus(`${errors.length} validation error(s) — fix before saving`, 'var(--danger)');
      return;
    }
    _setStatus('Saving…', '');

    const today = new Date().toISOString().slice(0, 10);
    const tags = document.getElementById('tut-art-tags').value
      .split(',').map(t => t.trim()).filter(Boolean);
    const related = document.getElementById('tut-art-related').value
      .split(',').map(t => t.trim()).filter(Boolean);

    const body = {
      title: document.getElementById('tut-art-title').value.trim(),
      summary: document.getElementById('tut-art-summary').value.trim(),
      tags,
      leagueFilter: document.getElementById('tut-art-league').value || null,
      relatedArticles: related,
      lastUpdated: today,
      markdown: document.getElementById('tut-art-markdown').value,
    };

    fetch(`${ADMIN_BASE}/tutorial/article/${_tutEditingCat}/${_tutEditingArt}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          _setStatus('Saved ✓', 'var(--success)');
        } else {
          _setStatus('Error: ' + (data.error || 'unknown'), 'var(--danger)');
        }
      })
      .catch(err => {
        _setStatus('Error: ' + err, 'var(--danger)');
      });
  }

  // ── Delete article ──
  function tutDeleteArticle() {
    if (!_tutEditingCat || !_tutEditingArt) return;
    if (!confirm(`Delete article "${_tutEditingArt}" from "${_tutEditingCat}"? This cannot be undone.`)) return;

    fetch(`${ADMIN_BASE}/tutorial/article/${_tutEditingCat}/${_tutEditingArt}`, {
      method: 'DELETE',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          _tutEditingCat = null;
          _tutEditingArt = null;
          loadTutorialManifest();
        } else {
          alert('Delete failed: ' + (data.error || 'unknown'));
        }
      })
      .catch(err => alert('Delete failed: ' + err));
  }

  // ── Duplicate article ──
  function tutDuplicateArticle(catId, artId) {
    _tutStatus('Loading article for duplication…');
    fetch(`${ADMIN_BASE}/tutorial/article/${catId}/${artId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) { _tutStatus('Error: ' + (data.error || 'unknown')); return; }
        const art = data.article;
        const newId = prompt('New article ID (slug):', artId + '-copy');
        if (!newId || !newId.trim()) { _tutStatus(''); return; }

        const today = new Date().toISOString().slice(0, 10);
        const body = {
          id: newId.trim(),
          title: art.title + ' (Copy)',
          summary: art.summary,
          tags: art.tags || [],
          leagueFilter: art.leagueFilter,
          relatedArticles: art.relatedArticles || [],
          lastUpdated: today,
          markdown: data.markdown || '',
        };

        fetch(`${ADMIN_BASE}/tutorial/article/${catId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(body),
        })
          .then(r => r.json())
          .then(res => {
            if (res.ok) {
              _tutStatus('Duplicated ✓');
              loadTutorialManifest();
            } else {
              alert('Duplicate failed: ' + (res.error || 'unknown'));
              _tutStatus('');
            }
          })
          .catch(err => { alert('Duplicate failed: ' + err); _tutStatus(''); });
      })
      .catch(err => { _tutStatus('Error: ' + err); });
  }

  // ── New article ──
  function tutNewArticle(catId) {
    document.getElementById('tut-newart-cat').value = catId;
    document.getElementById('tut-newart-id').value = '';
    document.getElementById('tut-newart-title').value = '';
    document.getElementById('tut-newart-summary').value = '';
    document.getElementById('tut-newart-tags').value = '';
    document.getElementById('tut-newart-league').value = '';
    document.getElementById('tut-newart-markdown').value = '';
    _tutShowView('new-article');
  }

  function tutSaveNewArticle() {
    const catId = document.getElementById('tut-newart-cat').value;
    const artId = document.getElementById('tut-newart-id').value.trim();
    const title = document.getElementById('tut-newart-title').value.trim();
    if (!artId || !title) { alert('ID and Title are required'); return; }

    const today = new Date().toISOString().slice(0, 10);
    const tags = document.getElementById('tut-newart-tags').value
      .split(',').map(t => t.trim()).filter(Boolean);

    const body = {
      id: artId,
      title,
      summary: document.getElementById('tut-newart-summary').value.trim(),
      tags,
      leagueFilter: document.getElementById('tut-newart-league').value || null,
      lastUpdated: today,
      markdown: document.getElementById('tut-newart-markdown').value,
    };

    fetch(`${ADMIN_BASE}/tutorial/article/${catId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          loadTutorialManifest();
        } else {
          alert('Create failed: ' + (data.error || 'unknown'));
        }
      })
      .catch(err => alert('Create failed: ' + err));
  }

  // ── New category ──
  function tutShowNewCategory() {
    document.getElementById('tut-newcat-id').value = '';
    document.getElementById('tut-newcat-title').value = '';
    document.getElementById('tut-newcat-desc').value = '';
    document.getElementById('tut-newcat-icon').value = 'compass';
    document.getElementById('tut-newcat-league').value = '';
    _tutShowView('new-category');
  }

  function tutSaveNewCategory() {
    const catId = document.getElementById('tut-newcat-id').value.trim();
    const title = document.getElementById('tut-newcat-title').value.trim();
    if (!catId || !title) { alert('ID and Title are required'); return; }

    const body = {
      id: catId,
      title,
      icon: document.getElementById('tut-newcat-icon').value,
      description: document.getElementById('tut-newcat-desc').value.trim(),
      leagueFilter: document.getElementById('tut-newcat-league').value || null,
    };

    fetch(`${ADMIN_BASE}/tutorial/category`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          loadTutorialManifest();
        } else {
          alert('Create failed: ' + (data.error || 'unknown'));
        }
      })
      .catch(err => alert('Create failed: ' + err));
  }

  // ── Edit category (inline prompt) ──
  function tutEditCategory(catId) {
    const cat = (_tutManifest.categories || []).find(c => c.id === catId);
    if (!cat) return;

    const newTitle = prompt('Category title:', cat.title);
    if (newTitle === null) return;
    const newDesc = prompt('Description:', cat.description);
    if (newDesc === null) return;
    const newIcon = prompt('Icon key:', cat.icon);
    if (newIcon === null) return;
    const newOrder = prompt('Order:', cat.order);
    if (newOrder === null) return;

    const body = {
      title: newTitle,
      description: newDesc,
      icon: newIcon,
      order: parseInt(newOrder, 10) || cat.order,
    };

    fetch(`${ADMIN_BASE}/tutorial/category/${catId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) loadTutorialManifest();
        else alert('Update failed: ' + (data.error || 'unknown'));
      })
      .catch(err => alert('Update failed: ' + err));
  }

  // ── Delete category ──
  function tutDeleteCategory(catId) {
    const cat = (_tutManifest.categories || []).find(c => c.id === catId);
    if (!cat) return;
    const count = (cat.articles || []).length;
    if (!confirm(`Delete category "${cat.title}" and its ${count} article(s)? This cannot be undone.`)) return;

    fetch(`${ADMIN_BASE}/tutorial/category/${catId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) loadTutorialManifest();
        else alert('Delete failed: ' + (data.error || 'unknown'));
      })
      .catch(err => alert('Delete failed: ' + err));
  }

  // ── Glossary editor ──
  function tutOpenGlossary() {
    if (!_tutManifest) return;
    const glossary = _tutManifest.glossary || {};
    const container = document.getElementById('tut-glossary-rows');
    let html = '';
    for (const [term, def] of Object.entries(glossary)) {
      html += _glossaryRow(term, def);
    }
    container.innerHTML = html;
    _tutShowView('glossary');
  }

  function _glossaryRow(term, def) {
    return `<div class="tut-glossary-row" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
      <input type="text" class="input tut-gl-term" value="${_esc(term)}" style="width:160px;font-weight:600" placeholder="Term" />
      <input type="text" class="input tut-gl-def" value="${_esc(def)}" style="flex:1" placeholder="Definition" />
      <button class="btn btn-danger btn-sm" onclick="this.parentElement.remove()">×</button>
    </div>`;
  }

  function tutAddGlossaryRow() {
    const container = document.getElementById('tut-glossary-rows');
    container.insertAdjacentHTML('beforeend', _glossaryRow('', ''));
  }

  function tutSaveGlossary() {
    const rows = document.querySelectorAll('.tut-glossary-row');
    const glossary = {};
    rows.forEach(row => {
      const term = row.querySelector('.tut-gl-term').value.trim();
      const def = row.querySelector('.tut-gl-def').value.trim();
      if (term) glossary[term] = def;
    });

    fetch(`${ADMIN_BASE}/tutorial/glossary`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ glossary }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          _tutManifest.glossary = glossary;
          _tutStatus('Glossary saved ✓');
          _tutShowView('list');
        } else {
          alert('Save failed: ' + (data.error || 'unknown'));
        }
      })
      .catch(err => alert('Save failed: ' + err));
  }

  // ── Insert block templates ──
  const _TUT_TEMPLATES = {
    'glossary': '[term]{definition}',
    'rating': ':::rating\nattribute: \nscale: 20-80\nexample: 50\ndescription: \n:::\n',
    'callout-tip': ':::callout type=tip\n\n:::\n',
    'callout-info': ':::callout type=info\n\n:::\n',
    'callout-warning': ':::callout type=warning\n\n:::\n',
    'callout-important': ':::callout type=important\n\n:::\n',
    'compare': ':::compare\n| | Option A | Option B |\n|---|---|---|\n| Metric | Value | Value |\n:::\n',
    'link': ':::link\ntarget: team\nlabel: Go to your team →\nleague: auto\n:::\n',
    'detail': ':::detail title=""\n\n:::\n',
    'player-hitter': ':::player-example\nposition: CF\nattributes:\n  contact: 50\n  power: 50\n  eye: 50\n  speed: 50\n  fielding: 50\ncaption: ""\n:::\n',
    'player-pitcher': ':::player-example\nposition: SP\nattributes:\n  stuff: 50\n  control: 50\n  stamina: 50\n  velocity: 50\ncaption: ""\n:::\n',
    'league-mlb': ':::league filter=MLB\n\n:::\n',
    'league-college': ':::league filter=College\n\n:::\n',
  };

  function _tutInsertBlock(key) {
    const ta = document.getElementById('tut-art-markdown');
    if (!ta) return;
    const template = _TUT_TEMPLATES[key];
    if (!template) return;

    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const text = ta.value;

    // Ensure we're on a fresh line
    const prefix = (start > 0 && text[start - 1] !== '\n') ? '\n\n' : (start > 1 && text[start - 2] !== '\n') ? '\n' : '';

    ta.value = text.slice(0, start) + prefix + template + text.slice(end);
    // Place cursor inside the block (after the opening line)
    const cursorPos = start + prefix.length + template.indexOf('\n') + 1;
    ta.selectionStart = ta.selectionEnd = cursorPos;
    ta.focus();
    _tutUpdatePreview();
  }

  // ── Live preview renderer ──
  let _tutPreviewTimer = null;

  function _tutUpdatePreview() {
    clearTimeout(_tutPreviewTimer);
    _tutPreviewTimer = setTimeout(_tutRenderPreview, 250);
  }

  function _tutRenderPreview() {
    const ta = document.getElementById('tut-art-markdown');
    const pane = document.getElementById('tut-preview-pane');
    if (!ta || !pane) return;

    const md = ta.value;
    pane.innerHTML = _tutMdToHtml(md);
  }

  function _tutMdToHtml(md) {
    // Split into segments: custom blocks (:::) and regular markdown
    const lines = md.split('\n');
    let html = '';
    let i = 0;
    let mdBuf = [];

    function flushMd() {
      if (mdBuf.length) {
        html += _tutRenderBasicMd(mdBuf.join('\n'));
        mdBuf = [];
      }
    }

    while (i < lines.length) {
      const line = lines[i];
      const blockMatch = line.match(/^:::(rating|callout|compare|link|detail|player-example|league)\b(.*)/);
      if (blockMatch) {
        flushMd();
        const blockType = blockMatch[1];
        const blockArgs = blockMatch[2].trim();
        const blockLines = [];
        i++;
        while (i < lines.length && lines[i].trim() !== ':::') {
          blockLines.push(lines[i]);
          i++;
        }
        i++; // skip closing :::
        html += _tutRenderBlock(blockType, blockArgs, blockLines);
      } else {
        mdBuf.push(line);
        i++;
      }
    }
    flushMd();
    return html;
  }

  function _tutRenderBasicMd(text) {
    // Minimal markdown -> HTML for preview
    let html = '';
    const paragraphs = text.split(/\n{2,}/);
    for (const para of paragraphs) {
      const trimmed = para.trim();
      if (!trimmed) continue;

      // Headings
      if (trimmed.startsWith('#### ')) {
        html += `<h4 style="color:var(--text-primary);margin:16px 0 8px;font-size:14px">${_tutInline(trimmed.slice(5))}</h4>`;
      } else if (trimmed.startsWith('### ')) {
        html += `<h3 style="color:var(--text-primary);margin:20px 0 10px;font-size:16px">${_tutInline(trimmed.slice(4))}</h3>`;
      } else if (trimmed.startsWith('## ')) {
        html += `<h2 style="color:var(--text-primary);margin:24px 0 12px;font-size:18px;border-bottom:1px solid var(--border);padding-bottom:6px">${_tutInline(trimmed.slice(3))}</h2>`;
      } else if (trimmed.match(/^[-*] /m)) {
        // Unordered list
        const items = trimmed.split('\n').filter(l => l.match(/^[-*] /));
        html += '<ul style="margin:8px 0 12px 20px;color:var(--text-secondary)">';
        for (const item of items) html += `<li style="margin:3px 0">${_tutInline(item.replace(/^[-*] /, ''))}</li>`;
        html += '</ul>';
      } else if (trimmed.match(/^\d+\. /m)) {
        // Ordered list
        const items = trimmed.split('\n').filter(l => l.match(/^\d+\. /));
        html += '<ol style="margin:8px 0 12px 20px;color:var(--text-secondary)">';
        for (const item of items) html += `<li style="margin:3px 0">${_tutInline(item.replace(/^\d+\. /, ''))}</li>`;
        html += '</ol>';
      } else {
        html += `<p style="margin:8px 0;color:var(--text-secondary)">${_tutInline(trimmed.replace(/\n/g, ' '))}</p>`;
      }
    }
    return html;
  }

  function _tutInline(text) {
    let s = _esc(text);
    // Glossary tooltips [term]{definition}
    s = s.replace(/\[([^\]]+)\]\{([^}]+)\}/g,
      '<span style="color:var(--accent);border-bottom:1px dotted var(--accent);cursor:help" title="$2">$1</span>');
    // Bold
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--text-primary)">$1</strong>');
    // Italic
    s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Inline code
    s = s.replace(/`([^`]+)`/g, '<code style="background:var(--bg-input);padding:1px 5px;border-radius:3px;font-size:12px">$1</code>');
    return s;
  }

  function _tutRenderBlock(type, args, lines) {
    const content = lines.join('\n');
    switch (type) {
      case 'rating': return _tutRenderRating(lines);
      case 'callout': return _tutRenderCallout(args, content);
      case 'compare': return _tutRenderCompare(lines);
      case 'link': return _tutRenderLink(lines);
      case 'detail': return _tutRenderDetail(args, content);
      case 'player-example': return _tutRenderPlayerCard(lines);
      case 'league': return _tutRenderLeague(args, content);
      default: return `<div style="padding:8px;border:1px dashed var(--border);margin:8px 0;color:var(--text-muted)">Unknown block: ${type}</div>`;
    }
  }

  function _tutParseFields(lines) {
    const fields = {};
    for (const line of lines) {
      const m = line.match(/^(\w[\w-]*):\s*(.+)/);
      if (m) fields[m[1]] = m[2].trim();
    }
    return fields;
  }

  function _tutRenderRating(lines) {
    const f = _tutParseFields(lines);
    const attr = f.attribute || '?';
    const scale = f.scale || '20-80';
    const [min, max] = scale.split('-').map(Number);
    const example = parseInt(f.example || '50', 10);
    const desc = f.description || '';
    const pct = Math.max(0, Math.min(100, ((example - min) / (max - min)) * 100));
    const color = pct < 30 ? 'var(--danger)' : pct < 50 ? 'var(--warning)' : pct < 75 ? 'var(--accent)' : 'var(--success)';

    return `<div style="margin:12px 0;padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm)">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <span style="font-weight:600;color:var(--text-primary)">${_esc(attr)}</span>
        <span style="background:${color};color:#fff;padding:2px 10px;border-radius:12px;font-size:13px;font-weight:700">${example}</span>
      </div>
      <div style="height:8px;background:var(--bg-input);border-radius:4px;overflow:hidden;margin-bottom:4px">
        <div style="width:${pct}%;height:100%;background:${color};border-radius:4px;transition:width .3s"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:6px">
        <span>${min}</span><span>${max}</span>
      </div>
      <div style="font-size:13px;color:var(--text-secondary)">${_esc(desc)}</div>
    </div>`;
  }

  function _tutRenderCallout(args, content) {
    const typeMatch = args.match(/type=(\w+)/);
    const ctype = typeMatch ? typeMatch[1] : 'info';
    const colors = { tip: 'var(--success)', info: 'var(--info)', warning: 'var(--warning)', important: 'var(--danger)' };
    const icons = { tip: '💡', info: 'ℹ️', warning: '⚠️', important: '❗' };
    const color = colors[ctype] || colors.info;
    const icon = icons[ctype] || icons.info;
    const label = ctype.charAt(0).toUpperCase() + ctype.slice(1);

    return `<div style="margin:12px 0;padding:12px 14px;background:var(--bg-card);border-left:4px solid ${color};border-radius:var(--radius-sm)">
      <div style="font-size:12px;font-weight:700;color:${color};margin-bottom:6px">${icon} ${label}</div>
      <div style="color:var(--text-secondary);font-size:13px">${_tutInline(content.trim())}</div>
    </div>`;
  }

  function _tutRenderCompare(lines) {
    // Parse markdown table
    const tableLines = lines.filter(l => l.trim().startsWith('|'));
    if (tableLines.length < 2) return '<div style="color:var(--text-muted);margin:8px 0">Compare block: no table found</div>';

    let html = '<div style="margin:12px 0;overflow-x:auto"><table class="data-table" style="width:100%;font-size:13px">';
    tableLines.forEach((line, idx) => {
      if (line.replace(/[|\-\s]/g, '').length === 0) return; // separator row
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      const tag = idx === 0 ? 'th' : 'td';
      html += '<tr>';
      cells.forEach(cell => { html += `<${tag} style="padding:6px 10px">${_tutInline(cell)}</${tag}>`; });
      html += '</tr>';
    });
    html += '</table></div>';
    return html;
  }

  function _tutRenderLink(lines) {
    const f = _tutParseFields(lines);
    return `<div style="margin:12px 0">
      <div style="display:inline-block;padding:10px 20px;background:var(--accent);color:#fff;border-radius:var(--radius-sm);font-weight:600;font-size:14px;cursor:default">
        ${_esc(f.label || 'Link')} →
      </div>
      <span style="font-size:11px;color:var(--text-muted);margin-left:8px">→ ${_esc(f.target || '?')} (${_esc(f.league || 'auto')})</span>
    </div>`;
  }

  function _tutRenderDetail(args, content) {
    const titleMatch = args.match(/title="([^"]*)"/);
    const title = titleMatch ? titleMatch[1] : 'Details';
    return `<details style="margin:12px 0;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card)">
      <summary style="padding:10px 14px;cursor:pointer;font-weight:600;color:var(--text-primary);font-size:14px">${_esc(title)}</summary>
      <div style="padding:10px 14px;border-top:1px solid var(--border);color:var(--text-secondary);font-size:13px">${_tutRenderBasicMd(content)}</div>
    </details>`;
  }

  function _tutRenderPlayerCard(lines) {
    const f = _tutParseFields(lines);
    const position = f.position || '??';
    const caption = (f.caption || '').replace(/^"|"$/g, '');
    // Parse attributes (indented lines)
    const attrs = {};
    let inAttrs = false;
    for (const line of lines) {
      if (line.trim().startsWith('attributes:')) { inAttrs = true; continue; }
      if (inAttrs) {
        const am = line.match(/^\s+(\w+):\s*(\d+)/);
        if (am) attrs[am[1]] = parseInt(am[2], 10);
        else inAttrs = false;
      }
    }

    let attrHtml = '';
    for (const [k, v] of Object.entries(attrs)) {
      const color = v >= 65 ? 'var(--accent)' : v >= 55 ? 'var(--success)' : v >= 45 ? 'var(--text-secondary)' : 'var(--danger)';
      attrHtml += `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--bg-input)">
        <span style="color:var(--text-muted);font-size:12px;text-transform:capitalize">${k}</span>
        <span style="font-weight:700;color:${color};font-size:13px">${v}</span>
      </div>`;
    }

    return `<div style="margin:12px 0;padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm);max-width:280px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <span style="background:var(--accent);color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700">${_esc(position)}</span>
        <span style="font-size:12px;color:var(--text-muted)">Example Player</span>
      </div>
      ${attrHtml}
      ${caption ? `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border);font-size:12px;color:var(--text-secondary);font-style:italic">${_esc(caption)}</div>` : ''}
    </div>`;
  }

  function _tutRenderLeague(args, content) {
    const filterMatch = args.match(/filter=(\w+)/);
    const league = filterMatch ? filterMatch[1] : '?';
    const color = league === 'MLB' ? 'var(--accent)' : 'var(--success)';
    return `<div style="margin:12px 0;padding:12px 14px;border:1px dashed ${color};border-radius:var(--radius-sm);position:relative">
      <span style="position:absolute;top:-8px;left:12px;background:var(--bg-dark);padding:0 6px;font-size:11px;font-weight:700;color:${color}">${_esc(league)}</span>
      <div style="color:var(--text-secondary);font-size:13px">${_tutRenderBasicMd(content)}</div>
    </div>`;
  }

  // ── Validation ──
  function _tutValidate(md) {
    const errors = [];
    const lines = md.split('\n');
    let i = 0;
    let blockStack = [];

    while (i < lines.length) {
      const line = lines[i];
      const openMatch = line.match(/^:::(rating|callout|compare|link|detail|player-example|league)\b(.*)/);
      if (openMatch) {
        blockStack.push({ type: openMatch[1], args: openMatch[2].trim(), line: i + 1 });
      } else if (line.trim() === ':::' && blockStack.length) {
        const block = blockStack.pop();
        // Validate block-specific fields
        const blockLines = lines.slice(block.line, i);
        _tutValidateBlock(block.type, block.args, blockLines, block.line, errors);
      } else if (line.trim() === ':::' && !blockStack.length) {
        errors.push(`Line ${i + 1}: Closing ::: without a matching opening block`);
      }
      i++;
    }

    // Unclosed blocks
    for (const b of blockStack) {
      errors.push(`Line ${b.line}: :::${b.type} block never closed (missing :::)`);
    }

    // Check glossary bracket matching
    const glossaryRe = /\[([^\]]*)\]\{([^}]*)\}/g;
    // Check for unmatched patterns
    const partial1 = /\[[^\]]*\]\{[^}]*$/gm;
    const partial2 = /\[[^\]]*\]$/gm;
    let lineNum = 0;
    for (const ln of lines) {
      lineNum++;
      if (ln.match(/\[[^\]]*\]\{/) && !ln.match(/\[[^\]]*\]\{[^}]*\}/)) {
        errors.push(`Line ${lineNum}: Glossary tooltip has unclosed {definition}`);
      }
    }

    return errors;
  }

  function _tutValidateBlock(type, args, lines, lineNum, errors) {
    const fields = {};
    for (const l of lines) {
      const m = l.match(/^(\w[\w-]*):\s*(.+)/);
      if (m) fields[m[1]] = m[2].trim();
    }

    switch (type) {
      case 'rating':
        for (const f of ['attribute', 'scale', 'example', 'description']) {
          if (!fields[f]) errors.push(`Line ${lineNum}: :::rating missing required field "${f}"`);
        }
        break;
      case 'callout': {
        const m = args.match(/type=(\w+)/);
        if (!m) errors.push(`Line ${lineNum}: :::callout missing type= (tip|info|warning|important)`);
        else if (!['tip','info','warning','important'].includes(m[1]))
          errors.push(`Line ${lineNum}: :::callout type="${m[1]}" is not valid (use tip|info|warning|important)`);
        break;
      }
      case 'compare': {
        const tableLines = lines.filter(l => l.trim().startsWith('|'));
        if (tableLines.length < 2) errors.push(`Line ${lineNum}: :::compare must contain a markdown table`);
        break;
      }
      case 'link':
        for (const f of ['target', 'label', 'league']) {
          if (!fields[f]) errors.push(`Line ${lineNum}: :::link missing required field "${f}"`);
        }
        break;
      case 'detail': {
        if (!args.match(/title="[^"]*"/)) errors.push(`Line ${lineNum}: :::detail missing title="..." attribute`);
        break;
      }
      case 'player-example':
        if (!fields.position) errors.push(`Line ${lineNum}: :::player-example missing "position" field`);
        if (!lines.some(l => l.match(/^\s+\w+:\s*\d+/))) errors.push(`Line ${lineNum}: :::player-example has no attributes`);
        break;
      case 'league': {
        const m = args.match(/filter=(\w+)/);
        if (!m) errors.push(`Line ${lineNum}: :::league missing filter= (MLB|College)`);
        else if (!['MLB','College'].includes(m[1]))
          errors.push(`Line ${lineNum}: :::league filter="${m[1]}" is not valid (use MLB|College)`);
        break;
      }
    }
  }

  function _tutShowValidation(errors) {
    const bar = document.getElementById('tut-validation-bar');
    if (!bar) return;
    if (!errors.length) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = 'block';
    bar.style.background = 'rgba(239,68,68,0.1)';
    bar.style.border = '1px solid var(--danger)';
    bar.style.color = 'var(--danger)';
    bar.innerHTML = `<strong>⚠ ${errors.length} issue${errors.length > 1 ? 's' : ''} found:</strong><ul style="margin:6px 0 0 18px">${errors.map(e => `<li>${_esc(e)}</li>`).join('')}</ul>`;
  }

  // ── Tutorial event listeners ──
  function _setupTutorialListeners() {
    const btn = (id, fn) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', fn);
    };
    btn('btn-tut-refresh', loadTutorialManifest);
    btn('btn-tut-new-category', tutShowNewCategory);
    btn('btn-tut-edit-glossary', tutOpenGlossary);
    btn('btn-tut-back', () => { _tutEditingCat = null; _tutEditingArt = null; loadTutorialManifest(); });
    btn('btn-tut-save', tutSaveArticle);
    btn('btn-tut-save-bottom', tutSaveArticle);
    btn('btn-tut-delete-article', tutDeleteArticle);
    btn('btn-tut-newcat-save', tutSaveNewCategory);
    btn('btn-tut-newcat-cancel', () => _tutShowView('list'));
    btn('btn-tut-glossary-back', () => _tutShowView('list'));
    btn('btn-tut-glossary-save', tutSaveGlossary);
    btn('btn-tut-glossary-add', tutAddGlossaryRow);
    btn('btn-tut-newart-save', tutSaveNewArticle);
    btn('btn-tut-newart-cancel', () => _tutShowView('list'));

    // Insert toolbar buttons
    document.querySelectorAll('.tut-insert-btn').forEach(btn => {
      btn.addEventListener('click', () => _tutInsertBlock(btn.dataset.tutInsert));
    });

    // Live preview on textarea input
    const ta = document.getElementById('tut-art-markdown');
    if (ta) {
      ta.addEventListener('input', _tutUpdatePreview);
      // Tab key inserts spaces instead of jumping focus
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
          e.preventDefault();
          const start = ta.selectionStart;
          ta.value = ta.value.slice(0, start) + '  ' + ta.value.slice(ta.selectionEnd);
          ta.selectionStart = ta.selectionEnd = start + 2;
          _tutUpdatePreview();
        }
      });
    }
  }

  // Expose to global App for inline onclick handlers
  window.App = window.App || {};
  Object.assign(window.App, {
    faOpenOffer,
    faUpdateTotals,
    tutOpenArticle,
    tutNewArticle,
    tutDuplicateArticle,
    tutEditCategory,
    tutDeleteCategory,
  });

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
