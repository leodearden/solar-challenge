# Capability manifest — PV model: one home for module choice, run policy and ageing (review-all S14)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/pv-model-one-home.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/pv-model-one-home.capability-manifest.yaml`.

**Code anchors** verified against main `9d7b67e` (2026-10-15). Main moves fast: cite-by-symbol; re-locate lines at implementation time. Probes ran under pvlib 0.15.1 (`uv run --locked --extra dev`). Their weather was the tests' `synthetic_june_weather("2024-06-21")` and Bristol's TMY from the main checkout's `.cache/weather` (GHI 1069.46 kWh/m²).

**Batch verdict: PASS, conditional on two pre-conditions.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Every refusal a signal asserts is built by the leaf that asserts it and observed by that leaf's own test. The two pre-conditions are named in the PRD:

- task 284 lands upstream of β and η;
- task 195 is cancelled before ζ.

## α — Name the default module and require its row (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The named row exists in the locked catalogue | probe: `retrieve_sam("CECMod")` has 21,535 columns, including `Canadian_Solar_Inc__CS1U_400MS` (STC 400.428 W) | PASS |
| Today a library missing the row is simulated silently with another module (B1's RED) | probe: the substring selector's matches are `[CS1U_400MS, CS3W_400P]`, so without the first it returns `CS3W_400P` (400.158 W); both fallbacks follow | PASS (RED observed by reading the probe's match list) |
| A row guard exists to generalise | grep: `pv._require_cec_library_row` refuses an inverter name absent from `CECInverter` | PASS |
| The 7 restatements exist to repoint | grep `400\.428\|CS6K` over src, docs and tests: the `wired_dc_capacity_kw` docstring, `docs/pv-inverter-string-matching.md` ×2, `docs/pv-annual-yield-benchmark.md` ×1, `tests/unit/test_validation.py` ×3; the `CS6K` comment ×2 in `_get_cec_module` | PASS |
| The refusal fires when the row is absent | built and bound by α: its subprocess test patches `retrieve_sam` and observes the message naming the row and `CECMod` | PASS (bound in-leaf) |

## β — One run policy: `run_model_chain` (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A bare run emits the warnings the policy suppresses (B2's RED) | probe: `create_model_chain(PVConfig.default_4kw(), bristol).run_model(day)` → 39 `RuntimeWarning: invalid value encountered in divide` from `scipy/optimize/_chandrupatla.py` | PASS (RED observed) |
| Four copies of the policy exist to collapse | grep: `simulate_pv_output`, `measure_pv_performance_ratio.in_plane_irradiation`, `measure_mppt_window.main` (process-wide), and `tests/unit/test_measurement_scripts._QUIET_DIODE_SOLVER`, plus 3 `filterwarnings` marks in `tests/unit/test_pv.py` | PASS |
| Every chain ages on DC, so `run_model_chain` needs only the warning policy | producer: task 284 (branch `task/284`: `_dc_kept_fraction`, `_deduct_dc_losses`; `simulate_pv_output`'s `apply_degradation` call removed), upstream of β; `git merge-tree` against main is clean | PASS (producer upstream) |
| `measure_year` today depends on `main`'s process-wide filter | grep: `measure_mppt_window.measure_year` calls `chain.run_model(weather)` with no filter; `main` installs `warnings.filterwarnings` before calling `census` | PASS |
| `measure` mixes the two entry points today | grep: `measure_pv_performance_ratio.measure` calls `in_plane_irradiation` (`create_model_chain`) and `annual_ac_kwh` (`simulate_pv_output`) | PASS |

## γ — One rating; wired DC from the built system (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A 300 W PVWatts dict is miscounted today (B3's RED) | probe: `PVConfig(4.0, custom_module_params={"pdc0": 300, "gamma_pdc": -0.004})` wires 10 modules, `wired_dc_capacity_kw` → 4.0, and the clear-day peak is 2.66 kW (3.0 kWp modelled) | PASS (RED observed) |
| After the fix: 13 modules, 3.9 kWp | arithmetic: `max(1, round(4000 / 300))` = 13; 13 × 300 W = 3.9 kW; pvlib's PVWatts DC scales `pdc0` by the module count (the `create_simple_module_params` docstring; task 196) | PASS |
| The default sizes keep their wired DC | arithmetic: 0.3 kW → 1 × 400.428 W; 4 kW → 10 × 400.428 W; the built system's arrays hold the same counts | PASS |
| `wired_dc_capacity_kw` is free to change its body | grep: not in `FROZEN_SURFACE` or `solar_challenge.__all__` | PASS |
| A module with neither `pdc0` nor `STC` is refused | built and bound by γ's own test | PASS (bound in-leaf) |
| α's `_cec_library_module` is the template accessor | producer: α, upstream | PASS |

## δ — Validation states what it applies (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The stated and applied bands differ today | grep: `validate_self_consumption_pv_only`'s docstring says ~25–35% and the code applies 20.0–45.0 ("Slightly wider"); `validate_self_consumption_with_battery` says ~60–80% and applies 50.0–90.0 | PASS |
| The size notes depend on a nameplate today (B4's RED) | grep: both functions compute `(capacity_kw * 900) / annual_consumption_kwh`; for the same results, a 1 kW and a 6 kW nameplate cross different note thresholds (0.26 against 1.59) | PASS |
| The signatures may drop `capacity_kw` | grep: neither function is in `FROZEN_SURFACE`; callers are `validate_simulation` and `tests/unit/test_validation.py` only | PASS |
| `SimulationResults` carries the generation and demand the notes read | grep: `home.SimulationResults.generation` and `.demand`, which `validate_simulation` already reads | PASS |
| A sourced band doc has a precedent shape to follow | `docs/pv-annual-yield-benchmark.md` §2 (sources, scope, "not derived from the model") | PASS |
| S22 will read the constants | proposed cross-reference; S22's fk-194e5b40da23 proposal asks for exactly these hoisted constants | PASS (consumer named) |

## ε — Cell temperature from the module: NOCT-SAM for every run (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| pvlib infers `noct_sam` from the array's parameters | grep in pvlib 0.15.1: `ModelChain.infer_temperature_model` returns `noct_sam_temp` when `{'noct', 'module_efficiency'} <= params`; `Array.get_cell_temperature` builds both from `temperature_model_parameters`. probe: the patched default chain's `temperature_model` is `noct_sam_temp` | PASS |
| The template carries its own NOCT and efficiency | probe: `T_NOCT` 45.1; `A_c` 1.99 → 400.428 / 1990 = 0.2012 | PASS |
| The default clear-day energy moves ×1.031 (B5) | probe: 26.0119 → 26.8194 kWh on `synthetic_june_weather("2024-06-21")` | PASS |
| Bristol's re-baseline stays inside the slow guard | probe: 993.14 → 1012.12 kWh/kWp (×1.0191); ratio 0.8034 × 1.0191 ≈ 0.819, inside `tests/integration/test_pv_performance_ratio.py`'s 0.76–0.84 | PASS (floor: 0.76 < 0.819 < 0.84) |
| A low-efficiency module runs hotter, so yields less | probe under NOCT-SAM: η 0.10 → ×0.9901 clear day and ×0.9951 year against η 0.2012; η 0.22 → ×1.0018 | PASS |
| `create_simple_module_params` is free to change its output keys | grep: not in `FROZEN_SURFACE` or `__all__`; callers are `pv.py` docstrings and tests | PASS |
| γ's rating rule feeds the efficiency (rating / (A_c × 1000)) | producer: γ, upstream | PASS |
| Re-measurement can run offline | the main checkout's `.cache/weather` holds Bristol's TMY (`tmy_5dc8c8bca218`); the probes read it through `WeatherCache` with no network | PASS |

## ζ — `module_efficiency` and `temperature_coefficient` become live (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Today the fields change nothing (B6's RED) | the finding's measurement (497.7746611592203 kWh for three settings); grep: `module_efficiency` is read nowhere in `pv.py`; the sentinel `config.temperature_coefficient != -0.004` writes `gamma_pdc` on a CEC dict | PASS (RED observed) |
| A set γ keeps the STC point (exactness) | identity: `calcparams_cec` uses `alpha_sc * (1 - Adjust / 100)` only in the `(T − T_ref)` term, so at 25 °C and 1000 W/m² the parameters don't depend on `Adjust`. probe: P_mp(STC) = 400.4281 W for `Adjust` −500…2000 | PASS |
| The `Adjust` solve reaches every γ in the domain [−0.01, 0) | probe: γ is linear in `Adjust`, from −0.035 to −1.57 %/K over −500…2000; −1.0 %/K needs `Adjust` ≈ 1070, where P_mp(90 °C) stays positive (125 W at 1500); γ → 0 needs ≈ −560 (P_mp positive from −40 to 90 °C) | PASS |
| The domain covers every real module | probe: `gamma_r` spans −0.679…−0.166 %/K over 21,535 rows; STC / A_c spans 0.036…0.227, inside 0 < η < 0.9 | PASS |
| The template's own γ round-trips | probe: solving for −0.0034730 returns `Adjust` 7.312982 (row 7.312982); clear-day energy ×(1 + 1e-11) | PASS |
| Clear-day bounds (−0.005 ≥ 1.5% below; −0.003 above; η 0.10 ≥ 0.5% below) | probe under NOCT-SAM: 0.97862, 1.00661 and 0.99009 against the default. Each bound has ≥ 0.5 pp margin over the measured value | PASS (floor: 1.5% < 2.14%; 0.5% < 0.99%) |
| A steeper γ lowers annual yield | NOT asserted. probe: Bristol year ×1.0055 at −0.005, because cells spend most of the year below 25 °C | premise rejected; signal restricted to the clear day |
| The efficiency acts on output | producer: ε (NOCT-SAM reads the module's efficiency), upstream of ζ | PASS |
| The YAML and fleet plumbing exist to change | grep: `_PV_BLOCK_KEYS` names both; `PVDistributionConfig.module_efficiency` defaults to 0.20; `generate_homes_from_distribution` falls back with `else 0.20`; `scenario_writer` writes both keys | PASS |
| The frozen form pins both fields today | grep: the `FROZEN_SURFACE` entry for `PVConfig` reads `module_efficiency: float = 0.2, temperature_coefficient: float = -0.004` | PASS |
| The out-of-domain and wrong-form refusals fire | built and bound by ζ's own tests | PASS (bound in-leaf) |
| Task 195 does not retire the fields first | pre-condition: 195 cancelled (PRD open question 1); its branch `task/195` deletes both fields and merges cleanly, so the risk is real | CONDITIONAL (lead action) |

## η — Retire `apply_degradation` from the surface (held leaf, S29)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| No src caller remains after task 284 | producer: task 284's diff removes `simulate_pv_output`'s `apply_degradation` call; grep on main finds no other src caller | PASS (producer upstream) |
| It is a frozen name today | grep: `apply_degradation` in `solar_challenge.__all__`, `_SYMBOL_MODULE` and `FROZEN_SURFACE` | PASS |
| Removal waits for S29's bump | D4/D29: a retirement is a held leaf; filed with `x_seam_wait` | PASS |
