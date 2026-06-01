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

import dataclasses
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.config import load_scenarios
from solar_challenge.home import calculate_summary, simulate_home

pytestmark = pytest.mark.integration

runner = CliRunner()

SCENARIO = Path("scenarios/bristol-arbitrage.yaml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zero_pv_weather(
    day: str = "2024-01-15",
    tz: str = "Europe/London",
) -> pd.DataFrame:
    """Build a 1-day hourly weather DataFrame with zero irradiance.

    All GHI/DNI/DHI are zero → PV generation is zero, so net_cost == import_cost.
    This isolates the import-arbitrage signal exactly: the grid-charge ON run
    pre-loads the battery overnight at the off-peak rate and discharges into
    the evening peak, shifting expensive peak-rate import to cheap off-peak.

    Modeled on tests/integration/test_community_fleet.py::_synth_weather.
    """
    index = pd.date_range(day, periods=24, freq="h", tz=tz)
    return pd.DataFrame(
        {
            "ghi": [0.0] * 24,
            "dni": [0.0] * 24,
            "dhi": [0.0] * 24,
            "temp_air": [8.0] * 24,  # mild winter temperature
            "wind_speed": [2.0] * 24,
        },
        index=index,
    )


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


# ---------------------------------------------------------------------------
# Economics A/B proof (GREEN against existing #2 + #27 code)
# ---------------------------------------------------------------------------


def test_grid_charge_lowers_net_cost() -> None:
    """grid_charge ON reduces net_cost_gbp vs OFF on a deterministic winter day.

    Uses zero-PV injected weather so net_cost == import_cost in both runs.
    The ON run grid-charges overnight (off-peak 0.09 £/kWh) and discharges
    at the 18:00 evening peak (0.25 £/kWh), strictly lowering import cost.
    The Economy 7 spread gate guarantees a comfortable ~£0.31 margin.
    """
    scenario = load_scenarios(SCENARIO)[0]
    home_on = scenario.home
    assert home_on is not None

    # Derive grid-charge-OFF variant — differs only in battery.grid_charging
    off_batt = dataclasses.replace(home_on.battery_config, grid_charging=None)
    home_off = dataclasses.replace(home_on, battery_config=off_batt)

    start = end = pd.Timestamp("2024-01-15")
    weather = _zero_pv_weather("2024-01-15")

    res_on = simulate_home(home_on, start, end, weather_data=weather)
    res_off = simulate_home(home_off, start, end, weather_data=weather)

    summary_on = calculate_summary(res_on)
    summary_off = calculate_summary(res_off)

    # Headline assertion: grid-charging strictly reduces net cost
    assert summary_on.net_cost_gbp < summary_off.net_cost_gbp, (
        f"Expected grid_charge ON ({summary_on.net_cost_gbp:.4f} £) < "
        f"OFF ({summary_off.net_cost_gbp:.4f} £)"
    )

    # Corroborating: grid-charging actually fired in ON (battery charged)
    assert res_on.battery_charge.sum() > 0, (
        "Grid-charge ON: expected non-zero battery charging"
    )
    # No PV + no grid-charging → no charging in OFF
    assert res_off.battery_charge.sum() == 0, (
        "Grid-charge OFF with zero PV: expected zero battery charging"
    )


def test_energy_balance_holds_with_grid_charging() -> None:
    """Energy balance is maintained (validate_balance=True) when grid-charging is on."""
    scenario = load_scenarios(SCENARIO)[0]
    home_on = scenario.home
    assert home_on is not None

    start = end = pd.Timestamp("2024-01-15")
    weather = _zero_pv_weather("2024-01-15")

    # simulate_home with validate_balance=True asserts at every timestep internally;
    # if the balance is violated it raises. Passing here proves #27's split-source
    # accounting keeps the energy balance closed.
    res = simulate_home(home_on, start, end, weather_data=weather, validate_balance=True)

    # With zero PV and grid-charging, we must have drawn from the grid
    assert res.grid_import.sum() > 0, "Expected non-zero grid import"
