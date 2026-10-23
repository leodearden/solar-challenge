# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of number settings: each takes a value and its field's name, and returns the number read or refuses the value with a ConfigurationError naming the field and the value.

A valid number setting is a finite number, never a bool, and a whole number where a count is
meant. The module imports no package module but errors and whole_numbers, so any module can
import it.

An integer field reads through as_whole_number, or as_whole_number_within when it has
bounds, so a fraction or a boolean is refused, not truncated or read as 1.
"""

import math
from dataclasses import dataclass
from typing import Any, Final, NoReturn, TypeVar

from solar_challenge.errors import ConfigurationError
from solar_challenge.whole_numbers import whole_number

_Number = TypeVar("_Number", int, float)


@dataclass(frozen=True)
class Interval:
    """The finite numbers from *low* to *high*, each bound included unless it is open; an infinite bound is no bound."""

    low: float = -math.inf
    high: float = math.inf
    low_open: bool = False
    high_open: bool = False

    def __post_init__(self) -> None:
        if not self.low <= self.high:
            raise ValueError(
                f"an Interval's low bound must be at most its high bound, got low={self.low!r} and high={self.high!r}"
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


def as_finite_float(value: Any, field: str) -> float:
    """Return *value* read as float() reads it, refusing a boolean or one that is not a finite number.

    Raises:
        ConfigurationError: If *value* is a boolean, which float() reads as 1.0 or 0.0,
            float() cannot read it (not a number or numeric string), it is an integer too
            large for a float, or it is infinite or NaN; the error names *field* and *value*.
    """
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        _refuse(field, "a finite number", value, cause=exc)
    if isinstance(value, bool) or not math.isfinite(number):
        _refuse(field, "a finite number", value)
    return number


def as_finite_float_within(value: Any, field: str, low: float, high: float) -> float:
    """Return *value* read by :func:`as_finite_float`, refusing one outside *low* to *high* inclusive.

    Raises:
        ConfigurationError: If :func:`as_finite_float` refuses *value*, or it is outside
            *low* to *high*; the range error names *field*, the range and *value*.
    """
    return _within(as_finite_float(value, field), value, field, low, high)


def as_whole_number(value: Any, field: str) -> int:
    """Return *value* read by :func:`as_finite_float` as the int it equals, refusing one with a fractional part.

    Raises:
        ConfigurationError: If :func:`as_finite_float` refuses *value*, or it has a
            fractional part; the whole-number error names *field* and *value*.
    """
    whole = whole_number(as_finite_float(value, field))
    if whole is None:
        _refuse(field, "a whole number", value)
    return whole


def as_whole_number_within(value: Any, field: str, low: int, high: int) -> int:
    """Return *value* read by :func:`as_whole_number`, refusing one outside *low* to *high* inclusive.

    Raises:
        ConfigurationError: If :func:`as_whole_number` refuses *value*, or it is outside
            *low* to *high*; the range error names *field*, the range and *value*.
    """
    return _within(as_whole_number(value, field), value, field, low, high)


def _within(number: _Number, value: Any, field: str, low: float, high: float) -> _Number:
    """Return *number*, the *field* value read from *value*, refusing one outside *low* to *high* inclusive.

    Raises:
        ConfigurationError: If *number* is outside *low* to *high*; the error names *field*,
            the range and *value*, the value as given.
    """
    if not low <= number <= high:
        _refuse(field, f"between {low} and {high}", value)
    return number


def _refuse(field: str, requirement: str, value: Any, *, cause: Exception | None = None) -> NoReturn:
    """Raise the refusal of *value*, given for *field*, which must be *requirement*, from *cause*."""
    raise ConfigurationError(f"{field} must be {requirement}, got {value!r}") from cause
