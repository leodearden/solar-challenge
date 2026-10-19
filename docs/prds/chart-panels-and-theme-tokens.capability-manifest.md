# Capability manifest — Results chart panels, theme tokens and chart facts (S21)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/chart-panels-and-theme-tokens.md`. Each asserted capability binds to one kind of evidence:

- a symbol that is wired on main (`grep:<file>::<symbol>`);
- a producer in this batch that runs upstream (`producer:<label>`);
- an out-of-batch producer wired as a dependency at decompose (`producer:task-<N>` or `producer:S19-γ`);
- a probe whose result was observed (`probe:`);
- an arithmetic identity (`identity:`).

The YAML twin `chart-panels-and-theme-tokens.capability-manifest.yaml` carries the mechanical `delivered_check`s.

**Code anchors** verified against main `9625529` (2026-10-15). The Tailwind probes ran in a scratch copy of `src/solar_challenge/web` after `npm ci` against the committed `package-lock.json` (tailwindcss 3.4.19). Anchors cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS, conditional on decompose wiring.** No binding resolves to `declared-only`, `test-only`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Four bindings name out-of-batch producers that are not yet edges. Each becomes a PASS when its edge is wired at decompose:

- S19 γ (not yet filed) for ζ and η;
- task 780 for δ;
- task 714 for δ and ε;
- tasks 691 and 736 for γ (serialisation only).

---

## α — theme token file; Tailwind and charts read it (intermediate; own signal)

| capability asserted | evidence | status |
|---|---|---|
| `tailwind.config.js` can `require` a JSON file and `tailwindcss/colors` | `probe:` scratch build with `require('./static/src/theme-tokens.json')` and `colors[tokens.tailwind.primary]` succeeded | PASS |
| B2: the rebuild is byte-identical with primary named, not copied | `probe:` `cmp` of the rebuilt and committed `static/dist/style.css`: identical, both for the committed config and for the token-reading config | PASS |
| `primary` today is a verbatim copy of built-in amber | `probe:` `require('tailwindcss/colors').amber[500]` is `#f59e0b`; `grep:tailwind.config.js` primary 500 `'#f59e0b'` with the comment "Copies Tailwind's built-in amber" | PASS |
| `COLOUR_PALETTE` keeps its role→hex shape, so `_ChartElement.colour` and the tests' recolouring fixture keep working | `grep:charts.py::COLOUR_PALETTE` (dict of role → hex); `grep:charts.py::_ChartElement.colour` reads `COLOUR_PALETTE[self.colour_role]` at call time | PASS |
| The neutral figure colours exist to be tokenised | `grep:charts.py::financial_breakdown` `font=dict(size=14, color="#888888")`; `grep:charts.py::sankey_diagram` `line=dict(color="black", width=0.5)` | PASS |
| The token file ships in the wheel | `grep:pyproject.toml` `[tool.setuptools.package-data] "solar_challenge.web" = [..., "static/**/*"]` | PASS |
| The css-build lane builds from the committed token file | `grep:tests/css_build/test_dist_style_css.py::_copy_web_package` copies the whole web package | PASS |
| B1 rejection: a role naming no hue, or a hue not `#rrggbb`, raises naming both | `producer:α` authors the loader's refusals and B1 observes them; precedent `grep:charts.py::_with_alpha` already refuses a non-`#rrggbb` colour by name | PASS |

## β — role palettes replace amber outside the accent (leaf)

| capability asserted | evidence | status |
|---|---|---|
| Nested role palettes compile to the same colours | `probe:` `status: {running: colors.amber}` produced `.bg-status-running-100{…rgb(254 243 199/…)}`, amber-100's value | PASS |
| The five amber roles exist where β edits them | `grep:` `assistant/chat.html` (banner), `components/macros.html::_run_status_badge_classes['running']`, `simulate/partials/progress-tracker.html` (`bg-amber-500`), `dashboard.html` (Run Single Home), `simulate/fleet.html` (PV card); these match `test_web_theme_colours.py::_AMBER_ROLES` | PASS |
| The battery and load cards use teal and red | `grep:simulate/fleet.html` `bg-teal-50`/`bg-teal-500` (battery), `bg-red-500` (load) | PASS |
| B2 rejection: an unknown palette name fails the build naming the role | `producer:β` adds the throw in `tailwind.config.js`. `colors['ambr']` is `undefined` (`probe:` the `tailwindcss/colors` export is a plain object of palettes), so without the throw Tailwind would silently drop the palette. The throw is the active mechanism, and B2 observes the non-zero exit | PASS |
| `_AMBER_ROLES`, its meta-tests and the regex premise exist to delete | `grep:tests/unit/test_web_theme_colours.py::_AMBER_ROLES`, `_AmberRole`, `_PRIMARY_500_ENTRY`; `grep:tests/unit/test_web_theme_palettes.py::_PALETTE` | PASS |
| Upstream token file and config | `producer:α` | PASS |

## γ — no colour outside the token file; chart chrome from computed style (leaf)

| capability asserted | evidence | status |
|---|---|---|
| chart-renderer.js holds the hexes being removed | `grep:static/js/chart-renderer.js::_darkOverrides`/`_lightOverrides` (`#1e293b`, `#e2e8f0`, `#334155`, `#ffffff`) | PASS |
| Arbitrary custom properties with `theme()` compile per theme | `probe:` `[--chart-grid:theme(colors.slate.200)]` gave `{--chart-grid:#e2e8f0}`, and `dark:[…slate.700…]` gave `:is(.dark *){--chart-grid:#334155}` | PASS |
| The figures already have transparent paper and plot backgrounds | `grep:charts.py::_SHARED_LAYOUT` `paper_bgcolor="rgba(0,0,0,0)"`, `plot_bgcolor="rgba(0,0,0,0)"` | PASS |
| Theme toggles reach the renderer | `grep:chart-renderer.js` `document.addEventListener('theme-changed', …)`; `grep:partials/theme-toggle.html` dispatches `theme-changed` | PASS |
| B6: the theme reaches secondary axes, zero lines and the polar disc | `producer:γ` applies chrome to every `xaxis*`/`yaxis*`/`polar*` key. Today's gap is measured in tasks 735 (secondary y grid, zero lines) and 737 (polar disc rgb(229, 236, 246)), whose measurements become B6's postconditions | PASS |
| The legibility and dark-mode e2e checks exist | `grep:tests/e2e/test_compare_page.py::test_compare_chart_titles_and_legends_are_legible`; `grep:tests/e2e/test_dark_mode_pages.py::test_dark_mode_results_page_charts` | PASS |
| The Chart.js path is dead | `grep:static/js/parameter-sweep.js::_renderChart` returns at `typeof Chart === 'undefined'`; no template or `static/vendor` file loads Chart.js; `#sweep-chart` is a `<div>` | PASS |
| B5: the scan finds hexes only in the token file once α and γ land | identity: hexes today are in `charts.py` (8), `tailwind.config.js` (10), `chart-renderer.js` (10) and `parameter-sweep.js` (2), and none in templates or `static/style.css` (`git grep -E '#[0-9a-fA-F]{6}'`). α removes the first two, γ the last two | PASS |
| Serialisation with in-flight renderer edits | `producer:task-691` (in progress), `producer:task-736` (pending), upstream at decompose | PASS (edge at decompose) |

## δ — chart panels: one typed description per chart, tabs as data, named absences (leaf; high)

| capability asserted | evidence | status |
|---|---|---|
| `chart_panel` writes the id once with `data-chart-figure`, and chart-renderer.js draws such containers | `grep:components/macros.html::chart_panel`; `grep:chart-renderer.js` `querySelectorAll('[data-chart-figure]')` (tasks 637, 674) | PASS |
| The three-state convention exists to remove | `grep:charts.py::sankey_diagram`/`sweep_parameter_chart` `return "{}"`; `monthly_summary`/`seasonal_comparison`/`heat_pump_analysis` return `None`; `grep:macros.html::chart_panel` `figure != '{}'` | PASS |
| The 90/180 gates read `results.window.days` | `producer:task-780` (S10 γ2), upstream at decompose; its delivered check makes `.days + 1` absent from `web/charts.py` | PASS (edge at decompose) |
| B7: the 2024-10-01..11-30 window is 61 days | `producer:task-777` via 780: S10 B1's probe gives 61 (a timedelta gives 62) | PASS |
| The stored home run carries the `HomeConfig` the assembler needs | `grep:routes.py::home_results` `config, sim_results, summary = storage.load_home_run(run_id)` | PASS |
| The compare page swallows chart errors and imports charts in-function | `grep:history.py::compare_page` `try: from solar_challenge.web.charts import …` with `except Exception: logger.warning(...)`; `grep:routes.py` `# noqa: PLC0415` ×3 | PASS |
| The tab bars and Plotly tags exist to replace | `grep:` the active class pair `border-primary-500 text-primary-600 dark:text-primary-400` in `results/home.html` (4), `results/fleet.html` (3) and `history/compare.html` (2); `cdn.plot.ly/plotly-2.27.0` in the same three templates | PASS |
| B8 rejection: `ChartPanel` refuses `"{}"`, a bad id, height ≤ 0 and a blank reason | `producer:δ` authors `__post_init__`, and B8 observes each refusal | PASS |
| The financial line is renamed first | `producer:task-714` (in progress) | PASS (edge at decompose) |
| `overlaid_power_flows` is deleted first | `producer:task-752` (pending) | PASS (edge at decompose) |

## ε — chart facts from the run (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `battery_charge = pv charge + grid charge` per step | `grep:flow.py::simulate_timestep` `battery_charge_kwh = pv_charge_stored_kwh + grid_charge_stored_kwh` | PASS |
| Self-consumption counts battery discharge | `grep:flow.py::simulate_timestep` `self_consumption_kwh = min(direct_consumption_kwh + battery_discharge_kwh, demand_kwh)` | PASS |
| `total_pv_charge_kwh` and `total_grid_to_demand_kwh` are ≥ 0 by construction | `grep:home.py::SummaryStatistics.__post_init__` refuses grid charge outside [0, battery charge] and above grid import | PASS |
| `total_direct_self_consumption_kwh` is exact while discharge ≤ shortfall | identity: self − discharge = direct when `direct + discharge ≤ demand`, i.e. discharge ≤ shortfall. The leaf asserts the identity against the summary's fields, not a literal | PASS |
| The pricing facts are in the stored config | `grep:home.py::HomeConfig` `tariff_config: Optional[TariffConfig]`, `seg_tariff: Optional[SEGTariff]`; `grep:home.py::simulate_home` writes a zero `tariff_rate` and warns when `tariff_config` is set without `seg_tariff` | PASS |
| `SummaryStatistics` is pinned by the frozen-surface test, so additive members land in-leaf | `grep:tests/unit/test_public_api_surface.py` `"SummaryStatistics": "dataclass[eq] (…)"`; D29; precedent task 469 | PASS |
| `SimulationResults`' docstring misstates self-consumption | `grep:home.py::SimulationResults` docstring "self_consumption: Direct PV consumption in kW" | PASS |
| B10's arbitrage scenario exists | `grep:scenarios/bristol-arbitrage.yaml`; `grep:tests/_synthetic_weather.py::synthetic_june_weather`. The literal 0.0288 / 2.1085 kWh is task 492's measurement at 2544e06 and is illustrative only; B10 asserts identities | PASS |
| Upstream panels and the renamed financial line | `producer:δ`, `producer:task-714` | PASS |

## ζ — typed comparison (leaf)

| capability asserted | evidence | status |
|---|---|---|
| `RunRecord.summary()` and `RunHeadline`/`run_headline` | `producer:S19-γ` (`docs/prds/run-store-one-owner.md` §3.4, D-S19-8: "S21's comparison consumes it (and may widen `RunHeadline`)") | PASS (edge at decompose) |
| `FleetSummary` has the five totals and the two fleet ratios, but no export ratio and no battery totals | `grep:fleet.py::FleetSummary` (`total_*_kwh`, `fleet_self_consumption_ratio`, `fleet_grid_dependency_ratio`) | PASS |
| B11: the fleet radar shows 25 % and 60 % | identity: per home, generation = self + export = 72 and demand = self + import = 45, so 18/72 = 0.25 and 27/45 = 0.6. Task 565 measured `decoded_summary()` giving 0.25 and 0.6 for `make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)` | PASS |
| B11: the radar draws 0 today | `grep:charts.py::comparison_radar` `summary.get("self_consumption_ratio", 0)`; task 565's measured r `[0, 0, 0, 0.0, 0]` | PASS |
| The PV-stored share reads ε's property | `producer:ε` | PASS |
| An unreadable stored summary is refused | `producer:S19-γ`/κ `StoredRunUnreadable`, which pages flash (D-S19-9) | PASS (edge at decompose) |

## η — the sweep chart, drawn from the sweep's runs (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The page knows each finished point's run id | `grep:static/js/parameter-sweep.js::_followPoint` reads `data.run_id` from the `complete` event | PASS |
| Each point's summary is readable by run id | `producer:S19-γ` `RunRecord.summary()` | PASS (edge at decompose) |
| `sweep_parameter_chart` exists, unwired, with its optimum at the max | `grep:charts.py::sweep_parameter_chart` `best_idx = max(...)`; no caller in `src` | PASS |
| The page blueprint can take a POST route | `grep:scenarios.py` `bp = Blueprint(...)` serves `/scenarios/sweep` | PASS |
| Late containers are drawn | `producer:η` adds a `MutationObserver` to chart-renderer.js; the e2e half of B12 observes it | PASS |
| The renderer and the empty card are already reworked | `producer:γ`, `producer:δ` (`chart_panel(panel)`, `chart_scripts`) | PASS |
| B12 rejection: an unknown run id answers 400 naming it | `producer:η` authors it and B12 observes it | PASS |

## θ — one card macro (leaf)

| capability asserted | evidence | status |
|---|---|---|
| The triple has 16 copies, 13 outside `macros.html` | `grep:` `git grep -c -F 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm'` gives `dashboard.html` 3, `simulate/fleet.html` 7, `results/home.html` 1, `results/fleet.html` 1, `history/compare.html` 1, `components/macros.html` 3 | PASS |
| `card` is called once | `grep:dashboard.html` `{% call card(title="Recent Runs", …) %}` | PASS |
| The macro-import guard exists | `grep:tests/unit/test_web_template_macros.py::test_templates_import_exactly_the_library_macros_they_call` | PASS |
| Upstream template edits | `producer:β` (dashboard, fleet), `producer:δ` (results, compare, `chart_panel`) | PASS |

## Acceptance — fk-657669b23e71

No capability is asserted. Ruled R4 (Leo, 2026-10-15). Filed `cancelled` with `x_acceptance_reason`. It has no sidecar block, because it is not a producer.
