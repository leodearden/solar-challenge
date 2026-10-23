# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.text_options: one_of, a value narrowed to the one of a closed set of text options it equals."""

from typing import Literal, get_args

import pytest

from solar_challenge.web.text_options import one_of

_Shade = Literal["light", "dark"]
_SHADES: tuple[_Shade, ...] = get_args(_Shade)


def test_a_value_equal_to_an_option_is_that_option() -> None:
    assert one_of("dark", _SHADES, "shade") == "dark"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("sepia", id="another-text"),
        pytest.param("DARK", id="an-option-in-another-case"),
        pytest.param(None, id="null"),
        pytest.param(1, id="a-number"),
    ],
)
def test_a_value_equal_to_no_option_is_refused_naming_the_field_the_value_and_each_option(value: object) -> None:
    with pytest.raises(ValueError) as refusal:
        one_of(value, _SHADES, "shade")

    assert str(refusal.value) == f"shade is {value!r}, not one of ['light', 'dark']"
