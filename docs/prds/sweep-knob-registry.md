# PRD — Sweep knob registry: one name and one edit for every setting a sweep varies

- **Program:** review-all-solar_challenge-20261013, stream **S26** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 3, upstream S5 and S6, size L, risk medium.
- **Finding keys:**
  - fk-4cc34de4e649 (medium, **weakened**, re-measured in §2.4 per D28);
  - fk-ac39320dcf1d (medium);
  - fk-bea05911eb70 (medium);
  - fk-59fdc80fdded (medium; this stream closes its one-value-generator half, S5 α and γ close the rest);
  - fk-3ca00f8edeb8 (low);
  - fk-0b4f5e04067c (low, mechanical; filed as task 718, superseded here);
  - fk-32d5e6707fb5 (low, mechanical; filed as task 739, in progress, which delivers it; no leaf here carries it, §2.4).
- **Binding rulings:**
  - **D25:** the registry maps a typed knob to a ScenarioConfig → ScenarioConfig transform only, using `ScenarioConfig.homes()` from S6; the web's single-home sweep wraps the home in a scenario.
  - **D28:** the weakened finding is re-measured before decomposing.
  - **D10:** SEG fill-and-refuse; optimize's overwrite path becomes a refusal. This binds the SEG knob.
  - **D4 and D29:** no name here is on the frozen surface (§2.5), so no leaf is held for S29.
  - **L10:** a band-valued events knob is a new registry entry, recorded as a cross-reference and not filed here.
  - **L29:** task 440 is narrowed to `api.simulate_sweep`.
  - **L37:** S5's layout and ordering.
- **Cross-reference lines that bind it:**
  - S5: S26 depends on S5 γ, because `SweepSpec` and the distribution grammar live in `fleet_distribution.py`; the S26 `web/api.simulate_sweep` leaf carries fk-59fdc80fdded.
  - S7: after S7 δ the battery-capacity placement is `ComponentDistribution.draws["capacity_kwh"]`.
  - S9: the grid-services knob means a flat rate, refused under the events model; it builds `FlatGridServices(v)` at 804 (S9 ε), which edits the registry entry if S26 has landed.
- **Status:** authored 2026-10-17 by an author-only spawn /prd seat; committed in aa8dece. Decomposed 2026-10-18 at main `beb1d91`: α 964, β 965, γ 966, δ 967, ε 968, ζ 969, η 971, θ 972, all medium; 718 cancelled (superseded by γ 966) and 140 cancelled (superseded by ε 968, its Steps max with 807); 739 and 440 kept as prerequisites of η and δ.
  - **L43 overrides the body** where they differ: reads go through `simulated_homes()` (the body's `homes()`), the form-preserving write is `map_homes()` (there is no `with_homes` or `with_seg`), and the SEG knob is `replace(seg_tariff_pence_per_kwh=v)`, which construction refuses when a home sets its own other rate, so the knob stays. The S6 edges are β → 955, 957; γ → 959; η → 957.
  - **Decompose corrections** (recorded on the leaves):
    - ζ: S7 defines no path type, so `FleetFieldPath` is ζ's own alias unless 916's sampler names a key type.
    - δ: `web/sweep_request` cannot import 807's `_SWEEP_MAX_STEPS` from the Flask module `web/api.py`, so the ceiling moves into `sweep_request`.
    - ε: no `JSON.parse` in `parameter-sweep.js`, because 888's check is absent on it.
    - γ: C8's 6-of-8 count needs a fixture grid rate outside the band values.
    - β: under D10, P3's SEG case is valid only at the per-home rate.
  - **Extra edges added at decompose**, for the lead to ratify: ζ → 957 and η → 960 (each rewrites the same reader as the S6 leaf), and 767 → γ (767's own text waits on S26).
- **Approach:** B + H. The registry is a seam read by four entry points (web API, sweep page, `fleet sweep`, `optimize configs`) and edited by a later stream (S9 ε). Its leaves touch eight modules, so §4 is a contract and §5 a two-way boundary-test sketch.
- **Code anchors** verified against main `dfcbde8` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time. Since the review's pin `7dfea36`:
  - `optimize.py` changed in tasks 704 (`SENSITIVITY_BANDS`) and 717 (a public `apply_knob` replaced `_build_axis_configs`, the anchor of fk-4cc34de4e649);
  - `cli/optimize.py` changed in 704 (the alias map names knobs only) and 773;
  - `web/api.py` changed in 153 (imports hoisted);
  - `cli/fleet.py` and `config.py` differ only by 773's import line.

## 1. Goal

"Vary one named setting of a scenario across runs" becomes one mechanism. It has three parts:

- **One registry.** It maps a knob's name to the one edit that sets it, a pure `ScenarioConfig → ScenarioConfig` transform.
- **One alias table.**
- **One value generator.** `SweepSpec` has a typed mode, one default and finite points.

The web sweep, `optimize configs`' sensitivity axes and install grid, and `fleet sweep --param` all resolve names through the registry. Where a YAML-defined sweep may sit is data that the grammar checks when it parses the file.

What a user observes:

1. **The web sweep refuses what it cannot run, before any job.**
   - `POST /api/simulate/sweep` with `mode: "log"` answers 400, naming `mode`, `'log'`, `linear` and `geometric`. Today it answers 201 and runs a linear sweep (probed).
   - A battery sweep up to 200 kWh answers 400, naming `battery_capacity_kwh` and its 0–100 range. Today it submits three jobs (probed).
   - A body without `mode` sweeps geometrically, the one default: `[1.0, 2.0, 4.0]` for 1 to 4 in three steps. Today it gives `[1.0, 2.5, 4.0]`.
   - Every submitted home is the base home with the registry's knob applied. For the page's default body this is exactly the home today's per-point parse builds (probed equal for all three parameters).
2. **The sweep page knows only what the server tells it.** Its parameter list, labels, starting ranges, preselected mode and preview values come from the server. The preview of a geometric sweep from 0 shows the server's own refusal. Today `parameter-sweep.js` restates the three parameters, ranges that disagree with the server (PV 1–20 against 0.5–20, battery 0–50 against 0–100), and the point arithmetic.
3. **A misplaced YAML sweep is refused when the file is read, naming where it sits.** `validate config`, `fleet run` and `fleet sweep` on a file whose sweep multiplier sits on `battery.max_charge_kw` each exit 1, naming `fleet_distribution.battery.max_charge_kw` and the supported `fleet_distribution.battery.capacity_kwh`. Today the first two print an internal message naming `expand_sweep_configs()`, and `fleet sweep` says "No sweep specification found… Use proportional_to with type: sweep", which is what the file already does (probed). `fleet run` on the shipped sweep file says it defines a sweep and to run it with `fleet sweep`. Today it prints the same internal message (probed).
4. **`fleet sweep` speaks the registry's names.**
   - `fleet sweep fleet.yaml --param battery_capacity_kwh --min 5 --max 10 --steps 2` sets every home's battery capacity, as the web and `optimize configs --battery` do. It writes `battery_capacity_kwh_5.0000.csv`.
   - `--param CAP` still sweeps the file's `${CAP}`.
   - A YAML sweep's points are named by their placement, `battery.capacity_kwh.multiplier=0.1000`. Today they are named `multiplier=0.1000` and written to `multiplier_0.1000.csv`.
   - An overflowing sweep (`min: 1.0e-300`, `max: 1.0e+300`) is refused, naming both values. Today the refusal comes later and from elsewhere: "battery.capacity_kwh must be >= 0 and finite …, got inf kWh" (probed).
5. **`optimize configs` evaluates each distinct sweep once.**
   - On the default `--sensitivity` path it asks its simulator for 6 sweeps' worth of fleets where today it asks for 8. The baseline is no longer re-run inside the panel. The floor value equal to the scenario's floor reuses the baseline (finding measurement).
   - `--sensitivity retained_cash_floor_per_home_per_year_gbp`, the knob's canonical name, is accepted. Today only the alias is.
   - An unknown name is refused, listing the knobs that have a board-facing band.
6. **Guards keep it so.** The per-task verify fails if `optimize`, a CLI module or a web module defines its own knob-name table or edit, if web code generates sweep values, or if the same knob value gives different homes at two entry points.

## 2. Background (measured at `dfcbde8`)

### 2.1 Five mechanisms vary a named setting

| # | Site | Vocabulary | Edit |
|---|---|---|---|
| 1 | `config.detect_sweep_spec`, `_replace_sweep_with_value`, `expand_sweep_configs` (moving to `fleet_distribution.py` in S5 γ) | the YAML `multiplier: {type: sweep}`. The parser accepts it on 19 distribution fields (19 `_parse_distribution_spec` call sites across the pv 7, battery 3, heat-pump 3, load 2 and EV 4 readers); detection looks only at `battery.capacity_kwh` | replaces that spec's multiplier |
| 2 | `cli/fleet.py::sweep --param` | any `${VAR}` in the raw document | text substitution before parsing |
| 3 | `web/api._SWEEP_PARAMETER_HOME_KEYS` | `pv_capacity_kw`, `battery_capacity_kwh`, `annual_consumption_kwh`, mapped to form keys | sets the form key, then re-parses the whole body per point |
| 4 | `config._apply_parameter_to_home` | 8 names, test-only callers | S5 α deletes it |
| 5 | `optimize.apply_knob` (task 717); `optimize._apply_install`; `cli/optimize._SENSITIVITY_ALIAS_MAP`; `sensitivity_panel` | every `FinanceConfig` field, plus `seg`/`seg_tariff_pence_per_kwh` and `degradation`/`degradation_rate_per_year`; 3 install axes; 5 CLI aliases; the literal `retained_cash_floor_per_home_per_year_gbp` special-cased in the panel | `replace` on `finance`; SEG overwrite of every home; PV degradation; the install rule |

### 2.2 Value generators and default modes

- **Generators:**
  - `SweepSpec.get_values`;
  - `ParameterSweepConfig.get_values` (S5 α deletes it);
  - `web/api.simulate_sweep`'s inline log/exp arithmetic, where any mode but `geometric` runs linear;
  - `parameter-sweep.js` `previewValues`, a fourth copy.
- **Default mode:**
  - `geometric` in `SweepSpec`'s field, in `_parse_proportional_to_multiplier`'s `data.get("mode", "geometric")` and in `fleet sweep --mode`;
  - `linear` in `web/api.simulate_sweep` and in the page's preselected radio.
- **`SweepSpec` accepts non-finite points** (probed):
  - `SweepSpec(1e-300, 1e300, 3)` gives `[1e-300, inf, inf]`;
  - `SweepSpec(1.0, inf, 3, "linear")` gives `[nan, inf, inf]`;
  - a NaN `min` passes every check.
  - S4 ζ (868) makes `SweepSpec` read finite numbers. Overflow between two finite ends is still this stream's.

### 2.3 Probes (offline, `uv run --locked --extra dev`)

| Input | Today |
|---|---|
| `POST /api/simulate/sweep {parameter: pv_capacity_kw, min 1, max 4, steps 3, mode: "log"}` | 201, values `[1.0, 2.5, 4.0]` (linear) |
| the same with no `mode` | 201, `[1.0, 2.5, 4.0]`; with `mode: geometric`, `[1.0, 2.0, 4.0]` |
| `battery_capacity_kwh` from 0 to 200 | 201, three jobs, the last a 200 kWh battery |
| `battery_capacity_kwh` 0 to 10, `base_config: {battery_kwh: 0, max_charge_kw: 3}` | 201; the 10 kWh point's battery has `max_charge_kw` 3.0 (the form setting re-read per point) |
| `steps: 1000000` | 201 and 1,000,000 jobs (S19 η, task 807, adds the 50-step bound) |
| each of the three web parameters, applied as `dataclasses.replace` to the parsed base home, against today's per-point `parse_home_config` | equal at 0.5/4/20 kW, 0/7.5/13.5 kWh and 500/3,100/20,000 kWh (no `PVConfig`, `BatteryConfig` or `LoadConfig` field derives a stored value from the swept one) |
| `validate config` on the shipped sweep file with the sweep moved to `battery.max_charge_kw` | ERROR "Cannot sample ProportionalDistribution with SweepSpec multiplier directly. Use expand_sweep_configs()…", exit 1 |
| `parse_sweep_fleet_configs` on the same | "No sweep specification found in config. Use proportional_to with type: sweep in multiplier." |
| `fleet run scenarios/bristol-phase1-proportional-battery-sweep.yaml` | "Configuration error: Cannot sample ProportionalDistribution with SweepSpec multiplier directly…" |
| `validate config` on that file with `min: 1.0e-300, max: 1.0e+300, steps: 3` | ERROR "battery.capacity_kwh must be >= 0 and finite (0 for no battery), got inf kWh" |
| `ScenarioConfig` of the 100 bristol-phase1 homes against a field-by-field copy | equal (`==`); unhashable |

### 2.4 Re-measured findings (D28 and the mechanical rows)

| Finding | Claim | `dfcbde8` |
|---|---|---|
| fk-4cc34de4e649 (weakened) | 5 mechanisms | 5, as §2.1. Mechanism 5's anchor moved: task 717 replaced `_build_axis_configs` with the public `apply_knob`, but the vocabulary is unchanged |
| fk-4cc34de4e649 | 4 spellings of battery capacity | **2 user-facing knob names**, as the skeptic found: the web API's `battery_capacity_kwh` and `optimize configs --battery`. Not spellings of capacity: the YAML multiplier on `battery.capacity_kwh`, a ratio to its source field; `battery_kwh`, the `ConfigPoint` field and web form key; a `${VAR}`, a user label. The "four spellings" deletion therefore reads as one knob name at every entry point that sets a capacity |
| fk-4cc34de4e649 | default-mode clash | confirmed: 3 sites geometric, 2 linear (§2.2) |
| fk-3ca00f8edeb8 | 8 sweeps issued, 6 distinct on the CLI default path | unchanged code path: `configs` runs one sweep, then `sensitivity_panel` reruns the baseline, 3 floor values (no short-circuit, override `None`) and 3 grid values |
| fk-0b4f5e04067c (task 718) | `sensitivity_panel` cognitive 26 | **30** (complexipy at `dfcbde8`); `apply_knob` 5, `run_sweep` 10 |
| fk-32d5e6707fb5 (task 739) | `fleet sweep` cognitive 20 | 20 on main; **8 on `task/739`** (in progress: `_param_sweep`/`_yaml_sweep` return `(param_name, sweep_configs)`, no `type: ignore`, no closure capturing mutable locals). 739 delivers the key; η builds on its shape |
| fk-ac39320dcf1d | 19 accepted, 1 swept; 2 of 2 misplacements refused late without a field | unchanged (§2.3) |
| fk-bea05911eb70 | inline validation, unknown mode linear, no steps bound, JS copies | unchanged (§2.3); task 440's branch (`7c70bf2`, base `f7a4968`) reads min/max/steps through `web.number_fields` and adds `_MAX_SWEEP_POINTS` but keeps the arithmetic and the linear fallback |

### 2.5 Surface and platform

- No name this PRD changes is on the frozen surface:
  - `optimize`'s names, `SweepSpec` and the distribution types are absent from `solar_challenge.__all__`, the lazy map, `FROZEN_SURFACE` and `FROZEN_CLOSURE` (grep of `tests/unit/test_public_api_surface.py` and `__init__.py`);
  - `optimize.__all__` is a module list, not the package surface.
- So `apply_knob`'s move, `run_sweep`'s and `sensitivity_panel`'s keyword changes and `SweepSpec.mode`'s type land in-leaf, each with an Unreleased line in `docs/domain-library-consumption.md`.
- The CLI and the web API are not frozen (S16 decision 6).

### 2.6 Tasks this PRD meets

| Task | Status at authoring | Relation |
|---|---|---|
| 718 (fk-0b4f5e04067c) | pending; branch `task/718` has no commits | Superseded by γ, which carries its key (§8 step 1 at decompose) |
| 739 (fk-32d5e6707fb5) | in progress; `task/739` restructures `fleet sweep` into mode functions | Kept; η depends on it and builds on `_param_sweep`/`_yaml_sweep` |
| 440 | pending (Leo, 2026-10-17: resume to merge); narrowed by the lead to `api.simulate_sweep`; branch `task/440` has finished code at an old base | **Lead question 1.** Default: kept; δ depends on it and moves its reads and its overflow refusal into the request reader and `SweepSpec` |
| 140 | pending; depends on 123 (cancelled), 128 (done) and 835 | Superseded: its parameter-options half by ε, its Steps-max half by 807 (S19 η). Keyless; found by the step-2 search |
| 807 (S19 η) | pending | Owns `_SWEEP_MAX_STEPS` (50), its 400 and `sweep.html`'s `max`. δ and ε depend on it and read the constant |
| 835 (S21 η) | pending | Server-side sweep chart; posts `parameter_label`, which ε renders from the server table. ε depends on it (both edit `parameter-sweep.js` and `sweep.html`) |
| 870 (S4 η) | pending | Reads `simulate_sweep`'s min/max/steps through the number leaf; δ depends on it and moves those reads |
| 868 (S4 ζ) | pending | `SweepSpec` reads its numbers through the leaf; α depends on it |
| 802, 803, 804 (S9 β, γ, ε) | pending, pending, held | 802 refuses a flat rate under the events model and resolves `--sensitivity`'s default per model; 803 repoints `SENSITIVITY_BANDS`' grid entry; 804 builds `FlatGridServices(v)` and edits the registry entry. β depends on 802 and 803 |
| 237, 320, 651 | pending | S5 α's supersessions (its decompose cancels them). Re-read at decompose; nothing here if S5 has cancelled them |

## 3. Resolved design decisions

1. **The registry is its own module above `config`: `scenario_knobs.py`.**
   - Its purpose: it names the settings of a scenario that a sweep or a sensitivity axis varies, and holds the one edit that sets each.
   - It imports `config` (for `ScenarioConfig`) and the domain modules whose fields knobs set: `finance`, `battery`, `seg`, `pv` and `load`, plus `gridservices` from 804.
   - Readers: `optimize`, `cli/optimize`, `cli/fleet`, `web/sweep_request`.
   - It is not in `config.py`, whose purpose S5 states as documents and loaders. It is not below `config`, because its transforms take and return `ScenarioConfig`.
   - This is the seam row's "fleet_distribution/config stratum", one step above `config`.
2. **A knob is a frozen value, and that value is the typed identifier.** `Knob(name, apply)`:
   - `name` is the canonical name, the one every output labels points with;
   - `apply(scenario, value) -> ScenarioConfig` is pure (D25).
   - Boundaries resolve a string to a `Knob` once, through `knob_named`. Past the boundary, code holds `Knob` values: `SENSITIVITY_BANDS` is keyed by `Knob`, and so are the web table's rows.
   - A `StrEnum` was rejected: the finance knobs are derived from `FinanceConfig`'s fields (decision 4), and an enum would restate them.
3. **Every knob is scenario-shaped (D25).**
   - A home-level knob maps one home edit over `scenario.homes()` (S6). It writes the result back through the form-preserving write: S6's `with_homes` if S6 provides it, otherwise a private helper in `scenario_knobs` (lead question 3).
   - The web wraps its one home in a `ScenarioConfig(home=…)` and takes `homes()[0]` back.
   - No knob has a second signature.
4. **The knob set at authoring.**

   | Knob (canonical name) | Aliases | Edit | Source of today's meaning |
   |---|---|---|---|
   | `pv_capacity_kw` | — | `pv_config.capacity_kw` on every home | web, `_apply_install` |
   | `inverter_capacity_kw` | — | `pv_config.inverter_capacity_kw` on every home | `_apply_install` |
   | `battery_capacity_kwh` | — | none at 0 (`has_battery`); else the home's battery with `capacity_kwh` replaced; else a fresh `BatteryConfig(capacity_kwh=v)` | `_apply_install` (decision 6) |
   | `annual_consumption_kwh` | — | `load_config.annual_consumption_kwh` on every home | web |
   | `degradation_rate_per_year` | `degradation` | `pv_config.degradation_rate_per_year` on every home | `apply_knob` |
   | `seg_tariff_pence_per_kwh` | `seg` | the scenario's SEG rate, reaching homes under S6's D10 policy (decision 7) | `apply_knob` (overwrite, which D10 retires) |
   | `grid_services_income_per_kw_per_year_gbp` | `grid_services` | that `FinanceConfig` field until 804; `FlatGridServices(v)`, or `NoGridServices()` at 0, from 804. Under the events model the `FinanceConfig` refusal of 802 applies | `apply_knob`, S9 |
   | each other real-number `FinanceConfig` field, by its field name | `retained_floor`, `battery_cost`, `pv_cost`, `inverter_cost` (the CLI's) | that field of `scenario.finance` | `apply_knob` |

   - The finance knobs are **derived** from `dataclasses.fields(FinanceConfig)`, taking the real-number fields (`float`, `Optional[float]`). A new finance field becomes a knob without an edit here. Year counts (`int`) and the model selector are not knobs.
   - The grid-services knob is an explicit entry. That gives 804 its one edit site (S9 cross-reference), and keeps the knob's name and report label when 804 retires the field (S9 Q6, answered).
   - Tilt and occupants, the test-only engine's extra names, are not knobs: S5 α deletes that engine, and no entry point offers them.
5. **One alias table, in the registry.**
   - `ALIASES` maps each alias to a canonical name. No alias is a canonical name.
   - `knob_named(name)` resolves either form, or refuses with a `ConfigurationError` that names `name` and lists the canonical names and the aliases.
   - `cli/optimize._SENSITIVITY_ALIAS_MAP` and `optimize`'s `_SEG_KNOBS`/`_DEGRADATION_KNOBS` go.
   - `optimize configs --sensitivity` accepts any name that resolves to a knob with a `SENSITIVITY_BANDS` entry. A knob without a band is refused, naming it and listing the banded knobs. The help text lists both forms from the registry.
6. **Battery capacity has one meaning: `_apply_install`'s homogeneous-install rule.** Zero is no battery. An existing battery keeps its power, SOC and dispatch settings. A home without one gains a default `BatteryConfig` at that capacity.
   - The web, `fleet sweep --param battery_capacity_kwh` and `optimize configs --battery` all apply it.
   - `_apply_install` is deleted, and `iter_configs` composes the three install knobs.
   - One web edge changes. A base body with `battery_kwh: 0` and battery settings used to give each point a battery with those settings. It now gives a default battery, because a home without a battery carries no settings (§2.3, probed). β's Unreleased line says so.
7. **The SEG knob sets the scenario's SEG rate and nothing else (D10).** Homes without their own `seg_tariff` export at it. A home whose own rate contradicts it is refused by name, through S6's `with_seg` policy. Today's overwrite of every home (`_repriced_at_seg_rate`) is the path D10 retires. This presumes S6 keeps a home's own SEG distinct from the scenario's fill; lead question 3 passes that to S6. No CLI or board path reaches this knob (it has no band), so no figure moves.
8. **`SweepSpec` is the one value generator.**
   - `SweepMode` is a `StrEnum`, `linear | geometric`. `SweepSpec.mode: SweepMode = SweepMode.GEOMETRIC` is the **one default**. Construction coerces a string and refuses any other, naming `mode`, the value and both modes.
   - `get_values()` returns a `tuple[float, ...]`, not a list, so a spec's points are an immutable value. Its two src callers iterate it, so neither changes.
   - Construction refuses a spec whose points are not all finite, naming `min` and `max`. Task 440's overflow check moves here, so the YAML and CLI paths get it too.
   - Every reader that omits `mode` takes the field default: the YAML multiplier, `fleet sweep --mode` (its default is `SweepSpec`'s) and the web body.
   - Geometric is kept because it is the default at three of five sites and the library's own. The web API's omitted-mode default changes. The page always sends a mode, so the page does not change.
   - Explicit value lists, such as `SENSITIVITY_BANDS`' board bands, are not generated, and they stay tuples.
9. **A YAML sweep's placement is grammar data in `fleet_distribution.py`, not a registry knob.**
   - The multiplier is a parameter of a distribution: a ratio to a source field, applied before homes exist. Re-expressing it as an edit of resolved homes would be wrong whenever another field is `proportional_to` the swept one (S7's F4 admits that). So it cannot be a scenario transform.
   - The table must be read when the file is parsed, and `fleet_distribution` cannot import a module above `config` (S5 C1).
   - So `SWEEP_PLACEMENTS: frozenset[FleetFieldPath]` lives beside the grammar. At authoring it holds the one placement the expander supports, `battery.capacity_kwh`.
   - A placement is S7's `(component, key)` pair. Detection, replacement and expansion are generic over the table, on S7 δ's `ComponentDistribution.draws[key]`. Supporting a second placement is one table entry and a test.
   - The registry does not hold the table. The stream row's "data the registry knows" is read as: data, in the lowest module that must read it (lead question 2).
10. **The placement rule is an invariant of `FleetDistributionConfig` (F7, beside S7 ε's F1–F6).** Construction refuses two things, each naming the path `fleet_distribution.<component>.<key>`:
    - a `SweepSpec` multiplier anywhere outside `SWEEP_PLACEMENTS`;
    - more than one sweep multiplier.

    So a library-built config is refused too.
    - `parse_fleet_config` refuses a document whose distribution still sweeps, naming the placement and `fleet sweep`.
    - `generate_homes_from_distribution` refuses a sweeping distribution at entry, naming `expand_sweep_configs`.
    - The sampler's branch becomes an `assert`: no reader can reach it.
11. **`fleet sweep --param NAME` resolves `NAME` through the registry first.**
    - A knob name sweeps that knob. The document is read once into its scenario (S6's fleet-document reader). Each point is `knob.apply(scenario, v).homes()` as a `FleetConfig`.
    - Any other name is a `${NAME}` document variable, as today.
    - A name that is both a knob and a `${NAME}` the document holds is refused, naming both readings.
    - A name that is neither is refused, listing the knobs (task 707 refuses unused variables).
    - After resolution the axis is a typed value, `KnobAxis | VariableAxis`. One option keeps the CLI small, and the stream row puts the `${VAR}` path through the registry (lead question 4 offers a separate `--knob` option instead).
12. **Every sweep point is labelled `<axis label>=<value>`, and its file is `<axis label>_<value>.csv`.** The axis label is the knob's canonical name, the `${VAR}` name, or the placement path `battery.capacity_kwh.multiplier`. One function names points on all three paths. The `multiplier` literals go.
13. **The sensitivity panel takes its baseline, and the floor has one setter.**
    - `sensitivity_panel(base_configs, axes, *, baseline: RankedSweep, simulate)`. It refuses a baseline whose evaluated points differ from `base_configs`' points, or whose `retained_cash_floor_gbp` differs from theirs, naming both.
    - An axis value whose knob leaves every base scenario equal to itself (`knob.apply(s, v) == s`, dataclass equality, probed) reuses the baseline. That covers the floor value equal to the scenario's floor, with no name special case.
    - `SensitivityAxis` refuses a repeated value, so the `(name, value)` cache goes.
    - `run_sweep` loses its `retained_cash_floor_gbp` override. The floor is the scenario's `FinanceConfig` field, set through its knob. `optimize configs --retained-floor` applies it to the base scenario, as `--grid-services-kw` applies the grid knob.
    - `run_sweep` refuses configs whose floors differ, naming two of them. `RankedSweep.retained_cash_floor_gbp` is their common floor, so the echo is true by construction.
    - The reverse design (route the floor axis through the override) was rejected: it keeps two setters and the special case.
14. **The web's sweep table is the page's one source.**
    - `web/sweep_request.SWEEP_PARAMETERS` maps each web-offered knob to its label, its `FLEET_COMPONENTS` key and its starting range:
      - `pv_capacity_kw` → `pv`, 0.5–20;
      - `battery_capacity_kwh` → `battery`, 0–100;
      - `annual_consumption_kwh` → `load`, 500–20,000.
    - `read_sweep_request(body) -> SweepRequest(parameter, spec)` reads:
      - `parameter` and `mode` with S17's `read_string`;
      - the numbers with the number leaf;
      - `steps` within 2 to 807's `_SWEEP_MAX_STEPS`.
    - It refuses a `min` or `max` outside the component's `fixed_range`. That is the bound the home form applies per field, and since both modes are monotone, every point is then within it.
    - The page renders the table, and its preview comes from a points endpoint that runs the same reader. The JS `parameterOptions` and `previewValues` go.
15. **Values are rounded, then applied.** The web keeps today's 3-decimal rounding of point values before applying the knob. So a job's value, its name and the chart's x-value agree. The rounding is the web's display precision, and the CLI and optimize do not round.
16. **Eight leaves.**
    - α: `SweepSpec`.
    - β: the registry and optimize's knob consumers.
    - γ: the panel and the floor.
    - δ: the web API.
    - ε: the sweep page.
    - ζ: the YAML placement.
    - η: `fleet sweep`.
    - θ: the integration gate.

    β and α are independent producers. The consumers split by entry point, so each leaf's file set is one surface.

## 4. Contract

### 4.1 Module map (after the batch)

| Module | Defines | Imports from the package | Never imports |
|---|---|---|---|
| `fleet_distribution.py` (S5 γ) | `SweepMode`, `SweepSpec` (α); `SWEEP_PLACEMENTS`, F7, the generic `detect_sweep_spec`/`expand_sweep_configs` (ζ) | as S5 §4.1 | `config`, `scenario_knobs` |
| `scenario_knobs.py` (β, new) | `Knob`, `KNOBS`, `ALIASES`, `knob_named` | `config`, `errors`, `finance`, `battery`, `seg`, `pv`, `load`; `gridservices` from 804 | `optimize`, `fleet`, any `cli` or `web` module, any `simulate_*` |
| `optimize.py` | `SENSITIVITY_BANDS: Mapping[Knob, tuple[float, ...]]`; the panel (γ) | `scenario_knobs` | — |
| `web/sweep_request.py` (δ, new) | `SweepParameter`, `SWEEP_PARAMETERS`, `SweepRequest`, `read_sweep_request` | `scenario_knobs`, `fleet_distribution`, `web/fleet_components`, the request readers (S17) | Flask |

### 4.2 Signatures

```python
# src/solar_challenge/fleet_distribution.py (α)
class SweepMode(StrEnum):
    LINEAR = "linear"
    GEOMETRIC = "geometric"

@dataclass(frozen=True)
class SweepSpec:
    min: float
    max: float
    steps: int
    mode: SweepMode = SweepMode.GEOMETRIC      # the one default; a str is coerced, another refused naming mode
    # __post_init__ (after S4 ζ's number reads): geometric needs min > 0; max > min; steps >= 2;
    #   every point finite, else ConfigurationError naming min and max
    def get_values(self) -> tuple[float, ...]: ...

# src/solar_challenge/fleet_distribution.py (ζ)
SWEEP_PLACEMENTS: frozenset[FleetFieldPath]     # {("battery", "capacity_kwh")} at authoring; S7's path type
def detect_sweep_spec(config: FleetDistributionConfig) -> Optional[tuple[FleetFieldPath, SweepSpec]]: ...
def expand_sweep_configs(config: FleetDistributionConfig) -> Iterator[tuple[float, FleetDistributionConfig]]: ...

# src/solar_challenge/scenario_knobs.py (β)
@dataclass(frozen=True)
class Knob:
    name: str                                                   # canonical; the label of every point it sets
    apply: Callable[[ScenarioConfig, float], ScenarioConfig]    # pure; same form out as in

KNOBS: Mapping[str, Knob]        # canonical name -> knob, MappingProxyType, insertion order = help order
ALIASES: Mapping[str, str]       # alias -> canonical name
def knob_named(name: str) -> Knob: ...   # ConfigurationError naming name, listing KNOBS and ALIASES

# src/solar_challenge/optimize.py (γ)
def run_sweep(configs: list[tuple[ConfigPoint, ScenarioConfig]], *, simulate: FleetSimulate) -> RankedSweep: ...
def sensitivity_panel(
    base_configs: list[tuple[ConfigPoint, ScenarioConfig]],
    axes: Mapping[Knob, Sequence[float]],
    *,
    baseline: RankedSweep,
    simulate: FleetSimulate,
) -> SensitivityPanel: ...

# src/solar_challenge/web/sweep_request.py (δ)
@dataclass(frozen=True)
class SweepParameter:
    knob: Knob
    label: str                    # the page's option text, e.g. "PV Capacity (kW)"
    component: str                # FLEET_COMPONENTS key whose fixed_range bounds min and max
    default_min: float
    default_max: float

SWEEP_PARAMETERS: Mapping[str, SweepParameter]    # keyed by knob name, in the page's option order

@dataclass(frozen=True)
class SweepRequest:
    parameter: SweepParameter
    spec: SweepSpec

def read_sweep_request(body: Mapping[str, object]) -> SweepRequest: ...   # the web's one refusal type, naming the field
```

`simulate: FleetSimulate` is S16's form (885 makes it required). `SensitivityAxis.name` stays a `str`, the knob's canonical name, so `output.generate_config_ranking_report` reads it unchanged.

### 4.3 Invariants

| # | Invariant | Enforced by |
|---|---|---|
| K1 | Every entry point that varies a scenario setting by name resolves the name through `knob_named`. `optimize`, `cli/*` and `web/*` define no knob-name table and no knob edit | θ's guard: an AST scan for name→edit dicts and for `apply_knob`, `_apply_install`, `_SWEEP_PARAMETER_HOME_KEYS` and `_SENSITIVITY_ALIAS_MAP` |
| K2 | `knob.apply` is pure: its argument compares equal to a deep copy taken before the call. The result has the argument's form (`home` or `homes`). Applying the same value twice equals applying it once | β's per-knob parametrized test over every `KNOBS` entry, on a fleet and on a single-home scenario |
| K3 | No alias is a canonical name; every alias resolves; an unknown name is refused listing both sets | β |
| K4 | Sweep values come only from `SweepSpec.get_values()`. Its mode is a `SweepMode` with one default, and its points are finite | α (construction), θ's guard (no `math.log`/`math.exp` in `web/`, no `Math.log`/`Math.exp` in `parameter-sweep.js`, no `"geometric"`/`"linear"` default literal outside `SweepMode`) |
| K5 | A sweep multiplier sits only at a `SWEEP_PLACEMENTS` path, at most once per distribution | ζ: F7 at construction; seeded misplacements on every NUMBER field of S7's tables |
| K6 | A point's label is `<axis label>=<value>` on every sweep path | η |
| K7 | The panel's baseline matches its configs (points and floor). A value that leaves the base scenarios equal reuses the baseline. The floor has one setter | γ |
| K8 | A web sweep's `min` and `max` lie within its component's `fixed_range`. The page's options, ranges, preselected mode and preview are the server's | δ, ε |
| K9 | One knob value gives one home at every entry point | θ (B-rows across the web, CLI and optimize) |

**Error semantics.**
- Grammar refusals (α, ζ) are `ConfigurationError`, built through S5 δ's `scenario_blocks.refusal` once that exists. S5 δ's guard (C4) converts any raised before it lands.
- `knob_named` raises `ConfigurationError`.
- A knob's edit refuses only through the config constructor it calls. It adds no range rule of its own; the battery's "0 is none" is `has_battery`'s rule.
- The web reader raises the web boundary's one refusal type (S17 δ), which routes answer with 400.
- Library precondition failures (`sensitivity_panel`'s baseline mismatch, `run_sweep`'s mixed floors, a repeated axis value) are `ValueError`, as `optimize`'s other guards are.

## 5. Boundary-test sketch

| # | Side | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| P1 | producer: generator | one default, typed mode | — | `SweepSpec(1, 4, 3)` is geometric; `SweepSpec(1, 4, 3, "linear").mode is SweepMode.LINEAR`; `mode="log"` raises naming `mode`, `'log'`, `linear`, `geometric` | α |
| P2 | producer: generator | finite points | S4 ζ landed | `SweepSpec(1e-300, 1e300, 3)` raises naming both values (RED: `[1e-300, inf, inf]`, probed) | α |
| P3 | producer: registry | purity and form | a 3-home fleet scenario with a heat pump, an EV and a per-home SEG tariff on one home; a single-home scenario | for every `KNOBS` entry and a valid value, the argument equals its pre-call deep copy, the result keeps its form, and each home keeps every field the knob does not set | β |
| P4 | producer: registry | battery rule | homes with and without a battery | 0 → `battery_config is None`; 7.5 on a home with a 2.5 kW battery keeps 2.5 kW; 7.5 on a home without one gives `BatteryConfig(capacity_kwh=7.5)` | β |
| P5 | producer: registry | names | — | `knob_named("retained_floor") is knob_named("retained_cash_floor_per_home_per_year_gbp")`; `knob_named("battery_kwh")` raises listing canonical names and aliases; the set of finance knobs equals the real-number fields of `FinanceConfig` | β |
| P6 | producer: grammar | placement | the shipped sweep file, with the sweep moved to each NUMBER field of S7's tables in turn | each move raises at parse, naming `fleet_distribution.<component>.<key>` and `fleet_distribution.battery.capacity_kwh` (RED: an internal message or "No sweep specification found", probed); the heat-pump move is refused with or without `heat_pump_type` | ζ |
| P7 | producer: grammar | one sweep | a `FleetDistributionConfig` built in code with two sweep multipliers (a test-local table of two placements) | construction raises naming both paths | ζ |
| C1 | consumer: web API | mode and bounds | the recording job manager of `test_simulate_sweep.py` | `mode: "log"` → 400 naming the modes, no job (RED: 201); battery max 200 → 400 naming `battery_capacity_kwh` and `0`–`100` (RED: 201, 3 jobs); no `mode` → values `[1.0, 2.0, 4.0]` | δ |
| C2 | consumer: web API | points equal today's | the page's default body; each of the three parameters at three values within range | each submitted `HomeConfig` equals `parse_home_config({**base, form_key: v})[0]`, today's per-point home (probed equal) | δ |
| C3 | consumer: web API | preview | — | `POST` to the points endpoint returns the submit's values and submits no job; a geometric body from 0 answers the submit's 400 | δ |
| C4 | consumer: page | server is the source | — | `GET /scenarios/sweep` offers exactly `SWEEP_PARAMETERS`' knobs, labels and ranges, and preselects `SweepSpec`'s default mode; e2e: min 1, max 10, steps 5, linear previews the five values; `parameter-sweep.js` holds no `parameterOptions` literal and no `Math.log` | ε |
| C5 | consumer: CLI | misplaced sweep | P6's files | `validate config`, `fleet run` and `fleet sweep` exit 1 with the row naming the path; `validate config` on the shipped sweep file still reports OK across 16 points | ζ |
| C6 | consumer: CLI | sweep document under `fleet run` | the shipped sweep file | exit 1 naming `fleet_distribution.battery.capacity_kwh` and `fleet sweep` (RED: internal message, probed) | ζ |
| C7 | consumer: CLI | three paths, one meaning | `test_cli.py`'s two-home fleet file and `_run_fleet` | `--param battery_capacity_kwh --min 5 --max 10 --steps 2 --mode linear` writes `battery_capacity_kwh_5.0000.csv`, frame-equal to `fleet run` on the 5 kWh file; the YAML row writes `battery.capacity_kwh.multiplier_1.2500.csv`; `--param CAP` writes `CAP_5.0000.csv`; a file holding `${battery_capacity_kwh}` with `--param battery_capacity_kwh` exits 1 naming both readings | η |
| C8 | consumer: optimize | one baseline | a counting `simulate` through `invoke_cli`, a flat-model scenario at floor 27, the default `--sensitivity` | simulate calls = 6 × one `run_sweep`'s calls (RED: 8 ×); the report is unchanged | γ |
| C9 | consumer: optimize | baseline mismatch, one floor | — | `sensitivity_panel(..., baseline=<a sweep of other points>)` raises naming the points; `run_sweep` over two configs with floors 15 and 27 raises naming both; `optimize configs --retained-floor 27` on a scenario at 27 prints the same report as without the flag | γ |
| C10 | consumer: optimize CLI | names | — | `--sensitivity retained_cash_floor_per_home_per_year_gbp` runs (RED: "Unknown sensitivity alias"); `--sensitivity seg` exits 1 naming `seg_tariff_pence_per_kwh` as having no band and listing the banded knobs | β |
| I1 | integration | one knob, one home | a base home with a 2.5 kW battery | `battery_capacity_kwh` = 7.5 through the web submit, `fleet sweep --param` (the first point's homes) and `enumerate_configs(base, pv, [7.5], inv)` gives homes whose `battery_config` equals `KNOBS["battery_capacity_kwh"].apply` on the same base | θ |
| I2 | integration | guard | the real tree; a `tmp_path` module seeded with a name→edit dict and with `Math.log` in a copy of `parameter-sweep.js` | the seeded violations are reported by file and line; the tree passes | θ |

## 6. Cross-PRD relationship

| Other stream / PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S5 `scenario-grammar-partition.md` | consumes | `SweepSpec`, the distribution grammar, `detect_sweep_spec`/`expand_sweep_configs` in `fleet_distribution.py` (γ); `scenario_blocks.refusal` for grammar refusals (δ); S5 α deletes the test-only engine and `ParameterSweepConfig` | S5 layout; S26 content | α and ζ depend on S5 γ. No edge on S5 δ: its guard converts whichever lands first |
| S6 fleet-document overlays (PRD in authoring) | consumes | `ScenarioConfig.homes()`; a form-preserving write (`with_homes`, or a registry-private helper); `with_seg`'s D10 policy, with a home's own SEG distinct from the fill; the fleet-document reader that gives `fleet sweep` its scenario; S6's rewiring of `cli/optimize.configs`' base scenario | S6 | **β, γ and η depend on S6 leaves; the lead supplies the labels** (lead question 3) |
| S7 `component-defaults-one-home.md` | consumes | `ComponentDistribution.draws` (919, δ) for the generic placement edit; `FleetDistributionConfig.__post_init__` (921, ε), which F7 joins; S7's `(component, key)` path type | S7 | ζ depends on 919 and 921 |
| S4 `finite-quantities.md` | consumes | `SweepSpec` reads its numbers through the leaf (868, ζ); `simulate_sweep`'s min/max/steps through the leaf (870, η) | S4 | α depends on 868; δ depends on 870 |
| S8 `finance-partition.md` | consumes | `run_cost_recovery` and the one projection per config (930, ζ); `optimize`'s imports after the move (928, δ) | S8 | γ depends on 930 (930 depends on 928) |
| S9 `grid-services-pricing-model.md` | both | the grid knob's meaning: a flat rate, refused under the events model by `FinanceConfig` (802, β); the `--sensitivity` default per model (802); `SENSITIVITY_BANDS`' grid entry from the rate table (803); `FlatGridServices(v)` at 804, which edits the registry entry | S9 owns the meaning, S26 hosts the entry | β depends on 802 and 803; **804 depends on β** (proposed; 804 is held for S29, so the edge never delays S26) |
| S16 `fleet-execution-policy.md` | consumes | `simulate: FleetSimulate` required on `run_sweep` and `sensitivity_panel` (885, γ); `fleet sweep` through `simulate_each` (879) and root `--workers` (882) | S16 | γ depends on 885; η is textual over 879 and 882 (no edge) |
| S17 `web-request-boundary.md` | consumes | `read_string` (938, ζ) for `parameter` and `mode`; the one web refusal type (935, δ) | S17 | δ depends on 938 |
| S19 `run-store-one-owner.md` | consumes | `_SWEEP_MAX_STEPS` and its 400, `sweep.html`'s `max` (807, η); no `sweep_id` | S19 | δ and ε depend on 807 |
| S21 `chart-panels-and-theme-tokens.md` | consumes / file overlap | the sweep chart's `parameter_label`, which the page now renders from `SWEEP_PARAMETERS` (835, η); both edit `parameter-sweep.js` and `sweep.html` | S21 chart; S26 labels | ε depends on 835 |
| S18 dashboard limits (PRD in authoring) | produces for | `SWEEP_PARAMETERS` reads `FLEET_COMPONENTS[...].fixed_range`; if S18's `PageLimits` absorbs `FLEET_COMPONENTS` or `_SWEEP_MAX_STEPS`, the table reads it from there | S18 | cross-reference |
| S22 `assistant-facts-from-engine.md` | none | 440's assistant half moved to 751 (L29) | — | — |

## 7. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries:

- `x_finding_key` (list), `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`;
- priority equal to the highest severity among its keys;
- file-level `metadata.files`.

Each leaf records the §2.4 measurement it re-ran at its base. No leaf is high or critical, so none joins trigger-chain gate 772.

**α — SweepSpec: one value generator with a typed mode, one default and finite points** (intermediate; unlocks δ, ζ, η; priority medium)

- **Keys:** fk-59fdc80fdded, fk-4cc34de4e649.
- **Modules:**
  - `src/solar_challenge/fleet_distribution.py` (`SweepMode`, `SweepSpec`, `_parse_proportional_to_multiplier` taking the field default);
  - `tests/unit/config/test_fleet_file.py`;
  - a new `tests/unit/config/test_sweep_spec.py`;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Decision 8.
  - `get_values` returns a tuple. `test_fleet_file.py`'s comparison of the swept values with `get_values()` compares tuples.
  - Write an Unreleased line: `SweepSpec.mode` is a `SweepMode`; a spec whose points overflow is refused; `get_values()` returns a tuple.
- **Signal:**
  - P1, P2.
  - `validate config` on the shipped sweep file with `min: 1.0e-300, max: 1.0e+300, steps: 3` exits 1 with a row naming `min` and `max`. Today the row says "battery.capacity_kwh … got inf kWh" (probed).
  - The shipped sweep file still validates OK across 16 points.
- **Consumer:** δ, ζ, η; S4 ζ's number reads already sit in `SweepSpec`.
- **Prereqs:** S5 γ; 868 (S4 ζ).

**β — scenario_knobs.py: the knob registry and its one alias table; optimize and its CLI resolve names through it** (leaf; priority medium)

- **Keys:** fk-4cc34de4e649.
- **Modules:**
  - `src/solar_challenge/scenario_knobs.py` (new);
  - `src/solar_challenge/optimize.py`:
    - `apply_knob`, `_repriced_at_seg_rate`, `_FINANCE_KNOBS`, `_SEG_KNOBS`, `_DEGRADATION_KNOBS` and `_apply_install` deleted;
    - `iter_configs` composes the three install knobs over `homes()`;
    - `SENSITIVITY_BANDS` keyed by `Knob`;
    - `sensitivity_panel` calls `knob.apply`;
    - the module docstring's API list;
  - `src/solar_challenge/cli/optimize.py`:
    - `_SENSITIVITY_ALIAS_MAP` deleted;
    - `--sensitivity` through `knob_named` and the bands;
    - `--grid-services-kw` applied as the grid knob;
    - the help text from the registry;
  - tests:
    - `tests/unit/test_scenario_knobs.py` (new; P3–P5);
    - `tests/unit/test_optimize_apply_knob.py`, deleted, its cases moved to the new module;
    - `tests/unit/test_optimize_sensitivity_bands.py`;
    - `tests/unit/test_optimize_enumerate.py`;
    - `tests/integration/test_optimize_sensitivity.py`;
    - `tests/integration/test_optimize_cli.py`;
  - `docs/domain-library-consumption.md`;
  - `CLAUDE.md` (the architecture list gains `scenario_knobs.py`).
- **Work:**
  - Decisions 1–7 and §4.2's registry.
  - Write an Unreleased line:
    - `optimize.apply_knob` is now `scenario_knobs.knob_named(name).apply`;
    - `SENSITIVITY_BANDS` is keyed by `Knob`;
    - the SEG knob fills and refuses under D10 instead of overwriting;
    - a web base without a battery gives battery points a default battery.
- **Signal:**
  - C10.
  - P3–P5.
  - `python -c "import solar_challenge.optimize as o; o.apply_knob"` raises `AttributeError`.
  - `optimize configs` on the bristol fixture prints a ranking report byte-identical to its base's: `iter_configs` builds the same homes through the knobs, and `test_optimize_enumerate.py` passes unchanged.
- **Consumer:** γ, δ, η, θ; `optimize configs` users; S9 ε (804) edits the grid entry.
- **Prereqs:** S6's `homes()` leaf and its SEG-policy leaf (labels from the lead); 802 and 803 (S9 β, γ).

**γ — sensitivity_panel takes the baseline RankedSweep; the retained-cash floor has one setter** (leaf; priority medium)

- **Keys:** fk-3ca00f8edeb8, fk-0b4f5e04067c, fk-4cc34de4e649 (the floor-axis name special case).
- **Modules:**
  - `src/solar_challenge/optimize.py`:
    - `sensitivity_panel` per §4.2;
    - `run_sweep` loses the override and refuses mixed floors;
    - `SensitivityAxis` refuses repeated values;
    - the floor special case, its short-circuit and the cache deleted;
  - `src/solar_challenge/cli/optimize.py`:
    - `--retained-floor` applied as the floor knob on the base scenario;
    - `baseline=ranked`;
    - the "72 configs" comment, if S8 ζ has not already replaced it;
  - tests: `tests/integration/test_optimize_sensitivity.py`, `tests/integration/test_optimize_sweep.py` and `tests/integration/test_optimize_cli.py`;
  - `docs/domain-library-consumption.md`.
- **Work:**
  - Decision 13.
  - Re-measure complexipy on `sensitivity_panel` and record it on the task (30 at authoring).
  - Write an Unreleased line: `sensitivity_panel` requires `baseline`; `run_sweep` has no floor override; set the floor through its knob.
  - Supersedes 718.
- **Signal:**
  - C8: through the public CLI with a counting simulator, the default sensitivity path asks for 6 sweeps' worth of fleet simulations, where today it asks for 8.
  - C9.
  - The ranking report is unchanged.
- **Consumer:** `optimize configs` users; library callers of the panel.
- **Prereqs:** β; 930 (S8 ζ); 885 (S16 γ); S6's `cli/optimize.configs` leaf (label from the lead).

**δ — POST /api/simulate/sweep reads one SweepRequest and builds every point through the registry** (leaf; priority medium)

- **Keys:** fk-bea05911eb70, fk-59fdc80fdded, fk-4cc34de4e649.
- **Modules:**
  - `src/solar_challenge/web/sweep_request.py` (new);
  - `src/solar_challenge/web/api.py`:
    - `simulate_sweep`;
    - `_SWEEP_PARAMETER_HOME_KEYS` and the inline arithmetic deleted;
    - a points endpoint (suggested `POST /api/simulate/sweep/points`);
  - `tests/unit/web_api/test_simulate_sweep.py`;
  - a new `tests/unit/web/test_sweep_request.py`.
- **Work:**
  - Decisions 14 and 15, and D25's wrap:
    1. Parse the base body once.
    2. Wrap the home in a `ScenarioConfig(home=…)` over its window.
    3. For each rounded value, apply the knob and take `homes()[0]`.
  - A point the configs refuse answers 400 `Invalid config for <knob>=<value>: <reason>`, as today.
  - Every 400 still comes before any job.
- **Signal:** C1, C2, C3. `mode: "log"` is a 400 (today 201). Battery to 200 kWh is a 400 (today three jobs). An omitted mode sweeps geometrically. Each submitted home equals today's per-point home on the default body.
- **Consumer:** the sweep page (ε); API callers; θ.
- **Prereqs:** α; β; 807 (S19 η); 870 (S4 η); 938 (S17 ζ); 440 per lead question 1.

**ε — The sweep page renders its parameters, ranges, mode and preview from the server** (leaf; priority medium)

- **Keys:** fk-bea05911eb70.
- **Modules:**
  - `src/solar_challenge/web/scenarios.py` (`sweep()` passes `SWEEP_PARAMETERS` and `SweepSpec`'s default mode);
  - `src/solar_challenge/web/templates/scenarios/sweep.html` (a JSON script block; options rendered);
  - `src/solar_challenge/web/static/js/parameter-sweep.js` (`parameterOptions` and the `previewValues` arithmetic deleted; preview fetched from δ's points endpoint);
  - `src/solar_challenge/web/static/dist/style.css`, rebuilt if a class changes;
  - `tests/unit/test_web_scenarios.py`;
  - `tests/e2e/test_parameter_sweep.py`;
  - `docs/web-ui-design.md` §5.
- **Work:**
  - The rest of decision 14.
  - Keep `x-data="parameterSweep()"` (the e2e selectors).
  - Supersedes 140, whose Steps-max half is 807's.
- **Signal:**
  - C4.
  - `GET /scenarios/sweep` offers exactly the knobs `POST /api/simulate/sweep` accepts (140's test a).
  - The e2e preview test passes on the server's values.
  - A geometric preview from 0 shows the server's refusal.
- **Consumer:** dashboard users; 835's `parameter_label`.
- **Prereqs:** δ; 807; 835 (S21 η).

**ζ — A YAML sweep's placement is grammar data; a misplaced or second sweep is refused at parse time naming its path** (leaf; priority medium)

- **Keys:** fk-ac39320dcf1d, fk-4cc34de4e649.
- **Modules:**
  - `src/solar_challenge/fleet_distribution.py`:
    - `SWEEP_PLACEMENTS`;
    - F7 in `FleetDistributionConfig.__post_init__`;
    - generic `detect_sweep_spec`, `_replace_sweep_with_value` and `expand_sweep_configs` over `draws`;
    - `generate_homes_from_distribution`'s entry refusal;
    - the sampler's branch an `assert`;
  - `src/solar_challenge/config.py`:
    - `parse_fleet_config` refuses a sweeping document, naming the placement and `fleet sweep`;
    - `parse_sweep_fleet_configs` names each `FleetConfig` `<placement>=<value>`;
    - `detect_fleet_sweep_spec` returns the placement with the spec;
  - tests: `tests/unit/config/test_fleet_file.py`, `tests/unit/config/test_unrecognised_keys.py`, the S7 fleet-grammar module that holds F1–F6, and `tests/unit/test_cli.py` (C5, C6);
  - `docs/domain-library-consumption.md`.
- **Work:** decisions 9 and 10. Write an Unreleased line: a sweep multiplier outside `fleet_distribution.battery.capacity_kwh` is refused when the file is read; a sweep file under `fleet run` is refused, naming `fleet sweep`.
- **Signal:**
  - P6, P7, C5, C6.
  - The three commands name `fleet_distribution.battery.max_charge_kw` for the misplaced file. Today they print an internal message or a contradiction (probed).
  - `fleet run` on the shipped sweep file names the placement and `fleet sweep`.
- **Consumer:** CLI users of `validate config`, `fleet run` and `fleet sweep`; the web fleet import (its loader check reads `parse_fleet_distribution_config`); η.
- **Prereqs:** α; 919 (S7 δ); 921 (S7 ε).

**η — fleet sweep resolves --param through the registry and labels every point by its axis** (leaf; priority medium)

- **Keys:** fk-4cc34de4e649, fk-ac39320dcf1d (the `multiplier` labels).
- **Modules:**
  - `src/solar_challenge/cli/fleet.py`:
    - `--param` resolution per decision 11;
    - `--mode` typed `SweepMode`, its default `SweepSpec`'s;
    - one point-label function for the three axes;
    - the YAML path's label from the placement;
  - `tests/unit/test_cli.py` (`_SWEEP_PATHS` gains the knob row; point-file names);
  - `tests/unit/test_cli_fleet_sweep.py` (739's module);
  - `CLAUDE.md` (the "Parameter sweeps" bullet names the registry, `SweepSpec` and the placement table).
- **Work:**
  - Decisions 11 and 12, on 739's `_param_sweep`/`_yaml_sweep` shape.
  - The help text names both readings of `--param`.
- **Signal:**
  - C7. `--param battery_capacity_kwh` writes `battery_capacity_kwh_5.0000.csv`, equal to `fleet run` at 5 kWh.
  - The YAML path writes `battery.capacity_kwh.multiplier_1.2500.csv` and prints the placement. Today it writes `multiplier_1.2500.csv` and prints "YAML sweep: multiplier".
  - `--param CAP` still sweeps `${CAP}`.
  - A name with both readings exits 1 naming both.
- **Consumer:** CLI users; θ.
- **Prereqs:** α; β; ζ; 739; S6's fleet-document reader leaf (label from the lead).

**θ — Integration gate: one knob, one meaning at every entry point** (leaf, integration gate; priority medium)

- **Keys:** fk-4cc34de4e649.
- **Modules:**
  - `tests/integration/test_sweep_knob_entry_points.py` (new; I1);
  - a guard test, suggested `tests/unit/test_knob_vocabulary.py` (I2, K1, K4);
  - `review/briefing.yaml` (a `conventions` line pointing at the guard).
- **Work:** §5 I1 and I2. Run the boundary rows of α–η at θ's base and record them on the task.
- **Signal:**
  - I1: `battery_capacity_kwh` = 7.5 gives equal batteries through the web submit, `fleet sweep --param` and `optimize`'s install grid.
  - I2: seeded violations are named by file and line, and the tree passes.
  - Every row of §5 passes at θ's base.
- **Consumer:** every later edit to an entry point (S9 ε, S18, a band-valued events knob); /review through the briefing.
- **Prereqs:** γ, δ, ε, η.

**DAG.**
- Producers: α and β (independent).
- β → γ.
- {α, β} → δ → ε.
- α → ζ.
- {α, β, ζ} → η.
- {γ, δ, ε, η} → θ.

**Out-of-batch edges:**
- α → {S5 γ, 868};
- β → {S6 `homes()` leaf, S6 SEG-policy leaf, 802, 803};
- γ → {930, 885, S6 `cli/optimize` leaf};
- δ → {807, 870, 938, 440 (lead question 1)};
- ε → {807, 835};
- ζ → {919, 921};
- η → {739, S6 fleet-document reader leaf};
- **804 → β** (proposed for S9's held leaf).

**Supersessions at decompose** (§8 step 1 first, then re-read status and claimant):
- 718 → γ;
- 140 → ε (keyless; carries no key, so cancel with `x_superseded_by` ε and a note that 807 owns the Steps max).

**G7** (advisory: this repo has no `docs/legibility/design-invariants.md`; walked against dark-factory's trigger shapes):

- **`one-fact-one-home`:**
  - one name and one edit per knob (K1);
  - one alias table (K3);
  - one value generator and one default mode (K4);
  - one battery-capacity rule (decision 6);
  - one floor setter (decision 13);
  - one placement table (K5);
  - one source for the page's options (K8).
- **`no-lockstep-duplication`:** the JS options and arithmetic, the CLI alias map and `_apply_install`'s restated edits are deleted, not mirrored under a parity test.
- **`no-silent-fail-soft`:** removed silent paths:
  - an unknown web mode read as linear;
  - a misplaced heat-pump sweep never sampled;
  - an overflowing sweep producing `inf`;
  - a panel floor equal to the scenario's re-running silently;
  - a battery sweep beyond the page's own range.
- **`guards-exercise-behaviour`:** θ's guard scans the real tree and a seeded `tmp_path` copy. I1 runs the three entry points. No guard asserts prose.
- **`exceptions-owned-or-ratified`:** none added. The sampler's `assert` is unreachable by construction (F7 and the entry refusal), not an exemption.

No hit.

## 8. Out of scope

- **A band-valued grid-services knob for the events model** (L10; S9 lead question 3). It is a new registry entry, `GridServicesBand`-valued, when someone needs it. The registry's `apply` signature takes a float, so that knob would widen `Knob` to a value type parameter. That is a design pass of its own.
- **Two-dimensional sweeps** (`docs/web-ui-design.md` §5's "optional second dimension").
- **Sweeping a distribution parameter other than the battery multiplier through the YAML grammar.** The table makes it one entry when wanted. `${VAR}` already covers it on the CLI.
- **The Steps max, `sweep_id` and the stored run type** (S19 η, 807). **The sweep chart** (S21 η, 835).
- **Where the dashboard's limits live** (S18's `PageLimits`). The web table reads `FLEET_COMPONENTS` wherever S18 leaves it.
- **The test-only parameter-sweep engine** (S5 α) and **component defaults** (S7).
- **`optimize configs`' projection count per config** (S8 ζ) and **the runner** (S16).
- **The assistant's sweep-free number reads** (751, S22 β).

## 9. Open questions

**Tactical** (decide in the leaf):

1. β: whether the form-preserving write is S6's `with_homes` or a private `_with_homes` in `scenario_knobs`. That depends on S6's landed shape. The rule, same form out as in, is fixed.
2. β: the finance-knob derivation reads `dataclasses.fields` annotations. Since `finance.py` uses `from __future__ import annotations`, a string compare on `"float"`/`"Optional[float]"` is the simplest. `typing.get_type_hints` needs `GridServicesEventsConfig` resolvable (it fails today, probed).
3. δ: the points endpoint's path, and whether it shares `simulate_sweep`'s handler body through `read_sweep_request` only or through a helper that also builds the homes. The points endpoint builds no home.
4. ε: the battery row's starting range under the geometric default. Either keep 0–13.5, so the preview shows the server's refusal until the user picks linear, or start it at a positive minimum. A UX call; both keep one default.
5. ζ: whether F7 lives in S7 ε's `__post_init__` checks or in a helper it calls. The refusal text must name the path, and the supported placements when there is one.
6. η: the help-text wording for `--param`'s two readings.
7. θ: whether the vocabulary guard is AST-based (name→callable dict literals in the entry modules) or a list of retired names plus a regex over `static/js`. Both must seed a violation.

**For the lead** (S26's design holds whichever way each goes):

1. **Task 440.**
   - Its branch is finished, at an old base. It reads the sweep's min, max and steps through `web.number_fields`, adds `_MAX_SWEEP_POINTS` and refuses overflowing points.
   - Leo ruled on 2026-10-17 to resume it to merge, and the lead narrowed it to `api.simulate_sweep`.
   - δ rewrites that function: the reads move into `read_sweep_request`, the overflow refusal into `SweepSpec`, and the bound is 807's constant.
   - **Default:** keep 440; δ depends on it and moves what it adds.
   - The alternative is to cancel 440 with `x_superseded_by` δ and spare its rebase. That is a live-branch cancel, so it is Leo's.
2. **Where the YAML placement table lives.** The stream row says the placement is "data the registry knows". The table must be read by the parser, below `config`, and the registry sits above `config` (S5 C1 forbids the upward import). Decision 9 puts the table in `fleet_distribution.py` and keeps the registry for scenario knobs.
   - **Default:** as decision 9.
   - The alternative is to put the registry in `config.py`, so the parser could read it. That reverses S5's purpose statement for `config.py` and still leaves the parser below it, so it does not work either. No leaf changes under the default.
3. **S6 seams.** β, γ and η need four things from S6:
   - `homes()`;
   - a form-preserving write, or the registry builds its own;
   - D10's fill-and-refuse at resolve time, with a home's own SEG distinct from the scenario's fill, so that the SEG knob can set the scenario rate alone;
   - the fleet-document reader that `fleet sweep` reads its scenario through.

   **Default:** the lead passes these to the S6 author and supplies the four leaf labels for the edges. If S6 fills homes at parse time instead, the SEG knob cannot tell a home's own rate from the fill. Then it must refuse every fleet whose homes carry rates, or overwrite them, which D10 rules out. In that case the SEG knob is dropped from the registry until S6 offers the distinction. No CLI path reaches it.
4. **`fleet sweep --param` with two readings.** Decision 11 resolves the name through the registry, then as a `${NAME}`, refusing a name with both readings. The stream row puts "cli fleet sweep's ${VAR} path" through the registry.
   - **Default:** as decision 11.
   - The alternative is a separate `--knob NAME` option, with `--param` left as the variable path. It is more explicit, at one more option, and only η changes.
5. **804's edge on β.** S9's cross-reference says 804 edits the registry entry "if S26 has landed". **Default:** add 804 → β, so 804 always has the entry to edit. 804 is held for S29's bump window, so the edge delays nothing.

## 10. Proposed cross-reference lines (for the lead to apply)

- **S6:** "S26 β, γ and η depend on S6 for:
  - `ScenarioConfig.homes()`;
  - a form-preserving write of a scenario's homes (`with_homes`), or S26's private helper;
  - D10's fill-and-refuse applied at resolve time, with a home's own SEG distinct from the scenario's fill. S26's SEG knob sets the scenario rate only;
  - the fleet-document reader that `fleet sweep --param <knob>` reads its scenario through;
  - the rewired `cli/optimize.configs` base scenario, on which `--retained-floor` and `--grid-services-kw` apply their knobs.

  The S6 decompose returns those leaf ids."
- **S9:** "804 (S9 ε) depends on S26 β. It edits `scenario_knobs`' grid-services entry to build `FlatGridServices(v)` (`NoGridServices()` at 0). The knob keeps its name, `grid_services_income_per_kw_per_year_gbp`, and its report label (S9 Q6). `SENSITIVITY_BANDS` is keyed by `Knob` after S26 β."
- **S5:** "S26 α edits `SweepSpec` in `fleet_distribution.py` (mode typed, `values()`, finite points), and ζ adds `SWEEP_PLACEMENTS` and F7 there. Their grammar refusals build through `scenario_blocks.refusal` if S5 δ has landed; otherwise S5 δ's guard converts them."
- **S7:** "S26 ζ's F7 (one sweep multiplier, only at `SWEEP_PLACEMENTS`) joins `FleetDistributionConfig.__post_init__`'s F1–F6 after 921. The placement edit is `ComponentDistribution.draws[key]`, generic over the table."
- **S4:** "868's `SweepSpec` number reads land before S26 α. 870's `simulate_sweep` reads land before S26 δ, which moves them into `web/sweep_request.read_sweep_request`."
- **S8:** "S26 γ depends on 930. `sensitivity_panel` takes the caller's baseline `RankedSweep`, and `run_sweep` loses its floor override, so 930's `run_sweep` docstring describes the one-setter form if S26 γ lands first."
- **S16:** "885 makes `simulate` required on `run_sweep` and `sensitivity_panel`. S26 γ depends on 885 and adds the required `baseline`."
- **S17:** "S26 δ reads the sweep's `parameter` and `mode` with `read_string` (938), per S17 decision 15."
- **S18:** "`web/sweep_request.SWEEP_PARAMETERS` bounds each web sweep by `FLEET_COMPONENTS[<component>].fixed_range`, and reads 807's `_SWEEP_MAX_STEPS`. If `PageLimits` absorbs either, the table reads it there. `parse_home_config`'s PV literal 0.5–20 restates `FLEET_COMPONENTS['pv'].fixed_range`; that literal is S18's."
- **S19:** "807 owns `_SWEEP_MAX_STEPS`. S26 δ and ε depend on 807 and read the constant."
- **S21:** "835's `parameter_label` is the page's, rendered from `SWEEP_PARAMETERS` after S26 ε. ε depends on 835."
- **Tasks:**
  - "718 is superseded by S26 γ (fk-0b4f5e04067c). 140 is superseded by S26 ε, with 807 for the Steps max.
  - 739 delivers fk-32d5e6707fb5 (complexipy 20 → 8 on `task/739`), and S26 η depends on it.
  - 440 stays as narrowed, and S26 δ depends on it (lead question 1).
  - 237, 320 and 651 are S5 α's to cancel."

## Gate record

- **G1:**
  - `SweepSpec`'s typed mode and finite points are consumed by `fleet sweep`, the YAML grammar and the web (α → δ, ζ, η).
  - `scenario_knobs` is consumed by `optimize configs`' sensitivity axes and install grid (β, γ), the web sweep (δ), `fleet sweep --param` (η) and S9 ε (804).
  - `SWEEP_PARAMETERS` and `read_sweep_request` are consumed by `POST /api/simulate/sweep`, its points endpoint and the sweep page (δ, ε).
  - `SWEEP_PLACEMENTS` and F7 are consumed by `validate config`, `fleet run`, `fleet sweep` and the web fleet import (ζ).
  - The panel's `baseline` is consumed by `optimize configs` (γ).
  - The vocabulary guard is consumed by every entry-point edit's verify and by /review's briefing (θ).
  - No producer is orphaned. The registry holds no knob that no entry point offers, except SEG and degradation, which `sensitivity_panel` library callers use today (`apply_knob`'s tests).
- **G2:** every leaf names a user-observable signal through the CLI, the web API, the page or library behaviour through public names (§7). α is an intermediate with its own CLI signal. θ is the integration gate over §5.
- **G3:** verified at `dfcbde8`:
  - `SweepSpec`, `detect_sweep_spec` and `expand_sweep_configs` (config.py, moving with S5 γ);
  - `apply_knob`, `_apply_install`, `SENSITIVITY_BANDS`, `sensitivity_panel`, `run_sweep` and `RankedSweep.retained_cash_floor_gbp` (optimize.py);
  - `_SENSITIVITY_ALIAS_MAP` (cli/optimize.py);
  - `_SWEEP_PARAMETER_HOME_KEYS` and `simulate_sweep` (web/api.py);
  - `FLEET_COMPONENTS[...].fixed_range` (web/fleet_components.py: pv 0.5–20, battery 0–100, load 500–20,000);
  - `parse_home_config` and `with_default_days` (web/simulation_params.py);
  - `validate config`'s sweep arm through `parse_sweep_fleet_configs` (cli/validate.py);
  - `ScenarioConfig` equality (probed).

  Producers outside the batch are upstream: S5 γ, S6's leaves, 919, 921, 868, 870, 930, 885, 802, 803, 807, 835, 938, 739 and 440. None is downstream of a leaf that reads it.
- **G4:** each seam has one owner (§6). The S6 seams and 440 go to the lead (questions 1 and 3). S9's edit of the grid entry is ordered by 804 → β (question 5). There are no reciprocal claims: S9 says S26 hosts the knob and S9 owns its meaning, and §6 says the same.
- **G5:** B + H.
  - The blast radius is eight modules across four entry points, and 15 mechanisms.
  - S9 ε edits the seam later.
  - §4 is the contract, §5 the two-way test sketch, and θ the integration gate.
- **G6:** the premises were checked as follows.
  - RED today, probed:
    - C1's `log` mode 201 and the 200 kWh battery;
    - P2's `inf` points;
    - P6 and C5/C6's internal messages;
    - α's validate row ("got inf kWh");
    - C10's refused canonical name, by reading `_SENSITIVITY_ALIAS_MAP`.
  - Exactness holds as follows:
    - C2 holds because no swept field derives a stored value at construction (probed equal at nine points). The one stored derivation, the battery efficiency split, reads `efficiency`, not capacity.
    - C8's 6-of-8 is arithmetic on the unchanged call path: one baseline, floors 15 and 40, and grid 1.5, 12 and 48 (or S9 γ's band values). The floor-27 point is reused through equality, and the probe showed `ScenarioConfig ==` holds on copies of 100 homes.
  - The end-to-end capabilities lie in each leaf's dependency set:
    - η's knob path needs S6's reader upstream;
    - θ needs γ, δ, ε and η.
  - The rejection mechanisms are new and are each a RED test:
    - `SweepMode` coercion (α);
    - F7 (ζ);
    - `knob_named` (β);
    - the bound check (δ).
- **G7:** advisory, walked in §7.
- **META:** decomposing this without further oversight yields:
  - one registry of scenario knobs with one alias table, used by every entry point that varies a setting by name;
  - one value generator with one default and finite points;
  - a YAML grammar that refuses a misplaced sweep where it reads it;
  - a sensitivity panel that runs each distinct sweep once, with one floor setter;
  - a sweep page that restates nothing the server knows.

  Each property is guarded. The lead questions order work or assign a seam, and each has a default the PRD is written to.
