# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.text_options: one_of and read_one_of, a value narrowed to the one of a closed set of text options it equals."""

from typing import Literal, get_args

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.web.text_options import one_of, read_one_of

_Shade = Literal["light", "dark"]
_SHADES: tuple[_Shade, ...] = get_args(_Shade)

_VALUES_EQUAL_TO_NO_OPTION = [
    pytest.param("sepia", id="another-text"),
    pytest.param("DARK", id="an-option-in-another-case"),
    pytest.param(None, id="null"),
    pytest.param(1, id="a-number"),
]


def test_a_value_equal_to_an_option_is_that_option() -> None:
    assert one_of("dark", _SHADES, "shade") == "dark"


@pytest.mark.parametrize("value", _VALUES_EQUAL_TO_NO_OPTION)
def test_a_value_equal_to_no_option_is_refused_naming_the_field_the_value_and_each_option(value: object) -> None:
    with pytest.raises(ValueError) as refusal:
        one_of(value, _SHADES, "shade")

    assert str(refusal.value) == f"shade is {value!r}, not one of ['light', 'dark']"
    assert type(refusal.value) is ValueError, "a stored value outside its options is a defect, not a request refusal"


def test_a_requests_value_equal_to_an_option_is_that_option() -> None:
    assert read_one_of("dark", _SHADES, "shade") == "dark"


@pytest.mark.parametrize("value", _VALUES_EQUAL_TO_NO_OPTION)
def test_a_requests_value_equal_to_no_option_is_refused_as_one_of_refuses_it(value: object) -> None:
    with pytest.raises(ValueError) as expected:
        one_of(value, _SHADES, "shade")
    with pytest.raises(ConfigurationError) as refusal:
        read_one_of(value, _SHADES, "shade")

    assert str(refusal.value) == str(expected.value)
