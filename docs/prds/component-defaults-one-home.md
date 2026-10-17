# Component defaults: one home per component, distributions derive from it

**Status:** authored 2026-10-17 in the agent-mode /prd pass, not committed. Program `review-all-solar_challenge-20261013`, stream S7, wave 1, no upstream stream. Upstream task 297. Contract-first (B + H).

**Code anchors** verified against main `ac1fdf1` (2026-10-17). Main moves fast: cite by symbol and re-locate lines at implementation time. Against the review's pin `7dfea36e`, `config.py` differs only in that `ConfigurationError` moved to `errors.py`. `scenario_writer.py`, `heat_pump.py` and `ev.py` are unchanged. `pv.py`'s changes since the pin (task 756) and `battery.py`'s (docstrings) leave the fields this PRD reads untouched.

## 1. Goal

Each component's field list and defaults are stated once, on its domain dataclass: `PVConfig`, `BatteryConfig`, `LoadConfig`, `HeatPumpConfig`, `EVConfig`, plus `Location` for the location block. Every reader and writer derives from that dataclass:

- the home-block parsers;
- `scenario_writer`;
- the fleet-distribution grammar and its sampler.

A heat-pump type is one record. A seeded fleet that generates today generates the same homes afterwards.

What a user sees when this lands:

- **PV system losses can be set from YAML.** A `home:` block with `pv: {system_losses: 0.05}` simulates with 5% losses. Today the key is refused as unrecognised. A `HomeConfig` with `system_losses=0.05` is written by `scenario_writer` and loads back as 0.05; today it loads back as 0.14076 with no error. A fleet can draw `system_losses`, `temperature_coefficient` and `inverter_capacity_kw` too, along with the battery's SOC limits, efficiencies and ageing.
- **One rule for what a block may leave out.**
  - A `heat_pump:` block without `thermal_capacity_kw` gets an 8 kW heat pump.
  - An `ev:` block without `arrival_hour` arrives at 18:00.
  - Today both blocks are refused, while the fleet grammar silently supplies those same numbers.
  - A key written as `null` reads as absent. Today `pv: {tilt: null}` raises a raw `TypeError`.
- **Fleets that go wrong silently or crash now either generate or are refused by name.** Measured at `ac1fdf1` (§3.1):
  - a `heat_pump_type` shuffled pool gives 0 heat pumps;
  - a `proportional_to` source spelled `pv.capacity` gives 0 batteries;
  - a pool on `pv.tilt` under `bristol_legacy` raises a bare `KeyError(<object id>)`;
  - one pool object shared by two fields raises `IndexError`;
  - `proportional_to` on a PV field raises "Unknown distribution type: <class …>";
  - `heat_pump_type: XSHP` passes the parser and fails mid-generation.

  After δ and ε each of these either generates the fleet it describes or is refused when the file is read. The refusal names the field path and the rule. It reaches `validate config`, `fleet run`, `finance run`, `optimize` and the dashboard's fleet routes as a `ConfigurationError`.
- **Adding a heat-pump type means editing two adjacent lines in `heat_pump.py`**: the `Literal` and one curve record, tied together by a test. Today the vocabulary is spelled in five places and the curves are eight loose constants.

## 2. Background

Findings (all `confirmed`):

| Key | Severity | Anchor | Leaf |
|---|---|---|---|
| fk-148991ab9439 | high | `config.py::_modify_battery_config` | β, δ; the sweep half closes with S5's deletion |
| fk-0e58e2a7e007 | high | `config.py::generate_homes_from_distribution` | δ, ε |
| fk-d2b4045c6676 | medium | `config.py::_modify_pv_config` | β; the sweep half closes with S5's deletion |
| fk-dfeefbe95640 | medium | `config.py::generate_homes_from_distribution` | β, δ; web half by cross-reference to S17 |
| fk-f2e1ad46df4b | medium (mechanical, filed:297) | `config.py::_DistributionSampler` | 297, γ, ε |
| fk-2b16cc8bcf46 | medium | `scenario_writer.py::_pv_block` | β |
| fk-d6f16d95b126 | low | `heat_pump.py::calculate_cop` | α |

### 2.1 What is restated today (`ac1fdf1`)

- **PV.** Five `PVConfig` defaults (azimuth 180.0, tilt 35.0, module_efficiency 0.20, inverter_efficiency 0.96, degradation_rate_per_year 0.005) each appear three more times:
  - in `PVDistributionConfig`'s field defaults;
  - in `_parse_pv_distribution_config`'s `data.get(..., <literal>)` calls;
  - in `generate_homes_from_distribution`'s `x if x is not None else <literal>` fallbacks.
- **Battery.** `BatteryConfig`'s 2.5 kW limits appear in the same three places.
- **Heat pump.** The 8000.0 demand appears in `HeatPumpConfig`, `HeatPumpDistributionConfig`, `_parse_heat_pump_config`, `_parse_heat_pump_distribution_config` and the generator's fallback. The web's `simulation_params._parse_heat_pump_block` adds a sixth copy. `HeatPumpConfig.thermal_capacity_kw` has no default, yet the distribution class, its parser, the generator and the web each invent 8.0.
- **EV.** Departure 7, required charge 35.0 and mode `"none"` appear in `EVConfig`, `_parse_ev_config`, `EVDistributionConfig`, its parser and the generator. `EVConfig.arrival_hour` has no default, yet the fleet grammar invents 18.
- **Load.** `LoadDistributionConfig` restates occupants 3 and `use_stochastic` True. The generator's `int(x) if x else 3` turns a sampled 0 into 3.
- **Field lists.** Every block's keys are listed twice by hand: `config._PV_BLOCK_KEYS` (and the battery, load, heat-pump, EV and location sets) and `scenario_writer`'s per-block dict literals. They already drift:
  - `PVConfig.system_losses` is in neither list.
  - `_pv_block`'s guard against fields the grammar cannot express names only the two `custom_*` dicts.
  - The fleet grammar's lists are a third, smaller copy, with no PV `temperature_coefficient`, `inverter_capacity_kw` or `system_losses`, and no battery SOC limits, efficiencies or ageing.
- **Fleet field axis.** `generate_homes_from_distribution` (211 lines) decides inline, field by field, which spec types each field can draw. Its `all_specs` list omits `heat_pump_type`. `_DistributionSampler` keys pools and pre-samples by `id(spec)`, indexes pools without a bound, and receives a context holding only `pv.capacity_kw`. Heat-pump and EV categorical values travel in `WeightedDiscreteDistribution.values: tuple[Optional[float], ...]`, behind a `type: ignore`, a `cast` and a `str()`.
- **Heat-pump vocabulary.** It is spelled in the `HeatPumpType` Literal, `HeatPumpConfig.__post_init__`'s `valid_types`, `calculate_cop`'s if/elif and its message, and the generator's tuple, message and `cast`. Eight loose module floats (`ASHP_COP_*`, `GSHP_COP_*`) hold the curves.

### 2.2 In-flight tasks on these keys

| Task | Status | Overlap | Disposition (decompose, after contract §8 step 1) |
|---|---|---|---|
| 297 | pending, complete plan.json | refuse a shuffled pool whose counts ≠ n_homes, at `FleetDistributionConfig.__post_init__` and at generation start | **kept**, γ depends on it (as S14 kept 756) |
| 403 | pending | defect 1: a pool on an unprepared field raises `KeyError`; defect 2: a `heat_pump_type` pool is ignored | superseded by γ (defect 1) and δ (defect 2) |
| 662 | pending | pools keyed by `id(spec)` | superseded by γ |
| 600 | pending | the distribution layer's restated defaults | superseded by δ |
| 599 | pending | the heat-pump, EV and location parsers' inline defaults | superseded by β |
| 283 | pending | `system_losses` in the `pv:` block and the fleet's pv block | superseded by β (home) and δ (fleet) |
| 395 | pending | occupants `int()` and `if x else 3` in the generator; introduces the sampler's count rounding | **kept**; δ consumes its count conversion if it has landed (§6 decision 9) |
| 237, 320 | pending | `run_parameter_sweep` field drops and scenario context | S5's, which deletes the sweep (not S7) |

## 3. Re-measurement and probes (`ac1fdf1`)

### 3.1 Behaviour probes

Run with `uv run --locked --extra dev python -I <probe>`, using `parse_fleet_distribution_config` then `generate_homes_from_distribution` at Bristol, or `parse_home_block`.

| # | Input | Today |
|---|---|---|
| P1 | `home.pv: {capacity_kw: 4, system_losses: 0.05}` | `ConfigurationError: Unrecognised keys in home.pv: 'system_losses'` |
| P2 | `HomeConfig(PVConfig(4.0, system_losses=0.05))` → `home_scenario` → `parse_home_block` | writer's pv keys omit `system_losses`; reads back 0.14075660688264469 |
| P3 | 10 homes, `heat_pump_type: {shuffled_pool, values [ASHP, null], counts [5, 5]}` | 0 heat pumps |
| P4 | battery `capacity_kwh: {proportional_to, source: pv.capacity}` | 0 batteries of 4 |
| P5 | pv pool counts [2, 2] for 5 homes | `IndexError: list index out of range` (297's case) |
| P6 | `random_order: bristol_legacy`, `pv.tilt` pool [30, 40] × [2, 2] | `KeyError: 132606489280928` |
| P7 | one `ShuffledPoolDistribution` object as both `pv.tilt` and `pv.azimuth` | `IndexError` |
| P8 | `pv.tilt: {proportional_to, source: pv.capacity_kw}` | `ConfigurationError: Unknown distribution type: <class '…ProportionalDistribution'>` |
| P9 | pv pool counts [50, 50] for 4 homes | accepted; capacities [4, 3, 4, 4] |
| P10 | `heat_pump: {heat_pump_type: ASHP}` home block | refused: requires `thermal_capacity_kw` |
| P11 | `ev: {charger_type: 7kW}` home block | refused: requires `arrival_hour` |
| P12 | fleet `load.household_occupants: 0` | every home gets 3 occupants |
| P13 | fleet `heat_pump_type: XSHP` | the parser accepts it; generation raises "Invalid heat pump type sampled" |
| P14 | fleet `pv.temperature_coefficient`; fleet `battery.min_soc_fraction` | refused as unrecognised keys |
| P15 | `heat_pump.annual_heat_demand_kwh: null`; `pv.tilt: null` | raw `TypeError` (float(None); `<=` on None) |
| P16 | `PVConfig(custom_module_params=…)` written | refused naming the field (kept, computed after β) |
| P17 | `FleetDistributionConfig.__dataclass_params__.frozen` | False |

### 3.2 Shipped fleets

Every tracked `scenarios/*.yaml` with a `fleet_distribution:` generates today:

| File | Homes | random_order | Batteries | EVs | Heat pumps |
|---|---|---|---|---|---|
| `bristol-phase1.yaml` | 100 | bristol_legacy | 60 | 0 | 0 |
| `bristol-phase1-aged.yaml` | 100 | bristol_legacy | 60 | 0 | 0 |
| `bristol-with-evs.yaml` | 100 | default | 60 | 30 | 0 |
| `bristol-phase1-flex.yaml` | 100 | default | 100 | 0 | 0 |
| `bristol-fin-calibration.yaml` | 100 | default | 100 | 0 | 0 |
| `bristol-phase1-proportional-battery-sweep.yaml` | 16 sweep points × 100 homes | default | — | — | — |

These six are γ's reproducibility pins (§6 decision 8).

### 3.3 COP curves

The values α must reproduce, at −20, −5, 0, 7, 20 and 40 °C:

- ASHP: [1.8, 2.0, 2.5, 3.2, 4.5, 4.5]
- GSHP: [3.4, 3.7, 3.8, 3.94, 4.2, 4.6]

## 4. Sketch of approach

1. **α. A per-type record.** `heat_pump.COP_CURVES` maps each `HeatPumpType` to a frozen `CopCurve(intercept, slope, minimum, maximum)`. `HEAT_PUMP_TYPES = get_args(HeatPumpType)` is the runtime vocabulary. A test asserts that the Literal's arguments and the record's keys are the same set. `calculate_cop` is a lookup. `HeatPumpConfig`'s check and config's fleet check read `HEAT_PUMP_TYPES`. The eight constants, the generator's tuple and the `cast` go.
2. **β. Component block tables.** Config's grammar declares one `ComponentBlock` per component (§5.1). The table holds:
   - the block's keys, which are the dataclass fields it carries, in field order;
   - the fields the grammar does not carry, each with a reason;
   - its sub-blocks (battery `dispatch_strategy` and `grid_charging`, with S2's grammar);
   - the parser's when-omitted policy (PV 4.0 kW, battery 5.0 kWh, the location block's Bristol values).

   How the tables are used:
   - The home-block parsers read the keys from the table and drop null keys. A required field is one with no dataclass default, refused by name when absent. The parsers pass the rest as written. S4 ε later wraps that construction in `_constructed`.
   - `scenario_writer` emits every key from the same table. It refuses a config that sets a non-grammar field to a non-default value, computed from `dataclasses.fields`.
   - A coverage test holds each table equal to its dataclass's fields.
   - `system_losses` joins the PV keys.
   - `HeatPumpConfig.thermal_capacity_kw` gains its default of 8.0 and `EVConfig.arrival_hour` its default of 18. Both are additive under D29.
3. **γ. Sampler state per field path.**
   - `_DistributionSampler` keys pools and pre-samples by field path.
   - It shuffles every pool in both random orders: the legacy four first, in their order, then the rest in the default order.
   - A pool that runs dry raises an error naming its path (exhaustion is already refused at construction by 297).
   - Each stateless spec type draws itself.
   - Golden fixtures pin the homes every shipped fleet and a probe set generate, captured before the change.
4. **δ. The fleet grammar from the tables.**
   - One frozen `ComponentDistribution(draws, settings)` replaces the five `*DistributionConfig` classes.
   - Each component table's fleet rows give each drawable field a kind: number, count, choice or setting.
   - The fleet parser derives recognised keys and kinds from the tables.
   - The generator draws in the table's order and builds each component from the drawn non-null values plus its settings, so an undrawn field takes its dataclass default. The five classes, the restated defaults, the `None` fallbacks, `all_specs` and the inline per-field type decisions all go.
5. **ε. Invariants at read time.** A frozen `FleetDistributionConfig.__post_init__` checks every per-field invariant, naming the path:
     - the spec type is drawable for the field's kind;
     - a choice value is in the vocabulary;
     - a number field's value is not a string;
     - a `proportional_to` source is a field drawn earlier for every home that draws the dependent;
     - a field is required by its block;
     - pools hold n_homes values (297's rule, kept).

## 5. Contract (seam owned: the component block key tables shared by config's parsers, `scenario_writer` and the fleet grammar)

Names are final. S5's partition gives the modules their final homes:

- `ComponentBlock`, the tables and `FleetField` are written into `config.py` and move with the block readers to `scenario_blocks.py`.
- `ComponentDistribution`, the kind rules and the sampler move to `fleet_distribution.py`.
- `scenario_writer` imports the tables from `config.py` until S5's partition, and from `scenario_blocks.py` after it, so it never depends on config's loaders once the partition lands.

### 5.1 Tables

```python
class FieldKind(Enum):
    NUMBER = "number"    # a float; fixed, null, weighted_discrete, normal, uniform, shuffled_pool, proportional_to
    COUNT = "count"      # a whole number: drawn as NUMBER, then the sampler's one count conversion (int() today; 395 / S4 ζ round)
    CHOICE = "choice"    # one of FleetField.choices: a fixed string, null, weighted_discrete or shuffled_pool over them
    SETTING = "setting"  # not drawn: one value, as written (bool, str or a sub-block), given to every home

@dataclass(frozen=True)
class FleetField:
    kind: FieldKind
    choices: tuple[str, ...] = ()        # CHOICE only, e.g. heat_pump.HEAT_PUMP_TYPES, ev.CHARGER_TYPES
    required: bool = False               # the fleet block must give it (pv.capacity_kw, battery.capacity_kwh, ev.charger_type)

@dataclass(frozen=True)
class SubBlock:
    read: Callable[[object, str], object]           # (value, block_path) -> config or None: S2's readers
    write: Callable[[object], Optional[dict[str, Any]]]

@dataclass(frozen=True)
class ComponentBlock(Generic[_Built]):
    config_type: type[_Built]
    keys: tuple[str, ...]                           # the block's keys == the config fields it carries, in field order
    outside_grammar: Mapping[str, str]              # config field -> why no key carries it
    sub_blocks: Mapping[str, SubBlock]              # keys whose value is a nested block (battery only)
    when_omitted: Mapping[str, Any]                 # parser policy for an absent key, e.g. {"capacity_kw": 4.0}
    fleet: Mapping[str, FleetField]                 # fleet-block keys in draw order; a subset of keys
    not_in_fleet: Mapping[str, str]                 # key -> why the fleet grammar does not carry it (name, seed)
    presence: Optional[str] = None                  # the fleet field whose null (battery: also 0) sample means "no such component"

PV_BLOCK: ComponentBlock[PVConfig]
BATTERY_BLOCK: ComponentBlock[BatteryConfig]
LOAD_BLOCK: ComponentBlock[LoadConfig]
HEAT_PUMP_BLOCK: ComponentBlock[HeatPumpConfig]
EV_BLOCK: ComponentBlock[EVConfig]
LOCATION_BLOCK: ComponentBlock[Location]           # fleet = {}; when_omitted = Bristol's coordinates, timezone, altitude
```

Invariants:

- **T1 Coverage.** For each table, `{f.name for f in fields(config_type)} == set(keys) | set(outside_grammar)`, and the two sets are disjoint. `set(fleet) | set(not_in_fleet) == set(keys)`, also disjoint. `keys` follows field order. A new dataclass field fails T1 until its author places it.
- **T2 Rows at `ac1fdf1`.**
  - **PV.** All thirteen `PVConfig` fields are keys except `custom_module_params` and `custom_inverter_params`, which have no YAML form. That includes `system_losses`. The fleet rows are NUMBER, with `capacity_kw` required. `name` is not in the fleet grammar.
  - **Battery.** Every field is a key. `dispatch_strategy` and `grid_charging` are sub-blocks, read and written by S2's grammar (S2 PRD §5.5), and are SETTING in the fleet. `capacity_kwh` is the required presence field. The other numbers are NUMBER. `name` is not in the fleet grammar.
  - **Load.** `annual_consumption_kwh` is NUMBER, `household_occupants` COUNT and `use_stochastic` SETTING. `name` and `seed` are not in the fleet grammar: the generator gives each home `fleet seed + index`.
  - **Heat pump.** `heat_pump_type` is CHOICE over `HEAT_PUMP_TYPES` and is the presence field. It is not required: a block without it gives no heat pump, as today. The two numbers are NUMBER.
  - **EV.** `charger_type` is CHOICE over `CHARGER_TYPES` and is the required presence field. The hours are COUNT, `required_charge_kwh` is NUMBER and `smart_charging_mode` is SETTING.
- **T3 Draw order.**
  - The per-home draw order is pv, battery, load, heat_pump, ev. Within a component it follows the `fleet` mapping's order, which is field order.
  - The default-mode shuffle order is the explicit `_DEFAULT_SHUFFLE_ORDER = (pv, load, battery, heat_pump, ev)`. It is today's `all_specs` order with `heat_pump_type` added first in its component.
  - The legacy order is `_BRISTOL_LEGACY_ORDER`: pre-sample `load.annual_consumption_kwh`, then shuffle `pv.capacity_kw`, `battery.capacity_kwh`, `heat_pump.heat_pump_type` and `ev.charger_type`, then every other pool in the default order.
  - Both orders are tested data. They are not simplified away (briefing: reproducibility).
  - A component whose presence field draws null is not drawn further for that home.

### 5.2 Readers and writer

- **R1.** A home-block reader:
  1. refuses keys outside `keys` (today's `_refuse_unrecognised_keys`, recognised set from the table);
  2. drops null-valued keys;
  3. refuses an absent field that has no dataclass default and no `when_omitted` entry, naming `<block_path>.<key>`;
  4. reads sub-blocks through `sub_blocks[k].read`;
  5. builds `config_type(**when_omitted | present)` with the values as written.

  A null *block* keeps its meaning: no battery, heat pump or EV. The heat-pump block's required key becomes `heat_pump_type` alone, and the EV block's `charger_type` alone.
- **R2.** `scenario_writer` writes `{k: getattr(cfg, k) for k in keys}`, with sub-blocks through `write` and `None` written as null. It raises `ValueError` naming every `outside_grammar` field whose value differs from that field's dataclass default. The battery block keeps one stated exception until S28 retires `efficiency`: when `efficiency` is set, the derived per-direction pair is not written.
- **R3.** A file the writer wrote reads back, through `load_home_config`, `load_scenarios` or `load_fleet_config`, as an equal config.

### 5.3 Fleet grammar

```python
SpecValue = Union[float, str, None]                 # WeightedDiscreteDistribution.values / ShuffledPoolDistribution.values
SettingValue = Union[bool, str, GridChargeConfig, DispatchStrategyConfig, None]

@dataclass(frozen=True)
class ComponentDistribution:
    draws: Mapping[str, DistributionSpec]            # fleet key -> spec, only the keys the block gives
    settings: Mapping[str, SettingValue] = MappingProxyType({})

@dataclass(frozen=True)
class FleetDistributionConfig:                       # frozen; field names unchanged
    n_homes: int
    pv: ComponentDistribution
    load: ComponentDistribution = ComponentDistribution(MappingProxyType({}))
    battery: Optional[ComponentDistribution] = None
    heat_pump: Optional[ComponentDistribution] = None
    ev: Optional[ComponentDistribution] = None
    seed: Optional[int] = None
    random_order: str = "default"
    dispatch_strategy: Optional[str] = None          # S2 ε retires it
```

`FleetDistributionConfig.__post_init__` refuses with `ConfigurationError`, naming the path `fleet_distribution.<component>.<key>` and the offending values:

- **F1** a draws or settings key that is not in the table's `fleet`, or is in the wrong one of the two;
- **F2** a spec type that the field's kind does not accept;
- **F3** a CHOICE value outside `choices`, or a NUMBER or COUNT value that is a string;
- **F4** a `proportional_to` whose source is not a NUMBER or COUNT field drawn earlier for every home that draws the dependent. That means an earlier field of pv or load (always present) in draw order, or an earlier field of the same component;
- **F5** a missing `required` field;
- **F6** a pool whose counts do not sum to n_homes (297, kept).

The parser builds `ComponentDistribution` from a block by the table. It reads sub-block settings through the table's `sub_blocks`.

Generation:

- `generate_homes_from_distribution(config, location, *, fleet_tariff=None)` keeps its signature.
- Per home it draws each component's fields in T3 order through the path-keyed sampler. Drawn values are recorded in a context keyed by path, which serves F4's sources.
- It builds each component as `config_type(**{k: v for k, v in drawn.items() if v is not None} | settings)`. A COUNT is converted once.
- A refusal from the dataclass is re-raised naming `fleet_distribution.<component>` and the home's number.
- A required field drawn null (PV capacity) is refused naming its path.

### 5.4 Heat-pump record (α)

```python
HeatPumpType = Literal["ASHP", "GSHP"]

@dataclass(frozen=True)
class CopCurve:
    intercept: float     # COP at 0 °C
    slope: float         # per °C
    minimum: float
    maximum: float
    def cop(self, outdoor_temp_c: float) -> float: ...   # clamp(intercept + slope * t, minimum, maximum)

COP_CURVES: Mapping[HeatPumpType, CopCurve]           # ASHP (2.5, 0.1, 1.8, 4.5); GSHP (3.8, 0.02, 3.2, 4.8)
HEAT_PUMP_TYPES: tuple[HeatPumpType, ...] = get_args(HeatPumpType)

def calculate_cop(heat_pump_type: HeatPumpType, outdoor_temp_c: float) -> float: ...  # signature unchanged
```

- `calculate_cop`, `HeatPumpConfig.__post_init__` and config's CHOICE check refuse a type outside `HEAT_PUMP_TYPES` with a message listing it.
- A test pins `set(COP_CURVES) == set(HEAT_PUMP_TYPES)`.
- No public name changes. `HeatPumpConfig`'s frozen form changes only by β's added default.

## 6. Resolved design decisions

1. **The dataclass is the one statement of a component's fields and defaults.** The grammar declares, per component, only what it adds: key placement, the fields without a YAML form (with reasons), sub-blocks, the parser's when-omitted values, and fleet kinds. T1 keeps that declaration honest. The tables live in config's grammar, not beside the dataclasses, because the YAML grammar is config's concern (heuristic 6). `pv.py` and the other domain modules stay free of grammar.
2. **Build from the drawn values, not `replace` over a default instance.** The program row says "`dataclasses.replace` over a default instance". `PVConfig`, `BatteryConfig`, `HeatPumpConfig` and `EVConfig` each have a required field, so no default instance exists. `config_type(**drawn_non_null | settings)` gives the same rule: an undrawn or null field takes the dataclass default. `dataclasses.replace` stays the tool for edits of an existing config (S26's knobs).
3. **Defaults move onto the dataclasses where only the distribution layer had one.** `HeatPumpConfig.thermal_capacity_kw = 8.0` matches `default_ashp`'s value. `EVConfig.arrival_hour = 18` is the fleet grammar's commuter arrival. Both are additive frozen-form edits that land in-leaf under D29, with their `FROZEN_CLOSURE` entries and an Unreleased line. The home grammar widens to match the fleet grammar, rather than the fleet grammar narrowing, so no shipped file stops loading.
4. **A null key is absent** in every component block, and also in the fleet grammar, where a null spec already meant "not drawn". This matches S17's web presence rule and S2's sub-grammar (a null key another variant reads is absent). The writer's "null reads back as the default or None" becomes true. A null *block* still means no component.
5. **One writer rule for every block.** Every key is written, and an unset Optional is written as null. Exported files stay self-describing, and the rule matches the module docstring. The set of fields with no YAML form is computed, not a hand-kept deny-list. S14's 825 says "writes a key only when it is set" for its two Optional fields. That gives way to this rule; 825's round-trip assertion is config equality (cross-reference; lead question 2).
6. **One generic `ComponentDistribution` instead of five field-listing classes.** Typed field-per-class distribution configs would restate every field list a fourth time. The distribution configs are not on the frozen surface: no `__all__` name or `FROZEN_CLOSURE` form names them (measured). Their 89 constructions in tests are mechanical rewrites. `settings` is typed by `SettingValue`, never `Any`, per the briefing's "no Any-typed config fields".
7. **Factoring the spec-type × field axis.**
   - field → kind is S7's table;
   - kind → accepted spec types is S7's rule (F2);
   - spec type → parse, draw and serialise is the per-type table D18 gives S18, in `fleet_distribution.py`.

   Stateless spec types (`WeightedDiscreteDistribution`, `NormalDistribution`, `UniformDistribution`) each implement `draw(rng)`. The pool and `proportional_to` keep per-path state in the sampler. Categorical values are `SpecValue`, so the `type: ignore`, the `cast` and the `str()` go. Numbers in a NUMBER or COUNT field's spec are read at F3, which is the per-kind site S4 decision 6 needs. A spec type never reads its outcome values as numbers.
8. **Reproducibility is pinned, not argued.**
   - γ commits golden fixtures captured on its base before any change. Each holds, per home, the drawn fleet fields and presence of a shipped fleet (§3.2) or of a probe fleet: conditional battery draws, a weighted heat-pump type, EV pools and normals, legacy pre-sampling, and `proportional_to` battery.
   - Every later leaf keeps them equal. Only a change that means to move generated fleets regenerates them, and it says so in an Unreleased line. That covers S4 ζ's EV-hour rounding and task 395's occupants rounding.
   - The pins compare drawn fields only, so a default change elsewhere (S14's `module_efficiency=None`) does not move them.
   - Identity holds because the RNG call sequence is unchanged for every fleet that generates today:
     - the per-home draw order and the default and legacy shuffle orders are kept as data (T3);
     - an absent field draws nothing, exactly as today's scalar default specs drew nothing;
     - the new fleet fields are absent from existing files.
   - Exceptions are only fleets that fail or misgenerate today: P3, P4, P6, P7, P8 and P13. P12 (0 occupants) is now refused by `LoadConfig`, named. 297 already refuses P5 and P9.
9. **Count conversion is one site and is not decided here.** COUNT uses the sampler's count conversion: `int()` at `ac1fdf1`, or 395's `sample_count` if 395 has landed. S4 ζ moves EV hours onto it. δ deletes only the `if x else 3` truthiness default, so a null draw takes `LoadConfig`'s 3 and a 0 is `LoadConfig`'s refusal.
10. **297 is kept, and γ depends on it.** Its exact-count rule (counts == n_homes) and its two check sites match F6 and the type's own contract ("must sum to n_homes"). An oversized pool is refused (lead question 1). The sampler's pool guard is the redundant second enforcement heuristic 10 asks for. It is not the primary refusal.
11. **The web's deterministic load default stays a web policy.** `simulation_params._HOME_CONFIG_DEFAULTS["stochastic"] = False` agrees with `home.html`'s `stochastic: false`, so an interactive run is deterministic by default. `LoadConfig.use_stochastic` stays True for the library and YAML. S17 names the web default as such when it applies its presence rule (cross-reference). That module's PV, heat-pump and type literals are S17's to derive from the dataclasses once β lands.

## 7. Boundary-test sketch (both sides of the seam)

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| A1 | heat-pump model | the record reproduces the curves | §3.3 temperatures | `calculate_cop` equals §3.3's values within 1e-12; `HeatPumpConfig("XSHP", 8.0)` and `calculate_cop("XSHP", 0)` raise naming both valid types | α |
| A2 | vocabulary | one vocabulary | — | `set(get_args(HeatPumpType)) == set(COP_CURVES) == set(HEAT_PUMP_TYPES)`; no `ASHP_COP_`/`GSHP_COP_` name and no `'ASHP'`/`'GSHP'` literal in `config.py` | α |
| B1 | grammar → user | `system_losses` from YAML | P1 | `home run` on the file simulates with `pv_config.system_losses == 0.05` (today refused) | β |
| B2 | writer ↔ reader | round-trip of every grammar field | a home setting every key of every table to a non-default value, `system_losses=0.05` included | `home_scenario` → `scenario_yaml` → file → `load_scenarios` gives an equal `HomeConfig` (today `system_losses` reads back 0.14076); the same for `fleet_scenario` → `load_fleet_config` | β |
| B3 | writer | a field with no YAML form | `custom_module_params` or `custom_inverter_params` set | `ValueError` naming it; the named set is `outside_grammar`'s, computed | β |
| B4 | grammar | blocks may leave out what the dataclass defaults | P10, P11; `pv: {tilt: null}`; `heat_pump: {…, annual_heat_demand_kwh: null}` | an 8 kW heat pump; an 18:00 EV; tilt 35.0; demand 8000.0 (today: two refusals and two raw `TypeError`s) | β |
| B5 | coverage | T1 for each table | — | parametrised over the six tables; a dataclass field added in a test double fails it | β |
| C1 | sampler | the legacy pool | P6 | 4 homes whose tilts are a permutation of [30, 30, 40, 40] (today `KeyError`) | γ |
| C2 | sampler | a shared spec object | P7, and P7's legacy normal shared by `load.annual_consumption_kwh` and `pv.tilt` | each field gets its own exact counts / its own draws (today `IndexError`) | γ |
| C3 | reproducibility | pins | the six §3.2 files and the probe set | generated drawn fields equal the goldens captured on γ's base | γ, and every later leaf |
| D1 | grammar → user | heat-pump pools drawn | P3 | 5 of 10 homes have an ASHP (today 0) | δ |
| D2 | grammar → user | refusals at read time | P4, P8 with a source that is not earlier, P13, a `normal` spec on `heat_pump_type`, a string in `pv.tilt`'s weighted values | `validate config` exits 1 naming `fleet_distribution.<component>.<key>` and the rule; nothing generates. P8 with source `pv.capacity_kw` generates tilt = 5 × capacity (today "Unknown distribution type") | ε |
| D3 | grammar | the fleet grammar widens to every numeric key | P14 | accepted; drawn values reach `PVConfig.temperature_coefficient` and `BatteryConfig.min_soc_fraction` | δ |
| D4 | defaults | undrawn fields take the dataclass default | a fleet giving only `pv.capacity_kw`, `battery.capacity_kwh` and `ev.charger_type` | every other field equals its dataclass default (a `dataclasses.fields` walk, no literals in the test) | δ |
| D5 | web | the dashboard path | `POST /api/fleet/import-yaml` with P4's and P13's fleet documents (`fleet_scenario._refuse_what_the_loaders_refuse` runs `parse_fleet_distribution_config`) | HTTP 400, the error naming `fleet_distribution.battery.capacity_kwh` and `pv.capacity`, and `fleet_distribution.heat_pump.heat_pump_type` and `XSHP` (today the parse step accepts both: P4, P13) | ε |
| D6 | reproducibility | pins after the reshape | C3's set | still equal | δ, ε |

## 8. Pre-conditions for activating

- **Task 297** lands before γ (pool counts == n_homes, refused at construction). If the contract §8 step 1 lookup at decompose finds it cancelled, γ absorbs its plan (`.worktrees/.task-meta/297/plan.json`).
- No other substrate is missing. Every capability §5 relies on exists at `ac1fdf1`:
  - `dataclasses.fields` and `MISSING`;
  - `typing.get_args` on a `Literal` (probe: `('ASHP', 'GSHP')`);
  - `MappingProxyType`;
  - `_refuse_unrecognised_keys`;
  - `has_battery` and `require_valid_capacity_setting`;
  - `parse_dispatch_strategy_config` and `_parse_grid_charge_config`;
  - `load_home_config`, `load_scenarios`, `load_fleet_config` and `parse_sweep_fleet_configs`.
- `scenario_writer` may import config's grammar. Only `web/{api,builder_form,fleet_scenario}.py` import `scenario_writer`, and config imports none of them, so no cycle forms.

## 9. Cross-PRD relationship

| Other stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S5 scenario grammar | consumes, moves | S5's partition moves the §5.1 tables with the block readers to `scenario_blocks.py`, and `ComponentDistribution`, the kind rules and the sampler to `fleet_distribution.py`; `scenario_writer` then imports `scenario_blocks`. S5 deletes `_modify_pv_config`, `_modify_battery_config` and `_modify_load_config` with the sweep, which closes the sweep halves of fk-d2b4045c6676 and fk-148991ab9439 | S7 (tables), S5 (layout, sweep deletion) | no edge; file locks serialise, and whichever lands second rebases by symbol |
| S2 dispatch configuration | consumes | the battery table's `dispatch_strategy`/`grid_charging` sub-blocks are S2's grammar (S2 PRD §5.5 and its seam row) | S2 (sub-grammar), S7 (table) | concurrent with 786; file overlap |
| S4 finite quantities | shares | S4 ε's `_constructed` wraps R1's construction (null keys dropped first, values as written); S4 ζ reads NUMBER/COUNT spec values at F3's per-kind site (S4 decision 6); S4 ζ's EV-hour rounding is the COUNT conversion and regenerates C3's goldens with its Unreleased line | S4 (checker, rounding), S7 (kinds, pins) | no edge (S4's own row: "file locks serialize") |
| S14 PV model | shares | 825 makes `module_efficiency`/`temperature_coefficient` Optional; once β/δ land, its `config.py` bullets (`PVDistributionConfig` default, `else 0.20`, null pass-through) are already delivered, and its writer bullet follows decision 5 | S14 (fields), S7 (derivation) | parallel; file overlap |
| S28 battery facts | consumes | retiring `BatteryConfig.efficiency` (held leaf) edits the battery row and deletes R2's efficiency exception in the same change; T1 enforces it | S28 | — |
| S18 dashboard editing | consumes | D18's per-type table reads F2's kind → spec types and the tables' fleet rows for the editor's per-component fields; the preview samples through γ's sampler; the heat-pump and EV option lists render from `HEAT_PUMP_TYPES` (α) and `CHARGER_TYPES` (δ) | S18 | wave 3, after S5 |
| S17 web request boundary | consumes | `_parse_heat_pump_block` and `_HOME_CONFIG_DEFAULTS`' PV entries defer to the dataclass defaults; `stochastic: False` is named as the web's policy (decision 11) | S17 | after β |
| S26 sweep knob registry | consumes | after δ, `detect_sweep_spec`/`_replace_sweep_with_value` read `config.battery.draws["capacity_kwh"]`; δ edits them mechanically and S26 replaces them | S26 | — |
| S12 load composition | consumes | a `LoadConfig` field change edits the load row (T1) | S12 | — |
| S29 surface bump | consumes | release section lists β's two additive defaults and the widened grammars | S29 | — |
| task 395 | upstream of δ's COUNT site | `sample_count` | 395 | kept; no edge (decision 9) |

## 10. Decomposition plan

Labels are the sidecar's. Every leaf carries:

- `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`;
- the `x_finding_key` list below;
- priority equal to the highest severity among its keys.

β, δ and ε are high, so all three join the trigger-chain gate (772) once it exists.

- **α. Heat-pump types as one per-type record.**
  - **Files:** `heat_pump.py`, `config.py` (the generator's type tuple, message and `cast`; the heat-pump distribution docstring), `tests/unit/test_heat_pump.py`, `tests/unit/config/test_generate_homes.py`.
  - **Changes:** §5.4. Deletes the eight `*_COP_*` constants, `valid_types` and `calculate_cop`'s if/elif. The tests read `COP_CURVES`.
  - **Signal:** A1, A2. `home run` on a heat-pump scenario gives the same heat-pump load as before (the existing `test_home_heat_pump` figures).
  - **Prereqs:** none. **Unlocks:** δ (the CHOICE vocabulary).
  - **Key:** fk-d6f16d95b126. **Priority:** low.
- **β. Component block tables shared by the home-block readers and `scenario_writer`** (supersedes 599; 283's home half).
  - **Files:** `config.py` (§5.1 tables; `parse_location_block`, `_parse_pv_config`, `_parse_battery_config`, `_parse_load_config`, `_parse_heat_pump_config` and `_parse_ev_config` per R1; the six `_*_BLOCK_KEYS` sets replaced), `scenario_writer.py` (R2; module docstring), `heat_pump.py` (`thermal_capacity_kw = 8.0`; `default_ashp`/`default_gshp` from the field defaults), `ev.py` (`arrival_hour = 18`), `tests/unit/test_scenario_writer.py` (`_every_grammar_field_home` built from the tables), new `tests/unit/config/test_component_blocks.py` (T1, T2), `tests/unit/config/test_home_block.py`, `tests/unit/config/test_unrecognised_keys.py`, `tests/unit/test_public_api_surface.py` (the two `FROZEN_CLOSURE` forms), `docs/domain-library-consumption.md` (Unreleased: `system_losses` is a `pv:` key; the two defaults; null keys read as absent), `docs/pv-system-losses.md` (the YAML key), `CLAUDE.md` (the `scenario_writer.py` line: both read the component tables, no "change both together").
  - **Signal:** B1–B5.
  - **Prereqs:** none. **Unlocks:** δ.
  - **Keys:** fk-2b16cc8bcf46, fk-d2b4045c6676, fk-148991ab9439, fk-dfeefbe95640. **Priority:** high.
- **γ. Sampler state per field path; every pool shuffled in either order; reproducibility pins** (supersedes 662; 403's defect 1).
  - **Files:** `config.py` (`_DistributionSampler` keyed by path; `draw(rng)` on the three stateless spec types replacing `_sample_from_distribution`'s chain; the legacy branch prepares every pool after its four), new `tests/unit/config/test_fleet_generation_pins.py` and `tests/fixtures/fleet_generation/*.json` captured on the leaf's base before any edit, with a regeneration entry point named in the failure message, `tests/unit/config/test_generate_homes.py`, `review/briefing.yaml` (the reproducibility rule points at the pin test).
  - **Signal:** C1–C3. The sampler's pool guard raises `ConfigurationError` naming the path if a pool runs dry (unreachable after 297; a unit test drives it directly).
  - **Prereqs:** 297. **Unlocks:** δ.
  - **Key:** fk-f2e1ad46df4b. **Priority:** medium.
- **δ. The fleet grammar from the component tables** (supersedes 600; 403's defect 2; 283's fleet half).
  - **Files:** `config.py` (`ComponentDistribution`, `FieldKind`, `FleetField`, the tables' `fleet` rows, the fleet block parsers derived from the tables, `generate_homes_from_distribution` per §5.3, `SpecValue` on the two value-carrying spec types, `detect_sweep_spec`/`_replace_sweep_with_value` on `draws`; the five `*DistributionConfig` classes, their parsers' `data.get` defaults, the `None` fallbacks, `all_specs`, the inline per-field decisions and the `if x else 3` default deleted), `ev.py` (`CHARGER_TYPES` read by `__post_init__`), `tests/unit/config/{test_fleet_distribution_block,test_generate_homes,test_unrecognised_keys,test_fleet_file}.py` (the 89 constructions rewritten), `docs/domain-library-consumption.md` (Unreleased: the fleet grammar accepts every numeric component key and a bare string for a choice; `heat_pump_type` pools are drawn; a 0-occupant draw is refused).
  - **Signal:** D1, D3, D4, D6. A grep check finds no `x if x is not None else <default>` fallback and no `*DistributionConfig` class left.
  - **Prereqs:** α, β, γ. **Unlocks:** ε.
  - **Keys:** fk-0e58e2a7e007, fk-148991ab9439, fk-dfeefbe95640. **Priority:** high.
- **ε. The fleet invariants at read time.**
  - **Files:** `config.py` (frozen `FleetDistributionConfig.__post_init__` with F1–F5 beside 297's F6; the generator's dataclass refusals re-raised with the path and home number), `tests/unit/config/{test_fleet_distribution_block,test_generate_homes}.py`, `tests/unit/test_cli.py` or `tests/unit/cli/` (`validate config`), `tests/unit/web_api/test_fleet_yaml.py` (D5), `tests/unit/test_web_scenarios.py`, `docs/domain-library-consumption.md` (Unreleased: the refusals move to read time).
  - **Signal:** D2, D5, D6.
  - **Prereqs:** δ. **Unlocks:** S18's editor and preview, and S26's battery-capacity knob (cross-reference).
  - **Keys:** fk-0e58e2a7e007, fk-f2e1ad46df4b. **Priority:** high.

DAG: 297 → γ → δ → ε; α → δ; β → δ. α and β are independent of each other and of γ. fk-148991ab9439 and fk-d2b4045c6676 close when their S7 leaves and S5's sweep-deletion leaf have landed. fk-f2e1ad46df4b closes with 297, γ and ε. fk-0e58e2a7e007 closes with δ and ε.

**G7.** Advisory: this repo has no `docs/legibility/design-invariants.md`, so the dark-factory trigger shapes were walked instead.

- **`no-silent-fail-soft`.** δ and ε delete three silent outcomes: 0 heat pumps from a pool, 0 batteries from a misspelt source, and 0 occupants read as 3. 297 deletes the silently truncated oversized pool. γ turns two crashes into generated fleets. No new fallback is added. A null key reading as absent (decision 4) is a stated grammar rule with its own test (B4), not a hidden default.
- **`one-fact-one-home` / `no-lockstep-duplication`.** Defaults live on the dataclasses. Field placement lives in one table per component, read by the parser, the writer and the fleet grammar, and T1 ties the table to the dataclass. The heat-pump vocabulary is the Literal, its curves one record each. The two shuffle orders are deliberate data that the briefing requires, tested against the table (T3). They are not duplication.
- **`guards-exercise-behaviour`.** T1 runs over the real dataclasses. C3 and D6 run the real generator over the shipped files. Every grep check has a behaviour twin in §7.
- **`exceptions-owned-or-ratified`.** R2's battery-efficiency exception is owned by S28's retirement of `efficiency` (cross-reference).

No waivers.

## 11. Out of scope

- The parameter sweep (`run_parameter_sweep`, `_modify_*`, `_apply_parameter_to_home`) and tasks 237 and 320: S5 deletes them.
- The web request readers' defaults (`simulation_params`): S17, by cross-reference.
- The distribution editor, its per-type table, the preview sampler and the form's option lists: S18 (D18).
- Rounding sampled counts: task 395 and S4 ζ.
- The home-level and fleet-level `dispatch_strategy` string: S2 ε.
- `EVConfig._parse_charger_power`, which parses `"7kW"` into 7.0 from the string. It is a heuristic-12 candidate for the next run. `CHARGER_TYPES` names the vocabulary only.
- The scenario-level blocks (tariff, seg, finance, period): S6 and S11.

## 12. Open questions (for the lead)

1. **Exact pool counts.** 297's plan and F6 refuse a pool whose counts exceed n_homes; today it is truncated silently (P9). The dashboard fleet form then refuses a user who lowers n_homes below the default pools' 100, naming the pool and n_homes. **Suggested:** exact, as planned, matching `ShuffledPoolDistribution`'s own contract. The alternative, "at least n_homes", keeps the form lenient but leaves the exact-count promise false.
2. **The writer's rule for an unset Optional.** Decision 5 (every key, null when unset) conflicts with 825's "writes a key only when it is set". **Suggested:** decision 5, applied to 825 by cross-reference (its B6 round-trip asserts config equality). Either rule keeps the system coherent if it is the only one.
