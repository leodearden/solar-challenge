# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet simulation for multiple homes."""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional, Sequence

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    SummaryStatistics,
    calculate_summary,
    grid_dependency_ratio,
    self_consumption_ratio,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import PrefetchedWeather, default_weather


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
            raise ConfigurationError("Fleet must have at least one home")

        # Validate all homes have compatible timezones
        timezones = {h.location.timezone for h in self.homes}
        if len(timezones) > 1:
            raise ConfigurationError(
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
            raise ConfigurationError("All configuration lists must have the same length")

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
    """Results from a fleet simulation of at least one home, each home's SimulationResults paired with its HomeConfig.

    Attributes:
        per_home_results: List of SimulationResults for each home
        home_configs: The HomeConfig of each home, in per_home_results' order
    """

    per_home_results: list[SimulationResults]
    home_configs: list[HomeConfig]

    def __post_init__(self) -> None:
        """Enforce _require_paired_homes at construction."""
        self._require_paired_homes()

    def _require_paired_homes(self) -> None:
        """Raise ValueError unless the fleet has at least one home and one HomeConfig per home's results."""
        if not self.per_home_results:
            raise ValueError("FleetResults must have at least one home: per_home_results is empty")
        if len(self.home_configs) != len(self.per_home_results):
            raise ValueError(
                "FleetResults pairs one HomeConfig with each home's results: "
                f"got {len(self.per_home_results)} per_home_results and {len(self.home_configs)} home_configs"
            )

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
            Sum of the series across all homes, named as each home's series is: its
            SimulationResults column, which to_aggregate_dataframe relies on

        Raises:
            ValueError: If the fleet has no homes, or home_configs does not hold one
                HomeConfig per home's results
        """
        self._require_paired_homes()
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
        """The fleet's total generation, demand, self-consumption, grid import and grid export, each under the column SimulationResults.to_dataframe writes that series under."""
        return pd.concat(
            [
                self.total_generation,
                self.total_demand,
                self.total_self_consumption,
                self.total_grid_import,
                self.total_grid_export,
            ],
            axis=1,
        )


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
    weather: PrefetchedWeather,
) -> tuple[int, SimulationResults]:
    """Run one home's simulation job, on the PrefetchedWeather it carries, tagged with the home's index. Must be top-level for pickle."""
    results = simulate_home(home_config, start_date, end_date, validate_balance, weather=weather)
    return (home_index, results)


def _simulate_home_worker_tagged(
    sweep_index: int,
    home_index: int,
    home_config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool,
    weather: PrefetchedWeather,
) -> tuple[int, int, SimulationResults]:
    """Run one home's simulation job, on the PrefetchedWeather it carries, tagged with its sweep and home indices.

    Must be top-level for pickle.

    Args:
        sweep_index: Index of the sweep iteration this job belongs to
        home_index: Index of the home within the sweep
        home_config: Configuration for the home
        start_date: Start of simulation period
        end_date: End of simulation period
        validate_balance: Whether to validate energy balance
        weather: The job's weather, holding the weather of the home's location alone

    Returns:
        Tuple of (sweep_index, home_index, SimulationResults)
    """
    results = simulate_home(home_config, start_date, end_date, validate_balance, weather=weather)
    return (sweep_index, home_index, results)


def _job_weather(weather: PrefetchedWeather, home: HomeConfig) -> PrefetchedWeather:
    """The weather home's job carries: its location's alone, so a job pickles one frame."""
    return PrefetchedWeather.fetch(weather, [home.location])


def simulate_fleet_iter(
    config: FleetConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    parallel: bool = True,
    max_workers: int | None = None,
) -> Iterator[tuple[int, SimulationResults]]:
    """Yield (home_index, result) as each simulation completes.

    Each home is simulated on its location's weather from default_weather(),
    fetched once per distinct location in the calling process before any home
    runs. Each home's job carries a PrefetchedWeather holding its location's
    weather alone, so a worker reads no weather cache and no network under any
    multiprocessing start method.

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
    weather = PrefetchedWeather.fetch(default_weather(), (home.location for home in config.homes))

    if not parallel or n_homes == 1:
        for idx, home in enumerate(config.homes):
            yield _simulate_home_worker(
                idx,
                home,
                start_date,
                end_date,
                validate_balance,
                _job_weather(weather, home),
            )
    else:
        workers = max_workers or min(n_homes, os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _simulate_home_worker,
                    i,
                    h,
                    start_date,
                    end_date,
                    validate_balance,
                    _job_weather(weather, h),
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

    Each home runs on its location's weather from default_weather(), fetched as
    simulate_fleet_iter fetches it, and carried in its job's PrefetchedWeather.

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


def calculate_home_summaries(
    results: FleetResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> list[SummaryStatistics]:
    """Calculate each home's summary statistics, in per_home_results' order.

    Args:
        results: Fleet simulation results
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, each home's summary has its SEG revenue at that tariff.

    Returns:
        calculate_summary of each home's results, in per_home_results' order

    Raises:
        ValueError: If results has no homes, or its home_configs does not hold one
            HomeConfig per home's results
    """
    results._require_paired_homes()
    return [
        calculate_summary(r, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh)
        for r in results.per_home_results
    ]


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

    Raises:
        ValueError: If results has no homes, or its home_configs does not hold one
            HomeConfig per home's results
    """
    return aggregate_home_summaries(calculate_home_summaries(results, seg_tariff_pence_per_kwh))


def aggregate_home_summaries(home_summaries: Sequence[SummaryStatistics]) -> FleetSummary:
    """Aggregate the summary statistics of a fleet's homes into the fleet's.

    The fleet's SEG revenue total and per-home mean are taken over the homes whose
    summary has a seg_revenue_gbp, and both are None when no home's summary has one.

    Args:
        home_summaries: The summary statistics of each home in the fleet

    Returns:
        FleetSummary of a fleet whose homes have these summaries

    Raises:
        ValueError: If home_summaries is empty
    """
    if not home_summaries:
        raise ValueError("A fleet summary aggregates at least one home's summary: home_summaries is empty")

    # Fleet totals
    total_gen = sum(s.total_generation_kwh for s in home_summaries)
    total_demand = sum(s.total_demand_kwh for s in home_summaries)
    total_self = sum(s.total_self_consumption_kwh for s in home_summaries)
    total_import = sum(s.total_grid_import_kwh for s in home_summaries)
    total_export = sum(s.total_grid_export_kwh for s in home_summaries)

    # Per-home generation distribution
    gen_values = [s.total_generation_kwh for s in home_summaries]
    gen_series = pd.Series(gen_values)

    # Per-home self-consumption ratio distribution
    sc_ratios = [s.self_consumption_ratio for s in home_summaries]
    sc_series = pd.Series(sc_ratios)

    # Aggregate SEG revenue over the homes whose summary has one
    total_seg_revenue_gbp: Optional[float] = None
    per_home_seg_revenue_mean_gbp: Optional[float] = None
    seg_revenues = [
        s.seg_revenue_gbp for s in home_summaries if s.seg_revenue_gbp is not None
    ]
    if seg_revenues:
        total_seg_revenue_gbp = sum(seg_revenues)
        per_home_seg_revenue_mean_gbp = total_seg_revenue_gbp / len(seg_revenues)

    # Fleet financial aggregates
    total_import_cost = sum(s.total_import_cost_gbp for s in home_summaries)
    total_export_revenue = sum(s.total_export_revenue_gbp for s in home_summaries)
    total_net_cost = sum(s.net_cost_gbp for s in home_summaries)

    return FleetSummary(
        n_homes=len(home_summaries),
        total_generation_kwh=total_gen,
        total_demand_kwh=total_demand,
        total_self_consumption_kwh=total_self,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        fleet_self_consumption_ratio=self_consumption_ratio(self_consumption_kwh=total_self, generation_kwh=total_gen),
        fleet_grid_dependency_ratio=grid_dependency_ratio(grid_import_kwh=total_import, demand_kwh=total_demand),
        per_home_generation_min_kwh=float(gen_series.min()),
        per_home_generation_max_kwh=float(gen_series.max()),
        per_home_generation_mean_kwh=float(gen_series.mean()),
        per_home_generation_median_kwh=float(gen_series.median()),
        per_home_self_consumption_ratio_min=float(sc_series.min()),
        per_home_self_consumption_ratio_max=float(sc_series.max()),
        per_home_self_consumption_ratio_mean=float(sc_series.mean()),
        simulation_days=home_summaries[0].simulation_days,
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

    Weather is fetched from default_weather() as simulate_fleet_iter fetches it, over
    every sweep's homes, and each job carries its home's PrefetchedWeather.

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

    weather = PrefetchedWeather.fetch(
        default_weather(), (home.location for _, fleet_config in sweep_configs for home in fleet_config.homes)
    )

    # Count total jobs
    total_jobs = sum(len(cfg.homes) for _, cfg in sweep_configs)

    if not parallel or total_jobs == 1:
        # Sequential execution
        for sweep_idx, (_, fleet_config) in enumerate(sweep_configs):
            for home_idx, home in enumerate(fleet_config.homes):
                yield _simulate_home_worker_tagged(
                    sweep_idx,
                    home_idx,
                    home,
                    start_date,
                    end_date,
                    validate_balance,
                    _job_weather(weather, home),
                )
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
                        _job_weather(weather, home),
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
