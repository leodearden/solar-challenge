# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.boolean_fields, the package's boolean reader."""

import json
import subprocess
import sys

import numpy as np
import pytest

from solar_challenge.boolean_fields import as_boolean
from solar_challenge.errors import ConfigurationError

_IMPORT_PROBE = """\
import json
import sys

import solar_challenge.boolean_fields

print(json.dumps(sorted(
    name for name in sys.modules if name == "solar_challenge" or name.startswith("solar_challenge.")
)))
"""


def test_importing_the_module_loads_only_errors_and_whole_numbers_from_the_package() -> None:
    """A fresh ``python -I`` interpreter that imports the reader loads no other package module, so any module can import it."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, f"importing solar_challenge.boolean_fields failed:\n{result.stderr}"
    assert json.loads(result.stdout) == [
        "solar_challenge",
        "solar_challenge.boolean_fields",
        "solar_challenge.errors",
        "solar_challenge.whole_numbers",
    ]


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
