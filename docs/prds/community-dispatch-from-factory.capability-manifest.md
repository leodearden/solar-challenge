# Capability manifest: Community, dispatch from the factory (review-all stream S27)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise holds) for each leaf of `docs/prds/community-dispatch-from-factory.md`. Each capability a leaf's signal asserts is bound to one of four kinds of evidence: a symbol read on main and wired into the production path, a producer leaf upstream (in this batch or another stream's), a measurement taken for this PRD, or a rejection mechanism that the leaf's test observes firing. The machine-readable twin is `docs/prds/community-dispatch-from-factory.capability-manifest.yaml`.

**Code anchors** were verified against main `ac1fdf18ef8cde1a13d69eae3ae81333d72f6a73` (2026-10-17) and are cited by symbol. Measurements came from a `uv run --locked --extra dev python -I` probe on that SHA. The probe simulated `scenarios/bristol-community.yaml`'s fleet over 2024-01-15 sequentially with the repo's weather cache, then ran a community block with `peak_shaving` (3.0 kW), `grid_charging` 0.9 and an Economy 7 billing tariff two ways: through today's `simulate_community`, and through a factory-equivalent loop (`PeakShavingStrategy(3.0)` stepped by `simulate_timestep(..., tariff=E7)`).

**Batch verdict: PASS, with two cross-stream producers to wire at decompose.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `bound≤floor`. The out-of-batch producers are both upstream of the leaves that need them: 786 and 787 (S2 α, β) for α, and S16 α for β. The intra-batch edges are β→α and γ→β, and γ is held for S29.

---

## α: the community battery dispatches through the factory with the community tariff (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| `dispatch.build_dispatch_strategy(config, *, grid_charging, tariff)` and `SelfConsumptionStrategyConfig` exist | producer: 786 (S2 α), pending, upstream as α's out-of-batch dependency. Both are absent on main (`grep build_dispatch_strategy src` finds nothing) | PASS (queued prerequisite) |
| The factory refuses `grid_charging` under self-consumption and without a tariff, naming both | producer: 787 (S2 β), pending, upstream. Its work item 1 defines the two refusals and their required names, and its consumer_ref names S27 | PASS (queued prerequisite) |
| The community parser populates `BatteryConfig.dispatch_strategy` and `grid_charging` | measured: `_parse_community_config` → `_parse_battery_config` parses a `community_battery` block holding `dispatch_strategy {peak_shaving, 3.0}` and `grid_charging {0.9}` (probe printed both) | PASS |
| `simulate_timestep` takes `tariff=` and offers the strategy a grid-charge context when the battery grid-charges | grep: `flow.simulate_timestep(..., strategy, *, tariff)`. Measured: the factory-equivalent loop grid-charges 8.000 kWh in the E7 window | PASS |
| SOC at 07:29 ≥ 0.85 × 20 kWh with the named strategy, against 2.000 today | measured: 17.485 kWh (0.874) after, and 2.000 today. The bound is below the measurement and below the 0.9 target cap of 18.0 kWh, so the leaf's change produces it. S3 γ's bus-basis charge changes the drawn energy, not the stored SOC path the target caps | PASS |
| Community Grid Import rises (55.9 → 58.8 kWh) | measured: 55.933 kWh today, 58.824 kWh after. The CLI table prints `m.community_import_kwh` from `output.compute_community_metrics` | PASS |
| `CommunityConfig` construction errors reach `fleet run` as `Configuration error`, exit 1 | grep: `_parse_community_config` wraps `CommunityConfig(...)` in `except ValueError` → `ConfigurationError`, and `cli/utils.handle_errors` prints `Configuration error` and exits 1 for it | PASS |
| The refusal precedes the simulation | grep: `cli/fleet.py::run` calls `load_community_config(config)` after `simulate_fleet_iter` today, so α moves it above `print_info("Simulating fleet …")`. The signal observes the line's absence | PASS (built by α) |
| A half-specified billing block warns, naming the missing input | measured: a tariff-only `CommunityBillingConfig` gives `community_savings_gbp is None` and no warning today. α's test observes the `UserWarning`. Precedent: `home.simulate_home`'s tariff-without-SEG `UserWarning` | PASS (rejection-style, built and observed by α) |
| No existing test builds a community battery that α refuses | grep: no `grid_charging` or `dispatch_strategy` in `test_community.py`, `config/test_community_block.py`, `test_community_fleet.py` | PASS |
| The briefing note α replaces exists | grep: `review/briefing.yaml` "the community battery currently hardcodes SelfConsumptionStrategy" | PASS |

## β: fleet and community values are frozen and built once (leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| One `FleetResults` assembly in `fleet.py` (plus `web/storage`'s rebuild) | producer: S16 α (`fleet-execution-policy.md` α, I1), upstream, with the id from the lead. Until it lands there are five `FleetResults(` sites in `src` | PASS (queued prerequisite) |
| Nothing assigns these classes' fields after construction except `simulate_community`'s billing | measured: grep over `src` and `tests` for field assignment and list mutation of `homes`, `home_configs`, `per_home_results` and the `CommunityResults` fields finds only `community.py`'s three billing lines | PASS |
| Lists passed at construction keep working | built by β (conversion in `__post_init__`). Measured: about 50 test sites and the platform construct with lists, and none of them assigns a field | PASS |
| Stored fleet runs reload with tuple fields | grep: `web/storage._deserialize_value` rebuilds `tuple[X, ...]` (`origin is tuple`), and `RunStorage.load_fleet_run` constructs `FleetResults` | PASS |
| The surface forms change only in `FROZEN_SURFACE` | grep: `tests/unit/test_public_api_surface.py` pins `FleetConfig`, `FleetResults` and `CommunityResults` as `dataclass[eq]`, and β edits the three entries | PASS |
| `fleet run` output unchanged | β changes no arithmetic, and `simulate_community`'s billing values are computed from the same series before construction | PASS |

## γ: the sharing mode is derived from the community battery (held leaf)

| Capability asserted by the signal | Evidence binding | Status |
|---|---|---|
| The double encoding and its checks exist (re-measured) | measured: 3 ifs in `CommunityConfig.__post_init__` (1 vocabulary, 2 consistency). `simulate_community` branches on `cb_config is None`, `output.CommunityMetrics.sharing_mode: str`, and the parser requires the key. 61 `sharing_mode=` sites | PASS (finding re-measured, §2.3) |
| The retired key is refused by name | rejection-mechanism built by γ: the `_COMMUNITY_BLOCK_KEYS` table drives `_refuse_unrecognised_keys` today, and γ adds the named retirement message. γ's test observes it | PASS |
| One scenario file carries the key | grep: `scenarios/` matches `sharing_mode` only in `bristol-community.yaml` | PASS |
| The surface bump window | producer: S29 releases γ (`x_seam_wait`) | PASS (held) |
