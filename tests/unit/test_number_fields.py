# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.number_fields, the package's number readers."""

import dataclasses
import json
import math
import subprocess
import sys
from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    Interval,
    as_finite_float,
    as_finite_floats,
    as_whole_number,
    as_whole_numbers,
    read_field,
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
            pytest.param(Interval(5, 5), 5, id="closed-at-one-number"),
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

    @pytest.mark.parametrize(
        ("low", "high", "low_open", "high_open"),
        [
            pytest.param(math.inf, math.inf, False, False, id="low-bound-at-infinity"),
            pytest.param(-math.inf, -math.inf, False, False, id="high-bound-at-negative-infinity"),
            pytest.param(0, 0, True, False, id="equal-bounds-open-below"),
            pytest.param(0, 0, False, True, id="equal-bounds-open-above"),
        ],
    )
    def test_an_interval_whose_equal_bounds_admit_no_finite_number_is_refused_naming_it(
        self, low: float, high: float, low_open: bool, high_open: bool
    ) -> None:
        """Equal bounds hold one number, so an infinite bound, or one either end leaves out, leaves the interval empty: a defect, refused with a plain ValueError."""
        with pytest.raises(ValueError) as exc_info:
            Interval(low, high, low_open=low_open, high_open=high_open)
        assert exc_info.type is ValueError
        assert (
            f"Interval(low={low!r}, high={high!r}, low_open={low_open!r}, high_open={high_open!r})"
            in str(exc_info.value)
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

    def test_with_no_interval_any_finite_number_is_read(self) -> None:
        assert as_finite_float(-1e308, "x") == -1e308

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
            pytest.param(np.True_, id="numpy-true"),
            pytest.param(np.False_, id="numpy-false"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_is_refused_naming_the_field_and_the_value(
        self, value: object
    ) -> None:
        """A boolean, Python's or numpy's, a value float() cannot read, one too large for a float, and ±inf or NaN are refused alike."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float(value, "pv_kw")
        assert str(exc_info.value) == f"pv_kw must be a finite number, got {value!r}"


class TestAsFiniteFloatWithAnInterval:
    """as_finite_float given an interval reads a value as it does without one, and refuses a number outside the interval, phrasing it."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [pytest.param(0.5, 0.5, id="low"), pytest.param(20, 20.0, id="high")],
    )
    def test_a_closed_interval_admits_its_bounds_and_a_value_is_read_as_a_float(
        self, value: object, expected: float
    ) -> None:
        """Both bounds of a closed interval are admitted, each returned as a float, an integer sent included."""
        number = as_finite_float(value, "pv_kw", within=Interval(0.5, 20))
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
    def test_a_value_outside_the_interval_is_refused_naming_the_field_the_interval_and_the_value_sent(
        self, value: object
    ) -> None:
        """The refusal shows the value as sent ('25' in quotes), not the float it converts to."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float(value, "pv_kw", within=Interval(0.5, 20))
        assert str(exc_info.value) == f"pv_kw must be between 0.5 and 20, got {value!r}"

    @pytest.mark.parametrize(
        ("value", "field", "within", "message"),
        [
            pytest.param(0, "capacity_kw", POSITIVE, "capacity_kw must be greater than 0, got 0", id="positive"),
            pytest.param(
                "1",
                "share",
                Interval(0, 1, high_open=True),
                "share must be at least 0 and less than 1, got '1'",
                id="open-above",
            ),
        ],
    )
    def test_a_refusal_phrases_an_open_interval(
        self, value: object, field: str, within: Interval, message: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float(value, field, within=within)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("inf"), id="infinity"),
            pytest.param("abc", id="non-numeric-string"),
            pytest.param(True, id="true"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_gets_the_finite_number_refusal(
        self, value: object
    ) -> None:
        """A value that is not a finite number is refused as such, before the interval is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_float(value, "pv_kw", within=Interval(0.5, 20))
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

    def test_with_no_interval_any_whole_number_is_read(self) -> None:
        assert as_whole_number(-(10**15), "x") == -(10**15)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(2**53 + 1, id="python-int"),
            pytest.param(np.int64(2**62 + 1), id="numpy-int64"),
            pytest.param(np.uint64(2**64 - 1), id="numpy-uint64"),
        ],
    )
    def test_an_integer_beyond_a_floats_precision_is_read_as_itself(
        self, value: int | np.integer[Any]
    ) -> None:
        """An integer, Python's or numpy's, is returned as the int it is, never rounded through a float."""
        number = as_whole_number(value, "seed")
        assert number == int(value)
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
            pytest.param(np.True_, id="numpy-true"),
        ],
    )
    def test_a_value_that_is_not_a_finite_number_gets_the_as_finite_float_refusal(
        self, value: object
    ) -> None:
        """A value as_finite_float refuses is refused as it refuses it, before any whole-number check."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(value, "n_homes")
        assert str(exc_info.value) == f"n_homes must be a finite number, got {value!r}"


class TestAsWholeNumberWithAnInterval:
    """as_whole_number given an interval reads a value as it does without one, and refuses a number outside the interval, phrasing it."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(1, 1, id="low"),
            pytest.param(10, 10, id="high"),
            pytest.param(10.0, 10, id="high-as-a-whole-float"),
        ],
    )
    def test_a_closed_interval_admits_its_bounds_and_a_value_is_read_as_the_int_it_equals(
        self, value: object, expected: int
    ) -> None:
        """Both bounds of a closed interval are admitted, each returned as the int it equals, not as a float."""
        number = as_whole_number(value, "n_homes", within=Interval(1, 10))
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
    def test_a_value_outside_the_interval_is_refused_naming_the_field_the_interval_and_the_value_sent(
        self, value: object
    ) -> None:
        """The refusal shows the value as sent (1e300 reads 1e+300), not the int it converts to."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(value, "n_homes", within=Interval(1, 10))
        assert str(exc_info.value) == f"n_homes must be between 1 and 10, got {value!r}"

    def test_a_refusal_phrases_an_open_interval(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(0, "n_homes", within=POSITIVE)
        assert str(exc_info.value) == "n_homes must be greater than 0, got 0"

    @pytest.mark.parametrize(
        "value", [pytest.param(2.5, id="inside"), pytest.param(0.5, id="outside")]
    )
    def test_a_number_with_a_fractional_part_gets_the_whole_number_refusal(
        self, value: object
    ) -> None:
        """A number with a fractional part is refused as such, before the interval is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(value, "n_homes", within=Interval(1, 10))
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
    def test_a_value_that_is_not_a_finite_number_gets_the_finite_number_refusal(
        self, value: object
    ) -> None:
        """A value that is not a finite number is refused as such, before the whole-number rule or the interval is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_number(value, "n_homes", within=Interval(1, 10))
        assert str(exc_info.value) == f"n_homes must be a finite number, got {value!r}"


class TestListReaders:
    """as_finite_floats and as_whole_numbers read a list as a tuple, each element i as as_finite_float or as_whole_number reads it under the name {field}[{i}]."""

    def test_as_finite_floats_reads_each_element_as_a_float(self) -> None:
        numbers = as_finite_floats([1, "2.5", 3.0], "rates")
        assert numbers == (1.0, 2.5, 3.0)
        assert all(type(number) is float for number in numbers)

    def test_as_whole_numbers_reads_each_element_as_the_int_it_equals(self) -> None:
        numbers = as_whole_numbers([1, 2.0, "3"], "months")
        assert numbers == (1, 2, 3)
        assert all(type(number) is int for number in numbers)

    @pytest.mark.parametrize(
        "make_values",
        [
            pytest.param(lambda: (1, 2, 3), id="tuple"),
            pytest.param(lambda: (number for number in (1, 2, 3)), id="generator"),
            pytest.param(lambda: range(1, 4), id="range"),
        ],
    )
    def test_any_iterable_of_numbers_is_read(self, make_values: Callable[[], Iterable[int]]) -> None:
        assert as_whole_numbers(make_values(), "months") == (1, 2, 3)

    @pytest.mark.parametrize(
        "read", [pytest.param(as_finite_floats, id="floats"), pytest.param(as_whole_numbers, id="whole-numbers")]
    )
    def test_an_empty_list_reads_as_an_empty_tuple(self, read: Callable[[object, str], tuple[object, ...]]) -> None:
        assert read([], "months") == ()

    def test_an_element_with_a_fractional_part_is_refused_naming_its_index_and_the_element(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_numbers([1, 2.5], "months")
        assert str(exc_info.value) == "months[1] must be a whole number, got 2.5"

    def test_an_element_that_is_not_a_finite_number_is_refused_naming_its_index_and_the_element(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            as_finite_floats([1.0, math.nan], "rates")
        assert str(exc_info.value) == "rates[1] must be a finite number, got nan"

    def test_the_interval_applies_to_each_element(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            as_whole_numbers([1, 13], "months", Interval(1, 12))
        assert str(exc_info.value) == "months[1] must be between 1 and 12, got 13"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("1,2", id="string"),
            pytest.param(b"12", id="bytes"),
            pytest.param({"a": 1}, id="mapping"),
            pytest.param({1, 2}, id="set"),
            pytest.param(frozenset({1, 2}), id="frozenset"),
            pytest.param(5, id="int"),
            pytest.param(2.5, id="float"),
            pytest.param(None, id="null"),
        ],
    )
    @pytest.mark.parametrize(
        ("read", "field", "kind"),
        [
            pytest.param(as_finite_floats, "rates", "finite numbers", id="floats"),
            pytest.param(as_whole_numbers, "months", "whole numbers", id="whole-numbers"),
        ],
    )
    def test_a_value_that_is_not_a_list_is_refused_naming_the_field_and_the_value(
        self, read: Callable[[object, str], tuple[object, ...]], field: str, kind: str, value: object
    ) -> None:
        """Text, a mapping and a set are iterable, but none is a list of numbers, a set having no order to index its elements by, so each is refused as a number is."""
        with pytest.raises(ConfigurationError) as exc_info:
            read(value, field)
        assert str(exc_info.value) == f"{field} must be a list of {kind}, got {value!r}"


@dataclasses.dataclass(frozen=True)
class _Settings:
    """A frozen input type that reads each number field with read_field, as the package's input types do."""

    number: Any
    count: Any = 1
    numbers: Any = (1,)
    optional_number: Any = None

    def __post_init__(self) -> None:
        read_field(self, "number", as_finite_float, POSITIVE)
        read_field(self, "count", as_whole_number)
        read_field(self, "numbers", as_whole_numbers)
        read_field(self, "optional_number", as_finite_float, optional=True)


class TestReadField:
    """read_field reads a field of an instance under construction with a reader, and stores in it what the reader returns."""

    def test_what_each_reader_returns_is_stored_in_the_frozen_instance(self) -> None:
        settings = _Settings(number="4", count=7.0, numbers=[1, 2.0])

        assert (settings.number, settings.count, settings.numbers) == (4.0, 7, (1, 2))
        assert type(settings.number) is float
        assert type(settings.count) is int
        assert [type(number) for number in settings.numbers] == [int, int]

    def test_the_interval_is_passed_to_the_reader(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            _Settings(number=0)
        assert str(exc_info.value) == "number must be greater than 0, got 0"

    def test_none_is_refused_where_the_field_is_not_optional(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            _Settings(number=None)
        assert str(exc_info.value) == "number must be a finite number, got None"

    def test_an_optional_field_left_none_stays_none(self) -> None:
        assert _Settings(number=1).optional_number is None

    def test_an_optional_field_given_a_value_stores_what_was_read(self) -> None:
        assert _Settings(number=1, optional_number="2.5").optional_number == 2.5

    def test_an_optional_field_given_a_value_that_is_not_a_finite_number_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            _Settings(number=1, optional_number=math.nan)
        assert str(exc_info.value) == "optional_number must be a finite number, got nan"
