// Single-page app for YRCARKIT Battery Manager.
// Vanilla JS, no build step.

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ---------- tab switching ----------
$$(".tab").forEach(btn => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

function switchTab(name) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-pane").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "dashboard")  loadDashboard();
  if (name === "sessions")   loadSessions();
  if (name === "pool")       loadPool();
  if (name === "build")      loadBuildForm();
  if (name === "history")    loadHistory();
}

// ---------- API helpers ----------
async function apiGet(url)  { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }
async function apiPost(url, body) {
  const r = await fetch(url, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body || {}) });
  return r.json();
}
async function apiDel(url) { const r = await fetch(url, { method: "DELETE" }); return r.json(); }

function fmt(v, dp=2) { return v == null ? "—" : Number(v).toFixed(dp); }

// ---------- DASHBOARD ----------
async function loadDashboard() {
  const el = $("#dashboard-content");
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const d = await apiGet("/api/dashboard");
    const trendCounts = Object.entries(d.by_trend || {}).map(([k,v]) => `<span class="badge ${k}">${k} ${v}</span>`).join(" ");
    const statusCounts = Object.entries(d.by_status || {}).map(([k,v]) => `<span class="status-pill ${k}">${k}: ${v}</span>`).join(" ");

    let latestHtml = "";
    if (d.latest_session) {
      const lab = d.latest_label;
      latestHtml = `
        <div class="card" style="grid-column: span 2;">
          <div class="label">Latest session</div>
          <div class="value" style="font-size: 18px;">${d.latest_session.session_key}</div>
          <div class="sub">Started ${d.latest_session.started} · Channels ${(d.latest_session.channels || []).join(", ")}</div>
          <div style="margin-top: 8px;">
            ${ lab
                ? `Labelled <strong>Battery ${lab.battery}</strong>, cells ${lab.cell_start}–${lab.cell_end}`
                : `<span style="color: var(--danger); font-weight: 600;">⚠ Not labelled yet — go to Sessions tab</span>` }
          </div>
        </div>`;
    }

    el.innerHTML = `
      ${latestHtml}
      <div class="card"><div class="label">Total modules tested</div><div class="value">${d.total_modules}</div></div>
      <div class="card"><div class="label">Sessions</div><div class="value">${d.session_count}</div></div>
      <div class="card"><div class="label">Packs built</div><div class="value">${d.pack_count}</div></div>
      <div class="card" style="grid-column: span 2;">
        <div class="label">Status breakdown</div>
        <div style="margin-top: 6px;">${statusCounts || '—'}</div>
      </div>
      <div class="card" style="grid-column: span 2;">
        <div class="label">Trend breakdown</div>
        <div style="margin-top: 6px;">${trendCounts || '—'}</div>
      </div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="error-msg">Failed to load dashboard: ${e}</div>`;
  }
}

// ---------- SESSIONS ----------
async function loadSessions() {
  const el = $("#sessions-list");
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const sessions = await apiGet("/api/sessions");
    if (!sessions.length) { el.innerHTML = "<p>No sessions yet.</p>"; return; }
    sessions.reverse(); // newest first
    el.innerHTML = sessions.map(s => {
      const cls = s.label ? "labelled" : "unlabelled";
      const labelText = s.label
        ? `Battery <strong>${s.label.battery}</strong>, cells ${s.label.cell_start}–${s.label.cell_end}`
        : `<em style="color: var(--danger);">unlabelled</em>`;
      return `
        <div class="session-row ${cls}">
          <div class="info">
            <div><strong>${s.session_key}</strong> · ${s.started}</div>
            <div class="meta">channels ${s.channels.join(", ")} · ${labelText}</div>
          </div>
          <button class="btn-primary" onclick="openLabelModal('${s.session_key}')">${s.label ? "Re-label" : "Label"}</button>
        </div>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

async function openLabelModal(sessionKey) {
  $("#label-modal-title").textContent = `Label session ${sessionKey}`;
  $("#label-channels-preview").innerHTML = '<p class="loading">Reading channel data…</p>';
  $("#label-modal").classList.remove("hidden");

  try {
    const det = await apiGet(`/api/sessions/${sessionKey}`);
    const f = $("#label-form");
    f.battery.value     = det.label?.battery || "";
    f.cell_start.value  = det.label?.cell_start || "";
    f.cell_end.value    = det.label?.cell_end || "";
    f.skip_channels.value = det.label
      ? (JSON.parse(det.label.skip_channels || "[3]")).join(",")
      : "3";
    f.notes.value = det.label?.notes || "";

    const skipSet = new Set((f.skip_channels.value || "").split(/[,\s]+/).map(s => parseInt(s)).filter(Boolean));
    const rows = det.channels.map(ch => {
      const skipped = skipSet.has(ch.channel);
      const trend = `<span class="badge ${ch.trend}">${ch.trend}</span>`;
      return `<div class="ch-row">
        <span class="ch-name">CH${ch.channel}</span>
        ${ skipped ? '<span style="color: var(--muted)">(skipped)</span>' :
          `<span>cap ${fmt(ch.cap_ah)} Ah · IR ${fmt(ch.ir_mohm,1)} mΩ · Vend ${fmt(ch.v_end,3)} V · ${ch.n_cycles}D</span>${trend}` }
      </div>`;
    }).join("");
    $("#label-channels-preview").innerHTML = rows;

    f.onsubmit = async (e) => {
      e.preventDefault();
      const skip = (f.skip_channels.value || "").split(/[,\s]+/).map(s=>parseInt(s)).filter(n=>!isNaN(n));
      const body = {
        battery: f.battery.value,
        cell_start: parseInt(f.cell_start.value),
        cell_end:   parseInt(f.cell_end.value),
        skip_channels: skip.length ? skip : [3],
        notes: f.notes.value,
      };
      const r = await apiPost(`/api/sessions/${sessionKey}/label`, body);
      if (r.error) { alert(r.error); return; }
      closeModal("label-modal");
      loadSessions();
    };
  } catch (e) {
    $("#label-channels-preview").innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

function closeModal(id) { $("#" + id).classList.add("hidden"); }

// ---------- POOL ----------
let _pool = [];
async function loadPool() {
  const wrap = $("#pool-table-wrap");
  wrap.innerHTML = '<p class="loading">Loading…</p>';
  try {
    _pool = await apiGet("/api/pool");
    const batteries = [...new Set(_pool.map(m => m.battery).filter(Boolean))].sort();
    const sel = $("#filter-battery");
    sel.innerHTML = '<option value="">any</option>' + batteries.map(b => `<option value="${b}">${b}</option>`).join("");
    renderPool();
  } catch (e) {
    wrap.innerHTML = `<div class="error-msg">${e}</div>`;
  }
}
$("#filter-battery").addEventListener("change", renderPool);
$("#filter-status").addEventListener("change", renderPool);
$("#filter-trend").addEventListener("change", renderPool);

function renderPool() {
  const fb = $("#filter-battery").value;
  const fs = $("#filter-status").value;
  const ft = $("#filter-trend").value;
  let rows = _pool.slice();
  if (fb) rows = rows.filter(m => m.battery === fb);
  if (fs) rows = rows.filter(m => m.status === fs);
  if (ft) rows = rows.filter(m => m.trend === ft);
  rows.sort((a,b) => (b.cap_ah || 0) - (a.cap_ah || 0));

  $("#pool-count").textContent = `${rows.length} of ${_pool.length} modules`;

  const html = `
    <table>
      <thead><tr>
        <th>Battery / Cell</th>
        <th>Session · CH</th>
        <th>Cap (Ah)</th>
        <th>IR (mΩ)</th>
        <th>Vend (V)</th>
        <th>Trend</th>
        <th>Cycles</th>
        <th>Status</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>
        ${rows.map(m => `
          <tr>
            <td>${ m.battery ? `<strong>${m.battery}</strong>-${m.cell_position ?? '?'}` : '<em style="color: var(--danger)">unlabelled</em>' }</td>
            <td><span style="font-family: monospace; font-size: 11px;">${m.session_key}</span> · CH${m.channel}</td>
            <td>${fmt(m.cap_ah)}</td>
            <td>${fmt(m.ir_mohm, 1)}</td>
            <td>${fmt(m.v_end, 3)}</td>
            <td><span class="badge ${m.trend}">${m.trend}</span></td>
            <td><span class="cap-series" title="discharge caps each cycle">${(m.discharge_caps || []).map(c=>c.toFixed(2)).join('→')}</span></td>
            <td>
              <select class="status-edit" data-sk="${m.session_key}" data-ch="${m.channel}">
                ${["available","used","weak","dead","retired"].map(s => `<option value="${s}" ${s===m.status?'selected':''}>${s}</option>`).join("")}
              </select>
            </td>
            <td><input type="text" class="notes-edit" data-sk="${m.session_key}" data-ch="${m.channel}" value="${escapeHtml(m.notes||'')}" style="width: 140px; padding: 3px 6px; font-size: 12px;"></td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
  $("#pool-table-wrap").innerHTML = html;

  $$(".status-edit").forEach(sel => sel.addEventListener("change", async e => {
    await apiPost("/api/modules/override", {
      session_key: sel.dataset.sk, channel: sel.dataset.ch, status: sel.value,
    });
    loadPool();
  }));
  $$(".notes-edit").forEach(inp => inp.addEventListener("blur", async e => {
    await apiPost("/api/modules/override", {
      session_key: inp.dataset.sk, channel: inp.dataset.ch, notes: inp.value,
    });
  }));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// ---------- BUILD ----------
let _previewedPack = null;

async function loadBuildForm() {
  // populate battery dropdown
  try {
    const pool = await apiGet("/api/pool");
    const batteries = [...new Set(pool.map(m => m.battery).filter(Boolean))].sort();
    const sel = $('#build-form select[name="target_battery"]');
    sel.innerHTML = '<option value="ANY">any (use whole pool)</option>' + batteries.map(b => `<option value="${b}">${b}</option>`).join("");
  } catch (e) { /* ignore */ }

  // bind submit
  $("#build-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const body = {
      target_battery:    f.target_battery.value,
      allow_borrow:      f.allow_borrow.checked,
      strategy:          f.strategy.value,
      thermal_placement: f.thermal_placement.checked,
      target_blocks:     parseInt(f.target_blocks.value),
      cap_floor_reuse:   parseFloat(f.cap_floor_reuse.value),
      ir_ceiling_module: parseFloat(f.ir_ceiling_module.value),
      max_pack_cap_spread: parseFloat(f.max_pack_cap_spread.value),
      max_pack_ir_spread:  parseFloat(f.max_pack_ir_spread.value),
      destination:       f.destination.value,
    };
    $("#build-result").innerHTML = '<p class="loading">Building pack…</p>';
    const pack = await apiPost("/api/packs/preview", body);
    renderPackResult(pack);
  };

  $("#save-pack-btn").onclick = async () => {
    if (!_previewedPack || _previewedPack.error) return;
    const r = await apiPost("/api/packs/save", _previewedPack);
    if (r.ok) {
      alert(`Saved pack ${r.pack_id}. Modules locked.`);
      _previewedPack = null;
      $("#save-pack-btn").disabled = true;
      switchTab("history");
    } else {
      alert("Save failed: " + JSON.stringify(r));
    }
  };
}

function renderPackResult(pack) {
  if (pack.error) {
    $("#build-result").innerHTML = `<div class="error-msg">⚠ ${pack.error}</div>`;
    if (pack.candidate_summary) {
      $("#build-result").innerHTML += summarizeCandidates(pack.candidate_summary);
    }
    _previewedPack = null;
    $("#save-pack-btn").disabled = true;
    return;
  }

  _previewedPack = pack;
  $("#save-pack-btn").disabled = false;

  const blocks = pack.block_layout.map(b => `
    <tr>
      <td><strong>${b.block_number}</strong></td>
      <td>${moduleCell(b.a)}</td>
      <td>${moduleCell(b.b)}</td>
      <td>${fmt(b.block_cap)}</td>
      <td>${fmt(b.block_ir, 1)}</td>
      <td style="color: ${b.cap_gap > 0.5 ? 'var(--danger)' : 'var(--muted)'}">${fmt(b.cap_gap)}</td>
    </tr>
  `).join("");

  const reasons = (pack.reasons || []).map(r => `<div>• ${r}</div>`).join("");

  $("#build-result").innerHTML = `
    <div class="pack-summary">
      <div>
        <span class="pack-grade ${pack.grade}">${pack.grade}</span>
        <span class="predicted-life">Predicted life in service: <strong>${pack.predicted_life}</strong></span>
        <span style="color: var(--muted); margin-left: 12px;">(${pack.grade_name})</span>
      </div>
      <div class="pack-stats">
        <div class="stat"><span class="label">Avg cap</span><span class="value">${fmt(pack.avg_cap)} Ah</span></div>
        <div class="stat"><span class="label">Cap spread</span><span class="value">${fmt(pack.cap_spread)} Ah</span></div>
        <div class="stat"><span class="label">Weakest cap</span><span class="value">${fmt(pack.weakest_cap)} Ah</span></div>
        <div class="stat"><span class="label">Avg IR</span><span class="value">${fmt(pack.avg_ir, 1)} mΩ</span></div>
        <div class="stat"><span class="label">IR spread</span><span class="value">${fmt(pack.ir_spread, 1)} mΩ</span></div>
        <div class="stat"><span class="label">Strategy</span><span class="value">${pack.strategy}</span></div>
      </div>
      ${ reasons ? `<div class="pack-reasons">${reasons}</div>` : '' }
    </div>
    ${ pack.candidate_summary ? summarizeCandidates(pack.candidate_summary) : '' }
    <table>
      <thead><tr>
        <th>Block</th>
        <th>Module A (high)</th>
        <th>Module B (low)</th>
        <th>Block cap (Ah)</th>
        <th>Block IR (mΩ)</th>
        <th>Cap gap</th>
      </tr></thead>
      <tbody>${blocks}</tbody>
    </table>
  `;
}

function moduleCell(m) {
  if (!m) return "<em>—</em>";
  const tag = m.battery ? `${m.battery}-${m.cell_position}` : `(${m.session_key} CH${m.channel})`;
  return `<strong>${tag}</strong> <span style="color:var(--muted)">${fmt(m.cap_ah)}Ah ${fmt(m.ir_mohm,1)}mΩ</span> <span class="badge ${m.trend}" style="font-size:10px">${m.trend}</span>`;
}

function summarizeCandidates(s) {
  const byBat = Object.entries(s.by_battery || {}).map(([k,v]) => `${k}: ${v}`).join(" · ");
  return `<p style="color: var(--muted); font-size: 13px;">Candidate pool: ${s.eligible} eligible of ${s.total_modules} total (${byBat || 'none labelled yet'})</p>`;
}

// ---------- HISTORY ----------
async function loadHistory() {
  const el = $("#history-list");
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const packs = await apiGet("/api/packs");
    if (!packs.length) {
      el.innerHTML = "<p>No packs built yet. Go to Build Pack tab to create one.</p>";
      return;
    }
    el.innerHTML = packs.map(p => `
      <div class="pack-summary">
        <div>
          <span class="pack-grade ${p.grade}">${p.grade}</span>
          <strong>${p.pack_id}</strong>
          <span style="color: var(--muted); margin-left: 12px;">${p.built_at}</span>
          <span style="float: right;">
            <button class="btn-danger" onclick="deletePack('${p.pack_id}')">Delete & release modules</button>
          </span>
        </div>
        <div class="pack-stats" style="margin-top: 6px;">
          <div class="stat"><span class="label">Predicted life</span><span class="value">${p.predicted_life}</span></div>
          <div class="stat"><span class="label">Blocks</span><span class="value">${p.block_count}</span></div>
          <div class="stat"><span class="label">Avg cap</span><span class="value">${fmt(p.avg_cap)} Ah</span></div>
          <div class="stat"><span class="label">Cap spread</span><span class="value">${fmt(p.cap_spread)} Ah</span></div>
          <div class="stat"><span class="label">Weakest</span><span class="value">${fmt(p.weakest_cap)} Ah</span></div>
          <div class="stat"><span class="label">Strategy</span><span class="value">${p.strategy}</span></div>
        </div>
        ${ p.destination ? `<div style="margin-top: 6px; font-size: 13px;">Destination: <strong>${escapeHtml(p.destination)}</strong></div>` : '' }
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

async function deletePack(id) {
  if (!confirm(`Delete ${id} and release its modules back to the pool?`)) return;
  await apiDel(`/api/packs/${id}`);
  loadHistory();
}

// ---------- refresh ----------
function refreshAll() {
  const active = $(".tab.active").dataset.tab;
  switchTab(active);
}

// ---------- init ----------
loadDashboard();
