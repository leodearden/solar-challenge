# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.number_fields, the web layer's readers of a request's number fields."""

import pytest

from solar_challenge.web.number_fields import (
    as_finite_float,
    as_int,
    as_int_within,
    as_whole_number,
)


class TestAsFiniteFloat:
    """as_finite_float reads a value as float() reads it, and refuses a boolean or one that is not a finite number."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(4, 4.0, id="integer"),
            pytest.param(4.5, 4.5, id="float"),
            pytest.param("4.5", 4.5, id="numeric-string"),
            pytest.param(0, 0.0, id="zero"),
            pytest.param(-3, -3.0, id="negative"),
        ],
    )
    def test_a_finite_number_is_read_as_float_reads_it(
        self, value: object, expected: float
    ) -> None:
        """A finite number, or a string float() reads as one, is returned as that float."""
        number = as_finite_float(value, "pv_kw")
        assert number == expected
        assert isinstance(number, float)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("abc", id="non-numeric-string"),
            pytest.param(None, id="null"),
            pytest.param([4], id="array"),
            pytest.param(float("inf"), id="infinity"),
            pytest.param(float("-inf"), id="negative-infinity"),
            pytest.param(float("nan"), id="nan"),
            pytest.param("inf", id="infinity-string"),
            pytest.param(10**400, id="integer-too-large-for-a-float"),
            pytest.param(True, id="true"),
            pytest.param(False, id="false"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_is_refused_naming_the_field_and_the_value(
        self, value: object
    ) -> None:
        """A boolean, a value float() cannot read, one too large for a float, and ±inf or NaN are refused alike."""
        with pytest.raises(ValueError) as exc_info:
            as_finite_float(value, "pv_kw")
        assert str(exc_info.value) == f"pv_kw must be a finite number, got {value!r}"


class TestAsInt:
    """as_int reads a value as int() reads it, and refuses one int() cannot read."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(7, 7, id="integer"),
            pytest.param("7", 7, id="numeric-string"),
            pytest.param(7.9, 7, id="float-truncated"),
        ],
    )
    def test_a_value_int_reads_is_read_as_int_reads_it(self, value: object, expected: int) -> None:
        """An integer, a string of one, or a finite float truncated toward zero, as int() reads them."""
        assert as_int(value, "seed") == expected

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("inf"), id="infinity"),
            pytest.param(float("-inf"), id="negative-infinity"),
            pytest.param(float("nan"), id="nan"),
            pytest.param("x", id="non-numeric-string"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_value_int_cannot_read_is_refused_naming_the_field_and_the_value(
        self, value: object
    ) -> None:
        """A value int() cannot read is refused with a ValueError naming the field and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            as_int(value, "seed")
        assert str(exc_info.value) == f"seed must be an integer, got {value!r}"


class TestAsIntWithin:
    """as_int_within reads a value as as_int does, and refuses one outside its inclusive range."""

    @pytest.mark.parametrize("value", [pytest.param(1, id="low"), pytest.param(10, id="high")])
    def test_the_range_is_inclusive(self, value: int) -> None:
        """Both ends of the range are accepted."""
        assert as_int_within(value, "n_homes", 1, 10) == value

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(0, id="below"),
            pytest.param(11, id="above"),
            pytest.param(1e300, id="huge-float"),
        ],
    )
    def test_a_value_outside_the_range_is_refused_naming_the_field_the_range_and_the_value_sent(
        self, value: object
    ) -> None:
        """The refusal shows the value as sent (1e300 reads 1e+300), not the int it converts to."""
        with pytest.raises(ValueError) as exc_info:
            as_int_within(value, "n_homes", 1, 10)
        assert str(exc_info.value) == f"n_homes must be between 1 and 10, got {value!r}"

    def test_a_value_int_cannot_read_gets_the_as_int_refusal(self) -> None:
        """A value int() cannot read is refused as as_int refuses it, before any range check."""
        with pytest.raises(ValueError) as exc_info:
            as_int_within(float("inf"), "n_homes", 1, 10)
        assert str(exc_info.value) == "n_homes must be an integer, got inf"


class TestAsWholeNumber:
    """as_whole_number reads a value as as_finite_float does, as the int it equals, and refuses one with a fractional part."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(7, 7, id="integer"),
            pytest.param(7.0, 7, id="whole-float"),
            pytest.param("7", 7, id="numeric-string"),
            pytest.param("7.0", 7, id="whole-float-string"),
            pytest.param(-3, -3, id="negative"),
        ],
    )
    def test_a_whole_number_is_read_as_the_int_it_equals(
        self, value: object, expected: int
    ) -> None:
        """A whole number, or a string float() reads as one, is returned as the int it equals, not as a float."""
        number = as_whole_number(value, "n_homes")
        assert number == expected
        assert type(number) is int

    @pytest.mark.parametrize(
        "value", [pytest.param(2.5, id="float"), pytest.param("2.5", id="numeric-string")]
    )
    def test_a_number_with_a_fractional_part_is_refused_naming_the_field_and_the_value(
        self, value: object
    ) -> None:
        """A number with a fractional part is refused, not truncated."""
        with pytest.raises(ValueError) as exc_info:
            as_whole_number(value, "n_homes")
        assert str(exc_info.value) == f"n_homes must be a whole number, got {value!r}"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("inf"), id="infinity"),
            pytest.param("abc", id="non-numeric-string"),
            pytest.param(True, id="true"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_gets_the_as_finite_float_refusal(
        self, value: object
    ) -> None:
        """A value as_finite_float refuses is refused as it refuses it, before any whole-number check."""
        with pytest.raises(ValueError) as exc_info:
            as_whole_number(value, "n_homes")
        assert str(exc_info.value) == f"n_homes must be a finite number, got {value!r}"
