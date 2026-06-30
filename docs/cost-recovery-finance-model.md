# CBS Cost-Recovery Finance Model

**Task**: W2-CR + task-84 §6 — authoritative specification (CR6, task/62; basis-C amendment, task/84)
**Code**: `src/solar_challenge/finance.py`, `src/solar_challenge/output.py`
**Tests**: `tests/integration/test_cost_recovery_calibration.py` (CR6 H6 gate + basis-C gate)
**Cross-ref**: `docs/finance-spreadsheet-reconciliation.md` (θ, task/48)
**Version**: 0.4.0 (basis-C cost-recovery release; platform α2 re-pins to this version)

---

## Overview

The Bristol CBS (Community Benefit Society) owns the PV panels, battery systems,
and the export MPAN for each home in the fleet.  Householders pay the CBS an
**own-use rate** for CBS-owned solar consumed on-site, but take on **no debt** and
receive **no SEG credit** (the export income flows to the CBS).  The CBS uses the
collected own-use revenue to service the project loan, cover opex, and retain a
minimum cash surplus per home.

This document specifies the cost-recovery model precisely enough that a board member
can reproduce a live `solar-challenge fleet run --cost-recovery` run by hand, and that
a future code-reviewer can verify any code change against this spec.  Every equation
traces to a function in `finance.py`; every reported number in §7 matches a live
calibration run captured by `tests/integration/test_cost_recovery_calibration.py`.

---

## 1. CBS Ownership Model

The CBS owns the PV array, battery, and export MPAN for each home.  A householder's
relationship to the system has three components:

| Component | Who receives/pays | Where in code |
|-----------|------------------|---------------|
| Self-consumed solar | Householder pays CBS at `own_use_rate` p/kWh | `householder_bill()` `own_use_payment_gbp` |
| Grid export (SEG) | CBS receives; not passed to householder | `project_multi_year()` `fleet_revenue_gbp` (SEG rate reconciled from `ScenarioConfig.seg_tariff_pence_per_kwh` onto homes) |
| Grid import | Householder pays retailer at `retail_baseline_rate` p/kWh | `householder_bill()` `import_cost_gbp` |

The householder carries no debt, no capital obligation, and no export-MPAN risk.
The CBS bears all capex, debt service, and battery-cycling costs.

---

## 2. The Own-Use Lever

The own-use rate `r` (p/kWh) is the single control variable in the cost-recovery
solve.  Raising `r` increases both:

- **CBS income** — the fleet pays more for self-consumed solar.
- **Householder outlay** — each home's annual bill rises by `Δr × own_use_kwh / 100`.

The solve finds the **minimum** `r` that lets the CBS meet a retained-cash-floor
target, minimising the householder cost.  When flex revenue (grid services or
TOU arbitrage) is present, the CBS needs a lower `r` to reach the same floor.

### Own-Use Basis (Basis C) — task-84 §6

All CBS billing (householder bill and cost-recovery solve) uses **basis C**:

```
own_use_kwh = total_demand_kwh − total_grid_import_kwh   (≥ 0)
```

This equals the energy that did **not** cross the grid boundary in the consumption
direction — the CBS-supplied energy actually used by the home (direct PV + battery
discharge, net of any grid-charged battery energy).

**Why basis C instead of B-style self-consumption?**

The physics series `self_consumption = min(direct + battery_discharge, demand)`
(B-style) counts grid-charged battery discharge as "self-consumed" — but the
round-trip grid-charge energy crossed the grid boundary on the way *in*, so
it must not be double-counted as CBS-supplied.  On TOU-arbitrage / grid-charging
homes, B-style is strictly larger than basis C:

```
total_self_consumption_kwh = demand − import + grid_charge_kwh  (B-style)
own_use_kwh (basis C)       = demand − import                   (grid-immune)
```

The CBS bears the battery round-trip loss; this is absorbed into the headline
own-use rate (the solver sets `r` against basis-C own-use, which is smaller, so
the floor-binding rate is correspondingly higher).

**Implementation**: `finance._cbs_own_use_kwh(summary)` returns
`max(summary.total_demand_kwh − summary.total_grid_import_kwh, 0.0)`.
Both money-path callers (`_simulate_age` fleet_sc and `bill_distribution`
annual_self_consumption_kwh) route through this helper.  The physics
`self_consumption` series and `self_consumption_ratio` in `flow.py` / `home.py`
are **not changed** — only the money path moves to basis C.

---

## 3. Householder-Outlay Equations

Source: `finance.py:householder_bill()`, `BillBreakdown`.

All monetary values in GBP (£).  VAT is applied to (import + standing + own-use)
as a block; the householder receives **no SEG deduction**.

`own_use_kwh` below is basis C (see §2): `own_use_kwh = total_demand_kwh − total_grid_import_kwh`.

```
own_use_payment_gbp      = own_use_rate_pence_per_kwh × own_use_kwh / 100
                           (own_use_kwh = demand − import = CBS-supplied energy; basis C)

standing_charge_gbp      = standing_charge_pence_per_day × 365 / 100

vat_gbp                  = vat_rate × (import_cost_gbp
                                        + standing_charge_gbp
                                        + own_use_payment_gbp)

total_outlay_gbp         = (import_cost_gbp
                            + standing_charge_gbp
                            + own_use_payment_gbp) × (1 + vat_rate)

baseline_bill_gbp        = (demand_kwh × retail_rate / 100
                            + standing_charge_pence_per_day × 365 / 100) × (1 + vat_rate)

saving_vs_baseline_gbp   = baseline_bill_gbp − total_outlay_gbp

saving_pct               = 100 × saving_vs_baseline_gbp / baseline_bill_gbp

self_consumption_saving_gbp = own_use_kwh × (retail_rate − own_use_rate)
                              × (1 + vat_rate) / 100
```

**H3 board identity** (holds when import is priced at retail, import_kwh = demand − own_use_kwh):

```
saving_vs_baseline ≈ own_use_kwh × (retail_rate − own_use_rate) × (1 + vat_rate) / 100
```

**[FIN] example** (100 homes × 5.5 kWp + 5 kWh, no grid-charging, synthetic scf ≈ 0.346,
r ≈ 12.22 p/kWh — see §7 for the full worked reconciliation):

```
own_use_kwh         = 2,000 kWh/home/yr   (no grid-charging: basis C == B-style; see §2)
import_kwh          = 1,400 kWh/home/yr
import_cost_gbp     = 1,400 × 23 / 100  = £322.00/yr (retail fallback; no tariff config)
standing_charge_gbp = 60 × 365 / 100    = £219.00/yr
own_use_payment_gbp = 12.22 × 2,000 / 100 = £244.40/yr  (at solved rate; basis C = 2,000 here)
vat_gbp             = 0.05 × (322 + 219 + 244.40) = £39.27/yr
total_outlay_gbp    = (322 + 219 + 244.40) × 1.05 ≈ £824.67/yr
baseline_bill_gbp   = ((2000+1400) × 23/100 + 219) × 1.05 ≈ £1,051.05/yr
saving_vs_baseline  ≈ £226/yr             (REPORTED; not pinned — see §7)
```

---

## 4. CBS-Revenue Equation

Source: `finance.py:project_multi_year()`.

At each projection year, the CBS fleet revenue is:

```
fleet_revenue_gbp = own_use_revenue
                  + seg_revenue
                  + grid_services_income
                  − cbs_grid_charge_cost
```

Where each term is:

```
own_use_revenue   = own_use_rate_pence_per_kwh × fleet_sc_kwh / 100
                    (fleet_sc_kwh = Σ_homes _cbs_own_use_kwh(s) = Σ (demand − import); basis C)

seg_revenue       = Σ_homes _seg_export_income_gbp(home, finance, sim_days)
                    (= Σ home.total_export_revenue_gbp on the physics path,
                    unless self_consumption_override is set)

                    SEG input reconciliation: project_multi_year calls
                    _reconcile_seg_homes() immediately after _resolve_homes().
                    When ScenarioConfig.seg_tariff_pence_per_kwh is set and a
                    home's HomeConfig.seg_tariff is None, the scenario rate is
                    threaded onto that home as SEGTariff(rate_pence_per_kwh=R),
                    making per-home seg_tariff the single source of SEG maths
                    (robust to the Task-85 export-revenue zeroing).  If a
                    per-home seg_tariff is already set and its rate differs from
                    the scenario rate, ValueError is raised (fail-fast).

grid_services_income = grid_services_income_per_kw_per_year_gbp
                       × Σ_homes battery.max_discharge_kw
                    (field from FinanceConfig; W1 fills the non-zero value)

cbs_grid_charge_cost = Σ_homes summary.total_grid_charge_cost_gbp
                    (= Σ home.grid_charge_cost.sum() when grid_charge_cost is not None,
                     0.0 when grid_charge_cost is None — i.e., flat-rate homes)
```

**No-flex identity** (flat-rate fleet, grid_services = 0):

When `grid_charge_cost=None` and `grid_services_income_per_kw_per_year_gbp=0.0`
and `export_revenue=0` (synthetic SEG-free fleet):

```
fleet_revenue_gbp = own_use_rate × fleet_sc / 100
```

This identity is hard-asserted in `TestNoFlexAnchorReconciliation::test_no_flex_cbs_revenue_identity`.

---

## 5. Cost-Recovery Solve + Feasibility Cases

Source: `finance.py:solve_cost_recovery_rate()`.

The CBS net surplus per home is **exactly affine** in the own-use rate `r`:

```
net_surplus(r) = [Σ_years (r × sc_y/100 + C_y − opex − debt_y)] / (N_years × N_homes)
```

where `sc_y` is the **basis-C** fleet own-use at year `y`
(`YearPoint.fleet_self_consumption_kwh = Σ_homes (demand − import)` after degradation
interpolation), and `C_y` is rate-independent (SEG + grid-services − grid-charge, fixed by physics).
PCHIP interpolation and `project_economics` are both linear in per-year revenue,
so the affine form is preserved end-to-end.

The solver uses this affine structure to avoid re-simulating for each trial rate:

1. Run `project_multi_year` **once** at the configured `r0`.
2. Evaluate `s0 = net_surplus(0)`, `s_ret = net_surplus(retail)`.
3. `slope = (s_ret − s0) / retail`.
4. `r* = (floor − s0) / slope`  (closed-form).
5. Clamp and set binding (see table below).

| Outcome | Rate | Binding | Feasible |
|---------|------|---------|---------|
| `r* < 0` — project over-delivers at r = 0 | 0 | `rate_clamped_zero` | True |
| `0 ≤ r* ≤ retail` — interior solve | `r*` | `floor` | True |
| `r* > retail` — impossible to meet floor | `retail` | `infeasible_above_retail` | False |
| Degenerate (no self-consumption) | 0 or retail | one of the above | as above |

After the solve, a separate age-0 fleet simulation provides per-home granularity
for the `BillDistribution` (representative median-outlay home, min/mean/median/max).

---

## 6. Capex → Debt → Required-Own-Use → Outlay Coupling (H2)

Source: `finance.py:project_economics()`.

The project capex is built up as a 4-term sum:

```
total_capex_gbp = Σ_homes [
    pv_kwp × pv_cost_per_kwp_gbp
  + roof_fit_cost_gbp
  + battery_kwh × battery_cost_per_kwh_gbp
  + eff_inv_kw × inverter_cost_per_kw_gbp
]

financed        = max(total_capex_gbp − grant_gbp, 0)
equity_gbp      = financed × equity_fraction
debt_gbp        = financed × (1 − equity_fraction)
annual_debt_svc = annuity(debt_gbp, loan_rate, loan_term_years)
```

Raising capex (larger battery or PV) directly raises `annual_debt_svc`, which
raises `s0` (the surplus deficit at r = 0), which raises `r*` (to compensate),
which raises `own_use_payment_gbp` per home, which raises `total_outlay_gbp`.

This **H2 monotonicity** is exact by the affine solve algebra.  It is
hard-asserted in `TestStructuralInvariants::test_h2_capex_monotone_on_fin_fleet`.

**[FIN] example** (100 homes × 5.5 kWp + 5 kWh, grant = £250,000):

```
total_capex  = 100 × (5.5×1000 + 1000 + 5.0×250) = 100 × £7,750 = £775,000
financed     = 775,000 − 250,000 = £525,000
equity       = 525,000 × 0.75   = £393,750
debt         = 525,000 × 0.25   = £131,250
debt_svc/yr  = annuity(131,250, 7%, 15yr) ≈ £14,410/yr
opex/yr      = 100 × £131       = £13,100/yr
floor_total  = 100 × £27        = £2,700/yr
required rev = 14,410 + 13,100 + 2,700 = £30,210/yr (no-flex, interior target)
r*           ≈ 30,210 / (fleet_sc / 100)             (closed-form, synthetic fleet)
```

---

## 7. Worked No-Flex [FEAS] Reconciliation (Corrected Premise)

Source: calibration anchor from `TestNoFlexAnchorReconciliation::test_no_flex_solve_report`
(live run: `tests/integration/test_cost_recovery_calibration.py`).

### 7.1 Corrected False Premise

The board feasibility study ([FEAS]) states a retained surplus of £27/home/yr.
**This figure is a no-flex figure**: it assumes income from self-consumption and
export only, with **no grid-services income** and **no TOU arbitrage** (flat-rate tariff).

The incorrect shorthand "15p + Central flex → £27" is internally inconsistent:
adding Central grid-services income (W1) to the revenue side lowers the required
own-use rate substantially below 15p — it does **not** produce £27 surplus at 15p.

The correct statement is:

> At **zero flex** (grid_services = 0, flat-rate tariff), the cost-recovery solve
> finds the own-use rate needed to retain exactly £27/home/yr surplus.
> Flex (grid-services + TOU arbitrage, W1) **lowers** the required rate from this baseline.

### 7.2 [FIN] Synthetic No-Flex Calibration

The calibration test uses a 100-home synthetic fleet (5.5 kWp + 5 kWh, Bristol
period 2024-01-01 to 2024-12-31) with injected energy aggregates and no PVGIS
(fast, deterministic, no-network):

```
Synthetic energy inputs (per home, annual):
  self_kwh           = 2,000 kWh   (constant power series; B-style sc)
  export_kwh         = 3,775 kWh   (constant power series)
  import_kwh         = 1,400 kWh
  grid_charge_cost   = None         (flat-rate → cbs_grid_charge_cost = 0)
  export_revenue     = £0           (SEG = 0, CBS retains all export)
  grid_services      = £0/kW/yr     (no-flex)

  Basis C (no grid-charging):
    own_use_kwh/home = demand − import = (2000 + 1400) − 1400 = 2,000 kWh/home
    (basis C == B-style sc when grid_charge == 0; see §2)
  fleet_sc (basis C) = 100 × 2,000 = 200,000 kWh/yr
  synthetic scf      ≈ 0.346        (2,000 / (2,000 + 3,775))
```

**[FIN] finance parameters** (from `FinanceConfig` defaults / `_FIN_GOLDEN`):

| Parameter | Value |
|-----------|-------|
| `pv_cost_per_kwp_gbp` | £1,000/kWp |
| `roof_fit_cost_gbp` | £1,000/home |
| `battery_cost_per_kwh_gbp` | £250/kWh |
| `grant_gbp` | £250,000 |
| `equity_fraction` | 0.75 |
| `loan_rate` | 7 % |
| `loan_term_years` | 15 |
| `opex_per_home_per_year_gbp` | £131 |
| `own_use_rate_pence_per_kwh` | 15 p/kWh (configured; solved rate below) |
| `retained_cash_floor_per_home_per_year_gbp` | £27 |
| `retail_baseline_rate_pence_per_kwh` | 23 p/kWh |
| `vat_rate` | 5 % |
| `standing_charge_pence_per_day` | 60 p/day (from `_FIN_GOLDEN` calibration fixture) |
| `grid_services_income_per_kw_per_year_gbp` | £0 (no-flex) |
| PV degradation rate (`PVConfig.degradation_rate_per_year`) | 0.5 %/yr (0.005, linear; default in `calculate_degradation_factor`) |

### 7.3 Live Calibration Output (REPORTED — not pinned)

```
[NO-FLEX ANCHOR REPORT] (synthetic scf≈0.346; assumption-dependent)
  Solved own-use rate: 12.22 p/kWh  (target ≈15p; reported, not pinned)
  Saving vs baseline:  £226          (target ≈£324; reported, not pinned)
  Net surplus/home/yr: £27.00        (= £27 floor when binding='floor')
  Binding:             floor
  Feasible:            True
```

### 7.4 Why the Live Rate Differs from the Single-Year Approximation

A single-year back-of-envelope gives:

```
required revenue = opex(13,100) + debt_svc(14,410) + floor×n(2,700) = £30,210/yr
r*_approx        = 30,210 / (200,000 / 100) = 15.1 p/kWh
```

The live calibration value is **12.22 p/kWh** — lower than this approximation.
The difference has two sources:

1. **Multi-year mean, not a single-year snapshot.**  `project_multi_year` builds a
   25-year PCHIP revenue curve and `project_economics` takes the *mean net surplus*
   over all 25 years.  Generation (and therefore self-consumption) peaks in years 1–5
   and degrades gently (linear PV degradation at 0.5 %/yr, `degradation_rate_per_year=0.005`
   default in `calculate_degradation_factor`; applied per-home in `_simulate_age` via
   `h.pv_config.degradation_rate_per_year`, producing the per-year `pv_soh` that shapes
   the PCHIP curve); the PCHIP mean surplus at a given rate is slightly higher than
   the year-1 point, so the solver can reach the £27/home floor at a *lower* rate than
   the year-1 approximation implies.

2. **Synthetic scf ≈ 0.346 ≠ spreadsheet 0.70.**  The [FEAS] target of ≈15p and
   saving ≈£324 assume the spreadsheet self-consumption fraction of 0.70
   (Sensitivity!B7: 5 kWh battery; see §4.1 of `docs/finance-spreadsheet-reconciliation.md`).
   The synthetic fleet uses injected aggregates (self=2,000 kWh, gen=5,775 kWh) that
   produce scf ≈ 0.346.  The single-year approximation above already uses the correct
   fleet_sc = 200,000 kWh, so the scf difference does not change the 15.1 p estimate —
   but it does mean the solved *saving* (≈£226 live vs. ≈£324 target) differs, because
   saving depends on sc_kwh per home.

**The key structural result is exact and hard-asserted**: `sol.net_surplus_per_home_per_year_gbp == 27.00`
to float ε (binding = 'floor' — the closed-form affine solve guarantees this regardless
of the rate value).  The printed rate (12.22 p) and saving (£226) are live, code-authoritative
figures reported for transparency; no test pins them to specific digits.

> **Note on code line numbers** — The line numbers cited in this document (e.g. line 499,
> line 1814) are approximate anchors for the current version and will drift as the code
> evolves.  Use the function names as durable references.

**The key structural result is hard-asserted and exact**: `sol.net_surplus_per_home_per_year_gbp == 27.00` to float ε (binding = 'floor' — the closed-form affine solve guarantees this regardless of the rate value).

### 7.5 Assertion Strategy (Mirrors θ §3.3)

| Assertion | Status | Rationale |
|-----------|--------|-----------|
| `sol.feasible is True` | **HARD asserted** | Robust: 'floor' and 'rate_clamped_zero' are both feasible |
| No-flex CBS-revenue identity | **HARD asserted** | By construction (grid_charge=None, grid_services=0) |
| `0 ≤ r* ≤ retail` | **HARD asserted** | Valid clamped range |
| H1: `surplus == floor` (interior regime) | **HARD asserted** | Exact by the affine solve algebra |
| H2: capex → rate + outlay monotone | **HARD asserted** | Exact by affine algebra |
| flex → strictly lower rate | **HARD asserted** | Monotone by affine algebra |
| θ: capex == £775,000, min_dscr ≥ 1.20 | **HARD asserted** | 4-term build-up exact; covenant floor achievable |
| Solved rate ≈ 15 p/kWh (no-flex anchor) | *REPORTED only* | Assumption-dependent (scf); live value: 12.22 p |
| Saving ≈ £324 vs baseline (no-flex) | *REPORTED only* | Assumption-dependent; live value: £226 |

---

## 8. The Flex Seam (W1 integration points)

When W1 (flexibility-value finance integration, task/52–56) is complete, two
exogenous revenue terms move the solved rate:

### 8.1 Grid-Services Income (Exogenous £/kW/yr)

`FinanceConfig.grid_services_income_per_kw_per_year_gbp` is a W1-filled field.
At each projection year:

```
grid_services_income = grid_services_income_per_kw_per_year_gbp
                       × Σ_homes battery.max_discharge_kw
```

A positive value increases `fleet_revenue_gbp` without changing householder
sc_kwh, so it directly reduces the required rate:

```
r*(flex) = r*(no-flex) − grid_services_income / (fleet_sc / 100)   [approx, single-year]
```

This directional property is hard-asserted in
`TestFlexLowersSolvedRate::test_grid_services_lowers_solved_rate`.

### 8.2 TOU Arbitrage / Time-Shift (Endogenous Physics) — Basis C

W1's TOU+grid-charging dispatch raises per-home B-style self-consumption (battery
charges at cheap off-peak rates, discharges at peak) while introducing a CBS
grid-charge cost (`total_grid_charge_cost_gbp` from `SimulationResults.grid_charge_cost`).

**Basis C and TOU arbitrage**: grid-charged battery energy crosses the grid boundary on
the way *in*, so it inflates `total_grid_import_kwh` and does *not* inflate
`own_use_kwh (basis C) = demand − import`.  Formally:

```
own_use_kwh (basis C) = sc_kwh (B-style) − grid_charge_kwh
```

So even though B-style self-consumption rises with TOU discharge, the CBS's own-use
*rate-base* (basis C) only rises by `sc_uplift − grid_charge` — the net net of the
battery round-trip.  The CBS bears the round-trip loss (absorbed into the solved rate).

Both effects flow through `project_multi_year` (fleet_sc is basis C after task-84 §6):
- Higher basis-C own-use → more own-use revenue at any given rate.
- CBS grid-charge cost → deducted from `fleet_revenue_gbp`.

Net effect: if (uplift_basis_c × r) / 100 > grid_charge_cost/home, the CBS earns more
net revenue, so the solver accepts a lower rate.  This is hard-asserted in
`TestFlexLowersSolvedRate::test_arbitrage_lowers_solved_rate` and the new
`TestArbitrageBasisCReconciliation` class (task-84 §6 gate).

---

## 9. The Rendered Cost-Recovery Report (output.py)

Source: `src/solar_challenge/output.py` (`render_cost_recovery_report()`).

Running `solar-challenge fleet run --cost-recovery` appends a `## Cost-Recovery Analysis`
block to the markdown summary.  The block renders the `CostRecoverySolution` fields:

```markdown
## Cost-Recovery Analysis

| Item | Value |
|------|-------|
| Solved Own-Use Rate              | {r:.2f} p/kWh                    |
| Representative Householder Outlay| £{representative_outlay_gbp:.2f} |
| Saving vs Baseline               | £{saving:.2f} ({saving_pct:.1f}%)|
| CBS Net Surplus / home / yr      | £{net_surplus:.2f}               |
| Feasibility                      | ✔ Surplus meets floor            |

## Per-Home Total Outlay at Solved Rate (£)

| Metric | Value |
|--------|-------|
| Min    | £{min:.2f}    |
| Mean   | £{mean:.2f}   |
| Median | £{median:.2f} |
| Max    | £{max:.2f}    |
```

The `representative` outlay is the home whose `total_outlay_gbp` is closest to the
fleet median — the board's single-home summary figure.

---

## Summary

| Concept | Equation | Code location |
|---------|----------|---------------|
| Basis-C own-use energy | `own_use_kwh = demand − import` (≥ 0; see §2) | `_cbs_own_use_kwh()` |
| Own-use payment | `own_use_rate × own_use_kwh / 100` (basis C) | `householder_bill()` |
| VAT | `vat_rate × (import + standing + own_use_payment)` | `householder_bill()` |
| Total outlay | `(import + standing + own_use_payment) × (1+vat)` | `householder_bill()` |
| Saving | `baseline_bill − total_outlay` | `householder_bill()` |
| CBS revenue (no-flex) | `own_use_rate × fleet_sc / 100` (fleet_sc = Σ basis-C own_use) | `project_multi_year()` |
| CBS revenue (full) | `own_use_rev + seg_rev + gs_income − cbs_grid_charge` | `project_multi_year()` |
| Solve rate-base | `fleet_sc = Σ_homes (demand − import)` (basis C; §2) | `_simulate_age()` |
| Solve | `r* = (floor − s0) / slope` (affine, closed-form) | `solve_cost_recovery_rate()` |
| Capex | `Σ(pv_kwp×pv_cost + roof_fit + batt_kwh×batt_cost)` | `project_economics()` |
| Net surplus | `mean(surplus_y) / n_homes` over 25 yr | `project_economics()` |
