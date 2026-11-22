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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time, timedelta
from enum import Enum
from types import MappingProxyType
from typing import ClassVar, Final, List, Literal, Optional, Tuple, TypeAlias, assert_never, get_args
from zoneinfo import ZoneInfo

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    Interval,
    as_finite_float,
    as_whole_numbers,
    read_field,
)
from solar_challenge.tariff import TariffConfig, describe_minutes_of_day
from solar_challenge.timebase import HOURS_PER_MINUTE, MINUTES_PER_HOUR, require_valid_duration


@dataclass(frozen=True)
class DispatchDecision:
    """Decision from a dispatch strategy for a single timestep.

    Attributes:
        charge_kw: Requested battery charging power in kW, finite and at least 0.
            Represents PV or other on-site charge power.
        discharge_kw: Requested battery discharge power in kW, finite and at least 0.
        grid_charge_kw: Requested grid-to-battery charging power in kW, finite and
            at least 0 (default 0.0). Represents deliberate charging from
            the grid (e.g. during cheap-rate periods). May co-exist with
            charge_kw > 0 (both are charging), but is mutually exclusive with
            discharge_kw > 0.

    Raises:
        ValueError: If a power is negative, NaN or infinite, naming it and its value; or if
            discharge_kw > 0 alongside charge_kw > 0 or grid_charge_kw > 0.
    """

    charge_kw: float
    discharge_kw: float
    grid_charge_kw: float = 0.0

    def __post_init__(self) -> None:
        """Refuse a power NON_NEGATIVE does not admit, then a discharge alongside either charge."""
        for name in _DECISION_POWERS:
            if not NON_NEGATIVE.admits(value := getattr(self, name)):
                raise ValueError(f"{name} must be non-negative and finite, got {value!r} kW")
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


_DECISION_POWERS: Final = tuple(power.name for power in fields(DispatchDecision))


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
        target_soc_kwh: The SOC in kWh that grid charging fills the battery
            to in cheap periods; the engine sets it from
            Battery.grid_charge_target_kwh, a fraction of effective capacity
            capped at max_soc_kwh
        max_charge_kw: Maximum charge power in kW (hardware C-rate limit of
            the battery/inverter), shared by PV and grid charging; the engine
            sets it from Battery.max_charge_kw
        round_trip_efficiency: Round-trip charge/discharge efficiency in
            (0, 1], used in the spread gate calculation
        charge_efficiency: One-way charge efficiency in (0, 1], used to
            account for losses when computing how much grid power is needed
            to reach the target SOC
    """

    current_rate: float
    peak_rate: float
    is_cheap_period: bool
    target_soc_kwh: float
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
        battery_soc_kwh: The battery's state of charge in kWh before this
            step's PV charge.
        pv_charge_power_kw: The PV charge power in kW the step offers the
            battery ahead of grid charging. The controller predicts the SOC
            after it as ``Battery.charge`` stores it, ``battery_soc_kwh +
            min(pv_charge_power_kw, ctx.max_charge_kw) × dt_h ×
            ctx.charge_efficiency``, and it shares ``ctx.max_charge_kw`` with
            the grid power.
        timestep_minutes: Duration of the timestep in minutes. Must be
            positive and finite (raises ``ValueError`` if not).

    Returns:
        Recommended grid-to-battery charge power in kW: at least 0.0 and at
        most the headroom ``ctx.max_charge_kw - min(pv_charge_power_kw,
        ctx.max_charge_kw)``. It is 0.0 when the period is not cheap
        (ctx.is_cheap_period is False), when the spread gate fails (peak
        saving does not cover round-trip losses), or when the predicted
        post-PV SOC is at or above ``ctx.target_soc_kwh``. The engine's
        target, ``Battery.grid_charge_target_kwh``, is at most
        ``max_soc_kwh``, so a prediction past the battery's ceiling also
        gives 0.0. A step that grid-charges therefore ends at or below the
        target.

    Raises:
        ValueError: If ``timestep_minutes`` is not positive and finite.
    """
    require_valid_duration(timestep_minutes, "timestep_minutes")

    # Gate 1: only charge from grid during cheap periods
    if not ctx.is_cheap_period:
        return 0.0

    # Gate 2: spread gate — only profitable if selling at peak_rate covers
    # the round-trip energy loss when charging at current_rate.
    # Break-even condition: peak_rate > current_rate / round_trip_efficiency
    if ctx.peak_rate <= ctx.current_rate / ctx.round_trip_efficiency:
        return 0.0

    # Gate 3: how much the battery still needs after this step's PV charge
    return _grid_power_to_target_kw(
        ctx,
        target_kwh=ctx.target_soc_kwh,
        battery_soc_kwh=battery_soc_kwh,
        pv_charge_kw=pv_charge_power_kw,
        timestep_minutes=timestep_minutes,
    )


def _grid_charge_kw(
    ctx: GridChargeContext | None,
    *,
    battery_soc_kwh: float,
    charge_kw: float,
    discharge_kw: float,
    timestep_minutes: float,
) -> float:
    """The grid-charge power a decision of charge_kw PV charge and discharge_kw discharge asks for: none without a context or while it discharges, which DispatchDecision forbids alongside grid charging; else compute_grid_charge_power_kw's, with charge_kw as the step's PV charge."""
    if ctx is None or discharge_kw > 0.0:
        return 0.0
    return compute_grid_charge_power_kw(
        ctx,
        battery_soc_kwh=battery_soc_kwh,
        pv_charge_power_kw=charge_kw,
        timestep_minutes=timestep_minutes,
    )


def _charge_headroom_kw(max_charge_kw: float, charge_kw: float) -> float:
    """The max_charge_kw a step's charge_kw of PV charge leaves for grid charging."""
    return max(0.0, max_charge_kw - min(charge_kw, max_charge_kw))


def _step_excess_kw(generation_kw: float, demand_kw: float) -> float:
    """A step's PV excess in kW: its generation beyond its demand, or 0."""
    return max(0.0, generation_kw - demand_kw)


def _step_shortfall_kw(generation_kw: float, demand_kw: float) -> float:
    """A step's shortfall in kW: its demand beyond its generation, or 0."""
    return max(0.0, demand_kw - generation_kw)


@dataclass(frozen=True)
class StepLimits:
    """What one step's decision may ask of the battery, in kW.

    Attributes:
        excess_kw: PV beyond demand, the most charge_kw may take.
        shortfall_kw: Demand beyond PV, the most discharge_kw may give.
        max_charge_kw: The battery's charge limit, which PV and grid charging share.
    """

    excess_kw: float
    shortfall_kw: float
    max_charge_kw: float

    @classmethod
    def for_step(cls, generation_kw: float, demand_kw: float, *, max_charge_kw: float) -> "StepLimits":
        """The limits of a step at generation_kw and demand_kw, for a battery whose charge limit is max_charge_kw.

        Its excess and shortfall are those the built-in strategies decide from, so a decision that asks
        for all of either is within its limit to the last bit.
        """
        return cls(
            excess_kw=_step_excess_kw(generation_kw, demand_kw),
            shortfall_kw=_step_shortfall_kw(generation_kw, demand_kw),
            max_charge_kw=max_charge_kw,
        )

    def require_admissible(self, decision: DispatchDecision, strategy_name: str) -> None:
        """Refuse *decision*, by the strategy named *strategy_name*, if a power is above its limit.

        A charge_kw above max_charge_kw is admissible: it is a PV offer the battery clamps,
        and the grid charge's limit is the headroom left after the clamped offer.

        Raises:
            ValueError: Naming the strategy and, for each power above its limit, the field,
                its value and its limit.
        """
        bounds = (
            ("charge_kw", decision.charge_kw, self.excess_kw, "the step's PV excess"),
            ("discharge_kw", decision.discharge_kw, self.shortfall_kw, "the step's shortfall"),
            (
                "grid_charge_kw",
                decision.grid_charge_kw,
                _charge_headroom_kw(self.max_charge_kw, decision.charge_kw),
                "the charge limit's headroom after charge_kw",
            ),
        )
        breaches = [
            f"{name}={value!r} kW is above {limit!r} kW, {what}"
            for name, value, limit, what in bounds
            if not value <= limit
        ]
        if breaches:
            raise ValueError(
                f"Dispatch strategy {strategy_name!r} decided more than the step allows: " + "; ".join(breaches)
            )


def _grid_power_to_target_kw(
    ctx: GridChargeContext,
    *,
    target_kwh: float,
    battery_soc_kwh: float,
    pv_charge_kw: float,
    timestep_minutes: float,
) -> float:
    """The grid power that charges the battery to target_kwh this step, after its pv_charge_kw of PV charge, within the headroom that charge leaves.

    It predicts the SOC after the PV charge as Battery.charge stores it, and draws the gap
    from there to target_kwh, divided by charge_efficiency, from the grid; it asks for
    nothing once that SOC reaches target_kwh.
    """
    dt_h = timestep_minutes * HOURS_PER_MINUTE
    soc_after_pv_kwh = battery_soc_kwh + min(pv_charge_kw, ctx.max_charge_kw) * dt_h * ctx.charge_efficiency
    gap_kwh = target_kwh - soc_after_pv_kwh
    if not gap_kwh > 0.0:
        return 0.0
    return min(gap_kwh / ctx.charge_efficiency / dt_h, _charge_headroom_kw(ctx.max_charge_kw, pv_charge_kw))


TARGET_SOC_FRACTION: Final = FRACTION
"""The grid-charge targets a battery may be given, as fractions of its effective (SOH-derated) capacity: greater than 0 and at most 1."""

GridChargeForecast: TypeAlias = Literal["pv_blind", "trailing_14_days", "perfect_foresight"]
"""The forecasts that may size a battery's grid charge in cheap periods; GridChargeConfig.forecast says what each does."""

GRID_CHARGE_FORECASTS: Final = get_args(GridChargeForecast)
"""Every GridChargeForecast, in its declared order."""


def _refuse_unknown_forecast(forecast: object) -> None:
    """Raise ConfigurationError, naming forecast, the value and every GRID_CHARGE_FORECASTS name, unless forecast is one of them."""
    if not (isinstance(forecast, str) and forecast in GRID_CHARGE_FORECASTS):
        raise ConfigurationError.must_be(
            "forecast", f"one of {', '.join(map(repr, GRID_CHARGE_FORECASTS))}", got=forecast
        )


@dataclass(frozen=True)
class GridChargeConfig:
    """Configuration for grid-charging (battery arbitrage) mode.

    Attributes:
        target_soc_fraction: Target state-of-charge to reach via grid charging,
            expressed as a fraction of the battery's effective (SOH-derated) capacity,
            the basis of Battery.soc_fraction: a finite number greater than 0 and at
            most 1, held as the float read. Defaults to 0.9. A target above the
            battery's max_soc_fraction charges it to max_soc_kwh
            (Battery.grid_charge_target_kwh).
        forecast: What sizes a cheap period's grid charge, one of GRID_CHARGE_FORECASTS;
            defaults to 'pv_blind'. 'pv_blind' fills to the target whatever PV the day
            brings. 'trailing_14_days' caps the fill at the forecast useful-charge
            ceiling, the charge the PV after it is not forecast to strand
            (docs/grid-charge-forecast.md). 'perfect_foresight' is an upper-bound
            analysis mode: it reads the run's own future PV and demand, and is never
            used for board figures.

    Raises:
        ConfigurationError: If target_soc_fraction is a bool, is not a finite number, or
            is outside that range, naming target_soc_fraction and the value; or if
            forecast is not one of GRID_CHARGE_FORECASTS, naming forecast, the value and
            every forecast.
    """

    target_soc_fraction: float = 0.9
    forecast: GridChargeForecast = "pv_blind"

    def __post_init__(self) -> None:
        """Read target_soc_fraction, and hold the float read; refuse a forecast outside GRID_CHARGE_FORECASTS."""
        read_field(self, "target_soc_fraction", as_finite_float, TARGET_SOC_FRACTION)
        _refuse_unknown_forecast(self.forecast)


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
        raise ConfigurationError.must_be(field, "a (start, end) window that starts before it ends", got=value)
    return (hours[0], hours[1])


def _as_hour_windows(value: object, field: str, within: Interval) -> tuple[tuple[int, int], ...]:
    """Return *value*, a list of at least one window, as the tuple of its windows, each read by _as_hour_window as {field}[{i}].

    Raises:
        ConfigurationError: If *value* is not a list or tuple, or is empty, naming *field*;
            or if _as_hour_window refuses a window.
    """
    if not isinstance(value, (list, tuple)):
        raise ConfigurationError.must_be(field, "a list of (start, end) windows", got=value)
    if not value:
        raise ConfigurationError(f"{field} must hold at least one (start, end) window; it is empty")
    return tuple(_as_hour_window(window, f"{field}[{index}]", within) for index, window in enumerate(value))


_TouClock: TypeAlias = TariffConfig | tuple[tuple[int, int], ...]
"""What a TOUOptimizedStrategy tells its peak minutes by: its peak windows, read by _as_hour_windows, or the tariff, each of whose minutes that is not cheap is peak."""


def _tou_clock(peak_hours: Sequence[object] | None, tariff: TariffConfig | None) -> _TouClock:
    """The clock of a TOUOptimizedStrategy given peak_hours and tariff: the windows of peak_hours, checked against tariff when there is one; else tariff.

    Raises:
        ConfigurationError: If peak_hours and tariff are both None; if _as_hour_windows refuses
            peak_hours; or if a window reaches a cheap minute of tariff.
    """
    if peak_hours is None:
        if tariff is None:
            raise ConfigurationError(
                "dispatch strategy 'tou_optimized' without peak_hours charges and discharges the battery on the "
                "tariff's clock, but there is no tariff; add a tariff or set peak_hours"
            )
        return tariff
    windows = _as_hour_windows(peak_hours, "peak_hours", _PEAK_WINDOW_HOURS)
    if tariff is not None:
        _refuse_peak_hours_in_cheap_minutes(peak_hours, windows, tariff)
    return windows


def _refuse_peak_hours_in_cheap_minutes(
    peak_hours: Sequence[object], windows: tuple[tuple[int, int], ...], tariff: TariffConfig
) -> None:
    """Refuse peak_hours, read as windows, if a window reaches a minute tariff prices cheap: a peak hour is when the battery discharges.

    Raises:
        ConfigurationError: Naming each window that does as peak_hours[i] and the window given,
            the cheap clock ranges it reaches, and the tariff.
    """
    cheap_by_window = {index: _cheap_minutes_in(window, tariff) for index, window in enumerate(windows)}
    reaches = [
        f"peak_hours[{index}] {peak_hours[index]!r} reaches {describe_minutes_of_day(cheap)}"
        for index, cheap in cheap_by_window.items()
        if cheap
    ]
    if reaches:
        raise ConfigurationError(
            "dispatch strategy 'tou_optimized' discharges the battery in its peak hours, so none may fall in a "
            f"cheap period of {_tariff_label(tariff)}, but {' and '.join(reaches)}; remove peak_hours to discharge "
            "on the tariff's clock, or narrow the window to the tariff's expensive minutes"
        )


def _cheap_minutes_in(window: tuple[int, int], tariff: TariffConfig) -> frozenset[int]:
    """The minutes of the day in window, a (start, end) pair of whole hours, that tariff prices cheap."""
    start, end = window
    return frozenset(range(start * MINUTES_PER_HOUR, end * MINUTES_PER_HOUR)) & tariff.cheap_minutes_of_day


def _tariff_label(tariff: TariffConfig) -> str:
    """The tariff as a refusal names it: tariff and its quoted name, when it has one, else the tariff."""
    return f"tariff {tariff.name!r}" if tariff.name else "the tariff"


_IMPORT_LIMIT_KW = POSITIVE
"""The grid import limits, in kW, that PeakShavingStrategyConfig and PeakShavingStrategy admit."""


@dataclass(frozen=True)
class SelfConsumptionStrategyConfig:
    """The configuration of a SelfConsumptionStrategy, which has no setting."""

    strategy_type: Literal["self_consumption"] = field(default="self_consumption", init=False)
    _charges_from_the_grid: ClassVar[bool] = False


@dataclass(frozen=True)
class TOUOptimizedStrategyConfig:
    """The configuration of a TOUOptimizedStrategy.

    Attributes:
        peak_hours: The (start, end) hours of the peak periods the strategy discharges the
            battery in: a list of at least one window, each a pair of whole hours from 0 to
            24 that starts before it ends, held as a tuple of int pairs. None, the default,
            is the tariff's clock: the strategy discharges in the home tariff's expensive
            minutes and grid-charges in its cheap ones. A set peak_hours narrows discharge,
            and the strategy checks it against the home's tariff when it is built.

    Raises:
        ConfigurationError: With the refusal TOUOptimizedStrategy gives, if peak_hours is
            not None and not a list of at least one window; if an hour is a bool, is not a
            finite whole number, or is outside 0 to 24, naming it peak_hours[i][j] and the
            value; or if a window is not a (start, end) pair that starts before it ends,
            naming it peak_hours[i] and the window.
    """

    peak_hours: tuple[tuple[int, int], ...] | None = None
    strategy_type: Literal["tou_optimized"] = field(default="tou_optimized", init=False)
    _charges_from_the_grid: ClassVar[bool] = True

    def __post_init__(self) -> None:
        """Read a set peak_hours as TOUOptimizedStrategy does, and hold the int pairs read."""
        read_field(self, "peak_hours", _as_hour_windows, _PEAK_WINDOW_HOURS, optional=True)


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
    _charges_from_the_grid: ClassVar[bool] = True

    def __post_init__(self) -> None:
        """Read import_limit_kw as PeakShavingStrategy does, and hold the float read."""
        read_field(self, "import_limit_kw", as_finite_float, _IMPORT_LIMIT_KW)


DispatchStrategyConfig: TypeAlias = (
    SelfConsumptionStrategyConfig | TOUOptimizedStrategyConfig | PeakShavingStrategyConfig
)
"""The configuration of a battery's dispatch strategy: one variant per strategy.

A variant's strategy_type, which its constructor does not take, is its tag: the name of the
strategy it configures, and the strategy_type key of the block the scenario grammar reads it from.
Its _charges_from_the_grid, a ClassVar, says whether the strategy it configures charges the
battery from the grid in a cheap period of the tariff; build_dispatch_strategy refuses
grid_charging under a variant that does not, naming each variant that does.
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
            battery_capacity_kwh: The battery's effective (SOH-derated) capacity in kWh, the
                basis of its SOC fractions, which simulate_timestep passes as
                Battery.effective_capacity_kwh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.
                A strategy that grid-charges passes it to
                ``compute_grid_charge_power_kw`` to fill ``grid_charge_kw``,
                and only when it is not discharging, because
                ``DispatchDecision`` forbids ``grid_charge_kw > 0`` together
                with ``discharge_kw > 0``.  A strategy that does not
                grid-charge ignores it.  ``None`` means no grid charging.

        Returns:
            DispatchDecision specifying charge_kw or discharge_kw, and any grid_charge_kw,
            within the step's bounds:
            - each power is finite and at least 0, as DispatchDecision requires;
            - charge_kw is at most the step's PV excess, max(0, generation_kw - demand_kw); it
              may exceed the battery's charge limit, Battery.max_charge_kw, which the battery
              applies;
            - discharge_kw is at most the step's shortfall, max(0, demand_kw - generation_kw);
            - grid_charge_kw is at most the headroom the charge limit leaves after charge_kw.
            simulate_timestep refuses a decision that breaks a bound with ValueError before the
            battery moves; see StepLimits.for_step.

        Raises:
            ValueError: If inputs are invalid (negative, NaN or infinite values, etc.)
        """
        pass


def require_valid_step_powers(generation_kw: float, demand_kw: float) -> None:
    """Refuse a step's generation or demand power unless NON_NEGATIVE admits it: finite and at least 0.

    Raises:
        ValueError: Naming the power and its value.
    """
    if not NON_NEGATIVE.admits(generation_kw):
        raise ValueError(f"Generation must be non-negative and finite, got {generation_kw} kW")
    if not NON_NEGATIVE.admits(demand_kw):
        raise ValueError(f"Demand must be non-negative and finite, got {demand_kw} kW")


def _require_valid_strategy_inputs(
    generation_kw: float,
    demand_kw: float,
    battery_soc_kwh: float,
    battery_capacity_kwh: float,
    timestep_minutes: float,
) -> None:
    """Refuse a decide_action input out of its range: a power or SOC that is negative, NaN or infinite, or a capacity or timestep that is not positive and finite.

    Raises:
        ValueError: Naming the input, its bound and its value.
    """
    require_valid_step_powers(generation_kw, demand_kw)
    if not NON_NEGATIVE.admits(battery_soc_kwh):
        raise ValueError(f"Battery SOC must be non-negative and finite, got {battery_soc_kwh} kWh")
    if not POSITIVE.admits(battery_capacity_kwh):
        raise ValueError(f"Battery capacity must be positive and finite, got {battery_capacity_kwh} kWh")
    require_valid_duration(timestep_minutes, "Timestep")


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
            battery_capacity_kwh: The battery's effective (SOH-derated) capacity in kWh, the
                basis of its SOC fractions, which simulate_timestep passes as
                Battery.effective_capacity_kwh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context
                (accepted but not used in this strategy).

        Returns:
            DispatchDecision with charge_kw if excess PV available,
            discharge_kw if demand exceeds generation, or both zero if
            generation equals demand

        Raises:
            ValueError: If generation, demand or SOC is negative, NaN or infinite, or the
                capacity or timestep is not positive and finite.
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )

        excess_kw = _step_excess_kw(generation_kw, demand_kw)
        shortfall_kw = _step_shortfall_kw(generation_kw, demand_kw)

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

    Its peak hours are its peak_hours windows or, without them, the tariff's clock: each
    minute the tariff does not price cheap (TariffConfig.is_cheap_at) is a peak minute.

    This strategy is designed for scenarios with time-of-use tariffs where
    electricity costs vary by time of day.
    """

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "tou_optimized"

    def __init__(
        self, peak_hours: List[Tuple[int, int]] | None = None, *, tariff: TariffConfig | None = None
    ) -> None:
        """Initialize TOU-optimized strategy with its peak windows, or the tariff on whose clock it dispatches.

        Args:
            peak_hours: List of (start_hour, end_hour) windows defining peak periods: at
                least one, each a pair of whole hours from 0 to 24 that starts before it
                ends, held as a tuple of int pairs. For example, [(17, 20)] represents
                peak period from 5 PM to 8 PM. Every hour outside these ranges is off-peak.
                None, the default, dispatches on the tariff's clock instead.
            tariff: The tariff the strategy's battery is charged at. Without peak_hours it is
                the strategy's clock; with them it only checks them, and the strategy does
                not hold it. None, the default, leaves peak_hours unchecked.

        Raises:
            ConfigurationError: If peak_hours and tariff are both None, naming tou_optimized,
                the tariff's clock and the missing tariff. If peak_hours is not a list of at
                least one window; if an hour is a bool, is not a finite whole number, or is
                outside 0 to 24, naming it peak_hours[i][j] and the value; or if a window is
                not a (start, end) pair that starts before it ends, naming it peak_hours[i] and
                the window. Then, with a tariff, if a window reaches a minute it prices cheap:
                one refusal naming each such window as peak_hours[i] and the window given, the
                cheap clock ranges it reaches and the tariff, by its name when it has one.
        """
        self._clock = _tou_clock(peak_hours, tariff)

    def _get_tariff_period(self, timestamp: datetime) -> TariffPeriod:
        """Determine tariff period for given timestamp.

        Args:
            timestamp: Timestamp to check

        Returns:
            On the tariff's clock, TariffPeriod.OFF_PEAK if the tariff prices the timestamp's
            minute cheap, TariffPeriod.PEAK otherwise; with peak windows, TariffPeriod.PEAK if
            its hour falls within one, TariffPeriod.OFF_PEAK otherwise
        """
        clock = self._clock
        if isinstance(clock, TariffConfig):
            return TariffPeriod.OFF_PEAK if clock.is_cheap_at(timestamp) else TariffPeriod.PEAK
        hour = timestamp.hour
        if any(start <= hour < end for start, end in clock):
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
            battery_capacity_kwh: The battery's effective (SOH-derated) capacity in kWh, the
                basis of its SOC fractions, which simulate_timestep passes as
                Battery.effective_capacity_kwh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.  When
                supplied, the strategy grid-charges in a cheap period by the
                power ``compute_grid_charge_power_kw`` gives for
                ``battery_soc_kwh`` with the step's PV charge, ``charge_kw``,
                stored first, so a step that grid-charges ends at or below
                ``grid_charge_ctx.target_soc_kwh``.  It asks for none while
                the decision discharges.  When the strategy was built with
                the step's tariff, no minute is both PEAK and cheap, so it
                never discharges while ``grid_charge_ctx.is_cheap_period``
                is true.
                ``None`` (default) means no grid charging: ``grid_charge_kw``
                is always 0.

        Returns:
            DispatchDecision optimized for TOU tariffs:
            - Off-peak: charge from excess PV; also grid-charges when a
              favourable GridChargeContext is provided.
            - Peak: discharge to meet demand, still charge from excess PV;
              grid-charging is suppressed when discharging.

        Raises:
            ValueError: If generation, demand or SOC is negative, NaN or infinite, or the
                capacity or timestep is not positive and finite.
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )

        # Determine current tariff period
        tariff_period = self._get_tariff_period(timestamp)

        excess_kw = _step_excess_kw(generation_kw, demand_kw)
        shortfall_kw = _step_shortfall_kw(generation_kw, demand_kw)

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

        return DispatchDecision(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            grid_charge_kw=_grid_charge_kw(
                grid_charge_ctx,
                battery_soc_kwh=battery_soc_kwh,
                charge_kw=charge_kw,
                discharge_kw=discharge_kw,
                timestep_minutes=timestep_minutes,
            ),
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
            battery_capacity_kwh: The battery's effective (SOH-derated) capacity in kWh, the
                basis of its SOC fractions, which simulate_timestep passes as
                Battery.effective_capacity_kwh
            timestep_minutes: Duration of timestep in minutes
            grid_charge_ctx: Optional rate-aware grid-charging context.  When
                supplied, the strategy grid-charges in a cheap period by the
                power ``compute_grid_charge_power_kw`` gives for
                ``battery_soc_kwh`` with the step's PV charge, ``charge_kw``,
                stored first, so a step that grid-charges ends at or below
                ``grid_charge_ctx.target_soc_kwh``.  It asks for none while
                the decision discharges to shave a peak: shaving takes
                precedence.  ``None`` (default) means no grid charging:
                ``grid_charge_kw`` is always 0.

        Returns:
            DispatchDecision with:
            - charge_kw if excess PV available
            - discharge_kw to reduce grid import below threshold
            - grid_charge_kw when a cheap period is active and the battery is
              not shaving a peak: shaving takes precedence, so grid charging
              happens only on excess PV, a below-threshold shortfall or
              balanced load.

        Raises:
            ValueError: If generation, demand or SOC is negative, NaN or infinite, or the
                capacity or timestep is not positive and finite.
        """
        _require_valid_strategy_inputs(
            generation_kw, demand_kw, battery_soc_kwh, battery_capacity_kwh, timestep_minutes
        )

        excess_kw = _step_excess_kw(generation_kw, demand_kw)
        shortfall_kw = _step_shortfall_kw(generation_kw, demand_kw)

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

        return DispatchDecision(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            grid_charge_kw=_grid_charge_kw(
                grid_charge_ctx,
                battery_soc_kwh=battery_soc_kwh,
                charge_kw=charge_kw,
                discharge_kw=discharge_kw,
                timestep_minutes=timestep_minutes,
            ),
        )


def build_dispatch_strategy(
    config: DispatchStrategyConfig,
    *,
    grid_charging: GridChargeConfig | None,
    tariff: TariffConfig | None,
) -> DispatchStrategy:
    """Build a new instance of the strategy config configures, for a battery whose grid-charge setting is grid_charging, in a home on tariff.

    Raises:
        ConfigurationError: The strategy's constructor refuses the variant at tariff: a
            tou_optimized variant with no peak_hours and no tariff, or with peak_hours that
            reach a cheap minute of tariff. Then grid_charging is set, but the strategy would
            ignore it: its variant does not charge from the grid, there is no tariff to find a
            cheap period in, or the tariff has no cheap period.
    """
    strategy: DispatchStrategy
    match config:
        case SelfConsumptionStrategyConfig():
            strategy = SelfConsumptionStrategy()
        case TOUOptimizedStrategyConfig():
            strategy = TOUOptimizedStrategy(
                None if config.peak_hours is None else list(config.peak_hours), tariff=tariff
            )
        case PeakShavingStrategyConfig():
            strategy = PeakShavingStrategy(config.import_limit_kw)
        case _:
            assert_never(config)
    if grid_charging is not None:
        _refuse_grid_charging_it_would_ignore(config, tariff)
    return strategy


def _refuse_grid_charging_it_would_ignore(config: DispatchStrategyConfig, tariff: TariffConfig | None) -> None:
    """Refuse a battery's grid_charging under dispatch strategy *config*, unless its variant charges from the grid and there is a tariff with a cheap minute to charge in.

    Raises:
        ConfigurationError: The variant does not charge from the grid, or there is no tariff;
            the message names grid_charging, the strategy and what to change. The first
            message names, as the strategy to use instead, each variant that charges from
            the grid. Otherwise _require_cheap_minutes_for_grid_charging's refusal of a tariff
            with no cheap minute.
    """
    tag = config.strategy_type
    if not config._charges_from_the_grid:
        grid_charging_tags = [each_tag for each_tag, variant in STRATEGY_CONFIG_BY_TYPE.items() if variant._charges_from_the_grid]
        raise ConfigurationError(
            f"grid_charging is set, but dispatch strategy {tag!r} does not charge from the grid; "
            f"remove grid_charging, or use {' or '.join(grid_charging_tags)}"
        )
    if tariff is None:
        raise ConfigurationError(
            f"grid_charging is set, but there is no tariff, so dispatch strategy {tag!r} has no cheap period "
            "to charge in; add a tariff or remove grid_charging"
        )
    _require_cheap_minutes_for_grid_charging(tag, tariff)


def _require_cheap_minutes_for_grid_charging(tag: str, tariff: TariffConfig) -> None:
    """Refuse grid_charging under dispatch strategy *tag* when *tariff* has no cheap minute to charge in.

    _refuse_grid_charging_it_would_ignore calls it once it has established that grid_charging
    is set, that variant *tag* charges from the grid and that there is a tariff, so a variant
    that does not grid-charge, or a home with no tariff, is told that instead.

    Raises:
        ConfigurationError: tariff's cheap_minutes_of_day is empty, naming grid_charging, the
            tariff, the strategy and what to change.
    """
    if tariff.cheap_minutes_of_day:
        return
    raise ConfigurationError(
        f"grid_charging is set, but {_tariff_label(tariff)} has no cheap period, so dispatch strategy {tag!r} "
        "never charges from the grid; remove grid_charging or use a time-of-use tariff"
    )


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
        read_field(self, "target_soc_fraction", as_finite_float, TARGET_SOC_FRACTION)
        if not _are_opening_days(self.days):
            raise ConfigurationError.must_be(
                "days", "'daily' or a non-empty frozenset of date.weekday() numbers from 0 to 6", got=self.days
            )
        if self.start.tzinfo is not None:
            raise ConfigurationError.must_be(
                "start", "a wall-clock time on its strategy's zone, with no tzinfo", got=self.start
            )
        if not timedelta(0) < self.duration <= _ONE_DAY:
            raise ConfigurationError.must_be("duration", "more than 0 and at most a day", got=self.duration)

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
    excess_kw = _step_excess_kw(generation_kw, demand_kw)
    shortfall_kw = _step_shortfall_kw(generation_kw, demand_kw)
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
            raise ConfigurationError.must_be("tz", "the ZoneInfo on whose wall clock its windows open", got=tz)
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
