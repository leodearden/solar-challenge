# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a home with a heat pump."""

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.heat_pump import HeatPumpConfig, calculate_cop
from solar_challenge.home import HomeConfig, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from tests._synthetic_weather import sunless_tmy, weather_for


class TestHeatPumpConfig:
    """Test HeatPumpConfig construction — pure config, no simulation."""

    def test_home_config_with_heat_pump(self):
        """HomeConfig can be created with heat pump configuration."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
            name="Home with ASHP",
        )
        assert config.heat_pump_config is not None
        assert config.heat_pump_config.heat_pump_type == "ASHP"
        assert config.heat_pump_config.thermal_capacity_kw == 8.0
        assert config.heat_pump_config.annual_heat_demand_kwh == 8000.0

    def test_heat_pump_optional(self):
        """Heat pump config is optional."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        assert config.heat_pump_config is None


@pytest.fixture
def cold_january15_tmy_weather() -> pd.DataFrame:
    """A dark TMY year whose only heating day is a cold 15 January.

    Every hour of 15 January is below the heat pump's 15.5 °C base temperature, so the heat pump runs all day.
    The night is the coldest part (1 °C from 02:00 to 05:00 UTC),
    the afternoon the warmest (7 °C from 12:00 to 14:00 UTC).
    The rest of the year is 20 °C, so 15 January carries the whole year's heat demand.
    """
    weather = sunless_tmy(temp_air=20.0, wind_speed=3.0)
    weather.loc["1990-01-15", "temp_air"] = [
        2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 5.0, 6.0,
        7.0, 7.0, 7.0, 6.0, 5.0, 4.0, 3.0, 3.0, 2.0, 2.0, 2.0, 2.0,
    ]
    return weather


class TestSimulateHomeAddsHeatPumpLoad:
    """simulate_home adds a heat pump's electrical load, driven by the TMY temperature, to the household demand.

    Synthetic weather, no network.
    """

    def test_heat_pump_load_is_added_to_household_demand_minute_by_minute(self, cold_january15_tmy_weather):
        load_config = LoadConfig(annual_consumption_kwh=3000.0, seed=42)
        heat_pump_home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=load_config,
            heat_pump_config=HeatPumpConfig.default_ashp(),
            location=Location.bristol(),
        )
        household_only_home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=load_config,
            location=Location.bristol(),
        )
        day = pd.Timestamp("2024-01-15")

        with_heat_pump = simulate_home(
            heat_pump_home, day, day, weather=weather_for(heat_pump_home, cold_january15_tmy_weather)
        )
        household_only = simulate_home(
            household_only_home, day, day, weather=weather_for(household_only_home, cold_january15_tmy_weather)
        )

        assert household_only.heat_pump_load is None
        heat_pump_load = with_heat_pump.heat_pump_load
        assert heat_pump_load is not None
        assert (heat_pump_load > 0).all()
        pd.testing.assert_index_equal(heat_pump_load.index, with_heat_pump.demand.index)
        pd.testing.assert_series_equal(with_heat_pump.demand, household_only.demand + heat_pump_load, check_names=False)
        warm_hour_load = heat_pump_load.loc["2024-01-15 13:00":"2024-01-15 13:59"]
        cold_hour_load = heat_pump_load.loc["2024-01-15 03:00":"2024-01-15 03:59"]
        assert warm_hour_load.max() < cold_hour_load.min()


class TestSimulateHomeNamesTheHeatPumpLoad:
    """simulate_home names its heat_pump_load heat_pump_load_kw, the column to_dataframe gives it.

    That holds whether or not the TMY year has any heating, so on both of generate_heat_pump_load's return paths.
    Synthetic weather, no network.
    """

    @pytest.mark.parametrize(
        "temp_air_c",
        [
            pytest.param(10.0, id="heating-year"),
            pytest.param(20.0, id="no-heating-year"),
        ],
    )
    def test_heat_pump_load_is_named_heat_pump_load_kw(self, temp_air_c):
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            heat_pump_config=HeatPumpConfig.default_ashp(),
            location=Location.bristol(),
        )
        day = pd.Timestamp("2024-01-15")

        results = simulate_home(home, day, day, weather=weather_for(home, sunless_tmy(temp_air=temp_air_c, wind_speed=3.0)))

        assert results.heat_pump_load is not None
        assert results.heat_pump_load.name == "heat_pump_load_kw"


@pytest.fixture
def constant_10c_tmy_weather() -> pd.DataFrame:
    """A dark TMY year at a constant 10 °C.

    Every minute is 5.5 °C below the heat pump's 15.5 °C base temperature, so every day of the year needs the same heat.
    """
    return sunless_tmy(temp_air=10.0, wind_speed=3.0)


class TestSimulateHomeSharesTheAnnualHeatDemandOverTheTMYYear:
    """simulate_home shares a heat pump's annual heat demand over the whole TMY year, whatever the run's length.

    Synthetic weather, no network. Delivered heat is recovered from the electrical load as load × COP.
    """

    @pytest.mark.parametrize(
        ("last_day", "days"),
        [
            pytest.param("2025-01-15", 1, id="one-day"),
            pytest.param("2025-01-21", 7, id="one-week"),
        ],
    )
    def test_a_run_delivers_its_days_share_of_the_annual_heat_demand(self, last_day, days, constant_10c_tmy_weather):
        heat_pump = HeatPumpConfig.default_ashp()
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            heat_pump_config=heat_pump,
            location=Location.bristol(),
        )

        results = simulate_home(
            home,
            pd.Timestamp("2025-01-15"),
            pd.Timestamp(last_day),
            weather=weather_for(home, constant_10c_tmy_weather),
        )

        assert results.heat_pump_load is not None
        heat_delivered_kwh = (results.heat_pump_load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(days * heat_pump.annual_heat_demand_kwh / 365)


class TestSimulateHomeRejectsWeatherThatIsNotOneYear:
    """With a heat pump configured, simulate_home needs its weather to be one TMY year of hourly rows.

    That is the year the heat pump's annual heat demand is shared out over. Synthetic weather, no network.
    """

    def test_one_day_of_weather_raises_naming_the_homes_location_and_its_hourly_rows(self):
        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            heat_pump_config=HeatPumpConfig.default_ashp(),
            location=Location.bristol(),
        )
        day = pd.Timestamp("2025-01-15")

        with pytest.raises(ValueError) as refusal:
            simulate_home(home, day, day, weather=weather_for(home, sunless_tmy(temp_air=10.0, wind_speed=3.0).loc["1990-01-15"]))

        named = (repr(home.location), "24 rows", "(8,760 to 8,784)")
        assert [value for value in named if value not in str(refusal.value)] == []


@pytest.fixture
def daylit_cold_january15_tmy_weather(cold_january15_tmy_weather: pd.DataFrame) -> pd.DataFrame:
    """cold_january15_tmy_weather with daylight on 15 January.

    The daylight is an overcast day's, all of it diffuse, so the PV generates on the day the heat pump runs.
    """
    weather = cold_january15_tmy_weather.copy()
    weather.loc["1990-01-15 09:00":"1990-01-15 15:00", ["ghi", "dhi"]] = 100.0
    return weather


class TestHeatPumpIntegration:
    """Test heat pump integration in home simulation: simulate_home on Bristol homes.

    Each run is given daylit_cold_january15_tmy_weather, a synthetic TMY year, as its home's weather. Synthetic weather, no network.
    """

    def test_simulate_home_with_heat_pump_gshp(self, daylit_cold_january15_tmy_weather):
        """simulate_home generates heat pump load for GSHP."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="GSHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        # Simulate one day in winter
        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        # Verify GSHP heat pump load is generated
        assert results.heat_pump_load is not None
        assert len(results.heat_pump_load) == 1440
        assert results.heat_pump_load.min() >= 0.0
        assert results.heat_pump_load.sum() > 0.0

    def test_results_to_dataframe_includes_heat_pump(self, daylit_cold_january15_tmy_weather):
        """SimulationResults.to_dataframe includes heat pump load column."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
            ),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        df = results.to_dataframe()

        # DataFrame should include heat pump load column
        assert "heat_pump_load_kw" in df.columns
        assert len(df) == 1440
        assert df["heat_pump_load_kw"].min() >= 0.0

    def test_results_to_dataframe_without_heat_pump(self, daylit_cold_january15_tmy_weather):
        """SimulationResults.to_dataframe works without heat pump."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        df = results.to_dataframe()

        # DataFrame should not include heat pump load column
        assert "heat_pump_load_kw" not in df.columns
        assert len(df) == 1440

    def test_calculate_summary_with_heat_pump(self, daylit_cold_january15_tmy_weather):
        """calculate_summary computes heat pump metrics."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        summary = calculate_summary(results)

        # Heat pump metrics should be present
        assert summary.total_heat_pump_load_kwh is not None
        assert summary.peak_heat_pump_load_kw is not None
        assert summary.heat_pump_load_ratio is not None

        # Values should be reasonable
        assert summary.total_heat_pump_load_kwh > 0.0
        assert summary.peak_heat_pump_load_kw > 0.0
        assert 0.0 <= summary.heat_pump_load_ratio <= 1.0

        # Heat pump ratio = heat_pump_load / total_demand
        expected_ratio = summary.total_heat_pump_load_kwh / summary.total_demand_kwh
        assert summary.heat_pump_load_ratio == pytest.approx(expected_ratio, rel=0.01)

    def test_calculate_summary_without_heat_pump(self, daylit_cold_january15_tmy_weather):
        """calculate_summary works without heat pump (None values)."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        summary = calculate_summary(results)

        # Heat pump metrics should be None
        assert summary.total_heat_pump_load_kwh is None
        assert summary.peak_heat_pump_load_kw is None
        assert summary.heat_pump_load_ratio is None

    def test_heat_pump_draws_power_on_a_winter_day_and_none_on_a_summer_day(self, daylit_cold_january15_tmy_weather):
        """The run's date picks the TMY day that drives the load: 15 January is below the heat pump's base temperature, 15 July above it."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        # Simulate one day in winter (January)
        winter_results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        # Simulate one day in summer (July)
        summer_results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-07-15"),
            end_date=pd.Timestamp("2024-07-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        assert winter_results.heat_pump_load.sum() > 0.0
        assert summer_results.heat_pump_load.sum() == 0.0

    def test_heat_pump_with_battery(self, daylit_cold_january15_tmy_weather):
        """Heat pump works correctly with battery storage."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            battery_config=BatteryConfig(capacity_kwh=10.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        # Verify all components are working together
        assert results.generation.sum() > 0.0  # PV generation
        assert results.demand.sum() > 0.0  # Total demand (household + heat pump)
        assert results.heat_pump_load is not None
        assert results.heat_pump_load.sum() > 0.0  # Heat pump load
        # Battery may charge or discharge depending on generation/demand
        assert results.battery_soc.max() >= 0.0

    def test_peak_heat_pump_load_is_capacity_over_the_cop_at_the_coldest_hour(self, daylit_cold_january15_tmy_weather):
        """On 15 January the heat pump runs at its thermal capacity all day, so its peak electrical load is that capacity over the COP at the coldest hour."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(config, daylit_cold_january15_tmy_weather),
        )

        coldest_hour_c = daylit_cold_january15_tmy_weather["temp_air"].min()
        assert results.heat_pump_load.max() == pytest.approx(
            config.heat_pump_config.thermal_capacity_kw / calculate_cop("ASHP", coldest_hour_c)
        )
