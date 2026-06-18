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

**Import cycle note**: this module has NO top-level import of ``config.py``.
``ConfigurationError`` is imported *lazily*, inside each validation-failure
branch only, so that the module constants (``GRID_SERVICES_RATE_BANDS``,
``DEFAULT_EVENT_WINDOWS``) can be built at load time without triggering
``config.py``'s heavy import chain.  ``config.py`` is the side that imports
``gridservices``; the lazy guard keeps both import orders valid.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# EventWindow
# ---------------------------------------------------------------------------


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
        """Validate domain constraints, raising ConfigurationError on violation."""
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
