# Load composition: additional loads one mechanism, calendar-aligned days

**Status:** authored 2026-10-16 (program `review-all-solar_challenge-20261013`, stream S12, wave 2, upstream streams S10 and S19). Decomposed 2026-10-17 under L26: α 893, β 894 (held for S13), γ 895, δ 897, ε 899, ζ 901 (held for S29). S11 δ is 842, S21 δ is 832 and S21 α is 829. S13's hand-off leaf was not yet filed, so β waits on it. Tasks 711, 745, 725 and 726 were cancelled as superseded. Contract-first (B + H).

**Code anchors** verified against main `1fa8f79` (2026-10-16). Main moves fast: cite-by-symbol; re-locate lines at implementation time. Task 708's code is read from its branch `task/708` at `44eecaa` (not merged).

## Goal

A home's demand is the sum of named loads, each produced on the run's local calendar days. Every result, report and chart reads the loads by name instead of asking "is there a heat pump?".

What a user sees when this lands:

1. `solar-challenge home run --output out.csv` on a home with a heat pump and an EV writes `heat_pump_load_kw` and `ev_load_kw` columns. Today an EV's charging cannot be told apart from household demand in any result, report, chart or stored run.
2. `home run --report` prints a "Demand by load" table: Household, Heat pump, EV charging, each with its energy, share and peak. Their energies sum to Total Demand. The dashboard's results page for a heat-pump home shows a demand-by-load panel and the heat pump's profile, built from the same mapping.
3. A household's day looks the same whatever window contains it. On 2024-04-04 the deterministic profile peaks at 17:30 BST both when the window starts 2024-03-25 and when it starts 2024-04-03. Today the first window gives 18:30, because every day after a clock change is laid an hour late. A window ending 2024-03-31 ends at 23:59 BST, not 00:59 the next morning. A window ending 2024-10-27 ends at 23:59 GMT, not 22:59.
4. A calendar-year run delivers the configured annual consumption. `home run` over 2023 with `annual_consumption_kwh: 3400` reports Total Demand 3400.0 kWh, on both the deterministic and the seeded stochastic path; today it reports 3325.0. 2024 also gives 3400.0; today it gives 3336.2.
5. An EV's session starts at its arrival hour on the wall clock on both sides of a clock change. Today it starts at 19:00 BST instead of 18:00 after the spring change. A one-day run of an overnight off-peak EV charges that morning's session: 35.0 kWh, where today it charges 0.0. Over 2024-01-08..14 the same EV takes 7 × 35 = 245.0 kWh. A 3.6 kW EV needing 30 kWh takes exactly 30.0 kWh a day, not 30.06.
6. A `solar` EV charges in the run of its stay with the most PV generation from the home's own array (L11). Today it charges from the opening of a fixed 10:00–16:00 window, whatever the PV produces.

## Background

Findings (record `plans/review-all-solar_challenge-20261013.json`):

| key | severity / verdict | what it says | where it lands |
|---|---|---|---|
| fk-781d153ab978 | medium / confirmed | Heat pump and EV join demand by two mechanisms at two layers. The heat pump is composed in `home` and branched on in every layer above. The EV is merged inside `load.generate_load_profile` through a function-local import and leaves no trace. | γ, δ, ε, ζ |
| fk-1d920c89e872 | **high** / confirmed | Both load paths and the EV lay 1,440 positional minutes per day onto a tz-aware index and trim or pad at the end. Every day after a clock change is an hour off the wall clock. `base_load.add(ev_load, fill_value=0.0)` unions mismatched indexes. | α, β, γ |
| fk-740e9a804a4f | medium / confirmed | Smart-charging sessions run past departure. | task **708** (mechanical filing; on branch, unmerged). γ builds on it and does not carry the key. |
| fk-7fa120a8bb98 | low / confirmed | `EVConfig.charger_type` is a meaningful string parsed by `replace('kW', '')`, and the existing enums go unused. | γ (in-leaf), ζ (held annotation) |
| fk-89777ec9faad | medium / confirmed | The seasonal factors' day-weighted mean is 0.978, so a year of demand falls 2.2% short of the configured annual figure. | β (task 711 superseded, Q1) |
| fk-72af0b90338d | low / **weakened** | `_try_richardsonpy_profile` is one 166-line try block whose `except Exception` turns the project's own errors into a silent Elexon fallback. | β |
| fk-1609d8c3d091 | medium / confirmed | `simulate_home` does nine jobs. The additional-load axis has two mechanisms, and the TMY-year check is spelled twice. | δ |

Rulings that bind this PRD (program doc §Resolved decisions and §Lead rulings):

- **D4.** One coordinated surface bump. S12's derived clean option is that the three Optional heat-pump summary fields are replaced by the named-load mapping. The retirement is held leaf ζ.
- **D8.** The cadence is a run-owned parameter carried by `SimulationWindow`. The generators are built from the window, so they read its cadence and keep no `1440` or `freq='1min'` of their own.
- **D29.** Additive frozen-table edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line. Renames, retirements and type changes are held leaves released by S29.
- **D28.** fk-72af0b90338d is re-measured below.
- **L11.** S12 owns `solar` EV charging that follows the home's PV series (the solar half of fk-bd03fe349ffd). The EV contribution keeps receiving the home tariff (S11 δ).
- **L9.** No user-settable cadence option. `simulate_home` runs at `timebase.ONE_MINUTE`.

### Re-measurement at `1fa8f79`

- **fk-72af0b90338d (weakened; D28).** It reproduces. `_try_richardsonpy_profile` is 166 lines inside one `try` that ends `except Exception` → `return None`. That one block covers the richardsonpy imports, the data-file paths, the global seeding, date normalisation, occupancy, the day loop, the DST trim/pad copy and the seasonal scaling. Tests reach in four times. `tests/unit/test_load.py` monkeypatches `load._simulate_stochastic_day` once (S13's deletable). It patches richardsonpy's `run_application_simulation` three times to count calls, which pins third-party internals. β removes those three.
- **fk-1d920c89e872.** It reproduces (`probe:` deterministic `LoadConfig(3400, use_stochastic=False)`). On 2024-04-04 the profile's first maximum is at 18:30+01:00 for a window starting 2024-03-25 and at 17:30+01:00 for one starting 2024-04-03. The last row of a 2024-03-30..31 window is 2024-04-01 00:59+01:00. The last row of a 2024-10-26..27 window is 22:59+00:00. On `task/708` the EV generator still lays `len(date_range) * 1440` positional minutes from the first midnight, and its docstring says so.
- **fk-89777ec9faad.** It reproduces. 2023 Jan–Dec totals 3325.01 kWh on both paths (seed 42), and 2024 totals 3336.19. The day-weighted means of `SEASONAL_FACTORS` are 0.97795 for 2023 and 0.97855 for 2024.
- **fk-781d153ab978.** There are 9 result-side heat-pump presence branches today:
  - `home.py` 2: `_demand`, `calculate_summary`;
  - `output.py` 5: the report section, its seasonal block, and three in `aggregate_annual`, which S10 γ2 (780) deletes;
  - `web/charts.py` 1: `heat_pump_analysis`;
  - `results/home.html` 1.

  The remaining heat-pump branches are input-side and stay, because a component configuration is optional by nature (S5/S7 own that grammar): `config.py` 5, `scenario_writer.py` 1, the `simulate/home.html` toggle, and `home._hourly_weather`'s year check (moved into the heat-pump contribution, δ). The program's "18 branches across 7 files" therefore becomes "the 9 result-side branches", 3 of them via S10 γ2. EV: 0 mentions in `output.py`, `fleet.py`, `web/` and `cli/`.
- **fk-1609d8c3d091.** Task 710 has already shrunk `simulate_home` to a 24-line composition of private steps (`_hourly_weather`, `_demand`, `_dispatch_path`, `_minute_flows`, `_price_imports`, `_export_revenue`, `_results`). What remains is the two load mechanisms, the heat pump's alignment inside `home.py`, and the year rule spelled twice: `_YEAR_LENGTHS_IN_HOURS` in `home.py` and `_YEAR_LENGTHS_IN_MINUTES` in `heat_pump.py`, both from `heat_pump.reference_year_lengths`. δ moves all of it.
- **"Despite the name" disclaimers** (program deletable list): already gone. Task 757 renamed `scale_profile_to_annual` → `scale_profile_to_energy` and `calculate_annual_consumption` → `energy_kwh`.

## Sketch of approach

Three moves, each with one home.

**Calendar days come from the window (α).** `timebase.py` gains the day iterator over S10's `SimulationWindow`:

- `window.rows()` is the run's tz-aware index, from the first day's local midnight to the local midnight after the last day, at the window's cadence.
- `window.local_days()` yields one `LocalDay` per calendar date. Each holds that date's rows, 1,380, 1,440 or 1,500 on a one-minute Europe/London window, and answers two wall-clock questions: each row's local minute of day, and the first instant whose local clock reads a given time.

Every generator builds on these rows, so no generator counts minutes and no end trim exists.

**Generators place by wall clock (β, γ).**

- The household load places each day's minute-of-day profile, Elexon or richardsonpy, on that day's rows by local wall-clock minute.
  - A spring-forward day skips 01:00–01:59. A fall-back day plays it twice.
  - A deterministic day keeps its seasonal energy exactly.
  - The stochastic window is scaled once to the sum of its days' energies.
  - Seasonal weights are normalised over each day's own calendar year, so a calendar year sums to `annual_consumption_kwh`.
- The EV becomes one scheduler over rows.
  - Each stay runs from the arrival instant to the departure instant on the wall clock, from the day before the window (the morning carry-in) to its last day.
  - Each stay charges exactly `required_charge_kwh`: whole rows at charger power, then one fractional row.
  - The session is the contiguous run of the stay with the largest preference weight, earliest on a tie (708's rule). `none` weighs nothing. `off_peak` weighs the tariff's cheap minutes (S11 δ). `solar` weighs the home's PV generation (L11).
  - The EV leaves `load.generate_load_profile` and is composed beside the household load, so the function-local import and the index union go.

**Results carry named loads (δ, ε).**

- `demand.py` (new) owns `LoadKind` (household, heat pump, EV) and `compose_demand`, which builds every configured load on the window's rows and refuses one that is not on them.
- `SimulationResults.additional_loads` maps each non-household kind to its series.
- `loads` adds the household as demand minus the rest. A composition can never leave demand unattributed, and old stored runs need no migration: their `heat_pump_load_kw` column already has the heat pump's column name, and an old EV was always inside demand.
- `SummaryStatistics.load_energy_kwh` maps each kind to its energy.
- `calculate_summary`, the report, the chart panels and the routes iterate the mappings. No layer branches on a kind.

The held leaf ζ retires the old per-kind fields at the S29 bump and ships the stored-run step.

Heuristics served:

- 3: the additional-load axis has one mechanism, and calendar placement is one mechanism shared by the generators.
- 11 (SPOT): one day iterator, one TMY-year rule, one EV scheduler, one load vocabulary.
- 12: `LoadKind` and the EV enums replace meaningful strings and the `replace('kW', '')` parser.
- 10: exact-index and non-negative-household refusals at composition.
- 6 and 4: `simulate_home` orchestrates; `_try_richardsonpy_profile`'s single try becomes import, simulate, place and scale steps.
- 9: `demand.py` is a deep module with one function as its interface.

## Resolved design decisions

1. **The household is the residual, not a stored series.** `SimulationResults.loads[HOUSEHOLD]` is `demand − Σ additional_loads`, and `SimulationResults.__post_init__` refuses a residual below −1e-9 kW, naming the first such timestamp. Every kWh of demand is attributed to exactly one load by construction, so there is no sum invariant to police. Stored frames keep their columns: `heat_pump_load_kw` is already `LoadKind.HEAT_PUMP`'s column, and `ev_load_kw` is new and optional. A pre-S12 EV run's charging stays inside its household, which is the truth of what was stored. Consequence: S19's expected frame transform is not needed (cross-reference).
2. **A closed load vocabulary.** `LoadKind(StrEnum)` has HOUSEHOLD, HEAT_PUMP and EV. Each member's `column` (`<value>_load_kw`), `energy_column` (`<value>_load_kwh`), `label` and chart role (its value) derive from the member, so no reader keeps a per-kind table. A new load costs one member, one contribution in `compose_demand`, a `HomeConfig` field and its config block. No consumer changes. A second EV per home has no consumer and stays out (G1).
3. **Composition lives in `demand.py`, with explicit inputs.** `compose_demand(load, heat_pump, ev, inputs)` takes the three component configurations and one frozen `DemandInputs`:
   - the window;
   - the TMY year's hourly air temperature;
   - the PV's TMY-year minute generation;
   - the home tariff.

   It does not take `HomeConfig`, which would make `demand` import `home`, its importer. `home.py` loses `_Demand`, `_demand`, `_heat_pump_load` and `_YEAR_LENGTHS_IN_HOURS`.
4. **One TMY-year rule.** `heat_pump.reference_year_lengths` moves to `timebase.year_row_counts(rows_per_day)`. It is a calendar fact, and `timebase` is the time vocabulary's home. `weather.py` would pull pvlib into `heat_pump`. Two readers use it:
   - `demand.py`'s heat-pump contribution, which refuses a weather year of the wrong length, naming the hourly row count as `_hourly_weather` does today (S15 β's B4 keeps that message);
   - `heat_pump.generate_heat_pump_load`'s refusal of its own `annual_temperature_c`.
5. **Wall-clock placement, energy by day or by window.** A minute-of-day profile is placed on a day's rows by each row's local minute of day. A row's value is the mean of the profile over the wall-clock minutes the row spans, which is plain indexing at one minute.
   - Deterministic: each day is rescaled to its own energy `E_d`, so a 23- or 25-hour day keeps its seasonal share.
   - Stochastic: the whole window is scaled once to `Σ E_d`, keeping richardsonpy's day-to-day variation (today's rule, one helper).
6. **Seasonal weights per calendar year.** `E_d = annual × SEASONAL_FACTORS[month(d)] / Σ_{d' in year(d)} SEASONAL_FACTORS[month(d')]`. Any whole calendar year sums to `annual_consumption_kwh` exactly, in both 365- and 366-day years. `SEASONAL_FACTORS` (frozen) keeps its values. This is fk-89777ec9faad's proposal made concrete. "The simulated year" is read as each day's own calendar year, so a window across New Year is still exact per year.
7. **The iterator's precondition: the cadence divides one hour.** `rows()` and `local_days()` refuse any other cadence with `ValueError` naming it. That is the condition under which every local day, 23, 24 or 25 hours long, holds whole rows, and every row lies inside one wall-clock hour. S10's `SimulationWindow` invariants are untouched: S12 adds the iterator, not window rules (S10 contract).
8. **`simulate_home` builds its window first.** The window is the run's first and last local dates in the location's zone, `timebase.ONE_MINUTE` and the location's timezone. The run's index is `window.rows()`, and PV aligns to it through `align_tmy_to_index`, as today. This replaces S10 γ1's `of_index` derivation of the run's window from the load profile's index. `SimulationResults.window` (S10 α) still derives through `of_index`, and `of_index(window.rows()) == window` is pinned (B1).
9. **One EV scheduler over rows (γ).**
   - Stays run over local dates `first_day − 1 … last_day`. A stay starts at `day.instant(arrival_hour·60)` and ends at the departure day's `instant(departure_hour·60)`. The departure day is the next one when `departure_hour ≤ arrival_hour`.
   - Charge rows: `n = required / (power × step_hours)`. That is `⌊n⌋` whole rows (tolerance 1e-9 of a row) plus one row at the remaining fraction, capped at the stay's rows.
   - The session is the contiguous run of `⌈n⌉` stay rows whose weights sum highest, earliest on a tie. The fractional row comes last.
   - Weights by mode:
     - `none`: zeros, so the session starts at arrival;
     - `off_peak`: the tariff's cheap flags at each row's local minute of day (S11 δ's `cheap_minutes_of_day`);
     - `solar`: PV generation in kW on those rows.
   - The profile is the sum of the sessions on a widened window (`first_day − 1 … last_day + 1`), restricted to `window.rows()`.
   - Consequences:
     - No charging outside a stay.
     - A stay that fits delivers exactly `required_charge_kwh`.
     - The first morning holds the previous evening's session (task 725's option (a), the periodic steady state).
     - The rounding artefact of task 726 cannot arise.
     - DST shortens or lengthens a stay, and a stay too short for the charge charges all of it.
   - Solar follows generation, not surplus (L11 says "the home PV series"). Surplus-following would make one contribution read another; out of scope.
10. **EV enums at the boundary, in two steps (D29).**
    - In-leaf (γ): `EVConfig.__post_init__` parses `charger_type` and `smart_charging_mode` once into `EVChargerType` and `SmartChargingMode`. It refuses others with `ValueError` naming the field and the allowed values, and stores the member, which is a `str`, so the frozen annotation `str` stays true. `EVChargerType.power_kw` (3.6, 7.0, 22.0) replaces `_parse_charger_power`'s `replace('kW', '')`.
    - Held (ζ): the annotations become the enums, with `SmartChargingMode.NONE` as the default.
    - Because PyYAML refuses to represent a str-Enum (`probe:` `RepresenterError`), `scenario_writer._ev_block` writes `.value`. JSON writes the value already (`probe:`), so `web/storage` needs no change.
11. **Summary: energy per load, nothing derivable.** `SummaryStatistics.load_energy_kwh: Mapping[LoadKind, float]` holds each load's energy over the window. `load_share(kind)` derives the share. Peaks are read from `results.loads` by the report, the one reader that shows them, so the summary stores no peak.
    - `__post_init__` coerces keys to `LoadKind`, refusing an unknown kind by name. It refuses a value that is negative or not finite, and holds the mapping in `LoadKind` order as an immutable mapping.
    - The field defaults to `{}` until ζ, meaning "built before S12". `calculate_summary` always fills it.
    - The three heat-pump fields are still set until ζ. `__post_init__` refuses a `total_heat_pump_load_kwh` that differs from `load_energy_kwh[HEAT_PUMP]` when both are set: one reconciler for the transition.
12. **Transitional `heat_pump_load` (until ζ).** `SimulationResults.heat_pump_load` stays a constructor parameter but loses its column metadata. `__post_init__` makes it and `additional_loads[HEAT_PUMP]` one series: either may be given, and two that differ are refused. `to_dataframe` writes each load once, from the mapping.
13. **Consumers iterate.**
    - The report's "Demand by load" table is always present: one row per load in `LoadKind` order, with energy, share and peak. A plain home shows Household at 100%. The heat-pump seasonal block becomes a winter-versus-summer table per additional load.
    - Chart panels follow S21's emptiness rule. The demand-by-load panel applies when the run has an additional load, and each additional load gets a profile panel. Colours come from S21's token file by chart role, the kind's value. ε adds roles `household` and `ev`; `heat_pump` exists.
14. **Stored runs.**
    - γ and δ add only defaulted fields and an optional column, so no `RunDocumentStep` is needed (C10 covers renames, retirements and new required fields). Before ζ, a pre-S12 run loads with `load_energy_kwh == {}`, and its results page still draws the heat-pump panels from the frame.
    - ζ ships the step: a stored summary with no `load_energy_kwh` gains `{household: total_demand − hp, heat_pump: hp}` (hp omitted when null), and the three keys are dropped from `summary.json`, `runs.summary_json` and fleet home summaries alike.
15. **Fallback scope (fk-72af0b90338d).** The Elexon fallback stays (CLAUDE.md's defensive fallback). It fires only on richardsonpy's own failures: its import, its data-file load and its per-day simulation call. Windowing, placement and scaling run outside the `try`, so the project's own errors propagate. S13 owns the RNG context and the injectable per-day simulator. β splits the rest into import, simulate-per-day, place and scale steps.

## Contract (seams owned here: the day iterator, and the named load series)

```python
# src/solar_challenge/timebase.py  (α adds; SimulationWindow's fields and invariants are S10's)
MINUTES_PER_DAY: int = 24 * 60          # minutes on a 24-hour wall clock: the length of a minute-of-day profile
ONE_MINUTE: timedelta                   # timedelta(minutes=1): the cadence simulate_home runs at (L9: no option)

def year_row_counts(rows_per_day: int) -> range: ...   # (δ) rows in one calendar year: 365 to 366 days of rows_per_day

@dataclass(frozen=True)
class LocalDay:
    date: date                          # the local calendar date
    rows: pd.DatetimeIndex              # local midnight (incl.) to the next local midnight (excl.), at the window's cadence, in its zone
    def minute_of_day(self) -> np.ndarray: ...       # each row's local wall-clock minute, 0..1439 (fall-back repeats 60..119; spring-forward lacks them)
    def instant(self, minute_of_day: int) -> pd.Timestamp: ...  # first row whose local clock reads minute_of_day or later on this date

class SimulationWindow:                 # S10's frozen value
    def rows(self) -> pd.DatetimeIndex: ...          # concatenation of local_days()' rows; freq = cadence
    def local_days(self) -> Iterator[LocalDay]: ...   # one per date first_day..last_day, in order
    # both raise ValueError naming the cadence when it does not divide one hour

# src/solar_challenge/load.py  (β)
def generate_load_profile(config: LoadConfig, window: SimulationWindow, *, <S13's per-day simulator keyword>) -> pd.Series: ...
    # kW on window.rows(); no ev_config, no timezone (γ removes ev_config/tariff; β changes the positional part)

# src/solar_challenge/ev.py  (γ)
class EVChargerType(str, Enum):  ...; power_kw: float (property)
RowWeights = Callable[[pd.DatetimeIndex], np.ndarray]   # a preference weight per row
def generate_ev_charging_profile(config: EVConfig, window: SimulationWindow, *,
                                 tariff: TariffConfig | None = None,
                                 generation_kw: RowWeights | None = None) -> pd.Series: ...
    # kW on window.rows(); refuses off_peak without tariff (S11 δ's require_tariff_for_smart_charging)
    # and solar without generation_kw, each naming smart_charging_mode and the missing input

# src/solar_challenge/demand.py  (δ; new)
class LoadKind(StrEnum):
    HOUSEHOLD = "household"; HEAT_PUMP = "heat_pump"; EV = "ev"
    column: str          # f"{value}_load_kw"
    energy_column: str   # f"{value}_load_kwh"
    label: str           # "Household", "Heat pump", "EV charging"

@dataclass(frozen=True)
class DemandInputs:
    window: SimulationWindow
    hourly_temperature_c: pd.Series     # the TMY year's temp_air (heat pump)
    minute_generation_kw: pd.Series     # the PV's TMY-year generation at minute resolution (solar EV)
    tariff: TariffConfig | None         # the home's tariff (off_peak EV)

@dataclass(frozen=True)
class Demand:
    loads: Mapping[LoadKind, pd.Series]  # every configured load, kW on window.rows(), LoadKind order; HOUSEHOLD always
    @property
    def total_kw(self) -> pd.Series: ...
    def additional(self) -> Mapping[LoadKind, pd.Series]: ...   # without HOUSEHOLD

def compose_demand(load: LoadConfig, heat_pump: HeatPumpConfig | None, ev: EVConfig | None,
                   inputs: DemandInputs) -> Demand: ...
    # refuses a load whose index is not window.rows(), naming the load and the first differing row;
    # refuses (heat pump) a temperature year whose row count is not year_row_counts(24), naming the count

# src/solar_challenge/home.py  (δ)
class SimulationResults:   # existing fields unchanged; appended:
    additional_loads: Mapping[LoadKind, pd.Series] = <empty>   # each written under kind.column
    @property
    def loads(self) -> Mapping[LoadKind, pd.Series]: ...         # HOUSEHOLD = demand − Σ additional, then additional
    # __post_init__ refuses: HOUSEHOLD among additional_loads; a load whose index differs from demand's;
    # heat_pump_load and additional_loads[HEAT_PUMP] that differ; a residual household below −1e-9 kW (names the timestamp)
class SummaryStatistics:   # appended:
    load_energy_kwh: Mapping[LoadKind, float] = <empty>          # {} only for a summary built before S12 (required at ζ)
    def load_share(self, kind: LoadKind) -> float: ...           # energy / total_demand_kwh; 0.0 without demand
```

Invariants and where each is enforced:

| invariant | construction | use |
|---|---|---|
| A run's rows are its local calendar days, midnight to midnight. | `SimulationWindow.rows()` / `local_days()` (α) | every generator builds on them (β, γ); `compose_demand` refuses any other index (δ) |
| A day's household profile depends only on its date and config. | wall-clock placement + per-day energy (β) | B2's window-independence test |
| A calendar year of household demand is `annual_consumption_kwh`. | per-calendar-year seasonal weights (β) | B2; `validate_consumption` (S10 δ) annualises a window that is exactly one |
| An EV charges only while home and, per fitting stay, exactly its required energy. | the row scheduler (γ) | B4 |
| Demand is the sum of named loads, none negative. | `SimulationResults.__post_init__`: residual household ≥ −1e-9 (δ) | `loads`; summary; report; panels |
| A result names its loads from one vocabulary. | `LoadKind` (δ) | `to_dataframe`/`from_dataframe`, `load_energy_kwh`, report, panels, token roles |
| A heat pump shares its annual demand over one TMY year. | `timebase.year_row_counts` (δ) | `compose_demand`'s heat-pump contribution; `generate_heat_pump_load` |

Downstream readers and their seam lines:

- **S10** keeps `SimulationWindow`'s fields and rules. S12 adds `rows()`, `local_days()`, `LocalDay`, `MINUTES_PER_DAY`, `ONE_MINUTE` and `year_row_counts` to `timebase.py`.
- **S13** owns the global-RNG context and the injectable per-day simulator. β calls that simulator once per `LocalDay` and places its 1,440 values by wall clock. S12 takes none of S13's keys.
- **S19** owns the stored-run format. γ/δ need no step. ζ adds one `RunDocumentStep` (summary-only: no frame transform, decision 1).
- **S21** owns `ChartPanel`, the tab assembler and `theme-tokens.json`. ε adds builders returning `ChartPanel` and the chart roles `household` and `ev`.
- **S25** may read `load_energy_kwh` for per-load rows in its typed summary rows. No S12 leaf edits `cli/utils.py`.

## Boundary-test sketch (both sides of each seam)

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | Day iterator | Europe/London one-minute windows 2024-03-30..04-01 and 2024-10-26..28; a 30-minute window 2024-03-30..04-01; a 7-minute window | days hold 1440/1380/1440 and 1440/1500/1440 rows; the first `rows()` has 4,260 rows from 2024-03-30 00:00+00:00 to 2024-04-01 23:59+01:00 with `freq` one minute; `of_index(w.rows()) == w`; 2024-10-27's `minute_of_day()` holds 60 twice; `instant(90)` is 02:00+01:00 on 2024-03-31 and the first 01:30 on 2024-10-27; the 30-minute days hold 48/46/48 rows; the 7-minute window's `rows()` raises naming 7 minutes | α |
| B2 | Household placement and energy (producer) | `LoadConfig(3400, use_stochastic=False)`; `LoadConfig(3400, seed=42)` | the 2024-04-04 deterministic profile from windows starting 2024-03-25 and 2024-04-03 is equal (`Series.equals`), first maximum 17:30+01:00 (today 18:30 vs 17:30); a 2024-03-30..31 window's last row is 23:59+01:00 and a 2024-10-26..27 window's is 23:59+00:00; 2023 and 2024 full years total 3400 kWh to 1e-9 relative on both paths (today 3325.01 / 3336.19); the 2024-03-31 deterministic day's energy equals its seasonal `E_d` | β |
| B3 | Stochastic days on the wall clock | S13's injectable per-day simulator, faked to return day_of_year W at every minute; window 2024-04-03..05 | the fake is called once per local day (3 calls); every row of 2024-04-04 carries day 95's value before scaling, including 00:00–00:59 BST (today it carries day 94's there); an error raised inside the scaling step propagates instead of falling back | β |
| B4 | EV row scheduler | `EVConfig('7kW', 18, 7, 35, 'none')` over 2024-03-29..04-02; `EVConfig('7kW', 18, 8, 35, 'off_peak')` with `TariffConfig.economy_7()` over 2024-06-21..21 and 2024-01-08..14; `EVConfig('3.6kW', 8, 17, 30, 'none')` one day; `EVConfig('7kW', 18, 7, 35, 'off_peak')` with `economy_10()` over 2024-01-10..11 | each `none` session is 18:00–22:59 local, 2024-03-31 included (today 19:00 BST), EV index `== window.rows()`, total 175.0 kWh; the one-day off-peak run holds 00:30–05:29 and 35.0 kWh (today 0.0); the 7-day run 245.0 kWh; the 3.6 kW EV takes 500 rows and exactly 30.0 kWh (today 501 / 30.06); the E10 session on 11 Jan is 00:00–04:59 (S11 δ's row, unchanged); no charging row lies outside a stay | γ |
| B5 | Solar follows PV (L11) | `EVConfig('7kW', 8, 17, 21, 'solar')`, a 4 kWp Bristol home, 2024-06-21, the TMY in the test's cache | the EV's 180 charging rows are the 180-row run of the stay with the largest Σ `generation_kw` in the same results (today 10:00–12:59 whatever the PV); a solar EV without `generation_kw` raises naming `smart_charging_mode 'solar'` | γ |
| B6 | Composition (producer and consumer of `SimulationResults`) | a home with heat pump and EV over 2024-03-30..04-01 | `results.loads` keys are household, heat_pump, ev; their sum equals `demand` to 1e-9; every load's index is `window.rows()` (4,260 rows); `to_dataframe()` has `heat_pump_load_kw` and `ev_load_kw` and no household column; `from_dataframe(to_dataframe())` gives equal loads; `additional_loads={HOUSEHOLD: s}` raises naming household; an EV series 0.5 kW above demand at 2024-03-31 02:00+01:00 raises naming that timestamp; `heat_pump_load=s` alone equals `additional_loads[HEAT_PUMP]` | δ |
| B7 | Summary and storage | B6's results; `save_home_run` then `load_home_run`; a stored pre-S12 heat-pump run dir (summary without `load_energy_kwh`, frame with `heat_pump_load_kw`) | `load_energy_kwh` in `LoadKind` order summing to `total_demand_kwh` to 1e-9 relative; `load_share` of each; the round trip keeps the mapping with `LoadKind` keys; the pre-S12 run loads with `load_energy_kwh == {}` and `results.loads[HEAT_PUMP]` from its frame; `SummaryStatistics(load_energy_kwh={"boiler": 1.0}, ...)` raises naming `boiler` | δ |
| B8 | Consumers end to end (integration gate) | CliRunner `home run --report --output` on a scenario with heat pump and an `off_peak` EV on Economy 7 over 2024-03-30..04-01, offline with the cache seeded; the Flask client on a stored heat-pump home run and on a plain one | the report's "Demand by load" lists Household, Heat pump and EV charging, with energies summing to Total Demand to 0.1 kWh; the CSV has both columns on 4,260 rows; the heat-pump run's results page shows the demand-by-load panel (slices Household and Heat pump) and the heat-pump profile panel, and the plain run shows neither; no `heat_pump_load is` / `total_heat_pump_load_kwh` / `charts.heat_pump` remains in `output.py`, `web/` or `calculate_summary` | ε |
| B9 | Stored-run step (held) | a pre-S12 summary with `total_demand_kwh` 5400 and `total_heat_pump_load_kwh` 2400; one without a heat pump; a fleet run's home summaries | after `web migrate`: `load_energy_kwh` is {household: 3000, heat_pump: 2400} and {household: 5400}; the three keys are gone; the step is idempotent (C5); the frozen-surface test pins the forms without the retired names; `EVConfig(EVChargerType.FAST, 18)` type-checks under mypy strict | ζ |

## Pre-conditions for activating

Decomposition needs these filed ids from the lead (they are not yet filed):

- **S11 δ** ("EV off-peak charging reads the home tariff's cheap minutes"): γ depends on it. γ's off-peak weights are δ's `cheap_minutes_of_day` flags, and `require_tariff_for_smart_charging` is δ's.
- **S13's hand-off leaf** (RNG context + injectable per-day simulator on `generate_load_profile`): β depends on it. B3 drives the injected simulator.
- **S21 δ** (`ChartPanel`, `home_results_tabs`) and **S21 α** (`theme-tokens.json`): ε depends on both.

Filed upstream (G3 verified by `get_task`/`get_statuses` on 2026-10-16):

- **777** (S10 α, pending): `SimulationWindow`, `of_index`. α depends on it.
- **779** (S10 γ1, pending): `simulate_home` reads the window, and `load.energy_kwh` integrates through it. β depends on it, because β replaces its `of_index` derivation with the constructed window (decision 8).
- **780** (S10 γ2, pending): output's integrations read the window, and `aggregate_annual` is deleted with its 3 heat-pump branches. ε depends on it.
- **809** (S15 β, pending): `simulate_home` takes `weather: WeatherProvider`. γ and δ depend on it, since both restructure the same function and δ moves the year check it keeps.
- **775** (S1 γ, pending): `tests/unit/test_import_structure.py` with the `load → ev` Transitional entry. γ depends on it and deletes the entry.
- **822** (S19 κ, pending): `RunDocumentStep`, `RUN_DOCUMENT_STEPS`, the strict reader. ζ depends on it.
- **708** (pending, implemented on `task/708` at `44eecaa`): `_daily_session`, `_earliest_best_start`, `_PREFERRED_WINDOWS`. γ depends on it and generalises its flags to row weights.

G3 substrate checks (all PASS; details in the manifest):

- `pd.date_range` between consecutive local midnights gives 1,380/1,500 rows with `freq` set (`probe:`).
- `align_tmy_to_index` maps any index by UTC time of year (`grep:weather.py::align_tmy_to_index`).
- JSON writes a str-Enum as its value, and PyYAML's safe dumper refuses it (`probe:`).
- `generate_load_profile`, `generate_ev_charging_profile` and `simulate_home` are not in `__all__`, so their signatures change freely (`grep:__init__.py::__all__`).
- `SummaryStatistics` (in `__all__`), `home.SimulationResults` and `ev.EVConfig` are pinned by `FROZEN_SURFACE`/`FROZEN_CLOSURE`.

## Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S10 Window (`simulation-window-and-cadence.md`) | consumes | `SimulationWindow` fields; S12 adds `rows()`, `local_days()`, `LocalDay` in `timebase.py`; `simulate_home` constructs its window (replaces 779's `of_index` derivation of the run index) | S10 (window), S12 (iterator, generators) | α → 777; β → 779; ε → 780 |
| S11 Tariff (`tariff-coverage-classifier-presets.md`) | consumes | `TariffConfig.cheap_minutes_of_day`, `ev.require_tariff_for_smart_charging`, the `tariff` argument S11 δ threads to the EV; S12 γ moves the EV into composition keeping it, deletes `_PREFERRED_WINDOWS`' solar row (L11) | S11 (classifier, refusal), S12 (scheduler, solar) | γ → S11 δ (id from lead) |
| S13 RNG hand-off (unauthored) | consumes | the injectable per-day simulator and the RNG context around the richardsonpy run | S13 | β → S13's leaf (id from lead); S12 takes none of S13's keys |
| S19 Run store (`run-store-one-owner.md`) | consumes | `RunDocumentStep` for ζ's retirements; no frame transform (decision 1); reader decodes `Mapping[LoadKind, float]` (δ extends it if not) | S19 (mechanism), S12 (its step) | ζ → 822 |
| S21 Chart panels (`chart-panels-and-theme-tokens.md`) | consumes | `ChartPanel`, `home_results_tabs`, `theme-tokens.json` chart roles; S12 replaces `heat_pump_analysis` with per-load panels and adds roles `household`, `ev` | S21 (types, tokens), S12 (builders, two roles) | ε → S21 δ, α (ids from lead) |
| S1 Errors leaf (`errors-leaf.md`) | shrinks | `load → ev` Transitional allow-list entry | S1 guard, S12 edit | γ → 775 |
| S15 Weather (`weather-as-explicit-input.md`) | shares | `simulate_home(..., weather=)`; the heat-pump year check moves from `_hourly_weather` into the heat-pump contribution, same message | S15 (signature), S12 (the check's home) | γ, δ → 809 |
| S25 Board reports | may consume | `SummaryStatistics.load_energy_kwh` for per-load typed rows | S25 | cross-reference only |
| S29 Surface bump | consumes | held ζ: `heat_pump_load` and three summary fields retired, `load_energy_kwh` required, EV enum annotations | S29 releases ζ | ζ filed with `x_seam_wait` |
| S2, S3, S4, S7, S10 β/η, S16 | file overlap only | `home.py` (`HomeConfig.__post_init__`, dispatch routing, summary fields), `ev.py`/`heat_pump.py` validation (S4 β), `scenario_writer` key tables (S7), `fleet.py` (S16) | — | textual merges; no semantic seam |

## Decomposition plan

Labels are the sidecar's. Every leaf carries `x_finding_run = review-all-solar_challenge-20261013` and `source = review-all`, and its keys after the §8 step-1 lookup. Each leaf that changes a frozen form edits the surface tables and adds its "Unreleased on main" line in the same commit (D29). β and γ are high and join the trigger-chain gate 772.

- **α. Calendar-day iterator in `timebase`** (intermediate; priority high, key fk-1d920c89e872).
  - Files: `timebase.py`, `tests/unit/test_timebase.py`, `tests/unit/test_public_api_surface.py` (if 778 has pinned `SimulationWindow`'s members: add `rows`, `local_days`), `docs/domain-library-consumption.md`.
  - Work: the contract's `MINUTES_PER_DAY`, `ONE_MINUTE`, `LocalDay`, `rows()`, `local_days()` and the cadence refusal.
  - Signal: B1. `SimulationWindow(date(2024,3,30), date(2024,4,1), ONE_MINUTE, "Europe/London").rows()` has 4,260 rows ending 23:59+01:00. No such iterator exists today: the generators count `n_days * 1440`.
  - Unlocks β and γ. Prereq: 777.
- **β. Household load on calendar days, a calendar year exact** (leaf; priority high).
  - Keys: fk-1d920c89e872, fk-89777ec9faad (task 711 superseded, Q1), fk-72af0b90338d (D28 measurement above, recorded on the task).
  - Files: `load.py`, `home.py` (`simulate_home` builds its window per decision 8 and passes it), `tests/unit/test_load.py` (the three `run_application_simulation` counters become counts of S13's injected simulator), `tests/unit/test_home_demand.py`, `docs/domain-library-consumption.md` (every run spanning a clock change moves; demand +2.2%), `docs/finance-spreadsheet-reconciliation.md` (§4.1's calibration demand).
  - Work: decisions 5, 6 and 15. `generate_load_profile(config, window, ...)`. The positional loops, the end-of-window trim/pad blocks (×2), `end + Timedelta(days=1) − 1 min` (×2) and the second copy of the seasonal formula go.
  - Signal (CLI): `home run` with `--output` on a scenario with `load: {annual_consumption_kwh: 3400, use_stochastic: false}` writes 2024-04-04's `demand_kw` with its first maximum at 17:30+01:00, identical for `--start 2024-03-25` and `--start 2024-04-03`. Today the first gives 18:30. Over 2023-01-01..12-31 the table prints Total Demand 3400.0 kWh, also with `use_stochastic: true, seed: 42` (today 3325.0). B2, B3.
  - Prereqs: α, 779, S13's hand-off leaf.
- **γ. EV charging on calendar days, out of the household model, following the home's tariff and PV** (leaf; priority high).
  - Keys: fk-1d920c89e872, fk-7fa120a8bb98, fk-781d153ab978. fk-740e9a804a4f stays with 708, and the solar half of fk-bd03fe349ffd is S11's key, delivered here under L11.
  - Files: `ev.py`, `load.py` (`ev_config`, `tariff`, the `TYPE_CHECKING` and function-local `ev` imports and `add(fill_value=0.0)` go), `home.py` (`_demand` composes household + EV on the window's rows; PV is simulated before demand), `scenario_writer.py` (`_ev_block` writes `.value`), `tests/unit/test_ev.py`, `tests/unit/test_load.py`, `tests/unit/test_home_demand.py`, `tests/unit/test_scenario_writer.py`, `tests/integration/test_ev_fleet.py`, `tests/unit/test_import_structure.py` (the `load → ev` entry deleted), `docs/domain-library-consumption.md` (the first morning's carry-in, exact energy, DST, solar).
  - Work: decisions 9 and 10 (in-leaf half). The five `1440` literals, `_parse_charger_power`'s `replace('kW','')`, and `_PREFERRED_WINDOWS`' `SOLAR` row go.
  - Signal (CLI): `home run --output` on `example-economy7.yaml` with `use_stochastic: false` and a `home.ev:` block (`7kW`, arrival 18, departure 7, 35 kWh, `none`) over 2024-03-29..04-02. Its `demand_kw` minus the same file's without the `ev:` block is 7.0 kW from 18:00 to 22:59 local on every day, and 0 elsewhere. Today that difference starts at 19:00 BST from 2024-03-31. With `off_peak`, departure 8 and `--start 2024-06-21 --end 2024-06-21`, the difference holds 35.0 kWh at 00:30–05:29 (today 0.0). B4, B5.
  - Prereqs: α, β, 708, S11 δ, 775, 809.
- **δ. Named load series on results and summaries** (intermediate with its own CLI signal; priority medium).
  - Keys: fk-781d153ab978, fk-1609d8c3d091.
  - Files: `demand.py` (new), `home.py` (`_Demand`, `_demand`, `_heat_pump_load` and `_YEAR_LENGTHS_IN_HOURS` go; `SimulationResults.additional_loads`/`loads`; `SummaryStatistics.load_energy_kwh`/`load_share`; `calculate_summary` fills the mapping, plus the transitional heat-pump fields from it), `heat_pump.py` (`reference_year_lengths` → `timebase.year_row_counts`), `timebase.py`, `web/storage.py` or `web/stored_runs.py` (decode `Mapping[LoadKind, float]` if the reader on main does not), `tests/unit/test_demand.py` (new), `tests/unit/test_home.py`, `tests/unit/test_home_heat_pump.py`, `tests/unit/test_home_demand.py`, `tests/unit/test_web_storage_roundtrip.py`, `tests/unit/test_public_api_surface.py` (`SimulationResults` and `SummaryStatistics` forms gain the fields; `FROZEN_MEMBERS` gains `loads` and `load_share`; `LoadKind` joins the closure), `docs/domain-library-consumption.md`, `review/briefing.yaml` (the key-scenario line on EV and heat pump says the results carry each load by name).
  - Work: decisions 1–4, 11, 12 and 14.
  - Signal (CLI): `home run --output` on a heat-pump + EV home over 2024-03-30..04-01 writes `heat_pump_load_kw` and `ev_load_kw` on 4,260 rows. Today the CSV has no EV column, and the EV is inside `demand_kw`. B6, B7.
  - Unlocks ε, ζ. Prereqs: γ, 809.
- **ε. Reports and panels iterate the named loads (integration gate)** (leaf; priority medium; key fk-781d153ab978).
  - Files: `output.py` (the heat-pump section and seasonal block become "Demand by load" and per-load seasonal tables), `web/charts.py` (`heat_pump_analysis` and `HeatPumpCharts` → `load_panels(results) -> tuple[ChartPanel, ...]`), `web/routes.py` or the S21 assembler, `web/templates/results/home.html` (if the `charts.heat_pump` block survives S21 δ), `web/static/src/theme-tokens.json` (chart roles `household`, `ev`), `tests/unit/test_output.py`, `tests/unit/test_web_heat_pump_results.py`, `tests/unit/test_web_charts.py`, `tests/unit/test_web_chart_figures.py`, a CLI + Flask integration test for B8.
  - Work: decision 13.
  - Signal: B8 end to end. `home run --report` prints "Demand by load" with Household, Heat pump and EV charging summing to Total Demand. Today it prints a heat-pump section only, and nothing for an EV. The results page of a heat-pump run shows the demand-by-load panel, and a plain run's does not.
  - Prereqs: δ, 780, S21 δ, S21 α.
- **ζ. Retire the per-kind result fields and type the EV config at the bump (held: `x_seam_wait = {stream: S29, contract: "the surface bump release window"}`)** (leaf; priority medium; keys fk-781d153ab978, fk-7fa120a8bb98).
  - Files: `home.py`, `ev.py`, `web/stored_runs.py` (one `RunDocumentStep`, decision 14), `tests/fixtures/stored_runs/` (a pre-S12 heat-pump run), `tests/unit/test_public_api_surface.py`, the tests constructing `heat_pump_load=` or the three fields (re-grep: 13 test modules at `1fa8f79`), `docs/domain-library-consumption.md`.
  - Work:
    - `SimulationResults.heat_pump_load` and `SummaryStatistics.total_heat_pump_load_kwh`/`peak_heat_pump_load_kw`/`heat_pump_load_ratio` are retired;
    - `load_energy_kwh` becomes required (keyword-only or among the required fields: decide in ζ);
    - `EVConfig.charger_type: EVChargerType` and `smart_charging_mode: SmartChargingMode = SmartChargingMode.NONE`, still accepting the string values at construction.
  - Signal: B9. `web migrate` turns a pre-S12 heat-pump run's summary into `{household: 3000, heat_pump: 2400}` and its results page loads. `SummaryStatistics(..., total_heat_pump_load_kwh=1.0)` raises `TypeError`, and the surface test pins the new forms.
  - Prereqs: δ, ε, γ, 822. S29 releases it.

DAG: 777 → α → β → γ → δ → ε; δ → ζ (held); {779, S13} → β; {708, S11 δ, 775, 809} → γ; 809 → δ; {780, S21 δ, S21 α} → ε; {ε, γ, 822} → ζ. β and γ → gate 772.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`). The dark-factory trigger shapes were walked:

- `no-silent-fail-soft`:
  - The Elexon fallback is narrowed to richardsonpy's own failures and keeps its WARNING log (decision 15). **G7 waiver on β**: the fallback is CLAUDE.md's documented defensive policy, and recording the model on the results has no consumer.
  - The index union `add(fill_value=0.0)` is replaced by an exact-index refusal.
  - `load_energy_kwh == {}` for pre-S12 summaries is a distinct, bounded state: ζ fills it by step, with the S29 bump as its deadline.
- `one-fact-one-home`:
  - `heat_pump_load` and the three summary fields coexist with the mappings until ζ, with `__post_init__` as their reconciler.
  - The household is never stored beside demand (decision 1).
  - The TMY-year rule has one home.
- `exceptions-owned-or-ratified`: γ deletes an allow-list entry and adds none.
- `guards-exercise-behaviour`: each grep delivered check has a behaviour test in B1–B9.

## Out of scope

- PV at a non-minute cadence. `pv.interpolate_to_minute_resolution` (S14's file) builds the TMY year at one minute, and `align_tmy_to_index` places it on the window's rows, DST-correct today. Building PV at another cadence has no consumer (L9). S10's out-of-scope line assigned "generators at a chosen cadence" here: the household and EV generators read the window's cadence, and PV is left as it is.
- Solar EV following PV surplus instead of generation; a second EV per home; per-load figures in `FleetSummary`, the fleet results page or the CLI's default summary table (S25 may take the last).
- The global RNG, the injectable simulator and the fleet's per-home seeds (S13).
- Configuration grammar for components (S5/S7): the input-side presence branches stay.
- `TariffConfig`'s classifier and the off-peak refusal (S11).

## Open questions

For the lead:

1. **Pre-existing tasks on this stream's keys** (after §8 step 1 at decompose).
   - **Default:**
     - keep 708 (γ depends on it);
     - cancel 711 with `x_superseded_by` β, since β rewrites the very formula and needs the calendar-year rule of decision 6;
     - cancel 745 with `x_superseded_by` γ, since 745 changes `EVConfig`'s frozen field types in-leaf, against D29;
     - cancel 725 and 726 with `x_superseded_by` γ, since decision 9 delivers 725's option (a) and makes 726's rounding moot.
   - **Alternative:** keep 711 upstream of β with its rule amended to decision 6, so the +2.2% lands in wave 1.
2. **S19's expected frame transform.** Decision 1 removes the need: no stored column changes name. S19's PRD §8 row "S12 … extends `RunDocumentStep` with a frame transform" can drop that clause; ζ's step is summary-only.
3. **Order against S13.** The default puts β after S13's hand-off leaf. If S13's session shapes the injectable simulator differently from "a keyword-only parameter of `generate_load_profile` called per day", β follows S13's shape.

Tactical, decided in the leaf:

4. `rows()` computed per call or cached (`functools.cached_property` works on a frozen dataclass). Decide in α by timing a 527,040-row window.
5. How `LocalDay.instant` and the EV's carry-in day are built: from a widened `SimulationWindow`, or a private `LocalDay` constructor. Decide in γ.
6. `simulate_home` turns a tz-aware `start_date` in another zone into the location's local date (convert, then `.date()`). A naive one is read as local. Decide in β.
7. Whether the report's per-load seasonal table omits a load with no energy in a season. Decide in ε.
