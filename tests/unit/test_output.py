"""Tests for output and reporting functions."""

import tempfile
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityConfig, simulate_community
from solar_challenge.finance import BillDistribution
from solar_challenge.grid_charge_forecast import GRID_CHARGE_FORECAST_LABELS
from solar_challenge.home import SimulationResults, calculate_summary, simulate_home
from solar_challenge.optimize import RankedSweep
from solar_challenge.output import (
    CommunityMetrics,
    SeasonSummary,
    aggregate_daily,
    aggregate_monthly,
    calculate_seasonal_metrics,
    compute_community_metrics,
    export_to_csv,
    generate_community_report,
    generate_config_ranking_report,
    generate_finance_report,
    generate_summary_report,
)
from solar_challenge.timebase import SimulationWindow
from tests._factories import make_bill_distribution, make_config_result, make_ranked_sweep
from tests._finance_builders import make_fleet_results_of, make_home_config, make_window
from tests._synthetic_weather import synthetic_june_weather, weather_for


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


def _seasonal_run(freq: str = "1min") -> SimulationResults:
    """Two February days, the spring, and half a June day, each day steady at its own levels, on one index whose rows are freq apart.

    The first February day's battery stores its PV surplus and meets part of the sunless second
    day's demand. Every row balances as a simulated one does.
    """
    index = pd.date_range("2024-02-28", "2024-06-01 11:59", freq=freq, tz="Europe/London")
    days = index.normalize()
    winter_1 = days == pd.Timestamp("2024-02-28", tz="Europe/London")
    winter_2 = days == pd.Timestamp("2024-02-29", tz="Europe/London")
    spring = index.month <= 5

    def steady(*, winter_1_kw: float, winter_2_kw: float, spring_kw: float, summer_kw: float) -> pd.Series:
        return pd.Series(
            np.select([winter_1, winter_2, spring], [winter_1_kw, winter_2_kw, spring_kw], default=summer_kw),
            index=index,
        )

    zeros = pd.Series(0.0, index=index)
    return SimulationResults(
        generation=steady(winter_1_kw=8.0, winter_2_kw=0.0, spring_kw=9.0, summer_kw=4.0),
        demand=steady(winter_1_kw=5.0, winter_2_kw=5.0, spring_kw=10.0, summer_kw=1.0),
        self_consumption=steady(winter_1_kw=5.0, winter_2_kw=1.0, spring_kw=9.0, summer_kw=1.0),
        battery_charge=steady(winter_1_kw=1.0, winter_2_kw=0.0, spring_kw=0.0, summer_kw=2.0),
        battery_discharge=steady(winter_1_kw=0.0, winter_2_kw=1.0, spring_kw=0.0, summer_kw=0.0),
        battery_soc=zeros,
        grid_import=steady(winter_1_kw=0.0, winter_2_kw=4.0, spring_kw=1.0, summer_kw=0.0),
        grid_export=steady(winter_1_kw=2.0, winter_2_kw=0.0, spring_kw=0.0, summer_kw=1.0),
        import_cost=zeros,
        export_revenue=zeros,
        tariff_rate=zeros,
        heat_pump_load=steady(winter_1_kw=2.0, winter_2_kw=2.0, spring_kw=9.0, summer_kw=0.25),
    )


_SEASONAL_RUN_FREQS = (
    pytest.param("1min", id="minute-rows"),
    pytest.param("30min", id="half-hour-rows"),
)


def _energy_figures(metrics: CommunityMetrics) -> dict[str, float]:
    """metrics' kWh figures and its self-sufficiency, each under its field name."""
    return {
        name: value
        for name, value in asdict(metrics).items()
        if name.endswith("_kwh") or name == "self_sufficiency"
    }


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

    @pytest.mark.parametrize("freq", _SEASONAL_RUN_FREQS)
    def test_report_tables_each_seasons_heat_pump_figures(self, freq: str) -> None:
        lines = generate_summary_report(_seasonal_run(freq)).splitlines()

        # Winter: 2 kW × 48 h = 96 kWh, 40% of 5 kW × 48 h, over 2 days.
        # Summer: 0.25 kW × 12 h = 3 kWh, 25% of 1 kW × 12 h, over half a day.
        assert "| Total Heat Pump Load | 96.0 kWh | 3.0 kWh | 32.0x |" in lines
        assert "| Peak Heat Pump Load | 2.00 kW | 0.25 kW | 8.0x |" in lines
        assert "| HP % of Demand | 40.0% | 25.0% | - |" in lines
        assert "| Daily Average | 48.0 kWh/day | 6.0 kWh/day | 8.0x |" in lines

    @pytest.mark.parametrize("freq", _SEASONAL_RUN_FREQS)
    def test_seasonal_metrics_total_each_seasons_own_flows_and_leave_out_the_rest(self, freq: str) -> None:
        seasons = calculate_seasonal_metrics(_seasonal_run(freq))

        # Winter self-consumption: 5 kW × 24 h plus the battery's 1 kW × 24 h = 144 kWh, where
        # min(generation, demand) would give 120. Winter import: 4 kW × 24 h = 96 kWh of 240.
        # Spring's rows count in neither season.
        assert asdict(seasons.winter) == pytest.approx(
            {
                "generation_kwh": 192.0,
                "demand_kwh": 240.0,
                "self_consumption_kwh": 144.0,
                "self_consumption_ratio": 0.75,
                "grid_dependency_ratio": 0.4,
            },
            rel=1e-9,
        )
        assert asdict(seasons.summer) == pytest.approx(
            {
                "generation_kwh": 48.0,
                "demand_kwh": 12.0,
                "self_consumption_kwh": 12.0,
                "self_consumption_ratio": 0.25,
                "grid_dependency_ratio": 0.0,
            },
            rel=1e-9,
        )

    def test_a_battery_homes_summer_day_has_its_summarys_figures(self):
        day = pd.Timestamp("2024-06-21")
        home = make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))
        run = simulate_home(home, day, day, weather=weather_for(home, synthetic_june_weather(day)))
        summary = calculate_summary(run)
        # The battery discharges, so min(generation, demand) would differ from the summary.
        assert summary.total_battery_discharge_kwh > 0

        seasons = calculate_seasonal_metrics(run)

        assert seasons.winter == SeasonSummary(
            generation_kwh=0.0,
            demand_kwh=0.0,
            self_consumption_kwh=0.0,
            self_consumption_ratio=0.0,
            grid_dependency_ratio=0.0,
        )
        assert asdict(seasons.summer) == pytest.approx(
            {
                "generation_kwh": summary.total_generation_kwh,
                "demand_kwh": summary.total_demand_kwh,
                "self_consumption_kwh": summary.total_self_consumption_kwh,
                "self_consumption_ratio": summary.self_consumption_ratio,
                "grid_dependency_ratio": summary.grid_dependency_ratio,
            }
        )


class TestCommunityMetrics:
    """compute_community_metrics integrates each row over as long as the community's rows last, so a half-hourly twin of a run has the minute run's figures."""

    def test_a_half_hourly_twin_of_a_run_has_the_minute_runs_figures(self) -> None:
        minute, half_hour = (
            compute_community_metrics(
                simulate_community(make_fleet_results_of([_seasonal_run(freq)]), CommunityConfig(sharing_mode="p2p"))
            )
            for freq in ("1min", "30min")
        )

        assert _energy_figures(half_hour) == pytest.approx(_energy_figures(minute), rel=1e-9)
        assert minute.dt_h == pytest.approx(1 / 60, rel=1e-9)
        assert half_hour.dt_h == pytest.approx(0.5, rel=1e-9)
        assert half_hour.sharing_mode == minute.sharing_mode


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


def _annualised_from(window: SimulationWindow) -> BillDistribution:
    """make_bill_distribution's distribution, its yearly figures annualised from *window*."""
    return replace(make_bill_distribution(), annualised_from=window)


def _one_config_sweep(window: SimulationWindow) -> RankedSweep:
    """A sweep of one feasible config, whose outlay's yearly figures are annualised from *window*."""
    cr = make_config_result(outlay=_annualised_from(window))
    return make_ranked_sweep((cr,))


_TRAILING_NOTICE = (
    "*Battery grid charging in cheap periods was sized by the trailing_14_days forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['trailing_14_days']}.*\n\n"
)
_PV_BLIND_AND_TRAILING_NOTICE = (
    "*Battery grid charging in cheap periods was sized by the pv_blind forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['pv_blind']}; and by the trailing_14_days forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['trailing_14_days']}.*\n\n"
)


def _sized_by(*forecasts: str) -> BillDistribution:
    """make_bill_distribution's distribution, its homes' grid charge sized by *forecasts*."""
    return replace(make_bill_distribution(), grid_charge_forecasts=forecasts)


class TestGridChargeForecastNotice:
    """Every report of results whose grid charge a forecast sized says, under its first heading, which forecast and what it is."""

    def test_a_summary_report_names_its_runs_forecast_under_its_title(self, sample_results: SimulationResults) -> None:
        report = generate_summary_report(replace(sample_results, grid_charge_forecast="trailing_14_days"))

        assert report.startswith("# Simulation Report\n\n" + _TRAILING_NOTICE + "## Simulation Period")

    def test_a_summary_report_of_a_run_that_did_not_grid_charge_has_no_notice(
        self, sample_results: SimulationResults
    ) -> None:
        report = generate_summary_report(sample_results)

        assert report.startswith("# Simulation Report\n\n## Simulation Period")
        assert "sized by" not in report

    @pytest.mark.parametrize("side_by_side", [False, True], ids=["physics-only", "side-by-side"])
    def test_a_finance_report_names_each_forecast_under_its_title(self, side_by_side: bool) -> None:
        dist = _sized_by("pv_blind", "trailing_14_days")

        report = generate_finance_report(dist, dist if side_by_side else None, scenario_name="Bristol")

        assert report.startswith("# Finance Report: Bristol\n\n" + _PV_BLIND_AND_TRAILING_NOTICE + "## Householder Bill")

    def test_a_finance_report_gives_the_forecast_notice_after_the_extrapolation_notice(self) -> None:
        dist = replace(_sized_by("trailing_14_days"), annualised_from=make_window(days=2, first_day=date(2024, 3, 31)))

        report = generate_finance_report(dist, scenario_name="Bristol")

        assert report.startswith(
            "# Finance Report: Bristol\n\n"
            "*Yearly figures are extrapolated ×183.000 from a 2-day window (2024-03-31 to 2024-04-01), "
            "not whole calendar years.*\n\n" + _TRAILING_NOTICE + "## Householder Bill"
        )

    def test_a_finance_report_whose_homes_did_not_grid_charge_has_no_notice(self) -> None:
        report = generate_finance_report(_sized_by(), scenario_name="Bristol")

        assert report == generate_finance_report(make_bill_distribution(), scenario_name="Bristol")
        assert "sized by" not in report

    def test_a_ranking_report_names_its_outlays_forecasts_under_its_first_heading(self) -> None:
        sweep = make_ranked_sweep((make_config_result(outlay=_sized_by("pv_blind", "trailing_14_days")),))

        assert generate_config_ranking_report(sweep).startswith(
            "## Cost-Recovery Rank\n\n" + _PV_BLIND_AND_TRAILING_NOTICE + "| Config"
        )

    def test_a_ranking_report_whose_homes_did_not_grid_charge_has_no_notice(self) -> None:
        sweep = make_ranked_sweep((make_config_result(outlay=_sized_by()),))

        assert generate_config_ranking_report(sweep).startswith("## Cost-Recovery Rank\n\n| Config")

    def test_a_community_report_names_its_homes_forecasts_under_its_title(self, sample_results: SimulationResults) -> None:
        """Its baseline is the homes' own grid flows, which their forecasts sized."""
        fleet = make_fleet_results_of(
            [replace(sample_results, grid_charge_forecast=each) for each in ("trailing_14_days", None, "pv_blind")]
        )

        report = generate_community_report(simulate_community(fleet, CommunityConfig(sharing_mode="p2p")))

        assert report.startswith(
            "# Community Energy Sharing Report\n\n" + _PV_BLIND_AND_TRAILING_NOTICE + "## Sharing Mode"
        )

    def test_a_community_report_whose_homes_did_not_grid_charge_has_no_notice(
        self, sample_results: SimulationResults
    ) -> None:
        fleet = make_fleet_results_of([sample_results, sample_results])

        report = generate_community_report(simulate_community(fleet, CommunityConfig(sharing_mode="p2p")))

        assert report.startswith("# Community Energy Sharing Report\n\n## Sharing Mode")
        assert "sized by" not in report


class TestExtrapolationNotice:
    """A board report whose bills are annualised from a window other than whole calendar years says so under its first heading."""

    @pytest.mark.parametrize("side_by_side", [False, True], ids=["physics-only", "side-by-side"])
    def test_a_finance_report_from_a_window_that_is_not_whole_calendar_years_says_so_under_its_title(
        self, side_by_side: bool
    ) -> None:
        dist = _annualised_from(make_window(days=2, first_day=date(2024, 3, 31)))

        report = generate_finance_report(dist, dist if side_by_side else None, scenario_name="Bristol")

        assert report.startswith(
            "# Finance Report: Bristol\n\n"
            "*Yearly figures are extrapolated ×183.000 from a 2-day window (2024-03-31 to 2024-04-01), "
            "not whole calendar years.*\n\n"
            "## Householder Bill"
        )

    @pytest.mark.parametrize(
        "window",
        [
            pytest.param(make_window(days=365, first_day=date(2023, 1, 1)), id="calendar-year-2023"),
            pytest.param(make_window(days=731, first_day=date(2023, 1, 1)), id="two-calendar-years"),
        ],
    )
    def test_a_finance_report_from_whole_calendar_years_has_no_notice(self, window: SimulationWindow) -> None:
        report = generate_finance_report(_annualised_from(window), scenario_name="Bristol")

        assert report == generate_finance_report(make_bill_distribution(), scenario_name="Bristol")
        assert "extrapolated" not in report

    def test_a_ranking_report_from_a_30_day_window_says_so_under_its_first_heading(self) -> None:
        sweep = _one_config_sweep(make_window(days=30, first_day=date(2024, 6, 1)))

        assert generate_config_ranking_report(sweep).startswith(
            "## Cost-Recovery Rank\n\n"
            "*Yearly figures are extrapolated ×12.200 from a 30-day window (2024-06-01 to 2024-06-30), "
            "not whole calendar years.*\n\n"
            "| Config"
        )

    def test_a_ranking_report_from_a_whole_calendar_year_has_no_notice(self) -> None:
        report = generate_config_ranking_report(_one_config_sweep(make_window(days=365, first_day=date(2023, 1, 1))))

        assert "extrapolated" not in report
        assert report.startswith("## Cost-Recovery Rank\n\n| Config")
