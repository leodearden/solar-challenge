# PRD — Board reports: one typed row source and one assumption mode per report

- **Program:** review-all-solar_challenge-20261013, stream **S25** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 3, size M, risk medium. Program upstream: S6, S10. Built on S8, S9, S16 and S19 by cross-reference.
- **Finding keys (9):** fk-2106d1fbaed0, fk-b7241e0ce122, fk-89afcb2b57f7, fk-f66948b9528c, fk-b523bff3e51c, fk-ae20e1833a19, fk-41767a1bc146, fk-ef13881623be, fk-6a52ed98b18e. §2.3 gives each key's disposition. Four keys get no leaf here, because a filed task already holds or has closed them.
- **Binding rulings:**
  - **D24.** Every computation (bills, solve, economics, events income) is rendered under both assumption modes, each labelled, and `generate_finance_report` takes sections keyed by mode.
  - **D12, D30, D31.** Annualisation and the standing charge; S10 owns them.
  - **D13, D41.** Capacity-at-events income per age, and its firmness; S9 owns them.
  - **D42.** The settlement basis; S3 owns it, and this PRD does no work for it.
  - **D34, D44.** Preset rates; S11 owns them, and this PRD does no work for them.
  - **D4, D29.** One coordinated surface bump. Additive edits land in-leaf; retirements are held for S29.
  - **D26.** fk-6a52ed98b18e is assigned to S25.
  - **D1.** `cli/finance.py` and `cli/optimize.py` belong to finance-economics.
  - **L9.** `aggregate_annual` is S10 γ2's (780) and leaves this stream's deletable list.
  - **L10.** S16 owns the age-0 simulations.
  - **L24.** S9 α′ is 837.
  - **L33.** S8's board figures.
- **Status:** authored 2026-10-17 by an author-only /prd session. Not committed and not decomposed. Decompose waits until the lead hands over the filed ids this batch depends on, S6's above all.
- **Approach:** B + H. The work touches 9 modules: a new `board_report`, `output`, `finance`, `projection`, `home`, `fleet`, the four CLI modules and the stored-run steps. It has 10 mechanisms and sits on seams of S6, S8, S9, S10, S16 and S19. So it carries a contract (§5) and a two-way boundary-test sketch (§9).
- **Code anchors** verified against main `dfcbde8` (2026-10-17). Main moves fast, so anchors cite symbols; re-locate lines at implementation time.
  - Changes since the findings' pin `7dfea36`, by file:
    - `output.py`: tasks 712 (`calculate_seasonal_metrics` sums the run's own per-minute amounts) and 743 (docstrings).
    - `cli/finance.py`: task 773's import only.
    - `cli/utils.py::create_summary_table`: unchanged.
    - `home.py`: task 710's split; `calculate_summary`'s SEG path is unchanged.
    - `fleet.py`: `FleetSummary` and `calculate_fleet_summary` are unchanged.
  - Two in-flight branches rewrite symbols this PRD builds on:
    - task 738's branch (in progress) rewrites `cli/finance.run`;
    - task 705's branch (pending after a merge retry) rewrites `create_summary_table`.

## 1. Goal

Every figure a board report prints says which self-consumption assumption it was computed under. Each assumption mode drives every computation of the report from its own finance configuration. The grid-services income appears beside the economics it changes, with the terms it was booked on. The board reports have a module of their own, `output.py` keeps per-run output, and one export-revenue figure remains where there were two.

What a user observes:

1. **Labels that tell the truth.** `finance run --assumptions spreadsheet` heads its value column "Spreadsheet (70% self-consumption)". Today it heads the override's figures "## Householder Bill (Physics Assumptions)": the finding's home pays £420.00 own-use under the override and £180.00 under physics.
2. **Every computation follows the mode.**
   - Under `--assumptions spreadsheet --project --cost-recovery`, the economics and the solved rate are the override's. Today they are computed on the scenario's raw finance block, which is physics unless the YAML sets an override.
   - Under `--assumptions physics` on `scenarios/bristol-fin-calibration.yaml`, whose finance block sets `self_consumption_override: 0.70`, the economics and the solve are physics. Today they are the override's.
   - `--assumptions both` renders the bill, the distribution, the economics, the cost-recovery solve and the outlay at the solved rate in two labelled columns. Today only the two bill tables have two columns.
3. **The events income sits with the economics.**
   - **The section.** `finance run --project` on an events scenario (`scenarios/bristol-phase1-flex.yaml`) renders a "Grid Services Income" section, even without `--flex-band`. It names:
     - the model, its band and its delivery baseline;
     - the income the projection booked in its first and last year under each mode;
     - for the bill run's fleet, the capacity available on 50% and 90% of event days and the evening self-use an event displaces, with the note that the income is gross of it.

     Today the event income appears only under `--flex-band`, nested in the flexibility block.
   - **The flex block.** With `--flex-band central`, the block's grid-services row shows the booked figure per battery home, about £3, instead of the consulting £30. Its headline follows. When a scenario books no grid services, the row says so.
   - **The report text** names no "PRD §6".
4. **`fleet run` shows its fleet's ratios and net cost.** The four rows it drops today come back, and no row is chosen by an attribute-name probe (task 705, re-scoped in place as α).
5. **One export-revenue figure.**
   - `home run --report` on a home with a 15 p SEG prints the SEG rate beside Grid Export Revenue, and no second "SEG Revenue" section.
   - `calculate_summary` and `calculate_fleet_summary` take no SEG rate, and `FleetSummary` carries no SEG pair.
   - A fleet run stored before the change still opens after `solar-challenge web migrate`.
6. **The structure says what it is.**
   - `board_report.py` holds the `finance run` and `optimize configs` reports, with one binding-label table and one formatter set, and `output.py` imports no finance, flex, grid-services or optimize type.
   - A cost-recovery solution whose binding is outside the vocabulary is refused by name. Today the finance report renders it INFEASIBLE and the ranking report prints the raw string.
   - The three dead ratio wrappers are gone.
7. **At the bump (held).** `SummaryStatistics.seg_revenue_gbp` is retired.

## 2. Background (measured at dfcbde8)

### 2.1 What exists today

- **`finance run`'s mode reaches two of five computations.** `--assumptions` reaches only the two `bill_distribution` calls. `project_multi_year`, `project_economics` and `solve_cost_recovery_rate` read the scenario's raw `finance`.
  - The spreadsheet-only branch passes its distribution into `generate_finance_report`'s first positional, `bill_physics`, which fixes the "Physics Assumptions" heading.
  - Task 738's branch, in progress, extracts helpers (`_bill_finances`, `_project_level_economics`, `_cost_recovery_solution`) and makes one report call over a (primary, spreadsheet) pair. It still passes the raw `finance` to the projection and the solve, and still puts the primary distribution in the `bill_physics` slot.
- **`generate_finance_report` is 220 lines.**
  - It has two near-identical bill templates, one single-column and one side-by-side, chosen by whether `bill_spreadsheet` is `None`.
  - Its economics and cost-recovery blocks have one column whatever the mode.
  - The binding label is an if/elif chain whose `else` renders any unknown binding as INFEASIBLE.
  - IRR, DSCR and payback are formatted inline, beside the `_fmt_irr`, `_fmt_dscr` and `_fmt_payback` the ranking report uses.
  - The capacity-at-events sub-section is nested under `if flex_band is not None`.
  - The flex block renders "(PRD §6)" into the board report, a pathless planning pointer. Task 765 changes only comments and docstrings (its AST check), so it leaves this rendered string alone. S27 offered it here.
- **`output.py` is 886 lines and serves two audiences.**
  - **Per-run output:** CSV export, the markdown summary report, seasonal metrics, period aggregation, and the community metrics and report.
  - **The two board reports:** `generate_finance_report` and `generate_config_ranking_report`. They are why `output.py` imports finance, flex, gridservices and optimize types under `TYPE_CHECKING`.
  - **Dead code:** `calculate_self_consumption_ratio`, `calculate_grid_dependency_ratio` and `calculate_export_ratio` have no caller in `src` (only `tests/unit/test_output.py`). `aggregate_annual` has none either, and S10 γ2 (780) deletes it.
  - **Restated code:** the ranking report writes the config label f-string four times. Its `_BINDING_LABELS` carries a comment claiming it is "reused from generate_finance_report", which it is not.
- **`create_summary_table` probes attribute names.** It takes `summary: Any` and makes 8 `hasattr`/`getattr` probes. `fleet run` drops the fleet's self-consumption ratio, grid dependency, net cost and SEG revenue rows.
  - Task 705's branch already replaces the probes with typed row builders in `cli/utils.py` (`home_summary_rows`, `fleet_summary_rows`, `_energy_total_rows`, `_money_rows`).
  - Its tests render a real `FleetSummary` (`tests/unit/test_cli_summary_tables.py`).
  - It is pending after one merge retry.
- **SEG export revenue has two representations.**
  - `SummaryStatistics.total_export_revenue_gbp` sums the per-minute export revenue `simulate_home` priced from `HomeConfig.seg_tariff`.
  - `SummaryStatistics.seg_revenue_gbp` (frozen form) is an independent recomputation from a `calculate_summary(…, seg_tariff_pence_per_kwh=)` argument, explained in a 20-line docstring. `FleetSummary.total_seg_revenue_gbp` and `per_home_seg_revenue_mean_gbp` (not frozen) aggregate it.
  - **Callers passing the rate:** `finance.py` 2 (S8 β and ζ remove them), `optimize._age0_baseline_outlay` 1 (S8 ζ deletes it), `output.generate_summary_report` and `aggregate_annual` 2, and `fleet.calculate_fleet_summary` 1.
  - **Readers in `src`:** the summary report's "## SEG Revenue" section, the CLI table's "SEG Revenue" row, and the fleet aggregation. `cli/home.py` carries an 8-line comment defending why it does not pass the rate.
  - **The platform:** it passes `seg_revenue_gbp=None` at 3 test sites (solar-challenge-platform, grep).
- **Stored runs.** `web/storage` saves a fleet run's `FleetSummary` as its summary JSON. S19 κ's strict reader refuses unknown keys, so removing a stored field needs a `RunDocumentStep` and a schema step (S19 C10).

### 2.2 Re-measurement

None of this stream's keys is weakened (D28 lists none of them). The freshness clause was applied per anchor (header). fk-ae20e1833a19's cognitive-complexity figures (41, 28, 22) are re-measured by β at its base and recorded on the task; complexipy is not installed in this checkout's environment.

### 2.3 Key dispositions (contract §8 step 1, run 2026-10-17 at authoring; re-run at decompose)

| key | step-1 result | this PRD |
|---|---|---|
| fk-2106d1fbaed0 | 705 `pending` (branch reviewed, merge retry) | α: task 705 re-scoped in place |
| fk-6a52ed98b18e | none | α (stamped on 705 at decompose) |
| fk-b7241e0ce122 | none | γ (modes), δ (events income) |
| fk-ae20e1833a19 | none | β; its heat-pump-block half goes to S12 δ by cross-reference (§13) |
| fk-ef13881623be | none | ε, and ζ (held) |
| fk-f66948b9528c | 738 `in-progress` | not filed; γ depends on 738 and finishes the mode half of the restructure 738 began |
| fk-89afcb2b57f7 | 703 `done`; re-read absent: the model doc names `finance run <scenario> --cost-recovery` at its overview and §9, and `render_cost_recovery_report` appears nowhere | not filed; closed by 703 |
| fk-41767a1bc146 | 712 `done`; re-read absent: `calculate_seasonal_metrics` sums the run's `per_minute_amounts()` | not filed; closed by 712 |
| fk-b523bff3e51c | 741 `pending` | not filed; 741 keeps it. S8 ζ (930) rewrites the sweep-count sentence, and §13 lists the other overlaps |

### 2.4 Tasks this PRD meets

- **Re-scoped in place:** 705 becomes α.
- **Depended on:**
  - task 738, task 765 and task 705;
  - S8: 922 (β), 925 (γ), 928 (δ), 929 (ε), 930 (ζ);
  - S9: 801, 802, 803, 837;
  - S10: 780 (γ2), 782 (ε), 783 (ζ);
  - S16: 882 (β), 890 (ε);
  - S19: 822 (κ);
  - S6's `cli/finance` reader leaf, not yet filed.
- **Overlapping files, no edge:**
  - 741 (cli prose);
  - 764 (`cli/finance.py` prose);
  - S12 δ 897 (`generate_summary_report`'s heat-pump section);
  - S27 α (`cli/fleet.py` community prose).

## 3. Rulings and how this PRD reads them

- **D24.**
  - **Columns.** The mode is a column, not a section heading: every table of the finance report has one value column per requested mode, headed by the mode's label.
  - **Input.** `generate_finance_report` takes a mapping from `finance.OwnUseBasis` to an `AssumptionSection`, whose figures were all computed under that mode's `FinanceConfig`.
  - **Events income.** The per-mode booked figures render in each mode's column. The breakdown of the bill run's fleet does not depend on the assumption, so it renders once and says so.
- **D12, D30, D31 (S10).** The bill bills over the summaries' own window (783). The report renders S10's extrapolation notice once, from the window every section shares (§5.3 R4). This PRD annualises nothing.
- **D13, D41 (S9).** The projection books grid-services income per simulated age (801, carried into S8 ε's node). δ renders the income the projection booked at its first and last age. Both are seed nodes, so both are exact node values. δ renders 837's breakdown with the delivery baseline named, which `GridServicesAtEvents` does not carry (S9 §5.10).
- **D4, D29.**
  - **Not frozen, so they land in-leaf:** the two board reports (`generate_finance_report` and `generate_config_ranking_report` are outside `__all__`), `calculate_summary`, `FleetSummary` and `calculate_fleet_summary`. They take Unreleased lines where a consumer could see them.
  - **Additive, outside `__all__`:** `own_use_basis` and `with_own_use_basis`.
  - **A retirement of a frozen form:** `SummaryStatistics.seg_revenue_gbp`, held as ζ.
- **D26.** fk-6a52ed98b18e is this stream's. α carries it.
- **L9.** `aggregate_annual` is deleted by 780; ε depends on 780 so that no SEG-rate caller survives in it.
- **L10.** S16's 890 wraps `finance run`'s simulator after the bill run. γ keeps the wrapper and simulates the bill run on the same resolved homes the projection ages, so the reuse matches under every mode.

## 4. Sketch of approach

1. **α (task 705).** Typed row builders per summary type; `create_summary_table` takes rows.
2. **β.** The two board reports move to `board_report.py` unchanged in output, behind one binding-label table and one formatter set. The dead ratio wrappers go.
3. **γ.** Mode resolution in finance. Report sections keyed by mode with a column per mode. `finance run` drives the bill, the projection, the economics and the solve per mode from one resolved fleet.
4. **δ.** The grid-services income renders with the economics, from the pricing value, the projection's booked node incomes and 837's breakdown. The flex block reads the booked figure.
5. **ε.** One export-revenue figure: `calculate_summary`, `calculate_fleet_summary`, `FleetSummary`, the summary report and the CLI table lose the second representation; a stored-run step drops the fleet pair.
6. **ζ (held for S29).** `SummaryStatistics.seg_revenue_gbp` is retired, with its stored-run step.

## 5. Contract

### 5.1 Mode resolution (`finance.py`; γ)

```python
def own_use_basis(finance: FinanceConfig) -> OwnUseBasis: ...
    # OwnUseBasis.OVERRIDE when finance.self_consumption_override is set, else OwnUseBasis.SIMULATED.
    # home_ledger (S8 γ) reads a ledger's basis through this function: one rule.

def with_own_use_basis(finance: FinanceConfig, basis: OwnUseBasis) -> FinanceConfig: ...
    # SIMULATED: self_consumption_override=None.
    # OVERRIDE: finance's own override, else DEFAULT_SPREADSHEET_SELF_CONSUMPTION (0.70).
    # Identity: own_use_basis(with_own_use_basis(f, b)) is b, for every f and b.
```

- Both are public names of `solar_challenge.finance`, outside `__all__`, beside `OwnUseBasis` and `DEFAULT_SPREADSHEET_SELF_CONSUMPTION`.
- The CLI's vocabulary does not change. `--assumptions physics|spreadsheet|both` maps to `(SIMULATED,)`, `(OVERRIDE,)` or `(SIMULATED, OVERRIDE)` through one table in `cli/finance.py`.

### 5.2 The report's input (`board_report.py`; γ creates, δ extends)

```python
@dataclass(frozen=True)
class AssumptionSection:
    """One assumption mode's figures, every one computed under `finance`."""
    finance: FinanceConfig                               # with_own_use_basis(the scenario's finance, the mode)
    bill: BillDistribution                               # bill_distribution(the bill run's summaries, finance, their days)
    projection: Optional[FleetProjection] = None         # the mode's projection, when the run projects (--project or --cost-recovery)
    economics: Optional[ProjectEconomics] = None         # project_economics(projection.curve, fleet, finance), under --project
    cost_recovery: Optional[CostRecoverySolution] = None # run_cost_recovery(fleet, finance).solution, under --cost-recovery

ASSUMPTION_LABELS: Mapping[OwnUseBasis, str]             # SIMULATED: "Physics"; OVERRIDE: "Spreadsheet"
                                                         # an OVERRIDE column reads "Spreadsheet (70% self-consumption)" from its section's override

def generate_finance_report(
    sections: Mapping[OwnUseBasis, AssumptionSection],
    *,
    scenario_name: str = "",
    grid_services: Optional[GridServicesIncome] = None,  # δ; None when the pricing books no grid services
    flex: Optional[FlexBlock] = None,                     # δ; today's flex_band and flex_band_name, after S9 γ's GridServicesBand
) -> str: ...
```

Refusals (`ValueError`, naming the values involved):

- **R1.** `sections` is empty.
- **R2.** A key is not `own_use_basis(section.finance)`.
- **R3.** The sections differ in which of `projection`, `economics` and `cost_recovery` they carry. No mode may lack a computation another mode has (D24).
- **R4.** The sections' bills were annualised from different windows (`BillDistribution.annualised_from`, S10 ε).

### 5.3 Rendering rules (γ, δ)

- **Columns.** Value columns follow `OwnUseBasis` order (`SIMULATED`, then `OVERRIDE`).
  - Every table carries one value column per section: the bill, the per-home distribution, the project economics, the cost-recovery analysis, the outlay at the solved rate and the booked grid-services rows.
  - A one-mode report is the one-column case of the same renderer. No heading names a mode.
- **The extrapolation notice** (S10 ζ's `_extrapolation_notice`, moved with β) renders once, under the title, from the window R4 makes common.
- **The binding label** comes from one table, `_BINDING_LABELS`, which both reports read. A binding outside the table's three keys raises `ValueError` naming it.
- **Formatting.** IRR, DSCR and payback format through `_fmt_irr`, `_fmt_dscr` and `_fmt_payback` in both reports, and one `_config_label` writes a config point.
- **Block order:**
  1. the bill;
  2. the distribution;
  3. the project economics;
  4. Grid Services Income (δ);
  5. the cost-recovery analysis;
  6. the outlay at the solved rate;
  7. the flexibility value.

### 5.4 Grid-services income (δ)

```python
@dataclass(frozen=True)
class GridServicesIncome:
    """What the scenario's grid-services pricing books on the bill run's fleet: the same under every assumption mode."""
    pricing: FlatGridServices | GridServicesEventsConfig  # S9 α's values; NoGridServices books nothing and has no section
    annual_income_gbp: float                              # pricing.annual_income_gbp(the bill run's FleetResults)
    battery_homes: int                                    # homes with a battery in that fleet
    battery_discharge_kw: float                           # Σ max_discharge_kw over them
    at_events: Optional[GridServicesAtEvents] = None      # 837's breakdown, set exactly when pricing is a GridServicesEventsConfig
    # __post_init__ (ValueError naming the values): at_events set under flat pricing, or missing under events pricing;
    # events income != at_events.annual_income_gbp; any figure negative or non-finite; income > 0 with no battery home.

class FleetProjection:                                    # S8 ε's type, in projection.py; δ adds one field
    grid_services_income_gbp: tuple[tuple[int, float], ...]
    # (age, £/yr) for every simulated node, ascending by age: the grid-services part of the node's
    # rate-independent income, as S8 ε's _simulate_node priced it through S9's annual_income_gbp.
```

The "Grid Services Income" section renders when `grid_services` is given. It holds:

1. **The model line.** For example "capacity at events, central band, operational delivery baseline", read from `pricing` (`band`, and 837's `delivery_baseline`), or "flat, £12.0/kW-yr".
2. **The booked rows, when the sections carry projections.** For each mode, the income at the projection's first simulated age (year 1) and at its last (year N). S8 ε's seeds always include ages 0 and L−1, so both are node values, never interpolations.
3. **This window's fleet, labelled "the same under every assumption".** It shows the annual fleet income. Under events pricing it also shows 837's rows: the capacity on 50% and 90% of event days, the evening self-use displaced per event and its value per year, and the note that the income is gross of it. This block is the capacity-at-events sub-section 837 renders, moved out of the flex block.

**The flex block (`flex` given):**

- **Grid-services row.** Under a pricing that books grid services it shows `annual_income_gbp / battery_homes` per home and `annual_income_gbp / battery_discharge_kw` per kW, labelled booked. Its headline is the time-shift figure plus that per-home figure. With no grid-services pricing the row shows the consulting band figure, labelled "consulting planning band, not booked: the scenario prices no grid services", and the consulting headline.
- **Doc pointer.** The rendered "(PRD §6)" becomes the document path, `docs/flexibility-buildability.md`.

### 5.5 `finance run` (γ, δ)

1. Read the scenario through S6's fleet-document reader. Resolve it once with S8's `projection.scenario_fleet`.
2. Build the runner through S16's `invocation(ctx).runner`.
3. Simulate the bill run on `FleetConfig(fleet.homes)` over `fleet.start` to `fleet.end`, then wrap the runner's `simulate` with S16's `fleet.reusing(…, bill_results, …)`.
4. Summarise the bill run once.
5. For each mode of `--assumptions`, build `with_own_use_basis(finance, basis)` and from it the mode's `AssumptionSection`:
   - the bill;
   - with `--cost-recovery`, one `run_cost_recovery(fleet, mode_finance, simulate=…)`, whose projection, economics (under `--project`) and solution the section carries;
   - with `--project` alone, `project_fleet` and `project_economics`.
6. Build `GridServicesIncome` from the pricing value (S9 β; `grid_services_model_of` until S9 ε) on the bill run's results (δ).
7. Make one `generate_finance_report` call.

No computation reads the scenario's raw `finance`. The bill run and every projection age the same resolved homes, so S16's reuse answers each mode's age-0 node on an unaged scenario.

### 5.6 One export-revenue figure (ε, ζ)

- **Removed in-leaf (ε):**
  - `calculate_summary`'s and `calculate_fleet_summary`'s `seg_tariff_pence_per_kwh` parameter, and the 20-line two-path docstring;
  - `FleetSummary.total_seg_revenue_gbp` and `per_home_seg_revenue_mean_gbp`;
  - `generate_summary_report`'s `seg_tariff_pence_per_kwh` parameter and its "## SEG Revenue" section;
  - the CLI table's "SEG Revenue" row;
  - `cli/home.py`'s rate threading for the report and its defence comment;
  - every remaining call that passes the rate at ε's base.
- **Kept:** the export revenue is `total_export_revenue_gbp`. The summary report's Financial table gains "SEG Rate", read from `results.pricing.seg_rate_pence_per_kwh` (S8 β), whenever a SEG rate priced the run.
- **Stored runs:** ε adds a `RunDocumentStep`, with its schema step, that drops the two `FleetSummary` keys from stored fleet summaries (S19 C10).
- **Transitional field.** Between ε and ζ, `SummaryStatistics.seg_revenue_gbp` stays on the frozen form, always `None`, and no `src` module reads it. Its docstring says it is retired at the program's surface bump.
- **ζ (held):** `SummaryStatistics.seg_revenue_gbp` is retired, with a `RunDocumentStep` dropping the key from stored home summaries and from a fleet run's per-home summaries. The consumer action is to drop the keyword (the platform's 3 test sites).

### 5.7 Typed summary rows (α, task 705)

`create_summary_table(rows: Iterable[tuple[str, str]], title)` renders rows in order. `home_summary_rows(SummaryStatistics)` and `fleet_summary_rows(FleetSummary)` build them by typed attribute access, sharing `_energy_total_rows` (the five energy totals) and `_money_rows`. They live in `cli/utils.py`, the presentation layer (§6 decision 7).

### 5.8 Invariants and where each is enforced

| # | Invariant | Construction | Use |
|---|---|---|---|
| I1 | Every figure in a mode's column was computed under that mode's `FinanceConfig` | `with_own_use_basis` builds it once per mode; `cli/finance` passes it to every call of that mode | R2; B7 |
| I2 | No mode lacks a computation another mode has | — | R3 |
| I3 | A report has one window | — | R4; one notice |
| I4 | A section's mode has one rule | `own_use_basis` | `home_ledger` and R2 read it; B5 |
| I5 | The grid-services figures a report prints come from the pricing the projection booked | `GridServicesIncome.__post_init__`; the node writes `grid_services_income_gbp` | the section and the flex block read only them; B10–B13 |
| I6 | A binding has one label | `_BINDING_LABELS` | both reports; an unknown binding is refused (B3) |
| I7 | SEG export revenue has one representation in `src` | ε removes the second; ζ the frozen field | grep checks; B14 |
| I8 | A stored run never names a field its dataclass lacks | ε's and ζ's `RunDocumentStep`s | S19 κ's strict reader; B15, B16 |
| I9 | A summary table's rows are chosen by type, not by attribute name | α's typed builders | mypy; B1 |

### 5.9 Surface ledger for S29 (D4)

| Leaf | Change | Release text and consumer action |
|---|---|---|
| β | `generate_finance_report` and `generate_config_ranking_report` move from `solar_challenge.output` to `solar_challenge.board_report` | Unreleased line; not frozen; the platform imports neither (grep) |
| γ | `generate_finance_report(sections, *, scenario_name, …)` replaces the `bill_physics`/`bill_spreadsheet` positionals; `finance.own_use_basis` and `finance.with_own_use_basis` are new | Unreleased line |
| δ | `FleetProjection.grid_services_income_gbp`; `GridServicesIncome` | Unreleased line |
| ε | `calculate_summary`, `calculate_fleet_summary` and `generate_summary_report` lose `seg_tariff_pence_per_kwh`; `FleetSummary` loses its two SEG fields | Unreleased line; the platform calls none of them with the rate (grep) |
| ζ (held) | `SummaryStatistics.seg_revenue_gbp` retired | release section: consumers drop the keyword (platform: 3 test sites); positional constructors past `strategy_name` shift by one |

## 6. Resolved design decisions

1. **The mode is the ledger's own-use basis.** S8 γ's `OwnUseBasis` already names the two ways a home's own-use is taken, and each `HomeLedger` records it. Keying the report by it gives the assumption one vocabulary from ledger to column. "Physics" and "Spreadsheet" stay as the board's labels, and the CLI keeps its flag values. A second enum in the report or the CLI would restate the same fact.
2. **One column per mode in every table, not one stacked section per mode.** Today's `--assumptions both` bill tables are already side by side, and the board reads them that way. Extending that layout to every table makes the comparison complete, and the one-mode report becomes the n = 1 case. That removes the two near-identical templates. A stacked layout would repeat every heading and make the comparison a page apart.
3. **Mode-free figures render once, labelled.** The bill run's events breakdown depends on the simulated batteries, not on the self-consumption assumption, so printing it twice would be noise. The figures the projection booked are rendered per mode, as D24 rules, even when they agree.
4. **The board reports move to `board_report.py`.** This goes beyond the stream row's "the helpers they sit beside", because fk-ae20e1833a19 is a heuristic-6 finding: `output.py`'s purpose needs "and" while it holds the board reports. The finding proposes a finance-report module.
   - **Why now.** γ rewrites `generate_finance_report` almost entirely, so moving it first costs a behaviour-preserving move and removes four `TYPE_CHECKING` imports from `output.py`.
   - **What stays.** `output.py` keeps per-run output (CSV, the summary report, seasonal and period aggregation, community metrics and report).
   - **Why not the alternatives.** A per-domain split (`finance_report`, `ranking_report`) would make two satellites that share the formatters and the label table.
5. **Booked income from node values at the first and last ages.** The projection interpolates revenue, not grid-services income, and S8 ε keeps it that way. Showing the two seed-node values the projection actually priced is exact and shows the board the decline with battery health that D41 reports. The alternatives:
   - an interpolated per-year series would invent figures between nodes;
   - a mean over the projection would need a new interpolated quantity;
   - the bill run's figure alone hides the decline.
6. **The flex block reads the booked figure.** Under events pricing, S9 requires it (its §8). Under flat pricing, the same rule gives the scenario's own rate rather than the consulting band's. With no pricing, the consulting figure stays but is labelled not booked. The report then never shows two grid-services figures without saying which one the economics use.
7. **Typed rows stay in `cli/utils.py`.** This amends the program's seam row, which names `SummaryStatistics` and `FleetSummary` as owners. The labels and formats ("Total Generation", "£", "%") are the CLI's. The markdown summary report and the web use other labels, so a rows method on the domain type would serve one reader and add presentation members to a frozen form. Typed attribute access in the builders gives the stated property: a renamed field fails mypy. Task 705's reviewed branch has this shape.
8. **Under `--assumptions both` the projection runs once per mode.**
   - **Why.** Node selection reads each mode's own-use, so the two projections may pick different trial ages. One projection driven by both modes' metrics would be an S8 contract change.
   - **The cost** is one more projection's node simulations, less the age-0 node S16's reuse answers on unaged scenarios.
   - **Sharing** node simulations across modes is a follow-up candidate (§12 lead question 4).
9. **One export-revenue figure, its rate read from the run.** `total_export_revenue_gbp` is what `simulate_home` priced and what finance reads (S8 β), so the recomputation goes. The report shows the rate the run was priced at from `RunPricing` (S8 β), not from a parameter the caller must keep in step.
10. **An unknown binding is refused.** The solve produces three bindings. Today one report silently prints INFEASIBLE for anything else, and the other prints the raw string. `CostRecoverySolution.binding` stays `str` (S8 decision 13, L33), so the refusal sits at the one label table.
11. **One resolved fleet for the bill and the projection.** The bill run simulates `scenario_fleet(scenario).homes`, the homes the projection ages. Without this, S16's reuse match rule would see a different SEG fill or time zone and re-simulate age 0 once per mode.

## 7. Pre-conditions and substrate (G3)

- **α:** none. Task 705's branch carries it.
- **β:** S10 ζ (783: the extrapolation notice in both reports), S9 α′ (837: the events rows), S8 ζ (930: the ranking header; and through it 928's report imports, 738, 890), and task 765 (`output.py` docstring pointers). β moves code those tasks edit, so it lands after them.
- **γ:** β; S8 ζ (930), and through it 925 (`OwnUseBasis`, `home_ledger`), 928 (`scenario_fleet`), 929 (`project_fleet`, `FleetProjection`) and 890 (`reusing`); S6's leaf that makes `cli/finance.run` read the scenario through the one reader (label from the lead).
- **δ:** γ; S9 γ (803: `GridServicesBand`); 837 and 802 through β and 928.
- **ε:** α (705); S8 β (922: `RunPricing`, `SummaryStatistics.pricing`); S10 γ2 (780: `aggregate_annual` deleted); S19 κ (822: `RUN_DOCUMENT_STEPS`).
- **ζ:** ε; 822; held for S29.

G3 substrate, verified at dfcbde8:

- **Surface status.**
  - `calculate_summary`, `FleetSummary`, `calculate_fleet_summary`, `generate_finance_report` and `generate_config_ranking_report` are on no frozen table (`__init__`, `FROZEN_SURFACE`, `FROZEN_CLOSURE`).
  - `SummaryStatistics` is frozen, and its form includes `seg_revenue_gbp`.
  - `FinanceConfig` has no `FROZEN_MEMBERS` entry.
- **Defaults.** `finance.DEFAULT_SPREADSHEET_SELF_CONSUMPTION` is 0.70.
- **Stored runs.** `web/storage` saves `FleetSummary` and reads it through `_deserialize_dataclass`.
- **Task 705's branch** defines `home_summary_rows` and `fleet_summary_rows`, and its tests build a real `FleetSummary`.
- **Scenarios.** `scenarios/bristol-fin-calibration.yaml` sets `self_consumption_override: 0.70`. `scenarios/bristol-phase1-flex.yaml` prices capacity at events and has 100 homes, each with a 5 kWh battery.
- **Producers filed upstream, not on main:** `OwnUseBasis`, `home_ledger`, `scenario_fleet`, `project_fleet`, `FleetProjection`, `run_cost_recovery` (S8 925, 928, 929, 930); `RunPricing` (922); `_extrapolation_notice` and `BillDistribution.annualised_from` (782, 783); the pricing values and `grid_services_model_of` (801, 802); `GridServicesAtEvents`' p50, p90 and displaced fields and `GridServicesEventsConfig.delivery_baseline` (837); `GridServicesBand` (803); `fleet.reusing` (890); `invocation(ctx).runner` (882); `RUN_DOCUMENT_STEPS` (822); S6's reader. Each sits upstream of the leaf that uses it (§10).

No other substrate is assumed.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S6 Fleet-document overlays | consumes | the one reader `cli/finance.run` calls instead of hand-building a `ScenarioConfig`; the scenario's `flex_band` | S6 | γ depends on S6's `cli/finance` leaf (label from the lead) |
| S8 Finance partition (922–936) | consumes | `OwnUseBasis` and `home_ledger` (925); `scenario_fleet` (928); `project_fleet`/`FleetProjection` (929); `run_cost_recovery` (930); `RunPricing` (922) | S8 | γ → β → 930; ε → 922 |
| S8 (925, 929) | extends | γ adds `own_use_basis` and `with_own_use_basis`, and `home_ledger` reads its basis through `own_use_basis`; δ adds `FleetProjection.grid_services_income_gbp`, filled by `_simulate_node` | S25 | after 925 and 929 (transitive) |
| S9 Grid services (801, 802, 803, 837) | consumes | pricing values and `annual_income_gbp`; 837's breakdown and `delivery_baseline`; `GridServicesBand` | S9 the values; S25 the rendering and per-mode placement (S9 §8) | δ → 803; 837 and 802 upstream of β and 928 |
| S10 Window (782, 783, 780) | consumes | `annualised_from`; `_extrapolation_notice`; `aggregate_annual` deleted | S10 the notice; S25 the sections that keep it | β → 783; ε → 780 |
| S16 Fleet execution (882, 890) | consumes | `invocation(ctx).runner`; `fleet.reusing` around the per-mode projections | S16 | through 930 |
| S19 Run store (822) | consumes | `RunDocumentStep` and schema step for the `FleetSummary` pair (ε) and `SummaryStatistics.seg_revenue_gbp` (ζ) | S19 the mechanism; S25 the steps | ε, ζ → 822 |
| S21 Charts (833) | shares | `SummaryStatistics`' three flow properties are available to the typed rows; S25 adds no row for them | — | no edge |
| S27 Community | consumes | the rendered "(PRD §6)" pointer it offered | S25 (δ) | no edge |
| S12 Load composition (897) | shares | `generate_summary_report`: S12 δ rewrites its heat-pump section and seasonal block; ε edits its Financial and SEG sections | each its own section | textual; §13 asks S12 δ to build its per-load seasonal tables on `calculate_seasonal_metrics`' aggregation (fk-ae20e1833a19's other half) |
| S29 Surface bump | produces for | §5.9; ζ held | S29 | held |
| S23 Surface lock | touches | ζ edits `SummaryStatistics`' `FROZEN_SURFACE` form | S23 | whichever lands second adapts |
| Task 705 | is α | typed rows | S25 | re-scoped in place |
| Task 738 | builds on | `cli/finance.run`'s helper extraction and one report call | 738 | γ depends on 738 (transitive through 930) |
| Task 741 | shares | cli prose: the sweep-count sentence (S8 ζ rewrites it), `cli/home`'s SEG defence (ε deletes it), `cli/fleet`'s task labels (S27 α), the "pre-CR5" item (S6 and γ delete the branch) | 741 keeps fk-b523bff3e51c | textual; §13 |
| Task 765 | precedes | `output.py` docstring pointers | 765 | β depends on 765 |

## 9. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| B1 | consumer: CLI | typed rows | a `FleetSummary` with every field set; a `SummaryStatistics` | the fleet table lists Self-Consumption Ratio, Grid Dependency and Net Cost (RED: the 9 rows of the finding's probe); the home tables are unchanged; `create_summary_table` makes no `hasattr` or `getattr` call | α |
| B2 | both: reports | the move preserves output | the fixtures of `tests/integration/test_cost_recovery_cli.py` and `test_optimize_cli.py`, and the finance-report tests | each report captured at β's base equals β's output | β |
| B3 | producer: labels | unknown binding refused | a `CostRecoverySolution` with `binding="other"` and `feasible=True` (constructible after S8 η); a `RankedSweep` carrying it | both reports raise `ValueError` naming `"other"` (RED: the finance report prints INFEASIBLE, the ranking report prints `other`) | β |
| B4 | layering | `output.py`'s purpose | the tree | `output.py` imports no `finance`, `flex`, `gridservices`, `optimize` or `projection` name; the three ratio wrappers and their tests are gone; `board_report.py` holds both reports | β |
| B5 | producer: finance | one mode rule | `FinanceConfig`s with override `None` and 0.6 | `own_use_basis(with_own_use_basis(f, b)) is b` for each f and b; `OVERRIDE` keeps 0.6 and fills `None` with 0.70; `SIMULATED` clears it; `home_ledger(…).basis == own_use_basis(finance)` | γ |
| B6 | consumer: CLI | the spreadsheet label | the finding's home (generation 4,000, demand 3,400, import 2,200 kWh; standing charge 60 p) through a fake simulator, `--assumptions spreadsheet` | the bill column is headed "Spreadsheet (70% self-consumption)", own-use payment £420.00, and "Physics" appears nowhere in the report (RED: "## Householder Bill (Physics Assumptions)") | γ |
| B7 | consumer: CLI | every computation follows the mode | a constant fake simulator; a finance block that solves feasibly | `--assumptions spreadsheet --project --cost-recovery`: the solved rate and the economics equal `run_cost_recovery(fleet, with_own_use_basis(finance, OVERRIDE), simulate=fake)` and differ from the physics run's (RED: equal to physics). `--assumptions physics` with `self_consumption_override: 0.70` in the YAML equals the physics run (RED: the override's) | γ |
| B8 | consumer: CLI | both modes, complete | as B7, `--assumptions both --project --cost-recovery`, counting simulator, unaged homes | the bill, distribution, economics, cost-recovery and solved-rate outlay tables each have two value columns, Physics then Spreadsheet (70% self-consumption); the simulator count satisfies count(both) − 1 == 2 × (count(physics) − 1) | γ |
| B9 | producer: report | section refusals | hand-built sections | an empty mapping; an `OVERRIDE` key over a section whose finance has no override; one section with economics and one without; bills annualised from two windows: each raises `ValueError` naming the values | γ |
| B10 | consumer: CLI | events income with the economics | the events fixture of `tests/integration/test_grid_services_events.py`, `finance run --project` without `--flex-band`; an injected simulate whose battery capacity falls with age | the report has a "Grid Services Income" section naming the model, the band and "operational"; 837's p50, p90 and displaced rows; the gross note; per mode, year-1 and year-N rows equal `projection.grid_services_income_gbp[0]` and `[-1]`, with year N below year 1 (RED: no grid-services text without `--flex-band`) | δ |
| B11 | consumer: CLI | the flex block reads the booked figure | B10's fixture with `--flex-band central`; a no-grid-services scenario with `--flex-band central` | the grid-services row is `annual_income_gbp / battery_homes` and the headline is time-shift plus it (RED: £30 and the consulting headline); the second scenario's row says "not booked"; "PRD §6" is absent from both reports | δ |
| B12 | producer: value | `GridServicesIncome` refusals | hand-built values | `at_events` under a flat pricing; an events pricing without `at_events`; an events income differing from `at_events.annual_income_gbp`: each raises naming the values | δ |
| B13 | producer: projection | the node income is populated | an injected simulate over ages 0, 12, 24 | `grid_services_income_gbp` has one entry per simulated node, ascending by age, and the age-0 entry equals `pricing.annual_income_gbp` of the age-0 `FleetResults` | δ |
| B14 | consumer: CLI, library | one export-revenue figure | a home with SEG 15 p over 2024-06-21 (synthetic weather) | `home run --report` shows "SEG Rate 15.0 p/kWh" and Grid Export Revenue, and no "## SEG Revenue" section (RED); `calculate_summary(results, seg_tariff_pence_per_kwh=15.0)` and `calculate_fleet_summary(fleet, seg_tariff_pence_per_kwh=15.0)` raise `TypeError`; `FleetSummary` has neither SEG field; no table prints "SEG Revenue" | ε |
| B15 | consumer: web | stored fleet run migrates | a fleet run directory saved at ε's base with the two keys (fixture) | after `solar-challenge web migrate` its results page renders and its summary JSON lacks both keys; the step is idempotent (S19 B15) | ε |
| B16 | surface (held) | the frozen field retired | after ζ | `SummaryStatistics(…, seg_revenue_gbp=None)` raises `TypeError`; `FROZEN_SURFACE` has no `seg_revenue_gbp`; a stored home run carrying the key loads after migrate | ζ |

δ is the integration gate for the board report. Its signal is B10 to B13, and rows B5 to B9 pass at its base.

## 10. Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`, priority equal to its highest key severity, and file-level `metadata.files`. γ and δ are high, so each joins trigger-chain gate 772 as a dependency.

**α — Summary tables are typed per summary type; `fleet run` prints its fleet's ratios and net cost** (task 705, re-scoped in place; leaf; medium; keys fk-2106d1fbaed0, fk-6a52ed98b18e)

- **Modules:** 705's files: `src/solar_challenge/cli/utils.py`, `cli/fleet.py`, `cli/home.py`, `tests/unit/test_cli_summary_tables.py`, `tests/unit/test_cli.py`.
- **Work:** §5.7, as 705's branch has it.
- **Signal (user-observable):** B1. `fleet run` prints Self-Consumption Ratio, Grid Dependency and Net Cost for its fleet (today they are missing), and `create_summary_table` probes no attribute name.
- **Consumer:** `home run`, `home quick` and `fleet run` users; ε (it drops the SEG row from `_money_rows`).
- **Prereqs:** none.

**β — The board reports live in `board_report.py` with one binding table and one formatter set; `output.py` is per-run output** (leaf; low; key fk-ae20e1833a19)

- **Modules:**
  - new `src/solar_challenge/board_report.py`: `generate_finance_report`, `generate_config_ranking_report`, `_extrapolation_notice`, `_BINDING_LABELS`, `_fmt_*`, `_config_label`;
  - `src/solar_challenge/output.py`: the reports and the three ratio wrappers removed, the `TYPE_CHECKING` imports of finance, flex, gridservices and optimize removed, and a purpose docstring;
  - `src/solar_challenge/cli/finance.py`, `src/solar_challenge/cli/optimize.py`: imports;
  - tests: `tests/integration/test_cost_recovery_cli.py`, `test_finance_bill.py`, `test_finance_economics.py`, `test_flex_timeshift.py`, `test_grid_services_events.py`, `test_optimize_cli.py` (imports); `tests/unit/test_output.py` (ratio tests deleted); new `tests/unit/test_board_report.py` (B3);
  - docs: `CLAUDE.md` (Output & Validation; Finance & Community Layer names `board_report.py`), `docs/cost-recovery-finance-model.md` (§9's heading and source), `docs/domain-library-consumption.md` (Unreleased line), and `review/briefing.yaml` (finance-economics member list, if member lists exist at β's base).
- **Work:**
  - Move the two reports unchanged in output.
  - The finance report's binding chain and inline formatting read the table and helpers. The ranking report's four config labels call `_config_label`. An unknown binding is refused.
  - Record on the task complexipy's per-function figures for the three report functions, before and after, read as a pair with the module totals (a measurement, not the signal).
- **Signal (user-observable):** B2–B4. `finance run --project --cost-recovery` and `optimize configs` print the same reports as before. A solution with an out-of-vocabulary binding is refused by name in both (today it prints INFEASIBLE in one and the raw string in the other). `output.py` imports no board-report type.
- **Consumer:** γ and δ (they rewrite the moved report); `finance run` and `optimize configs` users.
- **Prereqs:** 783, 837, 930, 765.

**γ — Each `--assumptions` mode drives every computation from its own finance configuration; the report is one column per mode** (leaf; high; key fk-b7241e0ce122)

- **Modules:**
  - `src/solar_challenge/finance.py`: §5.1; `home_ledger` reads `own_use_basis`;
  - `src/solar_challenge/board_report.py`: §5.2 without `grid_services`, §5.3;
  - `src/solar_challenge/cli/finance.py`: §5.5 steps 1–5 and 7;
  - tests: `tests/integration/test_finance_run_cli.py` (738's module), `test_cost_recovery_cli.py`, `test_finance_bill.py`, `test_finance_economics.py`, `test_flex_timeshift.py`, `test_grid_services_events.py` (report calls); new `tests/unit/test_board_report_sections.py` (B9); `tests/unit/test_finance_ledger.py` (B5);
  - docs: `docs/cost-recovery-finance-model.md` (§3's override path, the `finance run --assumptions spreadsheet|both` line; §9's rendered report with mode columns), `docs/domain-library-consumption.md`.
- **Work:** §5.1–§5.3 and §5.5. Record on the task the simulator counts of B8 at the leaf's base, and the board figures that move (§12 lead question 5).
- **Signal (user-observable):** B5–B9.
  - `finance run --assumptions spreadsheet` labels its column "Spreadsheet (70% self-consumption)" and prints no "Physics" (today "Physics Assumptions" over the override's £420.00).
  - Its economics and solved rate are the override's (today physics). On the calibration scenario's YAML override, `--assumptions physics` is physics (today the override's).
  - `--assumptions both` prints every block in two labelled columns.
- **Consumer:** `finance run` users (the board); δ.
- **Prereqs:** β; 930; S6's `cli/finance` reader leaf.

**δ — The grid-services income renders with the economics it changes, under its model, band and delivery baseline** (leaf, integration gate; high; key fk-b7241e0ce122)

- **Modules:**
  - `src/solar_challenge/board_report.py`: §5.4; the flex block's rows and doc pointer;
  - `src/solar_challenge/projection.py`: `FleetProjection.grid_services_income_gbp`, filled by `_simulate_node`;
  - `src/solar_challenge/cli/finance.py`: §5.5 step 6;
  - tests: `tests/integration/test_grid_services_events.py`, `test_finance_flex_cli.py`, `test_flex_grid_services.py`, `test_flex_timeshift.py`, `tests/unit/test_finance_projection.py` (B13);
  - docs: `docs/cost-recovery-finance-model.md` (§8.1: where the events income renders; §9), `docs/flexibility-buildability.md` (the report block's grid-services row), `docs/domain-library-consumption.md`.
- **Work:** §5.4. Record on the task the board fleet's booked year-1 and year-N figures and the flex row before and after, at the leaf's base.
- **Signal (user-observable):** B10–B13, with B5–B9 passing at its base.
  - `finance run --project` on the events scenario prints the Grid Services Income section without `--flex-band`, with the operational baseline, the 50% and 90% capacities, the displaced self-use and the year-1 and year-N booked figures per mode (today nothing without `--flex-band`).
  - With `--flex-band central`, the flex block's grid-services row shows the booked figure per battery home (today the consulting £30).
- **Consumer:** board readers of `finance run`.
- **Prereqs:** γ; 803.

**ε — One export-revenue figure: the SEG recomputation leaves the summaries, the reports and the CLI** (leaf; low; key fk-ef13881623be)

- **Modules:**
  - `src/solar_challenge/home.py` (`calculate_summary`'s parameter and docstring; `seg_revenue_gbp`'s docstring says it is transitional);
  - `src/solar_challenge/fleet.py` (`calculate_fleet_summary`; `FleetSummary`);
  - `src/solar_challenge/output.py` (`generate_summary_report`);
  - `src/solar_challenge/cli/home.py`, `src/solar_challenge/cli/utils.py` (`_money_rows`);
  - any caller still passing the rate at the base (`finance.py`, `projection.py`, `optimize.py`);
  - the S19 stored-run step module (`RUN_DOCUMENT_STEPS` and its schema step);
  - tests: `tests/unit/test_home.py`, `tests/unit/test_fleet.py`, `tests/unit/test_cli.py`, `tests/unit/test_cli_summary_tables.py`, `tests/unit/test_output.py`, `tests/_finance_builders.py`, `tests/unit/test_finance_builders_helper.py`, S19's step fixture tests (B15);
  - docs: `docs/domain-library-consumption.md`.
- **Work:** §5.6, in-leaf part.
- **Signal (user-observable):** B14, B15. `home run --report` on a 15 p SEG home prints the rate beside the one export revenue and no "## SEG Revenue" section (today a second, recomputed revenue). `calculate_summary` refuses the rate argument. A fleet run stored before ε opens after `web migrate`.
- **Consumer:** `home run` and `fleet run` users; library consumers of `calculate_summary`; ζ.
- **Prereqs:** α (705); 922; 780; 822.

**ζ — SummaryStatistics.seg_revenue_gbp is retired** (held leaf; low; key fk-ef13881623be; `metadata.x_seam_wait = {stream: "S29", contract: "the surface bump release window"}`; excluded from this batch's `commit_planning`)

- **Modules:** `src/solar_challenge/home.py`; `tests/unit/test_public_api_surface.py` (the form); the S19 stored-run step module; the tests that construct `SummaryStatistics` with the keyword (`tests/unit/test_home.py` and others found at the base); `docs/domain-library-consumption.md` (release text).
- **Signal (user-observable):** B16.
- **Consumer:** S29's release section; the platform re-pin (3 test sites drop the keyword).
- **Prereqs:** ε; 822; S29 releases it.

**DAG.**

- **In batch:** α → ε → ζ (held); β → γ → δ.
- **Out of batch:**
  - β → 783, 837, 930, 765;
  - γ → 930, S6's `cli/finance` leaf;
  - δ → 803;
  - ε → 705 (α itself), 922, 780, 822;
  - ζ → 822.
- **Gate:** gate 772 depends on γ and δ.

**G7** is advisory, because this repo has no `docs/legibility/design-invariants.md`. Screened against dark-factory's trigger shapes:

- `no-silent-fail-soft`:
  - an unknown binding is refused instead of rendered INFEASIBLE;
  - the report refuses sections that mix modes, lack a computation or span two windows;
  - a no-pricing flex row says "not booked" instead of presenting the consulting figure as booked.
- `one-fact-one-home`:
  - the mode rule (`own_use_basis`);
  - the binding labels (one table);
  - SEG export revenue (one figure);
  - the grid-services figures (from the pricing value and the node).
- `readers-prove-their-producer`: the booked rows read the node values the projection priced (B13 binds field population), and the breakdown reads 837's production fields.
- `holds-owned-and-bounded`: ζ is held with `x_seam_wait` S29. The transitional always-`None` `seg_revenue_gbp` has the same owner and bound.

No hit.

## 11. Out of scope

- **The scenario reader and the SEG-fill policy** (S6): `ScenarioConfig.homes()`/`with_seg()`, D10, D11's period policy for `finance run`, and the hand-built `ScenarioConfig` in `cli/optimize.configs`.
- **The projection's engine, the solve and their simulation counts** (S8), and the age-0 reuse (S16). Sharing node simulations across modes is §12 lead question 4.
- **Pricing models, firmness, the counterfactual event simulation** (S9 and its successor PRD).
- **The window rule and its notice text** (S10).
- **`generate_summary_report`'s heat-pump section and seasonal block** (S12 δ, 897).
- **`optimize configs`' function size** (fk-f66948b9528c's second half: cognitive 29) and its hand-built scenario (S6). This stream renders `optimize`'s report only.
- **Rows for S21's flow properties** in the CLI tables.
- **`CostRecoverySolution.binding` as an enum** (S8 decision 13, L33).
- **cli prose that task 741 and task 764 own.**

## 12. Open questions

**For the lead** (the design holds either way):

1. **Seam row "Typed summary rows."** The program names `home.SummaryStatistics` and `fleet.FleetSummary` as owners. §6 decision 7 puts the rows in `cli/utils.py`, where task 705's reviewed branch has them. **Default:** amend the row to "owner: `cli/utils` (`home_summary_rows`, `fleet_summary_rows`, task 705); readers `cli/home`, `cli/fleet`".
2. **Task 705 as α.** Re-scope it in place at decompose: description note, `prd_path`, `prd_task_label = α`, fk-6a52ed98b18e added to `x_finding_key`, signal and consumer. Re-read its status, claimant and branch right before. If 705 is `done` by then, stamp fk-6a52ed98b18e on it, drop α from the batch, and ε's edge is already satisfied. If it is cancelled, file α new from §10. **Default:** re-scope in place.
3. **Seam row "Report sections keyed by assumption mode."** β moves the owner. **Default:** amend to "owner: `board_report.generate_finance_report`; reader `cli/finance`".
4. **Cross-mode projection sharing.** Under `--assumptions both` the projection runs once per mode (§6 decision 8). Sharing node simulations would need S8's `run_cost_recovery` to drive node selection by several finance configurations at once. **Default:** not now; recorded in §Triage as a follow-up candidate after S8 ε (929).
5. **Board figures that move** (for Leo; each leaf records its exact figures at its base):
   - **γ, `--assumptions spreadsheet`:** the economics (capex is unchanged; DSCR, IRR and payback follow revenue) and the solved own-use rate become the override's. Today they are physics.
   - **γ, `--assumptions physics` on `bristol-fin-calibration.yaml`** (YAML override 0.70): the economics and the solved rate become physics. Today they are the override's.
   - **γ, `--assumptions both`:** the economics and cost-recovery blocks gain a Spreadsheet column (new figures). The "Physics Assumptions" heading goes; columns name the mode.
   - **δ, `bristol-phase1-flex.yaml` with `--flex-band central`:** the flex block's grid-services row falls from the consulting £30 per home to the booked events figure per battery home. That is about £3 on S9 §2.2's ~£296 a year fleet figure (operational, SOH 1.0) over 100 battery homes, and the headline falls by the difference. The events income now appears whenever the report projects.
   - **ε:** no figure moves. The removed SEG revenue was a second copy of Grid Export Revenue.

**Tactical** (decide in the leaf):

1. γ: the exact column label for an override other than 0.70 (format of the percentage).
2. γ: whether `AssumptionSection` validates its own blocks (economics only with a projection) or leaves that to R3.
3. δ: whether `FlexBlock` carries the resolved `FlexibilityValueBand` or the `GridServicesBand` and the report resolves it.
4. δ: how 837's per-window rows read for a scenario with more than one event window (837 decides the rows; δ moves them).
5. ε: whether "SEG Rate" is a row of the Financial table or a parenthetical on Grid Export Revenue.

## 13. Proposed cross-reference lines (for the lead to apply)

- **S6:** "S25 γ depends on S6's leaf that makes `cli/finance.run` read the fleet document through the one reader; S6's edits to `cli/finance.run` (the hand-built `ScenarioConfig`, the SEG threading and its inert cost-recovery branch, `flex_band`) land before γ restructures it per mode. S25 does not touch `cli/optimize.configs`' scenario."
- **S8:** "S25 γ adds `finance.own_use_basis` and `finance.with_own_use_basis`, and `home_ledger` reads its basis through `own_use_basis` (after 925). S25 δ adds `FleetProjection.grid_services_income_gbp`, filled by `_simulate_node` (after 929). S25 β moves `output`'s two board reports to `board_report.py` after 930. S25 γ drives one `run_cost_recovery` per `--assumptions` mode."
- **S9:** "837's capacity-at-events rows move out of the flex block into S25 δ's Grid Services Income section, which names the delivery baseline from the pricing value. Under a grid-services pricing the flex block's row is the booked figure per battery home (S9 §8 satisfied by δ). S25 δ depends on 803."
- **S10:** "783's `_extrapolation_notice` moves to `board_report.py` with S25 β, which depends on 783; S25 γ renders it once per report from the window every mode's bill shares."
- **S12:** "897's per-load seasonal tables in `generate_summary_report` build on `calculate_seasonal_metrics`' season aggregation rather than their own masks (the heat-pump-block half of fk-ae20e1833a19). S25 ε also edits `generate_summary_report` (Financial and SEG sections): textual only."
- **S16:** "S25 γ keeps 890's `reusing` wrapper and simulates the bill run on `scenario_fleet(scenario).homes`, the homes every projection ages, so the reuse answers each mode's age-0 node on unaged scenarios."
- **S19:** "S25 ε adds a `RunDocumentStep` and schema step dropping `FleetSummary.total_seg_revenue_gbp` and `per_home_seg_revenue_mean_gbp`; S25 ζ (held) one dropping `SummaryStatistics.seg_revenue_gbp`; both depend on 822 (C10). The five-energy-totals row helper stays in `cli/utils` (presentation), so `run_headline` does not delegate to it."
- **S21:** "833's flow properties: S25 adds no CLI rows for them."
- **S27:** "The rendered '(PRD §6)' in the flex block is replaced by S25 δ."
- **S29:** "The release section includes S25 ζ (`SummaryStatistics.seg_revenue_gbp` retired; consumers drop the keyword, the platform at 3 test sites) and the Unreleased lines of β (the reports' module), γ (`generate_finance_report`'s signature; `own_use_basis`, `with_own_use_basis`), δ (`FleetProjection.grid_services_income_gbp`, `GridServicesIncome`) and ε (the SEG-rate parameters and `FleetSummary`'s pair removed)."
- **Seam table:** "Report sections keyed by assumption mode (owner: `board_report.generate_finance_report`; reader `cli/finance`)" and "Typed summary rows (owner: `cli/utils` `home_summary_rows`/`fleet_summary_rows`, task 705; readers `cli/home`, `cli/fleet`)."
- **Tasks:**
  - 705 is re-scoped in place as S25 α and carries fk-6a52ed98b18e.
  - 703 closes fk-89afcb2b57f7, and 712 closes fk-41767a1bc146; the next run re-verifies both.
  - 741 keeps fk-b523bff3e51c. Its sweep-count sentence is rewritten by 930 (whichever lands second keeps 930's count). Its `cli/home` SEG-defence item is deleted by S25 ε, its `cli/fleet` task labels by S27 α, and its "pre-CR5" item with the branch S6 and S25 γ remove.
  - 765 lands before S25 β (edge). The rendered "(PRD §6)" is S25 δ's.

## Gate record

- **G1:** every mechanism has a named consumer.
  - `own_use_basis` and `with_own_use_basis`: `cli/finance.run` (per mode), `home_ledger`, the report's R2.
  - `AssumptionSection` and the keyed `generate_finance_report`: `finance run`.
  - `GridServicesIncome` and `FleetProjection.grid_services_income_gbp`: the report's Grid Services Income section and flex block (`finance run`).
  - `board_report.py`: `finance run`, `optimize configs`.
  - `_BINDING_LABELS` and the formatters: both reports.
  - The typed rows: `home run`, `home quick`, `fleet run`.
  - The stored-run steps: `web migrate` and the results pages.

  No orphan producer.
- **G2:** every leaf names a user-observable signal (§10): CLI report text and figures, library refusals, simulator counts through the CLI, a stored run's page after migrate. δ is the integration gate over B5–B13. ζ is a held leaf whose signal is the surface lock's form.
- **G3:** the substrate on main is verified at dfcbde8 (§7). Every other capability is produced upstream in the DAG: S8's 922, 925, 928, 929, 930; S9's 802, 803, 837; S10's 780, 783; S16's 882, 890; S19's 822; 705; S6's reader leaf.
- **G4:** each seam has one owner (§8). There are no reciprocal claims:
  - S9 names S25 for the rendering, and S27 offers the pointer;
  - S16 names S25 for keeping the wrapper;
  - S10 names S25 for keeping the notice;
  - S8 names S25 for the per-mode drive;
  - S19 names S25 for its stored-shape steps.

  Two program seam rows are proposed amendments (§12 questions 1 and 3).
- **G5:** B + H. The blast radius is 9 modules, the work has 10 mechanisms, and it sits on seams of six streams.
- **G6:**
  - **B6's figures.** £420.00 and the "Physics Assumptions" heading are the finding's measured run. 2,800 kWh override own-use (min(0.7 × 4,000, 3,400)) × 15 p = £420.00; physics own-use is 3,400 − 2,200 = 1,200 kWh × 15 p = £180.00.
  - **B7's difference.** The two modes' own-use differs (1,200 against 2,800 kWh), so the solved rates differ. The comparison is against the library's own per-mode run on the same fake, not a guessed figure.
  - **B8's count identity.** On a constant simulate every metric's interpolation is exact, so both modes select the same nodes (S8 B10's 5 nodes). S16 B17's match rule answers both modes' age-0 node, or neither. Either way count(both) − 1 = 2 × (count(physics) − 1).
  - **B10's year N below year 1** needs an injected simulate whose battery capacity falls with age. Per-age pricing (801) prices each age from its own fleet. D41's £296 against £143 at SOH 1.0 and 0.8 is the production analogue.
  - **The rejection mechanisms** (B3, B9, B12, B14's `TypeError`) are new code, each RED today. The binding chain's `else` renders an unknown binding today; the report signature and `GridServicesIncome` do not exist; `calculate_summary` accepts the rate.
  - **Field population.** `grid_services_income_gbp` is written by the node function on every simulated age (B13). 837's p50, p90 and displaced fields are written by 837's production path. `RunPricing.seg_rate_pence_per_kwh` is written by `simulate_home` (S8 β).
  - **The flex figure.** ~£3 a home is £296 / 100 battery homes. The scenario has 100 homes, each with a 5 kWh battery.
- **G7:** advisory (§10). No hit.
- **META:** decomposed without further oversight, this yields:
  - a board report whose every column is one assumption, computed from that assumption alone;
  - grid-services income shown where it changes the economics, on the terms it was booked;
  - board reports with a module of their own and one label and format set;
  - CLI tables chosen by type;
  - one export-revenue figure.

  The lead questions are two seam-row amendments, a re-scope, an optional cost saving and board communication. None changes the design.
