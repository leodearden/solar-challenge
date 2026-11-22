# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a fleet_distribution: battery's drawn efficiency builds its homes' batteries: through BatteryConfig's transitional efficiency field, until task 1350 builds it through with_round_trip as a home: battery block's is."""

import math

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    FleetDistributionConfig,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.location import Location


def _fleet(battery: dict[str, float]) -> FleetDistributionConfig:
    """A seeded two-home fleet with PV whose fleet_distribution: battery block is *battery*."""
    return parse_fleet_distribution_config(
        {"n_homes": 2, "seed": 1, "pv": {"capacity_kw": 4.0}, "battery": battery}
    )


def _efficiencies(fleet: FleetDistributionConfig) -> list[tuple[float | None, float, float]]:
    """Each generated home's battery's efficiency, charge_efficiency and discharge_efficiency."""
    batteries = [home.battery_config for home in generate_homes_from_distribution(fleet, Location.bristol())]
    return [
        (battery.efficiency, battery.charge_efficiency, battery.discharge_efficiency)
        for battery in batteries
        if battery is not None
    ]


def test_a_drawn_round_trip_is_held_beside_the_pair_it_splits_into() -> None:
    efficiencies = _efficiencies(_fleet({"capacity_kwh": 5.0, "efficiency": 0.81}))

    assert efficiencies == [(0.81, math.sqrt(0.81), math.sqrt(0.81))] * 2


def test_a_per_direction_draw_contradicting_a_drawn_round_trip_is_refused_at_generation_naming_the_home() -> None:
    """The fleet's refusal is BatteryConfig's own, naming the fleet's battery block and the home."""
    fleet = _fleet({"capacity_kwh": 5.0, "efficiency": 0.92, "charge_efficiency": 0.96})
    with pytest.raises(ConfigurationError) as battery_refusal:
        BatteryConfig(capacity_kwh=5.0, efficiency=0.92, charge_efficiency=0.96)

    with pytest.raises(ConfigurationError) as fleet_refusal:
        generate_homes_from_distribution(fleet, Location.bristol())

    assert str(fleet_refusal.value) == f"fleet_distribution.battery: home 1: {battery_refusal.value}"


def test_a_per_direction_draw_at_its_default_gives_way_to_a_drawn_round_trip() -> None:
    """Unlike a home: battery block, which refuses both forms by key, whatever their values."""
    efficiencies = _efficiencies(_fleet({"capacity_kwh": 5.0, "efficiency": 0.92, "charge_efficiency": 0.975}))

    assert efficiencies == [(0.92, math.sqrt(0.92), math.sqrt(0.92))] * 2
