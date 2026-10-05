# PV Inverter/String Matching: MPPT-Window Sizing

**Task:** #203 (follow-up from #189); #240 (§7)
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`_voltage_matched_cec_inverter`, `_ranking_key`, `_wiring_within_window`, `CecInverter.admits`, `candidate_cec_inverters`, `CecInverter.is_battery_inverter`, `create_model_chain_picking_from`)
**PRD:** [docs/prds/discrete-install-config-sweep.md](prds/discrete-install-config-sweep.md) §2.1
**Measurement:** [`scripts/measure_mppt_window.py`](../scripts/measure_mppt_window.py) (§3)

---

## 1. What the Code Does

A module with a `V_mp_ref` gets a CEC inverter voltage-matched to its strings:
`_ranking_key` orders the candidate inverters, and `_wiring_within_window` wires the
modules as the fewest near-equal series strings, each group of equal strings being one
pvlib `Array`, i.e. one MPPT input. The candidates, `candidate_cec_inverters`, are the
usable CEC rows minus the battery inverter/chargers (§7). The sizing rule this note is
about is `CecInverter.admits`: every string's STC voltage, modules × `V_mp_ref`, must lie
inside the inverter's `[Mppt_low, Mppt_high]`. Custom inverter parameters and PVWatts
modules bypass the matching (`_inverter_and_wiring`). Those functions are the source of
truth for the ranking and the wiring; this note does not restate them.

## 2. Decision (task 203, 2026-10-01): Strings Stay Sized on STC V_mp_ref

This decision covers the window's ceiling; §7 covers the floor. Strings are
sized on the module's STC `V_mp_ref`, not on a cold-corrected V_mp or a fixed margin
below `Mppt_high`. Operating V_mp does exceed the ceiling on cold hours, but on the
Bristol TMY that costs at most 0.21% of annual AC (median 0.014%, §4). Sizing with
enough headroom to keep every hour inside (a 0 °C design cell) would re-pick the
inverter or the wiring, and move the affected capacities' annual AC by a median of about
0.4%, and up to 2.4% (3.5% on a 5 kW inverter), in either direction. That change is more
than ten times the error it removes, with no gain in accuracy (§4).

## 3. Method

[`scripts/measure_mppt_window.py`](../scripts/measure_mppt_window.py) is the method. It
prints the figures in §4–§7, and can write a CSV with one row per sizing and
configuration; the figures for particular capacities, and §6's count against the band,
are read from that. Its docstring gives the command. A run takes about twelve minutes.
[`tests/unit/test_measurement_scripts.py`](../tests/unit/test_measurement_scripts.py)
runs it offline on a one-day TMY at one capacity (`--dc-kw`); the full run is not part
of the test suite. §7 measures the window's floor with it.
In outline:

- **Provenance.** Measured on main 9e9ab8f (2026-09-30), re-measured in full on
  abd0bcc (2026-10-01), and reproduced by the script on task 203's branch from main
  a0f1102 (2026-10-01). pv.py's selection code and uv.lock are the same in all three.
  CPython 3.12.3, pvlib 0.15.1, pandas 3.0.3, numpy 2.4.6. §7 was measured by the
  script on task 240's branch from main 684c9ec (2026-10-03), on the same versions.
- **Weather.** The PVGIS TMY for `Location.bristol()`: year 1990, UTC-indexed, 8760
  hours, minimum air temperature −6.2 °C, cached as `tmy_5dc8c8bca218`. The script
  reads it through the weather cache and prints those facts, so a different TMY shows.
  **[Amended 2026-10-03, task 285: that was the unscaled TMY. `get_tmy_data` now scales
  its irradiance by 1.078 ([tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)), so
  the figures here and in §4 and §6 describe the unscaled year, and the script now reads
  the scaled one; the facts it prints stay the same, since the scaling leaves the year,
  its hours and its temperatures alone. For the annual-yield band under the scaled TMY,
  see [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md) §3.]**
  **[Amended 2026-10-03, task 240: the script now also prints the TMY's annual GHI,
  1069.5 kWh/m² for the scaled year, cached as `tmy_f8a4df0259c4`, against 992.3 for the
  unscaled one, so the two years show apart. §7 is measured on the scaled one.]**
- **Model.** `create_model_chain(config, location).run_model(tmy)`. The hourly AC,
  clipped at 0 and summed, equals the year-long home's generation: 4 kW gives
  4328.13 kWh, as `simulate_home` does over a whole year. A producing hour has sunlight
  on the cells. Counting `p_mp > 0` instead would add 518 night hours, where the diode
  solver leaves about 1e-43 W.
- **Module.** The representative CEC module: 400.428 W at STC, `V_mp_ref` 44.1 V,
  `V_oc_ref` 53.4 V, `beta_oc` −0.147064 V/K. The CEC library has no V_mp temperature
  coefficient.
- **Sizing.** Each configuration gets its inverter and wiring from pv.py's own
  selection. An alternative sizing in §4 divides every catalogue `Mppt_high` by its
  factor before that selection runs, which is the same check as multiplying the string
  voltage by it. A hot-floor sizing in §7 divides every `Mppt_low` by its factor in the
  same way. §7's "battery inverter/chargers kept" alternative picks from every usable
  CEC row, as pv.py did before task 240. Each sizing's candidates, moved or not, reach
  pv.py's selection through `create_model_chain_picking_from`.
- **(a) Extrapolation alone.** `pvlib.inverter.sandia_multi` gets each array's `v_mp`
  moved to the window's edge in its out-of-window hours, at unchanged `p_mp`. Its annual
  AC is compared with the model's.
- **(b) What a real inverter delivers.** An inverter holds a string outside its window
  at the window's edge, off the maximum power point. Each out-of-window hour is
  re-evaluated there, on the module's IV curve (`pvlib.pvsystem.i_from_v` with the
  chain's diode parameters), and `sandia_multi` gets that power at the edge's voltage.
- **Counting.** Configured capacities that wire the same modules to the same inverter
  give identical results, so §4 takes the current sizing's error over distinct
  inverter/wiring pairs; the census and headroom tables count configs. Medians are
  pandas' (an even count takes the mean of the middle two).

## 4. Ceiling-Side Measurement

**[Amended 2026-10-03, task 240: the counts below predate task 240's 23 re-picks, and the
last headline bullet's 90.2% no longer holds (91.9% since); §7(h) gives the counts after
the re-picks.]**

**Operating voltage.**
- The highest module V_mp is 1.0684 × `V_mp_ref` (47.1 V), at 1990-03-04 08:00 UTC:
  POA 258 W/m², cell 4.3 °C, air −3.8 °C.
- The six hours above 1.06 × `V_mp_ref` fall in February, March and December, between
  08:00 and 11:00 UTC, at 184–301 W/m² with cells at 4.0–6.9 °C.
- For the default 4 kW string, 1679 of its 4226 producing hours, carrying 38.3% of its
  DC energy, run above `V_mp_ref`.

**Proxy coefficient.**
- `beta_oc / V_oc_ref` is −0.275 %/K. As a proxy for V_mp's coefficient it gives ×1.041
  at a 10 °C cell, ×1.069 at 0 °C and ×1.096 at −10 °C.
- The model's own single-diode V_mp at 1000 W/m² (`pvlib.pvsystem.calcparams_cec` then
  `max_power_point`) rises about 0.375 %/K as the cell cools (×1.056 / ×1.094 /
  ×1.132), so the proxy understates it.
- On this TMY cold cells occur only at low irradiance, so the 0 °C proxy (×1.069) still
  bounds the observed peak (×1.068).

**Census.** 248 DC capacities, 0.3–25.0 kW in 0.1 kW steps, at each
`inverter_capacity_kw`. "Unset" is default rating, i.e. the DC capacity.

| | unset | 3.0 kW | 3.68 kW | 5.0 kW |
|---|---|---|---|---|
| Longest string within 10% of `Mppt_high` at STC | 68 | 168 | 108 | 92 |
| Configs with any hour above `Mppt_high` | 33 | 88 | 0 | 92 |
| Most hours above, of 4226 producing | 1215 | 1215 | 0 | 1660 |
| Largest overshoot | 52.4 V | 24.1 V | – | 51.0 V |

**Error of the current sizing**, over the 64 distinct inverter/wiring pairs with any
hour above the ceiling:
- (a) |ΔAC| ≤ 0.015%.
- (b) The model overstates annual AC by a median of 0.014%, and at most 0.21%. The
  maximum is 6.7 kW on a 5.0 kW inverter: one string of 17, above the 750 V ceiling for
  1660 h, which carry 37.8% of its DC energy.
- At default rating the maximum is 0.12% (21.5 kW, three strings of 18 under 800 V).
  7.4 kW, two strings of 9 under 400 V, is 0.11%.

**Headroom alternative.** The ceiling check becomes modules × `V_mp_ref` ×
(1 + (`beta_oc` / `V_oc_ref`)(T_cell − 25 °C)) ≤ `Mppt_high` at a design cell
temperature T_cell. The floor check and the ranking are unchanged. "Re-picks" counts the
configs whose inverter or wiring changes, and ΔAC is their annual AC change. "Hours
left" is the most hours any config in the column still spends above the ceiling.

| Design cell | | unset | 3.0 kW | 3.68 kW | 5.0 kW |
|---|---|---|---|---|---|
| 10 °C | re-picks | 31 | 88 | 0 | 60 |
| | \|ΔAC\| median / max | 0.37 / 2.43% | 0.48 / 2.18% | – | 0.43 / 1.89% |
| | mean ΔAC | −0.26% | −0.63% | – | +0.15% |
| | hours left | 1 | 0 | 0 | 12 |
| 0 °C | re-picks | 33 | 88 | 0 | 92 |
| | \|ΔAC\| median / max | 0.37 / 2.43% | 0.48 / 2.18% | – | 0.44 / 3.53% |
| | mean ΔAC | −0.29% | −0.63% | – | −0.37% |
| | hours left | 0 | 0 | 0 | 0 |
| −10 °C | re-picks | 68 | 168 | 0 | 92 |
| | \|ΔAC\| median / max | 0.38 / 8.66% | 0.06 / 2.18% | – | 0.44 / 3.53% |
| | mean ΔAC | −0.49% | −0.32% | – | −0.37% |
| | hours left | 0 | 0 | 0 | 0 |

- A fixed margin that caps the STC string voltage at `Mppt_high` / 1.05 makes the same
  picks as 10 °C, and a cap at `Mppt_high` / 1.10 the same as −10 °C.
- A re-pick moves AC because the model then evaluates a different inverter's Sandia
  fit, or the same inverter at another voltage inside its window.
- The −10 °C maximum, +8.66% at 15.3 kW, is a swap away from the catalogue's Xantrex
  PV15-208. The same 38 modules model 15,017 kWh on it, against 16,328–16,359 kWh on the
  inverters picked at 15.2 and 15.4 kW.

**Headline configs.**
- 3, 4, 5 and 6 kWp never go above the ceiling, at default rating or on a 3.0, 3.68 or
  5.0 kW inverter. Some sizes between them do: 4.4 and 4.6 kWp at default rating spend
  351 h above, which the model overstates by at most 0.014%.
- The default 4 kW is one string of 10: 441 V at STC and 471 V at its peak hour, under
  its inverter's 500 V ceiling.
- On the 3.68 kW G98 inverter, no capacity from 0.3 to 25 kW exceeds 90.2% of the
  ceiling at STC.

## 5. Scope and When to Revisit

- `Vdcmax` equals `Mppt_high` on all 3264 rows of pvlib 0.15.1's CEC library, so the
  ceiling check is also the `Vdcmax` check.
  - The installer's safety rule, string V_oc at the coldest cell ≤ `Vdcmax`, is not
    modelled. The default string's STC V_oc (10 × 53.4 = 534 V) already exceeds its
    Samil SolarRiver4000TL-US's 500 V.
  - The model chain has no over-voltage behaviour, so this has no energy effect in the
    model.
  - Adopting the rule would re-pick inverters, the default's included. That effect is
    unmeasured.
- The floor is checked at STC too; §7 measures it and records why.
- The measurement covers Bristol only. Re-run §3's script, with the site or module
  changed, before relying on it for a colder site or a module with a larger voltage
  temperature coefficient. Re-run it too once the model gains out-of-window inverter
  behaviour or a new selection policy.

## 6. Annual-Yield Band Re-Check (Task Item 5)

- Per wired DC kWp (modules × 400.428 W), the 248 default-rated capacities give
  969.4–1098.5 kWh/kWp (median 1078.6). That is inside `validation.py`'s coded 700–1100
  and the review briefing's "~700-1100".
- The headline 3, 4, 5 and 6 kWp at default rating read 995.7–1082.0 kWh per nameplate
  kWp.
- At this measurement `validate_pv_generation` divided by the nameplate `capacity_kw`,
  while the model wires whole modules, so 10 of the 248 read outside the band (0.3 kW,
  one 400 W module: 1407.5). Task 239 moved the check to the wired DC
  (`pv.wired_dc_capacity_kw`), under which all 248 read inside it; see
  [pv-annual-yield-benchmark.md](pv-annual-yield-benchmark.md).

## 7. Floor Side: Battery Inverter/Chargers (Task 240)

These figures are on the scaled TMY (§3), unlike §4's and §6's.

**(a) Decision (task 240, 2026-10-03).** Battery inverter/chargers are left out of the
inverter candidates, and the floor stays checked at STC, as the ceiling is (§2).

**(b) What they are.**
- A battery inverter/charger's DC input is its battery bus, which PV reaches only
  through a charge controller, so its CEC MPPT window is the battery's voltage range.
  The OutBack GS8048A's is 44–56 V: its floor sits at the module's 44.1 V STC `V_mp`,
  so a module wired straight to it runs below the window whenever its cells are warm.
- The CEC library has no flag for them; its `CEC_Type` is only "Utility Interactive" or
  "Grid Support". 22 usable rows are battery inverter/chargers:
  - OutBack Power's GS4048A, GS8048A, GS8048, FXR3048A, GTFX3048, VFXR3648A, GVFX3648,
    VFXR3524A and GVFX3524, with their 120 V and 240 V variants (14 rows);
  - SMA's Sunny Island SI6048, Beacon Power's M4, M4 Plus, M5 and M5 Plus, GridPoint's
    Connect C36, Alpha Technologies' Solaris 3500 XP and Heart Transverter's HT2000.
- The cut is a nominal DC voltage (`Vdco`) of at most 60 V at a rating (`Paco`) above
  1.5 kW. `CecInverter.is_battery_inverter` is its single source; this note
  transcribes it.
- It falls in clean gaps in pvlib 0.15.1's catalogue, so any cut inside them drops the
  same rows. Kept rows at `Vdco` ≤ 54.5 V reach at most 1400 W. The dropped rows start
  at 1970 W and reach at most 54.5 V. The lowest kept `Vdco` at 1970 W or more is 62 V.

**(c) Before.** With them kept, 23 census configs pick one. Under §3's (b):
- The OutBack GS4048A and GS8048A take single-module strings under a 44 V floor, and
  60.9% of their DC energy, over 2381 hours, falls below it. The model overstates annual
  AC by 2.83% at 0.3–0.6 kW on the 3.68 kW inverter, by 2.07% at 0.7–1.0 kW, and by
  1.42% at 7.2–7.3 kW at default rating.
- The SMA SI6048's 41 V floor takes 6.2% of a lone module's DC energy over 237 hours
  (0.03%). The 40 V floor of the GridPoint C36 and OutBack FXR3048A takes 1.3% over
  106 hours (under 0.01%).

**(d) What leaving them out changed.** ΔAC is the change in annual AC from the battery
inverter/charger to the new pick, on the same modules.

| Inverter | DC | Before | After | ΔAC |
|---|---|---|---|---|
| unset | 2.6 kW | OutBack FXR3048A, 6 strings of 1 module | Schneider Conext TX 2800 NA, 1 string of 6 modules | +3.72% |
| unset | 7.2 kW | OutBack GS8048A, 18 strings of 1 module | Growatt 8000MTLP-US, 2 strings of 9 modules | +4.03% |
| unset | 7.3 kW | OutBack GS8048A, 18 strings of 1 module | Motech PVMate 7500U, 2 strings of 9 modules | +1.92% |
| 3.0 kW | 0.3–0.6 kW | GridPoint Connect C36, 1 string of 1 module | Altenergy QS1200, 1 string of 1 module | +44.33% |
| 3.0 kW | 0.7–1.0 kW | GridPoint Connect C36, 2 strings of 1 module | Altenergy QS1200, 2 strings of 1 module | +19.88% |
| 3.68 kW | 0.3–0.6 kW | OutBack GS4048A, 1 string of 1 module | Altenergy QS1200, 1 string of 1 module | +43.67% |
| 3.68 kW | 0.7–1.0 kW | OutBack GS4048A, 2 strings of 1 module | SUNERGY LV 208, 1 string of 2 modules | −3.42% |
| 5.0 kW | 0.3–0.6 kW | SMA Sunny Island SI6048, 1 string of 1 module | Altenergy QS1200, 1 string of 1 module | +11.15% |

- The large changes on one- and two-module arrays come from inverter tare (`Pso`):
  57–63 W on the OutBack and GridPoint units and 18 W on the SMA SI6048, against 6.9 W
  on Altenergy's (APsystems') QS1200 microinverter. So a lone module reads 775–778 kWh
  per wired kWp on the OutBack and GridPoint units, 1006 on the SI6048 and 1118 on the
  QS1200, inside the 1051–1184 that default-rated arrays read. The −3.42% moves two
  modules to the SUNERGY LV 208, a PV inverter whose 55.8 W tare is close to the
  GS4048A's 57.5 W.
- The headline 3, 4, 5 and 6 kWp configs keep their picks.

**(e) After.** The floor's worst error under §3's (b) is now 0.12%: the Huawei
SUN2000-22KTL-US at 21.9–22.2 kW, three strings of 14 modules and one of 13 under its
560 V floor, below it for 1129 hours that carry 8.6% of the DC energy. Next is 0.09%,
the Fronius Symo Advanced 12.0 at 12.3–12.4 kW. 36 distinct inverter/wiring pairs spend
any hour below the floor, against 42 with the battery inverter/chargers kept.

**(f) Hot-floor alternative.** The floor check becomes modules × `V_mp_ref` ×
(1 + (`beta_oc` / `V_oc_ref`)(T_cell − 25 °C)) ≥ `Mppt_low` at a design cell
temperature T_cell: ×0.945 at 45 °C, ×0.917 at 55 °C and ×0.890 at 65 °C. The ceiling
check and the ranking are unchanged. The rows read as in §4's headroom table; "hours
left below" is the most hours any config in the column still spends below the floor.

| Design cell | | unset | 3.0 kW | 3.68 kW | 5.0 kW |
|---|---|---|---|---|---|
| 45 °C | re-picks | 6 | 0 | 0 | 0 |
| | \|ΔAC\| median / max | 0.01 / 0.77% | – | – | – |
| | mean ΔAC | +0.25% | – | – | – |
| | hours left below | 292 | 0 | 0 | 257 |
| 55 °C | re-picks | 19 | 0 | 0 | 4 |
| | \|ΔAC\| median / max | 5.79 / 12.11% | – | – | 3.39 / 3.39% |
| | mean ΔAC | +4.17% | – | – | −3.39% |
| | hours left below | 106 | 0 | 0 | 0 |
| 65 °C | re-picks | 25 | 0 | 0 | 4 |
| | \|ΔAC\| median / max | 1.44 / 12.11% | – | – | 3.39 / 3.39% |
| | mean ΔAC | +3.23% | – | – | −3.39% |
| | hours left below | 44 | 0 | 0 | 0 |

- At 45 °C, the two re-picks at 12.3 and 12.4 kW move annual AC by +0.77% and +0.70%,
  about eight times the 0.09% error they remove. The four at 21.9–22.2 kW move it by
  +0.014%, less than their 0.12%, and other configs keep up to 292 hours below the
  floor.
- Keeping nearly every hour inside needs a design cell near the TMY's hottest, 56.6 °C
  on the default 4 kW array. At 55 and 65 °C, 23 and 29 configs move by up to 12.1%.
- So, as §2 found for the ceiling, the floor stays checked at STC.

**(g) Ranking alternative.** Preferring fewer parallel strings cannot help the worst case
in (c): a one-module array's only wiring is one single-module string.

**(h) What the re-picks change in §4.** Re-pick counts and counts of strings near the
ceiling do not depend on the weather, so these compare directly with §4's figures. The
CSV's "kept" rows show 33 default-rated configs with an hour above the ceiling, as §4
has, so each change below is task 240's.
- Longest string within 10% of `Mppt_high` at STC: 69 / 176 / 112 / 96 configs (§4:
  68 / 168 / 108 / 92).
- Configs with any hour above `Mppt_high` at default rating: 34, because 7.3 kW now
  shares 7.4 kW's two strings of 9, 396.9 V under the Motech PVMate 7500U's 400 V.
- The 3.68 kW column's largest STC share of the ceiling is 91.9%: the QS1200 at
  0.3–0.6 kW, 44.1 V under 48 V, with no hour above.
- Headroom re-picks at default rating: 32 at 10 °C (§4: 31) and 34 at 0 °C (§4: 33).
  At −10 °C: 69 / 176 / 4 / 96 (§4: 68 / 168 / 0 / 92).
- Unchanged: the sizings that make identical picks, and the error of the current sizing,
  whose 64 distinct pairs are the same with or without the battery inverter/chargers.
