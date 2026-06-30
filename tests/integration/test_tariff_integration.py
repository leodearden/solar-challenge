"""Integration tests for Economy 7 tariff support.

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
class TestEconomy7TariffIntegration:
    """Test comprehensive Economy 7 tariff integration."""

    @pytest.fixture
    def flat_rate_config(self) -> HomeConfig:
        """4 kW PV with 5 kWh battery and flat-rate tariff."""
        from solar_challenge.tariff import TariffPeriod

        # Create a proper 24-hour period that crosses midnight to cover all times
        flat_period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",  # Crosses midnight to cover full day
            rate_per_kwh=0.20,
            name="All day"
        )
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=TariffConfig(periods=(flat_period,), name="Flat rate £0.20/kWh"),
            name="Flat-rate home",
        )

    @pytest.fixture
    def economy7_config(self) -> HomeConfig:
        """4 kW PV with 5 kWh battery and Economy 7 tariff."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=TariffConfig.economy_7(
                off_peak_rate=0.09,
                peak_rate=0.25,
            ),
            name="Economy 7 home",
        )

    @pytest.fixture
    def pv_only_economy7_config(self) -> HomeConfig:
        """4 kW PV-only with Economy 7 tariff."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=None,
            location=Location.bristol(),
            tariff_config=TariffConfig.economy_7(),
            name="PV-only Economy 7 home",
        )

    def test_economy7_simulation_completes(self, economy7_config):
        """Economy 7 tariff simulation completes successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_home(economy7_config, start, end)

        # All result fields populated
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 7 * 1440  # 7 days of minutes
        assert len(results.demand) == 7 * 1440
        assert len(results.tariff_rate) == 7 * 1440

        # Battery should be active
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

    def test_tariff_rates_match_economy7(self, economy7_config):
        """Tariff rates correctly match Economy 7 periods."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_home(economy7_config, start, end)

        # Economy 7 default: off-peak 00:30-07:30
        off_peak_times = results.tariff_rate.index[
            (results.tariff_rate.index.time >= pd.Timestamp("00:30").time()) &
            (results.tariff_rate.index.time < pd.Timestamp("07:30").time())
        ]
        peak_times = results.tariff_rate.index[
            ~results.tariff_rate.index.isin(off_peak_times)
        ]

        # Check off-peak rates
        assert (results.tariff_rate.loc[off_peak_times] == 0.09).all()
        # Check peak rates
        assert (results.tariff_rate.loc[peak_times] == 0.25).all()

        # Both rates should be present
        unique_rates = results.tariff_rate.unique()
        assert len(unique_rates) == 2
        assert 0.09 in unique_rates
        assert 0.25 in unique_rates

    def test_import_costs_calculated(self, economy7_config):
        """Import costs are calculated with Economy 7 rates."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results = simulate_home(economy7_config, start, end)

        # Import costs should be non-negative
        assert (results.import_cost >= 0).all()

        # Total import cost should be positive (grid imports expected)
        assert results.import_cost.sum() > 0

        # Costs should match grid imports * tariff rates
        expected_costs = results.grid_import * results.tariff_rate
        # Note: import_cost is in £, grid_import is in kW for 1-min timestep
        # Cost = Power(kW) * Time(hours) * Rate(£/kWh)
        # For 1-minute: Cost = Power * (1/60) * Rate
        expected_costs = results.grid_import * results.tariff_rate / 60
        pd.testing.assert_series_equal(
            results.import_cost,
            expected_costs,
            check_names=False,
        )

    def test_export_revenue_calculated(self, economy7_config):
        """Without seg_tariff, export_revenue is zero (never priced at import rate)."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        with pytest.warns(UserWarning, match="seg_tariff"):
            results = simulate_home(economy7_config, start, end)

        # Export revenue should be non-negative
        assert (results.export_revenue >= 0).all()

        # Without a SEG tariff, export revenue must be zero at every timestep.
        assert (results.export_revenue == 0).all()
        assert calculate_summary(results).total_export_revenue_gbp == 0

    def test_summary_financial_totals(self, economy7_config):
        """Summary statistics include correct financial totals."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_home(economy7_config, start, end)
        summary = calculate_summary(results)

        # Financial totals should match sum of time series
        assert summary.total_import_cost_gbp == pytest.approx(
            results.import_cost.sum(),
            rel=1e-6
        )
        assert summary.total_export_revenue_gbp == pytest.approx(
            results.export_revenue.sum(),
            rel=1e-6
        )
        assert summary.net_cost_gbp == pytest.approx(
            summary.total_import_cost_gbp - summary.total_export_revenue_gbp,
            rel=1e-6
        )

        # Net cost should be reasonable
        assert -20 < summary.net_cost_gbp < 20  # £-3 to £3 per day for 7 days

    def test_economy7_vs_flat_rate_comparison(self, economy7_config, flat_rate_config):
        """Economy 7 vs flat-rate cost comparison."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        # Simulate with both tariffs
        economy7_results = simulate_home(economy7_config, start, end)
        flat_results = simulate_home(flat_rate_config, start, end)

        # Calculate summaries
        economy7_summary = calculate_summary(economy7_results)
        flat_summary = calculate_summary(flat_results)

        # Energy totals should be identical (same PV, load, battery)
        assert economy7_summary.total_generation_kwh == pytest.approx(
            flat_summary.total_generation_kwh,
            rel=1e-6
        )
        assert economy7_summary.total_demand_kwh == pytest.approx(
            flat_summary.total_demand_kwh,
            rel=1e-6
        )

        # Costs will differ based on when consumption happens
        # Both should be reasonable
        assert economy7_summary.total_import_cost_gbp > 0
        assert flat_summary.total_import_cost_gbp > 0

        # Without SEG tariff, export revenue is zero for both configs.
        assert economy7_summary.total_export_revenue_gbp == 0
        assert flat_summary.total_export_revenue_gbp == 0

    def test_pv_only_with_economy7(self, pv_only_economy7_config):
        """PV-only system works with Economy 7 tariff."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days

        results = simulate_home(pv_only_economy7_config, start, end)

        # Simulation completes successfully
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 7 * 1440

        # No battery activity
        assert (results.battery_charge == 0).all()
        assert (results.battery_discharge == 0).all()
        assert (results.battery_soc == 0).all()

        # Tariff rates should still vary
        unique_rates = results.tariff_rate.unique()
        assert len(unique_rates) == 2
        assert 0.09 in unique_rates
        assert 0.25 in unique_rates

        # Import costs should be calculated
        assert results.import_cost.sum() > 0

    def test_dataframe_includes_tariff_columns(self, economy7_config):
        """Results DataFrame includes tariff-related columns."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_home(economy7_config, start, end)
        df = results.to_dataframe()

        # Tariff columns should be present
        assert "tariff_rate_per_kwh" in df.columns
        assert "import_cost_gbp" in df.columns
        assert "export_revenue_gbp" in df.columns

        # All columns should have same length
        assert len(df) == 1440  # 1 day of minutes
        assert all(len(df[col]) == 1440 for col in df.columns)

    def test_winter_period_costs(self, economy7_config):
        """Economy 7 costs in winter period (higher consumption)."""
        start = pd.Timestamp("2024-01-15")
        end = pd.Timestamp("2024-01-21")  # 7 days in winter

        results = simulate_home(economy7_config, start, end)
        summary = calculate_summary(results)

        # Winter should have lower generation, higher imports
        assert summary.total_generation_kwh > 0  # Some generation even in winter
        assert summary.total_import_cost_gbp > 0

        # Grid dependency should be high in winter
        assert summary.grid_dependency_ratio > 0.5

        # Net cost should be positive (paying for electricity)
        # Winter typically has negative economics without enough solar
        assert summary.net_cost_gbp > 0

    def test_summer_period_revenue(self, economy7_config):
        """Economy 7 revenue in summer period (high exports)."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-27")  # 7 days in summer

        results = simulate_home(economy7_config, start, end)
        summary = calculate_summary(results)

        # Summer should have high generation
        assert summary.total_generation_kwh > 50  # Good generation in June

        # Without SEG tariff, export revenue is zero (energy is still exported,
        # but there is no rate configured to value it).
        assert summary.total_export_revenue_gbp == 0

        # Export ratio should be reasonable (energy-based, unaffected by revenue fix)
        assert summary.export_ratio > 0.1

        # Net cost may be negative (earning money) in summer
        # This is normal for well-sized solar systems

    def test_no_tariff_fallback(self):
        """Simulation works without tariff config (fallback to zero costs)."""
        config = HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=None,  # No tariff
            name="No tariff home",
        )

        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        results = simulate_home(config, start, end)

        # Should complete successfully
        assert isinstance(results, SimulationResults)

        # All costs should be zero
        assert (results.import_cost == 0).all()
        assert (results.export_revenue == 0).all()
        assert (results.tariff_rate == 0).all()

        # Summary should show zero costs
        summary = calculate_summary(results)
        assert summary.total_import_cost_gbp == 0
        assert summary.total_export_revenue_gbp == 0
        assert summary.net_cost_gbp == 0

    def test_custom_economy7_times(self):
        """Custom Economy 7 off-peak times work correctly."""
        config = HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=TariffConfig.economy_7(
                off_peak_rate=0.08,
                peak_rate=0.28,
                off_peak_start="01:00",
                off_peak_end="08:00",
            ),
            name="Custom Economy 7 home",
        )

        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_home(config, start, end)

        # Check custom off-peak times (01:00-08:00)
        off_peak_times = results.tariff_rate.index[
            (results.tariff_rate.index.time >= pd.Timestamp("01:00").time()) &
            (results.tariff_rate.index.time < pd.Timestamp("08:00").time())
        ]
        peak_times = results.tariff_rate.index[
            ~results.tariff_rate.index.isin(off_peak_times)
        ]

        # Check custom rates
        assert (results.tariff_rate.loc[off_peak_times] == 0.08).all()
        assert (results.tariff_rate.loc[peak_times] == 0.28).all()

    def test_energy_balance_with_tariff(self, economy7_config):
        """Energy balance validates with Economy 7 tariff."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        # validate_balance=True is default, should not raise
        results = simulate_home(economy7_config, start, end, validate_balance=True)
        assert results is not None

        # All values should be non-negative
        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.self_consumption >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()
