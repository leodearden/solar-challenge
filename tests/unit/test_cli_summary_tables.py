"""Tests of the summary tables `home run`, `home quick` and `fleet run` print: the (metric, value) rows cli.utils builds from a home's SummaryStatistics and from a fleet's FleetSummary."""

import dataclasses

import pytest

from solar_challenge.cli.utils import fleet_summary_rows, home_summary_rows
from solar_challenge.fleet import FleetSummary
from solar_challenge.home import SummaryStatistics

_FLEET_MONEY_FIELDS_AND_METRICS = [
    ("total_import_cost_gbp", "Grid Import Cost"),
    ("total_export_revenue_gbp", "Grid Export Revenue"),
    ("total_net_cost_gbp", "Net Cost"),
    ("total_seg_revenue_gbp", "SEG Revenue"),
]


def _home_summary(**changes: float | None) -> SummaryStatistics:
    """A one-day home summary with its SEG revenue set, and with changes applied."""
    return dataclasses.replace(
        SummaryStatistics(
            total_generation_kwh=10.0,
            total_demand_kwh=8.0,
            total_self_consumption_kwh=6.0,
            total_grid_import_kwh=2.0,
            total_grid_export_kwh=4.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=3.5,
            peak_demand_kw=2.5,
            self_consumption_ratio=0.6,
            grid_dependency_ratio=0.25,
            export_ratio=0.4,
            simulation_days=1,
            total_import_cost_gbp=0.56,
            total_export_revenue_gbp=0.24,
            net_cost_gbp=0.32,
            seg_revenue_gbp=1.23,
        ),
        **changes,
    )


def _fleet_summary_without_money_figures() -> FleetSummary:
    """A three-home, two-day fleet summary built from its required fields alone, so its Optional money figures keep their None defaults."""
    return FleetSummary(
        n_homes=3,
        total_generation_kwh=30.0,
        total_demand_kwh=24.0,
        total_self_consumption_kwh=18.6,
        total_grid_import_kwh=6.0,
        total_grid_export_kwh=11.4,
        fleet_self_consumption_ratio=0.62,
        fleet_grid_dependency_ratio=0.25,
        per_home_generation_min_kwh=8.0,
        per_home_generation_max_kwh=12.0,
        per_home_generation_mean_kwh=10.0,
        per_home_generation_median_kwh=10.0,
        per_home_self_consumption_ratio_min=0.5,
        per_home_self_consumption_ratio_max=0.7,
        per_home_self_consumption_ratio_mean=0.58,
        simulation_days=2,
    )


def _fleet_summary(**changes: float | None) -> FleetSummary:
    """That fleet summary with every money figure set too, and with changes applied.

    Its fleet ratio differs from its homes' mean, and its net cost from its import cost and export revenue, so a row that reads the wrong field shows.
    """
    every_field_set = dataclasses.replace(
        _fleet_summary_without_money_figures(),
        total_seg_revenue_gbp=0.47,
        per_home_seg_revenue_mean_gbp=0.16,
        total_net_cost_gbp=0.9,
        total_import_cost_gbp=1.68,
        total_export_revenue_gbp=0.78,
    )
    return dataclasses.replace(every_field_set, **changes)


class TestHomeSummaryRows:
    """Tests of home_summary_rows, the rows `home run` and `home quick` print."""

    def test_a_home_summary_gives_its_energy_ratio_day_and_money_rows(self) -> None:
        """The rows are the home's five energy totals, its two ratios, its days and its four money figures, in that order."""
        assert home_summary_rows(_home_summary()) == (
            ("Total Generation", "10.0 kWh"),
            ("Total Demand", "8.0 kWh"),
            ("Self-Consumption", "6.0 kWh"),
            ("Grid Import", "2.0 kWh"),
            ("Grid Export", "4.0 kWh"),
            ("Self-Consumption Ratio", "60.0%"),
            ("Grid Dependency", "25.0%"),
            ("Simulation Days", "1"),
            ("Grid Import Cost", "£0.56"),
            ("Grid Export Revenue", "£0.24"),
            ("Net Cost", "£0.32"),
            ("SEG Revenue", "£1.23"),
        )

    def test_a_home_summary_without_seg_revenue_has_no_seg_revenue_row(self) -> None:
        """A home summary with no SEG revenue gives the same rows less the SEG Revenue row."""
        full_rows = home_summary_rows(_home_summary())

        rows = home_summary_rows(_home_summary(seg_revenue_gbp=None))

        assert rows == tuple(row for row in full_rows if row != ("SEG Revenue", "£1.23"))


class TestFleetSummaryRows:
    """Tests of fleet_summary_rows, the rows `fleet run` prints."""

    def test_a_fleet_summary_gives_its_fleet_ratios_money_and_per_home_spread(self) -> None:
        """The rows are the fleet's energy totals, its own two ratios, its homes, its days and its money figures, then, after a blank row, the spread of its homes' generation and self-consumption ratios."""
        assert fleet_summary_rows(_fleet_summary()) == (
            ("Total Generation", "30.0 kWh"),
            ("Total Demand", "24.0 kWh"),
            ("Self-Consumption", "18.6 kWh"),
            ("Grid Import", "6.0 kWh"),
            ("Grid Export", "11.4 kWh"),
            ("Self-Consumption Ratio", "62.0%"),
            ("Grid Dependency", "25.0%"),
            ("Number of Homes", "3"),
            ("Simulation Days", "2"),
            ("Grid Import Cost", "£1.68"),
            ("Grid Export Revenue", "£0.78"),
            ("Net Cost", "£0.90"),
            ("SEG Revenue", "£0.47"),
            ("", ""),
            ("Per-Home Generation (min/max)", "8.0 / 12.0 kWh"),
            ("Per-Home Generation (mean)", "10.0 kWh"),
            ("Self-Consumption Ratio (min/max)", "50.0% / 70.0%"),
            ("Self-Consumption Ratio (mean)", "58.0%"),
        )

    @pytest.mark.parametrize(("field", "metric"), _FLEET_MONEY_FIELDS_AND_METRICS)
    def test_a_money_figure_the_fleet_summary_lacks_prints_no_row(self, field: str, metric: str) -> None:
        """A money figure that is None takes its own row out and leaves every other row as it was."""
        full_rows = fleet_summary_rows(_fleet_summary())

        rows = fleet_summary_rows(_fleet_summary(**{field: None}))

        assert rows == tuple(row for row in full_rows if row[0] != metric)

    def test_a_fleet_summary_built_without_money_figures_prints_none_of_them(self) -> None:
        """A fleet summary built directly, its money figures left at their None defaults, gives no money row."""
        rows = fleet_summary_rows(_fleet_summary_without_money_figures())

        money_metrics = {metric for _field, metric in _FLEET_MONEY_FIELDS_AND_METRICS}
        assert [metric for metric, _value in rows if metric in money_metrics] == []
