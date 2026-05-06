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

from flask import Flask, jsonify, request, render_template, abort

# Allow running as script or module
HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from battery_ui import db, pairing  # noqa: E402

app = Flask(__name__,
            template_folder=str(HERE / "templates"),
            static_folder=str(HERE / "static"))


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


@app.post("/api/sessions/<session_key>/label")
def api_label_session(session_key):
    data = request.get_json(force=True)
    battery = (data.get("battery") or "").strip().upper()
    cell_start = int(data.get("cell_start"))
    cell_end = int(data.get("cell_end"))
    skip = data.get("skip_channels") or [3]
    notes = data.get("notes") or ""

    if not battery or not battery.isalpha():
        return jsonify({"error": "battery must be a letter A-Z"}), 400
    if cell_start < 1 or cell_end > 28 or cell_end < cell_start:
        return jsonify({"error": "cell range must be within 1-28 and ascending"}), 400

    db.save_session_label(session_key, battery, cell_start, cell_end, skip, notes)
    return jsonify({"ok": True})


# ----------------------- API: modules pool -----------------------

@app.get("/api/pool")
def api_pool():
    pool = db.build_module_pool()
    return jsonify(pool)


@app.post("/api/modules/override")
def api_module_override():
    data = request.get_json(force=True)
    sk = data.get("session_key")
    ch = int(data.get("channel"))
    db.save_module_override(
        sk, ch,
        battery=(data.get("battery") or None),
        cell_position=int(data["cell_position"]) if data.get("cell_position") not in (None, "") else None,
        status=data.get("status"),
        notes=data.get("notes"),
    )
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


# ----------------------- API: thresholds -----------------------

@app.get("/api/thresholds")
def api_thresholds():
    return jsonify(pairing.DEFAULT_THRESHOLDS)


# ----------------------- API: dashboard summary -----------------------

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

    return jsonify({
        "total_modules":    len(pool),
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
    Timer(1.5, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
