"""Tests for HomeConfig, SimulationResults, calculate_summary and SEG export pricing in simulate_home."""

import dataclasses
import typing

import numpy as np
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
from tests._synthetic_weather import synthetic_june_weather


@pytest.fixture
def june21_weather_data() -> pd.DataFrame:
    """A clear 21 June, sunny enough for the SEG tests' 4-5 kW arrays to export, with no PVGIS call."""
    return synthetic_june_weather("2024-06-21")


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

    def test_name_and_dispatch_strategy_take_the_declared_defaults(self):
        """An unnamed home has an empty name and the greedy dispatch strategy."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        assert config.name == ""
        assert config.dispatch_strategy == "greedy"

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


def _series_field_names() -> list[str]:
    """SimulationResults' fields annotated pd.Series or Optional[pd.Series], in declaration order."""
    hints = typing.get_type_hints(SimulationResults)
    return [
        field.name
        for field in dataclasses.fields(SimulationResults)
        if pd.Series in (hints[field.name], *typing.get_args(hints[field.name]))
    ]


def _results_with_every_series_set() -> SimulationResults:
    """Results whose every series, optional ones included, varies and holds values no other series holds."""
    index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min", tz="Europe/London")
    return SimulationResults(
        strategy_name="tou_optimized",
        **{
            name: pd.Series(np.arange(60.0) + 100.0 * position, index=index)
            for position, name in enumerate(_series_field_names())
        },
    )


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

    def test_to_dataframe_appends_a_set_grid_charge_cost_as_grid_charge_cost_gbp(self, sample_results):
        """A set grid_charge_cost is one more column, grid_charge_cost_gbp, after the columns of a run without it."""
        grid_charge_cost = pd.Series(0.01, index=sample_results.generation.index)

        df = dataclasses.replace(sample_results, grid_charge_cost=grid_charge_cost).to_dataframe()

        assert list(df.columns) == [*sample_results.to_dataframe().columns, "grid_charge_cost_gbp"]
        pd.testing.assert_series_equal(df["grid_charge_cost_gbp"], grid_charge_cost, check_names=False)

    def test_to_dataframe_appends_a_set_grid_charge_as_grid_charge_kw(self, sample_results):
        """A set grid_charge is the last column, grid_charge_kw, after the grid_charge_cost_gbp a tariffed run also has."""
        index = sample_results.generation.index
        grid_charge = pd.Series(0.25, index=index)

        df = dataclasses.replace(
            sample_results, grid_charge_cost=pd.Series(0.01, index=index), grid_charge=grid_charge
        ).to_dataframe()

        assert list(df.columns) == [
            *sample_results.to_dataframe().columns,
            "grid_charge_cost_gbp",
            "grid_charge_kw",
        ]
        pd.testing.assert_series_equal(df["grid_charge_kw"], grid_charge, check_names=False)

    def test_from_dataframe_restores_every_series_to_dataframe_wrote(self):
        """from_dataframe gives back every series to_dataframe wrote, under the same name, optional ones included."""
        original = _results_with_every_series_set()

        restored = SimulationResults.from_dataframe(
            original.to_dataframe(), strategy_name=original.strategy_name
        )

        assert restored.heat_pump_load is not None
        assert restored.grid_charge_cost is not None
        assert restored.grid_charge is not None
        for name in _series_field_names():
            pd.testing.assert_series_equal(getattr(restored, name), getattr(original, name), obj=name)
        assert restored.strategy_name == "tou_optimized"

    @pytest.mark.parametrize(
        "built_name",
        [pytest.param(None, id="unnamed"), pytest.param("demand_kw", id="named-another-series-column")],
    )
    def test_each_series_is_named_the_column_to_dataframe_writes_it_under(self, built_name):
        """Each series is named the column to_dataframe writes it under, whatever it was named when built."""
        built = _results_with_every_series_set()
        results = dataclasses.replace(
            built, **{name: getattr(built, name).rename(built_name) for name in _series_field_names()}
        )

        name_by_field = {field_name: getattr(results, field_name).name for field_name in _series_field_names()}
        column_by_field = dict(zip(name_by_field, results.to_dataframe().columns, strict=True))

        assert name_by_field == column_by_field

    def test_the_series_it_was_built_from_keep_their_names(self):
        """Naming its series does not rename the series a SimulationResults was built from."""
        built = _results_with_every_series_set()
        given = {name: getattr(built, name).rename("temp_air") for name in _series_field_names()}

        dataclasses.replace(built, **given)

        assert {name: series.name for name, series in given.items()} == dict.fromkeys(given, "temp_air")

    @pytest.mark.parametrize("name", _series_field_names())
    def test_a_series_field_cannot_be_reassigned_after_construction(self, name):
        """Reassigning a series field after construction raises FrozenInstanceError, leaving the series named its column."""
        results = _results_with_every_series_set()
        column = getattr(results, name).name

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(results, name, getattr(results, name).rename("temp_air"))

        assert getattr(results, name).name == column

    def test_results_stay_unhashable_though_frozen(self):
        """hash(results) raises TypeError: freezing SimulationResults does not make it hashable."""
        with pytest.raises(TypeError):
            hash(_results_with_every_series_set())

    def test_optional_series_left_unset_come_back_none(self, sample_results):
        """An optional series left unset is written as no column, and comes back None rather than NaN or zero."""
        restored = SimulationResults.from_dataframe(
            sample_results.to_dataframe(), strategy_name="self_consumption"
        )

        assert restored.heat_pump_load is None
        assert restored.grid_charge_cost is None
        assert restored.grid_charge is None

    def test_frame_lacking_required_series_columns_is_refused_naming_them(self, sample_results):
        """A frame lacking required series' columns is refused with a ValueError naming each, and no absent optional one."""
        frame = sample_results.to_dataframe().drop(columns=["generation_kw", "tariff_rate_per_kwh"])

        with pytest.raises(ValueError) as refusal:
            SimulationResults.from_dataframe(frame, strategy_name="self_consumption")

        message = str(refusal.value)
        assert "generation_kw" in message
        assert "tariff_rate_per_kwh" in message
        assert "grid_charge_cost_gbp" not in message


class TestPerMinuteAmounts:
    """Test SimulationResults.per_minute_amounts, each minute's energy and money, and total_amounts, their run totals."""

    def test_power_becomes_each_minutes_kwh_and_money_stays_its_pounds(self):
        """Each kW series becomes its minute's kWh, each £ series stays as it is, and a level has no column."""
        results = _results_with_every_series_set()

        amounts = results.per_minute_amounts()

        expected = pd.DataFrame(
            {
                "generation_kwh": results.generation / 60,
                "demand_kwh": results.demand / 60,
                "self_consumption_kwh": results.self_consumption / 60,
                "battery_charge_kwh": results.battery_charge / 60,
                "battery_discharge_kwh": results.battery_discharge / 60,
                "grid_import_kwh": results.grid_import / 60,
                "grid_export_kwh": results.grid_export / 60,
                "heat_pump_load_kwh": results.heat_pump_load / 60,
                "grid_charge_kwh": results.grid_charge / 60,
                "import_cost_gbp": results.import_cost,
                "export_revenue_gbp": results.export_revenue,
                "grid_charge_cost_gbp": results.grid_charge_cost,
            }
        )
        pd.testing.assert_frame_equal(amounts, expected, check_like=True)

    def test_an_unset_optional_series_has_no_amount_column(self):
        """An optional series left unset has no amount column."""
        amounts = dataclasses.replace(
            _results_with_every_series_set(), heat_pump_load=None, grid_charge_cost=None, grid_charge=None
        ).per_minute_amounts()

        assert sorted(amounts.columns) == sorted(
            [
                "generation_kwh",
                "demand_kwh",
                "self_consumption_kwh",
                "battery_charge_kwh",
                "battery_discharge_kwh",
                "grid_import_kwh",
                "grid_export_kwh",
                "import_cost_gbp",
                "export_revenue_gbp",
            ]
        )

    @pytest.mark.parametrize(
        "unset",
        [{}, {"heat_pump_load": None, "grid_charge_cost": None, "grid_charge": None}],
        ids=["every_series_set", "optional_series_unset"],
    )
    def test_total_amounts_are_the_per_minute_amounts_summed_over_the_run(self, unset):
        """Each run total is its per-minute amount column's sum, keyed by that column."""
        results = dataclasses.replace(_results_with_every_series_set(), **unset)

        assert results.total_amounts() == pytest.approx(results.per_minute_amounts().sum().to_dict())


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
