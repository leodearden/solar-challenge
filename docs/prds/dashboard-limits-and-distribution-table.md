# PRD — Dashboard limits and distribution editing from one table

- **Program:** review-all-solar_challenge-20261013, stream **S18** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 3, upstream S5 and S4 (and S7 by the cross-reference lines), size L, risk medium.
- **Finding keys:** fk-a6d9f3e5a7e2 (high), fk-1df9dbc0d971, fk-366773b4083f, fk-8107696f0b02, fk-7893b49b92c3, fk-88374e6e3553, fk-d303b6dbf669, fk-40dff1473b94 (weakened; re-measured in §2.6), fk-9dd1d9389dd2 (mechanical, task 697; §2.6), fk-f8b7b3ab709d (low, mechanical, task 376), fk-006c3339e3b2 (low), fk-021a21b35427 (low, weakened; re-measured in §2.6), fk-3cd0d3f3b512 (low, mechanical, task 753), fk-c3625a25eed4 (low). Severities are medium unless stated.
- **Binding rulings:**
  - D18: config's grammar module, `fleet_distribution.py` after S5's partition, owns the per-type table; the editor, preview and serialisers derive from it.
  - D28: the weakened findings are re-measured before decomposing.
  - D2, D9, D17 and S17's translator: a refusal is `errors.ConfigurationError`, answered 400 by S17's boundary.
  - D27 and invariant 11: S18 owns the window half of invariant 11's test; S11 γ (841) owns the tariff half, `tests/unit/test_web_tariff_presets.py`.
  - L35: a shuffled pool's counts sum to n_homes exactly (S7 F6).
  - L17 Q4: S21 offers S18 the form-label macro.
  - L37: priority follows severity unless a ruling says otherwise.
  - L38: task 584 comes to this decompose as a pre-existing task.
  - The cross-reference lines naming S18:
    - the table reads S7's kind → spec-type rule and fleet rows;
    - the preview samples through S7 γ's sampler;
    - option lists render from `heat_pump.HEAT_PUMP_TYPES` and `ev.CHARGER_TYPES`;
    - the dispatch vocabulary renders from `dispatch.STRATEGY_CONFIG_BY_TYPE` and includes a tariff-clocked `tou_optimized`;
    - the translator deletion depends on S4 η (870).
- **Status:** authored 2026-10-17 by an author-only /prd session (spawn); committed by the lead at `aa8dece`; decomposed 2026-10-18 at main `beb1d91` (ids in the sidecar). Lead ruling L42 accepts the defaults of lead questions 1–4: ε (not ε′), decision 12's refusal, decision 9 and decision 2. L42 and L44 also move the default-window pair to S6 β (956) as `timebase.DEFAULT_FIRST_DAY`/`DEFAULT_LAST_DAY`: α defines only `SHORT_WINDOW_START` and repoints the CLI, the templates and `web/simulation_params.py`. Decision 5, §4.1, §4.2, §5 W1 and §8 α say so. Decompose corrections:
  - S6 δ, ε and ζ (958, 959, 960) give the five commands with `--start`/`--end` the `cli/utils` option pair, which defaults to None, so W1 accepts either form in either landing order;
  - α also edits `web/assistant.py`, which imports the `simulation_params` window names;
  - β also edits `simulate/partials/load-config.html` (it reads `fixed_range`);
  - the δ file `tests/integration/test_web_fleet_distribution.py` does not exist and is dropped;
  - ζ also deletes `static/vendor/js-yaml/LICENSE` and `upstream.toml`; alpinejs stays vendored, so the wheel's licence test still finds a package;
  - three sidecar checks are re-anchored: β's size-literal check would have matched `heat-pump-config.html`'s `max="50000"`, ζ's would have matched the builder's initial `latitude: 51.45`, and δ's builder check is anchored on `wd_values`/`sp_entries` because `task/313` deletes the three names it named.
- **Approach:** B + H. The work spans the grammar, six web modules, four templates and three scripts across two languages, and four streams' seams meet in it. §4 is the contract and §5 the two-way boundary-test sketch.
- **Code anchors** verified against main `ede1d99` (2026-10-17). Main moves fast: cite by symbol and re-locate lines at implementation time. Against the review's pin `7dfea36e`, the S18 web files differ as follows:
  - `fleet_config.py`: `_pool_counts` is now the public `read_pool_counts`, and `sample_distribution` is imported at the top of `api.py`;
  - `builder_form.py`: task 697 reads pool counts through `read_pool_counts`;
  - the anchors the findings name are otherwise unchanged.

## 1. Goal

What the dashboard's forms accept, and what they start at, is stated once: on the server, beside the grammar that reads it. A distribution is edited, posted, previewed and imported as the grammar's own spec. No page or script restates a limit, a default, a distribution type or a tariff or dispatch type.

What a user observes:

1. **One fleet-size limit.** Today the fleet page allows 10–500 (input and slider), its script refuses more than 1,000, and the server takes up to 10,000. After this stream, the fleet page and the builder accept 1 to 10,000 homes, and the fleet page posts 2,000 homes and runs them. A fleet of 10,001 is refused by the server, which names `n_homes` and 10,000. The slider stays a 10–500 convenience.
2. **One range per component, on every form.** A home with a 500 kWh battery is refused on the home page; today it runs. A fleet whose homes draw 50 kW of PV, by a fixed value or by a distribution, is refused on the fleet page and the builder. Today the fleet page runs it, and the builder refuses only the fixed value. The refusal names the field, the range and the value. The assistant's tool descriptions state the same PV range.
3. **One distribution grammar on both fleet pages.** A normal with no std posted from the fleet page is refused with the builder's message, naming the missing `std`. Today the fleet page runs it as N(0, 1). A scenario that loads on one page loads on the other. Each distribution editor offers the same types, with the same titles and fields, on both pages.
4. **The preview shows what Run builds.** The fleet page's preview of each card lists the values Run's homes will hold, for the same seed. A preview of an inverted clamp or a negative weight is refused with Run's message. Today the endpoint previews a shuffled pool that Run refuses, cycling it.
5. **The builder imports on the server.** Uploading a scenario, or loading a built-in or saved preset, fills every field the builder holds. It refuses a setting the builder cannot hold, naming it, and lists the settings it leaves out, as the fleet page does. Today the upload drops an Economy 7 tariff, a SEG preset and every dispatch setting silently, and a preset restores at most its name, location and size. A saved preset reloads as saved.
6. **Window defaults are the engine's.** Every CLI `--start`/`--end` default, the CLI's scenario templates and every dashboard date default read one pair of constants in `timebase.py`. No `2024-01-01`, `2024-12-31` or `2024-06-01` string literal remains in `src/`.
7. **Tariff and dispatch choices come from the server.** The fleet form's tariff and dispatch options, their settings and their starting values render from server tables. The economy rates come from `tariff.PRESET_RATES` and the strategies from `dispatch.STRATEGY_CONFIG_BY_TYPE`. A `tou_optimized` that follows the tariff's cheap periods is one of the choices. The home page's heat-pump types render from `heat_pump.HEAT_PUMP_TYPES`.

## 2. Background (measured at `ede1d99`)

### 2.1 Limits restated per page

| Limit | Server | Pages and scripts |
|---|---|---|
| Fleet size | `fleet_config.MAX_FLEET_HOMES = 10_000`, read by `read_fleet_size` and `builder_form._home_count_allowed` | `simulate/fleet.html`: `min="10" max="500"` on the number input, the slider `range_input(... min=10, max=500 ...)` and its 10/500 captions; `fleet-simulator.js` `formErrors`: `n > 1000`; `scenarios/builder.html`: `max="10000"` |
| Seed | `MAX_FLEET_SEED = 2**53 - 1` | `fleet-simulator.js` `DEFAULT_SEED = 42` |
| Window | `simulation_params.MAX_WINDOW_DAYS`, `FULL_YEAR_START`, `FULL_YEAR_END`, `DAYS_WINDOW_START`, `FULL_YEAR_DAYS_SENTINEL` | `fleet.html`: days choices `[7, 14, 30, 90, 365]`; `fleet-simulator.js`: `DEFAULT_PERIOD_DAYS = 30`, `startDate: '2024-06-01'`, `endDate: '2024-06-30'`; `home.html`: `start_date`/`end_date`; `scenario-builder.js`: `start_date`/`end_date` and `setPeriod`'s five windows; `sweep.html` already receives `max_window_days` |
| Component ranges | `FleetComponent.fixed_range`, enforced by `builder_form._dashboard_limit_errors` (fixed values only) and by `parse_home_config` for load alone | `simulation_params.parse_home_config` and `home.html` restate the PV range as `0.5`/`20`; the battery range is enforced nowhere on the home page; `form_to_fleet_distribution_config` enforces none; `assistant.py`'s two PV tool descriptions say `(0.5–20)` |
| Starting distributions | `FleetComponent.builder_default` | `fleet-simulator.js`'s `pvDist`, `batteryDist` and `loadDist` literals disagree with it: battery normal max 15.0 against 13.5, load max 6,000 against 5,000, and a four-row PV weighted list against three rows |

The fleet page's `formErrors` also makes rules of its own: `std <= 0` and `min >= max`, for PV only. Config refuses `std < 0` and `min > max`. The scripts `parseInt` `n_homes`, `days` and the peak hours, so 2.5 is posted as 2.

### 2.2 Two wire shapes, two decoders, seven per-type chains

Both fleet pages edit a component through `components/distribution-editor.html` and `distribution-editor.js`. The editor's state is `{type, fixed, mean, std, min, max, values: [{value, weight}], entries: [{value, count}]}`.

The pages serialise this state differently:

- The fleet page's `_buildDistPayload` posts it nested.
- The builder's `componentFormData` flattens it to `pv_distribution_type`, `pv_mean`, `pv_wd_values` and `pv_sp_entries`.

Two server decoders then rebuild config's grammar from the two shapes:

- `fleet_config._build_distribution_dict` invents defaults: mean 0, std 1, min 0, max 1, value 0, weight 1, count 1.
- `builder_form._distribution_spec` leaves absent keys out for the loader to refuse.

The distribution type is branched on in seven places. On the server:

- `_build_distribution_dict`;
- `distribution_form_spec`, with its own `_EDITOR_DISTRIBUTION_TYPES`;
- `_draw_samples`;
- `builder_form._distribution_spec`.

In the scripts:

- `fleet-simulator.js` `_buildDistPayload`;
- `scenario-builder.js` `componentDistribution` and `componentFormData`.

The editor template spells the types again in its `<select>` and its `x-show` chain. Config keeps the grammar's own table, `config._DISTRIBUTION_SPEC_TYPES`, which holds each type's recognised keys and builder.

The import paths disagree as well. `distribution_form_spec` (fleet import) accepts `{type: fixed, value}` but refuses a normal without both clamps. `scenario-builder.js` `componentDistribution` (builder upload) throws on `fixed`.

### 2.3 The preview

`POST /api/fleet/preview-distribution` calls `fleet_config.sample_distribution` → `_draw_samples`, which is a hand copy of config's sampler (cognitive complexity 34). No template or script calls the endpoint (grep of `templates/` and `static/`). The copy accepts distributions that config refuses, and it cycles a shuffled pool that Run refuses (§2.7 P8–P10).

### 2.4 The builder's import and presets

The fleet page imports on the server. `fleet_scenario.fleet_form_from_scenario` runs the loaders first. It refuses a setting the form needs but cannot hold, and lists the rest in `not_loaded`.

The builder parses the same grammar in the browser instead, through `jsyaml.load` → `scenarioFormFields` → `componentDistribution`, under the opposite policy. Measured by reading `scenario-builder.js` at `ede1d99`:

- **Tariff:** a non-`flat_rate` tariff becomes `import_rate: ''`, so the next preview or save writes `tariff: null`.
- **SEG:** a `{preset: …}` SEG becomes `''`.
- **Other settings:** `dispatch_strategy` and every component setting except capacity vanish with no notice.
- **Presets:** `loadPreset` copies `name`, `n_homes` and the coordinates, with `|| 51.45` and `|| -2.58`. It sets no altitude, distributions, period, tariff or SEG.
- **Saved presets:** `doSave` posts `config: getFormData()`, and `api.scenarios_save_scenario` stores that flat form unvalidated. `scenarios_get_preset` therefore answers two untagged shapes: a document for built-ins, and the flat form for saved presets. `loadPreset` reads document keys, so a saved preset restores only its name.

The page also loads a vendored js-yaml, pinned by `tests/unit/test_web_page_scripts.py`, for this one purpose.

### 2.5 The fleet form's tariff and dispatch vocabulary

Twelve per-type decision sites in three files, two languages (fk-006c3339e3b2's measurement, reproduced):

- `fleet.html`, 6 sites: two option lists, plus `x-show` conditions for flat rate, economy, `tou_optimized` and `peak_shaving`.
- `fleet-simulator.js`, 4 sites: the tariff and dispatch branches of `buildPayload`, plus `_applyTariff` and `_applyDispatch`. Their `else` branches assume that every tariff other than `flat_rate` is a peak/off-peak pair.
- `fleet_scenario.py`, 2 sites: `_FORM_TARIFF_SETTINGS` and `_FORM_DISPATCH_SETTINGS`.

`_FORM_DISPATCH_SETTINGS["tou_optimized"]` reads `peak_hours` through `_one_peak_window`, which refuses anything but exactly one window. So once S11 β makes `peak_hours` optional, it would refuse a tariff-clocked import. The flat-rate starting rate is 0.28 on the fleet and home pages and 0.245 in the builder. S11 handed the form defaults other than the economy rates to S18.

### 2.6 Re-measured findings (D28, mechanical rows)

| Key | Measured at `ede1d99` | Disposition |
|---|---|---|
| fk-40dff1473b94 (weakened) | Still present: `uploadYaml` calls `jsyaml.load`. Each silent drop in §2.4 holds, read from the code. The skeptic's correction also holds: `componentDistribution` throws on `fixed` and `proportional_to`, so not every loss is silent. | ζ carries it at weakened weight; the measurement is recorded on ζ |
| fk-021a21b35427 (weakened) | Docstrings are 41.3% of `fleet_config.py`'s raw lines (226/547) and 34.2% of `fleet_scenario.py`'s (188/550). AST count; the finding says 225/545 and 188/550. `fleet_config.py` holds 12 `see :func:` Raises cross-references. The skeptic's note (amend SHAs unverified) is not re-checked: the count, not the history, is what δ and ζ change. | δ and ζ carry it; each records the post-change share |
| fk-9dd1d9389dd2 (task 697, done) | Fixed: the builder refuses `pv_sp_entries[0].count` 10¹², naming the field and 10,000 (probe P7). The proposal's structural half, one decoder plus a pool bound in config itself, is delivered by δ (no web pool reader) and by S7 F6 / task 297 (counts == n_homes). | Closed by 697. No S18 leaf carries it; re-run contract §8 step 1 at decompose regardless |
| fk-f8b7b3ab709d (task 376, pending) | Still present (§2.1) | β supersedes 376 |
| fk-3cd0d3f3b512 (task 753, pending; the report table says a ticket, the findings JSON says `filed:753`) | Still present: `form_to_fleet_distribution_config`'s docstring is 26 lines over about 13 lines of code. The inline defence in `simulation_params` is S4 η's to delete ("the four PVConfig-named pre-reads and their comment"). | δ deletes the functions those docstrings describe; δ supersedes 753 |

### 2.7 Probes

All probes ran at `ede1d99` under `UV_OFFLINE=1 uv run --locked --extra dev --extra web python -I`.

| # | Input | Today |
|---|---|---|
| P1 | `parse_home_config({pv_kw: 4, battery_kwh: 500, days: 1})` | accepted, battery 500.0 kWh |
| P2 | `parse_home_config({pv_kw: 50, days: 1})` | `ValueError: PV capacity must be 0.5-20 kW, got 50.0` (the literal) |
| P3 | `parse_fleet_form` with PV 50, battery 500, load 100,000 as fixed values | accepted; homes generated with those values |
| P4 | `form_to_fleet_distribution_config({pv: {capacity_kw: {type: normal}}})` | `{type: normal, mean: 0.0, std: 1.0}` |
| P5/P6 | builder `{pv_distribution_type: normal, pv_mean: 4}` | the spec carries no std; `builder_form_errors` returns "normal distribution for 'fleet_distribution.pv.capacity_kw' requires 'mean' and 'std'" |
| P7 | builder pool count 10¹² | refused by name (697) |
| P8 | `sample_distribution('normal', {mean 4, std 1, min 9, max 2}, 3)` | `[2.0, 2.0, 2.0]` |
| P9 | weighted weights −1 and 3 | `[5.0] * 4` |
| P10 | pool counts 2+1, 6 samples | `[3, 3, 4, 3, 3, 4]`: the pool is cycled |
| P11 | fleet form, `n_homes` 2000 | accepted (the page caps at 500, the script at 1,000) |
| P12 | fleet import, `pv.capacity_kw: {type: fixed, value: 4}` | form `4.0` |
| P13 | fleet import, normal without clamps | refused: `…capacity_kw.min must be a finite number, got None` |
| P14 | builder `pv_capacity_kw: 50` | refused: "PV Capacity (kW) must be between 0.5 and 20, got 50." |
| P15 | builder normal mean 50 kW, std 1 | accepted: no range check on drawn values |

## 3. Resolved design decisions

1. **`PageLimits` is one frozen value, owned by `web/fleet_components.py`** (seam row). `page_limits()` builds it from the constants that module holds:
   - `MAX_FLEET_HOMES`, `MAX_FLEET_SEED`, `read_fleet_size` and `read_fleet_seed` move in from `fleet_config`;
   - `MAX_WINDOW_DAYS` and `FULL_YEAR_DAYS_SENTINEL` move in from `simulation_params`, since `fleet_components` cannot import `simulation_params`, which imports it;
   - each component's range, step, new-row value and starting distribution;
   - the window defaults from `timebase`.

   A Flask context processor registered in `create_app` gives every template `page_limits`. `base.html` renders it once as `<script type="application/json" id="page-limits">`, and every script reads that element. That is one channel: no route passes a limit, and no script holds one. The module's purpose becomes "what the dashboard's forms accept and start at". The name stays, as the seam table writes it.
2. **One range per component bounds every home's value, on every form.** `FleetComponent.fixed_range` becomes `value_range: Interval`, an S4 α `number_fields.Interval`. It bounds the value a home holds, whether the form fixes it or a distribution draws it. Three readers apply it:
   - The home reader reads `pv_kw`, `battery_kwh` and `consumption_kwh` through `as_finite_float(..., within=component.value_range)`, naming the form field. The PV literal goes, and the battery range applies for the first time.
   - The fleet form and the builder apply one function, `fleet_components.refuse_homes_outside_ranges(homes)`, to the homes the loaders generate. It names the component's field as both forms post it (`pv.capacity_kw`), the home's number, the range and the value.

   Bounding drawn values, not only fixed ones, is this PRD's widening of fk-1df9dbc0d971 (heuristic 10, uniformly enforced). A fixed 50 kW and a normal around 50 kW describe the same implausible home (P14 against P15). A distribution whose tail crosses the range is refused for the seed that draws it, naming the home. The preview shows such a draw before Run.
3. **The fleet page validates nothing on the client.** `formErrors` goes. Run and Export post the form, and the page shows the server's refusal, as the builder already does through `/api/scenarios/validate`. The scripts post numbers as the inputs hold them, with no `parseInt`. The home page keeps its client checks, which read their bounds from `page_limits`.
4. **The fleet-size slider is a convenience, not the bound.** The number input carries the limit, 1 to `MAX_FLEET_HOMES`. The slider spans 10–500 in steps of 10, and `PageLimits` names it `fleet_size_slider`. A larger fleet is typed.
5. **The default window is a library fact in `timebase.py`** (invariant 11; L42):
   - `DEFAULT_FIRST_DAY = date(2024, 1, 1)` and `DEFAULT_LAST_DAY = date(2024, 12, 31)` give the 2024 calendar year. S6 β (956) defines them as D11's default tier. They are every CLI command's default window, the `config template` period, the dashboard's full-year window, and the longest window the dashboard runs.
   - `SHORT_WINDOW_START = date(2024, 6, 1)` is the first day of the n-day windows that the dashboard and `home quick` run. α defines it beside the pair; it is S18's only constant there.
   - `simulation_params`'s `FULL_YEAR_*` and `DAYS_WINDOW_START` become these names.
6. **The per-type table lives in `fleet_distribution.py`** (D18). The public `DISTRIBUTION_TYPES` replaces `_DISTRIBUTION_SPEC_TYPES`, with the same six types in the same order. Each record states, once:
   - the type's tag and title;
   - its scalar parameters, each with a title and whether it is required;
   - its paired row lists, if any, with the paired column's title and kind;
   - the keys an editor has no input for (proportional_to's `source`, `multiplier` and `offset`);
   - its builder, which is the existing parse;
   - its writer, the inverse of the builder.

   What the table derives:
   - Recognised keys and "editable" (no unheld keys) are derived, not stated.
   - `editor_types(kind)` gives the types S7's kind rule (F2) accepts for a field, kept to the editable ones and in table order. S7 keeps that rule in its own home; the table reads it.
   - Drawing stays where S7 γ puts it, on the spec types.
   - The editor's "Fixed Value" option is the scalar form, titled by the `fixed` record.
7. **The wire shape is the grammar.** Each page posts a component's field as the spec `fleet_distribution` reads: a number for a fixed value, or `{type, …}` with the type's keys. The server passes it to `parse_fleet_distribution_config` as written. Deleted:
   - in `fleet_config`: `_build_distribution_dict`, `_spec_number`, `_named_rows`, `_other_setting`, `_parse_component_distribution`, `_refuse_block_that_is_a_distribution`, `_is_distribution`, `_is_fixed_value`, `read_pool_counts` and `distribution_form_spec` with its helpers;
   - in `builder_form`: `_DISTRIBUTION_FIELDS`, `_prefixed`, `_distribution_spec`, `_row_lists` and `_finite_floats`.

   A pool is bounded by S7 F6 (counts == n_homes) and the n_homes bound, so no web pool reader remains. The builder's form changes contract: its `<key>_distribution_type`/`<key>_mean`/… fields become the fleet form's `{pv: {capacity_kw: spec}, …}` blocks. The builder is the only client of that contract.
8. **The editor holds one grammar spec per type.** Its state is `{type, fixed, specs: {<type>: {…}}}` (§4.4). Switching type keeps each type's values, as today, and the paired rows are the grammar's parallel lists.

   `distribution-editor.js` gains `wire()` and `load(spec)`, generic over the table that the page renders into each editor scope. A blank optional input posts null, which the grammar reads as absent: a normal without clamps is holdable. A blank pool value posts null, which is a home with no battery, so `_null_capacity_as_zero` goes.

   An import keeps a spec of an editable type and writes it in canonical form, `write(parse(spec))`. It refuses any other type, naming its path.
9. **One starting distribution per component, shared by both pages.** `FleetComponent.builder_default` becomes `start`: a type plus one spec per editable type, built as `fleet_distribution` spec objects so that they are validated at import time.
   - The values are the fleet page's, the distributions its default Run uses: PV and battery shuffled pools, and load normal 3,400 ± 800 clamped to 2,000–6,000.
   - Each starting pool's counts total the default fleet size of 100, checked at construction.
   - The builder therefore starts at the fleet page's distributions instead of fixed values. One fact replaces two.
10. **The preview is Run's homes** (default; lead question 1).
    - `POST /api/fleet/preview-distribution` takes the fleet form, the body Run posts.
    - It answers each component's value per generated home: `parse_fleet_form(form).homes`, read through each component.
    - It refuses exactly what Run refuses.
    - The fleet page gains a Preview action that writes each card's summary under its editor.
    - `sample_distribution` and `_draw_samples` go. The preview samples through S7 γ's sampler because it is the generator.
    - The alternative is to delete the endpoint (lead question 1).
11. **One import policy for both pages, on the server.**
    - `fleet_scenario`'s import readers move to a new `web/scenario_import.py`: the loaders-first refusal, `_read_blocks`, `_not_loaded`, `_read_typed_block`, `_read_name`, `_read_period`/`_read_day`, `_read_seg` and the component read through the table.
    - `fleet_scenario` and `builder_form` each declare what their form holds, and the builder gains `builder_form_from_scenario(document) -> ImportedForm`.
    - The builder holds `flat_rate` and a SEG rate. An Economy 7 tariff or a SEG preset is refused by name: the builder needs the setting and cannot hold it exactly. Anything else goes in `not_loaded`.
    - The builder gains the fleet page's `seed` field, bounded by `PageLimits.seed`, so a built-in fleet saved from the builder keeps its seed. `random_order` is held by neither page and is listed in `not_loaded` on both.
    - Presets are looked up by source and, for saved ones, by `type = 'fleet'`, so a built-in no longer shadows a saved preset of the same name (task 359).
    - `POST /api/scenarios/import-yaml` (new) and `GET /api/scenarios/presets/<name>` answer `{form, not_loaded}`.
    - `POST /api/scenarios/save` stores the document `scenario_from_builder_form` returns, after `builder_form_errors` finds none. A save that is refused gets a 400 with the errors.
    - The builder page drops js-yaml.
    - The prose policy of `fleet_form_from_scenario` (20 lines) moves to one section of `docs/web-ui-design.md`, covering both pages.
12. **A saved builder preset stored before ζ is refused by name** (default; lead question 2). The message names the preset and says it was saved in the builder's former form format and must be saved again. Today such a preset restores only its name (§2.4), so nothing a user had is lost. The alternative is a conversion in ζ.
13. **The fleet form's tariff and dispatch vocabulary is one table each, in `fleet_scenario.py`.** They replace `_FORM_TARIFF_SETTINGS` and `_FORM_DISPATCH_SETTINGS`.
    - `FLEET_FORM_DISPATCH` is built by iterating `dispatch.STRATEGY_CONFIG_BY_TYPE`. Each setting is one init field of the strategy's config, so a new strategy or field without a title raises `KeyError` at import.
    - `peak_hours` is either one window or the tariff's clock (null, S11 β).
    - `FLEET_FORM_TARIFFS` lists the tariff types the form holds: `flat_rate`, `economy_7` and `economy_10`, not `custom`. Each is checked at import against the grammar's tariff types. Its economy starting rates read `PRESET_RATES`.
    - The flat-rate starting rate is stated once, as `PageLimits.flat_rate_start` (what the forms start at, decision 1), and read by the fleet, home and builder forms. It is 0.28, the value two of the three forms start at. The fleet table's `flat_rate` setting starts there.
    - The page renders options, `x-show`s, `buildPayload` and `apply` from the tables.
    - The home page's heat-pump type options (`simulate/partials/heat-pump-config.html`) render from `heat_pump.HEAT_PUMP_TYPES` (911), with titles keyed by type in the same way. No page offers EV charger types today, so `CHARGER_TYPES` (919) has no S18 reader (§9).
14. **The form-label macro is taken** (L17 Q4). β adds `number_field(id, label, model, within, step)` to `components/macros.html`: a number input bound by an `Interval`, with its label. β, δ and η use it on the inputs they render, and `distribution-editor.html`'s private `_parameter` becomes it. fk-ff5b90768f66 stays S21's key; the lead decides whether this closes its form-label third.
15. **`fleet_config` keeps one purpose: the fleet-wide overlay.** After δ and ε it holds only `apply_fleet_overlay`, which is S6's (fk-a391cf1f4edf). Its module docstring says so. The size and seed limits went to `fleet_components` in β, and the form conversion and the sampler are gone. The Raises sections that traced the private call graph go with the functions.

## 4. Contract

### 4.1 `PageLimits` (β; owner `web/fleet_components.py`)

```python
@dataclass(frozen=True)
class ComponentLimits:
    key: str                       # "pv", the fleet_distribution block
    grammar_key: str               # "capacity_kw"
    subject: str                   # "PV Capacity"
    unit: str                      # "kW"
    step: float
    value_range: Interval          # S4 α: the range of a home's value, fixed or drawn
    new_row_value: float
    start: Mapping[str, Any]       # δ: the editor's starting state (§4.4); β carries today's builder_default state

@dataclass(frozen=True)
class PageLimits:
    fleet_size: Interval           # [1, MAX_FLEET_HOMES]
    fleet_size_default: int        # 100
    fleet_size_slider: tuple[int, int, int]   # (10, 500, 10): a convenience, not a bound
    seed: Interval                 # [-MAX_FLEET_SEED, MAX_FLEET_SEED]
    seed_default: int              # 42
    window_days: Interval          # [1, MAX_WINDOW_DAYS]
    default_window: tuple[date, date]         # timebase.DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY (956)
    short_window_start: date                  # timebase.SHORT_WINDOW_START
    day_choices: tuple[int, ...]              # (7, 14, 30, 90, FULL_YEAR_DAYS_SENTINEL)
    default_days: int                          # 30
    period_presets: Mapping[str, tuple[date, date]]   # the builder's full-year, summer, winter, week, month, from the constants
    flat_rate_start: float                     # η: 0.28, every form's starting flat import rate
    components: Mapping[str, ComponentLimits]          # FLEET_COMPONENTS order

    def as_json(self) -> dict[str, Any]: ...   # dates ISO, intervals {low, high}

def page_limits() -> PageLimits: ...
def refuse_homes_outside_ranges(homes: Sequence[HomeConfig]) -> None: ...   # ConfigurationError naming path, home number, range, value
```

Invariants:

| # | Invariant | Enforced by |
|---|---|---|
| L1 | Every `min`/`max` of a form input on `/simulate/home`, `/simulate/fleet`, `/scenarios/builder` and `/scenarios/sweep`, and every bound or default a script reads, equals the `page_limits()` value it renders. No script or template holds a fleet size, seed, day count, date, component range or starting distribution. | β's page test (rendered pages vs `page_limits()`); a scan of `static/js` and `templates` for date literals and the retired numbers |
| L2 | A home whose PV, battery or load value lies outside its component's `value_range` is refused, by every reader that builds homes from a dashboard form | β's reader tests (home, fleet, builder); θ |
| L3 | `page_limits()` is pure and frozen: two calls compare equal, and `as_json()` round-trips through `json` | β |

### 4.2 Window constants (α; owner `timebase.py`)

`DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY` are S6 β's (956). α adds `SHORT_WINDOW_START: Final[date]` beside them.

| # | Invariant (invariant 11, window half) | Enforced by |
|---|---|---|
| W1 | Every CLI `--start`/`--end` option either defaults to the two constants' ISO strings or is the `cli/utils` option pair, which defaults to None and falls back to the constants through the scenario's period (S6 δ, ε, ζ: 958, 959, 960). `home quick` starts at `SHORT_WINDOW_START`. `config template home` and `config template scenario` write the pair as the period. | α's test introspects each command's click parameters from `solar_challenge.cli:app` and runs `config template` |
| W2 | No string literal in `src/solar_challenge/**/*.py` outside `timebase.py` equals an ISO date (`^\d{4}-\d{2}-\d{2}$`), and no file in `web/static/js` or `web/templates` contains one | α's AST scan (Python); β's text scan (templates and scripts, which have no other per-task test seam) |
| W3 | The rendered pages' window defaults equal the constants: the home and fleet pages' custom window, the fleet page's n-day window start, and the builder's start, end and period presets | β's page test, beside S11 γ's `test_web_tariff_presets.py` |

### 4.3 The per-type table (γ; owner `fleet_distribution.py`)

```python
@dataclass(frozen=True)
class SpecParameter:
    key: str              # grammar key, e.g. "std"
    title: str            # "Std Dev"
    required: bool = True # normal's min and max are optional clamps

@dataclass(frozen=True)
class SpecRows:
    paired_key: str       # "weights" | "counts"; the value list is always "values"
    paired_title: str     # "Weight" | "Count"
    paired_kind: FieldKind  # S7: NUMBER for weights, COUNT for counts

@dataclass(frozen=True)
class DistributionType:
    name: str             # the type: tag
    title: str            # "Normal (Gaussian)"
    build: Callable[[Mapping[str, Any], str], DistributionSpec]   # (spec mapping, block_path) -> spec
    parameters: tuple[SpecParameter, ...] = ()
    rows: Optional[SpecRows] = None
    unheld_keys: tuple[str, ...] = ()   # keys an editor has no input for
    @property
    def recognised_keys(self) -> frozenset[str]: ...   # {"type"} | parameters | rows | unheld_keys
    @property
    def editable(self) -> bool: ...                    # not unheld_keys
    def write(self, spec: DistributionSpec) -> dict[str, Any]: ...   # build(write(s)) == s

DISTRIBUTION_TYPES: Mapping[str, DistributionType]   # weighted_discrete, normal, uniform, fixed, shuffled_pool, proportional_to
def write_distribution_spec(spec: DistributionSpec) -> object: ...   # number or None for the scalar form, else the type's write
def editor_types(kind: FieldKind) -> tuple[DistributionType, ...]: ...  # S7 F2's accepted types for kind, editable, not `fixed`
```

Invariants:

| # | Invariant | Enforced by |
|---|---|---|
| T1 | `parse(write_distribution_spec(s)) == s` for a spec of every type, the scalar and null forms included | γ, parametrised over `DISTRIBUTION_TYPES` |
| T2 | The parser's recognised keys and its unknown-type message come from `DISTRIBUTION_TYPES`; no other module names a distribution type tag | γ's test; δ's scans of `web/` (Python, templates, scripts) for the tags `normal`, `uniform`, `weighted_discrete`, `shuffled_pool`, `fixed` and `proportional_to` |
| T3 | γ changes no parsed value and no message: the shipped scenarios validate as before, and S7 γ's generation pins stay equal | the existing suite; `validate config` on `scenarios/*.yaml`; S7's pins |
| T4 | The editor offers, for each component, exactly `editor_types(kind of its field)` plus Fixed Value | δ's page test |

### 4.4 Editor state and wire shape (δ; owner `distribution-editor.js`, rendered from the table)

```text
dist   = { type: "" | <editable name>, fixed: number | "", specs: { <name>: { <param>: number | "", values: [...], <paired_key>: [...] } } }
wire   = dist.type === "" ? nullIfBlank(dist.fixed)
                          : { type: dist.type, ...nullIfBlank(dist.specs[dist.type]) }
load(spec) = number | null      -> type "", fixed = spec ?? ""
             { type: t, ... }   -> type t, specs[t] = { ...specs[t], ...spec without "type" }
```

- The page renders, into each editor scope, the component's `editor_types` with their parameters and rows, and its starting state from `page_limits().components[key].start`.
- The fleet form and the builder form both carry `{pv: {capacity_kw: wire}, battery: {capacity_kwh: wire} | absent, load: {annual_consumption_kwh: wire}}`. The server reads those blocks as the `fleet_distribution:` block's.
- An import answers each component as `write_distribution_spec(parse(spec))` when its type is editable. It refuses any other type, naming the path and the types the editor holds.

### 4.5 Preview (ε; default of lead question 1)

```text
POST /api/fleet/preview-distribution   body: the fleet form (as /api/simulate/fleet-from-distribution)
200 { "homes": n, "values": { "pv": [kW per home], "battery": [kWh per home, 0 for none], "load": [kWh per home, null when the home's load is unscaled] } }
400 { "error": <the refusal parse_fleet_form or refuse_homes_outside_ranges raises> }
```

The values are in home order, as `parse_fleet_form(form).homes` holds them. Each is read through the component's `ComponentLimits` key and grammar key, as `refuse_homes_outside_ranges` reads it.

### 4.6 Import answer (ζ; owner `web/scenario_import.py`)

`ImportedForm(form: Mapping[str, Any], not_loaded: tuple[str, ...])` is the existing `ImportedFleetForm`, renamed for both pages.
- Each page states what its form holds.
- Refusal order: the loaders' refusal first; then a setting the form needs but cannot hold exactly, by name; and then, after reading, the form's own reader (`parse_fleet_form` or `builder_form_errors`), so a loaded form always runs.
- The answer is `{form, not_loaded}`, HTTP 200, on `/api/fleet/import-yaml`, `/api/fleet/presets/<name>`, `/api/scenarios/import-yaml` and `/api/scenarios/presets/<name>`.

### 4.7 Fleet form vocabulary (η; owner `web/fleet_scenario.py`)

```python
@dataclass(frozen=True)
class FormSetting:
    key: str                   # the grammar key, e.g. "import_limit_kw"
    title: str
    within: Interval
    step: float
    start: Any                 # the form's starting value; economy rates from tariff.PRESET_RATES
    read: Callable[[Any, str], Any]   # how an import reads the scenario's value (today's _required / _one_peak_window)

@dataclass(frozen=True)
class FormChoice:
    type: str                  # the grammar tag
    title: str
    settings: tuple[FormSetting, ...]

FLEET_FORM_TARIFFS: tuple[FormChoice, ...]
FLEET_FORM_DISPATCH: tuple[FormChoice, ...]   # one per dispatch.STRATEGY_CONFIG_BY_TYPE entry, its order
# The flat_rate setting starts at page_limits().flat_rate_start (0.28), which the home and builder forms read too.
```

| # | Invariant | Enforced by |
|---|---|---|
| V1 | `[c.type for c in FLEET_FORM_DISPATCH] == list(STRATEGY_CONFIG_BY_TYPE)`, and each choice's setting keys equal its config's init fields | built at import by iterating the server table; a missing title raises `KeyError` at import |
| V2 | Each `FLEET_FORM_TARIFFS` type is one the grammar reads; each economy choice starts at `PRESET_RATES[type]` | import-time check; S11 γ's test (tariff half of invariant 11) |
| V3 | The page's options, setting inputs and their bounds are the tables' | η's page test |

## 5. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| W1 | CLI | default window | — | `home run`, `fleet run`, `fleet sweep` and `finance run` have `--start` default `DEFAULT_FIRST_DAY.isoformat()` and `--end` default `DEFAULT_LAST_DAY.isoformat()`, or None where S6's option pair has landed; `config template scenario` writes the pair | α |
| W2 | grammar scan | no date literal | src tree; a seeded `tmp_path` module holding `"2024-03-01"` | the scan names the seeded file and line; the real tree passes | α (Python), β (templates and scripts) |
| L1 | pages | limits rendered | Flask test client | the four pages' `#page-limits` JSON equals `page_limits().as_json()`; the fleet `n_homes` input has `min=1 max=10000`; the builder's has the same; the home page's PV check reads `0.5`/`20` from the JSON, with no literal in the template | β |
| L2 | home reader | battery range | P1 | 400 naming `battery_kwh`, the range 0–100 and 500 (today: 200) | β |
| L3 | fleet reader | fixed and drawn values | P3; then `pv.capacity_kw: {normal, mean 50, std 1}` | 400 naming `pv.capacity_kw`, a home number, the range and the value (today: 201) | β |
| L4 | builder | drawn value | P15 | `/api/scenarios/validate` lists the range error (today: valid) | β |
| L5 | fleet page | size | P11 with 2000; then 10001 | 2000 runs (201); 10001 gives 400 naming `n_homes` and 10,000 | β |
| W3 | pages | window defaults | — | each page's window defaults equal the constants (§4.2 W3); with S11 γ's test, invariant 11 holds | β |
| T1 | grammar | write is the inverse | one spec of each type, plus a number and null | `parse(write(s)) == s` | γ |
| T3 | grammar | no change | shipped scenarios; S7 γ pins | `validate config` OK; pins equal | γ |
| E1 | both pages | one wire shape | for every editable type × component, the starting spec posted as the fleet form and as the builder form | both forms' `fleet_distribution` blocks parse to equal `ComponentDistribution` draws | δ, θ |
| E2 | fleet page | no invented defaults | P4 | 400 naming the missing `mean` (and `std`): the builder's message (RED at `ede1d99`: N(0, 1); task 313 may remove the invented defaults first, and δ keeps the rule) | δ |
| E6 | both pages | a broken invariant is named (584) | `pv.capacity_kw: {normal, mean 4, std 1, min 9, max 2}` | 400 naming `pv.capacity_kw` and the inverted clamps, on both pages | δ |
| E7 | both pages | 697's guarantee | n_homes 10, pool counts `[10**12]` | refused naming the pool's counts and n_homes, before any pool is built (F6 at parse; the size bound before generation) | δ |
| E3 | both pages | imports agree | `{type: fixed, value: 4}`; a normal without clamps; a `proportional_to` | both pages load the first two (fixed as `4.0`; the normal's clamps blank) and refuse the third naming the path and the editable types (today: the builder throws on `fixed`, the fleet page refuses the unclamped normal: P13) | δ (fleet), ζ (builder) |
| E4 | editor | pages render the table | `/simulate/fleet` and `/scenarios/builder` | each editor's options are Fixed Value plus `editor_types`, titled by the table; no type tag literal in `distribution-editor.html`, `distribution-editor.js`, `fleet-simulator.js` or `scenario-builder.js` | δ |
| E5 | browser | the editor posts the spec | Playwright on both pages: choose each type in the PV card and run or validate | the request body's `pv.capacity_kw` equals the same grammar spec on both pages | δ (e2e), θ |
| P1 | preview | Run's homes | the fleet page's starting form | the answer's `values.pv` equals `[h.pv_config.capacity_kw for h in parse_fleet_form(form).homes]` | ε |
| P2 | preview | refusals | P8, P9, P10's specs in the PV card, with n_homes 6 for P10 | 400 with Run's messages: inverted clamps, negative weight, and pool counts 3 ≠ 6 (today: samples) | ε |
| P3 | browser | preview shown | Playwright: click Preview | each card shows its summary; a refused form shows the error | ε (e2e) |
| B1 | builder | upload | an Economy 7 scenario; a SEG-preset scenario; a scenario with a battery `dispatch_strategy` | the first two are refused naming `tariff.type` and `seg.preset`; the third loads, with `not_loaded` naming the dispatch path (today: silently dropped) | ζ |
| B2 | builder | presets | the built-in `bristol-phase1`; a preset saved from the builder | each loads every field the builder holds: distributions, seed, period as ISO strings, and location. `not_loaded` names `fleet_distribution.random_order`, `pv.azimuth`, `pv.tilt` and `finance`. A saved preset reloads equal to what was saved (today: name only, `\|\| 51.45`) | ζ |
| B3 | builder | old saved preset | a `config_presets` row holding a flat form | 400 naming the preset and saying it must be saved again (lead question 2) | ζ |
| B4 | builder | save validates | a form `builder_form_errors` refuses | 400 with the errors; nothing is stored | ζ |
| V1 | fleet page | vocabulary | `/simulate/fleet` | its tariff and dispatch options and setting inputs are `FLEET_FORM_TARIFFS`/`FLEET_FORM_DISPATCH`'s; `tou_optimized` offers the tariff's clock | η |
| V2 | fleet import | tariff-clocked TOU | a scenario with `dispatch_strategy: {strategy_type: tou_optimized}` and an Economy 7 tariff | loads, with the clock choice selected; it runs (today: refused by `_one_peak_window`) | η |
| V3 | forms | flat-rate start | the three pages | each starts its flat rate at `page_limits().flat_rate_start` | η |
| G1 | integration | one table, one limits value, both pages | θ's module | E1, E3 on both pages, the L1 and V3 page checks, and an export → import round trip on each page, all in one module | θ |

## 6. Existing tasks this PRD meets

Statuses read 2026-10-17. Each disposition is re-checked at decompose, after contract §8 step 1, by re-reading the task's status and claimant immediately before cancelling it. An in-progress target becomes a dependency edge instead of a cancellation.

| Task | Status at authoring | What it changes | Disposition |
|---|---|---|---|
| 313 | **in progress** (claimant live; amend-round review) | replaces `_build_distribution_dict` with a public `distribution_grammar_spec` that invents no defaults, used by both readers | δ depends on 313. δ then deletes that function and keeps its rule: the grammar's own refusals, no invented defaults |
| 394 | pending; branch finished, port run ruled | one `refuse_unrecognised_keys` for the home, builder and fleet bodies (S17 β moves it to `request_boundary`) | δ depends on 394, since δ changes both forms' recognised keys |
| 376 | pending (fk-f8b7b3ab709d) | the builder's and fleet page's size bounds | superseded by β |
| 612 | pending; **re-planned 2026-10-17 and dispatchable** | the home page's 0.5–20 PV bound in four places, the assistant's two included | superseded by β. **The lead holds it now** (§11 action 1) |
| 664 | pending | a neutral context name for the home page's bounds | superseded by β (`page_limits`) |
| 611 | pending | the fleet script and readers restate component keys; Run applies no fixed-value range | superseded by β (range) and δ (keys); `x_superseded_by` δ |
| 676 | pending, depends on 612 | whether the PV bound also bounds drawn fleet values and a saved home preset's `pv_kw` | kept. Decision 2 answers its distribution half. Its dependency moves from 612 to β, and it keeps the saved-home-preset half |
| 753 | pending (fk-3cd0d3f3b512) | comment and docstring trimming in `fleet_config.py` | superseded by δ, which carries the key |
| 424 | pending (narrowed at S17's decompose to `fleet_config._require_dict`) | one "must be a mapping" mechanism | superseded by δ: the function goes, and the grammar's `require_mapping` reads the blocks |
| 592 | pending | an unrecognised component key sent as a string is read as a bad number | superseded by δ: the blocks reach the grammar, which refuses the key with its own message |
| 584 | pending, depends on 921 and 935; brought here by L38 | the fleet route refuses a distribution that breaks config's invariants without naming it | superseded by δ (row E6). The path comes from S4 ζ's (868) `_constructed`, which is upstream of δ through γ |
| 569, 571 | pending | the preview's refusals and its copy sampler | superseded by ε (or ε′) |
| 298 | pending; **branch finished (14/14); esc-298-3 closed, so it can re-dispatch** | the builder's preset and upload restore every field and refuse what they cannot hold (in the browser) | superseded by ζ, which does it on the server. **The lead holds it now** (§11 action 1) |
| 545, 549, 553, 554 | pending, depend on 298 | which built-ins the builder lists; `.nan`/`.inf` uploads; copied grammar keys; unquoted dates reaching the form as HTTP-date text | superseded by ζ. ζ's answers carry ISO dates (B2), the loaders refuse a non-finite number (S4), and the builder lists only the built-ins it loads |
| 360 | pending, depends on 298 | the builder cannot hold a pool's null ("no battery") value | superseded by δ: a blank pool value posts null |
| 359 | pending; branch 7/8 | the scenario preset lookup lets a built-in shadow a saved preset and ignores the preset type | superseded by ζ, which reads presets by source and by `type = 'fleet'`. Reuse its branch's lookup |
| 140 | pending (deps 123, 128, 835) | the sweep page's configuration from the server | kept. No edge: the sweep's parameters are S26's and 140's. 140 renders through β's `#page-limits` channel if β has landed |
| 297 | pending (high) | exact pool counts (F6) | upstream through 921; no edge |
| 697 | done (fk-9dd1d9389dd2) | the builder bounds pool counts | δ keeps its guarantee (row E7) and its tests, reshaped |
| 395, 509 | pending | occupants rounding; one unrecognised-key rule | unrelated |
| 759 | pending (fk-94cab00e114e), depends on 956 | the default-window constants in `config.py` | superseded by α and 956 (L44); α carries its key |
| 844 | pending (keyless; found by the decompose's step-2 search) | the fleet form drops a distribution's keys its type does not read | delivered by δ: the blocks reach the grammar, which refuses unrecognised keys. Not ruled: it gains an edge on δ, and cancelling it is recommended to the lead |
| 754 | pending (fk-d8ad51b22de5, `/review` run; branch 3 ahead) | `_read_battery`'s docstrings over `_null_capacity_as_zero` | δ deletes `_null_capacity_as_zero` and rewrites `_read_battery`. Not ruled: it gains an edge on δ, and cancelling it is recommended to the lead |
| 811 | pending (S19 δ) | saved presets owned by `presets.py`; the get filters `type = 'fleet'` | ζ overlaps it in `presets.py` and `api.scenarios_get_preset`; no edge, second lands rebases, and ζ reads presets through `presets.py`'s functions if 811 has landed |

## 7. Cross-PRD relationship

| Other stream / PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S5 `scenario-grammar-partition.md` | consumes | `fleet_distribution.py` exists; γ edits `_DISTRIBUTION_SPEC_TYPES` and `_parse_distribution_spec` there by their final names | S5 layout, S18 table (D18) | γ depends on S5 γ (id from the lead) |
| S7 `component-defaults-one-home.md` | consumes | F2's kind → accepted spec types; `FieldKind`; the fleet rows naming each component field's kind; γ's `draw` and path-keyed sampler (the preview generates through it); F6 exact pool counts (L35); `HEAT_PUMP_TYPES` (911) and `CHARGER_TYPES` (919) | S7 | γ depends on 921 (ε), which follows 911, 914, 916 and 919. η renders the home page's heat-pump options from `HEAT_PUMP_TYPES` and depends on 911. No page offers EV charger types, so `CHARGER_TYPES` has no S18 reader yet (§9) |
| S4 `finite-quantities.md` | consumes | `number_fields.Interval` and `within=` (860); the fleet grammar reads its numbers at construction (868); the web stops pre-reading numbers and `_build_distribution_dict` becomes shape-only (870), which δ then deletes | S4 | β depends on 860; γ on 868; δ on 870 |
| S17 `web-request-boundary.md` | consumes | the request-reading module, `present_fields`, `ConfigurationError` → 400 translator (935); `fleet_config`'s refusals become `ConfigurationError` (935); builder location reading (933) | S17 | δ depends on 937 (which follows 931–935), so δ rewrites S17's converted readers rather than S17 converting δ's. S18's new refusals raise `ConfigurationError` |
| S11 `tariff-coverage-classifier-presets.md` | consumes | `tariff.PRESET_RATES` and its rendering into both simulate pages (841); optional `TOUOptimizedStrategyConfig.peak_hours` (839); 841's `test_web_tariff_presets.py` is invariant 11's tariff half | S11 | η depends on 839 and 841; β's window half sits beside 841's test (no edge) |
| S2 `dispatch-configuration-below-config.md` | consumes | `dispatch.STRATEGY_CONFIG_BY_TYPE` and the strategy configs (786) | S2 | η depends on 786 |
| S21 `chart-panels-and-theme-tokens.md` | file overlap; macro offered | β 830 moves `fleet.html`'s cards to `component-*` classes; θ 836 converts its card copies to `card`; the form-label macro is S18's (decision 14) | S21 / S18 | no edge: whichever lands second rebases by symbol. After 830, S18's template edits use the role classes; after 836, the `card` macro |
| S10 `simulation-window-and-cadence.md` | file overlap | α adds `SHORT_WINDOW_START` to `timebase.py` | S10 module, S6 and S18 constants | textual |
| S6 `one-scenario-reader.md` | consumes | D11's default window is `timebase.DEFAULT_FIRST_DAY`/`DEFAULT_LAST_DAY` (956, L42), which α reads; S6's option pair (958, 959, 960) replaces the CLI defaults' literal form and keeps W1 true; S6 η (961) deletes `apply_fleet_overlay` (fk-a391cf1f4edf) and the restated loader order, and reads the dashboard's documents through `parse_scenario`; ζ then moves the `parse_scenario`-based readers into `web/scenario_import.py` (L42) | S6 | α depends on 956; ζ depends on 961; δ and 961 overlap textually in `fleet_scenario.py`, no edge, second lands rebases |
| S26 sweep knob registry | produces for | the sweep page's parameter options and ranges (`parameter-sweep.js` `parameterOptions`) render from S26's registry; their value bounds may read `ComponentLimits.value_range` | S26 | proposed cross-reference; no S18 leaf edits the sweep's parameters (β renders only `sweep.html`'s window bound) |
| S22 `assistant-facts-from-engine.md` | file overlap | β renders `assistant.py`'s two PV tool descriptions from `value_range`; 751 restructures the tools | S22 | textual |
| S29 surface bump | none | `timebase`'s new constants are not frozen-surface names (re-checked at α); `DISTRIBUTION_TYPES` is not exported | — | — |

## 8. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries:
- `x_finding_key` (list), `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`;
- priority = the highest severity among its keys;
- file-level `metadata.files`.

Every leaf that changes a template or a script rebuilds and commits `web/static/dist/style.css`. CLAUDE.md gives the command, with `npm ci --cache /tmp/<dir>` in a sandbox. When npm is unreachable, the lane's css-build job is the guard (D22, D40).

Script behaviour runs only in the lane's e2e job. Each script-changing leaf updates and adds its e2e tests. It runs them locally with `uv run --locked --extra dev --extra web --extra e2e pytest <files> -p no:cacheprovider` when Chromium is installed.

**α — The CLI, its templates and the web read `timebase`'s default window; the invariant 11 window test** (leaf; priority medium; `x_finding_key: [fk-94cab00e114e]` from task 759, which it supersedes with 956 (L44); `metadata.x_invariant = 11`)

- **Modules:**
  - `src/solar_challenge/timebase.py` (`SHORT_WINDOW_START` only; 956 defines `DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY`);
  - `cli/home.py` (`run`'s defaults unless 958 has landed; `quick`'s start);
  - `cli/fleet.py` (`run` and `sweep`, unless 960 has landed);
  - `cli/finance.py` (unless 959 has landed);
  - `cli/optimize.py` (the period fallback, unless 959 has deleted it);
  - `cli/config.py` (`HOME_TEMPLATE` and `SCENARIO_TEMPLATE` formatted from the constants);
  - `web/simulation_params.py` (`FULL_YEAR_*` and `DAYS_WINDOW_START` become the `timebase` names);
  - `web/assistant.py` (imports those names for its tool descriptions);
  - new `tests/unit/test_window_defaults.py` (W1, W2's Python scan, seeded); `tests/unit/test_web_simulation_params.py`, `tests/unit/test_cli_home_quick.py`, `tests/unit/test_cli.py`;
  - `review/briefing.yaml` (invariant 11's conventions line names both halves' tests; S11 γ writes it if it lands first, else α writes it and S11 γ extends it);
  - `docs/domain-library-consumption.md` (Unreleased: `SHORT_WINDOW_START`).
- **Work:**
  - §4.2.
  - Help-text examples (`--start 2024-01-01 --end 2024-01-07`) are prose inside longer strings and stay.
  - S6 δ, ε and ζ (958, 959, 960) overlap textually in `cli/home.py`, `cli/finance.py`, `cli/optimize.py` and `cli/fleet.py`, with no edge. A command still holding a literal default at α's base reads the constants; a command already on the option pair is left alone.
  - Check at the leaf's base whether `timebase` is frozen surface. It is not at `beb1d91`; if it is, the addition is additive under D29.
- **Signal:**
  - W1: `solar-challenge home run --help` shows the constants' defaults, or the option pair's help naming them, and the test reads every command's parameters.
  - W2: the seeded literal is named; the real tree passes.
  - `config template scenario` writes `start_date: "2024-01-01"` from the constant.
- **Consumer:** CLI users; β (pages); S6's period policy.
- **Prereqs:** 956 (S6 β: `DEFAULT_FIRST_DAY`, `DEFAULT_LAST_DAY`).

**β — `PageLimits`: every form bound rendered from one value; one range per component in every reader** (leaf; priority medium)

- **Keys:** fk-1df9dbc0d971, fk-f8b7b3ab709d, fk-366773b4083f.
- **Modules:**
  - `web/fleet_components.py` (§4.1; `MAX_FLEET_HOMES`, `MAX_FLEET_SEED`, `read_fleet_size` and `read_fleet_seed` from `fleet_config`; `MAX_WINDOW_DAYS` and `FULL_YEAR_DAYS_SENTINEL` from `simulation_params`; `fixed_range` → `value_range`; `refuse_homes_outside_ranges`; module docstring);
  - `web/app.py` (the context processor);
  - `web/fleet_config.py` (the moved names leave; importers repointed);
  - `web/simulation_params.py` (`pv_kw`, `battery_kwh` and `consumption_kwh` read `within=` the ranges; the PV literal goes);
  - `web/fleet_scenario.py` (`parse_fleet_form` refuses homes outside the ranges);
  - `web/builder_form.py` (`_dashboard_limit_errors`' fixed-value loop becomes the homes check after the loader; `_home_count_allowed` reads `PageLimits.fleet_size`);
  - `web/scenarios.py` (the sweep route stops passing `max_window_days`);
  - `web/assistant.py` (the two PV descriptions render from `value_range`);
  - `templates/base.html` (`#page-limits`);
  - `templates/components/macros.html` (`number_field`, decision 14);
  - `templates/simulate/fleet.html` (size input, slider and captions; day choices);
  - `templates/simulate/home.html` (the PV check, `consumptionRange`, start and end);
  - `templates/scenarios/builder.html` (size input; period buttons);
  - `templates/scenarios/sweep.html`;
  - `templates/components/distribution-editor.html` (the fixed input's bounds from `value_range`; `_parameter` → `number_field`);
  - `static/js/fleet-simulator.js` (size, seed, days and dates from `#page-limits`; `formErrors` and every `parseInt` deleted);
  - `static/js/scenario-builder.js` (start, end, size and `setPeriod` from `#page-limits`);
  - `tests/unit/test_window_defaults.py` (W2's template and script scan, W3);
  - `tests/unit/test_web_fleet_components.py`, `test_web_simulate_forms.py`, `test_web_simulation_params.py`, `test_web_builder_form.py`, `test_web_fleet_scenario.py`, `test_web_fleet_config.py`, `test_web_scenarios.py`, `tests/unit/web_api/test_fleet_distribution.py`, `test_assistant*.py` (the descriptions);
  - e2e: `test_fleet_interactions.py`, `test_page_errors.py`, `test_home_simulation.py`;
  - `docs/web-ui-design.md` (the limits section names `fleet_components.page_limits`);
  - `static/dist/style.css`.
- **Work:**
  - §4.1 and decisions 1–4 and 14.
  - The `start` field carries today's `builder_default` editor state until δ replaces it.
  - Supersedes 376.
- **Signal:**
  - L1–L5 and W3.
  - The home page refuses a 500 kWh battery with 400 naming `battery_kwh`, 0–100 and 500 (RED: P1 runs it).
  - The fleet page runs 2,000 homes (RED: the input caps at 500 and the script refuses above 1,000) and refuses 10,001 by name.
  - The builder lists the range error for P15 (RED: valid).
  - `grep -E "1000|max=\"500\"|max=\"10000\"|0\.5 \|\| pv > 20|'2024-" static/js templates` finds none of the retired values.
- **Consumer:** dashboard users of the home, fleet and builder pages; the assistant's tool schema; δ, ε and η (the channel and the macro); S26 (`value_range`).
- **Prereqs:** α, 860 (S4 α: `Interval`), 774 (S1 β: `ConfigurationError` is a `ValueError`, so today's route catches answer it until S17 δ's translator lands).

**γ — The per-type distribution table in `fleet_distribution.py`** (intermediate; unlocks δ, ε, ζ; priority high)

- **Keys:** fk-8107696f0b02, fk-a6d9f3e5a7e2.
- **Modules:**
  - `src/solar_challenge/fleet_distribution.py` (§4.3: `DISTRIBUTION_TYPES` replaces `_DISTRIBUTION_SPEC_TYPES`; `_parse_distribution_spec` reads it; `write_distribution_spec`; `editor_types`);
  - `tests/unit/config/test_distribution_types.py` (new: T1, T2, T4's table half);
  - `tests/unit/config/test_fleet_distribution_block.py`;
  - `docs/domain-library-consumption.md` (Unreleased: `fleet_distribution.DISTRIBUTION_TYPES` is the per-type table of the distribution grammar).
- **Work:**
  - §4.3 and decision 6. The builders keep their bodies; S4 ζ (868) has rewritten their number reads, so γ moves them into the records by name.
  - `editor_types` reads S7 F2's rule by the name S7 ε gives it. If 921 leaves the rule private, γ makes it public where it stands, without moving it.
  - Records `title`s: "Fixed Value", "Normal (Gaussian)", "Uniform", "Weighted Discrete", "Shuffled Pool", "Proportional To"; parameter titles from today's editor captions ("Mean", "Std Dev", "Min (clamp)", "Max (clamp)", "Min", "Max", "Value", "Weight", "Count").
- **Signal:**
  - T1 and T3. `validate config` prints "Configuration is valid" on every shipped scenario, and S7 γ's generation pins stay equal.
  - `grep -n "_DISTRIBUTION_SPEC_TYPES" src` finds nothing.
- **Consumer:** δ (editor and readers), ε (preview), ζ (import), S26 (a sweep knob's spec types, if it reads them).
- **Prereqs:** 947 (S5 γ), 921 (S7 ε), 868 (S4 ζ).

**δ — One wire shape: both fleet pages edit and post the grammar's spec** (leaf; priority high)

- **Keys:** fk-a6d9f3e5a7e2, fk-8107696f0b02, fk-366773b4083f, fk-c3625a25eed4, fk-3cd0d3f3b512, fk-021a21b35427.
- **Modules:**
  - `web/fleet_components.py` (`start` built from `fleet_distribution` specs, decision 9; `fixed_field` deleted; `ComponentLimits.start` from it);
  - `web/fleet_config.py` (the decision-7 deletions);
  - `web/builder_form.py` (the decision-7 deletions; the form's component blocks read as the `fleet_distribution:` block's; `_RECOGNISED_KEYS` from `FLEET_COMPONENTS` keys);
  - `web/fleet_scenario.py` (`parse_fleet_form` builds the block from the form's blocks; `_read_component` and `_read_battery` per §4.4; `_null_capacity_as_zero` deleted);
  - `web/scenarios.py` (`_script_components` deleted: the page reads `#page-limits`);
  - `templates/components/distribution-editor.html` (options, parameter inputs and row lists rendered from `editor_types`; no type literal);
  - `static/js/distribution-editor.js` (`wire`, `load`, generic rows over parallel lists);
  - `static/js/fleet-simulator.js` (`pvDist`/`batteryDist`/`loadDist` from `#page-limits`; `_buildDistPayload` and `_distFromConfig` deleted; `buildPayload` and `applyConfig` call the editor);
  - `static/js/scenario-builder.js` (`componentFormData` deleted; `getFormData` posts the blocks; `componentDistribution` and `distributionRows` become the editor's `load`);
  - `templates/simulate/fleet.html`, `templates/scenarios/builder.html`;
  - `tests/_fleet_form.py`;
  - `tests/unit/test_web_fleet_config.py`, `test_web_builder_form.py`, `test_web_fleet_scenario.py`, `test_web_fleet_components.py`, `test_web_scenarios.py`, `test_web_simulate_forms.py`;
  - `tests/unit/web_api/test_fleet_distribution.py`, `test_fleet_yaml.py`;
  - `tests/integration/test_web_fleet_distribution.py`;
  - e2e: `test_fleet_interactions.py`, `test_fleet_simulation.py`, `test_scenario_builder.py`, `_scenario_builder_page.py`, and a new `test_distribution_editor_wire.py` (E5);
  - `docs/web-ui-design.md`;
  - `static/dist/style.css`.
- **Work:**
  - Decisions 7–9 and 15 (form-conversion half), and §4.4.
  - The docstrings of the rewritten readers state each public reader's contract once. No Raises section traces the private call graph.
  - Record `fleet_config.py`'s and `fleet_scenario.py`'s post-change docstring share (fk-021a21b35427).
  - Supersedes 753. Further supersessions per §6.
- **Signal:**
  - E1–E7. The fleet page's `{type: normal}` gets 400 naming `mean` and `std` (RED P4: runs as N(0, 1)). Both pages load `{type: fixed, value: 4}` and a normal without clamps (RED: P13 refuses the second on the fleet page, and the builder's script throws on the first).
  - `grep -nE "'(normal|uniform|weighted_discrete|shuffled_pool)'" static/js/*.js templates/components/distribution-editor.html` finds none.
  - The functions of decision 7 are gone (grep).
- **Consumer:** fleet-page and builder users; ε, ζ and η build on the shape.
- **Prereqs:** γ, β, 870 (S4 η), 937 (S17 ε), 313 (in progress), 394.
- **Refusal paths:** both readers parse the form's blocks with the form's own path (`pv.capacity_kw…`), not `fleet_distribution.…`, so a refusal names the field the page posted.

**ε — The fleet page previews the homes Run builds** (leaf; priority medium; lead question 1 may replace it with the deletion variant ε′)

- **Keys:** fk-7893b49b92c3, fk-88374e6e3553, fk-c3625a25eed4.
- **Modules:**
  - `web/api.py` (`preview_distribution` per §4.5);
  - `web/fleet_config.py` (`sample_distribution` and `_draw_samples` deleted; module docstring: the fleet-wide overlay);
  - `templates/simulate/fleet.html` (the Preview action and each card's summary);
  - `static/js/fleet-simulator.js` (`preview()`);
  - `tests/unit/web_api/test_fleet_distribution.py`, `tests/unit/test_web_fleet_config.py`;
  - e2e: `test_fleet_interactions.py` (P3);
  - `docs/web-ui-design.md`;
  - `static/dist/style.css`.
- **Work:**
  - Decision 10 and §4.5.
  - The summary lists value × homes when the values take at most 8 distinct values, else min, median and max. The format is tactical.
- **Signal:**
  - P1–P3. P8, P9 and P10 are refused with Run's messages (RED: today they sample).
  - `grep -n "_draw_samples\|def sample_distribution" src` finds nothing.
- **Consumer:** fleet-page users (Preview).
- **Prereqs:** δ.
- **ε′ (if lead question 1 rules deletion):**
  - Delete the endpoint, `sample_distribution`, `_draw_samples` and their tests.
  - Signal: `POST /api/fleet/preview-distribution` answers 404, and the grep is empty.
  - Same keys, same prereq.

**ζ — The builder imports scenarios and presets on the server, under the fleet page's policy** (leaf; priority medium)

- **Keys:** fk-40dff1473b94 (weakened, measurement recorded), fk-d303b6dbf669, fk-021a21b35427.
- **Modules:**
  - `web/scenario_import.py` (new: decision 11's moved readers and `ImportedForm`);
  - `web/fleet_scenario.py` (keeps the fleet form's holdings and imports the shared readers);
  - `web/builder_form.py` (`builder_form_from_scenario`; the `seed` field);
  - `web/presets.py` (saved fleet presets read by type; task 359's lookup);
  - `web/api.py` (`/api/scenarios/import-yaml`; `scenarios_get_preset` answers `{form, not_loaded}`; `scenarios_save_scenario` validates and stores the document; decision 12's refusal);
  - `web/fleet_presets.py` / `web/builtin_scenarios.py` (the builder's preset menu offers the presets it loads, as `fleet_preset_names` does for the fleet page);
  - `templates/scenarios/builder.html` (js-yaml tag deleted; a not-loaded notice);
  - `static/js/scenario-builder.js` (`uploadYaml` posts the text; `loadPreset` applies `{form, not_loaded}`; `scenarioFormFields` and the `|| 51.45` reads deleted);
  - `static/vendor/js-yaml/` (deleted);
  - `tests/unit/test_web_page_scripts.py` (the js-yaml pin goes);
  - `tests/unit/test_web_scenarios.py`, `tests/unit/web_api/test_presets.py`, `tests/unit/test_web_builder_form.py`, `tests/unit/test_web_fleet_scenario.py`;
  - e2e: `test_scenario_builder.py`, `_scenario_builder_page.py`;
  - `docs/web-ui-design.md` (one import-policy section for both pages, replacing `fleet_form_from_scenario`'s prose);
  - `static/dist/style.css`.
- **Work:**
  - Decisions 11 and 12, and §4.6.
  - Record `fleet_scenario.py`'s post-change docstring share.
- **Signal:**
  - B1–B4, and E3 on the builder.
  - Uploading `scenarios/bristol-phase1-flex.yaml` (a fleet with an Economy 7 tariff) to the builder is refused naming `tariff.type` (RED: it loads with `import_rate: ''`, and the next save writes `tariff: null`).
  - Loading `bristol-phase1` fills its distributions, period and location (RED: name, size and coordinates only).
  - `grep -rn "jsyaml\|js-yaml" src/solar_challenge/web` finds nothing.
- **Consumer:** builder users; S6 (`scenario_import.py` is where its overlay reader replaces the loaders-first refusal).
- **Prereqs:** δ; 961 (S6 η, L42), after which ζ moves the `parse_scenario`-based readers into `web/scenario_import.py`.

**η — The fleet form's tariff and dispatch choices from the server's tables** (leaf; priority low)

- **Keys:** fk-006c3339e3b2.
- **Modules:**
  - `web/fleet_scenario.py` (§4.7 replaces `_FORM_TARIFF_SETTINGS` and `_FORM_DISPATCH_SETTINGS`);
  - `web/routes.py` (the fleet and home pages render the tables);
  - `web/fleet_components.py` (`PageLimits.flat_rate_start`);
  - `templates/simulate/fleet.html` (options and setting inputs in loops through `number_field`; the TOU clock choice);
  - `templates/simulate/home.html` / `templates/simulate/partials/tariff-config.html` (the flat-rate start);
  - `templates/simulate/partials/heat-pump-config.html` (type options from `HEAT_PUMP_TYPES`);
  - `static/js/fleet-simulator.js` (`buildPayload`'s tariff and dispatch parts and `_applyTariff`/`_applyDispatch`, generic over the tables);
  - `static/js/scenario-builder.js` (the flat-rate start);
  - `tests/unit/test_web_fleet_scenario.py`, `test_web_simulate_forms.py`;
  - e2e: `test_fleet_interactions.py`, `test_enable_switches.py`;
  - `static/dist/style.css`.
- **Work:**
  - Decision 13 and §4.7.
  - The TOU default window stays S11 β's 16–19 (L11), as the custom-window choice's start.
- **Signal:**
  - V1–V3. Importing a tariff-clocked `tou_optimized` loads and runs (RED: refused by `_one_peak_window` once S11 β lands; today the grammar requires `peak_hours`, so V2 is RED by construction).
  - `grep -nE "'(flat_rate|economy_7|economy_10|self_consumption|tou_optimized|peak_shaving)'" static/js/fleet-simulator.js templates/simulate/fleet.html` finds none.
  - No `0.28`/`0.245` literal remains in `static/js` or the templates.
  - No `value="ASHP"`/`value="GSHP"` literal remains in the templates.
- **Consumer:** fleet-page and home-page users.
- **Prereqs:** δ (same files), 786, 839, 841, 911.

**θ — Integration gate: both fleet pages edit, post, import and bound every distribution from one table** (leaf; priority medium)

- **Keys:** fk-a6d9f3e5a7e2, fk-1df9dbc0d971.
- **Modules:**
  - `tests/integration/test_dashboard_forms_one_table.py` (new: G1);
  - `tests/e2e/test_distribution_editor_wire.py` (E5 extended to every editable type × component);
  - `review/briefing.yaml` (a conventions entry: the dashboard's limits, starting values and distribution types are rendered from `page_limits()`, `DISTRIBUTION_TYPES` and the fleet form tables; the integration module is its test).
- **Signal:** G1 passes in the per-task verify, and E5 passes in the lane's e2e job.
- **Consumer:** every later edit of the dashboard forms (verify); /review through the briefing.
- **Prereqs:** β, δ, ε, ζ, η.

**DAG.** α → β; γ → δ; β → δ; δ → {ε, ζ, η}; {β, δ, ε, ζ, η} → θ.

**Out-of-batch edges:**
- α → {956};
- β → {860, 774};
- γ → {947 (S5 γ), 921, 868};
- δ → {870, 937, 313, 394};
- ζ → {961};
- η → {786, 839, 841, 911};
- plus §6's: 676 → β (moved from 612); 844 → δ and 754 → δ (keyless or unruled twins, cancel recommended to the lead).

**Trigger-chain gate 772:** γ and δ (high) join it. Neither is an exception to priority = severity, since both carry fk-a6d9f3e5a7e2.

**G7** (advisory: this repo has no `docs/legibility/design-invariants.md`; walked against dark-factory's trigger shapes):

- **`one-fact-one-home`, `no-lockstep-duplication`:**
  - each limit, range, starting distribution, window default, distribution type and form choice has one home: `fleet_components`, `timebase`, `fleet_distribution` or `fleet_scenario`;
  - the pages and scripts render it, and α's, β's and δ's scans keep it so;
  - the vocabulary tables are built by iterating the server's own table, so they are not checked copies.
  - The UI titles are the only web-side text keyed by a grammar name: one dict per table, failing at import.
- **`no-silent-fail-soft`:** δ removes invented defaults (P4), ζ removes the builder's silent drops, ε removes a preview that hid Run's refusals, and β removes accepting out-of-range homes. The ε′ variant deletes rather than leaving a dead endpoint.
- **`guards-exercise-behaviour`:**
  - The page tests render the real pages and compare with the live values.
  - The reader tests post through the Flask client.
  - The e2e tests read the request the browser sends.
  - The text scans (dates, type tags) cover templates and scripts only where the per-task verify has no behaviour seam. Each has a behaviour twin in §5 (L1, E4, E5).
- **`exceptions-owned-or-ratified`:** none added. Decision 12's refusal of old saved presets is a named rule with its own test (B3).
- **`readers-prove-their-producer`:** the preview reads the generator Run uses, and P1 compares the two directly.

No waivers.

## 9. Out of scope

- Number pre-reads, `within` checks other than the component ranges, and the assistant's `n_homes` clamp (S4 η).
- The presence rule, `_HOME_CONFIG_DEFAULTS`, the refusal translator and location presets (S17).
- The home page's heat-pump block (S17 η).
- A location control on the fleet page (S6).
- `apply_fleet_overlay` and the fleet document's scenario-level blocks (S6).
- The sweep page's parameters, their ranges and the sweep value generator (S26).
- Heat-pump and EV fleet editors. No fleet page edits them today. When a page offers them, its option lists render from `HEAT_PUMP_TYPES` (911) and `CHARGER_TYPES` (919), and its spec types from `editor_types`. The home page's heat-pump type options are η's.
- Charts on the results pages (S21). The preview is a text summary, not a chart panel.
- Stored runs (S19). `config_presets` holds presets, not runs.
- Renaming `fleet_components.py` (the seam table names it).
- Offering `proportional_to` in the editor: a candidate follow-up, since `editor_types` would then need a source picker.

## 10. Open questions

**Tactical** (decided in the leaf):

1. β: `number_field`'s exact signature, and whether a page test asserts that every number input has a label.
2. β: the context processor's registration point, `create_app` or a blueprint's `app_context_processor`.
3. δ: the name of the shared helper both readers use to take the form's component blocks.
4. ε: the summary format and the Preview control's placement.
5. ζ: whether the builder's preset menu filter reuses `fleet_presets`' loader or `builtin_scenarios`'.

**For the lead** (S18's design holds whichever way each goes):

1. **The preview.** The default, ε, wires the endpoint into the fleet page as a preview of Run's homes. That gives the endpoint its first page consumer (G1), and it previews through the generator. The alternative, ε′, deletes the endpoint, the copy sampler and their tests. That is the smaller change: the endpoint has had no page caller since it landed. D18 names "preview", and the stream row keeps the endpoint, so the default follows them. Leo's call if the lead prefers.
2. **Builder presets saved before ζ.** The default refuses them by name: they hold the old flat form, which restores only a name today, and the reader of that form is gone after δ. The alternative is a one-shot conversion in ζ through a frozen copy of the flat-form reader. That keeps every saved row loadable, at the cost of carrying the deleted reader in a migration.
3. **The builder starts at the fleet page's distributions** (decision 9). One fact needs one starting type. The alternative keeps "the builder starts at Fixed Value" as a per-page flag beside the shared values.
4. **Bounding drawn values** (decision 2) widens fk-1df9dbc0d971 from fixed values to every home's value. A distribution whose tail crosses the range is refused for the seed that draws it. The alternative bounds fixed values only, which keeps today's builder behaviour on P15.

## 11. Decompose-time and lead actions

1. **Now, before the decompose:** hold tasks 612 and 298. 612 was re-planned on 2026-10-17 and is dispatchable. 298's branch is finished and its escalation closed, so it can re-dispatch. Both are superseded here (§6), and landing either first only adds work that β or ζ deletes.
2. At decompose: run contract §8 step 1 for every key. In particular:
   - fk-f8b7b3ab709d (376);
   - fk-9dd1d9389dd2 (697, done; expected closed, no leaf);
   - fk-3cd0d3f3b512 (753; the report's ticket resolved to this task).
3. Re-read each §6 target's status and claimant immediately before cancelling it, cancelling dependents first. An in-progress target (today 313) becomes a dependency edge, not a cancellation.
4. Re-measure fk-40dff1473b94 and fk-021a21b35427 at the decompose base (§2.6) and record the figures on ζ and δ.
5. File ε or ε′ per lead question 1, and ζ's decision-12 variant per lead question 2.
6. Add γ and δ (high) as dependencies of trigger-chain gate 772.
7. Move 676's dependency from 612 to β.

## Gate record

- **G1:**
  - `PageLimits` is consumed by the four pages, three scripts, the assistant schema and three readers.
  - The window constants are consumed by the CLI, the CLI's templates, `simulation_params`, `PageLimits` and S6.
  - `DISTRIBUTION_TYPES` is consumed by the parser, the editor, both readers and the import; ε uses it through `parse_fleet_form`.
  - `refuse_homes_outside_ranges` is consumed by the fleet and builder readers.
  - The preview is consumed by the fleet page (ε). Under ε′ nothing remains to consume.
  - `scenario_import.py` is consumed by both pages and by S6.
  - The vocabulary tables are consumed by the fleet page, the fleet import and, for the flat-rate start, all three forms.
  - `number_field` is consumed by β's, δ's and η's inputs.
  - No producer is orphaned.
- **G3:** verified at `ede1d99`:
  - the context processor API (Flask);
  - `tests/_html_page` helpers (`element_attributes`, `script_texts`) for page tests;
  - click parameter introspection through `typer.main.get_command`;
  - the preview endpoint's lack of callers (grep);
  - the js-yaml pin in `test_web_page_scripts.py`;
  - `_DISTRIBUTION_SPEC_TYPES` and `_BlockType` in config;
  - `ImportedFleetForm`, `_read_blocks`, `_not_loaded` and `_read_typed_block` in `fleet_scenario`;
  - `config_presets` reads and writes in `api.py`.

  Substrate from other streams is upstream in the DAG: `Interval` (860), the fleet grammar's construction reads (868), shape-only `_build_distribution_dict` (870), `fleet_distribution.py` (S5 γ), `FieldKind`/F2/F6/`draw` (921 and its chain), `STRATEGY_CONFIG_BY_TYPE` (786), optional `peak_hours` (839), `PRESET_RATES` (841), and `present_fields` and the translator (937, 935).
- **G4:**
  - S5 owns the module and S18 the table in it (D18).
  - S7 owns kinds and F2, and S18 reads them.
  - S4 owns numbers, and S18 deletes the shape translator after 870 (S4's own G4 note).
  - S17 owns the boundary, and δ follows 937.
  - S11, S2 and S21 are consumed as their PRDs' S18 rows state.
  - S6 and S26 are proposed cross-references (§7).
  - No reciprocal "the other owns it".
- **G5:** B + H. Blast radius: grammar, six web modules, four templates, three scripts, the CLI and `timebase`, with four upstream streams' seams. §4 is the contract, §5 the two-way sketch, and θ the integration gate.
- **G6:**
  - Every RED is probed (§2.7) or read from the code (§2.4, §2.5).
  - V2 is RED by construction: `_one_peak_window` refuses a missing window.
  - The end-to-end capabilities lie in each leaf's dependency set. ε's P1 needs δ's form and S7 γ's generator upstream; η's V2 needs 839.
  - Rejection mechanisms: β's range refusal is built in-leaf and observed by L2–L4. δ's E2 message is the grammar's existing "requires 'mean' and 'std'" (P6).
  - No numeric tolerance is asserted.
- **G7:** advisory, walked in §8.
- **META:** decomposing this without further oversight yields one limits value rendered everywhere, one range enforced on every home, one window default shared by CLI and web, one per-type table that the parser, editor, preview and import derive from, one import policy for both pages, and a fleet form whose choices come from the engine's tables. Each property has a test that exercises it. The four lead questions choose between complete alternatives; none leaves a design gap.
