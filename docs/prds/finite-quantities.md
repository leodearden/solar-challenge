# PRD — Finite quantities: one checker in every input type's `__post_init__`

- **Program:** review-all-solar_challenge-20261013, stream **S4** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 2, upstream S1, size L, risk medium.
- **Finding keys:** fk-a9c609ecb8ef (high), fk-649851e5fc38 (high), fk-60410de6dd0a (high), fk-b69968a37b36 (medium), fk-e79170280adf (medium), fk-239274130a5a (medium, weakened; re-measured in §2.3), fk-a2b33a420bcf (medium), fk-7dcdc5559d22 (low), fk-5827f41eb082 (low), fk-f2f8a5512feb (low, D26), fk-606a9211b34d (low, D26).
- **Binding rulings:** D9 (the shared checker raises `ConfigurationError` from every domain `__post_init__`; config's readers add the key path on the way up), D26 (fk-f2f8a5512feb and fk-606a9211b34d are S4's), D29 (additive and behavioural surface edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line; only renames and retirements wait for S29), D27 (invariant 1 is promoted; S4 owns its test), L1 (S4 also converts the non-numeric `ValueError` refusals of the input types, and invariant 1's test asserts the type), L2 (S1 ships the bare type; S4 extends it only if a reader needs the path as data).
- **Session rulings (Leo, this session, 2026-10-15):** R1 the key path is added by wrapping construction, not by pre-reading every number; R2 an input type stores the value it read; R3 both `SummaryStatistics` and `EnergyFlowResult` are frozen, paying the measured per-step cost.
- **Status:** authored 2026-10-15 by an author-only /prd session; not committed.
- **Approach:** B + H. The seam (the number rule and its refusal) is read by every input type in 14 modules, by config's grammar, by the web readers and by six other streams, so it gets a contract (§5) and two-way boundary tests (§6).
- **Code anchors** verified against main `962552956508` (2026-10-15). Main moves fast — cite-by-symbol; re-locate lines at implementation time. `config.py` is unchanged since the review's pin `7dfea36e`; `dispatch.py`, `flow.py`, `home.py`, `battery.py`, `load.py`, `seg.py` and the web readers have moved, and every anchor below was re-read at `962552956508`.

## 1. Goal

One rule decides what a valid number setting is: a finite number, never a bool, a whole number where a count is meant, and inside the field's interval. It lives in one leaf module, `solar_challenge.number_fields`, moved down from `web/`. Every input type reads its own numeric fields through it in `__post_init__`, naming the field. Config's readers stop coercing numbers and instead add the block path to whatever the constructor refuses. The web stops pre-reading numbers ahead of config.

What a user observes:

1. **A bad number in a scenario is refused by name, with its path.** `solar-challenge validate config` reports an ERROR row naming the key path and the value, and exits 1. Today these files are accepted ("Configuration is valid", exit 0): a home with `pv: {capacity_kw: true}`, `heat_pump: {thermal_capacity_kw: .nan}`, `ev: {arrival_hour: 18.9}`, or `location: {altitude: .nan, timezone: Europe/Londn}`; and `bristol-phase1-flex.yaml` with `event_hours: .inf`. A fleet with `n_homes: 2.7` is refused, where today it runs 2 homes. `pv: {azimuth: south}`, which today ends in a `TypeError` traceback, gets an ERROR row (all probed at `962552956508`, §2.2).
2. **A library consumer gets the same refusal without config.** `SEGTariff("x", nan)`, `TariffPeriod("00:00", "00:00", nan)`, `EVConfig("7kW", 17.5)`, `EVConfig("7kW", True)`, `HeatPumpConfig("ASHP", nan, nan)`, `Location(51, -2, altitude=nan)` and `PVConfig(capacity_kw=True)` each raise `ConfigurationError`, a `ValueError`, naming the field and the value. All of them construct today.
3. **One refusal type at both boundaries.** Every refusal of an input type is a `ConfigurationError`, numeric (D9) or not (L1). The CLI therefore prints `Configuration error:` for each one, and S17's web translator can answer 400 to that one type.
4. **The web form says what config says.** A fleet form whose `pv.capacity_kw` is `{type: normal, mena: 4, std: 1}` is refused, naming the unrecognised key `mena`; today it runs N(0, 1). `pv.tilt: {type: fixed, value: 30}` is accepted; today it is refused with "requires 'value'".
5. **Sampled hours are rounded, not truncated.** On `scenarios/bristol-with-evs.yaml` the 30 EV homes' mean arrival hour becomes 17.933 and their mean departure 7.200. Today they are 17.433 and 6.533 (fk-a2b33a420bcf).
6. **Results are values.** Assigning to a `SummaryStatistics` or `EnergyFlowResult` field raises `FrozenInstanceError`. `simulate_timestep(inf, 1.0, None)` raises naming `generation`; today it returns infinite generation and export.
7. **A guard keeps it so.** Invariant 1's test (§5.6) walks every numeric dataclass under `solar_challenge`. Every input type must refuse NaN, ±inf, `True` and a non-number in every numeric field with `ConfigurationError` naming the field and the value. Every other numeric dataclass must be classified with a reason. A new numeric dataclass that nobody classifies fails the per-task verify.

## 2. Background (measured at `962552956508`)

### 2.1 What exists

- `web/number_fields.py` holds the project's one reusable reader. It has four functions: `as_finite_float`, `as_finite_float_within`, `as_whole_number` and `as_whole_number_within`.
  - They refuse a bool, a value `float()` cannot read, a value that is not finite, and a fraction where a whole number is meant. Each refusal is a `ValueError` naming the field and `{value!r}`.
  - Their ranges are closed only (`low <= x <= high`).
  - Only the web imports them: `builder_form`, `fleet_config` and `simulation_params`.
- `whole_numbers.whole_number` (`Optional[int]`, None for a bool, a non-finite value or a fraction) is the rule layer under `as_whole_number`. `load.LoadConfig`, `finance.FinanceConfig` and `finance.YearPoint` also call it.
- The domain guards come in three polarities (fk-a9c609ecb8ef). An AST census of raising constructors (`__post_init__`/`__init__`) finds:
  - NaN-permissive `x < 0` / `x <= 0` in `SEGTariff`, `TariffPeriod`, `HeatPumpConfig`, `EVConfig`, `Location` (`altitude < -500`), `GridServicesRateBand`, `EventWindow`, `GridServicesEventsConfig`, `FlexibilityValueBand`, the distribution types, `SweepSpec`, `FleetDistributionConfig`, `config.DispatchStrategyConfig`, `DispatchDecision` and `PeakShavingStrategy.__init__`.
  - NaN-refusing but inf-accepting `not x >= 0` in `EnergyFlowResult` and `battery._require_valid_request`.
  - Fully finite `not 0 < x < math.inf` in `BatteryConfig`, `PVConfig`, `LoadConfig`, `FinanceConfig`, `ConfigPoint` and `battery.require_valid_power_limit` / `require_valid_capacity_setting` (tasks 332, 374, 378, 633).
- Raise types: input types raise `ValueError` (battery, pv, load, heat_pump, ev, location, seg, tariff, flex, community, fleet, `GridServicesRateBand`), or `ConfigurationError` (config's grammar types, `FinanceConfig`, `EventWindow`, `GridServicesEventsConfig`).
- `config.py` coerces numbers in three styles (fk-649851e5fc38):
  1. **Raw splat** into the constructor: `_parse_pv_config`, `_parse_battery_config`, `_parse_load_config`, `_parse_grid_charge_config`, `parse_location_block`.
  2. **Inline `float()`/`int()`**: `_parse_heat_pump_config`, `_parse_ev_config`, `_build_*_spec`, `_parse_proportional_to_multiplier`, `parse_fleet_distribution_config` (`int(data["n_homes"])`), `_parse_event_windows`, `_parse_seg_rate_scalar`, `_parse_community_billing_config`.
  3. **Coercion tables** over `_number`/`_number_or_none`: `_FINANCE_SCALAR_COERCIONS` and `_GRID_SERVICES_EVENTS_SCALAR_COERCIONS`, whose refusal reads "finance block contains a non-numeric value: …", naming no key.
- `_parse_distribution_spec` takes a scalar with `isinstance(data, (int, float))`, so `True` passes as 1.0 (task 521).
- `generate_homes_from_distribution` truncates sampled EV hours with `int()`. Occupants are task 395's, in merge.
- The web compensates for config's coercions:
  - `fleet_config._build_distribution_dict` rebuilds each distribution, reading every number through `as_finite_float`. Its `_spec_number` invents defaults that config's grammar would refuse (mean 0, std 1, uniform 0..1, weight 1, count 1). The rebuild drops keys and types it does not know.
  - `fleet_scenario._read_fleet_size_and_seed` reads `n_homes` and `seed` "ahead of the loaders, whose int() would refuse n_homes first, naming no setting".
  - `simulation_params.parse_home_config` pre-reads `azimuth`, `tilt`, `system_age_years` and `degradation_rate_per_year`. These are `PVConfig`'s own field names, and a comment says PVConfig is the single source of truth for their bounds.
  - `api.simulate_sweep` reads `min`, `max` and `steps` with bare `float()`/`int()`.
  - `assistant`'s fleet tool reads `n_homes` with `int()`.
- `SummaryStatistics` (in `__all__`) and `EnergyFlowResult` (in `__all__`) are the two non-frozen result dataclasses fk-f2f8a5512feb names. Nothing in src or tests assigns to their fields (grep). The frozen contract pins each class's `frozen` parameter (task 567), so freezing either one edits `FROZEN_SURFACE`.

### 2.2 Probes (RED today)

| Probe at `962552956508` | Today |
|---|---|
| `validate config` on a home with `pv: {capacity_kw: true}` | OK, exit 0 |
| … `pv: {capacity_kw: 4.0, azimuth: south}` | `TypeError: '<=' not supported between instances of 'int' and 'str'` traceback, exit 1 |
| … `heat_pump: {heat_pump_type: ASHP, thermal_capacity_kw: .nan}` | OK, exit 0 |
| … `ev: {charger_type: 7kW, arrival_hour: 18.9}` | OK, exit 0 (runs 18) |
| … `location: {…, altitude: .nan, timezone: Europe/Londn}` | OK, exit 0 |
| … fleet with `n_homes: 2.7` and a normal capacity with mean `.nan` | ERROR `Capacity must be positive and finite, got nan kW`, with no path; `n_homes` silently truncated |
| … `bristol-phase1-flex.yaml` with `event_hours: .inf` | OK, exit 0 |
| `SEGTariff("x", nan)`, `SEGTariff("x", inf)`, `TariffPeriod("00:00","00:00",nan)`, `EVConfig("7kW",17.5)`, `EVConfig("7kW",True)`, `HeatPumpConfig("ASHP",nan,nan)`, `Location(51,-2,altitude=nan)`, `Location(51,-2,timezone="Europe/Londn")`, `PVConfig(capacity_kw=True)` | all construct |
| `PVConfig(capacity_kw="4")` | `TypeError` |
| `simulate_timestep(inf, 1.0, None)` | returns `generation=inf`, `grid_export=inf` |
| `form_to_fleet_distribution_config` with `pv.capacity_kw: {type: normal, mena: 4, std: 1}` | becomes `{type: normal, mean: 0.0, std: 1.0}` |
| … with `pv.tilt: {type: fixed, value: 30}` | cut to `{type: fixed}`, then config refuses it with "requires 'value'" |
| EV hours on `bristol-with-evs.yaml` (30 EV homes) | mean arrival 17.433, mean departure 6.533, 15 of 30 depart at 06:00; raw draws average 17.945 / 7.090; Python `round()` of the same draws gives 17.933 / 7.200 |
| Frozen 9-float dataclass vs plain (microbenchmark, CPython 3.12.3) | +1.3 to 1.6 µs per construction; `simulate_timestep` costs 8.2 µs per step with a battery and 2.9 µs without. Whole-run timing was unreliable at load average 332 |

### 2.3 D28 re-measure of fk-239274130a5a (weakened)

| Claim | Finding | `962552956508` |
|---|---|---|
| `except (ValueError, TypeError)` blocks in `web/api.py` | 5 | 5 |
| `simulate_fleet_api` passes `data.get("name", …)` unchecked | yes | yes |
| `simulate_sweep` reads `mode` with `str()` and treats any non-geometric value as linear | yes | yes |
| `parse_home_config` reads `stochastic` with `bool()` | yes | yes |
| `simulate_sweep` reads `min`/`max`/`steps` with bare `float()`/`int()` | yes | yes; `{"min": true}` reads as 1.0 |

The finding holds. S4 acts only on its number half (§4 decision 9).

## 3. How this PRD reads the rulings

1. **D9 and the synthesis row.** The row says the rule is enforced "at parse (key path) and at construction (field name), both through the one checker". D9 says "config's readers add the key path on the way up". R1 resolves the two:
   - Construction is the one place an input value is read.
   - The reader passes values as written. It adds its block path to whatever `ConfigurationError` the constructor raises.
   - The checker is called at parse only where nothing constructs the value at parse. That is a distribution's scalar arm and its `fixed` value, whose home is generated later.

   Heuristic 10's "redundantly" (construction *and use*) is met by construction plus the engine's at-use checks, which S3 routes through the same rule (§8). A parse-time pre-read of every number would add a third enforcement point and a second home for "which keys are numbers". The pre-read could derive that from type hints, but `typing.get_type_hints` fails today on `BatteryConfig` and `FinanceConfig` because of their `TYPE_CHECKING` imports.
2. **L2.** No reader needs the path as data. The block path is prepended to the message, `"<block path>: <constructor's message>"`. `errors.py` is not extended.
3. **L1.** Every `raise ValueError` in an input type's constructor becomes `ConfigurationError` in the leaf that converts that type, numeric or not. The input types are listed in §5.4. Computed results keep `ValueError`, per S1's C4.
4. **D26.** fk-f2f8a5512feb is θ's. fk-606a9211b34d is shared by β, γ, δ and ι.
5. **D29.** S4 renames and retires no public name, so no leaf is held for S29.
   - Raising `ConfigurationError` where `ValueError` was raised is compatible, since it is a subclass.
   - Refusing NaN, inf, bools and fractions that the 0.5.0 tag accepted is a behavioural tightening, and so is storing the read value.
   - Freezing the two result classes edits `FROZEN_SURFACE`'s `frozen` flag, like task 436's freeze of `SimulationResults`.

   Each leaf writes its own "Unreleased on main" line in `docs/domain-library-consumption.md`.
6. **The synthesis row's four names.** "Moves down unchanged in behaviour" is kept for every refusal the web sees. The two `_within` variants fold into an optional `within: Interval` parameter, because the domain needs open bounds such as (0, ∞), (0, 1] and (−1, 0), and a closed `low, high` pair cannot say them. The closed-range message keeps its wording ("between {low} and {high}").

## 4. Resolved design decisions

1. **The leaf is `solar_challenge/number_fields.py`, moved from `web/`.** It is not a new quantities module (synthesis). It imports `errors` and `whole_numbers` only; `whole_numbers` stays the Optional-returning rule for counts.
2. **Intervals are values.** A frozen `Interval(low, high, low_open, high_open)` has `admits(number)` and a `__str__` that phrases the bound ("greater than 0", "at least 0 and less than 1", "between 0 and 360").
   - Named intervals `POSITIVE`, `NON_NEGATIVE`, `FRACTION` and `UNIT_INTERVAL` replace the repeated idioms (heuristic 11).
   - The interval is the rule's one home, and every enforcement point calls it (heuristic 10, *uniformly*).
3. **Readers raise `ConfigurationError` (D9).** They name the field they are given and `{value!r}`.
4. **An input type reads and stores (R2).** `__post_init__` calls `read_field(self, "<field>", <reader>, <interval>)` once per numeric field.
   - That reads the value and stores what was read, so after construction a float field holds a Python `float` and an int field a Python `int`.
   - This extends the precedent of `LoadConfig.household_occupants`, `FinanceConfig`'s year counts and `YearPoint.year`.
   - Consequences: `PVConfig(capacity_kw=4)` holds `4.0`; numpy scalars become Python numbers; `"4"` is read as 4.0, as the web already reads it.
   - All numeric fields are read before any cross-field rule, so a NaN is refused by name before it can fall into another comparison.
5. **Config's readers construct through one wrap (R1).** `_constructed(block_path, cls, /, **values)` returns `cls(**values)`, or re-raises its `ConfigurationError` as `"<block label>: <message>"` from the original.
   - Readers pass values as written. `float()`, `int()`, `_number`, `_number_or_none`, `_float_or_none`, the two coercion tables, `_parse_event_windows`' `except (ValueError, TypeError, OverflowError)` and `_parse_seg_rate_scalar`'s private `isfinite` rule all go.
   - Arguments are built before the wrap is entered, so an inner reader's refusal is never prefixed twice.
6. **A distribution's outcome values are not read as numbers.** `weighted_discrete` and `shuffled_pool` values may be strings (`heat_pump_type`), so the generated home's type reads them.
   - A distribution's parameters are read by the distribution type: mean, std, min and max; weights; counts; multiplier and offset; and a sweep's min, max and steps.
   - The scalar arm and `fixed`'s `value` are read at parse with the parameter's path, because nothing constructs them there.
7. **Sampled whole-number fields are rounded once** by the sampler's count rounding (task 395's `sample_count`), not truncated by `int()`. EV hours join occupants. This changes the fleets that existing seeds generate; ζ's Unreleased line says so.
8. **Location refuses an unknown time zone** at construction, through `zoneinfo.ZoneInfo`. The message names `timezone` and the value (fk-7dcdc5559d22). `Europe/London`, `Europe/Paris`, `America/New_York` and `UTC`, every zone in src, tests and scenarios, resolve (probed).
9. **S4 is numbers.** The non-numeric web reads in fk-5827f41eb082 and the non-number half of fk-239274130a5a go elsewhere, so the leaf stays a number module and its name stays true (heuristic 1):
   - `stochastic` as a JSON boolean, `name` as a string, and `location`: task 517, which already carries fk-5827f41eb082.
   - Sweep `mode`: S26's `SweepSpec` routing.
   - `use_stochastic` in config: task 559.
10. **`${VAR}` substitution stays with task 707** (fk-e79170280adf). That task refuses unused variables and embedded placeholders and reads a non-numeric default through `as_finite_float`, naming the variable and its key path. S4 does not edit `_substitute_variables`, so the function has one editor.
11. **The engine's per-step arguments are S3's** (`simulate_timestep` inputs, `decide_action`'s copied input block, `DispatchDecision`, `battery._require_valid_request`). S3 rewrites those functions under D6. It uses `Interval.admits` and raises `ValueError` (computed values, C4). Durations stay with tasks 659 and 672 (and S10's cadence). S4 owns only `EnergyFlowResult` in the engine (θ).
12. **Freeze both result classes (R3).** `EnergyFlowResult` also refuses a non-finite or negative flow with `ValueError` naming each field and value. The measured cost (§2.2) is accepted.
13. **The web pre-reads only what it alone can name.**
    - It deletes reads that config or the domain repeats under the same name: `PVConfig`'s fields in `parse_home_config`, the distribution rebuild's numbers and defaults, and the fleet-size pre-read.
    - It keeps reads of request-only names: `pv_kw`, `battery_kwh`, `consumption_kwh`, `occupants`, the heat-pump block's `heat_pump.<key>`, and the sweep's `min`, `max` and `steps`.
    - Dashboard-only bounds (`MAX_FLEET_HOMES` on `n_homes` and pool totals) apply to the parsed `FleetDistributionConfig`, as `builder_form` already does.
14. **The rebuild stays a shape translator only.** `_build_distribution_dict` keeps the form's row-to-list translation (`values[i].weight` → `weights[i]`, `entries[i].count` → `counts[i]`). It passes every other key, every type and every number through as sent. Deleting the translator is S18's (D18).
15. **Invariant 1 is a discovery guard with a two-way classification (§5.6).** This corrects its premise (§7): "every dataclass in solar_challenge" includes computed results, which carry no finiteness contract of that type.

## 5. Contract

### 5.1 `solar_challenge.number_fields` (α)

```python
# src/solar_challenge/number_fields.py — imports solar_challenge.errors and solar_challenge.whole_numbers only
@dataclass(frozen=True)
class Interval:
    low: float = -math.inf
    high: float = math.inf
    low_open: bool = False
    high_open: bool = False
    def admits(self, number: float) -> bool: ...   # finite and inside; False for NaN and ±inf
    def __str__(self) -> str: ...                   # "" when unbounded; "between 0 and 360"; "greater than 0 and at most 1"; "at least -500"

POSITIVE: Final = Interval(0, math.inf, low_open=True)          # (0, ∞)
NON_NEGATIVE: Final = Interval(0, math.inf)                     # [0, ∞)
FRACTION: Final = Interval(0, 1, low_open=True)                 # (0, 1]
UNIT_INTERVAL: Final = Interval(0, 1)                           # [0, 1]

def as_finite_float(value: object, field: str, within: Interval = Interval()) -> float: ...
def as_whole_number(value: object, field: str, within: Interval = Interval()) -> int: ...
def as_finite_floats(values: object, field: str, within: Interval = Interval()) -> tuple[float, ...]: ...
def as_whole_numbers(values: object, field: str, within: Interval = Interval()) -> tuple[int, ...]: ...
def read_field(instance: object, field: str, read: Callable[[object, str, Interval], object],
               within: Interval = Interval(), *, optional: bool = False) -> None: ...
```

| # | Rule | Enforced by |
|---|---|---|
| N1 | `import solar_challenge.number_fields` loads, from the package, only `solar_challenge`, `errors`, `whole_numbers` and itself | α's fresh-interpreter test |
| N2 | A reader refuses a bool (Python's or numpy's), a value `float()` cannot read (including an int too large for a float), NaN and ±inf, with `{field} must be a finite number, got {value!r}`; `as_whole_number` also refuses a fraction with `{field} must be a whole number, got {value!r}` | α's tests (moved and extended from `test_web_number_fields.py`) |
| N3 | A value outside `within` is refused with `{field} must be {within}, got {value!r}`; a closed finite interval reads `between {low} and {high}`, the web's wording today | α's tests; the existing web tests pass unchanged |
| N4 | Every refusal is `errors.ConfigurationError` | α's tests; ι |
| N5 | `as_finite_floats`/`as_whole_numbers` refuse a str, a mapping or a non-iterable with `{field} must be a list of …, got {value!r}`, and read element *i* as `{field}[{i}]`, returning a tuple | α's tests |
| N6 | `read_field` stores what `read` returns with `object.__setattr__`; with `optional=True`, None stays None | α's tests |
| N7 | `Interval.admits` is the rule for computed values, which raise `ValueError` themselves (C4) | θ; S3 by cross-reference |

### 5.2 Input types (β, γ, δ, ζ)

- `__post_init__` reads every numeric field with `read_field` first, in field order, then applies cross-field rules. Each refusal is a `ConfigurationError` naming the bare field (`capacity_kw`, `months[0]`).
- Public helpers that refuse an input value delegate to the readers and raise `ConfigurationError`: `battery.require_valid_power_limit`, `require_valid_capacity_setting` (and so `has_battery`), and `dispatch._require_valid_import_limit` / `_require_valid_peak_hours` (S2 α).
- Every other `raise ValueError` in an input type's constructor becomes `ConfigurationError` (L1).

### 5.3 Config's readers (ε, ζ)

```python
def _constructed(block_path: str, cls: Callable[..., _Built], /, **values: Any) -> _Built:
    """cls(**values), its ConfigurationError re-raised as "<block label>: <message>" from the original."""
```

- Every reader that builds an input type calls `_constructed` with its block path and the block's values as written.
- The scalar arm of `_parse_distribution_spec` (any non-mapping, non-null value) and `fixed`'s `value` are read with `as_finite_float(value, <parameter path>)`.
- S5 moves `_constructed` with the readers into `scenario_blocks.py` (§8).

### 5.4 Which types are input types

These are tested by ι:

- battery `BatteryConfig`
- community `CommunityBillingConfig`
- config `WeightedDiscreteDistribution`, `NormalDistribution`, `UniformDistribution`, `ShuffledPoolDistribution`, `ProportionalDistribution`, `SweepSpec`, `FleetDistributionConfig` and `ScenarioConfig`
- dispatch `GridChargeConfig`, `TOUOptimizedStrategyConfig` and `PeakShavingStrategyConfig` (S2 α)
- ev `EVConfig`
- finance `FinanceConfig`
- flex `FlexibilityValueBand`
- gridservices `GridServicesRateBand`, `EventWindow` and `GridServicesEventsConfig`
- heat_pump `HeatPumpConfig`
- load `LoadConfig`
- location `Location`
- optimize `ConfigPoint`
- pv `PVConfig`
- seg `SEGTariff`
- tariff `TariffPeriod`

`FleetConfig`, `CommunityConfig` and `TariffConfig` are input types with no numeric field; L1 converts their refusals.

Not input types, classified in ι's table with the reason:

- **Computed results (C4):**
  - `SummaryStatistics`, `EnergyFlowResult`, `DispatchDecision` and `GridChargeContext`;
  - `BillBreakdown`, `BillDistribution`, `CostRecoverySolution`, `YearPoint`, `MultiYearCurve`, `ProjectEconomics` and `_NodeData`;
  - `FleetSummary` and `MultiSweepResults`;
  - `GridServicesAtEvents`;
  - `RankedSweep`, `SensitivityAxis`, `SensitivityPanel` and `ConfigResult`;
  - `CommunityResults` and `CommunityMetrics`;
  - `ValidationResult`.
- **Library or private values:** `pv.CecInverter`, `pv._StringGroup`, `pv._Inverter`, `battery._SocLimitsAndEfficiencies` and `home._StepAmount`.
- **Spec containers:** `PVDistributionConfig`, `BatteryDistributionConfig`, `LoadDistributionConfig`, `HeatPumpDistributionConfig` and `EVDistributionConfig`. Each scalar arm is read at parse (§5.3), and each sampled value is read by the generated home's type.
- **Retired by S5:** `ParameterSweepConfig` and `SweepResult`.

Field-level exclusions:

- `WeightedDiscreteDistribution.values` and `ShuffledPoolDistribution.values` hold outcome values (decision 6).
- `PVConfig.custom_module_params` and `custom_inverter_params` are pvlib parameter mappings, which S14 owns.

### 5.5 Results (θ)

`SummaryStatistics` and `EnergyFlowResult` are `@dataclass(frozen=True)`. `EnergyFlowResult.__post_init__` refuses any field that `NON_NEGATIVE.admits` rejects. It raises one `ValueError` naming each refused field and its value, keeping today's single-error shape. S10's derived `simulation_days` and window field, and S12's named loads, set fields through `object.__setattr__` or `dataclasses.replace` (§8).

### 5.6 Invariant 1 (ι; D27)

`tests/unit/test_input_type_numbers.py`:

- **Discovery.** It finds every dataclass defined in a module directly under `solar_challenge` (not `web/` or `cli/`) whose field annotations mention `int` or `float`, including inside `Optional`, `Union` or `tuple`. It resolves hints where it can, falling back to the annotation text.
- **Two-way table.** `INPUT_TYPES` maps each class to a valid-instance factory. `NOT_INPUT_TYPES` maps a class to its reason, and `EXCLUDED_FIELDS` maps a (class, field) pair to its reason.
  - A discovered class in neither table fails. The message names it and says to classify it.
  - A listed class no longer discovered fails, naming the stale entry.
- **Refusal.** For each input type and each numeric field not excluded, each of `nan`, `inf`, `-inf`, `True` and `"x"` is tried, plus `2.5` where the field is whole. A tuple field gets a one-element tuple; for `peak_hours`, the bad value is the first hour of the first pair. `dataclasses.replace(valid, field=bad)` must raise `ConfigurationError` whose message contains the field name and `repr(bad)`.
- **Briefing.** One `review/briefing.yaml` `conventions` entry states the rule and its reason and points at the test.

## 6. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer | import the leaf alone | fresh `-I` interpreter (pattern of `test_init_lazy_surface.py`) | `solar_challenge.*` in `sys.modules` is exactly `solar_challenge`, `errors`, `whole_numbers`, `number_fields` | α |
| P2 | producer | interval phrasing | — | `str(POSITIVE) == "greater than 0"`, `str(Interval(0, 1, high_open=True)) == "at least 0 and less than 1"`, `str(Interval(0, 360)) == "between 0 and 360"`, `str(Interval()) == ""`; `POSITIVE.admits(nan)` and `.admits(inf)` are False | α |
| P3 | producer | readers | — | each N2–N6 row; `as_whole_numbers([1, 2.5], "months")` raises naming `months[1]` and `2.5`; every refusal `isinstance` `ConfigurationError` | α |
| W1 | consumer: web | wording unchanged | existing web tests (`test_web_number_fields` cases moved, fleet form, builder, simulation params) | pass with only import-line edits | α |
| D1 | consumer: library | input types refuse by name | — | §1 item 2's constructions each raise `ConfigurationError` naming the field and `repr` | β, γ |
| D2 | consumer: library | stored value | — | `PVConfig(capacity_kw=4).capacity_kw` is the float `4.0`; `EVConfig("7kW", 18.0).arrival_hour` is the int `18`; `EventWindow(months=[1, 2], …).months == (1, 2)` | β, γ |
| D3 | consumer: library | non-numeric refusals typed (L1) | — | `HeatPumpConfig("XSHP", 8.0)`, `EVConfig("9kW", 18)` and `FleetConfig(homes=[])` raise `ConfigurationError` | β, γ |
| D4 | consumer: library | dispatch inputs | 786 landed | `PeakShavingStrategy(import_limit_kw=True)`, `PeakShavingStrategy(import_limit_kw=nan)` and `PeakShavingStrategyConfig(True)` raise `ConfigurationError` naming `import_limit_kw`; `GridChargeConfig(True)` raises naming `target_soc_fraction`; `TOUOptimizedStrategyConfig(((16.5, 19),))` raises naming `peak_hours` | δ |
| C1 | consumer: CLI | key path on the way up | probe files of §2.2 | `validate config` exits 1; the ERROR row reads `home.pv: capacity_kw must be a finite number greater than 0, got True`, `home.ev: arrival_hour must be a whole number …, got 18.9`, `fleet_distribution: n_homes must be a whole number …, got 2.7`; an entry of `homes:` names `homes[1].…` | ε, ζ |
| C2 | consumer: CLI | no traceback | `pv: {azimuth: south}` | exit 1, `Configuration error:` or an ERROR row naming `azimuth` and `'south'`; no `TypeError` | β (path from ε) |
| C3 | consumer: CLI | finance block | `bristol-phase1-flex.yaml` with `event_hours: .inf`; with `vat_rate: true` | exit 1 naming `event_hours` and `inf`; naming `finance: vat_rate` and `True` (today "finance block contains a non-numeric value: True is a boolean, not a number") | γ, ε |
| C4 | consumer: grammar | scalar arm | fleet with `pv: {capacity_kw: true}` | refused naming `fleet_distribution.pv.capacity_kw` and `True` (today 1.0 kW) | ζ |
| C5 | consumer: grammar | rounded hours | `scenarios/bristol-with-evs.yaml` | mean arrival ≥ 17.9 and mean departure ≥ 7.1 over its 30 EV homes (rounded draws measured 17.933 / 7.200; today 17.433 / 6.533) | ζ |
| C6 | consumer: web | form passes through | POST `/api/simulate/fleet-from-distribution` | `pv.capacity_kw: {type: normal, mena: 4, std: 1}` → 400 naming `mena`; `{type: normal}` → 400 naming the missing `mean`; `pv.tilt: {type: fixed, value: 30}` → 201 | η |
| C7 | consumer: web | sweep numbers | POST `/api/simulate/sweep` | `{"min": true}` → 400 naming `min` and `True` (today runs from 1.0); `{"steps": 2.5}` → 400 naming `steps` | η |
| R1 | consumer: engine | frozen results | — | assigning `summary.total_generation_kwh` or `flow.grid_export` raises `FrozenInstanceError`; `simulate_timestep(inf, 1.0, None)` raises `ValueError` naming `generation` and `inf` | θ |
| G1 | guard | seeded unclassified class | `tmp_path` module with a numeric dataclass, discovered through the test's discovery function | reported by name with the classification instruction | ι |
| G2 | guard | the real tree | ι's base | every input type refuses every bad value by name with `ConfigurationError`; no unclassified or stale entry | ι |

## 7. Invariant 1: premise correction

The program's checkable text reads "for every dataclass in solar_challenge whose fields include float or int, constructing with NaN, inf, -inf and True … raises". Measured at `962552956508`, 54 dataclasses in top-level modules have a numeric field. 25 of them are computed results, library rows or private values:

- Under S1's C4 they raise plain `ValueError` when they break their own invariant.
- Several have no finiteness rule at all. `SummaryStatistics` checks only its grid-charge sub-total; `FleetSummary` and `BillDistribution` check nothing.
- `ParameterSweepConfig` goes with S5.

So the checkable form promoted here is: every **input type** refuses as stated, with `ConfigurationError` (L1); every other numeric dataclass is classified with a reason. The fixture's 13 named classes are a subset of §5.4. `config.DispatchStrategyConfig` is replaced by S2 α's three variants and `dispatch.GridChargeConfig`.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 errors leaf (773, 774, 775) | consumes | `errors.ConfigurationError(ValueError)` raised by the readers | S1 | α depends on 774. γ updates S1 β's C2 pin: the `EventWindow.months` wording becomes `months[0] must be a whole number between 1 and 12, got 13` |
| S2 dispatch (786) | consumes, edits | `_require_valid_import_limit`, `_require_valid_peak_hours` and `dispatch.GridChargeConfig` read through the leaf (S2 §5.1 extension point) | S4 δ | δ depends on 786 |
| S3 one dispatch engine | produces for | `Interval.admits` for `DispatchDecision`, `simulate_timestep`'s inputs, `decide_action`'s input block and `battery._require_valid_request`, raising `ValueError` | S3 (uses), S4 (rule) | **proposed:** S3's leaves touching those checks depend on α; fk-a9c609ecb8ef closes when S4 ι and S3 land |
| S5 scenario grammar | consumes, moves | `number_fields` is the bottom stratum beside `errors`; `_constructed` moves with the readers to `scenario_blocks.py`; reader-local messages gain block paths (S5) | S4 owns `_constructed`; S5 moves it | **proposed:** S5's partition depends on α; ε depends on S5's partition (the seam table's "S4 imports the partitioned modules by their final names") |
| S7 component defaults | file overlap | config's readers and the distribution configs | — | no edge; file locks serialize |
| S9 grid-services pricing | consumes | S9's new pricing values read through the leaf (its PRD: "once it lands") | S9 | **proposed:** those leaves depend on α; ι classifies whatever exists at its base |
| S10 window | file overlap | frozen `SummaryStatistics` (θ): S10's derived fields set through `object.__setattr__` | S10 | note |
| S11 tariff | consumes | `TariffPeriod.rate_per_kwh` and `TariffConfig`'s refusals through the leaf | S4 γ | γ depends on S11 α (S11 §8: "S4 after α") |
| S12 load composition, S25 board reports | file overlap | frozen `SummaryStatistics` | — | note |
| S14 PV model | consumes | `PVConfig`'s Optional `module_efficiency` and `temperature_coefficient` read with `optional=True`; ζ's new `ValueError` refusals converted (L12) | S4 β | **proposed:** β depends on S14 ζ, so PVConfig is converted once |
| S17 web request boundary | consumes | every input-type refusal is a `ConfigurationError` (β, γ, δ); the web reads only request-only names (η) | S17 translator | S17 depends on S4 (program); **proposed:** on β, γ, δ and η |
| S18 dashboard limits | consumes | `_build_distribution_dict` is a pure shape translator after η; S18 deletes it under D18 | S18 | **proposed:** S18's editor leaf depends on η |
| S19 run store | consumes | a stored run whose config holds a value S4 refuses fails to rebuild; S19's loader names it | S19 | note |
| S26 sweep registry | consumes | `SweepSpec` reads its numbers (ζ); `simulate_sweep`'s `mode` routing | S26 | note |
| S27 community | file overlap | `CommunityConfig`'s `sharing_mode` refusals become `ConfigurationError` (γ) until S27 deletes them | — | note |
| S28 battery facts | file overlap | `BatteryConfig`'s refusals (β); S28's efficiency refusal raises `ConfigurationError` (L5) | — | note |
| S29 surface bump | none | nothing held (D29) | — | — |
| task 395 | upstream | `_DistributionSampler.sample_count` | 395 | ζ depends on 395 |
| task 707 | consumes | reads the `${VAR:default}` through `as_finite_float`, naming the variable and key path | 707 | **proposed:** 707 depends on α |
| tasks 659, 672 | consumes | the duration rule written over `POSITIVE.admits` if they land after α | 659/672 | note |

## 9. Existing tasks this PRD meets

Run contract §8 step 1 before filing. A task S4 supersedes is cancelled with `metadata.x_superseded_by` naming the covering leaves.

| Task | Status | Disposition |
|---|---|---|
| 382 | pending | **superseded** by β, γ, δ and ζ: NaN and inf through one-sided guards in the input types. Its suggested inline `math.inf` convention is what S4 replaces |
| 314 | pending | **superseded** by ε and ζ: non-finite and overflow-sized tariff and distribution numbers. `float(10**400)` is refused by N2 |
| 521 | pending | **superseded** by ζ: a bool read as 1.0 in the scalar arm and in code-built specs |
| 618 | pending | **superseded** by ζ: `n_homes` and pool counts truncated |
| 616 | pending | **superseded** by γ and ε: event-window counts truncated and bools read as numbers |
| 675 | pending | **superseded** by β, ε and ζ: EV hours truncated or bool-accepted. Carries fk-a2b33a420bcf |
| 558 | pending | **superseded** by δ and ε: `grid_charging.target_soc_fraction: true` |
| 673 | pending | **superseded** by δ: `PeakShavingStrategy` with a NaN or infinite limit |
| 187 | pending | **superseded** by γ and ε: the community billing SEG scalar and `SEGTariff` finiteness |
| 395 | merge phase | upstream of ζ |
| 423 | pending | stays: S4 removes its `capacity_kw: four` TypeError (C2); the non-mapping-document and `homes: 5` refusals remain |
| 517 | pending | stays, and carries fk-5827f41eb082 (decision 9) |
| 559 | pending | stays: `use_stochastic` as a boolean |
| 570 | pending | stays; re-verify after 395 and ζ, which read a non-finite draw by name before any `int()` |
| 573 | pending | stays: the seed's 0..2**32−n range rule. ζ refuses a fractional or bool seed |
| 651 | pending | S5's to cancel: `ParameterSweepConfig` is deleted |
| 659, 672 | pending | stay: durations |
| 678 | pending | stays: rounding against a spec's min and max |
| 707 | pending | stays, and carries fk-e79170280adf (decision 10) |
| 331, 509, 560, 660 | pending | adjacent; untouched |

## 10. Decomposition plan

Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`. Priority is the highest severity among its keys. Each leaf that tightens a public class adds an "Unreleased on main" line in the doc's existing "refuses input the 0.5.0 tag accepted" form. Each updates the existing tests whose `match=` pins old wording.

**α — `number_fields` moves to the package leaf with intervals and `ConfigurationError`** (intermediate; unlocks β, γ, δ, θ; priority high)
- **Keys:** fk-a9c609ecb8ef, fk-649851e5fc38.
- **Work:**
  - `git mv` `web/number_fields.py` → `src/solar_challenge/number_fields.py`, and build §5.1 on it.
  - Repoint `builder_form`, `fleet_config` and `simulation_params`, rewriting their `_within` calls to `within=Interval(low, high)`.
  - Move `tests/unit/test_web_number_fields.py` to `tests/unit/test_number_fields.py`, extended for P1–P3. Repoint `tests/_unusable_numbers.py` and `tests/_whole_number_forms.py`.
- **Signal:** P1–P3 pass. The web's number refusals keep their text and are now a `ConfigurationError` (W1). `src/solar_challenge/web/number_fields.py` is gone.
- **Prereqs:** 774.

**β — Component and fleet inputs read their numbers through the leaf** (intermediate; unlocks ε, ι; priority high)
- **Keys:** fk-a9c609ecb8ef, fk-606a9211b34d, fk-7dcdc5559d22, fk-a2b33a420bcf.
- **Work:**
  - `PVConfig`, `BatteryConfig` (with `require_valid_power_limit` and `require_valid_capacity_setting`), `LoadConfig`, `HeatPumpConfig`, `EVConfig`, `Location` (including the time zone) and `FleetConfig`, per §5.2.
  - L1 conversions in those modules.
  - Supersedes 382 (in part) and 675 (`EVConfig`).
- **Files:**
  - `src/solar_challenge/{pv,battery,load,heat_pump,ev,location,fleet}.py`;
  - `tests/unit/test_{pv,battery,load,heat_pump,ev,location,fleet}.py` and the tests that match old wording;
  - `docs/domain-library-consumption.md`.
- **Signal:**
  - `solar-challenge validate config` exits 1 with an ERROR row naming the field and value for each of these homes; each passes today, or tracebacks: `pv: {capacity_kw: true}`, `pv: {azimuth: south}` (no `TypeError`), `heat_pump: {thermal_capacity_kw: .nan}`, `location: {altitude: .nan}` and `location: {timezone: Europe/Londn}`.
  - D1–D3 for these types.
- **Prereqs:** α; **proposed** S14 ζ.

**γ — Tariff, SEG, finance, grid-services, flexibility, community and install-point inputs read their numbers through the leaf** (intermediate; unlocks ε, ι; priority medium)
- **Keys:** fk-b69968a37b36, fk-606a9211b34d.
- **Work:**
  - `SEGTariff`, `TariffPeriod` (swaps S11 α's idiom), `FinanceConfig`, `GridServicesRateBand`, `EventWindow` (tuples of whole numbers), `GridServicesEventsConfig`, `FlexibilityValueBand`, `CommunityBillingConfig` and `ConfigPoint`.
  - L1 conversions for `TariffConfig`, `CommunityConfig` and `TariffPeriod`'s time refusals.
  - Update S1 β's C2 wording pin.
  - Supersedes 382 (in part), 616 (`EventWindow`) and 187 (`SEGTariff`).
- **Files:**
  - `src/solar_challenge/{seg,tariff,finance,gridservices,flex,community,optimize}.py`;
  - their tests;
  - `docs/domain-library-consumption.md`.
- **Signal:**
  - `solar-challenge validate config` on `bristol-phase1-flex.yaml` with `event_hours: .inf` exits 1 naming `event_hours` and `inf`; today it is valid.
  - `SEGTariff("x", nan)` and `TariffPeriod("00:00", "00:00", nan)` raise `ConfigurationError` naming the rate.
  - D2 for `EventWindow`.
- **Prereqs:** α; **proposed** S11 α.

**δ — Dispatch inputs read their numbers through the leaf** (intermediate; unlocks ε, ι; priority high)
- **Keys:** fk-a9c609ecb8ef, fk-606a9211b34d.
- **Work:** `dispatch.GridChargeConfig`, `_require_valid_import_limit` and `_require_valid_peak_hours`, which serve both the configs and the strategy constructors. Supersedes 673 and 558 (domain half).
- **Files:** `src/solar_challenge/dispatch.py`; `tests/unit/dispatch/`; `docs/domain-library-consumption.md`.
- **Signal:**
  - `solar-challenge validate config` on `scenarios/dispatch-comparison.yaml` with a peak-shaving `import_limit_kw: true` exits 1 naming `import_limit_kw` and `True`. Today it validates, since `True` passes `<= 0`. Any comparison idiom 786 adopts also passes `True`, so this stays RED until δ.
  - On `scenarios/bristol-arbitrage.yaml` with `target_soc_fraction: true`, it exits 1 naming `target_soc_fraction`; today it validates (task 558).
  - D4.
- **Prereqs:** α, 786.

**ε — Config's block readers construct through one wrap and pass values as written** (intermediate; unlocks ζ; priority high)
- **Keys:** fk-649851e5fc38, fk-a2b33a420bcf.
- **Work:**
  - `_constructed` (§5.3), used by `parse_location_block`, `_parse_pv_config`, `_parse_battery_config`, `_parse_grid_charge_config`, `_parse_load_config`, `_parse_heat_pump_config`, `_parse_ev_config` (its `int()` and `str()` go), `_parse_tariff_period` and the tariff builders, `parse_seg_rate` / `_parse_seg_rate_scalar` (its `isfinite` rule goes), `_parse_event_windows` (coercions and handler go), `_parse_grid_services_events_config` and `parse_finance_config` (both coercion tables go), `_parse_community_billing_config` and `parse_home_block`.
  - Delete `_number` and `_number_or_none`.
  - Supersedes 314 (tariff half), 616 (reader half), 558 (reader half) and 187 (reader half).
- **Files:**
  - `src/solar_challenge/config.py`, or `scenario_blocks.py` after S5's partition;
  - `tests/unit/config/`;
  - `tests/unit/test_cli.py` for C1–C3.
- **Signal:** C1, C2 and C3. `validate config` names `home.ev: arrival_hour` and `18.9`, `home.pv: capacity_kw` and `True`, and `finance: vat_rate` and `True`. A `homes:` entry names `homes[<i>]`.
- **Prereqs:** α, β, γ, δ; **proposed** S5's partition leaf.

**ζ — The fleet grammar reads its numbers at construction and rounds sampled counts** (intermediate; unlocks η, ι; priority high)
- **Keys:** fk-649851e5fc38, fk-60410de6dd0a, fk-a2b33a420bcf.
- **Work:**
  - The distribution types, `ProportionalDistribution` (gains a `__post_init__`), `SweepSpec`, `FleetDistributionConfig` (`n_homes` whole and at least 1; `seed` whole and Optional) and `ScenarioConfig.seg_tariff_pence_per_kwh` read through the leaf.
  - The `_build_*_spec` builders and `parse_fleet_distribution_config` construct through `_constructed` and pass values as written.
  - The scalar arm and `fixed` read with the parameter path; delete `_float_or_none`.
  - `generate_homes_from_distribution` rounds EV hours through `sample_count`.
  - Unreleased line: seeded EV fleets change.
  - Supersedes 314 (distribution half), 521 and 618.
- **Files:**
  - `src/solar_challenge/config.py`, or `fleet_distribution.py` after S5;
  - `tests/unit/config/`;
  - `docs/domain-library-consumption.md`.
- **Signal:**
  - C1's `n_homes` row: `validate config` on a fleet with `n_homes: 2.7` exits 1 naming `n_homes` and `2.7`; today it runs 2 homes.
  - C4.
  - C5 on the shipped `bristol-with-evs.yaml`.
- **Prereqs:** ε, 395.

**η — The web stops pre-reading numbers ahead of config** (intermediate; unlocks ι; priority high)
- **Keys:** fk-60410de6dd0a, fk-239274130a5a.
- **Work:**
  - Decisions 13 and 14:
    - `fleet_config`: `_build_distribution_dict` becomes shape-only; `_spec_number` goes; `_other_setting` and the fixed value pass values as sent; dashboard bounds apply to the parsed fleet.
    - `fleet_scenario`: `_read_fleet_size_and_seed` goes; the form reads `n_homes` and `seed` from the parsed fleet.
    - `simulation_params`: the four `PVConfig`-named pre-reads and their comment go.
    - `api.simulate_sweep`: `min`, `max` and `steps` are read through the leaf.
    - `assistant`'s `n_homes`.
  - Re-measure fk-239274130a5a's number half and record it on the task.
- **Files:**
  - `src/solar_challenge/web/{fleet_config,fleet_scenario,simulation_params,api,assistant,builder_form}.py`;
  - `tests/unit/web_api/`;
  - `tests/unit/test_web_fleet_config.py` and `tests/unit/test_web_*` as needed.
- **Signal:** C6 and C7 through the Flask test client. `fleet_form_from_scenario` on a scenario with `n_homes: 2.5` refuses naming `fleet_distribution: n_homes` from config's own reader.
- **Prereqs:** ζ, β.

**θ — Summary and step results are frozen values; a step result refuses a non-finite flow** (intermediate; unlocks ι; priority high)
- **Keys:** fk-f2f8a5512feb, fk-a9c609ecb8ef.
- **Work:**
  - §5.5.
  - `FROZEN_SURFACE`'s `frozen` flag for both classes.
  - An Unreleased line: assignment raises; `simulate_timestep` with a non-finite input raises where it returned infinite flows. Record the measured per-step cost in the commit message.
- **Files:** `src/solar_challenge/{home,flow}.py`; `tests/unit/test_flow.py`, `tests/unit/test_home.py`, `tests/unit/test_public_api_surface.py`; `docs/domain-library-consumption.md`.
- **Signal:** R1.
- **Prereqs:** α.

**ι — Invariant 1 guard: every input type refuses a non-finite, bool or non-number value by name** (leaf; integration gate; priority high)
- **Keys:** fk-a9c609ecb8ef, fk-606a9211b34d, fk-b69968a37b36.
- **Work:**
  - §5.6.
  - Convert any input type still raising `ValueError` or using an inline bound at ι's base; for example, S14 ζ's or S9's if they landed after β or γ.
  - The `review/briefing.yaml` conventions entry.
- **Files:** `tests/unit/test_input_type_numbers.py` (new); `review/briefing.yaml`; any input-type module the walk finds unconverted.
- **Signal:**
  - The per-task verify runs it. G1: a seeded unclassified numeric dataclass fails by name. G2 over the real tree.
  - Constructing `SEGTariff("x", nan)`, `HeatPumpConfig("ASHP", nan, 8000.0)` or `EVConfig("7kW", True)`, and every other (input type, numeric field, bad value) triple, raises `ConfigurationError` naming the field and the value.
  - The briefing carries the rule.
- **Prereqs:** β, γ, δ, ζ, η, θ.

**DAG.** 774 → α. α → {β, γ, δ, θ}. 786 → δ. {α, β, γ, δ, S5 partition} → ε. {ε, 395} → ζ. {ζ, β} → η. {β, γ, δ, ζ, η, θ} → ι.

**Intra-batch edges:** β→α, γ→α, δ→α, θ→α, ε→{α, β, γ, δ}, ζ→ε, η→{ζ, β}, ι→{β, γ, δ, ζ, η, θ}.

**Out-of-batch edges:** α→774, δ→786, ζ→395. Proposed: β→S14 ζ, γ→S11 α, ε→S5 partition.

High leaves (α, β, δ, ε, ζ, η, θ, ι) join trigger-chain gate 772.

**G7** (advisory: this repo has no `docs/legibility/design-invariants.md`; walked against dark-factory's trigger shapes):

- **`no-silent-fail-soft`:** η removes the silent defaults and key drops; ζ removes truncation.
- **`one-fact-one-home` / `no-lockstep-duplication`:** the interval and the reader are the one home; the pre-reads and coercion tables go.
- **`exceptions-owned-or-ratified`:** every non-input entry and excluded field in ι's table carries a reason or an owner stream.
- **`guards-exercise-behaviour`:** ι constructs instances; it greps nothing.

No hit.

## 11. Out of scope

- The engine's per-step argument checks and `DispatchDecision`'s finiteness. These are S3's, through `Interval.admits` (decision 11).
- Durations and cadence (tasks 659 and 672; S10).
- Booleans and strings at both boundaries:
  - `use_stochastic` (task 559);
  - `stochastic`, `name` and `location` in web bodies (task 517, S17);
  - sweep `mode` (S26).
- `${VAR}` substitution (task 707).
- Block paths in reader-local messages that do not come from a constructor (S5).
- The request-reading module, presence rule and web translator (S17).
- The editor's per-type table and deleting the form's shape translation (S18, D18).
- `PVConfig`'s pvlib parameter mappings (S14).
- The seed's numpy range (task 573).
- Rounding against a distribution's min and max (task 678).
- Making the readers or `Interval` public in `__all__`.

## 12. Open questions

**Tactical** (decide during the leaf):

1. α: whether `Interval.__str__` prints integral float bounds as `0` or `0.0`. The web's closed ranges use whatever literal their callers pass, and N3 must keep those messages byte-identical.
2. β: `require_valid_capacity_setting`'s message drops "(0 for no battery)" unless the helper keeps a suffix. Either is fine; the CLI flag `--battery-kwh` moves from `Invalid value:` to `Configuration error:`.
3. ε: the wrap's label for the top level of a flat home file (`_block_label("")` reads "the top level").
4. η: `assistant`'s `n_homes` refuses out-of-range values rather than clamping them. Suggested: refuse; the model gets a tool error.
5. ι: how discovery resolves annotations that `get_type_hints` cannot (module namespace merge, or annotation text).

**For the lead** (cross-stream; S4 is correct whichever way each goes):

1. **Ordering against S5.** Proposed: S5's partition depends on α, and ε depends on S5's partition, per the seam table's "S4 imports the partitioned modules by their final names". The alternative is that S5 moves ε's and ζ's code after they land. Either way the code moves once; the choice is which stream waits.
2. **β after S14 ζ, γ after S11 α.** These convert `PVConfig` and `TariffPeriod` once. Otherwise ι converts the stragglers.
3. **S3 takes the engine's checks** through `Interval.admits` and depends on α (decision 11). fk-a9c609ecb8ef then closes when S4 ι and S3 land.
4. **fk-5827f41eb082 stays with 517 and fk-e79170280adf with 707** (decisions 9 and 10). S4 files no leaf for either key. Proposed edge: 707 depends on α.
5. **Invariant 1's premise correction (§7).** The checkable text becomes "every input type" plus a reasoned classification of the rest.

## Gate record

- **G1:**
  - The leaf is consumed by every input type (β, γ, δ, ζ), config's readers (ε, ζ), the web (α, η), S3's engine checks, S9's new values and task 707.
  - `Interval.admits` is consumed by θ and S3.
  - `_constructed` is consumed by every block reader.
  - ι's guard is consumed by every stream that adds a numeric dataclass.
  - No orphan producer.
- **G3:** the substrate is verified:
  - `web/number_fields.py`'s four readers and their tests;
  - `whole_numbers.whole_number`;
  - `zoneinfo` resolves every zone in use (probed);
  - `validate config` prints ERROR rows for a `ConfigurationError` and a `ValueError`, and a traceback for a `TypeError` (probed);
  - the fresh-interpreter `sys.modules` pattern in `test_init_lazy_surface.py`;
  - `review/briefing.yaml` `conventions:`;
  - S2 α's validators (786, filed), task 395's `sample_count` (in merge) and S5's partition (to be filed), each wired as a prerequisite.
  - The type-hint route was rejected because `get_type_hints` fails on `BatteryConfig` and `FinanceConfig` (probed).
- **G4:**
  - The S4/S18 overlap on `_build_distribution_dict` is resolved: S4 takes numbers and lossy drops, S18 the shape.
  - The S4/S5 overlap on block paths is resolved: S4 owns construction refusals, S5 reader-local messages.
  - The S1/S2 PRDs' "block paths on construction-time refusals (S5)" is met by S4's `_constructed`, which S5 moves.
  - The S4/707 and S4/517 key splits and the S3 engine handoff go to the lead.
- **G5:** B + H. The blast radius is 14 src modules plus the web, the seam is load-bearing at both boundaries, and six streams consume it.
- **G6:**
  - Every RED premise was probed at `962552956508` (§2.2).
  - C5's bounds rest on the measured rounded means 17.933 and 7.200, with the draw sequence unchanged because rounding follows the draw.
  - The `FrozenInstanceError` and `ValueError` rejection mechanisms are Python's own.
  - θ's cost was measured and ruled (R3).
  - Invariant 1's "every dataclass" premise was false and is corrected (§7).
- **G7:** advisory, no hit (§10).
- **META:** decomposing this without further oversight yields:
  - one number rule in a leaf below config, with intervals as values;
  - every input type reading and storing its numbers by name and refusing with the one boundary type;
  - config's readers adding paths instead of coercing;
  - the web deferring to config;
  - frozen results;
  - a guard that forces every future numeric type to be classified.

  The lead questions are cross-stream ordering and key ownership; neither changes S4's design.
