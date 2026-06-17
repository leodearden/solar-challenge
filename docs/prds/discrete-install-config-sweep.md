# PRD — Discrete install-config optimisation sweep (W3)

- **Source:** 2026-06-15 deployment-readiness survey §6 decision 6 (physics-first install-spec optimisation), §7 (objective function), §8 workstream **W3**. Brief: `/home/leo/.claude/spawn-briefs/solar-w3-config-sweep.md`.
- **Status:** active · authored 2026-06-16 · **re-spec'd 2026-06-17 for the cost-recovery objective** (the original year-1-net-bill + two-axis-Pareto objective was mis-specified against the real CBS business model — see §2.2).
- **Owner seam:** a **new `optimize.py` module** (pure config-grid enumeration + cost-recovery evaluation + ranking + feasibility + fixed-rate Pareto + sensitivity) + a new `solar-challenge optimize configs` CLI subcommand + a ranked-table renderer in `output.py`. **Imports, does not re-implement,** W2's cost-recovery finance functions. No edit to `home.py`/`fleet.py`/`finance.py`/`battery.py`/`pv.py` logic.
- **Approach:** **B + targeted H** (written contract + a two-way boundary test on the W3↔W2 seam). W3 *orchestrates and ranks*; it does not re-derive physics or finance, so the heavy B+H lives in W2 — see §8.
- **Consumes (do not re-touch):** the **W2 cost-recovery amendment** (`docs/prds/cost-recovery-householder-billing.md`) — `finance.solve_cost_recovery_rate(scenario, finance, *, simulate=None) -> CostRecoverySolution` (the **rank** number) plus the redefined `bill_distribution` / `project_multi_year` / `project_economics` / `FinanceConfig` cost-recovery fields (the **fixed-baseline trade-off** pair) — the **declared contract W2 owns**; the **W1** physics (`docs/prds/flexibility-value-finance-integration.md`) — fleet **TOU + grid-charging** (the endogenous time-shift value, reached via the energy aggregates) + the `grid_services_income_per_kw_per_year_gbp` value W2's field carries; plus the existing fleet/sweep executor (`fleet.simulate_multi_sweep_iter` / `simulate_fleet` / `FleetResults.home_configs`), the frozen config dataclasses (`dataclasses.replace`), and `PVConfig.inverter_capacity_kw` (inverter clipping is live in `simulate_pv_output` via the CEC inverter model; inverter capex now priced inside `project_economics`).
- **Produces (G1 consumer named):** a **board-readable ranked table of discrete install configs** that **Leo + the ResNet board** read to pick the Phase-1 install spec: a **cost-recovery rank** (the lowest householder outlay that keeps the CBS solvent at the board's retained-cash floor) + a **fixed-baseline (outlay, surplus) Pareto trade-off** + an **assumption-sensitivity panel**. Also feeds funder reporting and the install BoM decision.

---

## 1. Goal

Rank the **discrete** install configurations realistically on offer — `PV (kWp) × battery (kWh) × inverter (kW AC)` — for the Bristol **Community Benefit Society (CBS)** cost-recovery model, where the CBS owns the assets and bills householders an **own-use rate** for self-consumed solar (W2). The **primary objective** is the **minimum cost-recovery householder total outlay**: for each config, W2 solves the **minimum own-use rate** such that the **CBS retained surplus exactly meets the board's retained-cash floor** (default £27/home/yr), and W3 ranks configs by the resulting **representative householder total outlay**, flagging configs that **cannot clear the floor even at full retail** as infeasible. Alongside, W3 reports the **raw trade-off** — each config's `(householder outlay, CBS surplus)` at the **policy-baseline own-use rate** (15 p/kWh) with a **Pareto flag** — and an **assumption-sensitivity panel**. Estimated prices/assumptions now; re-runnable when installer/aggregator figures arrive.

**Why the objective changed (the "two axes are illusory" insight, §2.2).** Under the old decoupled model, "minimum householder bill" and "project surplus" looked like two independent axes (survey §7: report both, never collapse). Under cost-recovery they are **the same trade-off seen once**: the own-use rate is the single dial between householder outlay and CBS surplus. The cost-recovery rank pins the surplus at the board's chosen floor and reports the outlay; the fixed-baseline Pareto shows the raw trade-off at the current 15p tariff; sweeping the retained-cash floor traces the frontier. The board still sees **both quantities and the trade-off** — honoured more faithfully, not less.

**User-observable outcome:** `solar-challenge optimize configs scenarios/bristol-phase1.yaml` prints a **board-readable markdown report** with two tables — **(1) the cost-recovery rank** (one row per config → **solved own-use rate** + **householder total annual outlay** (representative + min/mean/median/max) + **CBS surplus** (= the retained floor, or the headroom when the rate clamps to 0) + **feasibility/binding** flag + key economics: total capex, min-DSCR, equity-IRR, payback) and **(2) the fixed-15p trade-off** (config → outlay + surplus + Pareto flag) — followed by an **assumption-sensitivity section** (retained-floor, grid-services £/kW, capex, tariff/SEG, self-consumption, degradation). A board member reads it and chooses a config.

## 2. Background

### 2.1 What this consumes (verified in code / committed contracts 2026-06-17)

- **W2's cost-recovery layer is the bill/economics engine.** The committed W2 amendment (`docs/prds/cost-recovery-householder-billing.md` §3.1–3.4) declares, in `finance.py`:
  - `solve_cost_recovery_rate(scenario, finance, *, simulate=None) -> CostRecoverySolution` — the **rank** object. `CostRecoverySolution` carries `own_use_rate_pence_per_kwh` (the SOLVED minimum rate, clamped to `[0, retail]`), `outlay: BillDistribution`, `representative_outlay_gbp` (**W3's primary key**), `net_surplus_per_home_per_year_gbp` (= the retained floor at the solved rate, or > floor when clamped to 0), `saving_vs_baseline_gbp`, `saving_pct`, `feasible: bool`, and `binding: str ∈ {'floor','rate_clamped_zero','infeasible_above_retail'}`.
  - The redefined `householder_bill`/`bill_distribution` → `BillBreakdown.total_outlay_gbp` (`(import_cost + standing + own_use_payment)×(1+vat)`, **no SEG credit**) and `BillDistribution` (`representative` median-outlay home + per-home tuple + min/mean/median/max); and `project_multi_year` → `project_economics` (`net_surplus_per_home_per_year_gbp`, `min_dscr`, `equity_irr`, `payback_years`, `total_capex_gbp`) with **CBS revenue = own-use + SEG + grid-services topper − CBS grid-charge cost**. W3 calls these at the **policy-baseline own-use rate** for the fixed-15p trade-off pair. **W2 owns all these signatures.** W3 does **not** duplicate the math.
- **W1 supplies the flexibility physics + the grid-services value.** W1 (`docs/prds/flexibility-value-finance-integration.md`) threads a fleet **TOU tariff + grid-charging** dispatch (the **endogenous time-shift** value of CBS-operated arbitrage) and fills W2's `grid_services_income_per_kw_per_year_gbp` field (the **exogenous** DFS/DNO topper, per kW of battery discharge power; Low ~1.5 / Central ~12 / High ~48 £/kW). W3 runs configs under the **board dispatch** (W1's TOU + grid-charging) so the time-shift is present in the energy aggregates the cost-recovery solve consumes, and sweeps grid-services £/kW + the dispatch policy as sensitivity axes.
- **The existing sweep executor is reused, not the sweep *spec*.** `fleet.simulate_multi_sweep_iter(...)` flattens many fleet jobs into one `ProcessPoolExecutor` (`fleet.py:444+`); `collect_multi_sweep_results` buckets them (`fleet.py:531+`). The single-param `SweepSpec` does **not** express a cartesian product of explicit discrete sets across three install dimensions — that **enumerator is W3-novel** (§3.2). Per-config evaluation drives `project_multi_year`'s aged-fleet march; cross-config parallelism is available (§12).
- **Inverter clipping is live and inverter capex is priced.** `simulate_pv_output` sizes a CEC inverter to `PVConfig.effective_inverter_capacity_kw` and clips AC at Paco (`pv.py:255-420`); `project_economics` includes the inverter capex term (`eff_inv_kw × inverter_cost_per_kw_gbp`, finance.py:1228-1234, landed). So sweeping inverter AC capacity has both a **physics** effect (clipping) and a **capex** effect (which now moves the solved own-use rate → the rank).

### 2.2 The objective correction (why cost-recovery)

The original W3 objective ranked by **year-1 net householder bill** with a two-column **(bill, surplus) Pareto** and the £27 surplus as a Pareto constraint. Decompose (2026-06-17) found this **mis-specified against the real CBS model**: W2's then-current `householder_bill` priced self-consumed solar as a **free** retail saving and `project_multi_year` credited the **same** retail-valued self-consumption to **both** the householder bill **and** CBS revenue — no own-use transfer price, so the bill was **decoupled from capex** by an accounting artifact, and a bill-ranking biased toward the largest install that cleared the floor. Leo's redesign (the W2 cost-recovery amendment + W1 flexibility physics) fixes this: the own-use rate couples householder outlay to capex. W3 is re-spec'd to rank by the **cost-recovery solved outlay** and to present the trade-off via the hybrid framing above (§1). Full record: `cost-recovery-householder-billing.md`; memory `cost-recovery-objective`.

### 2.3 The gaps this PRD fills

1. **No discrete-cartesian config enumerator.** The sweep machinery ranges one distribution multiplier; W3 needs the cartesian product of explicit discrete sets `PV × battery × inverter`, each → a homogeneous-install fleet.
2. **No cross-config cost-recovery ranking / feasibility / fixed-rate Pareto / sensitivity.** `output.py` has per-run and finance reports only — no ranked-table-across-configs, no per-config cost-recovery solve aggregation, no feasibility/Pareto/sensitivity over configs.

## 3. Sketch of approach

A **new pure module `optimize.py`** (mirroring how `community.py`/`finance.py` are self-contained consumers): it enumerates the discrete config grid, drives each homogeneous-install scenario through the existing executor + W2's cost-recovery functions to produce **both** a `CostRecoverySolution` (the rank) **and** the fixed-baseline `(outlay, surplus)` pair (the trade-off), ranks the feasible set, computes the baseline Pareto front, runs the sensitivity panel, and returns frozen result dataclasses. Rendering lives in `output.py`; the user surface is a new `solar-challenge optimize` CLI subcommand. No simulation/finance logic is reimplemented.

### 3.1 Data model (the contract — B)

```python
# optimize.py — frozen dataclasses, __post_init__ validation

@dataclass(frozen=True)
class ConfigPoint:                       # one discrete install config
    pv_kwp: float
    battery_kwh: float                   # 0.0 == no battery
    inverter_kw: float                   # AC capacity

@dataclass(frozen=True)
class ConfigResult:                      # one config's cost-recovery evaluation
    config: ConfigPoint
    solution: CostRecoverySolution       # W2 — the whole solved object (rank source)
    # --- cost-recovery rank projections (copied from the W2 solution) ---
    representative_outlay_gbp: float     # == solution.representative_outlay_gbp (PRIMARY RANK KEY)
    solved_own_use_rate_pence_per_kwh: float  # == solution.own_use_rate_pence_per_kwh (board headline)
    surplus_at_solved_gbp: float         # == solution.net_surplus_per_home_per_year_gbp (= floor, or > floor if clamped)
    feasible: bool                       # == solution.feasible
    binding: str                         # == solution.binding
    total_capex_gbp: float; min_dscr: float; equity_irr: float; payback_years: float | None
    # --- fixed-baseline (15p own-use) TRADE-OFF pair (the survey-§7 two-objective view) ---
    baseline_outlay_gbp: float           # representative householder total outlay at finance.own_use_rate (15p)
    baseline_surplus_per_home_gbp: float # CBS surplus at 15p — the second trade-off axis

@dataclass(frozen=True)
class RankedSweep:
    results: tuple[ConfigResult, ...]    # FEASIBLE configs, ascending by representative_outlay_gbp (primary rank)
    infeasible: tuple[ConfigPoint, ...]  # binding == 'infeasible_above_retail' (cannot clear the floor at any rate ≤ retail)
    retained_cash_floor_gbp: float       # the board-set floor the solve targeted (default 27.0)
    cheapest_feasible: ConfigPoint | None  # == results[0].config — the recommended config
    pareto_baseline: tuple[ConfigPoint, ...]  # non-dominated on (baseline_outlay ↓, baseline_surplus ↑) at 15p — the trade-off front
    # deterministic tie-break on the rank: (representative_outlay_gbp, -surplus_at_solved, pv_kwp, battery_kwh, inverter_kw)

@dataclass(frozen=True)
class SensitivityAxis:
    name: str                            # a FinanceConfig knob or the dispatch policy, e.g. "retained_cash_floor_per_home_per_year_gbp",
                                         #   "grid_services_income_per_kw_per_year_gbp", "battery_cost_per_kwh_gbp"
    values: tuple[float, ...]
    rankings: tuple[tuple[ConfigPoint, ...], ...]   # cost-recovery rank order (by outlay) under each value
    top_config_per_value: tuple[ConfigPoint, ...]

@dataclass(frozen=True)
class SensitivityPanel:
    axes: tuple[SensitivityAxis, ...]
    baseline_top: ConfigPoint
    rank_stability: float                # fraction of axis-values for which baseline_top stays the #1 (cheapest feasible) config
```

### 3.2 Config-grid enumerator (pure) — `enumerate_configs`

```python
def enumerate_configs(
    base: ScenarioConfig,                # supplies fleet load diversity, location, period, tariff/SEG, finance (incl. cost-recovery knobs + dispatch)
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> list[tuple[ConfigPoint, ScenarioConfig]]: ...
```

- Cartesian product of the three discrete sets. For each combo, build a **homogeneous-install** scenario via `dataclasses.replace` over the base fleet's resolved home configs: every home's `PVConfig.capacity_kw = pv_kwp`, `PVConfig.inverter_capacity_kw = inverter_kw`, `BatteryConfig.capacity_kwh = battery_kwh` (0 ⟹ no battery). **Load / occupancy diversity is preserved** — only the install spec is fixed, so the outlay *distribution* still reflects real household spread. The base's **dispatch strategy (W1 board TOU + grid-charging), tariff/SEG, and `FinanceConfig` cost-recovery knobs** are carried unchanged, so the time-shift value and the cost-recovery solve are consistent across configs. Battery `max_discharge_kw` is held at the base value (battery-power sweep = §12).

### 3.3 Evaluate + rank (the orchestration) — `run_sweep`

```python
def run_sweep(
    configs: list[tuple[ConfigPoint, ScenarioConfig]],
    *, retained_cash_floor_gbp: float | None = None,   # None ⟹ use each scenario's FinanceConfig field
    simulate=None,                                      # injectable fast simulate for tests (threaded to W2)
) -> RankedSweep: ...
```

- For each config, evaluate via W2 (one energy march per config; the cost-recovery solve is **near-closed-form** — surplus is linear in the own-use rate — so the rank and the fixed-baseline pair come from the same simulation):
  - **Rank:** `solve_cost_recovery_rate(scenario, finance, simulate=simulate)` → `CostRecoverySolution`.
  - **Trade-off:** evaluate the config at `finance.own_use_rate_pence_per_kwh` (15p) → `baseline_outlay_gbp` (via `bill_distribution`) and `baseline_surplus_per_home_gbp` (via `project_economics(project_multi_year(...))`). Reuse the solve's energy curve where the W2 API allows (§12); else a second pure post-sim evaluation.
- **Rank** the **feasible** configs ascending by `representative_outlay_gbp`; collect `infeasible` = configs with `binding == 'infeasible_above_retail'`; `cheapest_feasible = results[0].config`. Deterministic tie-break `(representative_outlay_gbp, -surplus_at_solved, pv_kwp, battery_kwh, inverter_kw)`. Compute `pareto_baseline` = the non-dominated set on `(baseline_outlay ↓, baseline_surplus ↑)`. The retained-cash floor is the **solve target**, never folded into a scalar score.

### 3.4 Inverter dimension + G98 default

Inverter AC capacity is one of the three swept dimensions. Default discrete set respects the **UK G98 single-phase 3.68 kW cap**: e.g. `{3.68, 5.0, 6.0}` kW. The per-config inverter is set on each home's `PVConfig.inverter_capacity_kw` by the enumerator (the field exists; clipping is live). The financial trade-off (cheaper small inverter + clipping loss vs larger inverter + capex) is **real and now moves the rank**: inverter capex feeds `project_economics` → the solved own-use rate → the outlay. The clip and the inverter cost are exposed as **sensitivity axes**.

### 3.5 Sensitivity panel (pure) — `sensitivity_panel`

```python
def sensitivity_panel(
    base_configs: list[tuple[ConfigPoint, ScenarioConfig]],
    axes: Mapping[str, Sequence[float]],   # FinanceConfig field (or dispatch policy) -> values to test
    *, retained_cash_floor_gbp: float | None = None, simulate=None,
) -> SensitivityPanel: ...
```

- For each axis at each value, `dataclasses.replace` the combo finance (or dispatch), re-run `run_sweep`, record the cost-recovery rank order + `rank_stability` (does the cheapest-feasible config survive as #1?). **Capex knobs now genuinely move the rank** (they move the solved own-use rate → the outlay), so the panel is informative for the whole soft-input set. **Headline board axes (default-on):** `retained_cash_floor_per_home_per_year_gbp` (the board's solvency target — sweeping it traces the outlay↔surplus frontier the survey wanted), `grid_services_income_per_kw_per_year_gbp` (the largest assumption uncertainty, ~10× the surplus — Low/Central/High), and the **dispatch policy** (board TOU+grid-charging vs flat — the time-shift value). Secondary: `battery_cost_per_kwh_gbp`, `pv_cost_per_kwp_gbp`, `inverter_cost_per_kw_gbp`, `retail_baseline_rate_pence_per_kwh`, `seg`/tariff, `self_consumption_override`, degradation. One-axis-at-a-time (OAT); combined-axis is tactical (§12).

### 3.6 Report + CLI surface

- `output.generate_config_ranking_report(ranked, panel) -> str` (new) renders **two tables**: **(1) the cost-recovery rank** (config → solved own-use rate + householder total outlay (rep + min/mean/median/max) + CBS surplus (= floor / headroom) + feasible/binding + total capex + min-DSCR + equity-IRR + payback), with `cheapest_feasible` flagged as the recommendation and `infeasible` configs listed separately; **(2) the fixed-15p trade-off** (config → baseline outlay + baseline surplus + Pareto flag); then the **sensitivity section** (per-axis rank movement + `rank_stability`). Serialised after W2's `generate_finance_report` (same file).
- `cli/optimize.py`: `solar-challenge optimize configs <base-scenario> [--pv 3,4,5,6] [--battery 0,5,10] [--inverter 3.68,5,6] [--retained-floor 27] [--grid-services-kw 12] [--sensitivity retained_floor,grid_services,battery_cost,...]`, registered with one `app.add_typer(optimize_app.app, name="optimize")` line in `cli/main.py`. Discrete sets + soft inputs default to the documented menu (§12) and are re-runnable with installer/aggregator figures.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Objective | **Primary rank = cost-recovery householder total outlay** (own-use rate solved so CBS surplus = the retained-cash floor); **feasibility flag** for configs that can't clear the floor at any rate ≤ retail | The real CBS model couples householder outlay to capex via the own-use rate; ranking the *solved* outlay ranks "the cheapest config that stays solvent at the board's target." *(supersedes the original year-1-net-bill objective — §2.2)* |
| Two objectives / trade-off | **Hybrid:** primary cost-recovery rank + a **fixed-15p (outlay, surplus) Pareto** trade-off view; the retained-floor sweep traces the frontier | Under cost-recovery the two axes are one trade-off (the own-use rate); the hybrid still shows **both quantities + the trade-off** (survey §7), more faithfully than the decoupled two-column Pareto. *(user-confirmed 2026-06-17)* |
| Surplus | **Pinned at the board-set `retained_cash_floor` by the solve** (default £27/home/yr); reported as the headroom when the rate clamps to 0 | Surplus is no longer a free axis — it is the board's chosen solvency target and a config knob. |
| Config unit | **One homogeneous-install fleet per discrete config** (load diversity preserved) | The CBS surplus is fleet-level (shared grant/debt don't split per home); homogeneous-per-config gives a clean per-config solve + outlay distribution straight from W2, zero attribution math. *(user-confirmed)* |
| Inverter | **Swept as a 3rd dimension** with a **G98-realistic default** (AC ∈ {3.68, 5.0, 6.0}); clipping live, capex priced in `project_economics` | Clipping physics is live; inverter capex now moves the solved rate → the rank. *(user-confirmed)* |
| Flexibility | **Time-shift via the board dispatch physics** (W1 TOU+grid-charging, present in the energy aggregates); **grid-services £/kW** as a sensitivity axis (W1 value) | Time-shift is per-config and non-linear in kWh ⟹ physics; grid-services is exogenous ⟹ a parameter. Both surface in the cost-recovery solve. |
| New-code home | **new `optimize.py`** (pure) + `output.py` renderer + new `optimize` CLI subcommand | Mirrors `community.py`/`finance.py`; keeps W3 off contested files. W3 imports the cost-recovery functions, never edits `finance.py`. |
| Sensitivity method | **OAT over `FinanceConfig` knobs + dispatch policy**, headline axes retained-floor + grid-services £/kW + dispatch; report rank stability | Capex knobs now move the rank (coupling), so OAT is informative across the whole soft set; the retained-floor sweep is the board's trade-off view. *(corrects the original task-D false premise — §9 W-H4)* |
| Backward compatibility | Pure additive module + new CLI; no edit to any existing simulation/finance logic | Every existing test stays green; W3 only reads W2's public cost-recovery functions. |

## 5. Pre-conditions for activating

- **The W2 cost-recovery amendment landed:** `cost-recovery-householder-billing.md` tasks **CR1** (`FinanceConfig` cost-recovery fields), **CR2** (CBS-revenue fix + time-shift accounting), **CR3** (`householder_bill` → cost-recovery outlay), **CR4** (`solve_cost_recovery_rate` — **W3's primary producer**). W3's evaluate/rank leaf depends on these.
- **The W1 flexibility physics landed:** `flexibility-value-finance-integration.md` — fleet **TOU + grid-charging** (time-shift) + the `grid_services_income_per_kw_per_year_gbp` value. W3 runs configs under this board dispatch.
- **W3 decompose/queue is gated on the W1 + W2 cost-recovery batch (tasks 52–63) reaching `done`/merged.** Until then the seam binds to declared-but-unlanded capabilities (wired cross-PRD dependency edges, not fictions).
- All other substrate exists — see §6. Novel substrate (`optimize.py` functions, `generate_config_ranking_report`, `cli/optimize.py`) is **produced within this batch**, each by a named task consumed by a named downstream task or the CLI surface.

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `finance.solve_cost_recovery_rate(...) -> CostRecoverySolution` (`representative_outlay_gbp`, `own_use_rate_pence_per_kwh`, `net_surplus_per_home_per_year_gbp`, `feasible`, `binding`) | **producer: W2 cost-recovery task CR4** (`cost-recovery-householder-billing.md` §3.4); declared contract, W2-owned — cross-PRD dependency wired (§7) |
| Redefined `bill_distribution` → `BillBreakdown.total_outlay_gbp`; `project_multi_year`/`project_economics` cost-recovery CBS revenue + `FinanceConfig.{own_use_rate_pence_per_kwh, retained_cash_floor_per_home_per_year_gbp, grid_services_income_per_kw_per_year_gbp}` | **producer: W2 cost-recovery tasks CR1/CR2/CR3** (§3.1–3.3); cross-PRD dependency |
| Fleet **TOU + grid-charging** board dispatch (time-shift value in the energy aggregates) + the grid-services £/kW value | **producer: W1 tasks** (`flexibility-value-finance-integration.md` §3); cross-PRD dependency |
| `fleet.simulate_multi_sweep_iter` / `collect_multi_sweep_results` (cross-sweep executor) | grep:`fleet.py:444+`, `fleet.py:531+` wired |
| `simulate_fleet(...) -> FleetResults`; `FleetResults.home_configs` exposes resolved per-home PV/battery | grep:`fleet.py:319`, `fleet.py:142` wired |
| Frozen config dataclasses + `dataclasses.replace` to build homogeneous-install scenarios (no sampler change) | identity: stdlib; `HomeConfig`/`PVConfig`/`BatteryConfig`/`ScenarioConfig` frozen (config.py:46+, pv.py:18, battery.py:82) |
| `PVConfig.inverter_capacity_kw` exists; clipping live in `simulate_pv_output`; inverter capex in `project_economics` | grep:`pv.py:56`, `pv.py:102-104`, `pv.py:286-291`, `finance.py:1228-1234` wired |
| `output.generate_finance_report` markdown idiom to extend with a ranking renderer | grep:`output.py:666` wired |
| Typer `app` + `add_typer` for a new `optimize` subcommand | grep:`cli/main.py:25-30` wired |
| Scenarios run a full year ⟹ year-1 outlay + the multi-year curve come out directly | grep:`scenarios/*.yaml` period wired |

**Novel substrate introduced (queued within this batch, not assumed):** `optimize.py` (`ConfigPoint`, `ConfigResult`, `RankedSweep`, `SensitivityAxis`, `SensitivityPanel`, `enumerate_configs`, `run_sweep`, `sensitivity_panel`); `output.generate_config_ranking_report`; `cli/optimize.py`. Each is produced by a named task (§10) and consumed by a named downstream task or the CLI surface — no orphan, no fiction. **G3 verdict: PASS**, modulo the cross-PRD dependencies on the W1 + W2 cost-recovery contracts, which the manifest binds as `producer:CR4/W1-task upstream`.

## 7. Cross-PRD relationship (G4)

W3 is recorded in `review/gap-register.md` as **P7**. W3 owns only the **enumerate → evaluate(cost-recovery solve + baseline) → rank/feasibility/Pareto/sensitivity → report** pipeline.

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **W2 cost-recovery amendment** (`cost-recovery-householder-billing.md`) | **consumes** | imports `solve_cost_recovery_rate` (rank) + redefined `bill_distribution`/`project_economics`/`FinanceConfig` cost-recovery fields (baseline pair); read-only, never re-implements | **W2-amendment owns** the signatures (its §7 names W3 as the consumer) | W2 batch queued (tasks 52–63), implementing; **W3 queue-gated on it landing** |
| **W1** (`flexibility-value-finance-integration.md`) | **consumes** | runs configs under W1's fleet TOU + grid-charging (time-shift); sweeps the `grid_services_income_per_kw_per_year_gbp` value W1 fills | **W1 owns** the physics + the grid-services values; **W2 owns the field**; W3 consumes both read-only | W1 batch queued, implementing |
| `output.py` (`generate_finance_report`) | **co-tenant** | W3 adds a **new** `generate_config_ranking_report` beside it; disjoint symbol; file-lock serialises | each owns its own function | additive, serialised |
| `cli/main.py` | **co-tenant** | one `add_typer` line for `optimize` (beside `finance`) | W3 owns `cli/optimize.py` | additive |
| `pv.py` / `fleet.py` / `home.py` / `battery.py` / `finance.py` | **none** | W3 reads public APIs only; sets install dims via `dataclasses.replace` on resolved configs | unchanged | no edge |
| **Enhanced grid-services** (`enhanced-grid-services-capacity-at-events.md`, trigger task 51) | **upstream-of (future)** | the capacity-at-events model later **replaces** the flat per-kW grid-services term W3 sweeps; W3's terminal leaf is wired as a dependency of task 51 when W3 decomposes | that follow-on owns the replacement | deferred; out of scope here (§11) |

**No reciprocal-ownership ambiguity:** the W2 amendment unilaterally owns the cost-recovery finance contract (its own §7 names W3 as the consumer); W1 owns the flexibility physics + values; W3 unilaterally owns the enumerate/rank/report pipeline and consumes the others read-only.

## 8. G5 note — why B + targeted H (not full B+H)

Stakes are board-facing (the ranking picks a real Phase-1 install spec feeding a £750k share-offer + BoM decision), so the W3↔W2 **seam** is specified up front (B, §3.1) and gets a **two-way boundary test** (H, §9 W-H1): the ranked table's per-config numbers must equal calling `solve_cost_recovery_rate` (and the baseline `bill_distribution`/`project_economics`) directly on the same homogeneous scenario. But W3 **does not re-implement** the cost-recovery solve, physics, or economics — those are W2's, covered by W2's B+H + adversarial code↔doc gate (incl. the [FIN]/θ calibration). W3's own risk surface is enumeration correctness, ranking/feasibility/Pareto/tie-break logic, and report legibility — covered by pure unit tests on synthetic record sets. → **B + one seam boundary test**, not a second full B+H over economics.

## 9. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|
| W-H1 | **W3↔W2 seam:** ranked numbers == direct W2 calls | a 2×2 grid run via `run_sweep` with an injected fast `simulate` | each `ConfigResult.representative_outlay_gbp` / `solved_own_use_rate_pence_per_kwh` / `surplus_at_solved_gbp` equals `solve_cost_recovery_rate(...)` for that config's scenario, to ε; `baseline_outlay`/`baseline_surplus` equal `bill_distribution`/`project_economics` at the 15p policy rate |
| W-H2 | **Homogeneous-install + load diversity preserved** | `enumerate_configs` on a base fleet with a load distribution + board dispatch | every home in a combo carries identical PV/battery/inverter; load/occupancy spread + the TOU/grid-charging dispatch are unchanged from `base`; `battery_kwh=0` ⟹ no battery |
| W-H3 | **Ranking + feasibility + Pareto algebra** (pure) | a synthetic `ConfigResult` set with known outlays/surpluses/binding | `results` are exactly the feasible configs ascending by `representative_outlay_gbp`; `infeasible` = exactly the `binding=='infeasible_above_retail'` set; `cheapest_feasible == results[0]`; `pareto_baseline` is exactly the non-dominated set on (baseline_outlay ↓, baseline_surplus ↑); tie-break deterministic |
| W-H4 | **Sensitivity moves the rank the expected way** (the coupling, now real) | OAT on `battery_cost_per_kwh_gbp` ↑ (a CAPEX knob) and on `grid_services_income_per_kw_per_year_gbp` ↑ | raising battery cost raises the solved own-use rate → raises outlay → battery-heavy configs rank **worse** (and may turn infeasible); raising grid-services lowers the solved rate → battery configs rank **better**; `rank_stability` computed; per-value top config listed. *(This is achievable because outlay is coupled to capex — the cost-recovery fix dissolves the original decoupled-bill false premise.)* |
| W-H5 | **Capex→own-use→outlay coupling (the headline)** | two configs, a higher-capex one, fixed energy mix | the higher-capex config has a **higher solved own-use rate** AND **higher `representative_outlay_gbp`**; an over-cheap config clamps (`binding='rate_clamped_zero'`, rate 0, surplus ≥ floor); an over-expensive config is `infeasible_above_retail` |
| W-H6 | **End-to-end report** (the G2 surface) | `solar-challenge optimize configs <scenario>` on a small grid under board dispatch | prints the cost-recovery rank (solved rate + outlay + surplus=floor + feasibility) + the fixed-15p Pareto trade-off + the sensitivity section; a row's numbers are self-consistent and reproduce a direct W2 call; real-PVGIS variant marked `slow` |

## 10. Decomposition plan

Five tasks. **File-lock discipline:** `optimize.py` is new (chain A→B→C→D, serialised); `output.py` ranking renderer by E (after `generate_finance_report` — serialised); `cli/optimize.py` new (E) + one `cli/main.py` `add_typer` line. No edit to `finance.py` or any sim module. **All leaves carry cross-PRD dependencies on the W2 cost-recovery tasks (CR1–CR4) + the W1 physics reaching `done`** (wired at decompose against the actual task IDs in the 52–63 batch).

#### A — `enumerate_configs` + `ConfigPoint` (pure, intermediate)
- **Modules:** `optimize.py` (new) (+ `tests/unit/test_optimize_enumerate.py`)
- **Work:** `ConfigPoint`; `enumerate_configs` builds the cartesian product and, per combo, a homogeneous-install `ScenarioConfig` via `dataclasses.replace` (PV/battery/inverter fixed; load diversity, board dispatch, and cost-recovery `FinanceConfig` knobs preserved).
- **Signal (G2, observable):** enumerating `{pv:[4,5], battery:[0,5], inverter:[3.68,5]}` yields 8 combos, each a scenario whose every home carries the right install dims and whose load distribution + dispatch are unchanged from base (W-H2).
- **Deps:** none W3-internal (config dataclasses landed).

#### B — `run_sweep` evaluate + `ConfigResult`/`RankedSweep` (the orchestration leaf, B+H seam)
- **Modules:** `optimize.py` (+ `tests/integration/test_optimize_sweep.py`)
- **Work:** per config call `solve_cost_recovery_rate` (rank) + the baseline `bill_distribution`/`project_economics` at the policy own-use rate (trade-off); assemble `ConfigResult`; rank feasible by `representative_outlay_gbp`; collect `infeasible`; compute `pareto_baseline`.
- **Signal (G2):** on a 2×2 grid (injected fast `simulate`), every `ConfigResult`'s solved + baseline numbers equal direct W2 calls (W-H1); rank, feasibility, and Pareto sets correct.
- **Deps:** A; **W2 CR4 (`solve_cost_recovery_rate`), CR1/CR2/CR3 (fields + revenue + outlay), W1 physics**.

#### C — Ranking + feasibility + Pareto logic hardening (pure unit leaf)
- **Modules:** `optimize.py` (+ `tests/unit/test_optimize_rank.py`)
- **Work:** factor `rank`/`feasible_split`/`pareto_baseline` into pure helpers over `ConfigResult` sequences with the deterministic tie-break; property tests (outlay ordering, infeasible split, non-domination, clamp/binding handling).
- **Signal:** on synthetic record sets, `results` exactly the feasible set ascending by outlay; `infeasible` exact; `pareto_baseline` exact; tie-break stable (W-H3).
- **Deps:** A (record shape). *(May merge into B if the orchestration leaf stays small; kept separate so the pure logic is tested without a sim.)*

#### D — `sensitivity_panel` + `SensitivityAxis`/`SensitivityPanel` (intermediate)
- **Modules:** `optimize.py` (+ `tests/integration/test_optimize_sensitivity.py`)
- **Work:** OAT over `FinanceConfig` knobs + dispatch policy; `dataclasses.replace`, re-run `run_sweep`, record per-value cost-recovery rankings + `rank_stability`. Headline axes: retained-floor, grid-services £/kW, dispatch.
- **Signal:** raising `battery_cost_per_kwh_gbp` (a capex knob) reorders the rank in the expected direction (battery configs worse) and raising `grid_services_income_per_kw_per_year_gbp` improves them; panel reports per-value top config + stability (W-H4).
- **Deps:** B.

#### E — Ranked report + `optimize` CLI (the user-observable leaf, G2 surface)
- **Modules:** `output.py`, `cli/optimize.py` (new), `cli/main.py` (one `add_typer`), `scenarios/` (+ `tests/integration/test_optimize_cli.py`)
- **Work:** `output.generate_config_ranking_report(ranked, panel)` — the two-table hybrid report (cost-recovery rank + fixed-15p Pareto trade-off) + sensitivity section; `solar-challenge optimize configs <scenario> [--pv …] [--battery …] [--inverter …] [--retained-floor …] [--grid-services-kw …] [--sensitivity …]`.
- **Signal (G2):** `solar-challenge optimize configs scenarios/bristol-phase1.yaml` prints the board-readable cost-recovery rank (solved own-use rate + outlay + surplus=floor + feasibility) + the fixed-15p trade-off + a sensitivity panel; a board member can pick a config (W-H6). Real-PVGIS variant marked `slow`.
- **Deps:** B, C, D; W2 task CR5 (`generate_finance_report`/CLI co-tenancy in `output.py`/`cli/`).

> **Note for decompose-time:** the orchestrator does not yet consume `user_observable_signal` / `consumer_ref` / substrate-confirmed metadata — recorded for a future tracking session. Keep `mypy --strict` green. Mark any real-PVGIS optimisation test `slow`. **Do not queue W3 until the W1 + W2 cost-recovery batch (tasks 52–63) is `done`/merged.** When decomposing, wire each leaf's cross-PRD deps to the actual CR1–CR4 + W1 task IDs, and wire W3's terminal leaf (E) as a dependency of trigger **task 51** (enhanced grid-services follow-on).

## 11. Out of scope

- **Re-implementing the cost-recovery solve / any bill/economics math** — W3 imports W2's cost-recovery functions; if a number is wrong, it's fixed in W2.
- **Capacity-at-events grid-services** — W3 sweeps the flat per-kW `grid_services_income_per_kw_per_year_gbp`; the capacity-at-events-derived replacement is the **enhanced-grid-services follow-on** (trigger task 51), explicitly later.
- **Per-config surplus attribution inside a heterogeneous fleet** — surplus is fleet-level; W3 uses homogeneous-fleet-per-config (§4). A mixed-fleet financeability check on a *chosen* deployment plan is a possible follow-up.
- **25-yr householder-outlay NPV as a ranked column** — W2's `MultiYearCurve` is fleet-level; a lifetime per-home outlay would need a documented approximation or a new W2 per-home multi-year output. Primary rank is the year-1 cost-recovery outlay; the 25-yr view is on the project side (DSCR/IRR/payback) and is tactical (§12).
- **Sweeping battery SOC / round-trip efficiency / battery discharge power** — sensitivity axes at most, not primary install-menu dimensions.
- **Discrete inverter *product* models** (brand/topology) — W3 sweeps inverter AC *capacity*; a product BoM is a future extension.
- **Web exposure** of the ranking report — CLI + engine only here.
- **Combined (multi-axis) sensitivity / formal robust optimisation** — OAT panel here; interaction effects are §12.

## 12. Open questions (tactical — deferred, not design-blocking)

1. **Exact discrete menu.** Default `pv ∈ {3,4,5,6}` kWp, `battery ∈ {0,5,10}` kWh, `inverter ∈ {3.68,5.0,6.0}` kW — confirm against the real installer offer (and whether 3-phase lifts the 3.68 cap). Re-runnable with installer figures.
- 2. **Retained-cash floor default + the trade-off sweep.** Default `retained_cash_floor = £27`; confirm the board's actual target and the floor-sweep range for the trade-off frontier.
- 3. **Grid-services £/kW band + which sensitivity axes ship default-on.** Low ~1.5 / Central ~12 / High ~48 £/kW; ± span per knob; whether dispatch (TOU vs flat), degradation, SEG, self-consumption are all default-on.
- 4. **Curve reuse vs double-sim.** Whether `solve_cost_recovery_rate` should expose its energy curve / baseline pair so W3 gets the rank + the fixed-15p trade-off from **one** sim per config (a small W2 helper), or W3 does a second pure post-sim evaluation. Efficiency-only; the grid is small (≤36 configs).
- 5. **Battery discharge-power sweep.** Whether to add `battery_kw` as a 4th dimension (it moves grid-services £/kW income + dispatch headroom) or hold it at the base value.
- 6. **25-yr outlay view + combined-axis sensitivity.** Approximated lifetime householder NPV column; a small 2-factor grid (e.g. grid-services × retained-floor) for the board view.
- 7. **Grid cardinality / parallelism.** ≤36 configs × 100 homes × full year × the multi-age march is heavier than the original single-year sweep; consider cross-config parallelism or a representative-home pre-filter if the menu grows.
