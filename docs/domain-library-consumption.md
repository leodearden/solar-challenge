# Domain Library Consumption Guide

This document is the consumer-facing recipe for depending on the
`solar_challenge` domain library from a separate repository (e.g.
`solar-challenge-platform`) as a **git dependency pinned to a release tag**.

The authoritative public surface is `solar_challenge.__all__` (defined in
`src/solar_challenge/__init__.py`).
[Frozen public surface](#frozen-public-surface) names the tests that freeze it.

---

## Pinned dependency recipe

Add the following line to the consuming project's `pyproject.toml`
`[project]` `dependencies` list:

```toml
dependencies = [
  "solar-challenge @ git+https://github.com/leodearden/solar-challenge.git@<release-tag>",
]
```

The URL is this repository's public GitHub remote, so the pin resolves the same
way on any host that can reach GitHub — developer machines, CI runners and
container builds alike.  Do not substitute a `git+file://` URL: it resolves only
on a host that has a clone at that exact path.

**Worked example** (current release tag):

```toml
dependencies = [
  "solar-challenge @ git+https://github.com/leodearden/solar-challenge.git@solar-challenge-v0.5.0",
]
```

After editing, run `uv lock` and commit the updated `uv.lock` alongside the
`pyproject.toml` change.  The lockfile is the reproducibility contract — never
leave it uncommitted.

---

## Why pinned, not an editable path

An editable `pip install -e /path/to/solar-challenge` (or a `path =`
dependency) resolves against the **live main checkout** shared by all
worktrees.  Any `git merge` into `main` deploys the change underneath every
in-flight worktree immediately — no review step, no lockfile bump, no CI gate.

The tag pin **insulates** each consuming worktree:

- The resolved wheel is content-addressed at the tag SHA, not the tip of main.
- Breaking API changes on main cannot reach the consumer until a deliberate
  pin-bump PR is merged.
- Parallel worktrees running their own verify steps see the same pinned surface
  throughout, giving reproducible results.

---

## Upgrade workflow

1. Cut the new release tag in this repository and push it to `origin`
   (see [Tag / release convention](#tag--release-convention) below).
2. In the consuming project's `pyproject.toml`, change the release tag at the
   end of the [dependency line](#pinned-dependency-recipe) to
   `solar-challenge-vX.Y.Z`.
3. Run `uv lock` — this re-resolves the wheel from the new tag SHA, and fails
   if the tag is not on `origin`.
4. Commit both `pyproject.toml` and `uv.lock` together as a single reviewed
   platform commit with a message like:
   `chore(deps): bump solar-challenge to solar-challenge-vX.Y.Z`.
5. Open a PR; CI verifies the new surface before merge.

---

## Tag / release convention

Tags use the prefix `solar-challenge-` followed by a semantic version:

```
solar-challenge-v0.2.0   ← API freeze (first release tag)
solar-challenge-v0.3.0   ← next minor (additive surface changes)
solar-challenge-v0.4.0   ← basis-C cost-recovery + arbitrage
solar-challenge-v0.5.0   ← current release (CBS amount due: own-use VAT + collectable total)
solar-challenge-v1.0.0   ← first stable / breaking-change boundary (future)
```

**The first freeze tag** (`solar-challenge-v0.2.0`) IS the literal API freeze, i.e.
`solar_challenge.__all__` is considered stable from that point.

**A tag is a consumable release only once it is on `origin`.**  Consumers
resolve the pin from GitHub, never from a local clone, and `git push` does not
send tags by default, so push each release tag explicitly and confirm it arrived:

```bash
git push origin solar-challenge-vX.Y.Z
git ls-remote --tags origin solar-challenge-vX.Y.Z   # must print the tag
```

**v0.5.0 is additive for readers of `BillBreakdown`, but not for its
constructors.** The two new fields are **required** and have no defaults — a
defaulted `0.0` would silently invoice a zero amount due — so any code that
builds a `BillBreakdown` (typically test fixtures) must supply
`own_use_vat_gbp` and `cbs_amount_due_gbp` when it re-pins. `__post_init__`
additionally rejects a pair where `cbs_amount_due_gbp` is not the exact float
sum `own_use_payment_gbp + own_use_vat_gbp`, so derive the two rather than
hardcoding a rounded literal. Consumers that only read the dataclass —
including anything walking it with `dataclasses.fields()` — need no change.

**Changes merged since the last tag.** Each change merged to `main` since the
last tag that alters the frozen public surface, or what a public name returns,
is listed here as an **Unreleased on main** line, added by the commit that makes
the change. A change to what a finance-model name returns is listed instead in
the header of [cost-recovery-finance-model.md](cost-recovery-finance-model.md),
and the next release folds both lists into its notes. A change to an exported
signature, to the constructor of a class outside `__all__` that the frozen
surface names, to which of the dataclass parameters `eq`, `order`,
`unsafe_hash` and `frozen` either kind of class sets, or to either kind of
class's public members, must also edit `FROZEN_SURFACE`, `FROZEN_CLOSURE` or
`FROZEN_MEMBERS` in `tests/unit/test_public_api_surface.py`, which fails until
it does.

**Unreleased on main** (task 392): `SimulationResults`, reached through
`FleetResults.per_home_results`, gains two methods: `per_minute_amounts()`, a
frame of each minute's energy in kWh and money in £, one column per amount, and
`total_amounts()`, the run's total of each amount, keyed by column; the 0.5.0
tag has neither. Consumers need no change when they re-pin.

**Unreleased on main** (task 505): the frozen contract now covers the
constructors and public members of the eight classes outside `__all__` that the
frozen surface names, directly or through another such class:
`DispatchStrategyConfig`, `GridChargeConfig`, `OutputConfig` and
`SimulationPeriod` in `solar_challenge.config`, `EVConfig` in
`solar_challenge.ev`, `HeatPumpConfig` in `solar_challenge.heat_pump`, and
`HomeConfig` and `SimulationResults` in `solar_challenge.home`. Consumers still
import each from its module, as on the 0.5.0 tag, e.g.
`from solar_challenge.home import HomeConfig`, and need no change when they
re-pin.

**Unreleased on main** (task 567): the frozen contract now covers, for each
class it pins, whether it is a dataclass and which of the dataclass parameters
`eq`, `order`, `unsafe_hash` and `frozen` it sets. These decide whether its
instances compare equal field by field, support `<`, `<=`, `>` and `>=`, are
hashable, and refuse a field assignment with `dataclasses.FrozenInstanceError`.
All 34 pinned dataclasses set `eq`, and none sets `order` or `unsafe_hash`. All
are frozen except `SummaryStatistics`, `ScenarioConfig`, `FleetConfig`,
`FleetResults`, `EnergyFlowResult` and `CommunityResults`, and
`DispatchStrategyConfig`, `OutputConfig` and `SimulationPeriod` in
`solar_challenge.config`. Each sets the same parameters as on the 0.5.0 tag,
except `SimulationResults`, which task 436 froze (below). Consumers need no
change when they re-pin.

**Unreleased on main** (task 426): `Battery` declares `config`,
`min_soc_fraction`, `max_soc_fraction`, `charge_efficiency` and
`discharge_efficiency` in its class body, and `WeatherCache` declares
`cache_dir`, so the frozen contract now covers them. Each is still a plain
instance attribute that `__init__` sets, read and assigned as on the 0.5.0 tag.
Consumers need no change when they re-pin.

**Unreleased on main** (task 540): `Battery`'s `min_soc_fraction`,
`max_soc_fraction`, `charge_efficiency` and `discharge_efficiency` are settable
properties instead of plain instance attributes, still read and assigned as on
the 0.5.0 tag. An assignment is now checked against the bounds `Battery()`
checks for these four values: a value that breaks
`0 <= min_soc_fraction < max_soc_fraction <= 1`, an efficiency outside (0, 1],
or NaN for any of the four raises `ValueError` and leaves the battery
unchanged; the 0.5.0 tag accepts the assignment. As on the tag, a new SOC limit
is not checked against the current SOC and may move past it. Consumers that
assign values within these bounds need no change when they re-pin, and a
consumer's own check of these bounds before assigning can go.

**Unreleased on main** (task 580): a `Battery` whose SOC an assigned SOC limit
has moved past moves no energy further past it. While the SOC is below
`min_soc_kwh`, `discharge` returns 0.0 and leaves the SOC unchanged, and
`available_discharge_capacity_kwh` is 0.0; while it is above `max_soc_kwh`,
`charge` and `available_charge_capacity_kwh` do the same. On the 0.5.0 tag
these returned negative amounts: `discharge` raised the SOC to the floor and
`charge` lowered it to the ceiling. So a `simulate_timestep` or
`simulate_timestep_tou` step could report a negative battery discharge, with
self-consumption lowered and grid import raised by as much. It could also
report a negative battery charge, with grid export raised by as much, or grid
import lowered by as much for a charge from the grid. `validate_energy_balance`
accepted all of these. Charging up from below the floor, discharging down from
above the ceiling, and a battery whose SOC is within its limits behave as on
the tag. Consumers that move a SOC limit past the SOC, as a min-SOC register
write can, need no change when they re-pin, and any correction they make for
the negative amounts can go.

**Unreleased on main** (task 590): building an `EnergyFlowResult` with a flow
below 0, or NaN, raises `ValueError` naming each such flow and its value. Its
flows are `generation`, `demand`, `self_consumption`, `battery_charge`,
`battery_discharge`, `grid_export`, `grid_import` and `grid_charge`;
`battery_soc` is not checked. The 0.5.0 tag accepts such a result, and
`validate_energy_balance` passes it whenever the six flows its balance equation
reads balance, or one of them is NaN; it never reads `self_consumption` or
`grid_charge`. So `simulate_timestep` and `simulate_timestep_tou` raise
`ValueError` rather than return such a step. That covers a NaN `generation_kw`
or `demand_kw`, and a negative one given to `simulate_timestep_tou`, or to
`simulate_timestep` without a battery: the tag returns the step in each of
these cases. With a battery, `simulate_timestep`'s built-in dispatch strategies
refuse a negative power, as on the tag. Consumers that build results with flows
of 0 or more, and pass powers of 0 or more, need no change when they re-pin.

**Unreleased on main** (task 633): `Battery.charge` and `Battery.discharge`
raise `ValueError` before moving any energy, leaving the battery unchanged, for
a NaN `power_kw` and for a `duration_minutes` that is not positive and finite:
NaN, infinite, 0 or negative. The 0.5.0 tag refuses only a negative power. A
power of `inf` is still accepted, at the battery's maximum rate. On the tag, a
NaN power or duration returns NaN and makes the SOC NaN, where it stays through
every later call; a negative duration returns a negative amount and moves the
SOC the wrong way; an infinite duration fills or empties the battery, or makes
the SOC NaN at a power of 0; and a duration of 0 moves no energy. The message
for a negative power now ends in its unit, as in
`Charge power must be non-negative, got -1.0 kW`. `simulate_timestep` passes
its `timestep_minutes` to the battery, and its built-in dispatch strategies
refuse only a timestep of 0 or less, so with a NaN or infinite timestep a step
whose strategy charges or discharges now raises this `ValueError` with the SOC
unchanged; the tag returns that step, with the SOC NaN or the battery filled or
emptied. With a dispatch strategy of the consumer's own that does not refuse a
timestep of 0 or less, such a step raises the same `ValueError`, where the tag
returns it. While generation and demand are 0 or more, `simulate_timestep_tou`
passes the battery such a duration only with a negative power, which the battery
refuses as on the tag. Consumers that pass a power of 0 or more and a positive,
finite duration need no change when they re-pin.

**Unreleased on main** (task 436): `SimulationResults`, reached through
`FleetResults.per_home_results`, is frozen, so that each of its series stays
named the column `to_dataframe()` writes it under. Assigning to one of its
fields, such as `results.demand = series`, raises
`dataclasses.FrozenInstanceError`; the 0.5.0 tag accepts the assignment.
Consumers that assign to a results field build new results with
`dataclasses.replace(results, demand=series)` instead when they re-pin.
`hash(results)` still raises `TypeError`.

**Unreleased on main** (task 464): `WeatherCache.get`, and so `get_tmy_data` on
a cache hit, returns exactly the frame `WeatherCache.put` stored. Its floats
come back bit for bit; on the 0.5.0 tag the CSV reader left some values 1 ulp
off, so the run that filled a cache simulated from a TMY slightly different from
every later run's. Its index comes back in the timezone it was put in; on the
tag, a frame in a zone with daylight saving, such as `Europe/London`, came back
at a fixed UTC offset (`UTC+01:00` for a June day), and one spanning a clock
change raised `AttributeError`. Simulation reads a TMY by its UTC instants, so
the zone alone changes no result. `get` restores the zone from its `str`, which
`put` records, so `put` now raises `ValueError`, writing nothing, for a frame
indexed in a zone whose `str` names none, such as a `dateutil` zone (UTC
included) or `pytz.FixedOffset`; on the tag, `put` cached such a frame, and `get`
returned it at a fixed UTC offset, or raised `AttributeError` for a `dateutil`
zone across a clock change. Consumers that seed a cache with such a frame convert
its index first, e.g. with `tz_convert("Europe/London")`; other consumers need no
change when they re-pin. Any workaround for the fixed offset can go.

**Unreleased on main** (task 200): `TariffConfig` gains two read-only members,
`peak_rate`, its highest period rate, and `mean_period_rate`, the mean of its
period rates with each period counted once whatever its length, both in £/kWh;
the 0.5.0 tag has neither. Consumers need no change when they re-pin.

**Unreleased on main** (task 323): `BatteryConfig` gains the read-only property
`nominal_usable_capacity_kwh`, its usable capacity between the SOC limits before
SOH de-rating, in kWh; the 0.5.0 tag lacks it. Consumers need no change when
they re-pin.

**Unreleased on main** (task 466): `FleetResults` refuses input the 0.5.0 tag
accepts, and raises `ValueError`: an empty `per_home_results`, or a
`home_configs` that does not hold one `HomeConfig` for each entry of
`per_home_results`. The tag accepts both, and a fleet of no homes fails only
later, with a bare `IndexError` from `get_aggregate_series`, the `total_*`
properties and `to_aggregate_dataframe`. Those now raise the same `ValueError`
for a fleet whose lists were emptied or unpaired after construction. Consumers
that build a `FleetResults`, in a `simulate` they pass to
`solve_cost_recovery_rate` or in test fixtures, give it at least one home, and
one `HomeConfig` per home's results, when they re-pin.

**Unreleased on main** (task 240): `create_pv_system` and `simulate_pv_output`
no longer treat a battery inverter/charger as a candidate inverter, so they pick
a different inverter for 23 of the 992 census configs; the 0.5.0 tag may pick a
battery inverter/charger. Annual AC moves by +4.03% at 7.2 kW DC and +1.92% at
7.3 kW, and by +3.72% at 2.6 kW, all with the inverter unset; by +11% to +44%
for 0.3–1.0 kW arrays on 3.0, 3.68 and 5.0 kW inverters; and by −3.42% for
0.7–1.0 kW on 3.68 kW. The headline 3, 4, 5 and 6 kWp configs keep their picks
([pv-inverter-string-matching.md](pv-inverter-string-matching.md) §7). Consumers
re-baseline the figures for those configs when they re-pin.

**Unreleased on main** (task 236): `create_pv_system`, `create_model_chain` and
`simulate_pv_output` run every voltage-matched CEC inverter at
`PVConfig.inverter_efficiency` at rated output
(`Pdco = Paco / inverter_efficiency`), the default 0.96 included; the 0.5.0 tag
keeps the picked inverter's catalogue efficiency (0.892–0.983 across the
default-rated capacities) whenever `inverter_efficiency` is exactly 0.96. With
the system losses, on Bristol's scaled TMY, default-config annual AC moves by
−2.3% to +6.9% per capacity: 3 kWp +0.5%, 3.68 kWp +2.0%, 4 kWp −0.7%, 5 kWp
−1.1%, 6 kWp −1.3% ([pv-inverter-efficiency.md](pv-inverter-efficiency.md) §3).
The `PVSystem` that `create_pv_system` returns, which is also the `system` of
the model chain `create_model_chain` returns, names the picked CEC library row
in its `inverter` attribute, where the tag leaves `None`; custom and PVWatts
inverters still give `None`. Consumers re-baseline every figure that depends on
PV generation at the default efficiency when they re-pin.

**Unreleased on main** (tasks 384, 378, 332): `LoadConfig`, `BatteryConfig` and
`PVConfig` refuse input the 0.5.0 tag accepts, and raise `ValueError`.
`LoadConfig` refuses a `household_occupants` that is not a whole number or is a
bool (Python's or numpy's), and holds `3.0` as the int `3`; the tag accepts e.g.
`2.5`. All three refuse non-finite (`inf`/`NaN`) capacities, power limits,
consumption, ageing inputs and system age; the tag accepts e.g.
`capacity_kwh=float("inf")`. Consumers fix such inputs when they re-pin.

**Unreleased on main** (task 374): `FinanceConfig` refuses input the 0.5.0 tag
accepts, and raises `ConfigurationError`. It refuses NaN and ±inf for every
number: the tag accepts NaN and +inf for `standing_charge_pence_per_day`,
`retail_baseline_rate_pence_per_kwh`, `pv_cost_per_kwp_gbp`, `roof_fit_cost_gbp`,
`battery_cost_per_kwh_gbp`, `inverter_cost_per_kw_gbp`, `grant_gbp`, `loan_rate`,
`opex_per_home_per_year_gbp`, `own_use_rate_pence_per_kwh`,
`retained_cash_floor_per_home_per_year_gbp` and
`grid_services_income_per_kw_per_year_gbp`, and those messages now end
"must be > 0 and finite" or "must be >= 0 and finite". `loan_term_years` and
`asset_life_years` must be finite whole numbers: a bool (Python's or numpy's), a
NaN, an infinity or a fraction raises "must be a finite whole number", where the
tag accepts e.g. `20.5` and stores it; a whole-number float or numpy integer is
held as the plain int it equals. `parse_finance_config`, and so `load_scenarios`
and the finance CLIs, also refuse a YAML boolean, which the tag reads as 1.0
or 0.0, for any numeric scalar `finance` or `grid_services_events` key and for
an event window's `event_hours`, and a fractional year, which the tag truncates
with `int()`; an integer too large for a float, or an infinite count, is a
`ConfigurationError` where the tag raises a raw `OverflowError`. Consumers fix
such inputs when they re-pin, and any `except OverflowError` around
`parse_finance_config` can go.

**Unreleased on main** (task 318): `SimulationResults`, reached through
`FleetResults.per_home_results`, gains the classmethod
`from_dataframe(frame, *, strategy_name)`, the inverse of `to_dataframe()`.
`to_dataframe()` also gains a trailing `grid_charge_cost_gbp` column for
tariffed runs, so the CSV that `home run` writes and the web CSV export of home
runs carry one more column. Consumers that read the frame by position rather
than by name re-check it when they re-pin.

**Unreleased on main** (task 460): `simulate_fleet`, `simulate_fleet_iter` and
`simulate_multi_sweep_iter`, and so `solve_cost_recovery_rate`'s default
`simulate`, fetch each distinct home location's TMY once, in the calling
process, and pass it to their worker processes. So a `WeatherCache` installed
with `set_weather_cache` now serves a parallel fleet under every
multiprocessing start method. On the 0.5.0 tag, a worker started by
`forkserver` (Linux's default from Python 3.14) or `spawn` (macOS's default)
ignored that cache, read the working directory's `.cache/weather` and fetched
PVGIS on a miss: offline the run failed with `WeatherDataError`, and online it
simulated from PVGIS's live TMY instead of the injected one.

**Unreleased on main** (task 326): `TOUOptimizedStrategy` no longer accepts
`off_peak_hours`, and passing it raises `TypeError`; the 0.5.0 tag accepts it,
checks its hour ranges and otherwise ignores it. Consumers drop the argument
when they re-pin: it never changed a decision, because every hour outside
`peak_hours` is off-peak.

**Unreleased on main** (task 285): `get_tmy_data` multiplies the TMY's `ghi`,
`dni` and `dhi` by one factor, so that the year's GHI equals the mean annual GHI
of PVGIS's 2005–2020 hourly series for the point; the 0.5.0 tag returns PVGIS's
TMY unscaled. At Bristol, the TMY's annual GHI goes from 992.3 to 1069.5 kWh/m²
and the default 4 kW system's annual AC from 4328 to 4664 kWh (+7.8%); each
point has its own factor, from 0.936 (Glasgow) to 1.078 (Bristol) at the seven
UK points measured
([tmy-irradiation-scaling.md](tmy-irradiation-scaling.md) §4, §6). Temperature
and wind are unchanged. Fetching the TMY now also requests that hourly series,
and every weather cache entry written before the change is ignored
([Network I/O](#network-io)). Consumers re-baseline every figure that depends on
PV generation when they re-pin, bills and the cost-recovery rate included, and
rebuild any pre-built cache with `WeatherCache.put`.

**Unreleased on main** (task 252): `PVConfig` gains a last keyword,
`system_losses`, the fraction of each array's DC power lost before the
inverter. Its default is PVWatts v5's 14.08%
(`pvlib.pvsystem.pvwatts_losses() / 100`), and a value outside [0, 1) raises
`ValueError`. On the same weather, every PV output is lower than the 0.5.0
tag's. AC falls by about 14% where the inverter does not clip (Bristol's
default 4 kW on its scaled TMY: 4664 to 4004 kWh), and by less where it clips,
because the loss is taken before the inverter
([pv-system-losses.md](pv-system-losses.md)). `system_losses=0.0` gives the
output without system losses. Consumers re-baseline every figure that depends
on PV generation when they re-pin, bills and the cost-recovery rate included.

**Unreleased on main** (task 469): `SimulationResults`, reached through
`FleetResults.per_home_results`, gains a last field, `grid_charge`, defaulting
to `None`: the power the battery stores from the grid, in kW, a part of both
`battery_charge` and `grid_import`. `simulate_home` sets it for tariffed runs,
as it does `grid_charge_cost`. `to_dataframe()` gains a trailing
`grid_charge_kw` column for those runs, so the CSV that `home run` writes and
the web CSV export of tariffed home runs carry one more column, and
`per_minute_amounts()` and `total_amounts()` gain `grid_charge_kwh`.
`SummaryStatistics` gains a last keyword, `total_grid_charge_kwh`, defaulting
to `0.0`: the run's energy stored in the battery from the grid, in kWh, a part
of both `total_battery_charge_kwh` and `total_grid_import_kwh`. Building one
raises `ValueError` unless `total_grid_charge_kwh` is at least 0 and at most
each of those two totals, so it also refuses a negative or NaN battery charge
or grid import total, which the 0.5.0 tag accepts. Code that builds one with a
battery charge and a grid import of 0 or more needs no change, and a summary
the web app stored before the field existed loads with it at `0.0`. The 0.5.0
tag has none of these. Consumers that read the frame by position rather than by
name re-check it when they re-pin.

**Unreleased on main** (task 773): `ConfigurationError` is defined in
`solar_challenge.errors`, which imports no other module of the package; import
it as `from solar_challenge.errors import ConfigurationError`.
`solar_challenge.config` still binds the name at runtime, so code that imports
it from there keeps running, but config no longer exports it, so `mypy --strict`
refuses that import ("does not explicitly export attribute"). Constructing a
`FinanceConfig`, a `GridServicesEventsConfig` or an `EventWindow`, valid or
refused, no longer imports the scenario grammar (`solar_challenge.config`) or
pvlib; on the 0.5.0 tag, constructing a `FinanceConfig` or a
`GridServicesEventsConfig`, or a refused `EventWindow`, imports both. The
class's base, `Exception`, and every refusal message are unchanged. Consumers
that import it from `solar_challenge.config` switch to `solar_challenge.errors`
when they re-pin.

**Unreleased on main** (task 777): `SimulationResults`, reached through
`FleetResults.per_home_results`, gains a read-only property, `window`: the
`SimulationWindow`, imported from `solar_challenge.timebase`, that its index
describes: the first and last calendar dates it covers on the index's own
clock, the cadence its rows are spaced at, and that clock's zone name.
`per_minute_amounts()` and `total_amounts()` multiply each kW series by
`window.step_hours`, the cadence in hours, where the 0.5.0 tag multiplies by
1/60 whatever the spacing: a row of half-hourly results, such as
`from_dataframe` builds from a half-hourly frame, now counts as half an hour's
kWh, where the tag counts it as one minute's. Both now raise `ValueError` for
results whose index no window describes: an empty index, one row without a
fixed-duration `freq` (a daily `freq` is never one, on any pandas release: a
zoned day lasts 23 or 25 hours across a clock change), unevenly spaced rows
(naming the first position whose gap differs and both gaps), or an index that
is not a `DatetimeIndex` (naming its type and dtype); the tag returns amounts
for each. The frozen contract now
also covers `SimulationWindow`, a frozen dataclass that sets `eq`: its
constructor and public members. Every `simulate_home` run, and every run the
web app stores, is spaced one minute apart, so its amounts are unchanged;
consumers that build results at another spacing re-check their totals when they
re-pin.

Bumping the pin in a consuming project is a **deliberate, reviewed consumer
commit** (not an automatic update).  The tag convention makes the intent of
each bump self-documenting in git history.

---

## Consumption caveats

### Cheap top-level import

```python
import solar_challenge          # fast — no pvlib, no network I/O
```

`import solar_challenge` executes the `__init__` module only, which is
pvlib-free.  The frozen `__all__` and the PEP-562 `__getattr__` lazy loader
are registered, but no submodule is imported until a public name is accessed.

### Lazy pvlib dependency

Accessing any name from `pv` or `weather` triggers `importlib.import_module`
for that submodule, which pulls `pvlib` transitively:

```python
sc = solar_challenge
mc = sc.create_model_chain(...)    # ← first access imports pv.py + pvlib
tmy = sc.get_tmy_data(...)         # ← first access imports weather.py + pvlib
```

Consumers that want to avoid the pvlib cost must not touch these symbols.

### Network I/O

On a cache miss, `weather.get_tmy_data` makes **two outbound HTTPS requests to the
PVGIS API**: the TMY, and the 2005–2020 hourly series whose mean annual GHI it scales
the TMY to (see [tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)).
In test environments and CI, consumers **must inject a mock or a pre-cached
`WeatherCache`** rather than calling `get_tmy_data` directly:

```python
import solar_challenge

# Inject a pre-built cache instead of hitting the network
solar_challenge.set_weather_cache(my_test_cache)
```

The fleet simulators in `solar_challenge.fleet` read weather through the installed
cache in the calling process and hand it to their worker processes, so an injected
cache serves a parallel fleet whatever the multiprocessing start method.

A cache directory written before that scaling is ignored, because its entries' keys
changed. Rebuild a pre-built cache with `my_test_cache.put(df, "tmy", location)`, which
`get_tmy_data` serves exactly as stored.

---

## Frozen public surface

The authoritative public surface is `solar_challenge.__all__`, defined in
`src/solar_challenge/__init__.py`.  It is frozen by
`tests/unit/test_public_api_surface.py`, whose `FROZEN_SURFACE` pins every
public name and that name's signature and, for a dataclass, which of `eq`,
`order`, `unsafe_hash` and `frozen` it sets, and whose `FROZEN_MEMBERS` pins the
public methods, properties, class constants, and declared instance attributes of
every exported class and of every class outside `__all__` that the frozen
surface names.  The same file's `FROZEN_CLOSURE` pins the constructor of each
such class and, for a dataclass, which of those four parameters it sets;
consumers import such a class, such as `HomeConfig`, from its module.
`__all__` is also enforced at import time via the module's `__getattr__` guard,
and `tests/unit/test_init_lazy_surface.py` checks the lazy loader's structure.
Consumers should reference `__all__` directly rather than relying on any copy
maintained in this document.
