# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""project_multi_year and solve_cost_recovery_rate simulate the scenario over ScenarioConfig.simulation_bounds().

The scenario's period is a pair of zoned Timestamps at a time of day: the one period form whose
Timestamps are not simulation_bounds()'s local midnights, so a simulate asked for the period as
given is told apart from one asked for the bounds.
"""
from __future__ import annotations

import dataclasses

import pandas as pd

from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.finance import FinanceConfig, project_multi_year, solve_cost_recovery_rate
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from tests._finance_builders import make_fleet_results, make_scenario_and_finance
from tests._fleet_simulate_stand_in import answering_with

_AT_A_TIME_OF_DAY = SimulationPeriod(
    pd.Timestamp("2024-01-01 06:00", tz="Europe/London"),
    pd.Timestamp("2024-12-31 18:00", tz="Europe/London"),
)
"""The calendar year 2024, as zoned Timestamps at 06:00 on its first day and 18:00 on its last."""

_Request = tuple[str, pd.Timestamp, pd.Timestamp]
"""What a simulate is asked: the fleet's name, the start and the end."""


def _scenario_and_finance() -> tuple[ScenarioConfig, FinanceConfig]:
    """Two homes over _AT_A_TIME_OF_DAY, and a FinanceConfig over a five-year asset life."""
    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=5)
    return dataclasses.replace(scenario, period=_AT_A_TIME_OF_DAY), finance


def _recording(asked: list[_Request]) -> FleetSimulate:
    """A simulate that appends each request to *asked*, then answers it with two homes' results."""
    answer = answering_with(make_fleet_results(n_homes=2))

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        asked.append((fleet_config.name, start, end))
        return answer(fleet_config, start, end)

    return simulate


def test_project_multi_year_simulates_every_age_over_the_scenario_bounds() -> None:
    scenario, finance = _scenario_and_finance()
    asked: list[_Request] = []

    project_multi_year(scenario, finance, simulate=_recording(asked))

    assert asked
    assert [(start, end) for _, start, end in asked] == [scenario.simulation_bounds()] * len(asked)


def test_solve_cost_recovery_rate_simulates_over_the_scenario_bounds() -> None:
    """Both the projection's ages and the solve's own age-0 fleet, cr4-solve-age0."""
    scenario, finance = _scenario_and_finance()
    asked: list[_Request] = []

    solve_cost_recovery_rate(scenario, finance, simulate=_recording(asked))

    assert "cr4-solve-age0" in [name for name, _, _ in asked]
    assert [(start, end) for _, start, end in asked] == [scenario.simulation_bounds()] * len(asked)
