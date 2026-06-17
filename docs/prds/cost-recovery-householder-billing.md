# PRD — Cost-recovery householder billing (W2 amendment)

- **Source:** 2026-06-15 deployment-readiness survey §1/§3/§6-decision-6/§7; W3 decompose-session
  finding (2026-06-17) that W3's "minimum total householder bill" objective is mis-specified
  against the real Bristol CBS business model. Brief:
  `/home/leo/.claude/spawn-briefs/solar-w2-cost-recovery-amendment.md`.
- **Status:** active · authored 2026-06-17 · target board meeting **Friday 2026-06-19**
- **Relationship to W2:** **successor/amendment** to the merged W2 finance layer
  (`docs/prds/financial-layer-battery-fidelity.md`, tasks #43–#49 `done`). This is **additive new
  capability that also fixes one load-bearing defect in W2's revenue/bill definition** — so it is a
  fresh `/prd` author pass with full G1–G6 + META gates, **not** a silent edit. W2 stays `done`; this
  PRD owns its own task batch + capability manifest.
- **Owner seam:** the **`FinanceConfig` cost-recovery contract** (three new fields) + new
  **cost-recovery bill / solve functions and result dataclasses** in `finance.py`, a **fixed CBS-revenue
  definition** in `project_multi_year`, a `solar-challenge finance run --cost-recovery` surface, a
  **human-readable finance-model doc**, and a **final adversarial code↔doc verification gate**.
- **Approach:** **B + H + adversarial acceptance gate.** High stakes: board-facing numbers, a cross-PRD
  consumer (W3), and this redefines *the definition of the householder bill*. See §8.
- **Consumes (do not re-touch):** W2's `project_economics` (pure curve→economics; **unchanged** — its
  tests feed synthetic curves), the `MultiYearCurve`/`YearPoint` energy quantities
  (`fleet_self_consumption_kwh`, `fleet_export_kwh` per year — finance.py:100–110), `FinanceConfig`
  (config.py:478–518), `bill_distribution`/`householder_bill` shape (finance.py:139,636), the finance
  CLI + `generate_finance_report` (cli/finance.py, output.py). PVGIS/physics aggregates from W2/#2/P3
  (landed).
- **Produces (G1 consumers named):** the **cost-recovery householder outlay** + **solved minimum
  own-use rate** that **W3** ranks configs by, the `solar-challenge finance` CLI + finance report
  render, and **Leo + the ResNet board** read for the Friday 2026-06-19 install-spec decision.

---

## 1. Goal

Replace the simulator's **decoupled, double-counted** householder-bill / project-surplus model with a
**cost-recovery model** that matches the real Bristol Community Benefit Society (CBS) business model, so
that W3 can rank install configs by the **right** number.

**The defect being fixed (verified in code 2026-06-17):**

- `householder_bill` (finance.py:139–289) prices self-consumed solar as a **free saving to the
  householder** at full retail (`self_consumption_saving_gbp = sc_kwh × retail_baseline_rate × (1+vat)`,
  line 259). The householder pays **£0** for self-consumed solar.
- `project_multi_year` (finance.py:864–877) sets CBS fleet revenue =
  `Σ_home (self_consumption_saving_gbp + seg_export_income_gbp)` — crediting the **same** retail-valued
  self-consumption to **both** the householder's saving **and** the CBS's revenue, and crediting SEG to
  both sides too.
- Net effect: the householder bill and the CBS surplus are **decoupled by an accounting artifact**.
  There is no own-use rate, no transfer price. At a fixed config the two are *actually* a 1:1 trade-off
  along the own-use rate, which a frozen 23p retail rate cannot express — so a bill-ranking biases
  toward the **largest install that clears the surplus floor**, the opposite of what a cost-recovery
  society wants.

**The real Bristol model (survey §1/§3/§7, verified against [FIN]/[FEAS]):** a CBS owns the PV +
batteries (householders take no debt; roof lease — "virtual urban solar farm"). The CBS **bills
householders an own-use rate** ([FIN] baseline **15 p/kWh**) for self-consumed CBS-owned solar — *below*
the ~23 p/kWh grid retail; that gap is the householder's **~£324/yr ≈ 30% saving**. CBS **income** =
own-use revenue + SEG (6 p export) + **flexibility income** (W1). CBS **outgoings** = debt service +
opex. **Net retained surplus ≈ £27/home/yr** — razor-thin. The own-use rate is the **CBS policy lever
and the coupling**: bigger/pricier install → more capex → more debt service → the CBS must **raise the
own-use rate** (↑ householder bill) *or* eat the surplus. This feedback is what bounds install size.

**User-observable outcome:** `solar-challenge finance run --cost-recovery scenarios/bristol-phase1.yaml`
prints, per config/fleet: the **solved minimum own-use rate**, the resulting **householder total annual
outlay** (representative + min/mean/median/max), and **CBS surplus = the retained-cash floor** (by
construction). Running a higher-capex config shows a **higher required own-use rate and higher
householder outlay** — the coupling, now observable end-to-end. A board member reads one config's
numbers and checks them by hand against the **human-readable finance-model doc** (`docs/`).

## 2. Background

### 2.1 What already exists (verified in code 2026-06-17 — do not rebuild)

- **The correct CBS-revenue shape already exists, in one corner only.**
  `spreadsheet_revenue_curve` (finance.py:1314+) **already** prices revenue as
  `own_use_rate × self + export_rate × export` (15 p / 6 p) — but only as a **function argument** feeding
  the θ/#48 calibration's "spreadsheet-input" column. The **physics** path (`project_multi_year` /
  `householder_bill`) does **not** use it. This amendment makes the physics path consistent with the
  shape `spreadsheet_revenue_curve` already encodes.
- **`project_economics` is pure and consumes a revenue curve** (finance.py:1175–1306). Its tests feed
  **synthetic** `YearPoint`s with explicit `fleet_revenue_gbp` (test_finance_economics.py:27–36), so its
  capex/DSCR/IRR/annuity arithmetic is **unaffected** by changing how the *curve* is built. ✅
- **`MultiYearCurve.points[y]` already carries per-year energy quantities** —
  `fleet_self_consumption_kwh`, `fleet_export_kwh`, `fleet_import_kwh` (finance.py:100–110) — so the
  cost-recovery surplus can be expressed analytically as a function of the own-use rate **without
  re-running the sim**. This makes the solve near-closed-form.
- **`FinanceConfig` is a frozen dataclass with appended-default fields** (config.py:478–518); adding
  keyword fields with defaults is back-compat-safe and keeps `mypy --strict` green.
- **`bristol-phase1.yaml` carries only `standing_charge_pence_per_day`** (line 56); every new finance
  field defaults, so existing scenarios round-trip unchanged.

### 2.2 The θ/#48 compatibility analysis (META-load-bearing)

The W2 θ/#48 calibration (`tests/integration/test_finance_calibration.py`,
`docs/finance-spreadsheet-reconciliation.md`) **must stay green**. Verified:

- Its **hard** assertions — `total_capex == £775,000 ±£1`, `min_dscr ≥ 1.20`, `equity_irr > 0` — flow
  through `spreadsheet_revenue_curve → project_economics` (test lines 397–591). **Neither**
  `project_multi_year` **nor** `householder_bill` is in that path, so fixing the physics revenue/bill
  does **not** touch the hard gate.
- The **physics** calibration column is `@pytest.mark.slow` and **reported-only** (reconciliation note
  §4). It is re-derived/re-reported here, never hard-pinned.

→ The fix-in-place is **safe for θ**. The recalibration blast radius is confined to (a)
`project_multi_year`'s revenue line, (b) `householder_bill`/`BillBreakdown`/`bill_distribution`
semantics + their tests (test_finance_bill.py), (c) the δ finance report. **Leo accepted this churn**
(2026-06-17 decision: "fix-in-place + recalibrate").

### 2.3 The flex-income value (W1, survey §3)

Flexibility income is worth **Low £120 / Central £280 / High £450 per battery-equipped home/yr** (W1,
`2026-06-16-flexibility-value-buildability-model.md` §0/§1). W1 explicitly states *how it splits between
householder-bill reduction and CBS revenue is a tariff-design choice the W2 sim models* — here it accrues
to **CBS revenue** (it lets the CBS lower the own-use rate, deepening the householder saving while
holding the surplus floor). W1 also warns the value is **not physically linear in battery capacity**
(arbitrage and self-consumption contend for the same kWh) — see §12.

## 3. Sketch of approach

All new computation lives in **`finance.py`** (pure, frozen dataclasses, `__post_init__` validation),
beside the existing W2 functions. The CBS-revenue defect is **fixed in place** in `project_multi_year`;
the householder bill is **redefined in place** to the cost-recovery outlay; a new **solve** sits on top;
the CLI/report gain a `--cost-recovery` surface; a **human-readable model doc** is the written spec; and
a **final adversarial gate** verifies code↔doc fidelity.

### 3.1 Data model (the contract — B)

```python
# config.py — FinanceConfig gains three appended fields (defaults preserve existing round-trips)

own_use_rate_pence_per_kwh: float = 15.0
    # CBS transfer price for self-consumed CBS-owned solar ([FIN] baseline). Validate >= 0.
retained_cash_floor_per_home_per_year_gbp: float = 27.0
    # Board-set minimum retained CBS surplus per home/yr ([FEAS] baseline). Validate >= 0.
    # Generalises the £27 financeability floor; the cost-recovery solve targets this.
flex_income_per_battery_kwh_per_year_gbp: float = 28.0
    # W1 SEAM (W2 owns the field, W1 fills the value). Annual flexibility income credited to
    # CBS revenue per kWh of installed battery. Validate >= 0. Default ≈ Central £280/battery-home
    # ÷ 10 kWh representative battery ([FIN] with-battery basis). See §7 + §12.

# finance.py — BillBreakdown REDEFINED to the cost-recovery householder outlay
@dataclass(frozen=True)
class BillBreakdown:                 # one CBS-customer householder, one year
    standing_charge_gbp: float
    import_cost_gbp: float           # grid import: retail × import_kwh, ex-VAT (unchanged)
    own_use_payment_gbp: float       # NEW: own_use_rate × self_consumed_kwh, ex-VAT (→ CBS income)
    vat_gbp: float                   # vat_rate × (import_cost + standing + own_use_payment) †
    total_outlay_gbp: float          # NEW HEADLINE: (import_cost+standing+own_use_payment)×(1+vat).
                                     #   The householder's TOTAL annual payment. NO SEG credit —
                                     #   the CBS owns the assets and the export MPAN.
    baseline_bill_gbp: float         # all-grid-at-retail counterfactual, VAT-inclusive (unchanged)
    self_consumption_saving_gbp: float  # REDEFINED: self_consumed × (retail − own_use) × (1+vat) —
                                     #   the REAL per-kWh saving (the retail↔own-use gap), not a free
                                     #   retail saving.
    saving_vs_baseline_gbp: float    # baseline_bill − total_outlay  (REDEFINED)
    saving_pct: float                # 100 × saving_vs_baseline / baseline (unchanged formula)
    self_consumption_fraction: float # unchanged
    # REMOVED: seg_export_income_gbp (householder gets no SEG); net_annual_bill_gbp → total_outlay_gbp.
    # † own-use VAT treatment is a deferred regulatory question (§11/§12); vat_rate is configurable so
    #   either treatment (5% domestic, or 0% if the class-exemption supply route zero-rates it) is
    #   expressible. Default: own-use payment is VAT-treated symmetrically with grid import.

@dataclass(frozen=True)
class CostRecoverySolution:          # the W3 ranking object + board headline
    own_use_rate_pence_per_kwh: float        # the SOLVED minimum rate (clamped to [0, retail])
    outlay: BillDistribution                 # householder total-outlay distribution at the solved rate
    representative_outlay_gbp: float         # == outlay.representative.total_outlay_gbp (W3 PRIMARY KEY)
    net_surplus_per_home_per_year_gbp: float # == retained floor at the solved rate (boundary, exact),
                                             #   or > floor when the rate is clamped to 0 (over-feasible)
    saving_vs_baseline_gbp: float            # representative saving at the solved rate
    saving_pct: float
    feasible: bool                           # True iff some rate in [0, retail] clears the floor
    binding: str                             # 'floor' | 'rate_clamped_zero' | 'infeasible_above_retail'
```

`BillDistribution` (finance.py:92–117) is reused; its `representative` is the **median-`total_outlay`**
home and `per_home_net_bill_gbp` becomes the per-home **total-outlay** tuple (field role redefined; name
may be retained for back-compat or renamed in T3 — tactical, §12).

### 3.2 CBS revenue — fixed in place — `project_multi_year`

In `_simulate_age` (finance.py:864–877), replace the retail-valued self-consumption term with the
**own-use + SEG + flex** CBS revenue, reusing energy aggregates already computed:

```python
own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc / 100.0      # fleet_sc already computed
seg_revenue     = sum(b.seg_export_income_gbp for b in bills)                # SEG to CBS (export MPAN)
flex_income     = finance.flex_income_per_battery_kwh_per_year_gbp \
                  * sum(h.battery_config.capacity_kwh for h in homes if h.battery_config)
fleet_revenue   = own_use_revenue + seg_revenue + flex_income                # the new CBS revenue
```

`YearPoint.fleet_revenue_gbp` now means **CBS revenue** (own-use + SEG + flex), not the retail-valued
self-consumption proxy. Energy quantities on the curve are unchanged. **`project_economics` is not
touched** — it keeps consuming `curve.points[y].fleet_revenue_gbp`.

### 3.3 Householder outlay — redefined in place — `householder_bill` / `bill_distribution`

`householder_bill` keeps its annualisation + physics/override switch (finance.py:170–249) but emits the
**cost-recovery `BillBreakdown`** of §3.1: `total_outlay = (grid_import + standing + own_use_payment) ×
(1+vat)`, **no SEG credit**, real saving `= self_consumed × (retail − own_use) × (1+vat)`. The clean
algebraic identity (the board-checkable one): **`saving_vs_baseline = self_consumed × (retail − own_use)
× (1+vat)`** — the householder saves exactly the retail↔own-use gap on every self-consumed kWh.
`bill_distribution` (finance.py:636) maps it and selects the **median-total-outlay** representative.

### 3.4 The cost-recovery solve — `solve_cost_recovery_rate`

```python
def solve_cost_recovery_rate(
    scenario: ScenarioConfig, finance: FinanceConfig, *, simulate=None,
) -> CostRecoverySolution: ...
```

Find the **minimum own-use rate** such that **CBS mean surplus per home/yr ≥
`retained_cash_floor_per_home_per_year_gbp`** over the asset life. CBS surplus is **linear in the
own-use rate** (`surplus(r) = r × Σ_y fleet_sc_y/100 / (N_years·n_homes) + (SEG + flex − opex − debt
averaged)`), so this is a **near-closed-form solve, not a search**: evaluate
`project_economics(project_multi_year(...))` at two trial rates (or read the energy curve directly and
recompute revenue analytically via `dataclasses.replace` on `YearPoint`s — no re-sim), fit the line,
solve `surplus(r*) = floor`, then **clamp `r*` to `[0, retail_baseline_rate]`** and set `binding`:
- `r* ∈ (0, retail]` → `binding='floor'`, surplus == floor exactly.
- `r* < 0` → config over-clears the floor even at free own-use → `binding='rate_clamped_zero'`, `r*=0`,
  surplus > floor (reported).
- `r* > retail` → config cannot clear the floor even charging full retail → `feasible=False`,
  `binding='infeasible_above_retail'` (W3 flags/excludes it).

`representative_outlay_gbp` (median-home total outlay at `r*`) is **the number W3 ranks by**.

### 3.5 Surface — CLI + report

- `cli/finance.py`: add `--cost-recovery/--no-cost-recovery` to `finance run`. When set, run the solve
  and render the solved own-use rate + householder total-outlay distribution + CBS surplus (= floor) +
  feasibility flag. (`--project` continues to render `project_economics` at the *configured* own-use
  rate; `--cost-recovery` renders the *solved* rate.)
- `output.py`: a cost-recovery block in `generate_finance_report` (solved rate, outlay distribution,
  surplus vs floor, saving %, feasibility).

### 3.6 Human-readable finance-model doc (Leo's requirement — the written spec)

`docs/cost-recovery-finance-model.md` — a board-readable explanation that is **the authoritative spec
the adversarial gate verifies against**. Contents: the CBS ownership model; the own-use lever; the
householder-outlay equation; the CBS-revenue equation; the cost-recovery solve + feasibility cases; the
capex→debt→required-own-use→outlay **coupling**; a **worked [FEAS] reconciliation** (flex=0 → solved
rate ≈ 15p → surplus = £27 floor → saving ≈ £324); and the flex seam + its unit basis. Every equation is
stated so a board member can reproduce a config's numbers by hand.

### 3.7 Adversarial code↔doc verification gate (Leo's requirement — final acceptance)

A **final gate task**: an agent (or agent team) **adversarially verifies that the implemented `finance.py`
arithmetic and the rendered report match `docs/cost-recovery-finance-model.md` exactly** — every equation
in the doc traces to code; every load-bearing code path / constant traces to the doc (no unmodelled term,
no undocumented magic number); and the doc's worked example reproduces to the penny against a live run.
It emits a **fidelity report**; any discrepancy is a **blocking** finding. This gate is what makes "the
board can trust these numbers" true. (Decompose note: this is an agent-team/review-style task, not a
standard TDD leaf — see §10 CR7 + the decompose hand-back.)

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| PRD packaging | **New focused PRD** `cost-recovery-householder-billing.md` (not appended to W2) | Fresh task batch + own manifest; W2 stays `done`/merged. *(Leo, 2026-06-17)* |
| Revenue defect | **Fix-in-place + recalibrate** (redefine `project_multi_year` CBS revenue + `householder_bill` outlay; re-derive the affected physics-path tests) | One coherent revenue/bill definition rather than a labelled-legacy double-count path. θ hard gate unaffected (§2.2). *(Leo, 2026-06-17)* |
| Householder concept | **Redefine `BillBreakdown` to the cost-recovery outlay** (single concept); `baseline_bill_gbp` stays the all-grid-at-retail counterfactual | The old free-self-consumption + SEG-to-householder framing *is* the defect; one householder model is the coherent fix. |
| Calibration anchor | **flex=0 anchor (corrects the brief).** `solve(floor=£27, flex=0)` ≈ 15p → saving ≈ £324 reproduces [FEAS] (**reported**, tolerance). Hard-assert structural props. **Separately** show Central flex lowers the solved rate. | [FEAS]'s £27 is a **no-flex** figure (income £653 = self-consumption + export only). Asserting £27 *with* Central flex is a false premise (surplus would be far higher). *(Leo confirmed, 2026-06-17)* |
| Flex-income field | **Per battery-kWh**: `flex_income_per_battery_kwh_per_year_gbp = 28.0` → CBS revenue | Gives W3 per-config sensitivity (battery size moves flex income). Default ≈ Central £280/battery-home ÷ 10 kWh. *(Leo, 2026-06-17)* — non-linearity caveat §12. |
| Solve method | **Near-closed-form** (surplus linear in own-use rate; clamp `[0, retail]`; feasibility flag) | Exact, deterministic, cheap; surplus = floor by construction. |
| Solve target | **Mean `net_surplus_per_home_per_year_gbp` ≥ floor** over asset life (the field W3/`project_economics` already expose) | Matches the [FEAS] "£27/home/yr" framing and the existing dataclass. Per-year-minimum is a tactical alternative (§12). |
| θ compatibility | **Hard θ assertions stay green** (spreadsheet-curve path); **physics column re-derived/reported** | The fix never enters the hard-asserted path (§2.2). |
| Acceptance | **Adversarial code↔doc gate** is the final, blocking deliverable | Board-trust requirement. *(Leo, 2026-06-17)* |

## 5. Pre-conditions for activating

- **W2 finance layer landed** (#43–#49 `done`): `householder_bill`, `bill_distribution`,
  `project_multi_year`, `project_economics`, `FinanceConfig`, `spreadsheet_revenue_curve`, the finance
  CLI + `generate_finance_report`. Verified in code. No re-fix of #2 pricing / P3 degradation.
- **W1 flex-income values**: cross-PRD seam (G4). W2 ships the **field it owns** with the **Central
  per-kWh default (£28.0)**; W1 supplies the Low/Central/High per-kWh values when it lands. Until then
  the default holds (a wired seam, not a fiction).
- All other substrate exists (§6). Novel substrate is produced within this batch, each consumed by a
  named downstream task or the CLI/board surface.

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `FinanceConfig` frozen + appended-default fields + `__post_init__` validation pattern | grep:`config.py:478–572` wired |
| `_parse_finance_config` parses the `finance:` block (extend for 3 new keys) | grep:`cli/finance.py:18` + `config.py` `_parse_finance_config` wired |
| `project_multi_year` `_simulate_age` computes `fleet_sc`/`fleet_exp`/per-home `bills` (the revenue line to fix) | grep:`finance.py:859–877` wired |
| `project_economics` consumes `curve.points[y].fleet_revenue_gbp` only; **unaffected** by curve-build change; arithmetic tests use synthetic curves | grep:`finance.py:1262` + test_finance_economics.py:27–36 wired |
| `MultiYearCurve.points[y].{fleet_self_consumption_kwh,fleet_export_kwh}` available for the analytic solve | grep:`finance.py:100–110` wired |
| `householder_bill` annualisation + physics/override switch (extend to cost-recovery outlay) | grep:`finance.py:170–249` wired |
| `bill_distribution` maps `householder_bill`, selects median representative, returns `BillDistribution` | grep:`finance.py:636–685` wired |
| `scenario.seg_tariff_pence_per_kwh` + per-home SEG already priced into `seg_export_income_gbp` | grep:`finance.py:855,875` + `home.py:333–344` wired (#2, landed) |
| Resolved fleet homes expose `battery_config.capacity_kwh` (for flex = Σ kWh × rate) | grep:`finance.py:888–896` wired |
| finance CLI `run` + `--project` flag pattern + `generate_finance_report` (extend with `--cost-recovery`) | grep:`cli/finance.py:46–206`, `output.py` `generate_finance_report` wired |
| θ hard gate isolated from physics path (`spreadsheet_revenue_curve → project_economics`) | grep:`tests/integration/test_finance_calibration.py:397–591` wired |
| `[FIN]`/`[FEAS]` golden references for the reconciliation anchor | `docs/finance-spreadsheet-reconciliation.md` + survey §3 |

**Novel substrate introduced (queued within this batch, not assumed):** three `FinanceConfig` fields;
`BillBreakdown` cost-recovery fields; `CostRecoverySolution`; `solve_cost_recovery_rate`; the fixed
`project_multi_year` revenue line; the `--cost-recovery` CLI + report block; `docs/cost-recovery-finance-model.md`;
the adversarial gate. Each produced by a named task (§10), consumed by a named downstream task / the CLI
/ W3 / the board doc. **G3 verdict: PASS.**

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **W2** (financial layer, `finance.py`) | **amends** | redefines `project_multi_year` CBS revenue + `householder_bill` outlay; reuses `project_economics`/`bill_distribution`/CLI unchanged; θ hard gate preserved | **this PRD owns** the redefinition; W2 stays `done` | landed; amended here |
| **W1** (flexibility value) | **consumes values** | W2 **owns** `flex_income_per_battery_kwh_per_year_gbp` (the field); **W1 produces** Low/Central/High **per-kWh** values; W2 consumes through the field. Default £28.0 ≈ Central £280/battery-home ÷ 10 kWh until W1 lands. **Unit note:** if W1 publishes per-battery-**home** bands, convert by the representative battery size; the W1 brief states this mirror. | **W2 owns the field; W1 owns the value** | W1 authored concurrently (2026-06-17); seam declared here |
| **W3** (discrete install-config sweep) | **consumed-by** | W3 ranks configs by `CostRecoverySolution.representative_outlay_gbp` (primary), flags `infeasible_above_retail` configs; reads `solve_cost_recovery_rate` read-only. **W3 re-spec** (post-this-PRD) replaces its year-1-net-bill objective + two-axis Pareto with the **solved-outlay rank + feasibility flag** (the "two axes are illusory" insight). | **this PRD owns** the solve signature; W3 references it as a dependency | W3 decompose **resumes after** W1 + this PRD land (sequence W1 → W2-amendment → W3) |
| `cli/main.py` / `output.py` / `config.py` | **co-tenant** | additive `--cost-recovery` option + report block + 3 config fields; disjoint from W2/W3 symbols | this PRD owns its additions | additive |

**No reciprocal-ownership fight.** W2-amendment unilaterally owns the finance contract (the
`FinanceConfig` fields, the cost-recovery bill/solve functions, the fixed revenue). W1 owns only the
flex **value**. W3 consumes the solve read-only. The board doc + CLI are themselves named consumers, so
**G1 holds independent of W1/W3**.

## 8. G5 note — why B + H + adversarial gate

Stakes on four axes: (1) **board-facing numbers** drive a real Phase-1 install-spec + £750k share-offer
decision; (2) a **cross-PRD consumer** (W3) imports the solve signature; (3) this **redefines the
householder bill** — a load-bearing mechanism; (4) **blast radius across `finance.py`/`config.py`/
`output.py`/`cli/` + recalibrated tests**. → **B** (the §3.1 data model + §3.2–3.4 signatures/invariants
are the written contract every leaf binds to) **+ H** (two-way boundary tests, §9) **+** the
**adversarial code↔doc acceptance gate** (§3.7) that no standard test gives: independent confirmation
that the implementation *is* the documented model.

**Invariants (B):** `solve` is pure/deterministic given (scenario, finance, simulate); surplus is linear
in the own-use rate; at `binding='floor'`, `net_surplus_per_home_per_year_gbp == floor` exactly;
`saving_vs_baseline = self_consumed × (retail − own_use) × (1+vat)`; `total_outlay` excludes SEG;
own-use rate is monotone non-decreasing in capex (fixed energy mix); θ hard assertions unchanged.

## 9. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|
| H1 | **Solve hits the floor exactly** | injected fast fleet; `binding='floor'` regime | `net_surplus_per_home_per_year_gbp == retained_cash_floor` to ε; recomputing `project_economics` at the solved rate reproduces it |
| H2 | **Capex→own-use coupling (the headline)** | two configs, higher-capex one | higher-capex config has **higher solved own-use rate** AND **higher `representative_outlay_gbp`** (fixed energy mix) — the coupling, observable |
| H3 | **Householder-saving identity** | a home at own-use `r` vs baseline | `saving_vs_baseline == self_consumed × (retail − r) × (1+vat)` to ε; `total_outlay` has **no** SEG term; `r = retail` ⟹ saving == 0 |
| H4 | **Feasibility clamps** | a runaway-cheap config and a runaway-expensive one | over-feasible ⟹ `binding='rate_clamped_zero'`, `r==0`, surplus ≥ floor; under-feasible ⟹ `feasible==False`, `binding='infeasible_above_retail'` |
| H5 | **CBS-revenue fix** | injected fleet through `project_multi_year` | `YearPoint.fleet_revenue_gbp == own_use×self + seg + flex` (not retail self-consumption saving); flex == `Σ battery_kwh × rate` |
| H6 | **[FEAS] reconciliation (reported, flex=0)** | [FIN]/[FEAS] assumption inputs, flex=0, floor=£27 | solved own-use rate ≈ 15p and saving ≈ £324 **within documented tolerance** (REPORTED, not hard-pinned); Central flex run shows a **lower** solved rate (value to householder) |
| H7 | **θ stays green** | the W2 calibration suite | `capex==£775,000±£1`, `min_dscr≥1.20`, `equity_irr>0` unchanged; physics column re-derived/reported |
| H8 | **CLI end-to-end (G2 surface)** | `finance run --cost-recovery scenarios/bristol-phase1.yaml` | prints solved own-use rate + householder total outlay (rep + distribution) + CBS surplus = floor + feasibility; real-PVGIS variant marked `slow` |

## 10. Decomposition plan

Seven tasks. **File-lock discipline:** `config.py` finance fields by **CR1** (disjoint region from
`_parse_battery_config`); `finance.py` by the serialised chain **CR2 → CR3 → CR4**; `output.py` +
`cli/finance.py` by **CR5**; `docs/` + calibration test by **CR6**; the adversarial gate **CR7** reads
everything, edits nothing. Per-task tests in distinct modules.

#### CR1 — `FinanceConfig` cost-recovery fields + parser
- **Modules:** `config.py` (+ `tests/unit/test_config.py`)
- **Work:** add `own_use_rate_pence_per_kwh=15.0`, `retained_cash_floor_per_home_per_year_gbp=27.0`,
  `flex_income_per_battery_kwh_per_year_gbp=28.0` (all `>= 0`, validated in `__post_init__`); parse the
  three keys in `_parse_finance_config`.
- **Signal (G2):** a `finance:` block with the three keys round-trips into `FinanceConfig`; negative
  values raise `ConfigurationError`; omission ⟹ the documented defaults; existing finance YAMLs
  unchanged.
- **Classification:** intermediate — unlocks CR2/CR3/CR4.

#### CR2 — CBS-revenue fix in `project_multi_year`
- **Modules:** `finance.py` (`_simulate_age` revenue line) (+ recalibrate `tests/unit/test_finance_projection.py` injected-revenue assertions)
- **Work:** `fleet_revenue = own_use_rate×fleet_sc/100 + Σ seg_export_income + flex` (§3.2); redefine
  `YearPoint.fleet_revenue_gbp` docstring to "CBS revenue."
- **Signal (G2/H5):** injected-fleet `fleet_revenue_gbp == own_use×self + seg + flex`; θ hard assertions
  green (H7).
- **Prereqs:** CR1.

#### CR3 — `householder_bill` → cost-recovery outlay
- **Modules:** `finance.py` (`householder_bill`, `BillBreakdown`, `bill_distribution`) (+ recalibrate `tests/integration/test_finance_bill.py`)
- **Work:** redefine `BillBreakdown` (§3.1): add `own_use_payment_gbp`/`total_outlay_gbp`, real saving,
  drop SEG credit; `bill_distribution` keys on median `total_outlay`.
- **Signal (G2/H3):** bill run shows total outlay = (import+standing+own-use)×(1+vat), no SEG; saving ==
  self×(retail−own_use)×(1+vat); own-use ↑ ⟹ outlay ↑ / saving ↓; `r==retail` ⟹ saving == 0.
- **Prereqs:** CR1.

#### CR4 — cost-recovery solve (leaf)
- **Modules:** `finance.py` (`CostRecoverySolution`, `solve_cost_recovery_rate`) (+ `tests/unit/test_cost_recovery_solve.py`)
- **Work:** near-closed-form linear solve (§3.4); clamp `[0, retail]`; feasibility/`binding` flags;
  `representative_outlay_gbp`.
- **Signal (G2/H1/H2/H4):** solved rate drives surplus == floor exactly; higher-capex ⟹ higher solved
  rate + outlay; clamp/infeasible flags correct; deterministic.
- **Prereqs:** CR2 (CBS revenue), CR3 (outlay).

#### CR5 — `finance run --cost-recovery` CLI + report block (leaf, G2 surface)
- **Modules:** `cli/finance.py`, `output.py` (+ `scenarios/`, `tests/integration/test_cost_recovery_cli.py`)
- **Work:** `--cost-recovery/--no-cost-recovery` flag; cost-recovery block in `generate_finance_report`
  (solved rate, outlay distribution, surplus vs floor, saving %, feasibility).
- **Signal (G2/H8):** `finance run --cost-recovery scenarios/bristol-phase1.yaml` prints the board-readable
  cost-recovery report; real-PVGIS variant `slow`.
- **Prereqs:** CR4.

#### CR6 — [FEAS]/[FIN] reconciliation calibration + human-readable model doc
- **Modules:** `tests/integration/test_cost_recovery_calibration.py`, `docs/cost-recovery-finance-model.md`
- **Work:** the flex=0 anchor (§4): hard-assert structural props (H1/H2 on the [FIN]-aligned fleet);
  **report** solved rate ≈ 15p / saving ≈ £324 within documented tolerance; demonstrate Central-flex
  lowers the solved rate; write the board-readable model doc (§3.6) whose worked example matches the run.
- **Signal (G2/G6/H6):** calibration report shows the flex=0 reconciliation (reported) + the structural
  asserts (hard); θ stays green; the doc's worked example reproduces a live run.
- **Prereqs:** CR4, CR5.

#### CR7 — adversarial code↔doc verification gate (acceptance, blocking)
- **Modules:** `review/` (a fidelity report; reads `finance.py` + `docs/cost-recovery-finance-model.md` + a live run; edits nothing)
- **Work:** an agent (or agent team) adversarially verifies every doc equation ⟺ code, no unmodelled
  term / undocumented constant, worked example reproduces to the penny (§3.7). Emits a fidelity report;
  any discrepancy is a blocking finding routed back to CR2–CR6.
- **Signal:** a filed fidelity report stating code ≡ documented model (or an itemised discrepancy list
  that blocks acceptance).
- **Prereqs:** CR1–CR6. *(Decompose note: file as an agent-team/review-style task, not a TDD leaf — see
  hand-back.)*

> **Note for decompose-time:** orchestrator does not yet consume `user_observable_signal` /
> `consumer_ref` / substrate-confirmed metadata — recorded for a future tracking session. Keep
> `mypy --strict` green. Mark real-PVGIS tests `slow`. **Recalibrated tests** (CR2 projection-revenue,
> CR3 bill) re-derive pinned numbers under the new model — this is expected, not a regression. **θ
> hard assertions must stay green throughout.** W3 decompose stays gated until W1 + this batch land.

## 11. Out of scope

- **W3's sweep re-spec** — ranking by the solved outlay + feasibility flag; consumes this PRD's solve, a
  separate session (sequence W1 → W2-amendment → W3).
- **W1's flex-value derivation** — W2 owns only the field; W1 produces the per-kWh values.
- **Web exposure** of the cost-recovery report — engine + CLI + doc only here.
- **Per-timestep / arbitrage physics for the flex value** — flex is a per-battery-kWh £/yr input
  (W1-owned), not modelled in dispatch here.
- **The CBS-supply VAT regulatory determination** (is self-consumed CBS-owned generation VATable / does
  the class-exemption route zero-rate own-use?) — a regulatory question (survey §7); `vat_rate` +
  symmetric own-use VAT keep both treatments expressible.
- **Per-year-minimum surplus financeability** (vs the mean used here) — DSCR already covers loan-year
  coverage; a min-year retained-surplus target is a tactical extension (§12).

## 12. Open questions (tactical — deferred, not design-blocking)

1. **Flex per-kWh non-linearity.** W1 (§1.1) warns flex value does not scale linearly with battery
   capacity (arbitrage vs self-consumption contend for the same kWh). The per-kWh field is a modelling
   convenience for per-config sensitivity; revisit whether a per-battery-home or capped-per-kWh form is
   better once W1's per-kWh bands land. The field set supports either via the default.
2. **Own-use VAT treatment.** Default applies `vat_rate` to the own-use payment (symmetric with grid
   import). Confirm against the class-exemption supply route (own-use may be 0%-rated). Affects the
   exact saving but not the model shape.
3. **Solve target: mean vs min-year surplus.** Mean `net_surplus_per_home_per_year_gbp ≥ floor` is used
   (matches [FEAS] + the existing dataclass). A min-year retained-surplus target is more conservative;
   decide with the board which the £27 floor means.
4. **`BillDistribution.per_home_net_bill_gbp` naming.** Its role becomes per-home total-outlay; keep the
   name for back-compat or rename in CR3. Tactical.
5. **Reconciliation tolerance (CR6).** The ≈15p / ≈£324 anchor is assumption-dependent (physics
   self-consumption ~30–52% vs [FEAS]'s 90%); set the reported tolerance when the [FIN]/[FEAS] inputs
   are wired, erring toward method-agreement not digit-equality (mirrors θ's latitude).
6. **Adversarial-gate mechanics (CR7).** Whether the fidelity gate runs as a `/review`-style task, a
   multi-agent workflow, or a scripted equation-by-equation check — the decompose session picks the
   filing form; the deliverable (a blocking fidelity report) is fixed.

## 13. G6 — premise validity of the asserted signals

- **"Solved rate drives CBS surplus to exactly the floor" (H1):** by construction — surplus is linear in
  the own-use rate (closed-form), so `surplus(r*) = floor` holds to numerical ε. **Producible by CR4.**
- **"Higher-capex ⟹ higher required own-use rate / higher outlay" (H2):** structural — more capex ⟹ more
  debt service ⟹ larger negative offset in `surplus(r)` ⟹ larger `r*` to reach the floor (energy mix
  fixed). Monotone by the solve's algebra; re-checked on synthetic configs. **Producible by CR2+CR4.**
- **"Saving = self × (retail − own_use) × (1+vat)" (H3):** algebraic identity from the outlay definition
  (the import and standing terms cancel against the baseline; only the self-consumed kWh re-priced from
  retail to own-use remains). **Producible by CR3.**
- **"≈£27 surplus / ≈£324 saving at own-use ≈15p, flex=0" (H6):** **REPORTED**, not hard-pinned —
  assumption-dependent (physics self-consumption ≠ [FEAS]'s 90%), so reproduced **within a documented
  tolerance** under the spreadsheet-assumption path, mirroring θ's "assert the achievable, report the
  rest" latitude. The **flex=0** framing corrects the brief's internally-inconsistent "15p + Central flex
  → £27" premise ([FEAS]'s £27 is a no-flex figure; Central flex would push surplus far higher or the
  solved rate far below 15p). **False premise avoided.**
- **Feasibility / clamp assertions (H4):** backed by the explicit clamp-to-`[0, retail]` + `binding`
  flag authored in CR4; observed by constructing over- and under-feasible configs. **Rejection-mechanism
  -backed.**
- **"θ hard assertions unchanged" (H7):** the fix never enters the `spreadsheet_revenue_curve →
  project_economics` path that the hard gate uses (§2.2); `project_economics` arithmetic tests feed
  synthetic curves. **Structurally preserved.**

**G6 verdict: PASS.**

## 14. META gate

> If this PRD is decomposed and queued without further oversight, will the architecture be complete,
> coherent, cohesive, and good?

**Yes.** Every mechanism has a named consumer (W3, the CLI, the board doc — G1); every leaf names a
user-observable signal (§10 — G2); every assumed substrate is verified present or produced in-batch
(§6 — G3); the W1/W3 seams have clean unilateral owners (§7 — G4); the high-stakes redefinition uses
B + H + an adversarial acceptance gate (§8/§9 — G5); every numeric/exactness/rejection premise is
validated, and the brief's one false premise (the £27-with-flex anchor) is corrected (§13 — G6). The
fix is coherent (one CBS-revenue definition, one householder-outlay definition, a closed-form solve), it
keeps the θ hard gate green, and it terminates in a human-readable model doc + an adversarial fidelity
gate that makes the board-trust property explicit. **No open design questions remain;** §12 items are
tactical/implementation-time.
