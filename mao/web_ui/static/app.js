const $ = (id) => document.getElementById(id);

function token() {
  const q = new URLSearchParams(location.search).get("token");
  if (q) {
    try { localStorage.setItem("orcaToken", q); } catch (_) {}
    return q;
  }
  try { return localStorage.getItem("orcaToken") || ""; } catch (_) { return ""; }
}

function authHeaders() {
  const t = token();
  const h = { "Content-Type": "application/json" };
  if (t) h.Authorization = "Bearer " + t;
  return h;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { ...authHeaders(), ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = { error: text }; }
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

function renderTeam(status) {
  const root = $("team");
  root.innerHTML = "";
  const agents = status.agents || {};
  const turnSel = $("turnAgent");
  const grantSel = $("grantAgent");
  turnSel.innerHTML = "";
  grantSel.innerHTML = "";

  Object.entries(agents).forEach(([name, info]) => {
    const granted = new Set(info.granted || []);
    const eff = info.effective || [];
    const row = document.createElement("div");
    row.className = "agent-row";
    row.innerHTML = `
      <div>
        <div class="agent-name">${name}</div>
        <div class="agent-title">${info.title || ""}</div>
      </div>
      <div class="tags">
        ${
          eff
            .map((p) => {
              const g = granted.has(p);
              return `<span class="tag ${g ? "granted" : "on"}">${p}${g ? " *" : ""}</span>`;
            })
            .join("") || '<span class="tag">none</span>'
        }
      </div>`;
    root.appendChild(row);

    for (const sel of [turnSel, grantSel]) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
  });

  $("activeTurn").textContent = status.active_turn || "— None —";
}

function renderCost(usage) {
  $("costTokens").textContent = Number(usage.total_tokens ?? 0).toLocaleString();
  $("costUsd").textContent = "$" + Number(usage.total_cost_usd ?? 0).toFixed(6);
  const root = $("costByAgent");
  root.innerHTML = "";
  Object.entries(usage.by_agent || {}).forEach(([name, s]) => {
    const chip = document.createElement("span");
    chip.className = "tag on";
    chip.textContent = `${name}: ${s.input + s.output} tok / $${Number(s.cost).toFixed(4)}`;
    root.appendChild(chip);
  });
}

function renderBus(messages) {
  const root = $("bus");
  root.innerHTML = "";
  (messages || [])
    .slice(-100)
    .reverse()
    .forEach((m) => {
      const line = document.createElement("div");
      line.className = "bus-line";
      const content =
        typeof m.content === "object"
          ? JSON.stringify(m.content).slice(0, 160)
          : String(m.content ?? "").slice(0, 160);
      const ts = (m.timestamp || "").slice(11, 19);
      line.innerHTML = `<span class="ts">[${ts}]</span> <span class="topic">${m.topic}</span> · <span class="sender">${m.sender}</span> · ${escapeHtml(content)}`;
      root.appendChild(line);
    });
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&")
    .replaceAll("<", "<")
    .replaceAll(">", ">");
}

function renderGate(gate) {
  const pending = gate && gate.pending;
  $("gateBadge").textContent = pending ? "active" : "idle";
  $("gateBadge").className = "badge" + (pending ? " active" : "");
  if (!pending) {
    $("gateEmpty").classList.remove("hidden");
    $("gatePanel").classList.add("hidden");
    return;
  }
  $("gateEmpty").classList.add("hidden");
  $("gatePanel").classList.remove("hidden");
  $("gateContext").textContent = gate.context || "";
  $("gatePayload").textContent = JSON.stringify(gate.payload, null, 2);
}

async function refresh() {
  try {
    const data = await api("/api/state");
    $("conn").textContent = "online";
    $("conn").className = "pill pill-online";
    $("modelPill").textContent = data.model || "model";
    renderTeam(data.privileges || {});
    renderCost(data.usage || {});
    renderBus(data.bus || []);
    renderGate(data.gate);
  } catch (e) {
    $("conn").textContent = String(e).includes("unauthorized") ? "auth required" : "offline";
    $("conn").className = "pill pill-warn";
  }
}

$("btnRefresh").onclick = refresh;

$("btnSaveToken").onclick = () => {
  const t = $("dashToken").value.trim();
  try { localStorage.setItem("orcaToken", t); } catch (_) {}
  refresh();
};

$("btnStartTurn").onclick = async () => {
  await api("/api/turn/start", {
    method: "POST",
    body: JSON.stringify({ agent: $("turnAgent").value }),
  });
  refresh();
};

$("btnEndTurn").onclick = async () => {
  await api("/api/turn/end", { method: "POST", body: "{}" });
  refresh();
};

$("btnGrant").onclick = async () => {
  const privs = [...document.querySelectorAll(".grantPriv:checked")].map((x) => x.value);
  await api("/api/grant", {
    method: "POST",
    body: JSON.stringify({
      agent: $("grantAgent").value,
      privs,
      note: $("grantNote").value,
      human_approved: $("grantFry").checked,
    }),
  });
  refresh();
};

$("btnRevoke").onclick = async () => {
  await api("/api/revoke", {
    method: "POST",
    body: JSON.stringify({ agent: $("grantAgent").value }),
  });
  refresh();
};

async function decide(decision) {
  await api("/api/gate/decide", {
    method: "POST",
    body: JSON.stringify({
      decision,
      note: $("gateNote").value,
      edited: $("gateEdit").value,
    }),
  });
  refresh();
}

$("btnApprove").onclick = () => decide("approve");
$("btnReject").onclick = () => decide("reject");
$("btnEdit").onclick = () => decide("edit");

$("btnRun").onclick = async () => {
  $("runOut").textContent = "Running… (if human gate is on, use the panel above)";
  try {
    const data = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({
        input: $("runInput").value,
        require_human: $("runHuman").checked,
      }),
    });
    $("runOut").textContent = JSON.stringify(data, null, 2);
    refresh();
  } catch (e) {
    $("runOut").textContent = String(e);
  }
};

refresh();
setInterval(refresh, 2000);
