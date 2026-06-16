# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet simulation for multiple homes."""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    SummaryStatistics,
    calculate_summary,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import get_tmy_data


@dataclass
class FleetConfig:
    """Configuration for a fleet of homes.

    Attributes:
        homes: List of HomeConfig objects for each home
        name: Optional identifier for the fleet
    """

    homes: list[HomeConfig] = field(default_factory=list)
    name: str = ""

    def __post_init__(self) -> None:
        """Validate fleet configuration."""
        if not self.homes:
            raise ValueError("Fleet must have at least one home")

        # Validate all homes have compatible timezones
        timezones = {h.location.timezone for h in self.homes}
        if len(timezones) > 1:
            raise ValueError(
                f"All homes must have same timezone. Found: {timezones}"
            )

    @classmethod
    def create_uniform(
        cls,
        n_homes: int,
        pv_config: PVConfig,
        load_config: LoadConfig,
        battery_config: Optional[BatteryConfig] = None,
        location: Location = Location.bristol(),
        name: str = "",
    ) -> "FleetConfig":
        """Create a fleet with uniform home configurations.

        Args:
            n_homes: Number of homes in the fleet
            pv_config: PV configuration for all homes
            load_config: Load configuration for all homes
            battery_config: Battery configuration (or None) for all homes
            location: Location for all homes
            name: Fleet name

        Returns:
            FleetConfig with identical home configurations
        """
        homes = [
            HomeConfig(
                pv_config=pv_config,
                load_config=load_config,
                battery_config=battery_config,
                location=location,
                name=f"Home {i+1}",
            )
            for i in range(n_homes)
        ]
        return cls(homes=homes, name=name)

    @classmethod
    def create_heterogeneous(
        cls,
        pv_capacities_kw: list[float],
        battery_capacities_kwh: list[Optional[float]],
        annual_consumptions_kwh: list[float],
        location: Location = Location.bristol(),
        name: str = "",
    ) -> "FleetConfig":
        """Create a fleet with heterogeneous home configurations.

        Args:
            pv_capacities_kw: PV capacity for each home
            battery_capacities_kwh: Battery capacity (or None) for each home
            annual_consumptions_kwh: Annual consumption for each home
            location: Location for all homes
            name: Fleet name

        Returns:
            FleetConfig with varied home configurations
        """
        if not (
            len(pv_capacities_kw)
            == len(battery_capacities_kwh)
            == len(annual_consumptions_kwh)
        ):
            raise ValueError("All configuration lists must have the same length")

        homes = []
        for i, (pv_kw, bat_kwh, load_kwh) in enumerate(
            zip(pv_capacities_kw, battery_capacities_kwh, annual_consumptions_kwh, strict=True)
        ):
            battery_config = (
                BatteryConfig(capacity_kwh=bat_kwh) if bat_kwh is not None else None
            )
            homes.append(
                HomeConfig(
                    pv_config=PVConfig(capacity_kw=pv_kw),
                    load_config=LoadConfig(annual_consumption_kwh=load_kwh),
                    battery_config=battery_config,
                    location=location,
                    name=f"Home {i+1}",
                )
            )

        return cls(homes=homes, name=name)


@dataclass
class FleetResults:
    """Results from a fleet simulation.

    Attributes:
        per_home_results: List of SimulationResults for each home
        home_configs: List of HomeConfig for each home (for reference)
    """

    per_home_results: list[SimulationResults]
    home_configs: list[HomeConfig]

    def __len__(self) -> int:
        """Return number of homes in fleet."""
        return len(self.per_home_results)

    def __getitem__(self, index: int) -> SimulationResults:
        """Get results for a specific home by index."""
        return self.per_home_results[index]

    def get_aggregate_series(self, series_name: str) -> pd.Series:
        """Get aggregate (sum) of a series across all homes.

        Args:
            series_name: Name of the series (e.g., 'generation', 'demand')

        Returns:
            Sum of the series across all homes
        """
        series_list = [getattr(r, series_name) for r in self.per_home_results]
        return sum(series_list[1:], series_list[0])

    @property
    def total_generation(self) -> pd.Series:
        """Total fleet generation (sum across homes)."""
        return self.get_aggregate_series("generation")

    @property
    def total_demand(self) -> pd.Series:
        """Total fleet demand (sum across homes)."""
        return self.get_aggregate_series("demand")

    @property
    def total_grid_import(self) -> pd.Series:
        """Total fleet grid import (sum across homes)."""
        return self.get_aggregate_series("grid_import")

    @property
    def total_grid_export(self) -> pd.Series:
        """Total fleet grid export (sum across homes)."""
        return self.get_aggregate_series("grid_export")

    @property
    def total_self_consumption(self) -> pd.Series:
        """Total fleet self-consumption (sum across homes)."""
        return self.get_aggregate_series("self_consumption")

    def to_aggregate_dataframe(self) -> pd.DataFrame:
        """Get aggregate results as DataFrame."""
        return pd.DataFrame({
            "generation_kw": self.total_generation,
            "demand_kw": self.total_demand,
            "self_consumption_kw": self.total_self_consumption,
            "grid_import_kw": self.total_grid_import,
            "grid_export_kw": self.total_grid_export,
        })


@dataclass
class FleetSummary:
    """Summary statistics for fleet simulation.

    All energy values in kWh.
    """

    n_homes: int
    total_generation_kwh: float
    total_demand_kwh: float
    total_self_consumption_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    fleet_self_consumption_ratio: float
    fleet_grid_dependency_ratio: float

    # Distribution stats across homes
    per_home_generation_min_kwh: float
    per_home_generation_max_kwh: float
    per_home_generation_mean_kwh: float
    per_home_generation_median_kwh: float

    per_home_self_consumption_ratio_min: float
    per_home_self_consumption_ratio_max: float
    per_home_self_consumption_ratio_mean: float

    simulation_days: int

    # SEG revenue aggregates (populated when seg_tariff_pence_per_kwh is provided)
    total_seg_revenue_gbp: Optional[float] = None
    per_home_seg_revenue_mean_gbp: Optional[float] = None

    # Financial aggregates (always populated on computed path, None on direct construction)
    total_net_cost_gbp: Optional[float] = None
    total_import_cost_gbp: Optional[float] = None
    total_export_revenue_gbp: Optional[float] = None


def _simulate_home_worker(
    home_index: int,
    home_config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool,
) -> tuple[int, SimulationResults]:
    """Worker for parallel execution. Must be top-level for pickle."""
    results = simulate_home(home_config, start_date, end_date, validate_balance)
    return (home_index, results)


def _simulate_home_worker_tagged(
    sweep_index: int,
    home_index: int,
    home_config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool,
) -> tuple[int, int, SimulationResults]:
    """Worker with sweep tagging for cross-sweep parallel execution.

    Must be top-level for pickle.

    Args:
        sweep_index: Index of the sweep iteration this job belongs to
        home_index: Index of the home within the sweep
        home_config: Configuration for the home
        start_date: Start of simulation period
        end_date: End of simulation period
        validate_balance: Whether to validate energy balance

    Returns:
        Tuple of (sweep_index, home_index, SimulationResults)
    """
    results = simulate_home(home_config, start_date, end_date, validate_balance)
    return (sweep_index, home_index, results)


def simulate_fleet_iter(
    config: FleetConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    parallel: bool = True,
    max_workers: int | None = None,
) -> Iterator[tuple[int, SimulationResults]]:
    """Yield (home_index, result) as each simulation completes.

    Args:
        config: Fleet configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        validate_balance: Whether to validate energy balance
        parallel: Whether to run simulations in parallel
        max_workers: Maximum number of parallel workers (defaults to CPU count)

    Yields:
        Tuples of (home_index, SimulationResults) as each completes
    """
    n_homes = len(config.homes)

    # Pre-warm weather cache
    get_tmy_data(config.homes[0].location, use_cache=True)

    if not parallel or n_homes == 1:
        for idx, home in enumerate(config.homes):
            yield (idx, simulate_home(home, start_date, end_date, validate_balance))
    else:
        workers = max_workers or min(n_homes, os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _simulate_home_worker, i, h, start_date, end_date, validate_balance
                ): i
                for i, h in enumerate(config.homes)
            }
            for future in as_completed(futures):
                yield future.result()


def simulate_fleet(
    config: FleetConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    parallel: bool = True,
    max_workers: int | None = None,
) -> FleetResults:
    """Simulate all homes in a fleet for a date range.

    Weather data is retrieved once and shared across all homes
    (assumes same location).

    Args:
        config: Fleet configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        validate_balance: Whether to validate energy balance
        parallel: Whether to run simulations in parallel
        max_workers: Maximum number of parallel workers (defaults to CPU count)

    Returns:
        FleetResults with per-home results
    """
    results: list[SimulationResults | None] = [None] * len(config.homes)

    for idx, result in simulate_fleet_iter(
        config, start_date, end_date, validate_balance, parallel, max_workers
    ):
        results[idx] = result

    # Convert to non-optional list (all positions filled)
    final_results: list[SimulationResults] = []
    for r in results:
        assert r is not None
        final_results.append(r)

    return FleetResults(
        per_home_results=final_results,
        home_configs=config.homes,
    )


def calculate_fleet_summary(
    results: FleetResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> FleetSummary:
    """Calculate summary statistics for fleet simulation.

    Args:
        results: Fleet simulation results
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, SEG revenue is aggregated across all homes.

    Returns:
        FleetSummary with totals and distribution statistics
    """
    # Calculate per-home summaries
    home_summaries: list[SummaryStatistics] = [
        calculate_summary(r, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh)
        for r in results.per_home_results
    ]

    # Fleet totals
    total_gen = sum(s.total_generation_kwh for s in home_summaries)
    total_demand = sum(s.total_demand_kwh for s in home_summaries)
    total_self = sum(s.total_self_consumption_kwh for s in home_summaries)
    total_import = sum(s.total_grid_import_kwh for s in home_summaries)
    total_export = sum(s.total_grid_export_kwh for s in home_summaries)

    # Fleet ratios
    fleet_self_ratio = total_self / total_gen if total_gen > 0 else 0.0
    fleet_grid_dep = total_import / total_demand if total_demand > 0 else 0.0

    # Per-home generation distribution
    gen_values = [s.total_generation_kwh for s in home_summaries]
    gen_series = pd.Series(gen_values)

    # Per-home self-consumption ratio distribution
    sc_ratios = [s.self_consumption_ratio for s in home_summaries]
    sc_series = pd.Series(sc_ratios)

    # Aggregate SEG revenue if tariff was provided
    total_seg_revenue_gbp: Optional[float] = None
    per_home_seg_revenue_mean_gbp: Optional[float] = None
    if seg_tariff_pence_per_kwh is not None:
        seg_revenues = [
            s.seg_revenue_gbp for s in home_summaries if s.seg_revenue_gbp is not None
        ]
        if seg_revenues:
            total_seg_revenue_gbp = sum(seg_revenues)
            per_home_seg_revenue_mean_gbp = total_seg_revenue_gbp / len(seg_revenues)

    # Fleet financial aggregates (per-home fields are always-present floats).
    # float() ensures the result is 0.0 (float), not 0 (int), when home_summaries is
    # empty — Python's sum() of an empty generator returns int 0 by default.
    total_import_cost = float(sum(s.total_import_cost_gbp for s in home_summaries))
    total_export_revenue = float(sum(s.total_export_revenue_gbp for s in home_summaries))
    total_net_cost = float(sum(s.net_cost_gbp for s in home_summaries))

    return FleetSummary(
        n_homes=len(results),
        total_generation_kwh=total_gen,
        total_demand_kwh=total_demand,
        total_self_consumption_kwh=total_self,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        fleet_self_consumption_ratio=fleet_self_ratio,
        fleet_grid_dependency_ratio=fleet_grid_dep,
        per_home_generation_min_kwh=float(gen_series.min()),
        per_home_generation_max_kwh=float(gen_series.max()),
        per_home_generation_mean_kwh=float(gen_series.mean()),
        per_home_generation_median_kwh=float(gen_series.median()),
        per_home_self_consumption_ratio_min=float(sc_series.min()),
        per_home_self_consumption_ratio_max=float(sc_series.max()),
        per_home_self_consumption_ratio_mean=float(sc_series.mean()),
        simulation_days=home_summaries[0].simulation_days if home_summaries else 0,
        total_seg_revenue_gbp=total_seg_revenue_gbp,
        per_home_seg_revenue_mean_gbp=per_home_seg_revenue_mean_gbp,
        total_net_cost_gbp=total_net_cost,
        total_import_cost_gbp=total_import_cost,
        total_export_revenue_gbp=total_export_revenue,
    )


def simulate_multi_sweep_iter(
    sweep_configs: list[tuple[Any, FleetConfig]],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    parallel: bool = True,
    max_workers: int | None = None,
) -> Iterator[tuple[int, int, SimulationResults]]:
    """Submit all jobs from all sweeps to a single executor for maximum CPU utilization.

    This function enables cross-sweep parallel execution: when sweep N's last batch
    has only a few jobs, sweep N+1's jobs fill the remaining worker slots.

    Args:
        sweep_configs: List of (sweep_value, FleetConfig) pairs
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        validate_balance: Whether to validate energy balance
        parallel: Whether to run simulations in parallel
        max_workers: Maximum number of parallel workers (defaults to CPU count)

    Yields:
        Tuples of (sweep_index, home_index, SimulationResults) as each completes
    """
    if not sweep_configs:
        return

    # Pre-warm weather cache using first home from first sweep
    get_tmy_data(sweep_configs[0][1].homes[0].location, use_cache=True)

    # Count total jobs
    total_jobs = sum(len(cfg.homes) for _, cfg in sweep_configs)

    if not parallel or total_jobs == 1:
        # Sequential execution
        for sweep_idx, (_, fleet_config) in enumerate(sweep_configs):
            for home_idx, home in enumerate(fleet_config.homes):
                result = simulate_home(home, start_date, end_date, validate_balance)
                yield (sweep_idx, home_idx, result)
    else:
        # Parallel execution with all jobs in single pool
        workers = max_workers or min(total_jobs, os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for sweep_idx, (_, fleet_config) in enumerate(sweep_configs):
                for home_idx, home in enumerate(fleet_config.homes):
                    future = executor.submit(
                        _simulate_home_worker_tagged,
                        sweep_idx,
                        home_idx,
                        home,
                        start_date,
                        end_date,
                        validate_balance,
                    )
                    futures[future] = (sweep_idx, home_idx)

            for future in as_completed(futures):
                yield future.result()


@dataclass
class MultiSweepResults:
    """Results from multi-sweep simulation organized by sweep index.

    Attributes:
        sweep_results: Dict mapping sweep_index to (sweep_value, FleetResults)
        sweep_values: List of sweep values in order
    """

    sweep_results: dict[int, tuple[Any, FleetResults]]
    sweep_values: list[Any]

    def __len__(self) -> int:
        """Return number of sweeps."""
        return len(self.sweep_results)

    def __getitem__(self, sweep_index: int) -> tuple[Any, FleetResults]:
        """Get (sweep_value, FleetResults) for a specific sweep."""
        return self.sweep_results[sweep_index]

    def iter_results(self) -> Iterator[tuple[Any, FleetResults]]:
        """Iterate over (sweep_value, FleetResults) in sweep order."""
        for i in range(len(self.sweep_values)):
            yield self.sweep_results[i]


def collect_multi_sweep_results(
    sweep_configs: list[tuple[Any, FleetConfig]],
    result_iter: Iterator[tuple[int, int, SimulationResults]],
    on_sweep_complete: Optional[Callable[[int, Any, FleetResults], None]] = None,
) -> MultiSweepResults:
    """Collect results from multi-sweep iterator and organize by sweep.

    Routes results to per-sweep buckets and calls callback when each sweep completes.

    Args:
        sweep_configs: List of (sweep_value, FleetConfig) pairs (same as passed to
            simulate_multi_sweep_iter)
        result_iter: Iterator from simulate_multi_sweep_iter
        on_sweep_complete: Optional callback called when a sweep completes.
            Receives (sweep_index, sweep_value, FleetResults).

    Returns:
        MultiSweepResults with organized results
    """
    n_sweeps = len(sweep_configs)

    # Initialize per-sweep result buckets
    # bucket[sweep_idx] = list of (home_idx, result) tuples
    buckets: list[list[tuple[int, SimulationResults]]] = [[] for _ in range(n_sweeps)]
    homes_per_sweep = [len(cfg.homes) for _, cfg in sweep_configs]
    completed_sweeps: set[int] = set()

    # Collect results
    sweep_results: dict[int, tuple[Any, FleetResults]] = {}
    sweep_values = [val for val, _ in sweep_configs]

    for sweep_idx, home_idx, result in result_iter:
        buckets[sweep_idx].append((home_idx, result))

        # Check if this sweep is now complete
        if sweep_idx not in completed_sweeps and len(buckets[sweep_idx]) == homes_per_sweep[sweep_idx]:
            completed_sweeps.add(sweep_idx)

            # Build FleetResults for this sweep
            sweep_val, fleet_config = sweep_configs[sweep_idx]
            bucket = buckets[sweep_idx]

            # Sort by home_idx and extract results
            bucket.sort(key=lambda x: x[0])
            per_home_results = [r for _, r in bucket]

            fleet_results = FleetResults(
                per_home_results=per_home_results,
                home_configs=fleet_config.homes,
            )

            sweep_results[sweep_idx] = (sweep_val, fleet_results)

            # Call callback if provided
            if on_sweep_complete is not None:
                on_sweep_complete(sweep_idx, sweep_val, fleet_results)

    return MultiSweepResults(
        sweep_results=sweep_results,
        sweep_values=sweep_values,
    )
