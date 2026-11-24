# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a scenario file's top level, from the raw YAML or JSON read to the ScenarioConfig that load_scenarios builds."""

import dataclasses
import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.config import (
    ScenarioConfig,
    load_community_config,
    load_config,
    load_config_json,
    load_config_yaml,
    load_fleet_config,
    load_home_config,
    load_scenario,
    load_scenarios,
    parse_scenario,
    period_day,
    period_window,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import GridServicesBand
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import parse_location_block
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, ONE_MINUTE, SimulationWindow
from tests._flex_band_refusal import flex_band_refusal


def _window(first_day: date, last_day: date, timezone: str | None = "Europe/London") -> SimulationWindow:
    """The one-minute window from *first_day* to *last_day* on *timezone*'s clock."""
    return SimulationWindow(first_day, last_day, ONE_MINUTE, timezone)


_FIRST_WEEK = _window(date(2024, 1, 1), date(2024, 1, 7))
"""The first week of 2024 on London's clock."""

_SUMMER = _window(date(2024, 6, 1), date(2024, 8, 31))
"""June to August 2024 on London's clock."""

_NEW_YORK = Location(latitude=40.71, longitude=-74.0, timezone="America/New_York")


def _home() -> HomeConfig:
    """A 4 kW home on the default load, carrying no SEG tariff of its own."""
    return HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())


def _new_york_home() -> HomeConfig:
    """_home() in New York."""
    return dataclasses.replace(_home(), location=_NEW_YORK)


def _scenario(
    *,
    home: HomeConfig | None = None,
    homes: list[HomeConfig] | None = None,
    seg_tariff_pence_per_kwh: float | None = None,
) -> ScenarioConfig:
    """Scenario 'x' over the first week of 2024, holding *home* or *homes* under *seg_tariff_pence_per_kwh*."""
    return ScenarioConfig(
        name="x",
        period=_FIRST_WEEK,
        home=home,
        homes=homes or [],
        seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh,
    )


def _bristol_scenario(period: SimulationWindow = _SUMMER) -> ScenarioConfig:
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
            period=_FIRST_WEEK,
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
            period=_FIRST_WEEK,
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
            period=_FIRST_WEEK,
            homes=[h1, h2],
        )
        single = ScenarioConfig(
            name="Single",
            period=_FIRST_WEEK,
            home=h1,
        )

        assert isinstance(fleet.homes, tuple)
        assert fleet.homes == (h1, h2)
        assert single.homes == ()

    def test_refuses_a_field_assignment(self) -> None:
        """A scenario is a frozen value: assigning one of its fields raises FrozenInstanceError."""
        scenario = ScenarioConfig(
            name="Test",
            period=_FIRST_WEEK,
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
                period=_FIRST_WEEK,
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
                period=_FIRST_WEEK,
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
            period=_FIRST_WEEK,
            home=home,
        )
        loc = scenario.get_location()
        assert loc.latitude == pytest.approx(51.45, abs=0.01)

    @pytest.mark.parametrize("field", ["output", "tariff_config"])
    def test_takes_no_output_or_tariff_config(self, field: str) -> None:
        with pytest.raises(TypeError, match=f"unexpected keyword argument '{field}'"):
            ScenarioConfig(
                name="x", period=_FIRST_WEEK, home=_home(), **{field: None}
            )

    def test_holds_a_flex_band_as_the_band_it_names(self) -> None:
        scenario = ScenarioConfig(name="x", period=_FIRST_WEEK, home=_home(), flex_band="high")

        assert scenario.flex_band is GridServicesBand.HIGH

    def test_has_no_flex_band_unless_given_one(self) -> None:
        assert ScenarioConfig(name="x", period=_FIRST_WEEK, home=_home()).flex_band is None

    def test_a_flex_band_naming_no_band_is_refused_naming_the_scenario_and_flex_band(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            ScenarioConfig(name="x", period=_FIRST_WEEK, home=_home(), flex_band="medium")

        assert "Scenario 'x' flex_band" in str(refused.value)
        assert "'medium'" in str(refused.value)


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
    """Construction is the one point that refuses a SEG rate SEGTariff refuses, a home's own SEG rate other than the scenario's, and a period that is not a one-minute window on the scenario's clock."""

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

    @pytest.mark.parametrize(
        ("period", "type_name"),
        [
            pytest.param((date(2024, 1, 1), date(2024, 1, 7)), "tuple", id="a-pair-of-dates"),
            pytest.param("2024-01-01", "str", id="a-string"),
        ],
    )
    def test_a_period_that_is_not_a_window_is_refused_naming_the_scenario_and_its_type(
        self, period: object, type_name: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=_naming("'x'", "period", type_name)):
            ScenarioConfig(name="x", period=period, home=_home())

    def test_a_period_at_another_cadence_is_refused_naming_its_cadence_and_one_minute(self) -> None:
        quarter_hourly = dataclasses.replace(_SUMMER, cadence=timedelta(minutes=15))

        with pytest.raises(
            ConfigurationError,
            match=_naming("'x'", "period.cadence", repr(timedelta(minutes=15)), repr(ONE_MINUTE)),
        ):
            _bristol_scenario(quarter_hourly)

    @pytest.mark.parametrize(
        ("window_zone", "location", "first_home", "scenario_zone"),
        [
            pytest.param(
                "America/New_York", Location.bristol(), _home(), "Europe/London", id="another-zone-than-the-location"
            ),
            pytest.param(
                "Europe/London", None, _new_york_home(), "America/New_York", id="another-zone-than-the-first-homes"
            ),
            pytest.param(None, Location.bristol(), _home(), "Europe/London", id="no-zone"),
        ],
    )
    def test_a_period_on_another_clock_than_the_scenarios_is_refused_naming_both_zones(
        self, window_zone: str | None, location: Location | None, first_home: HomeConfig, scenario_zone: str
    ) -> None:
        period = _window(date(2024, 6, 1), date(2024, 8, 31), window_zone)

        with pytest.raises(
            ConfigurationError,
            match=_naming("'x'", "period.timezone", repr(window_zone), repr(scenario_zone)),
        ):
            ScenarioConfig(name="x", period=period, location=location, homes=[first_home, _home()])

    def test_replace_re_runs_the_period_check(self) -> None:
        with pytest.raises(ConfigurationError, match=_naming("'x'", "period.timezone")):
            dataclasses.replace(
                _bristol_scenario(), period=_window(date(2024, 6, 1), date(2024, 8, 31), "America/New_York")
            )

    def test_a_one_day_window_constructs_and_is_held_as_given(self) -> None:
        period = _window(date(2024, 6, 21), date(2024, 6, 21))

        assert ScenarioConfig(name="x", period=period, home=_home()).period is period


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
            period=_FIRST_WEEK,
            description="every scenario-level field set",
            location=Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester"),
            homes=[_home(), _home()],
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
    """window(), with_window() and simulation_bounds() read the scenario's period, the window it simulates."""

    def test_the_window_is_the_period_itself(self) -> None:
        scenario = _bristol_scenario()

        assert scenario.window() == _SUMMER
        assert scenario.window() is scenario.period

    def test_with_no_scenario_location_the_window_is_on_the_first_homes_clock(self) -> None:
        scenario = ScenarioConfig(
            name="x",
            period=_window(date(2024, 6, 1), date(2024, 8, 31), "America/New_York"),
            homes=[_new_york_home(), _home()],
        )

        assert scenario.window().timezone == "America/New_York"

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
            seg_tariff_pence_per_kwh=5.0,
            finance=FinanceConfig(standing_charge_pence_per_day=28.0),
        )

        windowed = scenario.with_window(first_day=date(2024, 7, 1), last_day=date(2024, 7, 31))

        assert dataclasses.replace(windowed, period=scenario.period) == scenario
        assert scenario.period == _SUMMER

    def test_with_window_refuses_a_first_day_after_the_last_naming_its_argument_and_the_windows_reason(
        self,
    ) -> None:
        with pytest.raises(
            ConfigurationError, match=_naming("'x'", "first_day=datetime.date(2024, 9, 1)", "is before first_day")
        ):
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
        with pytest.raises(ConfigurationError, match=_naming("'x'", "with_window", f"{parameter}={day!r}")):
            _bristol_scenario().with_window(**{parameter: day})

    def test_the_simulation_bounds_are_the_first_and_last_days_local_midnights(self) -> None:
        bounds = _bristol_scenario().simulation_bounds()

        assert bounds == (
            pd.Timestamp("2024-06-01", tz="Europe/London"),
            pd.Timestamp("2024-08-31", tz="Europe/London"),
        )
        assert all(bound.tz is not None for bound in bounds)


class TestPeriodReaders:
    """period_day reads one day of a period and period_window both, as a scenario file's period is read, each refusal naming the day's block path."""

    def test_a_period_of_iso_days_is_the_one_minute_window_of_those_days_on_the_zone_given(self) -> None:
        assert period_window("2024-06-01", "2024-08-31", timezone="Europe/London") == SimulationWindow(
            date(2024, 6, 1), date(2024, 8, 31), ONE_MINUTE, "Europe/London"
        )

    def test_the_window_is_on_the_zone_given(self) -> None:
        assert period_window("2024-06-01", "2024-08-31", timezone="America/New_York") == SimulationWindow(
            date(2024, 6, 1), date(2024, 8, 31), ONE_MINUTE, "America/New_York"
        )

    @pytest.mark.parametrize(
        ("start_date", "end_date"),
        [
            pytest.param(date(2024, 6, 1), date(2024, 8, 31), id="dates-as-unquoted-yaml-gives"),
            pytest.param(
                pd.Timestamp("2024-06-01 06:00", tz="Europe/London"),
                pd.Timestamp("2024-08-31 18:00", tz="Europe/London"),
                id="zoned-timestamps-at-a-time-of-day",
            ),
            pytest.param(pd.Timestamp("2024-06-01"), pd.Timestamp("2024-08-31"), id="naive-timestamps"),
            pytest.param(
                pd.Timestamp("2024-06-01 23:30", tz="UTC"),
                pd.Timestamp("2024-08-31 23:30", tz="UTC"),
                id="timestamps-late-on-utcs-clock",
            ),
        ],
    )
    def test_dates_or_timestamps_give_the_window_of_their_own_dates_on_their_own_clock(
        self, start_date: object, end_date: object
    ) -> None:
        assert period_window(start_date, end_date, timezone="Europe/London") == SimulationWindow(
            date(2024, 6, 1), date(2024, 8, 31), ONE_MINUTE, "Europe/London"
        )

    @pytest.mark.parametrize(
        "start_date",
        [
            pytest.param("2024", id="a-year"),
            pytest.param("2024-02-30", id="a-day-its-month-lacks"),
            pytest.param("20240601", id="an-iso-basic-date"),
            pytest.param(pd.NaT, id="not-a-time"),
        ],
    )
    def test_a_start_day_that_is_not_a_day_is_refused_naming_its_path_and_value(self, start_date: object) -> None:
        with pytest.raises(ConfigurationError, match=_naming("period.start_date", repr(start_date))):
            period_window(start_date, "2024-06-07", timezone="Europe/London")

    def test_a_day_that_is_not_a_day_is_refused_after_its_path(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            period_window("2024", "2024-01-07", timezone="Europe/London")

        assert str(refusal.value) == (
            "period.start_date: '2024' is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp"
        )

    def test_an_end_day_that_is_not_a_day_is_refused_by_its_own_path(self) -> None:
        with pytest.raises(ConfigurationError, match=_naming("period.end_date", "'2024'")):
            period_window("2024-01-01", "2024", timezone="Europe/London")

    def test_the_refusal_names_the_block_path_given(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            period_window("2024", "2024-01-07", timezone="Europe/London", block_path="scenarios[0].period")

        assert str(refusal.value) == (
            "scenarios[0].period.start_date: '2024' is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp"
        )

    def test_a_last_day_before_the_first_is_refused_naming_both_from_the_windows_refusal(self) -> None:
        with pytest.raises(
            ConfigurationError,
            match=_naming("period.start_date", "2024-08-31", "period.end_date", "2024-06-01"),
        ) as refusal:
            period_window("2024-08-31", "2024-06-01", timezone="Europe/London")

        assert type(refusal.value.__cause__) is ValueError

    def test_period_day_reads_a_date_as_it_is(self) -> None:
        assert period_day(date(2024, 6, 1), "period.start_date") == date(2024, 6, 1)

    def test_period_day_names_the_path_it_is_given(self) -> None:
        with pytest.raises(ConfigurationError, match=r"^a\.b: 'x' is not a day"):
            period_day("x", "a.b")


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


_WEEK = {"start_date": "2024-01-01", "end_date": "2024-01-07"}
_A_HOME = {"pv": {"capacity_kw": 4.0}}


def _refusal_loading(tmp_path: Path, load: Callable[[Path], object], document: object, suffix: str = ".json") -> str:
    """The message of the ConfigurationError *load* raises reading *document*, written as JSON to a file with *suffix*."""
    path = tmp_path / f"document{suffix}"
    path.write_text(json.dumps(document))
    with pytest.raises(ConfigurationError) as refusal:
        load(path)
    return str(refusal.value)


def _scenarios_loaded(tmp_path: Path, document: object) -> list[ScenarioConfig]:
    """The scenarios load_scenarios reads from *document*, written as JSON."""
    path = tmp_path / "document.json"
    path.write_text(json.dumps(document))
    return load_scenarios(path)


_ECONOMY_7 = {"type": "economy_7"}
_FLAT_RATE = {"type": "flat_rate", "rate_per_kwh": 0.25}
_TWO_HOME_DISTRIBUTION = {"n_homes": 2, "pv": {"capacity_kw": 4.0}}
_NEW_YORK_BLOCK = {"latitude": 40.71, "longitude": -74.0, "timezone": "America/New_York"}


def _parse_refusal(document: object, *, block_path: str = "") -> str:
    """The message of the ConfigurationError parse_scenario raises reading *document* at *block_path*."""
    with pytest.raises(ConfigurationError) as refusal:
        parse_scenario(document, block_path=block_path)
    return str(refusal.value)


class TestParseScenario:
    """parse_scenario reads one scenario mapping: its scenario-level blocks, then exactly one homes source, each home given the scenario's location and tariff."""

    def test_an_absent_name_and_description_read_as_empty(self) -> None:
        scenario = parse_scenario({"home": _A_HOME})

        assert (scenario.name, scenario.description) == ("", "")

    def test_a_name_that_is_not_a_string_is_refused_naming_it(self) -> None:
        assert _parse_refusal({"name": 7, "home": _A_HOME}).startswith("name: must be a string")

    @pytest.mark.parametrize(
        ("location", "timezone"),
        [pytest.param(None, "Europe/London", id="bristol"), pytest.param(_NEW_YORK_BLOCK, "America/New_York", id="new-york")],
    )
    @pytest.mark.parametrize("period", [pytest.param({}, id="absent"), pytest.param({"period": None}, id="null")])
    def test_with_no_period_the_window_is_the_default_days_on_the_locations_clock(
        self, location: dict[str, object] | None, timezone: str, period: dict[str, object]
    ) -> None:
        scenario = parse_scenario({"location": location, **period, "home": _A_HOME})

        assert scenario.window() == SimulationWindow(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, ONE_MINUTE, timezone)

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param({"home": _A_HOME}, id="home"),
            pytest.param({"homes": [_A_HOME, {}]}, id="homes"),
            pytest.param({"fleet_distribution": _TWO_HOME_DISTRIBUTION}, id="fleet_distribution"),
        ],
    )
    def test_the_top_level_tariff_and_location_reach_every_home(self, source: dict[str, object]) -> None:
        scenario = parse_scenario({"location": _NEW_YORK_BLOCK, "tariff": _ECONOMY_7, **source})

        assert scenario.location == parse_location_block(_NEW_YORK_BLOCK)
        assert scenario.simulated_homes()
        for home in scenario.simulated_homes():
            assert home.tariff_config == TariffConfig.economy_7()
            assert home.location == scenario.location

    @pytest.mark.parametrize(
        ("block_path", "prefix"),
        [pytest.param("", "homes[0].tariff: ", id="bare"), pytest.param("scenarios[2]", "scenarios[2].homes[0].tariff: ", id="scenarios")],
    )
    def test_a_home_whose_own_tariff_differs_is_refused_naming_its_tariff_and_the_top_level_one(
        self, block_path: str, prefix: str
    ) -> None:
        document = {"tariff": _ECONOMY_7, "homes": [{"tariff": _FLAT_RATE}]}

        message = _parse_refusal(document, block_path=block_path)

        assert message.startswith(prefix)
        assert "tariff:" in message.removeprefix(prefix)

    def test_the_seg_rate_reaches_every_simulated_home_and_the_stored_homes_keep_none(self) -> None:
        scenario = parse_scenario({"seg": {"rate_pence_per_kwh": 15.0}, "homes": [_A_HOME, {}]})

        assert scenario.seg_tariff_pence_per_kwh == 15.0
        assert [home.seg_tariff for home in scenario.simulated_homes()] == [SEGTariff("", 15.0)] * 2
        assert [home.seg_tariff for home in scenario.homes] == [None, None]

    @pytest.mark.parametrize(
        ("value", "band"),
        [
            pytest.param("central", GridServicesBand.CENTRAL, id="central"),
            pytest.param("Central", GridServicesBand.CENTRAL, id="any-case"),
            pytest.param(None, None, id="null"),
        ],
    )
    def test_a_flex_band_reads_as_the_band_it_names(self, value: object, band: GridServicesBand | None) -> None:
        assert parse_scenario({"flex_band": value, "home": _A_HOME}).flex_band is band

    @pytest.mark.parametrize(
        ("block_path", "what"), [pytest.param("", "flex_band", id="bare"), pytest.param("scenarios[2]", "scenarios[2].flex_band", id="scenarios")]
    )
    @pytest.mark.parametrize("value", [pytest.param(1, id="a-number"), pytest.param("Medium", id="a-word-in-any-case")])
    def test_a_flex_band_naming_no_band_is_refused_as_the_band_refuses_it_as_written(
        self, block_path: str, what: str, value: object
    ) -> None:
        assert _parse_refusal({"flex_band": value, "home": _A_HOME}, block_path=block_path) == flex_band_refusal(value, what)

    def test_a_community_block_is_recognised_and_reaches_no_home(self) -> None:
        scenario = parse_scenario({"community": {"sharing_mode": "p2p"}, "home": _A_HOME})

        assert scenario.simulated_homes() == parse_scenario({"home": _A_HOME}).simulated_homes()

    @pytest.mark.parametrize(
        ("sources", "refusal"),
        [
            pytest.param(
                {"home": _A_HOME, "homes": [_A_HOME]},
                "the top level: sets 'home', 'homes', but a scenario's homes come from exactly one of "
                "'home', 'homes', 'fleet_distribution'",
                id="home-and-homes",
            ),
            pytest.param(
                {"home": _A_HOME, "homes": [_A_HOME], "fleet_distribution": _TWO_HOME_DISTRIBUTION},
                "the top level: sets 'home', 'homes', 'fleet_distribution', but a scenario's homes come "
                "from exactly one of 'home', 'homes', 'fleet_distribution'",
                id="all-three",
            ),
            pytest.param(
                {"homes": [_A_HOME], "fleet_distribution": None},
                "the top level: sets 'homes', 'fleet_distribution', but a scenario's homes come from "
                "exactly one of 'home', 'homes', 'fleet_distribution'",
                id="a-null-source-beside-another",
            ),
            pytest.param(
                {},
                "the top level: requires the scenario's homes, from exactly one of 'home', 'homes', 'fleet_distribution'",
                id="none",
            ),
        ],
    )
    def test_a_scenario_must_give_exactly_one_homes_source(self, sources: dict[str, object], refusal: str) -> None:
        assert _parse_refusal({"name": "a", **sources}) == refusal

    @pytest.mark.parametrize(
        ("source", "refusal"),
        [
            pytest.param("home", "home: must be a mapping, got NoneType", id="home"),
            pytest.param("homes", "homes: must be a list, got NoneType", id="homes"),
            pytest.param("fleet_distribution", "fleet_distribution: must be a mapping, got NoneType", id="fleet_distribution"),
        ],
    )
    def test_a_null_homes_source_is_refused_by_its_reader(self, source: str, refusal: str) -> None:
        assert _parse_refusal({source: None}) == refusal

    def test_an_empty_homes_list_is_refused(self) -> None:
        assert _parse_refusal({"homes": []}) == "homes: must list at least one home"

    @pytest.mark.parametrize(
        ("document", "refused_on"),
        [
            pytest.param({"name": 7, "location": {"lat": 1.0}, "home": _A_HOME}, "name: must be a string", id="name-before-location"),
            pytest.param(
                {"description": 7, "period": {"start_date": "2024-06-01"}, "home": _A_HOME},
                "description: must be a string",
                id="description-before-period",
            ),
            pytest.param({"location": {"lat": 1.0}, "tariff": {"type": "economy_8"}, "home": _A_HOME}, "location: ", id="location-before-tariff"),
            pytest.param(
                {"tariff": {"type": "economy_8"}, "fleet_distribution": {**_TWO_HOME_DISTRIBUTION, "n_homez": 2}},
                "tariff.type: ",
                id="tariff-before-fleet_distribution",
            ),
            pytest.param({"flex_band": 1, "homes": 5}, "flex_band must be ", id="flex_band-before-homes"),
            pytest.param({"flex_band": 1, "home": _A_HOME, "homes": [_A_HOME]}, "flex_band must be ", id="flex_band-before-the-homes-source"),
        ],
    )
    def test_blocks_are_read_in_order_and_the_first_bad_one_is_refused(self, document: dict[str, object], refused_on: str) -> None:
        assert _parse_refusal(document).startswith(refused_on)


_JUNE_WEEK = {"start_date": "2024-06-01", "end_date": "2024-06-07"}
_ONE_GRAMMAR_BLOCKS = {
    "location": _NEW_YORK_BLOCK,
    "period": _JUNE_WEEK,
    "tariff": _ECONOMY_7,
    "seg": {"rate_pence_per_kwh": 15.0},
}
"""The scenario-level blocks every document form below carries."""


class TestEveryDocumentFormReadsThroughOneGrammar:
    """R1: every document form, and every homes source, gives its homes the same scenario-level blocks."""

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({**_ONE_GRAMMAR_BLOCKS, "home": _A_HOME}, id="home"),
            pytest.param({**_ONE_GRAMMAR_BLOCKS, "homes": [_A_HOME, {}]}, id="homes"),
            pytest.param({**_ONE_GRAMMAR_BLOCKS, "fleet_distribution": _TWO_HOME_DISTRIBUTION}, id="fleet_distribution"),
            pytest.param({"scenario": {**_ONE_GRAMMAR_BLOCKS, "home": _A_HOME}}, id="scenario"),
            pytest.param(
                {
                    "scenarios": [
                        {**_ONE_GRAMMAR_BLOCKS, "homes": [_A_HOME, {}]},
                        {**_ONE_GRAMMAR_BLOCKS, "fleet_distribution": _TWO_HOME_DISTRIBUTION},
                    ]
                },
                id="scenarios",
            ),
        ],
    )
    def test_every_simulated_home_gets_the_location_tariff_and_seg_rate_over_the_period(
        self, tmp_path: Path, document: dict[str, object]
    ) -> None:
        scenarios = _scenarios_loaded(tmp_path, document)

        location = parse_location_block(_NEW_YORK_BLOCK)
        for scenario in scenarios:
            assert scenario.window() == _window(date(2024, 6, 1), date(2024, 6, 7), "America/New_York")
            assert scenario.simulated_homes()
            for home in scenario.simulated_homes():
                assert (home.location, home.tariff_config, home.seg_tariff) == (
                    location,
                    TariffConfig.economy_7(),
                    SEGTariff("", 15.0),
                )

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"name": "a", **_ONE_GRAMMAR_BLOCKS, "home": _A_HOME}, id="bare"),
            pytest.param({"scenario": {"name": "a", **_ONE_GRAMMAR_BLOCKS, "home": _A_HOME}}, id="scenario"),
        ],
    )
    def test_load_scenario_reads_a_bare_or_wrapped_scenario(self, tmp_path: Path, document: dict[str, object]) -> None:
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps(document))

        assert load_scenario(path) == parse_scenario({"name": "a", **_ONE_GRAMMAR_BLOCKS, "home": _A_HOME})

    def test_load_scenario_refuses_a_file_of_several_scenarios_naming_how_many(self, tmp_path: Path) -> None:
        document = {"scenarios": [{"home": _A_HOME}, {"home": _A_HOME}]}

        message = _refusal_loading(tmp_path, load_scenario, document)

        assert message.startswith("scenarios: ")
        assert "2" in message

    @pytest.mark.parametrize(
        ("load", "document"),
        [
            pytest.param(load_scenario, {"name": "a", "scenario": {"home": _A_HOME}}, id="load_scenario-scenario"),
            pytest.param(load_scenarios, {"name": "a", "scenario": {"home": _A_HOME}}, id="load_scenarios-scenario"),
            pytest.param(load_scenarios, {"name": "a", "scenarios": [{"home": _A_HOME}]}, id="load_scenarios-scenarios"),
        ],
    )
    def test_a_wrapper_beside_another_top_level_key_is_refused_naming_that_key(
        self, tmp_path: Path, load: Callable[[Path], object], document: dict[str, object]
    ) -> None:
        message = _refusal_loading(tmp_path, load, document)

        assert message.startswith("the top level: unrecognised keys 'name'")


class TestAScenarioDocumentNamesTheBlockItRefuses:
    """Each refusal load_scenarios writes for a scenario document reads '<block label>: <problem>'."""

    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            pytest.param(
                {"scenarios": [{"name": "a", "period": {"start_date": "2024-01-01"}, "home": {}}]},
                "scenarios[0].period: requires 'end_date'",
                id="R4-a-period-without-its-end",
            ),
            pytest.param(
                {"scenario": {"name": "a", "period": {}, "home": _A_HOME}},
                "scenario.period: requires 'start_date', 'end_date'",
                id="a-period-with-neither-day",
            ),
            pytest.param(
                {"scenario": {"name": "a", "period": _WEEK}},
                "scenario: requires the scenario's homes, from exactly one of 'home', 'homes', 'fleet_distribution'",
                id="no-homes-source",
            ),
            pytest.param(
                {"scenario": {"name": "a", "period": _WEEK, "homes": 5}},
                "scenario.homes: must be a list, got int",
                id="R2-homes-a-number",
            ),
            pytest.param({"scenarios": 5}, "scenarios: must be a list, got int", id="R2-scenarios-a-number"),
            pytest.param(
                {"scenarios": [{"name": "a", "period": {**_WEEK, "start_date": "2024"}, "home": _A_HOME}]},
                "scenarios[0].period.start_date: '2024' is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp",
                id="P10-a-period-day-that-is-not-a-day",
            ),
        ],
    )
    def test_the_refusal_names_the_block(self, tmp_path: Path, document: dict, expected: str) -> None:
        assert _refusal_loading(tmp_path, load_scenarios, document) == expected

    def test_a_period_whose_last_day_precedes_its_first_is_refused_naming_both_days_paths(self, tmp_path: Path) -> None:
        reversed_period = {"start_date": "2024-08-31", "end_date": "2024-06-01"}
        document = {"scenario": {"name": "a", "period": reversed_period, "home": _A_HOME}}

        assert re.search(
            _naming("scenario.period.start_date", "2024-08-31", "scenario.period.end_date", "2024-06-01"),
            _refusal_loading(tmp_path, load_scenarios, document),
        )


class TestAScenarioDocumentsPeriod:
    """load_scenarios reads a document's period as the one-minute window of its days on the scenario location's clock."""

    @pytest.mark.parametrize(
        ("document", "name", "period"),
        [
            pytest.param({"scenarios": [{"period": _WEEK, "home": _A_HOME}]}, "", _FIRST_WEEK, id="no-name"),
            pytest.param(
                {"scenario": {"name": "a", "home": _A_HOME}},
                "a",
                _window(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY),
                id="no-period",
            ),
            pytest.param(
                {"scenarios": [{"home": _A_HOME}]}, "", _window(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY), id="neither"
            ),
            pytest.param(
                {"name": "a", "home": _A_HOME}, "a", _window(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY), id="the-bare-form"
            ),
        ],
    )
    def test_a_document_without_a_name_or_period_reads_as_unnamed_over_the_default_days(
        self, tmp_path: Path, document: dict[str, object], name: str, period: SimulationWindow
    ) -> None:
        (scenario,) = _scenarios_loaded(tmp_path, document)

        assert (scenario.name, scenario.period) == (name, period)

    def test_a_document_with_no_location_simulates_on_bristols_clock(self, tmp_path: Path) -> None:
        (scenario,) = _scenarios_loaded(tmp_path, {"name": "a", "period": _WEEK, "home": _A_HOME})

        assert scenario.period == _FIRST_WEEK

    def test_the_window_is_on_the_documents_location_clock(self, tmp_path: Path) -> None:
        location = {"latitude": 40.71, "longitude": -74.0, "timezone": "America/New_York"}

        (scenario,) = _scenarios_loaded(
            tmp_path, {"name": "a", "location": location, "period": _WEEK, "home": _A_HOME}
        )

        assert scenario.period == _window(date(2024, 1, 1), date(2024, 1, 7), "America/New_York")

    def test_unquoted_yaml_dates_read_as_the_same_window_as_quoted_ones(self, tmp_path: Path) -> None:
        def loaded(start_date: str, end_date: str) -> ScenarioConfig:
            path = tmp_path / "scenario.yaml"
            path.write_text(
                "name: a\n"
                f"period:\n  start_date: {start_date}\n  end_date: {end_date}\n"
                "home:\n  pv:\n    capacity_kw: 4.0\n"
            )
            (scenario,) = load_scenarios(path)
            return scenario

        assert loaded("2024-06-01", "2024-08-31").period == loaded('"2024-06-01"', '"2024-08-31"').period == _SUMMER


class TestEveryLoaderRefusesADocumentThatIsNoMapping:
    """R3: a document is a mapping of blocks, so a file holding a list or a scalar is refused naming the top level, never an AttributeError or an empty community."""

    @pytest.mark.parametrize(
        ("load", "suffix"),
        [
            pytest.param(load_config_yaml, ".yaml", id="load_config_yaml"),
            pytest.param(load_config_json, ".json", id="load_config_json"),
            pytest.param(load_scenarios, ".yaml", id="load_scenarios"),
            pytest.param(load_home_config, ".yaml", id="load_home_config"),
            pytest.param(load_fleet_config, ".yaml", id="load_fleet_config"),
            pytest.param(load_community_config, ".yaml", id="load_community_config"),
        ],
    )
    @pytest.mark.parametrize(
        ("document", "type_name"),
        [pytest.param(["a", "b"], "list", id="a-list"), pytest.param("a", "str", id="a-string")],
    )
    def test_the_document_is_refused_naming_the_top_level_and_its_type(
        self, tmp_path: Path, load: Callable[[Path], object], suffix: str, document: object, type_name: str
    ) -> None:
        assert _refusal_loading(tmp_path, load, document, suffix) == f"the top level: must be a mapping, got {type_name}"


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
        """A block that sets any key sets both coordinates: each it leaves out or nulls is named, and one it sets is not."""
        with pytest.raises(ConfigurationError) as refused:
            parse_location_block(block)

        required = ", ".join(repr(coordinate) for coordinate in ("latitude", "longitude") if coordinate in missing)
        assert str(refused.value) == f"location: requires {required}"

    def test_a_coordinate_left_out_is_named_by_the_blocks_path_in_its_file(self) -> None:
        """The refusal names the block by *block_path*, its path in its file, and the coordinate it leaves out."""
        with pytest.raises(ConfigurationError, match=re.escape("scenarios[1].location: requires 'longitude'")):
            parse_location_block({"latitude": 50}, block_path="scenarios[1].location")
