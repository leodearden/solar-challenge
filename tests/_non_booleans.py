# SPDX-License-Identifier: AGPL-3.0-or-later
"""Values a boolean setting refuses, as tests give them: one of each kind solar_challenge.boolean_fields.as_boolean refuses, but null.

The kinds are a number, a string, the words "false" and "no" among them, a list and a
mapping, each of which a truthiness read would take as true or false. Null is left out
because a scenario block reads a null key as absent. as_boolean's own tests, in
tests/unit/test_boolean_fields.py, cover its full matrix, so a setting read through it needs
only one value of each kind.

Usage::

    from tests._non_booleans import NON_BOOLEANS

    @pytest.mark.parametrize("value", NON_BOOLEANS)
    def test_a_value_that_is_not_a_bool_is_refused_naming_it(value: object) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(use_stochastic=value)
        assert str(exc_info.value) == f"use_stochastic must be true or false, got {value!r}"
"""

import pytest

#: One value of each kind as_boolean refuses, but null.
NON_BOOLEANS = (
    pytest.param(0, id="zero"),
    pytest.param(1, id="one"),
    pytest.param("", id="empty-string"),
    pytest.param("false", id="the-word-false"),
    pytest.param("no", id="the-word-no"),
    pytest.param([], id="empty-list"),
    pytest.param({}, id="empty-mapping"),
    pytest.param({"a": 1}, id="mapping"),
)
