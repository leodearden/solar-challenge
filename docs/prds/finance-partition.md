# PRD — Finance partition: a projection stratum above bill arithmetic

- **Program:** review-all-solar_challenge-20261013, stream **S8** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 2, size L, risk medium. Upstream: S1, S9, S10 (L9).
- **Finding keys (17):** fk-5fdb04305288, fk-41283f42a36a, fk-6cd8a932665c, fk-b0f648b0e6d0, fk-9cc706d3afdd, fk-c2c9277c1920, fk-c0e0ae3dcca8, fk-4a9af7c31a4f, fk-3b0a239d0489, fk-52fa98174363, fk-caeaf35c8151, fk-50cf1dd5df58, fk-9fa18977ec68, fk-3f4daea21220, fk-62dbe0f34b68, fk-808be5588896, fk-5b34adae950b. Disposition of each in §2.3. By cross-reference (L12 Q6) this PRD also decides the finance capex basis of fk-8b8f9d686b86, an S14 key.
- **Binding rulings:** D4 and D29 (one coordinated surface bump; additive frozen edits land in-leaf with an "Unreleased on main" line; a public name that moves module, here `solve_cost_recovery_rate`, moves in a held leaf, with `_SYMBOL_MODULE` repointed under the bump), D12 and D30 (one annualisation rule and the standing charge over `window.year_days`, landing in S10's 782), D10 (fill-and-refuse SEG), D24 (both assumption modes rendered, S25's work, which this PRD's per-mode run serves), D41 (S9's 837, firmness per event day, priced inside the projection's per-age node), D28 (weakened keys re-measured, §2.2), L9 (the move depends on S10 ε), L10 (S16 owns the four age-0 simulations of `finance run`), L12 Q6 (the capex basis is S8's to decide).
- **Status:** authored 2026-10-17 by an author-only /prd session; not committed, not decomposed. Decompose waits until the lead hands over the filed ids this batch depends on.
- **Approach:** B + H. The work touches 8 modules (`finance`, a new `projection`, `home`, `optimize`, `cli/finance`, `output`, `__init__`, the tests), has 11 mechanisms, sits on the frozen surface, and is consumed by S6, S9, S16, S25 and S29. So it carries a contract (§5) and a two-way boundary-test sketch (§9).
- **Code anchors** verified against main `c06d12b` (2026-10-17). Main moves fast: anchors cite symbols; re-locate lines at implementation time. Since the findings' pin `7dfea36`, `finance.py` changed only in task 716's `BillBreakdown` docstrings and task 773's top-level `ConfigurationError` import; `project_multi_year`, the solve and the billing helpers are byte-identical. `optimize.py` changed in tasks 704 and 717 (sensitivity bands, `apply_knob`); `_evaluate_config` and `_age0_baseline_outlay` are unchanged.

## 1. Goal

`finance.py` becomes the bill-arithmetic module that `config` can depend on: finance parameters, one billing ledger per home, the bill, and the cash-flow maths. Everything that takes a scenario and simulates a fleet moves to `projection.py`, a module above finance beside `optimize.py`: the 25-year projection, the project economics and the cost-recovery solve. It imports `fleet`, `home`, `pv`, `battery` and `gridservices` at module top. One home's year is assembled once, as a ledger whose balances are checked, and the bill and the projection both read it. How a run was priced travels as data from the simulator to finance instead of being inferred from pound totals. The solve hands its projection, its economics and its age-0 summaries to the callers that need them, so `optimize configs` and `finance run` stop re-simulating.

What a user observes:

1. **Bills price what was configured, not what pounds imply.** A home whose tariff is £0/kWh is billed £0 for its import, with no "no tariff configured" warning; today it is billed at the 23 p retail rate with that warning (task 690's measurement: £217.99). Under the spreadsheet assumption, a home whose battery absorbed every simulated export still earns the CBS its SEG on the override's export: £49.20 on 1,200 kWh at 4.1 p, where today it earns £0.00. A home with no tariff is still billed at retail with the warning, now keyed on the fact.
2. **The householder pays for the own-use the CBS earns on.** For every home, the own-use on its bill is the own-use in the projection's age-0 revenue: one ledger, read twice. A ledger whose own-use exceeds demand, or whose own-use and import cannot cover demand (the window-against-annual class of tasks 271 and 308), is refused, naming the values. Under the spreadsheet assumption, `YearPoint.fleet_export_kwh` is the export the SEG revenue is priced on, so revenue ÷ export is the SEG rate; today it is the physics export.
3. **One projection per config.** `optimize configs` simulates each config's fleet once per projection node: 5 calls on a constant fixture where today it makes 12 (the solve's projection, its age-0 outlay run, a second identical projection and a second age-0 run, probed). `finance run --project --cost-recovery` makes 6 calls where today it makes 12, before S16's reuse wrapper takes it lower. The baseline outlay and the solved outlay of a config are priced on the same age-0 fleet; today a scenario whose battery is 6 years old is ranked on two different fleets.
4. **The solve is exact.** Re-projecting a fleet at the solved rate meets the surplus floor, and the solved rate no longer depends on the configured own-use rate. Today, on task 720's fixture, the rate-shifted curve is off the re-projected one by up to £38.74 in a year. On the finding's node shapes the solved rate moves by 0.004–0.010 p/kWh across configured rates of 0, 15 and 23 p.
5. **Capex prices the array the revenue came from.** The physics projection of `scenarios/bristol-phase1.yaml` prices 420.449 kWp of PV, the modules the simulator wires, where today it prices the 430.0 kWp nameplate (2.22% lower PV capex). The spreadsheet calibration column still prices its 5.5 kWp homes at £775,000 (Capital_Stack!B6). An `optimize configs --pv 3,…` config is priced at the 2.803 kWp it generates from.
6. **The structure says what it is.** `pydoc solar_challenge.finance` names every public name of the module and no side-effect claim; finance.py carries no task-tracker codenames; no module or test imports an underscore name from `finance` or `projection`; `import solar_challenge.finance` still loads neither pvlib nor `fleet`, and finance.py has no function-local import of a package module except the one transitional entry the held leaf ι removes.
7. **At the bump (held).** `solar_challenge.solve_cost_recovery_rate` is defined in `projection`; `BillDistribution.per_home_net_bill_gbp` is `per_home_total_outlay_gbp`.

## 2. Background (measured at c06d12b)

### 2.1 What exists today

- **Two strata in one file.** finance.py is 2,370 lines, 45.3% prose (879 docstring, 194 comment-only, 416 blank, 881 code lines). The lower stratum (`FinanceConfig`, the bill types, `bill`, `householder_bill`, `bill_distribution` and the annualisation and billing helpers) does arithmetic over `SummaryStatistics`, and config imports `FinanceConfig` from it at top level. The upper stratum (`YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `project_multi_year`, `project_economics`, `spreadsheet_revenue_curve`, `solve_cost_recovery_rate` and their helpers) takes a `ScenarioConfig` and runs fleet simulations. Lower-to-upper code references: 0. Upper-to-lower: 11 names, 9 of them private.
- **The layering cost.** The upper stratum reaches the simulator through 9 function-local import statements: battery 1, fleet 4, home 2, pv 1, gridservices 1 (S9 α removes the last). `optimize.py` imports `finance._resolve_homes`, the only underscore-name import between src modules.
- **The ledger is assembled twice.** `householder_bill` annualises, applies the retail fallback, switches physics/override through `_billed_energy`, re-prices the override's import by a cost/kWh ratio and calls `bill`. `project_multi_year._simulate_age` annualises again, calls `_billed_energy` with `_cbs_own_use_kwh(s) * phys.scale`, sums the physics export and import, and calls `_seg_export_income_gbp`, which re-runs `_override_energy_split` and re-derives the SEG rate by a ratio. Nothing checks a home's balances.
- **Pricing is inferred from pounds.** `simulate_home` writes an all-zero `import_cost` series when the home has no tariff, and `SummaryStatistics` keeps only totals. `_physics_import_cost_gbp` reads "unpriced" as `cost == 0.0 and import > 0.0`; `householder_bill`'s override branch takes the import rate as cost ÷ kWh with a retail fallback; `_seg_export_income_gbp` takes the SEG rate as revenue ÷ export with a 0.0 fallback.
- **The solve hides what its callers need.** `solve_cost_recovery_rate` projects once at the configured rate and runs a second age-0 simulation for the outlay. `optimize._evaluate_config` then projects again with identical arguments and runs a third age-0 simulation through `_age0_baseline_outlay`, whose fleet differs from the solve's: it ages only PV, so a configured battery keeps its own SOH, and it skips the SEG fill. `cli/finance.run` also projects separately before the solve. The scenario-to-fleet resolution (homes, SEG fill, time zone, window) is written three times.
- **One 317-line function.** `project_multi_year` holds home resolution, time axes, a model guard, an 86-line closure `_simulate_age` with a capacity-at-events memo, the seed march, the bisection loop with a trial memo, and PCHIP assembly. The four driven metrics are written out in five places. Its cognitive complexity was 78 at the pin (complexipy), the next highest in the area 26.
- **A false exactness claim.** The solve's docstring and the model doc's §5 say surplus is exactly affine in the rate because PCHIP is linear in its node values. PCHIP is not linear (task 720 measured it at e5d7e80), so the shifted curve is exact only when the rate-independent income nodes are proportional to the own-use nodes.
- **Undocumented invariants.** `CostRecoverySolution` documents three invariants (feasible ⇔ binding, three copies of the representative's fields) and enforces none; `optimize.ConfigResult` copies five of its fields a third time.
- **Names that lie.** `BillDistribution.per_home_net_bill_gbp` holds total outlay, and its min, mean, median, max and representative docstrings say "net annual bill" and point at a "§12-Q4 deprecation list" no tracked file has.
- **Capex on nameplate, generation on wired DC.** `project_economics` prices `pv_config.capacity_kw`, while the simulator wires whole modules of the 400.428 W template: on the board fleet 3.0 kWp wires 2.803 (−6.6%), 5.0 wires 4.805 (−3.9%), 4.0 and 6.0 within 0.1%.

### 2.2 Re-measurement of the weakened keys (D28)

| key | measured at c06d12b | holds? |
|---|---|---|
| fk-b0f648b0e6d0 (two strata) | 9 function-local package imports in finance.py: the skeptic's 8 that close no cycle, plus the gridservices import S9 α removes (S1 already removed the two cycle-closing `ConfigurationError` imports); upper→lower private names: `_annualise_physics`, `_billed_energy`, `_cbs_own_use_kwh`, `_seg_export_income_gbp`, `_annuity_payment`, `_irr_bisection`, `_annualisation_scale`, `_ANNUALISATION_DAYS`, `_SHORT_PERIOD_THRESHOLD` (9; the last three go with S10 ε); lower→upper 0; one private src import (`optimize` ← `_resolve_homes`) | yes, with the skeptic's wider interface |
| fk-9cc706d3afdd (private layer as interface) | 7 private names imported by 5 test modules: 63 occurrences by `grep -w`, 31 name uses outside import statements by AST; the src import above | yes (counts as stated by method) |
| fk-41283f42a36a (purpose needs four "and"s) | unchanged purpose; 40 codename hits (CR3 ×8, W1/W2/W3, CR1/CR4, H3/H4/H6, T2, step-8/16, task 64/83/84, 9 Greek letters, "Suggestion 3/4") | yes |
| fk-5b34adae950b ("exactly affine") | docstring and doc §5 unchanged; task 720's measurement (£38.74 in one year at e5d7e80) and the finding's (£41–150 a year, r* spread 0.004–0.010 p) stand: the projection is byte-identical since | yes |
| fk-50cf1dd5df58 (SEG ratio on override) | `_seg_export_income_gbp`'s ratio and 0.0 fallback unchanged | yes |

### 2.3 Key dispositions (contract §8 step 1, run 2026-10-17)

| key | step-1 result | this PRD |
|---|---|---|
| fk-6cd8a932665c | no task by key; report row `filed:581` (581 carries no key and plans prose for task 350's four-module split) | α; 581 superseded (§12 Q1) |
| fk-3f4daea21220 | none | α (docstrings) and κ (rename, held) |
| fk-52fa98174363 | none | β |
| fk-50cf1dd5df58 | `filed:715` (pending) | β; 715 superseded and its key moved to β (§12 Q1) |
| fk-caeaf35c8151, fk-c2c9277c1920 | none | γ |
| fk-9cc706d3afdd | none | γ (tests) and δ (optimize) |
| fk-b0f648b0e6d0, fk-41283f42a36a, fk-5fdb04305288 | none | δ (and ι for the frozen name) |
| fk-c0e0ae3dcca8, fk-5b34adae950b | none by key; tasks 730, 720, 721 cover parts without keys | ε; 730, 720, 721 superseded (§12 Q1) |
| fk-4a9af7c31a4f, fk-3b0a239d0489 | none by key; task 582 covers part without a key | ζ; 582 superseded |
| fk-808be5588896 | none | η |
| fk-62dbe0f34b68 | `filed:702` (in progress: the `fleet_billed_own_use_kwh` rename and the dead revenue clamp) | not filed; every leaf here builds on 702 |
| fk-9fa18977ec68 | task 716 `done`; its finding re-read absent (BillBreakdown describes the billed period and points at `bill()`; the doc's Summary capex row has the inverter term) | not filed |
| fk-8b8f9d686b86 (S14's key) | 812, 818 (S14) | θ carries it for the finance half only |

### 2.4 Tasks this PRD meets

- **Superseded at decompose (§12 Q1):** 350 (the finance.py split into three modules, by δ), 581 (prose for that split, by α), 582 (the age-0 outlay written twice, by ζ), 690 (the £0 tariff, by β), 715 (the override SEG rate, by β), 720 (the affine claim, by ε), 721 (the revenue deviation scale, by ε), 730 (`project_multi_year` heuristics 2 and 4, by ε). Each is pending and each edits code a leaf here rewrites.
- **Re-scoped:** 667 (the web chart's "no tariff configured" note) reads `SimulationResults.pricing` from β instead of defining its own `RunPricing`.
- **Depended on:** 702 (in progress), S1's 775 (in progress), S9's 801, 837 and 802, S10's 782 and 783, S14's 812, and 738 (in progress: `cli/finance.run` restructure, fk-f66948b9528c).
- **Order-agnostic, textual only:** S16's 885 (required `simulate`), 890 (age-0 reuse in `finance run`) and 892 (held); S28's 865 (throughput docstrings); S4's 862 (finite finance inputs); 764 and 765 (optimize prose).

## 3. Rulings and how this PRD reads them

- **D4, D29.** Additive public names (`RunPricing`, the ledger, the cash-flow maths, `projection.py`'s names) land in-leaf. Non-frozen names that change module (`project_multi_year`, `YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `project_economics`, `spreadsheet_revenue_curve`) move in-leaf with an Unreleased line: none is on a frozen table, and the platform imports none of them (grep of solar-challenge-platform `45ecca2`). `solve_cost_recovery_rate` is in `__all__`: its implementation moves in δ, finance.py keeps the frozen name as a transitional wrapper, and held leaf ι repoints `_SYMBOL_MODULE` at the bump. `CostRecoverySolution` stays in finance.py: it reads only `BillDistribution` and needs nothing above. The `per_home_net_bill_gbp` rename is a retirement, held in κ.
- **D12, D30.** S10's 782 lands the window rule in finance first. The ledger (γ) annualises by `summary.window.annualisation_scale` and `householder_bill` keeps billing the standing charge over `window.year_days`. S10 ε's own-use bound moves into the ledger's invariants.
- **D10.** The scenario SEG fills homes without a `seg_tariff` and a contradicting home is refused: `_reconcile_seg_homes` already does this, and it moves into `projection.scenario_fleet` until S6 replaces it with `ScenarioConfig.with_seg`. A home's SEG rate then has one home, `HomeConfig.seg_tariff`, which `simulate_home` copies into `RunPricing`.
- **D24.** Rendering both modes is S25's. This PRD gives each mode one run: `run_cost_recovery(fleet, finance_for_mode)` returns that mode's projection, economics and solve, and each home's ledger names its own-use basis.
- **D41.** S9 α and 837 price grid-services income per simulated age from that age's fleet. ε's node function keeps that call and books the figure in the rate-independent income term.
- **L9.** δ depends on S10 ε (782). β and γ, which edit the same billing functions, depend on it too.
- **L10.** The bill run's age-0 reuse is S16's (890). The duplicated projection in `finance run` and `optimize` is this PRD's (S16 decision 8 hands it here).
- **L12 Q6.** Decided in §6 decision 9.

## 4. Sketch of approach

1. **α. Prose first.** Rehome finance.py's history and reviewer prose, fix the docstrings that lie, correct the exactness claim to what holds, and re-measure. No code change.
2. **β. Pricing as data.** `simulate_home` records how it priced the run in `SimulationResults.pricing`; `calculate_summary` carries it to `SummaryStatistics.pricing`; finance prices import and SEG from it.
3. **γ. One ledger.** `home_ledger(annualise(summary), finance)` is the one path from a summary to the billed year; `householder_bill` and the projection's age simulation both read it; the cash-flow maths go public.
4. **δ. The move.** `projection.py` takes the upper stratum and `scenario_fleet`, the one resolution of a scenario into the fleet and window to simulate. finance.py keeps the frozen solve as a wrapper until ι.
5. **ε. The projection, factored.** A module-level node function, one tuple of driven metrics, a pure assembler, and revenue built as rate × own-use + income, so the solve is exact.
6. **ζ. One projection per run.** `run_cost_recovery` returns the projection, its economics and the solve; the solve's outlay reads the projection's age-0 summaries; `optimize` and `finance run` use it.
7. **η.** `CostRecoverySolution` enforces its documented invariants; `ConfigResult` stops copying them.
8. **θ.** The curve records the PV DC its generation came from, and `project_economics` prices it.
9. **ι, κ (held for S29).** The frozen solve moves module; the misnamed field is renamed.

## 5. Contract

### 5.1 The pricing fact (`home.py`; β)

```python
@dataclass(frozen=True)
class RunPricing:
    """How simulate_home priced a run's grid flows, from the home's tariff and SEG tariff."""
    import_tariff_mean_rate_gbp_per_kwh: Optional[float]   # None: no tariff priced the import; else the tariff's time-weighted mean rate over the run (a £0 tariff is 0.0, priced)
    seg_rate_pence_per_kwh: Optional[float]                # None: no SEG tariff; else HomeConfig.seg_tariff's rate
    # __post_init__: each set value finite and >= 0, else ValueError naming the field and value

class SimulationResults:   # gains a last field (additive; its FROZEN_* entries); its series iteration skips it
    pricing: Optional[RunPricing] = None    # simulate_home always sets it; None for results it did not make (from_dataframe)

class SummaryStatistics:   # gains a last field (additive; FROZEN_SURFACE form)
    pricing: Optional[RunPricing] = None    # calculate_summary copies results.pricing
```

- **One writer.** `simulate_home` builds `RunPricing` from `HomeConfig.tariff_config` and `seg_tariff`. Nothing derives it from pound totals.
- **Unknown is not unpriced.** `None` on the summary means the pricing is unknown (results built from a CSV, or a hand-built summary). Finance refuses such a summary, naming `pricing` and `calculate_summary`, as S10 ε refuses a window-less one. It stays Optional permanently, because `from_dataframe` results have no pricing to carry.
- `RunPricing` joins `FROZEN_CLOSURE`, as `SimulationWindow` did.

### 5.2 The lower interface (`finance.py`; γ)

```python
@dataclass(frozen=True)
class AnnualPhysics:                # was _AnnualisedPhysics
    window: SimulationWindow        # the window the summary covers (S10)
    scale: float                    # window.annualisation_scale
    generation_kwh: float; demand_kwh: float
    import_kwh: float; import_cost_gbp: float      # the simulated import and its simulated cost, scaled
    export_kwh: float; battery_discharge_kwh: float
    pricing: RunPricing

def annualise(summary: SummaryStatistics) -> AnnualPhysics: ...
    # ValueError naming `window` or `pricing` when either is None

def basis_c_own_use_kwh(summary: SummaryStatistics) -> float: ...
    # demand − import over the summary's window, clamped at 0 with today's UserWarning (was _cbs_own_use_kwh)

class OwnUseBasis(Enum):
    SIMULATED = auto()   # own-use from the simulation (basis C, or householder_bill's caller figure); import and export are the simulated flows
    OVERRIDE = auto()    # FinanceConfig.self_consumption_override splits generation and demand

@dataclass(frozen=True)
class HomeLedger:
    """One home's year as the CBS bills it."""
    basis: OwnUseBasis
    generation_kwh: float; demand_kwh: float
    own_use_kwh: float                  # the own-use the householder pays for and the CBS earns on
    import_kwh: float; import_cost_gbp: float
    import_at_retail: bool              # no tariff priced this home, so import is priced at the retail baseline
    export_kwh: float; seg_income_gbp: float   # SEG income is CBS revenue
    own_use_capped: bool                # OVERRIDE only: override × generation exceeded demand

def home_ledger(physics: AnnualPhysics, finance: FinanceConfig, *, simulated_own_use_kwh: Optional[float] = None) -> HomeLedger: ...
    # simulated_own_use_kwh: annual own-use for the SIMULATED basis; None means basis C from physics

def annuity_payment(principal: float, rate: float, n_years: int) -> float: ...   # was _annuity_payment
def npv(rate: float, cashflows: Sequence[float]) -> float: ...                    # was _npv
def irr(cashflows: Sequence[float]) -> float: ...                                 # was _irr_bisection; nan when undefined
```

**Pricing rules, all inside `home_ledger`:**

| quantity | SIMULATED basis | OVERRIDE basis |
|---|---|---|
| own-use | `simulated_own_use_kwh`, or basis C = max(0, demand − import) | min(override × generation, demand) |
| import, export (kWh) | the simulated flows | demand − own-use; generation − own-use |
| import cost, priced | `physics.import_cost_gbp` | override import × (simulated cost ÷ simulated import kWh, or the tariff's mean rate when the simulated import is 0) |
| import cost, unpriced | import × retail; `import_at_retail` | override import × retail; `import_at_retail` |
| SEG income | export × `seg_rate_pence_per_kwh` / 100; 0.0 when the rate is `None` | the same, on the override's export |

`home_ledger` warns about nothing. `householder_bill` warns when `import_at_retail` (today's text, now keyed on the fact) and when `own_use_capped` (today's text). The projection calls it per home per age and stays silent, as today.

**Invariants (`HomeLedger.__post_init__`, `ValueError` naming the invariant and every value in it):**

- L1. Every figure finite and ≥ 0.
- L2. `own_use_kwh ≤ demand_kwh`: a home cannot own-use more than it demands. S10 ε's bound on `householder_bill`'s own-use moves here.
- L3. `demand_kwh ≤ own_use_kwh + import_kwh` (to `rel 1e-12`): own-use and import cover demand. It holds for basis C (equality, or import above demand when the basis-C clamp binds), for a caller's B-style self-consumption (demand plus the grid charge), and for the override (equality). It refuses an own-use on another time basis than the import, the class of tasks 271 and 308.
- L4. OVERRIDE only: `own_use + import == demand` and `own_use + export == generation` (to `rel 1e-12`).

The comparisons in L2–L4 allow a relative 1e-12, which is the float rounding of one subtraction and one scaling, and nothing more.

**Readers.**

- `householder_bill(summary, own_use, finance, simulation_days)`: frozen signature. It refuses a mismatched day count (S10 ε), builds `home_ledger(annualise(summary), finance, simulated_own_use_kwh=own_use × scale)`, warns as above and calls `bill(period_days=window.year_days, …)` with the ledger's own-use, import, import cost, and demand × retail as the baseline.
- `bill_distribution`: unchanged, passing `basis_c_own_use_kwh(s)`.
- The projection's node (§5.4) sums `home_ledger(annualise(s), finance)` over the fleet.

### 5.3 The upper interface (`projection.py`; δ creates, ε and ζ extend, θ adds one field)

```python
@dataclass(frozen=True)
class ScenarioFleet:
    """The homes a scenario projects, SEG filled (D10), and the window to simulate them over."""
    homes: tuple[HomeConfig, ...]   # non-empty, else ValueError
    start: pd.Timestamp; end: pd.Timestamp

def scenario_fleet(scenario: ScenarioConfig) -> ScenarioFleet: ...
    # homes from either form; scenario SEG filled, contradiction refused by name (today's _reconcile_seg_homes);
    # start/end from scenario.period in scenario.location's zone, else the first home's. S6 later swaps the homes for ScenarioConfig.with_seg.

YearPoint, MultiYearCurve, ProjectEconomics      # moved unchanged in δ (YearPoint after 702)
class MultiYearCurve:                             # θ adds one field
    fleet_pv_dc_kw: float                         # the PV DC the curve's generation came from, kWp; > 0 and finite

@dataclass(frozen=True)
class FleetProjection:                            # ε
    curve: MultiYearCurve
    age0_summaries: tuple[SummaryStatistics, ...] # the age-0 node's per-home summaries, fleet order

def project_fleet(fleet: ScenarioFleet, finance: FinanceConfig, *, simulate: FleetSimulate,
                  error_target_pct: float = 1.0) -> FleetProjection: ...            # ε
def project_multi_year(scenario: ScenarioConfig, finance: FinanceConfig, *,
                       error_target_pct: float = 1.0, simulate: ...) -> MultiYearCurve: ...
    # project_fleet(scenario_fleet(scenario), …).curve; simulate's form is whatever S16 γ (885) has left at the leaf's base
def project_economics(curve: MultiYearCurve, fleet: ScenarioFleet, finance: FinanceConfig) -> ProjectEconomics: ...
    # δ changes the second parameter from the scenario to the resolved fleet
def spreadsheet_revenue_curve(*, n_homes, pv_kwp, kwh_per_kwp, self_consumption_fraction,
                              own_use_rate_pence_per_kwh, export_rate_pence_per_kwh, asset_life_years) -> MultiYearCurve: ...

@dataclass(frozen=True)
class CostRecoveryRun:                            # ζ
    projection: FleetProjection                   # at finance.own_use_rate_pence_per_kwh, the configured rate
    economics: ProjectEconomics                   # project_economics(projection.curve, fleet, finance)
    solution: CostRecoverySolution                # the solved rate; its outlay from projection.age0_summaries

def run_cost_recovery(fleet: ScenarioFleet, finance: FinanceConfig, *, simulate: FleetSimulate) -> CostRecoveryRun: ...
def solve_cost_recovery_rate(scenario, finance, *, simulate=None) -> CostRecoverySolution: ...
    # the frozen form; run_cost_recovery(scenario_fleet(scenario), …).solution
```

- **Imports.** `projection.py` imports `battery`, `config`, `finance`, `fleet`, `gridservices`, `home` and `pv` at module top. Importing it loads pvlib. Nothing below it imports it.
- **finance.py until ι.** `solve_cost_recovery_rate` keeps its frozen form and delegates to `projection.solve_cost_recovery_rate` through one function-local import. That import is the only package import inside a function in finance.py, and it is a `Transitional` allow-list entry owned by ι, which deletes the wrapper and the entry at the bump. This is heuristic 13's re-export symptom, bounded by D4's one bump.
- **Required `simulate`.** The new functions (`project_fleet`, `run_cost_recovery`) take `simulate: FleetSimulate` as a required keyword (S16's direction). The two scenario-level functions keep whatever form S16 has left (885 makes `project_multi_year`'s required; 892 does the solve's at the bump).

### 5.4 The projection's shape (ε)

- **Node.** `_simulate_node(fleet, age, throughput, finance, grid_services, simulate)` is a module-level function. It ages the homes, simulates them, summarises each home, sums the ledgers and prices grid services per age through S9's `grid_services.annual_income_gbp(fleet_results)`. It returns the node and the per-home summaries. No closure and no memo outlive a call.
- **Driven metrics.** `fleet_own_use_kwh`, `fleet_export_kwh`, `fleet_import_kwh` and `fleet_income_gbp` (SEG plus grid services, independent of the own-use rate) are one tuple of named accessors. The bisection loop iterates it. Adding a metric is one entry.
- **Deviation scale.** Each metric's midpoint deviation is normalised by the largest magnitude that metric takes at the seed ages, floored at 1e-9 in its unit. It is fixed once the seeds are simulated, positive for any income, and needs no revenue sign.
- **Revenue.** Each year's revenue is `own_use_rate × own_use_y / 100 + income_y`, where `own_use_y` and `income_y` are the PCHIP curves of their nodes. Revenue is not interpolated. Node selection reads no rate, so a projection at rate r is the configured projection with its revenue shifted by (r − r₀)/100 × `own_use_y`, and the solve's two-point affine fit is exact. `interp_error_estimate` covers the four driven metrics.
- **Assembly.** A pure function turns the node map into the `MultiYearCurve`.

### 5.5 The solve and its callers (ζ)

- `run_cost_recovery`: one `project_fleet` at the configured rate; `economics` from its curve; `surplus_at(r)` from the curve, exact after ε; the outlay is `bill_distribution(projection.age0_summaries, finance at the solved rate, …)`. There is no second simulation. The outlay's fleet is the projection's age-0 fleet (`_aged_homes(homes, 0, zeros)`), which is the fleet today's solve simulates separately.
- `optimize._evaluate_config`: one `run_cost_recovery`. The solution gives the rank fields, `run.economics` the baseline economics, and `bill_distribution(run.projection.age0_summaries, finance, …).representative.total_outlay_gbp` the baseline outlay. `_age0_baseline_outlay` is deleted.
- `cli/finance.run`: with `--project` and `--cost-recovery`, one `run_cost_recovery` supplies the curve, the economics and the solution. `--project` alone runs `project_fleet` and `project_economics`.
- The configured own-use rate is read, never written as "15 p": optimize's docstrings and `output.generate_config_ranking_report`'s second table header name `finance.own_use_rate_pence_per_kwh`.

### 5.6 `CostRecoverySolution` (η)

`__post_init__` refuses, naming both values:

- `feasible != (binding != "infeasible_above_retail")`;
- `representative_outlay_gbp != outlay.representative.total_outlay_gbp`;
- `saving_vs_baseline_gbp != outlay.representative.saving_vs_baseline_gbp`;
- `saving_pct != outlay.representative.saving_pct`.

These are bare equalities, because the solve copies the same floats. `optimize.ConfigResult`'s five copies of solution fields become read-only properties over `solution`.

### 5.7 Invariants and where each is enforced

| # | Invariant | Construction | Use |
|---|---|---|---|
| C1 | A run's pricing is data written once, by `simulate_home`, never inferred from pounds | `RunPricing` | `home_ledger` reads only it; a pricing-less summary is refused by `annualise` |
| C2 | One home's billed year has one assembly | `home_ledger` is the only producer of `HomeLedger` in src | `householder_bill` and the projection node both call it; B5 compares them |
| C3 | A ledger's balances hold (L1–L4) | `HomeLedger.__post_init__` | the bill's own-use bound (S10 ε) now reads the ledger |
| C4 | finance.py holds no symbol that simulates or takes a scenario, and imports no package module inside a function except the wrapper ι removes | δ's move | `tests/unit/test_import_structure.py` (775) |
| C5 | No module or test reaches an underscore name of `finance` or `projection` | γ, δ | grep delivered checks; the tests drive public names |
| C6 | Projected revenue is rate × own-use + income in every year, so the solve is exact and independent of the configured rate | ε's assembler | B8 |
| C7 | A run's age-0 fleet is simulated once and every age-0 figure reads it | ζ | B10, B11 |
| C8 | `CostRecoverySolution`'s copies equal their source | η's `__post_init__` | `ConfigResult` reads through properties |
| C9 | Capex prices the PV DC the curve's generation came from | θ: each curve producer fills `fleet_pv_dc_kw` | `project_economics` reads only it for the PV term |
| C10 | `import solar_challenge.finance` loads neither pvlib nor `fleet` (S1 C7, S16 I10) | finance's imports | existing probe; B7 |

### 5.8 Surface ledger for S29 (D4)

| Leaf | Change | Release text and consumer action |
|---|---|---|
| β | `RunPricing` (closure); `SimulationResults.pricing`, `SummaryStatistics.pricing` (last fields, default `None`) | additive; Unreleased line. A consumer that builds `SummaryStatistics` by hand and bills it passes `pricing=RunPricing(...)`, as it passes `window` after S10 ε (the platform's parity tests do both) |
| β | `householder_bill`/`bill_distribution` refuse a summary whose pricing is `None`; a £0 tariff bills £0; the override's SEG reads the home's rate | Unreleased line (behaviour) |
| γ | `HomeLedger`, `home_ledger`, `AnnualPhysics`, `annualise`, `basis_c_own_use_kwh`, `OwnUseBasis`, `annuity_payment`, `npv`, `irr`: new public names of `solar_challenge.finance`, outside `__all__` | Unreleased line; `householder_bill` refuses a ledger that breaks L2–L4 |
| δ | `project_multi_year`, `project_economics`, `spreadsheet_revenue_curve`, `YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `MAX_NODES` move to `solar_challenge.projection`; `project_economics` takes a `ScenarioFleet` | Unreleased line: not frozen; the platform imports none (measured) |
| η | `CostRecoverySolution` refuses inconsistent copies | Unreleased line (behaviour of a frozen constructor) |
| θ | physics capex prices wired DC | the model doc's header Unreleased line; board capex moves (§12 Q4) |
| ι (held) | `_SYMBOL_MODULE["solve_cost_recovery_rate"] = "projection"`; `solar_challenge.finance.solve_cost_recovery_rate` retired; touching the name now loads pvlib | release section; consumption doc's lazy-import list gains the name |
| κ (held) | `BillDistribution.per_home_net_bill_gbp` → `per_home_total_outlay_gbp` | release section; consumers rename the keyword |

## 6. Resolved design decisions

1. **One module above finance, named `projection.py`.** The stream row names one stratum. Task 350's three-module split (projection, economics, cost recovery) would leave `economics.py` with one function over a curve and `cost_recovery.py` with one function over a projection: satellites with no depth (heuristic 9). The upper stratum measures about 1,000 lines with its prose; after α and ε it is well under the ceiling. The program's D4 calls it "the new projection module", and S10, S16 and S28 already refer to it by that name.
2. **`CostRecoverySolution` stays in finance.py.** It reads only `BillDistribution`. The solve's extra outputs go on `CostRecoveryRun` in projection.py, not on the frozen class, so no frozen form grows and no lower type references a higher one.
3. **Pricing rides on the results, and unknown is refused.** The fact originates where the configuration is known (`simulate_home`) and travels with the data, as S10's window does (heuristic 7). The alternatives were a `calculate_summary` parameter, which every caller would have to thread, or a summary-only field, which `calculate_summary` could not fill. `None` stays legal because CSV results have no pricing. Finance refuses it rather than guessing (no silent fail-soft).
4. **The override prices its import at the home's own rate.** It uses the simulated cost ÷ kWh, or the tariff's time-weighted mean when nothing was imported, and retail only when unpriced. Today's retail fallback on zero simulated import bills a priced home at someone else's rate.
5. **SEG income is export × the home's SEG rate on both bases.** On the simulated basis this equals today's simulated export revenue to float precision (simulate_home prices each minute's export at the same flat rate), so physics board figures do not move. On the override basis it removes the ratio and its zero-export fallback. Finance no longer reads `total_export_revenue_gbp` or `seg_revenue_gbp`, which S25 then reduces to one figure.
6. **The ledger's basis has two values, and its balance is a bracket.** `householder_bill`'s frozen own-use parameter accepts the caller's figure (27 test calls pass the B-style self-consumption), so the simulated basis cannot pin own-use to demand − import. The bracket own-use ≤ demand ≤ own-use + import holds for every legitimate figure and refuses the time-basis mismatches the history shows. The override's two identities are exact, so they are checked exactly.
7. **The solve's projection is the configured-rate projection, and its age-0 node is the outlay's fleet.** Today's solve simulates `_aged_homes(homes, 0)` separately, which is the same fleet the projection's age-0 node simulates. The baseline outlay of `optimize` moves to that fleet too: a new install at age 0 with the scenario's SEG filled. That is what `enumerate_configs`' install points describe. A configured battery's own SOH or age no longer makes the two outlays of one config disagree.
8. **Revenue is affine in the rate by construction (task 720's option b).** Interpolating own-use and the rate-independent income separately costs no extra simulation, makes the solve's docstring and the model doc's §5 true, removes the configured rate's influence on the solved rate and on node selection, and makes revenue ≥ 0 by construction, which settles 721's sign problem. The cost is that per-year revenue between nodes moves slightly (§12 Q4). The alternative, correcting the claim and keeping the approximation, was rejected: it leaves the solved rate depending on an input the doc calls irrelevant.
9. **Capex prices the PV array the curve's generation came from (L12 Q6).** The physics projection simulates `pv.wired_dc_capacity_kw` of each home: whole template modules, 2.22% below nameplate on the board fleet and up to 6.6% off at 3 kWp. Pricing the nameplate pays for modules the projection never generates from, and biases `optimize`'s ranking by size: a 3 kWp config is charged for 3.0 kWp and credited with 2.803 kWp of generation. Pricing wired DC everywhere would break the spreadsheet column, whose generation is nameplate × yield and whose capex the calibration gate pins at £775,000. So the curve carries the PV DC its generation came from (`fleet_pv_dc_kw`): `project_fleet` sums wired DC, and `spreadsheet_revenue_curve` uses its own `n_homes × pv_kwp`. Each column is consistent with itself, and the PV size has one definition per curve (heuristic 11). A fleet total suffices because the PV capex term is linear in kWp. If S14 later wires the nameplate exactly, capex follows with no edit.
10. **`scenario_fleet` is this PRD's; homes and SEG become S6's.** One function resolves a scenario once, where today three do it three ways. S6's `ScenarioConfig.homes()` and `with_seg()` replace the two private helpers inside it later, so S6 edits one function and deletes two helpers.
11. **Prose first, then code.** α changes no code, so every later leaf moves less prose, and the re-measurement that justifies δ (finance.py still past the 2,000-line alarm after rehoming) is taken on clean prose.
12. **No dual field for `per_home_net_bill_gbp`.** D4 says no dual field survives the bump, and the field has no src reader outside finance and no platform reader (grep), so κ renames it in one step at the bump.
13. **`CostRecoverySolution`'s duplicated fields stay, enforced.** The stream row asks for construction-time enforcement. Turning `binding` into an enum and the copies into properties would be a second frozen-form break for little gain once the copies are checked (§12 Q3).

## 7. Pre-conditions

- **α:** 702 merged (it rewrites the same docstrings: the 22-line YearPoint note goes with it).
- **β:** α; S10's 782 (and so 778's `SummaryStatistics.window`, whose codec branch carries a nested Optional dataclass).
- **γ:** β; S9's 801 (it rewrites `_simulate_age`).
- **δ:** γ; S9's 801 and 802 (802 depends on 837); S10's 782; S1's 775 (the allow-list δ edits).
- **ε:** δ.
- **ζ:** ε; S10's 783 and task 738 (both edit `cli/finance.run` and the ranking report).
- **η:** ζ.
- **θ:** ε; S14's 812 (wired DC read from the built PVSystem; the figures in §1 are re-measured on it).
- **ι:** δ, ζ; held for S29 (`x_seam_wait`).
- **κ:** α; S10's 784 (both edit `BillDistribution`'s frozen form); held for S29.

G3 substrate verified at c06d12b:

- `pv.wired_dc_capacity_kw` exists and sizes from the same helpers `create_pv_system` wires with. 812 makes it read the built system.
- `SimulationResults.tariff_rate` exists when a tariff is configured, and `simulate_home` holds `config.tariff_config` and `config.seg_tariff`.
- `web.storage._deserialize_value` rebuilds an Optional nested dataclass of floats (it reads a union's first non-None member and a dict as a dataclass).
- `tests/_cli_fleet_simulator.invoke_cli` takes a simulator callable, and `tests/_finance_builders.make_fleet_results` builds constant fleets. The probe of §1 item 3 used them.
- 775's `tests/unit/test_import_structure.py` (on `task/775`) has `Transitional` reasons and lists the four finance entries δ deletes under an S8 owner.
- `scipy.interpolate.PchipInterpolator` is in use.

No other substrate is assumed.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 Errors leaf (773 done, 775) | shrinks | δ deletes `finance → battery, fleet, home, pv` from 775's allow-list and adds `finance → projection` (Transitional, owner ι); ι deletes it | S8 | δ depends on 775 |
| S9 Grid services (801, 837, 802, 804) | consumes | the move carries `grid_services_model_of` until 804 deletes it; ε's node keeps the per-age `annual_income_gbp` call inside `fleet_income_gbp` | S9 owns pricing; S8 the node | δ depends on 801, 802 (program cross-reference) |
| S10 Window (782, 783, 784) | consumes | `summary.window` drives `annualise`; ε's own-use bound becomes ledger L2; `MultiYearCurve.annualised_from` moves with the class; κ and 784 both edit `BillDistribution` | S10 window; S8 ledger | β, γ, δ depend on 782; ζ on 783; κ on 784 |
| S16 Fleet execution (885, 890, 892) | shares | 885 makes `project_multi_year`'s `simulate` required wherever it lives at its base; 890 wraps `finance run`'s simulate for reuse; 892 and ι both change the solve at the bump; ζ removes the duplicated projection S16 hands here | S16 simulator; S8 projection | cross-reference; order-agnostic |
| S6 Fleet-document overlays | produces for | `projection.scenario_fleet` is the one place homes are resolved and SEG filled; S6 swaps in `ScenarioConfig.homes()`/`with_seg()` there and deletes `_resolve_homes` and `_reconcile_seg_homes` from projection.py | S6 | **proposed:** S6's homes leaf depends on δ |
| S25 Board reports | produces for | per-mode `run_cost_recovery` (one projection, economics and solve per mode, D24); `HomeLedger.basis`; finance no longer reads the SEG revenue pair | S25 | **proposed:** S25's `cli/finance.run` restructure depends on ζ |
| S19 Run store (822) | produces for | `SummaryStatistics.pricing` in stored summaries; a summary stored before β loads with `pricing=None`, which the web never bills and finance refuses | S19 format | **proposed** cross-reference |
| S28 Battery facts (865) | shares | 865 rewrites the docstrings of `_throughput_at`, `_aged_homes` and `per_home_throughput`, which δ moves | whichever lands second carries the text | textual |
| S14 PV model (812) | consumes | θ prices `pv.wired_dc_capacity_kw` | S14 the quantity; S8 the price | θ depends on 812 |
| S29 Surface bump | produces for | §5.8; ι and κ held | S29 | held |
| S23 Surface lock | touches | β, η, ι, κ edit `FROZEN_*` tables | S23 | whichever lands second adapts |
| S4 (862), S12 | file overlap | `FinanceConfig.__post_init__`; `SummaryStatistics` (named loads) | — | textual |
| Task 667 (web chart note) | consumes | reads `SimulationResults.pricing` (β) | S8 the fact; 667 the chart | **proposed:** 667 depends on β |
| Task 702 | produces for | `fleet_billed_own_use_kwh`; the dead clamp dropped | 702 | α depends on 702 |

## 9. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| B1 | producer: home | pricing recorded | `simulate_home` over 2024-06-21 (synthetic weather) for a home with `TariffConfig.flat_rate(0.0)` and SEG 15 p; the same with no tariff and no SEG; a `from_dataframe` result | `results.pricing == RunPricing(0.0, 15.0)`, then `RunPricing(None, None)`, then `None`; `calculate_summary` copies each; a stored summary round-trips its pricing | β |
| B2 | consumer: bill | priced £0 is £0 | B1's £0 home; a no-tariff home; a summary with `pricing=None` | the £0 home's import cost is 0.0 with no warning (RED: task 690's £217.99 and the warning); the no-tariff home is billed at retail with the warning; the pricing-less summary raises naming `pricing` and `calculate_summary` | β |
| B3 | consumer: projection | override SEG at the home's rate | override 0.7; generation 4,000, demand 3,400; simulated export 0 kWh; SEG 4.1 p | the home's SEG income is £49.20 (RED: £0.00); with simulated export 1 kWh it is the same £49.20 | β |
| B4 | producer: ledger | balances refused | hand-built `HomeLedger`s | own-use 3,500 > demand 3,400 raises naming both; own-use from a 30-day window against an annual import (own-use + import < demand) raises naming the three; an OVERRIDE ledger whose own-use + export ≠ generation raises naming the three | γ |
| B5 | both: bill ↔ projection | one ledger, read twice | a 3-home constant fleet, SEG 4.1 p, under the simulated basis and under override 0.7 | each home's bill own-use (`own_use_payment ÷ rate × 100`) equals its age-0 ledger own-use in the projection; `points[0].fleet_billed_own_use_kwh` equals their sum; under the override, `fleet_export_kwh` equals Σ override export and the SEG part of revenue ÷ `fleet_export_kwh` equals 4.1 p (RED: physics export) | γ |
| B6 | consumer: tests, optimize | no private reach | the tree | no `from solar_challenge.finance import _…` or `projection import _…` in `src/` or `tests/`; the tests of the oracle cases compute basis C as demand − import written out | γ, δ |
| B7 | layering | the strata | the tree; a fake-simulator `finance run --project --cost-recovery` fixture | `test_import_structure` passes with the four finance entries gone and one Transitional `finance → projection`; `python -I -c "import solar_challenge.finance"` leaves `pvlib` and `solar_challenge.fleet` out of `sys.modules`; the report is byte-identical before and after δ | δ |
| B8 | consumer: solve | exact and rate-free | task 720's node fixture (ages 0, 12, 24; own-use 10,000/9,000/6,000 kWh; income £500/800/820) through an injected simulate; r₀ ∈ {0, 15, 23} | re-projecting at r* gives net surplus = floor within £1e-6/home/yr, and r* is equal across the three r₀ within 1e-12 p. RED today: the re-projection misses the floor, because task 720 measured the shifted curve on these nodes off the re-projected one by up to £38.74 in a year, and r* moves with r₀ | ε |
| B9 | producer: projection | robust deviation scale | a fixture whose age-0 income is 0 and later ages earn | the projection converges below `MAX_NODES` with a finite `interp_error_estimate` | ε |
| B10 | consumer: optimize, CLI | one projection per run | a counting constant simulate (asset life 25) | `_evaluate_config` makes 5 calls (RED: 12); `finance run --project --cost-recovery` makes 6 (RED: 12); `run_cost_recovery(...).solution == solve_cost_recovery_rate(...)` on the same input | ζ |
| B11 | consumer: optimize | one age-0 fleet | a home with `system_age_years=6` on its battery, scenario SEG 4.1 p and none per home | the baseline outlay equals `bill_distribution(run.projection.age0_summaries, finance).representative.total_outlay_gbp`, and every age-0 fleet the counter saw has battery SOH 1.0 and SEG 4.1 p (RED: the baseline fleet had SOH `None` → 0.88 and no SEG) | ζ |
| B12 | consumer: report | the configured rate named | a scenario at 12 p/kWh | the ranking report's second table names 12.0 p/kWh; no `15p`/`15 p/kWh` literal remains in optimize.py or output.py | ζ |
| B13 | producer: solve value | copies enforced | `CostRecoverySolution(feasible=True, binding="infeasible_above_retail", …)`; one with `representative_outlay_gbp=999.0` against a £66.15 representative | each raises naming both values (RED: both construct); `ConfigResult.feasible is result.solution.feasible` | η |
| B14 | consumer: economics | capex on the generating array | the board fleet's homes; the spreadsheet calibration scenario; an `optimize` 3 kWp point | the physics curve's `fleet_pv_dc_kw` is Σ wired DC (420.449 kWp at c06d12b, re-measured after 812) and the PV capex term is that × `pv_cost_per_kwp_gbp` (RED: 430.0); the spreadsheet column's capex is still £775,000; the 3 kWp point's PV capex is 2.803 × the cost | θ |
| B15 | surface (held) | the frozen solve's module | after ι | `solar_challenge.solve_cost_recovery_rate.__module__ == "solar_challenge.projection"`; finance.py has no package import inside a function; the surface tests pin the form | ι |
| B16 | surface (held) | the outlay field's name | after κ | `BillDistribution(per_home_total_outlay_gbp=…)` constructs; the old keyword raises `TypeError`; `FROZEN_SURFACE` names the new field | κ |

ζ is the integration gate. Its signal is B10–B12, and every row B1–B12 passes at its base.

## 10. Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`, priority equal to its highest key severity, and file-level `metadata.files`. β, γ and ε are high, so each joins trigger-chain gate 772 as a dependency. Each weakened key's measurement (§2.2) is recorded on its leaf.

**α — finance.py's prose says what the code does; history and reviewer answers leave it** (leaf; medium; keys fk-6cd8a932665c, fk-3f4daea21220)

- **Modules:** `src/solar_challenge/finance.py`; `docs/cost-recovery-finance-model.md` (the rehomed rationale; §5's exactness statement).
- **Work:** Replace each CR/W/H/T/step/task-number codename and Greek task letter with a pointer to the model doc's section, or delete it. Delete the "Suggestion 3 / robustness note" and "Suggestion 4 / performance" paragraphs: the precondition's substance goes to §5, and the cost note goes with ζ. Replace the stale `cli/finance.py:162-169` pointer with a symbol. Rewrite the module docstring as a purpose sentence plus a "Provides" list of every public name, with no "no side-effects" claim. State the solve's exactness as it holds at α's base, in the docstring and §5: affine by the reconstruction, exact at the nodes and when income nodes are proportional to own-use nodes. `BillDistribution`'s representative, min, mean, median and max docstrings say total outlay, and the §12-Q4 pointer becomes "renamed at the program's surface bump". No code change. Re-measure prose share, codename hits and lines, and record them on the task with the h14 reading (still above the alarm after rehoming).
- **Signal (user-observable):** `pydoc solar_challenge.finance`'s "Provides" list names all 14 public classes and functions of the module (today 7; the finding's "13" was miscounted) and no side-effect claim. `help(solar_challenge.BillDistribution)` says total outlay in every field. The codename grep over finance.py finds nothing (today 40 hits). The model doc's §5 no longer claims PCHIP is linear.
- **Consumer:** every later leaf here (less prose to move); readers of `pydoc` and of the model doc.
- **Prereqs:** 702. **Supersedes:** 581.

**β — How a run was priced travels as data; finance stops inferring it** (leaf; high; keys fk-52fa98174363, fk-50cf1dd5df58)

- **Modules:** `src/solar_challenge/home.py` (`RunPricing`; `SimulationResults.pricing`; `simulate_home` sets it; `SummaryStatistics.pricing`; `calculate_summary` copies it); `src/solar_challenge/finance.py` (import cost and SEG income read the fact; the refusal; deletes `_physics_import_cost_gbp`'s inference, `householder_bill`'s retail-fallback ratio and `_seg_export_income_gbp`'s ratio and zero fallback; the projection stops passing `seg_tariff_pence_per_kwh` to `calculate_summary`); `tests/_finance_builders.py`; `tests/unit/test_home.py`; `tests/integration/test_finance_bill.py`; `tests/unit/test_finance_projection_revenue.py` (the £0-SEG pin flips); `tests/unit/test_web_storage_roundtrip.py`; `tests/unit/test_public_api_surface.py` (`SimulationResults` member, `SummaryStatistics` form, `RunPricing` in the closure); `docs/cost-recovery-finance-model.md` (§3 retail fallback on the fact; §4 override SEG at the home's rate); `docs/domain-library-consumption.md` (Unreleased lines, §5.8).
- **Work:** §5.1 and the pricing rows of §5.2, on today's helpers; γ then folds them into the ledger.
- **Signal (user-observable):** B1–B3. `finance run` on a scenario whose homes carry a £0 flat tariff reports £0.00 import cost and prints no "no tariff configured" warning. Today it reports retail-priced import and the warning. The override SEG fixture earns £49.20 (today £0.00).
- **Consumer:** `finance run`, `optimize configs` and the projection (through finance); γ; task 667's chart note.
- **Prereqs:** α; S10's 782. **Supersedes:** 690, 715.

**γ — One ledger per home, read by the bill and the projection; the lower interface is public** (leaf; high; keys fk-caeaf35c8151, fk-c2c9277c1920, fk-9cc706d3afdd)

- **Modules:** `src/solar_challenge/finance.py`: §5.2. `householder_bill` and `_simulate_age` read `home_ledger`; YearPoint export and import come from the ledgers; `annuity_payment`, `npv` and `irr` become public. It deletes `_BilledEnergy`, `_billed_energy`, the second `_override_energy_split` caller, `_seg_export_income_gbp`, `_physics_import_cost_gbp`, `_cbs_own_use_kwh` and `_AnnualisedPhysics`/`_annualise_physics`. Tests: `tests/integration/test_cost_recovery_calibration.py`, `tests/integration/test_finance_bill.py`, `tests/unit/test_finance_projection_revenue.py`, `tests/integration/test_finance_economics.py` are repointed at public names, and the oracle uses of `_cbs_own_use_kwh` become demand − import written out. A new `tests/unit/test_finance_ledger.py` covers B4. `docs/cost-recovery-finance-model.md` (§3 and §4: one ledger and its balances); `docs/domain-library-consumption.md`.
- **Signal (user-observable):** B4, B5, and B6's finance half. Through the library a consumer reaches a home's billed year as `home_ledger(annualise(summary), finance)`. Under the spreadsheet assumption the projection's fleet export is the export its SEG revenue is priced on (today the physics export). No test imports a finance private.
- **Consumer:** `householder_bill`/`bill_distribution` (the bill tables of `finance run`), the projection (its revenue), δ, S25 (`HomeLedger.basis` per mode).
- **Prereqs:** β; S9's 801.

**δ — projection.py: the projection, economics and solve move above finance** (leaf; medium; keys fk-b0f648b0e6d0, fk-41283f42a36a, fk-5fdb04305288, fk-9cc706d3afdd)

- **Modules:** new `src/solar_challenge/projection.py`; `src/solar_challenge/finance.py` (upper stratum removed; frozen solve wrapper); `src/solar_challenge/optimize.py` (`scenario_fleet` replaces `_resolve_homes` and its time-axis copy; imports); `src/solar_challenge/cli/finance.py`, `src/solar_challenge/output.py` (imports); `tests/unit/test_import_structure.py`; the 17 test modules importing upper names (`test_cost_recovery_calibration`, `test_cost_recovery_cli`, `test_finance_calibration`, `test_finance_economics`, `test_flex_grid_services`, `test_grid_services_events`, `test_optimize_cli`, `test_optimize_sweep`, `test_cost_recovery_solve`, `test_finance_multi_year_curve`, `test_finance_projection`, `test_finance_projection_adaptive`, `test_finance_projection_ageing`, `test_finance_projection_revenue`, `test_finance_projection_scenario_seg`, `test_finance_projection_short_window`, `test_optimize_rank`); `docs/cost-recovery-finance-model.md` (`Source:` pointers); `docs/domain-library-consumption.md`; `CLAUDE.md` (Finance & Community Layer); `review/briefing.yaml` (the finance-economics area names projection.py, if member lists exist at δ's base).
- **Work:** §5.3's δ part, behaviour-preserving. Move the upper stratum with `ScenarioFleet` and `scenario_fleet`. Use them in `project_multi_year`, the solve and `optimize`. `project_economics` takes the fleet. Make the top-level imports. Add the wrapper and its Transitional entry. Carry `grid_services_model_of` (until 804) and the form of `simulate` found at the base.
- **Signal (user-observable):** B7, and B6's optimize half. finance.py has no package import inside a function but the wrapper's (today 9), `import solar_challenge.finance` stays free of pvlib and `fleet`, and a fake-simulator `finance run --project --cost-recovery` report is byte-identical before and after.
- **Consumer:** ε, ζ, θ, ι; `finance run`, `optimize configs`; S6 (`scenario_fleet`).
- **Prereqs:** γ; S9's 801 and 802; S10's 782; S1's 775. **Supersedes:** 350.

**ε — The projection as a node function, one metric tuple and a pure assembler; revenue affine by construction** (leaf; high; keys fk-c0e0ae3dcca8, fk-5b34adae950b)

- **Modules:** `src/solar_challenge/projection.py` (§5.4; `FleetProjection`, `project_fleet`; `project_multi_year` delegates; the solve's docstring states exactness); tests: `tests/unit/test_finance_projection*.py`, `tests/unit/test_finance_multi_year_curve.py`, `tests/unit/test_cost_recovery_solve.py`; `docs/cost-recovery-finance-model.md` (§4 per-year revenue; §5 the solve exact and independent of r₀; header Unreleased line).
- **Work:** §5.4. Record on the task the board projection's node count, `interp_error_estimate` and largest per-year revenue change before and after, with complexipy's per-function maximum and module total read as a pair (a measurement, not the signal).
- **Signal (user-observable):** B8 and B9. Through the public projection API that `finance run --project --cost-recovery` and `optimize configs` consume, re-projecting at the solved rate meets the floor and the solved rate no longer moves with the configured rate.
- **Consumer:** the solve (ζ), `finance run`, `optimize configs`, θ.
- **Prereqs:** δ. **Supersedes:** 730, 720, 721.

**ζ — One projection per run serves the solve, the economics and the age-0 outlays** (leaf, integration gate; medium; keys fk-4a9af7c31a4f, fk-3b0a239d0489)

- **Modules:** `src/solar_challenge/projection.py` (`CostRecoveryRun`, `run_cost_recovery`; the solve through it); `src/solar_challenge/optimize.py` (`_evaluate_config`; `_age0_baseline_outlay` deleted; `run_sweep`'s docstring; "15 p/kWh" read from the configuration); `src/solar_challenge/cli/finance.py` (one run when both flags are set); `src/solar_challenge/cli/optimize.py` (the large-sweep estimate counts one projection per config); `src/solar_challenge/output.py` (the ranking report's second table header); tests: `tests/integration/test_optimize_sweep.py`, `tests/integration/test_optimize_cli.py`, `tests/integration/test_cost_recovery_cli.py`, `tests/unit/test_cost_recovery_solve.py`, `tests/unit/test_optimize_rank.py`; `docs/cost-recovery-finance-model.md` (§5: no second simulation); `review/briefing.yaml` (the "3-12 fleet sims plus one extra age-0 fleet sim" decision line).
- **Work:** §5.5 and §6 decision 7.
- **Signal (user-observable):** B10–B12, and every row B1–B12 passes at its base. `optimize configs` on a two-config grid asks its simulator 5 times per config (today 12). `finance run --project --cost-recovery` asks 6 times (today 12). An aged-battery scenario's baseline and solved outlays come from one age-0 fleet. The ranking report names the configured rate.
- **Consumer:** `optimize configs` and `finance run` users; S25's per-mode restructure.
- **Prereqs:** ε; S10's 783; task 738. **Supersedes:** 582.

**η — CostRecoverySolution refuses copies that disagree with their source** (leaf; medium; key fk-808be5588896)

- **Modules:** `src/solar_challenge/finance.py` (`CostRecoverySolution.__post_init__`); `src/solar_challenge/optimize.py` (`ConfigResult`'s five copies become properties); `tests/unit/test_cost_recovery_solve.py`, `tests/unit/test_optimize_rank.py` and every test constructing `ConfigResult`; `docs/domain-library-consumption.md`.
- **Work:** §5.6.
- **Signal (user-observable):** B13. A library consumer constructing an inconsistent solution gets a `ValueError` naming both values; today it constructs. `optimize configs` output is unchanged.
- **Consumer:** library consumers of `CostRecoverySolution` (the platform's seam test reads it); `optimize`'s ranking and Pareto split.
- **Prereqs:** ζ.

**θ — Capex prices the PV DC the curve's generation came from** (leaf; medium; key fk-8b8f9d686b86, its finance half; resolves L12 Q6)

- **Modules:** `src/solar_challenge/projection.py` (`MultiYearCurve.fleet_pv_dc_kw`; `project_fleet` sums `pv.wired_dc_capacity_kw`; `spreadsheet_revenue_curve` fills `n_homes × pv_kwp`; `project_economics` prices the PV term on it; `ProjectEconomics.total_capex_gbp` docstring); tests: `tests/integration/test_finance_calibration.py` (the physics column's capex follows; the spreadsheet gate unchanged), `tests/integration/test_finance_economics.py`, `tests/unit/test_finance_multi_year_curve.py`, `tests/integration/test_optimize_sweep.py`; `docs/cost-recovery-finance-model.md` (§6's 4-term build-up and the Summary capex row; header Unreleased line).
- **Work:** §6 decision 9. Record on the task the board fleet's wired and nameplate kWp, and its capex, debt, minimum DSCR, payback and solved rate, before and after, at the leaf's base.
- **Signal (user-observable):** B14. `finance run --project` on `scenarios/bristol-phase1.yaml` reports capex priced on 420.449 kWp of PV (today 430.0). The calibration gate's £775,000 still holds. `optimize configs --pv 3,…` prices its 3 kWp config at 2.803 kWp.
- **Consumer:** board readers of `finance run --project` and `--cost-recovery`; `optimize configs` ranking.
- **Prereqs:** ε; S14's 812.

**ι — solve_cost_recovery_rate is defined in projection** (held leaf; medium; key fk-5fdb04305288; `metadata.x_seam_wait = {stream: "S29", contract: "surface bump release window"}`; excluded from this batch's `commit_planning`)

- **Modules:** `src/solar_challenge/__init__.py` (`_SYMBOL_MODULE` and the `TYPE_CHECKING` import); `src/solar_challenge/finance.py` (the wrapper goes); `tests/unit/test_import_structure.py` (its entry goes); `tests/unit/test_public_api_surface.py` and `tests/unit/test_init_lazy_surface.py` if they pin the module; the tests importing the solve from finance; `docs/domain-library-consumption.md` (release text; the lazy-import list).
- **Signal (user-observable):** B15.
- **Consumer:** S29's release section; the platform re-pin (it imports the name from `solar_challenge`, unchanged).
- **Prereqs:** δ, ζ; S29 releases it. Coordinate with S16's 892, which changes the same frozen form at the bump.

**κ — BillDistribution.per_home_total_outlay_gbp** (held leaf; medium; key fk-3f4daea21220; held as ι)

- **Modules:** `src/solar_challenge/finance.py`; `tests/_factories.py`, `tests/integration/test_cost_recovery_cli.py`, `tests/integration/test_optimize_cli.py`, `tests/integration/test_finance_bill.py`, `tests/unit/test_public_api_surface.py`; `docs/domain-library-consumption.md`; `review/briefing.yaml` (finance-economics `known_gaps[1]` closes).
- **Signal (user-observable):** B16.
- **Consumer:** S29's release section; library consumers of `BillDistribution`.
- **Prereqs:** α; S10's 784; S29 releases it.

**DAG.** 702 → α → β → γ → δ → ε → ζ → η; ε → θ; δ, ζ → ι (held); α → κ (held). Out of batch: β→782; γ→801; δ→801, 802, 782, 775; ζ→783, 738; θ→812; κ→784; and gate 772 → β, γ, ε.

**G7** is advisory: this repo has no `docs/legibility/design-invariants.md`. Screened against dark-factory's trigger shapes:

- `no-silent-fail-soft`: β removes two inferred fallbacks and refuses unknown pricing; ε removes a deviation scale that could not see a zero.
- `one-fact-one-home`: a run's pricing is written once (C1); a home's SEG rate stays `HomeConfig.seg_tariff`; the solve's copies are enforced (η), and optimize's become properties.
- `exceptions-owned-or-ratified`: δ's Transitional allow-list entry is owned by ι and bounded by S29.
- `holds-owned-and-bounded`: finance's solve wrapper has the same owner and bound.
- `guards-exercise-behaviour`: each grep check has a behaviour twin in §9.

No hit.

## 11. Out of scope

- **The scenario-reading consolidation** (S6): `ScenarioConfig.homes()`/`with_seg()`, the CLI's SEG threading, `cli/validate._scenario_homes`, task 485.
- **Per-mode report sections** (S25), and `calculate_summary`'s SEG revenue pair (S25 reduces it; finance stops reading it in β).
- **The runner and the bill run's age-0 reuse** (S16: 885, 890, 892); the sensitivity panel's re-projection per floor value (`sensitivity_panel`, task 718).
- **The basis-C clamp's warning text** ("likely a dispatch/accounting bug"), which a grid-charging winter window can reach legitimately. It is unchanged here, and a follow-up candidate.
- **The simulator's whole-module rounding** (S14). θ follows whatever the simulator wires.
- **Turning `CostRecoverySolution.binding` into an enum and its copies into properties** (§12 Q3).
- **The model doc's own codenames** (H2, θ, W1, [FEAS]). fk-6cd8a932665c is about finance.py, and α edits only the sections its prose points into.
- **optimize.py's and output.py's planning labels** (tasks 764, 765).

## 12. Open questions

**For the lead** (S8's design holds either way):

1. **Supersessions at decompose.** Cancel with `x_superseded_by` after §8 step 1: 350 → δ, 581 → α, 582 → ζ, 690 → β, 715 → β (its key fk-50cf1dd5df58 moves to β), 720 → ε, 721 → ε, 730 → ε. Re-scope 667 to read `SimulationResults.pricing` and depend on β. All eight were pending on 2026-10-17. Re-read each target's status, claimant and heartbeat right before cancelling it. A target that has gone in progress is not cancelled: the superseding leaf takes a dependency edge on it instead, and that edge is reported back as a cross-reference line. **Default:** all as listed.
2. **ι's reading of D29.** The brief reads repointing `_SYMBOL_MODULE` as held. The frozen contract is `solar_challenge.solve_cost_recovery_rate`, whose form does not change, and the platform imports nothing from `solar_challenge.finance`. If the lead reads the repoint as no retirement, ι's work folds into δ, and the transitional wrapper and its allow-list entry never exist. **Default:** held, as the brief rules.
3. **`CostRecoverySolution`'s clean form at the bump.** Under D4 "streams take their clean option": `binding` as a str-valued enum, and `feasible` plus the three representative copies as properties. That is a frozen-form break, and η's enforcement already removes the risk. **Default:** not filed.
4. **Board figures that move**, for the board to hear:
   - θ: physics capex on `bristol-phase1.yaml` falls by the 9.551 kWp the simulator never wires: 2.22% of PV capex, £9,551 at £1,000/kWp, with the solved rate and payback following.
   - ε: per-year revenue between projection nodes moves by up to the £41–150 a year the finding measured, and the solved rate by at most 0.01 p/kWh.
   - ζ: `optimize`'s baseline outlay changes for scenarios with configured battery ages.
   - β: a £0 tariff, or an override home with no simulated export, now bills as configured.

   θ's leaf records the exact figures at its base.

**Tactical** (decide in the leaf):

1. β: whether the tariff's time-weighted mean rate is computed in `simulate_home` from the `tariff_rate` series or by a `TariffConfig` method. The contract fixes the value, not the site.
2. γ: whether `householder_bill` builds the ledger with the caller's figure × scale, or `home_ledger` takes a window figure. The contract fixes the annual own-use on the ledger.
3. ε: whether trial nodes and accepted nodes share one map with an accepted set, or two maps of one lifetime. Nothing outlives the call either way.
4. ζ: whether `CostRecoveryRun` also carries the solved-rate economics (today the solve computes it once inside `surplus_at`).
5. θ: whether `fleet_pv_dc_kw` is checked against the homes' count. The fleet total cannot be, and the per-home tuple was rejected as more than the linear term needs.

## 13. Proposed cross-reference lines (for the lead to apply)

- **S1:** "S8 δ deletes `finance → battery`, `fleet`, `home`, `pv` from 775's allow-list and adds `finance → projection` (Transitional, owner S8 ι). ι deletes it at the bump."
- **S6:** "`projection.scenario_fleet` (S8 δ) is the one place a scenario's homes are resolved and its SEG filled. S6's `ScenarioConfig.homes()`/`with_seg()` replace `_resolve_homes` and `_reconcile_seg_homes` there and delete them from projection.py (not finance.py). optimize imports neither after S8 δ. S6's homes leaf depends on δ."
- **S9:** "804 deletes `grid_services_model_of` and repoints its reader in projection.py if S8 δ has landed. S8 ε's node keeps the per-age `annual_income_gbp` call, booked in the rate-independent income term."
- **S10:** "784 and S8 κ both edit `BillDistribution`'s frozen form; κ depends on 784. 782's own-use bound on `householder_bill` becomes S8's ledger invariant L2 (γ)."
- **S16:** "885 edits `project_multi_year` in projection.py if S8 δ has landed. 892 and S8 ι change `solve_cost_recovery_rate` in the same bump window; ι follows 892. After S8 ζ, `finance run --project --cost-recovery` requests the age-0 fleet twice (the bill run and the projection), and 890's reuse answers both with one simulation."
- **S19:** "The stored-run format covers `SummaryStatistics.pricing` (S8 β: `RunPricing`, two floats or `None`). A summary stored before β loads with `pricing=None`; the web never bills it, and finance refuses it."
- **S25:** "The `cli/finance.run` restructure drives each `--assumptions` mode through `projection.run_cost_recovery` (S8 ζ): one projection, economics and solve per mode, so no section mixes modes (D24). Each home's `HomeLedger.basis` names the mode. Finance no longer reads `total_export_revenue_gbp` or `seg_revenue_gbp` (S8 β), so the pair reduces freely. S25's restructure depends on S8 ζ."
- **S28:** "865 rewrites the docstrings of `_throughput_at`, `_aged_homes` and `per_home_throughput`; S8 δ moves them to projection.py. Whichever lands second carries the text."
- **S14:** "L12 Q6 resolved by S8 θ: capex prices the PV DC the projection simulates (Σ `pv.wired_dc_capacity_kw`); the spreadsheet column keeps its nameplate. θ depends on 812."
- **S29:** "The release section includes S8 §5.8: ι (the solve's module; finance's wrapper retired; the name now loads pvlib) and κ (the field rename) as held leaves, plus the Unreleased lines of β, γ, δ, η and θ."
- **Tasks:** "350, 581, 582, 690, 715, 720, 721 and 730 are superseded at S8's decompose; 667 reads `SimulationResults.pricing` from S8 β and depends on it; 702 lands before S8 α."

## Gate record

- **G1:** every mechanism has a named consumer.
  - `RunPricing` and the pricing fields: finance's ledger (`finance run`, `optimize configs`, the projection) and task 667's chart.
  - The ledger and the lower interface: `householder_bill`/`bill_distribution`, the projection node, S25.
  - The cash-flow maths: `project_economics`.
  - `projection.py`, `ScenarioFleet`/`scenario_fleet`: `finance run`, `optimize configs`, S6.
  - `FleetProjection`, `project_fleet`: `run_cost_recovery`, `project_multi_year`.
  - `CostRecoveryRun`/`run_cost_recovery`: `optimize._evaluate_config`, `cli/finance.run`, S25.
  - `fleet_pv_dc_kw`: `project_economics`.
  - η's refusals: library constructors and `ConfigResult`.

  No orphan producer.
- **G2:** every leaf names a user-observable signal (§10): library behaviour through public names, CLI output, simulation counts through the public CLI or `optimize`, or `pydoc` text for α. ζ is the integration gate over §9. ι and κ are held leaves whose signal is the surface test's pinned form.
- **G3:** the substrate exists at c06d12b (§7). Every other capability is produced upstream in the DAG (702, 775, 782, 783, 801, 802, 812, 738) or by an earlier leaf here.
- **G4:** each seam has one owner (§8). There are no reciprocal claims: S16 hands the duplicated projection here explicitly, S9 names S8 for the move, S10 names S8 for the balance check, and S28 says whichever lands second. The S6, S19, S25 and 667 lines are proposed to the lead (§13).
- **G5:** B + H. The blast radius is 8 modules; the work has 11 mechanisms and touches frozen-surface seams (`SummaryStatistics`, `SimulationResults`, `CostRecoverySolution`, `BillDistribution`, `_SYMBOL_MODULE`); S6, S9, S16, S25 and S29 consume it.
- **G6:**
  - B3's £49.20 is 1,200 kWh × 4.1 p. 1,200 is 4,000 − min(0.7 × 4,000, 3,400) = 4,000 − 2,800.
  - B5's equalities hold by construction: one function produces both ledgers. The SEG rate equality is Σ(eᵢ × r)/Σeᵢ = r, for the one scenario rate D10 fills.
  - β's "physics figures unchanged": simulate_home prices each minute's export at the flat SEG rate, so export × rate equals the summed revenue to float precision.
  - B8's exactness is the identity of §5.4. Node selection reads own-use, export, import and income, none of which depends on the rate. `project_economics` is affine in per-year revenue, and 702 removes the only clamp. The tolerance is far above float error.
  - B10's counts were probed at c06d12b with a counting constant simulate: projection 5 (seeds 0, 12, 24 and trials 6, 18), solve 6, `_evaluate_config` 12.
  - B11's RED values are the finding's capturing-simulate measurement (soh `None` → 0.88 calendar SOH, `seg_tariff` `None`).
  - B14's 420.449 kWp, and the 2.803 and 5.606 kWp sizes, were probed with `pv.wired_dc_capacity_kw` over the board fleet at c06d12b. The £775,000 gate's homes are nameplate 5.5 kWp, and the spreadsheet curve carries 550 kWp.
  - The rejection mechanisms (B2's pricing refusal, B4, B13) are new code, each RED today: the finding constructed the inconsistent solution, and today's ledger has no checks.
  - Field population: `RunPricing` is written by `simulate_home` on every run, and `fleet_pv_dc_kw` by both curve producers. Neither is left at a sentinel on a production path.
- **G7:** advisory (§10). No hit.
- **META:** decomposed without further oversight, this yields three things. finance.py becomes bill arithmetic with one checked ledger and pricing read as data. projection.py becomes one deep module that resolves a scenario once, projects it through a factored and exact engine, and hands every caller the run it already paid for. The surface changes come in one bump. The lead questions are supersessions, a D29 reading, an optional clean-form leaf and board communication; none changes the design.
