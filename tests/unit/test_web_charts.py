# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.charts's chart builders, called directly.

An invariant that every chart shares is tested in a module of its own beside this one:
tests/unit/test_web_chart_colours.py, tests/unit/test_web_chart_downsampling.py and tests/unit/test_web_chart_energy_flows.py.
"""

import dataclasses
import json
from typing import TypeVar

import pandas as pd
import pytest

pytest.importorskip("plotly")
from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetSummary, calculate_fleet_summary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.charts import (
    ChartPanel,
    ChartTab,
    ComparedRun,
    battery_soc_chart,
    comparison_bar_chart,
    comparison_radar,
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
from solar_challenge.web.storage import run_headline
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._chart_absences import SANKEY_REASON, monthly_reason, seasonal_reason
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


def _priced_home(*, tariff: bool, seg: bool) -> HomeConfig:
    """make_home_config's home, on a 30 p/kWh flat tariff if *tariff* and paid a 5 p/kWh SEG if *seg*."""
    return dataclasses.replace(
        make_home_config(),
        tariff_config=TariffConfig.flat_rate(0.30) if tariff else None,
        seg_tariff=SEGTariff(name="", rate_pence_per_kwh=5.0) if seg else None,
    )


def _simulate_seg_rate_without_tariff(weather: pd.DataFrame) -> tuple[HomeConfig, SimulationResults]:
    """A home requested with an SEG rate and no tariff, and its run over the day *weather* starts on.

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
    return config, simulate_home(config, start_date=start_date, end_date=end_date, weather=weather_for(config, weather))


def _summary_of_the_arbitrage_home_on_a_clear_21_june() -> SummaryStatistics:
    """The summary of the home of scenarios/bristol-arbitrage.yaml on a clear 21 June, when it charges its battery from PV and from the grid."""
    home = bristol_arbitrage_home()
    return calculate_summary(
        simulate_home(
            home,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather=weather_for(home, synthetic_june_weather("2024-06-21")),
        )
    )


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

        assert sankey_diagram(summary).absence_reason == SANKEY_REASON

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
        output = financial_breakdown(results, make_home_config()).content
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_monthly_summary_of_a_short_run_names_the_rule_and_the_runs_days(self) -> None:
        assert monthly_summary(make_sinusoidal_sim_results(days=30)).absence_reason == monthly_reason(30)

    def test_seasonal_comparison_of_a_short_run_names_the_rule_and_the_runs_days(self) -> None:
        assert seasonal_comparison(make_sinusoidal_sim_results(days=60)).absence_reason == seasonal_reason(60)

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

        assert (monthly_summary(results).absence_reason, seasonal_comparison(results).absence_reason) == (
            monthly_reason(61),
            seasonal_reason(61),
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

    def test_a_simulated_sunny_grid_charging_day_draws_the_batterys_charge_from_each_source_as_the_summary_splits_it(
        self,
    ) -> None:
        summary = _summary_of_the_arbitrage_home_on_a_clear_21_june()
        assert summary.total_pv_charge_kwh > 0.01 and summary.total_grid_charge_kwh > 0.01

        links = sankey_link_values(sankey_diagram(summary).content)

        assert links[("PV Generation", "Battery")] == round(summary.total_pv_charge_kwh, 2)
        assert links[("Grid", "Battery")] == round(summary.total_grid_charge_kwh, 2)


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
                steady_run("2024-06-01", "2024-06-02", import_cost_gbp=0.002, export_revenue_gbp=0.001),
                _priced_home(tariff=True, seg=True),
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
                steady_run("2024-06-01", "2024-06-02", import_cost_gbp=0.002, export_revenue_gbp=0.001),
                _priced_home(tariff=True, seg=True),
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

        figure = financial_breakdown(results, _priced_home(tariff=True, seg=True)).content
        line = traces_by_name(figure)["Cumulative Net Cost"]

        assert line["y"][-1] == pytest.approx(net_cost, abs=0.005)

    def test_is_drawn_against_the_secondary_axis_titled_for_it(self) -> None:
        figure = financial_breakdown(
            make_sinusoidal_sim_results(days=2, import_rate_gbp_per_kwh=0.30, export_rate_gbp_per_kwh=0.05),
            _priced_home(tariff=True, seg=True),
        ).content

        line = traces_by_name(figure)["Cumulative Net Cost"]

        assert line["yaxis"] == "y2"
        assert json.loads(figure)["layout"]["yaxis2"]["title"]["text"] == "Cumulative Net Cost (GBP)"

    def test_seasonal_bars_are_each_seasons_kwh_of_the_runs_own_flows(self) -> None:
        figure = seasonal_comparison(make_sim_results(self_kwh=876.0, export_kwh=1752.0, import_kwh=438.0, days=365)).content
        assert isinstance(figure, str)

        bars = {name: dict(zip(trace["x"], trace["y"])) for name, trace in traces_by_name(figure).items()}

        # make_sim_results spreads each total evenly over its 8,760 hourly rows from 2021-01-01:
        # 0.3, 0.15 and 0.1 kWh a row of generation, demand and self-consumption. 2021 is not a
        # leap year, so the 365 days end on 31 December. Winter is then 2,160 rows (Jan, Feb's
        # 28 days and Dec) and summer 2,208 (Jun-Aug).
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

        by_name = traces_by_name(financial_breakdown(results, _priced_home(tariff=True, seg=True)).content)

        assert by_name["Daily Cost"]["y"] == results.import_cost.resample("D").sum().round(2).tolist()
        assert by_name["Daily Revenue"]["y"] == results.export_revenue.resample("D").sum().round(2).tolist()

    def test_an_unpriced_run_is_drawn_at_zero_pounds_though_it_imports_and_exports(self) -> None:
        results = make_sinusoidal_sim_results(days=2)
        peak_import_kw = results.grid_import.max()
        peak_export_kw = results.grid_export.max()
        assert peak_import_kw > 0
        assert peak_export_kw > 0

        by_name = traces_by_name(financial_breakdown(results, make_home_config()).content)

        assert by_name["Daily Cost"]["y"] == [0.0, 0.0]
        assert by_name["Daily Revenue"]["y"] == [0.0, 0.0]


class TestFinancialBreakdownNoTariffAnnotation:
    """financial_breakdown notes on its chart that cost tracking is unavailable exactly when the home the run simulated sets no import tariff.

    It notes that revenue tracking is unavailable too when that home sets no SEG either.
    """

    @pytest.mark.parametrize(
        ("tariff", "seg", "notes"),
        [
            pytest.param(
                False,
                False,
                ["No tariff configured — cost and revenue tracking unavailable"],
                id="neither",
            ),
            pytest.param(
                False,
                True,
                ["No import tariff configured — cost tracking unavailable"],
                id="seg-only",
            ),
            pytest.param(True, False, [], id="tariff-only"),
            pytest.param(True, True, [], id="tariff-and-seg"),
        ],
    )
    def test_is_drawn_exactly_when_the_home_sets_no_tariff_and_names_revenue_too_when_it_sets_no_seg(
        self, tariff: bool, seg: bool, notes: list[str]
    ) -> None:
        """Every case draws the same unpriced run, so the note reads the home and not the run's rates."""
        results = make_sinusoidal_sim_results(days=2)

        assert annotation_texts(financial_breakdown(results, _priced_home(tariff=tariff, seg=seg)).content) == notes

    def test_a_simulated_run_with_an_seg_rate_and_no_tariff_notes_that_no_import_tariff_is_configured(
        self,
    ) -> None:
        """simulate_home prices such a run's export and leaves its import unpriced."""
        config, results = _simulate_seg_rate_without_tariff(synthetic_june_weather("2024-06-21"))

        assert results.grid_import.sum() > 0
        assert results.export_revenue.sum() > 0
        assert annotation_texts(financial_breakdown(results, config).content) == [
            "No import tariff configured — cost tracking unavailable"
        ]

    def test_a_simulated_run_with_an_seg_rate_and_no_tariff_that_exports_nothing_notes_only_that_no_import_tariff_is_configured(
        self,
    ) -> None:
        """Its SEG rate is set, so its £0 revenue is tracked, though it exports nothing."""
        config, results = _simulate_seg_rate_without_tariff(sunless_weather("2024-01-15", temp_air=8.0))

        assert results.grid_import.sum() > 0
        assert results.grid_export.sum() == 0
        assert annotation_texts(financial_breakdown(results, config).content) == [
            "No import tariff configured — cost tracking unavailable"
        ]


def _compared(label: str, summary: SummaryStatistics | FleetSummary) -> ComparedRun:
    """The compared run labelled *label* of the run whose summary is *summary*."""
    return ComparedRun(label, run_headline(summary))


def _b11_fleet() -> FleetSummary:
    """B11's fleet: each of two homes self-consumes 18 and exports 54 of the 72 kWh it generates, and imports 27 of the 45 it uses."""
    return calculate_fleet_summary(make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1))


def _a_day_of_a_plain_home() -> SummaryStatistics:
    return calculate_summary(make_sim_results(days=1))


_FIVE_FLOWS = ["Generation", "Demand", "Self-Consumption", "Grid Import", "Grid Export"]
_THREE_RATIO_AXES = ["Self-Consumption %", "Grid Dependency %", "Export %"]
_PV_STORED_AXIS = "PV stored in battery %"

_Point = TypeVar("_Point")


def _closed(polygon: list[_Point]) -> list[_Point]:
    """*polygon*'s points closed on its first, as a radar trace draws them."""
    return [*polygon, polygon[0]]


class TestComparisonCharts:
    """comparison_bar_chart and comparison_radar: each compared run drawn from its headline, under its label.

    The radar draws only the axes every compared run has a figure for, and notes each axis it
    leaves out, naming the runs without it: a fleet run has no PV stored in battery.
    """

    def test_a_compared_run_with_a_blank_label_is_refused_naming_its_label(self) -> None:
        with pytest.raises(ValueError) as refusal:
            _compared("  ", _a_day_of_a_plain_home())

        assert "ComparedRun.label" in str(refusal.value)

    def test_the_bar_chart_draws_each_run_s_five_energy_totals_in_flow_order_under_its_label(self) -> None:
        home = _compared("Home A", _a_day_of_a_plain_home())

        figure = comparison_bar_chart([home, _compared("Fleet B", _b11_fleet())]).content

        totals = home.headline
        home_kwh = (
            totals.generation_kwh,
            totals.demand_kwh,
            totals.self_consumption_kwh,
            totals.grid_import_kwh,
            totals.grid_export_kwh,
        )
        assert [(bar["name"], bar["x"], bar["y"]) for bar in traces(figure)] == [
            ("Home A", _FIVE_FLOWS, [round(kwh, 2) for kwh in home_kwh]),
            ("Fleet B", _FIVE_FLOWS, [144.0, 90.0, 36.0, 54.0, 108.0]),
        ]

    def test_the_radar_of_a_home_run_and_a_fleet_run_draws_the_fleet_at_its_own_ratios_and_notes_the_axis_it_lacks(
        self,
    ) -> None:
        """B11: the fleet was drawn at 0 % on every axis while the radar read a fleet summary by a home summary's names."""
        home = _compared("Home A", _a_day_of_a_plain_home())

        figure = comparison_radar([home, _compared("Fleet B", _b11_fleet())]).content

        radar = traces_by_name(figure)
        assert (radar["Fleet B"]["r"], radar["Fleet B"]["theta"]) == ([25.0, 60.0, 75.0, 25.0], _closed(_THREE_RATIO_AXES))
        ratios = (home.headline.self_consumption_ratio, home.headline.grid_dependency_ratio, home.headline.export_ratio)
        assert (radar["Home A"]["r"], radar["Home A"]["theta"]) == (
            _closed([round(ratio * 100, 1) for ratio in ratios]),
            _closed(_THREE_RATIO_AXES),
        )
        assert annotation_texts(figure) == ["PV stored in battery % is left out: no figure for Fleet B"]

    def test_the_radar_of_two_home_runs_draws_all_four_axes_and_no_note(self) -> None:
        runs = [
            _compared("Home A", _a_day_of_a_plain_home()),
            _compared("Home B", calculate_summary(make_sim_results(self_kwh=30.0, days=1))),
        ]

        figure = comparison_radar(runs).content

        assert [trace["theta"] for trace in traces(figure)] == [_closed([*_THREE_RATIO_AXES, _PV_STORED_AXIS])] * 2
        assert annotation_texts(figure) == []

    def test_the_pv_stored_axis_of_a_grid_charging_home_counts_only_the_pv_its_battery_stored(self) -> None:
        """B11: the axis once counted the battery's whole charge, grid charge included, as its share of the generation."""
        summary = _summary_of_the_arbitrage_home_on_a_clear_21_june()
        assert summary.total_grid_charge_kwh > 0.01
        assert round(summary.total_pv_charge_kwh / summary.total_generation_kwh * 100, 1) != round(
            summary.total_battery_charge_kwh / summary.total_generation_kwh * 100, 1
        ), "the PV-stored share rounds to the battery's whole charge's share, so a radar drawing that passes"

        figure = comparison_radar([_compared("Arbitrage", summary), _compared("Plain", _a_day_of_a_plain_home())]).content

        assert traces_by_name(figure)["Arbitrage"]["r"][3] == round(
            summary.total_pv_charge_kwh / summary.total_generation_kwh * 100, 1
        )


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

    def test_the_financial_panel_notes_the_pricing_its_homes_config_sets(self) -> None:
        """The home sets an SEG and no tariff, and its run earns no export revenue, so only the config says its export is priced."""
        results = make_sim_results(days=1)

        tabs = home_results_tabs(_priced_home(tariff=False, seg=True), results, calculate_summary(results))

        (financial,) = [panel for tab in tabs for panel in tab.panels if panel.dom_id == "chart-financial"]
        assert annotation_texts(financial.content) == ["No import tariff configured — cost tracking unavailable"]

    def test_a_fleet_lists_every_fleet_chart(self) -> None:
        home_summaries = [calculate_summary(make_sim_results(days=1))] * 2

        tabs = fleet_results_tabs(make_fleet_results(n_homes=2, days=1), home_summaries)

        assert _tab_layout(tabs) == [
            ("aggregate", "Aggregate", ["chart-aggregate-timeline", "chart-grid-impact"]),
            ("per_home", "Per-Home", ["chart-heatmap", "chart-box-plots"]),
            ("distributions", "Distributions", ["chart-distribution-histograms"]),
        ]

    def test_a_comparison_lists_the_energy_totals_and_the_efficiency_ratios(self) -> None:
        headline = run_headline(_a_day_of_a_plain_home())

        tabs = comparison_tabs([ComparedRun("Run A", headline), ComparedRun("Run B", headline)])

        assert _tab_layout(tabs) == [
            ("bar", "Energy Totals", ["chart-comparison-bar"]),
            ("radar", "Efficiency Ratios", ["chart-comparison-radar"]),
        ]
