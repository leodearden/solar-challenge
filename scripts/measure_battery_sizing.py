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

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.gridservices import EventParticipation, GridServicesBand, GridServicesEventsConfig
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


def _priced_at(base: ScenarioConfig, participation: EventParticipation, band: GridServicesBand) -> ScenarioConfig:
    """base with its events configuration at participation and band, all else as it is.

    Raises:
        ConfigurationError: If base does not price grid services at events, naming it.
    """
    finance = base.finance
    events = None if finance is None else finance.grid_services_model
    if finance is None or not isinstance(events, GridServicesEventsConfig):
        raise ConfigurationError(
            f"scenario {base.name!r} does not price grid services at events (finance.grid_services_model"
            " of type: capacity_at_events), which the sweep enrols and prices at each band"
        )
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
