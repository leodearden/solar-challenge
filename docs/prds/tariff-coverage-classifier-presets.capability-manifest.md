# Capability manifest — Tariff: coverage invariant, one cheap-period classifier, named preset rates (review-all stream S11)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/tariff-coverage-classifier-presets.md`. Each capability a leaf's signal asserts binds to evidence: a symbol read on main (wired into the production path, not only tests), a producer leaf upstream in this batch, another stream's or an in-flight task, a measurement taken for this PRD, or a rejection mechanism the leaf builds and its test observes firing. Machine-readable twin: `docs/prds/tariff-coverage-classifier-presets.capability-manifest.yaml`.

**Code anchors** verified against main `9d7b67e7ba8091f1252ec067cea277f2b19be4d3` (2026-10-14), cited by symbol. Measurements: `uv run --locked --extra dev python -I` probes and `solar-challenge` CLI runs on that SHA, with the Bristol TMY in the local weather cache; task 708's scheduler read from branch `task/708` (`44eecaa`).

**Batch verdict: PASS, with four out-of-batch producers to wire at decompose.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Out-of-batch producers, all upstream of the leaves that need them: S1-β (α), S2 α and S2 β (β; S2 β also for δ), task 708 (δ). S29 releases ε. Intra-batch edges: β→α, δ→α, ε→α; γ has none.

---

## α — TariffConfig tiles the day and owns the cheap-period classifier (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `ConfigurationError` importable below `config` and a `ValueError` (`TariffPeriod`'s refusals switch from `ValueError`) | producer: S1-β (`docs/prds/errors-leaf.md` leaf β, `class ConfigurationError(ValueError)` in `solar_challenge/errors.py`), upstream, out-of-batch dependency; extent: the class with D2's base | PASS (queued prerequisite) |
| `validate config` shows a tariff constructor refusal as an ERROR row and exits 1 | observed: a `flat_rate` block with `rate_per_kwh: -0.1` prints ERROR "Rate cannot be negative, got -0.1 £/kWh", exit 1 (`cli/validate` builds the homes through the loaders, `config._build_custom_tariff` calls `TariffConfig(...)`) | PASS |
| Gap, overlap and NaN refusals exist and fire | rejection-check today: the three scenarios print "Configuration is valid", exit 0, so the rejection is **absent on main** and α builds it; bound by α's `tests/unit/test_tariff_tiling.py` (invariant 2) and the CLI rows of §9 row 2, which observe `ConfigurationError` naming `23:00-07:00`, `06:00-12:00` and the rate | PASS (built and bound by α) |
| Four-period run reports 4.8 kWh / £0.60 after α | measured today: `home run` on `bristol-arbitrage.yaml` with the four-period tariff, 2024-01-10: 10.2 kWh / £1.67; with the five-period split: 4.8 kWh / £0.60. Identity: the two tariffs charge equal rates at every minute, so after α their `cheap_minutes_of_day` are equal (duration-weighted mean 0.1896 for both) and the flows are equal; the five-period classification is unchanged by α (0.10 ≤ 0.1896 cheap, 0.20 > 0.1896 not, as 0.20 > 0.19 today), so its figures stand. S2 γ's effective-capacity basis equals today's at SOH 1.0 (the file's battery is age 0) | PASS |
| The classifier's current readers exist | grep: `flow._is_cheap_period` is called by `flow._build_grid_charge_context` and `flow.simulate_timestep_tou`; no other `src` reader | PASS |
| `get_rate`'s callers need no change | grep: `flow` (2), `home.simulate_home` (1), `tariff.calculate_bill`; signature frozen and unchanged | PASS |
| Two-rate tariffs classify as today | identity (PRD §5.2) and measured: E7 / E10 / flat 0.25 give 420 / 600 / 0 cheap minutes under both the list mean and the weighted mean | PASS |
| Surface table to extend | grep: `FROZEN_MEMBERS["TariffConfig"]` in `tests/unit/test_public_api_surface.py` pins `peak_rate`, `mean_period_rate`, `get_rate` and the three classmethods | PASS |
| Briefing conventions section for invariant 2's line | grep: `review/briefing.yaml` top-level `conventions:` | PASS |
| Task 748's test stays green | read: `tests/unit/test_tariff_period_time_cache.py`; 748 (in merge phase) asserts through `get_start_time`/`get_end_time`, which α leaves | PASS |

## β — TOU dispatch on the tariff clock; peak_hours a checked override; no grid charging without a cheap period (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `TOUOptimizedStrategyConfig`, `build_dispatch_strategy`, `_require_valid_peak_hours` | producer: S2 α (`docs/prds/dispatch-configuration-below-config.md` §5.1, §5.3), upstream, out-of-batch dependency; extent: the variant, the union's factory with its `tariff` parameter, the shared validator | PASS (queued prerequisite) |
| Refusal arms, `HomeConfig.__post_init__` calling the factory, `_runs_tariff_tou` | producer: S2 β (§5.3 of S2's PRD), upstream, out-of-batch dependency; extent: β adds one condition beside S2 β's two | PASS (queued prerequisite) |
| `TariffConfig.is_cheap_at`, `cheap_minutes_of_day`, `describe_minutes_of_day` | producer: α, upstream (β→α) | PASS |
| Battery-level `tou_optimized` without `peak_hours` is refused today | observed: `validate config` on the `bristol-arbitrage.yaml` copy prints ERROR "tou_optimized strategy requires 'peak_hours' parameter" | PASS (β lifts it) |
| The copy's run equals the unmodified file: 7.9 kWh, £1.34 | measured: CLI on the unmodified file, 2024-01-15: Grid Import 7.9 kWh, Grid Import Cost £1.34; a `TOUOptimizedStrategy` subclass whose period comes from the classifier, run through `simulate_home`'s strategy route with the tariff passed to `simulate_timestep`: 7.904248 kWh, £1.336699, grid charge 2.124508 kWh, equal to the tariff route; β's arm builds exactly that strategy | PASS |
| `[[7, 9]]` under Economy 7 is accepted today | observed: "Configuration is valid"; rejection **absent on main**, built by β and bound by `tests/unit/test_tou_tariff_clock.py` observing `ConfigurationError` naming `07:00-07:30` (07:00-07:30 is in E7's 00:30-07:30 cheap period) | PASS (built and bound by β) |
| Flat tariff + grid charging refusal | built by β; bound by rows in `tests/unit/test_grid_charge_refusals.py` (S2 β's file) observing `ConfigurationError` naming `grid_charging`, the tag and the tariff; flat 0.25 has 0 cheap minutes (measured) | PASS (built and bound by β) |
| The override and the context cannot disagree | identity: with the D7 check, every peak minute is outside `cheap_minutes_of_day`, and the context's `is_cheap_period` is `is_cheap_at` of the same tariff | PASS |
| Web defaults to move | grep: `dispatch_peak_end: 21` in `simulate/home.html`, `dispatchPeakEnd: 21` in `fleet-simulator.js`; 16-21 covers E10's cheap 20:00-21:00 | PASS |
| Tests that build a now-contradicting home | grep: `tests/unit/test_home_grid_charging.py` builds `peak_hours=[(7, 24)]` with `TariffConfig.economy_7()` (07:00-07:30 cheap); the custom 00:00-07:00 fixture with `(7, 24)` does not contradict; full count taken when filed | PASS (sized at filing) |
| Briefing line to extend | grep: `review/briefing.yaml` "A home only grid-charges if it uses a tou_optimized or peak_shaving strategy with a tariff AND a GridChargeConfig" | PASS |

## γ — Economy preset rates in one table, read by the dashboard (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| Routes already hand a server table to both simulate pages | grep: `web/routes.simulate_home_page` and `simulate_fleet_page` pass `seg_presets=SEG_PRESETS`; `partials/tariff-config.html` and `fleet.html` render it | PASS |
| A static script can take a server table through `x-data` | grep: `scenarios/builder.html` `x-data='scenarioBuilder({{ initial_section|tojson }}, {{ script_components|tojson }})'` | PASS |
| The literals to replace | grep: `tariff_peak_rate: 0.35`, `tariff_off_peak_rate: 0.13` in `simulate/home.html`; `tariffPeakRate: 0.35`, `tariffOffPeakRate: 0.13` in `fleet-simulator.js` | PASS |
| A rate-less economy import is refused today | read: `web/fleet_scenario._FORM_TARIFF_SETTINGS` reads both economy rates with `_required`, which raises "<path> must be set: the fleet page always sets it"; `tests/unit/test_web_fleet_scenario.py` pins `tariff.peak_rate` | PASS (γ changes it) |
| Classmethod signatures render unchanged when defaults come from the table | `FROZEN_MEMBERS` pins `economy_7(... off_peak_rate: float = 0.09, peak_rate: float = 0.25 ...)`; a default expression reading `PRESET_RATES` evaluates to the same float at definition time, so the rendered form is unchanged | PASS |
| Scenario restatements equal the defaults, so runs do not move | grep: the three files set `off_peak_rate: 0.09`, `peak_rate: 0.25`, `off_peak_start: "00:30"`, `off_peak_end: "07:30"`, equal to `economy_7`'s defaults | PASS |
| The lane's e2e round trip keeps working | read: `tests/e2e/test_fleet_interactions.py::_set_a_fleet_unlike_the_default` fills "Peak Rate (£/kWh)" after choosing Economy 7; γ keeps labels and ids | PASS |
| Default Economy 7 run prices 03:00 at 0.09 | `parse_tariff_config({'type': 'economy_7', 'peak_rate': 0.25, 'off_peak_rate': 0.09})` charges 0.09 at 03:00 (the finding's probe shape); the results page renders the stored `tariff_rate` series | PASS |

## δ — EV off-peak charging reads the home tariff's cheap minutes (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| A per-minute preferred mask and one session scheduler | producer: task 708 (in-progress; branch `task/708` `44eecaa` has `_PREFERRED_WINDOWS`, `_preferred_minutes(mode)`, `_daily_session`, `_earliest_best_start`), upstream, out-of-batch dependency | PASS (queued prerequisite) |
| `cheap_minutes_of_day` | producer: α, upstream (δ→α) | PASS |
| `HomeConfig.__post_init__` for the construction-time refusal | producer: S2 β, upstream | PASS (queued prerequisite) |
| Sessions after δ: E10 00:00-04:59, E7 00:30-05:29, E7 23:00-06:00 from 23:00, flat from 18:00 | measured: 708's `_daily_session` for `EVConfig('7kW', 18, 7, 35.0, 'off_peak')` with each tariff's cheap minutes as the preferred mask | PASS |
| Today's session and its peak-rate minutes | measured on main: 00:30-05:29 (300 minutes); 30 of them at E10's 0.27 | PASS |
| The scenario grammar reads an EV block under `home` | grep: `config._HOME_BLOCK_KEYS` holds `"ev"`; `parse_home_block` calls `_parse_ev_config` | PASS |
| `home run` writes `demand_kw`, which includes the EV | observed: the `home run -o` CSV header carries `demand_kw`; `load.generate_load_profile` adds the EV series into demand (function-local `ev` import) | PASS |
| `simulate_home` has the tariff where it builds the load | grep: `home.simulate_home` holds `config.tariff_config` and calls `generate_load_profile(..., ev_config=config.ev_config)` | PASS |
| The no-tariff refusal exists and fires | built by δ; bound by `tests/unit/test_home_ev_tariff.py` observing `ConfigurationError` naming `smart_charging_mode` at `HomeConfig` construction; today such a file validates | PASS (built and bound by δ) |

## ε — Retire TariffConfig.mean_period_rate at the bump (held leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| The member exists and is pinned | grep: `TariffConfig.mean_period_rate` cached_property; `FROZEN_MEMBERS["TariffConfig"]["mean_period_rate"]` | PASS |
| No `src` reader after α | grep: its one `src` reader is `flow._is_cheap_period`, which α deletes; the platform does not read it | PASS |
| The surface bump window | producer: S29 releases ε (`x_seam_wait`) | PASS (held) |
