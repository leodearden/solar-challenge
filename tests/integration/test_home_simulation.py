"""Integration tests for single home simulation.

These tests make real PVGIS API calls and may be slow.
"""

import pytest
import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    calculate_summary,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


@pytest.mark.slow
@pytest.mark.integration
class TestSingleHomeSimulation:
    """Test VAL-005: Integration test for single home simulation."""

    @pytest.fixture
    def pv_only_config(self) -> HomeConfig:
        """4 kW PV-only home configuration."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=None,
            location=Location.bristol(),
            name="PV-only test home",
        )

    @pytest.fixture
    def pv_battery_config(self) -> HomeConfig:
        """4 kW PV with 5 kWh battery home configuration."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            name="PV+battery test home",
        )

    def test_simulates_7_days_pv_only(self, pv_only_config):
        """Simulates PV-only home for 7 days successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_home(pv_only_config, start, end)

        # All result fields populated
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 7 * 1440  # 7 days of minutes
        assert len(results.demand) == 7 * 1440
        assert len(results.self_consumption) == 7 * 1440
        assert len(results.grid_import) == 7 * 1440
        assert len(results.grid_export) == 7 * 1440

        # Battery fields present but zeroed (no battery)
        assert (results.battery_charge == 0).all()
        assert (results.battery_discharge == 0).all()
        assert (results.battery_soc == 0).all()

    def test_simulates_7_days_with_battery(self, pv_battery_config):
        """Simulates home with battery for 7 days successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")

        results = simulate_home(pv_battery_config, start, end)

        # All result fields populated
        assert len(results.generation) == 7 * 1440
        assert len(results.demand) == 7 * 1440

        # Battery should be active
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0
        assert results.battery_soc.max() > 0

    def test_energy_balance_validates(self, pv_battery_config):
        """Energy balance validates throughout simulation."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days to keep fast

        # validate_balance=True is default, should not raise
        results = simulate_home(pv_battery_config, start, end, validate_balance=True)
        assert results is not None

    def test_no_negative_values(self, pv_battery_config):
        """All output values are non-negative."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")

        results = simulate_home(pv_battery_config, start, end)

        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.self_consumption >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()

    def test_summary_statistics_reasonable(self, pv_battery_config):
        """Summary statistics are in reasonable ranges."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")

        results = simulate_home(pv_battery_config, start, end)
        summary = calculate_summary(results)

        # 7 days of simulation
        assert summary.simulation_days == 7

        # 4 kW system in June should generate ~12-20 kWh/day in UK
        assert 50 < summary.total_generation_kwh < 200  # 7-30 kWh/day range

        # 3,400 kWh/year ≈ 9.3 kWh/day, with June low factor
        assert 40 < summary.total_demand_kwh < 100  # 6-14 kWh/day range

        # Ratios should be valid
        assert 0 <= summary.self_consumption_ratio <= 1
        assert 0 <= summary.grid_dependency_ratio <= 1
        assert 0 <= summary.export_ratio <= 1

    def test_dataframe_conversion(self, pv_only_config):
        """Results can be converted to DataFrame."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        results = simulate_home(pv_only_config, start, end)
        df = results.to_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1440  # 1 day of minutes
        assert "generation_kw" in df.columns
        assert "demand_kw" in df.columns
        assert isinstance(df.index, pd.DatetimeIndex)
