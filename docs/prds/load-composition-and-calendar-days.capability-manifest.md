# Capability manifest: load composition and calendar days (S12)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/load-composition-and-calendar-days.md`. Each asserted capability binds to one kind of evidence:

- `grep:<file>::<symbol>`: a symbol wired on main;
- `producer:<label>`: a producer in this batch, upstream of the leaf;
- `task:<id>`: a filed producer outside the batch, wired as a dependency;
- `probe:`: an observed result;
- `identity:`: an arithmetic identity.

The YAML twin `load-composition-and-calendar-days.capability-manifest.yaml` carries the mechanical `delivered_check`s.

**Code anchors** verified against main `1fa8f79` (2026-10-16), with task 708's code read from `task/708` at `44eecaa`. Probes ran with `uv run --locked --extra dev python -I` in the main checkout. Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: OPEN (blocks decompose, as the brief requires).** Three bindings name producers that are not yet filed:

- S11 δ (γ);
- S13's hand-off leaf (β);
- S21 δ and α (ε).

Each turns PASS when the lead hands back the filed id and the edge is wired. No binding resolves to `declared-only`, `test-only`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. ζ is held for S29.

---

## α: calendar-day iterator in `timebase` (intermediate; own library signal)

| capability asserted | evidence | status |
|---|---|---|
| `SimulationWindow` with `first_day`, `last_day`, `cadence`, `timezone`, `of_index` | `task:777` (S10 α, pending; its description specifies these fields) | PASS (upstream, wired α → 777) |
| No iterator exists today: generators count `n_days × 1440` | `grep:ev.py::generate_ev_charging_profile` `n_minutes = n_days * 1440`; `grep:load.py::_generate_elexon_profile` positional `while current_date <= end_date` loop | PASS |
| A local-midnight-to-midnight `date_range` gives 1,380 / 1,500 rows with `freq` set | `probe:` 2024-03-31 → 1,380 rows, `freq <Minute>`, row 60 is 02:00+01:00; 2024-10-27 → 1,500 rows, minute-of-day 60 occurs twice | PASS |
| B1's 4,260 rows | `identity:` 1,440 + 1,380 + 1,440 | PASS |
| B1's 30-minute days 48/46/48 | `identity:` 1,440/30, 1,380/30, 1,440/30 | PASS |
| `of_index(w.rows()) == w` | `task:777`: `of_index` reads `index.freq` and `index[0].date()`, `index[-1].date()` in the index's zone; `rows()` sets `freq` and spans the window's dates exactly | PASS |
| Rejection: a cadence not dividing one hour is refused | `producer:α` authors the refusal in `rows()`/`local_days()`; B1 observes it fire for 7 minutes | PASS |

## β: household load on calendar days, a calendar year exact (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Today the 2024-04-04 peak depends on the window: 18:30+01:00 (from 03-25) vs 17:30+01:00 (from 04-03) | `probe:` `generate_load_profile(LoadConfig(3400, use_stochastic=False), …)` at `1fa8f79` | PASS |
| After the fix, 17:30+01:00 for both | `identity:` `ELEXON_PROFILE_CLASS_1` peaks first at half-hour index 35 (0.046, 17:30) on the wall clock; per-day placement makes the day independent of the window | PASS |
| Today's end bounds: 00:59+01:00 and 22:59+00:00 | `probe:` 2024-03-30..31 and 2024-10-26..27 windows | PASS |
| Today's totals: 3,325.01 (2023) and 3,336.19 (2024), both paths | `probe:` Elexon and seed 42; day-weighted means 0.97795 and 0.97855 | PASS |
| 3,400 exactly after | `identity:` Σ over year Y of `SEASONAL_FACTORS[m(d)] / Σ_Y SEASONAL_FACTORS[m(d')]` = 1; deterministic days carry `E_d` exactly, and the stochastic window is scaled once to Σ `E_d` | PASS |
| `home run` prints Total Demand from the summary | `grep:cli/utils.py::create_summary_table` "Total Demand"; `grep:cli/home.py::run` calls it; `--start`/`--end`/`--output` options exist | PASS |
| The CSV holds `demand_kw` per row | `grep:output.py::export_to_csv` writes `results.to_dataframe()`; `grep:home.py::SimulationResults` `demand` column `demand_kw` | PASS |
| `load.energy_kwh` integrates through the window; `simulate_home` derives the run's window | `task:779` (S10 γ1, pending); β replaces its `of_index` derivation of the run index with the constructed window | PASS (upstream, wired β → 779) |
| The injectable per-day simulator B3 drives | S13's hand-off leaf (S13 unauthored; program remedy: "The per-day simulator is an injectable parameter of generate_load_profile") | **OPEN**: id from the lead; wire β → it |
| Rejection: an error in the scaling step propagates (no fallback) | `producer:β` moves scaling outside the `try`; B3 raises inside it and observes the error, not an Elexon profile | PASS |
| fk-89777ec9faad is not double-filed | task 711 (pending, no commits on `task/711`) superseded by β at decompose (PRD Q1); if the lead keeps 711, β depends on it and drops the key | PASS (either ruling) |

## γ: EV on calendar days, out of the household model, following the tariff and PV (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The one-session scheduler (`_daily_session`, `_earliest_best_start`) that γ generalises from minute flags to row weights | `task:708` (pending; implemented on `task/708` at `44eecaa`, not merged) | PASS (upstream, wired γ → 708) |
| `_earliest_best_start`'s cumulative-sum selection works for float weights | `grep:task/708 ev.py::_earliest_best_start` uses `np.cumsum(preferred)` and `argmax`; the arithmetic is the same for floats, earliest on a tie (`argmax` returns the first maximum) | PASS |
| `off_peak` weights: the tariff's cheap minutes of day; `require_tariff_for_smart_charging` | S11 δ (`tariff-coverage-classifier-presets.md` §5.6; not filed: the sidecar's `task_id` is null) | **OPEN**: id from the lead; wire γ → it |
| `solar` weights: PV generation on any rows | `grep:weather.py::align_tmy_to_index` maps any index by UTC time of year; `grep:home.py::simulate_home` holds the TMY-year `minute_generation` before alignment | PASS |
| Today the session starts 19:00 BST after the spring change; the one-day overnight off-peak run charges 0.0 kWh; 30 kWh at 3.6 kW charges 501 minutes | finding fk-1d920c89e872 (re-observed); task 725's observation (`EVConfig('7kW', 18, 8, 35, 'off_peak')`, one day: 0.0 kWh); task 726's observation (501 minutes, 30.06 kWh) | PASS |
| 35.0, 245.0, 175.0 and 30.0 kWh after | `identity:` 35/7 = 5 h = 300 whole rows; carry-in (00:30–05:29 of the window's first morning) + 6 in-window evenings → 7 sessions; `none` sessions end 23:00 the same day → 5 sessions; 30/3.6 h = 500 rows with a zero-fraction remainder under the 1e-9 tolerance | PASS |
| E10's 00:00–04:59 session is unchanged | S11 δ's signal (§9 row 15) on the same weights | PASS (with S11 δ) |
| EV leaves `load.py`: the function-local import and the TYPE_CHECKING import go | `grep:load.py::generate_load_profile` `from solar_challenge.ev import generate_ev_charging_profile` (function-local) and `TYPE_CHECKING` `EVConfig` | PASS |
| The `load → ev` allow-list entry exists to delete | `task:775` (S1 γ, pending) creates `tests/unit/test_import_structure.py` (S1 PRD: "S12 removes 1 (load → ev)") | PASS (upstream, wired γ → 775) |
| `simulate_home`'s weather is an argument when γ reorders PV before demand | `task:809` (S15 β, pending) | PASS (upstream, wired γ → 809) |
| `scenario_writer` must write the enum's value | `probe:` `yaml.safe_dump({'charger_type': <str-Enum>})` raises `RepresenterError`; `json.dumps` writes `"7kW"`; `grep:scenario_writer.py::_ev_block` writes `ev.charger_type` as is | PASS |
| `EVChargerType` and `SmartChargingMode` exist with exactly the accepted values | `grep:ev.py::EVChargerType` (`3.6kW`, `7kW`, `22kW`); `grep:ev.py::SmartChargingMode` (`none`, `solar`, `off_peak`) | PASS |
| `generate_load_profile` and `generate_ev_charging_profile` are not on the frozen surface | `grep:__init__.py::__all__` lists neither; `grep:tests/unit/test_public_api_surface.py` pins `ev.EVConfig`'s form only | PASS |
| Rejection: a solar EV without `generation_kw`, and a charger type outside the enum, are refused by name | `producer:γ` authors both; B5 and γ's tests observe them fire | PASS |

## δ: named load series on results and summaries (intermediate; own CLI signal)

| capability asserted | evidence | status |
|---|---|---|
| Results carry series by field metadata today; `heat_pump_load` maps to `heat_pump_load_kw` | `grep:home.py::SimulationResults` `heat_pump_load … _power("heat_pump_load_kw", "heat_pump_load_kwh")`; `_series_columns`, `to_dataframe`, `from_dataframe` | PASS |
| Stored runs keep `heat_pump_load_kw`, so the frame needs no transform | `grep:web/storage.py::save_home_run` writes `results.to_dataframe()` to `data.parquet`; `load_home_run` reads it with `SimulationResults.from_dataframe` | PASS |
| A summary dict round-trips through the codec | `grep:web/storage.py::_deserialize_value` returns a dict unchanged for a non-dataclass annotation, and `SummaryStatistics.__post_init__` coerces the keys (δ) | PASS |
| `SummaryStatistics.__post_init__` exists and refuses | `grep:home.py::SummaryStatistics.__post_init__` (the `total_grid_charge_kwh` refusal) | PASS |
| The TMY-year rule is spelled twice | `grep:home.py::_YEAR_LENGTHS_IN_HOURS`; `grep:heat_pump.py::_YEAR_LENGTHS_IN_MINUTES`; both from `heat_pump.reference_year_lengths` | PASS |
| The heat pump is composed in `home` | `grep:home.py::_demand`, `_heat_pump_load` | PASS |
| `SummaryStatistics` and `home.SimulationResults` forms are pinned, so the new fields are additive entries | `grep:tests/unit/test_public_api_surface.py::FROZEN_SURFACE["SummaryStatistics"]`, `FROZEN_CLOSURE["home.SimulationResults"]`, `FROZEN_MEMBERS["home.SimulationResults"]`; precedent task 469 | PASS |
| Household load and EV both on `window.rows()` | `producer:β`, `producer:γ` (upstream) | PASS |
| B6's sum identity | `identity:` `loads[HOUSEHOLD]` is defined as `demand − Σ additional` | PASS |
| Rejection: HOUSEHOLD among `additional_loads`, a mismatched index, a negative residual, an unknown summary key | `producer:δ` authors each in `__post_init__`/`compose_demand`; B6 and B7 observe each fire | PASS |

## ε: reports and panels iterate the named loads (leaf; integration gate)

| capability asserted | evidence | status |
|---|---|---|
| The heat-pump report section and seasonal block exist to replace | `grep:output.py::generate_summary_report` `if summary.total_heat_pump_load_kwh is not None`, `if results.heat_pump_load is not None` | PASS |
| `aggregate_annual`'s three branches are deleted upstream | `task:780` (S10 γ2, pending; L9) | PASS (upstream, wired ε → 780) |
| `home run --report` prints the report | `grep:cli/home.py::run` `print_report(generate_summary_report(…))` | PASS |
| `ChartPanel`, the tab assembler, the emptiness rule | S21 δ (`chart-panels-and-theme-tokens.md`; not filed) | **OPEN**: id from the lead; wire ε → it |
| Chart roles in `theme-tokens.json` | S21 α (not filed) | **OPEN**: id from the lead; wire ε → it |
| The results page draws the heat pump's charts from the results today | `grep:web/routes.py` `"heat_pump": heat_pump_analysis(sim_results)`; `grep:web/charts.py::heat_pump_analysis`; `grep:results/home.html` `{% if charts.heat_pump %}` | PASS |
| Named loads on results and summaries | `producer:δ` (upstream) | PASS |

## ζ: retire the per-kind fields and type the EV config at the bump (held for S29)

| capability asserted | evidence | status |
|---|---|---|
| `RunDocumentStep`, `RUN_DOCUMENT_STEPS`, `web migrate`, the strict reader | `task:822` (S19 κ, pending) | PASS (upstream, wired ζ → 822) |
| The three summary fields and `heat_pump_load` exist to retire | `grep:home.py::SummaryStatistics` `total_heat_pump_load_kwh`, `peak_heat_pump_load_kw`, `heat_pump_load_ratio`; `grep:home.py::SimulationResults` `heat_pump_load` | PASS |
| B9's 3,000 | `identity:` 5,400 − 2,400 | PASS |
| `EVConfig` fields annotated `str` today | `grep:tests/unit/test_public_api_surface.py` `"ev.EVConfig": "dataclass[eq, frozen] (charger_type: str, …, smart_charging_mode: str = 'none', …)"` | PASS |
| Released by S29 | program D4/D29; `x_seam_wait = {stream: S29, contract: "the surface bump release window"}` | PASS (held) |
