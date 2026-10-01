# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a scenario file's top level, from the raw YAML or JSON read to the ScenarioConfig that load_scenarios builds."""

import json
import tempfile
from pathlib import Path

import pytest

from solar_challenge.config import (
    ConfigurationError,
    OutputConfig,
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    load_config_json,
    load_config_yaml,
    load_scenarios,
    parse_location_block,
)
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


class TestLocationBlockParsing:
    """Tests for parse_location_block's public contract."""

    def test_full_block_parses_every_field(self) -> None:
        """Every key of a location block reaches the Location."""
        block = {
            "latitude": 55.95,
            "longitude": -3.19,
            "timezone": "Europe/London",
            "altitude": 47.0,
            "name": "Edinburgh",
        }
        assert parse_location_block(block) == Location(
            latitude=55.95,
            longitude=-3.19,
            timezone="Europe/London",
            altitude=47.0,
            name="Edinburgh",
        )

    @pytest.mark.parametrize(
        "block", [pytest.param(None, id="absent"), pytest.param({}, id="empty")]
    )
    def test_absent_or_empty_block_is_bristol(self, block: dict[str, object] | None) -> None:
        """A config that gives no location simulates Bristol."""
        assert parse_location_block(block) == Location.bristol()

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            pytest.param(
                {"name": "Clifton"},
                Location(
                    latitude=51.45,
                    longitude=-2.58,
                    timezone="Europe/London",
                    altitude=11.0,
                    name="Clifton",
                ),
                id="name-only",
            ),
            pytest.param(
                {"latitude": 55.95, "longitude": -3.19},
                Location(
                    latitude=55.95,
                    longitude=-3.19,
                    timezone="Europe/London",
                    altitude=11.0,
                    name="",
                ),
                id="coordinates-only",
            ),
        ],
    )
    def test_omitted_keys_take_bristol_values_except_the_name(
        self, block: dict[str, object], expected: Location
    ) -> None:
        """Omitted coordinates, timezone and altitude are Bristol's; an omitted name stays empty."""
        assert parse_location_block(block) == expected
