"""Tests for Location class."""

import dataclasses

import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import LOCATION_PRESETS, Location, parse_location
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


class TestParseLocation:
    """A location string names a preset or gives coordinates; anything else is refused by name."""

    @pytest.mark.parametrize(
        ("key", "spelling"),
        [
            pytest.param(key, spelling, id=f"{key}-{how}")
            for key in LOCATION_PRESETS
            for how, spelling in (("lower", key), ("upper", key.upper()), ("padded-title", f"  {key.title()}\t"))
        ],
    )
    def test_a_preset_is_named_in_any_case_and_with_surrounding_whitespace(self, key: str, spelling: str) -> None:
        assert parse_location(spelling) == LOCATION_PRESETS[key]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param(
                "51.5,-0.1", Location(latitude=51.5, longitude=-0.1, name="Custom (51.50, -0.10)"), id="lat-lon"
            ),
            pytest.param(
                "51.5,-0.1,11",
                Location(latitude=51.5, longitude=-0.1, altitude=11.0, name="Custom (51.50, -0.10)"),
                id="lat-lon-alt",
            ),
            pytest.param(
                " 51.5 , -0.1 , 11 ",
                Location(latitude=51.5, longitude=-0.1, altitude=11.0, name="Custom (51.50, -0.10)"),
                id="padded-numbers",
            ),
            pytest.param(
                "-33.87,151.21",
                Location(latitude=-33.87, longitude=151.21, name="Custom (-33.87, 151.21)"),
                id="south-and-east",
            ),
        ],
    )
    def test_coordinates_give_a_custom_location(self, text: str, expected: Location) -> None:
        assert parse_location(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("londn", id="misspelt-preset"),
            pytest.param("51.5;-0.1", id="semicolon"),
            pytest.param("", id="empty"),
            pytest.param("51.5", id="one-number"),
            pytest.param("51.5,-0.1,11,0", id="four-numbers"),
        ],
    )
    def test_text_that_is_neither_a_preset_nor_coordinates_is_refused_naming_location_the_text_and_the_forms(
        self, text: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_location(text)

        message = str(refusal.value)
        assert message.startswith("location must be ")
        assert message.endswith(f", got {text!r}")
        forms = [*map(repr, LOCATION_PRESETS), "'lat,lon'", "'lat,lon,alt'"]
        assert [form for form in forms if form not in message] == []

    @pytest.mark.parametrize(
        ("text", "field", "value"),
        [
            pytest.param("abc,-0.1", "latitude", "abc", id="latitude-word"),
            pytest.param("nan,-0.1", "latitude", "nan", id="latitude-nan"),
            pytest.param("51.5,abc", "longitude", "abc", id="longitude-word"),
            pytest.param("51.5,inf", "longitude", "inf", id="longitude-infinite"),
            pytest.param("51.5,", "longitude", "", id="longitude-empty"),
            pytest.param("51.5,-0.1,x", "altitude", "x", id="altitude-word"),
        ],
    )
    def test_a_coordinate_that_is_not_a_finite_number_is_refused_naming_it(
        self, text: str, field: str, value: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_location(text)

        assert str(refusal.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        ("text", "location_refusal"),
        [
            pytest.param("95,0", "latitude must be between -90 and 90, got 95.0", id="latitude-95"),
            pytest.param("0,181", "longitude must be between -180 and 180, got 181.0", id="longitude-181"),
            pytest.param("0,0,-501", "altitude must be at least -500, got -501.0", id="altitude-minus-501"),
        ],
    )
    def test_coordinates_outside_locations_ranges_are_refused_as_location_refuses_them(
        self, text: str, location_refusal: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_location(text)

        assert str(refusal.value) == location_refusal
