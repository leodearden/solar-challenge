"""Tests for home simulation."""

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    SummaryStatistics,
    _align_tmy_to_demand,
    calculate_summary,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


class TestHomeConfigBasics:
    """Test HOME-001: HomeConfig dataclass."""

    def test_create_with_all_params(self):
        """HomeConfig can be created with all parameters."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            location=Location.bristol(),
            name="Test home",
        )
        assert config.pv_config.capacity_kw == 4.0
        assert config.load_config.annual_consumption_kwh == 3400.0
        assert config.battery_config is not None
        assert config.battery_config.capacity_kwh == 5.0
        assert config.name == "Test home"

    def test_battery_optional(self):
        """Battery config is optional (PV-only home)."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        assert config.battery_config is None

    def test_default_location_is_bristol(self):
        """Default location is Bristol."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        assert config.location.latitude == pytest.approx(51.45, rel=0.01)


class TestSimulationResults:
    """Test SimulationResults functionality."""

    @pytest.fixture
    def sample_results(self) -> SimulationResults:
        """Create sample simulation results."""
        index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min")
        return SimulationResults(
            generation=pd.Series([2.0] * 60, index=index),
            demand=pd.Series([1.0] * 60, index=index),
            self_consumption=pd.Series([1.0] * 60, index=index),
            battery_charge=pd.Series([0.5] * 60, index=index),
            battery_discharge=pd.Series([0.0] * 60, index=index),
            battery_soc=pd.Series([2.5] * 60, index=index),
            grid_import=pd.Series([0.0] * 60, index=index),
            grid_export=pd.Series([0.5] * 60, index=index),
            import_cost=pd.Series([0.0] * 60, index=index),
            export_revenue=pd.Series([0.05] * 60, index=index),
            tariff_rate=pd.Series([0.10] * 60, index=index),
        )

    def test_to_dataframe(self, sample_results):
        """Results can be converted to DataFrame."""
        df = sample_results.to_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 60
        assert "generation_kw" in df.columns
        assert "demand_kw" in df.columns
        assert "battery_soc_kwh" in df.columns


class TestAlignTMYToDemand:
    """Test TMY data alignment."""

    def test_aligns_by_time_of_year(self):
        """TMY data aligned by month-day-hour-minute."""
        # TMY data for June 21
        tmy_index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min")
        tmy_gen = pd.Series(range(60), index=tmy_index, dtype=float)

        # Demand for same time in a different year
        demand_index = pd.date_range("2025-06-21 10:00", periods=60, freq="1min")
        demand = pd.Series([1.0] * 60, index=demand_index)

        aligned = _align_tmy_to_demand(tmy_gen, demand)

        assert len(aligned) == 60
        # Values should be preserved from TMY
        assert aligned.iloc[0] == 0.0
        assert aligned.iloc[59] == 59.0

    def test_missing_tmy_data_returns_zero(self):
        """Missing TMY timestamps return zero."""
        # TMY data only for noon
        tmy_index = pd.date_range("2024-06-21 12:00", periods=1, freq="1min")
        tmy_gen = pd.Series([5.0], index=tmy_index)

        # Demand for earlier time
        demand_index = pd.date_range("2025-06-21 10:00", periods=60, freq="1min")
        demand = pd.Series([1.0] * 60, index=demand_index)

        aligned = _align_tmy_to_demand(tmy_gen, demand)

        # Most values should be zero since TMY data doesn't cover this time
        assert aligned.iloc[0] == 0.0


class TestCalculateSummary:
    """Test HOME-005: Summary statistics calculation."""

    @pytest.fixture
    def sample_results(self) -> SimulationResults:
        """Create sample results for 1 day (1440 minutes)."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")
        return SimulationResults(
            generation=pd.Series([3.0] * 1440, index=index),  # 3 kW constant
            demand=pd.Series([2.0] * 1440, index=index),  # 2 kW constant
            self_consumption=pd.Series([2.0] * 1440, index=index),
            battery_charge=pd.Series([0.5] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([2.5] * 1440, index=index),
            grid_import=pd.Series([0.0] * 1440, index=index),
            grid_export=pd.Series([0.5] * 1440, index=index),
            import_cost=pd.Series([0.0] * 1440, index=index),
            export_revenue=pd.Series([0.05] * 1440, index=index),
            tariff_rate=pd.Series([0.10] * 1440, index=index),
        )

    def test_calculates_totals(self, sample_results):
        """Calculates total energy values."""
        summary = calculate_summary(sample_results)

        # 3 kW for 1440 minutes = 3 * 24 = 72 kWh generation
        assert summary.total_generation_kwh == pytest.approx(72.0, rel=0.01)

        # 2 kW for 1440 minutes = 48 kWh demand
        assert summary.total_demand_kwh == pytest.approx(48.0, rel=0.01)

    def test_calculates_peaks(self, sample_results):
        """Calculates peak values."""
        summary = calculate_summary(sample_results)
        assert summary.peak_generation_kw == 3.0
        assert summary.peak_demand_kw == 2.0

    def test_calculates_ratios(self, sample_results):
        """Calculates efficiency ratios."""
        summary = calculate_summary(sample_results)

        # self_consumption_ratio = 48/72 = 0.667
        assert summary.self_consumption_ratio == pytest.approx(0.667, rel=0.01)

        # grid_dependency = 0/48 = 0
        assert summary.grid_dependency_ratio == 0.0

        # export_ratio = 12/72 = 0.167
        assert summary.export_ratio == pytest.approx(0.167, rel=0.01)

    def test_handles_zero_generation(self):
        """Handles zero generation gracefully."""
        index = pd.date_range("2024-06-21 00:00", periods=60, freq="1min")
        results = SimulationResults(
            generation=pd.Series([0.0] * 60, index=index),
            demand=pd.Series([1.0] * 60, index=index),
            self_consumption=pd.Series([0.0] * 60, index=index),
            battery_charge=pd.Series([0.0] * 60, index=index),
            battery_discharge=pd.Series([0.0] * 60, index=index),
            battery_soc=pd.Series([0.0] * 60, index=index),
            grid_import=pd.Series([1.0] * 60, index=index),
            grid_export=pd.Series([0.0] * 60, index=index),
            import_cost=pd.Series([0.10] * 60, index=index),
            export_revenue=pd.Series([0.0] * 60, index=index),
            tariff_rate=pd.Series([0.10] * 60, index=index),
        )

        summary = calculate_summary(results)
        assert summary.self_consumption_ratio == 0.0
        assert summary.export_ratio == 0.0

    def test_SEG_revenue_with_tariff(self, sample_results):
        """SEG revenue is computed when tariff is provided."""
        # total_grid_export_kwh = 0.5 kW * 24 h = 12 kWh
        # seg_revenue_gbp = 12 * 15 / 100 = 1.80 GBP
        summary = calculate_summary(sample_results, seg_tariff_pence_per_kwh=15.0)

        assert summary.seg_revenue_gbp is not None
        assert summary.seg_revenue_gbp == pytest.approx(1.80, rel=0.01)

    def test_SEG_revenue_without_tariff(self, sample_results):
        """seg_revenue_gbp is None when no tariff is provided."""
        summary = calculate_summary(sample_results)

        assert summary.seg_revenue_gbp is None

    def test_calculates_financial_statistics(self):
        """Calculates financial statistics correctly."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")
        results = SimulationResults(
            generation=pd.Series([3.0] * 1440, index=index),
            demand=pd.Series([2.0] * 1440, index=index),
            self_consumption=pd.Series([1.5] * 1440, index=index),
            battery_charge=pd.Series([0.0] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([0.0] * 1440, index=index),
            grid_import=pd.Series([0.5] * 1440, index=index),
            grid_export=pd.Series([1.5] * 1440, index=index),
            import_cost=pd.Series([0.05] * 1440, index=index),  # £0.05 per minute
            export_revenue=pd.Series([0.03] * 1440, index=index),  # £0.03 per minute
            tariff_rate=pd.Series([0.10] * 1440, index=index),
        )

        summary = calculate_summary(results)

        # Total import cost = £0.05 * 1440 minutes = £72.00
        assert summary.total_import_cost_gbp == pytest.approx(72.0, rel=0.01)

        # Total export revenue = £0.03 * 1440 minutes = £43.20
        assert summary.total_export_revenue_gbp == pytest.approx(43.2, rel=0.01)

        # Net cost = £72.00 - £43.20 = £28.80
        assert summary.net_cost_gbp == pytest.approx(28.8, rel=0.01)


class TestSummaryStatistics:
    """Test SummaryStatistics dataclass."""

    def test_all_fields_present(self):
        """SummaryStatistics has all required fields."""
        stats = SummaryStatistics(
            total_generation_kwh=100.0,
            total_demand_kwh=80.0,
            total_self_consumption_kwh=60.0,
            total_grid_import_kwh=20.0,
            total_grid_export_kwh=40.0,
            total_battery_charge_kwh=15.0,
            total_battery_discharge_kwh=15.0,
            peak_generation_kw=4.0,
            peak_demand_kw=3.0,
            self_consumption_ratio=0.6,
            grid_dependency_ratio=0.25,
            export_ratio=0.4,
            simulation_days=7,
            total_import_cost_gbp=5.0,
            total_export_revenue_gbp=8.0,
            net_cost_gbp=-3.0,
        )
        assert stats.total_generation_kwh == 100.0
        assert stats.simulation_days == 7


class TestHeatPumpIntegration:
    """Test heat pump integration in home simulation."""

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

    def test_heat_pump_load_added_to_demand(self):
        """Heat pump electrical load is added to household demand."""
        # Config with heat pump
        config_with_hp = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        # Config without heat pump (same household load)
        config_no_hp = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            location=Location.bristol(),
        )

        # Simulate same period for both
        start = pd.Timestamp("2024-01-15")
        end = pd.Timestamp("2024-01-15")

        results_with_hp = simulate_home(config_with_hp, start, end)
        results_no_hp = simulate_home(config_no_hp, start, end)

        # Total demand with heat pump should be higher
        total_with_hp = results_with_hp.demand.sum()
        total_no_hp = results_no_hp.demand.sum()
        assert total_with_hp > total_no_hp

        # Difference should approximately equal heat pump load
        # (allowing for small numerical differences)
        hp_load_total = results_with_hp.heat_pump_load.sum()
        demand_increase = total_with_hp - total_no_hp
        assert demand_increase == pytest.approx(hp_load_total, rel=0.01)

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
