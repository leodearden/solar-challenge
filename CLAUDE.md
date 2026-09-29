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
uv run --extra dev pytest tests/interpreter_matrix

# Browser e2e suite: what the offline lane's e2e job runs after every merge
# (~3.5 min); the per-task verify never runs it
uv run --extra dev --extra web --extra e2e pytest tests/e2e -m 'not slow' -p no:cacheprovider

# CLI entry point
solar-challenge --help
```

## Architecture

The source lives in `src/solar_challenge/` with a setuptools build (`pyproject.toml`). The CLI entry point is `solar_challenge.cli:app` (Typer).

### Simulation Pipeline

The simulation flows through these core modules:

1. **`location.py`** — Frozen dataclass for geographic coordinates (Bristol default: 51.45°N, 2.58°W)
2. **`weather.py`** — Fetches TMY/hourly irradiance from PVGIS via pvlib; caches results to disk (MD5-keyed by location)
3. **`pv.py`** — Models PV generation using pvlib; interpolates hourly output to 1-minute resolution
4. **`load.py`** — Generates household consumption profiles; optional stochastic mode via richardsonpy (UK CREST model), fallback to Ofgem TDCV benchmarks
5. **`battery.py`** — Tracks state of charge with configurable power limits, efficiency, and SOC constraints
6. **`flow.py`** — Per-timestep energy dispatch: self-consumption → battery charge → grid export; grid import for shortfalls
7. **`home.py`** — Orchestrates a single home simulation combining PV + Load + Battery + Weather → `SimulationResults`
8. **`fleet.py`** — Runs multiple homes in parallel via `ProcessPoolExecutor`; aggregates results

### Configuration System (`config.py`, ~1500 lines)

The largest module. Key concepts:
- **Distribution types** for fleet diversity: `WeightedDiscreteDistribution`, `NormalDistribution`, `UniformDistribution`, `ShuffledPoolDistribution`, `ProportionalDistribution`
- **`ScenarioConfig`** — Complete simulation specification parsed from YAML
- **Parameter sweeps** — Geometric/linear sweep specs with cross-sweep parallel execution
- **Variable substitution** — `${VAR}` syntax in config files
- **`generate_homes_from_distribution()`** — Creates heterogeneous fleet configs from distributions

### CLI (`cli/`)

Typer-based with subcommands: `home run|quick`, `fleet run|sweep`, `config template|validate`, `validate`.

### Output & Validation

- `output.py` — CSV export and markdown summary reports
- `validation.py` — Energy balance checks, generation/consumption sanity validation

## Key Patterns

- **Frozen dataclasses** throughout for immutability (config objects, Location, etc.)
- **Validation in `__post_init__`** — Domain constraints enforced at construction time
- **mypy strict mode** enabled; pvlib/pandas/numpy/yaml have `ignore_missing_imports`
- **Reproducible simulations** via per-home seeding (seed parameter in configs)
- **Scenario files** in `scenarios/` (YAML) — e.g., `bristol-phase1.yaml` defines a 100-home fleet

## Optional Dependencies

- `stochastic` extra: `richardsonpy` for realistic UK load profiles
- `web` extra: Flask + Plotly for dashboard

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
- Orchestrator verify uses `uv run --extra dev …` (worktree-safe; the local
  `venv/` is not present inside task worktrees).
- After every merge, the offline lane re-runs the verify suite on each admitted
  Python minor other than the pin (`tests/interpreter_matrix`). A fix task it
  files names the interpreter in its failing node-id, e.g.
  `...test_verify_suite_passes_on_python[3.14]`; reproduce it by running that node-id.
- The lane's `e2e` job runs the non-slow Playwright suite after every merge. A
  fix task it files names the failing e2e node-ids, e.g.
  `tests/e2e/test_history.py::<test>[chromium]`, or `e2e::nonzero-exit` when
  the red run printed no failing node-id (it hit the job's `timeout`, or pytest
  could not start). Reproduce with
  `uv run --extra dev --extra web --extra e2e pytest <node-id> -p no:cacheprovider`.
  The browser comes from `~/.cache/ms-playwright`, which the sandbox cannot
  write, so the playwright locked in `uv.lock` must match an installed
  chromium-headless-shell. This shows the revision it needs:
  `uv run --extra e2e playwright install --dry-run chromium-headless-shell`.
  Installing it (the same command without `--dry-run`) has to happen outside
  the sandbox.
