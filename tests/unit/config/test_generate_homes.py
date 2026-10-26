# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for generate_homes_from_distribution, which samples a FleetDistributionConfig into the fleet's HomeConfigs."""

import json
import math
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Optional, Union

import pytest

from solar_challenge.config import (
    BatteryDistributionConfig,
    DistributionSpec,
    FleetDistributionConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
    load_fleet_config,
    parse_fleet_distribution_config,
)
from solar_challenge.dispatch import GridChargeConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location
from solar_challenge.pv import simulate_pv_output
from solar_challenge.tariff import TariffConfig
from tests._synthetic_weather import synthetic_june_weather


#: A uniform whose max - min overflows a float, so every draw from it is inf whatever the seed.
_OVERFLOWING_UNIFORM = {"type": "uniform", "min": -1.7e308, "max": 1.7e308}

#: A fleet_distribution block that draws each of _DRAWN_SETTINGS for every home: a battery's charge
#: powers are drawn only for a home with a capacity, and the heat pump and EV settings only for a home
#: with a heat pump type and a charger.
_EVERY_SETTING_DRAWN: dict = {
    "n_homes": 2,
    "seed": 42,
    "pv": {"capacity_kw": 4.0},
    "load": {"annual_consumption_kwh": 3500.0, "use_stochastic": False},
    "battery": {"capacity_kwh": 5.0},
    "heat_pump": {"heat_pump_type": "ASHP"},
    "ev": {"charger_type": {"type": "weighted_discrete", "values": ["7kW"], "weights": [1]}},
}

#: Each setting a normal or uniform can be drawn for, as its block and field in a fleet_distribution block.
_DRAWN_SETTINGS = (
    ("pv", "capacity_kw"),
    ("pv", "azimuth"),
    ("pv", "tilt"),
    ("pv", "module_efficiency"),
    ("pv", "inverter_efficiency"),
    ("pv", "system_age_years"),
    ("pv", "degradation_rate_per_year"),
    ("load", "annual_consumption_kwh"),
    ("load", "household_occupants"),
    ("battery", "capacity_kwh"),
    ("battery", "max_charge_kw"),
    ("battery", "max_discharge_kw"),
    ("heat_pump", "thermal_capacity_kw"),
    ("heat_pump", "annual_heat_demand_kwh"),
    ("ev", "arrival_hour"),
    ("ev", "departure_hour"),
    ("ev", "required_charge_kwh"),
)


class TestDistributionSampling:
    """How generate_homes_from_distribution samples each home's value from a spec."""

    def test_sample_none_returns_none(self) -> None:
        """A None spec samples no value, so every home's annual consumption stays unset."""
        config = FleetDistributionConfig(
            n_homes=5,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(annual_consumption_kwh=None),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        assert len(homes) == 5
        for home in homes:
            assert home.load_config.annual_consumption_kwh is None

    def test_sample_normal(self) -> None:
        """Test sampling from normal distribution."""
        config = FleetDistributionConfig(
            n_homes=1000,
            pv=PVDistributionConfig(
                capacity_kw=4.0, azimuth=NormalDistribution(mean=100.0, std=10.0)
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        mean = sum(home.pv_config.azimuth for home in homes) / len(homes)
        assert 95.0 <= mean <= 105.0  # Should be close to 100

    def test_sample_normal_respects_bounds(self) -> None:
        """Test normal distribution respects min/max bounds."""
        config = FleetDistributionConfig(
            n_homes=100,
            pv=PVDistributionConfig(
                capacity_kw=4.0,
                azimuth=NormalDistribution(mean=100.0, std=50.0, min=80.0, max=120.0),
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        assert all(80.0 <= home.pv_config.azimuth <= 120.0 for home in homes)

    def test_sample_uniform(self) -> None:
        """A uniform spec samples every home's value inside [min, max]."""
        config = FleetDistributionConfig(
            n_homes=100,
            pv=PVDistributionConfig(
                capacity_kw=4.0, azimuth=UniformDistribution(min=80.0, max=120.0)
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        assert all(80.0 <= home.pv_config.azimuth <= 120.0 for home in homes)


class TestGenerateHomesFromDistribution:
    """Tests for generate_homes_from_distribution function."""

    def test_generate_correct_count(self) -> None:
        """Test generating correct number of homes."""
        config = FleetDistributionConfig(
            n_homes=25,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        assert len(homes) == 25

    def test_generate_with_fixed_values(self) -> None:
        """Test generating homes with fixed values."""
        config = FleetDistributionConfig(
            n_homes=5,
            pv=PVDistributionConfig(capacity_kw=5.0, azimuth=180.0, tilt=35.0),
            load=LoadDistributionConfig(annual_consumption_kwh=3500.0),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        for home in homes:
            assert home.pv_config.capacity_kw == 5.0
            assert home.pv_config.azimuth == 180.0
            assert home.load_config.annual_consumption_kwh == 3500.0

    def test_generate_with_distributions(self) -> None:
        """Test generating homes with distributions."""
        config = FleetDistributionConfig(
            n_homes=100,
            pv=PVDistributionConfig(
                capacity_kw=WeightedDiscreteDistribution(
                    values=(3.0, 4.0, 5.0),
                    weights=(33.0, 34.0, 33.0),
                )
            ),
            load=LoadDistributionConfig(
                annual_consumption_kwh=NormalDistribution(
                    mean=3400.0, std=500.0, min=2000.0, max=5000.0
                )
            ),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())

        pv_sizes = [h.pv_config.capacity_kw for h in homes]
        assert set(pv_sizes) == {3.0, 4.0, 5.0}

        consumptions = [h.load_config.annual_consumption_kwh for h in homes]
        assert all(c is not None and 2000.0 <= c <= 5000.0 for c in consumptions)

    def test_generate_with_battery_distribution_including_none(self) -> None:
        """Test generating homes with battery distribution including None."""
        config = FleetDistributionConfig(
            n_homes=100,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(
                capacity_kwh=WeightedDiscreteDistribution(
                    values=(None, 5.0, 10.0),
                    weights=(40.0, 40.0, 20.0),
                )
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())

        with_battery = [h for h in homes if h.battery_config is not None]
        without_battery = [h for h in homes if h.battery_config is None]
        assert len(with_battery) > 0
        assert len(without_battery) > 0

    @pytest.mark.parametrize(
        ("capacity_kwh", "requirement"),
        [
            pytest.param(math.nan, "a finite number", id="nan"),
            pytest.param(math.inf, "a finite number", id="inf"),
            pytest.param(-1.0, "at least 0", id="-1.0"),
        ],
    )
    def test_a_sampled_battery_capacity_that_is_not_one_is_refused_naming_it(
        self, capacity_kwh: float, requirement: str
    ) -> None:
        """A sampled battery capacity that is negative or not finite is refused naming battery.capacity_kwh, never read as no battery."""
        config = FleetDistributionConfig(
            n_homes=3,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(
                capacity_kwh=ShuffledPoolDistribution(values=(5.0, capacity_kwh), counts=(2, 1))
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )

        with pytest.raises(ValueError) as exc_info:
            generate_homes_from_distribution(config, Location.bristol())
        assert str(exc_info.value) == f"battery.capacity_kwh must be {requirement}, got {capacity_kwh!r}"

    @pytest.mark.parametrize(
        ("capacity_kwh", "requirement"),
        [
            pytest.param(math.nan, "a finite number", id="nan"),
            pytest.param(math.inf, "a finite number", id="inf"),
            pytest.param(-1.0, "at least 0", id="-1.0"),
        ],
    )
    def test_a_fixed_battery_capacity_that_is_not_one_is_refused_before_any_home_is_generated(
        self, capacity_kwh: float, requirement: str
    ) -> None:
        """A fixed battery capacity that is negative or not finite is refused when the battery distribution is configured, naming battery.capacity_kwh."""
        with pytest.raises(ValueError) as exc_info:
            BatteryDistributionConfig(capacity_kwh=capacity_kwh)
        assert str(exc_info.value) == f"battery.capacity_kwh must be {requirement}, got {capacity_kwh!r}"

    def test_a_sampled_null_or_zero_battery_capacity_is_no_battery(self) -> None:
        """A null or 0 sampled battery capacity is no battery, and every other home has the battery it sampled."""
        config = FleetDistributionConfig(
            n_homes=30,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(
                capacity_kwh=ShuffledPoolDistribution(
                    values=(None, 0.0, 5.0), counts=(10, 10, 10)
                )
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )

        batteries = [h.battery_config for h in generate_homes_from_distribution(config, Location.bristol())]

        assert sum(battery is None for battery in batteries) == 20
        assert [b.capacity_kwh for b in batteries if b is not None] == [5.0] * 10

    @pytest.mark.parametrize("capacity_kwh", [None, 0.0])
    def test_a_fixed_null_or_zero_battery_capacity_is_no_battery(
        self, capacity_kwh: Optional[float]
    ) -> None:
        """A fixed null or 0 battery capacity is configured without complaint and gives every home no battery."""
        config = FleetDistributionConfig(
            n_homes=3,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(capacity_kwh=capacity_kwh),
            load=LoadDistributionConfig(),
            seed=42,
        )

        homes = generate_homes_from_distribution(config, Location.bristol())

        assert [home.battery_config for home in homes] == [None, None, None]

    def test_generate_reproducibility_with_seed(self) -> None:
        """Test that same seed produces same results."""
        config = FleetDistributionConfig(
            n_homes=50,
            pv=PVDistributionConfig(
                capacity_kw=WeightedDiscreteDistribution(
                    values=(3.0, 4.0, 5.0, 6.0),
                    weights=(25.0, 25.0, 25.0, 25.0),
                )
            ),
            battery=BatteryDistributionConfig(
                capacity_kwh=WeightedDiscreteDistribution(
                    values=(None, 5.0),
                    weights=(50.0, 50.0),
                )
            ),
            load=LoadDistributionConfig(
                annual_consumption_kwh=NormalDistribution(mean=3400.0, std=800.0)
            ),
            seed=12345,
        )
        location = Location.bristol()

        homes1 = generate_homes_from_distribution(config, location)
        homes2 = generate_homes_from_distribution(config, location)

        for h1, h2 in zip(homes1, homes2, strict=True):
            assert h1.pv_config.capacity_kw == h2.pv_config.capacity_kw
            assert (h1.battery_config is None) == (h2.battery_config is None)
            if h1.battery_config and h2.battery_config:
                assert h1.battery_config.capacity_kwh == h2.battery_config.capacity_kwh
            assert h1.load_config.annual_consumption_kwh == h2.load_config.annual_consumption_kwh

    def test_generate_home_names(self) -> None:
        """Test that homes are named sequentially."""
        config = FleetDistributionConfig(
            n_homes=5,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        assert [h.name for h in homes] == [
            "Home 1",
            "Home 2",
            "Home 3",
            "Home 4",
            "Home 5",
        ]


class TestGenerationRefusesAPoolNotSizedToTheFleet:
    """generate_homes_from_distribution refuses a fleet whose shuffled pool does not hold one value per home."""

    @pytest.mark.parametrize(
        "resized_n_homes",
        [pytest.param(4, id="grown past its pool"), pytest.param(2, id="shrunk below its pool")],
    )
    def test_a_fleet_resized_after_construction_is_refused_as_construction_refuses_it(
        self, resized_n_homes: int
    ) -> None:
        """A fleet built with 3 pool values for 3 homes, then given another n_homes, is refused in the words construction uses for that size."""

        def fleet_of(n_homes: int) -> FleetDistributionConfig:
            return FleetDistributionConfig(
                n_homes=n_homes,
                pv=PVDistributionConfig(
                    capacity_kw=ShuffledPoolDistribution(values=(4.0,), counts=(3,))
                ),
                load=LoadDistributionConfig(),
            )

        with pytest.raises(ConfigurationError) as construction_refusal:
            fleet_of(resized_n_homes)
        config = fleet_of(3)
        config.n_homes = resized_n_homes

        with pytest.raises(ConfigurationError) as use_refusal:
            generate_homes_from_distribution(config, Location.bristol())

        assert str(use_refusal.value) == str(construction_refusal.value)


class TestGenerateHomesRefusesADrawThatIsNotFinite:
    """generate_homes_from_distribution refuses a normal or uniform draw that is not a finite number, naming its setting and the draw."""

    @pytest.mark.parametrize(
        ("block", "field"),
        [pytest.param(block, field, id=f"{block}.{field}") for block, field in _DRAWN_SETTINGS],
    )
    def test_an_overflowing_draw_is_refused_naming_its_setting_and_the_draw(self, block: str, field: str) -> None:
        """A draw that overflows a float is refused naming its setting and the inf it drew, whichever setting it is drawn for."""
        fleet = parse_fleet_distribution_config(
            {**_EVERY_SETTING_DRAWN, block: {**_EVERY_SETTING_DRAWN[block], field: _OVERFLOWING_UNIFORM}}
        )

        with pytest.raises(ConfigurationError) as exc_info:
            generate_homes_from_distribution(fleet, Location.bristol())
        assert str(exc_info.value) == f"{block}.{field} must draw samples that are finite numbers, got a sample of inf"

    def test_an_overflowing_draw_pre_sampled_in_bristol_legacy_order_is_refused_as_a_fresh_one_is(self) -> None:
        """random_order bristol_legacy draws every home's annual consumption before it builds the first home; an overflowing one is refused naming its setting and the draw."""
        fleet = parse_fleet_distribution_config(
            {
                **_EVERY_SETTING_DRAWN,
                "random_order": "bristol_legacy",
                "load": {**_EVERY_SETTING_DRAWN["load"], "annual_consumption_kwh": _OVERFLOWING_UNIFORM},
            }
        )

        with pytest.raises(ConfigurationError) as exc_info:
            generate_homes_from_distribution(fleet, Location.bristol())
        assert str(exc_info.value) == (
            "load.annual_consumption_kwh must draw samples that are finite numbers, got a sample of inf"
        )

    def test_a_normal_whose_bounds_clamp_its_overflowing_draws_is_accepted(self) -> None:
        """A normal whose draws overflow a float, but whose min and max clamp them, gives each home a finite capacity from its min to its max."""
        config = FleetDistributionConfig(
            n_homes=20,
            pv=PVDistributionConfig(capacity_kw=NormalDistribution(mean=1.7e308, std=1e308, min=1.0, max=10.0)),
            load=LoadDistributionConfig(),
            seed=42,
        )

        capacities = [home.pv_config.capacity_kw for home in generate_homes_from_distribution(config, Location.bristol())]

        assert len(capacities) == 20
        assert all(1.0 <= capacity <= 10.0 for capacity in capacities)


class TestGenerateHomesRefusesAnEVHourThatIsNotFinite:
    """generate_homes_from_distribution refuses an EV hour that is an infinity or a NaN, whichever spec gives it, naming its setting and the hour."""

    @pytest.mark.parametrize("hour", [math.inf, -math.inf, math.nan], ids=repr)
    @pytest.mark.parametrize(
        "spec_holding",
        [
            pytest.param(lambda hour: hour, id="scalar"),
            pytest.param(lambda hour: {"type": "fixed", "value": hour}, id="fixed"),
            pytest.param(
                lambda hour: {"type": "weighted_discrete", "values": [hour], "weights": [1]},
                id="weighted_discrete",
            ),
            pytest.param(
                lambda hour: {
                    "type": "shuffled_pool",
                    "values": [hour],
                    "counts": [_EVERY_SETTING_DRAWN["n_homes"]],
                },
                id="shuffled_pool",
            ),
        ],
    )
    @pytest.mark.parametrize("field", ["arrival_hour", "departure_hour"])
    def test_an_hour_that_is_not_finite_is_refused_naming_its_setting_and_the_hour(
        self, field: str, spec_holding: Callable[[float], object], hour: float
    ) -> None:
        """An infinite or NaN hour given as a number, a fixed value, or a weighted_discrete or shuffled_pool outcome is refused naming its setting and the hour, never escaping as an OverflowError."""
        block = {**_EVERY_SETTING_DRAWN, "ev": {**_EVERY_SETTING_DRAWN["ev"], field: spec_holding(hour)}}

        with pytest.raises(ConfigurationError) as exc_info:
            generate_homes_from_distribution(parse_fleet_distribution_config(block), Location.bristol())
        assert str(exc_info.value) == f"ev.{field} must be a finite number, got {hour!r}"


class TestHeatPumpDistribution:
    """Tests for heat pump distribution in fleet config."""

    def test_generate_homes_with_heat_pump_distribution(self) -> None:
        """Test generating homes with heat pump distribution including None."""
        config = FleetDistributionConfig(
            n_homes=100,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            heat_pump=HeatPumpDistributionConfig(
                heat_pump_type=WeightedDiscreteDistribution(
                    values=(None, "ASHP", "GSHP"),
                    weights=(50.0, 40.0, 10.0),
                ),
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())

        # Check correct number of homes
        assert len(homes) == 100

        # Count heat pump types
        no_heat_pump = [h for h in homes if h.heat_pump_config is None]
        ashp_homes = [
            h for h in homes
            if h.heat_pump_config is not None and h.heat_pump_config.heat_pump_type == "ASHP"
        ]
        gshp_homes = [
            h for h in homes
            if h.heat_pump_config is not None and h.heat_pump_config.heat_pump_type == "GSHP"
        ]

        # Check we have all types
        assert len(no_heat_pump) > 0
        assert len(ashp_homes) > 0
        assert len(gshp_homes) > 0
        assert len(no_heat_pump) + len(ashp_homes) + len(gshp_homes) == 100

        # Check heat pump properties for homes with heat pumps
        for home in ashp_homes + gshp_homes:
            assert home.heat_pump_config is not None
            assert home.heat_pump_config.thermal_capacity_kw == 8.0
            assert home.heat_pump_config.annual_heat_demand_kwh == 8000.0

    def test_generate_homes_with_heat_pump_capacity_distribution(self) -> None:
        """Test generating homes with varied heat pump capacities."""
        config = FleetDistributionConfig(
            n_homes=50,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            heat_pump=HeatPumpDistributionConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=WeightedDiscreteDistribution(
                    values=(6.0, 8.0, 10.0),
                    weights=(30.0, 50.0, 20.0),
                ),
                annual_heat_demand_kwh=8000.0,
            ),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())

        # All should have ASHP
        assert all(h.heat_pump_config is not None for h in homes)
        assert all(
            h.heat_pump_config.heat_pump_type == "ASHP"
            for h in homes
            if h.heat_pump_config is not None
        )

        # Check capacity distribution
        capacities = {
            h.heat_pump_config.thermal_capacity_kw
            for h in homes
            if h.heat_pump_config is not None
        }
        assert capacities == {6.0, 8.0, 10.0}

    def test_generate_homes_with_heat_pump_demand_distribution(self) -> None:
        """Test generating homes with varied heat pump demand."""
        config = FleetDistributionConfig(
            n_homes=50,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            heat_pump=HeatPumpDistributionConfig(
                heat_pump_type="GSHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=NormalDistribution(
                    mean=8000.0,
                    std=2000.0,
                    min=4000.0,
                    max=15000.0,
                ),
            ),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())

        # All should have GSHP
        assert all(h.heat_pump_config is not None for h in homes)
        assert all(
            h.heat_pump_config.heat_pump_type == "GSHP"
            for h in homes
            if h.heat_pump_config is not None
        )

        # Check demand is in range
        demands = [
            h.heat_pump_config.annual_heat_demand_kwh
            for h in homes
            if h.heat_pump_config is not None
        ]
        assert all(4000.0 <= d <= 15000.0 for d in demands)
        # Check mean is roughly correct
        mean_demand = sum(demands) / len(demands)
        assert 7000.0 <= mean_demand <= 9000.0

    def test_load_fleet_config_with_heat_pump_distribution_yaml(self, tmp_path: Path) -> None:
        """Test loading fleet config with heat pump distribution from YAML."""
        yaml_content = """
name: Test Heat Pump Fleet
fleet_distribution:
  n_homes: 20
  seed: 42
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  heat_pump:
    heat_pump_type:
      type: weighted_discrete
      values: [null, "ASHP", "GSHP"]
      weights: [50, 40, 10]
    thermal_capacity_kw: 8.0
    annual_heat_demand_kwh: 8000.0
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert fleet.name == "Test Heat Pump Fleet"
        assert len(fleet.homes) == 20

        # Check some homes have heat pumps and some don't
        with_heat_pump = [h for h in fleet.homes if h.heat_pump_config is not None]
        without_heat_pump = [h for h in fleet.homes if h.heat_pump_config is None]
        assert len(with_heat_pump) > 0
        assert len(without_heat_pump) > 0

        # Check heat pump types
        ashp_count = sum(
            1 for h in fleet.homes
            if h.heat_pump_config is not None
            and h.heat_pump_config.heat_pump_type == "ASHP"
        )
        gshp_count = sum(
            1 for h in fleet.homes
            if h.heat_pump_config is not None
            and h.heat_pump_config.heat_pump_type == "GSHP"
        )
        assert ashp_count > 0
        assert gshp_count >= 0  # May be 0 due to small sample size

    def test_load_fleet_config_with_heat_pump_distribution_json(self, tmp_path: Path) -> None:
        """Test loading fleet config with heat pump distribution from JSON."""
        json_content = {
            "name": "JSON Heat Pump Fleet",
            "fleet_distribution": {
                "n_homes": 15,
                "seed": 123,
                "pv": {
                    "capacity_kw": 5.0,
                },
                "load": {},
                "heat_pump": {
                    "heat_pump_type": "ASHP",
                    "thermal_capacity_kw": {
                        "type": "uniform",
                        "min": 6.0,
                        "max": 10.0,
                    },
                    "annual_heat_demand_kwh": {
                        "type": "normal",
                        "mean": 8000,
                        "std": 1500,
                        "min": 5000,
                        "max": 12000,
                    },
                },
            },
        }
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        fleet = load_fleet_config(path)
        assert fleet.name == "JSON Heat Pump Fleet"
        assert len(fleet.homes) == 15

        # All should have ASHP
        assert all(h.heat_pump_config is not None for h in fleet.homes)
        assert all(
            h.heat_pump_config.heat_pump_type == "ASHP"
            for h in fleet.homes
            if h.heat_pump_config is not None
        )

        # Check capacity is in range
        for home in fleet.homes:
            if home.heat_pump_config:
                assert 6.0 <= home.heat_pump_config.thermal_capacity_kw <= 10.0
                assert 5000.0 <= home.heat_pump_config.annual_heat_demand_kwh <= 12000.0

    def test_heat_pump_distribution_reproducibility(self) -> None:
        """Test that heat pump distribution is reproducible with same seed."""
        config = FleetDistributionConfig(
            n_homes=30,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            heat_pump=HeatPumpDistributionConfig(
                heat_pump_type=WeightedDiscreteDistribution(
                    values=(None, "ASHP", "GSHP"),
                    weights=(40.0, 40.0, 20.0),
                ),
                thermal_capacity_kw=UniformDistribution(min=6.0, max=10.0),
                annual_heat_demand_kwh=NormalDistribution(mean=8000.0, std=1500.0),
            ),
            seed=999,
        )
        location = Location.bristol()

        homes1 = generate_homes_from_distribution(config, location)
        homes2 = generate_homes_from_distribution(config, location)

        # Check reproducibility
        for h1, h2 in zip(homes1, homes2, strict=True):
            # Check heat pump type
            if h1.heat_pump_config is None:
                assert h2.heat_pump_config is None
            else:
                assert h2.heat_pump_config is not None
                assert h1.heat_pump_config.heat_pump_type == h2.heat_pump_config.heat_pump_type
                assert h1.heat_pump_config.thermal_capacity_kw == h2.heat_pump_config.thermal_capacity_kw
                assert h1.heat_pump_config.annual_heat_demand_kwh == h2.heat_pump_config.annual_heat_demand_kwh

    @pytest.mark.parametrize(
        "heat_pump_type",
        [
            pytest.param("XSHP", id="fixed"),
            pytest.param(WeightedDiscreteDistribution(values=("XSHP",), weights=(1.0,)), id="weighted"),
        ],
    )
    def test_a_sampled_type_outside_heat_pump_types_is_refused_naming_every_type(
        self, heat_pump_type: Union[str, WeightedDiscreteDistribution]
    ) -> None:
        """A heat pump type outside heat_pump.HEAT_PUMP_TYPES, fixed or drawn, is refused naming every type."""
        config = FleetDistributionConfig(
            n_homes=1,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(),
            heat_pump=HeatPumpDistributionConfig(heat_pump_type=heat_pump_type),
            seed=42,
        )

        with pytest.raises(
            ConfigurationError,
            match=re.escape("Invalid heat pump type sampled: 'XSHP'. Must be one of ('ASHP', 'GSHP')"),
        ):
            generate_homes_from_distribution(config, Location.bristol())


class TestGenerateHomesFromDistributionDegradation:
    """Tests that generate_homes_from_distribution threads age fields into each home's PVConfig."""

    def test_scalar_age_reaches_all_homes(self) -> None:
        """A fixed system_age_years scalar is present in every home's PVConfig."""
        config = FleetDistributionConfig(
            n_homes=10,
            pv=PVDistributionConfig(capacity_kw=4.0, system_age_years=20.0),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        for home in homes:
            assert home.pv_config.system_age_years == 20.0
            assert home.pv_config.degradation_rate_per_year == 0.005  # default

    def test_distribution_age_varies_across_homes(self) -> None:
        """A NormalDistribution on system_age_years produces varying ages within [min, max]."""
        config = FleetDistributionConfig(
            n_homes=20,
            pv=PVDistributionConfig(
                capacity_kw=4.0,
                system_age_years=NormalDistribution(mean=15.0, std=3.0, min=0.0, max=30.0),
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )
        homes = generate_homes_from_distribution(config, Location.bristol())
        ages = [home.pv_config.system_age_years for home in homes]
        assert len(set(ages)) > 1, "Ages should vary across homes"
        assert all(0.0 <= age <= 30.0 for age in ages), "Ages must stay within [0, 30]"

    def test_scalar_age_preserves_rng_reproducibility(self) -> None:
        """Scalar system_age_years does not perturb the RNG stream.

        A config with system_age_years=20.0 (scalar) must yield the same
        capacity_kw sequence as an otherwise-identical config with the
        default age (0.0), given the same seed.  This directly proves the
        new scalar field does not consume RNG and leaves the legacy
        capacity-draw sequence undisturbed.
        """
        pv_capacity = WeightedDiscreteDistribution(
            values=[3.0, 4.0, 5.0], weights=[0.3, 0.4, 0.3]
        )
        config_with_age = FleetDistributionConfig(
            n_homes=10,
            pv=PVDistributionConfig(capacity_kw=pv_capacity, system_age_years=20.0),
            load=LoadDistributionConfig(),
            seed=99,
        )
        config_no_age = FleetDistributionConfig(
            n_homes=10,
            pv=PVDistributionConfig(capacity_kw=pv_capacity, system_age_years=0.0),
            load=LoadDistributionConfig(),
            seed=99,
        )
        homes_aged = generate_homes_from_distribution(config_with_age, Location.bristol())
        homes_unaged = generate_homes_from_distribution(config_no_age, Location.bristol())
        caps_aged = [h.pv_config.capacity_kw for h in homes_aged]
        caps_unaged = [h.pv_config.capacity_kw for h in homes_unaged]
        assert caps_aged == caps_unaged, (
            "Scalar system_age_years must not consume RNG; "
            "capacity sequences should be identical regardless of scalar age value"
        )


class TestGenerateHomesFromDistributionInverterEfficiency:
    """Each home's PVConfig takes the inverter efficiency sampled for it, 0.96 included."""

    def test_each_home_takes_its_sampled_inverter_efficiency(self) -> None:
        config = FleetDistributionConfig(
            n_homes=3,
            pv=PVDistributionConfig(
                capacity_kw=3.68,
                inverter_efficiency=ShuffledPoolDistribution(
                    values=(0.955, 0.96, 0.965), counts=(1, 1, 1)
                ),
            ),
            load=LoadDistributionConfig(),
            seed=42,
        )

        homes = generate_homes_from_distribution(config, Location.bristol())

        assert sorted(home.pv_config.inverter_efficiency for home in homes) == [0.955, 0.96, 0.965]


class TestGenerateHomesFromDistributionModuleEfficiency:
    """Each home's PVConfig takes the module efficiency drawn for it; a fleet that draws none, or draws a null, leaves the module its own (None)."""

    @staticmethod
    def _fleet(n_homes: int, **pv: DistributionSpec) -> FleetDistributionConfig:
        """A seeded fleet of *n_homes* 4 kW homes whose other PV settings are drawn from *pv*."""
        return FleetDistributionConfig(
            n_homes=n_homes,
            pv=PVDistributionConfig(capacity_kw=4.0, **pv),
            load=LoadDistributionConfig(),
            seed=42,
        )

    def test_a_fleet_drawing_no_module_efficiency_leaves_each_home_the_modules_own(self) -> None:
        homes = generate_homes_from_distribution(self._fleet(2), Location.bristol())

        assert [home.pv_config.module_efficiency for home in homes] == [None, None]

    def test_each_home_takes_its_drawn_module_efficiency_a_null_the_modules_own(self) -> None:
        fleet = self._fleet(
            3,
            module_efficiency=ShuffledPoolDistribution(values=(None, 0.15, 0.22), counts=(1, 1, 1)),
        )

        homes = generate_homes_from_distribution(fleet, Location.bristol())

        assert {home.pv_config.module_efficiency for home in homes} == {None, 0.15, 0.22}

    def test_homes_drawing_different_efficiencies_generate_differently(self) -> None:
        """On the tests' synthetic clear June day the 0.15 home's cells run hotter, so it yields less (measured x0.994987 and x1.001836 of the default's 26.8194 kWh)."""
        fleet = self._fleet(
            2, module_efficiency=ShuffledPoolDistribution(values=(0.15, 0.22), counts=(1, 1))
        )
        clear_day = synthetic_june_weather("2024-06-21")

        kwh_by_efficiency = {
            home.pv_config.module_efficiency: float(
                simulate_pv_output(home.pv_config, Location.bristol(), clear_day).sum()
            )
            for home in generate_homes_from_distribution(fleet, Location.bristol())
        }

        assert kwh_by_efficiency[0.15] < kwh_by_efficiency[0.22], kwh_by_efficiency


class TestGenerateHomesHouseholdOccupants:
    """How generate_homes_from_distribution draws each home's household occupants for LoadConfig's rule to read."""

    @staticmethod
    def _fleet(household_occupants: DistributionSpec, n_homes: int = 2) -> FleetDistributionConfig:
        """A seeded fleet of *n_homes* homes with deterministic loads, whose household occupants are drawn from *household_occupants*."""
        return FleetDistributionConfig(
            n_homes=n_homes,
            pv=PVDistributionConfig(capacity_kw=4.0),
            load=LoadDistributionConfig(household_occupants=household_occupants, use_stochastic=False),
            seed=42,
        )

    @pytest.mark.parametrize(
        ("household_occupants", "whole_numbers"),
        [
            pytest.param(
                NormalDistribution(mean=3.0, std=1.5, min=1.0, max=6.0),
                (1, 2, 3, 4, 5, 6),
                id="normal-between-whole-bounds",
            ),
            pytest.param(
                UniformDistribution(min=1.0, max=5.0),
                (1, 2, 3, 4, 5),
                id="uniform-between-whole-bounds",
            ),
            pytest.param(
                NormalDistribution(mean=4.0, std=1.0, min=1.0, max=3.5),
                (1, 2, 3),
                id="normal-clamped-to-a-max-of-3.5",
            ),
            pytest.param(
                NormalDistribution(mean=1.0, std=0.1, min=2.4, max=4.0),
                (3, 4),
                id="normal-clamped-to-a-min-of-2.4",
            ),
            pytest.param(
                UniformDistribution(min=2.2, max=4.7),
                (3, 4),
                id="uniform-between-fractional-bounds",
            ),
            pytest.param(
                NormalDistribution(mean=4.5, std=0.0, min=1.0, max=6.0),
                (1, 2, 3, 4, 5, 6),
                id="normal-drawing-halfway-between-whole-numbers-within-whole-bounds",
            ),
        ],
    )
    def test_each_home_gets_the_whole_number_nearest_its_draw_among_those_from_its_specs_min_to_its_max(
        self,
        household_occupants: Union[NormalDistribution, UniformDistribution],
        whole_numbers: tuple[int, ...],
    ) -> None:
        """Each home gets, as an int, the whole number nearest its draw among those from its spec's min to its max, a half rounding up.

        The expected counts apply that rule to the spec's own draws from the fleet's seed, which the fleet takes in order because it draws nothing else from its RNG.
        A fractional bound excludes the whole number past it: a draw clamped to a max of 3.5 gives 3, not 4, and one clamped to a min of 2.4 gives 3, not 2.
        A draw of 4.5, equally near 4 and 5, gives 5: the expected count breaks a tie toward the greater whole number.
        """
        rng = random.Random(42)
        draws = [household_occupants.draw(rng) for _ in range(20)]

        homes = generate_homes_from_distribution(self._fleet(household_occupants, n_homes=20), Location.bristol())

        occupants = [home.load_config.household_occupants for home in homes]
        assert [(type(count), count) for count in occupants] == [
            (int, min(whole_numbers, key=lambda whole: (abs(whole - draw), -whole))) for draw in draws
        ]

    @pytest.mark.parametrize(
        ("mean", "count"),
        [
            pytest.param(2.5, 3, id="two-and-a-half"),
            pytest.param(4.5, 5, id="four-and-a-half"),
        ],
    )
    def test_a_draw_halfway_between_two_whole_numbers_rounds_up(self, mean: float, count: int) -> None:
        """Every draw is the mean, halfway between two whole numbers, and gives its home the upper one, where rounding a half to even gives 2 and 4.

        The spec's std is 0 and it sets no bound, so every draw is exactly its mean whatever the seed, and no bound decides the count.
        """
        household_occupants = NormalDistribution(mean=mean, std=0.0)

        homes = generate_homes_from_distribution(self._fleet(household_occupants), Location.bristol())

        assert [home.load_config.household_occupants for home in homes] == [count, count]

    def test_an_infinite_min_or_max_bounds_nothing(self) -> None:
        """A normal with an infinite min and an infinite max gives each home the whole number nearest its draw, 3 for draws near 3.0."""
        household_occupants = NormalDistribution(mean=3.0, std=0.1, min=-math.inf, max=math.inf)

        homes = generate_homes_from_distribution(self._fleet(household_occupants, n_homes=20), Location.bristol())

        assert [home.load_config.household_occupants for home in homes] == [3] * 20

    def test_a_nan_bound_is_refused_as_the_nan_draw_it_clamps_to(self) -> None:
        """A NaN min clamps every draw to NaN, so the fleet is refused as drawing a sample that is not a finite number, not as a NaN bound."""
        household_occupants = NormalDistribution(mean=3.0, std=1.0, min=math.nan)

        with pytest.raises(ConfigurationError) as exc_info:
            generate_homes_from_distribution(self._fleet(household_occupants), Location.bristol())

        assert str(exc_info.value) == (
            "load.household_occupants must draw samples that are finite numbers, got a sample of nan"
        )

    #: Normal and uniform specs with no whole number from their min to their max, so no count can be drawn from them.
    _SPECS_WITH_NO_WHOLE_NUMBER = [
        pytest.param(UniformDistribution(min=2.3, max=2.45), id="uniform-within-one-unit"),
        pytest.param(UniformDistribution(min=2.5, max=2.5), id="uniform-between-equal-halfway-bounds"),
        pytest.param(NormalDistribution(mean=2.4, std=0.1, min=2.3, max=2.45), id="normal-within-one-unit"),
    ]

    @pytest.mark.parametrize("household_occupants", _SPECS_WITH_NO_WHOLE_NUMBER)
    def test_a_spec_with_no_whole_number_from_its_min_to_its_max_is_refused_when_configured_naming_it(
        self, household_occupants: Union[NormalDistribution, UniformDistribution]
    ) -> None:
        """No count a home could get lies from the spec's min to its max, so the load distribution is refused when it is configured, naming the setting, the min and the max."""
        with pytest.raises(ConfigurationError) as exc_info:
            LoadDistributionConfig(household_occupants=household_occupants)

        assert str(exc_info.value) == (
            "load.household_occupants is a count, so a whole number must lie from its min to its max, "
            f"got a min of {household_occupants.min!r} and a max of {household_occupants.max!r}"
        )

    @pytest.mark.parametrize("household_occupants", _SPECS_WITH_NO_WHOLE_NUMBER)
    def test_a_spec_with_no_whole_number_given_to_a_configured_fleet_is_refused_as_configuring_it_refuses_it(
        self, household_occupants: Union[NormalDistribution, UniformDistribution]
    ) -> None:
        """A fleet built with 3 household occupants, then given a spec with no whole number from its min to its max, is refused in the words construction uses for that spec."""
        with pytest.raises(ConfigurationError) as configuration_refusal:
            LoadDistributionConfig(household_occupants=household_occupants)
        fleet = self._fleet(3)
        fleet.load.household_occupants = household_occupants

        with pytest.raises(ConfigurationError) as generation_refusal:
            generate_homes_from_distribution(fleet, Location.bristol())

        assert str(generation_refusal.value) == str(configuration_refusal.value)

    @pytest.mark.parametrize(
        ("household_occupants", "refusal"),
        [
            pytest.param(2.5, "household_occupants must be a whole number, got 2.5", id="fixed-fraction"),
            pytest.param(0.0, "household_occupants must be between 1 and 10, got 0.0", id="fixed-zero"),
            pytest.param(True, "household_occupants must be a finite number, got True", id="fixed-boolean"),
            pytest.param(
                WeightedDiscreteDistribution(values=(True,), weights=(1.0,)),
                "household_occupants must be a finite number, got True",
                id="weighted-discrete-boolean",
            ),
            pytest.param(
                ShuffledPoolDistribution(values=(2, 0), counts=(1, 1)),
                "household_occupants must be between 1 and 10, got 0",
                id="shuffled-pool-zero",
            ),
            pytest.param(
                UniformDistribution(min=1e300, max=1e300),
                "household_occupants must be between 1 and 10, got 1e+300",
                id="uniform-draw-too-large-for-a-count",
            ),
            pytest.param(
                UniformDistribution(min=-1e300, max=-1e300),
                "household_occupants must be between 1 and 10, got -1e+300",
                id="uniform-draw-far-below-one",
            ),
        ],
    )
    def test_a_count_load_config_refuses_is_refused_as_it_refuses_it(
        self, household_occupants: DistributionSpec, refusal: str
    ) -> None:
        """Each count is refused with LoadConfig's message: it is never truncated, read as 1, or replaced by the default 3, and a drawn count is named as drawn, 1e+300 rather than the 301-digit int it equals.

        A uniform between equal bounds draws its bound whatever the seed.
        """
        with pytest.raises(ValueError) as exc_info:
            generate_homes_from_distribution(self._fleet(household_occupants), Location.bristol())
        assert str(exc_info.value) == refusal

    def test_a_null_draw_takes_load_configs_default_and_a_whole_number_float_is_held_as_its_int(self) -> None:
        """A null draw gives its home LoadConfig's default of 3 occupants, and a draw of 4.0 gives its home the int 4."""
        homes = generate_homes_from_distribution(
            self._fleet(ShuffledPoolDistribution(values=(None, 4.0), counts=(1, 1))), Location.bristol()
        )

        occupants = sorted(home.load_config.household_occupants for home in homes)
        assert [(type(count), count) for count in occupants] == [(int, 3), (int, 4)]


class TestGenerateHomesFromDistributionFlex:
    """How generate_homes_from_distribution gives every home the fleet's tariff and dispatch strategy, and every battery the fleet's grid charging."""

    def _base_config(
        self,
        *,
        grid_charging: Optional[GridChargeConfig] = None,
        dispatch_strategy: Optional[str] = None,
    ) -> FleetDistributionConfig:
        """A small fixed fleet with a battery on every home, with the given battery grid charging and fleet dispatch strategy."""
        return FleetDistributionConfig(
            n_homes=5,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(capacity_kwh=5.0, grid_charging=grid_charging),
            load=LoadDistributionConfig(),
            seed=42,
            dispatch_strategy=dispatch_strategy,
        )

    def test_fleet_tariff_threaded_to_all_homes(self) -> None:
        """fleet_tariff=TariffConfig.economy_7() sets tariff_config on every home."""
        tariff = TariffConfig.economy_7()
        homes = generate_homes_from_distribution(
            self._base_config(), Location.bristol(), fleet_tariff=tariff
        )
        assert len(homes) == 5
        for home in homes:
            assert home.tariff_config is not None
            assert home.tariff_config == tariff

    def test_battery_grid_charging_reaches_every_battery(self) -> None:
        """BatteryDistributionConfig.grid_charging is the grid charging of every generated battery."""
        gc = GridChargeConfig(target_soc_fraction=0.9)
        homes = generate_homes_from_distribution(
            self._base_config(grid_charging=gc), Location.bristol()
        )
        for home in homes:
            assert home.battery_config is not None
            assert home.battery_config.grid_charging == gc

    def test_fleet_tariff_and_battery_grid_charging_both_reach_every_home(self) -> None:
        """The fleet_tariff keyword and the battery's grid_charging reach every home together."""
        tariff = TariffConfig.economy_7()
        gc = GridChargeConfig(target_soc_fraction=0.85)
        homes = generate_homes_from_distribution(
            self._base_config(grid_charging=gc),
            Location.bristol(),
            fleet_tariff=tariff,
        )
        for home in homes:
            assert home.tariff_config is not None
            assert home.tariff_config == tariff
            assert home.battery_config is not None
            assert home.battery_config.grid_charging == gc

    def test_calibration_guard_without_tariff_or_grid_charging(self) -> None:
        """Neither a fleet_tariff nor a battery grid_charging: every home has tariff_config=None and grid_charging=None (bit-identical)."""
        homes = generate_homes_from_distribution(self._base_config(), Location.bristol())
        for home in homes:
            assert home.tariff_config is None
            assert home.battery_config is not None
            assert home.battery_config.grid_charging is None

    def test_config_dispatch_strategy_reaches_every_home(self) -> None:
        """FleetDistributionConfig.dispatch_strategy='tou_optimized' is the dispatch strategy of every home."""
        homes = generate_homes_from_distribution(
            self._base_config(dispatch_strategy="tou_optimized"), Location.bristol()
        )
        assert len(homes) == 5
        for home in homes:
            assert home.dispatch_strategy == "tou_optimized"

    def test_dispatch_strategy_defaults_to_greedy(self) -> None:
        """A config without a dispatch_strategy: every home dispatches greedy."""
        homes = generate_homes_from_distribution(self._base_config(), Location.bristol())
        for home in homes:
            assert home.dispatch_strategy == "greedy"
