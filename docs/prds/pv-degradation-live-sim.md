# PRD — PV degradation in live simulation

- **Gap register item:** P3 (supersedes placeholder task #7)
- **Status:** active · authored 2026-05-30 (review `20260530T090214Z`)
- **Owner seam:** sole owner of the new PV-age schema field for this PRD batch
- **Approach:** bare **B** (vertical slice) + a precise field-contract announcement in `review/gap-register.md` §D. See §G5 note.

---

## 1. Goal

Make long-run yield reflect panel ageing. Today the simulator assumes panels never degrade: `pv.calculate_degradation_factor` / `pv.apply_degradation` (`pv.py:370-438`) are implemented and unit-tested but **never called** from the live path, and no config carries a system age. After this PRD, a configured PV-array age reduces simulated generation through the production sim path, so multi-year projections for the Bristol fleet are physically meaningful.

**User-observable outcome:** a scenario whose PV array is aged 20 years produces ~10% lower annual generation than an identical age-0 scenario, visible in the CLI fleet summary — without re-running any helper in isolation.

## 2. Background

- `apply_degradation(generation, system_age_years, degradation_rate_per_year=0.005)` and `calculate_degradation_factor(system_age_years, rate=0.005)` exist + are tested (`tests/unit/test_pv.py:247-298`). Linear model: `factor = max(0, 1 - age·rate)`.
- The live PV path is `pv.simulate_pv_output(config: PVConfig, location, weather_data) -> pd.Series` (`pv.py:341`). It has **exactly one production caller**, `home.simulate_home` (`home.py:199`); all other references are tests. This makes it a clean single chokepoint — every downstream consumer (single-home, fleet, CLI, web) routes through it.
- `PVConfig` (frozen dataclass, `pv.py:17`) holds array parameters (capacity, azimuth, tilt, efficiencies). It is built from parsed config in `_parse_pv_config` (`config.py`), in the fleet distribution sampler (`config.py:1240`), and in sweep builders.
- `PVDistributionConfig` (`config.py:224`) already provides per-home heterogeneity for PV parameters across a fleet.
- **Note on the register text:** the gap register says "config.py HomeConfig"; in fact `HomeConfig` lives in `home.py:26` and degradation is a property of the PV array, so the field lands on **`PVConfig`** (see §6). This is the "+ PVConfig if that fits better" branch the register authorised.

Review context: `review/reports/summary-20260530T090214Z.md` ("PV degradation defined+tested but never wired").

## 3. Sketch of approach

1. Add two fields to `PVConfig`: `system_age_years: float = 0.0`, `degradation_rate_per_year: float = 0.005`. Validate in `__post_init__` (matches the frozen-dataclass construction-time validation convention).
2. Inside `simulate_pv_output`, after computing AC power, multiply by the degradation factor via the existing `apply_degradation(ac_power, config.system_age_years, config.degradation_rate_per_year)`. Because `PVConfig` is already the argument to `simulate_pv_output`, this requires **zero signature changes** anywhere — every caller inherits degradation automatically.
3. Thread both fields through all `config.py` PVConfig-construction paths: `_parse_pv_config` (YAML single-home), `PVDistributionConfig` + its fleet parser + the distribution sampler (fleet heterogeneity), and the sweep PVConfig builders. Defaults preserve current behaviour everywhere they are not specified.
4. Ship an aged example scenario and prove the end-to-end signal via `solar-challenge fleet run`.

**Why apply inside `simulate_pv_output` and not `simulate_home`:** the degradation factor is a multiplicative scalar, so applying it on the hourly AC series before interpolation is identical to applying it later, and the single-chokepoint placement means the fleet/CLI/web paths cannot silently miss it.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Field location | `PVConfig` (not `HomeConfig`) | Degradation is a PV-array property; `simulate_pv_output` already receives `PVConfig` → zero signature changes; `PVDistributionConfig` gives free per-home age spread. |
| Field name / type / units | `system_age_years: float` (years, fractional allowed), default `0.0` | Matches the existing `apply_degradation` parameter name exactly — least friction; default 0.0 = brand-new array. |
| Rate configurability | `degradation_rate_per_year: float`, default `0.005` (0.5%/yr) | Exposed so premium (~0.25%/yr) vs commodity (~0.7%/yr) panels can be modelled; default matches the tested helper default. |
| Apply point | inside `simulate_pv_output` | Single production chokepoint; scalar factor commutes with interpolation. |
| Validation | `__post_init__`: `system_age_years >= 0`, `0 <= degradation_rate_per_year <= 1` | Mirrors the guards inside `calculate_degradation_factor` and PVConfig's existing `__post_init__`. |
| Backward compatibility | both fields default to no-op (factor 1.0) | Existing scenarios and the generation-asserting tests (`test_pv.py:172-195`) stay green. |
| Fleet heterogeneity | add both fields to `PVDistributionConfig` + sampler | A 100-home fleet can model a realistic install-age spread (e.g. a `normal` distribution on `system_age_years`). |

## 5. Pre-conditions for activating

None blocking. All substrate exists (see §G3). Independent of task #14 — the user-observable signal uses the `fleet run` path, which already routes through the canonical sampler, not the under-exposing `cli/home.py` hand-builder.

## 6. Substrate verification (G3)

No novel substrate. Every assumed capability verified present:

| Assumed capability | Evidence |
|---|---|
| `apply_degradation` callable on a generation Series | `pv.py:414-438`, tested |
| `simulate_pv_output` is the single live PV chokepoint | `pv.py:341`; only prod caller is `home.py:199` |
| `PVConfig` is the arg to `simulate_pv_output` | `pv.py:341-342` |
| `_parse_pv_config` reads the `pv:` block into `PVConfig` | `config.py` (`_parse_pv_config`) |
| `PVDistributionConfig` + sampler build per-home `PVConfig` | `config.py:224`, `config.py:1240` |
| `fleet run` routes through `generate_homes_from_distribution` | `cli/fleet.py:323/350` |

**G3 verdict: N/A — no novel substrate; pure wiring + one schema field.**

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| P2 (web UI parity) | consumes | `PVConfig.system_age_years` / `degradation_rate_per_year` exposed in the web home form | **P3 owns the schema; P2 owns the form wiring** | announced in §D of gap register; P2 wires |
| task #14 (CLI full-config parity) | consumes | same fields surfaced via the canonical `_parse_pv_config` path once #14 routes CLI through it | **P3 owns the schema; #14 owns the CLI parser fix** | announced; #14 wires (no action needed in P3) |
| task #7 | superseded | — | this PRD | #7 → cancel/replace by α+β at decompose |

No reciprocal-ownership ambiguity: P3 owns the schema and its wiring into the engine; P2/#14 own only their own surface exposure. The schema announcement in gap-register §D is the contract both consumers read.

## 8. G5 note — why bare B (not B+H)

The G5 heuristic flags cross-PRD consumers ≥ 2 (P2, #14), which leans toward B+H. **Decision: bare B + a precise §D field-contract announcement.** Reasoning: the entire cross-PRD contract is a single schema fact (two field names, types, defaults, validation, semantics), fully specified by the §D announcement — there is no multi-signature seam to document. A two-way boundary test (web form sets age → sim reflects it; CLI flag sets age → sim reflects it) necessarily touches `web/api.py` / `cli/home.py`, which are **P2's and #14's locked files** — P3 cannot author those tests without violating seam ownership. They belong to P2's and #14's decompositions. P3's own vertical slice (scenario YAML → degraded `fleet run` output) is the integration proof for the part P3 owns.

## 9. Decomposition plan

Two-task vertical slice. File contention is avoided by construction: α touches only `pv.py`, β touches only `config.py` + `scenarios/`.

### α — Wire PV degradation into the engine
- **Modules:** `pv.py` (+ `tests/unit/test_pv.py`)
- **Work:** add `system_age_years: float = 0.0` and `degradation_rate_per_year: float = 0.005` to `PVConfig`; validate both in `__post_init__`; in `simulate_pv_output`, apply `apply_degradation(ac_power, config.system_age_years, config.degradation_rate_per_year)` before return.
- **Classification:** intermediate — unlocks β.
- **Downstream prerequisite unlocked:** β consumes `PVConfig.system_age_years` / `degradation_rate_per_year` and the now-degrading `simulate_pv_output`.
- **Verification signal:** `simulate_pv_output` called with a `PVConfig(system_age_years=20)` returns generation equal to `0.90 ×` the age-0 output (live-path test on the production function, **not** a re-test of the `apply_degradation` helper); the existing age-0 `simulate_pv_output` tests remain green (backward-compat proof).

### β — Thread PV age through config + prove end-to-end via fleet run
- **Modules:** `config.py`, `scenarios/` (+ tests)
- **Work:** thread both fields through `_parse_pv_config`; through `PVDistributionConfig`, its fleet parser, and the distribution sampler (`config.py:1240`); through the sweep PVConfig builders (so no construction site silently drops them). Add an aged example scenario (e.g. `scenarios/bristol-phase1-aged.yaml`, `pv.system_age_years: 20`).
- **Classification:** leaf.
- **Prereqs:** α (intra-batch).
- **User-observable signal:** `solar-challenge fleet run <aged-scenario>` reports aggregate annual generation ≈ 10% below an identical age-0 baseline scenario (20 yr × 0.5%/yr = 0.90 factor), visible in the fleet summary; `solar-challenge config validate` accepts the new `pv.system_age_years` / `pv.degradation_rate_per_year` keys. Supporting unit tests assert `_parse_pv_config` and the sampler round-trip the fields.

> **Note for decompose-time:** the orchestrator does not yet consume the `user_observable_signal` / `consumer_ref` metadata; these are recorded for a future tracking session. Task #7 should be cancelled/replaced by α+β.

## 10. Out of scope

- Web home-form exposure of the field → **P2**.
- CLI `home run` full-config parity / fixing `cli/home.py`'s hand-builder → **task #14**. (Until #14 lands, `home run` will not surface the field; `fleet run` and the canonical parser do.)
- Non-linear / climate-dependent degradation models (the existing linear model is retained).
- Per-component (inverter vs module) degradation split.

## 11. Open questions (tactical — deferred, not design-blocking)

1. **Exact aged-scenario shape for β's signal.** A scalar `system_age_years: 20` on a small fleet is the simplest reproducible baseline-vs-aged pair. **Suggested resolution:** ship one scalar aged scenario; optionally also a `normal`-distribution age variant to exercise the sampler. Decide during β.
2. **Full list of sweep PVConfig builders to touch.** `config.py:586/1824/1835/1846` are PVConfig construction sites; β should thread the fields through every one that originates from parsed config (defaults make untouched sites safe). **Suggested resolution:** grep `PVConfig(` in config.py during β and cover all parsed-config sites.

## 12. G6 — premise validity of the leaf signal

β's signal asserts a numeric bound ("≈10% lower at 20 yr"). **Achievability basis:** the model is `factor = 1 - 20·0.005 = 0.90` exactly — a multiplicative scalar on generation, so annual-total ratio = 0.90 by construction. Already proven for the factor at `test_pv.py:265-268` (`test_year_twenty_default_rate` asserts 0.90). Not a guess. Every capability the signal needs (degrading `simulate_pv_output`, sampler threading, `fleet run` summary) is delivered by α or β themselves — nothing is owed by a downstream task. **G6 pass.**
