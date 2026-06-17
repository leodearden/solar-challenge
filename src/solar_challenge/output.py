# SPDX-License-Identifier: AGPL-3.0-or-later
"""Output and reporting functions for simulation results."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

import pandas as pd

from solar_challenge.home import SimulationResults, SummaryStatistics, calculate_summary

if TYPE_CHECKING:
    from solar_challenge.community import CommunityResults
    from solar_challenge.finance import BillDistribution, CostRecoverySolution, ProjectEconomics


@dataclass(frozen=True)
class StrategyComparisonResult:
    """Result of comparing two dispatch strategies.

    All delta values are calculated as (alternative - baseline).
    Negative delta_grid_import_kwh means the alternative imports less from grid.

    Attributes:
        baseline_strategy: Name of the baseline strategy
        alternative_strategy: Name of the alternative strategy
        baseline_summary: Summary statistics for baseline
        alternative_summary: Summary statistics for alternative
        delta_grid_import_kwh: Change in grid import (kWh)
        delta_grid_export_kwh: Change in grid export (kWh)
        delta_self_consumption_kwh: Change in self-consumption (kWh)
        peak_import_reduction_pct: Percentage reduction in peak grid import
    """

    baseline_strategy: str
    alternative_strategy: str
    baseline_summary: SummaryStatistics
    alternative_summary: SummaryStatistics
    delta_grid_import_kwh: float
    delta_grid_export_kwh: float
    delta_self_consumption_kwh: float
    peak_import_reduction_pct: float


def compare_strategies(
    baseline: SimulationResults,
    alternative: SimulationResults,
) -> StrategyComparisonResult:
    """Compare two simulation results from different dispatch strategies.

    Calculates deltas between an alternative strategy and a baseline,
    showing the impact of switching strategies on grid import, export,
    self-consumption, and peak demand.

    Args:
        baseline: Results from the baseline strategy (e.g., self-consumption)
        alternative: Results from the alternative strategy (e.g., TOU or peak-shaving)

    Returns:
        StrategyComparisonResult with deltas and percentage improvements
    """
    base_summary = calculate_summary(baseline)
    alt_summary = calculate_summary(alternative)

    # Peak grid import reduction
    base_peak_import = float(baseline.grid_import.max())
    alt_peak_import = float(alternative.grid_import.max())
    if base_peak_import > 0:
        peak_reduction_pct = (base_peak_import - alt_peak_import) / base_peak_import * 100
    else:
        peak_reduction_pct = 0.0

    return StrategyComparisonResult(
        baseline_strategy=baseline.strategy_name,
        alternative_strategy=alternative.strategy_name,
        baseline_summary=base_summary,
        alternative_summary=alt_summary,
        delta_grid_import_kwh=alt_summary.total_grid_import_kwh - base_summary.total_grid_import_kwh,
        delta_grid_export_kwh=alt_summary.total_grid_export_kwh - base_summary.total_grid_export_kwh,
        delta_self_consumption_kwh=alt_summary.total_self_consumption_kwh - base_summary.total_self_consumption_kwh,
        peak_import_reduction_pct=peak_reduction_pct,
    )


def generate_comparison_report(
    comparison: StrategyComparisonResult,
) -> str:
    """Generate a markdown report comparing two dispatch strategies.

    Args:
        comparison: Strategy comparison result

    Returns:
        Formatted markdown text report
    """
    base = comparison.baseline_summary
    alt = comparison.alternative_summary

    report = f"""# Strategy Comparison Report

## Strategies
- Baseline: {comparison.baseline_strategy}
- Alternative: {comparison.alternative_strategy}

## Energy Comparison (kWh)
| Metric | Baseline | Alternative | Delta |
|--------|----------|-------------|-------|
| Grid Import | {base.total_grid_import_kwh:.1f} | {alt.total_grid_import_kwh:.1f} | {comparison.delta_grid_import_kwh:+.1f} |
| Grid Export | {base.total_grid_export_kwh:.1f} | {alt.total_grid_export_kwh:.1f} | {comparison.delta_grid_export_kwh:+.1f} |
| Self-Consumption | {base.total_self_consumption_kwh:.1f} | {alt.total_self_consumption_kwh:.1f} | {comparison.delta_self_consumption_kwh:+.1f} |
| Battery Charged | {base.total_battery_charge_kwh:.1f} | {alt.total_battery_charge_kwh:.1f} | {alt.total_battery_charge_kwh - base.total_battery_charge_kwh:+.1f} |
| Battery Discharged | {base.total_battery_discharge_kwh:.1f} | {alt.total_battery_discharge_kwh:.1f} | {alt.total_battery_discharge_kwh - base.total_battery_discharge_kwh:+.1f} |

## Efficiency Comparison
| Metric | Baseline | Alternative |
|--------|----------|-------------|
| Self-Consumption Ratio | {base.self_consumption_ratio:.1%} | {alt.self_consumption_ratio:.1%} |
| Grid Dependency | {base.grid_dependency_ratio:.1%} | {alt.grid_dependency_ratio:.1%} |
| Export Ratio | {base.export_ratio:.1%} | {alt.export_ratio:.1%} |

## Peak Import Reduction
- Peak import reduction: {comparison.peak_import_reduction_pct:.1f}%
"""
    return report


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
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> str:
    """Generate a text summary report of simulation results.

    Args:
        results: Simulation results
        home_name: Optional name for the home
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, a SEG Revenue section is included in the report.

    Returns:
        Formatted markdown text report
    """
    summary = calculate_summary(results, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh)

    title = f"# Simulation Report: {home_name}" if home_name else "# Simulation Report"

    report = f"""{title}

## Simulation Period
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

## Battery (kWh)
| Metric | Value |
|--------|-------|
| Total Charged | {summary.total_battery_charge_kwh:.1f} |
| Total Discharged | {summary.total_battery_discharge_kwh:.1f} |
"""

    # Add heat pump section if heat pump metrics are present
    if summary.total_heat_pump_load_kwh is not None:
        report += f"""
## Heat Pump Impact
| Metric | Value |
|--------|-------|
| Total Heat Pump Load | {summary.total_heat_pump_load_kwh:.1f} kWh |
| Peak Heat Pump Load | {summary.peak_heat_pump_load_kw:.2f} kW |
| Heat Pump % of Total Demand | {summary.heat_pump_load_ratio:.1%} |
"""

        # Add seasonal breakdown if we have heat pump load data
        if results.heat_pump_load is not None:
            # Calculate seasonal heat pump metrics
            months = results.heat_pump_load.index.month
            winter_mask = months.isin([12, 1, 2])
            summer_mask = months.isin([6, 7, 8])

            winter_hp_load = results.heat_pump_load[winter_mask]
            summer_hp_load = results.heat_pump_load[summer_mask]
            winter_demand = results.demand[winter_mask]
            summer_demand = results.demand[summer_mask]

            # Convert kW to kWh (1-minute resolution: divide by 60)
            winter_hp_kwh = float(winter_hp_load.sum() / 60) if len(winter_hp_load) > 0 else 0.0
            summer_hp_kwh = float(summer_hp_load.sum() / 60) if len(summer_hp_load) > 0 else 0.0
            winter_demand_kwh = float(winter_demand.sum() / 60) if len(winter_demand) > 0 else 0.0
            summer_demand_kwh = float(summer_demand.sum() / 60) if len(summer_demand) > 0 else 0.0

            winter_peak_hp_kw = float(winter_hp_load.max()) if len(winter_hp_load) > 0 else 0.0
            summer_peak_hp_kw = float(summer_hp_load.max()) if len(summer_hp_load) > 0 else 0.0

            winter_hp_ratio = winter_hp_kwh / winter_demand_kwh if winter_demand_kwh > 0 else 0.0
            summer_hp_ratio = summer_hp_kwh / summer_demand_kwh if summer_demand_kwh > 0 else 0.0

            # Calculate average daily values
            winter_days = len(winter_hp_load) / (60 * 24) if len(winter_hp_load) > 0 else 1
            summer_days = len(summer_hp_load) / (60 * 24) if len(summer_hp_load) > 0 else 1
            winter_daily_avg = winter_hp_kwh / winter_days if winter_days > 0 else 0.0
            summer_daily_avg = summer_hp_kwh / summer_days if summer_days > 0 else 0.0

            report += f"""
### Seasonal Heat Pump Analysis
**Winter (Dec-Feb) vs Summer (Jun-Aug)**

| Metric | Winter | Summer | Winter/Summer Ratio |
|--------|--------|--------|---------------------|
| Total Heat Pump Load | {winter_hp_kwh:.1f} kWh | {summer_hp_kwh:.1f} kWh | {(winter_hp_kwh / summer_hp_kwh if summer_hp_kwh > 0 else 0):.1f}x |
| Peak Heat Pump Load | {winter_peak_hp_kw:.2f} kW | {summer_peak_hp_kw:.2f} kW | {(winter_peak_hp_kw / summer_peak_hp_kw if summer_peak_hp_kw > 0 else 0):.1f}x |
| HP % of Demand | {winter_hp_ratio:.1%} | {summer_hp_ratio:.1%} | - |
| Daily Average | {winter_daily_avg:.1f} kWh/day | {summer_daily_avg:.1f} kWh/day | {(winter_daily_avg / summer_daily_avg if summer_daily_avg > 0 else 0):.1f}x |

**Key Insights:**
- Heat pump demand is **{(winter_hp_kwh / summer_hp_kwh if summer_hp_kwh > 0 else 0):.1f}x higher** in winter than summer
- Heat pump accounts for **{winter_hp_ratio:.1%}** of winter demand vs **{summer_hp_ratio:.1%}** in summer
"""

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
| Net Cost | {summary.net_cost_gbp:.2f} |
"""

    if summary.seg_revenue_gbp is not None:
        report += f"""
## SEG Revenue
| Metric | Value |
|--------|-------|
| Tariff Rate | {seg_tariff_pence_per_kwh:.1f} p/kWh |
| Total Export | {summary.total_grid_export_kwh:.1f} kWh |
| SEG Revenue | £{summary.seg_revenue_gbp:.2f} |
"""

    return report


def calculate_self_consumption_ratio(results: SimulationResults) -> float:
    """Calculate self-consumption ratio.

    Self-consumption ratio = self_consumed / total_generation

    Args:
        results: Simulation results

    Returns:
        Ratio between 0 and 1 (or 0 if no generation)
    """
    summary = calculate_summary(results)
    return summary.self_consumption_ratio


def calculate_grid_dependency_ratio(results: SimulationResults) -> float:
    """Calculate grid dependency ratio.

    Grid dependency = grid_import / total_consumption

    Lower values indicate more self-sufficiency.

    Args:
        results: Simulation results

    Returns:
        Ratio between 0 and 1 (or 0 if no consumption)
    """
    summary = calculate_summary(results)
    return summary.grid_dependency_ratio


def calculate_export_ratio(results: SimulationResults) -> float:
    """Calculate export ratio.

    Export ratio = grid_export / total_generation

    Higher values indicate more excess PV.

    Args:
        results: Simulation results

    Returns:
        Ratio between 0 and 1 (or 0 if no generation)
    """
    summary = calculate_summary(results)
    return summary.export_ratio


def calculate_seasonal_metrics(
    demand: pd.Series,
    generation: pd.Series,
) -> dict[str, float]:
    """Calculate seasonal breakdown of energy metrics (winter vs summer).

    Winter is defined as December, January, February.
    Summer is defined as June, July, August.

    Args:
        demand: Demand time series with datetime index (kW)
        generation: Generation time series with datetime index (kW)

    Returns:
        Dictionary containing seasonal metrics including:
        - winter_generation_kwh: Total winter generation
        - winter_demand_kwh: Total winter demand
        - winter_self_consumption_kwh: Winter self-consumption
        - winter_self_consumption_ratio: Winter self-consumption / generation
        - winter_grid_dependency_ratio: Winter grid dependency
        - summer_generation_kwh: Total summer generation
        - summer_demand_kwh: Total summer demand
        - summer_self_consumption_kwh: Summer self-consumption
        - summer_self_consumption_ratio: Summer self-consumption / generation
        - summer_grid_dependency_ratio: Summer grid dependency
    """
    # Extract month from index
    months = demand.index.month

    # Define seasons (Northern Hemisphere)
    winter_mask = months.isin([12, 1, 2])
    summer_mask = months.isin([6, 7, 8])

    # Filter data by season
    winter_demand = demand[winter_mask]
    winter_generation = generation[winter_mask]
    summer_demand = demand[summer_mask]
    summer_generation = generation[summer_mask]

    # Calculate self-consumption (minimum of generation and demand at each timestep)
    winter_self_consumption = pd.Series(
        [min(g, d) for g, d in zip(winter_generation, winter_demand)],
        index=winter_generation.index,
    )
    summer_self_consumption = pd.Series(
        [min(g, d) for g, d in zip(summer_generation, summer_demand)],
        index=summer_generation.index,
    )

    # Convert kW to kWh (1-minute resolution: divide by 60)
    winter_generation_kwh = float(winter_generation.sum() / 60)
    winter_demand_kwh = float(winter_demand.sum() / 60)
    winter_self_consumption_kwh = float(winter_self_consumption.sum() / 60)

    summer_generation_kwh = float(summer_generation.sum() / 60)
    summer_demand_kwh = float(summer_demand.sum() / 60)
    summer_self_consumption_kwh = float(summer_self_consumption.sum() / 60)

    # Calculate ratios with safety checks
    winter_self_consumption_ratio = (
        winter_self_consumption_kwh / winter_generation_kwh if winter_generation_kwh > 0 else 0.0
    )
    summer_self_consumption_ratio = (
        summer_self_consumption_kwh / summer_generation_kwh if summer_generation_kwh > 0 else 0.0
    )

    # Grid dependency = (demand - self_consumption) / demand
    winter_grid_import_kwh = max(0.0, winter_demand_kwh - winter_self_consumption_kwh)
    winter_grid_dependency_ratio = (
        winter_grid_import_kwh / winter_demand_kwh if winter_demand_kwh > 0 else 0.0
    )

    summer_grid_import_kwh = max(0.0, summer_demand_kwh - summer_self_consumption_kwh)
    summer_grid_dependency_ratio = (
        summer_grid_import_kwh / summer_demand_kwh if summer_demand_kwh > 0 else 0.0
    )

    return {
        "winter_generation_kwh": winter_generation_kwh,
        "winter_demand_kwh": winter_demand_kwh,
        "winter_self_consumption_kwh": winter_self_consumption_kwh,
        "winter_self_consumption_ratio": winter_self_consumption_ratio,
        "winter_grid_dependency_ratio": winter_grid_dependency_ratio,
        "summer_generation_kwh": summer_generation_kwh,
        "summer_demand_kwh": summer_demand_kwh,
        "summer_self_consumption_kwh": summer_self_consumption_kwh,
        "summer_self_consumption_ratio": summer_self_consumption_ratio,
        "summer_grid_dependency_ratio": summer_grid_dependency_ratio,
    }


def aggregate_daily(results: SimulationResults) -> pd.DataFrame:
    """Aggregate 1-minute results to daily totals.

    Args:
        results: Simulation results with 1-minute resolution

    Returns:
        DataFrame with daily DatetimeIndex and energy totals in kWh
    """
    df = results.to_dataframe()

    # Convert power (kW) to energy (kWh) - sum of 1-minute kW values / 60
    # Resample to daily and sum, then divide by 60 to get kWh
    daily = df.resample("D").sum() / 60

    # Rename columns to indicate energy
    daily.columns = [col.replace("_kw", "_kwh") for col in daily.columns]

    # Also add daily peak values
    peaks = df.resample("D").max()
    daily["peak_generation_kw"] = peaks["generation_kw"]
    daily["peak_demand_kw"] = peaks["demand_kw"]

    return daily


def aggregate_monthly(results: SimulationResults) -> pd.DataFrame:
    """Aggregate results to monthly totals.

    Args:
        results: Simulation results

    Returns:
        DataFrame with monthly period index and energy totals in kWh
    """
    daily = aggregate_daily(results)

    # Resample to monthly - sum energy columns
    energy_cols = [col for col in daily.columns if "_kwh" in col]
    peak_cols = [col for col in daily.columns if "peak_" in col]

    monthly_energy = daily[energy_cols].resample("ME").sum()
    monthly_peaks = daily[peak_cols].resample("ME").max()

    return pd.concat([monthly_energy, monthly_peaks], axis=1)


def aggregate_annual(
    results: SimulationResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> dict[str, float]:
    """Aggregate results to annual totals.

    Args:
        results: Simulation results
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, seg_revenue_gbp is included in the returned dictionary.

    Returns:
        Dictionary with annual energy totals in kWh, and optionally SEG revenue in GBP
    """
    summary = calculate_summary(results, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh)

    annual: dict[str, float] = {
        "generation_kwh": summary.total_generation_kwh,
        "demand_kwh": summary.total_demand_kwh,
        "self_consumption_kwh": summary.total_self_consumption_kwh,
        "grid_import_kwh": summary.total_grid_import_kwh,
        "grid_export_kwh": summary.total_grid_export_kwh,
        "battery_charge_kwh": summary.total_battery_charge_kwh,
        "battery_discharge_kwh": summary.total_battery_discharge_kwh,
        "peak_generation_kw": summary.peak_generation_kw,
        "peak_demand_kw": summary.peak_demand_kw,
        "self_consumption_ratio": summary.self_consumption_ratio,
        "grid_dependency_ratio": summary.grid_dependency_ratio,
        "export_ratio": summary.export_ratio,
        "simulation_days": float(summary.simulation_days),
    }

    if summary.seg_revenue_gbp is not None:
        annual["seg_revenue_gbp"] = summary.seg_revenue_gbp

    # Include heat pump metrics if present
    if summary.total_heat_pump_load_kwh is not None:
        annual["heat_pump_load_kwh"] = summary.total_heat_pump_load_kwh
    if summary.peak_heat_pump_load_kw is not None:
        annual["peak_heat_pump_load_kw"] = summary.peak_heat_pump_load_kw
    if summary.heat_pump_load_ratio is not None:
        annual["heat_pump_load_ratio"] = summary.heat_pump_load_ratio

    return annual


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
    #: Heuristic: 'community_battery' when battery was active, else 'p2p'.
    #: TODO: read directly from CommunityResults.sharing_mode once that field
    #: is added to community.py (requires editing a module outside this task's scope).
    sharing_mode: str


def compute_community_metrics(community_results: "CommunityResults") -> CommunityMetrics:
    """Derive kWh aggregates from a :class:`~solar_challenge.community.CommunityResults`.

    Infers the timestep duration from the series index so the conversion is
    correct for any cadence (1-minute operational or hourly TMY), mirroring
    :func:`~solar_challenge.community.simulate_community`'s own derivation.
    """
    cr = community_results
    fleet = cr.fleet_results

    # Derive timestep from index so kW→kWh conversion is cadence-agnostic
    index = cr.grid_import.index
    if len(index) >= 2:
        dt_h = (index[1] - index[0]).total_seconds() / 3600.0
    else:
        dt_h = 1.0 / 60.0  # assume 1-minute for degenerate single-step index

    community_import_kwh = float(cr.grid_import.sum()) * dt_h
    community_export_kwh = float(cr.grid_export.sum()) * dt_h
    unshared_import_kwh = float(fleet.total_grid_import.sum()) * dt_h
    unshared_export_kwh = float(fleet.total_grid_export.sum()) * dt_h
    total_demand_kwh = float(fleet.total_demand.sum()) * dt_h

    if total_demand_kwh > 0:
        self_sufficiency = max(0.0, 1.0 - community_import_kwh / total_demand_kwh)
    else:
        self_sufficiency = 0.0

    # Sharing-mode heuristic: battery activity → community_battery, else p2p.
    # CommunityResults carries no sharing_mode field yet; this is the best
    # derivation possible without editing community.py (outside task scope).
    sharing_mode = (
        "community_battery" if cr.battery_charge.abs().sum() > 0 else "p2p"
    )

    return CommunityMetrics(
        dt_h=dt_h,
        community_import_kwh=community_import_kwh,
        community_export_kwh=community_export_kwh,
        unshared_import_kwh=unshared_import_kwh,
        unshared_export_kwh=unshared_export_kwh,
        total_demand_kwh=total_demand_kwh,
        self_sufficiency=self_sufficiency,
        import_reduction_kwh=unshared_import_kwh - community_import_kwh,
        export_reduction_kwh=unshared_export_kwh - community_export_kwh,
        battery_charge_kwh=float(cr.battery_charge.sum()) * dt_h,
        battery_discharge_kwh=float(cr.battery_discharge.sum()) * dt_h,
        sharing_mode=sharing_mode,
    )


def generate_community_report(
    community_results: "CommunityResults",
    community_summary: Optional[Mapping[str, Any]] = None,
) -> str:
    """Generate a markdown report for a community energy sharing simulation.

    Mirrors :func:`generate_summary_report` in structure.  All kWh figures are
    derived via :func:`compute_community_metrics` using an index-inferred
    timestep so the report is correct for any series cadence.

    Args:
        community_results: Output of :func:`~solar_challenge.community.simulate_community`.
        community_summary: Optional mapping of extra key/value metadata to
            append as a separate section.

    Returns:
        Formatted markdown report string.
    """
    m = compute_community_metrics(community_results)

    report = f"""# Community Energy Sharing Report

## Sharing Mode
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

    # Community Billing section — only when VNM billing was computed (task ε / #34)
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


def generate_finance_report(
    bill_physics: "BillDistribution",
    bill_spreadsheet: Optional["BillDistribution"] = None,
    *,
    scenario_name: str = "",
    economics: Optional["ProjectEconomics"] = None,
    cost_recovery: Optional["CostRecoverySolution"] = None,
) -> str:
    """Generate a markdown finance report from one or two BillDistributions.

    Renders the representative householder bill line items (standing charge,
    import cost, VAT, gross bill, SEG export income, self-consumption saving,
    net annual bill, saving %) and a per-home distribution table
    (min / mean / median / max).

    When ``bill_spreadsheet`` is provided the report includes side-by-side
    Physics vs Spreadsheet columns (the ``--assumptions both`` surface).
    The δ-owned scaffold; η extends it additively with a project-economics
    block.

    Args:
        bill_physics: BillDistribution from the physics self-consumption path.
        bill_spreadsheet: Optional BillDistribution from the spreadsheet
            (override) path; when supplied both are rendered side by side.
        scenario_name: Optional scenario label for the report title.
        economics: Optional :class:`~solar_challenge.finance.ProjectEconomics`
            from :func:`~solar_challenge.finance.project_economics`; when
            provided, a ``## Project Economics`` block is appended after the
            bill block.  ``None`` (default) reproduces the δ output exactly.
        cost_recovery: Optional :class:`~solar_challenge.finance.CostRecoverySolution`
            from :func:`~solar_challenge.finance.solve_cost_recovery_rate`; when
            provided, a ``## Cost-Recovery Analysis`` block is appended (CR5).
            ``None`` (default) reproduces the existing output exactly.

    Returns:
        A markdown-formatted finance report string.
    """
    title = (
        f"# Finance Report: {scenario_name}"
        if scenario_name
        else "# Finance Report"
    )

    rep = bill_physics.representative

    if bill_spreadsheet is None:
        # ---- Physics-only path (CR3: own-use payment + total outlay; no SEG) --
        report = f"""{title}

## Householder Bill (Physics Assumptions)

| Line Item | Value |
|-----------|-------|
| Standing Charge | £{rep.standing_charge_gbp:.2f} |
| Import Cost | £{rep.import_cost_gbp:.2f} |
| Own-Use Payment | £{rep.own_use_payment_gbp:.2f} |
| VAT | £{rep.vat_gbp:.2f} |
| **Total Outlay** | **£{rep.total_outlay_gbp:.2f}** |
| Self-Consumption Saving | £{rep.self_consumption_saving_gbp:.2f} |
| Baseline Bill (no solar) | £{rep.baseline_bill_gbp:.2f} |
| Saving vs Baseline | £{rep.saving_vs_baseline_gbp:.2f} ({rep.saving_pct:.1f}%) |
| Self-Consumption Fraction | {rep.self_consumption_fraction:.1%} |

## Per-Home Bill Distribution (Total Annual Outlay, £)

| Metric | Value |
|--------|-------|
| Min | £{bill_physics.min_gbp:.2f} |
| Mean | £{bill_physics.mean_gbp:.2f} |
| Median | £{bill_physics.median_gbp:.2f} |
| Max | £{bill_physics.max_gbp:.2f} |
"""
    else:
        # ---- Physics vs Spreadsheet side-by-side (CR3) --------------------
        rep_s = bill_spreadsheet.representative
        report = f"""{title}

## Householder Bill — Physics vs Spreadsheet Assumptions

| Line Item | Physics | Spreadsheet |
|-----------|---------|-------------|
| Standing Charge | £{rep.standing_charge_gbp:.2f} | £{rep_s.standing_charge_gbp:.2f} |
| Import Cost | £{rep.import_cost_gbp:.2f} | £{rep_s.import_cost_gbp:.2f} |
| Own-Use Payment | £{rep.own_use_payment_gbp:.2f} | £{rep_s.own_use_payment_gbp:.2f} |
| VAT | £{rep.vat_gbp:.2f} | £{rep_s.vat_gbp:.2f} |
| **Total Outlay** | **£{rep.total_outlay_gbp:.2f}** | **£{rep_s.total_outlay_gbp:.2f}** |
| Self-Consumption Saving | £{rep.self_consumption_saving_gbp:.2f} | £{rep_s.self_consumption_saving_gbp:.2f} |
| Baseline Bill (no solar) | £{rep.baseline_bill_gbp:.2f} | £{rep_s.baseline_bill_gbp:.2f} |
| Saving vs Baseline | £{rep.saving_vs_baseline_gbp:.2f} ({rep.saving_pct:.1f}%) | £{rep_s.saving_vs_baseline_gbp:.2f} ({rep_s.saving_pct:.1f}%) |
| Self-Consumption Fraction | {rep.self_consumption_fraction:.1%} | {rep_s.self_consumption_fraction:.1%} |

## Per-Home Bill Distribution (Total Annual Outlay, £)

| Metric | Physics | Spreadsheet |
|--------|---------|-------------|
| Min | £{bill_physics.min_gbp:.2f} | £{bill_spreadsheet.min_gbp:.2f} |
| Mean | £{bill_physics.mean_gbp:.2f} | £{bill_spreadsheet.mean_gbp:.2f} |
| Median | £{bill_physics.median_gbp:.2f} | £{bill_spreadsheet.median_gbp:.2f} |
| Max | £{bill_physics.max_gbp:.2f} | £{bill_spreadsheet.max_gbp:.2f} |
"""

    # ---- Optional project-economics block (η) --------------------------------
    if economics is not None:
        import math as _math

        # Format IRR: NaN → "n/a"
        if _math.isnan(economics.equity_irr):
            irr_str = "n/a"
        else:
            irr_str = f"{economics.equity_irr:.1%}"

        # Format payback: None → "—"
        payback_str = (
            "—" if economics.payback_years is None
            else f"{economics.payback_years:.1f} yr"
        )

        # Format min DSCR: inf → "∞"
        if _math.isinf(economics.min_dscr):
            dscr_str = "∞"
        else:
            dscr_str = f"{economics.min_dscr:.2f}×"

        report += f"""
## Project Economics

| Item | Value |
|------|-------|
| Total CapEx | £{economics.total_capex_gbp:,.0f} |
| Grant | £{economics.grant_gbp:,.0f} |
| Debt | £{economics.debt_gbp:,.0f} |
| Equity | £{economics.equity_gbp:,.0f} |
| Annual Debt Service | £{economics.annual_debt_service_gbp:,.0f} |
| Fleet OpEx / yr | £{economics.fleet_opex_gbp:,.0f} |
| Mean Fleet Surplus / yr | £{economics.mean_fleet_surplus_per_year_gbp:,.0f} |
| Net Surplus / home / yr | £{economics.net_surplus_per_home_per_year_gbp:,.0f} |
| Min DSCR (loan years) | {dscr_str} |
| Equity IRR | {irr_str} |
| Payback | {payback_str} |
"""

    # ---- Optional cost-recovery block (CR5) ----------------------------------
    if cost_recovery is not None:
        report += f"""
## Cost-Recovery Analysis

| Item | Value |
|------|-------|
| Solved Own-Use Rate | {cost_recovery.own_use_rate_pence_per_kwh:.2f} p/kWh |
| CBS Net Surplus / home / yr | £{cost_recovery.net_surplus_per_home_per_year_gbp:.2f} |
| Feasible | {"Yes" if cost_recovery.feasible else "No"} |
| Binding | {cost_recovery.binding} |
"""

    return report
