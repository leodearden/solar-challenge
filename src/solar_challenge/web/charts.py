# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized chart module for the Solar Challenge web dashboard.

All functions return Plotly JSON strings via fig.to_json().
Charts share layout defaults. Every series colour is a COLOUR_PALETTE entry, or a translucent
form of one made by _with_alpha, so a palette edit reaches it; a chart that writes a palette
colour out by hand fails tests/unit/test_web_chart_colours.py. Every COLOUR_PALETTE role is one
some chart draws, and a role none draws fails the same test module. Neutral chrome (backgrounds,
annotation text, outlines) and the heatmap's named colour scale mark no series and have no
palette role. Each of the five energy flows has its label, colour role and place in the charts'
order once, in _EnergyFlow; tests/unit/test_web_chart_energy_flows.py checks that the charts agree.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, NamedTuple, TypeVar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults, SummaryStatistics
from solar_challenge.output import aggregate_daily, aggregate_monthly, calculate_seasonal_metrics

_AMBER = "#f5a623"
_RED = "#d0021b"
_GREEN = "#7ed321"
_BLUE = "#4a90e2"
_PURPLE = "#9013fe"

COLOUR_PALETTE = {
    "pv_generation": _AMBER,
    "demand": _RED,
    "self_consumption": _GREEN,
    "grid_import": "#9b9b9b",
    "grid_export": _BLUE,
    "battery_charge": "#50e3c2",
    "heat_pump": _PURPLE,
    "cost": _RED,
    "revenue": _GREEN,
    "soc_low_threshold": _RED,
    "soc_high_threshold": _GREEN,
    "net_savings": _BLUE,
    "winter": _BLUE,
    "summer": _AMBER,
    "comparison_run_1": _AMBER,
    "comparison_run_2": _BLUE,
    "comparison_run_3": _GREEN,
    "comparison_run_4": _PURPLE,
}

_SHARED_LAYOUT = dict(
    font=dict(family="system-ui, sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=50, r=20, t=40, b=60),
    legend=dict(orientation="h", y=-0.15),
)

_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def _with_alpha(colour: str, alpha: float) -> str:
    """*colour* as an rgba() string at opacity *alpha*.

    Raises:
        ValueError: If *colour* is not written #rrggbb; the message names it.
    """
    if not _HEX_COLOUR.fullmatch(colour):
        raise ValueError(f"a translucent chart colour derives from a #rrggbb colour, not {colour!r}")
    red, green, blue = bytes.fromhex(colour[1:])
    return f"rgba({red},{green},{blue},{alpha})"


class _ChartElement(Enum):
    """Things a chart draws, each member with its label and the COLOUR_PALETTE role it is drawn in."""

    def __init__(self, label: str, colour_role: str) -> None:
        self.label: Final = label
        self.colour_role: Final = colour_role

    @property
    def colour(self) -> str:
        """The member's COLOUR_PALETTE colour, read when called, so a palette edit reaches every chart that draws it."""
        return COLOUR_PALETTE[self.colour_role]


class _EnergyFlow(_ChartElement):
    """The five energy flows the charts draw, in the order every chart draws them: each one's label and COLOUR_PALETTE role."""

    GENERATION = ("Generation", "pv_generation")
    DEMAND = ("Demand", "demand")
    SELF_CONSUMPTION = ("Self-Consumption", "self_consumption")
    GRID_IMPORT = ("Grid Import", "grid_import")
    GRID_EXPORT = ("Grid Export", "grid_export")


_FlowValue = TypeVar("_FlowValue")


def _in_flow_order(drawn: Mapping[_EnergyFlow, _FlowValue]) -> list[tuple[_EnergyFlow, _FlowValue]]:
    """*drawn*'s flows, each paired with its value, in the order every chart draws the five flows."""
    return [(flow, drawn[flow]) for flow in _EnergyFlow if flow in drawn]


_TimeIndexed = TypeVar("_TimeIndexed", pd.Series, pd.DataFrame)


def _adaptive_downsample(data: _TimeIndexed, max_points: int = 2000) -> _TimeIndexed:
    """*data*, a time-indexed Series or DataFrame, as the mean of each of about *max_points* evenly spaced windows.

    Data of at most *max_points* rows is returned unchanged.
    """
    if len(data) <= max_points:
        return data

    total_seconds = (data.index[-1] - data.index[0]).total_seconds()
    freq_seconds = max(1, int(total_seconds / max_points))
    if freq_seconds < 60:
        freq = f"{freq_seconds}s"
    elif freq_seconds < 3600:
        freq = f"{freq_seconds // 60}min"
    else:
        freq = f"{freq_seconds // 3600}h"
    return data.resample(freq).mean()


def _stacked_power_flow_timeline(
    title: str,
    *,
    generation: pd.Series,
    demand: pd.Series,
    self_consumption: pd.Series,
    grid_import: pd.Series,
    grid_export: pd.Series,
) -> str:
    """Plotly JSON of a stacked area chart, titled *title*, of the five power flows over time, with a range slider."""
    flows = _in_flow_order({
        _EnergyFlow.GENERATION: generation,
        _EnergyFlow.DEMAND: demand,
        _EnergyFlow.SELF_CONSUMPTION: self_consumption,
        _EnergyFlow.GRID_IMPORT: grid_import,
        _EnergyFlow.GRID_EXPORT: grid_export,
    })
    df = _adaptive_downsample(pd.DataFrame({flow: series for flow, series in flows}))
    dates = [d.isoformat() for d in df.index]
    traces: list[Any] = [
        go.Scatter(
            name=flow.label,
            x=dates,
            y=df[flow].round(4).tolist(),
            mode="lines",
            stackgroup="one",
            line=dict(width=0.5, color=flow.colour),
        )
        for flow, _ in flows
    ]

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title=title,
        xaxis=dict(
            title="Time",
            rangeslider=dict(visible=True),
        ),
        yaxis=dict(title="Power (kW)"),
        height=500,
    )
    return str(fig.to_json())


def power_flow_timeline(results: SimulationResults) -> str:
    """Plotly JSON of the home's power flows in *results*, stacked over time with a range slider."""
    return _stacked_power_flow_timeline(
        "Power Flow Timeline",
        generation=results.generation,
        demand=results.demand,
        self_consumption=results.self_consumption,
        grid_import=results.grid_import,
        grid_export=results.grid_export,
    )


def battery_soc_chart(results: SimulationResults, battery_capacity_kwh: float) -> str:
    """Line chart with fill-to-zero for battery state of charge.

    Adds horizontal threshold lines at 10% and 90% of capacity.

    Args:
        results: SimulationResults instance.
        battery_capacity_kwh: Nominal battery capacity in kWh.

    Returns:
        Plotly figure JSON string.
    """
    soc = _adaptive_downsample(results.battery_soc)
    dates = [d.isoformat() for d in soc.index]
    values = soc.round(4).tolist()

    trace = go.Scatter(
        name="Battery SOC",
        x=dates,
        y=values,
        mode="lines",
        fill="tozeroy",
        line=dict(color=COLOUR_PALETTE["battery_charge"], width=1.5),
        fillcolor=_with_alpha(COLOUR_PALETTE["battery_charge"], 0.15),
    )

    fig = go.Figure(data=[trace])

    # Add threshold lines at 10% and 90%
    low_threshold = battery_capacity_kwh * 0.10
    high_threshold = battery_capacity_kwh * 0.90

    fig.add_hline(
        y=low_threshold,
        line_dash="dash",
        line_color=COLOUR_PALETTE["soc_low_threshold"],
        annotation_text="10%",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=high_threshold,
        line_dash="dash",
        line_color=COLOUR_PALETTE["soc_high_threshold"],
        annotation_text="90%",
        annotation_position="top right",
    )

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Battery State of Charge",
        xaxis=dict(title="Time"),
        yaxis=dict(title="State of Charge (kWh)"),
        height=400,
    )
    return str(fig.to_json())


class _SankeyNode(_ChartElement):
    """The energy-flow Sankey's nodes, in the order its figure lists them: each one's label and COLOUR_PALETTE role.

    Each node but the battery sends or receives one of the five energy flows in total, and is drawn in that flow's role.
    """

    PV_GENERATION = ("PV Generation", _EnergyFlow.GENERATION.colour_role)
    GRID = ("Grid", _EnergyFlow.GRID_IMPORT.colour_role)
    BATTERY = ("Battery", "battery_charge")
    DEMAND = (_EnergyFlow.DEMAND.label, _EnergyFlow.DEMAND.colour_role)
    EXPORT = ("Export", _EnergyFlow.GRID_EXPORT.colour_role)


class _SankeyLink(NamedTuple):
    """The kWh flowing from source to target, drawn in a translucent form of coloured_as's colour."""

    source: _SankeyNode
    target: _SankeyNode
    kwh: float
    coloured_as: _ChartElement


def sankey_diagram(summary: SummaryStatistics) -> str:
    """Sankey diagram of the run's energy flows from PV, the grid and the battery to their uses.

    PV feeds demand, the battery and export; the grid feeds demand and, on
    grid-charging days, the battery; the battery feeds demand. A flow of
    0.01 kWh or less is not drawn.

    Args:
        summary: The run's summary statistics, whose energy totals the links draw.

    Returns:
        Plotly figure JSON string, or ``"{}"`` if there is no energy flow
        to draw.
    """
    grid_charge = summary.total_grid_charge_kwh
    # Self-consumption counts the battery's discharge to demand as well as the PV used directly
    pv_to_demand = summary.total_self_consumption_kwh - summary.total_battery_discharge_kwh
    pv_to_battery = summary.total_battery_charge_kwh - grid_charge
    grid_to_demand = summary.total_grid_import_kwh - grid_charge
    flows = [
        _SankeyLink(_SankeyNode.PV_GENERATION, _SankeyNode.DEMAND, pv_to_demand, _EnergyFlow.SELF_CONSUMPTION),
        _SankeyLink(_SankeyNode.PV_GENERATION, _SankeyNode.BATTERY, pv_to_battery, _SankeyNode.BATTERY),
        _SankeyLink(_SankeyNode.PV_GENERATION, _SankeyNode.EXPORT, summary.total_grid_export_kwh, _EnergyFlow.GRID_EXPORT),
        _SankeyLink(_SankeyNode.GRID, _SankeyNode.DEMAND, grid_to_demand, _EnergyFlow.GRID_IMPORT),
        _SankeyLink(_SankeyNode.GRID, _SankeyNode.BATTERY, grid_charge, _SankeyNode.BATTERY),
        _SankeyLink(_SankeyNode.BATTERY, _SankeyNode.DEMAND, summary.total_battery_discharge_kwh, _SankeyNode.BATTERY),
    ]
    drawn = [flow for flow in flows if flow.kwh > 0.01]
    if not drawn:
        return "{}"

    nodes = list(_SankeyNode)
    link_opacity = 0.4
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=20,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=[node.label for node in nodes],
            color=[node.colour for node in nodes],
        ),
        link=dict(
            source=[nodes.index(link.source) for link in drawn],
            target=[nodes.index(link.target) for link in drawn],
            value=[round(link.kwh, 2) for link in drawn],
            color=[_with_alpha(link.coloured_as.colour, link_opacity) for link in drawn],
        ),
    )])

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Energy Flow",
        height=450,
    )
    return str(fig.to_json())


_AGGREGATE_KWH_COLUMNS: Mapping[_EnergyFlow, str] = MappingProxyType({
    _EnergyFlow.GENERATION: "generation_kwh",
    _EnergyFlow.DEMAND: "demand_kwh",
    _EnergyFlow.SELF_CONSUMPTION: "self_consumption_kwh",
    _EnergyFlow.GRID_IMPORT: "grid_import_kwh",
    _EnergyFlow.GRID_EXPORT: "grid_export_kwh",
})


def daily_energy_balance(results: SimulationResults) -> str:
    """Grouped bar chart of daily generation, demand and related metrics.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string.
    """
    daily = aggregate_daily(results)
    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    traces: list[Any] = [
        go.Bar(name=flow.label, x=dates, y=daily[column].round(3).tolist(), marker_color=flow.colour)
        for flow, column in _in_flow_order(_AGGREGATE_KWH_COLUMNS)
    ]

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Daily Energy Balance",
        barmode="group",
        xaxis=dict(title="Date", type="category"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return str(fig.to_json())


def monthly_summary(results: SimulationResults) -> str | None:
    """Stacked bar chart of monthly energy breakdown.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, or ``None`` if the simulation spans
        fewer than 90 days.
    """
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1
    if sim_days < 90:
        return None

    monthly = aggregate_monthly(results)
    months = [d.strftime("%Y-%m") for d in monthly.index]

    stacked = frozenset({_EnergyFlow.SELF_CONSUMPTION, _EnergyFlow.GRID_IMPORT, _EnergyFlow.GRID_EXPORT})
    traces: list[Any] = [
        go.Bar(name=flow.label, x=months, y=monthly[column].round(2).tolist(), marker_color=flow.colour)
        for flow, column in _in_flow_order(_AGGREGATE_KWH_COLUMNS)
        if flow in stacked
    ]

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Monthly Energy Summary",
        barmode="stack",
        xaxis=dict(title="Month", type="category"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return str(fig.to_json())


def financial_breakdown(results: SimulationResults) -> str:
    """Dual-axis chart with daily cost bars and a cumulative savings line.

    Daily cost and revenue are :func:`~solar_challenge.output.aggregate_daily`'s
    ``import_cost_gbp`` and ``export_revenue_gbp``: the day totals of the
    engine-priced series ``results.import_cost`` and ``results.export_revenue``,
    which already reflect the tariff and SEG rate set at simulation time.

    When the simulation was run without a tariff configured, both series are
    all-zero (home.py populates zeros when ``tariff_config`` is ``None``).
    In that case an annotation is added to the chart explaining that cost and
    revenue tracking is unavailable, rather than displaying a misleadingly
    flat-zero plot.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string.
    """
    daily = aggregate_daily(results)
    daily_cost = daily["import_cost_gbp"].round(2)
    daily_revenue = daily["export_revenue_gbp"].round(2)
    daily_net = (daily_cost - daily_revenue).round(2)
    cumulative_savings = (-daily_net).cumsum().round(2)
    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            name="Daily Cost",
            x=dates,
            y=daily_cost.tolist(),
            marker_color=COLOUR_PALETTE["cost"],
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            name="Daily Revenue",
            x=dates,
            y=daily_revenue.tolist(),
            marker_color=COLOUR_PALETTE["revenue"],
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            name="Cumulative Net Savings",
            x=dates,
            y=cumulative_savings.tolist(),
            mode="lines",
            line=dict(color=COLOUR_PALETTE["net_savings"], width=2),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Financial Breakdown",
        barmode="group",
        xaxis=dict(title="Date", type="category"),
        height=420,
    )
    fig.update_yaxes(title_text="Daily (GBP)", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative Net Savings (GBP)", secondary_y=True)

    # If the simulation was run without a tariff, both cost and revenue series
    # are all-zero.  Annotate the chart so the user understands the chart is
    # empty due to missing tariff configuration, not because costs are zero.
    if daily_cost.sum() == 0 and daily_revenue.sum() == 0:
        fig.add_annotation(
            text="No tariff configured — cost and revenue tracking unavailable",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="#888888"),
        )

    return str(fig.to_json())


def _season_bar(name: str, colour_role: str, kwh: Mapping[_EnergyFlow, float]) -> Any:
    """A bar trace, named *name* in *colour_role*'s colour, of one season's kWh of each flow in *kwh*."""
    flows = _in_flow_order(kwh)
    return go.Bar(
        name=name,
        x=[f"{flow.label} (kWh)" for flow, _ in flows],
        y=[round(total, 1) for _, total in flows],
        marker_color=COLOUR_PALETTE[colour_role],
    )


def seasonal_comparison(results: SimulationResults) -> str | None:
    """Winter vs Summer grouped bar chart.

    Winter is defined as Dec-Feb and Summer as Jun-Aug.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, or ``None`` if the simulation spans
        fewer than 180 days.
    """
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1
    if sim_days < 180:
        return None

    metrics = calculate_seasonal_metrics(results.demand, results.generation)

    fig = go.Figure(data=[
        _season_bar("Winter (Dec-Feb)", "winter", {
            _EnergyFlow.GENERATION: metrics["winter_generation_kwh"],
            _EnergyFlow.DEMAND: metrics["winter_demand_kwh"],
            _EnergyFlow.SELF_CONSUMPTION: metrics["winter_self_consumption_kwh"],
        }),
        _season_bar("Summer (Jun-Aug)", "summer", {
            _EnergyFlow.GENERATION: metrics["summer_generation_kwh"],
            _EnergyFlow.DEMAND: metrics["summer_demand_kwh"],
            _EnergyFlow.SELF_CONSUMPTION: metrics["summer_self_consumption_kwh"],
        }),
    ])

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Seasonal Comparison",
        barmode="group",
        xaxis=dict(title="Metric"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return str(fig.to_json())


def heat_pump_analysis(results: SimulationResults) -> dict[str, str] | None:
    """Charts for heat pump load analysis.

    Args:
        results: SimulationResults instance.

    Returns:
        Dictionary with ``'load_profile_chart'`` and ``'load_share_chart'`` keys
        containing Plotly JSON strings, or ``None`` if no heat pump data
        is present.
    """
    if results.heat_pump_load is None:
        return None

    # --- Load share pie chart ---
    totals = results.total_amounts()
    hp_total = totals["heat_pump_load_kwh"]
    total_demand = totals["demand_kwh"]
    other_demand = max(0, total_demand - hp_total)

    pie_fig = go.Figure(data=[go.Pie(
        labels=["Heat Pump", "Other Demand"],
        values=[round(hp_total, 1), round(other_demand, 1)],
        marker=dict(colors=[COLOUR_PALETTE["heat_pump"], COLOUR_PALETTE["demand"]]),
        hole=0.4,
    )])
    pie_fig.update_layout(
        **_SHARED_LAYOUT,
        title="Heat Pump Share of Demand",
        height=400,
    )

    # --- Heat pump load profile over time ---
    hp_series = _adaptive_downsample(results.heat_pump_load)
    dates = [d.isoformat() for d in hp_series.index]

    load_fig = go.Figure(data=[go.Scatter(
        name="Heat Pump Load",
        x=dates,
        y=hp_series.round(4).tolist(),
        mode="lines",
        fill="tozeroy",
        line=dict(color=COLOUR_PALETTE["heat_pump"], width=1),
        fillcolor=_with_alpha(COLOUR_PALETTE["heat_pump"], 0.15),
    )])
    load_fig.update_layout(
        **_SHARED_LAYOUT,
        title="Heat Pump Load Profile",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Power (kW)"),
        height=400,
    )

    return {
        "load_share_chart": str(pie_fig.to_json()),
        "load_profile_chart": str(load_fig.to_json()),
    }


# ---------------------------------------------------------------------------
# Comparison charts (for run comparison page)
# ---------------------------------------------------------------------------

_COMPARISON_RUN_ROLES = ("comparison_run_1", "comparison_run_2", "comparison_run_3", "comparison_run_4")


def _comparison_run_colour(run_index: int) -> str:
    """The palette colour of the compared run at *run_index*; a fifth run starts the cycle again."""
    return COLOUR_PALETTE[_COMPARISON_RUN_ROLES[run_index % len(_COMPARISON_RUN_ROLES)]]


def overlaid_power_flows(results_list: list[SimulationResults], labels: list[str]) -> str:
    """Overlaid line chart of power flows from multiple runs.

    Each run gets a different colour from the comparison palette.
    Shows generation and demand lines for each run, downsampled
    for performance.

    Args:
        results_list: List of SimulationResults from different runs.
        labels: Display labels for each run.

    Returns:
        Plotly figure JSON string.
    """
    traces: list[Any] = []
    for i, (results, label) in enumerate(zip(results_list, labels)):
        colour = _comparison_run_colour(i)

        gen = _adaptive_downsample(results.generation)
        dem = _adaptive_downsample(results.demand)

        gen_dates = [d.isoformat() for d in gen.index]
        dem_dates = [d.isoformat() for d in dem.index]

        traces.append(go.Scatter(
            name=f"{label} - {_EnergyFlow.GENERATION.label}",
            x=gen_dates,
            y=gen.round(4).tolist(),
            mode="lines",
            line=dict(color=colour, width=1.5),
            legendgroup=label,
        ))
        traces.append(go.Scatter(
            name=f"{label} - {_EnergyFlow.DEMAND.label}",
            x=dem_dates,
            y=dem.round(4).tolist(),
            mode="lines",
            line=dict(color=colour, width=1.5, dash="dash"),
            legendgroup=label,
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Overlaid Power Flows",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Power (kW)"),
        height=500,
    )
    return str(fig.to_json())


def comparison_bar_chart(summaries: list[dict[str, Any]], labels: list[str]) -> str:
    """Grouped bar chart comparing energy totals across runs.

    One category per energy flow; one group per run, labelled.

    Args:
        summaries: List of summary dictionaries from different runs.
        labels: Display labels for each run.

    Returns:
        Plotly figure JSON string.
    """
    summary_keys = _in_flow_order({
        _EnergyFlow.GENERATION: "total_generation_kwh",
        _EnergyFlow.DEMAND: "total_demand_kwh",
        _EnergyFlow.SELF_CONSUMPTION: "total_self_consumption_kwh",
        _EnergyFlow.GRID_IMPORT: "total_grid_import_kwh",
        _EnergyFlow.GRID_EXPORT: "total_grid_export_kwh",
    })
    categories = [flow.label for flow, _ in summary_keys]

    traces: list[Any] = []
    for i, (summary, label) in enumerate(zip(summaries, labels)):
        colour = _comparison_run_colour(i)
        values = [round(summary.get(key, 0), 2) for _, key in summary_keys]
        traces.append(go.Bar(
            name=label,
            x=categories,
            y=values,
            marker_color=colour,
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Energy Totals Comparison",
        barmode="group",
        xaxis=dict(title="Metric"),
        yaxis=dict(title="Energy (kWh)"),
        height=450,
    )
    return str(fig.to_json())


def comparison_radar(summaries: list[dict[str, Any]], labels: list[str]) -> str:
    """Radar chart comparing efficiency ratios across runs.

    Axes: Self-Consumption %, Grid Dependency %, Export %,
    Battery Utilization %.

    Args:
        summaries: List of summary dictionaries from different runs.
        labels: Display labels for each run.

    Returns:
        Plotly figure JSON string.
    """
    theta = [
        "Self-Consumption %",
        "Grid Dependency %",
        "Export %",
        "Battery Utilization %",
    ]

    traces: list[Any] = []
    for i, (summary, label) in enumerate(zip(summaries, labels)):
        colour = _comparison_run_colour(i)

        sc_ratio = summary.get("self_consumption_ratio", 0) * 100
        grid_dep = summary.get("grid_dependency_ratio", 0) * 100
        export_ratio = summary.get("export_ratio", 0) * 100

        # Battery utilization: charge / generation (if available)
        total_charge = summary.get("total_battery_charge_kwh", 0)
        total_gen = summary.get("total_generation_kwh", 0)
        battery_util = (total_charge / total_gen * 100) if total_gen > 0 else 0

        r_values = [
            round(sc_ratio, 1),
            round(grid_dep, 1),
            round(export_ratio, 1),
            round(battery_util, 1),
        ]

        traces.append(go.Scatterpolar(
            name=label,
            r=r_values + [r_values[0]],  # close the polygon
            theta=theta + [theta[0]],
            fill="toself",
            fillcolor=_with_alpha(colour, 0.1),
            line=dict(color=colour, width=2),
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Efficiency Ratios",
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100]),
        ),
        height=450,
    )
    return str(fig.to_json())


# ---------------------------------------------------------------------------
# Fleet charts (for fleet results page)
# ---------------------------------------------------------------------------


def fleet_aggregate_timeline(fleet: FleetResults) -> str:
    """Plotly JSON of *fleet*'s power flows, each summed across its homes, stacked over time with a range slider."""
    return _stacked_power_flow_timeline(
        "Fleet Aggregate Power Flow",
        generation=fleet.total_generation,
        demand=fleet.total_demand,
        self_consumption=fleet.total_self_consumption,
        grid_import=fleet.total_grid_import,
        grid_export=fleet.total_grid_export,
    )


def fleet_grid_impact(fleet: FleetResults) -> str:
    """Area chart of the fleet's net grid impact: its total grid import less its total grid export.

    At each timestep the net fills above zero (import region) or below
    zero (export region).

    Args:
        fleet: The fleet whose totals are drawn.

    Returns:
        Plotly figure JSON string.
    """
    net = fleet.total_grid_import - fleet.total_grid_export
    net = _adaptive_downsample(net)
    dates = [d.isoformat() for d in net.index]
    values = net.round(4).tolist()

    regions = _in_flow_order({
        _EnergyFlow.GRID_IMPORT: [max(0, v) for v in values],
        _EnergyFlow.GRID_EXPORT: [min(0, v) for v in values],
    })
    traces: list[Any] = [
        go.Scatter(
            name=flow.label,
            x=dates,
            y=region,
            mode="lines",
            fill="tozeroy",
            line=dict(width=0.5, color=flow.colour),
            fillcolor=_with_alpha(flow.colour, 0.3),
        )
        for flow, region in regions
    ]

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Net Grid Impact",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Power (kW) — Import (+) / Export (-)"),
        height=450,
    )
    return str(fig.to_json())


_SUMMARY_KWH: Mapping[_EnergyFlow, Callable[[SummaryStatistics], float]] = MappingProxyType({
    _EnergyFlow.GENERATION: lambda summary: summary.total_generation_kwh,
    _EnergyFlow.DEMAND: lambda summary: summary.total_demand_kwh,
    _EnergyFlow.SELF_CONSUMPTION: lambda summary: summary.total_self_consumption_kwh,
    _EnergyFlow.GRID_IMPORT: lambda summary: summary.total_grid_import_kwh,
    _EnergyFlow.GRID_EXPORT: lambda summary: summary.total_grid_export_kwh,
})


def fleet_heatmap(home_summaries: Sequence[SummaryStatistics]) -> str:
    """Homes x metrics heatmap matrix.

    Rows represent individual homes and columns the five energy flows'
    totals in kWh. Limits to the first 50 homes if there are more.

    Args:
        home_summaries: Each home's summary statistics, in the fleet's order.

    Returns:
        Plotly figure JSON string.
    """
    summaries = home_summaries[:50]

    y_labels = [f"Home {i+1}" for i in range(len(summaries))]
    columns = _in_flow_order(_SUMMARY_KWH)
    x_labels = [flow.label for flow, _ in columns]
    z = [[round(kwh(summary), 2) for _, kwh in columns] for summary in summaries]

    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=x_labels,
        y=y_labels,
        colorscale="YlOrRd",
        hoverongaps=False,
    ))

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Per-Home Energy Metrics",
        xaxis=dict(title="Metric"),
        yaxis=dict(title="Home", autorange="reversed"),
        height=max(350, len(summaries) * 25 + 100),
    )
    return str(fig.to_json())


def fleet_box_plots(home_summaries: Sequence[SummaryStatistics]) -> str:
    """Box plots of energy metrics across all homes.

    One box per metric showing the distribution of values across
    the fleet.

    Args:
        home_summaries: Each home's summary statistics, in the fleet's order.

    Returns:
        Plotly figure JSON string.
    """
    traces: list[Any] = [
        go.Box(
            name=flow.label,
            y=[kwh(summary) for summary in home_summaries],
            marker_color=flow.colour,
            boxmean=True,
        )
        for flow, kwh in _in_flow_order(_SUMMARY_KWH)
    ]

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Energy Metrics Distribution Across Homes",
        yaxis=dict(title="Energy (kWh)"),
        height=450,
    )
    return str(fig.to_json())


def fleet_distribution_histograms(home_summaries: Sequence[SummaryStatistics]) -> str:
    """Histograms showing distribution of key metrics across homes.

    Three subplots: generation (kWh), self-consumption ratio, and
    grid dependency ratio.

    Args:
        home_summaries: Each home's summary statistics, in the fleet's order.

    Returns:
        Plotly figure JSON string.
    """
    generation = _EnergyFlow.GENERATION
    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=[f"{generation.label} (kWh)", "Self-Consumption Ratio", "Grid Dependency Ratio"],
    )

    gen_values = [_SUMMARY_KWH[generation](summary) for summary in home_summaries]
    sc_values = [summary.self_consumption_ratio for summary in home_summaries]
    gd_values = [summary.grid_dependency_ratio for summary in home_summaries]

    fig.add_trace(
        go.Histogram(
            x=gen_values,
            name=generation.label,
            marker_color=generation.colour,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Histogram(
            x=sc_values,
            name="Self-Consumption",
            marker_color=COLOUR_PALETTE["self_consumption"],
        ),
        row=1, col=2,
    )
    fig.add_trace(
        go.Histogram(
            x=gd_values,
            name="Grid Dependency",
            marker_color=COLOUR_PALETTE["grid_import"],
        ),
        row=1, col=3,
    )

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Fleet Distribution Histograms",
        showlegend=False,
        height=400,
    )
    return str(fig.to_json())


# ---------------------------------------------------------------------------
# Parameter sweep chart
# ---------------------------------------------------------------------------


def sweep_parameter_chart(
    param_values: list[float],
    metric_values: list[float],
    param_name: str,
    metric_name: str,
) -> str:
    """Line chart showing parameter vs metric for sweep results.

    Plots the swept parameter values on the X-axis and the resulting
    metric values on the Y-axis.  Highlights the optimal point (maximum
    metric value) with an annotation and adds a linear trend line.

    Args:
        param_values: List of parameter values tested.
        metric_values: Corresponding metric values for each parameter point.
        param_name: Display name for the X-axis (e.g. "PV Capacity (kW)").
        metric_name: Display name for the Y-axis (e.g. "Self-Consumption (%)").

    Returns:
        Plotly figure JSON string, or ``"{}"`` if either input list is empty.
    """
    if not param_values or not metric_values:
        return "{}"

    # Main data trace
    traces: list[Any] = [
        go.Scatter(
            name=metric_name,
            x=param_values,
            y=metric_values,
            mode="lines+markers",
            line=dict(color=COLOUR_PALETTE["pv_generation"], width=2.5),
            marker=dict(size=8),
        ),
    ]

    # Highlight optimal point (max metric value)
    if metric_values:
        best_idx = max(range(len(metric_values)), key=lambda i: metric_values[i])
        traces.append(
            go.Scatter(
                name="Optimal",
                x=[param_values[best_idx]],
                y=[metric_values[best_idx]],
                mode="markers+text",
                marker=dict(size=14, color=COLOUR_PALETTE["self_consumption"], symbol="star"),
                text=[f"{metric_values[best_idx]:.1f}"],
                textposition="top center",
                showlegend=True,
            ),
        )

    # Simple linear trend line
    if len(param_values) >= 2:
        x_arr = np.array(param_values, dtype=float)
        y_arr = np.array(metric_values, dtype=float)
        coeffs = np.polyfit(x_arr, y_arr, 1)
        trend_y = np.polyval(coeffs, x_arr)
        traces.append(
            go.Scatter(
                name="Trend",
                x=param_values,
                y=trend_y.round(2).tolist(),
                mode="lines",
                line=dict(color=COLOUR_PALETTE["grid_import"], width=1.5, dash="dash"),
            ),
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title=f"{metric_name} vs {param_name}",
        xaxis=dict(title=param_name),
        yaxis=dict(title=metric_name),
        height=450,
    )
    return str(fig.to_json())
