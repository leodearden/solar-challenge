# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a scenario file's top level, from the raw YAML or JSON read to the ScenarioConfig that load_scenarios builds."""

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from solar_challenge.config import (
    OutputConfig,
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    load_config_json,
    load_config_yaml,
    load_scenarios,
    parse_location_block,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff


def _home() -> HomeConfig:
    """A 4 kW home on the default load, carrying no SEG tariff of its own."""
    return HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())


def _scenario(
    *,
    home: HomeConfig | None = None,
    homes: list[HomeConfig] | None = None,
    seg_tariff_pence_per_kwh: float | None = None,
) -> ScenarioConfig:
    """Scenario 'x' over the first week of 2024, holding *home* or *homes* under *seg_tariff_pence_per_kwh*."""
    return ScenarioConfig(
        name="x",
        period=SimulationPeriod("2024-01-01", "2024-01-07"),
        home=home,
        homes=homes or [],
        seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh,
    )


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

    def test_holds_its_homes_as_a_tuple_in_order(self) -> None:
        """A list of homes is held as a tuple in the given order, and the single-home form holds none."""
        h1 = HomeConfig(pv_config=PVConfig(capacity_kw=3.0), load_config=LoadConfig())
        h2 = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

        fleet = ScenarioConfig(
            name="Fleet",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            homes=[h1, h2],
        )
        single = ScenarioConfig(
            name="Single",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            home=h1,
        )

        assert isinstance(fleet.homes, tuple)
        assert fleet.homes == (h1, h2)
        assert single.homes == ()

    def test_refuses_a_field_assignment(self) -> None:
        """A scenario is a frozen value: assigning one of its fields raises FrozenInstanceError."""
        scenario = ScenarioConfig(
            name="Test",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            homes=[HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())],
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            scenario.homes = ()  # type: ignore[misc]

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


class TestSimulatedHomes:
    """simulated_homes() reads the homes a scenario simulates, each given the scenario's SEG rate unless it carries its own tariff."""

    def test_the_single_home_is_simulated_at_the_scenario_seg_rate(self) -> None:
        home = _home()

        scenario = _scenario(home=home, seg_tariff_pence_per_kwh=5.0)

        assert scenario.simulated_homes() == (
            dataclasses.replace(home, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=5.0)),
        )
        assert scenario.home is home
        assert scenario.home.seg_tariff is None

    def test_a_fleet_home_is_filled_with_the_scenario_rate_and_a_home_tariff_is_kept(self) -> None:
        h1 = _home()
        h2 = dataclasses.replace(_home(), name="north", seg_tariff=SEGTariff("Octopus", 5.0))

        scenario = _scenario(homes=[h1, h2], seg_tariff_pence_per_kwh=5.0)
        simulated = scenario.simulated_homes()

        assert simulated[0] == dataclasses.replace(h1, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=5.0))
        assert simulated[1] is h2
        assert scenario.homes == (h1, h2)

    def test_with_no_scenario_rate_the_stored_homes_are_simulated(self) -> None:
        h1 = _home()
        h2 = dataclasses.replace(_home(), name="north", seg_tariff=SEGTariff("Octopus", 5.0))

        fleet = _scenario(homes=[h1, h2])
        single = _scenario(home=h1)

        assert fleet.simulated_homes() == fleet.homes
        assert fleet.simulated_homes()[0].seg_tariff is None
        assert fleet.simulated_homes()[1].seg_tariff == SEGTariff("Octopus", 5.0)
        assert single.simulated_homes() == (h1,)

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda: _scenario(home=_home(), seg_tariff_pence_per_kwh=5.0), id="home"),
            pytest.param(lambda: _scenario(homes=[_home(), _home()], seg_tariff_pence_per_kwh=5.0), id="homes"),
        ],
    )
    def test_is_pure_and_never_empty(self, build: Callable[[], ScenarioConfig]) -> None:
        scenario = build()

        assert scenario.simulated_homes() == scenario.simulated_homes()
        assert len(scenario.simulated_homes()) >= 1


class TestLoadConfigYaml:
    """Tests for YAML configuration loading."""

    def test_load_yaml_file(self, tmp_path: Path) -> None:
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
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        config = load_config_yaml(path)
        assert config["name"] == "Test Scenario"
        assert config["home"]["pv"]["capacity_kw"] == 4.0

    def test_load_nonexistent_yaml_raises(self) -> None:
        """Test loading nonexistent YAML file raises error."""
        with pytest.raises(ConfigurationError, match="not found"):
            load_config_yaml("/nonexistent/path.yaml")


class TestLoadConfigJson:
    """Tests for JSON configuration loading."""

    def test_load_json_file(self, tmp_path: Path) -> None:
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
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps(json_content))

        config = load_config_json(path)
        assert config["name"] == "Test Scenario"
        assert config["home"]["pv"]["capacity_kw"] == 4.0

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        """Test loading invalid JSON raises error."""
        path = tmp_path / "scenario.json"
        path.write_text("{ invalid json }")

        with pytest.raises(ConfigurationError, match="Invalid JSON"):
            load_config_json(path)


class TestLoadConfig:
    """Tests for auto-detecting configuration format."""

    def test_auto_detect_yaml(self, tmp_path: Path) -> None:
        """Test auto-detecting YAML format."""
        yaml_content = "name: Test\nvalue: 123"
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml_content)

        config = load_config(path)
        assert config["name"] == "Test"

    def test_auto_detect_yml(self, tmp_path: Path) -> None:
        """Test auto-detecting .yml format."""
        yaml_content = "name: Test\nvalue: 123"
        path = tmp_path / "scenario.yml"
        path.write_text(yaml_content)

        config = load_config(path)
        assert config["name"] == "Test"

    def test_auto_detect_json(self, tmp_path: Path) -> None:
        """Test auto-detecting JSON format."""
        json_content = {"name": "Test", "value": 123}
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps(json_content))

        config = load_config(path)
        assert config["name"] == "Test"

    def test_unknown_format_raises(self, tmp_path: Path) -> None:
        """Test unknown format raises error."""
        path = tmp_path / "scenario.txt"
        path.write_text("some content")

        with pytest.raises(ConfigurationError, match="Unknown.*format"):
            load_config(path)


class TestLoadScenarios:
    """Tests for loading scenarios from configuration files."""

    def test_load_single_scenario(self, tmp_path: Path) -> None:
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
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps(json_content))

        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].name == "Single Home Test"
        assert scenarios[0].home is not None

    def test_load_multiple_scenarios(self, tmp_path: Path) -> None:
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
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps(json_content))

        scenarios = load_scenarios(path)
        assert len(scenarios) == 2
        assert scenarios[0].name == "Scenario 1"
        assert scenarios[1].name == "Scenario 2"


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
        "block",
        [
            pytest.param(None, id="absent"),
            pytest.param({}, id="empty"),
            pytest.param({"name": None}, id="all-null"),
        ],
    )
    def test_absent_or_empty_block_is_bristol(self, block: dict[str, object] | None) -> None:
        """A config that gives no location, or only null keys, which read as absent, simulates Bristol."""
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
            pytest.param(
                {"latitude": None, "name": "Clifton"},
                Location(
                    latitude=51.45,
                    longitude=-2.58,
                    timezone="Europe/London",
                    altitude=11.0,
                    name="Clifton",
                ),
                id="null-latitude",
            ),
        ],
    )
    def test_omitted_keys_take_bristol_values_except_the_name(
        self, block: dict[str, object], expected: Location
    ) -> None:
        """Omitted or null coordinates, timezone and altitude are Bristol's; an omitted name stays empty."""
        assert parse_location_block(block) == expected
