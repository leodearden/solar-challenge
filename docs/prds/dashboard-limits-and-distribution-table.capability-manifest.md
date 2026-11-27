# Capability manifest: Dashboard limits and distribution editing from one table (review-all S18)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/dashboard-limits-and-distribution-table.md`. Each capability that a leaf's signal asserts is bound to evidence. The machine-readable twin is `docs/prds/dashboard-limits-and-distribution-table.capability-manifest.yaml`. It validates with `shared.capability_manifest.load_capability_manifest`, and every one of its 36 grep checks fails on main `beb1d91`. That was checked with `git grep -E` at authoring and again at the 2026-10-18 decompose, also against the open `task/*` branches that touch each check's paths; branch flips came only from merge-bases older than the symbol. `commit_planning` stamped the ids 977–984 into the sidecar. Three checks were re-anchored at the decompose:

- β's size-literal pattern would have matched `heat-pump-config.html`'s `max="50000"`;
- ζ's pattern would have matched the builder's initial `latitude: 51.45`;
- δ's builder check is anchored on the flat `wd_values`/`sp_entries` keys, because `task/313`, a δ prereq, deletes the three names it named.

**Code anchors** verified against main `ede1d99` (2026-10-17). Main moves fast: cite by symbol and re-locate lines at implementation time. The probes P1–P15 are the PRD's §2.7. They ran under `UV_OFFLINE=1 uv run --locked --extra dev --extra web python -I`.

**Batch verdict: PASS, with pre-conditions.** These producers from other streams must land upstream of their consumers:

- 956 (S6 β: `DEFAULT_FIRST_DAY`, `DEFAULT_LAST_DAY`, L42) before α;
- 860 (S4 α) before β;
- 947 (S5 γ), 921 (S7 ε) and 868 (S4 ζ) before γ;
- 870 (S4 η), 937 (S17 ε), 313 (in progress) and 394 before δ;
- 961 (S6 η, L42) before ζ;
- 786 (S2 α), 839 (S11 β), 841 (S11 γ) and 911 (S7 α) before η.

No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Each refusal a signal asserts is absent today, either probed or read from the code, and is built by the leaf that asserts it or by an upstream producer. No signal asserts a numeric tolerance.

## α: The CLI, its templates and the web read `timebase`'s default window (leaf)

L42: α defines no default-window constant. 956 (S6 β) puts `DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY` in `timebase.py`, and α adds only `SHORT_WINDOW_START`.

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The default pair exists | producer: 956 (S6 β), upstream of α | PASS (producer upstream) |
| W1 holds in either order against S6's option pair | 958, 959 and 960 give the five commands the `cli/utils` pair, which defaults to None; W1 accepts None or the constants' ISO strings | PASS (order-agnostic) |
| The literals to replace exist | grep: `"2024-01-01"`/`"2024-12-31"` as typer defaults in `cli/home.py`, `cli/fleet.py` (`run`, `sweep`) and `cli/finance.py`; the `.get` fallback in `cli/optimize.py`; `cli/config.py`'s two templates; `home quick`'s `"2024-06-01"`; `date(2024, …)` in `web/simulation_params.py` | PASS (RED observed) |
| W1 is checkable | probe: `typer.main.get_command` exists in the locked typer; each click parameter carries `.default` | PASS |
| W2's exact-literal scan does not hit prose | grep: the only other ISO-date texts in `src/` are inside `heat_pump.py`'s docstring example and help-text sentences (`cli/optimize.py`, `cli/finance.py`), none of them a whole string literal | PASS |
| `timebase` may gain `SHORT_WINDOW_START` | no `FROZEN_*` entry names a `timebase` constant at `beb1d91` (re-checked in-leaf; additive under D29 if one does) | PASS |

## β: `PageLimits`; one range per component in every reader (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| L2's RED: the home page takes a 500 kWh battery | P1: accepted, 500.0 | PASS (RED observed) |
| L3's RED: the fleet page takes out-of-range homes | P3: PV 50, battery 500 and load 100,000 generate homes | PASS (RED observed) |
| L4's RED: the builder bounds only fixed values | P14 refused, P15 accepted | PASS (RED observed) |
| L5's RED: three size limits | grep: `min="10" max="500"` and `range_input(… max=500 …)` in `simulate/fleet.html`; `n > 1000` in `fleet-simulator.js`; `max="10000"` in `builder.html`; P11 runs 2000 | PASS (RED observed) |
| The range refusal fires | built in-leaf: `as_finite_float(…, within=value_range)` (860's `within=`) for the home body; `refuse_homes_outside_ranges` over generated homes for the fleet and builder bodies | PASS (bound in-leaf; 860 upstream) |
| One channel into templates | Flask's `app.context_processor`; `base.html` is extended by all four pages | PASS |
| Scripts can read a JSON element | the pages already pass JSON through `tojson` (`builder.html`'s `scenarioBuilder(…)`, `home.html`'s `consumptionRange`) | PASS |
| `fleet_components` can hold the moved names without a cycle | grep: `fleet_components.py` imports only the standard library; `simulation_params`, `builder_form` and `scenarios` import it; it will import `number_fields` (leaf), `timebase` (leaf) and `home` | PASS |
| The assistant's PV descriptions are literals beside a rendered load range | grep: `"PV array capacity in kW (0.5–20)."` and the fleet tool's twin; `FLEET_COMPONENTS["load"].fixed_range` already rendered beside them | PASS |
| Page tests can read the rendered pages | `tests/_html_page.py`: `element_attributes`, `script_texts` | PASS |

## γ: The per-type table in `fleet_distribution.py` (intermediate; unlocks δ, ε, ζ)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The table to extend exists | grep: `_DISTRIBUTION_SPEC_TYPES` (six `_BlockType` records: recognised keys and builder) and `_parse_distribution_spec`, which reads it, in `config.py` | PASS |
| `fleet_distribution.py` exists at γ's base | producer: S5 γ moves the fleet grammar there (S5 PRD §4.1, which names "S18 adds the per-type distribution table") | PASS (producer upstream; id from the lead) |
| `FieldKind` and the F2 rule exist | producer: 921 (S7 ε), with `FieldKind` from 919 (S7 §5.1, F2) | PASS (producer upstream) |
| The builders read their numbers at construction | producer: 868 (S4 ζ) rewrites the `_build_*_spec` number reads; γ moves the builders by name | PASS (producer upstream) |
| T1, write is the inverse | identity: each builder reads keys equal to its spec dataclass's field names (`NormalDistribution.mean/std/min/max`, `WeightedDiscreteDistribution.values/weights`, `ShuffledPoolDistribution.values/counts`, `UniformDistribution.min/max`); `fixed` writes the scalar form; `proportional_to` writes `source`, `offset` and its `multiplier` (number or sweep mapping) explicitly | PASS |
| T3, nothing moves | γ changes only where keys and titles are stated; the shipped scenarios validate today ("Configuration is valid" ×10, S5 §2.4); S7 γ's pins (916) guard generation | PASS |

## δ: One wire shape on both pages (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| E2's RED: invented defaults | P4: `{type: normal}` → `mean 0.0, std 1.0` | PASS (RED observed at `ede1d99`; task 313 may remove it first, and δ depends on 313 and keeps the rule) |
| E2's refusal text exists | P6: "normal distribution for 'fleet_distribution.pv.capacity_kw' requires 'mean' and 'std'" | PASS |
| E3's RED: imports disagree | P12 (fleet loads `fixed`), P13 (fleet refuses an unclamped normal); read: `scenario-builder.js` `componentDistribution` throws on `fixed` | PASS (RED observed) |
| A blank optional clamp reads as absent | grep: `_build_normal_spec` reads `min`/`max` through `_float_or_none`, so null → None; S4 ζ keeps "optional" (§5.1 `optional=True`) | PASS |
| A null pool value is a home with no battery | `scenarios/bristol-phase1.yaml`'s battery pool holds `None`, and it generates 60 batteries of 100 (S7 §3.2) | PASS |
| E6: the route names a broken invariant | producer: 868's builders construct through 866's `_constructed`, which prefixes the block path; upstream of δ through γ | PASS (producer upstream) |
| E7: a huge pool is refused before allocation | producer: 921's F6 (counts == n_homes, 297's rule) at `FleetDistributionConfig` construction; `ShuffledPoolDistribution` builds no pool at construction (`create_pool` runs at sampling); the size bound runs before generation (`read_fleet_size`, `_home_count_allowed`) | PASS (producer upstream) |
| The translators to delete exist | grep: `_build_distribution_dict`, `_spec_number`, `_named_rows`, `read_pool_counts`, `distribution_form_spec` (`fleet_config.py`); `_DISTRIBUTION_FIELDS`, `_distribution_spec`, `_row_lists` (`builder_form.py`); `_buildDistPayload`, `_distFromConfig`, `componentFormData` (scripts) | PASS (RED observed) |
| E5 is observable | the e2e suite drives both pages (`test_fleet_interactions.py`, `test_scenario_builder.py`); Playwright request interception reads the posted body | PASS (lane e2e job) |

## ε: The fleet page previews the homes Run builds (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| P2's RED: the preview accepts what Run refuses | P8 `[2.0, 2.0, 2.0]`, P9 `[5.0]*4`, P10 cycles `[3, 3, 4, 3, 3, 4]` | PASS (RED observed) |
| G1 gap: no page calls the endpoint | grep: `preview-distribution` appears in `api.py` and the tests only | PASS (RED observed) |
| P1: the preview is Run's homes | `parse_fleet_form` is wired into `simulate_fleet_from_distribution` on main and generates through `generate_homes_from_distribution`, which samples through 916 (S7 γ) after γ and δ | PASS (wired; sampler upstream) |
| P2's refusals are Run's | the same call raises them: 921's F-checks and the spec constructors through 868 | PASS (producer upstream) |

## ζ: The builder imports on the server (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| B1's RED: silent drops | read: `scenarioFormFields` sets `import_rate` to `''` unless `tariff.type === 'flat_rate'`, and reads SEG only as `rate_pence_per_kwh`; `scenarios/bristol-phase1-flex.yaml` has a `fleet_distribution` block and an `economy_7` tariff | PASS (RED observed by reading) |
| B2's RED: presets restore little | read: `loadPreset` copies `name`, `n_homes` and the coordinates with `\|\| 51.45`; `scenarios_save_scenario` stores `getFormData()`'s flat form | PASS (RED observed by reading) |
| The fleet page's machinery to share exists | grep: `ImportedFleetForm`, `_read_blocks`, `_not_loaded`, `_read_typed_block`, `_read_period`, `_read_day`, `_read_name`, `_read_seg` in `fleet_scenario.py`; `_loaded_fleet_form_answer` in `api.py` | PASS |
| Dates leave as ISO | `_read_period` returns `start.isoformat()`/`end.isoformat()` | PASS |
| js-yaml can go | grep: its only uses are `builder.html`'s script tag and `uploadYaml`; `test_web_page_scripts.py` pins the vendored file | PASS |

## η: Tariff and dispatch choices from the server's tables (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The twelve decision sites exist | fk-006c3339e3b2's measurement, reproduced: `fleet.html` 6, `fleet-simulator.js` 4, `fleet_scenario.py` 2 | PASS (RED observed) |
| `STRATEGY_CONFIG_BY_TYPE` | producer: 786 (S2 α), read-only `Mapping[str, type[DispatchStrategyConfig]]` (S2 PRD §5) | PASS (producer upstream) |
| A tariff-clocked `tou_optimized` | producer: 839 (S11 β): `peak_hours: … \| None = None`; V2's RED by construction: `_one_peak_window` refuses a missing window | PASS (producer upstream) |
| Economy starting rates | producer: 841 (S11 γ): `tariff.PRESET_RATES`, rendered into both simulate pages | PASS (producer upstream) |
| Flat-rate starting values disagree | grep: `0.28` (`fleet-simulator.js`, `home.html`), `0.245` (`scenario-builder.js`) | PASS (RED observed) |
| Heat-pump options from the vocabulary | grep: `<option value="ASHP">`/`"GSHP"` in `simulate/partials/heat-pump-config.html`; producer: 911 (S7 α) `HEAT_PUMP_TYPES` | PASS (RED observed; producer upstream) |

## θ: Integration gate (signal leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| G1 has every producer upstream | θ depends on β, δ, ε, ζ and η | PASS |
| The briefing has a conventions list | grep: `conventions:` in `review/briefing.yaml` | PASS |
| E5 runs | the lane's e2e job (`tests/e2e`, not slow) after every merge | PASS (lane) |
