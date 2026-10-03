# PVGIS TMY Irradiation: Scaled to the Long-Term Mean

**Task:** #285 (follow-up from #252)
**Code:** [`src/solar_challenge/weather.py`](../src/solar_challenge/weather.py) (`get_tmy_data`, `scale_tmy_to_annual_ghi`, `WeatherCache`)
**Measurement:** [`scripts/measure_tmy_irradiation.py`](../scripts/measure_tmy_irradiation.py) (§3)

---

## 1. What the Code Does

On a cache miss, `get_tmy_data` fetches two things for the same point, with the same
horizon, from one pinned PVGIS release, `PVGIS_API_URL` (v5_3: PVGIS-SARAH3 + ERA5):

- PVGIS's TMY, built from `CLIMATE_YEARS`, 2005–2020;
- the hourly series of those years on a horizontal plane, whose `poa_global` is GHI.

It refuses a series that lacks or repeats any hour of those years: a `WeatherDataError`
(a `RuntimeError`) names the years, and nothing is cached. Otherwise
`scale_tmy_to_annual_ghi` multiplies the TMY's `ghi`, `dni` and `dhi` by one factor, so
that the year's GHI equals the mean of the series' calendar-year totals, and
`get_tmy_data` caches the scaled year. Temperature and wind stay as PVGIS gives them.
`scale_tmy_to_annual_ghi` takes exactly one TMY year, 8760 hourly rows with some GHI, so
it never rescales a partial frame. `get_tmy_data` raises its refusal as a
`WeatherDataError`, as it does any other bad PVGIS response, and caches nothing.

A cache hit is returned as stored, never rescaled: a cache seeded with
`put(df, "tmy", location)` serves exactly what was put.

## 2. Decision (task 285, 2026-10-02): Scale the TMY's Year by One Factor

- **The TMY's level is wrong.** Bristol's TMY is below every year from 2005 to 2020: GHI
  992.3 kWh/m² against 1006.3–1141.6, mean 1069.5 (§4). The default 4 kW system
  simulated on it produces 4328 kWh of AC, less than in any real year (4505–4987).
- **Why.** The TMY's months are real months, and PVGIS's metadata names each one's source
  year. But ISO 15927-4 picks each month by how its daily values are distributed, not by
  its total, so the year's irradiation is not preserved. 11 of Bristol's 12 picks rank in
  the darker half of their 16 candidates, August 2008 is −23%, and July to September all
  come from 2008.
- **Not a database mix-up.** The task text compared the v5.3 TMY with PVGIS-SARAH2
  (v5_2) years, 1006.7–1150.6 kWh/m² with a mean of 1072.3. Within v5_3 alone the gap is
  much the same.
- **Not one-directional.** The bias is the site's own and runs both ways: Glasgow's TMY
  is above every year (954.4 against 852.6–927.7 kWh/m²), and its AC reads +7.3%.
- **The correction.** One factor per site, k = the mean annual GHI over the TMY's GHI,
  corrects the level and keeps what ISO 15927-4 chose: the hourly sequence, the seasonal
  shape, temperature and wind. Because `ghi`, `dni` and `dhi` share the factor,
  GHI = DNI·cos z + DHI and the beam/diffuse split still hold. At the seven sites in §4
  it brings the TMY's AC within −1.9% to +0.4% of the real years' mean, from −7.5% to
  +7.3% raw.

## 3. Method

[`scripts/measure_tmy_irradiation.py`](../scripts/measure_tmy_irradiation.py) is the
method: it prints every figure in §4. Its docstring gives the command. It needs network
access to PVGIS, takes about two to three minutes, and is not part of the test suite. In
outline:

- **Provenance.** Run on task 285's branch from main d8659e3 (2026-10-02), and again from
  main 89b9299 (2026-10-03) with identical output: CPython 3.12.3, pvlib 0.15.1, pandas
  3.0.3, numpy 2.4.6. The architect's prototype gave the same figures on 2026-10-01.
- **Sites.** Seven UK points, pinned in the script, because a site's factor depends on
  the exact point: Glasgow's read 0.978 at a nearby one.
- **The TMY.** Requested with `get_tmy_data`'s own arguments, `PVGIS_TMY_REQUEST`,
  keeping the metadata's `months_selected`: the real year each month comes from.
- **The real years.** The 2005–2020 hourly series with `components=True` on a horizontal
  plane, decomposed by task 290's recipe: ghi = `poa_direct` + `poa_sky_diffuse`,
  dhi = `poa_sky_diffuse`, and dni = `poa_direct` / sin(solar elevation) with the sun up,
  else 0. `get_tmy_data` needs GHI alone, and reads it as the `components=False` series'
  `poa_global`: for Bristol that mean is 1069.456 kWh/m², against 1069.454 from the
  components.
- **Metric.** The annual AC of `PVConfig.default_4kw()` (4 kW, south, 35°) from
  `simulate_pv_output`, on each real year and on three versions of the TMY: raw; scaled
  by `scale_tmy_to_annual_ghi` to the real years' mean GHI ("annual"); and scaled month
  by month, each month's `ghi`, `dni` and `dhi` multiplied by that month's 16-year mean
  GHI over the TMY month's ("monthly"). Each TMY's AC is a percentage against the mean AC
  of the 16 real years.
- **Peaks and ranks.** A peak is the highest hourly GHI, and the record is the series'.
  A TMY month is ranked among the same calendar month of the 16 years, 1 = darkest; the
  darker half is ranks 1–8.

## 4. Measurements

This is a dated record. Re-measure with §3's script before relying on it.

**Seven sites.** AC against the mean of the real years; peak hourly GHI in W/m².

| Site (lat, lon) | k | raw TMY | annual scale | monthly scale | peak GHI raw / annual / monthly / record |
|---|---|---|---|---|---|
| Bristol (51.45, −2.58) | 1.078 | −7.5% | −0.3% | −1.2% | 931 / 1003 / 1088 / 944 |
| London (51.5074, −0.1278) | 0.990 | +0.7% | −0.3% | −0.2% | 918 / 909 / 919 / 942 |
| Penzance (50.1188, −5.5376) | 1.067 | −6.4% | −0.2% | −1.3% | 943 / 1006 / 1154 / 967 |
| Eastbourne (50.7684, 0.2903) | 1.031 | −4.8% | −1.9% | −1.8% | 930 / 958 / 1067 / 951 |
| Belfast (54.5973, −5.9301) | 1.040 | −3.5% | +0.4% | −0.0% | 899 / 935 / 976 / 915 |
| Glasgow (55.8642, −4.2518) | 0.936 | +7.3% | +0.4% | +0.8% | 863 / 808 / 915 / 900 |
| Plymouth (50.3755, −4.1427) | 1.010 | −0.8% | +0.2% | +0.1% | 941 / 950 / 1016 / 963 |

GHI totals in kWh/m²:

| Site | TMY | Real years (mean) | Annual-scaled hours above the record | TMY months from the darker half |
|---|---|---|---|---|
| Bristol | 992.3 | 1006.3–1141.6 (1069.5) | 15 | 11 of 12 |
| London | 1076.5 | 1012.5–1138.8 (1066.0) | 0 | 6 of 12 |
| Penzance | 1078.7 | 1094.1–1220.0 (1150.4) | 9 | 8 of 12 |
| Eastbourne | 1162.1 | 1126.0–1265.1 (1197.7) | 2 | 7 of 12 |
| Belfast | 916.2 | 910.8–984.2 (952.8) | 6 | 9 of 12 |
| Glasgow | 954.4 | 852.6–927.7 (893.2) | 0 | 5 of 12 |
| Plymouth | 1150.9 | 1109.9–1226.4 (1162.4) | 0 | 6 of 12 |

**Bristol's AC**, kWh: real years 4505–4987 (mean 4677); raw TMY 4328; annual-scaled
4664; monthly-scaled 4620.

**Bristol's TMY months:**

| Month | Source year | GHI, kWh/m² | Rank (1 = darkest) | Against the 16-year mean |
|---|---|---|---|---|
| January | 2018 | 23.9 | 7 | −2.6% |
| February | 2007 | 40.0 | 8 | −1.6% |
| March | 2006 | 72.8 | 4 | −9.1% |
| April | 2016 | 118.7 | 7 | −4.2% |
| May | 2007 | 142.3 | 4 | −5.6% |
| June | 2011 | 151.3 | 5 | −3.4% |
| July | 2008 | 148.7 | 6 | −7.4% |
| August | 2008 | 99.5 | 1 | −23.0% |
| September | 2008 | 87.1 | 2 | −9.4% |
| October | 2006 | 53.4 | 3 | −5.0% |
| November | 2017 | 34.5 | 15 | +14.8% |
| December | 2017 | 19.9 | 7 | −2.5% |

## 5. Rejected Alternatives

- **Simulating the multi-year series.** It costs 16× the compute per home, and
  `simulate_home` models one weather year, aligned to the simulation period by UTC time
  of year (`weather.align_tmy_to_index`). Real-historical weather is a separate gap, with
  no fetcher since task 290 ([financial-layer PRD](prds/financial-layer-battery-fidelity.md)
  §11, amended).
- **Monthly scaling.** It is no more accurate (−1.8% to +0.8%; Bristol −1.2%), and it
  inflates the brightest hours far more: Bristol's August is multiplied by 1.30
  (1 / 0.770), giving 1088 W/m² against a 16-year record of 944.
- **Capping scaled hours at the series' hourly record.** It needs a second statistic from
  the series and a solved, non-uniform factor to keep the annual total, for 15 of
  Bristol's 8760 hours.
- **Keeping the raw TMY and documenting the bias.** Bristol's AC would stay below every
  real year's (§2), which a board-facing P50 figure cannot carry.

## 6. Consequences

- Bristol's default 4 kW AC goes from 4328 to 4664 kWh (+7.8%). Every other site moves
  with its own factor (§4's k), up or down.
- The brightest hours scale too. Bristol's goes from 931 to 1003 W/m², and 15 hours sit
  above the 16-year record of 944, so those hours are optimistic for clipping, export
  limits and validation's peak check.
- The TMY's seasonal shape is kept: Bristol's August stays about 17% below its 16-year
  mean (0.770 × 1.078) and its November about 24% above it (1.148 × 1.078).
- A cache miss also downloads the 2005–2020 series, about 9 s, once per location per
  cache.
- Cache entries written before this change are never read. `WeatherCache`'s key version
  2 renames every entry, so Bristol's raw TMY, cached as `tmy_5dc8c8bca218`, is ignored
  (`clear()` removes it). A cache built by copying files must be rebuilt with
  `put(df, "tmy", location)`.
- Validation's annual-yield band and peak check under the scaled TMY are recorded once,
  in [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §3's task-285
  amendment.

## 7. Task 252: System Losses

Task 252, which gives the PV model system losses, is pending.

- The model applies no soiling, wiring, mismatch or availability losses yet. Before this
  task, Bristol's 4 kW read 1080.9 kWh per wired kWp
  ([pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §3): +6% against PVGIS's
  1021 kWh/kWp at its default 14% system loss (quoted by tasks 252 and 285), because the
  dark TMY partly cancelled the missing losses.
- With this task alone it reads about +14% (1164.7, that doc's §3 amendment), above
  validation's 1100 band.
- The two corrections are independent physics and compose. With task 252's ~14% loss,
  Bristol's 4 kW is expected near 1000 kWh/kWp (1164.7 × 0.86): an expectation to
  re-measure with §3's script once task 252 lands.

## 8. When to Revisit

- A new PVGIS release or radiation database. `PVGIS_API_URL` is pinned, so a retired
  release fails loudly instead of drifting the figures.
- A change to `CLIMATE_YEARS`.
- Relying on these figures for a new kind of site: each site has its own factor, and §4
  covers seven UK points.
- Results that turn on the brightest hours, which annual scaling raises with the rest
  (§6).
- Task 252 landing: re-measure §4 here, and §3–§4 of
  [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md).
