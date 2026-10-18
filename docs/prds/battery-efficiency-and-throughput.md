# PRD — Battery facts: one representation each for efficiency and throughput (review-all stream S28)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S28** (wave 1, size S, risk medium). Findings record `plans/review-all-solar_challenge-20261013.json`, run `review-all-solar_challenge-20261013`.
- **Status:** authored 2026-10-15, not committed; awaiting the lead's reading of §12 (lead-level questions, each with the default this PRD is written to) before commit and decompose.
- **Binding rulings:** D4 (one coordinated surface bump; S28's clean option is "`BatteryConfig` keeps two efficiency fields plus a `with_round_trip` constructor"), D29 (additive frozen-table edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line; renames and retirements are held for S29; the retained `efficiency` field is such a retirement), D2 and L5 (this stream's refusals raise `errors.ConfigurationError`, a `ValueError` subclass, and depend on S1-β, task 774).
- **Approach:** **B + H, light.** Five modules change (`battery`, `config`, `scenario_writer`, `web/simulation_params`, `finance`) across the frozen public surface and two cross-stream seams (S2's SOH resolution, S19's stored-run format), but the mechanism count is small. §5 is the contract, §9 the two-way boundary tests.
- **Code anchors** verified against main `9625529565087fb3405efa390cc1c55049b26ce0` (2026-10-15). Between the findings' anchor commit `7dfea36e` and that SHA, `battery.py` changed only in docstrings and comments (the cycle-fade field's docstring gained a sentence; `Battery.__init__`'s SOH NOTE was removed), `web/simulation_params.py`, `tests/unit/test_public_api_surface.py` and `docs/domain-library-consumption.md` changed elsewhere, and `finance.py`, `config.py` and `scenario_writer.py` are unchanged. Every finding statement re-measured true (§2.1). Anchors are cited by symbol; re-locate lines at implementation time.

Finding keys (both `simulation-core`, both medium, confirmed, structural): fk-35b8ddcf5565 (`battery.py::BatteryConfig`, three fields for two efficiency facts), fk-50a3985fae0f (`battery.py::compute_soh`, the equivalent-full-cycle count is halved).

---

## 1. Goal

A battery's efficiency is two facts, charge and discharge, held in two fields; a round-trip efficiency is a way to construct them, not a third field that silently wins. A battery's cycle ageing counts each discharged kWh once: "throughput" means one thing in `compute_soh` and in the finance accrual that feeds it.

**What a user observes when this lands:**

1. `solar-challenge validate config <file>` on a scenario whose battery block sets `efficiency` together with `charge_efficiency` or `discharge_efficiency` exits 1 with an ERROR row naming the block (`home.battery`, or `community.community_battery`) and both keys. Today the file validates (probed: exit 0) and the run silently uses `sqrt(efficiency)` for both directions.
2. `scenarios/example-economy7.yaml` (`efficiency: 0.95`) and the web home form's Round-trip Efficiency slider still work and simulate the same battery as today (`charge_efficiency = discharge_efficiency = sqrt(round trip)`), built through `BatteryConfig.with_round_trip`.
3. In the library, `dataclasses.replace(BatteryConfig(capacity_kwh=5, efficiency=0.81), charge_efficiency=0.99)` raises `ConfigurationError` naming `efficiency` 0.81 and `charge_efficiency` 0.99, where today it returns a config whose `charge_efficiency` is still 0.9 (probed). The `optimize` and `finance` `replace()` sites that change other fields keep working.
4. `solar_challenge.compute_soh(12.0, 12_000.0, 4.0, BatteryConfig(capacity_kwh=5.0))` returns 0.61, where today it returns 0.685 (probed): one equivalent full cycle is one usable capacity of discharged energy. Every multi-year projection of a battery fleet (`solar-challenge finance run --project`, `--cost-recovery`) ages its batteries twice as fast by cycling as today, as the fade parameter's own documentation ("5e-5/EFC ≈ 30 % fade over ~6 000 EFC") says it should. On the board scenario the solved own-use rate moves from 7.74 to 7.79 p/kWh and the minimum DSCR from 1.95× to 1.90× (§2.1).
5. At the program's bump (S29), `BatteryConfig` has no `efficiency` field; `BatteryConfig(..., efficiency=x)` is a `TypeError`, its callers write `.with_round_trip(x)`, the scenario key `efficiency:` still reads as the round-trip form, and runs stored before the bump load after `solar-challenge web migrate`.

## 2. Background

### 2.1 What exists today (measured at `9625529`)

- **Efficiency.** `BatteryConfig` declares `charge_efficiency: float = 0.975`, `discharge_efficiency: float = 0.975` and `efficiency: Optional[float] = None`. When `efficiency` is set, `__post_init__` overwrites both per-direction fields with `math.sqrt(self.efficiency)` and keeps `efficiency` on the field. Nothing refuses a per-direction value that contradicts it; the class docstring spends 12 lines on the override and a "Caveat" that `dataclasses.replace(cfg, charge_efficiency=x)` does not take effect. `Battery`, `flow` and `dispatch` read only the per-direction pair (`Battery.__init__` copies `config.charge_efficiency`/`discharge_efficiency`; `flow` builds the grid-charge context's round trip as their product).
- **Who sets `efficiency`.** In `src`: `config._parse_battery_config` splats the YAML block into `BatteryConfig(**...)`, and `_BATTERY_BLOCK_KEYS` admits all three keys at once; `web/simulation_params._parse_battery` puts the home form's `efficiency_pct / 100` into `settings["efficiency"]`. `scenario_writer._battery_block` branches: it writes `efficiency` alone when set, else the pair. `optimize._apply_install`'s docstring says its `replace()` preserves `efficiency`. One scenario file (`scenarios/example-economy7.yaml`) uses `efficiency: 0.95`. The platform consumer (`solar-challenge-platform` at `314e8ea`) builds `BatteryConfig` from the per-direction pair only and never reads `efficiency` or calls `compute_soh`.
- **Throughput.** `compute_soh(system_age_years, cumulative_throughput_kwh, usable_capacity_kwh, params)` documents `cumulative_throughput_kwh` as "Total energy discharged over the battery's lifetime" and computes `efc = cumulative_throughput_kwh / (2 * usable_capacity_kwh)`, the formula for charge-plus-discharge throughput (`docs/prds/financial-layer-battery-fidelity.md` open question 3, "throughput / 2·usable", was never resolved). `finance._throughput_at` accrues each home's annualised `SummaryStatistics.total_battery_discharge_kwh` (discharge only) and `finance._aged_homes` passes it to `compute_soh` with `nominal_usable_capacity_kwh`, then injects the result with `dataclasses.replace(battery_config, soh=...)`. `docs/cost-recovery-finance-model.md` §4 says "the annualised discharge is the yearly throughput that battery cycle ageing integrates". So the discharge-only total is divided by twice the usable capacity and the effective cycle fade is half the configured one. `Battery.__init__` calls `compute_soh` with throughput 0.0 (calendar fade only), so single runs are unaffected; only multi-year projections move.

Probes run for this PRD (`uv run --locked --extra dev python -I`, main `9625529`):

| Probe | Today |
|---|---|
| `BatteryConfig(capacity_kwh=5, efficiency=0.81, charge_efficiency=0.99, discharge_efficiency=0.7)` | constructs, charge/discharge 0.9/0.9, no error |
| `dataclasses.replace(<that>, charge_efficiency=0.99)` | charge 0.9, no error |
| `BatteryConfig(capacity_kwh=5, efficiency=0.81)`: per-direction values; `replace(<it>, soh=0.7)` | 0.9 each, exactly `math.sqrt(0.81)`; replace keeps 0.9 |
| `validate config` on `example-economy7.yaml` with `charge_efficiency: 0.99` added beside `efficiency: 0.95` | `OK Configuration is valid`, exit 0 |
| `validate config` on the same file with `bogus: 1` in the battery block | exit 1, ERROR "Unrecognised keys in home.battery: …" (the reader's refusals surface as ERROR rows with the block path) |
| `compute_soh(12.0, 12000.0, 4.0, BatteryConfig(5.0))` | 0.685 (1 − 0.24 − 0.075); with `efc = throughput / usable`: 0.61 |
| Suite with `efc = throughput / usable` (non-slow unit + integration, `-k soh or finance or battery or ageing or projection or cost_recovery or calibration`, scratch tree) | 5 failures, all the fixture premise "the SOH floor clamps no year" (cycle fade 0.0002 on a 10 kWh battery discharging 800 kWh/yr now reaches the 0.6 floor at year 24): two in `tests/unit/test_finance_projection_ageing.py::TestBatterySohCountsThroughputToEachAge`, three parametrisations of `tests/unit/test_finance_projection_short_window.py::TestProjectMultiYearAnnualisesShortWindow::test_short_window_projects_the_equivalent_full_year_curve`. No test pins the halved value; the ageing tests use `compute_soh` itself as their oracle. 1,202 passed. |
| Board scenario, `finance run scenarios/bristol-phase1.yaml --assumptions physics --project --cost-recovery` (the CLI's default window, the repo's weather cache, `UV_OFFLINE=1`; 1 h 23 min and 1 h 48 min wall clock), before → after the formula change | solved own-use rate 7.74 → **7.79 p/kWh**; representative householder outlay £759.57 → £760.82 (saving vs baseline £399.28 → £398.03); mean fleet surplus £14,660 → £14,428/yr (£147 → £144 per home); min DSCR 1.95× → 1.90×; equity IRR 1.8 % → 1.7 %. The single-year householder bill section is unchanged. |

### 2.2 Already-filed tasks

No pending task covers either key (search over filed tasks, 2026-10-15). Done tasks this PRD builds on: 323 (`BatteryConfig.nominal_usable_capacity_kwh`, the one usable-capacity definition `compute_soh` is fed), 295 (each sampled age counts throughput from installation), 163 (the web form's round trip reaches `BatteryConfig`).

## 3. Rulings that bind, and how this PRD reads them

- **D4.** `BatteryConfig` keeps `charge_efficiency` and `discharge_efficiency` and gains `with_round_trip`. This PRD makes `with_round_trip` a method on a config, `BatteryConfig(capacity_kwh=5).with_round_trip(0.9)` (pathlib's `with_suffix` idiom: a new value derived from this one), not a classmethod: a classmethod constructor would have to take `**fields: Any`, which `mypy --strict` cannot check against the dataclass, or restate all sixteen fields. §12 Q1 asks the lead to confirm this reading.
- **D29.** `with_round_trip`, the two refusals and the `compute_soh` unit change are additive or behavioural and land in their leaves with their `FROZEN_*` entry and "Unreleased on main" line. Retiring the `efficiency` field is a retirement: the held leaf γ, released by S29.
- **L5.** α depends on S1-β (task 774) and every refusal it writes raises `solar_challenge.errors.ConfigurationError`.

## 4. Sketch of approach

1. **Round trip is a constructor; every reader uses it (α).** `battery.py` gains one private split rule and `BatteryConfig.with_round_trip`. The scenario reader reads `efficiency:` through it and refuses a block that also sets a per-direction key; the writer always writes the pair; the web home form builds its battery through it. Until γ retires the field, `__post_init__` refuses a set `efficiency` that a per-direction value contradicts, so the `replace()` caveat becomes an error instead of a silent no-op, and the caveat text goes.
2. **One equivalent full cycle is one usable capacity discharged (β).** `compute_soh` computes `efc = cumulative_throughput_kwh / usable_capacity_kwh`; its docstring is the one statement of what throughput is; finance's docstrings point at it; the finance model doc names the unit; the five tests whose fixture premise the faster fade breaks get a smaller cycle-fade rate, and a closed-form test (not `compute_soh` as its own oracle) pins the unit.
3. **Retire the field at the bump (γ, held for S29).** Delete `BatteryConfig.efficiency`, its docstring and its `__post_init__` arm; ship S19's stored-run step that drops the stored key.

## 5. Contract

### 5.1 `battery.py` (α)

```python
def _one_way_efficiency(round_trip_efficiency: float) -> float:
    """The charge (and discharge) efficiency of a battery whose round trip is round_trip_efficiency: its square root."""
    # refuses a value outside (0, 1] with ConfigurationError naming "round-trip efficiency" and the value

@dataclass(frozen=True)
class BatteryConfig:
    ...
    charge_efficiency: float = 0.975
    discharge_efficiency: float = 0.975
    efficiency: Optional[float] = None        # transitional: retired by γ at the bump
    ...
    def with_round_trip(self, round_trip_efficiency: float) -> "BatteryConfig":
        """This battery with charge and discharge efficiency each _one_way_efficiency(round_trip_efficiency)."""
        # dataclasses.replace(self, efficiency=None, charge_efficiency=s, discharge_efficiency=s); γ drops efficiency=None
```

- **The split rule has one home**, `_one_way_efficiency`. `with_round_trip` and, until γ, `__post_init__`'s `efficiency` arm both call it; the existing "Round-trip efficiency must be (0, 1]" refusal moves into it and raises `ConfigurationError` (a `ValueError` after 774, so the existing `pytest.raises(ValueError, match="efficiency")` cases still pass).
- **Transitional refusal (α; deleted by γ).** When `efficiency` is set, each of `charge_efficiency` and `discharge_efficiency` must equal `_one_way_efficiency(efficiency)` or its declared default (the dataclass cannot tell an explicit 0.975 from the default; `BatteryConfig(capacity_kwh=5, efficiency=0.81)` passes the defaults). Otherwise `__post_init__` raises `ConfigurationError` naming `efficiency` and its value and each contradicting field and its value, and saying to use `with_round_trip` or to pass the pair without `efficiency`. `dataclasses.replace(cfg, soh=…)` and `replace(cfg, capacity_kwh=…)` on an `efficiency`-set config re-pass the derived values (exactly equal floats) and construct; the documented escape `replace(cfg, efficiency=None, charge_efficiency=x, discharge_efficiency=y)` constructs. The one remaining silent case, a per-direction value explicitly equal to its default beside `efficiency`, closes at γ.
- `efficiency`'s docstring entry shrinks to the transitional rule and a pointer to `with_round_trip`; the 12-line override text and the `replace()` caveat go.

### 5.2 Scenario grammar and the web form (α)

- `_parse_battery_config` (home and community battery blocks alike) reads `efficiency` as the round-trip form. A block setting `efficiency` together with `charge_efficiency`, `discharge_efficiency` or both is refused with `ConfigurationError` naming the block path, `efficiency` and each per-direction key present. Otherwise the block, without `efficiency`, builds the `BatteryConfig`, and `.with_round_trip(efficiency)` applies when the block sets it. `efficiency: null` reads as absent. `_BATTERY_BLOCK_KEYS` keeps `efficiency`.
- `scenario_writer._battery_block` always writes `charge_efficiency` and `discharge_efficiency` and never `efficiency`; its branch and docstring sentence go. A config read from a scenario never carries `efficiency` after α, so parse → write → parse is the identity on every config the reader builds; a Python-built config with `efficiency` set writes its derived pair, which reads back as `cfg.with_round_trip(cfg.efficiency)`.
- `web/simulation_params._parse_battery` builds the battery from its other settings and applies `.with_round_trip(efficiency)` when the form sends `efficiency_pct`; `settings["efficiency"]` goes. The form, its range refusal and its units are unchanged.

### 5.3 Throughput (β)

- `compute_soh`'s docstring is the one statement of the unit: `cumulative_throughput_kwh` is the energy the battery has discharged since installation, as `SummaryStatistics.total_battery_discharge_kwh` counts it (`Battery.discharge`'s output); one equivalent full cycle is `usable_capacity_kwh` of it, the battery's nominal (not SOH-derated) usable capacity; `efc = cumulative_throughput_kwh / usable_capacity_kwh` (0 when `usable_capacity_kwh` is 0). The signature, parameter names and clamp are unchanged.
- `finance._throughput_at`, `finance._aged_homes` and the `per_home_throughput` attribute docstring say that they accrue or pass the discharged energy `compute_soh` counts, pointing at it rather than restating the cycle rule. `docs/cost-recovery-finance-model.md` §4 *Battery ageing* names the unit once for a reader reproducing the projection by hand (`cycle fade = cycle_fade_per_equivalent_full_cycle × T_h(t) / U_h`).
- **No second SOH resolver.** S2's task 789 makes `BatteryConfig.resolved_soh` (the `soh` override, else `compute_soh(system_age_years, 0.0, nominal_usable_capacity_kwh, self)`) the one resolution `Battery` reads. β changes only what a non-zero throughput means, so `resolved_soh` and every single-run SOH are unchanged. `finance._aged_homes` keeps computing the aged SOH with `compute_soh` and injecting it through the `soh` override, the path 789 honours.

### 5.4 Retirement (γ, held)

- `BatteryConfig.efficiency`, its docstring entry, `__post_init__`'s `efficiency` arm and the transitional refusal are deleted; `with_round_trip` drops its `efficiency=None`; `_one_way_efficiency` stays as `with_round_trip`'s split rule. The YAML key `efficiency:` stays the round-trip form (§5.2).
- Stored runs: one `RunDocumentStep` under S19's contract C10 drops the `efficiency` key from every stored `BatteryConfig` (home `battery_config` and community battery, run files and database copies). Every run the library saved holds the derived pair beside it (`asdict` after `__post_init__`), so dropping it changes no battery.

### 5.5 Surface ledger for S29 (D4)

Each line is a frozen-surface change S28 makes, the release-note text S29's one section carries, and what a consumer does at re-pin. "Platform" is `solar-challenge-platform` at `314e8ea`.

| Leaf | Change | Consumer action |
|---|---|---|
| α | `BatteryConfig.with_round_trip(round_trip_efficiency)` returns the config with charge and discharge efficiency each the square root | none |
| α | `BatteryConfig` refuses `efficiency` set beside a per-direction value that is neither its square root nor its default, raising `ConfigurationError` naming both; `dataclasses.replace` of a per-direction efficiency on a config with `efficiency` set raises instead of silently keeping the square root | Platform: none (never sets `efficiency`) |
| α | A scenario battery block setting `efficiency` with `charge_efficiency` or `discharge_efficiency` is refused naming the block and both keys; a battery read from a scenario or the web home form carries the per-direction pair and `efficiency` None; the scenario writer writes the pair | Scenario files: keep one form per battery |
| β | `compute_soh` counts one equivalent full cycle per usable capacity of discharged energy, where it counted one per two; cycle fade doubles, so multi-year battery SOH, later-year own-use and the cost-recovery solve move for battery fleets | Platform: none (does not call it); board figures re-run |
| γ (held) | `BatteryConfig.efficiency` retired: write `.with_round_trip(x)` | Platform: none; library callers passing `efficiency=` switch; stored runs migrate with `web migrate` |

## 6. Resolved design decisions

1. **`with_round_trip` derives from a config (§3).** Typed, composes with `default_5kwh()` and any `replace`, restates no field list.
2. **One split rule, `_one_way_efficiency`.** The square-root rule lives in one function that the method and the transitional field arm share; at γ only the method calls it.
3. **The transitional refusal is in α, not left to γ.** The finding's next change (an agent sweeping a per-direction efficiency with `replace`) silently produces flat results until S29 otherwise; S2 decision 8 set the precedent of a few transitional lines that the held leaf deletes. The default-value carve-out is the price of not changing the fields' types on the frozen surface; it leaves only an explicit default beside `efficiency` silent, for one window.
4. **The YAML keeps the round-trip form, as input only.** `efficiency: 0.95` is what scenario authors and the web slider mean; the reader turns it into the pair and refuses it beside the pair. The writer writes the pair, so the stored and written form of a battery is its two facts.
5. **Throughput is discharged energy, one cycle per usable capacity** (option A of the finding's proposal), not charge plus discharge with finance passing both (option B). A is what `compute_soh`'s docstring, finance's accrual and the finance model doc already say, needs no second accrued series, and is how cycle-life warranties count energy throughput. B would differ from A by about 1.3 % of cycle fade (stored charge ≈ discharge / 0.975), not enough to buy a second series.
6. **The denominator stays nominal usable capacity.** An equivalent full cycle is measured against the rated window, and `nominal_usable_capacity_kwh` (task 323) is already the one definition `compute_soh` is fed; derating it would make the fade compound and is a modelling change no finding asks for.
7. **No parameter rename.** Renaming `cumulative_throughput_kwh` to `cumulative_discharge_kwh` would be a held retirement and delay a board-figure defect to wave 4; "throughput" is defined once in the docstring instead.
8. **No `DeprecationWarning` on `efficiency` in the window.** The refusal covers the silent case, the Unreleased line and S29's release section tell consumers, and no other stream warns for its held retirements.
9. **The SOH-envelope seam stays S2's.** β does not add an SOH resolver or touch `resolved_soh`; 789 does not restate the throughput unit (§8).

## 7. Pre-conditions

- **S1-β (task 774, `ConfigurationError(ValueError)`)** is landed before α (L5): α's refusals raise it and the web form's `except ValueError` callers must still catch them. Wired as α's out-of-batch dependency.
- β has no prerequisite: it adds no refusal and changes no signature.
- For γ only: α; S19's κ (the stored-run format version and `RunDocumentStep` mechanism, not yet filed; S19's PRD §8 already lists "S28's held S29 leaf → κ"); S29's bump window.

G3 substrate: every symbol §5 names as existing was read at `9625529` (capability manifest). `errors.ConfigurationError` (774) and S19's `RunDocumentStep` (κ) are queued prerequisites, not assumptions.

## 8. Cross-PRD relationship

| Other stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 errors leaf | consumes | `errors.ConfigurationError` (a `ValueError` after 774) raised by `_one_way_efficiency`, the transitional refusal and the both-forms refusal | S1 | α depends on 774 (L5) |
| S2 dispatch configuration | shares `compute_soh` | 789 (δ) owns SOH resolution (`BatteryConfig.resolved_soh`, zero throughput) and the derated envelope; S28 β owns what a non-zero throughput means in `compute_soh`. Neither restates the other's rule | S2 resolution / S28 unit | no edge: β moves no zero-throughput SOH; textual overlap in `battery.py` with 786, 788, 789; whichever lands second rebases |
| S2 dispatch configuration | shares files | 786 edits `_parse_battery_config` (strategy sub-block), `scenario_writer._battery_block`'s strategy entry and `web/simulation_params._parse_battery`'s strategy read; α edits the efficiency handling in the same three functions | each its own lines | no edge; textual merge |
| S19 run store | consumes | γ's `RunDocumentStep` dropping stored `efficiency` (C10) | S19 mechanism / S28 step | γ depends on κ (lead adds the edge when S19 files) |
| S7 component defaults | shares | the battery block key table: `efficiency` is the grammar's round-trip form, read through `with_round_trip`, never written; after γ it is not a `BatteryConfig` field, so a table derived from the fields carries it as a reader-only key and keeps the both-forms refusal | S7 table / S28 key semantics | concurrent (both wave 1), file overlap in `config.py`, `scenario_writer.py` |
| S5 config partition | produces for | `_parse_battery_config` moves into `scenario_blocks.py` with α's refusal intact | S5 | S5 after S1, S2 (wave 2); textual |
| S4 finite quantities | touches | `BatteryConfig.__post_init__`'s range checks; `_one_way_efficiency` already raises `ConfigurationError`; invariant 1's fixture walks `dataclasses.fields`, so it drops `efficiency` by itself at γ | S4 | file overlap only |
| S8 finance partition | touches | β edits docstrings of `_throughput_at`, `_aged_homes` and `per_home_throughput`, which S8 moves to the projection module | S8 move | whichever lands second carries the text |
| S17 web request boundary | touches | `web/simulation_params._parse_battery` reads `efficiency_pct` through `with_round_trip` (α); S17's presence-rule rewrite keeps that call | S17 | file overlap only |
| S23 surface lock | touches | α adds `with_round_trip` to the `BatteryConfig` member table; γ removes `efficiency` from the `BatteryConfig` signature | S23 owns the tables | file overlap in the surface test module |
| S29 surface bump | produces for | §5.5 ledger; γ held for the bump window | S29 | γ held |

The program's seam table lists "BatteryConfig fields on the frozen surface (version-bump route)" under S28 and "BatteryConfig fields" with `HomeConfig.dispatch_strategy` under S2. This PRD reads them as split by field: S28 owns the efficiency fields and `compute_soh`'s unit; S2 owns `dispatch_strategy` and `grid_charging`; S29 does the one bump.

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Faces |
|---|---|---|---|---|
| 1 | Round-trip form reads as the pair | home block `efficiency: 0.95`; community battery block likewise | charge = discharge = `math.sqrt(0.95)` (the floats today's `BatteryConfig(efficiency=0.95)` derives), `efficiency is None`; equals `BatteryConfig(<same fields>).with_round_trip(0.95)` | grammar → battery |
| 2 | Both forms refused | blocks with `efficiency` + `charge_efficiency`, `efficiency` + `discharge_efficiency`, `efficiency` + both, under `home.battery` and the community battery | `ConfigurationError` naming the block path, `efficiency` and each per-direction key present; `validate config` exit 1 with that ERROR row | grammar, CLI |
| 3 | Writer writes the pair | configs from rows 1 and from a pair block; a Python-built `BatteryConfig(5, efficiency=0.81)` | written blocks hold `charge_efficiency`, `discharge_efficiency`, no `efficiency`; parse(write(c)) == c for reader-built configs; the Python-built one reads back as `c.with_round_trip(0.81)` | writer ↔ reader |
| 4 | Web form | home body with `battery_kwh: 5`, `efficiency_pct: 90` | the stored run's battery has charge = discharge = `math.sqrt(0.9)`, `efficiency is None` | web → battery |
| 5 | Pre-α stored run loads | a run saved before α with `"efficiency": 0.81`, pair 0.9 | loads; per-direction 0.9 (the transitional check accepts the derived pair) | storage → battery |
| 6 | `replace()` on an `efficiency`-set config | `cfg = BatteryConfig(5, efficiency=0.81)` | `replace(cfg, charge_efficiency=0.99)` raises naming `efficiency` 0.81 and `charge_efficiency` 0.99; `replace(cfg, soh=0.7)` (finance's aged homes) and `replace(cfg, capacity_kwh=10)` (optimize's install sweep) construct with 0.9/0.9; `BatteryConfig(5, efficiency=0.81, charge_efficiency=0.99, discharge_efficiency=0.7)` raises naming both contradicting fields | battery ↔ finance, optimize |
| 7 | Split rule's range | `with_round_trip(0.0)`, `(1.5)`, `(-0.5)`; `with_round_trip(1.0)` | the three raise `ConfigurationError` naming round-trip efficiency and the value; 1.0 gives 1.0/1.0 | battery |
| 8 | The cycle unit, closed form | `compute_soh(12.0, 12000.0, 4.0, BatteryConfig(5.0))`; `project_multi_year` on one 10 kWh battery (usable 8 kWh), calendar 0.005/yr, cycle 1e-4/EFC, floor 0.6, an injected simulate discharging 800 kWh/yr, 25-year life | 0.61 within 1e-12; every year's `battery_soh` equals `1 − 0.015·y` within 1e-9 (today `1 − 0.01·y`), the floor clamping no year | battery ↔ finance |
| 9 | Single runs unchanged | `Battery(BatteryConfig(5, system_age_years=10)).soh` (after 789: `BatteryConfig(...).resolved_soh`) | 0.8 before and after β | battery (S2 seam) |
| 10 | Retirement (γ) | `BatteryConfig(capacity_kwh=5, efficiency=0.9)`; `example-economy7.yaml`; a committed pre-γ stored run with `"efficiency": 0.81` | `TypeError` naming `efficiency`; the scenario validates and its battery is unchanged; the run loads after `web migrate` with charge = discharge = 0.9 and its documents carry no `efficiency` | battery, grammar, storage |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`; priority is the finding severity (medium). α and β edit the surface tables (if they change a frozen form) and add their "Unreleased on main" line to `docs/domain-library-consumption.md` in their own commits (D29); S29 folds the lines into its release section from §5.5.

**α — Round-trip efficiency is a constructor, and every reader builds through it** (leaf; priority medium)
- Keys: fk-35b8ddcf5565.
- Work: §5.1 and §5.2. `_one_way_efficiency`; `BatteryConfig.with_round_trip`; the transitional refusal; `efficiency`'s docstring shrunk (the override text and `replace()` caveat deleted); `_parse_battery_config`'s both-forms refusal and `with_round_trip` read; `scenario_writer._battery_block` writes the pair (branch deleted); `web/simulation_params._parse_battery` builds through `with_round_trip`. Add `"with_round_trip": "(self, round_trip_efficiency: float) -> BatteryConfig"` to the `BatteryConfig` member table and the Unreleased line (§5.5 rows α). Tests: §9 rows 1-7. Existing tests that change: `tests/unit/test_battery.py::TestBatteryConfigRoundTripEfficiency::test_efficiency_overrides_explicit_charge_discharge` asserts the refusal instead of the override; `tests/unit/config/test_unrecognised_keys.py::...::test_block_setting_every_recognised_key_is_accepted` sets both forms, so it splits into one block per efficiency form; `tests/unit/config/test_home_block.py` (asserts `battery_config.efficiency == 0.95`) and `tests/unit/web_api/test_simulate_home_and_fleet.py` (asserts `battery_config.efficiency == approx(0.9)`) assert the derived pair and `efficiency is None`; `tests/unit/test_scenario_writer.py`'s every-field home (`efficiency=0.9`, asserting `loaded == home`) builds its battery with `.with_round_trip(0.9)` so the identity still holds, and §9 row 3's Python-built case is added beside it.
- Files: `src/solar_challenge/{battery,config,scenario_writer}.py`, `src/solar_challenge/web/simulation_params.py`, `tests/unit/test_battery.py`, `tests/unit/config/{test_home_block,test_unrecognised_keys,test_community_block}.py`, `tests/unit/test_scenario_writer.py`, `tests/unit/test_web_simulation_params.py`, `tests/unit/web_api/test_simulate_home_and_fleet.py`, `tests/unit/test_public_api_surface.py`, `docs/domain-library-consumption.md`.
- Signal: `solar-challenge validate config` on a copy of `scenarios/example-economy7.yaml` with `charge_efficiency: 0.99` added beside `efficiency: 0.95` exits 1, its ERROR row naming `home.battery`, `efficiency` and `charge_efficiency` (today: OK, exit 0); the unmodified file validates and its parsed battery has charge = discharge = `math.sqrt(0.95)`; `dataclasses.replace(BatteryConfig(capacity_kwh=5, efficiency=0.81), charge_efficiency=0.99)` raises `ConfigurationError` naming both values (today it returns 0.9); §9 rows 1-7.
- Prereqs: task 774 (S1-β).

**β — `compute_soh` counts one equivalent full cycle per usable capacity discharged** (leaf; priority medium)
- Keys: fk-50a3985fae0f.
- Work: §5.3. The formula and the docstring's one statement of the unit; finance's three docstrings point at it; `docs/cost-recovery-finance-model.md` §4 names the unit and its header gains an "Unreleased on main" line (the task-295 line's form: what moved, what the 0.5.0 tag does); the consumption guide's Unreleased line (§5.5 row β). The five tests whose premise "the SOH floor clamps no year" the faster fade breaks (§2.1) take cycle fade 1e-4 instead of 2e-4, keeping their assertions; a new closed-form test (§9 rows 8-9) pins the unit without using `compute_soh` as its own oracle. No surface-table edit (the signature is unchanged).
- Files: `src/solar_challenge/battery.py`, `src/solar_challenge/finance.py`, `tests/unit/test_battery.py`, `tests/unit/test_finance_projection_ageing.py`, `tests/unit/test_finance_projection_short_window.py`, `docs/cost-recovery-finance-model.md`, `docs/domain-library-consumption.md`.
- Signal: `solar_challenge.compute_soh(12.0, 12_000.0, 4.0, BatteryConfig(capacity_kwh=5.0))` returns 0.61 (today 0.685); `project_multi_year` on §9 row 8's battery reports `battery_soh = 1 − 0.015·y` every year (today `1 − 0.01·y`); `Battery(BatteryConfig(5, system_age_years=10)).soh` stays 0.8.
- Prereqs: none.

**γ — Retire `BatteryConfig.efficiency` at the bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "surface bump window open"}`, excluded from this batch's `commit_planning`)
- Keys: fk-35b8ddcf5565.
- Work: §5.4. Delete the field, its docstring entry, the `__post_init__` arm and the transitional refusal and its tests; `with_round_trip` drops `efficiency=None`; the `BatteryConfig` signature in the frozen tables loses `efficiency: float | None = None`; every `BatteryConfig(..., efficiency=x)` in `tests/` becomes `.with_round_trip(x)`; `optimize._apply_install`'s docstring stops naming `efficiency` among the fields its `replace()` preserves; the `RunDocumentStep` and its test (§9 row 10) with a committed pre-γ stored run.
- Files: `src/solar_challenge/battery.py`, `src/solar_challenge/optimize.py` (docstring), S19's stored-run step module (`web/stored_runs.py` per S19 §3.1), `tests/unit/test_battery.py` and the other test files that pass `efficiency=`, `tests/unit/test_public_api_surface.py`, a stored-run fixture under `tests/fixtures/stored_runs/`.
- Signal: §9 row 10 (`BatteryConfig(capacity_kwh=5, efficiency=0.9)` is a `TypeError`; `validate config scenarios/example-economy7.yaml` still exits 0; a pre-γ stored run loads after `solar-challenge web migrate` with its pair intact).
- Prereqs: α; S19 κ; S29 releases it.

DAG: 774 → α → γ (held); β independent; {α, S19 κ, S29 window} → γ. Intra-batch edge: γ→α.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`): screened against dark-factory's trigger shapes. α removes a silent override (`no-silent-fail-soft`) and gives the square-root rule one home (`one-fact-one-home`); β states the throughput unit once and has finance point at it (`one-fact-one-home`), and its new test asserts a closed form instead of the function under test (`guards-exercise-behaviour`); α's transitional refusal is a placeholder owned by γ with a named bound (S29), not an unowned one. No hit.

## 11. Out of scope

- A `round_trip_efficiency` read accessor on `BatteryConfig` or `Battery`; `flow` keeps forming the product for the grid-charge context (S2 γ reshapes that context).
- Renaming the YAML `efficiency` key, or the `cumulative_throughput_kwh` parameter (§6.7).
- Ageing against SOH-derated capacity, or a datasheet throughput curve in place of the linear EFC rule (`financial-layer-battery-fidelity.md` open question 3's other branch).
- SOH resolution and the derated envelope (S2, task 789).
- Finite and bool checks of the efficiency fields beyond today's range (S4).
- Block paths on `BatteryConfig.__post_init__`'s refusals (S5).

## 12. Open questions

### Lead-level (each has a default the PRD is written to)

1. **D4's "with_round_trip constructor".** **Default:** a method on a config (`BatteryConfig(capacity_kwh=5).with_round_trip(0.9)`), §3. If the lead wants the classmethod, it is `with_round_trip(cls, round_trip_efficiency, /, **fields: Any)`; nothing else in α changes.
2. **Transitional refusal in α.** **Default:** in (§6.3). Dropping it leaves the `replace()` no-op live until S29, and the caveat text then stays in α and goes at γ.
3. **Throughput unit.** **Default:** discharged energy, one cycle per usable capacity (§6.5). The alternative (charge plus discharge over twice usable) needs finance to accrue a second series for a ~1.3 % difference.
4. **γ → S19 κ edge.** S19 is not filed; S19's PRD §8 asks for this edge. **Default:** the lead adds it when S19 decomposes, as L14 did for S10's leaf 784.

### Tactical (decide in the leaf)

1. Exact refusal wording, within §5's required names.
2. Whether the transitional check compares with `==` or `math.isclose` (the `replace()` path re-passes exactly equal floats; a hand-written consistent pair may differ in the last bit).
3. Whether γ's step reports dropped `efficiency` keys (S19's v2 step reports dropped non-null keys; here nothing is lost).

## 13. Proposed cross-reference lines (for the lead to apply to other PRDs)

- S19: "S28 γ (held) retires `BatteryConfig.efficiency` and ships its `RunDocumentStep` under C10, dropping the stored key (the stored pair already holds the derived values); γ depends on κ."
- S7: "The battery block's `efficiency` key is the grammar's round-trip form, read through `BatteryConfig.with_round_trip` and never written (S28 α); after S28 γ it is not a `BatteryConfig` field, so the shared battery key table carries it as a reader-only key, and the reader keeps refusing it beside `charge_efficiency`/`discharge_efficiency`."
- S5: "`_parse_battery_config` moves into `scenario_blocks.py` with S28 α's both-forms refusal intact."
- S2: "789 (δ) owns SOH resolution (`resolved_soh`, zero throughput); S28 β owns what a non-zero throughput means in `compute_soh`; neither restates the other's rule. No edge; `battery.py` textual overlap."
- S8: "β (S28) edits the docstrings of `_throughput_at`, `_aged_homes` and `per_home_throughput`; the `project_multi_year` move carries them, whichever lands second."
- S17: "`web/simulation_params._parse_battery` reads `efficiency_pct` through `BatteryConfig.with_round_trip` (S28 α); the presence-rule rewrite keeps that call."
- S23: "`BatteryConfig`'s member table gains `with_round_trip` (S28 α, in-leaf per D29); its signature loses `efficiency` at S28 γ (held)."
- S29: "Release section and consumer recipe include S28 §5.5; S28 γ is a held leaf released in the bump window, after S19 κ."
