# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of number settings: each takes a value and its field's name, and returns the number read or refuses the value with a ConfigurationError naming the field and the value.

A valid number setting is a finite number, never a bool, and a whole number where a count is
meant. The module imports no package module but errors and whole_numbers, so any module can
import it.

An integer field reads through as_whole_number, or as_whole_number_within when it has
bounds, so a fraction or a boolean is refused, not truncated or read as 1.
"""

import math
from typing import Any, NoReturn, TypeVar

from solar_challenge.errors import ConfigurationError
from solar_challenge.whole_numbers import whole_number

_Number = TypeVar("_Number", int, float)


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
