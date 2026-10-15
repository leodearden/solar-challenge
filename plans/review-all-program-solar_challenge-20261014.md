# Program: review-all-program-solar_challenge-20261014

Deliberation of `plans/review-all-solar_challenge-20261013.md` (as_of_sha 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8), sitting of 2026-10-14 (Leo with the review-all lead). Every finding key below is defined in `plans/review-all-solar_challenge-20261013.json`; a stream acts only on its keys. Keys that no stream lists were filed as mechanical tasks in Phase 5 (table in the report) or are refuted.

## Streams

Sized for one /prd session each. Mode `agent` is an agent-team /prd; `spawn` is an interactive /prd session. Wave is the seam order: a stream starts when its upstream deps have filed.

| ID | Slug | Scope | Finding keys | Mode | Size/risk | Wave | Upstream deps |
|---|---|---|---|---|---|---|---|
| S1 | Errors leaf: one exception vocabulary below config | New leaf module solar_challenge/errors.py importing no solar_challenge module; it defines ConfigurationError (base class decided here, see open choice) and config.py, finance.py and gridservices.py import it at top level. The invariant 'a domain invariant fail… | fk-601c5b5f6415 fk-4435376bedb3 fk-da69830bb2d6 fk-291910b552af | spawn | S/low | 1 | — |
| S2 | Dispatch configuration below config | dispatch.py owns the dispatch-configuration types: a frozen DispatchStrategyConfig and GridChargeConfig, a closed strategy vocabulary (StrEnum or tagged union of strategy configs) with one validator, and the strategy factory moved from home._create_dispatch_st… | fk-b3dfd41a4d6a fk-615cbc883512 fk-370b3e49b67c fk-c36d6fcbc2a8 fk-94f4881bbe48 fk-04b52ee632c6 fk-fc652220a4d3 fk-8529726bbd6b fk-99244625d7f2 fk-f126b1c9cbbe | spawn | L/medium | 1 | S1 |
| S3 | One dispatch engine: shared settle tail and bounded decisions | flow.py keeps one settle function for both paths (sum, self-consumption cap, split-source flows, EnergyFlowResult) and one grid-charge gate; DispatchDecision.__post_init__ bounds charge_kw + grid_charge_kw against the battery's charge limit and discharge again… | fk-4df47ebe6a96 fk-491014934d1e fk-7440003fdd59 fk-2a53ae89932e fk-f622bbaa9f2e | spawn | M/medium | 2 | S2 |
| S4 | Finite quantities: one checker in every domain __post_init__ | web/number_fields.py moves down to the package leaf beside whole_numbers.py unchanged in behaviour (as_finite_float, as_finite_float_within, as_whole_number, as_whole_number_within refuse bool, NaN, inf and fractions naming the field). Every domain __post_init… | fk-a9c609ecb8ef fk-b69968a37b36 fk-7dcdc5559d22 fk-649851e5fc38 fk-60410de6dd0a fk-e79170280adf fk-5827f41eb082 fk-239274130a5a fk-a2b33a420bcf fk-f2f8a5512feb fk-606a9211b34d | spawn | L/medium | 2 | S1 |
| S5 | Scenario grammar: config.py partition and the parameter-sweep deletion | Partition config.py along the config-cli seat's measured layering: errors leaf (from the Errors stream) and the moved number_fields <- scenario_blocks.py (block readers, _refuse_unrecognised_keys, _BlockType, every reader raising with its block_path) <- fleet_… | fk-62821dcde535 fk-2dc9d1cd2c06 fk-59fdc80fdded fk-caad5305a3be fk-e2aaf2bfe651 fk-897e13f84164 | agent | L/low | 2 | S1, S2 |
| S6 | Fleet-document scenario overlays: one reader for the blocks that reach the homes | config gains one function that parses a fleet document's scenario-level blocks (location, tariff, seg, finance, flex_band, period, name) into a typed scenario with the same unknown-key refusal as _parse_scenario, applying them to the generated homes under one… | fk-3be3240278ee fk-2264bc150fa3 fk-416eb5643e7a fk-e756dab8077e fk-f99038047a27 fk-a391cf1f4edf fk-ad65ad5e4e48 fk-81d0840d19e2 fk-8047de9b6789 fk-188af6c13d71 fk-0b791f2be2d6 fk-be5b13274bcb | spawn | L/medium | 3 | S5 |
| S7 | Component defaults: one home per component, distributions derive from it | Each component's defaults live on its domain config (PVConfig, BatteryConfig, LoadConfig, HeatPumpConfig, EVConfig) and the distribution layer builds homes with dataclasses.replace over a default instance, so no field list is restated; heat-pump types become o… | fk-148991ab9439 fk-d2b4045c6676 fk-dfeefbe95640 fk-0e58e2a7e007 fk-f2e1ad46df4b fk-2b16cc8bcf46 fk-d6f16d95b126 | agent | M/low | 1 | — |
| S8 | Finance partition: a scenario-economics stratum above bill arithmetic | Step one is p84's prose rehoming (CR/W/Greek codenames, 'Suggestion 3/4' headings, stale cli pointers, the non-linear 'exactly affine' claim) with a re-measure after it. Then, resting on f39's heuristic-13 symptoms (7 cycle-free function-local import statement… | fk-5fdb04305288 fk-41283f42a36a fk-6cd8a932665c fk-b0f648b0e6d0 fk-9cc706d3afdd fk-c2c9277c1920 fk-c0e0ae3dcca8 fk-4a9af7c31a4f fk-3b0a239d0489 fk-52fa98174363 fk-caeaf35c8151 fk-50cf1dd5df58 fk-9fa18977ec68 fk-3f4daea21220 fk-62dbe0f34b68 fk-808be5588896 fk-5b34adae950b | spawn | L/medium | 2 | S1, S9, S10 |
| S9 | Grid-services figure as an explicit input and a closed model selector | FinanceConfig.grid_services_model becomes a closed type (none | flat band | capacity_at_events(config)) validated once at construction, so the four selector checks and the admitted 'capacity_at_events with events None' go. project_multi_year takes the age-0 fl… | fk-4ddab794283a fk-758b2f309cab fk-aafe32daa988 fk-d432a549b03f fk-0f24b7f66eb2 fk-71b4ca35efe0 | spawn | M/medium | 1 | S1 |
| S10 | Window length and cadence as typed values in timebase | timebase.py owns SimulationWindow: covered days derived from the tz-aware minute index (not timedelta.days), the one-minute cadence, one kW-to-kWh integration helper that reads it, and annualisation_scale() with the one threshold. SummaryStatistics.simulation_… | fk-1cd332300623 fk-d63c41ca13f9 fk-286fe17c28c9 fk-756c0ef9e9d9 fk-7ef1099d24e8 | spawn | M/medium | 1 | — |
| S11 | Tariff: coverage invariant, one cheap-period classifier, named preset defaults | TariffConfig.__post_init__ checks that sorted periods tile the 24-hour day exactly once, raising with the gap or overlap times named, and TariffPeriod requires a finite rate; TariffConfig exposes the cheap-period classifier (flow._is_cheap_period moves onto it… | fk-872021ade9b6 fk-2f88003e22c8 fk-97213a0e9ab2 fk-bd03fe349ffd fk-463e82417506 fk-4872e7ab367e | spawn | M/medium | 1 | S1 |
| S12 | Load composition: additional loads one mechanism, calendar-aligned days | home.simulate_home composes a sequence of named load contributions (household, heat pump, EV) from each configured component and SimulationResults carries a mapping of named load series; summary, output, charts and templates iterate it instead of branching per… | fk-781d153ab978 fk-1d920c89e872 fk-740e9a804a4f fk-7fa120a8bb98 fk-89777ec9faad fk-72af0b90338d fk-1609d8c3d091 | spawn | L/medium | 2 | S10, S19 |
| S13 | RNG hand-off: the seed travels with the call | load.py owns the global-RNG hand-off: a module-private lock and a context that saves np.random and random state, seeds both from LoadConfig.seed (fresh SeedSequence entropy when None), runs the richardsonpy window and restores the state, so profiles are identi… | fk-16df1a7ac416 fk-e0e34ef46058 fk-c78416de5500 | agent | S/low | 1 | — |
| S14 | PV model: one home for module choice, run policy and ageing | pv.py names the default CEC module row as a constant and requires it the way _require_cec_library_row requires inverter rows, deleting the substring search and both fallbacks; exposes one public run-the-chain function that applies the scipy warning policy and… | fk-48447960eb2c fk-616cc076b7cb fk-0edf0069c6bb fk-8b8f9d686b86 fk-a98db49f3fd7 fk-f5cd69400ce6 fk-998f0cb69410 fk-835a87838a52 fk-3ccbba41d836 | spawn | M/medium | 1 | — |
| S15 | Weather as an explicit input | simulate_home takes weather_data (or a weather provider) as a required input; cli/home, the web JobManager and any sweep runner prefetch per location as fleet.simulate_fleet_iter already does; WeatherCache.get reads what put writes (tz sidecar, metadata) with… | fk-44fdf5fb356b fk-06035cd76226 fk-e4549a3a6b54 | spawn | M/medium | 1 | — |
| S16 | Fleet execution policy as one value | One frozen FleetRunner (parallel, max_workers, validate_balance, progress sink, home simulator) with simulate(FleetConfig, start, end), built once at each boundary: the CLI (CliFleetSimulator wraps it and gains a per-home progress callback so fleet run and fle… | fk-7e76b4cf2cb2 fk-f3a20a6d53e0 fk-31fd9d5d4c68 fk-d89ee8df893c fk-cc292d7ce407 fk-e58042aef503 fk-f7b19fc4c8b5 fk-7bdd33abd0ff fk-f6c905f91d32 fk-7aaa879bf0ac | spawn | L/medium | 2 | S15 |
| S17 | Web request boundary: one refusal, one presence rule, one location grammar | A request-reading module below the Flask services (shared.py split: readers and NotAJsonObject here, get_storage/get_job_manager beside app/jobs) applies one presence rule (null and '' are absent, defaults separated from nullability) to every body before readi… | fk-6c98ee030531 fk-1d143fefefed fk-29af8a4fe018 fk-66f886576b3f fk-bd7f2abebeba fk-0593b530a371 fk-acdc650baeb8 fk-da0e3a4df6e7 fk-a0866b1bd680 fk-ba29e186122f fk-70edc755ede4 | spawn | M/medium | 2 | S1, S4 |
| S18 | Dashboard limits and distribution editing from one table | fleet_components.page_limits() returns a frozen PageLimits (MAX_FLEET_HOMES moves in beside each FleetComponent's fixed_range/step/default, seed and days bounds) that routes render into fleet.html, builder.html and the scripts, so no limit is a template or JS… | fk-1df9dbc0d971 fk-f8b7b3ab709d fk-366773b4083f fk-a6d9f3e5a7e2 fk-8107696f0b02 fk-7893b49b92c3 fk-88374e6e3553 fk-40dff1473b94 fk-d303b6dbf669 fk-9dd1d9389dd2 fk-006c3339e3b2 fk-021a21b35427 fk-3cd0d3f3b512 fk-c3625a25eed4 | spawn | L/medium | 3 | S5, S4 |
| S19 | Run store with one owner: connection, schema version, stored-run format, run type | RunStorage is the one owner of the runs table and the stored-run format: database.connect(db_path) applies the connection policy (WAL, row_factory, foreign_keys) for init_db, get_db and the job connection; init_db writes PRAGMA user_version and applies ordered… | fk-bfdae4525795 fk-df9d0fc1b2d3 fk-9d7f66fdcfdd fk-34a6679f1ef3 fk-a37ed16d59c5 fk-273b8b09c91a fk-1070454e4c6e fk-cca5fd81afda fk-c14c02dc1b77 fk-e29393df0cd4 fk-2ff305a1dbb2 fk-8f4f4d63f917 fk-2ac79d7a1989 fk-81e62b2640a7 | spawn | L/high | 1 | — |
| S20 | Job events and SSE framing | jobs.py holds one job state table (JobStatus transitions) and _finish_job/_report_state refuse a transition the table does not allow, stamping finished_at only on terminal states; each event type has one typed payload and one web module frames SSE (sse_frame(e… | fk-7eb56fda0b1c fk-4540d657bff6 fk-484952247bb6 fk-0097b5aaa45c fk-066e5cb461f7 | spawn | M/medium | 2 | S19 |
| S21 | Results chart panels, theme tokens and chart facts | charts.py returns a ChartPanel value (figure JSON or a named absence reason) rendered through the existing chart_container macro (macros.html:78, already live on compare.html:118 and :129; p122's measurement corrected to 'unused on results/home.html and result… | fk-42c0053b9a2b fk-93ee9a05751a fk-8e109704aa24 fk-3239afd8ce6b fk-8f26d000b68d fk-ff5b90768f66 fk-2e7ddcee2379 fk-657669b23e71 fk-ce345e3b013d fk-55f4e4ea396d fk-02500b87f3cb | spawn | M/low | 1 | — |
| S22 | Assistant facts from the engine | assistant.py derives its TDCV figures, benchmark bands and yield figure from load.OFGEM_TDCV_BY_OCCUPANTS and validation's band constants (one import, not three copies); TOOLS carries each tool's handler so dispatch_tool is a lookup; chat() is split into the s… | fk-194e5b40da23 fk-93d3bd7aa219 fk-ab16fff6f6c3 | agent | S/low | 1 | — |
| S23 | Surface lock | One surface-contract test module organised by behaviour (laziness, pvlib-free import, frozen forms, drift message) replaces test_init_lazy_surface.py and test_public_api_surface.py; the exported-name count derives from FROZEN_SURFACE rather than a literal; __i… | fk-293a1282ace4 fk-9df95e9e2b45 fk-879e8c13f581 fk-ca5301a6f39f fk-d2881616c782 fk-dc5370224a78 fk-b0607cc5a685 fk-ac70915ba435 | agent | M/low | 1 | — |
| S24 | Lane harness: one typed collection source, one lane-only mechanism, gates over tests/ | tests/_collect_only.py obtains node ids and interpreter names from pytest's --junitxml report (the seam test_per_task_verify.py:84 already uses) instead of parsing '::' stdout; tests/e2e/conftest.py's existing pytest_collection_modifyitems hook adds pytest.mar… | fk-1abd62632ae1 fk-dd434cb2d4b9 fk-eec3806e584e fk-f48c29a98a89 fk-a0b751097301 fk-e5820c5e22ed fk-5de02e56b3af fk-3667e4e32155 fk-a9aad5f6d1b2 | spawn | M/low | 1 | — |
| S25 | Board reports: one typed row source and one assumption mode per report | cli/finance.run resolves each --assumptions mode to its own FinanceConfig once and drives bill, projection, solve and events per mode from that value; generate_finance_report takes labelled sections keyed by mode instead of a positional bill_physics; events in… | fk-2106d1fbaed0 fk-b7241e0ce122 fk-89afcb2b57f7 fk-f66948b9528c fk-b523bff3e51c fk-ae20e1833a19 fk-41767a1bc146 fk-ef13881623be fk-6a52ed98b18e | spawn | M/medium | 3 | S6, S10 |
| S26 | Sweep knob registry | One registry below the entry points maps a typed knob identifier to a pure ScenarioConfig -> ScenarioConfig transform, with value generation always through SweepSpec (one default mode); the YAML sweep's placement is data the registry knows, so a sweep multipli… | fk-4cc34de4e649 fk-ac39320dcf1d fk-bea05911eb70 fk-32d5e6707fb5 fk-3ca00f8edeb8 fk-0b4f5e04067c | spawn | L/medium | 3 | S5, S6 |
| S27 | Community: dispatch from the factory, mode derived from the battery | CommunityConfig takes a dispatch strategy config and the community battery runs through the dispatch factory from the Dispatch stream with the tariff; sharing_mode becomes a property derived from community_battery (or each mode a frozen variant carrying its ow… | fk-664e2030921e fk-083990041fdc fk-dc5cf2ec9b84 fk-8995288451e6 | agent | S/low | 2 | S2 |
| S28 | Battery facts: one representation each for efficiency and throughput | BatteryConfig holds two efficiency facts in two fields; round-trip efficiency is a classmethod constructor (or __post_init__ refuses a set efficiency that contradicts per-direction values, naming both) and _parse_battery_config refuses a block setting both for… | fk-35b8ddcf5565 fk-50a3985fae0f | spawn | S/medium | 1 | S1 |
| S29 | Surface version bump and consumer recipe (D4) | One coordinated bump of the frozen public surface: FROZEN_SURFACE/FROZEN_CLOSURE/FROZEN_MEMBERS updated once for every retired or renamed name the program introduced, docs/domain-library-consumption.md gains one Unreleased-on-main section and the tag conventio… | (program closing step) | agent | S/medium | 4 | every stream that changes a frozen name |

Full remedy and deletable text per stream:

### S1 Errors leaf: one exception vocabulary below config

Remedy: New leaf module solar_challenge/errors.py importing no solar_challenge module; it defines ConfigurationError (base class decided here, see open choice) and config.py, finance.py and gridservices.py import it at top level. The invariant 'a domain invariant failure raises the one error type the CLI and web boundaries catch' is enforced by cli/utils.handle_errors and the web boundary translator catching that type and by an import-graph test asserting zero cycle-closing deferred imports.

Deletable: The 11 function-local ConfigurationError imports (finance.py:119, :1540; gridservices.py:237-266 x8, :345), about 20 lines of cycle-break prose in gridservices.py and finance.py, and, if the ValueError base is chosen, web's three 'raise ValueError(str(exc)) from exc' rewraps and the FLEET_FORM_REFUSALS tuple.

### S2 Dispatch configuration below config

Remedy: dispatch.py owns the dispatch-configuration types: a frozen DispatchStrategyConfig and GridChargeConfig, a closed strategy vocabulary (StrEnum or tagged union of strategy configs) with one validator, and the strategy factory moved from home._create_dispatch_strategy. The factory takes the battery's grid_charging and the tariff and returns the dispatcher. Battery answers target_soc_kwh(fraction) on its effective (SOH-derated) capacity and flow passes the Battery's answers instead of reading battery.config. config.py and scenario_writer construct and emit these types and never define them; parse_home_block refuses an unknown strategy naming the block path. Enforced at construction (the vocabulary) and at use (the factory refuses or warns per the open choice).

Deletable: battery.py's TYPE_CHECKING import of config types; web/storage._field_types' namespace merge of solar_challenge.config and its docstring; web/fleet_config.py's TYPE_CHECKING import; config._VALID_DISPATCH_STRATEGIES and the 'greedy' defaults in HomeConfig and generate_homes_from_distribution; home._create_dispatch_strategy's if/elif and simulate_home's use_tariff_tou predicate; 11 battery.config.* reads in flow.py; the three peak_hours validators collapse to one.

### S3 One dispatch engine: shared settle tail and bounded decisions

Remedy: flow.py keeps one settle function for both paths (sum, self-consumption cap, split-source flows, EnergyFlowResult) and one grid-charge gate; DispatchDecision.__post_init__ bounds charge_kw + grid_charge_kw against the battery's charge limit and discharge against the shortfall, so Battery.charge's per-call clamp is a second check, not the only one. Settlement is computed on pre-efficiency energy with the loss term carried into validate_energy_balance.

Deletable: flow.py:412-438 (verbatim copy of 290-316) and the preamble copy 356-376; the identical 15-line grid-charge gate in TOUOptimizedStrategy and PeakShavingStrategy; the two NOTE comments at the settle sites; the 'battery layer clamps downstream' docstring line at dispatch.py:601-602.

### S4 Finite quantities: one checker in every domain __post_init__

Remedy: web/number_fields.py moves down to the package leaf beside whole_numbers.py unchanged in behaviour (as_finite_float, as_finite_float_within, as_whole_number, as_whole_number_within refuse bool, NaN, inf and fractions naming the field). Every domain __post_init__ that today writes 'x < 0' or 'not 0 < x < inf' calls it with the field name; config.py's readers (_parse_pv_config's splat, _parse_ev_config's int(), parse_fleet_distribution_config's int(n_homes), _build_*_spec's float(), _substitute_variables' float(default_str)) call it with the key path, so the web no longer pre-reads numbers ahead of config. Enforced redundantly: at parse (key path) and at construction (field name), both through the one checker.

Deletable: config._parse_seg_rate_scalar's private isfinite rule; fleet_config._build_distribution_dict's rebuild and _spec_number's invented defaults; fleet_scenario._read_fleet_size_and_seed ('ahead of the loaders'); simulation_params' pre-reads of numbers config will refuse; api.simulate_sweep's bare float()/int(); every 'not 0 < x < math.inf' and NaN-permissive '< 0' idiom in battery, load, dispatch, location, seg, tariff, gridservices, flex.

### S5 Scenario grammar: config.py partition and the parameter-sweep deletion

Remedy: Partition config.py along the config-cli seat's measured layering: errors leaf (from the Errors stream) and the moved number_fields <- scenario_blocks.py (block readers, _refuse_unrecognised_keys, _BlockType, every reader raising with its block_path) <- fleet_distribution.py (distribution types, sampler, generate_homes_from_distribution, sweep expansion) <- config.py (ScenarioConfig, loaders, parse_fleet_config). Delete run_parameter_sweep, SweepResult, ParameterSweepConfig, _apply_parameter_to_home and _modify_* with tests/unit/config/test_parameter_sweep.py (0 src callers), which removes config.py's top-level imports of simulate_home and simulate_fleet. Drop the unread ScenarioConfig.tariff_config and output fields or give them a reader.

Deletable: 266 lines of parameter-sweep runner and its test file; config.py's imports of home and fleet; the cli/config.py templates' dead output:/period: keys; every reader-local error message that omits its block_path.

### S6 Fleet-document scenario overlays: one reader for the blocks that reach the homes

Remedy: config gains one function that parses a fleet document's scenario-level blocks (location, tariff, seg, finance, flex_band, period, name) into a typed scenario with the same unknown-key refusal as _parse_scenario, applying them to the generated homes under one stated policy. ScenarioConfig becomes a deep value: homes() returns the resolved list for either form and with_seg(policy) returns homes with the scenario SEG applied. cli/finance.run, cli/optimize.configs, cli/home.home_config_for_run, cli/fleet.run, web fleet import (fleet_scenario) and the builder's validation call it.

Deletable: cli/utils.load_config_with_overrides' hand-written home/pv/load/location blocks and the whole-block battery replace; the two hand-built ScenarioConfigs in cli/finance.py:228 and cli/optimize.py:267; fleet_scenario._refuse_what_the_loaders_refuse and builder_form._scenario_reader_errors' tempfile; finance._resolve_homes, _reconcile_seg_homes, cli/validate._scenario_homes and optimize's private import; cli/finance.py's SEG threading block and its inert cost-recovery branch.

### S7 Component defaults: one home per component, distributions derive from it

Remedy: Each component's defaults live on its domain config (PVConfig, BatteryConfig, LoadConfig, HeatPumpConfig, EVConfig) and the distribution layer builds homes with dataclasses.replace over a default instance, so no field list is restated; heat-pump types become one per-type record (COP intercept, slope, min, max) that the Literal, the parser's accepted values and calculate_cop derive from; the sampler bounds its pool indices and keys pools by spec identity, not id(). scenario_writer and the parser share the block key tables so what one writes the other reads (system_losses included).

Deletable: The restated PV defaults in PVDistributionConfig, _parse_pv_distribution_config and generate_homes_from_distribution's None fallbacks; the 8.0/8000.0 heat-pump defaults in three places; _modify_pv_config's three ten-field copies and _modify_battery_config (gone with the sweep deletion); the five spellings of the heat-pump vocabulary and 8 loose COP constants.

### S8 Finance partition: a scenario-economics stratum above bill arithmetic

Remedy: Step one is p84's prose rehoming (CR/W/Greek codenames, 'Suggestion 3/4' headings, stale cli pointers, the non-linear 'exactly affine' claim) with a re-measure after it. Then, resting on f39's heuristic-13 symptoms (7 cycle-free function-local import statements, optimize's private _resolve_homes import, p75's partition), move project_multi_year, solve_cost_recovery_rate, project_economics and their helpers into a module above finance beside optimize.py that imports config, fleet, home and gridservices at top level; finance.py keeps FinanceConfig and bill arithmetic with one ledger assembly (householder_bill and the age simulator share one annualise -> billed energy -> SEG income path with a per-home balance check), and publishes the billing-energy records (basis-C own-use, annualised physics, SEG export income) and finance maths (npv, irr, annuity) as public names so tests and optimize stop importing privates. CostRecoverySolution enforces its three documented invariants at construction; YearPoint's clamp and docstring agree.

Deletable: 7 function-local import statements in finance.py (1422, 1517, 1561-1563, 2276, 2350-2351) after the Errors stream removes lines 119 and 1540 and the Grid-services stream removes line 1606; optimize's private _resolve_homes import; 61 test references to 7 private names repointed; _physics_import_cost_gbp's zero-cost inference once a priced/unpriced fact is carried; the 22-line 'read it as billed own-use' note; the second ledger assembly.

### S9 Grid-services figure as an explicit input and a closed model selector

Remedy: FinanceConfig.grid_services_model becomes a closed type (none | flat band | capacity_at_events(config)) validated once at construction, so the four selector checks and the admitted 'capacity_at_events with events None' go. project_multi_year takes the age-0 fleet results (or a precomputed GridServicesAtEvents) as an input, computed once by the caller, so the closure memo and the function-local gridservices import disappear and the compute-once tests assert through the injected input. One rate-band table in gridservices.py that flex, FLEX_VALUE_BANDS' readers and cli/optimize's alias map derive from.

Deletable: _event_gs_memo and finance.py:1606; the string branch and assert in _simulate_age; cli/finance's silent None and cli/optimize's flat-field override; _SENSITIVITY_ALIAS_MAP's (1.5, 12.0, 48.0) literals; FLEX_VALUE_BANDS as a mutable dict; the two tests that monkeypatch gridservices.compute_grid_services_at_events.

### S10 Window length and cadence as typed values in timebase

Remedy: timebase.py owns SimulationWindow: covered days derived from the tz-aware minute index (not timedelta.days), the one-minute cadence, one kW-to-kWh integration helper that reads it, and annualisation_scale() with the one threshold. SummaryStatistics.simulation_days derives from it; bill_distribution and householder_bill (frozen signatures kept) refuse a simulation_days that differs from the summaries' own, naming both; cli/finance passes summaries[0].simulation_days; validation, output.aggregate_annual and charts call the same scale; householder_bill's 'annual' parameter is renamed to the window quantity it is or dropped.

Deletable: 13 inline '.sum() * HOURS_PER_MINUTE' integrations; four '.days + 1' recomputations (validation.py:87, 299; charts.py:370, 526); validation's own 365/duration rule and _check_annual_yield's un-annualised branch; the cli date arithmetic at cli/finance.py:209, 223; the two timestep_minutes=1.0 literals in home.py if the cadence is declared invariant.

### S11 Tariff: coverage invariant, one cheap-period classifier, named preset defaults

Remedy: TariffConfig.__post_init__ checks that sorted periods tile the 24-hour day exactly once, raising with the gap or overlap times named, and TariffPeriod requires a finite rate; TariffConfig exposes the cheap-period classifier (flow._is_cheap_period moves onto it, with mean_period_rate duration-weighted or replaced) and named preset defaults (economy_7, economy_10 rates) in one table. TOUOptimizedStrategy and ev.py's off_peak/solar modes read the classifier instead of peak_hours and literal windows; routes pass the preset table into simulate/home.html and simulate/fleet.html as they pass SEG_PRESETS; the test that patches TariffPeriod._parse_time drives the public cache behaviour instead.

Deletable: flow._is_cheap_period's private authority and its mean_period_rate comparison; ev.py's two copies of the 00:30-07:30 window and the 10:00-16:00 literal; the 0.35/0.13 pairs in home.html:48-50 and fleet-simulator.js:43-45; the three scenario restatements of the economy rates; DispatchStrategyConfig.peak_hours as an independent clock (per the open choice); the wraps-patch in test_tariff_period_time_cache.py:54.

### S12 Load composition: additional loads one mechanism, calendar-aligned days

Remedy: home.simulate_home composes a sequence of named load contributions (household, heat pump, EV) from each configured component and SimulationResults carries a mapping of named load series; summary, output, charts and templates iterate it instead of branching per kind. load, ev and heat_pump generators produce series aligned to the tz-aware minute index by calendar day (one shared day iterator), not n_days x 1440 positions trimmed at the end; seasonal factors are normalised to a day-weighted mean of 1; EVConfig parses charger_type and smart_charging_mode into the existing enums at the boundary and the EV scheduler charges the needed energy across the window. simulate_home's nine jobs shrink to orchestration; _try_richardsonpy_profile's one try block splits into import, window, DST and scaling steps.

Deletable: load.py:447's function-local ev import and base_load.add(fill_value=0.0); 18 heat-pump presence branches across 7 files and the three Optional summary fields; ev.py's five 1440 literals and the replace('kW','') parse; the DST trim/pad copy; the 'Despite the name' disclaimers once the window helpers are renamed.

### S13 RNG hand-off: the seed travels with the call

Remedy: load.py owns the global-RNG hand-off: a module-private lock and a context that saves np.random and random state, seeds both from LoadConfig.seed (fresh SeedSequence entropy when None), runs the richardsonpy window and restores the state, so profiles are identical serially and concurrently (briefing line 252). FleetConfig.create_uniform and create_heterogeneous give each home its own LoadConfig seeded fleet_seed + index (briefing 82-83). The per-day simulator is an injectable parameter of generate_load_profile so tests stop patching load privates. A test runs two seeded profiles on two threads and compares them with the serial run.

Deletable: The shared LoadConfig in create_uniform and the unseeded LoadConfigs in create_heterogeneous; tests/unit/test_load.py:547's monkeypatch of _simulate_stochastic_day; the order dependence of unseeded homes after a seeded one.

### S14 PV model: one home for module choice, run policy and ageing

Remedy: pv.py names the default CEC module row as a constant and requires it the way _require_cec_library_row requires inverter rows, deleting the substring search and both fallbacks; exposes one public run-the-chain function that applies the scipy warning policy and ageing (degradation on DC before the inverter, or documented) and returns the run chain, used by simulate_pv_output and both measurement scripts; wired_dc_capacity_kw reads the built PVSystem and validation reads wired capacity instead of capacity_kw * 900; PVConfig's module_efficiency and temperature_coefficient either drive the model or leave the config (frozen-surface bump) and the stated validation bands match the applied ones.

Deletable: _get_cec_module's two fallbacks and the wrong CS6K-400MS comment; three verbatim copies of the _chandrupatla filter (pv.py, two scripts) and the broader test filter; the gamma_pdc != -0.004 sentinel; the recomputed module parameters in wired_dc_capacity_kw; validation's two capacity_kw * 900 sites and the two stated/applied band mismatches.

### S15 Weather as an explicit input

Remedy: simulate_home takes weather_data (or a weather provider) as a required input; cli/home, the web JobManager and any sweep runner prefetch per location as fleet.simulate_fleet_iter already does; WeatherCache.get reads what put writes (tz sidecar, metadata) with one os.replace; the module-global cache and set_weather_cache are retired from the frozen surface at the next contract revision, the composition root constructing the cache value and passing it.

Deletable: weather._weather_cache and get/set_weather_cache (after the surface bump); simulate_home's weather_data-is-None fallback; fleet._tmy_by_location's compensation; the three conftest and two script set_weather_cache calls become fixture construction; the unread put fields.

### S16 Fleet execution policy as one value

Remedy: One frozen FleetRunner (parallel, max_workers, validate_balance, progress sink, home simulator) with simulate(FleetConfig, start, end), built once at each boundary: the CLI (CliFleetSimulator wraps it and gains a per-home progress callback so fleet run and fleet sweep use it), the web (create_app takes the JobManager or runner as a parameter and returns the shutdown handle) and tests (which pass their runner in). finance and optimize take the runner in place of the bare simulate callable; simulate_fleet_iter and simulate_multi_sweep_iter share one prefetch/submit loop yielding (index, result). CLI per-invocation state (quiet, consoles) lives on Click's context beside CliFleetSimulator.

Deletable: cli/fleet.py run's 16-line copy of simulate_fleet's assembly; the simulate kwarg threaded through 6 finance/optimize functions; the (validate_balance, parallel, max_workers) tuple on fleet.py's public functions; the duplicated worker formula and as_completed loop; 10 test writes of app.extensions['job_manager']; the module WeakSet and shutdown_all_managers; status_console as a module global and its 8 test patches/restorations; test_cli.py:1161's patch of cli.home.simulate_home; the five @pytest.mark.slow classes in test_fleet.py that only need the runner's fake.

### S17 Web request boundary: one refusal, one presence rule, one location grammar

Remedy: A request-reading module below the Flask services (shared.py split: readers and NotAJsonObject here, get_storage/get_job_manager beside app/jobs) applies one presence rule (null and '' are absent, defaults separated from nullability) to every body before reading, and one boundary translator maps the one refusal type (from the Errors stream) to HTTP 400, so every route catches one type. location.py owns the named presets and one strict 'preset or lat,lon[,alt]' parser; cli/utils.parse_location and web/shared.resolve_location become thin callers; custom coordinates travel as the {latitude, longitude} mapping parse_location_block already reads; the heat-pump block refuses unknown keys like config does.

Deletable: FLEET_FORM_REFUSALS and the three ConfigurationError rewraps; six distinct except-tuples collapse to one; resolve_location's silent Bristol fallback and LOCATION_PRESETS in shared.py; home.html's custom_lat + ',' + custom_lon join; {**_HOME_CONFIG_DEFAULTS, **data}'s accidental nullability; parse_fleet_form's IndexError escape (pool shorter than n_homes refused by name); data.get('name', ...) passed unread.

### S18 Dashboard limits and distribution editing from one table

Remedy: fleet_components.page_limits() returns a frozen PageLimits (MAX_FLEET_HOMES moves in beside each FleetComponent's fixed_range/step/default, seed and days bounds) that routes render into fleet.html, builder.html and the scripts, so no limit is a template or JS literal; the distribution editor's per-type behaviour (fields, defaults, serialise, apply) derives from one per-type table shared with config's grammar instead of if-chains in fleet_config, builder_form, fleet-simulator.js and scenario-builder.js; the preview endpoint samples through config's sampler; the fleet form's tariff/dispatch vocabulary renders from the server tables (as scenarios._script_components does for components); scenario uploads are parsed server-side.

Deletable: fleet-simulator.js's 1000/15.0/6000 literals and fleet.html's max=500, builder.html's 10000; _build_distribution_dict and its lossy rebuild, _draw_samples' per-type chain and _spec_number's defaults; builder_form._distribution_spec's unbounded counts; scenario-builder.js's jsyaml parsing and loadPreset's '|| 51.45'; fleet.html's hard-coded option lists and x-show chains, buildPayload's and _apply*'s type branches, _FORM_TARIFF_SETTINGS/_FORM_DISPATCH_SETTINGS; fleet_config.py's transitive Raises prose and the 26-line docstring over 13 lines of code.

### S19 Run store with one owner: connection, schema version, stored-run format, run type

Remedy: RunStorage is the one owner of the runs table and the stored-run format: database.connect(db_path) applies the connection policy (WAL, row_factory, foreign_keys) for init_db, get_db and the job connection; init_db writes PRAGMA user_version and applies ordered migrations or refuses naming both versions and the file, with the runs DDL derived from RunRecord's fields and a test comparing table_info with fields(RunRecord); save_* write a format version and loaders raise one StoredRunUnreadable naming the run id and field, with _deserialize_dataclass refusing unknown or missing required keys; RunRecord (or a per-type table) names a run type's loader, results endpoint and exporter, exposed to Jinja and the JSON run list; JobManager is constructed with the app's RunStorage and writes through it; listing, summary decoding and the default run name each have one implementation; create_app acquires an exclusive lock under DATA_DIR before recover_stale_jobs; sweep runs are stored as 'sweep' or the sweep_id is dropped.

Deletable: 17 current_app.config reads of DATABASE/DATA_DIR and 3 of 4 RunStorage constructions; raw runs SQL in jobs.py, api.history_list_runs, assistant.list_recent_runs and routes._get_aggregate_stats; the positional 12-column INSERT; the per-tick progress UPDATE+commit; 11 default-name literal sites (7 become none); 9 run-type sites across Python, Jinja and JS and their three fallbacks; the 'delete the database file' migration policy; the 500 on a results page for a run saved before a field was added.

### S20 Job events and SSE framing

Remedy: jobs.py holds one job state table (JobStatus transitions) and _finish_job/_report_state refuse a transition the table does not allow, stamping finished_at only on terminal states; each event type has one typed payload and one web module frames SSE (sse_frame(event, payload), event_stream(frames)) used by both assistant.chat and api.get_job_progress; get_events returns without draining so the compensating terminal branch goes; the 600-second stream limit ends with a named 'timeout' event the browser treats as a reconnect, not an error.

Deletable: 10 hand-written frame sites and the two header copies; api.get_job_progress's compensating terminal branch; progress-tracker.js's `data.message || data.error`; the three error payload shapes; _finish_job's unconditional stamp and the save upsert writing 'completed' before the record.

### S21 Results chart panels, theme tokens and chart facts

Remedy: charts.py returns a ChartPanel value (figure JSON or a named absence reason) rendered through the existing chart_container macro (macros.html:78, already live on compare.html:118 and :129; p122's measurement corrected to 'unused on results/home.html and results/fleet.html'), extended to take the panel; chart inputs are a typed ChartSummary built from SummaryStatistics/FleetSummary, not dict.get over decoded JSON; sankey and radar flows read the grid-charge-aware fields instead of reconstructing them; theme colour tokens have one table emitted into tailwind.config.js and chart-renderer.js so tests/_css_classes.py's hand list shrinks; compare.html renders through chart-renderer.js; financial_breakdown's trace is titled for what it plots.

Deletable: 12 "!= '{}'" guards and the '{}'/None returns; the two direct Plotly.newPlot calls; 32 copies of the card class triple via the card macro; the Chart.js dead path in parameter-sweep.js and sweep_parameter_chart's optimal-by-max; overlaid_power_flows (0 callers); the amber restated in tailwind.config.js and the hard-coded hexes in chart-renderer.js and parameter-sweep.js; most of tests/_css_classes.py's 448-line list.

### S22 Assistant facts from the engine

Remedy: assistant.py derives its TDCV figures, benchmark bands and yield figure from load.OFGEM_TDCV_BY_OCCUPANTS and validation's band constants (one import, not three copies); TOOLS carries each tool's handler so dispatch_tool is a lookup; chat() is split into the stream loop, the tool round-trip and the persistence step, with one save site that refuses an empty assistant row.

Deletable: The three TDCV versions and the literal bands in the system prompt and metric tables; the six-name string if-chain in dispatch_tool; two of three save_chat_message sites.

### S23 Surface lock

Remedy: One surface-contract test module organised by behaviour (laziness, pvlib-free import, frozen forms, drift message) replaces test_init_lazy_surface.py and test_public_api_surface.py; the exported-name count derives from FROZEN_SURFACE rather than a literal; __init__'s three tables derive from one name-to-module mapping with the sync check over all pairs; surface_form gains the frozen/eq/order dimension and pins constants by their value's structure, _Unevaluated uses one quoting rule, _parsed drops the type-ignores by handling each typing form explicitly, _attributes_set_on_self walks only __init__/__post_init__, and the drift message classifies breaking vs additive and names the doc line to update.

Deletable: Three duplicated test bodies and the two literal 69 asserts plus four prose mentions; the T3/T4/H-number ownership prose; _external_probe.py's stale line pointer; the two type-ignores in _surface_forms; the first-pair-only sync check.

### S24 Lane harness: one typed collection source, one lane-only mechanism, gates over tests/

Remedy: tests/_collect_only.py obtains node ids and interpreter names from pytest's --junitxml report (the seam test_per_task_verify.py:84 already uses) instead of parsing '::' stdout; tests/e2e/conftest.py's existing pytest_collection_modifyitems hook adds pytest.mark.e2e to every test under its directory so conftest's offline exemption is the directory rule, not a hand-written pytestmark per module; 'lane-only' is stated once (collect_ignore) and the lane rows, interpreter_matrix and newest_releases read it; _orchestrator_config reads LaneCommand.cwd/enabled through one helper instead of re-implementing them; test_lint widens to tests/ after clearing the 59 F findings and the helper type check covers every tests/_*.py; the two hand-kept network lists go; dark-factory-orchestrator.yaml's timing prose moves to docs.

Deletable: collected_node_ids' '::' filter and _interpreters_named_by's rpartition; test_marker_registration's regex over collect output and its INTEGRATION_FILES/NETWORKED_UNIT_CLASSES/PURE_UNIT_CLASSES lists; 23 hand-written e2e pytestmarks; PYTEST_ADDOPTS=--ignore restatements; 29 name-defined type-ignores; 85 comment lines of the 134 in the orchestrator yaml.

### S25 Board reports: one typed row source and one assumption mode per report

Remedy: cli/finance.run resolves each --assumptions mode to its own FinanceConfig once and drives bill, projection, solve and events per mode from that value; generate_finance_report takes labelled sections keyed by mode instead of a positional bill_physics; events income renders with the economics it changes. Summary tables are typed per summary type (SummaryStatistics and FleetSummary each expose typed (label, value) rows; one helper for the five shared energy totals) so a renamed field fails mypy and fleet run shows its four missing rows. output.py's report builders use the _fmt_* helpers and _BINDING_LABELS table they sit beside, the four dead ratio functions go, and calculate_seasonal_metrics reads the engine's self-consumption series; home.calculate_summary carries one export-revenue figure. Docs name the commands that exist.

Deletable: create_summary_table's 8 hasattr/getattr probes and Any parameter; the 'Physics Assumptions' heading on spreadsheet figures; the if/elif binding chain and inline IRR/DSCR/payback formatting; calculate_self_consumption_ratio, calculate_grid_dependency_ratio, calculate_export_ratio, aggregate_annual (0 callers); the seg_revenue_gbp/total_export_revenue_gbp pair and its 20-line docstring; 'up to 3 fleet simulations' and the fleet run --cost-recovery doc lines.

### S26 Sweep knob registry

Remedy: One registry below the entry points maps a typed knob identifier to a pure ScenarioConfig -> ScenarioConfig transform, with value generation always through SweepSpec (one default mode); the YAML sweep's placement is data the registry knows, so a sweep multiplier on an unsupported field is refused at parse time naming the field path; web/api.simulate_sweep, cli fleet sweep's ${VAR} path, optimize's sensitivity axes and aliases resolve through it; sensitivity_panel takes the baseline RankedSweep and compares floors against its effective retained_cash_floor_gbp; cli/fleet.sweep's closures and the type-ignore go with the registry's typed values.

Deletable: detect_sweep_spec/_replace_sweep_with_value's battery.capacity_kwh special case and the sampler's late refusal as a user message; _SWEEP_PARAMETER_HOME_KEYS; cli/optimize's alias map (merged into the registry's one alias table); the four spellings of the battery-capacity knob; the duplicated baseline run_sweep and the floor-axis name special case; cli/fleet.sweep's 'YAML sweep: multiplier' labels and multiplier_*.csv naming.

### S27 Community: dispatch from the factory, mode derived from the battery

Remedy: CommunityConfig takes a dispatch strategy config and the community battery runs through the dispatch factory from the Dispatch stream with the tariff; sharing_mode becomes a property derived from community_battery (or each mode a frozen variant carrying its own fields); CommunityResults and FleetResults/FleetConfig are frozen with tuple fields; billing absence warns once naming the missing inputs; the α/γ/ε/task labels and line-number pointers leave the code.

Deletable: The hard-coded SelfConsumptionStrategy() and tariff-less simulate_timestep call; the three consistency ifs in CommunityConfig.__post_init__; community.py:366-368's post-construction mutation; the 'mirrors home.simulate_home:299-300' pointer and the Greek/task labels at 8 sites.

### S28 Battery facts: one representation each for efficiency and throughput

Remedy: BatteryConfig holds two efficiency facts in two fields; round-trip efficiency is a classmethod constructor (or __post_init__ refuses a set efficiency that contradicts per-direction values, naming both) and _parse_battery_config refuses a block setting both forms; compute_soh's throughput definition (discharged energy vs charged plus discharged) is stated once and finance's accrual matches it.

Deletable: The retained efficiency field and its 12-line override docstring with the replace() caveat; the efc = throughput / (2 * usable) ambiguity and finance.py's contradicting docstring.

### S29 Surface version bump and consumer recipe (D4)

Remedy: One coordinated bump of the frozen public surface: FROZEN_SURFACE/FROZEN_CLOSURE/FROZEN_MEMBERS updated once for every retired or renamed name the program introduced, docs/domain-library-consumption.md gains one Unreleased-on-main section and the tag convention, and the platform consumer re-pins once.

Deletable: Every transitional re-export or dual field a stream kept only until this bump.

## Seam ownership (G4 — authoritative)

| Seam/artifact | Owner stream | Consumers (do NOT redefine) |
|---|---|---|
| ConfigurationError (owner: errors.py; consumers config, finance, gridservices, web readers, cli/utils.handle_errors) | S1 | every other stream that reads it |
| DispatchStrategyConfig / GridChargeConfig (owner: dispatch.py; readers battery, flow, home, config, scenario_writer, web/storage, web/fleet_config) | S2 | every other stream that reads it |
| HomeConfig.dispatch_strategy and BatteryConfig fields are on the frozen public surface: version-bump route per the briefing | S2 | every other stream that reads it |
| Energy settlement rule (one function in flow.py read by both simulate_timestep variants and by validate_energy_balance) | S3 | every other stream that reads it |
| number_fields (owner: package leaf; readers config, web readers, domain configs) | S4 | every other stream that reads it |
| Refusal type raised by the checker (depends on the Errors stream's base-class choice) | S4 | every other stream that reads it |
| scenario_blocks.py as the home of battery.py's TYPE_CHECKING types until the Dispatch stream moves them (order the two streams: Dispatch first) | S5 | every other stream that reads it |
| Fleet-document overlay reader (owner: config; consumers cli/finance, cli/optimize, cli/home, cli/fleet, web/fleet_scenario, web/builder_form) | S6 | every other stream that reads it |
| ScenarioConfig.homes()/with_seg() (owner: config; consumers finance, optimize, cli/validate) | S6 | every other stream that reads it |
| Component block key tables shared by config's parsers and scenario_writer (one owner, read by both) | S7 | every other stream that reads it |
| Billing-energy records (owner: finance.py; readers projection module, tests) | S8 | every other stream that reads it |
| solar_challenge.__init__._SYMBOL_MODULE maps solve_cost_recovery_rate to 'finance' (frozen surface): re-export from finance or version bump | S8 | every other stream that reads it |
| Grid-services rate bands (owner: gridservices.py; readers flex, finance, cli/optimize) | S9 | every other stream that reads it |
| FinanceConfig.grid_services_model is on the frozen surface | S9 | every other stream that reads it |
| SimulationWindow (owner: timebase.py; readers home, finance, validation, output, charts, cli) | S10 | every other stream that reads it |
| Cheap-period classifier (owner: tariff.py; readers flow, dispatch, ev) | S11 | every other stream that reads it |
| Tariff preset defaults (owner: tariff.py; readers config.parse_tariff_config, web routes/forms, fleet_scenario._FORM_TARIFF_SETTINGS) | S11 | every other stream that reads it |
| Named load series on SimulationResults (owner: home.py; readers output, charts, templates, scenario_writer, web/storage) | S12 | every other stream that reads it |
| Day iterator over the tz-aware index (owner: timebase.py, shared with the Window stream) | S12 | every other stream that reads it |
| Global RNG state (owner: load.py's hand-off context; the briefing mandates seeding both numpy and random) | S13 | every other stream that reads it |
| Default PV module identity (owner: pv.py constant; restated in 6 docs/tests sites that should point at it) | S14 | every other stream that reads it |
| PVConfig fields on the frozen surface | S14 | every other stream that reads it |
| Weather cache value (owner: composition roots cli/web/tests; readers simulate_home via argument) | S15 | every other stream that reads it |
| set_weather_cache is on the frozen public surface | S15 | every other stream that reads it |
| FleetRunner (owner: fleet.py; built by cli/utils, web/app, tests/_cli_fleet_simulator) | S16 | every other stream that reads it |
| cli/utils module docstring's rule 'every fleet command reads its simulator from ctx' becomes true or is narrowed | S16 | every other stream that reads it |
| Location grammar and presets (owner: location.py; readers cli/utils, web readers, templates) | S17 | every other stream that reads it |
| Refusal type (owner: errors.py) | S17 | every other stream that reads it |
| Presence rule (owner: the request-reading module; readers simulation_params, fleet_scenario, builder_form) | S17 | every other stream that reads it |
| PageLimits (owner: fleet_components.py; readers routes, templates, static/js, builder_form, simulation_params) | S18 | every other stream that reads it |
| Per-type distribution table (owner: config's grammar / fleet_distribution module; readers web editor and preview) | S18 | every other stream that reads it |
| Connection policy (owner: database.connect) | S19 | every other stream that reads it |
| Stored-run format version and runs schema version (owner: storage/database; readers every loader) | S19 | every other stream that reads it |
| Run type -> behaviour table (owner: storage.RunRecord; readers api, routes, templates, assistant) | S19 | every other stream that reads it |
| SSE frame and event payload types (owner: one web module; readers assistant.js, progress-tracker.js, parameter-sweep.js) | S20 | every other stream that reads it |
| Theme tokens (owner: one table; readers tailwind.config.js, chart-renderer.js, charts.py _AMBER) | S21 | every other stream that reads it |
| ChartPanel rendered by chart_container (owner: macros.html) | S21 | every other stream that reads it |
| Benchmark constants (owner: load.py and validation.py; reader assistant.py) | S22 | every other stream that reads it |
| FROZEN_SURFACE as the one home of the surface (owner: tests/_surface_forms.py; readers the merged test module, release notes) | S23 | every other stream that reads it |
| Lane-only suite list (owner: tests/conftest.py collect_ignore; readers lane rows, interpreter_matrix, newest_releases) | S24 | every other stream that reads it |
| Collection report (owner: tests/_collect_only via JUnit XML) | S24 | every other stream that reads it |
| Report sections keyed by assumption mode (owner: output.generate_finance_report; reader cli/finance) | S25 | every other stream that reads it |
| Typed summary rows (owner: home.SummaryStatistics / fleet.FleetSummary; reader cli/utils) | S25 | every other stream that reads it |
| Knob registry (owner: the fleet_distribution/config stratum; readers web/api, cli/fleet, cli/optimize, optimize) | S26 | every other stream that reads it |
| Dispatch factory (owner: dispatch.py, from the Dispatch stream; this stream follows it) | S27 | every other stream that reads it |
| BatteryConfig fields on the frozen surface (version-bump route) | S28 | every other stream that reads it |
| FROZEN_SURFACE (owner: S23 until this stream closes) | S29 | every other stream that reads it |
| review/briefing.yaml member lists (D1) | /review-briefing, run by the lead before wave 1 | every instrument |
| config.py partition layout (errors leaf, number_fields leaf, scenario_blocks, fleet_distribution, config) | S5 | S4, S6, S18, S26 import the partitioned modules by their final names |
| SimulationWindow (days, cadence, annualisation_scale, extrapolated) | S10 | S12, S25, finance, validation, output, charts |
| Weather provider | S15 | S16 and every composition root |

## Invariants

This project has no invariants registry; a promoted invariant is a test in its owning stream, in the checkable form below, plus one `review/briefing.yaml` conventions line pointing at the test (D27).

1. **Every numeric field of a frozen domain config is finite and not a bool, and a violation names the field and value.** — owner S4; checkable: For every dataclass in solar_challenge whose fields include float or int, constructing with NaN, inf, -inf and True in each numeric field raises, and the message contains the field name and the repr of the value; no construction succeeds.; fixture: Parametrize over (dataclass, field) pairs discovered by walking dataclasses.fields of PVConfig, BatteryConfig, LoadConfig, HeatPumpConfig, EVConfig, Location, SEGTariff, TariffPeriod, GridChargeConfig, DispatchStrategyConfig, EventWindow, FlexibilityValueBand, FinanceConfig; build a valid instance from a fixture, dataclasses.replace one field with each bad value, assert raises and message content.
2. **A TariffConfig's periods tile the 24-hour day exactly once.** — owner S11; checkable: TariffConfig((TariffPeriod('07:00','23:00',0.3),)) raises naming the gap 23:00-07:00; TariffConfig with 00:00-12:00 and 06:00-00:00 raises naming the overlap 06:00-12:00; every preset constructs; get_rate over 1440 minutes of a constructed tariff never raises.; fixture: The two probed tariffs from f14 plus the three presets; a 1-minute sweep over 2024-01-10 Europe/London.
3. **A stochastic load profile depends only on its LoadConfig, not on process order or concurrency.** — owner S13; checkable: generate_load_profile(LoadConfig(seed=s)) run serially equals the same call run on two threads concurrently for s in {42, 43}; an unseeded profile generated after a seeded one differs from a second fresh unseeded profile; FleetConfig.create_heterogeneous gives every home a distinct LoadConfig.seed equal to fleet_seed + index.; fixture: f51's probe harness: 2024-06-01..07 window, ThreadPoolExecutor(2), five trials, Series.equals; plus a fleet of three homes asserting seeds.
4. **The runs table and stored-run files are written and read only through RunStorage.** — owner S19; checkable: grep over src/solar_challenge/web for 'sqlite3.connect', 'FROM runs', 'INSERT INTO runs', 'UPDATE runs' and 'RunStorage(' finds matches only in storage.py and database.py (connect) and app.py (one construction).; fixture: A test that walks the web package's .py files with a regex and asserts the allowed set of files; runs under the per-task verify.
5. **No solar_challenge module imports another solar_challenge module inside a function.** — owner S1; checkable: An AST scan of src/solar_challenge finds zero Import/ImportFrom nodes nested in a FunctionDef whose module starts with solar_challenge, except an allow-list that is empty after the Errors, Finance, Grid-services and Load composition streams land.; fixture: Reuse the import_graph.json producer's deferred-edge logic as a test; the allow-list is a frozenset in the test that shrinks per stream. (S1 PRD §7 correction: the allow-list in tests/unit/test_import_structure.py is not empty after S1; its Transitional entries empty once S8, S9, S12 and tasks 153 and 454 land, and each Permanent entry cites a contract)
6. **A stored run names the format version that wrote it, and a loader refuses a run it cannot rebuild, naming the run id and the field.** — owner S19; checkable: Loading a fixture run directory saved without a version, or with a summary.json missing total_generation_kwh, raises StoredRunUnreadable whose message contains the run id and the field name; loading a current-format fixture succeeds; _deserialize_dataclass with an unknown key raises the same type.; fixture: A frozen pre-task-469 run directory committed under tests/fixtures/stored_runs/ plus a current one generated by save_home_run in the test. (S19 text amendments apply)
7. **The database schema version matches the code and the runs DDL matches RunRecord.** — owner S19; checkable: After init_db on a fresh file, PRAGMA user_version equals database.SCHEMA_VERSION and the column names of PRAGMA table_info(runs) equal [f.name for f in fields(RunRecord)]; init_db on a file whose user_version is lower either migrates to SCHEMA_VERSION or raises naming both versions and the path.; fixture: A temp database created with the pre-548 DDL (f19's probe) and one created fresh. (S19 text amendments apply)
8. **The day count a bill is computed over is the summaries' own.** — owner S10; checkable: bill_distribution(summaries, finance, days) raises naming both values when days != summaries[0].simulation_days; cli finance run over 2024-03-31..04-01 bills over 2 days (the index's count), not 1.; fixture: f32's probe summaries with simulation_days 2 and a call with days 1; a CliRunner invocation over the DST-crossing window with a fake simulator.
9. **A grid-charge target is a fraction of the battery's effective capacity.** — owner S2; checkable: After 180 one-minute cheap-period steps of simulate_timestep_tou on Battery(BatteryConfig(10 kWh, soh=0.7, grid_charging=GridChargeConfig(0.5))) with Economy 7, the end SOC fraction of effective capacity equals 0.5 within 1e-6 (today 0.714).; fixture: f52's probe verbatim, parametrized over soh in {1.0, 0.7}.
10. **A BatteryConfig.grid_charging set under a dispatcher that cannot honour it is refused (or warned) by name. CONDITIONAL on the Dispatch stream's first open choice; if the briefing's accept-and-ignore is kept, the invariant is instead 'the run emits one warning naming grid_charging and the strategy'.** — owner S2; checkable: For each of the three ignored combinations f44 measured (default greedy, battery self_consumption, home tou_optimized without tariff), constructing or simulating raises ConfigurationError naming 'grid_charging' and the strategy, or emits exactly one warning with both names; the two honoured combinations produce total_grid_charge_kwh > 0.; fixture: probes/grid_charge.py from the cross-dimensions seat: PV 4 kW, deterministic 3400 kWh load, 5 kWh battery with GridChargeConfig(0.9), 2024-06-15 synthetic June weather, warnings captured with simplefilter('always').
11. **Dashboard form defaults for tariff rates and the simulation window are the engine's.** — owner S18; checkable: Rendering simulate/home.html and simulate/fleet.html and parsing their x-data yields economy_7 and economy_10 peak/off-peak rates equal to TariffConfig's preset table, and start/end defaults equal to the library's default window constants; cli option defaults for --start/--end import the same constants.; fixture: Flask test client GET of both pages, a small regex over the x-data block, compared with tariff.PRESET_DEFAULTS and timebase/config window constants; a grep test that no '2024-01-01'/'2024-12-31'/'2024-06-01' literal remains in src outside the one home. (compares with tariff.PRESET_RATES, per S11)

## Resolved decisions (do not relitigate)

### D1. path-to-area member rule — ruled_by: human

Option B: each cli/<cmd>.py follows the domain it drives (cli/finance.py, cli/optimize.py -> finance-economics; cli/web.py -> web-dashboard; other cli modules and the package __init__ -> simulation-core); tariff.py and seg.py -> finance-economics. /review-briefing writes it as member lists; the 14 review-solar_challenge-20261013 priors keyed under repo are re-keyed with supersedes links at the next run.

Options considered: A: all cli to repo (keeps the review priors' keys); B (keeps this run's and the hotspot survey's keys).

Consequence that decided it: a CLI command's cost lands with the owner of the behaviour it drives.

Keys: fk-6a52ed98b18e fk-be5b13274bcb fk-606a9211b34d fk-2106d1fbaed0 fk-f99038047a27 fk-b69968a37b36 fk-f3a20a6d53e0 fk-b7241e0ce122 fk-8376e0ab00db fk-cc292d7ce407 fk-2264bc150fa3

### D2. ConfigurationError base class (S1) — ruled_by: human

ConfigurationError moves to an errors leaf and subclasses ValueError; the web boundary translator logs a non-domain ValueError separately so a bug is not silently a 400 (INV-11).

Options considered: subclass ValueError; plain Exception with one translator per boundary.

Consequence that decided it: one refusal type at both boundaries; no per-route except tuples.

Keys: fk-601c5b5f6415 fk-4435376bedb3 fk-da69830bb2d6 fk-291910b552af fk-6c98ee030531

### D3. grid_charging under a dispatcher that ignores it (S2, S27, invariant 10) — ruled_by: human

Refuse at construction with a ConfigurationError naming grid_charging and the strategy (reverses the briefing's accept-and-ignore decision; briefing edit and contract bump). Mid-term direction: every dispatcher, the strategy family and the community battery included, must support grid charging, so the refusal is transitional.

Options considered: refuse at construction; warn once; keep and record.

Consequence that decided it: the silent 0 kWh grid charge cannot recur; invariant candidate 10 is a refusal; the dispatch stream carries the mid-term goal.

Keys: fk-fc652220a4d3 fk-664e2030921e

### D4. frozen public surface posture — ruled_by: human

One coordinated surface version bump for the whole program, sequenced by the program doc with one consumer-recipe update; streams take their clean option. Derived: S8 _SYMBOL_MODULE points at the new projection module; S12 the three Optional heat-pump summary fields are replaced by the named-load mapping; S15 weather is passed explicitly first and set_weather_cache retired at the bump; S28 BatteryConfig keeps two efficiency fields plus a with_round_trip constructor.

Options considered: one coordinated bump; no bumps (shims); bump per stream.

Consequence that decided it: no re-export shims or dual fields survive the program; one re-pin for the platform consumer.

Keys: fk-9df95e9e2b45 fk-f5cd69400ce6 fk-35b8ddcf5565 fk-44fdf5fb356b fk-06035cd76226 fk-781d153ab978

### D5. dispatch strategy vocabulary (S2) — ruled_by: human

One tagged union of strategy configs on BatteryConfig; HomeConfig.dispatch_strategy retired under the program's bump.

Options considered: StrEnum with both fields kept; tagged union.

Consequence that decided it: one field, one home, one precedence; adding a strategy is one variant plus one factory branch.

Keys: fk-94f4881bbe48 fk-04b52ee632c6 fk-b3dfd41a4d6a fk-c36d6fcbc2a8

### D6. two dispatch paths (S3) — ruled_by: human

simulate_timestep_tou is retired into a TOU strategy object run through simulate_timestep, with one settle function and one grid-charge gate; the byte-identical tail goes. Reverses the briefing's 'two dispatch paths coexist' decision; rides the bump.

Options considered: keep both entry points with a shared tail; retire the inline path.

Consequence that decided it: one dispatch mechanism for the axis; the inline path cannot drift again; the mid-term grid-charging support (D3) lands in one family.

Keys: fk-4df47ebe6a96 fk-491014934d1e fk-7440003fdd59 fk-2a53ae89932e fk-f622bbaa9f2e

### D7. peak/cheap classifier (S11) — ruled_by: human

The tariff is the authority: TariffConfig exposes the cheap-period classifier and the tiling invariant; peak_hours is a checked override refused when it contradicts the tariff; EV windows and the web presets read the tariff.

Options considered: tariff authority with checked override; peak_hours independent behavioural window.

Consequence that decided it: one definition of peak; seasonal or Agile-style tariffs are one edit; contradicting scenario YAML starts failing.

Keys: fk-4872e7ab367e fk-bd03fe349ffd fk-2f88003e22c8 fk-872021ade9b6 fk-463e82417506

### D8. simulation cadence (S10) — ruled_by: human

The cadence is a run-owned parameter derived from the index and carried by the typed SimulationWindow, threaded to every integration site; the ten timestep parameters become reads of it, not deletions. (Against the lead's recommendation of a one-minute invariant.)

Options considered: invariant in timebase; run-owned parameter.

Consequence that decided it: variable cadence works end to end; each new integration site must read the window.

Keys: fk-7ef1099d24e8

### D9. finite-number checker's error (S4) — ruled_by: human

The shared checker raises ConfigurationError (from the errors leaf, a ValueError subclass) from every domain __post_init__; config's readers add the key path on the way up.

Options considered: ValueError in domain wrapped by config; ConfigurationError everywhere.

Consequence that decided it: one type reaches both boundaries.

Keys: fk-a9c609ecb8ef fk-649851e5fc38 fk-b69968a37b36 fk-606a9211b34d fk-7dcdc5559d22

### D10. SEG-to-home policy (S6) — ruled_by: human

Fill-and-refuse: a scenario's SEG fills homes lacking a seg_tariff and a contradicting per-home rate is refused by name; the CLI's and optimize's overwrite paths become refusals.

Options considered: fill-and-refuse; overwrite.

Consequence that decided it: one policy with a loud failure; a per-home SEG an agent sets is never silently ignored.

Keys: fk-81d0840d19e2 fk-a391cf1f4edf fk-50cf1dd5df58 fk-f99038047a27

### D11. period policy across commands (S6) — ruled_by: human

Flag > file period block > default, for every command (finance run, optimize, fleet run); finance run's windows change for files carrying a period block.

Options considered: flag > file > default; flags only, period refused in fleet documents.

Consequence that decided it: one period policy for one file across commands.

Keys: fk-be5b13274bcb fk-f99038047a27 fk-2264bc150fa3

### D12. annualisation rule (S10) — ruled_by: human

One rule: scale = covered year length / window days, always (365 or 366 by the covered period's calendar year; 365.25 across years), computed once by the typed SimulationWindow and used by finance, validation and the annual aggregate; any board output whose window is not a whole number of calendar years carries an explicit extrapolated marking (replacing finance's short-period warning); charts' 90/180-day gates stay as display gates. Finance's 360-day threshold rule is retired. householder_bill's 'annual' parameter is renamed to the window quantity and cli/finance's tz-aware day count is replaced by the window's count in the same stream.

Options considered: pure rate with calendar year length; finance's 360-day threshold; whole-year-only board figures.

Consequence that decided it: a 400-day or two-year run is no longer billed as one year; the board sees when a figure is extrapolated; one threshold-free rule.

Keys: fk-d63c41ca13f9 fk-286fe17c28c9 fk-1cd332300623 fk-756c0ef9e9d9

### D13. capacity-at-events income per age (S9) — ruled_by: human

Computed per projection age from that age's aged homes; the age-0 closure memo and finance.py's function-local gridservices import go; compute-once tests become per-age tests; FinanceConfig.grid_services_model becomes a closed selector type.

Options considered: per age; age-0 as explicit input.

Consequence that decided it: the model says what it means; later-year income falls with SOH; more simulations per projection.

Keys: fk-758b2f309cab fk-4ddab794283a fk-aafe32daa988 fk-d432a549b03f fk-0f24b7f66eb2 fk-71b4ca35efe0

### D14. PVConfig.module_efficiency and temperature_coefficient (S14) — ruled_by: human

Both become live model inputs: when set they derive the module parameters STC-consistently, the CEC row being a template as the inverter already is; the gamma_pdc sentinel goes.

Options considered: make live; remove under the bump.

Consequence that decided it: the fields do what their names say; yields change for scenarios that set them.

Keys: fk-f5cd69400ce6 fk-0edf0069c6bb fk-48447960eb2c fk-a98db49f3fd7

### D15. weather input to simulate_home (S15) — ruled_by: human

A cache-backed weather provider object with get(location), picklable for the process pool, is passed down; the module-global cache and set_weather_cache are retired at the bump.

Options considered: required weather_data frame; provider object.

Consequence that decided it: one prefetch policy; a second parallel path cannot miss the cache (task-460 class).

Keys: fk-06035cd76226 fk-44fdf5fb356b fk-e4549a3a6b54

### D16. fleet runner and weather prefetch (S16) — ruled_by: human

The frozen FleetRunner owns weather prefetch per location through the provider of D15; D15 and D16 are one mechanism.

Options considered: runner owns prefetch; weather passed per call.

Consequence that decided it: one prefetch policy in one place.

Keys: fk-7e76b4cf2cb2 fk-f7b19fc4c8b5 fk-f3a20a6d53e0 fk-e58042aef503

### D17. unknown location at the web boundary (S17) — ruled_by: human

Refused with a 400 naming the value; location.py owns the presets and one strict 'preset or lat,lon[,alt]' grammar shared by the CLI and the web; resolve_location's silent Bristol fallback goes.

Options considered: refuse; keep the fallback, return the resolved location.

Consequence that decided it: a mistyped preset can no longer pass every test; one grammar.

Keys: fk-0593b530a371 fk-acdc650baeb8 fk-66f886576b3f fk-1d143fefefed

### D18. distribution editor per-type table (S18) — ruled_by: human

config's grammar module (fleet_distribution.py after the S5 partition) owns the per-type table; the web editor, preview and serialisers derive from it.

Options considered: config owns it; fleet_components owns a web table with a guard test.

Consequence that decided it: grammar and editor cannot drift; adding a distribution type is one record.

Keys: fk-a6d9f3e5a7e2 fk-8107696f0b02 fk-7893b49b92c3 fk-88374e6e3553 fk-d303b6dbf669 fk-006c3339e3b2

### D19. database schema migrations (S19) — ruled_by: human

init_db writes PRAGMA user_version; on a mismatch the app refuses to start naming both versions and the file; `solar-challenge web migrate` applies the ordered migrations explicitly.

Options considered: refuse + explicit migrate; in-place on startup.

Consequence that decided it: no silent change to a user's data; startup stays simple.

Keys: fk-1070454e4c6e fk-273b8b09c91a fk-cca5fd81afda

### D20. results routes (S19) — ruled_by: human

One /results/<run_id> route choosing the page from the record's run type, with redirects from /results/home and /results/fleet; the run-type-to-behaviour table lives on storage.RunRecord.

Options considered: one route; keep both, derive links.

Consequence that decided it: a new run kind adds a loader and a template only.

Keys: fk-81e62b2640a7 fk-34a6679f1ef3 fk-2ac79d7a1989

### D21. SSE error event (S20) — ruled_by: human

The server's failure event is renamed 'failed' with id and retry fields; one SSE framing module serves assistant.chat and api.get_job_progress; the 600-second stream limit ends with a named 'timeout' event the browser treats as a reconnect.

Options considered: rename to failed; keep error, unify payload.

Consequence that decided it: no collision with EventSource's native error event; reconnects resume.

Keys: fk-7eb56fda0b1c fk-484952247bb6 fk-0097b5aaa45c fk-066e5cb461f7 fk-4540d657bff6

### D22. theme token table (S21) — ruled_by: human

A JSON token file under static/src is read by tailwind.config.js and loaded by charts.py; the css-build lane job guards the Tailwind side.

Options considered: JSON under static/src; Python constants emitted to a generated tokens.js.

Consequence that decided it: a colour change is one edit and one rebuild; no new build step.

Keys: fk-93ee9a05751a fk-42c0053b9a2b fk-ff5b90768f66 fk-8f26d000b68d

### D23. declared dependency floors (S24) — ruled_by: human

Each floor in pyproject.toml is raised to the locked version and the capability-claim tests are deleted; the floor is the lock, re-raised on every re-lock. No oldest-floor lane job.

Options considered: raise floors to the lock; oldest-floor lane job.

Consequence that decided it: a floor claim cannot drift silently; the one consumer pins a tag so the range buys nothing today.

Keys: fk-e5820c5e22ed

### D24. board report under --assumptions both (S25) — ruled_by: human

Every computation (bills, solve, economics, events income) is rendered under both assumption modes, each labelled; generate_finance_report takes sections keyed by mode.

Options considered: both modes for every computation; physics-only solve/economics, labelled.

Consequence that decided it: the spreadsheet comparison is complete; no mixed-mode section.

Keys: fk-b7241e0ce122 fk-89afcb2b57f7 fk-f66948b9528c fk-2106d1fbaed0 fk-6a52ed98b18e

### D25. sweep knob registry signature (S26) — ruled_by: human

The registry maps a typed knob to a ScenarioConfig -> ScenarioConfig transform only, using ScenarioConfig.homes() from S6; the web's single-home sweep wraps the home in a scenario.

Options considered: ScenarioConfig only; two signatures per knob.

Consequence that decided it: one transform signature; every knob is scenario-shaped.

Keys: fk-4cc34de4e649 fk-ac39320dcf1d fk-bea05911eb70 fk-32d5e6707fb5 fk-3ca00f8edeb8 fk-0b4f5e04067c

### D26. uncontested block and loose findings — ruled_by: human

Streams S5, S7, S13, S22, S23 and S27 are accepted as the synthesis wrote them. The five structural findings no stream claimed are assigned: fk-6a52ed98b18e -> S25, fk-be5b13274bcb -> S6, fk-3ccbba41d836 -> S14, fk-f2f8a5512feb -> S4, fk-606a9211b34d -> S4.

Options considered: accept the block; hold S5; reject.

Consequence that decided it: every structural finding has an owning stream.

Keys: fk-6a52ed98b18e fk-be5b13274bcb fk-3ccbba41d836 fk-f2f8a5512feb fk-606a9211b34d

### D27. invariant candidates — ruled_by: human

All eleven candidates are promoted: each becomes a test in its owning stream in the checkable form the synthesis wrote (candidate 10 as a refusal per D3), plus one review/briefing.yaml conventions line pointing at the test. This project has no invariants registry; the briefing conventions and the tests are its two sites.

Options considered: all eleven; 1-5 only; defer to /prd.

Consequence that decided it: every promoted rule has a fixture before a stream lands.

Keys: (cross-cutting)

### D28. weakened findings ranked in a top-3 cell — ruled_by: human

The twelve stay in their streams at weakened weight; each /prd session re-measures them before decomposing.

Options considered: keep at weakened weight; drop and leave open.

Consequence that decided it: the skeptics' notes (mostly overstated counts) are carried to the session that acts.

Keys: fk-b3dfd41a4d6a fk-72af0b90338d fk-9cc706d3afdd fk-4cc34de4e649 fk-d63c41ca13f9 fk-b0f648b0e6d0 fk-5b34adae950b fk-41283f42a36a fk-021a21b35427 fk-8376e0ab00db fk-cc292d7ce407 fk-a0b751097301

### D29. surface sequencing under D4 (S2 Q1, S10 Q3) — ruled_by: human

Additive frozen-table edits land in-leaf with their FROZEN_* entry and an 'Unreleased on main' line (main's precedent, tasks 326 and 469); only renames and retirements are held leaves released by S29, which writes the one release section and consumer-recipe update.

Options considered: additive in-leaf, retirements held; every frozen-table touch waits for S29.

Consequence that decided it: S3, S5, S27, S12 and S25 are not stalled behind wave 4.

Keys: (cross-cutting)

### D30. standing charge over the covered year's days (S10 decision 6) — ruled_by: human

A bill's standing charge covers window.year_days (366 in a leap year), the same year its energy is scaled to.

Options considered: year_days; 365 fixed.

Consequence that decided it: energy and standing charge cover one year; default 2024 board outlays move by one day's standing charge.

Keys: fk-d63c41ca13f9 fk-1cd332300623

### D31. simulation_days parameter of householder_bill and bill_distribution (S10 Q6) — ruled_by: human

Dropped at the S29 bump; until then refused on mismatch with the summaries' own window.

Options considered: drop at the bump; keep the signatures.

Consequence that decided it: the parameter that only ever disagreed with the summaries goes.

Keys: fk-1cd332300623 fk-286fe17c28c9

### D32. PV model inputs (S14, ruled in the S14 /prd session, 2026-10-15) — ruled_by: human

An unset PVConfig.module_efficiency or temperature_coefficient means the template CEC module's own value: both fields become Optional with default None (an additive widening that lands in-leaf under D29). Every run switches its cell-temperature model from SAPM open_rack_glass_glass to pvlib's noct_sam using the module's own T_NOCT and efficiency; the Bristol 4 kW default yield moves from 993.1 to 1012.1 kWh/kWp (+1.9%).

Options considered: keep the sentinel defaults; Optional fields meaning the template's own value; NOCT-SAM.

Consequence that decided it: the fields do what they say; one cell-temperature model.

Keys: fk-f5cd69400ce6 fk-0edf0069c6bb

### D33. run store (S19, ruled in the S19 /prd session, 2026-10-14) — ruled_by: human

The 'sweep' run type and sweep_id are dropped (a sweep is its points' runs); deleting a run whose job is queued or running wins and cancels the job at the runner's checkpoints, never inside core simulate_home.

Options considered: keep sweep type; drop it; deletion cancels the job.

Consequence that decided it: two run kinds with one loader table; no orphaned running job after a delete.

Keys: fk-2ac79d7a1989 fk-8f4f4d63f917 fk-81e62b2640a7

## Lead rulings on PRD open questions

- L1 (S1; non-numeric input refusals (S1 lead Q1)): S4 converts the non-numeric ValueError refusals of the input types in the same edits as the numeric ones; invariant 1's test asserts the type; S17 depends on S4.
- L2 (S1; key path as data (Q2)): S1 ships the bare type; a later leaf of S4 or S5 extends errors.py if a reader needs the path as data, depending on S1-α.
- L3 (S1; ConfigurationError in __all__ (Q3)): Added to the surface in S29's release section.
- L4 (S1; task 177 (Q4)): Cancelled as superseded (metadata.x_superseded_by the S1-α leaf) when S1 files, after contract §8 step 1.
- L5 (S1; wave-1 streams that add refusals (Q5)): S2, S9, S11 and S28 depend on S1-β and raise errors.ConfigurationError; program deps updated.
- L6 (S2; D6/D7 meeting point (Q2)): S11 owns the optional peak_hours override and the factory's tariff-clock arm; S3 owns routing the home-level key and deleting use_tariff_tou.
- L7 (S2; S2 depends on S1 (Q3); δ in or out (Q4); absorbed tasks (Q5); flat tariff + grid charging (Q7); both levels set (Q8)): All defaults accepted: α depends on S1-β; δ stays as its own leaf; tasks 209, 568 and 632 are cancelled with x_superseded_by at decompose after §8 step 1; S11 adds the 'has a cheap period' fact and refusal arm; battery-level precedence stands until ε removes the home key.
- L8 (S2; D3 mid-term (Q6)): No leaf now; the lead files a design follow-up for grid charging in every dispatcher after S3 and S11 land (program §Triage).
- L9 (S10; aggregate_annual (Q1); S8 ordering (Q5); cadence option (Q4)): aggregate_annual is deleted in S10 γ2 (0 callers) and dropped from S25's deletable list, D12's 'annual aggregate' reads as that deletion; S8's move leaf depends on S10 ε; no user-settable cadence option now.
- L10 (S9; ε held (Q1); S26 cross-reference (Q3); owner of the four age-0 simulations (Q4, ruled by Leo)): ε stays a held leaf for S29; the band-valued events knob is a cross-reference line on S26, not an S9 leaf; S16 (the fleet runner) owns the four age-0 simulations the per-age income needs. Q2 (the board scenario's £0 events income) is under a separate fable /team investigation whose result file carries the resolution; S9's leaves do not wait for it.
- L11 (S11; solar half of fk-bd03fe349ffd (Q2); off_peak EV without a tariff (Q3); web TOU default window (Q4); flat-tariff degenerates (Q5)): Defaults accepted: the solar half goes to S12 and 'the 10:00-16:00 literal' leaves S11's deletable list; off_peak EV without a tariff is refused at construction (D7); both web forms default the TOU window to 16-19; tou_optimized without grid charging and an off_peak EV on a tariff with no cheap minute run as their cost-equal degenerate. Q1 (reference rates) is Leo's, see D34.
- L12 (S14; D29 reading of the Optional widening (Q2); L5 (Q3); exports (Q4); NOCT mounting field (Q5); capex basis (Q6); task 284 (Q7)): The Optional widening is additive and lands in-leaf; ζ raises ValueError like PVConfig's existing refusals and S4 converts them (L5 does not extend to S14); run_model_chain and DEFAULT_CEC_MODULE are not exported now; a mounting field for NOCT-SAM is recorded in §Triage as a follow-up candidate after ε, not filed; the capex basis (nameplate vs wired DC, fk-8b8f9d686b86) is routed to S8 by cross-reference; task 284 keeps running and is folded into β only if it stalls. Q1 (task 195) is Leo's, see D35.
- L13 (S15; get_tmy_data at the bump (Q1); cache-dir environment variable (Q2)): get_tmy_data is retired at the S29 bump in the held ε leaf (one public way to obtain weather); SOLAR_CHALLENGE_WEATHER_CACHE_DIR is confirmed as the one user-facing variable, read by WeatherCache() alone.
- L14 (S19; pre-existing tasks 468, 547, 355, 614; S10 η vs contract C10): 547, 355 and 614 are cancelled with x_superseded_by at S19's decompose after the step-1 lookup; 468 is Leo's (D36). S10's held leaf 784 (SummaryStatistics.window required) gains a dependency on S19's stored-run migration leaf (contract C10), so no pre-existing run becomes unreadable; the S19 decompose session returns that leaf id and the lead adds the edge.
- L15 (S2 decompose; cross-reference lines returned): S3's anchors drifted after task 710 (re-read before decomposing); the S11 tariff-clock arm leaf and S3's routing leaf each add_dependency on 790 (S2 ε); where the S2 PRD §10 says 'add no line', the leaves follow D29 instead.

## Cross-reference lines applied by the lead

- S3 (from S2 decompose): anchors drifted after task 710; the routing leaf add_dependency on 790 (S2 ε) and on S11 β (tariff-clock arm); a tariff-clocked TOUOptimizedStrategy reproduces simulate_timestep_tou on bristol-arbitrage.yaml, so retiring the inline path is a routing change.
- S11 (from S2 decompose): the tariff-clock arm leaf add_dependency on 790; S11 β makes TOUOptimizedStrategyConfig.peak_hours optional and adds the flat-tariff grid-charging refusal; S11 δ adds ev.require_tariff_for_smart_charging to the HomeConfig.__post_init__ S2 β creates; the decompose adds edge 230 -> S11 α.
- S12 (from S11): owns solar-mode EV charging following the home PV series, taking the solar half of fk-bd03fe349ffd; the EV contribution keeps receiving the home tariff.
- S18 (from S11): invariant 11 compares the forms with tariff.PRESET_RATES; S11 γ test_web_tariff_presets.py is its tariff half, S18 adds the window half; the fleet form dispatch vocabulary includes a tariff-clocked tou_optimized.
- S19 (from S11, S10): a stored run whose tariff does not tile no longer loads after S11 α; the stored-run format covers TOUOptimizedStrategyConfig(peak_hours=None) and summary.window; S10 leaf 784 depends on the S19 migration leaf (L14).
- S29 (from S11, S9, S14, S15): release section includes S11 §5.8 (mean_period_rate retired, held ε), S9 §5.8 (ε held), S14 η, S15 ε (set_weather_cache and get_tmy_data retired), ConfigurationError in __all__.
- S1 (from S9): the cli.finance -> gridservices allow-list entry is S9 β; finance -> gridservices is S9 α; each deletes its entry if 775 has landed.
- S8 (from S9, S14, S1): the project_multi_year move leaf depends on S9 α and β and on 773; it decides the finance capex basis, nameplate vs wired DC (fk-8b8f9d686b86, S14 Q6).
- S10 (from S9): the grid-services term is annual by construction; SimulationWindow scale multiplies energy and SEG, never it.
- S25 (from S9): the cli/finance.run restructure depends on S9 β and γ; per-mode rendering of events income stays S25.
- S26 (from S9): the grid-services knob means a flat rate, refused under the events model; a band-valued events knob is a new registry entry.
- S16 (from S9, S15): owns the four age-0 simulations the per-age events income needs (L10) and prefetch through the S15 provider; depends on S15 β.
- S4 (from S11, S14, S1): TariffPeriod.rate_per_kwh finiteness and PVConfig ζ refusals are converted to the shared checker; S4 depends on 774.
- S17 (from S1): depends on 774 and S4; the web rewraps and FLEET_FORM_REFUSALS belong to S17, not S1 deletable.
- S5, S8 (from S1): depend on 773; S8, S9, S12 delete their allow-list entry in tests/unit/test_import_structure.py (775) in the same change that removes the function-local import.
- Tasks 355 (S19), 423 (S4/S5), 509 (S17/S5) assume ConfigurationError is not a ValueError, which stops being true at 774; tasks 704 and 738 touch files 773/774 edit (textual merges only).
- S3: deletes home.simulate_home's use_tariff_tou predicate and _runs_tariff_tou (moved from S2's deletable list); builds on S2's GridChargeContext.target_soc_kwh and Battery answers; depends on S2 α and γ.
- S11: makes dispatch.TOUOptimizedStrategyConfig.peak_hours an optional override (None = the tariff's cheap periods) with D7's contradiction check and adds that arm to dispatch.build_dispatch_strategy, plus the flat-tariff grid-charging refusal arm; depends on S2 α; S2 ε depends on this leaf.
- S27: calls dispatch.build_dispatch_strategy(community_battery.dispatch_strategy or SelfConsumptionStrategyConfig(), grid_charging=..., tariff=billing.tariff) from CommunityConfig.__post_init__ and simulate_community; depends on S2 α and β.
- S5: moves parse_dispatch_strategy_config and _parse_grid_charge_config into scenario_blocks.py; they construct dispatch types and define none.
- S4: invariant 1's fixture walks dispatch.GridChargeConfig, SelfConsumptionStrategyConfig, TOUOptimizedStrategyConfig, PeakShavingStrategyConfig (not config.DispatchStrategyConfig); converts the non-numeric refusals too (L1).
- S19: _deserialize_value's tagged-union rule (S2 §5.6) and the storage codec for date/timedelta (S10 β) are part of the stored-run format; the format version covers S2 α's shape change, ε's removed home key and S10's summary.window.
- S18: the fleet form's dispatch vocabulary renders from dispatch.STRATEGY_CONFIG_BY_TYPE.
- S29: release section and consumer recipe include S2 §5.8, S10 η (required window fields, derived simulation_days, parameter rename, defaults dropped, per_step_amounts, D31) and ConfigurationError in __all__ (L3); S2 ε and S10 η are held leaves released in the bump window.
- S12: calendar-day iterator in timebase.py and generators built from SimulationWindow; depends on S10.
- S25: the extrapolated notice and annualised_from come from S10; aggregate_annual leaves S25's deletable list (deleted by S10 γ2).
- S21: the 90/180 gates read results.window.days (S10 γ2) and S21 turns their None into named absence reasons.
- S8: the project_multi_year move leaf depends on S10 ε and carries the window reads.

## Shared conventions (every session)

- Every task filed carries `metadata.x_finding_key` (list), `metadata.x_finding_run = "review-all-solar_challenge-20261013"`, `metadata.source = "review-all"`, `priority` = the finding severity, file-level `metadata.files`; file under `planning_mode=True`, wire `add_dependency`, then one `commit_planning` per batch.
- Run docs/quality-findings-contract.md §8 step 1 (key lookup over `$.x_finding_key`, scalar or list) immediately before filing each key, whatever the report table says; a `done` task with the finding still present files with `x_supersedes_task`.
- An acceptance is a `cancelled` task carrying `metadata.x_acceptance_reason`, never `deferred`.
- **Freshness clause**: anchors were verified at `7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8` and main has moved; before building a task on an anchor, `git diff 7dfea36e..main -- <path>` and re-read the symbol.
- **Held leaf**: a leaf that depends on a later stream's contract is filed with `metadata.x_seam_wait = {stream, contract}`, wired into its own batch's dependencies and excluded from that batch's `commit_planning`; the owning stream's session releases it.
- **One editor per document**: a /prd seat never edits this program doc or another stream's PRD; it returns its FILED row and cross-reference lines as a structured block for the lead to apply.
- Each `/prd` session adds its `high`/`critical` leaves as dependencies of the trigger-chain gate named in §FILED once it exists.
- The quality definition is dark-factory's docs/code-quality.md (this repo carries no copy); the contract is docs/quality-findings-contract.md in the dark-factory checkout.
- Weakened findings (D28) are re-measured by the session before decomposition; a measurement that fails is recorded on the task, not silently dropped.
- The frozen public surface changes only through S29's one bump (D4): a stream that retires or renames a public name files its surface edit as a held leaf waiting on S29.

## Triage briefing

- The pinned worktree for this run was removed by an external sweep of `.worktrees/` mid-run; seats read a `git archive` of the same commit. Future runs pin under a directory the orchestrator does not sweep.
- Tasks 681, 270, 581, 485, 674, 297, 675, 237, 284, 376, 564 and 245 pre-date this run and already cover 13 mechanical findings; do not duplicate them.
- The `/review` instrument keyed cli/, tariff.py and seg.py under other areas (D1): until `/review-briefing` writes the member lists, a key lookup that misses may be a re-keyed twin; search by anchor as well.
- `richardsonpy` load generation seeds process-global RNGs (S13); until S13 lands, parallel fleet tests that compare profiles are order-sensitive.
- Instrument debt: none (both siblings ran whole in Phase 2); the dark-factory snapshot instrument needs task 6921 before the next run can measure this repo without the shim.

## FILED — program status

| Stream | PRD | Task id | Finding keys | Severity |
|---|---|---|---|---|
| (Phase 5 mechanical) | — | see report §Mechanical filings | 69 keys: 53 filed as tickets, 13 already covered, 3 left open (weakened) | mixed |

Trigger chain: human gate task 772 (interim form, skills/_shared/filing-the-trigger-chain.md §4; `metadata.trigger_chain = {role: human_gate, skill: review-all, run_id: review-all-solar_challenge-20261013}`), filed deferred under planning mode on 2026-10-14; each /prd session adds its high and critical leaves as its dependencies; committed by the human once this table is complete. No earlier review-all chain existed; launched_from: none.

Coordinator interventions: the S9 and S11 spawns failed once on shell quoting and were relaunched; the fused-memory server restarted during Phase 5 ticket resolution and 29 tickets were resubmitted.
