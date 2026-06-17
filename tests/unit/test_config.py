"""Tests for configuration file support."""

import json
import random
import tempfile
from pathlib import Path

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.config import (
    BatteryDistributionConfig,
    ConfigurationError,
    DispatchStrategyConfig,
    FinanceConfig,
    FleetDistributionConfig,
    GridChargeConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    OutputConfig,
    ParameterSweepConfig,
    PVDistributionConfig,
    ScenarioConfig,
    SimulationPeriod,
    UniformDistribution,
    WeightedDiscreteDistribution,
    _parse_battery_config,
    _parse_community_config,
    _parse_dispatch_strategy_config,
    _parse_ev_config,
    _parse_finance_config,
    _parse_heat_pump_config,
    _parse_home_config,
    _parse_pv_config,
    _parse_pv_distribution_config,
    _modify_pv_config,
    load_community_config,
    _parse_distribution_spec,
    _parse_fleet_distribution_config,
    _sample_from_distribution,
    generate_homes_from_distribution,
    load_config,
    load_config_json,
    load_config_yaml,
    load_fleet_config,
    load_home_config,
    load_scenarios,
)
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, calculate_degradation_factor
from solar_challenge.tariff import TariffConfig


class TestSimulationPeriod:
    """Tests for SimulationPeriod class."""

    def test_string_dates(self) -> None:
        """Test period with string dates."""
        period = SimulationPeriod(
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        assert period.start_date == "2024-01-01"
        assert period.end_date == "2024-01-07"

    def test_get_timestamps(self) -> None:
        """Test getting timestamps from string dates."""
        period = SimulationPeriod(
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        start = period.get_start_timestamp("Europe/London")
        end = period.get_end_timestamp("Europe/London")
        assert start.year == 2024
        assert start.month == 1
        assert start.day == 1
        assert end.day == 7


class TestOutputConfig:
    """Tests for OutputConfig class."""

    def test_defaults(self) -> None:
        """Test default output configuration."""
        config = OutputConfig()
        assert config.csv_path is None
        assert config.include_minute_data is True
        assert config.include_summary is True
        assert config.aggregation == "minute"

    def test_custom_values(self) -> None:
        """Test custom output configuration."""
        config = OutputConfig(
            csv_path="/output/results.csv",
            include_minute_data=False,
            aggregation="daily",
        )
        assert config.csv_path == "/output/results.csv"
        assert config.include_minute_data is False
        assert config.aggregation == "daily"


class TestScenarioConfig:
    """Tests for ScenarioConfig class."""

    def test_single_home_scenario(self) -> None:
        """Test scenario with single home."""
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400),
        )
        scenario = ScenarioConfig(
            name="Test",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            home=home,
        )
        assert not scenario.is_fleet
        assert scenario.home == home
        assert len(scenario.homes) == 0

    def test_fleet_scenario(self) -> None:
        """Test scenario with multiple homes."""
        homes = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=i),
                load_config=LoadConfig(annual_consumption_kwh=3000),
            )
            for i in [3.0, 4.0, 5.0]
        ]
        scenario = ScenarioConfig(
            name="Test Fleet",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            homes=homes,
        )
        assert scenario.is_fleet
        assert len(scenario.homes) == 3

    def test_requires_home_or_homes(self) -> None:
        """Test that scenario requires home or homes."""
        with pytest.raises(ConfigurationError, match="must define either"):
            ScenarioConfig(
                name="Empty",
                period=SimulationPeriod("2024-01-01", "2024-01-07"),
            )

    def test_cannot_have_both(self) -> None:
        """Test that scenario cannot have both home and homes."""
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        with pytest.raises(ConfigurationError, match="cannot define both"):
            ScenarioConfig(
                name="Both",
                period=SimulationPeriod("2024-01-01", "2024-01-07"),
                home=home,
                homes=[home],
            )

    def test_get_location_default(self) -> None:
        """Test default location is Bristol."""
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        scenario = ScenarioConfig(
            name="Test",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            home=home,
        )
        loc = scenario.get_location()
        assert loc.latitude == pytest.approx(51.45, abs=0.01)


class TestParameterSweepConfig:
    """Tests for ParameterSweepConfig class."""

    def test_explicit_values(self) -> None:
        """Test sweep with explicit values."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            values=[0, 5, 10, 15],
        )
        assert sweep.get_values() == [0, 5, 10, 15]

    def test_range_with_step(self) -> None:
        """Test sweep with range and step."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            min_value=0,
            max_value=10,
            step=2,
        )
        values = sweep.get_values()
        assert values == [0, 2, 4, 6, 8, 10]

    def test_range_with_n_steps(self) -> None:
        """Test sweep with range and n_steps."""
        sweep = ParameterSweepConfig(
            parameter_name="pv_capacity_kw",
            min_value=2,
            max_value=6,
            n_steps=4,
        )
        values = sweep.get_values()
        assert len(values) == 5
        assert values[0] == 2
        assert values[-1] == 6

    def test_empty_values_raises(self) -> None:
        """Test that empty values list raises error."""
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            ParameterSweepConfig(
                parameter_name="test",
                values=[],
            )

    def test_invalid_range_raises(self) -> None:
        """Test that invalid range raises error."""
        with pytest.raises(ConfigurationError, match="must be less than"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=10,
                max_value=5,
                step=1,
            )

    def test_missing_step_raises(self) -> None:
        """Test that missing step raises error."""
        with pytest.raises(ConfigurationError, match="requires either"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=0,
                max_value=10,
            )


class TestDispatchStrategyConfig:
    """Tests for DispatchStrategyConfig class."""

    def test_self_consumption_strategy(self) -> None:
        """Test self-consumption strategy configuration."""
        config = DispatchStrategyConfig(strategy_type="self_consumption")
        assert config.strategy_type == "self_consumption"
        assert config.peak_hours is None
        assert config.import_limit_kw is None

    def test_tou_optimized_strategy(self) -> None:
        """Test TOU optimized strategy configuration."""
        config = DispatchStrategyConfig(
            strategy_type="tou_optimized",
            peak_hours=[(16, 20), (7, 9)],
        )
        assert config.strategy_type == "tou_optimized"
        assert config.peak_hours == [(16, 20), (7, 9)]

    def test_peak_shaving_strategy(self) -> None:
        """Test peak-shaving strategy configuration."""
        config = DispatchStrategyConfig(
            strategy_type="peak_shaving",
            import_limit_kw=5.0,
        )
        assert config.strategy_type == "peak_shaving"
        assert config.import_limit_kw == 5.0

    def test_invalid_strategy_type_raises(self) -> None:
        """Test invalid strategy type raises error."""
        with pytest.raises(ConfigurationError, match="Invalid strategy_type"):
            DispatchStrategyConfig(strategy_type="invalid_strategy")

    def test_tou_without_peak_hours_raises(self) -> None:
        """Test TOU strategy without peak_hours raises error."""
        with pytest.raises(ConfigurationError, match="requires 'peak_hours'"):
            DispatchStrategyConfig(strategy_type="tou_optimized")

    def test_tou_with_invalid_hour_range_raises(self) -> None:
        """Test TOU strategy with invalid hour range raises error."""
        with pytest.raises(ConfigurationError, match="must be in range"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 25)],  # 25 is invalid
            )

    def test_tou_with_negative_hour_raises(self) -> None:
        """Test TOU strategy with negative hour raises error."""
        with pytest.raises(ConfigurationError, match="must be in range"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(-1, 10)],
            )

    def test_tou_with_start_after_end_raises(self) -> None:
        """Test TOU strategy with start_hour >= end_hour raises error."""
        with pytest.raises(ConfigurationError, match="start_hour must be less than"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(20, 16)],
            )

    def test_tou_with_equal_start_end_raises(self) -> None:
        """Test TOU strategy with equal start and end hours raises error."""
        with pytest.raises(ConfigurationError, match="start_hour must be less than"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 16)],
            )

    def test_peak_shaving_without_limit_raises(self) -> None:
        """Test peak-shaving strategy without import_limit_kw raises error."""
        with pytest.raises(ConfigurationError, match="requires 'import_limit_kw'"):
            DispatchStrategyConfig(strategy_type="peak_shaving")

    def test_peak_shaving_with_negative_limit_raises(self) -> None:
        """Test peak-shaving strategy with negative limit raises error."""
        with pytest.raises(ConfigurationError, match="must be positive"):
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=-5.0,
            )

    def test_peak_shaving_with_zero_limit_raises(self) -> None:
        """Test peak-shaving strategy with zero limit raises error."""
        with pytest.raises(ConfigurationError, match="must be positive"):
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=0.0,
            )


class TestGridChargeConfig:
    """Tests for GridChargeConfig class."""

    def test_default_target_soc_fraction(self) -> None:
        """GridChargeConfig() default target_soc_fraction is 0.9."""
        config = GridChargeConfig()
        assert config.target_soc_fraction == 0.9

    def test_custom_target_soc_fraction(self) -> None:
        """GridChargeConfig accepts custom target_soc_fraction."""
        config = GridChargeConfig(target_soc_fraction=0.8)
        assert config.target_soc_fraction == 0.8

    def test_boundary_value_one_accepted(self) -> None:
        """GridChargeConfig accepts target_soc_fraction == 1.0."""
        config = GridChargeConfig(target_soc_fraction=1.0)
        assert config.target_soc_fraction == 1.0

    def test_small_positive_value_accepted(self) -> None:
        """GridChargeConfig accepts small positive target_soc_fraction."""
        config = GridChargeConfig(target_soc_fraction=0.01)
        assert config.target_soc_fraction == 0.01

    def test_zero_raises(self) -> None:
        """target_soc_fraction == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=0.0)

    def test_negative_raises(self) -> None:
        """target_soc_fraction < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=-0.1)

    def test_above_one_raises(self) -> None:
        """target_soc_fraction > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=1.5)


class TestBatteryGridChargeParsing:
    """Tests for _parse_battery_config grid_charging support."""

    def test_parse_grid_charging_sets_target_soc(self) -> None:
        """_parse_battery_config parses nested grid_charging dict."""
        result = _parse_battery_config(
            {"capacity_kwh": 5.0, "grid_charging": {"target_soc_fraction": 0.8}}
        )
        assert result is not None
        assert result.grid_charging is not None
        assert result.grid_charging.target_soc_fraction == 0.8

    def test_parse_absent_grid_charging_is_none(self) -> None:
        """Absent grid_charging block -> grid_charging is None."""
        result = _parse_battery_config({"capacity_kwh": 5.0})
        assert result is not None
        assert result.grid_charging is None

    def test_parse_empty_grid_charging_uses_default(self) -> None:
        """Empty grid_charging dict -> default target_soc_fraction == 0.9."""
        result = _parse_battery_config({"capacity_kwh": 5.0, "grid_charging": {}})
        assert result is not None
        assert result.grid_charging is not None
        assert result.grid_charging.target_soc_fraction == 0.9

    def test_parse_out_of_range_raises(self) -> None:
        """Out-of-range target_soc_fraction propagates ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            _parse_battery_config(
                {"capacity_kwh": 5.0, "grid_charging": {"target_soc_fraction": 1.5}}
            )

    def test_parse_grid_charging_non_mapping_raises(self) -> None:
        """grid_charging supplied as a scalar raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="grid_charging must be a mapping"):
            _parse_battery_config({"capacity_kwh": 5.0, "grid_charging": 0.8})

    def test_yaml_round_trip_grid_charging(self) -> None:
        """YAML with battery.grid_charging round-trips into home.battery_config.grid_charging."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    grid_charging:
      target_soc_fraction: 0.8
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.battery_config is not None
            assert home.battery_config.grid_charging is not None
            assert home.battery_config.grid_charging.target_soc_fraction == 0.8
        finally:
            path.unlink()


class TestBatterySOCEfficiencyParsing:
    """Tests for _parse_battery_config SOC + efficiency key forwarding."""

    def test_parse_explicit_soc_and_eff_keys(self) -> None:
        """All five SOC/eff keys are forwarded to BatteryConfig."""
        result = _parse_battery_config(
            {
                "capacity_kwh": 5.0,
                "min_soc_fraction": 0.2,
                "max_soc_fraction": 0.85,
                "charge_efficiency": 0.96,
                "discharge_efficiency": 0.97,
            }
        )
        assert result is not None
        assert result.min_soc_fraction == 0.2
        assert result.max_soc_fraction == 0.85
        assert result.charge_efficiency == 0.96
        assert result.discharge_efficiency == 0.97

    def test_parse_efficiency_splits_via_sqrt(self) -> None:
        """efficiency key is forwarded and split as sqrt by BatteryConfig.__post_init__."""
        import math

        result = _parse_battery_config({"capacity_kwh": 5.0, "efficiency": 0.95})
        assert result is not None
        assert result.efficiency == 0.95
        assert result.charge_efficiency == pytest.approx(math.sqrt(0.95))
        assert result.discharge_efficiency == pytest.approx(math.sqrt(0.95))

    def test_absent_keys_use_defaults(self) -> None:
        """Absent SOC/eff keys yield the correct defaults."""
        result = _parse_battery_config({"capacity_kwh": 5.0})
        assert result is not None
        assert result.min_soc_fraction == 0.1
        assert result.max_soc_fraction == 0.9
        assert result.charge_efficiency == 0.975
        assert result.discharge_efficiency == 0.975
        assert result.efficiency is None

    def test_out_of_range_soc_raises_value_error(self) -> None:
        """Out-of-range SOC fractions propagate as ValueError."""
        with pytest.raises(ValueError, match="SOC"):
            _parse_battery_config(
                {"capacity_kwh": 5.0, "min_soc_fraction": 0.9, "max_soc_fraction": 0.5}
            )

    def test_out_of_range_efficiency_raises_value_error(self) -> None:
        """Out-of-range efficiency propagates as ValueError."""
        with pytest.raises(ValueError, match="[Cc]harge"):
            _parse_battery_config({"capacity_kwh": 5.0, "charge_efficiency": 0.0})

    def test_yaml_round_trip_efficiency(self) -> None:
        """YAML with battery.efficiency round-trips into home.battery_config.charge_efficiency."""
        import math

        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    efficiency: 0.95
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.battery_config is not None
            assert home.battery_config.efficiency == 0.95
            assert home.battery_config.charge_efficiency == pytest.approx(math.sqrt(0.95))
            assert home.battery_config.discharge_efficiency == pytest.approx(math.sqrt(0.95))
        finally:
            path.unlink()

    def test_yaml_round_trip_min_max_soc(self) -> None:
        """YAML with battery.min_soc_fraction/max_soc_fraction round-trips correctly."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    min_soc_fraction: 0.15
    max_soc_fraction: 0.85
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.battery_config is not None
            assert home.battery_config.min_soc_fraction == 0.15
            assert home.battery_config.max_soc_fraction == 0.85
        finally:
            path.unlink()


class TestBatterySOHParsing:
    """Tests for _parse_battery_config SOH/aging key forwarding."""

    def test_parse_explicit_soh_keys(self) -> None:
        """All five SOH keys are forwarded to BatteryConfig."""
        result = _parse_battery_config(
            {
                "capacity_kwh": 5.0,
                "system_age_years": 8.0,
                "calendar_fade_rate_per_year": 0.025,
                "cycle_fade_per_equivalent_full_cycle": 6e-5,
                "soh_floor": 0.6,
                "soh": 0.85,
            }
        )
        assert result is not None
        assert result.system_age_years == 8.0
        assert result.calendar_fade_rate_per_year == 0.025
        assert result.cycle_fade_per_equivalent_full_cycle == 6e-5
        assert result.soh_floor == 0.6
        assert result.soh == pytest.approx(0.85)

    def test_absent_soh_keys_use_defaults(self) -> None:
        """Absent SOH keys yield the correct BatteryConfig defaults."""
        result = _parse_battery_config({"capacity_kwh": 5.0})
        assert result is not None
        assert result.system_age_years == 0.0
        assert result.calendar_fade_rate_per_year == 0.02
        assert result.cycle_fade_per_equivalent_full_cycle == 5e-5
        assert result.soh_floor == 0.5
        assert result.soh is None

    def test_yaml_round_trip_system_age_years(self) -> None:
        """YAML with battery.system_age_years round-trips into battery_config.system_age_years."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    system_age_years: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.battery_config is not None
            assert home.battery_config.system_age_years == 10
        finally:
            path.unlink()

    def test_out_of_range_system_age_raises(self) -> None:
        """Negative system_age_years surfaces as ValueError."""
        with pytest.raises(ValueError, match="system_age_years"):
            _parse_battery_config({"capacity_kwh": 5.0, "system_age_years": -1.0})


class TestDispatchStrategyParsing:
    """Tests for _parse_dispatch_strategy_config function."""

    def test_parse_none(self) -> None:
        """Test parsing None returns None."""
        result = _parse_dispatch_strategy_config(None)
        assert result is None

    def test_parse_self_consumption(self) -> None:
        """Test parsing self-consumption strategy."""
        data = {"strategy_type": "self_consumption"}
        result = _parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "self_consumption"
        assert result.peak_hours is None
        assert result.import_limit_kw is None

    def test_parse_tou_optimized(self) -> None:
        """Test parsing TOU optimized strategy."""
        data = {
            "strategy_type": "tou_optimized",
            "peak_hours": [[16, 20], [7, 9]],
        }
        result = _parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "tou_optimized"
        assert result.peak_hours == [(16, 20), (7, 9)]

    def test_parse_peak_shaving(self) -> None:
        """Test parsing peak-shaving strategy."""
        data = {
            "strategy_type": "peak_shaving",
            "import_limit_kw": 5.0,
        }
        result = _parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "peak_shaving"
        assert result.import_limit_kw == 5.0

    def test_parse_missing_strategy_type_raises(self) -> None:
        """Test parsing without strategy_type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'strategy_type'"):
            _parse_dispatch_strategy_config({})

    def test_parse_empty_strategy_type_raises(self) -> None:
        """Test parsing with empty strategy_type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'strategy_type'"):
            _parse_dispatch_strategy_config({"strategy_type": ""})

    def test_parse_tou_with_null_peak_hours(self) -> None:
        """Test parsing TOU strategy with null peak_hours raises error."""
        data = {
            "strategy_type": "tou_optimized",
            "peak_hours": None,
        }
        with pytest.raises(ConfigurationError, match="requires 'peak_hours'"):
            _parse_dispatch_strategy_config(data)


class TestLoadConfigYaml:
    """Tests for YAML configuration loading."""

    def test_load_yaml_file(self) -> None:
        """Test loading a YAML configuration file."""
        yaml_content = """
name: Test Scenario
period:
  start_date: "2024-01-01"
  end_date: "2024-01-07"
home:
  pv:
    capacity_kw: 4.0
    azimuth: 180
    tilt: 35
  load:
    annual_consumption_kwh: 3400
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            config = load_config_yaml(path)
            assert config["name"] == "Test Scenario"
            assert config["home"]["pv"]["capacity_kw"] == 4.0
        finally:
            path.unlink()

    def test_load_nonexistent_yaml_raises(self) -> None:
        """Test loading nonexistent YAML file raises error."""
        with pytest.raises(ConfigurationError, match="not found"):
            load_config_yaml("/nonexistent/path.yaml")


class TestLoadConfigJson:
    """Tests for JSON configuration loading."""

    def test_load_json_file(self) -> None:
        """Test loading a JSON configuration file."""
        json_content = {
            "name": "Test Scenario",
            "period": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-07",
            },
            "home": {
                "pv": {"capacity_kw": 4.0},
                "load": {"annual_consumption_kwh": 3400},
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            config = load_config_json(path)
            assert config["name"] == "Test Scenario"
            assert config["home"]["pv"]["capacity_kw"] == 4.0
        finally:
            path.unlink()

    def test_load_invalid_json_raises(self) -> None:
        """Test loading invalid JSON raises error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{ invalid json }")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigurationError, match="Invalid JSON"):
                load_config_json(path)
        finally:
            path.unlink()


class TestLoadConfig:
    """Tests for auto-detecting configuration format."""

    def test_auto_detect_yaml(self) -> None:
        """Test auto-detecting YAML format."""
        yaml_content = "name: Test\nvalue: 123"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            config = load_config(path)
            assert config["name"] == "Test"
        finally:
            path.unlink()

    def test_auto_detect_yml(self) -> None:
        """Test auto-detecting .yml format."""
        yaml_content = "name: Test\nvalue: 123"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            config = load_config(path)
            assert config["name"] == "Test"
        finally:
            path.unlink()

    def test_auto_detect_json(self) -> None:
        """Test auto-detecting JSON format."""
        json_content = {"name": "Test", "value": 123}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            config = load_config(path)
            assert config["name"] == "Test"
        finally:
            path.unlink()

    def test_unknown_format_raises(self) -> None:
        """Test unknown format raises error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("some content")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigurationError, match="Unknown.*format"):
                load_config(path)
        finally:
            path.unlink()


class TestLoadScenarios:
    """Tests for loading scenarios from configuration files."""

    def test_load_single_scenario(self) -> None:
        """Test loading a single scenario."""
        json_content = {
            "name": "Single Home Test",
            "period": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-07",
            },
            "home": {
                "pv": {"capacity_kw": 4.0},
                "load": {"annual_consumption_kwh": 3400},
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            assert scenarios[0].name == "Single Home Test"
            assert scenarios[0].home is not None
        finally:
            path.unlink()

    def test_load_multiple_scenarios(self) -> None:
        """Test loading multiple scenarios."""
        json_content = {
            "scenarios": [
                {
                    "name": "Scenario 1",
                    "period": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
                    "home": {"pv": {"capacity_kw": 3.0}, "load": {}},
                },
                {
                    "name": "Scenario 2",
                    "period": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
                    "home": {"pv": {"capacity_kw": 5.0}, "load": {}},
                },
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 2
            assert scenarios[0].name == "Scenario 1"
            assert scenarios[1].name == "Scenario 2"
        finally:
            path.unlink()


class TestLoadHomeConfig:
    """Tests for loading home configuration."""

    def test_load_home_config(self) -> None:
        """Test loading home configuration from file."""
        json_content = {
            "home": {
                "pv": {"capacity_kw": 5.0, "tilt": 30},
                "battery": {"capacity_kwh": 10.0},
                "load": {"annual_consumption_kwh": 4000},
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.pv_config.capacity_kw == 5.0
            assert home.pv_config.tilt == 30
            assert home.battery_config is not None
            assert home.battery_config.capacity_kwh == 10.0
            assert home.load_config.annual_consumption_kwh == 4000
        finally:
            path.unlink()

    def test_load_home_without_battery(self) -> None:
        """Test loading home without battery."""
        json_content = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            home = load_home_config(path)
            assert home.pv_config.capacity_kw == 4.0
            assert home.battery_config is None
        finally:
            path.unlink()


class TestLoadFleetConfig:
    """Tests for loading fleet configuration."""

    def test_load_fleet_config(self) -> None:
        """Test loading fleet configuration from file."""
        json_content = {
            "name": "Test Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
                {"pv": {"capacity_kw": 5.0}, "load": {}},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "Test Fleet"
            assert len(fleet.homes) == 3
        finally:
            path.unlink()

    def test_load_fleet_requires_homes(self) -> None:
        """Test that fleet config requires homes list or fleet_distribution."""
        json_content = {"name": "Empty Fleet"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(
                ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
            ):
                load_fleet_config(path)
        finally:
            path.unlink()


class TestBristolPhase1Scenario:
    """Tests for Bristol Phase 1 scenario (loaded from YAML)."""

    @pytest.fixture
    def bristol_fleet(self) -> "FleetConfig":
        """Load Bristol Phase 1 from YAML."""
        from solar_challenge.fleet import FleetConfig
        yaml_path = Path(__file__).parent.parent.parent / "scenarios" / "bristol-phase1.yaml"
        return load_fleet_config(yaml_path)

    def test_load_bristol_phase1(self, bristol_fleet: "FleetConfig") -> None:
        """Test loading Bristol Phase 1 from YAML."""
        assert bristol_fleet.name == "Bristol Phase 1"
        assert len(bristol_fleet.homes) == 100

    def test_pv_distribution(self, bristol_fleet: "FleetConfig") -> None:
        """Test PV capacity distribution."""
        pv_sizes = [h.pv_config.capacity_kw for h in bristol_fleet.homes]

        # Check all sizes are in expected range
        assert all(3.0 <= s <= 6.0 for s in pv_sizes)

        # Check exact distribution (shuffled_pool guarantees counts)
        count_3kw = sum(1 for s in pv_sizes if s == 3.0)
        count_4kw = sum(1 for s in pv_sizes if s == 4.0)
        count_5kw = sum(1 for s in pv_sizes if s == 5.0)
        count_6kw = sum(1 for s in pv_sizes if s == 6.0)

        assert count_3kw == 20
        assert count_4kw == 40
        assert count_5kw == 30
        assert count_6kw == 10

    def test_battery_distribution(self, bristol_fleet: "FleetConfig") -> None:
        """Test battery distribution."""
        no_battery = sum(1 for h in bristol_fleet.homes if h.battery_config is None)
        battery_5kwh = sum(
            1 for h in bristol_fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 5.0
        )
        battery_10kwh = sum(
            1 for h in bristol_fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 10.0
        )

        assert no_battery == 40
        assert battery_5kwh == 40
        assert battery_10kwh == 20

    def test_consumption_distribution(self, bristol_fleet: "FleetConfig") -> None:
        """Test consumption distribution."""
        consumptions = [
            h.load_config.annual_consumption_kwh
            for h in bristol_fleet.homes
            if h.load_config.annual_consumption_kwh is not None
        ]

        # All should be in valid range
        assert all(2000 <= c <= 6000 for c in consumptions)

        # Mean should be around 3400
        mean_consumption = sum(consumptions) / len(consumptions)
        assert 3000 <= mean_consumption <= 3800

    def test_reproducible(self) -> None:
        """Test that loading from YAML is reproducible (seeded random)."""
        yaml_path = Path(__file__).parent.parent.parent / "scenarios" / "bristol-phase1.yaml"
        fleet1 = load_fleet_config(yaml_path)
        fleet2 = load_fleet_config(yaml_path)

        for h1, h2 in zip(fleet1.homes, fleet2.homes, strict=True):
            assert h1.pv_config.capacity_kw == h2.pv_config.capacity_kw
            assert h1.battery_config == h2.battery_config
            assert h1.load_config.annual_consumption_kwh == h2.load_config.annual_consumption_kwh


class TestDistributionDataclasses:
    """Tests for distribution dataclasses."""

    def test_weighted_discrete_basic(self) -> None:
        """Test basic WeightedDiscreteDistribution."""
        dist = WeightedDiscreteDistribution(
            values=(3.0, 4.0, 5.0),
            weights=(20.0, 50.0, 30.0),
        )
        assert dist.values == (3.0, 4.0, 5.0)
        assert dist.weights == (20.0, 50.0, 30.0)

    def test_weighted_discrete_with_none(self) -> None:
        """Test WeightedDiscreteDistribution with None values."""
        dist = WeightedDiscreteDistribution(
            values=(None, 5.0, 10.0),
            weights=(40.0, 40.0, 20.0),
        )
        assert dist.values == (None, 5.0, 10.0)

    def test_weighted_discrete_mismatched_length_raises(self) -> None:
        """Test WeightedDiscreteDistribution with mismatched lengths raises."""
        with pytest.raises(ConfigurationError, match="same length"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(1.0,))

    def test_weighted_discrete_negative_weight_raises(self) -> None:
        """Test WeightedDiscreteDistribution with negative weight raises."""
        with pytest.raises(ConfigurationError, match="negative"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(1.0, -1.0))

    def test_weighted_discrete_all_zero_weights_raises(self) -> None:
        """Test WeightedDiscreteDistribution with all zero weights raises."""
        with pytest.raises(ConfigurationError, match="all be zero"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(0.0, 0.0))

    def test_normal_distribution_basic(self) -> None:
        """Test basic NormalDistribution."""
        dist = NormalDistribution(mean=3400.0, std=800.0)
        assert dist.mean == 3400.0
        assert dist.std == 800.0
        assert dist.min is None
        assert dist.max is None

    def test_normal_distribution_with_bounds(self) -> None:
        """Test NormalDistribution with bounds."""
        dist = NormalDistribution(mean=3400.0, std=800.0, min=2000.0, max=6000.0)
        assert dist.min == 2000.0
        assert dist.max == 6000.0

    def test_normal_distribution_negative_std_raises(self) -> None:
        """Test NormalDistribution with negative std raises."""
        with pytest.raises(ConfigurationError, match="negative"):
            NormalDistribution(mean=100.0, std=-1.0)

    def test_normal_distribution_invalid_bounds_raises(self) -> None:
        """Test NormalDistribution with min > max raises."""
        with pytest.raises(ConfigurationError, match="greater than max"):
            NormalDistribution(mean=100.0, std=10.0, min=200.0, max=100.0)

    def test_uniform_distribution_basic(self) -> None:
        """Test basic UniformDistribution."""
        dist = UniformDistribution(min=0.0, max=10.0)
        assert dist.min == 0.0
        assert dist.max == 10.0

    def test_uniform_distribution_invalid_bounds_raises(self) -> None:
        """Test UniformDistribution with min > max raises."""
        with pytest.raises(ConfigurationError, match="greater than max"):
            UniformDistribution(min=10.0, max=5.0)

    def test_shuffled_pool_distribution_basic(self) -> None:
        """Test basic ShuffledPoolDistribution."""
        from solar_challenge.config import ShuffledPoolDistribution
        dist = ShuffledPoolDistribution(
            values=(3.0, 4.0, 5.0, 6.0),
            counts=(20, 40, 30, 10),
        )
        assert dist.values == (3.0, 4.0, 5.0, 6.0)
        assert dist.counts == (20, 40, 30, 10)

    def test_shuffled_pool_distribution_with_none(self) -> None:
        """Test ShuffledPoolDistribution with None values."""
        from solar_challenge.config import ShuffledPoolDistribution
        dist = ShuffledPoolDistribution(
            values=(None, 5.0, 10.0),
            counts=(40, 40, 20),
        )
        assert dist.values == (None, 5.0, 10.0)

    def test_shuffled_pool_distribution_create_pool(self) -> None:
        """Test ShuffledPoolDistribution creates correct pool."""
        from solar_challenge.config import ShuffledPoolDistribution
        dist = ShuffledPoolDistribution(
            values=(1.0, 2.0),
            counts=(3, 2),
        )
        pool = dist.create_pool()
        assert len(pool) == 5
        assert pool.count(1.0) == 3
        assert pool.count(2.0) == 2

    def test_shuffled_pool_distribution_mismatched_length_raises(self) -> None:
        """Test ShuffledPoolDistribution with mismatched lengths raises."""
        from solar_challenge.config import ShuffledPoolDistribution
        with pytest.raises(ConfigurationError, match="same length"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(1,))

    def test_shuffled_pool_distribution_negative_count_raises(self) -> None:
        """Test ShuffledPoolDistribution with negative count raises."""
        from solar_challenge.config import ShuffledPoolDistribution
        with pytest.raises(ConfigurationError, match="negative"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(1, -1))

    def test_shuffled_pool_distribution_all_zero_counts_raises(self) -> None:
        """Test ShuffledPoolDistribution with all zero counts raises."""
        from solar_challenge.config import ShuffledPoolDistribution
        with pytest.raises(ConfigurationError, match="all be zero"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(0, 0))


class TestDistributionParsing:
    """Tests for _parse_distribution_spec function."""

    def test_parse_none(self) -> None:
        """Test parsing None value."""
        result = _parse_distribution_spec(None, "test")
        assert result is None

    def test_parse_scalar_float(self) -> None:
        """Test parsing scalar float."""
        result = _parse_distribution_spec(4.0, "test")
        assert result == 4.0

    def test_parse_scalar_int(self) -> None:
        """Test parsing scalar int converts to float."""
        result = _parse_distribution_spec(5, "test")
        assert result == 5.0
        assert isinstance(result, float)

    def test_parse_weighted_discrete(self) -> None:
        """Test parsing weighted_discrete distribution."""
        data = {
            "type": "weighted_discrete",
            "values": [3.0, 4.0, 5.0],
            "weights": [20, 50, 30],
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, WeightedDiscreteDistribution)
        assert result.values == (3.0, 4.0, 5.0)
        assert result.weights == (20.0, 50.0, 30.0)

    def test_parse_weighted_discrete_with_null(self) -> None:
        """Test parsing weighted_discrete with null values."""
        data = {
            "type": "weighted_discrete",
            "values": [None, 5.0, 10.0],
            "weights": [40, 40, 20],
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, WeightedDiscreteDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_shuffled_pool(self) -> None:
        """Test parsing shuffled_pool distribution."""
        from solar_challenge.config import ShuffledPoolDistribution
        data = {
            "type": "shuffled_pool",
            "values": [3.0, 4.0, 5.0, 6.0],
            "counts": [20, 40, 30, 10],
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (3.0, 4.0, 5.0, 6.0)
        assert result.counts == (20, 40, 30, 10)

    def test_parse_shuffled_pool_with_null(self) -> None:
        """Test parsing shuffled_pool with null values."""
        from solar_challenge.config import ShuffledPoolDistribution
        data = {
            "type": "shuffled_pool",
            "values": [None, 5.0, 10.0],
            "counts": [40, 40, 20],
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_shuffled_pool_missing_counts_raises(self) -> None:
        """Test parsing shuffled_pool without counts raises."""
        with pytest.raises(ConfigurationError, match="requires 'values' and 'counts'"):
            _parse_distribution_spec(
                {"type": "shuffled_pool", "values": [1, 2, 3]}, "test"
            )

    def test_parse_normal(self) -> None:
        """Test parsing normal distribution."""
        data = {
            "type": "normal",
            "mean": 3400,
            "std": 800,
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, NormalDistribution)
        assert result.mean == 3400.0
        assert result.std == 800.0

    def test_parse_normal_with_bounds(self) -> None:
        """Test parsing normal distribution with bounds."""
        data = {
            "type": "normal",
            "mean": 3400,
            "std": 800,
            "min": 2000,
            "max": 6000,
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, NormalDistribution)
        assert result.min == 2000.0
        assert result.max == 6000.0

    def test_parse_uniform(self) -> None:
        """Test parsing uniform distribution."""
        data = {
            "type": "uniform",
            "min": 3.0,
            "max": 6.0,
        }
        result = _parse_distribution_spec(data, "test")
        assert isinstance(result, UniformDistribution)
        assert result.min == 3.0
        assert result.max == 6.0

    def test_parse_fixed(self) -> None:
        """Test parsing fixed distribution (explicit scalar)."""
        data = {
            "type": "fixed",
            "value": 4.5,
        }
        result = _parse_distribution_spec(data, "test")
        assert result == 4.5

    def test_parse_missing_type_raises(self) -> None:
        """Test parsing dict without type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'type'"):
            _parse_distribution_spec({"values": [1, 2, 3]}, "test")

    def test_parse_unknown_type_raises(self) -> None:
        """Test parsing unknown type raises error."""
        with pytest.raises(ConfigurationError, match="Unknown distribution type"):
            _parse_distribution_spec({"type": "unknown"}, "test")

    def test_parse_weighted_discrete_missing_values_raises(self) -> None:
        """Test parsing weighted_discrete without values raises."""
        with pytest.raises(ConfigurationError, match="requires 'values' and 'weights'"):
            _parse_distribution_spec(
                {"type": "weighted_discrete", "weights": [1, 2]}, "test"
            )

    def test_parse_normal_missing_std_raises(self) -> None:
        """Test parsing normal without std raises."""
        with pytest.raises(ConfigurationError, match="requires 'mean' and 'std'"):
            _parse_distribution_spec({"type": "normal", "mean": 100}, "test")

    def test_parse_uniform_missing_max_raises(self) -> None:
        """Test parsing uniform without max raises."""
        with pytest.raises(ConfigurationError, match="requires 'min' and 'max'"):
            _parse_distribution_spec({"type": "uniform", "min": 0}, "test")


class TestDistributionSampling:
    """Tests for _sample_from_distribution function."""

    def test_sample_none_returns_none(self) -> None:
        """Test sampling None returns None."""
        rng = random.Random(42)
        assert _sample_from_distribution(None, rng) is None

    def test_sample_scalar_returns_float(self) -> None:
        """Test sampling scalar returns float."""
        rng = random.Random(42)
        assert _sample_from_distribution(4.0, rng) == 4.0
        assert _sample_from_distribution(5, rng) == 5.0

    def test_sample_weighted_discrete(self) -> None:
        """Test sampling from weighted discrete distribution."""
        rng = random.Random(42)
        dist = WeightedDiscreteDistribution(
            values=(3.0, 4.0, 5.0),
            weights=(1.0, 1.0, 1.0),
        )
        samples = [_sample_from_distribution(dist, rng) for _ in range(100)]
        assert all(s in (3.0, 4.0, 5.0) for s in samples)

    def test_sample_weighted_discrete_can_return_none(self) -> None:
        """Test weighted discrete can return None."""
        rng = random.Random(42)
        dist = WeightedDiscreteDistribution(
            values=(None, 5.0),
            weights=(50.0, 50.0),
        )
        samples = [_sample_from_distribution(dist, rng) for _ in range(100)]
        assert None in samples
        assert 5.0 in samples

    def test_sample_normal(self) -> None:
        """Test sampling from normal distribution."""
        rng = random.Random(42)
        dist = NormalDistribution(mean=100.0, std=10.0)
        samples = [_sample_from_distribution(dist, rng) for _ in range(1000)]
        mean = sum(s for s in samples if s is not None) / len(samples)
        assert 95.0 <= mean <= 105.0  # Should be close to 100

    def test_sample_normal_respects_bounds(self) -> None:
        """Test normal distribution respects min/max bounds."""
        rng = random.Random(42)
        dist = NormalDistribution(mean=100.0, std=50.0, min=80.0, max=120.0)
        samples = [_sample_from_distribution(dist, rng) for _ in range(100)]
        assert all(s is not None and 80.0 <= s <= 120.0 for s in samples)

    def test_sample_uniform(self) -> None:
        """Test sampling from uniform distribution."""
        rng = random.Random(42)
        dist = UniformDistribution(min=0.0, max=10.0)
        samples = [_sample_from_distribution(dist, rng) for _ in range(100)]
        assert all(s is not None and 0.0 <= s <= 10.0 for s in samples)


class TestFleetDistributionConfig:
    """Tests for FleetDistributionConfig parsing."""

    def test_parse_basic_fleet_distribution(self) -> None:
        """Test parsing basic fleet distribution config."""
        data = {
            "n_homes": 10,
            "pv": {
                "capacity_kw": 4.0,
            },
            "load": {},
        }
        config = _parse_fleet_distribution_config(data)
        assert config.n_homes == 10
        assert config.pv.capacity_kw == 4.0
        assert config.battery is None

    def test_parse_full_fleet_distribution(self) -> None:
        """Test parsing full fleet distribution config."""
        data = {
            "n_homes": 100,
            "seed": 42,
            "pv": {
                "capacity_kw": {
                    "type": "weighted_discrete",
                    "values": [3.0, 4.0, 5.0],
                    "weights": [30, 50, 20],
                },
                "azimuth": 180,
                "tilt": 35,
            },
            "battery": {
                "capacity_kwh": {
                    "type": "weighted_discrete",
                    "values": [None, 5.0, 10.0],
                    "weights": [40, 40, 20],
                },
            },
            "load": {
                "annual_consumption_kwh": {
                    "type": "normal",
                    "mean": 3400,
                    "std": 800,
                    "min": 2000,
                    "max": 6000,
                },
            },
        }
        config = _parse_fleet_distribution_config(data)
        assert config.n_homes == 100
        assert config.seed == 42
        assert isinstance(config.pv.capacity_kw, WeightedDiscreteDistribution)
        assert config.pv.azimuth == 180.0
        assert config.battery is not None
        assert isinstance(config.battery.capacity_kwh, WeightedDiscreteDistribution)
        assert isinstance(config.load.annual_consumption_kwh, NormalDistribution)

    def test_parse_missing_n_homes_raises(self) -> None:
        """Test parsing without n_homes raises."""
        with pytest.raises(ConfigurationError, match="requires 'n_homes'"):
            _parse_fleet_distribution_config({"pv": {"capacity_kw": 4.0}})

    def test_parse_missing_pv_raises(self) -> None:
        """Test parsing without pv raises."""
        with pytest.raises(ConfigurationError, match="requires 'pv'"):
            _parse_fleet_distribution_config({"n_homes": 10})

    def test_fleet_distribution_config_validation(self) -> None:
        """Test FleetDistributionConfig validation."""
        with pytest.raises(ConfigurationError, match="at least 1"):
            FleetDistributionConfig(
                n_homes=0,
                pv=PVDistributionConfig(capacity_kw=4.0),
                load=LoadDistributionConfig(),
            )


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


class TestLoadFleetConfigWithDistribution:
    """Tests for load_fleet_config with fleet_distribution."""

    def test_load_fleet_distribution_yaml(self) -> None:
        """Test loading fleet config with distribution from YAML."""
        yaml_content = """
name: Test Distribution Fleet
fleet_distribution:
  n_homes: 10
  seed: 42
  pv:
    capacity_kw:
      type: weighted_discrete
      values: [3.0, 4.0, 5.0]
      weights: [30, 50, 20]
  battery:
    capacity_kwh:
      type: weighted_discrete
      values: [null, 5.0]
      weights: [50, 50]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "Test Distribution Fleet"
            assert len(fleet.homes) == 10

            # Check PV sizes are from the distribution
            pv_sizes = {h.pv_config.capacity_kw for h in fleet.homes}
            assert pv_sizes.issubset({3.0, 4.0, 5.0})

            # Check some homes have batteries and some don't
            with_battery = [h for h in fleet.homes if h.battery_config is not None]
            without_battery = [h for h in fleet.homes if h.battery_config is None]
            assert len(with_battery) + len(without_battery) == 10
        finally:
            path.unlink()

    def test_load_fleet_distribution_json(self) -> None:
        """Test loading fleet config with distribution from JSON."""
        json_content = {
            "name": "JSON Distribution Fleet",
            "fleet_distribution": {
                "n_homes": 5,
                "seed": 123,
                "pv": {
                    "capacity_kw": {
                        "type": "uniform",
                        "min": 3.0,
                        "max": 6.0,
                    },
                },
                "load": {
                    "annual_consumption_kwh": 3400,
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
            assert fleet.name == "JSON Distribution Fleet"
            assert len(fleet.homes) == 5

            # Check PV sizes are in uniform range
            for home in fleet.homes:
                assert 3.0 <= home.pv_config.capacity_kw <= 6.0
                assert home.load_config.annual_consumption_kwh == 3400
        finally:
            path.unlink()

    def test_load_fleet_backward_compatibility(self) -> None:
        """Test that explicit homes list still works."""
        json_content = {
            "name": "Explicit Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "Explicit Fleet"
            assert len(fleet.homes) == 2
            assert fleet.homes[0].pv_config.capacity_kw == 3.0
            assert fleet.homes[1].pv_config.capacity_kw == 4.0
        finally:
            path.unlink()

    def test_load_fleet_missing_homes_and_distribution_raises(self) -> None:
        """Test that missing both homes and fleet_distribution raises error."""
        json_content = {"name": "Empty Fleet"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(
                ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
            ):
                load_fleet_config(path)
        finally:
            path.unlink()

    def test_load_fleet_empty_homes_list_raises(self) -> None:
        """Test that empty homes list raises error."""
        json_content = {"name": "Empty Fleet", "homes": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigurationError, match="cannot be empty"):
                load_fleet_config(path)
        finally:
            path.unlink()


class TestBristolPhase1DistributionEquivalence:
    """Tests that distribution config can reproduce Bristol Phase 1 scenario."""

    def test_distribution_config_matches_programmatic(self) -> None:
        """Test that YAML distribution config produces similar results to programmatic."""
        # Create distribution config that mirrors Bristol Phase 1
        yaml_content = """
name: Bristol Phase 1 (Distribution)
fleet_distribution:
  n_homes: 100
  seed: 42
  pv:
    capacity_kw:
      type: weighted_discrete
      values: [3.0, 4.0, 5.0, 6.0]
      weights: [20, 40, 30, 10]
  battery:
    capacity_kwh:
      type: weighted_discrete
      values: [null, 5.0, 10.0]
      weights: [40, 40, 20]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert len(fleet.homes) == 100

            # Check PV distribution
            pv_sizes = [h.pv_config.capacity_kw for h in fleet.homes]
            assert all(3.0 <= s <= 6.0 for s in pv_sizes)

            # Check battery distribution
            no_battery = sum(1 for h in fleet.homes if h.battery_config is None)
            battery_5 = sum(
                1
                for h in fleet.homes
                if h.battery_config is not None and h.battery_config.capacity_kwh == 5.0
            )
            battery_10 = sum(
                1
                for h in fleet.homes
                if h.battery_config is not None and h.battery_config.capacity_kwh == 10.0
            )
            # Should be roughly 40/40/20 distribution
            assert no_battery + battery_5 + battery_10 == 100

            # Check consumption bounds
            consumptions = [
                h.load_config.annual_consumption_kwh
                for h in fleet.homes
                if h.load_config.annual_consumption_kwh is not None
            ]
            assert all(2000 <= c <= 6000 for c in consumptions)
        finally:
            path.unlink()


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


# ---------------------------------------------------------------------------
# Community config parsing
# ---------------------------------------------------------------------------


class TestParseCommunityConfig:
    """Tests for _parse_community_config."""

    def test_none_returns_none(self) -> None:
        """_parse_community_config(None) returns None (mirrors _parse_battery_config)."""
        assert _parse_community_config(None) is None

    def test_minimal_p2p(self) -> None:
        """A minimal dict with sharing_mode='p2p' returns a valid CommunityConfig."""
        cfg = _parse_community_config({"sharing_mode": "p2p"})
        assert isinstance(cfg, CommunityConfig)
        assert cfg.sharing_mode == "p2p"
        assert cfg.community_battery is None
        assert cfg.billing is None

    # ------------------------------------------------------------------
    # community_battery mode + invalid combinations (step-3)
    # ------------------------------------------------------------------

    def test_community_battery_mode_parses_battery(self) -> None:
        """community_battery mode with battery block returns BatteryConfig."""
        cfg = _parse_community_config(
            {
                "sharing_mode": "community_battery",
                "community_battery": {
                    "capacity_kwh": 50.0,
                    "max_charge_kw": 20.0,
                    "max_discharge_kw": 20.0,
                },
            }
        )
        assert isinstance(cfg, CommunityConfig)
        assert cfg.sharing_mode == "community_battery"
        assert cfg.community_battery is not None
        assert cfg.community_battery.capacity_kwh == 50.0

    def test_community_battery_mode_without_battery_raises(self) -> None:
        """community_battery mode without a community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_community_config({"sharing_mode": "community_battery"})

    def test_p2p_with_battery_raises(self) -> None:
        """p2p + community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "community_battery": {"capacity_kwh": 50.0},
                }
            )

    def test_bogus_mode_raises(self) -> None:
        """An unrecognised sharing_mode raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_community_config({"sharing_mode": "bogus"})

    # ------------------------------------------------------------------
    # billing block: tariff + direct SEG scalar (step-5)
    # ------------------------------------------------------------------

    def test_billing_with_tariff_and_direct_seg(self) -> None:
        """billing block with tariff + direct seg_rate_pence_per_kwh is parsed."""
        cfg = _parse_community_config(
            {
                "sharing_mode": "p2p",
                "billing": {
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
                    "seg_rate_pence_per_kwh": 4.1,
                },
            }
        )
        assert isinstance(cfg, CommunityConfig)
        assert cfg.billing is not None
        assert isinstance(cfg.billing, CommunityBillingConfig)
        assert cfg.billing.tariff is not None
        assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(4.1)

    def test_no_billing_key_gives_none(self) -> None:
        """Absence of the billing key leaves billing=None."""
        cfg = _parse_community_config({"sharing_mode": "p2p"})
        assert cfg is not None
        assert cfg.billing is None

    # ------------------------------------------------------------------
    # billing: nested SEG forms (step-7)
    # ------------------------------------------------------------------

    def test_billing_seg_preset(self) -> None:
        """billing.seg.preset resolves to the SEG_PRESETS rate."""
        cfg = _parse_community_config(
            {
                "sharing_mode": "p2p",
                "billing": {"seg": {"preset": "Octopus"}},
            }
        )
        assert cfg is not None
        assert cfg.billing is not None
        assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(4.1)

    def test_billing_seg_rate(self) -> None:
        """billing.seg.rate_pence_per_kwh stores the explicit float."""
        cfg = _parse_community_config(
            {
                "sharing_mode": "p2p",
                "billing": {"seg": {"rate_pence_per_kwh": 5.5}},
            }
        )
        assert cfg is not None
        assert cfg.billing is not None
        assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(5.5)

    def test_billing_seg_unknown_preset_raises(self) -> None:
        """billing.seg with unknown preset name raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Unknown SEG preset"):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "billing": {"seg": {"preset": "Nonexistent"}},
                }
            )

    def test_billing_both_scalar_and_seg_block_raises(self) -> None:
        """Supplying both seg_rate_pence_per_kwh and seg block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "billing": {
                        "seg_rate_pence_per_kwh": 4.1,
                        "seg": {"preset": "Octopus"},
                    },
                }
            )

    # ------------------------------------------------------------------
    # Amendment: additional robustness tests (reviewer pass)
    # ------------------------------------------------------------------

    def test_billing_seg_non_dict_raises(self) -> None:
        """A bare scalar for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "billing": {"seg": 4.1},
                }
            )

    def test_billing_seg_string_raises(self) -> None:
        """A bare string for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "billing": {"seg": "Octopus"},
                }
            )

    def test_billing_seg_block_both_preset_and_rate_raises(self) -> None:
        """A seg block with both preset and rate_pence_per_kwh raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_community_config(
                {
                    "sharing_mode": "p2p",
                    "billing": {
                        "seg": {"preset": "Octopus", "rate_pence_per_kwh": 5.5},
                    },
                }
            )

    def test_empty_billing_block_returns_none_billing(self) -> None:
        """An empty billing: {} block normalises to billing=None (same as absent key)."""
        cfg = _parse_community_config({"sharing_mode": "p2p", "billing": {}})
        assert cfg is not None
        assert cfg.billing is None


class TestLoadCommunityConfig:
    """Tests for load_community_config."""

    def test_load_yaml_with_community_block(self) -> None:
        """YAML file with community: block returns a populated CommunityConfig."""
        yaml_content = """\
community:
  sharing_mode: community_battery
  community_battery:
    capacity_kwh: 50.0
    max_charge_kw: 20.0
    max_discharge_kw: 20.0
  billing:
    tariff:
      type: flat_rate
      rate_per_kwh: 0.30
    seg_rate_pence_per_kwh: 4.1
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            cfg = load_community_config(path)
            assert isinstance(cfg, CommunityConfig)
            assert cfg.sharing_mode == "community_battery"
            assert cfg.community_battery is not None
            assert cfg.community_battery.capacity_kwh == pytest.approx(50.0)
            assert cfg.billing is not None
            assert cfg.billing.tariff is not None
            assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(4.1)
        finally:
            path.unlink()

    def test_load_yaml_without_community_block_returns_none(self) -> None:
        """YAML file with no community: key returns None."""
        yaml_content = """\
name: Bristol Phase 1
period:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            result = load_community_config(path)
            assert result is None
        finally:
            path.unlink()

    def test_load_non_dict_yaml_returns_none(self) -> None:
        """A YAML file whose top-level value is a list (not a dict) returns None
        instead of raising AttributeError on .get('community').
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("- item1\n- item2\n")  # top-level list, no community key
            f.flush()
            path = Path(f.name)

        try:
            result = load_community_config(path)
            assert result is None
        finally:
            path.unlink()


class TestCommunityConfigFrozenPicklable:
    """Contract guard: full CommunityConfig object graph is frozen and picklable (step-11)."""

    def _full_community_config(self) -> "CommunityConfig":
        """Return a CommunityConfig that exercises every nested dataclass."""
        cfg = _parse_community_config(
            {
                "sharing_mode": "community_battery",
                "community_battery": {
                    "capacity_kwh": 50.0,
                    "max_charge_kw": 20.0,
                    "max_discharge_kw": 20.0,
                },
                "billing": {
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
                    "seg_rate_pence_per_kwh": 4.1,
                },
            }
        )
        assert cfg is not None
        return cfg

    def test_picklable_round_trip(self) -> None:
        """CommunityConfig (with nested BatteryConfig + CommunityBillingConfig + TariffConfig)
        round-trips through pickle with structural equality."""
        import pickle

        cfg = self._full_community_config()
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg

    def test_frozen_top_level(self) -> None:
        """Assigning a new attribute on CommunityConfig raises FrozenInstanceError."""
        import dataclasses

        cfg = self._full_community_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.sharing_mode = "p2p"  # type: ignore[misc]

    def test_frozen_nested_battery(self) -> None:
        """BatteryConfig inside CommunityConfig is also frozen."""
        import dataclasses

        cfg = self._full_community_config()
        assert cfg.community_battery is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.community_battery.capacity_kwh = 99.0  # type: ignore[misc]

    def test_frozen_nested_billing(self) -> None:
        """CommunityBillingConfig inside CommunityConfig is also frozen."""
        import dataclasses

        cfg = self._full_community_config()
        assert cfg.billing is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.billing.seg_rate_pence_per_kwh = 0.0  # type: ignore[misc]


class TestParseHomeConfigHeatPumpEV:
    """Tests that _parse_home_config honours heat_pump and ev blocks (step-1/step-2)."""

    def test_parse_home_config_with_heat_pump_and_ev(self) -> None:
        """_parse_home_config populates heat_pump_config and ev_config when blocks present."""
        data: dict = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
            "heat_pump": {
                "heat_pump_type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
            "ev": {
                "charger_type": "7kW",
                "arrival_hour": 18,
                "departure_hour": 7,
                "required_charge_kwh": 35,
            },
        }
        result = _parse_home_config(data, Location.bristol())

        assert result.heat_pump_config is not None, "heat_pump_config should not be None"
        assert isinstance(result.heat_pump_config, HeatPumpConfig)
        assert result.heat_pump_config.heat_pump_type == "ASHP"
        assert result.heat_pump_config.thermal_capacity_kw == 8.0

        assert result.ev_config is not None, "ev_config should not be None"
        assert isinstance(result.ev_config, EVConfig)
        assert result.ev_config.charger_type == "7kW"
        assert result.ev_config.arrival_hour == 18

    def test_parse_home_config_without_heat_pump_ev_yields_none(self) -> None:
        """_parse_home_config backward-compat: absent heat_pump/ev keys yield None."""
        data: dict = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        }
        result = _parse_home_config(data, Location.bristol())

        assert result.heat_pump_config is None, "heat_pump_config should be None when key absent"
        assert result.ev_config is None, "ev_config should be None when key absent"


class TestParseHeatPumpEvConfigErrors:
    """Tests that _parse_heat_pump_config / _parse_ev_config raise ConfigurationError
    for malformed blocks (amendment: suggestion 1 + 2)."""

    def test_heat_pump_missing_heat_pump_type_raises(self) -> None:
        """heat_pump block without heat_pump_type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="heat_pump_type"):
            _parse_heat_pump_config({"thermal_capacity_kw": 8.0})

    def test_heat_pump_missing_thermal_capacity_raises(self) -> None:
        """heat_pump block without thermal_capacity_kw raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="thermal_capacity_kw"):
            _parse_heat_pump_config({"heat_pump_type": "ASHP"})

    def test_ev_missing_charger_type_raises(self) -> None:
        """ev block without charger_type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="charger_type"):
            _parse_ev_config({"arrival_hour": 18})

    def test_ev_missing_arrival_hour_raises(self) -> None:
        """ev block without arrival_hour raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="arrival_hour"):
            _parse_ev_config({"charger_type": "7kW"})

    def test_heat_pump_missing_type_via_parse_home_config(self) -> None:
        """_parse_home_config raises ConfigurationError for partial heat_pump block."""
        data: dict = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
            "heat_pump": {"thermal_capacity_kw": 8.0},  # missing heat_pump_type
        }
        with pytest.raises(ConfigurationError, match="heat_pump_type"):
            _parse_home_config(data, Location.bristol())


class TestParsePVConfig:
    """Tests that _parse_pv_config threads degradation keys through to PVConfig."""

    def test_explicit_degradation_keys_are_passed_through(self) -> None:
        """system_age_years and degradation_rate_per_year from data reach PVConfig."""
        data = {
            "capacity_kw": 4.0,
            "system_age_years": 15.0,
            "degradation_rate_per_year": 0.008,
        }
        pv = _parse_pv_config(data)
        assert pv.system_age_years == 15.0
        assert pv.degradation_rate_per_year == 0.008

    def test_missing_keys_yield_dataclass_defaults(self) -> None:
        """Omitting both keys gives PVConfig defaults (age 0.0, rate 0.005)."""
        data = {"capacity_kw": 4.0}
        pv = _parse_pv_config(data)
        assert pv.system_age_years == 0.0
        assert pv.degradation_rate_per_year == 0.005


class TestModifyPVConfigPreservesDegradation:
    """Tests that _modify_pv_config sweeps do not drop system_age_years/degradation_rate_per_year."""

    def _base_config(self) -> "PVConfig":
        return PVConfig(
            capacity_kw=4.0,
            system_age_years=20.0,
            degradation_rate_per_year=0.008,
        )

    def test_modify_pv_capacity_kw_preserves_age(self) -> None:
        """Sweeping pv_capacity_kw keeps age and degradation rate intact."""
        base = self._base_config()
        result = _modify_pv_config(base, "pv_capacity_kw", 6.0)
        assert result.capacity_kw == 6.0
        assert result.system_age_years == 20.0
        assert result.degradation_rate_per_year == 0.008

    def test_modify_pv_tilt_preserves_age(self) -> None:
        """Sweeping pv_tilt keeps age and degradation rate intact."""
        base = self._base_config()
        result = _modify_pv_config(base, "pv_tilt", 45.0)
        assert result.tilt == 45.0
        assert result.system_age_years == 20.0
        assert result.degradation_rate_per_year == 0.008

    def test_modify_pv_azimuth_preserves_age(self) -> None:
        """Sweeping pv_azimuth keeps age and degradation rate intact."""
        base = self._base_config()
        result = _modify_pv_config(base, "pv_azimuth", 90.0)
        assert result.azimuth == 90.0
        assert result.system_age_years == 20.0
        assert result.degradation_rate_per_year == 0.008


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


class TestParsePVDistributionConfigDegradation:
    """Tests that _parse_pv_distribution_config threads degradation keys into PVDistributionConfig."""

    def test_explicit_keys_are_parsed(self) -> None:
        """system_age_years and degradation_rate_per_year from data reach PVDistributionConfig."""
        data = {
            "capacity_kw": 4.0,
            "system_age_years": 20.0,
            "degradation_rate_per_year": 0.008,
        }
        pv_dist = _parse_pv_distribution_config(data)
        assert pv_dist.system_age_years == 20.0
        assert pv_dist.degradation_rate_per_year == 0.008

    def test_defaults_apply_when_keys_omitted(self) -> None:
        """Omitting both keys yields defaults: system_age_years=0.0, degradation_rate_per_year=0.005."""
        data = {"capacity_kw": 4.0}
        pv_dist = _parse_pv_distribution_config(data)
        assert pv_dist.system_age_years == 0.0
        assert pv_dist.degradation_rate_per_year == 0.005


class TestAgedScenario:
    """Full product read-path test: load_fleet_config propagates system_age_years from YAML."""

    _SCENARIOS_DIR = Path(__file__).parent.parent.parent / "scenarios"

    def test_aged_scenario_has_100_homes_all_aged_20(self) -> None:
        """Loading bristol-phase1-aged.yaml returns 100 homes each with system_age_years=20.0."""
        aged_path = self._SCENARIOS_DIR / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        assert len(fleet.homes) == 100
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 20.0

    def test_baseline_scenario_has_age_zero(self) -> None:
        """Loading bristol-phase1.yaml returns homes with default system_age_years=0.0."""
        baseline_path = self._SCENARIOS_DIR / "bristol-phase1.yaml"
        fleet = load_fleet_config(baseline_path)
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 0.0

    def test_aged_scenario_degradation_factor_is_approx_90pct(self) -> None:
        """The aged scenario yields degradation factor ≈ 0.90 (20yr × 0.5%/yr).

        Exercises the signal chain end-to-end at config speed:
          YAML system_age_years=20  →  home.pv_config.system_age_years==20.0
          + default rate 0.005      →  calculate_degradation_factor → 0.90
        This confirms the ≈10% lower aggregate generation claim without
        running a live PVGIS simulation.
        """
        aged_path = self._SCENARIOS_DIR / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        home = fleet.homes[0]  # all homes share the same scalar age
        factor = calculate_degradation_factor(
            home.pv_config.system_age_years,
            home.pv_config.degradation_rate_per_year,
        )
        expected = 1.0 - 20.0 * 0.005  # 0.90
        assert abs(factor - expected) < 1e-9, (
            f"Expected degradation factor {expected}, got {factor}"
        )


# ---------------------------------------------------------------------------
# FinanceConfig tests (step-1: construction + defaults)
# ---------------------------------------------------------------------------


class TestFinanceConfig:
    """Tests for FinanceConfig dataclass construction, defaults, and immutability."""

    def test_construction_with_required_arg(self) -> None:
        """FinanceConfig can be constructed with only standing_charge_pence_per_day."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.standing_charge_pence_per_day == 60.0

    def test_defaults_vat_rate(self) -> None:
        """Default vat_rate is 0.05."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.vat_rate == 0.05

    def test_defaults_retail_baseline_rate(self) -> None:
        """Default retail_baseline_rate_pence_per_kwh is 23.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retail_baseline_rate_pence_per_kwh == 23.0

    def test_defaults_self_consumption_override_is_none(self) -> None:
        """Default self_consumption_override is None."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.self_consumption_override is None

    def test_defaults_pv_cost_per_kwp(self) -> None:
        """Default pv_cost_per_kwp_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.pv_cost_per_kwp_gbp == 1000.0

    def test_defaults_roof_fit_cost(self) -> None:
        """Default roof_fit_cost_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.roof_fit_cost_gbp == 1000.0

    def test_defaults_battery_cost_per_kwh(self) -> None:
        """Default battery_cost_per_kwh_gbp is 250.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.battery_cost_per_kwh_gbp == 250.0

    def test_defaults_grant_gbp(self) -> None:
        """Default grant_gbp is 250000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grant_gbp == 250000.0

    def test_defaults_equity_fraction(self) -> None:
        """Default equity_fraction is 0.75."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.equity_fraction == 0.75

    def test_defaults_loan_term_years(self) -> None:
        """Default loan_term_years is 15."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_term_years == 15

    def test_defaults_loan_rate(self) -> None:
        """Default loan_rate is 0.07."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_rate == 0.07

    def test_defaults_opex_per_home_per_year(self) -> None:
        """Default opex_per_home_per_year_gbp is 131.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.opex_per_home_per_year_gbp == 131.0

    def test_defaults_asset_life_years(self) -> None:
        """Default asset_life_years is 25."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.asset_life_years == 25

    def test_defaults_inverter_cost_per_kw_is_zero(self) -> None:
        """Default inverter_cost_per_kw_gbp is 0.0 (opt-in, zero-allowed)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    def test_defaults_own_use_rate_pence_per_kwh(self) -> None:
        """Default own_use_rate_pence_per_kwh is 15.0 (CBS transfer price)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.own_use_rate_pence_per_kwh == 15.0

    def test_defaults_retained_cash_floor_per_home_per_year_gbp(self) -> None:
        """Default retained_cash_floor_per_home_per_year_gbp is 27.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 27.0

    def test_defaults_grid_services_income_per_kw_per_year_gbp(self) -> None:
        """Default grid_services_income_per_kw_per_year_gbp is 0.0 (theta-safe seam)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_frozen_raises_on_assignment(self) -> None:
        """FinanceConfig is frozen: attribute assignment raises FrozenInstanceError."""
        import dataclasses

        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.vat_rate = 0.20  # type: ignore[misc]

    def test_standing_charge_is_required(self) -> None:
        """standing_charge_pence_per_day has no default; omitting it raises TypeError."""
        with pytest.raises(TypeError):
            FinanceConfig()  # type: ignore[call-arg]

    def test_custom_values_round_trip(self) -> None:
        """All fields can be set to custom values and are retrievable."""
        fc = FinanceConfig(
            standing_charge_pence_per_day=75.0,
            vat_rate=0.20,
            retail_baseline_rate_pence_per_kwh=28.0,
            self_consumption_override=0.80,
            pv_cost_per_kwp_gbp=900.0,
            roof_fit_cost_gbp=1200.0,
            battery_cost_per_kwh_gbp=300.0,
            inverter_cost_per_kw_gbp=200.0,
            grant_gbp=200000.0,
            equity_fraction=0.60,
            loan_term_years=20,
            loan_rate=0.06,
            opex_per_home_per_year_gbp=150.0,
            asset_life_years=25,
            own_use_rate_pence_per_kwh=12.0,
            retained_cash_floor_per_home_per_year_gbp=30.0,
            grid_services_income_per_kw_per_year_gbp=5.0,
        )
        assert fc.standing_charge_pence_per_day == 75.0
        assert fc.vat_rate == 0.20
        assert fc.retail_baseline_rate_pence_per_kwh == 28.0
        assert fc.self_consumption_override == 0.80
        assert fc.pv_cost_per_kwp_gbp == 900.0
        assert fc.roof_fit_cost_gbp == 1200.0
        assert fc.battery_cost_per_kwh_gbp == 300.0
        assert fc.inverter_cost_per_kw_gbp == 200.0
        assert fc.grant_gbp == 200000.0
        assert fc.equity_fraction == 0.60
        assert fc.loan_term_years == 20
        assert fc.loan_rate == 0.06
        assert fc.opex_per_home_per_year_gbp == 150.0
        assert fc.asset_life_years == 25
        assert fc.own_use_rate_pence_per_kwh == 12.0
        assert fc.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert fc.grid_services_income_per_kw_per_year_gbp == 5.0


# ---------------------------------------------------------------------------
# FinanceConfig validation tests (step-3: __post_init__ rejections + acceptances)
# ---------------------------------------------------------------------------


class TestFinanceConfigValidation:
    """Tests for FinanceConfig.__post_init__ validation (raises ConfigurationError)."""

    _BASE = dict(standing_charge_pence_per_day=60.0)

    # ---- vat_rate ----

    def test_vat_rate_too_high_raises(self) -> None:
        """vat_rate > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=2.0)

    def test_vat_rate_negative_raises(self) -> None:
        """vat_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=-0.1)

    def test_vat_rate_zero_ok(self) -> None:
        """vat_rate == 0 is valid (VAT-exempt scenario)."""
        fc = FinanceConfig(**self._BASE, vat_rate=0.0)
        assert fc.vat_rate == 0.0

    def test_vat_rate_one_ok(self) -> None:
        """vat_rate == 1 is valid (100% VAT, boundary)."""
        fc = FinanceConfig(**self._BASE, vat_rate=1.0)
        assert fc.vat_rate == 1.0

    # ---- equity_fraction ----

    def test_equity_fraction_too_high_raises(self) -> None:
        """equity_fraction > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=1.5)

    def test_equity_fraction_negative_raises(self) -> None:
        """equity_fraction < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=-0.1)

    def test_equity_fraction_zero_ok(self) -> None:
        """equity_fraction == 0 is valid (fully debt-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=0.0)
        assert fc.equity_fraction == 0.0

    def test_equity_fraction_one_ok(self) -> None:
        """equity_fraction == 1 is valid (fully equity-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=1.0)
        assert fc.equity_fraction == 1.0

    # ---- self_consumption_override ----

    def test_self_consumption_override_zero_raises(self) -> None:
        """self_consumption_override == 0 raises ConfigurationError (must be > 0)."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=0.0)

    def test_self_consumption_override_too_high_raises(self) -> None:
        """self_consumption_override > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=1.5)

    def test_self_consumption_override_one_ok(self) -> None:
        """self_consumption_override == 1 is valid (100% self-consumed)."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=1.0)
        assert fc.self_consumption_override == 1.0

    def test_self_consumption_override_none_ok(self) -> None:
        """self_consumption_override == None skips override validation."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=None)
        assert fc.self_consumption_override is None

    # ---- loan_term_years ----

    def test_loan_term_years_zero_raises(self) -> None:
        """loan_term_years == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=0)

    def test_loan_term_years_negative_raises(self) -> None:
        """loan_term_years < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=-1)

    # ---- loan_rate ----

    def test_loan_rate_negative_raises(self) -> None:
        """loan_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_rate=-0.01)

    def test_loan_rate_zero_ok(self) -> None:
        """loan_rate == 0 is valid (interest-free loan)."""
        fc = FinanceConfig(**self._BASE, loan_rate=0.0)
        assert fc.loan_rate == 0.0

    # ---- asset_life_years vs loan_term_years ----

    def test_asset_life_less_than_loan_term_raises(self) -> None:
        """asset_life_years < loan_term_years raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, asset_life_years=10, loan_term_years=15)

    def test_asset_life_equals_loan_term_ok(self) -> None:
        """asset_life_years == loan_term_years is valid (equality allowed)."""
        fc = FinanceConfig(**self._BASE, asset_life_years=15, loan_term_years=15)
        assert fc.asset_life_years == 15

    # ---- cost fields (must be > 0) ----

    def test_standing_charge_zero_raises(self) -> None:
        """standing_charge_pence_per_day == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(standing_charge_pence_per_day=0.0)

    def test_retail_baseline_rate_zero_raises(self) -> None:
        """retail_baseline_rate_pence_per_kwh == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retail_baseline_rate_pence_per_kwh=0.0)

    def test_pv_cost_per_kwp_zero_raises(self) -> None:
        """pv_cost_per_kwp_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, pv_cost_per_kwp_gbp=0.0)

    def test_roof_fit_cost_negative_raises(self) -> None:
        """roof_fit_cost_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, roof_fit_cost_gbp=-1.0)

    def test_battery_cost_per_kwh_zero_raises(self) -> None:
        """battery_cost_per_kwh_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, battery_cost_per_kwh_gbp=0.0)

    def test_opex_per_home_per_year_negative_raises(self) -> None:
        """opex_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, opex_per_home_per_year_gbp=-1.0)

    # ---- grant_gbp (must be >= 0) ----

    def test_grant_negative_raises(self) -> None:
        """grant_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grant_gbp=-1.0)

    def test_grant_zero_ok(self) -> None:
        """grant_gbp == 0 is valid (no grant received)."""
        fc = FinanceConfig(**self._BASE, grant_gbp=0.0)
        assert fc.grant_gbp == 0.0

    # ---- inverter_cost_per_kw_gbp (must be >= 0) ----

    def test_inverter_cost_negative_raises(self) -> None:
        """inverter_cost_per_kw_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=-5.0)

    def test_inverter_cost_zero_accepted(self) -> None:
        """inverter_cost_per_kw_gbp == 0.0 is valid (opt-in with zero default)."""
        fc = FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=0.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    # ---- own_use_rate_pence_per_kwh (must be >= 0) ----

    def test_own_use_rate_negative_raises(self) -> None:
        """own_use_rate_pence_per_kwh < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=-1.0)

    def test_own_use_rate_zero_ok(self) -> None:
        """own_use_rate_pence_per_kwh == 0.0 is valid (zero transfer price allowed)."""
        fc = FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=0.0)
        assert fc.own_use_rate_pence_per_kwh == 0.0

    # ---- retained_cash_floor_per_home_per_year_gbp (must be >= 0) ----

    def test_retained_cash_floor_negative_raises(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=-1.0)

    def test_retained_cash_floor_zero_ok(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp == 0.0 is valid (no floor allowed)."""
        fc = FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=0.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 0.0

    # ---- grid_services_income_per_kw_per_year_gbp (must be >= 0) ----

    def test_grid_services_income_negative_raises(self) -> None:
        """grid_services_income_per_kw_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=-1.0)

    def test_grid_services_income_zero_ok(self) -> None:
        """grid_services_income_per_kw_per_year_gbp == 0.0 is valid (theta-safe default)."""
        fc = FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=0.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0


# ---------------------------------------------------------------------------
# _parse_finance_config tests (step-5)
# ---------------------------------------------------------------------------


class TestFinanceConfigParsing:
    """Tests for _parse_finance_config parser function."""

    def test_none_returns_none(self) -> None:
        """_parse_finance_config(None) returns None (no finance block in YAML)."""
        assert _parse_finance_config(None) is None

    def test_minimal_dict_uses_defaults(self) -> None:
        """Dict with only standing_charge_pence_per_day uses all other defaults."""
        result = _parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result is not None
        assert result.standing_charge_pence_per_day == 60.0
        assert result.vat_rate == 0.05
        assert result.retail_baseline_rate_pence_per_kwh == 23.0
        assert result.self_consumption_override is None
        assert result.pv_cost_per_kwp_gbp == 1000.0
        assert result.roof_fit_cost_gbp == 1000.0
        assert result.battery_cost_per_kwh_gbp == 250.0
        assert result.inverter_cost_per_kw_gbp == 0.0
        assert result.grant_gbp == 250000.0
        assert result.equity_fraction == 0.75
        assert result.loan_term_years == 15
        assert result.loan_rate == 0.07
        assert result.opex_per_home_per_year_gbp == 131.0
        assert result.asset_life_years == 25
        assert result.own_use_rate_pence_per_kwh == 15.0
        assert result.retained_cash_floor_per_home_per_year_gbp == 27.0
        assert result.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_full_dict_round_trips(self) -> None:
        """All fields supplied in the dict are reflected on the returned FinanceConfig."""
        data = {
            "standing_charge_pence_per_day": 70.0,
            "vat_rate": 0.08,
            "retail_baseline_rate_pence_per_kwh": 28.5,
            "self_consumption_override": 0.70,
            "pv_cost_per_kwp_gbp": 950.0,
            "roof_fit_cost_gbp": 1100.0,
            "battery_cost_per_kwh_gbp": 280.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 200000.0,
            "equity_fraction": 0.60,
            "loan_term_years": 20,
            "loan_rate": 0.065,
            "opex_per_home_per_year_gbp": 140.0,
            "asset_life_years": 25,
            "own_use_rate_pence_per_kwh": 12.0,
            "retained_cash_floor_per_home_per_year_gbp": 30.0,
            "grid_services_income_per_kw_per_year_gbp": 5.0,
        }
        result = _parse_finance_config(data)
        assert result is not None
        assert result.standing_charge_pence_per_day == 70.0
        assert result.vat_rate == 0.08
        assert result.retail_baseline_rate_pence_per_kwh == 28.5
        assert result.self_consumption_override == 0.70
        assert result.pv_cost_per_kwp_gbp == 950.0
        assert result.roof_fit_cost_gbp == 1100.0
        assert result.battery_cost_per_kwh_gbp == 280.0
        assert result.inverter_cost_per_kw_gbp == 200.0
        assert result.grant_gbp == 200000.0
        assert result.equity_fraction == 0.60
        assert result.loan_term_years == 20
        assert result.loan_rate == 0.065
        assert result.opex_per_home_per_year_gbp == 140.0
        assert result.asset_life_years == 25
        assert result.own_use_rate_pence_per_kwh == 12.0
        assert result.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert result.grid_services_income_per_kw_per_year_gbp == 5.0

    def test_inverter_cost_omission_defaults_zero(self) -> None:
        """Parser with no inverter_cost_per_kw_gbp key returns 0.0 (acceptance guard)."""
        result = _parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 0.0

    def test_inverter_cost_key_round_trips(self) -> None:
        """inverter_cost_per_kw_gbp in dict is reflected on the returned FinanceConfig."""
        result = _parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": 200.0}
        )
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 200.0

    def test_negative_inverter_cost_propagates_configuration_error(self) -> None:
        """negative inverter_cost_per_kw_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": -5.0}
            )

    def test_out_of_range_propagates_configuration_error(self) -> None:
        """An out-of-range field (vat_rate=2.0) raises ConfigurationError via __post_init__."""
        with pytest.raises(ConfigurationError):
            _parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": 2.0}
            )

    def test_zero_grant_accepted(self) -> None:
        """grant_gbp=0 is accepted by the parser (non-negative allowed)."""
        result = _parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "grant_gbp": 0.0}
        )
        assert result is not None
        assert result.grant_gbp == 0.0

    def test_missing_standing_charge_raises(self) -> None:
        """Finance block without standing_charge_pence_per_day raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="standing_charge_pence_per_day"):
            _parse_finance_config({"vat_rate": 0.05})

    def test_int_coercion_of_year_fields(self) -> None:
        """loan_term_years/asset_life_years given as floats in the dict are coerced to int."""
        result = _parse_finance_config(
            {
                "standing_charge_pence_per_day": 60.0,
                "loan_term_years": 20.0,
                "asset_life_years": 25.0,
            }
        )
        assert result is not None
        assert result.loan_term_years == 20
        assert isinstance(result.loan_term_years, int)
        assert result.asset_life_years == 25
        assert isinstance(result.asset_life_years, int)

    def test_non_numeric_value_raises_configuration_error(self) -> None:
        """A non-numeric string for a numeric field raises ConfigurationError (not ValueError)."""
        with pytest.raises(ConfigurationError, match="non-numeric"):
            _parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": "not-a-number"}
            )

    def test_negative_own_use_rate_propagates_configuration_error(self) -> None:
        """negative own_use_rate_pence_per_kwh in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "own_use_rate_pence_per_kwh": -1.0}
            )

    def test_negative_retained_cash_floor_propagates_configuration_error(self) -> None:
        """negative retained_cash_floor_per_home_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "retained_cash_floor_per_home_per_year_gbp": -1.0,
                }
            )

    def test_negative_grid_services_income_propagates_configuration_error(self) -> None:
        """negative grid_services_income_per_kw_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            _parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "grid_services_income_per_kw_per_year_gbp": -1.0,
                }
            )


# ---------------------------------------------------------------------------
# ScenarioConfig.finance field + load_scenarios round-trip (step-7)
# ---------------------------------------------------------------------------


class TestScenarioFinance:
    """Tests for ScenarioConfig.finance field and _parse_scenario wiring."""

    _MINIMAL_PERIOD = {
        "start_date": "2024-01-01",
        "end_date": "2024-01-07",
    }
    _MINIMAL_HOME = {
        "pv": {"capacity_kw": 4.0},
        "load": {"annual_consumption_kwh": 3400},
    }

    def test_scenario_config_finance_defaults_to_none(self) -> None:
        """ScenarioConfig.finance is None when not provided (constructed directly)."""
        from solar_challenge.home import HomeConfig
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig

        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        sc = ScenarioConfig(
            name="test",
            period=SimulationPeriod(**self._MINIMAL_PERIOD),
            home=home,
        )
        assert sc.finance is None

    def test_load_scenarios_with_finance_block_populates_field(self) -> None:
        """YAML with a top-level finance: block → scenarios[0].finance is FinanceConfig."""
        yaml_content = (
            "name: Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  vat_rate: 0.08\n"
            "  self_consumption_override: 0.75\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            fc = scenarios[0].finance
            assert fc is not None
            assert isinstance(fc, FinanceConfig)
            assert fc.standing_charge_pence_per_day == 65.0
            assert fc.vat_rate == 0.08
            assert fc.self_consumption_override == 0.75
            # Un-overridden fields use defaults
            assert fc.loan_term_years == 15
        finally:
            path.unlink()

    def test_load_scenarios_without_finance_block_is_none(self) -> None:
        """YAML without a finance: block → scenarios[0].finance is None."""
        yaml_content = (
            "name: No Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            assert scenarios[0].finance is None
        finally:
            path.unlink()

    def test_load_scenarios_with_cost_recovery_fields_round_trip(self) -> None:
        """YAML finance: block with the three cost-recovery keys round-trips into FinanceConfig."""
        yaml_content = (
            "name: Cost Recovery Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  own_use_rate_pence_per_kwh: 12.5\n"
            "  retained_cash_floor_per_home_per_year_gbp: 30.0\n"
            "  grid_services_income_per_kw_per_year_gbp: 8.0\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            fc = scenarios[0].finance
            assert fc is not None
            assert isinstance(fc, FinanceConfig)
            assert fc.own_use_rate_pence_per_kwh == 12.5
            assert fc.retained_cash_floor_per_home_per_year_gbp == 30.0
            assert fc.grid_services_income_per_kw_per_year_gbp == 8.0
            # Un-overridden fields use documented defaults
            assert fc.loan_term_years == 15
        finally:
            path.unlink()


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


class TestLoadFleetConfigFlexThreading:
    """Tests for YAML tariff + grid_charging threading through load_fleet_config."""

    def test_fleet_yaml_tariff_and_grid_charging_threaded(self) -> None:
        """A fleet YAML with top-level tariff: and battery.grid_charging: threads both to all homes."""
        yaml_content = """
name: Flex Threading Test
fleet_distribution:
  n_homes: 4
  seed: 7
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
    grid_charging:
      target_soc_fraction: 0.9
  load:
    annual_consumption_kwh: 3400
tariff:
  type: economy_7
  off_peak_rate: 0.09
  peak_rate: 0.25
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert len(fleet.homes) == 4
            for home in fleet.homes:
                assert home.tariff_config is not None, "tariff_config should be threaded"
                assert home.battery_config is not None, "all homes should have batteries"
                assert home.battery_config.grid_charging is not None, "grid_charging should be threaded"
                assert home.battery_config.grid_charging.target_soc_fraction == 0.9
        finally:
            path.unlink()
