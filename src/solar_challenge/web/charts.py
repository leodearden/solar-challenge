"""Centralized chart module for the Solar Challenge web dashboard.

All functions return Plotly JSON strings via fig.to_json().
Charts use a consistent colour palette and shared layout defaults.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from solar_challenge.home import SimulationResults

COLOUR_PALETTE = {
    "pv_generation": "#f5a623",
    "demand": "#d0021b",
    "self_consumption": "#7ed321",
    "grid_import": "#9b9b9b",
    "grid_export": "#4a90e2",
    "battery_charge": "#50e3c2",
    "battery_discharge": "#f8a427",
    "heat_pump": "#9013fe",
    "cost": "#d0021b",
    "revenue": "#7ed321",
}

_SHARED_LAYOUT = dict(
    font=dict(family="system-ui, sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=50, r=20, t=40, b=60),
    legend=dict(orientation="h", y=-0.15),
)


def _adaptive_downsample(df: pd.DataFrame, max_points: int = 2000) -> pd.DataFrame:
    """Downsample a DataFrame to approximately max_points rows.

    If the DataFrame already has fewer rows than max_points, it is
    returned unchanged. Otherwise the data is resampled using the mean
    to reach roughly max_points rows.

    Args:
        df: Time-indexed DataFrame to downsample.
        max_points: Target maximum number of rows.

    Returns:
        Original or downsampled DataFrame.
    """
    if len(df) <= max_points:
        return df

    # Calculate the resample frequency needed to hit ~max_points rows
    total_seconds = (df.index[-1] - df.index[0]).total_seconds()
    freq_seconds = max(1, int(total_seconds / max_points))

    # Pick a human-friendly frequency string
    if freq_seconds < 60:
        freq = f"{freq_seconds}s"
    elif freq_seconds < 3600:
        freq = f"{max(1, freq_seconds // 60)}min"
    else:
        freq = f"{max(1, freq_seconds // 3600)}h"

    return df.resample(freq).mean()


def _adaptive_downsample_series(series: pd.Series, max_points: int = 2000) -> pd.Series:
    """Downsample a single Series (convenience wrapper).

    Args:
        series: Time-indexed Series.
        max_points: Target maximum rows.

    Returns:
        Original or downsampled Series.
    """
    if len(series) <= max_points:
        return series

    total_seconds = (series.index[-1] - series.index[0]).total_seconds()
    freq_seconds = max(1, int(total_seconds / max_points))

    if freq_seconds < 60:
        freq = f"{freq_seconds}s"
    elif freq_seconds < 3600:
        freq = f"{max(1, freq_seconds // 60)}min"
    else:
        freq = f"{max(1, freq_seconds // 3600)}h"

    return series.resample(freq).mean()


def power_flow_timeline(results: SimulationResults) -> str:
    """Stacked area chart of power flows over time.

    Shows PV generation, demand, self-consumption, grid import and grid
    export with a range-slider for zooming.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, or ``"{}"`` if Plotly is unavailable.
    """
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    # Build a DataFrame from the relevant series and downsample
    df = pd.DataFrame({
        "PV Generation": results.generation,
        "Demand": results.demand,
        "Self-Consumption": results.self_consumption,
        "Grid Import": results.grid_import,
        "Grid Export": results.grid_export,
    })
    df = _adaptive_downsample(df)

    series_meta = [
        ("PV Generation", COLOUR_PALETTE["pv_generation"]),
        ("Demand", COLOUR_PALETTE["demand"]),
        ("Self-Consumption", COLOUR_PALETTE["self_consumption"]),
        ("Grid Import", COLOUR_PALETTE["grid_import"]),
        ("Grid Export", COLOUR_PALETTE["grid_export"]),
    ]

    traces: list[Any] = []
    dates = [d.isoformat() for d in df.index]
    for col, colour in series_meta:
        traces.append(
            go.Scatter(
                name=col,
                x=dates,
                y=df[col].round(4).tolist(),
                mode="lines",
                stackgroup="one",
                line=dict(width=0.5, color=colour),
                fillcolor=colour.replace(")", ",0.3)").replace("#", "rgba(")
                if colour.startswith("rgba")
                else None,
            )
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Power Flow Timeline",
        xaxis=dict(
            title="Time",
            rangeslider=dict(visible=True),
        ),
        yaxis=dict(title="Power (kW)"),
        height=500,
    )
    return fig.to_json()


def battery_soc_chart(results: SimulationResults, battery_capacity_kwh: float) -> str:
    """Line chart with fill-to-zero for battery state of charge.

    Adds horizontal threshold lines at 10% and 90% of capacity.

    Args:
        results: SimulationResults instance.
        battery_capacity_kwh: Nominal battery capacity in kWh.

    Returns:
        Plotly figure JSON string, or ``"{}"`` if Plotly is unavailable.
    """
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    soc = _adaptive_downsample_series(results.battery_soc)
    dates = [d.isoformat() for d in soc.index]
    values = soc.round(4).tolist()

    trace = go.Scatter(
        name="Battery SOC",
        x=dates,
        y=values,
        mode="lines",
        fill="tozeroy",
        line=dict(color=COLOUR_PALETTE["battery_charge"], width=1.5),
        fillcolor="rgba(80,227,194,0.15)",
    )

    fig = go.Figure(data=[trace])

    # Add threshold lines at 10% and 90%
    low_threshold = battery_capacity_kwh * 0.10
    high_threshold = battery_capacity_kwh * 0.90

    fig.add_hline(
        y=low_threshold,
        line_dash="dash",
        line_color="#d0021b",
        annotation_text="10%",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=high_threshold,
        line_dash="dash",
        line_color="#7ed321",
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
    return fig.to_json()


def sankey_diagram(summary: dict[str, Any]) -> str:
    """Sankey diagram of energy flows from PV and Grid to end uses.

    Args:
        summary: Dictionary with SummaryStatistics fields.

    Returns:
        Plotly figure JSON string, or ``"{}"`` if Plotly is unavailable.
    """
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    total_gen = summary.get("total_generation_kwh", 0)
    total_demand = summary.get("total_demand_kwh", 0)
    total_self = summary.get("total_self_consumption_kwh", 0)
    total_export = summary.get("total_grid_export_kwh", 0)
    total_import = summary.get("total_grid_import_kwh", 0)
    total_charge = summary.get("total_battery_charge_kwh", 0)
    total_discharge = summary.get("total_battery_discharge_kwh", 0)

    # Nodes: PV(0), Grid(1), Battery(2), Demand(3), Export(4)
    node_labels = ["PV Generation", "Grid", "Battery", "Demand", "Export"]
    node_colours = [
        COLOUR_PALETTE["pv_generation"],
        COLOUR_PALETTE["grid_import"],
        COLOUR_PALETTE["battery_charge"],
        COLOUR_PALETTE["demand"],
        COLOUR_PALETTE["grid_export"],
    ]

    # Links
    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_colours: list[str] = []

    # PV -> Self-consumption (direct to demand)
    pv_direct = max(0, total_self - total_discharge)
    if pv_direct > 0.01:
        sources.append(0)
        targets.append(3)
        values.append(round(pv_direct, 2))
        link_colours.append("rgba(126,211,33,0.4)")

    # PV -> Battery
    if total_charge > 0.01:
        sources.append(0)
        targets.append(2)
        values.append(round(total_charge, 2))
        link_colours.append("rgba(80,227,194,0.4)")

    # PV -> Export
    if total_export > 0.01:
        sources.append(0)
        targets.append(4)
        values.append(round(total_export, 2))
        link_colours.append("rgba(74,144,226,0.4)")

    # Grid -> Demand
    if total_import > 0.01:
        sources.append(1)
        targets.append(3)
        values.append(round(total_import, 2))
        link_colours.append("rgba(155,155,155,0.4)")

    # Battery -> Demand
    if total_discharge > 0.01:
        sources.append(2)
        targets.append(3)
        values.append(round(total_discharge, 2))
        link_colours.append("rgba(80,227,194,0.4)")

    if not values:
        return "{}"

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=20,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=node_labels,
            color=node_colours,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color=link_colours,
        ),
    )])

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Energy Flow",
        height=450,
    )
    return fig.to_json()


def daily_energy_balance(results: SimulationResults) -> str:
    """Grouped bar chart of daily generation, demand and related metrics.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, or ``"{}"`` if Plotly is unavailable.
    """
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    from solar_challenge.output import aggregate_daily  # noqa: PLC0415

    daily = aggregate_daily(results)
    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    series_meta: list[tuple[str, str, str]] = [
        ("generation_kwh", "Generation", COLOUR_PALETTE["pv_generation"]),
        ("demand_kwh", "Demand", COLOUR_PALETTE["demand"]),
        ("self_consumption_kwh", "Self-Consumption", COLOUR_PALETTE["self_consumption"]),
        ("grid_import_kwh", "Grid Import", COLOUR_PALETTE["grid_import"]),
        ("grid_export_kwh", "Grid Export", COLOUR_PALETTE["grid_export"]),
    ]

    traces: list[Any] = []
    for col, name, colour in series_meta:
        if col in daily.columns:
            traces.append(
                go.Bar(
                    name=name,
                    x=dates,
                    y=daily[col].round(3).tolist(),
                    marker_color=colour,
                )
            )

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Daily Energy Balance",
        barmode="group",
        xaxis=dict(title="Date", type="category"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return fig.to_json()


def monthly_summary(results: SimulationResults) -> str | None:
    """Stacked bar chart of monthly energy breakdown.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, ``None`` if the simulation spans
        fewer than 90 days, or ``"{}"`` if Plotly is unavailable.
    """
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1
    if sim_days < 90:
        return None

    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    from solar_challenge.output import aggregate_monthly  # noqa: PLC0415

    monthly = aggregate_monthly(results)
    months = [d.strftime("%Y-%m") for d in monthly.index]

    series_meta: list[tuple[str, str, str]] = [
        ("self_consumption_kwh", "Self-Consumption", COLOUR_PALETTE["self_consumption"]),
        ("grid_import_kwh", "Grid Import", COLOUR_PALETTE["grid_import"]),
        ("grid_export_kwh", "Grid Export", COLOUR_PALETTE["grid_export"]),
    ]

    traces: list[Any] = []
    for col, name, colour in series_meta:
        if col in monthly.columns:
            traces.append(
                go.Bar(
                    name=name,
                    x=months,
                    y=monthly[col].round(2).tolist(),
                    marker_color=colour,
                )
            )

    fig = go.Figure(data=traces)
    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Monthly Energy Summary",
        barmode="stack",
        xaxis=dict(title="Month", type="category"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return fig.to_json()


def financial_breakdown(results: SimulationResults, tariff_config: Any | None = None) -> str:
    """Dual-axis chart with daily cost bars and a cumulative savings line.

    If no tariff_config is supplied, defaults to an import rate of
    0.245 GBP/kWh and an export rate of 0.15 GBP/kWh.

    Args:
        results: SimulationResults instance.
        tariff_config: Optional tariff configuration (unused for now;
            reserved for future expansion).

    Returns:
        Plotly figure JSON string, or ``"{}"`` if Plotly is unavailable.
    """
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
        from plotly.subplots import make_subplots  # noqa: PLC0415
    except ImportError:
        return "{}"

    import_rate = 0.245
    export_rate = 0.15

    from solar_challenge.output import aggregate_daily  # noqa: PLC0415

    daily = aggregate_daily(results)
    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    daily_cost = (daily.get("grid_import_kwh", 0) * import_rate).round(2)
    daily_revenue = (daily.get("grid_export_kwh", 0) * export_rate).round(2)
    daily_net = (daily_cost - daily_revenue).round(2)
    cumulative_savings = (-daily_net).cumsum().round(2)

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
            line=dict(color="#4a90e2", width=2),
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

    return fig.to_json()


def seasonal_comparison(results: SimulationResults) -> str | None:
    """Winter vs Summer grouped bar chart.

    Winter is defined as Dec-Feb and Summer as Jun-Aug.

    Args:
        results: SimulationResults instance.

    Returns:
        Plotly figure JSON string, ``None`` if the simulation spans
        fewer than 180 days, or ``"{}"`` if Plotly is unavailable.
    """
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1
    if sim_days < 180:
        return None

    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    from solar_challenge.output import calculate_seasonal_metrics  # noqa: PLC0415

    metrics = calculate_seasonal_metrics(results.demand, results.generation)

    categories = ["Generation (kWh)", "Demand (kWh)", "Self-Consumption (kWh)"]
    winter_vals = [
        round(metrics["winter_generation_kwh"], 1),
        round(metrics["winter_demand_kwh"], 1),
        round(metrics["winter_self_consumption_kwh"], 1),
    ]
    summer_vals = [
        round(metrics["summer_generation_kwh"], 1),
        round(metrics["summer_demand_kwh"], 1),
        round(metrics["summer_self_consumption_kwh"], 1),
    ]

    fig = go.Figure(data=[
        go.Bar(name="Winter (Dec-Feb)", x=categories, y=winter_vals, marker_color="#4a90e2"),
        go.Bar(name="Summer (Jun-Aug)", x=categories, y=summer_vals, marker_color="#f5a623"),
    ])

    fig.update_layout(
        **_SHARED_LAYOUT,
        title="Seasonal Comparison",
        barmode="group",
        xaxis=dict(title="Metric"),
        yaxis=dict(title="Energy (kWh)"),
        height=420,
    )
    return fig.to_json()


def heat_pump_analysis(results: SimulationResults) -> dict[str, str] | None:
    """Charts for heat pump load analysis.

    Args:
        results: SimulationResults instance.

    Returns:
        Dictionary with ``'cop_chart'`` and ``'load_share_chart'`` keys
        containing Plotly JSON strings, or ``None`` if no heat pump data
        is present.
    """
    if results.heat_pump_load is None:
        return None

    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return None

    # --- Load share pie chart ---
    hp_total = float(results.heat_pump_load.sum() / 60)  # kWh
    total_demand = float(results.demand.sum() / 60)  # kWh
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
    hp_series = _adaptive_downsample_series(results.heat_pump_load)
    dates = [d.isoformat() for d in hp_series.index]

    load_fig = go.Figure(data=[go.Scatter(
        name="Heat Pump Load",
        x=dates,
        y=hp_series.round(4).tolist(),
        mode="lines",
        fill="tozeroy",
        line=dict(color=COLOUR_PALETTE["heat_pump"], width=1),
        fillcolor="rgba(144,19,254,0.15)",
    )])
    load_fig.update_layout(
        **_SHARED_LAYOUT,
        title="Heat Pump Load Profile",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Power (kW)"),
        height=400,
    )

    return {
        "load_share_chart": pie_fig.to_json(),
        "cop_chart": load_fig.to_json(),
    }
