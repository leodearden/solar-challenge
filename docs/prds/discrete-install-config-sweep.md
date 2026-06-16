# PRD — Discrete install-config optimisation sweep (W3)

- **Source:** 2026-06-15 deployment-readiness survey §6 decision 6 (physics-first install-spec optimisation), §7 (objective function), §8 workstream **W3**. Brief: `/home/leo/.claude/spawn-briefs/solar-w3-config-sweep.md`.
- **Status:** active · authored 2026-06-16
- **Owner seam:** a **new `optimize.py` module** (pure config-grid enumeration + ranking + Pareto + sensitivity over already-computed economics) + a new `solar-challenge optimize configs` CLI subcommand + a ranked-table renderer in `output.py`. **Imports, does not re-implement,** W2's `finance.py` bill/economics functions. No edit to `home.py`/`fleet.py`/`finance.py`/`battery.py`/`pv.py` logic.
- **Approach:** **B + targeted H** (written contract + a two-way boundary test on the W3↔W2 seam). W3 *orchestrates and ranks*; it does not re-derive physics or finance, so the heavy B+H lives in W2 — see §8.
- **Consumes (do not re-touch):** W2 (`docs/prds/financial-layer-battery-fidelity.md`) `finance.householder_bill` / `bill_distribution` / `project_multi_year` / `project_economics` / `FinanceConfig` + dataclasses — the **declared contract W2 owns**; plus the existing fleet/sweep executor (`fleet.simulate_multi_sweep_iter` / `simulate_fleet` / `FleetResults.home_configs`), the frozen config dataclasses (`dataclasses.replace`), and `PVConfig.inverter_capacity_kw` (inverter clipping is live in `simulate_pv_output` via the CEC inverter model).
- **Produces (G1 consumer named):** a **ranked Pareto table of discrete install configs** that **Leo + the ResNet board** read to pick the Phase-1 install spec; the output also feeds funder reporting and the install BoM decision.

---

## 1. Goal

Rank the **discrete** install configurations realistically on offer — `PV (kWp) × battery (kWh) × inverter (kW AC)` — by **minimum total householder bill** (the primary objective), reporting **project surplus per home/yr** alongside as a **hard Pareto constraint** (the ~£27/home/yr financeability floor), with an **assumption-sensitivity panel**. Each config is evaluated by running it through the physics sim + W2's financial layer; the optimisation **reports both axes and the trade-off**, never collapsing them into one score. Estimated prices now; re-runnable when installer figures arrive.

**User-observable outcome:** `solar-challenge optimize configs scenarios/bristol-phase1.yaml` prints a **board-readable ranked markdown table** — one row per discrete config → **year-1 net annual householder bill** (representative + min/mean/median/max distribution) + **project surplus £/home/yr** + key economics sub-totals (min-DSCR, equity-IRR, payback, total capex) — with the **Pareto-optimal set flagged** against the £27 surplus floor, followed by an **assumption-sensitivity section** showing how the ranking moves when the soft inputs are varied. A board member can read it and choose a config.

## 2. Background

### 2.1 What this consumes (verified in code 2026-06-16)

- **W2's financial layer is the bill/economics engine.** W2's committed PRD declares, in a new `finance.py`, the pure functions W3 imports: `householder_bill(summary, annual_self_consumption_kwh, finance, simulation_days) -> BillBreakdown`; a fleet `bill_distribution` helper → `BillDistribution` (`representative` + `per_home_net_bill_gbp` + min/mean/median/max); `project_multi_year(scenario, finance) -> MultiYearCurve`; `project_economics(curve, scenario, finance) -> ProjectEconomics` (`.net_surplus_per_home_per_year_gbp`, `.min_dscr`, `.equity_irr`, `.payback_years`, `.total_capex_gbp`); and `FinanceConfig` (the frozen soft-assumption knob set). **W2 owns these signatures** (W2 PRD §7: "P6 owns the function signatures; W3 references the P6 task as a dependency"). W3 does **not** duplicate this math.
- **Project surplus is a fleet-level quantity.** `project_economics` returns surplus only as `net_surplus_per_home_per_year_gbp = project total ÷ homes`; the £250k grant and project debt are shared, indivisible project facts that do **not** decompose per home. → W3 evaluates **one homogeneous-install fleet per discrete config**, so each config has a clean, well-defined `ProjectEconomics` (and `BillDistribution`) straight from W2 with **zero attribution math** (the resolved design, §4).
- **The existing sweep executor is reused, not the sweep *spec*.** `fleet.simulate_multi_sweep_iter(sweep_configs, …)` flattens many fleet jobs into one `ProcessPoolExecutor` and yields `(sweep_idx, home_idx, SimulationResults)` (`fleet.py:429-487`); `collect_multi_sweep_results` buckets them. W3 feeds it a list of homogeneous-install scenarios. The existing `SweepSpec` (geometric/linear range over a single distribution multiplier) and the single-param `ParameterSweepConfig` do **not** express a cartesian product of explicit discrete sets across three install dimensions — that **enumerator is W3-novel** (§3.2).
- **Inverter clipping is live.** `simulate_pv_output → create_pv_system` sizes a CEC inverter to `PVConfig.effective_inverter_capacity_kw` and pvlib's ModelChain clips AC output at the inverter's Paco (`pv.py:255-420`). So sweeping inverter AC capacity has real physics effect. Today the field **defaults to DC capacity (no clipping)**, which would overstate large-PV generation and bias the ranking — W3 sets a realistic inverter per config and treats the clip as a sensitivity axis (§3.4, §4).

### 2.2 The gaps this PRD fills

1. **No discrete-cartesian config enumerator.** The sweep machinery ranges one distribution multiplier; W3 needs the cartesian product of explicit discrete sets `PV × battery × inverter`, each → a homogeneous-install fleet.
2. **No cross-config ranking / Pareto / sensitivity.** `output.py` has per-run and strategy-pair reports only — no ranked-table-across-configs, no Pareto-front computation, no assumption-sensitivity panel.
3. **Inverter capex is not priced.** W2's capex build-up (`pv_kwp×pv_cost + roof_fit + battery_kwh×battery_cost`) has **no inverter line**, and `project_economics` computes capex internally from resolved configs — so W3 cannot inject inverter cost from outside without re-running W2's debt/DSCR/IRR math. **W2 is being amended** (this session) to add a `FinanceConfig.inverter_cost_per_kw_gbp` term to the capex build-up; W3 declares the dependency (§7).

## 3. Sketch of approach

A **new pure module `optimize.py`** (mirroring how `community.py`/`finance.py` are self-contained consumers): it enumerates the discrete config grid, drives each homogeneous-install scenario through the existing executor + W2's `finance.py` functions, assembles a per-config record, ranks and computes the Pareto front, runs the sensitivity panel, and returns frozen result dataclasses. Rendering lives in `output.py`; the user surface is a new `solar-challenge optimize` CLI subcommand. No simulation/finance logic is reimplemented.

### 3.1 Data model (the contract — B)

```python
# optimize.py — frozen dataclasses, __post_init__ validation

@dataclass(frozen=True)
class ConfigPoint:                       # one discrete install config
    pv_kwp: float
    battery_kwh: float                   # 0.0 == no battery
    inverter_kw: float                   # AC capacity

@dataclass(frozen=True)
class ConfigResult:                      # one config's full evaluation
    config: ConfigPoint
    bill: BillDistribution               # W2 — representative + per-home distribution
    economics: ProjectEconomics          # W2 — surplus / DSCR / IRR / payback / capex
    # convenience projections for ranking/report (copied from the W2 objects):
    rep_net_annual_bill_gbp: float       # == bill.representative.net_annual_bill_gbp (primary key)
    net_surplus_per_home_per_year_gbp: float  # == economics.net_surplus_per_home_per_year_gbp

@dataclass(frozen=True)
class RankedSweep:
    results: tuple[ConfigResult, ...]    # ascending by rep_net_annual_bill_gbp (primary objective)
    pareto_optimal: tuple[ConfigPoint, ...]   # non-dominated on (bill ↓, surplus ↑)
    surplus_floor_gbp: float             # the financeability constraint (default 27.0)
    feasible: tuple[ConfigPoint, ...]    # configs meeting surplus >= floor

@dataclass(frozen=True)
class SensitivityAxis:
    name: str                            # e.g. "battery_cost_per_kwh_gbp", "self_consumption_override"
    values: tuple[float, ...]
    rankings: tuple[tuple[ConfigPoint, ...], ...]   # top-ranked order under each value
    top_config_per_value: tuple[ConfigPoint, ...]

@dataclass(frozen=True)
class SensitivityPanel:
    axes: tuple[SensitivityAxis, ...]
    baseline_top: ConfigPoint
    rank_stability: float                # fraction of axis-values for which baseline_top stays #1
```

### 3.2 Config-grid enumerator (pure) — `enumerate_configs`

```python
def enumerate_configs(
    base: ScenarioConfig,                # supplies fleet load diversity, location, period, tariff/SEG, finance
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> list[tuple[ConfigPoint, ScenarioConfig]]: ...
```

- Cartesian product of the three discrete sets. For each combo, build a **homogeneous-install** scenario via `dataclasses.replace` over the base fleet's resolved home configs: every home's `PVConfig.capacity_kw = pv_kwp`, `PVConfig.inverter_capacity_kw = inverter_kw`, `BatteryConfig.capacity_kwh = battery_kwh` (0 ⟹ no battery). **Load / occupancy diversity is preserved** — only the install spec is fixed, so the bill *distribution* still reflects real household spread.
- The combo's `FinanceConfig` is the base scenario's `finance` block. When inverter is priced (§3.4) the per-combo finance sets `inverter_cost_per_kw_gbp` and a **panels-only** `pv_cost_per_kwp_gbp` so total capex isn't double-counted (§4).

### 3.3 Evaluate + rank (the orchestration) — `run_sweep`

```python
def run_sweep(
    configs: list[tuple[ConfigPoint, ScenarioConfig]],
    *, surplus_floor_gbp: float = 27.0,
    simulate=simulate_multi_sweep_iter,  # injectable for fast tests
) -> RankedSweep: ...
```

- Run all homogeneous scenarios through the existing cross-sweep executor (one job pool, max CPU). For each, call W2's `bill_distribution` (year-1) and `project_multi_year` → `project_economics`; assemble a `ConfigResult`.
- **Rank** ascending by `rep_net_annual_bill_gbp` (primary objective). **Pareto front** over `(bill ↓, surplus ↑)`: a config is non-dominated if no other config has both ≤ bill and ≥ surplus. **`feasible`** = configs with `surplus >= surplus_floor_gbp`. Deterministic tie-break: `(bill, -surplus, pv_kwp, battery_kwh, inverter_kw)`. The £27 floor is **flagged**, never folded into the rank key.

### 3.4 Inverter dimension + G98 default

Inverter AC capacity is one of the three swept dimensions. Default discrete set respects the **UK G98 single-phase 3.68 kW cap**: e.g. `{3.68, 5.0, 6.0}` kW. The per-config inverter is set on each home's `PVConfig.inverter_capacity_kw` by the enumerator (no sampler/parser change needed — the field exists; clipping is live). **Financial trade-off** (cheaper small inverter vs clipping loss) is real only once W2's `inverter_cost_per_kw_gbp` lands (§7); until then the default `0.0` means inverter sizing affects bills via clipping only (and the sweep is still valid for the bill axis). The clip is also exposed as a **sensitivity axis** so the ranking's exposure to inverter policy is visible.

### 3.5 Sensitivity panel (pure) — `sensitivity_panel`

```python
def sensitivity_panel(
    base_configs: list[tuple[ConfigPoint, ScenarioConfig]],
    axes: Mapping[str, Sequence[float]],   # FinanceConfig field -> values to test
    *, surplus_floor_gbp: float = 27.0, simulate=...,
) -> SensitivityPanel: ...
```

- For each axis (a `FinanceConfig` knob — `battery_cost_per_kwh_gbp`, `pv_cost_per_kwp_gbp`, `inverter_cost_per_kw_gbp`, `retail_baseline_rate_pence_per_kwh`, `seg`/tariff rate, `self_consumption_override` 0.45/0.70, degradation) at each value, `dataclasses.replace` the combo finance, re-run `run_sweep`, record the top-ranked order. Report `rank_stability` (does the baseline winner survive?) and the per-axis top config. One-axis-at-a-time (OAT); combined-axis exploration is a tactical extension (§12).

### 3.6 Report + CLI surface

- `output.generate_config_ranking_report(ranked, panel) -> str` (new) renders: a **ranked table** (config → year-1 rep bill + bill distribution + surplus £/home/yr + min-DSCR + equity-IRR + payback + total capex), the **Pareto-optimal set** and **feasible set** flagged against the £27 floor, then the **sensitivity section** (per-axis ranking movement + stability). Serialised after W2's `generate_finance_report` (same file).
- `cli/optimize.py`: `solar-challenge optimize configs <base-scenario> [--pv 3,4,5,6] [--battery 0,5,10] [--inverter 3.68,5,6] [--surplus-floor 27] [--sensitivity battery_cost,self_consumption,...]`, registered with one `app.add_typer(optimize_app.app, name="optimize")` line in `cli/main.py`. Discrete sets default to the documented menu (§12) and are re-runnable with installer figures.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Config unit | **One homogeneous-install fleet per discrete config** (load diversity preserved) | W2 exposes surplus only fleet-wide (shared grant/debt don't split per home). Homogeneous-per-config gives a clean per-config surplus AND bill distribution straight from W2 — true two-column Pareto, zero attribution math. *(user-confirmed)* |
| Objective | **Primary rank = year-1 net annual householder bill**; surplus reported alongside as a hard Pareto constraint | "Minimum total householder bill" is primary; £27/home/yr surplus is a constraint, not folded into one score (survey §7). Year-1 bill is produced directly by W2's `householder_bill`/`bill_distribution` — G6-safe (no unbacked lifetime-bill premise). *(user-confirmed)* |
| Surplus source | `ProjectEconomics.net_surplus_per_home_per_year_gbp` per homogeneous-fleet config | A real W2 output per config; the £27 floor is flagged, never asserted-equal. |
| Inverter | **Swept as a 3rd dimension** with a **G98-realistic default** (AC ∈ {3.68, 5.0, 6.0}); priced via a **W2 amendment** | Clipping physics is already live; the DC=AC default would bias toward big PV. Financial lever needs W2's `inverter_cost_per_kw_gbp` (being amended now). *(user-confirmed)* |
| Inverter capex / double-count | W2 default `inverter_cost_per_kw_gbp = 0.0` (calibration bit-identical); W3 sweep scenarios set it nonzero **with** a panels-only reduced `pv_cost_per_kwp_gbp` | Adding an inverter line without splitting it out of the £1000/kWp would inflate capex and break W2's spreadsheet calibration (θ). Default 0 keeps W2 green; W3 opts in consistently. |
| New-code home | **new `optimize.py`** (pure) + `output.py` renderer + new `optimize` CLI subcommand | Mirrors `community.py`/`finance.py`; keeps W3 off contested files. W3 imports `finance.py`, never edits it. |
| Pareto vs single score | **Two-column Pareto front + feasible-set flag**, never a weighted scalar | Brief mandate (survey §7): report both objectives and the trade-off. |
| Sensitivity method | **OAT over `FinanceConfig` knobs + the inverter clip**, report rank stability | The soft inputs are exactly `FinanceConfig` fields W3 can `replace`; OAT is the legible board-facing view. Combined-axis is tactical (§12). |
| Backward compatibility | Pure additive module + new CLI; no edit to any existing simulation/finance logic | Every existing test stays green; W3 only reads W2's public functions. |

## 5. Pre-conditions for activating

- **W2 leaves landed:** **γ** (`FinanceConfig` + parser, **incl. the inverter-capex amendment**), **δ** (`householder_bill` + `bill_distribution`), **ε** (`FleetSummary` financial aggregation), **ζ** (`project_multi_year`), **η** (`project_economics` + capex build-up, **incl. the inverter term**). W3's evaluate/rank leaf depends on these. **W3 decompose/queue is gated on these W2 tasks reaching `done`/merged** (brief §17).
- **W2 inverter-capex amendment** committed to W2's PRD + tasks γ/η (this session). Until then the seam binds to a declared-but-unlanded capability (a wired cross-PRD dependency edge, not a fiction).
- All other substrate exists — see §6. Novel substrate (`optimize.py` functions, `generate_config_ranking_report`, `cli/optimize.py`) is **produced within this batch**, each by a named task consumed by a named downstream task or the CLI surface.

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `finance.householder_bill` / `bill_distribution` / `project_multi_year` / `project_economics` / `FinanceConfig` + dataclasses | **producer: W2 tasks δ/ζ/η/γ** (PRD `financial-layer-battery-fidelity.md` §3.1-3.4); declared contract, W2-owned — cross-PRD dependency wired (§7) |
| `FinanceConfig.inverter_cost_per_kw_gbp` + inverter term in `project_economics` capex | **producer: W2 tasks γ/η (amended this session)** — wired cross-PRD dependency |
| `fleet.simulate_multi_sweep_iter` flattens many fleet jobs into one `ProcessPoolExecutor`; `collect_multi_sweep_results` buckets | grep:`fleet.py:429-487`, `fleet.py:516+` wired |
| `simulate_fleet(scenario,…) -> FleetResults`; `FleetResults.home_configs` exposes resolved per-home PV/battery for grouping/capex | grep:`fleet.py:132-197` wired (P5: signature unchanged) |
| Frozen config dataclasses + `dataclasses.replace` to build homogeneous-install scenarios (no sampler change) | identity: stdlib; `HomeConfig`/`PVConfig`/`BatteryConfig`/`ScenarioConfig` frozen |
| `PVConfig.inverter_capacity_kw` exists; inverter clipping live in `simulate_pv_output` via CEC inverter | grep:`pv.py:55-56`, `pv.py:102-104` (`effective_inverter_capacity_kw`), `pv.py:255-420` wired |
| `output.generate_summary_report` / `generate_finance_report` markdown idiom to extend with a ranking renderer | grep:`output.py:147-286`; **producer: W2 task δ** (`generate_finance_report`, serialises `output.py`) |
| Typer `app` + `add_typer` for a new `optimize` subcommand | grep:`cli/main.py:17`, `cli/main.py:24-28` wired |
| Scenarios run a full year (`simulation_days == 365`) ⟹ year-1 annual bill comes out directly | grep:`scenarios/*.yaml` `period: 2024-01-01..2024-12-31` wired |

**Novel substrate introduced (queued within this batch, not assumed):** `optimize.py` (`ConfigPoint`, `ConfigResult`, `RankedSweep`, `SensitivityAxis`, `SensitivityPanel`, `enumerate_configs`, `run_sweep`, `sensitivity_panel`); `output.generate_config_ranking_report`; `cli/optimize.py`. Each is produced by a named task (§10) and consumed by a named downstream task or the CLI surface — no orphan, no fiction. **G3 verdict: PASS**, modulo the cross-PRD dependency on W2's (now-amended) `finance.py` contract, which the manifest binds as `producer:W2-task upstream`.

## 7. Cross-PRD relationship (G4)

W3 is added to `review/gap-register.md` as **P7**; seam rows append to §C. W3 owns only the **enumerate → run → rank/Pareto/sensitivity → report** pipeline.

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **W2** (financial layer, `finance.py`) | **consumes** | imports `householder_bill`/`bill_distribution`/`project_multi_year`/`project_economics`/`FinanceConfig` (read-only); never re-implements | **W2 owns** the signatures (W2 PRD §7); W3 references W2 tasks δ/ζ/η/γ as dependencies | seam declared by W2; **W3 queue-gated on W2 landing** |
| **W2 task γ** (`FinanceConfig`) | **consumes + requires amendment** | W3 needs `inverter_cost_per_kw_gbp` added (default 0.0, calibration-preserving) | **W2 owns**; amended this session per Leo | amend in flight |
| **W2 task η** (`project_economics`) | **consumes + requires amendment** | W3 needs the inverter capex term in the build-up | **W2 owns**; amended this session | amend in flight |
| `output.py` (W2 task δ `generate_finance_report`) | **co-tenant** | W3 adds a **new** `generate_config_ranking_report` beside it; disjoint symbol; file-lock serialises (W3 queues after W2) | each owns its own function | additive, serialised |
| `cli/main.py` | **co-tenant** | one `add_typer` line for `optimize` (beside W2's `finance` line) | W3 owns `cli/optimize.py` | additive |
| `pv.py` / `fleet.py` / `home.py` / `battery.py` | **none** | W3 reads public APIs only; sets `inverter_capacity_kw` via `dataclasses.replace` on resolved configs | unchanged | no edge |

**No reciprocal-ownership ambiguity:** W2 unilaterally owns the finance contract (it predates W3 and its CLI report is itself a named consumer); W3 unilaterally owns the enumerate/rank/report pipeline. The one bidirectional touch — W3 needing an inverter capex field — is resolved by **amending W2's owned contract** (not W3 reaching into `finance.py`), so ownership stays clean.

## 8. G5 note — why B + targeted H (not full B+H)

Stakes are board-facing (the ranking picks a real Phase-1 install spec feeding a funder decision), so the W3↔W2 **seam** is specified up front (B, §3.1) and gets a **two-way boundary test** (H, §9 W-H1): the ranked table's per-config numbers must equal calling W2's functions directly on the same homogeneous scenario. But W3 **does not re-implement** physics or finance — the numerically load-bearing economics are W2's, already covered by W2's B+H (incl. spreadsheet calibration θ). W3's own risk surface is enumeration correctness, Pareto/tie-break logic, and report legibility — covered by pure unit tests on synthetic record sets. → **B + one seam boundary test**, not a second full B+H over economics that would duplicate W2's.

## 9. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|
| W-H1 | **W3↔W2 seam:** ranked numbers == direct W2 calls | a 2×2 grid run via `run_sweep` with an injected fast `simulate` | each `ConfigResult.rep_net_annual_bill_gbp` / `net_surplus_per_home_per_year_gbp` equals `bill_distribution(...).representative.net_annual_bill_gbp` / `project_economics(...).net_surplus_per_home_per_year_gbp` for that config's scenario, to ε |
| W-H2 | **Homogeneous-install + load diversity preserved** | `enumerate_configs` on a base fleet with a load distribution | every home in a combo scenario has identical PV/battery/inverter; the load/occupancy spread is unchanged from `base`; `battery_kwh=0` ⟹ no battery |
| W-H3 | **Ranking + Pareto + floor algebra** (pure) | a synthetic `ConfigResult` set with known bills/surpluses | `results` ascending by bill; `pareto_optimal` is exactly the non-dominated set on (bill ↓, surplus ↑); `feasible` is exactly surplus ≥ floor; tie-break deterministic |
| W-H4 | **Sensitivity moves the ranking the expected way** | OAT on `battery_cost_per_kwh_gbp` ↑ | configs with more battery rank worse as battery cost rises; `rank_stability` computed; panel lists per-value top config |
| W-H5 | **Inverter clip is live + capex consistent** | a config with `inverter_kw < pv_kwp` vs `inverter_kw = pv_kwp`; nonzero `inverter_cost_per_kw_gbp` + panels-only `pv_cost` | the smaller inverter shows clipped generation (lower self-consumption/export) AND lower `total_capex_gbp`; with default cost 0.0 + unchanged pv_cost, capex matches the no-inverter-line baseline (W2 calibration preserved) |
| W-H6 | **End-to-end report** (the G2 surface) | `solar-challenge optimize configs <scenario>` on a small grid | prints a ranked table with Pareto/feasible flags + sensitivity section; a row's numbers are self-consistent; real-PVGIS variant marked `slow` |

## 10. Decomposition plan

Five tasks. **File-lock discipline:** `optimize.py` is new (chain A→B→C→D, serialised); `output.py` ranking renderer by E (after W2's `generate_finance_report` — serialised); `cli/optimize.py` new (E) + one `cli/main.py` `add_typer` line. No edit to W2's `finance.py` or any sim module. **All leaves carry a cross-PRD dependency on W2 tasks γ/δ/ζ/η reaching `done`.**

#### A — `enumerate_configs` + `ConfigPoint` (pure, intermediate)
- **Modules:** `optimize.py` (new) (+ `tests/unit/test_optimize_enumerate.py`)
- **Work:** `ConfigPoint` frozen dataclass; `enumerate_configs` builds the cartesian product and, per combo, a homogeneous-install `ScenarioConfig` via `dataclasses.replace` over the base fleet's resolved home configs (PV/battery/inverter fixed, load diversity preserved).
- **Signal (G2, observable):** enumerating `{pv:[4,5], battery:[0,5], inverter:[3.68,5]}` yields 8 combos, each a scenario whose every home carries the right install dims and whose load distribution is unchanged from the base (W-H2).
- **Deps:** none W3-internal (config dataclasses landed).

#### B — `run_sweep` evaluate + `ConfigResult`/`RankedSweep` (the orchestration leaf, B+H seam)
- **Modules:** `optimize.py` (+ `tests/integration/test_optimize_sweep.py`)
- **Work:** drive enumerated scenarios through `simulate_multi_sweep_iter`; per config call W2's `bill_distribution` + `project_multi_year` → `project_economics`; assemble `ConfigResult`; rank ascending by `rep_net_annual_bill_gbp`; compute `pareto_optimal` / `feasible` against `surplus_floor_gbp` (default 27.0).
- **Signal (G2):** on a 2×2 grid (injected fast `simulate`), every `ConfigResult`'s bill/surplus equals direct W2-function calls on that scenario (W-H1); ranking + Pareto + feasible sets are correct.
- **Deps:** A; **W2 δ (`bill_distribution`), ζ (`project_multi_year`), η (`project_economics`), γ (`FinanceConfig` incl. inverter capex)**.

#### C — Ranking + Pareto logic hardening (pure unit leaf)
- **Modules:** `optimize.py` (+ `tests/unit/test_optimize_rank.py`)
- **Work:** factor `rank`/`pareto_front`/`feasible` into pure helpers over `ConfigResult` sequences with the deterministic tie-break; property tests (non-domination, monotonicity, floor boundary).
- **Signal:** on synthetic record sets, `pareto_optimal` is exactly the non-dominated set on (bill ↓, surplus ↑); `feasible` exactly surplus ≥ floor; tie-break stable (W-H3).
- **Deps:** A (record shape). *(May merge into B if the orchestration leaf stays small; kept separate so the pure logic is tested without a sim.)*

#### D — `sensitivity_panel` + `SensitivityAxis`/`SensitivityPanel` (intermediate)
- **Modules:** `optimize.py` (+ `tests/integration/test_optimize_sensitivity.py`)
- **Work:** OAT over `FinanceConfig` knobs + the inverter clip; `dataclasses.replace` the per-combo finance, re-run `run_sweep`, record per-value rankings + `rank_stability`.
- **Signal:** raising `battery_cost_per_kwh_gbp` reorders the ranking in the expected direction; panel reports per-value top config + stability (W-H4).
- **Deps:** B.

#### E — Ranked report + `optimize` CLI (the user-observable leaf, G2 surface)
- **Modules:** `output.py`, `cli/optimize.py` (new), `cli/main.py` (one `add_typer`), `scenarios/` (+ `tests/integration/test_optimize_cli.py`)
- **Work:** `output.generate_config_ranking_report(ranked, panel)` — ranked table (config → year-1 rep bill + distribution + surplus + min-DSCR/IRR/payback + capex), Pareto/feasible flags, sensitivity section; `solar-challenge optimize configs <scenario> [--pv …] [--battery …] [--inverter …] [--surplus-floor …] [--sensitivity …]`.
- **Signal (G2):** `solar-challenge optimize configs scenarios/bristol-phase1.yaml` prints a board-readable ranked Pareto table with the £27 floor flagged + a sensitivity panel; a board member can pick a config (W-H6). Real-PVGIS variant marked `slow`.
- **Deps:** B, C, D; W2 task δ (`generate_finance_report`, serialises `output.py`).

> **Note for decompose-time:** the orchestrator does not yet consume `user_observable_signal` / `consumer_ref` / substrate-confirmed metadata — recorded for a future tracking session. Keep `mypy --strict` green. Mark any real-PVGIS optimisation test `slow`. **Do not queue W3 until W2 tasks γ/δ/ζ/η are `done`/merged** (incl. the inverter-capex amendment).

## 11. Out of scope

- **Re-implementing any bill/economics math** — W3 imports W2's `finance.py`; if a number is wrong, it's fixed in W2.
- **Per-config surplus attribution inside a heterogeneous fleet** — surplus is fleet-level; W3 uses homogeneous-fleet-per-config instead (§4). A mixed-fleet financeability check on a *chosen* deployment plan is a possible follow-up, not this PRD.
- **25-yr householder-bill NPV as a ranked column** — W2's `MultiYearCurve` is fleet-level (per-year revenue), not per-home bills per year; a lifetime per-home bill would need a documented approximation or a new W2 per-home multi-year output. Primary rank is year-1 bill; the 25-yr view is carried on the *project* side (DSCR/IRR/payback) and is a tactical extension (§12).
- **Sweeping battery SOC / round-trip efficiency** — W2 task α makes these YAML-configurable; W3 may add them as *sensitivity* axes later, but they are not primary install-menu dimensions.
- **Discrete inverter *product* models** (brand/topology) — W3 sweeps inverter AC *capacity*; a product BoM (efficiency curves per model) is a future extension.
- **Web exposure** of the ranking report — CLI + engine only here.
- **Combined (multi-axis) sensitivity / formal robust optimisation** — OAT panel here; interaction effects are §12.

## 12. Open questions (tactical — deferred, not design-blocking)

1. **Exact discrete menu.** Default `pv ∈ {3,4,5,6}` kWp, `battery ∈ {0,5,10}` kWh, `inverter ∈ {3.68,5.0,6.0}` kW — confirm against the real installer offer (and whether 3-phase lifts the 3.68 cap for some homes). Menu values are CLI/config inputs; re-runnable when installer figures land (brief §36).
2. **Inverter cost £/kW.** Default for `inverter_cost_per_kw_gbp` and the matching panels-only `pv_cost_per_kwp_gbp` split — set from the installer quote / [FIN] cell once known; default 0.0 keeps W2 calibration intact meanwhile.
3. **Sensitivity ranges + which axes ship by default.** ± span per `FinanceConfig` knob and whether degradation / SEG / self_consumption_override (45/70) are all default-on.
4. **25-yr bill view.** Whether to add an approximated lifetime householder NPV column (representative bill × W2 SOH/degradation curve) once W2's curve shape is fixed.
5. **Combined-axis sensitivity.** Whether a small 2-factor grid (e.g. battery cost × SEG rate) is worth the extra runs for the board view.
6. **Grid cardinality.** 36 combos × 100 homes × full year is comfortable for the ProcessPool path; if the menu grows, consider a representative-home pre-filter before the full-fleet pass.
