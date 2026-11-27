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
  "solar-challenge @ git+https://github.com/leodearden/solar-challenge.git@solar-challenge-v0.6.0",
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
   `chore(deps): bump solar-challenge to solar-challenge-v0.6.0`.
5. Open a PR; CI verifies the new surface before merge.

---

## Tag / release convention

Tags use the prefix `solar-challenge-` followed by a semantic version:

```
solar-challenge-v0.2.0   ← API freeze (first release tag)
solar-challenge-v0.3.0   ← next minor (additive surface changes)
solar-challenge-v0.4.0   ← basis-C cost-recovery + arbitrage
solar-challenge-v0.5.0   ← CBS amount due: own-use VAT + collectable total
solar-challenge-v0.6.0   ← current release (one release window for the review-all program; Python floor 3.11)
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
has a release note: one file,
`docs/unreleased/domain-library-consumption/<task id>.md`, named by the id of
the task that makes the change and added by the same commit. A change to what a
finance-model name returns has its note in
`docs/unreleased/cost-recovery-finance-model/<task id>.md`, for readers of
[cost-recovery-finance-model.md](cost-recovery-finance-model.md); a change both
kinds of reader need has a note in each. A note is
the paragraph the release lists under its task id: what changed against the
last tag, ending with what a consumer does when they re-pin. A later change to
the same note edits that file. Neither doc holds an unreleased note, so tasks
that write notes never wait on each other for a doc;
`tests/unit/test_unreleased_notes.py` checks both. The next release folds every
note into its notes in this section and deletes the files. A change to an exported
signature, to the constructor of a class outside `__all__` that the frozen
surface names, to which of the dataclass parameters `eq`, `order`,
`unsafe_hash` and `frozen` either kind of class sets, to whether either kind of
class's instances match a positional class pattern, hold a `__dict__` or take a
weakref, to an exported container
constant's keys or length, or the type of a value or item it holds, to
either kind of class's public members, or to the `__call__` a pinned class's own
body defines, must also edit `FROZEN_SURFACE`, `FROZEN_CLOSURE`, `FROZEN_MEMBERS`
or `FROZEN_CALLS` in `tests/unit/test_public_api_surface.py`, which fails until it
does. Such a change also adds each edited path to that file's `UNRELEASED`, with
the id of the task. The file fails until each path changed since the release is
listed and the note file of the task its row names exists, so it checks a path's
first change since the release: a later change to a listed path re-points that
row to its own task, which writes its own note, and only the `FROZEN_*` lock's
failure message asks for that.

**Release windows.** A rename or retirement of a frozen name lands only inside
an open release window: a `### solar-challenge-vX.Y.Z` subsection at the end of
this section whose first line says the window is open. Its release note is a
file under `docs/unreleased/domain-library-consumption/`, as the paragraph above
says, never a line in the window's section. The window closes with the release
commit that bumps the version, which folds the notes into the window's section.
The tag is cut on that commit's merge, pushed, and checked with
`git ls-remote`, as the push rule above says.

**The released snapshot.** `tests/_released_surface.py` holds the four frozen
tables as the last release shipped them, each `RELEASED_*` table being the
`FROZEN_*` table at the release commit, and that release's `RELEASED_VERSION`.
`UNRELEASED`, in `tests/unit/test_public_api_surface.py`, maps each path whose
form has changed since that release to the task that last changed it. The release
commit that bumps the version replaces each `RELEASED_*` table with the
`FROZEN_*` table it releases, sets `RELEASED_VERSION` to the new version, empties
`UNRELEASED`, and deletes the notes it folds, keeping `docs/unreleased/README.md`
and each `docs/unreleased/<doc>/README.md`.
`tests/unit/test_public_api_surface.py::test_the_released_snapshot_is_of_the_package_version`
fails a version bump that keeps the old snapshot.

Bumping the pin in a consuming project is a **deliberate, reviewed consumer
commit** (not an automatic update).  The tag convention makes the intent of
each bump self-documenting in git history.

### solar-challenge-v0.6.0

Released by task 224 (review-all-solar_challenge-20261013, S29 β), closing the window task 986 opened; Python floor: 3.11. A consumer re-pinning starts at [Consumer recipe for 0.6.0](#consumer-recipe-for-060).

**Breaking** — each entry: what changed (task N); what a consumer writes instead.

**Task 117.** The library's Python floor rose to 3.11 after the 0.5.0 tag: requires-python is ">=3.11,<3.15", where the tag's is ">=3.10,<3.13". solar-challenge-platform pins requires-python ">=3.11,<3.14" (main f8d7a1ef1), inside that range, so its re-pin locks. Consumers on Python 3.10 move to 3.11 or later before they re-pin.

**Task 326.** `TOUOptimizedStrategy` no longer accepts
`off_peak_hours`, and passing it raises `TypeError`; the 0.5.0 tag accepts it,
checks its hour ranges and otherwise ignores it. Consumers drop the argument
when they re-pin: it never changed a decision, because every hour outside
`peak_hours` is off-peak.

**Task 374.** `FinanceConfig` refuses input the 0.5.0 tag
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

**Task 384.** `LoadConfig`, `BatteryConfig` and
`PVConfig` refuse input the 0.5.0 tag accepts, and raise `ValueError`.
`LoadConfig` refuses a `household_occupants` that is not a whole number or is a
bool (Python's or numpy's), and holds `3.0` as the int `3`; the tag accepts e.g.
`2.5`. All three refuse non-finite (`inf`/`NaN`) capacities, power limits,
consumption, ageing inputs and system age; the tag accepts e.g.
`capacity_kwh=float("inf")`. Consumers fix such inputs when they re-pin.

This note also covers tasks 378 and 332.

**Task 436.** `SimulationResults`, reached through
`FleetResults.per_home_results`, is frozen, so that each of its series stays
named the column `to_dataframe()` writes it under. Assigning to one of its
fields, such as `results.demand = series`, raises
`dataclasses.FrozenInstanceError`; the 0.5.0 tag accepts the assignment.
Consumers that assign to a results field build new results with
`dataclasses.replace(results, demand=series)` instead when they re-pin.
`hash(results)` still raises `TypeError`.

**Task 464.** `WeatherCache.get`, and so `get_tmy_data` on
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

**Task 466.** `FleetResults` refuses input the 0.5.0 tag
accepts, and raises `ValueError`: an empty `per_home_results`, or a
`home_configs` that does not hold one `HomeConfig` for each entry of
`per_home_results`. The tag accepts both, and a fleet of no homes fails only
later, with a bare `IndexError` from `get_aggregate_series`, the `total_*`
properties and `to_aggregate_dataframe`. Those now raise the same `ValueError`
for a fleet whose lists were emptied or unpaired after construction. Consumers
that build a `FleetResults`, in a `simulate` they pass to
`solve_cost_recovery_rate` or in test fixtures, give it at least one home, and
one `HomeConfig` per home's results, when they re-pin.

**Task 469.** `SimulationResults`, reached through
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

**Task 540.** `Battery`'s `min_soc_fraction`,
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

**Task 559.** `LoadConfig` refuses a `use_stochastic` that
is not a bool, `None` included, raising `ConfigurationError`, a `ValueError`:
`LoadConfig(use_stochastic="no")` raises `use_stochastic must be true or false,
got 'no'`. The 0.5.0 tag accepts any value and reads it by its truthiness:
`None`, `0`, `""`, `[]` and `{}` select the deterministic Elexon profile, and
`"no"` or `"false"` the stochastic one. A numpy bool is held as the Python bool
it equals. A `load:` block's `use_stochastic` is refused the same way, and a
`fleet_distribution:` block's `load.use_stochastic` is refused as the block is
read, naming `fleet_distribution.load.use_stochastic`; the tag accepts both,
handing the value to the home, or to every home of the fleet. A null in either
block still reads as absent, the default true, as the task 914 and 919 lines
say. Consumers that pass such values give `true` or `false` when they re-pin.

**Task 590.** building an `EnergyFlowResult` with a flow
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

**Task 633.** `Battery.charge` and `Battery.discharge`
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

**Task 659.** `SelfConsumptionStrategy`,
`TOUOptimizedStrategy` and `PeakShavingStrategy` raise `ValueError` from
`decide_action` for a NaN or infinite `generation_kw`, `demand_kw`,
`battery_soc_kwh`, `battery_capacity_kwh` or `timestep_minutes`, and
`compute_grid_charge_power_kw` raises it for a NaN or infinite
`timestep_minutes`, whatever its context. The 0.5.0 tag refuses only negative
values, and a capacity or timestep of 0 or less, and returns a decision for
these: an infinite generation asks the battery to charge at `inf` kW, an
infinite demand asks `SelfConsumptionStrategy`, `PeakShavingStrategy` and, in
a peak hour, `TOUOptimizedStrategy` to discharge at `inf` kW, and a NaN
generation or demand asks for nothing. On the
tag, `compute_grid_charge_power_kw` returns NaN for a NaN timestep when its
gates would grid-charge, and 0.0 for any other NaN or infinite one. Every
refusal of these inputs, a negative value or a 0 included, now names
finiteness, as in `Timestep must be positive and finite, got nan minutes`, and
`compute_grid_charge_power_kw`'s also ends in its unit:
`timestep_minutes must be positive and finite, got nan minutes`. So
`simulate_timestep` with a battery and a built-in dispatch strategy raises the
strategy's `ValueError` for a NaN or infinite timestep, generation or demand,
before the battery moves any energy, whatever the strategy would decide. That
covers the step the task 633 line describes, now refused by the strategy, and a
step that neither charges nor discharges, which the tag returns with NaN or
infinite flows and the task 590 line's check refuses only when a flow is NaN.
For an infinite power, the tag also returns a step with infinite generation and
grid export, or infinite demand and grid import, the battery charging or
discharging at its maximum rate. `simulate_timestep_tou` raises the
controller's `ValueError` for such a timestep in a cheap period when the
battery's config sets `grid_charging`; the tag returns that step, with NaN or
infinite flows. Consumers that pass finite powers, SOCs and capacities and a
positive, finite timestep need no change when they re-pin.

**Task 660.** `SimulationResults`, reached through `FleetResults.per_home_results`, refuses an
amount series that holds no number in a row: a NaN, or an NA in a nullable
`Int64` or `Float64` series, in `generation`, `demand`, `self_consumption`,
`battery_charge`, `battery_discharge`, `grid_import`, `grid_export`,
`import_cost` or `export_revenue`, or in `heat_pump_load`, `grid_charge_cost` or
`grid_charge` when set. Building one, `from_dataframe` included, raises a
`ValueError` naming the first such series' column, in declaration order, how
many of its rows hold no number, and the first one's value and timestamp.
`per_minute_amounts()`, `total_amounts()` and `to_dataframe()`, and so
`calculate_summary`, raise the same refusal for an amount series made NaN in
place after construction, as by `results.demand.iloc[5] = math.nan`, which
freezing does not prevent. This narrows task 1218's admission of floats holding
NaN and of nullable series holding NA to the `battery_soc` and `tariff_rate`
levels, which are not checked. The 0.5.0 tag accepts such results: its
`to_dataframe()` writes each NaN to the frame, and its `calculate_summary` skips
each one, so a series that is NaN throughout totals 0.0. An infinite sample is
still accepted and makes its total infinite. Consumers that build results with a
number in every row of each amount series, and code that catches `ValueError`,
need no change when they re-pin; a consumer whose amounts can be unknown fills
or drops those rows before building the results.

**Task 669.** `SummaryStatistics`, `EnergyFlowResult`, and `OutputConfig` and
`SimulationPeriod` in `solar_challenge.config` are frozen. Assigning to one of
their fields, such as `summary.net_cost_gbp = cost`, raises
`dataclasses.FrozenInstanceError`; the 0.5.0 tag accepts the assignment. Each
of them now hashes, and equal values hash equal; on the tag, hashing one raises
`TypeError`. So a `ScenarioConfig`, whose `period` is a `SimulationPeriod` and
whose `output` an `OutputConfig`, hashes too, unless a value it holds is
unhashable, as the dict of a `PVConfig` that sets `custom_module_params` is:
`hash(scenario)` then raises `TypeError`, as it always does on the tag.
Consumers that assign to a field of one of these classes build the changed
value with `dataclasses.replace(value, field=new)` instead when they re-pin.

**Task 672.** `simulate_timestep` and `simulate_timestep_tou`
raise `ValueError` for a `timestep_minutes` that is not positive and finite:
NaN, infinite, 0 or negative. They refuse it before anything else, so before
any dispatch strategy, battery or `compute_grid_charge_power_kw` is given it,
with or without a battery and in any tariff period, naming it, as in
`Timestep must be positive and finite, got inf minutes`. The 0.5.0 tag returns
the step for a NaN or infinite timestep. For one of 0 or less, it returns the
step from `simulate_timestep` without a battery, and from
`simulate_timestep_tou` except in a cheap period when the battery's config sets
`grid_charging`, or where the battery refuses the negative power that a
negative timestep can bring. A NaN or infinite timestep gives NaN or infinite
generation, demand and self-consumption, and an infinite one also loses the
step's export or import:
`simulate_timestep(2.0, 1.0, None, timestep_minutes=math.inf)` returns
`grid_export=0.0`. A timestep of 0 gives all-zero flows, and a negative one
negative generation, demand and self-consumption. Since the tag, the battery of
the task 633 line, and the dispatch strategies and
`compute_grid_charge_power_kw` of the task 659 line, refuse the timestep
wherever they are given it, and the task 590 line's check refuses the flows of
a NaN or negative one, naming the flows rather than the timestep; a step that
gives none of them the timestep, as `simulate_timestep` without a battery does,
still returns for an infinite or zero one. Each step now refuses the timestep
before any of them, with the message the built-in strategies give. So
`simulate_timestep_tou` in a cheap period when the battery's config sets
`grid_charging` names it `Timestep`, where `compute_grid_charge_power_kw` named
it `timestep_minutes`, and `simulate_timestep` no longer calls a dispatch
strategy of the consumer's own with it: the step raises this `ValueError` where
the task 633 line says the battery's is raised. Consumers that pass a positive,
finite timestep need no change when they re-pin.

**Task 773.** `ConfigurationError` is defined in
`solar_challenge.errors`, which imports no other module of the package; import
it as `from solar_challenge.errors import ConfigurationError`.
`solar_challenge.config` still binds the name at runtime, so code that imports
it from there keeps running, but config no longer exports it, so `mypy --strict`
refuses that import ("does not explicitly export attribute"). Constructing a
`FinanceConfig`, a `GridServicesEventsConfig` or an `EventWindow`, valid or
refused, no longer imports the scenario grammar (`solar_challenge.config`) or
pvlib; on the 0.5.0 tag, constructing a `FinanceConfig` or a
`GridServicesEventsConfig`, or a refused `EventWindow`, imports both. Every
refusal message is unchanged; task 774 changes the class's base (its note).
Consumers that import it from `solar_challenge.config` switch to
`solar_challenge.errors` when they re-pin.

**Task 774.** `ConfigurationError` subclasses `ValueError`;
on the 0.5.0 tag it subclasses `Exception`. So `except ValueError` now catches
every refusal that the scenario grammar and the input types raise. An
`except ValueError` placed before an `except ConfigurationError` now takes a
refusal, and the later clause never runs, so code that handles a refusal apart
from other `ValueError`s names `ConfigurationError` first.
`GridServicesRateBand` and `solar_challenge.flex.FlexibilityValueBand` refuse a
value with `ConfigurationError`, where the 0.5.0 tag raises a plain
`ValueError`, with the same messages. `resolve_grid_services_rate_band` and
`solar_challenge.flex.resolve_flex_band` still raise a plain `ValueError` for a
band they do not know. Consumers that catch `ValueError` alone, or
`ConfigurationError` first, need no change when they re-pin.

**Task 782.** `householder_bill` and `bill_distribution` bill a summary's window as the
window's year by one rule: every total is scaled by the window's
`annualisation_scale`, `year_days / days`, with no 360-day threshold. A 400-day
window from 2024-01-01 to 2025-02-03 bills 365.25/400 of its energy, where the
0.5.0 tag bills it ×1, and a 30-day 2024 window bills ×366/30, where the tag
uses ×365/30. The standing charge covers the window's `year_days` days: 366 for
a 2024 window and 365.25 for one that crosses a new year, where the tag always
bills 365. Both raise `ValueError` for a `simulation_days` other than the
summaries' own, naming both day counts, and for a summary whose `window` is
None, naming `calculate_summary`; `bill_distribution` also refuses summaries
over different windows, naming both windows, and `householder_bill` own-use
below 0 or above the summary's `total_demand_kwh`, naming both. Neither emits
the tag's short-period `UserWarning`, nor does `project_multi_year` emit the
short-window one added since the tag. `solve_cost_recovery_rate` projects and
bills by the same rule, so its solved rate and outlay move with them, and it
refuses a fleet whose homes cover different windows.
`BillDistribution` gains the last keyword `annualised_from`, default None, which
`bill_distribution` sets to the summaries' window. Consumers give a hand-built
`SummaryStatistics` a `window`, or build it with `calculate_summary`, pass the
summaries' own `simulation_days`, and re-check any bill or solved rate of a
window that is not one whole non-leap calendar year, when they re-pin.

**Task 784.** `SummaryStatistics` holds `window: SimulationWindow`, imported from
`solar_challenge.timebase`, where the 0.5.0 tag's `simulation_days: int` stands,
after `export_ratio`: the window its totals were computed over, with no default,
which `calculate_summary` sets to its results' `window`. The last keyword
`window`, default None, that the task 778 line adds is gone, and so is that
line's refusal of a `simulation_days` other than the window's `days`.
`simulation_days` is a read-only property, the window's `days`, so the
dashboard's run JSON for a home summary, as its API and its assistant answer it,
holds no `simulation_days`: its `window`'s `first_day` to `last_day` are its
days. Building a summary whose `window` is not a `SimulationWindow`, such as None
or the day count a positional caller of the tag's form passes in its place,
raises `ValueError` naming `window`, the value it got and `calculate_summary`;
passing `simulation_days=` raises `TypeError`. `BillDistribution.annualised_from`,
which the task 782 line adds as a keyword defaulting to None, is required; it
follows `max_gbp`, and building a `BillDistribution` whose `annualised_from` is
not a `SimulationWindow`, such as None, raises `ValueError` naming
`annualised_from`, the value it got and `bill_distribution`.
`householder_bill(summary, window_self_consumption_kwh, finance)` and
`bill_distribution(summaries, finance)` take no `simulation_days`: each bills a
summary over its own window, which carries its days, so neither raises the task
782 line's refusals of a day count other than the summaries' own or of a summary
whose `window` is None. `householder_bill`'s second parameter,
`annual_self_consumption_kwh` on the tag, is `window_self_consumption_kwh`, the
home's own-use over the summary's window; passing the old keyword raises
`TypeError`, and the L1 and L2 refusals that the task 925 line describes name
`window_self_consumption_kwh`.
`simulate_timestep`, `simulate_timestep_tou` and every `decide_action`,
`DispatchStrategy`'s and that of each strategy `solar_challenge.dispatch`
defines, take `timestep_minutes` with no default, where the tag defaults it to
1.0, so a call that omits it raises `TypeError`. The method the task 392 line
adds as `SimulationResults.per_minute_amounts()` is `per_step_amounts()`: each
row's energy and money over that row's step, as the task 777 line describes. A
dashboard store at schema version 4 is refused until `solar-challenge web
migrate` brings it to version 5, whose step sets each stored `SummaryStatistics`
saved without a window, which the task 778 line says loads with `window` None, to
the window of its run's stored time series, and drops each one's
`simulation_days`, reporting as a dropped value a stored day count other than its
window's days. A run whose summary holds no window and whose time series is
missing is left in its format, named as a run `web migrate` cannot migrate, and
the dashboard answers it as unreadable. When they re-pin, consumers build
summaries with `calculate_summary` or pass `window=` and no `simulation_days=`;
pass `window_self_consumption_kwh=` and no day count to `householder_bill` and
`bill_distribution`; pass `timestep_minutes` to every call of
`simulate_timestep`, `simulate_timestep_tou` and a `decide_action`, a
`DispatchStrategy` override's call of its base's included; call
`per_step_amounts()`; give a hand-built `BillDistribution` its
`annualised_from`; and run `solar-challenge web migrate` on a dashboard store.

**Task 786.** `GridChargeConfig` is defined in
`solar_challenge.dispatch`, with the same constructor; import it as
`from solar_challenge.dispatch import GridChargeConfig`.
`solar_challenge.config` still binds the name at runtime, so code that imports
it from there keeps running, but config does not export it, so `mypy --strict`
refuses that import ("does not explicitly export attribute").
`TOUOptimizedStrategy` and `PeakShavingStrategy` refuse a value with
`ConfigurationError`, a `ValueError`, where the 0.5.0 tag raises a plain
`ValueError`. Their messages name `peak_hours`, with the rule
`0 <= start < end <= 24` and the period that breaks it, or `import_limit_kw`
and its value. `TOUOptimizedStrategy` also refuses an empty `peak_hours`,
which the tag accepts and runs as a strategy that never discharges.
The mutable `config.DispatchStrategyConfig`, whose `strategy_type` is a
string, is gone. Each strategy it configured is a frozen dataclass in
`solar_challenge.dispatch`: `SelfConsumptionStrategyConfig()`,
`TOUOptimizedStrategyConfig(peak_hours)`, its `peak_hours` a tuple of
`(start, end)` tuples, and `PeakShavingStrategyConfig(import_limit_kw)`. Each
holds only its own strategy's fields, and carries the strategy's name as
`strategy_type`, which its constructor does not take.
`dispatch.DispatchStrategyConfig` is their union, the type
`BatteryConfig.dispatch_strategy` takes, so a `BatteryConfig` with a strategy
is hashable. A `dispatch_strategy:` block naming a battery's strategy, in a
scenario file or a dashboard request, reads as the variant its `strategy_type`
names. It refuses a `strategy_type` no strategy has, naming its key path, e.g.
`home.battery.dispatch_strategy.strategy_type`, and the strategies; and a key
its strategy does not read, unless the key is null and another strategy reads
it, as exports before this change write it. So a `tou_optimized` block that
sets `import_limit_kw`, which the tag ignores, is refused. Exports write only
the strategy's own keys, and runs stored before this change load, each
strategy as its variant. These lines supersede the mentions of
`config.DispatchStrategyConfig` and `config.GridChargeConfig` in the task 505
and 567 lines. The platform changes `optimiser/planner.py`'s import of
`GridChargeConfig` when it re-pins, and needs no other change; other consumers
that catch `ValueError`, and pass at least one peak period, change only code
that builds or reads `config.DispatchStrategyConfig`, which builds or reads its
strategy's variant instead.

**Task 787.** building a `HomeConfig` refuses, with
`ConfigurationError`, a `dispatch_strategy` other than `'greedy'` or
`'tou_optimized'`, which the 0.5.0 tag accepts and dispatches as greedy. When
the home has a battery, it also refuses three settings the tag's dispatch
ignores with no warning: the battery's `grid_charging` under self-consumption
dispatch, its `grid_charging` without a `tariff_config`, and
`dispatch_strategy='tou_optimized'` without a `tariff_config` when the battery
names no strategy of its own. `FleetDistributionConfig` refuses an unknown
`dispatch_strategy`, and a fleet file without a `tariff:` block that dispatches
`tou_optimized` is refused, where the tag warns. A dashboard store at schema
version 2 is refused until `solar-challenge web migrate` brings it to version
3, whose step reads each stored run's dispatch as it ran. `simulate_home`'s
`strategy` replaces the dispatch only once the `HomeConfig` is built, so a home
whose override should grid-charge, such as `ScheduledChargeStrategy`'s windows,
still has to select a grid-charging dispatch of its own, as
[scheduled-charge-windows.md](scheduled-charge-windows.md) §2 says; removing its
`grid_charging` instead leaves the override no grid-charge context. The platform
needs no change: its `HomeConfig`s set none of these. When they re-pin, consumers give a home whose battery sets `grid_charging` a `tariff_config` and a grid-charging dispatch, give a fleet file that dispatches `tou_optimized` a `tariff:` block, and run `solar-challenge web migrate` on a dashboard store at schema version 2.

**Task 788.** `GridChargeConfig.target_soc_fraction` is a
fraction of the battery's effective (SOH-derated) capacity, capped at its
`max_soc_fraction`, where the 0.5.0 tag measures it against the nominal
`capacity_kwh`, uncapped. So grid-charge results change for batteries below SOH
1, multi-year projections included: a 10 kWh battery at SOH 0.7 with target 0.5
charges to 3.5 kWh, not 5.0. A target above `max_soc_fraction` charges the
battery to `max_soc_kwh` and then asks for no grid power, where the tag keeps
asking for `max_charge_kw`. `GridChargeContext.target_soc_fraction` becomes
`target_soc_kwh`, the target in kWh, and `compute_grid_charge_power_kw` drops
`capacity_kwh`. `simulate_timestep` passes the effective capacity as
`decide_action`'s `battery_capacity_kwh`, so a strategy's capacity-relative
targets, `ScheduledChargeStrategy`'s windows included, follow SOH. `Battery`
gains `grid_charge_target_kwh` and `max_charge_kw`. The platform's planner
workaround of `soh=1.0` (task 875) stays correct and can go; it needs no other
change. When they re-pin, consumers read `GridChargeContext.target_soc_kwh`, the target in kWh, where they read `target_soc_fraction`, and call `compute_grid_charge_power_kw` without `capacity_kwh`.

**Task 790.** `HomeConfig` has no `dispatch_strategy` field, so `HomeConfig(...,
dispatch_strategy=...)` and `dataclasses.replace(home, dispatch_strategy=...)`
raise `TypeError`, and `dispatch_strategy: str = 'greedy'` is gone from its
frozen signature; `FleetDistributionConfig` has no `dispatch_strategy` field
either. The dispatch strategy is the battery's own setting,
`BatteryConfig.dispatch_strategy`. A scenario's `home.dispatch_strategy`,
`homes[i].dispatch_strategy` or `fleet_distribution.dispatch_strategy` key, or
the top-level key of a home file that is itself a home block, of any value, null included, is refused when it is read, naming its path and the
battery's key in its place, `battery.dispatch_strategy: {strategy_type:
tou_optimized}`. A home with no battery names its results `self_consumption`,
or the name of a strategy given to `simulate_home`. A home's scenario block
written by `scenario_writer` no longer carries the key. A dashboard store at
schema version 7 is refused until `solar-challenge web migrate` brings it to
version 8, whose step brings each stored run to run-document format 8: it
moves each stored home's `dispatch_strategy` into its battery, where a battery
that names no strategy takes `tou_optimized` on its tariff's clock when its
home asked for `tou_optimized`, as the home ran, and reports it as a rewritten
value, e.g. `run '<id>': config.json's homes[2].battery_config.dispatch_strategy
was null, now {"strategy_type": "tou_optimized", "peak_hours": null}`; then it
drops every home's key.

`BatteryConfig.dispatch_strategy` defaults to `SelfConsumptionStrategyConfig()`
rather than `None`, and its annotation drops `| None`: a battery that names no
strategy holds the self-consumption variant it dispatches by, and `scenario_writer`
writes it as `dispatch_strategy: {strategy_type: self_consumption}`. A
`dispatch_strategy` that is not one of `DispatchStrategyConfig`'s variants, `None`
included, is refused when the battery is built, with a `ConfigurationError`
naming `dispatch_strategy`, the value and each variant's tag. A battery block
whose `dispatch_strategy` is absent or null still reads as self-consumption. The
same format-8 step gives each stored battery that names no strategy, whose home
did not ask for `tou_optimized`, `{"strategy_type": "self_consumption"}`, the
dispatch its run ran, unreported.

`home.HOME_DISPATCH_STRATEGIES`, `home.refuse_unknown_home_dispatch_strategy`,
`scenario_blocks.read_dispatch_strategy_key` and
`scenario_blocks.dispatch_strategy_argument` are deleted with the home-level
vocabulary, superseding task 947's note that names them: importing any of them
raises `ImportError`, and callers drop them, as the dispatch strategy is the
battery's `DispatchStrategyConfig`.

When they re-pin, library callers move `dispatch_strategy='tou_optimized'` from
the `HomeConfig` into its battery as
`dispatch_strategy=TOUOptimizedStrategyConfig()`, and scenario files move it
from the home or fleet block into the battery block as
`battery.dispatch_strategy: {strategy_type: tou_optimized}`; `'greedy'` is
dropped, as a battery that names no strategy dispatches self-consumption, and a
`BatteryConfig(..., dispatch_strategy=None)` leaves the argument out.

**Task 802.** `FinanceConfig` refuses, when it is built, three grid-services choices the
0.5.0 tag accepts: `grid_services_model="flat"` with `grid_services_events`
set, `grid_services_model="capacity_at_events"` with a nonzero
`grid_services_income_per_kw_per_year_gbp`, and
`grid_services_model="capacity_at_events"` with `grid_services_events` None.
The tag builds all three: under the first two the field the model does not
read is ignored, and the third is refused only by `project_multi_year`, before
it simulates, while `finance run` reports it with no events breakdown. Each
refusal is a `ConfigurationError`, a `ValueError`, naming the fields involved
and their values, and an unknown `grid_services_model` is refused naming
`flat` and `capacity_at_events`. `FinanceConfig.__post_init__` runs
`finance.grid_services_model_of`, so a `dataclasses.replace` of a
`FinanceConfig`, such as the one `optimize.apply_knob` builds for a
`sensitivity_panel` axis, is refused alike, and `parse_finance_config`, and so
`load_scenarios` and the `finance run` and `optimize configs` commands, refuse
such a `finance:` block at load. Under `capacity_at_events`, `optimize
configs` also refuses `--grid-services-kw`, whatever its value, and a
`--sensitivity` naming `grid_services`, both before any simulation, and its
default `--sensitivity` sweeps `retained_floor` alone, with a note on stderr
naming the omitted `grid_services` axis, where the tag sets and sweeps the
flat rate that model does not read. No frozen-table form changes. Consumers
that build or load such a choice drop the field its model does not read, the
events block under `flat` or the flat rate under `capacity_at_events`, or add
`grid_services_events` under `capacity_at_events`, when they re-pin, and drop
`--grid-services-kw`, or `grid_services` from `--sensitivity`, from an
`optimize configs` run on an events-model scenario; code that catches
`ValueError` needs no change.

**Task 803.** `GridServicesRateBand` gains a last field,
`flat_gbp_per_kw_per_year: float = 0.0`, refused unless it is >= 0 and finite.
`GRID_SERVICES_RATE_BANDS`' rows hold 1.5, 12.0 and 48.0 there, in £ per kW of
installed battery discharge power per year, beside unchanged per-event rates;
the two columns are independent calibrations of the same three bands. Every
band refusal shares one message, "LABEL must be one of low, central, high, got
VALUE". `GridServicesRateBands.resolve`, `resolve_grid_services_rate_band` and
`solar_challenge.flex.resolve_flex_band` raise `ConfigurationError`, a
`ValueError`, for a band they do not know, where the 0.5.0 tag raises a plain
`ValueError`; this supersedes the task 774 line's "still raise a plain
`ValueError`". `GridServicesEventsConfig`'s band refusal lists the bands in that
order. `solar_challenge.flex.FLEX_VALUE_BANDS` is read-only and keyed by
`solar_challenge.gridservices.GridServicesBand`. `GridServicesBand` is a
`StrEnum`: its members compare, hash and format as the tag's string keys,
`"low"`, `"central"` and `"high"`, so string lookups still work, and `str()`
and f-strings give the band's value.
`solar_challenge.flex.resolve_grid_services_band` is gone; read
`GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year` instead.
Consumers that catch `ValueError` need no change when they re-pin.

**Task 804.** `FinanceConfig.grid_services_model` now holds the grid-services pricing
itself: `NoGridServices()` by default, `FlatGridServices(r)`, or a
`GridServicesEventsConfig`. `grid_services_income_per_kw_per_year_gbp`,
`grid_services_events` and the `str` selector are retired, and
`finance.grid_services_model_of` is gone. A value that is none of the three
types raises `ConfigurationError`, a `ValueError`, naming them, and
`mypy --strict` refuses it. `NoGridServices`, `FlatGridServices` and
`GridServicesBand` join `__all__`. `GridServicesEventsConfig.band` is typed
`GridServicesBand` and held as the member it names, and a band string is
still accepted. `GridServicesRateBands.resolve` and
`resolve_grid_services_rate_band` take a `GridServicesBand`; a band string
still works at runtime, through the StrEnum. The scenario grammar reads one
`finance.grid_services_model:` block, tagged `type: flat` (with
`income_per_kw_per_year_gbp`) or `type: capacity_at_events` (with the events
fields); an absent or null block means no grid services. The three legacy
forms, a string `grid_services_model`, a `grid_services_income_per_kw_per_year_gbp`
key and a `grid_services_events` key, are refused, naming
`finance.grid_services_model` and the form to write. The `grid_services` knob
keeps its name, `grid_services_income_per_kw_per_year_gbp`, and builds
`FlatGridServices(v)`, or `NoGridServices()` at 0, refusing a scenario priced
at events. When they re-pin, consumers that build a `FinanceConfig` pass the
pricing value: `FlatGridServices(r)` for a nonzero rate, nothing for a zero
rate, the `GridServicesEventsConfig` itself for the events model. Consumers
that write scenario files move those keys under `grid_services_model:` with
its `type:`. The platform needs no edit, since it builds `FinanceConfig` with
the grid-services defaults only.

**Task 812.** `create_pv_system`, and so
`create_model_chain` and `simulate_pv_output`, count `custom_module_params`
with PVWatts parameters (`pdc0` and `gamma_pdc`) in modules of their `pdc0`,
the power pvlib's PVWatts DC model multiplies by the module count, and any
other module in modules of its `STC`. The 0.5.0 tag counts every module
without an `STC` key as 400 W. So 4 kW of
`{"pdc0": 300.0, "gamma_pdc": -0.004}` now wires 13 modules, 3.9 kWp, where
the tag wires 10, 3.0 kWp. On Bristol's scaled TMY, with the default system
losses, that raises its annual AC from 2948 to 3857 kWh (+30.8%; measured with
pvlib 0.15.1 on main 067b13e and on this change). Custom module parameters
with neither PVWatts parameters nor an `STC`, such as a row of pvlib's
`SandiaMod` library, raise `ValueError` naming `pdc0` and `STC`, with or
without `custom_inverter_params`; the tag counts them as 400 W modules. The
default module, and modules from `create_simple_module_params`, which carry
`pdc0` and `STC` at one value, are counted as on the tag. Consumers that pass a
PVWatts module without `STC` re-baseline its figures, and consumers that pass a
module with neither key add its `STC`, when they re-pin.

**Task 815.** `WeatherCache` stores each entry as one file,
`<prefix>_<hash>.csv`: a first line of JSON holding the SHA-256 of the rest of
the file, a line of JSON naming the timezone and frequency of the frame's
index, then the frame as CSV, written beside the entry and replaced whole by
one `os.replace`; the 0.5.0 tag writes a CSV and a `.meta.json` sidecar. `get`
returns the frame `put` stored, or `None` when there is no entry; for an entry
file cut short, changed after `put` wrote it, or holding anything else, it
raises `ValueError` naming the file, where the tag's `get` returned whatever
`read_csv` made of the CSV, restoring the index's timezone and frequency only
when the sidecar was there. `get_tmy_data` passes that `ValueError` on and
fetches nothing until the file is removed, as `WeatherCache.invalidate` does.
Every entry's key changes (key version 3), so each entry written before the
change is ignored, `get_tmy_data` fetches each such TMY afresh from PVGIS at
its first call ([Network I/O](#network-io)),
and `clear()` removes those files too. Consumers rebuild any pre-built cache
with `WeatherCache.put(df, "tmy", location)` when they re-pin, and read entries
only through `WeatherCache.get`, never from their files.

**Task 823.** `create_pv_system`, `create_model_chain` and
`simulate_pv_output` give every array pvlib's NOCT-SAM cell temperature, from
the module's own `T_NOCT` and efficiency (its rating over `A_c` × 1000); the
0.5.0 tag gives every module SAPM's generic open-rack glass/glass set
([pv-cell-temperature.md](pv-cell-temperature.md)). Every PV figure moves: on
Bristol's scaled TMY, with the default system losses, the default 4 kW goes
from 3977 to 4053 kWh a year, 993.1 to 1012.1 kWh per wired kWp (+1.9%;
measured with pvlib 0.15.1 on this change). Custom module parameters lacking
`T_NOCT` or `A_c` take the default module's value of that key, and a `T_NOCT`
or `A_c` with which NOCT-SAM cannot heat the cells above the air raises
`ValueError` naming it, as the default module's if the module lacks it. So a
module rated at 1791 W or more without its own `A_c`, such as one PVWatts
module standing for a whole array, now raises: over the default's 1.99 m² its
rating is an efficiency of 0.9 or more, and consumers give it its own `A_c`.
`create_simple_module_params` writes `A_c` from its
`efficiency` in place of an `"efficiency"` key nothing read, so its efficiency
now acts on output. A run chain's `results.cell_temperature` is NaN in hours
with no sun. The figures the lines above quote were measured under SAPM.
Consumers re-baseline every figure that depends on PV generation when they
re-pin, bills and the cost-recovery rate included.

**Task 825.** `PVConfig`'s `module_efficiency` and
`temperature_coefficient` widen from `float = 0.2` and `float = -0.004` to
`float | None = None`, and act on output. The 0.5.0 tag reads neither: a
`temperature_coefficient` other than `-0.004` lands on the default module's
`gamma_pdc`, which its CEC model never reads. `None` keeps the module's own
values: its rating over `A_c` × 1000, and its modelled temperature coefficient
of maximum power (0.2012 and −0.347 %/K for the default module). A set
`module_efficiency` sets the module's `A_c` to its rating over the efficiency ×
1000, so it acts through NOCT-SAM's cell temperature. A set
`temperature_coefficient` solves a CEC single-diode module's `Adjust`, keeping
its STC point, and sets its `gamma_r`, or sets a PVWatts module's `gamma_pdc`
([pv-module-settings.md](pv-module-settings.md)). `module_efficiency` must lie
above 0 and below 0.9, and `temperature_coefficient` from −0.01 per K to below
0, where the tag admits (0, 1] and (−1, 0). A set `temperature_coefficient` is
refused when the `PVConfig` is built if its `custom_module_params` are in
neither form, such as a row of pvlib's `SandiaMod` library, and when its system
is built if no `Adjust` reaches it for a custom CEC module. Each refusal is a
`ValueError` naming the field. On Bristol's scaled TMY, with the default system
losses, the default 4 kW's 4053 kWh a year changes by ×0.9951 at a
`module_efficiency` of 0.10 and ×1.0009 at 0.22, and by ×0.9983 at a
`temperature_coefficient` of −0.003 and ×1.0055 at −0.005: a steeper
coefficient gains over the year, because the cells spend most of it below
25 °C (measured with pvlib 0.15.1 on this change). A fleet whose
`module_efficiency` is a distribution now gives its homes different generation,
and `PVDistributionConfig.module_efficiency` defaults to `None`. A stored run,
scenario YAML or fleet distribution carrying the old inert 0.2 or −0.004 now
sets the field, against the default module's own 0.2012 and −0.347 %/K, so
consumers drop those values, or re-baseline the figures they move, when they
re-pin.

**Task 826.** `apply_degradation` leaves `__all__` and `solar_challenge.pv`; the 0.5.0 tag
exports it. `from solar_challenge import apply_degradation` and
`from solar_challenge.pv import apply_degradation` raise `ImportError`.
`simulate_pv_output` and `create_model_chain` already apply a `PVConfig`'s
`system_age_years` and `degradation_rate_per_year` to each array's DC power
before the inverter, as task 810's note says, so applying `apply_degradation` to
that output aged the array twice. `calculate_degradation_factor` is unchanged
and is the one ageing function. This supersedes the task 810 line's
"`apply_degradation` is unchanged, so applying it to `simulate_pv_output`'s
output for an aged `PVConfig` ages the array twice". The platform calls no
`apply_degradation` and needs no change. When they re-pin, consumers drop any
`apply_degradation` call on `simulate_pv_output`'s output and set the
`PVConfig`'s `system_age_years` (and `degradation_rate_per_year`) instead; one
that scaled some other series writes
`series * calculate_degradation_factor(age, rate)`.

**Task 827.** `get_tmy_data`, `get_weather_cache` and `set_weather_cache` leave `__all__` and
`solar_challenge.weather`; the 0.5.0 tag exports all three. Accessing one on the
package raises `AttributeError`, and `from solar_challenge.weather import` one
raises `ImportError`. `weather.default_weather()`, and so
`fleet.default_runner()`, is `PvgisTmy(WeatherCache())`: a new cache at each
call, in the directory `SOLAR_CHALLENGE_WEATHER_CACHE_DIR` names when it is set
and non-empty, else `.cache/weather` under the working directory. No
process-wide cache can steer it. When they re-pin, consumers write
`PvgisTmy(WeatherCache()).get(loc)` for `get_tmy_data(loc)`,
`PvgisTmy(None).get(loc)` for `get_tmy_data(loc, use_cache=False)` and
`WeatherCache()` for `get_weather_cache()`. One that called
`set_weather_cache(c)` passes `PvgisTmy(c)` wherever weather is taken, as
`simulate_home(..., weather=PvgisTmy(c))` or
`FleetRunner(weather=PvgisTmy(c), home_simulator=simulate_home)`, with
`simulate_home` from `solar_challenge.home`, or sets
`SOLAR_CHALLENGE_WEATHER_CACHE_DIR` to `c.cache_dir`.

**Task 837.** `compute_fleet_spare_capacity_kw` and `compute_grid_services_at_events` measure
firm spare capacity per event day, a local calendar date holding an in-window
timestep, and return and book the mean over event days of the fleet's daily
total; the 0.5.0 tag takes the minimum over every in-window timestep of the
season. `GridServicesEventsConfig` gains a last field
`delivery_baseline: str = "operational"`, `"operational"` or `"capacity"`,
refusing any other value with a `ConfigurationError` (a ValueError), and the
scenario key `grid_services_events.delivery_baseline` sets it.
`compute_fleet_spare_capacity_kw` gains a last parameter
`delivery_baseline: str = "operational"`, refused the same way.
`GridServicesAtEvents` gains `per_window_avail_p50_kw`,
`per_window_avail_p90_kw`, `per_window_displaced_self_use_kwh_per_event` and
`per_window_displaced_import_gbp_per_year`: the
capacity available on at least 50% and at least 90% of event days, and the
evening self-use an event displaces, per event and its value per year, which
`annual_income_gbp` does not subtract. To report that energy,
`compute_grid_services_at_events` reads each battery home's step length, so it
raises a ValueError for a fleet whose index has none, its rows not evenly
spaced or one row without a fixed-duration freq, which the 0.5.0 tag prices;
`compute_fleet_spare_capacity_kw` and
`GridServicesEventsConfig.annual_income_gbp` do not read it.
Consumers whose fleets come from `simulate_home` or `simulate_fleet` need no
code change when they re-pin; one that hands `compute_grid_services_at_events`
an unevenly spaced index resamples it to one cadence first.
Capacity-at-events figures for a fleet whose homes share one simulated index
never fall, and rise wherever a home's firm capacity differs between event days.

**Task 838.** `TariffConfig` refuses input the 0.5.0 tag
accepts: periods that leave a minute of the local day uncovered, or cover one
twice. It raises `ConfigurationError`, a `ValueError`, naming each gap and each
overlap as clock ranges, a range across midnight as one (e.g. `23:00-07:00`),
and each overlap's periods by name and times, e.g. `Tariff periods must cover
each minute of the day exactly once: 06:00-12:00 is covered by 'Off-peak'
00:00-12:00, 'Day' 06:00-00:00`. The tag builds such a tariff, then its
`get_rate` raises `ValueError` ("No tariff period matches timestamp") at the
first uncovered minute, part-way through a simulation, and bills an overlapped
minute at the first listed period's rate; `get_rate` now raises for no minute.
`solar-challenge validate config` reports such a custom tariff as an ERROR row
where the tag reports it valid, and a stored run or scenario file holding one
no longer loads. The platform's `integrations/tariff_adapter.to_solar_challenge`
now refuses a `Tariff` row whose periods do not tile at conversion, not at the
first uncovered half-hour. `TariffPeriod` refuses a NaN or infinite
`rate_per_kwh`, naming it, which the tag accepts: `Tariff period rate_per_kwh
must be finite and not negative, got nan £/kWh`. Its other refusals, of a
negative rate and of a time that is not an `HH:MM` string (a `datetime.time`
included), and `TariffConfig`'s refusal of no periods now raise
`ConfigurationError` where the tag raises a plain `ValueError`. A negative rate's
message is the one above, where the tag's is `Rate cannot be negative, got -0.1
£/kWh`, and a time's gives its prefix once, `Invalid time format '9': Expected
HH:MM format, got '9'`, where the tag's begins `Invalid time format: Invalid time
format '9'`. `validate config` reports a `.nan` or `.inf` rate as an ERROR row.
Consumers that catch `ValueError`, whose tariffs tile and whose rates are finite
and 0 or more, need no change when they re-pin.

`TariffConfig` gains two read-only members,
`cheap_minutes_of_day`, the frozenset of minutes of the local day (0 to 1439)
whose rate is below `peak_rate` and at or below the tariff's duration-weighted
mean rate, the mean of its 1,440 per-minute rates, and `is_cheap_at(timestamp)`,
whether the wall-clock minute of `timestamp` is one of them; a tariff whose
minutes share one rate has none. The 0.5.0 tag has neither.
`simulate_timestep_tou`, and the `GridChargeContext` that `simulate_timestep`
builds from a tariff for a grid-charging battery (its `is_cheap_period`),
classify each minute with `is_cheap_at`. The tag compares the minute's rate
with the mean of the period rates, each period counted once whatever its
length, so one schedule written as different period lists could dispatch
differently.
Dispatch changes only on tariffs with three or more distinct rates: night 0.10
(00:00-07:00), day 0.20 (07:00-16:00), peak 0.35 (16:00-19:00) and day 0.20
(19:00-00:00) as four periods holds the battery and grid-charges at the 0.20 day
rate on the tag (period mean 0.2125) and now does not (duration-weighted
mean 0.1896), as the same schedule with the night split at 03:00 already did.
Every two-rate tariff (Economy 7, Economy 10) dispatches as on the tag, and every
flat tariff dispatches as it did before task 838; task 182's note says how a flat
tariff's dispatch moved against the tag. Consumers on tariffs with
three or more distinct rates re-baseline the figures built on them when they
re-pin; other consumers need no change.

**Task 839.** `TOUOptimizedStrategy(peak_hours: list[tuple[int, int]] | None = None, *,
tariff: TariffConfig | None = None)` runs on the tariff's clock when it is given a
tariff and no `peak_hours`: it discharges in the tariff's expensive minutes and
grid-charges in its cheap ones, each minute classified by
`TariffConfig.is_cheap_at`. Given both, it refuses input the 0.5.0 tag accepts: a
window that reaches a cheap minute of the tariff raises `ConfigurationError`, a
`ValueError`, naming each such window as `peak_hours[i]` and the window given, the
clock ranges it reaches and the tariff, e.g. `dispatch strategy 'tou_optimized'
discharges the battery in its peak hours, so none may fall in a cheap period of
tariff 'Economy 7 (off-peak 00:30-07:30)', but peak_hours[0] (7, 9) reaches
07:00-07:30; remove peak_hours to discharge on the tariff's clock, or narrow the
window to the tariff's expensive minutes`. A window wholly inside the expensive
minutes is accepted and narrows discharge to its hours. Given neither, it is
refused, naming `tou_optimized`, the tariff's clock and the missing tariff; the
tag requires `peak_hours`. `peak_hours` alone is accepted unchecked, as on the tag.

`dispatch.TOUOptimizedStrategyConfig.peak_hours` is optional, `None` by default:
the tariff's clock. A scenario battery block may say `dispatch_strategy:
{strategy_type: tou_optimized}` under a time-of-use tariff, which the tag refuses
as missing `peak_hours`. `build_dispatch_strategy` builds the strategy with the
home's tariff, so building a home whose battery's `peak_hours` reach a cheap
minute of its tariff, or whose battery is on the tariff's clock with no tariff, is
refused, and `solar-challenge validate config` reports it as an ERROR row. Building
a home, or calling `build_dispatch_strategy`, with `grid_charging` set on a tariff
with no cheap period (any flat tariff) is refused, naming `grid_charging`, the
tariff and the strategy, for a battery's strategy and for the home-level
`tou_optimized` route alike: `grid_charging is set, but tariff 'Flat rate 0.25
£/kWh' has no cheap period, so dispatch strategy 'tou_optimized' never charges
from the grid; remove grid_charging or use a time-of-use tariff`. The tag builds
such a home, and it grid-charges nothing. A dashboard store at schema version 3
is refused until `solar-challenge web migrate` brings it to version 4, whose step
drops each stored battery's `grid_charging` that its run ignored on a tariff with
no cheap period, reporting each value it rewrites. A stored run whose battery
dispatches `tou_optimized` with `peak_hours` that reach a cheap minute of its
tariff, such as the home page's former default 16:00-21:00 on Economy 10, no
longer loads: it discharged in cheap minutes, which no configuration now accepted
dispatches. `web migrate` leaves it in its format and names it as a run it cannot
migrate, with the refusal, and the dashboard answers it as unreadable. When they
re-pin, the platform may replace `planner._derive_tou_hours` with
`TOUOptimizedStrategy(tariff=tariff)`, and must not pass both its derived hours
and the tariff: its "any slot" hours contradict Economy 7 at 07:00-07:30.
Scenario files may drop `peak_hours` under a time-of-use tariff. Code that
catches `ValueError` needs no change.

**Task 842.** an EV whose `EVConfig.smart_charging_mode` is `"off_peak"` now charges in its
home tariff's cheap minutes, `TariffConfig.cheap_minutes_of_day`, in place of
the window the task 708 line calls Economy 7's 00:30–07:30. Each day's session
is still the one the task 708 line describes, covering as many of those minutes
as it can, as early as it can. A 7 kW, 35 kWh EV home from 18:00 to 07:00 on
Economy 10 now charges from 00:00 until 05:00, all at the off-peak rate; on the
0.5.0 tag, as on the task 708 line's schedule, it charged from 00:30 until
05:30, its last 30 of 300 minutes at Economy 10's 0.27 peak rate. On an
Economy 7 whose off-peak runs from 23:00 to 06:00 it starts at 23:00, and on a
tariff with no cheap minute, such as a flat rate, it charges from arrival, as
`"none"` does. On Economy 7's default 00:30–07:30 its schedule is the one the
task 708 line describes. These times hold until the run's first clock change.
As on the tag, the EV's days are laid end to end, 1,440 minutes each, from the
run's first midnight, so after a clock change each session runs an hour off the
wall clock, late on summer time after a winter start and early on winter time
after a summer start: over 2024 from 1 January the Economy 10 home charges
05:00–05:59 at the peak rate each day from 31 March to 26 October, 12,600 of
its 109,500 charging minutes, where the tag charged 23,550 of them at the peak
rate. Building a `HomeConfig` with such an EV and no
`tariff_config` now raises `ConfigurationError`, a `ValueError`, naming
`smart_charging_mode 'off_peak'` and the missing tariff, and so does reading a
home or fleet file whose `ev` block sets or draws `off_peak` without a tariff;
`validate config` reports such a file as an error. A stored run whose config
holds such a home no longer reads: its `StoredRunUnreadable` names
`HomeConfig`'s refusal. The 0.5.0 tag builds such a home, and times every
off_peak EV's charging by Economy 7's window whatever its tariff.
`generate_ev_charging_profile` and `generate_load_profile` take a new
keyword-only `tariff`, and `generate_ev_charging_profile` refuses an off_peak
EV without one with the same message. The demand that `simulate_home` and
`simulate_fleet` return changes for off_peak EV homes on a tariff whose cheap
minutes are not 00:30–07:30, and so do the figures built on it. Consumers give
each home with an off_peak EV a tariff, or set its `smart_charging_mode` to
`"none"`, and re-baseline those figures, when they re-pin.

**Task 843.** `TariffConfig.mean_period_rate`, the mean of a tariff's period rates with each
period counted once whatever its length, is retired before it reaches a
release. Task 200 added it on `main` after the 0.5.0 tag, and since task 838
nothing in `solar_challenge` reads it: `cheap_minutes_of_day` compares each
minute's rate with `peak_rate` and with the tariff's duration-weighted mean
rate, which stays private. Like the 0.5.0 tag, 0.6.0 has no such member, so
`TariffConfig.economy_7().mean_period_rate` raises `AttributeError`. Consumers
need no change when they re-pin.

**Task 861.** `PVConfig`, `BatteryConfig`, `LoadConfig`,
`Location` and `FleetConfig`, and `HeatPumpConfig` and `EVConfig` from their
modules, refuse input the 0.5.0 tag accepts, and raise `ConfigurationError`, a
`ValueError`, for every refusal where the tag raises a plain `ValueError`. Each
number setting must be a finite number, never a bool, inside its field's
range, and one that is not a finite number is refused as such before its range
is checked. The tag accepts `True` wherever 1 is in range, e.g.
`PVConfig(capacity_kw=True)`, and NaN in a heat pump's capacity and demand, an
EV's required charge and a location's altitude. EV hours, `household_occupants`
and `LoadConfig.seed` must be whole numbers: `EVConfig("7kW", 17.5)` is
refused, which resolves the task 914 line's `IndexError`. `Location` refuses a
`timezone` zoneinfo does not know, e.g. `"Europe/Londn"`. `BatteryConfig` reads
its `charge_efficiency` and `discharge_efficiency` even where a round-trip
`efficiency` replaces them, so `BatteryConfig(capacity_kwh=5, efficiency=0.9,
charge_efficiency=0)`, which the tag builds, is refused. Each type holds what
it read: `PVConfig(capacity_kw=4).capacity_kw` is `4.0` and
`EVConfig("7kW", 18.0).arrival_hour` is `18`; a numpy scalar becomes the Python
number it equals, and a numeric string such as `"4"` is read as its number, so
a quoted number in a `pv:`, `battery:`, `load:` or `location:` block, a raw
`TypeError` on the tag and refused as the task 914 line says, now reads as that
number. Messages name the field and the value, e.g. `capacity_kw must be
greater than 0, got 0` in place of the tag's `Capacity must be positive and
finite, got 0 kW`. `require_valid_power_limit`, `require_valid_capacity_setting`,
`has_battery`, `household_occupant_count`, `calculate_degradation_factor` and
`calculate_cop` refuse the same way, and so do a `Battery`'s SOC-limit and
efficiency assignments; the capacity-setting message drops "(0 for no
battery)". `require_valid_power_limit` and `require_valid_capacity_setting`
return the number they read, and `has_battery` compares that number, so
`has_battery("4", "battery_kwh")` is `True`. `solar-challenge validate config`
reports such homes as an ERROR row, and the CLI labels a refused
`--battery-kwh` "Configuration error:" where the tag says "Invalid value:".
Consumers that catch `ValueError` need no change for the type; those that
match message text, or pass such values, change them when they re-pin.

**Task 862.** `SEGTariff`, `TariffPeriod`, `FinanceConfig`,
`GridServicesRateBand`, `EventWindow` and `GridServicesEventsConfig`,
`solar_challenge.flex.FlexibilityValueBand`,
`solar_challenge.community.CommunityBillingConfig` and
`solar_challenge.optimize.ConfigPoint` refuse input the 0.5.0 tag accepts, and
raise `ConfigurationError`, a `ValueError`, naming the field and the value;
`FlatGridServices`, which the tag lacks, refuses the same way. Each number must
be a finite number, never a bool (Python's or numpy's), inside its field's
range, and one that is not a finite number is refused as such before its range
is checked. The tag accepts e.g. `SEGTariff("x", float("nan"))`,
`TariffPeriod("00:00", "00:00", True)`,
`CommunityBillingConfig(seg_rate_pence_per_kwh=-1.0)` and an `EventWindow` with
`event_hours=float("inf")` or `events_per_year=2.5`; `TariffConfig.flat_rate`
refuses `True` and `"x"` as its period does, where the tag names a `True`
rate's tariff "Flat rate 1.00 £/kWh". `EventWindow`'s `months`, `weekdays` and
`hours` must each be a list of whole numbers in range, an element named by its
position, e.g. `months[0]`. Each type holds what it read:
`SEGTariff("x", 4).rate_pence_per_kwh` is `4.0` and
`EventWindow(months=[1, 2], ...).months` is `(1, 2)`, a tuple of ints, its
`weekdays` and `hours` likewise; a numeric string such as `"4"` is read as its
number, a numpy scalar becomes the Python number it equals, and
`FinanceConfig`'s year counts are still held as ints. Messages name the field
and the value, e.g. `rate_pence_per_kwh must be at least 0, got -0.5` in place
of the tag's `SEG rate must be non-negative, got -0.5 p/kWh`, and `months[0]
must be between 1 and 12, got 13` in place of `EventWindow.months values must be
in 1..12, got (13,)`. This supersedes the task 374 line's "must be > 0 and
finite", "must be >= 0 and finite" and "must be a finite whole number", the task
838 line's `TariffPeriod` rate messages, the task 803 line's flat rate refusal,
which now reads e.g. `flat_gbp_per_kw_per_year must be at least 0, got -1.0`,
and the task 774 line's "with the same messages" for `GridServicesRateBand` and
`FlexibilityValueBand`. `CommunityConfig`'s refusals raise `ConfigurationError`
where the tag raises a plain `ValueError`, with the same messages. `finance run`
and `optimize configs` refuse such a finance block before they simulate, e.g.
`Configuration error: event_hours must be a finite number, got inf`, where the
tag accepts it; `solar-challenge validate config` reports it as an ERROR row
for a `scenario:` file.
Consumers that catch `ValueError` need no change for the type; those that match
message text, or pass such values, change them when they re-pin.

**Task 863.** `BatteryConfig` gains `with_round_trip(round_trip_efficiency)`, the config with
`charge_efficiency` and `discharge_efficiency` each the square root of
`round_trip_efficiency` and `efficiency` None. It refuses a round trip that is
not a finite number above 0 and at most 1 with a `ConfigurationError` naming
round-trip efficiency and the value. `BatteryConfig` now refuses `efficiency`
set beside a per-direction efficiency that is neither its square root nor that
field's default, 0.975, raising a `ConfigurationError` that names `efficiency`
and each such field with its value, where the 0.5.0 tag silently keeps the
square root. So `dataclasses.replace(cfg, charge_efficiency=x)` on a config
with `efficiency` set raises, where the tag ignores `x`. `replace()` of any
other field still constructs, and `replace(cfg, efficiency=None,
charge_efficiency=x, discharge_efficiency=y)` is how to change the pair. A
scenario's `home:`, `homes:` or `community_battery:` battery block that sets
`efficiency` with `charge_efficiency` or `discharge_efficiency` is refused,
whatever their values, naming the block and the keys, e.g. `home.battery sets
both forms of a battery's efficiency: efficiency and charge_efficiency`, where
the tag lets `efficiency` win silently; `validate config` reports it as an
ERROR row and exits 1. An `efficiency` in one of those battery blocks that is
not a finite number above 0 and at most 1 is refused naming the key by its
path, e.g. `home.battery.efficiency: round-trip efficiency must be greater
than 0 and at most 1, got 1.5`, where the tag's refusal names no block. A
battery read from such a block, or from the web home form's `efficiency_pct`,
carries the per-direction pair and `efficiency` None, and the scenario writer
writes the pair and never `efficiency`. A `fleet_distribution:` battery still
holds the `efficiency` it draws beside the pair it derives, and one that also
draws a per-direction efficiency is refused when its homes are generated
wherever `BatteryConfig` refuses that pair, naming `fleet_distribution.battery`
and the home. A caller that never sets `efficiency`, as the platform does not,
needs no change when it re-pins; one that sets it beside the pair passes one
form, or calls `with_round_trip`; a scenario file keeps one form per battery.

**Task 864.** `GridChargeConfig`, `TOUOptimizedStrategy`
and `PeakShavingStrategy`, and the task 786 line's `TOUOptimizedStrategyConfig`
and `PeakShavingStrategyConfig`, refuse input the 0.5.0 tag accepts, and raise
`ConfigurationError`, a `ValueError`, naming the field and the value. Each number
they read, `target_soc_fraction`, `import_limit_kw` and each hour of a
`peak_hours` window, must be a finite number: a bool, Python's or numpy's, NaN,
±inf or a value `float()` cannot read is refused as such before its range is
checked. A peak hour must also be a whole number from 0 to 24, and is named by
its position, e.g. `peak_hours[1][0]`; each window must be a `(start, end)` pair
that starts before it ends, and `peak_hours` a list of at least one window. The
tag accepts e.g. `GridChargeConfig(True)`, `PeakShavingStrategy(float("nan"))`
and `TOUOptimizedStrategy([(16.5, 19)])`. Each holds what it read:
`PeakShavingStrategyConfig(3).import_limit_kw` is `3.0`, a numeric string such
as `"3"` is read as `3.0`, a numpy scalar becomes the Python float it equals, and
`peak_hours` holds its windows as a tuple of int pairs, its hours read the same
way, so `TOUOptimizedStrategyConfig([[16.0, 19.0]]).peak_hours` is
`((16, 19),)`. Messages name the field and the value, e.g. `import_limit_kw must
be greater than 0, got 0.0`, `peak_hours[0][0] must be between 0 and 24, got 25`
and `peak_hours[0] must be a (start, end) window that starts before it ends, got
(20, 17)`; this supersedes the task 786 line's description of those messages.
`solar-challenge validate config` reports a battery's
`grid_charging: {target_soc_fraction: true}`, a `peak_shaving` strategy's
`import_limit_kw: true` and a `tou_optimized` strategy's
`peak_hours: [[16.5, 19]]` as ERROR rows, where the tag reports such files
valid. Consumers that catch `ValueError` need no change for the type; those that
match message text, or pass such values, change them when they re-pin.

**Task 866.** A scenario file's block readers build each type through one wrap, the new
`solar_challenge.scenario_blocks.constructed`, and pass the block's values as
written. A refusal a reader gets from constructing its type is a
`ConfigurationError` whose message is the type's own after the block's path,
e.g. `home.pv: capacity_kw must be a finite number, got True`; the paths
include `homes[1].pv: `, `location: `, `home.battery.grid_charging: `,
`home.tariff.periods[0]: `, `finance: `,
`finance.grid_services_events.event_windows[0]: `, `seg: `, `community: `, and
`the top level: ` for a flat home file's own refusal, e.g. an off_peak EV with
no tariff. On the 0.5.0 tag these messages carry no path. A tariff rate, which
is flat_rate's `rate_per_kwh`, an economy preset's `off_peak_rate` or
`peak_rate`, or a custom period's `rate_per_kwh`, is refused naming the key the
block sets and the value when it is a bool or a word, where the tag reads
`true` as 1.0 and a word gives `could not convert string to float: 'cheap'`. An
event window's fractional `months`, `weekdays`, `hours` or `events_per_year`
is refused, where the tag truncates it with `int()`. A finance or
`grid_services_events` value its type refuses is refused naming the key, e.g.
`finance: vat_rate must be a finite number, got 'x'` in place of the tag's
`finance block contains a non-numeric value: could not convert string to
float: 'x'`, and `grid_services_model`, `band` and `delivery_baseline` reach
their type as written, so `band: 5` is refused as `got 5`. A `seg:` block's
rate and billing's `seg_rate_pence_per_kwh` are read as `SEGTariff` reads
them, e.g. `seg: rate_pence_per_kwh must be at least 0, got -1` and
`community.billing.seg_rate_pence_per_kwh: rate_pence_per_kwh must be a
finite number, got True`. This supersedes the task 862 line's `Configuration
error: event_hours must be a finite number, got inf` for `finance run` and
`optimize configs`, which now reads `Configuration error:
finance.grid_services_events.event_windows[0]: event_hours must be a finite
number, got inf`. Consumers that catch `ConfigurationError` or `ValueError`
need no change when they re-pin; those that match message text, or pass such
values, change them.

**Task 867.** `BatteryConfig` has no `efficiency` field, so `BatteryConfig(...,
efficiency=x)` and `dataclasses.replace(cfg, efficiency=x)` raise `TypeError`,
and `efficiency` is gone from its frozen signature; on the 0.5.0 tag it is a
field whose square root becomes `charge_efficiency` and `discharge_efficiency`.
Write `BatteryConfig(...).with_round_trip(x)`, which now just sets
`charge_efficiency` and `discharge_efficiency` each to the square root of `x`
and leaves every other field as it is. A scenario's `home:`, `homes:` or
`community_battery:` battery block still reads `efficiency:` as the round trip,
through `with_round_trip`, and still refuses it beside `charge_efficiency` or
`discharge_efficiency`, as task 863's note says. A `fleet_distribution:`
battery that draws or sets `efficiency` now builds each home's battery through
`with_round_trip` too, so the battery holds only the pair. A block that draws
or sets `efficiency` beside `charge_efficiency` or `discharge_efficiency` is
refused when it is read, whatever their values, naming the block and the keys:
`fleet_distribution.battery: sets both forms of a battery's efficiency:
efficiency and charge_efficiency; set efficiency, the round trip, or
charge_efficiency and discharge_efficiency, not both`, and a
`FleetDistributionConfig` built with such a battery is refused the same way.
863's note has such a block refused only when its homes are generated, and a
per-direction efficiency at its default giving way. A drawn `efficiency` that
is not a finite number above 0 and at most 1 is refused when the homes are
generated, naming `fleet_distribution.battery`, the home, `efficiency` and the
value. The scenario writer writes no `efficiency`, as before. A dashboard store
at schema version 6 is refused until `solar-challenge web migrate` brings it to
version 7, whose step brings each stored run to run-document format 7: it drops
each stored battery's `efficiency`, in the run's directory and in its runs row
alike, keeps the `charge_efficiency` and `discharge_efficiency` derived from
it, and reports as a dropped value each one that is not null, e.g. `run
'<id>': config.json's battery_config.efficiency was 0.81`. When they re-pin,
library callers that pass `efficiency=` to `BatteryConfig` or `replace()` call
`.with_round_trip(x)` instead, scenario files need no change, and dashboards
run `solar-challenge web migrate`. The platform sets no `efficiency`, and
needs no change.

**Task 868.** The fleet grammar's types read their numbers when they are built, through
`solar_challenge.number_fields`, and raise `ConfigurationError` naming the
field and the value: `WeightedDiscreteDistribution`'s `weights`,
`NormalDistribution`'s `mean`, `std`, `min` and `max`, `UniformDistribution`'s
`min` and `max`, `ShuffledPoolDistribution`'s `counts`,
`ProportionalDistribution`'s `multiplier` and `offset`, `SweepSpec`'s `min`,
`max` and `steps`, and `FleetDistributionConfig`'s `n_homes` and `seed`. They
hold Python floats and ints, and a `weighted_discrete`'s or `shuffled_pool`'s
`values` as a tuple of them as given. So a fractional `n_homes` or pool count
is refused where it was truncated (`n_homes: 2.7` ran 2 homes), and so is a
bool or fractional seed. A scalar or `fixed` number in a `fleet_distribution:`
block is refused as the block is read, naming its path, when it is a bool, text
or not finite: `capacity_kw: true` was a 1.0 kW home. On a choice key
(`heat_pump_type`, `charger_type`), a `fixed`, `normal`, `uniform` or
`proportional_to` spec is refused as a spec the key does not draw before any
number in it is read, so a `fixed` null there, which gave no home a heat pump
or an EV, is refused too. A bare number in a `ComponentDistribution` built in
code reaches the home's type as given, so a `True` is refused there rather than
read as 1.0. A refusal `FleetDistributionConfig` makes while
`parse_fleet_distribution_config` builds it now starts `fleet_distribution: `.
EV arrival and departure hours drawn from a `normal`, `uniform` or
`proportional_to` are rounded to the nearest whole hour, a half rounding up,
not truncated, and a listed or fixed fractional EV hour is refused by
`EVConfig`, as an occupant count is. A rounded hour stays within the whole
hours from its `normal`'s or `uniform`'s `min` to its `max`, and such a spec
with no whole hour between them is refused when the fleet is built. Unless
those bounds keep it from 0 to 23, a draw or value from 23.5 up to 24 now gives
24, and one between -1 and -0.5 gives -1, which `EVConfig` refuses where
truncation gave 23 and 0. So seeded EV fleets change:
`scenarios/bristol-with-evs.yaml`'s 30 EV homes' mean arrival moves from 17.433
to 17.933 and their mean departure from 6.533 to 7.2.
`solar_challenge.scenario_blocks.float_or_none`, which the task 947 line
lists, is deleted. Consumers give `n_homes`, seeds and pool counts as whole
numbers and fleet numbers as numbers, not text, give a choice key null or one
of its choices bare, bound each EV hour's `normal` or `uniform` from 0 to 23 and
keep a `proportional_to` EV hour below 23.5, expect a seeded EV fleet's hours
to move, and regenerate any stored expectation of one, when they re-pin.

**Task 871.** Building an `EnergyFlowResult` with an infinite flow raises `ValueError`
naming each such flow and its value, as a flow below 0 or NaN does since the
task 590 line, and that refusal now reads `EnergyFlowResult's flows are the
energies its timestep moved, so each is a finite number at least 0: got
generation=inf, grid_export=inf` where it read `... so each is at least 0:
...`. The 0.5.0 tag accepts an infinite flow. So `simulate_timestep` raises
`ValueError` rather than return a step whose energy is beyond a float, as
`simulate_timestep(1e308, 0.0, None, timestep_minutes=120)` does, for which the
tag returns `generation=inf` and `grid_export=inf`; with a battery it raises
after the battery has moved, so the battery keeps that step's charge or
discharge. Consumers whose powers and timesteps keep each step's energies
finite need no change when they re-pin; one that matches the refusal's text
updates it to the new wording.

**Task 879.** `solar_challenge.fleet`'s `simulate_fleet`, `simulate_fleet_iter`,
`simulate_multi_sweep_iter`, `collect_multi_sweep_results` and `MultiSweepResults`
are removed; none was in `__all__`. `fleet.FleetRunner(weather, home_simulator,
parallel=True, max_workers=None)` simulates fleets: `default_runner().simulate(fleet,
start, end)` runs one as `simulate_fleet` did, in parallel on `default_weather()`, and
`FleetRunner(weather=PvgisTmy(WeatherCache(d)), home_simulator=simulate_home,
parallel=False)` sets the weather and the worker policy. `simulate_each(fleets, start,
end)` yields each fleet's index and `FleetResults` from one pool as the fleet's last
home finishes, and `progress=` takes a callable told (homes finished, homes in the
call). A failed home's own exception now carries a note naming the home and its fleet,
and the homes not yet started are cancelled; the 0.5.0 tag names no home and runs every
pending home first. `max_workers=0` is refused with a `ValueError` naming `max_workers`,
instead of meaning every CPU. Consumers that import one of the five names move to
`default_runner()` or `FleetRunner` when they re-pin.

**Task 885.** `finance.project_multi_year`, `optimize.run_sweep` and `optimize.sensitivity_panel`
take `simulate` as a required keyword-only argument, typed as `fleet.FleetSimulate`:
a callable `(fleet_config, start, end)` returning `FleetResults`. A call that
passes none raises `TypeError` naming `simulate` before any fleet is simulated,
where the 0.5.0 tag silently simulates each fleet through `simulate_fleet`, in
parallel on up to one process per CPU. `solve_cost_recovery_rate`'s `simulate`
is required too (task 892's note). Consumers that call one of the three with no
`simulate` add
`simulate=default_runner().simulate`, which simulates as `simulate_fleet` did,
or `simulate=FleetRunner(...).simulate` with the weather and worker policy they
choose, when they re-pin.

**Task 889.** A parallel `fleet.FleetRunner` call, `default_runner().simulate`'s included,
never starts its worker processes as a fork of the calling process. Where
multiprocessing's default start method is `fork` (Linux before Python 3.14), the
pool starts them by
`forkserver`, as Linux already does from 3.14; elsewhere it keeps the default
(`spawn` on macOS). On the 0.5.0 tag a parallel fleet on Linux before 3.14
forked the caller. A worker now starts afresh: it imports the calling script's
main module, and the home simulator's (pandas and pvlib, for `simulate_home`),
and inherits no state the caller set after import, so each call's pool takes a
second or more to start, which a fork did not. The workers also ignore SIGINT: a
Ctrl+C in a terminal interrupts the calling process alone, which hands the pool
no further home and waits for the running ones to finish before its
`KeyboardInterrupt` propagates; on the 0.5.0 tag it interrupted the running
homes too. A consumer that makes a parallel fleet call from a script guards the
script's entry point with `if __name__ == "__main__":` when they re-pin, as
macOS already requires, and moves a home simulator defined in a notebook or
other interactive session into an importable module.

**Task 892.** `solve_cost_recovery_rate` takes `simulate` as a required keyword-only argument,
typed as `fleet.FleetSimulate`, as `finance.project_multi_year` does (task 885's
note). A call that passes none raises `TypeError` naming `simulate` before any
fleet is simulated, where the 0.5.0 tag resolved a default simulator behind the
call. `FleetRunner`, `FleetSimulator`, `HomeSimulator`, `FleetSimulate` and
`HomesDone` join `__all__`, so `solar_challenge` exports them; the 0.5.0 tag
exports none of them. Each is the object `solar_challenge.fleet` defines, so
either import gives the same object, and accessing one loads
`solar_challenge.fleet`, and so pvlib, as any of the package's fleet names does.
When they re-pin, consumers that call `solve_cost_recovery_rate` with no
`simulate` pass `simulate=default_runner().simulate`, with `default_runner` from
`solar_challenge.fleet`, to simulate as that default did. One that relied on
`set_weather_cache` reaching that default, which task 827 retires at the same
release, passes
`simulate=FleetRunner(weather=PvgisTmy(WeatherCache(d)), home_simulator=simulate_home).simulate`
instead, with `simulate_home` from `solar_challenge.home`. Consumers may then
write `from solar_challenge import FleetRunner`, and likewise for the other four
names, or keep importing them from `solar_challenge.fleet`.

**Task 894.** `generate_load_profile` now takes
`(config, window, ev_config=None, *, household_model=...)`, where `window`, a
`timebase.SimulationWindow`, replaces `start_date`, `end_date` and `timezone`,
and it returns kW on `window.rows()`. Each local day's minute-of-day profile,
Elexon's or the household model's, is placed by wall-clock minute: a
spring-forward day skips 01:00-01:59 and an autumn day plays it twice. The
0.5.0 tag lays the days end to end, 1,440 minutes each, from the window's first
midnight. So a day whose clock is an hour ahead of the first day's, on summer
time after a winter start, is laid an hour late, and one an hour behind, on
winter time after a summer start, an hour early; and a window whose last day is
the March change day ends at 00:59 the next day, one whose last day is the
October change day at 22:59. Every run spanning a clock change moves. A row
takes the mean of the minutes it spans, and a cadence that is not whole minutes
raises `ValueError` naming it, as does any cadence but one minute with an
`ev_config`. Each day's energy is the annual consumption ×
`SEASONAL_FACTORS[month]` / the factors summed over the days of its calendar
year, so a whole calendar year delivers `annual_consumption_kwh` exactly, on
both paths: demand rises to 3,400.0 kWh for 2023, 2.3% above the tag's 3,325.0,
and to 3,400.0 for 2024, 1.9% above the tag's 3,336.2. `simulate_home`'s rows
run from its first local date's midnight to the midnight after its last, at one
minute on the location's clock; a tz-aware date in another zone is read as its
date on that clock, and a naive one as already on it. So a run whose last day
is the March change day ends at 23:59 on it, and its `SimulationResults.window`
ends that day. `generate_load_profile` raises `ValueError` for a household
model whose days have no energy: the Elexon fallback the task 906 line
describes covers only a model that raises or gives a day of another length.
Consumers re-baseline demand figures when they re-pin. Consumers pass `generate_load_profile` a `window`, a `timebase.SimulationWindow`, in place of `start_date`, `end_date` and `timezone` when they re-pin.

**Task 895.** `generate_ev_charging_profile` now takes
`(config, window, *, tariff=None, generation_kw=None)`, where `window`, a
`timebase.SimulationWindow`, replaces `start_date`, `end_date` and `timezone`,
and `generation_kw` is an `ev.RowWeights`, a callable giving the home's PV
generation in kW on the rows it is given; it returns kW on `window.rows()`.
`generate_load_profile` loses the `ev_config` parameter the task 894 line
describes and the `tariff` the task 842 line adds, and returns the household
alone; `simulate_home` now adds the EV's charging to it. Each stay now runs from
`arrival_hour` to `departure_hour` on the wall clock on both sides of a clock
change: a 7 kW, 35 kWh `"none"` EV home from 18:00 to 07:00 starts at 18:00 BST
on 2024-03-31, where the 0.5.0 tag started at 19:00. This supersedes the task
842 line's clock-change caveat. Each stay that fits its charge delivers exactly
`required_charge_kwh`, on whole rows at the charger's rating and then one row at
the fraction of it the rest needs: a 3.6 kW, 30 kWh EV home from 08:00 to 17:00
charges 500 one-minute rows and 30.0 kWh, where the tag charges 501 and 30.06. A
stay the clocks shorten below its charge charges on every one of its rows. The
first morning now holds the session of the stay from the evening before the
run: a one-day run on 2024-06-21 of a 7 kW, 35 kWh `"off_peak"` EV home from
18:00 to 08:00 on Economy 7 charges 35.0 kWh at 00:30–05:29, where the tag
charged 0.0. A `"solar"` EV now charges in the run of its stay with the most of
the home's own PV generation, not its surplus, in place of the 10:00–16:00
window the task 708 line describes, and `generate_ev_charging_profile` refuses
a `"solar"` EV without `generation_kw` with a `ConfigurationError` naming
`smart_charging_mode 'solar'`. `EVConfig` now holds `charger_type` and
`smart_charging_mode` as `EVChargerType` and `SmartChargingMode` members, both
now `StrEnum`, so each still equals, hashes, formats and JSON-encodes as its
string, but its `type()` and `repr` differ, and `str(EVChargerType.FAST)` is now
`'7kW'`, not `'EVChargerType.FAST'`. `EVChargerType.power_kw` is new. An unknown
value is refused with `ConfigurationError`, a `ValueError`, e.g.
"charger_type must be one of 3.6kW, 7kW, 22kW, got '50kW'", and likewise for
`smart_charging_mode`, where the tag says "Charger type must be one of [...]".
The demand that `simulate_home` and `FleetRunner.simulate` return changes for
every EV home, and so do the figures built on it. Consumers pass a window, add the EV's
charging to the household themselves where they called `generate_load_profile`
with an EV, give a `"solar"` EV its generation, and re-baseline EV demand
figures, when they re-pin.

**Task 897.** `SimulationResults` carries each load within demand by name. Its new last
field, `additional_loads`, maps `solar_challenge.demand.LoadKind` (`HOUSEHOLD`,
`HEAT_PUMP`, `EV`; a key may also be the kind's value, such as `'ev'`) to each
load besides the household's, in kW on demand's rows. `to_dataframe` and the
CSV exports write each under its kind's column, `heat_pump_load_kw` as before
and the new optional `ev_load_kw`, after the other series, and `from_dataframe`
reads them back; an EV home's `demand_kw` is unchanged. The new `loads`
property holds every load, the household's being demand less the additional
loads. `heat_pump_load` stays, as one series with
`additional_loads[LoadKind.HEAT_PUMP]`. Construction now refuses, with
`SeriesRefused`, a household entry, a load off demand's rows, a
`heat_pump_load` that differs from `additional_loads['heat_pump']`, and
additional loads that exceed demand by more than 1e-9 kW in a row, naming that
row's timestamp. A `dataclasses.replace` that changes or removes
`heat_pump_load` on results with a heat pump must therefore also pass
`additional_loads`: a different series is refused, and `heat_pump_load=None`
alone no longer removes the heat pump.
`SummaryStatistics` gains `load_energy_kwh`, each load's energy in kWh by
`LoadKind`, summing to `total_demand_kwh` (`{}` for a run stored before this
change), and `load_share(kind)`; it refuses a `total_heat_pump_load_kwh` that
differs from `load_energy_kwh['heat_pump']` when both are set. A heat pump's
refusal of weather that is not one year of hourly rows no longer names the
home's location: it opens "the weather's air temperature has". Consumers read
the loads by kind when they re-pin; a hand-built `SimulationResults` whose heat
pump exceeds its demand must raise its demand to include it; and a summary
that keeps its own copy of the heat-pump total keeps it equal to
`load_energy_kwh['heat_pump']`.

**Task 898.** `compute_grid_charge_power_kw` measures the gap to `target_soc_kwh` from the
SOC after the step's PV charge, `battery_soc_kwh + min(pv_charge_power_kw,
max_charge_kw)` × the step's hours × `charge_efficiency`, where the 0.5.0 tag
measures it from `battery_soc_kwh` itself. So `battery_soc_kwh` is the SOC
before that PV charge. `TOUOptimizedStrategy` and `PeakShavingStrategy` no
longer grid-charge past their target in a cheap minute in which PV also charges
the battery: under `simulate_timestep`, an Economy 10 minute at 14:00 with
1.5 kW of PV excess, into a 10 kWh battery at 5.98 kWh with a 6.0 kWh target,
stores no grid energy, where the tag stores 0.01625 kWh. A
`TOUOptimizedStrategy` clocked to the tariff's expensive hours grid-charges what
`simulate_timestep_tou` does: 5.045223 kWh over
docs/prds/one-dispatch-engine.md §2.2's morning-drain Economy 10 day, against
the tag's 5.047494. This change leaves `simulate_timestep_tou`'s results as
they were. A direct caller of `compute_grid_charge_power_kw` that passed the
SOC after the step's PV charge passes the SOC before it when it re-pins; no
other change is needed.

**Task 901.** `SimulationResults` has no `heat_pump_load` field, so
`SimulationResults(..., heat_pump_load=s)` and
`dataclasses.replace(results, heat_pump_load=s)` raise `TypeError`, and
`heat_pump_load` is gone from its frozen signature. Pass a heat pump's load as
`additional_loads[LoadKind.HEAT_PUMP]`, and read it there or from
`results.loads[LoadKind.HEAT_PUMP]`. The fields after `strategy_name`,
`grid_charge_cost` onwards, move one place forward, so pass them by keyword.
`SummaryStatistics` has no `total_heat_pump_load_kwh`, `peak_heat_pump_load_kw`
or `heat_pump_load_ratio` field, and passing any of them raises `TypeError`.
Read a heat pump's energy from `load_energy_kwh[LoadKind.HEAT_PUMP]`, its share
of the demand from `load_share(LoadKind.HEAT_PUMP)`, and its peak from the
run's `results.loads[LoadKind.HEAT_PUMP].max()`. `load_energy_kwh` is now a
required keyword-only field with no default, so `SummaryStatistics(...)`
without it raises `TypeError` naming it, and a value passed by position where
it is declared raises `TypeError` for one positional argument too many. The fields after `strategy_name` move three places
forward, so pass them by keyword too. `EVConfig.charger_type` is annotated
`EVChargerType`, and `smart_charging_mode` is annotated `SmartChargingMode`,
its default `SmartChargingMode.NONE`. Each holds its member, and a string naming
a member is still read as that member at construction, so a caller under mypy
strict passes the members. `EVChargerType` and `SmartChargingMode` now appear in
the frozen surface. A dashboard store at schema version 9 is refused until
`solar-challenge web migrate` brings it to version 10. That step brings each
stored run to run-document format 10. Every stored `SummaryStatistics` document
without a `load_energy_kwh` gains `{household: total_demand_kwh − heat pump,
heat_pump: heat pump}`, the heat pump omitted when its total was null, and the
three heat-pump keys are dropped. That covers a home run's `summary.json` and
its runs row, and each of a fleet run's `homes/home_<i>_summary.json`. A summary
that already holds a `load_energy_kwh` keeps it, and the step reports a dropped
`total_heat_pump_load_kwh` only when that mapping does not hold it. When they
re-pin, library callers move off the retired names as above and pass
`load_energy_kwh` by keyword, and dashboards run `solar-challenge web migrate`.

**Task 902.** `DispatchDecision` refuses a `charge_kw`, `discharge_kw` or `grid_charge_kw`
that is NaN or infinite, as well as a negative one, raising `ValueError` naming
the field and its value, as in `charge_kw must be non-negative and finite, got
nan kW`. The 0.5.0 tag constructs a decision with a NaN or infinite power, and
words a negative one as `Charge power must be non-negative, got -1.0 kW`.
`simulate_timestep` and `simulate_timestep_tou` raise `ValueError` for a
`generation_kw` or `demand_kw` that is negative, NaN or infinite, with or
without a battery, after the timestep check and before any dispatch strategy or
battery is given it, in the words the built-in strategies use, as in
`Generation must be non-negative and finite, got inf kW`. The tag returns such
a step without a battery, and under a dispatch strategy of the consumer's own
that checks none of its inputs, which it calls with the power: an infinite
power gives an infinite export or import, as `simulate_timestep(math.inf, 1.0,
None)` returns `grid_export=inf`, a NaN one NaN flows and a negative one
negative flows; since the tag, the task 590 line's check refuses the negative
and NaN flows, naming the flow rather than the power. `simulate_timestep` also
raises `ValueError` before the battery moves, leaving it unchanged, when its
strategy's decision asks for a `charge_kw` above the step's PV excess,
`max(0, generation_kw - demand_kw)`, a `discharge_kw` above its shortfall,
`max(0, demand_kw - generation_kw)`, or a `grid_charge_kw` above the headroom
the battery's `max_charge_kw` leaves after `charge_kw`. It names the strategy
and, for each such power, the field, its value and its limit, as in `Dispatch
strategy 'mine' decided more than the step allows: charge_kw=2.5 kW is above
0.0 kW, the step's PV excess`. A `charge_kw` above `max_charge_kw` is still
accepted, as the PV offer the battery clamps, and no built-in strategy's
decision is refused. On the tag, an hour of `DispatchDecision(5.0, 0.0, 5.0)`
at 10 kW of PV and no demand stores 4.875 kWh in a 10 kWh battery with a
2.5 kW charge limit, and `validate_energy_balance` passes the step; an hour of
`DispatchDecision(2.5, 0.0)` with no PV and no demand stores 2.4375 kWh from
nowhere; and an hour of `DispatchDecision(0.0, 2.5)` against 1.0 kW of demand
discharges 2.5 kWh. `validate_energy_balance` refuses those two, the last as
`Energy balance violated: in=0.000000 kWh, out=-1.500000 kWh`, and without it
nothing does. `Battery.charge` and `Battery.discharge` refuse an infinite
`power_kw`, which the task 633 line says is still accepted at the battery's
maximum rate, and their refusal of a power now reads `Charge power must be
non-negative and finite, got inf kW`. A dispatch strategy of the consumer's own
whose decisions keep within these bounds needs no change when they re-pin; one
that asked the battery for more now raises where the tag charged the battery
from nowhere or lost energy; and a caller that passed `inf` to
`Battery.charge` or `Battery.discharge` passes the battery's `max_charge_kw` or
`max_discharge_kw` instead.

**Task 904.** A home whose `dispatch_strategy` is `'tou_optimized'` and whose battery names
no strategy of its own now runs `TOUOptimizedStrategy` on its tariff's clock
through `simulate_timestep`, where the 0.5.0 tag runs it through
`simulate_timestep_tou`'s own dispatch; its flows equal that route's within
1e-9 kWh in every minute, and its results still name `'tou_optimized'`.
`simulate_timestep_tou` keeps its signature and now returns
`simulate_timestep(generation_kw, demand_kw, battery, timestep_minutes,
timestamp, TOUOptimizedStrategy(tariff=tariff), tariff=tariff)`; it is retired
at the next release. Building such a home with a battery and no
`tariff_config`, which task 787's note says is refused, raises the factory's
refusal of a TOU strategy with no clock, "dispatch strategy 'tou_optimized'
without peak_hours charges and discharges the battery on the tariff's clock,
but there is no tariff; add a tariff or set peak_hours", in place of the
wording 787 gives it ("dispatch_strategy 'tou_optimized' dispatches the battery
by the tariff's rates, but there is no tariff; ..."). A home with no battery
that asks for `'tou_optimized'` without a `tariff_config` keeps its flows, and
its results' `strategy_name` is now `'tou_optimized'`, where the tag's is
`'self_consumption'`. When they re-pin, callers of
`simulate_timestep_tou` move to the `simulate_timestep` call it returns before
the next release, and code matching the refusal's text matches the new
wording; nothing else changes.

**Task 905.** `simulate_timestep_tou`, which the 0.5.0 tag exports from `solar_challenge`
and `solar_challenge.flow`, is retired: importing it, `from solar_challenge
import simulate_timestep_tou` or `from solar_challenge.flow import
simulate_timestep_tou`, raises `ImportError`, and reading it as an attribute,
`solar_challenge.simulate_timestep_tou` or
`solar_challenge.flow.simulate_timestep_tou`, raises `AttributeError`. Since
task 904 it returned `simulate_timestep(generation_kw, demand_kw, battery,
timestep_minutes, timestamp, TOUOptimizedStrategy(tariff=tariff),
tariff=tariff)`, so that call gives its flows exactly, and what the other notes
since the tag say of `simulate_timestep_tou`'s flows and refusals holds for
that call. When they re-pin, consumers replace each
`simulate_timestep_tou(generation_kw, demand_kw, battery, timestamp, tariff,
timestep_minutes)` with `simulate_timestep(generation_kw, demand_kw, battery,
timestep_minutes, timestamp, strategy=TOUOptimizedStrategy(tariff=tariff),
tariff=tariff)`, passing one tariff to both and the timestep fourth.

**Task 908.** `FleetConfig.create_uniform` and `FleetConfig.create_heterogeneous` gain a
last, keyword-only parameter, `seed: int | None = None`. Given a seed, home i's
load seed is seed + i, so a seeded fleet's demand repeats run to run and
differs home to home; without one every home's load is unseeded, as on the
0.5.0 tag. The rule is the new `solar_challenge.fleet.fleet_home_seed`, which
`generate_homes_from_distribution` now calls too, so a scenario's
`fleet_distribution` seeds its homes as on the tag. `create_uniform` now
refuses a `load_config` whose `seed` is set with `ConfigurationError`, naming
`load_config.seed` and its value, where on the tag every home shares that seed
and so draws one identical profile. Consumers need no change when they re-pin
unless they pass `create_uniform` a seeded `load_config`; those pass that seed
as `seed=` instead, and home i then gets seed + i.

**Task 909.** building a `CommunityConfig` whose `community_battery` sets `grid_charging`
raises `ConfigurationError` under self-consumption dispatch, which a battery
whose `dispatch_strategy` names no strategy runs, or when `billing` sets no
`tariff`, where the 0.5.0 tag accepts it and never charges the battery from the
grid. `simulate_community` dispatches the community battery by the strategy its
`dispatch_strategy` names, built by `dispatch.build_dispatch_strategy`, with
`billing.tariff` as its tariff, where the tag always runs self-consumption; a
community battery that sets neither `dispatch_strategy` nor `grid_charging`
dispatches as before. A `CommunityBillingConfig` that leaves `tariff` or
`seg_rate_pence_per_kwh` unset makes `simulate_community` emit one
`UserWarning`, naming each unset input and the three billing fields that stay
`None`: `baseline_net_cost_gbp`, `community_net_cost_gbp` and
`community_savings_gbp`; the tag prices nothing and gives no warning.
`solar-challenge fleet run` reads the `community:` block before it simulates, so
a block it refuses exits before any home is simulated. Consumers that re-pin
drop `grid_charging` from a self-consumption community battery, or give it a
grid-charging `dispatch_strategy` and a `billing.tariff`. The platform needs no
change, since it builds no community.

**Task 910.** `FleetConfig`, `FleetResults` and `CommunityResults` are frozen, and
`FleetConfig.homes`, `FleetResults.per_home_results` and
`FleetResults.home_configs` are tuples. A list passed for one of them is stored
as a tuple, so building them with lists still works at run time, and a fleet's
results no longer share its configuration's list of homes. `FleetResults`
checks that it holds at least one home and one `HomeConfig` per home's results
when it is built, and only then: the fields cannot change afterwards.
`simulate_community` sets `baseline_net_cost_gbp`, `community_net_cost_gbp` and
`community_savings_gbp` on the one `CommunityResults` it builds, rather than
assigning them afterwards. Assigning a field of any of the three, such as
`results.home_configs = ()` or `community.community_savings_gbp = 0.0`, raises
`dataclasses.FrozenInstanceError`, and appending to a tuple field, such as
`results.home_configs.append(home)`, raises `AttributeError`; the 0.5.0 tag
accepts both. Consumers that re-pin see the fleet fields typed as tuples: they
pass tuples to keep a type checker green (lists still work at run time), and
build a changed fleet or result with `dataclasses.replace(...)` instead of
assigning or appending.

**Task 912.** `CommunityConfig` has no `sharing_mode` field. `sharing_mode` is a read-only
property derived from `community_battery`: `"community_battery"` when it is
set and `"p2p"` when it is `None`, so the mode and the battery can no longer
disagree. The constructor takes `community_battery` and `billing` by keyword
only, so `CommunityConfig("p2p")` and `CommunityConfig(sharing_mode=...)`
raise `TypeError`. A positional class pattern such as
`case CommunityConfig(mode):`, which bound `sharing_mode` under the 0.5.0 tag,
now raises `TypeError` when it is matched, since the class takes no positional
sub-patterns; match by keyword, e.g.
`case CommunityConfig(community_battery=battery):`. The refusals of an unknown
mode, of a `"p2p"` config with a community battery and of a
`"community_battery"` config without one are gone, since none of those configs
can be written. `community.SharingMode`, `Literal["p2p", "community_battery"]`,
types `CommunityResults.sharing_mode`, still a field that `simulate_community`
sets from the config, and `output.CommunityMetrics.sharing_mode`, where the
0.5.0 tag annotates the latter `str`. A `community:` block that sets
`sharing_mode`, null or not, is refused naming `community.sharing_mode`, and
`community: {}` is a peer-to-peer community, where the tag requires the key.
When they re-pin, scenario authors delete `sharing_mode:` from each
`community:` block, and library callers drop the `sharing_mode` argument and
pass `community_battery` and `billing` by keyword.

**Task 914.** `HeatPumpConfig.thermal_capacity_kw` gains
the default `8.0` and `EVConfig.arrival_hour` the default `18`; on the 0.5.0
tag both are required. Code that passes them needs no change when it re-pins.
The scenario grammar changes with them. A home's `heat_pump:` block may leave
out `thermal_capacity_kw`, and its `ev:` block `arrival_hour`; the tag refuses
both. A block without `heat_pump_type` or `charger_type` is refused naming its
path, e.g. `home.ev.charger_type`. A key written as null in a `pv:`,
`battery:`, `load:`, `heat_pump:`, `ev:` or `location:` block, or a home's
`name: null`, reads as absent and takes the default; on the tag the null is
handed on, so `pv: {tilt: null}` and a null `annual_heat_demand_kwh` raise a
raw `TypeError`, `load: {use_stochastic: null}` selects the deterministic
profile, and a null name is held as `None`. The `heat_pump:` and `ev:` blocks
pass their values as written, as `pv:`, `battery:` and `load:` already do,
where the tag converts them with `float()`, `int()` and `str()`: a fractional
EV `arrival_hour` now reaches `EVConfig`, which the tag runs truncated, and
simulating the home raises `IndexError` until `EVConfig` refuses it (task
861). A value of a type a block's dataclass cannot use, such as a quoted
number, which the tag's `heat_pump:` and `ev:` blocks convert, is refused as a
`ConfigurationError` naming the block, e.g. `home.heat_pump`; on the tag it
raises a raw `TypeError` in a `pv:`, `battery:`, `load:` or `location:` block.
`system_losses` is a `pv:` key and `scenario_writer` writes it: a
`HomeConfig` with `system_losses=0.05` exported as scenario YAML loads back as
0.05, where the tag refuses the key and its export loads back as the default
0.14076. An export writes every key of each component block, an unset one as
null, a battery's unset `efficiency` included. Consumers whose scenario files
rely on a null meaning `None`, or on those conversions, re-check them when they
re-pin. When they re-pin, consumers give each `heat_pump:` block its `heat_pump_type` and each `ev:` block its `charger_type`, write a quoted number as a number, and re-check any key written as null, which now reads as absent and takes the default.

**Task 919.** a `fleet_distribution:` block's
`heat_pump.heat_pump_type` given as a `shuffled_pool`, or as any spec other
than a `weighted_discrete` or a bare type, is now drawn: a pool hands each home
the type it draws, a null being no heat pump. The tag gives every home of such a
fleet no heat pump. Only such fleets' generated homes change.
`solar_challenge.config`'s `PVDistributionConfig`, `BatteryDistributionConfig`,
`LoadDistributionConfig`, `HeatPumpDistributionConfig` and `EVDistributionConfig`
are replaced by one `ComponentDistribution(draws, settings)`; none was in
`__all__` or the frozen surface, and `FleetDistributionConfig` keeps its field
names, its `load` now defaulting to an empty distribution. A
`ComponentDistribution` holds its draws and settings read-only, and pickles and
deep-copies as the classes it replaces did, but `dataclasses.asdict` of a
`FleetDistributionConfig` holding one raises `TypeError`, where the tag's classes
allow it. The component tables
(`PV_BLOCK` … `EV_BLOCK`) state each block's fleet keys, so a block accepts every
key of its component's home block except `name` (and the load's `seed`, the
fleet's seed plus the home's index): the PV's `temperature_coefficient`,
`inverter_capacity_kw` and `system_losses` and the battery's SOC limits,
efficiencies and ageing can now be drawn, where the tag ignores them. A
`heat_pump_type` or `charger_type` may be one of its choices given bare, and a
`heat_pump_type` outside `heat_pump.HEAT_PUMP_TYPES` is refused when the block is
read, as a charger type outside `ev.CHARGER_TYPES` is since task 792. A field a fleet
does not draw, or draws null, takes its dataclass's default. A component's
refusal of what a home drew is re-raised as a `ConfigurationError` naming
`fleet_distribution.<component>` and the home's number, e.g.
`fleet_distribution.load, home 1: household_occupants must be between 1 and 10,
got 0` for a 0-occupant draw, which the tag reads as 3, and a null `pv.capacity_kw` draw is refused naming its path and the home,
where the tag refuses a PV capacity that is null or not positive with `PV
capacity must be positive`. A `proportional_to` may take any field its home drew
earlier as its source; a source the home has not drawn, or that drew a choice,
is refused when the homes are generated, where the tag gives a battery or heat
pump field its default for a source other than `pv.capacity_kw`. A home draws no
field of a component it has none of, past the presence field, so a source there
is refused at the first home without that component, and a fleet whose homes all
have it generates. A `proportional_to` on a count gives a whole number, as a
normal or uniform draw there does: `household_occupants` rounded, an EV hour
truncated; the tag refuses one there with `Unknown distribution type`. A null setting
(`use_stochastic`, `smart_charging_mode`, `grid_charging`, `dispatch_strategy`)
reads as absent. Every other generated fleet is unchanged, home for home. Consumers that build `PVDistributionConfig`, `BatteryDistributionConfig`, `LoadDistributionConfig`, `HeatPumpDistributionConfig` or `EVDistributionConfig` build one `ComponentDistribution(draws, settings)` instead, and fix any fleet input now refused.

**Task 921.** `FleetDistributionConfig` is frozen: assigning to one of its fields, such as
`fleet.n_homes = 4`, raises `dataclasses.FrozenInstanceError`, where the 0.5.0
tag accepts the assignment; a changed fleet is made with `dataclasses.replace`,
which checks it as construction does. A fleet built in code is now refused as it
is built for what the parser refuses in a `fleet_distribution:` block, in the
parser's words: a key outside its component's fleet rows, a required key its
component does not draw (`pv.capacity_kw`, `battery.capacity_kwh` or
`ev.charger_type`), and a heat-pump or charger type outside its choices. It is
also refused for a SETTING or FLAG key in a `ComponentDistribution`'s draws, or a
drawn key in its settings, e.g. `fleet_distribution.load.use_stochastic is a flag
key, which a ComponentDistribution holds in its settings, not its draws`, and for
a spec its field's kind does not draw, such as a bare string on a number field.
Built or read, a fleet is now refused for a string among a number or count
field's listed values, e.g. `Invalid fleet_distribution.pv.tilt value '35'; valid
values: null or a number`, and for a `proportional_to` whose source is not a
number or count field drawn earlier for every home that draws it: one `pv` or
`load` draws, since each home draws its PV, battery, load, heat pump and EV in
that order, or one the dependent's own component draws before it. Task 919's note
says such a source is refused when the homes are generated, and that a fleet
whose homes all have the source's component generates; such a fleet is now
refused as it is read, e.g. `Invalid fleet_distribution.heat_pump.thermal_capacity_kw
source 'battery.max_charge_kw'; valid sources: a number or count field drawn
earlier for every home that draws it, one of ['pv.capacity_kw']` for a heat pump
sized by a battery's charge rate, so whether a fleet is refused no longer depends
on what it draws. `validate config` and the dashboard's YAML import report these
refusals, and every fleet they do not refuse generates the same homes, home for
home. On re-pin: change a fleet with `dataclasses.replace` instead of assigning
its fields, keep a component's SETTING and FLAG keys in its `settings`, and
expect these refusals where the fleet is built or read rather than from
`generate_homes_from_distribution`.

**Task 922.** `solar_challenge.home` gains `RunPricing`, a frozen class outside `__all__`
that records how `simulate_home` priced a run's grid flows. Its
`import_tariff_mean_rate_gbp_per_kwh` is the import tariff's rate in £/kWh,
time-weighted over the run's rows, and its `seg_rate_pence_per_kwh` is the SEG
rate in pence/kWh the run's export earned. Each is None when no tariff, or no
SEG tariff, priced its flow; a £0 tariff is 0.0, and priced. Construction
raises `ConfigurationError`, a `ValueError`, naming the field and the value,
for a set rate that is negative, not finite or a boolean. `SimulationResults`
and `SummaryStatistics` each gain a last field, `pricing`, defaulting to None.
`simulate_home` always sets its results' `pricing`, `calculate_summary` copies
it into the summary, and `SimulationResults.from_dataframe` leaves it None,
since a frame holds no rates. `to_dataframe` writes no column for it. A stored
summary keeps its `pricing`, and one stored before this change loads with None.
The 0.5.0 tag has none of these. Finance prices a summary's grid flows from its
`pricing` rather than inferring it from pounds: `householder_bill` and
`bill_distribution` raise `ValueError` for a summary whose `pricing` is None,
and `project_multi_year` and `solve_cost_recovery_rate` for a `simulate` whose
results record none, naming `calculate_summary`, where the tag billed them. A
home on a £0 tariff is billed £0 of import with no
warning, where the tag billed it at the retail rate with the "no tariff
configured" `UserWarning`; that warning now fires for every home no tariff
priced, whatever it imported. With `self_consumption_override` set, a home
whose run imported nothing is billed its import at its own tariff's
time-weighted mean rate rather than at retail, and the CBS earns each home's
override export at the SEG rate its run was priced at, whatever the simulated
export, so an override home that exported nothing no longer earns £0. Finance
no longer reads `total_export_revenue_gbp` or `seg_revenue_gbp`. It prices
that SEG income with `seg.calculate_seg_revenue`, as `simulate_home` and
`calculate_summary` price SEG, so `project_multi_year` and
`solve_cost_recovery_rate` raise that function's `ValueError`, naming the
export, for a `simulate` whose results give a home a negative billed export at
a SEG rate. When they
re-pin, consumers that build a `SummaryStatistics` by hand for finance give it
`pricing=RunPricing(...)`, the rates its run was priced at, as they give it
`window`, and an injected `simulate` that builds its own `SimulationResults`
sets their `pricing` the same way.

**Task 925.** `solar_challenge.finance` gains public names outside `__all__`: `AnnualPhysics`,
the frozen dataclass of a summary's totals scaled to its window's year, beside
the window and the run's `RunPricing`, with `scale`, the window's
`annualisation_scale`, as a property, and `annualise(summary)`, which builds it;
`basis_c_own_use_kwh(summary)`, a summary's demand − import over its window, 0.0
with a `UserWarning` when the import is above the demand; `OwnUseBasis`, whose
members are `SIMULATED` and `OVERRIDE`; `HomeLedger`, the frozen dataclass of
one home's year as the CBS bills it, whose construction raises `ValueError`
naming the invariant and every value in it for a year that breaks L1 (every
figure finite and >= 0), L2 (own-use at most demand), L3 (own-use and import
cover demand) or, on the `OVERRIDE` basis, L4 (own-use and import are demand,
own-use and export are generation), L2-L4 to a relative 1e-12, and naming
`own_use_capped` for a capped year that is not on the `OVERRIDE` basis or
whose own-use is not its demand;
`home_ledger(physics, finance, *, simulated_own_use_kwh=None)`, its one
producer, which holds every pricing rule and warns about nothing; and the
cash-flow maths `annuity_payment(principal, rate, n_years)`, which raises
`ValueError` naming the argument for a term under one year or a rate that is
not finite or is at or below -1, `npv(rate, cashflows)` and `irr(cashflows)`,
which is nan when the rate of return is undefined. The 0.5.0 tag has none of
these. `householder_bill` and `project_multi_year` each read one `home_ledger`
per home. `householder_bill`
raises `ValueError` naming the ledger's invariant for an own-use outside 0 to
the summary's demand, with or without the override, before it scales it: L1
for one below 0 or not finite, naming `annual_self_consumption_kwh`, and L2 for
one above the demand, naming it and the summary's `total_demand_kwh`, each as
passed, in place of the message that the task 782 line describes; and L3,
with no override, for one that with the summary's import falls short of its
demand, which the tag bills, naming the ledger's demand, own-use and import
scaled to the window's year. With
`self_consumption_override` set, `project_multi_year`'s
`YearPoint.fleet_export_kwh` and `fleet_import_kwh` are the override's split,
generation − own-use and demand − own-use summed over the homes, where the tag
reports the simulated flows. `project_multi_year`, and so
`solve_cost_recovery_rate`, refuses a home's NaN or infinite own-use, export or
import with the ledger's L1 message, naming each figure it refuses, rather than
with the message naming the simulated age that it still gives for the
aggregates a ledger does not hold. It no longer warns "Basis-C own-use is
negative" for a home whose import is above its demand, whose own-use it still
projects as 0. `MultiYearCurve.interp_error_estimate` measures export and
import as a percentage of the age-0 fleet generation and demand, where the
0.5.0 tag measures them against their own age-0 values, so
`project_multi_year` can sample different ages. When they re-pin, consumers
that pass `householder_bill` an own-use of their own with no override make it
cover the summary's demand together with the summary's import, as basis C and
B-style self-consumption do, and match a refusal of it on the invariant it
names.

**Task 928.** `YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `MAX_NODES`, `project_multi_year`, `project_economics` and `spreadsheet_revenue_curve` move from `solar_challenge.finance` to the new module `solar_challenge.projection`, whose import loads pvlib. `project_economics(curve, fleet, finance)` takes a `ScenarioFleet` where the 0.5.0 tag takes the `ScenarioConfig`: `scenario_fleet(scenario)` gives it, the scenario's `simulated_homes()` over its `simulation_bounds()`. `solar_challenge.projection` also defines `ScenarioFleet`, whose construction raises `ValueError` naming `homes` when there are none, and `scenario_fleet`. `solar_challenge.finance` gains `one_window(summaries)`, outside `__all__`, the one window summaries billed or projected together cover, raising `ValueError` naming the first summary over another window. The move changes neither the form nor the result of the frozen `solar_challenge.solve_cost_recovery_rate`; task 939's note says where it resolves. `import solar_challenge.finance` still loads neither pvlib nor `solar_challenge.fleet`. The platform (solar-challenge-platform 45ecca2) imports none of the moved names: it imports only the frozen `solar_challenge.solve_cost_recovery_rate`. When they re-pin, consumers import the moved names from `solar_challenge.projection` and pass `project_economics` `scenario_fleet(scenario)`.

**Task 934.** `CostRecoverySolution` refuses, when it is built, a `feasible` other than
`binding != "infeasible_above_retail"`, and a `representative_outlay_gbp`,
`saving_vs_baseline_gbp` or `saving_pct` that is not `==` its
`outlay.representative`'s `total_outlay_gbp`, `saving_vs_baseline_gbp` or
`saving_pct`. Each refusal is a `ValueError` naming both values. The 0.5.0 tag
builds such a solution. `solve_cost_recovery_rate` never builds one, so no
value it returns changes. `optimize.ConfigResult`'s
`representative_outlay_gbp`, `solved_own_use_rate_pence_per_kwh`,
`surplus_at_solved_gbp`, `feasible` and `binding` are now read-only properties
over its `solution`, not constructor parameters, and `optimize.feasible_split`
partitions on `feasible`; `optimize configs` output does not change. When they
re-pin, consumers that build a `CostRecoverySolution` by hand copy those three
figures from `outlay.representative` and set `feasible` to
`binding != "infeasible_above_retail"`; consumers that build a `ConfigResult`
drop those five keywords; consumers that only read either class need no
change.

**Task 939.** `solar_challenge.solve_cost_recovery_rate` is the function
`solar_challenge.projection` defines, its `__module__`
`solar_challenge.projection`, where the 0.5.0 tag defines it in
`solar_challenge.finance`; the move changes neither its form, which task 892's
note gives, nor its result.
`solar_challenge.finance.solve_cost_recovery_rate` is retired, so importing it
from `solar_challenge.finance` raises `ImportError`. A first access of
`solar_challenge.solve_cost_recovery_rate` now loads
`solar_challenge.projection`, and so pvlib; at the 0.5.0 tag it loaded
`solar_challenge.finance`, which imports nothing that loads pvlib. The warnings
the solve's projection collects and shows once, such as one naming an event
window the simulated period never enters, name the consumer's line that calls
the solve. When they re-pin, consumers who import the solve from
`solar_challenge.finance` import it from `solar_challenge` or
`solar_challenge.projection`. Consumers who import it from `solar_challenge`,
as the platform (solar-challenge-platform 45ecca2) does, change nothing beyond
the pvlib import on the first access.

**Task 941.** `BillDistribution.per_home_net_bill_gbp` is renamed
`per_home_total_outlay_gbp`: the field has always held each home's
`total_outlay_gbp`, not a net bill. No dual field survives: the old keyword
raises `TypeError` on construction and the old attribute no longer exists.
`bill_distribution` fills the new field with the same tuple. Consumers rename
the keyword and the attribute when they re-pin.

**Task 945.** `solar_challenge.config.run_parameter_sweep`,
`ParameterSweepConfig` and `SweepResult` are removed. None was in `__all__` or
had a package caller; sweeps run through `fleet.FleetRunner.simulate_each`,
`optimize.run_sweep` and the web's sweep endpoint.

**Task 946.** The scenario grammar's block readers `parse_home_block`, `parse_location_block`,
`parse_tariff_config`, `parse_dispatch_strategy_config`, `parse_seg_rate` and
`parse_finance_config`, its component block tables `PV_BLOCK`, `BATTERY_BLOCK`,
`LOAD_BLOCK`, `HEAT_PUMP_BLOCK`, `EV_BLOCK` and `LOCATION_BLOCK`, and the types
those tables are built from, `ComponentBlock`, `SubBlock`, `FieldKind` and
`FleetField`, move from `solar_challenge.config` to the new
`solar_challenge.scenario_blocks`. Importing that module loads neither
`solar_challenge.config` nor the fleet grammar. Every one of these names is new
since the 0.5.0 tag, whose block readers were private. `solar_challenge.config`
still binds at runtime the names it uses itself, which is every name listed here
except `parse_dispatch_strategy_config`, `LOCATION_BLOCK` and `SubBlock`, but it
no longer exports them to `mypy --strict`. Reading `parse_dispatch_strategy_config`,
`LOCATION_BLOCK` or `SubBlock` from `solar_challenge.config` raises
`AttributeError`. `solar_challenge.config` also no longer binds names that other
modules define and that it only imported: `GridChargeConfig`,
`DispatchStrategyConfig` and `STRATEGY_CONFIG_BY_TYPE` (`solar_challenge.dispatch`),
`TariffPeriod` (`solar_challenge.tariff`), `EventWindow` and
`GridServicesEventsConfig` (`solar_challenge.gridservices`),
`CommunityBillingConfig` (`solar_challenge.community`), `HEAT_PUMP_TYPES`
(`solar_challenge.heat_pump`), `CHARGER_TYPES` (`solar_challenge.ev`),
`has_battery` (`solar_challenge.battery`) and `resolve_seg_tariff`
(`solar_challenge.seg`). Importing any of them from `solar_challenge.config`
raises `ImportError`, and reading one as an attribute raises `AttributeError`.
Six of them import from `solar_challenge.config` on the 0.5.0 tag, which defines
`GridChargeConfig` and `DispatchStrategyConfig` and imports `TariffPeriod`,
`EventWindow`, `GridServicesEventsConfig` and `CommunityBillingConfig`; the
other five are new since the tag. These lines supersede the task 786 line that
`solar_challenge.config` still binds `GridChargeConfig` at runtime, so code that
imports it from there keeps running. No parsed value changes, and no message
does either. When they re-pin, consumers import each moved name from
`solar_challenge.scenario_blocks`, and each name `solar_challenge.config` only
imported from the module named beside it. The platform changes
`optimiser/planner.py` to `from solar_challenge.dispatch import GridChargeConfig`;
its import of `SimulationPeriod` from `solar_challenge.config`, which still
defines it, needs no change.

**Task 947.** The fleet grammar's distribution types `WeightedDiscreteDistribution`,
`NormalDistribution`, `UniformDistribution`, `ShuffledPoolDistribution` and
`ProportionalDistribution`, and `SweepSpec`, `DistributionSpec`, `SpecValue`,
`ComponentDistribution`, `FleetDistributionConfig`,
`parse_fleet_distribution_config`, `generate_homes_from_distribution`,
`detect_sweep_spec` and `expand_sweep_configs`, move from
`solar_challenge.config` to the new `solar_challenge.fleet_distribution`, the
`fleet_distribution:` grammar and the homes it generates. Importing that module
does not load `solar_challenge.config`. `parse_fleet_distribution_config`,
`ComponentDistribution` and `SpecValue` are new since the 0.5.0 tag, whose
config defines the reader as the private `_parse_fleet_distribution_config`;
the other eleven import from `solar_challenge.config` on the tag.
`solar_challenge.config` still binds at runtime the six of them it uses itself,
`FleetDistributionConfig`, `SweepSpec`, `parse_fleet_distribution_config`,
`generate_homes_from_distribution`, `detect_sweep_spec` and
`expand_sweep_configs`, but it no longer exports them to `mypy --strict`, which
refuses such an import ("does not explicitly export attribute"). Importing any
other moved name from `solar_challenge.config` raises `ImportError`, and reading
one as an attribute raises `AttributeError`. `solar_challenge.config` also no
longer binds names that other modules define and that only the moved code
imported: `PVConfig` (`solar_challenge.pv`), `BatteryConfig`
(`solar_challenge.battery`), `LoadConfig` (`solar_challenge.load`),
`HeatPumpConfig` (`solar_challenge.heat_pump`), `EVConfig`
(`solar_challenge.ev`), `DataclassInstance`
(`solar_challenge.dataclass_instance`), `as_boolean`
(`solar_challenge.boolean_fields`), `fleet_home_seed` (`solar_challenge.fleet`),
`refuse_unknown_home_dispatch_strategy` (`solar_challenge.home`), and `PV_BLOCK`,
`BATTERY_BLOCK`, `LOAD_BLOCK`, `HEAT_PUMP_BLOCK`, `EV_BLOCK`, `ComponentBlock`,
`FieldKind`, `FleetField`, `BlockType`, `SettingValue`,
`dispatch_strategy_argument`, `float_or_none`, `read_dispatch_strategy_key` and
`refuse_missing_keys` (`solar_challenge.scenario_blocks`). Importing any of them
from `solar_challenge.config` raises `ImportError`, and reading one as an
attribute raises `AttributeError`. Five of them import from
`solar_challenge.config` on the 0.5.0 tag, which imports `PVConfig`,
`BatteryConfig`, `LoadConfig`, `HeatPumpConfig` and `EVConfig`; it binds none of
the other eighteen. These lines supersede the task 946 line that
`solar_challenge.config` still binds `PV_BLOCK`, `BATTERY_BLOCK`, `LOAD_BLOCK`,
`HEAT_PUMP_BLOCK`, `EV_BLOCK`, `ComponentBlock`, `FieldKind` and `FleetField` at
runtime. No parsed value changes, and no message does either. When they re-pin,
consumers import each moved name from `solar_challenge.fleet_distribution`, and
each name `solar_challenge.config` only imported from the module named beside
it. The platform imports none of these names from `solar_challenge.config`, so
it needs no change for them.

**Task 948.** Every refusal the scenario grammar's readers write, in `scenario_blocks`,
`fleet_distribution` and `config`, now reads `<block path>: <problem>`, except
that a number or true-or-false value read through
`solar_challenge.number_fields` or `solar_challenge.boolean_fields` keeps
their `<path> must be …` form, e.g. "fleet_distribution.pv.tilt must be a
finite number, got 'south'". The new
`solar_challenge.scenario_blocks.refusal(block_path, problem)` builds it and
returns a `ConfigurationError`; `require_list` sits beside `require_mapping`,
and `require_keys` and `require_held_keys` beside `refuse_missing_keys`. Two
message forms changed: "Unrecognised keys in X: …" is now "X: unrecognised
keys …", and "X must be a mapping, got T" is now "X: must be a mapping, got
T". "Missing required keys in X: X.k" is now "X: requires 'k'", and every
reader-local "requires …" message names its block and each key the block
leaves out, e.g. "homes[1].heat_pump: requires 'heat_pump_type'" and
"scenarios[0].period: requires 'end_date'". A key a block requires that is
given as null now reads as absent, and is refused as left out where it reached
the block's type or its next reader, e.g. a `normal` spec's `std: null` as
"fleet_distribution.pv.tilt: requires 'std'", except where null is a value: a
`fleet_distribution:` component block's required spec, a `fixed` spec's
`value`, which is the null spec, and `finance:`'s
`standing_charge_pence_per_day`, whose null `FinanceConfig` refuses. `homes`,
`scenarios`, a custom tariff's `periods` and `event_windows` that are not
lists are refused as "X: must be a list, got T", where the 0.5.0 tag raises
`TypeError` or a misleading message. A document that is not a mapping is
refused by `load_config_yaml` and `load_config_json`, and so by every loader,
as "the top level: must be a mapping, got list", where `load_community_config`
returned None and `load_home_config` raised `AttributeError`;
`parse_fleet_config`, `parse_sweep_fleet_configs` and
`detect_fleet_sweep_spec` refuse such a document too. Refusals raised while
`generate_homes_from_distribution` draws homes name the spec's path under
`fleet_distribution`, e.g. "fleet_distribution.pv.tilt: must draw samples that
are finite numbers, got a sample of inf" and "fleet_distribution.pv: home 1:
tilt must be between 0 and 90, got 100.0". When they re-pin, consumers that
match a refusal's text match the new texts; the exception type is unchanged, a
`ConfigurationError`, a `ValueError`.

**Task 949.** `load_scenarios`, and so `validate config` on a `scenario:` or `scenarios:`
document, refuses a scenario that holds `output:`, a scenario-level
`tariff_config:` or any key outside `name`, `description`, `location`,
`period`, `home`, `homes`, `seg` and `finance`. It raises
`ConfigurationError`, a `ValueError`, naming the key's path, such as
`scenario.output` or `scenarios[i].tariff_config`, and for the two retired
keys what replaces them: `--output` for `output:`, and `home.tariff` or each
`homes[i].tariff` for `tariff_config:`. A scenario's keys are checked before
any of its blocks is read, and the two retired keys before any other, whatever
they hold. The 0.5.0 tag reads `output:` into `ScenarioConfig.output`, which
no command reads, ignores an unknown key, and builds a scenario from
`tariff_config:` whose tariff prices no home. A scenario `load_scenarios`
builds now always has `output` None; `OutputConfig` and
`ScenarioConfig.output` stay, as does construction's refusal of a set
`ScenarioConfig.tariff_config`. `config template home` and
`config template scenario` no longer write an `output:` block. When they
re-pin, consumers drop a scenario's `output:` block and pass `--output` to the
command instead, move a scenario-level tariff to `home.tariff` or to each
`homes[i].tariff`, and remove any other key a scenario does not read.

**Task 950.** `ScenarioConfig` takes no `output` and no `tariff_config`, and
`solar_challenge.config.OutputConfig` is gone: passing either keyword to
`ScenarioConfig(...)` or to `dataclasses.replace` on a scenario raises
`TypeError`, and importing `OutputConfig` raises `ImportError`.
`seg_tariff_pence_per_kwh` is now the seventh parameter and `finance` the
eighth, so a positional call or a positional `match` class pattern past `home`
shifts. The 0.5.0 tag holds both fields: no command reads `output`, and a set
`tariff_config` prices no home. `load_scenarios` still refuses a scenario's
`output:` and `tariff_config:` keys, as the task 949 note says. The platform
consumer sets neither field. This supersedes the task 955 line's
construction-time `ConfigurationError` for a set `tariff_config`, which is now
the `TypeError` above, and the task 949 line's statement that `OutputConfig`
and `ScenarioConfig.output` stay, as does that refusal. When they re-pin, consumers drop `output=` and
`tariff_config=` from every `ScenarioConfig(...)` and `dataclasses.replace(...)`
call, and every import of `OutputConfig`; pass `--output` to the command that
writes results; and give each home its tariff as `HomeConfig.tariff_config`.

**Task 955.** `ScenarioConfig` is frozen, and it holds
`homes` as a tuple, defaulting to `()`: a list of homes is converted when the
scenario is built, so `ScenarioConfig(homes=[h1, h2], ...).homes` is
`(h1, h2)`. Assigning to one of its fields, such as `scenario.homes = homes`,
raises `dataclasses.FrozenInstanceError`; the 0.5.0 tag accepts the
assignment. Consumers that assign to a scenario field build the changed
scenario with
`dataclasses.replace(scenario, homes=homes)` instead, and those that compare
`scenario.homes` with a list compare it with a tuple, when they re-pin.
`ScenarioConfig.simulated_homes()` returns the homes the scenario simulates:
`(home,)` in the single-home form, else `homes`, in order. When the scenario
sets `seg_tariff_pence_per_kwh`, each home whose `seg_tariff` is None is given
`SEGTariff(name="", rate_pence_per_kwh=seg_tariff_pence_per_kwh)`, and a home's
own tariff is kept; the stored homes are left as they are. The 0.5.0 tag has no
such method. `ScenarioConfig.map_homes(transform)` returns the scenario in the
same form with *transform* applied to each stored home, never to the filled
homes `simulated_homes()` returns, and every scenario-level field kept; the
result is checked as construction checks it. The tag has no such method
either. Construction raises `ConfigurationError`, a `ValueError`, for a
home whose own `seg_tariff` rate is not `math.isclose` to
`seg_tariff_pence_per_kwh`, naming the home's position (`home` or `homes[i]`),
its name and both rates, and `dataclasses.replace` re-runs the check. The tag
builds that scenario, and its `project_multi_year` and
`solve_cost_recovery_rate` raise a plain `ValueError` on it. Construction also
raises `ConfigurationError` for a `seg_tariff_pence_per_kwh` that `SEGTariff`
refuses, one that is negative, not finite or a boolean, naming the scenario and
the rate; it checks the rate before it compares any home's rate with it, and it
holds the rate as the float `SEGTariff` reads, so `simulated_homes()` never
raises. The tag builds that scenario; its `project_multi_year` and
`solve_cost_recovery_rate` raise a plain `ValueError` on a negative rate and
simulate a NaN one. Construction also
raises `ConfigurationError` for a set `tariff_config`, which no simulation
reads, naming `HomeConfig.tariff_config`, so `load_scenarios` refuses a
scenario that sets `tariff_config:`; the tag builds that scenario and loads
that file. Consumers give each home its tariff as `HomeConfig.tariff_config`
when they re-pin. `optimize.apply_knob`, which the tag lacks, sets only the
scenario's rate through its `'seg'` knob and leaves the stored homes as they
are, as the tag's `sensitivity_panel` does, so `simulated_homes()` gives the
swept rate to each home without a tariff of its own. When a home carries its
own tariff at another rate, the knob raises `ConfigurationError`, naming the
home's position and both rates, where the tag's `sensitivity_panel` raises a
plain `ValueError` as it evaluates that value. The knob also raises
`ConfigurationError` as it sets a rate that `SEGTariff` refuses.
`optimize.run_sweep` simulates its age-0 baseline outlay fleet as
`simulated_homes()` gives it, as it already
simulates the solve's and the projection's fleets; the tag simulates that fleet
without the scenario's rate on a home that has no tariff of its own.
`baseline_outlay_gbp` is unchanged, since the householder bill reads no export
income. When they re-pin, consumers build a changed scenario with `dataclasses.replace(scenario, homes=homes)` instead of assigning to a scenario field, and compare `scenario.homes` with a tuple.

**Task 956.** `ScenarioConfig` gains three methods. `window()` is the
`timebase.SimulationWindow` of its period's first and last calendar days at
`timebase.ONE_MINUTE`, in the zone of its `location`, or of its first home's
location when `location` is None. `with_window(first_day=, last_day=)` is a
copy whose period keeps each day not given; it raises `ConfigurationError`
for a day that is not exactly a `date`, such as a `datetime` or a `Timestamp`,
naming the parameter and the value. `simulation_bounds()` is those days' local
midnights, the start and end a simulator takes. The 0.5.0 tag has none of
them. Construction raises `ConfigurationError`, a `ValueError`, for a
period whose `start_date` or `end_date` is not a date, a 'YYYY-MM-DD' string
or a `Timestamp`, naming `period.start_date` or `period.end_date` and the
value; the tag builds that scenario, and runs `SimulationPeriod("2024", "2024")`
as 2024-01-01. Construction also raises `ConfigurationError` for a period whose
last day precedes its first, naming both fields and both days, where the tag
builds the scenario. `with_window` and `dataclasses.replace` re-run both
checks. `project_multi_year`, `solve_cost_recovery_rate` and
`optimize.run_sweep` simulate over `simulation_bounds()`. So a period given as
a `Timestamp`, naive or zoned, at any time of day, reaches `simulate` as its
own date's local midnight on the scenario's clock, where the tag passes the
`Timestamp` as given. A naive `Timestamp` therefore now arrives zoned, even at
midnight. A zoned one's date is read on its own clock:
`Timestamp("2024-06-01 23:30", tz="UTC")` names 2024-06-01 in a Bristol
scenario, though it falls on 2 June on London's clock. A period of
'YYYY-MM-DD' strings or dates gets equal bounds. `timebase` gains
`DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY`, 2024-01-01 and 2024-12-31: the
days a scenario simulates when neither its file nor a flag gives one. When
they re-pin, consumers give a period's days as 'YYYY-MM-DD' strings or
`Timestamp`s, the types `SimulationPeriod` declares; construction also accepts
a date, as unquoted YAML dates arrive, though a date is outside those types.
They read a scenario's window from `window()` or `simulation_bounds()`
instead of `period.get_start_timestamp`, and give `fleet.reusing` the
scenario's `simulation_bounds()`, since it matches a request's clocks as well
as its instants.

**Task 957.** Every scenario document form, a bare scenario, a `scenario:` block or each `scenarios:`
entry, whose homes come from `home:`, `homes:` or `fleet_distribution:`, is read by one
grammar, through the new `config.parse_scenario(document, *, block_path="")` and
`config.load_scenario(path)`. `name:` and `period:` are optional: an absent name reads as
`""`, an absent or null period as `timebase.DEFAULT_FIRST_DAY` to `DEFAULT_LAST_DAY` on the
location's clock. A top-level key outside the grammar is refused, and exactly one homes
source is required. A `name:` or `description:` that is not a string is refused, and so is
a `scenario:` or `scenarios:` wrapper beside any other top-level key, such as a top-level
`name:` beside `scenarios:`, which used to load. `load_fleet_config` and `parse_fleet_config`
now give the homes of a `home:` or `homes:` document its top-level `tariff:`, as they and
`parse_sweep_fleet_configs` already did for a `fleet_distribution:` document, and so does
`load_home_config`; a home's own tariff that differs from it is refused, naming both. All
four give their homes the document's `seg:` rate, as a `SEGTariff` with no name.
`load_fleet_config` reads a `home:` document as a one-home fleet, `load_home_config` refuses
a fleet document, and a flat home
file (top-level `pv:`, `battery:`, `load:`, `heat_pump:` or `ev:`) or a top-level
`dispatch_strategy` is refused, naming `home:` or the battery's key.
`detect_fleet_sweep_spec` reads a `fleet_distribution:` document's keys and scenario-level
blocks before the block, refusing them as `parse_sweep_fleet_configs` does, so a file is
refused on the same first block whether or not it sweeps. `ScenarioConfig` gains
`flex_band: GridServicesBand | None = None`, and `fleet run` now books SEG export revenue on
a file with `seg:`. A consumer re-pinning wraps a flat home file in `home:`, renames
`tariff_config:` to `tariff:`, drops any top-level key the grammar refuses, and stops
threading the file's SEG rate onto loaded homes by hand.

**Task 958.** `home run` reads its file through `config.load_scenario`, the one reader every scenario
loader shares, and applies its options to the typed scenario it reads. So it simulates the
file's `period:`: `home run scenarios/bristol-arbitrage.yaml` simulates 2024-01-15 alone, not
all of 2024. `--start` and `--end` each replace only their own day of that period, and each
defaults to the file's day, else to `timebase.DEFAULT_FIRST_DAY` or `DEFAULT_LAST_DAY`. A
flag day that leaves no window, such as a `--start` after the file's `end_date`, is refused
with the window's reason under the flags given, e.g. `--start 2024-01-20: last_day 2024-01-15
is before first_day 2024-01-20: …`, and a flag that is not a `YYYY-MM-DD` date is a usage
error, exit 2. The home is given the
file's top-level `tariff:`, as `load_home_config` gives it. A flat home file, a fleet
document (a `homes:` list of any length or a `fleet_distribution:`, refused naming its home
count and `fleet run`), a top-level key the grammar refuses and `home: null` are each refused
by name before anything is simulated, where they used to run the default home or raise a
`TypeError`. `--battery-kwh N` replaces only the capacity of the file's battery, keeping its
other settings, `grid_charging` and `dispatch_strategy` included, and gives a home without a
battery one of that capacity. `--pv-kw`, `--consumption-kwh` and `--system-losses` values
that the home's config refuses are refused with that config's own message under the option's
name, e.g. `--pv-kw: capacity_kw must be greater than 0, got 0.0`, where the message used to
name a `home.pv:` or `home.load:` block. `cli.home.scenario_for_run` is the scenario the command
reads, and `cli.home.home_config_for_run` keeps its signature as that scenario's one
simulated home. `cli.utils` gains the `StartOption` and `EndOption` option pair and
`with_window_options`, and `cli.utils.load_config_with_overrides` is deleted. A consumer
re-pinning passes `--start` and `--end` to keep simulating a whole year from a file that sets
a `period:`, wraps a flat home file in `home:`, and runs fleet files with `fleet run`.

**Task 959.** `finance run` reads its file through `config.load_scenario`, the one reader every scenario
loader shares, as `optimize configs` now also does. So `finance run` simulates the file's
`period:` (D11), where it used to simulate all of 2024 whatever the file said. Both commands
take the `--start` and `--end` option pair: each flag replaces only its own day of the period,
and each defaults to the file's day, else to `timebase.DEFAULT_FIRST_DAY` or
`DEFAULT_LAST_DAY`. A flag that is not a `YYYY-MM-DD` date is a usage error, exit 2, where it
was a configuration error, exit 1. Flag days that leave no window are refused with the
window's reason under the flags given, e.g. `--start 2024-09-01: last_day 2024-08-31 is before
first_day 2024-09-01: …` for a file whose period ends on 2024-08-31. Both commands refuse every
block the one reader refuses, and refuse a file with no `finance:` block in one message, before
anything is simulated. `optimize configs` refuses a `home:` document, which it used to sweep as
a one-home fleet: give it a `homes:` or `fleet_distribution:` file. `cli.utils` gains
`required_finance`. No shipped scenario's report changes: each shipped file with a `finance:`
block sets no `period:` or all of 2024. A consumer re-pinning passes `--start` and `--end` to
keep simulating a whole year from a file that sets a shorter `period:`.

**Task 963.** `ScenarioConfig.period` is a `timebase.SimulationWindow`: a scenario is built
with `period=SimulationWindow(first_day, last_day, ONE_MINUTE, timezone)`,
where the 0.5.0 tag takes `period=SimulationPeriod(start_date, end_date)`.
The window's `timezone` is the scenario's zone: its `location`'s, or its first
home's location's when `location` is None. `config.SimulationPeriod`, with its
`get_start_timestamp` and `get_end_timestamp`, is retired: importing it, `from
solar_challenge.config import SimulationPeriod`, raises `ImportError`.
Construction raises `ConfigurationError`, a `ValueError`, naming the scenario,
for a period that is not a `SimulationWindow`, naming its type; for one at a
cadence other than `ONE_MINUTE`, naming both; and for one on another zone than
the scenario's, naming both zones. A window whose days are not exactly `date`s,
or whose last day precedes its first, cannot be built: `SimulationWindow`
raises `ValueError`. `window()` returns the period itself, and
`simulation_bounds()` its first and last days' local midnights, as before.
`with_window(first_day=, last_day=)` raises `ConfigurationError` for days that
give no window, a `datetime` or a last day before the first, naming the
scenario, the arguments given and the window's reason. A scenario file's
period day that is not a day, such as '2024', or a period whose last day
precedes its first, is refused naming its block path, e.g.
`scenarios[0].period.start_date`, where the tag builds that scenario, reading
'2024' as 2024-01-01 and keeping a reversed period as given.
`config.period_day(value, path)` and `config.period_window(start_date,
end_date, *, timezone, block_path="period")` are new: they read a period's
days as a scenario file's are read, a date, a 'YYYY-MM-DD' string or a
`Timestamp`'s own date, and `period_window` gives the one-minute window on
`timezone`, raising `ConfigurationError` naming each refused day's path. When
they re-pin, consumers build one window at `ONE_MINUTE` on the scenario's zone,
or call `config.period_window(start, end, timezone=...)` with the strings or
`Timestamp`s they gave `SimulationPeriod`, and read a scenario's days from
`period.first_day` and `period.last_day`, or `simulation_bounds()`, instead of
`period.start_date`, `period.end_date` or `period.get_start_timestamp`. The
platform's seam test builds one window. Where this note and task 956's entry differ,
this note holds for the release: construction, and so `dataclasses.replace`,
checks the window's type, cadence and zone, not its days, so no construction
refusal names `period.start_date`; and consumers give a period's days to a
window, not to `SimulationPeriod` as task 956's entry's re-pin advice says.

**Task 964.** `solar_challenge.fleet_distribution.SweepSpec`'s `mode` is now a `SweepMode`,
a new `StrEnum` of `linear` and `geometric` in the same module, and defaults to
`SweepMode.GEOMETRIC`. A spec built with a string naming either holds that
member, and `SweepMode.parse`, which construction uses, refuses any other
value, a member's name such as `GEOMETRIC` or a non-string included, with a
`ConfigurationError` naming `mode`, the value and both modes: "mode must be
linear or geometric, got 'log'". A spec whose points are not all finite, such
as a geometric sweep from 1e-300 to 1e300 in 3 steps or a linear span whose
step overflows a float, is refused as it is built, naming `min`, `max` and
their values, and so is a YAML `type: sweep` multiplier, which the refusal
names by its path, or a `fleet sweep --min/--max` that gives one. The 0.5.0
tag builds such a spec: its points are infinite or not a number, or
`get_values()` raises `OverflowError`, and `generate_homes_from_distribution`
at an infinite point builds homes with an infinite battery capacity.
`get_values()` returns a `tuple` rather than a list, its points unchanged, and
`write_distribution_spec` writes a sweep's mode as its string. Consumers that
compare `mode` with a string, format it or iterate the points need no change
when they re-pin; code that compares `get_values()` with a list or mutates it
wraps it in `list(...)`. Code that builds a spec with a string mode, or
annotates `get_values()` as `list[float]`, still runs, but `mypy --strict`
refuses it (`arg-type`, `assignment`): it passes `SweepMode.LINEAR`,
`SweepMode.GEOMETRIC` or `SweepMode.parse(text)` instead, and annotates the
points `tuple[float, ...]` or wraps them in `list(...)`.

**Task 965.** The new module `scenario_knobs` names each setting of a scenario that a sweep or a
sensitivity axis varies, and holds the one edit that sets it. `KNOBS` maps each
canonical name to its `Knob`, whose `apply(scenario, value)` returns a new
scenario in the form it was given, single-home or fleet. `ALIASES` maps each
short alias to a canonical name, and `knob_named(name)` resolves either. An
unknown name raises `ConfigurationError`, a `ValueError`, that lists every
canonical name with its aliases. The knobs are `pv_capacity_kw`,
`inverter_capacity_kw`, `battery_capacity_kwh`, `annual_consumption_kwh`,
`degradation_rate_per_year` (alias `degradation`), `seg_tariff_pence_per_kwh`
(alias `seg`) and every real-number `FinanceConfig` field. The year counts,
`grid_services_model` and `grid_services_events` are not knobs. A finance knob on
a scenario without a finance block raises `ConfigurationError` naming the knob
and the scenario. `optimize.apply_knob`, which the 0.5.0 tag lacks, is gone. It
refused a single-home scenario, which a knob accepts. The SEG knob sets the
scenario's rate as its `'seg'` knob did (task 955's note).
`optimize.SENSITIVITY_BANDS`, which the tag also lacks, is keyed by `Knob`. So is
`sensitivity_panel`'s `axes`, where the tag takes knob names. Each
`SensitivityAxis.name` is still the knob's canonical name. `enumerate_configs` and
`iter_configs` now fit each point's install through the `pv_capacity_kw`,
`battery_capacity_kwh` and `inverter_capacity_kw` knobs. They build the same
homes as the tag, and `optimize configs` prints the same report. The
`battery_capacity_kwh` knob follows one rule. At 0 a home has no battery. A
battery a home has keeps its power, state-of-charge, grid-charging and dispatch
settings at the new capacity, and a home without one gains a default
`BatteryConfig` at that capacity. So once the web's sweep reads the registry (task 967), a web base home without a
battery gains a default battery at each battery point. `optimize configs
--sensitivity` accepts a knob's canonical name as well as its alias. It refuses
a knob with no sensitivity band, naming it and listing the knobs that have one,
and a knob named twice, naming both names as written, before anything is
simulated. It reports an unknown name as a "Configuration
error", where the tag reports an "Invalid value". When they re-pin, consumers
replace `apply_knob(scenario, name, value)` with
`knob_named(name).apply(scenario, value)`, and key `sensitivity_panel`'s axes and
any `SENSITIVITY_BANDS` lookup by `KNOBS[name]`.

**Task 966.** The retained-cash floor has one setter, the scenario's
`FinanceConfig.retained_cash_floor_per_home_per_year_gbp`, and the sensitivity
panel no longer sweeps its own baseline. `optimize.run_sweep(configs, *, simulate)`
takes no `retained_cash_floor_gbp`, where the 0.5.0 tag's run_sweep overrides
each config's floor with it. It refuses with `ValueError`, before any
simulation, configs whose floors differ, naming two of them and their floors,
and `RankedSweep.retained_cash_floor_gbp` is the configs' common floor, where
the tag echoes the override or, without one, the first config's floor.
`optimize.sensitivity_panel(base_configs, axes, *, baseline, simulate)` requires
`baseline`, the `RankedSweep` that `run_sweep(base_configs)` returned, and takes
no `retained_cash_floor_gbp`, where the tag re-runs that sweep itself at the
floor it is given. Before any simulation it refuses with `ValueError` a
baseline whose evaluated points or `retained_cash_floor_gbp` differ from
`base_configs`', naming both, a baseline with no feasible config, and an axis
that repeats a value. The floor axis is an ordinary knob axis, and the panel
reuses the baseline for any axis value whose knob leaves every base scenario
equal, such as the floor band's value at the scenario's own floor, so
`optimize configs`' default sensitivity asks for 6 sweeps' worth of
simulations where it asked for 8. `SensitivityAxis` also refuses a repeated
value. `optimize configs --retained-floor` sets the floor on the scenario's
finance block before enumeration, as the `retained_floor` knob does, and its
report is unchanged. When they re-pin, consumers set the floor on the scenario
before `enumerate_configs`, with
`scenario_knobs.knob_named('retained_floor').apply(scenario, floor)` or the
`FinanceConfig` field, drop `retained_cash_floor_gbp=` from both calls, and pass
the `run_sweep` result to `sensitivity_panel` as `baseline`.

**Task 969.** A `fleet_distribution` sweep multiplier, a `proportional_to` whose
`multiplier` has `type: sweep`, is refused when the file is read unless it
sits at `fleet_distribution.battery.capacity_kwh`, the one placement in the
new `fleet_distribution.SWEEP_PLACEMENTS`, a frozenset of the new
`FleetFieldPath`, a `(component, key)` named tuple whose `dotted` property
reads `'battery.capacity_kwh'`. A fleet holding a second sweep multiplier is
refused too. Each refusal is a `ConfigurationError` naming every sweep's
field path, e.g. `fleet_distribution.battery.max_charge_kw: a sweep
multiplier, which a fleet holds only at
fleet_distribution.battery.capacity_kwh`, and `FleetDistributionConfig`
refuses either when it is built in code or through `dataclasses.replace`.
The 0.5.0 tag parses a sweep multiplier at other fields and refuses it only
when it draws homes, while `fleet sweep` reports that the file holds no
sweep. `detect_sweep_spec` and `config.detect_fleet_sweep_spec` return
`(placement, spec)` instead of the `SweepSpec` alone, and still return
`None` for a fleet with no sweep. `generate_homes_from_distribution` refuses
a fleet that still sweeps before it draws any home, naming its placement,
its point count and `expand_sweep_configs`. `parse_scenario`,
`load_scenario`, `load_scenarios`, `parse_fleet_config` and
`load_fleet_config` refuse a sweep document, naming its placement and
`'fleet sweep'`, and `fleet run` exits 1 on one; a sweep under a
`scenario:` block or a `scenarios:` entry, which `fleet sweep` does not
read, is refused saying to give the scenario a file of its own, unwrapped. `fleet sweep` names each
point's fleet `battery.capacity_kwh.multiplier=<value>` and writes
`battery.capacity_kwh.multiplier_<value>.csv`, where the tag uses
`multiplier=<value>` and `multiplier_<value>.csv`, and puts that label in
its announcement and its summary's `param` column; `parse_sweep_fleet_configs`
names its fleets alike. `config.YAML_SWEEP_PARAMETER`, added since the tag,
is gone; `fleet_distribution.swept_parameter_path(placement)` gives the
label. Consumers, when they re-pin, unpack the pair from both detect
functions, move any sweep multiplier to `battery.capacity_kwh`, run a sweep
file with `fleet sweep` or read it with `parse_sweep_scenarios` or
`parse_sweep_fleet_configs`, never a one-fleet reader, and expect the new
point names in any CSV paths or fleet names they read.

**Task 970.** `generate_finance_report` and `generate_config_ranking_report`, the board's reports that `finance run` and `optimize configs` print, move from `solar_challenge.output` to the new module `solar_challenge.board_report`; neither is frozen, and the platform imports neither. `solar_challenge.output` keeps per-run output: the CSV export, the summary and community reports, and seasonal and period aggregation. Both reports now raise `ValueError`, naming the binding, for a cost-recovery solution or config whose `binding` is not one of `'floor'`, `'rate_clamped_zero'` and `'infeasible_above_retail'`, where the finance report printed it as *✘ INFEASIBLE: required rate exceeds retail* and the ranking report printed the raw string. A `CostRecoverySolution` already refuses any other binding when it is built, so only a solution that bypassed that check reaches the finance report's refusal; a `ConfigResult` has no such check, so the ranking report now refuses one built directly with any other binding. The grid-charge forecast notice that both board reports and output's summary and community reports print, which the 0.5.0 tag does not have, is rendered by one public function, `output.grid_charge_forecast_notice`. The move changes no report's text. Consumers that import either board report import it from `solar_challenge.board_report` when they re-pin.

**Task 973.** `board_report.generate_finance_report` now takes `sections: Mapping[OwnUseBasis, AssumptionSection]`, then the keywords `scenario_name`, `flex_band`, `flex_band_name` and `grid_services_at_events`. This replaces its `bill_physics` and `bill_spreadsheet` positionals and its `economics` and `cost_recovery` keywords. The new frozen dataclass `board_report.AssumptionSection` holds one own-use mode's figures, every one computed under its own `finance: FinanceConfig`: its `bill: BillDistribution` and optional `projection`, `economics` and `cost_recovery`. The new `board_report.ASSUMPTION_LABELS` maps `OwnUseBasis.SIMULATED` to `"Physics"` and `OwnUseBasis.OVERRIDE` to `"Spreadsheet"`. Every table of the bill, project-economics and cost-recovery blocks has one value column per section, in `OwnUseBasis` order, headed by that label and, for an override, the self-consumption it sets, e.g. `Spreadsheet (70% self-consumption)`; no heading names a mode. The flexibility-value block, which no mode changes, renders once with its own columns. The report raises `ValueError`, naming the values, in this order: for an empty mapping; for a key that is not `own_use_basis` of its section's finance; for sections that carry different computations of `projection`, `economics` and `cost_recovery`; and for bills annualised from different windows. `finance.own_use_basis(finance)`, the one rule of a `FinanceConfig`'s own-use basis, and `finance.with_own_use_basis(finance, basis)`, which puts a `FinanceConfig` on a basis and changes no other field, are new public names; `finance` has no `__all__`, so neither is in one. Consumers that call `generate_finance_report` build one `AssumptionSection` per mode when they re-pin, its finance from `with_own_use_basis`, and pass them keyed by `own_use_basis(section.finance)`.

**Task 974.** `FleetProjection`, which `project_fleet` and `run_cost_recovery` return, gains a third field, `grid_services_income_gbp`: (age, £/yr) for every age the projection simulated, its seeds and every bisection trial, ascending, each the grid-services income the scenario's pricing booked on that age's own simulated fleet; its first entry is age 0 (year 1) and its last the curve's last year. Construction refuses, with `ValueError` naming the series, one that is empty, not strictly ascending, not starting at age 0, not ending at the curve's last year, missing one of the curve's `sampled_ages`, or holding an income that is negative, NaN or infinite. `solar_challenge.board_report` gains `GridServicesIncome`, what a pricing that books grid services (`FlatGridServices` or `GridServicesEventsConfig`, never `NoGridServices`) books on the bill run's fleet: its income, battery homes and Σ battery discharge kW, and under events pricing its `GridServicesAtEvents` breakdown, refusing with `ValueError` a figure its pricing could not have printed; and `FlexBlock`, the flexibility-value block's `GridServicesBand`, holding the band a word names and refusing any other value with `ConfigurationError` naming `FlexBlock.band`, whose consulting figures `flex.resolve_flex_band` reads from `flex.FLEX_VALUE_BANDS`. `generate_finance_report`'s keywords `grid_services` and `flex` replace `flex_band`, `flex_band_name` and `grid_services_at_events`: given a `GridServicesIncome` it renders a Grid Services Income section after Project Economics, with the pricing's model line, each mode's booked income at year 1 and year N when the sections carry projections, and this window's fleet table, which now holds the capacity-at-events rows the flexibility-value block used to carry; the block's grid-services row reads the booked income, or the band's consulting figure labelled not booked. Neither report module is frozen, and nothing in `__all__` changes. Consumers that call `generate_finance_report` build a `GridServicesIncome` from their pricing value on the bill run's fleet and a `FlexBlock` from their band when they re-pin; consumers that construct neither can read the projection's booked income from the new field.

**Task 975.** `calculate_summary(results)`, `fleet.calculate_fleet_summary(results)`,
`fleet.calculate_home_summaries(results)` and
`output.generate_summary_report(results, home_name=None)` take no
`seg_tariff_pence_per_kwh`, so passing it raises `TypeError`; on the 0.5.0 tag
`calculate_summary`, `calculate_fleet_summary` and `generate_summary_report`
take it, and `calculate_home_summaries` does not exist. A run's SEG income is
its `total_export_revenue_gbp`, which `simulate_home` prices at its
`HomeConfig.seg_tariff`'s rate, as on the tag, so no figure of a home priced
that way moves: the rate argument re-priced the same export a second time.
`calculate_summary` no longer sets `SummaryStatistics.seg_revenue_gbp`. The
field keeps its place on the frozen form, None unless a caller builds or stores
a summary with a value, until the next surface bump retires it. `FleetSummary`
loses `total_seg_revenue_gbp` and `per_home_seg_revenue_mean_gbp`, and
`aggregate_home_summaries` reads no home's `seg_revenue_gbp`. The summary
report's `## SEG Revenue` section and the `SEG Revenue` row of the CLI's summary
tables are gone. The report's Financial table instead shows a `SEG Rate` row
after Grid Export Revenue, e.g. `| SEG Rate | 15.0 p/kWh |`: the rate the run's
export was priced at, the results' `pricing.seg_rate_pence_per_kwh` (the task
922 line's `RunPricing`), whenever one is set, 0.0 included. The tag has no such
row. A dashboard store at schema version 5 is refused until `solar-challenge web
migrate` brings it to version 6, whose step brings each stored run to
run-document format 6: it drops the pair from every stored fleet summary, in the
run's directory and in its runs row alike, reporting as a dropped value each one
that is not null. When they re-pin, consumers stop passing the rate to these
four functions; read a run's SEG income from `total_export_revenue_gbp` and its
rate from `pricing.seg_rate_pence_per_kwh`; give a home whose export a passed
rate was meant to price `seg_tariff=SEGTariff(...)` instead; and run
`solar-challenge web migrate` on a dashboard store. The platform calls none of
these with the rate, and needs no change.

**Task 976.** `SummaryStatistics` has no `seg_revenue_gbp` field, so
`SummaryStatistics(..., seg_revenue_gbp=x)` and
`dataclasses.replace(summary, seg_revenue_gbp=x)` raise `TypeError`, and
`seg_revenue_gbp` is gone from its frozen signature; on the 0.5.0 tag it is the
field `calculate_summary` set from its `seg_tariff_pence_per_kwh` argument, and
task 975's note left it on the frozen form, None, until this retirement. A
run's SEG income is its `total_export_revenue_gbp`, which `simulate_home`
prices at its `HomeConfig.seg_tariff`'s rate, so no figure moves. Each field
after `strategy_name` moves one place forward, so `total_heat_pump_load_kwh` is
now the 18th: a caller that passes these fields by position, or a `match` on
`SummaryStatistics(...)`'s positional patterns past `strategy_name`, shifts by
one, and a value passed where `seg_revenue_gbp` stood now lands in
`total_heat_pump_load_kwh` without an error, so pass these fields by keyword. A
dashboard store at schema version 8 is refused until `solar-challenge web
migrate` brings it to version 9, whose step brings each stored run to
run-document format 9: it drops `seg_revenue_gbp` from every stored home
summary, a home run's summary in its directory and in its runs row alike, and
each of a fleet run's `homes/home_<i>_summary.json`, and reports as a dropped
value each one that is not null, e.g. `run '<id>':
homes/home_0_summary.json's seg_revenue_gbp was 2.8048407673789746`. When
they re-pin, library callers drop the `seg_revenue_gbp` keyword and read a
run's SEG income from `total_export_revenue_gbp`, and dashboards run
`solar-challenge web migrate`. The platform passes `seg_revenue_gbp=None` at 3
test sites, which drop the keyword.

**Task 1029.** `PVConfig` refuses, when it is built, the
`custom_module_params` that the task 812 and 823 lines say `create_pv_system`
refuses: a module with neither `pdc0` and `gamma_pdc` nor an `STC`, and one
whose `T_NOCT` or `A_c` (its own, or `DEFAULT_CEC_MODULE`'s where it lacks one)
leaves NOCT-SAM unable to heat its cells above the air. The 0.5.0 tag builds
both, counting the first as 400 W modules and running every module at SAPM's
cell temperatures, which read neither key. The area a set `module_efficiency`
gives counts, so `PVConfig(capacity_kw=4.0, custom_module_params={"pdc0":
4000.0, "gamma_pdc": -0.004}, module_efficiency=0.2)` is built, and refused
without its `module_efficiency`. Each refusal is a `ConfigurationError`, a
`ValueError`, with the message `create_pv_system` gives, and
`create_pv_system`, `create_model_chain`, `simulate_pv_output` and
`wired_dc_capacity_kw` now raise `ConfigurationError` where those lines say
`ValueError`. They still check the module they wire, a second enforcement
point of the same rule. A stored run whose config carries such a module no
longer reads: its `StoredRunUnreadable` names `PVConfig`'s refusal. Consumers
that pass such a module give it an `STC`, or `pdc0` and `gamma_pdc`, a
`T_NOCT` inside NOCT-SAM's domain, and an `A_c` inside it or a
`module_efficiency`, which sets the `A_c`, and expect the refusal where they
build the `PVConfig`, when they re-pin; code that catches `ValueError` needs
no change.

**Task 1102.** `TariffConfig.get_rate` and `TariffPeriod.matches_time` annotate their
`timestamp` as `datetime`, as `TariffConfig.is_cheap_at` does, where the 0.5.0
tag annotates it `pd.Timestamp`. Both read the wall clock of any `datetime` at
run time, as on the tag, and a `pd.Timestamp` is a `datetime`, so no value
they return changes. A type checker now admits a plain `datetime`, which the
tag's annotation refuses under pandas' stubs, and refuses an argument that is
no `datetime`, which pandas without stubs makes the tag's annotation read as
`Any` and admit. Consumers need no change when they re-pin; one that passes a
plain `datetime` can drop a `pd.Timestamp(...)` wrapper or a `cast` added only
for the type checker.

**Task 1119.** `solve_cost_recovery_rate`, `finance.project_multi_year`, `optimize.run_sweep`
and `optimize.sensitivity_panel` raise `ValueError` when their `simulate`
returns a `FleetResults` whose `home_configs` do not carry, in order and state
of health aside, the batteries of the `fleet_config.homes` it was asked to
simulate, since grid-services income is priced from those batteries. The
message names the fleet, then both numbers of homes, or the first home whose
batteries differ and both batteries. The 0.5.0 tag accepts such a fleet.
Consumers whose `simulate=` builds its own `FleetResults` make its
`home_configs` carry the batteries of the homes it is given, as
`FleetRunner.simulate` does, when they re-pin; consumers that simulate through
a `FleetRunner` need no change.

**Task 1125.** `solar-challenge validate config` reads the `seg:` and `finance:` blocks of a
`homes:`, `fleet_distribution:` or home file with the parsers a `scenario:`
file's loader reads them with: `seg:` with `parse_seg_rate`, as `finance run`,
`home run` and `optimize configs` read it, and `finance:` with
`parse_finance_config`, as `finance run` and `optimize configs` read it. A value
one of them refuses, e.g. `rate_pence_per_kwh: .nan` or `event_hours: .inf`, is
that file's ERROR row naming the field and the value, where the 0.5.0 tag read
neither block of any file. No value a public name returns changes, so
consumers need nothing when they re-pin; a file that `validate config` passed
with such a value now fails it, as `finance run` and `optimize configs` refuse
the value, and `home run` a `seg:` one, where the tag accepts them. A consumer whose file `validate config` now fails gives the field its ERROR row names a value `parse_seg_rate` or `parse_finance_config` reads, when they re-pin.

**Task 1218.** `SimulationResults` refuses, when it is built, a series in any of its fields,
the optional ones included, whose dtype is neither an integer's nor a
float's: strings, objects such as `None` or floats held as objects, bools,
nullable booleans, timestamps, durations, complex numbers and the like; and
`SimulationResults.from_dataframe` refuses a column holding such a series the
same way. The 0.5.0 tag builds each. The refusal is a `ValueError` naming the
first such series' column, in declaration order, e.g. `generation_kw`, and its
dtype. Series of integers, nullable `Int64` and `Float64` series, and floats
holding NaN or the infinities are still admitted as given. The check reads one
dtype per series, so building a `SimulationResults` costs what it did.
Consumers that build one from series of numbers, and code that catches
`ValueError`, need no change when they re-pin; a consumer that builds one from
series of another dtype converts them first, e.g. with `astype(float)`.

**Task 1270.** `optimize.RankedSweep` gains a last field, `self_consumption_override`, with no default: the `FinanceConfig.self_consumption_override` every config's finance sets, `None` when every config is solved on simulated own-use (`finance.OwnUseBasis.SIMULATED`); a value `FinanceConfig` would refuse, one outside (0, 1], is refused at construction with a `ConfigurationError` naming it. `run_sweep` records it and, as it already does for the retained-cash floor, requires it to be one across configs: it refuses configs whose finance blocks set two overrides with a `ValueError` naming both configs and both values, before any simulation, where the 0.5.0 tag ranks them together, each solved on its own assumption. `sensitivity_panel` likewise refuses a `baseline` whose `self_consumption_override` differs from `base_configs`', before any simulation. `board_report.generate_config_ranking_report` now opens with `Self-consumption assumption: **Physics**` or `Self-consumption assumption: **Spreadsheet (<x>% self-consumption)**`, the label `finance run` heads that assumption's column with, and a blank line above `## Cost-Recovery Rank`, where the tag's ranking report opens with that heading; it names the assumption even when no config is feasible. When they re-pin, consumers pass `self_consumption_override` to any `RankedSweep` they build, put every config's finance on one assumption, e.g. with `finance.with_own_use_basis` on the base scenario's finance, before `enumerate_configs`, and read the report's first heading after its assumption line.

**Task 1315.** `DispatchStrategy` gains a read-only property, `charges_from_the_grid`:
whether the strategy charges the battery from the grid when `decide_action`
is offered a `GridChargeContext`. It is `True` unless a strategy overrides it.
`SelfConsumptionStrategy`'s is `False`, and `TOUOptimizedStrategy`'s and
`PeakShavingStrategy`'s are `True`, each as its configuration variant
declares; `dispatch.ScheduledChargeStrategy`'s is `True` with any window, else
its base's. The property is part of the frozen public surface of
`DispatchStrategy`, `SelfConsumptionStrategy`, `TOUOptimizedStrategy` and
`PeakShavingStrategy`, which the 0.5.0 tag's lack.
`simulate_home`, given a `strategy` whose `charges_from_the_grid` is `False`
on a home whose battery sets `grid_charging`, now raises `ConfigurationError`
before it asks its weather provider for weather, with the message
"grid_charging is set, but dispatch strategy '<name>' does not charge from
the grid; ...", whose remedies, for a `ScheduledChargeStrategy`, include
giving it a `ChargeWindow`. The `strategy` keyword is new since the 0.5.0 tag,
whose `simulate_home` takes none; until this change it ran such a home storing
nothing from the grid, with no warning. `dispatch.build_dispatch_strategy`
refuses as before, with the same messages. It calls the now public
`dispatch.refuse_grid_charging_it_would_ignore(strategy, *, grid_charging,
tariff)`, which refuses a set `grid_charging` under a strategy whose
`charges_from_the_grid` is `False`, or with no tariff. That function does not
judge the tariff's rates, since a `ChargeWindow` grid-charges on any tariff:
`build_dispatch_strategy` alone refuses `grid_charging` on a tariff with no
cheap period. When they re-pin, consumers that pass
`SelfConsumptionStrategy`, or a `ScheduledChargeStrategy` with no window over
it, to a home whose battery sets `grid_charging` drop the `grid_charging` or
pass a strategy that charges from the grid. A strategy of their own that
ignores the context overrides `charges_from_the_grid` to return `False`, so
that it is refused; one that charges from the grid needs no change.

**Task 1358.** Building a `SummaryStatistics` raises `ValueError` when its
`total_battery_discharge_kwh` is more than its `total_self_consumption_kwh`,
which counts the battery's discharge, or when either is NaN; the message names
both totals. The 0.5.0 tag builds such a summary. So
`total_direct_self_consumption_kwh`, the self-consumption less the discharge,
is never below 0. `calculate_summary` over `simulate_home`'s results always
satisfies the bound, since a step's discharge no longer exceeds its
self-consumption, as the task 1362 line describes. Code that builds summaries
with `calculate_summary` over `simulate_home`'s results, or by hand with a
self-consumption that counts the discharge, needs no change when it re-pins;
code that builds one with a discharge above its self-consumption, by hand or
with `calculate_summary` over results of its own, now raises, and counts the
discharge in the self-consumption instead.

**Task 1372.** `PVConfig` refuses, when it is built, the set
`temperature_coefficient` that the task 825 line says is refused when its
system is built, if no `Adjust` reaches it on custom CEC single-diode
`custom_module_params`: on a module whose `alpha_sc` is 0, which no `Adjust`
moves, and on one where no `Adjust` in the solver's bracket reaches the
coefficient. `DEFAULT_CEC_MODULE`'s row at an `EgRef` of 3.0, for instance,
reaches only −3.115 to −0.0908 %/K, so −0.05 %/K is refused, and a module
whose modelled coefficient at the bracket's ends is NaN, as with a negative
`R_sh_ref`, reaches none. The 0.5.0 tag
builds each, ignoring the coefficient on custom module parameters. Each
refusal is a `ConfigurationError`, a `ValueError`, with the message
`create_pv_system` gives, and `create_pv_system`, `create_model_chain`,
`simulate_pv_output` and `wired_dc_capacity_kw` now raise
`ConfigurationError` where that line says `ValueError`. They still check the
module they wire, a second enforcement point of the same rule. Building a
`PVConfig` with a set `temperature_coefficient` on CEC single-diode
`custom_module_params` now evaluates pvlib's single-diode model at the
bracket's two ends; every other `PVConfig` costs what it did. A stored run
whose config carries such a module no longer reads: its
`StoredRunUnreadable` names `PVConfig`'s refusal. Consumers that pass such a
module expect the refusal where they build the `PVConfig`, when they re-pin;
code that catches `ValueError` needs no change. Consumers that pass such a module give it an `alpha_sc` that is not 0 and a `temperature_coefficient` an `Adjust` in the solver's bracket reaches when they re-pin; code that catches `ValueError` needs no change.

**Task 1374.** `PVConfig` refuses, when it is built, `custom_module_params` whose rating is
not a finite number above 0: 0, a negative number, NaN, infinity, or text, even
text that reads as such a number.
The rating is the one the task 812 line says counts the modules, `pdc0` on a
module with `pdc0` and `gamma_pdc` and `STC` on any other, so a module rated
by its `pdc0` is not refused for an `STC` its rating does not read. The
refusal is a `ConfigurationError`, a `ValueError`, naming the key and its
value, e.g. "Module parameter pdc0 must be greater than 0, got 0.0", and
`create_pv_system`, `create_model_chain`, `simulate_pv_output` and
`wired_dc_capacity_kw` refuse the module they wire with the same message, a
second enforcement point of the same rule. It comes before the NOCT-SAM
refusal the task 1029 line describes, so with a set `module_efficiency` such a
rating is refused by name, not through the `A_c` the efficiency would derive
from it. The 0.5.0 tag builds such a `PVConfig`. Its `create_pv_system`
counts a module rated by its `pdc0` without reading the `pdc0`, as the task 812
line says, raises `ZeroDivisionError`, which is not a `ValueError`, for an
`STC` of 0 and the uninformative `ValueError` "cannot convert float NaN to
integer" for a NaN one, and wires a negative or infinite `STC` as one module.
It raises `TypeError` for an `STC` given as text, and passes a `pdc0` given as
text to pvlib's PVWatts model, which raises numpy's `UFuncTypeError`, a
`TypeError`, when the system is simulated. A stored run whose config carries
a module with a rating of 0, a negative number, NaN or infinity no longer
reads: its `StoredRunUnreadable` names `PVConfig`'s refusal. The stored
config's reader already refuses a rating given as text, before `PVConfig` is
built. Consumers that pass such a module give it a rating that is a finite
number above 0, and expect the refusal where they build the `PVConfig`, when
they re-pin; code that catches `ValueError` needs no change, while code that
caught the `TypeError` of a rating given as text catches `ValueError` instead.

**Task 1400.** `PVConfig` refuses, when it is built, `custom_module_params` that give
`gamma_pdc`, `alpha_sc`, `a_ref`, `I_L_ref`, `I_o_ref`, `R_sh_ref`, `R_s`,
`Adjust`, `T_NOCT`, `A_c` or `V_mp_ref` as anything but a finite number:
text, even text that reads as one, a boolean, NaN or infinity. pvlib's DC
models, NOCT-SAM and the string wiring read these keys from the module's own
parameters. The rule reads the parameters as the caller gives them, so it
refuses such a key even where a set `module_efficiency` or
`temperature_coefficient` replaces it. Keys no model reads, such as a CECMod
row's `Technology`, are not checked, and pvlib's CECMod rows, which
`cec_module_params` reads, give each checked key as a finite float. The
refusal is a `ConfigurationError`, a `ValueError`, naming the key and its
value, e.g. "Module parameter gamma_pdc must be a finite number, got
'-0.004'", and `create_pv_system`, `create_model_chain`, `simulate_pv_output`
and `wired_dc_capacity_kw` refuse the module they wire with the same message,
a second enforcement point of the same rule. It is the first check of the
custom module parameters, ahead of the NOCT-SAM refusal the task 1029 line
describes and the reach refusal the task 1372 line describes, so a NaN
`T_NOCT`, `A_c` or `alpha_sc` gets this message. The 0.5.0 tag builds such a
`PVConfig` and its system. It never reads `T_NOCT`, `A_c` or `V_mp_ref`, and
passes `gamma_pdc` and the CEC parameters to pvlib, which raises `TypeError`,
numpy's `UFuncTypeError` among them, for one given as text when the system is
simulated; an infinite `gamma_pdc` or a NaN `alpha_sc` simulates to no AC,
and a boolean is read as 1 or 0, with no error. A stored run whose config
carries a NaN or infinite one no longer reads: its `StoredRunUnreadable` names
`PVConfig`'s refusal. The stored config's reader already refuses text and
booleans there. Consumers that pass such a module give these keys as numbers,
and expect the refusal where they build the `PVConfig`, when they re-pin; code
that catches `ValueError` needs no change, while code that caught the
`TypeError` of a key given as text catches `ValueError` instead.

**Task 1434.** `GridServicesAtEvents` takes all seven of its fields with no default,
including the four per-window fields task 837 adds, which 837's note had
defaulting to `()`, so `GridServicesAtEvents(...)` without
`per_window_avail_p50_kw`, `per_window_avail_p90_kw`,
`per_window_displaced_self_use_kwh_per_event` or
`per_window_displaced_import_gbp_per_year` raises `TypeError`. Construction,
and `dataclasses.replace` alike, raises a ValueError for a breakdown with no
event window, a per-window field without one entry per event window (as many
as `per_window_avail_kw` holds), a NaN figure, a capacity, energy or income
below 0, or an `annual_income_gbp` that is not `sum(per_window_income_gbp)`,
naming the invariant and the values that break it. A
`per_window_displaced_import_gbp_per_year` entry may be below 0: it takes its
import price's sign. The 0.5.0 tag accepts any tuples and any total. So
`compute_grid_services_at_events` raises that ValueError for a fleet in which a
battery home's `battery_discharge` below 0 after an event window makes a
displaced self-use below 0, which the 0.5.0 tag returns. When they re-pin,
consumers that take the breakdown from `compute_grid_services_at_events` for
fleets from `simulate_home` or `simulate_fleet` need no code change; one that
builds a breakdown itself, a test fixture say, passes every per-window field
with one entry per window and `annual_income_gbp=sum(per_window_income_gbp)`,
derived rather than written as a literal. The platform builds none. Consumers that build a `GridServicesAtEvents` pass its `per_window_avail_p50_kw`, `per_window_avail_p90_kw`, `per_window_displaced_self_use_kwh_per_event` and `per_window_displaced_import_gbp_per_year`.

**Task 1440.** `PVConfig` also refuses, when it is built, `custom_module_params` that give
any of these keys as anything but a finite number: text, even text that
reads as one, a boolean, `None`, NaN or infinity. They are the keys pvlib
defaults when a module lacks them (`calcparams_cec`'s `EgRef`, `dEgdT`,
`irrad_ref` and `temp_ref`, `pvwatts_dc`'s `temp_ref` and `k`, the effective
irradiance's `FD` and the physical IAM's `n`, `K`, `L` and `n_ar`), SAPM's DC
parameters (`C0` to `C3`, `Isco`, `Impo`, `Voco`, `Vmpo`, `Aisc`, `Aimp`,
`Bvoco`, `Mbvoc`, `Bvmpo`, `Mbvmp`, `N` and `Cells_in_Series`) and PVsyst's
`gamma_ref`, `mu_gamma`, `R_sh_0`, `R_sh_exp` and `cells_in_series`, which
the rule the task 1400 line describes now also reads. It also refuses a
`cap_adjustment`, the flag `pvwatts_dc` reads, that is not true or false, a
Python or numpy bool. SAPM's `IXO`, `IXXO` and `C4` to `C7`, which pvlib
reads only into currents no inverter reads, and keys no model this package
runs reads are not checked, and no row of pvlib's CECMod or SandiaMod
libraries is refused. The refusal is a `ConfigurationError`, a `ValueError`,
naming the key and its value, e.g. "Module parameter EgRef must be a finite
number, got '1.121'" or "Module parameter cap_adjustment must be true or
false, got 'False'", and `create_pv_system`, `create_model_chain`,
`simulate_pv_output` and `wired_dc_capacity_kw` refuse the module they wire
with the same message. It is the first check of the custom module
parameters, ahead of the reach refusal the task 1372 line describes, so a
NaN `EgRef` under a set `temperature_coefficient` gets this message. The
0.5.0 tag builds such a `PVConfig` and its system, and passes these keys to
pvlib as given, through the same physical IAM and no-loss spectral models;
with pvlib 0.15.1, one given as text raises `TypeError`, numpy's
`UFuncTypeError` among them, when the system is simulated, a NaN simulates
to no AC with no error, and the text "False" as `cap_adjustment` turns the
cap on. A stored run whose config carries a NaN or infinite one no longer
reads: its `StoredRunUnreadable` names `PVConfig`'s refusal. A key given as
`None`, such as a `k` or `n_ar` meant as pvlib's default, is now refused:
leave the key out instead. Consumers that pass such a module give these keys
as numbers and `cap_adjustment` as a bool, and expect the refusal where they
build the `PVConfig`, when they re-pin; code that catches `ValueError` needs
no change, while code that caught the `TypeError` of a key given as text
catches `ValueError` instead.

**Task 1473.** `PVConfig` also refuses, when it is built, `custom_module_params` that give
`temp_ref` at or below −273.15, absolute zero in °C, or `irrad_ref` or
`I_L_ref` at or below 0: pvlib's single-diode models divide by `temp_ref` in
kelvin and by `irrad_ref`, and no module has a photocurrent of 0 or less at
its reference conditions. The refusal is a `ConfigurationError`, a
`ValueError`, naming the key, its value and the domain, e.g. "Module
parameter temp_ref must be greater than -273.15, got -273.15", and
`create_pv_system`, `create_model_chain`, `simulate_pv_output` and
`wired_dc_capacity_kw` refuse the module they wire with the same message.
It is part of the rule the task 1440 line describes, so it reads the module
in every form, with or without a set `temperature_coefficient`, ahead of the
reach refusal the task 1372 line describes, and a NaN, infinite or text
value still gets that rule's "must be a finite number". Under a set
`temperature_coefficient`, a custom CEC module whose modelled maximum power
at STC is 0 W, such as one whose `I_L_ref` or `R_sh_ref` is 1e-300, also
gets that reach refusal. No row of pvlib's CECMod or SandiaMod libraries is
refused. The 0.5.0 tag builds such a `PVConfig` and its system, ignoring the
coefficient on custom module parameters; with pvlib 0.15.1, a 4 kW system at
Bristol over a clear June day raises `ZeroDivisionError` when simulated with
a `temp_ref` of −273.15, yields no AC, with no error, with an `irrad_ref` or
`I_L_ref` of 0 or an `I_L_ref` or `R_sh_ref` of 1e-300, and yields 56 kWh
with an `I_L_ref` of −1, against 21.69 kWh with the module's own row. A
stored run whose config carries a module outside these domains no longer
reads: its `StoredRunUnreadable` names `PVConfig`'s refusal. Consumers that
pass such a module give these keys values inside their domains, and expect
the refusal where they build the `PVConfig`, when they re-pin; code that
catches `ValueError` needs no change, while code that caught the
`ZeroDivisionError` of a `temp_ref` of −273.15 when simulating catches
`ValueError` instead.

**Task 1559.** `WeatherCache` no longer creates its directory when it is built: its first
`put` creates it, parents included, and a `put` that raises `ValueError` for its
frame's timezone creates nothing. `get` on an absent directory returns `None`,
`invalidate` `False` and `clear` `0`, as on an empty one. So `WeatherCache()`,
`get_weather_cache()`, `weather.default_weather()` and `fleet.default_runner()`
touch no file, and none of them fails where the directory cannot be created, as
in a working directory the process cannot write; the first `put` there raises
that `OSError` instead. The 0.5.0 tag's constructor creates the directory it is
given, else `.cache/weather` under the working directory, raising any `OSError`
from doing so. Consumers that use the cache only through `get`, `put`,
`invalidate` and `clear` need no change when they re-pin; code that lists
`cache_dir`, or writes files into it, before any `put` first creates it with
`cache_dir.mkdir(parents=True, exist_ok=True)`.

**Task 1691.** `Battery.config` is a settable property instead of a plain instance attribute,
still read and assigned as on the 0.5.0 tag. Assigning a `BatteryConfig` makes
the battery follow the new config before the assignment returns: its `soh` is
now the new config's `resolved_soh`, where the tag kept the SOH the battery was
built with; its SOC envelope and what reads it (`soc_envelope`,
`effective_capacity_kwh`, `min_soc_kwh`, `max_soc_kwh`, `usable_capacity_kwh`
and `soc_fraction`), its `grid_charge_target_kwh` and its power limits follow
too. Capacity and the power limits followed at once on the tag too. As on the
tag, the battery's own `min_soc_fraction`, `max_soc_fraction`,
`charge_efficiency` and `discharge_efficiency` survive the assignment, and the
new config's values for them are not applied. `soc_kwh` is untouched and is not
checked against the new envelope. A config whose capacity times its SOH is not
above 0 raises `ConfigurationError`, which is a `ValueError`, and leaves the
battery unchanged; the tag accepted it. Consumers need no change when they
re-pin: one that reassigns `config` now gets a battery consistent with it, SOH
included.

**Task 1740.** `scenario_knobs.Knob` has a new required field, `target`, a value of the new
enum `KnobTarget`: `HOMES`, `SEG_RATE` or `FINANCE`, saying which part of a
scenario the knob's `apply` edits. The five install, load and degradation knobs
are `HOMES`, `seg_tariff_pence_per_kwh` is `SEG_RATE`, and the flat
grid-services knob and every finance knob are `FINANCE`. `fleet sweep --param`
refuses a knob whose target is not `HOMES`, naming the knob as written, its
canonical name and what it sets, and listing the knobs it sweeps, before it
reads the scenario: such a knob leaves every home's simulation as it was, so
every point would simulate the same fleet. The 0.5.0 tag has no such refusal,
and task 971's `--param`, on main since the tag, simulated every point of such a
sweep identically. Its `--help` and its refusal of a name that is neither a knob
nor a variable now list only those knobs. A sweep point's value label, in
`fleet sweep`'s fleet names, CSV file names and summary table and in
`config.parse_sweep_fleet_configs`' fleet names, is at four decimals, or at the
fewest more that tell the sweep's points apart, from the new
`config.sweep_value_labels(values)`; points closer than 1e-4 no longer share a
label, and so no longer overwrite each other's CSV. Where such a label would be
longer than any float's `repr`, 24 characters, every point of the sweep is
labelled by its value's `repr`, so a label always fits in a file name, and
`sweep_value_labels` refuses a value that is not finite with a
`ConfigurationError` naming its index and the value. `config.sweep_point_fleet`
takes that label in place of the value. When they re-pin, consumers build a
`Knob` with `target=`, call `sweep_point_fleet` with a label from
`sweep_value_labels`, and expect wider names only for points closer than 1e-4.

**Results that move** — each entry: which figure moves and by how much where measured (task N).

**Task 182.** A tariff whose periods share one rate has no cheap period, so time-of-use
dispatch on it is self-consumption. The 0.5.0 tag classifies a minute as cheap
when its rate is at or below the mean of the period rates, so every minute of a
flat tariff such as `TariffConfig.flat_rate(0.25)` or
`economy_7(off_peak_rate=0.25, peak_rate=0.25)` is a cheap minute there;
`simulate_timestep_tou` holds the battery through all of them and imports the
whole shortfall. Task 182 changed that on `main`, and task 838 carries it on: a
flat tariff's `cheap_minutes_of_day` is empty and `is_cheap_at` is `False` at
every minute. A 2 kW shortfall for an hour against a fresh
`Battery(BatteryConfig.default_5kwh())` (2.5 kWh stored) at 03:00 on a flat
0.25 £/kWh tariff discharges 0 kWh and imports 2.0 kWh (£0.50) on the tag, and
discharges 1.95 kWh and imports 0.05 kWh (£0.0125) now, the result
`simulate_timestep` returns with no tariff. A home goes the same way under
`simulate_home`, and so under `FleetRunner` and `home run`. On the tag, a
`HomeConfig` whose `dispatch_strategy` is `'tou_optimized'` on a flat tariff,
with a battery that names no strategy of its own, runs through
`simulate_timestep_tou` (task 904's note), so its battery never discharges over
the whole run and only charges from surplus PV; it now discharges as
self-consumption does. The `GridChargeContext` that `simulate_timestep` builds
from a tariff for a grid-charging battery changes with it: its
`is_cheap_period` is `True` at every minute of a flat tariff on the tag and
`False` at every minute now. Yet no built-in dispatch charged from the grid on
a flat tariff on the tag: `compute_grid_charge_power_kw` refused a charge whose
peak rate does not cover the round-trip loss, and a flat tariff's peak rate,
being its current rate, never covers it. So grid-charge figures do not move.
What does change is the `is_cheap_period` that a consumer's own
`DispatchStrategy` receives in `grid_charge_ctx`. Tariffs with a rate spread
classify as before task 182, apart from what task 838's note describes.
Consumers who run time-of-use dispatch on a flat tariff, through
`simulate_timestep_tou` or through `simulate_home` (and so `FleetRunner` and
`home run`) with a `HomeConfig` whose `dispatch_strategy` is `'tou_optimized'`,
re-baseline the figures built on that dispatch when they re-pin. Consumers
whose own `DispatchStrategy` reads `grid_charge_ctx.is_cheap_period` on a flat
tariff check what it does now that the flag is `False`. Other consumers need no
change.

**Task 236.** `create_pv_system`, `create_model_chain` and
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

**Task 240.** `create_pv_system` and `simulate_pv_output`
no longer treat a battery inverter/charger as a candidate inverter, so they pick
a different inverter for 23 of the 992 census configs; the 0.5.0 tag may pick a
battery inverter/charger. Annual AC moves by +4.03% at 7.2 kW DC and +1.92% at
7.3 kW, and by +3.72% at 2.6 kW, all with the inverter unset; by +11% to +44%
for 0.3–1.0 kW arrays on 3.0, 3.68 and 5.0 kW inverters; and by −3.42% for
0.7–1.0 kW on 3.68 kW. The headline 3, 4, 5 and 6 kWp configs keep their picks
([pv-inverter-string-matching.md](pv-inverter-string-matching.md) §7). Consumers
re-baseline the figures for those configs when they re-pin.

**Task 252.** `PVConfig` gains a last keyword,
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

**Task 285.** `get_tmy_data` multiplies the TMY's `ghi`,
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

**Task 460.** `simulate_fleet`, `simulate_fleet_iter` and
`simulate_multi_sweep_iter`, and so `solve_cost_recovery_rate`'s default
`simulate`, fetch each distinct home location's TMY once, in the calling
process, and pass it to their worker processes. So a `WeatherCache` installed
with `set_weather_cache` now serves a parallel fleet under every
multiprocessing start method. On the 0.5.0 tag, a worker started by
`forkserver` (Linux's default from Python 3.14) or `spawn` (macOS's default)
ignored that cache, read the working directory's `.cache/weather` and fetched
PVGIS on a miss: offline the run failed with `WeatherDataError`, and online it
simulated from PVGIS's live TMY instead of the injected one.

**Task 580.** a `Battery` whose SOC an assigned SOC limit
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

**Task 708.** an EV whose `EVConfig.smart_charging_mode`
is `"solar"` or `"off_peak"` now charges only while it is home. Each day's
session is one unbroken run inside the stay from `arrival_hour` to
`departure_hour`, covering as much of the mode's window (10:00–16:00, or
Economy 7's 00:30–07:30) as it can, on either day of an overnight stay, and
starting as early as it can. A window too short for the charge is used whole,
with the rest charged just before it opens, or from arrival when that is later.
On the 0.5.0 tag such a session started when the window opened and could run
past departure: a 3.6 kW, 35 kWh off-peak EV home from 18:00 to 07:00 charged
from 00:30 until 10:14, and now charges from 21:16 until 07:00. The tag also
looked only at the arrival day's solar window, and only at the next night's
off-peak window for an overnight stay: a 7 kW, 35 kWh solar EV home from 18:00
to 12:00 charged from 18:00 until 23:00, and now charges from 07:00 until 12:00
the next morning. `"none"` is unchanged. The demand that `simulate_home` and
`simulate_fleet` return changes for homes with such EVs, and so do the figures
built on it, `solve_cost_recovery_rate`'s included; consumers re-baseline them
when they re-pin.

**Task 778.** `SummaryStatistics` gains a last keyword,
`window`, defaulting to `None`: the `SimulationWindow`, imported from
`solar_challenge.timebase`, that its totals were computed over. Building one
raises `ValueError`, naming both values, when `window` is set and
`simulation_days` is not its `days`. Code that builds one without a window
needs no change. `calculate_summary` sets `window` to its results' `window`,
and `simulation_days` to that window's `days`: the calendar dates the results'
index covers on its own clock, first and last both counted. The 0.5.0 tag
counts the whole 24-hour days between the index's first and last rows, plus
one. So for an index that crosses the October clock change but not the March
one, the tag counts one day more: 62 for a `Europe/London` minute index from
2024-10-01 00:00 to 2024-11-30 23:59, which now reads 61. A `simulate_home` run
whose last day is the October change day counts its window's days, 2 for
2024-10-26..27, as the tag does. `FleetSummary.simulation_days`, read from the
first home's summary, changes the same way. The web app stores each summary's
window, its days as ISO 8601 dates and its cadence as an ISO 8601 duration
such as `P0DT0H1M0S`; a summary it stored before the field existed loads with
`window` `None`. Consumers that read `simulation_days` for windows crossing the
October change re-check them when they re-pin.

**Task 779.** `simulate_community` reads each row's length
from the window of the fleet's index, `SimulationWindow.of_index` of
`FleetResults.total_grid_export`'s index. It does so in both sharing modes,
whether or not it bills. The community battery steps at the window's cadence,
and billing prices each row's kWh over it. It now raises `ValueError` for a
fleet index no window describes: an empty index; one row without a
fixed-duration `freq`; unevenly spaced rows, naming the first position whose
gap differs and both gaps; or an index that is not a `DatetimeIndex`, naming
its type and dtype. The 0.5.0 tag reads the length from the index's first two
rows, and takes one minute for a single row or an empty index. The only
refusal it states is of a billed index whose last gap differs from its first,
so it prices a fleet whose index lacks one middle row with no error. The fleets
`simulate_fleet` returns are spaced one minute apart, so their community
results are unchanged. Consumers that build a `FleetResults` on another index
re-check it when they re-pin.

**Task 810.** `simulate_pv_output` and
`create_model_chain` apply a `PVConfig`'s ageing to each array's DC power
before the inverter, in the same step as `system_losses`, carrying task 284's
change; the 0.5.0 tag multiplies `simulate_pv_output`'s AC by the degradation
factor, after the inverter has clipped, and leaves `create_model_chain`'s AC
un-aged. So an aged inverter-limited array now keeps more of its new AC, and an
unclipped one slightly less: on Bristol's scaled TMY at age 20, 6 kW on a
3.68 kW inverter keeps 0.9186 of its new annual AC instead of 0.9000, and the
default sizes keep 0.8976–0.8991 ([pv-system-losses.md](pv-system-losses.md)
§4). A run chain's `results.losses` holds the combined fraction of DC power
kept. `apply_degradation` is unchanged, so applying it to `simulate_pv_output`'s
output for an aged `PVConfig` ages the array twice. Consumers re-baseline every
figure for an aged PV system when they re-pin, `project_multi_year`'s later
years and the cost-recovery rate included.

**Task 841.** `TariffConfig.economy_7()` and `TariffConfig.economy_10()` built without rates
now charge 0.13 £/kWh off-peak and 0.35 £/kWh peak (ruling D34), the rates the
new `tariff.PRESET_RATES`, outside `__all__`, states for each preset. The 0.5.0
tag charges 0.09/0.25 £/kWh on Economy 7 and 0.08/0.27 £/kWh on Economy 10.
Their signatures' defaults render the new values, and the `get_rate`,
`rates_for` and `peak_rate` of such a tariff, and
`calculate_bill` over it, read the new rates. A scenario `tariff:` block of
type `economy_7` or `economy_10` that sets no rate is charged them too. Their
cheap minutes, the task 838 line's `cheap_minutes_of_day`, are unchanged,
Economy 7's 420 and Economy 10's 600, since both stay two-rate. The scenarios
`example-economy7.yaml`, `bristol-arbitrage.yaml` and `bristol-phase1-flex.yaml`
no longer restate Economy 7 at 0.09/0.25 £/kWh, so they re-price. Measured on
base f12e6a1 over 2024, `solar-challenge home run
scenarios/bristol-arbitrage.yaml --start 2024-01-01 --end 2024-12-31` prints a
grid import cost of £298.84 and a net cost of £-69.05, where it printed
£208.96 and £-158.93, on the same 1844.0 kWh of import. `solar-challenge
finance run scenarios/bristol-phase1-flex.yaml` gives its representative
householder an import cost of £314.48 (was £253.89), a total outlay of £827.92
(was £727.72), a saving vs baseline of £274.25, 24.9% (was £366.45, 33.5%), and
a self-consumption fraction of 34.7% (was 51.5%), and its fleet bill a mean of
£832.76 (was £728.06) and a median of £827.90 (was £727.69).
`example-economy7.yaml`'s load is stochastic with no seed, so each run draws
its own profile: its `home run` over 2024 printed a grid import cost of
£337.87 and £346.85 in two runs after the change, and £240.05 in one before.
Consumers that keep the tag's prices pass `off_peak_rate` and `peak_rate`
explicitly when they re-pin, to either classmethod or as keys of a scenario's
preset block; consumers that already pass both rates need no change.

**Task 865.** `compute_soh` counts one
equivalent full cycle per usable capacity of discharged energy, where the 0.5.0
tag counts one per two usable capacities, so its cycle fade doubles:
`compute_soh(12.0, 12000.0, 4.0, BatteryConfig(capacity_kwh=5.0))` returns 0.61
where the tag returns 0.685. Its signature is unchanged, and so is a single
run's SOH, which counts no throughput. Multi-year battery SOH, later-year
own-use and the cost-recovery solve move for battery fleets
([cost-recovery-finance-model.md](cost-recovery-finance-model.md) §4). The
platform needs no code change: it does not call `compute_soh`, though the rate
its `recommend_rate` takes from `solve_cost_recovery_rate` moves for a battery
fleet.

**Task 900.** `Battery.charge` returns the energy it drew from the bus, before
`charge_efficiency`; the 0.5.0 tag returns the energy stored, after it. Its
state-of-charge update is unchanged, so no dispatch decision moves.
`simulate_timestep`'s and `simulate_timestep_tou`'s `grid_export` no longer
includes the battery's PV charge loss, and their `grid_import` includes all the
grid energy grid charging drew. `EnergyFlowResult.battery_charge` and
`grid_charge`, `SimulationResults`' `battery_charge` and `grid_charge` series and
`SummaryStatistics`' `total_battery_charge_kwh`, `total_grid_charge_kwh` and
`total_pv_charge_kwh` are drawn energies, 1 / `charge_efficiency` times the tag's
(2.56% higher at the default 0.975); `total_grid_to_demand_kwh` is unchanged, and
so are every field's name and type and `validate_energy_balance`'s formula.
Measured on `scenarios/bristol-arbitrage.yaml` over 2024-01-15 with the committed
Bristol TMY: grid import 8.116274 to 8.170810 kWh, export 0.003555 to 0.000000
kWh, grid charge 2.126889 to 2.181425 kWh, import cost £1.383597 to £1.388505.
Consumers re-read any stored-basis assumption on `battery_charge` or
`grid_charge` when they re-pin: the energy stored is `charge_efficiency ×
battery_charge`, and the state of charge changes by `charge_efficiency ×
battery_charge − battery_discharge / discharge_efficiency`. Runs saved before
this change keep the stored basis and the export it booked.

**Task 906.** `generate_load_profile` gains a last,
keyword-only parameter, `household_model`, which defaults to the new
`solar_challenge.load.richardsonpy_household`, so a call without it runs
richardsonpy as on the 0.5.0 tag. Its type is `HouseholdModel`: it is called
once per stochastic window with the `LoadConfig` and the window's dates, and
returns a `DaySimulator`, called once per date for that day's 1,440 one-minute
values in W. A model that raises, or gives a day of another length, gives the
Elexon profile with the fallback warning. A call now leaves the caller's
`random` and `numpy.random` states as it found them, and stochastic windows run
one at a time across threads, so seeded profiles generated concurrently equal
their serial ones. An unseeded profile draws fresh entropy, where on the tag
one generated right after a seeded profile continues that profile's generators,
and so repeats on every run. A seed outside 0 to `2**32 - 1` now gives a
reproducible stochastic profile, distinct for s and −s, where the tag gives the
Elexon profile with a warning. A seed from 0 to `2**32 - 1` gives the tag's
profile, with one exception: in a window that starts in summer time and runs
past the change that sets the clocks back (October in Europe/London), each day
from the one after the change through the day the clocks next go forward is now
simulated as its own weekday and day of the year, where the tag simulates it as
the day before's. Such a window's profile differs from the tag's on every day,
since a window is scaled to its seasonal energy as a whole, and that energy now
counts each of those days at its own month's factor, where the tag counts the
first of a month at the month before's: at 3,400 kWh a year, 2024-10-26 to
2024-11-02 has 73.59 kWh, where the tag gives 72.19. Consumers need no change
when they re-pin; those with such windows re-baseline the figures built on
them.

**Task 1362.** `Battery.discharge` never returns more than the
requested power, capped at `max_discharge_kw`, times the duration. The 0.5.0
tag returns the energy it withdraws times `discharge_efficiency`, which for
fewer than 1% of requests at the default 0.975 rounds one ulp above that
product; the state of charge still falls by the energy withdrawn. So a step's
`battery_discharge` no longer exceeds the self-consumption it is part of, where
the tag's can by an ulp: from `simulate_timestep_tou`, and from
`simulate_timestep` under any dispatch strategy that asks the battery for no
more than `demand_kw - generation_kw`, as each built-in strategy does. Over
such steps, `SummaryStatistics.total_battery_discharge_kwh` from
`calculate_summary` no longer exceeds `total_self_consumption_kwh` either.
`simulate_timestep_tou`'s expensive-period discharge now asks the battery for
`demand_kw - generation_kw` whenever that is above 0, as the dispatch
strategies do, rather than for the step's shortfall energy divided by its
duration whenever that energy is above 0. On a step with both PV and a
shortfall, that quotient can round an ulp away from `demand_kw -
generation_kw`; on a step whose demand exceeds its generation by too little
for their energies to differ, the tag asks for nothing, where the battery now
delivers that difference in power for the step. So on a tariff with no rate
spread, a step whose demand exceeds its generation gives exactly the results
`simulate_timestep` gives under its default self-consumption strategy; a step
with surplus PV can still differ from them in the last digit. Each of these
changes moves a result by an ulp-sized amount; consumers need no change when
they re-pin.

For readers of [cost-recovery-finance-model.md](cost-recovery-finance-model.md): the entries below are its release notes, and each § in them is a section of that doc.

**Task 219.** CBS revenue no longer deducts the grid-charge cost (§4); the 0.5.0 tag still does.

**Task 271.** on a simulated window under 360 days, `project_multi_year` annualises own-use, export, import and battery-discharge kWh (§4, §7.6); the 0.5.0 tag sums them over the window.

**Task 281.** with `self_consumption_override` set, each home's own-use is capped at its demand and the surplus generation is counted as export (§3, §4); the 0.5.0 tag bills override × generation uncapped.

**Task 295.** each simulated age's battery SOH counts the battery throughput from installation to that age (§4, §7.6); the 0.5.0 tag ages each seed with the throughput up to the previous seed only, so a battery fleet's mid-life battery SOH and own-use read high there.

**Task 307.** on a home with no tariff configured, the override path prices its grid import at the retail baseline rate, with the physics path's `UserWarning` (§3); the 0.5.0 tag prices that import at £0.

**Task 308.** with `self_consumption_override` set, `project_multi_year`'s own-use revenue, and so the cost-recovery solve's rate base, is each home's capped override own-use, the own-use its bill charges (§2, §4, §5); the 0.5.0 tag keeps both on basis C.

**Task 656.** `project_multi_year`, and so `solve_cost_recovery_rate`, raises `ValueError` when a simulated age, seed or bisection trial, gives a NaN or infinite value for any aggregate §4 requires to be finite, naming the age and each such aggregate with its value; the 0.5.0 tag projects a NaN own-use or revenue on a one-year asset life as 0 kWh and £0 and passes an infinity through, drops a bisection trial whose aggregate is NaN, accepts a non-finite battery discharge, and stops on a non-finite seed of a longer life in scipy's PCHIP with "`y` must contain only finite values", which names no age.

**Task 702.** `YearPoint.fleet_self_consumption_kwh`, the fleet's billed own-use (§4) and the cost-recovery solve's rate base (§5), is renamed `fleet_billed_own_use_kwh`; the 0.5.0 tag has the old name. `project_multi_year` also no longer floors a year's `fleet_revenue_gbp` at £0, so a `simulate` whose fleet earns a negative revenue projects, and the solve prices, that loss; the 0.5.0 tag projects it as £0. Its adaptive refinement measures each metric's interpolation error against the magnitude of that metric's age-0 value, so a fleet whose revenue is negative at age 0 and varies with age converges as the fleet earning the mirror revenue does; the 0.5.0 tag divides that fleet's revenue error by 1e-9, so its bisection typically runs to `MAX_NODES` and reports a meaningless `interp_error_estimate`. Fleets `simulate_fleet` builds are unaffected: their own-use, SEG and grid-services income is never negative.

**Task 778.** the `sim_days_h` by which a home's window under 360 days is annualised (§4, *Annual basis*) is its calendar days, as `calculate_summary` now counts them. For a window that crosses the October clock change but not the March one, such as 2024-10-01 to 2024-11-30, that is 61 days, so `k_h = 365/61`; the 0.5.0 tag's `simulation_days` counts 62.

**Task 782.** each home's window totals are scaled to the window's year by `k_h = year_days / days`, whatever the window's length, in the bills (§3) and in the projection (§4, *Annual basis*); `year_days` is 365 or 366 for a window within one calendar year and 365.25 for one that crosses a new year. The 360-day threshold is retired, and with it the rule the task 271 and 778 notes describe, so a window of 360 to 365 days is scaled too, and a 2024 window by 366/days, where the 0.5.0 tag's bills scale a window under 360 days by 365/days and any other by 1. The standing charge covers `year_days` days (§3): 366 in 2024, where the tag always bills 365. `householder_bill` no longer emits the tag's short-period `UserWarning`, nor `project_multi_year` the short-window one added since the tag. `householder_bill` and `bill_distribution` raise `ValueError` for a summary with no window, naming `calculate_summary`, and for a `simulation_days` other than their summaries' own, naming both; `householder_bill` for own-use below 0 or above the window's `total_demand_kwh`, naming both; and `bill_distribution` for summaries over different windows, as `project_multi_year` does for a fleet whose homes cover different windows, naming both windows (§3, §4). `BillDistribution` and `MultiYearCurve` carry `annualised_from`, the window their yearly figures were annualised from, None for `spreadsheet_revenue_curve`'s curve of yearly assumptions. §7.6's physics column, three June days of 2024, now scales by `k = 366/3 = 122`, not 365/3. When they re-pin, consumers re-check any bill, projection or solved rate of a window that is not one whole non-leap calendar year, give each summary they bill its window (`calculate_summary` sets it), pass the summaries' own `simulation_days`, and read `annualised_from` where they relied on the short-period warning to flag a short window.

**Task 783.** `generate_finance_report` (`finance run`) and `generate_config_ranking_report` (`optimize configs`) print, under their first heading, "*Yearly figures are extrapolated ×<annualisation_scale, 3 dp> from a <days>-day window (<first day> to <last day>), not whole calendar years.*" when their bills' `annualised_from` window runs other than from 1 January to 31 December (§4, *Annual basis*; §9). The notice replaces the short-period warnings that task 782's note retires. A distribution with no `annualised_from`, which only a hand-built one has, renders none, and neither does a ranking with no feasible config. The CLI's status lines and `optimize configs`' large-sweep warning count the run's calendar days: a run that starts on GMT and ends on BST, such as 2024-03-31 to 2024-04-01, counts 2 days where the 0.5.0 tag counts 1. When they re-pin, consumers that parse either report expect the notice paragraph after its first heading.

**Task 801.** `project_multi_year` prices grid-services income from each simulated age's own fleet, seed and bisection-trial ages alike (§4, §8.1), so capacity-at-events income falls with battery SOH; the 0.5.0 tag books the age-0 event figure at every age. A flat rate prices the batteries of the `home_configs` that `simulate` returns, where the 0.5.0 tag sums the scenario's homes; `FleetRunner.simulate` pairs them with the homes each age simulates, the scenario's, so its flat figure is unchanged, and an injected `simulate` must return those homes' batteries (§4; task 1119's note). An event window the simulated period never enters is named in one `UserWarning` per projection (§4); the 0.5.0 tag prices it at £0 silently.

**Task 804.** The model's grid-services pricing is now named by `FinanceConfig.grid_services_model`,
which holds `NoGridServices()`, `FlatGridServices(g)` or a
`GridServicesEventsConfig`, in §4, §6's no-flex identity, §7's assumptions
table and §8.1, where the retired `grid_services_income_per_kw_per_year_gbp`,
`grid_services_events` and `grid_services_model_of` stood. No figure moves:
the migrated board scenarios load to the same pricing. Readers read §8 under
the new field name.

**Task 837.** Capacity-at-events income in `project_multi_year` and `finance run` is priced at the mean over event days of the fleet's daily firm spare capacity, under the events configuration's `delivery_baseline`, `operational` by default (§4, §8.1); the 0.5.0 tag takes the minimum over every in-window timestep of the season, so one minute at a battery's SOC floor zeroes that home for the whole season there. The finance report's capacity-at-events table adds the capacity available on 50% and on 90% of event days and the evening self-use an event displaces per event, shown for a single event window and as — for several, and that self-use's value per year, summed over the windows, £0 for a home simulated without a tariff; the income is gross of it (§8.1). Re-read any capacity-at-events figure taken from the 0.5.0 tag; flat and no-grid-services figures are unchanged.

**Task 848.** `scenarios/bristol-phase1-flex.yaml`, the board fleet, now sizes each battery's cheap-period grid charge by the `trailing_14_days` forecast (`docs/grid-charge-forecast.md`), where the 0.5.0 tag fills every battery to 90% every night. Measured on its 100 homes over 2024 on the committed Bristol TMY at task/848's step-14 commit (`docs/grid-charge-forecast.md` §6 says which, and why main's changes since leave the figures standing), against the same runs with `forecast: pv_blind`: per-home net cost (import cost less export at 4.1 p) £226.27 to £201.87 a year; grid charge 1,070.79 to 649.02 kWh and export 2,598.65 to 2,221.90 kWh a home; the mean householder bill at the scenario's 15 p own-use rate £832.76 to £850.60, as basis-C own use (demand − import, §2) rises by the import it replaces; mean fleet surplus £13,910 to £17,166 a year, min DSCR 1.83× to 2.11×, equity IRR 0.9% to 2.5% and payback 23.0 to 20.0 years; the solved cost-recovery own-use rate 7.96 to 7.35 p/kWh, and the mean householder outlay at it £714.21 to £691.32. Re-read any figure of this fleet taken from the 0.5.0 tag; a scenario whose `grid_charging:` block names no forecast is unchanged.

**Task 865.** each simulated age's battery SOH counts one equivalent full cycle per usable capacity of discharged energy (§4, *Battery ageing*); the 0.5.0 tag counts one per two usable capacities, so its cycle fade is half the configured `cycle_fade_per_equivalent_full_cycle`, and a battery fleet's later-year battery SOH and own-use read high there and its solved own-use rate low.

**Task 900.** On the physics path a battery's PV charge loss is no longer booked as export, so it no longer earns SEG income, and grid charging's charge loss is now imported, so import cost and the informational `total_grid_charge_cost_gbp` rise and basis-C own-use (demand − import, §2) falls by it; the 0.5.0 tag books the battery's charge on the energy it stored, after its charge losses. Measured on `scenarios/bristol-phase1-flex.yaml` (100 homes, 2024, committed Bristol TMY, at main 3dd45073 and with this change): export 260,369.288 to 259,864.839 kWh, SEG income (export at 4.1 p) £10,675.14 to £10,654.46; import 194,119.676 to 196,796.663 kWh, import cost £23,069.57 to £23,310.50; grid charge 104,402.491 to 107,079.478 kWh; basis-C own-use 163,131.393 to 160,454.406 kWh (−1.64%), so a solved own-use rate rises. Re-read any battery fleet's board figure taken from the 0.5.0 tag; a fleet without batteries is unchanged.

**Task 922.** Finance now prices each home's grid flows by how its simulated run was priced (`SummaryStatistics.pricing`, §3, §4), instead of inferring it from the pounds the run reported. A home on a £0 tariff is billed £0 of import with no warning, where the 0.5.0 tag billed it at the retail rate with the "no tariff configured" warning. With `self_consumption_override` set, a home that simulated no export earns the CBS its SEG at its own rate on the override's export: £49.20 on 1,200 kWh at 4.1 p, where the tag gives £0.00. A priced override home that simulated no import is billed the override's import at its tariff's time-weighted mean rate rather than at retail. Physics bills and projections do not move beyond float precision. When they re-pin, board readers re-check the bills of homes on a £0 tariff, the override-mode SEG revenue, and the solved own-use rates that read them.

**Task 925.** With `self_consumption_override` set (the spreadsheet assumption), each projection year's fleet export and import (`YearPoint.fleet_export_kwh` and `fleet_import_kwh`, §4) are now the override's split, Σ_homes generation − own-use and demand − own-use, which is the export the year's SEG revenue is priced on. So for a fleet on one SEG rate, a year's SEG revenue ÷ its fleet export is that rate. The 0.5.0 tag reports the simulated export and import beside SEG revenue priced on the override's export. Each home's bill does not move, and nor do each simulated age's own-use and revenue: the bill and the projection now read one ledger per home (§3, *One ledger per home*), which assembles the same figures once. The projection's adaptive choice of which ages to simulate now measures the fleet export's and import's interpolation error against the age-0 fleet generation and demand (§4, *Node selection*), not against their own age-0 values. So a fleet that imports nothing at age 0, under the override with own-use capped at demand or on the simulated basis with a battery covering its demand, no longer simulates up to 12 ages and reports an `interp_error_estimate` of billions of percent. On either basis a projection can therefore simulate different ages: its interpolated years, its `interp_error_estimate` and the solved rate that reads them can move, within the error target, while each simulated age's own figures do not. When they re-pin, board readers re-check projections and the solved rates that read them.

**Task 928.** The CBS-revenue projection (§4), the cost-recovery solve (§5) and the capex coupling (§6) are now in `projection.py`, above `finance.py`'s bill arithmetic, and their Source lines name it. No figure moves: a fake-simulator `finance run --project --cost-recovery --assumptions both` report is byte-identical before and after the move. When they re-pin, readers follow the Source lines to `projection.py`.

**Task 929.** Each projection year's revenue between simulated ages (§4, *Per-year revenue*) is now the own-use rate × that year's billed own-use / 100 plus the year's income, SEG plus grid services, with own-use and income each interpolated by PCHIP through their values at the simulated ages; revenue itself is no longer interpolated. The projection's choice of which ages to simulate (§4, *Node selection*) now measures the income's interpolation error, not the revenue's, against its largest value at the seed ages, and the own-use's against its largest value there, so it reads no own-use rate. So the cost-recovery solve (§5) is exact: its shifted line is a re-projection at every rate, and its solved rate no longer moves with the configured `own_use_rate_pence_per_kwh`. The 0.5.0 tag (solar-challenge-v0.5.0) interpolates revenue itself: on task 720's nodes its shifted line was off a re-projection by up to £38.74 in a year, and on the same nodes its solved rate moves by 0.017 p/kWh across configured rates of 0, 15 and 23 p. Board figures move with it, where review-all S8 estimated per-year revenue between simulated ages by £41–150 a year and the solved rate by at most 0.01 p/kWh. Measured on `scenarios/bristol-phase1.yaml` as `finance run` projects it (100 homes, 15 p own-use rate, the committed Bristol TMY), the simulated ages (0, 6, 12, 24), the `interp_error_estimate` (0.686 %) and every year's own-use do not move, and a year's revenue moves by up to £94.71 (year 17, £33,239.53 to £33,334.24), £22.83 a year higher on the mean, which at that fleet's mean own-use moves its solved rate by about −0.014 p/kWh (derived from the mean, not solved), more than S8's 0.01 p/kWh estimate. A fleet whose income is £0 at age 0, at a 0 p own-use rate, no longer simulates 12 ages and reports an `interp_error_estimate` of billions of percent. `solar_challenge.projection` gains `project_fleet(fleet, finance, *, simulate, error_target_pct=1.0)`, the projection of a `ScenarioFleet`, returning a frozen `FleetProjection` whose `curve` is `project_multi_year`'s and whose `age0_summaries` are each home's summary of the fleet simulated at age 0, in fleet order. When they re-pin, board readers re-check projections and solved rates; a library consumer that wants the age-0 summaries reads `project_fleet(...).age0_summaries`.

**Task 930.** `solar_challenge.projection` gains `CostRecoveryRun(projection, economics, solution)`, `run_cost_recovery(fleet, finance, *, simulate)` and `fewest_simulated_ages(asset_life_years)` (§5). `run_cost_recovery` projects a fleet once at the configured own-use rate, and that one projection gives its economics, its solve and the solve's outlay. `solve_cost_recovery_rate` is that run's solution: it bills its outlay on the projection's age-0 summaries, the same fleet it used to simulate a second time as `cr4-solve-age0`. So the solve now asks its simulator for 5 fleets at a 25-year life instead of 6, and its projection's warnings name the solve's caller. `optimize.run_sweep` makes one projection per config: 5 simulations at a 25-year life where main before this change asks 12, and 3 at a 3-year life where it asks 8. `ConfigResult` gains `baseline_own_use_rate_pence_per_kwh`, the configured rate its baseline pair is priced at. Its `baseline_outlay_gbp` now bills the new-install age-0 fleet with the scenario's SEG. The figure moves for scenarios whose batteries carry a configured age or SOH, because their age-0 battery is now at SOH 1.0: the 0.5.0 tag billed, for example, the calendar 0.88 of a 6-year battery. That figure is one axis of the board's Pareto front. `generate_config_ranking_report`'s second table is now headed '## Configured-Rate Trade-Off' and gains a 'Configured Rate (p/kWh)' column; the 0.5.0 tag prints '## Fixed-15p Trade-Off'. `finance run --project --cost-recovery` now asks for 6 simulations where main before this change asks 12, or 5 where the age-0 fleet is the bill run's (9 before). `optimize configs`' large-sweep warning counts at least `fewest_simulated_ages` per config's projection. The counts were measured with a constant stand-in simulator, on main at this task's merge base and on this change. When they re-pin, board readers re-check baseline outlays and the Pareto front on aged-battery scenarios. Report parsers read the new heading and column. Code that constructs `ConfigResult` passes `baseline_own_use_rate_pence_per_kwh`. A consumer that wants the projection, the economics and the solve from one projection calls `run_cost_recovery`.

**Task 936.** `project_economics` now prices the PV capex term (§6) on the new `MultiYearCurve.fleet_pv_dc_kw`, the PV DC the curve's generation came from, in kWp, refused at construction unless > 0 and finite: Σ `pv.wired_dc_capacity_kw` of the fleet's homes for a `project_fleet` or `project_multi_year` curve, the whole modules of the template the simulator wires, and `n_homes × pv_kwp` for `spreadsheet_revenue_curve`; the roof, battery and inverter terms stay per home. The 0.5.0 tag (solar-challenge-v0.5.0) prices each home's nameplate `pv_config.capacity_kw`, modules the projection never generates from. Measured on `scenarios/bristol-phase1.yaml` (100 homes, the committed Bristol TMY), the PV basis moves from 430.0 to 420.4494 kWp, so capex moves from £630,000.00 to £620,449.40, debt from £95,000.00 to £92,612.35, annual debt service from £10,430.49 to £10,168.34, the minimum DSCR from 1.998 to 2.050, the equity IRR from 2.20 % to 2.50 % and the net surplus from £153.36 to £154.93 a home a year; payback stays at year 20, every year's revenue and own-use are bit-identical, and the solved own-use rate moves from 7.5071 to 7.4139 p/kWh (the 0.5.0 figure derived from its curve by the solve's closed form, §5, which gives this tree's live solve to 15 significant figures). CR6's synthetic no-flex anchor (§7), whose 5.5 kWp homes each wire 5.606 kWp, moves from £775,000 to £785,599.20 of capex and from £131,250 to £133,899.80 of debt, its solved rate from 12.2232 to 12.3104 p/kWh and its saving from £226 to £224, and its 0.70-override solve (§5) from 7.190096 to 7.241437 p/kWh; the [FIN] spreadsheet gate stays £775,000 on 550 kWp. An optimize config of 3 kWp homes is priced at the 2.803 kWp each wires. When they re-pin, board readers re-read capex, payback and solved rates, and a consumer that constructs `MultiYearCurve` by hand passes `fleet_pv_dc_kw`.

**Task 970.** §9's report, with its Cost-Recovery Analysis block, is now rendered by `board_report.generate_finance_report` (`src/solar_challenge/board_report.py`), where the 0.5.0 tag renders it in `output.generate_finance_report`; the move leaves its text byte for byte as it was. A cost-recovery binding outside `'floor'`, `'rate_clamped_zero'` and `'infeasible_above_retail'` is now refused with a `ValueError` naming it, in the finance report and in `optimize configs`' config ranking, where the finance report rendered it as *✘ INFEASIBLE: required rate exceeds retail*; every solution `solve_cost_recovery_rate` returns carries one of those three, so no report of one changes. Readers who follow §9's Source to the code read it from `board_report.py` when they re-pin.

**Task 973.** `finance run --assumptions` now drives the projection, the project economics and the cost-recovery solve from each mode's own `FinanceConfig`, as it already drove the bill (§3, *Override (spreadsheet-assumption) path*): `physics` clears any override, `spreadsheet` keeps the scenario's or sets 0.70, and `both` runs the two, one projection per mode. The 0.5.0 tag computes the economics and the solve once, on the scenario's `finance:` block whatever the mode, so its `physics` economics carry a scenario's YAML override and its `spreadsheet` economics ignore the 0.70 it bills at. Every table of the bill, project-economics and cost-recovery blocks, the per-home bill distribution and the outlay at the solved rate among them, is now one value column per mode, headed `Physics` or `Spreadsheet (<override>% self-consumption)` (§9); in those blocks the '## Householder Bill (Physics Assumptions)' and '## Householder Bill — Physics vs Spreadsheet Assumptions' headings, and the single 'Value' column, go. The flexibility-value block (`--flex-band`), which no mode changes, renders once with its own columns, as before. The figures that move are those of a mode the scenario's finance block is not on. On `scenarios/bristol-fin-calibration.yaml`, whose block sets 0.70, `--assumptions physics` over 1-7 June 2024 now reports a mean fleet surplus of £50,328 a year, min DSCR 3.95×, equity IRR 11.3% and a CBS net surplus at the solved rate of £138.60 a home, where it reported the spreadsheet's £53,486, 4.20×, 11.9% and £117.92; its payback, 9.0 years, and its solved rate, clamped to 0.00 p/kWh, do not move. On `scenarios/bristol-phase1.yaml`, which sets no override, `--assumptions spreadsheet` over the same week now solves at 2.65 p/kWh, with a mean fleet surplus of £37,129, min DSCR 4.22×, equity IRR 11.9% and payback in 9.0 years, where it reported physics' 2.14 p/kWh, £28,804, 3.37×, 8.7% and 11.0 years. Readers of the report read each figure's mode from its column's header when they re-pin.

**Task 974.** The finance report renders the grid-services income beside the economics it changes (§8.1, §9): whenever the scenario's pricing books grid services, with or without `--flex-band`, a Grid Services Income section follows Project Economics, naming the model with its band and delivery baseline, or the flat rate; giving, when the run projects, the income each mode's projection booked at year 1 and at year N; and holding this window's fleet table, the same under every assumption, with the capacity-at-events rows that rendered only inside the flexibility-value block, the single-window rule now covering the per-event capacity row too. The flexibility-value block's grid-services row is now the booked income per battery home and per kW, under a headline of the band's time-shift plus it, where the 0.5.0 tag shows the consulting band whatever the scenario books; a scenario that prices no grid services shows the consulting figure there labelled not booked, and the block cites docs/flexibility-buildability.md where it printed "(PRD §6)". Re-read any flexibility-value headline taken from the 0.5.0 tag for a scenario that books grid services: its grid-services figure was the consulting band, not the scenario's income.

**Task 1119.** `project_multi_year`, and so the cost-recovery solve, raises `ValueError` when its `simulate` returns, for an age t, a fleet that is not §4's F_t, the scenario's homes at age t: one whose `home_configs` hold another number of homes, or do not carry the scenario's batteries in order, state of health aside. Grid-services income is priced from F_t's batteries (§4), so such a fleet would misprice it, a flat rate at £0 for a fleet returned without batteries. The message names the age's fleet, `proj-age-<t>`, then both numbers of homes, or the first home whose batteries differ and both batteries; the 0.5.0 tag accepts such a fleet. When they re-pin, consumers whose injected `simulate` builds its own results return the batteries of the homes it is asked to simulate, as `FleetRunner.simulate` does.

**Task 1270.** `optimize configs` gains `--assumptions`, `physics` (the default) or `spreadsheet`, and ranks every config, computes the configured-rate trade-off and runs the sensitivity panel under that mode's `FinanceConfig`, `finance.with_own_use_basis` of the scenario's, as `finance run` computes each mode (§3, *Override (spreadsheet-assumption) path*): `physics` clears any override, and `spreadsheet` keeps the scenario's or sets 0.70. `--assumptions both`, which names two assumptions, is refused as a configuration error before any simulation; run once per assumption. The 0.5.0 tag ranks under the scenario's `finance:` block as written, so on `scenarios/bristol-fin-calibration.yaml`, whose block sets 0.70, the ranking, the trade-off and the sensitivity panel are now physics' where the tag ranked under the override; `--assumptions spreadsheet` reproduces the tag's ranking. Scenarios that set no override rank as before. The ranking report now names its assumption on its first line, `Self-consumption assumption: **Physics**` or `Self-consumption assumption: **Spreadsheet (70% self-consumption)**`, above `## Cost-Recovery Rank`. Readers of the report read the assumption from that line when they re-pin, and pass `--assumptions spreadsheet` to rank a calibration scenario under its override.

**Additive** — each entry (task N).

**Task 200.** `TariffConfig` gains one read-only member, `peak_rate`, its highest period
rate in £/kWh, which the 0.5.0 tag lacks. Consumers need no change when they
re-pin.

**Task 230.** `TariffConfig` gains `rates_for(index)`, the rate in £/kWh at each timestamp
of a `pandas.DatetimeIndex`, in order, as a float64 `numpy.ndarray`. Each rate
is the one `get_rate` returns for that timestamp, at its wall-clock minute. The
0.5.0 tag lacks it. `calculate_bill` reads its rates through it and sums the
rows' costs with numpy, where the tag adds them one row at a time. Its total can
therefore differ from the tag's in the last digits, about 4e-14 relative on a
minute year. A NaN energy still gives a NaN bill, and a `pd.NA` energy now gives
one too, where the tag returns `pd.NA` itself. Consumers need no change when
they re-pin, unless they test a bill with `is pd.NA`: `pd.isna` reads both.

**Task 318.** `SimulationResults`, reached through
`FleetResults.per_home_results`, gains the classmethod
`from_dataframe(frame, *, strategy_name)`, the inverse of `to_dataframe()`.
`to_dataframe()` also gains a trailing `grid_charge_cost_gbp` column for
tariffed runs, so the CSV that `home run` writes and the web CSV export of home
runs carry one more column. Consumers that read the frame by position rather
than by name re-check it when they re-pin.

**Task 323.** `BatteryConfig` gains the read-only property
`nominal_usable_capacity_kwh`, its usable capacity between the SOC limits before
SOH de-rating, in kWh; the 0.5.0 tag lacks it. Consumers need no change when
they re-pin.

**Task 392.** `SimulationResults`, reached through
`FleetResults.per_home_results`, gains two methods: `per_minute_amounts()`, a
frame of each minute's energy in kWh and money in £, one column per amount, and
`total_amounts()`, the run's total of each amount, keyed by column; the 0.5.0
tag has neither. Consumers need no change when they re-pin.

**Task 426.** `Battery` declares `config`,
`min_soc_fraction`, `max_soc_fraction`, `charge_efficiency` and
`discharge_efficiency` in its class body, and `WeatherCache` declares
`cache_dir`, so the frozen contract now covers them. `WeatherCache.cache_dir` is
still a plain instance attribute that `__init__` sets. `Battery`'s five are
settable properties since tasks 540 and 1691, still read and assigned as on the
0.5.0 tag. Consumers need no change when they re-pin.

**Task 505.** the frozen contract now covers the
constructors and public members of the eight classes outside `__all__` that the
frozen surface names, directly or through another such class:
`DispatchStrategyConfig`, `GridChargeConfig`, `OutputConfig` and
`SimulationPeriod` in `solar_challenge.config`, `EVConfig` in
`solar_challenge.ev`, `HeatPumpConfig` in `solar_challenge.heat_pump`, and
`HomeConfig` and `SimulationResults` in `solar_challenge.home`. Consumers still
import each from its module, as on the 0.5.0 tag, e.g.
`from solar_challenge.home import HomeConfig`, and need no change when they
re-pin.

**Task 567.** the frozen contract now covers, for each
class it pins, whether it is a dataclass and which of the dataclass parameters
`eq`, `order`, `unsafe_hash` and `frozen` it sets. These decide whether its
instances compare equal field by field, support `<`, `<=`, `>` and `>=`, are
hashable, and refuse a field assignment with `dataclasses.FrozenInstanceError`.
Every pinned dataclass sets `eq` except `PrefetchedWeather` and
`solar_challenge.timebase.LocalDay`, and none sets `order` or `unsafe_hash`. All
are frozen except `FleetConfig`, `FleetResults` and `CommunityResults`. A pinned
dataclass that the 0.5.0 tag also has sets the same parameters there, except
`SimulationResults` and `ScenarioConfig`, which tasks 436 and 955 froze, and
`SummaryStatistics`, `EnergyFlowResult`, and `OutputConfig` and
`SimulationPeriod` in `solar_challenge.config`, which task 669 froze (see their
notes). Consumers need no change when they re-pin.

**Task 668.** The frozen contract now covers, for every class it pins but an Enum, whether a
positional class pattern such as `case Location(lat, lon)` matches its
instances by its constructor's positional parameters, whether they hold no
`__dict__`, so `vars()` and attributes set ad hoc fail on them, and, if they
hold none, whether they take a weakref. These are spelled `match_args`,
`slots` and `weakref_slot` in its kind: `dataclass[eq, frozen, match_args]
(...)` for a dataclass, and `class[match_args, slots] (...)` for any other
class that has one. Every pinned dataclass with a positional field reads
`match_args`; `SelfConsumptionStrategyConfig` in `solar_challenge.dispatch`,
which has no field, does not, and no other pinned class sets `__match_args__`.
No pinned class reads `slots`: the instances of each hold a `__dict__` and take
a weakref. No class changes: the lock now pins what instances already did.
Consumers need no change when they re-pin.

**Task 777.** `SimulationResults`, reached through
`FleetResults.per_home_results`, gains a read-only property, `window`: the
`SimulationWindow`, imported from `solar_challenge.timebase`, that its index
describes: the first and last calendar dates it covers on the index's own
clock, the cadence its rows are spaced at, and that clock's zone name.
`per_minute_amounts()` and `total_amounts()` take each kW row's kWh from
`window.row_energy_kwh`, which multiplies it by `window.step_hours`, the
cadence in hours; the 0.5.0 tag multiplies by 1/60 whatever the spacing. A row
of half-hourly results, such as `from_dataframe` builds from a half-hourly
frame, now counts as half an hour's kWh, where the tag counts it as one
minute's. Both now raise `ValueError` for
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

**Task 789.** `solar_challenge.battery` gains `SocEnvelope(effective_capacity_kwh,
min_soc_kwh, max_soc_kwh)`, a frozen value holding a battery's SOH-derated
capacity and the SOC limits within it, in kWh, whose `target_kwh(fraction)` is
that fraction of the effective capacity capped at `max_soc_kwh`. It refuses,
with a `ConfigurationError`, a field that is not a finite number, an effective
capacity that is not above 0, a negative limit, and limits out of the order
`min_soc_kwh <= max_soc_kwh <= effective_capacity_kwh`; `target_kwh` refuses
the same way a fraction that is not a finite number greater than 0 and at
most 1, the range in which `GridChargeConfig` reads `target_soc_fraction`.
`BatteryConfig` gains `resolved_soh`, the SOH a `Battery` holds while this
config is its own, built from it or assigned to it: its `soh` override as
given, else `compute_soh` of its `system_age_years` with no throughput; and
`soc_envelope()`, the SOH-derated envelope at its own SOC fractions, the one a
`Battery` built from it starts with. `Battery` gains `soc_envelope`, the
envelope of its config at its current SOC fractions, either possibly
reassigned, from which its `min_soc_kwh`, `max_soc_kwh`, `usable_capacity_kwh`,
`effective_capacity_kwh`, `soc_fraction` and `grid_charge_target_kwh` now
derive. The first five give the values the 0.5.0 tag gives and follow a
reassigned `config` at once as on the tag, except that the SOH they derive from
now follows a reassigned `config` too (task 1691's note); the tag has no
`grid_charge_target_kwh` (task 788's note). The 0.5.0 tag has no `SocEnvelope`,
`resolved_soh` or `soc_envelope`, so a reader of a battery's SOC limits or
effective capacity builds a `Battery` to read them. Consumers need no change
when they re-pin; one that builds a `Battery` only to read its SOC limits or
effective capacity can ask the config's `soc_envelope()` instead.

**Task 801.** `GridServicesEventsConfig` gains
`annual_income_gbp(fleet_results)`, the annual capacity-at-events income in £,
net of the aggregator share, that it prices a simulated fleet at, equal to
`compute_grid_services_at_events(fleet_results, self).annual_income_gbp`; the
0.5.0 tag lacks it. `compute_grid_services_at_events` now issues a
`UserWarning`, once per call, for each event window the fleet's simulated index
never enters, naming the window's months, weekdays and hours and the index's
first and last timestamps. That window still contributes £0, and a fleet with
no battery home does not warn. `project_multi_year`, which prices every
simulated age, shows each such warning once per call, attributed to its own
caller; the 0.5.0 tag prices the window at £0 silently.
`project_multi_year`, and so `solve_cost_recovery_rate`, prices a flat
grid-services rate from the batteries of the `home_configs` its `simulate`
returns, where the 0.5.0 tag sums the scenario's own homes.
`FleetRunner.simulate` pairs them with the homes it is asked to simulate, so its
flat figure is unchanged. A `simulate=` must return `home_configs` carrying the
batteries that earn the income; task 1119's note says how one that does not is
refused, and what such a consumer changes. Consumers that simulate through a
`FleetRunner` need no change when they re-pin.

**Task 808.** `WeatherProvider`, `PvgisTmy` and
`PrefetchedWeather` join `__all__`; the 0.5.0 tag has none of them.
`WeatherProvider` is a `typing.Protocol`: any object whose `get(location)`
returns a frame of hourly weather is one. `PvgisTmy(cache)` is a frozen
dataclass whose `get(location)` returns the TMY `get_tmy_data` returns, read
from `cache` and put there on a miss, or fetched on every call when `cache` is
`None`; it raises `WeatherDataError` where `get_tmy_data` does.
`PrefetchedWeather(frames)` is a frozen dataclass compared by identity. Its
`frames` is a read-only copy of the mapping from `Location` to frame it is
given, so the locations it holds are fixed at construction; the frames
themselves are the ones given, not copies. Its `get(location)` returns the held
frame, and for any other location raises `LookupError` naming that location and
those held; its `fetch(weather, locations)` calls `weather.get` once per
distinct location, in first-seen order. Both pickle. `WeatherCache()` given no
directory uses the one `SOLAR_CHALLENGE_WEATHER_CACHE_DIR` names, when it is set
and non-empty, else `.cache/weather` under the working directory, as on the
tag; so `get_tmy_data`, with no cache installed, reads and fills that
directory. With none installed, `get_weather_cache()` returns a new
`WeatherCache()` on each call, so a change to the variable takes effect at the
next call; the tag builds one on the first call and returns it ever after.
`set_weather_cache` still overrides both. Consumers need no change when they
re-pin.

**Task 833.** `SummaryStatistics` gains three read-only
properties, each the difference of two of its totals, in kWh:
`total_pv_charge_kwh`, the battery charge less `total_grid_charge_kwh`;
`total_direct_self_consumption_kwh`, the self-consumption less the battery
discharge, which `simulate_home` counts in self-consumption; and
`total_grid_to_demand_kwh`, the grid import less `total_grid_charge_kwh`. The
0.5.0 tag has none of them. Consumers need no change when they re-pin, and a
subtraction of their own that computes one can go.

**Task 848.** `GridChargeConfig` gains a `forecast` field, after `target_soc_fraction`, naming
what sizes a cheap period's grid charge: one of `dispatch.GRID_CHARGE_FORECASTS`,
`'pv_blind'`, `'trailing_14_days'` or `'perfect_foresight'`
(`docs/grid-charge-forecast.md`). A `grid_charging:` block reads and writes it as
`forecast`. Omitted, it is `'pv_blind'`, which fills to the target in every cheap
period as the 0.5.0 tag does; the tag has no such field, and its `grid_charging:`
block refuses the key. Any other value is refused with a `ConfigurationError`
naming `forecast`, the value and every forecast. Consumers that build
`GridChargeConfig` by `target_soc_fraction`, positionally or by keyword, need no
change when they re-pin.

`GridChargeContext` gains a last field, `useful_charge_ceiling_kwh`, `None` by
default: the state of charge above which a step's grid charge is forecast to be
stranded by the PV after it. `compute_grid_charge_power_kw` then fills to the
lower of it and `target_soc_kwh`, so every strategy that grid-charges through it,
`TOUOptimizedStrategy` and `PeakShavingStrategy`, honours it;
`ScheduledChargeStrategy`'s windows still fill to their own targets. A ceiling
that is negative, NaN or infinite is refused with a `ValueError` naming the field
and the value. `simulate_timestep` gains a keyword-only `useful_charge_ceiling_kwh`,
`None` by default, that it carries into the context it builds; without a tariff or
grid charging it builds none, and the ceiling has no effect. The 0.5.0 tag has
neither. A context or call that leaves them out fills to the target as on the tag,
so consumers need no change when they re-pin.

`simulate_home` now sizes each cheap period's grid charge by its battery's
`GridChargeConfig.forecast`: it computes every row's useful-charge ceiling from the
run's PV and demand (`grid_charge_forecast.grid_charge_ceilings_kwh`) and passes it to
`simulate_timestep`, so a strategy given as `strategy=` is offered the same ceilings.
Under `'pv_blind'`, the default, no period has a ceiling, and every run is as on the
0.5.0 tag. Under `'trailing_14_days'` the first 14 cheap windows of a run fill as
`'pv_blind'` does, and from the 15th on a window fills no higher than its ceiling, so
a sunny spell grid-charges less. `SimulationResults` and `SummaryStatistics` gain a last
field, `grid_charge_forecast`, `None` by default: the forecast that sized the run's grid
charge, `None` when the run did not grid-charge. `simulate_home` sets it from the
battery's `grid_charging`, `calculate_summary` copies it, and
`SimulationResults.from_dataframe` gains a keyword-only `grid_charge_forecast`, `None` by
default, that it records. A stored summary saved before the field existed reads it as
`None`. The 0.5.0 tag has none of these; a consumer that builds either class by keyword,
or calls `from_dataframe` with `strategy_name` alone, needs no change when it re-pins.

`dispatch.distinct_grid_charge_forecasts(forecasts)` is new: the distinct forecasts
among the given runs' forecasts, each `None` for a run that did not grid-charge, in
`GRID_CHARGE_FORECASTS` order, `()` when none is set. `FleetSummary` and
`BillDistribution` gain a last field, `grid_charge_forecasts`, `()` by default, which
`aggregate_home_summaries` and `bill_distribution` set from it, so a fleet's net cost
and every bill distribution, cost-recovery outlays included, say what sized their grid
charge. A stored fleet summary saved before the field existed reads `()`.
`generate_summary_report`, `generate_finance_report`, `generate_config_ranking_report`
and `generate_community_report` open, under their first heading, with a notice naming
each forecast that sized the grid charge they report, and what it is; a report of runs
that did not grid-charge is as on the 0.5.0 tag.

`dispatch.ANALYSIS_ONLY_FORECASTS` is new: the forecasts no board figure may use,
`'perfect_foresight'`. `finance.annualise`, which `householder_bill`,
`bill_distribution`, `solve_cost_recovery_rate` and `project_multi_year` all
annualise through, now refuses a summary whose `grid_charge_forecast` is one of them
with a `ConfigurationError` naming the field, the value and the forecasts to run
instead: it reads the run's own future, an upper bound no board figure may use.
`project_multi_year` and `solve_cost_recovery_rate` refuse a scenario whose battery
grid-charges by one of them before they simulate it, through the new
`finance.refuse_analysis_only_forecasts(homes)`, which names the first such home's
`battery_config.grid_charging.forecast` by its position. A
`CommunityConfig` whose community battery's `grid_charging` names a forecast other
than `'pv_blind'` is refused with a `ConfigurationError` naming the community
battery, the forecast and `'pv_blind'`: the community dispatch computes no
useful-charge ceilings. The 0.5.0 tag has none of these names, fields or refusals;
a `'pv_blind'` or omitted forecast is accepted everywhere it was.

**Task 893.** `solar_challenge.timebase` gains
`ONE_MINUTE`, `timedelta(minutes=1)`, the cadence of a simulated run's window.
Its `SimulationWindow`, the type of the task 777 line's
`SimulationResults.window`, gains two methods. `rows()` is the window's index,
from its first day's first instant on its clock up to, not including, the first
instant after its last day, at its cadence, with `freq` the cadence, at
microsecond resolution, so `SimulationWindow.of_index(window.rows())` is the
window. A date's first instant is its local midnight, or, where the clocks skip
midnight, the instant they jump to, or, where they repeat it, the first 00:00.
A window with no zone has 24-hour days. A Europe/London one-minute window from
2024-03-30 to 2024-04-01 has 4,260 rows. `local_days()` yields one
`LocalDay(date, rows)` per date from `first_day` to `last_day`, in order, each
holding the rows of `rows()` that start on its date: 1,380 one-minute rows on
Europe/London's spring-forward day, 1,500 on its fall-back day and 1,440 on any
other. `rows()` raises `ValueError` naming the cadence when the cadence does not
divide one hour, and `local_days()` raises the same `ValueError` when it is
called, before it yields a day. `LocalDay`, in `solar_challenge.timebase`, is a
frozen dataclass compared by identity, whose two methods read the local wall
clock. `minute_of_day()` gives each row's minute of the day, 0 to 1439: it
repeats the minutes of the hour the clocks go back over and lacks those of the
hour they skip. `instant(minute_of_day)` gives the first row of the date whose
clock reads that minute or later, e.g. 02:00 BST for 01:30 on 2024-03-31, and
the first 01:30 on 2024-10-27; it raises `ValueError` for a minute outside 0 to
1439, or one no row of the date reaches. The frozen contract now also covers
`LocalDay`'s constructor and methods. The 0.5.0 tag has none of these.
Consumers need no change when they re-pin.

**Task 915.** the frozen contract now covers what a
consumer indexes in each exported container constant: the keys of
`SEG_PRESETS`, `OFGEM_TDCV_BY_OCCUPANTS` and `SEASONAL_FACTORS`, in order, with
the type of the value under each, and the length of `ELEXON_PROFILE_CLASS_1`
and `DEFAULT_EVENT_WINDOWS`, with the type of each item. The 0.5.0 tag's
constants hold the same keys and items, of the same types. Their numbers stay
data: a changed rate gets its own note as a change to what a public name returns.
Consumers need no change when they re-pin.

**Task 977.** `timebase` gains `SHORT_WINDOW_START`, 2024-06-01, beside
`DEFAULT_FIRST_DAY` and `DEFAULT_LAST_DAY`: the first day of the n-day windows
that the dashboard's `days` requests and `solar-challenge home quick` run. The
0.5.0 tag has no such name. Consumers need no change when they re-pin; code
that wants the n-day start reads it there instead of restating 2024-06-01.

**Task 979.** `solar_challenge.fleet_distribution.DISTRIBUTION_TYPES` is the per-type table
of the distribution grammar: one `DistributionType` for each `type:` a
`fleet_distribution:` spec names (`weighted_discrete`, `normal`, `uniform`,
`fixed`, `shuffled_pool` and `proportional_to`, in that order), with its title,
its `SpecParameter`s and `SpecRows`, the keys an editor has no input for, the
spec type its builder returns, its builder and its `write`.
`write_distribution_spec` writes a spec back as the mapping, or the scalar,
that the grammar reads as it, and `editor_types(kind)` gives the editable types
a field of a `FieldKind` draws. `DrawnKindRule` and `DRAWN_KIND_RULES`, the rule
of which specs a field of each drawn `FieldKind` may be given, are now public
names of the module. None of these is exported from `solar_challenge`, and no
parsed value or refusal changes. Consumers need no change when they re-pin; one
that spells a distribution type's keys or titles, or writes a spec back by
hand, can read them from the table, or write the spec with
`write_distribution_spec`, instead.

**Task 986.** `ConfigurationError` joins `__all__`, so `solar_challenge` exports it; the
0.5.0 tag does not. `ConfigurationError(*args)` takes the arguments
`ValueError` takes, and its classmethod `must_be(field, requirement, *, got)`
builds a refusal, which the caller raises. It is the class that
`solar_challenge.errors` defines, so either import gives the same class.
Accessing `solar_challenge.ConfigurationError` loads `solar_challenge.errors`
alone: neither pvlib nor any other module of the package. When they re-pin,
consumers may import it as task 773's note says,
`from solar_challenge.errors import ConfigurationError`, or write
`from solar_challenge import ConfigurationError`; either gives the same
`ValueError` subclass.

**Task 1309.** `SimulationWindow`, the type the task 777 line introduces, now raises
`ValueError` when it is built with a `first_day` or `last_day` whose type is
not exactly `datetime.date`, such as a `pd.Timestamp` or a `datetime`, or with
a `cadence` whose type is not exactly `datetime.timedelta`, such as a
`pd.Timedelta`, naming the field and the value. Before this change a window
could be built with two days that were each a `pd.Timestamp` or a `datetime`,
or with a cadence that is a `pd.Timedelta` or another value that compares with
a `timedelta`, as a NumPy `timedelta64` or a pandas tick offset such as
`pd.offsets.Minute(1)` does. A web-app save of a summary carrying such a
window wrote a `pd.Timestamp` day as datetime text, which loading the run then
refused, and failed on any other of these values. Any day that is not exactly
a `date`, or cadence that is not exactly a `timedelta`, and did not build,
usually with a `TypeError` or `AttributeError`, now raises this `ValueError`.
The window `SimulationWindow.of_index` gives, and so
`SimulationResults.window` and the `window` that `calculate_summary` gives a
`SummaryStatistics`, already holds exactly these types, as does the window
`simulate_home` runs over, so no result changes. The 0.5.0 tag has no
`SimulationWindow`. Consumers that build a window from other values pass
`pd.Timestamp(day).date()` for each day and
`pd.Timedelta(cadence).to_pytimedelta()` for the cadence when they re-pin.

**Task 1408.** A parallel `FleetRunner` (`simulate`, `simulate_each`) whose worker process ends
abruptly, e.g. through an out-of-memory kill, fails every unfinished home with one
`BrokenProcessPool`. That exception now carries the note "the process pool broke before
home {i} ({name!r}) of fleet {k} ({fleet name!r}) finished; the process that ended may
have been simulating another home", which names whichever unfinished home's future
reported first; before this change it carried task 879's note, "simulating home {i}
({name!r}) of fleet {k} ({fleet name!r})", which claimed that the home it named had
failed. A `BrokenProcessPool` that a home simulator raises itself, e.g. from a process
pool of its own, now carries the broken-pool note too, whether the runner runs homes in
parallel or in turn; every other exception a failed home raises keeps task 879's note.
The 0.5.0 tag's `simulate_fleet` raises `BrokenProcessPool` with no note. Consumers
change nothing when they re-pin; code that reads the note to find the failing home
should take a `BrokenProcessPool`'s note as naming only a home that had not finished.

**Task 1567.** `PvgisTmy.get`, and so `get_tmy_data`, `weather.default_weather().get` and
`fleet.default_runner()`'s weather prefetch, returns the TMY it has fetched when
its cache's `put` then raises `OSError`, as where the process may not create the
cache directory. It issues a `UserWarning`, attributed to its caller, naming the
cache directory and the error, and caches nothing, so the next `get` requests
PVGIS again. On the 0.5.0 tag, which has `get_tmy_data` but not `PvgisTmy`, a
`put` that raises after the fetch makes `get_tmy_data` raise `RuntimeError`
("Failed to retrieve TMY data from PVGIS"), with the `OSError` as its cause, and
the fetched TMY is lost. Code that relied on that error to notice a cache it
cannot write watches for the warning instead, e.g. with
`warnings.catch_warnings(record=True)` or an `error::UserWarning` filter; other
consumers need no change when they re-pin.

#### Consumer recipe for 0.6.0

1. **Re-pin.** Change the release tag at the end of the
   [dependency line](#pinned-dependency-recipe) to solar-challenge-v0.6.0, run
   `uv lock`, and commit `pyproject.toml` and `uv.lock` together, as the
   [Upgrade workflow](#upgrade-workflow) says. Move to Python 3.11 or later
   first (task 117).

2. **Rewrite each old spelling.** Each row is a spelling the 0.5.0 tag accepts
   and 0.6.0 does not, with the spelling that replaces it. The task's entry
   under Breaking says more.

   | Old spelling | New spelling | Task |
   |---|---|---|
   | `householder_bill(summary, annual_self_consumption_kwh, finance, simulation_days)` | `householder_bill(summary, window_self_consumption_kwh, finance)` | 784 |
   | `bill_distribution(summaries, finance, simulation_days)` | `bill_distribution(summaries, finance)` | 784 |
   | `BillDistribution.per_home_net_bill_gbp`, as keyword or attribute | `per_home_total_outlay_gbp`; a hand-built `BillDistribution` also passes `annualised_from` | 941, 784 |
   | `FinanceConfig(grid_services_model='flat', grid_services_income_per_kw_per_year_gbp=r, grid_services_events=…)` | `FinanceConfig(grid_services_model=…)` holding `NoGridServices()` (the default), `FlatGridServices(r)` or a `GridServicesEventsConfig(…)`; a scenario file moves the keys under `grid_services_model:` with its `type:` | 804 |
   | a band string, `GridServicesEventsConfig(band='central')`, `resolve_grid_services_rate_band('central')`, `GridServicesRateBands.resolve('central')` | `GridServicesBand.CENTRAL` (a string still works at run time; `mypy --strict` refuses it) | 804 |
   | `solve_cost_recovery_rate(…)` with no `simulate` | `solve_cost_recovery_rate(…, simulate=default_runner().simulate)` | 892 |
   | `project_multi_year(…)`, `optimize.run_sweep(…)`, `optimize.sensitivity_panel(…)` with no `simulate` | `simulate=default_runner().simulate`, or `FleetRunner(...).simulate` | 885 |
   | `SummaryStatistics(simulation_days=…, seg_revenue_gbp=…, total_heat_pump_load_kwh=…)` | `SummaryStatistics(window=…, …)`; SEG income from `total_export_revenue_gbp`; a heat pump's energy from `load_energy_kwh[LoadKind.HEAT_PUMP]`; a hand-built one for finance also passes `pricing=RunPricing(…)` | 784, 976, 901, 922 |
   | `ScenarioConfig(period=SimulationPeriod(start_date, end_date), …)` | `period=SimulationWindow(first_day, last_day, ONE_MINUTE, timezone)`, or `config.period_window(start, end, timezone=…)` | 963 |
   | `scenario.period.get_start_timestamp(…)` | `scenario.window()` or `scenario.simulation_bounds()` | 956 |
   | `ScenarioConfig(output=…, tariff_config=…)`; `config.OutputConfig` | no `output` (pass `--output` to the command); each home's `HomeConfig.tariff_config` | 950 |
   | a scenario file's `output:` block or scenario-level `tariff_config:` | `--output` on the command; `home.tariff` or each `homes[i].tariff` | 949 |
   | a flat home file; its `tariff_config:` key | the file wrapped in `home:`; `tariff:` | 957 |
   | `FleetConfig.homes`, `FleetResults.per_home_results` and `.home_configs` as lists, assigned or appended | tuples; a changed fleet or result built with `dataclasses.replace(...)` | 910 |
   | assigning a field of `SimulationResults`, `SummaryStatistics`, `EnergyFlowResult`, `config.SimulationPeriod`, `ScenarioConfig` or `FleetDistributionConfig` | `dataclasses.replace(value, field=new)`; `scenario.homes` compared with a tuple | 436, 669, 955, 921 |
   | `BatteryConfig(…, efficiency=x)` | `BatteryConfig(…).with_round_trip(x)` | 867 |
   | `HomeConfig(…, dispatch_strategy='tou_optimized')` | `BatteryConfig(…, dispatch_strategy=TOUOptimizedStrategyConfig())`; in a scenario file, `battery.dispatch_strategy: {strategy_type: tou_optimized}`; `'greedy'` dropped | 790 |
   | `config.DispatchStrategyConfig(strategy_type=…, …)` | `dispatch.SelfConsumptionStrategyConfig()`, `TOUOptimizedStrategyConfig(peak_hours)` or `PeakShavingStrategyConfig(import_limit_kw)` | 786 |
   | `TOUOptimizedStrategy(…, off_peak_hours=…)` | the argument dropped | 326 |
   | `simulate_timestep(…)`, a `decide_action(…)` with `timestep_minutes` omitted | `timestep_minutes` passed | 784 |
   | `simulate_timestep_tou(generation_kw, demand_kw, battery, timestamp, tariff, timestep_minutes)` | `simulate_timestep(generation_kw, demand_kw, battery, timestep_minutes, timestamp, strategy=TOUOptimizedStrategy(tariff=tariff), tariff=tariff)` | 905 |
   | `GridChargeContext.target_soc_fraction`; `compute_grid_charge_power_kw(…, capacity_kwh=…)` | `GridChargeContext.target_soc_kwh`; the call without `capacity_kwh` | 788 |
   | `compute_grid_charge_power_kw` given the SOC after the step's PV charge | the SOC before it | 898 |
   | `GridServicesAtEvents(…)` without its four per-window fields | `per_window_avail_p50_kw`, `per_window_avail_p90_kw`, `per_window_displaced_self_use_kwh_per_event` and `per_window_displaced_import_gbp_per_year` passed | 1434 |
   | `flex.resolve_grid_services_band(band)` | `GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year` | 803 |
   | `CommunityConfig(sharing_mode=…, …)`; a `community:` block's `sharing_mode:` | the argument and the key dropped; `community_battery` and `billing` passed by keyword | 912 |
   | `apply_degradation(…)` on `simulate_pv_output`'s output | `PVConfig(system_age_years=…, degradation_rate_per_year=…)`; another series, `series * calculate_degradation_factor(age, rate)` | 826 |
   | `get_tmy_data(loc)`, `get_tmy_data(loc, use_cache=False)`, `get_weather_cache()`, `set_weather_cache(c)` | `PvgisTmy(WeatherCache()).get(loc)`, `PvgisTmy(None).get(loc)`, `WeatherCache()`, and `PvgisTmy(c)` wherever weather is taken | 827 |
   | `EVConfig(charger_type='…')` as a string | an `EVChargerType` member; `smart_charging_mode` a `SmartChargingMode` | 901 |
   | `SimulationResults(…, heat_pump_load=s)` | `additional_loads[LoadKind.HEAT_PUMP]`, read there or from `results.loads[LoadKind.HEAT_PUMP]` | 901, 897 |
   | `results.per_minute_amounts()` | `results.per_step_amounts()` | 784 |
   | `TariffConfig.mean_period_rate` | none: added and retired on main, so neither release has it | 843 |
   | `battery.config = cfg` | still assigned; a `cfg` whose capacity times its SOH is not above 0 raises `ConfigurationError` | 1691 |
   | `from solar_challenge.config import ConfigurationError` | `from solar_challenge.errors import ConfigurationError`, or `from solar_challenge import ConfigurationError` (task 986) | 773 |
   | `ConfigurationError`, a subclass of `Exception` | a subclass of `ValueError`, which `except ValueError` catches | 774 |
   | `from solar_challenge.config import GridChargeConfig` | `from solar_challenge.dispatch import GridChargeConfig` | 786, 946 |
   | the block readers and block tables from `solar_challenge.config`; a name `config` only imported, e.g. `TariffPeriod` or `EventWindow` | `solar_challenge.scenario_blocks`; the module that defines the name, e.g. `solar_challenge.tariff` or `solar_challenge.gridservices` | 946 |
   | the fleet grammar's names from `solar_challenge.config` (`WeightedDiscreteDistribution`, `SweepSpec`, `FleetDistributionConfig`, `generate_homes_from_distribution`, `expand_sweep_configs`, …), and `PVConfig` or `LoadConfig` through it | `solar_challenge.fleet_distribution`; each component config from its own module | 947 |
   | `PVDistributionConfig`, `BatteryDistributionConfig`, `LoadDistributionConfig`, `HeatPumpDistributionConfig`, `EVDistributionConfig` | `ComponentDistribution(draws, settings)` | 919 |
   | `FleetConfig.create_uniform(…)` given a seeded `load_config` | `create_uniform(…, seed=s)`; home i gets seed + i | 908 |
   | `fleet.simulate_fleet`, `simulate_fleet_iter`, `simulate_multi_sweep_iter`, `collect_multi_sweep_results`, `MultiSweepResults` | `default_runner()` or `FleetRunner(weather, home_simulator, …)` | 879 |
   | `config.run_parameter_sweep`, `ParameterSweepConfig`, `SweepResult` | `fleet.FleetRunner.simulate_each`, `optimize.run_sweep` or the web's sweep endpoint | 945 |
   | `generate_load_profile(config, start_date, end_date, timezone=…)` | `generate_load_profile(config, window, …)`, `window` a `timebase.SimulationWindow` | 894 |
   | `generate_ev_charging_profile(config, start_date, end_date, …)`; an EV's charging inside `generate_load_profile` | `generate_ev_charging_profile(config, window, *, tariff=None, generation_kw=None)`, added to the household by the caller | 895 |
   | the projection names from `solar_challenge.finance` (`YearPoint`, `MultiYearCurve`, `ProjectEconomics`, `MAX_NODES`, `project_multi_year`, `project_economics`, `spreadsheet_revenue_curve`); `project_economics(curve, scenario, finance)` | `solar_challenge.projection`; `project_economics(curve, scenario_fleet(scenario), finance)` | 928 |
   | `from solar_challenge.finance import solve_cost_recovery_rate` | `from solar_challenge import solve_cost_recovery_rate`, or `solar_challenge.projection` | 939 |
   | `ConfigResult(representative_outlay_gbp=…, solved_own_use_rate_pence_per_kwh=…, surplus_at_solved_gbp=…, feasible=…, binding=…)` | the five keywords dropped: they are read-only properties over its `solution` | 934 |
   | `from solar_challenge.output import generate_finance_report, generate_config_ranking_report` | `solar_challenge.board_report` | 970 |
   | `generate_finance_report(…)` with the 0.5.0 tag's arguments | `sections=`, one `AssumptionSection` per mode, its finance from `with_own_use_basis`, keyed by `own_use_basis(section.finance)`, plus a `GridServicesIncome` and a `FlexBlock` | 973, 974 |
   | `calculate_summary(results, seg_tariff_pence_per_kwh=r)`, and likewise `calculate_fleet_summary`, `calculate_home_summaries` and `generate_summary_report` | no rate: `HomeConfig(seg_tariff=SEGTariff(…))` prices the export; read `total_export_revenue_gbp` and `pricing.seg_rate_pence_per_kwh` | 975 |
   | `SweepSpec(mode='linear')`; `get_values()` annotated `list[float]` | `SweepMode.LINEAR`, `SweepMode.GEOMETRIC` or `SweepMode.parse(text)`; `tuple[float, ...]` | 964 |
   | `optimize.apply_knob(scenario, name, value)`; `sensitivity_panel`'s axes and `SENSITIVITY_BANDS` keyed by name | `knob_named(name).apply(scenario, value)`; keyed by `KNOBS[name]` | 965 |
   | `run_sweep(configs, retained_cash_floor_gbp=f, …)`, `sensitivity_panel(…, retained_cash_floor_gbp=f)` | the floor set on the scenario, `knob_named('retained_floor').apply(scenario, f)`; `sensitivity_panel(base_configs, axes, baseline=<the run_sweep result>, simulate=…)` | 966 |
   | `Knob(…)` without `target`; `config.sweep_point_fleet(…, value)` | `Knob(…, target=KnobTarget.HOMES)` or another `KnobTarget`; `sweep_point_fleet` with a label from `config.sweep_value_labels` | 1740 |
   | `detect_sweep_spec(…)`, `config.detect_fleet_sweep_spec(…)` returning a `SweepSpec`; a sweep multiplier at another field; point names `multiplier=<value>`; `config.YAML_SWEEP_PARAMETER` | the pair `(placement, spec)`; the multiplier at `battery.capacity_kwh`; `battery.capacity_kwh.multiplier=<value>`; `fleet_distribution.swept_parameter_path(placement)` | 969 |
   | `RankedSweep(…)` without `self_consumption_override`; `optimize configs` ranking a calibration scenario under its override | `self_consumption_override` passed; `optimize configs --assumptions spreadsheet` | 1270 |
   | `home run` on a file that sets `period:`, expecting a whole year; `cli.utils.load_config_with_overrides` | `--start` and `--end`; fleet files run with `fleet run` | 958 |
   | `finance run` on a file that sets a shorter `period:`, expecting a whole year | `--start` and `--end` | 959 |
   | `WeatherCache.cache_dir` listed or written before any `put` | `cache_dir.mkdir(parents=True, exist_ok=True)` first | 1559 |
   | a pre-built weather cache's files | `WeatherCache.put(df, "tmy", location)`, read only through `WeatherCache.get` | 815 |
   | code that matches a refusal's message text | the new text: a scenario grammar refusal reads `<block path>: <problem>` | 861, 862, 864, 866, 871, 904, 948, 965 |
   | input the 0.5.0 tag accepted, now refused (tasks 374, 384, 466, 469, 540, 559, 590, 633, 659, 660, 672, 787, 802, 823, 863, 868, 902, 909, 914, 925, 1029, 1119, 1125, 1218, 1315, 1358, 1372, 1374, 1400, 1440, 1473) | fix the input; `except ValueError` still catches each refusal | see the list |

   The other Breaking entries change behaviour, not a spelling, and each says
   what a consumer does: 464 (a cache seeded with a fixed-offset frame), 782 (a
   bill of a window that is not one calendar year), 812 (a PVWatts module
   without `STC`), 825 (a stored 0.2 or −0.004 module setting), 837, 838, 839
   (`TOUOptimizedStrategy(tariff=tariff)` in place of derived hours), 842 (an
   off-peak EV with no tariff), 889 (a parallel fleet call from a script, now
   guarded by `if __name__ == "__main__":`) and 1102 (a `pd.Timestamp(...)`
   wrapper kept for the type checker).

3. **Re-baseline.** Re-measure each stored figure that depends on one of these
   entries under Breaking or Results that move:
   - PV generation: 236, 240, 252, 285, 460, 810, 812, 823, 825;
   - demand and EV: 708, 842, 868, 894, 895, 906;
   - dispatch and battery: 182, 580, 788, 838, 841, 865, 900, 1362;
   - grid services: 837;
   - community: 779;
   - bills and the solved rate: 778, 782, and every entry after the lead-in for
     readers of cost-recovery-finance-model.md.

4. **Platform (solar-challenge-platform at f8d7a1ef1).** Its main pins
   solar-challenge-v0.5.0 and requires-python ">=3.11,<3.14". The table counts the
   lines that name an old spelling of the table above in the 68 files under
   `src` and `tests` that import `solar_challenge`, leaving out comments,
   docstrings and names that only contain one, such as a test function named
   after `householder_bill`. Sites counts each line once, though one line can
   name two spellings. A line that already writes the new form, such as a call
   that passes `timestep_minutes`, still counts, so each site is a line to check.
   The platform's `target_soc_fraction` lines are `GridChargeConfig`'s field,
   which 0.6.0 keeps, so they need no edit and are not counted.

   | File | Sites | Old spellings it names |
   |---|---|---|
   | `solar-challenge-platform/src/solar_challenge_platform/optimiser/forecast/weather_api.py` | 2 | `generate_load_profile` ×2 |
   | `solar-challenge-platform/src/solar_challenge_platform/optimiser/planner.py` | 5 | `decide_action(` ×3; `simulate_timestep(` ×1; `solar_challenge.config` ×1 |
   | `solar-challenge-platform/src/solar_challenge_platform/simulator/physics.py` | 4 | `decide_action(` ×3; `simulate_timestep(` ×1 |
   | `solar-challenge-platform/src/solar_challenge_platform/simulator/service.py` | 1 | `create_uniform` or `create_heterogeneous` ×1 |
   | `solar-challenge-platform/tests/billing/test_reducer_reconciliation.py` | 12 | `SummaryStatistics(` ×2; `householder_bill(` ×2; `seg_revenue_gbp` ×2; `simulation_days` ×4; `total_heat_pump_load_kwh` ×2 |
   | `solar-challenge-platform/tests/integration/test_billing_boundary.py` | 9 | `BillDistribution(` ×1; `CostRecoverySolution(` or `ConfigResult(` ×1; `SummaryStatistics(` ×1; `householder_bill(` ×1; `per_home_net_bill_gbp` ×1; `seg_revenue_gbp` ×1; `simulation_days` ×2; `total_heat_pump_load_kwh` ×1 |
   | `solar-challenge-platform/tests/integration/test_optimiser_end_to_end.py` | 1 | `simulate_timestep(` ×1 |
   | `solar-challenge-platform/tests/optimiser/test_outlay_parity.py` | 5 | `SummaryStatistics(` ×1; `householder_bill(` ×1; `simulation_days` ×2; `solar_challenge.finance` ×1 |
   | `solar-challenge-platform/tests/optimiser/test_planner.py` | 1 | `decide_action(` ×1 |
   | `solar-challenge-platform/tests/optimiser/test_planner_derated_battery.py` | 3 | `decide_action(` ×2; `solar_challenge.config` ×1 |
   | `solar-challenge-platform/tests/simulator/fleet_harness.py` | 1 | `create_uniform` or `create_heterogeneous` ×1 |
   | `solar-challenge-platform/tests/simulator/test_fleet.py` | 2 | `FleetConfig(`, `FleetResults(` or `CommunityResults(` ×1; `create_uniform` or `create_heterogeneous` ×1 |
   | `solar-challenge-platform/tests/simulator/test_physics.py` | 4 | `simulate_timestep(` ×4 |
   | `solar-challenge-platform/tests/test_solar_challenge_seam.py` | 6 | `FleetConfig(`, `FleetResults(` or `CommunityResults(` ×1; `ScenarioConfig(` ×1; `SimulationPeriod` ×2; `seg_tariff_pence_per_kwh` ×1; `solar_challenge.config` ×1; `solve_cost_recovery_rate(` ×1 |

   No code line of those files names `bill_distribution(`; the `grid_services_*` keywords; `band=`; `heat_pump_load`; `OutputConfig`; `get_start_timestamp`; `efficiency=`; `dispatch_strategy`; `GridServicesAtEvents`; `sharing_mode`; `simulate_timestep_tou`; `compute_grid_charge_power_kw`; `GridChargeContext.target_soc_fraction`; `apply_degradation`; `get_tmy_data`, `get_weather_cache`, `set_weather_cache`; `charger_type`; `per_minute_amounts`; `mean_period_rate`; `.config =`; `off_peak_hours`; `DispatchStrategyConfig`; `resolve_grid_services_band`; `simulate_fleet` and task 879's other names; `project_multi_year`, `run_sweep`, `sensitivity_panel`; `generate_ev_charging_profile`; the `*DistributionConfig` types; the names task 928 moved; `run_parameter_sweep`, `ParameterSweepConfig`, `SweepResult`; the block readers; the fleet grammar's names; `apply_knob`, `SENSITIVITY_BANDS`, `Knob(`; `retained_cash_floor_gbp`; `RankedSweep`; the board reports; `calculate_summary(` and its three siblings; `load_config_with_overrides`; or `ConfigurationError`.

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

Accessing any name from `config`, `fleet`, `home`, `projection`, `pv` or
`weather` imports `pvlib` transitively.  `pv` and `weather` import it directly;
`home` imports `pv`, `fleet` imports `home`, `config` imports `home`, `fleet`
and `pv`, and `projection` imports `config`, `fleet`, `home` and `pv`:

```python
sc = solar_challenge
mc = sc.create_model_chain(...)    # ← first access imports pv.py + pvlib
w = sc.PvgisTmy(...)               # ← first access imports weather.py + pvlib
cfg = sc.ScenarioConfig            # ← first access imports config.py + pvlib
solve = sc.solve_cost_recovery_rate  # ← first access imports projection.py + pvlib
```

Accessing a name from any other public submodule (`battery`, `community`,
`dispatch`, `errors`, `finance`, `flow`, `gridservices`, `load`, `location`,
`seg`, `tariff`) leaves `pvlib` unloaded;
`tests/unit/test_public_api_surface.py::test_the_first_access_of_a_public_name_loads_pvlib_exactly_for_the_listed_submodules`
pins this split.  Consumers that want to avoid the pvlib cost must not touch the
`config`, `fleet`, `home`, `projection`, `pv` or `weather` symbols.  Accessing
a name does not run it, so a function of any other submodule can still load
`pvlib` when called, by importing one of those submodules at call time.

### Network I/O

On a cache miss, `PvgisTmy(cache).get(location)` makes **two outbound HTTPS requests
to the PVGIS API**: the TMY, and the 2005–2020 hourly series whose mean annual GHI it
scales the TMY to (see [tmy-irradiation-scaling.md](tmy-irradiation-scaling.md)).
In test environments and CI, a consumer passes its simulation a provider over a
pre-seeded cache, or names that cache's directory in `SOLAR_CHALLENGE_WEATHER_CACHE_DIR`,
rather than letting a run fetch:

```python
from pathlib import Path

from solar_challenge import PvgisTmy, WeatherCache

my_test_cache = WeatherCache(Path("my-test-cache"))
weather = PvgisTmy(my_test_cache)
```

```sh
export SOLAR_CHALLENGE_WEATHER_CACHE_DIR=my-test-cache
```

`WeatherCache()` given no directory reads that variable at each construction, and so do
`weather.default_weather()` and `fleet.default_runner()` at each call.

`fleet.FleetRunner` fetches each distinct home location's weather once per call, in the
calling process, through its weather provider. `fleet.default_runner()`'s provider is
`weather.default_weather()`, which is `PvgisTmy(WeatherCache())`. A consumer with its
own cache builds
`FleetRunner(weather=PvgisTmy(WeatherCache(d)), home_simulator=simulate_home)`. Each
worker job then carries a `PrefetchedWeather` holding its own home's location alone, so
the runner's cache serves a parallel fleet under any multiprocessing start method, and a
worker reads no cache and no network.

A cache directory written before that scaling is ignored, because its entries' keys
changed. Rebuild a pre-built cache with `my_test_cache.put(df, "tmy", location)`, which
`PvgisTmy.get` serves exactly as stored.

---

## Frozen public surface

The authoritative public surface is `solar_challenge.__all__`, defined in
`src/solar_challenge/__init__.py`.  It is frozen by
`tests/unit/test_public_api_surface.py`, whose `FROZEN_SURFACE` pins every
public name and that name's signature and, for a dataclass, which of `eq`,
`order`, `unsafe_hash` and `frozen` it sets.  For every class but an Enum, it
also pins whether a positional class pattern matches its instances
(`match_args`), whether they hold no `__dict__` (`slots`) and whether they take a
weakref (`weakref_slot`).  For a constant, `FROZEN_SURFACE`
pins its type and, for a mapping, list or tuple, its keys or length and the type
of each value or item.  The file's `FROZEN_MEMBERS` pins the public methods,
properties, class constants, and declared instance attributes of every exported
class and of every class outside `__all__` that the frozen surface names.  The
same file's `FROZEN_CLOSURE` pins the constructor of each
such class, for a dataclass which of those four parameters it sets, and, for
every such class but an Enum, those three qualifiers of its instances;
consumers import such a class, such as `HomeConfig`, from its module.
Importing the package fails with a `RuntimeError` naming the offending name when
its tables disagree: a name that `__all__` lists twice, a name that `__all__`
and the lazy loader's module map do not both list, or an alias of a name outside
`__all__`.  `tests/unit/test_public_api_surface.py` also checks that a bare
`import solar_challenge` stays pvlib-free and that each public name resolves to
the object its `TYPE_CHECKING` import names.
Consumers should reference `__all__` directly rather than relying on any copy
maintained in this document.
