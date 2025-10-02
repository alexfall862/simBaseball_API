async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "include", ...opts });
  const text = await r.text();
  try {
    return { status: r.status, data: JSON.parse(text) };
  } catch {
    return { status: r.status, data: text };
  }
}

function show(el, v) { el.style.display = v ? "" : "none"; }

async function login() {
  const pw = document.getElementById("pw").value;
  const res = await api("/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: pw })
  });
  document.getElementById("auth-out").textContent = JSON.stringify(res.data, null, 2);
  if (res.status === 200) loadPresets();
}

async function logout() {
  const res = await api("/admin/logout", { method: "POST" });
  document.getElementById("auth-out").textContent = JSON.stringify(res.data, null, 2);
  document.getElementById("preset").innerHTML = "";
  document.getElementById("out").textContent = "";
}

async function loadPresets() {
  const sel = document.getElementById("preset");
  sel.innerHTML = "";
  const res = await api("/admin/presets");
  if (res.status !== 200) return;
  res.data.presets.forEach(p => {
    const o = document.createElement("option");
    o.value = p.key; o.textContent = `${p.label} (${p.mode})`;
    sel.appendChild(o);
  });
}

async function runPreset() {
  const key = document.getElementById("preset").value;
  const res = await api("/admin/run_preset?key=" + encodeURIComponent(key));
  document.getElementById("out").textContent = JSON.stringify(res.data, null, 2);
}

async function runSQL() {
  const payload = {
    sql: document.getElementById("sql").value,
    mode: document.getElementById("mode").value,
    limit: parseInt(document.getElementById("limit").value || "100", 10),
    dry_run: document.getElementById("dry").checked
  };
  const res = await api("/admin/run_sql", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  document.getElementById("out").textContent = JSON.stringify(res.data, null, 2);
}

window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-login").addEventListener("click", login);
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-preset").addEventListener("click", runPreset);
  document.getElementById("btn-run").addEventListener("click", runSQL);
  loadPresets();
});

document.addEventListener('DOMContentLoaded', () => {
  // --- Organizations dropdown wiring ---
  const orgsSelect = document.getElementById('orgs-select');
  const orgsRefresh = document.getElementById('orgs-refresh');
  const orgsResult = document.getElementById('orgs-result');
  async function fetchJSON(url) {
    const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  }
  async function loadOrgs() {
    try {
      orgsSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';
      const abbrevs = await fetchJSON('/api/v1/organizations');
      orgsSelect.innerHTML = '<option value="" disabled selected>Select an organization</option>' +
        abbrevs.map(a => `<option value="${a}">${a}</option>`).join('');
    } catch (err) {
      console.error('Failed to load organizations', err);
      orgsSelect.innerHTML = '<option value="" disabled selected>Error loading orgs</option>';
    }
  }
  function renderKV(tableData) {
    if (!Array.isArray(tableData) || tableData.length === 0) {
      orgsResult.innerHTML = '<p>No results.</p>';
      return;
    }
    const row = tableData[0];
    const rows = Object.keys(row).map(k => `
<div class="kv-row"><div class="kv-key">${k}</div><div class="kv-val">${String(row[k])}</div></div>
`).join('');
    orgsResult.innerHTML = `<div class="kv-table">${rows}</div>`;
  }
  async function loadOrg(org) {
    if (!org) return;
    try {
      const data = await fetchJSON(`/api/v1/${encodeURIComponent(org)}/`);
      renderKV(data);
    } catch (err) {
      console.error('Failed to load org', err);
      orgsResult.innerHTML = '<p>Error fetching organization.</p>';
    }
  }
  if (orgsSelect && orgsRefresh && orgsResult) {
    loadOrgs();
    orgsRefresh.addEventListener('click', loadOrgs);
    orgsSelect.addEventListener('change', () => {
      const val = orgsSelect.value;
      loadOrg(val);
    });
  }
});