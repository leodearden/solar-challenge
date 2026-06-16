# PRD — Financial layer + battery fidelity (W2)

- **Source:** 2026-06-15 deployment-readiness survey §6 decision 6 (physics-first install-spec optimisation), §8 workstream **W2**. Brief: `/home/leo/.claude/spawn-briefs/solar-w2-financial-layer.md`.
- **Status:** active · authored 2026-06-16
- **Owner seam:** a **new `finance.py` module** (pure bill / project-economics / multi-year-projection functions) + a new `solar-challenge finance` CLI subcommand. Additive battery-fidelity fields on `BatteryConfig` (battery.py) + `_parse_battery_config` (config.py). Financial aggregation fields on `FleetSummary` (fleet.py). Finance report sections in `output.py`.
- **Approach:** **B + H** (contract + two-way boundary tests). High stakes: board-facing financial numbers reconciled against the investor spreadsheet, and a cross-PRD consumer (W3). See §8.
- **Consumes (do not re-touch):** export/import pricing from **task #2** (`home.py` financial accounting / `seg.py`) — landed; `SummaryStatistics.{total_import_cost_gbp,total_export_revenue_gbp,net_cost_gbp,seg_revenue_gbp}` are read-only inputs. PV degradation from **P3** (`pv.PVConfig.system_age_years` / `apply_degradation`) — landed; the multi-year projection sets `system_age_years` and inherits degradation through the physics.
- **Produces (G4 seam owned here):** `finance.householder_bill(...)`, `finance.project_economics(...)`, `finance.project_multi_year(...)` — the pure functions **W3** (discrete install-config optimisation sweep, sibling PRD) imports to rank configs by minimum total householder bill.

---

## 1. Goal

Add a **financial layer** to the simulator that emits, for a scenario: (a) a **full householder annual bill** — standing charge + import at tariff + VAT, net of self-consumption saving and SEG export — and (b) **project-level economics** — capex build-up, grant, debt/equity split, finance cost, opex, annual surplus, **DSCR, equity IRR, payback** over the 25-year asset life. Plus the **battery fidelity** the honest 25-year span requires: SOC limits + round-trip efficiency made YAML-configurable (today they are constructor-only and hard-wired to defaults), and a battery **capacity-fade / SOH** model (today absent) that de-rates the battery across its life the way PV degradation already does.

**User-observable outcome:** `solar-challenge finance run scenarios/bristol-phase1.yaml` prints a board-readable markdown report with two blocks — a **householder annual bill** (representative home + per-home min/mean/median/max distribution) and **project economics** (capex / grant / debt / equity / finance / opex / surplus / min-DSCR / equity-IRR / payback) — structured to line up against the investor spreadsheet's sheets, computed from the physics sim with a switch to reproduce the spreadsheet's own self-consumption assumptions for side-by-side reconciliation. A reviewer can read one config's numbers and check them by hand.

## 2. Background

### 2.1 What already exists (do not rebuild — verified in code 2026-06-16)

The survey's W2 brief flagged several items as gaps; three of those are **already fixed** and must not be re-scoped:

- **Export priced at SEG (F-TOU-EXPORT fixed):** `home.simulate_home` prices `export_revenue` through `seg.calculate_seg_revenue` when `HomeConfig.seg_tariff` is set, else falls back to the import rate (`home.py:333-344`). `net_cost_gbp`/`seg_revenue_gbp` are computed correctly (`home.py:491-540`). Task **#2** owns this; this PRD **consumes** it.
- **PV degradation wired (P3):** `pv.simulate_pv_output` calls `apply_degradation(ac_power, config.system_age_years, config.degradation_rate_per_year)` (`pv.py:400-404`); `PVConfig.system_age_years`/`degradation_rate_per_year` exist (`pv.py:60-61`). The multi-year projection (§3.3) reuses this verbatim.
- **`seg.py` is live, not orphaned:** imported by `home.py:22` and `community.py:27`. Only the preset-name resolver `resolve_seg_tariff` (`seg.py:41`) is unwired into CLI/web selectors — irrelevant here.
- **CLI home path threads tariff/SEG:** `cli/home.py` uses `_parse_home_config` (`config.py:858`) which threads tariff/SEG/HP/EV/dispatch. The survey's "CLI silently drops tariff" claim is stale.

### 2.2 The three real gaps this PRD fills

1. **No financial layer.** Zero `standing_charge`/`VAT`/`capex`/`opex`/`DSCR`/`IRR`/`payback` in `src/` (grep, 0 hits). The aggregate `SummaryStatistics` (`home.py:126-152`) emits only `total_import_cost_gbp`, `total_export_revenue_gbp`, `net_cost_gbp`, `seg_revenue_gbp`. There is **no full householder bill** (standing charge + unit rates + VAT, net of self-consumption saving and SEG export) and **no project economics**.
2. **No battery aging model.** `battery.py` tracks SOC and applies round-trip efficiency but has **no** capacity-fade / SOH / cycle term (grep for `soh|fade|degrad|cycle|aging`: 0 hits in `battery.py`). The spreadsheet's 25-yr economics assume degradation; without a battery SOH the projection can't honestly span the asset life.
3. **Battery SOC limits + round-trip efficiency are not YAML-configurable.** `min_soc_fraction`/`max_soc_fraction`/`charge_efficiency`/`discharge_efficiency` live only as `Battery.__init__` arguments (`battery.py:77-80`); `BatteryConfig` (the frozen dataclass YAML parses into) does **not** carry them, and `home.py:261` calls `Battery(config.battery_config)` with **all four defaults hard-wired** (0.1/0.9 SOC, 0.975 eff). `_parse_battery_config` (`config.py:626-655`) parses only capacity/charge/discharge/dispatch/grid_charging — so `battery.efficiency: 0.95` in `scenarios/example-economy7.yaml:35` is **silently dropped today**. W3's sweep needs these varied per config.

### 2.3 The calibration target and a known tension (G6-load-bearing)

The investor spreadsheet `finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm` `[FIN]` is the reconciliation reference: avg 5.5 kWp + 10 kWh; £1,000/kWp PV + £1,000/roof fit + £250/kWh battery; 1,050 kWh/kWp/yr; self-consumption **45% (no battery) / 70% (with battery)**; own-use 15 p/kWh, export 6 p/kWh; grant £250k; 75% equity / 25% debt; 15-yr loan @ 7%. Cached headline outputs: total capex £775k, min DSCR 2.10, min cash £96k, equity IRR ≈69%. The ResNet "Simple Annual Revenue Model" `[FEAS]`: net surplus **£27/home/yr**; householder saving ~£324/yr (~30%) vs 23 p flat retail.

> **⚠ Self-consumption tension (surface, do not silently resolve).** The spreadsheet's 45%/70% self-consumption is **contradicted by the sim's physics** (~30% at low/no battery rising to ~70% only at large battery; battery-kWh ≈ PV-kWp gives ~52%). The sim's per-minute figure is **better grounded** (survey §3, decision 6). The financial layer must let **both** be compared — physics default, spreadsheet-assumption override — never bake in one.

> **⚠ Capex-arithmetic discrepancy (a calibration deliverable, NOT a test threshold).** The survey's cached "total capex £775k" does **not** reconcile with the [FIN] build-up on a 5.5 kWp + 10 kWh home: `100 × (5.5×£1,000 + £1,000 + 10×£250) = £900k` gross. Reconciling this delta is part of the calibration leaf (§10 θ); the golden values come from **named spreadsheet cells**, not the survey's rounded prose — see §13.

Review context: `review/gap-register.md` (this PRD is added as **P6**); survey `/home/leo/mission-control/consulting/solar-challenge/2026-06-15-deployment-readiness-survey.md` §6/§8/§9.

## 3. Sketch of approach

The new financial computation lives in a **new module `finance.py`** (mirroring how `community.py` is a self-contained consumer of `FleetResults`). It is **pure** — it consumes already-computed sim aggregates and config, and returns frozen dataclasses. Rendering lives in `output.py`; the user surface is a new `solar-challenge finance` CLI subcommand. Existing-file edits are minimal and additive (battery fidelity on `battery.py`/`config.py`; financial aggregation on `fleet.py`; report sections on `output.py`; one `add_typer` line in `cli/main.py`). **No edit to `home.py` financial accounting (#2's territory).**

### 3.1 Data model (the contract — H)

```python
# finance.py — all frozen dataclasses, __post_init__ validation

@dataclass(frozen=True)
class FinanceConfig:
    # Householder retail side
    standing_charge_pence_per_day: float       # e.g. 60.0
    vat_rate: float = 0.05                      # UK domestic 5%; applied to import + standing
    retail_baseline_rate_pence_per_kwh: float = 23.0   # flat-retail counterfactual for "saving %"
    self_consumption_override: Optional[float] = None  # None = physics; e.g. 0.70 reproduces [FIN]
    # Project capex build-up (per [FIN])
    pv_cost_per_kwp_gbp: float = 1000.0
    roof_fit_cost_gbp: float = 1000.0
    battery_cost_per_kwh_gbp: float = 250.0
    inverter_cost_per_kw_gbp: float = 0.0   # W3 seam: default 0 ⟹ inverter folded in pv_cost (calibration
                                            #   bit-identical); W3's sweep sets this nonzero WITH a panels-only
                                            #   reduced pv_cost_per_kwp_gbp so total capex isn't double-counted.
    grant_gbp: float = 250_000.0
    # Project finance
    equity_fraction: float = 0.75
    loan_term_years: int = 15
    loan_rate: float = 0.07
    opex_per_home_per_year_gbp: float = 131.0
    asset_life_years: int = 25
    # __post_init__: 0<=vat_rate<=1; 0<=equity_fraction<=1; 0<self_consumption_override<=1 if set;
    #   loan_term_years>0; loan_rate>=0; asset_life_years>=loan_term_years; positive PV/roof/battery costs;
    #   inverter_cost_per_kw_gbp>=0 (0 permitted — the folded-in default).

@dataclass(frozen=True)
class BillBreakdown:                 # one householder, one year
    standing_charge_gbp: float
    import_cost_gbp: float           # import_kwh * tariff, pre-VAT
    vat_gbp: float                   # vat_rate * (import_cost + standing_charge)
    gross_bill_gbp: float            # (import_cost + standing_charge) * (1+vat_rate)
    seg_export_income_gbp: float     # zero-rated
    self_consumption_saving_gbp: float
    net_annual_bill_gbp: float       # gross_bill - seg_export_income
    baseline_bill_gbp: float         # flat-retail counterfactual, VAT-inclusive
    saving_vs_baseline_gbp: float
    saving_pct: float
    self_consumption_fraction: float # the fraction actually used (physics or override)

@dataclass(frozen=True)
class BillDistribution:              # a fleet's householders
    representative: BillBreakdown     # the mean/median home, for [FIN] reconciliation
    per_home_net_bill_gbp: tuple[float, ...]
    min_gbp: float; mean_gbp: float; median_gbp: float; max_gbp: float

@dataclass(frozen=True)
class YearPoint:
    year: int
    pv_soh: float; battery_soh: float
    fleet_self_consumption_kwh: float; fleet_export_kwh: float; fleet_import_kwh: float
    fleet_revenue_gbp: float          # self-consumption value + SEG export, that year

@dataclass(frozen=True)
class MultiYearCurve:
    points: tuple[YearPoint, ...]     # one per asset-life year (interpolated)
    sampled_ages: tuple[int, ...]     # the ages actually simulated (forward-march nodes)
    interp_error_estimate: float      # max |interpolant - trial sim| / annual, % (adaptive target)

@dataclass(frozen=True)
class ProjectEconomics:
    total_capex_gbp: float; grant_gbp: float; equity_gbp: float; debt_gbp: float
    annual_debt_service_gbp: float    # level amortisation of `debt` over loan_term @ loan_rate
    per_year_surplus_gbp: tuple[float, ...]   # revenue - opex - debt_service, each year
    min_dscr: float                   # min over loan years of (revenue-opex)/debt_service
    equity_irr: float                 # IRR of (-equity @ yr0, +distributions yr 1..N)
    payback_years: Optional[float]    # first year cumulative equity cashflow >= 0 (None if never)
    net_surplus_per_home_per_year_gbp: float
```

### 3.2 Householder bill (pure, year-1) — `householder_bill`

```python
def householder_bill(
    summary: SummaryStatistics,          # from #2: import/export cost, net_cost, SEG already priced
    annual_self_consumption_kwh: float,  # from the sim, OR derived from an override fraction
    finance: FinanceConfig,
    simulation_days: int,                # to scale standing charge to the sim window / annualise
) -> BillBreakdown: ...
```

- **Self-consumption source switch** (the §2.3 tension): when `finance.self_consumption_override is None`, use the physics figure (`summary.total_self_consumption_kwh`); otherwise `annual_self_consumption_kwh = override * total_generation_kwh` and the import/export are recomputed consistently from that fraction. Both paths feed the same `BillBreakdown` shape; the report shows them side-by-side.
- **VAT** is an explicit line at `finance.vat_rate` on (import cost + standing charge); SEG export income is zero-rated; the self-consumption saving and the baseline counterfactual are valued at the **VAT-inclusive** retail rate.
- **Annual normalisation:** scenarios run a full year (all `scenarios/*.yaml` use `2024-01-01`→`2024-12-31`, `simulation_days == 365`); the standing charge is `standing_charge_pence_per_day × simulation_days`. If `simulation_days < 360` the function scales energy + standing to 365 and flags it (annualisation is honest only from a representative window — see §12).

### 3.3 Multi-year projection (forward-march, adaptive) — `project_multi_year`

The 25-year economics need annual energy **as the system ages**. Per the resolved design (§4): a **forward-march over adaptively-placed age nodes**, because the **combined calendar + cycle** SOH at age *t* depends on cumulative throughput from 0→*t*, which is the integral of per-year throughput — and per-year throughput is an existing aggregate (`SummaryStatistics.total_battery_discharge_kwh`). **No dispatch-loop instrumentation is needed.**

```python
def project_multi_year(
    scenario: ScenarioConfig,            # the fleet to age
    finance: FinanceConfig,
    *, error_target_pct: float = 1.0,    # adaptive node refinement target (tactical knob, §12)
    simulate=simulate_fleet,             # injectable for fast tests
) -> MultiYearCurve: ...
```

Algorithm (per node, ascending age — order matters; SOH integrates history):
1. Build an **aged fleet** via `dataclasses.replace`: set `pv.system_age_years = t` (P3's wired degradation) and inject the **battery SOH for age t** (computed by §3.5 `compute_soh` from the running `cumulative_throughput`). Weather is location-MD5-cached, so re-running ages re-costs only the flow/dispatch loop, not PVGIS.
2. `simulate_fleet(aged_scenario)` → that year's `FleetSummary` (extended per §3.4) → annual self-consumption / export / import / revenue **and** that year's battery throughput.
3. Accumulate throughput into `cumulative_throughput` for the next node.
4. **Interpolate** the per-year curves between nodes with **shape-preserving monotone cubic (PCHIP)** — it will not overshoot on the monotone-declining curve a free cubic spline can. **Adaptive placement:** start with coarse nodes (0 / mid / asset-life); bisect any interval whose PCHIP interpolant deviates from a trial sim at its midpoint by more than `error_target_pct`; bound the node count (§12). All sampling/interpolation is encapsulated here — it never leaks into the §3.2/§3.4 seam signatures W3 consumes.

### 3.4 Project economics (pure) — `project_economics`

```python
def project_economics(curve: MultiYearCurve, scenario: ScenarioConfig, finance: FinanceConfig)
    -> ProjectEconomics: ...
```

- **Capex build-up** per home from the resolved fleet configs: `Σ_home (pv_kwp×pv_cost_per_kwp + roof_fit + battery_kwh×battery_cost_per_kwh + inverter_kw×inverter_cost_per_kw)`, where `inverter_kw` is the home's `PVConfig.effective_inverter_capacity_kw`; total minus `grant` is financed `equity_fraction` / `1-equity_fraction`. The inverter term defaults to **0** (`inverter_cost_per_kw_gbp=0.0`) so existing scenarios and the [FIN] calibration (θ/H6) are **bit-identical**; it exists so **W3** can price inverter sizing (the seam consumer — §7).
- **Debt service:** level amortisation of `debt` over `loan_term_years` at `loan_rate` (standard annuity).
- **Per-year surplus:** `curve.points[y].fleet_revenue_gbp − fleet_opex − (debt_service if y < loan_term else 0)`.
- **DSCR:** `min over loan years of (revenue − opex) / debt_service`. **Equity IRR:** IRR of `[−equity, dist₁, …, dist_N]`. **Payback:** first year cumulative equity cashflow ≥ 0.
- **Self-consumption switch** flows through here too: the same override that drives the bill drives the projection's revenue, so the economics can be produced under physics **or** [FIN] assumptions for reconciliation.

### 3.5 Battery fidelity (battery.py + config.py)

**(a) SOC limits + efficiency → `BatteryConfig` (gap 3).** Add `min_soc_fraction=0.1`, `max_soc_fraction=0.9`, `charge_efficiency=0.975`, `discharge_efficiency=0.975`, and an optional round-trip `efficiency: Optional[float]=None` (when set, splits as `sqrt(efficiency)` into charge/discharge) to the frozen `BatteryConfig`, validated in `__post_init__` (mirrors the existing `Battery.__init__` checks at `battery.py:94-106`). `Battery.__init__` reads each from `config` when its constructor arg is `None` (so the four constructor params become optional overrides and **`home.py:261` / `community.py:304` need no change** — the defaults move from constructor to config). `_parse_battery_config` parses the new keys (so `battery.efficiency: 0.95` stops being silently dropped).

**(b) Combined calendar + cycle SOH (gap 2).** Add `system_age_years=0.0`, `calendar_fade_rate_per_year` (default a warranty-grounded value, e.g. ~0.02/yr to ~70% SOH near end-of-life), and a cycle term (`cycle_fade_per_equivalent_full_cycle`, throughput-referenced) to `BatteryConfig`, plus an optional `soh: Optional[float]=None` override. A **pure** `compute_soh(system_age_years, cumulative_throughput_kwh, usable_capacity_kwh, params) -> float` returns the SOH fraction; `Battery` de-rates usable capacity by it. For a **single** aged run (no projection driver), throughput history is 0 → **calendar-only** SOH (the honest single-run answer); the §3.3 forward-march supplies cumulative throughput so the **combined** term engages across the asset life. `compute_soh` clamps to `[soh_floor, 1.0]`.

### 3.6 Fleet financial aggregation (fleet.py)

`FleetSummary` (`fleet.py:201-231`) today aggregates energy + `total_seg_revenue_gbp` only. Add `total_net_cost_gbp`, `total_import_cost_gbp`, `total_export_revenue_gbp`; `calculate_fleet_summary` (`fleet.py:357-426`) sums the per-home `SummaryStatistics` fields. Additive, backward-compatible (new fields default-None for callers that don't compute them). This is the only `fleet.py` change; P5 left the file otherwise unchanged (§7).

### 3.7 Config + CLI surface

- **YAML:** a top-level `finance:` block parsed by a new `_parse_finance_config` → `ScenarioConfig.finance: Optional[FinanceConfig]` (beside `tariff_config`/`seg_tariff_pence_per_kwh` at `config.py:500-501`). Battery-fidelity keys ride the existing `battery:` block via `_parse_battery_config`.
- **CLI:** a new `cli/finance.py` with `solar-challenge finance run <scenario> [--project] [--assumptions physics|spreadsheet|both]`, registered with one `app.add_typer(finance_app.app, name="finance")` line at `cli/main.py:29`. It runs `simulate_fleet` (+ `project_multi_year` for `--project`), calls the `finance.py` functions, and renders via a new `output.generate_finance_report`.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| PRD packaging | **One PRD, phased** (battery fidelity → bill → economics → calibration) | The 25-yr economics consume battery degradation; keeping it in-batch avoids a new cross-PRD G4 seam for two things that ship together. *(user-confirmed)* |
| 25-yr projection | **Hybrid: sim representative ages + interpolate**, forward-march | Captures the battery-fade→self-consumption non-linearity the survey stresses, at bounded cost; weather is cached so re-aging is cheap. Physics-grounded per decision 6. *(user-confirmed)* |
| Interpolation | **PCHIP (monotone cubic)** + **adaptive node refinement** against an error target | User refinement: non-linear + adaptive interval. PCHIP won't overshoot the monotone-declining curve; adaptive placement spends nodes where curvature is highest. *(user-confirmed)* |
| Battery aging model | **Combined calendar + cycle** SOH | User-chosen. Made consistent with hybrid sampling via the forward-march (cumulative throughput = integral of an existing per-year aggregate; no dispatch instrumentation). *(user-confirmed)* |
| Self-consumption | **Dual-source**: physics default, `self_consumption_override` reproduces [FIN] 45/70 | Brief mandate — both must be comparable; the physics figure is better grounded and is the default. |
| Calibration ground-truth | golden values from **named `.xlsm` cells**, asserting **method-agreement under identical inputs** — not the survey's prose numbers | Avoids the £775k-vs-£900k false-premise trap (G6); reconciling that delta is a deliverable, not a RED threshold. |
| VAT | explicit line, configurable `vat_rate` (default 5%) on import + standing; SEG zero-rated; saving valued VAT-inclusive | UK domestic convention. The CBS-supply VAT question is regulatory → §12, not sim logic. |
| Inverter capex (W3 seam) | `FinanceConfig.inverter_cost_per_kw_gbp` (**default 0.0**) + `inverter_kw×cost` term in the `project_economics` build-up; W3 sets it nonzero with a **panels-only** reduced `pv_cost_per_kwp_gbp` | Added so **W3** can price inverter sizing (cheaper small inverter vs clipping loss). Default 0 keeps inverter folded in `pv_cost` ⟹ W2 results + [FIN] calibration bit-identical; W3 opts in consistently to avoid double-counting. *(added 2026-06-16 per W3 dependency)* |
| New-code home | **new `finance.py`** module (pure) + `output.py` rendering + new `finance` CLI subcommand | Mirrors `community.py`; keeps the bulk off contested files (`home.py` financial accounting is #2's). W3 imports `finance.py`, not `output.py`. |
| Battery-field home | **`BatteryConfig`** (battery.py) for SOC/eff/aging | Symmetric with P3's PV-age on `PVConfig` and P4's `grid_charging` on `BatteryConfig`; rides `battery.config` into `Battery` with no `home.py` change. |
| Bill altitude | **both** representative home + per-home distribution | Representative reconciles against [FIN]'s average-home model; the distribution is the physics-first spread W3 ranks on. |
| Backward compatibility | `finance=None` ⟹ finance report unavailable, sim unchanged; new battery fields default to today's constants ⟹ identical results | Every existing test stays green; `battery.efficiency` newly *honoured* is the only behaviour change, and only when a YAML set it (previously dropped). |

## 5. Pre-conditions for activating

- **Task #2** (SEG/import pricing on `home.py`/`seg.py`) — **landed**; the bill/economics consume `SummaryStatistics` financial fields. No re-fix.
- **P3** (`PVConfig.system_age_years` + wired `apply_degradation`) — **landed**; the projection sets `system_age_years`. No change to `pv.py`.
- All other substrate exists — see §6. Novel substrate (`finance.py` functions, new `BatteryConfig` fields, `FleetSummary` fields, `_parse_finance_config`, the `finance` CLI) is **produced within this batch**, each by a named task consumed by a named downstream task.

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `SummaryStatistics.{total_import_cost_gbp,total_export_revenue_gbp,net_cost_gbp,seg_revenue_gbp,total_self_consumption_kwh,total_generation_kwh,total_battery_discharge_kwh,simulation_days}` | `home.py:126-152` (wired; populated by `calculate_summary`, `home.py:434`) |
| `calculate_summary(results, seg_tariff_pence_per_kwh)` produces those fields | `home.py:434` |
| Export already SEG-priced; `net_cost_gbp` correct (#2) | `home.py:333-344`, `home.py:491-540` |
| `seg.calculate_seg_revenue(export_kwh, tariff)`; `SEGTariff` | `seg.py:68`, `seg.py:8` |
| `tariff.TariffConfig.get_rate(ts)` / `calculate_bill(series, tariff)` (import-side bill primitive) | `tariff.py:125`, `tariff.py:301` |
| `pv.PVConfig.system_age_years` / `degradation_rate_per_year`; `apply_degradation` wired into `simulate_pv_output` (P3) | `pv.py:60-61`, `pv.py:400-404` |
| `Battery.__init__` SOC/efficiency params + validation to mirror onto `BatteryConfig` | `battery.py:73-108` |
| `BatteryConfig` frozen + additive-field pattern (`dispatch_strategy`, `grid_charging` precedents) | `battery.py:11-29` |
| `home.py:261` / `community.py:304` build `Battery(config.battery_config)` (so config-read needs no caller change) | `home.py:261`, `community.py:304` |
| `_parse_battery_config` reads the `battery:` block (extend for SOC/eff/aging) | `config.py:626-655` |
| `ScenarioConfig` carries `tariff_config`/`seg_tariff_pence_per_kwh` (add `finance` beside) | `config.py:477-521` (fields `:500-501`); `_parse_scenario` `config.py:1515-1525` |
| `FleetResults` + `FleetSummary` + `calculate_fleet_summary` (extend with net-cost fields) | `fleet.py:132-197`, `fleet.py:201-231`, `fleet.py:357-426` |
| `simulate_fleet(scenario, …) -> FleetResults` (the projection's per-age sim; injectable) | `fleet.py` `simulate_fleet` (P5 announcement: signature UNCHANGED) |
| `output.generate_summary_report` markdown shape (add finance sections / new `generate_finance_report`) | `output.py:147-286` (Financial block `:268-284`) |
| Typer `app` + `add_typer` registration for a new `finance` subcommand | `cli/main.py:17`, `cli/main.py:24-28` |
| Scenarios run a full year (`simulation_days == 365`) so annual figures come out directly | `scenarios/*.yaml` `period: 2024-01-01..2024-12-31`; `home.py:501` |
| `numpy.irr`-free IRR / PCHIP — implement IRR via bisection on NPV; PCHIP via `scipy.interpolate.PchipInterpolator` (scipy is a transitive dep of pvlib) | `scipy` present via pvlib; IRR is a pure root-find (no extra dep) |

**Novel substrate introduced (queued within this batch, not assumed):** `finance.py` (`FinanceConfig`, `BillBreakdown`, `BillDistribution`, `YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `householder_bill`, `project_multi_year`, `project_economics`, `compute_soh`); new `BatteryConfig` fields (SOC/eff/aging) + `Battery` config-read; `FleetSummary` net-cost fields; `_parse_finance_config` + `ScenarioConfig.finance`; `output.generate_finance_report`; `cli/finance.py`. Each is produced by a named task (§10) and consumed by a named downstream task or the CLI surface — no orphan, no fiction. **One open verification for decompose:** confirm `scipy.interpolate.PchipInterpolator` imports in the project env (pvlib pulls scipy); if absent, the fallback is a hand-rolled monotone cubic Hermite (no new dep). **G3 verdict: PASS** (modulo the scipy/PCHIP confirm, which the manifest binds).

## 7. Cross-PRD relationship (G4)

This PRD is added to `review/gap-register.md` as **P6**; seam rows appended to §C (additive ownership of `BatteryConfig` aging/SOC fields, `FleetSummary` financial fields, the new `finance.py`/`cli finance`/`generate_finance_report`).

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **task #2** (SEG/import pricing) | **consumes** | reads `SummaryStatistics` financial fields read-only; never re-prices | #2 owns pricing; **P6 must not touch `home.py` financial accounting** | landed; consume as-is |
| **P3** (PV degradation) | **consumes** | projection sets `PVConfig.system_age_years`; `apply_degradation` already wired | P3 owns `pv.py`; **P6 does not edit `pv.py`** | landed; consume as-is |
| **P4** (grid-charging) | **co-tenant of `BatteryConfig`/`_parse_battery_config`** | P6 adds SOC/eff/aging fields **additively** beside P4's `grid_charging`; both optional, no overlap | each owns its own fields | landed; additive |
| **P5** (community sharing) | **co-tenant of `fleet.py`/`output.py`** | P6 adds financial fields to `FleetSummary` (P5 left `fleet.py` logic unchanged) + a new `generate_finance_report` (P5 owns `generate_community_report`) | disjoint symbols; file-lock serialises | landed; additive |
| **W3** (install-config optimisation sweep, sibling — `docs/prds/discrete-install-config-sweep.md`) | **produces / consumed-by** | W3 imports `finance.householder_bill` / `bill_distribution` / `project_multi_year` / `project_economics` / `FinanceConfig` to rank configs by min householder bill with project-surplus as a constraint. **Also consumes `FinanceConfig.inverter_cost_per_kw_gbp` + the `project_economics` inverter capex term** (added here per W3, default 0.0) so W3 can price inverter sizing. | **P6 owns** the function signatures + the inverter capex field (the contract, §3.1/§3.4/§8); W3 references P6 tasks γ/δ/ζ/η as dependencies | seam defined here; **W3 authored 2026-06-16**, queue-gated on W2 (γ/δ/ζ/η) landing |
| `cli/home.py` (#14) / `cli/fleet.py` (P5) | **none** | P6 adds a **new** `cli/finance.py` subcommand; touches `cli/main.py` only for one `add_typer` line | P6 owns `cli/finance.py` | no edge |

No reciprocal-ownership ambiguity: W2 unilaterally owns the finance contract (incl. the inverter capex field — W3 consumes it, never edits `finance.py`), and the **user-observable report surface** (`solar-challenge finance run`) is itself a named consumer, so G1 is satisfied independent of W3. W3 now exists but owns only its own enumerate/rank/report pipeline (`optimize.py`).

## 8. G5 note — why B + H

High stakes on three axes: (1) **board-facing financial numbers** reconciled against an investor spreadsheet — a wrong DSCR/IRR misinforms a £750k share offer; (2) a **cross-PRD consumer** (W3) imports the seam functions, so their signatures + invariants must be specified up front or W3's integration starves under the narrow-lock orchestrator; (3) **blast radius ≥ 5 modules** (`finance.py`, `battery.py`, `config.py`, `fleet.py`, `output.py`, `cli/`). → **B + H**.

- **Contract (B):** §3.1 data model + §3.2/§3.3/§3.4 function signatures and invariants are the written contract every leaf binds to. Invariants: `householder_bill` and `project_economics` are **pure and deterministic** given (config, aggregate); `gross_bill = (import_cost + standing) × (1+vat_rate)`; `net_annual_bill = gross_bill − seg_export_income`; `min_dscr` is over loan years only; `compute_soh ∈ [floor, 1]` and is monotone non-increasing in both age and throughput; `MultiYearCurve.points` has exactly `asset_life_years` entries with `pv_soh`, `battery_soh` non-increasing.
- **Two-way boundary tests (H):** §9.

## 9. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|
| H1 | **Bill ↔ pricing seam (#2):** physics bill reconciles with `net_cost_gbp` | a home with tariff + SEG, year sim; `finance.self_consumption_override=None` | `gross_bill − seg_export_income` equals `net_cost_gbp + standing×(1+vat)` to ε; `vat_gbp == vat_rate×(import_cost+standing)` |
| H2 | **Self-consumption switch:** override reproduces a chosen fraction | same home; `override=0.70` | `BillBreakdown.self_consumption_fraction == 0.70`; physics-run vs override-run differ in `self_consumption_saving_gbp` in the expected direction; both share the `BillBreakdown` shape |
| H3 | **SOH ↔ projection seam:** combined fade engages across life | aged fleet via `project_multi_year`, asset_life 25 | `battery_soh` and `pv_soh` are non-increasing; year-25 `battery_soh < year-0`; cycle term raises fade above calendar-only when throughput is high (vs a zero-throughput control) |
| H4 | **Adaptive interpolation:** error target honoured | `error_target_pct=1.0` on a synthetic curve | `interp_error_estimate <= 1.0`; refining the target lowers it / adds nodes; PCHIP curve is monotone (no overshoot above the node values) |
| H5 | **Economics determinism + DSCR/IRR/payback algebra** | a fixed `MultiYearCurve` + `FinanceConfig` | `project_economics` is bit-identical across runs; level-amortisation debt-service matches a hand annuity; `min_dscr` ignores post-loan years; `equity_irr` reprices the equity cashflow to NPV≈0 |
| H6 | **Calibration ↔ spreadsheet (the integration gate, θ):** identical inputs reproduce [FIN] | `override=0.70`/`0.45`, [FIN] prices/finance terms, golden values from named `.xlsm` cells | capex / min-DSCR / equity-IRR match the spreadsheet cells within documented tolerance; the **physics** column is emitted alongside and is allowed to differ; the capex-arithmetic delta (§2.3) is reported, not asserted-equal-to-£775k |
| H7 | **Battery-fidelity round-trip (gap 3):** YAML SOC/eff honoured | scenario sets `battery.efficiency`/`min_soc_fraction`/`max_soc_fraction` | report's round-trip loss / usable-capacity figures move with the YAML; previously-dropped `battery.efficiency: 0.95` now changes results; omission ⟹ today's defaults (bit-identical) |

## 10. Decomposition plan

Eight tasks across four phases. **File-lock discipline:** `battery.py` + `_parse_battery_config` edited only by the serialized chain **α → β**; `config.py` finance parsing only by **γ** (disjoint region from `_parse_battery_config`); `finance.py` by **δ → ζ → η** (serialised, new file); `fleet.py` only by **ε**; `output.py` finance sections by **δ** (bill) then **η** (economics) — serialised; `cli/finance.py` new (δ). Per-task tests in distinct modules.

### Phase 1 — Battery fidelity

#### α — `BatteryConfig` SOC limits + efficiency (gap 3)
- **Modules:** `battery.py`, `config.py` (+ `tests/unit/test_battery.py`, `test_config.py`)
- **Work:** add `min_soc_fraction`/`max_soc_fraction`/`charge_efficiency`/`discharge_efficiency` (today's defaults) + optional round-trip `efficiency` to frozen `BatteryConfig`, validated in `__post_init__`. `Battery.__init__` reads each from `config` when the constructor arg is `None` (overrides preserved; `home.py`/`community.py` untouched). Extend `_parse_battery_config` to parse the keys (round-trip `efficiency` splits as `sqrt`).
- **Classification:** intermediate — unlocks β, and the bill/projection inherit honoured efficiencies.
- **Signal (G2, user-observable):** a scenario with `battery.efficiency: 0.90` + a narrow `min/max_soc` shows changed round-trip loss / usable capacity in the run summary; previously-dropped `battery.efficiency` now changes `total_battery_discharge_kwh`; omission ⟹ bit-identical to today (H7).

#### β — Battery combined calendar+cycle SOH (gap 2)
- **Modules:** `battery.py`, `config.py` (+ tests)
- **Work:** add `system_age_years`/`calendar_fade_rate_per_year`/cycle-fade param + optional `soh` to `BatteryConfig`; pure `compute_soh(age, cumulative_throughput_kwh, usable_capacity_kwh, params)`; `Battery` de-rates usable capacity by SOH (calendar-only for a single run). Parse the aging block.
- **Prereqs:** α (serialises `battery.py` + `_parse_battery_config`).
- **Signal:** an aged single-home scenario (`battery.system_age_years: 10`) reports lower usable capacity / `total_battery_discharge_kwh` than age 0; `compute_soh` is monotone non-increasing and clamped to `[floor,1]` (unit); omission ⟹ today's behaviour.

### Phase 2 — Householder bill

#### γ — `FinanceConfig` schema + parser + `ScenarioConfig.finance`
- **Modules:** `config.py` (+ `tests/unit/test_config.py`)
- **Work:** frozen `FinanceConfig` (defaults from [FIN], §3.1) with `__post_init__` validation; `_parse_finance_config`; add `finance: Optional[FinanceConfig]` to `ScenarioConfig` + wire in `_parse_scenario`.
- **Classification:** intermediate — unlocks δ, η.
- **Signal:** `solar-challenge config validate` accepts a `finance:` block; a YAML round-trips into `ScenarioConfig.finance`; out-of-range (`vat_rate=2`, `equity_fraction=1.5`, `override=0`) raises `ConfigurationError`; omission ⟹ `None`.

#### δ — `householder_bill` + finance report + `finance` CLI (leaf)
- **Modules:** `finance.py` (new), `output.py`, `cli/finance.py` (new), `cli/main.py` (one `add_typer`), `scenarios/` (+ `tests/integration/test_finance_bill.py`)
- **Work:** `BillBreakdown`/`BillDistribution` + `householder_bill` (§3.2) + a fleet `bill_distribution` helper; `output.generate_finance_report` bill block (representative + min/mean/median/max); `solar-challenge finance run <scenario> --assumptions physics|spreadsheet|both`.
- **Prereqs:** γ (finance config); consumes #2's `SummaryStatistics` (read-only) and α's honoured efficiencies.
- **Signal (G2):** `solar-challenge finance run scenarios/bristol-phase1.yaml` prints a full householder annual bill (standing + import@tariff + VAT − self-consumption saving − SEG export) for a representative home + distribution; `--assumptions both` prints physics vs spreadsheet side-by-side (H1, H2). Mark any real-PVGIS test `slow` (#11).

### Phase 3 — Project economics

#### ε — `FleetSummary` financial aggregation
- **Modules:** `fleet.py` (+ `tests/unit/test_fleet.py`)
- **Work:** add `total_net_cost_gbp`/`total_import_cost_gbp`/`total_export_revenue_gbp` to `FleetSummary`; `calculate_fleet_summary` sums per-home `SummaryStatistics`. Additive (default `None`).
- **Classification:** intermediate — unlocks ζ/η fleet revenue.
- **Signal:** a fleet run's summary reports aggregated net cost / import / export equal to the sum of per-home figures (unit, synthetic `FleetResults`); existing fleet tests green.

#### ζ — `project_multi_year` forward-march driver
- **Modules:** `finance.py` (+ `tests/unit/test_finance_projection.py`)
- **Work:** `YearPoint`/`MultiYearCurve` + `project_multi_year` (§3.3): forward-march over adaptive nodes, aged configs via `dataclasses.replace`, PCHIP interpolation, throughput integral feeding β's `compute_soh`, error-target refinement. `simulate` injectable for fast synthetic tests.
- **Prereqs:** β (`compute_soh` + battery SOH de-rate), ε (fleet financial aggregation); consumes P3's `PVConfig.system_age_years` (landed).
- **Signal:** a 25-yr projection over a small injected fleet shows non-increasing `pv_soh`/`battery_soh` and declining annual generation; `interp_error_estimate <= error_target_pct`; tighter target adds nodes (H3, H4).

#### η — `project_economics` + economics report (leaf)
- **Modules:** `finance.py`, `output.py` (+ `tests/integration/test_finance_economics.py`)
- **Work:** `ProjectEconomics` + `project_economics` (§3.4: capex build-up, annuity debt service, per-year surplus, min-DSCR, equity-IRR via NPV bisection, payback); economics block in `generate_finance_report`; `finance run --project`.
- **Prereqs:** γ (finance config), ζ (multi-year curve).
- **Signal (G2):** `solar-challenge finance run --project scenarios/bristol-phase1.yaml` prints capex / grant / debt / equity / finance / opex / surplus / min-DSCR / equity-IRR / payback; the function is deterministic; debt service matches a hand annuity (H5).

### Phase 4 — Calibration integration gate

#### θ — Spreadsheet calibration + two-way boundary tests (integration-gate leaf)
- **Modules:** `tests/integration/test_finance_calibration.py`, `scenarios/` (a `[FIN]`-aligned calibration scenario), `finance.py` (a small calibration helper) , `docs/` (a short reconciliation note)
- **Work:** the H6 boundary test — feed [FIN]'s own inputs (45/70 override, [FIN] prices/finance terms) and assert the economics reproduce the spreadsheet's capex / min-DSCR / equity-IRR within documented tolerance, golden values read from **named `.xlsm` cells** (documented in the test); emit the physics column alongside; report (not assert) the §2.3 capex-arithmetic delta.
- **Prereqs:** δ (bill), η (economics). The **integration-gate leaf**: α/β/γ/ε/ζ rope into it; it is where "the financial layer matches or exceeds the spreadsheet" becomes observable.
- **Signal (G2/G6):** a calibration report/test shows spreadsheet-input vs physics columns; the spreadsheet-input column matches the named `.xlsm` cells within tolerance; the run documents the capex delta. **No assertion that the physics column equals the spreadsheet** (it legitimately differs).

> **Note for decompose-time:** the orchestrator does not yet consume `user_observable_signal` / `consumer_ref` / substrate-confirmed metadata — recorded for a future tracking session. Confirm `scipy.interpolate.PchipInterpolator` is importable in the env at θ/ζ start (fallback: hand-rolled monotone Hermite — no new dep). Mark real-PVGIS finance tests `slow` (#11); keep `mypy --strict` green (#12).

## 11. Out of scope

- **The W3 sweep** — ranking discrete install configs by minimum householder bill with project-surplus as a constraint + sensitivity. W3 imports this PRD's functions; a separate PRD.
- **Web exposure** of the finance report / new battery fields → candidate P2 follow-up (engine + CLI + YAML only here).
- **Flexibility / grid-services revenue** (DFS / DNO flex / arbitrage uplift) in the economics — the W1/survey value model; the projection models self-consumption + SEG only. A future revenue-stack extension.
- **Cycle counting inside the dispatch loop** — the cycle term reads the existing `total_battery_discharge_kwh` aggregate; per-timestep cycle accounting is not added.
- **Real-historical weather** in the projection — runs on TMY like the rest of the sim (`weather.py`'s historical path stays unwired — a separate gap).
- **Re-fixing pricing / SEG** (#2), **PV degradation** (P3), **`fleet.py` simulation logic** (P5) — consumed, not modified.
- **The CBS-supply VAT regulatory question** (is self-consumed CBS-owned generation VATable?) — a regulatory determination (survey §7), not sim logic; `vat_rate` is configurable so either treatment is expressible.

## 12. Open questions (tactical — deferred, not design-blocking)

1. **Adaptive node budget + error target.** `error_target_pct=1.0` and the coarse seed (0 / mid / asset-life) are starting values; the max-node cap and whether to seed extra nodes at the warranty knee are empirical. Tune in ζ; the knobs are configurable.
2. **Calendar fade curve shape.** A single linear `calendar_fade_rate_per_year` vs a piecewise warranty curve (faster year-1 "formation" loss, then linear to ~70% @ EoL). Default linear; revisit against a real battery datasheet during β. The field set supports either.
3. **Cycle-fade reference.** Equivalent-full-cycles (throughput / 2·usable) vs raw kWh-throughput against a datasheet curve. Pick the better-grounded one in β; both consume the same `cumulative_throughput`.
4. **Standing-charge / VAT under CBS supply.** §11 defers the regulatory question; the default models a conventional retail bill (5% VAT, daily standing charge). Confirm with the board which counterfactual the "saving %" should use (current-supplier standing charge vs zero).
5. **Calibration tolerance values.** The per-metric tolerances in H6/θ depend on how exactly the [FIN] sheet's intermediate rounding is reproducible; set them when the `.xlsm` cells are read (θ), erring toward method-agreement not digit-equality.
6. **`.xlsm` cell extraction.** Whether θ reads golden values live via `openpyxl` or pins documented constants transcribed from named cells. Either is acceptable; the test documents the cell references regardless.

## 13. G6 — premise validity of the asserted signals

- **δ / η end-to-end capability** ("report prints a full bill / economics block"): every required capability traces to this batch's deps — γ (finance config), #2 (`SummaryStatistics`, landed), β/ζ (SOH + curve). No capability is owed by a task that depends on these leaves. **Producible.**
- **θ numeric premise** ("reproduces the spreadsheet's capex / min-DSCR / equity-IRR under identical inputs"): the **achievability basis** is that, fed identical inputs, the economics use the **same arithmetic** as the spreadsheet (capex build-up, annuity debt service, DSCR/IRR/payback) — so agreement is structural, to within rounding + documented sheet quirks. The golden values are read from **named `.xlsm` cells**, not the survey's rounded prose. Critically, the signal does **not** assert the **physics** column equals the spreadsheet (it legitimately differs — §2.3), and does **not** hardcode "£775k" as a threshold (the £775k-vs-£900k delta is a *reported* deliverable). This sidesteps the classic false-premise trap of asserting an unbacked external number against a RED test. **Premise valid** (resolution-(b)-shaped: assert what's structurally achievable, report the rest).
- **H3 SOH monotonicity** ("`battery_soh`/`pv_soh` non-increasing; combined > calendar-only under load"): `compute_soh` is monotone non-increasing in both arguments by construction (β), and cumulative throughput is non-decreasing along the forward-march — so the assertion follows from the function's own algebra, re-checked on the produced curve. **Producible by β+ζ.**
- **H4 interpolation error** ("`interp_error_estimate <= error_target_pct`"): not a guessed accuracy bound on a numerical method but the **driver's own refinement invariant** — the forward-march bisects until the trial-sim deviation falls under the target, so the estimate is `≤` the target by the loop's exit condition (bounded by the node cap, which the report surfaces if hit). **No floor violation** — it's a convergence-control assertion, not an absolute-accuracy claim. **Producible by ζ.**
- **H7 negative/rejection assertions** ("out-of-range finance/battery values raise `ConfigurationError`"; "omission ⟹ bit-identical"): each binds to a real validator (`__post_init__` on `FinanceConfig`/`BatteryConfig`) authored in the same task; the rejection is observed by constructing the bad value and catching the raise. **Rejection-mechanism-backed.**

**G6 verdict: PASS.**
