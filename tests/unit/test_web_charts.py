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
from solar_challenge.battery import BatteryConfig
from solar_challenge.home import SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.web.charts import (
    ChartAbsence,
    ChartPanel,
    ChartTab,
    battery_soc_chart,
    comparison_tabs,
    daily_energy_balance,
    financial_breakdown,
    fleet_results_tabs,
    heat_pump_analysis,
    home_results_tabs,
    monthly_summary,
    power_flow_timeline,
    sankey_diagram,
    seasonal_comparison,
)
from solar_challenge.web.simulation_params import parse_home_config
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._plotly_figure import annotation_texts, annotations_by_text, sankey_link_values, traces, traces_by_name
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results
from tests._steady_runs import steady_run
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for


def _one_day_summary(
    *,
    total_generation_kwh: float,
    total_demand_kwh: float,
    total_self_consumption_kwh: float,
    total_grid_import_kwh: float,
    total_grid_export_kwh: float,
    total_battery_charge_kwh: float,
    total_battery_discharge_kwh: float,
    total_grid_charge_kwh: float,
) -> SummaryStatistics:
    """A one-day run's summary with the totals given, so a test writes every total the Sankey reads."""
    return dataclasses.replace(
        calculate_summary(make_sim_results(days=1)),
        total_generation_kwh=total_generation_kwh,
        total_demand_kwh=total_demand_kwh,
        total_self_consumption_kwh=total_self_consumption_kwh,
        total_grid_import_kwh=total_grid_import_kwh,
        total_grid_export_kwh=total_grid_export_kwh,
        total_battery_charge_kwh=total_battery_charge_kwh,
        total_battery_discharge_kwh=total_battery_discharge_kwh,
        total_grid_charge_kwh=total_grid_charge_kwh,
    )


def _simulate_seg_rate_without_tariff(weather: pd.DataFrame) -> SimulationResults:
    """The run of a home requested with an SEG rate and no tariff, over the day *weather* starts on.

    The home is the one parse_home_config reads from the request; *weather* stands in for PVGIS's.
    """
    day = weather.index[0].date().isoformat()
    config, start_date, end_date, _name = parse_home_config(
        {
            "pv_kw": 4.0,
            "consumption_kwh": 3400.0,
            "seg": {"rate_pence_per_kwh": 15.0},
            "start": day,
            "end": day,
        }
    )
    return simulate_home(config, start_date=start_date, end_date=end_date, weather=weather_for(config, weather))


_SANKEY_REASON = "No energy flowed in this run: every flow is 0.01 kWh or less."


def _monthly_reason(days: int) -> ChartAbsence:
    return ChartAbsence(f"The monthly summary needs at least 90 days; this run covers {days}.")


def _seasonal_reason(days: int) -> ChartAbsence:
    return ChartAbsence(f"The seasonal comparison needs at least 180 days; this run covers {days}.")


def _drawn(panel: ChartPanel) -> bool:
    """Whether a chart builder whose chart can be absent drew it: its panel holds Plotly figure JSON, which holds data, rather than a ChartAbsence."""
    assert not isinstance(panel.content, str) or "data" in json.loads(panel.content)
    return isinstance(panel.content, str)


def _tab_layout(tabs: tuple[ChartTab, ...]) -> list[tuple[str, str, list[str]]]:
    """Each of *tabs* as its key, its label and its panels' ids, in order."""
    return [(tab.key, tab.label, [panel.dom_id for panel in tab.panels]) for tab in tabs]


class TestChartFunctions:
    """Tests for the centralized chart functions in charts.py."""

    def test_daily_energy_balance_returns_json(self) -> None:
        """Test daily_energy_balance returns a panel of Plotly figure JSON."""
        results = make_sinusoidal_sim_results(days=3)
        output = daily_energy_balance(results).content
        assert isinstance(output, str)
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

        assert sankey_link_values(sankey_diagram(summary).content) == {
            ("PV Generation", "Demand"): 42.0,
            ("PV Generation", "Battery"): 10.0,
            ("PV Generation", "Export"): 40.0,
            ("Grid", "Demand"): 30.0,
            ("Battery", "Demand"): 8.0,
        }

    def test_sankey_diagram_of_a_run_whose_every_flow_is_at_most_a_hundredth_of_a_kwh_says_no_energy_flowed(self) -> None:
        summary = _one_day_summary(
            total_generation_kwh=0.03,
            total_demand_kwh=0.02,
            total_self_consumption_kwh=0.01,
            total_grid_import_kwh=0.01,
            total_grid_export_kwh=0.01,
            total_battery_charge_kwh=0.01,
            total_battery_discharge_kwh=0.0,
            total_grid_charge_kwh=0.0,
        )

        assert sankey_diagram(summary).content == ChartAbsence(_SANKEY_REASON)

    def test_power_flow_timeline_returns_json(self) -> None:
        """Test power_flow_timeline returns a panel of Plotly figure JSON."""
        results = make_sinusoidal_sim_results(days=2)
        output = power_flow_timeline(results).content
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_battery_soc_chart_returns_json(self) -> None:
        """Test battery_soc_chart returns a panel of Plotly figure JSON."""
        results = make_sinusoidal_sim_results(days=2)
        output = battery_soc_chart(results, battery_config=BatteryConfig(capacity_kwh=10.0)).content
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_financial_breakdown_returns_json(self) -> None:
        """Test financial_breakdown returns a panel of Plotly figure JSON."""
        results = make_sinusoidal_sim_results(days=3)
        output = financial_breakdown(results).content
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_monthly_summary_of_a_short_run_names_the_rule_and_the_runs_days(self) -> None:
        assert monthly_summary(make_sinusoidal_sim_results(days=30)).content == _monthly_reason(30)

    def test_seasonal_comparison_of_a_short_run_names_the_rule_and_the_runs_days(self) -> None:
        assert seasonal_comparison(make_sinusoidal_sim_results(days=60)).content == _seasonal_reason(60)

    def test_heat_pump_analysis_refuses_a_run_without_a_heat_pump_load(self) -> None:
        with pytest.raises(ValueError, match="heat_pump_load"):
            heat_pump_analysis(make_sinusoidal_sim_results(days=2))

    def test_heat_pump_analysis_returns_the_load_share_panel_then_the_load_profile_panel(self) -> None:
        panels = heat_pump_analysis(steady_run("2024-06-01", "2024-06-01", heat_pump_kw=1.5, demand_kw=4.0))

        assert [panel.dom_id for panel in panels] == ["chart-hp-load-share", "chart-hp-load-profile"]


class TestChartDisplayGates:
    """Each display gate counts the calendar days of the run's window, which a timedelta overcounts by one across the autumn fall-back."""

    @pytest.mark.parametrize(
        ("last_day", "days", "drawn"),
        [
            pytest.param("2024-12-28", 89, False, id="89-days-not-drawn"),
            pytest.param("2024-12-29", 90, True, id="90-days-drawn"),
        ],
    )
    def test_monthly_summary_draws_only_a_window_of_at_least_90_calendar_days(
        self, last_day: str, days: int, drawn: bool
    ) -> None:
        results = steady_run("2024-10-01", last_day)
        assert results.window.days == days

        assert _drawn(monthly_summary(results)) is drawn

    @pytest.mark.parametrize(
        ("last_day", "days", "drawn"),
        [
            pytest.param("2024-12-26", 179, False, id="179-days-not-drawn"),
            pytest.param("2024-12-27", 180, True, id="180-days-drawn"),
        ],
    )
    def test_seasonal_comparison_draws_only_a_window_of_at_least_180_calendar_days(
        self, last_day: str, days: int, drawn: bool
    ) -> None:
        results = steady_run("2024-07-01", last_day)
        assert results.window.days == days

        assert _drawn(seasonal_comparison(results)) is drawn

    def test_a_run_of_61_calendar_days_across_the_autumn_fall_back_names_its_61_days_in_both_reasons(self) -> None:
        results = steady_run("2024-10-01", "2024-11-30")

        assert (monthly_summary(results).content, seasonal_comparison(results).content) == (
            _monthly_reason(61),
            _seasonal_reason(61),
        )


class TestBatterySocChartLimitLines:
    """battery_soc_chart draws a dashed line at each SOC limit Battery holds the run's battery between, the config's min and max SOC fractions of its SoH-derated capacity."""

    @pytest.mark.parametrize(
        ("battery_config", "limits_kwh"),
        [
            pytest.param(
                BatteryConfig(capacity_kwh=10.0),
                {"Min SOC": 1.0, "Max SOC": 9.0},
                id="defaults-at-full-health",
            ),
            pytest.param(
                BatteryConfig(capacity_kwh=8.0, min_soc_fraction=0.1, max_soc_fraction=0.95, soh=0.9),
                {"Min SOC": 0.72, "Max SOC": 6.84},
                id="soh-override-and-raised-max",
            ),
            pytest.param(
                BatteryConfig(capacity_kwh=10.0, min_soc_fraction=0.2, system_age_years=5.0),
                {"Min SOC": 1.8, "Max SOC": 8.1},
                id="calendar-faded-and-raised-min",
            ),
        ],
    )
    def test_each_dashed_line_marks_one_of_the_batterys_soc_limits(
        self, battery_config: BatteryConfig, limits_kwh: dict[str, float]
    ) -> None:
        """Five years of calendar fade at the default 2% a year leave the last battery at 90% SoH, as the override sets the second's."""
        figure = battery_soc_chart(make_sinusoidal_sim_results(days=1), battery_config).content
        shapes = json.loads(figure)["layout"]["shapes"]

        assert {text: annotation["y"] for text, annotation in annotations_by_text(figure).items()} == pytest.approx(
            limits_kwh
        )
        assert sorted(shape["y0"] for shape in shapes) == pytest.approx(sorted(limits_kwh.values()))
        assert sorted(shape["y1"] for shape in shapes) == pytest.approx(sorted(limits_kwh.values()))


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

        assert sankey_link_values(sankey_diagram(summary).content) == {
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

        assert sankey_link_values(sankey_diagram(summary).content) == {
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
        home = bristol_arbitrage_home()
        results = simulate_home(
            home,
            start_date=pd.Timestamp("2024-01-15"),
            end_date=pd.Timestamp("2024-01-15"),
            weather=weather_for(home, sunless_weather("2024-01-15", temp_air=8.0)),
        )
        summary = calculate_summary(results)

        links = sankey_link_values(sankey_diagram(summary).content)

        assert set(links) == {("Grid", "Demand"), ("Grid", "Battery"), ("Battery", "Demand")}
        assert links[("Grid", "Battery")] == round(summary.total_battery_charge_kwh, 2)
        received_by_demand = sum(kwh for (_, target), kwh in links.items() if target == "Demand")
        assert received_by_demand == pytest.approx(summary.total_demand_kwh, abs=0.01)


class TestChartTotals:
    """Each chart's totals are the run's per-minute amounts summed: kWh for power, £ as they are."""

    def test_heat_pump_share_is_the_runs_heat_pump_and_other_kwh(self) -> None:
        load_share, _ = heat_pump_analysis(steady_run("2024-06-01", "2024-06-01", heat_pump_kw=1.5, demand_kw=4.0))

        pie = traces(load_share.content)[0]

        # 1.5 kW × 24 h of heat pump, and 4 kW × 24 h of demand less that.
        assert pie["labels"] == ["Heat Pump", "Other Demand"]
        assert pie["values"] == [36.0, 60.0]

    def test_financial_bars_are_each_days_pounds(self) -> None:
        by_name = traces_by_name(
            financial_breakdown(
                steady_run("2024-06-01", "2024-06-02", import_cost_gbp=0.002, export_revenue_gbp=0.001)
            ).content
        )

        # £0.002 and £0.001 a minute, for 1440 minutes a day.
        assert by_name["Daily Cost"]["x"] == ["2024-06-01", "2024-06-02"]
        assert by_name["Daily Cost"]["y"] == [2.88, 2.88]
        assert by_name["Daily Revenue"]["y"] == [1.44, 1.44]


class TestFinancialBreakdownNetCostLine:
    """financial_breakdown's line is the run's net cost to date: its import cost less its export revenue, summed day by day."""

    def test_is_the_running_total_of_each_days_import_cost_less_its_export_revenue(self) -> None:
        line = traces_by_name(
            financial_breakdown(
                steady_run("2024-06-01", "2024-06-02", import_cost_gbp=0.002, export_revenue_gbp=0.001)
            ).content
        )["Cumulative Net Cost"]

        # £2.88 of import cost less £1.44 of export revenue each day.
        assert line["y"] == [1.44, 2.88]

    def test_ends_at_the_runs_net_cost_to_the_penny(self) -> None:
        """An ordinary priced home: its import cost exceeds its export revenue, so its line ends above zero, at the run's net cost.

        Its day totals are not whole pennies, so summing them rounded day by day would leave the line pennies off.
        """
        results = make_sinusoidal_sim_results(
            days=3, import_rate_gbp_per_kwh=0.30, export_rate_gbp_per_kwh=0.05
        )
        net_cost = calculate_summary(results).net_cost_gbp
        assert net_cost > 0

        line = traces_by_name(financial_breakdown(results).content)["Cumulative Net Cost"]

        assert line["y"][-1] == pytest.approx(net_cost, abs=0.005)

    def test_is_drawn_against_the_secondary_axis_titled_for_it(self) -> None:
        figure = financial_breakdown(
            make_sinusoidal_sim_results(days=2, import_rate_gbp_per_kwh=0.30, export_rate_gbp_per_kwh=0.05)
        ).content

        line = traces_by_name(figure)["Cumulative Net Cost"]

        assert line["yaxis"] == "y2"
        assert json.loads(figure)["layout"]["yaxis2"]["title"]["text"] == "Cumulative Net Cost (GBP)"

    def test_seasonal_bars_are_each_seasons_kwh_of_the_runs_own_flows(self) -> None:
        figure = seasonal_comparison(make_sim_results(self_kwh=876.0, export_kwh=1752.0, import_kwh=438.0, days=365)).content
        assert isinstance(figure, str)

        bars = {name: dict(zip(trace["x"], trace["y"])) for name, trace in traces_by_name(figure).items()}

        # make_sim_results spreads each total evenly over its 8,760 hourly rows from 2020-01-01:
        # 0.3, 0.15 and 0.1 kWh a row of generation, demand and self-consumption. 2020 is a leap
        # year, so the 365 days end on 30 December. Winter is then 2,160 rows (Jan, Feb and
        # Dec 1-30) and summer 2,208 (Jun-Aug).
        assert bars == {
            "Winter (Dec-Feb)": {"Generation (kWh)": 648.0, "Demand (kWh)": 324.0, "Self-Consumption (kWh)": 216.0},
            "Summer (Jun-Aug)": {"Generation (kWh)": 662.4, "Demand (kWh)": 331.2, "Self-Consumption (kWh)": 220.8},
        }


class TestFinancialBreakdownPricing:
    """Tests that financial_breakdown uses engine-priced series, not hardcoded rates."""

    def test_uses_engine_priced_series(self) -> None:
        """financial_breakdown must aggregate import_cost/export_revenue series directly."""
        results = make_sinusoidal_sim_results(
            days=2, import_rate_gbp_per_kwh=0.30, export_rate_gbp_per_kwh=0.05
        )

        by_name = traces_by_name(financial_breakdown(results).content)

        assert by_name["Daily Cost"]["y"] == results.import_cost.resample("D").sum().round(2).tolist()
        assert by_name["Daily Revenue"]["y"] == results.export_revenue.resample("D").sum().round(2).tolist()

    def test_an_unpriced_run_is_drawn_at_zero_pounds_though_it_imports_and_exports(self) -> None:
        results = make_sinusoidal_sim_results(days=2)
        peak_import_kw = results.grid_import.max()
        peak_export_kw = results.grid_export.max()
        assert peak_import_kw > 0
        assert peak_export_kw > 0

        by_name = traces_by_name(financial_breakdown(results).content)

        assert by_name["Daily Cost"]["y"] == [0.0, 0.0]
        assert by_name["Daily Revenue"]["y"] == [0.0, 0.0]


class TestFinancialBreakdownNoTariffAnnotation:
    """financial_breakdown notes on its chart that cost tracking is unavailable exactly when the run's import is not priced.

    It notes that revenue tracking is unavailable too when the run earns no export revenue.
    """

    @pytest.mark.parametrize(
        ("import_rate", "export_rate", "notes"),
        [
            pytest.param(
                0.0,
                0.0,
                ["No tariff configured — cost and revenue tracking unavailable"],
                id="unpriced",
            ),
            pytest.param(0.30, 0.0, [], id="import-priced-only"),
            pytest.param(
                0.0,
                0.05,
                ["No import tariff configured — cost tracking unavailable"],
                id="export-priced-only",
            ),
            pytest.param(0.30, 0.05, [], id="import-and-export-priced"),
        ],
    )
    def test_is_drawn_exactly_when_import_is_not_priced_and_names_revenue_too_when_export_is_not_either(
        self, import_rate: float, export_rate: float, notes: list[str]
    ) -> None:
        results = make_sinusoidal_sim_results(
            days=2, import_rate_gbp_per_kwh=import_rate, export_rate_gbp_per_kwh=export_rate
        )

        assert annotation_texts(financial_breakdown(results).content) == notes

    @pytest.mark.parametrize(
        "export_rate",
        [pytest.param(0.0, id="export-unpriced"), pytest.param(0.05, id="export-priced")],
    )
    def test_is_not_drawn_for_a_run_whose_import_is_priced_though_it_imports_nothing(
        self, export_rate: float
    ) -> None:
        results = make_sinusoidal_sim_results(
            days=2,
            demand_kw=0.0,
            import_rate_gbp_per_kwh=0.30,
            export_rate_gbp_per_kwh=export_rate,
        )
        assert results.grid_import.max() == 0

        assert annotation_texts(financial_breakdown(results).content) == []

    def test_a_simulated_run_with_an_seg_rate_and_no_tariff_notes_that_no_import_tariff_is_configured(
        self,
    ) -> None:
        """simulate_home prices such a run's export and leaves its import unpriced."""
        results = _simulate_seg_rate_without_tariff(synthetic_june_weather("2024-06-21"))

        assert results.grid_import.sum() > 0
        assert results.export_revenue.sum() > 0
        assert annotation_texts(financial_breakdown(results).content) == [
            "No import tariff configured — cost tracking unavailable"
        ]

    def test_a_simulated_run_with_an_seg_rate_and_no_tariff_notes_revenue_tracking_unavailable_when_it_exports_nothing(
        self,
    ) -> None:
        """The note's revenue half is false for this run: its SEG rate is set, and its £0 revenue is tracked.

        SimulationResults records no export rate, so the chart cannot tell this run from one with no SEG rate.
        A structured pricing fact on the results (task 667) would change this reading.
        """
        results = _simulate_seg_rate_without_tariff(sunless_weather("2024-01-15", temp_air=8.0))

        assert results.grid_import.sum() > 0
        assert results.grid_export.sum() == 0
        assert annotation_texts(financial_breakdown(results).content) == [
            "No tariff configured — cost and revenue tracking unavailable"
        ]


class TestResultsTabs:
    """Each page's assembler lists, tab by tab, the panels of the charts that apply to its run.

    A home's battery chart applies only to a home with a battery, and its heat-pump charts only to a run with a
    heat-pump load.
    """

    def test_a_home_with_a_battery_and_a_heat_pump_load_lists_every_home_chart(self) -> None:
        year = make_sim_results()
        results = dataclasses.replace(year, heat_pump_load=pd.Series(0.3, index=year.demand.index))

        tabs = home_results_tabs(
            make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)), results, calculate_summary(results)
        )

        assert _tab_layout(tabs) == [
            ("overview", "Overview", ["chart-sankey", "chart-daily-balance"]),
            ("power_flow", "Power Flow", ["chart-power-flow"]),
            ("battery_finance", "Battery & Finance", ["chart-battery-soc", "chart-financial", "chart-monthly"]),
            ("analysis", "Analysis", ["chart-seasonal", "chart-hp-load-share", "chart-hp-load-profile"]),
        ]

    def test_a_home_without_a_battery_or_a_heat_pump_load_lists_neither_their_charts(self) -> None:
        results = make_sim_results(days=1)

        tabs = home_results_tabs(make_home_config(), results, calculate_summary(results))

        assert _tab_layout(tabs) == [
            ("overview", "Overview", ["chart-sankey", "chart-daily-balance"]),
            ("power_flow", "Power Flow", ["chart-power-flow"]),
            ("battery_finance", "Battery & Finance", ["chart-financial", "chart-monthly"]),
            ("analysis", "Analysis", ["chart-seasonal"]),
        ]

    def test_a_fleet_lists_every_fleet_chart(self) -> None:
        home_summaries = [calculate_summary(make_sim_results(days=1))] * 2

        tabs = fleet_results_tabs(make_fleet_results(n_homes=2, days=1), home_summaries)

        assert _tab_layout(tabs) == [
            ("aggregate", "Aggregate", ["chart-aggregate-timeline", "chart-grid-impact"]),
            ("per_home", "Per-Home", ["chart-heatmap", "chart-box-plots"]),
            ("distributions", "Distributions", ["chart-distribution-histograms"]),
        ]

    def test_a_comparison_lists_the_energy_totals_and_the_efficiency_ratios(self) -> None:
        summary = dataclasses.asdict(calculate_summary(make_sim_results(days=1)))

        tabs = comparison_tabs([summary, summary], ["Run A", "Run B"])

        assert _tab_layout(tabs) == [
            ("bar", "Energy Totals", ["chart-comparison-bar"]),
            ("radar", "Efficiency Ratios", ["chart-comparison-radar"]),
        ]
