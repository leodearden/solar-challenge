# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""The [FIN] calibration fixtures that θ and CR6 share.

θ (tests/integration/test_finance_calibration.py) and CR6
(tests/integration/test_cost_recovery_calibration.py) calibrate the finance layer
against the investor spreadsheet's [FIN] inputs, whose install is 5.5 kWp of PV and a
5 kWh battery per home.  Each has a slow physics column that simulates
make_physics_column_scenario's fleet through PVGIS.

Usage::

    from tests._fin_calibration import make_physics_column_scenario

    sol = solve_cost_recovery_rate(make_physics_column_scenario(), finance)
"""
from __future__ import annotations

import dataclasses

from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.load import LoadConfig
from tests._finance_builders import make_sized_home


def make_physics_column_scenario() -> ScenarioConfig:
    """Two homes of the [FIN] install on a deterministic 3,400 kWh load, over three January days of 2024.

    The fleet is small and the window short for speed.
    """
    home = dataclasses.replace(
        make_sized_home(pv_kwp=5.5, battery_kwh=5.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1),
    )
    return ScenarioConfig(
        name="FIN-Physics-Column",
        period=SimulationPeriod(start_date="2024-01-01", end_date="2024-01-03"),
        homes=[home] * 2,
    )
