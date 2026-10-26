# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized chart module for the Solar Challenge web dashboard.

Each chart builder returns Plotly figure JSON, made by fig.to_json(); heat_pump_analysis returns
its two figures as one HeatPumpCharts. ChartPanel, ChartAbsence and ChartTab describe a page's
charts, and each refuses at construction, naming the field and the value, what no page can draw.
Charts share layout defaults. COLOUR_PALETTE maps each chart role to its colour, loaded when
this module is imported from the chart section of the theme token file, static/src/theme-tokens.json.
Every colour a chart draws is a COLOUR_PALETTE entry, or a translucent form of one made by
_with_alpha, so a token edit reaches it; a chart that writes a chart colour out by hand fails
tests/unit/test_web_chart_colours.py. Every COLOUR_PALETTE role is one some chart draws, and a
role none draws fails the same test module. The unpriced-import note's text and the Sankey's node
outline are roles too; only the transparent backgrounds and the heatmap's named colour scale are
not palette colours. Each of the five energy flows has its label, colour role and place in the
charts' order once, in _EnergyFlow; tests/unit/test_web_chart_energy_flows.py checks that the
charts agree.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NamedTuple, NoReturn, TypeVar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults, SummaryStatistics
from solar_challenge.output import SeasonSummary, aggregate_daily, aggregate_monthly, calculate_seasonal_metrics
from solar_challenge.web.theme_tokens import chart_colour_palette, is_rrggbb

_THEME_TOKENS_FILE = Path(__file__).parent / "static" / "src" / "theme-tokens.json"

COLOUR_PALETTE: Mapping[str, str] = chart_colour_palette(_THEME_TOKENS_FILE)

_SHARED_LAYOUT = dict(
    font=dict(family="system-ui, sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=50, r=20, t=40, b=60),
    legend=dict(orientation="h", y=-0.15),
)

_CHART_DOM_ID = re.compile(r"chart-[a-z0-9-]+")
_CHART_TAB_KEY = re.compile(r"[a-z_]+")


def _refuse(field: str, value: object, rule: str) -> NoReturn:
    """Raise the ValueError that refuses *value* for *field*, naming both and the *rule* the value breaks."""
    raise ValueError(f"{field} must be {rule}; got {value!r}")


@dataclass(frozen=True)
class ChartAbsence:
    """Why a chart that applies to a run has nothing to draw, in one sentence naming the rule and the run's value."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            _refuse("ChartAbsence.reason", self.reason, "a sentence, not blank")


@dataclass(frozen=True)
class ChartPanel:
    """One chart of a page: its element id, the title and height its card and its figure share, and its figure's JSON or the absence that says why it has none."""

    dom_id: str
    title: str
    height_px: int
    content: str | ChartAbsence

    def __post_init__(self) -> None:
        if not _CHART_DOM_ID.fullmatch(self.dom_id):
            _refuse("ChartPanel.dom_id", self.dom_id, "'chart-' followed by lower-case letters, digits and hyphens")
        if not self.title.strip():
            _refuse("ChartPanel.title", self.title, "a title, not blank")
        if self.height_px <= 0:
            _refuse("ChartPanel.height_px", self.height_px, "a height above 0 px")
        if isinstance(self.content, str) and self.content.strip() in ("", "{}"):
            _refuse("ChartPanel.content", self.content, "a figure's JSON, neither blank nor an empty object")

    @property
    def figure_json(self) -> str | None:
        """The panel's figure JSON, or None when the panel is an absence."""
        return self.content if isinstance(self.content, str) else None

    @property
    def absence_reason(self) -> str | None:
        """Why the panel has no figure, or None when it has one."""
        return self.content.reason if isinstance(self.content, ChartAbsence) else None


@dataclass(frozen=True)
class ChartTab:
    """One tab of a page's charts: the key that selects it, its label, and its panels in the order they are drawn."""

    key: str
    label: str
    panels: tuple[ChartPanel, ...]

    def __post_init__(self) -> None:
        if not _CHART_TAB_KEY.fullmatch(self.key):
            _refuse("ChartTab.key", self.key, "lower-case letters and underscores")
        if not self.label.strip():
            _refuse("ChartTab.label", self.label, "a label, not blank")
        if not self.panels:
            _refuse("ChartTab.panels", self.panels, "at least one panel")


def _with_alpha(colour: str, alpha: float) -> str:
    """*colour* as an rgba() string at opacity *alpha*.

    Raises:
        ValueError: If *colour* is not written #rrggbb; the message names it.
    """
    if not is_rrggbb(colour):
        raise ValueError(f"a translucent chart colour derives from a #rrggbb colour, not {colour!r}")
    red, green, blue = bytes.fromhex(colour[1:])
    return f"rgba({red},{green},{blue},{alpha})"


def _bar(name: str, *, x: Sequence[str], y: Sequence[float], colour: str) -> Any:
    """A bar trace named *name* of the values *y* at *x*, filled in *colour* with no outline.

    Plotly's default template outlines a bar in its own plot background colour, which no figure draws, so the
    outline would show on the card in either theme.
    """
    return go.Bar(name=name, x=x, y=y, marker=dict(color=colour, line=dict(width=0)))


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


def battery_soc_chart(results: SimulationResults, battery_config: BatteryConfig) -> str:
    """Plotly JSON of the battery state of charge in *results*, filled to zero, with a dashed line at each SOC limit of the battery *battery_config* describes.

    The limits are Battery's min_soc_kwh and max_soc_kwh, its SOC fractions of its
    SoH-derated capacity, which bound the SOC simulate_home tracks.
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

    battery = Battery(battery_config)
    fig.add_hline(
        y=battery.min_soc_kwh,
        line_dash="dash",
        line_color=COLOUR_PALETTE["soc_low_threshold"],
        annotation_text="Min SOC",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=battery.max_soc_kwh,
        line_dash="dash",
        line_color=COLOUR_PALETTE["soc_high_threshold"],
        annotation_text="Max SOC",
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
    The labels name places, not flows, so only Demand's is also a flow's label, and it comes from _EnergyFlow.
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
            line=dict(color=COLOUR_PALETTE["sankey_node_outline"], width=0.5),
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
        _bar(flow.label, x=dates, y=daily[column].round(3).tolist(), colour=flow.colour)
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
        Plotly figure JSON string, or ``None`` if the run's window covers
        fewer than 90 calendar days.
    """
    if results.window.days < 90:
        return None

    monthly = aggregate_monthly(results)
    months = [d.strftime("%Y-%m") for d in monthly.index]

    stacked = frozenset({_EnergyFlow.SELF_CONSUMPTION, _EnergyFlow.GRID_IMPORT, _EnergyFlow.GRID_EXPORT})
    traces: list[Any] = [
        _bar(flow.label, x=months, y=monthly[column].round(2).tolist(), colour=flow.colour)
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


def _unpriced_import_note(results: SimulationResults) -> str | None:
    """The note *results*'s financial chart carries that its import is not priced, else None.

    A run's import is priced when its tariff rate is above zero at some minute:
    simulate_home writes a zero rate throughout a run without a tariff. The note
    names revenue tracking too only when the run earns no export revenue.
    """
    if results.tariff_rate.gt(0).any():
        return None
    if results.export_revenue.gt(0).any():
        return "No import tariff configured — cost tracking unavailable"
    return "No tariff configured — cost and revenue tracking unavailable"


def financial_breakdown(results: SimulationResults) -> str:
    """Dual-axis chart of the run's daily cost and revenue bars and its cumulative net cost line.

    Daily cost and revenue are :func:`~solar_challenge.output.aggregate_daily`'s
    ``import_cost_gbp`` and ``export_revenue_gbp``: the day totals of the
    engine-priced series ``results.import_cost`` and ``results.export_revenue``,
    which already reflect the tariff and SEG rate set at simulation time.

    The line is the run's net cost to date: the running total of each day's
    import cost less its export revenue.

    The chart carries a note exactly when the run's import is not priced: its
    tariff rate is zero throughout, as for a run simulated without a tariff.
    Its £0 cost bars would otherwise read as free import, and its Cumulative
    Net Cost would count revenue only. The note does not depend on the bars
    totalling £0, so a priced run that imports nothing carries none.

    - "No import tariff configured — cost tracking unavailable" when the run
      earns export revenue, which only an SEG rate pays.
    - "No tariff configured — cost and revenue tracking unavailable" when it
      earns none. That includes a run with an SEG rate that exports nothing in
      its window: SimulationResults records the import tariff's rate but no
      export rate, so the chart cannot tell it from a run with neither.

    A tariff with no SEG rate carries no note: its £0 revenue is the
    economically correct value, and simulate_home warns about it.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string.
    """
    daily = aggregate_daily(results)
    daily_cost = daily["import_cost_gbp"].round(2)
    daily_revenue = daily["export_revenue_gbp"].round(2)
    cumulative_net_cost = (daily["import_cost_gbp"] - daily["export_revenue_gbp"]).cumsum().round(2)
    net_cost_label = "Cumulative Net Cost"
    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        _bar("Daily Cost", x=dates, y=daily_cost.tolist(), colour=COLOUR_PALETTE["cost"]),
        secondary_y=False,
    )
    fig.add_trace(
        _bar("Daily Revenue", x=dates, y=daily_revenue.tolist(), colour=COLOUR_PALETTE["revenue"]),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            name=net_cost_label,
            x=dates,
            y=cumulative_net_cost.tolist(),
            mode="lines",
            line=dict(color=COLOUR_PALETTE["net_cost"], width=2),
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
    fig.update_yaxes(title_text=f"{net_cost_label} (GBP)", secondary_y=True)

    note = _unpriced_import_note(results)
    if note is not None:
        fig.add_annotation(
            text=note,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color=COLOUR_PALETTE["unpriced_note"]),
        )

    return str(fig.to_json())


def _season_bar(name: str, colour_role: str, season: SeasonSummary) -> Any:
    """A bar trace, named *name* in *colour_role*'s colour, of *season*'s kWh of generation, demand and self-consumption."""
    flows = _in_flow_order({
        _EnergyFlow.GENERATION: season.generation_kwh,
        _EnergyFlow.DEMAND: season.demand_kwh,
        _EnergyFlow.SELF_CONSUMPTION: season.self_consumption_kwh,
    })
    return _bar(
        name,
        x=[f"{flow.label} (kWh)" for flow, _ in flows],
        y=[round(total, 1) for _, total in flows],
        colour=COLOUR_PALETTE[colour_role],
    )


def seasonal_comparison(results: SimulationResults) -> str | None:
    """Winter vs Summer grouped bar chart.

    Winter is defined as Dec-Feb and Summer as Jun-Aug.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, or ``None`` if the run's window covers
        fewer than 180 calendar days.
    """
    if results.window.days < 180:
        return None

    seasons = calculate_seasonal_metrics(results)

    fig = go.Figure(data=[
        _season_bar("Winter (Dec-Feb)", "winter", seasons.winter),
        _season_bar("Summer (Jun-Aug)", "summer", seasons.summer),
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


@dataclass(frozen=True, kw_only=True)
class HeatPumpCharts:
    """A home run's two heat-pump figures, each Plotly figure JSON: the heat pump's share of the run's demand, and its load over time."""

    load_share_chart: str
    load_profile_chart: str


def heat_pump_analysis(results: SimulationResults) -> HeatPumpCharts | None:
    """The heat-pump charts of *results*, or None if it carries no heat-pump load."""
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

    return HeatPumpCharts(
        load_share_chart=str(pie_fig.to_json()),
        load_profile_chart=str(load_fig.to_json()),
    )


# ---------------------------------------------------------------------------
# Comparison charts (for run comparison page)
# ---------------------------------------------------------------------------

_COMPARISON_RUN_ROLES = ("comparison_run_1", "comparison_run_2", "comparison_run_3", "comparison_run_4")


def _comparison_run_colour(run_index: int) -> str:
    """The palette colour of the compared run at *run_index*; a fifth run starts the cycle again."""
    return COLOUR_PALETTE[_COMPARISON_RUN_ROLES[run_index % len(_COMPARISON_RUN_ROLES)]]


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
        traces.append(_bar(label, x=categories, y=values, colour=colour))

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
