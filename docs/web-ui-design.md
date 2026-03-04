# Solar Challenge Web UI — Design Specification

## Overview

A rich, interactive web dashboard for the Solar Challenge energy flow simulator. The UI enables users to configure and run single-home and fleet simulations, explore results through interactive data visualisations, browse past simulation runs, build and sweep scenarios, and get help from an AI assistant — all without using the command line.

Built on the existing Flask + HTMX stack, enhanced with Tailwind CSS, Alpine.js, and Plotly.js.

## Design Philosophy

- **Progressive enhancement** — Flask/Jinja2 server-rendered pages with HTMX for dynamic updates and Alpine.js for lightweight client interactivity. No SPA framework.
- **Python-centric** — All logic stays in Python. JavaScript is used only for chart rendering and minor UI interactions.
- **Zero infrastructure** — SQLite for persistence, threading for background jobs. No Redis, Celery, or external services required (except Anthropic API for the AI assistant).
- **Responsive** — Works on tablets and desktops. Not optimised for mobile (simulation tool, not a consumer app).

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | Flask + Blueprints | Existing, extended with multiple blueprints |
| Templating | Jinja2 + HTMX 2.x | Upgrade from 1.9.10; SSE extension for progress |
| Client interactivity | Alpine.js 3.x | Lightweight reactivity for forms, toggles, tabs |
| Styling | Tailwind CSS 3.x | CDN play mode (no build step) |
| Charts | Plotly.js 2.x | Already present |
| Persistence | SQLite via `sqlite3` | stdlib, no ORM |
| Background jobs | `concurrent.futures.ThreadPoolExecutor` + SSE | No external broker |
| AI | Anthropic Python SDK | `claude-sonnet-4-5-20250514` |

## Navigation Structure

```
Sidebar (collapsible):
├── Dashboard              Overview, recent runs, quick-start
├── Simulate
│   ├── Single Home        Full config -> run -> results
│   └── Fleet              Distribution config -> run -> results
├── Scenarios
│   ├── Builder            Visual YAML editor with live preview
│   └── Sweeps             Parameter sweep config & results
├── History
│   ├── Runs               Sortable/filterable run browser
│   └── Compare            Side-by-side run comparison
└── AI Assistant            Chat interface for configuration help
```

## Pages

### 1. Dashboard

The landing page providing an overview of activity and quick-start actions.

**Content:**
- **Recent Runs** — Table of last 10 simulation runs (name, type badge, date, key metric). Click to view results.
- **Quick-Start Cards** — Three action cards:
  - "Run Single Home" -> pre-filled form with sensible UK defaults
  - "Load Scenario" -> dropdown of built-in scenarios (bristol-phase1, etc.)
  - "Run Fleet" -> fleet configuration page
- **Aggregate Stats** — Counter cards: total runs, total homes simulated, total energy modelled (MWh).

### 2. Single Home Simulator

Full configuration form exposing all `HomeConfig` parameters, with run execution and inline results.

**Configuration Panels (accordion or tabs):**

| Panel | Fields | Notes |
|-------|--------|-------|
| **PV System** | Capacity (0.5-20 kW slider), Azimuth (compass widget or 0-360), Tilt (0-90), Module efficiency (%), Inverter efficiency (%), Inverter capacity (kW, optional) | Azimuth defaults to 180 (south-facing) |
| **Battery** | Enable toggle, Capacity (kWh), Max charge rate (kW), Max discharge rate (kW), Dispatch strategy picker: self-consumption / TOU-optimised / peak-shaving | Strategy-specific sub-forms: TOU -> peak hours, off-peak hours; Peak-shaving -> import limit kW |
| **Load** | Mode radio: "Annual consumption" (kWh input) OR "By occupants" (1-5+ dropdown), Stochastic toggle, Seed (optional) | Occupant mode shows Ofgem TDCV estimate |
| **Heat Pump** | Enable toggle, Type: ASHP / GSHP radio, Thermal capacity (kW), Annual heat demand (kWh) | Only visible when enabled |
| **Tariff** | Preset selector: Flat / Economy 7 / Economy 10 / Custom, Custom: add/remove TOU periods (start time, end time, rate, name) | SEG export rate (p/kWh, optional) |
| **Location** | Preset dropdown (Bristol, London, Edinburgh, Manchester) + Custom (lat, lon, altitude), Name field | Map pin would be nice but not required |
| **Period** | Date range picker, Quick presets: 7 days / 30 days / 90 days / 365 days | 365 days defaults to full year 2024-01-01 to 2024-12-31 |

**Execution:**
- "Run Simulation" button -> HTMX POST to `/api/simulate/home`
- Progress tracker appears (SSE-driven progress bar, step indicators, elapsed time)
- On completion, results section renders inline (below form or in separate tab)
- "Save to History" button persists results to SQLite

### 3. Fleet Simulator

Fleet configuration with distribution editors and live preview.

**Layout:**
- Fleet size selector (n_homes: 10-500)
- Per-component distribution editor cards:

| Component | Distribution Types | Parameters |
|-----------|-------------------|------------|
| **PV** | Weighted discrete, Normal, Uniform, Shuffled pool | Type-specific params (see below) |
| **Battery** | Weighted discrete, Normal, Uniform, Shuffled pool | Same, plus None option for "no battery" |
| **Load** | Normal, Uniform | Annual consumption distribution |
| **Heat Pump** | Weighted discrete | Ownership % (ASHP/GSHP/None weights) |

**Distribution Parameter Sub-forms:**
- **Weighted Discrete**: Value + Weight rows (add/remove). Live pie chart preview.
- **Normal**: Mean, Std, Min, Max sliders. Live bell curve preview.
- **Uniform**: Min, Max range slider. Live uniform bar preview.
- **Shuffled Pool**: Value + Count rows (add/remove). Counts must sum to n_homes (validated). Live bar chart preview.
- **Proportional**: Source field path, multiplier, offset.

**Live Preview:** Each distribution card shows a Plotly histogram of the expected fleet composition, updating on input change (debounced HTMX call or client-side for simple distributions).

**Actions:**
- "Run Fleet" -> background job with per-home progress bar
- "Export as YAML" -> generates `ScenarioConfig`-compatible YAML download
- "Import YAML" -> file upload that populates the form
- "Load Preset" -> dropdown of built-in scenarios

### 4. Scenario Builder

Visual editor for `ScenarioConfig` YAML files.

**Layout:** Dual-pane:
- **Left**: Structured form mapping to ScenarioConfig fields (name, description, period, location, fleet distribution, output config, SEG tariff, tariff config)
- **Right**: Live YAML preview (syntax-highlighted `<pre>` block), auto-updates on form change via HTMX partial

**Actions:**
- "Validate" -> runs `ScenarioConfig` parsing, shows errors inline with field highlighting
- "Save YAML" / "Download YAML" -> export
- "Load from File" -> file upload
- "Load Preset" -> built-in scenarios (bristol-phase1, dispatch-comparison, etc.)
- Schema documentation tooltips on each field

### 5. Sweep Configuration

Parameter sweep builder with results visualisation.

**Configuration:**
- Parameter to sweep: dropdown (pv_capacity_kw, battery_capacity_kwh, annual_consumption_kwh, etc.)
- Sweep range: min, max, steps inputs
- Sweep mode: linear / geometric radio
- Preview: dot plot showing sweep points on a number line
- Base configuration: select from saved configs or configure inline
- Optional: second sweep dimension for 2D parameter exploration

**Execution:**
- "Run Sweep" -> launches all sweep variants as background jobs
- Combined progress bar (N of M sweep points complete)

**Results:**
- Parameter-vs-metric chart: X = swept parameter, Y = selectable metric (self_consumption_ratio, grid_dependency, net_cost, etc.)
- If 2D sweep: heatmap with both parameters as axes, metric as colour
- Tabular results with all sweep points, sortable
- Highlight optimal point (min cost, max self-consumption, etc.)

### 6. Run Browser (History)

Browsable, searchable history of all simulation runs.

**Table Columns:**
| Column | Type | Sortable | Filterable |
|--------|------|----------|------------|
| Name | text | yes | search |
| Type | badge (home/fleet/sweep) | yes | dropdown |
| Date | datetime | yes | date range |
| Duration | seconds | yes | - |
| Generation (kWh) | number | yes | - |
| Self-Consumption Ratio | percentage | yes | - |
| Net Cost | currency | yes | - |
| Status | badge (complete/failed) | yes | dropdown |

**Interactions:**
- Click row -> navigate to detailed results view
- Multi-select checkbox -> "Compare Selected" button (2-4 runs)
- Right-click or action menu: Rename, Add notes, Delete (with confirmation), Export config, Export CSV
- Pagination (20 per page)

### 7. Comparison View

Side-by-side comparison of 2-4 simulation runs.

**Layout:**
- **Header**: Run names as column headers with badges
- **Summary Cards Row**: Key metrics for each run with delta indicators (green up/red down arrows showing % change relative to first run)
- **Tabbed Charts**:
  - Overlaid power flow timelines (different colours per run, shared axes)
  - Overlaid battery SOC curves
  - Grouped bar chart of energy totals per run
  - Radar chart comparing efficiency ratios (self-consumption, grid dependency, export ratio)
- **Delta Table**: Metric | Run A | Run B | Delta | % Change

### 8. AI Assistant

Conversational AI interface for configuring, running, and interpreting simulations.

**UI:**
- Accessible from every page via sidebar button or floating action button
- Opens as a slide-over panel (right side, ~400px wide) or full page
- Message thread: user bubbles (right, blue) and assistant bubbles (left, grey)
- Input: textarea with send button (Enter to submit, Shift+Enter for newline)
- Streaming: assistant tokens appear as they arrive (SSE from backend)
- Markdown rendering in assistant messages (headers, lists, code blocks, tables)
- Typing indicator while waiting

**Capabilities (via tool use):**
| Tool | Description |
|------|-------------|
| `run_home_simulation` | Accept natural language config -> parse to HomeConfig -> execute -> return summary |
| `run_fleet_simulation` | Accept fleet description -> configure distributions -> execute -> return fleet summary |
| `load_scenario` | Load a built-in or saved scenario file and describe it |
| `get_run_results` | Retrieve results from a past run by name or ID |
| `explain_metric` | Look up metric definition, typical UK benchmarks, and interpretation guidance |
| `suggest_config` | Recommend PV/battery sizing based on consumption and goals |

**System Prompt Context:**
- Full simulator capabilities documentation (parameters, ranges, strategies)
- Typical UK values and benchmarks
- Current page context (if on results page, include current simulation summary)
- Available scenarios and presets

**Pre-populated Prompts (quick actions):**
- "Help me size my solar PV system"
- "What battery capacity do I need?"
- "Explain my self-consumption ratio"
- "Compare dispatch strategies for my setup"
- "What PV system do I need for 3,200 kWh/year consumption?"

**Persistence:**
- Chat history stored in SQLite per session
- Previous messages loaded on page revisit
- "Ask about these results" button on results pages injects context

## Visualisation Spec

### Colour Palette

| Series | Colour | Hex |
|--------|--------|-----|
| PV Generation | Amber | `#f5a623` |
| Demand | Red | `#d0021b` |
| Self-Consumption | Green | `#7ed321` |
| Grid Import | Grey | `#9b9b9b` |
| Grid Export | Blue | `#4a90e2` |
| Battery Charge | Teal | `#50e3c2` |
| Battery Discharge | Orange | `#f8a427` |
| Heat Pump | Purple | `#9013fe` |
| Financial Cost | Red | `#d0021b` |
| Financial Revenue | Green | `#7ed321` |

### Single Home Charts

1. **Power Flow Timeline**
   - Type: Stacked area chart
   - Series: generation, demand, self_consumption, grid_import, grid_export
   - X-axis: time (zoomable via Plotly rangeslider)
   - Resolution adapts: minute for <3 days visible, hourly for <30 days, daily for longer
   - Brush zoom to select time range

2. **Battery State of Charge**
   - Type: Line chart with fill-to-zero
   - Series: battery_soc (kWh)
   - Overlays: min SOC threshold (dashed), max SOC threshold (dashed)
   - Charge events highlighted as green bands, discharge as orange bands
   - Only shown when battery is configured

3. **Energy Sankey Diagram**
   - Type: Plotly Sankey
   - Flows:
     - PV Generation -> Self-Consumption
     - PV Generation -> Battery Charge
     - PV Generation -> Grid Export
     - Grid Import -> Demand (shortfall)
     - Grid Import -> Battery Charge (TOU)
     - Battery Discharge -> Demand
   - Node colours match series palette

4. **Daily Energy Balance**
   - Type: Grouped bar chart (enhanced existing)
   - Series: generation, demand, self_consumption, grid_import, grid_export, battery_charge, battery_discharge
   - X-axis: date (category)

5. **Monthly Summary**
   - Type: Stacked bar per month
   - Series: all energy categories
   - Only shown for simulations >= 90 days

6. **Financial Breakdown**
   - Type: Dual-axis chart
   - Primary Y: daily cost bars (import cost red, export revenue green)
   - Secondary Y: cumulative net cost line
   - Only shown when tariff is configured

7. **Seasonal Comparison**
   - Type: Grouped bars
   - Groups: Winter (Dec-Feb) vs Summer (Jun-Aug)
   - Metrics: generation, demand, self-consumption ratio, grid dependency
   - Only shown for simulations >= 180 days

8. **Heat Pump Analysis** (conditional)
   - COP vs outdoor temperature scatter plot
   - Heating load vs degree-days line chart
   - Load share pie chart (heat pump vs base household)
   - Only shown when heat pump is configured

### Fleet Charts

1. **Distribution Overview**
   - Type: Histograms
   - Shows: configured distribution (outline) vs actual sampled values (filled bars)
   - One histogram per component (PV, battery, load, heat pump ownership)

2. **Fleet Aggregate Timeline**
   - Type: Stacked area chart (same as single home but fleet totals)
   - Series: total fleet generation, demand, self_consumption, grid_import, grid_export

3. **Home Comparison Heatmap**
   - Type: Plotly heatmap
   - Rows: homes (sorted by selectable metric)
   - Columns: metrics (self_consumption_ratio, grid_dependency, peak_demand, net_cost)
   - Colour intensity: normalised metric value
   - Click a home -> drill down to individual results

4. **Box Plots**
   - Type: Plotly box plots
   - One box per metric across all homes
   - Metrics: self_consumption_ratio, grid_dependency_ratio, peak_generation, peak_demand, net_cost
   - Shows median, quartiles, outliers

5. **Grid Impact Timeline**
   - Type: Area chart
   - Series: net fleet import/export (positive = import, negative = export)
   - Fill above zero (grey/red) and below zero (blue/green)
   - Shows fleet's aggregate grid impact over time

## Data Persistence

### SQLite Schema

```sql
-- Simulation run metadata
CREATE TABLE runs (
    id TEXT PRIMARY KEY,           -- UUID
    name TEXT NOT NULL,
    type TEXT NOT NULL,            -- 'home', 'fleet', 'sweep'
    config_json TEXT NOT NULL,     -- Serialised HomeConfig/FleetConfig
    summary_json TEXT,             -- Serialised SummaryStatistics/FleetSummary
    status TEXT NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed'
    error_message TEXT,
    created_at TEXT NOT NULL,      -- ISO 8601
    completed_at TEXT,
    duration_seconds REAL,
    n_homes INTEGER DEFAULT 1,
    notes TEXT
);

-- Time series stored as compressed files on disk
-- Path: ~/.solar-challenge/runs/{run_id}/results.parquet
-- Path: ~/.solar-challenge/runs/{run_id}/fleet_results/{home_idx}.parquet

-- Background job tracking
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,           -- UUID
    run_id TEXT REFERENCES runs(id),
    status TEXT NOT NULL DEFAULT 'queued',  -- 'queued', 'running', 'completed', 'failed'
    progress_pct REAL DEFAULT 0,
    current_step TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_traceback TEXT
);

-- AI chat history
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,            -- 'user', 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT             -- Tool calls, context, etc.
);

-- Saved configuration presets
CREATE TABLE config_presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,            -- 'home', 'fleet'
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### File Storage

```
~/.solar-challenge/
├── solar_challenge.db           # SQLite database
└── runs/
    ├── {uuid}/
    │   ├── results.parquet      # Single home time series
    │   ├── summary.json         # Quick-load summary
    │   └── config.json          # Original config
    └── {uuid}/
        ├── fleet_summary.json
        ├── config.json
        └── homes/
            ├── 0.parquet
            ├── 1.parquet
            └── ...
```

## API Endpoints

### Simulation API (`/api/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/simulate/home` | Start single home simulation (background) |
| POST | `/api/simulate/fleet` | Start fleet simulation (background) |
| GET | `/api/jobs/<id>` | Get job status |
| GET | `/api/jobs/<id>/progress` | SSE stream of job progress |
| GET | `/api/jobs/<id>/results` | Get completed job results |

### History API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/runs` | List runs (paginated, filterable) |
| GET | `/api/runs/<id>` | Get run detail |
| DELETE | `/api/runs/<id>` | Delete run |
| GET | `/api/runs/<id>/export/csv` | Export run as CSV |
| GET | `/api/runs/<id>/export/yaml` | Export run config as YAML |

### Assistant API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/assistant/chat` | Send message, get streaming SSE response |
| GET | `/api/assistant/history` | Get chat history for session |

## Implementation Tasks

This design is implemented across 10 AutoClaude tasks (specs 011-020) with the following dependency structure:

```
Task 011 (Foundation) ─────┬──> Task 012 (UI Shell)
                           └──> Task 013 (Background Engine)
                                          │
              ┌───────────────────────────┼───────────────────────┐
              v                           v                       v
     Task 014 (Home Config)    Task 015 (Home Viz)     Task 018 (Run Browser)
              │                           │
              v                           │
     Task 016 (Fleet Config) <────────────┘
              │
     ┌────────┼────────┐
     v        v        v
  Task 017  Task 019  Task 020
 (Fleet     (Scenario (AI
  Viz)      Builder)  Assistant)
```

### Execution Phases (parallelism opportunities)

| Phase | Tasks | Notes |
|-------|-------|-------|
| 1 | 011 (Foundation) | Must complete first |
| 2 | 012 (UI Shell) + 013 (Background Engine) | Parallel |
| 3 | 014 (Home Config) + 015 (Home Viz) | Parallel |
| 4 | 016 (Fleet Config) + 018 (Run Browser) | Parallel |
| 5 | 017 (Fleet Viz) + 019 (Scenarios) | Parallel |
| 6 | 020 (AI Assistant) | Depends on most prior tasks |
