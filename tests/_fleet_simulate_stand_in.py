# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""A fleet simulate stand-in that answers every fleet with the same per-home results, paired with that fleet's homes.

project_multi_year, and so solve_cost_recovery_rate, run_sweep and
sensitivity_panel, prices grid-services income from the batteries of the
home_configs its simulate returns, and refuses an answer whose home_configs do
not carry the batteries of the homes it asked for. A test that simulates the
same energy for every fleet therefore answers as FleetRunner.simulate pairs its
results: with the homes of the fleet it is asked to simulate.

Usage::

    from tests._finance_builders import make_fleet_results
    from tests._fleet_simulate_stand_in import answering_with

    ranked = run_sweep(configs, simulate=answering_with(make_fleet_results(n_homes=5)))

A stand-in that also records what it is asked delegates its answer::

    answer = answering_with(fleet_results)

    def simulate(fleet_config, start, end):
        asked.append(fleet_config)
        return answer(fleet_config, start, end)
"""
from __future__ import annotations

import pandas as pd

from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from tests._finance_builders import make_fleet_results_of


def answering_with(fleet_results: FleetResults) -> FleetSimulate:
    """A simulate that answers every fleet with *fleet_results*' per-home results, paired with that fleet's homes."""

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        return make_fleet_results_of(fleet_results.per_home_results, homes=fleet_config.homes)

    return simulate
