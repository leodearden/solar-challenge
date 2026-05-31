# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery dispatch strategy framework.

This module provides an abstract framework for battery dispatch strategies,
allowing different algorithms to decide when and how to charge/discharge
batteries based on generation, demand, tariffs, and other factors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class DispatchDecision:
    """Decision from a dispatch strategy for a single timestep.

    Attributes:
        charge_kw: Requested battery charging power in kW (non-negative).
            Represents PV or other on-site charge power.
        discharge_kw: Requested battery discharge power in kW (non-negative)
        grid_charge_kw: Requested grid-to-battery charging power in kW
            (non-negative, default 0.0). Represents deliberate charging from
            the grid (e.g. during cheap-rate periods). May co-exist with
            charge_kw > 0 (both are charging), but is mutually exclusive with
            discharge_kw > 0.
    """

    charge_kw: float
    discharge_kw: float
    grid_charge_kw: float = 0.0

    def __post_init__(self) -> None:
        """Validate dispatch decision parameters."""
        if self.charge_kw < 0:
            raise ValueError(
                f"Charge power must be non-negative, got {self.charge_kw} kW"
            )
        if self.discharge_kw < 0:
            raise ValueError(
                f"Discharge power must be non-negative, got {self.discharge_kw} kW"
            )
        if self.grid_charge_kw < 0:
            raise ValueError(
                f"Grid-charge power must be non-negative, got {self.grid_charge_kw} kW"
            )
        if self.charge_kw > 0 and self.discharge_kw > 0:
            raise ValueError(
                "Cannot charge and discharge simultaneously: "
                f"charge={self.charge_kw} kW, discharge={self.discharge_kw} kW"
            )
        if self.grid_charge_kw > 0 and self.discharge_kw > 0:
            raise ValueError(
                "Cannot grid-charge and discharge simultaneously: "
                f"grid_charge={self.grid_charge_kw} kW, discharge={self.discharge_kw} kW"
            )


@dataclass(frozen=True)
class GridChargeContext:
    """Context bundle for rate-aware grid-to-battery charging.

    A plain, immutable container of floats and a bool that describes the
    current tariff environment and battery configuration needed to decide
    how much power to draw from the grid for battery charging.  Inputs are
    pre-validated upstream (battery config / efficiency bounds), so this
    dataclass intentionally has no __post_init__ validation.

    Attributes:
        current_rate: Current grid import rate in £/kWh
        peak_rate: Reference peak rate in £/kWh used to evaluate the
            economic spread gate (charging is only worthwhile when the
            round-trip arbitrage profit is positive)
        is_cheap_period: True when the current tariff period is considered
            cheap enough to warrant grid charging
        target_soc_fraction: Target state-of-charge as a fraction of
            capacity (0.0–1.0) to fill up to during cheap periods
        max_charge_kw: Maximum battery charge power in kW (hardware limit)
        round_trip_efficiency: Round-trip charge/discharge efficiency
            (0.0–1.0), used in the spread gate calculation
        charge_efficiency: One-way charge efficiency (0.0–1.0), used to
            account for losses when computing how much grid power is needed
            to reach the target SOC
    """

    current_rate: float
    peak_rate: float
    is_cheap_period: bool
    target_soc_fraction: float
    max_charge_kw: float
    round_trip_efficiency: float
    charge_efficiency: float


class DispatchStrategy(ABC):
    """Abstract base class for battery dispatch strategies.

    A dispatch strategy determines when and how to charge/discharge a battery
    based on current conditions (generation, demand, SOC, time, tariffs, etc.).

    Subclasses must implement decide_action() to return a DispatchDecision
    for each timestep.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name identifying this strategy."""
        pass

    @abstractmethod
    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
    ) -> DispatchDecision:
        """Decide battery charge/discharge action for current timestep.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes

        Returns:
            DispatchDecision specifying charge_kw or discharge_kw

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        pass


class SelfConsumptionStrategy(DispatchStrategy):
    """Self-consumption dispatch strategy.

    Maximizes on-site consumption of PV generation by:
    - Charging battery from excess PV (generation > demand)
    - Discharging battery to meet shortfall (demand > generation)
    - Minimizing grid import/export

    This is the default strategy and replicates the original flow.py logic.
    """

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "self_consumption"

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
    ) -> DispatchDecision:
        """Decide battery action to maximize self-consumption.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes

        Returns:
            DispatchDecision with charge_kw if excess PV available,
            discharge_kw if demand exceeds generation, or both zero if
            generation equals demand

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        # Validate inputs
        if generation_kw < 0:
            raise ValueError(
                f"Generation must be non-negative, got {generation_kw} kW"
            )
        if demand_kw < 0:
            raise ValueError(f"Demand must be non-negative, got {demand_kw} kW")
        if battery_soc_kwh < 0:
            raise ValueError(
                f"Battery SOC must be non-negative, got {battery_soc_kwh} kWh"
            )
        if battery_capacity_kwh <= 0:
            raise ValueError(
                f"Battery capacity must be positive, got {battery_capacity_kwh} kWh"
            )
        if timestep_minutes <= 0:
            raise ValueError(
                f"Timestep must be positive, got {timestep_minutes} minutes"
            )

        # Calculate excess and shortfall
        excess_kw = max(0.0, generation_kw - demand_kw)
        shortfall_kw = max(0.0, demand_kw - generation_kw)

        # Decide action based on excess/shortfall
        if excess_kw > 0:
            # Charge from excess PV
            return DispatchDecision(charge_kw=excess_kw, discharge_kw=0.0)
        elif shortfall_kw > 0:
            # Discharge to meet shortfall
            return DispatchDecision(charge_kw=0.0, discharge_kw=shortfall_kw)
        else:
            # Generation exactly equals demand, no action needed
            return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)


class TariffPeriod(Enum):
    """Enumeration of tariff periods for time-of-use strategies.

    Attributes:
        PEAK: Peak tariff period (higher electricity rates)
        OFF_PEAK: Off-peak tariff period (lower electricity rates)
    """

    PEAK = "peak"
    OFF_PEAK = "off_peak"


class TOUOptimizedStrategy(DispatchStrategy):
    """Time-of-use optimized dispatch strategy.

    Optimizes battery operation based on tariff periods by:
    - Charging battery during off-peak hours (from excess PV)
    - Discharging battery during peak hours to offset demand and reduce costs
    - Still opportunistically charging from excess PV even during peak hours

    This strategy is designed for scenarios with time-of-use tariffs where
    electricity costs vary by time of day.
    """

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "tou_optimized"

    def __init__(
        self,
        peak_hours: List[Tuple[int, int]],
        off_peak_hours: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        """Initialize TOU-optimized strategy with tariff period definitions.

        Args:
            peak_hours: List of (start_hour, end_hour) tuples defining peak periods.
                Hours are in 24-hour format (0-23). For example, [(17, 20)]
                represents peak period from 5 PM to 8 PM.
            off_peak_hours: Optional list of (start_hour, end_hour) tuples for
                off-peak periods. If not specified, all non-peak hours are
                considered off-peak.

        Raises:
            ValueError: If hour ranges are invalid (not 0-23, start >= end)
        """
        self._peak_hours = peak_hours
        self._off_peak_hours = off_peak_hours

        # Validate peak hours
        for start, end in peak_hours:
            if not (0 <= start < 24 and 0 <= end <= 24):
                raise ValueError(
                    f"Peak hours must be in range 0-23, got ({start}, {end})"
                )
            if start >= end:
                raise ValueError(
                    f"Peak period start must be before end, got ({start}, {end})"
                )

        # Validate off-peak hours if provided
        if off_peak_hours is not None:
            for start, end in off_peak_hours:
                if not (0 <= start < 24 and 0 <= end <= 24):
                    raise ValueError(
                        f"Off-peak hours must be in range 0-23, got ({start}, {end})"
                    )
                if start >= end:
                    raise ValueError(
                        f"Off-peak period start must be before end, got ({start}, {end})"
                    )

    def _get_tariff_period(self, timestamp: datetime) -> TariffPeriod:
        """Determine tariff period for given timestamp.

        Args:
            timestamp: Timestamp to check

        Returns:
            TariffPeriod.PEAK if timestamp falls within peak hours,
            TariffPeriod.OFF_PEAK otherwise
        """
        hour = timestamp.hour

        # Check if current hour falls within any peak period
        for start, end in self._peak_hours:
            if start <= hour < end:
                return TariffPeriod.PEAK

        # If off_peak_hours specified, verify it's in an off-peak period
        if self._off_peak_hours is not None:
            for start, end in self._off_peak_hours:
                if start <= hour < end:
                    return TariffPeriod.OFF_PEAK
            # Not in peak or explicit off-peak, treat as off-peak by default
            return TariffPeriod.OFF_PEAK

        # Not in peak period, so it's off-peak
        return TariffPeriod.OFF_PEAK

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
    ) -> DispatchDecision:
        """Decide battery action based on time-of-use tariff optimization.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes

        Returns:
            DispatchDecision optimized for TOU tariffs:
            - Off-peak: charge from excess PV
            - Peak: discharge to meet demand, still charge from excess PV

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        # Validate inputs
        if generation_kw < 0:
            raise ValueError(
                f"Generation must be non-negative, got {generation_kw} kW"
            )
        if demand_kw < 0:
            raise ValueError(f"Demand must be non-negative, got {demand_kw} kW")
        if battery_soc_kwh < 0:
            raise ValueError(
                f"Battery SOC must be non-negative, got {battery_soc_kwh} kWh"
            )
        if battery_capacity_kwh <= 0:
            raise ValueError(
                f"Battery capacity must be positive, got {battery_capacity_kwh} kWh"
            )
        if timestep_minutes <= 0:
            raise ValueError(
                f"Timestep must be positive, got {timestep_minutes} minutes"
            )

        # Determine current tariff period
        tariff_period = self._get_tariff_period(timestamp)

        # Calculate excess and shortfall
        excess_kw = max(0.0, generation_kw - demand_kw)
        shortfall_kw = max(0.0, demand_kw - generation_kw)

        # Decision logic based on tariff period
        if tariff_period == TariffPeriod.OFF_PEAK:
            # Off-peak: charge from excess PV (like self-consumption)
            if excess_kw > 0:
                return DispatchDecision(charge_kw=excess_kw, discharge_kw=0.0)
            elif shortfall_kw > 0:
                # Off-peak: preserve battery for expensive peak periods
                # Let cheap off-peak grid power handle the shortfall
                return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
            else:
                return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        else:
            # Peak period: discharge to offset demand, charge from excess PV
            if excess_kw > 0:
                # Free PV energy available - charge even during peak
                return DispatchDecision(charge_kw=excess_kw, discharge_kw=0.0)
            elif shortfall_kw > 0:
                # Demand exceeds generation - discharge to reduce grid import
                return DispatchDecision(charge_kw=0.0, discharge_kw=shortfall_kw)
            else:
                # Generation equals demand
                return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)


class PeakShavingStrategy(DispatchStrategy):
    """Peak shaving dispatch strategy.

    Limits grid import to a configurable threshold by:
    - Charging battery from excess PV (generation > demand)
    - Discharging battery when grid import would exceed the threshold
    - Shaving demand peaks to reduce grid stress and capacity charges

    This strategy is designed for scenarios where grid connection capacity
    is limited or where demand charges incentivize reducing peak import.
    """

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "peak_shaving"

    def __init__(self, import_limit_kw: float) -> None:
        """Initialize peak shaving strategy with grid import threshold.

        Args:
            import_limit_kw: Maximum allowed grid import in kW. Battery will
                discharge to keep grid import at or below this level.

        Raises:
            ValueError: If import_limit_kw is not positive
        """
        if import_limit_kw <= 0:
            raise ValueError(
                f"Import limit must be positive, got {import_limit_kw} kW"
            )
        self._import_limit_kw = import_limit_kw

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
    ) -> DispatchDecision:
        """Decide battery action to limit grid import below threshold.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes

        Returns:
            DispatchDecision with:
            - charge_kw if excess PV available
            - discharge_kw to reduce grid import below threshold
            - both zero if generation meets demand within threshold

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        # Validate inputs
        if generation_kw < 0:
            raise ValueError(
                f"Generation must be non-negative, got {generation_kw} kW"
            )
        if demand_kw < 0:
            raise ValueError(f"Demand must be non-negative, got {demand_kw} kW")
        if battery_soc_kwh < 0:
            raise ValueError(
                f"Battery SOC must be non-negative, got {battery_soc_kwh} kWh"
            )
        if battery_capacity_kwh <= 0:
            raise ValueError(
                f"Battery capacity must be positive, got {battery_capacity_kwh} kWh"
            )
        if timestep_minutes <= 0:
            raise ValueError(
                f"Timestep must be positive, got {timestep_minutes} minutes"
            )

        # Calculate excess and shortfall
        excess_kw = max(0.0, generation_kw - demand_kw)
        shortfall_kw = max(0.0, demand_kw - generation_kw)

        # Decision logic based on excess/shortfall and import threshold
        if excess_kw > 0:
            # Charge from excess PV
            return DispatchDecision(charge_kw=excess_kw, discharge_kw=0.0)
        elif shortfall_kw > 0:
            # Check if grid import would exceed threshold
            if shortfall_kw > self._import_limit_kw:
                # Discharge to shave peak: reduce import to threshold
                peak_shave_kw = shortfall_kw - self._import_limit_kw
                return DispatchDecision(charge_kw=0.0, discharge_kw=peak_shave_kw)
            else:
                # Shortfall is below threshold, no battery action needed
                return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        else:
            # Generation exactly equals demand
            return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
