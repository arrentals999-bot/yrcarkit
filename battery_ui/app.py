"""
YRCARKIT Battery UI — Flask app.
Run with:   python -m battery_ui.app    (from the YRCARKIT folder)
or          python app.py               (from inside battery_ui/)
"""

import sys
import json
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, request, render_template, abort, Response

# Allow running as script or module
HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from battery_ui import db, pairing  # noqa: E402

app = Flask(__name__,
            template_folder=str(HERE / "templates"),
            static_folder=str(HERE / "static"))


# ---------- HTTP Basic Auth (only enforced on non-loopback requests) ----------
# Reads credentials from tunnel/credentials.json. If that file is absent,
# auth is disabled entirely (development / no-tunnel mode).

CREDS_PATH = HERE.parent / "tunnel" / "credentials.json"


def _load_creds():
    try:
        with open(CREDS_PATH) as f:
            d = json.load(f)
        return d.get("username"), d.get("password")
    except Exception:
        return None, None


@app.before_request
def _enforce_auth():
    user, pw = _load_creds()
    if not user or not pw:
        return None  # auth disabled — no creds file
    # Tunnel detection: Cloudflare adds X-Forwarded-For + Cf-Connecting-IP
    # on every proxied request. If neither is present, the request came
    # from real loopback (laptop user) and we skip auth for convenience.
    via_tunnel = bool(
        request.headers.get("Cf-Connecting-IP")
        or request.headers.get("X-Forwarded-For")
        or request.headers.get("Cf-Ray")
    )
    if not via_tunnel:
        return None
    auth = request.authorization
    if not auth or auth.username != user or auth.password != pw:
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Ratans Private Battery Manager"'},
        )
    return None


# ----------------------- views -----------------------

@app.route("/")
def index():
    return render_template("index.html")


# ----------------------- API: sessions -----------------------

@app.get("/api/sessions")
def api_sessions():
    sessions = db.scan_sessions()
    out = []
    for s in sessions:
        label = db.get_session_label(s["session_key"])
        # collect trend distribution for this session
        trend_dist = {}
        worst_cap = best_cap = None
        for ch in s["channels"]:
            cycles = db.read_cycles_for_channel(s["channel_paths"][ch])
            target = db.find_target_discharge(cycles)
            dis_caps = [c["cap_ah"] for c in cycles if c["kind"] == "F"]
            t = pairing.classify_trend(dis_caps)
            trend_dist[t] = trend_dist.get(t, 0) + 1
            if target and target["cap_ah"] is not None:
                worst_cap = target["cap_ah"] if worst_cap is None else min(worst_cap, target["cap_ah"])
                best_cap  = target["cap_ah"] if best_cap  is None else max(best_cap,  target["cap_ah"])
        out.append({
            "session_key":   s["session_key"],
            "started":       s["started"],
            "date":          s["date"],
            "channels":      s["channels"],
            "label":         label,
            "trend_dist":    trend_dist,
            "cap_range":     [worst_cap, best_cap] if worst_cap is not None else None,
        })
    return jsonify(out)


@app.get("/api/sessions/<session_key>")
def api_session_detail(session_key):
    sessions = {s["session_key"]: s for s in db.scan_sessions()}
    if session_key not in sessions:
        abort(404)
    s = sessions[session_key]
    label = db.get_session_label(session_key)

    skip = {3}
    if label:
        try:
            skip = set(json.loads(label["skip_channels"]))
        except Exception:
            skip = {3}

    channels_out = []
    for ch in s["channels"]:
        fp = s["channel_paths"][ch]
        cycles = db.read_cycles_for_channel(fp)
        target = db.find_target_discharge(cycles)
        dis_caps = [c["cap_ah"] for c in cycles if c["kind"] == "F"]
        trend = pairing.classify_trend(dis_caps)
        override = db.get_module_override(session_key, ch) or {}
        channels_out.append({
            "channel":       ch,
            "skipped":       ch in skip,
            "cap_ah":        target["cap_ah"] if target else None,
            "ir_mohm":       target["ir_mohm"] if target else None,
            "v_end":         target["v_end"] if target else None,
            "discharge_caps": dis_caps,
            "n_cycles":      len(dis_caps),
            "trend":         trend,
            "trend_desc":    pairing.TREND_DESCRIPTION.get(trend, ""),
            "override":      override,
        })
    return jsonify({
        "session_key": session_key,
        "started":     s["started"],
        "date":        s["date"],
        "label":       label,
        "channels":    channels_out,
    })


PENDING_LABEL_PATH = HERE / "pending_label.json"


@app.get("/api/labelling/pending")
def api_pending_label_get():
    """Read the queued label that will auto-apply to the next-detected session."""
    if not PENDING_LABEL_PATH.exists():
        return jsonify({"pending": None})
    try:
        with open(PENDING_LABEL_PATH) as f:
            return jsonify({"pending": json.load(f)})
    except Exception as e:
        return jsonify({"pending": None, "error": str(e)})


@app.post("/api/labelling/pending")
def api_pending_label_set():
    """Queue a label that will auto-apply to the next new session detected."""
    data = request.get_json(force=True) or {}
    battery = (data.get("battery") or "").strip().upper()
    if not battery:
        return jsonify({"error": "battery required"}), 400
    payload = {
        "battery":      battery,
        "cell_start":   int(data.get("cell_start", 1)),
        "cell_end":     int(data.get("cell_end", 7)),
        "skip_channels": data.get("skip_channels") or [3],
        "session_type": data.get("session_type", "production"),
        "notes":        data.get("notes", ""),
        "queued_at":    __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    with open(PENDING_LABEL_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    return jsonify({"ok": True, "pending": payload})


@app.delete("/api/labelling/pending")
def api_pending_label_clear():
    if PENDING_LABEL_PATH.exists():
        PENDING_LABEL_PATH.unlink()
    return jsonify({"ok": True})


@app.post("/api/labelling/apply-pending/<session_key>")
def api_apply_pending(session_key):
    """Apply the queued label to a specific session_key, then clear the queue."""
    if not PENDING_LABEL_PATH.exists():
        return jsonify({"error": "no pending label queued"}), 404
    try:
        with open(PENDING_LABEL_PATH) as f:
            p = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    sessions = {s["session_key"]: s for s in db.scan_sessions()}
    if session_key not in sessions:
        return jsonify({"error": f"session {session_key} not found"}), 404

    skip = p["skip_channels"]
    active = [c for c in sessions[session_key]["channels"] if c not in skip]
    n_cells = p["cell_end"] - p["cell_start"] + 1
    if p["session_type"] == "production" and n_cells != len(active):
        # Cell range doesn't match — leave queue intact, return error so user fixes manually
        return jsonify({"error":
            f"queued range covers {n_cells} cells but {len(active)} channels active. "
            f"Fix the queue or label manually."}), 400

    db.save_session_label(session_key, p["battery"], p["cell_start"], p["cell_end"],
                           skip, p["notes"], p["session_type"])
    PENDING_LABEL_PATH.unlink()
    return jsonify({"ok": True, "applied": p, "session_key": session_key})


@app.get("/api/labelling/suggest-next")
def api_suggest_next_label():
    """When a new YRCARKIT session appears, compute likely-correct labels.
    Adapts to the LATEST session's active channel count so partial-channel
    swaps (e.g., user reloaded only CH1 + CH2) get suggestions sized correctly."""
    sessions = db.scan_sessions()
    if not sessions:
        return jsonify({"current_battery": None, "suggestions": []})

    # How many channels are active in the latest session? (drives cell count)
    latest = sessions[-1]
    skip = {3}
    latest_label = db.get_session_label(latest["session_key"])
    if latest_label:
        try:
            skip = set(json.loads(latest_label["skip_channels"]))
        except Exception:
            pass
    active_channels_latest = sorted([c for c in latest["channels"] if c not in skip])
    n_active = len(active_channels_latest)

    # Walk all session labels to figure out where each battery stands
    conn = db.get_local_conn()
    labels = {r["session_key"]: dict(r) for r in conn.execute(
        "SELECT * FROM session_labels WHERE session_type='production'"
    )}
    conn.close()

    battery_progress = {}  # battery -> set of cell positions covered
    for sk, lbl in labels.items():
        bat = lbl["battery"]
        battery_progress.setdefault(bat, set())
        for c in range(lbl["cell_start"], lbl["cell_end"] + 1):
            battery_progress[bat].add(c)

    suggestions = []
    # Find the most recent battery being worked on (still has < 28 labelled)
    in_progress = sorted(
        [(b, len(c)) for b, c in battery_progress.items() if len(c) < 28],
        key=lambda x: -x[1]
    )
    if in_progress:
        bat, count = in_progress[0]
        covered = battery_progress[bat]
        # find next gap
        next_start = None
        for c in range(1, 29):
            if c not in covered:
                next_start = c
                break
        if next_start:
            # Extend by n_active-1 (or fewer if hit a covered cell or 28)
            next_end = min(next_start + n_active - 1, 28)
            for c in range(next_start + 1, next_end + 1):
                if c in covered:
                    next_end = c - 1
                    break
            n_cells = next_end - next_start + 1
            suggestions.append({
                "kind": "continue_battery",
                "label": f"Continue Battery {bat} - cells {next_start} to {next_end} ({n_cells} cells)",
                "battery": bat,
                "cell_start": next_start,
                "cell_end": next_end,
                "session_type": "production",
                "explanation": f"Battery {bat} has {count}/28 labelled. {n_active} channels active in this session, so suggesting cells {next_start}-{next_end}.",
            })

    # Suggest a new battery letter (next available after the latest)
    used = sorted(battery_progress.keys())
    next_letter = "A"
    if used:
        real = [b for b in used if b != "TEST"]
        if real:
            last = max(real)
            if last < "Z":
                next_letter = chr(ord(last) + 1)
            else:
                next_letter = "AA"
    new_end = min(n_active, 28)
    suggestions.append({
        "kind": "new_battery",
        "label": f"Start new Battery {next_letter} - cells 1 to {new_end} ({n_active} cells)",
        "battery": next_letter,
        "cell_start": 1,
        "cell_end": new_end,
        "session_type": "production",
        "explanation": f"Begin a new pack. Letter {next_letter} is next available. {n_active} channels active.",
    })

    # Always offer testing
    suggestions.append({
        "kind": "testing",
        "label": f"Testing / set-aside ({n_active} channels)",
        "battery": "TEST",
        "cell_start": 1,
        "cell_end": new_end,
        "session_type": "testing",
        "explanation": "Use for module sanity-checks, retests, or experimental work. Won't be eligible for pack-building.",
    })

    return jsonify({
        "battery_progress": {b: sorted(c) for b, c in battery_progress.items()},
        "latest_session": latest["session_key"],
        "active_channels": active_channels_latest,
        "n_active_channels": n_active,
        "suggestions": suggestions,
    })


@app.post("/api/sessions/<session_key>/label")
def api_label_session(session_key):
    data = request.get_json(force=True)
    battery = (data.get("battery") or "").strip().upper()
    cell_start = int(data.get("cell_start"))
    cell_end = int(data.get("cell_end"))
    skip = data.get("skip_channels") or [3]
    notes = data.get("notes") or ""
    session_type = data.get("session_type", "production")
    if session_type not in ("production", "testing"):
        return jsonify({"error": "session_type must be 'production' or 'testing'"}), 400

    if not battery:
        return jsonify({"error": "battery letter required"}), 400
    if session_type == "production" and not battery.isalpha():
        return jsonify({"error": "production battery must be a letter A-Z"}), 400
    if session_type == "production" and (cell_start < 1 or cell_end > 28 or cell_end < cell_start):
        return jsonify({"error": "cell range must be within 1-28 and ascending"}), 400

    sessions = {s["session_key"]: s for s in db.scan_sessions()}
    if session_key not in sessions:
        return jsonify({"error": f"session {session_key} not found"}), 404
    active_channels = [c for c in sessions[session_key]["channels"] if c not in skip]
    n_cells = cell_end - cell_start + 1
    # Validate cell-range count for production only — testing is freeform
    if session_type == "production" and n_cells != len(active_channels):
        return jsonify({"error":
            f"cell range covers {n_cells} cells but {len(active_channels)} channels are active "
            f"({active_channels}). Either widen the range or add channels to skip list."}), 400

    db.save_session_label(session_key, battery, cell_start, cell_end, skip, notes, session_type)
    return jsonify({"ok": True})


# ----------------------- API: modules pool -----------------------

@app.get("/api/pool")
def api_pool():
    pool = db.build_module_pool()
    return jsonify(pool)


@app.get("/api/modules/<session_key>/<int:channel>")
def api_module_detail(session_key, channel):
    """Full per-cell detail: every cycle (charge + discharge) with cap, IR,
    Vend, duration, plus historical tests of the same cell in other sessions
    (if it's labelled)."""
    sessions = {s["session_key"]: s for s in db.scan_sessions()}
    if session_key not in sessions:
        abort(404)
    s = sessions[session_key]
    if channel not in s["channels"]:
        abort(404)

    fp = s["channel_paths"][channel]
    cycles = db.read_cycles_for_channel(fp)
    target = db.find_target_discharge(cycles)
    dis_caps = [c["cap_ah"] for c in cycles if c["kind"] == "F"]
    trend = pairing.classify_trend(dis_caps)

    # determine battery + cell for this module (from override or label)
    override = db.get_module_override(session_key, channel) or {}
    label = db.get_session_label(session_key)
    battery = override.get("battery") or (label["battery"] if label else None)
    cell_pos = override.get("cell_position")
    if not cell_pos and label:
        skip = set(json.loads(label["skip_channels"]) if label.get("skip_channels") else [3])
        active = [c for c in s["channels"] if c not in skip]
        if channel in active:
            idx = active.index(channel)
            cell_pos = label["cell_start"] + idx

    # walk other sessions for the same battery+cell
    history = []
    if battery and cell_pos:
        for other in db.scan_sessions():
            if other["session_key"] == session_key:
                continue
            other_label = db.get_session_label(other["session_key"])
            if not other_label or other_label["battery"] != battery:
                continue
            if not (other_label["cell_start"] <= cell_pos <= other_label["cell_end"]):
                continue
            other_skip = set(json.loads(other_label.get("skip_channels", "[3]")))
            other_active = [c for c in other["channels"] if c not in other_skip]
            cell_offset = cell_pos - other_label["cell_start"]
            if cell_offset < len(other_active):
                other_ch = other_active[cell_offset]
                other_fp = other["channel_paths"].get(other_ch)
                if other_fp:
                    o_cycles = db.read_cycles_for_channel(other_fp)
                    o_target = db.find_target_discharge(o_cycles)
                    o_dis_caps = [c["cap_ah"] for c in o_cycles if c["kind"] == "F"]
                    history.append({
                        "session_key": other["session_key"],
                        "started":     other["started"],
                        "channel":     other_ch,
                        "cap_ah":      o_target["cap_ah"] if o_target else None,
                        "ir_mohm":     o_target["ir_mohm"] if o_target else None,
                        "v_end":       o_target["v_end"] if o_target else None,
                        "n_discharges": len(o_dis_caps),
                        "trend":       pairing.classify_trend(o_dis_caps),
                        "discharge_caps": o_dis_caps,
                    })
        history.sort(key=lambda h: h["started"], reverse=True)

    return jsonify({
        "session_key":    session_key,
        "session_started": s["started"],
        "channel":        channel,
        "battery":        battery,
        "cell_position":  cell_pos,
        "status":         override.get("status", "available"),
        "notes":          override.get("notes", ""),
        "trend":          trend,
        "trend_desc":     pairing.TREND_DESCRIPTION.get(trend, ""),
        "target":         target,
        "cycles":         cycles,
        "history":        history,
    })


@app.post("/api/modules/override")
def api_module_override():
    """Update an override. Fields are only changed if the request body
    explicitly contains the key. Pass null/'' to clear, or a value to set."""
    data = request.get_json(force=True)
    sk = data.get("session_key")
    ch = int(data.get("channel"))

    # Only forward keys actually present — otherwise preserve existing
    kwargs = {}
    if "battery" in data:
        v = data["battery"]
        kwargs["battery"] = (v.strip().upper() if isinstance(v, str) and v.strip() else None)
    if "cell_position" in data:
        v = data["cell_position"]
        if v is None or v == "":
            kwargs["cell_position"] = None
        else:
            try: kwargs["cell_position"] = int(v)
            except (TypeError, ValueError): kwargs["cell_position"] = None
    if "status" in data:
        kwargs["status"] = data["status"] or "available"
    if "notes" in data:
        kwargs["notes"] = data["notes"] or ""

    db.save_module_override(sk, ch, **kwargs)
    return jsonify({"ok": True})


@app.post("/api/modules/bulk")
def api_modules_bulk():
    """Bulk-update status (and optionally notes) for many modules at once.
    Body: { "refs": [{session_key, channel}, ...], "status": "retired", "notes": "..." }
    """
    data = request.get_json(force=True)
    refs = data.get("refs") or []
    status = data.get("status")
    notes = data.get("notes")
    for r in refs:
        db.save_module_override(
            r["session_key"], int(r["channel"]),
            status=status, notes=notes,
        )
    return jsonify({"ok": True, "updated": len(refs)})


# ----------------------- API: pack building -----------------------

@app.post("/api/packs/preview")
def api_pack_preview():
    """Build a candidate pack but don't save."""
    data = request.get_json(force=True) or {}
    pool = db.build_module_pool()

    # Optional filter: only use modules from a specific battery (with borrowing fallback)
    target_battery = data.get("target_battery")  # None = use everything

    def select_modules():
        if not target_battery or target_battery == "ANY":
            return pool
        primary = [m for m in pool if (m.get("battery") or "").upper() == target_battery.upper()]
        if data.get("allow_borrow", True):
            others = [m for m in pool if (m.get("battery") or "").upper() != target_battery.upper()]
            return primary + others
        return primary

    candidates = select_modules()
    target_blocks = int(data.get("target_blocks", 14))
    strategy = data.get("strategy", "pair_opposites")
    thermal = bool(data.get("thermal_placement", True))

    thresholds = pairing.DEFAULT_THRESHOLDS.copy()
    for k in thresholds:
        if k in data:
            try:
                thresholds[k] = float(data[k])
            except (TypeError, ValueError):
                pass

    pack = pairing.build_pack(
        candidates,
        target_blocks=target_blocks,
        strategy=strategy,
        thermal_placement=thermal,
        thresholds=thresholds,
        destination=data.get("destination", ""),
        notes=data.get("notes", ""),
        pack_name=data.get("pack_name", ""),
    )

    summary = pairing.build_pack_summary(candidates)
    pack["candidate_summary"] = summary
    pack["target_battery"] = target_battery
    return jsonify(pack)


@app.post("/api/packs/compare")
def api_pack_compare():
    """Build the pack with all 3 strategies and return summary stats for each
    so the user can pick the best one. Doesn't save anything."""
    data = request.get_json(force=True) or {}
    pool = db.build_module_pool()
    target_battery = data.get("target_battery")

    def select_modules():
        if not target_battery or target_battery == "ANY":
            return pool
        primary = [m for m in pool if (m.get("battery") or "").upper() == target_battery.upper()]
        if data.get("allow_borrow", True):
            others = [m for m in pool if (m.get("battery") or "").upper() != target_battery.upper()]
            return primary + others
        return primary

    candidates = select_modules()
    target_blocks = int(data.get("target_blocks", 14))
    thermal = bool(data.get("thermal_placement", True))

    thresholds = pairing.DEFAULT_THRESHOLDS.copy()
    for k in thresholds:
        if k in data:
            try:
                thresholds[k] = float(data[k])
            except (TypeError, ValueError):
                pass

    results = {}
    for strat in ("pair_opposites", "match_similar", "capacity_only"):
        p = pairing.build_pack(candidates, target_blocks=target_blocks,
                               strategy=strat, thermal_placement=thermal,
                               thresholds=thresholds)
        results[strat] = p
    return jsonify(results)


@app.post("/api/packs/save")
def api_pack_save():
    pack = request.get_json(force=True)
    if "error" in pack or "block_layout" not in pack:
        return jsonify({"error": "invalid pack payload"}), 400

    # mark modules used
    refs = []
    for b in pack["block_layout"]:
        for pos in ("a", "b"):
            m = b.get(pos)
            if m:
                refs.append({"session_key": m["session_key"], "channel": m["channel"]})

    db.save_pack(pack)
    db.mark_modules_used(pack["pack_id"], refs)
    return jsonify({"ok": True, "pack_id": pack["pack_id"]})


@app.get("/api/packs")
def api_packs_list():
    return jsonify(db.list_packs())


@app.delete("/api/packs/<pack_id>")
def api_packs_delete(pack_id):
    db.release_pack_modules(pack_id)
    return jsonify({"ok": True})


@app.post("/api/packs/<pack_id>/edit")
def api_packs_edit(pack_id):
    """Rename a saved pack and/or update its destination + notes after build."""
    data = request.get_json(force=True) or {}
    ok = db.update_pack_metadata(
        pack_id,
        pack_name=data.get("pack_name"),
        destination=data.get("destination"),
        notes=data.get("notes"),
    )
    if not ok:
        return jsonify({"error": "no such pack or no fields supplied"}), 404
    return jsonify({"ok": True})


# ----------------------- API: thresholds -----------------------

@app.get("/api/thresholds")
def api_thresholds():
    return jsonify(pairing.DEFAULT_THRESHOLDS)


@app.get("/api/cloud-status")
def api_cloud_status():
    """Return when the last cloud-backup happened and any pending changes."""
    import subprocess, os, time
    log_path = HERE.parent / "auto_push.log"
    last_push = None
    last_status = None
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()[-20:]
            for line in reversed(lines):
                if "Push complete." in line:
                    last_push = line.split("  ")[0].strip()
                    last_status = "ok"
                    break
                if "Push failed" in line:
                    last_push = line.split("  ")[0].strip()
                    last_status = "failed"
                    break
                if "No changes." in line:
                    last_push = line.split("  ")[0].strip()
                    last_status = "no-changes"
                    break
        except Exception:
            pass

    # check pending git changes
    repo = HERE.parent
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True, timeout=10
        )
        pending = [l for l in out.stdout.strip().split("\n") if l.strip()]
        pending_count = len(pending)
    except Exception:
        pending_count = -1

    return jsonify({
        "last_push_at":  last_push,
        "last_push_status": last_status,
        "pending_changes": pending_count,
        "scheduled_every": "15 minutes",
    })


@app.post("/api/cloud-status/sync-now")
def api_sync_now():
    """Trigger auto_push.ps1 immediately. Streams the result back."""
    import subprocess
    script = HERE.parent / "auto_push.ps1"
    if not script.exists():
        return jsonify({"error": "auto_push.ps1 not found"}), 500
    try:
        proc = subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=120
        )
        # Read the latest log lines to report what happened
        log_path = HERE.parent / "auto_push.log"
        tail = ""
        if log_path.exists():
            try:
                with open(log_path, encoding="utf-8") as f:
                    tail = "".join(f.readlines()[-6:])
            except Exception:
                pass
        return jsonify({
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "log_tail": tail,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "push took longer than 120s"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------- API: dashboard summary -----------------------

@app.get("/api/live")
def api_live():
    """Real-time view of the in-progress YRCARKIT session.
    Returns is_live=True if any DB in the latest session was modified
    within the last 5 minutes.
    """
    import time
    sessions = db.scan_sessions()
    if not sessions:
        return jsonify({"is_live": False, "session": None, "channels": []})

    latest = sessions[-1]
    label = db.get_session_label(latest["session_key"])
    skip = {3}
    if label:
        try:
            skip = set(json.loads(label["skip_channels"]))
        except Exception:
            skip = {3}

    # Compute channel→cell mapping for the live panel
    cell_map = {}
    if label:
        active_chs = sorted([c for c in latest["channels"] if c not in skip])
        cells = list(range(label["cell_start"], label["cell_end"] + 1))
        for ch, cid in zip(active_chs, cells):
            cell_map[ch] = cid

    channels_out = []
    most_recent_mtime = 0
    for ch in latest["channels"]:
        if ch in skip:
            continue
        fp = latest["channel_paths"][ch]
        live = db.read_live_state_for_channel(fp)
        if not live:
            continue
        most_recent_mtime = max(most_recent_mtime, live["file_mtime"])
        age_s = int(time.time() - live["file_mtime"])
        cycle_n = (live["current_seq"] + 1) // 2
        channels_out.append({
            "channel":             ch,
            "cell_label":          (f"{label['battery']}-{cell_map[ch]}" if (label and ch in cell_map) else None),
            "cell_position":       cell_map.get(ch),
            "current_table":       live["current_table"],
            "current_phase":       live["current_phase"],
            "current_cycle":       cycle_n,
            "completed_charge":    live["completed_charge_cycles"],
            "completed_discharge": live["completed_discharge_cycles"],
            "current_vol":         live["current_vol"],
            "current_cur":         live["current_cur"],
            "current_cap":         live["current_cap"],
            "elapsed_in_table_s":  live["elapsed_in_table_s"],
            "row_count":           live["row_count"],
            "is_resting":          (live.get("current_procedure") in (2, 4) or
                                    (live["current_cur"] is not None and abs(live["current_cur"]) < 0.1)),
            "age_s":               age_s,
        })

    is_live = (time.time() - most_recent_mtime) < 300 if most_recent_mtime else False
    return jsonify({
        "is_live":         is_live,
        "session_key":     latest["session_key"],
        "session_started": latest["started"],
        "battery_label":   label["battery"] if label else None,
        "channels":        channels_out,
    })


@app.get("/api/dashboard")
def api_dashboard():
    pool = db.build_module_pool()
    sessions = db.scan_sessions()
    packs = db.list_packs()

    by_status = {}
    for m in pool:
        s = m.get("status", "available")
        by_status[s] = by_status.get(s, 0) + 1

    by_trend = {}
    for m in pool:
        t = m.get("trend", "UNKNOWN")
        by_trend[t] = by_trend.get(t, 0) + 1

    latest_session = sessions[-1] if sessions else None
    latest_label = db.get_session_label(latest_session["session_key"]) if latest_session else None

    labelled = sum(1 for m in pool if m.get("battery") and m.get("cell_position"))
    by_battery = {}
    for m in pool:
        if m.get("battery"):
            by_battery[m["battery"]] = by_battery.get(m["battery"], 0) + 1

    return jsonify({
        "total_modules":    len(pool),
        "labelled_modules": labelled,
        "unlabelled_modules": len(pool) - labelled,
        "by_battery":       by_battery,
        "by_status":        by_status,
        "by_trend":         by_trend,
        "session_count":    len(sessions),
        "pack_count":       len(packs),
        "latest_session":   latest_session,
        "latest_label":     latest_label,
    })


# ----------------------- launcher -----------------------

def _open_browser():
    webbrowser.open("http://127.0.0.1:5000/")


if __name__ == "__main__":
    import os
    # Skip the browser-pop in headless mode (auto-start at logon, etc.)
    if not os.environ.get("BATTERY_UI_NO_BROWSER"):
        Timer(1.5, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
