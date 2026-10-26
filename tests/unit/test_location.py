"""Tests for Location class."""

import dataclasses

import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import LOCATION_PRESETS, Location
from tests._unusable_numbers import UNUSABLE_NUMBERS


class TestLocationBasics:
    """Test basic Location functionality."""

    def test_create_location_with_all_params(self):
        """Location can be created with all parameters."""
        loc = Location(
            latitude=51.5,
            longitude=-0.1,
            timezone="Europe/London",
            altitude=20.0,
            name="London"
        )
        assert loc.latitude == 51.5
        assert loc.longitude == -0.1
        assert loc.timezone == "Europe/London"
        assert loc.altitude == 20.0
        assert loc.name == "London"

    def test_create_location_with_defaults(self):
        """Location uses sensible defaults."""
        loc = Location(latitude=51.0, longitude=-2.0)
        assert loc.timezone == "Europe/London"
        assert loc.altitude == 0.0
        assert loc.name == ""

    def test_location_is_frozen(self):
        """Location is immutable (frozen dataclass)."""
        loc = Location(latitude=51.0, longitude=-2.0)
        with pytest.raises(Exception):  # FrozenInstanceError
            loc.latitude = 52.0  # type: ignore


class TestBristolLocation:
    """Test Bristol default location."""

    def test_bristol_factory(self):
        """Bristol factory creates correct location."""
        loc = Location.bristol()
        assert loc.latitude == 51.45
        assert loc.longitude == -2.58
        assert loc.timezone == "Europe/London"
        assert loc.altitude == 11.0
        assert loc.name == "Bristol, UK"

    def test_bristol_coordinates(self):
        """Bristol coordinates are correct (51.45°N, 2.58°W)."""
        loc = Location.bristol()
        # Latitude is positive (North)
        assert loc.latitude > 0
        # Longitude is negative (West)
        assert loc.longitude < 0


class TestLocationHashability:
    """Test that Location can be used as dict key."""

    def test_location_is_hashable(self):
        """Location instances are hashable."""
        loc = Location.bristol()
        assert hash(loc) is not None

    def test_location_as_dict_key(self):
        """Location can be used as dictionary key."""
        loc1 = Location.bristol()
        loc2 = Location(latitude=52.0, longitude=-1.0)

        data = {
            loc1: "Bristol data",
            loc2: "Other data"
        }

        assert data[loc1] == "Bristol data"
        assert data[loc2] == "Other data"

    def test_equal_locations_same_hash(self):
        """Equal locations have same hash."""
        loc1 = Location.bristol()
        loc2 = Location.bristol()

        assert loc1 == loc2
        assert hash(loc1) == hash(loc2)


class TestLocationValidation:
    """Test parameter validation."""

    def test_invalid_latitude_too_high(self):
        """Latitude > 90 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            Location(latitude=91.0, longitude=0.0)
        assert str(exc_info.value) == "latitude must be between -90 and 90, got 91.0"

    def test_invalid_latitude_too_low(self):
        """Latitude < -90 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            Location(latitude=-91.0, longitude=0.0)
        assert str(exc_info.value) == "latitude must be between -90 and 90, got -91.0"

    def test_invalid_longitude_too_high(self):
        """Longitude > 180 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            Location(latitude=0.0, longitude=181.0)
        assert str(exc_info.value) == "longitude must be between -180 and 180, got 181.0"

    def test_invalid_longitude_too_low(self):
        """Longitude < -180 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            Location(latitude=0.0, longitude=-181.0)
        assert str(exc_info.value) == "longitude must be between -180 and 180, got -181.0"

    def test_an_altitude_below_500_metres_under_sea_level_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            Location(latitude=0.0, longitude=0.0, altitude=-501.0)
        assert str(exc_info.value) == "altitude must be at least -500, got -501.0"

    def test_boundary_values_valid(self):
        """Boundary values are valid."""
        # Should not raise
        Location(latitude=90.0, longitude=180.0)
        Location(latitude=-90.0, longitude=-180.0)

    @pytest.mark.parametrize("field", ["latitude", "longitude", "altitude"])
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_coordinate_that_is_not_a_finite_number_is_refused_naming_it_and_the_value(
        self, field: str, value: object
    ) -> None:
        """A NaN, an infinity, a bool or a word is refused by name, before any range is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(Location.bristol(), **{field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    def test_whole_number_coordinates_are_held_as_the_floats_they_equal(self) -> None:
        location = Location(51, -2)
        assert location.latitude == 51.0
        assert type(location.latitude) is float
        assert location.longitude == -2.0
        assert type(location.longitude) is float


class TestLocationTimeZone:
    """A Location's time zone must be one zoneinfo knows."""

    @pytest.mark.parametrize(
        "timezone",
        [
            pytest.param("Europe/Londn", id="misspelt"),
            pytest.param("", id="empty"),
            pytest.param(123, id="not-text"),
        ],
    )
    def test_a_time_zone_zoneinfo_does_not_know_is_refused_naming_it(self, timezone: object) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(Location(51, -2), timezone=timezone)
        assert "timezone" in str(exc_info.value)
        assert repr(timezone) in str(exc_info.value)

    @pytest.mark.parametrize(
        "timezone", ["Europe/London", "Europe/Paris", "Europe/Dublin", "America/New_York", "UTC"]
    )
    def test_each_time_zone_in_use_is_known(self, timezone: str) -> None:
        assert Location(51, -2, timezone=timezone).timezone == timezone


class TestLocationPresets:
    """The named locations parse_location reads."""

    def test_the_presets_are_bristol_london_edinburgh_and_manchester(self) -> None:
        assert list(LOCATION_PRESETS) == ["bristol", "london", "edinburgh", "manchester"]

    def test_the_bristol_preset_is_location_bristol(self) -> None:
        assert LOCATION_PRESETS["bristol"] == Location.bristol()

    def test_the_presets_cannot_be_changed(self) -> None:
        with pytest.raises(TypeError):
            LOCATION_PRESETS["cardiff"] = Location(51.48, -3.18)  # type: ignore[index]
