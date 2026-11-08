# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grid-services event-window model for domestic battery capacity-at-events pricing.

Encodes the event-window scheduling and banded-rate decomposition for the
capacity-at-events grid-services pricing model introduced in the enhanced
grid-services PRD (docs/prds/enhanced-grid-services-capacity-at-events.md).

Key public symbols:

* :class:`EventWindow` — frozen dataclass describing *when* grid-service events
  can occur (months, weekdays, hours), with a :meth:`~EventWindow.mask` helper
  that returns a boolean :class:`pandas.Series` selecting in-window timesteps.
* :class:`GridServicesBand` — the one low / central / high uncertainty-band
  vocabulary, whose :meth:`~GridServicesBand.parse` refuses any other value.
* :class:`DeliveryBaseline` — the one operational / capacity delivery-baseline
  vocabulary, whose :meth:`~DeliveryBaseline.parse` refuses any other value.
* :class:`GridServicesRateBand` — frozen dataclass holding per-event availability
  and utilisation rates, and a flat rate per kW of battery discharge power per
  year, for one uncertainty band.
* :class:`GridServicesRateBands` — frozen container for the three canonical
  (low / central / high) bands with a :meth:`~GridServicesRateBands.resolve`
  helper.
* :data:`GRID_SERVICES_RATE_BANDS` — module-level constant holding every
  grid-services rate per band.
* :func:`resolve_grid_services_rate_band` — convenience helper delegating to
  the module constant.
* :data:`DEFAULT_EVENT_WINDOWS` — default winter-weekday-16:00-19:00 schedule
  per PRD open-Q4.
* :class:`GridServicesEventsConfig` — frozen dataclass combining band selection,
  event windows, aggregator share, and utilisation factor; its
  :meth:`~GridServicesEventsConfig.annual_income_gbp` prices a simulated fleet.
* :class:`NoGridServices` — frozen pricing value under which a fleet earns no
  grid-services income.
* :class:`FlatGridServices` — frozen pricing value paying a flat rate per kW of
  installed battery discharge power per year.
* :data:`GridServicesModel` — the union of the three pricing values, each of
  which prices a simulated fleet with ``annual_income_gbp(fleet_results)``.
* :func:`compute_fleet_spare_capacity_kw` — per event window, the mean over
  event days of the fleet's daily firm spare dispatchable battery capacity (kW),
  under a named delivery baseline.
* :class:`GridServicesAtEvents` — frozen dataclass holding the banded
  availability + utilisation income breakdown returned by
  :func:`compute_grid_services_at_events`.
* :func:`compute_grid_services_at_events` — applies the banded availability +
  utilisation pricing formula per event window, returning a
  :class:`GridServicesAtEvents` breakdown.
"""

import warnings
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, TypeAlias, TypeVar

import numpy as np
import numpy.typing as npt
import pandas as pd

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    Interval,
    as_finite_float,
    as_whole_number,
    as_whole_numbers,
    read_field,
)

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults
    from solar_challenge.home import SimulationResults


# ---------------------------------------------------------------------------
# GridServicesBand + DeliveryBaseline: the word-valued fields' vocabularies
# ---------------------------------------------------------------------------


_Word = TypeVar("_Word", bound=Enum)


def _member_named(vocabulary: type[_Word], value: object, *, what: str) -> _Word:
    """The member of *vocabulary* that *value* names: a member's value, exactly, or a member itself.

    Every word-valued field's ``parse`` reads through this one refusal.

    Raises:
        ConfigurationError: If *value* is anything else; the message names
            *what*, the members' values in order and *value*.
    """
    try:
        return vocabulary(value)
    except ValueError:
        raise ConfigurationError.must_be(
            what, f"one of {', '.join(member.value for member in vocabulary)}", got=value
        ) from None


class GridServicesBand(str, Enum):
    """The three uncertainty bands every grid-services rate is quoted in, from low to high."""

    LOW = "low"
    CENTRAL = "central"
    HIGH = "high"

    @classmethod
    def parse(cls, value: object, *, what: str) -> "GridServicesBand":
        """Return the band *value* names, refusing any other value as :func:`_member_named` does."""
        return _member_named(cls, value, what=what)


class DeliveryBaseline(str, Enum):
    """How an event's delivery is measured: operational, the increment above the battery's own discharge, as NESO's DFS measures it; capacity, the battery's whole window discharge, as NGED baselines domestic storage."""

    OPERATIONAL = "operational"
    CAPACITY = "capacity"

    @classmethod
    def parse(cls, value: object, *, what: str) -> "DeliveryBaseline":
        """Return the baseline *value* names, refusing any other value as :func:`_member_named` does."""
        return _member_named(cls, value, what=what)


# ---------------------------------------------------------------------------
# GridServicesRateBand + GridServicesRateBands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridServicesRateBand:
    """One uncertainty band's grid-services rates: per event, and flat per kW of battery discharge power per year.

    Capacity-at-events pricing reads the per-event rates; flat pricing reads
    the flat rate.

    Attributes:
        availability_gbp_per_kw_per_event: Availability payment per kW of
            contracted discharge capacity per activation event (£/kW/event).
        utilisation_gbp_per_mwh: Utilisation payment per MWh of actual energy
            dispatched during events (£/MWh).
        provenance: Source reference for these rates.
        flat_gbp_per_kw_per_year: Flat payment per kW of installed battery
            discharge power per year (£/kW/yr); >= 0 and finite.
    """

    availability_gbp_per_kw_per_event: float
    utilisation_gbp_per_mwh: float
    provenance: str = ""
    flat_gbp_per_kw_per_year: float = 0.0

    def __post_init__(self) -> None:
        """Read the three rates through number_fields as finite numbers of at least 0, holding the floats read."""
        read_field(self, "availability_gbp_per_kw_per_event", as_finite_float, NON_NEGATIVE)
        read_field(self, "utilisation_gbp_per_mwh", as_finite_float, NON_NEGATIVE)
        read_field(self, "flat_gbp_per_kw_per_year", as_finite_float, NON_NEGATIVE)


@dataclass(frozen=True)
class GridServicesRateBands:
    """Container for the three canonical (low / central / high) rate bands.

    Attributes:
        low: Pessimistic rate scenario.
        central: Central-estimate rate scenario.
        high: Optimistic rate scenario.
    """

    low: GridServicesRateBand
    central: GridServicesRateBand
    high: GridServicesRateBand

    def resolve(self, band: str) -> GridServicesRateBand:
        """Return the band matching *band*.

        Args:
            band: One of ``"low"``, ``"central"``, ``"high"``, or a
                :class:`GridServicesBand`.

        Returns:
            The matching :class:`GridServicesRateBand`.

        Raises:
            ConfigurationError: If *band* is not a band (a ValueError).
        """
        match GridServicesBand.parse(band, what="grid-services rate band"):
            case GridServicesBand.LOW:
                return self.low
            case GridServicesBand.CENTRAL:
                return self.central
            case GridServicesBand.HIGH:
                return self.high


# The two columns are independent calibrations of the same bands (docs/cost-recovery-finance-model.md §8.1).
_RATE_PROVENANCE = (
    "per-event rates: PRD docs/prds/enhanced-grid-services-capacity-at-events.md open-Q2 "
    "(calibrated defaults; tuning task to follow); "
    "flat rates: consulting 2026-06-16-flexibility-value-buildability-model.md §1.1 "
    "+ docs/prds/flexibility-value-finance-integration.md §6"
)

GRID_SERVICES_RATE_BANDS: GridServicesRateBands = GridServicesRateBands(
    low=GridServicesRateBand(
        availability_gbp_per_kw_per_event=0.50,
        utilisation_gbp_per_mwh=30.0,
        provenance=_RATE_PROVENANCE,
        flat_gbp_per_kw_per_year=1.5,
    ),
    central=GridServicesRateBand(
        availability_gbp_per_kw_per_event=1.00,
        utilisation_gbp_per_mwh=60.0,
        provenance=_RATE_PROVENANCE,
        flat_gbp_per_kw_per_year=12.0,
    ),
    high=GridServicesRateBand(
        availability_gbp_per_kw_per_event=2.00,
        utilisation_gbp_per_mwh=120.0,
        provenance=_RATE_PROVENANCE,
        flat_gbp_per_kw_per_year=48.0,
    ),
)


def resolve_grid_services_rate_band(band: str) -> GridServicesRateBand:
    """Validate *band* and return the corresponding :class:`GridServicesRateBand`.

    Delegates to :meth:`GRID_SERVICES_RATE_BANDS.resolve`.

    Args:
        band: One of ``"low"``, ``"central"``, ``"high"``, or a
            :class:`GridServicesBand`.

    Returns:
        The matching :class:`GridServicesRateBand` from
        :data:`GRID_SERVICES_RATE_BANDS`.

    Raises:
        ConfigurationError: If *band* is not a band (a ValueError).
    """
    return GRID_SERVICES_RATE_BANDS.resolve(band)


# ---------------------------------------------------------------------------
# EventWindow
# ---------------------------------------------------------------------------

# (GridServicesEventsConfig and DEFAULT_EVENT_WINDOWS defined after EventWindow below)


@dataclass(frozen=True)
class EventWindow:
    """Schedule descriptor for grid-service events.

    Specifies *when* capacity-at-events payments can be earned: the set of
    eligible calendar months, week-days (ISO Monday=0), and clock hours, plus
    aggregate statistics used by the capacity-at-events income formula.

    months, weekdays and hours are each read as a tuple of whole numbers, so a
    list is held as the tuple of its elements.

    Attributes:
        months: Tuple of eligible months (1=Jan … 12=Dec).
        weekdays: Tuple of eligible weekdays (0=Mon … 6=Sun).
        hours: Tuple of eligible hours (0 … 23); uses 24-hour clock, so
            ``hours=(16, 17, 18)`` selects 16:xx, 17:xx, and 18:xx only
            (19:00 is excluded).
        events_per_year: Expected number of activation events per year, a
            whole number greater than 0.
        event_hours: Duration of each activation event in hours, a finite
            number greater than 0.
    """

    months: tuple[int, ...]
    weekdays: tuple[int, ...]
    hours: tuple[int, ...]
    events_per_year: int
    event_hours: float

    def __post_init__(self) -> None:
        """Read every field through number_fields, holding what it read, then refuse an empty months, weekdays or hours, raising ConfigurationError."""
        read_field(self, "months", as_whole_numbers, Interval(1, 12))
        read_field(self, "weekdays", as_whole_numbers, Interval(0, 6))
        read_field(self, "hours", as_whole_numbers, Interval(0, 23))
        read_field(self, "events_per_year", as_whole_number, POSITIVE)
        read_field(self, "event_hours", as_finite_float, POSITIVE)
        if not self.months:
            raise ConfigurationError("EventWindow.months must be a non-empty tuple")
        if not self.weekdays:
            raise ConfigurationError("EventWindow.weekdays must be a non-empty tuple")
        if not self.hours:
            raise ConfigurationError("EventWindow.hours must be a non-empty tuple")

    def mask(self, index: pd.DatetimeIndex) -> pd.Series:
        """Return a boolean Series selecting in-window timesteps.

        Args:
            index: DatetimeIndex (may be tz-aware or tz-naive).

        Returns:
            A :class:`pandas.Series` of dtype ``bool`` aligned to *index*,
            where ``True`` marks every timestep whose month, weekday, and hour
            all fall within the window's eligible sets.
        """
        arr = (
            index.month.isin(self.months)
            & index.weekday.isin(self.weekdays)
            & index.hour.isin(self.hours)
        )
        return pd.Series(arr, index=index)


# ---------------------------------------------------------------------------
# DEFAULT_EVENT_WINDOWS + GridServicesEventsConfig
# ---------------------------------------------------------------------------

# PRD open-Q4: default event schedule.
# Single winter-weekday-16:00-19:00 window per the PRD default.
DEFAULT_EVENT_WINDOWS: tuple["EventWindow", ...] = (
    EventWindow(
        months=(11, 12, 1, 2),
        weekdays=(0, 1, 2, 3, 4),
        hours=(16, 17, 18),
        events_per_year=12,
        event_hours=3.0,
    ),
)


@dataclass(frozen=True)
class GridServicesEventsConfig:
    """Configuration for the capacity-at-events grid-services pricing model.

    Attributes:
        band: Uncertainty band name, a :class:`GridServicesBand` value
            (``"low"``, ``"central"``, or ``"high"``).
        event_windows: Tuple of :class:`EventWindow` objects describing when
            activation events can occur.
        aggregator_share: Fraction of gross income paid to the aggregator;
            must be in ``[0, 1)``.
        utilisation_factor: Expected fraction of contracted capacity actually
            dispatched during events; must be in ``[0, 1]``.
        availability_gbp_per_kw_per_event: Optional override for the
            availability rate (£/kW/event).  If ``None``, the rate is taken
            from :data:`GRID_SERVICES_RATE_BANDS` via *band*.
        utilisation_gbp_per_mwh: Optional override for the utilisation rate
            (£/MWh).  If ``None``, the rate is taken from
            :data:`GRID_SERVICES_RATE_BANDS` via *band*.
        delivery_baseline: How an event's delivery is measured, a
            :class:`DeliveryBaseline` value (``"operational"`` or
            ``"capacity"``).
    """

    band: str = "central"
    event_windows: tuple[EventWindow, ...] = DEFAULT_EVENT_WINDOWS
    aggregator_share: float = 0.25
    utilisation_factor: float = 0.6
    availability_gbp_per_kw_per_event: Optional[float] = None
    utilisation_gbp_per_mwh: Optional[float] = None
    delivery_baseline: str = "operational"

    def __post_init__(self) -> None:
        """Read the numbers through number_fields, holding the floats read, then refuse an unknown band, an unknown delivery baseline or no event windows, raising ConfigurationError."""
        read_field(self, "aggregator_share", as_finite_float, Interval(0, 1, high_open=True))
        read_field(self, "utilisation_factor", as_finite_float, UNIT_INTERVAL)
        read_field(self, "availability_gbp_per_kw_per_event", as_finite_float, NON_NEGATIVE, optional=True)
        read_field(self, "utilisation_gbp_per_mwh", as_finite_float, NON_NEGATIVE, optional=True)
        GridServicesBand.parse(self.band, what="GridServicesEventsConfig.band")
        DeliveryBaseline.parse(self.delivery_baseline, what="GridServicesEventsConfig.delivery_baseline")
        if not self.event_windows:
            raise ConfigurationError(
                "GridServicesEventsConfig.event_windows must be a non-empty tuple"
            )

    def annual_income_gbp(self, fleet_results: "FleetResults") -> float:
        """Return the annual capacity-at-events income this configuration prices *fleet_results* at.

        In £ per year, net of the aggregator share:
        ``compute_grid_services_at_events(fleet_results, self).annual_income_gbp``.
        """
        return compute_grid_services_at_events(fleet_results, self).annual_income_gbp


# ---------------------------------------------------------------------------
# The fleet's battery homes
# ---------------------------------------------------------------------------


def _battery_homes(
    fleet_results: "FleetResults",
) -> list[tuple["SimulationResults", BatteryConfig]]:
    """Each home of *fleet_results* with a battery: its simulated results and its battery configuration, in fleet order.

    A PV-only home (``battery_config is None``) has no battery to price.  A
    length mismatch between ``per_home_results`` and ``home_configs`` raises
    ValueError rather than truncating the fleet to the shorter list.
    """
    return [
        (sim, home.battery_config)
        for sim, home in zip(
            fleet_results.per_home_results, fleet_results.home_configs, strict=True
        )
        if home.battery_config is not None
    ]


# ---------------------------------------------------------------------------
# NoGridServices + FlatGridServices + GridServicesModel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoGridServices:
    """The pricing under which a fleet earns no grid-services income."""

    def annual_income_gbp(self, fleet_results: "FleetResults") -> float:
        """Return 0.0: no fleet earns grid-services income under this pricing."""
        return 0.0


@dataclass(frozen=True)
class FlatGridServices:
    """A flat grid-services rate per kW of installed battery discharge power per year.

    Attributes:
        income_per_kw_per_year_gbp: Income per kW of battery discharge power per
            year, net of the aggregator share (£/kW/yr); > 0 and finite.  Zero
            income is :class:`NoGridServices`.
    """

    income_per_kw_per_year_gbp: float

    def __post_init__(self) -> None:
        """Read the rate through number_fields as a finite number greater than 0, holding the float read."""
        read_field(self, "income_per_kw_per_year_gbp", as_finite_float, POSITIVE)

    def annual_income_gbp(self, fleet_results: "FleetResults") -> float:
        """Return the rate × the installed discharge power of the fleet's batteries, in £ per year.

        The power is the sum of ``battery_config.max_discharge_kw`` over the
        homes of *fleet_results* that have a battery.
        """
        return self.income_per_kw_per_year_gbp * sum(
            battery_config.max_discharge_kw
            for _, battery_config in _battery_homes(fleet_results)
        )


GridServicesModel: TypeAlias = NoGridServices | FlatGridServices | GridServicesEventsConfig


# ---------------------------------------------------------------------------
# compute_fleet_spare_capacity_kw
# ---------------------------------------------------------------------------


def _span_sums(
    series: pd.Series, start: npt.NDArray[np.intp], stop: npt.NDArray[np.intp]
) -> npt.NDArray[np.float64]:
    """The sum of *series* over each span of rows from *start* up to, not including, *stop*: 0.0 for an empty span."""
    values: npt.NDArray[np.float64] = series.to_numpy(dtype=float)
    cumulative = np.concatenate((np.zeros(1), np.cumsum(values)))
    return np.take(cumulative, stop) - np.take(cumulative, start)


def _home_displaced_self_use(
    sim: "SimulationResults",
    first_rows: npt.NDArray[np.intp],
    last_rows: npt.NDArray[np.intp],
    avail_kw: npt.NDArray[np.float64],
    event_hours: float,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """One battery home's displaced evening self-use on each of its event days: the kWh, and its value (£).

    A day's span is its rows after *last_rows* (its last in-window row) and before
    the first later row that charges, the next event day's first in-window row
    (*first_rows*, in date order) or the index's end, whichever comes first.  The
    kWh is ``min(avail_kw × event_hours, the span's discharge)``; its value is that
    kWh at the span's mean tariff, £0 for an empty span.
    """
    rows = len(sim.battery_discharge)
    charging = np.flatnonzero(sim.battery_charge.to_numpy(dtype=float) > 0)
    next_charge = np.append(charging, rows)[np.searchsorted(charging, last_rows, side="right")]
    start = last_rows + 1
    stop = np.minimum(next_charge, np.append(first_rows[1:], rows))
    span_rows = stop - start
    discharge_kwh = _span_sums(sim.battery_discharge, start, stop) * sim.window.step_hours
    mean_rate = np.divide(
        _span_sums(sim.tariff_rate, start, stop),
        span_rows,
        out=np.zeros(len(span_rows)),
        where=span_rows > 0,
    )
    displaced_kwh = np.minimum(avail_kw * event_hours, discharge_kwh)
    return displaced_kwh, displaced_kwh * mean_rate


def _home_event_days(
    sim: "SimulationResults",
    battery_config: BatteryConfig,
    floor_kwh: float,
    window: EventWindow,
    baseline: DeliveryBaseline,
) -> pd.DataFrame:
    """One battery home's figures on each of its event days in *window* under *baseline*, indexed by date in date order.

    Columns: avail_kw, its firm spare capacity (kW); displaced_kwh and
    displaced_gbp, the evening self-use that capacity displaces and its value (see
    :func:`_home_displaced_self_use`).  The formulas are
    :func:`compute_fleet_spare_capacity_kw`'s.  A home whose index the window never
    enters has no event day: the frame is empty.
    """
    index = sim.battery_soc.index
    rows = np.flatnonzero(window.mask(index).to_numpy())
    above_floor = sim.battery_soc.to_numpy(dtype=float) - floor_kwh
    days = (
        pd.DataFrame(
            {
                "above_floor": above_floor[rows],
                "discharge": sim.battery_discharge.to_numpy(dtype=float)[rows],
                "row": rows,
            }
        )
        .groupby(index[rows].date)
        .agg(
            min_above_floor=("above_floor", "min"),
            max_discharge=("discharge", "max"),
            first_row=("row", "min"),
            last_row=("row", "max"),
        )
    )
    first_rows = days["first_row"].to_numpy()
    match baseline:
        case DeliveryBaseline.OPERATIONAL:
            headroom_kw = battery_config.max_discharge_kw - days["max_discharge"].to_numpy()
            energy_kwh = days["min_above_floor"].to_numpy()
        case DeliveryBaseline.CAPACITY:
            headroom_kw = np.full(len(days), battery_config.max_discharge_kw)
            energy_kwh = above_floor[first_rows]
    avail_kw = np.maximum(0.0, np.minimum(headroom_kw, energy_kwh / window.event_hours))
    displaced_kwh, displaced_gbp = _home_displaced_self_use(
        sim, first_rows, days["last_row"].to_numpy(), avail_kw, window.event_hours
    )
    return pd.DataFrame(
        {"avail_kw": avail_kw, "displaced_kwh": displaced_kwh, "displaced_gbp": displaced_gbp},
        index=days.index,
    )


def _mean_or_zero(values: tuple[float, ...]) -> float:
    """The mean of *values*; 0.0 when there are none."""
    return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class _EventDayTotals:
    """One event window's fleet totals on each of its event days, in date order.

    The event days are the union of the battery homes' event dates in the window; a
    home lacking a date adds 0 to it.

    Attributes:
        window: The event window.
        avail_kw: The fleet's firm spare capacity on each event day, A(d) (kW).
        displaced_kwh: The fleet's evening self-use displaced on each event day (kWh).
        displaced_gbp: The value of that displaced self-use on each event day (£).
    """

    window: EventWindow
    avail_kw: tuple[float, ...]
    displaced_kwh: tuple[float, ...]
    displaced_gbp: tuple[float, ...]

    @classmethod
    def of_homes(cls, window: EventWindow, home_days: list[pd.DataFrame]) -> "_EventDayTotals":
        """Sum *home_days*, each one home's figures per event date, over the homes on the sorted union of their dates."""
        if not home_days:
            return cls(window=window, avail_kw=(), displaced_kwh=(), displaced_gbp=())
        fleet_days = pd.concat(home_days).groupby(level=0).sum()
        return cls(
            window=window,
            avail_kw=tuple(fleet_days["avail_kw"].tolist()),
            displaced_kwh=tuple(fleet_days["displaced_kwh"].tolist()),
            displaced_gbp=tuple(fleet_days["displaced_gbp"].tolist()),
        )

    @property
    def observed(self) -> bool:
        """Whether the window has an event day: some battery home's simulated index enters it."""
        return bool(self.avail_kw)

    @property
    def mean_avail_kw(self) -> float:
        """The mean of A(d) over the event days, the capacity the pricing books (kW); 0.0 with no event day."""
        return _mean_or_zero(self.avail_kw)

    @property
    def displaced_kwh_per_event(self) -> float:
        """The mean over the event days of the fleet's displaced evening self-use (kWh); 0.0 with no event day."""
        return _mean_or_zero(self.displaced_kwh)

    @property
    def displaced_gbp_per_year(self) -> float:
        """The mean over the event days of the displaced self-use's value, times the window's events per year (£); 0.0 with no event day."""
        return _mean_or_zero(self.displaced_gbp) * self.window.events_per_year

    def avail_on_share_of_days_kw(self, percent: int) -> float:
        """The capacity available on at least *percent* % of the event days (kW): the ⌈percent·n / 100⌉-th largest of the n values of A(d); 0.0 with no event day.

        The rank is computed in whole numbers, so no rounding of percent·n / 100 can
        move it; an interpolated percentile is never taken.
        """
        if not self.avail_kw:
            return 0.0
        rank = -(-percent * len(self.avail_kw) // 100)
        return sorted(self.avail_kw, reverse=True)[rank - 1]


def _event_day_totals(
    battery_homes: list[tuple["SimulationResults", BatteryConfig]],
    windows: tuple[EventWindow, ...],
    baseline: DeliveryBaseline,
) -> tuple[_EventDayTotals, ...]:
    """Each of *windows*' fleet totals per event day over *battery_homes* under *baseline*, in window order.

    The formulas are :func:`compute_fleet_spare_capacity_kw`'s.
    """
    # A battery's SOC floor depends on its configuration alone: computed once, not per window.
    floors = [
        (sim, battery_config, Battery(battery_config).min_soc_kwh)
        for sim, battery_config in battery_homes
    ]
    return tuple(
        _EventDayTotals.of_homes(
            window,
            [
                _home_event_days(sim, battery_config, floor_kwh, window, baseline)
                for sim, battery_config, floor_kwh in floors
            ],
        )
        for window in windows
    )


def compute_fleet_spare_capacity_kw(
    fleet_results: "FleetResults",
    windows: tuple["EventWindow", ...],
    delivery_baseline: str = "operational",
) -> tuple[float, ...]:
    """Compute firm spare dispatchable battery capacity (kW) per event window: the mean over its event days of the fleet's daily firm spare capacity.

    The capacity is derived solely from observable per-timestep SOC and net
    discharge series — no purpose-attribution of the underlying dispatch is
    required.  An event day of window *w* is a calendar date, in the home's index's
    own timezone, holding at least one of *w*'s timesteps.

    **Formula** (per battery home, per event day *d* of window *w*, with
    ``P = max_discharge_kw``, ``floor = Battery(battery_config).min_soc_kwh`` and
    ``h = w.event_hours``):

    .. code-block:: text

        operational:  avail(home, d) = max(0, min(P − max_{t∈d∩w} discharge(t),
                                                  min_{t∈d∩w}(soc(t) − floor) / h))
        capacity:     avail(home, d) = max(0, min(P, (soc(t₀) − floor) / h)),
                      t₀ the first timestep of d in w
        A(d)        = Σ_home avail(home, d)
        avail(w)    = mean over w's event days d of A(d)

    *delivery_baseline* chooses the formula: ``"operational"`` counts the increment
    above the battery's own discharge, as NESO's DFS measures delivery;
    ``"capacity"`` counts the battery's whole window discharge, as NGED baselines
    domestic storage (:class:`DeliveryBaseline`).

    On every event day the ``max(0, min(...))`` expression satisfies:

    * **I1** — the capacity is ≥ 0.
    * **I2** — firmness: it is within that day's inverter headroom throughout the
      window and within that day's energy above the floor over ``event_hours``.

    **Skips** (contribute 0):

    * Homes with ``battery_config is None`` (PV-only homes in a heterogeneous
      fleet) — skipped entirely; they have no battery to dispatch.
    * A date a home's index lacks — the home adds 0 to that date's A(d).  A window
      no home's index enters has no event day and gives 0.0.

    Args:
        fleet_results: Simulation results for the fleet.  Accessed via
            ``fleet_results.per_home_results`` and ``fleet_results.home_configs``.
        windows: Tuple of :class:`EventWindow` objects; order is preserved in
            the output.
        delivery_baseline: How an event's delivery is measured, a
            :class:`DeliveryBaseline` value: ``"operational"`` (the default) or
            ``"capacity"``.

    Returns:
        A :class:`tuple` of :class:`float` with one entry per window (in input
        order): the mean over the window's event days of the fleet's daily firm
        spare capacity, in kW.

    Raises:
        ConfigurationError: If *delivery_baseline* is not a baseline (a ValueError).
    """
    baseline = DeliveryBaseline.parse(delivery_baseline, what="delivery_baseline")
    return tuple(
        totals.mean_avail_kw
        for totals in _event_day_totals(_battery_homes(fleet_results), windows, baseline)
    )


# ---------------------------------------------------------------------------
# GridServicesAtEvents
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridServicesAtEvents:
    """Banded availability + utilisation income breakdown from a grid-services event model.

    Returned by :func:`compute_grid_services_at_events`.  All income figures are
    **net** of the aggregator share: the CBS's grid-services revenue, which
    :func:`~solar_challenge.finance.project_multi_year` books into fleet revenue.

    Attributes:
        annual_income_gbp: Total annual grid-services income across all event
            windows (£/year).  Equals ``sum(per_window_income_gbp)``.
        per_window_avail_kw: Per-window firm spare dispatchable capacity (kW):
            the mean over the window's event days of the fleet's daily total, in
            the same order as the :attr:`GridServicesEventsConfig.event_windows`
            tuple; the figures :func:`compute_fleet_spare_capacity_kw` gives for
            the same fleet, windows and delivery baseline.
        per_window_income_gbp: Per-window net income (£), in window order.
            Each entry is the net (post-aggregator-share) availability +
            utilisation income for that window.
        per_window_avail_p50_kw: Per-window capacity available on at least 50%
            of event days (kW), in window order: the ⌈0.5·n⌉-th largest of the
            window's n fleet daily totals; 0.0 for a window with no event day.
        per_window_avail_p90_kw: Per-window capacity available on at least 90%
            of event days (kW), in window order: the ⌈0.9·n⌉-th largest fleet
            daily total; 0.0 for a window with no event day.
        per_window_displaced_self_use_kwh_per_event: Per-window evening
            self-use an event displaces (kWh), in window order: per home and
            event day, ``min(avail × event_hours, the discharge after the window
            until the next recharge, the next event day's window or the index
            end)``, summed over homes and averaged over event days.  A reported
            figure: neither *annual_income_gbp* nor *per_window_income_gbp*
            subtracts it.
        per_window_displaced_import_gbp_per_year: Per-window value of that
            displaced self-use (£/year), in window order: each home-day's
            displaced kWh at the mean tariff over its span, summed over homes,
            averaged over event days and multiplied by ``events_per_year``.  The
            householders import it; neither income figure subtracts it.

    .. note::
        ``sum(per_window_income_gbp) == annual_income_gbp`` is a design
        invariant.  Consumers must NOT re-apply
        ``(1 - aggregator_share)`` to the per-window tuple — it has already
        been applied.
    """

    annual_income_gbp: float
    per_window_avail_kw: tuple[float, ...]
    per_window_income_gbp: tuple[float, ...]
    per_window_avail_p50_kw: tuple[float, ...] = ()
    per_window_avail_p90_kw: tuple[float, ...] = ()
    per_window_displaced_self_use_kwh_per_event: tuple[float, ...] = ()
    per_window_displaced_import_gbp_per_year: tuple[float, ...] = ()


# ---------------------------------------------------------------------------
# compute_grid_services_at_events
# ---------------------------------------------------------------------------


def _warn_unobserved_windows(
    battery_homes: list[tuple["SimulationResults", BatteryConfig]],
    per_window: tuple[_EventDayTotals, ...],
) -> None:
    """Issue one UserWarning for each window of *per_window* that no battery home's simulated index enters.

    Such a window contributes £0.  A fleet without a battery home has nothing to
    observe and does not warn.  The warning is attributed to the caller of
    :func:`compute_grid_services_at_events`, and its text names only the window
    and the span of the battery homes' indices.
    """
    unobserved = [totals.window for totals in per_window if not totals.observed]
    if not battery_homes or not unobserved:
        return
    first = min(sim.battery_soc.index.min() for sim, _ in battery_homes)
    last = max(sim.battery_soc.index.max() for sim, _ in battery_homes)
    for window in unobserved:
        warnings.warn(
            f"Event window months={window.months}, weekdays={window.weekdays}, "
            f"hours={window.hours} has no timestep in the fleet's simulated index, "
            f"{first} to {last}, so it contributes £0 to the capacity-at-events income",
            UserWarning,
            stacklevel=3,
        )


def compute_grid_services_at_events(
    fleet_results: "FleetResults",
    cfg: "GridServicesEventsConfig",
) -> GridServicesAtEvents:
    """Compute banded availability + utilisation income from grid-services events.

    Applies the capacity-at-events pricing formula per event window using the
    firm spare capacity from :func:`compute_fleet_spare_capacity_kw` under
    *cfg.delivery_baseline* (the mean over the window's event days) and the rates
    from :data:`GRID_SERVICES_RATE_BANDS` (resolved via *cfg.band*).

    **Rate resolution** (override precedence):

    .. code-block:: text

        avail_rate = cfg.availability_gbp_per_kw_per_event   if not None
                   else band.availability_gbp_per_kw_per_event
        util_rate  = cfg.utilisation_gbp_per_mwh             if not None
                   else band.utilisation_gbp_per_mwh

    Each rate field can be overridden independently; a ``None`` field falls back
    to the band value resolved via *cfg.band*.

    **Formula** (per window *w* with firm spare capacity *avail_kW*):

    .. code-block:: text

        avail_income = avail * avail_rate * w.events_per_year
        util_income  = avail * cfg.utilisation_factor * w.event_hours
                       * (util_rate / 1000.0) * w.events_per_year
        gross_w      = avail_income + util_income
        net_w        = gross_w * (1.0 - cfg.aggregator_share)

    The per-window income is **net** of the aggregator share.  Consumers must
    NOT re-apply ``(1 - aggregator_share)`` — see
    :class:`GridServicesAtEvents`.

    A window that no battery home's simulated index enters contributes £0 and
    is named in a ``UserWarning``, once per call.

    Args:
        fleet_results: Simulation results for the fleet.
        cfg: Grid-services configuration (band, event windows, aggregator share,
            utilisation factor, optional rate overrides).

    Returns:
        A :class:`GridServicesAtEvents` with:

        - ``per_window_avail_kw`` — firm spare capacity per window (from :func:`compute_fleet_spare_capacity_kw`).
        - ``per_window_income_gbp`` — net income per window (in window order).
        - ``annual_income_gbp`` — sum of per-window net income.
        - ``per_window_avail_p50_kw`` and ``per_window_avail_p90_kw`` — the
          capacity available on at least 50% and 90% of each window's event days.
        - ``per_window_displaced_self_use_kwh_per_event`` and
          ``per_window_displaced_import_gbp_per_year`` — the evening self-use an
          event displaces and its value, reported beside the income, which is
          gross of them.
    """
    battery_homes = _battery_homes(fleet_results)
    baseline = DeliveryBaseline.parse(
        cfg.delivery_baseline, what="GridServicesEventsConfig.delivery_baseline"
    )
    per_window = _event_day_totals(battery_homes, cfg.event_windows, baseline)
    _warn_unobserved_windows(battery_homes, per_window)
    band = resolve_grid_services_rate_band(cfg.band)

    # Override precedence: use cfg field if explicitly set, else fall back to band.
    avail_rate = (
        cfg.availability_gbp_per_kw_per_event
        if cfg.availability_gbp_per_kw_per_event is not None
        else band.availability_gbp_per_kw_per_event
    )
    util_rate = (
        cfg.utilisation_gbp_per_mwh
        if cfg.utilisation_gbp_per_mwh is not None
        else band.utilisation_gbp_per_mwh
    )

    per_window_net: list[float] = []
    for totals in per_window:
        window, avail = totals.window, totals.mean_avail_kw
        avail_income = avail * avail_rate * window.events_per_year
        util_income = (
            avail
            * cfg.utilisation_factor
            * window.event_hours
            * (util_rate / 1000.0)
            * window.events_per_year
        )
        gross = avail_income + util_income
        per_window_net.append(gross * (1.0 - cfg.aggregator_share))

    return GridServicesAtEvents(
        annual_income_gbp=float(sum(per_window_net)),
        per_window_avail_kw=tuple(totals.mean_avail_kw for totals in per_window),
        per_window_income_gbp=tuple(per_window_net),
        per_window_avail_p50_kw=tuple(totals.avail_on_share_of_days_kw(50) for totals in per_window),
        per_window_avail_p90_kw=tuple(totals.avail_on_share_of_days_kw(90) for totals in per_window),
        per_window_displaced_self_use_kwh_per_event=tuple(
            totals.displaced_kwh_per_event for totals in per_window
        ),
        per_window_displaced_import_gbp_per_year=tuple(
            totals.displaced_gbp_per_year for totals in per_window
        ),
    )
