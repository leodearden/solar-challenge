# Capability manifest — Dispatch configuration below config (review-all stream S2)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/dispatch-configuration-below-config.md`. Each capability a leaf's signal asserts binds to evidence: a symbol read on main (wired into the production path, not only tests), a producer leaf upstream in this batch or another stream's, a measurement taken for this PRD, or a rejection mechanism the leaf builds and its test observes firing. Machine-readable twin: `docs/prds/dispatch-configuration-below-config.capability-manifest.yaml`.

**Code anchors** verified against main `1251be0e621a6037173068d84ae3aea44c45fdce` (2026-10-14), cited by symbol. Measurements: `uv run --locked --extra dev python -I` probes on that SHA, and a `HomeConfig.__init__` wrapper run over the non-slow unit and integration suites (5291 passed; the three surface-lock failures in that run were the wrapper's own signature change, not main).

**Batch verdict: PASS, with three cross-stream producers to wire at decompose.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `bound≤floor`. Out-of-batch producers, all upstream of the leaves that need them: S1-β, the errors leaf with D2's `ValueError` base (α), S11's tariff-clock arm and S3's home-key routing (ε). Intra-batch edges: β→α, γ→α, δ→γ, ε→β.

---

## α — dispatch.py owns the dispatch-configuration types and the strategy factory (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `ConfigurationError` importable below `config` and a `ValueError` (moved types and factory raise it; `dispatch.py` cannot import `config`; the strategy constructors switch to it from `ValueError`) | producer: S1-β (`docs/prds/errors-leaf.md` leaf β: `class ConfigurationError(ValueError)` in `solar_challenge/errors.py`, after S1-α creates the module), upstream, wired as α's out-of-batch dependency; extent: the class with D2's base | PASS (queued prerequisite) |
| `dispatch.py` imports nothing above it today | grep: `dispatch.py` top-level imports are `abc`, `dataclasses`, `datetime`, `enum`, `typing`, `solar_challenge.timebase`; `tariff.py` imports only stdlib and pandas, so adding `tariff` keeps it a leaf | PASS |
| The unknown-tag refusal exists and fires (to be given a path) | rejection-check: `solar-challenge validate config` on a copy of `scenarios/dispatch-comparison.yaml` with `strategy_type: tou_optimised` exits 1 with ERROR row `Invalid strategy_type 'tou_optimised'. Must be one of: self_consumption, tou_optimized, peak_shaving` (observed); α adds the key path via `config._child_path` (block paths `homes[{index}]` are already built by `parse_fleet_config`) | PASS |
| `validate config` surfaces loader refusals as ERROR rows and exits 1 | grep: `cli/validate.py::config` raises `typer.Exit(1)` when `_findings` returns errors (observed exit 1) | PASS |
| Stored-run round trip goes through `RunStorage.save_home_run` / `load_home_run` and the export endpoint | grep: `web/storage.py::RunStorage.save_home_run`, `stored_home_config` → `_deserialize_dataclass(HomeConfig, ...)`; tests `tests/unit/test_web_storage_roundtrip.py::TestEveryFieldShapeRoundtrip`, `tests/unit/test_web_history.py::TestExportAPI` already drive it | PASS |
| The storage deserializer reads a union as its first member (so a tagged rule is needed) | grep: `web/storage._deserialize_value` "A union is read as its first non-None member" | PASS (motivates §5.6, built by α) |
| `get_type_hints(BatteryConfig)` fails in its own module today (1 of 14) | measured by fk-615cbc883512's probe; `battery.py` unchanged since `7dfea36` | PASS (α flips it) |
| Field-population: `BatteryConfig.dispatch_strategy` is populated by the production parsers | grep: `config._parse_battery_config` and `_parse_battery_distribution_config` call `parse_dispatch_strategy_config`; `generate_homes_from_distribution` copies it onto every `BatteryConfig`; `web/simulation_params._parse_battery` and `web/fleet_config.apply_fleet_overlay` set it | PASS |
| Strategy classes the factory builds exist with today's constructors | grep: `dispatch.SelfConsumptionStrategy()`, `TOUOptimizedStrategy(peak_hours)`, `PeakShavingStrategy(import_limit_kw)` | PASS |
| `assert_never` for an exhaustive `match` | `requires-python = ">=3.11"`; `typing.assert_never` is in 3.11 | PASS |

## β — Refuse at construction what the dispatcher would ignore (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `build_dispatch_strategy` exists | producer: α, upstream (intra-batch β→α) | PASS |
| Refusals fire for grid charging under self-consumption, without a tariff, and home `tou_optimized` without a tariff | rejection-mechanism built and bound by β: `tests/unit/test_grid_charge_refusals.py` constructs each combination and observes `ConfigurationError` naming `grid_charging` (or `tou_optimized` and `tariff`) and the strategy | PASS |
| The two honoured combinations still grid-charge (> 0) | measured by f44 at `7dfea36`: home `tou_optimized` + E7 2.080 kWh, battery `peak_shaving` + E7 2.000 kWh; β changes no dispatch arithmetic and at SOH 1.0 γ's basis equals today's (`compute_soh` at age 0 is 1.0) | PASS |
| The platform's shape still grid-charges (BatteryConfig with `grid_charging`, no strategy, own strategy object, tariff) | measured: `simulate_timestep` with `TOUOptimizedStrategy([(16, 19)])` and E7 on such a battery charges from `min_soc_kwh` to the target (inv9 probe, strategy path); β adds no `BatteryConfig` check | PASS |
| `validate config` reports a `HomeConfig` construction error as an ERROR row | grep: `cli/validate.py::_findings` builds the homes through the loaders, so a `ConfigurationError` raised in `HomeConfig.__post_init__` is a loader refusal | PASS |
| `scenarios/bristol-arbitrage.yaml` and `bristol-phase1-flex.yaml` stay valid | read: both carry a `tariff:` (economy_7) and `grid_charging`, and route through home/fleet-level `tou_optimized` with no battery strategy, the honoured tariff-TOU route | PASS |
| Blast radius of the refusal on existing tests | measured: 22 tests in 8 files build a home with a battery that β refuses (PRD §10 β lists them); 3 build both levels, which β leaves alone (§12 Q8) | PASS (sized) |
| The briefing key_decision β replaces exists | grep: `review/briefing.yaml` "SelfConsumptionStrategy deliberately accepts-but-ignores the grid-charge context" | PASS |

## γ — The Battery answers the grid-charge target on its effective capacity (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `Battery.effective_capacity_kwh`, `max_soc_fraction`, `soc_fraction` exist on the production path | grep: `battery.Battery` properties; `Battery.charge` clamps at `available_charge_capacity_kwh` | PASS |
| Invariant 9: end `soc_fraction` = 0.5 ± 1e-6 after 180 cheap minutes, both paths, SOH {1.0, 0.7}, from the midpoint and from `min_soc_kwh` | measured today: 0.500000 at SOH 1.0 (all four), 0.714286 at SOH 0.7 (all four). Achievability: on the last charging step the controller requests `gap / charge_efficiency / dt`, storing exactly the gap (arithmetic identity; float error ~1e-15 ≪ 1e-6); reach: 2.8 kWh needed at SOH 0.7 from the floor vs 5 kW × 0.975 × 3 h = 14.6 kWh available; spread gate passes on E7 defaults (0.09 / 0.950625 < 0.25); 01:00-04:00 is E7 off-peak | PASS |
| Target above the ceiling stops requesting once full | measured today: SOC at 0.9 of effective, `TOUOptimizedStrategy` still requests 5.0 kW; γ's cap makes the gap 0 → request 0.0 | PASS |
| CLI signal: `battery_soc_kwh` at 07:29 on 2024-01-15 is 1.75 kWh for `bristol-arbitrage.yaml` with `soh: 0.7`, target 0.5 | measured today with `simulate_home` (sunless weather, January night so PV is 0 under any weather): strategy `tou_optimized`, SOC 1.6255 kWh at 00:29 (below target after the 00:00-00:30 peak discharge), **2.5 kWh** at 07:29 (0.714 of 3.5); fixed value 0.5 × 3.5 = 1.75 because the cheap branch holds on shortfall and charges to the target | PASS |
| `home run` writes `battery_soc_kwh` to its CSV | grep: `SimulationResults.battery_soc` column metadata `battery_soc_kwh`, written by `to_dataframe` | PASS |
| No consumer constructs `GridChargeContext` or calls `compute_grid_charge_power_kw` | read: `solar-challenge-platform` main imports `GridChargeContext` only as an annotation in `simulator/physics.py`; no call of `compute_grid_charge_power_kw` | PASS |
| Task 632 is the same defect | read: task 632 pending, files `flow.py`, `dispatch.py`, `config.py`, `tests/unit/test_flow.py` | PASS (absorbed) |

## δ — One owner of the SOH-derated SOC envelope (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| The two throwaway-`Battery` readers exist | grep: `gridservices.compute_fleet_spare_capacity_kw` `Battery(battery_config).min_soc_kwh`; `web/charts.battery_soc_chart` `Battery(battery_config)` | PASS |
| No other `Battery(` construction outside `home.py` and `community.py` | grep `Battery(` over `src/solar_challenge`: `home.simulate_home`, `community.simulate_community`, plus the two readers | PASS |
| `compute_soh` and `nominal_usable_capacity_kwh` exist for `resolved_soh` | grep: `battery.compute_soh`, `BatteryConfig.nominal_usable_capacity_kwh`; `Battery.__init__`'s resolution reads them | PASS |
| Chart lines at 1.4 and 5.6 kWh for 10 kWh, SOH 0.7, fractions 0.2 / 0.8 | identity: 10 × 0.7 × 0.2 and 10 × 0.7 × 0.8; the chart draws `min_soc_kwh` / `max_soc_kwh` lines today (task 645) | PASS |
| `Battery.grid_charge_target_kwh` exists to re-derive | producer: γ, upstream (δ→γ) | PASS |

## ε — Retire the home- and fleet-level dispatch key at the bump (held leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| A battery-level `tou_optimized` with no `peak_hours` runs the tariff clock | producer: S11's tariff-clock arm leaf, upstream (out-of-batch dependency, id from the lead) | PASS (queued prerequisite) |
| The home-level key runs through the same factory arm, so the migrated file's grid charge equals the old one's | producer: S3's routing leaf (D6), upstream; equality holds by construction once both routes call one arm; the pre-migration figure is measured when ε is filed | PASS (queued prerequisite) |
| The surface bump window | producer: S29 releases ε (`x_seam_wait`) | PASS (held) |
| The keys and files to retire exist | grep: `home.HomeConfig.dispatch_strategy: str = "greedy"`, `config.FleetDistributionConfig.dispatch_strategy`, `_parse_fleet_dispatch_strategy`, `generate_homes_from_distribution`'s `or "greedy"`, `scenario_writer._home_block`'s `"dispatch_strategy"`; scenario files `bristol-arbitrage.yaml` (home level) and `bristol-phase1-flex.yaml` (fleet level) | PASS |
| The refusal of the old key fires | rejection-mechanism built and bound by ε: a test loads the pre-migration file and observes the refusal naming `battery.dispatch_strategy` | PASS |
