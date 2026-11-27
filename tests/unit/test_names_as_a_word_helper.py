# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_names_as_a_word.py, the check that a message names a value as a word of its own."""

import pytest

from tests._names_as_a_word import names_as_a_word


@pytest.mark.parametrize(
    ("text", "value"),
    [
        pytest.param("must be finite, got nan £/kWh", float("nan"), id="nan"),
        pytest.param("got -inf £/kWh", float("-inf"), id="a-negative-value-with-its-sign"),
        pytest.param("got -0.1 £/kWh", -0.1, id="a-negative-decimal"),
        pytest.param("A minute of the day is 0 to 1439, got 1440", 1440, id="at-the-end"),
        pytest.param("inf", float("inf"), id="the-whole-text"),
        pytest.param("no period covers 23:00-07:00", "23:00-07:00", id="a-clock-range"),
    ],
)
def test_a_value_standing_as_a_word_of_its_own_is_named(text: str, value: object) -> None:
    assert names_as_a_word(text, value)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        pytest.param("got -inf £/kWh", float("inf"), id="inside-its-negative"),
        pytest.param("got an infinite rate", float("inf"), id="inside-a-longer-word"),
        pytest.param("got 0.15 £/kWh", 0.1, id="the-start-of-a-longer-decimal"),
        pytest.param("got 1.5", 1, id="the-whole-part-of-a-decimal"),
        pytest.param("got 14400", 1440, id="the-start-of-a-longer-number"),
        pytest.param("got 21440", 1440, id="the-end-of-a-longer-number"),
    ],
)
def test_a_value_only_inside_a_longer_word_or_number_is_not_named(
    text: str, value: object
) -> None:
    assert not names_as_a_word(text, value)
