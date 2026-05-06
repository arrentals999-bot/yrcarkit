"""
Data layer for the YRCARKIT Battery UI.

Two data sources:
  - YRCARKIT SQLite DBs in ../w_lxdzdb/  (read-only, source of truth for cycle data)
  - Local SQLite at ./battery_ui.db      (read-write, our labels + pack history)
"""

import os
import re
import sqlite3
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
YRCARKIT_DIR = HERE.parent
DB_FOLDER = YRCARKIT_DIR / "w_lxdzdb"
LOCAL_DB = HERE / "battery_ui.db"


# ---------- Local DB schema ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_labels (
    session_key   TEXT PRIMARY KEY,
    battery       TEXT NOT NULL,        -- 'A', 'B', 'C', ...
    cell_start    INTEGER NOT NULL,     -- 1, 8, 15, 22
    cell_end      INTEGER NOT NULL,
    skip_channels TEXT DEFAULT '[3]',   -- JSON list
    notes         TEXT DEFAULT '',
    labeled_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS module_overrides (
    -- per-(session, channel) overrides — fix mislabels here without touching session_labels
    session_key   TEXT NOT NULL,
    channel       INTEGER NOT NULL,
    battery       TEXT,
    cell_position INTEGER,
    status        TEXT DEFAULT 'available',  -- available / used / weak / dead / retired
    notes         TEXT DEFAULT '',
    PRIMARY KEY(session_key, channel)
);

CREATE TABLE IF NOT EXISTS packs (
    pack_id      TEXT PRIMARY KEY,
    built_at     TEXT NOT NULL,
    block_count  INTEGER NOT NULL,
    strategy     TEXT NOT NULL,
    grade        TEXT,
    avg_cap      REAL,
    cap_spread   REAL,
    weakest_cap  REAL,
    avg_ir       REAL,
    ir_spread    REAL,
    predicted_life TEXT,
    destination  TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    block_layout TEXT NOT NULL  -- JSON: [{block:1, a:{...}, b:{...}}, ...]
);

CREATE TABLE IF NOT EXISTS pack_modules (
    pack_id       TEXT NOT NULL,
    session_key   TEXT NOT NULL,
    channel       INTEGER NOT NULL,
    block_number  INTEGER NOT NULL,
    block_position TEXT NOT NULL,    -- 'A' (high) or 'B' (low)
    PRIMARY KEY(pack_id, session_key, channel)
);
"""


def get_local_conn():
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------- YRCARKIT session/cycle reading ----------

def scan_sessions():
    """Group YRCARKIT DBs by session prefix.
    Returns list of dicts sorted oldest → newest.
    """
    sessions = {}
    if not DB_FOLDER.exists():
        return []

    for fp in sorted(DB_FOLDER.glob("A*_CH*_04.db")):
        m = re.match(r"A(\d{8})(\d{6})_CH(\d+)_04\.db", fp.name)
        if not m:
            continue
        date_str, time_str, ch = m.group(1), m.group(2), int(m.group(3))
        # group filenames within the same minute (1205xx → bucket "20260503_1205")
        key = f"{date_str}_{time_str[:4]}"
        try:
            ts = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M%S")
        except ValueError:
            continue

        s = sessions.setdefault(key, {
            "session_key": key,
            "first_started": ts,
            "channels": {},
        })
        s["first_started"] = min(s["first_started"], ts)
        s["channels"][ch] = str(fp)

    out = []
    for key, s in sessions.items():
        out.append({
            "session_key": key,
            "started": s["first_started"].strftime("%Y-%m-%d %H:%M:%S"),
            "started_iso": s["first_started"].isoformat(),
            "date": s["first_started"].strftime("%Y-%m-%d"),
            "channels": sorted(s["channels"].keys()),
            "channel_paths": s["channels"],
        })
    out.sort(key=lambda x: x["started"])
    return out


def read_cycles_for_channel(filepath):
    """Read all cycle tables from one channel DB. Returns sorted list of dicts."""
    conn = sqlite3.connect(filepath)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    cycles = []
    for t in tables:
        tm = re.match(r"([CF])(\d+)_CH", t)
        if not tm:
            continue
        kind = tm.group(1)
        seq = int(tm.group(2))

        cur.execute(f'SELECT MAX(cap), MAX(tim), COUNT(*) FROM "{t}"')
        max_cap, max_tim, cnt = cur.fetchone()

        cur.execute(f'SELECT vol FROM "{t}" ORDER BY id DESC LIMIT 1')
        r = cur.fetchone()
        v_end = round(r[0], 3) if r else None

        # IR via voltage-step under load
        ir_mohm = None
        cur.execute(f'SELECT vol, cur FROM "{t}" ORDER BY id ASC LIMIT 15')
        rows = cur.fetchall()
        v_rest = v_load = i_load = None
        for v, c in rows:
            if c == 0.0 and v_rest is None:
                v_rest = v
            elif c >= 1.0 and v_rest is not None and v_load is None:
                v_load = v
                i_load = c
                break
        if v_rest and v_load and i_load:
            ir = round(abs(v_rest - v_load) / i_load * 1000, 1)
            if 2 <= ir <= 200:
                ir_mohm = ir

        cycles.append({
            "table": t, "kind": kind, "seq": seq,
            "cap_ah": round(max_cap, 3) if max_cap else 0,
            "dur_s": max_tim or 0,
            "v_end": v_end,
            "rows": cnt,
            "ir_mohm": ir_mohm,
        })

    conn.close()
    cycles.sort(key=lambda x: x["seq"])
    return cycles


def find_target_discharge(cycles):
    """Pick the last complete discharge for export.
    Mirrors export_to_xlsx.py logic.
    """
    if not cycles:
        return None
    last = cycles[-1]
    if last["kind"] == "C":
        if len(cycles) < 2:
            return None
        target = cycles[-2]
    else:
        if len(cycles) == 1:
            return last
        if len(cycles) < 3:
            return None
        target = cycles[-3]
    return target if target["kind"] == "F" else None


# ---------- Label / override management ----------

def get_session_label(session_key):
    conn = get_local_conn()
    row = conn.execute(
        "SELECT * FROM session_labels WHERE session_key=?", (session_key,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_session_label(session_key, battery, cell_start, cell_end,
                       skip_channels=None, notes=""):
    if skip_channels is None:
        skip_channels = [3]
    conn = get_local_conn()
    conn.execute("""
        INSERT INTO session_labels (session_key, battery, cell_start, cell_end,
                                    skip_channels, notes, labeled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_key) DO UPDATE SET
            battery=excluded.battery,
            cell_start=excluded.cell_start,
            cell_end=excluded.cell_end,
            skip_channels=excluded.skip_channels,
            notes=excluded.notes,
            labeled_at=excluded.labeled_at
    """, (session_key, battery.upper(), cell_start, cell_end,
          json.dumps(skip_channels), notes, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_module_override(session_key, channel):
    conn = get_local_conn()
    row = conn.execute(
        "SELECT * FROM module_overrides WHERE session_key=? AND channel=?",
        (session_key, channel)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_module_override(session_key, channel, battery=None, cell_position=None,
                         status=None, notes=None):
    existing = get_module_override(session_key, channel) or {
        "battery": None, "cell_position": None, "status": "available", "notes": ""
    }
    new = {
        "battery": battery if battery is not None else existing.get("battery"),
        "cell_position": cell_position if cell_position is not None else existing.get("cell_position"),
        "status": status if status is not None else existing.get("status"),
        "notes": notes if notes is not None else existing.get("notes"),
    }
    conn = get_local_conn()
    conn.execute("""
        INSERT INTO module_overrides (session_key, channel, battery, cell_position, status, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_key, channel) DO UPDATE SET
            battery=excluded.battery,
            cell_position=excluded.cell_position,
            status=excluded.status,
            notes=excluded.notes
    """, (session_key, channel, new["battery"], new["cell_position"],
          new["status"], new["notes"]))
    conn.commit()
    conn.close()


def mark_modules_used(pack_id, module_refs):
    """Mark a list of (session_key, channel) modules as 'used' tied to a pack."""
    conn = get_local_conn()
    for ref in module_refs:
        sk, ch = ref["session_key"], ref["channel"]
        save_module_override(sk, ch, status="used")
    conn.close()


def release_pack_modules(pack_id):
    """Move all modules from a pack back to 'available'."""
    conn = get_local_conn()
    rows = conn.execute(
        "SELECT session_key, channel FROM pack_modules WHERE pack_id=?", (pack_id,)
    ).fetchall()
    for r in rows:
        save_module_override(r["session_key"], r["channel"], status="available")
    conn.execute("DELETE FROM pack_modules WHERE pack_id=?", (pack_id,))
    conn.execute("DELETE FROM packs WHERE pack_id=?", (pack_id,))
    conn.commit()
    conn.close()


# ---------- Pack persistence ----------

def save_pack(pack):
    conn = get_local_conn()
    conn.execute("""
        INSERT INTO packs (pack_id, built_at, block_count, strategy, grade,
                           avg_cap, cap_spread, weakest_cap, avg_ir, ir_spread,
                           predicted_life, destination, notes, block_layout)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pack["pack_id"], pack["built_at"], pack["block_count"], pack["strategy"],
        pack["grade"], pack["avg_cap"], pack["cap_spread"], pack["weakest_cap"],
        pack["avg_ir"], pack["ir_spread"], pack["predicted_life"],
        pack.get("destination", ""), pack.get("notes", ""),
        json.dumps(pack["block_layout"]),
    ))
    for block in pack["block_layout"]:
        for pos in ("A", "B"):
            mod = block.get(pos.lower())
            if mod:
                conn.execute("""
                    INSERT INTO pack_modules (pack_id, session_key, channel, block_number, block_position)
                    VALUES (?, ?, ?, ?, ?)
                """, (pack["pack_id"], mod["session_key"], mod["channel"],
                      block["block_number"], pos))
    conn.commit()
    conn.close()


def list_packs():
    conn = get_local_conn()
    rows = conn.execute(
        "SELECT * FROM packs ORDER BY built_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["block_layout"] = json.loads(d["block_layout"])
        out.append(d)
    conn.close()
    return out


# ---------- Combined: full module pool view ----------

def build_module_pool():
    """Walk all sessions, expand to per-module records with current
    label, override, status, capacity, IR, trend, etc.
    Returns a flat list — one record per channel-test.
    """
    from .pairing import classify_trend  # local import to avoid cycle

    pool = []
    for sess in scan_sessions():
        skey = sess["session_key"]
        label = get_session_label(skey)

        # Map channel → cell position from the session label
        cell_map = {}
        skip_set = {3}
        if label:
            try:
                skip_set = set(json.loads(label["skip_channels"]))
            except Exception:
                skip_set = {3}
            active = [c for c in sess["channels"] if c not in skip_set]
            cells = list(range(label["cell_start"], label["cell_end"] + 1))
            for ch, cid in zip(active, cells):
                cell_map[ch] = cid

        for ch in sess["channels"]:
            if ch in skip_set:
                continue
            fp = sess["channel_paths"][ch]
            cycles = read_cycles_for_channel(fp)
            target = find_target_discharge(cycles)
            dis_caps = [c["cap_ah"] for c in cycles if c["kind"] == "F"]
            trend = classify_trend(dis_caps)

            override = get_module_override(skey, ch) or {}
            battery = override.get("battery") or (label["battery"] if label else None)
            cell_pos = override.get("cell_position") or cell_map.get(ch)
            status = override.get("status") or "available"

            pool.append({
                "session_key": skey,
                "session_started": sess["started"],
                "channel": ch,
                "battery": battery,
                "cell_position": cell_pos,
                "labelled": battery is not None and cell_pos is not None,
                "cap_ah": target["cap_ah"] if target else None,
                "ir_mohm": target["ir_mohm"] if target else None,
                "v_end": target["v_end"] if target else None,
                "discharge_caps": dis_caps,
                "trend": trend,
                "status": status,
                "notes": override.get("notes") or "",
            })
    return pool
