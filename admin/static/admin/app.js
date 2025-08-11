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
