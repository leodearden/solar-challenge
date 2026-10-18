# Fleet execution policy as one value

**Status:** authored 2026-10-16 (program `review-all-solar_challenge-20261013`, stream S16, wave 2, upstream S15); not yet committed or decomposed. Contract-first (B + H). Binding rulings: D16 (the frozen `FleetRunner` owns weather prefetch per location through S15's provider), L10 (S16 owns the four age-0 simulations the per-age grid-services income needs), D29 (additive frozen edits in-leaf, renames and retirements held for S29), D4, D28.

**Code anchors** verified against main `1fa8f79` (2026-10-16). Main moves fast: cite-by-symbol; re-locate lines at implementation time.

## Goal

How a fleet is executed is one frozen value, `fleet.FleetRunner`: the weather provider it prefetches through, the home simulator, whether homes run in a process pool and how many workers it uses. Each composition root builds its runner once: the CLI's root callback, the dashboard's root, and tests. Everything below a root receives the runner, or its `simulate` method, and builds none.

What a user sees when this lands:

- `solar-challenge --workers 2 finance run board.yaml` and `solar-challenge --sequential optimize configs board.yaml` honour the worker policy. Today `finance run` and `optimize configs` always fan out to every CPU, because only `fleet run` and `fleet sweep` take `--workers`/`--sequential`. The two options move to the root, so every simulating command, `web start` included, reads them.
- A fleet run whose home fails says which home. `fleet run` on a homes-list file whose third home cannot be simulated prints the error, then `simulating home 2 ('Home C') of fleet 0 ('…')`, and exits 1. Homes not yet started are cancelled. Today the error names no home, and the pool waits for every pending home before raising.
- `finance run --project --cost-recovery` on an unaged scenario simulates its age-0 fleet once. Today it simulates it four times: the bill run, the projection's age 0, the solve's inner projection and the solve's outlay run (L10). On the 100-home board scenario that is three full-fleet simulations fewer per run.
- A dashboard fleet job simulates its homes through the same runner. Its homes run in parallel, with per-home progress, and a deleted run cancels the homes not yet started.
- In-process CLI tests and embedders hand the CLI or the dashboard their own simulator through the context object or `create_app`. Nothing patches a module binding, writes `app.extensions['job_manager']` or mutates a module-global console.

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says | leaf |
|---|---|---|---|
| fk-7e76b4cf2cb2 | medium / weakened | Execution policy (parallelism, worker cap, balance validation, home simulator, progress) is carried by separate mechanisms that do not compose: fleet.py's kwarg tuple, the `simulate` callable injected into finance/optimize, `CliFleetSimulator`, and the web's sequential per-home loop. | α, β, γ, δ |
| fk-f3a20a6d53e0 | medium / confirmed | `fleet run` and `fleet sweep` bypass the documented CLI seam. `fleet run` restates `simulate_fleet`'s assembly to drive a progress bar. | α, β |
| fk-31fd9d5d4c68 | low / confirmed | cli/utils' module docstring states a rule that only 2 of 4 fleet commands follow. | β |
| fk-d89ee8df893c | low / confirmed | `home run`'s parity test patches `cli.home.simulate_home` by attribute, because home commands have no injectable simulator. | β |
| fk-cc292d7ce407 | low / weakened | `--quiet` mutates a module-global Rich console that 30 call sites read implicitly. | β |
| fk-e58042aef503 | medium / confirmed | Five test_fleet classes slow-marked only for weather; no lane-run test of seeded parallel equality. | closed by task 709 (below) |
| fk-f7b19fc4c8b5 | low / confirmed | The pool fan-out is written twice. Neither copy names a failed home or cancels pending homes. | α |
| fk-7bdd33abd0ff | low / confirmed | `create_app` builds `JobManager()` itself, keeps it only in a string-keyed extension and returns no shutdown handle. | δ |
| fk-f6c905f91d32 | low / confirmed | Tests overwrite `app.extensions['job_manager']` after construction. The accessors carry `type: ignore[no-any-return]`. | δ |
| fk-7aaa879bf0ac | low / confirmed | A module-level `WeakSet` registry and an ineffective `atexit` hook. `web start` shuts down every manager in the process although it holds its app. | δ |

### Re-measurement at `1fa8f79` (D28 and the freshness clause)

`git diff 7dfea36..1fa8f79` touches `cli/fleet.py`, `cli/home.py`, `cli/optimize.py`, `home.py` (task 710's split), `optimize.py`, `web/jobs.py`, `web/shared.py` and `tests/unit/test_fleet.py`. `fleet.py`, `finance.py`, `cli/finance.py`, `cli/utils.py`, `cli/main.py`, `web/app.py` and `cli/web.py` are unchanged. Measured on `1fa8f79`:

- **fk-7e76b4cf2cb2 (weakened).**
  - `validate_balance` is on 8 signatures: fleet 5, home 2 (task 710 added the private `_minute_flows`), community 1. `simulate` is on 6: finance `project_multi_year`, `solve_cost_recovery_rate`; optimize `sensitivity_panel`, `_age0_baseline_outlay`, `_evaluate_config`, `run_sweep`.
  - `if simulate is None` defaults: 3 (`finance.project_multi_year`, `finance.solve_cost_recovery_rate`, `optimize.run_sweep`). The two in finance are function-local imports of `fleet.simulate_fleet`.
  - `--workers`/`--sequential` exist on 2 of 4 fleet-simulating commands. `FleetResults` is built from fresh simulations at 4 sites (`fleet.simulate_fleet`, `fleet.collect_multi_sweep_results`, `cli/fleet.run`, `web/jobs._run_fleet_simulation`), plus one rebuild from disk (`web/storage`).
  - No caller in `src` or `tests` passes `validate_balance=False` to a fleet function or to `simulate_home`. The one `False` is `simulate_community`'s (frozen, `test_community.py`).
  - The skeptic's correction holds: `CliFleetSimulator` holds the same callable that finance takes. There are three distinct mechanisms, not four. The finding stands at weakened weight.
- **fk-cc292d7ce407 (weakened).** 30 implicit readers: `print_info` 18, `print_success` 7, `create_progress` 2, `create_fleet_progress` 2, and `cli/web.start`'s direct `status_console.print` 1. Tests patch `status_console` with `monkeypatch.setattr` at 2 sites (`TestQuietOption`'s restore fixture and one display test), not 8. The skeptic's correction holds.
- **fk-e58042aef503.** Task 709 is `done`. `tests/unit/test_fleet.py` has no slow mark, seeds Bristol's TMY through `weather_cache`, and has a seeded stochastic test: each home's parallel results under forkserver and spawn equal its sequential results. Contract §8 step 1 at decompose finds 709 done and the finding absent, so nothing is filed for this key. α ports that test onto `FleetRunner`.
- **fk-f3a20a6d53e0, fk-31fd9d5d4c68, fk-d89ee8df893c, fk-f7b19fc4c8b5, fk-7bdd33abd0ff, fk-f6c905f91d32, fk-7aaa879bf0ac.** Still present as stated: `ensure_object(CliFleetSimulator)` only in `cli/finance.run` and `cli/optimize`, `fleet run`'s assembly copy, `test_cli.py`'s `_cli_home_module` patch, the two fan-out loops, `create_app`'s `JobManager()`, 10 `extensions['job_manager'] =` writes in tests, `_active_managers`, `shutdown_all_managers` and the `atexit` registration.

### Substrate the design rests on (probed on `1fa8f79`, `uv run --locked --extra dev python`, Python 3.12.3)

- `concurrent.futures.process.EXTRA_QUEUED_CALLS == 1`, and `ProcessPoolExecutor.shutdown` takes `cancel_futures`. So with `max_workers=1`, at most three homes start after the first raises (B3).
- `BaseException.add_note` exists on every admitted interpreter (`requires-python >=3.11`).
- `import solar_challenge.finance` leaves pvlib unloaded. `optimize`, `fleet` and `config` load it. So finance must keep fleet out of its module-level imports.
- **L10 premise.** On `scenarios/bristol-phase1.yaml` (100 homes) and `bristol-with-evs.yaml`, `finance._aged_homes(homes, 0)` differs from the configured homes only in each battery's `soh`: `None` against `1.0`. Mapping each battery to `Battery(config).soh` makes the two lists equal. The solve's outlay fleet equals the projection's age-0 fleet as is. On `bristol-phase1-aged.yaml` they stay unequal: the bill run and the projection's age 0 are genuinely different fleets there.
- A frozen dataclass whose field defaults to a function renders, through `tests/_surface_forms.surface_form`, with the function's memory address. That is why `FleetRunner.home_simulator` has no default (decision 3).
- One home-year of `SimulationResults` holds about 46 MB of series data: 88 bytes per minute row, measured on a 1-day run. A 100-home, full-year `FleetResults` is therefore 5–9 GB. That rules out a memo that keeps results the caller does not already hold (decision 8).

## Sketch of approach

1. **α — the runner.** `fleet.py` gains `FleetRunner` (contract below) and its two protocols. One private fan-out loop serves every call. It prefetches weather once per distinct location through the runner's provider (D16, `PrefetchedWeather.fetch`), submits one job per home, and yields `(job index, results)`. A failure re-raises the home's own exception with a note naming the home, and cancels homes not started. `simulate` is `simulate_each` over one fleet. These go: `simulate_fleet`, `simulate_fleet_iter`, `simulate_multi_sweep_iter`, `collect_multi_sweep_results`, `MultiSweepResults` and both worker functions. None is in `__all__`. `fleet run` and `fleet sweep` drive progress through the runner's sink, and `fleet run`'s assembly copy goes. Each other caller of `simulate_fleet` points at `default_runner().simulate` until its own leaf.
2. **β — the CLI invocation.** `CliFleetSimulator` becomes `CliInvocation(runner, quiet)` on Click's context object. The root callback builds it from `--quiet`, `--workers` and `--sequential`, unless the invoker passed one. Every simulating command reads its runner from it: `home run`, `home quick`, `fleet run`, `fleet sweep`, `finance run` and `optimize configs`, and `web start` once δ gives `create_app` its seam. The status helpers read `quiet` from the current invocation, and no module global is mutated.
3. **γ — finance and optimize require their simulator.** `project_multi_year`, `optimize.run_sweep` and `optimize.sensitivity_panel` take `simulate: FleetSimulate` as a required keyword, and their `if simulate is None` defaults go. `solve_cost_recovery_rate`'s frozen `simulate=None` resolves `default_runner().simulate` until ζ.
4. **δ — the dashboard.** `create_app(test_config, *, jobs)` builds its job manager through the given factory, after S19's lock, database and store. The app's collaborators live in one typed `Dashboard` value with one `close()`, which the root that built the app calls. `JobManager` runs home jobs through `runner.simulate_home` and fleet jobs through `runner.simulate`, with per-home progress. The registry, `shutdown_all_managers` and the `atexit` hook go.
5. **ε — the age-0 fleet once (L10).** `fleet.reusing(simulate, results, start, end)` answers a request for a fleet that simulates as `results`' fleet from `results`, re-paired with the asked homes. `cli/finance.run` wraps its runner's `simulate` with the bill run's results before the projection and the solve.
6. **ζ — held for S29.** `solve_cost_recovery_rate`'s `simulate` becomes required, and `FleetRunner` and its protocols join `__all__`, so finance never imports fleet at runtime.

## Resolved design decisions

1. **The policy is one frozen value, built at the roots.** `FleetRunner(weather, home_simulator, parallel=True, max_workers=None)`. The roots are:
   - the CLI root callback;
   - the dashboard's roots: `cli/web.start`, `web.create_app`'s package facade and `web/app.py`'s `__main__`;
   - tests;
   - `default_runner()`, the one place that names the production weather and home simulator.

   Below a root, nothing constructs a runner or resolves a default. The transitional exceptions are `solve_cost_recovery_rate`'s frozen default (until ζ) and `config.run_parameter_sweep` (until S5 deletes it).
2. **`validate_balance` is not a runner field.** No caller in `src` or `tests` sets it to `False` for a home or a fleet (re-measured), so a runner field would have no consumer (G1). The fleet functions that carried it go in α. `simulate_home` keeps its own parameter and default, and `simulate_community`'s is frozen.
3. **`home_simulator` is a required field.** `default_runner()` passes `home.simulate_home`. A function default would put a memory address into the frozen surface form ζ pins (substrate above), and a root should name what it simulates with anyway. Its type is the `HomeSimulator` protocol, `(config, start, end, *, weather) -> SimulationResults`. `simulate_home` satisfies it through its own `validate_balance` default.
4. **Progress is a per-call argument, not a field.** A progress display lives for one command or one job, while a runner lives for a whole root. So `progress: HomesDone | None` is a keyword of `simulate` and `simulate_each` (heuristic 5). It is called in the calling process after each home finishes, with (homes finished, homes in the call). An exception it raises propagates unchanged after homes not started are cancelled. That is how S19 θ's `_JobCancelled` stops a fleet job.
5. **Finance and optimize take the runner's `simulate`, a `FleetSimulate` callable, not the runner object (lead Q1).** `solve_cost_recovery_rate`'s `simulate` keyword is frozen in exactly that callable form. The finance functions need only "simulate this fleet over this window". A required callable is their narrowest interface (heuristic 9), and about 150 test sites already pass one. Each root passes `runner.simulate`, so the policy is honoured by construction. `FleetSimulate` is imported under `TYPE_CHECKING`, which keeps `import solar_challenge.finance` pvlib-free. What goes is the `Optional` default and its resolution: two of the three defaults in γ, the third in ζ. The parameter itself stays.
6. **The CLI's worker options move to the root (lead Q3).** `--workers N` (`min=1`) and `--sequential` join `--quiet` on the root callback, and leave `fleet run` and `fleet sweep`. The runner is then built once per invocation, and every simulating command honours it, `finance run`, `optimize configs` and `web start` included. Per-command options would mean every command derives its own runner. That needs either a concrete `FleetRunner` on the context, which forces home-level fakes on the finance CLI tests that answer with canned `FleetResults`, or a policy-rewriting method on the protocol. The CLI is not frozen. `fleet run f.yaml --workers 2` now fails with Click's "No such option".
7. **The CLI context holds a `FleetSimulator`, the protocol.** Tests pass fleet-level fakes, canned `FleetResults` as today, or a `FleetRunner` with a fake home simulator. An invocation passed by the invoker keeps its own runner, and the root's `--workers`/`--sequential` do not rewrite it: a test owns its simulator. The test helper says so.
8. **L10: reuse what the caller already holds, never cache.** A 100-home, full-year `FleetResults` is 5–9 GB, so a memo of every fleet a command simulates is out. `reusing(simulate, results, start, end)` returns results the caller already holds, so it adds no memory.
   - **Match rule.** It answers a request when `start` and `end` equal its own, and the asked fleet's homes equal `results.home_configs`, once each battery config is compared at the SOH a `Battery` built from it starts at (`Battery(config).soh`). That is battery.py's own rule, not a copy. The `FleetConfig` name is ignored. Any other request goes to `simulate`.
   - **Answer.** `FleetResults(per_home_results=results.per_home_results, home_configs=fleet.homes)`: the same series objects, paired with the homes that were asked for. A per-age reader of `home_configs`, such as S9 α's grid-services income, reads the projection's age-0 configs.
   - **Use.** `cli/finance.run` wraps after its bill run. On an unaged scenario the projection's age 0, the solve's inner projection and the solve's outlay all match, so four age-0 simulations become one. On an aged scenario the bill-run fleet differs, and nothing is reused. That is correct, because the configured fleet is not the projection's new install.
   - **Stochastic loads.** A run of seeded homes gives the same results either way. For unseeded stochastic loads the command's age-0 views now share one draw instead of four independent ones. That is the more coherent reading of one report.
   - **Out of scope.** `optimize configs` runs `project_multi_year` twice per config at the same rate: the solve's inner one and the explicit one. Removing that is S8's projection work (cross-reference), not a runner concern.
9. **A failed home is named on its own exception.** The runner adds a note, `simulating home {i} ({name!r}) of fleet {k} ({fleet name!r})`, and re-raises the same object. Its type is unchanged, so `cli/utils.handle_errors` and the web job's failure path catch what they catch today. `handle_errors` prints each note on its own line under the message. The web stores `str(exc)` as the job message, and the traceback it stores already carries notes.
10. **One shutdown, owned by the root that built the app.** `create_app` stores one `Dashboard(storage, jobs, database, lock)` under one extensions key. `dashboard_of(app)` reads it with one checked lookup. `shared.get_storage`/`get_job_manager`/`get_database` read its fields, with no `type: ignore`. `Dashboard.close(wait=False)` shuts the job manager down, then releases S19's store lock. `cli/web.start` calls it in `finally`. Tests close what they build through the harness that built it. `create_app` still returns the Flask app, so the factory's name stays true (heuristic 1).
11. **`create_app` takes a job-manager factory, `jobs: Callable[[RunStorage], JobManager]`.** S19 builds `RunStorage` inside `create_app`, after the store lock (C1: only `app.py` builds one; C9: recovery after the lock). So `create_app` cannot take a pre-built `JobManager`. A runner alone would leave the web tests that drive an autospecced `JobManager` with no seam. Roots pass `functools.partial(JobManager, runner=…)`, and `web.app.default_jobs` is that with `default_runner()`. Tests pass `lambda storage: mock` or a fake runner.
12. **The dashboard's fleet jobs run in parallel (lead Q5, inform).** They use the root's runner: `default_runner()`, or the CLI invocation's under `web start`. A 100-home fleet job then uses a process pool, as `fleet run` does. Two concurrent jobs (`JobManager`'s two threads) use two pools. `solar-challenge --sequential web start` restores today's sequential loop.
13. **Additive and held surface edits (D29).** α–ε change no frozen form. α removes non-frozen fleet names, with an "Unreleased on main" line and a recipe in the consumption guide. ζ is held for S29 (lead Q2): `solve_cost_recovery_rate`'s `simulate` loses its `None` default, and `FleetRunner`, `FleetSimulator`, `HomeSimulator`, `FleetSimulate` and `HomesDone` join `__all__`. A consumer that today relies on `set_weather_cache` reaching the solve's default, which S15 ε retires at the same bump, passes `FleetRunner(weather=PvgisTmy(WeatherCache(d)), home_simulator=simulate_home).simulate` instead.

## Contract (seam: fleet execution; owner this PRD; readers cli/*, web/jobs, web/app, finance, optimize, tests; upstream S15's provider)

```python
# src/solar_challenge/fleet.py (α; reusing in ε)

FleetSimulate: TypeAlias = Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]
"""Simulates a fleet over a window: what finance and optimize take, a FleetSimulator's simulate."""

HomesDone: TypeAlias = Callable[[int, int], None]
"""Told in the calling process after each home finishes: (homes finished, homes in the call)."""

class HomeSimulator(Protocol):
    def __call__(self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp,
                 *, weather: WeatherProvider) -> SimulationResults: ...

class FleetSimulator(Protocol):
    """How a composition root simulates homes and fleets."""
    def simulate(self, fleet: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp,
                 *, progress: HomesDone | None = None) -> FleetResults: ...
    def simulate_each(self, fleets: Sequence[FleetConfig], start_date: pd.Timestamp, end_date: pd.Timestamp,
                      *, progress: HomesDone | None = None) -> Iterator[tuple[int, FleetResults]]: ...
        # each fleet's index once, with its FleetResults, as its last home finishes
    def simulate_home(self, home: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults: ...

@dataclass(frozen=True)
class FleetRunner:                      # a FleetSimulator
    weather: WeatherProvider            # prefetched once per distinct location per call (D16)
    home_simulator: HomeSimulator       # picklable (top-level) when parallel
    parallel: bool = True
    max_workers: int | None = None      # None: min(homes in the call, os.cpu_count() or 4)
    # __post_init__: ValueError naming max_workers and its value unless it is None or a whole number >= 1

def default_runner() -> FleetRunner:
    """FleetRunner(weather=default_weather(), home_simulator=simulate_home): the runner a root uses when given none."""

def reusing(simulate: FleetSimulate, results: FleetResults,
            start_date: pd.Timestamp, end_date: pd.Timestamp) -> FleetSimulate:
    """simulate, except that a fleet that simulates as results' fleet over the same window is answered
    from results, paired with the asked fleet's homes (decision 8)."""

# src/solar_challenge/cli/utils.py (β)
@dataclass(frozen=True)
class CliInvocation:
    """What one CLI invocation runs with, on Click's context object."""
    runner: FleetSimulator = field(default_factory=default_runner)
    quiet: bool = False
def invocation(ctx: typer.Context) -> CliInvocation: ...      # ctx.ensure_object(CliInvocation)

# src/solar_challenge/web/dashboard.py (δ, new; imports jobs, storage, database, store_lock; no blueprints)
JobManagerFactory: TypeAlias = Callable[[RunStorage], JobManager]
@dataclass(frozen=True)
class Dashboard:
    storage: RunStorage
    jobs: JobManager
    database: Database                  # S19 α
    lock: StoreLock                     # S19 λ
    def close(self, *, wait: bool = False) -> None: ...   # jobs.shutdown(wait=wait), then lock.release()
def dashboard_of(app: Flask) -> Dashboard: ...            # LookupError naming the app when it holds none

# src/solar_challenge/web/app.py (δ)
def create_app(test_config: Mapping[str, Any] | None = None, *, jobs: JobManagerFactory) -> Flask: ...
def default_jobs(storage: RunStorage) -> JobManager: ...  # JobManager(storage, runner=default_runner())

# src/solar_challenge/web/jobs.py (δ, over S19 β's constructor)
class JobManager:
    def __init__(self, storage: RunStorage, max_workers: int = 2, *, runner: FleetSimulator,
                 new_id: Callable[[], str] = ..., clock: Callable[[], float] = ...) -> None: ...
```

| invariant | enforced at construction | enforced at use |
|---|---|---|
| I1. Fleet execution policy has one mechanism: only `fleet.py` submits homes to a pool or assembles `FleetResults` from fresh simulations. | `FleetRunner`'s frozen fields | grep: `ProcessPoolExecutor` and `per_home_results=` in `src` only in `fleet.py` (and `web/storage`'s disk rebuild); B1, B6 |
| I2. A call prefetches each distinct location's weather once, in the calling process, and each job carries only its home's location (D16). | `PrefetchedWeather.fetch` (S15) | B2's counting provider |
| I3. Results come back in each fleet's home order, whatever the completion order; parallel equals sequential for seeded homes. | — | B1 (ported from task 709) under forkserver and spawn |
| I4. A failed home is named on its own exception, and homes not yet started are cancelled. | — | B3, B4 |
| I5. A progress sink's exception propagates unchanged, after homes not yet started are cancelled. | — | B5, B12 |
| I6. `max_workers` is `None` or a whole number ≥ 1. | `FleetRunner.__post_init__`; the CLI option's `min=1` | B8 |
| I7. Every CLI command that simulates reads its runner from the invocation, and no module global carries invocation state. | `CliInvocation` frozen; root callback | grep: no `simulate_home(` or `FleetRunner(` call in `cli/` outside `utils`'s callback; no `status_console.quiet =`; B7, B9 |
| I8. The dashboard has one shutdown, owned by its root; no registry. | `Dashboard.close` | grep: no `_active_managers`, `live_managers`, `shutdown_all_managers` or `atexit` in `web/`; B13, B14 |
| I9. Reuse answers only a fleet that simulates identically over the same window. | `reusing`'s match rule | B16, B17 |
| I10. Finance stays pvlib-free at import and resolves no simulator below the roots (γ; ζ removes the last default). | `FleetSimulate` under `TYPE_CHECKING` | `import solar_challenge.finance` leaves pvlib unloaded (existing probe); B10 |

## Boundary-test sketch (both sides of each seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Seeded parallel equals sequential | task 709's seeded stochastic fleet; `FleetRunner` over `weather_cache`'s Bristol day; forkserver and spawn | each home's `simulate` results, parallel and sequential, equal (`check_exact`), in home order | α |
| B2 | Prefetch once per location | a counting provider over Bristol and Bath, counting in the parent; fleets `[bristol, bath, bristol]` and `[bath]`; parallel | `simulate` of the first calls `get` twice; `simulate_each` of both calls it twice in total; each job's provider holds only its home's location | α |
| B3 | Failed home named, rest cancelled | `parallel=True, max_workers=1`, 5 homes; a home simulator from an importable tests helper that touches a marker file per home, sleeps 0.2 s, and raises `ValueError` for home 0; a sequential runner whose home 2 raises | the `ValueError` itself propagates, with a note naming home 0 and its name; fewer than 5 marker files (at most 3, by `EXTRA_QUEUED_CALLS`); sequentially, homes 3 and 4 never start and the note names home 2 | α |
| B4 | The CLI names the failed home (user-facing) | a homes-list fleet file: two plain homes and a heat-pump home named `Home C`; `weather_cache` seeded with Bristol's 2024-06-21 day; `fleet run --start 2024-06-21 --end 2024-06-21` sequential | exit 1; stderr has `Invalid value:` with the heat-pump year-length refusal, then a line naming home 2 and `'Home C'` (today the message names no home) | α (β moves `--sequential` to the root) |
| B5 | Progress and its exceptions | 3 homes, sequential and parallel | the sink sees `(1,3)`, `(2,3)`, `(3,3)` in the calling process; a sink raising `RuntimeError` on its second call makes `simulate` raise that same `RuntimeError` with no home note | α |
| B6 | Many fleets, one pool | fleets of 2, 1 and 3 homes | `simulate_each` yields indexes 0–2 once each, each `FleetResults` paired with its fleet's homes in order; progress totals 6; `fleet sweep`'s CSVs and summary table unchanged | α |
| B7 | Every command reads the invocation | `invoke_cli` with a recording `FleetSimulator`; no weather seeded; the offline guard on | `home run`, `home quick`, `fleet run`, `fleet sweep`, `finance run` and `optimize configs` exit 0 offline, each through the recorder; `home run`'s parity cases assert the `HomeConfig` the recorder received, with no `monkeypatch` of `cli.home` | β |
| B8 | Root worker policy | `solar-challenge --help`; `--workers 0`; `fleet run f.yaml --workers 2`; the callback's runner builder | the root lists `--workers` and `--sequential`; `--workers 0` exits 2 naming `--workers`; the moved option exits 2 ("No such option"); the runner an uninjected `--sequential --workers 3` invocation gets equals `replace(default_runner(), parallel=False, max_workers=3)`; `FleetRunner(…, max_workers=0)` raises `ValueError` naming `max_workers` | β |
| B9 | Quiet per invocation | two in-process invocations in a row, the first with `--quiet` | the second prints its status lines; `TestQuietOption`'s restore fixture is gone | β |
| B10 | Finance requires its simulator | `make_scenario` from `tests/_finance_builders` | `project_multi_year(scenario, finance)` and `run_sweep(configs)` raise `TypeError` naming `simulate` (today: a hidden `simulate_fleet` on every CPU); every fake-driven test passes unchanged; `import solar_challenge.finance` leaves pvlib unloaded | γ |
| B11 | Dashboard fleet job through the runner | `build_test_app` with `jobs=partial(JobManager, runner=recording_runner)`; `POST /api/simulate/fleet` with 3 homes | the job completes; the recorder saw 3 homes; the progress stream reports each home; `GET /api/history/runs/<id>` shows `completed` | δ |
| B12 | Delete cancels a fleet job (S19 θ seam) | a runner whose home simulator blocks on home 1 of 3 | deleting the run ends the job `cancelled`; home 2 never starts; no run is saved | δ |
| B13 | One shutdown | an app built on `DATA_DIR` d, then `dashboard_of(app).close()` | a later submit is refused; a second `create_app` on d starts (S19 λ's lock released) | δ |
| B14 | `web start` owns its app | the child script runs `app(["web", "start", "--port", p], obj=CliInvocation(runner=<a runner whose home simulator blocks>))` | stopping the server drops queued jobs and lets running ones finish, as `test_cli_web` pins today, with no `request_started` swap and no `extensions` write | δ |
| B15 | No registry, no writes | the tree after δ | no `extensions["job_manager"] =` in `tests`; no `_active_managers`, `live_managers`, `shutdown_all_managers` or `atexit` in `src/solar_challenge/web`; no `sys.modules` reach-in in `tests/conftest.py` | δ |
| B16 | Age-0 fleet once (L10, user-facing) | an unaged 2-home seeded scenario; `invoke_cli(["finance", "run", "--project", "--cost-recovery", f], counting)`, where the counter answers with results that depend only on the asked homes | the counter is asked for the age-0 fleet (homes equal at starting SOH) once (today 4); the report renders the projection and the cost-recovery block | ε |
| B17 | Reuse refuses what differs | `reusing(sim, results, s, e)` | equal homes, `soh` `None` against `1.0` at age 0: no call, and the same series objects come back paired with the asked homes; `soh=0.9` against `None`, a different `end`, an aged PV: each calls `sim` | ε |
| B18 | Retired default (held) | after ζ | `solve_cost_recovery_rate(scenario, finance)` raises `TypeError` naming `simulate`; `solar_challenge.FleetRunner` resolves; the frozen-surface test pins the new forms; finance has no function-local `fleet` import | ζ |

## Pre-conditions for activating

- **S15 β (809)** — `simulate_home(…, *, weather)`, `WeatherProvider`, `PrefetchedWeather.fetch`, `default_weather()` (D16: the runner prefetches through S15's provider). α depends on it. 808 comes in transitively.
- **S9 α (801)** — it rewrites `project_multi_year`'s `_simulate_age` to price each age from the fleet it simulates. γ edits the same function's parameter and default, so γ depends on 801 (finance.py serialised).
- **S19 β (806), θ (819), λ (820)** — `JobManager(storage, …)`, the cancel flag at progress checkpoints, the store lock and its `release()`. δ depends on all three, and on 805 transitively.
- **Task 727 (in progress)** — it rewrites `tests/integration/test_fleet_simulation.py` and `test_ev_fleet.py`, which α moves off `simulate_fleet`. α starts after 727 merges.
- Before filing: contract §8 step 1 for all ten keys. Then cancel pending tasks **740** (fk-d89ee8df893c), **742** (fk-31fd9d5d4c68) and **747** (fk-f7b19fc4c8b5), and deferred **121** (create_app's `atexit`), each with `x_superseded_by` the leaf below (lead Q4). fk-e58042aef503 files nothing (709 done).
- ζ is filed held (`x_seam_wait = {stream: S29, contract: "the surface bump release window"}`) and excluded from this batch's `commit_planning`.

## Cross-PRD relationship

| other stream / task | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S15 Weather (809) | consumes | `WeatherProvider`, `PrefetchedWeather.fetch`, `default_weather()`, `simulate_home(weather=)`; α moves fleet's interim `default_weather()` calls into `default_runner()`, and δ replaces `create_app`'s `partial(simulate_home, weather=default_weather())` with the jobs factory | S15 provider; S16 runner (D16) | α depends on 809 |
| S9 Grid-services (801) | produces for | `project_multi_year` books each age's income from the `FleetResults` its `simulate` returns; γ makes that `simulate` required; ε's reuse returns results paired with the asked (aged) homes, so 801's per-age income at age 0 reads age-0 configs | S9 income; S16 simulator and reuse (L10) | γ depends on 801 |
| S19 Run store (806, 819, 820) | consumes | `JobManager(storage, …)`; the progress checkpoint that raises `_JobCancelled`, which the runner propagates (I5); `StoreLock.release()` called by `Dashboard.close()`; lock → database → store → jobs → recovery order kept inside `create_app` | S19 constructor, lock, cancel; S16 handle and injection | δ depends on 806, 819, 820 |
| S20 Job events | shares `jobs.py` | the fleet job's sink calls the job's progress callback, never job state; S20's `JobStreamPolicy` is one more collaborator, carried by the jobs factory or the `Dashboard` holder, whichever lands second | S20 writer and policy; S16 injection | cross-reference |
| S17 Web request boundary | shares `shared.py` | `get_storage`/`get_job_manager`/`get_database` read `dashboard_of(current_app)`'s fields (δ); S17 moves them beside `web/dashboard.py` | S16 holder; S17 location | order-agnostic |
| S8 Finance partition | consumed by | the `project_multi_year`/solve move carries the required `simulate: FleetSimulate` (γ) and the solve's default (until ζ); optimize's and `finance run`'s duplicated projection at the same rate is S8's to remove | S8 | cross-reference |
| S25 Board reports | consumed by | `cli/finance.run`'s restructure keeps ε's `reusing(…)` wrapper around the invocation's `simulate` | S25 | cross-reference |
| S1 Errors leaf (775) | shrinks | α repoints finance's two function-local `simulate_fleet` imports to `default_runner`; γ deletes `project_multi_year`'s; ζ (or S8's move, if first) deletes the solve's. Each edits its allow-list entry if 775 has landed | each its own | order-agnostic |
| S23 Surface lock | file overlap | ζ edits the `FROZEN_*` tables | S23 module shape | parallel |
| S29 Surface bump | consumes | ζ's retirement and exports; α's Unreleased line (fleet's iterator functions removed, never frozen) | S29 releases ζ | ζ held |
| S5 Scenario grammar | file overlap | `config.run_parameter_sweep` points at `default_runner().simulate` in α if S5 has not deleted it | S5 deletion | order-agnostic |
| S6, S10 (782, 783), S12 | file overlap | `cli/finance.py`, `cli/fleet.py`, `finance.py`; α's B4 trigger is the heat-pump year-length refusal, wherever S12 δ puts it | — | textual only |
| Tasks 739, 746 | file overlap | 739 splits `fleet sweep`'s two modes (α rewrites its simulation half); 746 adds a seed to `FleetConfig`'s constructors | each its own | order-agnostic |

## Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`, its keys in `x_finding_key`, priority = the highest severity among its keys, and file-level `metadata.files`. No key is high or critical, so no leaf joins trigger-chain gate 772.

- **α. FleetRunner: one execution value with one fan-out loop** (intermediate with its own user-facing signal). Files:
  - `fleet.py`: the contract's α half; the deletions in Sketch 1; one private fan-out with the note and the cancel;
  - `cli/fleet.py`: `run` and `sweep` call a runner built locally from their still-present `--workers`/`--sequential` until β; progress through the sink; `run`'s assembly copy goes; `sweep` iterates `simulate_each`;
  - `cli/utils.py`: `handle_errors` prints notes; `CliFleetSimulator`'s default becomes `default_runner().simulate`;
  - one-line repoints in `finance.py` (2 function-local imports), `optimize.py` and `config.run_parameter_sweep`;
  - tests: `tests/unit/test_fleet.py`, `tests/integration/test_fleet_simulation.py`, `tests/integration/test_ev_fleet.py`, `tests/unit/test_marker_registration.py`, a new `tests/_fleet_runner.py` holding picklable home-simulator fakes, `tests/unit/test_cli.py` (B4);
  - docs: `docs/domain-library-consumption.md` (Unreleased: the five names are gone; recipe `default_runner().simulate` / `FleetRunner(...)`), `review/briefing.yaml` (the ProcessPoolExecutor decision's "the weather cache is pre-warmed": workers receive their weather in the job), `CLAUDE.md` (the `fleet.py` line).

  Signal: B4. `fleet run` names the failed home, and homes not started are cancelled (today: no home named, and every pending home runs first). Also B1, B2, B3, B5, B6. `ProcessPoolExecutor` appears once in `src`.

  Prereqs: 809, 727. Unlocks β, γ, δ, ε. Keys: fk-7e76b4cf2cb2, fk-f7b19fc4c8b5, fk-f3a20a6d53e0. Priority medium. Supersedes 747.
- **β. One CLI invocation: the runner and `--quiet` on Click's context** (leaf). Files:
  - `cli/utils.py`: `CliInvocation`, `invocation`; the status helpers read `quiet`; `status_console` and `set_status_quiet` go; the module docstring's rule now says every simulating command;
  - `cli/main.py`: `--workers`, `--sequential`; the invocation built unless injected;
  - `cli/home.py`, `cli/fleet.py` (its options go), `cli/finance.py`, `cli/optimize.py` (`invocation(ctx).runner`); `cli/web.py` (its status line through a helper; δ passes it the runner);
  - tests: `tests/_cli_fleet_simulator.py` (`invoke_cli(argv, simulator)`, and an `answering(simulate)` fake for the callable-passing tests), `tests/unit/test_cli.py` (`TestQuietOption`, the display tests, `TestHomeRunFullConfigParity`), `tests/integration/test_community_fleet.py` (root options), and the `invoke_cli` callers (`test_optimize_cli.py`, `test_finance_flex_cli.py`, `test_cost_recovery_cli.py`, `test_finance_economics.py`, `test_grid_services_events.py`).

  Signal: B7, B8, B9. The root's `--workers` and `--sequential` build the invocation's runner, which `finance run` and `optimize configs` read (today those two always use every CPU). `fleet run` without a seeded weather cache runs a test's fake (today `invoke_cli(['fleet','run',…], fake)` ignores the fake). No `monkeypatch` of `cli.home` or `status_console` remains.

  Prereq α. Unlocks δ, ε. Keys: fk-f3a20a6d53e0, fk-31fd9d5d4c68, fk-d89ee8df893c, fk-cc292d7ce407, fk-7e76b4cf2cb2. Priority medium. Supersedes 740, 742.
- **γ. Finance and optimize require their simulator** (leaf). Files:
  - `finance.py` (`project_multi_year`: `simulate: FleetSimulate` required, its default and function-local import go; docstrings);
  - `optimize.py` (`run_sweep`, `sensitivity_panel`: required; `run_sweep`'s default, which α pointed at `default_runner()`, goes);
  - the four calls that pass none: `test_finance_calibration.py`, `test_cost_recovery_calibration.py` ×2, `test_optimize_sweep.py`;
  - `tests/unit/test_import_structure.py`'s entry, if 775 has landed.

  Signal: B10. `project_multi_year(scenario, finance)` raises `TypeError` naming `simulate`. Today it silently fans out on every CPU through a hidden import. The library consumer's projection is driven only by the simulator it passes.

  Prereqs α, 801. Unlocks ζ. Key: fk-7e76b4cf2cb2. Priority medium.
- **δ. The dashboard: injected job manager, one shutdown, fleet jobs through the runner** (leaf). Files:
  - `web/dashboard.py` (new), `web/app.py` (`create_app(…, *, jobs)`, `default_jobs`, the holder, no `atexit`, `__main__` closes), `web/__init__.py` (the facade passes `default_jobs`), `web/shared.py` (the accessors read the holder);
  - `web/jobs.py` (`runner=` replaces `simulate_home=`; the fleet job calls `runner.simulate` with a sink over the job's progress; the per-home loop, its `FleetResults` assembly, the registry and `shutdown_all_managers` go);
  - `cli/web.py` (`create_app(jobs=partial(JobManager, runner=invocation(ctx).runner))`, `dashboard_of(app).close()` in `finally`);
  - tests: `tests/_web_app.py` (`jobs=`; built apps closed by the harness that built them), `tests/conftest.py` (the `sys.modules` reach-in goes), the 10 `extensions['job_manager'] =` sites (`tests/unit/web_api/conftest.py`, `test_simulate_sweep.py`, `web_assistant/test_tool_use.py` ×3, `test_web_jobs.py` or its 647 successors, `test_web_jobs_drain_scope.py`, `test_cli_web.py`, `tests/e2e/conftest.py` ×2), every `JobManager(…, simulate_home=…)` construction, `tests/e2e/conftest.py`'s held simulations;
  - `review/briefing.yaml` (no registry; who shuts the dashboard down).

  Signal: B11–B15. A dashboard fleet job runs its homes through the runner with per-home progress. Deleting its run cancels the homes not started. `solar-challenge web start` closes its own app. Tests inject their manager through `create_app`. The e2e suite stays green, run locally before merge.

  Prereqs α, β, 806, 819, 820. Keys: fk-7bdd33abd0ff, fk-f6c905f91d32, fk-7aaa879bf0ac, fk-7e76b4cf2cb2. Priority medium. Supersedes 121.
- **ε. The age-0 fleet simulated once per `finance run` (L10)** (leaf). Files: `fleet.py` (`reusing`), `cli/finance.py` (wrap after the bill run), `tests/unit/test_fleet.py` (B17), `tests/integration/test_cost_recovery_cli.py` or a new module (B16).

  Signal: B16. `finance run --project --cost-recovery` on an unaged scenario asks its simulator for the age-0 fleet once (today 4). The leaf records on the task the board scenario's wall time with and without the wrapper, and a real-simulator check that a seeded 2-home, 1-day run's report is byte-identical with and without it.

  Prereqs α, β. Keys: none of S16's ten. It carries `x_lead_ruling = "L10"`, as S9 α′ carries its lead question; the lead confirms the key form at decompose. Priority medium.
- **ζ. Retire the solve's implicit simulator and export the runner (held: `x_seam_wait = {stream: S29, contract: "the surface bump release window"}`)**. Files: `finance.py` (`solve_cost_recovery_rate(…, *, simulate: FleetSimulate)`; its function-local `fleet` import goes, unless S8's move took it), `__init__.py` (five names), `tests/unit/test_public_api_surface.py` or S23's successor, `docs/domain-library-consumption.md` (the Unreleased lines and recipe), the in-repo callers that pass none (`test_cost_recovery_calibration.py`).

  Signal: B18. Prereq γ. S29 releases it. Key: fk-7e76b4cf2cb2. Priority medium. Conditional on lead Q2.

DAG: α → {β, γ}; β → {δ, ε}; γ → ζ (held). Out of batch: α ← 809, 727; γ ← 801; δ ← 806, 819, 820.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- `no-silent-fail-soft`: `--workers 0` meant "every CPU", because `0 or …` is falsy; it is refused. A failed home is named, and pending homes are cancelled instead of run. A progress sink's exception propagates. A reuse miss falls through to simulation, which gives identical results, so it is no fail-soft. An invocation's injected runner outranks `--workers`, and the test helper says so.
- `one-fact-one-home`: the policy lives in `FleetRunner`; the production runner in `default_runner()`; a battery's starting SOH in `Battery` (ε reads it, never restates it); the dashboard's collaborators in `Dashboard`.
- `no-lockstep-duplication`: one fan-out loop, and one `FleetResults` assembly.
- `holds-owned-and-bounded`: ζ is held with an owner (S29) and a stated window.
- `exceptions-owned-or-ratified`: the solve's function-local `fleet` import stays a Transitional allow-list entry owned by ζ (or S8).
- `guards-exercise-behaviour`: every grep `delivered_check` in the sidecar pairs with a behaviour row above.

No waivers.

## Out of scope

- `simulate_community`'s `validate_balance` (frozen) and `simulate_home`'s own parameter.
- Simulation reuse beyond the age-0 fleet: the duplicated projection at the same rate in `finance run --project --cost-recovery` and in `optimize`'s `_evaluate_config`, and the sensitivity panel's re-simulation per floor. These are S8's projection work.
- Cancelling a home mid-simulation (S19 §3.7: needs a hook on the frozen core).
- Job state transitions and SSE framing (S20); where the accessors live (S17).
- Making the dashboard's two job threads share one process pool.

## Open questions

For the lead:

1. **Q1 — Finance and optimize take `simulate`, not the runner (decision 5).** The stream row says "finance and optimize take the runner in place of the bare simulate callable". This PRD keeps the callable form, which `solve_cost_recovery_rate` freezes. It makes the callable required on the non-frozen functions, and roots pass `runner.simulate`. The deletable "simulate kwarg threaded through 6 functions" therefore becomes "its `None` defaults and their resolution". The alternative is `runner: FleetSimulator` everywhere: a rename of the frozen keyword, held for S29, plus about 150 test sites rewritten from lambdas to objects. **Default:** the callable.
2. **Q2 — ζ at the bump.** Retire `solve_cost_recovery_rate`'s `simulate=None` and export `FleetRunner` with its protocols (this PRD's default, by L13's reasoning: one public way to simulate, no weather resolved behind a finance call). Or keep the facade default and export nothing; then ζ is not filed, and the solve's function-local import becomes Permanent (pvlib-free finance) in S1's allow-list.
3. **Q3 — `--workers`/`--sequential` move to the root (decision 6).** This breaks `fleet run … --workers N` in favour of `solar-challenge --workers N fleet run …`, and gives every simulating command the policy. **Default:** move.
4. **Q4 — Supersessions at decompose.** Cancel 740, 742 and 747 (pending mechanical tasks for three of this stream's keys) and 121 (deferred; δ deletes the `atexit` hook), each with `x_superseded_by`. fk-e58042aef503 is closed by 709. **Default:** as listed.

For the lead to know (decided here):

5. Dashboard fleet jobs become parallel under the root's runner (decision 12).
6. L10's extent: four age-0 simulations become one on unaged scenarios. Aged scenarios and `optimize` keep theirs (decision 8). `optimize`'s larger duplication is S8's.

Tactical (decide in the leaf):

7. α: the note's exact wording, and whether `simulate` delegates to `simulate_each` or both delegate to the private loop.
8. α: the importable module for worker-side fakes (`tests/_fleet_runner.py` proposed), so spawn and forkserver workers can import them.
9. β: how the quiet flag is read outside an invocation (a direct call of a helper in a unit test prints, unquiet); whether `cli/web.start`'s status line gets its own helper.
10. δ: how the test harness closes the apps and `JobManager`s it builds (a fixture, or a harness-owned list closed by an autouse fixture), measured against the 35 `build_test_app` calls in 22 files at the leaf's base.
11. δ: how `tests/e2e/conftest.py`'s held simulations reach the session app's runner (a gate the session runner's home simulator consults) without a second app.
