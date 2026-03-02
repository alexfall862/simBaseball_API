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

    // Timestamp
    document.getElementById('btn-refresh-timestamp').addEventListener('click', loadTimestamp);
    document.getElementById('btn-advance-week').addEventListener('click', advanceWeek);
    document.getElementById('btn-reset-week').addEventListener('click', resetWeekGames);

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

    // Overall Weights
    document.getElementById('btn-load-weights').addEventListener('click', loadOverallWeights);
    document.getElementById('btn-save-weights').addEventListener('click', saveOverallWeights);

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

    // Amateur Seeding
    document.getElementById('btn-amateur-preview').addEventListener('click', loadAmateurPreview);
    document.getElementById('btn-amateur-seed').addEventListener('click', runAmateurSeed);

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
      'pe-generate': 'Player Generation',
      'pe-progress': 'Player Progression',
      'pe-sandbox': 'Progression Sandbox',
      'tx-eos': 'End of Season',
      'tx-amateur': 'Amateur Seeding',
      migrations: 'Migrations',
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
    if (isAuthenticated) {
      statusDot.classList.remove('offline');
      statusDot.classList.add('online');
      elements.authText.textContent = 'Authenticated';
      elements.btnLogin.style.display = 'none';
      elements.btnLogout.style.display = 'inline-block';
      elements.adminPassword.style.display = 'none';
    } else {
      statusDot.classList.remove('online');
      statusDot.classList.add('offline');
      elements.authText.textContent = 'Not logged in';
      elements.btnLogin.style.display = 'inline-block';
      elements.btnLogout.style.display = 'none';
      elements.adminPassword.style.display = 'inline-block';
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
        }
      })
      .catch(() => {
        // Not logged in, that's fine
      });
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

  // Simulation
  function runSimulation(execute) {
    const year = document.getElementById('sim-year').value;
    const week = document.getElementById('sim-week').value;
    const level = document.getElementById('sim-level').value;

    let url = `${API_BASE}/games/simulate-week?league_year_id=${year}&season_week=${week}`;
    if (level) url += `&level=${level}`;

    const resultBox = document.getElementById('sim-result');
    resultBox.textContent = 'Loading...';

    const options = execute ? {
      method: 'POST',
      credentials: 'include',
    } : { credentials: 'include' };

    fetch(url, options)
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      });
  }

  // Timestamp
  function loadTimestamp() {
    const container = document.getElementById('timestamp-data');
    container.innerHTML = '<div class="kv-row"><div class="kv-key">Loading...</div><div class="kv-val"></div></div>';

    fetch(`${API_BASE}/games/timestamp`)
      .then(r => r.json())
      .then(data => {
        container.innerHTML = Object.entries(data).map(([key, val]) => `
          <div class="kv-row">
            <div class="kv-key">${key}</div>
            <div class="kv-val">${JSON.stringify(val)}</div>
          </div>
        `).join('');
      })
      .catch(err => {
        container.innerHTML = `<div class="kv-row"><div class="kv-key">Error</div><div class="kv-val">${err.message}</div></div>`;
      });
  }

  function advanceWeek() {
    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = 'Advancing week...';

    fetch(`${API_BASE}/games/timestamp/advance`, {
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

  function resetWeekGames() {
    const resultBox = document.getElementById('timestamp-result');
    resultBox.textContent = 'Resetting week games...';

    fetch(`${API_BASE}/games/timestamp/reset-week`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        resultBox.textContent = JSON.stringify(data, null, 2);
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
  function clearCaches() {
    const resultBox = document.getElementById('cache-result');
    resultBox.textContent = 'Clearing caches...';

    fetch(`${ADMIN_BASE}/clear-caches`, {
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
        resultBox.textContent = JSON.stringify(data, null, 2);
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
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

  // Overall Weights
  let overallWeightsData = null; // cached after load

  function loadOverallWeights() {
    const container = document.getElementById('rc-weights-container');
    const resultBox = document.getElementById('rc-weights-result');
    resultBox.style.display = 'none';
    container.innerHTML = '<div class="text-center text-muted">Loading weights...</div>';

    fetch(`${ADMIN_BASE}/rating-config/overall-weights`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.weights) {
          container.innerHTML = '<div class="text-center text-muted">No weights found. Run the migration first.</div>';
          return;
        }

        overallWeightsData = data.weights;
        renderOverallWeights();
        document.getElementById('btn-save-weights').style.display = 'inline-block';
      })
      .catch(err => {
        container.innerHTML = `<div class="text-center text-danger">Error: ${err.message}</div>`;
      });
  }

  function renderOverallWeights() {
    if (!overallWeightsData) return;

    const container = document.getElementById('rc-weights-container');
    const sortedTypes = Object.keys(overallWeightsData).sort();

    container.innerHTML = sortedTypes.map(ratingType => {
      const attrs = overallWeightsData[ratingType];
      const sortedAttrs = Object.keys(attrs).sort();
      const total = sortedAttrs.reduce((sum, k) => sum + attrs[k], 0);
      const totalClass = Math.abs(total - 1.0) < 0.005 ? 'text-success' : 'text-danger';
      const RATING_TYPE_LABELS = {
        pitcher_overall: 'Pitcher Overall',
        position_overall: 'Position Player Overall',
        sp_rating: 'Starting Pitcher',
        rp_rating: 'Relief Pitcher',
        c_rating: 'Catcher',
        fb_rating: 'First Base',
        sb_rating: 'Second Base',
        tb_rating: 'Third Base',
        ss_rating: 'Shortstop',
        lf_rating: 'Left Field',
        cf_rating: 'Center Field',
        rf_rating: 'Right Field',
        dh_rating: 'Designated Hitter',
      };
      const label = RATING_TYPE_LABELS[ratingType] || ratingType;

      return `
        <div class="card" style="margin: 0">
          <h4>${label}</h4>
          <p class="text-muted" style="margin-bottom: 12px">
            Sum: <strong class="${totalClass}">${total.toFixed(3)}</strong>
            ${Math.abs(total - 1.0) >= 0.005 ? ' (should be 1.000)' : ''}
          </p>
          <table class="data-table">
            <thead>
              <tr>
                <th>Attribute</th>
                <th style="width: 100px">Weight</th>
              </tr>
            </thead>
            <tbody>
              ${sortedAttrs.map(attrKey => `
                <tr>
                  <td><code>${attrKey}</code></td>
                  <td>
                    <input type="number" step="0.01" min="0" max="1"
                      class="weight-input"
                      data-rating-type="${ratingType}"
                      data-attr-key="${attrKey}"
                      value="${attrs[attrKey]}"
                      style="width: 80px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text-primary); font-size: 0.85rem"
                    />
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }).join('');

    // Live sum recalculation on input change
    container.querySelectorAll('.weight-input').forEach(input => {
      input.addEventListener('input', recalcWeightSums);
    });
  }

  function recalcWeightSums() {
    const container = document.getElementById('rc-weights-container');
    const inputs = container.querySelectorAll('.weight-input');

    // Group by rating type
    const sums = {};
    inputs.forEach(input => {
      const rt = input.dataset.ratingType;
      sums[rt] = (sums[rt] || 0) + (parseFloat(input.value) || 0);
    });

    // Update the sum displays in each card
    const cards = container.querySelectorAll('.card');
    cards.forEach(card => {
      const firstInput = card.querySelector('.weight-input');
      if (!firstInput) return;
      const rt = firstInput.dataset.ratingType;
      const total = sums[rt] || 0;
      const strong = card.querySelector('p strong');
      if (strong) {
        strong.textContent = total.toFixed(3);
        strong.className = Math.abs(total - 1.0) < 0.005 ? 'text-success' : 'text-danger';
        const note = Math.abs(total - 1.0) >= 0.005 ? ' (should be 1.000)' : '';
        strong.parentElement.innerHTML = `Sum: <strong class="${strong.className}">${total.toFixed(3)}</strong>${note}`;
      }
    });
  }

  function saveOverallWeights() {
    const container = document.getElementById('rc-weights-container');
    const inputs = container.querySelectorAll('.weight-input');
    const resultBox = document.getElementById('rc-weights-result');

    // Collect weights from inputs
    const weights = {};
    inputs.forEach(input => {
      const rt = input.dataset.ratingType;
      const ak = input.dataset.attrKey;
      const w = parseFloat(input.value) || 0;
      if (!weights[rt]) weights[rt] = {};
      weights[rt][ak] = w;
    });

    // Validate sums
    for (const [rt, attrs] of Object.entries(weights)) {
      const total = Object.values(attrs).reduce((s, v) => s + v, 0);
      if (Math.abs(total - 1.0) >= 0.05) {
        if (!confirm(`${rt} weights sum to ${total.toFixed(3)} (not 1.0). Save anyway?`)) {
          return;
        }
      }
    }

    const btn = document.getElementById('btn-save-weights');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    resultBox.style.display = 'block';
    resultBox.textContent = 'Saving weights...';

    fetch(`${ADMIN_BASE}/rating-config/overall-weights`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ weights }),
    })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (data.ok) {
          resultBox.textContent = `Saved! ${data.updated} weight(s) updated. Re-seed the config to recalculate overall distributions.`;
        } else {
          resultBox.textContent = 'Error: ' + (data.message || JSON.stringify(data));
        }
      })
      .catch(err => {
        resultBox.textContent = 'Error: ' + err.message;
      })
      .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Save Weights';
      });
  }

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
            .map(l => `<span><strong>${l.level_name}:</strong> ${l.count}/${l.max_roster}${l.over_limit ? ' <span style="color:var(--danger)">OVER</span>' : ''}</span>`)
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
    if (action === 'extend') renderExtSalaryInputs();
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

  function loadTransactionLog() {
    fetchTxContext();
    const tbody = document.getElementById('tx-log-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';

    const typeFilter = document.getElementById('tx-log-type-filter').value;
    const orgFilter = document.getElementById('tx-log-org-filter').value;
    const limit = document.getElementById('tx-log-limit').value || 50;

    let url = `${API_BASE}/transactions/log?limit=${limit}`;
    if (typeFilter) url += `&type=${typeFilter}`;
    if (orgFilter) url += `&org_id=${orgFilter}`;

    fetch(url)
      .then(r => r.json())
      .then(entries => {
        if (!entries.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No transactions found</td></tr>';
          return;
        }
        tbody.innerHTML = entries.map(e => {
          const ts = e.created_at ? new Date(e.created_at).toLocaleString() : '--';
          const typeBadge = {
            promote: 'badge-info', demote: 'badge-info',
            ir_place: 'badge-warning', ir_activate: 'badge-warning',
            release: 'badge-danger', buyout: 'badge-danger',
            signing: 'badge-success', extension: 'badge-success',
            trade: 'badge-primary',
          }[e.transaction_type] || '';

          const notes = e.notes || '';
          const isRollback = notes.includes('ROLLBACK');

          return `<tr${isRollback ? ' style="opacity: 0.6"' : ''}>
            <td>${e.id}</td>
            <td>${ts}</td>
            <td><span class="badge ${typeBadge}">${e.transaction_type}</span></td>
            <td>${e.primary_org_id || '--'}</td>
            <td>${e.player_id || '--'}</td>
            <td title="${notes}">${notes.length > 40 ? notes.substring(0, 40) + '...' : notes || '--'}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="App.viewTxDetail(${e.id})">Detail</button>
              ${!isRollback ? `<button class="btn btn-sm btn-danger" onclick="App.rollbackTx(${e.id})">Rollback</button>` : ''}
            </td>
          </tr>`;
        }).join('');
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function viewTxDetail(txId) {
    const detailBox = document.getElementById('tx-log-detail');
    detailBox.style.display = 'block';
    detailBox.textContent = 'Loading...';

    // The log entries already contain details — find it from the table or re-fetch
    fetch(`${API_BASE}/transactions/log?limit=1&tx_id=${txId}`)
      .then(r => r.json())
      .then(entries => {
        // If single-fetch doesn't work, show what we have
        if (entries.length > 0) {
          detailBox.textContent = JSON.stringify(entries[0], null, 2);
        } else {
          detailBox.textContent = 'Transaction not found';
        }
      })
      .catch(() => {
        detailBox.textContent = 'Could not load detail';
      });
  }

  function rollbackTx(txId) {
    if (!confirm(`Rollback transaction #${txId}? This will reverse the operation.`)) return;

    const detailBox = document.getElementById('tx-log-detail');
    detailBox.style.display = 'block';
    detailBox.textContent = 'Rolling back...';

    fetch(`${API_BASE}/transactions/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ transaction_id: txId, executed_by: 'admin' }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          detailBox.textContent = `Error: ${data.message || data.error}`;
        } else {
          detailBox.textContent = JSON.stringify(data, null, 2);
          loadTransactionLog();
        }
      })
      .catch(err => {
        detailBox.textContent = 'Error: ' + err.message;
      });
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

  // Export public API
  window.App = {
    goTo,
    refreshDashboard,
    deleteTask,
    selectPlayer,
    selectFA,
    adminApproveProposal,
    adminRejectProposal,
    viewTxDetail,
    rollbackTx,
  };

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
