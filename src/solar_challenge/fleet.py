# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet simulation for multiple homes."""

import contextlib
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Generator, Iterator, Optional, Protocol, Sequence, TypeAlias

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
from solar_challenge.number_fields import Interval, as_whole_number, read_field
from solar_challenge.pv import PVConfig
from solar_challenge.weather import PrefetchedWeather, WeatherProvider, default_weather


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


FleetSimulate: TypeAlias = Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]
"""Simulates a fleet over a window: what finance and optimize take, a FleetSimulator's simulate."""

HomesDone: TypeAlias = Callable[[int, int], None]
"""Told in the calling process after each home finishes: (homes finished, homes in the call)."""


class HomeSimulator(Protocol):
    """Simulates one home over a window on the weather it is given, as home.simulate_home does."""

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults: ...


class FleetSimulator(Protocol):
    """How a composition root simulates homes and fleets."""

    def simulate(
        self, fleet: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, progress: HomesDone | None = None
    ) -> FleetResults: ...

    def simulate_each(
        self,
        fleets: Sequence[FleetConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        *,
        progress: HomesDone | None = None,
    ) -> Iterator[tuple[int, FleetResults]]:
        """Each fleet's index once, with its FleetResults, as its last home finishes."""
        ...

    def simulate_home(self, home: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults: ...


_WORKER_COUNTS = Interval(1, math.inf)


@dataclass(frozen=True)
class FleetRunner:
    """A FleetSimulator that runs each home through home_simulator on the weather it prefetches from weather.

    Attributes:
        weather: Asked once per call for each distinct location of the call's homes, in the calling process
        home_simulator: Simulates each home; a pool pickles it into each job, so when parallel it is a top-level function
        parallel: Whether a call of two or more homes runs them in a process pool rather than in turn in the calling process
        max_workers: The pool's worker count, a whole number of at least 1; None is min(homes in the call, os.cpu_count() or 4)
    """

    weather: WeatherProvider
    home_simulator: HomeSimulator
    parallel: bool = True
    max_workers: int | None = None

    def __post_init__(self) -> None:
        """Read a set max_workers as a whole number of at least 1, holding the int read, else a ConfigurationError (a ValueError) naming it and its value; None stays None."""
        read_field(self, "max_workers", as_whole_number, _WORKER_COUNTS, optional=True)

    def simulate(
        self, fleet: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, progress: HomesDone | None = None
    ) -> FleetResults:
        """fleet simulated from start_date to end_date: simulate_each of fleet alone."""
        ((_, results),) = self.simulate_each([fleet], start_date, end_date, progress=progress)
        return results

    def simulate_each(
        self,
        fleets: Sequence[FleetConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        *,
        progress: HomesDone | None = None,
    ) -> Iterator[tuple[int, FleetResults]]:
        """Each fleet's index once, with its FleetResults, as its last home finishes; the homes of all the fleets share one pool.

        Each distinct location's weather is fetched once, in this process, before any home runs, and
        each home's job carries its own location's alone. progress, when given, is told in this process
        after each home finishes: (homes finished, homes in the call).

        A home that fails re-raises its own exception, with a note naming the home and its fleet; an
        exception progress raises propagates as raised. Either, or closing the iterator early, cancels
        the homes not yet started, and the call ends once the homes already running have finished.
        """
        return _simulate_fleets(self, fleets, start_date, end_date, progress)

    def simulate_home(self, home: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        """home simulated in this process from start_date to end_date, on weather holding its location's alone."""
        return self.home_simulator(
            home, start_date, end_date, weather=PrefetchedWeather.fetch(self.weather, [home.location])
        )


def default_runner() -> FleetRunner:
    """FleetRunner(weather=default_weather(), home_simulator=simulate_home): the runner a root uses when given none."""
    return FleetRunner(weather=default_weather(), home_simulator=simulate_home)


def _job_weather(weather: PrefetchedWeather, home: HomeConfig) -> PrefetchedWeather:
    """The weather home's job carries: its location's alone, so a job pickles one frame."""
    return PrefetchedWeather.fetch(weather, [home.location])


@dataclass(frozen=True)
class _HomeJob:
    """One home of a runner's call: the home, and the fleet and the place in it its results go to."""

    fleet_index: int
    home_index: int
    fleet: FleetConfig
    home: HomeConfig


def _finished_homes(
    runner: FleetRunner,
    jobs: Sequence[_HomeJob],
    weather: PrefetchedWeather,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Generator[tuple[_HomeJob, SimulationResults], None, None]:
    """Each job with its home's results as the home finishes: in turn in this process, or in one process pool when runner is parallel and there are two jobs or more.

    A pool's job carries runner.home_simulator, the home, the window and the home's weather alone, so the runner and
    its weather provider are never pickled. A home's exception carries a note naming the home. In turn, no later home
    starts once the generator stops; a pool that stops, for whatever exception or when the generator is closed,
    cancels the homes not yet started and waits for those running.
    """
    if not runner.parallel or len(jobs) < 2:
        for job in jobs:
            with _naming_the_home(job):
                results = runner.home_simulator(job.home, start_date, end_date, weather=_job_weather(weather, job.home))
            yield job, results
        return
    workers = min(len(jobs), os.cpu_count() or 4) if runner.max_workers is None else runner.max_workers
    with ProcessPoolExecutor(max_workers=workers) as pool:
        try:
            futures = {
                pool.submit(
                    runner.home_simulator, job.home, start_date, end_date, weather=_job_weather(weather, job.home)
                ): job
                for job in jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                with _naming_the_home(job):
                    results = future.result()
                yield job, results
        except BaseException:
            pool.shutdown(cancel_futures=True)
            raise


@contextlib.contextmanager
def _naming_the_home(job: _HomeJob) -> Iterator[None]:
    """Re-raise an exception the block raises, that same object, with a note naming job's home and fleet."""
    try:
        yield
    except Exception as error:
        error.add_note(
            f"simulating home {job.home_index} ({job.home.name!r}) of fleet {job.fleet_index} ({job.fleet.name!r})"
        )
        raise


def _simulate_fleets(
    runner: FleetRunner,
    fleets: Sequence[FleetConfig],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    progress: HomesDone | None,
) -> Iterator[tuple[int, FleetResults]]:
    """FleetRunner.simulate_each's fan-out: every home of fleets run through _finished_homes on weather fetched once per distinct location, each fleet's results yielded in home order as its last home finishes."""
    jobs = [
        _HomeJob(fleet_index, home_index, fleet, home)
        for fleet_index, fleet in enumerate(fleets)
        for home_index, home in enumerate(fleet.homes)
    ]
    weather = PrefetchedWeather.fetch(runner.weather, (job.home.location for job in jobs))
    finished: dict[int, dict[int, SimulationResults]] = {fleet_index: {} for fleet_index in range(len(fleets))}
    with contextlib.closing(_finished_homes(runner, jobs, weather, start_date, end_date)) as homes:
        for done, (job, results) in enumerate(homes, start=1):
            if progress is not None:
                progress(done, len(jobs))
            fleet_finished = finished[job.fleet_index]
            fleet_finished[job.home_index] = results
            if len(fleet_finished) == len(job.fleet.homes):
                yield job.fleet_index, FleetResults(
                    per_home_results=[fleet_finished[home_index] for home_index in range(len(job.fleet.homes))],
                    home_configs=job.fleet.homes,
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


