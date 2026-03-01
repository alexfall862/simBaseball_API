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
    document.getElementById('btn-load-config').addEventListener('click', loadRatingConfig);
    document.getElementById('rc-attr-filter').addEventListener('input', filterRatingConfigTable);
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

  let ratingConfigData = null; // cached after load

  function loadRatingConfigSummary() {
    // Quick check: load config to populate stat cards
    fetch(`${ADMIN_BASE}/rating-config`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Login required');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.levels) throw new Error('No config data');
        const levels = data.levels;
        const levelCount = Object.keys(levels).length;
        let attrCount = 0;
        for (const attrs of Object.values(levels)) {
          attrCount += Object.keys(attrs).length;
        }
        document.getElementById('rc-status').textContent = levelCount > 0 ? 'Seeded' : 'Empty';
        document.getElementById('rc-status-sub').textContent = levelCount > 0 ? 'Config loaded' : 'Run seed to populate';
        document.getElementById('rc-levels-count').textContent = levelCount;
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
          const levels = data.levels || {};
          const levelDetails = Object.entries(levels)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([lvl, count]) => `  Level ${lvl} (${LEVEL_NAMES[lvl] || '?'}): ${count} attributes`)
            .join('\n');

          resultBox.textContent =
            `Success! ${data.rows_written} rows written across ${Object.keys(levels).length} levels.\n\n` +
            levelDetails;

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
        btn.textContent = 'Seed / Refresh Config';
      });
  }

  function loadRatingConfig() {
    const levelFilter = document.getElementById('rc-level-filter').value;
    const tbody = document.getElementById('rc-config-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';

    let url = `${ADMIN_BASE}/rating-config`;
    if (levelFilter) url += `?level=${levelFilter}`;

    fetch(url, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) throw new Error('Unauthorized - please login first');
        return r.json();
      })
      .then(data => {
        if (!data.ok || !data.levels) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No config data. Run seed first.</td></tr>';
          return;
        }

        ratingConfigData = data.levels;
        renderRatingConfigTable();
      })
      .catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${err.message}</td></tr>`;
      });
  }

  function renderRatingConfigTable() {
    if (!ratingConfigData) return;

    const searchTerm = (document.getElementById('rc-attr-filter').value || '').toLowerCase().trim();
    const tbody = document.getElementById('rc-config-tbody');

    // Collect all rows sorted by level then attribute
    const rows = [];
    const sortedLevels = Object.keys(ratingConfigData).sort((a, b) => Number(a) - Number(b));

    for (const levelId of sortedLevels) {
      const attrs = ratingConfigData[levelId];
      const sortedAttrs = Object.keys(attrs).sort();

      for (const attrKey of sortedAttrs) {
        if (searchTerm && !attrKey.toLowerCase().includes(searchTerm)) continue;

        const { mean, std } = attrs[attrKey];
        const low = std > 0 ? (mean - 3 * std).toFixed(1) : '--';
        const high = std > 0 ? (mean + 3 * std).toFixed(1) : '--';

        rows.push({
          levelId,
          levelName: LEVEL_NAMES[levelId] || `Level ${levelId}`,
          attrKey,
          mean: mean.toFixed(2),
          std: std.toFixed(2),
          low,
          mid: mean.toFixed(1),
          high,
        });
      }
    }

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No matching attributes found</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(r => {
      const attrClass = getAttrCategoryClass(r.attrKey);
      return `
        <tr>
          <td><span class="badge badge-${getLevelBadge(r.levelId)}">${r.levelName}</span></td>
          <td><code class="${attrClass}">${r.attrKey}</code></td>
          <td>${r.mean}</td>
          <td>${r.std}</td>
          <td class="text-muted">${r.low}</td>
          <td><strong>${r.mid}</strong></td>
          <td class="text-muted">${r.high}</td>
        </tr>
      `;
    }).join('');
  }

  function filterRatingConfigTable() {
    if (ratingConfigData) renderRatingConfigTable();
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
