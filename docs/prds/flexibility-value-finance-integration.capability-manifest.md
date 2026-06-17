# Capability manifest — Flexibility value → finance integration (W1)

Mechanizes G3 (substrate exists) + G6 (premise valid) per leaf. Each asserted
capability binds to evidence: `grep:file:line wired` (present substrate),
`producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` / band-membership (numeric/limit claim with its basis). PRD:
`docs/prds/flexibility-value-finance-integration.md`. Verified against `main` at
decompose 2026-06-17.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent` (unresolved), or `bound≤floor`. The single cross-PRD substrate
— the W2-owned `FinanceConfig.grid_services_income_per_kw_per_year_gbp` field —
is **absent on `main` today** (`grep` confirms: no `grid_services` symbol in
`src/solar_challenge/`), so it is bound as **producer:W2-CR1 upstream** with a
hard cross-batch dependency edge **δ→CR1** wired before any status flip (G3-b
resolution; mirror of the #2 precedent in the P4 manifest). All intra-batch
producers (`flex.py` value-model, the fleet-tariff threading) are queued with
wired edges (γ→α, γ→β, δ→α, ε→α). The board numeric assertions are **inequality
+ band-membership**, never point estimates (G6 branch-1 floor N/A — not an
accuracy bound on a numerical method).

## α — FLEX value-model module (`flex.py`) — intermediate (unlocks γ, δ, ε)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| New `flex.py` frozen dataclass(es) holding the Low/Central/High decomposition | new module — pure constants + resolver, **no novel substrate assumed** (G3 N/A) | ✅ |
| `resolve_grid_services_band(band) -> float` returns the £/kW rate | own-task deliverable; pure function | ✅ |
| Numeric: `resolve_grid_services_band("central") ≈ 12.0` £/kW; per-home totals (×~2.5 kW) match consulting §1.1 | band, not floor: values are **defined by** the consulting model (Low ~1.5 / Central ~12 / High ~48 £/kW = net per-home 4/30/120 ÷ ~2.5 kW); never above the High case | ✅ |
| Signal = unit test on the resolver + the three documented bands | unit test (own task) — exercises the product's own resolver, not synthetic input | ✅ |

## β — FLEET-TARIFF threading (`config.py`) — intermediate (unlocks γ)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `generate_homes_from_distribution` is the fleet-config factory to thread the tariff through | grep:`config.py:1387` wired; the hardcoded `tariff_config=None` gap is grep:`config.py:1579` (the exact site β fills) | ✅ |
| `_parse_tariff_config` builds a `TariffConfig` from a `tariff:` block | grep:`config.py:806` wired (already used by `_parse_scenario` at `config.py:1683`) | ✅ |
| Scenario-level `battery.grid_charging:` already parses into `GridChargeConfig` | grep:`config.py:737-754` wired (landed P4 #24) | ✅ |
| `HomeConfig`/`BatteryConfig` frozen ⇒ thread via construction, not mutation | grep:`config.py:2070-2092` (resolved-home construction sites carry `tariff_config`) wired | ✅ |
| Signal = `fleet_distribution` + `tariff: economy_7` ⇒ homes `tariff_config != None` + grid-charging; no `tariff:` ⇒ `None` | unit test (own task); the **θ guard** is the regression assertion (absent ⇒ bit-identical) | ✅ |
| Invariant (calibration-safe): absent ⇒ behaviour bit-identical to `tariff_config=None` today | floor: default code path unchanged; θ/#48 (`bristol-fin-calibration.yaml`, no `tariff:`) untouched | ✅ |

## γ — BOARD scenario + annual time-shift figure (integration gate) — leaf · prereqs α, β

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Grid-charge dispatch path (`compute_grid_charge_power_kw` / `simulate_timestep_tou`) executes the arbitrage | grep:`flow.py` wired (landed P4 #23/#27); proven `net_cost ON<OFF` by #29 | ✅ |
| Per-timestep TOU import pricing lowers `total_import_cost` on cheap-rate charge | grep:`home.py:322-323` (`r.grid_import * rate`) wired | ✅ |
| Fleet inherits the TOU tariff + grid-charging at scale | **producer:task-β** — dep γ→β wired | ✅ |
| Time-shift expected band (for validation) sourced from the value-model | **producer:task-α** — dep γ→α wired | ✅ |
| `validate_energy_balance` invariant holds across the run | grep:`flow.py` (the landed balance check) wired | ✅ |
| Numeric: per-battery-home time-shift delta ∈ **[£100, £330]** + `net_annual_bill(ON) < (OFF)` | **band-membership + inequality, NOT a point estimate** (G6); Economy-7 spread 0.16 £/kWh × usable battery × annual cycles brackets the band; inequality mechanism proven by #29. No analytical-floor violation (not an accuracy bound). | ✅ |

## δ — GRID-SERVICES parameter → economics (seam gate) — leaf · prereqs α, **W2-CR1 (out-of-batch)**

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `FinanceConfig.grid_services_income_per_kw_per_year_gbp` (the field δ sets on the scenario) | **producer-absent on main today** (grep: no `grid_services` in `src/solar_challenge/`) ⇒ bound **producer:W2-CR1 upstream**; cross-batch dep **δ→CR1** wired before flip | ✅ (resolved) |
| `flex.resolve_grid_services_band` supplies the £/kW value | **producer:task-α** — dep δ→α wired | ✅ |
| Per-config multiplier `home.battery_config.max_discharge_kw` | grep:`config.py:2160` (resolved homes) + `config.py:264` (default 2.5) wired | ✅ |
| Numeric: grid-services £/kW ~1.5/12/48 | PASS within consulting §1.1/§1.4 bounds; never above the High case | ✅ |
| Numeric: selecting band ∈ {low,central,high} moves project surplus by ≈ `Σ max_discharge_kw × {1.5,12,48}`; default/unset θ-bit-identical | the consuming math (`Σ kW × £/kW`) is **W2-owned** (CR2); δ asserts the field **moves the number** and the default leaves economics + θ identical — additive, default 0.0 | ✅ |

## ε — BUILDABILITY / risk note (`docs/`) — leaf · prereq α

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The banded value-model summary to document | **producer:task-α** — dep ε→α wired | ✅ |
| Prerequisites (P483 aggregator, MID asset meters, NGED CMZ confirmation, G99/G100) + the one HIGH risk | cite consulting §1.3/§2/§5 + survey §9 — **assessed, not built** (G3 N/A) | ✅ |
| Signal = doc committed at the path, lists 4 prerequisites + HIGH risk, linked from PRD + `flex.py` docstring | documentation deliverable (own task) | ✅ |
