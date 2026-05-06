# Ratan's Private Battery Manager

Local web UI for managing Prius hybrid battery module testing data from YRCARKIT.

## What it does

- **Reads YRCARKIT SQLite databases** in `../w_lxdzdb/` (read-only — your raw data is the source of truth).
- **Stores labels & pack history** in a local SQLite (`battery_ui.db`) right here.
- **Builds balanced 14-block (28-module) Prius packs** using pair-opposites or match-similar pairing, with optional thermal placement.
- **Grades each pack A–F** and predicts how long it'll last in service (18-36 months down to "weeks before P0A80").
- **Tags every module** with a trend signal (IMPROVING / STABLE / PLATEAU / DECLINING / DEAD) based on cycle-over-cycle behavior.

## Run it

Double-click `run.bat`. Browser opens to `http://127.0.0.1:5000/`. Close the console window to stop.

First run installs Flask automatically. Requires Python 3.9+ (already present on this machine).

## The 5 tabs

| Tab | What you do there |
|-----|-------------------|
| **Dashboard** | At-a-glance: total modules, status breakdown, latest session info |
| **Label Sessions** | Tag each YRCARKIT session with battery letter (A/B/...) and cell range (1-7, 8-14, ...) |
| **Module Pool** | Master table of every module ever tested. Filter, edit status, fix mislabels |
| **Build Pack** | Pick source battery + strategy, get a graded 14-block pack with predicted lifespan |
| **Pack History** | Every pack you've built, with stats. Delete to release modules back to pool |

## Default thresholds (calibrated for YRCARKIT 1.5 A / 6.4 V cutoff)

- Cap floor for reuse: **3.0 Ah**
- IR ceiling per module: **25 mΩ DC**
- Max pack cap spread: **0.5 Ah**
- Max pack IR spread: **5 mΩ**

All editable per pack-build in the UI. To get industry-comparable readings, change the YRCARKIT discharge cutoff from 6.4 V → 6.0 V in the program settings.

## Lifespan grading

| Grade | Weakest cap | Cap spread | Max IR | Predicted life |
|-------|-------------|-----------|--------|---------------|
| **A** Excellent | ≥ 4.5 Ah | ≤ 0.3 Ah | ≤ 20 mΩ | 18-36 months |
| **B** Good | ≥ 4.0 Ah | ≤ 0.4 Ah | ≤ 22 mΩ | 12-18 months |
| **C** Acceptable | ≥ 3.5 Ah | ≤ 0.5 Ah | ≤ 25 mΩ | 6-12 months |
| **D** Marginal | ≥ 3.0 Ah | ≤ 0.7 Ah | ≤ 30 mΩ | 3-6 months |
| **F** Don't ship | below D, or any DECLINING/DEAD | — | — | weeks |

Lifespan estimates from PriusChat refurb-life threads and Hybrid Automotive guides — ±50% real-world variation typical.

## Files

- `app.py` — Flask app + API endpoints
- `db.py` — YRCARKIT DB readers + local SQLite manager
- `pairing.py` — pair-opposites, match-similar, lifespan grading, trend classifier
- `templates/index.html` — single-page UI
- `static/app.js` — frontend logic
- `static/style.css` — styling
- `battery_ui.db` — local labels and pack history (created on first run)

## Phase 2 (later)

Push to Firebase Hosting + Firestore so you can view this from your phone. Same UI, same logic, just deployed to the web. Not built yet — the local app does everything you need first.
