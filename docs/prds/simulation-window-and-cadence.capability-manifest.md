# Capability manifest — Simulation window and cadence (S10)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/simulation-window-and-cadence.md`. Each asserted capability binds to one kind of evidence:

- a symbol that is wired on main (`grep:<file>::<symbol>`);
- a producer in this batch that runs upstream (`producer:<label>`);
- a probe whose result was observed (`probe:`);
- an arithmetic identity (`identity:`).

The YAML twin `simulation-window-and-cadence.capability-manifest.yaml` carries the mechanical `delivered_check`s.

**Code anchors** verified against main `1251be0` (2026-10-14). Probes ran with `uv run --locked --extra dev python` (pandas 3.0.3). Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS, with one OPEN binding.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-extent-short`, `producer-downstream` or `rejection-absent`.

- **OPEN:** γ2's `aggregate_annual` deletion waits on the lead's open question 1.
- **External producer:** task 749 must land before δ.
- **Held leaf:** η is held for S29 and is excluded from this batch's `commit_planning` until S29 releases it.

---

## α — `timebase.SimulationWindow` and `SimulationResults.window` (intermediate; own library signal)

| capability asserted | evidence | status |
|---|---|---|
| `SimulationWindow`, `covered_days`, `of_index` refusals, the D12 properties, `energy_kwh` | `producer:α` (new in `timebase.py`; absent today: `git grep 'class SimulationWindow'` is empty) | PASS |
| `index.freq`, `.date()` on tz-aware rows, uniform-spacing test over int64 nanoseconds | pandas 3.0.3 `DatetimeIndex.freq`, `Timestamp.date`; `probe:` `pd.date_range(..., freq='1min').freq` is `<Minute>` | PASS |
| B1 numbers: 61, 2 and 184 calendar days (the timedelta gives 62, 2 and 185) | `probe:` the minute indexes for 2024-10-01..11-30, 2024-03-31..04-01 and 2024-07-01..12-31 (Europe/London) | PASS |
| B2: a dropped middle row is uneven where today's checks see none | `probe:` `step_hours(j)` and `step_hours(j[-2:])` both 1/60 h with row 700 deleted, so the first-against-last check misses it | PASS |
| B2: a `read_csv` index across DST is strings | `probe:` `read_csv(index_col=0, parse_dates=True)` on a 2024-03-30..04-01 export gives `pandas.Index` of dtype `str` | PASS |
| B3: the D12 table | `identity:` 366/30 = 12.2; 365.25/731; 365.25/400; 2024-01-01 + 399 days = 2025-02-03 (`probe:`) | PASS |
| `SimulationResults` power amounts multiply a static `HOURS_PER_MINUTE` today (the signal's "today Σ kW / 60") | `grep:home.py::_power` builds `_PerMinuteAmount(energy_column, HOURS_PER_MINUTE)`; `total_amounts` sums `series * amount.factor` | PASS |
| `from_dataframe` accepts any index (the 30-minute frame) | `grep:home.py::SimulationResults.from_dataframe` checks only for required columns | PASS |
| Surface: `FROZEN_MEMBERS["home.SimulationResults"]` pins members, so `window` is an additive entry | `grep:tests/unit/test_public_api_surface.py::FROZEN_MEMBERS`; precedent task 469 (`745c6b8`, `2dfd05d`) | PASS |

## β — summaries carry their window (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `calculate_summary`'s count is a timedelta today (62 for 2024-10-01..11-30) | `grep:home.py::calculate_summary` `sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1`; B1 probe | PASS |
| `results.window` | `producer:α` (upstream) | PASS |
| `home run` prints "Simulation Days" from the summary | `grep:cli/utils.py::create_summary_table` adds the row "Simulation Days" when the summary has `simulation_days`; `grep:cli/home.py::run` calls it | PASS |
| A stored summary round-trips nested dataclasses | `grep:web/storage.py::_serialize_value` / `_deserialize_value` recurse into dataclasses | PASS |
| …but not `date` and `timedelta` | `grep:web/storage.py::_serialize_value` handles only dataclass, `pd.Timestamp`, list, tuple and dict, so β adds two branches (`producer:β`) | PASS |
| Rejection: `SummaryStatistics(simulation_days=3, window=<2-day>)` raises | `producer:β` adds the check to `SummaryStatistics.__post_init__`, which exists and already refuses (`total_grid_charge_kwh`); β authors it and observes it fire | PASS |

## γ1 — the engine and integration sources read the window (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The engine takes a cadence parameter | `grep:flow.py::simulate_timestep` / `simulate_timestep_tou` `timestep_minutes: float = 1.0`; `grep:battery.py::Battery.charge` / `discharge` `duration_minutes` | PASS |
| `simulate_home` feeds it a literal | `grep:home.py::simulate_home` `timestep_minutes=1.0` (×2), `minute_kwh_to_kw = 1 / HOURS_PER_MINUTE` | PASS |
| B10 rejection: `simulate_community` refuses an uneven index | `producer:α` (`of_index` raises on unevenness); `grep:community.py::simulate_community` and `_price_grid_flows` call `step_hours`, so γ1 routes both through `of_index` and observes the refusal on B2's index | PASS |
| `load.calculate_annual_consumption` and heat-pump's degree-minute conversion integrate at a fixed minute | `grep:load.py::calculate_annual_consumption` `profile.sum() * HOURS_PER_MINUTE`; `grep:heat_pump.py::generate_heat_pump_load` `/ HOURS_PER_MINUTE` | PASS |

## γ2 — readers read the window; `step_hours` goes (leaf)

| capability asserted | evidence | status |
|---|---|---|
| 10 inline minute integrations in `output.py` | `grep:output.py::generate_summary_report` (heat-pump seasonal block) and `calculate_seasonal_metrics`, `.sum() * HOURS_PER_MINUTE`; the count is 13 in `src` with load.py and validation.py | PASS |
| B4 (output rows): constant-power twins are exactly equal | `identity:` 0.4 × 10,080 × 1/60 = 0.4 × 336 × 0.5 = 67.2 kWh; float error ≪ 1e-9 relative | PASS |
| B9: the 89-day window passes today's gate | `probe:` 2024-10-01..12-28 gives a timedelta count of 90 and a calendar count of 89; `grep:web/charts.py` monthly gate `sim_days < 90` | PASS |
| `step_hours` callers are gone after γ1 and γ2 | `grep:` `step_hours(` in `community.py` (γ1) and `output.py::compute_community_metrics` (γ2) only | PASS |
| `aggregate_annual` has no `src` caller | `grep:` `aggregate_annual` appears in `src` only at its definition (`output.py`); tests at `tests/unit/test_output.py` | OPEN: deletion awaits open question 1 |

## δ — validation scales by the window (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Signal premise: the 2023 half-hourly CSV reads 117 kWh today | `probe:` `solar-challenge validate results june30.csv --consumption-kwh 3504` on 2024-06-01..07 at 30 minutes printed FAIL at 116.8 kWh (the minute rule) | PASS |
| Signal number: 3,504 kWh after δ | `identity:` 0.4 kW × 336 rows × 0.5 h = 67.2 kWh; × 365/7 (2023, not leap) = 3,504.0. (A 2024 window would give 366/7 → 3,513.6, which is why the signal names 2023.) | PASS |
| DST CSV crashes today | `probe:` `validate results dst.csv` (2024-03-30..04-01 minute export) raised `TypeError: unsupported operand type(s) for -: 'str' and 'str'` in `_check_annual_yield` | PASS |
| The CLI reads the CSV | `grep:cli/validate.py::results` `pd.read_csv(csv_file, index_col=0, parse_dates=True)` | PASS |
| `_check_annual_yield`'s rule is in flight elsewhere | external producer task 749 (in progress, fk-756c0ef9e9d9) is upstream of δ | PASS (wire the dependency) |

## ε — finance bills through the window (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Rejection (INV-8): `bill_distribution(<2-day>, f, 1)` raises naming both | `producer:ε` adds it; today `grep:finance.py::householder_bill` / `bill_distribution` compare nothing (finding fk-1cd332300623's probe: no error) | PASS |
| `summary.window` | `producer:β` (upstream) | PASS |
| `bill` takes a fractional year | `grep:finance.py::bill` signature `period_days: float` | PASS |
| A 400-day window is unscaled today | `grep:finance.py::_annualisation_scale` returns 1.0 at or above `_SHORT_PERIOD_THRESHOLD` (360) | PASS |
| Leap-year standing charge is 365 today | `grep:finance.py::householder_bill` `period_days=float(_ANNUALISATION_DAYS)` | PASS |
| Finance tests build summaries centrally | `grep:tests/_finance_builders.py` | PASS |
| `MultiYearCurve` and `_NodeData` are off the frozen surface (a required field is free) | `grep:tests/unit/test_public_api_surface.py` names neither | PASS |
| `review/briefing.yaml` has a conventions block for INV-8's line | `grep:review/briefing.yaml` `conventions:` | PASS |

## ζ — board outputs and CLI counts read the window (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `finance run` bills a CLI-computed day count today | `grep:cli/finance.py::run` `days = (end_date - start_date).days + 1` passed to `bill_distribution` (×2) | PASS |
| `finance run` is drivable offline with a fake fleet simulator | `grep:cli/utils.py::CliFleetSimulator`; `tests/_cli_fleet_simulator.py` exists | PASS |
| `annualised_from` on `BillDistribution` | `producer:ε` (upstream) | PASS |
| Both board reports are rendered in `output.py` | `grep:output.py::generate_finance_report` (called by `cli/finance.py::run`), `generate_config_ranking_report` (called by `cli/optimize.py::configs`) | PASS |
| `optimize`'s report reaches a `BillDistribution` | `grep:optimize.py::ConfigResult.solution` (a `CostRecoverySolution` whose `outlay` is a `BillDistribution`) | PASS |
| B8 number: ×183.000 | `identity:` 2024 is leap, and the window is within one year: 366/2 = 183 | PASS |

## η — surface bump edits (held for S29)

| capability asserted | evidence | status |
|---|---|---|
| The names to rename or retire exist today | `grep:finance.py::householder_bill` `annual_self_consumption_kwh`; `grep:home.py::SimulationResults.per_minute_amounts`; `grep:` `timestep_minutes: float = 1.0` in `flow.py` and `dispatch.py` | PASS |
| The coordinated bump exists to release it | S29 (program stream, wave 4) | PASS (held via `x_seam_wait`) |
| The defaults may sit on signatures S3 rewrites | S3 lands before S29; η edits whatever signatures exist then | PASS |
