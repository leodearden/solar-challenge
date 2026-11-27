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
    StepLimits,
    require_valid_step_powers,
)
from solar_challenge.number_fields import NON_NEGATIVE
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import HOURS_PER_MINUTE, require_valid_duration


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


@dataclass(frozen=True)
class EnergyFlowResult:
    """Results of energy flow simulation for a single timestep.

    Every field but battery_soc is a flow: an energy the timestep moved, in kWh,
    so a finite number at least 0. Construction raises ValueError naming each
    flow below 0, NaN or infinite, and its value. battery_soc is the state of
    charge after the timestep, in kWh.

    Every flow is an energy at the home's bus: battery_charge is what the battery
    drew, before its charge losses, and battery_discharge what it delivered, after
    its discharge losses. So generation + grid_import = demand + grid_export +
    battery_charge - battery_discharge closes with no loss term, and the battery's
    SOC changes by charge_efficiency × battery_charge - battery_discharge /
    discharge_efficiency (docs/prds/one-dispatch-engine.md §5.2).

    grid_charge and battery_export are informational parts of other flows, so the
    identity is unchanged by them: grid_charge of battery_charge and grid_import,
    battery_export of battery_discharge and grid_export
    (docs/prds/event-dispatch-and-battery-sizing.md §5.1).
    """

    generation: float
    demand: float
    self_consumption: float
    battery_charge: float
    battery_discharge: float
    grid_export: float
    grid_import: float
    battery_soc: float  # SOC after this timestep
    grid_charge: float = 0.0  # informational: kWh the battery drew from the grid, a part of battery_charge and grid_import
    battery_export: float = 0.0  # informational: kWh the battery sent to the grid, a part of battery_discharge and grid_export

    def __post_init__(self) -> None:
        """Refuse a flow NON_NEGATIVE does not admit (below 0, NaN or infinite), naming each such flow and its value."""
        refused = NON_NEGATIVE.refused({flow: getattr(self, flow) for flow in _FLOWS})
        if refused:
            raise ValueError(
                f"EnergyFlowResult's flows are the energies its timestep moved, so each is a finite number {NON_NEGATIVE}: "
                f"got {', '.join(f'{flow}={value!r}' for flow, value in refused.items())}"
            )


_FLOWS = tuple(field.name for field in fields(EnergyFlowResult) if field.name != "battery_soc")


def _build_grid_charge_context(
    battery: "Battery",
    tariff: TariffConfig,
    timestamp: datetime,
    *,
    target_soc_kwh: float,
    useful_charge_ceiling_kwh: Optional[float],
) -> GridChargeContext:
    """Build a GridChargeContext from a battery and tariff for the given timestamp, filling the battery to target_soc_kwh, or to useful_charge_ceiling_kwh when that is lower.

    Its cheap-period classification is TariffConfig.is_cheap_at's, the clock of a
    TOUOptimizedStrategy built with the tariff; a tariff with no rate spread has no cheap minute.
    """
    return GridChargeContext(
        current_rate=tariff.get_rate(timestamp),
        peak_rate=tariff.peak_rate,
        is_cheap_period=tariff.is_cheap_at(timestamp),
        target_soc_kwh=target_soc_kwh,
        max_charge_kw=battery.max_charge_kw,
        round_trip_efficiency=battery.charge_efficiency * battery.discharge_efficiency,
        charge_efficiency=battery.charge_efficiency,
        useful_charge_ceiling_kwh=useful_charge_ceiling_kwh,
    )


@dataclass(frozen=True)
class _StepEnergies:
    """A timestep's generation and demand as energies in kWh, and the excess and shortfall between them."""

    generation_kwh: float
    demand_kwh: float
    excess_kwh: float
    shortfall_kwh: float

    @classmethod
    def from_powers(cls, generation_kw: float, demand_kw: float, timestep_minutes: float) -> "_StepEnergies":
        """Return the energies a timestep of timestep_minutes moves at generation_kw and demand_kw.

        Raises:
            ValueError: If require_valid_step_powers refuses generation_kw or demand_kw.
        """
        require_valid_step_powers(generation_kw, demand_kw)
        duration_hours = timestep_minutes * HOURS_PER_MINUTE
        generation_kwh = generation_kw * duration_hours
        demand_kwh = demand_kw * duration_hours
        return cls(
            generation_kwh=generation_kwh,
            demand_kwh=demand_kwh,
            excess_kwh=max(0.0, generation_kwh - demand_kwh),
            shortfall_kwh=max(0.0, demand_kwh - generation_kwh),
        )


@dataclass(frozen=True)
class _BatteryExchange:
    """The energies a battery drew from PV and from the grid (before charge losses)
    and delivered to the home's bus (after discharge losses) in one timestep, in kWh,
    and whether its decision asked for export."""

    pv_charge_kwh: float
    grid_charge_kwh: float
    discharge_kwh: float
    export_asked: bool


_NO_EXCHANGE: Final = _BatteryExchange(pv_charge_kwh=0.0, grid_charge_kwh=0.0, discharge_kwh=0.0, export_asked=False)


def _execute(decision: DispatchDecision, battery: Battery, timestep_minutes: float) -> _BatteryExchange:
    """Run decision on battery for one timestep: its PV charge, then its grid charge, then its discharge and export in one discharge, skipping each power not above 0."""
    discharge_kw = decision.discharge_kw + decision.export_kw
    return _BatteryExchange(
        pv_charge_kwh=battery.charge(decision.charge_kw, timestep_minutes) if decision.charge_kw > 0 else 0.0,
        grid_charge_kwh=(
            battery.charge(decision.grid_charge_kw, timestep_minutes) if decision.grid_charge_kw > 0 else 0.0
        ),
        discharge_kwh=battery.discharge(discharge_kw, timestep_minutes) if discharge_kw > 0 else 0.0,
        export_asked=decision.export_kw > 0,
    )


def _settle(step: _StepEnergies, exchange: _BatteryExchange, battery_soc_kwh: float) -> EnergyFlowResult:
    """Return a timestep's EnergyFlowResult, settling with the grid what its battery did not draw or supply."""
    battery_charge_kwh = exchange.pv_charge_kwh + exchange.grid_charge_kwh

    # Self-consumption: direct PV consumption + battery discharge (capped at demand), so the
    # battery's delivery serves the home first and never counts what it exports.
    direct_consumption_kwh = min(step.generation_kwh, step.demand_kwh)
    self_consumption_kwh = min(direct_consumption_kwh + exchange.discharge_kwh, step.demand_kwh)

    # The battery exports what it delivered beyond the shortfall, but only when its decision asked
    # to: a discharge of just the shortfall can deliver an ulp more, which is not an export.
    battery_export_kwh = max(0.0, exchange.discharge_kwh - step.shortfall_kwh) if exchange.export_asked else 0.0

    # Export is the excess the battery did not draw, plus the battery's export; import adds what it
    # drew from the grid (docs/prds/one-dispatch-engine.md §5.2).
    grid_export_kwh = max(0.0, step.excess_kwh - exchange.pv_charge_kwh) + battery_export_kwh
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
        battery_export=battery_export_kwh,
    )


def simulate_timestep(
    generation_kw: float,
    demand_kw: float,
    battery: Optional[Battery],
    timestep_minutes: float,
    timestamp: Optional[datetime] = None,
    strategy: Optional[DispatchStrategy] = None,
    *,
    tariff: Optional[TariffConfig] = None,
    useful_charge_ceiling_kwh: Optional[float] = None,
) -> EnergyFlowResult:
    """Simulate energy flow for a single timestep.

    Energy flow priority (default self-consumption strategy):
    1. PV generation meets demand directly (self-consumption)
    2. Excess PV charges battery (if strategy allows)
    3. Remaining excess exports to grid
    4. Shortfall draws from battery (if strategy allows)
    5. Remaining shortfall imports from grid
    6. What the battery delivers beyond the shortfall exports to grid (if the strategy
       asks for export_kw), as battery_export

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
        useful_charge_ceiling_kwh: Optional SOC in kWh above which this step's grid
            charge is forecast to be stranded by PV, carried in the grid-charge context
            as ``GridChargeContext.useful_charge_ceiling_kwh``: grid charging then fills
            to the lower of it and ``battery.grid_charge_target_kwh``.  ``None``
            (default) means no ceiling.  It has no effect when no context is built.

    Returns:
        EnergyFlowResult with all energy flows in kWh

    Raises:
        ValueError: If timestep_minutes is not positive and finite, naming it; then if generation_kw
            or demand_kw is not finite and at least 0, naming it; then, when a grid-charge context
            is built, if useful_charge_ceiling_kwh is neither None nor finite and at least 0,
            naming it; then if the strategy's decision asks for more than the step allows
            (StepLimits.require_admissible), an export beyond the headroom the battery's discharge
            limit leaves after the shortfall included, naming the strategy and each power above
            its limit.
            These checks run before any battery moves energy. Then, after any battery has moved,
            if a flow the step computes is not a finite number at least 0 (an energy beyond a
            float, or one its battery reports), naming each such flow and its value
            (EnergyFlowResult).
    """
    require_valid_duration(timestep_minutes, "Timestep")
    step = _StepEnergies.from_powers(generation_kw, demand_kw, timestep_minutes)
    if battery is None:
        return _settle(step, _NO_EXCHANGE, 0.0)

    if strategy is None:
        strategy = SelfConsumptionStrategy()

    if timestamp is None:
        timestamp = datetime(1970, 1, 1)

    target_soc_kwh = battery.grid_charge_target_kwh
    grid_charge_ctx = (
        _build_grid_charge_context(
            battery,
            tariff,
            timestamp,
            target_soc_kwh=target_soc_kwh,
            useful_charge_ceiling_kwh=useful_charge_ceiling_kwh,
        )
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
    StepLimits.for_step(
        generation_kw,
        demand_kw,
        max_charge_kw=battery.max_charge_kw,
        max_discharge_kw=battery.max_discharge_kw,
    ).require_admissible(decision, strategy.name)

    exchange = _execute(decision, battery, timestep_minutes)
    return _settle(step, exchange, battery.soc_kwh)


def validate_energy_balance(
    result: EnergyFlowResult,
    tolerance: float = 0.001,
) -> bool:
    """Validate energy balance for a timestep result.

    Balance equation:
    generation + grid_import = demand + grid_export + battery_net_draw

    Where battery_net_draw = battery_charge - battery_discharge, the battery's net draw from
    the bus. Both are bus energies, so the balance carries no loss term; the battery's SOC
    change is the storage identity in EnergyFlowResult's docstring.

    Args:
        result: Energy flow result to validate
        tolerance: Allowed imbalance in kWh

    Returns:
        True if balance is valid

    Raises:
        ValueError: If balance is violated beyond tolerance
    """
    # StepLimits keeps every step simulate_timestep executes within its excess and its shortfall, and
    # _settle books what the battery delivers beyond the shortfall as grid export, so its flows close
    # this balance.
    energy_in = result.generation + result.grid_import
    battery_net_draw_kwh = result.battery_charge - result.battery_discharge
    energy_out = result.demand + result.grid_export + battery_net_draw_kwh

    imbalance = abs(energy_in - energy_out)

    if imbalance > tolerance:
        raise ValueError(
            f"Energy balance violated: in={energy_in:.6f} kWh, out={energy_out:.6f} kWh, "
            f"imbalance={imbalance:.6f} kWh (tolerance={tolerance} kWh)"
        )

    return True
