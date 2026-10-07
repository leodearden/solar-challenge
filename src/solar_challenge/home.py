# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single home simulation combining PV, battery, and load."""

import warnings
from collections.abc import Iterator
from dataclasses import MISSING, dataclass, field, fields
from typing import Optional

import pandas as pd

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    DispatchStrategy,
    PeakShavingStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.ev import EVConfig
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou, validate_energy_balance
from solar_challenge.heat_pump import HeatPumpConfig, generate_heat_pump_load, reference_year_lengths
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, interpolate_to_minute_resolution, simulate_pv_output
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import HOURS_PER_MINUTE
from solar_challenge.weather import align_tmy_to_index, get_tmy_data


_YEAR_LENGTHS_IN_HOURS = reference_year_lengths(rows_per_day=24)


@dataclass(frozen=True)
class HomeConfig:
    """Configuration for a single home simulation.

    Attributes:
        pv_config: PV system configuration
        load_config: Load profile configuration
        battery_config: Battery configuration (None for PV-only)
        heat_pump_config: Heat pump configuration (None for no heat pump)
        ev_config: EV configuration (None for no EV)
        location: Geographic location for weather data
        name: Optional identifier for the home
        tariff_config: Tariff configuration (None for no cost tracking)
        dispatch_strategy: Battery dispatch strategy ("greedy" or "tou_optimized")
    """

    pv_config: PVConfig
    load_config: LoadConfig
    battery_config: Optional[BatteryConfig] = None
    heat_pump_config: Optional[HeatPumpConfig] = None
    ev_config: Optional[EVConfig] = None
    location: Location = Location.bristol()
    name: str = ""
    tariff_config: Optional[TariffConfig] = None
    dispatch_strategy: str = "greedy"
    seg_tariff: Optional[SEGTariff] = None
    """Smart Export Guarantee tariff for pricing grid exports.

    When set, simulate_home prices export_revenue using calculate_seg_revenue()
    at this SEG rate (pence/kWh) rather than the import tariff rate.  This is
    the cross-PRD seam field: the web UI (P2) sets it via HomeConfig so the
    simulation automatically uses SEG pricing with no further wiring required.
    """


_COLUMN = "column"
_AMOUNT = "per_minute_amount"


@dataclass(frozen=True)
class _PerMinuteAmount:
    """How a series' sample becomes that minute's amount: the sample times factor, under column."""

    column: str
    factor: float


def _power(column: str, energy_column: str) -> dict[str, object]:
    """Metadata of a kW series written under column; its amount is each minute's kWh, under energy_column."""
    return {_COLUMN: column, _AMOUNT: _PerMinuteAmount(energy_column, HOURS_PER_MINUTE)}


def _money(column: str) -> dict[str, object]:
    """Metadata of a £ series written under column; each sample already is its minute's amount."""
    return {_COLUMN: column, _AMOUNT: _PerMinuteAmount(column, 1.0)}


def _level(column: str) -> dict[str, object]:
    """Metadata of a series written under column that holds a level, which has no amount.

    A state of charge or a rate does not add up over time.
    """
    return {_COLUMN: column}


@dataclass(frozen=True)
class SimulationResults:
    """Comprehensive results from a home simulation.

    All time series have 1-minute resolution and matching DatetimeIndex.
    Each series field's column metadata names the column to_dataframe writes it
    under and from_dataframe reads it from, and each series is named that column,
    whatever it was named when built.

    Attributes:
        generation: PV generation in kW
        demand: Load demand in kW
        self_consumption: Direct PV consumption in kW
        battery_charge: Power into battery in kW
        battery_discharge: Power out of battery in kW
        battery_soc: Battery state of charge in kWh
        grid_import: Power imported from grid in kW
        grid_export: Power exported to grid in kW
        import_cost: Cost of grid import in £
        export_revenue: Revenue from grid export in £
        tariff_rate: Tariff rate in £/kWh
        strategy_name: Name of the dispatch strategy used
        heat_pump_load: Optional heat pump electrical load in kW (None if no heat pump)
    """

    generation: pd.Series = field(metadata=_power("generation_kw", "generation_kwh"))
    demand: pd.Series = field(metadata=_power("demand_kw", "demand_kwh"))
    self_consumption: pd.Series = field(metadata=_power("self_consumption_kw", "self_consumption_kwh"))
    battery_charge: pd.Series = field(metadata=_power("battery_charge_kw", "battery_charge_kwh"))
    battery_discharge: pd.Series = field(metadata=_power("battery_discharge_kw", "battery_discharge_kwh"))
    battery_soc: pd.Series = field(metadata=_level("battery_soc_kwh"))
    grid_import: pd.Series = field(metadata=_power("grid_import_kw", "grid_import_kwh"))
    grid_export: pd.Series = field(metadata=_power("grid_export_kw", "grid_export_kwh"))
    import_cost: pd.Series = field(metadata=_money("import_cost_gbp"))
    export_revenue: pd.Series = field(metadata=_money("export_revenue_gbp"))
    tariff_rate: pd.Series = field(metadata=_level("tariff_rate_per_kwh"))
    strategy_name: str = "self_consumption"
    heat_pump_load: Optional[pd.Series] = field(default=None, metadata=_power("heat_pump_load_kw", "heat_pump_load_kwh"))
    # Per-timestep slice of import_cost spent charging the battery from the grid, in £
    # (None when tariff_config is None).
    grid_charge_cost: Optional[pd.Series] = field(default=None, metadata=_money("grid_charge_cost_gbp"))

    def __post_init__(self) -> None:
        """Name each set series after its column, without renaming the series it was built from."""
        for name, column in self._series_columns():
            series = getattr(self, name)
            if series is not None:
                object.__setattr__(self, name, series.rename(column))

    @classmethod
    def _series_columns(cls) -> Iterator[tuple[str, str]]:
        """Each series field's name and column, in declaration order."""
        for attribute in fields(cls):
            if _COLUMN in attribute.metadata:
                yield attribute.name, attribute.metadata[_COLUMN]

    def _amount_series(self) -> Iterator[tuple[str, pd.Series]]:
        """Each amount's column and its per-minute amounts, in declaration order, for every series that is set."""
        for attribute in fields(self):
            amount = attribute.metadata.get(_AMOUNT)
            series = getattr(self, attribute.name)
            if isinstance(amount, _PerMinuteAmount) and series is not None:
                yield amount.column, series * amount.factor

    def per_minute_amounts(self) -> pd.DataFrame:
        """Each minute's energy in kWh and money in £, one column per amount, so a period's totals are its column sums.

        The battery state of charge and the tariff rate have no column, as neither adds up over
        time, and nor has an optional series that is None.
        """
        return pd.concat(dict(self._amount_series()), axis=1)

    def total_amounts(self) -> dict[str, float]:
        """The run's total of each amount: per_minute_amounts' column sums, keyed by column."""
        return {column: float(amounts.sum()) for column, amounts in self._amount_series()}

    def to_dataframe(self) -> pd.DataFrame:
        """Convert results to a DataFrame with one column per series that is set."""
        return pd.DataFrame(
            {
                column: series
                for name, column in self._series_columns()
                if (series := getattr(self, name)) is not None
            }
        )

    @classmethod
    def from_dataframe(cls, frame: pd.DataFrame, *, strategy_name: str) -> "SimulationResults":
        """Build the results whose to_dataframe() is frame, simulated under strategy_name.

        Optional series whose column is absent are None.

        Raises:
            ValueError: If frame lacks any required series' column; the message names each one.
        """
        required_fields = {
            attribute.name
            for attribute in fields(cls)
            if attribute.default is MISSING and attribute.default_factory is MISSING
        }
        missing_columns = [
            column
            for name, column in cls._series_columns()
            if name in required_fields and column not in frame.columns
        ]
        if missing_columns:
            raise ValueError(f"frame lacks required series columns: {', '.join(missing_columns)}")
        return cls(
            strategy_name=strategy_name,
            **{name: frame[column] for name, column in cls._series_columns() if column in frame.columns},
        )


@dataclass
class SummaryStatistics:
    """Summary statistics for a simulation period.

    All energy values in kWh, all financial values in £.
    """

    total_generation_kwh: float
    total_demand_kwh: float
    total_self_consumption_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_battery_charge_kwh: float
    total_battery_discharge_kwh: float
    peak_generation_kw: float
    peak_demand_kw: float
    self_consumption_ratio: float  # self_consumption / generation
    grid_dependency_ratio: float  # grid_import / demand
    export_ratio: float  # grid_export / generation
    simulation_days: int
    total_import_cost_gbp: float  # total cost of grid imports in £
    total_export_revenue_gbp: float  # total revenue from grid exports in £
    net_cost_gbp: float  # net cost (import - export) in £
    strategy_name: str = "self_consumption"
    seg_revenue_gbp: Optional[float] = None
    total_heat_pump_load_kwh: Optional[float] = None  # total heat pump consumption
    peak_heat_pump_load_kw: Optional[float] = None  # peak heat pump load
    heat_pump_load_ratio: Optional[float] = None  # heat_pump_load / total_demand
    # Slice of total_import_cost_gbp spent charging the battery from the grid: householder
    # import, informational, in no CBS equation (docs/cost-recovery-finance-model.md §4).
    total_grid_charge_cost_gbp: float = 0.0


def _create_dispatch_strategy(config: HomeConfig) -> DispatchStrategy:
    """Create dispatch strategy from battery config.

    Args:
        config: Home configuration with optional battery and dispatch strategy

    Returns:
        DispatchStrategy instance (defaults to SelfConsumptionStrategy if not configured)
    """
    # If no battery or no strategy config, use self-consumption
    if config.battery_config is None or config.battery_config.dispatch_strategy is None:
        return SelfConsumptionStrategy()

    strategy_config = config.battery_config.dispatch_strategy
    strategy_type = strategy_config.strategy_type

    if strategy_type == "self_consumption":
        return SelfConsumptionStrategy()
    elif strategy_type == "tou_optimized":
        if strategy_config.peak_hours is None:
            raise ValueError("TOU strategy requires peak_hours configuration")
        return TOUOptimizedStrategy(peak_hours=strategy_config.peak_hours)
    elif strategy_type == "peak_shaving":
        if strategy_config.import_limit_kw is None:
            raise ValueError("Peak shaving strategy requires import_limit_kw configuration")
        return PeakShavingStrategy(import_limit_kw=strategy_config.import_limit_kw)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")


def simulate_home(
    config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    weather_data: pd.DataFrame | None = None,
) -> SimulationResults:
    """Simulate a single home for a date range.

    Args:
        config: Home configuration with PV, load, and optional battery
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        validate_balance: Whether to validate energy balance each timestep
        weather_data: One TMY year of hourly weather, as get_tmy_data returns;
            fetched for config.location when None. A heat pump's
            annual_heat_demand_kwh is shared out over the heating
            degree-minutes of the air temperature across this whole year,
            so with a heat pump configured the weather must be one year of
            hourly rows, 8760 to 8784 (365 to 366 days).

    Returns:
        SimulationResults with all time series at 1-minute resolution

    Raises:
        ValueError: If a heat pump is configured and weather_data is not one
            year of hourly rows.
    """
    # Get weather data (TMY for now)
    if weather_data is None:
        weather_data = get_tmy_data(config.location)
    if config.heat_pump_config is not None and len(weather_data) not in _YEAR_LENGTHS_IN_HOURS:
        raise ValueError(
            f"weather_data has {len(weather_data):,} rows, not one year of hourly rows "
            f"({_YEAR_LENGTHS_IN_HOURS.start:,} to {_YEAR_LENGTHS_IN_HOURS[-1]:,}): a heat pump's "
            "annual_heat_demand_kwh is shared out over the heating degree-minutes of this whole year, "
            "so pass one TMY year of hourly weather, as get_tmy_data returns."
        )

    # Generate PV output at hourly resolution
    hourly_generation = simulate_pv_output(
        config.pv_config,
        config.location,
        weather_data,
    )

    # Interpolate to 1-minute resolution
    minute_generation = interpolate_to_minute_resolution(hourly_generation)

    # Generate load profile at 1-minute resolution
    minute_demand = generate_load_profile(
        config.load_config,
        start_date,
        end_date,
        timezone=config.location.timezone,
        ev_config=config.ev_config,
    )

    # Generate and add heat pump load if configured
    heat_pump_load_series: Optional[pd.Series] = None
    if config.heat_pump_config is not None:
        hourly_temperature = weather_data["temp_air"]
        minute_temperature = interpolate_to_minute_resolution(hourly_temperature)
        aligned_temperature = align_tmy_to_index(minute_temperature, minute_demand.index)
        heat_pump_load_series = generate_heat_pump_load(
            config.heat_pump_config,
            aligned_temperature,
            annual_temperature_c=minute_temperature,
        )
        minute_demand = minute_demand + heat_pump_load_series

    aligned_generation = align_tmy_to_index(minute_generation, minute_demand.index)

    # Create battery if configured
    battery: Optional[Battery] = None
    if config.battery_config is not None:
        battery = Battery(config.battery_config)

    # Determine dispatch approach:
    # 1. BatteryConfig.dispatch_strategy (Strategy pattern from dispatch.py)
    # 2. HomeConfig.dispatch_strategy == "tou_optimized" with tariff (tariff-based TOU)
    # 3. Default: SelfConsumptionStrategy
    use_tariff_tou = (
        config.dispatch_strategy == "tou_optimized"
        and config.tariff_config is not None
        and (config.battery_config is None or config.battery_config.dispatch_strategy is None)
    )

    strategy: Optional[DispatchStrategy] = None
    strategy_name = "self_consumption"
    if not use_tariff_tou:
        strategy = _create_dispatch_strategy(config)
        strategy_name = strategy.name
    else:
        strategy_name = "tou_optimized"

    # Run timestep simulation
    results_list: list[EnergyFlowResult] = []

    # Get index for timestamp lookup
    index = minute_demand.index

    for timestamp, (gen_kw, dem_kw) in zip(
        index, zip(aligned_generation, minute_demand, strict=True), strict=True
    ):
        if use_tariff_tou:
            result = simulate_timestep_tou(
                generation_kw=float(gen_kw),
                demand_kw=float(dem_kw),
                battery=battery,
                timestamp=timestamp,
                tariff=config.tariff_config,  # type: ignore[arg-type]
                timestep_minutes=1.0,
            )
        else:
            result = simulate_timestep(
                generation_kw=float(gen_kw),
                demand_kw=float(dem_kw),
                battery=battery,
                timestep_minutes=1.0,
                timestamp=timestamp.to_pydatetime(),
                strategy=strategy,
                tariff=config.tariff_config,
            )

        if validate_balance:
            validate_energy_balance(result)

        results_list.append(result)

    minute_kwh_to_kw = 1 / HOURS_PER_MINUTE

    # Calculate tariff costs if tariff is configured
    if config.tariff_config is not None:
        tariff_rates = [config.tariff_config.get_rate(ts) for ts in index]
        import_costs = [r.grid_import * rate for r, rate in zip(results_list, tariff_rates, strict=True)]
        grid_charge_costs: list[float] = [r.grid_charge * rate for r, rate in zip(results_list, tariff_rates, strict=True)]
    else:
        tariff_rates = [0.0 for _ in results_list]
        import_costs = [0.0 for _ in results_list]
        grid_charge_costs = [0.0 for _ in results_list]

    # Calculate export revenue.
    # Grid export is valued at the export/SEG rate, never the import tariff rate.
    # Without a seg_tariff there is no export revenue (zero is the economically correct value).
    if config.seg_tariff is not None:
        export_revenues = [
            calculate_seg_revenue(r.grid_export, config.seg_tariff)
            for r in results_list
        ]
    else:
        if config.tariff_config is not None:
            warnings.warn(
                "tariff_config is set but seg_tariff is None: export_revenue will be 0.0. "
                "Configure HomeConfig.seg_tariff to value grid exports at the SEG/export rate.",
                UserWarning,
                stacklevel=2,
            )
        export_revenues = [0.0 for _ in results_list]

    return SimulationResults(
        strategy_name=strategy_name,
        generation=pd.Series([r.generation * minute_kwh_to_kw for r in results_list], index=index),
        demand=pd.Series([r.demand * minute_kwh_to_kw for r in results_list], index=index),
        self_consumption=pd.Series([r.self_consumption * minute_kwh_to_kw for r in results_list], index=index),
        battery_charge=pd.Series([r.battery_charge * minute_kwh_to_kw for r in results_list], index=index),
        battery_discharge=pd.Series([r.battery_discharge * minute_kwh_to_kw for r in results_list], index=index),
        battery_soc=pd.Series([r.battery_soc for r in results_list], index=index),
        grid_import=pd.Series([r.grid_import * minute_kwh_to_kw for r in results_list], index=index),
        grid_export=pd.Series([r.grid_export * minute_kwh_to_kw for r in results_list], index=index),
        import_cost=pd.Series(import_costs, index=index),
        export_revenue=pd.Series(export_revenues, index=index),
        tariff_rate=pd.Series(tariff_rates, index=index),
        heat_pump_load=heat_pump_load_series,
        grid_charge_cost=pd.Series(grid_charge_costs, index=index) if config.tariff_config is not None else None,
    )


def calculate_summary(
    results: SimulationResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> SummaryStatistics:
    """Calculate summary statistics from simulation results.

    Args:
        results: Simulation results with time series
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, ``seg_revenue_gbp`` is computed from total grid export
            via ``calculate_seg_revenue``.  Must be >= 0; negative values raise
            ``ValueError`` (enforced by ``SEGTariff`` validation — a behaviour
            change from the previous inline formula that silently returned a
            negative number).

    Returns:
        SummaryStatistics with totals and ratios

    Notes:
        **Two-path SEG design** — ``total_export_revenue_gbp`` and
        ``seg_revenue_gbp`` are independent figures that can legitimately differ:

        * ``total_export_revenue_gbp`` is always ``results.export_revenue.sum()``.
          When ``simulate_home`` was called with ``HomeConfig.seg_tariff`` set,
          every export timestep was already priced at that SEG rate, so
          ``total_export_revenue_gbp`` already reflects SEG pricing and is the
          authoritative revenue figure for that simulation.

        * ``seg_revenue_gbp`` is an *additional*, independent recalculation
          driven by ``seg_tariff_pence_per_kwh``.  This path exists for callers
          (``fleet.py``, ``output.py``) that build ``SimulationResults`` by hand
          and need a standalone SEG revenue figure without access to a
          ``HomeConfig``.

        **Recommended usage when** ``HomeConfig.seg_tariff`` **was set:**
        read ``total_export_revenue_gbp`` for the authoritative revenue and do
        *not* pass ``seg_tariff_pence_per_kwh`` — or pass the same rate as a
        consistency cross-check.  Passing a *different* rate will produce
        ``seg_revenue_gbp != total_export_revenue_gbp``, which is not an error
        but may mislead callers that compare the two.
    """
    totals = results.total_amounts()
    total_gen = totals["generation_kwh"]
    total_demand = totals["demand_kwh"]
    total_self = totals["self_consumption_kwh"]
    total_import = totals["grid_import_kwh"]
    total_export = totals["grid_export_kwh"]
    total_charge = totals["battery_charge_kwh"]
    total_discharge = totals["battery_discharge_kwh"]

    peak_gen = float(results.generation.max())
    peak_demand = float(results.demand.max())

    # Calculate financial totals
    total_import_cost = totals["import_cost_gbp"]
    total_export_revenue = totals["export_revenue_gbp"]
    net_cost = total_import_cost - total_export_revenue

    # Calculate ratios with zero-division protection
    self_consumption_ratio = total_self / total_gen if total_gen > 0 else 0.0
    grid_dependency_ratio = total_import / total_demand if total_demand > 0 else 0.0
    export_ratio = total_export / total_gen if total_gen > 0 else 0.0

    # Calculate simulation duration
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1

    # Calculate SEG revenue if tariff is provided.
    # Routed through SEGTariff + calculate_seg_revenue — single source of SEG math.
    # SEGTariff validates rate >= 0; negative values raise ValueError here.
    seg_revenue_gbp: Optional[float] = None
    if seg_tariff_pence_per_kwh is not None:
        seg_revenue_gbp = calculate_seg_revenue(
            total_export,
            SEGTariff(name="", rate_pence_per_kwh=seg_tariff_pence_per_kwh),
        )

    # Grid-charge cost: the slice of total_import_cost spent charging the battery from the grid
    total_grid_charge_cost = totals["grid_charge_cost_gbp"] if results.grid_charge_cost is not None else 0.0

    # Calculate heat pump metrics if heat pump load is present
    total_heat_pump_kwh: Optional[float] = None
    peak_heat_pump_kw: Optional[float] = None
    heat_pump_ratio: Optional[float] = None
    if results.heat_pump_load is not None:
        total_heat_pump_kwh = totals["heat_pump_load_kwh"]
        peak_heat_pump_kw = float(results.heat_pump_load.max())
        heat_pump_ratio = total_heat_pump_kwh / total_demand if total_demand > 0 else 0.0

    return SummaryStatistics(
        total_generation_kwh=total_gen,
        total_demand_kwh=total_demand,
        total_self_consumption_kwh=total_self,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_battery_charge_kwh=total_charge,
        total_battery_discharge_kwh=total_discharge,
        peak_generation_kw=peak_gen,
        peak_demand_kw=peak_demand,
        self_consumption_ratio=self_consumption_ratio,
        grid_dependency_ratio=grid_dependency_ratio,
        export_ratio=export_ratio,
        simulation_days=sim_days,
        total_import_cost_gbp=total_import_cost,
        total_export_revenue_gbp=total_export_revenue,
        net_cost_gbp=net_cost,
        strategy_name=results.strategy_name,
        seg_revenue_gbp=seg_revenue_gbp,
        total_heat_pump_load_kwh=total_heat_pump_kwh,
        peak_heat_pump_load_kw=peak_heat_pump_kw,
        heat_pump_load_ratio=heat_pump_ratio,
        total_grid_charge_cost_gbp=total_grid_charge_cost,
    )
