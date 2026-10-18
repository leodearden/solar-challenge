# Capability manifest — Battery facts: one representation each for efficiency and throughput (review-all S28)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/battery-efficiency-and-throughput.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/battery-efficiency-and-throughput.capability-manifest.yaml`.

**Code anchors** verified against main `9625529565087fb3405efa390cc1c55049b26ce0` (2026-10-15). Main moves fast — cite-by-symbol; re-locate lines at implementation time. Probes ran with `uv run --locked --extra dev python -I` on that tree; the "after β" rows ran on a `git archive` scratch copy of it with only `compute_soh`'s formula changed.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Each rejection a signal asserts is absent today (observed) and delivered by the leaf itself; the mechanism that surfaces it (the reader's `ConfigurationError` as a `validate config` ERROR row) was observed firing. The two cross-stream producers (774 for α; S19 κ for the held γ) are upstream prerequisites.

## α — Round-trip efficiency is a constructor, and every reader builds through it (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A battery block with both forms validates today (the refusal is a real RED) | ran: `solar-challenge validate config` on `example-economy7.yaml` + `charge_efficiency: 0.99` beside `efficiency: 0.95` → `OK Configuration is valid`, exit 0 | PASS (absence observed) |
| A `ConfigurationError` raised in `_parse_battery_config` surfaces as an ERROR row naming `home.battery`, exit 1 | ran: the same file with `bogus: 1` in the battery block → exit 1, ERROR "Unrecognised keys in home.battery: …" (raised by `_refuse_unrecognised_keys` inside `_parse_battery_config`) | PASS (mechanism observed) |
| The community battery goes through the same reader | grep: `config.py` community block calls `_parse_battery_config(…, block_path=_child_path(block_path, "community_battery"))` | PASS |
| `errors.ConfigurationError` subclasses `ValueError`, so the web form's and tests' `except ValueError` still catch α's refusals | producer: task 774 (S1-β), upstream; its delivered check greps `class ConfigurationError\(ValueError\)` | PASS (queued prerequisite) |
| `replace()` of a per-direction efficiency on an `efficiency`-set config is silent today | probe: `replace(BatteryConfig(5, efficiency=0.81, charge_efficiency=0.99, discharge_efficiency=0.7), charge_efficiency=0.99).charge_efficiency` → 0.9, no error | PASS (absence observed) |
| The transitional check accepts every `replace()` that does not touch the efficiencies (finance, optimize) | probe: `BatteryConfig(5, efficiency=0.81).charge_efficiency == math.sqrt(0.81)` → True (exact); `replace(<it>, soh=0.7).charge_efficiency` → 0.9; production `replace` sites change only `soh` (`finance._aged_homes`) and `capacity_kwh` (`optimize._apply_install`) | PASS |
| The defaults pass the transitional check (`BatteryConfig(5, efficiency=0.81)` constructs) | §5.1 carve-out: a per-direction value equal to its declared default (0.975) is accepted | PASS (by construction) |
| `example-economy7.yaml` parses to today's battery | grep: `scenarios/example-economy7.yaml` sets `efficiency: 0.95`; today's `BatteryConfig(efficiency=0.95)` derives `math.sqrt(0.95)` for both directions, which `with_round_trip(0.95)` reproduces through the same function | PASS |
| The web form reaches `BatteryConfig` through one call site | grep: `web/simulation_params._parse_battery` sets `settings["efficiency"]` from `_read_efficiency(params["efficiency_pct"])`, then `BatteryConfig(capacity_kwh=…, **settings)` | PASS |
| The writer's branch exists to delete | grep: `scenario_writer._battery_block` writes `{"efficiency": battery.efficiency}` when set, else the pair | PASS |
| The override caveat exists to delete | grep: `BatteryConfig` docstring "will not take effect" (the `replace()` caveat) | PASS |
| The `BatteryConfig` member table takes an additive entry (D29) | grep: `tests/unit/test_public_api_surface.py` member table for `BatteryConfig` holds `nominal_usable_capacity_kwh` and `default_5kwh`; the consumption guide's "Tag / release convention" section carries "Unreleased on main" lines | PASS |
| Existing tests that pin the override or set both forms are known | grep: `test_battery.py::TestBatteryConfigRoundTripEfficiency::test_efficiency_overrides_explicit_charge_discharge`; `config/test_unrecognised_keys.py::…::test_block_setting_every_recognised_key_is_accepted` (sets `charge_efficiency`, `discharge_efficiency` and `efficiency`); `config/test_home_block.py` and `web_api/test_simulate_home_and_fleet.py` assert `battery_config.efficiency`; `test_scenario_writer.py` builds `efficiency=0.9` | PASS |
| The platform consumer is unaffected | grep at platform `314e8ea`: `config/contract.py::to_battery_config` and `validation/grid_charging.py` build `BatteryConfig` with the per-direction pair or defaults; no `efficiency=` or `.efficiency`, no `compute_soh` | PASS |

## β — `compute_soh` counts one equivalent full cycle per usable capacity discharged (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Today's value is 0.685 | probe: `compute_soh(12.0, 12000.0, 4.0, BatteryConfig(5.0))` → 0.685 | PASS (RED observed) |
| After the change it is 0.61 within 1e-12 | identity: 1 − 0.02·12 − 5e-5·12000/4 = 1 − 0.24 − 0.15 = 0.61; ran on the scratch tree → `0.61`; float error ~1e-16 ≪ 1e-12 | PASS |
| `project_multi_year` reports `1 − 0.015·y` on §9 row 8's battery, within 1e-9 | identity: calendar 0.005·y + cycle 1e-4·(800·y)/8 = 0.015·y; ran on the scratch tree with the existing injected simulate (`tests/unit/test_finance_projection_ageing._make_battery_ageing_simulate`, 800 kWh/yr) and `error_target_pct=0.1`: 25 years, sampled ages (0, 3, 6, 9, 12, 18, 24), max deviation 1.1e-16, final 0.64 > floor 0.6; the same probe on main gives `1 − 0.01·y` (final 0.76) | PASS |
| Accrued throughput is discharge only, so the unit change is the whole fix | grep: `finance._throughput_at` accrues `base.per_home_discharge`; `_simulate_age` fills it from `phys.battery_discharge_kwh` (annualised `SummaryStatistics.total_battery_discharge_kwh`); `_aged_homes` passes it to `compute_soh` with `nominal_usable_capacity_kwh` | PASS |
| Single runs are unchanged (`Battery(...).soh` at age 10 stays 0.8) | grep: `Battery.__init__` passes throughput 0.0; probe on both trees → 0.8; S2 789's `resolved_soh` keeps 0.0 | PASS |
| The five tests the faster fade breaks pass with cycle fade 1e-4, assertions unchanged | ran on the scratch tree: with `efc = throughput / usable`, 5 fail on "the SOH floor clamps no year" (2 in `test_finance_projection_ageing.py`, 3 parametrisations in `test_finance_projection_short_window.py`); with their fixtures' cycle fade at 1e-4, both files pass (19 passed) | PASS |
| No other non-slow test pins the halved value | ran: non-slow unit + integration filtered to soh/finance/battery/ageing/projection/cost_recovery/calibration → 5 failed (above), 1,202 passed | PASS |
| The release note's "board figures move" is real and its size known | ran: `finance run scenarios/bristol-phase1.yaml --assumptions physics --project --cost-recovery` on main and on the scratch tree → solved own-use rate 7.74 → 7.79 p/kWh, min DSCR 1.95× → 1.90×, equity IRR 1.8 % → 1.7 % (PRD §2.1) | PASS |
| The finance doc and consumer guide do not yet state the unit | grep: no "equivalent full cycle" in `docs/cost-recovery-finance-model.md`; no `compute_soh` in `docs/domain-library-consumption.md` | PASS |

## γ — Retire `BatteryConfig.efficiency` at the bump (held leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `BatteryConfig(…, efficiency=0.9)` is a `TypeError` once the field is gone | rejection: a dataclass `__init__` refuses an unexpected keyword (Python), naming it | PASS (mechanism inherent) |
| α has moved every `src` construction off the field | producer: α, upstream (γ depends on α) | PASS |
| The scenario key keeps working | producer: α's reader reads `efficiency:` through `with_round_trip`, not the field | PASS |
| Stored runs with `efficiency` load after migration | producer: S19 κ (`RunDocumentStep`, `RUN_FORMAT_VERSION`, strict reader refusing unknown keys) and ι (`solar-challenge web migrate`), upstream; S19 PRD §8 lists "S28's held S29 leaf → κ"; not yet filed | PASS (queued prerequisite) |
| Dropping the key changes no battery | grep: stored configs are written from `dataclasses.asdict` after `__post_init__`, so the stored pair is `sqrt(efficiency)` whenever `efficiency` is stored | PASS |
| The frozen `BatteryConfig` signature names `efficiency` today | grep: `tests/unit/test_public_api_surface.py` `"BatteryConfig": "dataclass[eq, frozen] (… efficiency: float \| None = None …)"` | PASS |
