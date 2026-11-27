# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_html_select_options.py, the reader of the text each option of a page's select shows, keyed by the value it submits.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a page test that uses it pass vacuously.
"""

import pytest

from tests._html_select_options import option_texts, options_of_each


def test_option_texts_keys_the_text_of_each_option_of_the_select_by_its_value() -> None:
    page = (
        '<select x-model="location"><option value="bristol">Bristol, UK</option>'
        '<option value="london">London, UK</option></select>'
    )

    assert option_texts(page, {"x-model": "location"}) == {
        "bristol": "Bristol, UK",
        "london": "London, UK",
    }


def test_an_option_text_has_character_references_decoded_and_whitespace_collapsed() -> None:
    page = (
        '<select id="location"><option value="bristol">\n'
        "    Bristol, UK (51.45&deg;N,\n    2.58&deg;W)\n</option></select>"
    )

    assert option_texts(page, {"id": "location"}) == {"bristol": "Bristol, UK (51.45°N, 2.58°W)"}


def test_only_the_options_of_the_select_carrying_the_attributes_are_read() -> None:
    page = (
        '<select x-model="location"><option value="custom">Custom coordinates...</option></select>'
        '<select x-model="seg_preset"><option value="custom">Custom rate</option></select>'
    )

    assert option_texts(page, {"x-model": "location"}) == {"custom": "Custom coordinates..."}


def test_an_option_with_no_value_attribute_is_keyed_by_its_text() -> None:
    page = (
        '<select id="mode"><option>Linear</option>'
        '<option value="geometric">Geometric</option></select>'
    )

    assert option_texts(page, {"id": "mode"}) == {"Linear": "Linear", "geometric": "Geometric"}


@pytest.mark.parametrize(
    "page",
    [
        pytest.param(
            '<select name="seg_preset"><option value="a">A</option></select>',
            id="no-select-carries-them",
        ),
        pytest.param(
            '<select name="location"><option value="a">A</option></select>'
            '<select name="location"><option value="b">B</option></select>',
            id="two-selects-carry-them",
        ),
    ],
)
def test_option_texts_raises_unless_exactly_one_select_carries_the_attributes(page: str) -> None:
    with pytest.raises(ValueError, match="exactly one select"):
        option_texts(page, {"name": "location"})


def test_a_repeated_option_value_raises_rather_than_keeping_one_text() -> None:
    page = (
        '<select id="location"><option value="bristol">Bristol, UK</option>'
        '<option value="bristol">London, UK</option></select>'
    )

    with pytest.raises(ValueError, match="'bristol' is on more than one"):
        option_texts(page, {"id": "location"})


def test_options_of_each_lists_each_carrying_selects_options_as_value_and_text_in_document_order() -> None:
    page = (
        '<select x-model="dist.type"><option value="">Fixed</option><option>Normal</option></select>'
        '<select x-model="other"><option value="x">X</option></select>'
        '<select x-model="dist.type"><option value="b">B</option><option value="a">A</option></select>'
    )

    assert options_of_each(page, {"x-model": "dist.type"}) == [
        [("", "Fixed"), ("Normal", "Normal")],
        [("b", "B"), ("a", "A")],
    ]


def test_options_of_each_reads_no_selects_when_none_carries_the_attributes() -> None:
    page = '<select x-model="other"><option value="x">X</option></select>'

    assert options_of_each(page, {"x-model": "dist.type"}) == []
