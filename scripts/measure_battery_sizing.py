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
from pathlib import Path

from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
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
