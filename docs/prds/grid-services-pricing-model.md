# PRD — Grid-services pricing: one closed model, priced per projection age

- **Program:** review-all-solar_challenge-20261013, stream **S9** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 1, size M, risk medium. Upstream: S1 (L5).
- **Finding keys:** fk-758b2f309cab, fk-4ddab794283a, fk-aafe32daa988, fk-d432a549b03f, fk-0f24b7f66eb2, fk-71b4ca35efe0 (already filed as task 704; §2.3).
- **Binding rulings:** D13 (capacity-at-events income is computed per projection age from that age's aged homes; the age-0 closure memo and finance.py's function-local gridservices import go; the compute-once tests become per-age tests; `FinanceConfig.grid_services_model` becomes a closed selector type), D29 (additive frozen-table edits land in-leaf with an "Unreleased on main" line; renames and retirements are held for S29), D4 (one coordinated surface bump; no shim or dual field survives it), L5 (S9's refusals depend on S1-β and raise `errors.ConfigurationError`).
- **Status:** authored 2026-10-14 by an author-only /prd session. Not committed, not decomposed.
- **Approach:** B + H. The model is read by finance, both finance CLIs, optimize, flex and the scenario grammar, sits on the frozen surface, and is a seam for S8, S25 and S26. So it gets a contract (§5) and two-way boundary tests (§9).
- **Code anchors** verified against main `9d7b67e` (2026-10-14). Main moves fast — cite-by-symbol; re-locate lines at implementation time. `finance.py`, `gridservices.py`, `flex.py`, `optimize.py`, `config.py`, `cli/finance.py` and `cli/optimize.py` are byte-identical to the review's pin `7dfea36`. `tests/integration/test_grid_services_events.py` moved 16 lines, but its two monkeypatching tests are unchanged. Task 704 (in merge) rewrites `cli/optimize._SENSITIVITY_ALIAS_MAP`. Task 702 (in progress) renames `YearPoint.fleet_self_consumption_kwh` and `_NodeData.fleet_sc` inside `project_multi_year`.

## 1. Goal

How grid-services income is priced becomes one closed choice: no income, a flat rate per kW of battery discharge power, or capacity at events. Each choice is a frozen value that prices a simulated fleet with one method. `project_multi_year` asks it once per simulated age, so capacity-at-events income comes from that age's own aged fleet (D13). After the bump, `FinanceConfig.grid_services_model` holds the value itself. One table in `gridservices.py` holds every grid-services rate per uncertainty band, keyed by one band vocabulary.

What a user observes:

1. **Event income follows battery health.** Take a fleet whose battery state of charge scales with each aged battery's SOH. `project_multi_year` books each simulated age's own event figure, so revenue at age 24 carries about half the age-0 event income: battery SOH falls to 0.50–0.52 by age 24 under the default fade. Today the age-0 figure is booked at every age. The board model doc (`docs/cost-recovery-finance-model.md` §4, §8.1) gains the capacity-at-events equation, with a worked figure of £9.97 per kW of firm spare capacity per year in the central band. On the board scenario this moves no figure, because its event income is £0 at every age (§2.2).
2. **No inconsistent configuration is accepted.** These raise `ConfigurationError` at construction, so `finance run` and `optimize configs` exit 1 with `Configuration error:` before simulating:
   - `capacity_at_events` with no events configuration;
   - `capacity_at_events` with a non-zero flat rate;
   - `flat` with an events configuration.

   Today the first is constructed and later either refused (`--project`) or silently rendered with no events section (`finance run`). The other two are constructed and their extra field is ignored.
3. **No grid-services input is silently ignored.**
   - `optimize configs <events scenario> --grid-services-kw 20` is refused, naming the flag and the model. Today the override is ignored.
   - The default sensitivity panel on an events scenario omits the flat-rate axis with a printed line saying why. Today it sweeps a field the model never reads and reports the axis as rank-stable.
   - An event window the simulated period never enters is named in a warning. Today it is a silent £0.
4. **One band vocabulary, one rate table.**
   - `--flex-band medium`, a scenario `flex_band: medium` and an events `band: medium` are each refused with one message listing low, central and high.
   - `flex.FLEX_VALUE_BANDS` cannot be mutated.
   - The flat per-kW rates (1.5, 12, 48 £/kW-yr) that the flex report block and `optimize.SENSITIVITY_BANDS` show are read from `gridservices.GRID_SERVICES_RATE_BANDS`, beside the per-event rates.
5. **At the bump (held leaf ε).**
   - A scenario names its pricing once: `finance.grid_services_model: {type: capacity_at_events, …}` or `{type: flat, income_per_kw_per_year_gbp: …}`, and absent means none.
   - A file still carrying `grid_services_income_per_kw_per_year_gbp`, `grid_services_events` or a string `grid_services_model` is refused, naming the new location.
   - `FinanceConfig(grid_services_model="flat")` fails mypy --strict and raises at runtime.

## 2. Background (measured at 9d7b67e)

### 2.1 What exists today

- **One axis, three fields.** `FinanceConfig` encodes the pricing in three fields:
  - `grid_services_income_per_kw_per_year_gbp: float = 0.0`, meaningful only under flat;
  - `grid_services_model: str = "flat"`, checked against a local `_VALID_GS_MODELS`;
  - `grid_services_events: Optional[GridServicesEventsConfig] = None`, meaningful only under capacity_at_events.

  The field docstring admits the pair `capacity_at_events` + `None` ("α only validates the selector field").
- **Four sites read the selector string:**
  - `FinanceConfig.__post_init__`;
  - `project_multi_year`'s fail-fast guard, with a function-local `ConfigurationError` import;
  - `_simulate_age`'s string branch and `assert`;
  - `cli/finance.run`'s `== "capacity_at_events" and finance.grid_services_events is not None else None`, which silently drops the events section.
- **The memo.** The first `_simulate_age` call fills `_event_gs_memo`, through a function-local `from solar_challenge.gridservices import compute_grid_services_at_events`. Because seeds are built age 0 first, that call is age 0. Every seed and bisection-trial age then books that one figure. This is the briefing's known gap: `known_gaps[0]` of finance-economics.
- **Two tests pin the memo.** `test_compute_once_event_figure_reused_across_ages` and `test_compute_once_memo_reused_on_bisection_path` monkeypatch `gridservices.compute_grid_services_at_events` and assert `call_count == 1`. They pass only while the import stays function-local, so a layering fix that hoists it fails them.
- **Silent no-ops in optimize.**
  - `cli/optimize.configs --grid-services-kw` writes the flat field. Under capacity_at_events nothing reads it.
  - The `grid_services` sensitivity alias sweeps the same field through `optimize._build_axis_configs`. Under capacity_at_events every swept value prices identically, so the panel reports the axis as rank-stable.
- **The band vocabulary is written four times:**
  - `flex.FLEX_VALUE_BANDS` keys, with `resolve_flex_band`;
  - `GridServicesRateBands`' fields and `resolve`'s if-chain;
  - `GridServicesEventsConfig`'s local `_VALID_BANDS`;
  - `cli/finance.FlexBand`.
- **Two rate tables, unlinked.**
  - `flex.FLEX_VALUE_BANDS` is a mutable `dict` holding the flat 1.5, 12 and 48 £/kW-yr (provenance: consulting §1.1 + PRD §6).
  - `gridservices.GRID_SERVICES_RATE_BANDS` is frozen and holds 0.50, 1.00 and 2.00 £/kW/event and 30, 60 and 120 £/MWh.

  Only a comment ties them. With the defaults (`DEFAULT_EVENT_WINDOWS`, utilisation 0.6, aggregator share 0.25) the events bands net 4.99, 9.97 and 19.94 £ per kW of firm spare capacity per year. For central: (1.00 × 12 + 0.6 × 3 h × 0.060 £/kWh × 12) × 0.75 = 9.972.
- **Doc drift.**
  - The model doc's §4 and §8.1 give only the flat formula and never mention capacity_at_events.
  - `GridServicesAtEvents`' docstring calls the income "householder-side", but `project_multi_year` books it as CBS revenue.
  - `compute_fleet_spare_capacity_kw` skips a window the simulated index never enters, which is a silent £0.
  - `flex.REPRESENTATIVE_DISCHARGE_POWER_KW` points at a stale `config.py:264`; the default lives on `BatteryConfig.max_discharge_kw`.
- **Frozen surface.**
  - Frozen: `FinanceConfig`'s form (all three fields), `GridServicesRateBand`, `GridServicesRateBands.resolve(band: str)`, `resolve_grid_services_rate_band(band: str)`, `GridServicesEventsConfig(band: str = 'central', …)`, `GridServicesAtEvents`, `compute_grid_services_at_events` and `GRID_SERVICES_RATE_BANDS`.
  - `GridServicesEventsConfig` has no `FROZEN_MEMBERS` entry.
  - Not frozen: `project_multi_year`, `flex` and `optimize`.
- **Import closure.** In a fresh `-I` interpreter, `import solar_challenge.gridservices` loads only `battery` and `timebase` among package modules, and not pvlib (probed). So `finance` can import it at module top and keep S1's C7: constructing `FinanceConfig` loads neither `config` nor pvlib.
- **The platform consumer** is solar-challenge-platform, main `5fa0dfd`. `billing/config.py` builds `FinanceConfig` with defaults for every grid-services field. No platform source or test names those fields or imports from `solar_challenge.gridservices` or `solar_challenge.flex` (grep). So ε's break costs it no edit.

### 2.2 Board-scenario measurement (G6)

Probe: the first three battery homes of `scenarios/bristol-phase1-flex.yaml`, simulated with `simulate_fleet` over 2024-01-08..21, then priced with `compute_grid_services_at_events` and the scenario's own events configuration, at battery SOH 1.0 and 0.8.

| SOH | Annual income | Window spare capacity | Each home's minimum in-window SOC | Max in-window discharge |
|---|---|---|---|---|
| 1.0 | £0.000 | 0.0 kW | 0.5 kWh, its floor | 1.06–1.44 kW |
| 0.8 | £0.000 | 0.0 kW | 0.4 kWh, its floor | unchanged |

Firm spare energy is the minimum of (SOC − floor) over every in-window minute of the season. The TOU fleet reaches its floor inside 16:00–19:00. So the board scenario's event income is £0 today and stays £0 under D13: per-age pricing moves no board figure until the firmness definition or the dispatch changes (lead question 2).

D13's consequence names "more simulations per projection". Measured against the code, per-age pricing adds one reduction per simulated age and no simulation: `_simulate_age` already simulates each age. Bisection adds nodes only where per-age income bends the revenue curve. On the board scenario it does not, since the event income is flat at £0.

### 2.3 Tasks this PRD meets

- **704** (in merge, branch `task/704`). It moves the sensitivity values into `optimize.SENSITIVITY_BANDS` and derives its grid entry from `flex.resolve_grid_services_band`, which deletes the `(1.5, 12.0, 48.0)` literals. The CLI alias map then names knobs only. This closes fk-71b4ca35efe0, so S9 files no leaf for that key: at decompose, contract §8 step 1 finds 704. γ repoints the grid entry to the one table. β and ε change what the grid knob may do.
- **773, 774, 775** (S1 α, β, γ; pending): the errors leaf; `ConfigurationError ⊂ ValueError` and uniform raises in `GridServicesRateBand` and `FlexibilityValueBand`; the INV-5 import guard. α depends on 773. β and γ depend on 774. S1 §7 lists two of γ's Transitional allow-list entries as S9's: `finance → gridservices` (α deletes it) and `cli.finance → gridservices` (β deletes it).
- **702** (in progress) edits `_simulate_age`'s neighbourhood. The overlap with α is textual only.
- **616** (pending) is about event-window count coercion in `config._parse_event_windows`. ε's grammar move carries whichever form is at its base.

### 2.4 Freshness of the keys

All six keys were confirmed at `7dfea36`, and none is in D28's weakened list. Re-read at `9d7b67e`, every symbol their statements name is present as described: the memo, the guard, the branch and `assert`, the silent `None`, the flat-field override, `_VALID_BANDS`, the `resolve` if-chain, `FlexBand`, the mutable `FLEX_VALUE_BANDS`, the stale `config.py:264` pointer and the "householder-side" docstring. One key moves: fk-71b4ca35efe0's literals are gone on `task/704`.

## 3. Rulings and how this PRD reads them

- **D13, per age.** The stream row's "project_multi_year takes the age-0 fleet results (or a precomputed GridServicesAtEvents) as an input" is the option D13 rejected. Per-age pricing needs no new input, because `_simulate_age` already holds each age's `FleetResults`. So `project_multi_year`'s signature does not change. The memo and the function-local import go, and the compute-once tests become per-age tests that assert through the returned curve, with no module patch.
- **D13, closed selector type.** The final form is `grid_services_model: GridServicesModel`, where `GridServicesModel = NoGridServices | FlatGridServices | GridServicesEventsConfig`. This is the stream row's "none | flat band | capacity_at_events(config)". The two fields that each mean something under one choice only are retired.
- **D29.**
  - Held: retiring `grid_services_income_per_kw_per_year_gbp` and `grid_services_events`, and the `str` form of `grid_services_model`, are retirements. They form the held leaf ε, together with the scenario-grammar keys that name them.
  - In-leaf, each with an Unreleased line: `GridServicesEventsConfig.annual_income_gbp` (α) and `GridServicesRateBand.flat_gbp_per_kw_per_year` (γ) are additive.
  - In-leaf without a frozen-table edit: β's refusals change no form. They take an Unreleased line, as task 374's did.
- **D4.** No shim or dual field survives the bump. The transitional `finance.grid_services_model_of` lives from α to ε, and ε deletes it. It is outside `__all__`, so it never enters the frozen tables.
- **L5.** β's refusals raise `errors.ConfigurationError` and depend on S1-β (774). α raises only today's refusal, moved, and depends on S1-α (773) for the top-level import.

## 4. Sketch of approach

1. **α — Price per age through one mechanism.**
   - `gridservices` gains `NoGridServices` and `FlatGridServices`, and `GridServicesEventsConfig` gains `annual_income_gbp(fleet_results)`. Each pricing value prices a simulated fleet.
   - `finance.grid_services_model_of(finance)` maps today's three fields to the value.
   - `project_multi_year` resolves the value once, before simulating, and `_simulate_age` books `pricing.annual_income_gbp(fleet_results)` for the fleet it just simulated.
   - The import moves to module top. The memo, guard, string branch, `assert` and the two monkeypatching tests go, replaced by per-age tests.
   - The model doc gets its equation, the docstring its CBS wording, and an unobserved window its warning.
2. **β — Close the triple at construction.**
   - `FinanceConfig.__post_init__` calls `grid_services_model_of(self)`, which now refuses all three inconsistent combinations and replaces `_VALID_GS_MODELS`.
   - `cli/finance` renders the events breakdown when the value is an events configuration, with no silent `None` and no function-local import.
   - `cli/optimize` refuses a flat override under the events model and drops the flat axis from its defaults there, with a printed line.
   - The board scenario file loses its inert flat rate.
3. **γ — One band vocabulary, one rate table.**
   - `gridservices.GridServicesBand` is the one vocabulary, and `GRID_SERVICES_RATE_BANDS` rows gain the flat per-kW-year rate.
   - flex, `optimize.SENSITIVITY_BANDS` and `cli/finance` read both from there. `FLEX_VALUE_BANDS` is frozen.
   - The model doc states that the flat and events calibrations are independent.
4. **ε (held for S29) — The field holds the model.**
   - `FinanceConfig.grid_services_model: GridServicesModel = NoGridServices()`. The two fields and the transitional function are retired.
   - The scenario grammar reads one typed `grid_services_model:` block, and the two scenario files migrate.
   - The band annotations become `GridServicesBand`.

## 5. Contract

### 5.1 Pricing values (`gridservices.py`; α adds, ε exports)

```python
@dataclass(frozen=True)
class NoGridServices:
    def annual_income_gbp(self, fleet_results: FleetResults) -> float: ...   # 0.0

@dataclass(frozen=True)
class FlatGridServices:
    income_per_kw_per_year_gbp: float      # > 0 and finite, else ConfigurationError; zero income is NoGridServices()
    def annual_income_gbp(self, fleet_results: FleetResults) -> float: ...
        # income_per_kw_per_year_gbp × Σ battery_config.max_discharge_kw over fleet_results.home_configs with a battery

class GridServicesEventsConfig:            # existing, frozen; gains (additive, FROZEN_MEMBERS)
    def annual_income_gbp(self, fleet_results: FleetResults) -> float: ...
        # compute_grid_services_at_events(fleet_results, self).annual_income_gbp

GridServicesModel: TypeAlias = NoGridServices | FlatGridServices | GridServicesEventsConfig
```

- **Pure.** Each method reads only its value and the `FleetResults` it is given and keeps no state between calls.
- **Annual, finite, non-negative.** Each result is £ per year by construction.
- **Flat equals today's figure.** `_aged_homes` replaces only `pv_config.system_age_years` and `battery_config.soh`, so `max_discharge_kw` is the same on the aged and the scenario homes.

### 5.2 `FinanceConfig`'s grid-services choice

**Transitional rule (α creates, β extends and calls from `__post_init__`, ε deletes):** `finance.grid_services_model_of(finance: FinanceConfig) -> GridServicesModel`. It is a public name in `finance.py`, outside `__all__`, so it is not frozen. One function is both the validator and the reader's accessor.

| `grid_services_model` | flat rate | events | α (called by `project_multi_year` before any simulation) | β (called by `__post_init__`) |
|---|---|---|---|---|
| `"flat"` | 0 | None | `NoGridServices()` | same |
| `"flat"` | r > 0 | None | `FlatGridServices(r)` | same |
| `"flat"` | any | set | flat value; events ignored (today) | **refused**: an events configuration under the flat model |
| `"capacity_at_events"` | 0 | set | the events configuration | same |
| `"capacity_at_events"` | r > 0 | set | the events configuration; rate ignored (today) | **refused**: a flat rate under the events model |
| `"capacity_at_events"` | any | None | refused, today's message, before any simulation | refused at construction |
| anything else | — | — | refused by `__post_init__` (today) | refused by the rule, naming `flat` and `capacity_at_events` |

Each refusal names the fields involved and their values.

**Final form (ε):**
- `grid_services_model: GridServicesModel = NoGridServices()`.
- `grid_services_income_per_kw_per_year_gbp` and `grid_services_events` are retired.
- `__post_init__` refuses a value that is none of the three types, naming them. This is the runtime guard for an untyped caller passing `"flat"`; mypy --strict refuses it statically.

### 5.3 `project_multi_year` (α)

- `pricing = grid_services_model_of(finance)` runs before any simulation, which keeps today's fail-fast.
- `_simulate_age` books `pricing.annual_income_gbp(fleet_results)` from the fleet it has just simulated, at every seed and bisection-trial age. No state outlives the call.
- `finance.py` imports gridservices at module top. The `TYPE_CHECKING` import of `GridServicesEventsConfig` becomes a runtime import.
- **The figure is annual by construction.** Neither today's `_annualisation_scale` nor S10's `SimulationWindow` multiplies it.
- **The solve's affine premise still holds.** `solve_cost_recovery_rate` relies on revenue being affine in the own-use rate. Income depends on the simulated fleet only, never on the own-use rate, and is ≥ 0.

### 5.4 Unobserved event window (α)

- **Warning.** `compute_grid_services_at_events` emits one `UserWarning` per call for each window with no timestep in the fleet's simulated index. It names the window's months, weekdays and hours, and the index's first and last timestamp.
- **Figure unchanged.** That window still contributes £0.
- **No warning without batteries.** A fleet with no battery home does not warn, because its £0 means no batteries.
- **Repeats are collapsed.** Under per-age pricing the same text repeats once per simulated age, and Python's default filter shows it once.

### 5.5 Band vocabulary and rate table (γ)

```python
class GridServicesBand(str, Enum):
    LOW = "low"; CENTRAL = "central"; HIGH = "high"
    @classmethod
    def parse(cls, value: object, *, what: str) -> "GridServicesBand": ...
        # ConfigurationError: "<what> must be one of low, central, high, got <value!r>"

@dataclass(frozen=True)
class GridServicesRateBand:                # frozen; gains a last field (additive)
    availability_gbp_per_kw_per_event: float
    utilisation_gbp_per_mwh: float
    provenance: str = ""
    flat_gbp_per_kw_per_year: float = 0.0  # >= 0 and finite
```

- **The table.** `GRID_SERVICES_RATE_BANDS` rows are:
  - low: 0.50 £/kW/event, 30 £/MWh, flat 1.5 £/kW-yr;
  - central: 1.00, 60, flat 12.0;
  - high: 2.00, 120, flat 48.0.

  `provenance` names both sources. `GridServicesRateBands.resolve` reads through `GridServicesBand.parse` and has no if-chain.
- **Readers of the vocabulary.**
  - `GridServicesEventsConfig.__post_init__` (`_VALID_BANDS` goes).
  - flex: `FLEX_VALUE_BANDS` becomes a `MappingProxyType` keyed by `GridServicesBand`, and its `grid_services_per_kw_gbp` comes from the table. `resolve_flex_band` parses. `resolve_grid_services_band` is deleted, because after γ it has no src caller.
  - `optimize.SENSITIVITY_BANDS`: its grid entry is the table's flat column in band order.
  - `cli/finance`: `--flex-band` is typed `GridServicesBand` (`FlexBand` goes), and the scenario `flex_band` key is parsed through it.
- **Calibrations.** Flat and events rates are independent calibrations of the same three bands. The model doc states this beside the measured per-kW-firm figures (§2.1). No number changes.

### 5.6 CLI surfaces (β)

- **`finance run`.**
  - `grid_services_at_events` is the breakdown when the pricing is a `GridServicesEventsConfig`, else `None`.
  - gridservices is imported at module top.
  - Nothing is conjoined with `is not None`.
- **`optimize configs --grid-services-kw`.** Under the events model it is refused before any simulation, naming the flag and the model.
- **`optimize configs --sensitivity`.**
  - Omitted, the default is retained_floor plus grid_services when the pricing is none or flat.
  - Under the events model the default is retained_floor only, with a printed line naming the omitted grid_services axis and why.
  - An explicit `--sensitivity` naming grid_services under the events model is refused before any simulation.
- **`optimize._build_axis_configs`.** Rebuilding a `FinanceConfig` with a flat rate under the events model raises β's refusal, so library callers of `sensitivity_panel` get it too.

### 5.7 Scenario grammar (ε)

```yaml
finance:
  grid_services_model:            # absent or null: NoGridServices()
    type: flat
    income_per_kw_per_year_gbp: 12.0
---
finance:
  grid_services_model:
    type: capacity_at_events      # the other keys are GridServicesEventsConfig's fields, each defaulting as declared
    band: central
    event_windows: [...]
```

- **Tag.** The block is tagged by `type:` through the grammar's `_BlockType` table: `config.py` today, `scenario_blocks.py` after S5.
- **Legacy keys.** `grid_services_income_per_kw_per_year_gbp`, `grid_services_events` and a string `grid_services_model` are each refused, naming `finance.grid_services_model` and the form to write.
- **Migration.** `scenarios/bristol-phase1.yaml` drops its flat 0.0. `scenarios/bristol-phase1-flex.yaml` moves its events block under `grid_services_model`.
- **Before ε**, the grammar is unchanged. From β on, a file carrying an inconsistent combination fails at load, naming the fields.

### 5.8 Surface ledger for S29 (D4)

| Leaf | Frozen-surface or model change | Release-note text and consumer action |
|---|---|---|
| α | `GridServicesEventsConfig` gains `annual_income_gbp` (`FROZEN_MEMBERS`) | additive; Unreleased line in `docs/domain-library-consumption.md` |
| α | `compute_grid_services_at_events` warns on an unobserved window | Unreleased line |
| α | `project_multi_year` prices capacity-at-events income per simulated age | the model doc's header Unreleased line (that doc's own convention) |
| β | `FinanceConfig` refuses the three inconsistent combinations | Unreleased line; consumers fix such inputs at re-pin |
| γ | `GridServicesRateBand` gains a last field, `flat_gbp_per_kw_per_year` (default 0.0); band refusals share one message; `GridServicesRateBands.resolve` raises `ConfigurationError`, a `ValueError` | Unreleased line |
| ε (held) | `FinanceConfig.grid_services_model: GridServicesModel = NoGridServices()`; the two fields retired; `NoGridServices`, `FlatGridServices` and `GridServicesBand` in `__all__`; `GridServicesEventsConfig.band: GridServicesBand`; `resolve` and `resolve_grid_services_rate_band` take `GridServicesBand` | Build the value: `FlatGridServices(r)`, or pass the events configuration itself. The platform needs no edit (measured). Scenario files move their keys. String band literals still work at runtime, through the str-mixin enum. |

### 5.9 Invariants

| # | Invariant | Enforced by |
|---|---|---|
| C1 | Per simulated age, income = `pricing.annual_income_gbp(that age's FleetResults)`; no state outlives a `_simulate_age` call | α's per-age tests (§9 C1, C2), through the curve, with no patch |
| C2 | Every pricing value's income is finite and ≥ 0, and annual by construction, so no window scale multiplies it | the values' validation; α's tests; S10 cross-reference |
| C3 | A `FinanceConfig` cannot hold (β), then cannot represent (ε), an inconsistent grid-services choice | β's rule; ε's type |
| C4 | No input to the pricing is silently ignored | β (constructor, `--grid-services-kw`, sensitivity axis); α (an unobserved window warns) |
| C5 | One band vocabulary: every band read parses through `GridServicesBand`, with one message | γ |
| C6 | One rate table: every grid-services rate per band lives in `GRID_SERVICES_RATE_BANDS`, and flex, `SENSITIVITY_BANDS` and the report read it | γ's equality tests |
| C7 | `finance.py` and `cli/finance.py` import gridservices at module top | α, β; S1-γ's guard |
| C8 | Importing finance or constructing `FinanceConfig` loads neither `config` nor pvlib (S1's C7 kept) | probe at 9d7b67e; S1-α's test |

## 6. Resolved design decisions

1. **Per age, with no new input (D13).** Each simulated age already has its fleet. Reusing the CLI's or the solve's own simulations is a different saving with a different owner (§11).
2. **The values price themselves.** One method, `annual_income_gbp(fleet_results)`, means no consumer branches on the model to price it. `cli/finance` branches only to render the events breakdown, which only one value has.
3. **`GridServicesEventsConfig` is the events value**, gaining the method, not a wrapper around it. That avoids a one-field wrapper type and a rename.
4. **`NoGridServices` is its own value, and `FlatGridServices` requires a positive rate.** Zero income has one spelling, and today's default `("flat", 0.0, None)` maps to it.
5. **Flat prices the simulated fleet's installed discharge power**, read from `fleet_results.home_configs`, so every value has the same input. This equals today's sum over the scenario homes (§5.1). The flat-model regression tests guard it.
6. **The transitional accessor is a function, not a property.** A property would be a `FROZEN_MEMBERS` addition that ε then retires: frozen-table churn and an Unreleased line for a name that never ships in a tag. The function sits outside `__all__`.
7. **β refuses rather than ignores** all three inconsistent combinations. This follows the program's direction (D3, D10, D17), and the platform never sets these fields.
8. **An unobserved window warns, as the finding proposes.** A structured marking would join S10's extrapolation marking in S25's report sections. That is out of scope here, and the warning carries the window and the period meanwhile.
9. **The grid-services sensitivity axis stays a flat-rate axis.** Under the events model it leaves the default set with a printed line, and is refused when asked for explicitly. A meaningful events axis would sweep the band, which is a new, band-valued knob. That is S26's registry's to host (lead question 3).
10. **One table holds both calibrations, declared independent, with no number changes.** The finding allowed deriving the events defaults from the flat bands instead. That would move the low and high event figures with no calibration basis, while both bands are already marked provisional (enhanced-grid-services PRD open-Q2).
11. **The band vocabulary lives in gridservices.** flex then imports gridservices, which loads battery, timebase and pandas, all already loaded where flex is used, and not pvlib.
12. **ε is one held leaf.** It holds the type, the retired fields, the grammar, the scenario files and the band annotations: one release's break, sharing `finance.py`, `gridservices.py`, the grammar and the same tests.

## 7. Pre-conditions

- **α:** S1-α (773).
- **β:** α and S1-β (774).
- **γ:** S1-β (774) and task 704 merged.
- **ε:** β, γ and S29's bump window (`x_seam_wait`).

No substrate has to be built first. §G3 of the gate record lists what was verified.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 Errors leaf (773–775) | consumes / shrinks | `errors.ConfigurationError` for the rule and `FlatGridServices`; α and β delete their γ allow-list entries if 775 has landed | S1 | declared (L5) |
| S8 Finance partition | consumed by | `project_multi_year` and `FinanceConfig` change shape here first; S8's move carries `grid_services_model_of` (until ε) and the per-age call | S9 (α, β) | **proposed:** S8's move leaf depends on S9 α and β |
| S10 Window | shares | `_simulate_age` (textual); the grid-services term is annual by construction, so the window scale never multiplies it (C2) | S10 owns the window; S9 owns C2 | note only |
| S25 Board reports | consumed by | `cli/finance.run`'s events breakdown, read from the pricing value (β); `--flex-band` typed `GridServicesBand` (γ); per-mode rendering stays S25's | S9 (β, γ) | **proposed:** S25's `cli/finance` leaf depends on S9 β and γ |
| S26 Knob registry | consumed by | the grid-services knob's meaning: a flat rate, refused under the events model (β); builds `FlatGridServices(v)` (ε); an events-band knob would be new (lead question 3) | S9 owns the meaning; S26 hosts it | **proposed** cross-reference; ε edits the registry entry if S26 has landed |
| S2 Dispatch configuration | touches | S2 δ edits one line of `compute_fleet_spare_capacity_kw` (`soc_envelope`) | S2 | file overlap only |
| S4 Finite quantities | touches | `FlatGridServices`, the new rate-band field and flex's bands use the finite checker once it lands; until then, today's idiom | S4 | file overlap only |
| S5 Scenario grammar | touches | ε's typed block lives wherever `_BlockType` and `parse_finance_config` sit at ε's base | S5 layout; S9 grammar | ε follows S5 by time |
| S23 Surface lock | touches | α, γ and ε edit `FROZEN_*` entries; whichever lands second adapts | S23 | note only |
| S29 Surface bump | produces for | the §5.8 ledger; ε held for S29's window | S29 | ε held |
| Task 704 | consumes | `optimize.SENSITIVITY_BANDS` (γ repoints its grid entry) | 704 | in merge |

## 9. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer | each value prices a fleet | synthetic `FleetResults`: two battery homes (2.5 and 3.0 kW discharge) and one PV-only home | `NoGridServices` → 0.0; `FlatGridServices(12.0)` → 66.0; events → `compute_grid_services_at_events(...).annual_income_gbp` | α |
| P2 | producer | worked figure | one 5 kWh default battery home, a full-year index, SOC 3.5 kWh and discharge 0.5 kW constant (spare = min(2.0, 3.0 / 3) = 1.0 kW) | central `GridServicesEventsConfig()` → £9.972 (±1e-9); low → 4.986; high → 19.944; the doc's worked figure matches | α |
| P3 | producer | unobserved window | June-only index, default winter window | one `UserWarning` naming months (11, 12, 1, 2) and the index span; income 0.0; a fleet with no battery home does not warn | α |
| P4 | producer | one vocabulary | — | `GridServicesEventsConfig(band="medium")`, `GRID_SERVICES_RATE_BANDS.resolve("medium")` and `resolve_flex_band("medium")` all raise `ConfigurationError` containing `must be one of low, central, high` | γ |
| P5 | producer | one table | — | for each band, `FLEX_VALUE_BANDS[b].grid_services_per_kw_gbp == GRID_SERVICES_RATE_BANDS.resolve(b).flat_gbp_per_kw_per_year`; `SENSITIVITY_BANDS`' grid entry is that column in band order; item assignment on `FLEX_VALUE_BANDS` raises `TypeError` | γ |
| C1 | consumer: projection | per-age events | board scenario homes; an energy-constant fake simulator whose battery SOC is 0.8 × capacity × each aged home's `battery_config.soh`, so the `NoGridServices` curve is exactly flat; events model vs `NoGridServices` | for every age a in the events curve's `sampled_ages`, `events.points[a].fleet_revenue_gbp − none.points[a].fleet_revenue_gbp` equals `compute_grid_services_at_events` of that age's simulated fleet (approx); the age-24 figure < the age-0 figure (RED today: every age books the age-0 figure) | α |
| C2 | consumer: projection | bisection path | the C1 fake, tuned so event income dominates revenue. SOH's kink at the 0.5 floor then puts the PCHIP midpoint off by more than 1% (§G6), and bisection adds trial ages | `len(sampled_ages) > 3`, and every trial age satisfies C1's equality | α |
| C3 | consumer: projection | flat unchanged | the existing flat-model tests (`test_flex_grid_services`, B4's flat half) | YearPoints identical to before α | α |
| C4 | consumer: solve | affine premise | the existing B5 I4 rate-independence test, with the events model | still passes under per-age pricing | α |
| C5 | consumer: library | construction refusals | — | the three combinations of §5.2 raise `ConfigurationError` naming the fields (RED today: they construct); `pytest.raises(ValueError)` catches them | β |
| C6 | consumer: CLI | events without configuration | a scenario with `grid_services_model: capacity_at_events` and no `grid_services_events`; a simulator that fails the test if called | `finance run` exits 1 with `Configuration error:` naming `grid_services_events` (RED today: exit 0, no events section) | β |
| C7 | consumer: CLI | flat override under events | the flex scenario; `--grid-services-kw 20`; a simulator that fails if called | exit 1, stderr names `--grid-services-kw` and `capacity_at_events` (RED today: runs) | β |
| C8 | consumer: CLI | sensitivity default under events | the flex scenario via `invoke_cli`, with a fake giving a feasible baseline | stdout carries the omission line; the ranking report has no grid-services axis; `--sensitivity grid_services` exits 1 before simulating | β |
| C9 | consumer: CLI | events breakdown | the existing ε test (`finance run --flex-band central` on the flex scenario) | still renders "Grid services (capacity-at-events)" from the pricing value | β |
| C10 | consumer: CLI | band entry points | `finance run s.yaml --flex-band medium`; a scenario with `flex_band: medium` | Typer's choice error lists low, central, high; the scenario key gives `Configuration error:` with the same list (today `Invalid value: Unknown flexibility band …`) | γ |
| C11 | grammar | migrated files | both migrated scenario files; their pre-migration copies | each migrated file loads to the same `FinanceConfig` meaning, and a constant-fake projection is identical; each legacy key is refused naming `finance.grid_services_model` | ε |
| C12 | surface | the field holds the model | — | `FinanceConfig(standing_charge_pence_per_day=60, grid_services_model="flat")` raises naming the three types; `FROZEN_SURFACE`'s `FinanceConfig` form names `grid_services_model` and neither retired field | ε |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries:

- `x_finding_key`;
- `x_finding_run = review-all-solar_challenge-20261013`;
- `source = review-all`;
- `priority`, the highest severity among its keys;
- file-level `metadata.files`.

No leaf is high or critical, so none joins trigger-chain gate 772.

**α — Grid-services income per simulated age, through one pricing method** (leaf; priority medium; keys fk-758b2f309cab, fk-4ddab794283a)

- **Modules:**
  - `src/solar_challenge/gridservices.py`: `NoGridServices`, `FlatGridServices`, `GridServicesEventsConfig.annual_income_gbp`, the `GridServicesModel` alias, the unobserved-window warning and the CBS wording in `GridServicesAtEvents`' docstring;
  - `src/solar_challenge/finance.py`: the top-level import, `grid_services_model_of` and `project_multi_year`;
  - `tests/integration/test_grid_services_events.py`: delete the two monkeypatching tests; add C1 and C2, P1–P3;
  - `tests/unit/test_gridservices.py`;
  - `tests/unit/test_public_api_surface.py`: the `FROZEN_MEMBERS` entry for `GridServicesEventsConfig`;
  - `docs/cost-recovery-finance-model.md`: the §4 and §8.1 equation, the worked £9.97, and a header Unreleased line;
  - `docs/domain-library-consumption.md`: an Unreleased line naming `annual_income_gbp` and the warning.
- **Work:** §5.1, §5.2 (α column), §5.3 and §5.4. Delete:
  - `_event_gs_memo`;
  - the function-local `compute_grid_services_at_events` import;
  - the "Fail-fast" guard block, whose refusal moves into `grid_services_model_of`, still called before any simulation;
  - `_simulate_age`'s string branch and `assert`;
  - the two monkeypatching tests.

  If S1-γ (775) has landed, delete its `finance → gridservices` allow-list entry. Record on the task the board probe of §2.2, re-run at α's base: event income at ages 0 and 24.
- **Signal (user-observable):**
  - Through the public projection API, which `finance run --project`, `--cost-recovery` and `optimize` consume, on the SOH-tracking fleet fixture (§9 C1, C2): each sampled age's revenue carries that age's own event figure, and the age-24 figure is about half the age-0 figure. RED today: equal at every age.
  - The model doc's §4 states the capacity-at-events term, with £9.97 per kW of firm spare capacity per year in the central band (P2).
  - A June-only run of an events scenario prints a warning naming the winter window.
  - `grep _event_gs_memo` and `monkeypatch.setattr(gs_module` find nothing.
  - The board figures do not move; the task records the measurement.
- **Consumer:** board readers of the projection, through `finance run --project` and `--cost-recovery` and `optimize configs`; β; ε; S8's move.
- **Prereqs:** S1-α (773).

**β — FinanceConfig refuses an inconsistent grid-services choice; no CLI ignores one** (leaf; priority medium; keys fk-aafe32daa988, fk-d432a549b03f)

- **Modules:**
  - `src/solar_challenge/finance.py`: `__post_init__` calls `grid_services_model_of(self)`; the rule's β refusals; delete `_VALID_GS_MODELS`;
  - `src/solar_challenge/cli/finance.py`: breakdown from the pricing value; top-level import;
  - `src/solar_challenge/cli/optimize.py`: the `--grid-services-kw` refusal; `--sensitivity` default `None` resolved per model;
  - `scenarios/bristol-phase1-flex.yaml`: drop the inert flat 12.0 and its comment;
  - tests: `tests/unit/config/test_finance_block.py`, where `test_capacity_at_events_without_config_ok` flips, and every case that parses an events block under the default flat model adds `grid_services_model: capacity_at_events`; `tests/unit/config/test_unrecognised_keys.py`, likewise; `tests/integration/test_grid_services_events.py`, where the guard test becomes construction-time and B4's "flat with events attached" becomes a refusal; `tests/integration/test_flex_grid_services.py`, where the board test asserts the events model and band instead of the flat field; `tests/integration/test_optimize_cli.py`; `tests/integration/test_optimize_sensitivity.py`;
  - `docs/domain-library-consumption.md`: an Unreleased line naming the three refused combinations and `capacity_at_events`.
- **Work:** §5.2 (β column) and §5.6. If 775 has landed, delete its `cli.finance → gridservices` allow-list entry.
- **Signal (user-observable):**
  - C6: `finance run` on `capacity_at_events` without an events block exits 1 with `Configuration error:` before simulating. Today it exits 0 with no events section.
  - C7: `optimize configs <flex scenario> --grid-services-kw 20` exits 1 naming the flag and `capacity_at_events`.
  - C8: the default sensitivity panel on the flex scenario prints the omission line and has no grid-services axis.
  - C5: `FinanceConfig(standing_charge_pence_per_day=60, grid_services_model="capacity_at_events")` raises. Today it constructs, as the finding measured.
- **Consumer:** CLI users (finance, optimize); library constructors of `FinanceConfig`; S25; S26; ε.
- **Prereqs:** α; S1-β (774).

**γ — One band vocabulary and one grid-services rate table** (leaf; priority medium; keys fk-0f24b7f66eb2, fk-aafe32daa988)

- **Modules:**
  - `src/solar_challenge/gridservices.py`: `GridServicesBand`, the rate-band field and table, `resolve`, and `GridServicesEventsConfig`'s band check;
  - `src/solar_challenge/flex.py`: frozen `FLEX_VALUE_BANDS` read from the table; `resolve_flex_band`; delete `resolve_grid_services_band`; the `BatteryConfig.max_discharge_kw` pointer;
  - `src/solar_challenge/optimize.py`: `SENSITIVITY_BANDS`' grid entry;
  - `src/solar_challenge/cli/finance.py`: `FlexBand` → `GridServicesBand`; the scenario key parsed;
  - tests: `tests/unit/test_gridservices.py`, `tests/unit/test_flex.py`, `tests/integration/test_flex_grid_services.py`, `tests/integration/test_finance_flex_cli.py`, the task-704 module `tests/unit/test_optimize_sensitivity_bands.py`, and `tests/unit/test_public_api_surface.py` (`GridServicesRateBand`'s form);
  - docs: `docs/cost-recovery-finance-model.md` §8.1 (the "independent calibrations" statement beside 4.99, 9.97 and 19.94 vs 1.5, 12 and 48), `docs/flexibility-buildability.md`, and `docs/domain-library-consumption.md` (Unreleased line).
- **Work:** §5.5.
- **Signal (user-observable):**
  - C10: the scenario key `flex_band: medium` and an events `band: medium` both give `Configuration error: … must be one of low, central, high, got 'medium'`. Today these are two different messages and labels. `--flex-band medium` lists the same three.
  - `finance run --flex-band high` still renders `£48.0/kW-discharge/yr`, now read from `GRID_SERVICES_RATE_BANDS`.
  - Assigning to `FLEX_VALUE_BANDS` raises `TypeError`.
  - P5's equalities hold.
- **Consumer:** CLI users (`--flex-band`, scenario `flex_band`, events `band`); `optimize.SENSITIVITY_BANDS` (704) and the W3 sensitivity panel; ε.
- **Prereqs:** S1-β (774); task 704.

**ε — FinanceConfig.grid_services_model holds the pricing model; the scenario names it once** (held leaf; priority medium; keys fk-aafe32daa988, fk-d432a549b03f; `metadata.x_seam_wait = {stream: "S29", contract: "surface bump window open"}`; excluded from this batch's `commit_planning`)

- **Modules:**
  - `finance.py`: the field type, the two fields retired, `grid_services_model_of` deleted and its readers repointed;
  - `gridservices.py`: band annotations typed `GridServicesBand`;
  - `__init__.py`: exports `NoGridServices`, `FlatGridServices` and `GridServicesBand`;
  - the finance grammar (`config.py`, or `scenario_blocks.py` after S5): the typed block and the legacy-key refusals;
  - `cli/finance.py`, `cli/optimize.py`, and the grid-services knob in `optimize.py` or S26's registry;
  - both scenario files;
  - every test constructing the retired fields (about 100 sites in 12 files at 9d7b67e);
  - `tests/unit/test_public_api_surface.py` (`FROZEN_SURFACE`, `EXPECTED_KIND`).
- **Work:** §5.2 (final form), §5.7, and §5.8's ε row, which feeds S29's release section.
- **Signal (user-observable):** C11 and C12.
  - `finance run scenarios/bristol-phase1-flex.yaml` runs from the migrated file with unchanged figures.
  - A file with `grid_services_events:` is refused, naming `finance.grid_services_model`.
  - `FinanceConfig(grid_services_model="flat")` is a mypy --strict error and a runtime refusal.
- **Consumer:** scenario authors; library constructors; S29's release section; the platform re-pin, which needs no edit.
- **Prereqs:** β; γ; S29 releases it.

**DAG:** S1-α → α → β; S1-β → β; S1-β, 704 → γ; {β, γ} → ε (held). The intra-batch edges are β→α and ε→β, ε→γ. The out-of-batch edges are α→773, β→774, γ→774 and γ→704.

**G7** is advisory, because this repo has no `docs/legibility/design-invariants.md`. Screened against dark-factory's trigger shapes:

- `no-silent-fail-soft`: β removes four silent paths, and α adds a warning where £0 was silent.
- `no-lockstep-duplication` and `one-fact-one-home`: γ collapses four vocabularies and two tables into one.
- `guards-exercise-behaviour`: the compute-once tests that asserted an import's placement become per-age behaviour tests.
- `holds-owned-and-bounded`: the transitional `grid_services_model_of` is owned by ε, with a named bound (S29).

No hit.

## 11. Out of scope

- **Re-simulation counts.** fk-4ddab794283a measured four age-0 fleet simulations per `finance run --project --cost-recovery`: the CLI's bill run, `project_multi_year`'s age 0, the solve's inner projection, and the solve's outlay run. D13 makes the figure per-age, so no age-0 input is needed and S9 does not change the count. Reusing simulations across the CLI, projection and solve belongs with S8 (the projection module surfacing per-age results; `solve_cost_recovery_rate`'s "Cost note") or S16 (the runner) (lead question 4).
- **The firmness definition and the rate calibration.** These are what make the board's event income £0 (§2.2), and are a modelling decision (lead question 2).
- **A band-valued sensitivity knob for the events model** (S26; lead question 3).
- **Report sections per assumption mode, and where events income renders** (S25).
- **`GridServicesAtEvents`' unenforced sum invariant** (fk-f4d53977c642, left open as weakened; not this stream's key).
- **Finite-number checks** in gridservices and flex (S4), **prose rehoming** in finance.py and the model doc (S8), and **event-window count coercion** (task 616).
- **Deriving the events band defaults from the flat bands** (§6 decision 10).

## 12. Open questions

**For the lead** (cross-stream; S9's design holds whichever way each goes):

1. **ε held.** D29 classes ε's work as retirements: two fields, the `str` form of `grid_services_model`, and the legacy scenario keys. So ε waits for S29, and `finance.grid_services_model_of` carries the closed choice from α to ε. The platform constructs `FinanceConfig` with grid-services defaults only (measured), so landing ε in-leaf would cost it nothing. D29 still says retirements are held. **Default:** held.
2. **The board scenario's event income is £0** (§2.2). Firm spare energy is the season's minimum of SOC above the floor, and the TOU fleet reaches the floor inside the window. So D13 moves no board figure today. **Recommendation:** file a finance-economics modelling follow-up on the firmness definition, for example a per-event or per-day minimum averaged over event days. It is not S9's, and the board should know its events model currently prices nothing.
3. **Grid-services sensitivity under the events model.** β drops the flat-rate axis from the default panel there, with a printed line, and refuses it when asked for. A meaningful events axis would sweep `GridServicesBand`: a band-valued knob S26's registry could host. **Recommendation:** a cross-reference line on S26, not an S9 leaf.
4. **Owner for the four age-0 simulations** (§11): S8 (the projection surfaces per-age results to the solve and the CLI) or S16 (the runner).

**Tactical** (decide in the leaf):

1. ε: whether `type: none` is accepted as well as an absent block.
2. ε: whether `{type: flat, band: central}` resolves through the table. The default is no: it is a new feature, and the scenario states the rate.
3. γ: whether `FlexibilityValueBand.grid_services_per_kw_gbp` stays a field filled from the table or becomes a property reading it.
4. α: where the unobserved-window check sits, `compute_grid_services_at_events` or `compute_fleet_spare_capacity_kw`. The contract fixes the observable, not the site.
5. β: whether `cli/optimize` writes its own message naming `--grid-services-kw` or lets the rule's message through with the flag added. C7 pins that both the flag and the model are named.
6. ε: the sensitivity knob's identifier once the field is gone. S26's registry decides if it has landed.

## 13. Proposed cross-reference lines (for the lead to apply)

- **S1:** "`cli.finance → gridservices` (γ's Transitional allow-list entry) is owned by S9 β. `finance → gridservices` is S9 α's. Each deletes its entry if 775 has landed."
- **S8:** "The `project_multi_year` move leaf depends on S9 α and β. It carries `grid_services_model_of` until S9 ε deletes it, and the per-age `pricing.annual_income_gbp` call. finance.py:1606's import is already gone (S9 α)."
- **S10:** "The grid-services term is annual by construction (S9 §5.3, C2). `SimulationWindow`'s scale multiplies energy and SEG, never it."
- **S25:** "The `cli/finance.run` restructure depends on S9 β (the events breakdown comes from the pricing value; no silent `None`) and γ (`--flex-band` typed `gridservices.GridServicesBand`). Per-mode rendering of events income stays S25's."
- **S26:** "The grid-services knob means a flat rate: refused under the events model (S9 β), building `FlatGridServices(v)` at S9 ε. A band-valued events knob is a new registry entry (S9 lead question 3)."
- **S29:** "The release section includes S9 §5.8. S9 ε is a held leaf released in the bump window."

## Gate record

- **G1:** every mechanism has a named consumer.
  - The pricing values: `project_multi_year`, consumed by `finance run --project` and `--cost-recovery` and `optimize`; `cli/finance`'s report; ε's field.
  - `grid_services_model_of`: `FinanceConfig.__post_init__`, `project_multi_year` and `cli/finance`.
  - `GridServicesBand` and the table: flex, `cli/finance`'s `--flex-band`, `GridServicesEventsConfig` and `optimize.SENSITIVITY_BANDS`.
  - The warning: the operator running a mis-windowed scenario.
  - ε's grammar: scenario authors.

  No orphan producer.
- **G3:** the substrate exists and was verified at 9d7b67e.
  - `_simulate_age` holds each age's `FleetResults`.
  - `_aged_homes` sets battery `soh` per age, which `Battery.min_soc_kwh` reads.
  - `compute_soh` with the default 0.02/yr calendar fade gives at most 0.52 at age 24. Cycle fade from the fixture's discharge takes it to the 0.5 floor.
  - `tests/_cli_fleet_simulator.invoke_cli` takes a simulator callable.
  - The `_BlockType` `type:` grammar exists (`_TARIFF_TYPES`).
  - The gridservices import closure is free of pvlib and config (probed).
  - `FROZEN_MEMBERS` has no `GridServicesEventsConfig` entry yet.
  - Task 704's `SENSITIVITY_BANDS` exists on `task/704`; γ depends on 704.
  - S1's `errors.ConfigurationError` comes from 773 upstream.
- **G4:** each seam has one owner (§8). S8, S25 and S26 dependencies and the S1 allow-list ownership are proposed to the lead (§13). There are no reciprocal claims: S1 §7 already names S9 for both deferred-import entries.
- **G5:** B + H. The blast radius is at least 3 modules (gridservices, finance, flex, optimize, both CLIs, the grammar), the work touches a frozen-surface seam, and at least 2 streams consume it (S8, S25, S26).
- **G6:**
  - C1's "age 24 < age 0" holds on the fixture. Income is proportional to SOH there: E_spare = capacity × SOH × (0.8 − 0.1), so for a 5 kWh battery E_spare / 3 h = 1.17 × SOH kW, below P_spare = 2.0 kW. SOH(0) = 1.0 and SOH(24) ≤ 0.52.
  - C1's equality is exact at every year, because the energy-constant fake makes the no-income revenue curve constant, and PCHIP of a constant is that constant.
  - C2's bisection premise holds. With seeds 0, 12, 24 and SOH reaching its floor before age 12, PCHIP at age 6 gives SOH ≈ 0.656 against an actual ≈ 0.716 (calendar 0.02/yr plus cycle fade ≈ 0.027/yr at 0.5 kW discharge). That is a 0.06 × age-0 event income error, above 1% of age-0 revenue whenever event income is more than about a sixth of it.
  - The premise does **not** hold on the board scenario, where both figures are £0 (§2.2, measured). The signal is therefore bound to the fixture, and the board measurement is recorded rather than asserted.
  - P2's 9.972 is arithmetic on the defaults (§2.1).
  - The rejection mechanisms are new code in β and γ, each with a RED-today test (C5–C8, C10). The finding measured that `FinanceConfig(…, grid_services_model='capacity_at_events')` constructs today.
  - The solve's affine premise was re-derived (§5.3).
- **G7:** advisory (§10). No hit.
- **META:** decomposed without further oversight, this yields one pricing mechanism that values a fleet per simulated age. It holds one rule for the three-field triple until the bump and one closed type after it, one band vocabulary and one rate table, and no path that ignores a grid-services input. The open items are cross-stream ownership and a modelling observation for the lead. None changes S9's design.
