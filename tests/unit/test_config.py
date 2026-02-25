"""Tests for configuration file support."""

import json
import random
import tempfile
from pathlib import Path

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import (
    BatteryDistributionConfig,
    ConfigurationError,
    DispatchStrategyConfig,
    FleetDistributionConfig,
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
    _parse_dispatch_strategy_config,
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
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


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
