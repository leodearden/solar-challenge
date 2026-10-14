# Capability manifest — Errors leaf (review-all S1)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/errors-leaf.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/errors-leaf.capability-manifest.yaml`.

**Code anchors** verified against main `1251be0e621a` (2026-10-14). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Every substrate the signals read exists on main. Everything else is delivered by the leaf itself or by α upstream of β and γ.

## α — Errors leaf: ConfigurationError lives in solar_challenge/errors.py (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Constructing `FinanceConfig` today loads config and pvlib, so P2 is a real RED | probe at 1251be0: `solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0)` → `solar_challenge.config` and `pvlib` in sys.modules; same for `GridServicesEventsConfig()`; `EventWindow(months=())` refusal grows solar_challenge/pvlib modules 4 → 83 | PASS (RED observed) |
| After the move, finance and gridservices import nothing that loads pvlib | probe: `import solar_challenge.gridservices, solar_challenge.finance` loads only battery, finance, gridservices, seg, timebase, whole_numbers; errors.py adds nothing | PASS |
| `import solar_challenge` is pvlib-free and eager-import-free (P1 premise) | probe: `import solar_challenge` → `['solar_challenge']`; existing subprocess pattern in `tests/unit/test_init_lazy_surface.py` | PASS |
| mypy --strict refuses `from solar_challenge.config import ConfigurationError` once config only imports it (rejection mechanism forcing the repoint) | rejection-check: scratch package under `mypy --strict` (repo's mypy 2.1.0) → `does not explicitly export attribute "ConfigurationError" [attr-defined]`; `type_check_command` is `mypy src/solar_challenge` with `strict = true` | PASS (rejection observed) |
| The 11 function-local imports exist to delete | grep: `finance.FinanceConfig.__post_init__`, `finance.project_multi_year`, `gridservices.EventWindow.__post_init__` (8), `gridservices.GridServicesEventsConfig.__post_init__`; AST scan of src → 11 of 32 function-local package imports | PASS |
| ConfigurationError is outside the frozen surface (no S29 dependency) | grep: no `ConfigurationError` in `tests/_surface_forms.py`, `tests/unit/test_public_api_surface.py`, `src/solar_challenge/__init__.py` | PASS |
| Consumption guide takes an "Unreleased on main" line by the changing commit | grep: `docs/domain-library-consumption.md` §Tag / release convention, "Changes merged since the last tag" | PASS |

## β — ConfigurationError subclasses ValueError; uniform raises; no refusal relabelled (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| α's `errors.ConfigurationError` exists | producer: α, upstream (β depends on α) | PASS |
| `finance run` refuses an event window before any simulation (C2 needs no fake) | ran at 1251be0: `solar-challenge finance run <bristol-phase1-flex.yaml with months: [13]>` → `Configuration error: EventWindow.months values must be in 1..12, got (13,)`, exit 1 | PASS |
| A naive subclass relabels that refusal (C2 pins a real hazard) | probe: re-basing ConfigurationError onto ValueError in-process → `scenario.finance.grid_services_events.event_windows[0] contains a non-numeric value: EventWindow.months …` from `config._parse_event_windows` | PASS (hazard observed) |
| `optimize configs` reads its simulator from Click's context, so C3 can inject a refusing simulator | grep: `tests/_cli_fleet_simulator.invoke_cli` passes `obj=CliFleetSimulator(simulate=…)`; `cli/optimize.configs` guards `sensitivity_panel(...)` with `except ValueError` and has a `--sensitivity` option | PASS |
| `sensitivity_panel` can raise ConfigurationError (C3 premise) | grep: `optimize.sensitivity_panel` → `_build_axis_configs` rebuilds FinanceConfig per axis value; `FinanceConfig.__post_init__` raises ConfigurationError | PASS |
| `handle_errors` names ConfigurationError before ValueError (C1 order) | grep: `cli/utils.handle_errors` except chain | PASS |
| C1's two commands raise each type at the boundary | ran: `optimize configs <file without finance>` → `Configuration error: No 'finance:' block…`, exit 1; `home run --location '51.0,abc'` → `Invalid value: Invalid coordinates…`, exit 1 | PASS |
| GridServicesRateBand and FlexibilityValueBand raise plain ValueError today (P5 RED) | grep: `GridServicesRateBand.__post_init__` (2 × `raise ValueError`, ".. note::" citing the cycle); `FlexibilityValueBand.__post_init__` (6 × `raise ValueError`) | PASS |

## γ — Import-structure guard (INV-5) (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| α has removed the 11 imports the allow-list must not hold | producer: α, upstream (γ depends on α) | PASS |
| The real tree has a measurable set of function-local package imports to list | AST scan at 1251be0: 32 sites, 21 after α (§7 of the PRD) | PASS |
| The allow-list can be non-empty yet fully owned (corrected INV-5 premise) | §7 table: Permanent entries cite the cheap-import contract (consumption guide) or the optional `web` extra; Transitional entries name S8, S9, S12, S9/S25, tasks 153 and 454 | PASS |
| review/briefing.yaml has a `conventions` list taking rule + why entries | grep: `review/briefing.yaml` `conventions:` | PASS |
| The scan fires on a seeded violation (G1, a rejection check) | built and bound by γ: the guard's own `tmp_path` test observes the report | PASS (bound in-leaf) |
