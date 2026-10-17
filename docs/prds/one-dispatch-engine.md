# PRD — One dispatch engine: shared settle tail and bounded decisions (review-all stream S3)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S3** (wave 2, size M, risk medium, upstream S2). Findings record `plans/review-all-solar_challenge-20261013.json`, run `review-all-solar_challenge-20261013`.
- **Status:** authored 2026-10-16 (author only, uncommitted), awaiting the lead's rulings on §12 before commit and decompose.
- **Binding rulings:** D6 (`simulate_timestep_tou` is retired into a TOU strategy object run through `simulate_timestep`, with one settle function and one grid-charge gate; the byte-identical tail goes; rides the bump), D3 (mid-term, every dispatcher supports grid charging), D29 (additive and behaviour edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line; renames and retirements are held leaves released by S29), D4 (one coordinated bump, no shim survives the program). Lead rulings L6 (S3 owns routing the home-level key and deleting the tariff-TOU route), L8 (the D3 follow-up is filed after S3 and S11), L15 and L16 (anchors drifted after task 710; the engine checks go through S4's `Interval.admits` and depend on S4 α). Cross-reference lines: "S3 (from S2 decompose)", "S3 (from S4)", "S3" (deletes `use_tariff_tou`/`_runs_tariff_tou`, builds on S2 γ).
- **Approach:** **B + H**. The change is in the core engine (flow, dispatch, battery, home), touches the frozen surface, moves board-facing figures, and feeds S2 ε, S21, S27 and S29. §5 is the contract, §9 the two-way boundary tests.
- **Code anchors** verified against main `1fa8f796e87b608e6ee0ca9e8c62f377370203a7` (2026-10-16), cited by symbol. Main moves fast; re-locate lines at implementation time.

Finding keys (all `simulation-core`, all confirmed): fk-4df47ebe6a96 (medium, structural), fk-491014934d1e (medium, mechanical, filed as task 270), fk-7440003fdd59 (**high**, structural), fk-2a53ae89932e (medium, structural), fk-f622bbaa9f2e (medium, structural). δ also carries S4's fk-a9c609ecb8ef (high), which closes when S4 ι and S3 δ land (L16).

---

## 1. Goal

A home's battery is dispatched by one mechanism: a `DispatchStrategy` decides, `flow.simulate_timestep` checks the decision against what the step allows, the battery executes it, and one settle function turns what the battery exchanged with the home's bus into the step's flows. The flows are bus energies, so a charge loss is never reported as export and grid charging imports what the battery drew.

**What a user observes when this lands:**

1. `solar-challenge home run scenarios/bristol-arbitrage.yaml --start 2024-01-15 --end 2024-01-15 -o day.csv` writes a CSV whose grid import sums to **7.958723 kWh** (today 7.904248), grid export to **0.000000 kWh** (today 0.003741, all of it charge loss), grid charge to **2.178983 kWh** (today 2.124508) and import cost to **£1.341602** at the file's restated 0.09/0.25 rates (today £1.336699), or **£1.894444** once S11 γ (task 841) re-prices it to 0.13/0.35 (today at those rates £1.887363). A default Bristol home (4 kWp, `BatteryConfig.default_5kwh()`, 3,400 kWh, 2024) stops exporting **33.161 kWh** a year it never exported, 1.97% of its export, valued today at the SEG rate. Board figures move the same way: SEG income down, import cost up, basis-C own-use down for grid-charging homes.
2. A library consumer's strategy that asks for more than the step allows is refused by name before the battery moves: `charge_kw=5, grid_charge_kw=5` on a 2.5 kW battery raises `ValueError` naming `grid_charge_kw`, 5.0 and the 0.0 kW the charge limit leaves after `charge_kw` (today it stores 4.875 kWh in an hour, twice the hardware limit times efficiency); `discharge_kw=2.5` against a 1.0 kW shortfall names `discharge_kw`, 2.5 and 1.0 (today `Energy balance violated: in=0.000000 kWh, out=-1.500000 kWh`, and nothing at all with `validate_balance=False`); `DispatchDecision(charge_kw=nan)` is refused naming `charge_kw` (today accepted).
3. `TOUOptimizedStrategy` and `PeakShavingStrategy` size their grid charge from the state of charge after the step's PV charge, as the inline TOU path does: on an Economy 10 day whose battery drains in the morning peak, the strategy route grid-charges the same 5.045223 kWh as the inline path (today 5.047494: 2.27 Wh too much in one minute).
4. A home-level `dispatch_strategy: tou_optimized` home runs `TOUOptimizedStrategy` on the tariff's clock through `simulate_timestep`, producing the same flows as today's inline path (equal within 1e-9 kWh per minute; measured 1.8e-15), and `home.py` no longer reaches `simulate_timestep_tou`. At the program's bump (S29), `simulate_timestep_tou` leaves the public surface; the consumer recipe replaces it with `simulate_timestep(..., strategy=TOUOptimizedStrategy(tariff=tariff), tariff=tariff)`.

## 2. Background

### 2.1 What exists today (measured at `1fa8f79`)

- **Two engines.** `flow.simulate_timestep` asks a strategy for one `DispatchDecision` from the pre-step SOC, then calls `battery.charge(charge_kw)`, `battery.charge(grid_charge_kw)` and `battery.discharge(discharge_kw)`. `flow.simulate_timestep_tou` decides inline: in a cheap period it charges excess PV first, then sizes the grid top-up with `compute_grid_charge_power_kw` from the **post-PV** SOC and `pv_charge_power_kw = min(excess, max_charge_kw)`; in an expensive period it discharges on shortfall and charges excess PV. `home._dispatch_path` (task 710) sends a home to `_tariff_tou_timestep` (the inline path) when the home-level key is `tou_optimized`, it has a tariff and its battery names no strategy; otherwise to `_strategy_timestep`.
- **The tail is duplicated.** The 23-line settlement (charge sum, self-consumption cap, the 3-line split-source comment, export and import, `EnergyFlowResult`) is byte-identical in both functions (`diff` of the two ranges prints nothing), and so is the duration/excess/shortfall preamble apart from the TOU path's rate lookup. Task 270 (pending, blocked behind deferred task 183) asks for the extraction.
- **The gate is duplicated and fed differently.** `TOUOptimizedStrategy.decide_action` and `PeakShavingStrategy.decide_action` each carry the same block: grid-charge when the context is set, the period is cheap and the decision does not discharge, via `compute_grid_charge_power_kw(..., battery_soc_kwh=<pre-step SOC>, pv_charge_power_kw=charge_kw)`. The pre-step basis ignores the PV the same step stores.
- **The decision is unbounded.** `DispatchDecision.__post_init__` checks only `< 0` (NaN and inf pass) and charge/discharge exclusivity. Nothing bounds `charge_kw` by the excess PV, `discharge_kw` by the shortfall, or `charge_kw + grid_charge_kw` by the charge limit; `Battery.charge` clamps each call separately. The PeakShaving docstring line "the battery layer clamps downstream" is already gone (commit `a73de35`).
- **Charge losses leave the accounts.** `Battery.charge` returns the energy **stored** (after `charge_efficiency`), `Battery.discharge` the energy **delivered** (after `discharge_efficiency`). Settlement subtracts stored PV from export and adds stored grid energy to import, so the PV charger's loss is reported as export and grid charging imports less than it drew. `validate_energy_balance` closes on the stored basis with no loss term, so it passes. `docs/prds/tou-grid-charging-battery-arbitrage.md` §3.1 kept this "pre-existing and preserved".
- **Engine inputs are checked in three polarities** (fk-a9c609ecb8ef): the three `decide_action` methods each repeat a five-check `< 0`/`<= 0` block; `battery._require_valid_request` refuses NaN but accepts inf; `simulate_timestep` checks none of its inputs.

### 2.2 Probes run for this PRD on `1fa8f79` (`uv run --locked --extra dev python -I`)

| Probe | Today |
|---|---|
| Consumer strategy `DispatchDecision(5, 0, 5)`, 10 kWh battery at 1.0 kWh, `max_charge_kw` 2.5, PV 10 kW, one 60-minute step | stores **4.875 kWh** (2 × 2.5 × 0.975); balance passes |
| `DispatchDecision(2.5, 0, 0)` with no PV, 60 minutes | stores 2.4375 kWh from nowhere; balance `in=0.000000, out=2.437500` |
| `DispatchDecision(0, 2.5, 0)` against a 1.0 kW shortfall, 60 minutes | delivers 2.5 kWh, 1.5 kWh in no flow; balance `in=0.000000, out=-1.500000` |
| `DispatchDecision(charge_kw=nan)`, `(charge_kw=inf)` | both constructed |
| One step, Economy 10 at 14:00, PV 2.0 kW, demand 0.5 kW, 10 kWh battery at 5.98 kWh, `GridChargeConfig(0.6)` | inline path: no grid charge, SOC 6.004375; strategy path (`TOUOptimizedStrategy` clocked by the tariff): **0.01625 kWh** grid charge, SOC 6.020625, above the 6.0 target |
| One synthetic Economy 10 day (2024-06-21; PV `3·sin(π(h−5)/16)` kW between 05:00 and 21:00; demand 0.4 kW plus 3.5 kW 06:00-13:00 and 1.5 kW 17:00-20:00), 10 kWh, 2.5 kW, `GridChargeConfig(0.6)`, SOC0 ∈ {1.0, 4.0, 5.9}: inline vs tariff-clocked strategy, per-minute flows ("the morning-drain E10 day" below) | pre-step gate (today): max difference **2.271e-03 kWh** in one minute, grid charge 5.047494 vs 5.045223 (SOC0 1.0); post-PV gate (β emulated): max difference **1.776e-15 kWh**. `TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])`, Economy 10's expensive hours, gives the same 5.047494 today |
| The same day without the morning drain, on E7 and E10, and two synthetic June days through `simulate_home` (target 0.9 and 0.6) | equal flows on both gates: the overshoot needs a gap-limited approach in a cheap minute with PV charging |
| `solar-challenge home run scenarios/bristol-arbitrage.yaml`, 2024-01-15, cached Bristol TMY | import 7.904248, export 0.003741, battery charge 2.270412, grid charge 2.124508 kWh, import cost £1.336699, grid-charge cost £0.191206 |
| The same flows settled on drawn energy (dispatch is unchanged: `Battery.charge`'s state update does not change, only what it reports) | import **7.958723**, export **0.000000**, battery charge 2.328628, grid charge **2.178983** kWh, import cost **£1.341602**, grid-charge cost £0.196108; at S11 γ's 0.13/0.35 (same dispatch: the spread gate and cheap minutes are unchanged) import cost £1.887363 today, **£1.894444** settled on drawn energy |
| Bristol 2024, 4 kWp, `default_5kwh`, 3,400 kWh stochastic seed 42 | export 1,683.931 kWh, of which **33.161 kWh** (1.97%) is PV charge loss |

### 2.3 Re-measure of the five findings on `1fa8f79` (freshness clause)

Since `7dfea36e`, `flow.py` and `dispatch.py` changed only in prose (`a73de35`: the TOU PRD named by path, the Frame and Seam notes dropped), `battery.py` only in prose (`7821620`), and `home.py` through task 710 (`_dispatch_path`, `_tariff_tou_timestep`, `_strategy_timestep`, `_minute_flows`). Each finding re-observes: the tail and preamble are still duplicated (now 23 lines; the 7-line NOTE became a 3-line comment at both sites); the gate block is still in both strategies with the pre-step basis; `DispatchDecision` still checks only signs; settlement is still on stored energy; `Battery.charge` still clamps per call. The finding text's `use_tariff_tou` is now `home._dispatch_path`'s first branch and `_tariff_tou_timestep`. None is weakened.

### 2.4 Already-filed tasks this PRD meets

| Task | Status | Relation |
|---|---|---|
| 270 | pending (blocked on deferred 183) | The settle extraction. **Superseded** by α (`x_superseded_by`), after contract §8 step 1. |
| 183 | deferred (human risk notice esc-183-3) | Its finished branch adds a PV-aware grid-charge ceiling *inside* `simulate_timestep_tou`; ε turns that function into a delegate, so the branch cannot merge as written. §12 Q4. |
| 382 | pending | Its `DispatchDecision` row (`< 0` guards) is δ's (S4 decision 11); S4's decompose cancels 382 naming its own leaves. §13. |
| 659, 672 | pending | Duration bounds in `decide_action`, `compute_grid_charge_power_kw`, `Battery` (659) and `flow` (672). They stay (S4 decision 11); δ's helper calls whatever form they leave. Textual overlap, no edge. |
| 231 | pending | Perfect-forecast disclosure for 183's ceiling; unaffected. |

## 3. How this PRD reads the rulings

- **D6.** One engine: `simulate_timestep`. One settle function (`_settle`) and one grid-charge gate (`_grid_charge_kw` over `compute_grid_charge_power_kw`). The inline decision code goes at ε; the public name `simulate_timestep_tou` is a retirement, so under D29 it is a held leaf (ζ) released by S29. Between ε and the bump it is a one-call delegate, which cannot drift.
- **D3.** The gate is strategy-agnostic: a dispatcher supports grid charging by calling `_grid_charge_kw`. When L8's follow-up gives `SelfConsumptionStrategy` a policy, it calls the gate and S2's refusal arm for `self_consumption` goes; nothing here pre-empts that policy.
- **D29.** α-ε land in-leaf. β, γ, δ and ε change what public names return, so each adds its "Unreleased on main" line; γ also adds one to `docs/cost-recovery-finance-model.md`'s header (it changes what finance-model names return). Only ζ edits the frozen tables.
- **L6, L15, cross-reference lines.** ε routes the home-level key through S2's factory and S11 β's tariff-clock arm and deletes `_runs_tariff_tou` (787) and the tariff-TOU branch of `_dispatch_path`. The cross-reference "a tariff-clocked `TOUOptimizedStrategy` reproduces `simulate_timestep_tou` on `bristol-arbitrage.yaml`" is true on that file but not in general (§2.2): it becomes general once β sizes the grid charge from the post-PV SOC, so ε depends on β.
- **L16.** δ's checks go through `Interval.admits` and `NON_NEGATIVE` (S4 α) and raise `ValueError` (computed values, S4's C4).
- **Program row wording** "`DispatchDecision.__post_init__` bounds `charge_kw + grid_charge_kw` against the battery's charge limit and discharge against the shortfall": a decision is built by a strategy that never sees the battery's limit or the step's shortfall as fields, and `decide_action`'s signature is frozen (the platform implements it). So `__post_init__` takes the context-free bounds (each power finite and ≥ 0), and the step bounds live in one `dispatch.StepLimits` check that `simulate_timestep` applies to every decision before the battery moves (§5.4, §12 Q2). "Settlement on pre-efficiency energy with the loss term carried into `validate_energy_balance`": §6 decision 1 and §12 Q1.

## 4. Sketch of approach

1. **One settle function (α).** `flow._StepEnergies` computes the preamble once; `flow._execute` runs a decision against the battery and returns a `_BatteryExchange`; `flow._settle` is the only producer of derived flows. Both functions build their step through `_StepEnergies` and return through `_settle`; `simulate_timestep` executes through `_execute`, and the inline path, which sequences its own battery calls until ε, builds its `_BatteryExchange` from them. Behaviour-preserving.
2. **One grid-charge gate (β).** `compute_grid_charge_power_kw` measures the gap from the SOC after the decision's PV charge; `dispatch._grid_charge_kw` is the one gate both strategies call; one `_charge_headroom_kw` expression serves the controller and δ's bound.
3. **Bus settlement (γ).** `Battery.charge` reports the energy it drew from the bus, as `Battery.discharge` reports what it delivered. `_settle` is unchanged in form and becomes right: export is the excess the battery did not draw, import adds what it drew from the grid. Every flow in `EnergyFlowResult` is then a bus energy.
4. **Bounded decisions and engine checks (δ).** `DispatchDecision` refuses non-finite or negative powers; `StepLimits.require_admissible` refuses a decision that exceeds the step; `simulate_timestep` refuses non-finite or negative inputs; the strategies' copied input block becomes one function; all through `Interval.admits`.
5. **One route (ε).** The home-level `tou_optimized` key maps to `TOUOptimizedStrategyConfig()` (the tariff's clock) and runs through the factory and `simulate_timestep`; `simulate_timestep_tou` delegates to the same.
6. **Retire the name (ζ, held for S29).**

## 5. Contract

### 5.1 The engine (`flow.py`; α shape, γ basis, δ checks)

```python
@dataclass(frozen=True)
class _StepEnergies:                 # α: the preamble, once
    duration_hours: float
    generation_kwh: float
    demand_kwh: float
    excess_kwh: float                # max(0, generation - demand)
    shortfall_kwh: float             # max(0, demand - generation)

@dataclass(frozen=True)
class _BatteryExchange:              # α: what the battery exchanged with the bus this step
    pv_charge_kwh: float             # γ: drawn from PV, before charge losses
    grid_charge_kwh: float           # γ: drawn from the grid, before charge losses
    discharge_kwh: float             # delivered, after discharge losses

def _execute(decision: DispatchDecision, battery: Battery, timestep_minutes: float) -> _BatteryExchange
def _settle(step: _StepEnergies, exchange: _BatteryExchange, battery_soc_kwh: float) -> EnergyFlowResult
```

- `simulate_timestep` keeps its frozen signature. Order: build `_StepEnergies` (δ: refuse `generation_kw`/`demand_kw` unless `NON_NEGATIVE.admits`, before any battery call) → no battery: `_settle(step, zero exchange, 0.0)` → decide (S2 γ's arguments) → δ: `StepLimits(...).require_admissible(decision, strategy.name)` → `_execute` → `_settle`.
- `_settle` is the settlement rule (the program seam S3 owns), pure, and the only place derived flows are computed:
  - `battery_charge = pv_charge + grid_charge`; `grid_charge` as given;
  - `self_consumption = min(min(generation, demand) + discharge, demand)`;
  - `grid_export = max(0, excess - pv_charge)`; `grid_import = max(0, shortfall - discharge) + grid_charge`.
- **Balance by construction.** Whenever `pv_charge ≤ excess` and `discharge ≤ shortfall` (δ's bounds make every executed step so), `generation + grid_import = demand + grid_export + battery_charge - battery_discharge` is an identity of `_settle`. `validate_energy_balance` stays as the redundant check, its formula unchanged; its stale 20-line derivation comment is replaced by one sentence naming `_settle`.
- `_execute` makes the three Battery calls in today's order (PV charge, grid charge, discharge), skipping a zero power, so α changes no float. Until ε, `simulate_timestep_tou` keeps its own battery calls (PV first, then the grid top-up sized from the post-PV SOC) and passes what they returned to `_settle` as a `_BatteryExchange`.

### 5.2 The battery's port and the flows' basis (γ)

- `Battery.charge(power_kw, duration_minutes) -> float` returns the energy it **drew** from the bus, before `charge_efficiency`; its state of charge rises by that energy times `charge_efficiency`, capped at `max_soc_kwh`. When the cap binds, it draws only what it can store (`stored / charge_efficiency`). Signature and clamping unchanged; the state update is unchanged, so no dispatch decision changes.
- `Battery.discharge` is unchanged: it returns the energy delivered after `discharge_efficiency`. Both methods now report the energy that crossed the bus.
- **Storage identity** (per step and over a run): `Δsoc_kwh = charge_efficiency × drawn − delivered / discharge_efficiency`.
- `EnergyFlowResult`, `SimulationResults` and `SummaryStatistics` keep every field name and type. `battery_charge` / `total_battery_charge_kwh` is the energy the battery drew from the bus; `grid_charge` / `total_grid_charge_kwh` the part drawn from the grid, a part of both `battery_charge` and `grid_import` (`SummaryStatistics.__post_init__`'s check holds unchanged). At the default efficiency both read 2.56% higher than today (1 / 0.975).
- Readers that need no change because every flow is now on one basis: `validate_energy_balance`, community's aggregate balance (`community.py`), `home._price_imports` (grid-charge cost now prices the grid energy bought), S21's Sankey identities (`total_pv_charge_kwh = charge − grid_charge`, `total_grid_to_demand_kwh = import − grid_charge`), finance (reads import, import cost, export, export revenue and discharge only).

### 5.3 One grid-charge gate (`dispatch.py`; β)

```python
def _charge_headroom_kw(max_charge_kw: float, charge_kw: float) -> float:
    """The charge power the battery's limit leaves after charge_kw of PV charging."""
    return max(0.0, max_charge_kw - min(charge_kw, max_charge_kw))

def compute_grid_charge_power_kw(ctx, *, battery_soc_kwh, pv_charge_power_kw, timestep_minutes) -> float  # S2 γ's signature
def _grid_charge_kw(ctx: GridChargeContext | None, *, battery_soc_kwh: float, charge_kw: float,
                    discharge_kw: float, timestep_minutes: float) -> float
```

- `compute_grid_charge_power_kw` keeps its three gates and signature. Gate 3 measures the gap from `battery_soc_kwh + min(pv_charge_power_kw, ctx.max_charge_kw) × dt_h × ctx.charge_efficiency`, the SOC after this step's PV charge, computed in `Battery.charge`'s operation order. When PV charging is capped by the battery's ceiling the predicted SOC overshoots it, but S2 γ caps `target_soc_kwh` at `max_soc_kwh`, so the gap is 0 either way. Its residual is `_charge_headroom_kw(ctx.max_charge_kw, pv_charge_power_kw)`.
- `_grid_charge_kw` returns 0.0 when `ctx is None` or `discharge_kw > 0` (a decision may not grid-charge while discharging), else the controller. The redundant `ctx.is_cheap_period` test in the copied blocks goes (gate 1 holds it). `TOUOptimizedStrategy` and `PeakShavingStrategy` call it; `SelfConsumptionStrategy` calls it when L8's follow-up gives it a policy.
- With β, a tariff-clocked `TOUOptimizedStrategy` through `simulate_timestep` reproduces the inline path's decisions to float rounding (§2.2: 1.8e-15 kWh per minute).

### 5.4 Bounded decisions and engine checks (`dispatch.py`, `flow.py`, `battery.py`; δ)

```python
@dataclass(frozen=True)
class StepLimits:
    """What one step's decision may ask of the battery, in kW."""
    excess_kw: float        # PV beyond demand: the most charge_kw may take
    shortfall_kw: float     # demand beyond PV: the most discharge_kw may give
    max_charge_kw: float    # the battery's charge limit, which PV and grid charging share
    def require_admissible(self, decision: DispatchDecision, strategy_name: str) -> None: ...
```

- `DispatchDecision.__post_init__` refuses each of `charge_kw`, `discharge_kw`, `grid_charge_kw` unless `NON_NEGATIVE.admits` it (negative, NaN, ±inf), naming the field and `{value!r}`; the two exclusivity checks stay.
- `StepLimits.require_admissible` raises one `ValueError` naming the strategy and, for each breach, the field, its value and its limit: `charge_kw` within `[0, excess_kw]`; `discharge_kw` within `[0, shortfall_kw]`; `grid_charge_kw` within `[0, _charge_headroom_kw(max_charge_kw, charge_kw)]`. `charge_kw` above `max_charge_kw` stays admissible (a PV offer the battery clamps; every built-in strategy offers the whole excess).
- `simulate_timestep` builds the limits in kW with the expressions the strategies use (`max(0.0, generation_kw - demand_kw)`, `battery.max_charge_kw` from S2 γ), so built-in decisions pass exactly; it checks before `_execute`, so a refused step leaves the battery unchanged. `Battery.charge`'s per-call clamp stays, now the second check.
- The contract is stated once, on `DispatchStrategy.decide_action`'s docstring (the extension point), pointing at `StepLimits`.
- `simulate_timestep` refuses a `generation_kw` or `demand_kw` that `NON_NEGATIVE.admits` rejects, naming it, before any battery call.
- The three `decide_action` input blocks become one `_require_valid_strategy_inputs(generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh)` through `Interval.admits` (`NON_NEGATIVE` for the first three, `POSITIVE` for capacity), keeping today's message substrings; the timestep check stays in whatever form tasks 659 and 672 leave it.
- `battery._require_valid_request`'s power rule goes through `NON_NEGATIVE` (§12 tactical T2 on the documented "inf asks for the maximum rate").

### 5.5 One route (`home.py`, `flow.py`; ε)

- `home._dispatch_strategy_config(config) -> DispatchStrategyConfig`: the battery's own strategy config if set (battery-level precedence stands, L7); else `TOUOptimizedStrategyConfig()` (no `peak_hours`: the tariff's clock, S11 β) when `config.dispatch_strategy == "tou_optimized"`; else `SelfConsumptionStrategyConfig()`. `HomeConfig.__post_init__`'s factory step (787) and `simulate_home` both read it, so construction and run choose the same dispatcher. S2 ε (790) deletes its home-key arm.
- 787's tariff-TOU step and `_runs_tariff_tou` go: its refusals now arrive from the factory, S11 β's "no clock" refusal (a TOU strategy without a tariff or `peak_hours`, naming `tou_optimized` and the missing tariff) and S11's flat-tariff grid-charging arm.
- `home._tariff_tou_timestep` and the tariff-TOU branch of `_dispatch_path` go; every home with a battery runs `build_dispatch_strategy(...)` through `_strategy_timestep`; `SimulationResults.strategy_name` stays `tou_optimized` for these homes.
- `flow.simulate_timestep_tou` keeps its frozen signature and becomes `return simulate_timestep(generation_kw, demand_kw, battery, timestep_minutes, timestamp, TOUOptimizedStrategy(tariff=tariff), tariff=tariff)`; its docstring says it is retired at the next release and names the replacement call.
- `review/briefing.yaml`'s dispatch key_decision (as 787 leaves it) becomes "One dispatch engine: every dispatcher is a `DispatchStrategy` run through `flow.simulate_timestep` with one settle function and one grid-charge gate"; the comment in `scenarios/bristol-arbitrage.yaml` naming "the function path (simulate_timestep_tou ...)" is corrected (S2 ε migrates its key).

### 5.6 Retirement (ζ, held for S29)

`simulate_timestep_tou` leaves `flow.py`, `__all__`, `_SYMBOL_MODULE` and the lazy-import table; `FROZEN_SURFACE` loses its entry; the 21 call sites in `tests/unit/test_flow.py` move to `simulate_timestep(..., strategy=TOUOptimizedStrategy(tariff=tariff), tariff=tariff)`, and tests that only pinned the two-path equivalence go with the name.

### 5.7 Surface ledger for S29 (D4, D29)

| Leaf | Change ("Unreleased on main" line, in-leaf unless held) | Consumer action |
|---|---|---|
| β | `compute_grid_charge_power_kw` sizes the grid charge from the SOC after the step's PV charge; `TOUOptimizedStrategy` and `PeakShavingStrategy` no longer overshoot their target in a cheap minute with PV charging | none (the platform never calls it) |
| γ | `Battery.charge` returns the energy it drew, before `charge_efficiency`; `simulate_timestep`'s export no longer includes charge losses and its import includes the grid energy the battery drew; `battery_charge` and `grid_charge` (and their `SimulationResults`/`SummaryStatistics` totals) are drawn energies, 1/`charge_efficiency` times today's | Platform: re-read any stored-basis assumption on `battery_charge`; board figures move (cost-recovery header line) |
| δ | `DispatchDecision` refuses NaN and infinite powers; `simulate_timestep` refuses a negative or non-finite `generation_kw`/`demand_kw`, and a decision whose `charge_kw` exceeds the step's excess, whose `discharge_kw` exceeds its shortfall, or whose `grid_charge_kw` exceeds the charge headroom left after `charge_kw`, with `ValueError` naming the strategy, the field, the value and the limit | Platform: a custom strategy that breaks a bound is refused instead of over-charging or losing energy |
| ε | A home-level `tou_optimized` home runs `TOUOptimizedStrategy` on the tariff's clock through `simulate_timestep`; `simulate_timestep_tou` delegates to the same (flows equal within 1e-9 kWh per minute) and is retired at the next release | none until ζ |
| ζ (held) | `simulate_timestep_tou` removed | Platform: call `simulate_timestep(..., strategy=TOUOptimizedStrategy(tariff=tariff), tariff=tariff)` |

## 6. Resolved design decisions

1. **The battery reports bus energy; the flows are bus energies (γ).** The defect's root is an asymmetric port: `charge` reported stored energy, `discharge` delivered energy, and settlement mixed the two. Making `charge` report what it drew puts every `EnergyFlowResult` flow on the bus, so the bus balance closes with no loss term and every bus reader (validator, community check, grid-charge pricing, S21's Sankey identities) is right without an edit. The loss is the battery's internal business, checked by the storage identity (§5.2) where it lives. The alternative the program row and the finding name, keeping `battery_charge` stored and adding a loss field that `validate_energy_balance` carries, keeps two bases in one record and puts a loss term into four readers in lock-step (validator, community check, grid-charge pricing, Sankey's grid-to-demand), each of which silently re-opens the defect if it forgets it. §12 Q1.
2. **Bounds refuse, not clamp (δ).** A clamp would turn a consumer strategy's bug into silently different physics (the no-silent-fail-soft rule); the refusal names the field and the limit. Built-in strategies never trip it (§9 row 12). The finding left the choice explicit; the program row's "bounds … so `Battery.charge`'s clamp is a second check" reads as a check.
3. **Step bounds live on `StepLimits`, not in `DispatchDecision.__post_init__` (δ).** The decision has no excess, shortfall or charge limit to compare with, and `decide_action`'s signature is frozen. `__post_init__` takes the context-free bounds. §12 Q2.
4. **`charge_kw` may exceed `max_charge_kw`; the grid headroom is computed from `min(charge_kw, max_charge_kw)` (β, δ).** That is how every built-in strategy offers PV, and the same `_charge_headroom_kw` expression in the controller and the bound means a decision the controller produced always passes the bound (no ulp-level disagreement).
5. **The gate predicts the post-PV SOC rather than the engine executing in two phases (β).** The inline path's sequencing (charge PV, then size the grid top-up) is reproduced exactly by one prediction in the controller, which already models the battery's charge with `ctx.charge_efficiency`; a two-phase decision would change `decide_action`, which the platform implements.
6. **ε delegates instead of keeping the inline code until ζ.** One decision mechanism from ε on, so the inline path cannot drift; the equivalence is pinned by a characterisation test written against the inline code at ε's base before the switch (§9 row 13), measured at 1.8e-15 kWh per minute with β.
7. **The settle function is private.** It is the program's settlement seam inside the engine; consumers reach it through `simulate_timestep`. `StepLimits` stays out of `__all__` too; the contract is documented on `decide_action`.
8. **No new loss field.** A summary or report line for battery losses has no named consumer today (G1); losses are derivable from the bus flows and the SOC series, and the storage-identity test pins them.

## 7. Pre-conditions

- **S2:** 786 (α: dispatch types, `build_dispatch_strategy`, `TOUOptimizedStrategyConfig`), 788 (γ: `Battery.max_charge_kw`, `Battery.grid_charge_target_kwh`, `GridChargeContext.target_soc_kwh`, `compute_grid_charge_power_kw` without `capacity_kwh`, flow reads Battery answers), 787 (β: `HomeConfig.__post_init__`'s factory step and `_runs_tariff_tou`, which ε deletes).
- **S11 β, task 839** (the tariff-clock arm: `TOUOptimizedStrategy(peak_hours=None, *, tariff=)`, `TOUOptimizedStrategyConfig.peak_hours` optional, the no-clock and flat-tariff refusals), filed by the S11 decompose (which also wired 790 → 839): before ε.
- **S4 α** (`solar_challenge.number_fields.Interval`, `NON_NEGATIVE`, `POSITIVE`), authored in `docs/prds/finite-quantities.md`, not yet filed: before δ.
- **S29's bump window:** ζ.

G3: every symbol §5 names as existing was read at `1fa8f79` (capability manifest); the four cross-stream substrates above are queued prerequisites wired at decompose.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S2 dispatch configuration | consumes | `build_dispatch_strategy`, `TOUOptimizedStrategyConfig`, `Battery.max_charge_kw`, `GridChargeContext.target_soc_kwh`, `HomeConfig.__post_init__`'s factory step | S2 types / S3 engine | α → 786, 788; β → 788; ε → 787; **790 (S2 ε) → ε** (790 depends on ε, as 790's own text and S2 §10's DAG say) |
| S11 tariff | consumes | the tariff-clock arm and `TOUOptimizedStrategy(tariff=)` (839, S11 β); `tariff.is_cheap_at` read by `_build_grid_charge_context` (838, S11 α); S11 γ (841) re-prices `bristol-arbitrage.yaml` | S11 arm / S3 routing | ε → 839; S11 α's edits of `simulate_timestep_tou` and `_build_grid_charge_context` overlap α textually |
| S4 finite quantities | consumes | `Interval.admits`, `NON_NEGATIVE`, `POSITIVE` for δ's checks; S4 θ freezes `EnergyFlowResult` | S4 rule / S3 engine checks | δ → S4 α; θ overlaps α and γ in `flow.py` textually; fk-a9c609ecb8ef closes at S4 ι + S3 δ |
| S21 charts | produces for | γ: `battery_charge`/`grid_charge` are bus energies, so S21 ε's three summary identities hold with no loss term; δ: discharge ≤ shortfall is checked at use on every executed step | S3 | no edge (S21 reads the totals) |
| S27 community | produces for | community steps go through δ's bound and γ's bus settlement; its aggregate balance check needs no change | S3 engine / S27 call sites | no edge |
| S10 window | shares | γ1 edits home's timestep closures (after ε only `_strategy_timestep` remains); η drops `timestep_minutes = 1.0` defaults, skipping `simulate_timestep_tou` if ζ removes it in the same window | S10 (η) | textual overlap; both η and ζ held for S29 |
| S28 battery facts | shares | `battery.py` text; throughput is discharged energy, which γ leaves unchanged | S28 | no edge |
| S8, S25 finance and reports | produces for | γ lowers export and SEG income by the PV charge loss and raises import and import cost by the grid charge loss; basis-C own-use falls for grid-charging homes | S3 (γ's header line in `docs/cost-recovery-finance-model.md`) | no edge |
| S19 run store | touches | runs stored before γ keep stored-basis charge and the phantom export; field names unchanged, no format change | — | none |
| S29 surface bump | produces for | §5.7 ledger; ζ held | S29 | ζ held |
| Task 270 | supersedes | the settle extraction | α | cancel with `x_superseded_by` |
| Task 183 | conflicts | its branch edits `simulate_timestep_tou`'s cheap branch | — | §12 Q4 |
| Tasks 659, 672 | shares | duration checks in the same functions δ edits | 659, 672 | no edge; whichever lands second rebases |

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Faces | Leaf |
|---|---|---|---|---|---|
| 1 | One settlement | main after α | `tests/unit/test_flow.py` passes unchanged; `flow.py` constructs `EnergyFlowResult` once, in `_settle` | flow | α |
| 2 | PV charge loss is not export | 1 kW excess PV for 60 minutes into a 10 kWh, 2.5 kW battery at 2.0 kWh | `battery_charge` 1.000, SOC rise 0.975, `grid_export` 0.000 (today 0.975 / 0.975 / 0.025) | battery, flow | γ |
| 3 | Grid charging imports what it drew | one cheap Economy 7 hour, no PV, no demand, `TOUOptimizedStrategy` + E7, 10 kWh battery at `min_soc_kwh`, `GridChargeConfig(0.9)` | `grid_import` 2.500 and `grid_charge` 2.500 kWh, SOC rise 2.4375 (today 2.4375 / 2.4375) | battery, flow, dispatch | γ |
| 4 | Storage identity | one synthetic day with PV charging, grid charging and discharge, known initial SOC | `soc_end − soc_start = η_c·Σbattery_charge − Σbattery_discharge/η_d` within 1e-9 kWh (today off by 0.025·Σstored) | battery, flow | γ |
| 5 | Charge capped at the ceiling | battery 0.01 kWh below `max_soc_kwh`, 2 kW excess, 1 minute | SOC = `max_soc_kwh`; `battery_charge` = 0.01 / 0.975; `grid_export` = excess − that | battery | γ |
| 6 | Bus balances still close | `bristol-arbitrage` home over 2024-01-15 with `sunless_weather`; `test_community_fleet`'s community fixture | `validate_energy_balance` passes every minute; community aggregate balance passes; `SummaryStatistics` builds | flow, home, community | γ |
| 7 | Gate on the post-PV SOC | §2.2's one-step E10 case; §2.2's morning-drain E10 day (SOC0 1.0) through `simulate_timestep` with `TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])` and E10; the same with `PeakShavingStrategy` | no grid charge in the step (today 0.01625 kWh); day grid charge equals `simulate_timestep_tou`'s within 1e-9 kWh (today +2.27 Wh); with either strategy, a step that grid-charges ends at or below the target (PV alone may pass it) | dispatch, flow | β |
| 8 | Over-limit sum refused | consumer strategy `(5, 0, 5)`, 2.5 kW battery, PV 10 kW | `ValueError` naming the strategy, `grid_charge_kw`, 5.0 and 0.0; SOC unchanged | dispatch, flow | δ |
| 9 | PV charge above the excess refused | `(2.5, 0, 0)` with no PV | `ValueError` naming `charge_kw`, 2.5 and 0.0 (today 2.4375 kWh from nowhere) | dispatch, flow | δ |
| 10 | Discharge above the shortfall refused | `(0, 2.5, 0)` against 1.0 kW | `ValueError` naming `discharge_kw`, 2.5 and 1.0 (today `out=-1.500000`) | dispatch, flow | δ |
| 11 | Non-finite decision and inputs refused | `DispatchDecision(nan, 0)`, `(inf, 0)`; `simulate_timestep(nan, 1.0, battery)` | each raises naming the field; the battery's SOC is unchanged | dispatch, flow, battery | δ |
| 12 | Built-in strategies never trip a bound | each built-in strategy over §9 row 6's day and two synthetic June days on E7 and E10, with and without grid charging | no refusal; flows equal pre-δ | dispatch (producer), flow | δ |
| 13 | One route reproduces the inline path | characterisation at ε's base: `bristol-arbitrage` home on 2024-01-15 (`sunless_weather`) and §2.2's morning-drain E10 day, inline `simulate_timestep_tou` vs the home's new route | every minute's flows equal within 1e-9 kWh; `strategy_name` `tou_optimized` | home, flow, dispatch; S11's arm | ε |
| 14 | Refusals arrive through the factory | home-level `tou_optimized` with a battery and no tariff; with a flat tariff and `grid_charging` | `ConfigurationError` naming `tou_optimized` and the tariff; naming `grid_charging` (787's and S11's tests unchanged) | home, dispatch | ε |
| 15 | Retirement | after ζ | `solar_challenge.simulate_timestep_tou` and `flow.simulate_timestep_tou` are gone; the surface test names the removal; the recipe's call reproduces row 13's flows | surface, consumer | ζ |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`, `metadata.files`; priority is the highest severity among its keys. Leaves α-ε add their §5.7 "Unreleased on main" line in-leaf (D29); only ζ edits the frozen tables.

**α — One settle function both engines return through** (intermediate; unlocks γ, δ, ε; priority medium)
- Keys: fk-491014934d1e. Supersedes task 270.
- Work: §5.1 shape (`_StepEnergies`, `_BatteryExchange`, `_execute`, `_settle`); both functions call them; one copy of the split-source comment; `validate_energy_balance`'s derivation comment replaced by a pointer to `_settle`. Behaviour-preserving.
- Files: `src/solar_challenge/flow.py`, `tests/unit/test_flow.py` (additions only).
- Signal: unlocks γ (one function to change basis in) and ε (one tail); §9 row 1.
- Prereqs: 786, 788.

**β — One grid-charge gate sized from the SOC after the step's PV charge** (intermediate; unlocks δ, ε; priority medium)
- Keys: fk-4df47ebe6a96.
- Work: §5.3; the two copied blocks become `_grid_charge_kw` calls; docstrings of `compute_grid_charge_power_kw` and both strategies; Unreleased line (§5.7 β).
- Files: `src/solar_challenge/dispatch.py`, `tests/unit/dispatch/test_grid_charge_controller.py`, `tests/unit/dispatch/test_tou_optimized_strategy.py`, `tests/unit/dispatch/test_peak_shaving_strategy.py`, `docs/domain-library-consumption.md`.
- Signal: `simulate_timestep` with `TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])` (Economy 10's expensive hours, so β needs no S11 leaf) and `tariff=TariffConfig.economy_10()`: §2.2's one-step case stores no grid energy (today 0.01625 kWh); §2.2's morning-drain E10 day from SOC 1.0 grid-charges 5.045223 kWh, the inline path's figure (today 5.047494); §9 row 7. Unlocks ε's equivalence.
- Prereqs: 788.

**γ — Settle on the energy the battery drew: charge losses leave export and enter import** (leaf; priority **high**)
- Keys: fk-7440003fdd59.
- Work: §5.2; `Battery.charge`'s return and docstring; `_BatteryExchange` and `_settle` names say drawn; docstrings of `EnergyFlowResult`, `SimulationResults` (`battery_charge`, `grid_charge`) and `SummaryStatistics.total_grid_charge_kwh`'s comment; the split-source comment points at this PRD; §9 rows 2-6 as `tests/unit/test_battery_energy_accounts.py`; existing tests that pinned stored-basis charge or export (measured at implementation; `test_flow.py`, `test_battery.py`, `test_home_grid_charging.py`, `test_community.py` lead the count) re-derive their expectations; `review/briefing.yaml`'s energy-balance convention says charge and discharge are bus energies and points at the storage-identity test; Unreleased lines in `docs/domain-library-consumption.md` and the header of `docs/cost-recovery-finance-model.md`, the latter carrying the measured before/after of `scenarios/bristol-phase1-flex.yaml`'s board figures (SEG income, import cost, basis-C own-use); re-capture §7 of that document if its physics figures move.
- Files: `src/solar_challenge/{battery,flow,home}.py`, `tests/unit/test_battery_energy_accounts.py`, `tests/unit/test_flow.py`, `tests/unit/test_battery.py`, `tests/unit/test_home_grid_charging.py`, `tests/unit/test_community.py`, other tests found pinning the stored basis, `review/briefing.yaml`, `docs/domain-library-consumption.md`, `docs/cost-recovery-finance-model.md`.
- Signal: `solar-challenge home run scenarios/bristol-arbitrage.yaml --start 2024-01-15 --end 2024-01-15 -o day.csv` sums grid import 7.958723 kWh, export 0.000000, grid charge 2.178983 kWh (today 7.904248, 0.003741, 2.124508; cached Bristol TMY), and import cost £1.341602 at the file's 0.09/0.25 (today £1.336699) or £1.894444 if S11 γ (841) has re-priced it to 0.13/0.35 (today £1.887363); §9 rows 2-6.
- Prereqs: α.

**δ — Bounded decisions and engine checks through `Interval.admits`** (leaf; priority **high**)
- Keys: fk-2a53ae89932e, fk-f622bbaa9f2e, fk-a9c609ecb8ef (engine half, L16).
- Work: §5.4; the decision contract on `decide_action`'s docstring; Unreleased line (§5.7 δ); §9 rows 8-12 as `tests/unit/dispatch/test_decision_bounds.py`. Covers task 382's `DispatchDecision` row.
- Files: `src/solar_challenge/{dispatch,flow,battery}.py`, `tests/unit/dispatch/test_decision_bounds.py`, `tests/unit/dispatch/test_dispatch_decision.py`, `tests/unit/dispatch/test_*_strategy.py`, `tests/unit/test_flow.py`, `tests/unit/test_battery.py`, `docs/domain-library-consumption.md`.
- Signal: §9 rows 8-11: a library consumer's over-limit strategy is refused naming the field, value and limit with the battery unchanged (today 4.875 kWh stored in an hour; `out=-1.500000`); `DispatchDecision(charge_kw=nan)` refused (today accepted). Row 12: no built-in strategy trips a bound.
- Prereqs: α, β (`_charge_headroom_kw`), S4 α.

**ε — Route the home-level `tou_optimized` through the factory; `simulate_timestep_tou` delegates** (intermediate; unlocks ζ and S2's 790; priority medium)
- Keys: fk-4df47ebe6a96.
- Work: write §9 row 13's characterisation test against the inline path at the leaf's base first, then §5.5; delete `_runs_tariff_tou`, `_tariff_tou_timestep` and the tariff-TOU branch of `_dispatch_path`; §9 row 14; the briefing key_decision and the scenario comment; Unreleased line (§5.7 ε).
- Files: `src/solar_challenge/{home,flow}.py`, `tests/unit/test_one_dispatch_engine.py`, `tests/unit/test_home_dispatch.py`, `tests/unit/test_home_grid_charging.py`, `tests/unit/test_grid_charge_refusals.py`, `scenarios/bristol-arbitrage.yaml` (comment), `review/briefing.yaml`, `docs/domain-library-consumption.md`.
- Signal: `solar-challenge home run scenarios/bristol-arbitrage.yaml` over 2024-01-15 writes the same CSV as at the leaf's base within 1e-9 kWh per cell, through `simulate_timestep`; `home.py` names neither `simulate_timestep_tou` nor `_tariff_tou_timestep`; §9 rows 13-14.
- Prereqs: α, β, 787, 839 (S11 β).

**ζ — Retire `simulate_timestep_tou` at the bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "the surface bump release window"}`, excluded from this batch's `commit_planning`)
- Keys: fk-4df47ebe6a96.
- Work: §5.6; the frozen tables in `tests/unit/test_public_api_surface.py`; this leaf's line in the release section S29 opens.
- Files: `src/solar_challenge/{flow,__init__}.py`, `tests/unit/test_flow.py`, `tests/unit/test_one_dispatch_engine.py`, `tests/unit/test_public_api_surface.py`, `docs/domain-library-consumption.md`.
- Signal: §9 row 15.
- Prereqs: ε; S29 releases it.

DAG: {786, 788} → α; 788 → β; α → γ; {α, β, S4 α} → δ; {α, β, 787, 839} → ε; ε → ζ (held); ε → 790. Intra-batch edges: γ→α, δ→α, δ→β, ε→α, ε→β, ζ→ε. γ and δ (high) join the trigger-chain gate 772's dependencies at decompose.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`), screened against dark-factory's trigger shapes: α, β and ε remove lock-step copies (`no-lockstep-duplication`), and one headroom expression serves the controller and the bound (`one-fact-one-home`); δ replaces silent over-charge and vanishing energy with named refusals (`no-silent-fail-soft`); γ removes the loss-term lock-step a stored-basis record would need; ζ is a hold with an owner (S29) and a bound (the bump window). No hit.

## 11. Out of scope

- **Grid charging under every dispatcher (D3 mid-term).** L8's follow-up chooses `SelfConsumptionStrategy`'s policy; with it, the strategy calls `_grid_charge_kw` and S2's refusal arm goes. The community battery's half is S27's.
- A battery-loss field or report line (no consumer; §6 decision 8).
- **Self-consumption counts discharged grid energy.** `_settle`'s `self_consumption = min(direct + discharge, demand)` counts the battery's discharge whatever charged it, so a grid-charging home's self-consumption ratio exceeds 1 (`bristol-arbitrage.yaml` on 2024-01-15 reports 317%). Not among this stream's keys; returned to the lead as a candidate (§12 Q6).
- Duration bounds (tasks 659, 672; S10's cadence).
- Re-stating runs stored before γ.
- 183's PV-aware ceiling (§12 Q4).

## 12. Open questions

### Lead-level (rulings needed before commit; each has a default the PRD is written to)

1. **Charge basis (γ).** The program row says "settlement computed on pre-efficiency energy with the loss term carried into `validate_energy_balance`"; the finding proposes keeping `battery_charge` stored and adding a loss field. **Default:** §6 decision 1: `Battery.charge` reports drawn energy and every flow is a bus energy, so no loss term is needed anywhere and four readers stay right without an edit; the storage identity test pins the loss. The cost: `battery_charge`/`grid_charge` values rise by 1/η (2.56% at default), stated in the Unreleased line. Alternative: stored `battery_charge` plus a `charge_loss` field (additive), with the loss term added to `validate_energy_balance`, community's aggregate check, `_price_imports` and S21's grid-to-demand identity.
2. **Where the decision bounds live (δ).** **Default:** context-free bounds in `DispatchDecision.__post_init__`, step bounds in `StepLimits.require_admissible`, applied by `simulate_timestep` before the battery moves, raising rather than clamping (§3, §6 decisions 2-3).
3. **Edge direction with 790.** The lead's brief says the routing leaf "add_dependency on 790", the wording L15 uses for S11's arm too; 790's own description and S2 §10's DAG make **790 depend on ε** (ε deletes `_runs_tariff_tou` before 790 deletes the home key; ε depending on held 790 would stall it to wave 4), and the S11 decompose read the same wording as 790 → 839. **Default:** `add_dependency(id=790, depends_on=ε)` and `add_dependency(id=ε, depends_on=839)` (the S11 decompose already wired 790 → 839 and lists "S3's routing leaf → β").
4. **Task 183.** Its finished branch (human notice esc-183-3, deferred) puts an oracle-forecast grid-charge ceiling in `simulate_timestep_tou`'s cheap branch; after ε that branch is gone. **Default:** 183 stays deferred with no edge; the lead annotates it that a revival re-plans the ceiling as an input of `TOUOptimizedStrategy` on the one engine.
5. **γ moves board figures.** **Default:** no human gate before γ merges: the deliberation put the high finding in this stream, and γ discloses through the cost-recovery header line with `bristol-phase1-flex.yaml`'s measured before/after. Alternative: hold γ's merge behind a human acknowledgement, as 183's notice did.
6. **Self-consumption of grid-charged discharge** (§11). **Default:** the lead files it as a candidate finding for the next run or a design follow-up; S3 does not act on it.

### Tactical (decide in the leaf)

1. **Bound tolerance (δ).** Default exact: the limits use the strategies' own expressions and the headroom function is shared. If a consumer strategy's ulp-level excess shows up, a 1e-9 kW tolerance on the upper bounds.
2. **`Battery.charge(inf)` (δ).** The docstring offers `inf` as "the maximum rate"; no `src` caller passes it. Default: refuse it through `NON_NEGATIVE` (one interval) with an Unreleased line; keep it only if a test or consumer shows a use.
3. Refusal wording within §5.4's required names; whether `_DispatchPath` survives ε as a one-field value.
4. The characterisation fixture's exact demand profile for §9 row 13 (default §2.2's morning-drain day).

## 13. Proposed cross-reference lines (for the lead to apply)

- S2: "790 (ε) depends on S3 ε, which deletes `_runs_tariff_tou`, `_tariff_tou_timestep` and `_dispatch_path`'s tariff-TOU branch; S3 ε does not depend on 790. S3 α depends on 786 and 788, S3 β on 788, S3 ε on 787."
- S11: "S3 ε depends on 839 (S11 β, the tariff-clock arm). A tariff-clocked `TOUOptimizedStrategy` reproduces `simulate_timestep_tou` on `bristol-arbitrage.yaml`, but not on a day whose battery approaches its target in a cheap minute with PV charging (measured: 2.27 Wh in one minute on an Economy 10 day); S3 β's post-PV gate makes the equivalence general (1.8e-15 kWh). S11 α's edits of `simulate_timestep_tou` and `_build_grid_charge_context` overlap S3 α textually."
- S4: "S3 δ depends on S4 α and takes `DispatchDecision`'s guards, the strategies' copied input block, `simulate_timestep`'s inputs and `battery._require_valid_request` through `Interval.admits` (decision 11). S4's cancellation of task 382 names S3 δ for its `DispatchDecision` row. S4 θ's freezing of `EnergyFlowResult` overlaps S3 α and γ in `flow.py` textually."
- S21: "After S3 γ, `battery_charge` and `grid_charge` are energies the battery drew from the bus, so ε's identities hold at the bus with no loss term. S3 δ checks discharge ≤ shortfall at use (`StepLimits`), before the battery moves, not at `DispatchDecision` construction; every executed step satisfies it."
- S27: "The community battery's steps go through S3 δ's bound check and γ's bus settlement; community's aggregate balance check needs no loss term."
- S10: "S10 η skips `simulate_timestep_tou` when S3 ζ removes it in the same bump window; S10 γ1's home timestep closures overlap S3 ε (after ε only `_strategy_timestep` remains)."
- S8, S25: "S3 γ lowers export and SEG income by the PV charge loss and raises import and import cost by the grid charge loss; basis-C own-use falls for grid-charging homes. `docs/cost-recovery-finance-model.md` carries γ's header line with `bristol-phase1-flex.yaml`'s before/after."
- S29: "Release section and consumer recipe include S3 §5.7: β, γ, δ and ε as Unreleased lines, ζ (`simulate_timestep_tou` removed; recipe `simulate_timestep(..., strategy=TOUOptimizedStrategy(tariff=tariff), tariff=tariff)`) as a held leaf released in the bump window."
- Tasks: "270 is superseded by S3 α at S3's decompose; 183's branch conflicts with S3 ε (S3 §12 Q4)."

## Gate record

- **G1 (consumers).** `_settle`, `_execute`, `_StepEnergies`: `simulate_timestep` (every home, fleet and community run) and, until ζ, `simulate_timestep_tou`. `_grid_charge_kw`, `_charge_headroom_kw`: `TOUOptimizedStrategy`, `PeakShavingStrategy`, `StepLimits`; L8's follow-up. Bus-basis `Battery.charge`: `_execute`. `StepLimits`: `simulate_timestep`; S21 ε relies on its discharge bound. `_dispatch_strategy_config`: `HomeConfig.__post_init__` and `simulate_home`; S2 ε edits it. The delegate: platform consumers until the bump. No mechanism without a named consumer.
- **G3 (substrate).** Read at `1fa8f79`: `simulate_timestep`, `simulate_timestep_tou`, `EnergyFlowResult`, `validate_energy_balance`, `Battery.charge`/`discharge`/`charge_efficiency`/`soc_kwh`, `compute_grid_charge_power_kw`, the two strategies' copied gate, `DispatchDecision`, `home._dispatch_path`, `_tariff_tou_timestep`, `_strategy_timestep`, `_minute_flows`, `_price_imports`, community's balance check. Queued: 786, 787, 788, 839 (filed), S4 α (authored, unfiled).
- **G4 (seams).** §8; the program's settlement seam is owned here; edge directions with 790 and 839 per §12 Q3.
- **G5.** B + H (core engine, ≥ 3 modules, frozen surface, four consuming streams).
- **G6 (premises).** Every number in §1 and §10's signals was measured on `1fa8f79` (§2.2) or follows from an identity named beside it: γ's figures from today's per-minute flows settled on drawn energy (dispatch unchanged because `Battery.charge`'s state update is unchanged); β's and ε's equivalence from the post-PV gate (measured 1.8e-15 kWh); δ's refusals are built by δ and observed by its tests; the storage identity follows from `Battery`'s update rules (float error ≪ 1e-9 kWh over a day). Other leaves leave γ's CLI energies unchanged: the scenario's SOH is 1.0 and its target equals `max_soc_fraction` (788), Economy 7 is two-rate (S11 α), no PV falls in its cheap minutes in January (β), and S11 γ's re-pricing to 0.13/0.35 keeps the spread gate open (0.35 > 0.13 / 0.950625) and the cheap minutes, so it moves only the cost, for which the signal gives both figures.
- **G7.** Advisory walk in §10; no hit.
- **META.** With §12's defaults, decompose-and-queue yields one engine, one settlement on one basis, one gate, checked decisions and one route, with no design question left to an implementer; §12's six questions are the lead's.
