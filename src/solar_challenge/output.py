# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-run output: a run's CSV export and markdown summary report, its seasonal and period aggregation, and a community's metrics and report."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, TypeVar, Union

import pandas as pd

from solar_challenge.demand import LoadKind
from solar_challenge.home import (
    RunPricing,
    SimulationResults,
    SummaryStatistics,
    calculate_summary,
    grid_dependency_ratio,
    load_ratio,
    self_consumption_ratio,
)
from solar_challenge.dispatch import GridChargeForecast, distinct_grid_charge_forecasts
from solar_challenge.grid_charge_forecast import GRID_CHARGE_FORECAST_LABELS
from solar_challenge.timebase import SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.community import CommunityResults, SharingMode


_WINTER_MONTHS = (12, 1, 2)
_SUMMER_MONTHS = (6, 7, 8)

_TimeIndexed = TypeVar("_TimeIndexed", pd.Series, pd.DataFrame)


def _in_months(rows: _TimeIndexed, months: tuple[int, ...]) -> _TimeIndexed:
    """The rows of *rows* whose timestamps fall in *months*."""
    return rows[rows.index.month.isin(months)]


def _days_lasted(row_count: int, cadence: timedelta) -> float:
    """The days *row_count* rows last in all, each lasting *cadence*."""
    return row_count * cadence / timedelta(days=1)


def grid_charge_forecast_notice(forecasts: Sequence[GridChargeForecast]) -> str:
    """The paragraph, ending in a blank line, that tells the board which forecasts sized a report's battery grid charging, each with what it is; empty when nothing grid-charged."""
    if not forecasts:
        return ""
    sized_by = "; and by ".join(
        f"the {forecast} forecast: {GRID_CHARGE_FORECAST_LABELS[forecast]}" for forecast in forecasts
    )
    return f"*Battery grid charging in cheap periods was sized by {sized_by}.*\n\n"


def _seg_rate_row(pricing: RunPricing | None) -> str:
    """The Financial table's SEG Rate row, ending in a newline, naming the SEG rate that priced a run's export; empty when no SEG priced it."""
    if pricing is None or pricing.seg_rate_pence_per_kwh is None:
        return ""
    return f"| SEG Rate | {pricing.seg_rate_pence_per_kwh:.1f} p/kWh |\n"


def export_to_csv(
    results: SimulationResults,
    filepath: Union[str, Path],
    include_index: bool = True,
) -> Path:
    """Export simulation results to CSV file.

    Args:
        results: Simulation results to export
        filepath: Output file path
        include_index: Whether to include datetime index in output

    Returns:
        Path to the created file
    """
    filepath = Path(filepath)
    df = results.to_dataframe()
    df.to_csv(filepath, index=include_index)
    return filepath


def generate_summary_report(
    results: SimulationResults,
    home_name: Optional[str] = None,
) -> str:
    """Generate a text summary report of simulation results.

    Args:
        results: Simulation results
        home_name: Optional name for the home

    Returns:
        Formatted markdown text report. When a forecast sized the run's grid
        charge, it opens, under its title, with a notice naming the forecast.
        Its Demand by load table, after the Energy Totals, gives each load's
        energy, share of the demand and peak. For a run with an additional load
        and rows in both winter and summer, a winter-against-summer table of
        each additional load follows the Battery table. When a SEG rate priced
        the run's export, its Financial table names that rate, after the Grid
        Export Revenue it earned.
    """
    summary = calculate_summary(results)
    loads = results.loads

    title = f"# Simulation Report: {home_name}" if home_name else "# Simulation Report"
    notice = grid_charge_forecast_notice(distinct_grid_charge_forecasts([summary.grid_charge_forecast]))

    report = f"""{title}

{notice}## Simulation Period
- Duration: {summary.simulation_days} days
- Start: {results.generation.index[0]}
- End: {results.generation.index[-1]}

## Energy Totals (kWh)
| Metric | Value |
|--------|-------|
| Generation | {summary.total_generation_kwh:.1f} |
| Demand | {summary.total_demand_kwh:.1f} |
| Self-Consumption | {summary.total_self_consumption_kwh:.1f} |
| Grid Import | {summary.total_grid_import_kwh:.1f} |
| Grid Export | {summary.total_grid_export_kwh:.1f} |

{_demand_by_load_section(summary, loads)}
## Battery (kWh)
| Metric | Value |
|--------|-------|
| Total Charged | {summary.total_battery_charge_kwh:.1f} |
| Total Discharged | {summary.total_battery_discharge_kwh:.1f} |
"""

    report += _seasonal_load_section(results)

    report += f"""
## Peak Values (kW)
| Metric | Value |
|--------|-------|
| Peak Generation | {summary.peak_generation_kw:.2f} |
| Peak Demand | {summary.peak_demand_kw:.2f} |

## Efficiency Ratios
| Metric | Value |
|--------|-------|
| Self-Consumption Ratio | {summary.self_consumption_ratio:.1%} |
| Grid Dependency | {summary.grid_dependency_ratio:.1%} |
| Export Ratio | {summary.export_ratio:.1%} |

## Daily Averages (kWh/day)
| Metric | Value |
|--------|-------|
| Average Generation | {summary.total_generation_kwh / summary.simulation_days:.1f} |
| Average Demand | {summary.total_demand_kwh / summary.simulation_days:.1f} |
| Average Self-Consumption | {summary.total_self_consumption_kwh / summary.simulation_days:.1f} |

## Financial (£)
| Metric | Value |
|--------|-------|
| Grid Import Cost | {summary.total_import_cost_gbp:.2f} |
| Grid Export Revenue | {summary.total_export_revenue_gbp:.2f} |
{_seg_rate_row(summary.pricing)}| Net Cost | {summary.net_cost_gbp:.2f} |
"""

    return report


def _demand_by_load_section(summary: SummaryStatistics, loads: Mapping[LoadKind, pd.Series]) -> str:
    """The Demand by load table: a row of each load's energy, share of the demand and peak, in LoadKind order."""
    rows = "".join(
        f"| {kind.label} | {summary.load_energy_kwh[kind]:.1f} | {summary.load_share(kind):.1%} | {float(load.max()):.2f} |\n"
        for kind, load in loads.items()
    )
    return f"""## Demand by load
| Load | Energy (kWh) | Share of Demand | Peak (kW) |
|------|--------------|-----------------|-----------|
{rows}"""


@dataclass(frozen=True, kw_only=True)
class _LoadSeason:
    """One additional load over one season's rows: its energy, its peak, its share of the season's demand and its energy per day."""

    energy_kwh: float
    peak_kw: float
    share_of_demand: float
    daily_kwh: float

    @classmethod
    def of(
        cls, kind: LoadKind, load: pd.Series, amounts: pd.DataFrame, months: tuple[int, ...], cadence: timedelta
    ) -> "_LoadSeason":
        """*kind*'s figures over the rows in *months*: *load* is its kW and *amounts* the run's per_step_amounts(), each row lasting *cadence*."""
        season_amounts = _in_months(amounts, months)
        energy_kwh = float(season_amounts[kind.energy_column].sum())
        return cls(
            energy_kwh=energy_kwh,
            peak_kw=float(_in_months(load, months).max()),
            share_of_demand=load_ratio(load_kwh=energy_kwh, demand_kwh=float(season_amounts["demand_kwh"].sum())),
            daily_kwh=energy_kwh / _days_lasted(len(season_amounts), cadence),
        )


def _winter_over_summer_cell(winter: float, summer: float) -> str:
    """The Winter/Summer Ratio cell: *winter* divided by *summer*, written as a multiple such as "8.0x", or "-" when summer is not positive."""
    return f"{winter / summer:.1f}x" if summer > 0 else "-"


def _seasonal_load_table(kind: LoadKind, winter: _LoadSeason, summer: _LoadSeason) -> str:
    """*kind*'s table of its winter and summer figures, each winter figure but the share also as a multiple of summer's."""
    return f"""
### {kind.label}
| Metric | Winter | Summer | Winter/Summer Ratio |
|--------|--------|--------|---------------------|
| Energy | {winter.energy_kwh:.1f} kWh | {summer.energy_kwh:.1f} kWh | {_winter_over_summer_cell(winter.energy_kwh, summer.energy_kwh)} |
| Peak | {winter.peak_kw:.2f} kW | {summer.peak_kw:.2f} kW | {_winter_over_summer_cell(winter.peak_kw, summer.peak_kw)} |
| Share of Demand | {winter.share_of_demand:.1%} | {summer.share_of_demand:.1%} | - |
| Daily Average | {winter.daily_kwh:.1f} kWh/day | {summer.daily_kwh:.1f} kWh/day | {_winter_over_summer_cell(winter.daily_kwh, summer.daily_kwh)} |
"""


def _seasonal_load_section(results: SimulationResults) -> str:
    """The Seasonal demand by load section: each additional load's winter (Dec-Feb) and summer (Jun-Aug) table, in LoadKind order.

    Empty for a run whose demand is the household's alone, or with no row in winter or none in
    summer, since there is then no season to compare with the other.
    """
    if not results.additional_loads:
        return ""
    amounts = results.per_step_amounts()
    if _in_months(amounts, _WINTER_MONTHS).empty or _in_months(amounts, _SUMMER_MONTHS).empty:
        return ""
    cadence = results.window.cadence
    tables = "".join(
        _seasonal_load_table(
            kind,
            winter=_LoadSeason.of(kind, load, amounts, _WINTER_MONTHS, cadence),
            summer=_LoadSeason.of(kind, load, amounts, _SUMMER_MONTHS, cadence),
        )
        for kind, load in results.additional_loads.items()
    )
    return f"""
## Seasonal demand by load

**Winter (Dec-Feb) vs Summer (Jun-Aug)**
{tables}"""


@dataclass(frozen=True, kw_only=True)
class SeasonSummary:
    """One season of a run: its energy totals in kWh, and calculate_summary's two ratios of them.

    self_consumption_ratio and grid_dependency_ratio are home.self_consumption_ratio and
    home.grid_dependency_ratio of the season's totals.
    """

    generation_kwh: float
    demand_kwh: float
    self_consumption_kwh: float
    self_consumption_ratio: float
    grid_dependency_ratio: float


@dataclass(frozen=True, kw_only=True)
class SeasonalMetrics:
    """A run's winter (Dec-Feb) and summer (Jun-Aug) summaries."""

    winter: SeasonSummary
    summer: SeasonSummary


def _season_summary(amounts: pd.DataFrame, months: tuple[int, ...]) -> SeasonSummary:
    """The summary of the rows in *months* of *amounts*, a run's per_step_amounts()."""
    totals = _in_months(amounts, months).sum()
    return SeasonSummary(
        generation_kwh=float(totals["generation_kwh"]),
        demand_kwh=float(totals["demand_kwh"]),
        self_consumption_kwh=float(totals["self_consumption_kwh"]),
        self_consumption_ratio=self_consumption_ratio(
            self_consumption_kwh=totals["self_consumption_kwh"], generation_kwh=totals["generation_kwh"]
        ),
        grid_dependency_ratio=grid_dependency_ratio(
            grid_import_kwh=totals["grid_import_kwh"], demand_kwh=totals["demand_kwh"]
        ),
    )


def calculate_seasonal_metrics(results: SimulationResults) -> SeasonalMetrics:
    """The run's winter (Dec-Feb) and summer (Jun-Aug) totals and ratios.

    Each total is the season's sum of the run's own per-minute amounts, so self-consumption
    counts battery discharge as calculate_summary's does. The ratios are calculate_summary's,
    of the season's totals. A season with none of the run's rows has 0.0 for every figure.
    """
    amounts = results.per_step_amounts()
    return SeasonalMetrics(
        winter=_season_summary(amounts, _WINTER_MONTHS),
        summer=_season_summary(amounts, _SUMMER_MONTHS),
    )


def _aggregate_by_period(results: SimulationResults, freq: str) -> pd.DataFrame:
    """Sum each period's per-minute amounts and take its peak generation and demand.

    Args:
        results: Simulation results with 1-minute resolution
        freq: pandas offset alias of the period, e.g. "D" or "ME"
    """
    totals = results.per_step_amounts().resample(freq).sum()
    peaks = pd.DataFrame(
        {"peak_generation_kw": results.generation, "peak_demand_kw": results.demand}
    ).resample(freq).max()
    return pd.concat([totals, peaks], axis=1)


def aggregate_daily(results: SimulationResults) -> pd.DataFrame:
    """Aggregate 1-minute results to daily totals and peaks.

    Args:
        results: Simulation results with 1-minute resolution

    Returns:
        DataFrame with a daily DatetimeIndex holding each day's energy totals in
        kWh, money totals in £ (sums of the per-minute £ amounts) and peak
        generation and demand in kW. Each additional load's energy column
        (LoadKind.energy_column), ``grid_charge_cost_gbp`` and
        ``grid_charge_kwh`` appear only when the run has those series.
    """
    return _aggregate_by_period(results, "D")


def aggregate_monthly(results: SimulationResults) -> pd.DataFrame:
    """Aggregate 1-minute results to monthly totals and peaks.

    Args:
        results: Simulation results with 1-minute resolution

    Returns:
        DataFrame indexed by month end, with the columns of :func:`aggregate_daily`
    """
    return _aggregate_by_period(results, "ME")


@dataclass
class CommunityMetrics:
    """Pre-computed kWh aggregates for a community simulation result.

    Extracted from :class:`~solar_challenge.community.CommunityResults` so that
    both the markdown report (:func:`generate_community_report`) and the Rich
    CLI table (:func:`~solar_challenge.cli.fleet._print_community_section`) can
    consume identical figures from a single derivation.
    """

    dt_h: float
    community_import_kwh: float
    community_export_kwh: float
    unshared_import_kwh: float
    unshared_export_kwh: float
    total_demand_kwh: float
    self_sufficiency: float
    import_reduction_kwh: float
    export_reduction_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    #: Authoritative sharing mode, read directly from CommunityResults.sharing_mode.
    sharing_mode: "SharingMode"


def compute_community_metrics(community_results: "CommunityResults") -> CommunityMetrics:
    """Derive kWh aggregates from a :class:`~solar_challenge.community.CommunityResults`.

    Each figure integrates its kW series over the window
    :meth:`~solar_challenge.timebase.SimulationWindow.of_index` reads from the
    community's index, so the figures hold at any cadence.

    Raises:
        ValueError: As :meth:`~solar_challenge.timebase.SimulationWindow.of_index`
            does, for an index no window describes.
    """
    cr = community_results
    fleet = cr.fleet_results

    window = SimulationWindow.of_index(cr.grid_import.index)

    community_import_kwh = window.energy_kwh(cr.grid_import)
    community_export_kwh = window.energy_kwh(cr.grid_export)
    unshared_import_kwh = window.energy_kwh(fleet.total_grid_import)
    unshared_export_kwh = window.energy_kwh(fleet.total_grid_export)
    total_demand_kwh = window.energy_kwh(fleet.total_demand)

    if total_demand_kwh > 0:
        self_sufficiency = max(0.0, 1.0 - community_import_kwh / total_demand_kwh)
    else:
        self_sufficiency = 0.0

    sharing_mode = cr.sharing_mode

    return CommunityMetrics(
        dt_h=window.step_hours,
        community_import_kwh=community_import_kwh,
        community_export_kwh=community_export_kwh,
        unshared_import_kwh=unshared_import_kwh,
        unshared_export_kwh=unshared_export_kwh,
        total_demand_kwh=total_demand_kwh,
        self_sufficiency=self_sufficiency,
        import_reduction_kwh=unshared_import_kwh - community_import_kwh,
        export_reduction_kwh=unshared_export_kwh - community_export_kwh,
        battery_charge_kwh=window.energy_kwh(cr.battery_charge),
        battery_discharge_kwh=window.energy_kwh(cr.battery_discharge),
        sharing_mode=sharing_mode,
    )


def generate_community_report(
    community_results: "CommunityResults",
    community_summary: Optional[Mapping[str, Any]] = None,
) -> str:
    """Generate a markdown report for a community energy sharing simulation.

    Mirrors :func:`generate_summary_report` in structure.  All kWh figures are
    derived via :func:`compute_community_metrics` over the window the
    community's index describes, so the report is correct for any series
    cadence.

    Args:
        community_results: Output of :func:`~solar_challenge.community.simulate_community`.
        community_summary: Optional mapping of extra key/value metadata to
            append as a separate section.

    Returns:
        Formatted markdown report string. When forecasts sized the grid charge
        of the fleet's homes, whose grid flows it nets, it opens, under its
        title, with a notice naming each, and what it is.
    """
    m = compute_community_metrics(community_results)
    notice = grid_charge_forecast_notice(
        distinct_grid_charge_forecasts(
            home.grid_charge_forecast for home in community_results.fleet_results.per_home_results
        )
    )

    report = f"""# Community Energy Sharing Report

{notice}## Sharing Mode
{m.sharing_mode}

## Community vs Unshared Grid Flows (kWh)
| Metric | Unshared (Σ per-home) | Community | Reduction |
|--------|-----------------------|-----------|-----------|
| Grid Import | {m.unshared_import_kwh:.2f} | {m.community_import_kwh:.2f} | {m.import_reduction_kwh:.2f} |
| Grid Export | {m.unshared_export_kwh:.2f} | {m.community_export_kwh:.2f} | {m.export_reduction_kwh:.2f} |

## Community Self-Sufficiency
{m.self_sufficiency:.1%}
"""

    # Community Battery section — only when battery was active
    if m.battery_charge_kwh > 0 or m.battery_discharge_kwh > 0:
        report += f"""
## Community Battery (kWh)
| Metric | Value |
|--------|-------|
| Charged | {m.battery_charge_kwh:.2f} |
| Discharged | {m.battery_discharge_kwh:.2f} |
"""

    # Community Billing section — only when simulate_community priced the grid flows
    if community_results.community_savings_gbp is not None:
        report += f"""
## Community Billing (£)
| Metric | Value (£) |
|--------|-----------|
| Baseline Net Cost | {community_results.baseline_net_cost_gbp:.2f} |
| Community Net Cost | {community_results.community_net_cost_gbp:.2f} |
| Community Savings | {community_results.community_savings_gbp:.2f} |
"""

    # Optional extra summary section
    if community_summary is not None:
        report += "\n## Additional Information\n"
        for key, value in community_summary.items():
            report += f"- {key}: {value}\n"

    return report
