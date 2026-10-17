# Capability manifest — Scenario grammar partition (review-all S5)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/scenario-grammar-partition.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/scenario-grammar-partition.capability-manifest.yaml`.

**Code anchors** verified against main `ac1fdf18ef8c` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Producers outside the batch are upstream of the leaves that read them:

| Task | Stream and label | Status |
|---|---|---|
| 773 | S1 α | done |
| 774 | S1 β | in progress |
| 775 | S1 γ | in progress |
| 786 | S2 α | pending |
| 787 | S2 β | pending |
| 860 | S4 α | pending |
| 866 | S4 ε | held for this stream |
| 868 | S4 ζ | pending |

## α — Delete the parameter-sweep runner and its tests (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The runner family has no src caller | grep `-w` over src, scripts, docs and README: `run_parameter_sweep`, `ParameterSweepConfig`, `SweepResult`, `_apply_parameter_to_home` and `_modify_*` are named only in `config.py` and `tests/unit/config/test_parameter_sweep.py` (other PRDs mention them as S5's deletion) | PASS |
| No frozen name changes | grep `tests/unit/test_public_api_surface.py`: none of the seven names is in `FROZEN_SURFACE`, `FROZEN_CLOSURE` or `FROZEN_MEMBERS`; `__init__.py`'s lazy map does not name them | PASS |
| The platform consumer does not use them | grep of `solar-challenge-platform` at `82e71df`: no match | PASS |
| `simulate_home`, `simulate_fleet`, `SimulationResults` and `FleetResults` are imported only for the runner | AST walk: their only uses in config.py are inside `run_parameter_sweep` and `_apply_parameter_to_home` | PASS |
| Task 237's branch does not change the premise | `task/237` rewrites the same functions and their test file; α deletes both, whichever merges first | PASS |

## β — scenario_blocks.py: the block toolkit and every block reader (intermediate, unlocks γ and 866)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The block readers form a closed lower layer: they reference no fleet-grammar or document name | AST reference walk (PRD §2.1): the only cross-group edges point down; the apparent `generate_homes_from_distribution → load_config` edge is a local variable | PASS |
| The domain modules the readers import never import config | grep of their top-level imports: `community`, `finance`, `gridservices`, `home`, `battery`, `dispatch`, `seg`, `tariff`, `location`, `pv`, `load`, `ev` and `heat_pump` import no `config`; finance's `ScenarioConfig` import is under `TYPE_CHECKING` | PASS |
| P2's premise: the fresh-interpreter test pattern exists | `tests/unit/test_init_lazy_surface.py` runs `-I` subprocesses and reads `sys.modules` | PASS |
| GridChargeConfig and the strategy union are not config's when β runs | producer: 786 (S2 α), upstream; its sidecar checks `class GridChargeConfig` and `class TOUOptimizedStrategyConfig` present in `dispatch.py` | PASS |
| `_VALID_DISPATCH_STRATEGIES` has left config | producer: 787 (S2 β), upstream (`HOME_DISPATCH_STRATEGIES` in `home.py`) | PASS |
| `number_fields` sits at the package leaf before the partition (L16) | producer: 860 (S4 α), upstream | PASS |
| The guard file exists for β's first rule | producer: 775 (S1 γ) creates `tests/unit/test_import_structure.py` (on `task/775`), upstream | PASS |
| mypy refuses the old spelling in src, which forces the repoint | `pyproject.toml` `[tool.mypy] strict = true` with no `implicit_reexport` override; S1 observed `attr-defined` on the same pattern | PASS (rejection observed by S1) |
| C1: the 10 shipped scenarios validate today | ran `validate config` on each `scenarios/*.yaml` at `ac1fdf18`: all "Configuration is valid" | PASS |

## γ — fleet_distribution.py and the layering guard (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The fleet grammar needs only block-toolkit names from below | AST walk: `BlockType`, `child_path`, `float_or_none`, `parse_grid_charge_config`, `refuse_unrecognised_keys` and `parse_dispatch_strategy_config`, all public in `scenario_blocks` after β | PASS (producer: β, upstream) |
| No moved class is named by the frozen surface | `FROZEN_CLOSURE` config keys are `DispatchStrategyConfig` and `GridChargeConfig` (S2's), and `OutputConfig` and `SimulationPeriod` (staying in config.py) | PASS |
| Stored runs do not depend on the distribution types' module | grep of `web/storage.py` and `web/stored_runs.py`: no distribution type is named; the `vars(solar_challenge.config)` merge goes in 786 | PASS |
| P4/P5: the guard can see a seeded violation | built and bound by γ: its own `tmp_path` tests observe the report | PASS (bound in-leaf) |
| Sizes after the move (signal text) | measured spans at `ac1fdf18`: fleet grammar ~1,120, block readers ~835 less S2 α's types, documents ~530 lines | PASS (measured, not a bound) |
| The briefing takes a conventions entry | `review/briefing.yaml` has a `conventions:` list | PASS |

## δ — One refusal constructor and its guard (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| R1 RED today | ran `validate config` on `homes: [{}, {heat_pump: {thermal_capacity_kw: 8}}]`: ERROR `heat_pump configuration requires 'heat_pump_type' field`, exit 1 | PASS (RED observed) |
| R2 RED today | ran `validate config` on `homes: 5`: `TypeError: 'int' object is not iterable` traceback | PASS (RED observed) |
| R4 RED today | `load_scenarios` on a scenario list entry missing `end_date`: `Simulation period requires 'start_date' and 'end_date'` (no path) | PASS (RED observed) |
| A refusal reaches the user as an ERROR row and exit 1 | ran: `validate config` exits 1 on a ConfigurationError row | PASS |
| C3: construction refusals already carry their path | producer: 866 (S4 ε, `_constructed`), upstream of δ | PASS |
| The fleet grammar's construction is settled before δ rewrites its messages | producer: 868 (S4 ζ), upstream of δ | PASS |
| P6: the guard rejects a seeded direct raise | built and bound by δ (`tmp_path` test) | PASS (bound in-leaf) |
| The path-less sites exist to convert | AST scan: 40 `raise` sites outside the runner, 27 of them inside functions holding `block_path` (PRD §2.3) | PASS |

## ε — The scenario document refuses what nothing reads (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| S1/S2 RED today | ran `validate config` on a `scenario:` document with `output:`, scenario-level `tariff_config:` and `bogus: 1`: "Configuration is valid", exit 0 | PASS (RED observed) |
| Nothing reads `ScenarioConfig.output` or `.tariff_config` | grep of src: no reader of either attribute | PASS |
| `validate config` routes a `scenario:`-wrapped document through `load_scenarios` | read `cli/validate._homes_defined_by` | PASS |
| The commands that write files take an output flag | grep: `cli/home.py` has `--output` and `--report`; `cli/fleet.py` has `--output` | PASS |
| The templates carry `output:` and the CLI writes them | `cli/config.py` `HOME_TEMPLATE` and `SCENARIO_TEMPLATE`; the `template` command takes `--output` | PASS |
| No shipped scenario uses a key outside the recognised set through `load_scenarios` | top-level keys of the 10 `scenarios/*.yaml`: none is `scenario:`-wrapped, and none carries `output` or `tariff_config` | PASS |

## ζ — Retire the fields at the bump (held leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The fields are in the frozen surface, so retiring them waits for S29 | `FROZEN_SURFACE["ScenarioConfig"]` names `output` and `tariff_config`; `FROZEN_CLOSURE["config.OutputConfig"]` | PASS |
| The platform sets neither | `ScenarioConfig(...)` in `solar-challenge-platform` (seam test) passes only name, period, description, homes and seg | PASS |
| The YAML keys are refused before the fields go | producer: ε, upstream | PASS |
| The `tariff_config` clause | lead question 2: S6 claims the field or ζ retires it | OPEN (decided before S29 releases ζ) |
