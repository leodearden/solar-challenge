# PV System Losses: PVWatts v5's Default Budget on Each Array's DC Power

**Task:** #252
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`PVConfig.system_losses`, `create_model_chain_picking_from`)
**Measurement:** [`scripts/measure_pv_performance_ratio.py`](../scripts/measure_pv_performance_ratio.py) (§5); [`tests/integration/test_pv_performance_ratio.py`](../tests/integration/test_pv_performance_ratio.py)

---

## 1. What the Code Does

- `PVConfig.system_losses` is the fraction of each array's DC power lost before the
  inverter. `create_model_chain_picking_from`, which builds every model chain, installs it
  as pvlib's losses model, which runs between the DC and AC models: each array's
  maximum-power-point power and current are scaled by `1 - system_losses`, and its
  voltage stays as the module model computed it.
- The default is `pvlib.pvsystem.pvwatts_losses() / 100`, 14.08% (0.14075660688264469 in
  pvlib 0.15.1). A value outside [0, 1) raises `ValueError`, so 14.0, the percent that
  PVGIS and PVWatts take, is refused.
- **Performance ratio**, as this note and its measurements use it: a year's AC energy
  divided by the in-plane irradiation (kWh/m², before angle-of-incidence losses) times
  the wired DC capacity (`pv.wired_dc_capacity_kw`, the denominator of validation's
  annual-yield band).

## 2. Decision and Source

The default is PVWatts v5's loss budget (A. P. Dobos, *PVWatts Version 5 Manual*,
NREL/TP-6A20-62641, 2014), as pvlib implements it. Its categories, in % of DC power,
combine multiplicatively, as 1 − Π(1 − loss):

| Soiling | Shading | Snow | Mismatch | Wiring | Connections | Light-induced degradation | Nameplate rating | Age | Availability | Total |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 3 | 0 | 2 | 2 | 0.5 | 1.5 | 1 | 0 | 3 | 14.08 |

PVWatts budgets the losses its model does not otherwise compute; it models the inverter,
temperature and angle of incidence itself, as this model does. With the budget, the
model's annual performance ratio lands on the two UK references (§5):

- MCS MIS 3002 Issue 5.0 (p. 27; read 2026-10-03) estimates a domestic system's yield as
  PVGIS's climate-based figure times 0.8, a performance ratio of 0.8;
- PVGIS's own estimate at its default 14% system loss.

## 3. What It Excludes, and Why

- Inverter, temperature and angle-of-incidence losses: the model computes them.
- Ageing: `system_age_years × degradation_rate_per_year` applies it, and PVWatts' age
  category is 0.
- PVGIS's 14%: per the PVGIS user manual it covers cable, inverter, dirt and
  lifetime-ageing losses, for a model with no inverter of its own, so here its inverter
  and ageing shares would count twice. Its total happens to be close to PVWatts' (14 and
  14.08%); stacked on PVWatts' budget, it would put Bristol's ratio near 0.70
  (0.8089 × 0.86), below the slow guard's band.
- MCS's 0.8 as a flat factor: it is an overall performance ratio, which would replace
  the modelled inverter, temperature and angle-of-incidence physics, not add to it.

## 4. Where It Applies

- On the DC side, before the inverter, where real system losses arise, so an
  inverter-limited array still clips at its rating. On a clear June day
  (`tests/unit/test_pv.py`'s `clear_june_daytime`), 6 kW of PVWatts modules on a 3 kW
  inverter peaks at 3.000 kW with or without the losses and keeps 0.9546 of its energy;
  8 kW of CEC modules on 3.68 kW peaks at 3.680 kW and keeps 0.9623. A derate of the AC
  would cap both peaks at 0.859 of the rating and keep 0.859 of the energy.
- At unchanged voltage. The Sandia and ADR inverters read `v_mp`, and `create_pv_system`
  matches the strings' voltage to the inverter's MPPT window
  ([pv-inverter-string-matching.md](pv-inverter-string-matching.md)). pvlib's built-in
  `losses_model='pvwatts'` multiplies the whole DC frame, `v_mp` and `v_oc` included, so
  it would move that voltage by 14%; it also reads its categories from the `PVSystem`,
  not one fraction.

## 5. Measurements

This is a dated record. Re-measure with the script before relying on it.

- **Provenance.** 2026-10-09, on task 252's branch from main cf6af55, and again from
  main 5325093 with identical output: CPython 3.12.3, pvlib 0.15.1, pandas 3.0.3, numpy
  2.4.6. TMYs through `get_tmy_data`, scaled to PVGIS v5_3's 2005–2020 mean GHI
  ([tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)). PVGIS-14% is pvlib's
  `get_pvgis_hourly(pvcalculation=True, peakpower=1, loss=14)` from the same release
  and years (PVGIS-SARAH3), at 35° facing south, free-standing, with the horizon.
- **Bristol, default 4 kW** (4.00428 wired kWp; GHI 1069.46 and in-plane 1236.12
  kWh/m²): without the losses 4663.95 kWh, 1164.74 kWh/kWp, ratio 0.9423; with them
  4003.91 kWh, 999.91 kWh/kWp, ratio 0.8089. PVGIS-14% reads 1001.1 kWh/kWp, ratio 0.798;
  MCS's ratio is 0.8. `tests/integration/test_pv_performance_ratio.py` reads the same
  0.8089 through the script's `measure`, inside its 0.76–0.84 band.
- **Earlier reading** (2026-10-03, main f3e05fb, by task 252's first plan): PVGIS v5_3's
  PVcalc at 14% over SARAH3 2005–2023 gave Bristol 1022.83 kWh/kWp, ratio 0.8124, and
  0.808–0.825 across the fourteen sites.
- **Fourteen UK sites**, `scripts/measure_pv_performance_ratio.py` (303.5 s on a cold
  weather cache), 4 kW at 35° facing south:

| Site (lat, lon) | GHI kWh/m² | POA kWh/m² | lossless kWh/kWp | lossless PR | with losses kWh/kWp | with losses PR | PVGIS-14% kWh/kWp | PVGIS-14% PR | with losses vs PVGIS |
|---|---|---|---|---|---|---|---|---|---|
| Weymouth (50.61, -2.45) | 1193.1 | 1415.3 | 1324.5 | 0.936 | 1137.2 | 0.803 | 1127.7 | 0.799 | +0.8% |
| Shanklin, Isle of Wight (50.63, -1.18) | 1187.5 | 1421.9 | 1326.5 | 0.933 | 1138.9 | 0.801 | 1124.5 | 0.800 | +1.3% |
| St Mary's, Isles of Scilly (49.92, -6.3) | 1170.0 | 1355.6 | 1279.9 | 0.944 | 1098.8 | 0.811 | 1109.1 | 0.813 | -0.9% |
| Eastbourne (50.77, 0.29) | 1197.7 | 1389.5 | 1305.1 | 0.939 | 1120.6 | 0.807 | 1154.6 | 0.811 | -2.9% |
| Plymouth (50.37, -4.14) | 1162.4 | 1359.3 | 1278.8 | 0.941 | 1097.9 | 0.808 | 1103.0 | 0.808 | -0.5% |
| London (51.51, -0.13) | 1066.0 | 1241.9 | 1162.9 | 0.936 | 998.1 | 0.804 | 997.5 | 0.793 | +0.1% |
| Penzance (50.12, -5.54) | 1150.4 | 1327.2 | 1247.8 | 0.940 | 1071.6 | 0.807 | 1079.6 | 0.806 | -0.7% |
| Bristol (51.45, -2.58) | 1069.5 | 1236.1 | 1164.7 | 0.942 | 999.9 | 0.809 | 1001.1 | 0.798 | -0.1% |
| Belfast (54.6, -5.93) | 952.8 | 1122.7 | 1060.0 | 0.944 | 909.5 | 0.810 | 901.2 | 0.802 | +0.9% |
| Aberdeen (57.15, -2.09) | 885.6 | 1058.7 | 1006.4 | 0.951 | 863.5 | 0.816 | 866.1 | 0.811 | -0.3% |
| Manchester (53.48, -2.24) | 936.8 | 1092.8 | 1028.2 | 0.941 | 882.1 | 0.807 | 866.2 | 0.795 | +1.8% |
| Glasgow (55.86, -4.25) | 899.6 | 1039.8 | 981.1 | 0.944 | 841.6 | 0.809 | 840.5 | 0.797 | +0.1% |
| Stornoway (58.21, -6.39) | 835.0 | 979.7 | 930.4 | 0.950 | 798.0 | 0.815 | 786.6 | 0.805 | +1.5% |
| Lerwick (60.15, -1.15) | 800.2 | 907.4 | 869.9 | 0.959 | 746.0 | 0.822 | 763.9 | 0.815 | -2.3% |

Performance ratio ranges: without the losses 0.933–0.959; with them 0.801–0.822;
PVGIS-14% 0.793–0.815.

## 6. Consequences

- On the same weather every PV output is lower: by 14.08% where the inverter does not
  clip, by less where it does (§4). Bristol's default 4 kW goes from 1164.7 to 999.9 kWh
  per wired kWp.
- Validation's annual-yield band over Bristol's 248 capacities with the losses:
  [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §3's task-252 amendment.
- The finance calibration's specific yield and solved own-use rate:
  [finance-spreadsheet-reconciliation.md](finance-spreadsheet-reconciliation.md) §4.2.
- With the losses, Weymouth (1137.2), Shanklin (1138.9) and Eastbourne (1120.6) still
  read above validation's 1100 kWh/kWp; PVGIS-14% puts five of the fourteen sites above
  it. Whether the ceiling should move is task 282's question.

## 7. Open Items

- **Task 282:** validation's band edges.
- **Task 283:** exposure in YAML, fleet distributions, sweeps and `scenario_writer`.
  Until then every YAML, web and CLI run gets the default, only Python callers set the
  field, and `config.py` refuses a YAML `system_losses` key.
- **Task 284:** ageing is applied to the AC after clipping, not to the DC.

## 8. When to Revisit

- pvlib changes `pvwatts_losses`' defaults. `FROZEN_SURFACE` pins the default's repr, so
  the frozen-surface test fails, and the newest-releases lane with it.
- MCS or PVGIS changes its methodology.
- The model gains an explicit soiling, shading or availability term: take that category
  out of the budget.
