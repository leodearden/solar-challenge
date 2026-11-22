# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a scenario file's top level, from the raw YAML or JSON read to the ScenarioConfig that load_scenarios builds."""

import dataclasses
import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.config import (
    OutputConfig,
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    load_config_json,
    load_config_yaml,
    load_scenarios,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import parse_location_block
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow

_SUMMER = SimulationPeriod("2024-06-01", "2024-08-31")
"""June to August 2024, as ISO strings."""

_SUMMER_AT_A_TIME_OF_DAY = SimulationPeriod(
    pd.Timestamp("2024-06-01 06:00", tz="Europe/London"), pd.Timestamp("2024-08-31 18:00", tz="Europe/London")
)
"""June to August 2024, as zoned Timestamps at 06:00 on the first day and 18:00 on the last."""

_SUMMER_AS_NAIVE_TIMESTAMPS = SimulationPeriod(pd.Timestamp("2024-06-01"), pd.Timestamp("2024-08-31"))
"""June to August 2024, as naive Timestamps at midnight."""

_SUMMER_LATE_ON_UTCS_CLOCK = SimulationPeriod(
    pd.Timestamp("2024-06-01 23:30", tz="UTC"), pd.Timestamp("2024-08-31 23:30", tz="UTC")
)
"""June to August 2024, as Timestamps at 23:30 on UTC's clock: on London's, 00:30 on 2 June and on 1 September."""


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


def _bristol_scenario(period: SimulationPeriod = _SUMMER) -> ScenarioConfig:
    """Scenario 'x' in Bristol over *period*, holding one home."""
    return ScenarioConfig(name="x", period=period, location=Location.bristol(), home=_home())


def _naming(*pieces: str) -> str:
    """A pattern matching a message that names each of *pieces*, in order."""
    return ".*".join(re.escape(piece) for piece in pieces)


def _one_kw_larger(home: HomeConfig) -> HomeConfig:
    """*home* with its PV array 1 kW larger."""
    return dataclasses.replace(
        home, pv_config=dataclasses.replace(home.pv_config, capacity_kw=home.pv_config.capacity_kw + 1.0)
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

    def test_refuses_a_field_assignment(self) -> None:
        """A period is a frozen value: assigning one of its fields raises FrozenInstanceError."""
        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-01-07")

        with pytest.raises(dataclasses.FrozenInstanceError):
            period.end_date = "2024-01-14"  # type: ignore[misc]


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

    def test_refuses_a_field_assignment(self) -> None:
        """An output configuration is a frozen value: assigning one of its fields raises FrozenInstanceError."""
        config = OutputConfig()

        with pytest.raises(dataclasses.FrozenInstanceError):
            config.aggregation = "daily"  # type: ignore[misc]


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

    def test_holds_its_seg_rate_as_the_float_segtariff_reads(self) -> None:
        scenario = _scenario(home=_home(), seg_tariff_pence_per_kwh=5)

        assert type(scenario.seg_tariff_pence_per_kwh) is float
        assert scenario.seg_tariff_pence_per_kwh == 5.0

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
    def test_fills_copies_and_leaves_the_scenario_as_built(self, build: Callable[[], ScenarioConfig]) -> None:
        scenario = build()

        first = scenario.simulated_homes()
        second = scenario.simulated_homes()

        assert all(home.seg_tariff is not None for home in first)
        assert second == first
        assert scenario == build()


class TestScenarioConfigRefusals:
    """Construction is the one point that refuses a SEG rate SEGTariff refuses, a home's own SEG rate other than the scenario's, a scenario tariff_config, and a period whose days are not dates or run backwards."""

    @pytest.mark.parametrize(
        ("rate", "requirement"),
        [
            pytest.param(-1.0, "at least 0", id="negative"),
            pytest.param(math.nan, "a finite number", id="nan"),
            pytest.param(math.inf, "a finite number", id="infinite"),
            pytest.param(True, "a finite number", id="boolean"),
        ],
    )
    def test_a_seg_rate_segtariff_refuses_is_refused_naming_the_scenario_and_the_rate(
        self, rate: float, requirement: str
    ) -> None:
        with pytest.raises(
            ConfigurationError, match=_naming("'x'", f"seg_tariff_pence_per_kwh={rate!r}", requirement)
        ):
            _scenario(homes=[_home()], seg_tariff_pence_per_kwh=rate)

    def test_the_seg_rate_is_refused_before_a_home_rate_is_compared_with_it(self) -> None:
        home = dataclasses.replace(_home(), seg_tariff=SEGTariff("", 5.0))

        with pytest.raises(ConfigurationError, match=_naming("seg_tariff_pence_per_kwh=nan", "a finite number")):
            _scenario(homes=[home], seg_tariff_pence_per_kwh=math.nan)

    def test_a_fleet_home_at_another_seg_rate_is_refused_by_its_path_and_name(self) -> None:
        north = dataclasses.replace(_home(), name="north", seg_tariff=SEGTariff("", 3.0))

        with pytest.raises(ConfigurationError, match=_naming("homes[1]", "'north'", "3.0", "5.0")):
            _scenario(homes=[_home(), north], seg_tariff_pence_per_kwh=5.0)

    def test_the_single_home_at_another_seg_rate_is_refused(self) -> None:
        home = dataclasses.replace(_home(), seg_tariff=SEGTariff("", 3.0))

        with pytest.raises(ConfigurationError, match=_naming(" home ", "3.0", "5.0")):
            _scenario(home=home, seg_tariff_pence_per_kwh=5.0)

    def test_replace_re_runs_the_check(self) -> None:
        fleet = _scenario(homes=[dataclasses.replace(_home(), seg_tariff=SEGTariff("", 5.0))])

        with pytest.raises(ConfigurationError, match=_naming("homes[0]", "5.0", "3.0")):
            dataclasses.replace(fleet, seg_tariff_pence_per_kwh=3.0)

    @pytest.mark.parametrize(
        ("home_rate", "scenario_rate"),
        [
            pytest.param(5.0, 5.0 + 1e-12, id="a-home-rate-close-to-the-scenario-rate"),
            pytest.param(3.0, None, id="no-scenario-rate"),
        ],
    )
    def test_a_home_tariff_the_scenario_does_not_contradict_constructs(
        self, home_rate: float, scenario_rate: float | None
    ) -> None:
        home = dataclasses.replace(_home(), seg_tariff=SEGTariff("", home_rate))

        scenario = _scenario(homes=[home], seg_tariff_pence_per_kwh=scenario_rate)

        assert scenario.homes == (home,)

    def test_a_scenario_tariff_config_is_refused_naming_the_home_field(self) -> None:
        with pytest.raises(ConfigurationError, match=_naming("tariff_config", "HomeConfig.tariff_config")):
            ScenarioConfig(
                name="x",
                period=SimulationPeriod("2024-01-01", "2024-01-07"),
                home=_home(),
                tariff_config=TariffConfig.economy_7(),
            )

    @pytest.mark.parametrize(
        ("start_date", "end_date"),
        [
            pytest.param("2024", "2024-01-07", id="a-year"),
            pytest.param("2024-02-30", "2024-03-01", id="a-day-its-month-lacks"),
            pytest.param("20240601", "2024-06-07", id="an-iso-basic-date"),
            pytest.param(pd.NaT, "2024-06-07", id="not-a-time"),
        ],
    )
    def test_a_start_day_that_is_not_a_date_is_refused_naming_the_scenario_the_field_and_the_value(
        self, start_date: object, end_date: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=_naming("'x'", "period.start_date", repr(start_date))):
            ScenarioConfig(name="x", period=SimulationPeriod(start_date, end_date), home=_home())

    def test_an_end_day_that_is_not_a_date_is_refused_by_its_own_name(self) -> None:
        with pytest.raises(ConfigurationError, match=_naming("'x'", "period.end_date", "'2024'")):
            ScenarioConfig(name="x", period=SimulationPeriod("2024-01-01", "2024"), home=_home())

    def test_a_period_whose_last_day_precedes_its_first_is_refused_naming_both(self) -> None:
        with pytest.raises(
            ConfigurationError,
            match=_naming("'x'", "period.start_date", "2024-08-31", "period.end_date", "2024-06-01"),
        ):
            ScenarioConfig(name="x", period=SimulationPeriod("2024-08-31", "2024-06-01"), home=_home())

    def test_a_one_day_period_constructs(self) -> None:
        period = SimulationPeriod("2024-06-21", "2024-06-21")

        assert ScenarioConfig(name="x", period=period, home=_home()).period == period

    @pytest.mark.parametrize(
        "period",
        [
            pytest.param(SimulationPeriod(date(2024, 6, 1), date(2024, 6, 7)), id="dates-as-unquoted-yaml-gives"),
            pytest.param(
                SimulationPeriod(
                    pd.Timestamp("2024-06-01 06:00", tz="Europe/London"),
                    pd.Timestamp("2024-06-07 18:00", tz="Europe/London"),
                ),
                id="zoned-timestamps-at-a-time-of-day",
            ),
            pytest.param(
                SimulationPeriod(pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-07")), id="naive-timestamps"
            ),
        ],
    )
    def test_a_period_of_dates_or_timestamps_constructs(self, period: SimulationPeriod) -> None:
        assert ScenarioConfig(name="x", period=period, home=_home()).period == period


class TestMapHomes:
    """map_homes(transform) applies *transform* to each stored home, in either form, keeping every scenario-level field."""

    def test_the_single_home_form_maps_its_home(self) -> None:
        home = _home()

        mapped = _scenario(home=home).map_homes(_one_kw_larger)

        assert mapped.home == _one_kw_larger(home)
        assert mapped.homes == ()

    def test_the_fleet_form_maps_each_home_in_order(self) -> None:
        scenario = _scenario(homes=[_home(), dataclasses.replace(_home(), name="north")])

        mapped = scenario.map_homes(_one_kw_larger)

        assert mapped.homes == tuple(_one_kw_larger(home) for home in scenario.homes)

    def test_every_scenario_level_field_is_kept(self) -> None:
        scenario = ScenarioConfig(
            name="full",
            period=SimulationPeriod("2024-01-01", "2024-01-07"),
            description="every scenario-level field set",
            location=Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester"),
            homes=[_home(), _home()],
            output=OutputConfig(aggregation="daily"),
            seg_tariff_pence_per_kwh=5.0,
            finance=FinanceConfig(standing_charge_pence_per_day=28.0),
        )

        mapped = scenario.map_homes(_one_kw_larger)

        assert mapped == dataclasses.replace(
            scenario, homes=tuple(_one_kw_larger(home) for home in scenario.homes)
        )

    def test_the_transform_sees_the_stored_home_not_the_filled_one(self) -> None:
        seen: list[HomeConfig] = []

        def record(home: HomeConfig) -> HomeConfig:
            seen.append(home)
            return home

        _scenario(homes=[_home()], seg_tariff_pence_per_kwh=5.0).map_homes(record)

        assert [home.seg_tariff for home in seen] == [None]

    def test_a_transform_giving_a_home_another_seg_rate_is_refused(self) -> None:
        scenario = _scenario(homes=[_home()], seg_tariff_pence_per_kwh=5.0)

        with pytest.raises(ConfigurationError, match=_naming("homes[0]", "3.0", "5.0")):
            scenario.map_homes(lambda home: dataclasses.replace(home, seg_tariff=SEGTariff("", 3.0)))


class TestScenarioWindow:
    """window(), with_window() and simulation_bounds() read the scenario's period as the days it simulates."""

    def test_the_window_is_the_periods_days_at_one_minute_in_the_scenarios_zone(self) -> None:
        assert _bristol_scenario().window() == SimulationWindow(
            date(2024, 6, 1), date(2024, 8, 31), ONE_MINUTE, "Europe/London"
        )

    def test_with_no_scenario_location_the_zone_is_the_first_homes(self) -> None:
        new_york = dataclasses.replace(
            _home(), location=Location(latitude=40.71, longitude=-74.0, timezone="America/New_York")
        )
        scenario = ScenarioConfig(name="x", period=_SUMMER, homes=[new_york, _home()])

        assert scenario.window().timezone == "America/New_York"

    @pytest.mark.parametrize(
        "period",
        [
            pytest.param(SimulationPeriod(date(2024, 6, 1), date(2024, 8, 31)), id="dates"),
            pytest.param(_SUMMER_AT_A_TIME_OF_DAY, id="zoned-timestamps-at-a-time-of-day"),
            pytest.param(_SUMMER_AS_NAIVE_TIMESTAMPS, id="naive-timestamps"),
        ],
    )
    def test_a_period_of_dates_or_timestamps_gives_the_window_of_the_same_days_as_iso_strings(
        self, period: SimulationPeriod
    ) -> None:
        assert _bristol_scenario(period).window() == _bristol_scenario(_SUMMER).window()

    def test_a_timestamp_on_another_zones_clock_gives_its_own_date_there_not_its_date_on_the_scenarios(
        self,
    ) -> None:
        assert _bristol_scenario(_SUMMER_LATE_ON_UTCS_CLOCK).window() == SimulationWindow(
            date(2024, 6, 1), date(2024, 8, 31), ONE_MINUTE, "Europe/London"
        )

    def test_with_window_replaces_the_last_day(self) -> None:
        assert _bristol_scenario().with_window(last_day=date(2024, 6, 7)).window().days == 7

    def test_with_window_keeps_the_day_it_is_not_given(self) -> None:
        assert _bristol_scenario().with_window(first_day=date(2024, 7, 1)).window() == SimulationWindow(
            date(2024, 7, 1), date(2024, 8, 31), ONE_MINUTE, "Europe/London"
        )

    def test_with_window_keeps_every_other_field_and_leaves_the_scenario_as_built(self) -> None:
        scenario = ScenarioConfig(
            name="full",
            period=_SUMMER,
            description="every scenario-level field set",
            location=Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester"),
            homes=[_home(), _home()],
            output=OutputConfig(aggregation="daily"),
            seg_tariff_pence_per_kwh=5.0,
            finance=FinanceConfig(standing_charge_pence_per_day=28.0),
        )

        windowed = scenario.with_window(first_day=date(2024, 7, 1), last_day=date(2024, 7, 31))

        assert dataclasses.replace(windowed, period=scenario.period) == scenario
        assert scenario.period == _SUMMER

    def test_with_window_refuses_a_first_day_after_the_last_naming_both_fields(self) -> None:
        with pytest.raises(ConfigurationError, match=_naming("period.start_date", "period.end_date")):
            _bristol_scenario().with_window(first_day=date(2024, 9, 1))

    @pytest.mark.parametrize(
        ("parameter", "day"),
        [
            pytest.param("first_day", datetime(2024, 7, 1), id="first-day-a-datetime"),
            pytest.param("first_day", pd.Timestamp("2024-07-01"), id="first-day-a-timestamp"),
            pytest.param("last_day", datetime(2024, 7, 31), id="last-day-a-datetime"),
            pytest.param("last_day", pd.Timestamp("2024-07-31"), id="last-day-a-timestamp"),
        ],
    )
    def test_with_window_refuses_a_day_that_is_not_exactly_a_date_naming_its_parameter_and_value(
        self, parameter: str, day: date
    ) -> None:
        with pytest.raises(ConfigurationError, match=_naming("'x'", f"with_window's {parameter}", repr(day))):
            _bristol_scenario().with_window(**{parameter: day})

    def test_the_simulation_bounds_are_the_first_and_last_days_local_midnights(self) -> None:
        bounds = _bristol_scenario().simulation_bounds()

        assert bounds == (
            pd.Timestamp("2024-06-01", tz="Europe/London"),
            pd.Timestamp("2024-08-31", tz="Europe/London"),
        )
        assert all(bound.tz is not None for bound in bounds)

    @pytest.mark.parametrize(
        "period",
        [
            pytest.param(_SUMMER_AT_A_TIME_OF_DAY, id="zoned-timestamps-at-a-time-of-day"),
            pytest.param(_SUMMER_AS_NAIVE_TIMESTAMPS, id="naive-timestamps"),
            pytest.param(_SUMMER_LATE_ON_UTCS_CLOCK, id="timestamps-on-another-zones-clock"),
        ],
    )
    def test_a_period_of_timestamps_bounds_at_its_own_dates_midnights_on_the_scenarios_clock(
        self, period: SimulationPeriod
    ) -> None:
        bounds = _bristol_scenario(period).simulation_bounds()

        assert bounds == (
            pd.Timestamp("2024-06-01", tz="Europe/London"),
            pd.Timestamp("2024-08-31", tz="Europe/London"),
        )
        assert [str(bound.tz) for bound in bounds] == ["Europe/London", "Europe/London"]


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

    def test_an_omitted_timezone_and_altitude_are_bristols_and_an_omitted_name_stays_empty(
        self,
    ) -> None:
        """A block that sets only its coordinates is at Bristol's timezone and altitude, with no name."""
        assert parse_location_block({"latitude": 55.95, "longitude": -3.19}) == Location(
            latitude=55.95,
            longitude=-3.19,
            timezone="Europe/London",
            altitude=11.0,
            name="",
        )

    @pytest.mark.parametrize(
        ("block", "missing"),
        [
            pytest.param({"name": "Clifton"}, {"latitude", "longitude"}, id="name-only"),
            pytest.param(
                {"latitude": None, "name": "Clifton"}, {"latitude", "longitude"}, id="null-latitude"
            ),
            pytest.param({"latitude": 50}, {"longitude"}, id="latitude-only"),
            pytest.param({"longitude": -0.1}, {"latitude"}, id="longitude-only"),
            pytest.param({"altitude": 5.0}, {"latitude", "longitude"}, id="altitude-only"),
        ],
    )
    def test_a_block_that_leaves_out_a_coordinate_is_refused_naming_each_missing_one(
        self, block: dict[str, object], missing: set[str]
    ) -> None:
        """A block that sets any key sets both coordinates: each it leaves out or nulls is named by its path, and one it sets is not."""
        with pytest.raises(ConfigurationError) as refused:
            parse_location_block(block)

        assert {
            coordinate
            for coordinate in ("latitude", "longitude")
            if f"location.{coordinate}" in str(refused.value)
        } == missing

    def test_a_coordinate_left_out_is_named_by_the_blocks_path_in_its_file(self) -> None:
        """The refusal names the missing coordinate under *block_path*, the block's path in its file."""
        with pytest.raises(ConfigurationError, match=re.escape("scenarios[1].location.longitude")):
            parse_location_block({"latitude": 50}, block_path="scenarios[1].location")
