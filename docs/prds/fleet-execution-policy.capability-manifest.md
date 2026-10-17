# Capability manifest — Fleet execution policy as one value (S16)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/fleet-execution-policy.md`. Each asserted capability binds to one kind of evidence:

- a symbol wired on main (`grep:<file>::<symbol>`);
- a producer upstream of the leaf, in this batch (`producer:<label>`) or filed (`producer:<task id>`);
- a probe whose result was observed (`probe:`);
- a language or library identity (`identity:`).

The YAML twin `fleet-execution-policy.capability-manifest.yaml` carries the mechanical `delivered_check`s.

**Code anchors** verified against main `1fa8f79` (2026-10-16). Probes ran with `uv run --locked --extra dev python` (Python 3.12.3). Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-extent-short`, `producer-downstream` or `rejection-absent`. Every mechanical check was polarity-checked on `1fa8f79`: each `present` pattern is absent today and each `absent` pattern is present today (33 of 33). The sidecar loads under `shared.capability_manifest.load_capability_manifest`.

- **Upstream producers, all pending on 2026-10-16:** 809 (S15 β) for α; 801 (S9 α) for γ; 806, 819 and 820 (S19 β, θ, λ) for δ; task 727 (in progress) for α's integration test files.
- **Held leaf:** ζ is held for S29 and excluded from this batch's `commit_planning` until S29 releases it. It is conditional on lead Q2.
- **Closed key:** fk-e58042aef503 binds no leaf. Task 709 is `done`, and `tests/unit/test_fleet.py` has no slow mark and has the seeded parallel test (re-measured).

---

## α — FleetRunner: one execution value with one fan-out loop (intermediate with its own CLI signal)

| capability asserted | evidence | status |
|---|---|---|
| `FleetRunner`, `FleetSimulator`, `HomeSimulator`, `FleetSimulate`, `HomesDone`, `default_runner` | `producer:α` (new in `fleet.py`; `git grep -E '^class (FleetRunner\|FleetSimulator)'` is empty on `1fa8f79`) | PASS |
| The provider vocabulary the runner prefetches through (D16): `WeatherProvider`, `PrefetchedWeather.fetch`, `default_weather()`, `simulate_home(…, *, weather)` | `producer:809` (S15 β), upstream; 808 transitively | PASS |
| `simulate_home` satisfies `HomeSimulator` | `producer:809`: `simulate_home(config, start, end, validate_balance=True, *, weather)`; an extra defaulted positional parameter keeps a callable compatible with a protocol `__call__` that omits it (`identity:` structural typing) | PASS |
| One fan-out replaces two | `grep:fleet.py::simulate_fleet_iter` and `simulate_multi_sweep_iter` each hold the prefetch, the sequential fallback, `max_workers or min(n, os.cpu_count() or 4)` and the submit/`as_completed` loop | PASS |
| B3: a failure's own exception carries the home | `identity:` `BaseException.add_note` (3.11+; `pyproject.toml` `requires-python = ">=3.11,<3.15"`); `probe:` `ValueError('x').add_note('n')` gives `__notes__ == ['n']` | PASS |
| B3: homes not started are cancelled; at most 3 of 5 start with `max_workers=1` | `probe:` `ProcessPoolExecutor.shutdown` takes `cancel_futures`; `concurrent.futures.process.EXTRA_QUEUED_CALLS == 1`, so the call queue holds `max_workers + 1` items; the test asserts fewer than 5 | PASS |
| B3, B1 under spawn/forkserver: workers can import the fakes | `grep:tests/__init__.py` makes `tests` a package; task 709's forkserver and spawn tests already run workers from this tree; the fakes live in an importable helper (`tests/_fleet_runner.py`), not in a test function | PASS |
| B4: a home that fails at simulation time, through the real CLI path | `grep:home.py::_hourly_weather` raises `ValueError` when `heat_pump_config` is set and the weather is not one year of hourly rows; `grep:config.py::parse_fleet_config` reads a `homes:` list through `parse_home_block`, which reads `heat_pump` (`_parse_heat_pump_config`); `grep:cli/utils.py::handle_errors` maps `ValueError` to "Invalid value:" and exit 1 | PASS |
| B4: a seeded 1-day TMY serves the plain homes | `grep:tests/_synthetic_weather.py::synthetic_june_weather` (24 hourly rows); `grep:tests/conftest.py::weather_cache` | PASS |
| `handle_errors` prints notes | `grep:cli/utils.py::_print_error_verbatim` prints `str(error)` only today (α adds the notes) | PASS |
| B1: seeded parallel equals sequential | `grep:tests/unit/test_fleet.py` holds task 709's seeded stochastic test under forkserver and spawn (commit `e82ac3c`); α ports it onto `FleetRunner` | PASS |
| Removed names are not frozen | `grep:src/solar_challenge/__init__.py::__all__` exports only `FleetConfig` and `FleetResults` from fleet | PASS |
| Callers to repoint | `grep:` `simulate_fleet` imported in `finance.py` (2 function-local), `optimize.py`, `config.py` (`run_parameter_sweep`) and `cli/utils.py` (`CliFleetSimulator`'s default); `simulate_fleet_iter`/`simulate_multi_sweep_iter`/`collect_multi_sweep_results` only in `cli/fleet.py` | PASS |

## β — One CLI invocation: the runner and `--quiet` on Click's context (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `FleetRunner`, `default_runner`, `FleetSimulator` | `producer:α`, upstream | PASS |
| Click context object inherited by subcommands after the root callback runs | `identity:` Click `MultiCommand.invoke` runs the group callback before `cmd.make_context(..., parent=ctx)`, whose `obj` defaults to the parent's; `grep:` `Context.ensure_object` and `find_object` in the locked click | PASS |
| Root options on the callback | `grep:cli/main.py::main` already takes `--quiet` and `--version` as Typer options | PASS |
| `--workers 0` refused naming the option | `identity:` `typer.Option(min=1)` makes Click raise a usage error (exit 2) naming the option | PASS |
| B7: `invoke_cli` reaches every simulating command | `grep:tests/_cli_fleet_simulator.py::invoke_cli` passes `obj=`; after β every simulating command reads `invocation(ctx)` (sidecar check `fleet-commands-read-the-invocation`) | PASS |
| B7: `home run`'s parity cases without a module patch | `grep:tests/unit/test_cli.py::TestHomeRunFullConfigParity` patches `_cli_home_module.simulate_home` today; β's runner `simulate_home` receives the `HomeConfig` | PASS |
| B9: quiet is per invocation | `grep:cli/utils.py::set_status_quiet` mutates `status_console.quiet`; `grep:tests/unit/test_cli.py::TestQuietOption`'s autouse fixture restores it (the reason it exists, by its docstring) | PASS |
| Fleet-level fakes still work for finance CLI tests | `grep:tests/_cli_fleet_simulator.py::invoke_finance_run` answers every simulation with one `FleetResults`; the context holds the `FleetSimulator` protocol, so an `answering(...)` fake implements it | PASS |

## γ — Finance and optimize require their simulator (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `FleetSimulate` type | `producer:α`, upstream | PASS |
| `project_multi_year`'s age simulation is S9 α's code | `producer:801` (S9 α), upstream: γ edits the same function after it | PASS |
| B10: the defaults exist today | `grep:finance.py::project_multi_year` and `optimize.py::run_sweep`: `if simulate is None` | PASS |
| B10: few callers pass none | `grep:` 2 `project_multi_year`, 1 `solve_cost_recovery_rate` (ζ's) and 1 `run_sweep` call in tests pass no `simulate` (`test_finance_calibration.py`, `test_cost_recovery_calibration.py`, `test_optimize_sweep.py`) | PASS |
| B10: finance stays pvlib-free | `probe:` `import solar_challenge.finance` leaves `pvlib` out of `sys.modules`; `optimize`, `fleet` and `config` load it; `FleetSimulate` is imported under `TYPE_CHECKING` | PASS |

## δ — The dashboard: injected job manager, one shutdown, fleet jobs through the runner (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `FleetSimulator`, `default_runner`; `CliInvocation` for `web start` | `producer:α`, `producer:β`, upstream | PASS |
| `JobManager(storage, …)`; the store built inside `create_app` | `producer:806` (S19 β), upstream | PASS |
| `StoreLock.release()`; lock before recovery | `producer:820` (S19 λ), upstream | PASS |
| B12: a progress checkpoint raises `_JobCancelled`, which the runner propagates | `producer:819` (S19 θ), upstream; `producer:α` (I5, B5) | PASS |
| `Database` for the holder | `producer:805` (S19 α), upstream of 806 | PASS |
| B14: a CLI child script can pass `obj` to the Typer app | `probe:` `typer.Typer.__call__` forwards keyword arguments to Click's `Command.main`, whose `**extra` reaches `make_context`, so `obj=` sets the context object; `grep:tests/unit/test_cli_web.py` runs the CLI in a child today | PASS |
| B15: the sites exist today | `grep:` 10 `extensions["job_manager"] =` writes in tests; `web/jobs.py::_active_managers`, `live_managers`, `shutdown_all_managers`; `web/app.py::create_app` `atexit.register`; `tests/conftest.py::_live_job_managers` reads `sys.modules` | PASS |
| No import cycle for the holder | `grep:web/shared.py` imports `web.jobs` and `web.storage`; `web/app.py` imports the blueprints, which import `shared`. So the holder lives in a new `web/dashboard.py` that imports no blueprint | PASS |

## ε — The age-0 fleet simulated once per `finance run` (L10) (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `FleetSimulate`; `CliInvocation` in `cli/finance.run` | `producer:α`, `producer:β`, upstream | PASS |
| B16: four age-0 simulations today | fk-4ddab794283a's trace at `7dfea36` (`cli/finance.run`'s bill run; `project_multi_year` age 0; `solve_cost_recovery_rate`'s inner projection; its outlay run); `git diff 7dfea36..1fa8f79 -- src/solar_challenge/finance.py src/solar_challenge/cli/finance.py` is empty | PASS |
| B16: those fleets match under the rule | `probe:` on `bristol-phase1.yaml` and `bristol-with-evs.yaml`, `finance._aged_homes(homes, 0)` equals the configured homes once each battery's `soh` is `Battery(config).soh`; raw equality fails only on `soh` (`None` against `1.0`); the solve's outlay fleet equals the projection's age 0 as is; `bristol-phase1-aged.yaml` stays unequal | PASS |
| B16: the windows match | `grep:config.py::SimulationPeriod.get_start_timestamp`/`get_end_timestamp` localise the same date strings the CLI passes to `pd.Timestamp(…, tz=…)`; equal Timestamps | PASS |
| B16: SEG threading leaves the homes equal | `grep:cli/finance.py::run` sets `SEGTariff(name="", rate)` on every home; `grep:finance.py::_reconcile_seg_homes` keeps a home whose rate is close and fills only `None` | PASS |
| The starting-SOH rule has one home | `grep:battery.py::Battery.__init__` resolves `config.soh`, else `compute_soh(config.system_age_years, 0.0, …)`; `Battery.soh` is public; `probe:` `Battery(BatteryConfig(5.0)).soh == 1.0 == Battery(replace(…, soh=1.0)).soh` | PASS |
| No added memory | the reuse returns `results.per_home_results`, which `cli/finance.run` already holds for the whole command; `probe:` 88 bytes per minute row, about 46 MB per home-year, so a cache of other fleets is ruled out | PASS |

## ζ — Retire the solve's implicit simulator and export the runner (held)

| capability asserted | evidence | status |
|---|---|---|
| `project_multi_year` already requires its simulator | `producer:γ`, upstream | PASS |
| The frozen form today | `grep:tests/unit/test_public_api_surface.py::FROZEN_SURFACE` pins `solve_cost_recovery_rate`'s `simulate: Optional[Callable[...]] = None` | PASS |
| `FleetRunner`'s frozen form is stable | `probe:` `surface_form` of a frozen dataclass whose field defaults to a function prints `<function … at 0x…>`; `home_simulator` has no default (decision 3), so the form prints no address | PASS |
| Release window | S29 releases it (`x_seam_wait`); D4, D29 | PASS |
