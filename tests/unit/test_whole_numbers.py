# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for whole_number, the rule a configured count is held to, and is_boolean, which says which values are bools."""

import math

import numpy as np
import pytest

from solar_challenge.whole_numbers import is_boolean, whole_number


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(True, True, id="true"),
        pytest.param(False, True, id="false"),
        pytest.param(np.True_, True, id="numpy-true"),
        pytest.param(np.False_, True, id="numpy-false"),
        pytest.param(1, False, id="int-one"),
        pytest.param(0, False, id="int-zero"),
        pytest.param(1.0, False, id="float"),
        pytest.param(np.int64(1), False, id="numpy-int64"),
        pytest.param(np.float64(1.0), False, id="numpy-float64"),
        pytest.param("True", False, id="string"),
        pytest.param(None, False, id="none"),
    ],
)
def test_a_bool_is_one_of_python_s_or_numpy_s_and_nothing_else(value: object, expected: bool) -> None:
    """Python's and numpy's bools are bools; a number equal to 1 or 0, and the text "True", are not."""
    assert is_boolean(value) is expected
