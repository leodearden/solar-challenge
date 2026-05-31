# SPDX-License-Identifier: AGPL-3.0-or-later
"""Energy flow calculations for PV and battery systems."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from solar_challenge.battery import Battery
from solar_challenge.dispatch import DispatchStrategy, SelfConsumptionStrategy
from solar_challenge.tariff import TariffConfig


def calculate_self_consumption(
    generation: pd.Series,
    demand: pd.Series
) -> pd.Series:
    """Calculate instantaneous self-consumption.

    Self-consumption is the portion of PV generation that is consumed
    on-site at the moment of generation.

    Args:
        generation: PV generation time series in kW
        demand: Demand/consumption time series in kW

    Returns:
        Self-consumption time series in kW (min of generation and demand)

    Raises:
        ValueError: If series have different lengths or contain negative values
    """
    if len(generation) != len(demand):
        raise ValueError(
            f"Series must have same length: generation={len(generation)}, "
            f"demand={len(demand)}"
        )

    if (generation < 0).any():
        raise ValueError("Generation series contains negative values")
    if (demand < 0).any():
        raise ValueError("Demand series contains negative values")

    result = pd.concat([generation, demand], axis=1).min(axis=1)
    result.name = "self_consumption"
    return result


def calculate_excess_pv(
    generation: pd.Series,
    demand: pd.Series
) -> pd.Series:
    """Calculate excess PV generation available for export or battery charging.

    Excess = generation - demand when positive, else 0.

    Args:
        generation: PV generation time series in kW
        demand: Demand/consumption time series in kW

    Returns:
        Excess PV time series in kW (non-negative)

    Raises:
        ValueError: If series have different lengths or contain negative values
    """
    if len(generation) != len(demand):
        raise ValueError(
            f"Series must have same length: generation={len(generation)}, "
            f"demand={len(demand)}"
        )

    if (generation < 0).any():
        raise ValueError("Generation series contains negative values")
    if (demand < 0).any():
        raise ValueError("Demand series contains negative values")

    result = (generation - demand).clip(lower=0)
    result.name = "excess_pv"
    return result


def calculate_shortfall(
    generation: pd.Series,
    demand: pd.Series
) -> pd.Series:
    """Calculate demand shortfall requiring battery or grid import.

    Shortfall = demand - generation when positive, else 0.

    Args:
        generation: PV generation time series in kW
        demand: Demand/consumption time series in kW

    Returns:
        Shortfall time series in kW (non-negative)

    Raises:
        ValueError: If series have different lengths or contain negative values
    """
    if len(generation) != len(demand):
        raise ValueError(
            f"Series must have same length: generation={len(generation)}, "
            f"demand={len(demand)}"
        )

    if (generation < 0).any():
        raise ValueError("Generation series contains negative values")
    if (demand < 0).any():
        raise ValueError("Demand series contains negative values")

    result = (demand - generation).clip(lower=0)
    result.name = "shortfall"
    return result


@dataclass
class EnergyFlowResult:
    """Results of energy flow simulation for a single timestep.

    All values in kWh for the timestep.
    """

    generation: float
    demand: float
    self_consumption: float
    battery_charge: float
    battery_discharge: float
    grid_export: float
    grid_import: float
    battery_soc: float  # SOC after this timestep


def simulate_timestep(
    generation_kw: float,
    demand_kw: float,
    battery: Optional[Battery],
    timestep_minutes: float = 1.0,
    timestamp: Optional[datetime] = None,
    strategy: Optional[DispatchStrategy] = None,
) -> EnergyFlowResult:
    """Simulate energy flow for a single timestep.

    Energy flow priority (default self-consumption strategy):
    1. PV generation meets demand directly (self-consumption)
    2. Excess PV charges battery (if strategy allows)
    3. Remaining excess exports to grid
    4. Shortfall draws from battery (if strategy allows)
    5. Remaining shortfall imports from grid

    Args:
        generation_kw: PV generation power in kW
        demand_kw: Demand power in kW
        battery: Battery object (or None for no battery)
        timestep_minutes: Duration of timestep in minutes
        timestamp: Current simulation timestamp (defaults to epoch if None)
        strategy: Dispatch strategy to use (defaults to SelfConsumptionStrategy)

    Returns:
        EnergyFlowResult with all energy flows in kWh
    """
    duration_hours = timestep_minutes / 60

    # Convert power to energy for this timestep
    generation_kwh = generation_kw * duration_hours
    demand_kwh = demand_kw * duration_hours

    # Calculate excess and shortfall
    excess_kwh = max(0.0, generation_kwh - demand_kwh)
    shortfall_kwh = max(0.0, demand_kwh - generation_kwh)

    # Initialize battery-related values
    battery_charge_kwh = 0.0
    battery_discharge_kwh = 0.0
    battery_soc = 0.0

    if battery is not None:
        # Use strategy to decide battery action (default to self-consumption)
        if strategy is None:
            strategy = SelfConsumptionStrategy()

        # Use default timestamp if not provided
        if timestamp is None:
            timestamp = datetime(1970, 1, 1)  # Epoch

        # Get dispatch decision from strategy
        decision = strategy.decide_action(
            timestamp=timestamp,
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery_soc_kwh=battery.soc_kwh,
            battery_capacity_kwh=battery.config.capacity_kwh,
            timestep_minutes=timestep_minutes,
        )

        # Execute battery charge/discharge based on strategy decision
        if decision.charge_kw > 0:
            battery_charge_kwh = battery.charge(decision.charge_kw, timestep_minutes)

        if decision.discharge_kw > 0:
            battery_discharge_kwh = battery.discharge(decision.discharge_kw, timestep_minutes)

        battery_soc = battery.soc_kwh

    # Self-consumption: direct PV consumption + battery discharge (capped at demand)
    # Battery discharge represents PV energy stored earlier and consumed later
    direct_consumption_kwh = min(generation_kwh, demand_kwh)
    self_consumption_kwh = min(direct_consumption_kwh + battery_discharge_kwh, demand_kwh)

    # Calculate grid flows
    # Export = excess - battery_charged
    grid_export_kwh = max(0.0, excess_kwh - battery_charge_kwh)

    # Import = shortfall - battery_discharged
    grid_import_kwh = max(0.0, shortfall_kwh - battery_discharge_kwh)

    return EnergyFlowResult(
        generation=generation_kwh,
        demand=demand_kwh,
        self_consumption=self_consumption_kwh,
        battery_charge=battery_charge_kwh,
        battery_discharge=battery_discharge_kwh,
        grid_export=grid_export_kwh,
        grid_import=grid_import_kwh,
        battery_soc=battery_soc,
    )


def simulate_timestep_tou(
    generation_kw: float,
    demand_kw: float,
    battery: Optional[Battery],
    timestamp: pd.Timestamp,
    tariff: TariffConfig,
    timestep_minutes: float = 1.0,
) -> EnergyFlowResult:
    """Simulate energy flow for a single timestep with TOU-optimized battery dispatch.

    TOU-optimized energy flow strategy:
    1. PV generation meets demand directly (self-consumption)
    2. Determine if current period is cheap or expensive
    3. During cheap periods (off-peak):
       - Excess PV charges battery aggressively
       - Remaining excess exports to grid
       - Battery may charge from grid if rate is very low (future enhancement)
    4. During expensive periods (peak):
       - Discharge battery to meet demand before importing from grid
       - Excess PV charges battery (saving for later peak use)
       - Export only if battery is full

    Args:
        generation_kw: PV generation power in kW
        demand_kw: Demand power in kW
        battery: Battery object (or None for no battery)
        timestamp: Current timestamp for tariff rate lookup
        tariff: Tariff configuration with rate periods
        timestep_minutes: Duration of timestep in minutes

    Returns:
        EnergyFlowResult with all energy flows in kWh
    """
    duration_hours = timestep_minutes / 60

    # Convert power to energy for this timestep
    generation_kwh = generation_kw * duration_hours
    demand_kwh = demand_kw * duration_hours

    # Get current tariff rate
    current_rate = tariff.get_rate(timestamp)

    # Determine average rate across all periods (for peak/off-peak classification)
    # Simple heuristic: if multiple rates exist, classify as cheap/expensive
    all_rates = [period.rate_per_kwh for period in tariff.periods]
    avg_rate = sum(all_rates) / len(all_rates)
    is_cheap_period = current_rate <= avg_rate

    # Calculate excess and shortfall
    excess_kwh = max(0.0, generation_kwh - demand_kwh)
    shortfall_kwh = max(0.0, demand_kwh - generation_kwh)

    # Initialize battery-related values
    battery_charge_kwh = 0.0
    battery_discharge_kwh = 0.0
    battery_soc = 0.0

    if battery is not None:
        if is_cheap_period:
            # Off-peak strategy: charge battery from excess PV
            # Save battery for expensive periods - import from cheap grid instead of discharging
            if excess_kwh > 0:
                excess_power_kw = excess_kwh / duration_hours
                battery_charge_kwh = battery.charge(excess_power_kw, timestep_minutes)

            # During cheap periods, do NOT discharge battery
            # Let grid meet shortfall at low cost, save battery for peak periods
            # battery_discharge_kwh remains 0.0
        else:
            # Peak period strategy: prioritize battery discharge during shortfall
            # Also charge battery from excess to save for next peak
            if shortfall_kwh > 0:
                # Discharge battery aggressively to avoid expensive grid import
                shortfall_power_kw = shortfall_kwh / duration_hours
                battery_discharge_kwh = battery.discharge(shortfall_power_kw, timestep_minutes)

            if excess_kwh > 0:
                # Charge battery from excess (save for next peak period)
                excess_power_kw = excess_kwh / duration_hours
                battery_charge_kwh = battery.charge(excess_power_kw, timestep_minutes)

        battery_soc = battery.soc_kwh

    # Self-consumption: direct PV consumption + battery discharge (capped at demand)
    # Battery discharge represents PV energy stored earlier and consumed later
    direct_consumption_kwh = min(generation_kwh, demand_kwh)
    self_consumption_kwh = min(direct_consumption_kwh + battery_discharge_kwh, demand_kwh)

    # Calculate grid flows
    # Export = excess - battery_charged
    grid_export_kwh = max(0.0, excess_kwh - battery_charge_kwh)

    # Import = shortfall - battery_discharged
    grid_import_kwh = max(0.0, shortfall_kwh - battery_discharge_kwh)

    return EnergyFlowResult(
        generation=generation_kwh,
        demand=demand_kwh,
        self_consumption=self_consumption_kwh,
        battery_charge=battery_charge_kwh,
        battery_discharge=battery_discharge_kwh,
        grid_export=grid_export_kwh,
        grid_import=grid_import_kwh,
        battery_soc=battery_soc,
    )


def validate_energy_balance(
    result: EnergyFlowResult,
    tolerance: float = 0.001,
) -> bool:
    """Validate energy balance for a timestep result.

    Balance equation:
    generation + import = consumption + export + storage_delta

    Where storage_delta = battery_charge - battery_discharge (net storage)

    Args:
        result: Energy flow result to validate
        tolerance: Allowed imbalance in kWh

    Returns:
        True if balance is valid

    Raises:
        ValueError: If balance is violated beyond tolerance
    """
    # Left side: energy in
    energy_in = result.generation + result.grid_import

    # Right side: energy out
    # Note: self_consumption is part of demand that was met
    # Net storage = charge - discharge
    storage_delta = result.battery_charge - result.battery_discharge
    energy_out = result.demand + result.grid_export + storage_delta

    # But wait - we need to reconsider this
    # generation + import = demand + export + (charge - discharge)
    # This simplifies because:
    # - self_consumption = min(gen, demand)
    # - excess = gen - demand when positive
    # - shortfall = demand - gen when positive
    # - export = excess - charge
    # - import = shortfall - discharge

    # Let's verify:
    # gen + import = demand + export + charge - discharge
    # gen + (shortfall - discharge) = demand + (excess - charge) + charge - discharge
    # gen + shortfall - discharge = demand + excess - charge + charge - discharge
    # gen + shortfall = demand + excess
    # This is true since shortfall = max(0, demand - gen) and excess = max(0, gen - demand)

    imbalance = abs(energy_in - energy_out)

    if imbalance > tolerance:
        raise ValueError(
            f"Energy balance violated: in={energy_in:.6f} kWh, out={energy_out:.6f} kWh, "
            f"imbalance={imbalance:.6f} kWh (tolerance={tolerance} kWh)"
        )

    return True
