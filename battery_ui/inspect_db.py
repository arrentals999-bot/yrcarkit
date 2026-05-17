"""Sweep every YRCARKIT DB and infer cutoff voltage per channel per session."""
import sqlite3, re
from pathlib import Path
from collections import defaultdict

DB_FOLDER = Path(__file__).resolve().parent.parent / "w_lxdzdb"

def infer_cutoff(path):
    """Return the minimum voltage reached during any F (discharge) table.
    That's effectively the cutoff setting at the time."""
    c = sqlite3.connect(path)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'F%'").fetchall()]
    mins = []
    for t in tables:
        # Only the discharge portion (procedure=1) — exclude rest periods
        row = c.execute(f'SELECT MIN(vol) FROM "{t}" WHERE cur > 0').fetchone()
        if row and row[0] is not None:
            mins.append(row[0])
    c.close()
    if not mins:
        return None
    return min(mins)

# Group by session
sessions = defaultdict(dict)  # {session_key: {ch: cutoff_vol}}
for fp in sorted(DB_FOLDER.glob("A*_CH*_04.db")):
    m = re.match(r"A(\d{8})(\d{6})_CH(\d+)_04\.db", fp.name)
    if not m:
        continue
    date_str, time_str, ch = m.group(1), m.group(2), int(m.group(3))
    skey = f"{date_str}_{time_str[:4]}"
    cutoff = infer_cutoff(fp)
    sessions[skey][ch] = cutoff

# Print per-session summary with date
print(f"{'session_key':22} {'date':12} {'channels':30} {'cutoffs (min vol)':40}")
print("-" * 110)
for skey in sorted(sessions.keys()):
    chs = sorted(sessions[skey].keys())
    date = f"{skey[:4]}-{skey[4:6]}-{skey[6:8]}"
    ch_str = ", ".join(f"CH{c}" for c in chs)
    cut_str = ", ".join(f"{sessions[skey][c]:.3f}" if sessions[skey][c] is not None else "?" for c in chs)
    # Categorize: 6.0 or 6.4
    sample = next((v for v in sessions[skey].values() if v is not None), None)
    if sample is None:
        tag = "no-data"
    elif sample < 6.25:
        tag = "6.0V"
    elif sample < 6.7:
        tag = "6.4V"
    else:
        tag = "other"
    print(f"{skey:22} {date:12} {ch_str:30} [{tag}] {cut_str}")

# Summary
print("\n=== Sessions per cutoff bucket ===")
buckets = defaultdict(int)
for skey, chs in sessions.items():
    sample = next((v for v in chs.values() if v is not None), None)
    if sample is None:
        buckets["no-data"] += 1
    elif sample < 6.25:
        buckets["6.0V"] += 1
    elif sample < 6.7:
        buckets["6.4V"] += 1
    else:
        buckets["other"] += 1
for k, v in sorted(buckets.items()):
    print(f"  {k}: {v} sessions")
