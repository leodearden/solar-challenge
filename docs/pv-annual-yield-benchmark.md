# PV Annual-Yield Benchmark: kWh per Wired kWp

**Task:** #239 (follow-up from #203), #324
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
simulations failed the band; divided by the wired DC, they were inside it.
`validate_pv_generation` and `validate_simulation` take the `PVConfig` that produced the
generation, so the wired DC is that of the config's own module, `custom_module_params`
included. A bare capacity, as the `validate results` CLI's `--pv-kw` gives, stands for a
system of the default module.

## 2. The Band Is a Real-World Benchmark

- 700–1100 kWh/kWp is VAL-001's expected UK domestic range, 800–1000 kWh/kWp, widened
  by 100 either side. VAL-001 is in the original feature list,
  `git show 672cedb:feature_list.json`.
- `_UK_YIELD_BENCHMARK_KWH_PER_KWP` in `validation.py` is the single source of the
  numbers; this note transcribes them.
- The band is not derived from the model. Widening it to fit the model's output would
  make the benchmark circular, unable to catch the model it checks.
- So a FAIL on a correctly wired system means the model, or the site, sits outside what
  the benchmark expects of a UK roof. It does not mean validation is wrong.

## 3. Where the Model Sat

This is a dated record. Re-measure with the method below before relying on it.

- **Provenance.** Measured 2026-09-30 on main 0e8c240: CPython 3.12.3, pandas 3.0.3,
  pvlib 0.15.1, numpy 2.4.6. The 0.3–7.0 kW figures were re-measured identical on main
  df664c7 (2026-10-01).
- **Weather.** PVGIS TMYs through `weather.get_tmy_data`. Bristol's is the 1990 TMY,
  GHI 992.3 kWh/m², cached as `tmy_5dc8c8bca218`.
- **Model.** `pv.create_model_chain` applied no soiling, wiring, mismatch or
  availability losses.
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
