# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_html_page.py, the reader of a rendered page's doctype, elements, attributes, ids, texts, headings, script texts, renderChart targets, the figure each call passes and the figure each chart container carries.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a page test that uses it pass vacuously.
"""

import re

import pytest

from tests._html_page import (
    chart_figures,
    counts_of,
    doctype,
    element_attributes,
    element_count,
    element_ids,
    headings,
    render_chart_figure,
    render_chart_targets,
    script_texts,
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


def test_element_attributes_lists_the_attributes_of_each_element_with_the_tag_in_document_order() -> (
    None
):
    page = (
        '<script src="/static/a.js"></script>'
        '<link rel="stylesheet" href="/static/s.css">'
        '<script src="/static/b.js" integrity="sha384-b"></script>'
    )

    assert element_attributes(page, "script") == [
        {"src": "/static/a.js"},
        {"src": "/static/b.js", "integrity": "sha384-b"},
    ]


def test_a_valueless_attribute_reads_none() -> None:
    page = '<script defer src="/static/a.js"></script>'

    assert element_attributes(page, "script") == [
        {"defer": None, "src": "/static/a.js"}
    ]


def test_element_attributes_refuses_a_tag_not_in_lower_case() -> None:
    page = '<script src="/static/a.js"></script>'

    with pytest.raises(ValueError, match="in lower case.*; got 'Script'$"):
        element_attributes(page, "Script")


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


def test_counts_of_counts_the_items_equal_to_each_key() -> None:
    items = ["Simulate", "History", "Simulate"]

    assert counts_of(items, ("Simulate", "History")) == {"Simulate": 2, "History": 1}


def test_counts_of_counts_a_key_no_item_equals_as_0() -> None:
    items = ["Simulate"]

    assert counts_of(items, ("Simulate", "Scenarios")) == {
        "Simulate": 1,
        "Scenarios": 0,
    }


@pytest.mark.parametrize(
    "near_miss",
    [
        pytest.param("PV Capacity (kW)", id="longer-text"),
        pytest.param("PV capacity", id="other-case"),
    ],
)
def test_counts_of_counts_only_an_item_exactly_equal_to_the_key(near_miss: str) -> None:
    assert counts_of([near_miss], ("PV Capacity",)) == {"PV Capacity": 0}


def test_counts_of_refuses_no_keys_rather_than_equal_an_empty_expectation() -> None:
    with pytest.raises(ValueError, match="at least one key"):
        counts_of(["Simulate"], ())


def test_counts_of_refuses_a_str_rather_than_count_each_key_as_its_substring() -> None:
    page = "<h3>PV Capacity</h3>"

    with pytest.raises(ValueError, match="got a str of 20 characters"):
        counts_of(page, ("PV Capacity",))


def test_script_texts_lists_the_text_of_each_script_in_document_order() -> None:
    page = (
        '<script src="/static/js/chart-renderer.js"></script>'
        "<p>Overview</p>"
        "<script>renderChart('chart-sankey', figure);</script>"
    )

    assert script_texts(page) == ["", "renderChart('chart-sankey', figure);"]


def test_style_text_is_not_a_script_text() -> None:
    page = "<script>draw();</script><style>.chart { min-height: 400px; }</style>"

    assert script_texts(page) == ["draw();"]


def test_render_chart_targets_lists_the_id_each_call_draws_into_in_document_order() -> (
    None
):
    page = (
        "<script>renderChart('chart-sankey', figure);\n"
        '    renderChart ( "chart-daily-balance" , figure);</script>'
        "<p>Overview</p>"
        "<script>renderChart(\n        'chart-sankey', other);</script>"
    )

    assert render_chart_targets(page) == [
        "chart-sankey",
        "chart-daily-balance",
        "chart-sankey",
    ]


def test_a_render_chart_call_outside_a_script_does_not_count() -> None:
    page = (
        "<p>renderChart('chart-sankey', figure)</p>"
        "<button onclick=\"renderChart('chart-financial', figure)\">Draw</button>"
    )

    assert render_chart_targets(page) == []


@pytest.mark.parametrize(
    "commented_call",
    [
        pytest.param("// renderChart('chart-monthly', figure);\n", id="line-comment"),
        pytest.param(
            "/* renderChart('chart-monthly',\n    figure); */", id="block-comment"
        ),
    ],
)
def test_a_render_chart_call_in_a_comment_does_not_count(commented_call: str) -> None:
    page = f"<script>{commented_call} renderChart('chart-financial', figure);</script>"

    assert render_chart_targets(page) == ["chart-financial"]


def test_a_render_chart_call_in_a_string_does_not_count() -> None:
    page = (
        "<script>var note = \"renderChart('chart-monthly', figure)\";"
        " renderChart('chart-financial', figure);</script>"
    )

    assert render_chart_targets(page) == ["chart-financial"]


@pytest.mark.parametrize(
    "figure",
    [
        pytest.param("'https://re.jrc.ec.europa.eu/api'", id="line-comment-marker"),
        pytest.param("'/* figure'", id="block-comment-marker"),
        pytest.param(
            r'"{\"title\": \"PV // Grid\"}"', id="marker-after-an-escaped-quote"
        ),
    ],
)
def test_a_comment_marker_in_a_string_starts_no_comment(figure: str) -> None:
    page = (
        f"<script>renderChart('chart-sankey', {figure});"
        " renderChart('chart-financial', '*/');</script>"
    )

    assert render_chart_targets(page) == ["chart-sankey", "chart-financial"]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("_renderChart('chart-sankey', figure)", id="longer-name"),
        pytest.param("renderCharts('chart-sankey', figure)", id="name-with-suffix"),
        pytest.param("this.renderChart('chart-sankey', figure)", id="method"),
    ],
)
def test_a_call_of_another_function_does_not_count(call: str) -> None:
    page = f"<script>{call};</script>"

    assert render_chart_targets(page) == []


def test_the_declaration_of_render_chart_is_not_a_call() -> None:
    page = (
        "<script>function renderChart(elementId, jsonStr) {"
        " Plotly.newPlot(elementId, JSON.parse(jsonStr)); }"
        " renderChart('chart-sankey', figure);</script>"
    )

    assert render_chart_targets(page) == ["chart-sankey"]


@pytest.mark.parametrize(
    ("call", "named"),
    [
        pytest.param(
            "renderChart(chartId, figure)", "renderChart(chartId", id="identifier"
        ),
        pytest.param(
            "renderChart('chart-' + kind, figure)",
            "renderChart('chart-' + kind",
            id="expression",
        ),
        pytest.param(
            "renderChart(`chart-sankey`, figure)",
            "renderChart(`chart-sankey`",
            id="template-literal",
        ),
    ],
)
def test_a_call_whose_first_argument_is_not_one_quoted_id_raises_naming_it(
    call: str, named: str
) -> None:
    page = f"<script>{call};</script>"

    with pytest.raises(ValueError, match=r"quoted id.*" + re.escape(named)):
        render_chart_targets(page)


@pytest.mark.parametrize(
    ("script", "targets"),
    [
        pytest.param(
            "var quote = /'/; renderChart('chart-sankey', figure);",
            [],
            id="quote-hides-a-later-call",
        ),
        pytest.param(
            r"var absolute = /^https?:\/\//; renderChart('chart-sankey', figure);",
            [],
            id="comment-marker-hides-a-later-call",
        ),
        pytest.param(
            "var quote = /'/;"
            " var note = \"it's renderChart('chart-monthly', figure)\";",
            ["chart-monthly"],
            id="quote-counts-a-call-in-a-later-string",
        ),
        pytest.param(
            "var quote = /'/; draw(); // it's renderChart('chart-monthly', figure)",
            ["chart-monthly"],
            id="quote-counts-a-call-in-a-later-comment",
        ),
    ],
)
def test_a_regular_expression_literal_is_not_recognised_as_one(
    script: str, targets: list[str]
) -> None:
    """A known gap, pinned so that a fix updates this test and render_chart_targets' docstring together."""
    assert render_chart_targets(f"<script>{script}</script>") == targets


def test_render_chart_figure_reads_the_figure_json_the_call_drawing_into_the_id_passes() -> (
    None
):
    sankey = r'"{\"layout\": {\"title\": {\"text\": \"Energy Flows\"}}}"'
    financial = r'"{\"layout\": {\"title\": {\"text\": \"Import \u0026 export: today\u0027s \u003ctariff\u003e\"}}}"'
    page = (
        f"<script>renderChart('chart-sankey', {sankey});\n"
        f"    renderChart('chart-financial', {financial});</script>"
    )

    assert render_chart_figure(page, "chart-financial") == (
        """{"layout": {"title": {"text": "Import & export: today's <tariff>"}}}"""
    )
    assert render_chart_figure(page, "chart-sankey") == (
        '{"layout": {"title": {"text": "Energy Flows"}}}'
    )


def test_a_null_figure_reads_as_none() -> None:
    page = "<script>renderChart('chart-monthly', null);</script>"

    assert render_chart_figure(page, "chart-monthly") is None


@pytest.mark.parametrize(
    ("script", "found"),
    [
        pytest.param("renderChart('chart-sankey', null);", 0, id="no-call"),
        pytest.param(
            "renderChart('chart-financial', null);"
            " renderChart('chart-financial', \"{}\");",
            2,
            id="two-calls",
        ),
    ],
)
def test_render_chart_figure_raises_unless_exactly_one_call_draws_into_the_id(
    script: str, found: int
) -> None:
    page = f"<script>{script}</script>"

    with pytest.raises(ValueError, match=f"'chart-financial'.*found {found}$"):
        render_chart_figure(page, "chart-financial")


@pytest.mark.parametrize(
    ("call", "named"),
    [
        pytest.param(
            "renderChart('chart-sankey', figure)",
            "renderChart('chart-sankey', figure",
            id="identifier",
        ),
        pytest.param(
            "renderChart('chart-sankey', '{}')",
            "renderChart('chart-sankey', '{}'",
            id="single-quoted-string",
        ),
        pytest.param(
            "renderChart('chart-sankey')",
            "renderChart('chart-sankey')",
            id="no-second-argument",
        ),
    ],
)
def test_a_figure_that_is_neither_a_json_string_nor_null_raises_naming_the_call(
    call: str, named: str
) -> None:
    page = f"<script>{call};</script>"

    with pytest.raises(ValueError, match=r"JSON string or null.*" + re.escape(named)):
        render_chart_figure(page, "chart-sankey")


def test_render_chart_figure_finds_calls_as_render_chart_targets_does() -> None:
    page = (
        "<script>// renderChart('chart-monthly', null);\n"
        "var note = \"renderChart('chart-monthly', null)\";\n"
        r"""renderChart('chart-monthly', "{\"data\": []}");</script>"""
    )

    assert render_chart_figure(page, "chart-monthly") == '{"data": []}'


def test_chart_figures_reads_the_figure_each_chart_container_carries_keyed_by_its_id() -> (
    None
):
    page = (
        '<div id="chart-sankey" class="w-full" data-chart-figure="{&#34;data&#34;: []}"></div>'
        '<div id="chart-comparison-bar" class="w-full"></div>'
        '<section id="chart-financial" data-chart-figure="{&#34;layout&#34;:'
        ' {&#34;title&#34;: &#34;Import &amp; export: today&#39;s &lt;tariff&gt;&#34;}}"></section>'
    )

    assert chart_figures(page) == {
        "chart-sankey": '{"data": []}',
        "chart-financial": """{"layout": {"title": "Import & export: today's <tariff>"}}""",
    }


@pytest.mark.parametrize(
    ("page", "named"),
    [
        pytest.param('<div data-chart-figure="{}"></div>', "carries no id", id="no-id"),
        pytest.param(
            '<div id="chart-sankey" data-chart-figure></div>',
            "'chart-sankey' to carry a figure",
            id="valueless-figure",
        ),
        pytest.param(
            '<div id="chart-sankey" data-chart-figure="{}"></div>'
            '<div id="chart-sankey" data-chart-figure="{}"></div>',
            "'chart-sankey' is on more than one",
            id="repeated-id",
        ),
    ],
)
def test_chart_figures_raises_rather_than_drop_or_overwrite_a_chart_container(
    page: str, named: str
) -> None:
    with pytest.raises(ValueError, match=named):
        chart_figures(page)
