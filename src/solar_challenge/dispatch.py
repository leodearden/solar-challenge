# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery dispatch strategy framework.

This module provides an abstract framework for battery dispatch strategies,
allowing different algorithms to decide when and how to charge/discharge
batteries based on generation, demand, tariffs, and other factors.

It also defines the configuration a battery names its strategy and its grid
charging with: the variants of DispatchStrategyConfig, and GridChargeConfig;
build_dispatch_strategy builds the strategy a variant configures.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from types import MappingProxyType
from typing import List, Literal, Optional, Tuple, TypeAlias, assert_never, get_args
from zoneinfo import ZoneInfo

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    POSITIVE,
    Interval,
    as_finite_float,
    as_whole_numbers,
    read_field,
)
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import HOURS_PER_MINUTE


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
    how much power to draw from the grid for battery charging.

    Efficiency fields (round_trip_efficiency, charge_efficiency) are
    validated in __post_init__ to be in the half-open interval (0, 1] so
    that compute_grid_charge_power_kw can divide by them safely.

    Attributes:
        current_rate: Current grid import rate in £/kWh
        peak_rate: Reference peak rate in £/kWh used to evaluate the
            economic spread gate (charging is only worthwhile when the
            round-trip arbitrage profit is positive)
        is_cheap_period: True when the current tariff period is considered
            cheap enough to warrant grid charging
        target_soc_fraction: Target state-of-charge as a fraction of
            capacity (0.0–1.0) to fill up to during cheap periods
        max_charge_kw: Maximum charge power in kW (hardware C-rate limit of
            the battery/inverter), shared by PV and grid charging
        round_trip_efficiency: Round-trip charge/discharge efficiency in
            (0, 1], used in the spread gate calculation
        charge_efficiency: One-way charge efficiency in (0, 1], used to
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

    def __post_init__(self) -> None:
        """Validate efficiency fields to prevent ZeroDivisionError at runtime."""
        if not (0.0 < self.round_trip_efficiency <= 1.0):
            raise ValueError(
                f"round_trip_efficiency must be in (0, 1], "
                f"got {self.round_trip_efficiency}"
            )
        if not (0.0 < self.charge_efficiency <= 1.0):
            raise ValueError(
                f"charge_efficiency must be in (0, 1], "
                f"got {self.charge_efficiency}"
            )


def compute_grid_charge_power_kw(
    ctx: GridChargeContext,
    *,
    battery_soc_kwh: float,
    capacity_kwh: float,
    pv_charge_power_kw: float,
    timestep_minutes: float,
) -> float:
    """Compute the grid-to-battery charging power for the current timestep.

    Implements the rate-aware dispatch controller of
    docs/prds/tou-grid-charging-battery-arbitrage.md §3.2.
    All inputs are floats/bool (no tariff symbols imported here).

    Args:
        ctx: Tariff and battery context for this timestep.
            ``ctx.round_trip_efficiency`` and ``ctx.charge_efficiency`` must
            be in (0, 1] (enforced by ``GridChargeContext.__post_init__``).
        battery_soc_kwh: Current battery state of charge in kWh.
        capacity_kwh: Total battery capacity in kWh.
        pv_charge_power_kw: PV charging power already being consumed by the
            battery in this timestep (kW). Reduces the residual charging
            headroom available for grid charging.
        timestep_minutes: Duration of the timestep in minutes. Must be
            positive (raises ``ValueError`` if not).

    Returns:
        Recommended grid-to-battery charge power in kW: at least 0.0 and at
        most ``max(0.0, ctx.max_charge_kw - pv_charge_power_kw)``.
        Returns 0.0 when:
        - it is not a cheap period (ctx.is_cheap_period is False), or
        - the spread gate fails (peak saving does not cover round-trip losses),
        - the battery is already at or above the target SOC.

    Raises:
        ValueError: If ``timestep_minutes`` is not positive.
    """
    if timestep_minutes <= 0.0:
        raise ValueError(
            f"timestep_minutes must be positive, got {timestep_minutes}"
        )

    # Gate 1: only charge from grid during cheap periods
    if not ctx.is_cheap_period:
        return 0.0

    # Gate 2: spread gate — only profitable if selling at peak_rate covers
    # the round-trip energy loss when charging at current_rate.
    # Break-even condition: peak_rate > current_rate / round_trip_efficiency
    if ctx.peak_rate <= ctx.current_rate / ctx.round_trip_efficiency:
        return 0.0

    # Gate 3: how much energy is still needed to reach the target SOC?
    target_kwh = ctx.target_soc_fraction * capacity_kwh
    return _grid_power_for_gap_kw(
        ctx,
        gap_kwh=target_kwh - battery_soc_kwh,
        pv_charge_kw=pv_charge_power_kw,
        timestep_minutes=timestep_minutes,
    )


def _charge_headroom_kw(max_charge_kw: float, charge_kw: float) -> float:
    """The max_charge_kw a step's charge_kw of PV charge leaves for grid charging."""
    return max(0.0, max_charge_kw - min(charge_kw, max_charge_kw))


def _grid_power_for_gap_kw(
    ctx: GridChargeContext,
    *,
    gap_kwh: float,
    pv_charge_kw: float,
    timestep_minutes: float,
) -> float:
    """The grid power that stores gap_kwh this step, within the headroom the step's pv_charge_kw of PV charge leaves, and none unless the gap is positive.

    Storing gap_kwh draws gap_kwh / charge_efficiency from the grid.
    """
    if not gap_kwh > 0.0:
        return 0.0
    dt_h = timestep_minutes * HOURS_PER_MINUTE
    return min(gap_kwh / ctx.charge_efficiency / dt_h, _charge_headroom_kw(ctx.max_charge_kw, pv_charge_kw))


def _grid_power_to_target_kw(
    ctx: GridChargeContext,
    *,
    target_kwh: float,
    battery_soc_kwh: float,
    pv_charge_kw: float,
    timestep_minutes: float,
) -> float:
    """The grid power that charges the battery to target_kwh this step, after its pv_charge_kw of PV charge, within the headroom that charge leaves.

    It predicts the SOC after the PV charge as Battery.charge stores it, and asks for
    nothing once that SOC reaches target_kwh.
    """
    dt_h = timestep_minutes * HOURS_PER_MINUTE
    soc_after_pv_kwh = battery_soc_kwh + min(pv_charge_kw, ctx.max_charge_kw) * dt_h * ctx.charge_efficiency
    return _grid_power_for_gap_kw(
        ctx, gap_kwh=target_kwh - soc_after_pv_kwh, pv_charge_kw=pv_charge_kw, timestep_minutes=timestep_minutes
    )


_TARGET_SOC_FRACTION = FRACTION
"""The grid-charge targets, as fractions of the battery's capacity, that GridChargeConfig and ChargeWindow admit."""


@dataclass(frozen=True)
class GridChargeConfig:
    """Configuration for grid-charging (battery arbitrage) mode.

    Attributes:
        target_soc_fraction: Target state-of-charge to reach via grid charging,
            expressed as a fraction of usable capacity: a finite number greater than 0
            and at most 1, held as the float read. Defaults to 0.9.

    Raises:
        ConfigurationError: If target_soc_fraction is a bool, is not a finite number, or
            is outside that range, naming target_soc_fraction and the value.
    """

    target_soc_fraction: float = 0.9

    def __post_init__(self) -> None:
        """Read target_soc_fraction, and hold the float read."""
        read_field(self, "target_soc_fraction", as_finite_float, _TARGET_SOC_FRACTION)


_PEAK_WINDOW_HOURS = Interval(0, 24)
"""The hours a peak window starts and ends at, from 0, the midnight that begins the day, to 24, the one that ends it."""


def _as_hour_window(value: object, field: str, within: Interval) -> tuple[int, int]:
    """Return *value*, a window, read as the (start, end) pair of whole hours *within* admits that starts before it ends, each hour named {field}[{j}].

    Raises:
        ConfigurationError: If as_whole_numbers refuses *value* or one of its hours, or if
            *value* is not a (start, end) pair that starts before it ends, naming *field*
            and *value*.
    """
    hours = as_whole_numbers(value, field, within)
    if len(hours) != 2 or not hours[0] < hours[1]:
        raise ConfigurationError(f"{field} must be a (start, end) window that starts before it ends, got {value!r}")
    return (hours[0], hours[1])


def _as_hour_windows(value: object, field: str, within: Interval) -> tuple[tuple[int, int], ...]:
    """Return *value*, a list of at least one window, as the tuple of its windows, each read by _as_hour_window as {field}[{i}].

    Raises:
        ConfigurationError: If *value* is not a list or tuple, or is empty, naming *field*;
            or if _as_hour_window refuses a window.
    """
    if not isinstance(value, (list, tuple)):
        raise ConfigurationError(f"{field} must be a list of (start, end) windows, got {value!r}")
    if not value:
        raise ConfigurationError(f"{field} must hold at least one (start, end) window; it is empty")
    return tuple(_as_hour_window(window, f"{field}[{index}]", within) for index, window in enumerate(value))


_IMPORT_LIMIT_KW = POSITIVE
"""The grid import limits, in kW, that PeakShavingStrategyConfig and PeakShavingStrategy admit."""


@dataclass(frozen=True)
class SelfConsumptionStrategyConfig:
    """The configuration of a SelfConsumptionStrategy, which has no setting."""

    strategy_type: Literal["self_consumption"] = field(default="self_consumption", init=False)


@dataclass(frozen=True)
class TOUOptimizedStrategyConfig:
    """The configuration of a TOUOptimizedStrategy.

    Attributes:
        peak_hours: The (start, end) hours of the peak periods the strategy discharges the
            battery in: a list of at least one window, each a pair of whole hours from 0 to
            24 that starts before it ends, held as a tuple of int pairs.

    Raises:
        ConfigurationError: With the refusal TOUOptimizedStrategy gives, if peak_hours is
            not a list of at least one window; if an hour is a bool, is not a finite whole
            number, or is outside 0 to 24, naming it peak_hours[i][j] and the value; or if
            a window is not a (start, end) pair that starts before it ends, naming it
            peak_hours[i] and the window.
    """

    peak_hours: tuple[tuple[int, int], ...]
    strategy_type: Literal["tou_optimized"] = field(default="tou_optimized", init=False)

    def __post_init__(self) -> None:
        """Read peak_hours as TOUOptimizedStrategy does, and hold the int pairs read."""
        read_field(self, "peak_hours", _as_hour_windows, _PEAK_WINDOW_HOURS)


@dataclass(frozen=True)
class PeakShavingStrategyConfig:
    """The configuration of a PeakShavingStrategy.

    Attributes:
        import_limit_kw: The grid import, in kW, the strategy discharges the battery to keep
            at or below: read as a finite number greater than 0, and held as the float read.

    Raises:
        ConfigurationError: If import_limit_kw is a bool, is not a finite number, or is not
            greater than 0, naming import_limit_kw and the value, with the refusal
            PeakShavingStrategy gives.
    """

    import_limit_kw: float
    strategy_type: Literal["peak_shaving"] = field(default="peak_shaving", init=False)

    def __post_init__(self) -> None:
        """Read import_limit_kw as PeakShavingStrategy does, and hold the float read."""
        read_field(self, "import_limit_kw", as_finite_float, _IMPORT_LIMIT_KW)


DispatchStrategyConfig: TypeAlias = (
    SelfConsumptionStrategyConfig | TOUOptimizedStrategyConfig | PeakShavingStrategyConfig
)
"""The configuration of a battery's dispatch strategy: one variant per strategy.

A variant's strategy_type, which its constructor does not take, is its tag: the name of the
strategy it configures, and the strategy_type key of the block the scenario grammar reads it from.
"""

STRATEGY_CONFIG_BY_TYPE: Mapping[str, type[DispatchStrategyConfig]] = MappingProxyType(
    {variant.strategy_type: variant for variant in get_args(DispatchStrategyConfig)}
)
"""Each variant of DispatchStrategyConfig by its tag, read-only."""


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
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Decide battery charge/discharge action for current timestep.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.
                A strategy that grid-charges passes it to
                ``compute_grid_charge_power_kw`` to fill ``grid_charge_kw``,
                and only when it is not discharging, because
                ``DispatchDecision`` forbids ``grid_charge_kw > 0`` together
                with ``discharge_kw > 0``.  A strategy that does not
                grid-charge ignores it.  ``None`` means no grid charging.

        Returns:
            DispatchDecision specifying charge_kw or discharge_kw

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        pass


def _require_valid_strategy_inputs(
    generation_kw: float,
    demand_kw: float,
    battery_soc_kwh: float,
    battery_capacity_kwh: float,
    timestep_minutes: float,
) -> None:
    """Refuse a decide_action input out of its range: a negative power or SOC, or a capacity or timestep that is not positive.

    Raises:
        ValueError: Naming the input and its value.
    """
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


class SelfConsumptionStrategy(DispatchStrategy):
    """Self-consumption dispatch strategy.

    Maximizes on-site consumption of PV generation by:
    - Charging battery from excess PV (generation > demand)
    - Discharging battery to meet shortfall (demand > generation)
    - Minimizing grid import/export

    This is the default strategy.
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
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Decide battery action to maximize self-consumption.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context
                (accepted but not used in this strategy).

        Returns:
            DispatchDecision with charge_kw if excess PV available,
            discharge_kw if demand exceeds generation, or both zero if
            generation equals demand

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
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

    def __init__(self, peak_hours: List[Tuple[int, int]]) -> None:
        """Initialize TOU-optimized strategy with tariff period definitions.

        Args:
            peak_hours: List of (start_hour, end_hour) windows defining peak periods: at
                least one, each a pair of whole hours from 0 to 24 that starts before it
                ends, held as a tuple of int pairs. For example, [(17, 20)] represents
                peak period from 5 PM to 8 PM. Every hour outside these ranges is off-peak.

        Raises:
            ConfigurationError: If peak_hours is not a list of at least one window; if an
                hour is a bool, is not a finite whole number, or is outside 0 to 24, naming
                it peak_hours[i][j] and the value; or if a window is not a (start, end)
                pair that starts before it ends, naming it peak_hours[i] and the window.
        """
        self._peak_hours = _as_hour_windows(peak_hours, "peak_hours", _PEAK_WINDOW_HOURS)

    def _get_tariff_period(self, timestamp: datetime) -> TariffPeriod:
        """Determine tariff period for given timestamp.

        Args:
            timestamp: Timestamp to check

        Returns:
            TariffPeriod.PEAK if timestamp falls within peak hours,
            TariffPeriod.OFF_PEAK otherwise
        """
        hour = timestamp.hour
        if any(start <= hour < end for start, end in self._peak_hours):
            return TariffPeriod.PEAK
        return TariffPeriod.OFF_PEAK

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Decide battery action based on time-of-use tariff optimization.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.  When
                supplied and ``grid_charge_ctx.is_cheap_period`` is ``True``,
                the strategy will grid-charge the battery (via
                ``compute_grid_charge_power_kw``) provided the battery is not
                already being discharged, inside ``peak_hours`` too: whether
                a period is cheap is the caller's classification, which both
                dispatch paths share, never ``peak_hours``
                (docs/prds/tou-grid-charging-battery-arbitrage.md §4).
                ``None`` (default) means no grid charging: ``grid_charge_kw``
                is always 0.

        Returns:
            DispatchDecision optimized for TOU tariffs:
            - Off-peak: charge from excess PV; also grid-charges when a
              favourable GridChargeContext is provided.
            - Peak: discharge to meet demand, still charge from excess PV;
              grid-charging is suppressed when discharging.

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )

        # Determine current tariff period
        tariff_period = self._get_tariff_period(timestamp)

        # Calculate excess and shortfall
        excess_kw = max(0.0, generation_kw - demand_kw)
        shortfall_kw = max(0.0, demand_kw - generation_kw)

        if tariff_period == TariffPeriod.OFF_PEAK:
            # Off-peak: charge from excess PV; preserve battery on shortfall
            # (let cheap off-peak grid handle demand directly).
            charge_kw = excess_kw  # 0.0 on shortfall/balanced
            discharge_kw = 0.0
        else:
            # Peak period: discharge to offset demand, charge from excess PV
            if excess_kw > 0:
                # Free PV energy available — charge even during peak
                charge_kw = excess_kw
                discharge_kw = 0.0
            elif shortfall_kw > 0:
                # Demand exceeds generation — discharge to reduce grid import
                charge_kw = 0.0
                discharge_kw = shortfall_kw
            else:
                # Generation equals demand
                charge_kw = 0.0
                discharge_kw = 0.0

        # Grid-charge only while not discharging: DispatchDecision forbids
        # grid_charge_kw > 0 with discharge_kw > 0.  Passing charge_kw as
        # pv_charge_power_kw shares max_charge_kw between PV and grid.
        grid_charge_kw = 0.0
        if (
            grid_charge_ctx is not None
            and grid_charge_ctx.is_cheap_period
            and discharge_kw == 0.0
        ):
            grid_charge_kw = compute_grid_charge_power_kw(
                grid_charge_ctx,
                battery_soc_kwh=battery_soc_kwh,
                capacity_kwh=battery_capacity_kwh,
                pv_charge_power_kw=charge_kw,
                timestep_minutes=timestep_minutes,
            )

        return DispatchDecision(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            grid_charge_kw=grid_charge_kw,
        )


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
            import_limit_kw: Maximum allowed grid import in kW, read as a finite number
                greater than 0, and held as the float read. Battery will discharge to keep
                grid import at or below this level.

        Raises:
            ConfigurationError: If import_limit_kw is a bool, is not a finite number, or is
                not greater than 0, naming import_limit_kw and the value.
        """
        self._import_limit_kw = as_finite_float(import_limit_kw, "import_limit_kw", _IMPORT_LIMIT_KW)

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Decide battery action to limit grid import below threshold.

        Args:
            timestamp: Current simulation timestamp
            generation_kw: PV generation power in kW
            demand_kw: Demand/consumption power in kW
            battery_soc_kwh: Current battery state of charge in kWh
            battery_capacity_kwh: Total battery capacity in kWh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.  When
                supplied and ``grid_charge_ctx.is_cheap_period`` is ``True``,
                the strategy will grid-charge the battery (via
                ``compute_grid_charge_power_kw``) provided the battery is not
                already being discharged to shave a peak.  ``None`` (default)
                means no grid charging: ``grid_charge_kw`` is always 0.

        Returns:
            DispatchDecision with:
            - charge_kw if excess PV available
            - discharge_kw to reduce grid import below threshold
            - grid_charge_kw when a cheap period is active and the battery is
              not shaving a peak: shaving takes precedence, so grid charging
              happens only on excess PV, a below-threshold shortfall or
              balanced load.

        Raises:
            ValueError: If inputs are invalid (negative values, etc.)
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )

        # Calculate excess and shortfall
        excess_kw = max(0.0, generation_kw - demand_kw)
        shortfall_kw = max(0.0, demand_kw - generation_kw)

        if excess_kw > 0:
            # Charge from excess PV
            charge_kw = excess_kw
            discharge_kw = 0.0
        elif shortfall_kw > 0:
            # Check if grid import would exceed threshold
            if shortfall_kw > self._import_limit_kw:
                # Discharge to shave peak: reduce import to threshold
                charge_kw = 0.0
                discharge_kw = shortfall_kw - self._import_limit_kw
            else:
                # Shortfall is below threshold, no battery action needed
                charge_kw = 0.0
                discharge_kw = 0.0
        else:
            # Generation exactly equals demand
            charge_kw = 0.0
            discharge_kw = 0.0

        # Grid-charge only while not shaving a peak, which takes precedence:
        # DispatchDecision forbids grid_charge_kw > 0 with discharge_kw > 0.
        # Passing charge_kw as pv_charge_power_kw shares max_charge_kw
        # between PV and grid.
        grid_charge_kw = 0.0
        if (
            grid_charge_ctx is not None
            and grid_charge_ctx.is_cheap_period
            and discharge_kw == 0.0
        ):
            grid_charge_kw = compute_grid_charge_power_kw(
                grid_charge_ctx,
                battery_soc_kwh=battery_soc_kwh,
                capacity_kwh=battery_capacity_kwh,
                pv_charge_power_kw=charge_kw,
                timestep_minutes=timestep_minutes,
            )

        return DispatchDecision(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            grid_charge_kw=grid_charge_kw,
        )


def build_dispatch_strategy(
    config: DispatchStrategyConfig,
    *,
    grid_charging: GridChargeConfig | None,
    tariff: TariffConfig | None,
) -> DispatchStrategy:
    """Build a new instance of the strategy config configures, for a battery whose grid-charge setting is grid_charging, in a home on tariff."""
    match config:
        case SelfConsumptionStrategyConfig():
            return SelfConsumptionStrategy()
        case TOUOptimizedStrategyConfig():
            return TOUOptimizedStrategy(list(config.peak_hours))
        case PeakShavingStrategyConfig():
            return PeakShavingStrategy(config.import_limit_kw)
        case _:
            assert_never(config)


_ONE_DAY = timedelta(days=1)


def _are_opening_days(days: object) -> bool:
    """Whether days is 'daily' or a non-empty frozenset of date.weekday() numbers, 0 to 6, none of them a bool."""
    if days == "daily":
        return True
    return (
        isinstance(days, frozenset)
        and len(days) > 0
        and all(isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6 for day in days)
    )


@dataclass(frozen=True)
class ChargeWindow:
    """One scheduled-charge slot, as on a Victron GX: while it is open, the battery is charged from the grid to its target.

    Attributes:
        days: The date.weekday() numbers (Monday 0 … Sunday 6) of the days it opens on, or
            'daily'. A window that crosses midnight stays open into the morning after.
        start: The wall-clock time it opens at, on its strategy's zone, so it has no tzinfo.
        duration: How long it stays open: more than nothing, and at most a day.
        target_soc_fraction: The state of charge it charges to, as a fraction of the battery
            capacity decide_action is given: greater than 0 and at most 1, held as the float
            read.
        allow_discharge: Whether the battery may discharge while it is open, down to the target.

    Raises:
        ConfigurationError: For a field it cannot schedule, naming the field and its value.
    """

    days: frozenset[int] | Literal["daily"]
    start: time
    duration: timedelta
    target_soc_fraction: float
    allow_discharge: bool

    def __post_init__(self) -> None:
        """Read target_soc_fraction as GridChargeConfig does, then refuse a field the window cannot schedule, naming the field and its value."""
        read_field(self, "target_soc_fraction", as_finite_float, _TARGET_SOC_FRACTION)
        if not _are_opening_days(self.days):
            raise ConfigurationError(
                "ChargeWindow's days are 'daily' or a non-empty frozenset of date.weekday() numbers, "
                f"0 to 6: got days={self.days!r}"
            )
        if self.start.tzinfo is not None:
            raise ConfigurationError(
                "ChargeWindow's start is a wall-clock time on its strategy's zone, so it has no tzinfo: "
                f"got start={self.start!r}"
            )
        if not timedelta(0) < self.duration <= _ONE_DAY:
            raise ConfigurationError(
                f"ChargeWindow's duration is more than 0 and at most a day: got duration={self.duration!r}"
            )

    def covers(self, moment: datetime) -> bool:
        """Whether the window is open at moment, a naive wall-clock time on its strategy's zone.

        It is open from start for duration on each day it opens on, so at most a day: the
        opening that covers moment is that day's or the day before's.
        """
        today = moment.date()
        openings = (datetime.combine(day, self.start) for day in (today, today - _ONE_DAY) if self._opens_on(day))
        return any(opens <= moment < opens + self.duration for opens in openings)

    def _opens_on(self, day: date) -> bool:
        """Whether the window opens on day."""
        return self.days == "daily" or day.weekday() in self.days


def _window_decision(
    window: ChargeWindow,
    *,
    generation_kw: float,
    demand_kw: float,
    battery_soc_kwh: float,
    battery_capacity_kwh: float,
    timestep_minutes: float,
    grid_charge_ctx: Optional[GridChargeContext],
) -> DispatchDecision:
    """The decision of a step inside window.

    Above the window's target, a window that allows discharge covers a shortfall from the
    battery, down to the target and no further. Otherwise the step charges its PV excess and,
    offered a grid-charge context, the grid power that charges the battery to the target,
    whatever the rates.
    """
    excess_kw = max(0.0, generation_kw - demand_kw)
    shortfall_kw = max(0.0, demand_kw - generation_kw)
    target_kwh = window.target_soc_fraction * battery_capacity_kwh
    if window.allow_discharge and shortfall_kw > 0.0 and battery_soc_kwh > target_kwh:
        down_to_target_kw = (battery_soc_kwh - target_kwh) / (timestep_minutes * HOURS_PER_MINUTE)
        return DispatchDecision(charge_kw=0.0, discharge_kw=min(shortfall_kw, down_to_target_kw))
    grid_charge_kw = (
        0.0
        if grid_charge_ctx is None
        else _grid_power_to_target_kw(
            grid_charge_ctx,
            target_kwh=target_kwh,
            battery_soc_kwh=battery_soc_kwh,
            pv_charge_kw=excess_kw,
            timestep_minutes=timestep_minutes,
        )
    )
    return DispatchDecision(charge_kw=excess_kw, discharge_kw=0.0, grid_charge_kw=grid_charge_kw)


class ScheduledChargeStrategy(DispatchStrategy):
    """In each window it force-charges the battery from the grid to the window's target and then holds it, and outside every window its base decides.

    docs/scheduled-charge-windows.md gives the rules and the year harness that bills them.
    """

    def __init__(self, base: DispatchStrategy, windows: tuple[ChargeWindow, ...], tz: ZoneInfo) -> None:
        """Wrap base in windows read on tz's wall clock: the first listed window open at a step decides it.

        Raises:
            ConfigurationError: If tz is not a ZoneInfo, naming it.
        """
        if not isinstance(tz, ZoneInfo):
            raise ConfigurationError(
                "ScheduledChargeStrategy's tz is the ZoneInfo on whose wall clock its windows open: "
                f"got tz={tz!r}"
            )
        self._base = base
        self._windows = tuple(windows)
        self._tz = tz

    @property
    def name(self) -> str:
        """Return strategy name: its base's, wrapped."""
        return f"scheduled_charge({self._base.name})"

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Decide the step: the first listed window open at timestamp decides it, else the base does, given every argument unchanged.

        Raises:
            ValueError: If an input is out of the range the sibling strategies refuse, or
                timestamp is naive, so it has no wall-clock time on tz.
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )
        window = self._window_at(timestamp)
        if window is None:
            return self._base.decide_action(
                timestamp=timestamp,
                generation_kw=generation_kw,
                demand_kw=demand_kw,
                battery_soc_kwh=battery_soc_kwh,
                battery_capacity_kwh=battery_capacity_kwh,
                timestep_minutes=timestep_minutes,
                grid_charge_ctx=grid_charge_ctx,
            )
        return _window_decision(
            window,
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery_soc_kwh=battery_soc_kwh,
            battery_capacity_kwh=battery_capacity_kwh,
            timestep_minutes=timestep_minutes,
            grid_charge_ctx=grid_charge_ctx,
        )

    def _window_at(self, timestamp: datetime) -> Optional[ChargeWindow]:
        """The first listed window open at timestamp, read on tz's wall clock, or None."""
        if timestamp.utcoffset() is None:
            raise ValueError(
                f"ScheduledChargeStrategy reads each timestamp on {self._tz.key}'s wall clock, "
                f"so it refuses a naive one: got {timestamp!r}"
            )
        wall_clock = timestamp.astimezone(self._tz).replace(tzinfo=None)
        return next((window for window in self._windows if window.covers(wall_clock)), None)
