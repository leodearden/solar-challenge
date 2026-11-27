# Capability manifest — Board reports: sections by mode (S25)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/board-reports-sections-by-mode.md`. Each asserted capability binds to one kind of evidence:

- a symbol wired on main (`grep:<file>::<symbol>`);
- a producer upstream in this batch or out of it (`producer:<label>` or `producer:task-<id>`);
- a probe whose result was observed (`probe:`);
- an arithmetic identity (`identity:`).

The YAML twin, `board-reports-sections-by-mode.capability-manifest.yaml`, carries the mechanical `delivered_check`s. Every grep check's polarity was run on main `dfcbde8` with `git grep -cE`. Each `absent` pattern matches today and each `present` pattern does not.

**Code anchors** verified against main `dfcbde8` (2026-10-17). Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-extent-short`, `producer-downstream` or `rejection-absent`. The rejection mechanisms are new code, each bound to its producing leaf: the unknown binding (β), the section refusals (γ), `GridServicesIncome`'s refusals (δ) and the `TypeError` on the removed parameter (ε). Their RED cases are observed today as silent acceptance.

- **External producers upstream:**
  - S8: 922 (ε), 925, 928, 929, 930 (β, γ, δ);
  - S9: 802, 837 (β, δ), 803 (δ);
  - S10: 783 (β), 780 (ε);
  - S16: 882, 890 (γ, through 930);
  - S19: 822 (ε, ζ);
  - tasks 765 (β), 738 (γ, through 930), 705 (α itself, and ε);
  - S6 ε, task 959 (γ: `cli/finance.run` reads the one reader);
  - tasks 724 (β) and 439 (ε), edges added at decompose (2026-10-18).
- **Decompose re-walk (2026-10-18, main beb1d91).** Every grep check was re-run on main and on each `task/*` branch ahead of main that touches the leaves' files. Three checks changed:
  - ε's FleetSummary-pair check and ζ's field check could never pass, because their own `RunDocumentStep`s in `web/stored_runs.py` spell the keys. Both now name the modules that must lose the field.
  - ζ's surface check reads the form string `seg_revenue_gbp: float | None = None` under `tests/`, so it holds wherever S23 moves the table.
  - ε's "counted twice" check would go green if task 741 landed first. It is now `seg_tariff_pence_per_kwh` absent from `output.py`.

  β's wrapper check goes green on `task/724`, now β's prerequisite. α's checks go green on `task/705`, α's own branch.
- **Held leaf:** ζ waits for S29 and is excluded from this batch's `commit_planning`.

---

## α — typed summary rows (task 705, re-scoped in place)

| capability asserted | evidence | status |
|---|---|---|
| `fleet run` drops 4 rows today (B1's RED) | `probe:` the finding's run: a fully populated `FleetSummary` rendered 9 of 13 rows; `grep:cli/utils.py::create_summary_table` 8 `hasattr`/`getattr` probes at dfcbde8 | PASS |
| `FleetSummary` carries the four fields under other names | `grep:fleet.py::FleetSummary` (`fleet_self_consumption_ratio`, `fleet_grid_dependency_ratio`, `total_net_cost_gbp`, `total_seg_revenue_gbp`) | PASS |
| The typed builders exist and are wired into the three commands | `producer:task-705` (branch `task/705`: `home_summary_rows`, `fleet_summary_rows`, `_energy_total_rows`, `_money_rows`; `cli/home.py` run and quick, `cli/fleet.py` run pass rows) | PASS |
| A renamed field fails mypy | the builders read typed parameters (`SummaryStatistics`, `FleetSummary`); mypy strict is the project's type check | PASS (manual) |

## β — board_report.py (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The two board reports are outside every frozen table | `grep:__init__.py` (no `generate_finance_report`, `generate_config_ranking_report` or `output` entry); `FROZEN_SURFACE`/`FROZEN_CLOSURE` (none) | PASS |
| The duplicate label chain and inline formatting exist today | `grep:output.py::generate_finance_report` (`binding == "floor"`, `"rate_clamped_zero"`; `math.isnan(economics.equity_irr)`, `math.isinf(economics.min_dscr)`) beside `_BINDING_LABELS` and `_fmt_*` | PASS |
| The three ratio wrappers are dead | `grep:src` (no caller of `calculate_self_consumption_ratio`, `calculate_grid_dependency_ratio`, `calculate_export_ratio`; only `tests/unit/test_output.py`); `producer:task-724` deletes them first (branch `task/724`) | PASS |
| An unknown binding reaches the reports today (B3's RED) | `grep:finance.py::CostRecoverySolution.binding` is `str`; S8 η (934) refuses only `feasible != (binding != "infeasible_above_retail")`, so `binding="other"` with `feasible=True` constructs | PASS |
| The upstream edits to the two reports land first | `producer:task-783` (the notice), `producer:task-837` (the events rows), `producer:task-930` (the ranking header; 928's imports through it), `producer:task-765` (docstring pointers) | PASS |
| Byte-identical output (B2) | behaviour-preserving move; the reports captured at β's base are the reference | PASS |

## γ — one column per mode (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `OwnUseBasis` and `home_ledger` exist at the base | `producer:task-925` (S8 γ, §5.2) through 930 | PASS |
| `scenario_fleet`, `project_fleet`, `FleetProjection`, `run_cost_recovery` | `producer:task-928`, `producer:task-929`, `producer:task-930` | PASS |
| `fleet.reusing` and `invocation(ctx).runner` in `cli/finance.run` | `producer:task-890`, `producer:task-882` (both upstream of 930) | PASS |
| `BillDistribution.annualised_from` and `_extrapolation_notice` (R4, the one notice) | `producer:task-782`, `producer:task-783` | PASS |
| The scenario is read through S6's reader | `producer:task-959` (S6 ε: `load_scenario` plus the option pair in `cli/finance.run`; S6 PRD §4.4) | PASS |
| The spreadsheet default is 0.70 | `grep:finance.py::DEFAULT_SPREADSHEET_SELF_CONSUMPTION` = 0.70 | PASS |
| The mislabel ships today (B6's RED) | `probe:` the finding: `generate_finance_report(bill_distribution([home], replace(f, self_consumption_override=0.7), 365))` prints "## Householder Bill (Physics Assumptions)" over £420.00; `grep:output.py` "Physics Assumptions"; task 738's branch keeps the primary in the `bill_physics` slot | PASS |
| £420 against £180 | `identity:` min(0.7 × 4,000, 3,400) = 2,800 kWh × 15 p = £420.00; 3,400 − 2,200 = 1,200 kWh × 15 p = £180.00 | PASS |
| The projection and solve ignore the mode today (B7's RED) | `grep:cli/finance.py::run` passes the raw `finance` to `project_multi_year`, `project_economics` and `solve_cost_recovery_rate` (also on `task/738`) | PASS |
| `scenarios/bristol-fin-calibration.yaml` sets an override | `grep:` `self_consumption_override: 0.70` | PASS |
| B8's count identity | `identity:` on a constant simulate both modes select S8 B10's nodes, and S16 B17's match rule answers both modes' age-0 node or neither, so count(both) − 1 = 2 × (count(physics) − 1) | PASS |
| Section refusals | rejection mechanism authored in γ; B9 observes each fire | PASS (producer γ) |

## δ — grid-services income with the economics (leaf, integration gate)

| capability asserted | evidence | status |
|---|---|---|
| Pricing values with `annual_income_gbp`; `grid_services_model_of` | `producer:task-801`, `producer:task-802` (upstream through 928) | PASS |
| `GridServicesAtEvents` p50, p90, displaced self-use; `GridServicesEventsConfig.delivery_baseline` | `producer:task-837` (S9 α′ §5.10; fields written by `compute_grid_services_at_events` on the production path) | PASS |
| `GridServicesBand` for `--flex-band` | `producer:task-803` | PASS |
| The node prices grid services per age | `producer:task-929` (S8 ε `_simulate_node` calls `annual_income_gbp` per age, D13) | PASS |
| `FleetProjection.grid_services_income_gbp` is populated | field written by δ's `_simulate_node` edit on every simulated node; B13 binds it | PASS (producer δ) |
| Ages 0 and L−1 are always simulated | S8 ε's seeds {0, L/2, L−1} (`grep:finance.py::project_multi_year` seed march, moved by 928) | PASS |
| The events income is hidden without `--flex-band` today (B10's RED) | `grep:output.py::generate_finance_report` nests the capacity-at-events sub-section under `if flex_band is not None` | PASS |
| The flex row shows the consulting figure today (B11's RED) | `grep:output.py` "Grid services (firm flex)" reads `flex_band.grid_services_per_home_gbp`; "(PRD §6)" is rendered | PASS |
| ~£3 a battery home | `identity:` S9 §2.2's ~£296 a year (operational, SOH 1.0) / 100 battery homes (`scenarios/bristol-phase1-flex.yaml`: `n_homes: 100`, 5 kWh battery on every home) | PASS |
| `GridServicesIncome` refusals | rejection mechanism authored in δ; B12 observes each fire | PASS (producer δ) |

## ε — one export-revenue figure (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `calculate_summary`, `calculate_fleet_summary` and `FleetSummary` are not frozen | `grep:__init__.py` (no entry for any of them) | PASS |
| `RunPricing.seg_rate_pence_per_kwh` on the results | `producer:task-922` (S8 β; written by `simulate_home` on every run) | PASS |
| `aggregate_annual` is deleted first | `producer:task-780` (S10 γ2, L9) | PASS |
| A stored-run step mechanism exists | `producer:task-822` (S19 κ: `RUN_DOCUMENT_STEPS`, the strict reader, C10) | PASS |
| `web/storage` stores `FleetSummary` | `grep:web/storage.py::save_fleet_run` / `_deserialize_dataclass(FleetSummary, …)` | PASS |
| The CLI row exists to remove | `producer:task-705` (`_money_rows`' "SEG Revenue") | PASS |
| The recomputation and its readers exist today (B14's RED) | `grep:` 6 `calculate_summary(<r>, seg_tariff_pence_per_kwh=` calls; "## SEG Revenue" ×2; `total_seg_revenue_gbp`/`per_home_seg_revenue_mean_gbp` ×8; `cli/home.py`'s "counted twice" comment | PASS |
| Removing the parameter raises `TypeError` | Python's keyword-argument check | PASS |
| `calculate_home_summaries` (task 439) passes the rate too | `producer:task-439` (branch `task/439`: `calculate_home_summaries(results, seg_tariff_pence_per_kwh=None)`, `aggregate_home_summaries` aggregates the pair); ε depends on 439 and removes both | PASS |
| The absent checks can pass after ε's own migration step | ε's `RunDocumentStep` in `web/stored_runs.py` spells both keys, so the pair check reads `fleet.py`, `cli/` and `output.py` only | PASS |

## ζ — the frozen field retired (held leaf)

| capability asserted | evidence | status |
|---|---|---|
| The field is on the frozen form | `grep:tests/unit/test_public_api_surface.py::FROZEN_SURFACE["SummaryStatistics"]` includes `seg_revenue_gbp: float \| None = None` | PASS |
| The platform passes it by keyword | `probe:` grep of solar-challenge-platform: 3 test sites `seg_revenue_gbp=None` | PASS |
| Step mechanism | `producer:task-822` | PASS |
| The absent checks can pass after ζ's own migration step | ζ's `RunDocumentStep` in `web/stored_runs.py` spells the key, so the field check reads the domain, report and CLI modules; the surface check matches the form string under `tests/`, which B16's keyword test does not | PASS |
