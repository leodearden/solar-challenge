# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.number_fields, the package's number readers."""

import dataclasses
import json
import math
import subprocess
import sys

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    Interval,
    as_finite_float,
    as_finite_float_within,
    as_whole_number,
    as_whole_number_within,
)

_IMPORT_PROBE = """\
import json
import sys

import solar_challenge.number_fields

print(json.dumps(sorted(
    name for name in sys.modules if name == "solar_challenge" or name.startswith("solar_challenge.")
)))
"""


def test_importing_the_module_loads_only_errors_and_whole_numbers_from_the_package() -> None:
    """A fresh ``python -I`` interpreter that imports the readers loads no other package module, so any module can import them."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, f"importing solar_challenge.number_fields failed:\n{result.stderr}"
    assert json.loads(result.stdout) == [
        "solar_challenge",
        "solar_challenge.errors",
        "solar_challenge.number_fields",
        "solar_challenge.whole_numbers",
    ]


class TestInterval:
    """An Interval is a frozen value: it admits the finite numbers inside its bounds, and its str() phrases them for a refusal."""

    @pytest.mark.parametrize(
        ("interval", "text"),
        [
            pytest.param(Interval(), "", id="unbounded"),
            pytest.param(POSITIVE, "greater than 0", id="positive"),
            pytest.param(NON_NEGATIVE, "at least 0", id="non-negative"),
            pytest.param(FRACTION, "greater than 0 and at most 1", id="fraction"),
            pytest.param(UNIT_INTERVAL, "between 0 and 1", id="unit-interval"),
            pytest.param(Interval(0, 360), "between 0 and 360", id="closed"),
            pytest.param(Interval(0, 1, high_open=True), "at least 0 and less than 1", id="open-above"),
            pytest.param(
                Interval(-1, 0, low_open=True, high_open=True),
                "greater than -1 and less than 0",
                id="open-at-both-ends",
            ),
            pytest.param(Interval(-500), "at least -500", id="low-bound-only"),
            pytest.param(Interval(high=23), "at most 23", id="high-bound-only"),
            pytest.param(Interval(high=0, high_open=True), "less than 0", id="open-high-bound-only"),
        ],
    )
    def test_an_interval_phrases_its_bounds(self, interval: Interval, text: str) -> None:
        """A closed interval with two finite bounds reads "between", any other names each finite bound it has, and one with neither reads empty."""
        assert str(interval) == text

    @pytest.mark.parametrize(
        ("interval", "text"),
        [
            pytest.param(Interval(0.5, 20), "between 0.5 and 20", id="fraction-and-int"),
            pytest.param(Interval(0.0, 1.0), "between 0.0 and 1.0", id="integral-floats"),
            pytest.param(
                Interval(-(2**53 - 1), 2**53 - 1),
                "between -9007199254740991 and 9007199254740991",
                id="ints-beyond-six-digits",
            ),
        ],
    )
    def test_a_bound_prints_as_the_number_given(self, interval: Interval, text: str) -> None:
        """Each bound prints as str() prints it, so an integral float keeps its .0 and a large int prints in full."""
        assert str(interval) == text

    @pytest.mark.parametrize(
        ("interval", "number"),
        [
            pytest.param(POSITIVE, 5e-324, id="positive-smallest-float"),
            pytest.param(Interval(), -1e308, id="unbounded-large-negative"),
            pytest.param(Interval(), 10**400, id="unbounded-int-too-large-for-a-float"),
            pytest.param(Interval(0, 360), 0, id="closed-low-bound"),
            pytest.param(Interval(0, 360), 360, id="closed-high-bound"),
            pytest.param(Interval(0, 1, high_open=True), 0, id="open-above-low-bound"),
            pytest.param(FRACTION, 1, id="fraction-high-bound"),
        ],
    )
    def test_an_interval_admits_a_finite_number_inside_its_bounds(
        self, interval: Interval, number: float
    ) -> None:
        """A closed bound admits itself, and an int too large for a float is compared, not converted."""
        assert interval.admits(number) is True

    @pytest.mark.parametrize(
        ("interval", "number"),
        [
            pytest.param(POSITIVE, math.nan, id="positive-nan"),
            pytest.param(POSITIVE, math.inf, id="positive-infinity"),
            pytest.param(POSITIVE, -math.inf, id="positive-negative-infinity"),
            pytest.param(POSITIVE, 0, id="positive-zero"),
            pytest.param(Interval(), math.nan, id="unbounded-nan"),
            pytest.param(Interval(), math.inf, id="unbounded-infinity"),
            pytest.param(Interval(), -math.inf, id="unbounded-negative-infinity"),
            pytest.param(Interval(0, 360), -0.5, id="closed-below"),
            pytest.param(Interval(0, 360), 360.5, id="closed-above"),
            pytest.param(Interval(0, 1, high_open=True), 1, id="open-above-high-bound"),
            pytest.param(FRACTION, 0, id="fraction-low-bound"),
        ],
    )
    def test_an_interval_refuses_a_number_outside_its_bounds_or_not_finite(
        self, interval: Interval, number: float
    ) -> None:
        """An open bound refuses itself, and NaN and ±inf are refused by every interval, an unbounded one included."""
        assert interval.admits(number) is False

    def test_intervals_with_the_same_bounds_are_equal_and_hash_alike(self) -> None:
        assert Interval(0, 1) == UNIT_INTERVAL
        assert hash(Interval(0, 1)) == hash(UNIT_INTERVAL)

    def test_an_interval_is_frozen(self) -> None:
        interval = Interval(0, 1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            interval.low = 0.5

    @pytest.mark.parametrize(
        ("low", "high"),
        [
            pytest.param(1, 0, id="low-above-high"),
            pytest.param(math.nan, 1, id="nan-low"),
            pytest.param(0, math.nan, id="nan-high"),
        ],
    )
    def test_an_interval_whose_low_bound_is_not_at_most_its_high_bound_is_refused_naming_both(
        self, low: float, high: float
    ) -> None:
        """Bounds are written by code, so broken ones are a defect, refused with a plain ValueError rather than a ConfigurationError."""
        with pytest.raises(ValueError) as exc_info:
            Interval(low, high)
        assert exc_info.type is ValueError
        assert repr(low) in str(exc_info.value)
        assert repr(high) in str(exc_info.value)


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
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float(value, "pv_kw")
        assert str(exc_info.value) == f"pv_kw must be a finite number, got {value!r}"


class TestAsFiniteFloatWithin:
    """as_finite_float_within reads a value as as_finite_float does, and refuses one outside its inclusive range."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [pytest.param(0.5, 0.5, id="low"), pytest.param(20, 20.0, id="high")],
    )
    def test_the_range_is_inclusive_and_a_value_is_read_as_a_float(
        self, value: object, expected: float
    ) -> None:
        """Both ends of the range are accepted, each returned as a float, an integer sent included."""
        number = as_finite_float_within(value, "pv_kw", 0.5, 20)
        assert number == expected
        assert isinstance(number, float)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(0.49, id="below"),
            pytest.param(20.5, id="above"),
            pytest.param("25", id="numeric-string-above"),
        ],
    )
    def test_a_value_outside_the_range_is_refused_naming_the_field_the_range_and_the_value_sent(
        self, value: object
    ) -> None:
        """The refusal shows the value as sent ('25' in quotes), not the float it converts to."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float_within(value, "pv_kw", 0.5, 20)
        assert str(exc_info.value) == f"pv_kw must be between 0.5 and 20, got {value!r}"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("inf"), id="infinity"),
            pytest.param("abc", id="non-numeric-string"),
            pytest.param(True, id="true"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_gets_the_as_finite_float_refusal(
        self, value: object
    ) -> None:
        """A value as_finite_float refuses is refused as it refuses it, before any range check."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float_within(value, "pv_kw", 0.5, 20)
        assert str(exc_info.value) == f"pv_kw must be a finite number, got {value!r}"


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
        with pytest.raises(ConfigurationError) as exc_info:
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
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(value, "n_homes")
        assert str(exc_info.value) == f"n_homes must be a finite number, got {value!r}"


class TestAsWholeNumberWithin:
    """as_whole_number_within reads a value as as_whole_number does, and refuses one outside its inclusive range."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(1, 1, id="low"),
            pytest.param(10, 10, id="high"),
            pytest.param(10.0, 10, id="high-as-a-whole-float"),
        ],
    )
    def test_the_range_is_inclusive_and_a_value_is_read_as_the_int_it_equals(
        self, value: object, expected: int
    ) -> None:
        """Both ends of the range are accepted, each returned as the int it equals, not as a float."""
        number = as_whole_number_within(value, "n_homes", 1, 10)
        assert number == expected
        assert type(number) is int

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
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number_within(value, "n_homes", 1, 10)
        assert str(exc_info.value) == f"n_homes must be between 1 and 10, got {value!r}"

    @pytest.mark.parametrize(
        "value", [pytest.param(2.5, id="in-range"), pytest.param(0.5, id="out-of-range")]
    )
    def test_a_number_with_a_fractional_part_gets_the_as_whole_number_refusal(
        self, value: object
    ) -> None:
        """A number with a fractional part is refused as as_whole_number refuses it, before any range check."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number_within(value, "n_homes", 1, 10)
        assert str(exc_info.value) == f"n_homes must be a whole number, got {value!r}"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("inf"), id="infinity"),
            pytest.param("abc", id="non-numeric-string"),
            pytest.param(True, id="true"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_gets_the_as_finite_float_refusal(
        self, value: object
    ) -> None:
        """A value as_finite_float refuses is refused as it refuses it, before any whole-number or range check."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number_within(value, "n_homes", 1, 10)
        assert str(exc_info.value) == f"n_homes must be a finite number, got {value!r}"
