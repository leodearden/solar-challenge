# PRD — Event dispatch and battery sizing: metered grid-services income in the size sweep

- **Program:** review-all-solar_challenge-20261013, the successor to stream **S9** leaf α′ (task 837) that ruling **D41** and lead ruling **L24** name (`plans/review-all-program-solar_challenge-20261014.md`). Gate task 944, escalation esc-944-1. Size L, risk medium-high.
- **Binding rulings:** D41 (a successor PRD follows α′; the frozen-library posture does not bar simulator changes made for correctness), D29 (additive frozen-table edits land in-leaf with an unreleased note; renames and retirements are held), and Leo's rulings of 2026-11-24 in the gate's /team and /prd session, recorded in §6. Two of those rulings change D41's wording: delivery is metered inside one enrolled run as the products meter it, not by paired runs; and the battery does not hold charge back for an event.
- **Status:** authored 2026-11-24 by an attended /prd author session. Not decomposed. Every leaf waits for the 0.6.0 release commit (task 224).
- **Approach:** B + H. The change crosses the dispatch engine, the battery configuration, the scenario grammar, grid-services pricing, the projection and the install sweep, and adds to the frozen surface. So it gets a contract (§5) and two-way boundary tests (§9).
- **Code anchors** are cited by symbol and were read against main `07ff4398` (2026-11-24). Main moves fast; re-locate at implementation time.

## 1. Goal

The board needs to decide whether a larger battery earns back its extra capital cost. Part of what a larger battery earns is grid-services event income, and today the simulator cannot value it: no dispatch can send battery energy to the grid, so the events model only prices whatever charge the arbitrage dispatch happens to leave spare, and reports the evening self-use an event would displace beside the income without netting it.

After this PRD a scenario can enrol its fleet in events. An enrolled home discharges its battery at full power through each drawn event window, serving the home first and exporting the rest. Delivery is metered from that run as each product meters it, and the householders' bills come from the same run, so what an event costs a household is in its bill and needs no separate bookkeeping. The install sweep varies battery power with battery size and says, per size, whether it pays for itself.

What a user observes:

1. **A battery can export on command.** In an enrolled scenario, `fleet run` shows battery energy exported inside event windows on the drawn event days and on no other day. Today every dispatch strategy's discharge is refused above the home's own shortfall.
2. **Event income is metered, not inferred.** `finance run` on an enrolled scenario prints the events income priced from metered delivery, with the delivery baseline named, the delivery on 50% and 90% of event days, and the battery energy exported per event. The householder bill lines in the same report already include the import the event caused.
3. **Enrolment is one scenario setting.** `grid_services_events.participation: dispatched` enrols the fleet; `observed`, the default, keeps today's model unchanged. Pricing a fleet that was simulated without the event dispatch as `dispatched`, or the reverse, is refused, naming both.
4. **The sweep answers the sizing question.** `optimize configs` takes a battery power per battery size, costs the battery inverter, and prints for each configuration, against a named reference configuration, the extra capex per home, the change in householder outlay at the solved cost-recovery rate, the events income per home, and whether the configuration pays for itself.
5. **The board has a recorded answer.** `docs/battery-sizing-with-events.md` records the sweep over the four Victron configurations of §2.3 on the board fleet, enrolled and not, at the low, central and high bands.

## 2. Background

### 2.1 What exists today

- `gridservices.GridServicesEventsConfig` prices a simulated fleet with `annual_income_gbp(fleet_results)`. Since task 837 it measures each home's firm spare capacity on each event day under a named `delivery_baseline` and books the mean over event days. `compute_grid_services_at_events` returns the `GridServicesAtEvents` breakdown, including the displaced evening self-use, which the income does not net off (`docs/prds/grid-services-pricing-model.md` §5.10, §6 decision 15).
- No strategy can export battery energy. `dispatch.DispatchDecision` carries `charge_kw`, `discharge_kw` and `grid_charge_kw`. `dispatch.StepLimits.require_admissible` refuses a `discharge_kw` above the step's shortfall. `flow._settle` books `grid_export` as PV excess the battery did not draw.
- `dispatch.ScheduledChargeStrategy` already wraps a base strategy and overrides it inside clock windows. It is the precedent for a wrapping strategy.
- `optimize.ConfigPoint` sweeps PV capacity, battery energy and PV inverter capacity. `optimize._apply_install` keeps each home's battery power, so a larger battery in the sweep has the same power as a smaller one. `finance.FinanceConfig` costs the battery per kWh only.
- `config.ScenarioConfig.simulated_homes` already fills a scenario-level setting (the SEG tariff) into the homes it simulates.

### 2.2 Premise measurement (G6)

Today's model and today's dispatch, on battery-size variants of `scenarios/bristol-phase1-flex.yaml`: the first 20 homes, full 2024, central band, scaled to 100 homes. Battery energy and power were replaced on each home; nothing else changed. Script and log are outside the repo (`/tmp/944-measure/measure.py`, `/tmp/944-measure/run.log`), run on main `07ff4398`. The 5 kWh row reproduces the figures recorded at task 837's merge (commit 709af2f2: £283 operational, £905 capacity on all 100 homes).

| Battery / power | Events income, operational £/yr | Events income, capacity £/yr | Displaced self-use £/yr | Fleet import cost £/yr |
|---|---:|---:|---:|---:|
| 5 kWh / 2.5 kW | 299 | 895 | 344 | 26,722 |
| 10 kWh / 2.5 kW | 1,275 | 2,134 | 889 | 20,423 |
| 10 kWh / 5 kW | 1,398 | 2,196 | 891 | 20,421 |
| 13.5 kWh / 5 kW | 2,318 | 3,127 | 1,012 | 19,510 |

Rules: income is `compute_grid_services_at_events(...).annual_income_gbp` at each delivery baseline; displaced self-use is the sum of `per_window_displaced_import_gbp_per_year`, valued at each home's simulated tariff (Economy 7 at 0.13/0.35 £/kWh); import cost is the sum of each home's `import_cost` series. Every figure is 20 homes times 5.

Three readings:

- **The events line matters to the sizing decision.** From 5 to 10 kWh, import cost falls about £6,300 a year and events income rises about £1,000 to £1,250, against £125,000 of extra capex at £250 per kWh. From 10 to 13.5 kWh, import cost falls about £900 and events income rises about £1,000, against £87,500. For the last increment the events line is more than half of what it earns.
- **Gross is not net.** At 10 kWh the operational income of £1,275 sits beside £889 of displaced householder import. The observational model cannot book that; an enrolled run does, in the bills.
- **Power adds little under today's dispatch.** Doubling power at 10 kWh moves the operational figure from £1,275 to £1,398, because nothing discharges at full power in the window. Under the event dispatch, power is what an event delivers, so this is the figure the PRD most changes.

The measurement leaves out the export income a larger battery gives up, applies no export limit, and uses the scenario's battery efficiency and charge power, not Victron's.

### 2.3 Hardware (Victron)

The consulting decisions commit to Victron with a MultiPlus-II class inverter. From Victron's datasheets and UK certificates, read 2026-11-24:

- Battery: Lithium NG 51.2 V / 100 Ah, 5.12 kWh a module, paralleled freely; round-trip efficiency 92%.
- MultiPlus-II 48/3000: 2.4 kW continuous, 35 A charge (about 1.8 kW), certified to G98.
- MultiPlus-II 48/5000: 4.0 kW continuous, 70 A charge (about 3.6 kW); certified to G98 with a 16 A limit (3.68 kW), and to G99 at 4.4 kW feed-in.

The four configurations the board answer covers:

| Battery | Inverter | What limits a 3-hour event |
|---|---|---|
| 5.12 kWh | 48/3000 | energy |
| 10.24 kWh | 48/3000 | power, 2.4 kW |
| 10.24 kWh | 48/5000 | energy |
| 15.36 kWh | 48/5000 | power, 3.68 kW under G98 |

G98's 16 A per phase covers PV and battery together. So a home's export during an event has a site limit, which §5.4 takes as an input.

## 3. Rulings and how this PRD reads them

| Ruling | Reading |
|---|---|
| D41, successor PRD | This PRD. Its goal is restated around battery sizing (Leo, 2026-11-24). |
| D41, "paired baseline and event-dispatch runs" | Superseded by decision 1 of §6: one enrolled run, metered as the products meter. A fleet simulated twice, enrolled and not, is two scenarios, which the sweep compares. |
| D41, frozen-library posture | The engine change lands. Every surface change here is additive, so under D29 each lands in its leaf with its unreleased note. |
| L24 | Authored after α′ landed (837 merged 2026-11-08). |
| Leo 2026-11-24, queueing | Every leaf depends on the 0.6.0 release commit, task 224. |
| Leo 2026-11-24, rate calibration | A separate market-evidence task, not a leaf here (§11). This PRD reports across the low, central and high bands. |

## 4. Sketch of approach

Four layers, each hiding the one below (heuristic 9):

1. **Engine.** A dispatch decision may ask the battery to export. It is a new, separately bounded power, as grid charging was. The rule that discharge serves at most the home's shortfall is unchanged.
2. **Event dispatch.** A wrapping strategy overrides its base strategy inside a home's event windows and asks for full-power discharge. Outside them the base strategy decides. Enrolment is orthogonal to the base strategy (heuristic 3): it wraps any of them.
3. **Enrolment and metering.** The scenario's events block is the one definition of the event windows (heuristic 11). One function draws the event days. `simulated_homes` gives each battery home its drawn windows; pricing draws the same days from the same function and refuses a fleet whose homes carry different ones (heuristic 10).
4. **Sizing.** The sweep sets battery power with battery energy, costs the battery inverter, and reports each configuration against a reference.

Today's observational model stays as the pricing of a fleet that is not enrolled.

## 5. Contract

### 5.1 Battery export in the engine (α)

- `dispatch.DispatchDecision` gains `export_kw: float = 0.0`: battery power asked for beyond the home's shortfall, sent to the grid. Finite and at least 0. Refused above 0 alongside `charge_kw > 0` or `grid_charge_kw > 0`, as `discharge_kw` is.
- `dispatch.StepLimits` gains `max_export_kw`, and `require_admissible` refuses an `export_kw` above it, naming the field, its value and the limit. `StepLimits.for_step` sets it from the battery's `max_discharge_kw` less the step's shortfall, at least 0, and no more than the home's export headroom when one is set (§5.4). A strategy that asks for no export is admissible exactly as today.
- `flow._execute` discharges `discharge_kw + export_kw` in one battery call. `flow._settle` serves the home's shortfall first from what the battery delivered and books the rest as export.
- `flow.EnergyFlowResult` gains `battery_export: float = 0.0`, informational, a part of `battery_discharge` and of `grid_export`, as `grid_charge` is a part of `battery_charge` and `grid_import`. The bus identity is unchanged and still closes with no loss term.
- `home.SimulationResults` gains the `battery_export` series. `validation`'s energy balance holds on an exporting run.
- `self_consumption` never includes exported battery energy.

### 5.2 Event discharge strategy (β)

- `dispatch.EventDischargeWindow`: a frozen value holding `days: tuple[date, ...]` and `hours: tuple[int, ...]`, each read through `number_fields` and refused when empty. It is a resolved value: it holds no months, weekdays or seed.
- `dispatch.EventDischargeStrategy(base, windows)`: in a minute whose date and hour fall in one of its windows it returns a decision with no charge, `discharge_kw` equal to the step's shortfall and `export_kw` equal to the step's `max_export_kw`. In every other minute it returns the base strategy's decision unchanged. It asks for no grid charge inside a window.
- `battery.BatteryConfig` gains `event_discharge: tuple[EventDischargeWindow, ...] = ()`. It has no YAML form: `scenario_blocks.BATTERY_BLOCK` lists it in `outside_grammar` and `not_in_fleet`, each with the reason that the scenario's events block sets it.
- `dispatch.build_dispatch_strategy` gains the keyword `event_discharge`, default `()`, and wraps the strategy it builds when the tuple is not empty. `home.py` and `community.py` pass the battery's `event_discharge`.
- There is no hold-back (§6 decision 3): before the window the base strategy runs unchanged.

### 5.3 Enrolment and the event-day draw (γ)

- `gridservices.EventParticipation`, a `StrEnum`: `observed` (the default) and `dispatched`, parsed and refused as `DeliveryBaseline` is.
- `gridservices.GridServicesEventsConfig` gains `participation: str = "observed"`, `event_day_seed: int = 0` and `site_export_limit_kw: float | None = None` (§5.4). The scenario grammar reads them from `finance.grid_services_events`, as it reads the other fields of that value.
- `gridservices.drawn_event_days(window, days, seed) -> tuple[date, ...]`: from the days of `days` that `window`'s months and weekdays admit, a draw without replacement, seeded by `seed` and the window's position, of `n` days in date order. `n` is `window.events_per_year` scaled by the share of a year's eligible days that `days` holds, rounded, at least 1 when any eligible day exists, and at most the eligible days. The same arguments give the same days.
- `config.ScenarioConfig.simulated_homes` gives each battery home, when the scenario's events configuration is `dispatched`, a `battery_config.event_discharge` built from `drawn_event_days` over the scenario's window. Every home of a scenario gets the same days: an event is fleet-wide. A home with no battery is unchanged.
- With `observed`, `simulated_homes` sets nothing and every result is byte-identical to today's.
- A scenario that is `dispatched` with no battery home is refused with `ConfigurationError`, naming the setting.

### 5.4 Site export limit (γ)

`site_export_limit_kw` is the most a home may export in a step in which its battery exports, PV excess included. `None` means no limit. `simulated_homes` carries it to the home with the event windows, and `StepLimits.for_step` reduces `max_export_kw` to the limit less the step's PV excess, at least 0. It does not curtail PV export in a step where the battery exports nothing; that is a different feature (§11), and the field's name and docstring say so.

### 5.5 Metered pricing (δ)

For a `dispatched` configuration, `GridServicesEventsConfig.annual_income_gbp(fleet_results)` and `compute_grid_services_at_events` price metered delivery in place of spare capacity. The rate, aggregator share, utilisation factor and the per-kW-year formula are unchanged. For each window and each drawn event day `d`, the fleet's delivered power `D(d)` in kW is:

- **`capacity`:** the sum over battery homes of the battery's discharge energy inside the window on `d`, divided by `event_hours`.
- **`operational`:** `max(0, B(d) − N(d))`. `N(d)` is the fleet's mean net import power inside the window on `d`: the sum over battery homes of `grid_import − grid_export`. `B(d)` is the mean of `N` over the ten eligible non-event days nearest before `d`, completed from the days after `d` where fewer than ten precede it. This is the simulator's reading of a DFS-style historical baseline; §12 question 1 covers the product text.

The income books the mean of `D(d)` over the drawn event days. `GridServicesAtEvents` reports, per window: that mean in `per_window_avail_kw`; the delivery on 50% and 90% of event days by the rank rule the type already uses; and a new field `per_window_battery_export_kwh_per_event`. Under `dispatched` the two displaced-self-use fields are empty, because the bills of the same run already hold that import.

Invariant, enforced in pricing (heuristic 10): the days pricing draws from `drawn_event_days` over the fleet's simulated days equal the `event_discharge` days on every battery home in `fleet_results.home_configs`. A `dispatched` configuration pricing homes with no event windows, an `observed` one pricing homes that have them, or differing days, raises `ConfigurationError` naming the participation, the days expected and the days found.

The report's capacity-at-events table names the participation and the baseline, shows the three delivery rows and the export row, and for `dispatched` replaces the gross-of-self-use note with a line saying the bills in the report include the import the events caused. The model doc (`docs/cost-recovery-finance-model.md`) gains the metering equations.

Event export earns the home's SEG rate like any other export. Per-age pricing is unchanged in form: `projection._aged_homes` keeps each battery's `event_discharge`, so each simulated age is an enrolled run.

### 5.6 Sizing in the sweep (ε)

- `optimize.ConfigPoint` gains `battery_kw: float | None = None`. When set, `_apply_install` sets the battery's `max_charge_kw` and `max_discharge_kw` to it; `None` keeps the home's own, as today.
- `finance.FinanceConfig` gains `battery_inverter_cost_per_kw_gbp: float = 0.0`, costed on each battery's `max_discharge_kw` in the capex the projection already totals.
- `optimize configs` gains `--battery-kw`, a list parallel to `--battery`, refused when its length differs; and `--reference`, naming the configuration the marginal columns compare against, defaulting to the smallest battery in the grid at the smallest PV.
- Each ranked row gains: extra capex per home against the reference; the change in the representative householder outlay at the solved cost-recovery rate; the events income per home per year; and `pays for itself`, which is yes when the configuration is feasible and its outlay is not above the reference's. The ranking itself is unchanged (§6 decision 4).
- `scenarios/bristol-phase1-victron.yaml` is the board fleet on Victron's figures: 5.12 kWh modules, charge power below discharge power, the battery's 92% round trip, `participation: dispatched` and a 3.68 kW site export limit.

### 5.7 Surface ledger

All additive, each with its `docs/unreleased/<doc>/<task id>.md` note in the leaf that adds it:

| Name | Leaf |
|---|---|
| `DispatchDecision.export_kw`, `EnergyFlowResult.battery_export`, `SimulationResults.battery_export` | α |
| `EventDischargeWindow`, `EventDischargeStrategy`, `BatteryConfig.event_discharge` | β |
| `EventParticipation`, `GridServicesEventsConfig.participation`, `.event_day_seed`, `.site_export_limit_kw`, `drawn_event_days` | γ |
| `GridServicesAtEvents.per_window_battery_export_kwh_per_event` | δ |
| `ConfigPoint.battery_kw`, `FinanceConfig.battery_inverter_cost_per_kw_gbp` | ε |

Nothing is renamed or retired, so nothing is held for a later bump.

### 5.8 Invariants

1. A run with no event windows is byte-identical to today's run, at every layer.
2. `generation + grid_import = demand + grid_export + battery_charge − battery_discharge` holds on every step of an exporting run.
3. `battery_export ≤ battery_discharge` and `battery_export ≤ grid_export` on every step.
4. Battery export is above 0 only inside a drawn event window.
5. A home's export in a step in which its battery exports is at most `site_export_limit_kw` when one is set.
6. Pricing and simulation agree on the event days, or pricing refuses (§5.5).

## 6. Resolved design decisions

Decisions 1 to 4 are Leo's rulings of 2026-11-24.

1. **Delivery is metered inside one enrolled run, as the products meter it.** Paired runs double every projection and sweep point and meter against a baseline no product uses. With one run the householders' bills are the enrolled bills, so incidence needs no bookkeeping. This supersedes D41's "paired baseline and event-dispatch runs".
2. **Event days are exactly the configured number, drawn by seed.** The simulated year is the billed year. An event on every eligible day, scaled down, would charge a larger battery the cost of an event on days that pay nothing.
3. **No hold-back.** The base dispatch runs until the window opens; the battery then discharges at full power. A reserve ahead of the window is a later option (§11).
4. **"Pays for itself" is the cost-recovery ranking**, with the marginal capex, outlay and events income beside it. Simple payback and net present value of the increment were the alternatives.
5. **Export is a separate power on the decision.** Raising the discharge bound instead would let any strategy export by mistake and would make `discharge_kw` mean two things (heuristic 1).
6. **Enrolment wraps the base strategy.** A fourth strategy variant would cross enrolment with every base strategy (heuristic 3).
7. **The events block is the one definition of the windows.** The battery carries resolved days, not a second copy of the months and weekdays (heuristic 11).
8. **The observational model stays** for a fleet that is not enrolled. It is also the cross-check: on the board fleet the capacity-baseline figure under `dispatched` should sit near α′'s capacity figure for the same days, since both count the charge present when the window opens.
9. **The site export limit lives on the events configuration**, because in this PRD it binds only while a battery exports. A limit that also curtails PV belongs to the home.

## 7. Pre-conditions

- Task 224, the 0.6.0 release commit: every leaf depends on it.
- Task 974 (S25 δ), which moves the capacity-at-events rows to the board report and names the delivery baseline: δ depends on it and extends the table where 974 leaves it.
- Task 1434, the empty displaced-self-use rendering and `GridServicesAtEvents`'s unchecked per-window invariants: δ depends on it, because `dispatched` relies on an empty displaced field rendering as not reported.
- Task 1315, the `simulate_home(strategy=...)` override against the grid-charging refusal: β depends on it, since both change how `home.py` builds a strategy.
- S2 (786 to 790), S3's settle function (896, 900) and S16's `FleetRunner` are on main and are bound as they stand.

## 8. Cross-PRD relationship

| Other PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| `docs/prds/grid-services-pricing-model.md` (S9) | extends | `GridServicesEventsConfig`, `GridServicesAtEvents`, `compute_grid_services_at_events` | this PRD for the `dispatched` path; S9 for `observed` | S9 landed; §11's successor row is this PRD |
| `docs/prds/one-dispatch-engine.md` (S3) | extends | `DispatchDecision`, `StepLimits`, `flow._execute`, `flow._settle` | this PRD, leaf α | 896 and 900 landed; 897, 899, 901 pending and ordered before α by the edge on 224 |
| `docs/prds/dispatch-configuration-below-config.md` (S2) | consumes | `build_dispatch_strategy` | this PRD, leaf β | landed |
| `docs/prds/board-reports-sections-by-mode.md` (S25) | consumes | the capacity-at-events table | S25 owns the table's home; this PRD's δ adds rows | 974 pending |
| `docs/prds/discrete-install-config-sweep.md` | extends | `ConfigPoint`, `_apply_install`, the ranked table | this PRD, leaf ε | landed |
| `docs/prds/surface-version-bump.md` (S29) | follows | the release window | S29 | 224 blocked on open leaves |
| `docs/prds/inter-home-community-energy-sharing.md` | touches | `community.py`'s call of `build_dispatch_strategy` | this PRD, leaf β, passes `event_discharge` through | landed |

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Faces |
|---|---|---|---|---|
| B1 | A strategy asks for export | a battery above its floor, a step with a shortfall | the home is served first, the rest is exported, the bus identity closes, `battery_export` is the exported part | engine |
| B2 | Export above the limit | `export_kw` above `max_export_kw` | `ValueError` naming the strategy, the field, the value and the limit | engine |
| B3 | No event windows | any shipped scenario | every result series equals the pre-change run | engine, strategy |
| B4 | An event day | a home with one drawn window on a synthetic winter day | battery export is above 0 only inside the window; the base strategy's decisions outside it are unchanged | strategy |
| B5 | The draw | a full-year window and a seed | `events_per_year` days, all eligible, the same on every call; a different seed gives different days | enrolment |
| B6 | Fleet-wide events | a `dispatched` scenario | every battery home of `simulated_homes()` carries the same days; a home with no battery carries none | enrolment |
| B7 | Site export limit | a limit below battery power plus PV excess | no step in which the battery exports has export above the limit | engine, enrolment |
| B8 | Capacity metering | a fleet whose in-window discharge is known by construction | income equals the formula on that discharge | pricing |
| B9 | Operational metering | a fleet with a constant in-window import on non-event days and a known event export | delivery equals the import plus the export | pricing |
| B10 | Mismatch refused | `dispatched` pricing of an un-enrolled fleet, and the reverse | `ConfigurationError` naming participation and both sets of days | pricing, enrolment |
| B11 | Bills carry the event | the same fleet enrolled and not | the enrolled fleet's import cost after each event day is higher, and its bills differ by that import | pricing, finance |
| B12 | Projection | an enrolled scenario projected | each simulated age's homes carry the event windows and its income is metered from that age's run | projection |
| B13 | Sweep power | `--battery 5.12,10.24 --battery-kw 2.4,3.68` | each configuration's homes have that power; a length mismatch is refused | sweep |
| B14 | Sweep verdict | a grid with a reference | the marginal columns are differences against the reference row, and `pays for itself` follows the outlay rule | sweep |

## 10. Decomposition plan

Every leaf depends on task 224. Labels become task ids at decompose.

- **α — Battery export in the dispatch engine.** `dispatch.py`, `flow.py`, `home.py`, `validation.py` and their tests. Contract §5.1, invariants 1 to 3, tests B1 to B3. Intermediate: unlocks β.
- **β — Event discharge strategy on the battery.** `dispatch.py`, `battery.py`, `scenario_blocks.py` (block table), `home.py`, `community.py`. Contract §5.2, invariant 4, test B4. Depends on α and 1315. Intermediate: unlocks γ.
- **γ — Enrolment, the event-day draw and the site export limit.** `gridservices.py`, `config.py`, `scenario_blocks.py`, `dispatch.py` (`StepLimits.for_step`), `home.py`. Contract §5.3 and §5.4, invariant 5, tests B5 to B7. Depends on β. **Signal:** `solar-challenge fleet run` on an enrolled copy of the board scenario reports battery export on the drawn event days and none on any other day, and the same command with `participation: observed` reproduces today's output.
- **δ — Metered events income in pricing and the report.** `gridservices.py`, the report module 974 leaves the table in, `docs/cost-recovery-finance-model.md`. Contract §5.5, invariant 6, tests B8 to B12. Depends on γ, 974 and 1434. **Signal:** `solar-challenge finance run` on the enrolled scenario prints the events income from metered delivery with participation and baseline named, the 50% and 90% rows and the export per event; pricing an un-enrolled fleet as `dispatched` exits 1 with `Configuration error:`.
- **ε — Battery power and inverter cost in the sweep, with the marginal verdict.** `optimize.py`, `cli/optimize.py`, `finance.py`, `projection.py` (capex), `scenarios/bristol-phase1-victron.yaml`. Contract §5.6, tests B13 and B14. Depends on δ. **Signal:** `solar-challenge optimize configs scenarios/bristol-phase1-victron.yaml --battery 5.12,10.24,10.24,15.36 --battery-kw 2.4,2.4,3.68,3.68` prints the ranked table with the four marginal columns.
- **ζ — The board's sizing answer, recorded.** `docs/battery-sizing-with-events.md`, and an integration test that runs a reduced sweep end to end. Depends on ε. **Signal:** the doc records ε's command run on all 100 homes for a full year, enrolled and `observed`, at the three bands, with the command and the commit; the integration test runs the same path on a small fleet and a short window and asserts invariants 1 to 6. This leaf is the consumer of every mechanism above (G1).

## 11. Out of scope

- **Rate calibration.** What DFS and NGED-style products pay per home is a market-evidence task, filed separately at decompose. The October market reading (DFS and NGED bands, aggregator reports of £120 to £240 a home) is unverified.
- **Hold-back.** A reserve held ahead of the window, and filling to target overnight regardless of the PV forecast. Decision 3 leaves it out; the wrapper is where it would go.
- **PV curtailment under an export limit.** §5.4 binds only while a battery exports.
- **The web dashboard and the assistant.** They show what the report shows once S25's rendering carries it.
- **Community netting of event export.** `community.py` passes the windows through, and its netting is unchanged.
- **Events on homes with no battery.**

## 12. Open questions

1. **The DFS baseline text.** §5.5's ten-day mean is the simulator's reading. The October investigation named the product's baseline schedule as a gap. **Suggested resolution:** δ ships the ten-day mean as a named constant with its provenance in the model doc; the rate-calibration task reads the product text and files a change if it differs. Decide during δ.
2. **Partial-year periods.** §5.3 scales the event count to the share of a year's eligible days simulated. **Suggested resolution:** as written; γ's tests pin a full year and a two-month window. Decide during γ.
3. **Victron's inverter efficiency.** The scenario models one round-trip figure on the battery. **Suggested resolution:** ε's scenario folds inverter loss into the battery's charge and discharge efficiencies and says so in its header comment. Decide during ε.
4. **The reference configuration's default.** **Suggested resolution:** the smallest battery at the smallest PV, as §5.6 says; `--reference` overrides it. Decide during ε.

## Gate record

- **G1 (consumer named):** every mechanism is consumed by a later leaf and, at the end, by ζ's recorded board answer and the `optimize configs`, `finance run` and `fleet run` commands. Pass.
- **G3 (substrate):** verified on main `07ff4398`: `DispatchDecision`, `StepLimits.require_admissible`, `flow._execute`, `flow._settle`, `EnergyFlowResult`, `build_dispatch_strategy` (called from `home.py` and `community.py`), `ScheduledChargeStrategy`, `GridServicesEventsConfig`, `EventWindow`, `DeliveryBaseline`, `GridServicesAtEvents`, `FleetResults.home_configs`, `ScenarioConfig.simulated_homes` and `.finance`, `scenario_blocks`' `outside_grammar` and `not_in_fleet`, `ConfigPoint`, `_apply_install`, `FinanceConfig.battery_cost_per_kwh_gbp`, the `optimize configs` flags, `docs/unreleased/`. Not on main: the board-report module task 974 creates, bound as a prerequisite of δ. Pass.
- **G4 (seams):** §8; no reciprocal ownership. Pass.
- **G5:** B + H; §5 and §9.
- **G6 (premise):** §2.2 measured the premise. No leaf signal asserts a figure: ζ records what the sweep returns. δ's and γ's refusals are new mechanisms built in the same leaf, with B10 as their test. Pass.
- **G7:** the project has no `docs/legibility/design-invariants.md`; advisory screen only. One shape checked: pricing acts on the fleet's own home configs and refuses a mismatch, so no silent fallback prices an un-enrolled fleet. No hit.
- **META:** the design questions are decided in §6; §12 holds tactical ones. Yes.
- **Capability manifest:** drafted at decompose, beside this file.
