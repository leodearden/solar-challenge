# PV model: one home for module choice, run policy and ageing

**Status:** authored 2026-10-15, not committed (program `review-all-solar_challenge-20261013`, stream S14, wave 1, no upstream streams; upstream task 284). Contract-first (B + H).

**Code anchors** verified against main `9d7b67e` (2026-10-15). Main moves fast: cite-by-symbol; re-locate lines at implementation time.

## Goal

`pv.py` answers each of these questions once, and every caller reads the answer instead of re-deriving it:

- which module a default simulation uses;
- how a model chain is run;
- what a module's rating and an array's wired DC are;
- how the module's efficiency and temperature coefficient shape its output.

What a user sees when this lands:

- `PVConfig(capacity_kw=4.0, temperature_coefficient=-0.005)` gives 2.1% less energy than the default on the tests' synthetic clear June day, and `-0.003` gives 0.7% more. `module_efficiency=0.10` gives 1.0% less. Today all three give exactly the default's energy (the review measured 497.7746611592203 kWh for a Bristol June). A fleet whose `module_efficiency` is a distribution now gives its homes different yields.
- Every run computes cell temperature with SAM's NOCT model, from the module's own catalogue NOCT and efficiency. The default 4 kW array's Bristol year moves from 993.1 to 1012.1 kWh per wired kWp (+1.9%). The PV, finance and benchmark docs carry dated amendments with the re-measured figures.
- A pvlib release whose CEC library drops the default module's row stops every simulation with an error naming `Canadian_Solar_Inc__CS1U_400MS` and the `CECMod` library. Today the model switches silently to another Canadian Solar 400 W row (`CS3W_400P`, 400.158 W).
- `PVConfig(4.0, custom_module_params={"pdc0": 300.0, "gamma_pdc": -0.004})` is wired as 13 modules (3.9 kWp), and validation judges it on 3.9 kWp. Today it is 10 modules of 300 W, 3.0 kWp modelled, judged as 4.0 kWp.
- `pv.run_model_chain` runs any chain under the project's one run policy. The two measurement scripts and the tests call it, so the four copies of its warning filter go. Today a chain run without a copied filter emits 39 `RuntimeWarning`s per simulated day.
- The self-consumption checks judge a run against one sourced band each, the band their docstrings state. They compare the run's own generation with its own demand instead of a nameplate × 900 kWh guess.
- `apply_degradation` leaves the public surface at the program's bump (S29). Ageing has one home: the model chain's DC losses step (task 284).

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says |
|---|---|---|
| fk-f5cd69400ce6 | high / confirmed | `PVConfig.module_efficiency` and `temperature_coefficient` have no effect on output. Both are public, parsed from YAML, sampled per home and written back. |
| fk-0edf0069c6bb | high / confirmed | `module_efficiency` is read nowhere. `temperature_coefficient` reaches the model only through the `!= -0.004` sentinel, and lands on `gamma_pdc`, which the CEC model never reads. Custom parameters drop both silently. |
| fk-48447960eb2c | medium / weakened | The default CEC module is found by substring search, with two fallbacks. Nothing names it, a comment names a row the catalogue lacks, and its numbers are restated in 7 places. Mechanical filing: task 756. |
| fk-8b8f9d686b86 | medium / confirmed | `wired_dc_capacity_kw` recomputes the module helpers instead of reading the built `PVSystem`. Validation's self-consumption notes use `capacity_kw * 900`. |
| fk-3ccbba41d836 | medium / confirmed (D26) | System losses are a chain step, but ageing and the clip happen after the chain, on AC. `create_model_chain` and `simulate_pv_output` disagree about what the PV model is. |
| fk-616cc076b7cb | low / confirmed | The run's warning policy lives only in `simulate_pv_output`. The scripts copy it three times, and a test file has a broader fourth copy. |
| fk-a98db49f3fd7 | low / confirmed | `_module_rating_w` defaults to 400 W when a module has no `STC`. A PVWatts dict is then miscounted against its `pdc0`. Mechanical filing: task 699. |
| fk-998f0cb69410 | low / confirmed | Ageing is applied to AC after clipping. Mechanical filing: task 284, whose branch is finished. |
| fk-835a87838a52 | low / confirmed | Validation states 25–35% and 60–80% but applies 20–45% and 50–90%, unsourced. The assistant and load restate benchmark facts that disagree with these. |

Rulings that bind this PRD (program doc §Resolved decisions):

- **D14.** Both fields become live model inputs. When set, they derive the module parameters STC-consistently, the CEC row being a template as the inverter already is. The `gamma_pdc` sentinel goes.
- **D26.** fk-3ccbba41d836 (where system losses and ageing sit in the chain) belongs to this stream.
- **D4 / D29.** There is one coordinated surface bump (S29). Additive frozen edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line. Renames and retirements are held leaves.
- **D28.** fk-48447960eb2c is re-measured before decomposing (below).

Session rulings (Leo, 2026-10-15, in this authoring session):

- **An unset field means the module's own value.** Both fields become `Optional[float] = None`. `None` takes the template's catalogue efficiency (STC / (A_c × 1000)) and its modelled temperature coefficient.
- **Module efficiency acts through cell temperature, and every run switches to NOCT-SAM.** The thermal model becomes pvlib's `noct_sam`, fed the module's own `T_NOCT` and efficiency, in place of the generic SAPM `open_rack_glass_glass` set. Leo chose this over scaling SAPM's heating, accepting that every default yield moves.

### Re-measurement at `9d7b67e` (D28, fk-48447960eb2c)

The weakened finding reproduces at HEAD. `pv.py` and `validation.py` are unchanged since the pin `7dfea36e`.

- The selector matches 2 of pvlib 0.15.1's 21,535 `CECMod` columns: `Canadian_Solar_Inc__CS1U_400MS` (STC 400.428 W) first, then `CS3W_400P` (400.158 W). No `CS6K` row exists.
- `_get_cec_module` has 2 fallbacks.
- The skeptic's count of 7 restatement sites holds:
  - the `wired_dc_capacity_kw` docstring;
  - `docs/pv-inverter-string-matching.md` (§2 "Module" and the per-wired-kWp line);
  - `docs/pv-annual-yield-benchmark.md` §1;
  - `tests/unit/test_validation.py` (three sites).

Also measured for this PRD (pvlib 0.15.1, the tests' `synthetic_june_weather("2024-06-21")`, and Bristol's cached TMY at 1069.46 kWh/m² GHI):

- **The template.** The row holds STC 400.428 W, A_c 1.99 m² (efficiency 0.2012), T_NOCT 45.1 °C, `gamma_r` −0.3448 %/K and `Adjust` 7.313. Its modelled γ at STC is −0.3473 %/K.
- **Adjust.** In `calcparams_cec`, `Adjust` scales only the short-circuit current's temperature term, so it leaves the STC point unchanged: P_mp stays 400.4281 W for `Adjust` from −500 to 2000. The modelled γ is linear in it, from −0.035 to −1.57 %/K over that range. Solving `Adjust` for the template's own γ returns 7.312982 and reproduces the day's energy to 1e-11.
- **Catalogue span.** `gamma_r` spans −0.679 to −0.166 %/K over all 21,535 rows. STC / (A_c × 1000) spans 0.036 to 0.227.
- **The warning policy is live.** `create_model_chain(PVConfig.default_4kw(), bristol).run_model(day)` emits 39 `RuntimeWarning: invalid value encountered in divide` from `scipy/optimize/_chandrupatla.py`.
- **SAPM → NOCT-SAM, default module.**

  | | clear day | Bristol year |
  |---|---|---|
  | 4 kW | ×1.0310 | ×1.0191 (3976.80 → 4052.83 kWh; 993.14 → 1012.12 kWh/kWp) |
  | 6 kW on 3.68 kW | ×1.0052 | ×1.0109 |
  | 3 kW | ×1.0309 | ×1.0191 |

  Bristol's performance ratio moves from 0.8034 to ≈0.819. The slow guard's band is 0.76–0.84.
- **Live fields under NOCT-SAM** (4 kW, against the NOCT default):

  | setting | clear day | Bristol year |
  |---|---|---|
  | γ −0.003 | ×1.0066 | ×0.9983 |
  | γ −0.004 | ×0.9926 | ×1.0019 |
  | γ −0.005 | ×0.9786 | ×1.0055 |
  | η 0.10 | ×0.9901 | ×0.9951 |
  | η 0.15 | ×0.9950 | ×0.9975 |
  | η 0.22 | ×1.0018 | ×1.0009 |

  A steeper γ costs energy on a hot day but gains it over a Bristol year, because cells spend most of the year below 25 °C. Signals about γ therefore assert the clear day only.
- **PVWatts dict.** `{"pdc0": 300, "gamma_pdc": -0.004}` at 4 kW wires 10 modules today, and `wired_dc_capacity_kw` returns 4.0. Its clear-day peak is 2.66 kW, from 3.0 kWp of modules.

### In-flight tasks on these keys

- **284** (fk-998f0cb69410): pending, with a finished branch `task/284`. It moves ageing into the DC losses step (`_dc_kept_fraction`, `_deduct_dc_losses`) and drops the AC derate. It merges cleanly at `9d7b67e`. This PRD builds on it.
- **756** (fk-48447960eb2c), **699** (fk-a98db49f3fd7) and **609** (whether `apply_degradation` leaves the surface): pending. At decompose, each is cancelled as superseded by the leaf here that does its work.
- **195**: pending, with a finished branch `task/195` that **retires** `module_efficiency` and `temperature_coefficient` from `PVConfig`, its parsers and `FROZEN_SURFACE`. That is the option D14 rejected. Only a stale L2 escalation holds it back: esc-195-3, with members esc-195-2 and esc-224-2. Every dry-run proposal on it recommends resolving that record as moot, which would merge 195. See Pre-conditions and open question 1.

## Sketch of approach

**The module is a template plus the config's settings.** `pv.DEFAULT_CEC_MODULE` names the catalogue row, and the row guard that inverters already have also guards it. The module a system simulates is that row, or `custom_module_params`, with each set field applied in the template's own terms:

- A temperature coefficient re-solves the CEC `Adjust` parameter, or sets PVWatts' `gamma_pdc`.
- An efficiency re-derives the area A_c.

`PVConfig.__post_init__` refuses a set temperature coefficient that the chosen module's form cannot take, and values outside each field's physical domain (heuristic 10).

**The thermal model reads the module.** Every array's cell temperature is pvlib's `noct_sam`, fed the module's `T_NOCT` and its efficiency (rating / (A_c × 1000)). An efficiency setting therefore changes output through the one channel physics gives it at a fixed rating: how hot the cell runs.

**One rating and one wired DC.** `_module_rating_w` reads `pdc0` for a PVWatts module and `STC` otherwise, and refuses a module with neither. The module count, the DC model and `wired_dc_capacity_kw` all read that number. The wired DC is summed over the arrays of the `PVSystem` that `create_pv_system` builds, so two builders can no longer drift.

**One way to run a chain.** `run_model_chain(model_chain, weather_data)` applies the warning policy and returns the run chain. After task 284, every chain ages and loses its DC before the inverter. `simulate_pv_output` becomes build, run, W→kW and clip. The scripts and tests run chains through it. `apply_degradation`, the second and wrong way to age, leaves the surface at the bump.

**Validation states what it applies.**

- The self-consumption notes compare the run's own generation with its own demand.
- Each band is a public, sourced constant that the docstring, the message and S22's assistant all read.

Heuristics served:

- 11, SPOT: one module identity, one rating, one wired DC, one run policy, one ageing function, one band per check.
- 10: refusals at construction and at use, naming field and value.
- 1: fields that do what their names say.
- 3: module, thermal model, run policy and validation are each one mechanism.
- 9: a narrow `run_model_chain` over a deep chain builder.
- 12: catalogue identity as a named constant, not a substring.

## Resolved design decisions

1. **Default module identity.** `DEFAULT_CEC_MODULE = "Canadian_Solar_Inc__CS1U_400MS"` is public in `pv.py`, so docs and tests can name it.
   - `_require_cec_library_row` takes the library (`"CECMod"` or `"CECInverter"`) and the name, and refuses with both named.
   - `_get_cec_module` becomes `_cec_library_module(name)`. The substring search, both fallbacks and the CS6K comment go.
   - The 7 restatement sites name the constant: tests read the row's numbers from the library by the constant, and docs name the row beside their dated figures.
   - The constant stays out of `solar_challenge.__all__`, because no package-level consumer is named.
2. **Unset means the module's own (session ruling).**
   - `module_efficiency: float | None = None` and `temperature_coefficient: float | None = None`. `None` changes nothing in the template.
   - This mirrors `inverter_capacity_kw: float | None = None` ("defaults to DC capacity").
   - A stored run or YAML carrying the old inert `0.2` / `-0.004` now sets them. ζ's release note says so.
3. **The temperature coefficient derives the module's parameters.**
   - **CEC single-diode form** (`alpha_sc`, `a_ref`, `I_L_ref`, `I_o_ref`, `R_sh_ref`, `R_s` and `Adjust` present): `Adjust` is solved so the modelled dP_mp/dT / P_mp at 25 °C and 1000 W/m² equals the set γ, and `gamma_r` is set to 100γ.
     - The STC point is unchanged by construction (measured above), which is D14's "STC-consistently".
     - This is the parameter SAM's CEC fit uses to match γ. No refit library is needed: `fit_cec_sam` requires NREL-PySAM, which is not installed.
   - **PVWatts form** (`pdc0`, `gamma_pdc`): `gamma_pdc` is set to γ.
   - **Any other form** is refused at construction, naming `temperature_coefficient` and the keys each form needs.
   - **Domain:** −0.01 ≤ γ < 0 per K. That is −1 %/K, beyond every catalogue row's −0.68 %/K. It keeps the CEC derivation's photocurrent positive over the operating range: at `Adjust` 1500, P_mp(90 °C) = 125 W. The old (−1, 0) admitted values no model can honour.
   - If no `Adjust` in the solver's bracket reaches γ for a custom CEC template, the solver refuses at use, naming the field.
4. **The module efficiency derives A_c,** as A_c = rating / (η × 1000) in either form.
   - Its effect on output is the thermal model's (decision 5).
   - **Domain:** 0 < η < 0.9. At NOCT-SAM's transmittance–absorptance (0.9) and above, a cell would not heat. The old upper bound of 1 admitted that.
5. **NOCT-SAM for every run (session ruling).**
   - Each array's `temperature_model_parameters` are `{"noct": T_NOCT, "module_efficiency": rating / (A_c × 1000)}`, from which pvlib infers `noct_sam` (verified).
   - Installation takes pvlib's defaults: `array_height=1`, and `mount_standoff=4` inches, which applies no NOCT adjustment. That is the same open-rack assumption the replaced `open_rack_glass_glass` set made. A mounting field is out of scope (open question 5).
   - A custom module without `T_NOCT` or `A_c` takes the default module's value. `PVConfig.custom_module_params`' docstring states this rule.
   - `create_simple_module_params` writes `A_c` from its `efficiency` argument, so that argument becomes live. It stops writing the unread `"efficiency"` key; the helper is not frozen.
   - The re-baseline is one leaf (ε). The docs get dated amendments, never re-anchored snapshots. A new `docs/pv-cell-temperature.md` records the decision, its source (SAM Photovoltaic Model Technical Reference, §10.6, which pvlib's `noct_sam` cites) and the measurements.
6. **One rating.** `_module_rating_w(params)` is `pdc0` for a PVWatts module and `STC` otherwise, and raises `ValueError` naming both keys when the module has neither. The 400 W default goes. The module count uses it, so the count, the DC model's own scale and the wired DC agree.
7. **Wired DC from the built system.** `wired_dc_capacity_kw(config)` sums, over the arrays of `create_pv_system(config)`, modules per string × strings × `_module_rating_w(array.module_parameters)`. The recomputation through `_module_parameters` and `_module_count` goes. The function's frozen absence from `__all__` and its signature are unchanged.
8. **One run policy.** `run_model_chain(model_chain, weather_data) -> ModelChain` runs the chain inside the one `_chandrupatla` filter and returns it.
   - Build and run stay separate because `scripts/measure_mppt_window.py`'s `census` reads a chain's pick before deciding whether to run it.
   - It is module-public, not in `__all__` (open question 4).
   - `simulate_pv_output` is `run_model_chain(create_model_chain(...), weather).results.ac / 1000`, clipped at 0.
   - The scripts' three copies and the tests' `_QUIET_DIODE_SOLVER` and three marks go.
   - `measure_pv_performance_ratio.measure` reads each configuration's in-plane irradiation and AC from one run, so the script stops mixing the two entry points.
9. **Ageing has one home** (D26, fk-3ccbba41d836).
   - Task 284 puts it in the DC losses step as `(1 - system_losses) × calculate_degradation_factor(...)`.
   - `calculate_degradation_factor` is the one ageing function. The chain and finance's `pv_soh` both read it, and finance needs no change.
   - `apply_degradation` retires at S29 as held leaf η, which supersedes 609. It is a frozen name, and after 284 it has no src caller. Applied to `simulate_pv_output`'s output, it ages the array twice.
10. **Validation states what it applies** (fk-835a87838a52; fk-8b8f9d686b86's validation half).
    - The self-consumption notes compare the run's generation total with its demand total. That ratio is exactly what "PV large/small relative to consumption" means, so neither a capacity nor a yield guess is needed, and the 900 and the nameplate-versus-wired question both go. This deliberately departs from the stream row's "reads wired capacity".
    - `validate_self_consumption_pv_only` and `validate_self_consumption_with_battery` drop their `capacity_kw` parameter (not frozen). `validate_simulation` stops passing it.
    - Each band becomes a public constant: `UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT`, `UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT`, and `UK_YIELD_BENCHMARK_KWH_PER_KWP` (renamed from private).
    - Each self-consumption band is sourced from published UK references in a new `docs/self-consumption-benchmark.md`, scoped as `docs/pv-annual-yield-benchmark.md` is, never fitted to model output. The docstring, the message and S22's assistant read the constant.
    - `load.OFGEM_TDCV_BY_OCCUPANTS`'s comment is corrected to say it is the project's own interpolation by occupants, not Ofgem's low, medium and high values. The name is frozen and stays.
11. **Surface posture (D4/D29).**
    - **In-leaf** (ζ), with its `FROZEN_SURFACE` form edit and an Unreleased line: the `PVConfig` form change (two fields widen to `float | None = None`) and the tightened domains. This is my reading of D29: the change is neither a rename nor a retirement, and every existing constructor call stays valid (open question 2).
    - **In-leaf:** ε's NOCT re-baseline and γ's PVWatts count change get Unreleased lines.
    - **Held for S29:** only `apply_degradation`'s retirement.
12. **Error type.** New refusals raise `ValueError`, like `PVConfig`'s existing ones. S4 converts every `PVConfig` refusal to the shared checker's `ConfigurationError` (D9, L1). Open question 3 asks whether L5 should apply instead.
13. **Superseded and conflicting tasks.**
    - At decompose, after contract §8 step 1: 756 is superseded by α, 699 by γ, and 609 by η.
    - 195 contradicts D14 and must be cancelled before anyone resolves esc-195-3 (open question 1).
    - Task 224 (release) depends on 195, so the lead re-wires it.

## Contract (seams owned: default module identity; `PVConfig` fields on the frozen surface; validation's benchmark constants; readers home, validation, config, scenario_writer, scripts, finance via `calculate_degradation_factor`; downstream S22, S7, S4, S29)

```python
# src/solar_challenge/pv.py
DEFAULT_CEC_MODULE: str = "Canadian_Solar_Inc__CS1U_400MS"
"""The CECMod row a PVConfig without custom_module_params is modelled from: the template its set fields derive from."""

@dataclass(frozen=True)
class PVConfig:
    ...                                              # other fields unchanged
    module_efficiency: float | None = None           # None: the module's own, STC / (A_c × 1000); else 0 < η < 0.9
    temperature_coefficient: float | None = None     # None: the module's own modelled γ; else -0.01 <= γ < 0, per K
    custom_module_params: dict[str, float] | None = None
    # __post_init__ raises ValueError naming the field and value outside its domain, and naming
    # temperature_coefficient when custom_module_params are neither CEC single-diode nor PVWatts form.

def _require_cec_library_row(library: str, name: str) -> None: ...   # ValueError naming library and name
def _cec_library_module(name: str) -> dict[str, float]: ...          # the required CECMod row
def _module_rating_w(module_params: Mapping[str, float]) -> float: ...
    # pdc0 for PVWatts form, else STC; ValueError naming both keys when neither
def _module_parameters(config: PVConfig) -> dict[str, float]: ...
    # template = custom_module_params or _cec_library_module(DEFAULT_CEC_MODULE), with set fields applied:
    #   CEC form: Adjust solved so modelled dPmp/dT / Pmp at 25 °C, 1000 W/m² == temperature_coefficient; gamma_r = 100 × it
    #   PVWatts form: gamma_pdc = temperature_coefficient
    #   either form: A_c = _module_rating_w(template) / (module_efficiency × 1000)
    #   unset fields leave the template untouched (bit-identical)
def _temperature_model_parameters(module_params: Mapping[str, float]) -> dict[str, float]: ...
    # {"noct": T_NOCT, "module_efficiency": rating / (A_c × 1000)}; a missing T_NOCT or A_c takes DEFAULT_CEC_MODULE's
def wired_dc_capacity_kw(config: PVConfig) -> float: ...
    # Σ over create_pv_system(config).arrays: modules_per_string × strings × _module_rating_w(module_parameters) / 1000
def run_model_chain(model_chain: ModelChain, weather_data: pd.DataFrame) -> ModelChain: ...
    # runs model_chain over weather_data under the one warning policy; returns it run.
    # Every chain create_model_chain(_picking_from) builds already applies system losses and ageing on DC (task 284).
def simulate_pv_output(config, location, weather_data) -> pd.Series: ...   # frozen signature unchanged
    # run_model_chain(create_model_chain(config, location), weather_data).results.ac / 1000, clipped at 0

# src/solar_challenge/validation.py
UK_YIELD_BENCHMARK_KWH_PER_KWP: tuple[float, float] = (300.0, 1200.0)   # renamed from _UK_…
UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT: tuple[float, float]       # sourced: docs/self-consumption-benchmark.md
UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT: tuple[float, float]       # sourced: docs/self-consumption-benchmark.md
def validate_self_consumption_pv_only(results, annual_consumption_kwh) -> ValidationResult: ...
def validate_self_consumption_with_battery(results, battery_kwh, annual_consumption_kwh) -> ValidationResult: ...
    # PASS iff the ratio lies inside the constant; the message and docstring state the constant;
    # the size notes read results.generation.sum() / results.demand.sum()
```

Invariants and where each is enforced:

| invariant | construction | use |
|---|---|---|
| The default module is one named catalogue row. | `DEFAULT_CEC_MODULE` | `_require_cec_library_row("CECMod", …)` on every resolve |
| A set field changes the module in its own terms; an unset one changes nothing. | `PVConfig.__post_init__` (domains, form applicability) | `_module_parameters` (solver refusal for an unreachable γ) |
| The STC point survives a set temperature coefficient. | the CEC model: `Adjust` scales only the temperature term | B6's STC check |
| A cell's temperature follows its own module's NOCT and efficiency. | `_temperature_model_parameters` | pvlib infers `noct_sam` from the keys |
| The count, the DC model and the wired DC read one rating. | `_module_rating_w` | `wired_dc_capacity_kw` sums the built system |
| A chain is run one way. | — | `run_model_chain`, the only `.run_model(` in src and scripts |
| Ageing is applied once, on DC, by `calculate_degradation_factor`. | task 284's losses step | `apply_degradation` gone at the bump |
| A benchmark check applies the band it states. | the public constant | the docstring, the message and S22 read it |

Downstream readers and their seam lines:

- **S22** reads the three `validation.UK_*` constants (δ) and the post-ε Bristol yield figure (`docs/pv-cell-temperature.md`). It does not restate them.
- **S7** derives PV distribution defaults from `PVConfig`'s. With `None` for both fields, no `0.20` or `-0.004` literal returns.
- **S4**: invariant 1's fixture treats the two fields as Optional (`None` valid; NaN, inf and bool refused). S4 converts ζ's new refusals with `PVConfig`'s others.
- **S29** folds ε's and ζ's Unreleased lines and releases η.

## Boundary-test sketch (both sides of the seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Module identity | `PVConfig.default_4kw()`; a subprocess whose `pvlib.pvsystem.retrieve_sam("CECMod")` lacks the `DEFAULT_CEC_MODULE` column | the default system's module parameters equal the library's `DEFAULT_CEC_MODULE` column, key for key; in the subprocess, `simulate_pv_output` raises naming `Canadian_Solar_Inc__CS1U_400MS` and `CECMod` (today it simulates `CS3W_400P`) | α |
| B2 | One run policy | the default chain; `synthetic_june_weather("2024-06-21")`; `warnings.simplefilter("error")` | `run_model_chain` returns a run chain with no warning raised; the same chain's bare `run_model` raises `RuntimeWarning` from `scipy.optimize._chandrupatla`; `simulate_pv_output` equals the run chain's `results.ac / 1000` clipped at 0; `measure_mppt_window.measure_year` runs warning-free without `main` having run | β |
| B3 | One rating and one wired DC | 4 kW of `{"pdc0": 300, "gamma_pdc": -0.004}`; a module dict with neither `pdc0` nor `STC`; 0.3 kW and 4 kW of the default module | 13 modules and `wired_dc_capacity_kw` 3.9 (today 10 modules and 4.0); the module-less dict raises naming `pdc0` and `STC`; the default sizes return 0.400428 and 4.00428, unchanged; `validate_pv_generation`'s peak message names 3.90 kWp | γ |
| B4 | Validation states what it applies | `SimulationResults` from the existing `_create_simulation_results` builder at ratios on each band's edges ± 0.1 pp; results whose generation total is twice their demand total | PASS exactly inside each constant; the message range and the docstring both equal the constant; the "PV large relative to consumption" note follows the run's own totals whatever the capacity (today `capacity_kw * 900 / annual`) | δ |
| B5 | NOCT-SAM from the module | the default chain; 4 kW of `create_simple_module_params(efficiency=0.10)` and of `efficiency=0.22`; the clear day | the chain's temperature model is `noct_sam`; each array's cell temperature equals `pvlib.temperature.noct_sam(..., noct=45.1, module_efficiency=400.428/1990)`; the default's clear-day energy is ×1.031 today's; the 0.10 module yields less than the 0.22 one (today equal) | ε |
| B6 | Live fields | `PVConfig(4.0, temperature_coefficient=t)` for t in {−0.003, −0.005}; `module_efficiency=0.10`; a fleet `module_efficiency` distribution over {0.15, 0.22}; YAML with and without the keys; a SAPM-form custom dict with t set; t = −0.02; η = 0.95 | the derived module's modelled γ equals t within 1e-6/K and its P_mp at STC equals the row's within 1e-9 relative; clear-day energy: −0.005 at least 1.5% below the default and −0.003 above it, and η 0.10 at least 0.5% below (today all equal); the fleet's two efficiencies give different home generation; YAML round-trips through `scenario_writer` (an absent key stays absent); the last three are refused naming the field | ζ |
| B7 | Ageing has one home | after task 284 and η | `apply_degradation` is absent from `solar_challenge.__all__` and `FROZEN_SURFACE`; an aged `PVConfig`'s `simulate_pv_output` equals its run chain's AC | η (held), with task 284 |

## Pre-conditions for activating

- **Task 284 lands before β and η.** It is pending, its branch `task/284` is finished, and it merges cleanly at `9d7b67e`. If it stalls, the lead may fold it into β.
- **Task 195 is cancelled before ζ, and its escalations esc-195-2, esc-195-3 and esc-224-2 are dismissed as superseded.** Otherwise resolving esc-195-3 as moot merges a branch that deletes the fields ζ makes live. Task 224's dependency on 195 is re-wired by the lead.
- **G3 substrate, verified at `9d7b67e`:**
  - pvlib 0.15.1's `ModelChain.infer_temperature_model` returns `noct_sam_temp` when `{"noct", "module_efficiency"} <= temperature_model_parameters`, and `Array.get_cell_temperature` reads both from there (probe printed `noct_sam_temp`).
  - `calcparams_cec`'s `Adjust` multiplies only `alpha_sc`'s temperature term (STC P_mp is constant across `Adjust`, probed).
  - The `CECMod` row carries `T_NOCT`, `A_c`, `gamma_r` and `Adjust`.
  - `_require_cec_library_row` exists, for inverters.
  - `wired_dc_capacity_kw`, `create_simple_module_params` and the validation functions are not on `FROZEN_SURFACE`. `PVConfig`'s form, `simulate_pv_output`, `create_model_chain`, `create_pv_system`, `apply_degradation` and `calculate_degradation_factor` are.
  - `docs/domain-library-consumption.md` carries "Unreleased on main" paragraphs.
  - `review/briefing.yaml` has `decisions` and `conventions`.
  - Bristol's TMY is in the main checkout's `.cache/weather`, so ε re-measures offline with `--cache-dir` pointed there.
  - The slow guard `tests/integration/test_pv_performance_ratio.py` holds 0.76–0.84.

## Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S22 Assistant facts | produces for | `validation.UK_*` benchmark constants (δ); the Bristol yield figure in `docs/pv-cell-temperature.md` (ε) | S14 (constants, figure), S22 (assistant reads) | proposed: S22's facts leaf depends on δ and ε |
| S7 Component defaults | produces for | `PVConfig` field defaults (`None` for the two fields, ζ); distributions derive from `PVConfig` | S14 (fields), S7 (derivation) | parallel; file overlap `config.py` |
| S4 Finite quantities | consumes | invariant 1's fixture walks `PVConfig`, whose two fields become Optional; S4 converts ζ's new refusals | S4 | parallel; file overlap `pv.py` `PVConfig.__post_init__` |
| S1 Errors leaf | consumes (base type) | ζ's refusals are `ValueError`, `ConfigurationError`'s base (D2) | S1 | no dependency unless L5 is applied (open question 3) |
| S5 Scenario grammar | shares | `_parse_pv_config`, `PVDistributionConfig` and `generate_homes_from_distribution` move to scenario_blocks/fleet_distribution; ζ edits them for `None`; S5 deletes `_modify_pv_config` | S5 (layout), S14 (`None` plumbing) | whichever lands second rebases |
| S10 Window | shares | δ renames `_UK_YIELD_BENCHMARK_KWH_PER_KWP` to public; S10 δ edits `_check_annual_yield` | S14 (name), S10 (rule) | file overlap `validation.py`; the later leaf follows the name |
| S15 Weather | shares | both edit `scripts/measure_pv_performance_ratio.py` and `measure_mppt_window.py` (β: `run_model_chain`; S15: `set_weather_cache`) | each its own | file overlap only |
| S12 Load composition | shares | `pv.interpolate_to_minute_resolution` (S12); δ's comment on `load.OFGEM_TDCV_BY_OCCUPANTS` | each its own | file overlap only |
| S23 Surface lock | shares | ζ's `PVConfig` form edit and η's removal edit `FROZEN_SURFACE` wherever S23 has moved it | S23 (home), S14 (entries) | file overlap |
| S29 Surface bump | consumes | held leaf η; folds ε's and ζ's Unreleased lines | S29 releases η | η filed with `x_seam_wait` |
| S8 Finance partition | no seam | finance's `pv_soh` reads `calculate_degradation_factor` (unchanged); ε moves every board figure (+1.9% generation in Bristol) | — | release note in ε |
| task 284 | consumes | DC ageing in the losses step | 284 | upstream of β, η |
| tasks 756, 699, 609 | supersedes | their keys' work | α, γ, η | cancel at decompose with `x_superseded_by` |
| task 195 | conflicts | retires the two fields | S14 ζ (D14) | cancel now (open question 1) |

## Decomposition plan

Labels are the sidecar's. Every leaf carries:

- `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`;
- the `x_finding_key` list given below;
- priority = the highest severity among its keys.

ε and ζ are high, so both join the trigger-chain gate once it exists.

- **α. Name the default module and require its row** (supersedes 756).
  - **Files:** `pv.py`, `tests/unit/test_pv.py`, `tests/unit/test_validation.py`, `docs/pv-inverter-string-matching.md`, `docs/pv-annual-yield-benchmark.md`.
  - **Changes:**
    - Adds `DEFAULT_CEC_MODULE`, the two-argument `_require_cec_library_row` and `_cec_library_module`.
    - Deletes the substring search, both fallbacks and the CS6K comment.
    - `wired_dc_capacity_kw`'s docstring names the constant.
    - `test_validation`'s three 400.428 sites read the row's STC from the library by the constant.
    - The two docs name the row beside their dated figures.
  - **Signal:** B1. A library without the row stops the simulation, naming it; today `CS3W_400P` is simulated silently.
  - **Prereqs:** none. **Unlocks:** γ.
  - **Key:** fk-48447960eb2c (re-measured above). **Priority:** medium.
- **β. One run policy: `run_model_chain`.**
  - **Files:** `pv.py`, `scripts/measure_pv_performance_ratio.py`, `scripts/measure_mppt_window.py`, `tests/unit/test_pv.py`, `tests/unit/test_measurement_scripts.py`.
  - **Changes:**
    - Adds `run_model_chain`.
    - `simulate_pv_output` becomes build, run, W→kW and clip.
    - The scripts' `in_plane_irradiation`, `measure_year`, `operating_voltage` and `main`'s process-wide filter go through it.
    - `measure` reads POA and AC from one run per configuration.
    - `_QUIET_DIODE_SOLVER` and `test_pv`'s three `filterwarnings` marks go.
  - **Signal:** B2. The default chain run through `run_model_chain` under `simplefilter("error")` completes; the bare run raises; `measure_year` no longer depends on `main` having run.
  - **Prereq:** task 284. **Unlocks:** η.
  - **Keys:** fk-616cc076b7cb, fk-3ccbba41d836. **Priority:** medium.
- **γ. One rating; wired DC from the built system** (supersedes 699).
  - **Files:** `pv.py`, `tests/unit/test_pv.py`, `tests/unit/test_validation.py`, `docs/pv-annual-yield-benchmark.md` (§1 states the rule), `docs/domain-library-consumption.md` (Unreleased line: a PVWatts module without `STC` is now counted by its `pdc0`).
  - **Changes:**
    - `_module_rating_w` reads `pdc0`, else `STC`, else refuses; the 400 W default goes.
    - `wired_dc_capacity_kw` sums `create_pv_system(config)`'s arrays.
  - **Signal:** B3. The 300 W PVWatts dict at 4 kW wires 13 modules and validation's peak message names 3.90 kWp (today 10 modules, 4.00 kWp, 3.0 kWp modelled); a dict with neither key is refused naming both.
  - **Prereq:** α. **Unlocks:** ε.
  - **Keys:** fk-a98db49f3fd7, fk-8b8f9d686b86. **Priority:** medium.
- **δ. Validation states what it applies.**
  - **Files:** `validation.py`, `load.py` (the `OFGEM_TDCV_BY_OCCUPANTS` comment only), new `docs/self-consumption-benchmark.md`, `docs/pv-annual-yield-benchmark.md` (the constant's new name), `tests/unit/test_validation.py`.
  - **Changes:**
    - Adds the three public constants. Each self-consumption band is sourced from published UK references and scoped to the archetype its docstring names (4 kW, 3,400 kWh/yr; 5 kWh battery); fitting to model output is forbidden.
    - Docstrings and messages read the constants.
    - The notes read the run's generation/demand ratio.
    - `capacity_kw` leaves both functions; `validate_simulation` updates.
    - The TDCV comment says the table is the project's interpolation by occupants.
  - **Signal:** B4. PASS flips exactly at each constant's edges; the stated and applied ranges are the same numbers; the size note follows the run's own totals (today a 1 kW and a 6 kW nameplate give different notes on the same results). The `docs/self-consumption-benchmark.md` citation per band is checked by review.
  - **Prereqs:** none. **Unlocks:** S22's facts leaf (proposed).
  - **Keys:** fk-835a87838a52, fk-8b8f9d686b86. **Priority:** medium.
- **ε. Cell temperature from the module: NOCT-SAM for every run (session ruling; re-baseline).**
  - **Files:** `pv.py` (`_temperature_model_parameters`, `_arrays`, `create_simple_module_params` writes `A_c`), `tests/unit/test_pv.py`, `tests/unit/test_measurement_scripts.py` and any test pinning an SAPM-era yield, new `docs/pv-cell-temperature.md`, and `docs/domain-library-consumption.md` (Unreleased: every PV figure moves; Bristol default +1.9%; consumers re-baseline bills and the cost-recovery rate).
  - **Dated amendments, re-measured offline from the main checkout's `.cache/weather`** with `measure_pv_performance_ratio.measure` for Bristol and a re-run of `scripts/measure_mppt_window.py`. A figure not re-measured is marked as predating the change:
    - `docs/pv-system-losses.md` (§4, §5);
    - `docs/pv-annual-yield-benchmark.md` (§1, §3);
    - `docs/pv-inverter-string-matching.md` (§4–§7);
    - `docs/pv-inverter-efficiency.md`;
    - `docs/tmy-irradiation-scaling.md`;
    - `docs/finance-spreadsheet-reconciliation.md` §4.2.
  - **Also:** `review/briefing.yaml` (a decision line for the thermal model; the 203- and 284-era numeric lines re-measured or qualified as SAPM-era) and `CLAUDE.md`'s `pv.py` line.
  - **Signal:** B5. The default chain's temperature model is `noct_sam` with the row's NOCT and efficiency; the clear-day default energy is ×1.031 today's; `create_simple_module_params(efficiency=0.10)` yields less than `efficiency=0.22` (today equal); `docs/pv-cell-temperature.md` records Bristol's 4 kW at 1012.1 kWh/kWp and a performance ratio near 0.819, inside the slow guard's 0.76–0.84.
  - **Prereq:** γ (the efficiency reads `_module_rating_w`). **Unlocks:** ζ.
  - **Keys:** fk-f5cd69400ce6, fk-0edf0069c6bb. **Priority:** high.
- **ζ. `module_efficiency` and `temperature_coefficient` become live (D14).**
  - **Files:** `pv.py` (`PVConfig` fields, `__post_init__` domains and form applicability, `_module_parameters`' derivation, the sentinel deleted), `config.py`, `scenario_writer.py`, `tests/unit/test_pv.py`, `tests/unit/config/test_fleet_distribution_block.py`, `tests/unit/config/test_home_block.py`, `tests/unit/config/test_unrecognised_keys.py`, `tests/unit/test_scenario_writer.py`, `tests/unit/test_web_storage_roundtrip.py`, `tests/unit/test_public_api_surface.py` (`PVConfig` form), `docs/domain-library-consumption.md` (Unreleased: the fields widen to Optional, become live, and their domains tighten; a stored run or YAML carrying the old `0.2`/`-0.004` now sets them).
  - **`config.py` changes:**
    - `PVDistributionConfig.module_efficiency` defaults to `None`.
    - `generate_homes_from_distribution` passes the sample or `None` (the `else 0.20` goes).
    - `_parse_pv_config` passes `null`/absent through.
  - **`scenario_writer.py`:** writes a key only when it is set.
  - **Signal:** B6.
    - Clear-day energy: −0.005 is at least 1.5% below the default (measured 2.14%) and −0.003 is above it (+0.66%); η 0.10 is at least 0.5% below (0.99%). Today all three are equal.
    - The derived module keeps its STC point and reaches the set γ.
    - A fleet distribution over `module_efficiency` gives different homes (today identical).
    - The out-of-domain and wrong-form values are refused naming the field.
  - **Prereqs:** α, ε; task 195 cancelled.
  - **Keys:** fk-f5cd69400ce6, fk-0edf0069c6bb. **Priority:** high.
- **η. Retire `apply_degradation` from the surface** (held: `x_seam_wait = {stream: S29, contract: "one coordinated frozen-surface bump (D4)"}`; supersedes 609).
  - **Files:** `pv.py`, `src/solar_challenge/__init__.py` (`__all__`, `_SYMBOL_MODULE`, the `TYPE_CHECKING` import), `tests/unit/test_public_api_surface.py` (or S23's successor), `tests/unit/test_pv.py`.
  - Its release line is handed to S29's section.
  - **Signal:** B7. `from solar_challenge import apply_degradation` raises `ImportError`, and the frozen-surface test pins its absence.
  - **Prereqs:** task 284, β. S29 releases it.
  - **Key:** fk-3ccbba41d836. **Priority:** medium.

DAG: α → γ → ε → ζ; α → ζ; 284 → β → η; 284 → η; δ independent; η held for S29. fk-998f0cb69410 is delivered by task 284 and gets no S14 leaf.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- **`no-silent-fail-soft`.**
  - α deletes two silent fallbacks.
  - γ deletes the 400 W default.
  - ζ deletes the sentinel and refuses inapplicable settings.
  - ε gives a custom module without `T_NOCT` or `A_c` the default module's values. That is a stated rule in `custom_module_params`' docstring, not a hidden fallback, and it is no weaker than today, when every module gets one generic SAPM set. Recorded, no waiver needed.
- **`one-fact-one-home`.** Module identity is held by `DEFAULT_CEC_MODULE`, ageing by `calculate_degradation_factor`, and each band by its constant. ζ writes `gamma_r` and `A_c` into the derived module dict from the `PVConfig` field, its one home, so the dict stays self-consistent.
- **`exceptions-owned-or-ratified`.** The `_chandrupatla` filter is an owned suppression in one place, `run_model_chain`, whose docstring names the solver's dark-hour cause. β removes the unowned copies.
- **`guards-exercise-behaviour`.** Every grep delivered check has a behaviour twin in B1–B7.

No waivers.

## Out of scope

- **Mounting and installation inputs for NOCT-SAM** (standoff, array height). Measured: a 3 in standoff gives −0.27% and a two-storey height +0.32% on Bristol's year. Open question 5.
- **Whether finance prices capex on nameplate or wired DC** (fk-8b8f9d686b86's last sentence). That is finance's pricing basis, and the stream row leaves it out (open question 6).
- **The typed module spec that would replace the field trio** (fk-0edf0069c6bb's larger proposal). D14 keeps the fields.
- **`cli/validate results --pv-kw`'s default-module guess.** A CSV carries only a capacity.
- **`docs/web-ui-design.md`'s "Module efficiency (%)" form-field line.** The form has no such field. No consumer is named for adding one.
- **`pv.interpolate_to_minute_resolution`** (S12) and **the scripts' `set_weather_cache`** (S15).

## Open questions

For the lead:

1. **Task 195 (urgent).** Its finished branch retires both fields, the opposite of D14, and is held only by stale L2 esc-195-3. Five dry-runs recommend resolving that record as moot, which would merge it. Suggested:
   - cancel 195 now with `x_superseded_by` ζ (stamped at decompose) or an acceptance reason citing D14;
   - dismiss esc-195-2, esc-195-3 and esc-224-2 as superseded;
   - drop 224's dependency on 195 and its 195 release note.
2. **D29 reading.** `PVConfig`'s two fields widen from `float = 0.2` / `float = -0.004` to `float | None = None`, and their domains tighten. I file that in-leaf (ζ) with its form edit and an Unreleased line, because it is neither a rename nor a retirement and every constructor call stays valid. If you rule it held, ζ waits for wave 4. ε (the NOCT re-baseline) is unaffected either way.
3. **L5 for S14.** ζ adds refusals as `ValueError`, like `PVConfig`'s existing ones, and S4 converts them all. Apply L5 instead (ζ depends on S1-β and raises `errors.ConfigurationError`)? Suggested: no. That would leave `PVConfig` with mixed refusal types until S4.
4. **`run_model_chain` and `DEFAULT_CEC_MODULE` in `solar_challenge.__all__`?** They are module-public, used by pv.py, the scripts and tests. Exporting is additive (D29 in-leaf), but no package consumer is named. Suggested: not now.
5. **NOCT-SAM installation.** This PRD keeps pvlib's defaults (one storey; 4 in standoff, no NOCT adjustment), the open-rack assumption the replaced SAPM set made. UK domestic roofs are close-mounted (≈2.5–3.5 in, +2 °C NOCT) and often two-storey. A mounting field would be a new additive `PVConfig` field. File it as a follow-up after ε?
6. **Finance capex on nameplate versus wired DC** (fk-8b8f9d686b86). Should S8 or a follow-up decide it? Today a 4.0 kW config is priced as 4.0 kW and wires 4.00428 kWp. For non-dividing sizes the gap reaches one module, e.g. 0.3 kW priced and 0.4 kWp wired.
7. **Task 284 is pending with a finished branch** (base `84befcb`, 223 commits behind, merges cleanly). β and η depend on it. Suggested: let it run, and fold it into β only if it stalls.

Tactical, decided in the leaf:

8. ζ's γ solve: a finite-difference half-width (±0.5 K measured) and a bracketed root-finder over `Adjust`. γ is linear in `Adjust`, so two evaluations and a secant are exact enough.
9. δ's band values come from the leaf's source study. The MCS MIS 3002 self-consumption tables and the assistant's cited Solar Energy UK/BEIS figures are starting points. The existing synthetic-ratio tests (0.30 and 0.10 PV-only; 0.70 and 0.30 with a battery) are kept or moved to the new edges.
10. ε's handling of `scripts/measure_mppt_window.py`'s 12-minute full run: a full re-run, or the headline capacities only (`--dc-kw 3 4 5 6`) with a dated note.
