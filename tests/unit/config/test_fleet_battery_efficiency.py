# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a fleet_distribution: battery's drawn efficiency builds its homes' batteries: as a home: battery block's does, the round trip BatteryConfig.with_round_trip splits, refused beside a per-direction efficiency."""

from pathlib import Path
from typing import Any

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import load_fleet_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    ComponentDistribution,
    FleetDistributionConfig,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.scenario_writer import fleet_scenario, scenario_yaml


def _fleet_block(battery: dict[str, Any]) -> dict[str, Any]:
    """A seeded two-home fleet_distribution: block with PV whose battery block is *battery*."""
    return {"n_homes": 2, "seed": 1, "pv": {"capacity_kw": 4.0}, "battery": battery}


def _homes(battery: dict[str, Any]) -> list[HomeConfig]:
    """The homes of the fleet _fleet_block describes, at Bristol."""
    return generate_homes_from_distribution(
        parse_fleet_distribution_config(_fleet_block(battery)), Location.bristol()
    )


def _both_forms_refusal(*per_direction: str) -> str:
    """The refusal of the fleet's battery block setting efficiency beside each of *per_direction*, a home: battery block's wording."""
    return (
        "fleet_distribution.battery: sets both forms of a battery's efficiency: efficiency and "
        f"{' and '.join(per_direction)}; set efficiency, the round trip, or charge_efficiency "
        "and discharge_efficiency, not both"
    )


def test_a_drawn_round_trip_builds_each_battery_through_with_round_trip() -> None:
    batteries = [home.battery_config for home in _homes({"capacity_kwh": 5.0, "efficiency": 0.81})]

    assert batteries == [BatteryConfig(capacity_kwh=5.0).with_round_trip(0.81)] * 2
    assert [(battery.charge_efficiency, battery.discharge_efficiency) for battery in batteries if battery] == [
        (0.9, 0.9)
    ] * 2


@pytest.mark.parametrize(
    "charge_efficiency",
    [
        pytest.param(0.96, id="away-from-its-default"),
        pytest.param(0.975, id="at-its-default"),
    ],
)
def test_a_block_drawing_both_forms_is_refused_when_read_by_key(charge_efficiency: float) -> None:
    """As a home: battery block is, whatever the per-direction value."""
    block = _fleet_block({"capacity_kwh": 5.0, "efficiency": 0.92, "charge_efficiency": charge_efficiency})

    with pytest.raises(ConfigurationError) as refusal:
        parse_fleet_distribution_config(block)

    assert str(refusal.value) == _both_forms_refusal("charge_efficiency")


def test_a_fleet_built_drawing_both_forms_is_refused_at_construction() -> None:
    battery = ComponentDistribution({"capacity_kwh": 5.0, "efficiency": 0.92, "discharge_efficiency": 0.96})

    with pytest.raises(ConfigurationError) as refusal:
        FleetDistributionConfig(n_homes=2, pv=ComponentDistribution({"capacity_kw": 4.0}), battery=battery)

    assert str(refusal.value) == _both_forms_refusal("discharge_efficiency")


def test_homes_drawing_a_round_trip_load_back_from_their_written_fleet(tmp_path: Path) -> None:
    homes = _homes({"capacity_kwh": 5.0, "efficiency": 0.81})
    path = tmp_path / "fleet.yaml"
    path.write_text(scenario_yaml(fleet_scenario(homes, name="Round trip fleet")), encoding="utf-8")

    assert load_fleet_config(path).homes == tuple(homes)


def test_a_drawn_round_trip_out_of_range_is_refused_at_generation_naming_the_block_once_and_the_home() -> None:
    fleet = parse_fleet_distribution_config(_fleet_block({"capacity_kwh": 5.0, "efficiency": 1.5}))

    with pytest.raises(ConfigurationError) as refusal:
        generate_homes_from_distribution(fleet, Location.bristol())

    message = str(refusal.value)
    assert message.startswith("fleet_distribution.battery: home 1: ")
    assert "efficiency" in message.removeprefix("fleet_distribution.battery: home 1: ")
    assert "1.5" in message
    assert message.count("fleet_distribution") == 1
