# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""The multi-year projection, project economics and cost-recovery solve of a
scenario's fleet, above finance's bill arithmetic.

Provides:
  - ``ScenarioFleet`` — frozen dataclass of the homes a scenario projects, its
    SEG filled, and the window to simulate them over.
  - ``scenario_fleet`` — the one resolution of a scenario to its ScenarioFleet.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from solar_challenge.config import ScenarioConfig
from solar_challenge.home import HomeConfig


@dataclass(frozen=True)
class ScenarioFleet:
    """The homes a scenario projects, its SEG filled, and the window to simulate them over.

    Attributes:
        homes: The homes, in the scenario's order; at least one.
        start: The window's first day's local midnight.
        end: The window's last day's local midnight, inclusive.
    """

    homes: tuple[HomeConfig, ...]
    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        """Raise ValueError, naming homes, when there are none."""
        if not self.homes:
            raise ValueError(f"ScenarioFleet projects at least one home: got homes={self.homes!r}")


def scenario_fleet(scenario: ScenarioConfig) -> ScenarioFleet:
    """The one resolution of a scenario: its simulated_homes(), SEG filled, over its simulation_bounds()."""
    start, end = scenario.simulation_bounds()
    return ScenarioFleet(homes=scenario.simulated_homes(), start=start, end=end)
