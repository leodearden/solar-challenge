# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Shared integration-test helpers for grid-services tests.

Provides the common board-scenario/finance builder shared across
``test_flex_grid_services`` and ``test_grid_services_events`` to prevent
independent drift when the board YAML or config API changes.

Usage::

    from tests.integration._helpers import board_econ_scenario
    scenario, finance = board_econ_scenario()

"""
from __future__ import annotations

from pathlib import Path

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


def board_econ_scenario(scenario_name: str = "Board-GridServices-Test") -> tuple:  # type: ignore[return]
    """Build (scenario, finance_loaded) from the board YAML.

    Mirrors the canonical consumer path in cli/finance.py::

        load_config → _parse_finance_config → load_fleet_config → ScenarioConfig

    Args:
        scenario_name: Optional name for the constructed ``ScenarioConfig``
            instance.  Defaults to ``"Board-GridServices-Test"``.

    Returns:
        Tuple of ``(ScenarioConfig, FinanceConfig)`` for the board scenario.
    """
    from solar_challenge.config import (  # type: ignore[attr-defined]
        ScenarioConfig,
        SimulationPeriod,
        _parse_finance_config,
        load_config,
        load_fleet_config,
    )

    cfg = load_config(SCENARIO)
    finance = _parse_finance_config(cfg.get("finance"))
    fleet = load_fleet_config(SCENARIO)
    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    scenario = ScenarioConfig(
        name=scenario_name,
        period=period,
        homes=list(fleet.homes),
    )
    return scenario, finance
