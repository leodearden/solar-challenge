"""Tests for HomeConfig, SimulationResults, calculate_summary and SEG export pricing in simulate_home."""

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    SummaryStatistics,
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

    def test_tou_without_seg_zeroes_export_revenue_and_warns(
        self, no_seg_config, june21_weather_data
    ):
        """TOU tariff without seg_tariff: export_revenue must be zero and emit a UserWarning."""
        with pytest.warns(UserWarning, match="seg_tariff"):
            results = simulate_home(
                no_seg_config,
                start_date=pd.Timestamp("2024-06-21"),
                end_date=pd.Timestamp("2024-06-21"),
                weather_data=june21_weather_data,
            )
        # Non-vacuous: some export actually occurred on this sunny day.
        assert results.grid_export.sum() > 0, "Expected grid export on a sunny day"
        # Corrected behaviour: no SEG tariff => no export revenue at any timestep.
        assert (results.export_revenue == 0).all(), "export_revenue must be zero when seg_tariff is None"
        assert calculate_summary(results).total_export_revenue_gbp == 0

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
