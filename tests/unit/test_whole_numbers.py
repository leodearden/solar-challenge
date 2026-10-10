# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for whole_number, the rule a configured count is held to."""

import math

import numpy as np
import pytest

from solar_challenge.whole_numbers import whole_number


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(20.5, id="fraction"),
        pytest.param(True, id="bool"),
        pytest.param(np.True_, id="numpy-bool"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
        pytest.param(-math.inf, id="-inf"),
    ],
)
def test_a_value_that_is_not_a_finite_whole_number_gives_none(value: float) -> None:
    """A fraction, a bool (Python's or numpy's), a NaN or an infinity is not a whole number."""
    assert whole_number(value) is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(20, id="int"),
        pytest.param(20.0, id="float"),
        pytest.param(np.int64(20), id="numpy-int64"),
        pytest.param(np.float64(20.0), id="numpy-float64"),
    ],
)
def test_a_finite_whole_number_gives_the_plain_int_it_equals(value: float) -> None:
    """A whole number of any numeric type gives the plain int it equals."""
    whole = whole_number(value)

    assert whole == 20
    assert type(whole) is int


def test_an_int_too_large_for_a_float_is_a_whole_number() -> None:
    """An int too large for a float is finite and whole, so it gives itself rather than an OverflowError."""
    assert whole_number(10**400) == 10**400
