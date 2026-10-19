# Capability manifest — RNG hand-off (review-all S13)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/rng-hand-off.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/rng-hand-off.capability-manifest.yaml`.

**Code anchors** verified against main `c06d12b` (2026-10-17). Main moves fast: cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Every substrate the signals read exists on main. Every RED premise was observed at `c06d12b` (PRD §2). The fix premise for B7 was observed too: a lock around the window gives 0 of 10 differing stored demands.

## α — RNG hand-off and the injectable household model (leaf, high)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Concurrent seeded profiles differ from serial today (B1 RED) | probe at c06d12b: seeds 42/43, 2024-06-01..07, `ThreadPoolExecutor(2)`, 5 trials → 10 of 10 differ | PASS (RED observed) |
| Concurrent dashboard jobs store non-reproducible demand today (B7 RED) | probe: `JobManager(max_workers=2)`, default `simulate_home`, `WeatherCache` seeded with `synthetic_june_weather("2024-06-01", (1.0,)*7)`, `RunStorage.load_home_run(run)[1].demand` vs serial `simulate_home(...).demand` → 10 of 10 differ | PASS (RED observed) |
| A lock and the existing seeding make stored demand equal serial, through the parquet round trip (B7 GREEN premise) | probe: same harness with `_try_richardsonpy_profile` wrapped in a `threading.Lock` → 0 of 10 differ | PASS |
| `JobManager` takes `max_workers` and `simulate_home`; `wait_until_idle`; `RunStorage.load_home_run` returns `SimulationResults` with `.demand` | grep: `web/jobs.JobManager.__init__`, `JobManager.wait_until_idle`, `web/storage.RunStorage.load_home_run`; `tests/unit/web_jobs/test_job_manager.py::_run_storage` builds the DB with `init_db` | PASS |
| Offline weather for a 7-day window | grep: `tests/conftest.py::weather_cache`, `tests/_synthetic_weather.synthetic_june_weather(first_day, irradiance_scale_per_day)` | PASS |
| Unseeded after seeded is a copy today (B3 RED) | probe: two unseeded 2-day profiles each after seed 5 → equal | PASS (RED observed) |
| The synthesis's original clause does not discriminate (decision 12) | probe: two fresh unseeded profiles differ today, so "after a seeded one differs from a fresh one" already holds | PASS (correction justified) |
| Caller's RNG state is clobbered today (B4 RED) | probe: `random.getstate()` before/after a seed-7 call → not equal | PASS (RED observed) |
| Out-of-range seeds silently give Elexon today (B5 RED) | probe: seeds −1, 2**32, 2**40 → profile equals the Elexon profile; `np.random.seed` raises inside the `try` | PASS (RED observed) |
| `random.seed` takes the absolute value of s (C4's sign term is needed) | probe: `random.seed(-7)` and `random.seed(7)` give the same first draw | PASS |
| In-range seeding unchanged pins B2 | identity: `random.seed(s)` and `random.Random(s)` give the same stream; `np.random.seed(s)` and `np.random.RandomState(s)` likewise; C4 keeps today's two calls for 0 ≤ s < 2**32 | PASS |
| richardsonpy draws only from stdlib `random` (decision 5) | grep: in the installed richardsonpy 0.2.3 (`uv.lock`), `random.` calls in `classes/occupancy.py`, `classes/appliance.py`, `classes/lighting.py`, `functions/occupancy_model.py`; no `np.random` / `numpy.random` anywhere | PASS |
| `generate_load_profile` is off the frozen surface (no S29 dependency) | grep: no `generate_load_profile` in `tests/unit/test_public_api_surface.py` or `src/solar_challenge/__init__.py` | PASS |
| Five reach-ins to replace (B8) | grep: `tests/unit/test_load.py` `monkeypatch.setattr(_app_mod, "run_application_simulation"` ×3, `(load_module, "_simulate_stochastic_day"` ×1, `(ElectricityProfile, "power_sim"` ×1 | PASS |
| The zero-energy fallback warning text exists (B8) | grep: `load.scale_profile_to_energy` raises "Cannot scale profile with zero consumption"; `_try_richardsonpy_profile` logs it at WARNING | PASS |
| Only load writes global RNG state today (B9 passes on the real tree after α) | grep: `random\.[a-z_]+\(` and `np\.random\.[a-z_]+\(` in src (excluding `random.Random(`) → only `load._try_richardsonpy_profile`'s two seed calls | PASS |
| The briefing rule to edit in place exists | grep: `review/briefing.yaml` conventions "Fleet simulations must be reproducible from a single seed" | PASS |
| The verify runs web tests | grep: `dark-factory-orchestrator.yaml` `test_command` has `--extra web` | PASS |
| `os.register_at_fork` available (C5) | stdlib on POSIX, CPython ≥ 3.7; requires-python admits only later minors | PASS |

## β — Fleet constructors seed each home by one rule (leaf, low)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| α's test module and Unreleased list exist | producer: α, upstream (β depends on α) | PASS |
| `ConfigurationError` is a `ValueError` | producer: task 774 (S1 β), upstream out-of-batch (β depends on 774; in progress at c06d12b) | PASS |
| `create_uniform` shares one `LoadConfig`; `create_heterogeneous` builds unseeded loads (RED) | grep: `fleet.FleetConfig.create_uniform` passes `load_config=load_config` to every `HomeConfig`; `create_heterogeneous` builds `LoadConfig(annual_consumption_kwh=load_kwh)` | PASS (RED observed by reading) |
| No caller passes a seeded template (the refusal breaks nothing) | grep: every `create_uniform` call in `tests/unit/test_fleet.py` and `tests/integration/test_fleet_simulation.py` passes `LoadConfig(annual_consumption_kwh=3400.0)` | PASS |
| The per-home rule's other home exists to repoint | grep: `config.generate_homes_from_distribution`'s "Derive per-home seed" block, `home_seed = config.seed + i` | PASS |
| config may import from fleet (no cycle) | grep: `config.py` already has `from solar_challenge.fleet import FleetConfig, FleetResults, simulate_fleet` | PASS |
| Both constructors are pinned and the edit is additive (D29) | grep: `FROZEN_MEMBERS["FleetConfig"]` has `create_uniform` and `create_heterogeneous` forms | PASS |
