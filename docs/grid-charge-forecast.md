# Grid-Charge Forecasts: Sizing a Cheap Period's Fill by the Charge PV Will Not Strand

**Task:** #848
**Code:** [`src/solar_challenge/dispatch.py`](../src/solar_challenge/dispatch.py) (`GridChargeConfig.forecast`, `GRID_CHARGE_FORECASTS`)

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
