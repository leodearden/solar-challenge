# Self-Consumption Benchmarks: PV Only and with a Battery

**Task:** #818
**Code:** [`src/solar_challenge/validation.py`](../src/solar_challenge/validation.py) (`validate_self_consumption_pv_only`, `validate_self_consumption_with_battery`, `UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT`, `UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT`)

---

## 1. What the Checks Measure

- A run's ratio is `calculate_summary(results).self_consumption_ratio` as a percentage:
  the PV energy the home uses, directly or through its battery, over the PV generated.
  `flow.py` counts direct use plus battery discharge, capped at demand. That is MGD 003
  §2's definition.
- MGD 003 §3.12 assumes a battery run in self-consumption mode. A battery that also
  charges from the grid inflates the figure, as `review/briefing.yaml`'s Basis-C own-use
  convention notes.
- Each check passes inside its band, edges included. Its message states the band
  applied, and `expected_range` is the band.
- Outside the band, a note may say whether the run's PV is large or small relative to
  its consumption: its own generation total over its own demand total.
  - The battery check's other note compares the battery's capacity with a day of the
    run's own demand: its demand total over its days.
  - Until task 818 the PV notes guessed generation as nameplate kW × 900 kWh, so one
    run read differently under a 1 kW and a 6 kW nameplate. The battery note took its
    day from the target annual consumption, which can differ from the run's demand.
  - The notes are hints, and none changes whether a check passes. Their thresholds
    have no source. The checks' first version (4b208f4) set them when VAL-003 and
    VAL-004 (`git show 672cedb:feature_list.json`) asked a check outside its range to
    document its assumptions, and task 818 kept their values. Nothing records why the
    battery check's PV thresholds sit further from 1 than the PV-only check's.
- `validate_simulation` runs the battery check for a capacity above zero, else the
  PV-only one, and neither without a target annual consumption.

## 2. The Bands Are Sourced from MCS MGD 003

- The bands are PV only 10–45% and with a 5 kWh battery 35–90%. Each is the range
  MGD 003's lookup tables give the archetype below, rounded outward to the next 5
  percentage points. The two constants in `validation.py` are the single source of the
  numbers; this note transcribes them.
- **Reference.** MCS, MGD 003 Issue 2.0, *Solar PV Self-Consumption* (01/04/2022),
  prepared for MCS Working Group 2 by Advance Further Energy, BRE National Solar Centre
  and Loughborough University.
  - MIS 3002 Issue 6.0 (18/03/2026) §4.1.2 requires MCS installers' self-consumption
    estimates to follow it.
  - Its §7 tables give the average self-consumption of homes alike in four respects:
    occupancy archetype, annual consumption (one table per 500 kWh), annual generation
    (300 kWh rows) and usable battery capacity (1 kWh columns).
  - They rest on Loughborough University's research into domestic consumption and its
    occupancy profiles, with battery modelling developed with Advance Further Energy and
    validated by BRE National Solar Centre (§1).
- **Scope.** The archetype the checks' docstrings name, in MGD 003's terms:
  - a home using 3,000–3,499 kWh a year: the table holding 3,400 kWh, the consumption
    the docstrings gave until task 818;
  - any of the three occupancy archetypes, since a run carries no occupancy: Home all
    day, In half the day and Out during the day (Table 4-1 calls the last Out all day);
  - 4 kWp of unshaded PV facing within 90° of south, at any pitch, anywhere in the UK:
    the annual-yield band's scope ([pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §2).
    - MGD 003 takes generation from MIS 3002's kWp × Kk (§2, §3.11, §4.4), and MCS's Kk
      for that scope runs from 394 to 1,132 (§5 of that note).
    - So the array generates 1,576–4,528 kWh: the rows 1,500–1,799 to 4,500–4,799 kWh;
  - for the battery band, a 5 kWh battery holding 3.1–5.0 kWh usable: the columns
    ≥3.1 <4.1 and ≥4.1 <5.1.
    - `BatteryConfig.default_5kwh()` holds 4.0 kWh between its 10% and 90% charge
      limits, before ageing.
    - MGD 003 §4.5.4–4.5.5 counts a 5 kWh battery with no stated usable capacity as
      4.5 kWh, at 90% depth of discharge.
    - The default also meets §3.11's battery assumptions. Its round trip is 0.975² ≈ 95%,
      against a floor of 80%. It charges fully in under 2 hours at 2.5 kW, against a
      limit of 6.
- A ratio falls as generation rises and as the home is empty for more of the day, so
  each band's edges come from two corners:

| Check | Lowest in scope | Highest in scope | Band |
|---|---|---|---|
| PV only | 13%: Out during the day, 4,500–4,799 kWh (Table 7-22) | 43%: Home all day, 1,500–1,799 kWh (Table 7-4) | 10–45% |
| 5 kWh battery | 36%: Out during the day, 4,500–4,799 kWh, ≥3.1 <4.1 kWh (Table 7-22) | 89%: Home all day, 1,500–1,799 kWh, ≥4.1 <5.1 kWh (Table 7-4) | 35–90% |

- `tests/unit/test_validation.py` copies the four corner figures as ratios that must
  pass; a new MGD 003 issue that moves them moves the copies too.
- MGD 003 rounds its cells to whole percentages (§4.6.7). Rounding outward to the next
  5 points also covers that rounding.
- **Corroboration.**
  - McKenna, Pless and Darby (2018) metered 302 homes with PV in north-east England at
    one-minute resolution, April 2012 to March 2014. They averaged 45%
    self-consumption, with 1.95 kW of PV and 4,366 kWh a year of demand.
  - They estimate 37.3% ± 1.5% for an average home of 4,000 kWh a year with 2.9 kWp.
  - Both have less PV relative to demand than the archetype, and MGD 003 gives such
    homes higher ratios too.
  - DECC's 2015 feed-in tariff review assumed 25–45% (DECC 2015, p. 31, as McKenna et
    al. report).
  - No published measurement of UK homes with batteries was found to corroborate the
    battery band.
- The bands are not derived from the model. Fitting them to its output would make the
  benchmark circular, unable to catch the model it checks; §4 is a check only.
- **What a FAIL means:** a ratio that no in-scope home reads in MGD 003. Either:
  - the home is off the archetype, with more or less PV for its consumption (a note may
    say which way); or
  - the dispatch is wrong, e.g. self-consumption counted beyond generation, or a battery
    that never discharges.

  The bands are wide because a run carries no occupancy, site or orientation; §3 has
  the narrower cells.
- **History.**
  - Until task 818 the PV-only check applied 20–45% while its docstring said ~25–35%,
    and the battery check applied 50–90% while its docstring said ~60–80%. Neither band
    had a source.
  - On 2026-10-22 the dashboard assistant's `METRIC_TABLE` said 30–40% and 55–70%,
    citing "Solar Energy UK / BEIS smart export data 2022–2024". No such publication was
    found on 2026-10-19.

## 3. The Reference's Figures

This is a dated record. Re-read MGD 003 before relying on it.

- **Provenance.** Read 2026-10-19, and re-read 2026-10-22 with `pdftotext -layout`, from
  <https://mcscertified.com/wp-content/uploads/2022/04/MGD-003-Solar-PV-Self-Consumption-Issue-2.0-Final.pdf>,
  §7.
  - The tables used are 7-4 (Home all day), 7-13 (In half the day) and 7-22 (Out during
    the day), each for 3,000–3,499 kWh a year.
  - MCS also publishes the tables unrounded, as spreadsheets (§4.6.7).
  - The corroborating paper is McKenna, E., Pless, J. and Darby, S. J. (2018), Energy
    Policy 118, 482–491, doi:10.1016/j.enpol.2018.04.006. Its accepted manuscript is on
    UCL Discovery, eprint 10047969.
- PV only, % of annual generation:

| Annual generation | Home all day | In half the day | Out during the day |
|---|---|---|---|
| 1,500–1,799 kWh | 43 | 36 | 27 |
| 3,600–3,899 kWh | 26 | 22 | 15 |
| 3,900–4,199 kWh | 25 | 21 | 14 |
| 4,500–4,799 kWh | 23 | 19 | 13 |

- With a battery, % of annual generation, in each archetype's two usable-capacity
  columns, ≥3.1 <4.1 kWh and ≥4.1 <5.1 kWh:

| Annual generation | Home all day, ≥3.1 <4.1 | Home all day, ≥4.1 <5.1 | In half the day, ≥3.1 <4.1 | In half the day, ≥4.1 <5.1 | Out during the day, ≥3.1 <4.1 | Out during the day, ≥4.1 <5.1 |
|---|---|---|---|---|---|---|
| 1,500–1,799 kWh | 86 | 89 | 82 | 87 | 75 | 82 |
| 3,600–3,899 kWh | 55 | 60 | 51 | 57 | 44 | 50 |
| 3,900–4,199 kWh | 52 | 56 | 48 | 53 | 41 | 47 |
| 4,500–4,799 kWh | 47 | 51 | 43 | 48 | 36 | 42 |

- 3,600–3,899 kWh is 4 kWp in Bristol's MCS zone, 5E (MIS 3002 Appendix B: BS), facing
  south at 35°: Kk 971, so 3,884 kWh. 3,900–4,199 kWh holds the model's Bristol year
  (§4).
- Over the scope's eleven rows, 1,500–1,799 to 4,500–4,799 kWh, no column used here
  rises from one row to the next in any of the three tables. So the corners are the
  extremes.
- MGD 003 caps self-consumption at 95% of generation (§4.6.9). An installer who does not
  know the occupancy uses In half the day (Table 4-1).

## 4. Where the Model Sat

This is a dated record. Re-measure before relying on it.

- **Setup.** Measured 2026-10-22 on main de776fe, with CPython 3.12.3, pvlib 0.15.1,
  pandas 3.0.3, numpy 2.4.6 and richardsonpy 0.2.3. The model ran with NOCT-SAM cell
  temperatures ([pv-cell-temperature.md](pv-cell-temperature.md)) and the system losses,
  on the scaled TMY.
- **Method.** `simulate_home(HomeConfig(pv_config=PVConfig(capacity_kw=4.0),
  load_config=..., battery_config=...), 2023-01-01, 2023-12-31,
  weather=PvgisTmy(WeatherCache(...)))`, then `calculate_summary`.
  - `load_config`: `LoadConfig(annual_consumption_kwh=3400.0)` with seed 1–6, or with
    `use_stochastic=False` for the deterministic Elexon profile;
  - `battery_config`: None, or `BatteryConfig.default_5kwh()`;
  - weather: the `WeatherCache` holding Bristol's cached TMY.
- The year generated 4,052.8 kWh against 3,325.0 kWh of demand (1.219).
- PV only: 23.8–25.0% over richardsonpy seeds 1–6, and 33.9% on the Elexon profile.
- With the battery: 54.8–56.1% over the same seeds, and 58.1% on the Elexon profile.
- All read inside their bands. Against the 3,900–4,199 kWh row:
  - the seeded PV-only ratios sit between In half the day's 21% and Home all day's 25%;
  - the Elexon PV-only ratio and every battery ratio read above Home all day: 25% PV
    only, and 52% at ≥3.1 <4.1 kWh, the default battery's column.

## 5. When to Revisit

- MCS publishes a new MGD 003 issue or spreadsheet, or MIS 3002 stops requiring it.
- The docstrings' archetype changes, or the default battery's usable capacity leaves
  3.1–5.0 kWh.
- The annual-yield band's scope or MCS's Kk tables change, since the generation range
  comes from them.
- Validation learns a run's occupancy, site or orientation, so that a check could apply
  the run's own MGD 003 cell.
