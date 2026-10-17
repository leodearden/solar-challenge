# Capability manifest — One dispatch engine (review-all stream S3)

Mechanizes G3 (substrate exists) and G6 (premise valid) per leaf of `docs/prds/one-dispatch-engine.md`. Each capability a leaf's signal asserts binds to evidence: a symbol read on main and wired into the production path, a producer leaf upstream (this batch or another stream's), a measurement taken for this PRD, or a rejection mechanism the leaf builds and its test observes firing. Machine-readable twin: `docs/prds/one-dispatch-engine.capability-manifest.yaml`.

**Code anchors** verified against main `1fa8f796e87b608e6ee0ca9e8c62f377370203a7` (2026-10-16), cited by symbol. Measurements: `uv run --locked --extra dev python -I` probes and one `solar-challenge home run` on that SHA (PRD §2.2), with the cached Bristol TMY for the CLI and annual runs and synthetic profiles elsewhere.

**Batch verdict: PASS, with four cross-stream producers to wire at decompose.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `bound≤floor`. Out-of-batch producers, all upstream of the leaves that need them: 786 and 788 (α, β), 787 and 839 (S11 β) (ε), S4 α (δ). Intra-batch edges: γ→α, δ→α, δ→β, ε→α, ε→β, ζ→ε. Downstream: 790 → ε.

---

## α — One settle function both engines return through (intermediate)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| The settlement tail is duplicated verbatim | measured: `diff` of `simulate_timestep`'s and `simulate_timestep_tou`'s last 23 lines prints nothing; the preambles differ only by the TOU path's rate lookup | PASS |
| `simulate_timestep` is the production engine for every non-TOU-route home, the fleet and the community battery | grep: `home._strategy_timestep` and `community.simulate_community` call `simulate_timestep`; `home._minute_flows` runs every minute through the chosen timestep | PASS |
| Moving the tail changes no float | identity: `_settle` evaluates the same expressions in the same order on the same inputs; `_execute` makes the same Battery calls in the same order | PASS |
| `tests/unit/test_flow.py` pins today's flows on both paths | grep: 21 `simulate_timestep_tou` call sites and the `simulate_timestep` classes in `tests/unit/test_flow.py` | PASS |
| S2's flow edits land first (file order) | producer: 786, 788 (pending), upstream | PASS (queued) |
| Task 270 is the same work | read at authoring: task 270 pending, blocked on deferred 183; at decompose (2026-10-17) 270 is done (57ce3c2, `_settle_timestep`) and the preamble copy remains, so α files with `x_supersedes_task` 270 | PASS (supersedes done task) |

## β — One grid-charge gate sized from the SOC after the step's PV charge (intermediate)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| The gate block is copied in both strategies with a pre-step SOC basis | grep: `and grid_charge_ctx.is_cheap_period` twice in `dispatch.py` (`TOUOptimizedStrategy.decide_action`, `PeakShavingStrategy.decide_action`), each passing `battery_soc_kwh=battery_soc_kwh` | PASS |
| The controller holds the battery's charge model (charge efficiency, limit) | grep: `GridChargeContext.charge_efficiency`, `max_charge_kw`; gate 3 divides the gap by `charge_efficiency` | PASS |
| A capped target makes the post-PV prediction safe at the ceiling | producer: 788 work item 1 (`grid_charge_target_kwh = min(target_soc_fraction, max_soc_fraction) × effective_capacity_kwh`), upstream; extent: the cap | PASS |
| One-step signal: no grid charge where today 0.01625 kWh | measured: inline path 0.0 kWh / SOC 6.004375, strategy path 0.01625 kWh / SOC 6.020625; after β the gap is 6.0 − (5.98 + 1.5 × 1/60 × 0.975) < 0 (identity) | PASS |
| Day signal: strategy route grid-charges 5.045223 kWh, the inline figure | measured: `TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])` 5.047494 today vs inline 5.045223; with the post-PV gate emulated, per-minute flows agree to 1.776e-15 kWh | PASS |
| Economy 10's expensive hours are whole hours, so plain `peak_hours` reproduce its clock without S11 | read: `TariffConfig.economy_10` defaults 00:00-05:00, 13:00-16:00, 20:00-22:00 cheap | PASS |
| `compute_grid_charge_power_kw` has no external caller to break | read: platform never calls it (S2 §2.2); in `src` only the two strategies and `flow.simulate_timestep_tou` call it | PASS |

## γ — Settle on the energy the battery drew (leaf)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| `Battery.charge` returns stored energy and `discharge` delivered energy today | grep: `Battery.charge` returns `energy_stored_kwh` (after `charge_efficiency`); `Battery.discharge` returns `energy_output_kwh` (after `discharge_efficiency`) | PASS |
| Changing what `charge` returns changes no dispatch decision | grep: strategies read only `battery_soc_kwh`/`battery_capacity_kwh`/the context; `simulate_timestep_tou` sizes its top-up from `battery.soc_kwh`, not from the return; the SOC update is untouched | PASS |
| CLI signal: import 7.958723, export 0.000000, grid charge 2.178983 kWh, import cost £1.341602 (0.09/0.25) or £1.894444 (0.13/0.35) | measured: `home run` on `bristol-arbitrage.yaml` 2024-01-15 (cached TMY) gives import 7.904248, export 0.003741, grid charge 2.124508, cost £1.336699; the same per-minute flows settled on drawn energy (`stored / 0.975`) give the figures, and re-pricing the per-minute rates to 0.13/0.35 gives £1.887363 today and £1.894444 after (identity: dispatch is unchanged) | PASS |
| Other leaves leave those energies unchanged | read: the scenario's SOH is 1.0 and its target 0.9 equals `max_soc_fraction` (788 changes nothing); Economy 7 is two-rate (S11 α's identity); no PV in E7's cheap minutes on 2024-01-15 (β changes nothing); ε equal within 1e-9 kWh per minute; S11 γ (841) re-prices to 0.13/0.35, which keeps the spread gate open (0.35 > 0.13 / 0.950625) and the cheap minutes, so only the cost moves | PASS |
| `home run -o` writes `grid_import_kw`, `grid_export_kw`, `grid_charge_kw`, `import_cost_gbp` | observed: the CSV header of the run above | PASS |
| Storage identity holds after γ and fails today | identity from `Battery`'s update rules (SOC += drawn × η_c, capped as `stored = available`, `drawn = available / η_c`; SOC −= delivered / η_d); today `Σbattery_charge` is stored energy, so `η_c × Σbattery_charge` misses ΔSOC by `0.025 × Σstored` on any charging fixture | PASS |
| Bus readers need no edit | grep: `validate_energy_balance` (bus formula), `community.py`'s aggregate balance (`battery_charge − battery_discharge`), `home._price_imports` (`flow.grid_charge × rate`), `web/charts.sankey_diagram` (`total_battery_charge_kwh − total_grid_charge_kwh`, `total_grid_import_kwh − total_grid_charge_kwh`); finance reads import, cost, export, export revenue, discharge only | PASS |
| `SummaryStatistics`' grid-charge invariant holds on drawn energy | identity: drawn grid ≤ drawn total and ≤ import (import adds drawn grid) | PASS |
| Board scenario exists and takes the grid-charging TOU route | read: `scenarios/bristol-phase1-flex.yaml` (100 homes, Economy 7, `grid_charging`, fleet-level `dispatch_strategy: tou_optimized`) | PASS |
| The cost-recovery header carries Unreleased lines | grep: `docs/cost-recovery-finance-model.md` header "**Unreleased on main** (task …)" lines | PASS |
| Annual magnitude | measured: Bristol 2024, 4 kWp, `default_5kwh`, 3,400 kWh stochastic seed 42: 33.161 kWh of 1,683.931 kWh export is PV charge loss (1.97%) | PASS |

## δ — Bounded decisions and engine checks through `Interval.admits` (leaf)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| `Interval`, `NON_NEGATIVE`, `POSITIVE` in `solar_challenge.number_fields` | producer: S4 α (`docs/prds/finite-quantities.md` §5.1, authored, not yet filed), upstream out-of-batch dependency; extent: `Interval.admits` (finite and inside) and the named intervals | PASS (queued) |
| `Battery.max_charge_kw` for the limits | producer: 788 work item 1, upstream (δ → α → 788) | PASS |
| `_charge_headroom_kw` shared with the controller | producer: β, upstream (δ→β) | PASS |
| Over-limit sum is silently executed today | measured: `(5, 0, 5)` on a 2.5 kW battery stores 4.875 kWh in 60 minutes; balance passes | PASS (motivation) |
| PV charge above the excess, discharge above the shortfall reach the battery today | measured: `(2.5, 0, 0)` with no PV stores 2.4375 kWh, balance `in=0.000000, out=2.437500`; `(0, 2.5, 0)` vs 1.0 kW, balance `out=-1.500000` | PASS (motivation) |
| `DispatchDecision` accepts NaN and inf today | measured: `DispatchDecision(charge_kw=nan)` and `(charge_kw=inf)` construct | PASS (motivation) |
| The refusals exist and fire | rejection-mechanism built by δ and bound by `tests/unit/dispatch/test_decision_bounds.py` (PRD §9 rows 8-11): each fixture authored, `ValueError` observed naming the strategy, the field, the value and the limit, the battery's SOC unchanged | PASS |
| Built-in strategies never trip a bound | identity: each built-in sets `charge_kw = max(0.0, generation_kw − demand_kw)` (the limit's own expression), `discharge_kw` equal to the shortfall or the shortfall less the import limit, and after β `grid_charge_kw ≤ _charge_headroom_kw(max_charge_kw, charge_kw)` by the controller's `min`; PRD §9 row 12 runs them over five fixtures | PASS |
| The copied input block exists three times | grep: `if generation_kw < 0:` three times in `dispatch.py` | PASS |

## ε — Route the home-level `tou_optimized` through the factory; `simulate_timestep_tou` delegates (intermediate)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| `TOUOptimizedStrategy(tariff=)` on the tariff's clock, `TOUOptimizedStrategyConfig()` without `peak_hours`, the no-clock refusal, the flat-tariff arm | producer: 839, S11 β (`docs/prds/tariff-coverage-classifier-presets.md` §5.3-5.4, §9 rows 6-8), filed, upstream out-of-batch dependency; extent: the constructor's `tariff` keyword, the factory arm, both refusals | PASS (queued) |
| `build_dispatch_strategy` and `HomeConfig.__post_init__`'s factory step, `_runs_tariff_tou` | producer: 786 (factory) and 787 (work item 2, which extracts `_runs_tariff_tou` from `_dispatch_path` for S3 to delete), upstream | PASS |
| The tariff-TOU route exists to delete | grep: `home._dispatch_path`'s first branch returns `_DispatchPath("tou_optimized", _tariff_tou_timestep(tariff))`; `_tariff_tou_timestep` calls `simulate_timestep_tou` | PASS |
| The new route reproduces the inline path | measured with β's gate emulated: per-minute flows agree to 1.776e-15 kWh on the morning-drain E10 day (three initial SOCs); equal on E7/E10 days and two `simulate_home` June days; S11 §2.1 measured equal flows on `bristol-arbitrage.yaml` 2024-01-15 | PASS (needs β upstream) |
| `strategy_name` stays `tou_optimized` | grep: `TOUOptimizedStrategy.name` returns `"tou_optimized"`; `_DispatchPath` records `strategy.name` on the strategy route | PASS |
| The briefing decision and scenario comment exist to correct | grep: `review/briefing.yaml` "Two dispatch paths coexist"; `scenarios/bristol-arbitrage.yaml` "routes through the function path (simulate_timestep_tou" | PASS |

## ζ — Retire `simulate_timestep_tou` at the bump (held leaf)

| Capability asserted | Evidence binding | Status |
|---|---|---|
| The public name exists in every surface table | grep: `__init__.__all__`, `_SYMBOL_MODULE` (`"simulate_timestep_tou": "flow"`), the `TYPE_CHECKING` import, `FROZEN_SURFACE` in `tests/unit/test_public_api_surface.py` | PASS |
| Its test call sites are countable | grep: 21 `simulate_timestep_tou` sites in `tests/unit/test_flow.py`, none elsewhere in `tests/` but the surface test | PASS |
| The replacement call exists | producer: ε (the delegate's body is the recipe), upstream | PASS |
| Release window | S29's bump window; held with `x_seam_wait` | PASS (held) |
