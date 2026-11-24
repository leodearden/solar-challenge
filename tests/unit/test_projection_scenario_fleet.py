# SPDX-License-Identifier: AGPL-3.0-or-later
"""scenario_fleet is the one resolution of a scenario: its simulated_homes(), SEG filled, over its simulation_bounds()."""
from __future__ import annotations

import pandas as pd
import pytest

from solar_challenge.config import ScenarioConfig
from solar_challenge.projection import ScenarioFleet, scenario_fleet
from tests._finance_builders import make_home_config, make_period, make_scenario


def test_a_fleet_scenarios_fleet_is_its_simulated_homes_over_its_simulation_bounds() -> None:
    scenario = make_scenario(n_homes=3, seg_tariff_pence_per_kwh=4.1)

    fleet = scenario_fleet(scenario)

    assert fleet.homes == scenario.simulated_homes()
    assert (fleet.start, fleet.end) == scenario.simulation_bounds()


def test_a_fleet_scenarios_fleet_exports_at_the_scenarios_seg_rate() -> None:
    scenario = make_scenario(n_homes=3, seg_tariff_pence_per_kwh=4.1)

    homes = scenario_fleet(scenario).homes

    assert len(homes) == 3
    assert [home.seg_tariff.rate_pence_per_kwh if home.seg_tariff else None for home in homes] == [4.1, 4.1, 4.1]


def test_a_single_home_scenarios_fleet_is_that_home_over_its_simulation_bounds() -> None:
    scenario = ScenarioConfig(name="single-home", period=make_period(), home=make_home_config())

    fleet = scenario_fleet(scenario)

    assert fleet.homes == (scenario.home,)
    assert (fleet.start, fleet.end) == scenario.simulation_bounds()


def test_a_scenario_fleet_refuses_no_homes_naming_homes() -> None:
    start = pd.Timestamp("2021-01-01", tz="Europe/London")
    end = pd.Timestamp("2021-12-31", tz="Europe/London")

    with pytest.raises(ValueError, match="homes"):
        ScenarioFleet(homes=(), start=start, end=end)
