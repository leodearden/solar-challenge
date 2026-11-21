# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every block reader that builds an input type refuses as its type does, prefixed by the block's path."""

import math
from typing import Any, Callable

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import PeakShavingStrategyConfig, TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import constructed, parse_home_block, parse_location_block
from tests._construction_refusals import construction_refusal, prefixed_construction_refusal


class TestConstructed:
    """constructed builds a type from the values given, and re-raises its refusal prefixed by the block's path."""

    def test_it_is_the_type_built_from_the_values(self) -> None:
        assert constructed("home.pv", PVConfig, capacity_kw=4.0) == PVConfig(capacity_kw=4.0)

    def test_a_refusal_of_the_type_is_re_raised_prefixed_by_the_blocks_path_from_the_refusal(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("home.pv", PVConfig, capacity_kw=True)

        assert str(refusal.value) == prefixed_construction_refusal("home.pv", lambda: PVConfig(capacity_kw=True))
        assert isinstance(refusal.value.__cause__, ConfigurationError)
        assert str(refusal.value.__cause__) == construction_refusal(lambda: PVConfig(capacity_kw=True))

    def test_the_top_level_is_named_the_top_level(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("", PVConfig, capacity_kw=True)

        assert str(refusal.value) == prefixed_construction_refusal(
            "the top level", lambda: PVConfig(capacity_kw=True)
        )

    def test_a_type_error_is_re_raised_as_a_configuration_error_prefixed_by_the_blocks_path_from_it(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("x", PVConfig, capacity_kw=4.0, no_such_key=1)

        assert isinstance(refusal.value.__cause__, TypeError)
        assert "no_such_key" in str(refusal.value.__cause__)
        assert str(refusal.value) == f"x: {refusal.value.__cause__}"


def _home(blocks: dict[str, Any], *, block_path: str = "home") -> Callable[[], HomeConfig]:
    """Read a home: block holding only *blocks*, at *block_path* in its file, at the Bristol default location."""
    return lambda: parse_home_block(blocks, Location.bristol(), block_path=block_path)


_COMPONENT_BLOCK_ROWS = [
    pytest.param(
        lambda: parse_location_block({"latitude": 51.45, "longitude": -2.58, "altitude": math.nan}),
        "location",
        lambda: Location(latitude=51.45, longitude=-2.58, altitude=math.nan),
        id="location-altitude-nan",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}),
        "home.pv",
        lambda: PVConfig(capacity_kw=True),
        id="home-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}, block_path="homes[1]"),
        "homes[1].pv",
        lambda: PVConfig(capacity_kw=True),
        id="homes-entry-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}, block_path=""),
        "pv",
        lambda: PVConfig(capacity_kw=True),
        id="flat-home-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": 4.0, "azimuth": "south"}}),
        "home.pv",
        lambda: PVConfig(capacity_kw=4.0, azimuth="south"),
        id="home-pv-azimuth-word",
    ),
    pytest.param(
        _home({"battery": {"capacity_kwh": True}}),
        "home.battery",
        lambda: BatteryConfig(capacity_kwh=True),
        id="home-battery-capacity-boolean",
    ),
    pytest.param(
        _home({
            "battery": {
                "capacity_kwh": 5.0,
                "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": True},
            },
        }),
        "home.battery.dispatch_strategy",
        lambda: PeakShavingStrategyConfig(import_limit_kw=True),
        id="home-battery-peak-shaving-limit-boolean",
    ),
    pytest.param(
        _home({
            "battery": {
                "capacity_kwh": 5.0,
                "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[20, 16]]},
            },
        }),
        "home.battery.dispatch_strategy",
        lambda: TOUOptimizedStrategyConfig(((20, 16),)),
        id="home-battery-tou-window-reversed",
    ),
    pytest.param(
        _home({"load": {"household_occupants": 2.5}}),
        "home.load",
        lambda: LoadConfig(household_occupants=2.5),
        id="home-load-occupants-not-whole",
    ),
    pytest.param(
        _home({"heat_pump": {"heat_pump_type": "ASHP", "thermal_capacity_kw": math.nan}}),
        "home.heat_pump",
        lambda: HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=math.nan),
        id="home-heat-pump-capacity-nan",
    ),
    pytest.param(
        _home({"ev": {"charger_type": "7kW", "arrival_hour": 18.9}}),
        "home.ev",
        lambda: EVConfig(charger_type="7kW", arrival_hour=18.9),
        id="home-ev-arrival-not-whole",
    ),
]


@pytest.mark.parametrize(("read", "label", "construct"), _COMPONENT_BLOCK_ROWS)
def test_a_value_its_blocks_type_refuses_is_refused_prefixed_by_the_blocks_path(
    read: Callable[[], object], label: str, construct: Callable[[], object]
) -> None:
    with pytest.raises(ConfigurationError) as refusal:
        read()

    assert str(refusal.value) == prefixed_construction_refusal(label, construct)
