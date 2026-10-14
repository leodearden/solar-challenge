# Simulation window and cadence as typed values in timebase

**Status:** authored 2026-10-14, not committed (program `review-all-solar_challenge-20261013`, stream S10, wave 1, no upstream streams). Contract-first (B + H).

**Code anchors** verified against main `1251be0` (2026-10-14). Main moves fast: cite-by-symbol; re-locate lines at implementation time.

## Goal

How long a simulated window is, how long one row of it lasts, and how a window total becomes a yearly figure each have one typed home: `timebase.SimulationWindow`. Every consumer reads it instead of re-deriving it.

What a user sees when this lands:

- `solar-challenge finance run` over 2024-03-31..2024-04-01 bills the 2 days its homes simulated, not 1, and its report says the figures are extrapolated: ×183.000 from a 2-day window. A run over 2023-01-01..2023-12-31 carries no such notice.
- `bill_distribution(summaries, finance, 1)` on summaries of a 2-day window raises, naming 1 and 2. Today it bills the summaries as one day, with no error.
- A 400-day run is billed as 365.25/400 of its totals, not as one year. A 30-day run is billed ×12.2 (366/30) in 2024. Finance's 360-day threshold is gone.
- `solar-challenge validate results` on a half-hourly CSV of a constant 0.4 kW demand over 2023-06-01..06-07, with `--consumption-kwh 3504`, passes at 3,504 kWh. Today it fails at 117 kWh. A CSV whose window crosses a DST change validates; today it stops with a `TypeError` traceback.
- `calculate_summary` over 2024-10-01..2024-11-30 reports 61 simulation days. Today it reports 62, because it counts a timedelta that the autumn fall-back lengthens by an hour.
- `simulate_community` refuses a fleet index with a dropped middle row, naming the position and both gaps. Today it prices that run with no error.

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says |
|---|---|---|
| fk-1cd332300623 | medium / confirmed | `bill_distribution` and `householder_bill` take the day count as an argument nobody checks against the summaries; `cli/finance.run` computes it from tz-aware midnights and undercounts across spring-forward. |
| fk-d63c41ca13f9 | medium / weakened | Four window-to-annual rules and four thresholds (finance 360, validation 365, charts 90 and 180), and four `.days + 1` recomputations beside `SummaryStatistics.simulation_days`. |
| fk-286fe17c28c9 | medium / confirmed | `householder_bill`'s `annual_self_consumption_kwh` is the window's figure; a caller who believes the name is double-scaled with no error. |
| fk-756c0ef9e9d9 | low / confirmed | `_check_annual_yield` judges a run of 365+ days unannualised. Mechanical filing: task 749 (in progress). |
| fk-7ef1099d24e8 | low / confirmed | The cadence is one axis handled three ways: a constant, `step_hours`, and ten timestep parameters that the top of the stack feeds a literal `1.0`. |

Rulings that bind this PRD (program doc §Resolved decisions):

- **D8.** The cadence is a run-owned parameter derived from the index and carried by `SimulationWindow`, threaded to every integration site. The ten timestep parameters become reads of it, not deletions.
- **D12.** One annualisation rule: scale = covered year length / window days, always. The year length is 365 or 366 by the covered calendar year, and 365.25 when the window crosses years. `SimulationWindow` computes it once; finance, validation and the annual aggregate use it. A board output whose window is not a whole number of calendar years carries an explicit extrapolated marking, which replaces finance's short-period warning. Charts' 90- and 180-day gates stay as display gates. `householder_bill`'s "annual" parameter is renamed to the window quantity, and `cli/finance`'s day count is replaced by the window's, in this stream.
- **D4.** One coordinated frozen-surface bump (S29). A retire or rename waits for it as a held leaf.
- **D27.** Invariant 8 ("the day count a bill is computed over is the summaries' own") is promoted: a test plus a `review/briefing.yaml` conventions line.
- **D28.** fk-d63c41ca13f9 is re-measured before decomposing (below).

### Re-measurement at `1251be0` (D28, fk-d63c41ca13f9)

The weakened finding reproduces at HEAD:

- Window-to-annual rules: still 4. Finance scales ×365/d below 360 days, else ×1. `validate_consumption` scales ×365/d always. `_check_annual_yield` returns None under 365 days, else ×1. `output.aggregate_annual` scales ×1.
- Thresholds: 360 (`finance._SHORT_PERIOD_THRESHOLD`, 3 uses), 365 (`_check_annual_yield`), 90 and 180 (`web/charts`).
- `.days + 1` on a timedelta: 9 sites. These are `home.calculate_summary`, `validation` ×2, `web/charts` ×2, and the four CLI commands. `load._try_richardsonpy_profile` alone counts calendar dates.
- Inline `.sum() * HOURS_PER_MINUTE` integrations: 13. The `timestep_minutes=1.0` literal appears twice in `home.simulate_home`.

A new measurement sharpens the finding. The "authoritative" count, `calculate_summary`'s `(index[-1] - index[0]).days + 1`, is also a timedelta. It overcounts by one for any window that crosses the autumn fall-back but not the spring-forward: 2024-10-01..11-30 gives 62 against 61 calendar days, and 2024-07-01..12-31 gives 185 against 184. The skeptic's weakening still stands: the chart gates are display gates, not annualisation. They stay as gates and only stop recomputing the count.

## Sketch of approach

`timebase.py` grows from one constant and one helper into the module that says what a simulated window is. `SimulationWindow` is a frozen value: its first and last local calendar days, its cadence and its zone. It derives the covered days, the covered year length, the annualisation scale, the extrapolated flag, and the row length in hours and minutes. It has one kW-to-kWh integration. `SimulationWindow.of_index` builds it from a series index and refuses one it cannot describe. That refusal is the uniform enforcement point (heuristic 10) that `step_hours`' one-minute fallback and community's first-against-last check lacked.

The window travels with the data, never beside it (heuristic 7, stateless interactions):

- `SimulationResults.window` derives from the results' own index. The run's cadence is its index's. The results' energy amounts read `window.step_hours`.
- `SummaryStatistics.window` is set by `calculate_summary`. `simulation_days` agrees with it by construction (`__post_init__`).
- `BillDistribution.annualised_from` and `MultiYearCurve.annualised_from` say which window a yearly figure came from. The board reports read them for the extrapolated notice.

Each consumer then reads one value instead of choosing a rule:

- `simulate_home` passes `window.step_minutes` to the engine.
- Finance annualises by `window.annualisation_scale` and bills the standing charge over `window.year_days`.
- Validation scales by the same property.
- Output, community, load and heat-pump integrate through `window.energy_kwh` or `window.step_hours`.
- Charts gate on `window.days`.
- The CLI messages count with `covered_days`.

Heuristics served: 11 (SPOT: one day count, one cadence, one rule), 3 (window length and cadence as orthogonal axes, each with one mechanism), 1 (an "annual" parameter that is not annual, and a "per minute" amount that need not be, lose their lying names), 10 (refusals at construction and at use, naming values), 12 (a typed window instead of an int and an implicit constant).

## Resolved design decisions

1. **The window is a value with dates, not a day count.** D12's year length depends on the calendar year, and the extrapolated flag depends on the first and last days. An `int` cannot carry either, so `SummaryStatistics` must carry the window itself. `simulation_days` stays, derived from the window (remedy: "derives from it").
2. **Covered days count local calendar dates,** first to last inclusive (`covered_days`), never a timedelta. A partial first or last day counts as a whole day: every production window is whole days, and the rule stays total and simple. `load._try_richardsonpy_profile`'s calendar count is the same rule; S12 replaces that site.
3. **The cadence is derived, never defaulted.** `of_index` reads `index.freq` when it is set, else the common spacing. It refuses:
   - an empty index;
   - a one-row index without `freq`;
   - a spacing that is not uniform, naming the first position whose gap differs and both gaps;
   - a non-`DatetimeIndex`, naming its type.

   A tz-aware index is uniform in absolute time across DST, so real runs pass. `timebase.step_hours` and its silent one-minute fallback are deleted. `HOURS_PER_MINUTE` stays only as a unit conversion (minutes × it = hours), which the battery, dispatch and flow functions use to turn their `*_minutes` parameter into hours.
4. **D8's extent in this stream.** Every integration site reads the window: `simulate_home`'s engine loop and kW conversion, `SimulationResults`' amounts, output, community, `load.calculate_annual_consumption`, heat-pump's degree-minute conversion, validation and finance. The generators still build a one-minute index. S12's calendar-day rework of the generators builds them from the window, which is where a run's cadence would be chosen. No user-settable cadence option is added: nothing consumes one (G1). Variable cadence works end to end for any results whose index has another cadence: `SimulationResults.from_dataframe`, a `validate results` CSV, a fleet's community series.
5. **The one rule, as D12 states it:**
   - `year_days` is 366 or 365 by `calendar.isleap(first_day.year)` when `first_day.year == last_day.year`, else 365.25.
   - `annualisation_scale` is `year_days / days`, with no threshold.
   - `extrapolated` is false only when `first_day` is 1 January and `last_day` is 31 December.

   So a whole 2023–2024 run is a yearly mean (×365.25/731) and is not marked. A 2024-04-01..2025-03-31 run is marked (×365.25/365).
6. **The billed year's standing charge is `window.year_days` days.** This is derived from D12: the energy is scaled to the covered year, so the standing charge covers the same year. A full-2024 bill then carries 366 days of standing charge where today it carries 365, and its energy is unchanged (366/366 = 1). This is open question 2 for the lead's confirmation, because it moves every default (2024) board outlay by one day's standing charge.
7. **The extrapolated marking is data, then text.** `BillDistribution.annualised_from` and `MultiYearCurve.annualised_from` carry the window. One renderer in `output.py`, `_extrapolation_notice(window)`, writes the notice in `generate_finance_report` (`finance run`) and `generate_config_ranking_report` (`optimize configs`), the two board outputs. Both `UserWarning`s go: `householder_bill`'s short-period warning and `project_multi_year`'s short-window warning.
8. **Refusals at use name both values (heuristic 10, invariant 8):**
   - `householder_bill` refuses a `simulation_days` that differs from `summary.simulation_days`.
   - `bill_distribution` refuses summaries whose windows differ, naming the first differing position and both windows. A bill distribution is over one window.
   - Both refuse a summary without a window, naming the field and `calculate_summary` as its source.
   - `householder_bill` refuses an own-use figure below 0 or above the summary's demand (fk-286fe17c28c9's proposal). S8's per-home ledger balance check later sits beside it.

   The frozen signatures are kept (stream row). The refusals are `ValueError`, which is S1's `ConfigurationError`'s base (D2).
9. **Surface posture (D4).** Additive surface changes land in their own leaf, as task 469 did with `SummaryStatistics.total_grid_charge_kwh`. Each such leaf adds its `FROZEN_SURFACE` / `FROZEN_CLOSURE` / `FROZEN_MEMBERS` entry and a `docs/domain-library-consumption.md` "Unreleased on main" line. The additive changes are:
   - `SimulationResults.window`;
   - `SummaryStatistics.window`, optional for now;
   - `BillDistribution.annualised_from`, optional for now;
   - `SimulationWindow` joining the closure.

   Every rename or retirement waits for S29 in held leaf η: the window fields made required, `simulation_days` derived, the parameter rename, the `= 1.0` timestep defaults dropped, and `per_minute_amounts` renamed. Open question 3 asks the lead to confirm this reading of "changes only through S29".
10. **Stored runs.** `web/storage`'s value codec learns `datetime.date` and `datetime.timedelta`. These are the only new value types the window brings. `summary.window` therefore round-trips. A run stored before β loads with `window=None` until η makes the field required. From then on, S19's `StoredRunUnreadable` names such a run (cross-reference).
11. **`output.aggregate_annual` is deleted, not annualised.** It has no caller in `src` (0 callers; S25 lists it as dead). An annualising version would be a producer with no consumer (G1). Deleting it removes the fourth rule as surely as D12's "used by the annual aggregate" intends. This is open question 1, because D12's text names the aggregate as a user of the rule.

## Contract (seam: `SimulationWindow`, owner this PRD; readers home, finance, validation, output, charts, community, load, heat_pump, cli; downstream streams S12, S25)

```python
# src/solar_challenge/timebase.py
HOURS_PER_MINUTE: float = 1 / 60
"""Hours in one minute: a unit conversion. Says nothing about a series' cadence."""

def covered_days(first_day: date, last_day: date) -> int:
    """Calendar days from first_day to last_day inclusive. Raises ValueError naming both when last_day < first_day."""

@dataclass(frozen=True)
class SimulationWindow:
    first_day: date              # local calendar date of the first row
    last_day: date               # local calendar date of the last row, inclusive
    cadence: timedelta           # how long one row lasts; > 0
    timezone: str | None = None  # the index's zone name; None for a naive index
    # __post_init__: ValueError naming the field and value when last_day < first_day or cadence <= 0.

    @classmethod
    def of_index(cls, index: pd.DatetimeIndex) -> "SimulationWindow": ...
        # first_day/last_day: index[0].date(), index[-1].date() in the index's own zone.
        # cadence: index.freq as a Timedelta when set, else the uniform spacing.
        # Raises ValueError: empty index; one row without freq; non-uniform spacing
        # (names the first position whose gap differs and both gaps); not a DatetimeIndex (names its type).

    days: int                    # covered_days(first_day, last_day)
    year_days: float             # 365 or 366 by the year when first_day.year == last_day.year, else 365.25
    annualisation_scale: float   # year_days / days
    extrapolated: bool           # not (first_day is 1 Jan and last_day is 31 Dec)
    step_hours: float            # cadence in hours
    step_minutes: float          # cadence in minutes: the engine's timestep_minutes / duration_minutes
    def energy_kwh(self, power_kw: pd.Series) -> float: ...  # sum of power_kw times step_hours: the one kW-to-kWh integration
```

Invariants and where each is enforced:

| invariant | construction | use |
|---|---|---|
| A window's days are its local calendar dates, inclusive. | `covered_days` (the one rule) | `SummaryStatistics.__post_init__`: `simulation_days == window.days` |
| A window has one uniform, positive cadence. | `SimulationWindow.__post_init__`; `of_index` | community, output, validation and home all derive through `of_index`, never a constant |
| A yearly figure is window total × `annualisation_scale`. | the property | finance (`_annualise_physics`) and validation (`_check_annual_yield`, `validate_consumption`) |
| The day count a bill is computed over is the summaries' own (INV-8). | `SummaryStatistics.window` | `householder_bill` / `bill_distribution` refuse a mismatch, naming both |
| A bill distribution is over one window. | — | `bill_distribution` refuses differing windows |
| A board figure from a window that is not whole calendar years says so. | `BillDistribution.annualised_from`, `MultiYearCurve.annualised_from` | `output._extrapolation_notice` in both board reports |

Downstream readers and their seam lines:

- **S12** reads `first_day`, `last_day`, `cadence` and `timezone` to build its calendar-day iterator in `timebase.py`. It adds the iterator; it does not redefine the window.
- **S25** keeps the extrapolated notice when `generate_finance_report` becomes sections keyed by assumption mode.

## Boundary-test sketch (both sides of the seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Calendar day count | minute indexes from `pd.date_range` over 2024-10-01..11-30, 2024-03-31..04-01, 2024-07-01..12-31 (Europe/London) | `of_index(...).days` is 61, 2 and 184 (timedelta gives 62, 2 and 185) | α |
| B2 | Producer refusals | an index with row 700 of a 2024-06-01 minute day deleted; an empty index; a one-row index without freq; a string index (as `read_csv` returns across DST) | each raises `ValueError`; the first names position 700 and the 1-minute and 2-minute gaps; the last names the dtype | α |
| B3 | The one rule | windows 2023-01-01..12-31; 2024-01-01..12-31; 2024-06-01..06-30; 2023-01-01..2024-12-31; 2024-01-01..2025-02-03 | `(year_days, annualisation_scale, extrapolated)` = (365, 1.0, F); (366, 1.0, F); (366, 12.2, T); (365.25, 365.25/731, F); (365.25, 365.25/400, T) | α |
| B4 | Cadence twin | one `SimulationResults` at 1-minute and its 30-minute twin of constant powers (0.4 kW demand, 1.0 kW generation) over 2023-06-01..06-07, the twin built with `from_dataframe` | equal `total_amounts()` (demand 67.2 kWh), `calculate_summary` energies, `calculate_seasonal_metrics` and `compute_community_metrics` to 1e-9 relative; `window.cadence` is 1 minute and 30 minutes | α (amounts), γ2 (output) |
| B5 | Summary agrees with its window | `calculate_summary` on B1's 2024-10-01..11-30 results; `SummaryStatistics(simulation_days=3, window=<2-day window>)`; `save_home_run` then `load_home_run` | `simulation_days == window.days == 61`; construction raises naming 3 and 2; the loaded summary's window equals the saved one | β |
| B6 | Finance reads the window | summaries from tests/_finance_builders with windows attached | `bill_distribution(<2-day>, f, 1)` raises naming 1 and 2 (INV-8); differing windows refused; a window-less summary refused naming `window`; own-use above demand refused naming both; full-2024 standing charge = 366 × p/100; a 2024-01-01..2025-02-03 summary's billed energy = total × 365.25/400 | ε |
| B7 | Validation reads the same rule | B3's windows as minute series; the 2023 half-hourly CSV; a 2024-03-30..04-01 minute CSV | `validate_consumption`'s annual equivalent = `window.energy_kwh(demand) × window.annualisation_scale`; the CLI passes the half-hourly CSV at 3,504 kWh; the DST CSV prints the check table with exit code 0 or 1, never a traceback | δ |
| B8 | Board reports and CLI | `finance run` with a fake `CliFleetSimulator` producing per-home results on the 2024-03-31..04-01 minute index (2,820 rows); the same over 2023-01-01..12-31; `optimize configs` over a 30-day window | the first report contains the notice with ×183.000 and "2-day window"; its bills equal `bill_distribution(summaries, finance, 2)`; the second has no notice; the third has the notice; the pre-run "N days" message equals `summaries[0].simulation_days` | ζ |
| B9 | Chart display gates read the window | results over 2024-10-01..12-28 (89 calendar days) and 2024-10-01..12-29 (90) | the monthly chart is None for the first (today rendered: the timedelta reads 90) and a figure for the second | γ2 |
| B10 | Community refuses an uneven index | a `FleetResults` whose index drops one middle row | `simulate_community` raises naming the position and both gaps (today: priced, no error) | γ1 |

## Pre-conditions for activating

- No upstream stream (wave 1).
- **Task 749** (fk-756c0ef9e9d9's mechanical fix, in progress) lands before δ. δ replaces its 365/duration rule with the window's.
- G3 substrate:
  - `bill(period_days: float, ...)` takes a float, so `year_days` = 365.25 is legal.
  - The `CliFleetSimulator` injection and the `tests/_cli_fleet_simulator.py` fake exist.
  - `cli/utils.create_summary_table` prints "Simulation Days".
  - `review/briefing.yaml` has a `conventions` block.
  - `web/storage._serialize_value` lacks `date` and `timedelta`, so β adds them.

## Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S12 Load composition | produces for | `SimulationWindow` fields; S12's calendar-day iterator in `timebase.py` and generators built from the window | S10 (window), S12 (iterator, generators) | S12 depends on S10 (program) |
| S25 Board reports | produces for | the extrapolated notice and `annualised_from`; `aggregate_annual` deletion moves here (open question 1) | S10 (notice), S25 (report sections) | S25 depends on S10 (program) |
| S19 Run store | shares | storage value codec (`date`, `timedelta`); a run stored before β lacks `summary.window`; after η, S19's `StoredRunUnreadable` names it | S19 (format version, refusal); S10 (the two codec branches in β) | parallel wave 1; file overlap `web/storage.py` |
| S8 Finance partition | consumes | `project_multi_year` and its helpers move after ε, carrying `summary.window` reads; S8's per-home balance check sits beside ε's own-use bound | S10 (ε) | proposed: S8's move leaf depends on ε (open question 5) |
| S3 One dispatch engine | shares | engine `timestep_minutes` parameters; η drops their `= 1.0` defaults on whatever signatures S3 leaves | S10 (η) | η runs at the bump, after S3 |
| S21 Chart panels | shares | the 90/180 gates read `results.window.days` (γ2); S21 turns the gates' `None` into named absence reasons | S10 (count), S21 (panel) | parallel; file overlap `web/charts.py` |
| S29 Surface bump | consumes | held leaf η: required window fields, derived `simulation_days`, parameter rename, defaults dropped, `per_step_amounts` | S29 releases η | η filed with `x_seam_wait` |
| S2, S15, S13 | file overlap only | `home.py`, `load.py` | — | no semantic seam |

## Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`. Priorities follow severity; no leaf is high or critical, so none joins the trigger-chain gate.

- **α. `timebase.SimulationWindow` and `SimulationResults.window`.** Files: `timebase.py`, `home.py` (`SimulationResults`), `tests/unit/test_timebase.py`, `tests/unit/test_public_api_surface.py` (`FROZEN_MEMBERS` gains `home.SimulationResults.window`), `docs/domain-library-consumption.md`. Adds the contract's `covered_days` and `SimulationWindow`. `SimulationResults.window` derives from the generation index. Its power amounts multiply by `window.step_hours`, not `HOURS_PER_MINUTE`. Signal: `SimulationResults.from_dataframe(<30-minute frame>).total_amounts()["demand_kwh"]` is Σ kW × 0.5. Today it is Σ kW / 60. B1–B3 and B4's amounts row pass. Unlocks β, γ1, γ2, δ. Keys: fk-7ef1099d24e8, fk-d63c41ca13f9. Priority medium.
- **β. Summaries carry their window.** Files: `home.py` (`SummaryStatistics`, `calculate_summary`), `web/storage.py` (codec), `tests/unit/test_home.py`, `tests/unit/test_web_storage_roundtrip.py`, `tests/unit/test_public_api_surface.py` (`SummaryStatistics` form; `timebase.SimulationWindow` joins `FROZEN_CLOSURE` and `FROZEN_MEMBERS`), `docs/domain-library-consumption.md`. Adds `window: Optional[SimulationWindow] = None` (transitional), the agreement refusal, `calculate_summary` setting both from `results.window`, and the codec branches. Signal: `calculate_summary` over 2024-10-01..11-30 reports `simulation_days` 61 (today 62), and `home run` prints "Simulation Days 61" for that window. A stored run's results page loads with its summary's window intact. B5. Prereq α. Unlocks ε. Keys: fk-1cd332300623, fk-d63c41ca13f9. Priority medium.
- **γ1. The engine and integration sources read the window.** Files: `home.py` (`simulate_home`), `load.py` (`calculate_annual_consumption`), `heat_pump.py` (degree-minute conversion), `community.py` (`_price_grid_flows`, `simulate_community`), tests. `simulate_home` derives the window from the run's index and passes `window.step_minutes` to `simulate_timestep` and `simulate_timestep_tou`. Its kWh-to-kW conversion uses `window.step_hours`. Community's first-against-last check is deleted (`of_index` refuses unevenness). Signal: B10. `simulate_community` refuses a dropped middle row (today it prices silently), and no `timestep_minutes=1.0` literal remains in `home.py`. Prereq α. Unlocks γ2 and η. Key: fk-7ef1099d24e8. Priority low.
- **γ2. Readers read the window; `step_hours` goes.** Files: `output.py` (the 10 inline integrations, the heat-pump seasonal day counts, `calculate_seasonal_metrics`, `compute_community_metrics`, `aggregate_annual` deleted per open question 1), `web/charts.py` (monthly and seasonal gates on `results.window.days`), `timebase.py` (`step_hours` deleted, module docstring), `tests/unit/test_output.py`, `tests/unit/test_web_charts.py`, `tests/unit/test_timebase.py`. Signal: B4's output rows (a 30-minute twin's seasonal metrics equal the minute run's; today 1/30), and B9 (the 89-day window's results page shows no monthly chart). Prereqs α, γ1. Keys: fk-7ef1099d24e8, fk-d63c41ca13f9. Priority low.
- **δ. Validation scales by the window.** Files: `validation.py` (`_check_annual_yield`, `validate_consumption`), `cli/validate.py` (`results` reads the CSV index as tz-aware timestamps), `tests/unit/test_validation.py`, the CLI validate tests, `docs/pv-annual-yield-benchmark.md` where it states the rule. `_check_annual_yield` keeps its applicability gate (`window.days < 365` gives None: a yield benchmark needs a year of seasons) and annualises by `window.annualisation_scale`. Signal: `validate results` on the 2023 half-hourly CSV with `--consumption-kwh 3504` passes at 3,504 kWh (today it fails at 117). The 2024-03-30..04-01 CSV prints the table instead of a traceback. B7. Prereqs α and task 749. Keys: fk-756c0ef9e9d9 (re-run the §8 key lookup: 749 holds it), fk-d63c41ca13f9. Priority low.
- **ε. Finance bills through the window (D12, INV-8 library half).** Files: `finance.py` (`_annualise_physics`, `householder_bill`, `bill_distribution`, `BillDistribution.annualised_from` optional, `MultiYearCurve.annualised_from`, `_NodeData`, `project_multi_year`; `_annualisation_scale`, `_ANNUALISATION_DAYS` and `_SHORT_PERIOD_THRESHOLD` and both warnings deleted; 'annual' to 'window' in docstrings and the `_billed_energy` prose), `optimize.py` (`_age0_baseline_outlay` without the `else 365` fallback), `tests/_finance_builders.py` and the finance tests, `tests/unit/test_public_api_surface.py` (`BillDistribution` form), `docs/cost-recovery-finance-model.md` (§4 annual basis and the solve section), `docs/domain-library-consumption.md`, `review/briefing.yaml` (one conventions line naming INV-8's test). Signal: B6. `bill_distribution(<2-day summaries>, finance, 1)` raises naming 1 and 2; today it returns a bill. A 400-day summary bills 365.25/400 of its energy (today ×1). Prereq β. Unlocks ζ, η. Keys: fk-1cd332300623, fk-d63c41ca13f9, fk-286fe17c28c9. Priority medium.
- **ζ. Board outputs and CLI counts read the window (INV-8 CLI half).** Files: `cli/finance.py` (bills over `summaries[0].simulation_days`; the message counts with `covered_days`), `cli/fleet.py`, `cli/home.py`, `cli/optimize.py` (messages and the sweep-size threshold use `covered_days`), `output.py` (`_extrapolation_notice` in `generate_finance_report` and `generate_config_ranking_report`), `tests/unit/test_cli*.py`, `tests/unit/test_output.py`. Signal: B8. `finance run` over 2024-03-31..04-01 prints the notice "×183.000 … 2-day window (2024-03-31 to 2024-04-01)" and bills 2 days (today 1 day, no notice), and a 2023 full-year run prints no notice. Prereq ε. Keys: fk-1cd332300623, fk-d63c41ca13f9. Priority medium.
- **η. Surface bump edits for the window (held: `x_seam_wait = {stream: S29, contract: "one coordinated frozen-surface bump (D4)"}`).** Files: `home.py`, `finance.py`, `flow.py`, `dispatch.py`, `tests/unit/test_public_api_surface.py`, tests constructing `SummaryStatistics` or calling the renamed names, `docs/domain-library-consumption.md`.
  - `SummaryStatistics.window` becomes required and `simulation_days` a property of it.
  - `BillDistribution.annualised_from` becomes required.
  - `householder_bill`'s `annual_self_consumption_kwh` becomes `window_self_consumption_kwh`.
  - The `= 1.0` defaults go from `simulate_timestep`, `simulate_timestep_tou` (if S3 has not retired it) and `DispatchStrategy.decide_action` and its overrides.
  - `SimulationResults.per_minute_amounts` becomes `per_step_amounts`.

  Signal: the frozen-surface test pins the new forms. `householder_bill(summary, window_self_consumption_kwh=…, …)` works and the old keyword raises `TypeError`. Prereqs β, γ1, ε, ζ; S29 releases it. Keys: fk-286fe17c28c9, fk-7ef1099d24e8, fk-1cd332300623. Priority medium.

DAG: α → {β, γ1, δ (+749)}; γ1 → γ2; α → γ2; β → ε → ζ; {β, γ1, ε, ζ} → η (held).

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- `no-silent-fail-soft`: `step_hours`' one-minute fallback and community's partial check are removed. The transitional `None` on `SummaryStatistics.window` and `BillDistribution.annualised_from` is refused by finance. A report given a hand-built window-less distribution renders no notice. That is bounded and owned: η removes the `None`, with the S29 bump as its deadline.
- `one-fact-one-home`: `simulation_days` and `window` coexist until η, with `__post_init__` as their reconciler.
- `guards-exercise-behaviour`: every grep delivered check has a behaviour test twin in the boundary sketch.

No waivers.

## Out of scope

- Generators building at a chosen cadence (`freq='1min'`, the 1440 literals in `ev.py` and `load.py`, `pv.interpolate_to_minute_resolution`): S12, from the window.
- The default simulation window's constants (task 759, pending) and the web days window (task 593).
- Seasonal-factor normalisation (task 711, S12).
- `total_amounts`' NaN handling (task 660). `window.energy_kwh` sums as pandas does, and 660 changes both together.
- Dropping `simulation_days` from the two frozen finance signatures: the stream row keeps them (open question 6).

## Open questions

For the lead:

1. **`aggregate_annual`: delete (this PRD, γ2) or annualise?** D12 names "the annual aggregate" as a user of the rule. It has 0 `src` callers, and S25 already lists it as deletable. Suggested: S10 deletes it in γ2 and S25's deletable list drops it. If annualised instead, γ2 routes it through `annualisation_scale`, but it stays an orphan.
2. **Standing charge over `year_days` (decision 6).** This moves a default 2024 bill by one day's standing charge (e.g. +£0.60 at 60 p/day). Suggested: accept. The alternative keeps 365 days of standing charge against 366 days of energy.
3. **Surface posture.** Additive edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line (task 469's precedent). Only η's renames and retirements wait for S29. Confirm, or rule that additive edits wait too, which would hold α, β and ε behind wave 4 along with S12 and S25.
4. **D8's "end to end".** This PRD threads every integration site and leaves cadence choice to S12's generators (decision 4). Confirm no user-settable cadence option is wanted now.
5. **S8 ordering.** S8 moves `project_multi_year` out of `finance.py`. Suggested cross-reference: S8's move leaf depends on ε, so the move carries the window reads.
6. **At the S29 bump, also drop `simulation_days` from `householder_bill` and `bill_distribution`?** The summaries carry it. The stream row keeps the signatures; raise it with S29 if wanted.

Tactical, decided in the leaf:

7. `cli validate results` recovers local dates from a mixed-offset CSV by `pd.to_datetime(..., utc=True)` then converting to the default location's zone (suggested), or by a `--timezone` option. Decide in δ.
8. `SimulationResults.window` computed per access or cached (`functools.cached_property` works on a frozen dataclass). Decide in α by measuring a 527,040-row index.
9. The storage encoding of `timedelta` (ISO 8601 duration string or seconds). Decide in β with S19's format version in view.
