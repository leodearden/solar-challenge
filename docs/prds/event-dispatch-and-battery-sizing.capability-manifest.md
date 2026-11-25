# Capability manifest — Event dispatch and battery sizing

Mechanizes G3 (substrate exists) and G6 (premise valid) per task of `docs/prds/event-dispatch-and-battery-sizing.md`. Machine-readable twin: `docs/prds/event-dispatch-and-battery-sizing.capability-manifest.yaml`, the single home of the capability list and its delivered checks.

**Code anchors** are cited by symbol and were resolved against main `4055b9a3` (2026-11-25). Main moves fast; re-locate at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Every grep check in the sidecar fails on main today and is satisfiable by its own leaf. No open task's `absent` check forbids a name these leaves introduce (every sidecar under `docs/prds/` was scanned).

Every leaf depends on task 224, the 0.6.0 release commit. So each leaf builds on main as the release leaves it, in particular after task 804 moves the events configuration onto `FinanceConfig.grid_services_model`.

## α — Battery export in the dispatch engine (intermediate, unlocks β)

| Capability | Evidence binding | Status |
|---|---|---|
| A decision can carry a new, separately bounded power | `grep:src/solar_challenge/dispatch.py::DispatchDecision` carries `grid_charge_kw` as the precedent; `grep:src/solar_challenge/dispatch.py::StepLimits.require_admissible` bounds each power | PASS |
| One settle function books every flow | `grep:src/solar_challenge/flow.py::_settle` and `grep:src/solar_challenge/flow.py::_execute` (task 896 landed) | PASS |
| `export_kw`, `max_export_kw`, `EnergyFlowResult.battery_export`, the results series | capability→producer (built here) | PASS |
| The rule "discharge at most the shortfall" survives | unchanged by contract §5.1; boundary test B3 pins a no-export run byte-identical | PASS |

## β — Event discharge strategy on the battery (intermediate, unlocks γ)

| Capability | Evidence binding | Status |
|---|---|---|
| Export power on the decision | producer α, upstream | PASS |
| One strategy build site to wrap at | `grep:src/solar_challenge/dispatch.py::build_dispatch_strategy`, called from `grep:src/solar_challenge/home.py` and `grep:src/solar_challenge/community.py` | PASS |
| A wrapping strategy is an existing shape | `grep:src/solar_challenge/dispatch.py::ScheduledChargeStrategy` | PASS |
| A battery field with no YAML form has a declared place | `grep:src/solar_challenge/scenario_blocks.py::BATTERY_BLOCK`, whose `outside_grammar` and `not_in_fleet` rows T1 checks | PASS |
| `EventDischargeWindow`, `EventDischargeStrategy`, `BatteryConfig.event_discharge` | capability→producer (built here) | PASS |
| The strategy override in `home.py` is settled first | producer task 1315, upstream | PASS |

## γ — Enrolment, the event-day draw and the site export limit (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| The scenario fills a scenario-level setting into its homes | `grep:src/solar_challenge/config.py::ScenarioConfig.simulated_homes` fills the SEG tariff today | PASS |
| The events configuration is reachable from the scenario | producer task 804, upstream through task 224: `FinanceConfig.grid_services_model` holds it | PASS |
| An eligible-day rule exists to draw from | `grep:src/solar_challenge/gridservices.py::EventWindow`, whose months and weekdays the draw reads | PASS |
| `EventParticipation`, the three new fields, `drawn_event_days`, the fill, the export limit in `StepLimits.for_step` | capability→producer (built here) | PASS |
| Signal: `fleet run` shows battery export only on drawn days | every capability it needs is delivered by α, β or γ; none by a downstream task | PASS |
| A `dispatched` scenario with no battery home is refused | capability→producer (built here); the refusal is new and is tested in the leaf | PASS |

## δ — Metered events income in pricing and the report (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| Pricing sees each home's battery configuration | `grep:src/solar_challenge/gridservices.py::compute_grid_services_at_events` receives `grep:src/solar_challenge/fleet.py::FleetResults`, whose `home_configs` field is populated on the production path by the fleet runner | PASS |
| The series metering reads are on every result | `grid_import`, `grid_export` and `battery_discharge` on `grep:src/solar_challenge/home.py::SimulationResults` | PASS |
| The table's home and its baseline label | producer task 974, upstream | PASS |
| An empty displaced-self-use field renders as not reported | producer task 1434, upstream | PASS |
| Metered `D(d)`, `per_window_battery_export_kwh_per_event`, the mismatch refusal, the model-doc equations | capability→producer (built here) | PASS |
| The refusal fires on a mismatch (G6 branch 4) | built here with boundary test B10 in both directions | PASS |

## ε — Battery power and inverter cost in the sweep, with the marginal verdict (leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| The sweep applies an install to each home | `grep:src/solar_challenge/optimize.py::_apply_install` and `grep:src/solar_challenge/optimize.py::ConfigPoint` | PASS |
| Capex is totalled in one place | the projection's capex term, with `FinanceConfig.battery_cost_per_kwh_gbp` as the precedent: `grep:src/solar_challenge/finance.py::FinanceConfig` | PASS |
| The sweep's assumptions are stated first | producer task 1270, upstream | PASS |
| `ConfigPoint.battery_kw`, the inverter cost, `--battery-kw`, `--reference`, the marginal columns, the Victron scenario | capability→producer (built here) | PASS |
| The verdict asserts no figure | it is a comparison of two outlays the solve already returns | PASS |

## ζ — The board's sizing answer, recorded (leaf, the PRD's signal leaf)

| Capability | Evidence binding | Status |
|---|---|---|
| The sweep command and its columns | producer ε, upstream | PASS |
| A full-fleet, full-year sweep is runnable by a task | measured 2026-11-24: 20 homes for a year take about two minutes at six workers; the committed Bristol TMY is under `grep:tests/fixtures/weather_cache` | PASS |
| `docs/battery-sizing-with-events.md` | capability→producer (built here) | PASS |
| The doc's figures | recorded from the run, never asserted in advance | PASS |
