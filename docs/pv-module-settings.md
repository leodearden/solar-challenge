# PV Module Settings: Module Efficiency and Temperature Coefficient Derive the Module

**Task:** #825
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`PVConfig`, `_module_parameters`, `_with_temperature_coefficient`, `_with_module_efficiency`, `_adjust_giving`, `_adjust_bracket`, `_modelled_gamma`)
**Measurement:** [`tests/unit/test_pv_module_settings.py`](../tests/unit/test_pv_module_settings.py)

---

## 1. What the Code Does

- A system's module starts from its **template**: `PVConfig.custom_module_params`, copied,
  or else the CECMod row `DEFAULT_CEC_MODULE` names. `module_efficiency` and
  `temperature_coefficient` are `None` by default, and an unset field leaves the
  template as it is: the module keeps its own efficiency (its rating over `A_c` × 1000
  W/m²) and its own modelled temperature coefficient.
- **A set temperature coefficient** derives the module in the template's own form
  (`_with_temperature_coefficient`):
  - A **CEC single-diode** template (`alpha_sc`, `a_ref`, `I_L_ref`, `I_o_ref`,
    `R_sh_ref`, `R_s`, `Adjust`) gets the `Adjust` at which its modelled coefficient
    equals the set one, and `gamma_r` = 100 × the coefficient (in %/K, as the catalogue
    gives it).
    - The modelled coefficient (`_modelled_gamma`) is dP_mp/dT / P_mp at 1000 W/m² and
      25 °C: a central difference over 25 ± 0.5 °C through pvlib's
      `PVSystem.calcparams_cec` and `singlediode`. That is the model chain's own path,
      so a custom template's `EgRef`, `dEgdT`, `irrad_ref` and `temp_ref` count as the
      chain counts them.
    - scipy's `brentq` finds the `Adjust` (`_adjust_giving`). It searches between the
      `Adjust`s that keep the derived module's photocurrent positive at every cell
      temperature from −40 to 85 °C, IEC 61215's thermal-cycling range
      (`_adjust_bracket`): 100 (1 ∓ I_L_ref / (65 |alpha_sc|)).
  - A **PVWatts** template (`pdc0`, `gamma_pdc`) gets `gamma_pdc` = the coefficient.
    A template in both forms gets both changes, so whichever DC model pvlib infers
    reads the coefficient.
- **A set module efficiency** sets `A_c` = rating / (efficiency × 1000 W/m²)
  (`_with_module_efficiency`), the rating being `_module_rating_w`'s: `pdc0` for a
  PVWatts module, else `STC`. It acts on output through NOCT-SAM's cell temperature
  ([pv-cell-temperature.md](pv-cell-temperature.md)): a less efficient module turns
  more of its light into heat. It takes any module form that has a rating.
- **Refusals**, each a `ValueError` naming the field and its value:
  - At construction (`PVConfig.__post_init__`): an efficiency outside (0, 0.9), 0.9
    being NOCT-SAM's transmittance–absorptance, at which a cell no longer heats; a
    coefficient outside [−0.01, 0) per K; and a set coefficient on custom parameters in
    neither form, such as a row of pvlib's `SandiaMod` library, naming the keys of each
    form.
  - At use (`create_pv_system`, and so every chain builder and `wired_dc_capacity_kw`):
    the same form rule, through the same function; a CEC template whose `alpha_sc` is
    0, since `Adjust` scales only `alpha_sc` and so cannot move the coefficient; and a
    coefficient beyond the reach of the bracket's ends, naming the bracket and the
    reach. The efficiency's use-time check is NOCT-SAM's own
    (`_require_cells_noct_sam_can_heat`).
- `scenario_writer` writes both keys, an unset one as null, and `_parse_pv_config` hands
  a null on as `None`, so a written home loads back equal. A fleet distribution that
  draws no `module_efficiency` gives every home `None`.

## 2. Decision and Source

- **Program D14** (plans/review-all-program-solar_challenge-20261014.md, stream S14):
  both fields become live model inputs that derive the module from its template row,
  STC-consistently, and the old `temperature_coefficient != -0.004` sentinel, which
  wrote `gamma_pdc` onto a CEC module whose model never reads it, goes. **D32**
  (session ruling): an unset field means the module's own value, so both are
  `float | None = None`, as `inverter_capacity_kw` is. The PRD is
  [prds/pv-model-one-home.md](prds/pv-model-one-home.md), resolved decisions 2–4, 11
  and 12.
- **Why `Adjust`.** `Adjust` is the parameter SAM's CEC coefficient calculator tunes so
  that the six-parameter model matches the module's measured temperature coefficient of
  maximum power (A. Dobos, "An Improved Coefficient Calculator for the California Energy
  Commission 6 Parameter Photovoltaic Module Model", *J. Sol. Energy Eng.* 134, 2012,
  the reference pvlib's `calcparams_cec` cites). `calcparams_cec` passes
  `alpha_sc × (1 − Adjust / 100)` to De Soto's model, so `Adjust` scales only the
  photocurrent's (T − 25) term: at 25 °C the STC point is the row's for any `Adjust`.
  No refit is needed, and pvlib's `fit_cec_sam` would need NREL-PySAM, which is not
  installed.
- **Why that bracket.** A fixed bracket is arbitrary and too narrow for part of the
  catalogue (§3). The photocurrent-positive range has a physical meaning, scales with
  each template, and lets every CECMod row with a non-zero `alpha_sc` reach the whole
  domain. Its reach depends only on |alpha_sc|, so `alpha_sc` = 0 is the one degenerate
  case, refused by name rather than divided by.
- **The domains.** 0.9 is NOCT-SAM's transmittance–absorptance, read from the one
  constant the model reads. −0.01 per K (−1 %/K) is steeper than every catalogue row's
  modelled coefficient (−0.68 %/K), and the old (−1, 0) admitted values no model can
  honour.
- **Rejected:** retiring both fields (cancelled task 195), which D14 rejected; and the
  description's "an absent key stays absent" writer rule, which lead ruling L35
  replaced with S7 decision 5: the writer writes every key, null when unset.

## 3. Measurements

Measured on 2026-10-21 with pvlib 0.15.1 and scipy 1.17.1 by task 825's architect on
main 49b70e1, through a prototype of this design. Figures marked † were re-measured on
this branch at cae3d55 and reproduce exactly.

- **The template.** `DEFAULT_CEC_MODULE`'s modelled coefficient is −0.34730 %/K (−0.0034730293
  per K; half-widths from 0.02 to 2 K agree within 1e-8/K), beside its catalogue
  `gamma_r` of −0.3448 %/K. Its P_mp at STC is bit-identical, 400.42808420797684 W, for
  every `Adjust` from −1000 to 2000, and its modelled coefficient is linear in `Adjust`
  within 1e-8/K from −1000 to 3000.
- **Solved `Adjust`s** for the default row: −0.003 per K gives −69.6079; −0.005 gives
  255.6187†; −0.01 gives 1068.6852; −1e-6 gives −557.285; its own modelled coefficient
  gives back 7.312982. Each solve takes about 9 ms, with no warning under `-W error`.
- **The bracket.** For the default row it is (−2358.94, 2558.94), whose ends reach
  +1.108 to −1.916 %/K. All 21,287 CECMod rows with a positive `alpha_sc` reach the
  whole domain [−0.01, 0); a fixed [−1000, 2000] would let 14,654 do so, and
  [−5000, 5000] 20,842. 25 rows have `alpha_sc` = 0, and 223 a negative one. The row at
  `EgRef` 3.0 reaches only −3.11506 to −0.0907687 %/K†, so −0.05 %/K is refused.
- **The tests' synthetic clear June day** (`synthetic_june_weather("2024-06-21")`, 4 kW
  at Bristol; the default gives 26.8194 kWh): a coefficient of −0.005 per K gives
  ×0.978618, −0.003 ×1.006607, −0.004 ×0.99263 and −0.01 ×0.90802; an efficiency of
  0.10 gives ×0.990086, 0.15 ×0.994987 and 0.22 ×1.001836. The day's cells run above
  25 °C, so a steeper coefficient yields less.
- **A Bristol year†** (the main checkout's `.cache/weather`, key `tmy_f8a4df0259c4`;
  the default 4 kW gives 4052.83 kWh with the default system losses): an efficiency of
  0.10 gives ×0.9951, 0.15 ×0.9975 and 0.22 ×1.0009; a coefficient of −0.003 per K gives
  ×0.9983, −0.004 ×1.0019 and −0.005 ×1.0055. Over the year the cells spend most of
  their hours below 25 °C, so a steeper coefficient gains: no test asserts an annual
  direction for the coefficient.

## 4. When to Revisit

- pvlib changes how `calcparams_cec` uses `Adjust`, or how `ModelChain` infers its DC
  model. A hand-built template that also carries the keys of a DC model pvlib ranks
  above its CEC or PVWatts form, such as SAPM's `A0`, `A1` and `C3`, runs that model,
  which would not read the coefficient. No such template is reachable from YAML, since
  the `pv:` block has no key for custom module parameters.
- A typed module specification replaces the trio of `module_efficiency`,
  `temperature_coefficient` and `custom_module_params`.
- Module data from outside pvlib's CECMod library becomes a template, whose rows the
  bracket's coverage (§3) does not describe.
