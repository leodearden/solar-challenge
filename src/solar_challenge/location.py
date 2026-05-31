# SPDX-License-Identifier: AGPL-3.0-or-later
"""Location handling for PV system modelling."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Location:
    """Geographic location for solar modelling.

    Frozen dataclass ensures immutability and hashability.

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
        """Validate location parameters."""
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {self.longitude}")
        if self.altitude < -500:
            raise ValueError(f"Altitude below -500m is invalid, got {self.altitude}")
