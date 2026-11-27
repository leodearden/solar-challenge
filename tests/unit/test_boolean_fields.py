# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.boolean_fields, the package's booleans: is_boolean, which says which values are bools, and as_boolean, the reader of boolean settings."""

import numpy as np
import pytest

from solar_challenge.boolean_fields import as_boolean, is_boolean
from solar_challenge.errors import ConfigurationError
from tests._modules_loaded_by_importing import package_modules_loaded_by_importing


def test_importing_the_module_loads_only_errors_from_the_package() -> None:
    """A fresh interpreter that imports the reader loads no other package module, so any module can import it."""
    assert package_modules_loaded_by_importing("solar_challenge.boolean_fields") == {
        "solar_challenge",
        "solar_challenge.boolean_fields",
        "solar_challenge.errors",
    }


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


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(np.True_, id="numpy-true"),
        pytest.param(np.False_, id="numpy-false"),
    ],
)
def test_a_bool_is_returned_as_the_python_bool_it_is(value: object) -> None:
    read = as_boolean(value, "flag")

    assert read == bool(value)
    assert type(read) is bool


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="null"),
        pytest.param(0, id="zero"),
        pytest.param(1, id="one"),
        pytest.param(0.0, id="zero-float"),
        pytest.param(np.int64(1), id="numpy-int64"),
        pytest.param("", id="empty-string"),
        pytest.param("true", id="the-word-true"),
        pytest.param("false", id="the-word-false"),
        pytest.param("no", id="the-word-no"),
        pytest.param([], id="empty-list"),
        pytest.param([True], id="list-of-true"),
        pytest.param({}, id="empty-mapping"),
        pytest.param({"a": 1}, id="mapping"),
    ],
)
def test_any_other_value_is_refused_naming_the_field_and_the_value(value: object) -> None:
    """A truthiness read would take each of these as true or false; the reader refuses them all."""
    with pytest.raises(ConfigurationError) as exc_info:
        as_boolean(value, "flag")

    assert str(exc_info.value) == f"flag must be true or false, got {value!r}"
