# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_html_page.py, the reader of a rendered page's doctype, elements, ids, texts and headings.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a page test that uses it pass vacuously.
"""

import pytest

from tests._html_page import (
    doctype,
    element_count,
    element_ids,
    headings,
    texts,
    texts_after,
)


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


def test_texts_lists_every_text_in_document_order_each_time_it_occurs() -> None:
    page = "<title>Compare Runs</title><h1>Compare Runs</h1><h2>No Runs Selected</h2>"

    assert texts(page) == ["Compare Runs", "Compare Runs", "No Runs Selected"]


def test_element_count_counts_the_elements_with_the_tag() -> None:
    page = "<aside><nav></nav></aside><nav><a>Runs</a></nav><footer></footer>"

    assert element_count(page, "nav") == 2


def test_element_count_counts_only_elements_carrying_every_given_attribute() -> None:
    page = (
        '<input type="text" x-model="name">'
        '<input type="hidden" x-model="name">'
        '<input type="text" x-model="saveName">'
        '<select x-model="name"></select>'
    )

    assert element_count(page, "input", {"type": "text", "x-model": "name"}) == 1


def test_an_attribute_value_matches_only_in_its_exact_case() -> None:
    page = '<input x-model="Name">'

    assert element_count(page, "input", {"x-model": "name"}) == 0


def test_tag_and_attribute_names_are_read_in_lower_case() -> None:
    page = '<NAV></NAV><Input X-Model="name">'

    assert element_count(page, "nav") == 1
    assert element_count(page, "input", {"x-model": "name"}) == 1


@pytest.mark.parametrize(
    ("tag", "attributes", "refused"),
    [
        pytest.param("Input", {"x-model": "name"}, "Input", id="tag"),
        pytest.param("input", {"X-Model": "name"}, "X-Model", id="attribute-name"),
    ],
)
def test_a_name_not_in_lower_case_raises_rather_than_counting_none(
    tag: str, attributes: dict[str, str], refused: str
) -> None:
    page = '<input x-model="name">'

    with pytest.raises(ValueError, match=f"in lower case.*; got '{refused}'$"):
        element_count(page, tag, attributes)


def test_a_repeated_attribute_keeps_its_first_value() -> None:
    page = '<input x-model="name" x-model="saveName">'

    assert element_count(page, "input", {"x-model": "name"}) == 1
    assert element_count(page, "input", {"x-model": "saveName"}) == 0


def test_an_element_inside_script_text_does_not_count() -> None:
    page = "<nav></nav><script>menu.innerHTML = '<nav></nav>';</script>"

    assert element_count(page, "nav") == 1


@pytest.mark.parametrize(
    "declaration",
    [
        pytest.param("<!DOCTYPE html>", id="upper-case"),
        pytest.param("<!doctype HTML>", id="lower-case-keyword"),
    ],
)
def test_doctype_reads_the_declared_type_in_lower_case(declaration: str) -> None:
    page = f"{declaration}<html><p>Dashboard</p></html>"

    assert doctype(page) == "html"


def test_a_legacy_doctype_keeps_its_identifiers_so_it_is_not_html() -> None:
    page = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN"><p>Dashboard</p>'

    assert doctype(page) == 'html public "-//w3c//dtd html 4.01//en"'


def test_a_page_without_a_doctype_declares_none() -> None:
    page = "<html><p>Dashboard</p></html>"

    assert doctype(page) is None


def test_a_doctype_inside_a_comment_or_script_text_does_not_count() -> None:
    page = "<!-- <!DOCTYPE html> --><script>const d = '<!DOCTYPE html>';</script><p>Dashboard</p>"

    assert doctype(page) is None


def test_a_repeated_doctype_raises_rather_than_picking_one() -> None:
    page = "<!DOCTYPE html><!DOCTYPE html><p>Dashboard</p>"

    with pytest.raises(
        ValueError, match="at most one doctype declaration on the page; found 2"
    ):
        doctype(page)


@pytest.mark.parametrize("tag", ["h1", "h2", "h3", "h4", "h5", "h6"])
def test_a_heading_at_every_level_is_listed(tag: str) -> None:
    page = f"<{tag}>PV Capacity</{tag}>"

    assert headings(page) == ["PV Capacity"]


def test_headings_lists_heading_texts_in_document_order_and_no_other_text() -> None:
    page = (
        "<h1>Fleet Simulation</h1>"
        "<p>Distribution of PV system sizes (kW)</p>"
        "<h3>PV Capacity</h3>"
        '<label><span class="sr-only">PV Capacity </span>Mean</label>'
        "<h3>Battery Capacity</h3>"
    )

    assert headings(page) == ["Fleet Simulation", "PV Capacity", "Battery Capacity"]


def test_a_heading_text_is_all_its_character_data_decoded_and_collapsed() -> None:
    page = "<h2>Battery &amp;\n        <em>Finance</em></h2>"

    assert headings(page) == ["Battery & Finance"]


def test_a_heading_with_no_text_reads_as_empty() -> None:
    page = '<h3 x-text="title"></h3>'

    assert headings(page) == [""]


def test_a_heading_inside_script_text_does_not_count() -> None:
    page = (
        "<h1>Dashboard</h1><script>panel.innerHTML = '<h3>PV Capacity</h3>';</script>"
    )

    assert headings(page) == ["Dashboard"]


@pytest.mark.parametrize(
    "page",
    [
        pytest.param("<h3>PV Capacity<h3>Battery Capacity</h3>", id="next-heading"),
        pytest.param("<h3>PV Capacity<p>Distribution</p>", id="end-of-page"),
    ],
)
def test_a_heading_left_open_raises_rather_than_guessing_where_it_ends(
    page: str,
) -> None:
    with pytest.raises(ValueError, match="closed by its end tag.*; 1 left open"):
        headings(page)
