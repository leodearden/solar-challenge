"""Tests for output and reporting functions."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from solar_challenge.home import SimulationResults
from solar_challenge.output import (
    aggregate_annual,
    aggregate_daily,
    aggregate_monthly,
    calculate_export_ratio,
    calculate_grid_dependency_ratio,
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

