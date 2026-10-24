# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.run_names: is_run_name and require_run_name, what can name a run."""

import re

import pytest

from solar_challenge.web.run_names import is_run_name, require_run_name

_RUN_NAMES = ("North Roof", " North Roof ")
_RUN_NAME_IDS = ("a-name", "a-name-between-spaces")
_NOT_RUN_NAMES = (None, "", "   ", "\t\n", 5)
_NOT_RUN_NAME_IDS = ("none", "empty", "spaces", "tab-and-newline", "a-number")


@pytest.mark.parametrize("name", _RUN_NAMES, ids=_RUN_NAME_IDS)
def test_a_name_holding_a_character_other_than_whitespace_is_required_unchanged(name: str) -> None:
    assert require_run_name(name) == name


@pytest.mark.parametrize("name", _NOT_RUN_NAMES, ids=_NOT_RUN_NAME_IDS)
def test_a_name_that_is_no_string_or_holds_only_whitespace_is_refused_naming_the_field_and_the_value(
    name: object,
) -> None:
    with pytest.raises(ValueError, match="^" + re.escape(f"name is {name!r}")):
        require_run_name(name)


@pytest.mark.parametrize(
    ("name", "names_a_run"),
    [(name, True) for name in _RUN_NAMES] + [(name, False) for name in _NOT_RUN_NAMES],
    ids=_RUN_NAME_IDS + _NOT_RUN_NAME_IDS,
)
def test_is_run_name_holds_for_exactly_the_names_require_run_name_returns(name: object, names_a_run: bool) -> None:
    assert is_run_name(name) is names_a_run
