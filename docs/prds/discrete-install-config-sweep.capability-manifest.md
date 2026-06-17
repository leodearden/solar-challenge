# Capability manifest — W3 discrete install-config sweep (cost-recovery re-spec)

Per-leaf G3+G6 bindings for `docs/prds/discrete-install-config-sweep.md` (re-spec'd 2026-06-17,
commit `bd68671`). Any FAIL blocks queueing. Cross-PRD producers are tasks in the W1+W2
cost-recovery batch (52–63); each `producer:task-N upstream` binding is backed by a wired
`add_dependency` edge (listed). **Verdict: PASS** (no FAIL bindings).

Task-label → ID: **A**=enumerate · **B**=run_sweep · **C**=rank/feasibility logic · **D**=sensitivity · **E**=report+CLI (leaf). Cross-PRD: CR1=57, CR2=58, CR3=59, **CR4=60** (solve), CR5=61; W1 α=52, β=53, γ=54.

## A — `enumerate_configs` + `ConfigPoint` (intermediate; consumer: B, C)
- `dataclasses.replace` on frozen `HomeConfig`/`PVConfig`/`BatteryConfig` → **PASS** `grep:config.py:46+`, `pv.py:18`, `battery.py:82` (frozen) + stdlib.
- resolved per-home configs to replace over (`ScenarioConfig.homes` / `FleetResults.home_configs`) → **PASS** `grep:config.py:576`, `fleet.py:142` wired.
- *(pure W3 code; no cross-PRD producer needed — schedulable early.)*

## B — `run_sweep` + `ConfigResult`/`RankedSweep` (seam integration-gate; consumer: D, E)
- `solve_cost_recovery_rate(scenario, finance, *, simulate) -> CostRecoverySolution` + `.representative_outlay_gbp` / `.feasible` / `.binding` (the **rank key**) → **PASS** `producer:task-60 (CR4) upstream` — extent matches exactly (task 60 delivers the solve + `CostRecoverySolution` + `representative_outlay_gbp`). **dep B→60.**
- redefined `bill_distribution`→`BillBreakdown.total_outlay_gbp` (baseline-15p outlay) → **PASS** `producer:task-59 (CR3) upstream` (via 60→59).
- `project_economics` cost-recovery CBS revenue (baseline-15p surplus) → **PASS** `producer:task-58 (CR2) upstream` (via 60→58).
- `FinanceConfig.{own_use_rate_pence_per_kwh, retained_cash_floor_per_home_per_year_gbp, grid_services_income_per_kw_per_year_gbp}` → **PASS** `producer:task-57 (CR1) upstream`. **dep B→57.**
- fleet **TOU + grid-charging** board dispatch (time-shift in the energy aggregates the solve consumes) → **PASS** `producer:task-53 (β) upstream`. **dep B→53.**
- grid-services £/kW band values (≈1.5/12/48) for the sensitivity axis → **PASS** `producer:task-52 (α) upstream` (`flex.resolve_grid_services_band`). **dep B→52.**
- `simulate_multi_sweep_iter` / `simulate_fleet` executor → **PASS** `grep:fleet.py:444`, `fleet.py:319` wired.

## C — rank / feasibility / Pareto pure logic (intermediate; consumer: E)
- `CostRecoverySolution` type + `binding` enum (to build synthetic records) → **PASS** `producer:task-60 (CR4) upstream`. **dep C→60.**
- pure `rank` / `feasible_split` / `pareto_baseline` / tie-break over the `ConfigResult` shape → **PASS** W3-internal (produced in C; record shape from A). No numeric-floor/exactness premise.

## D — `sensitivity_panel` (intermediate; consumer: E)
- re-run `run_sweep` with `dataclasses.replace`'d `FinanceConfig` knobs → **PASS** `producer:task-B upstream` (intra-batch) → transitively gates on CR1/57 + CR4/60 via B.
- W-H4 directional premise — *raising `battery_cost_per_kwh_gbp` (capex) raises the solved own-use rate → raises outlay → battery configs rank worse; raising `grid_services_income_per_kw_per_year_gbp` lowers the solved rate → battery configs rank better* → **PASS (coupling, not a floor):** guaranteed monotone by the cost-recovery solve (CR4/60 makes outlay monotone in capex; grid-services adds CBS revenue at fixed config). **This is the binding that FAILED under the old decoupled objective** (capex could not move a capex-blind bill); the cost-recovery re-spec resolves it.

## E — `generate_config_ranking_report` + `optimize` CLI (LEAF — the G2 user-observable surface; consumer: Leo + ResNet board)
- `optimize` CLI subcommand via `add_typer` → **PASS** `grep:cli/main.py:25-30` wired (idiom); `generate_config_ranking_report` produced in E.
- renders `RankedSweep` (cost-recovery rank) + `SensitivityPanel` (trade-off + sensitivity) → **PASS** `producer:task-B/D upstream` (intra-batch).
- `output.py` co-tenancy with `generate_finance_report` (file-lock serialise the renderer additions) → **PASS** `producer:task-61 (CR5) upstream`. **dep E→61.**
- board-readable two-table report — **no numeric/exactness/rejection premise** (renders W2's numbers, asserts none; the seam-equality check lives in B/W-H1) → **PASS** (G6 branch-3 traces every capability to upstream producers; no branch-1/2/4 assertion).

## Wired cross-PRD dependency edges (backing the producer-upstream bindings)
`B→60, B→57, B→53, B→52` · `C→60` · `E→61`. Intra-batch: `B→A, C→A, D→B, E→{B,C,D}`. Plus the follow-on trigger `task-51→E` (W3 terminal leaf gates the enhanced-grid-services PRD).
