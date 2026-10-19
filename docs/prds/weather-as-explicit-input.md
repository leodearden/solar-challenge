# Weather as an explicit input

**Status:** authored 2026-10-14 (program `review-all-solar_challenge-20261013`, stream S15, wave 1, no upstream streams); not yet committed or decomposed. Contract-first (B + H). Binding rulings: D4, D15, D16, D29.

**Code anchors** verified against main `d316d0e` (2026-10-14). Main moves fast: cite-by-symbol; re-locate lines at implementation time.

## Goal

A simulation's weather is an argument. `simulate_home` takes a weather provider and never looks one up. The process-wide cache that `get_tmy_data` reads today stays only as the default the composition roots resolve, and the S29 bump retires it. A worker process receives its weather in its job, so no start method can make it miss the cache (the task-460 class). A cache entry is one file, written by one `os.replace`, and `get` returns exactly the frame `put` stored, or nothing.

What a user sees when this lands:

- `SOLAR_CHALLENGE_WEATHER_CACHE_DIR=<dir> solar-challenge home quick 4 --days 1`, with a Bristol TMY put into `<dir>`, runs offline from that TMY in any working directory. Today the CLI reads only `./.cache/weather` and fetches PVGIS on a miss. The dashboard and the fleet commands read the same variable.
- `simulate_home(config, start, end)` raises `TypeError` naming `weather`. Today it silently reads the process-global cache, and fetches PVGIS on a miss.
- After a run, the weather cache directory holds one file per location. Today it holds a CSV plus a JSON sidecar. `WeatherCache.get` never returns a frame that differs from the one `put` stored. Today a CSV whose sidecar is gone comes back at a fixed UTC offset with no frequency.
- After the S29 bump, `solar_challenge.set_weather_cache` raises `AttributeError`. A consumer passes a `PvgisTmy` over its own `WeatherCache` instead, or sets the variable.

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says |
|---|---|---|
| fk-06035cd76226 | medium / confirmed | `get_tmy_data` reads its cache from the process-global `_weather_cache` through `get_weather_cache`/`set_weather_cache`: an implicit input, a temporal coupling on an earlier `set_weather_cache`, and invisible to spawn/forkserver workers. Task 460 is the symptom. `fleet._tmy_by_location` compensates in another module. |
| fk-44fdf5fb356b | low / confirmed | The path is half-migrated. The fleet passes `weather_data` to `simulate_home`; the other 5 production call sites (`cli/home` `run` and `quick`, `config.run_parameter_sweep`, `web/jobs` home and fleet jobs) reach the global through `simulate_home`'s `weather_data is None` fallback. Tests and scripts install the global 8 times; 775ef88 fixed the fixture-order defect that followed. |
| fk-e4549a3a6b54 | low / weakened | An entry is a CSV plus a JSON sidecar, replaced by two `os.replace` calls. `put` writes five keys `get` never reads. A CSV whose sidecar is missing comes back as a degraded frame. |

### Re-measurement at `d316d0e` (D28 and the freshness clause)

`git diff 7dfea36e..d316d0e` touches `home.py` (task 710 split `simulate_home` into private steps; the fallback now lives in `_hourly_weather`) and `web/jobs.py` (one SQL statement). `weather.py`, `fleet.py`, `cli/home.py`, `config.py` and `tests/conftest.py` are unchanged. Measured on `d316d0e`:

- **Fallback callers.** `simulate_home(` in `src`: `cli/home.py` `run` and `quick`, `config.run_parameter_sweep` and `web/jobs.py` `_run_home_simulation` and `_run_fleet_simulation` (through the default `JobManager(simulate_home=home.simulate_home)`) pass no weather; `fleet._simulate_home_worker` and `_simulate_home_worker_tagged` pass `weather_data`. 5 of 7, as reported.
- **Global installers.** `set_weather_cache(` outside `weather.py`: `tests/conftest.py` 3 (`_open_offline_window` install and reset, the `weather_cache` fixture), `tests/unit/test_e2e_job_wait.py` 2, `tests/unit/test_fast_tests_run_offline.py` 1, `scripts/measure_mppt_window.py` 1, `scripts/measure_pv_performance_ratio.py` 1. 8, as reported.
- **fk-e4549a3a6b54 (weakened), probed with `uv run --locked --extra dev python`.** `put` of `synthetic_june_weather("2024-06-01")` writes `tmy_<hash>.csv` and `tmy_<hash>.meta.json`. The sidecar's keys are `end_date, freq, latitude, longitude, prefix, start_date, timezone`; `get` reads `timezone` and `freq`, so 5 are unread. With the sidecar deleted, `get` returns a frame indexed at the fixed offset `UTC+01:00`, not `Europe/London`, and with no frequency. The finding says "no timezone"; pandas 3 parses the offset, so the frame is degraded in zone and freq. `put` still replaces meta then CSV. The skeptic's weakening holds: since meta is replaced first, a killed `put` cannot leave a new CSV without its sidecar, so only outside deletion or a partial copy reaches the degraded path. Severity stays low.
- **Substrate the design rests on**, all probed: `pyarrow` is only in the `web` extra, so parquet is ruled out for the core; a frozen dataclass holding a `WeatherCache` pickles and unpickles with its `cache_dir`; a frozen dataclass holding a `dict[Location, DataFrame]` pickles; `types.MappingProxyType` does not pickle; `Location` hashes; `tests/_surface_forms.surface_form` renders a `typing.Protocol` as `(*args, **kwargs)` and `member_forms` gives its `get`; `solar_challenge.<name not in __all__>` raises `AttributeError: module 'solar_challenge' has no attribute ...`.

## Sketch of approach

`weather.py` gains the provider vocabulary (contract below):

- `WeatherProvider`, the protocol `get(location) -> DataFrame`.
- `PvgisTmy(cache)`: today's `get_tmy_data` body with the cache an attribute.
- `PrefetchedWeather`: frames in memory, refusing a location it does not hold, with `fetch(weather, locations)` doing the per-location prefetch `fleet._tmy_by_location` does today.
- `default_weather()`: the one default a composition root resolves.

`WeatherCache()` with no directory reads `SOLAR_CHALLENGE_WEATHER_CACHE_DIR`, else `.cache/weather` as today. The variable is how every root, the test window and any child process agree on a directory without a module global.

`simulate_home` takes `weather: WeatherProvider`, required and keyword-only. Every caller passes one:

- the fleet's workers get a `PrefetchedWeather` holding their home's location;
- `cli/home` and the dashboard (bound once in `create_app`) pass `default_weather()`;
- tests construct providers.

Until the S29 bump, `default_weather()` is `PvgisTmy(get_weather_cache())`, so a consumer's `set_weather_cache` still steers every root and the fleet facade. The bump retires the global, and `default_weather()` becomes `PvgisTmy(WeatherCache())`. By then no in-repo code calls the retired names, so the held leaf only deletes.

The cache entry becomes one self-describing file per key, with key version 3, so older entries are ignored.

## Resolved design decisions

1. **The provider is a protocol with two implementations (D15).** `PvgisTmy` holds the cache; `PrefetchedWeather` holds frames. A worker gets frames, not a cache: no disk, no network, any start method. `PvgisTmy` is picklable too, so S16 may hand it to a pool, but S15's fleet does not. `simulate_home` types its parameter as the protocol, so a test double needs no subclassing.
2. **`simulate_home(..., *, weather: WeatherProvider)` is required.** The `weather_data` frame parameter and its `None` fallback go. `simulate_home` is not on the frozen surface, so this lands in-leaf. The heat-pump year-length check stays, on what `weather.get(config.location)` returns.
3. **One default, resolved only at roots and facades.** `default_weather()` is the single home of "the weather a root uses when given none". Its callers after S15:
   - `cli/home` (`run`, `quick`) and `web/app.create_app`;
   - two transitional ones: `fleet.simulate_fleet_iter` and `fleet.simulate_multi_sweep_iter`, until S16's `FleetRunner` takes them to the roots (D16), and `config.run_parameter_sweep`, until S5 deletes it;
   - the frozen `get_tmy_data` facade, until ε.

   No function below them reads a process-wide weather source.
4. **The cache directory is configured by `SOLAR_CHALLENGE_WEATHER_CACHE_DIR`, read only by `WeatherCache.__init__` when `cache_dir` is `None`.** An empty value counts as unset. This is root configuration, like the web's `DATA_DIR`. Unlike the global, it crosses process boundaries (subprocess CLIs, spawn workers), and tests set it exactly as `tests/_network_guard.refusing_network` already sets proxy variables for a test's window.

   Per-root seams (a weather field on Click's context object, a `create_app` parameter) were considered and rejected. They collide with S16's CLI-context and `create_app` work, and they do not reach a CLI run as a subprocess. Lead question Q2 confirms.
5. **`get_weather_cache()` stops memoising its default.** With nothing installed, it returns a new `WeatherCache()` on each call, so a change to the variable takes effect. `set_weather_cache` keeps working as an override until the bump. Its surface form is unchanged.
6. **The web binds weather at the root.** `JobManager`'s `simulate_home` loses its default (the bare `home.simulate_home` no longer satisfies `HomeSimulator`). `create_app` passes `functools.partial(simulate_home, weather=default_weather())`. `HomeSimulator` keeps its three-argument shape, so no test double changes. The default is resolved once, when the app is created: a cache installed or a variable set after `create_app` does not reach its jobs. Today each job reads the global when it runs, so a fixture that installs weather must now do it before the app is built. The dashboard's fleet job keeps reading through that provider per home, as it reads the cache per home today; S16's runner brings it prefetch (D16).
7. **The fleet prefetches through the provider.** `PrefetchedWeather.fetch(default_weather(), <homes' locations>)` replaces `_tmy_by_location`. Each job carries a `PrefetchedWeather` holding only its home's location, so a job pickles one frame, as today. The fleet's public signatures are left to S16, which moves this call into `FleetRunner` (D16).
8. **Additive surface edits land in-leaf (D29).** `WeatherProvider`, `PvgisTmy` and `PrefetchedWeather` join `__all__` in α, with their `FROZEN_SURFACE` / `FROZEN_MEMBERS` (and, if the closure test names it, `FROZEN_CLOSURE`) entries and an "Unreleased on main" line. They are the consumer's replacement for `set_weather_cache`, so they are frozen before it is retired. `default_weather` and the variable-name constant stay module-level (`solar_challenge.weather`), for roots, not consumers.
9. **Retirements are one held leaf, ε (D4, D29).** It retires `_weather_cache`, `get_weather_cache`, `set_weather_cache` and (Q1 default) `get_tmy_data`. γ first moves every in-repo caller off them, so ε deletes, edits the frozen tables and writes the "Unreleased on main" lines S29 folds into the release.
10. **`get_tmy_data` is retired at the bump (Q1 default).** It is two providers behind a boolean flag, resolving an implicit default directory. D4 says streams take their clean option, so one public way to obtain weather survives. The recipe line: `get_tmy_data(loc)` becomes `PvgisTmy(WeatherCache()).get(loc)`, and `use_cache=False` becomes `PvgisTmy(None).get(loc)`. If the lead keeps it instead, ε leaves it as `(default_weather() if use_cache else PvgisTmy(None)).get(location)` with its `FROZEN_SURFACE` entry unchanged; nothing else in this PRD moves.
11. **A cache entry is one file (fk-e4549a3a6b54).** Its rules:
    - `put` writes the frame and the metadata `get` needs (timezone name, frequency) into one file, staged beside the entry and replaced by one `os.replace`.
    - `get` returns the stored frame exactly, or `None` when there is no entry: floats bit for bit, index in the zone and frequency it was put in, index name kept. An entry file it cannot decode raises `ValueError` naming the file, never a degraded frame.
    - The five unread keys go. `_KEY_VERSION` becomes 3, so older entries are misses.
    - Encoding constraints: no new core dependency (`pyarrow` is web-only) and no pickle (unsafe to load, fragile across pandas releases).

    The suggested encoding is a CSV whose first line is a JSON object holding `timezone` and `freq`, read back as task 464 reads today's CSV (UTC instants, then `tz_convert`, `float_precision="round_trip"`). The leaf may choose another encoding under the same constraints; B8 decides.
12. **`_require_timezone_name` stays.** `put` still records a zone by its `str`, so it still refuses a zone whose `str` names none.

## Contract (seam: the weather provider; owner this PRD; readers `home`, `fleet`, `cli/home`, `web/app`, `web/jobs`, scripts, tests; downstream S16's `FleetRunner`)

```python
# src/solar_challenge/weather.py

CACHE_DIR_VARIABLE = "SOLAR_CHALLENGE_WEATHER_CACHE_DIR"
"""The environment variable naming the directory WeatherCache() uses when given none."""

class WeatherCache:
    def __init__(self, cache_dir: Path | None = None) -> None:
        """cache_dir; else the directory CACHE_DIR_VARIABLE names, when set and non-empty; else DEFAULT_CACHE_DIR."""
    # get/put/clear/invalidate keep their frozen signatures; δ changes the entry format (decision 11).

class WeatherProvider(Protocol):
    """Supplies the hourly weather a simulation at a location runs on."""
    def get(self, location: Location) -> pd.DataFrame:
        """One year of hourly weather for location: temp_air, ghi, dni and dhi at least, on a DatetimeIndex."""

@dataclass(frozen=True)
class PvgisTmy:
    """PVGIS's TMY for each location, scaled to the point's 2005-2020 mean annual GHI
    (docs/tmy-irradiation-scaling.md): read from cache, else fetched and put there; with no cache, fetched on every get."""
    cache: WeatherCache | None
    def get(self, location: Location) -> pd.DataFrame:
        """Raises WeatherDataError exactly where get_tmy_data does today."""

@dataclass(frozen=True, eq=False)
class PrefetchedWeather:
    """Weather already in memory for the locations it holds; it pickles, so a worker reads no cache and no network."""
    frames: dict[Location, pd.DataFrame]          # a copy taken at construction; a mappingproxy would not pickle
    def get(self, location: Location) -> pd.DataFrame:
        """The held frame; LookupError naming location and the locations held, for any other."""
    @classmethod
    def fetch(cls, weather: WeatherProvider, locations: Iterable[Location]) -> "PrefetchedWeather":
        """weather.get once for each distinct location, in this process, in first-seen order."""

def default_weather() -> PvgisTmy:
    """The weather a composition root uses when it is given none.
    Until the S29 bump: PvgisTmy(get_weather_cache()). After it (ε): PvgisTmy(WeatherCache())."""

# src/solar_challenge/home.py
def simulate_home(
    config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    *,
    weather: WeatherProvider,
) -> SimulationResults: ...

# src/solar_challenge/web/jobs.py
class JobManager:
    def __init__(self, max_workers: int = 2, *, simulate_home: HomeSimulator, new_id=..., clock=...) -> None: ...
    # HomeSimulator is unchanged: Callable[[HomeConfig, Timestamp, Timestamp], SimulationResults]
```

| invariant | enforced at construction | enforced at use |
|---|---|---|
| I1. A simulation's weather is an argument; nothing below the roots and facades reads a process-wide weather source. | `simulate_home`'s required keyword (mypy strict; `TypeError` at call) | grep: `home.py` names no `get_tmy_data`, `get_weather_cache` or `default_weather`; after ε the global does not exist |
| I2. A worker process receives its weather in its job. | `PrefetchedWeather` pickles; jobs carry one | B5 under forkserver and spawn |
| I3. One default weather source and one default-directory rule. | `default_weather()`; `WeatherCache.__init__` | every root calls `default_weather()`; no other module reads `CACHE_DIR_VARIABLE` |
| I4. A prefetch fetches each distinct location once. | `PrefetchedWeather.fetch` | B2's counting provider |
| I5. A provider never answers for a location it was not given. | `PrefetchedWeather.get` refuses | B2 |
| I6. A cache entry is one file replaced whole; `get` returns the stored frame or `None`, or raises naming the file. | `put`'s one `os.replace` | B8 |

## Boundary-test sketch (both sides of the seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Cache-backed provider | `WeatherCache(tmp)` seeded by `put(synthetic_june_weather("2024-06-21"), "tmy", Location.bristol())`; `pvlib.iotools.get_pvgis_tmy` and `get_pvgis_hourly` patched where `test_weather.py` patches them today | `PvgisTmy(cache).get(bristol)` equals the seeded frame (`check_exact`); a miss fetches once and puts, so a second `get` makes no request; `PvgisTmy(None).get` fetches on every call and writes nothing; `pickle.loads(pickle.dumps(PvgisTmy(cache))).cache.cache_dir == cache.cache_dir` | α |
| B2 | Prefetch and refusal | a counting provider over Bristol and Bath frames | `PrefetchedWeather.fetch(counting, [bristol, bath, bristol])` calls `get` twice; `.get(bath)` is Bath's frame; `.get(Location(51.48, -3.18))` raises `LookupError` naming that location and both held ones; the result round-trips through pickle | α |
| B3 | The variable configures a root (user-facing) | an empty working directory; `<dir>` seeded with Bristol's 2024-06-01 day; the test's proxy variables refusing the network; `solar-challenge home quick 4 --days 1` run as a child process with `SOLAR_CHALLENGE_WEATHER_CACHE_DIR=<dir>` | exit code 0; the summary table shows generation above 0 kWh; the working directory has no `.cache/weather`; the window records no refused destination (today the child reads `./.cache/weather`, misses, and reaches `re.jrc.ec.europa.eu`) | α |
| B4 | `simulate_home` requires weather | `test_home.py`'s June fixtures | `simulate_home(config, d, d)` raises `TypeError` naming `weather`; every existing weather-fed assertion in `test_home.py`, `test_home_grid_charging.py` and `test_home_heat_pump.py` holds with `weather=PrefetchedWeather({config.location: frame})`; the heat-pump year-length refusal still names the row count | β |
| B5 | Workers cannot miss (task-460 class) | `TestParallelFleetWeather`'s Bristol and Bath TMYs seeded in the test's cache; start methods forkserver and spawn | `simulate_fleet` and `simulate_multi_sweep_iter`, sequential and parallel, give each home exactly `simulate_home(home, d, d, weather=default_weather())`'s results (`check_exact`) | β |
| B6 | Roots pass weather | `CliRunner` `home run` and `home quick` with the test's cache seeded; `create_app` from `tests/_web_app.py` and a 1-day home job and a 2-home fleet job through `/api/simulate/*` | both CLI commands exit 0 offline; both jobs complete with stored results; `JobManager()` raises `TypeError` naming `simulate_home` | β |
| B7 | The test window configures the default (no global) | the conftest after γ | a fast test that runs `home quick` through `CliRunner` unseeded fails at teardown naming `re.jrc.ec.europa.eu`; seeded through `weather_cache`, it passes; a child CLI the test starts reads the same cache; a slow test that requests `weather_cache` errors at setup as today; no `set_weather_cache(` remains in `tests/conftest.py`, `tests/unit/test_e2e_job_wait.py`, `tests/unit/test_fast_tests_run_offline.py` or `scripts/` | γ |
| B8 | One-file entry | frames: the synthetic June day (Europe/London, `h`); a 2024-03-30..04-01 hourly frame across the clock change; a UTC frame without freq named `time(UTC)` like PVGIS's; an entry in today's CSV + `.meta.json` form copied in from a committed fixture; a file of garbage at the entry's path | each `put` leaves exactly one file under `cache_dir` and `get` returns the frame exactly (values, zone, freq, index name); the old-form entry is a miss; the garbage entry raises `ValueError` naming its path; `clear()` removes old-form files too | δ |
| B9 | Retirement | after ε | `solar_challenge.set_weather_cache` and `solar_challenge.get_weather_cache` (and `get_tmy_data`, Q1 default) raise `AttributeError`; `from solar_challenge.weather import set_weather_cache` raises `ImportError`; the frozen-surface test pins the new name set; the verify passes | ε |

## Pre-conditions for activating

- None upstream: wave 1, no program dependencies.
- Before filing, run contract §8 step 1 (the key lookup over `$.x_finding_key`) for all three keys. The report's mechanical-filings table names none for this stream.
- ε is filed held (`x_seam_wait = {stream: S29, contract: "the surface bump release window"}`) and excluded from this batch's `commit_planning`.

## Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S16 Fleet execution policy | produces for | `WeatherProvider`, `PrefetchedWeather.fetch`, `default_weather()`, `simulate_home(weather=)`; `FleetRunner` holds a provider and prefetches per `simulate` call; the fleet's interim `default_weather()` calls and the dashboard fleet job's per-home reads move into the runner | S15 (provider, prefetch); S16 (runner, its construction at the roots, the web fleet job) | S16 depends on β (D16; program) |
| S29 Surface bump | consumes | ε's retirements and the "Unreleased on main" lines of α, δ and ε; the consumer recipe's Network I/O section | S29 releases ε and writes the release section | ε held with `x_seam_wait` |
| S5 Scenario grammar | file overlap | `config.run_parameter_sweep` (β passes `weather=default_weather()` there if it still exists; S5 deletes it) | S5 (deletion) | order-agnostic, no dependency |
| S23 Surface lock | file overlap | α and ε edit `FROZEN_*` and `__init__`'s three tables; S23 restructures that test module and derives the count | S23 (module shape) | parallel; the second to land carries the other's entries |
| S19 Run store | file overlap | β makes `JobManager.simulate_home` required and binds it in `create_app`; S19 constructs `JobManager` with the app's `RunStorage` and locks `DATA_DIR` in `create_app` | each its own argument | parallel wave 1 |
| S10, S12, S2, S3 | file overlap | `home.py` (`simulate_home`'s body and signature); S12's load composition reads the frame `_hourly_weather` returns | — | no semantic seam |

## Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`. Priorities follow severity; none is high or critical, so none joins the trigger-chain gate (task 772).

- **α. Weather providers, the root default, and the cache-directory variable.** Files: `weather.py`, `__init__.py` (`__all__`, the lazy-loader map, the `TYPE_CHECKING` imports), `tests/unit/test_weather.py`, a CLI subprocess test (B3), `tests/unit/test_public_api_surface.py` and `tests/unit/test_init_lazy_surface.py` (count), `docs/domain-library-consumption.md` (Unreleased: three names join `__all__`; `WeatherCache()` reads the variable; `get_weather_cache()` no longer memoises).

  The contract's `CACHE_DIR_VARIABLE`, `WeatherProvider`, `PvgisTmy`, `PrefetchedWeather` and `default_weather`. `get_tmy_data` delegates: `(default_weather() if use_cache else PvgisTmy(None)).get(location)`.

  Signal: B3. `SOLAR_CHALLENGE_WEATHER_CACHE_DIR=<seeded dir> solar-challenge home quick 4 --days 1` runs offline in an empty directory and creates no `.cache/weather` there; today it fetches PVGIS. B1, B2.

  Unlocks β, γ, δ. Keys: fk-06035cd76226, fk-44fdf5fb356b. Priority medium.
- **β. `simulate_home` takes its weather; every caller passes it.** Files:
  - `home.py` (`simulate_home`, `_hourly_weather`, docstrings);
  - `fleet.py` (`_tmy_by_location` deleted; `PrefetchedWeather.fetch(default_weather(), …)`; the two worker functions take a provider);
  - `cli/home.py` (`run`, `quick`);
  - `web/app.py` (`create_app` binds `partial(simulate_home, weather=default_weather())`);
  - `web/jobs.py` (`JobManager.simulate_home` required);
  - `config.py` (`run_parameter_sweep`, if S5 has not deleted it);
  - every test calling `simulate_home` (111 calls in 22 files at `d316d0e`: `weather_data=frame` becomes a `PrefetchedWeather` of the home's location through a `tests/_synthetic_weather` helper, slow tests take `default_weather()`, weather-cache tests take `PvgisTmy(weather_cache)`);
  - the `JobManager(...)` constructions that pass no `simulate_home=` (13 in `tests/unit/test_web_jobs.py` at `d316d0e`);
  - `tests/e2e/conftest.py`;
  - `docs/domain-library-consumption.md` (the Network I/O paragraph on how the fleet reads weather);
  - `review/briefing.yaml` (the ProcessPoolExecutor key decision's "the weather cache is pre-warmed": workers now receive their weather in the job).

  Signal: `simulate_home(config, start, end)` raises `TypeError` naming `weather` (today it reads the global and may fetch PVGIS). B4, B5, B6; mypy strict passes with no `weather_data` left in `src`.

  Prereq α. Unlocks γ, ε; S16 depends on it. Keys: fk-44fdf5fb356b, fk-06035cd76226. Priority medium.
- **γ. Tests and scripts construct their weather; the conftest window sets the variable.** Files:
  - `tests/conftest.py` (`_open_offline_window` sets `CACHE_DIR_VARIABLE` to its directory for the window, as `refusing_network` sets proxy variables, and calls no `set_weather_cache`; `weather_cache` returns the window's cache; the slow-test error and docstrings name `default_weather`);
  - `tests/unit/test_fast_tests_run_offline.py` (the guard's self-tests restated for the variable and roots; the 775ef88 case becomes "a broader-scoped fixture passes its provider explicitly; the window's default stays the test's own");
  - `tests/unit/test_e2e_job_wait.py` (its session fixture sets the variable);
  - `scripts/measure_mppt_window.py` and `scripts/measure_pv_performance_ratio.py` (`PvgisTmy(WeatherCache(args.cache_dir)).get(...)`, `--cache-dir` defaulting to the variable's rule);
  - every in-repo caller of `get_tmy_data` outside `tests/unit/test_weather.py`'s facade tests (`tests/integration/test_pvgis.py`, `test_pv_performance_ratio.py`, `test_community_fleet.py`, `tests/unit/test_fleet.py`, `test_pvgis_lane.py`'s message), moved to `PvgisTmy`;
  - `CLAUDE.md`'s "Offline fast tests" bullet ("pass `weather`", "`default_weather()` reads the test's own empty `weather_cache`").

  Signal: B7. A fast test that runs `home quick` unseeded fails naming PVGIS with no global installed; a child process the test starts reads the test's cache. Today a child reads `./.cache/weather`. After γ, the only callers of `set_weather_cache`, `get_weather_cache` and `get_tmy_data` are `weather.py` itself and `test_weather.py`'s tests of those names.

  Prereq β (shared test files). Unlocks ε. Keys: fk-44fdf5fb356b, fk-06035cd76226. Priority medium.
- **δ. One self-describing file per cache entry.** Files: `weather.py` (`WeatherCache.get`, `put`, `invalidate`, `_meta_path` deleted, `_KEY_VERSION = 3` with its docstring line), `tests/unit/test_weather.py`, a committed old-form fixture entry beside that test, `docs/domain-library-consumption.md` (Unreleased: entries written before are ignored; rebuild a pre-built cache with `put`), `review/briefing.yaml` (the consumer-footgun comment's "key version 2" becomes 3).

  Signal: B8. After a seeded `home quick`, the cache directory holds one file per location (today two). A garbage entry raises `ValueError` naming its path; today a missing sidecar returns a frame at `UTC+01:00` with no freq.

  Prereq α (same file). Unlocks ε. Key: fk-e4549a3a6b54. Priority low.
- **ε. Retire the global weather cache at the bump (held: `x_seam_wait = {stream: S29, contract: "the surface bump release window"}`).** Files:
  - `weather.py`: `_weather_cache`, `get_weather_cache` and `set_weather_cache` deleted, `default_weather()` returning `PvgisTmy(WeatherCache())`, and `get_tmy_data` deleted (Q1 default);
  - `__init__.py`'s three tables;
  - `tests/unit/test_public_api_surface.py` (or S23's successor module);
  - `tests/unit/test_weather.py` (the retired names' tests);
  - `docs/domain-library-consumption.md` (an Unreleased line per retirement, with the recipe; the Network I/O section shows `PvgisTmy(WeatherCache(dir))` and the variable);
  - the docs naming `get_tmy_data` (`tmy-irradiation-scaling.md`, `pv-system-losses.md`, `pv-inverter-string-matching.md`, `pv-annual-yield-benchmark.md`, `scripts/measure_tmy_irradiation.py`'s docstring);
  - `review/briefing.yaml` (the footgun comment's "inject a WeatherCache mock").

  Signal: B9. `solar_challenge.set_weather_cache` raises `AttributeError` (today it installs the global), and the verify passes with no global anywhere.

  Prereqs β, γ, δ; S29 releases it. Keys: fk-06035cd76226, fk-44fdf5fb356b. Priority medium.

DAG: α → {β, δ}; β → γ; {β, γ, δ} → ε (held). S16 depends on β.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- `no-silent-fail-soft`: `simulate_home`'s silent fallback goes. `PrefetchedWeather.get` refuses an unheld location instead of fetching. `WeatherCache.get` raises on an unreadable entry instead of returning a degraded frame. An empty variable is documented as unset.
- `one-fact-one-home`: the default directory has one rule (`WeatherCache.__init__`) and the default provider one function (`default_weather`). Until ε, `set_weather_cache` and the variable both steer the default. The override wins, and ε, deadline the S29 bump, removes it. `get_tmy_data` delegates to the providers, so a TMY is produced in one place.
- `holds-owned-and-bounded`: ε is held with an owner (S29) and a stated release window.
- `guards-exercise-behaviour`: every grep `delivered_check` has a behaviour row in the boundary sketch.

No waivers.

## Out of scope

- `FleetRunner`, the fleet's public signatures, the `simulate` callable threaded through finance and optimize, `CliFleetSimulator`, and the dashboard fleet job's loop: S16, which reads weather through this PRD's provider (D16).
- Moving the dashboard's weather cache under `DATA_DIR`. The roots keep today's directory, `./.cache/weather`, unless the variable says otherwise.
- The PVGIS request policies (fk-753ec8e6e149, mechanical, Phase 5) and the TMY scaling itself.
- `pv.simulate_pv_output(config, location, weather_data)`: frozen, takes a frame, unchanged.
- The consumer re-pin and the release section: S29.

## Open questions

For the lead:

1. **Q1 — `get_tmy_data` at the bump.** Retire it (this PRD's default, decision 10: one public way to obtain weather, no boolean-selected providers or implicit directory), or keep it as a facade over `default_weather()` and `PvgisTmy(None)` with its frozen form unchanged. Only ε's file list differs.
2. **Q2 — `SOLAR_CHALLENGE_WEATHER_CACHE_DIR` (decision 4).** It is a new user-facing environment variable, read by `WeatherCache()` alone. The alternative is per-root seams (Click context, a `create_app` parameter), which collide with S16 and do not reach a CLI subprocess. Confirm the variable and its name.

Tactical, decided in the leaf:

3. How a fleet job narrows the prefetched provider to its home's location (a fresh `PrefetchedWeather({loc: frame})` per job, or `fetch` over the prefetched provider). Decide in β; the payload stays one frame per job.
4. The test helper's name and shape for "this frame at this home's location" in `tests/_synthetic_weather.py`. Decide in β.
5. The entry encoding within decision 11's constraints. Decide in δ against B8.
6. How B3 starts the CLI as a child (the console script on the environment's `bin`, or `sys.executable -c "from solar_challenge.cli import app; app()"`). Decide in α.
