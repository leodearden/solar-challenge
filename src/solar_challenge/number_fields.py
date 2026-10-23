# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of number settings: each takes a value and its field's name, and returns the number read or refuses the value with a ConfigurationError naming the field and the value.

A valid number setting is a finite number, never a bool, a whole number where a count is
meant, and inside the field's Interval. The module imports no package module but errors and
whole_numbers, so any module can import it.

An integer field reads through as_whole_number, so a fraction or a boolean is refused, not
truncated or read as 1.
"""

import math
from dataclasses import dataclass
from typing import Any, Final, NoReturn, TypeVar

from solar_challenge.errors import ConfigurationError
from solar_challenge.whole_numbers import is_boolean, whole_number

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
        _refuse(field, "a finite number", value, cause=exc)
    if is_boolean(value) or not math.isfinite(number):
        _refuse(field, "a finite number", value)
    return _admitted(number, within, field, value)


def as_whole_number(value: Any, field: str, within: Interval = Interval()) -> int:
    """Return *value* read by :func:`as_finite_float` as the int it equals, refusing one with a fractional part or one *within* does not admit.

    Raises:
        ConfigurationError: If :func:`as_finite_float` refuses *value*, it has a fractional
            part, or *within* does not admit it, in that order; the error names *field* and
            *value*, and *within* when it does not admit *value*.
    """
    whole = whole_number(as_finite_float(value, field))
    if whole is None:
        _refuse(field, "a whole number", value)
    return _admitted(whole, within, field, value)


def _admitted(number: _Number, within: Interval, field: str, value: Any) -> _Number:
    """Return *number*, read from *value*, the value given for *field*, refusing it if *within* does not admit it."""
    if not within.admits(number):
        _refuse(field, within, value)
    return number


def _refuse(field: str, requirement: str | Interval, value: Any, *, cause: Exception | None = None) -> NoReturn:
    """Raise the refusal of *value*, given for *field*, which must be *requirement*, from *cause*."""
    raise ConfigurationError(f"{field} must be {requirement}, got {value!r}") from cause
