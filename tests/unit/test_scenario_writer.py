"""Tests for scenario_writer: configs written as scenario YAML that config.py's loaders read back."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_writer import home_scenario, scenario_yaml
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig


def _every_grammar_field_home() -> HomeConfig:
    """An Edinburgh home with every field the scenario grammar carries set away from its default.

    The timezone is the one exception: Edinburgh keeps London's.
    """
    return HomeConfig(
        pv_config=PVConfig(
            capacity_kw=9.0,
            azimuth=135.0,
            tilt=20.0,
            name="South roof",
            module_efficiency=0.21,
            temperature_coefficient=-0.0035,
            inverter_efficiency=0.97,
            inverter_capacity_kw=8.0,
            system_age_years=3.0,
            degradation_rate_per_year=0.006,
        ),
        battery_config=BatteryConfig(
            capacity_kwh=10.0,
            max_charge_kw=3.0,
            max_discharge_kw=3.5,
            name="Wall",
            dispatch_strategy=DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 19)]),
            grid_charging=GridChargeConfig(target_soc_fraction=0.8),
            min_soc_fraction=0.15,
            max_soc_fraction=0.95,
            efficiency=0.9,
            system_age_years=2.0,
            calendar_fade_rate_per_year=0.03,
            cycle_fade_per_equivalent_full_cycle=6e-05,
            soh_floor=0.6,
            soh=0.95,
        ),
        load_config=LoadConfig(
            annual_consumption_kwh=4200.0,
            household_occupants=4,
            name="Family",
            use_stochastic=False,
            seed=7,
        ),
        heat_pump_config=HeatPumpConfig(
            "GSHP", 6.0, annual_heat_demand_kwh=9000.0, name="Ground loop"
        ),
        ev_config=EVConfig(
            "7kW",
            arrival_hour=18,
            departure_hour=6,
            required_charge_kwh=20.0,
            smart_charging_mode="solar",
            name="Car",
        ),
        location=Location(
            55.95, -3.19, timezone="Europe/London", altitude=47.0, name="Edinburgh, UK"
        ),
        name="Nine kW home",
        tariff_config=TariffConfig.economy_7(),
        dispatch_strategy="tou_optimized",
        seg_tariff=SEGTariff(name="Octopus Outgoing", rate_pence_per_kwh=15.0),
    )


def _load_through_home_run(document: dict[str, Any], tmp_path: Path) -> HomeConfig:
    """Write *document* as a scenario file and load it the way `home run` does."""
    path = tmp_path / "home.yaml"
    path.write_text(scenario_yaml(document), encoding="utf-8")
    return home_config_for_run(path)


def test_a_home_written_as_a_scenario_loads_back_through_home_run(tmp_path: Path) -> None:
    """Every grammar field survives the round trip; the SEG tariff comes back unnamed.

    A seg: block names no tariff, and `home run` builds SEGTariff(name='').
    """
    home = _every_grammar_field_home()

    loaded = _load_through_home_run(home_scenario(home, name="Nine kW home"), tmp_path)

    assert loaded == dataclasses.replace(
        home, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=15.0)
    )


def test_a_home_without_optional_parts_loads_back_without_them(tmp_path: Path) -> None:
    home = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

    loaded = _load_through_home_run(home_scenario(home, name="Bare home"), tmp_path)

    assert loaded == home


def test_per_direction_battery_efficiencies_load_back(tmp_path: Path) -> None:
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            efficiency=None,
            charge_efficiency=0.96,
            discharge_efficiency=0.97,
        ),
    )

    loaded = _load_through_home_run(home_scenario(home, name="Split efficiencies"), tmp_path)

    assert loaded == home


@pytest.mark.parametrize("field", ["custom_module_params", "custom_inverter_params"])
def test_a_pv_field_the_grammar_has_no_key_for_is_refused(field: str) -> None:
    home = HomeConfig(
        pv_config=dataclasses.replace(PVConfig(capacity_kw=4.0), **{field: {"pdc0": 250.0}}),
        load_config=LoadConfig(),
    )

    with pytest.raises(ValueError, match=field):
        home_scenario(home, name="Custom pvlib")
