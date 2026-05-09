"""End-to-end verification of every UI tab and endpoint.
Run after server is up. Reports FAIL on any broken behavior.
This is a development/test script, not part of the app."""

import json, urllib.request, urllib.error

BASE = "http://127.0.0.1:5000"

def call(method, path, body=None):
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]

results = []
def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    results.append((mark, name, detail))
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))

print("=" * 70)
print("TAB 1 - DASHBOARD")
print("=" * 70)
s, d = call("GET", "/api/dashboard")
check("GET /api/dashboard 200", s == 200)
check("dashboard has total_modules", "total_modules" in d)
check("dashboard has by_status", "by_status" in d)
check("dashboard has by_trend", "by_trend" in d)
check("dashboard has session_count >= 31", d.get("session_count", 0) >= 31, f"got {d.get('session_count')}")
check("dashboard has latest_session", d.get("latest_session") is not None)

print()
print("=" * 70)
print("TAB 2 - SESSIONS")
print("=" * 70)
s, sessions = call("GET", "/api/sessions")
check("GET /api/sessions 200", s == 200)
check("at least 31 sessions returned", len(sessions) >= 31, f"got {len(sessions)}")
labelled = [x for x in sessions if x.get("label")]
check("at least 1 labelled", len(labelled) >= 1, f"{len(labelled)} labelled")
check("sessions have trend_dist", sessions[-1].get("trend_dist") is not None)
check("sessions have cap_range", sessions[-1].get("cap_range") is not None or sessions[-1]["channels"])

# Use a STABLE old session for label tests (not the latest, since the user
# may have a live session that we should not pollute).
sk_test = "20260324_2102"   # the very first session — safe to relabel
s, det = call("GET", f"/api/sessions/{sk_test}")
check("GET session detail 200", s == 200)
check("detail has channels list", isinstance(det.get("channels"), list))
check("each channel has trend", all("trend" in c for c in det["channels"]))
check("each channel has cap/IR/Vend", all("cap_ah" in c and "ir_mohm" in c and "v_end" in c for c in det["channels"]))

s, r = call("POST", f"/api/sessions/{sk_test}/label",
            {"battery": "Z", "cell_start": 22, "cell_end": 28, "skip_channels": [3]})
check("POST label returns ok", isinstance(r, dict) and r.get("ok") is True, str(r)[:60])

s, sessions2 = call("GET", "/api/sessions")
test_session = next(x for x in sessions2 if x["session_key"] == sk_test)
check("label persisted", test_session.get("label", {}).get("battery") == "Z")

s, r = call("POST", f"/api/sessions/{sk_test}/label",
            {"battery": "", "cell_start": 1, "cell_end": 7})
check("empty battery rejected", s == 400)
s, r = call("POST", f"/api/sessions/{sk_test}/label",
            {"battery": "X", "cell_start": 30, "cell_end": 40})
check("out-of-range cells rejected", s == 400)

# clean up — remove the test label entirely so the old session goes back to unlabelled
import sqlite3 as _s
from pathlib import Path as _P
_conn = _s.connect(_P(__file__).parent / "battery_ui.db")
_conn.execute("DELETE FROM session_labels WHERE session_key=?", (sk_test,))
_conn.commit(); _conn.close()

print()
print("=" * 70)
print("TAB 3 - MODULE POOL")
print("=" * 70)
s, pool = call("GET", "/api/pool")
check("GET /api/pool 200", s == 200)
check("at least 189 module entries", len(pool) >= 189, f"got {len(pool)}")
check("each has trend", all("trend" in m for m in pool))
check("each has discharge_caps", all("discharge_caps" in m for m in pool))
labelled_pool = [m for m in pool if m.get("battery")]
check("labelled modules show battery", len(labelled_pool) >= 7, f"{len(labelled_pool)} labelled in pool")
# Check that *any* labelled session has cell_position propagated (don't hard-code H specifically)
check("battery+cell propagated from session label",
      any(m.get("battery") and m.get("cell_position") for m in pool))

s, r = call("POST", "/api/modules/override",
            {"session_key": "20260504_1926", "channel": 1, "battery": "Q", "cell_position": 25})
check("POST module override ok", r.get("ok") is True)
s, pool2 = call("GET", "/api/pool")
qmod = next((m for m in pool2 if m["session_key"]=="20260504_1926" and m["channel"]==1), None)
check("override propagates to pool",
      qmod and qmod["battery"] == "Q" and qmod["cell_position"] == 25,
      f"{qmod['battery']}-{qmod['cell_position']}" if qmod else "missing")

call("POST", "/api/modules/override",
     {"session_key": "20260504_1926", "channel": 1, "battery": None, "cell_position": None})

s, r = call("POST", "/api/modules/bulk",
            {"refs": [{"session_key": "20260504_1926", "channel": 4},
                      {"session_key": "20260504_1926", "channel": 5}],
             "status": "weak"})
check("POST bulk ok", r.get("ok") is True and r.get("updated") == 2)
s, pool3 = call("GET", "/api/pool")
weak = [m for m in pool3 if m["session_key"]=="20260504_1926" and m["channel"] in (4,5) and m["status"]=="weak"]
check("bulk status applied", len(weak) == 2)
call("POST", "/api/modules/bulk",
     {"refs": [{"session_key": "20260504_1926", "channel": 4},
               {"session_key": "20260504_1926", "channel": 5}],
      "status": "available"})

s, det = call("GET", "/api/modules/20260504_1926/6")
check("GET module detail 200", s == 200)
check("detail has 10 cycles", len(det["cycles"]) == 10, f"got {len(det['cycles'])}")
check("detail has target", det.get("target") is not None)
check("detail trend valid", det.get("trend") in ("IMPROVING","STABLE","PLATEAU","DECLINING","DEAD","UNKNOWN"))
check("detail has battery from label", det.get("battery") == "H")
check("detail has cell_position",
      det.get("cell_position") is not None,
      f"got {det.get('cell_position')}")

print()
print("=" * 70)
print("TAB 4 - BUILD PACK")
print("=" * 70)
s, p = call("POST", "/api/packs/preview",
            {"target_battery": "ANY", "strategy": "pair_opposites",
             "target_blocks": 7, "cap_floor_reuse": 2.5,
             "ir_ceiling_module": 30, "max_pack_cap_spread": 0.7,
             "max_pack_ir_spread": 10})
check("POST preview 200", s == 200)
check("preview has grade", p.get("grade") in "ABCDEF")
check("preview has predicted_life", "predicted_life" in p)
check("preview has 7 blocks", len(p.get("block_layout", [])) == 7)
check("preview has rejected_modules",
      isinstance(p.get("rejected_modules"), list),
      f"{len(p.get('rejected_modules', []))} rejected")
check("preview has swap_suggestions", isinstance(p.get("swap_suggestions"), list))
check("preview has candidate_summary", "candidate_summary" in p)

s, p2 = call("POST", "/api/packs/preview",
             {"target_battery": "ANY", "strategy": "pair_opposites",
              "target_blocks": 14, "cap_floor_reuse": 5.0,
              "ir_ceiling_module": 15})
check("impossible build returns error", "error" in p2,
      p2.get("error", "")[:60])
check("error response includes rejected_modules",
      isinstance(p2.get("rejected_modules"), list))

s, p3 = call("POST", "/api/packs/preview",
             {"target_battery": "ANY", "strategy": "capacity_only",
              "target_blocks": 7, "cap_floor_reuse": 2.5,
              "ir_ceiling_module": 30})
check("capacity_only strategy works", p3.get("grade") in "ABCDEF")
check("capacity_only produces blocks", len(p3.get("block_layout", [])) == 7)

s, comp = call("POST", "/api/packs/compare",
               {"target_battery": "ANY", "target_blocks": 7,
                "cap_floor_reuse": 2.5, "ir_ceiling_module": 30})
check("POST compare 200", s == 200)
check("compare has all 3 strategies",
      all(k in comp for k in ("pair_opposites","match_similar","capacity_only")))

s, p_named = call("POST", "/api/packs/preview",
            {"target_battery": "ANY", "strategy": "pair_opposites",
             "target_blocks": 7, "cap_floor_reuse": 2.5,
             "ir_ceiling_module": 30,
             "pack_name": "Verify-Test-Pack",
             "destination": "Verify dest"})
check("preview accepts pack_name + destination", p_named.get("pack_name") == "Verify-Test-Pack")
check("preview computes source_summary", isinstance(p_named.get("source_summary"), str) and p_named["source_summary"])
check("preview includes source_counts dict", isinstance(p_named.get("source_counts"), dict))

s, save = call("POST", "/api/packs/save", p_named)
check("POST save returns ok", save.get("ok") is True)
pack_id = save.get("pack_id")
check("save returns pack_id", pack_id is not None)

s, dash = call("GET", "/api/dashboard")
check("modules now show as 'used'", dash["by_status"].get("used", 0) >= 14)

print()
print("=" * 70)
print("TAB 5 - PACK HISTORY")
print("=" * 70)
s, packs = call("GET", "/api/packs")
check("GET /api/packs 200", s == 200)
check("at least 1 pack in history", len(packs) >= 1)
saved = next((x for x in packs if x["pack_id"] == pack_id), None)
check("saved pack is there", saved is not None)
if saved:
    check("pack has block_layout", isinstance(saved.get("block_layout"), list))
    check("pack has grade", saved.get("grade") in "ABCDEF")
    check("pack has predicted_life", "predicted_life" in saved)
    check("pack has stats", all(k in saved for k in
          ("avg_cap","cap_spread","weakest_cap","avg_ir","ir_spread")))
    check("pack has pack_name persisted", saved.get("pack_name") == "Verify-Test-Pack",
          f"got {saved.get('pack_name')}")
    check("pack has source_summary persisted", bool(saved.get("source_summary")),
          f"got {saved.get('source_summary')}")
    check("pack has destination persisted", saved.get("destination") == "Verify dest")

# rename via /edit endpoint
s, r = call("POST", f"/api/packs/{pack_id}/edit",
            {"pack_name": "Renamed-Pack", "destination": "New dest", "notes": "n1"})
check("POST pack edit returns ok", r.get("ok") is True)
s, packs2 = call("GET", "/api/packs")
saved2 = next((x for x in packs2 if x["pack_id"] == pack_id), None)
check("rename took effect", saved2 and saved2.get("pack_name") == "Renamed-Pack",
      f"got {saved2.get('pack_name') if saved2 else None}")
check("destination edit took effect", saved2 and saved2.get("destination") == "New dest")
check("notes edit took effect", saved2 and saved2.get("notes") == "n1")

# edit non-existent pack -> 404
s, r = call("POST", "/api/packs/NOSUCH/edit", {"pack_name": "x"})
check("edit on bogus pack returns 404", s == 404)

s, r = call("DELETE", f"/api/packs/{pack_id}")
check("DELETE pack returns ok", r.get("ok") is True)
s, dash2 = call("GET", "/api/dashboard")
check("modules released back to pool",
      dash2["by_status"].get("used", 0) < dash["by_status"].get("used", 99))

print()
print("=" * 70)
print("CROSS-TAB / EDGE CASES")
print("=" * 70)
s, _ = call("GET", "/api/thresholds")
check("GET /api/thresholds works", s == 200)

# live endpoint
s, live = call("GET", "/api/live")
check("GET /api/live 200", s == 200)
check("live has is_live bool", isinstance(live.get("is_live"), bool))
check("live has session_key", "session_key" in live)
check("live has channels list", isinstance(live.get("channels"), list))
if live.get("channels"):
    c0 = live["channels"][0]
    check("live channel has phase", c0.get("current_phase") in ("CHARGE","DISCHARGE"))
    check("live channel has voltage", c0.get("current_vol") is not None)
    check("live channel has cap-so-far", "current_cap" in c0)
    check("live channel has age_s", isinstance(c0.get("age_s"), int))
s, _ = call("GET", "/api/sessions/NOSUCH")
check("404 on bad session key", s == 404)
s, _ = call("GET", "/api/modules/NOSUCH/1")
check("404 on bad module path", s == 404)
s, _ = call("GET", "/api/modules/20260504_1926/99")
check("404 on bad channel", s == 404)

with urllib.request.urlopen(f"{BASE}/") as r:
    html = r.read().decode()
check("index.html serves", r.status == 200)
check("html has all 5 tab buttons",
      all(t in html for t in ("dashboard","sessions","pool","build","history")))
check("html includes module-modal", "module-modal" in html)
check("html includes cutoff banner", "cutoff-banner" in html)
check("html includes unlabelled banner", "unlabelled-banner" in html)
check("html includes bulk-bar", "bulk-bar" in html)
check("html includes compare button", "compare-strategies-btn" in html)

for f in ("/static/app.js", "/static/style.css"):
    with urllib.request.urlopen(f"{BASE}{f}") as r:
        check(f"{f} serves", r.status == 200)

# JS sanity — check our new symbols exist in the served file
with urllib.request.urlopen(f"{BASE}/static/app.js") as r:
    js = r.read().decode()
for sym in ("openModuleDetail", "editPoolLabel", "bulkSetStatus",
            "renderStrategyCompare", "showCutoffReminder", "showUnlabelledBanner",
            "pollForUpdates", "cell-tag",
            "renamePack", "viewPackBlocks", "pack_name", "source_summary",
            "loadLive", "live-card", "live-dot",
            "TREND_TIPS", "trendBadge", "data-tip"):
    check(f"app.js contains {sym!r}", sym in js)
# Confirm tooltip text actually shipped
check("IMPROVING tooltip text shipped", "reconditioning worked" in js)
check("PLATEAU tooltip text shipped",   "Done conditioning" in js)
check("DEAD tooltip text shipped",      "Failed module" in js)

check("Build form has pack_name input", 'name="pack_name"' in html)
check("HTML rebrand to Ratan's", "Ratan" in html)
check("HTML has live-panel", "live-panel" in html)

print()
print("=" * 70)
fails = [r for r in results if r[0] == "FAIL"]
total = len(results)
print(f"SUMMARY: {total - len(fails)}/{total} checks passed")
if fails:
    print("\nFAILURES:")
    for mark, name, detail in fails:
        print(f"  {mark}  {name}  ({detail})")
else:
    print("\nALL CHECKS PASSED")
