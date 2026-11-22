# Grid-Charge Forecasts: Sizing a Cheap Period's Fill by the Charge PV Will Not Strand

**Task:** #848
**Code:** [`src/solar_challenge/dispatch.py`](../src/solar_challenge/dispatch.py) (`GridChargeConfig.forecast`, `GRID_CHARGE_FORECASTS`, `GridChargeContext.useful_charge_ceiling_kwh`); [`src/solar_challenge/grid_charge_forecast.py`](../src/solar_challenge/grid_charge_forecast.py) (`useful_charge_ceiling_kwh`, `grid_charge_ceilings_kwh`)
**Tests:** [`tests/unit/test_grid_charge_forecast.py`](../tests/unit/test_grid_charge_forecast.py); `tests/unit/dispatch/test_grid_charge_controller.py::TestUsefulChargeCeiling`
**Measurement:** [`scripts/measure_grid_charge_forecast.py`](../scripts/measure_grid_charge_forecast.py) (§6), smoke-tested offline by `tests/unit/test_measurement_scripts.py::TestMeasureGridChargeForecast`

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

## 3. Why the 75th Percentile of the 14 Days Before

1. **Over- and under-charging cost different amounts.** On Economy 7 (13 p cheap, 35 p
   peak, SEG 4.1 p, 0.975 one way), a kWh the fill buys that the PV then strands costs
   about 13 − 4.1 ≈ 8.9 p: it pushes a kWh of PV out at the SEG rate. A kWh the fill
   leaves out that the evening then imports at peak costs about 35 − 13 / 0.95 ≈ 21.3 p.
   The newsvendor's critical fractile, 21.3 / (21.3 + 8.9) ≈ 0.70, says to fill to about
   the 70th percentile of what the ceiling may turn out to be.
2. **The measured optimum agrees.** The architect's sweep, at e67d70fd on homes 0-9 of
   `scenarios/bristol-phase1-flex.yaml` over 2024 on the committed Bristol TMY, ran each
   rule through the real engine; net cost is import cost less export at 4.1 p, the mean
   per home a year:

   | Rule | £/home/yr | Against PV-blind |
   |---|---:|---:|
   | PV-blind | 238.33 | |
   | Persistence: yesterday's ceiling | 224.28 | −14.05, one home £2.91 worse |
   | 7 days, median | 221.40 | −16.93 |
   | 7 days, 75th percentile | 215.65 | −22.68 |
   | 7 days, 90th percentile | 218.52 | −19.81 |
   | 10 days, 75th percentile | 215.76 | −22.57 |
   | 14 days, 65th percentile | 214.90 | −23.43 |
   | **14 days, 75th percentile** | **214.55** | **−23.78** |
   | 14 days, 85th percentile | 218.17 | −20.16 |
   | 21 days, 75th percentile | 214.58 | −23.75 |
   | 28 days, 75th percentile | 213.97 | −24.36 |
   | Perfect foresight | 183.08 | −55.25 |

   14 days at the 75th percentile beat PV-blind on all 10 homes (the worst by £13.76), by
   season DJF 153.10 → 153.46, MAM 25.96 → 16.99, JJA −4.58 → −16.08 and SON 63.85 →
   60.18, and took 43% of perfect foresight's saving. The 65th to 75th percentiles are
   the optimum for every trailing length; 21 and 28 days are within the sample's noise of
   14, which is chosen for its shorter warm-up, so a shorter board window gets forecast
   days. Persistence and the median leave money on the table; the 90th percentile
   over-charges.
3. **The parameters are in the name.** `TRAILING_DAYS` and `CEILING_QUANTILE` in
   `grid_charge_forecast.py` hold them, and a disclosed result names `trailing_14_days`,
   so it says exactly what sized it; a re-tune is a new forecast with a new name.

## 4. The Cheap-Window Hold Stays

`TOUOptimizedStrategy` never discharges in a cheap minute, with or without a forecast.
Task 183 measured 1.749 kWh a week more off-peak import than greedy in its June week, of
which 0.303 kWh displaced peak import, so at most about 1.45 kWh a week could be
released, worth about 8.9 p a kWh: some £0.13 a home a week at June's peak and under £4 a
home a year, an order below the ceiling's saving. Releasing it would put a
forecast-driven discharge in TOU's cheap branch, break the exact zero off-peak discharge
`tests/integration/test_tou_dispatch_synthetic_weather.py::test_tou_holds_the_battery_through_the_off_peak_window`
pins, and make the peak-rate guarantee depend on forecast error. With the hold kept, a run's peak-rate import rises
from pv_blind to trailing_14_days to no grid charging to greedy, by SOC monotonicity, as
`tests/integration/test_tou_dispatch_synthetic_weather.py` pins on a sunless day after
15 sunny ones, the forecast's worst case.

## 5. Disclosed Wherever Results Are Reported, Refused Where They May Not Be Used

1. **Results say what sized them.** `SimulationResults.grid_charge_forecast` and
   `SummaryStatistics.grid_charge_forecast` hold the battery's forecast, `None` for a run
   that did not grid-charge; `FleetSummary.grid_charge_forecasts` and
   `BillDistribution.grid_charge_forecasts` hold the distinct forecasts of their homes,
   from the one derivation `home.grid_charge_forecasts_of`.
2. **Reports state it.** The summary, finance and config-ranking reports open with a
   notice naming each forecast and its `GRID_CHARGE_FORECAST_LABELS` text, beside the
   extrapolation notice, and the CLI home and fleet tables gain a `Grid-charge forecast`
   row; neither appears when nothing grid-charged.
3. **perfect_foresight is never a board figure.** `finance.annualise`, which every bill,
   projection and cost-recovery outlay passes through, refuses a summary it sized, with a
   `ConfigurationError` naming the forecasts to run instead.
4. **A community battery stays PV-blind.** Its dispatch in `community.py` computes no
   ceilings, so `CommunityConfig` refuses a community battery whose forecast is not
   `pv_blind` rather than silently ignoring it.
5. **The default is unchanged; the board fleet opts in.** Every scenario, stored run and
   pinned figure that names no forecast stays PV-blind. `scenarios/bristol-phase1-flex.yaml`
   sets `forecast: trailing_14_days`; its single-day tests end inside the 14-day warm-up.

## 6. The Board Fleet, Measured

Measured at 575ad5c6 (task/848) by `scripts/measure_grid_charge_forecast.py` on all 100
homes of `scenarios/bristol-phase1-flex.yaml` over 2024, 366 days, on the committed
Bristol TMY (`tests/fixtures/weather_cache`), each home exporting at the scenario's 4.1 p
SEG rate. Net cost is import cost less export revenue; every figure is the mean per home:

| Forecast | DJF £ | MAM £ | JJA £ | SON £ | Year £ | Grid charge kWh | Export kWh | Householder bill £/yr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pv_blind | 149.36 | 22.88 | −7.18 | 61.21 | 226.27 | 1,070.79 | 2,598.65 | 832.76 |
| trailing_14_days | 149.64 | 13.63 | −18.61 | 57.21 | 201.87 | 649.02 | 2,221.90 | 850.60 |
| perfect_foresight | 139.40 | 6.00 | −19.62 | 44.88 | 170.66 | 445.91 | 1,973.77 | refused |

1. **trailing_14_days cuts the fleet's net cost by £24.40 a home a year**, £2,440 over
   the 100 homes (−10.8%) and 44% of perfect foresight's £55.61, in line with the 10-home
   sweep's £23.78 (§3). It saves £9.25 a home in spring, £11.43 in summer and £4.00 in
   autumn, and costs £0.28 more in winter.
2. **It grid-charges 421.77 kWh a home a year less (−39%) and exports 376.75 kWh less
   (−14.5%):** the PV a blind fill pushed out at the SEG rate is stored instead.
3. **The householder bill rises £17.85 a home a year (+2.1%).** The bill charges a
   householder the import at the tariff, the standing charge, and own use on basis C,
   demand less import, at the scenario's 15 p/kWh, plus VAT; the export income is the
   CBS's, not the householder's (`docs/cost-recovery-finance-model.md`). A home that
   imports less pays less for its import and as many more kWh of own use at 15 p, more
   than the cheap import it replaces costs, so its bill rises while the fleet's net cost
   falls.

4. **The finance run moves every board figure.** `solar-challenge finance run
   scenarios/bristol-phase1-flex.yaml --project --cost-recovery` over 2024 at 575ad5c6,
   against the same run of a copy of the scenario set to `forecast: pv_blind`:

   | Figure | pv_blind | trailing_14_days | Change |
   |---|---:|---:|---:|
   | Householder bill at the 15 p own-use rate, mean £/yr | 832.76 | 850.60 | +17.84 |
   | Representative bill: import cost £/yr | 314.48 | 268.65 | −45.83 |
   | Representative bill: own-use payment £/yr | 254.41 | 318.98 | +64.57 |
   | Representative bill: total outlay £/yr | 827.92 | 847.59 | +19.67 |
   | Mean fleet surplus £/yr | 13,910 | 17,166 | +3,256 |
   | Min DSCR, loan years | 1.83× | 2.11× | +0.28× |
   | Equity IRR | 0.9% | 2.5% | +1.6 points |
   | Payback | 23.0 yr | 20.0 yr | −3.0 yr |
   | Solved cost-recovery own-use rate | 7.96 p/kWh | 7.35 p/kWh | −0.61 p/kWh |
   | Householder outlay at the solved rate, mean £/yr | 714.21 | 691.32 | −22.89 |
   | Grid services at events, fleet income £/yr | 283 | 268 | −15 |

   At the scenario's fixed own-use rate the saving lands with the CBS; once the own-use
   rate is solved for cost recovery it reaches the householders.
5. **The board scenario keeps trailing_14_days.** It beats pv_blind over the year on the
   board fleet's net cost, the measure it was tuned on (§3); the householder bill at the
   fixed own-use rate moves the other way, which task 848 raises for sign-off before merge.

## 7. Reproducing

From the repository root, on the committed Bristol TMY; the script took 22 minutes for its
300 home-years on a 32-core host that other work was loading:

    uv run --locked --extra dev python scripts/measure_grid_charge_forecast.py --cache-dir tests/fixtures/weather_cache
    SOLAR_CHALLENGE_WEATHER_CACHE_DIR=tests/fixtures/weather_cache uv run --locked --extra dev solar-challenge finance run scenarios/bristol-phase1-flex.yaml --project --cost-recovery

For pv_blind's finance figures, run the second command on a copy of the scenario whose
`grid_charging:` block sets `forecast: pv_blind`.
