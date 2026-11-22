# Grid-Charge Forecasts: Sizing a Cheap Period's Fill by the Charge PV Will Not Strand

**Task:** #848
**Code:** [`src/solar_challenge/dispatch.py`](../src/solar_challenge/dispatch.py) (`GridChargeConfig.forecast`, `GRID_CHARGE_FORECASTS`, `GridChargeContext.useful_charge_ceiling_kwh`); [`src/solar_challenge/grid_charge_forecast.py`](../src/solar_challenge/grid_charge_forecast.py) (`useful_charge_ceiling_kwh`, `grid_charge_ceilings_kwh`)
**Tests:** [`tests/unit/test_grid_charge_forecast.py`](../tests/unit/test_grid_charge_forecast.py); `tests/unit/dispatch/test_grid_charge_controller.py::TestUsefulChargeCeiling`

---

A battery that grid-charges fills itself in each cheap period to its target,
`GridChargeConfig.target_soc_fraction` of its effective capacity. Filled blind, the
battery is full when the sun comes up, so on a sunny day the PV the house cannot use
has nowhere to go but the export meter: each kWh bought at the cheap rate pushes out a
kWh of PV that sells at the SEG rate. `GridChargeConfig.forecast` names what sizes the
fill.

## 1. The Forecasts

`dispatch.GRID_CHARGE_FORECASTS` lists them, in this order.

1. **`pv_blind`**, the default, fills to the target whatever PV the day brings. Every
   battery whose `grid_charging:` block names no forecast is sized this way, as every
   grid-charging battery was before the field existed.
2. **`trailing_14_days`** caps the fill at the forecast useful-charge ceiling: the
   highest state of charge whose extra charge the PV after the cheap period is not
   forecast to strand. The forecast reads only days that have already happened.
3. **`perfect_foresight`** caps the fill at the ceiling the run's own future PV and
   demand give. It is an upper bound for analysis: no controller knows tomorrow's PV,
   so it is never used for board figures.

## 2. The Useful-Charge Ceiling

1. **A cheap window is a maximal run of rows the tariff prices cheap**, read from
   `TariffConfig.cheap_minutes_of_day` on each row's wall-clock minute. Its horizon runs
   from its first row to the next window's first row, or to the run's end.
2. **Over a horizon the battery follows TOU's tariff-clock rule.** It holds through the
   window's rows; after them it stores every PV surplus, at most `max_charge_kw` and less
   its charge loss, and covers every shortfall, at most `max_discharge_kw` and plus its
   discharge loss, within its SoH-derated SOC envelope. `StepLimits` bounds every
   dispatcher's discharge by the shortfall, so for another dispatcher the model
   over-states the discharge, which only raises the ceiling, toward PV-blind.
3. **The ceiling is the highest start SOC whose extra charge the horizon's PV will not
   strand.** With `level` the cumulative stored-less-withdrawn energy from 0 and `peak`
   its running maximum, a start at or below `top − peak[-1]` never fills, and a start at
   or below `min(floor − level[t], top − peak[t])` empties at `t` before it has filled;
   the ceiling is the larger of the two, clipped to `[floor, top]`, the envelope's
   `min_soc_kwh` and `max_soc_kwh` (`useful_charge_ceiling_kwh`, ported from task 183).
4. **The gate fills to the lower of the target and the ceiling.** The ceiling travels in
   `GridChargeContext.useful_charge_ceiling_kwh`, so `compute_grid_charge_power_kw`, which
   every grid-charging dispatcher calls, applies it; a scheduled-charge window keeps its
   own explicit target.
5. **`trailing_14_days` reads only the past.** Each window's ceiling is the
   `CEILING_QUANTILE` (0.75) of the ceilings the `TRAILING_DAYS` (14) earlier windows
   opening at the same wall-clock minute needed; each of those horizons ended by the time
   the window opens, since a horizon ends where the next window starts. Until 14 such
   windows exist the fill is PV-blind. A past day's PV and demand come as a pair, so the
   forecast also forecasts demand.
