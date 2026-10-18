# RNG hand-off: the seed travels with the call

**Status:** authored 2026-10-17 (program `review-all-solar_challenge-20261013`, stream S13, wave 1, agent mode, size S, risk low, no upstream streams). Not committed by the author seat; not decomposed. Contract-first (B + H): S12 β binds to the seam in §5.

**Code anchors** verified against main `c06d12b` (2026-10-17). Main moves fast: cite-by-symbol; re-locate lines at implementation time. Every anchor the review pinned at `7dfea36e` was re-read here: `load.py` (+25/−35: tasks 757's renames and 768's rescale through `scale_profile_to_energy`), `tests/unit/test_load.py` (+67/−21, one new reach-in since the pin) and `web/jobs.py` (+6/−6) moved; `fleet.py` did not. The symbols below are as found at `c06d12b`.

## 1. Goal

A stochastic load profile depends only on its `LoadConfig`: not on what ran before it in the process, not on what runs beside it on another thread. The per-day stochastic simulator is a parameter of `generate_load_profile`, so tests and S12 drive it without patching load's privates or richardsonpy's internals.

What a user sees when this lands:

1. **Dashboard.** Two seeded home simulations submitted together to the web `JobManager` (its default two worker threads) store the demand a serial run of each gives. Today a stored "seeded" run started while another job runs is not reproducible, and nothing says so: 10 of 10 stored demands differed from their serial runs (§2).
2. **Library.** `generate_load_profile` leaves the caller's `random` and `numpy.random` state as it found it. An unseeded profile is fresh each time, wherever it runs; today it is a deterministic copy when a seeded profile ran before it. Any whole-number seed gives a stochastic profile; today a seed below 0 or at or above 2**32 silently gives the deterministic Elexon profile with a log warning.
3. **Fleet constructors.** `FleetConfig.create_uniform(..., seed=7)` and `create_heterogeneous(..., seed=7)` give home *i* the load seed 7 + *i*, as scenario fleets already do. Run twice, the fleet's homes have the same demand; within one fleet they differ. Today `create_uniform` with a seeded load gives every home the same profile, and neither constructor can seed its homes at all.

## 2. Findings and re-measurement

| Key | Severity / verdict | Statement (short) | Leaf |
|---|---|---|---|
| fk-16df1a7ac416 | **high** / confirmed / structural | Per-home seeding travels through process-global state. `_try_richardsonpy_profile` calls `np.random.seed(config.seed); random.seed(config.seed)` and lets richardsonpy draw from the globals. Profiles depend on process order and on concurrent threads. The engine has no seam. | α |
| fk-c78416de5500 | low / confirmed / structural | `test_richardsonpy_runtime_error_falls_back_to_elexon` monkeypatches the private `load._simulate_stochastic_day`; the fallback has no public seam. | α (the guarded-region half is S12 β's, §9) |
| fk-e0e34ef46058 | low / confirmed / mechanical (task 746) | `FleetConfig.create_uniform` shares one `LoadConfig` across homes; `create_heterogeneous` builds unseeded loads; the per-home rule lives only in `generate_homes_from_distribution`. | β |

Re-measured at `c06d12b` with the review's probe harness (`uv run --locked --extra dev python`, `generate_load_profile(LoadConfig(3400, household_occupants=3, use_stochastic=True, seed=s), ...)`):

- **Concurrent seeded profiles** (2024-06-01..07, seeds 42 and 43, serial reference, then 5 trials on `ThreadPoolExecutor(2)`, `Series.equals`): **10 of 10 differ.**
- **Dashboard path** (`JobManager(max_workers=2)`, default `simulate_home`, `WeatherCache` seeded with `synthetic_june_weather("2024-06-01", (1.0,)*7)`, two seeded `HomeConfig(PVConfig(4.0), LoadConfig(3400, seed=s))` jobs over 2024-06-01..07, 5 trials, stored demand read back with `RunStorage.load_home_run`): **10 of 10 stored demands differ** from serial `simulate_home`. With a lock wrapped around the stochastic window (probe only), **0 of 10 differ**, so the parquet round trip preserves equality and a lock plus seeding is sufficient.
- **Order dependence:** two unseeded 2-day profiles, each generated right after a seed-5 profile, are **equal**. Two fresh unseeded profiles differ.
- **Caller state:** `random.getstate()` before and after a seeded call: **not equal.**
- **Seed domain:** seeds −1, 2**32 and 2**40 each return a profile **equal to the Elexon profile** (with the fallback WARNING). `np.random.seed` refuses them inside the `try`. The dashboard admits seeds from −(2**53−1) to 2**53−1 (`web/fleet_config.MAX_FLEET_SEED`), so a dashboard fleet with a negative seed runs every home on Elexon today.
- **What richardsonpy draws from:** the locked richardsonpy 0.2.3 draws only from the stdlib `random` (`classes/occupancy.py`, `classes/appliance.py`, `classes/lighting.py`, `functions/occupancy_model.py`); it never calls `numpy.random`. Seeding numpy is the briefing's rule and a defence against a richardsonpy release that does (the newest-releases lane would see it).
- **Python's `random.seed` takes |s|:** `random.seed(-7)` and `random.seed(7)` give the same stream (probed). A fleet seed of −1 would give homes −1 and +1 one profile unless the hand-off maps signs apart (decision 4).
- **Test reach-ins** into the stochastic engine in `tests/unit/test_load.py::TestWindowedStochasticGeneration`: **5** (the review counted 4 at the pin): three `monkeypatch.setattr(_app_mod, "run_application_simulation", ...)` call counters (`test_window_1day_calls_run_simulation_exactly_once`, `test_window_3day_calls_run_simulation_exactly_three_times`, `test_window_crossing_spring_dst_counts_calendar_days`), one of `load._simulate_stochastic_day` (`test_richardsonpy_runtime_error_falls_back_to_elexon`), and one of `ElectricityProfile.power_sim` (`test_a_richardsonpy_window_with_no_energy_falls_back_to_the_elexon_profile_with_a_warning`, added since the pin).
- **Cost of the window:** a 7-day stochastic profile takes about 0.47 s (two took 0.93 s serially); a year is about 25 s.
- **Fleet constructors:** unchanged since the pin. Their callers are tests only (`tests/unit/test_fleet.py`, `tests/integration/test_fleet_simulation.py`), and every one passes an unseeded `LoadConfig`.

## 3. What exists (G3)

- `load.generate_load_profile(config, start_date, end_date, timezone="Europe/London", ev_config=None)`: one caller in src, `home._demand`. Not on the frozen surface (`tests/unit/test_public_api_surface.py` pins `LoadConfig` only), so a keyword-only parameter needs no surface edit.
- `load._try_richardsonpy_profile`: one `try` around the richardsonpy imports, the data-file paths, the global seeding, date normalisation, `Occupancy` over the window, `Appliances`, `load_lighting_profile`, `ElectricityProfile`, the per-day loop through `_simulate_stochastic_day` (one `power_sim` call each), the DST trim/pad, and `scale_profile_to_energy`; `except Exception` logs a WARNING and returns `None`, and `generate_load_profile` then builds the Elexon profile.
- `config.generate_homes_from_distribution`: samples through an explicit `random.Random(config.seed)` and gives home *i* `LoadConfig(seed=config.seed + i)` when the fleet seed is set (the inline "Derive per-home seed" block).
- `fleet.FleetConfig.create_uniform` / `create_heterogeneous`: pinned in `FROZEN_MEMBERS` (`tests/unit/test_public_api_surface.py`).
- `web/jobs.JobManager(max_workers=2, *, simulate_home=...)` on a `ThreadPoolExecutor`; `web/storage.RunStorage.load_home_run(run_id)` returns `(HomeConfig, SimulationResults, SummaryStatistics)`; `SimulationResults.demand` is the stored demand series.
- `tests/conftest.py::weather_cache` and `tests/_synthetic_weather.synthetic_june_weather` serve an offline TMY.
- `errors.ConfigurationError` exists (task 773 done); task 774 (S1 β, in progress) makes it a `ValueError`.
- `review/briefing.yaml` already carries the conventions rule "Fleet simulations must be reproducible from a single seed: per-home seed = fleet_seed + index, and stochastic load paths must seed BOTH numpy and the stdlib `random` module".
- Global RNG use in src (`grep` for `random.<fn>(`, `np.random.<fn>(`): only `load._try_richardsonpy_profile`'s two seed calls. Explicit generators: `config.generate_homes_from_distribution` and `web/fleet_config` (`random.Random`).

No novel substrate: every capability the signals assume exists on main or is delivered by the leaf that asserts it.

## 4. Resolved design decisions

1. **The seam is a household model, not a bare per-day function.** richardsonpy's household is window-scoped state: an occupancy Markov chain over the whole window and one appliance and lighting set. A per-day callable alone would have to take that state as an opaque richardsonpy object, or load would keep building it outside the seam. So the injected parameter is a factory, called once per window, that returns the per-day simulator, called once per local day (contract C1, C2). Everything richardsonpy-specific (its imports, data files, occupancy, appliances, lighting and the `power_sim` call) lives behind the factory, in `load.richardsonpy_household`, the default. Load keeps the windowing, placement, scaling, the RNG hand-off and the fallback. This is the shape S12 β binds to; it is S12's "keyword-only parameter of `generate_load_profile` called per day", with the per-day callable produced by the keyword's factory.
2. **One hand-off context, in load.py, around the whole window.** It is entered once per stochastic window and wraps the factory call and every day call (C3). It takes a module-private lock, saves both global states, seeds both, and restores both and releases the lock on exit, normal or not. Serialising stochastic windows across threads costs no real throughput: richardsonpy is pure Python and holds the GIL, so two threads never ran it in parallel anyway.
3. **Unseeded means fresh entropy, every time.** `seed=None` seeds both generators from a fresh `numpy.random.SeedSequence()`. An unseeded profile no longer copies whatever ran before it.
4. **Every int is a seed, and seeded output in numpy's range is unchanged.** For 0 ≤ s < 2**32 the context makes exactly today's calls, `random.seed(s)` and `np.random.seed(s)`, so every seeded profile and every board figure built on one is unchanged byte for byte. Any other int (today a silent Elexon fallback) seeds both generators from one `SeedSequence` over (|s|, sign of s). Every int then gives a stochastic profile, and s and −s differ. This removes a domain rather than policing it, so the seed's numpy range needs no refusal anywhere (task 573's range rule and task 766 are superseded, §13). A bool or fractional seed is S4's: `LoadConfig.seed` joins S4 β's whole-number refusal (finite-quantities.md §5.2).
5. **numpy is seeded although richardsonpy 0.2.3 never draws from it.** The briefing mandates both; a richardsonpy release that draws from numpy then stays reproducible with no edit here.
6. **The hand-off is the only writer of global RNG state in src** (C6). A guard test scans src and refuses any other seed or set-state call on `random` or `numpy.random`, and any call of their module-level draw functions. Explicit generators (`random.Random`, `np.random.default_rng`, `np.random.SeedSequence`) stay free. The lock only protects windows from each other; this guard is what makes "no other draw interleaves" true.
7. **A fork child gets a fresh lock** (`os.register_at_fork(after_in_child=...)`, C5). A process forked while another thread is inside a window would otherwise inherit the lock held, and its first stochastic profile would hang. No src path forks from a threaded process today. `fleet.simulate_fleet_iter` forks only from the single-threaded CLI, and the web runs fleet homes on its job threads. The reset costs two lines and closes that path for good.
8. **The fallback's scope is unchanged in α.** S12's decision 15 narrows the `try` to richardsonpy's own failures; under this seam those are exactly the factory call and the day calls. α moves code out of the guarded body into `richardsonpy_household`, but every exception that falls back today still falls back after α. S12 β owns the behaviour change and its B3 assertion that the project's own errors propagate.
9. **Every test reach-in goes through the seam** (B8). The three `run_application_simulation` counters wrap `richardsonpy_household` and count day calls. The `_simulate_stochastic_day` patch becomes a factory that raises. The `power_sim` zeros patch becomes a factory whose days return zeros. `_simulate_stochastic_day` is deleted, since its body moves into the default model. S12 β's file-list clause "the three `run_application_simulation` counters become counts of S13's injected simulator" is therefore done by α (§9 cross-reference).
10. **The per-home seed rule has one home: `fleet.fleet_home_seed(fleet_seed, index)`.** It returns `None` for an unseeded fleet and `fleet_seed + index` otherwise. `config.generate_homes_from_distribution` and both constructors call it. It goes in fleet.py, which config already imports and whose constructors are its first readers (the name task 746's plan chose).
11. **Both constructors take a keyword-only `seed: int | None = None`; `create_uniform` refuses a seeded template.** A `load_config` with a seed in `create_uniform` is either the identical-homes bug or a second source of the fleet seed. Either way it is refused with `ConfigurationError` naming `load_config.seed` and its value and saying to pass `seed=`. This follows D10's fill-and-refuse posture and leaves one source. Unseeded stays the default, as for `fleet_distribution`, and stays irreproducible by declaration, with fresh draws per home (decision 3). Both signature changes are additive, so the `FROZEN_MEMBERS` edits and an "Unreleased on main" line land in β (D29). The refusal raises `errors.ConfigurationError`, like other wave-1 refusals (L5), so β depends on 774.
12. **Invariant 3's checkable text is corrected** (§7). Its middle clause, "an unseeded profile generated after a seeded one differs from a second fresh unseeded profile", already holds today, so it pins nothing. The discriminating form is: two unseeded profiles, each generated right after the same seeded profile, differ (today they are equal).

## 5. Contract (the seam S12 binds to)

```python
# src/solar_challenge/load.py  (α)
DaySimulator: TypeAlias = Callable[[datetime.date], npt.NDArray[np.float64]]
    # one local calendar day -> 1,440 one-minute power values in W, wall-clock 00:00..23:59
HouseholdModel: TypeAlias = Callable[[LoadConfig, Sequence[datetime.date]], DaySimulator]
    # one window's household; draws only from the global random / numpy.random generators

def richardsonpy_household(config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator: ...

def generate_load_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
    ev_config: "Optional[EVConfig]" = None,
    *,
    household_model: HouseholdModel = richardsonpy_household,
) -> pd.Series: ...
    # S12 β changes the positional part to (config, window); the keyword is unchanged.

# src/solar_challenge/fleet.py  (β)
def fleet_home_seed(fleet_seed: int | None, index: int) -> int | None: ...
class FleetConfig:
    @classmethod
    def create_uniform(cls, n_homes, pv_config, load_config, battery_config=None,
                       location=Location.bristol(), name="", *, seed: int | None = None) -> "FleetConfig": ...
    @classmethod
    def create_heterogeneous(cls, pv_capacities_kw, battery_capacities_kwh, annual_consumptions_kwh,
                             location=Location.bristol(), name="", *, seed: int | None = None) -> "FleetConfig": ...
```

- **C1 (seam calls).** When `config.use_stochastic`, `generate_load_profile` calls `household_model(config, days)` once. `days` holds the window's local calendar dates, consecutive and ascending: today `start_date`'s date through `end_date`'s, inclusive; under S12 β, `window.local_days()`' dates. It then calls the returned simulator exactly once per date, in order. When `use_stochastic` is False it calls neither.
- **C2 (day values).** A `DaySimulator` returns 1,440 one-minute power values in W, for its date's wall-clock minutes 00:00 to 23:59. It knows no time zone. Load converts W to kW and places the values: today by concatenation with the existing trim/pad, under S12 β by wall clock. Load refuses an array that is not 1,440 long with a `ValueError` naming the date and the length. Under today's `try` that refusal falls back like any other.
- **C3 (RNG window).** `household_model(...)` and every day call run inside load's hand-off context, entered once per window. The context:
  1. acquires the module-private lock;
  2. saves `random.getstate()` and `np.random.get_state()`;
  3. seeds both per C4;
  4. on exit, normal or by exception, restores both and releases the lock.

  A household model draws randomness only from the module-level `random` and `numpy.random` generators. It never calls `generate_load_profile`, because the lock is not re-entrant.
- **C4 (seed mapping).**
  - `seed` in [0, 2**32): `random.seed(seed)` and `np.random.seed(seed)`, today's calls.
  - Any other int: one `np.random.SeedSequence((abs(seed), int(seed < 0)))` seeds both generators.
  - `None`: a fresh `np.random.SeedSequence()` seeds both.

  The exact derivation of the two generators' seeds from a `SeedSequence` is tactical. The properties are fixed: it is deterministic for an int; distinct ints give distinct streams, s and −s included; `None` never repeats.
- **C5 (fork).** `os.register_at_fork(after_in_child=...)` replaces the lock in a forked child.
- **C6 (one writer).** In `src/solar_challenge`, C3's context is the only code that calls a module-level function of `random` or `numpy.random`: the seed, state and draw functions alike. The constructors `random.Random`, `np.random.default_rng`, `np.random.SeedSequence` and `np.random.Generator` are free anywhere. A guard test enforces this (B9).
- **C7 (fallback, unchanged by α).** Any exception from `household_model`, from a day call, or from load's own windowing and scaling inside `_try_richardsonpy_profile` does the same as today: it logs the WARNING "richardsonpy stochastic generation failed; falling back to Elexon deterministic profile: <type>: <message>" and `generate_load_profile` returns the Elexon profile. S12 β narrows this to the C1 calls (its decision 15).
- **C8 (per-home seed).** `fleet_home_seed(None, i) is None`; `fleet_home_seed(s, i) == s + i`. `config.generate_homes_from_distribution`, `create_uniform` and `create_heterogeneous` are its callers. No other src code adds an index to a seed.
- **C9 (constructors).** In `create_uniform`, home *i*'s load is `dataclasses.replace(load_config, seed=fleet_home_seed(seed, i))`. In `create_heterogeneous`, it is `LoadConfig(annual_consumption_kwh=..., seed=fleet_home_seed(seed, i))`. `create_uniform` raises `errors.ConfigurationError` when `load_config.seed is not None`. The message names `load_config.seed` and its value and says to pass `seed=`, since home *i* gets seed + *i*.

**Invariant table.**

| Invariant | Enforced by | Pinned by |
|---|---|---|
| A stochastic profile depends only on its `LoadConfig` (invariant 3) | C3 + C4 | B1, B3, B7 (`tests/unit/test_load_reproducibility.py`, the web half in `tests/unit/web_jobs/`) |
| A seeded profile in [0, 2**32) is today's profile | C4 | B2 |
| `generate_load_profile` leaves the caller's RNG state as it found it | C3 | B4 |
| Every int seed gives a stochastic profile; s ≠ −s | C4 | B5 |
| Only the hand-off writes global RNG state in src | C6 | B9 |
| Home *i* of a seeded fleet has load seed `fleet_seed + i`, by one rule | C8, C9 | B10 |

## 6. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|
| B1 | Seeded profiles serially and on two threads (invariant 3, producer) | `LoadConfig(3400, household_occupants=3, use_stochastic=True, seed=s)`, s ∈ {42, 43}, 2024-06-01..07, default model; serial references, then 5 trials on `ThreadPoolExecutor(2)` | every concurrent profile `Series.equals` its serial reference (today 10 of 10 differ) | α |
| B2 | Seeded draws are today's | a `household_model` that records `random.random()` and `np.random.random_sample()` on entry; seed 42 | the recorded draws equal `random.Random(42).random()` and `np.random.RandomState(42).random_sample()` (pins C4's in-range branch; α also records on the task that the seed-42 and seed-43 7-day profiles are byte-identical before and after) | α |
| B3 | Unseeded is fresh after a seeded call (invariant 3, corrected) | the recording model; seed 5, then `None`; again seed 5, then `None` | the two unseeded first draws differ (with the default model and 2-day windows, today they are equal) | α |
| B4 | Caller state restored | `random.getstate()`, `np.random.get_state()` taken before a seed-7 call; again around a model that raises | both states equal after each call (today not equal) | α |
| B5 | Every int is a seed | seeds −1, 1, 2**32, 2**40, default model, 2024-06-01..02, `caplog` at WARNING | −1 and 1 profiles differ; 2**32 and 2**40 profiles are not equal to the Elexon profile, reproduce on a second call, and log no fallback WARNING (today each equals Elexon with the WARNING) | α |
| B6 | Fork child while a thread holds the window | Linux `multiprocessing.get_context("fork")`; a thread inside `generate_load_profile` with a model blocked on an `Event`; the child runs a seed-42 1-day profile | the child exits 0 within 30 s with the serial profile; the parent thread is then released | α |
| B7 | Dashboard jobs (user-facing, invariant 3) | `JobManager(max_workers=2)`, default `simulate_home`; `weather_cache` seeded with `synthetic_june_weather("2024-06-01", (1.0,)*7)`; two seeded homes (42, 43) over 2024-06-01..07 submitted together; 2 trials | each stored run's `RunStorage.load_home_run(run_id)[1].demand` `Series.equals` serial `simulate_home(...).demand` (today 10 of 10 differ) | α |
| B8 | The seam replaces every reach-in (consumer: S12) | `TestWindowedStochasticGeneration` | a counting wrapper of `richardsonpy_household` counts 1, 3 and 3 day calls for 2024-06-21, 2024-06-21..23 and 2024-03-30..04-01; a raising model gives the Elexon profile and the WARNING; a zeros model gives the Elexon profile and the "zero consumption" WARNING; the class has no `monkeypatch`; `_simulate_stochastic_day` is gone | α |
| B9 | One writer (guard) | AST scan of `src/solar_challenge`; a seeded violation in a `tmp_path` module | the real tree reports only load's hand-off; the seeded `random.seed(1)` and `np.random.rand()` are reported by file and name | α |
| B10 | Fleet seeds (invariant 3, fleet clause; user-facing for library consumers) | `create_heterogeneous([4.0]*3, [None]*3, [3400.0]*3, seed=7)`; `create_uniform(3, PVConfig(4.0), LoadConfig(3400), seed=7)`; `create_uniform(..., LoadConfig(3400, seed=42))`; the same with no seed | seeds are 7, 8, 9 on both; each home's `generate_load_profile` over 2024-06-21 repeats exactly on a second call and the three differ pairwise; the seeded template raises `ConfigurationError` naming `load_config.seed` and 42; no seed gives seeds `None`; `generate_homes_from_distribution`'s existing seed tests pass unchanged | β |

## 7. Invariant 3 (D27)

Promoted as `tests/unit/test_load_reproducibility.py`, created by α with B1 and B3, the latter in its corrected form (decision 12). B4 and B5 live beside them. β adds the fleet clause, B10's seed assertions. B7, the web half, lives in `tests/unit/web_jobs/` beside the other `JobManager` tests (`pytest.importorskip("flask")`, as that package does). The verify runs `--extra web`.

The briefing has one home for this rule. α edits the existing `review/briefing.yaml` conventions entry ("Fleet simulations must be reproducible from a single seed ...") rather than adding a second one. The entry's rule gains "stochastic draws run only inside load.py's RNG hand-off, which seeds both generators from the call's seed (fresh entropy when unset) and restores them". Its `why` names `tests/unit/test_load_reproducibility.py` and the B7 test. β adds `fleet.fleet_home_seed` as the one home of `fleet_seed + index`.

Corrected checkable text, offered to the lead for the program doc (§9):

> `generate_load_profile(LoadConfig(seed=s))` run serially equals the same call run on two threads concurrently for s in {42, 43}. Two unseeded profiles, each generated right after the same seeded profile, differ. `FleetConfig.create_heterogeneous(..., seed=f)` and `create_uniform(..., seed=f)` give home *i* `LoadConfig.seed == f + i`.

## 8. Pre-conditions

- α: none. It is wave 1 and starts at decompose.
- β: α (shared test module and the same "Unreleased on main" list) and **774** (S1 β, in progress: `ConfigurationError` subclasses `ValueError`).
- Nothing waits on S29. Both surface edits are additive (D29), and `generate_load_profile` is not on the frozen surface.

## 9. Cross-PRD relationship (G4)

| Other PRD / stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S12 Load composition (`load-composition-and-calendar-days.md`) | produces → S12 β consumes | `generate_load_profile(..., *, household_model: HouseholdModel = richardsonpy_household)`; `DaySimulator` called once per local date (C1, C2); the RNG hand-off around the window (C3) | S13 (seam, context); S12 (calendar-day placement, scaling, fallback scope) | S12 β held on α (L26) |
| S12 (fk-72af0b90338d vs fk-c78416de5500) | shared region | the `try` in `_try_richardsonpy_profile` | S12 β narrows it (its decision 15); α changes no fallback behaviour | α first, then β |
| S4 Finite quantities (`finite-quantities.md`) | file overlap + one row | `LoadConfig.seed`'s bool/fraction refusal (S4 β/ζ); S4 §10's row for task 573 | S4 for the refusal; S13 supersedes 573's range rule | cross-reference |
| S16 Fleet execution policy (`fleet-execution-policy.md`) | file overlap | `fleet.py` (FleetRunner vs the constructors); S16's row for task 746 | each its own | order-agnostic |
| S5 config partition (unauthored) | file overlap | `generate_homes_from_distribution` may move to `fleet_distribution.py`; it keeps calling `fleet.fleet_home_seed` | S5 moves; S13 β edits the call | textual |
| S23 surface home | file overlap | `FROZEN_MEMBERS` entries for `FleetConfig.create_uniform` / `create_heterogeneous` | β edits in-leaf (D29) | textual |
| S15 β (task 809) | none semantic | B7 uses `JobManager`'s default `simulate_home`, so 809's signature change does not touch it | — | — |
| S18 PageLimits | none | the dashboard's seed bounds stay S18's; decision 4 makes every int it admits a working seed | S18 | — |

## 10. Decomposition plan

Every leaf carries `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`, its keys after the contract §8 step-1 lookup, and file-level `metadata.files`. α is high and joins trigger-chain gate 772.

- **α. RNG hand-off and the injectable household model** (leaf; priority high; keys fk-16df1a7ac416, fk-c78416de5500).
  - Files: `src/solar_challenge/load.py` (`DaySimulator`, `HouseholdModel`, `richardsonpy_household`, the hand-off context, the lock and its fork reset; `generate_load_profile` gains `household_model`; `_simulate_stochastic_day` and the inline seeding go); `tests/unit/test_load.py` (`TestWindowedStochasticGeneration`'s five reach-ins through the seam); `tests/unit/test_load_reproducibility.py` (new: B1–B6, B9); `tests/unit/web_jobs/test_seeded_jobs_reproduce.py` (new: B7); `review/briefing.yaml` (the existing seeding rule, §7); `docs/domain-library-consumption.md`. Its "Unreleased on main" line says that unseeded profiles no longer depend on earlier seeding, that a call restores the caller's global RNG state, that seeds outside 0..2**32−1 now give stochastic profiles instead of the Elexon fallback, and that seeded profiles in range are unchanged.
  - Signal (dashboard): two seeded home jobs submitted together to the web `JobManager` store the demand a serial run gives, for both homes in both trials (B7; today 10 of 10 differ). Library: B1, B3, B4, B5. Seam: B8, with no `monkeypatch` left in `TestWindowedStochasticGeneration`.
  - Records on the task: the seed-42 and seed-43 7-day profiles are byte-identical before and after (`Series.equals`), and the wall time of the full non-slow suite before and after.
  - Prereqs: none.
- **β. Fleet constructors seed each home by one rule** (leaf; priority low; key fk-e0e34ef46058).
  - Files: `src/solar_challenge/fleet.py` (`fleet_home_seed`; `seed` keyword on both constructors; `create_uniform`'s refusal); `src/solar_challenge/config.py` (`generate_homes_from_distribution` calls `fleet_home_seed`); `tests/unit/test_fleet.py`; `tests/unit/test_load_reproducibility.py` (fleet clause); `tests/unit/test_public_api_surface.py` (`FROZEN_MEMBERS`); `docs/domain-library-consumption.md` (an "Unreleased on main" line: the two keywords, the refusal of a seeded `create_uniform` template, consumers need no change unless they passed one); `review/briefing.yaml` (the rule names `fleet.fleet_home_seed`).
  - Signal (library consumer, frozen surface): `create_uniform(3, PVConfig(4.0), LoadConfig(3400), seed=7)` gives three homes with seeds 7, 8, 9, whose demand repeats exactly run to run and differs home to home. `create_uniform` with `LoadConfig(seed=42)` raises `ConfigurationError` naming `load_config.seed` (today every home draws one identical profile). B10.
  - Prereqs: α, 774.

DAG: α → β; 774 → β. α → gate 772. S12 β (held) → α.

**G7 (advisory; this project has no `docs/legibility/design-invariants.md`).** These are the hits against dark-factory's trigger shapes.
- `no-silent-fail-soft`: the Elexon fallback stays as CLAUDE.md's documented defence. α adds no new fallback and removes one silent path, the out-of-range seed. S12 β narrows the fallback's scope.
- `exceptions-owned-or-ratified`: B9's guard allows exactly one site, load's hand-off, ratified by C6 here.
- `one-fact-one-home`: the briefing rule is edited in place, and `fleet_home_seed` is the one home of the per-home rule.
- `holds-owned-and-bounded`: the lock is held for one window, at most about 25 s for a year, and the fork reset bounds the one path that could hold it forever.
- `guards-exercise-behaviour`: B9 is a source scan, but the behaviour it protects is exercised by B1 and B7. No waiver needed.

## 11. Out of scope

- Narrowing the fallback's `try`, wall-clock placement, calendar-day energy, and renaming `_try_richardsonpy_profile` (S12 β).
- `LoadConfig.seed`'s bool and fractional refusal, and `fleet_distribution.seed`'s whole-number read (S4 β/ζ).
- The dashboard's seed bounds (S18).
- Passing explicit generator objects into richardsonpy. Its API has no such parameter, and a fork of richardsonpy is not this program's.
- Raising `JobManager`'s worker count, or running web fleets through a process pool (S16 / S20).
- Recording on results whether a profile was seeded.

## 12. Open questions (tactical)

1. **The `SeedSequence` derivation in C4.** One option is `random.seed(int.from_bytes(ss.generate_state(4).tobytes(), "little"))` and `np.random.seed(ss.generate_state(4))`. Any deterministic derivation with C4's properties will do. Decide in α.
2. **B6 on interpreters without `fork`.** Skip it where `"fork" not in multiprocessing.get_all_start_methods()`. Python 3.12+ warns about forking a threaded process (`DeprecationWarning`), and the test filters that one warning locally. Decide in α.
3. **`HouseholdModel` as a `Protocol` or a `Callable` alias.** A `Protocol` names the parameters in mypy messages; either keeps the contract. Decide in α.

## 13. Decompose-time actions

- **Task 746** (pending, fk-e0e34ef46058): cancel with `x_superseded_by` β after the §8 step-1 lookup. β delivers 746's plan, `fleet_home_seed`, the `seed` keyword on both constructors, and config calling the helper. It also decides the case 746 left open: a seeded `create_uniform` template is refused (decision 11).
- **Task 766** (pending, depends on 573 and 746): cancel with `x_superseded_by` α. The hand-off accepts every int (decision 4), so no seed reaching `LoadConfig` silently drops to Elexon; the bool and fraction half is S4's.
- **Task 573** (pending): cancel with `x_superseded_by` α for its range rule. Its residual, reading `fleet_distribution.seed` as a whole number in config and the web readers, is S4 ζ's per finite-quantities.md §5.3. S4's §10 row "573 stays: the seed's 0..2**32−n range rule" changes accordingly (lead's cross-reference, §9).
- **Tasks 709 and 768** (done): no action. 709's seeded parallel fleet test stays green; α's change keeps seeded output identical.
