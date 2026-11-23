# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""project_multi_year and solve_cost_recovery_rate simulate the scenario over ScenarioConfig.simulation_bounds().

The scenario's period is the calendar year 2024, not make_period()'s 2021, so a simulate asked for
the scenario's simulation_bounds() is told apart from one asked for the builder's default window.
"""
from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd

from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import FinanceConfig, project_multi_year, solve_cost_recovery_rate
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._finance_builders import make_fleet_results, make_scenario_and_finance
from tests._fleet_simulate_stand_in import answering_with

_YEAR_2024 = SimulationWindow(date(2024, 1, 1), date(2024, 12, 31), ONE_MINUTE, "Europe/London")
"""The calendar year 2024 on London's clock."""

_Request = tuple[str, pd.Timestamp, pd.Timestamp]
"""What a simulate is asked: the fleet's name, the start and the end."""


def _scenario_and_finance() -> tuple[ScenarioConfig, FinanceConfig]:
    """Two homes over _YEAR_2024, and a FinanceConfig over a five-year asset life."""
    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=5)
    return dataclasses.replace(scenario, period=_YEAR_2024), finance


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
