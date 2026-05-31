# Capability manifest — TOU grid-charging / battery arbitrage (P4)

Mechanizes G3 (substrate exists) + G6 (premise valid) per leaf. Each asserted
capability binds to evidence: `grep:file:line wired` (present substrate),
`producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` (numeric/limit claim with its basis). PRD:
`docs/prds/tou-grid-charging-battery-arbitrage.md`.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, or `bound≤floor`. The two cross-PRD substrates (correct
SEG/import pricing; serialised `home.py` edits) are the single queued prereq
**task #2**, with hard dependency edges wired (δ→#2, ε→#2). All intra-batch
producers (`grid_charge_kw`, `GridChargeContext`, the controller,
`GridChargeConfig`, `BatteryConfig.grid_charging`, split accounting) are queued
with wired edges (α2/α3/γ→α; γ→β; ε/δ→γ).

## α — DISPATCH-CORE (decision channel + controller) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `DispatchDecision` is a frozen dataclass extensible with `grid_charge_kw` | grep:`dispatch.py:15-41` wired | ✅ |
| `battery.charge_efficiency`/`discharge_efficiency` exist for the round-trip term | grep:`battery.py:104-105` wired | ✅ |
| Controller is pure floats — imports no tariff symbol (two-`TariffPeriod` defence) | design: `GridChargeContext` local to `dispatch.py`; no `tariff` import | ✅ |
| `decide_action` ABC signature can carry a new keyword-only param mypy-compatibly | grep:`dispatch.py:60-86` (ABC) wired; α updates all 3 overrides | ✅ |
| Signal = controller spread/target/residual logic + `DispatchDecision` validation | unit test on `compute_grid_charge_power_kw` + `DispatchDecision` (own task) | ✅ |

## α2 — TOU-GRID-CHARGE — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `compute_grid_charge_power_kw` + `GridChargeContext` callable | **producer:task-α** — dep α2→α wired | ✅ |
| `DispatchDecision(grid_charge_kw=…)` constructs | **producer:task-α** — dep α2→α wired | ✅ |
| `TOUOptimizedStrategy.decide_action` exists + classifies off-peak | grep:`dispatch.py:269-344` wired | ✅ |
| Signal = TOU returns `grid_charge_kw>0` off-peak w/ favourable ctx, `0` otherwise | unit test (decision-level, no flow/pricing) (own task) | ✅ |

## α3 — PEAKSHAVE-GRID-CHARGE — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `compute_grid_charge_power_kw` + `GridChargeContext` + `grid_charge_kw` | **producer:task-α** — dep α3→α2 (→α) wired (serialises `dispatch.py`) | ✅ |
| `PeakShavingStrategy.decide_action` exists + discharge threshold logic | grep:`dispatch.py:380-447` wired | ✅ |
| Signal = grid-charges cheap below-threshold, `0` while shaving / no-ctx | unit test (decision-level) (own task) | ✅ |

## β — GRIDCHARGE-CONFIG — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `BatteryConfig` frozen + `TYPE_CHECKING` optional-config pattern | grep:`battery.py:10-26` wired | ✅ |
| `_parse_battery_config` reads the `battery:` block | grep:`config.py:598-614` wired | ✅ |
| `config.py` imports no `dispatch.py` (no import cycle from a new config dataclass) | grep:`config.py:23` (imports `battery`, not `dispatch`) wired | ✅ |
| Signal = YAML `battery.grid_charging.target_soc_fraction` round-trips; bad ⇒ `ConfigurationError`; omit ⇒ `None` (field-population + validation) | unit test on `_parse_battery_config` (own task) | ✅ |

## γ — FLOW-SPLIT-ACCOUNTING — intermediate (the H boundary)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `validate_energy_balance` invariant to preserve | grep:`flow.py:336-390` wired | ✅ |
| `simulate_timestep_tou` / `simulate_timestep` are the two execution sites | grep:`flow.py:229`, `flow.py:134` wired | ✅ |
| Controller + `GridChargeContext` + `DispatchDecision.grid_charge_kw` | **producer:task-α** — dep γ→α wired | ✅ |
| `BatteryConfig.grid_charging` readable via `battery.config` | **producer:task-β** — dep γ→β wired | ✅ |
| `battery.charge` caps at `max_charge_kw` (charge-power floor) | grep:`battery.py:168` wired | ✅ |
| Floor: total charge power ≤ `max_charge_kw`/step | floor: controller residual clamp `min(gap_power, max_charge − pv_charge_power)` (§3.2) | ✅ |
| Premise: balance closes with grid-charge active | floor: algebraic proof §3.1 (`gen+shortfall=demand+excess`); re-checked every timestep | ✅ |

## ε — HOME-STRATEGY-WIRING — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `simulate_timestep` accepts a `tariff` param | **producer:task-γ** — dep ε→γ wired | ✅ |
| `home.simulate_home` strategy branch calls `simulate_timestep` at `home.py:290` | grep:`home.py:289-297` wired | ✅ |
| `home.py`/`test_home.py` edits serialised behind #2's financial-accounting edits | **producer:task-2 upstream** — dep ε→#2 wired (file-lock serialisation) | ✅ |
| Signal = strategy-path home grid-charges (SOC rises overnight) + balance holds | integration test on `simulate_home` (own task, post-#2) | ✅ |

## δ — ARBITRAGE-ECONOMICS — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Function-path grid-charge produces the flows | **producer:task-γ** — dep δ→γ wired | ✅ |
| Export priced at SEG / import at tariff so `net_cost` moves correctly | **producer:task-2 upstream** (the pricing fix) — dep δ→#2 wired; **NOT** an independent P4 claim | ✅ |
| `simulate_home(weather_data=…)` injection for a fast no-PVGIS A/B | grep:`home.py:180`, `home.py:195` wired | ✅ |
| `calculate_summary` produces `net_cost_gbp` | grep:`home.py:438-440` wired (read-only; #2 owns the values) | ✅ |
| Numeric: `net_cost(on) < net_cost(off)` | floor: `Δnetcost ≈ E·(r_off − r_peak·rt_eff) < 0` exactly when the controller's spread gate fired (§12); scenario gives the battery a real peak to discharge into | ✅ |
| `config validate` accepts `battery.grid_charging` keys | **producer:task-β** (the parser) — dep δ→γ→β wired | ✅ |
