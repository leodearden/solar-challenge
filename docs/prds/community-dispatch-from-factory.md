# PRD — Community: dispatch from the factory, mode derived from the battery (review-all stream S27)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S27** (wave 2, size S, risk low, upstream S2). Findings record `plans/review-all-solar_challenge-20261013.json`, run `review-all-solar_challenge-20261013`.
- **Status:** authored 2026-10-17 in the agent-mode /prd pass (D45); not committed, not decomposed.
- **Binding rulings:** D3 (a `grid_charging` the dispatcher would ignore is refused at construction; mid-term every dispatcher, the community battery included, grid-charges), D5 (one tagged union of strategy configs on `BatteryConfig`), D6 (one dispatch engine, S3), D29 (additive frozen-table edits land in-leaf with an Unreleased line; renames and retirements are held for S29), D4 (one coordinated bump), L8 (the D3 mid-term design follow-up is the lead's, after S3 and S11).
- **Seam followed, not owned:** the dispatch factory `dispatch.build_dispatch_strategy` is S2's (program §Seam ownership); this stream is its community call site. The program's cross-reference line fixes the call: `build_dispatch_strategy(community_battery.dispatch_strategy or SelfConsumptionStrategyConfig(), grid_charging=..., tariff=billing.tariff)` from `CommunityConfig.__post_init__` and `simulate_community`, depending on S2 α (786) and β (787).
- **Approach:** bare **B** with a short contract (§5) and boundary table (§9). The stream changes no shared seam. It calls S2's factory and S16's runner and builds neither, so the B + H work for both seams sits in their PRDs.
- **Code anchors** verified against main `ac1fdf18ef8cde1a13d69eae3ae81333d72f6a73` (2026-10-17), cited by symbol; re-locate lines at implementation time. `git diff 7dfea36e..ac1fdf1` over the files this PRD touches: `community.py`, `output.py` and `cli/fleet.py` changed (task 743's prose edits, task 712's report changes); `fleet.py`'s `FleetConfig`/`FleetResults` and `config._parse_community_config` did not change in substance.

Finding keys (all `simulation-core`): fk-664e2030921e (medium, confirmed, mechanical), fk-083990041fdc (low, weakened, structural), fk-dc5cf2ec9b84 (low, confirmed, mechanical), fk-8995288451e6 (low, confirmed, structural).

---

## 1. Goal

A community battery dispatches by the strategy its configuration names, through the same factory that dispatches every home's battery, and sees the community's tariff. A setting the community would ignore is refused before any home is simulated, and a billing block too incomplete to price the grid flows says so by name. The community's results, and the fleet results and configuration they are computed from, are values that cannot change after construction. Whether a community shares through a battery is stated once, by the presence of that battery.

**What a user observes when this lands:**

1. `solar-challenge fleet run` on a copy of `scenarios/bristol-community.yaml` whose `community_battery` block adds `grid_charging: {target_soc_fraction: 0.9}` exits 1 with `Configuration error` naming `grid_charging` and `self_consumption`, before any home is simulated. Today the file runs, the community battery never charges from the grid, and nothing says so.
2. The same copy with `dispatch_strategy: {strategy_type: peak_shaving, import_limit_kw: 3.0}` in its `community_battery` block and an Economy 7 `billing.tariff` charges the community battery overnight. Over 2024-01-15 its SOC at 07:29 is 17.49 kWh of 20, against 2.00 today, and the CLI's Community Grid Import rises from 55.9 to 58.8 kWh because the battery buys cheap energy. Today the strategy and the grid charging both parse and are both ignored.
3. A `billing:` block with a tariff and no SEG rate, or the reverse, prints one warning naming the missing input and the three billing figures that stay empty. Today the billing rows silently vanish from the CLI table and the report.
4. A library consumer that assigns to a `CommunityResults`, `FleetResults` or `FleetConfig` field gets `FrozenInstanceError`. `simulate_fleet`'s result holds its own tuple of the homes, so appending to the configuration's list afterwards can no longer change it.
5. At the program's bump (S29), a `community:` block states its mode only by having, or not having, a `community_battery`. `CommunityConfig(community_battery=BatteryConfig(20.0)).sharing_mode` is `"community_battery"`, and a file still carrying `sharing_mode:` is refused with a message saying the mode follows `community_battery`.

## 2. Background (measured at `ac1fdf1`)

### 2.1 The community battery today

- `community.simulate_community` builds `Battery(cb_config)` and `SelfConsumptionStrategy()` and calls `flow.simulate_timestep(..., strategy=strategy)` with no `tariff=`. `config._parse_community_config` parses `community_battery` with the full home-battery grammar (`_parse_battery_config`), so `dispatch_strategy` and `grid_charging` blocks parse. Probe on this SHA: a `community_battery` block with `peak_shaving` (`import_limit_kw: 3.0`), `grid_charging` 0.9 and an Economy 7 billing tariff parses. Over 2024-01-15 on `bristol-community.yaml`'s fleet (sequential, repo weather cache), today's run gives community import 55.933 kWh and SOC at 07:29 2.000 kWh. A factory-equivalent loop (`PeakShavingStrategy(3.0)`, `simulate_timestep(..., tariff=E7)`) gives 58.824 kWh, SOC 17.485 kWh and grid charge 8.000 kWh.
- `review/briefing.yaml`'s key_decision for `community.py` records "the community battery currently hardcodes SelfConsumptionStrategy — it cannot yet dispatch on TOU/peak-shaving".
- `simulate_community` prices billing only when both `billing.tariff` and `billing.seg_rate_pence_per_kwh` are set. Probe: `CommunityBillingConfig(tariff=E7)` alone gives `community_savings_gbp is None` and no warning. `simulate_home`'s own "tariff_config is set but seg_tariff is None" `UserWarning` is the precedent for warning on a half-specified price.
- `cli/fleet.py::run` calls `load_community_config(config)` *after* simulating and printing the fleet, so any community refusal arrives after the whole simulation.
- No existing test sets `grid_charging` or `dispatch_strategy` on a community battery (grep of `tests/unit/test_community.py`, `tests/unit/config/test_community_block.py`, `tests/integration/test_community_fleet.py`), so α's refusal breaks no test.

### 2.2 Mutable results and configuration

- `FleetConfig` (`homes: list[HomeConfig]`) and `FleetResults` (`per_home_results`, `home_configs`, both lists) are plain `@dataclass`es; `CommunityResults` is too, and `simulate_community` assigns its three billing fields after constructing it. `simulate_fleet` and `collect_multi_sweep_results` pass `config.homes` itself as `home_configs`, so a result aliases its configuration. `FleetResults` re-runs `_require_paired_homes` in `get_aggregate_series`, and `calculate_fleet_summary` calls that private method from outside the class.
- Measured: no site in `src` or `tests` mutates a `FleetConfig`, `FleetResults` or `CommunityResults` field after construction other than `simulate_community`'s three billing assignments. Two test assertions compare `home_configs` with a list (`tests/unit/test_finance_builders_helper.py`). Construction sites in `src`: six `FleetConfig(` (`config` ×3, `finance` ×2, `optimize`) and five `FleetResults(` (`fleet` ×2, `cli/fleet`, `web/storage`, `web/jobs`). After S16 α only `fleet.py` and `web/storage`'s disk rebuild assemble `FleetResults` (S16 I1). `web/storage._deserialize_value` already rebuilds `tuple[X, ...]`.
- All three are in `__all__` and pinned in `FROZEN_SURFACE` (`tests/unit/test_public_api_surface.py`) as `dataclass[eq]`. Main's precedent for freezing a pinned results type in-leaf is task 436 (`SimulationResults`), with an Unreleased line in `docs/domain-library-consumption.md`.
- Platform consumer (`solar-challenge-platform` at its current main): it builds `FleetConfig(homes=[...])`, `FleetConfig.create_heterogeneous(...)` and `FleetResults(per_home_results=[...], home_configs=[...])` and reads `config.homes` by `len` and iteration. It never assigns a field, and it never uses the community types.
- Task 669 (pending) proposes freezing nine non-frozen pinned dataclasses, `FleetConfig`, `FleetResults` and `CommunityResults` among them.

### 2.3 The sharing mode (D28-style re-measure of the weakened key fk-083990041fdc)

- The fact is still encoded twice: `CommunityConfig.sharing_mode: Literal["p2p", "community_battery"]` and `community_battery: Optional[BatteryConfig]`. `__post_init__` has 3 ifs: 1 vocabulary guard and 2 mode/battery consistency checks. `simulate_community` branches on `cb_config is None`, while its docstring says "Two dispatch branches are selected by *config.sharing_mode*". `output.CommunityMetrics.sharing_mode` is typed `str`. The parser requires `sharing_mode`. The skeptic's correction stands and is adopted: of the 3 checks, 2 relate mode to battery. Re-counted with `grep -E 'p2p|community_battery|sharing_mode'`: config.py 11, community.py 35 raw / 34 code, output.py 5 raw / 4 code. `sharing_mode=` appears at 61 sites: community.py 8, config.py 1, output.py 1, test_community.py 35, test_community_fleet.py 14, test_community_block.py 1, test_unrecognised_keys.py 1. The decomposing session records this on γ.

### 2.4 fk-dc5cf2ec9b84 has landed

Task 743 is `done` (commits `ee518f3`, `b4091d9`, merged `d64a2bf`). The planning-slice labels, the `home.simulate_home:299-300` pointer and the symbol re-list are gone from `community.py`, and the δ/η labels are gone from `output.py`. One residue of the same pattern, outside the finding's site list, remains in `cli/fleet.py`'s community section: "(task ε / #34)", and "Strictly additive … byte-unchanged" at two sites. α deletes it because it edits those lines anyway (§10). The Deletable column's "Greek/task labels at 8 sites" is already met.

## 3. Rulings that bind, and how this PRD reads them

- **D3.** The community battery's `grid_charging` is refused by the factory's arms exactly as a home battery's is, when the `CommunityConfig` is built. Under self-consumption the refusal names `self_consumption`. With no `billing.tariff` it names the missing tariff. On a tariff with no cheap period it fires once S11 β's arm lands. The mid-term direction (grid charging under every dispatcher) arrives here for free when L8's follow-up deletes the factory's refusal arm, because the community reads the same arm.
- **D5 / D6.** The community holds no strategy vocabulary and no dispatch path of its own. It hands `BatteryConfig.dispatch_strategy` to the factory and steps through `simulate_timestep`, the one engine S3 keeps.
- **D29 / D4.** Freezing the three classes and narrowing their list fields to tuples changes the frozen forms, but it is neither a rename nor a retirement, and main froze `SimulationResults` in-leaf (task 436). β therefore lands in-leaf with its `FROZEN_SURFACE` edit and Unreleased line (§12 Q1). Retiring the `sharing_mode` constructor parameter is a retirement, so γ is held for S29.

## 4. Sketch of approach

1. **α — the factory dispatches the community battery.** `community.py` gains one private function that builds the battery's strategy from its config and the community's tariff. `CommunityConfig.__post_init__` calls it, so the construction-time check is D3's. `simulate_community` calls it again for the run, which is the use-time call, and passes `tariff=` to `simulate_timestep`. `simulate_community` warns once when a billing block is half-specified. `cli/fleet.py::run` reads the community block before simulating.
2. **β — values, built once.** `CommunityResults`, `FleetResults` and `FleetConfig` are frozen with tuple fields. `simulate_community` computes billing before constructing its result. `FleetResults` enforces pairing at construction only.
3. **γ (held) — the mode is derived.** `CommunityConfig` loses the `sharing_mode` field. `sharing_mode` becomes a read-only property derived from `community_battery`, and the vocabulary is one `SharingMode` alias read by the config, the results and the report. The YAML key is retired.

## 5. Contract

### 5.1 The community's strategy (α)

```python
def _battery_strategy(
    battery: BatteryConfig, billing: CommunityBillingConfig | None
) -> DispatchStrategy:
    return build_dispatch_strategy(
        battery.dispatch_strategy or SelfConsumptionStrategyConfig(),
        grid_charging=battery.grid_charging,
        tariff=billing.tariff if billing is not None else None,
    )
```

- This is the community's one statement of which strategy runs and what it sees. Two callers read it: `CommunityConfig.__post_init__`, which calls it when `community_battery` is set and discards the strategy, and `simulate_community`, which builds the run's strategy with it. It is private, not on the surface. S2 ε drops the `or SelfConsumptionStrategyConfig()` when `BatteryConfig.dispatch_strategy` gains that default.
- Refusals come only from the factory's arms: S2 β's two, S11 β's flat-tariff arm, and S11's tariff-clock arm for `TOUOptimizedStrategyConfig(peak_hours=None)` without a tariff. They propagate unchanged. `config._parse_community_config` already converts a `ValueError` from `CommunityConfig` into `ConfigurationError`, and after S1 β `ConfigurationError` is a `ValueError`. Like S2 β's `HomeConfig` refusals, these carry no block path.
- `simulate_community`'s battery branch calls `simulate_timestep(..., strategy=strategy, tariff=tariff)` with the same `tariff`. The engine then offers a grid-charge context exactly when that tariff is set and the battery grid-charges (S2 §5.2), so the community gets the home's contract unchanged. Every community step goes through S3 δ's bound and γ's bus settlement, and `validate_community_balance` needs no change: the battery's charge and the grid import both include the grid-charge energy, so the composition identity holds (S3 §8 row S27).
- The p2p branch is unchanged.

### 5.2 Half-specified billing (α)

- When `config.billing` is not `None` and either of its inputs is `None`, `simulate_community` emits one `UserWarning` (`stacklevel=2`). The warning names each missing input as `billing.tariff` or `billing.seg_rate_pence_per_kwh`, and names the three result fields that stay `None`. It emits nothing when billing is absent or complete. One warning per call, matching `simulate_home`'s tariff-without-SEG precedent.
- A tariff-only billing block is legitimate configuration: its tariff drives the battery's dispatch (§5.1). So it is warned about, not refused. The program row's remedy ("warns once naming the missing inputs") is followed, not the finding's alternatives (refuse, or price the import leg alone).

### 5.3 Frozen values (β)

```python
@dataclass(frozen=True)
class FleetConfig:
    homes: tuple[HomeConfig, ...] = ()
    name: str = ""

@dataclass(frozen=True)
class FleetResults:
    per_home_results: tuple[SimulationResults, ...]
    home_configs: tuple[HomeConfig, ...]

@dataclass(frozen=True)
class CommunityResults:  # fields and order unchanged
    ...
```

- Each sequence field is stored as a tuple. `__post_init__` converts whatever sequence it is given with `object.__setattr__(self, name, tuple(value))` before validating, so a caller that passes a list keeps working at run time: the platform, about 50 test sites. `src` callers pass tuples, which `mypy --strict` checks. A result never shares a sequence with its configuration.
- `FleetConfig.__post_init__` keeps its non-empty and single-timezone checks. The checks now hold for the object's whole lifetime.
- `FleetResults.__post_init__` is the one pairing check. `_require_paired_homes`'s call in `get_aggregate_series` and `calculate_fleet_summary`'s outside call go, and the private method folds into `__post_init__`.
- `simulate_community` computes `baseline_net_cost_gbp`, `community_net_cost_gbp` and `community_savings_gbp` before it constructs its one `CommunityResults`, in both branches. The pricing reads the branch's grid series, not the constructed result.
- `MultiSweepResults` and `FleetSummary` are out of scope. They are not in this stream's keys.

### 5.4 Mode from the battery (γ, held)

```python
SharingMode: TypeAlias = Literal["p2p", "community_battery"]

@dataclass(frozen=True)
class CommunityConfig:
    community_battery: Optional[BatteryConfig] = None
    billing: Optional[CommunityBillingConfig] = None

    @property
    def sharing_mode(self) -> SharingMode:
        return "p2p" if self.community_battery is None else "community_battery"
```

- `__post_init__` keeps only α's strategy check: the vocabulary guard and the two consistency ifs go. `CommunityResults.sharing_mode: SharingMode` stays a field, set from `config.sharing_mode` (the results' record of the run, kept since task 86 retired the report's heuristic). `output.CommunityMetrics.sharing_mode` is typed `SharingMode`. `simulate_community`'s docstring says the branch follows `community_battery`.
- Grammar: `_COMMUNITY_BLOCK_KEYS` loses `sharing_mode`. A block that still carries it is refused with a `ConfigurationError` naming `community.sharing_mode` and saying that a community with a `community_battery` block shares through it and one without nets peer to peer. This follows S2 ε, which refuses its own retired key the same way. An empty `community: {}` block is a p2p community. `scenarios/bristol-community.yaml` drops its `sharing_mode:` line and the comment that explains it.
- `CommunityConfig`'s first positional parameter disappears, so `CommunityConfig("p2p")` becomes a `TypeError`: the S29 ledger line (§5.5).

### 5.5 Surface ledger for S29

| Leaf | Change | Consumer action |
|---|---|---|
| α | Building a `CommunityConfig` whose `community_battery` sets `grid_charging` under self-consumption dispatch, or with no `billing.tariff`, raises `ConfigurationError`; a community battery runs the strategy its `dispatch_strategy` names, with the billing tariff; a half-specified billing block warns | Platform: none (no community use). Unreleased line in-leaf |
| β | `FleetConfig`, `FleetResults`, `CommunityResults` are frozen; `FleetConfig.homes`, `FleetResults.per_home_results` and `home_configs` are tuples (a list is accepted and stored as a tuple) | Platform: none at run time; its type checker sees `tuple` (pass a tuple, or keep the list). Unreleased line in-leaf |
| γ (held) | `CommunityConfig.sharing_mode` is a read-only property derived from `community_battery`; the constructor loses `sharing_mode`; the YAML key is refused | Scenario files: delete `sharing_mode:`. Callers: drop the argument |

## 6. Resolved design decisions

1. **The community calls the factory; it does not refuse strategies.** Task 706's proposal was to refuse a `community_battery` carrying `dispatch_strategy` or `grid_charging`. The program's remedy honours them instead, because a peak-shaving or TOU community battery is meaningful at the connection point. Honouring them through S2's factory gives the community D3's refusals and S11's arms with no community-owned check.
2. **One private strategy builder, two calls.** The construction check and the run must build the same strategy from the same inputs, so both read one function rather than two copies of the call's arguments (SPOT). The check builds and discards a strategy, as S2 β's `HomeConfig` check does.
3. **The community's tariff is `billing.tariff`.** The community has one tariff, its import tariff, and it prices the grid flows the battery's dispatch changes. The program's cross-reference line fixes this, and §5.2 keeps a tariff-only billing block legal for that reason.
4. **Warn, do not refuse, a half-specified billing block.** A tariff-only block is valid dispatch configuration (decision 3). The program row's remedy is a warning naming the missing inputs.
5. **Fail before simulating.** `cli/fleet.py::run` reads the community block before it simulates, so α's refusal costs nothing. The move is one call.
6. **Accept lists, store tuples.** A frozen class holding a caller's list would keep the aliasing finding open. Refusing lists would break the platform and about 50 tests for no gain. Converting in `__post_init__` makes "stored as a tuple" an invariant enforced at construction (heuristic 10).
7. **Freezing lands in-leaf; retiring `sharing_mode` is held.** D29 holds only renames and retirements. Task 436 froze `SimulationResults` in-leaf, and nothing in `src`, the tests or the platform assigns these fields.
8. **Derive the mode, do not split the type.** A frozen variant per mode would rename `CommunityConfig` for a two-valued fact with no third mode planned, and the finding's skeptic weighted it low. A property keeps the frozen name and removes the second encoding.
9. **Retire the YAML key with a named refusal.** Tolerating an agreeing `sharing_mode:` would keep the vocabulary and a consistency check in the parser, the finding's complaint. S2 ε refuses its retired key the same way. One scenario file carries the key.

## 7. Pre-conditions

- **S2 α (786)** lands before α: `dispatch.build_dispatch_strategy`, `SelfConsumptionStrategyConfig` and the tagged `BatteryConfig.dispatch_strategy`. Neither exists on main at `ac1fdf1`.
- **S2 β (787)** lands before α. It supplies the factory's two D3 refusals α's signal 1 relies on. Without them the factory is the plain mapping and a self-consumption community battery with `grid_charging` would still run and ignore it.
- **S16 α** (`docs/prds/fleet-execution-policy.md` α; id from the lead when S16 files) lands before β. It owns `fleet.py`'s runner and reduces fresh `FleetResults` assembly to `fleet.py`. β then freezes the classes over one assembly site instead of three, and does not contend with S16 α for `fleet.py`.
- **S29's bump window** for γ.

G3: every symbol this PRD names as existing was read at `ac1fdf1` (capability manifest). The new substrates are the S2 factory and the S16 runner, both queued prerequisites.

## 8. Cross-PRD relationship

| Other stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S2 dispatch configuration (`dispatch-configuration-below-config.md`) | consumes | `build_dispatch_strategy(config, *, grid_charging, tariff)`, `SelfConsumptionStrategyConfig`, `BatteryConfig.dispatch_strategy` union, β's refusals | S2 | α depends on 786, 787 (matches S2 §8 row S27) |
| S2 ε (790, held) | produced for | `community._battery_strategy`'s `or SelfConsumptionStrategyConfig()` goes when the default lands | S2 ε | cross-reference; no edge |
| S3 one dispatch engine (`one-dispatch-engine.md`) | consumes | community steps go through `simulate_timestep`'s bound (δ) and bus settlement (γ); `validate_community_balance` unchanged | S3 | no edge (S3 §8 row S27); test_community.py expectations re-derived by S3 γ if it lands first |
| S11 tariff (`tariff-coverage-classifier-presets.md`) | consumes | factory's flat-tariff grid-charging refusal (β) and tariff-clock arm reach the community through §5.1 | S11 | no extra edge (S11 §8 row S27) |
| S16 fleet execution (`fleet-execution-policy.md`) | shares `fleet.py`, `cli/fleet.py` | S16 α owns the runner and the one `FleetResults` assembly; β freezes the classes that assembly builds; S16 ε's `reusing` builds `FleetResults(per_home_results=results.per_home_results, home_configs=fleet.homes)`, tuple-safe | S16 runner / S27 class forms | β depends on S16 α; α's two-line `cli/fleet.py` move is a file overlap with S16 α/β (textual) |
| S1 errors leaf | consumes | `ConfigurationError(ValueError)` from the factory propagates through `_parse_community_config`'s `except ValueError` | S1 | transitively via 787 |
| S4 finite quantities (`finite-quantities.md`) | file overlap | S4 γ converts `CommunityConfig`'s sharing_mode refusals to `ConfigurationError` (L1); γ deletes them | S4 / S27 | order-agnostic |
| S5 config partition | file overlap | `_parse_community_config` may move into `scenario_blocks.py`; γ edits it wherever it lives | S5 | order-agnostic |
| S23 surface lock | file overlap | β and γ edit `FROZEN_SURFACE` (or S23's successor module) | S23 module | parallel |
| S29 surface bump | produces for | §5.5 ledger; γ held | S29 | γ held |
| Task 669 | overlaps | freezing `FleetConfig`, `FleetResults`, `CommunityResults` moves to β | S27 β | decompose: amend 669's details to drop the three (as 786 did for `DispatchStrategyConfig`) |
| Task 706 | superseded | fk-664e2030921e, refuse-instead-of-honour proposal | S27 α | decompose: cancel with `x_superseded_by` α after §8 step 1 |

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|
| 1 | Self-consumption community battery with grid charging is refused | `CommunityConfig(community_battery=BatteryConfig(20, grid_charging=GridChargeConfig(0.9)))`, with and without an E7 billing tariff | `ConfigurationError` naming `grid_charging` and `self_consumption`; YAML block via `load_community_config` raises the same | α |
| 2 | Grid charging without a tariff is refused | `peak_shaving` (3.0 kW) + `grid_charging` 0.9, billing `None` and billing SEG-only | `ConfigurationError` naming `grid_charging` and the tariff | α |
| 3 | The named strategy runs with the tariff | `bristol-community.yaml`'s fleet over 2024-01-15 (`synthetic`/cached weather as the suite seeds it), battery `peak_shaving` 3.0 kW + `grid_charging` 0.9 + E7 billing | SOC at 07:29 ≥ 0.85 × 20 kWh (17.485 at authoring; today 2.000); community import kWh greater than the same fleet under a self-consumption community battery; `validate_community_balance` passes | α |
| 4 | Default community battery unchanged | today's `bristol-community.yaml` | community series equal to the pre-α run (self-consumption, no grid-charge context offered) | α |
| 5 | Half-specified billing warns once | billing tariff-only; SEG-only; both set; absent | exactly one `UserWarning` naming `billing.seg_rate_pence_per_kwh` (resp. `billing.tariff`) and the three fields; none when complete or absent; billing fields `None` in the warned cases | α |
| 6 | Refused before simulating | `fleet run` (CliRunner) on the row-1 YAML | exit 1, `Configuration error` naming `grid_charging`; the output has no "Simulating fleet" line (the community block is read before `print_info` announces the simulation) | α |
| 7 | Frozen and unaliased | `FleetConfig(homes=[h])`; `simulate_fleet` on it (fake home simulator); `simulate_community` | `.homes == (h,)`; `results.home_configs is not` the config's input list and is a tuple; assigning any field of the three raises `FrozenInstanceError`; billing fields equal the pre-β values | β |
| 8 | Pickle and storage round trip | a stored fleet run through `RunStorage` | loads with tuple fields, equal to saved; `FleetResults` pickles | β |
| 9 | Mode derived (held) | `CommunityConfig()`; `CommunityConfig(community_battery=BatteryConfig(20))`; YAML with `sharing_mode:` | `sharing_mode` `"p2p"` / `"community_battery"`; the YAML is refused naming `community.sharing_mode`; migrated `bristol-community.yaml` gives the same community table | γ |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`; priority is its key's severity.

**α — The community battery dispatches through the factory with the community tariff** (leaf; priority medium)
- Keys: fk-664e2030921e.
- Work: §5.1 and §5.2. `community.py`: `_battery_strategy`, its call in `CommunityConfig.__post_init__` and in `simulate_community`'s battery branch, `tariff=` on `simulate_timestep`, the `SelfConsumptionStrategy` import goes, the half-billing warning, and the docstrings that say "with SelfConsumptionStrategy". `cli/fleet.py::run` reads `load_community_config(config)` before simulating; its "(task ε / #34)" label and the two "strictly additive / byte-unchanged" comments go (§2.4). `review/briefing.yaml`: the community key_decision's "hardcodes SelfConsumptionStrategy" note is replaced by "runs `dispatch.build_dispatch_strategy` with the billing tariff". Unreleased line from §5.5 row α. Tests: §9 rows 1-6 in `tests/unit/test_community.py`, `tests/unit/config/test_community_block.py` and `tests/integration/test_community_fleet.py`. Absorbs task 706.
- Files: `src/solar_challenge/community.py`, `src/solar_challenge/cli/fleet.py`, `tests/unit/test_community.py`, `tests/unit/config/test_community_block.py`, `tests/integration/test_community_fleet.py`, `review/briefing.yaml`, `docs/domain-library-consumption.md`.
- Signal: `solar-challenge fleet run` on a copy of `scenarios/bristol-community.yaml` whose `community_battery` adds `grid_charging: {target_soc_fraction: 0.9}`, `--start 2024-01-15 --end 2024-01-15`, exits 1 with `Configuration error` naming `grid_charging` and `self_consumption` and prints no "Simulating fleet" line. Today it runs to the community table. The copy with `dispatch_strategy: {strategy_type: peak_shaving, import_limit_kw: 3.0}` and `billing.tariff: {type: economy_7}` runs, and its Community Grid Import exceeds today's 55.9 kWh (58.8 at authoring). The original file's billing block minus `seg_rate_pence_per_kwh` prints a warning naming `billing.seg_rate_pence_per_kwh`. §9 rows 1-6.
- Prereqs: 786 (S2 α), 787 (S2 β).

**β — Fleet and community values are frozen and built once** (leaf; priority low)
- Keys: fk-8995288451e6.
- Work: §5.3. `fleet.py`: `FleetConfig` and `FleetResults` are frozen with tuple fields converted in `__post_init__`; `_require_paired_homes` folds into `__post_init__`, so its re-check in `get_aggregate_series` and `calculate_fleet_summary`'s outside call go; the classmethods and every `src` construction site pass tuples (`config`, `finance`, `optimize`, `web/storage`, and the sites S16 α leaves). `community.py`: `CommunityResults` is frozen and built once, with billing computed first. `FROZEN_SURFACE` forms for the three. Unreleased line from §5.5 row β. `review/briefing.yaml`'s frozen-config convention needs no edit: β brings three classes into line with it. Tests: §9 rows 7-8; the two list comparisons in `test_finance_builders_helper.py`; any test that built these with lists still passes (run-time conversion). Task 669: amend its details to drop the three classes.
- Files: `src/solar_challenge/fleet.py`, `src/solar_challenge/community.py`, `src/solar_challenge/{config,finance,optimize}.py`, `src/solar_challenge/web/storage.py`, `tests/unit/test_fleet.py`, `tests/unit/test_community.py`, `tests/unit/test_finance_builders_helper.py`, `tests/unit/test_web_storage_roundtrip.py`, `tests/unit/test_public_api_surface.py` (or S23's successor), `docs/domain-library-consumption.md`.
- Signal: a library consumer's `results.home_configs.append(h)` on `simulate_fleet`'s result raises `AttributeError` ('tuple' object has no attribute 'append'), and `results.home_configs = []` raises `FrozenInstanceError`; both succeed today. `simulate_community`'s billing fields are set on the one constructed result. `solar-challenge fleet run scenarios/bristol-community.yaml --start 2024-01-15 --end 2024-01-15` prints the same tables as before β. §9 rows 7-8.
- Prereqs: α (same `community.py` functions), S16 α.

**γ — The sharing mode is derived from the community battery** (held leaf; priority low; `metadata.x_seam_wait = {stream: "S29", contract: "surface bump window open"}`, excluded from this batch's `commit_planning`)
- Keys: fk-083990041fdc (weakened; §2.3's re-measure goes on the task).
- Work: §5.4. `CommunityConfig` loses `sharing_mode` and gains the property, and its three ifs go. `SharingMode` types `CommunityResults.sharing_mode` and `output.CommunityMetrics.sharing_mode`. The parser retires the key with a named refusal. `scenarios/bristol-community.yaml` is migrated. The 61 `sharing_mode=` sites are rewritten (the test sites drop the argument). `tests/unit/surface_forms_helper/test_surface_form.py`, if it builds `CommunityConfig`. The `FROZEN_SURFACE` form. `review/briefing.yaml`'s resolved-gap comment that cites `community.py` and `output.py` line numbers is restated by symbol.
- Files: `src/solar_challenge/community.py`, `src/solar_challenge/config.py`, `src/solar_challenge/output.py`, `scenarios/bristol-community.yaml`, `tests/unit/test_community.py`, `tests/integration/test_community_fleet.py`, `tests/unit/config/test_community_block.py`, `tests/unit/config/test_unrecognised_keys.py`, `tests/unit/surface_forms_helper/test_surface_form.py`, `tests/unit/test_public_api_surface.py` (or S23's successor), `review/briefing.yaml`.
- Signal: `solar-challenge fleet run` on the migrated `scenarios/bristol-community.yaml` (no `sharing_mode:`) prints the same community table as the pre-migration file did. The pre-migration file is refused, naming `community.sharing_mode` and the rule. §9 row 9.
- Prereqs: α, β; S29 releases it.

DAG: 786 → 787 → α → β ← S16 α; {α, β} → γ (held). Intra-batch edges: β→α, γ→β.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`): screened against dark-factory's trigger shapes. α removes two silent fail-softs (`no-silent-fail-soft`): an ignored strategy and grid-charge setting, and billing that vanishes without a word. The half-billing case is surfaced by a named warning, which is distinguishable from success. `_battery_strategy` is one home for the community's strategy arguments (`one-fact-one-home`, `no-lockstep-duplication`), and the factory is the one home of the refusals. β puts the pairing and timezone invariants at construction only. γ removes a second encoding (`one-fact-one-home`), and its hold has an owner and a window (`holds-owned-and-bounded`). No hit, no waiver.

## 11. Out of scope

- Grid charging a self-consumption community battery (D3 mid-term, L8's follow-up). When the factory's refusal arm goes, the community follows with no edit.
- Recording the community battery's grid charge as its own `CommunityResults` series, or rows for it in the CLI table and report.
- `validate config` checking a file's `community:` block. Its docstring scopes it to homes, and α's refusal is reached through `fleet run` and `load_community_config`.
- `MultiSweepResults`, `FleetSummary`, `ScenarioConfig` and the other classes on task 669's list.
- `output.py`'s "(PRD §6)" in the rendered flexibility-value report text: a board-report string, offered to S25 (§13).
- The community battery's starting SOC (midpoint, as each home's).

## 12. Open questions

### Lead-level (each has the default this PRD is written to)

1. **β in-leaf under D29.** Freezing three pinned classes and narrowing list fields to tuples is a form change that is neither additive nor a rename or retirement. **Default:** in-leaf with its `FROZEN_SURFACE` edit and an Unreleased line, following task 436's freeze of `SimulationResults`. A list still works at run time, and no measured consumer assigns these fields. The alternative is to hold β for S29.
2. **β's edge on S16 α.** **Default:** β depends on S16 α, so `fleet.py` has one editor at a time and β touches one assembly site. The lead adds the edge when S16 files; until then β is filed without it and the lead wires it. The alternative is an order-agnostic file overlap.

### Tactical (decide in the leaf)

1. The exact wording of the half-billing warning, within §5.2's required names.
2. Whether the frozen classes convert sequences in one shared helper or inline, one line each.
3. Whether §9 row 3 runs on the suite's seeded weather or on synthetic `FleetResults` built as `test_community.py` builds them. The assertion (SOC ≥ 0.85 of capacity, import above the self-consumption run) holds for both. Re-measure the 17.485 / 58.824 figures if S3 γ (bus-basis charge) has landed.

## 13. Proposed cross-reference lines (for the lead)

- S2: "S27 α (community battery through `build_dispatch_strategy`) depends on 786 and 787; S2 ε (790) also drops `community._battery_strategy`'s `or SelfConsumptionStrategyConfig()` when the battery default lands (file list gains `community.py`)."
- S16: "S27 β (frozen `FleetConfig`/`FleetResults` with tuple fields) depends on S16 α; S16 α–ε build `FleetResults` with tuples or lists (both accepted); S27 α moves `load_community_config` above the simulation in `cli/fleet.py::run` (file overlap with S16 α/β)."
- S3: "S27 α routes the community battery through `simulate_timestep(..., tariff=)`; S3 γ's re-derived `test_community.py` expectations include S27 α's new rows if α lands first."
- S11: "The flat-tariff grid-charging refusal and the tariff-clock arm reach the community battery through S27 α's `_battery_strategy`; no edge."
- S4: "S4 γ's L1 conversion of `CommunityConfig`'s sharing_mode refusals is deleted by S27 γ at the bump; order-agnostic."
- S25: "`output.py`'s flexibility-value block renders '(PRD §6)' into the board report, a planning-slice pointer like those task 743 removed; S25 owns the report text."
- S29: "Release section includes S27 §5.5 (α and β Unreleased lines, γ held: `CommunityConfig.sharing_mode` becomes a derived property and the `sharing_mode:` YAML key is retired)."
- Tasks: "706 is cancelled with `x_superseded_by` S27 α; 669 drops `FleetConfig`, `FleetResults` and `CommunityResults` from its list (S27 β); fk-dc5cf2ec9b84 is closed by done task 743 (§2.4), no S27 leaf carries it."
