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

Deletable: 266 lines of parameter-sweep runner and its test file; config.py's imports of home and fleet; the cli/config.py templates' dead output: keys (D11 keeps period:); every reader-local error message that omits its block_path.

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
| ScenarioConfig.simulated_homes() / map_homes() / window() / with_window() / simulation_bounds() (owner: config, S6 α and β; consumers finance, optimize, projection.scenario_fleet (928), cli, web, S25, S26; there is no with_seg(): simulated_homes() fills the scenario SEG under D10) [amended L41] | S6 | every other stream that reads it |
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
| Report sections keyed by assumption mode (owner: board_report.generate_finance_report after S25 β; reader cli/finance) [amended L39] | S25 | every other stream that reads it |
| Typed summary rows (owner: cli/utils home_summary_rows and fleet_summary_rows, task 705 as S25 α; readers cli/home, cli/fleet) [amended L39] | S25 | every other stream that reads it |
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

### D34. Economy 7 / Economy 10 reference rates (S11 Q1) — ruled_by: human

tariff.PRESET_RATES carries the web's rates, 0.13/0.35 (Economy 7) and the matching Economy 10 pair, closer to 2024 retail; the library's 0.09/0.25 and 0.08/0.27 defaults move to them, so every rate-less economy block's runs and the three board-facing scenarios move once their restatements go. The S11 PRD was written to the library default and is amended by the S11 decompose session.

Options considered: library rates 0.09/0.25; web rates 0.13/0.35.

Consequence that decided it: one reference set that matches retail; board scenarios re-price.

Keys: fk-463e82417506

### D35. task 195 (S14 Q1) — ruled_by: human

Task 195, whose finished branch retires PVConfig.module_efficiency and temperature_coefficient against D14, is cancelled as superseded by the S14 PRD (x_superseded_by stamped on the S14 ζ leaf at decompose); escalations esc-195-2, esc-195-3 and esc-224-2 are closed as superseded; task 224 loses its dependency on 195.

Options considered: cancel and dismiss; leave for Leo.

Consequence that decided it: a branch contradicting D14 cannot merge by a stale escalation being resolved as moot.

Keys: fk-f5cd69400ce6

### D36. task 468 (S19) — ruled_by: human

Task 468, architect-routed with a plan contradicting the run-store stream, is cancelled now with x_superseded_by the S19 PRD; 547, 355 and 614 are cancelled at S19's decompose.

Options considered: cancel now; let it run.

Consequence that decided it: no second owner of the runs table lands under the stream.

Keys: (cross-cutting)

### D37. theme token scope (S21 R1, ruled in the S21 /prd session, 2026-10-15) — ruled_by: human

static/src/theme-tokens.json names the accent and every UI role that reuses amber today (warning banner, running status, PV component card), each a built-in Tailwind palette name, plus the chart hues and roles; templates switch amber-* to primary-* or role classes with no visual change; _AMBER_ROLES and its meta-tests are deleted.

Options considered: accent only; role palettes.

Consequence that decided it: one colour table for Tailwind and charts.

Keys: fk-93ee9a05751a

### D38. sweep chart (S21 R2) — ruled_by: human

sweep_parameter_chart is kept and drawn server-side, the optimum chosen by each metric's direction; the Chart.js path is deleted.

Options considered: Chart.js in the browser; server-side Plotly panel.

Consequence that decided it: one renderer for every chart.

Keys: fk-55f4e4ea396d

### D39. chart chrome (S21 R3) — ruled_by: human

chart-renderer.js holds no colour: it reads text and grid colours from the computed style of the chart container, whose classes name theme colours; figure backgrounds stay transparent. The program's seam row reads: theme tokens (owner static/src/theme-tokens.json; readers tailwind.config.js and charts.py; chart-renderer.js through the compiled theme).

Options considered: tokens emitted to JS; computed style.

Consequence that decided it: no second colour channel.

Keys: fk-93ee9a05751a fk-8f26d000b68d

### D40. fk-657669b23e71 accepted (S21 R4) — ruled_by: human

The committed compiled stylesheet drifting is accepted as standing: D22 names the css-build lane job as the guard, the per-task sandbox cannot reach npm, and the lane has filed 2 reds since 2026-10-05 and none since the pin. Filed as a cancelled task carrying x_acceptance_reason at S21's decompose.

Options considered: fix (an in-sandbox rebuild check); accept as standing.

Consequence that decided it: an accepted disposition with an owner, re-verified next run.

Keys: fk-657669b23e71

### D41. capacity-at-events firmness (S9 lead question 2, ruled by Leo in the fable /team investigation session, 2026-10-16) — ruled_by: human

Firm spare capacity is measured per event day and booked at its mean over event days, under a named delivery baseline (operational, a DFS-style increment above own discharge, the default; or capacity, an NGED-style whole-window discharge), with the capacity available on 50% and 90% of event days and the evening self-use an event displaces reported beside the income. Carried by S9 as a new leaf α′ between α (801) and β (802), depending on 801 and 774. A successor PRD, the counterfactual event simulation (paired baseline and event-dispatch runs, delivery metered per product baseline, net income booked with its incidence), follows α′; the frozen-library posture does not bar simulator changes made for correctness. S16 is unaffected. The board hears the two §2.2 findings: the season-minimum rule priced the 100-home board fleet at about £3 a year, the per-event-day mean at £296 (SOH 1.0) and £143 (SOH 0.8), against £3,000 under the flat model.

Options considered: season minimum (status quo, £0); per-event-day mean with a delivery baseline; capacity baseline; retire the events model.

Consequence that decided it: the events model prices what a product would pay for; the board figure moves from £0 to a measured, baseline-named income.

Keys: fk-758b2f309cab fk-4ddab794283a

### D42. settlement charge basis (S3 Q1, Q5) — ruled_by: human

Battery.charge reports the energy drawn and every flow is a bus energy, so no loss term is carried anywhere; the storage identity test pins the loss; battery_charge and grid_charge figures rise by 1/η (2.56% at the default) and the board figures move (bristol-arbitrage 2024-01-15 import 7.904 -> 7.959 kWh, export 0.0037 -> 0), disclosed through the cost-recovery header line and an Unreleased line; no human gate before γ merges.

Options considered: bus energy; stored battery_charge plus a charge_loss field; bus energy behind a human acknowledgement.

Consequence that decided it: one energy identity; four readers unchanged.

Keys: fk-7440003fdd59 fk-2a53ae89932e

### D43. task 564 (S20 Q1) — ruled_by: human

Task 564, whose reviewed branch removes the 600-second SSE limit and adds a briefing line forbidding one against D21, is cancelled as superseded by S20 δ; its key fk-0097b5aaa45c moves to δ.

Options considered: cancel; let it land and rebase.

Consequence that decided it: D21's named timeout event stands.

Keys: fk-0097b5aaa45c

### D44. Economy 10 reference rates (S11 decompose) — ruled_by: human

Both presets carry 0.13 off-peak / 0.35 peak under D34; Economy 10 differs only in its hours. Board scenarios re-price (bristol-arbitrage 2024 import cost £204 -> £292, example-economy7 £247 -> £344).

Options considered: both 0.13/0.35; Economy 10 keeps its own pair.

Consequence that decided it: one reference pair.

Keys: fk-463e82417506

### D45. agent-mode pass timing — ruled_by: human

The agent-mode authoring pass (S5, S7, S13, S22, S23, S27; S29 last) starts now that every wave-1 spawn stream has filed, since S5 and S13 block S6, S12 β, S18, S25 and S26.

Options considered: start now; wait for S3, S12, S16, S20 to file.

Consequence that decided it: the blocked streams can author.

Keys: (cross-cutting)

### D46. task 237 (S5 Q4, ruled by Leo 2026-10-17) — ruled_by: human

Task 237 (implemented on task/237, under review) is cancelled at the S5 decompose with x_superseded_by S5 α after the step-1 lookup, unless it is done by then; 320 follows it. Its review work is dropped: α deletes run_parameter_sweep and everything 237 changed.

Options considered: cancel at S5 decompose; let 237 merge first, α deletes afterwards; lead cancels 237 and 320 now.

Consequence that decided it: no review and merge spent on code α deletes, and no rebase of α over it.

Keys: fk-caad5305a3be fk-59fdc80fdded

### D47. task 582 (S8 decompose, ruled by Leo 2026-10-17) — ruled_by: human

Task 582 (the age-0 outlay fleet simulation written twice), released into progress when its dependency 350 was cancelled, is cancelled now by the lead with x_superseded_by 930 (S8 ζ, run_cost_recovery); the edges 928 -> 582 and 930 -> 582 are removed; its branch and worktree are housekeeping.

Options considered: let 582 finish, 928 and 930 wait for it; cancel 582 now.

Consequence that decided it: no review and merge of code 930 replaces, and 928/930 do not wait on a plan that assumed the 350 split.

Keys: fk-50cf1dd5df58

### D48. S25 board figures that move (ruled by Leo 2026-10-17) — ruled_by: human

Both S25 moves are accepted for the board and recorded on leaves γ and δ: γ makes --assumptions spreadsheet render the override's economics and solved own-use rate (today physics), physics on bristol-fin-calibration.yaml render physics (today the override's) and both gain Spreadsheet columns, the 'Physics Assumptions' heading going; δ makes the flex block's grid-services row on bristol-phase1-flex.yaml --flex-band central fall from the consulting £30 per home to the booked events figure, about £3 per battery home on the S9 ~£296 fleet figure, the headline falling by the difference, and the events income appears whenever the report projects.

Options considered: accept both; accept γ only, hold δ; hold both.

Consequence that decided it: the board report says what D24 and D41 already decided, in one release.

Keys: fk-b7241e0ce122

### D49. task 377 (S5 decompose, ruled by Leo 2026-10-18) — ruled_by: human

Task 377 (finance parser errors name the offending key), a keyless twin of S5 δ (948) with a live claimant and three commits on task/377, is kept behind 948 and re-read at dispatch; it is not cancelled.

Options considered: keep behind 948; cancel now with x_superseded_by 948.

Consequence that decided it: no running work is killed; 372 and 374 already delivered most of its finance items.

Keys: fk-e2aaf2bfe651

### D50. flat home-file form (S6 Q5, ruled by Leo 2026-10-18) — ruled_by: human

S6 γ retires the flat home-file form (a home file whose top level is the home's own keys without a home: block) with a named refusal that says to wrap it in home:; one home-file form remains.

Options considered: retire with a named refusal; keep the flat form as a documented exception.

Consequence that decided it: one reader, one form; the retired flat keys derive from HOME_BLOCK_KEYS.

Keys: fk-2264bc150fa3 fk-416eb5643e7a

### D51. task 358 against D24/D48 (ruled by Leo 2026-10-18) — ruled_by: human

D24 and D48 stand: S25 γ (973) threads each --assumptions mode into the bill, the projection, the economics and the solve and labels every column; task 358 (finance run --assumptions selects only the bill table), whose esc-308-3 ruling of 2026-10-17 said label and do not thread, is cancelled with x_superseded_by 973 and that reading is recorded as considered and rejected.

Options considered: D24/D48 stand, cancel 358; keep label-do-not-thread, re-rule S25 γ and amend D24/D48.

Consequence that decided it: one assumption model in the board report, ruled with the deliberation context.

Keys: fk-b7241e0ce122

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
- L16 (S4; ordering against S5 (Q1); β after S14 ζ, γ after S11 α (Q2); S3 takes the engine checks (Q3); keys staying with 517 and 707 (Q4); invariant 1 premise (Q5)): All accepted: S5's partition depends on S4 α and S4 ε depends on S5's partition; β depends on S14 ζ and γ on S11 α (ι converts stragglers); S3's engine checks go through Interval.admits and depend on α, so fk-a9c609ecb8ef closes when S4 ι and S3 land; fk-5827f41eb082 stays with task 517 and fk-e79170280adf with 707, with the edge 707 -> α; invariant 1's checkable text becomes 'every input type' plus the reasoned classification of computed results.
- L17 (S21; supersessions at decompose (Q1); R1-R4 numbering (Q2); task 454 (Q3); form-label macro (Q4); edges on 691 and 736 (Q5); seam wording (Q6)): Q1 all supersessions as listed (123, 135 -> η; 129, 456 -> δ; 492, 565, 575, 629 -> ζ; 628 -> ε; 735, 737 -> γ; 153's charts item -> δ, 153 stays for api.py). Q2: R1-R4 are D37-D40. Q3: Leo rules on closing esc-454-3; until then δ carries no edge on 454 and does the hoist itself. Q4: the form-label macro is offered to S18 (cross-reference). Q5: the edges on 691 and 736 stay (they serialise edits to chart-renderer.js). Q6: seam wording adopted in D39.
- L18 (S24; setuptools floor under D23 (Q1)): Build requirements are outside uv.lock, so D23 has no referent for setuptools>=77.0.0: the declared floor stays and tests/unit/test_build_system.py is deleted with the other capability-claim tests.
- L19 (S28; with_round_trip shape (Q1); transitional refusal (Q2); throughput unit (Q3); γ -> S19 κ edge (Q4)): Defaults accepted: with_round_trip is a method on a config; the transitional refusal ships in α; throughput is discharged energy, one cycle per usable capacity, and finance's accrual matches; the lead adds the γ -> S19 migration-leaf edge when S19 files.
- L20 (S14; task 195 (Q1) and the escalation cluster): Done 2026-10-15: esc-195-3 closed with members esc-195-2 and esc-224-2 as superseded, task 195 cancelled with x_superseded_by_prd, task 224 no longer depends on 195 (D35). Task 468 cancelled (D36).
- L21 (S19 decompose; inbound edges; 750 and 760; task 140): Edges 784 -> 822 and 790 -> 822 added by the lead; S28 γ -> 822, S21 panels -> 822 and 814, S21 comparison -> 816 and S20 -> 806, 819, 814, 822 are passed to those sessions. The cancellation of 750 (x_superseded_by 807) and keeping 760 (α 805 depends on it) are ratified. Task 140 is left as filed unless the S19 session names a conflict.
- L22 (S14 decompose; task 756; tasks 389 and 504; key on 284): Task 756 stays in progress and delivers α (γ 812 and ζ 825 depend on it), accepted. fk-998f0cb69410 is stamped on task 284. Tasks 389 and 504 depended on the cancelled 195: their dependency is removed and each is re-read against D14 at its next dispatch; neither is cancelled by the lead.
- L23 (S15 decompose; task 366): Task 366 depends on 813 and seeds the e2e server through SOLAR_CHALLENGE_WEATHER_CACHE_DIR instead of set_weather_cache.
- L24 (S9 α′; filing the firmness leaf): A follow-up decompose pass files α′ from the amended S9 PRD §5.10 between 801 and 802 (802 gains a dependency on it), carrying the keys of its parent finding (fk-758b2f309cab) and the x_finding_run; the successor counterfactual-event PRD is authored after α′ lands.
- L25 (S3; decision bounds (Q2); edge direction with 790 (Q3); task 183 (Q4); self-consumption of grid-charged discharge (Q6)): Context-free bounds in DispatchDecision.__post_init__ and step bounds in StepLimits.require_admissible applied by simulate_timestep, raising rather than clamping; 790 (S2 ε) depends on S3 ε and S3 ε depends on 839 (S11 β), as S11's decompose wired, so L15's 'routing leaf add_dependency on 790' is corrected to that direction; task 183 stays deferred with no edge and a note that a revival re-plans the oracle ceiling as an input of TOUOptimizedStrategy on the one engine; self-consumption of grid-charged discharge is a candidate finding for the next run (triage note), not S3 work. Q1 (charge basis) and Q5 (a human gate before γ merges) are Leo's.
- L26 (S12; pre-existing tasks (Q1); S19 frame transform (Q2); order against S13 (Q3)): Keep 708 (γ depends on it); cancel 711, 745, 725 and 726 with x_superseded_by at decompose after the step-1 lookup; S19's PRD row drops the frame-transform clause (ζ's step is summary-only); β is filed as a held leaf with x_seam_wait on S13's hand-off leaf and follows S13's shape of the injectable per-day simulator.
- L27 (S16; callable vs runner on finance and optimize (Q1); ζ at the bump (Q2); root-level --workers/--sequential (Q3); supersessions (Q4)): Defaults accepted: finance and optimize keep the frozen simulate callable form, made required on the non-frozen functions, roots passing runner.simulate; ζ (retire solve_cost_recovery_rate's simulate=None and export FleetRunner with its protocols) is a held leaf for S29; --workers and --sequential move to the root command (fleet run --workers N becomes solar-challenge --workers N fleet run); 740, 742, 747 and deferred 121 are superseded at decompose; fk-e58042aef503 is closed by task 709.
- L28 (S20; task 680 (Q2); task 646 (Q3); reading of D21 (Q4)): 680 is cancelled with x_superseded_by γ at decompose (snapshots replace the drained queue); 646 lands and β subsumes it, no edge; the D21 reading is confirmed: each terminal status names its own event (completed, failed, cancelled), the chat's failure event is also failed, id and retry travel on the job stream only, complete becomes completed. 564 is cancelled by the lead (D43).
- L29 (S22; seam reading of the benchmark constants (a); β absorbing 506 and item 3 of 440 (b)): Accepted: S14 δ (818) produces the three validation.UK_* constants and S22 owns the reading rule plus validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP (the figure 823 documents); S22 β is the existing task 751 re-scoped in place, 506 is cancelled with x_superseded_by 751, and the lead narrows 440 to api.simulate_sweep; fk-ab16fff6f6c3 is closed by task 713 (chat complexipy 47 -> 3 at ac1fdf1), so no leaf. Triage notes carried: METRIC_TABLE's grid_export band (1,400-1,800 kWh) against the engine's ~2,400-2,800; battery_cycles' SOC definition vs 865; load-config.html's restated TDCV.
- L30 (S27; β in-leaf or held under D29 (Q1); β's edge on S16 α (Q2)): β lands in-leaf (freezing FleetConfig, FleetResults and CommunityResults with tuple fields is neither a rename nor a retirement; lists are converted at construction, following task 436's freeze of SimulationResults); β depends on S16 α, edge added when S16 files; γ (sharing_mode derived) is held for S29; 706 is superseded by α, 669 is amended not cancelled, fk-dc5cf2ec9b84 is closed by task 743.
- L31 (S13; seed domain (Q1); fk-c78416de5500's guarded-region half (Q2)): Decision 4 ratified: every int is a valid seed, [0, 2**32) keeps today's exact random.seed/np.random.seed calls so seeded outputs are byte-identical, other ints and None go through numpy SeedSequence with sign kept; task 573's range rule and task 766 are superseded by α and S4's §10 row reads accordingly (fleet_distribution.seed's whole-number read stays S4 ζ). fk-c78416de5500 is stamped on α only; the wide-try half is S12 β's under fk-72af0b90338d and the next run re-verifies after both land. Invariant 3's middle clause becomes 'two unseeded profiles, each generated right after the same seeded profile, differ'. The fork-child lock reset (C5, B6) stays.
- L32 (S23; file η now as a held leaf (Q1); seam row owner file (Q2)): η (released snapshot plus an executable Unreleased-on-main check) is filed held with x_seam_wait on S29's release commit; the seam row reads owner tests/unit/test_public_api_surface.py (tables) with tests/_surface_forms.py (forms, classification). Two stream-row claims corrected by measurement: __all__ and the TYPE_CHECKING block stay literal (mypy --strict rejects a computed __all__ for star-import consumers) and the import-time check widens to every runtime pair instead; the frozen/eq/order dimension is already delivered by task 567. Tasks 700 and 785 are built on, not superseded; 668 gains fk-879e8c13f581 and an edge on ζ; β (high) joins gate 772.
- L33 (S8; supersessions (Q1); ι's reading of D29 (Q2); CostRecoverySolution's clean form (Q3); board figures that move (Q4)): Supersessions as listed (350 -> δ, 581 -> α, 582 -> ζ, 690 and 715 -> β with fk-50cf1dd5df58 moving to β, 720/721/730 -> ε; 667 re-scoped to read SimulationResults.pricing and depend on β), each re-read for status and claimant right before cancelling, an in-progress target taking an edge instead; ι (the _SYMBOL_MODULE repoint) stays held for S29 as D4 reads it; the CostRecoverySolution frozen-form break is not filed (η's enforcement removes the risk); the moving board figures (θ: physics capex falls 2.22% / £9,551 on bristol-phase1 for PV the simulator never wires; ε: per-year revenue between nodes by up to £41-150; ζ: optimize's baseline for configured battery ages; β: a £0 tariff bills as configured) are recorded for the board in §Triage and on each leaf.
- L34 (S17; task 517 and fk-5827f41eb082 (Q1); fk-a0866b1bd680 (Q2); location-block tightening (Q3); θ on S16 δ (Q4); D2 reading (Q5)): ζ supersedes 331, 517 and 560 and carries fk-5827f41eb082; fk-a0866b1bd680 is stamped on task 297, 297 is raised to high and joins gate 772 beside S17 δ; S17 γ makes the location: block tightening so one mapping rule serves files and requests, S5 moves it; θ depends on S16 δ (task 889, now filed) rather than being held; D2 is read as the PRD does, a non-domain ValueError is answered 400 and logged at ERROR.
- L35 (S7; exact pool counts (Q1); writer rule for an unset Optional (Q2)): Exact: a shuffled pool whose counts exceed n_homes is refused by name, matching ShuffledPoolDistribution's contract and task 297's plan; the writer writes every key, null when unset (decision 5), and 825 (S14 ζ) follows that rule by cross-reference, its B6 round-trip asserting config equality. β, δ and ε (high) join gate 772; 599 -> β, 662 -> γ, 403 -> γ/δ, 600 -> δ, 283 -> β/δ superseded; 297 and 395 kept.
- L36 (decompositions S4, S12, S16, S20, S24, S3; deviations and leftovers reported): Accepted: 742 and 121 were in progress at S16's decompose, so 882 depends on 742 and 889 on 121 instead of cancelling them, and S16 ε carries x_finding_key [] with x_lead_ruling L10; task 728 (a reconciliation-filed twin of fk-1d920c89e872 with no key) is cancelled by the lead with x_superseded_by 894 and 895; task 270 had merged its tail extraction so S3 α (896) carries x_supersedes_task 270; task 183 is cancelled; 366's description is corrected to the L23 variable; fk-5827f41eb082 is stamped on 517 only until S17 ζ supersedes it. Housekeeping recorded in §Triage: worktrees .worktrees/123, 492, 680 and the empty branches of 382, 314, 187 belong to cancelled tasks.
- L37 (S5; ordering against S7 (Q1); ScenarioConfig.tariff_config (Q2); priority of β and γ (Q3)): Default accepted for Q1: β and γ depend on every S7 leaf whose metadata.files includes src/solar_challenge/config.py (the S5 decompose reads them from the store after S7 files) and S7 takes no edge on S5, so each move lands once. Q2: S6 decides in its /prd session whether tariff_config stays as the typed home of a scenario-level tariff: under D10 fill-and-refuse; if S6 names no reader, S5 ζ retires it with output. Q3: β and γ are filed high and join gate 772, an exception to priority = severity recorded on each leaf as metadata.x_lead_ruling L37, because 866 and 868 (high) wait on them and the gate must see the whole chain. Q4 (task 237, implemented on task/237) is Leo's, see D46.
- L38 (decompositions S13, S22, S27, S23, S8, S17, S7; deviations and leftovers reported): Accepted: 894 is released by the lead onto 906; 790 files gain community.py; 440 is narrowed to api.simulate_sweep and 751 retitled as S22 β; the files of 297 and 668 are corrected for the deleted and split test modules (a stale path blocked 394 at the merge gate); 287 gains an edge on 930 rather than being absorbed by S8 ζ; 584 depends on 921 and 935 and goes to the S18 decompose as a pre-existing task, since its web route samples through the one sampler (D18); the S27 β web/jobs.py conditional and the S17 γ / S7 β location-rule overlap are accepted as order-agnostic; the stale L36 claim that fk-5827f41eb082 was on 517 is corrected (it lives on 938). Task 582 is Leo's, see D47.
- L39 (S25; typed-rows seam owner (Q1); task 705 re-scoped as α (Q2); report-sections seam owner (Q3); per-mode projection simulations under both (Q4)): Defaults accepted: the Typed summary rows seam is owned by cli/utils (home_summary_rows and fleet_summary_rows, task 705), since the labels are CLI presentation and members on the frozen domain types would widen a frozen form; 705 is re-scoped in place as S25 α with fk-6a52ed98b18e stamped (re-read first: if done, stamp the key only; if cancelled, file α new); the Report sections seam is owned by board_report.generate_finance_report once β moves it; the extra per-mode projection under --assumptions both is accepted now and sharing its node simulations is a §Triage follow-up after 929, since it needs an S8 contract change. Q5 (board figures) is Leo's, see D48.
- L40 (S5 decompose; sidecar hazards (lines 2-5) and keyless twins (line 6) reported): The S4 construction wrap is spelled constructed (public) in scenario_blocks.py and the 866 wrap-exists check plus the S4 sidecar admit both spellings; the 790 held-leaf absent-check in the S2 sidecar also scans fleet_distribution.py; the 914 and 837 present-checks already scan scenario_blocks.py and the 868 float_or_none pattern already covers both spellings, so nothing else changes. Keyless twins: 328 and 563 are cancelled with x_superseded_by 948 and 762 with 945 (pending, no claimant, no branch commits); 325 is handed to the S6 decompose, which cancels it as superseded by S6 γ; 261 depends on 945 instead of 237 and drops the deleted test file from its files; 587 needs no edge. 377 is Leo's, see D49.
- L41 (S6; edge direction with 928 (Q1); freezing ScenarioConfig in-leaf (Q2); accessor name (Q3); S17 pointer (Q4)): Defaults accepted: 928 (S8 δ) depends on S6 α and β and builds scenario_fleet on simulated_homes() and simulation_bounds(), moving neither, since S6 owns the accessors; ScenarioConfig is frozen in-leaf under L30 (the freeze moves to ι only if the S23 lock labels it breaking at the base); the accessor is simulated_homes() with map_homes() for home-level transforms and no with_seg(), and D25 and the S25/S26 decompose prompts read homes() as simulated_homes(); the fleet import loading a scenario-level location is an S18 follow-up candidate in §Triage, not filed. One home for the default window: S6 β defines timebase.DEFAULT_FIRST_DAY and DEFAULT_LAST_DAY (not config.py) and S18 α reads them (L42). S6 η owns the dashboard reading through the reader and S18 ζ depends on it. The fleet run SEG booking and the home run one-day period are consequences of D10 and D11, recorded in §Triage. Q5 (flat home files) is Leo's, see D50.
- L42 (S18; preview (Q1); old flat-form presets (Q2); builder start state (Q3); drawn values (Q4); constants and import overlaps with S6): Defaults accepted: ε keeps the preview endpoint and wires it into the fleet page through parse_fleet_form (D18 and the stream row keep it); builder presets saved in the old flat form are refused by name; the builder starts at the fleet page distributions; every home value, drawn ones included, is bounded by the component range and a draw that crosses it is refused naming the home. α defines no constant: it depends on S6 β, which puts DEFAULT_FIRST_DAY and DEFAULT_LAST_DAY in timebase.py, and repoints the CLI, templates and web/simulation_params.py to them, adding the invariant 11 window test; ζ depends on S6 η and moves the parse_scenario-based readers into web/scenario_import.py; δ and S6 η overlap textually in fleet_scenario.py, second lands rebases. β takes the S21 form-label macro as number_field and carries no S21 key; the next run re-verifies the form-label part of fk-ff5b90768f66. 612 and 298 are parked deferred by the lead now and cancelled at decompose.
- L43 (S26; task 440 (Q1); placement table location (Q2); S6 seams (Q3); --param readings (Q4); 804 edge (Q5)): Defaults accepted: 440 stays as narrowed (L29) and S26 δ depends on it; SWEEP_PLACEMENTS lives in fleet_distribution.py and the registry scenario_knobs.py above config; the S6 seams are simulated_homes() for reads, map_homes() as the form-preserving write, the SEG knob as replace(seg_tariff_pence_per_kwh=v) refused at construction when a home sets its own other rate (D10 holds at construction, so the knob stays in the registry), the fleet-document reader S6 γ and the cli/optimize rewiring S6 ε, so S26 β depends on S6 α and γ, S26 γ on S6 ε and S26 η on S6 γ; fleet sweep --param keeps one option with two readings; 804 depends on S26 β.
- L44 (S6 decompose; keyless twins 390, 658, 759 and the 767/358 overlaps reported): 390 is cancelled with x_superseded_by 961 and 658 with x_superseded_by 956 (each pending with no claimant and no branch commits when re-read); 759, which would put the default-window constants in config.py, is cancelled at the S18 decompose with x_superseded_by S18 α and 956 (L42 puts them in timebase.py); 767 and 358 keep their edges on 959; the extra edge 960 -> 739 and the moved edges 390 -> 961, 358 -> 959 are accepted; the S18 decompose reads the constants as DEFAULT_FIRST_DAY and DEFAULT_LAST_DAY.
- L45 (S29; task 224 (Q1); version (Q2); what β waits for (Q3); tag and re-pin (Q4); gate 772 (Q5); contradictions found (Q6)): Defaults accepted: 224 is parked deferred by the lead now and re-scoped in place as β at the S29 decompose, keeping its release-scope notes; the version is 0.6.0 (a pre-1.0 minor, as 224 notes and the v0.5.0 precedent say); β waits for every held leaf and every open library-side program leaf, recomputed from the store at decompose, so the platform re-pins once (D4); the tag cut and the platform re-pin are the human gate γ, since a leaf cannot tag its own merge commit; β joins gate 772 at medium priority, an exception recorded as x_lead_ruling D4, so the next review-all run follows the release. Contradictions resolved: S29 writes no S4 entry and β folds the S4 in-leaf lines (the later S4 decompose line stands); the held count is 16 today (15 retirements across 14 streams plus 927) and 17 with S25 ζ; the store spelling of 826 x_seam_wait holds; the edge-direction ask is met by splitting α (window open, held leaves depend on it) from β (release commit, depends on them); 950 retires tariff_config and its title is amended at the S29 decompose.
- L46 (S26 decompose; 807 check, extra edges and task 486 reported): The 807 server-side-step-ceiling check is widened to paths src/solar_challenge/web and pattern SWEEP_MAX_STEPS on the task and in the S19 sidecar, so moving the ceiling into web/sweep_request.py at 967 does not wedge 968; the extra edges 969 -> 957, 971 -> 960 and 767 -> 966 are ratified; task 486 (pending, four commits on task/486, no claimant) is not cancelled: it depends on 964 and re-reads at dispatch, with fleet_distribution.py added to its files, since 947 empties config.py of the reader it fixes.
- L47 (S25 decompose; checks pinned to output.py; 358; keyless overlaps 724 and 439): The 783 board-reports-render-notice, 837 report-renders-the-reliability-rows and report-renders-the-displaced-self-use present checks and the 930 configured-rate-not-a-literal absent check also scan src/solar_challenge/board_report.py, on the tasks and in the S10, S9 and S8 sidecars, because S25 β (970) moves the board reports there; the edges 970 -> 724 (its branch deletes the dead ratio wrappers) and 975 -> 439 (in progress, adds the SEG-rate-passing summaries ε removes) are ratified; 705 re-scoped in place as α stands. Task 358 is Leo's, see D51.
- L48 (S18 decompose; θ priority; twins 844 and 754; fk-94cab00e114e): θ (984) filed high is ratified as the integration gate and joins gate 772; fk-94cab00e114e moves from the cancelled 759 to 977; twins 844 (keyless) and 754 (/review-keyed) are cancelled by the lead with x_superseded_by 980 when pending with no claimant and no branch commits, else kept behind 980.
- L49 (S29 decompose; 804 dropped check; overbroad warnings; the β fold against five doc-pinned checks; 950 description; 224 stale fields; held-leaf priorities; γ milestone delay): The 804 transitional-rule-deleted absent check, refused as vacuous_absent because its producer has not landed, is accepted as dropped (804 keeps seven checks and its signal); the 905 and 976 overbroad warnings are advisory, their upstream leaves 904 and 975 delete the matched lines; the five finance-model-doc present checks (801 capacity_at_events and 9.97, 803 independent calibrations, 837 delivery_baseline, 865 equivalent full cycle, 900 charge loss) are widened to also scan docs/domain-library-consumption.md on the tasks and in the S9, S28 and S3 sidecars, so the 224 fold can move the Unreleased paragraphs without wedging gate 772, and the keep-in-place constraint appended to 224 becomes advisory; 950's description carries a lead note resolving its conditional clause; 224 keeps its pending_since and routing record; 912, 927 and 976 stay at their filed priority; γ takes no milestone delay.

## Cross-reference lines applied by the lead

- S29 (decompose, L45, L49): α is 986 (window open; depends on 926 and 774), β is 224 re-scoped in place (release commit 0.6.0; priority medium; 116 dependencies: 986, 926, the 16 held retirement leaves and 98 open library-side program leaves recomputed from the store), γ is 987 (human gate, task_kind deterministic; depends on 224); 927 and 772 depend on 224; every held leaf (784, 790, 804, 826, 827, 843, 867, 892, 901, 905, 912, 939, 941, 950, 963, 976) depends on 986 and was released by one commit_planning each, x_seam_wait moved to x_seam_released, each stream sidecar stamped; 950 title and description note amended (tariff_config retired).
- S9, S8, S10, S28, S3 (from S29 decompose, L49): the finance-model-doc present checks of 801 (capacity_at_events, 9.97), 803 (independent calibrations), 837 (delivery_baseline), 865 (equivalent full cycle) and 900 (charge loss) also scan docs/domain-library-consumption.md, where the 224 fold moves the Unreleased paragraphs, so the fold cannot wedge gate 772; the 804 transitional-rule-deleted absent check was refused as vacuous_absent at release and is accepted as dropped (804 keeps seven checks); the overbroad warnings on 905 (simulate_timestep_tou in home.py, deleted by 904) and 976 (seg_revenue_gbp in cli/utils.py, fleet.py, output.py, deleted by 975) are advisory; 912, 927 and 976 stay at their filed priority; 224 keeps its 2026-09-30 pending_since and routing record (gated by its dependencies).
- S5, S6, S7, S4, S17, S11, S2, tasks (from S18 decompose, L48): S18 is 977 α, 978 β, 979 γ (high), 980 δ (high), 981 ε, 982 ζ, 983 η, 984 θ (filed high, the PRD row said medium: ratified, it is the integration gate); 979, 980 and 984 join gate 772; 977 depends on 956 (the timebase constants) and carries fk-94cab00e114e (moved from 759); 982 depends on 961; 676 moved from 612 to 978; 844 and 754 depend on 980 pending the lead cancellation; cancelled with x_superseded_by: 664, 376, 612 -> 978; 611, 753, 424, 592, 584, 360 -> 980; 569, 571 -> 981; 545, 549, 553, 554, 298, 359 -> 982; 759 -> 977 and 956; D28 re-measures recorded on δ and ζ (fleet_config 41.3% docstrings, fleet_scenario 34.2%).
- S8, S9, S10, S19, S29, tasks (from S25 decompose): S25 is 705 α (re-scoped in place, fk-6a52ed98b18e stamped), 970 β, 973 γ (high), 974 δ (high), 975 ε, 976 ζ (held for S29); 973 and 974 join gate 772; edges 970 -> 783, 837, 930, 765, 724 (724 deletes the dead ratio wrappers β moves); 973 -> 970, 930, 959; 974 -> 973, 803; 975 -> 705, 922, 780, 822, 439 (in progress, adds a SEG-rate-passing calculate_home_summaries that ε removes); 976 -> 975, 822; 358 depends on 973 pending the D51 reconciliation of its esc-308-3 ruling with D24/D48; the 783 and 837 present checks and the 930 15p absent check also scan src/solar_challenge/board_report.py (L47) because β moves the report builders there; two S25 absent checks and one comment check were re-anchored at decompose.
- S19, S20, S5, S6, S7, S9, tasks (from S26 decompose, L46): S26 is 964 α, 965 β, 966 γ, 967 δ, 968 ε, 969 ζ, 971 η, 972 θ, all medium, none on gate 772; 807 server-side-step-ceiling check widened by the lead to paths src/solar_challenge/web and pattern SWEEP_MAX_STEPS because δ moves the ceiling into the Flask-free web/sweep_request.py; ε must not use JSON.parse in parameter-sweep.js (888 absent check); 804 depends on 965; 718 cancelled -> 966 and 140 -> 968; 739 delivers fk-32d5e6707fb5 and 971 depends on it; 440 stays narrowed and 967 depends on it; extra edges ratified: 969 -> 957 (both rewrite parse_fleet_config and parse_sweep_fleet_configs), 971 -> 960 (fleet sweep file reading), 767 -> 966 (its own text starts after S26); 486 (four commits on its branch) depends on 964 and re-reads at dispatch, its files gain fleet_distribution.py; S7 defines no FleetFieldPath, ζ defines its own alias; textual overlaps only: 732 with η, 854 with γ, 959 and 767 with β; .worktrees/718 is an empty worktree of a cancelled task.
- S29 (from its PRD, L45): three leaves: α opens the solar-challenge-v0.6.0 release window (the release section heading in docs/domain-library-consumption.md and ConfigurationError in __all__, L3; depends on 926 and 774), β is the release commit (version 0.6.0 in pyproject and __init__, folded release notes from every Unreleased paragraph, the consumer recipe; task 224 re-scoped in place) and γ is the human gate that cuts and pushes the tag on β merge commit and files the platform re-pin. Release model: every held leaf depends on α and writes its Unreleased paragraph under the v0.6.0 heading; β depends on every held leaf and on every open library-side program leaf (recomputed from the store at decompose), so the platform re-pins once (D4); 927 depends on β. β joins gate 772 at medium (L45 exception) so the next review-all does not see a half-released surface.
- S2, S3, S5, S6, S8, S9, S10, S11, S12, S14, S15, S16, S23, S25, S27, S28 (from S29): each held leaf (784, 790, 804, 826, 827, 843, 867, 892, 901, 905, 912, 939, 941, 950, 963, S25 ζ) gains an edge on S29 α, writes its Unreleased on main paragraph under the v0.6.0 heading, touches neither version, uv.lock, tag list nor worked example, and is released by the S29 decompose commit_planning with x_seam_wait moved to x_seam_released; 927 depends on β and writes the snapshot step; the S4 line reads: S29 writes no S4 entry, β folds the in-leaf Unreleased lines of S4, S7, S13, S17, S22 and of the streams with no held leaf (S18, S20, S21, S24, S26); 950 retires tariff_config since S6 named no reader, its title amended at decompose.
- Platform (from S29): the solar_challenge_platform re-pin task γ files covers, at d521265, simulation_days (13 sites in 3 files), annual_self_consumption_kwh (4), seg_revenue_gbp (3), the heat-pump summary fields (12), per_home_net_bill_gbp (1), SimulationPeriod (2), GridChargeConfig imported from config (2 files) and solve_cost_recovery_rate simulate (3).
- S8, S18, S25, S26, S29, tasks (from S6 decompose): 928 depends on 955 and 956 and builds scenario_fleet on simulated_homes() and simulation_bounds() (L41 note appended to its details); S18 α depends on 956 and S18 ζ on 961, and the constants are DEFAULT_FIRST_DAY and DEFAULT_LAST_DAY (not the S18 PRD DEFAULT_WINDOW_START/END spelling; S18 keeps SHORT_WINDOW_START); S25 γ and its cli/optimize work depend on 959; S26 β depends on 955 and 957, γ on 959, η on 957; S29 releases ι 963 beside the 950 tariff_config retirement; 528 depends on 957; 960 depends on 739 (in progress, rewrites fleet sweep); cancelled with x_superseded_by: 485, 296 -> 955; 185, 542, 325 -> 957; 681, 422 -> 958; 287, 186, 541 -> 959; 390 moved from 185 to 961 and 358 from 186 and 287 to 959; 767 depends on 959; the ε carve-out check reads seg_tariff_pence_per_kwh= in cli/finance.py (task/738 drops the pre-CR5 comment); 955, 957, 958, 959, 962 (high) join gate 772; empty task/* branches and worktrees remain for 185, 186, 325, 422, 485 and 541 (housekeeping).
- Tasks (from S6 decompose, L44): keyless twins 390 (the simulate endpoint builds homes from the exported document, apply_fleet_overlay retired) and 658 (the non-date period refusal) are cancelled by the lead with x_superseded_by 961 and 956; 759 (the default-window constants in config.py) is cancelled at the S18 decompose with x_superseded_by S18 α and 956.
- S4, S2, S7, S9 (from S5 decompose, L40): 866 is released and depends on 946, 868 on 947, 948 on 866 and 868; the construction wrap is spelled constructed (public) in scenario_blocks.py because the S5 γ guard refuses an underscore import across grammar modules and 868 imports it, so the 866 wrap-exists check and the S4 sidecar admit both spellings; the 790 absent-check in the S2 sidecar also scans fleet_distribution.py; the 914 system_losses and 837 delivery_baseline present-checks already scan scenario_blocks.py; the 868 float_or_none pattern already covers both spellings.
- Tasks (from S5 decompose, L40, D46, D49): 237, 320, 651 cancelled with x_superseded_by 945 and 423 with 948 (fk-caad5305a3be stamped on 237); keyless twins 328 and 563 cancelled by the lead with x_superseded_by 948 and 762 with 945; 377 (live claimant, three commits) stays behind 948 (D49); 325 depends on 949 and is cancelled by the S6 decompose as superseded by S6 γ; 261 depends on 945 instead of 237 and drops tests/unit/config/test_parameter_sweep.py from its files; 587 (hoist import re) needs no edge; 933, 937 and 940 overlap 946, second lands repoints the imports; S6 depends on 947 and 949, S18 and S26 on 947; 946 and 947 (high, L37) join gate 772.
- S6 (from its PRD, L41, D50): the accessors are ScenarioConfig.simulated_homes() and map_homes() (homes() cannot exist beside the homes field), with window(), with_window() and simulation_bounds(); there is no with_seg(), simulated_homes() fills the scenario SEG and a contradicting home rate is refused at construction (D10); tariff_config gets no reader and S5 ζ (950) retires it, a scenario-level tariff: is applied as each home is built; the period is read as the S10 SimulationWindow and ι (held for S29) retires SimulationPeriod; flat home files are refused by name (D50); S6 γ adds tariff, fleet_distribution, flex_band and community to the S5 ε recognised keys and derives the retired flat home keys from HOME_BLOCK_KEYS.
- S8, S9, S10, S12, S16, S17, S18, S25, S26, S29, tasks (from S6, L41): 928 depends on S6 α and β (reversing the S8 §13 proposal) and builds scenario_fleet on simulated_homes() and simulation_bounds(), moving neither; S6 γ depends on 803 and ε deletes the 803 raw flex_band read; β depends on 778 and 893 (ONE_MINUTE); θ depends on 882; δ depends on 931; ε on 738; S18 α depends on S6 β and S18 ζ on S6 η (L42); S25 γ and the cli/optimize work depend on S6 ε; S26 β depends on S6 α and γ, S26 γ on S6 ε, S26 η on S6 γ, the SEG knob is replace(seg_tariff_pence_per_kwh=v) and home-level knobs use map_homes; S29 releases ι and the release section names it with the 950 tariff_config retirement; 528 depends on S6 γ; superseded at decompose: 485, 296 -> α; 185, 542, 325 -> γ; 422, 681 -> δ; 186, 287, 541 -> ε.
- S6, S18, S10 (L42, one home for the default simulation window): S6 β defines timebase.DEFAULT_FIRST_DAY and DEFAULT_LAST_DAY beside SimulationWindow (not in config.py) and reads them as the D11 default tier; S18 α depends on S6 β, defines no constant, and repoints the CLI, the templates and web/simulation_params.py to them, adding the invariant 11 window test tests/unit/test_window_defaults.py beside the S11 γ tariff half; both sidecars name timebase.py and the S6 names.
- S18 (from its PRD, L42): ε keeps the preview endpoint and wires it into the fleet page as a preview of the homes Run builds, through parse_fleet_form (D18 and the stream row keep it); builder presets saved in the old flat form are refused by name; the builder starts at the fleet page distributions; every home value, drawn ones included, is bounded by the component range and a distribution whose draw crosses it is refused naming the home; β takes the S21 form-label macro as number_field, carries no S21 key, and the next run re-verifies the form-label part of fk-ff5b90768f66 after β; 612 and 298 are parked deferred by the lead until the S18 decompose cancels them.
- S5, S7, S4, S17, S11, S2, S21, S22, S26, tasks (from S18): γ depends on 947 and replaces _DISTRIBUTION_SPEC_TYPES with a public DISTRIBUTION_TYPES in fleet_distribution.py; γ depends on 921 and 868, η on 911, 786, 839 and 841, β on 860 and 774, δ on 870, 937, 313 (in progress) and 394; the preview generates through 916; CHARGER_TYPES has no S18 reader; δ deletes the shape-only translator and its refusals raise ConfigurationError; 424 and 584 are superseded by δ; PageLimits.flat_rate_start is 0.28 on all three forms; no edge with 830 or 836, second lands rebases; β renders the assistant PV descriptions from the component range (overlap with 751); the sweep page parameter options come from the S26 registry and may read ComponentLimits.value_range, 140 keeps its scope; superseded at decompose: 376, 612, 664 -> β; 611, 753, 424, 592, 584, 360 -> δ; 569, 571 -> ε; 298, 359, 545, 549, 553, 554 -> ζ; 676 moves its dependency from 612 to β; 140 and 297 kept; S18 γ and δ (high) join gate 772.
- S26 (from its PRD, L43): 440 stays as narrowed and S26 δ depends on it, moving its reads into web/sweep_request.read_sweep_request and its overflow refusal into SweepSpec; the YAML placement table SWEEP_PLACEMENTS lives in fleet_distribution.py (the parser sits below config) and the registry scenario_knobs.py above it; fleet sweep --param resolves a knob name first, then a ${VAR}, refusing a name with both readings; 804 depends on S26 β and edits the scenario_knobs grid-services entry (FlatGridServices(v), NoGridServices() at 0), SENSITIVITY_BANDS keyed by Knob.
- S4, S5, S7, S8, S16, S17, S18, S19, S21, tasks (from S26): 868 SweepSpec number reads land before S26 α and 870 simulate_sweep reads before S26 δ; S26 α edits SweepSpec in fleet_distribution.py (typed mode, values(), finite points) and ζ adds SWEEP_PLACEMENTS and F7 there, refusals through scenario_blocks.refusal if 948 has landed; ζ joins the FleetDistributionConfig.__post_init__ checks after 921; S26 γ depends on 930 and 885 (sensitivity_panel takes the baseline RankedSweep, run_sweep loses its floor override); δ reads parameter and mode with read_string (938); web/sweep_request.SWEEP_PARAMETERS bounds each web sweep by FLEET_COMPONENTS fixed_range and reads the 807 steps constant, δ and ε depend on 807; ε depends on 835 (parameter_label rendered from SWEEP_PARAMETERS); 718 superseded by S26 γ, 140 by S26 ε; 739 delivers fk-32d5e6707fb5 and η depends on it.
- S6 (from S25): S25 γ depends on the S6 cli/finance reader leaf (label supplied by the lead at S6 decompose); S25 does not touch the cli/optimize.configs scenario.
- S8 (from S25): γ adds finance.own_use_basis and with_own_use_basis and home_ledger reads its basis through own_use_basis; δ adds FleetProjection.grid_services_income_gbp; β moves the two reports after 930; γ and β depend on 930.
- S9, S10, S27 (from S25): the 837 rows (p50, p90, displaced self-use) move into the δ Grid Services Income section and the flex row shows the booked figure, δ depends on 803; the 783 extrapolated notice moves with β and renders once per report, β depends on 783 and 837; δ replaces the S27 "(PRD §6)" planning pointer.
- S12, S16, S19, S21 (from S25): 897 per-load seasonal tables build on the calculate_seasonal_metrics aggregation (the other half of fk-ae20e1833a19), ε and 897 overlap textually; γ keeps the 890 reusing wrapper and the bill run simulates scenario_fleet(scenario).homes; ε and ζ each add a RunDocumentStep and depend on 822, the row helper stays in cli so run_headline does not delegate to it; no S25 rows for the 833 flow properties.
- S29 (from S25): release section includes S25 ζ (SummaryStatistics.seg_revenue_gbp retired, held) plus the Unreleased lines of β, γ, δ and ε (PRD §5.9).
- Tasks (from S25): 705 is re-scoped in place as S25 α (fk-2106d1fbaed0 plus fk-6a52ed98b18e stamped); 703 and 712 closed their keys (fk-89afcb2b57f7, fk-41767a1bc146); 738 keeps fk-f66948b9528c and γ finishes the mode half through 930; 741 keeps fk-b523bff3e51c and 930 rewrites its sweep-count sentence; 765 lands before β; the four moving board figures are recorded on γ and δ (D48).
- S12, S4, S16 (from S13 decompose): 894 depends on 906 (the hand-off leaf) and was released by the lead (commit_planning 2026-10-17, S12 β stamped); 573 is cancelled, its range rule superseded by 906 and its residual (the fleet_distribution.seed whole-number read) to 868; 746 is cancelled, superseded by 908 (S13 β), file overlap with S16 only; gate 772 depends on 906.
- Tasks (from S22 decompose): S22 α is 907 (depends on 818, 823); β is 751, re-scoped in place and retitled by the lead; 506 is cancelled with x_superseded_by 751; 440 is narrowed by the lead to api.simulate_sweep (L29) and its assistant item belongs to 751; whichever of 440 and 751 lands second adapts dispatch_tool; no S22 leaf is high.
- S2, S16, S29, tasks (from S27 decompose): 790 metadata.files gains community.py (done by the lead); 910 depends on 879, and 910 and 889 both edit the web/jobs.py fleet assembly, whichever lands second adapts (910 converts that site to tuples if 889 has not landed); 909 and 879/882 overlap textually in cli/fleet.py::run, load_community_config stays above the simulation; 669 lists five classes and no longer fleet.py or community.py; 706 is cancelled, superseded by 909; the α (909) and β (910) Unreleased lines land in-leaf, γ is 912, held, released by S29.
- S29, S15, tasks (from S23 decompose): η is 927 (deferred, x_seam_wait on the release commit that bumps the version and writes the one release section), depending on 926; the S29 bump leaf depends on 926 (ζ) and S29 adds 927 -> its release leaf before releasing it; α is 913 and deletes tests/unit/test_init_lazy_surface.py, 765 and 913 both edit the __init__ banner, second adapts; 668 depends on 926, carries fk-879e8c13f581 and has its files amended by the lead for the task-670 split; keys split by design: fk-879e8c13f581 -> 915 and 668, fk-ac70915ba435 -> 920 and 785, fk-dc5370224a78 -> 926 and 927; the fk-9df95e9e2b45 D28 re-measure is on 913; 915 (high) joins gate 772.
- Tasks (from S8 decompose): 350 -> 928, 581 -> 917, 690 and 715 -> 922, 720, 721 and 730 -> 929 cancelled with x_superseded_by; 582 went in progress when 350 was cancelled and is cancelled by Leo (D47) with x_superseded_by 930, its edges on 928 and 930 removed; 667 is re-scoped to the web chart and depends on 922; 287 (the --project SEG carve-out in cli/finance.run) gains an edge on 930 (L38); fk-62dbe0f34b68 stays on 702 and fk-9fa18977ec68 is absent (716 done); 922, 925 and 929 (high) join gate 772.
- S1, S6, S9, S10, S14, S16, S19, S25, S28, S29 (from S8 decompose): 928 deletes the finance -> battery, fleet, home and pv allow-list entries of 775 and adds a Transitional finance -> projection entry owned by 939, which deletes it at the bump; the S6 homes leaf depends on 928 (projection.scenario_fleet); 804 repoints grid_services_model_of in projection.py if 928 has landed and 929 keeps the annual_income_gbp call; 941 depends on 784 and the 782 own-use bound becomes ledger invariant L2 in 925; 936 depends on 812 and records the board capex figures at its base; 928 -> 885 and 837, 930 -> 890, 939 -> 892, 925 -> 782; the stored-run format covers SummaryStatistics.pricing (922); the S25 cli/finance.run restructure depends on 930 and 922 stops finance reading the SEG revenue pair; 865 and 928 share docstrings, second lands carries the text; the release section takes ι 939 and κ 941 plus the Unreleased lines of 922, 925, 928, 934 and 936.
- S7, S5, S18, S22 (from S17 decompose): 914 R1(3) and 933 both refuse a location: block missing a coordinate, second lands keeps one rule; the 914 when-omitted entry and 937 config.PV_CAPACITY_KW_WHEN_OMITTED end as one named constant; after 914 the 940 thermal_capacity_kw-required clause no longer holds and row H1 holds either way; S5 moves parse_location_block (933), parse_heat_pump_block (940) and PV_CAPACITY_KW_WHEN_OMITTED (937), order-agnostic, and 509 puts the one unrecognised-key rule where S5 puts refuse_unrecognised_keys; fleet_config refusals become ConfigurationError in 935 and option lists render from location.LOCATION_PRESETS (933); 424 is narrowed to fleet_config._require_dict; whichever of 751 and 935 lands second routes dispatch_tool refusals through refusal_text, 770 is re-pointed to 937.
- S16, S19, S20, tasks (from S17 decompose): θ 942 depends on 889 and moves the accessors to web/dashboard.py, later accessors (S19 get_database, S20 policy) land there and not in shared.py; 938 types the fleet name str | None if 817 has deleted the fleet default; 245 -> 940, 755 -> 937, 331, 517 and 560 -> 938 cancelled; 509 depends on 935 with its premise re-pointed; fk-5827f41eb082 lives on 938 only (L36 corrected: the store had no key on 517); 297 is high, on gate 772, and its files are corrected by the lead (tests/unit/web_api/test_fleet_distribution.py replaces the deleted tests/unit/test_web_api.py); 935 (high) joins gate 772.
- Tasks, S4, S14, S18, S26, S28, S29 (from S7 decompose): 610 depends on 914 (was 283); 599 -> 914, 662 -> 916, 403 -> 916 and 919, 600 -> 919, 283 -> 914 and 919 cancelled; 868 has no edge on 921 (file locks), whichever lands second reads the number and count outcomes at the ε F3 check, and the 868 EV-hour rounding regenerates the 916 goldens; 866 wraps the 914 reader construction in _constructed; 825 config.py bullets are void after 914 and 919; S18 depends on 921, with heat-pump options from 911, the charger list from 919 and the preview through the 916 sampler; the S26 battery-capacity knob reads ComponentDistribution.draws after 919; the S28 efficiency retirement edits the 914 battery row; the S29 release lists the two defaults 914 adds and the wider fleet grammar of 919; 584 (web fleet-from-distribution spec invariants) depends on 921 and 935 and goes to the S18 decompose as a pre-existing task (L38); 914, 919 and 921 (high) join gate 772.
- S5 (from its PRD, L37): layout: scenario_blocks.py = every reader of a domain-module value (finance, SEG and community included); fleet_distribution.py = distribution grammar, sampler and sweep expansion; config.py = documents, SimulationPeriod, ScenarioConfig, substitution and loaders; the S5 row deletable names the templates dead output: keys only, since D11 keeps period:; β and γ are filed high (L37) so gate 772 sees the chain to 866 and 868.
- S4 (from S5): 866 depends on S5 β and is released by the S5 decompose (commit_planning on 866 after the edge); 868 depends on S5 γ; S5 δ depends on 866 and 868.
- S6 (from S5): depends on S5 γ and ε; the _parse_scenario unknown-key refusal lands in S5 ε; S6 owns the top-level keys of the home file and of single-scenario documents and decides ScenarioConfig.tariff_config (a typed tariff: under D10 fill-and-refuse, or S5 ζ retires it with output).
- S7 (from S5): _modify_pv_config, _modify_battery_config and _modify_load_config are deleted by S5 α, not edited by S7; S5 β and γ depend on every S7 leaf whose files include src/solar_challenge/config.py (L37), S7 takes no edge on S5.
- S18, S26 (from S5): depend on S5 γ (the per-type table and SweepSpec live in fleet_distribution.py); the S26 web/api.simulate_sweep leaf carries fk-59fdc80fdded.
- S17 (from S5): task 509 depends on S5 δ; the location: block tightening S17 γ makes moves with S5 β.
- S29 (from S5): release section includes S5 ζ (ScenarioConfig.output and OutputConfig retired; tariff_config too unless S6 claims it).
- Tasks (from S5): 320 and 651 superseded by S5 α and 423 by S5 δ at decompose (step-1 lookup first; 237 per D46); 509 gains an edge on δ; metadata.files of γ cover CLAUDE.md, review/briefing.yaml and tests/unit/test_import_structure.py, β cli/home.py, ε cli/config.py, ζ tests/unit/test_public_api_surface.py.
- S5 (from S7, S4, S17): the partition moves S7 component tables with the block readers to scenario_blocks.py and ComponentDistribution, the kind rules and the sampler to fleet_distribution.py; the partition leaf depends on 860 (S4 α) and 866 (S4 ε) depends on it and is released by the S5 session; S5 moves the location: block S17 γ tightens; S5 supersedes 237 and 320 and closes the sweep halves of fk-148991ab9439 and fk-d2b4045c6676.
- S14 (from S7): 825 config.py bullets are void once S7 β and δ land; its writer bullet becomes one writer rule, every key, null when unset; B6 asserts config equality.
- S4 (from S7, S9): ζ reads number/count spec values at S7 ε per-kind check and its EV-hour rounding regenerates S7 γ goldens; S9 leaves adding numeric input types read through number_fields (edge -> 860) else 872 converts stragglers.
- S18 (from S7, S4): the per-type table reads S7 kind -> accepted spec types and the fleet rows, the preview samples through S7 γ sampler, option lists render from heat_pump.HEAT_PUMP_TYPES and ev.CHARGER_TYPES; depends on S7 ε and 870 (S4 η).
- S17 (from S4, S7, S20): depends on 861, 862, 864, 870; the web heat-pump block and PV defaults defer to the dataclass defaults after S7 β; the S20 policy accessor sits beside get_job_manager and moves with it.
- S26 (from S7): after S7 δ the battery-capacity knob replaces ComponentDistribution.draws capacity_kwh.
- S28 (from S7): the efficiency retirement edits S7 battery table row and deletes the scenario_writer efficiency exception in the same change.
- S29 (from S7, S8, S4): release section lists S7 β added defaults and widened fleet grammar, S8 ι (solve module repoint) and κ (BillDistribution rename) held, and no S4 lines (S4 exports no checker).
- S19, S21, S16, S17 (from S20): 883 sets the cancel flag before Future.cancel() in 819; 888 renames complete to completed and 835 reads JobState.run_id; JobStreamPolicy is one more create_app collaborator following S16 injection form.
- S3 (from S4): engine-check leaves depend on 860; fk-a9c609ecb8ef closes when 872 and S3 δ (902) land.
- Tasks (from S8): 350, 581, 582, 690, 715, 720, 721, 730 superseded at decompose; 667 re-scoped. Tasks (from S17): 331, 517, 560, 245, 755 superseded; 424 narrowed; 297 raised to high with fk-a0866b1bd680.
- All streams (from S23): the frozen tables stay in tests/unit/test_public_api_surface.py, one row per line; after S23 α no surface count exists; after ε rows spell the evaluated annotation and a stale row fails the merge verify printing its current form; after ζ each drift is labelled additive or breaking, and a leaf whose own edit prints breaking is a held leaf for S29.
- S29 (from S23): the bump leaf depends on S23 ζ and its release section names every breaking entry the lock reports; the release commit releases S23 η.
- S15 (from S23): after S23 α there is no literal surface count for 808 to raise; S23 α deletes tests/unit/test_init_lazy_surface.py (tasks 515, 808, 827 adjust); task 765 and S23 α both touch the __init__ banner, second lands adapts.
- S12 (from S13): β binds to generate_load_profile(..., *, household_model: HouseholdModel = richardsonpy_household), a factory called once per window returning a DaySimulator called once per local date (1,440 W values); S13 α moves the run_application_simulation counters and the power_sim patch onto the seam and leaves the fallback try scope to S12 β.
- S4 (from S13): the §10 row for task 573 reads superseded by S13 α for the range rule; LoadConfig.seed bool and fraction refusal stays S4 β; fleet_distribution.seed whole-number read stays S4 ζ.
- S16 (from S13): task 746 is superseded by S13 β (fleet_home_seed and the seed keyword on both constructors); file overlap only.
- Invariant 3 (from S13): the checkable middle clause becomes two unseeded profiles, each generated right after the same seeded profile, differ; tests tests/unit/test_load_reproducibility.py and tests/unit/web_jobs/test_seeded_jobs_reproduce.py.
- S2 (from S27): S27 α depends on 786 and 787; S2 ε (790) also drops community._battery_strategy or-SelfConsumptionStrategyConfig default (file list gains community.py).
- S16 (from S27): S27 β depends on S16 α (one FleetResults assembly); S27 α moves load_community_config above the simulation in cli/fleet.py::run (file overlap).
- S3, S11 (from S27): the community battery goes through simulate_timestep(..., tariff=) and S11 β reaches it through S27 α; no edge.
- S25 (from S27): output.py flexibility-value block renders a planning pointer (PRD §6) into the board report; S25 owns the report text.
- S29 (from S27): release section includes S27 §5.5; γ held (CommunityConfig.sharing_mode becomes a derived property, the YAML key retired).
- S14 (from S22): δ (818) produces the three validation.UK_* constants; S22 owns the reading rule and adds validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP (the docs/pv-cell-temperature.md figure of 823); S22 α depends on 818 and 823.
- S19 (from S22): S22 β (751) puts the tools collaborators in one ToolContext; whichever of 751 and 806/816 lands second edits ToolContext fields and handler bodies, no edge.
- S4 (from S22): β reads the assistant numbers through the shared readers wherever main holds them.
- Tasks (from S22): 506 superseded by 751; 440 narrowed to api.simulate_sweep; fk-ab16fff6f6c3 closed by 713.
- S2 (from S3): 790 (ε) depends on S3 ε (which deletes _runs_tariff_tou, _tariff_tou_timestep and the tariff-TOU branch of _dispatch_path); S3 ε does not depend on 790; S3 α depends on 786 and 788, S3 β on 788, S3 ε on 787 and 839; L15 corrected.
- S4 (from S3): S3 δ bounds go through Interval.admits and NON_NEGATIVE (S4 α) and raise ValueError (computed values).
- S19 (from S12): the S19 PRD §8 row for S12 drops the frame-transform clause; S12 ζ is summary-only.
- S13 (from S12): S12 β is held on the S13 hand-off leaf and follows its shape of the injectable per-day simulator.
- S21 (from S12): the per-named-load panel leaf depends on 832 (ChartPanel); S25: SummaryStatistics flow properties land in 833; S20 shares parameter-sweep.js with 835 (file overlap only).
- S9 (from S16): fleet.reusing in cli/finance.run cuts the age-0 simulations from four to one on unaged scenarios; aged scenarios and optimize keep theirs (S8).
- S20 (from S19, S16): β -> 806, 819, 822; δ -> 814; α -> 713; the policy injection form follows S16 if it has landed.
- S8 (from S9 decompose): the project_multi_year move leaf depends on 801 (S9 α) and 802 (S9 β).
- S25 (from S9 decompose, D41): the cli/finance.run restructure leaf depends on 802 and 803; the events income renders with its delivery baseline, the 50%/90% availability and the displaced evening self-use beside it.
- S26 (from S9 decompose): the grid-services knob builds FlatGridServices(v) at 804 (S9 ε); 804 edits the registry entry if S26 has landed.
- S4 (from S14 decompose): β depends on 825 (S14 ζ); S22 derives its PV facts from 818 and 823; S29 releases 826.
- S16 (from S15 decompose): the runner leaf depends on 809 (S15 β); S29 releases 827.
- S19 (from its decompose): 784 and 790 depend on 822; S28 γ -> 822; S21 panels -> 822 and 814, comparison -> 816; S20 -> 806, 819, 814, 822.
- S9 (D41): new leaf α′ (firmness per event day under a named delivery baseline) between 801 and 802; a successor PRD for the counterfactual event simulation follows it.
- S5 (from S4): the config.py partition depends on S4 α (Interval and the checker at the package leaf); S4 ε depends on the partition; S5 moves nothing of ε or ζ.
- S3 (from S4): the engine checks (dispatch, flow, battery) go through Interval.admits and depend on S4 α; fk-a9c609ecb8ef closes when S4 ι and S3 land.
- S18 (from S21): the form-label macro is offered to S18; invariant 11 window half beside S11 γ.
- S19 (from S28, S21): the S28 γ migration step and the S21 panel changes depend on the S19 format-version leaf; the lead adds the edges when S19 files.
- S29 (from S4, S21, S24, S28): release section includes S28 (efficiency field retired, held), S4 (public checker names), S24 (raised floors are not surface) and S21 (none).
- Tasks (from S21): 123, 135, 129, 456, 492, 565, 575, 629, 628, 735, 737 are superseded at S21 decompose; 153 keeps api.py; 691 and 736 keep their serialising edges.
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
- Board figures that move (for the board): S8 θ physics capex falls 2.22% (£9,551 at £1,000/kWp on bristol-phase1) for PV the simulator never wires; S8 ε per-year revenue between projection nodes by up to £41-150; S3 γ bus-energy settlement (D42); S11 preset re-pricing (D34/D44); S14 NOCT-SAM +1.9% yield (D32); S9 α′ events income (D41); S25 γ mode semantics (spreadsheet mode renders the override economics and solved rate, both gains Spreadsheet columns) and δ flex-block grid-services row from £30 per home to about £3 per battery home on bristol-phase1-flex.yaml (D48); S6 (D10, D11 consequences, L41): fleet run books SEG export revenue on the five shipped fleet files carrying a seg: block (today £0.00) and home run on bristol-arbitrage.yaml simulates its one-day period instead of all of 2024.
- Candidate finding for the next run (S3 Q6): self-consumption accounting of grid-charged discharge. Task 183 stays deferred: a revival re-plans its oracle grid-charge ceiling as an input of TOUOptimizedStrategy on the one engine (L25). Housekeeping: worktrees .worktrees/123, 492, 680, 283, 403 and 582 and the empty branches of 382, 314, 187 belong to cancelled tasks (S21, S20, S4, S7 decomposes; D47); keep .worktrees/.task-meta/{283,403}/plan.json, cited by 914, 916 and 919. Branch task/237 is unmerged and superseded by 945 (D46); task/582 by 930 (D47). Empty task/* branches and worktrees of 185, 186, 325, 422, 485 and 541 belong to tasks the S6 decompose cancelled. .worktrees/718 belongs to 718, cancelled at the S26 decompose.
- Follow-up candidates (not filed): a PVConfig mounting field for NOCT-SAM (S14 Q5, after 823); the finance capex basis, nameplate vs wired DC (S8, fk-8b8f9d686b86); the counterfactual event-simulation PRD after S9 α′ (D41); the D3 mid-term design follow-up (grid charging in every dispatcher) after S3 and S11 land (L8); sharing the per-mode projection node simulations under --assumptions both, which needs an S8 contract change (S25 Q4, L39, after 929); the fleet import loading a scenario-level location, the S17 out-of-scope pointer to S6 that S6 did not take because the fleet page has no location control (S6 Q4, L41: an S18 follow-up candidate, not filed).
- Instrument debt: none (both siblings ran whole in Phase 2); the dark-factory snapshot instrument needs task 6921 before the next run can measure this repo without the shim.

## FILED — program status

| Stream | PRD | Task id | Finding keys | Severity |
|---|---|---|---|---|
| (Phase 5 mechanical) | — | see report §Mechanical filings | 69 keys: 53 filed as tickets, 13 already covered, 3 left open (weakened) | mixed |
| S29 β | docs/prds/surface-version-bump.md | 224 (pending) |  | medium |
| S25 α | docs/prds/board-reports-sections-by-mode.md | 705 (pending) | fk-2106d1fbaed0 fk-6a52ed98b18e | medium |
| S22 β | docs/prds/assistant-facts-from-engine.md | 751 (pending) | fk-93d3bd7aa219 | low |
| S1 α | docs/prds/errors-leaf.md | 773 (done) | fk-601c5b5f6415 fk-4435376bedb3 fk-da69830bb2d6 | medium |
| S1 β | docs/prds/errors-leaf.md | 774 (pending) | fk-291910b552af fk-da69830bb2d6 | medium |
| S1 γ | docs/prds/errors-leaf.md | 775 (in-progress) | fk-601c5b5f6415 | medium |
| S10 α | docs/prds/simulation-window-and-cadence.md | 777 (done) | fk-7ef1099d24e8 fk-d63c41ca13f9 | medium |
| S10 β | docs/prds/simulation-window-and-cadence.md | 778 (in-progress) | fk-1cd332300623 fk-d63c41ca13f9 | medium |
| S10 γ1 | docs/prds/simulation-window-and-cadence.md | 779 (pending) | fk-7ef1099d24e8 | low |
| S10 γ2 | docs/prds/simulation-window-and-cadence.md | 780 (pending) | fk-7ef1099d24e8 fk-d63c41ca13f9 | medium |
| S10 δ | docs/prds/simulation-window-and-cadence.md | 781 (pending) | fk-d63c41ca13f9 | medium |
| S10 ε | docs/prds/simulation-window-and-cadence.md | 782 (pending) | fk-1cd332300623 fk-d63c41ca13f9 fk-286fe17c28c9 | medium |
| S10 ζ | docs/prds/simulation-window-and-cadence.md | 783 (pending) | fk-1cd332300623 fk-d63c41ca13f9 | medium |
| S10 η | docs/prds/simulation-window-and-cadence.md | 784 (pending) | fk-286fe17c28c9 fk-7ef1099d24e8 fk-1cd332300623 | medium |
| S2 α | docs/prds/dispatch-configuration-below-config.md | 786 (pending) | fk-b3dfd41a4d6a fk-615cbc883512 fk-370b3e49b67c fk-c36d6fcbc2a8 fk-94f4881bbe48 fk-04b52ee632c6 | medium |
| S2 β | docs/prds/dispatch-configuration-below-config.md | 787 (pending) | fk-fc652220a4d3 fk-94f4881bbe48 fk-04b52ee632c6 | medium |
| S2 γ | docs/prds/dispatch-configuration-below-config.md | 788 (pending) | fk-8529726bbd6b fk-99244625d7f2 fk-f126b1c9cbbe | high |
| S2 δ | docs/prds/dispatch-configuration-below-config.md | 789 (pending) | fk-f126b1c9cbbe | high |
| S2 ε | docs/prds/dispatch-configuration-below-config.md | 790 (pending) | fk-94f4881bbe48 fk-04b52ee632c6 | medium |
| S9 α | docs/prds/grid-services-pricing-model.md | 801 (pending) | fk-758b2f309cab fk-4ddab794283a | medium |
| S9 β | docs/prds/grid-services-pricing-model.md | 802 (pending) | fk-aafe32daa988 fk-d432a549b03f | medium |
| S9 γ | docs/prds/grid-services-pricing-model.md | 803 (pending) | fk-0f24b7f66eb2 fk-aafe32daa988 | medium |
| S9 ε | docs/prds/grid-services-pricing-model.md | 804 (pending) | fk-aafe32daa988 fk-d432a549b03f | medium |
| S19 α | docs/prds/run-store-one-owner.md | 805 (pending) | fk-bfdae4525795 | medium |
| S19 β | docs/prds/run-store-one-owner.md | 806 (pending) | fk-bfdae4525795 fk-df9d0fc1b2d3 fk-9d7f66fdcfdd fk-c14c02dc1b77 | medium |
| S19 η | docs/prds/run-store-one-owner.md | 807 (pending) | fk-2ac79d7a1989 fk-9d7f66fdcfdd | medium |
| S15 α | docs/prds/weather-as-explicit-input.md | 808 (pending) | fk-06035cd76226 fk-44fdf5fb356b | medium |
| S15 β | docs/prds/weather-as-explicit-input.md | 809 (pending) | fk-44fdf5fb356b fk-06035cd76226 | medium |
| S14 β | docs/prds/pv-model-one-home.md | 810 (pending) | fk-616cc076b7cb fk-3ccbba41d836 | medium |
| S19 δ | docs/prds/run-store-one-owner.md | 811 (pending) | fk-df9d0fc1b2d3 fk-bfdae4525795 | medium |
| S14 γ | docs/prds/pv-model-one-home.md | 812 (pending) | fk-a98db49f3fd7 fk-8b8f9d686b86 | medium |
| S15 γ | docs/prds/weather-as-explicit-input.md | 813 (pending) | fk-44fdf5fb356b fk-06035cd76226 | medium |
| S19 ε | docs/prds/run-store-one-owner.md | 814 (pending) | fk-81e62b2640a7 | medium |
| S15 δ | docs/prds/weather-as-explicit-input.md | 815 (pending) | fk-e4549a3a6b54 | low |
| S19 γ | docs/prds/run-store-one-owner.md | 816 (pending) | fk-a37ed16d59c5 fk-34a6679f1ef3 fk-df9d0fc1b2d3 fk-9d7f66fdcfdd fk-bfdae4525795 | high |
| S19 ζ | docs/prds/run-store-one-owner.md | 817 (pending) | fk-2ff305a1dbb2 | low |
| S14 δ | docs/prds/pv-model-one-home.md | 818 (pending) | fk-835a87838a52 fk-8b8f9d686b86 | medium |
| S19 θ | docs/prds/run-store-one-owner.md | 819 (pending) | fk-8f4f4d63f917 | medium |
| S19 λ | docs/prds/run-store-one-owner.md | 820 (pending) | fk-e29393df0cd4 | low |
| S19 ι | docs/prds/run-store-one-owner.md | 821 (pending) | fk-1070454e4c6e | medium |
| S19 κ | docs/prds/run-store-one-owner.md | 822 (pending) | fk-273b8b09c91a fk-a37ed16d59c5 | high |
| S14 ε | docs/prds/pv-model-one-home.md | 823 (pending) | fk-f5cd69400ce6 fk-0edf0069c6bb | high |
| S19 μ | docs/prds/run-store-one-owner.md | 824 (pending) | fk-df9d0fc1b2d3 fk-bfdae4525795 | medium |
| S14 ζ | docs/prds/pv-model-one-home.md | 825 (pending) | fk-f5cd69400ce6 fk-0edf0069c6bb | high |
| S14 η | docs/prds/pv-model-one-home.md | 826 (pending) | fk-3ccbba41d836 | medium |
| S15 ε | docs/prds/weather-as-explicit-input.md | 827 (pending) | fk-06035cd76226 fk-44fdf5fb356b | medium |
| S21 α | docs/prds/chart-panels-and-theme-tokens.md | 829 (pending) | fk-93ee9a05751a | medium |
| S21 β | docs/prds/chart-panels-and-theme-tokens.md | 830 (pending) | fk-93ee9a05751a fk-2e7ddcee2379 | medium |
| S21 γ | docs/prds/chart-panels-and-theme-tokens.md | 831 (pending) | fk-93ee9a05751a fk-55f4e4ea396d | medium |
| S21 δ | docs/prds/chart-panels-and-theme-tokens.md | 832 (pending) | fk-42c0053b9a2b fk-ff5b90768f66 fk-8f26d000b68d fk-3239afd8ce6b | high |
| S21 ε | docs/prds/chart-panels-and-theme-tokens.md | 833 (pending) | fk-8e109704aa24 | medium |
| S21 ζ | docs/prds/chart-panels-and-theme-tokens.md | 834 (pending) | fk-3239afd8ce6b fk-8e109704aa24 | medium |
| S21 η | docs/prds/chart-panels-and-theme-tokens.md | 835 (pending) | fk-55f4e4ea396d | medium |
| S21 θ | docs/prds/chart-panels-and-theme-tokens.md | 836 (pending) | fk-ff5b90768f66 | medium |
| S9 α′ | docs/prds/grid-services-pricing-model.md | 837 (pending) | fk-758b2f309cab fk-4ddab794283a | medium |
| S11 α | docs/prds/tariff-coverage-classifier-presets.md | 838 (pending) | fk-872021ade9b6 fk-2f88003e22c8 | medium |
| S11 β | docs/prds/tariff-coverage-classifier-presets.md | 839 (pending) | fk-4872e7ab367e | medium |
| S21  | docs/prds/chart-panels-and-theme-tokens.md | 840 (cancelled) | fk-657669b23e71 | low |
| S11 γ | docs/prds/tariff-coverage-classifier-presets.md | 841 (pending) | fk-463e82417506 | medium |
| S11 δ | docs/prds/tariff-coverage-classifier-presets.md | 842 (pending) | fk-bd03fe349ffd | medium |
| S11 ε | docs/prds/tariff-coverage-classifier-presets.md | 843 (pending) | fk-2f88003e22c8 | medium |
| S4 α | docs/prds/finite-quantities.md | 860 (pending) | fk-a9c609ecb8ef fk-649851e5fc38 | high |
| S4 β | docs/prds/finite-quantities.md | 861 (pending) | fk-a9c609ecb8ef fk-606a9211b34d fk-7dcdc5559d22 fk-a2b33a420bcf | high |
| S4 γ | docs/prds/finite-quantities.md | 862 (pending) | fk-b69968a37b36 fk-606a9211b34d | medium |
| S28 α | docs/prds/battery-efficiency-and-throughput.md | 863 (pending) | fk-35b8ddcf5565 | medium |
| S4 δ | docs/prds/finite-quantities.md | 864 (pending) | fk-a9c609ecb8ef fk-606a9211b34d | high |
| S28 β | docs/prds/battery-efficiency-and-throughput.md | 865 (pending) | fk-50a3985fae0f | medium |
| S4 ε | docs/prds/finite-quantities.md | 866 (pending) | fk-649851e5fc38 fk-a2b33a420bcf | high |
| S28 γ | docs/prds/battery-efficiency-and-throughput.md | 867 (pending) | fk-35b8ddcf5565 | medium |
| S4 ζ | docs/prds/finite-quantities.md | 868 (pending) | fk-649851e5fc38 fk-60410de6dd0a fk-a2b33a420bcf | high |
| S4 η | docs/prds/finite-quantities.md | 870 (pending) | fk-60410de6dd0a fk-239274130a5a | high |
| S4 θ | docs/prds/finite-quantities.md | 871 (pending) | fk-f2f8a5512feb fk-a9c609ecb8ef | high |
| S4 ι | docs/prds/finite-quantities.md | 872 (pending) | fk-a9c609ecb8ef fk-606a9211b34d fk-b69968a37b36 | high |
| S24 α | docs/prds/lane-harness-one-collection-source.md | 873 (in-progress) | fk-dd434cb2d4b9 | low |
| S24 β | docs/prds/lane-harness-one-collection-source.md | 874 (pending) | fk-1abd62632ae1 fk-a0b751097301 | medium |
| S24 γ | docs/prds/lane-harness-one-collection-source.md | 875 (pending) | fk-f48c29a98a89 fk-eec3806e584e | medium |
| S24 ε | docs/prds/lane-harness-one-collection-source.md | 877 (pending) | fk-e5820c5e22ed | high |
| S16 α | docs/prds/fleet-execution-policy.md | 879 (pending) | fk-7e76b4cf2cb2 fk-f7b19fc4c8b5 fk-f3a20a6d53e0 | medium |
| S20 α | docs/prds/job-events-and-sse-framing.md | 880 (pending) | fk-066e5cb461f7 | low |
| S24 δ | docs/prds/lane-harness-one-collection-source.md | 881 (pending) | fk-3667e4e32155 | low |
| S16 β | docs/prds/fleet-execution-policy.md | 882 (pending) | fk-f3a20a6d53e0 fk-d89ee8df893c fk-cc292d7ce407 fk-7e76b4cf2cb2 | medium |
| S20 β | docs/prds/job-events-and-sse-framing.md | 883 (pending) | fk-484952247bb6 | high |
| S24 ζ | docs/prds/lane-harness-one-collection-source.md | 884 (pending) | fk-5de02e56b3af | low |
| S16 γ | docs/prds/fleet-execution-policy.md | 885 (pending) | fk-7e76b4cf2cb2 | medium |
| S20 γ | docs/prds/job-events-and-sse-framing.md | 886 (pending) | fk-4540d657bff6 | medium |
| S24 η | docs/prds/lane-harness-one-collection-source.md | 887 (pending) | fk-a9aad5f6d1b2 | low |
| S20 δ | docs/prds/job-events-and-sse-framing.md | 888 (pending) | fk-7eb56fda0b1c fk-0097b5aaa45c fk-066e5cb461f7 | high |
| S16 δ | docs/prds/fleet-execution-policy.md | 889 (pending) | fk-7bdd33abd0ff fk-f6c905f91d32 fk-7aaa879bf0ac fk-7e76b4cf2cb2 | medium |
| S16 ε | docs/prds/fleet-execution-policy.md | 890 (pending) |  | medium |
| S24 θ | docs/prds/lane-harness-one-collection-source.md | 891 (pending) | fk-eec3806e584e | medium |
| S16 ζ | docs/prds/fleet-execution-policy.md | 892 (pending) | fk-7e76b4cf2cb2 | medium |
| S12 α | docs/prds/load-composition-and-calendar-days.md | 893 (pending) | fk-1d920c89e872 | high |
| S12 β | docs/prds/load-composition-and-calendar-days.md | 894 (pending) | fk-1d920c89e872 fk-89777ec9faad fk-72af0b90338d | high |
| S12 γ | docs/prds/load-composition-and-calendar-days.md | 895 (pending) | fk-1d920c89e872 fk-7fa120a8bb98 fk-781d153ab978 | high |
| S3 α | docs/prds/one-dispatch-engine.md | 896 (pending) | fk-491014934d1e | medium |
| S12 δ | docs/prds/load-composition-and-calendar-days.md | 897 (pending) | fk-781d153ab978 fk-1609d8c3d091 | medium |
| S3 β | docs/prds/one-dispatch-engine.md | 898 (pending) | fk-4df47ebe6a96 | medium |
| S12 ε | docs/prds/load-composition-and-calendar-days.md | 899 (pending) | fk-781d153ab978 | medium |
| S3 γ | docs/prds/one-dispatch-engine.md | 900 (pending) | fk-7440003fdd59 | high |
| S12 ζ | docs/prds/load-composition-and-calendar-days.md | 901 (pending) | fk-781d153ab978 fk-7fa120a8bb98 | medium |
| S3 δ | docs/prds/one-dispatch-engine.md | 902 (pending) | fk-2a53ae89932e fk-f622bbaa9f2e fk-a9c609ecb8ef | high |
| S3 ε | docs/prds/one-dispatch-engine.md | 904 (pending) | fk-4df47ebe6a96 | medium |
| S3 ζ | docs/prds/one-dispatch-engine.md | 905 (pending) | fk-4df47ebe6a96 | medium |
| S13 α | docs/prds/rng-hand-off.md | 906 (pending) | fk-16df1a7ac416 fk-c78416de5500 | high |
| S22 α | docs/prds/assistant-facts-from-engine.md | 907 (pending) | fk-194e5b40da23 | medium |
| S13 β | docs/prds/rng-hand-off.md | 908 (pending) | fk-e0e34ef46058 | low |
| S27 α | docs/prds/community-dispatch-from-factory.md | 909 (pending) | fk-664e2030921e | medium |
| S27 β | docs/prds/community-dispatch-from-factory.md | 910 (pending) | fk-8995288451e6 | low |
| S7 α | docs/prds/component-defaults-one-home.md | 911 (pending) | fk-d6f16d95b126 | low |
| S27 γ | docs/prds/community-dispatch-from-factory.md | 912 (pending) | fk-083990041fdc | low |
| S23 α | docs/prds/surface-lock-one-module.md | 913 (pending) | fk-293a1282ace4 fk-9df95e9e2b45 | low |
| S7 β | docs/prds/component-defaults-one-home.md | 914 (pending) | fk-2b16cc8bcf46 fk-d2b4045c6676 fk-148991ab9439 fk-dfeefbe95640 | high |
| S23 β | docs/prds/surface-lock-one-module.md | 915 (pending) | fk-879e8c13f581 | high |
| S7 γ | docs/prds/component-defaults-one-home.md | 916 (pending) | fk-f2e1ad46df4b | medium |
| S8 α | docs/prds/finance-partition.md | 917 (pending) | fk-6cd8a932665c fk-3f4daea21220 | medium |
| S23 γ | docs/prds/surface-lock-one-module.md | 918 (pending) | fk-ca5301a6f39f | medium |
| S7 δ | docs/prds/component-defaults-one-home.md | 919 (pending) | fk-0e58e2a7e007 fk-148991ab9439 fk-dfeefbe95640 | high |
| S23 δ | docs/prds/surface-lock-one-module.md | 920 (pending) | fk-ac70915ba435 | low |
| S7 ε | docs/prds/component-defaults-one-home.md | 921 (pending) | fk-0e58e2a7e007 fk-f2e1ad46df4b | high |
| S8 β | docs/prds/finance-partition.md | 922 (pending) | fk-52fa98174363 fk-50cf1dd5df58 | high |
| S23 ε | docs/prds/surface-lock-one-module.md | 924 (pending) | fk-d2881616c782 | medium |
| S8 γ | docs/prds/finance-partition.md | 925 (pending) | fk-caeaf35c8151 fk-c2c9277c1920 fk-9cc706d3afdd | high |
| S23 ζ | docs/prds/surface-lock-one-module.md | 926 (pending) | fk-dc5370224a78 | low |
| S23 η | docs/prds/surface-lock-one-module.md | 927 (pending) | fk-dc5370224a78 | low |
| S8 δ | docs/prds/finance-partition.md | 928 (pending) | fk-b0f648b0e6d0 fk-41283f42a36a fk-5fdb04305288 fk-9cc706d3afdd | medium |
| S8 ε | docs/prds/finance-partition.md | 929 (pending) | fk-c0e0ae3dcca8 fk-5b34adae950b | high |
| S8 ζ | docs/prds/finance-partition.md | 930 (pending) | fk-4a9af7c31a4f fk-3b0a239d0489 | medium |
| S17 α | docs/prds/web-request-boundary.md | 931 (pending) | fk-66f886576b3f fk-0593b530a371 | medium |
| S17 β | docs/prds/web-request-boundary.md | 932 (pending) | fk-bd7f2abebeba | low |
| S17 γ | docs/prds/web-request-boundary.md | 933 (pending) | fk-1d143fefefed fk-0593b530a371 | medium |
| S8 η | docs/prds/finance-partition.md | 934 (pending) | fk-808be5588896 | medium |
| S17 δ | docs/prds/web-request-boundary.md | 935 (pending) | fk-6c98ee030531 fk-a0866b1bd680 fk-da0e3a4df6e7 | high |
| S8 θ | docs/prds/finance-partition.md | 936 (pending) | fk-8b8f9d686b86 | medium |
| S17 ε | docs/prds/web-request-boundary.md | 937 (pending) | fk-29af8a4fe018 fk-ba29e186122f | medium |
| S17 ζ | docs/prds/web-request-boundary.md | 938 (pending) | fk-da0e3a4df6e7 fk-5827f41eb082 | medium |
| S8 ι | docs/prds/finance-partition.md | 939 (pending) | fk-5fdb04305288 | medium |
| S17 η | docs/prds/web-request-boundary.md | 940 (pending) | fk-70edc755ede4 | medium |
| S8 κ | docs/prds/finance-partition.md | 941 (pending) | fk-3f4daea21220 | medium |
| S17 θ | docs/prds/web-request-boundary.md | 942 (pending) | fk-bd7f2abebeba | low |
| S17 κ | docs/prds/web-request-boundary.md | 943 (pending) | fk-6c98ee030531 fk-1d143fefefed fk-66f886576b3f | medium |
| S9  | docs/prds/grid-services-pricing-model.md | 944 (pending) |  | medium |
| S5 α | docs/prds/scenario-grammar-partition.md | 945 (pending) | fk-59fdc80fdded fk-caad5305a3be | medium |
| S5 β | docs/prds/scenario-grammar-partition.md | 946 (pending) | fk-62821dcde535 fk-2dc9d1cd2c06 | high |
| S5 γ | docs/prds/scenario-grammar-partition.md | 947 (pending) | fk-62821dcde535 fk-2dc9d1cd2c06 fk-59fdc80fdded | high |
| S5 δ | docs/prds/scenario-grammar-partition.md | 948 (pending) | fk-e2aaf2bfe651 | medium |
| S5 ε | docs/prds/scenario-grammar-partition.md | 949 (pending) | fk-897e13f84164 | medium |
| S5 ζ | docs/prds/scenario-grammar-partition.md | 950 (pending) | fk-897e13f84164 | medium |
| S6 α | docs/prds/one-scenario-reader.md | 955 (pending) | fk-8047de9b6789 fk-188af6c13d71 fk-0b791f2be2d6 fk-81d0840d19e2 | high |
| S6 β | docs/prds/one-scenario-reader.md | 956 (pending) | fk-be5b13274bcb fk-f99038047a27 | medium |
| S6 γ | docs/prds/one-scenario-reader.md | 957 (pending) | fk-3be3240278ee fk-2264bc150fa3 fk-a391cf1f4edf | high |
| S6 δ | docs/prds/one-scenario-reader.md | 958 (pending) | fk-416eb5643e7a fk-2264bc150fa3 fk-e756dab8077e | high |
| S6 ε | docs/prds/one-scenario-reader.md | 959 (pending) | fk-f99038047a27 fk-be5b13274bcb fk-81d0840d19e2 | high |
| S6 ζ | docs/prds/one-scenario-reader.md | 960 (pending) | fk-be5b13274bcb | medium |
| S6 η | docs/prds/one-scenario-reader.md | 961 (pending) | fk-a391cf1f4edf fk-ad65ad5e4e48 | medium |
| S6 θ | docs/prds/one-scenario-reader.md | 962 (pending) | fk-3be3240278ee fk-2264bc150fa3 fk-be5b13274bcb | high |
| S6 ι | docs/prds/one-scenario-reader.md | 963 (pending) | fk-be5b13274bcb | medium |
| S26 α | docs/prds/sweep-knob-registry.md | 964 (pending) | fk-59fdc80fdded fk-4cc34de4e649 | medium |
| S26 β | docs/prds/sweep-knob-registry.md | 965 (pending) | fk-4cc34de4e649 | medium |
| S26 γ | docs/prds/sweep-knob-registry.md | 966 (pending) | fk-3ca00f8edeb8 fk-0b4f5e04067c fk-4cc34de4e649 | medium |
| S26 δ | docs/prds/sweep-knob-registry.md | 967 (pending) | fk-bea05911eb70 fk-59fdc80fdded fk-4cc34de4e649 | medium |
| S26 ε | docs/prds/sweep-knob-registry.md | 968 (pending) | fk-bea05911eb70 | medium |
| S26 ζ | docs/prds/sweep-knob-registry.md | 969 (pending) | fk-ac39320dcf1d fk-4cc34de4e649 | medium |
| S25 β | docs/prds/board-reports-sections-by-mode.md | 970 (pending) | fk-ae20e1833a19 | low |
| S26 η | docs/prds/sweep-knob-registry.md | 971 (pending) | fk-4cc34de4e649 fk-ac39320dcf1d | medium |
| S26 θ | docs/prds/sweep-knob-registry.md | 972 (pending) | fk-4cc34de4e649 | medium |
| S25 γ | docs/prds/board-reports-sections-by-mode.md | 973 (pending) | fk-b7241e0ce122 | high |
| S25 δ | docs/prds/board-reports-sections-by-mode.md | 974 (pending) | fk-b7241e0ce122 | high |
| S25 ε | docs/prds/board-reports-sections-by-mode.md | 975 (pending) | fk-ef13881623be | low |
| S25 ζ | docs/prds/board-reports-sections-by-mode.md | 976 (pending) | fk-ef13881623be | low |
| S18 α | docs/prds/dashboard-limits-and-distribution-table.md | 977 (pending) | fk-94cab00e114e | medium |
| S18 β | docs/prds/dashboard-limits-and-distribution-table.md | 978 (pending) | fk-1df9dbc0d971 fk-f8b7b3ab709d fk-366773b4083f | medium |
| S18 γ | docs/prds/dashboard-limits-and-distribution-table.md | 979 (pending) | fk-8107696f0b02 fk-a6d9f3e5a7e2 | high |
| S18 δ | docs/prds/dashboard-limits-and-distribution-table.md | 980 (pending) | fk-a6d9f3e5a7e2 fk-8107696f0b02 fk-366773b4083f fk-c3625a25eed4 fk-3cd0d3f3b512 fk-021a21b35427 | high |
| S18 ε | docs/prds/dashboard-limits-and-distribution-table.md | 981 (pending) | fk-7893b49b92c3 fk-88374e6e3553 fk-c3625a25eed4 | medium |
| S18 ζ | docs/prds/dashboard-limits-and-distribution-table.md | 982 (pending) | fk-40dff1473b94 fk-d303b6dbf669 fk-021a21b35427 | medium |
| S18 η | docs/prds/dashboard-limits-and-distribution-table.md | 983 (pending) | fk-006c3339e3b2 | low |
| S18 θ | docs/prds/dashboard-limits-and-distribution-table.md | 984 (pending) | fk-a6d9f3e5a7e2 fk-1df9dbc0d971 | high |
| S29 α | docs/prds/surface-version-bump.md | 986 (pending) |  | medium |
| S29 γ | docs/prds/surface-version-bump.md | 987 (pending) |  | medium |
| trigger chain | — | 772 (deferred; depends on [788, 789, 823, 825, 816, 822, 832, 860, 861, 864, 866, 868, 870, 871, 872, 883, 888, 877, 893, 894, 895, 900, 902, 906, 914, 919, 921, 915, 935, 297, 922, 925, 929, 946, 947, 955, 957, 958, 959, 962, 973, 974, 979, 980, 984, 224]) | — | medium |

Trigger chain: human gate task 772 (interim form, skills/_shared/filing-the-trigger-chain.md §4; `metadata.trigger_chain = {role: human_gate, skill: review-all, run_id: review-all-solar_challenge-20261013}`), filed deferred under planning mode on 2026-10-14; each /prd session added its high and critical leaves as its dependencies, and S29 β (224, the release commit) joined it at L45; the table above is complete as of 2026-10-18 (every stream S1-S29 filed, every held leaf released), so the human commits the gate with commit_planning(task_ids="772"). No earlier review-all chain existed; launched_from: none.

Coordinator interventions: the S9 and S11 spawns failed once on shell quoting and were relaunched; the fused-memory server restarted during Phase 5 ticket resolution and 29 tickets were resubmitted.
