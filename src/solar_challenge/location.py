# SPDX-License-Identifier: AGPL-3.0-or-later
"""Location handling for PV system modelling."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
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


LOCATION_PRESETS: Mapping[str, Location] = MappingProxyType({
    "bristol": Location.bristol(),
    "london": Location(latitude=51.51, longitude=-0.13, altitude=11.0, name="London, UK"),
    "edinburgh": Location(latitude=55.95, longitude=-3.19, altitude=47.0, name="Edinburgh, UK"),
    "manchester": Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester, UK"),
})
"""The named locations a location string may give, keyed by lower-case name."""


def parse_location(text: str) -> Location:
    """The Location *text* names: a LOCATION_PRESETS name, in any case and with surrounding whitespace, or 'lat,lon' or 'lat,lon,alt' in decimal degrees and metres, named 'Custom (lat, lon)', its altitude Location's default when not given.

    Raises:
        ConfigurationError: For any other text, naming location, the text and the accepted
            forms; from as_finite_float, for a coordinate that is not a finite number,
            naming it; from Location, for coordinates outside its range.
    """
    preset = LOCATION_PRESETS.get(text.strip().lower())
    if preset is not None:
        return preset
    numbers = text.split(",")
    if len(numbers) not in (2, 3):
        raise ConfigurationError(
            f"location must be one of {', '.join(map(repr, LOCATION_PRESETS))}, "
            f"or 'lat,lon' or 'lat,lon,alt' coordinates in decimal degrees and metres, got {text!r}"
        )
    latitude = as_finite_float(numbers[0], "latitude")
    longitude = as_finite_float(numbers[1], "longitude")
    name = f"Custom ({latitude:.2f}, {longitude:.2f})"
    if len(numbers) == 2:
        return Location(latitude=latitude, longitude=longitude, name=name)
    return Location(
        latitude=latitude, longitude=longitude, altitude=as_finite_float(numbers[2], "altitude"), name=name
    )
