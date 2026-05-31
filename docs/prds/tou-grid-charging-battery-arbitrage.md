# PRD — TOU grid-charging / battery arbitrage

- **Gap register item:** P4 (supersedes placeholder task #8)
- **Status:** active · authored 2026-05-31 (review `20260530T090214Z`)
- **Owner seam:** `flow.py` / `dispatch.py` TOU dispatch (gap-register §C). Adds the `GridChargeConfig` schema on `BatteryConfig` (battery.py) + its `config.py` parser.
- **Approach:** **B + H** (contracts + two-way boundary tests). High stakes: a core energy-flow change guarded by the energy-balance invariant, feeding the investor-viability net-cost case. See §8.
- **Consumes (do not re-touch):** SEG/import pricing from **task #2** (`home.py` financial accounting / `seg.py`). This PRD produces the energy *flows*; #2 prices them. Net-cost arbitrage benefit emerges from #2's accounting with no change to it.

---

## 1. Goal

Let the battery **charge from the grid during cheap TOU periods** so the stored cheap energy offsets expensive **peak-period** import. Today `flow.simulate_timestep_tou` charges the battery *only* from excess PV; grid-charging is a comment-only "future enhancement" (`flow.py:245`). After this PRD, a battery on a time-of-use tariff fills overnight at the off-peak rate and discharges into the evening peak, **reducing net cost** — and the energy-balance invariant still closes at every timestep.

**User-observable outcome:** a home on Economy 7 with a battery and grid-charging enabled reports a **lower `net_cost_gbp`** than the identical home with grid-charging off, for a scenario with evening peak demand the battery can cover — visible in the simulation summary, with `validate_energy_balance` passing at every one of the ~1440 timesteps/day.

## 2. Background

Two TOU dispatch surfaces coexist (briefing key_decision — *intentional*, not redundant):

1. **Rate-aware function path** — `flow.simulate_timestep_tou(generation_kw, demand_kw, battery, timestamp, tariff, timestep_minutes)` (`flow.py:229`). Uses **actual p/kWh rates** from `TariffConfig`. Selected by `home.simulate_home` when `HomeConfig.dispatch_strategy == "tou_optimized"` + a tariff is set + `BatteryConfig.dispatch_strategy is None` (`home.py:257`). **This is where the `flow.py:245` evidence lives.**
2. **Strategy-pattern path** — `dispatch.DispatchStrategy` subclasses return a `DispatchDecision`, executed by `flow.simulate_timestep` (`flow.py:134`). `TOUOptimizedStrategy` (`dispatch.py:180`) classifies peak/off-peak by **hour windows** (not rates). Selected when `BatteryConfig.dispatch_strategy` is set.

**Current cheap-period behaviour** (`flow.py:286-296`): charge from excess PV only; never discharge (preserve for peak); shortfall met by cheap grid. **Peak-period** (`flow.py:297-308`): discharge to meet shortfall, charge from excess PV. So the *discharge-at-peak* half already works — the missing half is **charging the battery from the grid while it's cheap** so there is stored energy to discharge.

**The two `TariffPeriod` symbols** (briefing hazard): `dispatch.TariffPeriod` is an **enum** (`PEAK`/`OFF_PEAK`); `tariff.TariffPeriod` is a **dataclass** (a rate window). They are unrelated. This PRD's controller in `dispatch.py` takes **floats only** and imports neither — see §3/§6, the structural defence against confusing them.

Review context: `review/reports/summary-20260530T090214Z.md` ("Battery grid-charging during cheap TOU periods absent (`flow.py:245`, comment-only)").

## 3. Sketch of approach

### 3.1 The energy-balance contract (load-bearing — H)

`validate_energy_balance` (`flow.py:336`) enforces, per timestep:

```
generation + grid_import = demand + grid_export + (battery_charge − battery_discharge)
```

It holds today because `grid_export = max(0, excess − battery_charge)` and `grid_import = max(0, shortfall − battery_discharge)`, which reduce to the identity `gen + shortfall = demand + excess`. The validator carries **no efficiency-loss term** — `battery_charge` is *stored* energy, and charge-efficiency loss already surfaces as phantom export in the PV path. That simplification is **pre-existing and preserved** (fixing it is out of scope — §10).

Grid-charging adds a second charge source. To keep the invariant closed, **charge must be split by source** and accounted asymmetrically:

```
battery_charge = pv_charge_stored + grid_charge_stored          # SOC / balance term (total stored)
grid_export    = max(0, excess  − pv_charge_stored)             # ONLY PV charge reduces export
grid_import    = max(0, shortfall − battery_discharge) + grid_charge_stored   # grid charge ADDS to import
```

**Proof it closes** (cheap period, `discharge = 0`):
```
LHS = gen + grid_import = gen + shortfall + grid_charge_stored
RHS = demand + grid_export + (battery_charge − 0)
    = demand + (excess − pv_charge_stored) + (pv_charge_stored + grid_charge_stored)
    = demand + excess + grid_charge_stored
gen + shortfall = demand + excess  ⟹  LHS = RHS  ∎
```
The existing single-source formula is the `grid_charge_stored = 0` special case, so the change is **backward-compatible** at the accounting layer. This is the **contract** every leaf inherits.

### 3.2 The rate-aware grid-charge controller (dispatch.py — single source of truth)

A **pure, float-only** function in `dispatch.py` decides how much to grid-charge. It imports neither `TariffConfig` nor `tariff.TariffPeriod` (structural defence against the two-symbol hazard); callers pass extracted floats bundled in a `dispatch.GridChargeContext` (a local frozen dataclass of floats/bools):

```python
@dataclass(frozen=True)
class GridChargeContext:
    current_rate: float          # £/kWh now
    peak_rate: float             # max period rate (the peak we arbitrage against)
    is_cheap_period: bool        # current_rate <= avg(period rates)
    target_soc_fraction: float   # fill ceiling, fraction of capacity
    max_charge_kw: float
    round_trip_efficiency: float # charge_eff * discharge_eff (real battery values)
    charge_efficiency: float

def compute_grid_charge_power_kw(
    ctx: GridChargeContext, *, battery_soc_kwh: float, capacity_kwh: float,
    pv_charge_power_kw: float, timestep_minutes: float,
) -> float:
    if not ctx.is_cheap_period: return 0.0
    if ctx.peak_rate <= ctx.current_rate / ctx.round_trip_efficiency: return 0.0   # spread test
    target_kwh = ctx.target_soc_fraction * capacity_kwh
    gap_kwh = max(0.0, target_kwh - battery_soc_kwh)
    if gap_kwh <= 0.0: return 0.0
    dt_h = timestep_minutes / 60.0
    gap_power_kw = gap_kwh / ctx.charge_efficiency / dt_h          # gross input power to store the gap
    residual_kw  = max(0.0, ctx.max_charge_kw - pv_charge_power_kw)  # share the inverter budget with PV charge
    return min(gap_power_kw, residual_kw)
```

- **Spread test:** grid-charge only when cheap energy, after **round-trip** loss, still beats the peak it offsets (`peak_rate > current_rate / round_trip_eff`). On a flat tariff `peak_rate == current_rate` ⟹ test fails ⟹ **zero grid-charge** (no behaviour change). Auto-disables when arbitrage is uneconomic.
- **Residual budget:** the grid top-up shares the `max_charge_kw` inverter limit with same-step PV charging, so total charge power in a timestep **never exceeds `max_charge_kw`** (G6 floor).
- `battery.charge()` re-applies real efficiency and caps at `max_soc_kwh`; the controller's job is the *request*.

### 3.3 Wiring (both dispatch paths)

- **Function path** (`flow.simulate_timestep_tou`): after PV charge, build a `GridChargeContext` from `battery.config.grid_charging` + the tariff rates + the real `battery` efficiencies, call the controller, `battery.charge(grid_power)`, apply §3.1 split accounting.
- **Strategy path** (per user decision — *explicit per-strategy*): `DispatchDecision` gains `grid_charge_kw: float = 0.0`; `decide_action` gains a keyword-only `grid_charge_ctx: Optional[GridChargeContext] = None`. `flow.simulate_timestep` (given a `tariff`) builds the context and passes it; **`TOUOptimizedStrategy` and `PeakShavingStrategy`** call the shared controller inside `decide_action` and return `grid_charge_kw`; `flow.simulate_timestep` executes it with the same §3.1 split accounting. `SelfConsumptionStrategy` accepts and **ignores** the context (it discharges on cheap-period shortfall, so grid-charge is inert under it).
- **home.py** threads `tariff=config.tariff_config` into the `simulate_timestep` call so the strategy path actually receives rates (one line in the dispatch-call region — **not** the financial-accounting block owned by #2).

### 3.4 Config surface

`GridChargeConfig` (frozen dataclass in `config.py`, beside `DispatchStrategyConfig`) as an **optional field on `BatteryConfig`** (`battery.py`): `grid_charging: Optional[GridChargeConfig] = None` (`None` = disabled = today's behaviour). It rides `battery.config` into `simulate_timestep_tou` with **zero new function args** on the function path. Parsed by `_parse_battery_config` (`config.py:598`) from a nested `battery.grid_charging:` YAML block.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Config home | nested `GridChargeConfig` on `BatteryConfig` (`grid_charging`, default `None`) | Grid-charging is battery dispatch behaviour; `BatteryConfig` already reaches `simulate_timestep_tou` via `battery.config` → zero new args, no `home.py` edit on the function path. *(user-confirmed)* |
| Arbitrage trigger | round-trip **spread test** + **target SOC** | Economically grounded; auto-disables on flat/shallow tariffs; pure-float controller is unit-testable in isolation. *(user-confirmed)* |
| Path coverage | **both** dispatch paths | Grid-charging must work whether TOU is configured via the function-path string or the Strategy-pattern `DispatchStrategyConfig`. *(user-confirmed)* |
| Strategy-path mechanism | **explicit per-strategy** via `DispatchDecision.grid_charge_kw` + `grid_charge_ctx` on `decide_action`; per-strategy serialized tasks | Transparent + per-strategy testable; discrete chained tasks on `dispatch.py` manage collision risk. *(user-confirmed)* |
| Grid-charge-capable strategies | `TOUOptimizedStrategy`, `PeakShavingStrategy` (not `SelfConsumption`) | Both preserve the battery during cheap periods, leaving room to grid-charge; self-consumption discharges on cheap shortfall → grid-charge inert. *(user-confirmed)* |
| Controller decoupling | floats only; lives in `dispatch.py`; imports no tariff symbols | Single source of truth for both paths; structurally avoids the two `TariffPeriod` symbols. |
| Period classification | `is_cheap = current_rate <= avg(period rates)`; `peak_rate = max(period rates)` | Reuses the existing `simulate_timestep_tou` heuristic; consistent across both paths. |
| Target SOC default | `target_soc_fraction = 0.9` (= default `max_soc_fraction`) | Fill the usable battery by default; PV-headroom tuning is a tactical knob (§11). |
| Backward compatibility | `grid_charging=None` ⟹ controller never invoked; `grid_charge_kw=0.0` default ⟹ split formulas reduce to the originals | Every existing flow/dispatch/home test stays green. |
| Efficiency-loss accounting in the balance | **unchanged** (preserved, not fixed) | The validator has no loss term today; introducing one would touch `validate_energy_balance` + the PV path — out of scope (§10). |

## 5. Pre-conditions for activating

- **Task #2 must land** before the *economics* signal (δ) and the *strategy-path home wiring* (ε): δ needs export priced at SEG / import at tariff for `net_cost` to move in the right direction; ε edits `home.py` (serialised behind #2's `home.py` edits). The mechanism tasks (α/α2/α3/β/γ) do **not** depend on #2 (their signals are balance/decision/parse correctness, not pricing).
- All engine substrate exists — see §6.

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `battery.charge(power_kw, minutes)` returns stored kWh, caps at `max_charge_kw` + `max_soc` | `battery.py:154-183` |
| `battery.charge_efficiency`, `battery.discharge_efficiency` (real round-trip) | `battery.py:104-105` |
| `battery.soc_kwh`, `battery.max_soc_kwh`, `battery.config.max_charge_kw`, `battery.config.capacity_kwh` | `battery.py:120-137`, `battery.py:22-23` |
| `tariff.get_rate(ts)`, `tariff.periods`, `period.rate_per_kwh` | `tariff.py:124-138`, `tariff.py:111`, `tariff.py:27` |
| `EnergyFlowResult` fields (`battery_charge`, `grid_import`, `grid_export`, …) | `flow.py:117-131` |
| `validate_energy_balance(result)` invariant | `flow.py:336-390` |
| `DispatchDecision` (frozen) + `decide_action` ABC + 3 strategies | `dispatch.py:15-41`, `dispatch.py:44-86`, `dispatch.py:89/180/347` |
| `simulate_timestep` executes a `DispatchDecision` | `flow.py:134-226` |
| `BatteryConfig` frozen + `_parse_battery_config` reads the `battery:` block | `battery.py:10-26`, `config.py:598-614` |
| `home.simulate_home(..., weather_data=...)` injection (fast, no-PVGIS economics test) | `home.py:180`, `home.py:195` |
| `config.py` does **not** import `dispatch.py` (so a `dispatch.py`-local `GridChargeContext` adds no import cycle) | `config.py` imports `battery`, not `dispatch` |

**Novel substrate introduced (queued within this batch, not assumed):** `DispatchDecision.grid_charge_kw`, `dispatch.GridChargeContext`, `dispatch.compute_grid_charge_power_kw`, `config.GridChargeConfig`, `BatteryConfig.grid_charging`, the `grid_charge_ctx` param on `decide_action`, and the `tariff` param on `simulate_timestep`. Each is produced by a named task below and consumed by a named downstream task — no orphan, no fiction. **G3 verdict: PASS.**

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **task #2** (SEG/import pricing, `home.py` + `seg.py`) | **consumes** | This PRD produces `grid_import`/`grid_export`/`battery_charge` flows; #2 prices them into `net_cost`. δ asserts the net-cost benefit; ε's `home.py` edit serialises behind #2's. | #2 owns all pricing; **P4 must not re-touch `home.py` financial accounting** | dep δ→#2, ε→#2 wired at decompose |
| P2 (web UI parity) | none | P2 surfaces tariff/dispatch/SEG inputs; it does **not** expose grid-charging. A future web toggle for `battery.grid_charging` is **out of scope here** and a candidate P2 follow-up. | — | no edge |
| P5 (community sharing) | none | P5 owns `fleet.py` aggregation; grid-charging is per-home dispatch, orthogonal. | — | no edge |
| task #8 | superseded | — | this PRD | #8 → cancel at decompose |

No reciprocal-ownership ambiguity: P4 owns the dispatch mechanism end-to-end; #2 owns pricing; the seam is the energy-flow series, already #2's input.

## 8. G5 note — why B + H

High stakes on two axes: (1) a **load-bearing invariant** (`validate_energy_balance`) that a naive grid-charge implementation silently breaks (subtract grid charge from export → import under-counts → imbalance), and (2) the arbitrage **net-cost** number feeds the investor case. → **B + H**:

- **Contract (B):** the §3.1 split-accounting equations and the §3.2 controller signature are the written contract every leaf binds to.
- **Two-way boundary tests (H):**
  - *flow ↔ invariant:* `validate_energy_balance` holds at **every** timestep with grid-charging active, on **both** dispatch paths (γ; ε for the strategy path end-to-end).
  - *controller ↔ flow:* the controller's decision is correctly consumed — grid-only charge (zero excess PV) raises `grid_import` by exactly the stored amount and `battery_charge` by the same, and charge power never exceeds `max_charge_kw` (γ).
  - *decision ↔ economics:* the produced flows, priced by #2, yield `net_cost(on) < net_cost(off)` for a constructed arbitrage scenario (δ).

## 9. Decomposition plan

Seven tasks. **dispatch.py** is edited only by the serialized chain **α → α2 → α3** (per-strategy, no concurrent edits — addresses the collision concern). **flow.py** only by γ; **config.py + battery.py** only by β; **home.py** only by ε (serialised behind #2). Per-task tests live in distinct modules to avoid test-file contention.

### α — Dispatch core: decision channel + rate-aware controller
- **Modules:** `dispatch.py` (+ `tests/unit/test_dispatch.py`)
- **Work:** add `grid_charge_kw: float = 0.0` to `DispatchDecision` (validate `>= 0`; forbid `grid_charge_kw > 0` with `discharge_kw > 0`; `grid_charge_kw` with `charge_kw` is allowed — both charge). Add frozen `GridChargeContext` (floats/bool). Add pure `compute_grid_charge_power_kw(...)` per §3.2. Add keyword-only `grid_charge_ctx: Optional[GridChargeContext] = None` to the `decide_action` **ABC and all three concrete signatures** (accept-and-ignore in α; logic added later) so mypy-strict override compatibility holds.
- **Classification:** intermediate — unlocks α2, α3, γ.
- **Verification signal:** unit tests — controller returns 0 when not cheap / spread fails (`peak ≤ current/rt_eff`) / at-or-above target; returns the residual-clamped gap power otherwise; `DispatchDecision(grid_charge_kw=…)` validates and rejects grid-charge-with-discharge; existing dispatch tests stay green (default `grid_charge_ctx=None`).

### α2 — TOUOptimizedStrategy grid-charging
- **Modules:** `dispatch.py` (+ `tests/unit/test_dispatch.py`)
- **Work:** in `TOUOptimizedStrategy.decide_action`, when `grid_charge_ctx` is provided and it's a cheap (off-peak) period with no discharge, call `compute_grid_charge_power_kw` (passing its own PV `charge_kw` as `pv_charge_power_kw`) and return `DispatchDecision(charge_kw=excess, discharge_kw=0, grid_charge_kw=<computed>)`.
- **Prereqs:** α (intra-batch, serialises `dispatch.py`).
- **Verification signal:** unit test — TOU `decide_action` with a favourable `GridChargeContext` during off-peak returns `grid_charge_kw > 0` (bounded by residual + gap); returns `0` when `grid_charge_ctx is None`, when the spread test fails, or during a peak period; no regression in existing TOU decision tests.

### α3 — PeakShavingStrategy grid-charging
- **Modules:** `dispatch.py` (+ `tests/unit/test_dispatch.py`)
- **Work:** same pattern in `PeakShavingStrategy.decide_action` — grid-charge during cheap periods when not discharging to shave, via the shared controller.
- **Prereqs:** α2 (serialises `dispatch.py` — chained after α2, **not** concurrent).
- **Verification signal:** unit test — PeakShaving `decide_action` grid-charges during a cheap period below the shave threshold given a favourable context; `0` when shaving (discharging), when `grid_charge_ctx is None`, or on spread-fail; existing peak-shaving tests green.

### β — Config schema + parser
- **Modules:** `config.py`, `battery.py` (+ `tests/unit/test_config.py`)
- **Work:** add frozen `GridChargeConfig` (`target_soc_fraction: float = 0.9`; `__post_init__`: `0 < target_soc_fraction <= 1`) in `config.py`; add `grid_charging: Optional[GridChargeConfig] = None` to `BatteryConfig` (battery.py, `TYPE_CHECKING` import like `dispatch_strategy`); parse a nested `battery.grid_charging:` block in `_parse_battery_config`.
- **Classification:** intermediate — unlocks γ.
- **Verification signal:** unit tests — YAML `battery.grid_charging.target_soc_fraction: 0.8` round-trips into `BatteryConfig.grid_charging`; out-of-range value raises `ConfigurationError`; omission ⟹ `None` (backward-compat); `BatteryConfig` stays frozen + picklable.

### γ — Flow integration: split accounting + both call sites
- **Modules:** `flow.py` (+ `tests/unit/test_flow.py`)
- **Work:** implement §3.1 split accounting (`pv_charge_stored` / `grid_charge_stored`) in **both** `simulate_timestep_tou` and `simulate_timestep`. In `simulate_timestep_tou`: build `GridChargeContext` from `battery.config.grid_charging` + tariff rates + real battery efficiencies, call the controller, `battery.charge(grid_power)`. Add keyword-only `tariff: Optional[TariffConfig] = None` to `simulate_timestep`; when present with `battery.config.grid_charging`, build the context, pass `grid_charge_ctx` to `decide_action`, and execute the returned `grid_charge_kw`.
- **Prereqs:** α (controller, `DispatchDecision.grid_charge_kw`, `GridChargeContext`, `decide_action` sig), β (`BatteryConfig.grid_charging`).
- **Verification signal (H boundary):** integration tests — with grid-charging configured, `validate_energy_balance` passes at **every** timestep (both functions); a grid-only-charge step (zero excess PV, cheap, below target) yields `battery_charge > 0`, `grid_import` up by exactly `grid_charge_stored`, `grid_export == 0`; total charge power ≤ `max_charge_kw`; with `grid_charging=None` / `tariff=None`, results are **bit-identical** to pre-PRD behaviour.

### ε — home.py strategy-path wiring
- **Modules:** `home.py` (+ `tests/unit/test_home.py`)
- **Work:** pass `tariff=config.tariff_config` into the `simulate_timestep` call (the `else` dispatch branch, `home.py:290`) so the Strategy-pattern path receives rates. Dispatch wiring only — **does not touch** the financial-accounting block (`home.py:310-318`, owned by #2).
- **Prereqs:** γ (needs the `tariff` param), **#2** (serialises `home.py` + `test_home.py` edits behind #2).
- **Verification signal:** integration test — a home with `BatteryConfig.dispatch_strategy = tou_optimized` + tariff + `grid_charging` grid-charges through `simulate_timestep` (battery SOC rises overnight from grid import) and energy balance holds end-to-end.

### δ — Arbitrage economics + demo scenario
- **Modules:** `scenarios/`, `tests/integration/` (new `test_grid_charge_arbitrage.py`)
- **Work:** commit a demo scenario (Economy 7 + battery + evening-peak load + `battery.grid_charging`). A/B test via `simulate_home` with **injected `weather_data`** (small synthetic frame, no PVGIS → fast/deterministic): same home, grid-charging on vs off, through #2's pricing.
- **Prereqs:** γ (function-path grid-charge), **#2** (SEG/import pricing so `net_cost` moves correctly).
- **User-observable signal (G6):** `net_cost_gbp(grid_charge_on) < net_cost_gbp(grid_charge_off)` for the scenario; `solar-challenge config validate` accepts the new `battery.grid_charging` keys; `validate_energy_balance` holds across the run.

> **Note for decompose-time:** the orchestrator does not yet consume `user_observable_signal` / `consumer_ref` / substrate-confirmed metadata; recorded for a future tracking session. Task #8 → cancel (superseded by α/α2/α3/β/γ/ε/δ). Mark any real-PVGIS test `slow` per task #11 (δ avoids PVGIS via injected weather).

## 10. Out of scope

- **Fixing the efficiency-loss accounting** in `validate_energy_balance` / the PV charge path (pre-existing simplification — preserved).
- **Re-touching `home.py` financial accounting / SEG pricing** → task #2.
- **Web exposure** of `battery.grid_charging` → candidate P2 follow-up (not wired here).
- **Per-home distribution sampling** of grid-charging in fleets (`BatteryDistributionConfig`) — v1 is a uniform `BatteryConfig` field.
- **Forecast/look-ahead optimal scheduling** — v1 uses the static `peak_rate = max(period rates)` reference + target-SOC fill, not a forecast of the next peak.
- **A new diagnostic time-series** for grid-charge energy in `SimulationResults`/`output.py`/web charts — grid-charge stays folded into `grid_import`; observable via SOC + import. (Adding a series would touch #2-adjacent `home.py` results assembly.)

## 11. Open questions (tactical — deferred, not design-blocking)

1. **Target SOC default vs PV headroom.** `target_soc_fraction = 0.9` fills the usable battery overnight, which can displace next-morning excess-PV storage (PV then exported at low SEG). A lower default (e.g. 0.7) leaves headroom but captures less arbitrage. Resolve empirically in δ; the field is configurable either way.
2. **Cheap-period classification edge cases.** `is_cheap = current_rate <= avg(rates)` treats a tariff with one cheap + many peak windows correctly, but a 3-tier tariff's "mid" rate lands on whichever side of the mean. Acceptable for v1; revisit if multi-tier scenarios appear.
3. **PeakShaving + grid-charge interaction** when the shave threshold and a cheap window overlap mid-step — α3 grid-charges only when not discharging-to-shave; confirm the precedence reads sensibly on a constructed scenario during α3.

## 12. G6 — premise validity of the asserted signals

- **δ numeric premise — `net_cost(on) < net_cost(off)`:** *achievable and producible from this batch's deps.* Mechanism: grid-charging imports `E` kWh at the off-peak rate `r_off` and offsets ≈`E·rt_eff` kWh of peak import at `r_peak`; net change ≈ `E·(r_off − r_peak·rt_eff)`, which is **negative whenever the controller's own spread gate fired** (`r_peak > r_off / rt_eff` ⟺ `r_peak·rt_eff > r_off`). The scenario is constructed so the battery can actually discharge the stored energy into a real evening peak (sufficient peak demand, sufficient capacity). Pricing correctness is owed to **#2** (wired dep), not asserted independently here. **Not a guess — it's the spread gate's own inequality.**
- **γ invariant premise — balance closes with grid-charging:** proven algebraically in §3.1; the leaf re-checks it at every timestep (the validator raises otherwise). **Producible by γ alone.**
- **γ floor — charge power ≤ `max_charge_kw`:** guaranteed by the controller's residual clamp (`min(gap_power, max_charge − pv_charge_power)`). **Producible by α+γ.**
- **No false exactness:** the spread test uses **real** battery efficiencies passed through the context (not an assumed constant), so the economic gate matches the physics the same run applies. **G6 pass.**
