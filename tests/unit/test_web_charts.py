# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.charts's chart builders, called directly.

An invariant that every chart shares is tested in a module of its own beside this one:
test_web_chart_colours.py, test_web_chart_downsampling.py and test_web_chart_energy_flows.py.
"""

import dataclasses
import json

import pandas as pd
import pytest

pytest.importorskip("plotly")
from solar_challenge.home import SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.web.charts import (
    battery_soc_chart,
    daily_energy_balance,
    financial_breakdown,
    heat_pump_analysis,
    monthly_summary,
    power_flow_timeline,
    sankey_diagram,
    seasonal_comparison,
)
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._finance_builders import make_sim_results
from tests._plotly_figure import sankey_link_values
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results
from tests._synthetic_weather import sunless_weather


def _steady_run(
    days: int,
    *,
    demand_kw: float = 0.0,
    heat_pump_kw: float | None = None,
    import_cost_gbp: float = 0.0,
    export_revenue_gbp: float = 0.0,
) -> SimulationResults:
    """A run of ``days`` days at one row a minute, every series steady.

    Demand, heat pump, import cost and export revenue are at the levels given,
    every other series is zero, and there is no heat pump unless heat_pump_kw is given.
    """
    index = pd.date_range("2024-06-01", periods=days * 1440, freq="min", tz="Europe/London")

    def steady(level: float) -> pd.Series:
        return pd.Series(level, index=index)

    return SimulationResults(
        generation=steady(0.0),
        demand=steady(demand_kw),
        self_consumption=steady(0.0),
        battery_charge=steady(0.0),
        battery_discharge=steady(0.0),
        battery_soc=steady(0.0),
        grid_import=steady(0.0),
        grid_export=steady(0.0),
        import_cost=steady(import_cost_gbp),
        export_revenue=steady(export_revenue_gbp),
        tariff_rate=steady(0.0),
        heat_pump_load=None if heat_pump_kw is None else steady(heat_pump_kw),
    )


def _one_day_summary(**totals: float) -> SummaryStatistics:
    """A one-day run's summary with the totals given, so a test writes every total the Sankey reads."""
    return dataclasses.replace(calculate_summary(make_sim_results(days=1)), **totals)


class TestChartFunctions:
    """Tests for the centralized chart functions in charts.py."""

    def test_daily_energy_balance_returns_json(self) -> None:
        """Test daily_energy_balance returns a non-empty JSON string."""
        results = make_sinusoidal_sim_results(days=3)
        output = daily_energy_balance(results)
        assert isinstance(output, str)
        assert len(output) > 2  # more than just "{}"
        parsed = json.loads(output)
        assert "data" in parsed

    def test_sankey_links_are_the_summarys_energy_flows(self) -> None:
        """Each link is one of the summary's flows, PV used directly being self-consumption less battery discharge.

        The summary is calculate_summary's, so renaming a field the sankey reads fails this test.
        """
        summary = dataclasses.replace(
            calculate_summary(
                make_sim_results(self_kwh=50.0, export_kwh=40.0, import_kwh=30.0, discharge_kwh=8.0, days=1)
            ),
            total_battery_charge_kwh=10.0,
        )

        assert sankey_link_values(sankey_diagram(summary)) == {
            ("PV Generation", "Demand"): 42.0,
            ("PV Generation", "Battery"): 10.0,
            ("PV Generation", "Export"): 40.0,
            ("Grid", "Demand"): 30.0,
            ("Battery", "Demand"): 8.0,
        }

    def test_power_flow_timeline_returns_json(self) -> None:
        """Test power_flow_timeline returns a non-empty JSON string."""
        results = make_sinusoidal_sim_results(days=2)
        output = power_flow_timeline(results)
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_battery_soc_chart_returns_json(self) -> None:
        """Test battery_soc_chart returns a non-empty JSON string."""
        results = make_sinusoidal_sim_results(days=2)
        output = battery_soc_chart(results, battery_capacity_kwh=10.0)
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_financial_breakdown_returns_json(self) -> None:
        """Test financial_breakdown returns a non-empty JSON string."""
        results = make_sinusoidal_sim_results(days=3)
        output = financial_breakdown(results)
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_monthly_summary_returns_none_for_short_sim(self) -> None:
        """Test monthly_summary returns None when simulation < 90 days."""
        results = make_sinusoidal_sim_results(days=30)
        output = monthly_summary(results)
        assert output is None

    def test_seasonal_comparison_returns_none_for_short_sim(self) -> None:
        """Test seasonal_comparison returns None when simulation < 180 days."""
        results = make_sinusoidal_sim_results(days=60)
        output = seasonal_comparison(results)
        assert output is None

    def test_heat_pump_analysis_returns_none_without_hp(self) -> None:
        """Test heat_pump_analysis returns None when no heat pump data."""
        results = make_sinusoidal_sim_results(days=2)
        output = heat_pump_analysis(results)
        assert output is None


class TestSankeyBatteryCharge:
    """The battery charges from PV and, on a grid-charging tariff, from the grid, and the Sankey draws each source's part as its own link."""

    def test_a_sunless_grid_charging_day_charges_the_battery_from_the_grid(self) -> None:
        """With no sun, the grid supplies the battery's charge as well as the demand the battery does not meet."""
        summary = _one_day_summary(
            total_generation_kwh=0.0,
            total_demand_kwh=11.75,
            total_self_consumption_kwh=4.0,
            total_grid_import_kwh=9.75,
            total_grid_export_kwh=0.0,
            total_battery_charge_kwh=2.0,
            total_battery_discharge_kwh=4.0,
            total_grid_charge_kwh=2.0,
        )

        assert sankey_link_values(sankey_diagram(summary)) == {
            ("Grid", "Battery"): 2.0,
            ("Grid", "Demand"): 7.75,
            ("Battery", "Demand"): 4.0,
        }

    def test_a_day_charging_from_pv_and_the_grid_draws_each_sources_part(self) -> None:
        """Every node balances: PV sends its 10 kWh, the grid its 8, the battery takes 5, and demand receives its 12."""
        summary = _one_day_summary(
            total_generation_kwh=10.0,
            total_demand_kwh=12.0,
            total_self_consumption_kwh=6.0,
            total_grid_import_kwh=8.0,
            total_grid_export_kwh=3.0,
            total_battery_charge_kwh=5.0,
            total_battery_discharge_kwh=2.0,
            total_grid_charge_kwh=2.0,
        )

        assert sankey_link_values(sankey_diagram(summary)) == {
            ("PV Generation", "Demand"): 4.0,
            ("PV Generation", "Battery"): 3.0,
            ("PV Generation", "Export"): 3.0,
            ("Grid", "Demand"): 6.0,
            ("Grid", "Battery"): 2.0,
            ("Battery", "Demand"): 2.0,
        }

    def test_a_simulated_sunless_grid_charging_day_draws_nothing_from_pv(self) -> None:
        """The home of scenarios/bristol-arbitrage.yaml on a sunless January day: all of the battery's charge comes from the grid.

        The summary is calculate_summary's of simulate_home's results, the summary /results/home loads and draws.
        """
        results = simulate_home(
            bristol_arbitrage_home(),
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather_data=sunless_weather("2024-01-15", temp_air=8.0),
        )
        summary = calculate_summary(results)

        links = sankey_link_values(sankey_diagram(summary))

        assert set(links) == {("Grid", "Demand"), ("Grid", "Battery"), ("Battery", "Demand")}
        assert links[("Grid", "Battery")] == round(summary.total_battery_charge_kwh, 2)
        received_by_demand = sum(kwh for (_, target), kwh in links.items() if target == "Demand")
        assert received_by_demand == pytest.approx(summary.total_demand_kwh, abs=0.01)


class TestChartTotals:
    """Each chart's totals are the run's per-minute amounts summed: kWh for power, £ as they are."""

    def test_heat_pump_share_is_the_runs_heat_pump_and_other_kwh(self) -> None:
        charts = heat_pump_analysis(_steady_run(1, heat_pump_kw=1.5, demand_kw=4.0))
        assert charts is not None

        pie = json.loads(charts["load_share_chart"])["data"][0]

        # 1.5 kW × 24 h of heat pump, and 4 kW × 24 h of demand less that.
        assert pie["labels"] == ["Heat Pump", "Other Demand"]
        assert pie["values"] == [36.0, 60.0]

    def test_financial_bars_are_each_days_pounds(self) -> None:
        figure = json.loads(
            financial_breakdown(_steady_run(2, import_cost_gbp=0.002, export_revenue_gbp=0.001))
        )

        traces = {trace["name"]: trace for trace in figure["data"]}

        # £0.002 and £0.001 a minute, for 1440 minutes a day.
        assert traces["Daily Cost"]["x"] == ["2024-06-01", "2024-06-02"]
        assert traces["Daily Cost"]["y"] == [2.88, 2.88]
        assert traces["Daily Revenue"]["y"] == [1.44, 1.44]
        assert traces["Cumulative Net Savings"]["y"] == [-1.44, -2.88]
