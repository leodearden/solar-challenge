# PV Module Settings: Module Efficiency and Temperature Coefficient Derive the Module

**Task:** #825, #1029, #1372, #1374, #1400, #1440
**Code:** [`src/solar_challenge/pv.py`](../src/solar_challenge/pv.py) (`PVConfig`, `_module_parameters`, `_template_with_set_efficiency`, `_with_temperature_coefficient`, `_with_module_efficiency`, `_adjust_giving`, `_adjust_bracket`, `_modelled_gamma`, `_require_module_values`, `_require_template_takes_temperature_coefficient`, `_require_adjust_reaches`)
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
  more of its light into heat. It takes any module form whose rating is a finite number
  above 0.
- **Refusals**, each a `ConfigurationError` (a `ValueError`) naming what it refuses:
  - At construction (`PVConfig.__post_init__`):
    - an efficiency outside (0, 0.9), 0.9 being NOCT-SAM's transmittance–absorptance,
      at which a cell no longer heats; a coefficient outside [−0.01, 0) per K;
    - custom parameters that give a key a model reads as a number as anything but a
      finite number (text, even text that reads as one, a boolean, `None`, NaN or
      infinity), or `cap_adjustment` as anything but true or false, naming the key and
      value (`_require_module_values`). pvlib's chain, NOCT-SAM and the string wiring
      read these keys from the module's own parameters into the power or voltage an
      inverter reads (§2, *Why these keys*). The rule reads the parameters as the
      caller gives them, whatever form the module is in, so it refuses a bad key even
      where a set field replaces it, as a set efficiency replaces `A_c`. It runs
      before the reach check, so a text optional CEC key under a set coefficient gets
      this refusal, not a bare `TypeError` from `calcparams_cec`. It reads:
      - as finite numbers, `gamma_pdc`, the CEC single-diode parameters, `T_NOCT`,
        `A_c` and `V_mp_ref`;
      - as finite numbers, the optional keys pvlib defaults when a module lacks them:
        `calcparams_cec`'s `EgRef`, `dEgdT`, `irrad_ref` and `temp_ref`,
        `pvwatts_dc`'s `temp_ref` and `k`, the effective irradiance's `FD` and the
        physical IAM's `n`, `K`, `L` and `n_ar`. Leave one out to take pvlib's
        default: one given as `None` is refused;
      - as finite numbers, SAPM's 16 DC parameters (`C0` to `C3`, `Isco`, `Impo`,
        `Voco`, `Vmpo`, `Aisc`, `Aimp`, `Bvoco`, `Mbvoc`, `Bvmpo`, `Mbvmp`, `N` and
        `Cells_in_Series`) and PVsyst's `gamma_ref`, `mu_gamma`, `R_sh_0`, `R_sh_exp`
        and `cells_in_series`;
      - as true or false, `pvwatts_dc`'s flag `cap_adjustment`
        (`boolean_fields.as_boolean`);
      - nothing else. SAPM's `IXO`, `IXXO` and `C4` to `C7`, which pvlib reads only
        into `i_x` and `i_xx` and 10 SandiaMod rows give as NaN, are not checked, so
        text there still raises a `TypeError` inside pvlib when the system is
        simulated. Nor are keys this chain's models never read, such as SAPM's `A0`
        to `A4`, `B0` to `B5`, `A`, `B` and `DTC`, or a CECMod row's `Technology`
        text. pvlib's CECMod and SandiaMod rows give every checked key they hold as a
        finite number;
    - a set coefficient that custom parameters cannot take, through
      `_require_template_takes_temperature_coefficient`, which use runs too: parameters
      in neither form, such as a row of pvlib's `SandiaMod` library, naming the keys of
      each form; or CEC single-diode parameters whose `alpha_sc` is 0, since `Adjust`
      scales only `alpha_sc` and so cannot move the coefficient, or on which the
      coefficient is beyond the reach of the bracket's ends, a NaN reach included (a
      negative `R_sh_ref` gives one), naming the bracket and the reach
      (`_require_adjust_reaches`). Construction
      evaluates only the bracket's two ends, not the solve;
    - then custom parameters with no rating (neither `pdc0` and `gamma_pdc` nor `STC`),
      or whose rating is not a finite number above 0, text that reads as one included,
      naming its key and value (`_module_rating_w`), or outside NOCT-SAM's domain once
      a set efficiency's area is applied (`_template_with_set_efficiency`), through
      `_require_cells_noct_sam_can_heat`, which use runs too
      ([pv-cell-temperature.md](pv-cell-temperature.md)).
  - At use (`create_pv_system`, and so every chain builder and `wired_dc_capacity_kw`):
    the same module-value rule (`_require_module_values`) first, on the custom
    parameters (`_module_parameters`), then the same form, reach, rating and NOCT-SAM
    rules, through the same functions, on the module it wires, `DEFAULT_CEC_MODULE`'s
    row included, which construction does not check. Unlike those rules, the
    module-value rule does not run on that row. The
    efficiency's use-time check is NOCT-SAM's own (`_require_cells_noct_sam_can_heat`).
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
- **Why construction checks the reach, not the solve.** Whether the modelled
  coefficients at the bracket's two ends straddle the set one, which a NaN end never
  does, is the refusal's whole condition: `brentq` always succeeds once they do, so a
  solve at construction would refuse nothing more. The check costs 2 of the solve's ~19
  single-diode evaluations (§3). `DEFAULT_CEC_MODULE`'s row reaches the whole domain
  (§3), so construction skips it: only custom parameters, which no YAML key sets, pay
  for the check.
- **Why these keys** (task 1440). The module-value rule reads every module key the
  chain reads into the power or voltage an inverter reads, since a NaN in any of them
  simulates to 0 kWh with no error and text raises a bare `TypeError` inside pvlib
  (§3). One rule over every such key leaves no list of keys still to check. SAPM's
  `IXO`, `IXXO` and `C4` to `C7` stay out: pvlib marks them not required and reads them
  only into `i_x` and `i_xx`, which no inverter model reads, and 10 SandiaMod rows give
  them NaN yet simulate (§3), so a finite-number check would refuse valid library
  modules. `cap_adjustment` is a flag, not a number: `pvwatts_dc` reads it as
  `if cap_adjustment:`, so the text "False" turns the cap on (§3), while
  `as_finite_real` would refuse a valid `True`; `boolean_fields.as_boolean` reads it,
  as it reads the package's other boolean settings. A key given as `None` is refused,
  not taken as absent: `custom_module_params` is a `dict[str, float]`, and leaving a
  key out is how a module takes pvlib's default, so taking `None` as absent for the
  keys whose pvlib default is `None` (`k`, `n_ar`) would be a per-key special case
  that accepts a value the type refuses. The type does not admit the rule's flag
  either: the stored-run reader, `web/field_tree.py`'s `read_field_tree`, reads
  `custom_module_params` by that annotation, so it refuses a run whose module gives
  `cap_adjustment` true or false (`FieldTreeRefused` "is true, not a number a float can
  hold"; measured on 2026-11-20 at fbdaccd1). No web path sets `custom_module_params`,
  so no stored run carries such a module; a typed module specification (§4) would let
  the type and the rule agree.
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
this branch at 695d386 and reproduce exactly.

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
- **The reach check's cost**, measured on 2026-11-07 by task 1372's architect on
  3d92c71 (`pv.py` unchanged at 5f39756) with pvlib 0.15.1, on a host at a load average
  of ~130 on 32 cores, so the ratios carry rather than the times: one `_modelled_gamma`
  takes 5.9 ms at best; the reach check, two of them, 12.5 ms; the full solve 119 ms,
  `brentq` taking 17 calls in 16 iterations for −0.004 per K; a `PVConfig` without the
  check 0.02 ms. Re-measured the same day by its implementer on task 1372's branch at
  dafc05d, its GREEN commit, at a load average of ~95: a `PVConfig` of the default row
  as custom parameters took 12.3 ms with −0.004 per K and 0.019 ms without it.
- **What the module-value rule's keys do unchecked**, measured on 2026-11-20 with pvlib
  0.15.1 by task 1440's implementer on its branch at fbdaccd1, whose `pv.py` is that of
  f0c89546, the branch's GREEN commit for `cap_adjustment`; 4 kW at Bristol over the
  synthetic clear June day. With `_require_module_values` patched out in a scratch
  script: a NaN `EgRef`, `temp_ref`, `FD` or `n` on the default row gives 0.0 kWh
  (26.8194 kWh as it is), a NaN `k` or `temp_ref` on a 300 W PVWatts module 0.0 kWh
  (25.7703), a NaN `C0` or `N` on SandiaMod's first row, rated at Impo × Vmpo with the
  simple inverter, 0.0 kWh (25.9264), and a NaN `gamma_ref` on the PVsyst module
  `tests/_pv_modules.py` builds 0.0 kWh (25.6956), none with an error; a PVWatts
  module with `k` 0.01 gives 25.5765 kWh with `cap_adjustment` False and 25.5581 with
  True or the text "False", and with `k` −0.05, 26.7387, 26.8307 and 26.8307. With the
  rule in place, that SAPM row with `A0` to `A4`, `B0` to `B5`, `A`, `B` and `DTC` as
  text still gives 25.9264 kWh, and with `C4` or `IXO` as text raises numpy's
  `UFuncTypeError`, a `TypeError`; 10 of SandiaMod's 523 rows give NaN in `IXO`,
  `IXXO` or `C4` to `C7`, and one, `Panasonic_VBHN235SA06B__2013_`, rated so, gives
  27.0011 kWh; the rule refuses none of CECMod's 21,535 rows nor SandiaMod's 523.

## 4. When to Revisit

- pvlib changes how `calcparams_cec` uses `Adjust`, or how `ModelChain` infers its DC
  model. A hand-built template that also carries the keys of a DC model pvlib ranks
  above its CEC or PVWatts form, such as SAPM's `A0`, `A1` and `C3`, runs that model,
  which would not read the coefficient. No such template is reachable from YAML, since
  the `pv:` block has no key for custom module parameters.
- pvlib adds or renames a module key one of the chain's models reads, or this code
  changes the chain's aoi, spectral or temperature model, which changes which keys are
  read (§1, the module-value rule). A parameter a pvlib release adds to
  `calcparams_cec`, `calcparams_desoto`, `calcparams_pvsyst`, `pvwatts_dc` or the
  physical IAM fails
  `tests/unit/test_pv.py::TestAModuleParameterAModelReadsIsAFiniteNumber::test_each_module_parameter_a_pvlib_reader_takes_by_name_is_refused_as_text`,
  which reads their signatures; nothing flags a key `sapm` or the effective irradiance
  starts reading.
- A typed module specification replaces the trio of `module_efficiency`,
  `temperature_coefficient` and `custom_module_params`.
- Module data from outside pvlib's CECMod library becomes a template, whose rows the
  bracket's coverage (§3) does not describe.
