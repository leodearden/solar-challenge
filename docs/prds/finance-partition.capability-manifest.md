# Capability manifest — Finance partition (S8)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/finance-partition.md`. Each asserted capability binds to one kind of evidence:

- a symbol wired on main (`grep:<file>::<symbol>`);
- a producer upstream in this batch or out of it (`producer:<label>` or `producer:task-<id>`);
- a probe whose result was observed (`probe:`);
- an arithmetic identity (`identity:`).

The YAML twin, `finance-partition.capability-manifest.yaml`, carries the mechanical `delivered_check`s.

**Code anchors** verified against main `c06d12b` (2026-10-17). Probes ran with `uv run --locked --extra dev python`; the scripts were scratch files outside the tree. Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-extent-short`, `producer-downstream` or `rejection-absent`. The rejection mechanisms (β's pricing refusal, γ's ledger invariants, η's copies) are new code whose RED cases are observed today as silent acceptance; each is bound to its producing leaf, not asserted of the substrate.

- **External producers upstream:** 702 (α), 782 (β, γ, δ), 801 (γ, δ), 802 (δ; it depends on 837), 775 (δ), 783 and 738 (ζ), 812 (θ), 784 (κ).
- **Held leaves:** ι and κ wait for S29 and are excluded from this batch's `commit_planning`.

---

## α — finance.py's prose says what the code does (leaf)

| capability asserted | evidence | status |
|---|---|---|
| 40 codename hits today (the signal's "today 40") | `probe:` regex over finance.py at c06d12b: CR3 ×8, W1/W1-delta/W2/W3, CR1/CR4, H3/H4/H6, T2, step-8/16, task 64/83/84, 9 Greek letters, Suggestion 3/4 | PASS |
| The "Provides" list names 7 of the 14 public classes and functions, and the docstring claims no side effects | `grep:finance.py::` module docstring (seven bullets; "has no side-effects") | PASS |
| The false exactness claim is in two homes | `grep:finance.py::solve_cost_recovery_rate` ("PCHIP interpolation is a linear operator on node values"); `grep:docs/cost-recovery-finance-model.md::§5` ("PCHIP interpolation and `project_economics` are both linear in per-year revenue") | PASS |
| `BillDistribution`'s five docstrings say net bill | `grep:finance.py::BillDistribution` ("median-net-bill", "net annual bill" ×4, "§12-Q4" ×3) | PASS |
| Behaviour-preserving | no code line changes; the verify suite is the guard | PASS |
| 702 rewrites the YearPoint note first | `producer:task-702` (in progress; branch `task/702` renames `fleet_billed_own_use_kwh` and drops the clamp) | PASS |

## β — pricing travels as data (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `simulate_home` knows the tariff and SEG tariff | `grep:home.py::simulate_home` reads `config.tariff_config` and `config.seg_tariff` (`_price_imports`, `_export_revenue`) | PASS |
| A time-weighted tariff mean is computable | `grep:home.py::SimulationResults.tariff_rate`, set when a tariff is configured, on the run's evenly spaced index | PASS |
| `SimulationResults` and `SummaryStatistics` gain a last defaulted field (additive) | `grep:tests/unit/test_public_api_surface.py::FROZEN_SURFACE/FROZEN_MEMBERS`; precedent S10 α/β (`SimulationResults.window`, task 777) | PASS |
| A stored summary round-trips an Optional nested dataclass of floats | `grep:web/storage.py::_deserialize_value` (a union reads its first non-None member; a dict becomes a dataclass) | PASS |
| £0 tariff billed at retail with a warning today (B2's RED) | `grep:finance.py::_physics_import_cost_gbp` (`import_cost_physics == 0.0 and import_kwh > 0.0`); task 690's probe: £217.99 and the warning | PASS |
| Override SEG £0.00 on zero simulated export today; £49.20 after (B3) | `grep:finance.py::_seg_export_income_gbp` (ratio, 0.0 fallback); `identity:` 4,000 − min(0.7 × 4,000, 3,400) = 1,200 kWh × 4.1 p = £49.20 | PASS |
| Physics-path SEG unchanged by export × rate | `grep:home.py::_export_revenue` prices each minute's `flow.grid_export` kWh at the flat SEG rate; `identity:` Σ(eᵢ·r) = r·Σeᵢ to float precision | PASS |
| The window is on the summary before β | `producer:task-782` (and 778's `SummaryStatistics.window`) | PASS |
| Pricing-less summary refused | rejection mechanism authored in β; B2 observes it fire | PASS (producer β) |

## γ — one ledger per home (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Two assemblies today | `grep:finance.py::householder_bill` and `grep:finance.py::project_multi_year._simulate_age` both call `_annualise_physics` and `_billed_energy`; `_seg_export_income_gbp` re-runs `_override_energy_split` | PASS |
| The tests reach 7 finance privates today | `probe:` AST scan: 5 test modules; `grep -w`: 63 occurrences | PASS |
| L3 holds for every legitimate own-use figure | `identity:` basis C: own-use + import = demand, or import > demand when clamped; B-style sc: sc + import = demand + grid charge; override: equality | PASS |
| L3 refuses the window-against-annual class | `identity:` a 30-day own-use × 1 against annual import × 12.2 gives own-use + import < demand whenever own-use > 0 | PASS |
| One ledger read twice (B5) | `producer:γ`: `home_ledger` is the only producer, called by `householder_bill` and the node | PASS |
| SEG ÷ export = rate under the override (B5) | `identity:` Σ(eᵢ·r)/Σeᵢ = r, for D10's one filled rate | PASS |
| `_simulate_age` already rewritten for per-age income | `producer:task-801` | PASS |

## δ — projection.py above finance (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Lower→upper code references: 0 (the split is legitimate) | `probe:` AST name intersection at c06d12b | PASS |
| The four allow-list entries exist under an S8 owner | `grep:tests/unit/test_import_structure.py::ALLOWED_FUNCTION_LOCAL_IMPORTS` on `task/775` (`_FINANCE_PARTITION`) | PASS (producer task-775) |
| `import solar_challenge.finance` is pvlib-free and keeps it so | `grep:finance.py::` imports: `errors`, `seg`, `whole_numbers` at top; fleet/home only under `TYPE_CHECKING`; S16 I10 probe | PASS |
| No upward import after the move except the wrapper | the moved symbols are exactly those that reference `ScenarioConfig`, `simulate` or each other (`probe:` AST) | PASS |
| The platform imports none of the moved names | `probe:` grep of solar-challenge-platform `45ecca2`: only `from solar_challenge import` of frozen names | PASS |
| `grid_services_model_of` exists to carry | `producer:task-801` | PASS |
| Byte-identical report (B7) | `identity:` the move changes no arithmetic; a deterministic fake gives identical numbers | PASS |

## ε — node function, metric tuple, affine revenue (leaf)

| capability asserted | evidence | status |
|---|---|---|
| PCHIP is not linear, so today's rebuild is inexact (B8's RED) | task 720's probe at e5d7e80 (£38.74 in one year); the finding's (£41–150 a year; r* spread 0.004–0.010 p) | PASS |
| Exactness after ε | `identity:` revenue_y = r·OU_y/100 + C_y with node selection reading no rate; `project_economics` affine in per-year revenue; 702 removes the only clamp | PASS (needs 702: upstream of α) |
| Income ≥ 0 by construction | `identity:` SEG = export × rate ≥ 0 (β, γ); grid services ≥ 0 (S9 §5.1) | PASS |
| Per-age grid-services call exists to keep | `producer:task-801` | PASS |
| `PchipInterpolator` available | `grep:finance.py::_interpolate_per_year` | PASS |

## ζ — one projection per run (leaf, integration gate)

| capability asserted | evidence | status |
|---|---|---|
| `_evaluate_config` makes 12 calls today; 5 after | `probe:` counting constant simulate, asset life 25: projection 5 (ages 0, 12, 24, 6, 18), solve 6, `_evaluate_config` 12 | PASS |
| `finance run --project --cost-recovery` makes 12 today; 6 after | `probe:` `invoke_cli([...])` with the counting simulate: bill run 1, projection 5, solve 6 | PASS |
| The solve's outlay fleet equals the projection's age-0 fleet | `grep:finance.py::solve_cost_recovery_rate` simulates `_aged_homes(homes, 0)`; the projection's age 0 is `_aged_homes(homes, 0, [0.0] * n)`; `_aged_homes` treats `None` as zeros | PASS |
| The baseline outlay's fleet differs today (B11's RED) | `grep:optimize.py::_age0_baseline_outlay` (PV age only; no SEG fill); the finding's capturing probe (SOH `None` → 0.88, `seg_tariff` `None`) | PASS |
| 17 "15p" literals in optimize, output and cli/optimize today | `probe:` git grep count | PASS |
| `cli/finance.run` restructured first | `producer:task-738`, `producer:task-783` | PASS |

## η — CostRecoverySolution refuses inconsistent copies (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Inconsistent construction succeeds today (B13's RED) | `grep:finance.py::CostRecoverySolution.__post_init__` checks only `binding` membership and the rate range; the finding's probe constructed `feasible=True, binding='infeasible_above_retail', representative_outlay_gbp=999.0` | PASS |
| Bare equality is achievable | `identity:` the solve copies the same floats from `outlay.representative` | PASS |
| `ConfigResult` is not frozen surface | `grep:tests/unit/test_public_api_surface.py`: no `ConfigResult` entry | PASS |

## θ — capex on the generating array (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Wired DC is computable per home | `grep:pv.py::wired_dc_capacity_kw` (same `_module_parameters`/`_module_count` as `_pv_system`); `producer:task-812` makes it read the built system | PASS |
| Board fleet 430.0 nameplate, 420.449 wired | `probe:` `load_fleet_config("scenarios/bristol-phase1.yaml")`: 20 × 3.0→2.803, 40 × 4.0→4.004, 30 × 5.0→4.805, 10 × 6.0→6.006 | PASS |
| The spreadsheet gate keeps £775,000 | `identity:` 100 × 5.5 = 550 kWp × £1,000 + 100 × (£1,000 + 5 × £250) = £775,000; `grep:tests/integration/test_finance_calibration.py::test_capex_5kwh_matches_capital_stack_b6` | PASS |
| Pricing wired DC everywhere would break that gate (why the curve carries its basis) | `probe:` `wired_dc_capacity_kw(PVConfig(capacity_kw=5.5))` = 5.606 kWp → +£10,599 | PASS |

## ι — the frozen solve moves module (held)

| capability asserted | evidence | status |
|---|---|---|
| `_SYMBOL_MODULE` maps it to `finance` today | `grep:__init__.py::_SYMBOL_MODULE` | PASS |
| The implementation is in projection.py first | `producer:δ`, `producer:ζ` | PASS |
| S29 releases it | `x_seam_wait`; S29 | held |

## κ — the outlay field's name (held)

| capability asserted | evidence | status |
|---|---|---|
| No src reader outside finance; no platform reader | `probe:` grep: tests and finance.py only; the platform has none | PASS |
| 784 edits the same frozen form first | `producer:task-784` (held) | PASS |
