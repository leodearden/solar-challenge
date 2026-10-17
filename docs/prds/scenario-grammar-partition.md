# PRD — Scenario grammar: config.py partition and the parameter-sweep deletion

- **Program:** review-all-solar_challenge-20261013, stream **S5** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 2, upstream S1 and S2 (and S4 α by L16), size L, risk low.
- **Finding keys:** fk-62821dcde535 (medium), fk-2dc9d1cd2c06 (medium), fk-59fdc80fdded (medium), fk-caad5305a3be (low; filed as task 237, superseded here), fk-e2aaf2bfe651 (medium), fk-897e13f84164 (medium). None is weakened (D28 lists none of them); §2.3 re-measures the size findings anyway.
- **Binding rulings:** D26 (S5 accepted as the synthesis wrote it), D4 and D29 (only renames and retirements wait for S29; behavioural edits land in-leaf with an "Unreleased on main" line), D9 and L16 (S4 owns construction refusals through `_constructed`; S5's partition depends on S4 α and S4 ε depends on the partition; S5 moves nothing of ε or ζ), L2 (`ConfigurationError` stays a bare type unless a reader needs the path as data), D11 (period: flag > file > default for every command, owned by S6), D18 (the per-type distribution table lives in `fleet_distribution.py`, owned by S18), cross-reference line "S5: moves `parse_dispatch_strategy_config` and `_parse_grid_charge_config` into `scenario_blocks.py`; they construct dispatch types and define none".
- **Status:** authored 2026-10-17 by an author-only agent-mode /prd seat; not committed.
- **Approach:** B + H. The partition is a seam four streams import by name (S4, S6, S18, S26) and every scenario reader crosses it, so §4 is a contract and §5 a two-way boundary-test sketch.
- **Code anchors** verified against main `ac1fdf18ef8c` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time. `config.py` differs from the review's pin `7dfea36e` only by S1 α's (773) move of `ConfigurationError` into `errors.py`; `cli/config.py`, `cli/validate.py` and the `tests/unit/config/` modules differ only by that import line.

## 1. Goal

`config.py` stops being five modules in one. The scenario grammar becomes three files with one import direction, `errors` and `number_fields` ← `scenario_blocks` ← `fleet_distribution` ← `config`. Each file's purpose can be stated without "and". The grammar no longer contains a simulation runner. Every refusal the grammar raises names the block it refuses, in one form. A scenario document can no longer carry a block that nothing reads.

What a user observes:

1. **A library consumer can read one block without the whole grammar.** In a fresh interpreter, `import solar_challenge.scenario_blocks` loads neither `solar_challenge.fleet_distribution` nor `solar_challenge.config`, and `import solar_challenge.fleet_distribution` does not load `solar_challenge.config`. Neither module exists today.
2. **The unused third sweep engine is gone.** `solar_challenge.config.run_parameter_sweep`, `ParameterSweepConfig` and `SweepResult` raise `AttributeError`. Today they exist, and a swept home silently loses its heat pump, EV and SEG tariff (probed in the findings record). `config.py` no longer imports `simulate_home` or `simulate_fleet`. Sweeps run through the paths that ship: `fleet.simulate_multi_sweep_iter`, `optimize.run_sweep` and the web's per-point jobs.
3. **Every refusal names its block.** `solar-challenge validate config` on a file whose `homes[1]` has `heat_pump: {thermal_capacity_kw: 8}` prints the ERROR row `homes[1].heat_pump: requires 'heat_pump_type'`. Today it prints `heat_pump configuration requires 'heat_pump_type' field`, which does not say which home. `homes: 5` prints `homes: must be a list, got int` and exits 1. Today it ends in a `TypeError` traceback (both probed at `ac1fdf18ef8c`). A document that is a YAML list is refused the same way (task 423's structural half).
4. **A scenario document holds only what is read.** `validate config` on a `scenario:` document carrying `output: {csv_path: r.csv}`, a scenario-level `tariff_config:`, or a misspelt key exits 1. Each refusal names the key, and for a retired key it names what to use instead. Today the same file reports "Configuration is valid" and exits 0 (probed). `solar-challenge config template home` and `config template scenario` no longer emit the `output:` block that no command reads.
5. **Guards keep it so.** The per-task verify fails in three cases, each naming the file and line: a grammar module imports one above it, or imports a `simulate_*` runner; a test or src module imports a moved name from `solar_challenge.config`; a grammar function raises `ConfigurationError` other than through the one refusal constructor.

## 2. Background (measured at `ac1fdf18ef8c`)

### 2.1 What config.py holds

`src/solar_challenge/config.py` is 2,810 lines. Grouping its top-level statements (each span runs to the next statement):

| Group | Lines | Members (by symbol) |
|---|---|---|
| Block toolkit and home-component readers | ~535 | `_child_path`, `_block_label`, `_require_mapping`, `_refuse_unrecognised_keys`, `_BlockType`, `_float_or_none`, `_number`, `_number_or_none`; `parse_location_block`, `_parse_pv_config`, `_parse_grid_charge_config`, `_parse_battery_config`, `_parse_load_config`, `parse_dispatch_strategy_config`, the tariff builders and `parse_tariff_config`, `_parse_heat_pump_config`, `_parse_ev_config`, `parse_home_block`; `GridChargeConfig` and `DispatchStrategyConfig` (S2 α moves both to `dispatch.py`) |
| SEG, finance, grid-services and community readers | ~300 | `parse_seg_rate`, `_parse_seg_rate_scalar`, the two coercion tables, `_parse_event_windows`, `_parse_grid_services_events_config`, `parse_finance_config`, `_parse_community_billing_config`, `_parse_community_config` |
| Fleet-distribution grammar, sampler and sweep expansion | ~1,120 | the five distribution types, `SweepSpec`, `DistributionSpec`, the five `*DistributionConfig`s, `FleetDistributionConfig`, the `_build_*_spec` builders, `_parse_distribution_spec`, the component distribution readers, `parse_fleet_distribution_config`, `_DistributionSampler`, `generate_homes_from_distribution`, `detect_sweep_spec`, `_replace_sweep_with_value`, `expand_sweep_configs`; `_VALID_DISPATCH_STRATEGIES` (S2 β moves it to `home.py`) |
| Parameter-sweep runner | ~285 | `ParameterSweepConfig`, `SweepResult`, `run_parameter_sweep`, `_apply_parameter_to_home`, `_modify_pv_config`, `_modify_battery_config`, `_modify_load_config` |
| Documents | ~530 | `SimulationPeriod`, `OutputConfig`, `ScenarioConfig`, `_parse_period`, `_parse_output_config`, `_parse_scenario`, `${VAR}` substitution (after a mid-file `import re`), the file loaders, `load_scenarios`, `load_home_config`, `_FleetFileSettings`, `_read_fleet_distribution_file`, `parse_fleet_config`, `load_fleet_config`, `detect_fleet_sweep_spec`, `parse_sweep_fleet_configs`, `load_community_config` |

An AST reference walk over the top-level names finds the direction acyclic once the runner is gone:

- fleet grammar → block toolkit: `_BlockType`, `_child_path`, `_float_or_none`, `_parse_grid_charge_config`, `_refuse_unrecognised_keys`, `parse_dispatch_strategy_config`, `GridChargeConfig`.
- documents → block readers: `_HOME_BLOCK_KEYS`, `_child_path`, `_refuse_unrecognised_keys`, `parse_home_block`, `parse_location_block`, `parse_tariff_config`, the finance, SEG and community readers.
- documents → fleet grammar: `FleetDistributionConfig`, `SweepSpec`, `detect_sweep_spec`, `expand_sweep_configs`, `generate_homes_from_distribution`, `parse_fleet_distribution_config`.
- Nothing points upward. The one apparent fleet → documents edge is a local variable named `load_config` in `generate_homes_from_distribution`.

So the cycle the findings saw ("fleet_distribution.py would need `from solar_challenge.config import _refuse_unrecognised_keys, …`") goes away once the shared names live in the lowest file and are public there.

### 2.2 Who imports from config

- **src** (AST scan):
  - `ScenarioConfig`, `load_config`, `parse_seg_rate` (6 modules each);
  - `load_fleet_config` (4); `parse_location_block`, `SimulationPeriod` (3);
  - `parse_fleet_config`, `parse_sweep_fleet_configs`, `detect_fleet_sweep_spec`, `parse_finance_config`, `parse_dispatch_strategy_config`, `parse_tariff_config` (2);
  - `parse_home_block`, `SweepSpec`, `generate_homes_from_distribution`, `parse_fleet_distribution_config`, `load_home_config`, `load_scenarios`, `load_community_config`, `substitute_config_variables` (1);
  - `battery.py` and `web/fleet_config.py` name the two dispatch types under `TYPE_CHECKING`, and `web/storage.py` merges `vars(solar_challenge.config)`; S2 α (786) removes all three.
- **tests:** 42 modules import from config, about 29 of them a name that moves (some only the dispatch types S2 α repoints); all import public names. No test or src module imports a private config name.
- **The platform consumer** (`solar-challenge-platform` at `82e71df`) imports `GridChargeConfig` (S2's to move) and `SimulationPeriod` from `solar_challenge.config`, and `ScenarioConfig` from the package root, built with keywords that set neither `output` nor `tariff_config`.
- **Frozen surface:** `FROZEN_CLOSURE` keys derive from `__module__`. The config keys are `config.DispatchStrategyConfig`, `config.GridChargeConfig` (S2 α), `config.OutputConfig` and `config.SimulationPeriod`. The partition keeps `SimulationPeriod`, `OutputConfig` and `ScenarioConfig` in `config.py`, and no distribution type or block reader is named by the frozen surface. So α to ε change no `FROZEN_*` entry. Only ζ, which retires `ScenarioConfig.output` and `OutputConfig`, changes a frozen form.
- **mypy --strict** runs over `src/solar_challenge` with implicit re-export off (S1 observed the `attr-defined` rejection). Once `config.py` only imports `parse_home_block`, `from solar_challenge.config import parse_home_block` fails mypy in src. Tests are not type-checked, which is why γ's guard covers them.

### 2.3 Re-measured findings

| Measurement | Finding | ac1fdf18 |
|---|---|---|
| config.py lines | 2,815 | 2,810 (S1 α removed the class) |
| sweep-runner family, src callers | 0 | 0; only `tests/unit/config/test_parameter_sweep.py` (181 lines) uses it |
| config.py's top-level `simulate_home`/`simulate_fleet` imports, used only by the runner | yes | yes, plus `FleetResults` and `SimulationResults`, used only by it |
| reader-local refusals without the block path | "a few use it" | 40 `raise` sites outside the runner omit it: 27 in a function that already holds `block_path`, 13 in one that holds none (3 of those are C4-exempt or a method: `load_config`, `_substitute_variables`, `_DistributionSampler.sample_with_context`) |
| `ScenarioConfig.tariff_config`, `.output` readers | 0 | 0 (grep of src) |
| `_parse_scenario` refuses an unknown top-level key | (not stated) | no: `{name, period, home, bogus: 1}` loads |

### 2.4 Probes (offline, `uv run --locked --extra dev`)

| Input | Today |
|---|---|
| `validate config` on `homes: [{}, {heat_pump: {thermal_capacity_kw: 8}}]` | ERROR `heat_pump configuration requires 'heat_pump_type' field`, exit 1 |
| `validate config` on `homes: 5` | `TypeError: 'int' object is not iterable` traceback |
| `load_scenarios` on `homes: [{}, {pv: {azimuth: 400}}]` | `ValueError: Azimuth must be 0-360 degrees, got 400` (no path; S4 ε's `_constructed` adds it) |
| `load_scenarios` on a scenario with no `name` | `Scenario must have a 'name' field` |
| `load_scenarios` on `scenarios: [{name: a, period: {start_date: …}, home: {}}]` | `Simulation period requires 'start_date' and 'end_date'` (which scenario?) |
| `validate config` on `scenario: {name, period, home: {}, output: {csv_path: r.csv}, tariff_config: {type: economy_7}, bogus: 1}` | "Configuration is valid", exit 0 |
| `validate config` on each of the 10 shipped `scenarios/*.yaml` | "Configuration is valid" |
| `import solar_challenge.home` in a fresh interpreter | loads pvlib; so dropping config's `simulate_home` import does not change what `import solar_challenge.config` loads (HomeConfig lives in home.py) |

## 3. Resolved design decisions

1. **Three files, named by the stream row.** They are `scenario_blocks.py`, `fleet_distribution.py` and `config.py`. Each states its purpose in its module docstring:
   - `scenario_blocks` reads one block of a scenario file into a value of a domain module, naming the block's path.
   - `fleet_distribution` is the `fleet_distribution:` grammar and the homes it generates, sweep points included.
   - `config` reads whole scenario, fleet and community documents into config's own document types.
2. **Every block reader whose value a domain module defines goes to `scenario_blocks.py`.** That covers the finance, SEG, grid-services and community readers, not only the home blocks. S9's PRD already plans its finance-block work in `scenario_blocks.py`, and an agent asking "where is block X read?" gets one answer. A reader whose type `config.py` defines stays beside the type: `_parse_period` with `SimulationPeriod`, and `_parse_output_config` until ε deletes it. This is the rule's only exception, and it falls out of rule 1.
3. **Names that cross a file line are public in the lower file. Everything else keeps its underscore.** The promoted names are:
   - in `scenario_blocks`: `child_path`, `block_label`, `refuse_unrecognised_keys`, `BlockType`, `float_or_none`, `HOME_BLOCK_KEYS`, `parse_grid_charge_config` and `parse_community_config`;
   - in δ, the refusal constructor and its two helpers.

   `float_or_none` is transitional: S4 ζ (868) deletes it. `_number`, `_number_or_none`, the coercion tables and every component reader stay private, because only `scenario_blocks` reads them.
4. **No re-export, no shim.** An importer imports a name from the module that defines it, src and tests alike (D4; S1's decision 5). `config.py` imports what it uses and exports nothing it does not define. A consumer still spelling `solar_challenge.config.parse_home_block` keeps working at runtime, because config binds the name for its own use, but fails its own `mypy --strict`. The consumption guide says so.
5. **Dispatch first; `scenario_blocks.py` homes no dispatch type.** β depends on S2 α (786), which moves `GridChargeConfig` and the strategy union into `dispatch.py`, and on S2 β (787), which moves `_VALID_DISPATCH_STRATEGIES` to `home.py`. The seam S5 owns ("scenario_blocks.py as the home of battery.py's TYPE_CHECKING types until the Dispatch stream moves them") is therefore discharged without an interim home. γ's guard asserts that `scenario_blocks` and `fleet_distribution` define no dataclass that `dispatch` defines.
6. **Delete the sweep runner; don't move it** (fk-59fdc80fdded, fk-caad5305a3be). It has no src caller and is outside `__all__` and the frozen closure, and it drops 3 of HomeConfig's 10 fields. The deletion goes first (α), so the partition never moves dead code. The other two sweep value generators are S26's: `SweepSpec` stays and moves to `fleet_distribution`, and the web's inline arithmetic goes to S26's registry.
7. **`${VAR}` substitution stays in `config.py`**, with its `import re` hoisted to the module top. Substitution is a transform of a whole document before any block is read, and task 707 is its one editor (S4 decision 10). A `variables.py` leaf (the finding's suggestion) would hold 55 lines with one importer.
8. **One refusal form, one constructor** (fk-e2aaf2bfe651). Every refusal the grammar raises reads `<block label>: <problem>`, built by `scenario_blocks.refusal(block_path, problem) -> ConfigurationError`.
   - `require_mapping`, `refuse_unrecognised_keys`, a new `require_list` and a new `require_keys` build through it. The two existing messages are rephrased to `<label>: must be a mapping, got str` and `<label>: unrecognised keys 'x'; recognised keys: …`.
   - S4 ε's `_constructed`, which wraps a constructor's refusal, already uses the same `<block label>: <message>` form; δ makes it build through `refusal`.
   - **Path as data: no.** `ConfigurationError` gains no `block_path` field. Both boundaries print or return `str(exc)`, and no reader parses it (L2; G1).
9. **Construction refusals are S4's, reader-local refusals are S5's.** The constructor's own message, such as "Azimuth must be 0-360 degrees", gains its path in S4 ε (866) through `_constructed`. δ owns every message a reader writes itself:
   - "requires X";
   - not a mapping, not a list;
   - unknown type;
   - ambiguous forms;
   - the document readers' messages.

   δ follows ε, so fk-e2aaf2bfe651 is closed when δ lands.
10. **`output:` is retired, not given a reader** (fk-897e13f84164). No command reads an output block. The commands that write result files already take a flag for it (`home run --output/--report`, `fleet run --output`); `finance run` and `optimize configs` print to stdout. A file-level default would be a second home for a choice the flag owns. ε refuses the key, naming `--output`; the templates stop emitting it; ζ retires `ScenarioConfig.output` and `OutputConfig` at S29's bump.
11. **A scenario-level `tariff_config:` is refused, and which home it should reach is S6's policy.** The key prices nothing today. Every tariff reader reads `HomeConfig.tariff_config`, and finance then falls back to retail pricing with a "no tariff configured" warning. ε refuses it, naming `home.tariff` / `homes[i].tariff`. The field itself is in the frozen `ScenarioConfig` signature, so it cannot leave before S29. S6 owns how scenario-level blocks reach homes (D10's fill-and-refuse for SEG; D11 for period). If S6 gives the scenario a typed tariff, re-admitted as `tariff:`, the spelling every other tariff block uses, ζ keeps the field. Otherwise ζ retires it (lead question 2). S5 is correct either way: no file can set the field silently.
12. **A scenario document refuses keys it does not read.** `_parse_scenario` gains the unknown-key refusal S6's PRD row already assumes ("the same unknown-key refusal as `_parse_scenario`"). Its recognised keys are what it reads: `name`, `description`, `location`, `period`, `home`, `homes`, `seg`, `finance`. Retired keys are checked first, from one table that maps each key to its replacement message. The home file's `home:` form and the top-level single-scenario form that `validate config` routes to `load_home_config` are S6's (§7). S6's one reader for every document form decides their top-level keys.
13. **`period:` stays in the templates.** D11 makes a file's period block read by every command, through S6. The program row's "dead `period:` keys" becomes live under that ruling, so S5 removes only `output:`.
14. **Six leaves.**
    - α deletes the runner.
    - β extracts `scenario_blocks`.
    - γ extracts `fleet_distribution` and lands the layering guard.
    - δ is the refusal form and its guard.
    - ε covers the scenario document's keys and the templates.
    - ζ is the held retirement.

    β and γ are separate moves so each is reviewable. S4 ε (866) needs only β, and S4 ζ (868) needs γ. Each move is recipe-shaped: by symbol, per the §4.1 table, redone from scratch at its own base, never a rebased stale diff.

## 4. Contract

### 4.1 Module map (after γ, with S2 α and β landed)

| Module | Defines | Imports from the package | Never imports |
|---|---|---|---|
| `scenario_blocks.py` | the block toolkit (`child_path`, `block_label`, `require_mapping`, `refuse_unrecognised_keys`, `BlockType`, `float_or_none`; δ adds `refusal`, `require_list`, `require_keys`); `HOME_BLOCK_KEYS`; readers `parse_location_block`, `parse_grid_charge_config`, `parse_dispatch_strategy_config`, `parse_tariff_config`, `parse_home_block`, `parse_seg_rate`, `parse_finance_config`, `parse_community_config` and their private component readers, builders and key tables | `errors`, `number_fields` (after S4 ε), and domain modules: `battery`, `community`, `dispatch`, `ev`, `finance`, `gridservices`, `heat_pump`, `home`, `load`, `location`, `pv`, `seg`, `tariff` | `fleet_distribution`, `config`, any `simulate_*` |
| `fleet_distribution.py` | the distribution types, `SweepSpec`, `DistributionSpec`, the five `*DistributionConfig`s, `FleetDistributionConfig`; `parse_fleet_distribution_config` and its private readers and builders; `_DistributionSampler`, `generate_homes_from_distribution`; `detect_sweep_spec`, `expand_sweep_configs` | `errors`, `scenario_blocks`, `number_fields` (after S4 ζ), domain modules | `config`, any `simulate_*` |
| `config.py` | `SimulationPeriod`, `OutputConfig` (until ζ), `ScenarioConfig`; `_parse_period`, `_parse_scenario`; `substitute_config_variables`; `load_config_yaml`, `load_config_json`, `load_config`, `load_scenarios`, `load_home_config`, `parse_fleet_config`, `load_fleet_config`, `detect_fleet_sweep_spec`, `parse_sweep_fleet_configs`, `load_community_config` | `errors`, `scenario_blocks`, `fleet_distribution`, domain modules for its own types (`community`, `finance`, `fleet.FleetConfig`, `home.HomeConfig`, `location`, `tariff`) | any `simulate_*` |

Later streams add to these modules by these names:

- S4 ε writes `_constructed` in `scenario_blocks.py`.
- S4 ζ edits the fleet grammar in `fleet_distribution.py`.
- S6 adds its overlay reader and `ScenarioConfig.homes()` in `config.py`.
- S18 adds the per-type distribution table in `fleet_distribution.py` (D18).
- S26's knob registry sits in the `fleet_distribution`/`config` stratum, per its own PRD.

### 4.2 Invariants

| # | Invariant | Enforced by |
|---|---|---|
| C1 | Import direction `errors`, `number_fields` ← `scenario_blocks` ← `fleet_distribution` ← `config`, at any scope | β's and γ's fresh-interpreter tests; γ's AST guard in `tests/unit/test_import_structure.py` |
| C2 | No grammar module imports a name starting `simulate_` from any package module | α (deletes the only use); γ's guard |
| C3 | One spelling: every `from solar_challenge.{scenario_blocks,fleet_distribution,config} import X` in src and tests names an `X` that the module defines; no module imports an underscore name from a grammar module | mypy --strict (src); γ's guard (src and tests) |
| C4 | Every `ConfigurationError` that a module-level function of the three grammar modules raises is built by `scenario_blocks.refusal`, reading `<block label>: <problem>`. Exempt: the file loaders, whose subject is a file path (Permanent), and `_substitute_variables` (Transitional, task 707). Methods of input types (`__post_init__`) name their field (S4) and are not readers | δ's AST guard (seeded-violation test plus the real tree) |
| C5 | Every module-level reader (`parse_*`, `_parse_*`, `_build_*`) in the three modules takes `block_path` | δ's guard |
| C6 | A scenario document is refused if it holds a key `_parse_scenario` does not read. A retired key's refusal names its replacement | ε's tests |
| C7 | α to ε change no parsed value and no `FROZEN_*` entry; β and γ change no message text either | the existing suite; `validate config` OK on the 10 shipped scenarios; `test_public_api_surface.py` unchanged |

Error semantics: `refusal` returns, and does not raise, a `ConfigurationError`, a `ValueError` subclass once S1 β (774) lands. Callers write `raise refusal(...)`, with `from exc` where a cause exists. `block_label("")` is `the top level`.

## 5. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer | the deletion | — | `hasattr(solar_challenge.config, "run_parameter_sweep")` is False, and likewise `ParameterSweepConfig` and `SweepResult`; config.py's source names no `simulate_` | α |
| P2 | producer | block readers alone | fresh `-I` interpreter (pattern of `test_init_lazy_surface.py`) | after `import solar_challenge.scenario_blocks`, `solar_challenge.config` and `solar_challenge.fleet_distribution` are not in `sys.modules` (RED: the module does not exist) | β |
| P3 | producer | fleet grammar alone | fresh interpreter | after `import solar_challenge.fleet_distribution`, `solar_challenge.config` is not in `sys.modules` | γ |
| P4 | producer | layering guard, seeded | `tmp_path` package whose `scenario_blocks.py` holds a function-local `from solar_challenge.config import load_config`, and whose `fleet_distribution.py` imports `simulate_home` | the scan reports both file:line pairs and the rule each breaks | γ |
| P5 | producer | one-spelling guard, seeded | a `tmp_path` test module with `from solar_challenge.config import parse_home_block` | reported, naming the defining module `scenario_blocks` | γ |
| P6 | producer | refusal guard, seeded | a `tmp_path` grammar module whose reader raises `ConfigurationError("x")` directly | reported with file:line; the real tree passes | δ |
| C1 | consumer: CLI | nothing moves for users | the 10 shipped `scenarios/*.yaml` | `validate config` prints "Configuration is valid" for each, as before | β, γ |
| C2 | consumer: web | import-line edits only | existing web route and form tests (`web_api/`, fleet scenario, builder, simulation params) | pass unchanged apart from import lines | β, γ |
| C3 | consumer: S4 | construction refusal gains the path | S4 ε (866) landed | `homes: [{}, {pv: {azimuth: 400}}]` → `homes[1].pv: …azimuth…400`; δ's guard passes with `_constructed` building through `refusal` | δ |
| R1 | consumer: CLI | reader-local refusal | `homes: [{}, {heat_pump: {thermal_capacity_kw: 8}}]` | `validate config` ERROR `homes[1].heat_pump: requires 'heat_pump_type'`, exit 1 | δ |
| R2 | consumer: CLI | list-shaped block | `homes: 5` | ERROR `homes: must be a list, got int`, exit 1, no traceback (RED: `TypeError`, probed) | δ |
| R3 | consumer: CLI | document shape | a YAML file whose document is a list | ERROR `the top level: must be a mapping, got list`, exit 1 | δ |
| R4 | consumer: library | which scenario | `scenarios: [{name: a, period: {start_date: …}, home: {}}]` | `ConfigurationError` reading `scenarios[0].period: requires 'end_date'` | δ |
| S1 | consumer: CLI | retired keys | `scenario:` document with `output:`; another with scenario-level `tariff_config:` | exit 1; the rows name `scenario.output` and `--output`, and `scenario.tariff_config` and `home.tariff` (RED: "Configuration is valid", probed) | ε |
| S2 | consumer: CLI | unknown key | `scenario:` document with `bogus: 1` | exit 1; the row names `scenario` and `'bogus'` | ε |
| S3 | consumer: CLI | templates | `config template home -o h.yaml`, `config template scenario -o s.yaml` | neither text contains `output:`; each file then validates OK | ε |
| H1 | consumer: library | retirement (held) | S29's bump window | `ScenarioConfig(name=…, period=…, home=…, output=None)` raises `TypeError`; `config.OutputConfig` is gone from `FROZEN_CLOSURE` and `test_public_api_surface.py` passes | ζ |

## 6. Existing tasks this PRD meets

| Task | Status at authoring | Relation |
|---|---|---|
| 237 | pending; implemented on `task/237` and under review | Rebuilds the runner's homes with `dataclasses.replace`. Superseded by α, which deletes the code (brief). Cancel with `x_superseded_by` α at decompose if not done. If it has merged, α deletes its result too. |
| 320 | pending, depends on 237 | The runner's scenario-context handling. Superseded by α. |
| 651 | pending | `ParameterSweepConfig.get_values` hangs on step ≤ 0. Superseded by α (S4's PRD lists it as S5's to cancel). |
| 423 | pending | Structural refusals (`homes: 5`, a list document) are δ's (R2, R3). Its numeric half is S4's, so cancel it with `x_superseded_by` δ once S4 ε is filed (it is: 866). |
| 509 | pending | One unrecognised-key rule for config and web. After β, `scenario_blocks.refuse_unrecognised_keys` is public below both, and δ fixes its message form. The web half is S17's (S1 PRD §8). 509 stays and gains a dependency on δ. |
| 866 (S4 ε) | deferred, held with `x_seam_wait {S5, partition module names}` | Gains a dependency on β and is released by this session's decompose. |
| 868 (S4 ζ) | pending | Gains a dependency on γ (it edits the fleet grammar by its final name). |
| 707 | pending | Edits `_substitute_variables`, which stays in config.py. C4's Transitional entry names it. No edge. |
| 297, 422, 485, 186, 558, 559, 599, 600, 616, 706, 755, 759 | pending | Their anchors in config.py move with β and γ. Their architects re-read at dispatch (freshness clause). No edges: none blocks or is blocked by the partition. |

## 7. Cross-PRD relationship

| Other stream / PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 `errors-leaf.md` | consumes | `errors.ConfigurationError` as the grammar's one refusal type; 775's `tests/unit/test_import_structure.py` gains γ's rules | S1 | 773 done; β depends on 774 (it edits `_parse_event_windows`) and 775 (the guard file) |
| S2 `dispatch-configuration-below-config.md` | consumes | `dispatch.GridChargeConfig`, the strategy-config union, `home.HOME_DISPATCH_STRATEGIES`; the two readers move into `scenario_blocks.py`, constructing those types and defining none | S2 types, S5 move | β depends on 786 and 787; S2 ε (790, held) edits the readers by their final names |
| S4 `finite-quantities.md` | both | `number_fields` at the package leaf (860) below the grammar; `_constructed` (866) and the fleet-grammar construction (868) written in `scenario_blocks.py` / `fleet_distribution.py`; `_constructed` builds through `refusal` | S4 owns `_constructed`; S5 owns the layout and `refusal` | L16: β depends on 860; 866 depends on β; 868 depends on γ; δ depends on 866 and 868 |
| S6 fleet-document overlays (PRD not yet authored) | consumes | the final layout; `_parse_scenario`'s unknown-key refusal (ε) that S6's row assumes; S6 owns the top-level keys of the home file and of the single-scenario form `validate config` routes to `load_home_config`; S6 decides `ScenarioConfig.tariff_config`'s fate (decision 11) | S6 | **proposed:** S6 depends on γ and ε |
| S7 component defaults (PRD in this pass) | file overlap | S7 edits the distribution configs, the sampler and the component block key tables that β and γ move; the `_modify_*` copies are deleted by α, not edited by S7 | S7 content, S5 layout | **lead question 1** (default: β and γ depend on S7's config.py leaves) |
| S9 `grid-services-pricing-model.md` | file overlap | its typed events block and finance-grammar edits land wherever `BlockType` and `parse_finance_config` sit at its base: `scenario_blocks.py` after β | S9 | order-insensitive, per S9's own row |
| S11 `tariff-coverage-classifier-presets.md` | file overlap | `parse_tariff_config` and the dispatch reader move to `scenario_blocks.py`; block paths on tariff *reader* messages are δ's, and on constructor refusals S4 ε's | S11 / S5 | order-insensitive |
| S14 `pv-model-one-home.md` | file overlap | `_parse_pv_config`, `PVDistributionConfig`, `generate_homes_from_distribution` move; α deletes `_modify_pv_config` | S14 / S5 | whichever lands second rebases (S14's row) |
| S15, S16 (`weather-as-explicit-input.md`, `fleet-execution-policy.md`) | file overlap | `run_parameter_sweep` is deleted by α; they edit it only if it is present | S5 deletion | order-agnostic, per their rows |
| S17 web request boundary | consumes | web readers import `parse_*` from `scenario_blocks`; task 509's web half can call `scenario_blocks.refuse_unrecognised_keys` | S17 | no edge; textual |
| S18 dashboard limits | consumes | the per-type distribution table goes in `fleet_distribution.py` (D18) | S18 | **proposed:** S18 depends on γ |
| S26 sweep knob registry | consumes | `SweepSpec` in `fleet_distribution`; the remaining value generator of fk-59fdc80fdded (web/api.simulate_sweep's inline arithmetic, unknown mode read as linear) is S26's | S26 | **proposed:** S26 depends on γ; S26's api leaf carries fk-59fdc80fdded too |
| S28 `battery-efficiency-and-throughput.md` | file overlap | `_parse_battery_config` moves with S28 α's both-forms refusal intact | S28 / S5 | textual (863 needs no edge) |
| S29 surface bump | produces for | ζ: `ScenarioConfig.output`, `OutputConfig` and, unless S6 claims it, `ScenarioConfig.tariff_config` retired | S29 releases ζ | ζ held |

fk-e2aaf2bfe651 is closed by S4 ε (construction refusals) together with δ (reader-local refusals and the guard); δ depends on ε, so it carries the key. fk-59fdc80fdded is closed by α and γ (no runner in the grammar; sweep expansion has its stratum) together with S26 (one value generator).

## 8. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries the following metadata:
- `x_finding_key` (list), `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`;
- priority = the highest severity among its keys;
- file-level `metadata.files`.

Each leaf records the measurement of §2.3 it re-measured at its base.

**α — Delete the parameter-sweep runner and its tests** (leaf; priority medium)

- **Keys:** fk-59fdc80fdded, fk-caad5305a3be.
- **Modules:**
  - `src/solar_challenge/config.py`;
  - `tests/unit/config/test_parameter_sweep.py` (deleted);
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Delete `ParameterSweepConfig`, `SweepResult`, `run_parameter_sweep`, `_apply_parameter_to_home`, `_modify_pv_config`, `_modify_battery_config` and `_modify_load_config`.
  - Drop the top-level imports only they use: `simulate_home`, `SimulationResults`, `simulate_fleet`, `FleetResults`, and `Iterator` if it goes unused.
  - Drop "and parameter sweep functionality" from the module docstring.
  - Delete the test file.
  - Add an Unreleased line: these three submodule names are removed. They had no package caller. Sweeps run through `fleet.simulate_multi_sweep_iter`, `optimize.run_sweep` and the web's sweep endpoint.
  - Supersedes 237, 320 and 651.
- **Signal:**
  - P1: `python -c "import solar_challenge.config as c; c.run_parameter_sweep"` raises `AttributeError`.
  - `grep -E 'simulate_(home|fleet)' src/solar_challenge/config.py` finds nothing.
  - The full suite passes.
- **Consumer:** β and γ (no dead code to move); S7 and S14 (no `_modify_*` copies left to edit); S15 and S16 (no runner left to repoint).
- **Prereqs:** none.

**β — scenario_blocks.py: the block toolkit and every block reader** (intermediate; unlocks γ, 866; priority medium)

- **Keys:** fk-62821dcde535, fk-2dc9d1cd2c06.
- **Modules:**
  - `src/solar_challenge/scenario_blocks.py` (new) and `config.py`;
  - import lines of `cli/finance.py`, `cli/home.py`, `cli/optimize.py`, `cli/fleet.py`, `web/builder_form.py`, `web/fleet_scenario.py` and `web/simulation_params.py`;
  - the docstring of `scenario_writer.py`, which names the parsers it inverts;
  - the importing test modules;
  - `tests/unit/test_import_structure.py`;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Move the scenario_blocks row of §4.1 by symbol.
  - Make the decision-3 names public.
  - Give `config.py` top-level imports of what it uses.
  - Repoint every src and test importer (decision 4).
  - Add P2 and the first guard rule: scenario_blocks imports neither config nor fleet_distribution, at any scope.
  - Add an Unreleased line: the block readers (`parse_home_block`, `parse_location_block`, `parse_tariff_config`, `parse_dispatch_strategy_config`, `parse_seg_rate`, `parse_finance_config`) live in `solar_challenge.scenario_blocks`. `solar_challenge.config` still binds them at runtime but no longer exports them to mypy --strict.
  - Redo the move at the task's own base, from the table, not from a stale diff.
- **Signal:**
  - P2: a fresh interpreter imports `solar_challenge.scenario_blocks` without loading `solar_challenge.config`. RED today: no such module.
  - C1: `validate config` prints OK on all 10 shipped scenarios.
  - C2 holds; mypy --strict and the suite are green.
- **Consumer:** γ; S4 ε (866) writes `_constructed` here; S9, S11, S28 edit readers here; S17's web readers.
- **Prereqs:** α, 774, 775, 786, 787, 860 (L16); per lead question 1, S7's config.py leaves.

**γ — fleet_distribution.py: the fleet grammar, sampler and sweep expansion; the layering guard** (leaf; priority medium)

- **Keys:** fk-62821dcde535, fk-2dc9d1cd2c06, fk-59fdc80fdded.
- **Modules:**
  - `src/solar_challenge/fleet_distribution.py` (new) and `config.py`;
  - import lines of `cli/fleet.py` (`SweepSpec`) and `web/fleet_scenario.py`;
  - the importing test modules;
  - `tests/unit/test_import_structure.py`;
  - `review/briefing.yaml`, a `conventions` entry pointing at the guard;
  - the "Configuration System" section of `CLAUDE.md`, which today describes config.py alone and calls scenario_writer "the inverse of config.py's parsers";
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Move the fleet_distribution row of §4.1 by symbol.
  - Hoist `import re` in config.py.
  - Write module docstrings stating decision 1's purposes.
  - Complete the guard for C1–C3: import direction at any scope; no `simulate_*` name; one spelling in src and tests; no underscore import from a grammar module; no dispatch dataclass defined in a grammar module (decision 5). Seed P4 and P5.
  - Add an Unreleased line: the distribution types, `FleetDistributionConfig`, `SweepSpec`, `parse_fleet_distribution_config` and `generate_homes_from_distribution` live in `solar_challenge.fleet_distribution`.
  - Record the final line counts of the three modules in the commit message (fk-2dc9d1cd2c06's instruction), not in a docstring.
- **Signal:**
  - P3: a fresh interpreter imports `fleet_distribution` without config.
  - P4 and P5: the guard names each seeded violation by file and line; the real tree passes.
  - C1: `validate config` stays OK on the 10 shipped scenarios.
  - `config.py` is about 530 lines, `fleet_distribution.py` about 1,100 and `scenario_blocks.py` about 800, each under the 2,000 alarm, with one purpose each.
  - The briefing carries the rule.
- **Consumer:** every agent that edits the grammar (S4 ζ 868, S6, S7, S14, S18, S26); /review through the briefing.
- **Prereqs:** β.

**δ — Every grammar refusal names its block: one refusal constructor and its guard** (leaf; priority medium)

- **Keys:** fk-e2aaf2bfe651.
- **Modules:**
  - `scenario_blocks.py`, `fleet_distribution.py`, `config.py`;
  - `tests/unit/config/` (message pins);
  - `tests/unit/test_cli.py`;
  - the e2e and web tests that pin "Unrecognised keys in" or "must be a mapping" text from config;
  - a new test module (suggested `tests/unit/config/test_block_paths.py`);
  - `tests/unit/test_import_structure.py` or the new module for the C4/C5 guard;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Add `refusal`, `require_list` and `require_keys` (decision 8).
  - Rebuild `require_mapping` and `refuse_unrecognised_keys` through them.
  - Convert every reader-local and document-reader refusal measured in §2.3 (37 sites at authoring, re-counted at δ's base) and the sampler's sampled-value refusals in `generate_homes_from_distribution`, which know their key path.
  - Rename `_parse_distribution_spec`'s `param_name` to `block_path` (C5).
  - Turn `_parse_community_config`'s `except ValueError → ConfigurationError(str(exc))` into a path-naming refusal, or into `_constructed` if S4 L1 has made `CommunityConfig` raise ConfigurationError.
  - Make `_constructed` build through `refusal`.
  - Require list-shaped values to be lists: `homes`, `scenarios`, a tariff's `periods`, `event_windows`, `peak_hours`.
  - Require each loader's document to be a mapping.
  - Add the AST guard for C4/C5 with its exemption table (file loaders: Permanent; `_substitute_variables`: Transitional, task 707) and seed P6.
  - Add an Unreleased line: grammar refusals now read `<block path>: <problem>`; two message forms changed.
  - Supersedes 423.
- **Signal:**
  - R1–R4 via `validate config` and `load_scenarios`.
  - `homes: 5` gets an ERROR row instead of a traceback (RED today, probed).
  - C3: `homes[1].pv` names `azimuth` and `400`.
  - P6: a seeded direct raise is named; the real tree passes.
- **Consumer:** CLI users (`validate config`, every command through `handle_errors`); the web, through S17's translator, which returns the message; S4's `_constructed`; task 509's unified web rule.
- **Prereqs:** γ, 866 (S4 ε), 868 (S4 ζ).

**ε — The scenario document refuses what nothing reads; the templates stop emitting `output:`** (leaf; priority medium)

- **Keys:** fk-897e13f84164.
- **Modules:**
  - `config.py` (`_parse_scenario`, deleting `_parse_output_config` and `_OUTPUT_BLOCK_KEYS`);
  - `cli/config.py` (`HOME_TEMPLATE`, `SCENARIO_TEMPLATE`, the `template` help text);
  - `tests/unit/config/test_unrecognised_keys.py` (its `output` and scenario `tariff_config` cases become retired-key refusals);
  - `tests/unit/config/test_scenario_file.py`;
  - `tests/unit/test_cli.py`;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Decision 12's recognised-key set.
  - One retired-key table: `output` → "no command reads an output block; pass --output to the command instead"; `tariff_config` → "a scenario-level tariff prices no home; set home.tariff, or each homes[i].tariff". It is checked before the unknown-key refusal.
  - Delete the templates' `output:` blocks and keep `period:` (decision 13).
  - Measure at ε's base whether any test or fixture feeds `load_scenarios` a key outside the set, and fix it.
  - Add an Unreleased line: scenario documents refuse `output:`, a scenario-level `tariff_config:` and unknown keys, where the tag accepts and ignores them.
- **Signal:** S1–S3. `validate config` exits 1 on a `scenario:` document carrying `output:` or `tariff_config:`, naming the key and the replacement (RED today: "Configuration is valid", probed). `config template scenario` prints no `output:`, and the written template validates OK.
- **Consumer:** CLI users; S6 (builds on the scenario unknown-key refusal); ζ.
- **Prereqs:** γ.

**ζ — Retire `ScenarioConfig.output` and `OutputConfig` (and `ScenarioConfig.tariff_config` unless S6 claims it) at the surface bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "the surface bump release window"}`; excluded from this batch's `commit_planning`)

- **Keys:** fk-897e13f84164.
- **Modules:**
  - `config.py`;
  - `tests/unit/test_public_api_surface.py` (the `ScenarioConfig` form loses `output` and maybe `tariff_config`; the `config.OutputConfig` closure entry goes);
  - `tests/unit/config/test_scenario_file.py` (the `OutputConfig` tests);
  - `docs/domain-library-consumption.md`, through S29's section.
- **Work:**
  - Delete the field(s) and the class.
  - ε's retired-key messages stay: they describe the file grammar, not the field.
  - S29's release section line: "`ScenarioConfig(output=…)` and `config.OutputConfig` retired; pass `--output` to the command. Platform: none (it sets neither)."
- **Signal:** H1.
- **Consumer:** S29's release section and consumer recipe.
- **Prereqs:** ε; S29 releases it; lead question 2 decides the `tariff_config` clause before release.

**DAG.** α → β → γ → {δ, ε}; ε → ζ (held).

**Out-of-batch edges:**
- β → {774, 775, 786, 787, 860}, plus S7's config.py leaves per lead question 1;
- δ → {866, 868};
- 866 → β; 868 → γ;
- 509 → δ.

**Proposed for later sessions:** S6 → {γ, ε}; S18 → γ; S26 → γ.

No leaf is high or critical, so none joins trigger-chain gate 772. See lead question 3: β and γ gate high leaves of S4.

**G7** (advisory: this repo has no `docs/legibility/design-invariants.md`; walked against dark-factory's trigger shapes):

- **`one-fact-one-home`:**
  - one home per grammar name (C3), with no re-export shim;
  - one refusal form (C4);
  - one retired-key table.
- **`no-silent-fail-soft`:**
  - ε removes three silent accepts (`output:`, scenario `tariff_config:`, unknown scenario keys);
  - δ turns two tracebacks into named refusals;
  - α removes a runner that silently dropped home fields.
- **`exceptions-owned-or-ratified`:** C4's two exemptions carry a Permanent contract or a Transitional owner, as S1's γ allow-list does.
- **`guards-exercise-behaviour`:**
  - the guards scan the real tree and a seeded `tmp_path` violation;
  - the fresh-interpreter tests import the modules;
  - no guard asserts prose.
- **`no-lockstep-duplication`:** none added. β and γ move code once, and the module map is the one table later streams read.

## 9. Out of scope

- Construction refusals' block paths and every number coercion (S4 ε, ζ: `_constructed`, `number_fields`).
- The dispatch types and the home/fleet dispatch key (S2).
- How a fleet document's or a home file's top-level blocks reach homes, including:
  - `load_home_config`'s `home:` form ignoring its other top-level keys;
  - `validate config` routing a top-level single-scenario document through `load_home_config`;
  - `ScenarioConfig.homes()` and `with_seg()` (S6).
- The web's inline sweep value generator and the sweep knob registry (S26).
- The per-type distribution table the web editor reads (S18).
- Component defaults and the shared block key tables (S7).
- `${VAR}` substitution's refusals (task 707).
- The web's own unrecognised-key rule (S17 / task 509).
- Splitting `fleet_distribution.py` (~1,100 lines) further: it is under the alarm, with one purpose.

## 10. Open questions

**Tactical** (decide during the leaf):

1. δ: the exact names `refusal` / `require_list` / `require_keys`, and whether the guard lives in `test_import_structure.py` or `tests/unit/config/test_block_paths.py`. C4's rule and its exemption table are fixed.
2. δ: whether a sampled-value refusal in `generate_homes_from_distribution` names the spec's path (`fleet_distribution.pv.capacity_kw`) or the home's (`fleet_distribution` home 7). The former is the default, since the sampler knows it statically.
3. β/γ: the order in which to repoint the ~29 test modules (one commit or per directory). Either is fine.
4. ε: the exact wording of the two retired-key messages. Each must name the key's path and the replacement.

**For the lead** (cross-stream; S5's design holds whichever way each goes):

1. **Ordering against S7.** S7, authored in this same pass, edits the distribution configs, the sampler (`dataclasses.replace` over default instances, pool bounds) and the block key tables that β and γ move. Every move should land once. **Default:** β and γ depend on S7's config.py leaves (wave 1 before wave 2), and S7's leaves take no edge on S5. The alternative mirrors L16: S7's config.py leaves depend on γ and edit `fleet_distribution.py` / `scenario_blocks.py` by name, which delays S7 behind 774, 786, 787 and 860.
2. **`ScenarioConfig.tariff_config` at the bump.** ε refuses the YAML key now. Should S6 keep the field as the typed home of a scenario-level tariff (re-admitted as `tariff:` under its fill-and-refuse policy, D10's analogue)? Or does ζ retire it with `output`? **Default:** S6 decides in its /prd session; if it names no reader, ζ retires it.
3. **Priority of β and γ.** Their keys are medium, but S4 ε (866, high) waits on β and S4 ζ (868, high) on γ, so both sit on the critical path to trigger gate 772's S4 leaves. **Default:** file at medium per the convention, and let the scheduler's dependency order carry them. The alternative is to file both as high.
4. **Task 237 is implemented and under review on `task/237`.** If it merges, α still deletes everything it changed. **Default:** cancel it at S5's decompose with `x_superseded_by` α if it is not done by then. Stopping it now would save its review; that is the lead's call.

## Gate record

- **G1:**
  - `scenario_blocks.py` is consumed by config.py, fleet_distribution.py, seven CLI and web modules, and S4 ε, S9, S11, S28 and S17.
  - `fleet_distribution.py` is consumed by config.py, cli/fleet, web/fleet_scenario, S4 ζ, S18 and S26.
  - `refusal` is consumed by every grammar reader, S4's `_constructed`, and the CLI and web boundaries that print the message.
  - The layering, spelling and refusal guards are consumed by every grammar edit's verify and by /review's briefing.
  - The scenario unknown-key refusal is consumed by S6.
  - No producer is orphaned. `ConfigurationError` gains no path field because nothing would read it.
- **G3:** every substrate was verified at `ac1fdf18ef8c`:
  - the import graph (AST walk, §2.1);
  - the importer lists (§2.2);
  - the frozen closure keys (`test_public_api_surface.py`);
  - mypy --strict with no implicit re-export (`pyproject.toml`; S1's observed rejection);
  - the fresh-interpreter pattern (`test_init_lazy_surface.py`);
  - `validate config`'s exit 1 on an ERROR row (ran);
  - the `config template` command and its `--output` option;
  - 775's guard file on `task/775`, and `review/briefing.yaml`'s `conventions` list.

  Producers outside the batch (774, 775, 786, 787, 860, 866, 868) are upstream of their consumers.
- **G4:**
  - S4's construction/reader split is resolved per S4's own PRD.
  - S5's seam over battery's `TYPE_CHECKING` types is discharged by ordering Dispatch first.
  - The S7 overlap and the `tariff_config` fate go to the lead (questions 1, 2).
  - S6, S18 and S26 dependencies are proposed (§7).
- **G5:** B + H.
  - The blast radius is the three grammar modules, seven CLI and web importers, about 29 test modules and four consuming streams.
  - §4 is the contract.
  - §5 is the two-way test sketch.
  - γ, δ and ε are the leaves whose signals the sketch drives.
- **G6:** the premises were checked as follows.
  - RED today, probed: δ's R1 message, R2's traceback, ε's S1/S2 "valid", and P2/P3 (no modules).
  - α's deletion has 0 src callers (grep), and the platform uses none of the names.
  - C7's "no frozen change" holds: no moved class is named by the frozen surface.
  - The end-to-end capabilities lie in each leaf's dependency set: C3 needs 866 upstream of δ, and S1's "valid" needs only ε.
  - Rejection mechanisms are observed: mypy's attr-defined, and `validate`'s exit 1.
  - The size figures are measured spans, not bounds.
- **G7:** advisory, walked in §8.
- **META:** decomposing this without further oversight yields three files with one import direction and one purpose each, no runner in the parser, one refusal form that names every block, and a scenario grammar that refuses what nothing reads. Each property is guarded. The open lead questions order or assign work across streams and do not change S5's design.
