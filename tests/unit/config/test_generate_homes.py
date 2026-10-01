# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for generate_homes_from_distribution, which samples a FleetDistributionConfig into the fleet's HomeConfigs."""

import json
import tempfile
from pathlib import Path

from solar_challenge.config import (
    BatteryDistributionConfig,
    FleetDistributionConfig,
    GridChargeConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
    load_fleet_config,
)
from solar_challenge.location import Location
from solar_challenge.tariff import TariffConfig


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

    def test_load_fleet_config_with_heat_pump_distribution_yaml(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
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
        finally:
            path.unlink()

    def test_load_fleet_config_with_heat_pump_distribution_json(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
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
        finally:
            path.unlink()

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


class TestGenerateHomesFromDistributionFlex:
    """Tests for fleet_tariff and fleet_grid_charging threading in generate_homes_from_distribution."""

    def _base_config(self) -> FleetDistributionConfig:
        """A small fixed fleet with a battery on every home (capacity_kwh fixed value)."""
        return FleetDistributionConfig(
            n_homes=5,
            pv=PVDistributionConfig(capacity_kw=4.0),
            battery=BatteryDistributionConfig(capacity_kwh=5.0),
            load=LoadDistributionConfig(),
            seed=42,
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

    def test_fleet_grid_charging_threaded_to_all_battery_homes(self) -> None:
        """fleet_grid_charging=GridChargeConfig(...) threads grid_charging to every battery home."""
        gc = GridChargeConfig(target_soc_fraction=0.9)
        homes = generate_homes_from_distribution(
            self._base_config(), Location.bristol(), fleet_grid_charging=gc
        )
        for home in homes:
            assert home.battery_config is not None  # all homes have batteries
            assert home.battery_config.grid_charging is not None
            assert home.battery_config.grid_charging.target_soc_fraction == 0.9

    def test_both_fleet_tariff_and_grid_charging_threaded(self) -> None:
        """Both fleet_tariff and fleet_grid_charging are threaded simultaneously."""
        tariff = TariffConfig.economy_7()
        gc = GridChargeConfig(target_soc_fraction=0.85)
        homes = generate_homes_from_distribution(
            self._base_config(),
            Location.bristol(),
            fleet_tariff=tariff,
            fleet_grid_charging=gc,
        )
        for home in homes:
            assert home.tariff_config is not None
            assert home.tariff_config == tariff
            assert home.battery_config is not None
            assert home.battery_config.grid_charging is not None
            assert home.battery_config.grid_charging.target_soc_fraction == 0.85

    def test_calibration_guard_no_new_kwargs(self) -> None:
        """No new kwargs: tariff_config=None and grid_charging=None on every home (bit-identical)."""
        homes = generate_homes_from_distribution(self._base_config(), Location.bristol())
        for home in homes:
            assert home.tariff_config is None
            assert home.battery_config is not None
            assert home.battery_config.grid_charging is None

    def test_fleet_dispatch_strategy_threaded_to_all_homes(self) -> None:
        """fleet_dispatch_strategy='tou_optimized' sets dispatch_strategy on every home."""
        homes = generate_homes_from_distribution(
            self._base_config(), Location.bristol(), fleet_dispatch_strategy="tou_optimized"
        )
        assert len(homes) == 5
        for home in homes:
            assert home.dispatch_strategy == "tou_optimized"

    def test_dispatch_strategy_defaults_to_greedy(self) -> None:
        """No fleet_dispatch_strategy kwarg: every home defaults to dispatch_strategy='greedy'."""
        homes = generate_homes_from_distribution(self._base_config(), Location.bristol())
        for home in homes:
            assert home.dispatch_strategy == "greedy"

    def test_dispatch_strategy_empty_string_defaults_to_greedy(self) -> None:
        """Empty-string fleet_dispatch_strategy='': every home falls back to 'greedy'.

        Documents the `fleet_dispatch_strategy or "greedy"` contract so future
        editors cannot silently break the empty-string case.
        """
        homes = generate_homes_from_distribution(
            self._base_config(), Location.bristol(), fleet_dispatch_strategy=""
        )
        for home in homes:
            assert home.dispatch_strategy == "greedy"
