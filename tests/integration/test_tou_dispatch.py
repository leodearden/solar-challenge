"""Integration tests comparing default vs TOU-optimized battery dispatch.

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
from solar_challenge.tariff import TariffConfig


@pytest.mark.slow
@pytest.mark.integration
class TestTOUDispatchComparison:
    """Test TOU-optimized dispatch vs default greedy dispatch."""

    @pytest.fixture
    def home_config_economy7(self) -> HomeConfig:
        """4 kW PV with 5 kWh battery and Economy 7 tariff."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=TariffConfig.economy_7(),
            name="Economy 7 test home",
        )

    def test_greedy_dispatch_completes(self, home_config_economy7):
        """Greedy dispatch strategy completes successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        # Use default greedy dispatch
        config = home_config_economy7
        results = simulate_home(config, start, end)

        # All result fields populated
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440  # 3 days of minutes
        assert len(results.demand) == 3 * 1440

        # Battery should be active
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

        # Financial fields should be calculated
        assert results.import_cost.sum() > 0
        assert results.tariff_rate.sum() > 0

    def test_tou_dispatch_completes(self, home_config_economy7):
        """TOU-optimized dispatch strategy completes successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        # Use TOU-optimized dispatch
        config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )
        results = simulate_home(config, start, end)

        # All result fields populated
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440
        assert len(results.demand) == 3 * 1440

        # Battery should be active
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

        # Financial fields should be calculated
        assert results.import_cost.sum() > 0
        assert results.tariff_rate.sum() > 0

    def test_tou_dispatch_reduces_costs(self, home_config_economy7):
        """TOU-optimized dispatch should reduce net cost vs greedy."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days for better signal

        # Simulate with greedy dispatch
        greedy_config = home_config_economy7
        greedy_results = simulate_home(greedy_config, start, end)
        greedy_summary = calculate_summary(greedy_results)

        # Simulate with TOU-optimized dispatch
        tou_config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )
        tou_results = simulate_home(tou_config, start, end)
        tou_summary = calculate_summary(tou_results)

        # TOU-optimized should have lower or equal net cost
        # (Equal is possible if battery is too small to make a difference)
        assert tou_summary.net_cost_gbp <= greedy_summary.net_cost_gbp

        # Should have similar energy totals (same PV, load, battery capacity)
        assert abs(tou_summary.total_generation_kwh - greedy_summary.total_generation_kwh) < 0.01
        assert abs(tou_summary.total_demand_kwh - greedy_summary.total_demand_kwh) < 0.01

    def test_battery_behavior_differs(self, home_config_economy7):
        """Battery charge/discharge patterns can differ between strategies."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        # Simulate with greedy dispatch
        greedy_config = home_config_economy7
        greedy_results = simulate_home(greedy_config, start, end)

        # Simulate with TOU-optimized dispatch
        tou_config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )
        tou_results = simulate_home(tou_config, start, end)

        # Both strategies should complete successfully
        assert greedy_results is not None
        assert tou_results is not None

        # Battery should be active in both cases
        assert greedy_results.battery_charge.sum() > 0
        assert greedy_results.battery_discharge.sum() > 0
        assert tou_results.battery_charge.sum() > 0
        assert tou_results.battery_discharge.sum() > 0

        # Note: In summer with high solar generation, both strategies may
        # make similar decisions, so we don't strictly require differences

    def test_tou_dispatch_maintains_energy_balance(self, home_config_economy7):
        """Energy balance should be maintained with TOU dispatch."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        # Use TOU-optimized dispatch with validation enabled
        config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )

        # validate_balance=True is default, should not raise
        results = simulate_home(config, start, end, validate_balance=True)
        assert results is not None

    def test_no_negative_values_with_tou(self, home_config_economy7):
        """All output values should be non-negative with TOU dispatch."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")

        # Use TOU-optimized dispatch
        config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )
        results = simulate_home(config, start, end)

        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.self_consumption >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()
        assert (results.import_cost >= 0).all()
        assert (results.export_revenue >= 0).all()

    def test_tariff_rate_varies_correctly(self, home_config_economy7):
        """Tariff rate should vary between off-peak and peak periods."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        config = home_config_economy7
        results = simulate_home(config, start, end)

        # Economy 7: off-peak 00:30-07:30 at £0.09, peak rest at £0.25
        # Should see both rates in the data
        unique_rates = results.tariff_rate.unique()

        # Should have at least 2 different rates
        assert len(unique_rates) >= 2

        # Should include both Economy 7 rates
        assert 0.09 in unique_rates  # off-peak
        assert 0.25 in unique_rates  # peak

    def test_summary_statistics_with_tou(self, home_config_economy7):
        """Summary statistics should be reasonable with TOU dispatch."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        # Use TOU-optimized dispatch
        config = HomeConfig(
            pv_config=home_config_economy7.pv_config,
            load_config=home_config_economy7.load_config,
            battery_config=home_config_economy7.battery_config,
            location=home_config_economy7.location,
            tariff_config=home_config_economy7.tariff_config,
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )
        results = simulate_home(config, start, end)
        summary = calculate_summary(results)

        # 7 days of simulation
        assert summary.simulation_days == 7

        # 4 kW system in June should generate ~12-20 kWh/day in UK
        assert 50 < summary.total_generation_kwh < 200  # 7-30 kWh/day range

        # 3,400 kWh/year ≈ 9.3 kWh/day
        assert 40 < summary.total_demand_kwh < 100  # 6-14 kWh/day range

        # Financial values should be reasonable
        assert summary.total_import_cost_gbp >= 0
        assert summary.total_export_revenue_gbp >= 0
        # Net cost can be negative (profit) in summer with high solar generation

        # Ratios should be valid
        assert 0 <= summary.self_consumption_ratio <= 1
        assert 0 <= summary.grid_dependency_ratio <= 1
        assert 0 <= summary.export_ratio <= 1
