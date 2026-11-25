# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""A fleet simulate that records each fleet it is asked to simulate, then answers as another simulate does.

A test that counts or inspects the simulations a sweep asks for wraps the
simulate it would otherwise pass::

    from tests._fleet_simulate_stand_in import answering_with
    from tests._recording_simulate import recording

    asked: list[FleetConfig] = []
    run_sweep(configs, simulate=recording(asked, answering_with(fleet_results)))
    assert len(asked) == 12
"""
from __future__ import annotations

import pandas as pd

from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate


def recording(asked: list[FleetConfig], answer: FleetSimulate) -> FleetSimulate:
    """*answer*, appending each fleet it is asked to simulate to *asked* before answering."""

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        asked.append(fleet_config)
        return answer(fleet_config, start, end)

    return simulate
