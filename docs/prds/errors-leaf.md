# PRD — Errors leaf: one exception vocabulary below config

- **Program:** review-all-solar_challenge-20261013, stream **S1** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 1, no upstream deps, size S, risk low.
- **Finding keys:** fk-601c5b5f6415 (weakened; re-measured in §2), fk-4435376bedb3, fk-da69830bb2d6, fk-291910b552af.
- **Binding rulings:** D2 (ConfigurationError moves to an errors leaf and subclasses ValueError; the web boundary translator logs a non-domain ValueError separately), D9 (the shared finite checker raises ConfigurationError), D27 (INV-5 promoted; S1 owns its test).
- **Status:** authored 2026-10-14 by an author-only /prd session; not yet committed.
- **Approach:** B + H. The seam is the one refusal type both boundaries and four later streams read, so it gets a contract (§4) and two-way boundary tests (§5).
- **Code anchors** verified against main `1251be0e621a` (2026-10-14). Main moves fast — cite-by-symbol; re-locate lines at implementation time. `config.py`, `finance.py`, `gridservices.py`, `flex.py` and `cli/utils.py` are unchanged since the review's pin `7dfea36e`; `web/` has moved, but S1 touches only its import lines.

## 1. Goal

`solar_challenge.errors` becomes the package's bottom stratum. It imports no solar_challenge module and is the home of `ConfigurationError`, which subclasses `ValueError` (D2). config, finance, gridservices and every other importer import the class from there at module top. That deletes the 11 function-local imports, the ~38 lines of prose defending them, and the hidden cycle config → finance/gridservices → config.

What a user observes:

1. **A library consumer stops paying for pvlib when constructing finance values.** Today, `solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0)` in a fresh interpreter loads `solar_challenge.config` and pvlib, because `FinanceConfig.__post_init__` imports config on every construction. `GridServicesEventsConfig()` does the same, and an `EventWindow` refusal grows `sys.modules` from 4 to 83+ package and pvlib modules (probed at 1251be0). This contradicts the consumption guide's "Lazy pvlib dependency" caveat, which says only `pv` and `weather` names pull pvlib. After α, none of these constructions loads config or pvlib.
2. **One refusal type at both boundaries.** `except ValueError` catches every ConfigurationError. `solar-challenge` still prints `Configuration error: …` for a ConfigurationError and `Invalid value: …` for any other ValueError, both with exit 1, and a test pins `handle_errors`' clause order.
3. **No refusal changes its wording because of the subclassing.** `solar-challenge finance run s.yaml`, where the finance block's event window has `months: [13]`, prints `Configuration error: EventWindow.months values must be in 1..12, got (13,)` and exits 1, exactly as today. A naive subclass change would print `…event_windows[0] contains a non-numeric value: EventWindow.months…` (probed by re-basing the class in a scratch interpreter).
4. **Uniform raises.** `GridServicesRateBand` and `FlexibilityValueBand` refuse with ConfigurationError like `EventWindow`, `GridServicesEventsConfig` and `FinanceConfig`. Their ValueError was forced by the cycle, as their own docstrings say.
5. **A guard keeps it so.** The per-task verify fails when a module gains a function-local package import that is not on an owned allow-list, naming the file, line and imported module. It also fails when a listed import has gone, naming the stale entry (INV-5, D27).

## 2. Background (measured at 1251be0)

- `config.py` defines `class ConfigurationError(Exception)` and imports battery, community, ev, finance, fleet, gridservices, heat_pump, home, load, location, pv, seg and tariff at top level.
- `finance.FinanceConfig.__post_init__` imports ConfigurationError at its top, so on every construction (comment: "lazy: avoids import cycle"). `finance.project_multi_year` imports it again inside its capacity_at_events fail-fast branch. `gridservices.EventWindow.__post_init__` imports it once per failure branch (8 imports), and `GridServicesEventsConfig.__post_init__` once at its top. That makes 11 imports, which are 11 of the import graph's 13 cycle-closing deferred imports.
- Prose defending the workaround:
  - gridservices' module docstring "Import cycle note": 6 lines.
  - `GridServicesRateBand.__post_init__` ".. note::" on why it raises ValueError: 12 lines.
  - `EventWindow.__post_init__` ".. important::": 12 lines.
  - `GridServicesEventsConfig.__post_init__`: 4 docstring lines and a 3-line comment.
  - finance's inline comment: 1 line.
- `issubclass(ConfigurationError, ValueError)` is False. Every boundary therefore lists its own catch tuple (fk-291910b552af, fk-6c98ee030531).
- Importers of the class:
  - src: cli/utils, cli/validate, cli/optimize, web/api, web/builder_form, web/fleet_scenario and web/simulation_params.
  - tests: 17 files.
- mypy runs `--strict` over `src/solar_challenge`. Once config only *imports* the class, every `from solar_challenge.config import ConfigurationError` fails with `Module "…config" does not explicitly export attribute "ConfigurationError" [attr-defined]` (probed with the repo's mypy 2.1.0). That rejection mechanism is what makes repointing the importers mandatory.
- ConfigurationError is not in `__all__` and not named by FROZEN_SURFACE, FROZEN_CLOSURE or FROZEN_MEMBERS. S1 changes no frozen name, so D4's S29 bump is not involved. `GridServicesRateBand` is public, but only what it raises changes, so its signature and surface form stay the same.

**Weakened finding re-measured (D28), fk-601c5b5f6415:**

| Measurement | Finding | Skeptic | 1251be0 |
|---|---|---|---|
| cycle-closing deferred ConfigurationError imports | 11 | 11 | 11 (finance 2, gridservices 9) |
| prose lines defending them | ~20 | ~28 | ~38, counting the rate-band note |
| `raise ConfigurationError` sites (config / gridservices / finance) | 93 / 14 / 10 | same | 93 / 14 / 10 |
| `raise ValueError` sites in the other domain modules | 178 in 18 | 155–156 in 17 | 179 AST nodes over src/solar_challenge/*.py minus config.py; 83 of them sit in the `__post_init__` of 27 classes across 17 modules |
| config loaded by `import finance` / `import gridservices` | no | no | no, but *constructing* FinanceConfig or GridServicesEventsConfig loads config and pvlib |

The finding's conclusion holds. Its counts were understated, and constructing these classes costs more than its probe measured.

## 3. Resolved design decisions

1. **Base class `ValueError`** (D2, binding). `except ValueError` keeps catching every refusal. A boundary that must tell a domain refusal from a defect names ConfigurationError first.
2. **errors.py holds ConfigurationError only.** The following stay with the modules that raise them, because none of them closes a cycle:
   - `weather.WeatherDataError` (a RuntimeError);
   - `validation.ValidationError`;
   - the web's refusal types (S17's NotAJsonObject, S19's StoredRunUnreadable).

   errors.py is where a future package-wide error type goes.
3. **No structured fields on ConfigurationError.** No reader parses a refusal today: the web returns `str(exc)` and the CLI prints it. A `path` or `field` attribute would have no consumer (G1). If S4 or S5 find that D9's "config's readers add the key path on the way up" needs the path as data, they extend the class in a leaf of their own that depends on α (open question 2).
4. **Who raises ConfigurationError.** An input value object raises it when it refuses a value it is given: component configs, tariff, location, SEG, and finance, grid-services and flexibility settings. So does the scenario grammar. A computed result that breaks its own invariant is a defect and keeps raising plain ValueError. Examples are EnergyFlowResult, BillBreakdown, YearPoint, DispatchDecision and RankedSweep. Those plain ValueErrors are the "non-domain ValueError" that D2's web translator logs. The rule is stated once, in ConfigurationError's docstring. S1 converts only the two input types whose ValueError the cycle forced, GridServicesRateBand and FlexibilityValueBand. The other input types' refusals are S4's to convert under D9 (open question 1).
5. **Every importer imports from `solar_challenge.errors`, tests included.** config.py imports the class for its own raises and does not re-export it: no shim, per D4. Repointing the tests too means S5's partition of config.py cannot break them. An external consumer still importing from `solar_challenge.config` keeps working at runtime but fails its own `mypy --strict`. The consumption guide says so.
6. **The subclassing hazard is audited, not assumed additive.** I listed every handler that catches ValueError, or a tuple holding ValueError but not ConfigurationError, around a call that can raise ConfigurationError (§6). Two of them would change behaviour once the class is a ValueError, and β keeps today's behaviour at both. The rest are benign, or turn an HTTP 500 into the 400 that D2 wants.
7. **The CLI boundary keeps its two labels.** A test pins `handle_errors`' clause order (ConfigurationError before ValueError), not a comment. TypeError is not added: a programming error is not a refusal, and `capacity_kw: "4kW"` is S4's (and task 423's).
8. **The web boundary changes only its import lines.** The three `raise ValueError(str(exc)) from exc` rewraps, `FLEET_FORM_REFUSALS` and the per-route tuples go with S17's translator, and S17's deletable list already names them. The rewraps must go in the same change as the translator: they turn a ConfigurationError into a plain ValueError, which the translator would log as non-domain. The program's S1 deletable clause about the web therefore belongs to S17 (cross-reference line).
9. **INV-5's guard is an AST scan with an owned, two-way allow-list.**
   - It scans src/solar_challenge for `Import`/`ImportFrom` nodes of `solar_challenge.*` nested in a function.
   - The set of (importing module, imported module) pairs it finds must equal the test's allow-list. An unlisted import fails, naming file:line and the imported module. A listed pair no longer found also fails, naming the stale entry.
   - Each entry has one of two kinds of reason. `Permanent` names the documented contract that requires the laziness: the package's cheap top-level import, or the optional `web` extra. `Transitional` names the task or program stream that removes the import.
   - This corrects INV-5's premise (§7).
10. **Three leaves.**
    - α moves the class. It preserves behaviour, apart from the pvlib-cost fix.
    - β carries all of D2's semantic change.
    - γ is the guard.

    β and γ both depend on α and touch disjoint files.

## 4. Contract — `solar_challenge.errors`

```python
# src/solar_challenge/errors.py — imports no solar_challenge module, at any scope
class ConfigurationError(ValueError):   # α ships (Exception); β makes it (ValueError)
    """A value an input type or the scenario grammar refuses, the message naming the value and why. ..."""
```

| # | Invariant | Enforced by |
|---|---|---|
| C1 | errors.py imports no solar_challenge module at any scope | α's fresh-interpreter test (sys.modules); γ's AST guard for function scope |
| C2 | One class object, one spelling: `solar_challenge.errors.ConfigurationError` in src and tests | mypy --strict (src); α's delivered check (`from solar_challenge.config import ConfigurationError` absent) |
| C3 | `issubclass(ConfigurationError, ValueError)` | β's test |
| C4 | Raised by input value objects and the grammar for a refused value; a computed result's broken invariant raises plain ValueError | the class docstring (rule's one home); β's tests for gridservices and flex; S4's INV-1 test asserts the type for every numeric refusal (D9) |
| C5 | A handler that treats ConfigurationError differently from other ValueErrors names it first; a handler catching ValueError around a call that can raise ConfigurationError does not relabel it by accident | β's CLI tests (§5 C1–C3) |
| C6 | No function-local import of a solar_challenge module unless γ's allow-list holds it with a reason | γ's guard |
| C7 | Constructing FinanceConfig, GridServicesEventsConfig, EventWindow, GridServicesRateBand or FlexibilityValueBand, valid or refused, loads neither `solar_challenge.config` nor pvlib | α's fresh-interpreter test |

Error semantics are unchanged: the message names the refused value and why. Ordering: config.py, finance.py, gridservices.py and flex.py import errors at top level. errors.py sits below all of them, so no import order can cycle.

## 5. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer | import the leaf alone | fresh interpreter (`-I` subprocess, as test_init_lazy_surface does) | `import solar_challenge.errors` leaves exactly `solar_challenge` and `solar_challenge.errors` among solar_challenge.* in sys.modules | α |
| P2 | producer | construct finance values | fresh interpreter | `solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0)` and `GridServicesEventsConfig()` leave `solar_challenge.config` and `pvlib` out of sys.modules (RED today) | α |
| P3 | producer | refuse an event window | fresh interpreter | `EventWindow(months=(), …)` raises `solar_challenge.errors.ConfigurationError` and leaves config and pvlib unloaded (RED today) | α |
| P4 | producer | base class | — | `issubclass(ConfigurationError, ValueError)` (RED until β) | β |
| P5 | producer | uniform raises | — | `GridServicesRateBand(-1.0, 0.0)` and a FlexibilityValueBand with a negative `time_shift_gbp` raise ConfigurationError, message naming the field (RED today: plain ValueError); the existing `pytest.raises(ValueError…)` cases tighten to ConfigurationError | β |
| C1 | consumer: CLI | label order | `optimize configs <file without a finance block>` (raises ConfigurationError) and `home run --location '51.0,abc'` (raises plain ValueError); both verified at 1251be0 | stderr starts `Configuration error:` and `Invalid value:` respectively, both exit 1 | β |
| C2 | consumer: CLI | event-window refusal | scenario file whose finance block's event window has `months: [13]`; refusal precedes any simulation, so no fake needed | `finance run` exits 1; stderr holds `Configuration error:` and `EventWindow.months values must be in 1..12`; it does not hold `non-numeric` | β |
| C3 | consumer: CLI | sensitivity panel | `optimize configs <file> --sensitivity <alias>` through `tests/_cli_fleet_simulator.invoke_cli`, whose simulator answers the main sweep and raises ConfigurationError for a panel run | exit 1, stderr `Configuration error:`; stdout lacks `Sensitivity panel skipped` | β |
| C4 | consumer: library | catch by base | — | `pytest.raises(ValueError)` catches a `load_scenarios` refusal (a scenario with an unrecognised key) | β |
| C5 | consumer: web | no change | existing web route tests | still pass unchanged (S1 edits only web import lines) | α, β |
| G1 | guard | seeded violation | `tmp_path` package with one function-local `from solar_challenge.config import X` | the scan reports that file:line and module | γ |
| G2 | guard | the real tree | src/solar_challenge at γ's base | found pairs == allow-list; each entry's reason is Permanent(contract) or Transitional(owner) | γ |

## 6. Subclassing audit (β's work list)

Every handler in src that catches ValueError (alone or in a tuple without ConfigurationError) was checked for a try body that can raise ConfigurationError, as of 1251be0:

| Site (by symbol) | Body can raise ConfigurationError? | Effect once ConfigurationError is a ValueError | β's action |
|---|---|---|---|
| `config._parse_event_windows` — `except (ValueError, TypeError, OverflowError)` around `EventWindow(...)` | yes: EventWindow's own refusals | relabelled "`<path>` contains a non-numeric value: …" (**probed**) | coerce inside the try, construct outside it (or let ConfigurationError pass); C2 pins |
| `cli/optimize.configs` — `except ValueError` around `sensitivity_panel(...)` | yes: FinanceConfig rebuilt per axis value, project economics | a refusal becomes "Sensitivity panel skipped: …", exit 0 (silent fail-soft) | let ConfigurationError propagate to handle_errors as today; C3 pins |
| `cli/utils.handle_errors` | yes | none: the ConfigurationError clause precedes ValueError | pin the order (C1) |
| `cli/validate._findings` — `(ConfigurationError, ValueError)` | yes | none | import line only |
| `config.parse_seg_rate`, `_parse_seg_rate_scalar` (×2), `_parse_grid_services_events_config`, `parse_finance_config`, `_parse_community_config` | no: seg, `_number` and community raise ValueError/TypeError | none | none |
| `web/api`, `web/assistant` — `(ValueError, TypeError)` around `parse_home_config` | via the three rewraps only | none | none (S17) |
| `web/api` around `scenario_from_builder_form`, the scenario writer and `sample_distribution`; `web/builder_form.builder_form_errors` | not on any path found | if one appears: 500 → 400/422, D2's direction | none |
| `tariff`, `weather`, `cli/utils.parse_location`, `cli/optimize._parse_float_list`, `web/shared`, `web/presets`, `web/storage`, `web/simulation_params.read_iso_date` | no | none | none |

β re-runs this audit at its own base (grep `except.*ValueError` over src). A new site whose body can raise ConfigurationError gets the same treatment: keep today's behaviour, or change it deliberately with a test.

## 7. INV-5 (D27): premise correction

The program's checkable text for INV-5 says the allow-list is "empty after the Errors, Finance, Grid-services and Load composition streams land". Measured at 1251be0, src has 32 function-local package imports:

- S1 removes 11.
- S8 removes 8 (finance → battery, fleet, home, pv).
- S9 removes 1 (finance → gridservices).
- S12 removes 1 (load → ev).

The other 11 stay after those four streams:

| Importer → imported | Reason kind | Reason / owner |
|---|---|---|
| `solar_challenge` (`get_cli_app`) → `cli` | Permanent | cheap top-level import (consumption guide) keeps Typer/Rich unloaded |
| `cli.web` → `web`, `web.jobs` | Permanent | the `web` extra is optional; `solar-challenge --help` runs without Flask |
| `web` (`create_app`) → `web.app` | Permanent | optional `web` extra; task 153 keeps and types the shim |
| `web.api` → `web.fleet_config` | Transitional | task 153 hoists it (S18 may delete the endpoint's sampler first) |
| `web.routes` → `web.database` | Transitional | task 454 hoists it |
| `web.routes` → `web.charts` (×2), `web.history` → `web.charts` | Permanent or Transitional | tasks 153 and 454 disagree: 153 keeps them so building the app leaves plotly unimported, 454 hoists them; γ records whichever has landed at its base |
| `cli.finance` → `gridservices` | Transitional | S9 (D13 moves the grid-services figure's computation) or S25 (cli/finance.run restructure) |

So the corrected checkable form is this. Every function-local solar_challenge import is on the allow-list with a reason. The list's Transitional entries are empty once S1, S8, S9, S12 and tasks 153/454 land. Each Permanent entry cites the contract that requires the laziness. γ measures the table at its own base, because 153, 454 and S9 may land first.

## 8. Existing tasks this PRD meets

- **177** (pending, low) plans the same move into `errors.py`, plus a config split into `config_parsing.py` that contradicts S5's partition (scenario_blocks / fleet_distribution / config). fk-601c5b5f6415's Phase-5 ticket was resubmitted and combined into it (tkt_0RVSJFZ0F5FRC7DGAGEVQXFZDY; the report's tkt_0RVRX9EAAMRDYC3Z5HD5WWTCBT failed on a server restart). Recommendation: cancel 177 as superseded by S1-α (the move) and S5 (the partition) when S1 files (lead question 4).
- **153, 454** (pending) own the web deferred imports in §7.
- **355, 423, 509** (pending) each state "ConfigurationError is not a ValueError" as a premise; that goes stale when β lands. Their owners are S19, S4/S5 and S17/S5 respectively.

## 9. Cross-PRD relationship

| Other stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S4 Finite quantities | consumes | `errors.ConfigurationError` as the checker's refusal type (D9) | S1 (α, β) | declared: S4 depends on S1 |
| S5 Scenario grammar | consumes | errors.py as the partition's bottom stratum; config.py's top-level import moves with the parsers | S1 (α) | declared: S5 depends on S1 |
| S8 Finance partition | consumes | finance.py's top-level import; S8 deletes its finance entries from γ's allow-list | S1 owns the guard; S8 shrinks it | declared: S8 depends on S1 |
| S17 Web request boundary | consumes | ConfigurationError ⊂ ValueError (β); S17 owns the translator and deletes the rewraps, FLEET_FORM_REFUSALS and per-route tuples | S1 type, S17 translator | declared: S17 depends on S1 (β, not only α) |
| S2 Dispatch configuration | consumes | D3's construction-time refusal naming grid_charging is raised below config (battery/dispatch), so it needs `errors` | S1 (α) | **proposed**: S2's refusal leaf depends on α (program lists no deps) |
| S9 Grid-services selector | consumes / shrinks | its closed-selector refusal in finance.py; it deletes finance → gridservices (γ entry) and the `project_multi_year` branch whose import α deletes | S1 (α) | **proposed**: refusal leaf depends on α; else textual merge only |
| S11 Tariff coverage | consumes | TariffConfig's tiling refusal is an input refusal (C4) raised in tariff.py | S1 (α) | **proposed**: depends on α, or raise ValueError for S4 to convert |
| S28 Battery facts | consumes | BatteryConfig's efficiency refusal (battery.py) | S1 (α) | **proposed**, as S11 |
| S12 Load composition | shrinks | deletes load → ev's γ entry | S1 guard, S12 edit | note only |
| S7 Component defaults | consumes | the sampler's pool-index refusal (fk-291910b552af's IndexError) raises ConfigurationError from config | S1 type | no dep needed: config imports the class either way |
| S29 Surface bump | none | S1 changes no frozen name; optional: add ConfigurationError to `__all__` at the bump | S29 | lead question 3 |

fk-291910b552af is closed by the conjunction of S1-β (one type, pinned CLI order), S4 (the `"4kW"` TypeError, refused with its key path), S5 (block paths in every reader), S7 (shuffled pool shorter than the fleet) and S17 (one web catch).

## 10. Decomposition plan

**α — Errors leaf: ConfigurationError lives in solar_challenge/errors.py, imported at module top everywhere** (leaf)

- **Modules:**
  - src/solar_challenge/errors.py (new);
  - config.py, finance.py and gridservices.py;
  - import lines in cli/utils.py, cli/validate.py, cli/optimize.py, web/api.py, web/builder_form.py, web/fleet_scenario.py and web/simulation_params.py;
  - the import lines of the 17 test files;
  - a new test module (suggested: tests/unit/test_errors_leaf.py);
  - docs/domain-library-consumption.md.
- **Work:**
  - Create errors.py with `class ConfigurationError(Exception)` and the C4 docstring, and delete the class from config.py.
  - Import it at module top in config, finance and gridservices. Delete every function-local `from solar_challenge.config import ConfigurationError` still present (11 at 1251be0; S9 may remove the `project_multi_year` one first).
  - Delete the cycle prose. That is the module "Import cycle note", EventWindow's ".. important::", GridServicesEventsConfig's paragraph and comment, and finance's inline comment. GridServicesRateBand's ".. note::" waits for β, which changes what the class raises.
  - Repoint every src and test importer.
  - Add an **Unreleased on main** line to the consumption guide. It says the class's home is `solar_challenge.errors`, that `solar_challenge.config` still binds it at runtime but no longer exports it to mypy --strict, and that constructing FinanceConfig, GridServicesEventsConfig or an EventWindow no longer imports the scenario grammar or pvlib.
- **Signal (user-observable):** in a fresh interpreter (P1–P3), `solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0)` leaves pvlib and `solar_challenge.config` out of sys.modules; RED today, verified. An `EventWindow` refusal raises `solar_challenge.errors.ConfigurationError` without loading config. `import solar_challenge.errors` loads nothing else from the package. mypy --strict and the full suite stay green.
- **Consumer:** library consumers (the platform repo); β, γ, S4, S5, S8, S17.
- **Prereqs:** none.

**β — ConfigurationError subclasses ValueError; uniform raises; no refusal relabelled** (leaf)

- **Modules:**
  - errors.py, gridservices.py (GridServicesRateBand and its ".. note::") and flex.py (FlexibilityValueBand);
  - config.py (`_parse_event_windows`) and cli/optimize.py (`configs`' sensitivity-panel guard);
  - tests: test_gridservices, test_flex, and the CLI tests for C1–C4;
  - docs/domain-library-consumption.md.
- **Work:**
  - Make the base ValueError (D2).
  - Make GridServicesRateBand and FlexibilityValueBand raise ConfigurationError and delete the rate band's ".. note::".
  - Re-run and act on the §6 audit.
  - Add an Unreleased line: ConfigurationError subclasses ValueError; those two classes raise it where the tag raises a plain ValueError; an `except ValueError` placed before an `except ConfigurationError` now takes it.
- **Signal (user-observable):** `solar-challenge finance run` on a `months: [13]` event window prints `Configuration error: EventWindow.months values must be in 1..12, got (13,)` (no "non-numeric"), exit 1. `optimize configs --sensitivity` exits 1 with `Configuration error:` when a panel run is refused, not "skipped". The CLI labels a ConfigurationError and a plain ValueError differently (C1). `GridServicesRateBand(-1.0, 0.0)` raises ConfigurationError, which `except ValueError` catches.
- **Consumer:** CLI users; S17's translator (which needs ConfigurationError ⊂ ValueError); S4's checker (D9).
- **Prereqs:** α.

**γ — Import-structure guard (INV-5): function-local package imports only by an owned allow-list** (leaf)

- **Modules:** tests/unit/test_import_structure.py (new); review/briefing.yaml (one `conventions` entry: rule + why, pointing at the test, per D27).
- **Work:** the D-9 guard, measured at γ's base and classified as §7 does.
- **Signal (user-observable):** the per-task verify runs it.
  - A function-local `from solar_challenge.config import ConfigurationError` added to gridservices.py fails it, naming gridservices.py:<line> and `solar_challenge.config`.
  - Deleting finance's deferred `battery` import, as S8 will, fails it naming the stale entry until the entry goes.
  - G1 shows the scan detecting a seeded violation.
  - The briefing gains the rule.
- **Consumer:** every agent that adds or removes a function-local import: S8, S9, S12, tasks 153 and 454, /review's briefing.
- **Prereqs:** α (its allow-list reflects the post-α tree).

Intra-batch edges: β → α, γ → α. No out-of-batch prerequisites. At decompose: α carries `x_finding_key` [fk-601c5b5f6415, fk-4435376bedb3, fk-da69830bb2d6]; β carries [fk-291910b552af, fk-da69830bb2d6]; γ carries [fk-601c5b5f6415]. All are medium priority. No leaf is high or critical, so none joins the trigger-chain gate.

## 11. Out of scope

- Converting the other input types' ValueError refusals: battery, pv, load, ev, heat_pump, location, seg, tariff, community, fleet and dispatch inputs. That is S4 under D9 (open question 1).
- The web translator; deleting the rewraps, FLEET_FORM_REFUSALS and the except-tuples (S17).
- Block paths in reader messages (S5).
- The TypeError on `"4kW"` (S4; task 423).
- The sampler's IndexError (S7).
- Moving GridChargeConfig and DispatchStrategyConfig out of config, and battery's TYPE_CHECKING import of them (fk-4435376bedb3's other half: S2 under D5, S5 for the interim home).
- Making `ConfigurationError` public in `__all__` (S29's bump, if wanted).
- WeatherDataError, ValidationError and the web's own error types.
- Hoisting the web's deferred imports (tasks 153 and 454).

## 12. Open questions

**Tactical** (decide during the leaf):

1. β, `_parse_event_windows`: narrow the try to the coercions, or let ConfigurationError pass through the handler. C2 pins the behaviour either way.
2. β, `cli/optimize.configs`: narrow the guard, or re-raise ConfigurationError ahead of the ValueError clause. C3 pins it.
3. γ: how to represent the two reason kinds (a small frozen dataclass or two mappings), and the wording of each Permanent contract. Key granularity is decided: (importing module, imported module).
4. α: the new test module's name. γ's file name is fixed, because the sidecar binds it.

**For the lead** (cross-stream; S1 is correct whichever way each goes):

1. **Non-numeric input refusals.** D9 has S4 convert every numeric refusal in a domain `__post_init__` to ConfigurationError. The non-numeric refusals in the same input types are unassigned: ~83 `raise ValueError` sites in 27 `__post_init__`s, minus the computed-result classes C4 excludes. Recommendation: S4 converts them in the same edits, and INV-1's test asserts the type. Until then, S17's translator logs a legitimate refusal such as `PVConfig`'s "Capacity must be positive" as non-domain, so S17 should either depend on S4 or accept that log noise.
2. **A key path as data?** If S4 or S5 want ConfigurationError to carry a key path as data (D9's "add the key path on the way up"), their leaf extends errors.py and depends on α. S1 ships the bare type, since no reader needs a field today.
3. **`ConfigurationError` in `__all__` at S29's bump.** It is optional. Consumers can import it from `solar_challenge.errors`, or catch ValueError.
4. **Task 177.** Cancel it as superseded by S1-α plus S5 when S1 files (§8). Otherwise it can be dispatched independently and move the class without D2's base, splitting config.py against S5's partition.
5. **Wave-1 streams that add input refusals below config.** S2's D3 refusal, S9's closed selector, S11's tiling invariant and S28's efficiency refusal should depend on α and raise `errors.ConfigurationError`. The alternative is ValueError, which S4 converts later. Today the program lists them with no upstream deps (§9).

## Gate record

- **G1:**
  - errors.py is consumed by config, finance, gridservices, the CLI and web importers, and S4, S5, S8 and S17.
  - The base class is consumed by S17's translator and the CLI boundary.
  - γ's guard is consumed by every stream that removes a deferred import (§9).
  - No orphan producer.
- **G3:** the substrate exists and is verified:
  - mypy --strict's explicit-export rejection (probed);
  - `tests/_cli_fleet_simulator.invoke_cli` for C3;
  - `finance run` refusing before any simulation (ran: exit 1 on `months: [13]`);
  - the subprocess sys.modules pattern in test_init_lazy_surface.py;
  - review/briefing.yaml's `conventions` list.
- **G4:** the S17 and S1 overlap on the web deletions is resolved to S17 (D-8). The proposed S2, S9, S11 and S28 dependencies are returned to the lead.
- **G5:** B + H: blast radius ≥ 3 modules, a load-bearing seam at both boundaries, ≥ 2 consuming streams.
- **G6:**
  - P2 is RED today (probed) and delivered by α itself.
  - C2's naive-subclass failure was probed; it is a characterisation pin, green before β and red against a naive β.
  - The mypy rejection mechanism was observed to fire.
  - INV-5's empty-allow-list premise was false and is corrected (§7).
- **G7** (advisory: the project has no design-invariants file; walked against dark-factory's trigger shapes):
  - `exceptions-owned-or-ratified`: every γ entry carries an owner or a contract.
  - `no-silent-fail-soft`: β removes the silent "skipped" the subclassing would create.
  - `contracts-machine-checked`: C4's rule is prose in one home, machine-checked for gridservices and flex by β and for numeric refusals by S4's INV-1.
  - `one-fact-one-home`: one class, one spelling, one docstring rule.
- **META:** decomposing this without further oversight yields one leaf error type below config. Both boundaries can catch it, no refusal changes wording by accident, the cycle and its prose are gone, and a guard keeps deferred imports owned. The remaining questions are cross-stream scoping for the lead and do not change S1's design.
