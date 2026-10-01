# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_html_page.py, the reader of a rendered page's element ids and texts.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a page test that uses it pass vacuously.
"""

import pytest

from tests._html_page import element_ids, texts_after


def test_element_ids_come_from_tags_and_not_from_script_text() -> None:
    page = (
        '<div id="chart-sankey"></div><input id="pv_kw">'
        "<script>panel.innerHTML = '<div id=\"chart-financial\"></div>';</script>"
    )

    assert element_ids(page) == {"chart-sankey", "pv_kw"}


def test_a_repeated_id_raises_rather_than_counting_once() -> None:
    page = '<div id="chart-sankey"></div><p id="main-content"></p><div id="chart-sankey"></div>'

    with pytest.raises(ValueError, match="'chart-sankey' is on 2 elements"):
        element_ids(page)


def test_texts_after_returns_the_following_texts_in_document_order() -> None:
    page = (
        "<p>Total Generation</p>\n"
        '<div class="mt-1">\n    <span>22.9</span>\n    <span>kWh</span>\n</div>\n'
        "<p>Total Demand</p>"
    )

    assert texts_after(page, "Total Generation", 2) == ["22.9", "kWh"]


def test_an_attribute_value_is_not_a_text() -> None:
    page = '<p title="Total Demand">Total Demand</p><span>12.0</span>'

    assert texts_after(page, "Total Demand", 1) == ["12.0"]


def test_script_and_style_content_is_not_a_text() -> None:
    page = (
        "<p>Total Demand</p>"
        '<script>const unit = "kW";</script><style>.kWh { color: red; }</style>'
        "<span>kWh</span>"
    )

    assert texts_after(page, "Total Demand", 1) == ["kWh"]


def test_a_text_has_character_references_decoded_and_whitespace_collapsed() -> None:
    page = "<button>Battery &amp;\n        Finance</button><span>Analysis</span>"

    assert texts_after(page, "Battery & Finance", 1) == ["Analysis"]


@pytest.mark.parametrize(
    "near_miss",
    [
        pytest.param("Total Generation (AC)", id="longer-text"),
        pytest.param("Total generation", id="other-case"),
    ],
)
def test_a_text_that_is_not_exactly_the_label_does_not_match(near_miss: str) -> None:
    page = f"<p>{near_miss}</p><span>22.9</span>"

    with pytest.raises(ValueError, match="'Total Generation'.*found 0"):
        texts_after(page, "Total Generation", 1)


def test_a_repeated_label_raises_rather_than_picking_one() -> None:
    page = "<p>Total Demand</p><span>12.0</span><p>Total Demand</p><span>5.7</span>"

    with pytest.raises(ValueError, match="'Total Demand'.*found 2"):
        texts_after(page, "Total Demand", 1)
