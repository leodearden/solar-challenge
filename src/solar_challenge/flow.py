# SPDX-License-Identifier: AGPL-3.0-or-later
"""Energy flow calculations for PV and battery systems."""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final, Optional

import pandas as pd

from solar_challenge.battery import Battery
from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    SelfConsumptionStrategy,
    compute_grid_charge_power_kw,
)
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import HOURS_PER_MINUTE


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

    Every field but battery_soc is a flow: an energy the timestep moved, in kWh,
    so never negative. Construction raises ValueError naming each flow below 0
    or NaN, and its value. battery_soc is the state of charge after the
    timestep, in kWh.
    """

    generation: float
    demand: float
    self_consumption: float
    battery_charge: float
    battery_discharge: float
    grid_export: float
    grid_import: float
    battery_soc: float  # SOC after this timestep
    grid_charge: float = 0.0  # informational: kWh stored in battery from grid (sub-set of battery_charge and grid_import)

    def __post_init__(self) -> None:
        """Refuse a flow that is negative or NaN, naming each such flow and its value."""
        refused = [f"{flow}={value!r}" for flow in _FLOWS if not (value := getattr(self, flow)) >= 0.0]
        if refused:
            raise ValueError(
                "EnergyFlowResult's flows are the energies its timestep moved, so each is at least 0: "
                f"got {', '.join(refused)}"
            )


_FLOWS = tuple(field.name for field in fields(EnergyFlowResult) if field.name != "battery_soc")


def _build_grid_charge_context(
    battery: "Battery",
    tariff: TariffConfig,
    timestamp: pd.Timestamp,
    *,
    target_soc_kwh: float,
) -> GridChargeContext:
    """Build a GridChargeContext from a battery and tariff for the given timestamp, filling the battery to target_soc_kwh.

    Its cheap-period classification is TariffConfig.is_cheap_at's, which
    :func:`simulate_timestep_tou` also reads, so both dispatch paths classify each
    minute alike; a tariff with no rate spread has no cheap minute.
    """
    return GridChargeContext(
        current_rate=tariff.get_rate(timestamp),
        peak_rate=tariff.peak_rate,
        is_cheap_period=tariff.is_cheap_at(timestamp),
        target_soc_kwh=target_soc_kwh,
        max_charge_kw=battery.max_charge_kw,
        round_trip_efficiency=battery.charge_efficiency * battery.discharge_efficiency,
        charge_efficiency=battery.charge_efficiency,
    )


@dataclass(frozen=True)
class _StepEnergies:
    """A timestep's duration in hours, its generation and demand as energies in kWh, and the excess and shortfall between them."""

    duration_hours: float
    generation_kwh: float
    demand_kwh: float
    excess_kwh: float
    shortfall_kwh: float

    @classmethod
    def from_powers(cls, generation_kw: float, demand_kw: float, timestep_minutes: float) -> "_StepEnergies":
        """Return the energies a timestep of timestep_minutes moves at generation_kw and demand_kw."""
        duration_hours = timestep_minutes * HOURS_PER_MINUTE
        generation_kwh = generation_kw * duration_hours
        demand_kwh = demand_kw * duration_hours
        return cls(
            duration_hours=duration_hours,
            generation_kwh=generation_kwh,
            demand_kwh=demand_kwh,
            excess_kwh=max(0.0, generation_kwh - demand_kwh),
            shortfall_kwh=max(0.0, demand_kwh - generation_kwh),
        )


@dataclass(frozen=True)
class _BatteryExchange:
    """The energies a battery stored from PV and from the grid (after charge losses)
    and delivered to the home's bus in one timestep, in kWh."""

    pv_charge_kwh: float
    grid_charge_kwh: float
    discharge_kwh: float


_NO_EXCHANGE: Final = _BatteryExchange(pv_charge_kwh=0.0, grid_charge_kwh=0.0, discharge_kwh=0.0)


def _execute(decision: DispatchDecision, battery: Battery, timestep_minutes: float) -> _BatteryExchange:
    """Run decision on battery for one timestep: its PV charge, then its grid charge, then its discharge, skipping each power not above 0."""
    return _BatteryExchange(
        pv_charge_kwh=battery.charge(decision.charge_kw, timestep_minutes) if decision.charge_kw > 0 else 0.0,
        grid_charge_kwh=(
            battery.charge(decision.grid_charge_kw, timestep_minutes) if decision.grid_charge_kw > 0 else 0.0
        ),
        discharge_kwh=(
            battery.discharge(decision.discharge_kw, timestep_minutes) if decision.discharge_kw > 0 else 0.0
        ),
    )


def _settle(step: _StepEnergies, exchange: _BatteryExchange, battery_soc_kwh: float) -> EnergyFlowResult:
    """Return a timestep's EnergyFlowResult, settling with the grid what its battery did not store or supply."""
    battery_charge_kwh = exchange.pv_charge_kwh + exchange.grid_charge_kwh

    # Self-consumption: direct PV consumption + battery discharge (capped at demand)
    direct_consumption_kwh = min(step.generation_kwh, step.demand_kwh)
    self_consumption_kwh = min(direct_consumption_kwh + exchange.discharge_kwh, step.demand_kwh)

    # Split-source grid flows, which keep validate_energy_balance closed
    # (docs/prds/tou-grid-charging-battery-arbitrage.md §3.1): only PV charge
    # reduces export, and grid charge adds the energy it stored to import.
    grid_export_kwh = max(0.0, step.excess_kwh - exchange.pv_charge_kwh)
    grid_import_kwh = max(0.0, step.shortfall_kwh - exchange.discharge_kwh) + exchange.grid_charge_kwh

    return EnergyFlowResult(
        generation=step.generation_kwh,
        demand=step.demand_kwh,
        self_consumption=self_consumption_kwh,
        battery_charge=battery_charge_kwh,
        battery_discharge=exchange.discharge_kwh,
        grid_export=grid_export_kwh,
        grid_import=grid_import_kwh,
        battery_soc=battery_soc_kwh,
        grid_charge=exchange.grid_charge_kwh,
    )


def simulate_timestep(
    generation_kw: float,
    demand_kw: float,
    battery: Optional[Battery],
    timestep_minutes: float = 1.0,
    timestamp: Optional[datetime] = None,
    strategy: Optional[DispatchStrategy] = None,
    *,
    tariff: Optional[TariffConfig] = None,
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
        strategy: Dispatch strategy to use (defaults to SelfConsumptionStrategy).
            Its ``decide_action`` is given the battery's effective (SOH-derated)
            capacity, ``Battery.effective_capacity_kwh``, as ``battery_capacity_kwh``.
        tariff: Optional tariff configuration.  When provided while
            ``battery.grid_charge_target_kwh`` is not None, a :class:`~solar_challenge.dispatch.GridChargeContext`
            is built and forwarded to ``strategy.decide_action`` so strategies
            can emit ``grid_charge_kw > 0``.  When ``None`` (default), the
            grid-charge context is not built and results are bit-identical to
            omitting the argument entirely.

    Returns:
        EnergyFlowResult with all energy flows in kWh
    """
    step = _StepEnergies.from_powers(generation_kw, demand_kw, timestep_minutes)
    if battery is None:
        return _settle(step, _NO_EXCHANGE, 0.0)

    if strategy is None:
        strategy = SelfConsumptionStrategy()

    if timestamp is None:
        timestamp = datetime(1970, 1, 1)

    target_soc_kwh = battery.grid_charge_target_kwh
    grid_charge_ctx = (
        _build_grid_charge_context(battery, tariff, pd.Timestamp(timestamp), target_soc_kwh=target_soc_kwh)
        if tariff is not None and target_soc_kwh is not None
        else None
    )

    decision = strategy.decide_action(
        timestamp=timestamp,
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery_soc_kwh=battery.soc_kwh,
        battery_capacity_kwh=battery.effective_capacity_kwh,
        timestep_minutes=timestep_minutes,
        grid_charge_ctx=grid_charge_ctx,
    )

    exchange = _execute(decision, battery, timestep_minutes)
    return _settle(step, exchange, battery.soc_kwh)


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
    2. Classify the current minute as cheap or expensive with
       TariffConfig.is_cheap_at, as the grid-charge context does.  A tariff
       with no rate spread has no cheap minute, so every step takes the
       expensive-period branch, which is plain self-consumption.
    3. During cheap periods (off-peak):
       - Excess PV charges battery aggressively
       - Remaining excess exports to grid
       - When ``battery.grid_charge_target_kwh`` is not None, the battery tops up
         from the grid toward it by the power :func:`compute_grid_charge_power_kw`
         returns
    4. During expensive periods (peak):
       - Discharge battery to meet demand before importing from grid, asking it
         for the shortfall power demand_kw - generation_kw whenever that is above
         0, as the dispatch strategies ask
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
    step = _StepEnergies.from_powers(generation_kw, demand_kw, timestep_minutes)
    is_cheap_period = tariff.is_cheap_at(timestamp)
    if battery is None:
        return _settle(step, _NO_EXCHANGE, 0.0)

    pv_charge_kwh = 0.0
    grid_charge_kwh = 0.0
    discharge_kwh = 0.0
    if is_cheap_period:
        # Off-peak: charge from excess PV, then optionally top-up from grid
        if step.excess_kwh > 0:
            excess_power_kw = step.excess_kwh / step.duration_hours
            pv_charge_kwh = battery.charge(excess_power_kw, timestep_minutes)

        target_soc_kwh = battery.grid_charge_target_kwh
        if target_soc_kwh is not None:
            pv_charge_power_kw = min(
                step.excess_kwh / step.duration_hours if step.excess_kwh > 0 else 0.0,
                battery.max_charge_kw,
            )
            ctx = _build_grid_charge_context(battery, tariff, timestamp, target_soc_kwh=target_soc_kwh)
            grid_power = compute_grid_charge_power_kw(
                ctx,
                battery_soc_kwh=battery.soc_kwh,  # post-PV-charge SOC
                pv_charge_power_kw=pv_charge_power_kw,
                timestep_minutes=timestep_minutes,
            )
            if grid_power > 0:
                grid_charge_kwh = battery.charge(grid_power, timestep_minutes)
    else:
        # Peak: discharge to meet shortfall, then charge from excess PV
        shortfall_kw = max(0.0, demand_kw - generation_kw)
        if shortfall_kw > 0:
            discharge_kwh = battery.discharge(shortfall_kw, timestep_minutes)

        if step.excess_kwh > 0:
            excess_power_kw = step.excess_kwh / step.duration_hours
            pv_charge_kwh = battery.charge(excess_power_kw, timestep_minutes)

    exchange = _BatteryExchange(
        pv_charge_kwh=pv_charge_kwh, grid_charge_kwh=grid_charge_kwh, discharge_kwh=discharge_kwh
    )
    return _settle(step, exchange, battery.soc_kwh)


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
    # _settle derives the flows so that this balance closes whenever a step's PV charge is within
    # its excess and its discharge within its shortfall.
    energy_in = result.generation + result.grid_import
    storage_delta = result.battery_charge - result.battery_discharge
    energy_out = result.demand + result.grid_export + storage_delta

    imbalance = abs(energy_in - energy_out)

    if imbalance > tolerance:
        raise ValueError(
            f"Energy balance violated: in={energy_in:.6f} kWh, out={energy_out:.6f} kWh, "
            f"imbalance={imbalance:.6f} kWh (tolerance={tolerance} kWh)"
        )

    return True
