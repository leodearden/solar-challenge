# Scheduled-Charge Windows: a Victron GX's Forced Grid Charge, Wrapping a Base Strategy

**Task:** #1016
**Code:** [`src/solar_challenge/dispatch.py`](../src/solar_challenge/dispatch.py) (`ChargeWindow`, `ScheduledChargeStrategy`); [`src/solar_challenge/home.py`](../src/solar_challenge/home.py) (`simulate_home(..., strategy=...)`)
**Tests:** [`tests/unit/dispatch/test_scheduled_charge_strategy.py`](../tests/unit/dispatch/test_scheduled_charge_strategy.py); [`tests/unit/test_home_scheduled_charge.py`](../tests/unit/test_home_scheduled_charge.py)
**Measurement:** [`scripts/measure_charge_window_bills.py`](../scripts/measure_charge_window_bills.py) (§3, §4), smoke-tested offline by [`tests/unit/test_measurement_scripts.py`](../tests/unit/test_measurement_scripts.py)

---

A Victron GX's "Scheduled charge levels" open a window each day in which the device
force-charges the battery from the grid to a target state of charge, overriding any
dispatch setpoint, then holds it there; `allow_discharge` governs discharge above the
target while the window is open. `ScheduledChargeStrategy(base, windows, tz)` models that
schedule: inside a window the window decides the step, and outside every window `base`
decides it, given every argument unchanged.

## 1. The Rules

1. **A window grid-charges only when the engine offers a `GridChargeContext`, and then
   whatever the rates.** `flow.simulate_timestep` offers one when the run has a tariff and
   `BatteryConfig.grid_charging` is set. The window applies neither the cheap-period gate
   nor the spread gate of `compute_grid_charge_power_kw`: it is the device's schedule, not a
   price signal. Reason: `decide_action`'s contract says that no context means no grid
   charging, and a GX whose grid charging is disabled runs no charge windows. Without a
   context a window still holds (rule 4).
2. **The target is `target_soc_fraction` of the `battery_capacity_kwh` that `decide_action`
   is given.** Reason: the strategy takes every battery fact from `decide_action`'s inputs,
   so it keeps no second copy of limits a `Battery` lets callers reassign. Today the engine
   passes the nominal capacity, the basis TOU and peak-shaving grid charging use too; when
   it passes the SoH-derated capacity, the windows follow with no change.
   `max_soc_fraction` stays the battery's own ceiling: `Battery.charge` stores nothing past
   `max_soc_kwh`, so a target above it asks for grid power that stores nothing.
3. **Grid power fills the gap left after the step's PV charge, within the `max_charge_kw`
   headroom that charge leaves.** The SOC after the PV charge is predicted as
   `Battery.charge` stores it, `soc + min(pv, max_charge_kw) × dt_h × charge_efficiency`;
   the grid power is `min(gap / charge_efficiency / dt_h, max_charge_kw − min(pv,
   max_charge_kw))`, and 0 once the gap is closed. Reason: the engine charges the PV excess
   first and the grid power after it, both through one `max_charge_kw`, so sizing from the
   SOC before the PV charge would overshoot the target in a sunny minute.
4. **At or above its target a window holds.** It neither grid-charges nor, unless rule 5
   applies, discharges. In every case short of discharging it charges the whole PV excess,
   as the built-in strategies do. Reason: the GX holds the battery at its scheduled level
   until the window closes.
5. **`allow_discharge` covers a shortfall only down to the target.** Above the target, a
   window that allows discharge discharges `min(shortfall_kw, (soc − target_kwh) / dt_h)`.
   Reason: Victron's self-consumption above the scheduled limit uses the battery down to
   that limit. Discharging the whole shortfall whenever the SOC is above the target would
   flip a one-minute model between a full-shortfall discharge and a grid top-up every other
   minute: by estimate, about 0.75 kWh of needless grid charge over the engine test's two
   hours of 1 kW shortfall from 3.0 kWh. With the cap the battery undershoots the target by
   at most the discharge loss, about 4.3e-4 kWh at 1 kW, and is topped up once; that test
   grid-charges under 0.01 kWh.
6. **Windows open on the declared zone's wall clock, and a window crossing midnight
   belongs to the day it opens.** `tz` must be a `ZoneInfo`, and each timestamp is read on
   its wall clock. A window covers `[start, start + duration)` of each day it opens on:
   `days` lists the `date.weekday()` numbers (Monday 0 … Sunday 6) of the opening day, or
   is `'daily'`, and `duration` is at most a day, so a window covers the next morning only
   when it opened the day before. Reason: the GX schedules on its local clock, a slot's day
   being the day it starts; on a clock-change day a wall-clock window is an hour shorter
   or longer, as the device's is.
7. **The first listed window open at a step governs it.** Reason: simple, deterministic
   and tested; Victron's own rule for overlapping slots is not documented here, so it is
   not guessed.
8. **A naive timestamp is refused**, with a `ValueError` naming the zone. Reason: reading a
   naive UTC index as local time would put every window an hour out in summer.
   `ChargeWindow` and the constructor refuse a value they cannot schedule with
   `ConfigurationError`, naming the field and the value; a bad `decide_action` input raises
   the `ValueError` the sibling strategies raise.

## 2. Use

`ChargeWindow` and `ScheduledChargeStrategy` are outside `solar_challenge.__all__`, so
import them from `solar_challenge.dispatch`. `simulate_home`'s keyword-only `strategy` runs
the battery under them in place of the dispatch the `HomeConfig` selects, through
`flow.simulate_timestep` at the home's tariff; the windows therefore grid-charge only on a
home with a tariff and `BatteryConfig.grid_charging`. The results' `strategy_name` is the
strategy's name, `scheduled_charge(<base name>)`.

```python
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from solar_challenge.dispatch import ChargeWindow, ScheduledChargeStrategy, SelfConsumptionStrategy
from solar_challenge.home import simulate_home

windows = (ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, allow_discharge=False),)
strategy = ScheduledChargeStrategy(SelfConsumptionStrategy(), windows, ZoneInfo(home.location.timezone))
results = simulate_home(home, start, end, weather=weather, strategy=strategy)
```

## 3. The Year Harness

`scripts/measure_charge_window_bills.py` bills the home of
`scenarios/bristol-arbitrage.yaml`, read as `home run` reads it, under four arms:

| Arm | Dispatch |
|---|---|
| A | The home as configured: `tou_optimized` on the tariff's clock (`simulate_timestep_tou`), grid-charging to `GridChargeConfig(0.9)` in the cheap period |
| B | `ScheduledChargeStrategy` over `TOUOptimizedStrategy([(0, 1), (7, 24)])` |
| C | `dispatch_strategy="greedy"` with `grid_charging=None`: self-consumption only |
| D | `ScheduledChargeStrategy` over `SelfConsumptionStrategy()` |

B and D share one window, daily from 00:30 for 7 hours to 0.9, holding, on
`Europe/London`. It mirrors Economy 7's clock: off-peak from 00:30 to 07:30 at £0.09/kWh,
peak from 07:30 to 00:30 at £0.25/kWh, on the same wall clock.

**B's base peak hours.** `TOUOptimizedStrategy`'s peak hours are whole hours, so they
cannot express 00:30 or 07:30. Outside the window B's base must dispatch as at the dear
rate. `[(0, 1), (7, 24)]` makes every hour peak but 01:00 to 07:00, and the only cheap
minutes those peak hours hold, 00:30 to 01:00 and 07:00 to 07:30, lie inside the window,
where the window decides.

**Why B and D reproduce A minute for minute.** In the cheap period A charges the PV excess,
then grid-charges from the SOC that charge leaves to 0.9 of capacity within the same
headroom (Economy 7 passes the spread gate), and never discharges: the window's rules 1 to
4. At the dear rate A discharges into a shortfall and charges an excess, as
`SelfConsumptionStrategy` and B's base both do. Both paths settle each step through one
`_settle_timestep`. `tests/unit/test_home_scheduled_charge.py` pins the equality to 1e-9
on a clear June day and a sunless January day; measured, the runs differ by about 1e-16 kW
a row. On this tariff, then, a GX window that mirrors the cheap period gains nothing over
the home's own TOU dispatch (B − A), and D − C is what grid charging in that window adds
to self-consumption only.

**Billing.** Each arm's run is summarised by `calculate_summary` and billed by
`finance.bill` at `FinanceConfig(standing_charge_pence_per_day=60.0)`, whose defaults put
own use at 15 p/kWh and VAT at 5%: `period_days` is the run's `simulation_days`, own use
is on basis C, demand less import
([`docs/cost-recovery-finance-model.md`](cost-recovery-finance-model.md)), the import cost
is the run's import priced at its tariff rates, and the baseline is its demand priced at
the same rates. The scenario's SEG does not enter: export income is the CBS's, not the
householder's.

**Weather and version.** The weather is PVGIS's TMY at Bristol (51.45, −2.58), scaled to
PVGIS's 2005–2020 mean annual GHI ([`docs/tmy-irradiation-scaling.md`](tmy-irradiation-scaling.md)),
read from the weather cache, so the harness needs no network once the cache holds it. The
report opens with the library version, then the weather, the tariff clock, the window, B's
base peak hours, the finance and the period, as §4 shows.

## 4. Measured Annual Bills

Run on task 1016's branch from main `5a3c2ed` (2026-10-20), and again from main `b25f7fa`
(2026-10-21) with identical output, on the main checkout's cached Bristol TMY, each in
under two minutes; from the main checkout, with `SOLAR_CHALLENGE_WEATHER_CACHE_DIR` unset,
the default `--cache-dir` (`.cache/weather`) is the same cache:

    uv run --locked --extra dev python scripts/measure_charge_window_bills.py --cache-dir /home/leo/src/solar-challenge/.cache/weather

It printed:

```
solar_challenge 0.5.0
Weather: PVGIS TMY at Bristol, UK (51.45, -2.58) from https://re.jrc.ec.europa.eu/api/v5_3/, scaled to its 2005-2020 mean annual GHI, read from the cache in /home/leo/src/solar-challenge/.cache/weather
Tariff: Economy 7 (off-peak 00:30-07:30), on Europe/London's clock: Off-peak 00:30-07:30 at £0.09/kWh; Peak 07:30-00:30 at £0.25/kWh
Window (B, D): daily from 00:30 for 7:00:00 to 0.9 of capacity, holding
B's base: TOUOptimizedStrategy, peak hours [(0, 1), (7, 24)]
Finance: standing charge 60.0 p/day, own use 15.0 p/kWh on basis C (demand less import), VAT 0.05
Period: 2025-01-01 to 2025-12-31
```

| Arm | Dispatch | Strategy | Import kWh | Import £ | Standing £ | Own-use kWh | Own-use £ | VAT £ | Total £ |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | as configured | tou_optimized | 1816.8 | 203.87 | 219.00 | 1508.2 | 226.23 | 32.45 | 681.55 |
| B | windows over tou_optimized | scheduled_charge(tou_optimized) | 1816.8 | 203.87 | 219.00 | 1508.2 | 226.23 | 32.45 | 681.55 |
| C | greedy, no grid charging | self_consumption | 974.9 | 195.76 | 219.00 | 2350.1 | 352.52 | 38.36 | 805.65 |
| D | windows over self-consumption | scheduled_charge(self_consumption) | 1816.8 | 203.87 | 219.00 | 1508.2 | 226.23 | 32.45 | 681.55 |

A, B and D bill alike, as §3 explains. D costs the householder £124.10 a year less than C.
It imports 841.9 kWh more, for only £8.11 more: its windows buy grid charge at the 9 p
off-peak rate, and the battery spends it at the peak rate. Since basis-C own use is demand
less import, D pays own use on 841.9 kWh less, £126.29 less at 15 p/kWh, and £5.91 less
VAT.
