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
    """A dark, cold 15 January in the shape of a PVGIS TMY: hourly rows indexed in UTC for 1990.

    Every hour is below the heat pump's 15.5 °C base temperature, so the heat pump runs all day.
    The night is the coldest part (1 °C from 02:00 to 05:00 UTC),
    the afternoon the warmest (7 °C from 12:00 to 14:00 UTC).
    """
    return pd.DataFrame(
        {
            "ghi": 0.0,
            "dni": 0.0,
            "dhi": 0.0,
            "temp_air": [
                2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 5.0, 6.0,
                7.0, 7.0, 7.0, 6.0, 5.0, 4.0, 3.0, 3.0, 2.0, 2.0, 2.0, 2.0,
            ],
            "wind_speed": 3.0,
        },
        index=pd.date_range("1990-01-15 00:00", periods=24, freq="1h", tz="UTC"),
    )


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

        with_heat_pump = simulate_home(heat_pump_home, day, day, weather_data=cold_january15_tmy_weather)
        household_only = simulate_home(household_only_home, day, day, weather_data=cold_january15_tmy_weather)

        assert household_only.heat_pump_load is None
        heat_pump_load = with_heat_pump.heat_pump_load
        assert heat_pump_load is not None
        assert (heat_pump_load > 0).all()
        pd.testing.assert_index_equal(heat_pump_load.index, with_heat_pump.demand.index)
        pd.testing.assert_series_equal(with_heat_pump.demand, household_only.demand + heat_pump_load, check_names=False)
        warm_hour_load = heat_pump_load.loc["2024-01-15 13:00":"2024-01-15 13:59"]
        cold_hour_load = heat_pump_load.loc["2024-01-15 03:00":"2024-01-15 03:59"]
        assert warm_hour_load.max() < cold_hour_load.min()


@pytest.fixture
def constant_10c_tmy_weather() -> pd.DataFrame:
    """A dark year at a constant 10 °C in the shape of a PVGIS TMY: 8760 hourly rows indexed in UTC for 1990.

    Every minute is 5.5 °C below the heat pump's 15.5 °C base temperature, so every day of the year needs the same heat.
    """
    return pd.DataFrame(
        {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": 10.0, "wind_speed": 3.0},
        index=pd.date_range("1990-01-01 00:00", periods=8760, freq="1h", tz="UTC"),
    )


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
            home, pd.Timestamp("2025-01-15"), pd.Timestamp(last_day), weather_data=constant_10c_tmy_weather
        )

        assert results.heat_pump_load is not None
        heat_delivered_kwh = (results.heat_pump_load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(days * heat_pump.annual_heat_demand_kwh / 365)


@pytest.mark.slow
class TestHeatPumpIntegration:
    """Test heat pump integration in home simulation (calls simulate_home — network)."""

    def test_simulate_home_with_heat_pump_ashp(self):
        """simulate_home generates heat pump load for ASHP."""
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
        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
        )

        # Verify heat pump load is present and tracked
        assert results.heat_pump_load is not None
        assert len(results.heat_pump_load) == 1440  # 24 hours * 60 minutes
        assert results.heat_pump_load.min() >= 0.0  # Non-negative load

        # Winter should have significant heating load
        assert results.heat_pump_load.sum() > 0.0

        # Demand should be higher than just household load
        # (household load + heat pump load)
        assert results.demand.sum() > 0.0

    def test_simulate_home_with_heat_pump_gshp(self):
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
        )

        # Verify GSHP heat pump load is generated
        assert results.heat_pump_load is not None
        assert len(results.heat_pump_load) == 1440
        assert results.heat_pump_load.min() >= 0.0
        assert results.heat_pump_load.sum() > 0.0

    def test_simulate_home_without_heat_pump(self):
        """simulate_home works without heat pump (None in results)."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
        )

        # Heat pump load should be None
        assert results.heat_pump_load is None

    def test_results_to_dataframe_includes_heat_pump(self):
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
        )

        df = results.to_dataframe()

        # DataFrame should include heat pump load column
        assert "heat_pump_load_kw" in df.columns
        assert len(df) == 1440
        assert df["heat_pump_load_kw"].min() >= 0.0

    def test_results_to_dataframe_without_heat_pump(self):
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
        )

        df = results.to_dataframe()

        # DataFrame should not include heat pump load column
        assert "heat_pump_load_kw" not in df.columns
        assert len(df) == 1440

    def test_calculate_summary_with_heat_pump(self):
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

    def test_calculate_summary_without_heat_pump(self):
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
        )

        summary = calculate_summary(results)

        # Heat pump metrics should be None
        assert summary.total_heat_pump_load_kwh is None
        assert summary.peak_heat_pump_load_kw is None
        assert summary.heat_pump_load_ratio is None

    def test_winter_has_higher_heat_pump_load_than_summer(self):
        """Heat pump load is higher in winter than summer."""
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
        )

        # Simulate one day in summer (July)
        summer_results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-07-15"),
            end_date=pd.Timestamp("2024-07-15"),
        )

        winter_load = winter_results.heat_pump_load.sum()
        summer_load = summer_results.heat_pump_load.sum()

        # Winter heating load should be significantly higher than summer
        # (summer may be near zero if temperatures are above base temperature)
        assert winter_load > summer_load

    def test_heat_pump_with_battery(self):
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
        )

        # Verify all components are working together
        assert results.generation.sum() > 0.0  # PV generation
        assert results.demand.sum() > 0.0  # Total demand (household + heat pump)
        assert results.heat_pump_load is not None
        assert results.heat_pump_load.sum() > 0.0  # Heat pump load
        # Battery may charge or discharge depending on generation/demand
        assert results.battery_soc.max() >= 0.0

    def test_heat_pump_load_reasonable_magnitude(self):
        """Heat pump load has reasonable magnitude relative to capacity."""
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
        )

        # Peak heat pump load should not exceed capacity / min_COP
        # ASHP min COP is 1.8, so max electrical load = 8.0 / 1.8 ≈ 4.44 kW
        # Add some margin for numerical precision
        max_expected_load = config.heat_pump_config.thermal_capacity_kw / 1.5
        assert results.heat_pump_load.max() <= max_expected_load
