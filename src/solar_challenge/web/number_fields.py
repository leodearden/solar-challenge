# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of a web request's number fields: each takes the value sent and the field's name, and refuses with a ValueError naming that field and the value sent, the error every web caller answers with HTTP 400.

An integer field reads through as_whole_number, or as_whole_number_within when it has
bounds, so a fraction or a boolean is refused, not truncated or read as 1.
"""

import math
from typing import Any, TypeVar

from solar_challenge.whole_numbers import whole_number

_Number = TypeVar("_Number", int, float)


def as_finite_float(value: Any, field: str) -> float:
    """Return *value* read as float() reads it, refusing a boolean or one that is not a finite number.

    Raises:
        ValueError: If *value* is a boolean (JSON true or false, which float() reads as 1.0
            or 0.0), float() cannot read it (not a number or numeric string), it is an
            integer too large for a float, or it is infinite or NaN; the error names
            *field* and the value sent.
    """
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number, got {value!r}") from exc
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number, got {value!r}")
    return number


def as_finite_float_within(value: Any, field: str, low: float, high: float) -> float:
    """Return *value* read by :func:`as_finite_float`, refusing one outside *low* to *high* inclusive.

    Raises:
        ValueError: If :func:`as_finite_float` refuses *value*, or it is outside *low* to
            *high*; the range error names *field*, the range and the value sent.
    """
    return _within(as_finite_float(value, field), value, field, low, high)


def as_whole_number(value: Any, field: str) -> int:
    """Return *value* read by :func:`as_finite_float` as the int it equals, refusing one with a fractional part.

    Raises:
        ValueError: If :func:`as_finite_float` refuses *value*, or it has a fractional part;
            the whole-number error names *field* and the value sent.
    """
    whole = whole_number(as_finite_float(value, field))
    if whole is None:
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    return whole


def as_whole_number_within(value: Any, field: str, low: int, high: int) -> int:
    """Return *value* read by :func:`as_whole_number`, refusing one outside *low* to *high* inclusive.

    Raises:
        ValueError: If :func:`as_whole_number` refuses *value*, or it is outside *low* to
            *high*; the range error names *field*, the range and the value sent.
    """
    return _within(as_whole_number(value, field), value, field, low, high)


def _within(number: _Number, value: Any, field: str, low: float, high: float) -> _Number:
    """Return *number*, the *field* value read from *value*, refusing one outside *low* to *high* inclusive.

    Raises:
        ValueError: If *number* is outside *low* to *high*; the error names *field*, the
            range and *value*, the value as sent.
    """
    if not low <= number <= high:
        raise ValueError(f"{field} must be between {low} and {high}, got {value!r}")
    return number
