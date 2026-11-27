# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rank the Victron board fleet's four battery configurations by householder outlay, enrolled in grid-services events and not, at each rate band.

docs/battery-sizing-with-events.md records what this prints and why. From the repository root:

    uv run --locked --extra dev python scripts/measure_battery_sizing.py [--scenario PATH] [--homes N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--cache-dir DIR] [--workers N] [--no-parallel]

It sweeps scenarios/bristol-phase1-victron.yaml's fleet over BATTERIES, every home at PV_KWP on
an INVERTER_KW inverter, as `solar-challenge optimize configs` sweeps it, twice: dispatched, as
the scenario enrols it in its event windows, and observed, the same events configuration
un-enrolled. It prices each sweep at the low, central and high bands, simulating each
configuration once per participation and pricing the three bands from those runs. By default it
runs the whole fleet over the scenario's period, all of 2024; --homes N keeps the first N homes
and their share of the grant. It reads Bristol's TMY from the weather cache committed under
tests/fixtures/weather_cache, so it runs offline. Each configuration is one cost-recovery
projection of several fleet-years, run in a process pool unless --no-parallel. It prints each
band's ranking as a markdown table, each configuration against the smallest battery, after the
library version, commit, homes, period, weather, install and events it was measured on.
tests/integration/test_battery_sizing_end_to_end.py runs measure offline on a short winter
window and synthetic weather, and tests/unit/test_measurement_scripts.py runs main on them; the
full run is not part of the test suite.
"""

import argparse
import dataclasses
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

import solar_challenge
from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig, FleetResults, FleetRunner, FleetSimulate
from solar_challenge.gridservices import EventParticipation, GridServicesBand, GridServicesEventsConfig
from solar_challenge.home import simulate_home
from solar_challenge.optimize import (
    ConfigResult,
    ReferenceComparison,
    default_reference,
    enumerate_configs,
    feasible_split,
    rank,
    run_sweep,
)
from solar_challenge.scenario_knobs import KNOBS
from solar_challenge.weather import CLIMATE_YEARS, PVGIS_API_URL, PvgisTmy, WeatherCache

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SCENARIO = REPOSITORY_ROOT / "scenarios" / "bristol-phase1-victron.yaml"

COMMITTED_WEATHER_CACHE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "weather_cache"
"""The weather cache committed with the tests, which holds Bristol's PVGIS TMY."""

PV_KWP = 4.0
"""Every home's PV in kWp: the board pool's most common size."""

INVERTER_KW = 3.68
"""Every home's PV inverter in kW: G98's single-phase limit."""

BATTERIES: tuple[tuple[float, float], ...] = ((5.12, 2.4), (10.24, 2.4), (10.24, 3.68), (15.36, 3.68))
"""PRD docs/prds/event-dispatch-and-battery-sizing.md §2.3's four configurations, each battery's nameplate kWh with its MultiPlus-II's power in kW: the 48/3000's 2.4 kW and the 48/5000's 3.68 kW under G98."""

PARTICIPATIONS = (EventParticipation.DISPATCHED, EventParticipation.OBSERVED)
"""Each sweep's part in the scenario's events, in the order each band's sweeps are given: enrolled, as the scenario sets it, then not."""


@dataclass(frozen=True)
class BandSweep:
    """One participation's four configurations priced at one band.

    Attributes:
        participation: Whether the fleet was enrolled in the events, or observed.
        band: The band its grid-services rates were priced at.
        rows: Each configuration compared with this participation's reference at this band,
            the smallest battery: the feasible first, in optimize.rank order, then the
            infeasible, in BATTERIES order.
    """

    participation: EventParticipation
    band: GridServicesBand
    rows: tuple[ReferenceComparison, ...]


def first_homes(scenario: ScenarioConfig, count: int) -> ScenarioConfig:
    """scenario's first count homes with their share of its grant; scenario itself when count is its whole fleet.

    The grant is the one project total in FinanceConfig, every other cost being per home or a
    fraction, so scaling it to the homes kept keeps each home's figures those of the whole fleet.

    Raises:
        ConfigurationError: If count is below 1 or above the scenario's homes, naming both, or if
            the scenario has no finance block to take a grant from.
    """
    fleet = len(scenario.homes)
    if not 1 <= count <= fleet:
        raise ConfigurationError(
            f"cannot keep the first {count} homes of scenario {scenario.name!r}: it has {fleet} homes,"
            f" so keep 1 to {fleet}"
        )
    if count == fleet:
        return scenario
    if scenario.finance is None:
        raise ConfigurationError(f"scenario {scenario.name!r} has no finance block, whose grant its first homes share")
    cut = dataclasses.replace(scenario, homes=scenario.homes[:count])
    return KNOBS["grant_gbp"].apply(cut, scenario.finance.grant_gbp * count / fleet)


class _SimulatedOnce:
    """A FleetSimulate that simulates each request once, for one participation's one configuration.

    A request equal to one it has answered, the same FleetConfig (its homes with their
    batteries' state of health, and its name) and the same start and end, is answered with the
    FleetResults it was given then; every other is passed to simulate and its results held.
    Nothing is held beyond the one configuration it serves: decision 8 of
    docs/prds/fleet-execution-policy.md says why a fleet's minute series are not kept longer.
    """

    def __init__(self, simulate: FleetSimulate) -> None:
        self._simulate = simulate
        self._answered: list[tuple[FleetConfig, pd.Timestamp, pd.Timestamp, FleetResults]] = []

    def __call__(self, fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        for answered_fleet, answered_start, answered_end, results in self._answered:
            if (answered_fleet, answered_start, answered_end) == (fleet, start, end):
                return results
        results = self._simulate(fleet, start, end)
        self._answered.append((fleet, start, end, results))
        return results


def _events_of(scenario: ScenarioConfig) -> tuple[FinanceConfig, GridServicesEventsConfig]:
    """scenario's finance block and the events configuration it prices grid services with.

    Raises:
        ConfigurationError: If scenario does not price grid services at events, naming it.
    """
    finance = scenario.finance
    events = None if finance is None else finance.grid_services_model
    if finance is None or not isinstance(events, GridServicesEventsConfig):
        raise ConfigurationError(
            f"scenario {scenario.name!r} does not price grid services at events (finance.grid_services_model"
            " of type: capacity_at_events), which the sweep enrols and prices at each band"
        )
    return finance, events


def _priced_at(base: ScenarioConfig, participation: EventParticipation, band: GridServicesBand) -> ScenarioConfig:
    """base with its events configuration at participation and band, all else as it is.

    Raises:
        ConfigurationError: If base does not price grid services at events, naming it.
    """
    finance, events = _events_of(base)
    pricing = dataclasses.replace(events, participation=participation, band=band)
    return dataclasses.replace(base, finance=dataclasses.replace(finance, grid_services_model=pricing))


def _band_sweep(participation: EventParticipation, band: GridServicesBand, results: Sequence[ConfigResult]) -> BandSweep:
    """results, one per configuration, ranked as run_sweep ranks them and compared with the smallest battery's."""
    feasible, infeasible = feasible_split(results)
    reference_point = default_reference([result.config for result in results])
    (reference,) = [result for result in results if result.config == reference_point]
    rows = tuple(ReferenceComparison(result, reference) for result in [*rank(feasible), *infeasible])
    return BandSweep(participation, band, rows)


def measure(base: ScenarioConfig, *, simulate: FleetSimulate) -> tuple[BandSweep, ...]:
    """base's sweep over BATTERIES at each band and participation, the bands low to high, dispatched before observed in each.

    Each configuration is run_sweep's own evaluation at each band. A band changes only the
    rates, but each band's cost-recovery solve prices inside its projection, so the three bands
    can share one set of simulations only while each fleet is held until its last band is
    priced. So it runs configuration by configuration: each configuration of each
    participation is simulated once, its three bands priced from those runs, and its runs
    dropped before the next. It then ranks each band's configurations as run_sweep ranks a
    sweep.

    Raises:
        ConfigurationError: If base does not price grid services at events, naming it.
        ValueError: As enumerate_configs and run_sweep refuse base, before it is simulated.
    """
    sweeps: dict[tuple[GridServicesBand, EventParticipation], BandSweep] = {}
    for participation in PARTICIPATIONS:
        configs = {
            band: enumerate_configs(
                _priced_at(base, participation, band),
                [PV_KWP],
                [kwh for kwh, _ in BATTERIES],
                [INVERTER_KW],
                battery_kw=[kw for _, kw in BATTERIES],
            )
            for band in GridServicesBand
        }
        results: dict[GridServicesBand, list[ConfigResult]] = {band: [] for band in GridServicesBand}
        for position in range(len(BATTERIES)):
            held = _SimulatedOnce(simulate)
            for band in GridServicesBand:
                results[band].append(run_sweep([configs[band][position]], simulate=held).reference)
        for band in GridServicesBand:
            sweeps[band, participation] = _band_sweep(participation, band, results[band])
    return tuple(sweeps[band, participation] for band in GridServicesBand for participation in PARTICIPATIONS)


def _git(*args: str) -> str:
    """What git prints for args in the repository, stripped."""
    return subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit() -> str:
    """HEAD's full SHA, flagged when a tracked file differs from it, or 'unknown (<reason>)' when git cannot say."""
    try:
        sha = _git("rev-parse", "HEAD")
        changed = _git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError) as error:
        return f"unknown ({error})"
    return f"{sha} (with uncommitted changes)" if changed else sha


def _signed_gbp(value: float, decimals: int) -> str:
    """A signed difference in pounds at decimals places, '+£1,280' or '-£6.40', a zero as '+£0'."""
    rounded = round(value, decimals)
    sign = "-" if rounded < 0 else "+"
    return f"{sign}£{abs(rounded):,.{decimals}f}"


_COLUMNS = (
    "Participation",
    "Rank",
    "Battery kWh",
    "Battery kW",
    "Capex/home £",
    "Extra capex/home £",
    "Solved own-use rate p/kWh",
    "Outlay at solved rate £/yr",
    "Outlay change £/yr",
    "Events income £/home/yr",
    "Pays for itself",
)


def _cells(sweep: BandSweep) -> list[tuple[str, ...]]:
    """Each row of sweep as the report prints it, in the order of _COLUMNS."""
    return [
        (
            str(sweep.participation),
            str(place) if row.result.feasible else "infeasible",
            f"{row.result.config.battery_kwh:g}",
            f"{row.result.config.battery_kw:g}",
            f"£{row.result.capex_per_home_gbp:,.0f}",
            _signed_gbp(row.extra_capex_per_home_gbp, 0),
            f"{row.result.solved_own_use_rate_pence_per_kwh:.2f}",
            f"£{row.result.representative_outlay_gbp:,.2f}",
            _signed_gbp(row.outlay_change_gbp, 2),
            f"£{row.result.grid_services_income_per_home_gbp:,.2f}",
            "yes" if row.pays_for_itself else "no",
        )
        for place, row in enumerate(sweep.rows, start=1)
    ]


def _print_measured_on(scenario: ScenarioConfig, *, scenario_path: Path, fleet_homes: int, cache_dir: Path) -> None:
    """Print the library version, commit, scenario, homes, period, weather, install and events the sweeps were measured on."""
    finance, events = _events_of(scenario)
    homes, window, location = len(scenario.homes), scenario.window(), scenario.get_location()
    print(f"solar_challenge {solar_challenge.__version__}")
    print(f"Commit: {_commit()}")
    population = (
        f"all {fleet_homes} homes"
        if homes == fleet_homes
        else f"its first {homes} of {fleet_homes} homes, the grant scaled to {homes}/{fleet_homes} of the scenario's:"
        f" £{finance.grant_gbp:,.0f}"
    )
    print(f"Scenario: {scenario_path} ({scenario.name}), {population}")
    print(f"Period: {window.first_day.isoformat()} to {window.last_day.isoformat()} ({window.days} days)")
    print(
        f"Weather: PVGIS TMY at {location.name} ({location.latitude}, {location.longitude}) from {PVGIS_API_URL},"
        f" scaled to its {CLIMATE_YEARS[0]}-{CLIMATE_YEARS[-1]} mean annual GHI, read from the cache in {cache_dir}"
    )
    batteries = "; ".join(f"{kwh:g} kWh at {kw:g} kW" for kwh, kw in BATTERIES)
    print(f"Install: every home {PV_KWP:g} kWp of PV on a {INVERTER_KW:g} kW inverter, with a battery of {batteries}")
    for event_window in events.event_windows:
        print(
            f"Event window: months {list(event_window.months)}, weekdays {list(event_window.weekdays)}, hours"
            f" {list(event_window.hours)}, {event_window.events_per_year:g} events a year of {event_window.event_hours:g} h"
        )
    print(
        f"Events: delivery baseline {events.delivery_baseline}, site export limit {events.site_export_limit_kw} kW"
        f" while a battery exports, event-day seed {events.event_day_seed}, aggregator share"
        f" {events.aggregator_share:g}, utilisation factor {events.utilisation_factor:g}"
    )
    print(
        "Participation: dispatched enrols every battery home in the drawn windows; observed is the same events"
        " configuration un-enrolled, priced from the spare capacity its own dispatch leaves"
    )


def print_report(
    scenario: ScenarioConfig, sweeps: Sequence[BandSweep], *, scenario_path: Path, fleet_homes: int, cache_dir: Path
) -> None:
    """Print each band's sweeps as one markdown table, dispatched rows before observed, after what they were measured on."""
    _print_measured_on(scenario, scenario_path=scenario_path, fleet_homes=fleet_homes, cache_dir=cache_dir)
    for band in GridServicesBand:
        print(f"\n### {band.value.capitalize()} band\n")
        print("| " + " | ".join(_COLUMNS) + " |")
        print("|---|---:|---:|---:|" + "---:|" * (len(_COLUMNS) - 5) + "---|")
        for participation in PARTICIPATIONS:
            (sweep,) = [sweep for sweep in sweeps if (sweep.band, sweep.participation) == (band, participation)]
            for cells in _cells(sweep):
                print("| " + " | ".join(cells) + " |")


def _announcing(simulate: FleetSimulate) -> FleetSimulate:
    """simulate, telling stderr of each fleet it simulates, so a long run can be followed in its log."""

    def announced(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        began = time.perf_counter()
        results = simulate(fleet, start, end)
        battery = fleet.homes[0].battery_config
        installed = (
            "no battery"
            if battery is None
            else f"{battery.capacity_kwh:g} kWh at {battery.max_discharge_kw:g} kW,"
            f" {'enrolled' if battery.event_discharge else 'in no event window'}"
        )
        print(
            f"{fleet.name}: {len(fleet.homes)} homes, the first with {installed},"
            f" simulated in {time.perf_counter() - began:.0f} s",
            file=sys.stderr,
            flush=True,
        )
        return results

    return announced


def _at_least_one(text: str) -> int:
    """text read as a whole number of at least 1, as --homes and --workers take it."""
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError(f"takes a whole number of at least 1, not {text!r}")
    return count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--scenario", type=Path, default=SCENARIO, help=f"the scenario swept (default: {SCENARIO})")
    parser.add_argument(
        "--homes", type=_at_least_one, default=None, help="sweep only the fleet's first N homes (default: all)"
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="first day, YYYY-MM-DD (default: the scenario's)"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, default=None, help="last day, YYYY-MM-DD (default: the scenario's)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=COMMITTED_WEATHER_CACHE_DIR,
        help=f"weather cache holding the TMY at the scenario's location (default: {COMMITTED_WEATHER_CACHE_DIR},"
        " which holds Bristol's committed PVGIS TMY)",
    )
    parser.add_argument(
        "--workers", type=_at_least_one, default=None, help="the process pool's workers (default: FleetRunner's own)"
    )
    parser.add_argument(
        "--parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run the homes in a process pool (the default), or in turn in this process",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    loaded = load_scenario(args.scenario).with_window(first_day=args.start, last_day=args.end)
    fleet_homes = len(loaded.homes)
    scenario = first_homes(loaded, fleet_homes if args.homes is None else args.homes)
    cache = WeatherCache(args.cache_dir)
    runner = FleetRunner(
        weather=PvgisTmy(cache), home_simulator=simulate_home, parallel=args.parallel, max_workers=args.workers
    )
    sweeps = measure(scenario, simulate=_announcing(runner.simulate))
    print_report(scenario, sweeps, scenario_path=args.scenario, fleet_homes=fleet_homes, cache_dir=cache.cache_dir)


if __name__ == "__main__":
    main()
