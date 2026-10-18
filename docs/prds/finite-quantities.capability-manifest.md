# Capability manifest — Finite quantities (review-all S4)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/finite-quantities.md`. Each capability a task's signal asserts is bound to evidence. The machine-readable twin is `docs/prds/finite-quantities.capability-manifest.yaml`.

**Code anchors** verified against main `962552956508` (2026-10-15). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Each capability falls into one of three groups:

- It exists on main.
- A task in this batch delivers it, upstream of the task that asserts it.
- An out-of-batch producer delivers it, wired as a prerequisite: 774, 786, 395 and S5's partition leaf, which is still to be filed.

Every RED premise was observed at `962552956508`. Each check that expects an old idiom to be absent was first confirmed to find that idiom present on main.

## α — `number_fields` moves to the package leaf with intervals and `ConfigurationError` (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The four readers exist to move, with tests | grep: `web/number_fields.py` defines `as_finite_float`, `as_finite_float_within`, `as_whole_number`, `as_whole_number_within`; `tests/unit/test_web_number_fields.py`; 20 references to `solar_challenge.web.number_fields` in src and tests | PASS |
| `ConfigurationError` exists below config and is a `ValueError` | producer: 773 (in progress), then 774 (β), upstream; α depends on 774 | PASS |
| Web callers keep catching the refusal | 774 makes `ConfigurationError` subclass `ValueError`; every web caller catches `ValueError` (`builder_form`, `fleet_config`, `simulation_params` call sites) | PASS |
| P1's fresh-interpreter pattern exists | `tests/unit/test_init_lazy_surface.py` runs `-I` subprocesses and inspects `sys.modules` | PASS |
| `whole_numbers` imports only numpy (leaf stays a leaf) | grep: `whole_numbers.py` imports `math`, `typing`, `numpy` | PASS |

## β — Component and fleet inputs read their numbers through the leaf (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `validate config` accepts `capacity_kw: true`, `thermal_capacity_kw: .nan`, `altitude: .nan`, `timezone: Europe/Londn` today (RED) | ran at `962552956508`: "Configuration is valid", exit 0, for each | PASS (RED observed) |
| `azimuth: south` ends in a traceback today (RED) | ran: `TypeError: '<=' not supported between instances of 'int' and 'str'`, exit 1 | PASS (RED observed) |
| `validate config` prints a `ConfigurationError` as an ERROR row | ran: a fleet refusal prints `ERROR │ Capacity must be positive and finite, got nan kW` | PASS |
| The splat readers pass raw values, so β alone makes these refusals visible, with no path until ε | grep: `_parse_pv_config` splats `PVConfig(**{...})`; `parse_location_block` passes `data.get(...)`; `_parse_heat_pump_config` passes `float(nan)` = nan | PASS |
| `zoneinfo` refuses an unknown zone and accepts every zone in use | probe: `ZoneInfo("Europe/Londn")` raises `ZoneInfoNotFoundError` (a `KeyError`); `Europe/London`, `Europe/Paris`, `America/New_York`, `UTC` resolve | PASS (rejection observed) |
| Library constructions accepted today (D1 RED) | probe: `EVConfig("7kW", 17.5)`, `EVConfig("7kW", True)`, `HeatPumpConfig("ASHP", nan, nan)`, `Location(51, -2, altitude=nan)`, `PVConfig(capacity_kw=True)` construct | PASS (RED observed) |
| `read_field` and the readers exist | producer: α, upstream | PASS |
| `PVConfig`'s Optional efficiency fields (S14 ζ) | proposed producer: S14 ζ upstream of β (lead question 2); otherwise ι converts the leftovers | PASS (wired as proposed prerequisite) |

## γ — Tariff, SEG, finance, grid-services, flexibility, community and install-point inputs (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `bristol-phase1-flex.yaml` with `event_hours: .inf` validates today (RED) | ran at `962552956508`: "Configuration is valid", exit 0 | PASS (RED observed) |
| `SEGTariff("x", nan)` and `TariffPeriod("00:00", "00:00", nan)` construct today (RED) | probe: both construct; `SEGTariff("x", inf)` too | PASS (RED observed) |
| The old idioms exist to replace | grep: `self.rate_pence_per_kwh < 0` (seg), `self.rate_per_kwh < 0` (tariff), `self.event_hours <= 0` and `self.events_per_year <= 0` (gridservices), `self.time_shift_gbp < 0` (flex), `not 0.0 <= value < math.inf` and `not 0.0 < value < math.inf` (FinanceConfig) | PASS |
| `EventWindow`'s refusal reaches the CLI unrelabelled | producer: 774 narrows `config._parse_event_windows`' handler (S1 §6), upstream through α | PASS |
| S11 α's `TariffPeriod` idiom to swap | proposed producer: S11 α upstream of γ (S11 PRD §8 "S4 after α") | PASS (wired as proposed prerequisite) |

## δ — Dispatch inputs (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `dispatch.GridChargeConfig`, `_require_valid_import_limit`, `_require_valid_peak_hours` exist | producer: 786 (S2 α, pending), out-of-batch prerequisite; S2 PRD §5.1 names "S4 replaces the two validators' bound idioms" as the extension point | PASS |
| `import_limit_kw: true` and `target_soc_fraction: true` are accepted today (RED) | grep: `PeakShavingStrategy.__init__` and `config.DispatchStrategyConfig` compare `import_limit_kw <= 0`, which `True` passes; `GridChargeConfig` compares `not 0 < x <= 1`, which `True` passes; task 558 measured `true` accepted | PASS (RED by construction) |
| The bool refusal stays RED after 786 | S2 PRD §11 leaves finite/bool checks to S4; no comparison idiom refuses `True` | PASS |
| `scenarios/dispatch-comparison.yaml` and `bristol-arbitrage.yaml` carry the keys the signal edits | grep: `strategy_type: peak_shaving` / `import_limit_kw: 2.0` (dispatch-comparison), `grid_charging: target_soc_fraction: 0.9` (bristol-arbitrage) | PASS |

## ε — Config's block readers construct through one wrap (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The coercions to delete exist | grep in `config.py`: `def _number`, `_FINANCE_SCALAR_COERCIONS`, `contains a non-numeric value` (3), `arrival_hour=int(` (2) | PASS |
| `ev: {arrival_hour: 18.9}` validates today (RED) | ran: "Configuration is valid", exit 0 | PASS (RED observed) |
| `finance: {vat_rate: true}` is refused today naming no key | grep: `_number` raises `TypeError("True is a boolean, not a number")`, rewrapped as "finance block contains a non-numeric value: …" | PASS (RED by construction) |
| Block paths are available to every reader | grep: each reader takes `block_path`; `parse_home_block` gets `homes[{index}]` from `_parse_scenario` and `load_home_config` | PASS |
| The input types refuse by field name, which the wrap prefixes | producers: β, γ, δ, upstream | PASS |
| The partition's final module names | proposed producer: S5's partition leaf upstream (seam table); otherwise ε edits `config.py` and S5 moves it | PASS (wired as proposed prerequisite) |

## ζ — The fleet grammar reads its numbers at construction and rounds sampled counts (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `n_homes: 2.7` runs 2 homes today (RED) | ran: the fleet probe validated n_homes silently (grep `n_homes=int(data["n_homes"])`); its only ERROR came from the `.nan` mean | PASS (RED observed) |
| The scalar arm reads `True` as 1.0 today (RED) | grep: `_parse_distribution_spec` has `isinstance(data, (int, float))` then `float(data)`; task 521 | PASS (RED by construction) |
| EV hours truncate today; rounding moves the means to 17.933 and 7.200 | probe on `bristol-with-evs.yaml`: 30 EV homes, `int()` means 17.433 / 6.533; raw draws 17.945 / 7.090; `round()` of the same draws 17.933 / 7.200. Rounding follows the draw, so the draw sequence is unchanged | PASS (bound ≥ 17.9 / ≥ 7.1 below measured) |
| `sample_count` rounds a finite draw | producer: task 395 (merge phase), out-of-batch prerequisite | PASS |
| `_constructed` exists | producer: ε, upstream | PASS |

## η — The web stops pre-reading numbers ahead of config (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The rebuild invents defaults and drops keys today (RED) | probe: `form_to_fleet_distribution_config` maps `{type: normal, mena: 4, std: 1}` to `{type: normal, mean: 0.0, std: 1.0}`, and `{type: fixed, value: 30}` to `{type: fixed}` | PASS (RED observed) |
| `simulate_sweep` reads `{"min": true}` as 1.0 and `{"steps": 2.5}` as 2 today (RED) | grep: `float(data.get("min", 1.0))`, `int(data.get("steps", 5))` | PASS (RED by construction) |
| fleet-from-distribution answers 201 on success and 400 on a `ValueError` | grep: `api.simulate_fleet_from_distribution` returns `…), 201` and `jsonify({"error": str(exc)}), 400` | PASS |
| The pre-reads to delete exist | grep: `def _spec_number` (fleet_config), `_read_fleet_size_and_seed` (fleet_scenario), "PVConfig is the single source of truth" (simulation_params) | PASS |
| Config refuses what the web stops refusing, with paths | producers: ζ and β, upstream | PASS |

## θ — Summary and step results are frozen values (intermediate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Both classes are plain dataclasses today and nothing assigns to their fields | census: `SummaryStatistics frozen=False`, `EnergyFlowResult frozen=False`; grep for field assignment in src and tests finds none | PASS |
| `simulate_timestep(inf, 1.0, None)` returns infinite flows today (RED) | probe: `EnergyFlowResult(generation=inf, …, grid_export=inf, …)` | PASS (RED observed) |
| The frozen contract pins the `frozen` flag (the edit is mandatory) | consumption guide, task 567: "the frozen contract now covers … which of the dataclass parameters … frozen it sets" | PASS |
| The per-step cost is known and accepted | microbenchmark: +1.3–1.6 µs per frozen construction vs 8.2 µs per step with a battery; ruled R3 | PASS |
| `Interval.admits` exists | producer: α, upstream | PASS |

## ι — Invariant 1 guard (leaf; integration gate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Discovery finds the numeric dataclasses to classify | probe: 54 numeric dataclasses in top-level modules; `typing.get_type_hints` fails on `BatteryConfig`, `FinanceConfig`, `CommunityResults`, `ConfigResult` (TYPE_CHECKING imports), so discovery needs its fallback (tactical Q5) | PASS |
| Every input type refuses by name with `ConfigurationError` | producers: β, γ, δ, ζ, upstream; ι converts any straggler at its base | PASS |
| A seeded unclassified class is reported (rejection check) | built and bound by ι: its own `tmp_path` test observes the report (G1) | PASS (bound in-leaf) |
| `review/briefing.yaml` takes a rule + why entry | grep: `review/briefing.yaml` `conventions:` list | PASS |
