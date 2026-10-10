"""Tests for output and reporting functions."""

import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.output import (
    aggregate_annual,
    aggregate_daily,
    aggregate_monthly,
    calculate_export_ratio,
    calculate_grid_dependency_ratio,
    calculate_seasonal_metrics,
    calculate_self_consumption_ratio,
    export_to_csv,
    generate_summary_report,
)


@pytest.fixture
def sample_results() -> SimulationResults:
    """Create sample simulation results for 2 days."""
    # 2 days = 2880 minutes
    index = pd.date_range(
        "2024-06-21 00:00", periods=2880, freq="1min", tz="Europe/London"
    )
    return SimulationResults(
        generation=pd.Series([3.0] * 2880, index=index),  # 3 kW constant
        demand=pd.Series([2.0] * 2880, index=index),  # 2 kW constant
        self_consumption=pd.Series([2.0] * 2880, index=index),
        battery_charge=pd.Series([0.5] * 2880, index=index),
        battery_discharge=pd.Series([0.0] * 2880, index=index),
        battery_soc=pd.Series([2.5] * 2880, index=index),
        grid_import=pd.Series([0.0] * 2880, index=index),
        grid_export=pd.Series([0.5] * 2880, index=index),
        import_cost=pd.Series([0.0] * 2880, index=index),
        export_revenue=pd.Series([0.01] * 2880, index=index),  # 0.01 £ per minute
        tariff_rate=pd.Series([0.20] * 2880, index=index),  # 0.20 £/kWh constant
    )


def _run_with_distinct_rising_series(
    start: str, days: int, *, with_optional_series: bool
) -> SimulationResults:
    """Every series climbs steadily from its own base, so no two series share values and every day's peak exceeds its mean."""
    index = pd.date_range(start, periods=days * 1440, freq="1min", tz="Europe/London")
    rise = np.linspace(1.0, 2.0, len(index))

    def series(base: float) -> pd.Series:
        return pd.Series(base * rise, index=index)

    return SimulationResults(
        generation=series(3.0),
        demand=series(2.0),
        self_consumption=series(1.5),
        battery_charge=series(0.75),
        battery_discharge=series(0.25),
        battery_soc=series(4.0),
        grid_import=series(0.5),
        grid_export=series(0.6),
        import_cost=series(0.002),
        export_revenue=series(0.001),
        tariff_rate=series(0.3),
        heat_pump_load=series(1.2) if with_optional_series else None,
        grid_charge_cost=series(0.0005) if with_optional_series else None,
        grid_charge=series(0.4) if with_optional_series else None,
    )


def _seasonal_run() -> SimulationResults:
    """Two January days, one April day and half a July day, each span steady at its own levels."""
    spans = [
        pd.date_range(start, periods=rows, freq="1min", tz="Europe/London")
        for start, rows in [("2024-01-01", 2 * 1440), ("2024-04-01", 1440), ("2024-07-01", 720)]
    ]
    index = spans[0].append(spans[1:])

    def steady(*, january: float, april: float, july: float) -> pd.Series:
        return pd.Series(np.repeat([january, april, july], [len(span) for span in spans]), index=index)

    zeros = pd.Series(0.0, index=index)
    return SimulationResults(
        generation=steady(january=1.0, april=9.0, july=4.0),
        demand=steady(january=5.0, april=10.0, july=1.0),
        self_consumption=zeros,
        battery_charge=zeros,
        battery_discharge=zeros,
        battery_soc=zeros,
        grid_import=zeros,
        grid_export=zeros,
        import_cost=zeros,
        export_revenue=zeros,
        tariff_rate=zeros,
        heat_pump_load=steady(january=2.0, april=9.0, july=0.25),
    )


class TestExportToCSV:
    """Test OUT-001: Export to CSV."""

    def test_creates_csv_file(self, sample_results):
        """Creates a CSV file at the specified path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "results.csv"
            result_path = export_to_csv(sample_results, filepath)

            assert result_path.exists()
            assert result_path.suffix == ".csv"

    def test_csv_contains_all_columns(self, sample_results):
        """CSV contains all result columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "results.csv"
            export_to_csv(sample_results, filepath)

            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            assert "generation_kw" in df.columns
            assert "demand_kw" in df.columns
            assert "battery_soc_kwh" in df.columns

    def test_csv_has_correct_length(self, sample_results):
        """CSV has correct number of rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "results.csv"
            export_to_csv(sample_results, filepath)

            df = pd.read_csv(filepath)
            assert len(df) == 2880


class TestGenerateSummaryReport:
    """Test OUT-002: Summary report generation."""

    def test_generates_markdown_report(self, sample_results):
        """Generates a markdown-formatted report."""
        report = generate_summary_report(sample_results)

        assert isinstance(report, str)
        assert "# Simulation Report" in report
        assert "## Energy Totals" in report
        assert "## Efficiency Ratios" in report

    def test_includes_home_name(self, sample_results):
        """Report includes home name when provided."""
        report = generate_summary_report(sample_results, home_name="Test Home")
        assert "Test Home" in report

    def test_includes_all_metrics(self, sample_results):
        """Report includes all key metrics."""
        report = generate_summary_report(sample_results)

        assert "Generation" in report
        assert "Demand" in report
        assert "Self-Consumption" in report
        assert "Grid Import" in report
        assert "Grid Export" in report

    def test_includes_financial_section(self, sample_results):
        """Report includes financial section with bill totals and savings."""
        report = generate_summary_report(sample_results)

        assert "## Financial" in report
        assert "Grid Import Cost" in report
        assert "Grid Export Revenue" in report
        assert "Net Cost" in report


class TestSeasonalBreakdowns:
    """Winter (December to February) and summer (June to August) each count only their own rows."""

    def test_report_tables_each_seasons_heat_pump_figures(self):
        lines = generate_summary_report(_seasonal_run()).splitlines()

        # Winter: 2 kW × 48 h = 96 kWh, 40% of 5 kW × 48 h, over 2 days.
        # Summer: 0.25 kW × 12 h = 3 kWh, 25% of 1 kW × 12 h, over half a day.
        assert "| Total Heat Pump Load | 96.0 kWh | 3.0 kWh | 32.0x |" in lines
        assert "| Peak Heat Pump Load | 2.00 kW | 0.25 kW | 8.0x |" in lines
        assert "| HP % of Demand | 40.0% | 25.0% | - |" in lines
        assert "| Daily Average | 48.0 kWh/day | 6.0 kWh/day | 8.0x |" in lines

    def test_seasonal_metrics_total_each_season_and_leave_out_the_rest(self):
        run = _seasonal_run()

        # Self-consumption is each minute's min(generation, demand): generation in winter, demand in summer.
        assert calculate_seasonal_metrics(run.demand, run.generation) == pytest.approx(
            {
                "winter_generation_kwh": 48.0,
                "winter_demand_kwh": 240.0,
                "winter_self_consumption_kwh": 48.0,
                "winter_self_consumption_ratio": 1.0,
                "winter_grid_dependency_ratio": 0.8,
                "summer_generation_kwh": 48.0,
                "summer_demand_kwh": 12.0,
                "summer_self_consumption_kwh": 12.0,
                "summer_self_consumption_ratio": 0.25,
                "summer_grid_dependency_ratio": 0.0,
            }
        )


class TestRatioCalculations:
    """Test OUT-003, OUT-004, OUT-005: Ratio calculations."""

    def test_self_consumption_ratio(self, sample_results):
        """OUT-003: Self-consumption ratio calculation."""
        ratio = calculate_self_consumption_ratio(sample_results)

        # 2 kW self-consumption / 3 kW generation = 0.667
        assert ratio == pytest.approx(0.667, rel=0.01)

    def test_grid_dependency_ratio(self, sample_results):
        """OUT-004: Grid dependency ratio calculation."""
        ratio = calculate_grid_dependency_ratio(sample_results)

        # 0 kW import / 2 kW demand = 0
        assert ratio == 0.0

    def test_export_ratio(self, sample_results):
        """OUT-005: Export ratio calculation."""
        ratio = calculate_export_ratio(sample_results)

        # 0.5 kW export / 3 kW generation = 0.167
        assert ratio == pytest.approx(0.167, rel=0.01)


class TestAggregateDaily:
    """Test OUT-006: Daily aggregation."""

    def test_aggregates_to_daily(self, sample_results):
        """Aggregates 1-minute data to daily totals."""
        daily = aggregate_daily(sample_results)

        # 2 days of data
        assert len(daily) == 2

    def test_converts_to_energy(self, sample_results):
        """Converts power (kW) to energy (kWh)."""
        daily = aggregate_daily(sample_results)

        # 3 kW for 1440 minutes = 3 * 24 = 72 kWh/day
        assert daily["generation_kwh"].iloc[0] == pytest.approx(72.0, rel=0.01)

    def test_includes_peak_values(self, sample_results):
        """Includes daily peak values."""
        daily = aggregate_daily(sample_results)

        assert "peak_generation_kw" in daily.columns
        assert "peak_demand_kw" in daily.columns

    def test_money_is_summed_without_a_unit_conversion(self, sample_results):
        """A money series is already £ per minute, so a day's total is its plain sum."""
        daily = aggregate_daily(sample_results)

        # £0.01 a minute for 1440 minutes a day
        assert daily["export_revenue_gbp"].tolist() == pytest.approx([14.40, 14.40])

    def test_peak_is_the_days_largest_sample_wherever_it_falls(self, sample_results):
        """A day's peak is its largest sample, even when the day ends back at its base."""
        spiked_demand = sample_results.demand.copy()
        spiked_demand[pd.Timestamp("2024-06-21 12:00", tz="Europe/London")] = 6.0

        daily = aggregate_daily(replace(sample_results, demand=spiked_demand))

        # 6 kW at noon on the first day, 2 kW all day on the second
        assert daily["peak_demand_kw"].tolist() == [6.0, 2.0]


class TestAggregateMonthly:
    """Test OUT-007: Monthly aggregation."""

    def test_aggregates_to_monthly(self, sample_results):
        """Aggregates to monthly totals."""
        monthly = aggregate_monthly(sample_results)

        # Both days in same month, so 1 row
        assert len(monthly) == 1

    def test_sums_energy_values(self, sample_results):
        """Sums energy values across days."""
        monthly = aggregate_monthly(sample_results)

        # 2 days * 72 kWh/day = 144 kWh
        assert monthly["generation_kwh"].iloc[0] == pytest.approx(144.0, rel=0.01)

    def test_each_month_totals_only_its_own_days(self):
        """June 29 and 30 total into June, and July 1 alone into July."""
        index = pd.date_range(
            "2024-06-29 00:00", periods=3 * 1440, freq="1min", tz="Europe/London"
        )

        def constant(value: float) -> pd.Series:
            return pd.Series(value, index=index)

        demand = constant(2.0)
        demand[pd.Timestamp("2024-07-01 18:00", tz="Europe/London")] = 6.0
        results = SimulationResults(
            generation=constant(3.0),
            demand=demand,
            self_consumption=constant(1.5),
            battery_charge=constant(0.75),
            battery_discharge=constant(0.25),
            battery_soc=constant(4.0),
            grid_import=constant(0.5),
            grid_export=constant(0.6),
            import_cost=constant(0.002),
            export_revenue=constant(0.001),
            tariff_rate=constant(0.3),
        )

        monthly = aggregate_monthly(results)

        assert monthly.index.tolist() == [
            pd.Timestamp("2024-06-30", tz="Europe/London"),
            pd.Timestamp("2024-07-31", tz="Europe/London"),
        ]
        # 3 kW for 2 days, then 1 day
        assert monthly["generation_kwh"].tolist() == pytest.approx([144.0, 72.0])
        # £0.002 a minute for 2 days, then 1 day
        assert monthly["import_cost_gbp"].tolist() == pytest.approx([5.76, 2.88])
        assert monthly["peak_demand_kw"].tolist() == [2.0, 6.0]


@pytest.mark.parametrize(
    "aggregate", [aggregate_daily, aggregate_monthly], ids=["daily", "monthly"]
)
class TestPeriodTotalsAndPeaks:
    """Each row holds that period's energy (kWh) and money (£) totals and its peak power (kW), and nothing else."""

    @pytest.mark.parametrize(
        "with_optional_series",
        [False, True],
        ids=["required_series_only", "with_optional_series"],
    )
    def test_columns_are_the_runs_totals_and_peaks(
        self, aggregate, with_optional_series
    ):
        """The columns are the run's energy totals, money totals and peaks."""
        results = _run_with_distinct_rising_series(
            "2024-06-29 00:00", 3, with_optional_series=with_optional_series
        )

        frame = aggregate(results)

        expected = [
            "generation_kwh",
            "demand_kwh",
            "self_consumption_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "grid_import_kwh",
            "grid_export_kwh",
            "import_cost_gbp",
            "export_revenue_gbp",
            "peak_generation_kw",
            "peak_demand_kw",
        ]
        if with_optional_series:
            expected += ["heat_pump_load_kwh", "grid_charge_cost_gbp", "grid_charge_kwh"]
        assert sorted(frame.columns) == sorted(expected)

    def test_totals_over_all_periods_equal_the_run_summary(self, aggregate):
        """Adding up every period gives the run's own summary totals and peaks."""
        results = _run_with_distinct_rising_series(
            "2024-06-29 00:00", 3, with_optional_series=True
        )
        summary = calculate_summary(results)
        run_totals = {
            "generation_kwh": summary.total_generation_kwh,
            "demand_kwh": summary.total_demand_kwh,
            "self_consumption_kwh": summary.total_self_consumption_kwh,
            "battery_charge_kwh": summary.total_battery_charge_kwh,
            "battery_discharge_kwh": summary.total_battery_discharge_kwh,
            "grid_import_kwh": summary.total_grid_import_kwh,
            "grid_export_kwh": summary.total_grid_export_kwh,
            "heat_pump_load_kwh": summary.total_heat_pump_load_kwh,
            "import_cost_gbp": summary.total_import_cost_gbp,
            "export_revenue_gbp": summary.total_export_revenue_gbp,
            "grid_charge_cost_gbp": summary.total_grid_charge_cost_gbp,
            "grid_charge_kwh": summary.total_grid_charge_kwh,
        }

        frame = aggregate(results)

        assert frame[list(run_totals)].sum().to_dict() == pytest.approx(run_totals)
        assert frame["peak_generation_kw"].max() == pytest.approx(
            summary.peak_generation_kw
        )
        assert frame["peak_demand_kw"].max() == pytest.approx(summary.peak_demand_kw)


class TestAggregateAnnual:
    """Test OUT-008: Annual aggregation."""

    def test_returns_dict(self, sample_results):
        """Returns dictionary with annual totals."""
        annual = aggregate_annual(sample_results)

        assert isinstance(annual, dict)
        assert "generation_kwh" in annual
        assert "demand_kwh" in annual

    def test_includes_all_metrics(self, sample_results):
        """Includes all summary metrics."""
        annual = aggregate_annual(sample_results)

        assert "self_consumption_ratio" in annual
        assert "grid_dependency_ratio" in annual
        assert "export_ratio" in annual
        assert "simulation_days" in annual

