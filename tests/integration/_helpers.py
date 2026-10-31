# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""The board scenario for the integration tests: ``SCENARIO``, the path of its YAML, and ``board_econ_scenario()``, which builds its ``ScenarioConfig`` and ``FinanceConfig``.

Usage::

    from tests.integration._helpers import SCENARIO, board_econ_scenario

    scenario, finance = board_econ_scenario()
    raw = load_config(SCENARIO)
"""

from __future__ import annotations

from pathlib import Path

from solar_challenge.config import (
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    load_fleet_config,
    parse_finance_config,
)
from solar_challenge.finance import FinanceConfig

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


def board_econ_scenario() -> tuple[ScenarioConfig, FinanceConfig]:
    """Build (scenario, finance_loaded) from the board YAML.

    Mirrors the canonical consumer path in cli/finance.py::

        load_config → parse_finance_config → load_fleet_config → ScenarioConfig

    Returns:
        Tuple of ``(ScenarioConfig, FinanceConfig)`` for the board scenario.
    """
    cfg = load_config(SCENARIO)
    finance = parse_finance_config(cfg.get("finance"))
    assert finance is not None, f"the board scenario {SCENARIO} has no finance block"
    fleet = load_fleet_config(SCENARIO)
    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    scenario = ScenarioConfig(
        name="Board-GridServices-Test",
        period=period,
        homes=list(fleet.homes),
    )
    return scenario, finance
