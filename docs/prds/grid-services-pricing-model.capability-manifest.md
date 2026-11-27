# Capability manifest — Grid-services pricing model (review-all S9)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/grid-services-pricing-model.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/grid-services-pricing-model.capability-manifest.yaml`.

**Code anchors** verified against main `9d7b67e` (2026-10-14). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`. Every substrate the signals read exists on main, or is delivered by the leaf itself or by an upstream prerequisite: S1's 773 and 774, task 704, α upstream of β, and β and γ upstream of ε. Each rejection a signal asserts is new code in its own leaf, and each has a RED-today test whose current silent-accept is measured.

## α — Grid-services income per simulated age, through one pricing method (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Each simulated age's `FleetResults` is in hand where income is booked | grep: `finance.project_multi_year._simulate_age` calls `simulate(fleet_config, start_ts, end_ts)` for `_aged_homes(homes, age, cum_tp)` before computing `fleet_revenue`, at every seed and trial age | PASS |
| An aged fleet's battery SOH reaches the spare-capacity floor (the fixture's premise) | grep: `_aged_homes` injects `dataclasses.replace(new_bc, soh=soh_i)`; `Battery.min_soc_kwh` = `effective_capacity_kwh × min_soc_fraction`, with `effective_capacity_kwh = capacity_kwh × soh`; `compute_fleet_spare_capacity_kw` builds `Battery(battery_config).min_soc_kwh` | PASS |
| SOH(24) < SOH(0), so "age 24 < age 0" is achievable | `compute_soh`: `calendar_fade_rate_per_year = 0.02` default, `soh_floor = 0.5`; SOH(0, 0) = 1.0, SOH(24) ≤ 0.52 | PASS |
| C1's equality is exact (the no-income curve is flat) | `_interpolate_per_year` is PCHIP over node values; with an energy-constant fake every node's revenue is equal, and PCHIP of a constant is that constant | PASS |
| C2's bisection fires on the fixture | numeric: PCHIP over SOH nodes (0, 1.0), (12, 0.5), (24, 0.5) at age 6 = 0.65625 (scipy, run); actual SOH(6) = 0.71575 (calendar 0.02/yr + cycle 5e-5 × 0.5 kW × 8760 h / (2 × 4 kWh) per year); a 1% target is exceeded when event income > ~1/6 of age-0 revenue | PASS (premise computed) |
| The board scenario's figure is £0, so the signal is bound to the fixture, not the board | probe at 9d7b67e: 3 battery homes of `bristol-phase1-flex.yaml`, 2024-01-08..21, SOH 1.0 and 0.8 → `annual_income_gbp` 0.000, `per_window_avail_kw` (0.0,), min in-window SOC = floor | PASS (recorded, not asserted) |
| The memo, function-local import, guard block, string branch and `assert` exist to delete | grep: `_event_gs_memo`; indented `from solar_challenge.gridservices import compute_grid_services_at_events`; "Fail-fast: validate grid_services_model prerequisites"; `assert finance.grid_services_events is not None` in `finance.py` | PASS |
| The two monkeypatching tests exist to delete | grep: `monkeypatch.setattr(gs_module, "compute_grid_services_at_events", …)` in `test_compute_once_event_figure_reused_across_ages` and `test_compute_once_memo_reused_on_bisection_path` | PASS |
| Hoisting the import keeps finance free of config and pvlib (S1 C7) | probe: `python -I -c "import solar_challenge.gridservices"` → package modules `battery`, `gridservices`, `timebase`; `pvlib` absent | PASS |
| `GridServicesEventsConfig` can gain a member additively | grep: `tests/unit/test_public_api_surface.py` `FROZEN_MEMBERS` has no `GridServicesEventsConfig` key; the members test fails until one is added (consumption guide §"Changes merged since the last tag") | PASS |
| The worked figure 9.972 is arithmetic on the defaults | `GRID_SERVICES_RATE_BANDS.central` (1.00 £/kW/event, 60 £/MWh), `DEFAULT_EVENT_WINDOWS` (12 events, 3 h), `utilisation_factor` 0.6, `aggregator_share` 0.25 → (12 + 0.6 × 3 × 0.06 × 12) × 0.75 = 9.972 | PASS |
| The model doc has no capacity-at-events equation yet | grep: `capacity_at_events` and `9.97` absent from `docs/cost-recovery-finance-model.md` | PASS |
| An unobserved window is silent today | grep: `compute_fleet_spare_capacity_kw` skips a home whose `mask.any()` is False with no warning | PASS |
| `ConfigurationError` importable from the errors leaf | producer: S1-α (773), upstream | PASS |

## α′ — Firm spare capacity per event day, with a named delivery baseline and the displaced self-use beside it (leaf, task 837)

Added 2026-10-16 by a follow-up decompose pass (D41, L24); anchors re-verified at main `1fa8f79`, where every module α′ touches is unchanged since the measurement's base `0a5ab70`.

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The per-day reduction and the displaced self-use need no new simulator output | grep: `SimulationResults` carries 1-minute `battery_soc`, `battery_discharge`, `battery_charge` and `tariff_rate` (`home.py`) | PASS |
| P6 is RED today | grep: `compute_fleet_spare_capacity_kw` takes `(soc_w - min_soc_kwh).min()` and `dis_w.max()` over every in-window minute of the season | PASS |
| The season minimum is a lower bound of every reliability figure (C9) | per home, a minimum over the season is at most each day's minimum and a maximum discharge over the season at least each day's, so the season figure is at most min over d of A(d) | PASS (derived) |
| "On 90% of event days" is a true label | the task pins the quantile as the largest v with A(d) ≥ v on at least that share of days (p50 = 2.0, p90 = 1.0 on P6); a linearly interpolated 10th percentile gives 1.1 there, available on half the days | PASS (definition pinned on the task) |
| P8's figure is producible on the P6 fixture | home A's day-1 availability is 0, so the fleet's daily displaced energies are (1.5, 3.0) kWh, mean 2.25; the PRD's "1.5 per home × 2 homes" holds only without A's floor minute | PASS (figure corrected on the task) |
| `delivery_baseline: metered` is refused naming both values, not relabelled | grep: `config._parse_grid_services_events_config` constructs `GridServicesEventsConfig(**fields)` outside its coercion `try`; today the key is refused by `_refuse_unrecognised_keys` | PASS (rejection is new code in α′) |
| The events breakdown can gain fields additively | grep: FROZEN_SURFACE pins `GridServicesAtEvents` (three fields) and `GridServicesEventsConfig` (last field `utilisation_gbp_per_mwh`); defaulted last fields keep positional construction | PASS |
| `compute_fleet_spare_capacity_kw` can learn the baseline | its frozen form is `(fleet_results, windows) -> tuple[float, ...]`; a last defaulted parameter is additive (PRD §5.8 and §5.10, amended after this decompose) | PASS |
| The report table exists to extend | grep: `output.generate_finance_report` renders "Grid services (capacity-at-events)" from `GridServicesAtEvents` only | PASS |
| `ConfigurationError ⊂ ValueError` for the refusal | producer: S1-β (774), upstream | PASS |
| The pricing value and the unobserved-window warning exist | producer: α (801), upstream | PASS |
| The board figures are measured | 100 homes, full 2024: £296 / £919 at SOH 1.0, £143 at SOH 0.8, £242 displaced; the scripts sit outside the repo (`docs/analysis-and-context` is an untracked symlink), path named on the task | PASS (recorded, not asserted) |

## β — FinanceConfig refuses an inconsistent grid-services choice; no CLI ignores one (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `grid_services_model_of` and the pricing values exist | producer: α, upstream (β depends on α) | PASS |
| `ConfigurationError ⊂ ValueError`; `cli/optimize`'s sensitivity guard lets it propagate | producer: S1-β (774), upstream | PASS |
| `capacity_at_events` + events None constructs today (C5 RED) | finding fk-d432a549b03f measured `FinanceConfig(standing_charge_pence_per_day=60, grid_services_model='capacity_at_events')` constructs; `test_capacity_at_events_without_config_ok` pins it | PASS (silent accept observed) |
| `finance run` on that file exits 0 with no events section today (C6 RED) | grep: `cli/finance.run` computes `_grid_services_at_events = … if finance.grid_services_model == "capacity_at_events" and finance.grid_services_events is not None else None` | PASS (silent path observed) |
| `--grid-services-kw` is ignored under events today (C7 RED) | grep: `cli/optimize.configs` does `dataclasses.replace(finance, grid_services_income_per_kw_per_year_gbp=grid_services_kw)`; `_simulate_age` reads the flat field only in its `else` branch | PASS (silent path observed) |
| The sensitivity axis is a no-op under events today (C8 RED) | grep: `optimize.apply_knob` routes any `FinanceConfig` field name through `replace(scenario.finance, …)`; the grid alias names the flat field | PASS (silent path observed) |
| The refusal happens before any simulation | grep: `cli/finance.run` calls `parse_finance_config` before `simulate`; `cli/optimize.configs` applies `--grid-services-kw` and parses `--sensitivity` before `load_fleet_config` and `run_sweep` | PASS |
| An injectable simulator can fail the test if called | grep: `tests/_cli_fleet_simulator.invoke_cli(args, simulator)` | PASS |
| The board scenario file carries a flat rate under the events model (needs migration) | grep: `scenarios/bristol-phase1-flex.yaml` finance block has `grid_services_income_per_kw_per_year_gbp: 12.0` and `grid_services_model: capacity_at_events` | PASS |
| `FinanceConfig`'s form does not change | the rule is called from `__post_init__`; no field is added or removed | PASS |

## γ — One band vocabulary and one grid-services rate table (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Four vocabularies exist to collapse | grep: `flex.FLEX_VALUE_BANDS` keys and `resolve_flex_band`; `GridServicesRateBands.resolve`'s `if band == "low"` chain; `GridServicesEventsConfig`'s `_VALID_BANDS`; `cli/finance.FlexBand` | PASS |
| `FLEX_VALUE_BANDS` is mutable today | grep: `FLEX_VALUE_BANDS: dict[str, FlexibilityValueBand] = {` | PASS |
| `GridServicesRateBand` can gain a last field additively | grep: its last field is `provenance: str = ""`; a defaulted field after it keeps positional construction; `FROZEN_SURFACE` pins the form, so the edit is required | PASS |
| `optimize.SENSITIVITY_BANDS` exists to repoint | producer: task 704 (branch `task/704`: `SENSITIVITY_BANDS` with its grid entry from `flex.resolve_grid_services_band`), upstream | PASS |
| The two band refusals differ today (C10 RED) | grep: `resolve_flex_band` raises `ValueError("Unknown flexibility band …")`, printed `Invalid value:` by `handle_errors`; `GridServicesEventsConfig` raises `ConfigurationError("…band must be one of [...]…")` | PASS (divergence observed) |
| Typer accepts a `(str, Enum)` option type case-insensitively | grep: `cli/finance.run`'s `--flex-band` is `Optional[FlexBand]` with `case_sensitive=False`, and `FlexBand(str, enum.Enum)` | PASS |
| `GridServicesRateBand` refusals raise ConfigurationError | producer: S1-β (774), upstream | PASS |
| The stale pointer exists | grep: `flex.py` "config.py:264" (×2); the default is `BatteryConfig.max_discharge_kw = 2.5` | PASS |
| flex importing gridservices loads no pvlib | probe: the gridservices import closure is `battery`, `timebase` and pandas | PASS |

## ε — FinanceConfig.grid_services_model holds the pricing model (held leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The pricing values exist | producer: α, upstream | PASS |
| One band vocabulary exists to type with | producer: γ, upstream | PASS |
| No inconsistent triple reaches ε's migration | producer: β, upstream (the files load under β's rule) | PASS |
| A typed block grammar exists (`type:` through `_BlockType`) | grep: `config._BlockType` and `_TARIFF_TYPES`, read by `parse_tariff_config` | PASS |
| The platform needs no edit | grep at solar-challenge-platform `5fa0dfd`: `billing/config.py` builds `FinanceConfig(standing_charge_pence_per_day=…, vat_rate=…, own_use_rate_pence_per_kwh=…, retained_cash_floor_per_home_per_year_gbp=…[, retail_baseline_rate_pence_per_kwh=…])`; no reference to `grid_services_income_per_kw_per_year_gbp`, `grid_services_model`, `grid_services_events`, `solar_challenge.gridservices` or `solar_challenge.flex` in `src/` or `tests/` (the platform's own `control/grid_services.py` port is unrelated) | PASS |
| The legacy keys are read today (so refusing them is a real change) | grep: `config._FINANCE_SCALAR_COERCIONS` has `grid_services_income_per_kw_per_year_gbp` and `grid_services_model`; `_FINANCE_BLOCK_KEYS` has `grid_services_events` | PASS |
| The bump window exists to release it | producer: S29 (wave 4); `x_seam_wait = {stream: S29, contract: surface bump window open}` | PASS (held) |

## Delivered-check notes

- **One vacuous check.** ε's `transitional-rule-deleted` passes vacuously on main today, because `grid_services_model_of` does not exist until α. Every other grep check fails on main `9d7b67e` (run) and passes once its leaf lands.
- **One check stops holding by design.** β's `constructor-applies-the-one-rule` stops holding when ε deletes the rule. ε is held for S29's window, after S8 and S25, whose leaves depend on β.
- **The surface checks search `tests/`.** The `FROZEN_*` checks for α and γ search `tests/` rather than `tests/unit/test_public_api_surface.py`, because S23 may move the surface tables into a new module first.
