"""One-off audit of Battery H pool — can it build a full Prius pack?"""
import sys
sys.path.insert(0, '.')
from battery_ui import db, pairing

pool = db.build_module_pool()
h_mods = [m for m in pool if m.get("battery") == "H"]

completed = [m for m in h_mods if m.get("trend") != "UNKNOWN" and m.get("cap_ah") is not None]
inprog    = [m for m in h_mods if m.get("trend") == "UNKNOWN"]
dead      = [m for m in completed if m.get("cap_ah", 0) < 0.5 or m.get("trend") == "DEAD"]
weak      = [m for m in completed if 0.5 <= m.get("cap_ah", 0) < 2.0 and m not in dead]
ok        = [m for m in completed if m.get("cap_ah", 0) >= 2.0 and m not in dead]

def names(ms):
    return [f"H-{m['cell_position']}" for m in ms]
def labelled(ms):
    return [f"H-{m['cell_position']} ({m['cap_ah']})" for m in ms]

print("=== Battery H module status ===")
print(f"  Total H modules:       {len(h_mods)}")
print(f"  Completed cycling:     {len(completed)}")
print(f"  Still in progress:     {len(inprog)} (H-22 to H-28, May 7 session)")
print(f"  DEAD/scrap (cap<0.5):  {len(dead)}    {names(dead)}")
print(f"  Weak (cap 0.5-2.0):    {len(weak)}    {labelled(weak)}")
print(f"  Reusable (cap>=2.0):   {len(ok)}")
print()

print("=== Reusable modules sorted by cap (descending) ===")
for m in sorted(ok, key=lambda x: -x["cap_ah"]):
    print(f"  H-{m['cell_position']:<3} cap={m['cap_ah']:.2f}  IR={m['ir_mohm'] or 0:.1f}  trend={m['trend']}")

print()
print("=== Pack-building from H only ===")
def attempt(target_blocks, cap_floor, ir_ceil, label):
    th = {**pairing.DEFAULT_THRESHOLDS,
          "cap_floor_reuse": cap_floor,
          "ir_ceiling_module": ir_ceil,
          "max_pack_cap_spread": 5.0,  # don't fail on spread for this audit
          "max_pack_ir_spread": 50.0}
    p = pairing.build_pack(h_mods, target_blocks=target_blocks,
                           strategy="pair_opposites", thresholds=th)
    print(f"\n--- {label} ---")
    if "error" in p:
        print(f"  Cannot build: {p['error']}")
    else:
        print(f"  Grade: {p['grade']}  {p['grade_name']}")
        print(f"  Predicted life: {p['predicted_life']}")
        print(f"  Avg cap: {p['avg_cap']}  spread: {p['cap_spread']}  weakest: {p['weakest_cap']}")

attempt(14, 2.5, 30, "Full pack (14 blocks/28 mods), strict cap>=2.5")
attempt(14, 2.0, 30, "Full pack, lenient cap>=2.0")
attempt(7,  2.5, 30, "Half pack (7 blocks/14 mods), strict cap>=2.5")
attempt(7,  2.0, 30, "Half pack, lenient cap>=2.0")
