# PV Inverter/String Matching: MPPT-Window Sizing

**Task:** #203 (follow-up from #189)
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`_voltage_matched_cec_inverter`, `_ranking_key`, `_wiring_within_window`, `_CecInverter.admits`)
**PRD:** [docs/prds/discrete-install-config-sweep.md](prds/discrete-install-config-sweep.md) §2.1
**Measurement:** [`scripts/measure_mppt_window.py`](../scripts/measure_mppt_window.py) (§3)

---

## 1. What the Code Does

A module with a `V_mp_ref` gets a CEC inverter voltage-matched to its strings:
`_ranking_key` orders the candidate inverters, and `_wiring_within_window` wires the
modules as the fewest near-equal series strings, each group of equal strings being one
pvlib `Array`, i.e. one MPPT input. The sizing rule this note is about is
`_CecInverter.admits`: every string's STC voltage, modules × `V_mp_ref`, must lie inside
the inverter's `[Mppt_low, Mppt_high]`. Custom inverter parameters and PVWatts modules
bypass the matching (`_inverter_and_wiring`). Those functions are the source of truth
for the ranking and the wiring; this note does not restate them.

## 2. Decision (task 203, 2026-10-01): Strings Stay Sized on STC V_mp_ref

This decision covers the window's ceiling; §5 says where the floor stands. Strings are
sized on the module's STC `V_mp_ref`, not on a cold-corrected V_mp or a fixed margin
below `Mppt_high`. Operating V_mp does exceed the ceiling on cold hours, but on the
Bristol TMY that costs at most 0.21% of annual AC (median 0.014%, §4). Sizing with
enough headroom to keep every hour inside (a 0 °C design cell) would re-pick the
inverter or the wiring, and move the affected capacities' annual AC by a median of about
0.4%, and up to 2.4% (3.5% on a 5 kW inverter), in either direction. That change is more
than ten times the error it removes, with no gain in accuracy (§4).

## 3. Method

[`scripts/measure_mppt_window.py`](../scripts/measure_mppt_window.py) is the method. It
prints the figures in §4–§6, and can write a CSV with one row per sizing and
configuration; the figures for particular capacities, and §6's count against the band,
are read from that. Its docstring gives the command. A run takes about twelve minutes,
and the script is not part of the test suite. Task 240 measures the window's floor with
it too. In outline:

- **Provenance.** Measured on main 9e9ab8f (2026-09-30), re-measured in full on
  abd0bcc (2026-10-01), and reproduced by the script on task 203's branch from main
  a0f1102 (2026-10-01). pv.py's selection code and uv.lock are the same in all three.
  CPython 3.12.3, pvlib 0.15.1, pandas 3.0.3, numpy 2.4.6.
- **Weather.** The PVGIS TMY for `Location.bristol()`: year 1990, UTC-indexed, 8760
  hours, minimum air temperature −6.2 °C, cached as `tmy_5dc8c8bca218`. The script
  reads it through the weather cache and prints those facts, so a different TMY shows.
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
  voltage by it.
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
- The floor is also checked at STC, and is outside this task. Measured by the §3
  method, its effect is at most 0.09%, except where a 48 V battery inverter
  (`Mppt_low` 44 V) is picked with single-module strings: there it reaches −2.3%
  (0.3–0.6 kW on the 3.68 kW inverter). At default rating, 7.2 kW picks an OutBack
  GS8048A wired as 18 single-module strings; 58% of its DC energy falls below the floor,
  and annual AC is 1.11% lower. Task 240 owns that.
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
