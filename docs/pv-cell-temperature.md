# PV Cell Temperature: NOCT-SAM from Each Module's Own NOCT and Efficiency

**Task:** #823
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`_temperature_model_parameters`, `_NoctSamInput`, `_require_cells_noct_sam_can_heat`, `_arrays`, `create_simple_module_params`, `PVConfig.custom_module_params`); [`src/solar_challenge/validation.py`](../src/solar_challenge/validation.py) (`BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP`)
**Measurement:** [`scripts/measure_pv_performance_ratio.py`](../scripts/measure_pv_performance_ratio.py)'s `measure` (§3); [`tests/unit/test_pv_cell_temperature.py`](../tests/unit/test_pv_cell_temperature.py); [`tests/integration/test_pv_performance_ratio.py`](../tests/integration/test_pv_performance_ratio.py)

---

## 1. What the Code Does

- Every array's cell temperature is pvlib's `noct_sam`, SAM's NOCT model.
  `_temperature_model_parameters` gives each array `{"noct": T_NOCT, "module_efficiency":
  rating / (A_c × 1000), "transmittance_absorptance": 0.9}`, and pvlib's `ModelChain`
  infers `noct_sam_temp` from those keys.
  - `T_NOCT` (°C) and `A_c` (m²) are the module's own catalogue values. The rating is
    `_module_rating_w`'s: the module's `pdc0` if it has PVWatts parameters, else its
    `STC`, the same rating that counts the modules and gives the wired DC.
  - So `DEFAULT_CEC_MODULE` runs at a NOCT of 45.1 °C and an efficiency of
    400.428 / (1.99 × 1000) = 0.2012.
- **A missing key takes the default module's value.** A module that lacks `T_NOCT` or
  `A_c` takes `DEFAULT_CEC_MODULE`'s value of that key, key by key, read from pvlib's CEC
  library. It does not take the default module's efficiency:
  `{"pdc0": 300.0, "gamma_pdc": -0.004}` runs at 300 / 1990 = 0.151.
  `PVConfig.custom_module_params`' docstring states the rule.
- **A module NOCT-SAM cannot heat is refused.** pvlib's `noct_sam` raises a sunlit cell
  above the air in proportion to (T_NOCT − 20 °C)(1 − efficiency / 0.9). So
  `_require_cells_noct_sam_can_heat` refuses, with a `ValueError` naming the key, its
  value and the domain:
  - a `T_NOCT` that is not a finite temperature above 20 °C, the air temperature at
    which NOCT is measured;
  - an `A_c` that is not a finite area over which the rating is an efficiency below the
    transmittance–absorptance 0.9.

  Outside that domain a cell runs no hotter than the air, or colder; a NaN gives NaN
  cells, so no DC, with no error. The refusal reaches `create_pv_system`,
  `create_model_chain`, `simulate_pv_output` and `wired_dc_capacity_kw`. Every one of
  pvlib's 21,535 CECMod rows lies inside the domain (NOCT 41.2–63.7 °C, efficiency
  0.036–0.227, no NaN `T_NOCT`, `A_c` or `STC`), so only hand-built module dicts are
  refused.

  A value the module lacks is checked too, and the `ValueError` names it as
  `DEFAULT_CEC_MODULE`'s and asks for the module's own (`_NoctSamInput`). So a module
  rated at 1791 W or more without its own `A_c`, such as one PVWatts module standing
  for a whole array, is refused: over the default's 1.99 m² its rating is an efficiency
  of 0.9 or more (1.99 m² × 0.9 × 1000 W/m² = 1791 W).
- **Installation takes pvlib's defaults:** one storey (`array_height=1`), and a 4 in
  standoff (`mount_standoff=4`), which adjusts NOCT by 0 °C. The transmittance–absorptance
  is pvlib's default 0.9, which `pv.py` passes explicitly as `_TRANSMITTANCE_ABSORPTANCE`,
  so the model and the refusal read one value. That is the open-rack assumption the
  replaced SAPM set made.
- **`create_simple_module_params`** writes `A_c = module_power_w / (efficiency × 1000)` in
  place of an `"efficiency"` key nothing read. Its `efficiency` now acts on output,
  through how hot the cells run.
- **Night.** `noct_sam` divides the effective irradiance by `poa_global`, so in an hour
  with no light on the plane the cell temperature is 0/0, NaN: 4534 of the 8760 hours of
  Bristol's TMY, and 9 of the 24 of the tests' synthetic clear June day.
  - pvlib's `ModelChain` fills the CEC single-diode DC, and the PVWatts inverter's AC,
    with 0 in those hours, so AC and energy stay finite.
    `tests/unit/test_pv_cell_temperature.py` pins that AC is finite in every hour and 0
    without sun.
  - A run chain's `results.cell_temperature` is NaN in those hours, and so is the PVWatts
    DC model's `results.dc`. That is expected.
  - The scipy `_chandrupatla` RuntimeWarnings that the single-diode solver raised in dark
    hours no longer occur: 0 per run, against 39 per clear day and 100 per Bristol year
    for each array under SAPM (§3). The run policy, `simulate_pv_output`'s warning filter
    included, is task 810's.

## 2. Decision and Source

- **Ruling.** Leo's session ruling of 2026-10-15 (program D32;
  [the PRD](prds/pv-model-one-home.md), resolved decision 5): every run switches to
  NOCT-SAM, fed the module's own NOCT and efficiency, accepting that every default yield
  moves.
- **Source.** P. Gilman, A. Dobos, N. DiOrio, J. Freeman, S. Janzou and D. Ryberg, *SAM
  Photovoltaic Model Technical Reference Update*, NREL/TP-6A20-67399, 2018, §10.6, which
  `pvlib.temperature.noct_sam` cites and implements.
- **Why.** The SAPM `open_rack_glass_glass` parameters were one generic set for every
  module, so a module's efficiency could not act on output. NOCT-SAM reads each module's
  NOCT and efficiency. A less efficient module turns more of the light it absorbs into
  heat, so at a fixed rating it runs hotter and yields less. Task 825 (ζ), which makes
  `PVConfig.module_efficiency` live, builds on that.
- **Rejected:** scaling SAPM's heating by the module's efficiency, a rule with no source.
- **Out of scope: a mounting field.** The PRD measured a 3 in standoff at −0.27% and two
  storeys at +0.32% of Bristol's year. Re-measured on this change for the default 4 kW,
  by setting `mount_standoff` or `array_height` in each array's parameters: −0.26% and
  +0.31%. It is a follow-up candidate under lead ruling L12, not filed.

## 3. Measurements

This is a dated record. Re-measure before relying on it.

- **Provenance.** 2026-10-20, on task 823's branch from main 8b65e02, and again from main
  85b1896 (at 2be9d1b) with identical figures: CPython 3.12.3, pvlib 0.15.1, pandas 3.0.3,
  numpy 2.4.6.
  - Bristol's TMY comes through `get_tmy_data` from the weather cache: key
    `tmy_f8a4df0259c4` (key version 2), GHI 1069.46 kWh/m², scaled to PVGIS v5_3's
    2005–2020 mean ([tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)). Task 1134
    commits that entry as `tests/fixtures/weather_cache/tmy_f8a4df0259c4.csv`; it
    equalled PVGIS's live response on 2026-10-25.
    `tests/integration/test_pvgis.py::TestPVGISTMY::test_the_committed_bristol_tmy_equals_the_live_one`,
    which the offline lane's `pvgis` job runs after every merge, fails once the entry no
    longer does (task 1139).
  - The clear day is `tests/_synthetic_weather.py::synthetic_june_weather` called with `"2024-06-21"`.
  - Each SAPM figure is the same chain with every array's temperature-model parameters
    set back to pvlib's SAPM `open_rack_glass_glass` set. It reproduces main's figures
    (3976.80 kWh and 993.14 kWh/kWp: [pv-system-losses.md](pv-system-losses.md) §5).
- **The headline.** Bristol's default 4 kW system yields 1012.1 kWh per wired kWp a year
  (from 993.1, +1.9%), a performance ratio of 0.819, inside
  `tests/integration/test_pv_performance_ratio.py`'s 0.76–0.84.
- **The code's copy.** `validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP` is this
  1012.1 figure (task 907, 2026-10-22). `tests/integration/test_pv_performance_ratio.py`
  re-measures it on that committed entry in every per-task verify (task 1134), and fails
  when the figure moves more than 1% from the constant, until the constant moves with it.
- **Bristol, default 4 kW**, by the script's `measure` (4.00428 wired kWp; in-plane
  1236.12 kWh/m²), SAPM → NOCT-SAM:
  - with the system losses: 3976.80 → 4052.83 kWh, 993.14 → 1012.12 kWh/kWp, ratio
    0.8034 → 0.8188;
  - without them: 4632.66 → 4716.89 kWh, 1156.93 → 1177.96 kWh/kWp, ratio 0.9359 → 0.9529.
- **Clear day and Bristol year**, `simulate_pv_output`'s energy with the default system
  losses, SAPM → NOCT-SAM:

| System | Wired kWp | Clear day, kWh | × | Bristol year, kWh | × | kWh per wired kWp |
|---|---|---|---|---|---|---|
| Default 4 kW | 4.00428 | 26.0119 → 26.8194 | 1.0310 | 3976.80 → 4052.83 | 1.0191 | 993.14 → 1012.12 |
| 3 kW | 2.80300 | 18.2180 → 18.7802 | 1.0309 | 2776.73 → 2829.77 | 1.0191 | 990.63 → 1009.55 |
| 6 kW on a 3.68 kW inverter (two arrays) | 6.00642 | 33.2769 → 33.4493 | 1.0052 | 5769.08 → 5831.92 | 1.0109 | 960.49 → 970.95 |
| 4 kW of `create_simple_module_params(efficiency=0.10)` | 4.0 | 25.6783 → 26.2835 | 1.0236 | 3957.45 → 4020.65 | 1.0160 | 989.36 → 1005.16 |
| … `efficiency=0.15` | 4.0 | 25.6783 → 26.4308 | 1.0293 | 3957.45 → 4031.58 | 1.0187 | 989.36 → 1007.89 |
| … `efficiency=0.20` | 4.0 | 25.6783 → 26.5780 | 1.0350 | 3957.45 → 4042.51 | 1.0215 | 989.36 → 1010.63 |
| … `efficiency=0.22` | 4.0 | 25.6783 → 26.6369 | 1.0373 | 3957.45 → 4046.88 | 1.0226 | 989.36 → 1011.72 |
| 4 kW of `{"pdc0": 300.0, "gamma_pdc": -0.004}` (13 modules) | 3.9 | 25.0340 → 25.7703 | 1.0294 | 3856.67 → 3929.14 | 1.0188 | 988.89 → 1007.47 |

- **Efficiency now acts.** 4 kW of 10% efficient modules yields 0.9867 × the 22% ones'
  energy on the clear day, and 0.9935 × over Bristol's year. Under SAPM the two were
  equal.
- **Hottest cell.** The default's hottest cell over Bristol's year is 58.9 °C
  (1990-07-27 12:00 UTC), against 56.6 °C under SAPM
  ([pv-inverter-string-matching.md](pv-inverter-string-matching.md) §7(f)).
- **Night.** 4534 of the year's 8760 hours have a NaN cell temperature. Each of them has
  no in-plane irradiance, and the DC is 0 in every one. The AC has no NaN.
- **Solver warnings.** Under SAPM, the CEC chains raised 39 `_chandrupatla`
  RuntimeWarnings per clear day and 100 per Bristol year for each array: 78 and 200 for
  the two-array 6 kW. The PVWatts chains raised none. Under NOCT-SAM every chain above
  raises 0.

## 4. Consequences

Every PV figure moves, and so does every figure that depends on PV generation: bills,
the cost-recovery rate, the benchmarks. Each doc that records one carries a dated
task-823 amendment, or marks the figure as predating NOCT-SAM:

- [pv-system-losses.md](pv-system-losses.md) §4 and §5;
- [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §1 and §3;
- [pv-inverter-efficiency.md](pv-inverter-efficiency.md) §3;
- [tmy-irradiation-scaling.md](tmy-irradiation-scaling.md) §4 and §7;
- [finance-spreadsheet-reconciliation.md](finance-spreadsheet-reconciliation.md) §4.2 and §5;
- [pv-inverter-string-matching.md](pv-inverter-string-matching.md) §3–§7;
- the consumer notice: [domain-library-consumption.md](domain-library-consumption.md)'s
  Unreleased line for task 823.

## 5. When to Revisit

- pvlib changes `noct_sam` or its defaults (`array_height`, `mount_standoff`,
  `transmittance_absorptance`), or its `ModelChain` stops filling the night's DC or AC
  with 0. `tests/unit/test_pv_cell_temperature.py` then fails.
- A mounting field arrives: a standoff or array height in `PVConfig`.
- Module data lacks `T_NOCT` or `A_c`, e.g. a library other than CECMod. The default
  module's values then decide those modules' cell temperature.
