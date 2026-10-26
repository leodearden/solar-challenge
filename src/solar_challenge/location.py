# SPDX-License-Identifier: AGPL-3.0-or-later
"""Location handling for PV system modelling."""

import math
from dataclasses import dataclass
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval, as_finite_float, read_field


@dataclass(frozen=True)
class Location:
    """Geographic location for solar modelling.

    Frozen dataclass ensures immutability and hashability. Construction reads latitude,
    longitude and altitude as finite numbers inside their ranges and holds them as floats,
    and refuses a timezone zoneinfo does not know, each with a ConfigurationError.

    Attributes:
        latitude: Latitude in decimal degrees (positive = North)
        longitude: Longitude in decimal degrees (positive = East)
        timezone: IANA timezone string (e.g., 'Europe/London')
        altitude: Altitude above sea level in meters
        name: Optional descriptive name for the location
    """

    latitude: float
    longitude: float
    timezone: str = "Europe/London"
    altitude: float = 0.0
    name: str = ""

    # Bristol default values as class constants
    BRISTOL_LAT: ClassVar[float] = 51.45
    BRISTOL_LON: ClassVar[float] = -2.58  # West = negative
    BRISTOL_ALT: ClassVar[float] = 11.0

    @classmethod
    def bristol(cls) -> "Location":
        """Create a Location instance for Bristol, UK.

        Default location: 51.45°N, 2.58°W, Europe/London, 11m altitude

        Returns:
            Location configured for Bristol
        """
        return cls(
            latitude=cls.BRISTOL_LAT,
            longitude=cls.BRISTOL_LON,
            timezone="Europe/London",
            altitude=cls.BRISTOL_ALT,
            name="Bristol, UK"
        )

    def __post_init__(self) -> None:
        """Read each number setting, then refuse a time zone zoneinfo does not know."""
        read_field(self, "latitude", as_finite_float, Interval(-90, 90))
        read_field(self, "longitude", as_finite_float, Interval(-180, 180))
        read_field(self, "altitude", as_finite_float, Interval(-500, math.inf))
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as unknown:
            raise ConfigurationError(
                f"timezone must name an IANA time zone, such as 'Europe/London', got {self.timezone!r}"
            ) from unknown
