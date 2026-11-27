# Battery Sizing with Grid-Services Events: the Victron Sweep, Enrolled and Not

**Task:** #1707
**Code:** [`scripts/measure_battery_sizing.py`](../scripts/measure_battery_sizing.py) (`measure`, `first_homes`, `print_report`); [`src/solar_challenge/optimize.py`](../src/solar_challenge/optimize.py) (`enumerate_configs`, `run_sweep`, `rank`, `ReferenceComparison`)
**Tests:** [`tests/integration/test_battery_sizing_end_to_end.py`](../tests/integration/test_battery_sizing_end_to_end.py)
**Measurement:** [`scripts/measure_battery_sizing.py`](../scripts/measure_battery_sizing.py) (§2, §4), smoke-tested offline by [`tests/unit/test_measurement_scripts.py`](../tests/unit/test_measurement_scripts.py)

---

## 1. The Question

Does a larger battery earn back its extra capital cost once grid-services event income is
counted? PRD [`docs/prds/event-dispatch-and-battery-sizing.md`](prds/event-dispatch-and-battery-sizing.md)
§1 item 5 asks for the answer to be recorded here: the install sweep over the four Victron
configurations of its §2.3 on the board fleet, enrolled in the events and not, at the low,
central and high bands. §4 holds what the sweep returned.

## 2. How It Was Measured

From the worktree root of task 1707's branch (`task/1707`), on 2026-11-27, timed by
`/usr/bin/time -v`:

    uv run --locked --extra dev python scripts/measure_battery_sizing.py --homes 20 --workers 10

The script printed the commit it ran on, `2d2ad9bcfea320469133b4ba98a9a5674912a9ea`, with
no uncommitted change. That is `task/1707`'s commit "feat: measure_battery_sizing's main
prints each band's ranked table after the commit, homes, period, weather, install and events
it was measured on (event dispatch ζ, step-6)"; a rebase onto main rewrites the SHA, so the
subject names it. The commit that adds this document changes no code.

- **Population.** The first 20 of `scenarios/bristol-phase1-victron.yaml`'s 100 homes.
  `first_homes` scales the grant, `finance.grant_gbp`, to 20/100 of the scenario's £250,000.
  The grant is the one project total in `FinanceConfig`: every other cost is per home, per
  kWh or kW, or a fraction. So each per-home figure of the 20-home run stands for the
  100-home fleet at the same mix. This is this run's reading of PRD §2.2's "first 20 homes,
  scaled to 100", whose table was in fleet totals; the columns here are per home. Every home
  gets the same PV and battery, so the homes differ only in their load.
- **Period.** The scenario's own: 2024-01-01 to 2024-12-31, 366 days.
- **Weather.** PVGIS's TMY at Bristol (51.45, −2.58), scaled to PVGIS's 2005–2020 mean
  annual GHI ([`docs/tmy-irradiation-scaling.md`](tmy-irradiation-scaling.md)), read from
  the weather cache committed under `tests/fixtures/weather_cache`, the script's default
  `--cache-dir`. The run needs no network.
- **Workers and cost.** A process pool of 10 workers on a shared 32-core host, whose load
  average stood at about 170 to 190 when the run began. It took 1 h 33 min of wall clock,
  52 fleet simulations of 20 homes over the year, each 1 to 2.5 minutes. The largest
  process, the script's own, peaked at 10.6 GB resident (`/usr/bin/time`'s maximum
  resident set size, 10,582,108 kB): it holds one projection's simulated fleets at a time.
- **Install.** Every home has 4 kWp of PV on a 3.68 kW PV inverter (`PV_KWP`,
  `INVERTER_KW`). 4 kWp is the board pool's most common size and 3.68 kW is G98's
  single-phase limit. `optimize.enumerate_configs` installs them, as
  `solar-challenge optimize configs` does.
- **Configurations.** PRD §2.3's four (`BATTERIES`), each battery's nameplate kWh with its
  MultiPlus-II's power: 5.12 kWh at 2.4 kW and 10.24 kWh at 2.4 kW (48/3000), 10.24 kWh at
  3.68 kW and 15.36 kWh at 3.68 kW (48/5000 under G98).
- **Participation.** Dispatched is the scenario as it is set: every battery home enrolled in
  the drawn event windows, discharging at full power through each, within the 3.68 kW site
  export limit. Observed is the same events configuration un-enrolled
  (`participation: observed`): each home runs its own dispatch, and the events are priced
  from the spare capacity it leaves. The two sweeps differ in enrolment alone.

The report opened with what it was measured on:

```
solar_challenge 0.6.0
Commit: 2d2ad9bcfea320469133b4ba98a9a5674912a9ea
Scenario: /home/leo/src/solar-challenge/.worktrees/1707/scenarios/bristol-phase1-victron.yaml (Bristol Phase 1 Victron), its first 20 of 100 homes, the grant scaled to 20/100 of the scenario's: £50,000
Period: 2024-01-01 to 2024-12-31 (366 days)
Weather: PVGIS TMY at Bristol, UK (51.45, -2.58) from https://re.jrc.ec.europa.eu/api/v5_3/, scaled to its 2005-2020 mean annual GHI, read from the cache in /home/leo/src/solar-challenge/.worktrees/1707/tests/fixtures/weather_cache
Install: every home 4 kWp of PV on a 3.68 kW inverter, with a battery of 5.12 kWh at 2.4 kW; 10.24 kWh at 2.4 kW; 10.24 kWh at 3.68 kW; 15.36 kWh at 3.68 kW
Event window: months [11, 12, 1, 2], weekdays [0, 1, 2, 3, 4], hours [16, 17, 18], 12 events a year of 3 h
Events: delivery baseline operational, site export limit 3.68 kW while a battery exports, event-day seed 0, aggregator share 0.25, utilisation factor 0.6
Participation: dispatched enrols every battery home in the drawn windows; observed is the same events configuration un-enrolled, priced from the spare capacity its own dispatch leaves
```

## 3. How Each Column Is Computed

Each configuration is `optimize.run_sweep`'s own evaluation of that configuration: one
cost-recovery projection over the scenario's 25-year asset life. Each band's table ranks the
four results with `optimize.rank` and compares them with `optimize.ReferenceComparison`, as
`optimize configs` does.

- **Capex/home £** is `ConfigResult.capex_per_home_gbp`: the projection economics' total
  capex divided by the homes.
- **Extra capex/home £** and **Outlay change £/yr** are `ReferenceComparison`'s
  `extra_capex_per_home_gbp` and `outlay_change_gbp`. Each row is compared with the same
  participation's 5.12 kWh / 2.4 kW row at the same band, `optimize.default_reference`'s
  smallest battery at the smallest PV.
- **Solved own-use rate p/kWh** and **Outlay at solved rate £/yr** are the cost-recovery
  solve's. The solve finds the own-use rate at which the project keeps the scenario's
  retained-cash floor of £27 per home per year. The outlay is the representative
  householder's annual outlay at that rate.
- **Events income £/home/yr** is `ConfigResult.grid_services_income_per_home_gbp`: the
  year-1 (the projection's age-0) grid-services income per home, net of the aggregator's
  share, under the operational delivery baseline. Dispatched, it is priced from the
  delivery metered in the enrolled run on each drawn event day: the fleet's mean net import
  over the window on the 10 eligible days with no event nearest before the event day
  (completed with the nearest after), less its mean net import over the window on the event
  day, and 0 when that is negative. Observed, it is priced from the firm spare capacity the
  homes' own dispatch leaves on each eligible day the window covers.
- **Pays for itself** is `ReferenceComparison.pays_for_itself`: the configuration is
  feasible and its outlay is not above the reference's. This is the cost-recovery ranking's
  verdict (PRD §6 decision 4), not a payback or NPV test.
- **Rank** orders the feasible rows by outlay at the solved rate, as `optimize.rank` does. A
  row the solve cannot fund within the 23 p/kWh retail baseline would print `infeasible`;
  none did.
- **Bands.** A band changes only the rates the events are priced at
  (`gridservices.GRID_SERVICES_RATE_BANDS`). Each configuration was simulated once per
  participation, and its three bands were priced from those simulations.

## 4. What the Sweep Returned

The tables below are the script's standard output, pasted as printed.

### 4.1 Low Band

| Participation | Rank | Battery kWh | Battery kW | Capex/home £ | Extra capex/home £ | Solved own-use rate p/kWh | Outlay at solved rate £/yr | Outlay change £/yr | Events income £/home/yr | Pays for itself |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| dispatched | 1 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.71 | £643.54 | -£40.08 | £4.83 | yes |
| dispatched | 2 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.72 | £646.09 | -£37.53 | £4.92 | yes |
| dispatched | 3 | 15.36 | 3.68 | £8,844 | +£2,560 | 11.13 | £669.48 | -£14.14 | £10.98 | yes |
| dispatched | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.23 | £683.62 | +£0.00 | £0.99 | yes |
| observed | 1 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.57 | £631.99 | -£47.38 | £6.37 | yes |
| observed | 2 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.57 | £632.13 | -£47.24 | £5.63 | yes |
| observed | 3 | 15.36 | 3.68 | £8,844 | +£2,560 | 10.79 | £648.09 | -£31.27 | £12.13 | yes |
| observed | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.23 | £679.37 | +£0.00 | £1.19 | yes |

### 4.2 Central Band

| Participation | Rank | Battery kWh | Battery kW | Capex/home £ | Extra capex/home £ | Solved own-use rate p/kWh | Outlay at solved rate £/yr | Outlay change £/yr | Events income £/home/yr | Pays for itself |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| dispatched | 1 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.59 | £643.98 | -£39.05 | £9.84 | yes |
| dispatched | 2 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.58 | £647.43 | -£35.59 | £9.66 | yes |
| dispatched | 3 | 15.36 | 3.68 | £8,844 | +£2,560 | 10.78 | £658.08 | -£24.95 | £21.96 | yes |
| dispatched | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.20 | £683.03 | +£0.00 | £1.98 | yes |
| observed | 1 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.39 | £628.95 | -£50.06 | £12.74 | yes |
| observed | 2 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.41 | £635.24 | -£43.77 | £11.27 | yes |
| observed | 3 | 15.36 | 3.68 | £8,844 | +£2,560 | 10.36 | £645.80 | -£33.22 | £24.26 | yes |
| observed | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.21 | £679.01 | +£0.00 | £2.37 | yes |

### 4.3 High Band

| Participation | Rank | Battery kWh | Battery kW | Capex/home £ | Extra capex/home £ | Solved own-use rate p/kWh | Outlay at solved rate £/yr | Outlay change £/yr | Events income £/home/yr | Pays for itself |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| dispatched | 1 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.35 | £639.74 | -£42.10 | £19.67 | yes |
| dispatched | 2 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.34 | £643.18 | -£38.66 | £19.33 | yes |
| dispatched | 3 | 15.36 | 3.68 | £8,844 | +£2,560 | 10.08 | £646.57 | -£35.26 | £43.92 | yes |
| dispatched | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.13 | £681.83 | +£0.00 | £3.97 | yes |
| observed | 1 | 10.24 | 2.4 | £7,564 | +£1,280 | 9.07 | £623.24 | -£55.06 | £22.54 | yes |
| observed | 2 | 15.36 | 3.68 | £8,844 | +£2,560 | 9.51 | £625.68 | -£52.63 | £48.52 | yes |
| observed | 3 | 10.24 | 3.68 | £7,564 | +£1,280 | 9.05 | £628.84 | -£49.46 | £25.49 | yes |
| observed | 4 | 5.12 | 2.4 | £6,284 | +£0 | 8.17 | £678.30 | +£0.00 | £4.74 | yes |

Read off the tables:

- At every band and in both participations, every configuration is feasible, and every
  larger battery's outlay at the solved rate is below the 5.12 kWh reference's, so each
  pays for itself against it.
- In every row, the dispatched events income is below the observed income for the same
  configuration and band, and the dispatched outlay is above the observed outlay.
- The two 10.24 kWh configurations have the same capex, since the battery inverter is
  unpriced (§5). Their outlays differ by at most £6.29 a year in any band and participation.

## 5. What the Run Leaves Out

- **The bands are uncalibrated.** Calibrating the events rates is a separate gate,
  task 1708.
- **No hold-back.** The base dispatch runs until a window opens, and the battery then
  discharges at full power with whatever charge it holds (PRD §6 decision 3).
- **PV is not curtailed under the export limit.** The site export limit binds only while
  the battery exports.
- **The battery inverter is unpriced.** The scenario leaves
  `finance.battery_inverter_cost_per_kw_gbp` at 0, so the 48/5000's extra cost is not in the
  extra capex.
- **Charge power equals discharge power.** `--battery-kw`, and the `battery_kw` of each
  sweep point, sets both, so the 48/3000's 1.8 kW charge is not modelled.
- **One round-trip efficiency for both inverters.** Every point keeps the scenario's
  0.911 each way; the 48/5000's 96% is not modelled.
- **One PV size on every home.** The sweep installs 4 kWp everywhere, not the scenario's
  3 to 6 kWp pool.

## 6. Reproducing

The whole 100-home fleet, from the repository root:

    uv run --locked --extra dev python scripts/measure_battery_sizing.py --workers 10

Scaled from the 20-home run, expect about five times its wall clock, some 8 hours at 10
workers on a host as loaded, and about five times its peak memory, some 50 GB in the
script's own process, since it holds one projection's fleets of every home. It reads
Bristol's TMY from the committed weather cache, so it runs offline. `--homes N` keeps the
first N homes with their share of the grant, and `--start`/`--end` shorten the period; a
shortened period must hold an eligible weekday with no drawn event, which the operational
baseline meters each event day against.
