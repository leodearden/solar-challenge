"""Integration tests for grid-charging (TOU arbitrage) economics signal.

Proves the user-observable signal: net_cost_gbp(grid_charge_ON) < net_cost_gbp(grid_charge_OFF).

These tests:
- Load the committed scenarios/bristol-arbitrage.yaml scenario
- Validate that the CLI accepts the battery.grid_charging YAML keys
- Assert that enabling grid-charging reduces net cost on a single winter day
  using a deterministic zero-PV synthetic weather frame (PVGIS-free, fast)
- Assert that a copy of the scenario whose battery is at SOH 0.7 ends the cheap
  night, in the CSV `home run` writes, at its target fraction of the battery's
  effective (SOH-derated) capacity

Every simulation is given a sunless winter day as its weather, so these tests run offline.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.config import load_scenarios
from solar_challenge.home import calculate_summary, simulate_home
from solar_challenge.weather import WeatherCache
from tests._repository_paths import SCENARIOS_DIR
from tests._synthetic_weather import sunless_tmy, sunless_weather, weather_for

runner = CliRunner()

SCENARIO = SCENARIOS_DIR / "bristol-arbitrage.yaml"


# ---------------------------------------------------------------------------
# Config-surface tests
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
    weather = sunless_weather("2024-01-15", temp_air=8.0)

    res_on = simulate_home(home_on, start, end, weather=weather_for(home_on, weather))
    res_off = simulate_home(home_off, start, end, weather=weather_for(home_off, weather))

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
    weather = sunless_weather("2024-01-15", temp_air=8.0)

    # simulate_home with validate_balance=True asserts at every timestep internally;
    # if the balance is violated it raises. Passing here proves #27's split-source
    # accounting keeps the energy balance closed.
    res = simulate_home(home_on, start, end, weather=weather_for(home_on, weather), validate_balance=True)

    # With zero PV and grid-charging, we must have drawn from the grid
    assert res.grid_import.sum() > 0, "Expected non-zero grid import"


def test_a_derated_battery_ends_the_cheap_night_at_its_target_fraction_of_effective_capacity(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """The 5 kWh battery at SOH 0.7, grid-charging to 0.5, holds 1.75 kWh at 07:29, the cheap night's last minute: half its 3.5 kWh effective capacity."""
    scenario = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
    battery = scenario["home"]["battery"]
    battery["soh"] = 0.7
    battery["grid_charging"]["target_soc_fraction"] = 0.5
    derated = tmp_path / "bristol-arbitrage-soh-0.7.yaml"
    derated.write_text(yaml.safe_dump(scenario), encoding="utf-8")
    home = load_scenarios(derated)[0].home
    assert home is not None
    weather_cache.put(sunless_tmy(temp_air=8.0), "tmy", home.location)
    csv = tmp_path / "run.csv"

    result = runner.invoke(
        app,
        ["home", "run", str(derated), "--start", "2024-01-15", "--end", "2024-01-15", "--output", str(csv)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    soc_kwh = pd.read_csv(csv, index_col=0, parse_dates=True)["battery_soc_kwh"]
    assert soc_kwh.loc["2024-01-15 07:29"] == pytest.approx(1.75, abs=1e-6)
