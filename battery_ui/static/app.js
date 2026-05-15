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
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// ---------- TREND BADGE WITH HOVER TOOLTIP ----------
// Hover any trend badge to see what it actually means in plain English.

const TREND_TIPS = {
  IMPROVING: "Cap rose by 5%+ across cycles — reconditioning worked. Module had memory effect, the cycles broke it down. Keep it, the number is real.",
  STABLE:    "Flat across cycles (within +/-5%) — module is already at its ceiling. This is the true cap, no benefit from more cycles.",
  PLATEAU:   "Peaked early (cycle 2-3), then mild fade. Done conditioning. Use the number — but don't run MORE cycles, you'll just lose cap.",
  DECLINING: "Peaked then fell by more than 8%. Over-cycled or end-of-life. Either accept the lower number, or retest with fewer cycles to recover.",
  DEAD:      "Peak cap below 0.3 Ah. Failed module — internal short, dried electrolyte, etc. Scrap it.",
  UNKNOWN:   "Not enough cycle data to classify yet (need 2+ completed discharges).",
};

function trendBadge(trend, opts = {}) {
  const tip = TREND_TIPS[trend] || "";
  const sz  = opts.small ? ' style="font-size:10px"' : '';
  return `<span class="badge ${trend}" data-tip="${escapeHtml(tip)}"${sz}>${trend}</span>`;
}

// ---------- BANNERS ----------
function dismissBanner(elId, storeKey) {
  $("#" + elId).classList.add("hidden");
  if (storeKey) localStorage.setItem(storeKey, "1");
}

function showCutoffReminder() {
  if (localStorage.getItem("cutoff-dismissed") === "1") return;
  $("#cutoff-banner").classList.remove("hidden");
}

async function renderPendingBanner() {
  try {
    const r = await apiGet("/api/labelling/pending");
    const el = $("#pending-label-banner");
    if (!r.pending) { el.classList.add("hidden"); return; }
    const p = r.pending;
    el.innerHTML = `
      <span><strong>📌 Pending label queued:</strong> next new session will be auto-labelled as
      <strong>Battery ${p.battery} cells ${p.cell_start}-${p.cell_end}</strong>
      ${p.session_type === 'testing' ? '(testing)' : ''}
      <span style="color: var(--muted); font-size: 11px; margin-left: 8px;">queued ${p.queued_at}</span></span>
      <button class="banner-dismiss" onclick="cancelPendingLabel()" title="cancel queue">×</button>
    `;
    el.classList.remove("hidden");
  } catch (_) {}
}

async function cancelPendingLabel() {
  await apiDel("/api/labelling/pending");
  $("#pending-label-banner").classList.add("hidden");
}

async function queuePendingLabel(battery, cell_start, cell_end, session_type) {
  const r = await apiPost("/api/labelling/pending", {
    battery, cell_start, cell_end, session_type: session_type || "production",
  });
  if (r.ok) renderPendingBanner();
  else alert("Queue failed: " + (r.error || ""));
}

function showUnlabelledBanner(latestSession) {
  const el = $("#unlabelled-banner");
  if (!latestSession || latestSession.label) {
    el.classList.add("hidden");
    return;
  }
  el.innerHTML = `
    <span><strong>⚠ New session needs labelling:</strong> ${latestSession.session_key}
    (started ${latestSession.started}). <a onclick="switchTab('sessions'); openLabelModal('${latestSession.session_key}')">Label it now →</a></span>
    <button class="banner-dismiss" onclick="document.getElementById('unlabelled-banner').classList.add('hidden')">×</button>
  `;
  el.classList.remove("hidden");
}

function showNewSessionToast(sessionKey) {
  const el = $("#new-session-toast");
  el.innerHTML = `<strong>New session detected:</strong> ${sessionKey}.
                  <a onclick="openCategorizeModal('${sessionKey}')">Categorize →</a>`;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 12000);
  // Also open the categorize modal automatically
  openCategorizeModal(sessionKey);
}

// ---------- AUTO-CATEGORIZE NEW SESSION ----------
async function openCategorizeModal(sessionKey) {
  const info = $("#categorize-session-info");
  const opts = $("#categorize-options");
  info.innerHTML = `Loading session info for <strong>${sessionKey}</strong>...`;
  opts.innerHTML = "";
  $("#categorize-modal").classList.remove("hidden");

  try {
    const [det, suggest] = await Promise.all([
      apiGet(`/api/sessions/${sessionKey}`),
      apiGet("/api/labelling/suggest-next"),
    ]);

    const activeChs = (det.channels||[]).filter(c => !c.skipped).map(c => c.channel);
    const nActive = activeChs.length;
    info.innerHTML = `
      <div><strong>${sessionKey}</strong> — started ${det.started || ''}</div>
      <div style="margin-top: 5px;">
        <strong style="color: ${nActive < 7 ? 'var(--warn)' : 'var(--success)'};">${nActive} channel${nActive===1?'':'s'} active in this session: ${activeChs.map(c => "CH"+c).join(", ")}</strong>
        ${nActive < 7 ? '<div style="color: var(--warn); font-size: 11px; margin-top: 2px;">⚠ Partial session detected — fewer than 7 channels. Cell range will match.</div>' : ''}
      </div>
    `;

    const cls = { continue_battery: "continue", new_battery: "new-battery", testing: "testing" };
    const used = Object.keys(suggest.battery_progress || {}).filter(b => b !== "TEST").sort();
    let html = (suggest.suggestions || []).map(s => {
      const mapping = previewChannelMapping(activeChs, s);
      return `
        <button class="categorize-option ${cls[s.kind]}" onclick='applyCategorize(${JSON.stringify(sessionKey)}, ${JSON.stringify(s).replace(/'/g, "&apos;")})'>
          <div class="cat-headline">${escapeHtml(s.label)}</div>
          <div class="cat-explain">${escapeHtml(s.explanation)}</div>
          <div class="cat-mapping">${mapping}</div>
        </button>
      `;
    }).join("");
    // Always include a "specific letter" option for picking any other battery.
    // Cell range pre-fills to match active channel count.
    html += `
      <div class="categorize-option new-battery" style="cursor: default;">
        <div class="cat-headline" style="display:flex; align-items:center; gap:8px; flex-wrap: wrap;">
          <span>Start a specific battery:</span>
          <input type="text" id="custom-battery-letter" maxlength="2" style="width:50px; padding:4px 8px; text-transform:uppercase; font-size:14px; font-weight:600;" placeholder="?">
          <span>cells</span>
          <input type="number" id="custom-cell-start" min="1" max="28" value="1" style="width:55px; padding:4px 8px; font-size:14px;">
          <span>-</span>
          <input type="number" id="custom-cell-end" min="1" max="28" value="${nActive}" style="width:55px; padding:4px 8px; font-size:14px;">
          <button class="btn-primary" style="padding: 4px 12px; font-size: 13px;" onclick="applyCustomLetter('${sessionKey}')">Apply</button>
        </div>
        <div class="cat-explain">Use any letter (D, M, etc.) when starting a different physical pack. Already used: ${used.length ? used.join(", ") : "none"}. Cell range pre-filled to ${nActive} (matches active channels).</div>
      </div>`;
    opts.innerHTML = html;
  } catch (e) {
    info.innerHTML = `<span style="color: var(--danger)">Failed to load: ${e}</span>`;
  }
}

function previewChannelMapping(activeChannels, suggestion) {
  if (suggestion.kind === "testing") return "";
  const cs = suggestion.cell_start, ce = suggestion.cell_end;
  const cells = [];
  for (let c = cs; c <= ce; c++) cells.push(c);
  if (cells.length !== activeChannels.length) {
    return `<span style="color: var(--danger);">⚠ ${cells.length} cells but ${activeChannels.length} channels — won't save until matched</span>`;
  }
  const pairs = activeChannels.map((ch, i) => `<span style="color: var(--primary-dark)">CH${ch}→${suggestion.battery}-${cells[i]}</span>`).join(" · ");
  return `<div style="margin-top: 6px; font-size: 11px; padding: 4px 8px; background: #eff6ff; border-radius: 3px;">Will map: ${pairs}</div>`;
}

async function applyCustomLetter(sessionKey) {
  const letter = ($("#custom-battery-letter").value || "").trim().toUpperCase();
  const cs = parseInt($("#custom-cell-start").value);
  const ce = parseInt($("#custom-cell-end").value);
  if (!letter || !letter.match(/^[A-Z]+$/)) { alert("Enter a letter (A-Z)"); return; }
  if (!cs || !ce || ce < cs || cs < 1 || ce > 28) { alert("Cell range must be 1-28 ascending"); return; }
  await applyCategorize(sessionKey, {
    kind: "new_battery", battery: letter,
    cell_start: cs, cell_end: ce,
    session_type: "production",
  });
}

async function applyCategorize(sessionKey, suggestion) {
  // For testing sessions, label is freeform; for production, use the suggested cells
  const body = {
    battery: suggestion.battery,
    cell_start: suggestion.cell_start,
    cell_end: suggestion.cell_end,
    skip_channels: [3],
    session_type: suggestion.session_type,
    notes: suggestion.kind === "testing" ? "Auto-tagged as testing/set-aside" : "",
  };
  const r = await apiPost(`/api/sessions/${sessionKey}/label`, body);
  if (r.error) {
    // For testing sessions, the channel-count check fails but that's OK — ignore and re-send
    if (suggestion.session_type === "testing") {
      // server already validated session_type=='testing' loosens the check. If still failing, surface error.
      alert("Save failed: " + r.error);
      return;
    }
    alert("Save failed: " + r.error);
    return;
  }
  closeModal("categorize-modal");
  // Refresh whatever tab is open
  const active = $(".tab.active").dataset.tab;
  switchTab(active);
}

// ---------- AUTO-POLL (adaptive: 10s when live, 30s when idle) ----------
let _lastSessionKey = null;
let _pollTimer = null;
let _liveMode  = false;

async function pollForUpdates() {
  try {
    const d = await apiGet("/api/dashboard");
    const ls = d.latest_session;
    if (!ls) return;
    if (_lastSessionKey === null) {
      _lastSessionKey = ls.session_key;
    } else if (ls.session_key !== _lastSessionKey) {
      _lastSessionKey = ls.session_key;
      // Try to auto-apply a queued pending label first
      try {
        const pend = await apiGet("/api/labelling/pending");
        if (pend.pending) {
          const r = await apiPost(`/api/labelling/apply-pending/${ls.session_key}`, {});
          if (r.ok) {
            const t = $("#new-session-toast");
            t.innerHTML = `<strong>Auto-labelled new session</strong> as ${r.applied.battery} cells ${r.applied.cell_start}-${r.applied.cell_end}.`;
            t.classList.remove("hidden");
            setTimeout(() => t.classList.add("hidden"), 8000);
            const active = $(".tab.active").dataset.tab;
            switchTab(active);
            renderPendingBanner();
            return;
          }
          // pending exists but couldn't apply — fall through to manual modal
        }
      } catch(_) {}
      showNewSessionToast(ls.session_key);
      const active = $(".tab.active").dataset.tab;
      switchTab(active);
    }
    if (ls && !d.latest_label) {
      showUnlabelledBanner({...ls, label: null});
    } else {
      $("#unlabelled-banner").classList.add("hidden");
    }
    // refresh live panel any time it's visible
    if ($("#tab-dashboard").classList.contains("active")) {
      await loadLive();
    }
  } catch (e) { /* ignore */ }
}

function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  const interval = _liveMode ? 10000 : 30000;
  _pollTimer = setInterval(pollForUpdates, interval);
}
startPolling();

// ---------- CLOUD STATUS / SYNC NOW ----------
async function loadRecentSessions() {
  const el = document.getElementById("recent-sessions-panel");
  if (!el) return;
  try {
    const sessions = await apiGet("/api/sessions");
    if (!sessions.length) { el.classList.add("hidden"); return; }
    // skip the latest (already shown in live panel) and take the 5 before that
    const recent = sessions.slice(-6, -1).reverse();
    if (!recent.length) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    el.innerHTML = `
      <div class="recent-sessions">
        <h3>Recent sessions (last 5 before current)</h3>
        ${recent.map(s => {
          const lbl = s.label
            ? `<span class="cell-tag">${s.label.battery}-${s.label.cell_start}..${s.label.cell_end}</span>`
            : `<span class="cell-tag unlab">unlabelled</span>`;
          const cap = s.cap_range ? `cap ${fmt(s.cap_range[0])} - ${fmt(s.cap_range[1])} Ah` : '';
          const trends = Object.entries(s.trend_dist || {})
            .map(([k,v]) => `<span class="badge ${k}" data-tip="${escapeHtml(TREND_TIPS[k]||'')}" style="font-size:9px">${k} ${v}</span>`)
            .join(" ");
          return `<div class="recent-row">
            <div style="flex:1;">
              <strong>${s.session_key}</strong> ${lbl}
              <span style="color: var(--muted); font-size: 11px;">started ${s.started}</span>
            </div>
            <div style="font-size: 11px; color: var(--muted);">CH${s.channels.join(",")} · ${cap}</div>
            <div>${trends}</div>
          </div>`;
        }).join("")}
      </div>`;
  } catch (e) { /* ignore */ }
}

async function loadCloudStatus() {
  const el = document.getElementById("cloud-status-content");
  if (!el) return;
  try {
    const s = await apiGet("/api/cloud-status");
    const status = s.last_push_status;
    let dot = "🟢", phrase;
    if (status === "ok")            phrase = "Last push complete";
    else if (status === "no-changes") phrase = "No changes (idle)";
    else if (status === "failed")   { dot = "🔴"; phrase = "Last push FAILED"; }
    else                            { dot = "🟡"; phrase = "Status unknown"; }

    const pending = s.pending_changes;
    const pendingTxt = pending > 0
      ? `<span style="color: var(--warn);">${pending} unsaved file(s) waiting</span>`
      : `<span style="color: var(--success);">all changes saved</span>`;

    el.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px;">
        <div style="flex: 1;">
          <div style="font-size: 14px;">${dot} ${phrase}</div>
          <div style="font-size: 11px; color: var(--muted); margin-top: 3px;">
            ${s.last_push_at || "no record"} · auto every ${s.scheduled_every} · ${pendingTxt}
          </div>
        </div>
        <button class="btn-primary" id="sync-now-btn" onclick="syncCloudNow()" style="padding: 6px 14px; font-size: 12px;">Sync now</button>
      </div>
    `;
  } catch (e) {
    el.innerHTML = `<span style="color: var(--danger);">cloud status unavailable</span>`;
  }
}

async function syncCloudNow() {
  const btn = document.getElementById("sync-now-btn");
  if (btn) { btn.disabled = true; btn.textContent = "syncing…"; }
  try {
    const r = await apiPost("/api/cloud-status/sync-now", {});
    if (r.error) {
      alert("Sync failed: " + r.error);
    } else if (r.ok) {
      // brief popup with the result
      const last = r.log_tail.split("\n").filter(l => l.trim()).slice(-3).join("\n");
      alert("Push complete!\n\n" + last);
    } else {
      alert("Push exited with code " + r.exit_code + "\n\n" + (r.log_tail || ""));
    }
  } catch (e) {
    alert("Sync error: " + e);
  }
  loadCloudStatus();
}

// ---------- LIVE PANEL ----------
async function loadLive() {
  try {
    const live = await apiGet("/api/live");
    const wasLive = _liveMode;
    _liveMode = live.is_live;
    if (wasLive !== _liveMode) startPolling();   // adapt cadence

    const el = $("#live-panel");
    if (!live.session_key) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");

    const cls   = live.is_live ? "" : "idle";
    const liveSess = live.live_sessions || [];
    let dotTxt;
    if (!live.is_live) {
      dotTxt = "Latest session (idle)";
    } else if (liveSess.length > 1) {
      dotTxt = `LIVE — ${liveSess.length} sessions running concurrently`;
    } else {
      dotTxt = "LIVE — session in progress";
    }
    const battTag = live.battery_label
      ? `<span class="cell-tag">Battery ${live.battery_label}</span>`
      : `<span class="cell-tag unlab">unlabelled</span>`;
    const multiSessionsLine = liveSess.length > 1
      ? `<div class="live-meta" style="margin-top: 4px; color: var(--warn);">⚠ Multiple sessions: ${liveSess.map(s => s.session_key + (s.battery_label ? ` (${s.battery_label} ${s.cell_range})` : '')).join(", ")}</div>`
      : '';

    // Use the new live_channels (all sessions) if available, fall back to legacy channels (latest only)
    const allLive = live.live_channels || live.channels || [];
    const channels = allLive.map(c => {
      const stale = c.age_s > 600;     // no update for 10+ min
      const resting = c.is_resting;
      let phaseClass = "charging";
      if (c.current_phase === "DISCHARGE") phaseClass = "discharging";
      if (resting) phaseClass = "resting";
      if (stale)   phaseClass = "stale";
      const phaseLabel = resting
        ? "RESTING"
        : (c.current_phase === "CHARGE" ? "⚡ CHARGING" : "🔻 DISCHARGING");
      const elapsedMin = Math.floor((c.elapsed_in_table_s || 0) / 60);
      const elapsedSec = (c.elapsed_in_table_s || 0) % 60;
      const ageStr = c.age_s < 60 ? `${c.age_s}s ago` : `${Math.floor(c.age_s/60)}m ago`;
      // typical max cap per Prius cycle ~3-5 Ah; show progress vs 4 Ah baseline
      const progressPct = Math.min(100, ((c.current_cap || 0) / 4.0) * 100);
      const cellTag = c.cell_label
        ? `<span class="cell-tag" style="font-size:11px; padding:2px 8px;">${c.cell_label}</span>`
        : `<span class="cell-tag unlab" style="font-size:11px; padding:2px 8px;">unlabelled</span>`;
      // Show session_key as a small footnote when there are multiple live sessions
      const multiSession = (live.live_sessions || []).length > 1;
      const sessionTag = multiSession && c.session_key
        ? `<span style="font-size:9px; color: var(--muted); font-family: monospace; display:block; margin-top:3px;">${c.session_key}</span>`
        : '';
      return `
        <div class="live-ch ${phaseClass}">
          <div class="ch-head">
            <span class="ch-num">CH${c.channel}</span>
            ${cellTag}
            <span class="ch-phase">${phaseLabel}</span>
          </div>
          ${sessionTag}
          <div class="live-grid">
            <span class="lbl">Cycle</span><span class="val">${c.current_cycle}</span>
            <span class="lbl">Voltage</span><span class="val">${fmt(c.current_vol, 3)} V</span>
            <span class="lbl">Current</span><span class="val">${fmt(c.current_cur, 2)} A</span>
            <span class="lbl">Cap so far</span><span class="val">${fmt(c.current_cap, 3)} Ah</span>
            <span class="lbl">Elapsed</span><span class="val">${elapsedMin}m ${elapsedSec}s</span>
            <span class="lbl">Last sample</span><span class="val">${ageStr}</span>
          </div>
          <div class="progress" title="cap accumulated this cycle"><div style="width: ${progressPct}%"></div></div>
        </div>`;
    }).join("");

    el.innerHTML = `
      <div class="live-card ${cls}">
        <div class="live-header">
          <span class="live-dot"></span>
          <div>
            <div class="live-title">${dotTxt}</div>
            <div class="live-meta">Session ${live.session_key} · started ${live.session_started} · ${battTag}</div>
            ${multiSessionsLine}
          </div>
        </div>
        ${live.channels.length === 0
          ? `<p style="color: var(--muted)">No channel data yet.</p>`
          : `<div class="live-channels">${channels}</div>`}
        ${live.is_live
          ? `<p class="live-meta" style="margin-top: 10px;">Refreshing every 10s. Cap-so-far progress bar shown vs 4 Ah baseline.</p>`
          : `<p class="live-meta" style="margin-top: 10px;">No new data in the last 5 min — session likely complete or YRCARKIT idle.</p>`}
      </div>`;
    renderPreviousSession(live.previous);
  } catch (e) { /* ignore */ }
}

function renderPreviousSession(prev) {
  const el = document.getElementById("previous-session-panel");
  if (!el) return;
  if (!prev || !prev.channels || !prev.channels.length) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");

  const battTag = prev.battery_label
    ? `<span class="cell-tag">Battery ${prev.battery_label}</span>`
    : `<span class="cell-tag unlab">unlabelled</span>`;

  const channels = prev.channels.map(c => {
    const cellTag = c.cell_label
      ? `<span class="cell-tag" style="font-size:11px; padding:2px 8px;">${c.cell_label}</span>`
      : `<span class="cell-tag unlab" style="font-size:11px; padding:2px 8px;">unlabelled</span>`;
    const cap = c.cap_ah != null ? fmt(c.cap_ah, 2) : "—";
    const ir = c.ir_mohm != null ? fmt(c.ir_mohm, 1) : "—";
    const ven = c.v_end != null ? fmt(c.v_end, 3) : "—";
    const prog = (c.cap_progression || []).map(p => p.toFixed(2)).join("→");
    return `
      <div class="prev-ch" onclick="openModuleDetail('${prev.session_key}', ${c.channel})" style="cursor:pointer">
        <div class="ch-head">
          <span class="ch-num">CH${c.channel}</span>
          ${cellTag}
          ${gradeBadge(c.quality_grade, '')}
        </div>
        <div class="live-grid">
          <span class="lbl">Settled cap</span><span class="val">${cap} Ah</span>
          <span class="lbl">IR</span><span class="val">${ir} mΩ</span>
          <span class="lbl">Vend</span><span class="val">${ven} V</span>
          <span class="lbl">Trend</span><span class="val">${trendBadge(c.trend, {small: true})}</span>
        </div>
        <div style="font-size: 10px; color: var(--muted); margin-top: 4px; font-family: ui-monospace, monospace;">${prog || '(no cycles)'}</div>
      </div>`;
  }).join("");

  el.innerHTML = `
    <div class="prev-card">
      <div class="prev-header">
        <strong>Previous session — just finished</strong>
        <span class="live-meta">${prev.session_key} · started ${prev.session_started} · ${battTag}</span>
      </div>
      <div class="prev-channels">${channels}</div>
      <p class="live-meta" style="margin-top: 8px; font-size: 11px;">Click any card to drill into the full per-cycle history of that module.</p>
    </div>
  `;
}

// ---------- DASHBOARD ----------
async function loadDashboard() {
  const el = $("#dashboard-content");
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const d = await apiGet("/api/dashboard");
    _lastSessionKey = d.latest_session ? d.latest_session.session_key : null;
    showUnlabelledBanner(d.latest_session ? {...d.latest_session, label: d.latest_label} : null);

    const trendCounts = Object.entries(d.by_trend || {}).map(([k,v]) => `<span class="badge ${k}" data-tip="${escapeHtml(TREND_TIPS[k] || '')}">${k} ${v}</span>`).join(" ");
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

    // also load the live panel and recent sessions
    loadLive();
    loadRecentSessions();

    const byBatList = Object.entries(d.by_battery || {}).sort()
      .map(([b,n]) => `<span class="cell-tag" style="margin-right:6px">${b}: ${n}</span>`).join("");
    el.innerHTML = `
      ${latestHtml}
      <div class="card">
        <div class="label">Labelled modules <span class="tooltip" data-tip="Modules tagged with a battery letter and cell number — these are usable for pack-building. Unlabelled ones (legacy/junk) are hidden from default views.">ⓘ</span></div>
        <div class="value">${d.labelled_modules || 0}</div>
        <div class="sub">${byBatList || 'no batteries labelled yet'}</div>
      </div>
      <div class="card">
        <div class="label">Unlabelled (hidden by default)</div>
        <div class="value" style="color: var(--muted);">${d.unlabelled_modules || 0}</div>
        <div class="sub">legacy data — hidden from Pool & Build by default</div>
      </div>
      <div class="card"><div class="label">Sessions</div><div class="value">${d.session_count}</div></div>
      <div class="card"><div class="label">Packs built</div><div class="value">${d.pack_count}</div></div>
      <div id="cloud-card" class="card" style="grid-column: span 2;">
        <div class="label">Cloud backup (GitHub)</div>
        <div id="cloud-status-content" style="margin-top: 6px;">checking…</div>
      </div>
      <div class="card" style="grid-column: span 2;">
        <div class="label">Status breakdown</div>
        <div style="margin-top: 6px;">${statusCounts || '—'}</div>
      </div>
      <div class="card" style="grid-column: span 2;">
        <div class="label">Trend breakdown <span class="tooltip" data-tip="IMPROVING = reconditioning is working. PLATEAU = peaked. STABLE = at ceiling. DECLINING = over-cycled. DEAD = scrap.">ⓘ</span></div>
        <div style="margin-top: 6px;">${trendCounts || '—'}</div>
      </div>
    `;
    loadCloudStatus();
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
      const trendBadges = Object.entries(s.trend_dist || {})
        .map(([k,v]) => `<span class="badge ${k}" data-tip="${escapeHtml(TREND_TIPS[k] || '')}" style="font-size:10px">${k} ${v}</span>`)
        .join(" ");
      const capRange = s.cap_range
        ? `<span style="color: var(--muted); margin-left: 12px;">cap ${fmt(s.cap_range[0])}–${fmt(s.cap_range[1])} Ah</span>`
        : "";
      return `
        <div class="session-row ${cls}">
          <div class="info">
            <div><strong>${s.session_key}</strong> · ${s.started} ${capRange}</div>
            <div class="meta">channels ${s.channels.join(", ")} · ${labelText}</div>
            <div class="meta" style="margin-top: 4px;">${trendBadges}</div>
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
      const trend = trendBadge(ch.trend);
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
      $("#unlabelled-banner").classList.add("hidden");
    };
  } catch (e) {
    $("#label-channels-preview").innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

function closeModal(id) { $("#" + id).classList.add("hidden"); }

// ---------- MODULE DETAIL MODAL ----------
async function openModuleDetail(sessionKey, channel) {
  $("#module-modal-title").textContent = `Loading…`;
  $("#module-modal-body").innerHTML = '<p class="loading">Reading cycle data…</p>';
  $("#module-modal").classList.remove("hidden");

  try {
    const d = await apiGet(`/api/modules/${sessionKey}/${channel}`);
    const tag = d.battery ? `Battery ${d.battery} · Cell ${d.cell_position}` : `Unlabelled module`;
    $("#module-modal-title").innerHTML = `${tag}  <span style="color: var(--muted); font-size: 14px;">(session ${d.session_key} · CH${d.channel})</span>`;

    // peak / settled metrics
    const dis = d.cycles.filter(c => c.kind === "F");
    const chg = d.cycles.filter(c => c.kind === "C");
    const peakDis = dis.length ? Math.max(...dis.map(c => c.cap_ah)) : null;
    const targetTable = d.target?.table;

    // mini sparkline for discharge caps
    const dcaps = dis.map(c => c.cap_ah);
    const dmax = Math.max(...dcaps, 1);
    const spark = `<span class="cap-spark">${dcaps.map(c => `<div class="bar" title="${c.toFixed(2)} Ah" style="height:${Math.max(2, c/dmax*22).toFixed(0)}px"></div>`).join('')}</span>`;

    // cycle table
    const cycleRows = d.cycles.map(c => {
      const cls = c.kind === "C" ? "charge" : "discharge";
      const tgt = c.table === targetTable ? "target" : "";
      return `<tr class="cycle-row ${cls} ${tgt}">
        <td>${c.table}</td>
        <td>${c.kind === "C" ? "CHARGE" : "discharge"}</td>
        <td>${c.cap_ah.toFixed(3)}</td>
        <td>${c.ir_mohm == null ? "—" : c.ir_mohm.toFixed(1)}</td>
        <td>${c.v_end == null ? "—" : c.v_end.toFixed(3)}</td>
        <td>${(c.dur_s / 60).toFixed(1)} min</td>
        <td>${c.rows}</td>
        ${c.table === targetTable ? '<td><span class="badge IMPROVING" style="font-size:10px">target for export</span></td>' : '<td></td>'}
      </tr>`;
    }).join("");

    // history of same cell across other sessions
    let historyHtml = "";
    if (d.history && d.history.length) {
      historyHtml = `
        <div class="module-section">
          <h4>Same cell tested in ${d.history.length} other session(s)</h4>
          ${d.history.map(h => `
            <div class="history-row">
              <strong>${h.session_key}</strong>
              <span style="color: var(--muted)">${h.started}</span>
              <span>cap <strong>${fmt(h.cap_ah)} Ah</strong></span>
              <span>IR <strong>${fmt(h.ir_mohm,1)} mΩ</strong></span>
              <span>Vend ${fmt(h.v_end,3)} V</span>
              <span>${h.n_discharges}D</span>
              ${trendBadge(h.trend, {small: true})}
              <button class="btn-cancel" style="padding: 3px 8px; font-size: 11px; margin-left: auto;" onclick="openModuleDetail('${h.session_key}', ${h.channel})">view</button>
            </div>
          `).join("")}
        </div>`;
    } else if (d.battery && d.cell_position) {
      historyHtml = `<div class="module-section"><h4>History</h4><p style="color: var(--muted)">No prior tests of this cell in other sessions.</p></div>`;
    } else {
      historyHtml = `<div class="module-section"><h4>History</h4><p style="color: var(--muted)">Module is unlabelled — label this session to track this cell across other tests.</p></div>`;
    }

    // total accumulated cycle time
    const totalSec = d.cycles.reduce((sum, c) => sum + (c.dur_s || 0), 0);
    const totalH = Math.floor(totalSec / 3600);
    const totalM = Math.round((totalSec % 3600) / 60);

    $("#module-modal-body").innerHTML = `
      <div class="module-section">
        <div class="module-meta-grid">
          <div class="meta-item"><div class="lbl">Settled cap (target)</div><div class="val">${fmt(d.target?.cap_ah)} Ah</div></div>
          <div class="meta-item"><div class="lbl">Settled IR</div><div class="val">${fmt(d.target?.ir_mohm, 1)} mΩ</div></div>
          <div class="meta-item"><div class="lbl">End voltage</div><div class="val">${fmt(d.target?.v_end, 3)} V</div></div>
          <div class="meta-item"><div class="lbl">Peak discharge cap</div><div class="val">${fmt(peakDis)} Ah</div></div>
          <div class="meta-item"><div class="lbl">Cycles run</div><div class="val">${chg.length}C / ${dis.length}D</div></div>
          <div class="meta-item"><div class="lbl">Total cycle time</div><div class="val">${totalH}h ${totalM}m</div></div>
        </div>
        <p style="margin-top: 10px; font-size: 13px;">
          ${trendBadge(d.trend)}
          <span style="color: var(--muted); margin-left: 8px;">${d.trend_desc}</span>
        </p>
        <p style="margin-top: 8px; font-size: 13px;">
          Discharge cap progression: ${spark}
          <span style="color: var(--muted); font-family: ui-monospace, monospace; font-size: 11px; margin-left: 8px;">
            ${dcaps.map(c => c.toFixed(2)).join(' → ')}
          </span>
        </p>
      </div>

      <div class="module-section">
        <h4>Every cycle in this session (${d.cycles.length} tables)</h4>
        <table class="cycle-table">
          <thead><tr>
            <th>Table</th><th>Kind</th><th>Cap (Ah)</th><th>IR (mΩ)</th><th>V end (V)</th><th>Duration</th><th>Rows</th><th></th>
          </tr></thead>
          <tbody>${cycleRows}</tbody>
        </table>
      </div>

      ${historyHtml}

      <div class="module-section">
        <h4>Status & notes</h4>
        <div style="display: flex; gap: 10px; align-items: center;">
          <select id="module-status-edit" style="padding: 6px 10px;">
            ${["available","used","weak","dead","retired"].map(s => `<option value="${s}" ${s===d.status?'selected':''}>${s}</option>`).join("")}
          </select>
          <input type="text" id="module-notes-edit" value="${escapeHtml(d.notes||'')}" placeholder="notes" style="flex: 1; padding: 6px 10px;">
          <button class="btn-primary" onclick="saveModuleEdits('${d.session_key}', ${d.channel})">Save</button>
        </div>
      </div>
    `;
  } catch (e) {
    $("#module-modal-body").innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

async function saveModuleEdits(sk, ch) {
  await apiPost("/api/modules/override", {
    session_key: sk, channel: ch,
    status: $("#module-status-edit").value,
    notes:  $("#module-notes-edit").value,
  });
  closeModal("module-modal");
  loadPool();
}

// ---------- POOL with bulk select + inline edit ----------
let _pool = [];
let _bulkSelection = new Set();

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
$("#filter-grade").addEventListener("change", renderPool);
$("#filter-hide-unlabelled").addEventListener("change", renderPool);

const GRADE_TIPS = {
  A: "Excellent — pack-grade module, top choice",
  B: "Good — solid candidate, use freely",
  C: "Acceptable — use when stronger modules unavailable",
  D: "Marginal — last resort, will reduce pack lifespan",
  F: "Reject — too weak / IR too high, do not use in pack",
};
const GRADE_RANK = { A: 5, B: 4, C: 3, D: 2, F: 1 };

function gradeBadge(grade, reason) {
  const tip = (GRADE_TIPS[grade] || "") + (reason ? "\n\n" + reason : "");
  return `<span class="module-grade ${grade}" data-tip="${escapeHtml(tip)}">${grade}</span>`;
}

function refKey(m) { return `${m.session_key}|${m.channel}`; }

function renderPool() {
  const fb = $("#filter-battery").value;
  const fs = $("#filter-status").value;
  const ft = $("#filter-trend").value;
  const fg = $("#filter-grade").value;
  const hideUnlabelled = $("#filter-hide-unlabelled").checked;
  let rows = _pool.slice();
  if (hideUnlabelled) rows = rows.filter(m => m.battery && m.cell_position);
  if (fb) rows = rows.filter(m => m.battery === fb);
  if (fs) rows = rows.filter(m => m.status === fs);
  if (ft) rows = rows.filter(m => m.trend === ft);
  if (fg) rows = rows.filter(m => fg.includes(m.quality_grade || ""));
  // Sort by grade descending (A first), then cap descending within grade
  rows.sort((a,b) => {
    const ga = GRADE_RANK[a.quality_grade] || 0;
    const gb = GRADE_RANK[b.quality_grade] || 0;
    if (gb !== ga) return gb - ga;
    return (b.cap_ah || 0) - (a.cap_ah || 0);
  });

  const hiddenCount = _pool.length - rows.length;
  $("#pool-count").textContent = hiddenCount > 0
    ? `${rows.length} shown · ${hiddenCount} hidden by filters`
    : `${rows.length} of ${_pool.length} modules`;
  updateBulkBar();

  const html = `
    <table>
      <thead><tr>
        <th><input type="checkbox" id="select-all-pool" onclick="bulkToggleAll(this.checked)"></th>
        <th>Grade</th>
        <th>Battery / Cell</th>
        <th>Source</th>
        <th>Cap (Ah)</th><th>IR (mΩ)</th><th>Vend (V)</th>
        <th>Trend</th>
        <th>Cycles</th>
        <th>Status</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>
        ${rows.map(m => {
          const k = refKey(m);
          const checked = _bulkSelection.has(k) ? "checked" : "";
          let tag;
          if (m.session_type === "testing") {
            tag = `<span class="cell-tag test" title="Testing/set-aside session — not for pack-building">${m.battery || 'TEST'}-${m.cell_position ?? '?'} (TEST)</span> <button class="tiny-edit" title="edit label" onclick="editPoolLabel('${m.session_key}', ${m.channel}, '${m.battery||''}', ${m.cell_position||0})">✎</button>`;
          } else if (m.battery) {
            tag = `<span class="cell-tag">${m.battery}-${m.cell_position ?? '?'}</span> <button class="tiny-edit" title="edit label" onclick="editPoolLabel('${m.session_key}', ${m.channel}, '${m.battery}', ${m.cell_position||0})">✎</button>`;
          } else {
            tag = `<span class="cell-tag unlab">unlabelled</span> <button class="tiny-edit" title="set label" onclick="editPoolLabel('${m.session_key}', ${m.channel}, '', 0)">✎</button>`;
          }
          return `
          <tr>
            <td><input type="checkbox" class="pool-checkbox" data-ref="${k}" ${checked} onclick="bulkToggle('${k}', this.checked)"></td>
            <td>${gradeBadge(m.quality_grade, m.quality_reason)}</td>
            <td>${tag}</td>
            <td><span class="detail-link" onclick="openModuleDetail('${m.session_key}', ${m.channel})">${m.session_key} · CH${m.channel}</span></td>
            <td>${fmt(m.cap_ah)}</td>
            <td>${fmt(m.ir_mohm, 1)}</td>
            <td>${fmt(m.v_end, 3)}</td>
            <td>${trendBadge(m.trend)}</td>
            <td><span class="cap-series" title="discharge caps each cycle — click for full detail" style="cursor:pointer" onclick="openModuleDetail('${m.session_key}', ${m.channel})">${(m.discharge_caps || []).map(c=>c.toFixed(2)).join('→')}</span></td>
            <td>
              <select class="status-edit" data-sk="${m.session_key}" data-ch="${m.channel}">
                ${["available","used","weak","dead","retired"].map(s => `<option value="${s}" ${s===m.status?'selected':''}>${s}</option>`).join("")}
              </select>
            </td>
            <td><input type="text" class="notes-edit" data-sk="${m.session_key}" data-ch="${m.channel}" value="${escapeHtml(m.notes||'')}" style="width: 140px; padding: 3px 6px; font-size: 12px;"></td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
  $("#pool-table-wrap").innerHTML = html;
  $$(".status-edit").forEach(sel => sel.addEventListener("change", async () => {
    await apiPost("/api/modules/override", {
      session_key: sel.dataset.sk, channel: sel.dataset.ch, status: sel.value,
    });
    loadPool();
  }));
  $$(".notes-edit").forEach(inp => inp.addEventListener("blur", async () => {
    await apiPost("/api/modules/override", {
      session_key: inp.dataset.sk, channel: inp.dataset.ch, notes: inp.value,
    });
  }));
}

async function editPoolLabel(sk, ch, currentBatt, currentCell) {
  const battery = prompt(`Battery letter for this module (current: ${currentBatt || 'none'}):`, currentBatt || '');
  if (battery === null) return;
  const cellStr = prompt(`Cell # 1-28 (current: ${currentCell || 'none'}):`, currentCell || '');
  if (cellStr === null) return;
  const cell = cellStr ? parseInt(cellStr) : null;
  if (battery && (!cell || cell < 1 || cell > 28)) { alert('cell must be 1-28'); return; }
  await apiPost("/api/modules/override", {
    session_key: sk, channel: ch,
    battery: battery.trim().toUpperCase() || null,
    cell_position: cell,
  });
  loadPool();
}

// ---------- BULK SELECT ----------
function bulkToggle(k, on) { if (on) _bulkSelection.add(k); else _bulkSelection.delete(k); updateBulkBar(); }
function bulkToggleAll(on) {
  $$(".pool-checkbox").forEach(cb => {
    cb.checked = on;
    if (on) _bulkSelection.add(cb.dataset.ref);
    else    _bulkSelection.delete(cb.dataset.ref);
  });
  updateBulkBar();
}
function bulkClear() { _bulkSelection.clear(); $("#select-all-pool").checked = false; renderPool(); }

function updateBulkBar() {
  const bar = $("#bulk-bar");
  if (_bulkSelection.size === 0) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  $("#bulk-count").textContent = `${_bulkSelection.size} module(s) selected`;
}

async function autoRetireGrade(grade) {
  const targets = _pool.filter(m => m.quality_grade === grade && m.status === "available");
  if (!targets.length) {
    alert(`No ${grade}-grade modules currently available to retire.`);
    return;
  }
  const action = grade === "F" ? "RECYCLE (scrap)" : "set aside as backup";
  if (!confirm(`Mark ${targets.length} ${grade}-grade module(s) as 'retired'?\n\nUse case: ${action}.\n\nThey'll be hidden from the default Pool view and won't appear in Build Pack candidates. You can restore them anytime by changing status back to 'available'.`)) return;
  const refs = targets.map(m => ({ session_key: m.session_key, channel: m.channel }));
  await apiPost("/api/modules/bulk", { refs, status: "retired" });
  alert(`${targets.length} ${grade}-grade modules retired. ${grade === "F" ? "Take them to a battery recycler when convenient." : "They're set aside but still in the system."}`);
  loadPool();
}

async function bulkSetStatus(status) {
  const refs = Array.from(_bulkSelection).map(k => {
    const [sk, ch] = k.split("|");
    return { session_key: sk, channel: parseInt(ch) };
  });
  if (!refs.length) return;
  if (!confirm(`Set ${refs.length} module(s) to "${status}"?`)) return;
  await apiPost("/api/modules/bulk", { refs, status });
  _bulkSelection.clear();
  loadPool();
}

// ---------- BUILD ----------
let _previewedPack = null;

async function loadBuildForm() {
  try {
    const pool = await apiGet("/api/pool");
    const batteries = [...new Set(pool.map(m => m.battery).filter(Boolean))].sort();
    const sel = $('#build-form select[name="target_battery"]');
    sel.innerHTML = '<option value="ANY">any (use whole pool)</option>' + batteries.map(b => `<option value="${b}">${b}</option>`).join("");
  } catch (e) { /* ignore */ }

  $("#build-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = readBuildForm();
    $("#build-result").innerHTML = '<p class="loading">Building pack…</p>';
    const pack = await apiPost("/api/packs/preview", body);
    renderPackResult(pack);
  };

  $("#compare-strategies-btn").onclick = async () => {
    const body = readBuildForm();
    delete body.strategy;
    $("#build-result").innerHTML = '<p class="loading">Comparing all 3 strategies…</p>';
    const res = await apiPost("/api/packs/compare", body);
    renderStrategyCompare(res);
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

function readBuildForm() {
  const f = $("#build-form");
  return {
    target_battery:    f.target_battery.value,
    allow_borrow:      f.allow_borrow.checked,
    strategy:          f.strategy.value,
    thermal_placement: f.thermal_placement.checked,
    target_blocks:     parseInt(f.target_blocks.value),
    cap_floor_reuse:   parseFloat(f.cap_floor_reuse.value),
    ir_ceiling_module: parseFloat(f.ir_ceiling_module.value),
    max_pack_cap_spread: parseFloat(f.max_pack_cap_spread.value),
    max_pack_ir_spread:  parseFloat(f.max_pack_ir_spread.value),
    require_labelled:    f.allow_unlabelled.checked ? 0 : 1,  // checkbox flips the flag
    pack_name:         f.pack_name.value.trim(),
    destination:       f.destination.value,
  };
}

function renderStrategyCompare(results) {
  const order = [
    ["pair_opposites", "Pair-opposites", "Mask weak cells, ECU-friendly. Standard for daily-driver."],
    ["match_similar",  "Match-similar",  "Strong-with-strong. Better diagnostics, weak blocks fail visibly."],
    ["capacity_only",  "Capacity-only",  "Take top N by cap, pair adjacent. Simplest."],
  ];

  // Pick best by grade
  const gradeRank = {A:5,B:4,C:3,D:2,F:1};
  let bestName = null, bestRank = -1;
  for (const [k] of order) {
    const p = results[k];
    if (p && !p.error) {
      const r = gradeRank[p.grade] || 0;
      if (r > bestRank) { bestRank = r; bestName = k; }
    }
  }

  const cards = order.map(([k, name, blurb]) => {
    const p = results[k];
    if (!p || p.error) {
      return `<div class="strategy-card">
        <div class="strat-name">${name}</div>
        <div style="color: var(--muted); font-size: 12px;">${blurb}</div>
        <div style="margin-top: 8px; color: var(--danger); font-size: 13px;">${p?.error || 'unavailable'}</div>
      </div>`;
    }
    const recommended = k === bestName ? "recommended" : "";
    return `<div class="strategy-card ${recommended}" onclick="renderPackResult(${escapeHtml(JSON.stringify(p))})">
      <div class="strat-name">${name} ${recommended ? '★ best' : ''}</div>
      <div style="color: var(--muted); font-size: 12px;">${blurb}</div>
      <div style="margin-top: 10px;">
        <span class="strat-grade pack-grade ${p.grade}">${p.grade}</span>
        <span style="font-size: 12px; margin-left: 8px;">${p.predicted_life}</span>
      </div>
      <div class="strat-stat">avg ${fmt(p.avg_cap)} Ah · spread ${fmt(p.cap_spread)} Ah · weakest ${fmt(p.weakest_cap)} Ah</div>
      <div class="strat-stat" style="margin-top: 4px; color: var(--primary)">click to see details →</div>
    </div>`;
  }).join("");

  $("#build-result").innerHTML = `
    <h3 style="margin-top: 18px;">Strategy comparison</h3>
    <p class="hint">All 3 strategies on the same eligible pool. Click a card to see its block layout.</p>
    <div class="strategy-compare">${cards}</div>
  `;
}

function renderPackResult(pack) {
  // pack may arrive serialized as a string from onclick
  if (typeof pack === "string") { try { pack = JSON.parse(pack); } catch (_) {} }

  if (pack.error) {
    let html = `<div class="error-msg">⚠ ${pack.error}</div>`;
    if (pack.candidate_summary) html += summarizeCandidates(pack.candidate_summary);
    if (pack.threshold_suggestions) html += renderThresholdSuggestions(pack.threshold_suggestions, pack.needed);
    if (pack.rejected_modules?.length) html += renderRejected(pack.rejected_modules);
    $("#build-result").innerHTML = html;
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
  const swaps = (pack.swap_suggestions || []).map(s => `<div>• ${s}</div>`).join("");

  $("#build-result").innerHTML = `
    <div class="pack-summary">
      <div style="font-size: 16px; margin-bottom: 8px;">
        <strong>${escapeHtml(pack.pack_name || pack.pack_id)}</strong>
        ${pack.source_summary ? `<span style="color: var(--muted); font-weight: normal; margin-left: 12px;"><strong>Sources:</strong> ${escapeHtml(pack.source_summary)}</span>` : ''}
      </div>
      <div>
        <span class="pack-grade ${pack.grade}">${pack.grade}</span>
        <span class="predicted-life">Predicted life in service: <strong>${pack.predicted_life}</strong></span>
        <span class="tooltip" data-tip="Estimates from PriusChat refurb-life threads, Hybrid Automotive guides, and reconditioner blogs. Real-world life depends on driver habits, climate, and luck. ±50% range typical." style="margin-left: 6px; color: var(--muted)">ⓘ</span>
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
      ${ swaps ? `<div class="swap-suggestions"><h4>How to improve this pack</h4>${swaps}</div>` : '' }
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
    ${ renderPairingVerification(pack) }
    ${ renderPreInstallChecklist(pack) }
    ${ pack.rejected_modules?.length ? renderRejected(pack.rejected_modules) : '' }
  `;
}

function renderPairingVerification(pack) {
  if (!pack.block_layout) return "";
  const summary = pack.verification_summary || {};
  const tag = (m) => m ? (m.battery ? `${m.battery}-${m.cell_position}` : `(CH${m.channel})`) : "—";
  const ico = { pass: "✓", warn: "!", fail: "✗" };

  const blockCards = pack.block_layout.map(b => {
    const checks = (b.verifications || []).map(c => `
      <div class="check-row ${c.status}">
        <span class="check-icon">${ico[c.status]}</span>
        <span class="check-label">${escapeHtml(c.label)}</span>
        <span class="check-detail">${escapeHtml(c.detail)}</span>
        <span class="check-source">${escapeHtml(c.source)}</span>
      </div>
    `).join("");
    return `
      <div class="block-verify ${b.verdict}">
        <div class="block-verify-head">
          <span class="block-num">Block ${b.block_number}</span>
          <span class="block-modules">${tag(b.a)} (${fmt(b.a?.cap_ah)} Ah, ${fmt(b.a?.ir_mohm,1)} mΩ) <strong>+</strong> ${tag(b.b)} (${fmt(b.b?.cap_ah)} Ah, ${fmt(b.b?.ir_mohm,1)} mΩ)</span>
          <span class="block-overall">${b.verdict}</span>
        </div>
        ${checks}
      </div>
    `;
  }).join("");

  return `
    <div class="pairing-verification">
      <h3>Pairing Verification — every block checked against industry standards</h3>
      <p style="font-size: 12px; color: var(--muted); margin-top: -6px;">
        Each pair runs 5 checks: IR delta, IR ceiling, Vend delta, block uniformity (P0A80 prevention), and trend compatibility.
        Sources: PriusChat #221864/#239581/#151459, Hybrid Automotive Prolong, Dr. Prius app docs, wrouesnel rebuild guide.
      </p>
      <div class="pack-summary-bar">
        <span style="background: #dcfce7; color: #166534;">✓ ${summary.pass_blocks || 0} blocks PASS</span>
        <span style="background: #fef3c7; color: #92400e;">! ${summary.warn_blocks || 0} blocks WARN</span>
        <span style="background: #fee2e2; color: #991b1b;">✗ ${summary.fail_blocks || 0} blocks FAIL</span>
      </div>
      ${blockCards}
    </div>
  `;
}

function renderPreInstallChecklist(pack) {
  if (!pack.pre_install_checklist) return "";
  const items = pack.pre_install_checklist.map((c, idx) => `
    <label>
      <input type="checkbox" data-idx="${idx}">
      <span>
        ${escapeHtml(c.label)}
        <span class="checklist-source">${escapeHtml(c.source)}</span>
      </span>
    </label>
  `).join("");
  return `
    <div class="pre-install-checklist">
      <h4>⚠ Pre-Install Checklist — confirm each item BEFORE bolting modules into the pack housing</h4>
      ${items}
      <p style="margin: 8px 0 0; font-size: 11px; color: var(--muted);">
        Industry torque specs: busbar nuts 48 in-lb (5.4 N·m), module bolts 84 in-lb (9.5 N·m). Toyota service spec.
      </p>
    </div>
  `;
}

function moduleCell(m) {
  if (!m) return "<em>—</em>";
  const tag = m.battery ? `${m.battery}-${m.cell_position}` : `(${m.session_key} CH${m.channel})`;
  return `<strong>${tag}</strong> <span style="color:var(--muted)">${fmt(m.cap_ah)}Ah ${fmt(m.ir_mohm,1)}mΩ</span> ${trendBadge(m.trend, {small: true})}`;
}

function summarizeCandidates(s) {
  const byBat = Object.entries(s.by_battery || {}).map(([k,v]) => `${k}: ${v}`).join(" · ");
  return `<p style="color: var(--muted); font-size: 13px;">Candidate pool: ${s.eligible} eligible of ${s.total_modules} total (${byBat || 'none labelled yet'})</p>`;
}

function renderThresholdSuggestions(suggestions, needed) {
  const rows = suggestions.map(s => {
    const cls = s.enough ? "enough" : "";
    const status = s.enough
      ? `✓ enough (${s.eligible} ≥ ${needed})`
      : `${s.eligible} eligible — short by ${s.deficit}`;
    return `<tr class="${cls}">
      <td>${escapeHtml(s.label)}</td>
      <td>cap ≥ ${s.cap_floor}</td>
      <td>IR ≤ ${s.ir_ceiling}</td>
      <td>${status}</td>
    </tr>`;
  }).join("");
  return `<div class="threshold-suggestions">
    <h4>Try lowering thresholds — or test more batteries</h4>
    <table>
      <thead><tr><th>Threshold preset</th><th>Cap floor</th><th>IR ceiling</th><th>Result</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p style="margin: 6px 0 0; color: var(--muted); font-size: 11px;">Lowering thresholds includes weaker modules (shorter pack life). Better long-term: test more batteries to grow the candidate pool.</p>
  </div>`;
}

function renderRejected(rejected) {
  const rows = rejected.slice(0, 50).map(m => {
    const tag = m.battery ? `${m.battery}-${m.cell_position}` : `${m.session_key} CH${m.channel}`;
    return `<div class="row"><strong>${tag}</strong> · cap ${fmt(m.cap_ah)} Ah · IR ${fmt(m.ir_mohm,1)} mΩ · ${m.reject_reasons.join(', ')}</div>`;
  }).join("");
  return `<div class="rejected-list">
    <h4>${rejected.length} module(s) rejected from candidate pool</h4>
    ${rows}
    ${rejected.length > 50 ? `<div style="margin-top: 6px; color: var(--muted)">…and ${rejected.length-50} more</div>` : ''}
  </div>`;
}

// ---------- HISTORY ----------
let _packsCache = [];
async function loadHistory() {
  const el = $("#history-list");
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const packs = await apiGet("/api/packs");
    _packsCache = packs;
    if (!packs.length) {
      el.innerHTML = "<p>No packs built yet. Go to Build Pack tab to create one.</p>";
      return;
    }
    el.innerHTML = packs.map(p => `
      <div class="pack-summary" id="pack-row-${p.pack_id}">
        <div>
          <span class="pack-grade ${p.grade}">${p.grade}</span>
          <strong class="pack-name-display">${escapeHtml(p.pack_name || p.pack_id)}</strong>
          <button class="tiny-edit" title="rename" onclick="renamePack('${p.pack_id}')">✎</button>
          <span style="color: var(--muted); font-size: 11px; margin-left: 8px;">id ${p.pack_id} · built ${p.built_at}</span>
          <span style="float: right;">
            <button class="btn-secondary" onclick="viewPackBlocks('${p.pack_id}')">View blocks</button>
            <button class="btn-danger" onclick="deletePack('${p.pack_id}')">Delete & release</button>
          </span>
        </div>
        ${p.source_summary ? `<div style="margin-top: 6px; font-size: 13px;"><strong>Sources:</strong> ${escapeHtml(p.source_summary)}</div>` : ''}
        <div class="pack-stats" style="margin-top: 6px;">
          <div class="stat"><span class="label">Predicted life</span><span class="value">${p.predicted_life}</span></div>
          <div class="stat"><span class="label">Blocks</span><span class="value">${p.block_count}</span></div>
          <div class="stat"><span class="label">Avg cap</span><span class="value">${fmt(p.avg_cap)} Ah</span></div>
          <div class="stat"><span class="label">Cap spread</span><span class="value">${fmt(p.cap_spread)} Ah</span></div>
          <div class="stat"><span class="label">Weakest</span><span class="value">${fmt(p.weakest_cap)} Ah</span></div>
          <div class="stat"><span class="label">Strategy</span><span class="value">${p.strategy}</span></div>
        </div>
        <div style="margin-top: 8px; display: flex; gap: 10px; align-items: center;">
          <label style="font-size: 12px; color: var(--muted);">Destination:</label>
          <input type="text" class="dest-edit" data-pack="${p.pack_id}" value="${escapeHtml(p.destination||'')}" placeholder="customer / vehicle / shelf #" style="flex: 1; padding: 4px 8px; font-size: 12px;">
          <label style="font-size: 12px; color: var(--muted);">Notes:</label>
          <input type="text" class="notes-pack-edit" data-pack="${p.pack_id}" value="${escapeHtml(p.notes||'')}" style="flex: 2; padding: 4px 8px; font-size: 12px;">
        </div>
      </div>
    `).join("");

    $$(".dest-edit").forEach(inp => inp.addEventListener("blur", async () => {
      await apiPost(`/api/packs/${inp.dataset.pack}/edit`, { destination: inp.value });
    }));
    $$(".notes-pack-edit").forEach(inp => inp.addEventListener("blur", async () => {
      await apiPost(`/api/packs/${inp.dataset.pack}/edit`, { notes: inp.value });
    }));
  } catch (e) {
    el.innerHTML = `<div class="error-msg">${e}</div>`;
  }
}

async function renamePack(id) {
  const cur = _packsCache.find(p => p.pack_id === id);
  const newName = prompt(`Rename this pack (current: "${cur?.pack_name || id}"):`, cur?.pack_name || "");
  if (newName === null || newName.trim() === "") return;
  const r = await apiPost(`/api/packs/${id}/edit`, { pack_name: newName.trim() });
  if (r.ok) loadHistory(); else alert("rename failed: " + JSON.stringify(r));
}

function viewPackBlocks(id) {
  const p = _packsCache.find(x => x.pack_id === id);
  if (!p) return;
  $("#module-modal-title").innerHTML = `Pack: <strong>${escapeHtml(p.pack_name || p.pack_id)}</strong>
    <span style="color: var(--muted); font-size: 13px;">(${p.block_count} blocks · grade ${p.grade} · ${p.predicted_life})</span>`;
  const rows = (p.block_layout || []).map(b => `
    <tr>
      <td><strong>${b.block_number}</strong></td>
      <td>${moduleCell(b.a)}</td>
      <td>${moduleCell(b.b)}</td>
      <td>${fmt(b.block_cap)}</td>
      <td>${fmt(b.block_ir, 1)}</td>
      <td style="color: ${b.cap_gap > 0.5 ? 'var(--danger)' : 'var(--muted)'}">${fmt(b.cap_gap)}</td>
    </tr>
  `).join("");
  $("#module-modal-body").innerHTML = `
    <div class="module-section">
      <p style="margin-top: 0; font-size: 13px;">
        <strong>Sources:</strong> ${escapeHtml(p.source_summary || '—')}<br>
        <strong>Built:</strong> ${p.built_at} · <strong>Strategy:</strong> ${p.strategy}<br>
        ${p.destination ? `<strong>Destination:</strong> ${escapeHtml(p.destination)}<br>` : ''}
        ${p.notes ? `<strong>Notes:</strong> ${escapeHtml(p.notes)}` : ''}
      </p>
    </div>
    <div class="module-section">
      <h4>Block layout</h4>
      <table>
        <thead><tr>
          <th>Block</th><th>Module A (high)</th><th>Module B (low)</th>
          <th>Block cap</th><th>Block IR</th><th>Cap gap</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
  $("#module-modal").classList.remove("hidden");
}

async function deletePack(id) {
  const cur = _packsCache.find(p => p.pack_id === id);
  const name = cur?.pack_name || id;
  if (!confirm(`Delete "${name}" and release its modules back to the pool?`)) return;
  await apiDel(`/api/packs/${id}`);
  loadHistory();
}

// ---------- refresh ----------
function refreshAll() {
  const active = $(".tab.active").dataset.tab;
  switchTab(active);
}

// ---------- init ----------
showCutoffReminder();
renderPendingBanner();
loadDashboard();
