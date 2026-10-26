# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every chart of the dashboard's five energy flows (generation, demand, self-consumption, grid
import and grid export) names each flow alike and draws them in one order, so the legends of a
results page agree. A chart that colours by flow draws each flow in its own palette role's colour.
"""

import dataclasses
from collections.abc import Callable

import pytest

pytest.importorskip("plotly")
from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.web import charts
from solar_challenge.web.charts import COLOUR_PALETTE
from tests._finance_builders import make_fleet_results_of, make_sim_results
from tests._plotly_figure import annotation_texts, opaque, sankey_link_colours, sankey_node_colours, traces

# Each flow's label and palette role, in the order every chart draws the flows.
_FLOW_ROLES = {
    "Generation": "pv_generation",
    "Demand": "demand",
    "Self-Consumption": "self_consumption",
    "Grid Import": "grid_import",
    "Grid Export": "grid_export",
}
_FIVE_FLOWS = tuple(_FLOW_ROLES)


@pytest.fixture
def flow_colours(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Each flow's label, mapped to a colour its role is recoloured with that no other palette role has."""
    colours = {label: f"#0000{index:02x}" for index, label in enumerate(_FLOW_ROLES, start=1)}
    for label, role in _FLOW_ROLES.items():
        monkeypatch.setitem(COLOUR_PALETTE, role, colours[label])
    return colours


def _year() -> SimulationResults:
    return make_sim_results(days=365)


def _fleet() -> FleetResults:
    return make_fleet_results_of([_year(), _year()])


def _summary() -> SummaryStatistics:
    return calculate_summary(make_sim_results(days=1))


def _drawn(panel: charts.ChartPanel) -> str:
    """The figure of *panel*, from a builder whose chart a run too short to chart lacks, asserted to be drawn."""
    assert isinstance(panel.content, str), panel.content
    return panel.content


def _lines(figure: str) -> list[tuple[str, str]]:
    """Each trace of *figure* as its name and its line's colour."""
    return [(trace["name"], trace["line"]["color"]) for trace in traces(figure)]


def _markers(figure: str) -> list[tuple[str, str]]:
    """Each trace of *figure* as its name and its markers' colour."""
    return [(trace["name"], trace["marker"]["color"]) for trace in traces(figure)]


_COLOURED_BY_FLOW: dict[str, tuple[Callable[[], list[tuple[str, str]]], tuple[str, ...]]] = {
    "power_flow_timeline": (lambda: _lines(charts.power_flow_timeline(_year()).content), _FIVE_FLOWS),
    "fleet_aggregate_timeline": (lambda: _lines(charts.fleet_aggregate_timeline(_fleet()).content), _FIVE_FLOWS),
    "daily_energy_balance": (lambda: _markers(charts.daily_energy_balance(make_sim_results(days=2)).content), _FIVE_FLOWS),
    "monthly_summary": (
        lambda: _markers(_drawn(charts.monthly_summary(_year()))),
        ("Self-Consumption", "Grid Import", "Grid Export"),
    ),
    "fleet_box_plots": (lambda: _markers(charts.fleet_box_plots([_summary()] * 2).content), _FIVE_FLOWS),
    "fleet_grid_impact": (lambda: _lines(charts.fleet_grid_impact(_fleet()).content), ("Grid Import", "Grid Export")),
    "fleet_distribution_histograms": (
        # The first histogram only: the other two draw ratios, which are not flows.
        lambda: _markers(charts.fleet_distribution_histograms([_summary()] * 2).content)[:1],
        ("Generation",),
    ),
}


@pytest.mark.parametrize(("legend", "flows"), _COLOURED_BY_FLOW.values(), ids=_COLOURED_BY_FLOW.keys())
def test_a_chart_coloured_by_flow_draws_each_flow_under_its_label_in_its_roles_colour(
    legend: Callable[[], list[tuple[str, str]]], flows: tuple[str, ...], flow_colours: dict[str, str]
) -> None:
    assert legend() == [(label, flow_colours[label]) for label in flows]


_NAMED: dict[str, tuple[Callable[[], list[str]], list[str]]] = {
    "fleet_heatmap": (lambda: traces(charts.fleet_heatmap([_summary()] * 2).content)[0]["x"], list(_FIVE_FLOWS)),
    "comparison_bar_chart": (
        lambda: traces(charts.comparison_bar_chart([dataclasses.asdict(_summary())], ["Run A"]).content)[0]["x"],
        list(_FIVE_FLOWS),
    ),
    "seasonal_comparison": (
        lambda: [category for trace in traces(_drawn(charts.seasonal_comparison(_year()))) for category in trace["x"]],
        # The winter bars' categories, then the summer bars'.
        ["Generation (kWh)", "Demand (kWh)", "Self-Consumption (kWh)"] * 2,
    ),
    "fleet_distribution_histograms_subplot_title": (
        # make_subplots writes the subplot titles as layout annotations, in subplot order.
        lambda: annotation_texts(charts.fleet_distribution_histograms([_summary()] * 2).content)[:1],
        ["Generation (kWh)"],
    ),
}


@pytest.mark.parametrize(("names", "expected"), _NAMED.values(), ids=_NAMED.keys())
def test_a_chart_coloured_otherwise_names_each_flow_by_its_label(
    names: Callable[[], list[str]], expected: list[str]
) -> None:
    assert names() == expected


def _sankey() -> str:
    """The Sankey figure of a day on which PV and the grid both charge the battery, so that every link is drawn."""
    summary = dataclasses.replace(
        calculate_summary(make_sim_results(discharge_kwh=2.0, days=1)),
        total_battery_charge_kwh=5.0,
        total_grid_charge_kwh=2.0,
    )
    return charts.sankey_diagram(summary).content


def test_the_sankey_draws_each_node_in_the_colour_of_the_flow_it_sends_or_receives_and_the_battery_in_its_own(
    flow_colours: dict[str, str],
) -> None:
    assert sankey_node_colours(_sankey()) == {
        "PV Generation": flow_colours["Generation"],
        "Grid": flow_colours["Grid Import"],
        "Battery": COLOUR_PALETTE["battery_charge"],
        "Demand": flow_colours["Demand"],
        "Export": flow_colours["Grid Export"],
    }


def test_the_sankey_draws_each_link_in_the_colour_of_the_flow_it_is_part_of_and_the_batterys_in_its_own(
    flow_colours: dict[str, str],
) -> None:
    assert {link: opaque(colour) for link, colour in sankey_link_colours(_sankey()).items()} == {
        ("PV Generation", "Demand"): flow_colours["Self-Consumption"],
        ("PV Generation", "Battery"): COLOUR_PALETTE["battery_charge"],
        ("PV Generation", "Export"): flow_colours["Grid Export"],
        ("Grid", "Demand"): flow_colours["Grid Import"],
        ("Grid", "Battery"): COLOUR_PALETTE["battery_charge"],
        ("Battery", "Demand"): COLOUR_PALETTE["battery_charge"],
    }
