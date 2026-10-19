# Capability manifest: Component defaults, one home per component (review-all S7)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/component-defaults-one-home.md`. Each capability a leaf's signal asserts is bound to evidence. The machine-readable twin is `docs/prds/component-defaults-one-home.capability-manifest.yaml`.

**Code anchors** verified against main `ac1fdf1` (2026-10-17). Main moves fast: cite by symbol and re-locate lines at implementation time. The probes ran under `UV_OFFLINE=1 uv run --locked --extra dev python -I`, using `parse_fleet_distribution_config`, `generate_homes_from_distribution` and `parse_home_block` at `Location.bristol()`. The PRD's §3.1 numbers them P1–P17.

**Batch verdict: PASS, with one pre-condition.** Task 297 lands upstream of γ. No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Each refusal a signal asserts is absent today, as the probes observe. Each one is built by the leaf that asserts it and observed by that leaf's own test. No signal asserts a numeric tolerance except A1's 1e-12, whose basis is that the record holds the same four floats and the same arithmetic as today's constants.

## α: Heat-pump types as one per-type record (intermediate; unlocks δ)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The curves to reproduce | probe: `calculate_cop` at −20, −5, 0, 7, 20, 40 °C gives ASHP [1.8, 2.0, 2.5, 3.2, 4.5, 4.5] and GSHP [3.4, 3.7, 3.8, 3.94, 4.2, 4.6] | PASS |
| A1 within 1e-12 is achievable | identity: `clamp(intercept + slope·t, min, max)` with the same four floats per type is the same IEEE expression as today's branch | PASS |
| The Literal's arguments are available at runtime | probe: `typing.get_args(Literal["ASHP","GSHP"])` returns `('ASHP', 'GSHP')` | PASS |
| The eight constants and the five spellings exist to collapse | grep: `^(ASHP\|GSHP)_COP_` ×8 in `heat_pump.py`; `valid_types = (` in `HeatPumpConfig.__post_init__`; the if/elif in `calculate_cop`; 6 `'ASHP'`/`'GSHP'` literals in `config.py` (the generator's tuple, message and `cast`, plus the docstring and comment) | PASS |
| The constants' only readers are `heat_pump.py` and `tests/unit/test_heat_pump.py` | grep `ASHP_COP\|GSHP_COP` over src, tests, scripts and docs | PASS |
| The public surface is unaffected | grep: no heat-pump name is in `__all__`; `HeatPumpConfig`'s `FROZEN_CLOSURE` form names `Literal['ASHP', 'GSHP']`, which stays | PASS |
| The XSHP refusal lists the vocabulary | built in-leaf; today's messages list hand-written tuples | PASS (bound in-leaf) |

## β: Component block tables shared by readers and writer (intermediate; unlocks δ)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| B1's RED: `system_losses` is refused in a `pv:` block | P1: `Unrecognised keys in home.pv: 'system_losses'` | PASS (RED observed) |
| B2's RED: the writer drops `system_losses` | P2: the written pv keys omit it; reads back 0.14075660688264469 | PASS (RED observed) |
| B2 exact round-trip | identity: the writer emits `getattr(cfg, k)` for every table key, YAML safe_dump/safe_load round-trips Python floats exactly, and R1 passes values as written; `efficiency` re-derives the per-direction pair identically | PASS |
| B4's RED: P10, P11 and the two nulls | P10, P11 refused; P15 raises raw `TypeError` | PASS (RED observed) |
| The parser writes PV's when-omitted capacity and battery's capacity as policy | grep: `_PV_CAPACITY_KW_WHEN_OMITTED`, `_BATTERY_CAPACITY_KWH_WHEN_OMITTED` in `config.py` | PASS |
| The sub-block readers and writer exist (S2 owns their grammar) | grep: `parse_dispatch_strategy_config`, `_parse_grid_charge_config` in `config.py`; `_dispatch_strategy_block` in `scenario_writer.py`; S2 PRD §5.5 names S7's battery table | PASS |
| `scenario_writer` may import config's grammar without a cycle | grep: only `web/{api,builder_form,fleet_scenario}.py` import `scenario_writer`; config imports none of them | PASS |
| `dataclasses.fields` defaults exist for the outside-grammar check | `PVConfig.custom_module_params` and `custom_inverter_params` default None | PASS |
| The two new defaults are additive on the frozen surface | `FROZEN_CLOSURE` holds `ev.EVConfig` and `heat_pump.HeatPumpConfig` forms; D29: additive edits land in-leaf with their entry and an Unreleased line in `docs/domain-library-consumption.md` | PASS |
| The hand lists to delete exist | grep: six `^_(PV\|BATTERY\|LOAD\|HEAT_PUMP\|EV\|LOCATION)_BLOCK_KEYS` in `config.py`; `"tilt": pv.tilt` in `scenario_writer.py`; `CLAUDE.md`'s "change both together" | PASS |
| T1 fails on a new field | built in-leaf: the coverage test is parametrised over the six tables | PASS (bound in-leaf) |

## γ: Sampler state per field path; reproducibility pins (intermediate; unlocks δ)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| C1's RED: a legacy pool on `pv.tilt` | P6: `KeyError: 132606489280928` | PASS (RED observed) |
| C2's RED: a shared spec object | P7: `IndexError: list index out of range` | PASS (RED observed) |
| Pools hold exactly n_homes values before γ | producer: task 297 (pending; its plan.json refuses counts ≠ n_homes at `FleetDistributionConfig.__post_init__` and at generation start), upstream of γ | PASS (producer upstream) |
| The fleets to pin generate today | §3.2: the six tracked files generate (100 homes each; the sweep 16 points) | PASS |
| C3 identity is achievable | identity: γ keeps every RNG call, its order and its arguments for those fleets. The default prepare order is today's `all_specs` order. Legacy prepares its four first, and the extra pools it prepares exist only in fleets that raise `KeyError` today. `pre_sample` stays for `load.annual_consumption_kwh` alone | PASS |
| `id(spec)` keying to replace | grep: `id(spec)` ×3 in `_DistributionSampler` | PASS |

## δ: The fleet grammar from the component tables (intermediate; unlocks ε)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| D1's RED: heat-pump pools are ignored | P3: 0 heat pumps of 10 | PASS (RED observed) |
| D3's RED: the fleet grammar is narrower than the home grammar | P14: refused as unrecognised keys | PASS (RED observed) |
| The tables' keys and kinds exist upstream | producer: β (tables), α (`HEAT_PUMP_TYPES`), both upstream of δ | PASS (producer upstream) |
| Path-keyed sampler and pins exist upstream | producer: γ, upstream of δ | PASS (producer upstream) |
| The distribution classes are free to reshape | grep: no `*DistributionConfig` in `__all__` or `FROZEN_CLOSURE`; 0 src readers outside `config.py`; 89 constructions under `tests/` | PASS |
| D6 identity holds after the reshape | identity: an absent key draws nothing, as today's scalar default specs drew nothing; T3 keeps both orders; the new keys are absent from the pinned files | PASS |
| 0 occupants is refused by `LoadConfig` | grep: `LoadConfig.__post_init__` refuses `household_occupants < 1`; P12 shows today's silent 3 | PASS |

## ε: The fleet invariants at read time (leaf; signal leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| D2's RED: P4, P8 and P13 pass the parser | P4: 0 batteries of 4, no error; P8: "Unknown distribution type: <class …>"; P13: the parser accepts, generation raises | PASS (RED observed) |
| The kinds the checks read exist upstream | producer: δ (`FleetField`, `ComponentDistribution`), upstream of ε | PASS (producer upstream) |
| F6 is already enforced | producer: task 297, upstream through γ | PASS (producer upstream) |
| D5's path reaches the parser | grep: `fleet_scenario._refuse_what_the_loaders_refuse` calls `parse_fleet_distribution_config`; `POST /api/fleet/import-yaml` maps `FLEET_FORM_REFUSALS` (including `ConfigurationError`) to HTTP 400 | PASS |
| `validate config` reports a loader refusal and exits 1 | grep: `cli/validate.py` loads `fleet_distribution:` files as `fleet run` does | PASS |
| Each refusal F1–F5 fires | built in-leaf; observed absent today (P4, P8, P13, P14) | PASS (bound in-leaf) |
