# Capability manifest — One scenario reader (review-all S6)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/one-scenario-reader.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/one-scenario-reader.capability-manifest.yaml` (validated by `shared.capability_manifest.load_capability_manifest`; all 33 mechanical checks fail on main `dfcbde8` as authored, so each one flips when its leaf lands).

**Code anchors** verified against main `dfcbde8` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time. Probe ids (P1–P11, Q1–Q7, C1–C3) are the PRD's §2.3.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. One substrate fiction was caught at authoring and rewritten: `ScenarioConfig.homes()` cannot exist beside the `homes` field (P7), so the accessor is `simulated_homes()`.

Producers outside the batch, all upstream of the leaves that read them:

| Task | Stream and label | What it delivers here | Status |
|---|---|---|---|
| 774 | S1 β | `ConfigurationError` a `ValueError`, so the moved SEG refusal still satisfies tests catching `ValueError` | in progress |
| 778 | S10 β | `timebase.SimulationWindow` in `FROZEN_CLOSURE`, which β's `window()` return type needs | pending |
| 893 | S12 α | `timebase.ONE_MINUTE`, the requested window's cadence | pending |
| 803 | S9 γ | `gridservices.GridServicesBand.parse`, the `flex_band` reader | pending |
| S5 γ, S5 ε | S5 | the final layout; the scenario document's unknown-key and retired-key refusal | not yet filed (ids at decompose) |
| 931 | S17 α | `location.parse_location` for `home run --location` | pending |
| 738 | finance run body split | the restructured `cli/finance.run` ε edits | in progress |
| 882 | S16 β | every command reads its runner from the invocation (θ's recorder) | pending |

## α — ScenarioConfig: one read of its homes, fill-and-refuse SEG, a frozen value (intermediate with its own signal)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A home read named `homes()` is impossible; the accessor must have another name | P7: a dataclass method named like a field becomes the field's default | PASS (rewritten to `simulated_homes()`) |
| P2 RED today: a contradicting SEG is constructed | Q2 at `dfcbde8` | PASS (RED observed) |
| P2 RED today: a set `tariff_config` is accepted, and nothing reads it | Q3; grep: no src reader of `ScenarioConfig.tariff_config` | PASS (RED observed) |
| P3 RED today: `homes` is assignable | P11 | PASS (RED observed) |
| The freeze lands in-leaf | L30 (910 freezes `FleetConfig` with tuple fields in-leaf); the platform at `a654254` builds `ScenarioConfig(homes=[h], …)` keyword-only and never mutates it | PASS (lead question 2 covers a "breaking" label from S23's lock) |
| Today's fill-and-refuse logic exists to move | `finance._reconcile_seg_homes` (fill None, refuse non-`isclose`) | PASS |
| The CLI shape stays consistent until ε | `cli/finance` and `cli/optimize` write the scenario rate onto homes and set the same scenario rate, so construction does not refuse them | PASS |
| P5's knob change has no CLI surface to break | `_SENSITIVITY_ALIAS_MAP` has no SEG alias; only `apply_knob`/`sensitivity_panel` library callers and `tests/integration/test_optimize_sensitivity.py` reach it | PASS |
| Every resolution site is listed | grep at `dfcbde8`: `_resolve_homes` ×3 plus optimize's import; `_scenario_homes`; optimize's raw `.homes` in `iter_configs`, `_repriced_at_seg_rate`, `apply_knob` | PASS |

## β — ScenarioConfig: the window, D11's default tier (intermediate with its own signal)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `SimulationWindow(first_day, last_day, cadence, timezone)` and `covered_days` exist | `timebase.py` at `dfcbde8` (777 done) | PASS |
| `ONE_MINUTE` exists | producer: 893, upstream | PASS |
| `window()`'s return type needs a closure entry | producer: 778 adds `timebase.SimulationWindow` to `FROZEN_CLOSURE`, upstream | PASS |
| P6 RED today: a non-date period is accepted | P10 | PASS (RED observed) |
| P7: three zone-then-period copies to replace | grep: `period.get_start_timestamp` in `project_multi_year`, `solve_cost_recovery_rate`, `_age0_baseline_outlay` | PASS |
| Same bounds for every valid period | `get_start_timestamp(tz)` localises a date string at midnight, as `simulation_bounds()` does; only a `Timestamp` with a time of day differs (recorded on the leaf) | PASS |
| `simulate_home`'s end is inclusive | `simulate_home` docstring: "End of simulation period (inclusive)"; `pv` builds to the last hour's last minute | PASS |

## γ — One reader for every scenario document (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| R1 RED today: a `fleet_distribution:` scenario is refused by `load_scenarios` | P9 | PASS (RED observed) |
| R1 RED today: SEG and a `homes:` fleet's tariff never reach homes | P1, P2 | PASS (RED observed) |
| A tariff must be on the home when it is built | 787 (S2 β) builds the dispatcher in `HomeConfig.__post_init__` from `tariff_config`; S11 δ adds the smart-EV check there; `generate_homes_from_distribution(fleet_tariff=)` already applies it at build | PASS |
| R2 RED today: unknown keys and the flat form are accepted | Q1 (`finanse:` valid); P4 (flat file valid, 9 kW) | PASS (RED observed) |
| The base refusal exists to widen | producer: S5 ε (`_parse_scenario`'s recognised and retired keys), upstream | PASS |
| `flex_band` parses through one vocabulary | producer: 803's `GridServicesBand.parse`, upstream | PASS |
| R3 RED today: the writer round trip loses SEG | P3; `test_scenario_writer.py`'s "does not read seg: yet" | PASS (RED observed) |
| R4: export revenue = export × rate | `simulate_home` prices each minute's export at the home's flat `seg_tariff` rate (S8 decision 5 relies on the same identity); `create_summary_table` prints Grid Export Revenue | PASS (identity) |
| R5: nothing else moves for shipped files | the 12 files' top-level keys all lie in §4.2's grammar (listed at `dfcbde8`); no shipped file uses the flat form | PASS |
| The flat-key list can be derived | `_HOME_BLOCK_KEYS` exists (`HOME_BLOCK_KEYS` public after S5 β) | PASS |

## δ — home run through the one reader; typed overrides (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| H1 RED today | P4 (flat → 4 kW), Q4 (fleet file → default home), Q5 (`hom:` → default home), Q6 (`home: null` → `TypeError`), P5 (`--battery-kwh` drops `grid_charging`), and `home run` never reading `period:` (its options default to 2024-01-01/12-31) | PASS (RED observed) |
| The override fields exist to replace | `PVConfig.capacity_kw`, `LoadConfig.annual_consumption_kwh`, `BatteryConfig.capacity_kwh`; `battery.has_battery` decides 0 | PASS |
| `--location` has its grammar | producer: 931, upstream | PASS |
| A malformed date flag is refused | Typer 0.26.3 `formats=["%Y-%m-%d"]` probed: `2024-6` exits 2 | PASS (rejection observed) |

## ε — finance run and optimize configs read the one scenario (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| F1 RED today: the two commands simulate different windows | C1 (finance 2024-01-01..12-31, optimize 06-01..08-31) | PASS (RED observed) |
| F2 RED today | C2 (misspelt period silently the full year), C3 (`flex_band: 1` reaches the simulator); `period: "2024"` → `AttributeError` (finding fk-f99038047a27, code unchanged at `dfcbde8`) | PASS (RED observed) |
| F3: the report is byte-identical | task 287's measurement: with homes carrying rate R, setting the scenario rate R leaves `project_multi_year`'s curve and `project_economics` unchanged; after ε the econ scenario's simulated homes are the same `SEGTariff("", R)` homes | PASS |
| The recording simulator exists | `tests/_cli_fleet_simulator.py` `invoke_cli` | PASS |

## ζ — fleet run and fleet sweep honour the period (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| L1 RED today | `cli/fleet.run` and `sweep` default `--start`/`--end` to 2024-01-01/12-31 and read no period | PASS (RED by code read) |
| The option pair and bounds exist | producers: δ (pair), β (bounds), upstream | PASS |

## η — The dashboard through the one reader (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| W1 RED today: the export reads back without SEG | fk-a391cf1f4edf's measurement; P3's mechanism (`parse_fleet_config` ignores `seg:`) | PASS (RED observed) |
| W2 RED today: import accepts a typo | Q7 (`finanse` in `not_loaded`) | PASS (RED observed) |
| W3 RED today: validation writes a temp file | `builder_form._scenario_reader_errors` uses `tempfile.TemporaryDirectory` | PASS |
| The routes answer a refusal with 400 | `/api/fleet/import-yaml` and `/api/scenarios/validate` catch `FLEET_FORM_REFUSALS` (or S17 δ's translator) | PASS |
| The form's document already holds every block the reader needs | `parse_fleet_form` writes name, period, location, fleet_distribution, tariff and seg | PASS |

## θ — Integration gate (signal leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Every command can be recorded without an internal patch | producer: 882 (S16 β), upstream; today `home run` calls `simulate_home` directly and its tests patch it | PASS |
| G1's documents are expressible | §4.2's grammar after γ | PASS (producer γ, upstream) |
| G2's realised window equals the requested one | needs S12's window construction in `simulate_home`; θ asserts it when on main and records it as pending otherwise | PASS (conditional, stated) |
| The briefing takes a conventions line | `review/briefing.yaml` has `conventions:` | PASS |

## ι — Held: the period becomes a window (held leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `SimulationPeriod` is frozen surface and the platform builds one | `FROZEN_CLOSURE["config.SimulationPeriod"]`; `solar-challenge-platform` `tests/test_solar_challenge_seam.py` builds `SimulationPeriod("2020-01-01", "2020-12-31")` | PASS (held for S29's one re-pin, D4) |
| The cadence a window must carry exists | producer: 893 (`ONE_MINUTE`), upstream via β | PASS |
