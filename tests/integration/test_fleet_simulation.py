"""Integration tests for fleet simulation.

These tests make real PVGIS API calls and may be slow.
VAL-006: Integration test for fleet simulation
"""

import pytest
import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    FleetSummary,
    calculate_fleet_summary,
    simulate_fleet,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


@pytest.mark.slow
@pytest.mark.integration
class TestFleetSimulation:
    """Test VAL-006: Integration test for fleet simulation."""

    @pytest.fixture
    def heterogeneous_fleet_config(self) -> FleetConfig:
        """Create a heterogeneous fleet of 10 homes.

        Mix of:
        - PV sizes: 3-6 kW
        - Battery sizes: None, 5, 10 kWh
        - Consumption: 2500-4500 kWh/year
        """
        return FleetConfig.create_heterogeneous(
            pv_capacities_kw=[3.0, 4.0, 4.0, 5.0, 5.0, 3.5, 4.5, 6.0, 4.0, 5.0],
            battery_capacities_kwh=[None, 5.0, None, 10.0, 5.0, None, 5.0, 10.0, None, 5.0],
            annual_consumptions_kwh=[
                2500.0, 3000.0, 3400.0, 3800.0, 4000.0,
                2800.0, 3200.0, 4500.0, 3100.0, 3600.0
            ],
            location=Location.bristol(),
            name="Test fleet - 10 heterogeneous homes",
        )

    @pytest.fixture
    def uniform_fleet_config(self) -> FleetConfig:
        """Create a uniform fleet of 10 homes."""
        return FleetConfig.create_uniform(
            n_homes=10,
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            name="Test fleet - 10 uniform homes",
        )

    def test_simulates_10_homes_for_7_days(self, heterogeneous_fleet_config):
        """Simulates 10 homes for 7 days successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_fleet(heterogeneous_fleet_config, start, end)

        # Verify 10 homes simulated
        assert len(results) == 10
        assert isinstance(results, FleetResults)

    def test_per_home_results_accessible(self, heterogeneous_fleet_config):
        """Per-home results are accessible by index."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days for speed

        results = simulate_fleet(heterogeneous_fleet_config, start, end)

        # Access each home's results
        for i in range(10):
            home_results = results[i]
            assert len(home_results.generation) == 3 * 1440  # 3 days of minutes
            assert len(home_results.demand) == 3 * 1440
            assert (home_results.generation >= 0).all()
            assert (home_results.demand >= 0).all()

    def test_fleet_aggregates_calculated(self, uniform_fleet_config):
        """Fleet aggregates are calculated correctly."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days for speed

        results = simulate_fleet(uniform_fleet_config, start, end)

        # Verify aggregate properties
        total_gen = results.total_generation
        total_demand = results.total_demand
        total_import = results.total_grid_import
        total_export = results.total_grid_export
        total_self = results.total_self_consumption

        # All should be series with correct length
        expected_len = 2 * 1440
        assert len(total_gen) == expected_len
        assert len(total_demand) == expected_len
        assert len(total_import) == expected_len
        assert len(total_export) == expected_len
        assert len(total_self) == expected_len

        # Aggregates should be sum of individual homes
        manual_total_gen = sum(results[i].generation for i in range(10))
        assert (total_gen == manual_total_gen).all()

    def test_fleet_summary_statistics(self, heterogeneous_fleet_config):
        """Fleet summary statistics are calculated correctly."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_fleet(heterogeneous_fleet_config, start, end)
        summary = calculate_fleet_summary(results)

        assert isinstance(summary, FleetSummary)
        assert summary.n_homes == 10
        assert summary.simulation_days == 7

        # Totals should be positive
        assert summary.total_generation_kwh > 0
        assert summary.total_demand_kwh > 0
        assert summary.total_self_consumption_kwh > 0

        # Ratios should be valid
        assert 0 <= summary.fleet_self_consumption_ratio <= 1
        assert 0 <= summary.fleet_grid_dependency_ratio <= 1

        # Distribution stats make sense
        assert summary.per_home_generation_min_kwh <= summary.per_home_generation_mean_kwh
        assert summary.per_home_generation_mean_kwh <= summary.per_home_generation_max_kwh

    def test_no_errors_or_warnings(self, heterogeneous_fleet_config):
        """Simulation completes without errors."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")

        # This should complete without raising any exceptions
        results = simulate_fleet(
            heterogeneous_fleet_config, start, end, validate_balance=True
        )

        # All homes should have valid results
        for i in range(len(results)):
            home_results = results[i]
            # No NaN values
            assert not home_results.generation.isna().any()
            assert not home_results.demand.isna().any()
            assert not home_results.grid_import.isna().any()
            assert not home_results.grid_export.isna().any()

    def test_aggregate_dataframe_output(self, uniform_fleet_config):
        """Fleet aggregate DataFrame is generated correctly."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        results = simulate_fleet(uniform_fleet_config, start, end)
        df = results.to_aggregate_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1440  # 1 day of minutes
        assert "generation_kw" in df.columns
        assert "demand_kw" in df.columns
        assert "self_consumption_kw" in df.columns
        assert "grid_import_kw" in df.columns
        assert "grid_export_kw" in df.columns

    def test_heterogeneous_configs_preserved(self, heterogeneous_fleet_config):
        """Different home configurations produce different results."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")

        results = simulate_fleet(heterogeneous_fleet_config, start, end)
        summary = calculate_fleet_summary(results)

        # Heterogeneous fleet should have variation in per-home generation
        # (different PV sizes produce different generation)
        assert summary.per_home_generation_min_kwh < summary.per_home_generation_max_kwh

        # Per-home self-consumption ratios should vary
        assert summary.per_home_self_consumption_ratio_min < summary.per_home_self_consumption_ratio_max
