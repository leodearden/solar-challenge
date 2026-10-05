# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readers of a web request's number fields: each takes the value sent and the field's name, and refuses with a ValueError naming that field and the value sent, the error every web caller answers with HTTP 400."""

import math
from typing import Any


def as_int(value: Any, field: str) -> int:
    """Return *value* read as int() reads it.

    Raises:
        ValueError: If int() cannot read *value* (not a number or numeric string, NaN,
            or infinite); the error names *field* and the value sent.
    """
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be an integer, got {value!r}") from exc


def as_int_within(value: Any, field: str, low: int, high: int) -> int:
    """Return *value* read by :func:`as_int`, refusing one outside *low* to *high* inclusive.

    Raises:
        ValueError: If :func:`as_int` refuses *value*, or it is outside *low* to *high*;
            the range error names *field*, the range and the value sent.
    """
    number = as_int(value, field)
    if not low <= number <= high:
        raise ValueError(f"{field} must be between {low} and {high}, got {value!r}")
    return number


def as_finite_float(value: Any, field: str) -> float:
    """Return *value* read as float() reads it, refusing one that is not a finite number.

    Raises:
        ValueError: If float() cannot read *value* (not a number or numeric string), it is
            an integer too large for a float, or it is infinite or NaN; the error names
            *field* and the value sent.
    """
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number, got {value!r}")
    return number


def as_whole_number(value: Any, field: str) -> int:
    """Return *value* read by :func:`as_finite_float` as the int it equals, refusing one with a fractional part.

    Raises:
        ValueError: If :func:`as_finite_float` refuses *value*, or it has a fractional part;
            the whole-number error names *field* and the value sent.
    """
    number = as_finite_float(value, field)
    if not number.is_integer():
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    return int(number)
