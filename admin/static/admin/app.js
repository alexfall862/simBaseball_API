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

    // Rating Config
    document.getElementById('btn-seed-config').addEventListener('click', seedRatingConfig);
    document.getElementById('btn-load-config').addEventListener('click', loadLevelConfig);
    document.getElementById('btn-save-config').addEventListener('click', saveLevelConfig);
    document.getElementById('btn-load-analysis').addEventListener('click', loadAnalysis);
    document.getElementById('rc-attr-filter').addEventListener('input', filterAnalysisTable);

    // Overall Weights
    document.getElementById('btn-load-weights').addEventListener('click', loadOverallWeights);
    document.getElementById('btn-save-weights').addEventListener('click', saveOverallWeights);
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
      const label = ratingType === 'pitcher_overall' ? 'Pitcher Overall' : 'Position Player Overall';

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

  // Export public API
  window.App = {
    goTo,
    refreshDashboard,
    deleteTask,
  };

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
