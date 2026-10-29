# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of number settings: each takes a value and its field's name, and returns the number read or refuses the value with a ConfigurationError naming the field and the value.

A valid number setting is a finite number, never a bool, a whole number where a count is
meant, and inside the field's Interval. The module imports no package module but errors and
whole_numbers, so any module can import it.

An integer field reads through as_whole_number, so a fraction or a boolean is refused, not
truncated or read as 1.
"""

import math
import numbers
from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from solar_challenge.errors import ConfigurationError
from solar_challenge.whole_numbers import is_boolean, whole_number

_Number = TypeVar("_Number", int, float)


@dataclass(frozen=True)
class Interval:
    """A non-empty interval of finite numbers, from *low* to *high*, each bound included unless it is open; an infinite bound is no bound."""

    low: float = -math.inf
    high: float = math.inf
    low_open: bool = False
    high_open: bool = False

    def __post_init__(self) -> None:
        if not self.low <= self.high:
            raise ValueError(
                f"an Interval's low bound must be at most its high bound, got low={self.low!r} and high={self.high!r}"
            )
        if self.low == self.high and not self.admits(self.low):
            raise ValueError(
                f"an Interval must admit a finite number, so equal bounds must be finite and neither open, got {self!r}"
            )

    def admits(self, number: float) -> bool:
        """Whether *number* is finite and inside the bounds; comparing it, never converting it, so an int too large for a float is compared too."""
        return (
            -math.inf < number < math.inf
            and (self.low < number if self.low_open else self.low <= number)
            and (number < self.high if self.high_open else number <= self.high)
        )

    def __str__(self) -> str:
        """The bounds as a refusal phrases them, each printed as given: "between 0 and 360", "greater than 0 and at most 1", or "" when there are none."""
        bounded_below, bounded_above = self.low > -math.inf, self.high < math.inf
        if bounded_below and bounded_above and not (self.low_open or self.high_open):
            return f"between {self.low} and {self.high}"
        phrases: list[str] = []
        if bounded_below:
            phrases.append(f"greater than {self.low}" if self.low_open else f"at least {self.low}")
        if bounded_above:
            phrases.append(f"less than {self.high}" if self.high_open else f"at most {self.high}")
        return " and ".join(phrases)


POSITIVE: Final = Interval(0, math.inf, low_open=True)
NON_NEGATIVE: Final = Interval(0, math.inf)
FRACTION: Final = Interval(0, 1, low_open=True)
UNIT_INTERVAL: Final = Interval(0, 1)


def as_finite_float(value: Any, field: str, within: Interval = Interval()) -> float:
    """Return *value* read as float() reads it, refusing a boolean, one that is not a finite number, or one *within* does not admit.

    Raises:
        ConfigurationError: If *value* is a boolean, Python's or numpy's, which float() reads
            as 1.0 or 0.0, float() cannot read it (not a number or numeric string), it is an
            integer too large for a float, or it is infinite or NaN; or if *within* does not
            admit it. The error names *field* and *value*, and *within* when it does not
            admit *value*.
    """
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError.must_be(field, "a finite number", got=value) from exc
    if is_boolean(value) or not math.isfinite(number):
        raise ConfigurationError.must_be(field, "a finite number", got=value)
    return _admitted(number, within, field, value)


def as_whole_number(value: Any, field: str, within: Interval = Interval()) -> int:
    """Return *value* read by :func:`as_finite_float` as the int it equals, refusing one with a fractional part or one *within* does not admit.

    An integral value, Python's or numpy's, is returned as the int it is, never rounded
    through a float; any other value is read through float().

    Raises:
        ConfigurationError: If :func:`as_finite_float` refuses *value*, it has a fractional
            part, or *within* does not admit it, in that order; the error names *field* and
            *value*, and *within* when it does not admit *value*.
    """
    number = as_finite_float(value, field)
    whole = int(value) if isinstance(value, numbers.Integral) else whole_number(number)
    if whole is None:
        raise ConfigurationError.must_be(field, "a whole number", got=value)
    return _admitted(whole, within, field, value)


def as_finite_floats(values: object, field: str, within: Interval = Interval()) -> tuple[float, ...]:
    """Return *values*, a list, as the tuple of its elements, each read by :func:`as_finite_float` under the name {field}[{i}].

    Raises:
        ConfigurationError: If *values* is text, a mapping, a set or not iterable, naming
            *field* and *values*; or if :func:`as_finite_float` refuses an element.
    """
    return _read_each(as_finite_float, values, field, within, "finite numbers")


def as_whole_numbers(values: object, field: str, within: Interval = Interval()) -> tuple[int, ...]:
    """Return *values*, a list, as the tuple of its elements, each read by :func:`as_whole_number` under the name {field}[{i}].

    Raises:
        ConfigurationError: If *values* is text, a mapping, a set or not iterable, naming
            *field* and *values*; or if :func:`as_whole_number` refuses an element.
    """
    return _read_each(as_whole_number, values, field, within, "whole numbers")


def read_field(
    instance: object,
    field: str,
    read: Callable[[object, str, Interval], object],
    within: Interval = Interval(),
    *,
    optional: bool = False,
) -> None:
    """Read *instance*'s *field* with *read* under *within*, and store what it returns, frozen dataclass or not; an *optional* field left None stays None.

    Raises:
        ConfigurationError: If *read* refuses the field's value.
    """
    value = getattr(instance, field)
    if optional and value is None:
        return
    object.__setattr__(instance, field, read(value, field, within))


def _read_each(
    read: Callable[[Any, str, Interval], _Number], values: object, field: str, within: Interval, kind: str
) -> tuple[_Number, ...]:
    """Return each element i of *values* read by *read* as {field}[{i}], refusing *values* unless it is a list of *kind*: iterable, and neither text, a mapping nor a set, whose order is arbitrary."""
    if isinstance(values, (str, bytes, Mapping, Set)) or not isinstance(values, Iterable):
        raise ConfigurationError.must_be(field, f"a list of {kind}", got=values)
    return tuple(read(value, f"{field}[{index}]", within) for index, value in enumerate(values))


def _admitted(number: _Number, within: Interval, field: str, value: Any) -> _Number:
    """Return *number*, read from *value*, the value given for *field*, refusing it if *within* does not admit it."""
    if not within.admits(number):
        raise ConfigurationError.must_be(field, str(within), got=value)
    return number
