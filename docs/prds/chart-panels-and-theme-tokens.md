# Results chart panels, theme tokens and chart facts

**Status:** authored 2026-10-15 (program `review-all-solar_challenge-20261013`, stream S21, wave 1, no upstream streams), committed in `0fcef8b`. Decomposed and filed 2026-10-16: α 829, β 830, γ 831, δ 832 (high; a dependency of trigger-chain gate 772), ε 833, ζ 834, η 835, θ 836, and fk-657669b23e71 accepted as cancelled task 840 (D40). Session rulings R1-R4 are D37-D40. The lead ruled Q1-Q6 in L17: the supersessions were applied, δ depends on 454 now that esc-454-3 is closed, and the 691/736 edges stay. Contract first (B + H).

**Code anchors** verified against main `9625529` (2026-10-15). Main moves fast: cite by symbol and re-locate lines at implementation time. The findings record's anchors are at `7dfea36`, and tasks 637 and 674 have since moved every chart page onto `chart_panel` (§Background, re-measurement).

## Goal

Each chart a dashboard page shows is described once, as a typed `ChartPanel`. The panel holds the chart's figure, or a named reason it has nothing to draw. Every colour the dashboard draws has one home, `static/src/theme-tokens.json`, and the facts a chart draws are read from the run, not reconstructed beside it.

What a user sees when this lands:

- The results page of a 61-day run (2024-10-01..11-30) shows a Monthly Summary card that says "The monthly summary needs at least 90 days; this run covers 61." Today the card is missing with no word of why. The seasonal card names 180 days and the run's 61. Today its message is a template literal that never states the run's length.
- The run-comparison radar draws a fleet run at its real 25 % self-consumption and 60 % grid dependency. Today it draws 0 % on every axis. The battery axis says what it plots, "PV stored in battery %". It leaves out grid-charged energy, so the Bristol arbitrage home reads about 0.1 % where today it reads about 7 %. When a fleet run is compared, the axis is left out with a note naming that run.
- A finished parameter sweep draws its charts: generation, self-consumption and grid import against the swept value. Each marks its best point by that metric's direction, so the grid-import chart marks the lowest. Today the sweep page shows an empty card.
- In dark mode, every chart's axes, secondary axes, zero lines and the radar's polar disc follow the theme. Today the radar's disc stays light and the financial chart's secondary grid stays white (tasks 735, 737).
- Visually, nothing else changes. Colours, card shapes and tabs look as they do today. The compare page's tabs gain the `role="tab"` and `aria-selected` that the results pages' tabs already have.

What an agent sees: one JSON file to edit for any colour, and one `ChartPanel` per chart that holds its id, title, height and figure or absence reason. There are no `'{}'` sentinels, no `amber-*` allow-list and no hex literal outside the token file.

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says | where it goes |
|---|---|---|---|
| fk-42c0053b9a2b | high / confirmed | Each chart is described in four places, with a three-state "nothing to draw" string convention (`'{}'`, `None`, JSON). | δ |
| fk-93ee9a05751a | medium / confirmed | Colour is defined in five places that tests keep reconciled. Primary copies amber, so accent and status share classes. | α, β, γ |
| fk-8e109704aa24 | medium / confirmed | Sankey and radar reconstruct the battery's PV/grid split. The financial note infers pricing from series. | ε, ζ |
| fk-3239afd8ce6b | medium / confirmed | The comparison charts read `dict.get(key, 0)` over decoded JSON, so a fleet run draws zeros. Chart errors are swallowed. | δ (except, imports), ζ (types) |
| fk-8f26d000b68d | medium / confirmed | compare.html drew with `Plotly.newPlot` outside chart-renderer.js. | done by task 674. δ carries the remnant: compare tabs lack `role=tab`/`aria-selected` |
| fk-ff5b90768f66 | medium / confirmed | Card and tab structures are copied instead of routed through macros. | δ (tab bar), θ (card) |
| fk-2e7ddcee2379 | low / weakened | `tests/_css_classes.py` and its guards pin source text. | β (re-measured below) |
| fk-657669b23e71 | low / weakened | style.css drift is caught only post-merge. | accepted (session ruling R4) |
| fk-ce345e3b013d | medium / confirmed | financial_breakdown's "Cumulative Net Savings" is not a saving. | task 714 (in progress); not refiled |
| fk-55f4e4ea396d | medium / confirmed | The sweep chart never draws: a Chart.js path with no Chart.js, and an uncalled Plotly builder whose optimum is the max. | γ (dead path), η (chart) |
| fk-02500b87f3cb | low / confirmed | `overlaid_power_flows` has 0 callers. | task 752 (pending); not refiled |

Rulings that bind this PRD:

- **D22.** A JSON token file under `static/src` is read by `tailwind.config.js` and loaded by `charts.py`. The css-build lane job guards the Tailwind side.
- **D26.** Accepted block and loose-finding assignment. S21's keys are as the program lists them.
- **D29.** Additive frozen-table edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line. Only renames and retirements wait for S29. S21 renames and retires nothing on the frozen surface, so it has no held leaf.
- **D12** (via S10). Charts' 90- and 180-day gates stay display gates. S10 γ2 (task 780) makes them read `results.window.days`, and this stream turns their `None` into named reasons (program cross-reference).
- **D33** (via S19). No sweep run type and no `sweep_id`: a sweep is its points' runs.
- **D28.** Weakened findings are re-measured before decomposing (below).

Session rulings (Leo, 2026-10-15, this /prd session; the lead numbers them):

- **R1 Token scope: role palettes.** The token file names the accent and every UI role that reuses amber today: warning banner, "running" run status, PV component card. Each is a built-in Tailwind palette *name*. The file also holds the chart hues and roles. Templates switch `amber-*` to `primary-*` or role classes with no visual change. `_AMBER_ROLES` and its meta-tests are deleted.
- **R2 Sweep chart: drawn server-side.** `sweep_parameter_chart` is kept and wired, with the optimum chosen by each metric's direction. The Chart.js path is deleted.
- **R3 Chart chrome from computed style.** chart-renderer.js holds no colour. It reads text and grid colours from the computed style of the chart's container, whose classes name theme colours. The figure background stays transparent, so the card shows through.
- **R4 fk-657669b23e71 accepted.** It is filed as a cancelled task with `x_acceptance_reason`.

### Re-measurement at `9625529`

The anchors moved after the review pin. Tasks 637 and 674 landed `components/macros.html::chart_panel(id, title, figure, min_height, empty_message='')`. It writes each chart's id once on a container that carries `data-chart-figure`, and `static/js/chart-renderer.js` draws each such container once it is shown. All three chart pages use it. So:

- `!= '{}'` guards: 1, in `chart_panel` (12 at the pin). `'{}'` returns: 2 (`sankey_diagram`, `sweep_parameter_chart`). `None` returns: 3 (`monthly_summary`, `seasonal_comparison`, `heat_pump_analysis`), plus the route's `None` for a battery-less run's SOC chart.
- Direct `Plotly.newPlot` in templates: 0 (2 at the pin). `test_no_dashboard_source_but_chart_renderer_js_calls_plotly` guards it.
- Still repeated: titles and heights (the template's `chart_panel` call and the builder's `update_layout` disagree on 4 of 16 titles, e.g. "Monthly Summary" vs "Monthly Energy Summary"). Also repeated: the route's dict keyed by chart name, the template-literal absence message ("Seasonal comparison requires at least 180 days…"), the Plotly CDN tag in 3 templates, and the tab-button class pair (10 copies; compare's 2 lack `role`/`aria-selected`).
- Card class triple (`bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm`): 16 exact copies (32 at the pin). 3 are in `macros.html` (`card`, `stat_card`, `chart_panel`). The other 13 are in `dashboard.html` (3), `simulate/fleet.html` (7), `results/home.html`, `results/fleet.html` and `history/compare.html` (1 each). `card()` is called once.
- Hex colour literals in web sources: `charts.py` 8, `tailwind.config.js` 10, `chart-renderer.js` 10, `parameter-sweep.js` 2. There are none in templates or `static/style.css`.
- Amber outside the accent: 5 roles, the ones `_AMBER_ROLES` lists. They are the `assistant/chat.html` warning banner, the `macros.html` "running" badge, the `progress-tracker.html` bar, the `dashboard.html` Run Single Home card and the `simulate/fleet.html` PV card. The battery and load cards of the same family use teal and red.

**fk-2e7ddcee2379 (weakened), re-measured.** `tests/_css_classes.py` is still 448 lines, but most of it serves invariants this stream does not touch: compiled-CSS coverage, hand-written CSS pruning and inline styles. The part that exists only because primary copies amber is in `tests/unit/test_web_theme_colours.py`, about 230 of its 316 lines: `_AMBER_ROLES`, `_AmberRole`, five meta-tests and the regex premise check `_PRIMARY_500_ENTRY`. A further part is `test_web_theme_palettes.py`'s regex `_PALETTE` over `tailwind.config.js`. `tests/_html_page.py` went from 340 to 276 lines when task 637 deleted its renderChart readers. The skeptic's weakening stands: "most of `_css_classes.py`" is not deletable. β deletes the amber machinery and the two config regexes, and records this measurement on the task.

**fk-657669b23e71 (weakened), re-measured.** Since the css-build lane started (task 222, 2026-10-05), it has filed 2 reds (626 done, 634 cancelled), and none since the review pin. The per-task sandbox cannot reach npm. Ruled R4: accepted.

**G3 probes (scratch copy of the web package, `npm ci` against the committed `package-lock.json`, tailwindcss 3.4.19):**

- The committed tree rebuilds byte-identical to `static/dist/style.css`.
- A `tailwind.config.js` holding no hex is byte-identical too. It does `require('./static/src/theme-tokens.json')` and sets `primary: colors[tokens.tailwind.primary]` from `require('tailwindcss/colors')`.
- A nested role palette compiles: `status: {running: colors.amber}` gives `.bg-status-running-100{…rgb(254 243 199…)}`, which is amber-100's value.
- An arbitrary custom property with `theme()` compiles: `[--chart-grid:theme(colors.slate.200)] dark:[--chart-grid:theme(colors.slate.700)]` gives `--chart-grid:#e2e8f0` and, under `.dark`, `#334155`.
- `pyproject.toml`'s package data `static/**/*` ships `static/src/theme-tokens.json` in the wheel. The css-build lane copies the whole web package, so it builds from the token file as committed.

## Sketch of approach

**One colour table (α, β, γ; D22, R1, R3).** `static/src/theme-tokens.json` has two sections:

- `tailwind` names built-in Tailwind palettes for the accent and each UI role. `tailwind.config.js` resolves them through `tailwindcss/colors` and refuses an unknown name at build time, naming the role.
- `chart` holds the chart hues as `#rrggbb` and the chart roles as hue names. `charts.py` loads it into `COLOUR_PALETTE` (role → hex, the shape it has today) and refuses at import a role naming no hue, or a hue not written `#rrggbb`, naming both.

`chart-renderer.js` takes text and grid colours from the computed style of the chart's container, and the container's classes name theme colours. So no script, template, stylesheet or Python module writes a hex. One test says so, over every web source.

**One description per chart (δ).** Every chart builder returns a frozen `ChartPanel(dom_id, title, height_px, content)`, where `content` is the figure JSON or a `ChartAbsence(reason)`. One helper writes the panel's title and height into the figure, so each lives once. Page assemblers return `ChartTab`s:

- `home_results_tabs(config, results, summary)`
- `fleet_results_tabs(fleet, home_summaries)`
- `comparison_tabs(...)`

A chart that does not apply to the run is not listed: no battery, no heat-pump load. A chart that applies but has nothing to draw is listed with its reason. That is the whole emptiness rule. The routes pass the tabs. `components/macros.html::chart_tabs(tabs)` renders one tab bar (`tab_bar`, with `role=tablist/tab` and `aria-selected`) and each tab's panels through `chart_panel(panel)`. One `chart_scripts()` macro loads Plotly and chart-renderer.js on every chart page.

**Facts from the run (ε, ζ).** `SummaryStatistics` gains three read-only properties beside its grid-charge invariant: `total_pv_charge_kwh`, `total_direct_self_consumption_kwh` and `total_grid_to_demand_kwh`. The Sankey and the comparison radar read them. The financial chart's unpriced note reads the run's own `HomeConfig.tariff_config` and `seg_tariff`, so it no longer infers pricing from the rate series. The comparison charts take typed runs built from S19's `RunRecord.summary()`. Their fleet-name mapping is S19's `run_headline`, widened here (D-S19-8), so there is no second mapping.

**The sweep chart (η, R2).** When every point has finished, the sweep page posts its points' run ids and values. The server builds one panel per `SweepMetric` from the runs' stored summaries and returns the `chart_panel` HTML. chart-renderer.js draws containers that appear after load.

**One card (θ).** Every card is rendered by `card` or a macro built on it, so the card class triple lives once.

Heuristics served: 11 (SPOT: colours, chart descriptions, flow identities, cards), 12 (a typed panel and a typed comparison input instead of `'{}'` strings and `dict.get`), 10 (refusals at construction: panel, tokens, Tailwind build; no swallowed chart errors), 9 (a deep `ChartPanel`/`chart_tabs` interface; the orphan sweep builder wired), 1 (the radar axis and the Sankey links say what they plot), 3 (accent, UI roles and chart hues as separate dimensions).

## Resolved design decisions

1. **Builders return panels; pages assemble tabs.** The builder knows the chart's title, height and absence rule, so it constructs the `ChartPanel`. The page assembler decides only which charts apply to a run and how they group into tabs. The alternative is a route-side dict of raw figures plus a template that knows titles. It keeps four homes per chart, which is the finding.
2. **Not applicable vs absent.** A chart whose subject the run lacks (no battery, no heat-pump load) is omitted by the assembler. A chart that applies but cannot draw is listed with a `ChartAbsence` whose reason names the rule and the run's value. So every absence a user sees explains itself, and no card appears for a thing the run does not have. The absence reasons are:
   - monthly under 90 days and seasonal under 180, both reading `results.window.days` from S10 γ2;
   - a Sankey with no flow above 0.01 kWh;
   - a sweep with fewer than two finished points.
3. **`ChartPanel` refuses what the old convention allowed.** `__post_init__` refuses a `dom_id` not matching `^chart-[a-z0-9-]+$`, a blank title, a height ≤ 0, a figure string that is blank or `{}`, and a blank reason. The `{}` sentinel cannot be constructed.
4. **Title and height have one value.** The panel helper writes `title` and `height_px` into the figure's layout, and `chart_panel` renders the same title as the card heading and the same height as the container's `min-height`. The figure keeps its title, so a chart downloaded from Plotly's modebar still names itself. Where builder and template disagree today, the builder's title is kept.
5. **Tabs are data.** `ChartTab(key, label, panels)` comes from the assembler, and `chart_tabs` renders the tab bar through `tab_bar`. That gives one place for `role=tab`, `aria-selected` and the active/inactive classes. The results and compare pages lose their hand-written tab markup. `simulate/home.html`'s Alpine-driven tab loop uses `tab_bar`'s classes if it can take an Alpine list (tactical, θ).
6. **One token file, two readers, no references across sections.** The `tailwind` section names built-in palettes: `primary` and `warning`, plus `status.{running,completed,failed}` and `component.{pv,battery,load}`. These resolve to amber, green, red and teal exactly as today, so the compiled colours are unchanged (probe). The `chart` section's hues are `#rrggbb` and its roles map to hues. The chart amber (`#f5a623`) stays distinct from primary-500 (`#f59e0b`): series encoding and UI accent are different dimensions (heuristic 3), and this keeps every chart's look. The neutral figure colours, the unpriced-note grey and the Sankey node outline, become chart roles, so the "only the token file writes a colour" rule has no exception.
7. **The Run Single Home quick action is the accent.** It is the dashboard's lead action, drawn in amber because amber is the accent. It moves to `primary-*`, a visual no-op (R1). The Fleet and Build Scenario actions keep their sky and emerald.
8. **Chrome from the page, not a second channel (R3).** `chart_panel`'s container carries `text-*` classes and `[--chart-grid:theme(...)]` custom properties for light and dark. chart-renderer.js reads `getComputedStyle(container).color` and `--chart-grid` at draw time and on `theme-changed`. It applies them to every axis the figure's layout has: `xaxis*`, `yaxis*` (secondary axes included), their zero lines, and `polar*` with its radial and angular axes and disc. Paper and plot backgrounds stay transparent as `charts._SHARED_LAYOUT` sets them, so the card colour shows through. This realises D22's "chart-renderer.js reads the tokens" through the compiled theme. The lead may want the program's seam row worded to match (§Open questions Q6).
9. **The flow identities live on `SummaryStatistics`.** The identities depend on the engine's definitions: `flow.simulate_timestep` makes `battery_charge = pv + grid` and counts discharge in self-consumption. So they live beside the type's grid-charge invariant, not in a web module:
   - `total_pv_charge_kwh = total_battery_charge_kwh − total_grid_charge_kwh`;
   - `total_direct_self_consumption_kwh = total_self_consumption_kwh − total_battery_discharge_kwh`;
   - `total_grid_to_demand_kwh = total_grid_import_kwh − total_grid_charge_kwh`.

   The first and third are ≥ 0 by `__post_init__`'s existing check. The second is exact while discharge never exceeds the step's shortfall, which S3's `DispatchDecision` bound makes a construction invariant. The properties are additive frozen-surface members (D29, in-leaf). `SimulationResults`' docstring "self_consumption: Direct PV consumption" is corrected in the same leaf.
10. **The financial note reads the run's configuration.** `HomeConfig.tariff_config` and `seg_tariff` are stored with every home run, so the note is a lookup. The rules:
    - no tariff and no SEG: "No tariff configured — cost and revenue tracking unavailable";
    - SEG only: "No import tariff configured — cost tracking unavailable";
    - a tariff: no note, as today.

    The "cannot tell an SEG run that exported nothing" caveat and the series inference go. No engine field and no stored-format change are needed. The SOC chart keeps reading the limits from `Battery(battery_config)`, the authority on SoH-derated limits. The route's double `has_battery` guard goes, because the assembler decides applicability once.
11. **Comparison input is S19's headline, widened.** D-S19-8 makes `storage.run_headline` the one place the web maps `FleetSummary` names. ζ widens `RunHeadline` with the five energy totals and three ratios, plus `pv_stored_share: float | None`. Export ratio for a fleet is `total_grid_export_kwh / total_generation_kwh`. The PV stored share is None for a fleet run, because `FleetSummary` carries no battery totals. The radar draws the axes every compared run has, and when one is left out the panel's figure carries a note naming the run and the metric. Mixed home and fleet comparisons are allowed.
12. **Chart errors are not swallowed.** `history.compare_page`'s broad `except Exception` and the function-local chart imports in `routes.py` and `history.py` go. This is the position of task 454, whose architect measured plotly at 1.4–5.4 % of app import. An unreadable stored summary is S19's `StoredRunUnreadable` (flash and redirect). Task 153's "keep the charts deferral" item is superseded (cross-reference). If 775 (S1's import-structure test) has landed, δ deletes the `web.routes → web.charts` and `web.history → web.charts` allow-list entries in the same change.
13. **The sweep chart is server-built and posted, not encoded in a URL.** `POST /scenarios/sweep/chart` takes JSON `{parameter_label, points: [{value, run_id}]}` and answers the HTML of the sweep panels, rendered by `chart_panel`. It loads each point's summary through S19's `RunRecord.summary()`, and refuses a missing or non-home run with 400 naming the run id. A `SweepMetric` enum carries each metric's label, its summary reader and its direction (`higher` or `lower` is better). Its members are generation, self-consumption ratio and grid import, and `sweep_parameter_chart` marks the best point by that direction. The swept values come from the page that submitted them. S26's knob registry may later read them back from the runs (cross-reference). chart-renderer.js observes the document for containers added or re-filled after load (`MutationObserver` on `data-chart-figure`), so the sweep page needs no renderer API.
14. **One Plotly loader.** `components/macros.html::chart_scripts()` emits the Plotly CDN tag and chart-renderer.js. Every chart page calls it, including the sweep page. This supersedes task 129. Vendoring Plotly (task 250) then edits one place.
15. **Card structure has one home (θ).** The card triple is written only in `macros.html`. `stat_card` and `chart_panel` are built on `card`, and each page card is a `card` call. The macro gains whatever header and body parameters the 13 sites need (coloured header bands, padding) without restating the triple. A source test refuses the triple outside `macros.html`. A source grep is the right check because the fact guarded is where the class string is written.
16. **No surface bump.** The only frozen-surface change is three additive `SummaryStatistics` properties (D29: `FROZEN_MEMBERS` entries plus an "Unreleased on main" line in ε). `RunHeadline`, `ChartPanel` and the token file are web-internal.

## Contract (seams: theme tokens and `ChartPanel`; owner this PRD)

```jsonc
// src/solar_challenge/web/static/src/theme-tokens.json  (JSON; comments here only)
{
  "tailwind": {                                  // read by tailwind.config.js only
    "primary": "amber",                          // α
    "warning": "amber",                          // β
    "status":    {"running": "amber", "completed": "green", "failed": "red"},   // β
    "component": {"pv": "amber", "battery": "teal", "load": "red"}              // β
  },
  "chart": {                                     // read by charts.py only
    "hues":  {"amber": "#f5a623", "red": "#d0021b", "green": "#7ed321", "blue": "#4a90e2",
              "purple": "#9013fe", "grey": "#9b9b9b", "teal": "#50e3c2",
              "mid_grey": "#888888", "black": "#000000"},
    "roles": {"pv_generation": "amber", "demand": "red", "...": "...",          // today's 18 roles
              "unpriced_note": "mid_grey", "sankey_node_outline": "black"}
  }
}
```

```js
// src/solar_challenge/web/tailwind.config.js
const colors = require('tailwindcss/colors');
const tokens = require('./static/src/theme-tokens.json');
// builtIn(role, name): colors[name], or throw Error naming the role and the name.
// theme.extend.colors: primary, warning, status.<s>, component.<c> from tokens.tailwind; no hex literal.
```

```python
# src/solar_challenge/web/charts.py
COLOUR_PALETTE: Mapping[str, str]        # role -> "#rrggbb", loaded from theme-tokens.json at import;
                                         # ValueError naming the role and hue (missing hue) or the hue and value (not #rrggbb)

@dataclass(frozen=True)
class ChartAbsence:
    reason: str                          # one sentence naming the rule and the run's value; non-blank

@dataclass(frozen=True)
class ChartPanel:
    dom_id: str                          # ^chart-[a-z0-9-]+$
    title: str                           # the card heading and the figure's layout title
    height_px: int                       # > 0: the figure's layout height and the container's min-height
    content: str | ChartAbsence          # Plotly figure JSON (never "{}") or why there is none
    # __post_init__: ValueError naming the field and value for each refusal in decision 3

@dataclass(frozen=True)
class ChartTab:
    key: str                             # the Alpine activeTab value, ^[a-z_]+$
    label: str
    panels: tuple[ChartPanel, ...]       # non-empty

def home_results_tabs(config: HomeConfig, results: SimulationResults, summary: SummaryStatistics) -> tuple[ChartTab, ...]: ...
def fleet_results_tabs(fleet: FleetResults, home_summaries: Sequence[SummaryStatistics]) -> tuple[ChartTab, ...]: ...
def comparison_tabs(runs: Sequence[ComparedRun]) -> tuple[ChartTab, ...]: ...          # ζ's input type; δ keeps today's inputs
class SweepMetric(Enum): ...             # label, summary reader, direction ('higher' | 'lower')   (η)
def sweep_panels(parameter_label: str, points: Sequence[SweepPoint]) -> tuple[ChartPanel, ...]: ...  # (η)

# src/solar_challenge/home.py  (ε; additive frozen members)
class SummaryStatistics:
    @property
    def total_pv_charge_kwh(self) -> float: ...                 # battery charge less grid charge
    @property
    def total_direct_self_consumption_kwh(self) -> float: ...   # self-consumption less battery discharge
    @property
    def total_grid_to_demand_kwh(self) -> float: ...            # grid import less grid charge

# src/solar_challenge/web/storage.py  (ζ widens S19 γ's type; S19 owns the name and the mapping)
@dataclass(frozen=True)
class RunHeadline:
    generation_kwh: float; demand_kwh: float; self_consumption_kwh: float
    grid_import_kwh: float; grid_export_kwh: float
    self_consumption_ratio: float; grid_dependency_ratio: float; export_ratio: float
    pv_stored_share: float | None        # total_pv_charge_kwh / generation; None for a fleet run
```

```jinja
{# src/solar_challenge/web/templates/components/macros.html #}
{% macro card(title='', subtitle='', ...) %}     {# the one home of the card class triple (θ) #}
{% macro chart_panel(panel) %}                   {# a card titled panel.title; a container with panel.dom_id, min-height panel.height_px
                                                    and data-chart-figure, its classes naming the chart chrome (γ); or the reason.
                                                    An undefined panel fails the render naming it, as chart_panel does today #}
{% macro tab_bar(tabs, model='activeTab') %}     {# role=tablist/tab, aria-selected, the active/inactive class pair once #}
{% macro chart_tabs(tabs) %}                     {# tab_bar + one x-show panel list per tab #}
{% macro chart_scripts() %}                      {# the Plotly CDN tag and chart-renderer.js, once #}
```

```text
POST /scenarios/sweep/chart     (η)
  body   {"parameter_label": str, "points": [{"value": number, "run_id": str}, ...]}
  200    text/html: the sweep panels, each through chart_panel
  400    {"error": ...} naming a run id that is unknown, not a home run, or has no summary
```

Invariants and where each is enforced:

| invariant | construction | use |
|---|---|---|
| Every colour the dashboard writes lives in `theme-tokens.json`. | the file; `charts.py` load refusal; `tailwind.config.js` throw; `build-favicon.js`'s refusal of a theme without primary-500 | a test scanning every web source (`.py`, `.html`, `.js`, hand-written `.css`, and the package root's `tailwind.config.js` and `build-favicon.js`) for `#rrggbb` finds only the token file (γ); `static/dist`'s `style.css` and `favicon.svg` (task 993) are build outputs, which the css-build lane compares with a fresh build |
| The accent is the only use of the accent's palette. | `tailwind.primary` names it | a test: no template or script applies a class naming the palette `tailwind.primary` names (β) |
| Every token role is drawn. | — | every `tailwind` role palette is applied by some template (β); every chart role is drawn by some figure (`test_web_chart_colours`, α) |
| A chart that applies is drawn or says why not. | `ChartPanel.__post_init__` | assemblers list only applicable charts; `chart_panel` renders the figure or the reason (δ) |
| A chart's id, title and height live once. | `ChartPanel` | the panel helper writes title/height into the figure; the template reads only the panel (δ) |
| The battery's PV/grid split has one home. | `SummaryStatistics.__post_init__` (grid charge ≤ charge, ≤ import) | Sankey and radar read the properties (ε, ζ) |
| A fleet summary's names are mapped once. | `storage.run_headline` (S19) | the comparison charts read `RunHeadline` (ζ) |
| Each card is the card macro. | `card` | a source test: the triple appears only in `macros.html` (θ) |

Downstream readers and their seam lines:

- **S19 ε** moves the results routes into one `/results/<run_id>` with a `match` on the stored-run variant. Each arm calls `home_results_tabs(stored.config, stored.results, stored.summary)` or `fleet_results_tabs(stored.fleet_results, stored.home_summaries)`. Whichever of δ and S19 ε lands second adapts the call.
- **S12** replaces the heat-pump panels' applicability (`results.heat_pump_load is not None`) and their figures with panels built per named load series. It adds builders that return `ChartPanel`. It does not touch the panel type.
- **S20** decides whether `queued` and `cancelled` get their own `status.*` colour when its job-state table lands. Adding a key to `tailwind.status` is one edit.

## Boundary-test sketch (both sides of each seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Token load | the committed token file; a copy whose role names a missing hue; a copy with hue `#f5a62` | `COLOUR_PALETTE` equals today's 18 role colours plus the two neutral roles. The copies raise `ValueError` naming the role and hue, and the hue and value | α |
| B2 | Tailwind reads the tokens | scratch web package, `npm ci`, `npm run build:css` | style.css byte-identical to the committed file (α). With `tailwind.status.running` = `"ambr"`, the build exits non-zero naming `status.running` and `ambr` (β) | α, β |
| B3 | A hue edit reaches every role that names it | the token file with hue `amber` recoloured, through the test's palette fixture | `pv_generation`, `summer` and `comparison_run_1` figures draw the new colour; no figure draws `#f5a623` | α |
| B4 | Role palettes render as before | Flask client: History rows with a running and a completed run; the assistant page without a key; the fleet page | badges carry `bg-status-running-100` / `bg-status-completed-100`; banner `warning-*`; PV card `component-pv-*`. Compiled CSS colours each as its old amber, green or teal class did (e.g. `rgb(254 243 199)`). No template or script applies an `amber-*` class. Every `tailwind` role palette is applied | β |
| B5 | No colour outside the token file | every web source | the hex scan finds `static/src/theme-tokens.json` only | γ |
| B6 | Chrome follows the theme | e2e, live server, dark mode: results page; compare page's radar tab; financial chart (secondary y) | no chart paper is white. The radar's disc and grid, and the financial chart's `yaxis2` grid and zero lines, are not the light template's (735's and 737's measurements). Toggling the theme recolours shown and later-shown charts. Compare chart texts keep WCAG AA contrast (`test_compare_chart_titles_and_legends_are_legible`) | γ |
| B7 | Panels and absences | results pages via the Flask client: a 2024-10-01..11-30 home run; a full-2024 run; a 1-day no-flow, no-battery run; a fleet run | 61-day run: the Monthly card reads the 90-day reason with "61", the Seasonal card the 180-day reason with "61". Full-year run: every panel a figure. No-flow run: Sankey reason "No energy flowed…", no battery or heat-pump panel. Every chart id appears once. Each container's `min-height` equals its figure's `layout.height`, and its heading equals `layout.title.text` | δ |
| B8 | Panel refusals | `ChartPanel` with content `"{}"`, dom_id `"Chart 1"`, height 0, blank reason | each raises naming the field and value | δ |
| B9 | Shared page parts | Flask client over the home, fleet and compare result pages (δ) and the sweep page (η) | each loads Plotly once, through `chart_scripts`. The compare tabs carry `role="tab"` and `aria-selected`. No page template writes the tab class pair | δ, η |
| B10 | Flow facts | the arbitrage home of `scenarios/bristol-arbitrage.yaml` on 2024-06-21 with `synthetic_june_weather`; a run with an SEG and no tariff that exports nothing | Sankey PV→Battery equals `summary.total_pv_charge_kwh`, and Grid→Battery equals `total_grid_charge_kwh`. The three properties satisfy their identities. The note reads "No import tariff configured…" (today "No tariff configured…") | ε |
| B11 | Typed comparison | a home run and a 2-home fleet run, `make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)`, saved and compared; the arbitrage home vs a plain home | the fleet's radar r is 25 % self-consumption and 60 % grid dependency (today 0). Its export axis is export/generation. The PV-stored axis is left out, with a note naming the fleet run. The arbitrage home's PV-stored axis equals `total_pv_charge_kwh / total_generation_kwh`, and its grid charge is not counted. A stored summary S19's reader refuses gives a flash, never a chart-less page | ζ |
| B12 | Sweep chart | three finished points of a `pv_capacity_kw` sweep saved through `save_home_run`, posted to the endpoint; one finished point; an unknown run id | three panels. The grid-import panel's optimum marker is at its lowest value, and generation's at its highest. One point: each panel's reason names two points. Unknown id: 400 naming it. e2e: a completed small sweep shows a `.js-plotly-plot` in its chart area (task 135's check) | η |
| B13 | One card | every page template | the triple appears only in `macros.html`. Each converted page's rendered card elements carry the same class sets as before | θ |

## Pre-conditions for activating

- No upstream stream (wave 1). Out-of-batch tasks this batch waits on, each wired at decompose:
  - **780** (S10 γ2): the 90/180 gates read `results.window.days`. Upstream of δ.
  - **714** (fk-ce345e3b013d, in progress): renames the financial line. Upstream of δ (the same builder).
  - **752** (fk-02500b87f3cb, pending): deletes `overlaid_power_flows`. Upstream of δ, so the figure-case table does not change twice.
  - **691** (in progress) and **736** (pending): both edit `chart-renderer.js`. Upstream of γ, for serialisation only.
  - **S19 γ** (not yet filed): `RunRecord.summary()` and `RunHeadline`. Upstream of ζ and η.
  - **454** (pending, branch complete, gated on esc-454-3): hoists the chart imports and drops compare's `except`. Upstream of δ if a human closes esc-454-3; otherwise δ does the hoist (§Open questions Q3).
- G3 substrate:
  - `tailwindcss/colors` and JSON `require` in `tailwind.config.js` (probed).
  - Arbitrary custom properties with `theme()` (probed).
  - `static/**/*` package data.
  - `HomeConfig.tariff_config` and `seg_tariff` in the stored config (`storage.load_home_run` returns the `HomeConfig`).
  - `flow.simulate_timestep`'s `battery_charge = pv + grid` and self-consumption including discharge.
  - `SummaryStatistics.__post_init__`'s grid-charge bound.
  - The complete event's `run_id` in `parameter-sweep.js::_followPoint`.
  - `MutationObserver` and `getComputedStyle(...).getPropertyValue` (standard DOM).
  - Plotly.js accepting `rgb(...)` colour strings.

## Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S10 Window and cadence | consumes | `results.window.days` in the monthly/seasonal gates (task 780); δ turns their `None` into `ChartAbsence` reasons | S10 (count), S21 (panel) | δ depends on 780 |
| S19 Run store | consumes | `RunRecord.summary()`, `RunHeadline`/`run_headline` (widened by ζ per D-S19-8), `StoredRunUnreadable` for unreadable compared runs; S19 ε's per-variant `match` calls δ's tab assemblers | S19 (decode, headline name, routes), S21 (headline fields, assemblers) | ζ and η depend on S19 γ; δ and S19 ε serialise on `routes.py` |
| S12 Load composition | consumes | heat-pump panels become per-named-load panels; builders return `ChartPanel` | S12 | S12 is wave 2 (after S21 δ in file order) |
| S20 Job events | shares | `parameter-sweep.js` (S20: SSE; η: the chart post); `status.*` tokens keyed by status name | S20 (events, job states), S21 (colours) | file overlap; no semantic seam |
| S18 Dashboard limits | shares | `simulate/fleet.html` cards use `component.*` (β) and `card` (θ) before S18 rewrites the page from `PageLimits`; the form-label macro of fk-ff5b90768f66 is offered to S18 | S18 (forms) | cross-reference line |
| S26 Sweep registry | consumes later | the sweep chart's parameter label and values come from the page; S26's registry may own labels and read values back from runs | S26 | cross-reference line |
| S25 Board reports | shares | `SummaryStatistics`' three flow properties are available to S25's typed rows; the fleet mapping stays in `run_headline` (no third copy) | S25 (rows) | cross-reference line |
| S3 One dispatch engine | produces for | discharge ≤ shortfall makes `total_direct_self_consumption_kwh` exact | S3 | no edge; ε's identity holds as the engine defines self-consumption |
| S1 Errors leaf | shares | δ deletes the `web.routes`/`web.history` → `web.charts` allow-list entries of task 775's test if 775 has landed | S1 (test), S21 (entries) | no edge |
| S29 Surface bump | none | ε's additive members land in-leaf (D29) | — | no held leaf |

No reciprocal "the other owns it" pair: each row names one owner.

## Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all` and the keys listed. δ is high (fk-42c0053b9a2b) and joins trigger-chain gate 772. Every leaf that changes a template, script or `tailwind.config.js` rebuilds and commits `static/dist/style.css` (CLAUDE.md "Tailwind rebuild").

- **α. Theme token file; Tailwind and charts read it.** Files:
  - `static/src/theme-tokens.json` (new; `tailwind.primary` and the `chart` section);
  - `tailwind.config.js`;
  - `charts.py` (`COLOUR_PALETTE` loaded; `_AMBER`/`_RED`/`_GREEN`/`_BLUE`/`_PURPLE`, `'#888888'` and `'black'` gone);
  - `static/dist/style.css` (rebuilt: unchanged);
  - `tests/unit/test_web_theme_tokens.py` (new);
  - `tests/unit/test_web_chart_colours.py` (palette source, neutral roles);
  - `tests/unit/test_web_theme_colours.py` (premise read from the JSON, regex `_PRIMARY_500_ENTRY` gone);
  - `tests/unit/test_web_theme_palettes.py` (palettes read from the JSON, regex `_PALETTE` gone);
  - `tests/_dashboard_sources.py`.

  Signal: B1, B2 (byte-identical rebuild from a config holding no hex) and B3. Unlocks β, γ. Key fk-93ee9a05751a. Priority medium.
- **β. Role palettes replace amber outside the accent.** Files:
  - `theme-tokens.json` (`warning`, `status`, `component`) and `tailwind.config.js` (nested roles, unknown-name throw);
  - `templates/assistant/chat.html`, `components/macros.html` (`_run_status_badge_classes`), `simulate/partials/progress-tracker.html`, `dashboard.html` (Run Single Home → `primary-*`), `simulate/fleet.html` (PV, battery and load cards → `component-*`);
  - `static/dist/style.css`;
  - `tests/unit/test_web_theme_colours.py` (`_AMBER_ROLES`, `_AmberRole` and their meta-tests deleted; one check that no source applies the accent's palette), `test_web_theme_palettes.py`, `test_web_run_badges.py`.

  Signal: B4 and B2's refusal half. The History page renders a running run's badge with `bg-status-running-100`, whose compiled colour is amber-100's. `git grep -E '\bamber-[0-9]'` over templates and scripts is empty, and `test_web_theme_colours.py` holds no allow-list. Record fk-2e7ddcee2379's re-measurement (§Background) on the task. Prereq α. Keys fk-93ee9a05751a, fk-2e7ddcee2379. Priority medium.
- **γ. No colour outside the token file: chart chrome from computed style.** Files:
  - `static/js/chart-renderer.js` (no hex; computed `color` and `--chart-grid`, applied to every `xaxis*`/`yaxis*` incl. zero lines and every `polar*` axis and disc; paper and plot left transparent);
  - `components/macros.html` (`chart_panel`'s container chrome classes);
  - `static/js/parameter-sweep.js` (`_renderChart`'s Chart.js path and its two hexes deleted);
  - `templates/scenarios/sweep.html` (the empty `#sweep-chart` card deleted until η);
  - `static/dist/style.css`;
  - `tests/unit/test_web_theme_tokens.py` (the hex-home scan), `tests/e2e/test_dark_mode_pages.py`, `tests/e2e/test_compare_page.py`.

  Signal: B5. B6 runs locally; the per-task verify never runs e2e. The sweep page no longer shows an empty card. Supersedes 735 and 737 (their measurements are B6's postconditions). Prereqs α, 691, 736. Keys fk-93ee9a05751a, fk-55f4e4ea396d. Priority medium.
- **δ. Chart panels: one typed description per chart, tabs as data, named absences.** Files:
  - `charts.py` (`ChartAbsence`, `ChartPanel`, `ChartTab`, the panel helper; every builder returns a panel, `heat_pump_analysis` two; `HeatPumpCharts` deleted; `home_results_tabs`, `fleet_results_tabs`, `comparison_tabs` over today's inputs; monthly, seasonal and Sankey reasons);
  - `routes.py` (pass tabs; the charts dict, the battery double guard and the function-local imports gone);
  - `history.py` (tabs; broad `except` and the function-local import gone);
  - `components/macros.html` (`chart_panel(panel)`, `tab_bar`, `chart_tabs`, `chart_scripts`);
  - `results/home.html`, `results/fleet.html`, `history/compare.html` (hand-written tab bars, `chart_panel` calls and Plotly tags replaced);
  - `static/dist/style.css`;
  - `tests/unit/test_web_chart_panel.py`, `test_web_chart_figures.py`, `test_web_charts.py`, `test_web_fleet_charts.py`, `test_web_chart_colours.py` (figure cases read `panel.content`), `test_web_heat_pump_results.py`, `test_web_history.py`, and `tests/unit/test_import_structure.py` if 775 has landed;
  - e2e `test_results_page.py`, `test_fleet_results_page.py`, `test_compare_page.py` (run locally).

  Signal: B7, B8, B9's δ rows. The 61-day run's results page shows both named reasons. Today the Monthly card is missing silently and the Seasonal card shows a template literal. Supersedes 456 and 129, and carries fk-8f26d000b68d with `x_supersedes_task = 674` (the tab-role remnant). Prereqs 780, 714, 752 (and 454 per Q3). Keys fk-42c0053b9a2b, fk-ff5b90768f66, fk-8f26d000b68d, fk-3239afd8ce6b. **Priority high; dependency of gate 772.**
- **ε. Chart facts from the run: flow properties and the pricing note.** Files:
  - `home.py` (three `SummaryStatistics` properties; `SimulationResults`' `self_consumption` docstring);
  - `charts.py` (`sankey_diagram` reads the properties; `financial_breakdown` takes the run's pricing facts from `config`; `_unpriced_import_note`'s inference and its caveat deleted);
  - `tests/unit/test_public_api_surface.py` (`FROZEN_MEMBERS`), `docs/domain-library-consumption.md` ("Unreleased on main");
  - `tests/unit/test_home.py`, `test_web_charts.py`, `test_web_chart_energy_flows.py`.

  Signal: B10. A grid-charging home's Sankey PV→Battery link equals `summary.total_pv_charge_kwh`. An SEG-only run that exports nothing carries "No import tariff configured — cost tracking unavailable"; today it says no tariff at all. Supersedes 628. Prereqs δ, 714. Key fk-8e109704aa24. Priority medium.
- **ζ. Typed comparison: runs, not decoded dicts.** Files:
  - `storage.py` (`RunHeadline` widened, `run_headline` fills it);
  - `charts.py` (`ComparedRun(label, headline)`; `comparison_bar_chart` and `comparison_radar` take it; the `summary_keys` string table and every `.get(key, 0)` gone; radar axis "PV stored in battery %", axes omitted by name);
  - `history.py` (builds `ComparedRun`s from `record.summary()`);
  - `tests/unit/test_web_charts.py` (comparison tests moved from `test_web_history.py`, per 629), `test_web_history.py`, `test_web_storage*.py`, `test_web_chart_colours.py`, `test_web_chart_energy_flows.py`.

  Signal: B11. `/history/compare?ids=<home>,<fleet>` draws the fleet at 25 % and 60 % (today 0 %), and names the fleet run in the battery-axis note. Supersedes 565, 575, 492 and 629. Prereqs ε, δ, S19 γ. Keys fk-3239afd8ce6b, fk-8e109704aa24. Priority medium.
- **η. The sweep chart, drawn from the sweep's runs.** Files:
  - `charts.py` (`SweepMetric`, `SweepPoint`, `sweep_parameter_chart` returning a panel with the optimum by direction, `sweep_panels`);
  - `scenarios.py` (`POST /scenarios/sweep/chart`);
  - `templates/scenarios/sweep.html` (chart area, `chart_scripts()`), a partial for the panels' HTML;
  - `static/js/parameter-sweep.js` (on all-done, post the finished points and insert the answer);
  - `static/js/chart-renderer.js` (`MutationObserver` for late or re-filled containers);
  - `static/dist/style.css`;
  - `tests/unit/test_web_scenarios.py` (TestSweepChart), a route test, e2e `test_parameter_sweep.py` (run locally).

  Signal: B12. A finished three-point sweep shows three charts and the grid-import chart marks its lowest point; today the page shows an empty card (γ removed it). Supersedes 123 (its stale branch is not rebased) and 135. Prereqs γ, δ, S19 γ. Key fk-55f4e4ea396d. Priority medium.
- **θ. One card macro.** Files:
  - `components/macros.html` (`card` gains the header and body parameters the sites need; `stat_card` and `chart_panel` built on it);
  - `dashboard.html`, `simulate/fleet.html`, `results/home.html`, `results/fleet.html`, `history/compare.html` (13 card copies), `simulate/home.html` (`tab_bar` classes if it can take the Alpine tab list);
  - `static/dist/style.css`;
  - `tests/unit/test_web_template_macros.py` (or a new module) with the triple-outside-macros check, and the affected page tests.

  Signal: B13. `git grep -F` of the triple finds only `macros.html` (16 copies today). Prereqs β, δ. Key fk-ff5b90768f66. Priority medium.
- **Acceptance (no code).** fk-657669b23e71 is filed as a `cancelled` task with `x_acceptance_reason`: "D22 names the css-build lane job as the Tailwind guard. The per-task sandbox cannot reach npm. Measured: 2 lane reds (626, 634) since the lane began on 2026-10-05, none since the review pin. Ruled R4 in the S21 /prd session, 2026-10-15." Not part of `commit_planning`'s pending flip.

DAG: α → {β, γ}; {α, 691, 736} → γ; {780, 714, 752, (454)} → δ; {δ, 714} → ε; {ε, δ, S19 γ} → ζ; {γ, δ, S19 γ} → η; {β, δ} → θ.

Not refiled: fk-ce345e3b013d (task 714), fk-02500b87f3cb (task 752).

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- `no-silent-fail-soft`:
  - `'{}'`, `None` and the compare page's swallowed exception become named absences or refusals.
  - The token loader and the Tailwind build refuse bad tokens.
  - chart-renderer.js already logs a failed draw by container id.
  - The radar's omitted axis is named in the figure.
- `one-fact-one-home`: colours (token file), chart descriptions (`ChartPanel`), flow identities (`SummaryStatistics`), the fleet mapping (`run_headline`), the card (`card`).
- `exceptions-owned-or-ratified`: no allow-list is added. `_AMBER_ROLES` is deleted.
- `guards-exercise-behaviour`: B4, B7, B9, B11 and B12 render pages. The two source scans (hex home, card triple) guard where text is written, which is the fact itself.
- `readers-prove-their-producer`: the sweep chart reads runs a real sweep's jobs saved (B12's e2e).

No waivers.

## Out of scope

- A form-control label macro (the third macro of fk-ff5b90768f66's proposal). The forms belong to S18 (fleet, builder) and S11/S17 (home form). Offered to S18 by cross-reference.
- Vendoring Plotly and js-yaml (task 250). δ's `chart_scripts` makes it a one-place edit.
- Charts drawn wider than their container during the main column's slide-in (task 736, medium; upstream of γ).
- Run-type badge colours, flash-category colours and any non-amber hue as a role. They do not collide with the accent.
- Re-theming the accent or changing any colour: every change here is visually a no-op except the named reasons, the compare tabs' a11y attributes, the fleet radar's real values and the sweep chart.
- Partitioning `charts.py` (1,060 lines). Net size moves little: `overlaid_power_flows` (752), `HeatPumpCharts` and the note's caveat go, and the panel types and assemblers come.
- Per-named-load chart panels (S12). The sweep knob registry and labels (S26).

## Open questions

For the lead:

1. **Q1 Supersession at decompose** (after §8 step 1, `cancelled` with `x_superseded_by`):
   - 123 and 135 → η;
   - 129 and 456 → δ;
   - 492, 565, 575 and 629 → ζ;
   - 628 → ε;
   - 735 and 737 → γ;
   - task 153's "keep the charts deferral" item → δ. 153 stays for `web/api.py`.

   Recommended: all, as listed. 123's branch is complete but 2,289 commits behind with four conflicted files, and its storage helper contradicts S19's decoder.
2. **Q2 Session rulings R1–R4** need D-numbers in the program doc.
3. **Q3 Task 454** has a complete branch blocked only on the stale info escalation esc-454-3. If a human closes it, δ depends on 454. Otherwise drop the edge and δ does the hoist and the `except` removal itself.
4. **Q4 The form-label macro** is offered to S18 (cross-reference line below). Accept, or return it to S21 as a ninth leaf?
5. **Q5 Edges on 691 and 736** exist only to serialise edits to `chart-renderer.js`. Keep them, or let the merge queue serialise?
6. **Q6 Seam wording.** The program's seam row reads "readers tailwind.config.js, chart-renderer.js, charts.py _AMBER". After R3, chart-renderer.js reads the theme through the compiled stylesheet, and `_AMBER` is gone. Proposed: "Theme tokens (owner: `static/src/theme-tokens.json`; readers `tailwind.config.js` and `charts.py`; chart-renderer.js through the compiled theme)".

Tactical, decided in the leaf:

7. How `chart_panel` tells a figure from an absence: properties on `ChartPanel` such as `figure_json` and `absence_reason`, never a string comparison in Jinja. Decide in δ.
8. `card`'s parameters for coloured header bands and `stat_card`'s padding. Decide in θ by the 13 sites.
9. The grid colour source: `--chart-grid` on the container (probed), or the text colour at reduced alpha. Decide in γ against B6's contrast checks.
10. The sweep panels' insertion: `x-html` of the fragment or a swapped container. Decide in η. The swept value's label comes from the page until S26.
