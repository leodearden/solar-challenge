# Capability manifest — Weather as an explicit input (S15)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/weather-as-explicit-input.md`. Each asserted capability binds to one kind of evidence:

- a symbol wired on main (`grep:<file>::<symbol>`);
- a producer in this batch that runs upstream (`producer:<label>`);
- a probe whose result was observed (`probe:`);
- a language or library identity (`identity:`).

The YAML twin `weather-as-explicit-input.capability-manifest.yaml` carries the mechanical `delivered_check`s.

**Code anchors** verified against main `d316d0e` (2026-10-14). Probes ran with `uv run --locked --extra dev python -I` (Python 3.12, pandas 3, mypy 2.1.0). Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-extent-short`, `producer-downstream` or `rejection-absent`. Every mechanical check was polarity-checked on `d316d0e`: each `present` pattern is absent today and each `absent` pattern is present today (29 of 29).

- **Held leaf:** ε is held for S29 and is excluded from this batch's `commit_planning` until S29 releases it.
- **Conditional binding:** ε's `get_tmy_data` deletion follows open question Q1's default. It is bound `manual`, so a lead ruling to keep the name changes no mechanical check.

---

## α — providers, the root default, the cache-directory variable (intermediate with its own CLI signal)

| capability asserted | evidence | status |
|---|---|---|
| `WeatherProvider`, `PvgisTmy`, `PrefetchedWeather`, `default_weather`, `CACHE_DIR_VARIABLE` | `producer:α` (new in `weather.py`; absent today: `git grep -E '^class (WeatherProvider|PvgisTmy|PrefetchedWeather)'` is empty) | PASS |
| `typing.Protocol` for the provider; `surface_form` renders it | `identity:` `typing.Protocol` (3.8+); `probe:` `surface_form(WeatherProvider)` is `(*args, **kwargs)`, `member_forms` gives `get: (self, location: Location) -> DataFrame` | PASS |
| `PvgisTmy` pickles with its cache directory (D15 "picklable") | `probe:` `pickle.loads(pickle.dumps(PvgisTmy(WeatherCache(d)))).cache.cache_dir == d` | PASS |
| `PrefetchedWeather` pickles; a mappingproxy field would not | `probe:` a frozen `eq=False` dataclass of `dict[Location, DataFrame]` round-trips; `pickle.dumps(types.MappingProxyType({}))` raises `TypeError` | PASS |
| `fetch` dedupes by location | `probe:` `Location` hashes (frozen dataclass with `eq`); `dict.fromkeys` keeps first-seen order (`identity:`) | PASS |
| `PvgisTmy.get` is today's `get_tmy_data` body | `grep:weather.py::get_tmy_data` reads `get_weather_cache().get("tmy", location)`, then `_fetch_pvgis_tmy`, `_fetch_mean_annual_ghi_kwh_per_m2`, `scale_tmy_to_annual_ghi`, `put` | PASS |
| `get_weather_cache` memoises today (decision 5 removes it) | `grep:weather.py::get_weather_cache` assigns `_weather_cache = WeatherCache()` on first call | PASS |
| `WeatherCache(None)` uses `DEFAULT_CACHE_DIR` today | `grep:weather.py::WeatherCache.__init__` `self.cache_dir = cache_dir or DEFAULT_CACHE_DIR` | PASS |
| B3: `home quick` reaches the default cache through the fallback in a child process | `grep:cli/home.py::quick` calls `simulate_home(home_config, start_date, end_date)` with `Location.bristol()` from 2024-06-01; `grep:home.py::_hourly_weather` calls `get_tmy_data(config.location)` when `weather_data is None`; `get_tmy_data` calls `get_weather_cache()`, which in a fresh process has nothing installed, so after α it builds `WeatherCache()` from the variable | PASS |
| B3: a child's HTTP(S) to PVGIS is refused and fails the test | `grep:tests/_network_guard.py::refusing_network` points the proxy variables at a refusing proxy and leaves only this machine in `NO_PROXY`; `tests/conftest.py::pytest_runtest_teardown` fails a test whose window refused a destination | PASS |
| B3: a seeded 2024-06-01 day covers a 1-day Bristol run | `grep:tests/_synthetic_weather.py::synthetic_june_weather` indexes 24 hours from local midnight; `align_tmy_to_index` matches by UTC time of year, so 05-31 23:00 to 06-01 22:00 UTC covers the local day | PASS |
| Surface: three names join `__all__` in-leaf (D29) | `grep:tests/unit/test_public_api_surface.py::FROZEN_SURFACE` and `FROZEN_MEMBERS`; precedent tasks 326 and 469 (additive in-leaf with an Unreleased line) | PASS |

## β — `simulate_home` takes its weather; every caller passes it (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `simulate_home`'s fallback lives in `_hourly_weather` today | `grep:home.py::_hourly_weather` `get_tmy_data(config.location) if weather_data is None else weather_data` | PASS |
| Callers to change: 5 production sites without weather, 2 fleet workers with a frame | `grep:` `cli/home.py::run`, `::quick`; `config.py::run_parameter_sweep`; `web/jobs.py::JobManager._run_home_simulation`, `::_run_fleet_simulation` via `self._simulate_home`; `fleet.py::_simulate_home_worker`, `::_simulate_home_worker_tagged` | PASS |
| `_tmy_by_location` is the prefetch to replace | `grep:fleet.py::_tmy_by_location`, called by `simulate_fleet_iter` and `simulate_multi_sweep_iter` | PASS |
| A missing required keyword raises `TypeError` naming it (B4, B6) | `identity:` CPython's `missing 1 required keyword-only argument: 'weather'` (and `'simulate_home'` for `JobManager`) | PASS |
| `partial(simulate_home, weather=...)` type-checks as `HomeSimulator` | `identity:` mypy 2.1.0 (locked) carries the `functools.partial` plugin; `HomeSimulator` is `Callable[[HomeConfig, Timestamp, Timestamp], SimulationResults]` (`grep:web/jobs.py::HomeSimulator`) | PASS |
| B5: the task-460 boundary test exists and is the regression twin | `grep:tests/unit/test_fleet.py::TestParallelFleetWeather` (forkserver and spawn, Bristol and Bath seeded, `check_exact`) | PASS |
| Workers receive picklable weather | `producer:α` `PrefetchedWeather` (probe above) | PASS |
| Test blast radius sized | `grep:` 111 `simulate_home(` calls in 22 test files, 39 passing `weather_data`; 13 `JobManager(` constructions in `test_web_jobs.py` without `simulate_home=` | PASS |
| `config.run_parameter_sweep` may be gone (S5) | `producer:S5` deletes it; β edits it only if present, so either order holds | PASS |

## γ — tests and scripts construct their weather; the window sets the variable (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The window may set an environment variable for a test and its children | `grep:tests/_network_guard.py::refusing_network` already sets `HTTP_PROXY`/`NO_PROXY` and their siblings for the window and restores them | PASS |
| The variable steers the roots with no global installed | `producer:α` (`WeatherCache.__init__`, `get_weather_cache` without memo) and `producer:β` (roots call `default_weather()`) | PASS |
| Sites to migrate | `grep:` `set_weather_cache(` in `tests/conftest.py` 3, `tests/unit/test_e2e_job_wait.py` 2, `tests/unit/test_fast_tests_run_offline.py` 1, `scripts/measure_mppt_window.py::main` 1, `scripts/measure_pv_performance_ratio.py::main` 1; `get_tmy_data` in `tests/integration/test_pvgis.py`, `test_pv_performance_ratio.py`, `test_community_fleet.py`, `tests/unit/test_fleet.py`, `test_pvgis_lane.py` | PASS |
| B7: an unseeded fast test reaching PVGIS fails naming it | `grep:tests/conftest.py::pytest_runtest_teardown` message names each refused destination; `grep:tests/unit/test_fast_tests_run_offline.py::test_a_fast_test_that_fetches_a_tmy_fails_and_leaves_no_weather_cache_behind` is the pytester pattern to restate | PASS |
| `CLAUDE.md` names the old mechanism | `grep:CLAUDE.md` "Offline fast tests" bullet: "`get_tmy_data` reads the test's own empty `weather_cache` fixture ... or pass `weather_data`" | PASS |

## δ — one self-describing file per cache entry (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Two files and two replaces today; five unread keys | `grep:weather.py::WeatherCache.put` writes `metadata` with `prefix, latitude, longitude, start_date, end_date, timezone, freq`, then `os.replace(staged_meta, meta_file)` and `os.replace(staged_csv, cache_file)`; `WeatherCache.get` reads `timezone` and `freq`; `probe:` the sidecar's 7 keys | PASS |
| The degraded frame on a missing sidecar (the "today" half of B8) | `probe:` with the sidecar deleted, `get` returns an index at `UTC+01:00`, freq `None` | PASS |
| Bit-exact floats and zone restoration are achievable without a new dependency | `grep:weather.py::WeatherCache.get` already reads `float_precision="round_trip"` and converts UTC instants (task 464's fixes; `tests/unit/test_weather.py` pins them) | PASS |
| Parquet is unavailable to the core | `grep:pyproject.toml` `pyarrow` only under `[project.optional-dependencies] web` | PASS |
| Older entries become misses | `producer:δ` `_KEY_VERSION = 3` changes every key hash (`grep:weather.py::WeatherCache._make_key` puts `v{_KEY_VERSION}` first) | PASS |
| An undecodable entry raises naming its file | rejection mechanism authored in δ; B8 observes it fire (today the same input returns a frame, so the test is RED first) | PASS |
| A PVGIS-shaped frame (UTC, no freq, index `time(UTC)`) round-trips | `probe:` `.cache/weather/tmy_5dc8c8bca218.csv`'s header is `time(UTC),temp_air,...` and its sidecar records `timezone: UTC, freq: null` | PASS |

## ε — retire the global at the bump (held leaf)

| capability asserted | evidence | status |
|---|---|---|
| Nothing in-repo calls the retired names when ε runs | `producer:β`, `producer:γ` (upstream); `delivered_check`s on β and γ | PASS |
| `solar_challenge.<retired name>` raises `AttributeError` | `rejection-check:` `solar_challenge.not_a_public_name` raised `AttributeError: module 'solar_challenge' has no attribute 'not_a_public_name'` (the PEP 562 guard) | PASS |
| `default_weather()` survives with `PvgisTmy(WeatherCache())` | `producer:α` | PASS |
| `get_tmy_data` deleted | conditional on Q1 (default: retire); bound `manual` | PASS (conditional) |
| Release | `producer:S29` releases ε (`x_seam_wait`) | PASS |
