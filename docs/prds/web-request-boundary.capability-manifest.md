# Capability manifest — Web request boundary (review-all S17)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/web-request-boundary.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/web-request-boundary.capability-manifest.yaml`.

**Code anchors** verified against main `2ff5673` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS, conditional on wiring.**
- No binding resolves to `declared-only`, `test-only`, `producer-downstream`, `producer-extent-short` or `rejection-absent`.
- Five bindings name producers that are filed but not yet done: 774, 297, 394, and S4 β, γ, δ and η, whose ids are pending S4's decompose.
- One binding names a producer not yet filed: S16 δ, for the held θ.
- Each such binding is PASS once its edge is wired at decompose; until then it reads `producer-absent` for that leaf, and the leaf is not queued.

## α — location.py owns the presets and one strict string grammar; the CLI reads it (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `home run --location` is parsed before any simulation, so L2 needs no weather | grep: `cli/home.home_config_for_run` calls `load_config_with_overrides(location_str=…)`, which calls `parse_location`, before `simulate_home` | PASS |
| The CLI turns a parsed Location into a `location:` mapping read by `parse_location_block` | grep: `load_config_with_overrides` writes `config["location"]` from the Location's fields; `home_config_for_run` reads it with `parse_location_block` | PASS |
| `Location` refuses `95,0` by range (L2 `'95,0'` row) | probe: `Location(95, 0)` → "Latitude must be between -90 and 90, got 95.0" | PASS (rejection observed) |
| …as `ConfigurationError`, so the CLI prints `Configuration error:` | producer: S4 β (converts `Location`; id pending), upstream of α | PASS once wired |
| `number_fields.as_finite_float` at the package leaf, raising `ConfigurationError` | producer: S4 α (via S4 β), upstream | PASS once wired |
| `handle_errors` labels `ConfigurationError` `Configuration error:` | grep: `cli/utils.handle_errors` except chain | PASS |
| An offline test fails on an uncached location (L1's proof the run is at London) | grep: `tests/conftest.py` network guard and `weather_cache` fixture; CLAUDE.md "Offline fast tests" | PASS |
| `'londn'` refused today by the CLI, but `'london'` refused too (RED for L1) | probe: `cli.utils.parse_location('london')` → `ValueError` "Invalid location format" | PASS (RED observed) |

## β — The request readers move below the Flask services (intermediate → γ, δ, θ)

| Capability | Evidence binding | Status |
|---|---|---|
| The readers import `shared` only for the request half | review measurement (fk-bd7f2abebeba), re-read at `2ff5673`: `builder_form` imports `LOCATION_PRESETS`, `NotAJsonObject` and `require_json_object`; `fleet_scenario` imports `resolve_location`; `simulation_params` imports `require_json_object` and `resolve_location` | PASS |
| `shared.py` pulls `web.jobs` and `web.storage` in at top level (RED for G1) | grep: `from solar_challenge.web.jobs import JobManager` and `from solar_challenge.web.storage import RunStorage` in `web/shared.py` | PASS (RED observed) |
| `refuse_unrecognised_keys` exists to move | producer: task 394 (pending, resumed), upstream | PASS once wired |

## γ — The web reads a location with the one grammar (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| `location.parse_location` and `LOCATION_PRESETS` | producer: α, upstream | PASS |
| `request_boundary` exists to hold `read_location` | producer: β, upstream | PASS |
| `parse_location_block` reads a mapping into a Location (L6 accepted half) | probe: `{"latitude": 51.5, "longitude": -0.1, "altitude": 11}` → `Location(51.5, -0.1, 'Europe/London', 11, '')` | PASS |
| A partial block is accepted silently today (RED for L6 and L7) | probe: `parse_location_block({"latitude": 50})` → `Location(50, -2.58)` | PASS (RED observed); refusal delivered by γ |
| Shipped scenarios survive the tightening | scan: all 12 `scenarios/*.yaml` with a `location:` block set both `latitude` and `longitude` | PASS |
| The web refuses the CLI's three-part form today (RED for L4) | probe: `POST /api/simulate/home` `location: "51.5,-0.1,11"` → 400 | PASS (RED observed) |
| A refusal reaches the client as 400 before δ | grep: `api.simulate_home_api` and the fleet routes catch `ValueError` or `FLEET_FORM_REFUSALS`; `ConfigurationError ⊂ ValueError` from 774, transitively upstream through S4 α | PASS |
| The three pages are rendered by routes that can pass the table | grep: `routes.simulate_home_page`, `scenarios.builder`, `scenarios.sweep` | PASS |
| The assistant's tool schema can be derived from a table | grep: `TOOLS`' `consumption_kwh` description is formatted from `FLEET_COMPONENTS["load"].fixed_range` | PASS |

## δ — One refusal type and one translator at the web boundary (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| `ConfigurationError ⊂ ValueError` | producer: 774 (in progress), upstream | PASS once wired |
| Input types refuse with `ConfigurationError` (R1 logs nothing for a domain refusal) | producer: S4 β, γ, δ (ids pending), upstream | PASS once wired |
| The web's number pre-reads are settled before δ converts the readers | producer: S4 η, upstream | PASS once wired |
| A blueprint `ValueError` handler catches a subclass (R1, R2) | probe: Flask 3.1.3 blueprint `errorhandler(ValueError)`, view raising a subclass → 400 JSON | PASS |
| A blueprint 500 handler answers an unhandled `TypeError` with JSON (R3) | probe: blueprint `errorhandler(500)` with `PROPAGATE_EXCEPTIONS` off, view raising `TypeError` → 500 `application/json`; `Flask.handle_exception` looks handlers up by `request.blueprints` | PASS |
| `/api` answers HTML for a defect today (RED for R3) | probe: `POST /api/presets` `name: 5` → 500 `text/html` | PASS (RED observed) |
| A short pool is refused by name (R4) | producer: task 297 (pending; plan: `FleetDistributionConfig.__post_init__` and `generate_homes_from_distribution` raise `ConfigurationError` naming the path, the pool size and `n_homes`), upstream; extent covers the fleet form path `parse_fleet_form` → `parse_fleet_distribution_config` → `generate_homes_from_distribution` | PASS once wired |
| A short pool answers 500 HTML today (RED for R4) | probe: PV entries 20+40+30+10 with `n_homes` 200 on `fleet-from-distribution` and `export-yaml` → 500 `text/html` | PASS (RED observed) |
| The assistant tools answer an `{"error"}` dict, so R5 is observable without the model | grep: `assistant.run_home_simulation` returns `{"error": f"Invalid simulation parameters: {exc}"}` | PASS |

## ε — One presence rule; defaults separated from nullability (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| `null` and `""` are refused today for valued defaults (RED for P1) | probe: `pv_kw`, `azimuth` and `occupants` null, and `pv_kw` and `days` `""` → 400 | PASS (RED observed) |
| `PVConfig` and `LoadConfig` declare the defaults P2 compares against | grep: `PVConfig` `azimuth`, `tilt`, `system_age_years` and `degradation_rate_per_year` defaults; `LoadConfig.household_occupants: int = 3` | PASS |
| An omitted-capacity constant exists to make public | grep: `config._PV_CAPACITY_KW_WHEN_OMITTED` read by `_parse_pv_config` | PASS |
| The four `PVConfig` pre-reads are already gone, so ε edits settled lines | producer: S4 η, upstream | PASS once wired |
| The fleet form's `null` seed is refused today (RED for P3) | probe: `fleet-from-distribution` `seed: null` → 400 | PASS (RED observed) |

## ζ — Names, labels and booleans are read as their JSON types (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| Wrongly typed names are accepted or crash today (RED for S1) | probe: `simulate/fleet` `name: {"x": 1}` → 201; `presets` `name: 5` → 500 HTML; home `name: ["a"]` → 201; `stochastic: "false"` → 201 with `use_stochastic=True` | PASS (RED observed) |
| The refusal reaches the client through one handler | producer: δ, upstream | PASS |
| S19 ζ's PATCH null/blank-name refusal does not conflict | §4 decision 13: PATCH is outside the presence rule; ζ refuses only a non-string, non-null label | PASS |

## η — The home body's heat-pump block is config's heat_pump block (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| Config's heat-pump reader refuses an unknown key, naming it (H1) | rejection-check: `_parse_heat_pump_config({heat_pump_type: GSHP, thermal_capacity: 12}, block_path="heat_pump")` → "Unrecognised keys in heat_pump: 'thermal_capacity'"; `{type: …}` → names `'type'` | PASS (rejection observed) |
| …and builds the GSHP the body asks for | probe: `{heat_pump_type: GSHP, thermal_capacity_kw: 12}` → `HeatPumpConfig('GSHP', 12.0, 8000.0)` | PASS |
| The web drops the keys silently today (RED for H1) | probe: home `heat_pump: {heat_pump_type: GSHP, thermal_capacity: 12}` → 201, queued `HeatPumpConfig('ASHP', 8.0, 8000.0)` | PASS (RED observed) |
| The home page posts `type` today | grep: `simulate/home.html` `buildPayload` `heat_pump = { type: f.heat_pump_type, … }` | PASS |

## θ — The service accessors move beside the dashboard holder; shared.py goes (leaf; held)

| Capability | Evidence binding | Status |
|---|---|---|
| `web/dashboard.py` with `Dashboard` and `dashboard_of` | producer: S16 δ (not yet filed) | held (`x_seam_wait`); producer-absent until S16 files, so θ is excluded from `commit_planning` |
| The readers no longer import `shared` | producer: β, upstream | PASS |

## κ — Integration gate (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| Both boundaries refuse the same strings with one message (L5) | producers: α (CLI), γ (web), upstream | PASS |
| Every `/api` POST route answers through the one handler (R1, R3) | producer: δ, upstream | PASS |
| A JSON route table exists to enumerate | grep: `api_bp` `@api_bp.route(..., methods=["POST"])` decorators in `web/api.py` | PASS |
