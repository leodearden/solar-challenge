# PRD — Web request boundary: one refusal, one presence rule, one location grammar

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S17** (wave 2, size M, risk medium; upstream S1 and S4).
- **Binding rulings:** D2 (ConfigurationError subclasses ValueError; the web translator logs a non-domain ValueError separately so a bug is not silently a 400), D17 (an unknown location is refused with a 400 naming the value; location.py owns the presets and one strict 'preset or lat,lon[,alt]' grammar shared by the CLI and the web; the silent Bristol fallback goes), D29 (additive frozen-table edits land in-leaf; only renames and retirements wait for S29), L1 (S4 converts every input-type refusal to ConfigurationError, so the translator sees one domain type; the web rewraps and `FLEET_FORM_REFUSALS` are S17's).
- **Finding keys:** fk-6c98ee030531, fk-1d143fefefed, fk-29af8a4fe018, fk-66f886576b3f, fk-bd7f2abebeba, fk-0593b530a371, fk-acdc650baeb8, fk-da0e3a4df6e7, fk-a0866b1bd680, fk-ba29e186122f, fk-70edc755ede4 (statement, measurements and skeptic notes in `plans/review-all-solar_challenge-20261013.json`).
- **Approach:** B + H. The seam is read by the CLI, every web reader, three templates and the assistant, and six other streams edit the same files, so it gets a contract (§5) and two-way boundary tests (§6).
- **Status:** authored 2026-10-17; committed by the lead in `672ba0c`; decomposed 2026-10-17 under lead ruling L34 (α 931, β 932, γ 933, δ 935, ε 937, ζ 938, η 940, θ 942, κ 943).
- **Code anchors** verified against main `2ff5673` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time. Every web file named below has moved since the review's pin `7dfea36e`; each finding was re-measured at `2ff5673` (§2.2).

## 1. Goal

What a user sees when this lands:

1. **One location grammar at both front ends.** `solar-challenge home run --location london` runs at London (today refused). `POST /api/simulate/home` with `location: "51.5,-0.1,11"` runs at those coordinates with altitude 11 m (today 400). `solar-challenge config locations` lists the four presets. Both boundaries refuse anything else, such as `'londn'`, `'51.5;-0.1'` or `'95,0'`, naming the value and the accepted forms.
2. **Custom coordinates travel as a mapping.** The home page posts `location: {latitude, longitude}` instead of joining `custom_lat + ',' + custom_lon`. A mapping that leaves out a coordinate is refused naming it; today a partial `location:` block silently takes Bristol's other coordinate. The home, builder and sweep pages render their preset options from the one table.
3. **One refusal at the web boundary.** Every refusal a web reader or an input type raises is a `ConfigurationError`. The `/api` blueprint answers it through one handler with HTTP 400 `{"error"}`. Any other `ValueError` gets the same answer, but is logged at ERROR with its traceback as a probable defect (D2). Anything else answers 500 with a JSON body; today it answers with the HTML error page. The fleet page's default 100-value PV pool posted with 200 homes answers 400 naming the pool on simulate, export and import; today it answers 500 HTML. `FLEET_FORM_REFUSALS`, the three rewraps, `NotAJsonObject` and the per-route except-tuples are gone.
4. **One presence rule.** In the home, fleet and builder form bodies, `null` and `""` both mean "not sent". A field not sent takes the engine's default (`PVConfig`, `LoadConfig`, `BatteryConfig`, `HomeConfig`) or one of two named web defaults (Bristol, the deterministic load profile). `pv_kw: null` runs a 4 kW array, as an omitted pv capacity does in a scenario file; today it is refused. An absent `azimuth` takes `PVConfig`'s default, not a web copy of it.
5. **Strings and booleans are read, not coerced.** Each of these answers 400 naming the field:
   - `POST /api/simulate/fleet` with `name: {"x": 1}` (today 201, then a failed job);
   - `POST /api/presets` with `name: 5` (today 500 HTML);
   - `PATCH /api/history/runs/<id>` with `name: {"a": 1}` (today 500);
   - `POST /api/simulate/home` with `stochastic: "false"` (today it runs the stochastic model).
6. **The heat-pump block is config's `heat_pump:` block.** The home page posts `heat_pump_type`. An unrecognised key is refused naming it. `{heat_pump_type: GSHP, thermal_capacity_kw: 12}` runs a 12 kW GSHP; today it runs an 8 kW ASHP with no error.
7. **The request readers sit below the Flask services.** The readers' import closure holds no `web.jobs`, `web.storage` or `web.database`. The service accessors live beside S16's dashboard holder, and `web/shared.py` is gone.

## 2. Background (measured at `2ff5673`)

### 2.1 What moved since the pin

- **Task 698 (done, `fec22d8`)** made `shared.resolve_location` refuse a location it cannot resolve instead of returning Bristol. That closes fk-acdc650baeb8 and the silent half of fk-0593b530a371. A non-string location on the fleet routes now answers 400, so fk-6c98ee030531's measured `AttributeError` escape no longer reproduces for `location`; the `IndexError` and `TypeError` escapes do.
- **Task 773 (done)** created `solar_challenge/errors.py`. **Task 774 (in progress)** makes `ConfigurationError` subclass `ValueError`. At `2ff5673` its MRO is still `ConfigurationError, Exception`.
- **Task 394 (pending; resumed by esc-394-3 on 2026-10-17)** adds `shared.refuse_unrecognised_keys` and refuses unrecognised fleet-form keys. Its branch conflicts with main in `builder_form`, `fleet_scenario`, `simulation_params` and `test_web_shared`.
- **Task 297 (pending, plan written)** refuses a shuffled pool whose counts do not total `n_homes`, with `ConfigurationError` from `FleetDistributionConfig.__post_init__` and `generate_homes_from_distribution`. It drops `builder_form`'s `IndexError` arm and folds in task 723.

### 2.2 Probes (Flask test client, `TESTING` and `PROPAGATE_EXCEPTIONS` off, mock job manager)

| Probe | Today |
|---|---|
| `resolve_location` / `cli.utils.parse_location` on `'london'` | web London; CLI `ValueError` |
| … on `'51.5,-0.1,11'` | web 400 "must be 'lat,lon' coordinates or one of …"; CLI (51.5, −0.1, 11 m) |
| … on `'51.5,-0.1'` | both (51.5, −0.1); web names it `''`, CLI `'Custom (51.50, -0.10)'` |
| … on `None`, `51`, `{"latitude": 50}` | web `ValueError` naming the value; CLI `AttributeError` |
| `config.parse_location_block({"latitude": 50})` | `Location(50, −2.58)`: Bristol's longitude, silently |
| `POST /api/simulate/home` `location: {"latitude": 51.5, "longitude": -0.1}` | 400: a mapping is not a location string |
| fleet form, PV `shuffled_pool` entries 20+40+30+10, `n_homes` 200, on `fleet-from-distribution` and `export-yaml` | 500 `text/html` (`IndexError`) |
| home `heat_pump: {heat_pump_type: GSHP, thermal_capacity: 12}` | 201; queued `HeatPumpConfig('ASHP', 8.0, 8000.0)` |
| `POST /api/simulate/fleet` `name: {"x": 1}` / home `name: ["a"]` | 201 / 201 |
| `POST /api/presets` `name: 5` | 500 `text/html` (`AttributeError` at `.strip()`) |
| home `stochastic: "false"` | 201; queued `use_stochastic=True` |
| home `pv_kw: null`, `azimuth: null`, `occupants: null`, `pv_kw: ""`, `days: ""` | each 400 "… must be a finite number, got None/''" |
| fleet `seed: null` / `n_homes: null` | 400 / 400; an absent seed runs 42 |

### 2.3 The census the deletions are measured against

- **Refusal catches in `web/*.py`:**
  - `api.py`: `(ValueError, TypeError)` ×5; `FLEET_FORM_REFUSALS` ×4; `ValueError` ×2 (builder preview, history YAML 422); and the stored-run five-type tuple in `history_export_yaml` ×1, which is S19's.
  - `fleet_presets._yaml_loads`: `FLEET_FORM_REFUSALS` ×1.
  - `assistant.py`: `(ValueError, TypeError)` ×5 (two trigger-tool parses, the `n_homes` clamp, `suggest_config`, `list_recent_runs`); `NotAJsonObject` ×1 (chat body).
  - `builder_form`: `(ConfigurationError, ValueError, IndexError)` ×1, `ConfigurationError` ×1, `ValueError` ×3, `NotAJsonObject` ×1.
  - `simulation_params`: `raise ValueError(str(exc)) from exc` ×3.
- **`raise ValueError` in the readers:** `simulation_params` 11, `fleet_scenario` 10, `fleet_config` 14, `builder_form` 5, `shared` 1.
- **Location presets spelled:** `web/shared.LOCATION_PRESETS`, plus the option lists in `simulate/home.html`, `scenarios/builder.html` and `scenarios/sweep.html`. The CLI knows only `bristol`.
- **`web/shared.py` importers:** `builder_form`, `fleet_scenario` and `simulation_params` import only the request readers. `history` and `routes` import only `get_storage`. `api` and `assistant` import both.

## 3. How this PRD reads the rulings

1. **D2, read as written.** A web boundary catches `ValueError`. A `ConfigurationError` is a refusal and is answered 400. Any other `ValueError` is also answered 400, but first it is logged at ERROR with its traceback as "not a ConfigurationError: probable defect". A bug is then never *silently* a 400. Everything else, `TypeError`, `AttributeError`, `KeyError` and `IndexError` included, is not a refusal; the `/api` blueprint answers it 500 with a JSON body. The consequence is §4 decision 10: every refusal a web reader raises itself must be a `ConfigurationError`, or it would be logged as a defect.
2. **L1.** S4 β, γ and δ convert the input types' refusals, numeric and not, so `Location`'s, `PVConfig`'s and the tariff's refusals reach the translator as `ConfigurationError`. S4 α moves `number_fields` to the package leaf, raising `ConfigurationError`. S4 η stops the web pre-reading numbers. S17's translator leaf depends on all of them. S1's §12 Q1 names the cost of not waiting: log noise for legitimate refusals.
3. **D17.** `location.py` owns the presets and the string grammar. Task 698 already deleted the fallback. S17 deletes `resolve_location` and the web's preset table, and makes the CLI and web read a location string with the one parser.
4. **D29.** S17 renames or retires no frozen-surface name. `Location`'s form is unchanged. The new names (`location.LOCATION_PRESETS`, `location.parse_location`, `config.parse_heat_pump_block`, `config.PV_CAPACITY_KW_WHEN_OMITTED`) are not exported from `solar_challenge`. Nothing is held for S29.

## 4. Resolved design decisions

1. **`location.py` owns the named presets and the strict string grammar.** It holds `LOCATION_PRESETS`, a read-only mapping of `bristol`, `london`, `edinburgh` and `manchester` whose `bristol` entry is `Location.bristol()`, and `parse_location(text)`. The web's table and its re-spelling of Bristol's constants go (heuristic 11).
2. **The grammar.**
   - A preset name, in any case and with surrounding whitespace.
   - Otherwise two or three comma-separated numbers: latitude, longitude and an optional altitude in metres.
   - Each number is read by `number_fields.as_finite_float` (S4 α), naming `latitude`, `longitude` or `altitude`. `Location` then applies its own range rules (S4 β).
   - Anything else is a `ConfigurationError` naming `location`, the text and the accepted forms.
   - `parse_location` holds no `float()` and no `try`: the reader and `Location` refuse by name (heuristic 10).
3. **The CLI is a thin caller.**
   - `cli.utils.parse_location` is deleted. `load_config_with_overrides` calls `location.parse_location`; S6 later moves that override code into the home command.
   - `--location`'s help and `config locations` render from `LOCATION_PRESETS`.
   - A refused `--location` now prints `Configuration error:`; today it prints `Invalid value:`. The test pinning `handle_errors`' clause order (task 774's C1) moves to another plain-`ValueError` input.
4. **The request-reading module is `web/request_boundary.py`.**
   - Its purpose: how the web reads a request body, and how it answers what it refuses.
   - It imports flask, `errors`, `location`, `number_fields` and `config.parse_location_block`, and no web service. The readers' closure therefore loses `web.jobs`, `web.storage` and `web.database` (fk-bd7f2abebeba's measured property).
   - Moved into it from `shared.py`: `require_json_object`, `request_json_object`, and `refuse_unrecognised_keys`, which task 394 adds there.
   - New in it: the presence rule, the string and boolean readers, the location reader and the translator.
5. **A location value has three forms.**
   - A string is read by `location.parse_location`.
   - A mapping is read by `config.parse_location_block`: the scenario grammar's `location:` block is the one mapping reader for files and requests, as fk-1d143fefefed proposes.
   - Any other JSON value is refused, naming `location` and its JSON type.
   - Not sent means Bristol, a web default (decision 14).
6. **A `location:` block names a point or nothing.** A non-empty block must set both `latitude` and `longitude`; otherwise `parse_location_block` refuses it, naming the missing one. An absent or empty block stays Bristol (the scenario default). All 12 `scenarios/*.yaml` with a `location:` block set both (scanned). This applies D17's "bad coordinates are refused" to the mapping, so the web's new mapping form cannot reintroduce the silent Bristol fill-in that the string form just lost.
7. **The pages read the table.**
   - The home, builder and sweep routes pass `LOCATION_PRESETS`, and each template renders its preset options from it.
   - `home.html` posts a custom location as `{latitude, longitude}`; the comma join goes.
   - The builder keeps its flat `latitude`/`longitude`/`altitude` fields for `custom`, written as the document's `location:` block. With decision 6, a custom location missing a coordinate is now reported by `/api/scenarios/validate` instead of loading as Bristol's. Its preset arm reads `LOCATION_PRESETS`.
   - The assistant's trigger-tool `location` description names the presets from the table and the coordinate form (the location half of task 770).
8. **One translator, registered once.**
   - `api_bp` registers `request_boundary.answer_refusal` for `ValueError` and `request_boundary.answer_server_error` for 500. Routes hold no refusal except-clauses.
   - A route that adds context, such as the sweep's `Invalid config for {parameter}={value}:`, catches `ConfigurationError` and re-raises it with the prefix.
   - Flask resolves a blueprint handler by the exception's MRO and consults blueprint 500 handlers for unhandled exceptions (probed on Flask 3.1.3, §Gate record G3).
9. **Every other boundary site applies the same rule through `refusal_text`.** These sites answer without HTTP 400:
   - the assistant's two trigger tools (an `{"error"}` dict) and its chat body (an SSE error frame);
   - `builder_form_errors` (the validate list);
   - `fleet_presets._yaml_loads` (a preset the menu does not offer).
   Each catches `ValueError` and calls `request_boundary.refusal_text`, which logs a non-domain `ValueError` exactly as the HTTP handler does. One function decides what a refusal is (heuristic 11).
10. **Every refusal a web reader raises is a `ConfigurationError`.**
    - This covers `simulation_params`, `fleet_scenario`, `fleet_config`, `builder_form` and `request_boundary`.
    - `NotAJsonObject` is deleted: `require_json_object` raises `ConfigurationError`, and nothing dispatches on the subclass except to answer 400 or short-circuit.
    - `errors.ConfigurationError`'s docstring names the web readers among its raisers and states the boundary rule. S17 owns the "Refusal type" seam at the web.
11. **`TypeError` is not a refusal.** It leaves every catch. A reader whose refusal relied on a caught `TypeError` gets an explicit refusal; δ audits every web test that expects 400 to confirm that.
12. **The stored-run decode keeps its own handling.** `history_export_yaml`'s five-type tuple decodes a stored run, not a request. It stays until S19 κ's `StoredRunUnreadable`.
13. **The presence rule** (fk-29af8a4fe018).
    - `request_boundary.present_fields(body)` drops each top-level field whose value is `None` or `""`.
    - `parse_home_config`, `parse_fleet_form` and the builder apply it after the body-object check and the unrecognised-key check, so an unrecognised key is refused even when null. The builder's private copy is deleted.
    - It applies at the top level only: a nested block's contents follow that block's grammar (config's).
    - `PATCH /api/history/runs/<id>` is an update, not a form body; there `""` can clear notes. It is outside the rule and keeps S19 ζ's null-or-blank-name refusal.
14. **Defaults separated from nullability** (fk-ba29e186122f).
    - Each form reader declares its recognised keys and, separately, its web defaults.
    - The home reader has two web defaults: `location` → `Location.bristol()`, and `stochastic` → `False`. The reason for the second, written beside it: a web run is repeatable by default. The dashboard takes no load seed and compares stored runs, so a body that does not ask for the stochastic model gets the deterministic profile; `LoadConfig`'s `True` is the library's default.
    - An engine field not sent is not passed, so its dataclass default applies.
    - `pv_kw` not sent is config's omitted-capacity constant, made public as `config.PV_CAPACITY_KW_WHEN_OMITTED`.
    - `battery_kwh` not sent is no battery; `consumption_kwh` not sent is the TDCV estimate.
    - `_HOME_CONFIG_DEFAULTS` is deleted.
15. **Strings and booleans are read** (fk-da0e3a4df6e7, task 517's fk-5827f41eb082).
    - `read_string(value, field)` refuses a non-string, as `{field} must be a JSON string, got {type}`. `read_boolean(value, field)` refuses anything but `true` or `false`.
    - The readers apply to `parse_home_config`'s `name` and `stochastic` and `parse_fleet_form`'s `name`; `ParsedFleetForm.name` is typed.
    - They also apply to the `/api` endpoints' names, labels and types: `simulate/fleet`, `presets`, `scenarios/save` (whose `config` also goes through `require_json_object`) and the history PATCH labels (string, or null where S19 allows it).
    - The chat body's `message` and `run_id` are read the same way.
    - The sweep's `parameter` and `mode` are S26's.
16. **One heat-pump grammar** (fk-70edc755ede4). The home body's `heat_pump` block is config's `heat_pump:` block. `home.html` posts `heat_pump_type`. `simulation_params` reads the block with config's reader, made public as `config.parse_heat_pump_block`. Unrecognised keys are refused naming them, `thermal_capacity_kw` is required, and the defaults live in one place. `_parse_heat_pump_block`, its `type` key and its 8.0 and 8000.0 defaults go.
17. **The service accessors live beside the holder that owns the services.** `get_storage`, `get_job_manager`, S19's `get_database` and S20's policy accessor all read S16's `dashboard_of(current_app)`. They move into `web/dashboard.py`, and `shared.py` is deleted. That leaf depends on S16 δ (task 889; L34).

## 5. Contract

### 5.1 `solar_challenge.location` (α)

```python
# imports: dataclasses, types, typing; solar_challenge.errors; solar_challenge.number_fields (S4 α)
LOCATION_PRESETS: Mapping[str, Location]   # MappingProxyType; keys bristol, london, edinburgh, manchester;
                                           # LOCATION_PRESETS["bristol"] == Location.bristol()

def parse_location(text: str) -> Location:
    """The Location *text* names: a LOCATION_PRESETS name in any case and with surrounding whitespace,
    or 'lat,lon' / 'lat,lon,alt' decimal degrees and metres.

    Raises:
        ConfigurationError: for any other text, naming location, the text and the accepted forms;
            from number_fields, for a coordinate that is not a finite number, naming it;
            from Location, for coordinates outside its range.
    """
```

| # | Invariant | Enforced by |
|---|---|---|
| L1 | One preset table; the CLI, the web readers, the builder, three templates and the assistant's tool description read it | α, γ; grep checks (manifest) |
| L2 | One string grammar; `cli.utils.parse_location` and `shared.resolve_location` do not exist | α, γ |
| L3 | A refused string is a `ConfigurationError` naming `location` and the text at both boundaries, with the same message | κ (row L5) |
| L4 | A `location:` block sets both coordinates or neither | γ, in `config.parse_location_block` |

### 5.2 `solar_challenge.web.request_boundary` (β, γ, δ, ε, ζ)

```python
# imports flask, solar_challenge.{errors, location, number_fields}, solar_challenge.config.parse_location_block;
# imports no solar_challenge.web module
def require_json_object(value: object, what: str) -> dict[str, Any]          # β moves it; δ: ConfigurationError
def request_json_object() -> dict[str, Any]                                   # β moves it
def refuse_unrecognised_keys(body, recognised, what) -> None                  # β moves it (task 394)
def read_location(value: object) -> Location                                  # γ: str | Mapping | refused
def refusal_text(refusal: ValueError) -> str                                  # δ: logs a non-domain ValueError
def answer_refusal(refusal: ValueError) -> tuple[Response, int]               # δ: 400 {"error": refusal_text(...)}
def answer_server_error(error: InternalServerError) -> tuple[Response, int]   # δ: 500 {"error": "Internal server error"}
def present_fields(body: Mapping[str, Any]) -> dict[str, Any]                 # ε: drops None and ""
def read_string(value: object, field: str) -> str                             # ζ
def read_boolean(value: object, field: str) -> bool                           # ζ
```

| # | Invariant | Enforced by |
|---|---|---|
| R1 | A web reader's refusal is a `ConfigurationError`; no reader module holds `raise ValueError` | δ; grep check |
| R2 | `/api` answers a `ValueError` 400 `{"error"}` through `answer_refusal` alone; no route catches `(ValueError, TypeError)` or a refusal tuple | δ; grep checks; row R1–R4 |
| R3 | A `ValueError` that is not a `ConfigurationError` produces exactly one ERROR log record naming its type before the 400 | δ (row R2) |
| R4 | An unhandled exception in an `/api` view answers 500 `application/json` | δ (row R3) |
| R5 | The assistant tools, the chat body, the builder's validate list and the fleet preset menu judge a refusal with `refusal_text` | δ |
| P1 | In the home, fleet and builder form bodies, a field sent as `null` or `""` reads exactly as one not sent | ε (rows P1–P3) |
| P2 | A form reader passes an engine field only when it is sent; its two web defaults are named and commented | ε |
| S1 | A name, label or boolean field of the wrong JSON type is refused naming the field before any job or database write | ζ |
| G1 | `simulation_params`, `fleet_scenario`, `builder_form` and `request_boundary` import, transitively, no `web.jobs`, `web.storage` or `web.database` | β (row G1) |

### 5.3 config (γ, ε, η)

- `parse_location_block(data, *, block_path="location")`: a non-empty block without `latitude` or without `longitude` raises `ConfigurationError` naming `<block_path>.latitude` or `<block_path>.longitude`. The unrecognised-key check stays first.
- `PV_CAPACITY_KW_WHEN_OMITTED`: the public name of `_PV_CAPACITY_KW_WHEN_OMITTED`, read by `_parse_pv_config` and the home reader.
- `parse_heat_pump_block(data, *, block_path="heat_pump")`: the public name of `_parse_heat_pump_config`, behaviour unchanged.
- S5's partition moves all three into `scenario_blocks.py` with the other readers. Each leaf imports from wherever the reader lives at its base.

## 6. Boundary-test sketch

| # | Faces | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| L1 | CLI | a preset the CLI did not know | — | `home run --location london`, with the weather cache seeded only for `LOCATION_PRESETS["london"]`, exits 0; any other location misses the cache and the offline guard fails the test | α |
| L2 | CLI | refused strings | — | `home run --location londn`, `'51.5;-0.1'` and `'95,0'` each exit 1 with `Configuration error:` naming the value (or `latitude` for `'95,0'`); no simulation starts | α |
| L3 | CLI | the listing | — | `config locations` prints one row per `LOCATION_PRESETS` key, with that preset's coordinates | α |
| L4 | web | the CLI's coordinate form | γ | `POST /api/simulate/home` with `location: "51.5,-0.1,11"` → 201; the queued home's location is `parse_location("51.5,-0.1,11")` (altitude 11) | γ |
| L5 | both | same answer at both boundaries | α, γ | for `'londn'`, `'51.5;-0.1'`, `'51.5,-0.1,x'` and `'95,0'`: the CLI's error text after `Configuration error: ` equals the web's 400 `error` | κ |
| L6 | web | the mapping form | γ | `location: {"latitude": 51.5, "longitude": -0.1}` → 201 at those coordinates; `{"latitude": 50}` → 400 naming `location.longitude`; `5` → 400 naming `location` and `int`; `null` → Bristol | γ (`null` from ε) |
| L7 | library | partial location block | γ | `load_fleet_config` on a document whose `location:` sets only `latitude` raises `ConfigurationError` naming `location.longitude`; every `scenarios/*.yaml` still loads | γ |
| L8 | web | pages render the table | γ | `GET /simulate/home`, `/scenarios/builder` and `/scenarios/sweep` render one `<option>` per `LOCATION_PRESETS` key; the home page script posts a custom location as a mapping (e2e custom-location path) | γ |
| R1 | web | a domain refusal | δ | a body refused with `ConfigurationError` → 400 `{"error"}`, no ERROR record | δ |
| R2 | web | a non-domain ValueError | δ | a reader monkeypatched to raise `ValueError("probe")` → 400 `{"error": "probe"}` and exactly one ERROR record naming `ValueError` | δ |
| R3 | web | a defect | δ | a reader monkeypatched to raise `TypeError` → 500 `application/json` `{"error": "Internal server error"}` (was HTML) | δ |
| R4 | web | short shuffled pool | 297 | the fleet page's default PV pool (100 values) with `n_homes` 200 → 400 naming the pool and 200 on `fleet-from-distribution`, `export-yaml` and `import-yaml`; such a file in the scenarios directory is not offered by `fleet_preset_names` | δ |
| R5 | assistant | trigger tool refusal | δ | `run_home_simulation({"pv_kw": 4, "location": "cardiff"})` → `{"error": "Invalid simulation parameters: …cardiff…"}`, nothing submitted | δ |
| P1 | web | null and "" read as absent (home) | ε | for each recognised home field F, the body `{pv_kw: 4, days: 1}` plus `F: null`, and plus `F: ""`, queues the same home, window and name as the body without F, and answers 201 | ε |
| P2 | web | engine defaults reach web runs | ε | `{"days": 1}` queues a `PVConfig` whose azimuth, tilt, system age and degradation rate equal `PVConfig`'s field defaults, and a `LoadConfig` whose occupants equal `LoadConfig`'s; `pv_kw` equals `config.PV_CAPACITY_KW_WHEN_OMITTED` | ε |
| P3 | web | null and "" read as absent (fleet) | ε | `seed: null`, `seed: ""` and an absent seed run the same fleet; likewise `n_homes` | ε |
| S1 | web | wrongly typed strings and booleans | ζ | `simulate/fleet` `name: {"x": 1}`, `presets` `name: 5`, PATCH `name: {"a": 1}`, home `name: ["a"]`, `scenarios/save` `name: 5` and `config: [1, 2]`, and home `stochastic: "false"` → each 400 naming the field; no job is submitted and no row is written | ζ |
| H1 | web | one heat-pump grammar | η | home `heat_pump: {heat_pump_type: GSHP, thermal_capacity: 12}` → 400 naming `thermal_capacity`; `{type: GSHP, …}` → 400 naming `type`; `{heat_pump_type: GSHP, thermal_capacity_kw: 12}` → 201 with a 12 kW GSHP | η |
| G1 | guard | readers below the services | β | in a fresh `-I` interpreter, importing `simulation_params`, `fleet_scenario`, `builder_form` and `request_boundary` leaves `web.jobs`, `web.storage` and `web.database` out of `sys.modules` | β |
| G2 | guard | one module of accessors | θ | `solar_challenge.web.shared` does not exist; `api`, `assistant`, `history` and `routes` read the accessors from `web.dashboard` | θ |

## 7. Existing tasks this PRD meets

Run contract §8 step 1 before filing. A superseded task is cancelled with `metadata.x_superseded_by` naming the leaf. Re-check each target's status at decompose: a target that has gone in progress or into the merge queue since authoring becomes a dependency edge of its superseding leaf, not a cancel.

| Task | Status | Disposition |
|---|---|---|
| 698 | done | Closes fk-acdc650baeb8: at `2ff5673`, `resolve_location('londn')` raises. γ deletes the function. No new task carries the key |
| 774 | in progress | Upstream of δ (ConfigurationError ⊂ ValueError). α moves its C1 location pin |
| 394 | pending (resumed) | Upstream of β, which moves its `refuse_unrecognised_keys` into `request_boundary` |
| 297 | pending | Upstream of δ: the config half of fk-a0866b1bd680. **Proposed:** stamp the key on 297 and raise it to high (§11 Q2) |
| 723 | pending | Folded into 297 by 297's plan |
| 245 | pending | **Superseded** by η (fk-70edc755ede4). Its seg half is already done by `config.parse_seg_rate` (245's own note) |
| 755 | pending | **Superseded** by ε (fk-ba29e186122f) |
| 770 | pending | Stays. Re-point its dependency from 755 to ε. γ writes the location description, so 770 keeps only the occupants prose |
| 331 | pending | **Superseded** by ζ: preset name, PATCH labels and fleet location types. The location half was done by 698 |
| 517 | pending (dep 331) | **Superseded** by ζ (name, stochastic, `ParsedFleetForm.name`) and γ (location). Its over-long fleet preset name item no longer reproduces: `fleet_preset_form` looks the name up in `builtin_scenario_files()`'s dict, so no path is built from it (probed: names of 255 and 300 characters answer 404 JSON). Carries fk-5827f41eb082, which moves to ζ (§11 Q1) |
| 560 | pending (dep 331) | **Superseded** by ζ: `scenarios/save` name and config |
| 424 | pending | Narrowed. η deletes the `simulation_params` heat-pump copy of "must be a mapping"; `fleet_config._require_dict` stays with 424 (S18's file) |
| 509 | pending | Stays. Its premise ("a web refusal must stay a ValueError") is void after δ. The one unrecognised-key rule lands where S5 puts `_refuse_unrecognised_keys`, and `request_boundary.refuse_unrecognised_keys` calls it |
| 751 | pending (S22) | Stays. Its per-tool input readers raise `ConfigurationError` and answer through `refusal_text` |
| 612, 664 | pending | Untouched (the PV bound and its context name) |

## 8. Cross-PRD relationship

| Other PRD / stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 errors leaf (773, 774, 775) | consumes | `ConfigurationError(ValueError)`; S17 edits its docstring for the web (decision 10) | S1 type, S17 web rule | δ depends on 774; α moves 774's C1 location pin |
| S4 finite quantities (`docs/prds/finite-quantities.md`) | consumes | `number_fields` at the package leaf (α); input types raise `ConfigurationError` (β, γ, δ); the web stops pre-reading numbers (η) | S4 | **declared:** S17 α on S4 β; S17 δ on S4 β, γ, δ and η. S17 η deletes the `heat_pump.<key>` pre-reads that S4 η keeps |
| S5 scenario grammar | file overlap, moves | `parse_location_block` (strict, γ), `parse_heat_pump_block` (η) and `PV_CAPACITY_KW_WHEN_OMITTED` (ε) move to `scenario_blocks.py`; 509's one key rule | S5 moves; S17 defines | order-agnostic: whichever lands second repoints the imports |
| S6 fleet-document overlays | consumes | `parse_location_block`'s strict block; `home run --location` through `location.parse_location` | S17 grammar; S6 moves the override code | cross-reference |
| S16 fleet execution policy | produces for S17 θ | `web/dashboard.py`'s `Dashboard` and `dashboard_of` (S16 δ) | S16 holder; S17 accessor location | θ depends on S16 δ (task 889; L34), not held |
| S18 dashboard limits | file overlap | `fleet_config`'s refusals become `ConfigurationError` (δ); option lists render from `LOCATION_PRESETS` (γ) | — | S18's new refusals raise `ConfigurationError` |
| S19 run store | file overlap | ζ (817) owns default run names and the PATCH null/blank-name refusal; κ owns `history_export_yaml`'s stored-run tuple; `get_database` moves with θ | S19 | order-agnostic textual overlap |
| S20 job events | file overlap | the policy accessor moves with θ; the chat body's error frame uses `refusal_text` | S20 frames | note |
| S22 assistant (751, 770) | consumes | `refusal_text`; `LOCATION_PRESETS` for the tool description | S17 | note |
| S26 sweep knob registry | none | the sweep's `parameter` and `mode` reads stay S26's | S26 | note |
| S11, S21 | file overlap | `simulate/home.html` (tariff defaults, S11 γ) | — | note |
| S29 | none | no frozen-surface rename or retirement | — | — |

## 9. Decomposition plan

Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all` and file-level `metadata.files`. Priority is the highest severity among its keys. A leaf that edits a template or a script runs the e2e tests that touch it (`tests/e2e/test_home_form_interactions.py`, `test_enable_switches.py`, `test_scenario_builder.py`, `test_parameter_sweep.py`). It rebuilds `static/dist/style.css` only if a class string changes.

**α — location.py owns the presets and one strict string grammar; the CLI reads it** (leaf; priority medium)
- **Keys:** fk-66f886576b3f, fk-0593b530a371.
- **Work:**
  - §5.1.
  - Delete `cli.utils.parse_location`; `load_config_with_overrides` calls `location.parse_location`.
  - `--location`'s help and `config locations` render from `LOCATION_PRESETS`.
  - Move task 774's C1 location pin to `Configuration error:` and keep a clause-order pin on another plain-`ValueError` input.
  - Coordinate locations are named per §11 Q-T1.
- **Files:** `src/solar_challenge/location.py`, `src/solar_challenge/cli/utils.py`, `src/solar_challenge/cli/home.py`, `src/solar_challenge/cli/config.py`; `tests/unit/test_location.py`, `tests/unit/test_cli.py`.
- **Signal:** rows L1–L3.
- **Prereqs:** S4 β (`Location` raises `ConfigurationError`; same file).

**β — The request readers move below the Flask services** (intermediate; unlocks γ, δ, θ; priority low)
- **Keys:** fk-bd7f2abebeba.
- **Work:**
  - Create `web/request_boundary.py` with `require_json_object`, `request_json_object` and `refuse_unrecognised_keys`, moved from `shared.py`.
  - Repoint the seven importers.
  - `shared.py` keeps only the service accessors.
- **Files:** `src/solar_challenge/web/{request_boundary,shared,simulation_params,fleet_scenario,builder_form,api,assistant}.py`; `tests/unit/test_web_shared.py` → `tests/unit/test_web_request_boundary.py`.
- **Signal:** row G1. Unlocks γ (the location reader's home), δ and θ.
- **Prereqs:** 394.

**γ — The web reads a location with the one grammar** (leaf; priority medium)
- **Keys:** fk-1d143fefefed, fk-0593b530a371.
- **Work:**
  - `request_boundary.read_location` (decision 5); `parse_location_block` requires both coordinates (decision 6).
  - `parse_home_config` and `parse_fleet_form` read `location` with it.
  - Delete `resolve_location`, `_lat_lon` and `LOCATION_PRESETS` from `shared.py`; the builder reads the table.
  - Templates and routes (decision 7); `home.html` posts a mapping.
  - Derive the assistant's location description from the table.
- **Files:** `src/solar_challenge/web/{request_boundary,shared,simulation_params,fleet_scenario,builder_form,assistant,routes,scenarios}.py`, `src/solar_challenge/config.py`, `src/solar_challenge/web/templates/simulate/home.html`, `templates/scenarios/builder.html`, `templates/scenarios/sweep.html`; `tests/unit/test_web_simulation_params.py`, `tests/unit/test_web_fleet_scenario.py`, `tests/unit/web_api/`, `tests/unit/config/test_unrecognised_keys.py` (or the location-block tests), `tests/unit/web_assistant/test_tool_handlers.py`, `tests/e2e/test_home_form_interactions.py`.
- **Signal:** rows L4, L6, L7 and L8.
- **Prereqs:** α, β.

**δ — One refusal type and one translator at the web boundary** (leaf; priority high)
- **Keys:** fk-6c98ee030531, fk-a0866b1bd680, fk-da0e3a4df6e7.
- **Work:**
  - Decisions 8–12.
  - Delete `FLEET_FORM_REFUSALS`, the three rewraps, `NotAJsonObject` and every route's refusal except-clause.
  - Every reader's `raise ValueError` becomes `ConfigurationError`.
  - Register `answer_refusal` and `answer_server_error` on `api_bp`.
  - The assistant's trigger tools and chat body, `builder_form_errors`, `_scenario_reader_errors` (its `IndexError` arm goes if 297 left it) and `fleet_presets._yaml_loads` use `refusal_text`.
  - `ConfigurationError`'s docstring (decision 10).
  - Audit every 400 test with `TypeError` dropped.
  - Re-measure §2.3 and record it on the task.
- **Files:** `src/solar_challenge/errors.py`, `src/solar_challenge/web/{request_boundary,api,assistant,simulation_params,fleet_scenario,fleet_config,builder_form,fleet_presets}.py`; `tests/unit/web_api/`, `tests/unit/test_web_*.py`, `tests/unit/web_assistant/`.
- **Signal:** rows R1–R5.
- **Prereqs:** γ, 774, 297, S4 β, S4 γ, S4 δ, S4 η.
- **Trigger chain:** add as a dependency of gate 772 (high).

**ε — One presence rule; defaults separated from nullability** (leaf; priority medium)
- **Keys:** fk-29af8a4fe018, fk-ba29e186122f.
- **Work:**
  - Decisions 13 and 14: `present_fields`, the recognised-key sets, the web-defaults tables, `config.PV_CAPACITY_KW_WHEN_OMITTED`.
  - `parse_date_range`'s `_window_sent` reads the present fields.
  - Delete `_HOME_CONFIG_DEFAULTS` and the builder's `_present_fields`.
  - Update `docs/web-ui-design.md` where it states a web default.
- **Files:** `src/solar_challenge/web/{request_boundary,simulation_params,fleet_scenario,fleet_config,builder_form}.py`, `src/solar_challenge/config.py`, `docs/web-ui-design.md`; `tests/unit/test_web_simulation_params.py`, `tests/unit/test_web_fleet_scenario.py`, `tests/unit/test_web_builder_form.py`, `tests/unit/web_api/`.
- **Signal:** rows P1–P3, plus the `null` half of L6.
- **Prereqs:** δ, S4 η.

**ζ — Names, labels and booleans are read as their JSON types** (leaf; priority medium)
- **Keys:** fk-da0e3a4df6e7, fk-5827f41eb082 (from 517, §11 Q1).
- **Work:**
  - Decision 15: `read_string` and `read_boolean`, applied at the listed fields.
  - `ParsedFleetForm.name` typed: `str`, or `str | None` if S19 ζ (817) has deleted the fleet default.
- **Files:** `src/solar_challenge/web/{request_boundary,simulation_params,fleet_scenario,api,assistant}.py`; `tests/unit/web_api/`, `tests/unit/test_web_history.py`, `tests/unit/test_web_scenarios.py`, `tests/unit/test_web_simulation_params.py`, `tests/unit/web_assistant/test_chat.py`.
- **Signal:** row S1, and `chat` with `message: 5` answers an SSE error frame naming `message`.
- **Prereqs:** δ.
- **Supersedes:** 331, 517, 560.

**η — The home body's heat-pump block is config's heat_pump block** (leaf; priority medium)
- **Keys:** fk-70edc755ede4.
- **Work:**
  - Decision 16.
  - Delete `_parse_heat_pump_block`.
  - `home.html`'s payload sends `heat_pump_type`.
- **Files:** `src/solar_challenge/web/simulation_params.py`, `src/solar_challenge/config.py` (or `scenario_blocks.py`), `src/solar_challenge/web/templates/simulate/home.html`; `tests/unit/test_web_simulation_params.py`, `tests/unit/web_api/test_simulate_home_and_fleet.py`, `tests/e2e/test_enable_switches.py`.
- **Signal:** row H1. The home page's heat-pump tab submits a GSHP run with the capacity set (e2e).
- **Prereqs:** δ.
- **Supersedes:** 245.

**θ — The service accessors move beside the dashboard holder; shared.py goes** (leaf; priority low)
- **Keys:** fk-bd7f2abebeba.
- **Work:** decision 17. Every importer reads the accessors from `web.dashboard`.
- **Files:** `src/solar_challenge/web/{shared,dashboard,api,assistant,history,routes}.py` and the tests that patch `shared`.
- **Signal:** row G2, with the full web suite green.
- **Prereqs:** β, S16 δ.
- **Not held (L34):** S16 δ is filed as task 889, so θ depends on it and is committed with the batch.

**κ — Integration gate: one grammar, one refusal and one presence rule across both boundaries** (leaf; integration gate; priority medium)
- **Keys:** fk-6c98ee030531, fk-1d143fefefed, fk-66f886576b3f.
- **Work:**
  - A boundary module (`tests/integration/test_request_boundary.py`) runs row L5 across the CLI and the web.
  - A route table asserts that every `/api` POST route answers a `ConfigurationError` body 400 and a `TypeError` 500 JSON.
- **Signal:** rows L5, R1 and R3 across every `/api` POST route; the per-task verify runs it.
- **Prereqs:** α, γ, δ, ε, ζ, η.

**DAG:** S4 β → α; 394 → β; {α, β} → γ; {γ, 774, 297, S4 β, γ, δ, η} → δ; {δ, S4 η} → ε; δ → ζ; δ → η; {β, S16 δ} → θ; {α, γ, δ, ε, ζ, η} → κ.

**Signal leaf:** κ.

## 10. Out of scope

- The scenario grammar taking a preset name as a `location:` value (`location: london` in YAML). It would be a scenario-grammar extension (S5/S6); the follow-up candidate is noted for the lead.
- The home page's client-side latitude and longitude bounds, which restate `Location`'s range in JS (S18's PageLimits territory).
- `scenario-builder.js`'s `cfg.location.latitude || 51.45` when a saved preset loads into the builder (S18's script).
- The fleet page gaining a location control, and fleet import loading a scenario's location (S6).
- The sweep's `parameter` and `mode` (S26), its number reads (S4 η), and the assistant's `n_homes` clamp (S4 η) and tool-argument coercions (751).
- Stored-run decoding and its refusal type (S19 κ).
- Default run names (S19 ζ).
- Exporting `LOCATION_PRESETS` or `parse_location` from `solar_challenge` (no surface change; S29 would carry it).

## 11. Open questions

**Tactical** (decide in the leaf):

- **Q-T1 (α).** What a coordinate location is named. Today the CLI says `Custom (51.50, -0.10)` and the web says `''`. Suggested: the CLI's, since it reaches the exported scenario's `name:`.
- **Q-T2 (α).** Which plain-`ValueError` CLI input pins `handle_errors`' clause order once `--location` and (after S4 β) `--battery-kwh` raise `ConfigurationError`. Suggested: a `CliFleetSimulator` that raises `ValueError`, through `tests/_cli_fleet_simulator.invoke_cli`.
- **Q-T3 (γ).** The option label format per page (name only, or name and coordinates). Suggested: one Jinja macro over the table, called with a flag for coordinates.
- **Q-T4 (γ).** Whether γ's tightened `location:` block needs an "Unreleased on main" line. Only if `load_scenarios` or another frozen-surface name reaches it; check `FROZEN_SURFACE` at γ's base.
- **Q-T5 (κ).** The harness for row L1 at κ's base. S15 makes weather an explicit input, so seed the CLI's weather through whatever `home run` prefetches through then.

**For the lead** (cross-stream; the design holds whichever way each goes):

1. **Task 517 and fk-5827f41eb082.** S4 decision 9 assigned 517's `stochastic`, `name` and `location` reads to "task 517, S17". Proposed: ζ supersedes 331, 517 and 560, and fk-5827f41eb082 moves onto ζ's `x_finding_key`.
2. **fk-a0866b1bd680 (high).** The invariant is config's and belongs to task 297, whose plan already refuses the pool by name. Proposed: stamp the key on 297 and raise 297 to high. Both 297 and δ, which carries the route half (row R4), then become dependencies of gate 772.
3. **The `location:` block tightening (decision 6)** is a config-grammar change in a module S5 moves and S6 consumes. Proposed: S17 γ makes it, so one mapping rule serves files and requests; S5 moves it.
4. **θ on S16 δ** (ruled by L34: a dependency on task 889, not held). S19's `get_database` and S20's policy accessor move with θ if they have landed; otherwise they are added to `web/dashboard.py` directly (cross-reference lines).
5. **D2's reading (§3.1).** A non-domain `ValueError` is answered 400 and logged at ERROR, not answered 500. This PRD follows the ruling's text; a 500 would be one line in `answer_refusal` if Leo meant that.

## Gate record

- **G1, consumer named.** Every mechanism has a named consumer:
  - `LOCATION_PRESETS` and `parse_location`: `home run --location`, `config locations`, the web location reader, the builder, three pages and the assistant's tool schema.
  - `request_boundary`: the three form readers and the `/api` blueprint.
  - `refusal_text` and the handlers: every `/api` route, the assistant tools and chat, builder validate and the fleet preset menu.
  - `present_fields`: the three form readers. `read_string` and `read_boolean`: the listed endpoints.
  - `parse_heat_pump_block`: the home reader. `PV_CAPACITY_KW_WHEN_OMITTED`: `_parse_pv_config` and the home reader.
  - The strict `location:` block: scenario files and web mappings.
- **G2, observable leaves.** Every leaf names user-observable rows (CLI exit and text, HTTP status and body, a log record, a rendered page, an e2e path). β is an intermediate that unlocks γ, δ and θ, and its own row G1 is a CI-run import guard. κ is the integration gate.
- **G3, substrate checked.**
  - On main: `Location.bristol()`; `Location`'s range refusal; `config.parse_location_block` and its unrecognised-key-first order; `_parse_heat_pump_config` refusing an unknown key (probed: "Unrecognised keys in heat_pump: 'thermal_capacity'"); `_PV_CAPACITY_KW_WHEN_OMITTED`; `cli.home.home_config_for_run` calling `load_config_with_overrides` before any simulation; `fleet_preset_form` using a dict lookup.
  - The Flask behaviour: a blueprint `ValueError` handler catches a subclass, and a blueprint 500 handler receives an unhandled `TypeError` with a JSON body (probed on Flask 3.1.3).
  - The offline guard and the `weather_cache` fixture (`tests/conftest.py`).
  - Produced upstream: `ConfigurationError ⊂ ValueError` (774), `number_fields` at the leaf (S4 α), the input types' `ConfigurationError` (S4 β, γ, δ), the pool refusal (297) and `refuse_unrecognised_keys` (394).
  - Upstream: S16's `web/dashboard.py` (task 889).
- **G4, seam owners.** §8 assigns every overlap. S1 and S17 on the web deletions is resolved to S17 (S1 PRD decision 8, cross-reference line). The accessor location is S17's and the holder S16's.
- **G5, B + H.** The blast radius is location, the CLI, config, eight web modules, three templates and the assistant, and six streams touch the same files. §5 is the contract, §6 the sketch, and κ the gate.
- **G6, premises checked.**
  - Every refusal row's mechanism was observed absent today (§2.2) and is delivered by its leaf or upstream: α's grammar, γ's block rule, δ's handlers, ζ's readers, η's use of config's reader, which is observed to refuse.
  - R4 needs 297 upstream, so δ depends on it.
  - L1's proof that the CLI ran at London rests on the offline guard refusing any uncached location.
  - No numeric bound is asserted.
- **G7 (advisory; the project has no `docs/legibility/design-invariants.md`).** Screened against dark-factory's trigger shapes:
  - `no-silent-fail-soft`: the Bristol fill-in for a partial block goes, and a non-domain `ValueError` is logged. The presence rule's defaults are documented API behaviour that matches config's omitted-field rule, not a silent substitution.
  - `one-fact-one-home`: one preset table, one string grammar, one mapping grammar, one refusal rule, one omitted-capacity constant.
  - `guards-exercise-behaviour`: every invariant has a behavioural row; the grep checks are additional.
  - No allow-list or suppression is added. No hit.
- **META.** Decomposed and queued without further oversight, this yields one location grammar owned below both front ends, one refusal type with one translator, and one presence rule with named defaults. Every overlap with S4, S5, S16, S18, S19 and S22 has an owner and an order. The only open items are tactical or lead bookkeeping.
