# Capability manifest — Cost-recovery householder billing (W2 amendment)

Mechanizes G3 (substrate exists) + G6 (premise valid) per leaf. Each asserted
capability binds to evidence: `grep:file:line wired` (present substrate),
`producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` / reported-tolerance (numeric claim with its basis). PRD:
`docs/prds/cost-recovery-householder-billing.md`. Verified against `main` at
decompose 2026-06-17.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent` (unresolved), or `bound≤floor`. All assumed W2-base substrate
(`FinanceConfig`, `_parse_finance_config`, `project_multi_year._simulate_age`,
`project_economics`, `MultiYearCurve`/`YearPoint` energy quantities,
`householder_bill`/`BillBreakdown`/`bill_distribution`, the finance CLI +
`generate_finance_report`, the θ hard gate, per-timestep `grid_charge_stored_kwh`)
is present on `main` and grep-bound below. Novel substrate (3 `FinanceConfig`
fields, the redefined `BillBreakdown`, `CostRecoverySolution`,
`solve_cost_recovery_rate`, the fixed `project_multi_year` revenue line, the
`cbs_grid_charge_cost` aggregate, the `--cost-recovery` surface, the model doc,
the adversarial gate) is each produced by a named in-batch task with wired edges
(CR2/CR3→CR1; CR4→CR2,CR3; CR5→CR4; CR6→CR4,CR5; CR7→CR1..CR6). The flex seam
(`grid_services_income_per_kw_per_year_gbp`) is **W2-owned and produced by CR1
in this batch**; W1-δ depends on CR1 cross-batch (see the W1 manifest). The one
reported-tolerance numeric (the £27/£324 no-flex anchor) is **reported, not
hard-pinned**, and the brief's internally-inconsistent "15p + Central flex → £27"
premise is corrected to the **no-flex** (grid_services=0 ∧ flat-rate) framing
(G6 §13). θ hard assertions stay green throughout (fix isolated from the
`spreadsheet_revenue_curve → project_economics` path).

## CR1 — `FinanceConfig` cost-recovery fields + parser — intermediate (unlocks CR2, CR3, CR4)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `FinanceConfig` frozen + appended-default fields + `__post_init__` validation | grep:`config.py:478` (class), `config.py:505` (existing fields), `config.py:520` (`__post_init__`) wired | ✅ |
| `_parse_finance_config` parses the `finance:` block (extend for 3 keys) | grep:`config.py:1604` wired | ✅ |
| The 3 new fields (`own_use_rate_pence_per_kwh=15.0`, `retained_cash_floor_per_home_per_year_gbp=27.0`, `grid_services_income_per_kw_per_year_gbp=0.0`) | own-task deliverable; appended-default keeps existing YAML round-trips | ✅ |
| Signal = 3 keys round-trip; negative ⇒ `ConfigurationError`; omission ⇒ defaults; existing finance YAMLs unchanged | unit test on `_parse_finance_config` + `__post_init__` (own task) — observable via the product's parse/validate path | ✅ |

## CR2 — CBS-revenue fix in `project_multi_year` — intermediate (unlocks CR4)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `_simulate_age` computes `fleet_sc` / per-home `bills` (the revenue line to replace) | grep:`finance.py:840` (`_simulate_age`), `finance.py:875-876` (current `Σ self_consumption_saving + seg` line) wired | ✅ |
| The 3 `FinanceConfig` fields the new revenue line reads | **producer:task-CR1** — dep CR2→CR1 wired | ✅ |
| Per-home `battery_config.max_discharge_kw` for `grid_services = Σ kW × £/kW` | grep:`config.py:2160` (resolved homes) wired | ✅ |
| Per-timestep `grid_charge_stored_kwh` to aggregate into `cbs_grid_charge_cost` | grep:`flow.py:262,272,286` (`simulate_timestep_tou`) + `flow.py:351,376,389` (`simulate_timestep`) wired; **the fleet aggregate is novel — produced in CR2** | ✅ |
| `YearPoint.fleet_revenue_gbp` is the field redefined (docstring → "CBS revenue") | grep:`finance.py:339` wired | ✅ |
| Numeric/invariant: flat-rate fleet ⇒ `cbs_grid_charge_cost == 0`; θ hard assertions green | the off-peak grid-charge term is **0 with no arbitrage** (no grid-charging on a flat-rate fleet); θ path (`spreadsheet_revenue_curve → project_economics`) untouched by `project_multi_year` (grep:`test_finance_calibration.py:44` `775000.0`, lines 397–591) | ✅ |
| Signal = injected-fleet `fleet_revenue_gbp == own_use×self + seg + grid_services − cbs_grid_charge_cost`; H9 no-double-count; H7 θ green | unit/integration test (own task) | ✅ |

## CR3 — `householder_bill` → cost-recovery outlay — intermediate (unlocks CR4)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `householder_bill` annualisation + physics/override switch (extend to outlay) | grep:`finance.py:139` (fn), `finance.py:170-249` (switch body) wired | ✅ |
| `BillBreakdown` frozen dataclass (redefined to the cost-recovery outlay) | grep:`finance.py:39` wired (field roles redefined: add `own_use_payment_gbp`/`total_outlay_gbp`, drop SEG credit) | ✅ |
| `bill_distribution` maps `householder_bill`, selects representative | grep:`finance.py:636,671` wired (re-key on median `total_outlay`) | ✅ |
| The 3 `FinanceConfig` fields (own-use rate, VAT) | **producer:task-CR1** — dep CR3→CR1 wired | ✅ |
| Numeric: `saving_vs_baseline = self_consumed × (retail − own_use) × (1+vat)` | **closed-form identity** (import + standing terms cancel against the baseline; only the self-consumed kWh re-priced retail→own-use remains) — G6 §13; `r==retail ⇒ saving==0` | ✅ |
| Signal = bill shows `total_outlay = (import+standing+own_use)×(1+vat)`, no SEG; own-use ↑ ⇒ outlay ↑ / saving ↓ | integration test (own task, recalibrated) | ✅ |

## CR4 — Cost-recovery solve (`solve_cost_recovery_rate`) — leaf · prereqs CR2, CR3

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `CostRecoverySolution` + `solve_cost_recovery_rate` (novel) | own-task deliverable | ✅ |
| `project_economics` consumes `curve.points[y].fleet_revenue_gbp` (read-only; unaffected by curve-build change) | grep:`finance.py:1262` wired; its arithmetic tests feed synthetic curves (`test_finance_economics.py:27-36`) | ✅ |
| `MultiYearCurve.points[y]` energy quantities for the analytic (no-re-sim) solve | grep:`finance.py:330` (`fleet_self_consumption_kwh`), `:333` (`fleet_export_kwh`), `:336` (`fleet_import_kwh`) wired | ✅ |
| `net_surplus_per_home_per_year_gbp` (the solve target field) | grep:`finance.py:480` (field), `finance.py:1291` (computed in `project_economics`) wired | ✅ |
| CBS revenue (CR2) + outlay (CR3) feed the solve | **producer:tasks CR2, CR3** — deps CR4→CR2, CR4→CR3 wired | ✅ |
| Numeric: `surplus(r*) == floor` exactly; clamp `[0, retail]`; `binding` flags | **by construction** — surplus linear in own-use rate (closed-form, G6 §13 H1); the clamp + `binding` rejection mechanism is authored in CR4 (branch-4 backed, H4) | ✅ |
| Numeric: higher-capex ⇒ higher solved rate + higher `representative_outlay_gbp` | structural/monotone by the solve algebra (H2; more capex ⇒ more debt service ⇒ larger negative offset ⇒ larger `r*`) | ✅ |
| Signal = solved rate drives surplus==floor; coupling H2; clamp/infeasible H4; deterministic | unit test on the solve (own task) | ✅ |

## CR5 — `finance run --cost-recovery` CLI + report block — leaf · prereq CR4

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| finance CLI `run` + `--project/--no-project` flag pattern (extend with `--cost-recovery`) | grep:`cli/finance.py:48` (`run`), `cli/finance.py:79-82` (`--project`) wired | ✅ |
| `generate_finance_report` (extend with a cost-recovery block) | grep:`output.py:666` + `cli/finance.py:32` (import) + `:184,191,199` (call sites) wired | ✅ |
| `solve_cost_recovery_rate` (the rendered object) | **producer:task-CR4** — dep CR5→CR4 wired | ✅ |
| Signal = `finance run --cost-recovery scenarios/bristol-phase1.yaml` prints the board-readable cost-recovery report | integration test (own task); real-PVGIS variant marked `slow` — **user-observable CLI surface** | ✅ |

## CR6 — [FEAS]/[FIN] reconciliation calibration + human-readable model doc — leaf · prereqs CR4, CR5

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `[FIN]`/`[FEAS]` golden references for the no-flex anchor | `docs/finance-spreadsheet-reconciliation.md` + survey §3 wired | ✅ |
| θ hard gate stays green (re-derived physics column reported, not pinned) | grep:`test_finance_calibration.py:44` (`775000.0`), `:52` (`min_dscr`), `:59` (`equity_irr_floor`); fix never enters `spreadsheet_revenue_curve → project_economics` (grep:`finance.py:1314`) | ✅ |
| The solve + CLI the doc's worked example reproduces against | **producer:tasks CR4, CR5** — deps CR6→CR4, CR6→CR5 wired | ✅ |
| Numeric: no-flex `solve(floor=£27, grid_services=0, flat-rate)` ⇒ rate ≈ 15p, saving ≈ £324 | **REPORTED within documented tolerance, NOT hard-pinned** (assumption-dependent: physics self-consumption ≠ [FEAS] 90%); the brief's "15p + Central flex → £27" is corrected to the **no-flex** framing (grid_services=0 ∧ flat-rate) — false premise avoided (G6 §13 H6). Tolerance set when [FIN]/[FEAS] inputs wired (tactical §12.5) | ✅ |
| Signal = calibration report (no-flex reconciliation reported + H1/H2 structural asserts hard); θ green; doc worked example reproduces a live run | integration test + committed doc (own task) | ✅ |

## CR7 — Adversarial code↔doc verification gate (acceptance, blocking) — leaf · prereqs CR1–CR6

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `finance.py` arithmetic to verify against the doc | **producer:tasks CR2, CR3, CR4** — deps wired | ✅ |
| `docs/cost-recovery-finance-model.md` (the authoritative spec) | **producer:task-CR6** — dep CR7→CR6 wired | ✅ |
| The rendered report + a live run to reproduce the worked example | **producer:task-CR5** — dep CR7→CR5 wired | ✅ |
| Signal = a filed fidelity report stating code ≡ documented model, or an itemised discrepancy list that **blocks** acceptance | review/agent-team deliverable; **reads everything, edits nothing** | ✅ |

> **Decompose note (CR7):** filed as a review/agent-team acceptance task, **not a
> standard TDD leaf** — flagged `task_kind=review_acceptance_gate` +
> `not_implementable_by_tdd_agent=true` in metadata so an implementation agent
> does not claim it. The deliverable (a blocking fidelity report) is fixed; the
> exact form (`/review`-style, multi-agent workflow, or scripted equation check)
> is the implementer's call (§12.6).
