# CBS Cost-Recovery Finance Model

**Task**: W2-CR + task-84 §6 — authoritative specification (CR6, task/62; basis-C amendment, task/84)
**Code**: `src/solar_challenge/finance.py`, `src/solar_challenge/output.py`
**Tests**: `tests/integration/test_cost_recovery_calibration.py` (CR6 H6 gate + basis-C gate); `tests/unit/test_finance_projection_revenue.py::TestGridChargeEnergyPaidOnce` (grid-charge energy paid once, §4); `tests/integration/test_finance_bill.py::TestOverrideExactValues` (override path, §3); `tests/unit/test_finance_projection_revenue.py::TestProjectMultiYearRevenue` (override path, §4)
**Cross-ref**: `docs/finance-spreadsheet-reconciliation.md` (θ, task/48)
**Version**: 0.5.0 (CBS amount-due release: own-use VAT + collectable total; platform PRD cbs-invoice-own-use-only task λ2 re-pins to this version)
**Unreleased on main** (task 219): CBS revenue no longer deducts the grid-charge cost (§4); the 0.5.0 tag still does.
**Unreleased on main** (task 271): on a simulated window under 360 days, `project_multi_year` annualises own-use, export, import and battery-discharge kWh (§4, §7.6); the 0.5.0 tag sums them over the window.
**Unreleased on main** (task 281): with `self_consumption_override` set, each home's own-use is capped at its demand and the surplus generation is counted as export (§3, §4); the 0.5.0 tag bills override × generation uncapped.
**Unreleased on main** (task 295): each simulated age's battery SOH counts the battery throughput from installation to that age (§4, §7.6); the 0.5.0 tag ages each seed with the throughput up to the previous seed only, so a battery fleet's mid-life battery SOH and own-use read high there.
**Unreleased on main** (task 307): on a home with no tariff configured, the override path prices its grid import at the retail baseline rate, with the physics path's `UserWarning` (§3); the 0.5.0 tag prices that import at £0.
**Unreleased on main** (task 308): with `self_consumption_override` set, `project_multi_year`'s own-use revenue, and so the cost-recovery solve's rate base, is each home's capped override own-use, the own-use its bill charges (§2, §4, §5); the 0.5.0 tag keeps both on basis C.

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
| Grid import (including off-peak energy a battery grid-charges) | Householder pays retailer at the home's tariff rate (`retail_baseline_rate` p/kWh fallback when no tariff is configured) | `householder_bill()` `import_cost_gbp` |

The householder carries no debt, no capital obligation, and no export-MPAN risk.
The CBS bears all capex, debt service, and battery-cycling costs.

---

## 2. The Own-Use Lever

The own-use rate `r` (p/kWh) is the single control variable in the cost-recovery
solve.  Raising `r` increases both:

- **CBS income** — the fleet pays more for self-consumed solar.
- **Householder outlay** — each home's annual bill rises by `Δr × own_use_kwh / 100`.

The solve finds the **minimum** `r` that lets the CBS meet a retained-cash-floor
target, minimising the householder cost.  When grid-services revenue is present,
the CBS needs a lower `r` to reach the same floor.  TOU arbitrage is not CBS
revenue: its time-shift value reaches the householder through import cost (§8.2).

### Own-Use Basis (Basis C) — task-84 §6

On the physics (default) path, all CBS billing (householder bill and cost-recovery
solve) uses **basis C**:

```
own_use_kwh = total_demand_kwh − total_grid_import_kwh   (≥ 0)
```

With `self_consumption_override` set, the householder bill's own-use and the solve's
rate base both come from the override instead (§3, *Override (spreadsheet-assumption)
path*; §4, §5).

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
`bill_distribution` passes it to `householder_bill` as
annual_self_consumption_kwh, and `_simulate_age` passes it for fleet_sc.  Both
annualise it and pass it to `_billed_energy(annual, finance, physics_own_use_kwh=…)`,
the one physics/override switch, which replaces it with the override's own-use when
one is set.  The physics `self_consumption` series and
`self_consumption_ratio` in `flow.py` / `home.py` are **not changed** — only the
money path moves to basis C.

---

## 3. Householder-Outlay Equations

Source: `finance.py:householder_bill()`, `BillBreakdown`.

All monetary values in GBP (£).  VAT is applied to (import + standing + own-use)
as a block; the householder receives **no SEG deduction**.

`own_use_kwh` below is basis C (see §2): `own_use_kwh = total_demand_kwh − total_grid_import_kwh`.
With `self_consumption_override` set it comes from the override instead (*Override
(spreadsheet-assumption) path*, below).

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

own_use_vat_gbp          = vat_rate × own_use_payment_gbp

cbs_amount_due_gbp       = own_use_payment_gbp + own_use_vat_gbp
                           (float sum — not own_use_payment × (1 + vat_rate))

baseline_bill_gbp        = (demand_kwh × retail_rate / 100
                            + standing_charge_pence_per_day × 365 / 100) × (1 + vat_rate)

saving_vs_baseline_gbp   = baseline_bill_gbp − total_outlay_gbp

saving_pct               = 100 × saving_vs_baseline_gbp / baseline_bill_gbp

self_consumption_saving_gbp = own_use_kwh × (retail_rate − own_use_rate)
                              × (1 + vat_rate) / 100
```

The CBS invoices `cbs_amount_due_gbp` — the own-use payment plus VAT on it, and
nothing else — while `total_outlay_gbp` remains the household's whole-picture
annual outlay: import cost and standing charge are paid to the retailer and
appear on the CBS statement as context only (Leo's ruling, 2026-09-21).

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
own_use_vat_gbp     = 0.05 × 244.40     = £12.22/yr
cbs_amount_due_gbp  = 244.40 + 12.22    = £256.62/yr  (invoiced by the CBS)
vat_gbp             = 0.05 × (322 + 219 + 244.40) = £39.27/yr
total_outlay_gbp    = (322 + 219 + 244.40) × 1.05 ≈ £824.67/yr
baseline_bill_gbp   = ((2000+1400) × 23/100 + 219) × 1.05 ≈ £1,051.05/yr
saving_vs_baseline  ≈ £226/yr             (REPORTED; not pinned — see §7)
```

### Override (spreadsheet-assumption) path

Source: `finance.py:householder_bill()` via `_billed_energy()` and `_override_energy_split()`.

With `FinanceConfig.self_consumption_override` set (a scenario's `finance:` block, or
`finance run --assumptions spreadsheet|both`), the bill's own-use comes from the
override fraction instead of basis C:

```
own_use_kwh = min(self_consumption_override × generation_kwh, demand_kwh)
import_kwh  = demand_kwh − own_use_kwh
              (priced at the home's effective import rate: physics import cost /
               physics import kWh × 100, or retail when physics import is 0.
               A home with no tariff configured reports a £0 physics import
               cost; householder_bill first prices that at retail, with a
               UserWarning, on both paths, so the home's effective rate is
               retail too)
```

Every other identity above is unchanged, applied to this `own_use_kwh`.  A home
cannot consume more solar than its demand: when `override × generation` exceeds
demand, own-use is capped at demand, the surplus generation is counted as export
(§4), `self_consumption_fraction` reports `own_use_kwh / generation_kwh` (below the
override), and `householder_bill` emits a `UserWarning`.  The CBS revenue follows
the same split (§4), so the cost-recovery solve's rate base is the own-use these
bills charge (§5).

**[FIN] override example** (`TestOverrideExactValues`; 5.5 kWp × 1,050 kWh/kWp,
3,400 kWh demand, override 0.70, own-use 15 p/kWh, retail and effective import
rate 23 p/kWh):

```
generation_kwh       = 5.5 × 1,050 = 5,775 kWh/yr
implied own-use      = 0.70 × 5,775 = 4,042.5 kWh > 3,400 kWh demand
own_use_kwh          = 3,400 kWh/yr   (capped at demand)
import_kwh           = 3,400 − 3,400 = 0 kWh/yr
export_kwh           = 5,775 − 3,400 = 2,375 kWh/yr   (uncapped: 1,732.5)
own_use_payment_gbp  = 15 × 3,400 / 100 = £510.00/yr
own_use_vat_gbp      = 0.05 × 510 = £25.50/yr
cbs_amount_due_gbp   = 510 + 25.50 = £535.50/yr  (invoiced by the CBS)
standing_charge_gbp  = 60 × 365 / 100 = £219.00/yr
vat_gbp              = 0.05 × (0 + 219 + 510) = £36.45/yr
total_outlay_gbp     = (0 + 219 + 510) × 1.05 = £765.45/yr
baseline_bill_gbp    = (3,400 × 23 / 100 + 219) × 1.05 = £1,051.05/yr
saving_vs_baseline   = 1,051.05 − 765.45 = £285.60/yr  (27.2%)
                     = 3,400 × (23 − 15) × 1.05 / 100  (H3, exact)
self_consumption_fraction = 3,400 / 5,775 = 0.589  (rendered 58.9%)
```

Uncapped, the 0.5.0 tag bills this home for 4,042.5 kWh: own-use
15 × 4,042.5 / 100 = £606.375, outlay £866.64, saving £184.41.

**Untariffed override example** (`TestOverrideExactValues`; 4,000 kWh generation,
3,400 kWh demand, 1,200 kWh physics import at £0 with no tariff configured,
override 0.70, own-use 15 p/kWh, retail 23 p/kWh):

```
own_use_kwh          = min(0.70 × 4,000, 3,400) = 2,800 kWh/yr   (cap not binding)
import_kwh           = 3,400 − 2,800 = 600 kWh/yr
effective import rate = 23 p/kWh   (retail fallback: physics import cost is £0; warned)
import_cost_gbp      = 600 × 23 / 100 = £138.00/yr
own_use_payment_gbp  = 15 × 2,800 / 100 = £420.00/yr
cbs_amount_due_gbp   = 420 + 0.05 × 420 = £441.00/yr   (import is paid to the retailer, so the fallback leaves this unchanged)
standing_charge_gbp  = 60 × 365 / 100 = £219.00/yr
vat_gbp              = 0.05 × (138 + 219 + 420) = £38.85/yr
total_outlay_gbp     = (138 + 219 + 420) × 1.05 = £815.85/yr
baseline_bill_gbp    = (3,400 × 23 / 100 + 219) × 1.05 = £1,051.05/yr
saving_vs_baseline   = 1,051.05 − 815.85 = £235.20/yr
                     = 2,800 × (23 − 15) × 1.05 / 100  (H3, exact)
```

The 0.5.0 tag bills this import at £0: outlay (0 + 219 + 420) × 1.05 = £670.95, saving £380.10.

---

## 4. CBS-Revenue Equation

Source: `finance.py:project_multi_year()`.

At each projection year, the CBS fleet revenue is:

```
fleet_revenue_gbp = own_use_revenue
                  + seg_revenue
                  + grid_services_income
```

Where each term is:

```
own_use_revenue   = own_use_rate_pence_per_kwh × fleet_sc_kwh / 100
                    (fleet_sc_kwh = Σ_homes _billed_energy(a_h, finance,
                                      physics_own_use_kwh=k_h × _cbs_own_use_kwh(s_h)).own_use_kwh
                                  = Σ_homes k_h × (demand − import)
                                    with no override (basis C)
                                  = Σ_homes min(override × k_h × generation, k_h × demand)
                                    with self_consumption_override set)
                    (a_h = _annualise_physics(s_h, sim_days_h), home h's window totals × k_h;
                     k_h = _annualisation_scale(sim_days_h)
                         = 365 / sim_days_h if sim_days_h < 360, else 1)

seg_revenue       = Σ_homes _seg_export_income_gbp(a_h, finance)
                    (= Σ k_h × home.total_export_revenue_gbp on the physics path;
                    both paths read the same a_h as own-use)

                    Override path (self_consumption_override set):
                    export_kwh = generation − min(override × generation, demand)
                    (a_h's annual generation and demand; §3, override path),
                    priced at the home's effective export rate = physics
                    export revenue / physics export kWh × 100
                    (0 when physics export is 0)

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
```

**Override path.** With `self_consumption_override` set, the capped split (§3)
drives both revenue terms: `own_use_revenue` prices each home's own-use,
`min(override × generation, demand)`, and `seg_revenue` prices the export that
own-use leaves over, `generation − own-use`.  So own-use revenue is exactly what
the §3 override bills charge.  `YearPoint.fleet_export_kwh`, `fleet_import_kwh` and
the battery throughput behind ageing stay the simulated flows
(`tests/unit/test_finance_projection_revenue.py::TestProjectMultiYearRevenue`).

**Annual basis.** Every projection year is a 365-day year.  When a home's
simulated window is under 360 days, `project_multi_year` scales that home's
own-use, export, import and battery-discharge kWh, and its SEG income, by
`k_h = 365 / sim_days_h`, and emits one `UserWarning` per projection.  Each home
is annualised once (`a_h`) before the override splits it, as `householder_bill`
annualises before it bills (§3;
`tests/unit/test_finance_projection_short_window.py::TestProjectMultiYearAnnualisesShortWindow`).  The
annualised discharge is the yearly throughput that battery cycle ageing
integrates.  Grid-services income is already annual.  Full-year windows are
unchanged (`k_h = 1`).  A short window is still one season's sample, so board
figures want `scenario.period` to cover about one full year.

**Battery ageing.** `project_multi_year` simulates each sampled age `t` with
every home's battery at `battery.compute_soh(t, T_h(t))`, where `T_h(t)` is the
home's cumulative battery throughput (kWh) from installation to `t`.  Throughput
accrues at the annualised discharge simulated at the latest seed age (0,
`asset_life_years // 2`, `asset_life_years − 1`) at or below `t`, for seed and
bisection-trial ages alike (`_throughput_at`).  `T_h` never falls and
`compute_soh` never rises in age or throughput, so `YearPoint.battery_soh` is
non-increasing year on year
(`tests/unit/test_finance_projection_ageing.py::TestBatterySohCountsThroughputToEachAge`).
A faded battery stores less, which lowers later years' basis-C own-use and its
revenue.

**No-flex identity** (flat-rate fleet, grid_services = 0):

When `grid_services_income_per_kw_per_year_gbp=0.0` and `export_revenue=0`
(synthetic SEG-free fleet):

```
fleet_revenue_gbp = own_use_rate × fleet_sc / 100
```

This identity is hard-asserted in `TestNoFlexAnchorReconciliation::test_no_flex_cbs_revenue_identity`.

### Grid-charge energy is householder import, not a CBS outgoing

Energy a battery grid-charges passes the home's grid meter, so it is inside
`total_grid_import_kwh` and its cost is inside `total_import_cost_gbp`.  The
householder pays the retailer for it as part of `import_cost_gbp` (§3).  Basis C
(§2) excludes it from own-use, so the CBS neither bills nor pays for it and bears
only the battery round-trip loss.

`SummaryStatistics.total_grid_charge_cost_gbp` is the slice of
`total_import_cost_gbp` spent charging the battery.  It is informational and
appears in no CBS equation.  Each grid-charged kWh is paid once:

```
Σ_homes import_cost_gbp (householder)  +  0 (CBS)  =  Σ_homes total_import_cost_gbp
(full-year physics path with a configured tariff; hard-asserted in
 tests/unit/test_finance_projection_revenue.py::TestGridChargeEnergyPaidOnce)
```

This is the basis-C ruling (Leo, 2026-06-22; platform `billing-engine-s4-s5.md`
decision B and register rule D15: grid-charge energy is "grid energy the member
already paid the retailer for").  Until task 219, `project_multi_year` also
subtracted `Σ total_grid_charge_cost_gbp` from CBS revenue (CR2), which paid
each grid-charged kWh twice.

---

## 5. Cost-Recovery Solve + Feasibility Cases

Source: `finance.py:solve_cost_recovery_rate()`.

The CBS net surplus per home is **exactly affine** in the own-use rate `r`:

```
net_surplus(r) = [Σ_years (r × sc_y/100 + C_y − opex − debt_y)] / (N_years × N_homes)
```

where `sc_y` is the fleet own-use the bills charge at year `y`
(`YearPoint.fleet_self_consumption_kwh`, §4's `fleet_sc_kwh` = Σ_homes `_billed_energy`
own-use: basis C, or the capped override own-use; annualised as in §4, after degradation
interpolation), and `C_y` is rate-independent (SEG + grid-services, fixed by physics).
`opex` is the fleet opex (`opex_per_home_per_year_gbp × N_homes`).  `debt_y` is
`annual_debt_svc` (§6) in the loan years `y < loan_term_years` and **0 afterwards**,
while the sum runs over all `N_years = asset_life_years`.  With the defaults
(`loan_term_years` = 15, `asset_life_years` = 25) debt service is therefore paid in
15 of the 25 years and enters the mean at 15/25 of its annual value (worked in §7.4).
Source: `project_economics` (algorithm steps 5, 6 and 10 in its docstring).
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

**[FIN] override solve** (`TestOverrideOwnUseCappedAtDemand`; the §7.2 anchor fleet
and finance with `self_consumption_override` 0.70: 3,400 kWh demand, 5,775 kWh
generation, no SEG, no grid services).  The anchor's 5,000 kWh fleet caps at the same
3,400 kWh, `min(0.70 × 5,000, 3,400)`, so both fleets solve to one rate.  Carry `r*`
to 6 dp and the own-use payment to 4 dp: the 4-dp rate 7.1901 gives bills of
£24,446.34, and £244.46 gives an outlay of £486.63.

```
own_use_kwh/home = min(0.70 × 5,775, 3,400)             = 3,400 kWh/yr    (capped at demand)
fleet_sc         = 100 × 3,400                          = 340,000 kWh/yr
required revenue = 13,100 + 14,410.5445 × 15/25 + 2,700 = 24,446.3267     = £24,446.33/yr (§7.4)
r*               = 24,446.3267 / (340,000 / 100)        = 7.190096 p/kWh  (live solve: 7.190096)
bills collect    = 100 × 3,400 × 7.190096 / 100         = £24,446.33/yr   (the required revenue)
```

On basis C the same anchor solves at 12.2232 p (§7.4).  The bills collect exactly the
required revenue, so they fund the £27 floor the solve reports
(`test_surplus_is_what_the_bills_fund`).  The representative home's bill (§3):

```
own_use_payment_gbp = 7.190096 × 3,400 / 100         = £244.4633/yr
import_cost_gbp     = 0                                (import = 3,400 − 3,400 = 0)
total_outlay_gbp    = (0 + 219 + 244.4633) × 1.05    = £486.64/yr
saving_vs_baseline  = 1,051.05 − 486.64              = £564.41/yr   (53.7%)
```

The 0.5.0 tag solves this anchor at the basis-C 12.2232 p (§7.4) and bills the
uncapped 0.70 × 5,775 = 4,042.5 kWh/home (§3), so its bills collect
100 × 4,042.5 × 12.2232 / 100 = £49,412/yr and fund (49,412 − 13,100 − 8,646.33) / 100
= £276.66/home/yr against the £27 it reports.

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

annuity(P, r, n) = P × r / (1 − (1 + r)^−n)    (= P / n when r = 0; _annuity_payment)
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
debt_svc/yr  = annuity(131,250, 7%, 15yr) ≈ £14,410.54/yr  (years 0–14 only; §5)
opex/yr      = 100 × £131       = £13,100/yr
floor_total  = 100 × £27        = £2,700/yr
```

§7.4 turns `debt_svc`, `opex` and `floor_total` into the solved rate for the synthetic
[FIN] fleet (12.22 p/kWh) and shows why summing them as one year's cost
(£30,210/yr → 15.1 p/kWh) overstates it.

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
> Grid-services income (W1) **lowers** the required rate from this baseline, and the
> TOU time-shift reaches the householder as import cost (§8.2).

### 7.2 [FIN] Synthetic No-Flex Calibration

The calibration test uses a 100-home synthetic fleet (5.5 kWp + 5 kWh, Bristol
period 2024-01-01 to 2024-12-31) with injected energy aggregates and no PVGIS
(fast, deterministic, no-network):

```
Synthetic energy inputs (per home, annual):
  self_kwh           = 2,000 kWh   (constant power series; B-style sc)
  export_kwh         = 3,775 kWh   (constant power series)
  import_kwh         = 1,400 kWh
  grid_charge_cost   = None         (flat-rate; no battery grid-charging)
  export_revenue     = £0           (SEG = 0, CBS retains all export)
  grid_services      = £0/kW/yr     (no-flex)

  Basis C (no grid-charging):
    own_use_kwh/home = demand − import = (2000 + 1400) − 1400 = 2,000 kWh/home
    (basis C == B-style sc when grid_charge == 0; see §2)
  fleet_sc (basis C) = 100 × 2,000 = 200,000 kWh/yr
  synthetic scf      ≈ 0.346        (2,000 / (2,000 + 3,775))
```

**[FIN] finance parameters** (from `FinanceConfig` defaults / `_FIN_GOLDEN` / the [FIN] fixture builders):

| Parameter | Value |
|-----------|-------|
| `pv_cost_per_kwp_gbp` | £1,000/kWp |
| `roof_fit_cost_gbp` | £1,000/home |
| `battery_cost_per_kwh_gbp` | £250/kWh |
| `grant_gbp` | £250,000 |
| `equity_fraction` | 0.75 |
| `loan_rate` | 7 % |
| `loan_term_years` | 15 |
| `asset_life_years` | 25 (`FinanceConfig` default; the [FIN] fixture sets it to 25) |
| `opex_per_home_per_year_gbp` | £131 |
| `own_use_rate_pence_per_kwh` | 15 p/kWh (configured; solved rate below) |
| `retained_cash_floor_per_home_per_year_gbp` | £27 |
| `retail_baseline_rate_pence_per_kwh` | 23 p/kWh |
| `vat_rate` | 5 % |
| `standing_charge_pence_per_day` | 60 p/day (required `FinanceConfig` field; set to 60 in the [FIN] fixture builders) |
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

The reported **saving** follows from §3's H3 identity at the solved rate (H3 is exact
here: the untariffed fixture prices import at the 23 p retail fallback):

```
saving_vs_baseline = 2,000 × (23 − 12.2232) × 1.05 / 100 = £226.31/home/yr
```

The [FEAS] saving of ≈£324 assumes the spreadsheet self-consumption fraction of 0.70
(Sensitivity!B7: 5 kWh battery; see §4.1 of `docs/finance-spreadsheet-reconciliation.md`).
The injected aggregates (self = 2,000 kWh, gen = 5,775 kWh) give scf ≈ 0.346 instead
(§7.2), and H3 scales the saving with own-use kWh per home, so the solved saving
(≈£226 live vs. ≈£324 target) differs.

### 7.4 Why the Live Rate Differs from the Single-Year Approximation

A single-year back-of-envelope gives:

```
required revenue = opex(13,100) + debt_svc(14,410) + floor×n(2,700) = £30,210/yr
r*_approx        = 30,210 / (200,000 / 100) = 15.1 p/kWh
```

The live calibration value is **12.22 p/kWh** — lower than this approximation.
The whole difference is the debt schedule.

**Cause.**  `project_economics` charges `annual_debt_svc` only in the loan years
`y < loan_term_years` (15), but `net_surplus_per_home_per_year_gbp` — the figure the
solve drives to the floor — is the mean over all `asset_life_years` (25, the
`FinanceConfig` default; §5).  Debt service therefore costs
`debt_svc × loan_term_years / asset_life_years` a year on average, not `debt_svc`; the
single-year sum above charges it in all 25 years, including the ten debt-free years
15–24.

For this fixture (flat curve, SEG = 0, grid services = 0), setting §5's
`net_surplus(r*) = floor` gives:

```
r* = (opex + debt_svc × loan_term/asset_life + floor × n_homes) / (fleet_sc / 100)
```

**Reproduction.**  Carry `debt_svc` to 4 dp: the 2-dp value 14,410.54 × 15/25 gives
8,646.32, but the live figure is 8,646.33.

```
debt_svc × 15/25 = 14,410.5445 × 15/25          = £8,646.33/yr
required revenue = 13,100 + 8,646.33 + 2,700    = £24,446.33/yr
r*               = 24,446.33 / (200,000 / 100)  = 12.2232 p/kWh    (live solve: 12.2232)
```

At the solved rate every one of the 25 `YearPoint.fleet_revenue_gbp` values is £24,446.33,
the required revenue above, to the penny.  Equivalently,
`(13,100 + 14,410.5445 + 2,700 − 14,410.5445 × 10/25) / 2,000 = 12.2232 p/kWh`: the
single-year sum also charges debt service in the ten debt-free years 15–24, worth
`14,410.5445 × 10/25 / 2,000 = 2.88 p/kWh` — the whole gap between 15.1 and 12.22 p/kWh.

**The revenue curve contributes nothing.**  The injected `simulate` returns the same
`FleetResults` at every sampled age (0, 12, 24), so the 25 revenue points are identical
and PCHIP returns that constant.  PV degradation (0.5 %/yr, §7.2) shows only in
`YearPoint.pv_soh` (1.00 at year 0 → 0.88 at year 24), because the injected results
ignore the aged home configs.  On a real-physics run, degradation lowers later-year
generation (`_aged_homes` → `simulate_pv_output` → `apply_degradation`), which would
raise `r*`, not lower it.

**The key structural result is exact.**  At binding = 'floor' the closed-form affine solve
returns `net_surplus_per_home_per_year_gbp == floor` to float ε, regardless of the rate
value (£27.00 at the [FIN] anchor).  It is hard-asserted (to within 1e-6) as H1 in
`TestStructuralInvariants::test_h1_surplus_equals_floor` (£50 floor) and in
`TestArbitrageBasisCReconciliation::test_b_solve_binds_floor_grid_charge` (£27 floor);
the [FIN] anchor test, `test_no_flex_solve_report`, prints its surplus and does not
assert it.  The printed rate (12.22 p) and saving (£226) are live, code-authoritative
figures reported for transparency; no test pins them to specific digits.

### 7.5 Assertion Strategy (Mirrors θ §3.3)

| Assertion | Status | Rationale |
|-----------|--------|-----------|
| `sol.feasible is True` | **HARD asserted** | Robust: 'floor' and 'rate_clamped_zero' are both feasible |
| No-flex CBS-revenue identity | **HARD asserted** | By construction (grid_services=0, SEG=0) |
| `0 ≤ r* ≤ retail` | **HARD asserted** | Valid clamped range |
| H1: `surplus == floor` (interior regime) | **HARD asserted** | Exact by the affine solve algebra |
| The bills fund the solve's surplus: n × own-use payment, less opex and the mean debt service (§7.4), per home | **HARD asserted** | On the anchor and under the 0.70 override (`test_surplus_is_what_the_bills_fund`): the rate base is the own-use the bills charge (§5) |
| H2: capex → rate + outlay monotone | **HARD asserted** | Exact by affine algebra |
| flex → strictly lower rate | **HARD asserted** | Monotone by affine algebra |
| θ: capex == £775,000, min_dscr ≥ 1.20 | **HARD asserted** | 4-term build-up exact; covenant floor achievable |
| Solved rate ≈ 15 p/kWh (no-flex anchor) | *REPORTED only* | ≈15 p matches only the single-year approximation; the solve spreads 15 years of debt service over the 25-year asset life (§7.4); live value: 12.22 p |
| Saving ≈ £324 vs baseline (no-flex) | *REPORTED only* | Assumption-dependent (scf ≈ 0.346 vs 0.70; §7.3); live value: £226 |

### 7.6 Why the Real-Physics Column Is Not Comparable with the Anchor

Source: `TestPhysicsReconciliationColumn::test_physics_path_reported`
(`@pytest.mark.slow`; real PVGIS weather), on the fleet
`_make_physics_column_scenario_cr6` builds.

The physics column solves 2 homes of 5.5 kWp + 5 kWh under the §7.2 [FIN] finance,
simulated over three January days (2024-01-01 to 2024-01-03).  It hard-asserts only that
the physics path returns a structurally valid `CostRecoverySolution`; the rate, saving
and surplus it prints are reported, not pinned.  Its rate cannot be set against the
anchor's (§7.3), for three reasons:

- **One winter window stands in for a year.**  The window is under 360 days, so
  `project_multi_year` scales each home's window totals to a 365-day year by
  `k = 365 / 3 ≈ 121.67` (§4, *Annual basis*).  The rate therefore extrapolates three
  January days to a whole year: one season's sample, where the anchor's injected
  aggregates are already annual (`k = 1`).
- **The fleet carries no debt.**  Its capex,
  `2 × (5.5 × 1,000 + 1,000 + 5 × 250) = £15,500`, is below the £250,000 [FIN] grant, so
  financed capex, debt and equity are all zero (§6).  No debt service enters its solve,
  DSCR is `inf` and the equity IRR is `nan`, where the anchor's 100 homes finance
  £525,000 and carry £131,250 of debt (§6, §7.4).  `TestPhysicsColumnPremises` asserts
  this premise in the fast suite.
- **The homes age.**  The column re-simulates the fleet at sampled ages, so PV
  degradation and battery fade (§4, *Battery ageing*) lower its later-year own-use.
  The anchor's injected results are the same at every age (§7.4).

Nor is the printed saving a [FEAS] figure: it is the representative home's §3 saving at
the column's own solved rate, on its annualised window.

On the 0.5.0 tag, which sums the window's kWh without annualising them, the column sets
three days of own-use against a year of opex and floor, and its rate clamps at the 23 p
retail rate (`infeasible_above_retail`).

---

## 8. The Flex Seam (W1 integration points)

W1 (flexibility-value finance integration, task/52–56) reaches the model two ways:
an exogenous CBS revenue term (§8.1) and endogenous physics that moves the energy
aggregates (§8.2).

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

W1's TOU + grid-charging dispatch buys off-peak grid energy into the battery
through the home's meter and discharges it at peak.  The householder pays the
off-peak import and avoids the peak import it displaces, so the time-shift value
lands in the householder's `import_cost_gbp` (§3), not in CBS revenue.

**Basis C and TOU arbitrage**: grid-charged battery energy crosses the grid boundary on
the way *in*, so it inflates `total_grid_import_kwh` and does *not* inflate
`own_use_kwh (basis C) = demand − import`.  Formally:

```
own_use_kwh (basis C) = sc_kwh (B-style) − grid_charge_kwh
```

So the CBS neither bills nor pays for grid-charged energy (§4) and bears only the
battery round-trip loss, absorbed into the solved rate.  The solved rate therefore
moves with arbitrage only through basis-C own-use (`fleet_sc` in `project_multi_year`).

Gates: `TestArbitrageBasisCReconciliation` pins the basis (fleet_sc is basis C on a
grid-charging fleet, task-84 §6), and `TestGridChargeEnergyPaidOnce` pins that each
grid-charged kWh is paid once, on householder import.
`TestFlexLowersSolvedRate::test_arbitrage_lowers_solved_rate` hard-asserts the
direction on a synthetic arbitrage fleet whose basis-C own-use is higher than the
flat-rate fleet's (2,400 vs 2,000 kWh/home), so it earns more own-use revenue and
solves at a lower rate.

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
| Override own-use | `min(override × generation, demand)`; surplus generation → export (§3, §4, §5) | `householder_bill()`, `_seg_export_income_gbp()`, `_billed_energy()` |
| VAT | `vat_rate × (import + standing + own_use_payment)` | `householder_bill()` |
| Total outlay | `(import + standing + own_use_payment) × (1+vat)` | `householder_bill()` |
| Saving | `baseline_bill − total_outlay` | `householder_bill()` |
| CBS revenue (no-flex) | `own_use_rate × fleet_sc / 100` (fleet_sc = Σ_homes `_billed_energy` own-use: basis C, or the capped override own-use; annualised; §4) | `project_multi_year()` |
| CBS revenue (full) | `own_use_rev + seg_rev + gs_income` | `project_multi_year()` |
| Grid-charge energy | in householder `import_cost_gbp`; no CBS term (§4) | `householder_bill()` |
| Solve rate-base | `fleet_sc` = Σ_homes `_billed_energy` own-use (basis C, or the capped override own-use; annualised; §2, §4, §5) | `_simulate_age()` |
| Solve | `r* = (floor − s0) / slope` (affine, closed-form) | `solve_cost_recovery_rate()` |
| Capex | `Σ(pv_kwp×pv_cost + roof_fit + batt_kwh×batt_cost)` | `project_economics()` |
| Net surplus | `mean(surplus_y) / n_homes` over 25 yr | `project_economics()` |
