# Capability manifest — Financial layer + battery fidelity (P6)

Mechanizes G3 (substrate exists) + G6 (premise valid) per leaf. Each asserted
capability binds to evidence: `grep:file:line wired` (present substrate),
`producer:task-X upstream` (queued prerequisite + wired dep), or
`floor:bound`/`identity:` (numeric/limit/exactness claim with its basis). PRD:
`docs/prds/financial-layer-battery-fidelity.md`.

**Batch verdict: PASS (one binding to confirm at decompose).** No binding
resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`,
or `bound≤floor`. The two cross-PRD substrates are **landed** (task #2 pricing on
`SummaryStatistics`; P3 `PVConfig.system_age_years` + wired `apply_degradation`) —
consumed read-only, not re-touched. All intra-batch producers (`BatteryConfig`
SOC/eff/aging, `compute_soh`, `FinanceConfig`, `FleetSummary` financial fields, the
`finance.py` functions) are queued with wired edges (β→α; δ→γ; ζ→β,ε; η→γ,ζ;
θ→δ,η). **One PASS-conditional binding:** `scipy.interpolate.PchipInterpolator`
import — bound below with a no-new-dep fallback; confirm at ζ/θ start.

---

## α — BATTERY-SOC-EFFICIENCY-CONFIG (gap 3) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `Battery.__init__` already validates SOC/efficiency (mirror onto `BatteryConfig`) | grep:`battery.py:73-108` wired | ✅ |
| `BatteryConfig` frozen + additive-field precedent (`dispatch_strategy`/`grid_charging`) | grep:`battery.py:11-29` wired | ✅ |
| `home.py:261`/`community.py:304` build `Battery(config.battery_config)` (config-read ⟹ no caller change) | grep:`home.py:261`, `community.py:304` wired | ✅ |
| `_parse_battery_config` reads the `battery:` block (extend; `efficiency` currently dropped) | grep:`config.py:626-655` wired | ✅ |
| Signal = YAML `battery.efficiency`/`min_soc`/`max_soc` change run round-trip-loss/usable-capacity; omit ⟹ bit-identical | integration test on a scenario run (own task); field-population: `Battery` reads the new fields on the production path | ✅ |
| Rejection: out-of-range SOC/eff raises | `__post_init__` mirrors `battery.py:94-106`; authored in α; observed by constructing bad value | ✅ |

## β — BATTERY-SOH-DEGRADATION (gap 2) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `BatteryConfig` extensible with aging fields + `Battery` usable-capacity de-rate | **producer:task-α** (frozen-field + Battery config-read) — dep β→α wired (serialises `battery.py`) | ✅ |
| `total_battery_discharge_kwh` exists as the throughput aggregate the cycle term reads | grep:`home.py:145-152` wired (`SummaryStatistics`) | ✅ |
| `compute_soh` monotone non-increasing in age + throughput, clamped `[floor,1]` | identity: pure function authored in β; monotone by construction; unit-tested | ✅ |
| Signal = aged single-home scenario reports lower usable capacity / discharge; calendar-only for a single run | integration test (own task); field-population: `Battery` applies SOH on production path | ✅ |

## γ — FINANCE-CONFIG (schema + parser) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `ScenarioConfig` carries optional config blocks (`tariff_config`/`seg_tariff…`) to add `finance` beside | grep:`config.py:477-521` (fields :500-501) wired | ✅ |
| `_parse_scenario` is the assembly point for a new `_parse_finance_config` | grep:`config.py:1515-1525` wired | ✅ |
| `config validate` / `ConfigurationError` path exists | grep:`config.py` `ConfigurationError` (raised in `_parse_battery_config`, e.g. :640) wired | ✅ |
| Signal = `finance:` block round-trips; out-of-range raises `ConfigurationError`; omit ⟹ `None` | unit test on `_parse_finance_config` (own task); rejection observed by constructing bad value | ✅ |

## δ — HOUSEHOLDER-BILL + finance report + CLI — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `SummaryStatistics.{total_import_cost_gbp,total_export_revenue_gbp,net_cost_gbp,total_self_consumption_kwh,total_generation_kwh,simulation_days}` populated by #2 | grep:`home.py:126-152` wired; populated by `calculate_summary` grep:`home.py:434` | ✅ |
| Export already SEG-priced; `net_cost_gbp` correct (so the bill reconciles) | grep:`home.py:333-344`, `home.py:491-540` wired (#2, landed) | ✅ |
| `FinanceConfig` (vat/standing/override) constructible | **producer:task-γ** — dep δ→γ wired | ✅ |
| Honoured battery efficiencies feed self-consumption | **producer:task-α** — dep δ→α (via γ chain / battery fidelity) wired | ✅ |
| `output.generate_summary_report` markdown shape to extend / new `generate_finance_report` | grep:`output.py:147-286` (Financial block :268-284) wired | ✅ |
| Typer `app` + `add_typer` for a new `finance` subcommand | grep:`cli/main.py:17`, `cli/main.py:24-28` wired | ✅ |
| Signal = `solar-challenge finance run …` prints full bill (representative + distribution); `--assumptions both` side-by-side | integration test (own task, real-PVGIS ⟹ `slow`) | ✅ |
| Identity: `gross_bill=(import_cost+standing)×(1+vat)`; `net=gross−seg_income` | identity: stated in §3.1/§8; H1 re-checks vs `net_cost_gbp` | ✅ |

## ε — FLEET-FINANCIAL-AGGREGATION — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `FleetSummary` + `calculate_fleet_summary` aggregate per-home `SummaryStatistics` (SEG already summed) | grep:`fleet.py:201-231`, `fleet.py:357-426` wired | ✅ |
| Per-home `net_cost_gbp`/`import`/`export` exist to sum | grep:`home.py:145-147` wired | ✅ |
| Signal = fleet summary's net/import/export equal the sum of per-home figures | unit test on synthetic `FleetResults` (own task); additive, default `None` ⟹ existing tests green | ✅ |

## ζ — MULTI-YEAR-PROJECTION (forward-march, adaptive PCHIP) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `PVConfig.system_age_years` + wired `apply_degradation` (aged PV through the physics) | grep:`pv.py:60-61`, `pv.py:400-404` wired (P3, landed) | ✅ |
| `compute_soh` + battery SOH de-rate (aged battery) | **producer:task-β** — dep ζ→β wired | ✅ |
| `FleetSummary` financial + throughput aggregates per age | **producer:task-ε** — dep ζ→ε wired | ✅ |
| `simulate_fleet(scenario,…) -> FleetResults` signature UNCHANGED (P5) + injectable | grep:`fleet.py` `simulate_fleet` wired; P5 §D announcement: signature unchanged | ✅ |
| `dataclasses.replace` to build aged configs (no sampler change) | identity: stdlib; configs are frozen dataclasses | ✅ |
| `scipy.interpolate.PchipInterpolator` importable (monotone cubic, no overshoot) | grep: `scipy` is a pvlib transitive dep — **confirm import at ζ start**; fallback: hand-rolled monotone Hermite (no new dep) | ⚠ confirm |
| Floor: `interp_error_estimate <= error_target_pct` | floor: **driver refinement invariant** (bisect-until-under-target); convergence-control, not an absolute-accuracy bound ⟹ no method floor to violate | ✅ |
| Monotonicity: `pv_soh`/`battery_soh` non-increasing | identity: `compute_soh` monotone (β) + cumulative throughput non-decreasing along the march | ✅ |

## η — PROJECT-ECONOMICS + economics report — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `MultiYearCurve` (per-year energy/revenue) available | **producer:task-ζ** — dep η→ζ wired | ✅ |
| `FinanceConfig` (capex rates, grant, equity/debt, loan term/rate, opex) | **producer:task-γ** — dep η→γ wired | ✅ |
| Resolved fleet configs expose per-home PV kWp + battery kWh for capex build-up | grep:`fleet.py:132-197` (`FleetResults.home_configs`) wired | ✅ |
| `output.generate_finance_report` economics block (extends δ's report) | **producer:task-δ** — dep η→δ (serialises `output.py` finance sections) wired | ✅ |
| Identity: level-amortisation debt service; `min_dscr` over loan years; IRR via NPV root-find (no `numpy.irr` dep) | identity: standard annuity + NPV bisection, pure; H5 re-checks vs hand annuity | ✅ |
| Signal = `finance run --project …` prints capex/grant/debt/equity/finance/opex/surplus/min-DSCR/IRR/payback; deterministic | integration test (own task) | ✅ |

## θ — SPREADSHEET-CALIBRATION (integration gate) — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `householder_bill` + `project_economics` callable under an override | **producer:task-δ,η** — dep θ→δ, θ→η wired | ✅ |
| `self_consumption_override` reproduces [FIN] 45/70 | **producer:task-γ** (the override field) + δ/η honour it — wired | ✅ |
| `[FIN]` workbook present for golden cells | grep:`finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm` exists on disk | ✅ |
| Numeric: economics reproduce [FIN] capex/min-DSCR/equity-IRR **under identical inputs** | floor: **same-arithmetic-identical-inputs ⟹ structural agreement** to rounding; golden values from **named `.xlsm` cells**, NOT survey prose; physics column allowed to differ; £775k delta **reported, not asserted-equal** (§2.3/§13) | ✅ |
| Negative: signal does NOT assert physics == spreadsheet, does NOT hardcode £775k as a RED threshold | premise-guard: avoids the unbacked-external-number trap; resolution-(b) (assert the achievable, report the rest) | ✅ |
