# PRD — One scenario reader: the blocks that reach the homes, read once, under one policy

- **Program:** review-all-solar_challenge-20261013, stream **S6** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 3, upstream S5 (γ and ε), size L, risk medium.
- **Finding keys (12):** fk-3be3240278ee (high), fk-2264bc150fa3 (high), fk-416eb5643e7a (high), fk-81d0840d19e2 (high), fk-f99038047a27 (medium), fk-a391cf1f4edf (medium), fk-be5b13274bcb (medium; weakened; assigned by D26), fk-8047de9b6789 (medium; weakened), fk-e756dab8077e (medium; mechanical, filed as task 681), fk-ad65ad5e4e48 (low; weakened), fk-188af6c13d71 (low; weakened; mechanical, filed as task 485), fk-0b791f2be2d6 (low; mechanical, filed as task 485). §2.4 re-measures the four weakened keys (D28).
- **Binding rulings:**
  - D10: SEG fill-and-refuse; the CLI's and optimize's overwrite paths become refusals.
  - D11: period flag > file period block > default, for every command.
  - D4 and D29: one surface bump; additive frozen edits land in-leaf with an "Unreleased on main" line; renames and retirements are held for S29.
  - D25: S26's knob registry maps a knob to a `ScenarioConfig → ScenarioConfig` transform built on this stream's homes accessor.
  - D26 (fk-be5b13274bcb is S6's) and D28 (re-measure the weakened keys).
  - L30: freezing a pinned config with tuple fields is neither a rename nor a retirement.
  - L37 and the S5 cross-reference line: S6 depends on S5 γ and ε, owns the top-level keys of the home file and of single-scenario documents, and decides `ScenarioConfig.tariff_config`.
- **Status:** authored 2026-10-17 by an author-only /prd session; committed by the lead at `aa8dece`; decomposed 2026-10-18 (ids in the sidecar). Lead rulings L41 (defaults of lead questions 1-4 accepted) and D50 (question 5: retire the flat form) apply. L42 moves `DEFAULT_FIRST_DAY`/`DEFAULT_LAST_DAY` from `config.py` to `timebase.py`; decision 7, §4.2, §4.4 and β below say so.
- **Approach:** B + H. The work touches config, finance, optimize, five CLI modules and three web modules. Its seams are consumed by S8, S18, S25 and S26, and every scenario command crosses them. So §4 is a contract and §5 a two-way boundary-test sketch whose integration gate is θ.
- **Code anchors** verified against main `dfcbde8` (2026-10-17). Main moves fast: anchors cite symbols; re-locate lines at implementation time. Since the findings' pin `7dfea36`, the files this PRD edits changed only in ways that leave every finding present (§2.3 probes ran at `dfcbde8`).

## 1. Goal

A scenario file means the same thing to every command that reads it. One reader in `config.py` reads every single-scenario document into a `ScenarioConfig`: a home file, a `homes:` fleet, a `fleet_distribution:` fleet, a `scenario:` wrapper, or each entry of a `scenarios:` list. It reads the scenario-level blocks that reach the homes (location, tariff, seg), the ones the commands read beside them (period, finance, flex_band, name, description), and refuses any other key. `ScenarioConfig` becomes a frozen value that answers the three questions every consumer re-derives today: which homes it simulates (with the scenario's SEG applied under D10), how a transform reaches every home, and which window it simulates (as S10's `SimulationWindow`, under D11).

What a user observes:

1. **`fleet run` books export revenue.** On a fleet file with `seg: {rate_pence_per_kwh: 15.0}`, the results table's Grid Export Revenue equals Grid Export × £0.15. Today it is £0.00: `load_fleet_config` gives every home `seg_tariff=None` (probed). The same holds for the five shipped fleet files that carry `seg:`.
2. **One period for one file.** On a file whose `period:` runs 2024-06-01 to 08-31, `finance run`, `optimize configs`, `fleet run` and `home run` all simulate those 92 days. `--start` or `--end` replaces only its own day, and a file without a period simulates calendar 2024. Today `finance run` simulates the whole of 2024 for that file while `optimize configs` honours it (probed), and `home run scenarios/bristol-arbitrage.yaml` simulates a year instead of the file's one day.
3. **A misread file is refused, by name, by every command.** A typo in a top-level key (`finanse:`), a misspelt period key (`period: {start: …}`), `period: "2024"`, `flex_band: 1`, `home: null`, or a fleet file passed to `home run` exits 1 with a message naming the key. Today, depending on the command, these run on defaults silently, print "Configuration is valid", or end in a traceback (all probed, §2.3).
4. **What is written is what is read.** A fleet written by `scenario_writer.fleet_scenario` or exported by the dashboard reads back through `load_fleet_config` as the same homes, SEG included. A top-level `tariff:` reaches the homes of a `homes:` fleet as it already reaches a `fleet_distribution:` fleet's. A home's own differing SEG rate or tariff is refused by name, never silently overwritten (D10).
5. **The overrides change what they say.** `home run scenarios/bristol-arbitrage.yaml --battery-kwh 10` simulates a 10 kWh battery that still grid-charges to 0.9. Today the override drops `grid_charging` and every other battery setting (probed).
6. **Library consumers stop re-deriving.** `scenario.simulated_homes()`, `scenario.map_homes(f)`, `scenario.window()` and `scenario.simulation_bounds()` replace finance's `_resolve_homes` and `_reconcile_seg_homes`, `cli/validate._scenario_homes`, optimize's private import and raw `.homes` reads, the three "zone from location, else the first home" copies, and both CLI's hand-built `ScenarioConfig`s.

## 2. Background (measured at `dfcbde8`)

### 2.1 Who decides what a file's top-level blocks mean

| Reader | Blocks it reads | What it drops or decides alone |
|---|---|---|
| `config._parse_scenario` (via `load_scenarios`) | name, description, location, period, home/homes, output, seg (onto `ScenarioConfig.seg_tariff_pence_per_kwh`), tariff_config, finance | refuses a `fleet_distribution:` document ("must define either 'home' or 'homes'", probe P9) |
| `config.load_home_config` | location, home (or a flat home) | ignores seg, period, name; accepts a malformed seg block (P6b) |
| `config.parse_fleet_config` | `fleet_distribution:` branch: location, tariff; `homes:` branch: location | seg on both branches (P1); tariff on the `homes:` branch (P2, task 542) |
| `cli/utils.load_config_with_overrides` + `cli/home.home_config_for_run` | location, home, seg | flat files run as the default home (P4); `hom:` and a fleet file run the default home (Q4, Q5); `home: null` is a `TypeError` (Q6); period ignored |
| `cli/finance.run` | finance, flex_band (raw, non-strings dropped), seg (threaded by hand), name | period ignored (probe: 2024-01-01..12-31 for a June–August file) |
| `cli/optimize.configs` | finance, seg (threaded by hand), period (raw dict), name | misspelt period keys silently fall back to the whole year (probed) |
| `cli/fleet.run` | (through `load_fleet_config`) | seg, period |
| `cli/validate._homes_defined_by` | picks a loader by key presence | accepts a fleet file with `finanse:` ("valid", Q1) |
| `web/fleet_scenario._refuse_what_the_loaders_refuse`, `parse_fleet_form` | restates the loader's order and adds seg; builds homes through `apply_fleet_overlay` | the export reads back without SEG (fk-a391cf1f4edf) |
| `web/builder_form._scenario_reader_errors` | writes a temp file for `load_fleet_config`, then reads seg and period itself | — |

### 2.2 How a scenario's homes and SEG reach a consumer

- **Homes are resolved in 3 live modules.**
  - `finance._resolve_homes` has 3 callers in finance, and `optimize._age0_baseline_outlay` imports it by its private name.
  - `cli/validate._scenario_homes` resolves them with the opposite precedence.
  - optimize reads raw `.homes` in `iter_configs`, `_repriced_at_seg_rate` and `apply_knob`'s degradation knob.
  - `config.run_parameter_sweep` is dead and S5 α deletes it.
- **A scenario SEG is written onto homes at 6 sites, under 2 policies.**
  - Fill-and-refuse: `finance._reconcile_seg_homes`.
  - Overwrite: `cli/home.home_config_for_run`, `cli/finance.run`, `cli/optimize.configs`, `optimize._repriced_at_seg_rate`, and `web/fleet_scenario._with_fleet_overlay` through `apply_fleet_overlay`.
- **The window is derived 3 times** as "the scenario location's zone, else the first home's; then `period.get_start_timestamp(tz)`": twice in finance (`project_multi_year` and `solve_cost_recovery_rate`) and once in `optimize._age0_baseline_outlay`.
- **`ScenarioConfig` is a plain mutable dataclass.**
  - Mutation bypasses its home-or-homes check (P11).
  - It accepts a home whose SEG contradicts the scenario's (Q2). Only `project_multi_year` and the solve refuse that later; `optimize`'s age-0 outlay does not.
  - It accepts a `tariff_config` that nothing reads (Q3).

### 2.3 Probes (offline, `uv run --locked --extra dev`, at `dfcbde8`)

| # | Input | Today |
|---|---|---|
| P1 | `load_fleet_config` on `homes:` + `seg: 15`, and on `fleet_distribution:` + `seg: 15` | every `seg_tariff` is `None` |
| P2 | `load_fleet_config` on `homes:` + top-level `tariff: {type: economy_7}` | `tariff_config` is `None` |
| P3 | `parse_fleet_config(scenario_writer.fleet_scenario([h, h]))`, h with SEG 15 | `seg_tariff` `[None, None]`; homes unequal |
| P4 | flat home file `pv: {capacity_kw: 9}` | `load_home_config` 9.0 kW; `home_config_for_run` 4.0 kW |
| P5 | `home_config_for_run(bristol-arbitrage.yaml, battery_kwh=10)` | `grid_charging` `None` (the file gives 0.9) |
| P6 | `home:` file with `seg: 15`; the same with `seg: {rate: 5}` | `load_home_config` ignores both; `home run` reads the first and refuses the second |
| P7 | a dataclass with a field `homes` and a method `homes()` | the method becomes the field's default; `C(homes=[1]).homes` is the list: **`ScenarioConfig.homes()` cannot exist beside the `homes` field** |
| P8 | `load_scenarios(bristol-arbitrage.yaml)` | period 2024-01-15..01-15; the home's `seg_tariff` `None`, the scenario's 15.0 |
| P9 | `load_scenarios` on a `fleet_distribution:` scenario | `ConfigurationError … must define either 'home' or 'homes'` |
| P10 | `SimulationPeriod("2024", "2024").get_start_timestamp()` | 2024-01-01: a non-date accepted |
| P11 | `scenario.homes = []` on a constructed `ScenarioConfig` | accepted |
| Q1 | `validate config` on `homes:` + `finanse:` | exit 0 |
| Q2 | `ScenarioConfig(homes=[h with SEG 3.0], seg_tariff_pence_per_kwh=5.0)` | constructed |
| Q3 | `ScenarioConfig(…, tariff_config=TariffConfig.economy_7())` | constructed; no reader |
| Q4–Q6 | `home_config_for_run` on a 2-home `homes:` file, on `hom:`, on `home: null` | the default 4 kW home, twice; `TypeError` |
| Q7 | `fleet_form_from_scenario` on a fleet scenario with `finanse:` | accepted, `finanse` listed in `not_loaded` |
| C1 | `finance run` / `optimize configs` (recording simulator) on `period: 2024-06-01..08-31` | 2024-01-01..12-31 / 2024-06-01..08-31 |
| C2 | `optimize configs` on `period: {start: …, end: …}` | simulates 2024-01-01..12-31 |
| C3 | `finance run` on `flex_band: 1` | reaches the simulator |

### 2.4 Weakened findings re-measured (D28)

| Key | Skeptic's correction | At `dfcbde8` |
|---|---|---|
| fk-8047de9b6789 | 2 live home-resolvers, not 4; 4 SEG-overwrite sites, not 3 | 3 resolving modules (finance, cli/validate, optimize via the private import) plus 3 raw `.homes` reads in optimize; 6 SEG-onto-home sites under 2 policies (§2.2). The SPOT point stands. |
| fk-188af6c13d71 | the single-home knob gap is unreachable through `iter_configs`/`enumerate_configs` | still unreachable through those entry points. The four resolution forms remain. D25's web single-home sweep wraps a home in a scenario, which makes a form-blind transform necessary. |
| fk-ad65ad5e4e48 | 1 hand-restated copy plus 1 temp-file use of the real loader, not 2 emulations | the same: `_refuse_what_the_loaders_refuse` makes 4 parser calls; `_scenario_reader_errors` writes a temp file; 0 web callers of `parse_fleet_config` |
| fk-be5b13274bcb | 2 ad hoc top-level keys (period, flex_band), not 3 | period (optimize) and flex_band (finance); `name` is re-read raw by both CLIs with a path fallback; both CLIs still load the YAML twice; 2 hand-built `ScenarioConfig`s |

## 3. Resolved design decisions

1. **One read of a scenario's homes: `ScenarioConfig.simulated_homes()`, with the scenario's SEG filled in.**
   - The program text calls this `homes()`. It cannot be: `homes` is a frozen field, and a method of that name becomes the field's default (P7). The accessor is named for what it returns.
   - There is no separate `with_seg()`. A read that leaves the scenario's SEG out is exactly the defect the findings record (`fleet run` simulating homes with no SEG), so the one read applies it.
   - S8's `scenario_fleet` and the stream row's "homes() and with_seg()" become this one method.
2. **D10's fill half lives in the read; its refuse half lives in construction.**
   - `ScenarioConfig.__post_init__` refuses a home whose own SEG rate differs from the scenario's, naming the home and both rates. It is the only refusal point.
   - So `dataclasses.replace` and `map_homes` re-check every transform, and `simulated_homes()` never raises.
   - The CLI's three overwrite loops go (the reader stores the scenario rate, and homes carry none).
   - optimize's SEG knob becomes `dataclasses.replace(scenario, seg_tariff_pence_per_kwh=v)`. Construction refuses it when a home sets its own other rate. This is D10's "optimize's overwrite path becomes a refusal".
3. **Store raw, read resolved.** Each stored home keeps its own `seg_tariff`, which is `None` where the scenario's fills it. `map_homes` hands a transform the stored home, never the filled view. A SEG knob and a home-level knob therefore compose in either order. Writing the filled rate back onto homes would make the next SEG knob a contradiction.
4. **`ScenarioConfig` is frozen, its homes a tuple.** This is heuristic 8, and it makes decision 2's construction check sound.
   - It lands in-leaf on L30's reading, the one S27 β (910) applies to `FleetConfig`.
   - Lists passed in are converted at construction, so the platform's `homes=[h]` keeps working.
   - Lead question 2 covers the case where S23's lock labels the drift breaking.
5. **Decision (1) of the brief: `ScenarioConfig.tariff_config` gets no reader; S5 ζ retires it with `output`.** A scenario-level tariff is the document's top-level `tariff:` key. It is read for every document form and applied to each home **when the home is built**, under the D10 policy: it fills a home with no tariff, and a home whose own `tariff:` differs is refused, naming `homes[i].tariff` and `tariff`. Three reasons:
   - 787 (S2 β) and S11 δ check a home's tariff inside `HomeConfig.__post_init__` (dispatch, grid charging, smart EV charging). A tariff resolved from a scenario field after construction cannot reach those checks.
   - Every tariff reader reads `HomeConfig.tariff_config`. A scenario field would be a second carrier of a fact already on every home: a producer with no consumer (G1).
   - `fleet_distribution:` files already work this way (`generate_homes_from_distribution(fleet_tariff=)`), and `scenario_writer` writes per-home tariffs.

   Until ζ, α makes a set `ScenarioConfig.tariff_config` a construction refusal that names `HomeConfig.tariff_config`, closing the library's silent accept (Q3). γ rewrites S5 ε's retired-key message for `tariff_config:` to name `tariff:`.
6. **Decision (2) of the brief: the period block is S10's window.**
   - `ScenarioConfig.window()` returns `timebase.SimulationWindow(first_day, last_day, timebase.ONE_MINUTE, timezone)`.
   - The days are the period's. The zone is the scenario location's, else the first home's. The cadence is the one `simulate_home` runs at (893, S12 α; L9: no option).
   - No S6 period type exists. `SimulationPeriod` stays only as the frozen field's type. At S29's bump, held leaf ι makes `period` a `SimulationWindow` and retires `SimulationPeriod`.
   - Once S12 makes `simulate_home` build its window from its bounds, a run's `results.window` equals the scenario's `window()`. θ pins that equality.
7. **D11 has three tiers, and each has one home.**
   - **Flag:** `ScenarioConfig.with_window(first_day=, last_day=)`. Every command calls it through one `--start`/`--end` option pair in `cli/utils`. A flag replaces only its own day.
   - **File:** the reader's `period:`.
   - **Default:** `timebase.DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY` (2024-01-01 and 2024-12-31), beside `SimulationWindow` (L42). The reader fills them in when a document has no period.

   `ScenarioConfig.period` stays required, so library callers keep giving one. Construction refuses a period whose days do not parse as dates (P10) or run backwards, through `covered_days`, which names both days. The commands are `home run`, `fleet run`, `fleet sweep`, `finance run` and `optimize configs`.
8. **One document grammar for every form.**
   - The recognised top-level keys are name, description, location, period, tariff, seg, finance, flex_band, community, and exactly one homes source: `home`, `homes` or `fleet_distribution`. A document with two sources or none is refused, naming them.
   - `name` and `period` are optional everywhere (name defaults to `""`; period to decision 7's default).
   - A `scenario:` or `scenarios:` wrapper holds only its own key.
   - **The flat home-file form is retired.** A top-level key of `scenario_blocks.HOME_BLOCK_KEYS` that is not also a scenario key (pv, battery, load, heat_pump, ev, dispatch_strategy) gets a retired-key refusal: "a home's `pv:` block goes under `home:`". The list is derived from the table, so S2 ε (790) and S7 β (914) need no edit there.
   - Why retire it: under one grammar its `name:` and `tariff:` would mean the home's in one form and the scenario's in every other. No shipped scenario, template, writer or web path produces it, and only 4 tests use it.
9. **`flex_band` is a `ScenarioConfig` field; `community` is recognised but read where it is used.**
   - `ScenarioConfig.flex_band: GridServicesBand | None = None` is an additive frozen field. It is parsed through 803's `GridServicesBand.parse`, so the message is S9's. `finance run` uses it unless `--flex-band` is given.
   - `community:` reaches no home. Putting `CommunityConfig` on `ScenarioConfig` would pull it into the frozen closure, under S27's open edits. So the reader recognises the key, and `load_community_config` stays its reader (`fleet run`; `validate config` gains the call so every block is checked).
10. **The loaders are projections of the one reader.**
    - `parse_scenario(document)` is the reader; it is today's `_parse_scenario`, made public.
    - `load_scenario(path)` is one scenario: a bare document or `scenario:`. A `scenarios:` file is refused, naming how many it holds.
    - `load_scenarios(path)` covers every form.
    - Defined by the reader: `parse_fleet_config` and `load_fleet_config` (`FleetConfig(homes=simulated_homes(), name=name)`), `load_home_config` (the one home of a `home:` document; a fleet document is refused, naming it), and `parse_sweep_fleet_configs` (each sweep point's homes get the same scenario-level blocks). `_FleetFileSettings`, `_read_fleet_distribution_file` and `_FLAT_HOME_FILE_KEYS` go: the reader is "the one place that decides which top-level blocks the homes get".
11. **CLI overrides apply to the typed home** (fk-416eb5643e7a, fk-e756dab8077e). `home run` reads `load_scenario(path)`, or the document `{home: {}}` without a file, and requires one home.
    - `--pv-kw` and `--consumption-kwh` replace their one field.
    - `--battery-kwh` replaces `capacity_kwh` on the file's battery, adds `BatteryConfig(capacity_kwh=N)` when there is none, and removes it for 0. This is task 681's option (a).
    - `--location` relocates the scenario and its homes, through 931's `location.parse_location`.
    - `cli/utils.load_config_with_overrides` is deleted.
12. **The dashboard reads its own documents through the reader** (fk-a391cf1f4edf, fk-ad65ad5e4e48).
    - `parse_fleet_form` builds homes and dates from `parse_scenario` of the scenario document it already writes, so the run and the export are one reading. `apply_fleet_overlay` and `_with_fleet_overlay` go.
    - Fleet import calls `parse_scenario` in place of `_refuse_what_the_loaders_refuse`.
    - Builder validation calls it on the document in memory: no temp file, and its separate seg and period checks go.
13. **The finance helpers go in α, not through S8 δ** (lead question 1). α is small and has one prerequisite. 928 (S8 δ) sits behind 922, 925 and S9/S10 leaves. Making α wait for 928 would hold S25's and S26's primitive behind the whole S8 chain. So 928 is proposed to depend on α and β, and to build `scenario_fleet` on `simulated_homes()` and `simulation_bounds()`. It then moves neither helper.

## 4. Contract

### 4.1 `ScenarioConfig` (config.py; α, β, γ)

```python
@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    period: SimulationPeriod                  # ι (held): SimulationWindow
    description: str = ""
    location: Location | None = None
    homes: tuple[HomeConfig, ...] = ()        # lists converted at construction (α)
    home: HomeConfig | None = None
    output: OutputConfig | None = None        # S5 ζ retires
    seg_tariff_pence_per_kwh: float | None = None
    tariff_config: TariffConfig | None = None # refused when set (α); S5 ζ retires
    finance: FinanceConfig | None = None
    flex_band: GridServicesBand | None = None # γ

    def simulated_homes(self) -> tuple[HomeConfig, ...]: ...                         # α
    def map_homes(self, transform: Callable[[HomeConfig], HomeConfig]) -> "ScenarioConfig": ...  # α
    def window(self) -> SimulationWindow: ...                                         # β
    def with_window(self, *, first_day: date | None = None,
                    last_day: date | None = None) -> "ScenarioConfig": ...           # β
    def simulation_bounds(self) -> tuple[pd.Timestamp, pd.Timestamp]: ...             # β
    # is_fleet and get_location unchanged
```

- **`simulated_homes()`:** `(home,)` for the single-home form, else `homes`, in document order. Each home whose `seg_tariff` is `None` is replaced by one with `SEGTariff(name="", rate_pence_per_kwh=seg_tariff_pence_per_kwh)` when the scenario sets a rate. A home's own `SEGTariff` (named or not) is returned unchanged. The tuple is never empty and the call never raises. It is pure: equal on every call, and it allocates new `HomeConfig`s only for filled homes.
- **`map_homes(transform)`:** a new `ScenarioConfig` in the same form, with `transform` applied to each **stored** home and every scenario-level field kept. The result goes through `__post_init__`, so a transform that gives a home a SEG contradicting the scenario's is refused there.
- **`window()`:** the period's first and last calendar days at `timebase.ONE_MINUTE` in the zone of `location`, or of the first home's location when `location` is `None`. The days come from a `date`, an ISO `YYYY-MM-DD` string, or a `Timestamp`'s own date.
- **`with_window(first_day=, last_day=)`:** a copy whose period keeps each day not given.
- **`simulation_bounds()`:** `(Timestamp(window.first_day, tz), Timestamp(window.last_day, tz))`, local midnights. These are the `start, end` that `simulate_home` (end inclusive) and a fleet simulator take.
- **Construction (`__post_init__`)** refuses with `ConfigurationError`, a `ValueError` once 774 lands:
  - neither or both of `home`/`homes` (today's check);
  - a home whose own SEG rate is not `math.isclose` to `seg_tariff_pence_per_kwh`, naming the home's index and name and both rates (α; today's `_reconcile_seg_homes` message, moved);
  - a non-`None` `tariff_config`, naming `HomeConfig.tariff_config` (α);
  - a period whose days do not parse, naming `period.start_date` or `period.end_date` and the value, or whose last day precedes its first, naming both (β, through `covered_days`).

### 4.2 The reader (config.py; γ)

```python
# in timebase.py, beside SimulationWindow (L42); config imports them
DEFAULT_FIRST_DAY: date = date(2024, 1, 1)    # β: D11's default tier
DEFAULT_LAST_DAY: date = date(2024, 12, 31)

def parse_scenario(document: Mapping[str, Any], *, block_path: str = "") -> ScenarioConfig: ...
def load_scenario(path: str | Path) -> ScenarioConfig: ...
def load_scenarios(path: str | Path) -> list[ScenarioConfig]: ...
# projections, defined by parse_scenario:
def parse_fleet_config(document: Mapping[str, Any]) -> FleetConfig: ...
def load_fleet_config(path: str | Path) -> FleetConfig: ...
def load_home_config(path: str | Path) -> HomeConfig: ...
def parse_sweep_fleet_configs(document: Mapping[str, Any]) -> list[tuple[float, FleetConfig]]: ...
```

The document grammar:

| Key | Read by | Reaches |
|---|---|---|
| `name`, `description` | the reader (strings; absent is `""`) | `ScenarioConfig` |
| `location` | `parse_location_block` | every home; `ScenarioConfig.location` |
| `period` | `_parse_period` (keys refused, both dates required, each a date) | `ScenarioConfig.period`; absent is decision 7's default |
| `tariff` | `parse_tariff_config` at `tariff` | each home **as it is built** (`parse_home_block(…, fleet_tariff=)`; `generate_homes_from_distribution(fleet_tariff=)`), under fill-and-refuse |
| `seg` | `parse_seg_rate` at `seg` | `ScenarioConfig.seg_tariff_pence_per_kwh`; homes through `simulated_homes()` |
| `finance` | `parse_finance_config` | `ScenarioConfig.finance` |
| `flex_band` | `GridServicesBand.parse(value, what="flex_band")` | `ScenarioConfig.flex_band` |
| `community` | recognised; `load_community_config` reads it | `fleet run`'s community netting |
| exactly one of `home`, `homes`, `fleet_distribution` | `parse_home_block` per block; `parse_fleet_distribution_config` and the sampler | `ScenarioConfig.home` / `homes` |
| `output`, `tariff_config`, the flat home keys | S5 ε's retired-key table (γ adds the flat keys and rewrites `tariff_config`'s message) | refused, naming the replacement |
| anything else | `refuse_unrecognised_keys` | refused |

- **Reading order** (which refusal comes first): name, description, location, period, tariff, seg, finance, flex_band, then the homes source.
- **Refusals** carry their block path (`scenarios[2].homes[0].tariff`). If S5 δ has landed they go through `scenario_blocks.refusal`; otherwise δ's guard converts them.
- **The tou_optimized-without-tariff warning** of `_read_fleet_distribution_file` moves into the reader unchanged (S2/S11 own whether it becomes a refusal).

### 4.3 The command boundary (cli; δ, ε, ζ)

- `cli/utils` holds one `--start`/`--end` pair:
  - `Annotated[Optional[datetime], typer.Option(..., formats=["%Y-%m-%d"])]`, whose help names the file's `period:` and the default constants;
  - one function that applies them: `scenario.with_window(first_day=…, last_day=…)`.

  Every simulating command uses that pair (Typer refuses a malformed date with exit 2, probed).
- A command simulates `scenario.simulated_homes()` over `scenario.simulation_bounds()`. It reads no raw document key and builds no `ScenarioConfig` of its own.
- `finance run` and `optimize configs` refuse a scenario with no `finance:` with one message, in one `cli/utils` helper.

### 4.4 Seams consumed by later streams (precise, for S25, S26, S8, S18)

- **S25 (board reports)** gets `scenario = load_scenario(path)`, with the flag tier applied through §4.3's pair, from `cli/finance.run` and `cli/optimize.configs` after ε. It reads:
  - `scenario.finance` (never `None` past the helper);
  - `scenario.flex_band` (the `--flex-band` flag wins);
  - `scenario.name or str(path)` for the report title;
  - `scenario.simulated_homes()` and `scenario.simulation_bounds()` for what was simulated;
  - `scenario.window()` for the pre-run day count and, through S10, the extrapolated notice.

  The econ scenario that `project_multi_year`/the solve receive is `scenario` itself. No per-mode copy rewrites its homes: S25's per-mode `FinanceConfig`s are `dataclasses.replace(scenario, finance=…)`, which keeps every invariant above.
- **S26 (knob registry, D25):** a knob is a pure `ScenarioConfig → ScenarioConfig` transform.
  - A finance knob is `dataclasses.replace(s, finance=dataclasses.replace(s.finance, …))`.
  - The SEG knob is `dataclasses.replace(s, seg_tariff_pence_per_kwh=v)`. It is refused at construction, naming the home, when a home sets its own other rate (D10).
  - A home-level knob (degradation, battery capacity, install point) is `s.map_homes(f)`. It works on both forms, so the web's single-home sweep wraps its home as `ScenarioConfig(home=h, …)` and uses the same knobs.
  - Reads go through `simulated_homes()`.
  - A YAML sweep's points come from `parse_sweep_fleet_configs`, each point's homes carrying the document's scenario-level blocks.
  - The registry never writes `homes=`/`home=` directly.
- **S8 (projection):** `scenario_fleet(scenario)` is `ScenarioFleet(homes=scenario.simulated_homes(), start=…, end=…)`, with `start, end = scenario.simulation_bounds()`.
- **S18 (dashboard):** the fleet form's homes are `parse_scenario(<the form's document>).simulated_homes()`. Invariant 11's window half compares the forms' default dates with `timebase.DEFAULT_FIRST_DAY`/`DEFAULT_LAST_DAY`; S18 α repoints the CLI, the templates and `web/simulation_params.py` to them (L42).

### 4.5 Invariants

| # | Invariant | Enforced by |
|---|---|---|
| C1 | Every scenario command, the validator, fleet import, builder validation and the fleet form read a file or document through `parse_scenario` | θ's matrix (§5); grep: no `raw.get(` in `cli/finance.py`/`cli/optimize.py`, no `ScenarioConfig(` in `cli/`, no `load_config_with_overrides`, `_refuse_what_the_loaders_refuse` or `apply_fleet_overlay` in src |
| C2 | A scenario's homes are read only through `simulated_homes()` / `map_homes()` outside `config.py` | α deletes every other form; delivered checks on `_resolve_homes`, `_reconcile_seg_homes`, `_scenario_homes`, `_repriced_at_seg_rate` |
| C3 | No home's own SEG rate contradicts its scenario's; the scenario's fills the rest | construction (refuse) and `simulated_homes()` (fill); θ's export round trip |
| C4 | A scenario-level tariff reaches each home when the home is built, and a home's differing tariff is refused | γ's reader; `HomeConfig.__post_init__`'s own checks (S2/S11) see it |
| C5 | One window per scenario: flag day > file day > default, as a `SimulationWindow` | `with_window`, the reader, construction; θ: every command's simulated bounds equal `simulation_bounds()` |
| C6 | A scenario document holds only keys the reader reads (S5 ε, widened to every form) | γ's tests; the 10 shipped scenarios validate |
| C7 | What `scenario_writer` writes, the reader reads back as equal homes | γ (writer round trip), η (dashboard export) |

## 5. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer | one read of the homes | `ScenarioConfig(home=h, seg=5.0)`; `ScenarioConfig(homes=[h1, h2], seg=5.0)` with h2 carrying its own `SEGTariff("Octopus", 5.0)` | `simulated_homes()` is `(h + SEG 5.0,)`; the pair has h1 filled and h2 unchanged; the stored homes are untouched | α |
| P2 | producer | refusal at construction | a home with SEG 3.0 beside scenario 5.0; `tariff_config=TariffConfig.economy_7()` | each raises `ConfigurationError`; the first names the home and 3.0 and 5.0 (RED Q2), the second `tariff_config` and `HomeConfig.tariff_config` (RED Q3) | α |
| P3 | producer | frozen value | a constructed scenario | assigning `homes` raises `FrozenInstanceError` (RED P11); `homes=[h]` stores `(h,)` | α |
| P4 | producer | form-blind transform | `ScenarioConfig(home=h).map_homes(f)`; the fleet form | `.home == f(h)`; each home is `f(home)`; a transform adding SEG 3.0 under scenario 5.0 is refused | α |
| P5 | consumer: optimize | D10 on the SEG knob | `apply_knob(s, "seg", 10.0)` on a reader-shaped scenario; on one whose homes carry SEG 5.0 | every simulated home exports at 10.0; the second raises naming a home (today: overwrites) | α |
| P6 | producer | the window | `period=SimulationPeriod("2024-06-01","2024-08-31")`, Bristol | `window() == SimulationWindow(date(2024,6,1), date(2024,8,31), ONE_MINUTE, "Europe/London")`; `with_window(last_day=date(2024,6,7)).window().days == 7`; `SimulationPeriod("2024","2024")` and a reversed period are refused naming `period.start_date` / both days (RED P10) | β |
| P7 | consumer: finance, optimize | bounds read once | a recording `simulate` | `project_multi_year`, `solve_cost_recovery_rate` and the age-0 outlay request `scenario.simulation_bounds()`; no `get_start_timestamp` call remains in finance.py or optimize.py | β |
| R1 | producer | every form, one grammar | `home:`, `homes:`, `fleet_distribution:`, `scenario:`, `scenarios:` documents with location, tariff, seg, period | `load_scenarios` reads each (RED P9 for `fleet_distribution:`); homes carry the location and tariff; `simulated_homes()` carries the SEG (RED P1, P2) | γ |
| R2 | producer | refusals by name | top-level `finanse:`; a flat `pv:`; `home:` + `homes:`; neither; `flex_band: 1`; a home with its own differing `tariff:` | `validate config` exits 1, naming `finanse`; `pv` and `home:`; both sources; the three sources; `flex_band` with S9's message; `homes[0].tariff` and `tariff` (RED Q1, P4) | γ |
| R3 | consumer: writer | round trip | `fleet_scenario([h, h])` and `home_scenario(h)`, h with SEG 15 | read back, the homes equal `[h, h]` and `h` (RED P3) | γ |
| R4 | consumer: CLI | `fleet run` prices export | a 1-home fleet with `seg: 15`, synthetic June weather seeded in `weather_cache` | Grid Export Revenue = Grid Export × 0.15 (today £0.00) | γ |
| R5 | consumer: CLI | nothing else moves | the 10 shipped `scenarios/*.yaml` | `validate config` OK for each | γ |
| H1 | consumer: CLI | `home run` reads the one reader | flat file; `homes:` file; `hom:`; `home: null`; bristol-arbitrage with `--battery-kwh 10`; with `--start 2024-01-10` | exit 1 naming `pv`/`home:`, `fleet run`, `hom`, `home`; a 10 kWh battery with `grid_charging` 0.9 (RED P5); bounds 2024-01-15..01-15 and 2024-01-10..01-15 (today 2024-01-01..12-31) | δ |
| F1 | consumer: CLI | finance and optimize agree | C1's file, recording simulator; with `--end 2024-06-07` | both simulate 2024-06-01..08-31 (RED: finance 01-01..12-31), then both 06-01..06-07 | ε |
| F2 | consumer: CLI | structured period and band | `period: {start: …}`; `period: "2024"`; `flex_band: 1` | each exits 1 naming the key (RED C2, C3; today `period: "2024"` is a traceback) | ε |
| F3 | consumer: CLI | the inert carve-out goes without effect | a seg scenario, fake simulator | the `finance run --project` report is byte-identical before and after (task 287's measurement) | ε |
| L1 | consumer: CLI | fleet commands honour the period | a fleet file with `period: 2024-06-01..06-07`; `fleet sweep` on a YAML sweep with that period | "for 7 days", and the bounds (today 366) | ζ |
| W1 | consumer: web | run equals export | a fleet form with SEG 15 | `POST /api/fleet/export-yaml` read back by `load_scenario` gives `simulated_homes()` equal to the homes `POST /api/simulate/fleet-from-distribution` runs (today `seg_tariff` `None`) | η |
| W2 | consumer: web | import refuses what the CLI refuses | `POST /api/fleet/import-yaml` of a fleet scenario with `finanse:` | HTTP 400 naming `finanse` (RED Q7: 200, listed in `not_loaded`) | η |
| W3 | consumer: web | builder validation in memory | `POST /api/scenarios/validate` of a form with an invalid seg block | 200 with the reader's refusal; no temp file (grep `tempfile` absent in `builder_form.py`) | η |
| G1 | integration | one file, every entry point | θ's matrix (§8 θ) over `home:`, `homes:` and `fleet_distribution:` documents with location, tariff, seg and a non-default period | every entry point simulates `load_scenario(path).with_window(flags).simulated_homes()` over its `simulation_bounds()`. optimize's homes match those homes in every field its install point leaves alone | θ |
| G2 | integration | the realised window | G1's `home run` case, after S12's window construction | the simulated results' `window` equals `scenario.window()` | θ |
| X1 | consumer: S8 | `scenario_fleet` | 928 built on α and β | `scenario_fleet(s).homes == s.simulated_homes()` and `(start, end) == s.simulation_bounds()` | 928 (proposed) |
| X2 | consumer: S26 | knobs compose | `seg` then `degradation`, and the reverse, on a reader-shaped fleet | equal scenarios; P5's refusal | S26 (proposed) |
| HB | consumer: library | held | S29's bump window | `ScenarioConfig.period` is a `SimulationWindow`; `config.SimulationPeriod` is gone from `FROZEN_CLOSURE`; the platform builds a window | ι |

## 6. Existing tasks this PRD meets

| Task | Status at authoring | Relation |
|---|---|---|
| 485 | pending; carries fk-188af6c13d71 and fk-0b791f2be2d6 (mechanical row) | One public home read on ScenarioConfig. Superseded by α, which carries both keys. |
| 296 | pending, depends on 186 | One SEG helper for scenario and homes. Superseded by α (decisions 2, 3). Cancel before 186. |
| 185 | pending | `fleet run` ignores `seg:`. Superseded by γ (R4). |
| 542 | pending | `homes:` fleet's top-level tariff dropped. Superseded by γ (decision 5). |
| 325 | pending | Top-level keys unchecked. S5 ε covers `scenario:` documents; γ covers every other form. Superseded by γ. |
| 422 | pending | `home run` and `load_home_config` disagree. Superseded by δ. |
| 681 | pending, depends on 422; carries fk-e756dab8077e (mechanical row) | `--battery-kwh` drops the battery block. Superseded by δ (option a), which carries the key. Cancel before 422. |
| 186 | pending (its `x_ruling` names 287 the carrier) | The finance/optimize scenario-loading duplication. Superseded by ε. Cancel after 287 and 296. |
| 287 | pending, depends on 186 | The inert cost-recovery carve-out. Superseded by ε (F3). |
| 541 | pending | optimize's raw period and finance's raw flex_band. Superseded by ε (F2). |
| 528 | pending | `validate config`'s first refusal for a YAML sweep. **Kept:** sweep detection is S26's. Proposed edge 528 → γ, so it builds on `_homes_defined_by`'s new form. |
| 738 | in progress | `finance run`'s body split (fk-f66948b9528c). ε depends on it, so ε edits the restructured body. |
| 803 | pending | S9 γ types `--flex-band` and the scenario `flex_band` through `GridServicesBand`. γ depends on it; ε deletes its raw read. |
| 928 | pending | S8 δ, `projection.scenario_fleet`. Proposed to depend on α and β (decision 13; lead question 1). |

## 7. Cross-PRD relationship

| Other stream / PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S5 `scenario-grammar-partition.md` | consumes | the final layout; ε's scenario unknown-key and retired-key refusal; `HOME_BLOCK_KEYS`, `parse_home_block`, `refuse_unrecognised_keys` in `scenario_blocks`; δ's `refusal` | S5 | γ depends on S5 γ and ε (ids at decompose); S5 ζ retires `tariff_config` (S6 names no reader) |
| S1 `errors-leaf.md` | consumes | `ConfigurationError` a `ValueError`, so finance tests catching `ValueError` for the moved SEG refusal keep passing | S1 | α depends on 774 |
| S2 `dispatch-configuration-below-config.md` | consumes | 787's `HomeConfig.__post_init__` reads the home's tariff, so a scenario tariff is applied at build (decision 5); 790 drops the home dispatch key, and γ's flat-key list derives from the table | S2 | no edge |
| S4 `finite-quantities.md` | file overlap | 866's `_constructed` may wrap `ScenarioConfig` construction refusals with the block path; 868 edits the fleet grammar the reader calls | S4 | order-insensitive |
| S7 `component-defaults-one-home.md` | file overlap | 914's block key tables include `HOME_BLOCK_KEYS`; 919 rewrites `generate_homes_from_distribution` (its `fleet_tariff` keyword stays) | S7 | textual |
| S8 `finance-partition.md` | produces for | `simulated_homes()` and `simulation_bounds()` are `scenario_fleet`'s inputs; α deletes `_resolve_homes` and `_reconcile_seg_homes` | S6 (accessors), S8 (`scenario_fleet`) | **reciprocal:** S8 §13 proposes "S6's homes leaf depends on δ"; this PRD proposes 928 → α, β (lead question 1) |
| S9 `grid-services-pricing-model.md` | consumes | `GridServicesBand.parse` for `flex_band` | S9 | γ → 803 |
| S10 `simulation-window-and-cadence.md` | consumes | `SimulationWindow`, `covered_days`; 778 pins the window in `FROZEN_CLOSURE`; 783's day-count message edits in cli land on `scenario.window().days` | S10 | β → 778; 783 textual |
| S11 `tariff-coverage-classifier-presets.md` | consumes | `parse_tariff_config` reads the top-level `tariff:`; S11 δ's smart-EV check at `HomeConfig` construction (decision 5) | S11 | no edge |
| S12 `load-composition-and-calendar-days.md` | consumes | `timebase.ONE_MINUTE`; `simulate_home` building its window | S12 | β → 893; θ's G2 row needs S12's window construction (asserted if landed, else recorded) |
| S16 `fleet-execution-policy.md` | consumes | 882: every command reads its runner from the invocation, θ's recorder; 889 and 890 edit `cli/fleet.run` and `cli/finance.run` | S16 | θ → 882; others textual |
| S17 `web-request-boundary.md` | consumes | 931's `location.parse_location` for `home run --location`; 935/937 edit `fleet_scenario.py`/`builder_form.py` | S17 | δ → 931; η textual. S17 §out-of-scope's "fleet import loading a scenario's location (S6)" is **not taken**: the fleet page has no location control (lead question 4) |
| S18 dashboard limits (PRD not yet authored) | produces for | the fleet form's homes through `parse_scenario`; `DEFAULT_FIRST_DAY`/`DEFAULT_LAST_DAY` for invariant 11's window half | S6 | cross-reference |
| S25 board reports (not yet authored) | produces for | §4.4: `load_scenario`, `simulated_homes()`, `simulation_bounds()`, `window()`, `flex_band`, the finance helper, from `cli/finance.run` and `cli/optimize.configs` | S6 | **proposed:** S25's cli/finance and cli/optimize leaves depend on ε |
| S26 sweep knob registry (not yet authored) | produces for | §4.4: knobs as `replace`/`map_homes`; YAML sweep points through the reader | S6 | **proposed:** S26's registry leaf depends on α and γ |
| S27 `community-dispatch-from-factory.md` | file overlap | `load_community_config` stays the community reader; 909 moves it in `cli/fleet.run` | S27 | textual |
| S29 surface bump | produces for | ι held; release section lines (§8) | S29 releases ι | ι held |

## 8. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries the following metadata:
- `x_finding_key` (list), `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`;
- priority = the highest severity among its keys;
- file-level `metadata.files`.

Each leaf re-reads its symbols at its base (freshness clause) and records §2.4's measurement for any weakened key it carries.

**α — ScenarioConfig answers which homes it simulates: one read, fill-and-refuse SEG, a frozen value** (intermediate with its own signal; unlocks β, 928; priority high)

- **Keys:** fk-8047de9b6789, fk-188af6c13d71, fk-0b791f2be2d6, fk-81d0840d19e2.
- **Modules:**
  - `config.py` (`ScenarioConfig`);
  - `finance.py`: `_resolve_homes` and `_reconcile_seg_homes` deleted, with their callers in `project_multi_year`, `project_economics` and `solve_cost_recovery_rate`. If 928 has moved them to `projection.py`, they are deleted there;
  - `optimize.py`: the private import, `_age0_baseline_outlay`, `iter_configs` and `apply_knob` through `map_homes`; `_repriced_at_seg_rate` deleted;
  - `cli/validate.py` (`_scenario_homes` deleted);
  - tests: `tests/unit/config/test_scenario_file.py`, `tests/unit/test_finance_projection_scenario_seg.py`, `tests/integration/test_optimize_sensitivity.py`, and `tests/integration/test_finance_economics.py` (its `object.__setattr__` empty-homes test goes with the branch);
  - `tests/unit/test_public_api_surface.py`: the `ScenarioConfig` form becomes frozen with tuple homes; `FROZEN_MEMBERS` gains `simulated_homes` and `map_homes`;
  - `docs/domain-library-consumption.md`; `docs/cost-recovery-finance-model.md` where it names `_reconcile_seg_homes`.
- **Work:** §4.1's α part; decisions 1–5's α halves; the SEG knob as `replace` (D10). Add an Unreleased line: `ScenarioConfig` is frozen; it fills and refuses SEG; it refuses a set `tariff_config`.
- **Signal:**
  - P1–P5 through the library. RED today:
    - a contradicting SEG is constructed (Q2);
    - `tariff_config` is accepted (Q3);
    - `homes` is assignable (P11);
    - the SEG knob overwrites.
  - `validate config` stays OK on the 10 shipped scenarios.
  - `grep -E 'def _resolve_homes|_reconcile_seg_homes|def _scenario_homes|_repriced_at_seg_rate' src/` finds nothing.
- **Consumer:** β; 928 (S8 δ, proposed); S25, S26 (§4.4); `finance run` and `optimize configs` (unchanged results: their homes already carry the scenario's rate).
- **Prereqs:** 774. **Supersedes:** 485, 296.

**β — ScenarioConfig answers which window it simulates: the period as S10's window, D11's default tier** (intermediate with its own signal; unlocks γ, 928; priority medium)

- **Keys:** fk-be5b13274bcb, fk-f99038047a27.
- **Modules:**
  - `config.py`: `window`, `with_window`, `simulation_bounds`, and the period check at construction;
  - `timebase.py`: `DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY` beside `SimulationWindow` (L42);
  - `finance.py` and `optimize.py`: the three zone-and-period copies become `scenario.simulation_bounds()`;
  - `tests/unit/config/test_scenario_file.py`;
  - `tests/unit/test_public_api_surface.py`: `FROZEN_MEMBERS` gains the three methods; `timebase.SimulationWindow`'s closure entry comes from 778;
  - `docs/domain-library-consumption.md`.
- **Work:** §4.1's β part; decisions 6 and 7's library half. A period given as a `Timestamp` with a time of day now bounds at its date's midnight; record any library test that relied on the time. Add an Unreleased line: `ScenarioConfig` gains `window()`, `with_window()` and `simulation_bounds()` and refuses a non-date or reversed period; `timebase` gains `DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY` (L42).
- **Signal:**
  - P6 and P7. RED today: `SimulationPeriod("2024","2024")` runs as 2024-01-01 (P10), and no window accessor exists.
  - `grep 'period.get_(start|end)_timestamp'` finds nothing in `finance.py` or `optimize.py`.
  - The finance projection and solve tests pass unchanged: same bounds for every valid period.
- **Consumer:** γ (the reader's default tier); δ, ε, ζ (bounds); 928 (proposed); S25 (`window().days`); S18 (default constants).
- **Prereqs:** α, 893 (`ONE_MINUTE`), 778.

**γ — One reader for every scenario document: the blocks that reach the homes** (leaf; unlocks δ, ε, ζ, η; priority high)

- **Keys:** fk-3be3240278ee, fk-2264bc150fa3, fk-a391cf1f4edf.
- **Modules:**
  - `config.py`:
    - `_parse_scenario` becomes `parse_scenario`, with the recognised and retired keys widened (§4.2);
    - new: `load_scenario`; `flex_band`;
    - `load_scenarios`, `load_home_config`, `parse_fleet_config`, `load_fleet_config` and `parse_sweep_fleet_configs` become projections;
    - deleted: `_FleetFileSettings`, `_read_fleet_distribution_file`, `_FLAT_HOME_FILE_KEYS`;
  - `scenario_blocks.py` (`parse_home_block`'s `fleet_tariff`);
  - `cli/validate.py`: `_homes_defined_by` reads `load_scenarios`, keeps the YAML-sweep branch, and calls `load_community_config`; its docstring stops saying only the homes are checked;
  - `scenario_writer.py` docstrings;
  - `scenarios/bristol-arbitrage.yaml`: the comment that claims `fleet run` threads SEG, and the "wire it yourself" note;
  - tests: `tests/unit/config/test_fleet_file.py`, `test_scenario_file.py`, `test_unrecognised_keys.py` (its flat-home cases become retired-key refusals), `test_home_block.py`, `tests/unit/test_scenario_writer.py` (its "does not read seg: yet" concession goes), `tests/unit/test_cli.py` (validate);
  - `tests/unit/test_public_api_surface.py`: the `ScenarioConfig` form gains `flex_band`;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - decisions 5, 8, 9 and 10; §4.2;
  - measure at γ's base which test fixtures use the flat form or a key outside the grammar, and fix them;
  - Unreleased lines: every document form is one grammar; the loaders give homes the scenario's tariff and SEG; flat home files are refused; `ScenarioConfig.flex_band` is added.
- **Signal:**
  - R1–R5. Three cases are RED today: `fleet run` books £0.00 export revenue on a SEG fleet; `validate config` passes `finanse:` (Q1); the writer round trip loses SEG (P3).
  - `load_fleet_config` on a `homes:` + `tariff:` file gives Economy 7 homes (RED P2).
- **Consumer:** CLI users (`fleet run`, `validate config`, every loader); δ, ε, ζ, η; S25 (`flex_band`); S26 (sweep points).
- **Prereqs:** β; S5 γ and S5 ε (ids at decompose); 803. **Supersedes:** 185, 542, 325.

**δ — `home run` reads its file through the one reader; overrides apply to the typed home** (leaf; priority high)

- **Keys:** fk-416eb5643e7a, fk-2264bc150fa3, fk-e756dab8077e.
- **Modules:**
  - `cli/home.py`: `home_config_for_run` becomes the command's scenario plus its overrides; `--start`/`--end` from the pair;
  - `cli/utils.py`: `load_config_with_overrides` deleted; §4.3's option pair and its applying function added;
  - tests: `tests/unit/test_cli.py` (home run parity), `tests/unit/test_cli_battery_capacity.py`, and a home-file CLI module (the name task 422 planned, `tests/unit/test_cli_home_file.py`, or the existing one);
  - `docs/domain-library-consumption.md` (no change unless it names the override layer).
- **Work:** decision 11; D11's flag tier for `home run`. With no file, the document is `{home: {}}`.
- **Signal:** H1.
  - RED today:
    - the flat file runs as 4 kW (P4);
    - a fleet file, `hom:` and `home: null` run the default home or crash (Q4–Q6);
    - `--battery-kwh 10` drops `grid_charging` (P5);
    - bristol-arbitrage runs 2024-01-01..12-31.
  - `grep 'def load_config_with_overrides' src/` finds nothing.
- **Consumer:** CLI users of `home run`; ε and ζ (the option pair).
- **Prereqs:** γ; 931 (S17 α). **Supersedes:** 422, 681.

**ε — `finance run` and `optimize configs` read the one scenario** (leaf; priority high)

- **Keys:** fk-f99038047a27, fk-be5b13274bcb, fk-81d0840d19e2.
- **Modules:**
  - `cli/finance.py`: the raw loads, flex_band read, SEG threading block, inert `--cost-recovery` branch and hand-built `ScenarioConfig` all go;
  - `cli/optimize.py`: the raw loads, SEG loop, raw period read and hand-built `ScenarioConfig` go;
  - `cli/utils.py`: the no-finance refusal helper;
  - tests: `tests/integration/test_optimize_cli.py`, `test_finance_flex_cli.py`, `test_cost_recovery_cli.py`, and 738's `test_finance_run_cli.py` if present.
- **Work:**
  - §4.3 and §4.4's S25 shape: `scenario = <pair>(load_scenario(path))`; `finance = <helper>(scenario)`; `fleet = FleetConfig(homes=scenario.simulated_homes(), name=scenario.name)`; `start, end = scenario.simulation_bounds()`.
  - optimize's `--grid-services-kw` override stays as S9 left it.
- **Signal:**
  - F1–F3. RED today: the June–August file runs 366 days under `finance run` (C1); a misspelt period and `flex_band: 1` pass (C2, C3); `period: "2024"` is a traceback.
  - `grep -E 'ScenarioConfig\(' src/solar_challenge/cli` and `grep 'raw.get(' src/solar_challenge/cli/{finance,optimize}.py` find nothing.
- **Consumer:** board readers of `finance run` and `optimize configs`; S25.
- **Prereqs:** γ, δ (the option pair), 738. **Supersedes:** 186, 287, 541.

**ζ — `fleet run` and `fleet sweep` honour the file's period** (leaf; priority medium)

- **Keys:** fk-be5b13274bcb.
- **Modules:** `cli/fleet.py` (`run` reads `load_scenario` and the option pair; `sweep` takes the option pair over its document's period); `tests/unit/test_cli.py` (fleet).
- **Work:** D11 for both fleet commands. Its `${VAR}` and YAML-sweep paths keep their structure (S26's).
- **Signal:** L1. Today both commands simulate 366 days for a 7-day period. `grep '] = "2024-01-01"' src/solar_challenge/cli/` finds nothing once δ, ε and ζ have landed.
- **Consumer:** CLI users of `fleet run` and `fleet sweep`.
- **Prereqs:** γ, δ.

**η — The dashboard reads its scenario documents through the one reader** (leaf; priority medium)

- **Keys:** fk-a391cf1f4edf, fk-ad65ad5e4e48.
- **Modules:**
  - `web/fleet_scenario.py`: `parse_fleet_form` reads its own document through `parse_scenario`; `fleet_form_from_scenario` calls `parse_scenario`; `_with_fleet_overlay` and `_refuse_what_the_loaders_refuse` deleted;
  - `web/fleet_config.py` (`apply_fleet_overlay` deleted);
  - `web/builder_form.py` (`_scenario_reader_errors` in memory; its seg and period checks go);
  - `web/api.py` (the export docstrings become true);
  - `optimize.py` (the docstring that compares with `apply_fleet_overlay`);
  - tests: `tests/unit/web_api/test_fleet_yaml.py` (its re-threading workaround goes), `tests/unit/test_web_fleet_scenario.py`, `tests/unit/test_web_builder_form.py`.
- **Work:** decision 12.
- **Signal:**
  - W1–W3. RED today: the export reads back with SEG `None`; the import accepts `finanse:` (Q7); validation writes a temp file.
  - `grep -E 'def apply_fleet_overlay|_refuse_what_the_loaders_refuse' src/` and `grep tempfile src/solar_challenge/web/builder_form.py` find nothing.
- **Consumer:** dashboard users (fleet run, export, import, builder); S18.
- **Prereqs:** γ.

**θ — Integration gate: every entry point simulates what the reader reads** (leaf; priority high)

- **Keys:** fk-3be3240278ee, fk-2264bc150fa3, fk-be5b13274bcb.
- **Modules:**
  - `tests/integration/test_one_scenario_reader.py` (new);
  - `review/briefing.yaml`: one `conventions` line: "every scenario command reads its file through `config.load_scenario`; see that test".
- **Work:**
  - The G1 matrix: three documents (`home:`, `homes:`, `fleet_distribution:`, each with location, tariff, seg and a non-default period). They run through `home run` (the `home:` one), `fleet run`, `finance run`, `optimize configs` (one config point), `validate config`, fleet import and the fleet form (the `fleet_distribution:` one), with flag and no-flag variants.
  - Each run is recorded through 882's injected runner, with no internal patch.
  - Plus G2, asserted when S12's window construction is on main and recorded as pending otherwise.
- **Signal:** G1 and G2 pass. The RED this matrix pins is §2.3's probes: C1 (finance run's window), P1 (fleet run's SEG), Q4 (home run on a fleet file) and Q7 (import). Each row names the leaf that turned it green.
- **Consumer:** every later edit to a scenario command's reading (the briefing line); /review.
- **Prereqs:** δ, ε, ζ, η; 882.

**ι — `ScenarioConfig.period` becomes a `SimulationWindow`; `SimulationPeriod` is retired at the surface bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "the surface bump release window"}`; excluded from this batch's `commit_planning`)

- **Keys:** fk-be5b13274bcb.
- **Modules:**
  - `config.py`;
  - `web/builder_form.py` (its `SimulationPeriod` use, if η left one);
  - `tests/unit/test_public_api_surface.py`: the `ScenarioConfig` form, and `config.SimulationPeriod`'s closure and member entries;
  - tests that build `SimulationPeriod`;
  - `docs/domain-library-consumption.md`, through S29's section.
- **Work:**
  - The field's type becomes `SimulationWindow`. `window()` returns it. Construction refuses a window whose cadence is not `ONE_MINUTE` or whose zone is not the scenario's, until S12/D8 honour another.
  - S29's release line: "`ScenarioConfig(period=SimulationPeriod(…))` becomes `period=SimulationWindow(first_day, last_day, ONE_MINUTE, timezone)`; `config.SimulationPeriod` is retired. Platform: its seam test builds one window."
- **Signal:** HB.
- **Consumer:** S29's release section and consumer recipe; the platform's re-pin.
- **Prereqs:** β; S29 releases it.

**DAG.** α → β → γ → {δ, η}; δ → {ε, ζ}; {δ, ε, ζ, η} → θ; β → ι (held).

**Out-of-batch edges:**
- α → 774;
- β → 893, 778;
- γ → S5 γ, S5 ε, 803;
- δ → 931;
- ε → 738;
- θ → 882.

**Proposed for other sessions (lead):**
- 928 → α, β;
- 528 → γ;
- S25's `cli/finance` and `cli/optimize` leaves → ε;
- S26's registry leaf → α, γ.

**Trigger-chain gate 772:** α, γ, δ, ε and θ are high, so each joins as a dependency.

**G7** (advisory; this repo has no `docs/legibility/design-invariants.md`; walked against dark-factory's trigger shapes):

- **`one-fact-one-home`:**
  - one reader decides every top-level block;
  - one SEG policy (fill in the read, refuse at construction);
  - one window rule with three tiers, each in one place;
  - one default-window pair of constants.
- **`no-silent-fail-soft`:** these silent accepts or fallbacks go:
  - SEG in `fleet run`;
  - a `homes:` fleet's tariff;
  - the period in four commands;
  - flat files and fleet files under `home run`;
  - `--battery-kwh`'s dropped settings;
  - non-string `flex_band`;
  - unknown keys in home and fleet documents;
  - a set scenario `tariff_config`;
  - a non-date period.
- **`no-lockstep-duplication`:** these duplicates are deleted:
  - six SEG-onto-home copies;
  - three window copies;
  - two hand-built `ScenarioConfig`s;
  - the web's restated loader order;
  - the flat-key list, which is now derived from `HOME_BLOCK_KEYS`.
- **`guards-exercise-behaviour`:** θ runs the commands; no guard asserts prose.
- **`exceptions-owned-or-ratified`:** no allow-list entry added.
- **`readers-prove-their-producer`:** not applicable (no store).

## 9. Out of scope

- The fleet page gaining a location control, and fleet import loading a non-default location (S17 §out-of-scope pointed it here). It is a dashboard feature on S18's page. Import keeps naming such a location in `not_loaded` (lead question 4).
- How a YAML sweep is detected, and the sweep's knob placement (S26; task 528 stays).
- The `community:` block's own grammar and the community battery (S27).
- `${VAR}` substitution (task 707).
- Construction-refusal block paths (S4 ε) and the refusal constructor (S5 δ).
- Per-mode finance rendering (S25), the age-0 reuse (S16 ε), the projection move (S8 δ).
- The web's per-home simulate body (`POST /api/simulate/fleet`): it builds homes from home bodies, not a scenario document.
- `home quick`'s own June window: it reads no file.
- A user-settable cadence (L9).

## 10. Open questions

**Tactical** (decide during the leaf):

1. The exact refusal wordings. Each must name the key's path and, for a retired key, the replacement (γ, δ).
2. α: whether the SEG comparison stays `math.isclose` (today's) or becomes exact. The default is `isclose`.
3. β: whether `with_window` takes `date` only, with the CLI converting Typer's `datetime`. The default is `date` only, converted in `cli/utils`.
4. η: builder validation reports the reader's first refusal, where today it can list up to three (loader, seg, period). Keep first-refusal unless a builder test pins several; then collect per block in `builder_form`.
5. γ: whether `parse_home_block`'s keyword is named `fleet_tariff`, to match `generate_homes_from_distribution`, or `scenario_tariff`. One name for both.

**For the lead** (cross-stream; S6's design holds whichever way each goes):

1. **Edge direction with S8 δ (928).** S8 §13 proposes "S6's homes leaf depends on δ". This PRD proposes the reverse. **Default:** 928 depends on α and β, builds `scenario_fleet` on `simulated_homes()` and `simulation_bounds()`, and moves neither helper (decision 13).
2. **Freezing `ScenarioConfig` in-leaf.** α reads L30 as covering `ScenarioConfig` as it covers `FleetConfig` (910). **Default:** in-leaf. If S23's lock (after its ζ) labels the form change breaking at α's base, the freeze moves into ι and α keeps the construction checks alone.
3. **The accessor's name.** The program's "ScenarioConfig.homes()" (D25, the S6 row, S8's PRD) cannot exist beside the `homes` field (P7). **Default:** apply `simulated_homes()` in D25's text and in the S25/S26 briefs. There is no `with_seg()`; `simulated_homes()` includes the fill.
4. **S17's pointer to S6** (fleet import loading a location) has no owner. **Default:** a follow-up candidate for S18, not filed by S6.
5. **Retiring the flat home-file form** is a user-facing grammar change, made here under S6's ownership of the home file's top-level keys (decision 8). **Default:** retire, with a named refusal. If Leo prefers to keep it, γ keeps the form with `name:` and `tariff:` read as the home's, and documents that exception.

## Gate record

- **G1:** each mechanism has a named consumer.
  - `simulated_homes`, `map_homes`: finance, optimize, cli/validate (α), every command (δ–ζ), the dashboard (η), S8's `scenario_fleet`, S26's knobs.
  - `window`, `with_window`, `simulation_bounds`, the default constants: finance and optimize (β), every command (δ–ζ), S25's day count, S18's invariant 11.
  - `parse_scenario`, `load_scenario`, `load_scenarios`: every command, `validate config`, fleet import, builder validation, the fleet form.
  - `flex_band`: `finance run` (ε), S25.
  - The CLI option pair: five commands.
  - The construction refusals: every construction path, including S26's transforms.
  - No producer is orphaned. `ScenarioConfig.tariff_config` is given no reader on purpose (decision 5), and `community` is not lifted onto `ScenarioConfig` because nothing would read it there.
- **G3:** verified at `dfcbde8`:
  - `SimulationWindow` and `covered_days` (777, done; read in `timebase.py`);
  - Typer's `formats=` date option (probed, Typer 0.26.3);
  - the `object.__setattr__` freeze pattern (`SimulationResults`);
  - `generate_homes_from_distribution(fleet_tariff=)`;
  - `parse_tariff_config`, `parse_seg_rate`, `parse_location_block`;
  - the `CliFleetSimulator` recorder (`tests/_cli_fleet_simulator.py`);
  - the shipped scenarios' top-level keys (all within §4.2's grammar).

  Producers outside the batch are upstream of their consumers: 774, 778, 803, 893, 931, 738, 882, and S5 γ and ε (filed before decompose).

  **Substrate fiction caught:** `ScenarioConfig.homes()` (P7), renamed `simulated_homes()`.
- **G4:**
  - S8's reciprocal proposal goes to the lead (question 1).
  - S17's unowned pointer goes to the lead (question 4).
  - S5's `tariff_config` question is decided here (decision 5).
  - S25 and S26 consume §4.4.
  - Every other overlap is textual (§7).
- **G5:** B + H.
  - Blast radius: config, finance, optimize, five CLI and three web modules.
  - About 13 mechanisms.
  - Four consuming streams.
  - §4 is the contract, §5 the sketch, θ the integration gate.
- **G6:** premises checked.
  - Every RED is probed (§2.3).
  - R4's revenue is an identity: `simulate_home` prices each minute's export at the home's flat SEG rate, so revenue = export × rate.
  - F3's byte-identity rests on 287's measurement: the scenario rate is inert when homes carry the same rate, and after ε the econ scenario's simulated homes are the same `SEGTariff("", R)` homes.
  - Each end-to-end signal's capabilities lie in its leaf's dependency set. R4 needs γ plus the existing pricing. H1 needs γ, β and δ. G1 needs 882 for `home run`'s recorder.
  - Every rejection signal is backed by a refusal its own leaf builds, and its absence today is observed.
- **G7:** advisory, walked in §8.
- **META:** decomposing this without further oversight yields one reader that decides every top-level block, and one frozen scenario value. That value answers its homes, its SEG and its window under D10 and D11. Five commands, the validator and three dashboard paths read through both. Each property is pinned by a leaf signal and by θ's matrix. The lead questions order work across streams or rename a seam in other streams' text; none changes S6's design.
