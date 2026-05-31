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

- **Canonical `project_id`: `my_solar_challenge`** — the directory name is
  hyphenated (`my-solar-challenge`) but the canonical id uses underscores.
  Always use this exact id for fused-memory writes and task operations; the
  dashboard may display the hyphenated form.
- Route **all** task operations through the **fused-memory MCP** with
  `project_root: "/home/leo/src/my-solar-challenge"` — never edit task state
  directly.
- Write-tag memory operations with `project_id: "my_solar_challenge"` and a
  descriptive `agent_id`.
- Config lives at the repo root: `orchestrator.yaml` (+ `.mcp.json`, `.envrc`).
  Escalation MCP runs on port **8106**; fused-memory is shared on 8002.
- Orchestrator verify uses `uv run --extra dev …` (worktree-safe; the local
  `venv/` is not present inside task worktrees).
