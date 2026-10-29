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
* :func:`compute_fleet_spare_capacity_kw` — per-event-window firm spare
  dispatchable battery capacity (kW) summed across the fleet.
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
from typing import TYPE_CHECKING, Optional, TypeAlias

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
# GridServicesBand
# ---------------------------------------------------------------------------


class GridServicesBand(str, Enum):
    """The three uncertainty bands every grid-services rate is quoted in, from low to high."""

    LOW = "low"
    CENTRAL = "central"
    HIGH = "high"

    @classmethod
    def parse(cls, value: object, *, what: str) -> "GridServicesBand":
        """Return the band *value* names: a band's value, exactly, or a band itself.

        Raises:
            ConfigurationError: If *value* is anything else; the message names
                *what*, the bands in order and *value*.
        """
        try:
            return cls(value)
        except ValueError:
            raise ConfigurationError(
                f"{what} must be one of {', '.join(band.value for band in cls)}, got {value!r}"
            ) from None


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
    """

    band: str = "central"
    event_windows: tuple[EventWindow, ...] = DEFAULT_EVENT_WINDOWS
    aggregator_share: float = 0.25
    utilisation_factor: float = 0.6
    availability_gbp_per_kw_per_event: Optional[float] = None
    utilisation_gbp_per_mwh: Optional[float] = None

    def __post_init__(self) -> None:
        """Read the numbers through number_fields, holding the floats read, then refuse an unknown band or no event windows, raising ConfigurationError."""
        read_field(self, "aggregator_share", as_finite_float, Interval(0, 1, high_open=True))
        read_field(self, "utilisation_factor", as_finite_float, UNIT_INTERVAL)
        read_field(self, "availability_gbp_per_kw_per_event", as_finite_float, NON_NEGATIVE, optional=True)
        read_field(self, "utilisation_gbp_per_mwh", as_finite_float, NON_NEGATIVE, optional=True)
        GridServicesBand.parse(self.band, what="GridServicesEventsConfig.band")
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


@dataclass(frozen=True)
class _WindowSpareCapacity:
    """One event window's firm spare capacity over a fleet's battery homes.

    Attributes:
        window: The event window.
        observed: Whether some battery home's simulated index enters the window.
        avail_kw: Firm spare dispatchable capacity (kW), summed over the battery
            homes whose index enters the window; 0.0 when none does.
    """

    window: EventWindow
    observed: bool
    avail_kw: float


def _spare_capacity_per_window(
    battery_homes: list[tuple["SimulationResults", BatteryConfig]],
    windows: tuple[EventWindow, ...],
) -> tuple[_WindowSpareCapacity, ...]:
    """Each of *windows*' firm spare capacity over *battery_homes*, in window order.

    The formula is :func:`compute_fleet_spare_capacity_kw`'s.
    """
    # A battery's SOC floor depends on its configuration alone: computed once, not per window.
    floors = [
        (sim, battery_config, Battery(battery_config).min_soc_kwh)
        for sim, battery_config in battery_homes
    ]
    capacities: list[_WindowSpareCapacity] = []
    for window in windows:
        total = 0.0
        observed = False
        for sim, battery_config, min_soc_kwh in floors:
            mask = window.mask(sim.battery_soc.index)
            # A home whose index the window never enters adds nothing; reducing its
            # empty in-window Series would give NaN.
            if not bool(mask.any()):
                continue
            observed = True
            soc_w = sim.battery_soc[mask]
            dis_w = sim.battery_discharge[mask]
            p_spare = battery_config.max_discharge_kw - float(dis_w.max())
            e_spare = float((soc_w - min_soc_kwh).min())
            total += max(0.0, min(p_spare, e_spare / window.event_hours))
        capacities.append(
            _WindowSpareCapacity(window=window, observed=observed, avail_kw=float(total))
        )
    return tuple(capacities)


def compute_fleet_spare_capacity_kw(
    fleet_results: "FleetResults",
    windows: tuple["EventWindow", ...],
) -> tuple[float, ...]:
    """Compute firm spare dispatchable battery capacity (kW) per event window.

    For each event window, sums across the fleet the firm spare battery
    capacity derived solely from observable per-timestep SOC and net discharge
    series — no purpose-attribution of the underlying dispatch is required.

    **Formula** (per battery home, per window *w*):

    .. code-block:: text

        mask      = w.mask(sim.battery_soc.index)        # in-window bool Series
        P_spare   = max_discharge_kw - max_{t in w}(battery_discharge)
        E_spare   = min_{t in w}(battery_soc - min_soc_kwh)
        avail(h)  = max(0.0, min(P_spare, E_spare / w.event_hours))
        avail(w)  = Σ_h avail(h)

    The single ``max(0, min(P_spare, E_spare/event_hours))`` expression
    satisfies:

    * **I1** — result is always ≥ 0 (the outer ``max(0,...)`` ensures this).
    * **I2** — firmness: avail ≤ P_spare (inverter headroom throughout the
      window) and ≤ E_spare / event_hours (energy deliverable throughout the
      window without violating the SOC floor).

    **Skips** (handled transparently — contribute 0 to the sum):

    * Homes with ``battery_config is None`` (PV-only homes in a heterogeneous
      fleet) — skipped entirely; they have no battery to dispatch.
    * Windows absent from a home's index (``mask.any()`` is False) — skipped
      to avoid reducing an empty Series (which would produce NaN).

    Args:
        fleet_results: Simulation results for the fleet.  Accessed via
            ``fleet_results.per_home_results`` and ``fleet_results.home_configs``.
        windows: Tuple of :class:`EventWindow` objects; order is preserved in
            the output.

    Returns:
        A :class:`tuple` of :class:`float` with one entry per window (in input
        order).  Each value is the total firm spare dispatchable capacity in kW
        across the fleet for that window.
    """
    return tuple(
        capacity.avail_kw
        for capacity in _spare_capacity_per_window(_battery_homes(fleet_results), windows)
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
        per_window_avail_kw: Per-window firm spare dispatchable capacity (kW),
            in the same order as the :attr:`GridServicesEventsConfig.event_windows`
            tuple: the figures :func:`compute_fleet_spare_capacity_kw` gives
            for the same fleet and windows.
        per_window_income_gbp: Per-window net income (£), in window order.
            Each entry is the net (post-aggregator-share) availability +
            utilisation income for that window.

    .. note::
        ``sum(per_window_income_gbp) == annual_income_gbp`` is a design
        invariant.  Consumers must NOT re-apply
        ``(1 - aggregator_share)`` to the per-window tuple — it has already
        been applied.
    """

    annual_income_gbp: float
    per_window_avail_kw: tuple[float, ...]
    per_window_income_gbp: tuple[float, ...]


# ---------------------------------------------------------------------------
# compute_grid_services_at_events
# ---------------------------------------------------------------------------


def _warn_unobserved_windows(
    battery_homes: list[tuple["SimulationResults", BatteryConfig]],
    capacities: tuple[_WindowSpareCapacity, ...],
) -> None:
    """Issue one UserWarning for each window of *capacities* that no battery home's simulated index enters.

    Such a window contributes £0.  A fleet without a battery home has nothing to
    observe and does not warn.  The warning is attributed to the caller of
    :func:`compute_grid_services_at_events`, and its text names only the window
    and the span of the battery homes' indices.
    """
    unobserved = [capacity.window for capacity in capacities if not capacity.observed]
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
    firm spare capacity from :func:`compute_fleet_spare_capacity_kw` and
    the rates from :data:`GRID_SERVICES_RATE_BANDS` (resolved via *cfg.band*).

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
    """
    battery_homes = _battery_homes(fleet_results)
    capacities = _spare_capacity_per_window(battery_homes, cfg.event_windows)
    _warn_unobserved_windows(battery_homes, capacities)
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
    for capacity in capacities:
        window, avail = capacity.window, capacity.avail_kw
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
        per_window_avail_kw=tuple(capacity.avail_kw for capacity in capacities),
        per_window_income_gbp=tuple(per_window_net),
    )
