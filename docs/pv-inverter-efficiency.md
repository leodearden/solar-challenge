# PV Inverter Efficiency: The Configured Efficiency at Rated Output

**Task:** #236 (follow-up from #195; folds #479)
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`PVConfig.inverter_efficiency`, `_inverter_and_wiring`, `create_model_chain_picking_from`)
**Tests:** [`tests/unit/test_pv.py`](../tests/unit/test_pv.py)'s `TestCecInverterEfficiency` and `TestTheSystemNamesItsInverter`; [`tests/unit/config/test_generate_homes.py`](../tests/unit/config/test_generate_homes.py)'s `TestGenerateHomesFromDistributionInverterEfficiency`

---

## 1. What the Code Does

- `PVConfig.inverter_efficiency` (default 0.96) is every inverter's efficiency at rated
  output:
  - the voltage-matched CEC inverter's `Pdco` is `Paco / inverter_efficiency`; pvlib's
    Sandia model turns `Pdco` of DC at the nominal voltage `Vdco` into `Paco` of AC;
  - the PVWatts inverter takes it as `eta_inv_nom`;
  - `custom_inverter_params` carry their own.
- Only the rated point is configured. The picked inverter keeps its catalogue `Pso` and
  `C0`–`C3`, so its tare and part-load shape.
- The `PVSystem` names the picked CEC row as `PVSystem.inverter`, or `None` for custom or
  PVWatts inverters. With `Pdco` configured the parameters equal no catalogue row, so a
  reader that needs the pick's name, such as
  [`scripts/measure_mppt_window.py`](../scripts/measure_mppt_window.py), takes it from
  there.

## 2. Decision (task 236, 2026-10-10): Always Apply the Configured Efficiency

- The CEC pick is by rating and MPPT window
  ([pv-inverter-string-matching.md](pv-inverter-string-matching.md)), so the picked
  inverter's own `Paco / Pdco` is incidental:
  - across the 249 default-rated capacities (0.3–25.0 kW in 0.1 kW steps, plus 3.68) it
    ran from 0.892 (2.7 kW) to 0.983 (20.2 kW);
  - neighbours jumped: 2.6/2.7/2.8 kW read 0.946/0.892/0.946;
  - the 3.68 kW G98 rating ran at 0.941.
- Before task 236, 0.96 was a sentinel meaning "keep the catalogue's":
  - neither the default nor an explicit 0.96 modelled a 96% inverter;
  - a fleet distribution over `inverter_efficiency` was discontinuous at 0.96. On
    `tests/unit/test_pv.py`'s `clear_june_daytime`, 3.68 kW made 17.40 kWh at 0.955,
    17.15 at 0.96 and 17.57 at 0.965.
- Rejected: `Optional`, with `None` meaning "the catalogue's". It keeps the incidental,
  capacity-dependent efficiency, needs a second default for the PVWatts inverter, and
  changes a frozen public signature.

## 3. Effect

This is a dated record, with the system losses
([pv-system-losses.md](pv-system-losses.md)), on Bristol's scaled TMY. Re-measure before
relying on it.

- Annual kWh per wired kWp over the 248 capacities 0.3–25.0 kW, by
  [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §3's method:
  - before: 890.7 (10.2 kW) to 1016.8 (10.8 kW), median 997.9, pstdev 23.1;
  - after: 925.9 (10.2 kW) to 1007.7 (10.1 kW), median 989.1, pstdev 11.5;
  - none falls outside validation's 300–1200 (benchmark §2) either way.
- Per capacity, −2.3% (20.2 kW) to +6.9% (2.7 kW): 3.0 kW +0.5%, 3.68 kW +2.0%,
  4.0 kW −0.7%, 5.0 kW −1.1%, 6.0 kW −1.3%.
- AC peak per wired DC, by benchmark §4's method: at most 0.961 before, and 0.948 after
  (at 0.4 kW).
- The default 4 kW's performance ratio (pv-system-losses.md §1's definition): 0.8089
  before, and 0.8034 after (993.14 kWh/kWp). Both are inside the slow guard's 0.76–0.84.
- Provenance:
  - "before" is as recorded in benchmark §3 and pv-system-losses.md §5, re-measured with
    the per-capacity changes by the task 236 architect on main aca7236 (2026-10-10);
  - "after" was measured on task 236's commit be3e1de (2026-10-10);
  - CPython 3.12.3, pvlib 0.15.1, pandas 3.0.3, numpy 2.4.6; TMY `tmy_f8a4df0259c4`,
    GHI 1069.5 kWh/m².
- Other dated records were measured with the catalogue efficiency: pv-system-losses.md
  §5's site table, [tmy-irradiation-scaling.md](tmy-irradiation-scaling.md),
  [finance-spreadsheet-reconciliation.md](finance-spreadsheet-reconciliation.md) §4.2 and
  [pv-inverter-string-matching.md](pv-inverter-string-matching.md).
