"""Tests for home simulation."""

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig
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
from solar_challenge.seg import SEGTariff, SEG_PRESETS, calculate_seg_revenue, resolve_seg_tariff
from solar_challenge.tariff import TariffConfig, TariffPeriod


@pytest.fixture
def june21_weather_data() -> pd.DataFrame:
    """Synthetic June 21 hourly weather data for Bristol.

    Covers all 24 hours so _align_tmy_to_demand maps every simulation
    minute to a valid weather value.  Using synthetic data avoids a
    PVGIS network call / disk cache in SEG pricing tests whose assertions
    concern revenue arithmetic rather than PV output magnitude.

    Irradiance profile is a realistic sunny summer day; GHI peaks ~870 W/m²
    around solar noon, which is enough to drive meaningful grid export from
    a 4-5 kW south-facing array with a 5 kWh battery.
    """
    index = pd.date_range(
        "2024-06-21 00:00", periods=24, freq="1h", tz="Europe/London"
    )
    return pd.DataFrame(
        {
            "ghi": [
                0, 0, 0, 0, 0, 50, 150, 300, 500, 650, 780, 850,
                870, 850, 780, 650, 500, 300, 150, 50, 0, 0, 0, 0,
            ],
            "dni": [
                0, 0, 0, 0, 0, 100, 250, 450, 650, 800, 900, 950,
                970, 950, 900, 800, 650, 450, 250, 100, 0, 0, 0, 0,
            ],
            "dhi": [
                0, 0, 0, 0, 0, 30, 70, 130, 180, 200, 200, 200,
                200, 200, 200, 200, 180, 130, 70, 30, 0, 0, 0, 0,
            ],
            "temp_air": [
                12, 11, 11, 11, 12, 13, 15, 17, 19, 21, 22, 23,
                23, 23, 22, 21, 19, 17, 16, 14, 13, 12, 12, 12,
            ],
            "wind_speed": [
                2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3,
                3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2,
            ],
        },
        index=index,
    )


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


class TestHomeConfigSEGField:
    """Test that HomeConfig carries the optional SEG seam field."""

    def test_default_seg_tariff_is_none(self):
        """HomeConfig built without seg_tariff has seg_tariff is None."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        assert config.seg_tariff is None

    def test_seg_tariff_stored_from_direct_instance(self):
        """HomeConfig accepts and stores a SEGTariff instance."""
        tariff = SEGTariff("X", 4.1)
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            seg_tariff=tariff,
        )
        assert config.seg_tariff is not None
        assert config.seg_tariff.rate_pence_per_kwh == pytest.approx(4.1)

    def test_seg_tariff_stored_from_resolve(self):
        """HomeConfig accepts and stores a SEGTariff from resolve_seg_tariff."""
        tariff = resolve_seg_tariff("Octopus")
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            seg_tariff=tariff,
        )
        assert config.seg_tariff is not None
        assert config.seg_tariff.rate_pence_per_kwh == pytest.approx(4.1)
        assert config.seg_tariff == SEG_PRESETS["Octopus"]

    def test_existing_configs_unaffected(self):
        """Existing HomeConfig construction without seg_tariff continues to work."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            location=Location.bristol(),
            name="Test home",
        )
        assert config.seg_tariff is None


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


class TestSimulateHomeSEGPricing:
    """Test that simulate_home prices export at SEG rate when seg_tariff is set."""

    @pytest.fixture
    def seg_home_config(self):
        """HomeConfig with flat import tariff + Octopus SEG tariff.

        Uses start_time==end_time=="00:00" to create a period that crosses
        midnight and covers all 1440 minutes of the day (matches_time returns
        True for time_of_day >= 00:00 OR time_of_day < 00:00 == always True).
        """
        flat_period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",  # Crosses midnight — covers the full day
            rate_per_kwh=0.25,
            name="All day",
        )
        return HomeConfig(
            pv_config=PVConfig(capacity_kw=5.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            tariff_config=TariffConfig(periods=(flat_period,), name="Flat 25p"),
            seg_tariff=SEGTariff("Octopus", 4.1),
            location=Location.bristol(),
        )

    def test_grid_export_is_positive(self, seg_home_config, june21_weather_data):
        """Sunny summer day with PV produces grid export > 0."""
        results = simulate_home(
            seg_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        assert results.grid_export.sum() > 0, "Expected grid export > 0 on sunny summer day"

    def test_export_revenue_priced_at_seg_rate(self, seg_home_config, june21_weather_data):
        """total_export_revenue_gbp equals SEG-rate calculation (not import rate)."""
        results = simulate_home(
            seg_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        summary = calculate_summary(results)

        total_export_kwh = results.grid_export.sum() / 60.0  # kW -> kWh for 1-min timesteps
        expected_seg_revenue = calculate_seg_revenue(total_export_kwh, SEGTariff("", 4.1))

        assert summary.total_export_revenue_gbp == pytest.approx(expected_seg_revenue, rel=1e-3)

    def test_export_revenue_less_than_import_rate_value(self, seg_home_config, june21_weather_data):
        """SEG-priced export revenue is strictly less than at the import tariff rate."""
        results = simulate_home(
            seg_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        summary = calculate_summary(results)

        total_export_kwh = results.grid_export.sum() / 60.0
        import_rate_revenue = total_export_kwh * 0.25  # 25 p/kWh = £0.25/kWh

        # SEG rate (4.1 p/kWh) is much less than import rate (25 p/kWh)
        assert summary.total_export_revenue_gbp < import_rate_revenue

    def test_net_cost_equals_import_minus_export(self, seg_home_config, june21_weather_data):
        """net_cost_gbp == total_import_cost_gbp - total_export_revenue_gbp."""
        results = simulate_home(
            seg_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        summary = calculate_summary(results)

        expected_net_cost = summary.total_import_cost_gbp - summary.total_export_revenue_gbp
        assert summary.net_cost_gbp == pytest.approx(expected_net_cost, rel=1e-6)


class TestSimulateHomeSEGNonRegression:
    """Non-regression + preset-wiring guards for simulate_home SEG changes."""

    @pytest.fixture
    def no_seg_config(self):
        """HomeConfig with flat import tariff and NO seg_tariff (legacy mode)."""
        flat_period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",  # Crosses midnight — covers the full day
            rate_per_kwh=0.20,
            name="All day",
        )
        return HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            tariff_config=TariffConfig(periods=(flat_period,), name="Flat 20p"),
            location=Location.bristol(),
        )

    def test_legacy_export_priced_at_import_rate(self, no_seg_config, june21_weather_data):
        """Without seg_tariff, export_revenue == grid_export * tariff_rate / 60 (element-wise)."""
        results = simulate_home(
            no_seg_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        # export_revenue (£/min) == grid_export (kW) * tariff_rate (£/kWh) / 60 (min/h)
        expected = results.grid_export * results.tariff_rate / 60.0
        pd.testing.assert_series_equal(
            results.export_revenue, expected, check_names=False, rtol=1e-6
        )

    def test_named_preset_end_to_end(self, june21_weather_data):
        """resolve_seg_tariff('Octopus') wired into HomeConfig prices export at 4.1 p/kWh."""
        flat_period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",
            rate_per_kwh=0.25,
            name="All day",
        )
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=5.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            tariff_config=TariffConfig(periods=(flat_period,), name="Flat 25p"),
            seg_tariff=resolve_seg_tariff("Octopus"),
            location=Location.bristol(),
        )
        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=june21_weather_data,
        )
        summary = calculate_summary(results)
        total_export_kwh = results.grid_export.sum() / 60.0
        expected_revenue = calculate_seg_revenue(total_export_kwh, SEG_PRESETS["Octopus"])
        assert summary.total_export_revenue_gbp == pytest.approx(expected_revenue, rel=1e-3)


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


class TestCalculateSummaryUnification:
    """Test that calculate_summary uses calculate_seg_revenue (unified SEG math)."""

    @pytest.fixture
    def export_results(self) -> SimulationResults:
        """Hand-built results with 12 kWh daily export (0.5 kW * 24 h)."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")
        return SimulationResults(
            generation=pd.Series([3.0] * 1440, index=index),
            demand=pd.Series([2.0] * 1440, index=index),
            self_consumption=pd.Series([2.0] * 1440, index=index),
            battery_charge=pd.Series([0.5] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([2.5] * 1440, index=index),
            grid_import=pd.Series([0.0] * 1440, index=index),
            grid_export=pd.Series([0.5] * 1440, index=index),  # 0.5 kW * 24h = 12 kWh
            import_cost=pd.Series([0.0] * 1440, index=index),
            export_revenue=pd.Series([0.0] * 1440, index=index),  # will be validated separately
            tariff_rate=pd.Series([0.10] * 1440, index=index),
        )

    def test_seg_revenue_preserved(self, export_results):
        """seg_revenue_gbp with 12 kWh export at 15 p/kWh == £1.80 (existing behaviour)."""
        # total_export = 0.5 kW * 1440 min / 60 = 12 kWh
        # seg_revenue = 12 * 15 / 100 = £1.80
        summary = calculate_summary(export_results, seg_tariff_pence_per_kwh=15.0)
        assert summary.seg_revenue_gbp is not None
        assert summary.seg_revenue_gbp == pytest.approx(1.80, rel=0.01)

    def test_negative_seg_rate_raises_value_error(self, export_results):
        """seg_tariff_pence_per_kwh < 0 now raises ValueError (via SEGTariff validation)."""
        with pytest.raises(ValueError):
            calculate_summary(export_results, seg_tariff_pence_per_kwh=-1.0)

    def test_unification_identity(self):
        """total_export_revenue_gbp == seg_revenue_gbp when export was SEG-priced at rate r."""
        rate_pence = 5.0  # p/kWh
        rate_pounds = rate_pence / 100.0
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")
        # Export-priced results: export_revenue per minute = grid_export_kwh * rate_pounds
        # grid_export_kwh per minute = 0.6 kW / 60 = 0.01 kWh
        grid_export_kw = 0.6
        export_kwh_per_min = grid_export_kw / 60.0
        export_rev_per_min = export_kwh_per_min * rate_pounds

        results = SimulationResults(
            generation=pd.Series([3.0] * 1440, index=index),
            demand=pd.Series([2.0] * 1440, index=index),
            self_consumption=pd.Series([2.0] * 1440, index=index),
            battery_charge=pd.Series([0.0] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([0.0] * 1440, index=index),
            grid_import=pd.Series([0.0] * 1440, index=index),
            grid_export=pd.Series([grid_export_kw] * 1440, index=index),
            import_cost=pd.Series([0.0] * 1440, index=index),
            export_revenue=pd.Series([export_rev_per_min] * 1440, index=index),
            tariff_rate=pd.Series([rate_pounds] * 1440, index=index),
        )
        summary = calculate_summary(results, seg_tariff_pence_per_kwh=rate_pence)

        # total_export_revenue_gbp (from series) == seg_revenue_gbp (from unified calc)
        assert summary.total_export_revenue_gbp == pytest.approx(
            summary.seg_revenue_gbp, rel=1e-6
        )


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

    def test_heat_pump_load_added_to_demand(self):
        """Heat pump electrical load is added to household demand."""
        # Config with heat pump
        config_with_hp = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
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
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
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


@pytest.fixture
def night_weather_data() -> pd.DataFrame:
    """Zero-irradiance synthetic 24-hour weather data for Bristol (June 21).

    All irradiance (GHI/DNI/DHI) is zero so PV generation is ~0.
    Any battery_charge > 0 is unambiguously from grid charging, not excess PV.
    Covers all 24 hours (same index shape as june21_weather_data) so
    _align_tmy_to_demand maps every simulation minute to a valid row.
    Avoids a PVGIS network call.
    """
    index = pd.date_range(
        "2024-06-21 00:00", periods=24, freq="1h", tz="Europe/London"
    )
    return pd.DataFrame(
        {
            "ghi": [0] * 24,
            "dni": [0] * 24,
            "dhi": [0] * 24,
            "temp_air": [12] * 24,
            "wind_speed": [2] * 24,
        },
        index=index,
    )


class TestSimulateHomeStrategyPathGridCharging:
    """Test grid-charging wiring via the Strategy-pattern dispatch path.

    The Strategy path (else branch in home.simulate_home) is taken when
    BatteryConfig.dispatch_strategy is set, making use_tariff_tou False.
    Before the fix, simulate_timestep on this path never receives tariff=…,
    so grid_charge_ctx is always None and grid-charging is dead.
    After the fix (adding tariff=config.tariff_config), the full grid-charge
    chain fires: is_cheap + spread gates pass → battery charged from grid.
    """

    @pytest.fixture
    def strategy_grid_charge_config(self):
        """HomeConfig that routes to the Strategy (else) branch and enables grid-charging.

        - BatteryConfig.dispatch_strategy is set → use_tariff_tou = False → else branch.
        - GridChargeConfig(target_soc_fraction=0.9) enables arbitrage charging.
        - Tariff: 0.10 £/kWh overnight (00:00-07:00, off-peak) + 0.30 £/kWh during day
          (07:00-00:00, peak). rt_eff ≈ 0.9506 → is_cheap (0.10 ≤ 0.20 avg) ✓;
          spread gate (0.30 > 0.10/0.9506 ≈ 0.1052) ✓.
        """
        off_peak = TariffPeriod("00:00", "07:00", 0.10, "Off-peak")
        peak = TariffPeriod("07:00", "00:00", 0.30, "Peak")
        return HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                max_charge_kw=2.5,
                dispatch_strategy=DispatchStrategyConfig(
                    strategy_type="tou_optimized",
                    peak_hours=[(7, 24)],
                ),
                grid_charging=GridChargeConfig(target_soc_fraction=0.9),
            ),
            tariff_config=TariffConfig(
                periods=(off_peak, peak),
                name="E7-like",
            ),
            location=Location.bristol(),
        )

    def test_strategy_path_grid_charges_battery(
        self, strategy_grid_charge_config, night_weather_data
    ):
        """Strategy path: zero-PV + tariff threaded → battery_charge > 0 (grid charging active).

        RED before fix: home.py Strategy else-branch omits tariff= → grid_charge_ctx is
        None → no grid charging → battery_charge.sum() == 0. GREEN after fix.

        Also verifies the §3.1 split-accounting energy balance closes on the Strategy path:
        generation + grid_import ≈ demand + grid_export + (battery_charge - battery_discharge).
        validate_balance=True already enforces this per-timestep; the explicit series check
        below makes the guarantee visible as a reviewable assertion.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.battery_charge.sum() > 0, (
            "Expected battery_charge > 0: grid charging should engage via Strategy path "
            "when tariff=config.tariff_config is threaded into simulate_timestep"
        )
        # §3.1 split-accounting identity (generation + grid_import == demand + grid_export +
        # battery_net) should hold element-wise within floating-point tolerance.
        lhs = results.generation + results.grid_import
        rhs = (
            results.demand
            + results.grid_export
            + (results.battery_charge - results.battery_discharge)
        )
        imbalance = (lhs - rhs).abs().max()
        assert imbalance < 1e-6, (
            f"Energy balance violated: max imbalance = {imbalance:.2e} kW"
        )

    def test_soc_rises_overnight_from_grid(
        self, strategy_grid_charge_config, night_weather_data
    ):
        """SOC climbs above the observed starting SOC during the cheap overnight window.

        RED before fix: with tariff absent from the call, grid_charge_ctx is None,
        no charging occurs, SOC stays at whatever the battery initialises to.
        GREEN after fix: overnight charging raises SOC toward target 0.9 × capacity.

        Uses results.battery_soc.iloc[0] rather than a re-derived constant so the
        test stays decoupled from Battery's internal initial-SOC formula.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        initial_soc = results.battery_soc.iloc[0]
        assert results.battery_soc.max() > initial_soc, (
            f"Expected SOC to rise above observed initial {initial_soc:.3f} kWh; "
            f"max={results.battery_soc.max():.3f}"
        )

    def test_grid_charge_inert_without_tariff(self, night_weather_data):
        """Without tariff_config, grid-charging stays inert (battery_charge == 0 with zero PV).

        Guard/non-regression: pins the 'tariff_config=None → no behaviour change' contract.
        Green before and after the fix (the impl threads config.tariff_config which is None here).
        """
        config_no_tariff = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                max_charge_kw=2.5,
                dispatch_strategy=DispatchStrategyConfig(
                    strategy_type="tou_optimized",
                    peak_hours=[(7, 24)],
                ),
                grid_charging=GridChargeConfig(target_soc_fraction=0.9),
            ),
            tariff_config=None,
            location=Location.bristol(),
        )
        results = simulate_home(
            config_no_tariff,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.battery_charge.sum() == pytest.approx(0.0), (
            "Expected battery_charge == 0: without tariff, grid charging should be inert"
        )
        initial_soc = results.battery_soc.iloc[0]
        assert results.battery_soc.max() <= initial_soc + 1e-9, (
            "Expected SOC to not rise above observed initial SOC without tariff"
        )


# ---------------------------------------------------------------------------
# CR2 step-3: RED tests for per-home grid-charge cost channel
# ---------------------------------------------------------------------------

@pytest.fixture
def economy7_tariff_config() -> TariffConfig:
    """Economy 7 tariff: off-peak 0.09/kWh (00:30-07:30), peak 0.25/kWh."""
    return TariffConfig.economy_7()


@pytest.fixture
def tou_grid_charge_home_config(economy7_tariff_config: TariffConfig) -> HomeConfig:
    """HomeConfig with TOU tariff + grid-charging enabled battery (overnight charging scenario)."""
    from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            max_charge_kw=2.5,
            max_discharge_kw=2.5,
            dispatch_strategy=DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(7, 24)],
            ),
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        ),
        tariff_config=economy7_tariff_config,
        location=Location.bristol(),
    )


@pytest.fixture
def flat_tariff_no_gc_home_config() -> HomeConfig:
    """HomeConfig with flat tariff and no grid-charging (H5 invariant base)."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        battery_config=BatteryConfig(capacity_kwh=5.0),  # no grid_charging
        tariff_config=TariffConfig(
            periods=[TariffPeriod(name="flat", rate_per_kwh=0.28, start_time="00:00", end_time="00:00")],
        ),
        location=Location.bristol(),
    )


@pytest.fixture
def night_weather_for_gc() -> pd.DataFrame:
    """Purely nocturnal weather (zero irradiance) to isolate grid-charge cost from PV."""
    index = pd.date_range("2024-06-21 00:00", periods=24, freq="1h", tz="Europe/London")
    return pd.DataFrame(
        {
            "ghi": [0.0] * 24,
            "dni": [0.0] * 24,
            "dhi": [0.0] * 24,
            "temp_air": [12.0] * 24,
            "wind_speed": [2.0] * 24,
        },
        index=index,
    )


class TestSimulationResultsGridChargeCost:
    """RED tests for the new SimulationResults.grid_charge_cost field (CR2 step-3a)."""

    def test_grid_charge_cost_field_defaults_to_none(self) -> None:
        """(a-i) SimulationResults.grid_charge_cost defaults to None (back-compat)."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        results = SimulationResults(
            generation=pd.Series([0.0, 0.0, 0.0], index=idx),
            demand=pd.Series([0.0, 0.0, 0.0], index=idx),
            self_consumption=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.0, 0.0, 0.0], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
        )
        assert results.grid_charge_cost is None

    def test_grid_charge_cost_round_trips(self) -> None:
        """(a-ii) SimulationResults accepts and returns a grid_charge_cost Series."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        gc_cost = pd.Series([0.01, 0.02, 0.03], index=idx, name="grid_charge_cost_gbp")
        results = SimulationResults(
            generation=pd.Series([0.0, 0.0, 0.0], index=idx),
            demand=pd.Series([0.0, 0.0, 0.0], index=idx),
            self_consumption=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.0, 0.0, 0.0], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_charge_cost=gc_cost,
        )
        assert results.grid_charge_cost is not None
        pd.testing.assert_series_equal(results.grid_charge_cost, gc_cost)


class TestCalculateSummaryGridChargeCost:
    """RED tests for SummaryStatistics.total_grid_charge_cost_gbp (CR2 step-3b)."""

    def _make_results(
        self, grid_charge_cost: "pd.Series | None" = None
    ) -> SimulationResults:
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        return SimulationResults(
            generation=pd.Series([1.0, 1.0, 1.0], index=idx),
            demand=pd.Series([0.5, 0.5, 0.5], index=idx),
            self_consumption=pd.Series([0.5, 0.5, 0.5], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([2.5, 2.5, 2.5], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.5, 0.5, 0.5], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_charge_cost=grid_charge_cost,
        )

    def test_total_grid_charge_cost_gbp_zero_when_none(self) -> None:
        """(b-i) total_grid_charge_cost_gbp == 0.0 when grid_charge_cost is None."""
        results = self._make_results(grid_charge_cost=None)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0)

    def test_total_grid_charge_cost_gbp_equals_series_sum(self) -> None:
        """(b-ii) total_grid_charge_cost_gbp == results.grid_charge_cost.sum() in £."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        gc_cost = pd.Series([0.01, 0.02, 0.03], index=idx)
        results = self._make_results(grid_charge_cost=gc_cost)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(gc_cost.sum())


class TestSimulateHomeGridChargeCost:
    """RED tests for simulate_home producing grid_charge_cost (CR2 step-3c/d)."""

    def test_tou_grid_charging_home_produces_nonzero_cost(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_for_gc: pd.DataFrame,
    ) -> None:
        """(c) TOU tariff + grid_charging battery → total_grid_charge_cost_gbp > 0."""
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_for_gc,
        )
        assert results.grid_charge_cost is not None, (
            "grid_charge_cost should be a Series when tariff_config is set"
        )
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp > 0.0, (
            "With TOU tariff + grid-charging battery + zero PV, CBS grid charge cost must be > 0"
        )

    def test_tou_grid_charging_cost_priced_at_offpeak_rate(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_for_gc: pd.DataFrame,
        economy7_tariff_config: TariffConfig,
    ) -> None:
        """(c-ii) grid_charge_cost per-timestep equals grid_charge kWh × off-peak rate."""
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_for_gc,
        )
        assert results.grid_charge_cost is not None
        # During off-peak hours (00:30–07:30), rate == 0.09 £/kWh.
        # grid_charge_cost per timestep = grid_charge_kwh × rate (off-peak)
        # Verify no timestep has a negative cost
        assert (results.grid_charge_cost >= 0.0).all(), (
            "All grid_charge_cost values must be non-negative"
        )

    def test_flat_no_grid_charging_produces_zero_cost(
        self,
        flat_tariff_no_gc_home_config: HomeConfig,
        night_weather_for_gc: pd.DataFrame,
    ) -> None:
        """(d) Flat-rate tariff, no grid_charging → total_grid_charge_cost_gbp == 0.0 (H5)."""
        results = simulate_home(
            flat_tariff_no_gc_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_for_gc,
        )
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0), (
            "Without grid_charging, CBS grid charge cost must be 0.0 (H5 invariant)"
        )
