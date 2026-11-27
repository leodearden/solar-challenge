# Solar Challenge Web UI — Design Specification

> **⚠ Non-authoritative design document.** This file is the original forward-looking
> design specification, written before implementation, and has diverged from the
> as-built code.  The as-built stack uses **Alpine.js** for client interactivity
> (**no HTMX**) and a **compiled Tailwind CSS build** (`static/dist/style.css`,
> built from `static/src/input.css`; the CDN play-mode approach in this document
> was not adopted).  Treat HTMX references and the "CDN (no build step)" Tailwind
> claim throughout this document as aspirational/historical.

## Overview

A rich, interactive web dashboard for the Solar Challenge energy flow simulator. The UI enables users to configure and run single-home and fleet simulations, explore results through interactive data visualisations, browse past simulation runs, build and sweep scenarios, and get help from an AI assistant — all without using the command line.

Built on the existing Flask + Alpine.js stack, enhanced with compiled Tailwind CSS and Plotly.js.

## Design Philosophy

- **Progressive enhancement** — Flask/Jinja2 server-rendered pages with Alpine.js for lightweight client interactivity. No SPA framework.
- **Python-centric** — All logic stays in Python. JavaScript is used only for chart rendering and minor UI interactions.
- **Zero infrastructure** — SQLite for persistence, threading for background jobs. No Redis, Celery, or external services required (except Anthropic API for the AI assistant).
- **Responsive** — Works on tablets and desktops. Not optimised for mobile (simulation tool, not a consumer app).

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | Flask + Blueprints | Existing, extended with multiple blueprints |
| Templating | Jinja2 | Server-rendered pages |
| Client interactivity | Alpine.js 3.x | Lightweight reactivity for forms, toggles, tabs (as-built; HTMX was not adopted) |
| Styling | Tailwind CSS 3.x | Compiled build (`static/dist/style.css`; CDN play mode was not adopted) |
| Charts | Plotly.js | As-built: the release the `plotly` Python package bundles, served by `web/plotly_js.py` |
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

### Form limits and starting values

Every dashboard form's bounds and starting values render from one value, `page_limits()` in web/fleet_components.py, a `PageLimits`. It holds the fleet size and the Fleet Simulator's size slider; the seed; the simulation window's days, default window, day choices and custom range, and the Scenario Builder's period presets; and the fleet components PV, battery and load (`FLEET_COMPONENTS`), each with its `value_range`, the types its distribution editor offers and the distribution that editor starts at. It reaches the pages through one channel:

- A context processor in web/app.py gives every template `page_limits`, from which the templates render their inputs' bounds and choices.
- base.html writes `page_limits.as_json()` once into each page's `<head>`, as the JSON of `<script type="application/json" id="page-limits">`.
- The pages' scripts, static/js/fleet-simulator.js, static/js/scenario-builder.js and the Single Home page's inline script, read that element for the values they start at and the bounds they check.

Each fleet component's `value_range` bounds every home's value, fixed or drawn. The server refuses a home whose PV capacity, battery capacity or annual consumption lies outside its component's range, naming the field and the range:

- The Single Home page's reader, `parse_home_config` (web/simulation_params.py), reads each of the home's values within its range.
- The Fleet Simulator's reader, `parse_fleet_form` (web/fleet_scenario.py), passes the homes `parse_scenario` reads from the form's scenario document to `refuse_homes_outside_ranges`, so a value a distribution draws is bounded as a fixed one is.
- The Scenario Builder's check, `builder_form_errors` (web/builder_form.py), passes the homes `parse_scenario` reads from the builder's document, read in memory, to `refuse_homes_outside_ranges` and lists its refusal.

The Fleet Simulator leaves validation to the server: Run posts the form as entered, and the page shows the server's refusal. The Single Home page also checks its values against the same ranges, read from `#page-limits`, before it sends them.

Each fleet component's editor offers Fixed Value and `fleet_distribution.editor_types` of its field's kind, the kind its block's fleet row gives the field, in the order of fleet_distribution.py's `DISTRIBUTION_TYPES`. Its `start`, an `EditorStart`, is built from fleet_distribution.py's spec objects: one spec of each type the editor offers, and the type the card shows. PV and battery start at shuffled pools, PV 3, 4, 5 and 6 kW in 20, 40, 30 and 10 homes, and battery 0, 5 and 10 kWh in 40, 40 and 20 homes; load starts at a normal of 3,400 ± 800 kWh clamped to 2,000–6,000. `ComponentLimits` checks at construction that a start holds one spec of each editor type, in order, and that each shuffled pool's counts total the default fleet size, `FLEET_SIZE_DEFAULT`. `#page-limits` writes a start as the editor holds it: `{type, fixed, specs: {<type>: <its spec without the type>}}`.

### Scenario import policy

The Fleet Simulator and the Scenario Builder each import a fleet scenario file, uploaded or a preset, as their own form, on the server: `fleet_form_from_scenario` (web/fleet_scenario.py) and `builder_form_from_scenario` (web/builder_form.py). Both compose the readers of web/scenario_import.py, and each page declares what its form holds as the reads it gives `read_blocks`. A page answers `{form, not_loaded}`, or `{error}` with HTTP 400 for a refusal. Each setting of the scenario is judged in this order:

1. **The reader's refusal.** The document must be a mapping holding a `fleet_distribution:` block, and its period's dates must be days, with no time of day or time zone, since the pages' date fields hold neither. The Fleet Simulator then refuses a window that ends before it starts or spans more than `MAX_WINDOW_DAYS` days. Next, `config.read_fleet_scenario` reads the document in `parse_scenario`'s order, and `refuse_a_fleet_the_dashboard_cannot_run` holds its fleet to the dashboard's bounds. No home is generated for these checks.
2. **A setting the form needs but cannot hold exactly.** Such a setting is refused, naming its path and the page, because loading the scenario without it would run another fleet. Examples are a component distribution its editor does not offer, such as `proportional_to` (`ComponentLimits.editor_spec`), a tariff type or dispatch strategy the page does not hold, a setting the page always sets but the scenario leaves out, and a SEG key the page does not hold.
3. **The page's own reader.** The form loaded is then read as the page reads its own form: the Fleet Simulator's by `parse_fleet_form`, which generates the import's one set of homes, and the Scenario Builder's by `builder_form_errors`. A missing scenario name is the one reason the builder does not refuse: the form loads with a blank name, which Validate and Save still require.
4. **Everything else.** The form has no control for any other setting, so the form loads without it and `not_loaded` names its path, in document order, e.g. `finance`, `fleet_distribution.random_order` or `fleet_distribution.pv.azimuth`. The page lists those paths in its notice. A setting the scenario leaves out is left out of the form.

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
| **PV System** | Capacity (0.5-20 kW slider), Azimuth (compass widget or 0-360), Tilt (0-90), Module efficiency (%), Inverter efficiency (%), Inverter capacity (kW, optional) | A field the body does not send takes `PVConfig`'s default (a south-facing azimuth), not a web copy; see [Fields not sent](#fields-not-sent) |
| **Battery** | Enable toggle, Capacity (kWh), Max charge rate (kW), Max discharge rate (kW), Dispatch strategy picker: self-consumption / TOU-optimised / peak-shaving | Strategy-specific sub-forms: TOU -> peak hours, off-peak hours; Peak-shaving -> import limit kW |
| **Load** | Mode radio: "Annual consumption" (kWh input) OR "By occupants" (1-5+ dropdown), Stochastic toggle | Occupant mode shows the simulator's own default for that household size (`OFGEM_TDCV_BY_OCCUPANTS`). No seed input: see [Fields not sent](#fields-not-sent) |
| **Heat Pump** | Enable toggle, Type: ASHP / GSHP radio, Thermal capacity (kW), Annual heat demand (kWh) | Only visible when enabled |
| **Tariff** | Preset selector: Flat / Economy 7 / Economy 10 / Custom, Custom: add/remove TOU periods (start time, end time, rate, name) | SEG export rate (p/kWh, optional) |
| **Location** | Preset dropdown (Bristol, London, Edinburgh, Manchester) + Custom (lat, lon, altitude), Name field | Map pin would be nice but not required |
| **Period** | Date range picker, Quick presets: 7 / 14 / 30 / 90 days / 1 year (365 days) | 365 days runs the full year 2024-01-01 to 2024-12-31; any other days value runs from 2024-06-01. The form leaves the window's rules to the server and shows its refusal; see [Simulation window](#simulation-window). |

**Execution:**
- "Run Simulation" button -> HTMX POST to `/api/simulate/home`
- Progress tracker appears (SSE-driven progress bar, step indicators, elapsed time)
- On completion, results section renders inline (below form or in separate tab)
- "Save to History" button persists results to SQLite

#### Simulation window

The server enforces two rules on a run's window. Their constants, `MAX_DAYS` and `MAX_WINDOW_DAYS`, live in web/fleet_components.py, and web/simulation_params.py enforces them:

- **Days** (`MAX_DAYS`): a request may send 1 to 365 days. 365 runs the full year 2024-01-01 to 2024-12-31. Any other value runs that many days from 2024-06-01, so one above 214 continues into 2025.
  - Running past the year's end is intended. The weather is read by UTC time of year and wraps at the year's end, so such a run reads each TMY day at most once, as a start/end window across the new year does.
  - Days stops at 365 so that the full year is the only year-long days window. 366 days from 2024-06-01 would be a second, June-to-June year that reads one TMY day twice.
- **Span** (`MAX_WINDOW_DAYS`): a run spans at most the full year, 366 days, and must not end before it starts. The weather is one TMY year, so a longer window would repeat it.

#### Fields not sent

- In the home, fleet and builder form bodies, a top-level field sent as null or `""` (a cleared input) reads as not sent, by one rule, `request_boundary.present_fields`. A key the reader does not recognise is still refused, whatever it holds. A nested block's contents follow that block's grammar.
- A home field not sent takes its engine dataclass's default: `PVConfig`'s, `LoadConfig`'s, `BatteryConfig`'s or `HomeConfig`'s. The home reader holds two web defaults of its own: location Bristol, `request_boundary.WEB_DEFAULT_LOCATION`, which a fleet form that sends no location runs at too, and stochastic false. The dashboard takes no load seed and compares stored runs, so a web run is repeatable by default, while `LoadConfig`'s `use_stochastic` default serves the library.
- A `pv_kw` not sent is `scenario_blocks.PV_CAPACITY_KW_WHEN_OMITTED`, as an omitted pv capacity in a scenario file is. A `battery_kwh` not sent is no battery, and a `consumption_kwh` not sent is the TDCV estimate for the occupants.
- `PATCH /api/history/runs/<id>` is an update, not a form body, and stays outside the rule.

### 3. Fleet Simulator

Fleet configuration with distribution editors, and a preview that summarises under each card the homes Run builds from the form.

**Layout:**
- Fleet size selector (n_homes: 1 to 10,000; the slider is a 10–500 convenience)
- Per-component distribution editor cards:

| Component | Field it posts | Distribution Types |
|-----------|----------------|--------------------|
| **PV** | `pv.capacity_kw` | Fixed Value, and the editor's types for the component's field kind |
| **Battery** | `battery.capacity_kwh` | The same; the card's enable switch leaves the battery block out, a fleet without batteries |
| **Load** | `load.annual_consumption_kwh` | The same |

**Distribution Parameter Sub-forms:** templates/components/distribution-editor.html renders each editor type from its `DISTRIBUTION_TYPES` record and names no type itself. A type's panel holds one input per parameter, captioned by the parameter's title. A type with rows holds a list of value rows, each with its paired weight or count (add/remove); a shuffled pool shows its counts' total, which the server holds to n_homes.

**Wire shape:** Both fleet pages post a component as the grammar's own spec: `{pv: {capacity_kw: <spec>}, battery: {capacity_kwh: <spec>} | absent, load: {annual_consumption_kwh: <spec>}}`. A spec is a number, null, or `{type, ...}` with its type's keys, a type's rows as parallel lists, `values` with `weights` or `counts`. static/js/distribution-editor.js's `DistributionEditor.wire` writes it from the editor's state.

- The server reads the blocks with `fleet_config.read_form_fleet`, as a `fleet_distribution:` block's are, at the form's own paths and with nothing invented, so a refusal names the field the page posted, e.g. `pv.capacity_kw`. It then holds the fleet to the dashboard's bounds. A shuffled pool's counts must total the fleet's n_homes, the grammar's rule.
- A blank optional input posts null, so a normal needs no clamps. A blank battery pool value is a home without a battery, and a blank load value takes the load's default. Every home needs a PV capacity, so a blank PV value, fixed or one a home would draw, is refused naming `pv.capacity_kw` before any home is generated.

**Import:** Import YAML and Load Preset load each component's spec as the grammar reads it, written back in canonical form (`ComponentLimits.editor_spec`), through `DistributionEditor.load`. A fixed spec loads as Fixed Value, a normal without clamps with blank clamps, and a pool's null value as a blank value. Any other type, such as `proportional_to`, is refused, naming its path and the editor's types.

**Preview:** The Preview action posts the form Run posts to `POST /api/fleet/preview-distribution`. It answers each component's value per home of `parse_fleet_form(form).homes`, in home order (`fleet_component_values`: the battery 0 for a home without one, the load null when unscaled), or Run's refusal, which the page shows in its error alert. The page writes each card's summary under its editor: each value, to 2 decimals, with its count of homes for at most 8 distinct values so written, else the min, the median (the lower middle home's) and the max. A summary describes the form its preview posted, so a change to the form, typed, imported or loaded from a preset, clears every summary, and the page drops the answer to any preview but the latest.

**Actions:**
- "Run Fleet" -> background job with per-home progress bar
- "Export as YAML" -> generates `ScenarioConfig`-compatible YAML download
- "Preview" -> summary of Run's homes under each card
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

**Fleet distribution:** The builder's PV, battery and load cards are the Fleet Simulator's distribution editors, and start at the fleet page's distributions, `page_limits().components[...].start`. Validate and the YAML preview post the same component blocks as the fleet page, and `builder_form_errors` reads them with `read_form_fleet` at the form's own paths. "Load from File" loads each spec through `DistributionEditor.load` at its path in the file, `fleet_distribution.<component>.<field>`, and refuses a type the editor does not hold, as the fleet import does.

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
| Type | badge (home/fleet) | yes | dropdown |
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
  - Radar chart comparing efficiency ratios (self-consumption, grid dependency, export ratio, and PV stored in battery, the share of generation the battery stored from PV). An axis that a compared run has no figure for, such as a fleet run's PV stored in battery, is left out, and a note names the run.
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

The as-built chart colours are the `chart` section of `src/solar_challenge/web/static/src/theme-tokens.json`, which `src/solar_challenge/web/charts.py` loads into `COLOUR_PALETTE`, the palette the Plotly figures read. They are not Tailwind theme colours: Plotly takes colour strings, not classes.

The dashboard's UI colours are the `tailwind` section of the same token file. It holds `primary`, the accent, and the roles `warning`, `status.<run status>` and `component.<fleet component>`, each named by a built-in Tailwind palette. `src/solar_challenge/web/tailwind.config.js` defines each palette under its role's name, so a template writes `bg-status-running-100`, never the palette's own name, and the token file stays the one home of each role's colour. The build fails, naming the roles at fault, when a role names no built-in palette or two roles take one name, such as a `status-running` role beside the `status` group's `running`. A run status is drawn in its role's palette wherever the dashboard shows it, in its badge and in the progress tracker, so a new run status's colour is one key in the `status` group, plus the classes that apply it.

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
   - Drawn for a run whose window covers at least 90 calendar days; a shorter run's card names the rule and the run's days

6. **Financial Breakdown**
   - Type: Dual-axis chart
   - Primary Y: daily cost bars (import cost red, export revenue green)
   - Secondary Y: cumulative net cost line
   - Only shown when tariff is configured

7. **Seasonal Comparison**
   - Type: Grouped bars
   - Groups: Winter (Dec-Feb) vs Summer (Jun-Aug)
   - Metrics: generation, demand, self-consumption ratio, grid dependency
   - Drawn for a run whose window covers at least 180 calendar days; a shorter run's card names the rule and the run's days

8. **Heat Pump Analysis** (conditional)
   - COP vs outdoor temperature scatter plot
   - Heating load vs degree-days line chart
   - Load share pie chart (heat pump vs base household)
   - Only shown when heat pump is configured
   - Drawn after the Seasonal Comparison in the Analysis tab, each chart full width below the last, as every tab stacks its charts

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
    type TEXT NOT NULL,            -- 'home', 'fleet'
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
