"""
Pairing, trend, and lifespan grading.

All thresholds are calibrated for the YRCARKIT cycler test recipe
(1.5 A discharge, 6.4 V cutoff). Updateable from the UI.
"""

from datetime import datetime
from statistics import mean, stdev


# ---------- DEFAULT THRESHOLDS ----------
# Tightened up after the verification pass. User can override per build.

DEFAULT_THRESHOLDS = {
    "cap_floor_reuse":      3.0,   # Ah  — modules below this are not eligible
    "cap_ideal":            4.0,   # Ah  — preferred lower bound for "Good" tier
    "ir_ceiling_module":    25.0,  # mΩ DC, per-module
    "max_pack_cap_spread":  0.5,   # Ah  — block-pair averages must be tighter than this
    "max_pack_ir_spread":   5.0,   # mΩ
    "require_labelled":     1.0,   # >0 = require battery+cell label; 0 = allow unlabelled
}


# ---------- TREND CLASSIFICATION ----------

def classify_trend(discharge_caps):
    """Given the per-cycle discharge cap series (oldest first), return a label.
    IMPROVING / STABLE / PLATEAU / DECLINING / DEAD / UNKNOWN

    A module needs at least 2 completed discharge cycles to be classified —
    a fresh in-progress session shouldn't be labelled DEAD just because the
    first cycle is partway done.
    """
    if not discharge_caps:
        return "UNKNOWN"
    if len(discharge_caps) < 2:
        # In-progress / incomplete — don't pre-judge
        return "UNKNOWN"
    peak = max(discharge_caps)
    if peak < 0.3:
        return "DEAD"

    first, last = discharge_caps[0], discharge_caps[-1]
    pct_change = (last - first) / first * 100 if first > 0 else 0
    pct_fade   = (last - peak) / peak * 100 if peak > 0 else 0

    if pct_change >= 5 and last >= 0.5:
        return "IMPROVING"
    if pct_fade <= -8:
        return "DECLINING"
    if -5 < pct_change < 5 and -5 < pct_fade <= 0:
        return "STABLE"
    if pct_fade <= -5:
        return "PLATEAU"
    return "STABLE"


def verify_pair(a, b, pack_avg_cap):
    """Run industry-standard per-pair verification checks on a block (pair of modules).
    Returns list of check dicts with status (pass/warn/fail), label, value, threshold,
    and source citation. Used to give the user confidence before assembly.

    Checks calibrated from PriusChat threads (151459, 239581, 256955, 221864),
    Hybrid Automotive Prolong docs, the NREL Thermal Evaluation paper, and the
    Toyota service manual (P112 Hybrid Battery Control).
    """
    checks = []
    if not a or not b:
        return [{"status": "fail", "label": "Pair complete", "detail": "Missing module(s) in pair", "source": "—"}]

    cap_a, cap_b = a.get("cap_ah") or 0, b.get("cap_ah") or 0
    ir_a, ir_b   = a.get("ir_mohm") or 0, b.get("ir_mohm") or 0
    ven_a, ven_b = a.get("v_end") or 0, b.get("v_end") or 0
    trend_a, trend_b = a.get("trend"), b.get("trend")

    # 1. IR delta within pair
    ir_delta = abs(ir_a - ir_b)
    if ir_delta <= 4:
        checks.append({"status": "pass", "label": "IR delta (within pair)",
                       "detail": f"{ir_delta:.1f} mΩ — well-matched (target ≤4)",
                       "source": "PriusChat #221864"})
    elif ir_delta <= 8:
        checks.append({"status": "warn", "label": "IR delta (within pair)",
                       "detail": f"{ir_delta:.1f} mΩ — acceptable but not tight (target ≤4, warn ≤8)",
                       "source": "PriusChat #221864"})
    else:
        checks.append({"status": "fail", "label": "IR delta (within pair)",
                       "detail": f"{ir_delta:.1f} mΩ — concerning (>8 mΩ — different load behavior)",
                       "source": "PriusChat #221864"})

    # 2. IR absolute ceiling per module
    max_ir = max(ir_a, ir_b)
    if max_ir <= 22:
        checks.append({"status": "pass", "label": "IR absolute (each module)",
                       "detail": f"max {max_ir:.1f} mΩ — both healthy (Dr. Prius warn at 30)",
                       "source": "Dr. Prius app docs"})
    elif max_ir <= 25:
        checks.append({"status": "warn", "label": "IR absolute (each module)",
                       "detail": f"max {max_ir:.1f} mΩ — borderline; one module is degrading",
                       "source": "Dr. Prius app docs"})
    else:
        checks.append({"status": "fail", "label": "IR absolute (each module)",
                       "detail": f"max {max_ir:.1f} mΩ — exceeds healthy ceiling (Dr. Prius warns at 30)",
                       "source": "Dr. Prius app docs"})

    # 3. End-of-discharge voltage delta within pair
    ven_delta = abs(ven_a - ven_b)
    if ven_delta <= 0.05:
        checks.append({"status": "pass", "label": "Vend delta (within pair)",
                       "detail": f"{ven_delta*1000:.0f} mV — tight match",
                       "source": "wrouesnel rebuild guide"})
    elif ven_delta <= 0.10:
        checks.append({"status": "warn", "label": "Vend delta (within pair)",
                       "detail": f"{ven_delta*1000:.0f} mV — acceptable; modules cycle slightly differently",
                       "source": "wrouesnel rebuild guide"})
    else:
        checks.append({"status": "fail", "label": "Vend delta (within pair)",
                       "detail": f"{ven_delta*1000:.0f} mV — concern; one module sags faster (target ≤50)",
                       "source": "wrouesnel rebuild guide"})

    # 4. Block sum within +/-5% of pack mean (THE P0A80 prevention check)
    block_sum = cap_a + cap_b
    pack_block_mean = pack_avg_cap * 2
    pct_diff = abs(block_sum - pack_block_mean) / pack_block_mean * 100 if pack_block_mean else 0
    if pct_diff <= 3:
        checks.append({"status": "pass", "label": "Block uniformity (vs pack mean)",
                       "detail": f"block sum {block_sum:.2f} Ah, {pct_diff:.1f}% off pack mean — excellent",
                       "source": "PriusChat #239581 (P0A80 prevention)"})
    elif pct_diff <= 5:
        checks.append({"status": "pass", "label": "Block uniformity (vs pack mean)",
                       "detail": f"block sum {block_sum:.2f} Ah, {pct_diff:.1f}% off pack mean — within ±5%",
                       "source": "PriusChat #239581 (P0A80 prevention)"})
    elif pct_diff <= 8:
        checks.append({"status": "warn", "label": "Block uniformity (vs pack mean)",
                       "detail": f"block sum {block_sum:.2f} Ah, {pct_diff:.1f}% off pack mean (target ≤5%)",
                       "source": "PriusChat #239581 (P0A80 prevention)"})
    else:
        checks.append({"status": "fail", "label": "Block uniformity (vs pack mean)",
                       "detail": f"block sum {block_sum:.2f} Ah, {pct_diff:.1f}% off pack mean — will trigger P0A80",
                       "source": "PriusChat #239581 (P0A80 prevention)"})

    # 5. Trend compatibility: avoid pairing DECLINING with healthy
    if trend_a == "DECLINING" and trend_b == "DECLINING":
        checks.append({"status": "fail", "label": "Trend compatibility",
                       "detail": "Both modules DECLINING — block will fail in months",
                       "source": "PriusChat #151459"})
    elif "DECLINING" in (trend_a, trend_b):
        weak = "A" if trend_a == "DECLINING" else "B"
        checks.append({"status": "warn", "label": "Trend compatibility",
                       "detail": f"Module {weak} is DECLINING — pair will degrade fast; flag for retest in 30 days",
                       "source": "PriusChat #151459"})
    elif trend_a in ("DEAD", "UNKNOWN") or trend_b in ("DEAD", "UNKNOWN"):
        checks.append({"status": "fail", "label": "Trend compatibility",
                       "detail": "One module DEAD/UNKNOWN — re-test or replace before assembly",
                       "source": "PriusChat #151459"})
    else:
        checks.append({"status": "pass", "label": "Trend compatibility",
                       "detail": f"both {trend_a}/{trend_b} — healthy pair",
                       "source": "PriusChat #151459"})

    return checks


def grade_module(m):
    """Score a single module A-F based on cap + IR + trend.
    Returns (letter, short_reason). Used to color-code modules in the Pool."""
    cap = m.get("cap_ah") or 0
    ir = m.get("ir_mohm")
    if ir is None: ir = 999
    trend = m.get("trend", "UNKNOWN")

    # Hard rejects first
    if trend == "DEAD" or cap < 1.0:
        return "F", "DEAD - scrap"
    if cap < 2.0:
        return "F", f"cap {cap:.2f} below 2.0 Ah floor"
    if ir > 35:
        return "F", f"IR {ir:.1f} too high"

    # A tier — strong candidates
    if cap >= 4.0 and ir <= 22 and trend not in ("DECLINING",):
        return "A", "Excellent — pack-grade"
    # B tier — good
    if cap >= 3.0 and ir <= 25 and trend not in ("DECLINING", "DEAD"):
        return "B", "Good — usable"
    # C tier — acceptable
    if cap >= 2.5 and ir <= 30:
        return "C", "Acceptable — use if needed"
    # D tier — marginal
    if cap >= 2.0:
        return "D", "Marginal — last resort"
    return "F", "Below all thresholds"


GRADE_TIPS = {
    "A": "Excellent — pack-grade module, top choice for any pack",
    "B": "Good — solid pack candidate, use freely",
    "C": "Acceptable — use when stronger modules unavailable",
    "D": "Marginal — last resort, will reduce pack lifespan",
    "F": "Reject — too weak/IR-high, do not use in pack",
}


TREND_DESCRIPTION = {
    "IMPROVING":  "Cap rose ≥5% across cycles — real reconditioning, this is a healthy module.",
    "STABLE":     "Flat across cycles — already at its ceiling, this is the true number.",
    "PLATEAU":    "Peaked early then mild fade — done conditioning.",
    "DECLINING":  "Peaked then fell ≥8% — over-cycled or end-of-life. Retest with fewer cycles.",
    "DEAD":       "Peak cap below 0.3 Ah — module is failed. Scrap.",
    "UNKNOWN":    "Not enough cycle data to classify.",
}


# ---------- PAIRING ALGORITHMS ----------

def _eligible(modules, thresholds):
    """Filter modules to those eligible for pack-building."""
    eligible, _ = _eligible_with_rejects(modules, thresholds)
    return eligible


def _eligible_with_rejects(modules, thresholds):
    """Same as _eligible but also returns rejected modules with reasons."""
    floor = thresholds["cap_floor_reuse"]
    ceil  = thresholds["ir_ceiling_module"]
    require_labelled = thresholds.get("require_labelled", 1.0) > 0
    eligible, rejected = [], []
    for m in modules:
        reasons = []
        if m.get("status") != "available":
            reasons.append(f"status={m.get('status')}")
        if require_labelled and not (m.get("battery") and m.get("cell_position")):
            reasons.append("unlabelled (no battery/cell — can't trust identity)")
        if m.get("session_type") == "testing":
            reasons.append("testing/set-aside session (not for pack-building)")
        if m.get("cap_ah") is None:
            reasons.append("no cap data")
        elif m["cap_ah"] < floor:
            reasons.append(f"cap {m['cap_ah']:.2f} < {floor} Ah floor")
        if m.get("ir_mohm") is None:
            reasons.append("no IR data")
        elif m["ir_mohm"] > ceil:
            reasons.append(f"IR {m['ir_mohm']:.1f} > {ceil} mΩ ceiling")
        if m.get("trend") == "DEAD":
            reasons.append("trend=DEAD")
        if m.get("trend") == "UNKNOWN":
            reasons.append("trend=UNKNOWN (incomplete cycles)")
        if reasons:
            rejected.append({**m, "reject_reasons": reasons})
        else:
            eligible.append(m)
    return eligible, rejected


def pair_opposites(modules, target_blocks=14, thresholds=None):
    """Sort by cap descending, pair strongest with weakest into blocks."""
    th = thresholds or DEFAULT_THRESHOLDS
    pool = _eligible(modules, th)
    needed = target_blocks * 2
    if len(pool) < needed:
        return None, f"Need {needed} eligible modules, have {len(pool)}"

    # Take the best `needed` modules (top by cap), then pair-opposites within them
    pool.sort(key=lambda m: -m["cap_ah"])
    picked = pool[:needed]
    picked.sort(key=lambda m: -m["cap_ah"])

    blocks = []
    i, j = 0, len(picked) - 1
    n = 1
    while i < j:
        a, b = picked[i], picked[j]
        blocks.append({
            "block_number": n, "a": a, "b": b,
            "block_cap": round((a["cap_ah"] + b["cap_ah"]) / 2, 3),
            "block_ir":  round(((a["ir_mohm"] or 0) + (b["ir_mohm"] or 0)) / 2, 1),
            "cap_gap":   round(abs(a["cap_ah"] - b["cap_ah"]), 3),
        })
        i += 1
        j -= 1
        n += 1
    return blocks, None


def match_similar(modules, target_blocks=14, thresholds=None):
    """Sort by cap descending, take consecutive pairs (strongest+strongest, etc)."""
    th = thresholds or DEFAULT_THRESHOLDS
    pool = _eligible(modules, th)
    needed = target_blocks * 2
    if len(pool) < needed:
        return None, f"Need {needed} eligible modules, have {len(pool)}"

    pool.sort(key=lambda m: -m["cap_ah"])
    picked = pool[:needed]

    blocks = []
    for n in range(target_blocks):
        a, b = picked[n * 2], picked[n * 2 + 1]
        blocks.append({
            "block_number": n + 1, "a": a, "b": b,
            "block_cap": round((a["cap_ah"] + b["cap_ah"]) / 2, 3),
            "block_ir":  round(((a["ir_mohm"] or 0) + (b["ir_mohm"] or 0)) / 2, 1),
            "cap_gap":   round(abs(a["cap_ah"] - b["cap_ah"]), 3),
        })
    return blocks, None


def capacity_only(modules, target_blocks=14, thresholds=None):
    """Simplest possible: take the top-N by capacity, pair them in adjacent order
    (1 with 2, 3 with 4, ...). No optimization, just rank-and-take."""
    th = thresholds or DEFAULT_THRESHOLDS
    pool = _eligible(modules, th)
    needed = target_blocks * 2
    if len(pool) < needed:
        return None, f"Need {needed} eligible modules, have {len(pool)}"
    pool.sort(key=lambda m: -m["cap_ah"])
    picked = pool[:needed]
    # arbitrary pairing: index 0 with -1, 1 with -2, ... (this is identical to
    # pair_opposites within the picked set, but we keep it simple here:
    # adjacent pairs in cap-sorted order = strongest pairs first, then weaker)
    blocks = []
    for n in range(target_blocks):
        a, b = picked[n * 2], picked[n * 2 + 1]
        blocks.append({
            "block_number": n + 1, "a": a, "b": b,
            "block_cap": round((a["cap_ah"] + b["cap_ah"]) / 2, 3),
            "block_ir":  round(((a["ir_mohm"] or 0) + (b["ir_mohm"] or 0)) / 2, 1),
            "cap_gap":   round(abs(a["cap_ah"] - b["cap_ah"]), 3),
        })
    return blocks, None


def apply_thermal_placement(blocks):
    """Reorder block positions: weakest pairs to the cool outer ends (1, 14),
    strongest pairs to the hot middle (7-8). Returns blocks with their
    'position' field set 1..N.
    """
    if not blocks:
        return blocks
    # sort by block_cap ascending (weakest first)
    by_strength = sorted(blocks, key=lambda b: b["block_cap"])
    n = len(by_strength)
    placed = [None] * n

    # weakest block -> position 1, next-weakest -> position n
    # alternate from the ends inward
    left, right = 0, n - 1
    weak_idx = 0
    flip = True
    while left <= right and weak_idx < n:
        if flip:
            placed[left] = by_strength[weak_idx]
            left += 1
        else:
            placed[right] = by_strength[weak_idx]
            right -= 1
        flip = not flip
        weak_idx += 1

    # renumber positions in physical order
    for i, b in enumerate(placed):
        b["block_number"] = i + 1
    return placed


# ---------- LIFESPAN GRADING ----------

GRADE_TIERS = [
    ("A", "Excellent",  4.5, 0.3, 20.0, 0, "18-36 months"),
    ("B", "Good",       4.0, 0.4, 22.0, 1, "12-18 months"),
    ("C", "Acceptable", 3.5, 0.5, 25.0, 2, "6-12 months"),
    ("D", "Marginal",   3.0, 0.7, 30.0, 99,"3-6 months"),
]


def grade_pack(blocks):
    """Given a list of block dicts (each with 'a' and 'b' module dicts), produce
    grade letter, descriptive name, predicted life, and stats.
    """
    all_modules = []
    for b in blocks:
        for pos in ("a", "b"):
            m = b.get(pos)
            if m:
                all_modules.append(m)
    caps = [m["cap_ah"] for m in all_modules if m.get("cap_ah") is not None]
    irs  = [m["ir_mohm"] for m in all_modules if m.get("ir_mohm") is not None]
    if not caps:
        return {
            "grade": "F", "grade_name": "Don't ship", "predicted_life": "—",
            "avg_cap": 0, "cap_spread": 0, "weakest_cap": 0,
            "avg_ir": 0, "ir_spread": 0, "issue_count": 0,
            "reasons": ["No usable modules"],
        }

    weakest_cap = min(caps)
    cap_spread  = max(caps) - min(caps)
    avg_cap     = round(mean(caps), 3)
    avg_ir      = round(mean(irs), 1) if irs else 0
    ir_spread   = round(max(irs) - min(irs), 1) if irs else 0
    max_ir      = max(irs) if irs else 0
    plateau_ct  = sum(1 for m in all_modules if m.get("trend") == "PLATEAU")
    decline_ct  = sum(1 for m in all_modules if m.get("trend") == "DECLINING")
    dead_ct     = sum(1 for m in all_modules if m.get("trend") == "DEAD")

    reasons = []
    if decline_ct > 0:
        reasons.append(f"{decline_ct} DECLINING module(s) — will fail fast")
    if dead_ct > 0:
        reasons.append(f"{dead_ct} DEAD module(s) — should not be in any pack")

    if weakest_cap < 3.0 or cap_spread > 0.7 or decline_ct > 0 or dead_ct > 0:
        return {
            "grade": "F", "grade_name": "Don't ship",
            "predicted_life": "Weeks before P0A80",
            "avg_cap": avg_cap, "cap_spread": round(cap_spread, 3),
            "weakest_cap": round(weakest_cap, 3),
            "avg_ir": avg_ir, "ir_spread": ir_spread,
            "issue_count": plateau_ct + decline_ct + dead_ct,
            "reasons": reasons or [f"weakest module {weakest_cap:.2f} Ah / spread {cap_spread:.2f} Ah"],
        }

    for letter, name, cap_floor, max_spread, ir_max, plateau_max, life in GRADE_TIERS:
        if (weakest_cap >= cap_floor and cap_spread <= max_spread
                and max_ir <= ir_max and plateau_ct <= plateau_max):
            return {
                "grade": letter, "grade_name": name,
                "predicted_life": life,
                "avg_cap": avg_cap, "cap_spread": round(cap_spread, 3),
                "weakest_cap": round(weakest_cap, 3),
                "avg_ir": avg_ir, "ir_spread": ir_spread,
                "issue_count": plateau_ct + decline_ct,
                "reasons": [],
            }

    # falls below D thresholds
    return {
        "grade": "F", "grade_name": "Don't ship",
        "predicted_life": "Weeks before P0A80",
        "avg_cap": avg_cap, "cap_spread": round(cap_spread, 3),
        "weakest_cap": round(weakest_cap, 3),
        "avg_ir": avg_ir, "ir_spread": ir_spread,
        "issue_count": plateau_ct + decline_ct,
        "reasons": [f"below D-tier thresholds (weakest {weakest_cap:.2f} Ah)"],
    }


# ---------- TOP-LEVEL BUILD ----------

def build_pack(modules, target_blocks=14, strategy="pair_opposites",
               thermal_placement=True, thresholds=None,
               destination="", notes="", pack_name=""):
    """Top-level pack builder. Returns a fully-formed pack dict ready to save."""
    th = thresholds or DEFAULT_THRESHOLDS

    if strategy == "match_similar":
        blocks, err = match_similar(modules, target_blocks, th)
    elif strategy == "capacity_only":
        blocks, err = capacity_only(modules, target_blocks, th)
    else:
        blocks, err = pair_opposites(modules, target_blocks, th)
    if err:
        # also include rejected modules in the error response so the user can see why
        eligible_now, rejected = _eligible_with_rejects(modules, th)
        suggestions = _suggest_threshold_relaxation(modules, target_blocks, th)
        return {
            "error": err,
            "eligible_now": len(eligible_now),
            "needed": target_blocks * 2,
            "rejected_modules": [_strip_module(r) | {"reject_reasons": r["reject_reasons"]} for r in rejected],
            "threshold_suggestions": suggestions,
        }

    if thermal_placement:
        blocks = apply_thermal_placement(blocks)

    grade_info = grade_pack(blocks)
    swap_suggestions = suggest_swaps(blocks, modules, th)

    # Compute pack avg cap for block-uniformity checks
    all_caps = []
    for b in blocks:
        for pos in ("a", "b"):
            m = b.get(pos)
            if m and m.get("cap_ah") is not None:
                all_caps.append(m["cap_ah"])
    pack_avg_cap = sum(all_caps) / len(all_caps) if all_caps else 0

    # normalize block_layout to JSON-safe dicts AND run per-block verification
    layout = []
    for b in blocks:
        a_full, b_full = b.get("a"), b.get("b")
        verifications = verify_pair(a_full, b_full, pack_avg_cap)
        # block-level overall verdict
        if any(v["status"] == "fail" for v in verifications):
            block_verdict = "fail"
        elif any(v["status"] == "warn" for v in verifications):
            block_verdict = "warn"
        else:
            block_verdict = "pass"
        layout.append({
            "block_number": b["block_number"],
            "a": _strip_module(a_full),
            "b": _strip_module(b_full),
            "block_cap": b["block_cap"],
            "block_ir":  b["block_ir"],
            "cap_gap":   b["cap_gap"],
            "verifications": verifications,
            "verdict":     block_verdict,
        })

    # full pool rejection report
    _, rejected = _eligible_with_rejects(modules, th)

    # Source-battery breakdown — count modules per battery letter in the final pack
    src_counts = {}
    for b in layout:
        for pos in ("a", "b"):
            m = b.get(pos)
            if m:
                key = m.get("battery") or "(unlabelled)"
                src_counts[key] = src_counts.get(key, 0) + 1
    # Sort by count descending so the dominant source comes first
    src_summary = " + ".join(f"{k} ({v})" for k, v in sorted(src_counts.items(), key=lambda x: -x[1]))

    # pack-level verification summary
    pass_blocks = sum(1 for b in layout if b["verdict"] == "pass")
    warn_blocks = sum(1 for b in layout if b["verdict"] == "warn")
    fail_blocks = sum(1 for b in layout if b["verdict"] == "fail")
    pre_install_checklist = [
        {"label": "Module rest voltage ≥ 7.7 V each", "ack": False, "source": "Toyota service spec"},
        {"label": "No corrosion / electrolyte residue at terminals", "ack": False, "source": "Hybrid Battery Repair SD"},
        {"label": "No case swelling or vent damage", "ack": False, "source": "Toyota service spec"},
        {"label": "Polarity orientation alternates +/− per pack diagram", "ack": False, "source": "wrouesnel guide"},
        {"label": "Busbar contact faces clean copper, Noalox applied", "ack": False, "source": "wrouesnel guide"},
        {"label": "Busbar nuts torqued to 48 in-lb (5.4 N·m) in sequence", "ack": False, "source": "Toyota service torque spec"},
        {"label": "Module mounting bolts torqued to 84 in-lb (9.5 N·m)", "ack": False, "source": "Toyota service torque spec"},
        {"label": "Cooling fan and vents cleaned", "ack": False, "source": "Toyota TSB T-SB-0098-12"},
        {"label": "(Gen 3 only) Battery ECU 'smart unit' inspected for corrosion", "ack": False, "source": "Art's Automotive Gen-3 article"},
        {"label": "Service plug installed last, after 12 V reconnection", "ack": False, "source": "Toyota repair manual"},
    ]

    pack_id = f"PACK-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return {
        "pack_id": pack_id,
        "pack_name": pack_name or pack_id,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "block_count": target_blocks,
        "strategy": strategy + (" + thermal" if thermal_placement else ""),
        "block_layout": layout,
        "destination": destination,
        "notes": notes,
        "source_summary": src_summary,
        "source_counts": src_counts,
        "swap_suggestions": swap_suggestions,
        "rejected_modules": [_strip_module(r) | {"reject_reasons": r["reject_reasons"]} for r in rejected],
        "verification_summary": {
            "pass_blocks": pass_blocks, "warn_blocks": warn_blocks, "fail_blocks": fail_blocks,
        },
        "pre_install_checklist": pre_install_checklist,
        **grade_info,
    }


def _suggest_threshold_relaxation(modules, target_blocks, current_th):
    """When build fails because too few eligible, try relaxing thresholds
    progressively and show how many would pass at each level."""
    needed = target_blocks * 2
    suggestions = []
    for cap_floor, ir_ceil, label in [
        (current_th["cap_floor_reuse"], current_th["ir_ceiling_module"], "current"),
        (2.5, 30, "moderate (cap >= 2.5, IR <= 30)"),
        (2.0, 32, "lenient (cap >= 2.0, IR <= 32)"),
        (1.5, 35, "very lenient (cap >= 1.5, IR <= 35) — quality risk"),
    ]:
        th = {**current_th, "cap_floor_reuse": cap_floor, "ir_ceiling_module": ir_ceil}
        elig, _ = _eligible_with_rejects(modules, th)
        suggestions.append({
            "label":       label,
            "cap_floor":   cap_floor,
            "ir_ceiling":  ir_ceil,
            "eligible":    len(elig),
            "enough":      len(elig) >= needed,
            "deficit":     max(0, needed - len(elig)),
        })
    return suggestions


def suggest_swaps(blocks, all_modules, thresholds):
    """For grade B-or-worse packs, suggest which weak module(s) to replace
    and where to find a stronger candidate."""
    if not blocks:
        return []
    # find the weakest block (by min cap of its 2 modules)
    block_min = []
    for b in blocks:
        a, bb = b.get("a"), b.get("b")
        for m in (a, bb):
            if m and m.get("cap_ah") is not None:
                block_min.append((m["cap_ah"], m, b["block_number"]))
    if not block_min:
        return []
    block_min.sort(key=lambda x: x[0])
    weakest_cap, weakest_mod, weakest_block = block_min[0]

    # what would a "Good" tier weakest look like?
    target_cap = 4.0  # B-tier floor

    if weakest_cap >= target_cap:
        return []   # already good

    in_pack_ids = set()
    for b in blocks:
        for pos in ("a", "b"):
            m = b.get(pos)
            if m:
                in_pack_ids.add((m["session_key"], m["channel"]))

    # find available stronger candidates not currently in this pack
    eligible, _ = _eligible_with_rejects(all_modules, thresholds)
    candidates = [m for m in eligible
                  if (m["session_key"], m["channel"]) not in in_pack_ids
                  and m.get("cap_ah", 0) >= target_cap]
    candidates.sort(key=lambda m: -m["cap_ah"])

    suggestions = []
    weakest_label = (f"{weakest_mod.get('battery')}-{weakest_mod.get('cell_position')}"
                     if weakest_mod.get("battery") else f"({weakest_mod['session_key']} CH{weakest_mod['channel']})")
    if candidates:
        top = candidates[0]
        top_label = (f"{top.get('battery')}-{top.get('cell_position')}"
                     if top.get("battery") else f"({top['session_key']} CH{top['channel']})")
        suggestions.append(
            f"Block {weakest_block}'s weakest cell is {weakest_label} ({weakest_cap:.2f} Ah). "
            f"Swapping for {top_label} ({top['cap_ah']:.2f} Ah) would push the pack toward grade B."
        )
    else:
        suggestions.append(
            f"Block {weakest_block}'s weakest cell is {weakest_label} ({weakest_cap:.2f} Ah). "
            f"No stronger candidate available — test more modules to fix this."
        )
    return suggestions


def _strip_module(m):
    if not m:
        return None
    return {
        "session_key": m.get("session_key"),
        "channel":     m.get("channel"),
        "battery":     m.get("battery"),
        "cell_position": m.get("cell_position"),
        "cap_ah":      m.get("cap_ah"),
        "ir_mohm":     m.get("ir_mohm"),
        "v_end":       m.get("v_end"),
        "trend":       m.get("trend"),
    }


def build_pack_summary(modules):
    """Pre-build inspection: how many eligible, by source, what the bottleneck is."""
    th = DEFAULT_THRESHOLDS
    eligible = _eligible(modules, th)
    by_battery = {}
    for m in eligible:
        b = m.get("battery") or "(unlabelled)"
        by_battery[b] = by_battery.get(b, 0) + 1
    return {
        "total_modules": len(modules),
        "eligible": len(eligible),
        "by_battery": by_battery,
    }
