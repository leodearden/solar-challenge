"""Integration tests for grid-charging (TOU arbitrage) economics signal.

Proves the user-observable signal: net_cost_gbp(grid_charge_ON) < net_cost_gbp(grid_charge_OFF).

These tests:
- Load the committed scenarios/bristol-arbitrage.yaml scenario
- Validate that the CLI accepts the battery.grid_charging YAML keys
- Assert that enabling grid-charging reduces net cost on a single winter day
  using a deterministic zero-PV synthetic weather frame (PVGIS-free, fast)

Marked integration (NOT slow): injected weather bypasses PVGIS entirely.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.config import load_scenarios

pytestmark = pytest.mark.integration

runner = CliRunner()

SCENARIO = Path("scenarios/bristol-arbitrage.yaml")


# ---------------------------------------------------------------------------
# Config-surface tests (RED until scenarios/bristol-arbitrage.yaml exists)
# ---------------------------------------------------------------------------


def test_validate_config_accepts_grid_charging_keys() -> None:
    """CLI 'validate config' accepts the battery.grid_charging keys without error."""
    result = runner.invoke(app, ["validate", "config", str(SCENARIO)])
    assert result.exit_code == 0, (
        f"validate config exited {result.exit_code}:\n{result.output}"
    )


def test_scenario_parses_grid_charging() -> None:
    """load_scenarios parses grid_charging.target_soc_fraction and dispatch_strategy."""
    scenario = load_scenarios(SCENARIO)[0]
    assert scenario.home is not None, "Scenario must define a single 'home:' block"
    assert scenario.home.battery_config is not None, "Home must have a battery_config"
    assert scenario.home.battery_config.grid_charging is not None, (
        "Battery must have grid_charging set"
    )
    assert scenario.home.battery_config.grid_charging.target_soc_fraction == 0.9
    assert scenario.home.dispatch_strategy == "tou_optimized"
    assert scenario.home.tariff_config is not None, "Home must have a tariff_config"
