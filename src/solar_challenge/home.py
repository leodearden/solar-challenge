"""Single home simulation combining PV, battery, and load."""

from dataclasses import dataclass
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
from solar_challenge.heat_pump import HeatPumpConfig, generate_heat_pump_load
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, interpolate_to_minute_resolution, simulate_pv_output
from solar_challenge.tariff import TariffConfig
from solar_challenge.weather import get_tmy_data


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


@dataclass
class SimulationResults:
    """Comprehensive results from a home simulation.

    All time series have 1-minute resolution and matching DatetimeIndex.

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

    generation: pd.Series
    demand: pd.Series
    self_consumption: pd.Series
    battery_charge: pd.Series
    battery_discharge: pd.Series
    battery_soc: pd.Series
    grid_import: pd.Series
    grid_export: pd.Series
    import_cost: pd.Series
    export_revenue: pd.Series
    tariff_rate: pd.Series
    strategy_name: str = "self_consumption"
    heat_pump_load: Optional[pd.Series] = None

    def to_dataframe(self) -> pd.DataFrame:
        """Convert results to DataFrame.

        Returns:
            DataFrame with all time series as columns
        """
        data = {
            "generation_kw": self.generation,
            "demand_kw": self.demand,
            "self_consumption_kw": self.self_consumption,
            "battery_charge_kw": self.battery_charge,
            "battery_discharge_kw": self.battery_discharge,
            "battery_soc_kwh": self.battery_soc,
            "grid_import_kw": self.grid_import,
            "grid_export_kw": self.grid_export,
            "import_cost_gbp": self.import_cost,
            "export_revenue_gbp": self.export_revenue,
            "tariff_rate_per_kwh": self.tariff_rate,
        }

        # Include heat pump load if present
        if self.heat_pump_load is not None:
            data["heat_pump_load_kw"] = self.heat_pump_load

        return pd.DataFrame(data)


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
        weather_data: Pre-fetched weather data (optional, will fetch if None)

    Returns:
        SimulationResults with all time series at 1-minute resolution
    """
    # Get weather data (TMY for now)
    if weather_data is None:
        weather_data = get_tmy_data(config.location)

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
        # Extract temperature from weather data
        hourly_temperature = weather_data["temp_air"]

        # Interpolate to 1-minute resolution
        minute_temperature = interpolate_to_minute_resolution(hourly_temperature)

        # Align temperature to demand index (same as generation alignment)
        aligned_temperature = _align_tmy_to_demand(minute_temperature, minute_demand)

        # Ensure temperature has timezone info matching demand
        if aligned_temperature.index.tz is None and minute_demand.index.tz is not None:
            aligned_temperature.index = aligned_temperature.index.tz_localize(minute_demand.index.tz)
        elif aligned_temperature.index.tz != minute_demand.index.tz:
            aligned_temperature.index = aligned_temperature.index.tz_convert(minute_demand.index.tz)

        # Generate heat pump electrical load
        heat_pump_load_series = generate_heat_pump_load(
            config.heat_pump_config,
            aligned_temperature,
        )

        # Add heat pump load to household demand
        minute_demand = minute_demand + heat_pump_load_series

    # Align generation to demand index (TMY data may have different dates)
    # TMY data uses a synthetic year, so we map by time-of-year
    aligned_generation = _align_tmy_to_demand(minute_generation, minute_demand)

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
            )

        if validate_balance:
            validate_energy_balance(result)

        results_list.append(result)

    # Convert energy (kWh) back to power (kW) for 1-minute timesteps
    # Energy in kWh for 1 minute = Power in kW * (1/60) hours
    # So Power in kW = Energy in kWh * 60
    conversion_factor = 60.0

    # Calculate tariff costs if tariff is configured
    if config.tariff_config is not None:
        tariff_rates = [config.tariff_config.get_rate(ts) for ts in index]
        import_costs = [r.grid_import * rate for r, rate in zip(results_list, tariff_rates, strict=True)]
        # Export revenue: use same rate as import for now (can be enhanced with separate export tariff)
        export_revenues = [r.grid_export * rate for r, rate in zip(results_list, tariff_rates, strict=True)]
    else:
        tariff_rates = [0.0 for _ in results_list]
        import_costs = [0.0 for _ in results_list]
        export_revenues = [0.0 for _ in results_list]

    return SimulationResults(
        strategy_name=strategy_name,
        generation=pd.Series(
            [r.generation * conversion_factor for r in results_list],
            index=index,
            name="generation_kw",
        ),
        demand=pd.Series(
            [r.demand * conversion_factor for r in results_list],
            index=index,
            name="demand_kw",
        ),
        self_consumption=pd.Series(
            [r.self_consumption * conversion_factor for r in results_list],
            index=index,
            name="self_consumption_kw",
        ),
        battery_charge=pd.Series(
            [r.battery_charge * conversion_factor for r in results_list],
            index=index,
            name="battery_charge_kw",
        ),
        battery_discharge=pd.Series(
            [r.battery_discharge * conversion_factor for r in results_list],
            index=index,
            name="battery_discharge_kw",
        ),
        battery_soc=pd.Series(
            [r.battery_soc for r in results_list],
            index=index,
            name="battery_soc_kwh",
        ),
        grid_import=pd.Series(
            [r.grid_import * conversion_factor for r in results_list],
            index=index,
            name="grid_import_kw",
        ),
        grid_export=pd.Series(
            [r.grid_export * conversion_factor for r in results_list],
            index=index,
            name="grid_export_kw",
        ),
        import_cost=pd.Series(
            import_costs,
            index=index,
            name="import_cost_gbp",
        ),
        export_revenue=pd.Series(
            export_revenues,
            index=index,
            name="export_revenue_gbp",
        ),
        tariff_rate=pd.Series(
            tariff_rates,
            index=index,
            name="tariff_rate_per_kwh",
        ),
        heat_pump_load=heat_pump_load_series,
    )


def _align_tmy_to_demand(
    tmy_generation: pd.Series,
    demand: pd.Series,
) -> pd.Series:
    """Align TMY generation data to demand index by time-of-year.

    TMY data has a synthetic year (often 2024 or similar), but we need
    to map it to the actual simulation dates. We do this by matching
    month-day-hour-minute.

    Args:
        tmy_generation: Generation series with TMY dates
        demand: Demand series with actual simulation dates

    Returns:
        Generation series reindexed to match demand index
    """
    # Create a time-of-year key for TMY data (month, day, hour, minute)
    tmy_keys = tmy_generation.index.strftime("%m-%d %H:%M")
    tmy_lookup = dict(zip(tmy_keys, tmy_generation.values, strict=False))

    # Map demand timestamps to TMY values
    demand_keys = demand.index.strftime("%m-%d %H:%M")
    aligned_values = [tmy_lookup.get(key, 0.0) for key in demand_keys]

    return pd.Series(aligned_values, index=demand.index, name="generation_kw")


def calculate_summary(
    results: SimulationResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> SummaryStatistics:
    """Calculate summary statistics from simulation results.

    Args:
        results: Simulation results with time series
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, seg_revenue_gbp is computed from total grid export.

    Returns:
        SummaryStatistics with totals and ratios
    """
    # Convert power (kW) to energy (kWh) - 1 minute = 1/60 hour
    minutes_to_hours = 1 / 60

    total_gen = float(results.generation.sum() * minutes_to_hours)
    total_demand = float(results.demand.sum() * minutes_to_hours)
    total_self = float(results.self_consumption.sum() * minutes_to_hours)
    total_import = float(results.grid_import.sum() * minutes_to_hours)
    total_export = float(results.grid_export.sum() * minutes_to_hours)
    total_charge = float(results.battery_charge.sum() * minutes_to_hours)
    total_discharge = float(results.battery_discharge.sum() * minutes_to_hours)

    peak_gen = float(results.generation.max())
    peak_demand = float(results.demand.max())

    # Calculate financial totals
    total_import_cost = float(results.import_cost.sum())
    total_export_revenue = float(results.export_revenue.sum())
    net_cost = total_import_cost - total_export_revenue

    # Calculate ratios with zero-division protection
    self_consumption_ratio = total_self / total_gen if total_gen > 0 else 0.0
    grid_dependency_ratio = total_import / total_demand if total_demand > 0 else 0.0
    export_ratio = total_export / total_gen if total_gen > 0 else 0.0

    # Calculate simulation duration
    sim_days = (results.generation.index[-1] - results.generation.index[0]).days + 1

    # Calculate SEG revenue if tariff is provided
    seg_revenue_gbp: Optional[float] = None
    if seg_tariff_pence_per_kwh is not None:
        seg_revenue_gbp = total_export * seg_tariff_pence_per_kwh / 100.0

    # Calculate heat pump metrics if heat pump load is present
    total_heat_pump_kwh: Optional[float] = None
    peak_heat_pump_kw: Optional[float] = None
    heat_pump_ratio: Optional[float] = None
    if results.heat_pump_load is not None:
        total_heat_pump_kwh = float(results.heat_pump_load.sum() * minutes_to_hours)
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
    )
