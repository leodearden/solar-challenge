# PV Annual-Yield Benchmark: kWh per Wired kWp

**Task:** #239 (follow-up from #203), #324, #282
**Code:** [`src/solar_challenge/validation.py`](../src/solar_challenge/validation.py) (`validate_pv_generation`, `_UK_YIELD_BENCHMARK_KWH_PER_KWP`); [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`wired_dc_capacity_kw`)

---

## 1. What the Check Measures

`validate_pv_generation`'s `annual_yield_range` check divides a year's AC energy by the
DC that `create_pv_system` wires, `pv.wired_dc_capacity_kw`, not by the configured
`capacity_kw`. The model wires whole 400.428 W modules, so the two differ:

| Configured | Modules | Wired | kWh per nameplate kWp | kWh per wired kWp |
|---|---|---|---|---|
| 0.3 kW | 1 | 0.40 kWp | 1407.5 | 1054.5 |
| 0.7 kW | 2 | 0.80 kWp | 1197.2 | 1046.4 |
| 1.5 kW | 4 | 1.60 kWp | 1130.6 | 1058.8 |
| 5.9 kW | 15 | 6.01 kWp | 1101.6 | 1082.1 |

The yields are §3's Bristol measurements. Divided by the nameplate, these correct
simulations failed the band as it then was, 700–1100; divided by the wired DC, they
were inside it.
`validate_pv_generation` and `validate_simulation` take the `PVConfig` that produced the
generation, so the wired DC is that of the config's own module, `custom_module_params`
included. The `validate results` CLI holds only a capacity, `--pv-kw`, so it validates
against a `PVConfig` of the default module at that capacity.

## 2. The Band Is Sourced from PVGIS and MCS

- The band is 300–1200 kWh per wired kWp: the range two external references give an
  unshaded UK array facing east, west or anywhere between them through south, at any
  pitch, in a typical year, rounded outward to the next hundred.
- `_UK_YIELD_BENCHMARK_KWH_PER_KWP` in `validation.py` is the single source of the
  numbers; this note transcribes them.
- **Scope.** The check knows neither the site nor, in `validate results`, the
  orientation, so the band must hold every array it may be given. Facing within 90° of
  south covers MCS's orientations up to east and west, and any pitch avoids an
  arbitrary cut-off. A north-facing array is out of scope: a north wall in MCS's
  Lerwick zone reads 204.
- **References.**
  - PVGIS, the European Commission Joint Research Centre's estimate for a point, at its
    default 14% system loss.
  - MCS's kWh/kWp (Kk) tables, from MIS 3002 Appendix B: a system's annual AC output is
    kWp × Kk × SF, with Kk per postcode zone, pitch and orientation, and SF the shade
    factor, 1.00 with a clear horizon. MCS notes that its Kk data "is drawn from the
    Climate-SAF-PVGIS dataset and multiplied by 0.8".
- The simulator models a point, not a postcode zone. PVGIS's point estimates are wider
  than MCS's zone tables at both ends, so PVGIS sets both edges; MCS's envelope for the
  same scope, 394–1132, lies inside. §5 has every figure.

| Edge | PVGIS-14% | MCS Kk | Band |
|---|---|---|---|
| Ceiling | Eastbourne, optimal: 1175.2 | Zone 2 Brighton, south, 38–40°: 1132 | 1200 |
| Floor | Unst, east wall: 367.3 | Zone 20 Lerwick, east or west wall: 394 | 300 |

- The band is not derived from the model. Fitting it to the model's output would make
  the benchmark circular, unable to catch the model it checks.
- **What a FAIL means:** a yield outside what the references give any in-scope UK
  array. That is a gross error (a year at zero, a unit or minute/hour slip, losses left
  out at a sunny site) or an array outside the scope. The band cannot catch an error of
  a few percent; `tests/integration/test_pv_performance_ratio.py` guards the model's
  losses ([pv-system-losses.md](pv-system-losses.md) §5).
- **History.** Until task 282 the band was 700–1100, VAL-001's unsourced 800–1000
  (`git show 672cedb:feature_list.json`) widened by 100 either side. Both references
  put the sunniest south-coast optimal systems above 1100 (PVGIS 1175.2, MCS 1132), and
  east- or west-facing arrays in the north below 700 (Lerwick, west at 45°: MCS 580,
  PVGIS 588.5).

## 3. Where the Model Sat

This is a dated record. Re-measure with the method below before relying on it.

- **Provenance.** Measured 2026-09-30 on main 0e8c240: CPython 3.12.3, pandas 3.0.3,
  pvlib 0.15.1, numpy 2.4.6. The 0.3–7.0 kW figures were re-measured identical on main
  df664c7 (2026-10-01).
- **Weather.** PVGIS TMYs through `weather.get_tmy_data`. Bristol's is the 1990 TMY,
  GHI 992.3 kWh/m², cached as `tmy_5dc8c8bca218`. **[Amended 2026-10-03, task 285:
  `get_tmy_data` now scales this TMY's irradiance by 1.078, to GHI 1069.5 kWh/m²
  ([tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)), so §3 and §4 describe the
  unscaled year. Re-measured on the scaled TMY by §3's and §4's methods (2026-10-03,
  main 89b9299): the 248 capacities read 1051.4–1183.5 kWh/kWp (median 1162.9), 230 of
  them above 1100, and 4 kW reads 1164.7. The AC peak reaches at most 1.100078 × the
  wired DC, at 0.6 kW (0.440502 kW against a limit of 0.440471), so 0.6 kW fails the 10%
  bound by 0.007%; 0.5 kW reads 1.0875 ×. These figures hold until task 252's system
  losses land. §3's other sites are likewise unscaled, and each site's factor
  differs.]** **[Amended 2026-10-03, task 240: leaving battery inverter/chargers out of
  the inverter candidates re-picked 2.6, 7.2 and 7.3 kW
  ([pv-inverter-string-matching.md](pv-inverter-string-matching.md) §7). On the scaled
  TMY the median becomes 1163.3 and 231 read above 1100, 2.6 kW now among them
  (1121.1); the range, 4 kW and the AC peak's maximum are unchanged.]**
  **[Amended 2026-10-09, task 252: the model now deducts PVWatts v5's default 14.08%
  system losses from each array's DC power ([pv-system-losses.md](pv-system-losses.md)).
  Re-measured on the scaled TMY by §3's and §4's methods, on task 252's branch from
  main 5325093 (same interpreter and libraries; without the losses they reproduce the
  figures as task 240 left them): the 248 capacities read 890.7–1016.8 kWh/kWp (median
  997.9), none outside the band, and 4 kW reads 999.9. The AC peak reaches at most
  0.961 × the wired DC (at 21.5–21.8 kW, which wire the same 54 modules), so none fails
  the peak bound: 0.6 kW, which failed it by 0.007%, reads 0.945 ×. The UK-site table
  below is lossless and unscaled; [pv-system-losses.md](pv-system-losses.md) §5 has the
  sites with the losses on their scaled TMYs, three of which still read above 1100
  (task 282).]**
  **[Amended 2026-10-09, task 282: the band is now 300–1200 (§2). In this section,
  "the band", 700 and 1100 mean the band as it was, 700–1100. With the losses,
  Bristol's 248 capacities (890.7–1016.8) and the fourteen UK sites of
  [pv-system-losses.md](pv-system-losses.md) §5 (746.0–1138.9) all read inside the new
  band.]**
- **Model.** `pv.create_model_chain` applied no soiling, wiring, mismatch or
  availability losses. From task 252 every model chain deducts PVWatts v5's default
  system losses from each array's DC power ([pv-system-losses.md](pv-system-losses.md)).
- **Method.** South-facing at 35° unless stated. The hourly AC in kW, summed, is kWh:

  ```python
  kwh = simulate_pv_output(config, location, get_tmy_data(location)).sum()
  kwh_per_wired_kwp = kwh / wired_dc_capacity_kw(config)
  ```

**Capacity.** Bristol's 248 default-rated capacities, 0.3–25.0 kW in 0.1 kW steps, read
969.4–1098.5 kWh/kWp (median 1078.6), all inside the band. The maximum, 1098.5 at
7.0 kW, left 0.14% headroom. Per nameplate kWp, 10 of the 248 read outside the band.

**Orientation** (Bristol, 4 and 7 kW). South at 35° was the optimum, and no orientation
read above 1100. Readings fell below 700 only for:
- north-facing roofs at 30° or steeper (measured to 35°);
- west-facing at 75° or steeper (4 kW at 75°: 699);
- east-facing at 90°.

**Above the ceiling.** Two cases read above 1100:
- an `inverter_efficiency` of 0.98–0.99 at some capacities: 10.8 kW read 1109.4 at 0.98
  and 1120.2 at 0.99;
- sunnier UK sites: the seven above Bristol in the table below, up to 1358.9 at
  Weymouth.

**UK sites** (4 kW, south, 35°, at `Location(latitude, longitude)`):

| Site | Latitude, longitude | kWh per wired kWp |
|---|---|---|
| Weymouth | 50.61, −2.45 | 1358.9 |
| Shanklin, Isle of Wight | 50.63, −1.18 | 1330.3 |
| St Mary's, Isles of Scilly | 49.92, −6.30 | 1284.3 |
| Eastbourne | 50.77, 0.29 | 1267.1 |
| Plymouth | 50.37, −4.14 | 1266.3 |
| London | 51.51, −0.13 | 1174.4 |
| Penzance | 50.12, −5.54 | 1171.1 |
| Bristol (`Location.bristol()`) | 51.45, −2.58 | 1080.9 |
| Belfast | 54.60, −5.93 | 1019.0 |
| Aberdeen | 57.15, −2.09 | 1014.5 |
| Manchester | 53.48, −2.24 | 1006.9 |
| Glasgow | 55.86, −4.25 | 1003.0 |
| Stornoway | 58.21, −6.39 | 930.1 |
| Lerwick | 60.15, −1.15 | 891.3 |

## 4. The Peak Check Uses the Same Wired DC

`peak_within_capacity` fails a peak more than 10% above the wired DC, the
`pv.wired_dc_capacity_kw` the annual yield divides by. Until task 324 it allowed 10%
over the configured `capacity_kw`. That failed correct simulations whose modules round
up past the configured capacity and whose inverter does not clip below them.

This is a dated record. Re-measure before relying on it.

- **Provenance.** Measured 2026-10-02 on main 3c4fb55: CPython 3.12.3, pandas 3.0.3,
  pvlib 0.15.1, numpy 2.4.6, and §3's Bristol 1990 TMY. The peak is
  `simulate_pv_output(config, location, get_tmy_data(location)).max()`.
- **Per wired DC.** The AC peak reached at most 1.029 × the wired DC (0.6 kW: 0.412 kW
  on 0.40 kWp), and 10% over it failed none of these configs:
  - the default module at 0.3–3.0 kW in 0.1 kW steps and at 4.0, 5.9, 7.0 and 10.8 kW;
  - `inverter_capacity_kw` 1.0, 2.0, 0.5 and 6.0 on 0.7, 1.5, 0.3 and 4.0 kW;
  - 250 W and 600 W PVWatts modules from `create_simple_module_params`, at 1.1, 4.0
    and 7.0 kW.
- **Per configured capacity.** 10% over it failed two of them:
  - 0.7 kW behind a 1.0 kW inverter peaked at 0.804 kW (limit 0.77) on 0.80 kWp;
  - 0.3 kW behind a 0.5 kW inverter peaked at 0.408 kW (limit 0.33) on 0.40 kWp.

## 5. The References' Figures

This is a dated record. Re-query before relying on it.

- **Provenance.** Queried 2026-10-09.
  - PVGIS: v5_3's PVcalc, the release `weather.PVGIS_API_URL` pins, over PVGIS-SARAH3
    2005–2023, with `peakpower=1` and `loss=14`, free-standing, with the horizon.
  - MCS: MIS 3002 Issue 6.0 (18/03/2026), Appendix B, Performance Estimation Method
    (pp. 26–28), and the Kk workbook MCS publishes as Irradiance Datasets version 2.0.
    MIS 3002:2025, the standard of MCS's redeveloped installer scheme, has no
    performance estimation method.
- **PVGIS method.** One query per point. The figure is `E_y` in the response's
  `outputs.totals.fixed`, the mean yearly AC energy, here in kWh/kWp, as PVGIS returns
  it:

  ```
  https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat=..&lon=..&peakpower=1&loss=14&raddatabase=PVGIS-SARAH3&outputformat=json&...
  ```

  The last parameters are `optimalangles=1` for an optimal array and
  `angle=..&aspect=..` for a fixed one. `angle` is the pitch; `aspect` 0 is south, −90
  east and 90 west, so an east wall is `angle=90&aspect=-90`.
- **MCS method.** The workbook,
  <https://mcscertified.com/wp-content/uploads/2025/02/Irradiance-Datasets.xlsx>, has one
  sheet per postcode zone, 25 from 'Zone 1 - London' to 'Zone 21 - Belfast'. In each,
  row 2 holds the orientation from south, 0–175° in 5° steps, from column C, and column
  B holds the pitch, 0–90° in 1° steps, from row 3. An orientation is the angle either
  way from south, so 90° is an east or a west face.

| Reference | Where | Array | kWh/kWp |
|---|---|---|---|
| PVGIS-14% | Eastbourne (50.77, 0.29) | optimal: pitch 40°, aspect 4 | 1175.15 |
| PVGIS-14% | Ventnor (50.59, −1.21) | optimal: pitch 40°, aspect 4 | 1172.99 |
| PVGIS-14% | Portland (50.55, −2.44) | optimal: pitch 39°, aspect 3 | 1168.91 |
| PVGIS-14% | Selsey (50.73, −0.79) | optimal: pitch 40°, aspect 3 | 1161.98 |
| PVGIS-14% | Brighton (50.82, −0.14) | optimal: pitch 40°, aspect 2 | 1159.40 |
| PVGIS-14% | Hastings (50.85, 0.57) | optimal: pitch 40°, aspect 4 | 1158.07 |
| PVGIS-14% | Worthing (50.81, −0.37) | optimal: pitch 40°, aspect 2 | 1157.78 |
| PVGIS-14% | Bexhill (50.84, 0.47) | optimal: pitch 40°, aspect 3 | 1153.98 |
| PVGIS-14% | Bognor Regis (50.78, −0.67) | optimal: pitch 40°, aspect 2 | 1150.32 |
| PVGIS-14% | Folkestone (51.08, 1.17) | optimal: pitch 40°, aspect 4 | 1150.08 |
| PVGIS-14% | Weymouth (50.61, −2.45) | optimal: pitch 39°, aspect 1 | 1150.02 |
| PVGIS-14% | Shanklin, Isle of Wight (50.63, −1.18) | optimal: pitch 39°, aspect 3 | 1146.99 |
| PVGIS-14% | St Mary's, Isles of Scilly (49.92, −6.30) | optimal: pitch 38°, aspect 5 | 1133.78 |
| PVGIS-14% | Margate (51.39, 1.38) | optimal: pitch 40°, aspect 2 | 1124.90 |
| PVGIS-14% | Lizard (49.97, −5.20) | optimal: pitch 38°, aspect 5 | 1100.02 |
| PVGIS-14% | Bristol (51.45, −2.58) | optimal: pitch 39°, aspect 0 | 1024.99 |
| PVGIS-14% | Lerwick (60.15, −1.15) | optimal: pitch 41°, aspect 2 | 764.70 |
| PVGIS-14% | Eastbourne (50.77, 0.29) | pitch 35°, aspect 0 (south) | 1171.61 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 35°, aspect 0 (south) | 762.25 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 45°, aspect 90 (west) | 588.52 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 45°, aspect −90 (east) | 577.37 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 60°, aspect 90 (west) | 538.77 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 90°, aspect 90 (west wall) | 391.43 |
| PVGIS-14% | Lerwick (60.15, −1.15) | pitch 90°, aspect −90 (east wall) | 374.69 |
| PVGIS-14% | Unst (60.75, −0.85) | pitch 90°, aspect 90 (west wall) | 383.89 |
| PVGIS-14% | Unst (60.75, −0.85) | pitch 90°, aspect −90 (east wall) | 367.26 |
| MCS Kk | Zone 2 - Brighton, C41:C43 | pitch 38–40°, south | 1132 |
| MCS Kk | Zone 2 - Brighton, C38 | pitch 35°, south | 1130 |
| MCS Kk | Zone 20 - Lerwick, C41:C43 | pitch 38–40°, south | 737 |
| MCS Kk | Zone 20 - Lerwick, C38 | pitch 35°, south | 736 |
| MCS Kk | Zone 20 - Lerwick, U48 | pitch 45°, 90° from south | 580 |
| MCS Kk | Zone 20 - Lerwick, U93 | pitch 90°, 90° from south | 394 |
| MCS Kk | Zone 20 - Lerwick, AL93 | pitch 90°, 175° from south | 204 |

- MCS's tables run from 204 (Zone 20 - Lerwick, a wall 175° from south) to 1132
  (Zone 2 - Brighton, south at 38–40°). Within 90° of south their minimum is Lerwick's
  wall at 90° from south, 394, and Lerwick is the lowest of the 25 zones in every cell;
  its own maximum is 737. At pitch 35° facing south, the zones run from Lerwick's 736 to
  Brighton's 1130.
- PVGIS gives Eastbourne's optimum a year-to-year standard deviation, `SD_y`, of 38.73,
  so a sunny single year there can pass 1200. The band is for a typical year, the kind
  of year `weather.get_tmy_data` gives the model.

## 6. When to Revisit

- PVGIS changes release or radiation database. `weather.PVGIS_API_URL` pins the
  release the model's weather comes from, and §5's queries used the same one.
- MCS publishes a new Irradiance Datasets version or MIS 3002 issue.
- North-facing arrays become a supported case. MCS's north walls read down to 204.
- Validation gains the in-plane irradiation. A performance-ratio check, a year's AC over
  the in-plane irradiation times the wired kWp, against MCS's 0.8, would then judge a
  run independently of its site and orientation.
