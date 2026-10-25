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
pytest tests/unit/test_battery.py::TestBatteryConfigDefaults::test_default_5kwh -v

# Type checking
mypy src/solar_challenge

# Lint: ruff with the rules pyproject.toml's [tool.ruff.lint] selects; the
# verify runs it through tests/unit/test_lint.py
uv run --locked --extra dev ruff check src/solar_challenge

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

# Tailwind rebuild: after editing tailwind.config.js, static/src/theme-tokens.json's
# tailwind section, static/src/input.css, a template or a script, rebuild
# static/dist/style.css and commit it; in a sandbox
# that cannot write ~/.npm, give npm ci `--cache /tmp/<dir>`
cd src/solar_challenge/web && npm ci && npm run build:css

# Favicon rebuild: after editing static/src/theme-tokens.json's tailwind
# primary, tailwind.config.js or build-favicon.js, rebuild
# static/dist/favicon.svg, the brand sun drawn in the theme's primary-500, and
# commit it
cd src/solar_challenge/web && npm ci && npm run build:favicon

# Stylesheet build check: what the offline lane's css-build job runs after every
# merge; it rebuilds the stylesheet and the favicon with npm and compares the
# Tailwind license texts beside them with the locked tailwindcss package's, so it
# needs npm and network access, and the per-task verify never runs it
uv run --locked --extra dev pytest tests/css_build -p no:cacheprovider

# Newest-releases check: what the offline lane's newest-releases job runs after
# every merge (~15-20 min); it upgrades a scratch copy's uv.lock from PyPI, so it
# needs network access, and the per-task verify never runs it
uv run --locked --extra dev pytest tests/newest_releases -p no:cacheprovider

# CLI entry point
solar-challenge --help
```

## Architecture

The source lives in `src/solar_challenge/` with a setuptools build (`pyproject.toml`). The CLI entry point is `solar_challenge.cli:app` (Typer).

### Simulation Pipeline

The simulation flows through these core modules:

1. **`location.py`** — Frozen dataclass for geographic coordinates (Bristol default: 51.45°N, 2.58°W)
2. **`weather.py`** — Fetches PVGIS's TMY (v5_3) via pvlib and scales its irradiance to PVGIS's 2005-2020 mean annual GHI (`docs/tmy-irradiation-scaling.md`); caches the result to disk (MD5-keyed by location)
3. **`pv.py`** — Models PV generation using pvlib, its cells at NOCT-SAM's temperature from each module's own NOCT and efficiency (`docs/pv-cell-temperature.md`), less PVWatts v5's default system losses on each array's DC power (`docs/pv-system-losses.md`); a set `module_efficiency` or `temperature_coefficient` derives the module from its template (`docs/pv-module-settings.md`); interpolates hourly output to 1-minute resolution
4. **`load.py`** — Generates household consumption profiles scaled to an annual total (the simulator's own default by household size, `OFGEM_TDCV_BY_OCCUPANTS`, unless set explicitly); stochastic mode via richardsonpy (UK CREST model, a core dependency), with a defensive fallback to the deterministic Elexon Profile Class 1 shape
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
- **Component block tables** — `PV_BLOCK`, `BATTERY_BLOCK`, `LOAD_BLOCK`, `HEAT_PUMP_BLOCK`, `EV_BLOCK` and `LOCATION_BLOCK` hold each block's keys in field order, the fields with no YAML form, sub-blocks and when-omitted values. A new dataclass field is placed in its table; `tests/unit/config/test_component_blocks.py` (T1) fails until it is
- **`scenario_writer.py`** — Writes HomeConfigs back as scenario YAML, the inverse of config.py's parsers; both read config.py's component block tables, so a field's key is declared once

### CLI (`cli/`)

Typer-based; subcommand groups are registered in `cli/main.py` (run `solar-challenge --help` for the authoritative list).

### Output & Validation

- `output.py` — CSV export and markdown summary reports
- `validation.py` — Energy balance checks, generation/consumption sanity validation

## Key Patterns

- **Frozen dataclasses** throughout for immutability (config objects, Location, etc.)
- **Validation in `__post_init__`** — Domain constraints enforced at construction time
- **mypy strict mode** enabled; pvlib/pandas/numpy/yaml have `ignore_missing_imports`
- **pytest deprecations are errors** — `filterwarnings` in `pyproject.toml` turns every `PytestDeprecationWarning` into an error in every run, so the suite keeps running on the pytest releases the `dev` extra's range admits (`tests/unit/test_pytest_deprecations_are_errors.py` says why). Fix the use the message names, e.g. parametrize over a list or tuple, not an iterator; if the use is in a plugin's code, raise that plugin's floor to a release without it. Do not filter the warning out. A pytest newer than `uv.lock`'s can flag a use the locked one passes.
- **Floors are the lock** — every requirement in `pyproject.toml`'s `[project].dependencies` and extras declares `name>=<the version uv.lock pins>`, so a consumer that re-locks gets at least the releases this repo tests; `tests/unit/test_dependency_floors.py` fails otherwise, naming the requirement, its table, the locked version and the fix. A dependency edit declares its floor at the version `uv lock` picks, in the same change: `uv add <dist>` (with `--optional <extra>` for an extra) writes such a floor itself (probed offline with uv 0.11.6). After a re-lock moves a dependency (e.g. `uv lock --upgrade-package <dist>`), raise its floor to the new pin and run `uv lock` again, which then changes only the specifier. `[build-system].requires` is outside the rule, because `uv.lock` does not lock build requirements.
- **Reproducible simulations** via per-home seeding (seed parameter in configs)
- **Scenario files** in `scenarios/` (YAML) — e.g., `bristol-phase1.yaml` defines a 100-home fleet
- **Offline fast tests** — `tests/conftest.py` runs every test not marked `slow` offline, the e2e suite's included, with every fixture it sets up or tears down, whatever its scope: a lookup or connection off the machine fails the test, naming the destination. So does an HTTP(S) request from a child process the test starts: the guard points the child's proxy variables at a refusing proxy on this machine and leaves only this machine in `NO_PROXY`, and uv, curl, and Python's requests and urllib honour those variables. `default_weather()` reads the test's own empty `weather_cache` fixture, in the test and in a child process that inherits its environment, since the window names its directory in `SOLAR_CHALLENGE_WEATHER_CACHE_DIR`; seed it with `weather_cache.put(synthetic_june_weather(day), "tmy", location)`, or pass `simulate_home` a `weather` provider. A test that needs Bristol's real TMY reads the PVGIS one committed under `tests/fixtures/weather_cache` through `WeatherCache(cache_dir=...)`, as `tests/integration/test_pv_performance_ratio.py` does. In `tests/e2e`, the live server's jobs read the weather cache that `tests/e2e/conftest.py`'s `live_server_weather` returns, which `_e2e_app` names in `SOLAR_CHALLENGE_WEATHER_CACHE_DIR` only while it builds the app: `synthetic_tmy()` at every `LOCATION_PRESETS` location, so a job at any other site reaches the network and fails its test. Mark a test `slow` only if it needs a live service: PVGIS; PyPI, from which each interpreter-matrix case provisions its interpreter's environment; the npm registry, from which the css-build check installs Tailwind; or the Anthropic API, which `tests/unit/web_assistant/test_chat.py::TestChatLiveSmoke` posts to through the assistant's chat endpoint. The per-task verify never runs a slow test, so each must run in an offline-lane job's suite or be listed, with the service it needs, in `tests/unit/test_offline_lane_contracts.py`'s `SLOW_TESTS_NO_LANE_JOB_RUNS`; otherwise `tests/unit/test_offline_lane_contracts.py::test_every_slow_test_runs_in_a_lane_job_or_is_listed_as_one_no_lane_job_runs` fails. Run a uv command that resolves from the package index with `UV_OFFLINE=1`, reading the index from uv's cache, as `tests/unit/test_stale_uv_lock.py` and the wheel build in `tests/integration/test_external_install.py` do. A test that needs third-party packages installed takes them from `uv.lock`, with `uv sync --locked` into a temporary `UV_PROJECT_ENVIRONMENT`, as `tests/integration/test_external_install.py`'s consumer environment does: the verify's own locked sync has already cached every wheel the lock pins, while an offline resolution of requirement ranges reads only the index pages some earlier online resolution left in uv's cache. When that cache is cold, newly cleaned or behind a dependency change, run `uv lock --dry-run --refresh` once with network access for the stale-lock probes; for the external install's wheel build, or for a uv probe that needs a wheel the cache lacks (e.g. a dependency new to the `e2e` extra), run the failing uv command once with network access.

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
  The reason for each of its settings is in `docs/orchestrator-config.md`.
- Orchestrator verify uses `uv run --locked --extra dev …` (worktree-safe; the
  local `venv/` is not present inside task worktrees). Every uv command the
  orchestrator runs, verify and offline lane alike, passes `--locked`, so it
  refuses a `uv.lock` that `pyproject.toml` has outgrown instead of silently
  re-locking it. A dependency edit to `pyproject.toml` must commit its `uv lock`
  re-lock in the same change, or verify fails with uv's "The lockfile at
  `uv.lock` needs to be updated" error.
- Merge verifies run on `leo-laptop` first, and on this workstation when the
  laptop is busy, benched or unreachable (`verify_runners` and
  `verify_host_policy` in `dark-factory-orchestrator.yaml`). A merge-verify red
  whose `merge_verify` event names runner `laptop`, and which does not
  reproduce here, may come from the laptop's environment.
  `docs/laptop-merge-verify.md` says how to reproduce it there and how to send
  merge verifies back to this host.
- An offline-lane job whose suite needs a live service declares, as its
  `outage_probe` in `dark-factory-orchestrator.yaml`, `scripts/outage_probe.py`
  naming that service; the script's docstring says what counts as an outage and
  what each service is asked. After a red run the lane runs the probe. When it
  reports an outage, the lane raises one escalation naming the service instead
  of filing a fix task, and closes it once the probe passes again. Check a
  service as the lane does with
  `uv run --locked --extra dev python scripts/outage_probe.py <service>`, whose
  `--help` lists the services.
- After every merge, the offline lane re-runs the verify suite on each admitted
  Python minor other than the pin (`tests/interpreter_matrix`). A fix task it
  files names the interpreter in its failing node-id, e.g.
  `tests/interpreter_matrix/test_verify_suite.py::test_verify_suite_passes_on_python[3.14]`;
  reproduce it by running that node-id. A red case's failure message, in the
  pass's `detect.log` under the main checkout's
  `data/orchestrator/offline-lane/interpreter-matrix/`, carries the inner verify
  run's ERRORS and FAILURES sections, each failing test's traceback and captured
  output, ahead of the tail of its output: read it before re-running the case.
  Its outage probe asks PyPI
  (`scripts/outage_probe.py pypi`), whose files a case's locked sync downloads
  whenever `uv.lock` changes. If uv could not download from PyPI, retry later
  before changing code.
- The lane's `e2e` job runs the non-slow Playwright suite after every merge. A
  fix task it files names the failing e2e node-ids, e.g.
  `tests/e2e/test_history.py::<test>[chromium]`, or `e2e::nonzero-exit` when
  the red run printed no failing node-id (it hit the job's `timeout`, or pytest
  could not start, e.g. uv refused a stale `uv.lock`). Reproduce with
  `uv run --locked --extra dev --extra web --extra e2e pytest <node-id> -p no:cacheprovider`.
  An e2e test that fails after Chromium failed one of its requests with
  `net::ERR_NETWORK_CHANGED` runs once more and shows as `RERUN`;
  `docs/e2e-network-change-reruns.md` says why.
  The browser comes from `~/.cache/ms-playwright`, which the sandbox cannot
  write, so the playwright locked in `uv.lock` must match an installed
  chromium-headless-shell. This shows the revision it needs:
  `uv run --extra e2e playwright install --dry-run chromium-headless-shell`.
  Installing it (the same command without `--dry-run`) has to happen outside
  the sandbox.
- The lane's `pvgis` job runs `tests/integration/test_pvgis.py`, the PVGIS
  contract tests, after every merge. They check PVGIS's live response, never a
  cached TMY, so a change in PVGIS's or pvlib's response turns the lane red.
  Its outage probe asks PVGIS (`scripts/outage_probe.py pvgis`). A
  fix task it files names `tests/integration/test_pvgis.py` node-ids, or `pvgis::nonzero-exit`
  when the red run printed no failing node-id (it hit the job's `timeout`, or
  pytest could not start, e.g. uv refused a stale `uv.lock`). Reproduce with
  `uv run --locked --extra dev pytest <node-id> -p no:cacheprovider`. The
  failure line a fix task quotes is the traceback's first: for a request PVGIS
  refused, pvlib's JSONDecodeError on PVGIS's HTML error page. The HTTP status
  is at the end of the traceback, in the pass's `detect.log` under the main
  checkout's `data/orchestrator/offline-lane/pvgis/`. If the named tests pass,
  the red was a PVGIS outage that outlasted the run and its confirm re-run; it
  needs no code change. If every test ERRORs at setup of `bristol_tmy` and the
  probe reports an outage, PVGIS is still out of reach: retry later before
  changing code. Any other failure means PVGIS's response, or pvlib's mapping
  of it, has changed.
- The lane's `css-build` job rebuilds the web package's `static/dist/style.css`
  from the committed sources and `package-lock.json` in a scratch copy, and
  fails when the committed file differs. Tailwind scans the raw text of
  templates and `static/js`, so an edit there can change the build too. Its
  outage probe asks the npm registry (`scripts/outage_probe.py npm`), from
  which `npm ci` installs every tarball `package-lock.json` resolves. If npm
  could not reach the registry, retry later before changing code. A fix
  task it files names
  `tests/css_build/test_dist_style_css.py::test_dist_style_css_matches_a_fresh_build_of_its_sources`,
  or `css-build::nonzero-exit` when the red run printed no failing node-id (it
  hit the job's `timeout`, or pytest could not start). The fix is the Tailwind
  rebuild in Commands, then a commit of the stylesheet. The job also rebuilds
  `static/dist/favicon.svg`, which `build-favicon.js` draws in the theme's
  primary-500, and fails when the committed favicon differs. A fix task for
  that names
  `tests/css_build/test_dist_style_css.py::test_dist_favicon_svg_matches_a_fresh_build_of_its_sources`.
  The fix is the favicon rebuild in Commands, then a commit of the favicon. The
  job also fails when a license text beside the stylesheet in `static/dist` is
  not byte for byte the file of the locked tailwindcss package that
  `tests/_tailwindcss_license_copies.py` names for it. A fix task for that names
  `tests/css_build/test_dist_style_css.py::test_dist_license_text_matches_the_locked_tailwindcss_package[<file>]`,
  `<file>` being the stale copy. The fix is the `cp` its failure message gives,
  from `node_modules/tailwindcss` after `npm ci` in `src/solar_challenge/web`,
  then a commit of the copy. Reproduce with
  `uv run --locked --extra dev pytest <node-id> -p no:cacheprovider`. To change
  the Tailwind version, run `npm install tailwindcss@<version>`, which rewrites
  `package-lock.json`, then rebuild and copy each license text from the new
  `node_modules/tailwindcss`.
- The lane's `newest-releases` job re-runs the verify suite in a scratch copy
  of the tree whose `uv.lock` is upgraded to the newest releases
  `pyproject.toml`'s ranges admit, the releases a consumer that re-locks
  installs. A red there usually comes from an upstream release, not from the
  merged commit in the fix task's suspect range. Its outage probe asks PyPI
  (`scripts/outage_probe.py pypi`). A fix task it files names
  `tests/newest_releases/test_verify_suite_on_newest_releases.py::test_verify_suite_passes_on_the_newest_releases_the_dependency_ranges_admit`,
  or `newest-releases::nonzero-exit` when the red run printed no failing
  node-id (pytest could not start, e.g. uv refused a stale `uv.lock`). Its
  failure message, in the pass's `detect.log` under the main checkout's
  `data/orchestrator/offline-lane/newest-releases/`, lists the releases
  `uv lock --upgrade` moved, then the inner run's ERRORS and FAILURES sections,
  then the tail of its output, which names the failing tests. If it moved none,
  the message says so: the red then comes
  from the tree, not from an upstream release. Make the code or the test work
  on both the locked and the new release; bound that dependency's range in
  `pyproject.toml`, committing the `uv lock` re-lock with it, only when the
  release itself is broken. A re-lock that moves a direct dependency raises
  that dependency's floor to its new pin in the same change, as the "Floors
  are the lock" bullet in Key Patterns says; the lane deselects the floor
  test, whose rule its upgraded copy breaks by design. Fix a pytest
  deprecation error as the "pytest
  deprecations are errors" bullet in Key Patterns says. If uv could not reach
  PyPI, retry later before changing code. Reproduce with the newest-releases
  check in Commands; to iterate on one failing test, overlay its one new
  release on the locked environment:
  `uv run --locked --extra dev --extra web --with '<dist>==<new version>' pytest <node-id> -p no:cacheprovider`.
