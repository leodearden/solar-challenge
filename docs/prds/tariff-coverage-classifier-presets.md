# PRD — Tariff: coverage invariant, one cheap-period classifier, named preset rates (review-all stream S11)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S11** (wave 1, size M, risk medium). Findings record `plans/review-all-solar_challenge-20261013.json`, run `review-all-solar_challenge-20261013`.
- **Status:** authored 2026-10-14; amended at decompose 2026-10-16 for D34 (preset reference rates) and L11 (§12 Q2-Q5 defaults accepted); decomposed 2026-10-16 (task ids in §10).
- **Binding rulings:** D34 (`tariff.PRESET_RATES` carries the web's rates, 0.13/0.35 £/kWh; the library's preset defaults move to them and the board-facing scenarios re-price, §5.5), L11 (the solar half of fk-bd03fe349ffd goes to S12; an `off_peak` EV without a tariff is refused; both web forms default the TOU window to 16-19; the flat-tariff degenerates run), D7 (the tariff is the authority for peak and cheap: `TariffConfig` exposes the classifier and the tiling invariant, `peak_hours` is a checked override refused when it contradicts the tariff, EV windows and the web presets read the tariff), D29 (additive frozen-table edits land in-leaf with their `FROZEN_*` entry and an "Unreleased on main" line; renames and retirements are held leaves released by S29), D4 (one coordinated bump, no dual fields), D27 (invariant candidate 2 is promoted here as a test plus one briefing conventions line), D28 (weakened keys re-measured, §2.5). Lead rulings L5 (S11 raises `errors.ConfigurationError`, depends on S1-β), L6 (S11 owns the optional `peak_hours` override and the factory's tariff-clock arm), L7 (S11 adds the "has a cheap period" fact and the flat-tariff grid-charging refusal arm).
- **Approach:** **B + H**. The change crosses tariff, flow, dispatch, ev, load, home and the web layer, touches the frozen public surface, and feeds four later streams (S2 ε, S3, S18, S27). §5 is the contract, §9 the two-way boundary tests.
- **Code anchors** verified against main `9d7b67e7ba8091f1252ec067cea277f2b19be4d3` (2026-10-14). Of the files this PRD touches, only web files outside its scope changed since the findings' anchor `7dfea36e` (`git diff 7dfea36e..9d7b67e` over `tariff.py`, `flow.py`, `dispatch.py`, `ev.py`, `load.py`, `home.py`, `config.py`, `web/routes.py`, `web/fleet_scenario.py`, `simulate/home.html`, `fleet-simulator.js`, `scenarios/` is empty). Anchors are cited by symbol; re-locate lines at implementation time. **Re-walked at decompose against main `1fa8f796e87b608e6ee0ca9e8c62f377370203a7` (2026-10-16):** of those files only `dispatch.py`, `flow.py`, `home.py`, `load.py` and `tests/unit/test_public_api_surface.py` changed. `flow._is_cheap_period` and its two callers are unchanged. `dispatch.py` lost the "Seam note" comment (a73de35); the same rule is now a clause of `TOUOptimizedStrategy.decide_action`'s `grid_charge_ctx` docstring (§5.3). `home.simulate_home` is now a composition of private steps (task 710), so `generate_load_profile` is called from `home._demand` (§5.6). Task 708 is `pending` with its finished branch `task/708` at `44eecaa`.

Finding keys: fk-872021ade9b6 (medium, finance-economics), fk-2f88003e22c8 (medium), fk-97213a0e9ab2 (low, mechanical; task 748, §2.4), fk-bd03fe349ffd (medium, weakened), fk-463e82417506 (medium, web-dashboard), fk-4872e7ab367e (medium, weakened).

---

## 1. Goal

What a tariff charges is one schedule that covers each minute of the day exactly once, and "is it cheap now" is one question that schedule answers. Dispatch, grid charging and EV smart charging all ask it; none keeps its own clock. What "Economy 7" and "Economy 10" cost by default is stated once and the dashboard reads it.

**What a user observes when this lands:**

1. `solar-challenge validate config` on a scenario whose custom tariff leaves 23:00-07:00 uncovered, or covers 06:00-12:00 twice, or gives a rate of `.nan`, exits 1 with an ERROR row naming the gap, the overlap (and the two periods) or the rate. Today all three print "Configuration is valid"; the gap fails mid-simulation at the first uncovered minute and the overlap silently bills the first period's rate.
2. Two tariffs that charge the same rate at every minute dispatch the same. Today a night/day/peak/day tariff written as four periods grid-charges at the 0.20 day rate and the same schedule written as five periods does not: one January day of `bristol-arbitrage.yaml` imports 10.2 kWh (£1.67) against 4.8 kWh (£0.60). After S11 both report 4.8 kWh and £0.60.
3. A battery block can say `dispatch_strategy: {strategy_type: tou_optimized}` with no `peak_hours`: it discharges in the tariff's expensive minutes and grid-charges in its cheap ones, and on `bristol-arbitrage.yaml` it reproduces the home-level TOU route exactly (7.9 kWh, £1.34 on 2024-01-15). Today that block is refused ("requires 'peak_hours'").
4. A `peak_hours` window that falls in a cheap period of the home's tariff is refused naming the window, the overlapping clock time and the tariff (`[[7, 9]]` under Economy 7 names 07:00-07:30); a window inside the expensive hours (`[[16, 19]]`) is accepted as a narrowing. Grid charging on a tariff with no cheap period is refused naming `grid_charging`, the strategy and the tariff. Today both build and run.
5. "Economy 7" and "Economy 10" cost the same by default in the CLI, the library and the dashboard: 0.35 £/kWh peak and 0.13 £/kWh off-peak, the web's rates, stated once in `tariff.PRESET_RATES` (D34). Today the library charges 0.25/0.09 (Economy 7) and 0.27/0.08 (Economy 10) while both dashboard types use 0.35/0.13, so a default dashboard run and a CLI run of "Economy 7" are priced about 40 % apart. The dashboard keeps one rate pair per economy type, initialised from the table. Importing a fleet scenario whose economy tariff gives no rates fills the preset's rates instead of refusing. The three board-facing scenarios stop restating 0.09/0.25 and re-price: over 2024, `bristol-arbitrage.yaml`'s import cost goes from £204.43 to £292.48 and `example-economy7.yaml`'s from £247.22 to £344.07 (§2.1).
6. An EV in `off_peak` mode charges in the home tariff's cheap minutes: on Economy 10 its 300-minute session runs 00:00-04:59 at the 0.08 rate (today 00:30-05:29, 30 minutes at 0.27); on an Economy 7 configured 23:00-06:00 it starts at 23:00. A home with an `off_peak` EV and no tariff is refused naming `smart_charging_mode` and the missing tariff.

## 2. Background

### 2.1 What exists today (measured at `9d7b67e`)

- **`tariff.TariffConfig`** holds `periods: tuple[TariffPeriod, ...]` and `name`. `__post_init__` refuses an empty tuple and re-parses each period's times (which `TariffPeriod.__post_init__` already did). `get_rate` returns the first period whose `matches_time` is true and raises "No tariff period matches timestamp" otherwise. Nothing checks that periods cover the day or do not overlap (fk-872021ade9b6); `tests/unit/test_tariff.py::test_get_rate_no_match_raises` pins that a gap tariff constructs and fails at use.
- **`TariffPeriod`** has `start_time`/`end_time: str` ("HH:MM", parsed once into `cached_property` values kept out of `fields()` for `web/storage`), `rate_per_kwh` checked with `< 0` (admits NaN and inf). Its docstring says the times accept "HH:MM format or time object"; a `time` raises.
- **The cheap-period classifier** is `flow._is_cheap_period(tariff, rate)`: `rate < tariff.peak_rate and rate <= tariff.mean_period_rate`, where `mean_period_rate` counts "each period once whatever its length" (fk-2f88003e22c8). `flow._build_grid_charge_context` and `flow.simulate_timestep_tou` call it.
- **Four clocks for one axis** (fk-4872e7ab367e): the classifier above; `DispatchStrategyConfig.peak_hours` (whole hours, required for `tou_optimized`, read by `TOUOptimizedStrategy._get_tariff_period` for discharge while the grid-charge context's `is_cheap_period` gates grid charging, the two reconciled by a 9-line "Seam note" in `TOUOptimizedStrategy.decide_action`); `ev.generate_ev_charging_profile`'s literal 00:30-07:30 off-peak window (written twice) and 10:00-16:00 solar window (fk-bd03fe349ffd); and the preset classmethods' own window parameters.
- **Preset rates** (fk-463e82417506): `TariffConfig.economy_7` defaults 0.09/0.25, `economy_10` 0.08/0.27, both pinned in `FROZEN_MEMBERS` signatures. `scenarios/bristol-arbitrage.yaml`, `bristol-phase1-flex.yaml` and `example-economy7.yaml` restate 0.09/0.25 and 00:30/07:30 with comments restating them again. `simulate/home.html`'s Alpine state and `fleet-simulator.js` hold one pair, 0.35/0.13, for both economy types and always send it. `web/routes.simulate_home_page` and `simulate_fleet_page` pass `seg.SEG_PRESETS` to their templates and no tariff fact. `web/fleet_scenario._FORM_TARIFF_SETTINGS` reads an economy block's two rates with `_required`, so a rate-less block is refused on import.
- **Web dispatch defaults:** both forms default the TOU window to 16-21 and always send it.

Probes run for this PRD on `9d7b67e` (`uv run --locked --extra dev python -I`, and the CLI with the Bristol TMY in the weather cache):

| Probe | Today |
|---|---|
| `validate config` on custom tariffs: one period 07:00-23:00; 00:00-12:00 + 06:00-00:00; `flat_rate` with `rate_per_kwh: .nan` | all three: "Configuration is valid", exit 0. A negative rate already shows as an ERROR row ("Rate cannot be negative"), exit 1, so a constructor refusal reaches the ERROR table |
| night 0.10 (00-07) / day 0.20 (07-16) / peak 0.35 (16-19) / day 0.20 (19-24), as four periods and with the night split at 03:00 (five) | `mean_period_rate` 0.2125 vs 0.19; 10:00 cheap: True vs False; cheap minutes 1260 vs 420. Duration-weighted mean 0.1896 for both. `home run` on `bristol-arbitrage.yaml` with that tariff, 2024-01-10: Grid Import 10.2 vs 4.8 kWh, cost £1.67 vs £0.60, grid-charge cost £0.73 vs £0.20 |
| Economy 7, Economy 10, flat 0.25 | cheap minutes 420 / 600 / 0 under both the list mean and the duration-weighted mean |
| `TOUOptimizedStrategy([(16, 19)])` vs the classifier over 2024-01-10 | Economy 7: 840 minutes tariff-expensive but strategy off-peak, 0 cheap-but-peak; Economy 10: 660 and 0 |
| `TOUOptimizedStrategy` subclass whose period comes from the classifier, through `simulate_timestep(..., tariff=)`, vs `simulate_timestep_tou` | equal flows: `bristol-arbitrage.yaml` home over 2024-01-15 (import 7.904248 kWh, cost £1.336699, grid charge 2.124508 kWh, both routes); a synthetic two-day PV/demand profile, with and without `GridChargeConfig(0.9)` |
| `validate config` on `bristol-arbitrage.yaml` with the battery given `dispatch_strategy: {strategy_type: tou_optimized}` (home key removed); and with `peak_hours: [[7, 9]]` added | ERROR "tou_optimized strategy requires 'peak_hours' parameter"; "Configuration is valid" |
| EV 7 kW, 35 kWh, 18:00-07:00, `off_peak`, 2024-01-10..12 | 11 Jan session 00:30-05:29 (300 min); priced on Economy 10: 270 at 0.08, 30 at 0.27 |
| Task 708's scheduler (branch `task/708`) with each tariff's cheap minutes as the preferred mask | Economy 7 00:30-05:29 (unchanged); Economy 10 00:00-04:59; Economy 7 23:00-06:00 23:00-03:59; flat 18:00-22:59 (from arrival) |
| D34 re-price (decompose, main `1fa8f79`): `home run` over 2024 (CLI default window) of `bristol-arbitrage.yaml` and `example-economy7.yaml` as committed (Economy 7 restated at 0.09/0.25) and with the restated rates set to 0.13/0.35 | `bristol-arbitrage.yaml`: Grid Import 1822.7 kWh both; import cost £204.43 → £292.48; net cost £-162.88 → £-74.82. `example-economy7.yaml`: Grid Import 1130.8 → 1108.0 kWh; import cost and net cost £247.22 → £344.07. `bristol-phase1-flex.yaml` (the board fleet, full year) not run here: γ measures it |

### 2.2 The platform consumer

`solar-challenge-platform` pins `solar-challenge-v0.5.0`. At its current main it builds `TariffConfig`s from ORM rows of arbitrary TOU periods (`integrations/tariff_adapter.to_solar_challenge`), constructs `TOUOptimizedStrategy(peak_hours=..., off_peak_hours=...)` (the second parameter is already gone on main, task 326) from hours it derives from the tariff itself (`optimiser/planner._derive_tou_hours`: a clock hour is peak when any half-hour slot starts in a dearest-rate period), and reads neither `mean_period_rate` nor the classifier. Consequences: the tiling refusal reaches the platform at conversion (a ledger line, §5.8); the strategy's constructor must keep accepting `peak_hours` without a tariff, unchecked, as the platform passes the tariff only to `simulate_timestep`; and the platform's derived hours would be refused by the D7 check if it ever handed the strategy the tariff too (its "any slot" rule marks 07:00-08:00 peak under Economy 7, whose 07:00-07:30 is cheap), so the consumer recipe offers `TOUOptimizedStrategy(tariff=tariff)` in place of the derivation rather than alongside it.

### 2.3 Already-filed tasks this PRD meets

| Task | Status | Relation |
|---|---|---|
| 748 | in-progress (merge phase) | fk-97213a0e9ab2's mechanical fix: the time-cache test asserts through the public accessors. S11 files nothing for that key; α keeps 748's rewritten test green. If 748 is cancelled or fails, α absorbs it (§12 tactical 4). |
| 708 | pending (finished branch `task/708`, `44eecaa`) | Rewrites `ev.generate_ev_charging_profile` around `_PREFERRED_WINDOWS` (one row per mode, minutes of the day), `_preferred_minutes(mode)` and one session scheduler that never charges past departure. δ is built on it: off-peak's row is replaced by the tariff's cheap minutes. δ depends on 708. |
| 725, 726 | pending (after 708) | EV session at period start; charge-minute rounding. File overlap with δ only. |
| 230 | pending | Vectorised `TariffConfig.rates_for(index)`. α's minute-of-day table is the substrate it needs; edge 230 → α added at decompose (§12 tactical 5). |
| 183, 231 | deferred / pending | TOU PV-blindness and the perfect-forecast note. Unaffected: α changes no classification on a two-rate tariff (§5.2). |

### 2.4 fk-97213a0e9ab2

Its mechanical filing row resolved to task 748 (`filed:748`), now in its merge phase. Contract §8 step 1 is re-run at decompose; a `done` 748 with the patch gone closes the key.

### 2.5 D28 re-measure of the weakened keys

- **fk-bd03fe349ffd.** On main the window literals sit on 6 code lines (the skeptic's count, not the finding's 4), 0 of the 3 functions on the EV path take a tariff, and 30 of 300 minutes of the probed session are billed at Economy 10's peak rate: the core claim reproduces. Task 708 collapses the literals into one `_PREFERRED_WINDOWS` table; the tariff input is still absent there. The decomposing session records this on δ.
- **fk-4872e7ab367e.** 840 / 660 reproduce. The skeptic's corrections stand: 2 range validators plus 1 presence check (not 3 validators), and `scenarios/dispatch-comparison.yaml` has no tariff, so its `peak_hours: [[16, 19]]` contradicts nothing and no shipped file holds the battery while importing at the day rate. The axis is real (D7 binds it); the weight is the D28 weight. Recorded on β.

## 3. Rulings that bind, and how this PRD reads them

- **D7.** The tariff's classifier (§5.2) is the one definition of cheap. `peak_hours` stays as an override that narrows *when the battery discharges* to a subset of the tariff's expensive time; a peak minute that the tariff calls cheap is the contradiction D7 refuses (§5.3). With no tariff there is nothing to contradict, so `peak_hours` alone stays legal (`dispatch-comparison.yaml`).
- **D29 / D4.** α, β and γ make additive surface edits (new members, a widened constructor) in their own commits with their `FROZEN_*` entries and an "Unreleased on main" line each; ε, the one retirement (`mean_period_rate`), is held for S29. Behavioural tightenings (the tiling refusal, finite rates, the D7 and flat-tariff refusals) get "Unreleased on main" lines in the leaf that makes them, in the doc's existing "refuses input the 0.5.0 tag accepted" form.
- **L5, L6, L7.** α raises `errors.ConfigurationError` and depends on S1-β. β owns the optional `peak_hours`, the factory's tariff-clock arm and the flat-tariff refusal arm, after S2 α (the union and factory) and S2 β (the refusal arms it extends). S2 ε depends on β; S3 routes the home-level key through β's arm.
- **D27.** Invariant candidate 2 becomes `tests/unit/test_tariff_tiling.py` in α, plus one `review/briefing.yaml` conventions line.

## 4. Sketch of approach

1. **The tariff tiles the day and answers "cheap?" (α).** `TariffConfig` builds a minute-of-day table at construction, refusing a gap or an overlap by name; `get_rate` reads it. `TariffPeriod` refuses a non-finite rate. The classifier moves onto the tariff as `is_cheap_at(timestamp)` and `cheap_minutes_of_day`, comparing against the duration-weighted mean rate; `flow` reads it and `_is_cheap_period` goes.
2. **TOU dispatch runs on the tariff's clock (β).** `TOUOptimizedStrategy` takes the tariff; `peak_hours` becomes optional and, when given with a tariff, is checked against it. The factory passes the tariff; a grid-charging battery on a tariff with no cheap minute is refused.
3. **Preset rates in one table (γ).** `tariff.PRESET_RATES` holds each economy preset's default rates; the classmethods' defaults read it, the routes pass it to both simulate pages, the forms keep a pair per type, the fleet import fills from it, and the three scenarios stop restating it.
4. **EV off-peak reads the tariff (δ).** On task 708's scheduler, `off_peak`'s preferred minutes are the home tariff's cheap minutes, threaded from `simulate_home`; a home with an `off_peak` EV and no tariff is refused.
5. **Retire the list-mean at the bump (ε, held).** `TariffConfig.mean_period_rate` has no reader after α and is the statistic that made dispatch list-dependent.

## 5. Contract

### 5.1 `tariff.py`: tiling and finite rates (α)

```python
@dataclass(frozen=True)
class TariffPeriod:
    start_time: str          # "HH:MM", the local wall-clock minute the period starts
    end_time: str            # "HH:MM"; end <= start wraps midnight; end == start is the whole day
    rate_per_kwh: float      # 0 <= rate < inf, else ConfigurationError naming the rate
    name: str = ""

@dataclass(frozen=True)
class TariffConfig:
    periods: tuple[TariffPeriod, ...]
    name: str = ""
    # __post_init__: every minute of the local day 0..1439 is covered by exactly one period,
    # else ConfigurationError naming each gap and each overlap (with the periods that overlap)
    def get_rate(self, timestamp: pd.Timestamp) -> float        # frozen signature; reads the table, never raises
```

- **The table.** At construction `TariffConfig` computes, for each minute of the day, the periods covering it, from each period's parsed start and end (interval arithmetic on minutes, not 1,440 `matches_time` calls); the result is a private 1,440-entry period table (kept out of `fields()` as the parsed times are). A minute covered by none is a gap, by two or more an overlap. `get_rate(ts)` returns the table's period at `ts.hour * 60 + ts.minute`, the same answer `matches_time` gives on the local wall clock (boundaries are whole minutes, so seconds never matter) on any day, DST days included. The "No tariff period matches" branch and its hint go: no tiling tariff can reach it.
- **Refusal text.** One `ConfigurationError` per tariff listing every gap and overlap as `HH:MM-HH:MM` clock ranges, a range that crosses midnight written as one range (`23:00-07:00`, not `23:00-24:00, 00:00-07:00`), and each overlap followed by the periods covering it (`'Off-peak' 00:00-12:00`, `'Day' 06:00-00:00`). One formatter in `tariff.py`, `describe_minutes_of_day(minutes) -> str`, writes these ranges; β's contradiction message uses it too.
- **Errors.** `TariffPeriod` and `TariffConfig` raise `errors.ConfigurationError` (a `ValueError` per D2) for every refusal: the rate, a time that is not `HH:MM`, an empty period tuple, a gap, an overlap. `config._build_custom_tariff` adds nothing; the constructor's message names the periods by time and name (block paths are S5's reader work).
- `TariffPeriod`'s docstring states `HH:MM` only. S4 later swaps the rate's `0 <= rate < inf` idiom for its finite-number checker (invariant 1's fixture already lists `TariffPeriod`); the behaviour is S11's.

### 5.2 The cheap-period classifier (α)

```python
class TariffConfig:
    peak_rate: float                              # cached_property, unchanged (GridChargeContext reads it)
    cheap_minutes_of_day: frozenset[int]          # cached_property: minutes 0..1439 whose rate is cheap
    def is_cheap_at(self, timestamp: datetime) -> bool   # timestamp's local minute of day is in cheap_minutes_of_day
```

- **The rule.** A rate is cheap when it is below `peak_rate` and at or below the tariff's **duration-weighted** mean rate (the mean of the 1,440 per-minute rates). The mean is private to the classifier; it is a function of the schedule, so two tariffs whose `get_rate` agrees at every minute have equal `cheap_minutes_of_day`.
- **Identity on two-rate tariffs.** With two rates `lo < hi` covering `d_lo, d_hi > 0` minutes, the weighted mean lies strictly between them, as the list mean does, so `lo` is cheap and `hi` is not under both rules: every Economy 7, Economy 10 and two-rate custom tariff classifies exactly as today (measured: 420 / 600 / 0 minutes for E7 / E10 / flat). Only tariffs with three or more distinct rates can change, and they change to the schedule's answer.
- **No cheap minute.** A tariff whose minutes share one rate (any flat tariff) has `cheap_minutes_of_day == frozenset()`. That empty set is the "has a cheap period" fact L7 names; there is no separate flag.
- `is_cheap_at` takes a `datetime` because strategies receive `datetime` and flow passes `pd.Timestamp` (a subclass); both read the local wall clock, as `get_rate` does.
- **Readers.** `flow._build_grid_charge_context` sets `is_cheap_period=tariff.is_cheap_at(timestamp)`; `flow.simulate_timestep_tou` reads the same until S3 retires it. `flow._is_cheap_period` and its `mean_period_rate` comparison are deleted. `GridChargeContext.is_cheap_period` keeps its name and meaning (the platform annotates with it). β's strategy and δ's EV scheduler are the other readers.

### 5.3 TOU dispatch on the tariff clock; `peak_hours` as a checked override (β)

```python
class TOUOptimizedStrategy(DispatchStrategy):
    def __init__(
        self,
        peak_hours: list[tuple[int, int]] | None = None,
        *,
        tariff: TariffConfig | None = None,
    ) -> None

@dataclass(frozen=True)
class TOUOptimizedStrategyConfig:                     # S2 α's variant
    peak_hours: tuple[tuple[int, int], ...] | None = None   # None: the tariff's clock
    strategy_type: Literal["tou_optimized"] = field(default="tou_optimized", init=False)
```

- **Clock.** With `peak_hours` (validated by S2's `_require_valid_peak_hours`: non-empty, `0 <= start < end <= 24`), a minute is PEAK when its hour is in a window, as today. With `peak_hours=None`, a minute is OFF_PEAK exactly when `tariff.is_cheap_at(timestamp)`. `_get_tariff_period` and the `dispatch.TariffPeriod` enum stay; the branch logic of `decide_action` is unchanged.
- **Refusals, each a `ConfigurationError` raised by the constructor, so the factory, `HomeConfig` (through S2 β) and direct callers all get them:**
  - `peak_hours is None and tariff is None`: names `tou_optimized`, that without `peak_hours` it charges and discharges on the tariff's clock, and that there is no tariff.
  - `peak_hours` given with a tariff, and some minute of some window is in `tariff.cheap_minutes_of_day` (D7's contradiction): names the window as given, the overlapping clock range(s) through `describe_minutes_of_day`, the tariff's `name`, and that a peak hour is when the battery discharges so it cannot fall in a cheap period; it suggests removing `peak_hours` (the tariff's clock) or narrowing the window.
  - A window wholly inside the tariff's expensive minutes is accepted: it narrows discharge to those hours and holds the battery in the other expensive minutes (the platform's and the briefing's evening-peak use, `[[16, 19]]`).
  - `peak_hours` without a tariff is accepted unchecked (today's behaviour, the platform's shape, `dispatch-comparison.yaml`).
- **Agreement with the grid-charge context.** When the strategy was built with the step's tariff, no minute is both PEAK and cheap, so `decide_action` never discharges while `grid_charge_ctx.is_cheap_period` is true. The "Seam note" comment is already gone on main (a73de35). Its rule survives as a clause of `decide_action`'s `grid_charge_ctx` docstring: grid charging happens "inside `peak_hours` too", because whether a period is cheap is the caller's classification. β replaces that clause with the agreement sentence above. A strategy built with one tariff and stepped with another (`simulate_timestep(..., tariff=other)`) is a direct caller's choice; the factory builds both from the home's one tariff.
- **Parse and write.** The `battery.dispatch_strategy` reader (wherever S2 α / S5 leave it) reads an absent or null `peak_hours` as `None`; `scenario_writer` writes the variant's fields (`peak_hours: null` or omitted, tactical), and the S2 §5.6 storage rule round-trips both forms.

### 5.4 The factory arm and the flat-tariff refusal (β)

- `dispatch.build_dispatch_strategy`'s `TOUOptimizedStrategyConfig` arm returns `TOUOptimizedStrategy(None if c.peak_hours is None else list(c.peak_hours), tariff=tariff)`; the constructor's refusals propagate. The factory's signature (S2 §5.3) is unchanged.
- **Flat-tariff grid charging (L7).** Beside S2 β's two refusals, in the same place and through one function `_require_cheap_minutes_for_grid_charging(tag, grid_charging, tariff)`: when `grid_charging` is set, the variant grid-charges and `tariff is not None and not tariff.cheap_minutes_of_day`, raise naming `grid_charging`, the strategy tag and the tariff ("tariff '<name>' has no cheap period, so dispatch strategy '<tag>' never charges from the grid; remove grid_charging or use a time-of-use tariff"). S2 β's `HomeConfig.__post_init__` step for the home-level tariff-TOU route (`_runs_tariff_tou`) calls the same function until S3 routes that key through the factory.
- **Accepted on purpose:** `tou_optimized` on a flat tariff without grid charging. Every minute is expensive, so it discharges on shortfall and charges from PV, which is self-consumption; `flow.simulate_timestep_tou`'s docstring and `tests/unit/test_flow.py` already state and pin this, and both routes now agree on it (§6 decision 6, §12 Q5).
- **Web defaults.** Both forms' TOU window defaults move from 16-21 to 16-19, so every default form combination builds: 16-21 covers Economy 10's cheap 20:00-21:00 and would be refused.

### 5.5 Preset rates (γ)

```python
@dataclass(frozen=True)
class PresetRates:
    off_peak_rate: float      # £/kWh
    peak_rate: float          # £/kWh

#: Each preset's default rates: what a preset tariff block that sets none is charged at.
PRESET_RATES: Mapping[str, PresetRates]   # read-only; keys "economy_7", "economy_10"
```

- **The values (D34).** Both entries are `PresetRates(off_peak_rate=0.13, peak_rate=0.35)`, the web's pair. Today the dashboard sends that pair for both economy types, so it is the web's rate for each. The two entries stay separate rows, so a later price refresh can split them with a one-row edit.
- The one statement of the economy rates. `TariffConfig.economy_7`'s and `economy_10`'s rate defaults are read from it (`off_peak_rate: float = PRESET_RATES["economy_7"].off_peak_rate`). Their pinned signatures in `FROZEN_MEMBERS` therefore render 0.13/0.35 in place of 0.09/0.25 and 0.08/0.27. γ edits both pinned strings in its commit and adds an "Unreleased on main" line in the doc's "refuses input the 0.5.0 tag accepted" form: "a preset tariff built without rates is charged 0.13/0.35". Under D29 that is an in-leaf behavioural change: it is neither a rename nor a retirement. Keys are the scenario grammar's `type` values, the same strings `config._TARIFF_TYPES` and the forms' `<select>` use. Window defaults stay in the classmethod signatures, their one statement; no reader outside `tariff.py` needs them once δ lands.
- `web/routes.simulate_home_page` and `simulate_fleet_page` pass `tariff_preset_rates` (the table as `{type: {off_peak_rate, peak_rate}}`) as they pass `seg_presets`. `simulate/home.html`'s state and `fleetSimulator(...)` (given the table through `x-data`, as `scenarioBuilder(...)` is in `builder.html`) hold one rate pair per economy type, initialised from it; the rate inputs edit the selected type's pair, keep their labels and ids (the lane's e2e round-trip drives "Peak Rate (£/kWh)"), and the payload sends the selected type's pair. The 0.35/0.13 literals go.
- `web/fleet_scenario._FORM_TARIFF_SETTINGS`' economy readers fill an absent rate from `PRESET_RATES` instead of refusing; a present rate is read as today.
- The three scenarios drop their restated `off_peak_rate`, `peak_rate`, `off_peak_start`, `off_peak_end` and the comments that restate the numbers; their comment names the preset and its override keys. **They re-price (D34):** the windows equal the defaults, the rates do not. Every board figure that reads an Economy 7 import price moves: import cost, net cost, grid-charge cost and `bristol-phase1-flex.yaml`'s time-shift value, whose spread widens from 0.16 to 0.22 £/kWh. §2.1 gives the full-year measurements. γ re-measures the three files on its own base and records the before/after figures on its task and in its "Unreleased on main" line.
- Tests that pin the old defaults' numbers move to the table (`tests/unit/test_tariff.py::test_economy_7_default_rates`, `tests/unit/test_home_grid_charging.py`'s `peak_mask = rates > 0.09`, `tests/integration/test_flex_timeshift.py`'s 0.09/0.25 at 03:00/18:00, the two `FROZEN_MEMBERS` strings). γ counts the full set when it plans. A test that passes rates explicitly is unaffected.
- `PRESET_RATES` and `PresetRates` stay out of `__all__` (library-internal seam, like S2's decision 11). The flat-rate form default (0.28, and the builder's 0.245) is not a preset rate and stays (§11).

### 5.6 EV off-peak charging reads the tariff (δ)

- On task 708's `ev.py`: `_PREFERRED_WINDOWS` loses its `OFF_PEAK` row; `_preferred_minutes(mode, tariff)` returns, for `off_peak`, the flags of `tariff.cheap_minutes_of_day`; `solar` and `none` read the table as 708 leaves it. 708's single-session scheduler is unchanged: of all unbroken sessions inside the stay, the one covering the most preferred minutes, earliest on a tie.
- `generate_ev_charging_profile(config, start_date, end_date, timezone="Europe/London", *, tariff: TariffConfig | None = None)` and `load.generate_load_profile(..., ev_config=None, tariff: TariffConfig | None = None)` (passes it to the EV); `simulate_home`'s demand step, `home._demand` since task 710, passes `config.tariff_config`. Neither function is on the frozen surface.
- **Refusal:** `ev.require_tariff_for_smart_charging(ev_config, tariff)`, one function called by `generate_ev_charging_profile` and by `HomeConfig.__post_init__` (S2 β's): `smart_charging_mode == "off_peak"` with `tariff is None` raises `ConfigurationError` naming `smart_charging_mode 'off_peak'`, that it charges in the tariff's cheap periods, and that the home has no tariff.
- A tariff with no cheap minute leaves `off_peak` with no preferred minute, so it charges from arrival as `none` does (equal cost on a flat rate; §6 decision 6).
- **Where the home's tariff arrives late.** `web/fleet_scenario` generates homes without a tariff and gives them the form's tariff through `web/fleet_config.apply_fleet_overlay` (one `dataclasses.replace` carrying tariff, dispatch and SEG); `config.generate_homes_from_distribution` takes `fleet_tariff` at construction. S2 β's construction-time grid-charging check meets the same ordering; δ's EV check, and β's D7 and flat-tariff checks, run at the same point and inherit S2 β's handling of it. Measured: the web fleet form carries no EV block today, so δ's check meets the late-tariff path only through an imported fleet scenario with an `off_peak` EV distribution.
- The docstring's "Economy 7's 00:30-07:30" becomes "the tariff's cheap minutes".

### 5.7 Invariant 2 (promoted, D27)

`tests/unit/test_tariff_tiling.py`: `TariffConfig((TariffPeriod("07:00", "23:00", 0.3),))` raises `ConfigurationError` whose message contains `23:00-07:00`; periods `00:00-12:00 @0.10` and `06:00-00:00 @0.30` raise naming `06:00-12:00` and both periods; `TariffConfig.flat_rate(0.25)`, `FlatRateTariff(0.25)`, `economy_7()` and `economy_10()` construct; for each constructed tariff `get_rate` over the 1,440 minutes of 2024-01-10 Europe/London never raises and equals the first-match answer `matches_time` gives. Plus one `review/briefing.yaml` conventions line: "A TariffConfig's periods tile the local day exactly once; TariffConfig refuses a gap or overlap at construction, naming the clock times (tests/unit/test_tariff_tiling.py)".

### 5.8 Surface ledger for S29 (D4, D29)

| Leaf | Change | Consumer action |
|---|---|---|
| α | `TariffConfig` refuses periods that leave a minute of the day uncovered or cover one twice, and `TariffPeriod` a NaN or infinite rate, with `ConfigurationError` (a `ValueError`); `get_rate` no longer raises for an uncovered minute | Platform: `tariff_adapter.to_solar_challenge` now refuses a `Tariff` row whose periods do not tile at conversion, not at the first uncovered half-hour |
| α | `TariffConfig` gains `cheap_minutes_of_day` and `is_cheap_at(timestamp)`; cheap periods are classified against the duration-weighted mean rate, so dispatch changes only on tariffs with three or more distinct rates | none |
| β | `TOUOptimizedStrategy(peak_hours: list[tuple[int, int]] \| None = None, *, tariff: TariffConfig \| None = None)`; with a tariff and no `peak_hours` it runs on the tariff's cheap minutes; with both, a peak hour in a cheap minute is refused | Platform: may replace `planner._derive_tou_hours` with `TOUOptimizedStrategy(tariff=tariff)`; must not pass both its derived hours and the tariff (its "any slot" hours contradict Economy 7 at 07:00-07:30) |
| β | `TOUOptimizedStrategyConfig.peak_hours` is optional (`None` = the tariff's clock); building a home whose grid-charging battery's tariff has no cheap period is refused | Scenario files: may drop `peak_hours` under a TOU tariff |
| γ | `tariff.PRESET_RATES` (not in `__all__`) states the economy presets' default rates; `economy_7()` and `economy_10()` built without rates charge 0.13/0.35 £/kWh (was 0.09/0.25 and 0.08/0.27, D34); their signatures' defaults render the new values | Any consumer that builds a preset without rates and wants the old prices passes them explicitly; scenario files with a rate-less economy block re-price |
| δ | An `off_peak` EV charges in the tariff's cheap minutes; a home with an `off_peak` EV and no tariff is refused | Scenario files with an `off_peak` EV and no tariff: add the tariff |
| ε (held) | `TariffConfig.mean_period_rate` retired | none (unread by the platform) |

## 6. Resolved design decisions

1. **Tiling enforced at construction, through the table `get_rate` reads.** The check and the lookup are one structure, so the invariant is redundantly enforced (H10) and first-match semantics disappear rather than coexisting with a check. It also gives task 230 its vectorised lookup for free.
2. **Duration-weighted mean, not "any rate below peak" or "the minimum rate".** It keeps every two-rate tariff's classification identical (an identity, §5.2), so no shipped scenario or board figure moves, and it makes three-rate tariffs depend on the schedule only. The alternatives each change some three-rate tariff's behaviour for reasons this stream has no evidence for.
3. **The classifier's mean stays private; `mean_period_rate` is retired, not redefined.** A public weighted mean would be a second statistic beside the misleading one; redefining `mean_period_rate` would change a frozen member's meaning silently. Retiring it rides the bump (ε) per D4.
4. **"Contradicts" means a peak minute the tariff calls cheap, and nothing else.** A peak window narrower than the tariff's expensive time is the override's purpose (evening-peak discharge on a two-rate tariff, true-peak discharge on a three-rate one); refusing it would leave the override able only to restate the tariff. Discharging in a cheap minute is the one combination that contradicts the tariff's prices.
5. **The strategy holds the tariff.** `decide_action`'s signature is frozen and platform-implemented, so the clock cannot arrive per call; a frozen `TariffConfig` held by the strategy is configuration, not state. The constructor is the one place both the factory and direct callers pass through, so the D7 check lives there.
6. **Refuse what cannot be interpreted or yields a silently wrong outcome; accept the honest degenerate.** No clock (`tou_optimized` without `peak_hours` or tariff, `off_peak` EV without tariff) and grid charging that can never happen (flat tariff, L7) are refused. TOU and `off_peak` on a flat tariff are accepted: every minute costs the same, so self-consumption and arrival charging are the cost-equal outcomes, already documented for TOU.
7. **Preset table holds rates only.** Rates are the restated, disagreeing fact; windows have one statement (the signatures) and, after δ, no outside reader. Named `PRESET_RATES` rather than the program's provisional `PRESET_DEFAULTS` because it holds rates, not every default (§13 corrects invariant 11's text).
8. **The web's rates are the reference (D34, overruling this PRD's original default).** 0.13/0.35 £/kWh is closer to 2024 retail than the library's 0.09/0.25 and 0.08/0.27. The library defaults move to it. Every rate-less economy block re-prices, and so do the three board-facing scenarios once γ drops their restatements (§5.5, §2.1). Classification is unchanged: both presets stay two-rate, so their cheap minutes are 420 and 600 as before (§5.2).
9. **EV builds on task 708, not on a held S12 seam.** 708's per-minute preferred mask is exactly the interface the tariff's cheap minutes fill, so δ is small and lands in wave 1; the `generate_load_profile` hop it adds is the one S12 deletes when it moves the EV into `simulate_home`'s composition, keeping the `tariff` argument.
10. **Solar mode is not a tariff question.** D7 binds peak and cheap; "charge when the sun shines" needs the home's PV series beside the EV, which S12's composition provides (§11, §12 Q2).

## 7. Pre-conditions

- **S1-β** (`docs/prds/errors-leaf.md` leaf β: `ConfigurationError(ValueError)` in `solar_challenge/errors.py`) before α: `TariffPeriod`'s refusals switch from `ValueError`, compatible only once the base is `ValueError`.
- **S2 α** (`docs/prds/dispatch-configuration-below-config.md`: `dispatch.TOUOptimizedStrategyConfig`, the union, `build_dispatch_strategy`, `_require_valid_peak_hours`) and **S2 β** (the factory's refusal arms, `HomeConfig.__post_init__`, `_runs_tariff_tou`) before β.
- **Task 708** (in-progress) and **S2 β** before δ.
- **S29's bump window** for ε.

G3 substrate: every symbol §5 names as existing was read at `9d7b67e` (capability manifest); the cross-stream and in-flight substrates (S1-β, S2 α/β, task 708) are queued prerequisites.

## 8. Cross-PRD relationship

| Other stream / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S1 errors leaf | consumes | `errors.ConfigurationError(ValueError)` raised by `TariffPeriod`, `TariffConfig`, `TOUOptimizedStrategy`, the refusal arm, the EV check | S1 | α depends on S1-β (L5) |
| S2 dispatch configuration | both | S2 owns the union, `TOUOptimizedStrategyConfig`'s tag and the factory signature; S11 makes `peak_hours` optional, adds the tariff-clock arm and the flat refusal arm, and calls its check from S2 β's `HomeConfig` step for the tariff-TOU route | S2 type / S11 arm | β depends on S2 α, β; S2 ε depends on β |
| S3 one dispatch engine | produces for | the tariff-clock arm; measured: a tariff-clocked `TOUOptimizedStrategy` reproduces `simulate_timestep_tou`'s flows (§2.1, §9 row 6), so D6's retirement is a routing change | S11 arm / S3 routing | S3's routing leaf depends on β |
| S27 community | produces for | `build_dispatch_strategy(..., tariff=billing.tariff)` gets the arm and refusals | S2 factory / S11 arm | S27 depends on S2 α, β; no extra edge |
| S4 finite quantities | consumes | swaps `TariffPeriod`'s `0 <= rate < inf` for its checker; invariant 1's fixture walks `TariffPeriod` | S4 | S4 after α (file overlap) |
| S5 config partition | touches | `parse_tariff_config` and the dispatch reader move to `scenario_blocks.py`; β's reader edit follows the partition if S5 lands first; block paths on tariff refusals are S5's | S5 | order-insensitive |
| S12 load composition | both | δ threads `tariff` through `generate_load_profile`; S12 moves the EV into `simulate_home` keeping the argument; the solar half of fk-bd03fe349ffd proposed to S12 (§12 Q2) | S11 δ / S12 composition | S12's EV move after δ (file overlap) |
| S18 dashboard limits | produces for | `tariff.PRESET_RATES` (both presets 0.13/0.35, D34) is the table invariant 11 compares the forms with; γ's page test is its tariff half; the fleet form's tariff vocabulary and a tariff-clocked TOU option render from server tables | S11 table / S18 render | S18 after γ |
| S19 run store | touches | a stored run whose tariff does not tile no longer loads; S19's `StoredRunUnreadable` names it once it lands; a `TOUOptimizedStrategyConfig(peak_hours=None)` is part of the stored format | S19 format | none blocking (the web only stores tiling presets) |
| S23 surface lock | touches | α, β edit `FROZEN_MEMBERS` / `FROZEN_SURFACE` / `FROZEN_CLOSURE` in their commits | S23 tables | file overlap |
| S29 surface bump | produces for | §5.8 ledger; ε held | S29 | ε held |
| Task 708 | consumes | `_PREFERRED_WINDOWS`, `_preferred_minutes`, the single-session scheduler | 708 | δ depends on 708 |
| Task 748 | shares | fk-97213a0e9ab2's test rewrite; α keeps it green | 748 | in merge phase |
| Task 230 | produces for | α's minute table | 230 | edge 230 → α added at decompose |

## 9. Boundary-test sketch

| # | Scenario | Preconditions | Postconditions | Faces |
|---|---|---|---|---|
| 1 | Invariant 2 | §5.7 fixture | gap and overlap raise naming `23:00-07:00` / `06:00-12:00` and both periods; presets construct; 1,440-minute `get_rate` sweep never raises and equals first-match | tariff (producer) |
| 2 | Refusals reach the CLI | custom-tariff scenarios: gap, overlap, `.nan` rate, `.inf` rate | `validate config` exits 1, ERROR row naming the range or rate (today "Configuration is valid") | config, cli (consumer) |
| 3 | Classifier depends on the schedule only | the four- and five-period night/day/peak/day tariffs (§2.1) | equal `cheap_minutes_of_day` (420 minutes, 00:00-07:00); `simulate_timestep_tou` and `simulate_timestep` + context give equal flows over 2024-01-10 | tariff, flow |
| 4 | Two-rate identity | E7, E10, a custom two-rate tariff, flat 0.25 | cheap minutes are exactly the lower rate's (420, 600, its own, 0), equal to the pre-α classification | tariff, flow (regression) |
| 5 | Flow reads the tariff | E7 | `GridChargeContext.is_cheap_period == tariff.is_cheap_at(ts)` at every minute; `flow.py` holds no `_is_cheap_period` | flow |
| 6 | Tariff clock equals the tariff route | `bristol-arbitrage`-shaped home, synthetic weather over two days, with and without `GridChargeConfig(0.9)`: battery `TOUOptimizedStrategyConfig()` vs home-level `tou_optimized` | equal grid import, export, grid charge and discharge (measured equal today through a subclass probe) | dispatch, home, flow; S3's guard |
| 7 | D7 contradiction | E7: `[[7, 9]]`, `[[16, 19]]`; E10: `[[16, 21]]`, `[[16, 19]]`; no tariff: `[[16, 19]]` | `[[7, 9]]` refused naming `07:00-07:30` and the tariff; E10 `[[16, 21]]` refused naming `20:00-21:00`; the rest build; `dispatch-comparison.yaml` validates | dispatch (producer), home and validate (consumer) |
| 8 | No clock | battery `tou_optimized` without `peak_hours`, no tariff; `TOUOptimizedStrategy()` | both raise naming `tou_optimized` and the missing tariff | dispatch, home |
| 9 | Flat tariff + grid charging | flat 0.25 with `GridChargeConfig(0.9)`: battery `tou_optimized`, battery `peak_shaving`, home-level `tou_optimized` route | each refused naming `grid_charging`, the strategy and the tariff; on E7 each builds and grid-charges > 0 | dispatch, home |
| 10 | Override and context agree | `TOUOptimizedStrategy([(16, 19)], tariff=E10)` with grid charging, 1,440 minutes | no decision has `discharge_kw > 0` at a minute whose context is cheap | dispatch, flow |
| 11 | Variant round-trips | `TOUOptimizedStrategyConfig()` and with `peak_hours` | YAML parse → `scenario_writer` → parse equal; stored home run reloads equal | config, writer, storage |
| 12 | Preset rates reach the pages | Flask client | `x-data` of `/simulate/home` and `/simulate/fleet` holds `PRESET_RATES`' pairs per type; the home form's default Economy 7 payload runs with `tariff_rate` 0.13 at 03:00 and 0.35 at 18:00 | web (consumer), tariff (producer) |
| 13 | Rate-less economy import | fleet scenario `tariff: {type: economy_10}` | form state carries peak 0.35 / off-peak 0.13 (today refused "tariff.peak_rate must be set") | web/fleet_scenario |
| 14 | Scenarios stop restating | the three scenario files | no economy rate or window key; `validate config` OK; a one-day run's `tariff_rate` is 0.13 at 03:00 and 0.35 at 18:00, and its import cost equals the pre-γ file's with the restated rates set to 0.13/0.35 | scenarios |
| 15 | EV reads the tariff | EV 7 kW, 35 kWh, 18:00-07:00, `off_peak`, over 2024-01-10..12 | E7 00:30-05:29 (unchanged); E10 00:00-04:59 with 0 of 300 minutes at 0.27; E7 23:00-06:00 starts 23:00; flat from 18:00; no tariff refused at `HomeConfig` naming `smart_charging_mode` | ev, load, home |

## 10. Decomposition plan

Labels are this PRD's; ids are assigned at decompose. Every leaf carries `x_finding_key`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all`; priority is the highest severity among its keys. Each leaf that changes a frozen form edits the surface tables and adds its "Unreleased on main" line in the same commit (D29).

**α — TariffConfig tiles the day and owns the cheap-period classifier** (leaf; priority medium)
- Keys: fk-872021ade9b6, fk-2f88003e22c8.
- Work: §5.1, §5.2; flow's two call sites and the deletion of `_is_cheap_period`; `get_rate` from the table; invariant 2 as `tests/unit/test_tariff_tiling.py` (§9 row 1) and its briefing line; rewrite `test_get_rate_no_match_raises` to assert the construction-time refusal; §9 rows 2-5; `FROZEN_MEMBERS["TariffConfig"]` gains the two members; the "Unreleased on main" lines for §5.8's α rows. Keep task 748's test green.
- Files: `src/solar_challenge/{tariff,flow}.py`, `tests/unit/{test_tariff,test_tariff_tiling,test_flow,test_public_api_surface}.py`, `docs/domain-library-consumption.md`, `review/briefing.yaml`.
- Signal: `solar-challenge validate config` on a scenario whose custom tariff is the single period 07:00-23:00 exits 1 with an ERROR row containing `23:00-07:00`, on 00:00-12:00 + 06:00-00:00 one containing `06:00-12:00`, on `rate_per_kwh: .nan` one naming the rate (all three print "Configuration is valid" today); `solar-challenge home run` on `bristol-arbitrage.yaml` with the four-period night/day/peak/day tariff over 2024-01-10 reports Grid Import 4.8 kWh and Grid Import Cost £0.60, equal to the five-period split (today 10.2 kWh, £1.67).
- Prereqs: S1-β.

**β — TOU dispatch on the tariff clock; peak_hours a checked override; no grid charging without a cheap period** (leaf; priority medium)
- Keys: fk-4872e7ab367e.
- Work: §5.3, §5.4; `decide_action`'s `grid_charge_ctx` docstring clause (the former "Seam note") becomes the agreement sentence; the dispatch reader accepts an absent `peak_hours`; both forms' TOU window default 16-19; §9 rows 6-11 as `tests/unit/test_tou_tariff_clock.py` plus rows in S2 β's `tests/unit/test_grid_charge_refusals.py`; existing tests that build a TOU home whose window covers a cheap minute (e.g. `test_home_grid_charging.py`'s `peak_hours=[(7, 24)]` with Economy 7) move to the tariff clock or a valid window, counted when filed; `FROZEN_SURFACE["TOUOptimizedStrategy"]` and the variant's closure form; `review/briefing.yaml`'s grid-charging prerequisite line gains "and a tariff with a cheap period"; record the D28 re-measure (§2.5).
- Files: `src/solar_challenge/{dispatch,home,config}.py` (or `scenario_blocks.py` after S5), `src/solar_challenge/web/templates/simulate/home.html`, `src/solar_challenge/web/static/js/fleet-simulator.js`, `tests/unit/{test_tou_tariff_clock,test_grid_charge_refusals,test_home_grid_charging,test_public_api_surface}.py`, `tests/unit/dispatch/test_tou_optimized_strategy.py`, `docs/domain-library-consumption.md`, `review/briefing.yaml`.
- Signal: `solar-challenge validate config` on a copy of `bristol-arbitrage.yaml` whose battery block says `dispatch_strategy: {strategy_type: tou_optimized}` (home-level key removed) prints "Configuration is valid" (today ERROR "tou_optimized strategy requires 'peak_hours' parameter"), and `home run` on it over 2024-01-15 reports the same Grid Import and Grid Import Cost as the unmodified file on the same base (7.9 kWh and £1.34 at `9d7b67e`; the cost moves once γ re-prices the file under D34, the equality does not); the same copy with `peak_hours: [[7, 9]]` exits 1 naming `07:00-07:30` and the tariff (today valid); with the tariff replaced by `flat_rate` 0.25 it exits 1 naming `grid_charging`, `tou_optimized` and the tariff.
- Prereqs: α; S2 α; S2 β.

**γ — Economy preset rates in one table, read by the dashboard** (leaf; priority medium)
- Keys: fk-463e82417506.
- Work: §5.5 with D34's values (both presets 0.13/0.35); the two `FROZEN_MEMBERS` signature strings and the "Unreleased on main" line in `docs/domain-library-consumption.md`; the tests that pin the old defaults' numbers; §9 rows 12-14 (row 12 is invariant 11's tariff half, S18 extends it); re-measure the three board-facing scenarios before and after and record the figures on the task (§2.1 has full-2024 figures for two of them); rebuild `static/dist/style.css` if the template edits change Tailwind's output.
- Files: `src/solar_challenge/tariff.py`, `src/solar_challenge/web/{routes,fleet_scenario}.py`, `src/solar_challenge/web/templates/simulate/{home,fleet}.html`, `src/solar_challenge/web/templates/simulate/partials/tariff-config.html`, `src/solar_challenge/web/static/js/fleet-simulator.js`, `scenarios/{bristol-arbitrage,bristol-phase1-flex,example-economy7}.yaml`, `tests/unit/{test_web_tariff_presets,test_web_fleet_scenario,test_tariff,test_public_api_surface,test_home_grid_charging}.py`, `tests/integration/test_flex_timeshift.py`, `docs/domain-library-consumption.md`.
- Signal: on the dashboard, enabling the tariff and choosing Economy 7 or Economy 10 shows Peak 0.35 / Off-peak 0.13, and switching between them keeps each type's edits (today one shared pair, so an edit under one type shows under the other); `solar-challenge home run` on `example-economy7.yaml` over 2024, with the file's rate lines gone, reports the same Grid Import Cost as the pre-γ file with its restated rates set to 0.13/0.35 on the same base (at `1fa8f79`: £344.07, against £247.22 at the restated 0.09/0.25); `python -c "import solar_challenge as s; t = s.TariffConfig.economy_10(); print(t.peak_rate)"` prints 0.35 (today 0.27); importing a fleet scenario with `tariff: {type: economy_10}` fills 0.35 / 0.13 (today refused naming `tariff.peak_rate`); `git grep -nE 'peak_rate: 0\.|off_peak_rate: 0\.' scenarios` finds nothing.
- Prereqs: none.

**δ — EV off-peak charging reads the home tariff's cheap minutes** (leaf; priority medium)
- Keys: fk-bd03fe349ffd (off-peak half; §12 Q2 for the solar half).
- Work: §5.6; §9 row 15; EV tests that build `off_peak` profiles pass a tariff; record the D28 re-measure (§2.5).
- Files: `src/solar_challenge/{ev,load,home}.py`, `tests/unit/{test_ev,test_load}.py`, `tests/unit/test_home_ev_tariff.py`.
- Signal: `solar-challenge home run` on `example-economy7.yaml` with a `home.ev:` block (`charger_type: 7kW`, `arrival_hour: 18`, `departure_hour: 7`, `required_charge_kwh: 35`, `smart_charging_mode: off_peak`) and its tariff block replaced by `{type: economy_10}`, over 2024-01-10..11, writes a CSV whose `demand_kw` steps up by 7 kW from 00:00 to 04:59 on 11 Jan (today, and on task 708's scheduler, 00:30 to 05:29); `validate config` on the same file without a tariff block exits 1 naming `smart_charging_mode 'off_peak'` and the missing tariff (today valid).
- Prereqs: α; task 708; S2 β.

**ε — Retire TariffConfig.mean_period_rate at the bump** (held leaf; priority medium; `metadata.x_seam_wait = {stream: "S29", contract: "the surface bump release window"}`, excluded from this batch's `commit_planning`)
- Keys: fk-2f88003e22c8.
- Work: delete the member, its tests and its `FROZEN_MEMBERS` entry; S29's release section carries §5.8's ε row.
- Files: `src/solar_challenge/tariff.py`, `tests/unit/{test_tariff,test_public_api_surface}.py`.
- Signal: `python -c "import solar_challenge as s; s.TariffConfig.economy_7().mean_period_rate"` raises `AttributeError`, and the surface-lock test passes with the member gone.
- Prereqs: α; S29 releases it.

DAG: S1-β → α → {β (also S2 α, S2 β), δ (also task 708, S2 β), ε (held)}; γ independent. Intra-batch edges: β→α, δ→α, ε→α. Out-of-batch: α→S1-β; β→S2 α, S2 β; δ→708, S2 β. Downstream: S2 ε → β; S3's routing leaf → β; 230 → α; S4 γ → α (L16).

**Filed 2026-10-16** (an arrow reads "depends on"):

| Label | Task | Keys (severity) | Edges wired |
|---|---|---|---|
| α | 838 | fk-872021ade9b6, fk-2f88003e22c8 (medium) | α → 774 (S1-β); 230 → α |
| β | 839 | fk-4872e7ab367e (medium) | β → 838, 786 (S2 α), 787 (S2 β); 790 (S2 ε) → β |
| γ | 841 | fk-463e82417506 (medium) | none |
| δ | 842 | fk-bd03fe349ffd (medium; the off-peak half, the solar half is S12's per L11) | δ → 838, 787 (S2 β), 708 |
| ε (held) | 843 | fk-2f88003e22c8 (medium) | ε → 838; `x_seam_wait` {S29, the surface bump release window}; not committed |

fk-97213a0e9ab2 stays `filed:748` (§8 step 1 at decompose: 748 `in-progress`). No leaf is `high` or `critical`, so none joins gate 772.

G7 (advisory: this repo has no `docs/legibility/design-invariants.md`): screened against dark-factory's trigger shapes. α removes two silent fail-softs (an overlap billed first-match, a gap found mid-run) and β/δ/L7 refuse three ignored or uninterpretable settings (`no-silent-fail-soft`); α, β, γ, δ collapse four clocks and two rate tables into one each (`one-fact-one-home`, `no-lockstep-duplication`); γ's page test renders the real pages and compares with the live table (`guards-exercise-behaviour`). One note, not a hit: decision 6 accepts TOU and `off_peak` on a flat tariff as their cost-equal degenerate; `strategy_name` still reads `tou_optimized` there, as it does today (§12 Q5).

## 11. Out of scope

- **Solar-mode EV charging following the home's PV** (the solar half of fk-bd03fe349ffd): it needs the PV series beside the EV contribution, which S12's composition provides; `_PREFERRED_WINDOWS[solar]` stays as task 708 leaves it (§12 Q2).
- **A dashboard choice of "peak hours from the tariff"** for TOU: the forms keep sending a window, which β now checks against the form's tariff; offering the tariff clock in the home and fleet forms is S18's vocabulary work for the fleet form and a follow-up for the home form (§12 Q4).
- **The flat-rate form defaults** (0.28 in both simulate forms, 0.245 in the builder) and whether they should equal `FinanceConfig.retail_baseline_rate_pence_per_kwh`: not a preset rate; S18 (form defaults) or a follow-up.
- **A further price refresh of the preset rates**: D34 sets 0.13/0.35 for both presets. A later refresh, including one that splits Economy 10 from Economy 7, is a one-row edit to `PRESET_RATES`.
- **Negative rates, day-varying (Agile-style) and seasonal tariffs**: `TariffConfig` stays a non-negative daily schedule.
- **Block paths on tariff refusals** (S5), the finite-number checker's swap-in (S4), the vectorised `rates_for` (task 230).
- **Retiring `simulate_timestep_tou`** (S3, D6) and grid charging under every dispatcher (D3 mid-term, L8).

## 12. Open questions

### Lead-level (resolved 2026-10-16: Q1 by D34, which overruled the default; Q2-Q5 by L11, which accepted the defaults)

1. **Reference rates.** **Ruled (D34): the web's 0.13/0.35 for both presets; §5.5, §6 decision 8.** The original default: the library's 0.09/0.25 (Economy 7) and 0.08/0.27 (Economy 10) are the reference; the forms move to them. Consequence: a default dashboard run is priced lower than today; no CLI run, board scenario or test moves. The alternative (the web's 0.13/0.35, closer to 2024 retail prices) moves every rate-less economy block's runs and the three board-facing scenarios once their restatements go.
2. **Solar half of fk-bd03fe349ffd.** **Default:** reassigned to S12, whose `simulate_home` composition puts the PV series beside the EV contribution; S11 leaves 708's solar row. The program's deletable list then drops "the 10:00-16:00 literal" from S11. Alternative: S11 files a held leaf waiting on S12's composition contract. **Ruled (L11): default.**
3. **`off_peak` EV without a tariff.** **Default:** refused at construction (D7: nothing to read; consistent with `tou_optimized` without a clock). Alternative: fall back to `TariffConfig.economy_7().cheap_minutes_of_day`, keeping today's no-tariff schedule at the cost of a hidden default tariff. Measured blast radius: no shipped scenario and no web path builds such a home; `tests/unit/test_ev.py`'s off-peak classes do. **Ruled (L11): default.**
4. **Web TOU default window.** **Default:** 16-19 in both forms (every default tariff then builds; Economy 10 with 16-21 would be refused). Alternative: the forms send no `peak_hours` when a tariff is enabled (the tariff's clock, D7's default reading), a larger UI change that overlaps S18. **Ruled (L11): default.**
5. **Flat-tariff degenerates.** **Default:** accept `tou_optimized` (no grid charging) and an `off_peak` EV on a tariff with no cheap minute, as their cost-equal degenerate (decision 6). Alternative: refuse both like flat-tariff grid charging (L7), so a home never reports `tou_optimized` while behaving as self-consumption; this breaks `tests/unit/test_flow.py`'s pinned flat-tariff TOU cases. **Ruled (L11): default.**

### Tactical (decide in the leaf)

1. Exact refusal wording, within §5.1/§5.3/§5.4/§5.6's required names.
2. Whether the minute table holds periods or rates, and whether `describe_minutes_of_day` is public or a module-private name imported by `dispatch` (one formatter either way).
3. Whether `scenario_writer` writes `peak_hours: null` or omits the key for the tariff clock (both read back as `None`).
4. If task 748 is cancelled or fails before α, α absorbs fk-97213a0e9ab2's test rewrite (`metadata.x_supersedes_task = 748`).
5. Whether the decomposing session adds the edge 230 → α. **Done at decompose:** 230 depends on α (838).

## 13. Proposed cross-reference lines (for the lead to apply to other PRDs)

- S2: "S11 β makes `TOUOptimizedStrategyConfig.peak_hours` optional (`None` = the tariff's clock), adds the factory's tariff-clock arm and the flat-tariff grid-charging refusal (`_require_cheap_minutes_for_grid_charging`), which β's `HomeConfig` step for `_runs_tariff_tou` also calls; S2 ε depends on S11 β. S11 δ adds `ev.require_tariff_for_smart_charging` to the `HomeConfig.__post_init__` β creates. β's construction-time check must see the tariff a fleet overlay supplies after generation (`web/fleet_scenario` → `apply_fleet_overlay`); S11's checks run at the same point and rely on that handling."
- S3: "The tariff-clock arm is S11 β's; a tariff-clocked `TOUOptimizedStrategy` reproduces `simulate_timestep_tou`'s flows on `bristol-arbitrage.yaml` (S11 §2.1, §9 row 6), so retiring the inline path is a routing change; S3's routing leaf depends on S11 β."
- S4: "`TariffPeriod.rate_per_kwh`'s `0 <= rate < inf` (S11 α) is swapped for the finite-number checker; behaviour unchanged."
- S12: "When the EV moves out of `load.generate_load_profile` into `simulate_home`'s composition, the EV contribution keeps receiving the home's tariff (S11 δ). Proposed (S11 §12 Q2): S12 owns solar-mode EV charging following the home's PV series, taking the solar half of fk-bd03fe349ffd."
- S18: "Invariant 11 compares the forms with `tariff.PRESET_RATES` (not `PRESET_DEFAULTS`); S11 γ's `tests/unit/test_web_tariff_presets.py` is its tariff half and S18 adds the window half beside it. The fleet form's dispatch vocabulary includes a tariff-clocked `tou_optimized` (no peak window); `_FORM_TARIFF_SETTINGS` already fills absent economy rates from `PRESET_RATES` (S11 γ). Both presets' rates are 0.13/0.35 (D34)."
- S19: "A stored run whose tariff does not tile no longer loads after S11 α; the stored-run format covers `TOUOptimizedStrategyConfig(peak_hours=None)`."
- S29: "Release section and consumer recipe include S11 §5.8; S11 ε (`mean_period_rate` retired) is a held leaf released in the bump window; the recipe offers the platform `TOUOptimizedStrategy(tariff=tariff)` in place of `planner._derive_tou_hours`."
- Program row S11: "Deletable: drop 'the 10:00-16:00 literal' (solar half to S12, L11); add 'TariffConfig.mean_period_rate (held ε)'. fk-97213a0e9ab2 is task 748's."

## Gate record

- **G1 (consumers).** Tiling table and refusals: `validate config` / `home run`, the web's 400s, the platform's `tariff_adapter`. `is_cheap_at` / `cheap_minutes_of_day`: `flow` (α), `TOUOptimizedStrategy` (β), the EV scheduler (δ), then S3's routing and S27's community battery through the factory. `describe_minutes_of_day`: α's tiling refusal and β's D7 refusal. Optional `peak_hours` and the tariff-clock arm: the scenario battery block (`validate config`, `home run`), S2 ε's migrated scenarios, S3, S27, the platform recipe. `_require_cheap_minutes_for_grid_charging`: the factory and S2 β's `HomeConfig` step. `PRESET_RATES`: the classmethods, both simulate pages, the fleet import, S18's invariant 11. `require_tariff_for_smart_charging` and the EV `tariff` argument: `simulate_home`, `HomeConfig`, `validate config`.
- **G3 (substrate).** Read at `9d7b67e` (manifest); S1-β, S2 α, S2 β and task 708 are queued prerequisites; no novel syntax.
- **G4 (seams).** §8; both program seams (classifier, preset rates) owned here; the S2 meeting point follows L6/L7; the solar half and the invariant-11 name are proposed in §13.
- **G5.** B + H: §5 contract, §9 boundary tests (blast radius ≥ 3 modules, frozen surface, four downstream streams).
- **G6.** Numeric signals are measured on `9d7b67e` (§2.1) or follow from identities stated in §5.2 and the manifest; every rejection signal names a rejection absent today that its leaf builds and its test observes.
- **G7.** Advisory (no design-invariants list in this repo); §10.
- **META.** Yes, under D34 and L11 (§12): no design question is left to an implementer; §12's tactical items are local.
