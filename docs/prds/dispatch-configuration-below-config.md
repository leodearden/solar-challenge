# PRD — Dispatch configuration below config (review-all stream S2)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S2** (wave 1, size L, risk medium). Findings record `plans/review-all-solar_challenge-20261013.json`, run `review-all-solar_challenge-20261013`.
- **Status:** authored 2026-10-14, awaiting the lead's rulings on §12 (lead-level questions) before commit and decompose.
- **Binding rulings:** D3 (grid_charging under an ignoring dispatcher is refused at construction; mid-term every dispatcher supports grid charging), D5 (one tagged union of strategy configs on `BatteryConfig`; `HomeConfig.dispatch_strategy` retired under the program's bump), D4 (one coordinated surface bump via S29), D28 (weakened findings re-measured before decomposing). D6 (S3) and D7 (S11) meet this stream at the TOU strategy; §8 assigns the meeting points.
- **Approach:** **B + H**. The change crosses eight modules (`dispatch`, `battery`, `flow`, `home`, `config`, `scenario_writer`, `web/storage`, `web/fleet_config`), touches the frozen public surface, and feeds three later streams (S3, S5, S27). §5 is the contract, §9 the two-way boundary tests.
- **Code anchors** verified against main `1251be0e621a6037173068d84ae3aea44c45fdce` (2026-10-14); none of the files this PRD touches changed between the findings' anchor commit `7dfea36e` and that SHA (`git diff 7dfea36e..1251be0 --stat` over them is empty). Anchors are cited by symbol; re-locate lines at implementation time.

Finding keys (all `simulation-core`): fk-b3dfd41a4d6a (medium, weakened), fk-615cbc883512 (low), fk-370b3e49b67c (medium), fk-c36d6fcbc2a8 (medium), fk-94f4881bbe48 (medium), fk-04b52ee632c6 (medium), fk-fc652220a4d3 (medium), fk-8529726bbd6b (medium), fk-99244625d7f2 (low), fk-f126b1c9cbbe (high).

---

## 1. Goal

Which dispatcher a battery runs, and whether it grid-charges, is decided in one place, by typed values defined where the simulation reads them, and a setting the chosen dispatcher would ignore is refused when the home is built instead of producing a plausible 0 kWh. A grid-charge target means one thing, a fraction of the battery's own SOH-derated capacity, and the Battery is the module that turns it into kWh.

**What a user observes when this lands:**

1. `solar-challenge validate config <file>` on a scenario whose battery sets `grid_charging` under self-consumption dispatch (the default), or with no tariff, exits 1 with an ERROR row naming `grid_charging` and the strategy (`solar-challenge home run` on the same file exits 1 with `Configuration error`). Today the file validates and the run simulates and stores 0.000 kWh from the grid with no warning (f44's probe: 3 of 5 combinations silently ignored).
2. The same command on a home-level `dispatch_strategy: tou_optimised` (a typo), `peak_shaving` or `42` fails naming the key and the valid values. Today each is accepted and simulated as self-consumption.
3. A battery-level `strategy_type` the vocabulary does not hold fails naming its block path (e.g. `homes[0].battery.dispatch_strategy.strategy_type`) and the valid values.
4. A grid-charging battery at SOH 0.7 charges to its target fraction of its *effective* capacity: a 10 kWh battery with `soh: 0.7` and target 0.5 stops at 3.5 kWh, where today it stops at 5.0 kWh (0.714 of effective). Multi-year projections of grid-charging fleets, which age every battery, change accordingly. A target above the battery's `max_soc_fraction` charges to `max_soc_kwh` and then stops asking: today the controller asks for 5.0 kW every cheap minute into a full battery.
5. A stored run with a dispatch strategy and grid charging exports and reloads equal to the run that was saved, and `web/storage.py` no longer imports `solar_challenge.config` to do it.
6. At the program's bump (S29), scenario files name a battery's strategy in one place, `battery.dispatch_strategy`, and a file still carrying the home- or fleet-level key is refused with a message naming the new location.

## 2. Background

### 2.1 What exists today (measured at `1251be0`)

- `config.py` defines `GridChargeConfig` (frozen) and `DispatchStrategyConfig` (plain mutable `@dataclass`, `strategy_type: str`, `peak_hours: Optional[list[tuple[int, int]]]`, `import_limit_kw: Optional[float]`). `config.py` imports `battery` at top level, so `battery.py` names both types only under `TYPE_CHECKING`. That one typing edge closes the 8-module typing cycle (battery, community, config, finance, fleet, flow, gridservices, home).
- `web/storage._field_types` merges `vars(solar_challenge.config)` into every `get_type_hints` call so stored `BatteryConfig`s can be rebuilt; its docstring explains the import order. `web/fleet_config.py` names `DispatchStrategyConfig` under `TYPE_CHECKING`.
- The dispatcher is chosen by two string fields with two vocabularies: `HomeConfig.dispatch_strategy: str = "greedy"` (`greedy` | `tou_optimized`, checked only for the fleet-distribution copy by `config._VALID_DISPATCH_STRATEGIES`; `HomeConfig` has no `__post_init__`) and `BatteryConfig.dispatch_strategy.strategy_type` (`self_consumption` | `tou_optimized` | `peak_shaving`, checked by `DispatchStrategyConfig.__post_init__` with `ConfigurationError`, re-checked by `home._create_dispatch_strategy` with `ValueError`, and a third time by the strategy constructors). The precedence (tariff TOU only when the battery has no strategy, and only with a tariff) lives in `home.simulate_home`'s `use_tariff_tou` predicate.
- Grid charging needs three settings in three places: `BatteryConfig.grid_charging`, `HomeConfig.tariff_config`, and a dispatcher that reads the context. `SelfConsumptionStrategy` documents `grid_charge_ctx` as "accepted but not used". Nothing refuses or warns.
- `flow.py` reads `battery.config.*` 11 times (`grid_charging` 7 including docstring and assert, `max_charge_kw` 2, `capacity_kwh` 2). Both paths pass the **nominal** `battery.config.capacity_kwh` as the capacity a grid-charge target is a fraction of (`simulate_timestep` into `decide_action(battery_capacity_kwh=...)`, `simulate_timestep_tou` into `compute_grid_charge_power_kw(capacity_kwh=...)`), while `Battery` bounds the SOC by fractions of `effective_capacity_kwh = capacity_kwh * soh`. `GridChargeConfig`'s docstring says "fraction of usable capacity": three readings.
- `Battery.__init__` resolves SOH (override, else `compute_soh` with zero throughput); `effective_capacity_kwh`, `min_soc_kwh`, `max_soc_kwh` exist only on the stateful `Battery`, so `gridservices.compute_fleet_spare_capacity_kw` and `web/charts.battery_soc_chart` each build a throwaway `Battery(battery_config)` to read them.

Probes run for this PRD on `1251be0` (`uv run --locked --extra dev python -I`):

| Probe | Today |
|---|---|
| 10 kWh, 5 kW, `soh` 0.7, target 0.5, 180 cheap E7 minutes from 01:00, both paths, from the midpoint and from `min_soc_kwh` | end fraction of effective capacity **0.714286** (all four); at `soh` 1.0, **0.500000** |
| Same battery, target 0.95 > `max_soc_fraction` 0.9, after 180 minutes | SOC at 0.9 of effective; `TOUOptimizedStrategy` still requests **5.0 kW** grid charge |
| f44 (findings record): PV 4 kW, deterministic 3400 kWh, 5 kWh battery with `GridChargeConfig(0.9)`, one synthetic June day | default dispatch 0.000, battery `self_consumption` 0.000, home `tou_optimized` without tariff 0.000; home `tou_optimized` + E7 **2.080**, battery `peak_shaving` + E7 **2.000** |

### 2.2 The platform consumer (constrains where the refusal lives)

`solar-challenge-platform` pins `solar-challenge-v0.5.0` and, read at its current main:

- imports `GridChargeConfig` **from `solar_challenge.config`** (`optimiser/planner.py`), and builds grid-charge candidates as `dataclasses.replace(battery_config, grid_charging=GridChargeConfig(target))` on a `BatteryConfig` with **no** `dispatch_strategy`, capping the target at `max_soc_fraction`;
- drives `flow.simulate_timestep` with its **own** strategy objects (it subclasses `DispatchStrategy`, implementing `decide_action` and `name`) and passes `tariff=`, relying on the engine to build the grid-charge context from `battery.config.grid_charging`;
- uses `GridChargeContext` only as an annotation, never constructs it, and never calls `compute_grid_charge_power_kw`, `HomeConfig.dispatch_strategy` or `DispatchStrategyConfig`.

Two consequences shape this PRD: the D3 refusal cannot live in `BatteryConfig.__post_init__` (it would refuse the planner's candidates), and the engine must keep offering a grid-charge context whenever a tariff is passed and the battery is configured to grid-charge. The `GridChargeConfig` import path is the one consumer edit the bump needs (§5.8).

### 2.3 Already-filed tasks this PRD absorbs or touches

| Task | Status | Relation |
|---|---|---|
| 632 | pending | Same defect as fk-8529726bbd6b / fk-99244625d7f2 (nominal vs effective target). Absorbed by γ. |
| 209 | pending | Drop `web/storage`'s config-namespace merge once the types move. Absorbed by α. |
| 568 | pending | `FleetDistributionConfig` accepts any `dispatch_strategy` string at construction. Absorbed by β (validated) and ε (retired). |
| 669 | pending | Freeze or narrow the "configs are frozen" rule; `DispatchStrategyConfig` is one of its nine classes. α removes that class from its list. |
| 744 | in-progress | Prose cleanup in `dispatch.py`. Same file as α; α lands after it. |
| 558 | pending | `grid_charging.target_soc_fraction: true` accepted. A finite-number/bool question, S4's checker; not taken here. |

### 2.4 D28 re-measure of the weakened key fk-b3dfd41a4d6a

The files are unchanged since `7dfea36`, so the cycle-closing edge (battery.py's `TYPE_CHECKING` import), the storage merge, the fleet_config import and the two validators with two exception types all still hold. The skeptic's correction stands and is adopted: the direct consumers below config are **3** modules (battery fields, flow's grid-charge context, home's strategy factory), not 4. The decomposing session records this on α.

## 3. Rulings that bind, and how this PRD reads them

- **D5.** One frozen tagged union of strategy configs is `BatteryConfig.dispatch_strategy`'s type. `HomeConfig.dispatch_strategy` (and its fleet copy) is retired in the held leaf ε at S29's bump; until then it is validated (β) and its precedence is unchanged.
- **D3.** The refusal fires when a home (and, through S27, a community) is built, and again when the dispatcher is built for a run, through one function (§5.3). The mid-term goal, every dispatcher grid-charging, is recorded in §11 with the policy question it raises; no leaf here implements it.
- **D4.** No re-export shim or dual field survives. §5.8 is the ledger S29 writes its one release section and consumer recipe from.
- **D6 / D7.** The tariff-clocked TOU dispatcher that replaces `simulate_timestep_tou` is S3's (D6) and its clock is the tariff's classifier, S11's (D7). This PRD does not write it; it gives the TOU variant the shape those leaves extend (§5.1, §8).

## 4. Sketch of approach

1. **Types move down (α).** `dispatch.py` defines `GridChargeConfig` and three frozen strategy-config variants, their union `DispatchStrategyConfig`, a tag table derived from the variants, one validator each for peak hours and the import limit (shared with the strategy constructors), and `build_dispatch_strategy`, the factory that replaces `home._create_dispatch_strategy`. `battery.py` imports them at top level; `config.py` parses into them, `scenario_writer.py` writes them, `web/storage.py` rebuilds them with a generic tagged-union rule and no config import.
2. **Refuse what would be ignored (β).** `HomeConfig.__post_init__` validates the transitional home-level key and calls the factory's check, so a home whose battery grid-charges under self-consumption, or without a tariff, cannot be built. The fleet file's "falls back to self-consumption" warning becomes that refusal.
3. **The Battery answers (γ).** `Battery.grid_charge_target_kwh` is the target in kWh on effective capacity, capped at `max_soc_kwh`; `Battery.max_charge_kw` is its charge limit. `GridChargeContext` carries the kWh target; `compute_grid_charge_power_kw` no longer takes a capacity; `flow.py` stops reading `battery.config` and hands strategies the effective capacity.
4. **One owner of the derated envelope (δ).** `BatteryConfig.resolved_soh` and `BatteryConfig.soc_envelope()` give any reader the derated SOC envelope without a throwaway `Battery`; `Battery` derives its kWh limits from the same envelope.
5. **Retire the second vocabulary at the bump (ε, held for S29).** Delete `HomeConfig.dispatch_strategy`, the fleet key and their constants; `BatteryConfig.dispatch_strategy` defaults to `SelfConsumptionStrategyConfig()`; migrate the two scenario files.

## 5. Contract

### 5.1 `dispatch.py` types (α)

```python
@dataclass(frozen=True)
class GridChargeConfig:
    target_soc_fraction: float = 0.9   # (0, 1]; a fraction of the battery's effective capacity (§5.4)

@dataclass(frozen=True)
class SelfConsumptionStrategyConfig:
    strategy_type: Literal["self_consumption"] = field(default="self_consumption", init=False)

@dataclass(frozen=True)
class TOUOptimizedStrategyConfig:
    peak_hours: tuple[tuple[int, int], ...]          # non-empty; each 0 <= start < end <= 24
    strategy_type: Literal["tou_optimized"] = field(default="tou_optimized", init=False)

@dataclass(frozen=True)
class PeakShavingStrategyConfig:
    import_limit_kw: float                            # positive and finite
    strategy_type: Literal["peak_shaving"] = field(default="peak_shaving", init=False)

DispatchStrategyConfig: TypeAlias = (
    SelfConsumptionStrategyConfig | TOUOptimizedStrategyConfig | PeakShavingStrategyConfig
)
STRATEGY_CONFIG_BY_TYPE: Mapping[str, type[DispatchStrategyConfig]]  # read-only, derived from the members' tag defaults
```

- **The tag** is each variant's `strategy_type` field: `init=False`, `Literal`-typed, its default the tag. It is serialised by `dataclasses.asdict`, so a variant's stored and written form is the YAML block it was read from: `{strategy_type: <tag>, <its init fields>}`. `STRATEGY_CONFIG_BY_TYPE` is computed from the union's members, never restated.
- **Validation** is in each variant's `__post_init__` through one module function per rule (`_require_valid_peak_hours`, `_require_valid_import_limit`), which `TOUOptimizedStrategy.__init__` and `PeakShavingStrategy.__init__` call too: one validator per rule, enforced at both entry points. They raise `ConfigurationError` from S1's errors leaf (a `ValueError` subclass per D2, so `except ValueError` callers are unaffected).
- **Extension points owned here, implemented elsewhere:** S11 (D7) makes `TOUOptimizedStrategyConfig.peak_hours` an optional override, `None` meaning the tariff's cheap periods, and adds that arm to `build_dispatch_strategy`; S4 replaces the two validators' bound idioms with its finite-number checker. Neither changes the tag, the union or the factory's signature.
- `dispatch.py` imports `timebase`, `tariff` (for the factory's `TariffConfig` parameter) and S1's errors leaf; it never imports `battery`, `config` or `home`.

### 5.2 `BatteryConfig` and the engine contract (α, γ)

- `BatteryConfig.dispatch_strategy: DispatchStrategyConfig | None = None` and `grid_charging: GridChargeConfig | None = None`, both resolving at run time in `battery.py`. `BatteryConfig` stays agnostic about whether its strategy honours its grid charging: it describes the battery; the home picks and checks the dispatcher (§5.3). At ε the default becomes `SelfConsumptionStrategyConfig()` and the annotation drops `| None`.
- **Engine contract, unchanged in meaning:** `flow.simulate_timestep(..., battery, ..., strategy, *, tariff)` offers `strategy.decide_action` a `GridChargeContext` exactly when `tariff is not None` and `battery.grid_charge_target_kwh is not None`. A caller driving the engine with its own strategy object (the platform) owns that strategy's use of the context. `simulate_timestep_tou` keeps its behaviour until S3 retires it, reading the same Battery answers.

### 5.3 The factory and the D3 refusal (α, β)

```python
def build_dispatch_strategy(
    config: DispatchStrategyConfig,
    *,
    grid_charging: GridChargeConfig | None,
    tariff: TariffConfig | None,
) -> DispatchStrategy
```

- One `match` over the union with `assert_never`, one arm per variant: adding a strategy is one variant plus one arm (D5's consequence). `TOUOptimizedStrategy` receives `list(config.peak_hours)`, a fresh list per call, so no strategy shares a caller's list.
- **Refusals (β adds them; α's factory is the plain mapping), each a `ConfigurationError` naming `grid_charging` and the strategy's tag:**
  - `grid_charging` set and the variant does not grid-charge (`self_consumption` today): "grid_charging is set, but dispatch strategy 'self_consumption' does not charge from the grid; remove grid_charging, or use tou_optimized or peak_shaving".
  - `grid_charging` set and `tariff is None`: "grid_charging is set, but there is no tariff, so dispatch strategy '<tag>' has no cheap period to charge in; add a tariff or remove grid_charging".
  Whether a variant grid-charges is one fact per variant, read in one place (the arm), so the mid-term change (§11) is one arm.
- **Construction-time enforcement (β):** `HomeConfig.__post_init__`
  1. refuses, for every home, a home-level `dispatch_strategy` outside `HOME_DISPATCH_STRATEGIES = ("greedy", "tou_optimized")` (the constant moves from `config._VALID_DISPATCH_STRATEGIES` to `home.py`; config's fleet reader reads it), naming the field, the value and the valid values; `FleetDistributionConfig.__post_init__` does the same for its copy (task 568);
  and, for a home with a battery,
  2. on the tariff-TOU route (`_runs_tariff_tou(config)`: home-level `tou_optimized`, battery strategy unset; extracted once and also read by `simulate_home` until S3 deletes it) refuses a missing tariff, naming `dispatch_strategy 'tou_optimized'` and the missing tariff; that route honours `grid_charging`;
  3. otherwise calls `build_dispatch_strategy(battery.dispatch_strategy or SelfConsumptionStrategyConfig(), grid_charging=battery.grid_charging, tariff=self.tariff_config)` and lets its refusals propagate.
  A home with no battery skips steps 2 and 3: no strategy runs. `dataclasses.replace` re-runs the check, so `finance._aged_homes` and `optimize`'s install sweep build only valid homes. `simulate_home` calls the same factory for the run (the use-time enforcement).
- `parse_home_block` and the fleet reader read the home/fleet key through one reader that names the key path, a null value reading as absent (one existing test writes `dispatch_strategy: null` at home level); the HomeConfig-level refusals (D3) carry no block path (adding paths is S5's reader work).

### 5.4 Capacity basis and Battery answers (γ, δ)

- `GridChargeConfig.target_soc_fraction` is a fraction of the battery's **effective (SOH-derated) capacity**, the basis of `Battery.soc_fraction`. A target above the battery's `max_soc_fraction` means "as full as the battery allows".
- `Battery.grid_charge_target_kwh -> float | None`: `None` when `config.grid_charging is None`, else `min(target_soc_fraction, self.max_soc_fraction) * self.effective_capacity_kwh` (it reads the battery's current, possibly reassigned, `max_soc_fraction`). `Battery.max_charge_kw -> float`: the charge limit `Battery.charge` already applies.
- `GridChargeContext(current_rate, peak_rate, is_cheap_period, target_soc_kwh, max_charge_kw, round_trip_efficiency, charge_efficiency)`; `compute_grid_charge_power_kw(ctx, *, battery_soc_kwh, pv_charge_power_kw, timestep_minutes)` uses `ctx.target_soc_kwh` and takes no capacity. `simulate_timestep` passes `battery_capacity_kwh=battery.effective_capacity_kwh` to `decide_action` (its docstring says so); `decide_action`'s signature is unchanged (the platform implements it).
- **δ:** `battery.SocEnvelope(effective_capacity_kwh, min_soc_kwh, max_soc_kwh)` (frozen) with `target_kwh(fraction)` holding the cap above; `BatteryConfig.resolved_soh` (the `soh` override, else `compute_soh(system_age_years, 0.0, nominal_usable_capacity_kwh, self)`), the one SOH resolution `Battery.__init__` reads; `BatteryConfig.soc_envelope()` at the config's fractions; `Battery.soc_envelope` at the battery's current fractions, from which `min_soc_kwh`, `max_soc_kwh`, `effective_capacity_kwh`, `usable_capacity_kwh` and `grid_charge_target_kwh` derive. `gridservices.compute_fleet_spare_capacity_kw` and `web/charts.battery_soc_chart` read `battery_config.soc_envelope()`.
- **Invariant 9 (promoted, D27):** every capacity a dispatcher sees is SOH-derated, so a grid-charge target is a fraction of effective capacity (§9 rows 9-10).

### 5.5 Scenario grammar (α, ε)

- The `battery.dispatch_strategy:` block grammar is unchanged: `strategy_type:` selects the variant through `STRATEGY_CONFIG_BY_TYPE`; the remaining keys are that variant's init fields. An unknown `strategy_type` is refused naming its key path and the sorted valid values; a key the variant does not read is refused naming its path, **except** a null-valued key another variant reads (`peak_hours: null`, `import_limit_kw: null`), which reads as absent, so files written by today's `scenario_writer` (all three keys, nulls included) still load. `peak_hours` lists become tuples at the boundary.
- `scenario_writer._dispatch_strategy_block` writes `{strategy_type, **init fields}` from the variant's fields, so the writer and the reader share the variant as their key table (S7's battery-block table names `dispatch_strategy` and `grid_charging` as sub-blocks whose grammar is this one).
- ε: `home.dispatch_strategy` and `fleet_distribution.dispatch_strategy` are refused with a message naming the new location (`battery.dispatch_strategy: {strategy_type: tou_optimized}`); `scenarios/bristol-arbitrage.yaml` and `scenarios/bristol-phase1-flex.yaml` move their `tou_optimized` into the battery block without `peak_hours` (the tariff clock, available once S11's arm lands).

### 5.6 Stored runs (α)

- `web/storage._field_types` resolves with plain `get_type_hints(cls)`; `import solar_challenge.config` and the docstring sentence go; the `functools.cache` and read-only return stay (task 209's measured performance fix).
- **Tagged-union rule** in `_deserialize_value`: a union whose non-`None` members are dataclasses each declaring an `init=False` field with a one-value `Literal` annotation of the same name is read as the member whose literal equals the stored value of that field; a stored value matching no member raises naming the field and the value. `_deserialize_dataclass` never passes an `init=False` field to the constructor. Runs stored before α (`{strategy_type, peak_hours, import_limit_kw}` with nulls) load as the matching variant; the other variants' null keys are skipped as unknown keys are today. S19's format version covers the change if S19 lands first (§8).

### 5.7 Invariant 10 (promoted, D27, as a refusal per D3)

For each of f44's ignored combinations (default dispatch, battery `self_consumption`, home `tou_optimized` without tariff), plus battery `peak_shaving` without a tariff, building the `HomeConfig` raises `ConfigurationError` whose message contains `grid_charging` (or, for the tariff-TOU route, `tou_optimized` and `tariff`) and the strategy's name; the two honoured combinations (home `tou_optimized` + E7, battery `peak_shaving` + E7) simulate with `total_grid_charge_kwh > 0`; and the platform's shape (a `BatteryConfig` with `grid_charging` and no strategy, driven through `simulate_timestep` with a `TOUOptimizedStrategy` and a tariff) still grid-charges. Fixture: f44's probe (PV 4 kW, deterministic 3400 kWh, 5 kWh battery, `GridChargeConfig(0.9)`, 2024-06-15, `synthetic_june_weather`, `warnings.simplefilter('always')`).

### 5.8 Surface ledger for S29 (D4)

Each line is a frozen-surface change S2 makes, the release-note text S29's one "Unreleased on main" section carries, and what a consumer does at re-pin. "Platform" means `solar-challenge-platform` at its current main.

| Leaf | Change | Consumer action |
|---|---|---|
| α | `GridChargeConfig` moves from `solar_challenge.config` to `solar_challenge.dispatch`, unchanged constructor | Platform: change `optimiser/planner.py`'s import |
| α | `config.DispatchStrategyConfig` (mutable, `strategy_type: str`) is replaced by frozen `dispatch.SelfConsumptionStrategyConfig()`, `TOUOptimizedStrategyConfig(peak_hours: tuple[tuple[int, int], ...])`, `PeakShavingStrategyConfig(import_limit_kw: float)`; `dispatch.DispatchStrategyConfig` is their union; `BatteryConfig.dispatch_strategy` takes it, so a `BatteryConfig` with a strategy is hashable | Platform: none (unused) |
| α | `TOUOptimizedStrategy` and `PeakShavingStrategy` raise `ConfigurationError` (a `ValueError`) where they raised `ValueError` | none |
| β | Building a `HomeConfig` refuses an unknown home-level `dispatch_strategy`, and, when the home has a battery, `grid_charging` under self-consumption dispatch, `grid_charging` without a tariff, and home-level `tou_optimized` without a tariff; a fleet file without a tariff that dispatches `tou_optimized` is refused, not warned | Platform: none (its `HomeConfig`s set none of these) |
| γ | `GridChargeConfig.target_soc_fraction` is a fraction of effective (SOH-derated) capacity, capped at `max_soc_fraction`; grid-charge results change for batteries below SOH 1, multi-year projections included | Platform: its planner's `soh=1.0` workaround (task 875) stays correct and can go |
| γ | `GridChargeContext.target_soc_fraction` becomes `target_soc_kwh`; `compute_grid_charge_power_kw` drops `capacity_kwh`; `simulate_timestep` passes effective capacity as `decide_action`'s `battery_capacity_kwh`; `Battery` gains `grid_charge_target_kwh` and `max_charge_kw` | Platform: none (annotation only) |
| δ | `battery.SocEnvelope`; `BatteryConfig.resolved_soh`, `BatteryConfig.soc_envelope()`; `Battery.soc_envelope` | none |
| ε (held) | `HomeConfig.dispatch_strategy` and the YAML home/fleet key retired; `BatteryConfig.dispatch_strategy` defaults to `SelfConsumptionStrategyConfig()` | Scenario files: move the key into the battery block |

## 6. Resolved design decisions

1. **Types and factory live in `dispatch.py`, the factory takes the parts, not a `BatteryConfig`.** `battery.py` imports `dispatch` for the field types, so a factory taking `BatteryConfig` would import `battery` back: a cycle. Taking `(config, grid_charging, tariff)` keeps `dispatch.py` a leaf above `timebase`, `tariff` and errors.
2. **Tag as an `init=False` `Literal` field, not a `ClassVar` or a registry.** It is in `asdict`, so YAML, scenario_writer and storage all carry it with no per-type code; it is not a constructor parameter, so a variant cannot be built with the wrong tag; `mypy --strict` checks exhaustiveness of the factory's `match`.
3. **The refusal sits at the home, not the battery.** `BatteryConfig.__post_init__` cannot refuse `grid_charging` without a strategy: the platform builds exactly that and supplies the strategy object to the engine (§2.2). The home is where the dispatcher is chosen from config, so it is where an ignored setting is detectable.
4. **The engine keeps reading grid charging from the battery.** Moving the grid-charge source into the dispatcher (fk-fc652220a4d3's "flow builds the context from what the dispatcher declares") would make the platform's grid-charge candidates silently stop charging. The Battery answers instead (`grid_charge_target_kwh`), which removes the reach-through and keeps the contract.
5. **Effective capacity, capped at the battery's ceiling.** Matches `Battery.soc_fraction` (invariant 9's ruling basis), task 632's recommendation, and the platform's own capping; the cap stops the controller requesting power into a full battery.
6. **The kWh target travels in the context; `decide_action` is untouched.** `GridChargeContext` and `compute_grid_charge_power_kw` change form (clean option under D4, no consumer reads them); `decide_action` does not, because the platform implements it and S3 owns the strategy interface.
7. **No tariff-clocked TOU strategy here.** It is the meeting point of D6 (S3) and D7 (S11); writing it here would pre-empt both. Until it lands the home-level key keeps its route, validated.
8. **The home-level key is validated now, retired at the bump.** D5 ties the retirement to the bump; a typo silently running self-consumption is a live defect today, so β closes it with ~10 transitional lines that ε deletes.
9. **Null keys of other variants read as absent.** Today's writer emits all three keys with nulls into exported scenarios and stored runs; refusing them would break every file the web exported.
10. **One validator per rule, two call sites.** The variant and the strategy constructor (public, built directly by the platform) both validate, through one function, so "the three peak_hours validators collapse to one" without weakening either entry point.
11. **`build_dispatch_strategy` and `STRATEGY_CONFIG_BY_TYPE` stay out of `__all__`.** They are library-internal seams (S18, S27, config); keeping them off the frozen surface keeps the bump small.
12. **δ is in scope, as its own leaf.** fk-f126b1c9cbbe is the stream's only high finding and its next-change risk is a new reader computing a capacity by hand; γ alone fixes the target but leaves SOH resolution and the derated envelope on the stateful `Battery`. δ is separable (§12 Q4).

## 7. Pre-conditions

- **S1's errors leaf with D2's base** (`solar_challenge/errors.py`; S1's PRD `docs/prds/errors-leaf.md` ships the module in its leaf α and makes `ConfigurationError` a `ValueError` subclass in its leaf β) is landed before α: the moved types raise it, `dispatch.py` cannot import `config`, and the strategy constructors switch from `ValueError` to it, which is only compatible once it subclasses `ValueError`. Wired as α's out-of-batch dependency on S1-β (S1-β depends on S1-α).
- **Task 744** (in-progress, `dispatch.py` prose) has merged before α starts.
- For ε only: S11's leaf that gives `TOUOptimizedStrategyConfig.peak_hours = None` its tariff-clock arm, S3's leaf that routes home-level `tou_optimized` through the factory and deletes `use_tariff_tou`, and S29's bump window.

G3 substrate: every symbol §5 names as existing was read at `1251be0` (capability manifest). No novel substrate is assumed beyond what α-δ build; the two cross-stream substrates (S1's error type, S11/S3's tariff-clock arm) are queued prerequisites.

## 8. Cross-PRD relationship

| Other stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 errors leaf | consumes | `errors.ConfigurationError` (a `ValueError` subclass) raised by the moved types, the shared validators and the factory | S1 | α depends on S1-β (matches S1 PRD §9's proposed row and its §12 Q5) |
| S3 one dispatch engine | produces for | `GridChargeContext(target_soc_kwh, ...)`, Battery answers, `build_dispatch_strategy`; S3 retires `simulate_timestep_tou` and **deletes `simulate_home`'s `use_tariff_tou` predicate and `_runs_tariff_tou`** (moved from this stream's program-row deletable list: it is D6's work) | S2 owns the types; S3 owns the engine | S3 depends on α, γ |
| S11 tariff | both | S11 owns the cheap-period classifier and makes `TOUOptimizedStrategyConfig.peak_hours` an optional override with the D7 contradiction check, adding the tariff-clock arm to `build_dispatch_strategy`; S2 owns the union and the factory signature | S2 type / S11 arm | S11's arm leaf depends on α; ε depends on S11's arm |
| S27 community | produces for | `build_dispatch_strategy(config, grid_charging=, tariff=)`; S27 calls it from `CommunityConfig` (construction-time D3 for the community battery) and from `simulate_community` | S2 factory / S27 call sites | S27 depends on α, β |
| S5 config partition | produces for | the moved types (S5 orders after S2); `parse_dispatch_strategy_config` and `_parse_grid_charge_config` move with the block readers into `scenario_blocks.py`; S5 adds block paths to readers | S2 types / S5 partition | S5 depends on α |
| S7 component defaults | shares | battery-block key table names `dispatch_strategy`/`grid_charging`; their sub-grammar is §5.5's | S7 table / S2 sub-grammar | concurrent, file overlap in config.py |
| S4 finite quantities | consumes | invariant 1's fixture walks `dispatch.GridChargeConfig` and the three variants (not `config.DispatchStrategyConfig`); S4 swaps §5.1's bound idioms for its checker | S4 | S4 after α |
| S19 run store | shares | the tagged-union rule in `_deserialize_value` (§5.6); S19's stored-run format version must cover α's shape change and, later, ε's removed home key | S2 rule / S19 format | α and S19 both wave 1: whichever lands second keeps the other's tests green |
| S18 dashboard limits | produces for | `STRATEGY_CONFIG_BY_TYPE` is the server table the fleet form's dispatch vocabulary renders from (replacing `_FORM_DISPATCH_SETTINGS`' restated tags) | S2 table / S18 render | S18 after α |
| S9 grid services, S21 charts | touches | δ edits one line each in `gridservices.compute_fleet_spare_capacity_kw` and `web/charts.battery_soc_chart` | S2 (δ) | file overlap only |
| S23 surface lock | touches | α-δ edit the frozen tables in their own commits (pending §12 Q1) | S23 owns the tables | file overlap in the surface test module |
| S29 surface bump | produces for | §5.8 ledger; ε is held for S29's window | S29 | ε held |

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Faces |
|---|---|---|---|---|
| 1 | Each variant's YAML block round-trips | one block per tag, plus `peak_hours` lists | parse → `scenario_writer` → parse yields an equal variant; written block lists only `strategy_type` and the variant's own keys | grammar (config, writer) |
| 2 | Pre-α writer output still loads | block with all three keys, nulls included, per tag | parses as the tag's variant | grammar back-compat |
| 3 | Unknown tag refused with path | `homes[0].battery.dispatch_strategy.strategy_type: tou_optimised` | `ConfigurationError` naming that path and the sorted valid tags | grammar |
| 4 | Stored run round-trips | `HomeConfig` with each variant and `GridChargeConfig(0.8)`, through `RunStorage.save_home_run`/`load_home_run` and the export endpoint | loaded config equals saved; `web/storage.py` contains no `solar_challenge.config` | storage (consumer) |
| 5 | Pre-α stored run loads | committed run JSON with the old three-key shape | loads as the matching variant | storage back-compat |
| 6 | Hints resolve in place; configs are values | walk dataclass fields from `HomeConfig`, `SummaryStatistics`, `FleetSummary` | `typing.get_type_hints` succeeds on all 14 in their own modules (today 13); `hash(HomeConfig(...strategy...))` works; assigning a variant field raises `FrozenInstanceError` | battery, storage |
| 7 | Factory maps every variant | each variant, `grid_charging=None`, E7 | strategy class and `.name` equal the tag; a TOU strategy's peak list is not the config's tuple | dispatch (producer) |
| 8 | Invariant 10 | §5.7 fixture | three refused + no-tariff peak shaving raise naming `grid_charging` and the strategy; two honoured > 0; platform shape > 0 | home (consumer), engine contract |
| 9 | Invariant 9 | program's fixture verbatim (10 kWh, 5 kW, `soh` ∈ {1.0, 0.7}, target 0.5, 180 E7 minutes from 01:00, demand 0.3, PV 0), on `simulate_timestep_tou` and on `simulate_timestep` with `TOUOptimizedStrategy([(16, 19)])` + tariff, from the midpoint **and** from `min_soc_kwh` | end `soc_fraction` = 0.5 ± 1e-6 in all eight cases (today 0.714286 at `soh` 0.7) | flow, battery, dispatch |
| 10 | Target above the ceiling | same, target 0.95, `max_soc_fraction` 0.9 | ends at `max_soc_kwh`; the strategy's next decision requests `grid_charge_kw == 0.0` (today 5.0) | dispatch, battery |
| 11 | Envelope without a Battery (δ) | `BatteryConfig(10, soh=0.7, min 0.2, max 0.8)` | `soc_envelope()` equals `Battery(config)`'s `(effective, min, max)`; chart lines and spare capacity read it; a battery whose `max_soc_fraction` is reassigned answers from its own fractions | battery, charts, gridservices |
| 12 | Retirement (ε) | migrated `bristol-arbitrage.yaml`; the pre-migration file | migrated file validates and its one-day run's `total_grid_charge_kwh` equals the pre-migration run's (measured when ε is filed); the old file is refused naming `battery.dispatch_strategy` | grammar, home |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`; priority is the highest severity among its keys. Each leaf that changes a frozen form edits the surface tables in the same commit (pending §12 Q1) and adds no line to `docs/domain-library-consumption.md` (S29 writes the section from §5.8).

**α — dispatch.py owns the dispatch-configuration types and the strategy factory** (leaf; priority medium)
- Keys: fk-b3dfd41a4d6a, fk-615cbc883512, fk-370b3e49b67c, fk-c36d6fcbc2a8, fk-94f4881bbe48 (battery vocabulary), fk-04b52ee632c6 (factory, re-checks).
- Work: §5.1, §5.5 (reader and writer), §5.6, the factory's plain mapping (§5.3 without refusals) replacing `home._create_dispatch_strategy`, `battery.py`'s top-level import, `web/fleet_config.py`'s import, shared validators; rewrite the ~33 `DispatchStrategyConfig(...)` test constructions (15 files) and ~35 `GridChargeConfig` imports. Absorbs task 209; record the D28 re-measure (§2.4).
- Files: `src/solar_challenge/{dispatch,battery,config,home,scenario_writer}.py`, `src/solar_challenge/web/{storage,fleet_config}.py`, tests under `tests/unit/{config,web_api}/`, `tests/unit/test_{scenario_writer,web_storage_roundtrip,web_history,web_fleet_config,home_grid_charging,public_api_surface,flow,battery,optimize_enumerate}.py`, `tests/integration/test_dispatch_strategies.py`.
- Signal: `solar-challenge validate config` on a copy of `scenarios/dispatch-comparison.yaml` whose first home says `strategy_type: tou_optimised` exits 1, its ERROR row naming `homes[0].battery.dispatch_strategy.strategy_type` and the three valid tags (today the row reads `Invalid strategy_type 'tou_optimised'. Must be one of: ...`, naming no path); the unmodified file validates; a stored home run with a TOU strategy and grid charging exports and reloads equal (§9 rows 1-7).
- Prereqs: S1-β (errors leaf with the `ValueError` base); task 744 merged.

**β — Refuse at construction what the dispatcher would ignore** (leaf; priority medium)
- Keys: fk-fc652220a4d3, fk-94f4881bbe48 (home key), fk-04b52ee632c6 (home key).
- Work: §5.3 refusals and construction-time enforcement, `HOME_DISPATCH_STRATEGIES`, `FleetDistributionConfig` check (absorbs 568), the fleet file's warning deleted, invariant 10 as `tests/unit/test_grid_charge_refusals.py`, `review/briefing.yaml`: replace the key_decision "Two dispatch paths coexist ... SelfConsumptionStrategy deliberately accepts-but-ignores the grid-charge context" with the refusal and its transitional status (D3), and add one conventions line pointing at the invariant-10 test. Fix the existing tests that build refused homes: measured at authoring by wrapping `HomeConfig.__init__` over the non-slow unit and integration suites, **22 tests in 8 files** build a home with a battery that β refuses (`tests/unit/config/test_fleet_file.py` 6, `tests/unit/test_optimize_enumerate.py` 6, `tests/unit/config/test_generate_homes.py` 3, `tests/unit/config/test_home_block.py` 2, `tests/unit/test_home_grid_charging.py` 2, `tests/unit/test_cli.py` 1, `tests/unit/web_api/test_fleet_distribution.py` 1, `tests/unit/web_api/test_fleet_yaml.py` 1); each either gains the missing tariff or strategy, or, where it pinned the silent behaviour, asserts the refusal. The e2e suite was not probed.
- Signal: `solar-challenge validate config` on `scenarios/bristol-arbitrage.yaml` with `dispatch_strategy: greedy` exits 1, its ERROR row naming `grid_charging` and `self_consumption` (today it validates); with its `tariff:` block removed, exits 1 naming `tou_optimized` and the tariff; the unmodified file and `bristol-phase1-flex.yaml` validate; §9 row 8.
- Prereqs: α.

**γ — The Battery answers the grid-charge target on its effective capacity** (leaf; priority **high**)
- Keys: fk-8529726bbd6b, fk-99244625d7f2, fk-f126b1c9cbbe.
- Work: §5.4 bullets 1-3, every `battery.config.` read in `flow.py` replaced by a Battery answer (both paths), docstrings of `GridChargeConfig`, `GridChargeContext`, `decide_action` and `compute_grid_charge_power_kw`, invariant 9 as `tests/unit/test_grid_charge_target_basis.py` (§9 rows 9-10), one `review/briefing.yaml` conventions line pointing at it. Absorbs task 632.
- Files: `src/solar_challenge/{battery,dispatch,flow}.py`, `tests/unit/test_grid_charge_target_basis.py`, `tests/unit/test_flow.py`, `tests/unit/dispatch/`, `tests/unit/test_public_api_surface.py`, `review/briefing.yaml`.
- Signal: `solar-challenge home run` on `scenarios/bristol-arbitrage.yaml` with the battery given `soh: 0.7` and `grid_charging.target_soc_fraction: 0.5`, over 2024-01-15, writes a CSV whose `battery_soc_kwh` at 07:29 is 1.75 kWh, 0.5 of the 3.5 kWh effective capacity (today 2.5 kWh, 0.714); §9 rows 9-10.
- Prereqs: α.

**δ — One owner of the SOH-derated SOC envelope** (leaf; priority **high**; separable, §12 Q4)
- Keys: fk-f126b1c9cbbe.
- Work: §5.4 δ bullet; `Battery`'s kWh limits and `grid_charge_target_kwh` derive from the envelope; `compute_fleet_spare_capacity_kw` and `battery_soc_chart` read `soc_envelope()`; `Battery.__init__`'s SOH NOTE goes with the resolution it explains.
- Files: `src/solar_challenge/battery.py`, `src/solar_challenge/gridservices.py`, `src/solar_challenge/web/charts.py`, their tests, `tests/unit/test_public_api_surface.py`.
- Signal: the results page of a stored home run whose battery has `soh: 0.7`, `min_soc_fraction: 0.2`, `max_soc_fraction: 0.8` draws its Min/Max SOC lines at 1.4 and 5.6 kWh for a 10 kWh battery, read from `soc_envelope()`; no `Battery(` construction remains in `src/solar_challenge` outside `home.py` and `community.py`; §9 row 11.
- Prereqs: γ.

**ε — Retire the home- and fleet-level dispatch key at the bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "surface bump window open"}`, excluded from this batch's `commit_planning`)
- Keys: fk-94f4881bbe48, fk-04b52ee632c6.
- Work: §5.5 ε bullet, §5.2's default change; delete `HomeConfig.dispatch_strategy`, `FleetDistributionConfig.dispatch_strategy`, `HOME_DISPATCH_STRATEGIES`, `_parse_fleet_dispatch_strategy`, `generate_homes_from_distribution`'s `"greedy"`, any `_runs_tariff_tou` S3 left; `scenario_writer` stops writing the home key; migrate the two scenario files; the ~20 test sites that pass a home-level `dispatch_strategy`; update the briefing's dispatch key_decision to "one vocabulary".
- Signal: §9 row 12 (`solar-challenge validate config` and `home run` on the migrated `bristol-arbitrage.yaml`; the old file refused naming `battery.dispatch_strategy`).
- Prereqs: β; S11's tariff-clock arm leaf; S3's leaf that routes home-level `tou_optimized` through the factory; S29 releases it.

DAG: S1-β → α → {β, γ}; γ → δ; {β, S11 arm, S3 routing} → ε (held). Intra-batch edges: β→α, γ→α, δ→γ, ε→β.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`): screened against dark-factory's trigger shapes. β removes a silent fail-soft (`no-silent-fail-soft`); α's tag table and shared validators remove lock-step copies (`no-lockstep-duplication`, `one-fact-one-home`); β's transitional home-key validation is a placeholder owned by ε with a named bound (S29), not an unowned one. No hit.

## 11. Out of scope

- **Grid charging under every dispatcher (D3's mid-term direction).** Self-consumption discharges on any shortfall, and `DispatchDecision` forbids grid-charging while discharging, so "self-consumption with grid charging" needs a policy (hold the battery in cheap periods? only top up above the discharge need?) before it is code. That is a design question for a follow-up PRD after S3's one grid-charge gate and S11's classifier land; when it lands, the refusal arm in `build_dispatch_strategy` is the one line that goes. The community battery's half is S27's.
- The tariff-clocked TOU strategy and the retirement of `simulate_timestep_tou` (S3, S11).
- Refusing `grid_charging` on a tariff with no cheap period (a flat tariff never classifies cheap): it needs S11's classifier (§12 Q7).
- Finite/bool checks of `target_soc_fraction` and `import_limit_kw` beyond today's bounds (S4; task 558).
- Block paths on construction-time refusals (S5).
- Exposing the factory or the tag table in `__all__`.

## 12. Open questions

### Lead-level (rulings needed before commit; each has a default the PRD is written to)

1. **Surface sequencing.** α's type move and union change `FROZEN_CLOSURE` keys (they derive from `__module__`), so the move and the table edit are one commit; holding them for S29 (wave 4) would stall S3, S5 and S27 (wave 2). **Default:** α-δ edit the frozen tables in their own commits, as main has done since v0.5.0 (e.g. task 326 dropped `off_peak_hours`), and S29 writes the one release section from §5.8; only ε, which D5 ties to the bump, is held. The platform needs one edit at re-pin (the `GridChargeConfig` import). If the lead wants S23's test-module restructure to land first, α-δ take S23's leaf as a dependency.
2. **D6/D7 meeting point.** **Default:** S11 owns making `TOUOptimizedStrategyConfig.peak_hours` an optional override and the factory's tariff-clock arm; S3 owns routing the home-level key through it and deleting `use_tariff_tou`, which leaves S2's program-row deletable list. The S3 and S11 PRDs need the matching lines (§13).
3. **S2 now depends on S1** (the program row says none; S1's PRD §9 proposes the same edge). **Default:** α depends on S1-β, the leaf that gives `ConfigurationError` its `ValueError` base, because α switches the public strategy constructors from `ValueError` to it; the alternative, `ValueError` in the moved types converted later by S4, is churn D9 rules out.
4. **δ in or out.** **Default:** in, as a separate leaf, because fk-f126b1c9cbbe is high and γ alone leaves its SOH-resolution and envelope halves open. Dropping δ leaves γ unchanged.
5. **Absorbed tasks.** **Default:** at decompose, cancel 209, 568 and 632 with `metadata.x_superseded_by = <leaf id>` and a pointer in the reason (they are absorbed, not accepted), after contract §8 step 1.
6. **D3 mid-term.** **Default:** no leaf now (§11); the lead files a design follow-up after S3 and S11, or leaves it to the next review.
7. **Flat tariff + grid charging.** **Default:** S11 adds a `TariffConfig` "has a cheap period" fact and the matching refusal arm in `build_dispatch_strategy`.
8. **Both levels set** (home-level `tou_optimized` and a battery strategy). **Default:** keep today's precedence (battery wins) until ε removes the home key; β does not refuse it. Measured: 3 existing tests build such homes (`test_unrecognised_keys.py`, `test_scenario_writer.py`, `test_web_history.py`), and the web fleet overlay can produce one, so refusing it now buys a transitional break for a field ε deletes.

### Tactical (decide in the leaf)

1. Exact refusal wording, within §5.3's required names.
2. Whether `parse_home_block` reads the home key through the fleet reader generalised or a sibling reader (one constant either way).
3. Where the pre-α stored-run fixture lives (`tests/fixtures/stored_runs/` if S19 has created it).

## 13. Proposed cross-reference lines (for the lead to apply to other PRDs)

- S3: "Deletes `home.simulate_home`'s `use_tariff_tou` predicate and `_runs_tariff_tou` (moved from S2's deletable list); builds on S2's `GridChargeContext.target_soc_kwh` and Battery answers; depends on S2 α and γ."
- S11: "Makes `dispatch.TOUOptimizedStrategyConfig.peak_hours` an optional override (`None` = the tariff's cheap periods) with D7's contradiction check, and adds that arm to `dispatch.build_dispatch_strategy`; depends on S2 α. Optionally adds the flat-tariff grid-charging refusal arm (S2 §12 Q7). S2 ε depends on this leaf."
- S27: "Calls `dispatch.build_dispatch_strategy(community_battery.dispatch_strategy or SelfConsumptionStrategyConfig(), grid_charging=..., tariff=billing.tariff)` from `CommunityConfig.__post_init__` and `simulate_community`; depends on S2 α and β."
- S5: "Moves `parse_dispatch_strategy_config` and `_parse_grid_charge_config` into `scenario_blocks.py`; they construct `dispatch` types and define none."
- S4: "Invariant 1's fixture walks `dispatch.GridChargeConfig`, `SelfConsumptionStrategyConfig`, `TOUOptimizedStrategyConfig`, `PeakShavingStrategyConfig` (not `config.DispatchStrategyConfig`)."
- S19: "`_deserialize_value`'s tagged-union rule (S2 §5.6) is part of the stored-run format; the format version covers S2 α's shape change and ε's removed home key."
- S18: "The fleet form's dispatch vocabulary renders from `dispatch.STRATEGY_CONFIG_BY_TYPE`."
- S29: "Release section and consumer recipe include S2 §5.8; S2 ε is a held leaf released in the bump window."
- S1: "S2 α depends on S1-β (`ConfigurationError(ValueError)`), not only S1-α: α moves the public strategy constructors from `ValueError` to `ConfigurationError`."
