# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Solar Challenge is a Python energy flow simulator for domestic PV and battery systems, modeling 100-home fleets in the Bristol community energy project. It simulates solar PV generation (via pvlib/PVGIS), battery storage, and household consumption at 1-minute resolution.

## Commands

```bash
# Install (editable, with dev dependencies)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_battery.py -v

# Run a specific test
pytest tests/unit/test_battery.py::TestBatteryConfig::test_default_config -v

# Type checking
mypy src/solar_challenge

# Test coverage
pytest --cov=src/solar_challenge

# Interpreter matrix: the orchestrator verify on every admitted Python minor
# except the .python-version pin (one case per minor, ~6-10 min each)
uv run --locked --extra dev pytest tests/interpreter_matrix

# Browser e2e suite: what the offline lane's e2e job runs after every merge
# (~3.5 min); the per-task verify never runs it
uv run --locked --extra dev --extra web --extra e2e pytest tests/e2e -m 'not slow' -p no:cacheprovider

# PVGIS contract tests: what the offline lane's pvgis job runs after every merge;
# they check PVGIS's live response, so they need network access, and the per-task
# verify never runs them
uv run --locked --extra dev pytest tests/integration/test_pvgis.py -p no:cacheprovider

# CLI entry point
solar-challenge --help
```

## Architecture

The source lives in `src/solar_challenge/` with a setuptools build (`pyproject.toml`). The CLI entry point is `solar_challenge.cli:app` (Typer).

### Simulation Pipeline

The simulation flows through these core modules:

1. **`location.py`** — Frozen dataclass for geographic coordinates (Bristol default: 51.45°N, 2.58°W)
2. **`weather.py`** — Fetches PVGIS's TMY (v5_3) via pvlib and scales its irradiance to PVGIS's 2005-2020 mean annual GHI (`docs/tmy-irradiation-scaling.md`); caches the result to disk (MD5-keyed by location)
3. **`pv.py`** — Models PV generation using pvlib; interpolates hourly output to 1-minute resolution
4. **`load.py`** — Generates household consumption profiles scaled to an annual total (Ofgem TDCV by household size, unless set explicitly); stochastic mode via richardsonpy (UK CREST model, a core dependency), with a defensive fallback to the deterministic Elexon Profile Class 1 shape
5. **`battery.py`** — Tracks state of charge with configurable power limits, efficiency, and SOC constraints
6. **`flow.py`** — Per-timestep energy dispatch: self-consumption → battery charge → grid export; grid import for shortfalls
7. **`home.py`** — Orchestrates a single home simulation combining PV + Load + Battery + Weather → `SimulationResults`
8. **`fleet.py`** — Runs multiple homes in parallel via `ProcessPoolExecutor`; aggregates results

### Finance & Community Layer

Built on top of simulation results; this is the board-facing decision layer:

- `finance.py` — Per-householder bills, fleet bill distributions, multi-year projections
- `optimize.py` — Discrete install-config sweeps ranked by cost recovery
- `flex.py` / `gridservices.py` — Flexibility value model and grid-services event-window pricing
- `community.py` — Post-hoc peer-to-peer community netting over `FleetResults` (homes are not re-simulated)

### Configuration System (`config.py`)

One of the largest modules. Key concepts:
- **Distribution types** for fleet diversity: `WeightedDiscreteDistribution`, `NormalDistribution`, `UniformDistribution`, `ShuffledPoolDistribution`, `ProportionalDistribution`
- **`ScenarioConfig`** — Complete simulation specification parsed from YAML
- **Parameter sweeps** — Geometric/linear sweep specs with cross-sweep parallel execution
- **Variable substitution** — `${VAR}` syntax in config files
- **`generate_homes_from_distribution()`** — Creates heterogeneous fleet configs from distributions
- **`scenario_writer.py`** — Writes HomeConfigs back as scenario YAML, the inverse of config.py's parsers; change both together

### CLI (`cli/`)

Typer-based; subcommand groups are registered in `cli/main.py` (run `solar-challenge --help` for the authoritative list).

### Output & Validation

- `output.py` — CSV export and markdown summary reports
- `validation.py` — Energy balance checks, generation/consumption sanity validation

## Key Patterns

- **Frozen dataclasses** throughout for immutability (config objects, Location, etc.)
- **Validation in `__post_init__`** — Domain constraints enforced at construction time
- **mypy strict mode** enabled; pvlib/pandas/numpy/yaml have `ignore_missing_imports`
- **Reproducible simulations** via per-home seeding (seed parameter in configs)
- **Scenario files** in `scenarios/` (YAML) — e.g., `bristol-phase1.yaml` defines a 100-home fleet
- **Offline fast tests** — `tests/conftest.py` runs every test not marked `slow` or `e2e` offline, with every fixture it sets up or tears down, whatever its scope: a lookup or connection off the machine fails the test, naming the destination. `get_tmy_data` reads the test's own empty `weather_cache` fixture; seed it with `weather_cache.put(synthetic_june_weather(day), "tmy", location)`, or pass `weather_data`. Mark a test `slow` only if it needs PVGIS itself.

## Optional Dependencies

See `[project.optional-dependencies]` in `pyproject.toml` for the authoritative list. `richardsonpy` is a core dependency (the `stochastic` extra is an empty back-compat alias). The `web` extra covers the dashboard and its assistant; `e2e` covers the Playwright browser suite.

## Dark Factory

This project is a dark-factory orchestrator target (onboarded via `factory-init`).

- **Canonical `project_id`: `solar_challenge`** — the directory name is
  hyphenated (`solar-challenge`) but the canonical id uses underscores.
  Always use this exact id for fused-memory writes and task operations; the
  dashboard may display the hyphenated form.
- Route **all** task operations through the **fused-memory MCP** with
  `project_root: "/home/leo/src/solar-challenge"` — never edit task state
  directly.
- Write-tag memory operations with `project_id: "solar_challenge"` and a
  descriptive `agent_id`.
- Config lives at the repo root: `dark-factory-orchestrator.yaml` (+ `.mcp.json`, `.envrc`).
  Escalation MCP runs on port **8106**; fused-memory is shared on 8002.
- Orchestrator verify uses `uv run --locked --extra dev …` (worktree-safe; the
  local `venv/` is not present inside task worktrees). Every uv command the
  orchestrator runs, verify and offline lane alike, passes `--locked`, so it
  refuses a `uv.lock` that `pyproject.toml` has outgrown instead of silently
  re-locking it. A dependency edit to `pyproject.toml` must commit its `uv lock`
  re-lock in the same change, or verify fails with uv's "The lockfile at
  `uv.lock` needs to be updated" error.
- After every merge, the offline lane re-runs the verify suite on each admitted
  Python minor other than the pin (`tests/interpreter_matrix`). A fix task it
  files names the interpreter in its failing node-id, e.g.
  `...test_verify_suite_passes_on_python[3.14]`; reproduce it by running that node-id.
- The lane's `e2e` job runs the non-slow Playwright suite after every merge. A
  fix task it files names the failing e2e node-ids, e.g.
  `tests/e2e/test_history.py::<test>[chromium]`, or `e2e::nonzero-exit` when
  the red run printed no failing node-id (it hit the job's `timeout`, or pytest
  could not start, e.g. uv refused a stale `uv.lock`). Reproduce with
  `uv run --locked --extra dev --extra web --extra e2e pytest <node-id> -p no:cacheprovider`.
  The browser comes from `~/.cache/ms-playwright`, which the sandbox cannot
  write, so the playwright locked in `uv.lock` must match an installed
  chromium-headless-shell. This shows the revision it needs:
  `uv run --extra e2e playwright install --dry-run chromium-headless-shell`.
  Installing it (the same command without `--dry-run`) has to happen outside
  the sandbox.
- The lane's `pvgis` job runs `tests/integration/test_pvgis.py`, the PVGIS
  contract tests, after every merge. They check PVGIS's live response, never a
  cached TMY, so a change in PVGIS's or pvlib's response turns the lane red. A
  fix task it files names `test_pvgis.py` node-ids, or `pvgis::nonzero-exit`
  when the red run printed no failing node-id (it hit the job's `timeout`, or
  pytest could not start, e.g. uv refused a stale `uv.lock`). Reproduce with
  `uv run --locked --extra dev pytest <node-id> -p no:cacheprovider`. If the
  named tests pass, the red was a PVGIS outage that outlasted the run and its
  confirm re-run; it needs no code change. If every test ERRORs at setup of
  `bristol_tmy` and the cause is a connection error, a timeout or an HTTP 5xx,
  PVGIS is still out of reach: retry later before changing code. Any other
  failure means PVGIS's response, or pvlib's mapping of it, has changed.
