# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grid-services event-window model for domestic battery capacity-at-events pricing.

Encodes the event-window scheduling and banded-rate decomposition for the
capacity-at-events grid-services pricing model introduced in the enhanced
grid-services PRD (docs/prds/enhanced-grid-services-capacity-at-events.md).

Key public symbols:

* :class:`EventWindow` — frozen dataclass describing *when* grid-service events
  can occur (months, weekdays, hours), with a :meth:`~EventWindow.mask` helper
  that returns a boolean :class:`pandas.Series` selecting in-window timesteps.
* :class:`GridServicesRateBand` — frozen dataclass holding per-event availability
  and utilisation rates for one uncertainty band.
* :class:`GridServicesRateBands` — frozen container for the three canonical
  (low / central / high) bands with a :meth:`~GridServicesRateBands.resolve`
  helper.
* :data:`GRID_SERVICES_RATE_BANDS` — module-level constant (sibling to
  :data:`~solar_challenge.flex.FLEX_VALUE_BANDS`).
* :func:`resolve_grid_services_rate_band` — convenience helper delegating to
  the module constant.
* :data:`DEFAULT_EVENT_WINDOWS` — default winter-weekday-16:00-19:00 schedule
  per PRD open-Q4.
* :class:`GridServicesEventsConfig` — frozen dataclass combining band selection,
  event windows, aggregator share, and utilisation factor.
* :func:`compute_fleet_spare_capacity_kw` — per-event-window firm spare
  dispatchable battery capacity (kW) summed across the fleet.

**Import cycle note**: this module has NO top-level import of ``config.py``.
``ConfigurationError`` is imported *lazily*, inside each validation-failure
branch only, so that the module constants (``GRID_SERVICES_RATE_BANDS``,
``DEFAULT_EVENT_WINDOWS``) can be built at load time without triggering
``config.py``'s heavy import chain.  ``config.py`` is the side that imports
``gridservices``; the lazy guard keeps both import orders valid.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import pandas as pd

from solar_challenge.battery import Battery, BatteryConfig

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults
    from solar_challenge.home import SimulationResults


# ---------------------------------------------------------------------------
# GridServicesRateBand + GridServicesRateBands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridServicesRateBand:
    """Per-event capacity-at-events rate decomposition for one uncertainty band.

    Mirrors :class:`~solar_challenge.flex.FlexibilityValueBand` in structure
    but is specific to the capacity-at-events pricing model.

    Attributes:
        availability_gbp_per_kw_per_event: Availability payment per kW of
            contracted discharge capacity per activation event (£/kW/event).
        utilisation_gbp_per_mwh: Utilisation payment per MWh of actual energy
            dispatched during events (£/MWh).
        provenance: Source reference for these rates.
    """

    availability_gbp_per_kw_per_event: float
    utilisation_gbp_per_mwh: float
    provenance: str = ""

    def __post_init__(self) -> None:
        """Validate non-negativity.

        .. note::
            This class intentionally raises ``ValueError`` rather than
            ``ConfigurationError`` (unlike :class:`EventWindow` and
            :class:`GridServicesEventsConfig`).  The module constant
            :data:`GRID_SERVICES_RATE_BANDS` is constructed at *import time*
            before ``config.py`` has necessarily been loaded, so importing
            ``ConfigurationError`` inside ``__post_init__`` here would
            re-introduce the import cycle this module was designed to avoid.
            Callers that parse user-supplied rates through a config dict
            receive errors wrapped as ``ConfigurationError`` by the
            :func:`~solar_challenge.config._parse_finance_config` layer.
            This mirrors the convention in :class:`~solar_challenge.flex.FlexibilityValueBand`.
        """
        if self.availability_gbp_per_kw_per_event < 0:
            raise ValueError(
                "availability_gbp_per_kw_per_event must be non-negative, "
                f"got {self.availability_gbp_per_kw_per_event}"
            )
        if self.utilisation_gbp_per_mwh < 0:
            raise ValueError(
                f"utilisation_gbp_per_mwh must be non-negative, "
                f"got {self.utilisation_gbp_per_mwh}"
            )


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
            band: One of ``"low"``, ``"central"``, ``"high"``.

        Returns:
            The matching :class:`GridServicesRateBand`.

        Raises:
            ValueError: If *band* is not a known name.
        """
        if band == "low":
            return self.low
        if band == "central":
            return self.central
        if band == "high":
            return self.high
        raise ValueError(
            f"Unknown grid-services rate band '{band}'. Available: high, central, low"
        )


# PRD open-Q2: default band rates to be calibrated in a tuning task.
# Seeded near the flat-rate neighbourhood (central £12/kW/yr ≈ £1/kW/event
# for ~12 events/yr).  Availability is per-kW per event; utilisation is per MWh
# dispatched during the event.
_RATE_PROVENANCE = (
    "PRD docs/prds/enhanced-grid-services-capacity-at-events.md open-Q2 "
    "(calibrated defaults; tuning task to follow)"
)

GRID_SERVICES_RATE_BANDS: GridServicesRateBands = GridServicesRateBands(
    low=GridServicesRateBand(
        availability_gbp_per_kw_per_event=0.50,
        utilisation_gbp_per_mwh=30.0,
        provenance=_RATE_PROVENANCE,
    ),
    central=GridServicesRateBand(
        availability_gbp_per_kw_per_event=1.00,
        utilisation_gbp_per_mwh=60.0,
        provenance=_RATE_PROVENANCE,
    ),
    high=GridServicesRateBand(
        availability_gbp_per_kw_per_event=2.00,
        utilisation_gbp_per_mwh=120.0,
        provenance=_RATE_PROVENANCE,
    ),
)


def resolve_grid_services_rate_band(band: str) -> GridServicesRateBand:
    """Validate *band* and return the corresponding :class:`GridServicesRateBand`.

    Delegates to :meth:`GRID_SERVICES_RATE_BANDS.resolve`.

    Args:
        band: One of ``"low"``, ``"central"``, ``"high"``.

    Returns:
        The matching :class:`GridServicesRateBand` from
        :data:`GRID_SERVICES_RATE_BANDS`.

    Raises:
        ValueError: If *band* is not a known key.
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
    aggregate statistics used by the γ income formula.

    Attributes:
        months: Tuple of eligible months (1=Jan … 12=Dec).
        weekdays: Tuple of eligible weekdays (0=Mon … 6=Sun).
        hours: Tuple of eligible hours (0 … 23); uses 24-hour clock, so
            ``hours=(16, 17, 18)`` selects 16:xx, 17:xx, and 18:xx only
            (19:00 is excluded).
        events_per_year: Expected number of activation events per year.
        event_hours: Duration of each activation event in hours.
    """

    months: tuple[int, ...]
    weekdays: tuple[int, ...]
    hours: tuple[int, ...]
    events_per_year: int
    event_hours: float

    def __post_init__(self) -> None:
        """Validate domain constraints, raising ConfigurationError on violation.

        .. important::
            ``ConfigurationError`` is imported *inside each failure branch* rather
            than once at the top of this method.  :data:`DEFAULT_EVENT_WINDOWS` is
            a module-level constant that constructs a valid :class:`EventWindow` at
            *import time*, which calls this ``__post_init__``.  A top-level import
            here would fire during ``gridservices`` module initialisation — before
            ``config.py`` has finished loading — and re-introduce the circular
            import this module was designed to avoid.  The per-branch approach is
            safe because a valid construction never reaches any of the
            ``if <invalid>:`` branches, so the import is never triggered at load
            time.  (Compare :class:`GridServicesEventsConfig`, where no module-level
            instances exist, so the consolidated form is safe there.)
        """
        if not self.months:
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError("EventWindow.months must be a non-empty tuple")
        if not self.weekdays:
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError("EventWindow.weekdays must be a non-empty tuple")
        if not self.hours:
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError("EventWindow.hours must be a non-empty tuple")
        if any(m < 1 or m > 12 for m in self.months):
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError(
                f"EventWindow.months values must be in 1..12, got {self.months}"
            )
        if any(d < 0 or d > 6 for d in self.weekdays):
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError(
                f"EventWindow.weekdays values must be in 0..6, got {self.weekdays}"
            )
        if any(h < 0 or h > 23 for h in self.hours):
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError(
                f"EventWindow.hours values must be in 0..23, got {self.hours}"
            )
        if self.events_per_year <= 0:
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError(
                f"EventWindow.events_per_year must be > 0, got {self.events_per_year}"
            )
        if self.event_hours <= 0.0:
            from solar_challenge.config import ConfigurationError
            raise ConfigurationError(
                f"EventWindow.event_hours must be > 0, got {self.event_hours}"
            )

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
        band: Uncertainty band name (``"low"``, ``"central"``, or ``"high"``).
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
        """Validate domain constraints, raising ConfigurationError on violation.

        The import is done once at the top of ``__post_init__`` rather than
        inside every failure branch.  This is still *lazy* — ``__post_init__``
        runs at construction time, not at module load, so it does NOT trigger
        ``config.py`` when the module constants are built at import time.
        """
        # Single lazy import at the top of __post_init__ — avoids repetition
        # while preserving the load-time cycle-break (this runs at construction,
        # not at gridservices module load).
        from solar_challenge.config import ConfigurationError

        _VALID_BANDS = frozenset({"low", "central", "high"})
        if self.band not in _VALID_BANDS:
            raise ConfigurationError(
                f"GridServicesEventsConfig.band must be one of "
                f"{sorted(_VALID_BANDS)}, got '{self.band}'"
            )
        if not self.event_windows:
            raise ConfigurationError(
                "GridServicesEventsConfig.event_windows must be a non-empty tuple"
            )
        if not (0.0 <= self.aggregator_share < 1.0):
            raise ConfigurationError(
                f"GridServicesEventsConfig.aggregator_share must be in [0, 1), "
                f"got {self.aggregator_share}"
            )
        if not (0.0 <= self.utilisation_factor <= 1.0):
            raise ConfigurationError(
                f"GridServicesEventsConfig.utilisation_factor must be in [0, 1], "
                f"got {self.utilisation_factor}"
            )
        if self.availability_gbp_per_kw_per_event is not None and self.availability_gbp_per_kw_per_event < 0:
            raise ConfigurationError(
                "GridServicesEventsConfig.availability_gbp_per_kw_per_event override "
                f"must be >= 0, got {self.availability_gbp_per_kw_per_event}"
            )
        if self.utilisation_gbp_per_mwh is not None and self.utilisation_gbp_per_mwh < 0:
            raise ConfigurationError(
                "GridServicesEventsConfig.utilisation_gbp_per_mwh override "
                f"must be >= 0, got {self.utilisation_gbp_per_mwh}"
            )


# ---------------------------------------------------------------------------
# compute_fleet_spare_capacity_kw
# ---------------------------------------------------------------------------


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
    # Pre-compute the SOC floor for each battery home once.  Battery construction
    # is window-independent (min_soc_kwh depends only on the config), so computing
    # it inside the window loop would redundantly allocate N_windows Battery objects
    # per home.  We also collect (sim, battery_config) so the inner loop no longer
    # needs to touch home_configs at all.
    #
    # strict=True (Python 3.10+): a length mismatch between per_home_results and
    # home_configs raises ValueError immediately rather than silently truncating to
    # the shorter list and under-counting spare capacity.
    home_floors: list[Any] = []
    for sim, home_cfg in zip(
        fleet_results.per_home_results, fleet_results.home_configs, strict=True
    ):
        battery_config: Optional[BatteryConfig] = home_cfg.battery_config
        if battery_config is None:
            continue  # PV-only home: no battery to dispatch
        home_floors.append((sim, battery_config, Battery(battery_config).min_soc_kwh))

    avails: list[float] = []
    for window in windows:
        total = 0.0
        for sim, battery_config, min_soc_kwh in home_floors:
            mask = window.mask(sim.battery_soc.index)
            # Guard: skip if window is entirely absent from this home's index
            # (avoids NaN from reducing an empty Series)
            if not bool(mask.any()):
                continue
            soc_w = sim.battery_soc[mask]
            dis_w = sim.battery_discharge[mask]
            p_spare = battery_config.max_discharge_kw - float(dis_w.max())
            e_spare = float((soc_w - min_soc_kwh).min())
            total += max(0.0, min(p_spare, e_spare / window.event_hours))
        avails.append(float(total))
    return tuple(avails)
