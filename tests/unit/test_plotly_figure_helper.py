# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_plotly_figure.py, the reader of a chart builder's Plotly figure JSON: a figure's traces, in drawing order or keyed by name, and the texts of its annotations or the annotations keyed by text; a Sankey's nodes and links; and the colours a figure writes.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a chart test that uses it pass vacuously.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from tests._plotly_figure import (
    annotation_texts,
    annotations_by_text,
    colour_literals,
    drawn_colours,
    opaque,
    sankey_link_colours,
    sankey_link_values,
    sankey_node_colours,
    traces,
    traces_by_name,
)


def _figure(*traces: dict[str, Any]) -> str:
    """A figure of *traces*, written as JSON as Figure.to_json writes it."""
    return json.dumps({"data": list(traces), "layout": {"title": {"text": "Energy Flow"}}})


def _annotated(*annotations: dict[str, Any]) -> str:
    """A figure of one bar and *annotations*, written as JSON as Figure.to_json writes it."""
    return json.dumps({"data": [_BAR], "layout": {"annotations": list(annotations)}})


def _sankey(
    labels: list[str], node_colours: list[str], links: list[tuple[int, int, float, str]]
) -> dict[str, Any]:
    """A Sankey trace of nodes *labels* drawn in *node_colours*, and *links*, each (source index, target index, value, colour)."""
    return {
        "type": "sankey",
        "node": {"label": list(labels), "color": list(node_colours)},
        "link": {
            "source": [source for source, _, _, _ in links],
            "target": [target for _, target, _, _ in links],
            "value": [value for _, _, value, _ in links],
            "color": [colour for _, _, _, colour in links],
        },
    }


def _pv_and_the_grid_feeding_demand() -> dict[str, Any]:
    """A Sankey trace whose first node, Demand, is the target of both its links, so a node's index is not a link's position."""
    return _sankey(
        ["Demand", "PV Generation", "Grid"],
        ["#4a90e2", "#F5A623", "rgba(208,2,27,0.8)"],
        [(1, 0, 42.0, "rgba(126,211,33,0.4)"), (2, 0, 30.0, "#9b9b9b")],
    )


_BAR = {"type": "bar", "x": ["Generation"], "y": [42.0]}

_LINK_READERS = [
    pytest.param(sankey_link_values, id="sankey_link_values"),
    pytest.param(sankey_link_colours, id="sankey_link_colours"),
]
_READERS = [*_LINK_READERS, pytest.param(sankey_node_colours, id="sankey_node_colours")]
_ANNOTATION_READERS = [
    pytest.param(annotation_texts, id="annotation_texts"),
    pytest.param(annotations_by_text, id="annotations_by_text"),
]


def test_traces_lists_each_trace_as_written_in_the_order_the_figure_draws_them() -> None:
    """The heatmap has no name, which traces, unlike traces_by_name, does not need."""
    generation = {"type": "box", "name": "Generation", "y": [72.0, 8.0]}
    heatmap = {"type": "heatmap", "x": ["Generation"], "y": ["Home 1", "Home 2"], "z": [[72.0], [8.0]]}
    demand = {"type": "box", "name": "Demand", "y": [45.0, 46.0]}

    assert traces(_figure(generation, heatmap, demand)) == [generation, heatmap, demand]


def test_traces_lists_each_of_two_traces_sharing_a_name() -> None:
    """Two traces may validly share a name, which traces, unlike traces_by_name, lists once for each."""
    first = {"type": "scatter", "name": "Grid Import", "y": [1.2, 0.0]}
    second = {"type": "scatter", "name": "Grid Import", "y": [0.4, 0.0]}

    assert traces(_figure(first, second)) == [first, second]


def test_a_figure_with_no_data_has_no_traces() -> None:
    """The case is a figure's JSON with no data or layout."""
    assert traces("{}") == []


def test_traces_by_name_keys_each_trace_as_written_by_its_name() -> None:
    cost = {"type": "bar", "name": "Daily Cost", "x": ["2024-06-01"], "y": [2.88]}
    revenue = {"type": "bar", "name": "Daily Revenue", "x": ["2024-06-01"], "y": [1.44]}
    net_cost = {
        "type": "scatter",
        "name": "Cumulative Net Cost",
        "mode": "lines",
        "x": ["2024-06-01"],
        "y": [1.44],
        "yaxis": "y2",
    }

    assert traces_by_name(_figure(cost, revenue, net_cost)) == {
        "Daily Cost": cost,
        "Daily Revenue": revenue,
        "Cumulative Net Cost": net_cost,
    }


def test_two_traces_sharing_a_name_raise_rather_than_keeping_one() -> None:
    figure = _figure(
        {"type": "scatter", "name": "Grid Import", "y": [1.2, 0.0]},
        {"type": "scatter", "name": "Grid Export", "y": [0.0, 0.8]},
        {"type": "scatter", "name": "Grid Import", "y": [0.4, 0.0]},
    )

    with pytest.raises(ValueError, match=re.escape("['Grid Import']") + "$"):
        traces_by_name(figure)


def test_a_trace_without_a_name_raises_rather_than_being_left_out() -> None:
    """Figure.to_json writes no name for a trace drawn without one."""
    figure = _figure(
        {"type": "scatter", "name": "Grid Import", "y": [1.2, 0.0]},
        {"type": "heatmap", "z": [[1.2, 0.0]]},
        {"type": "scatter", "name": "Grid Export", "y": [0.0, 0.8]},
    )

    with pytest.raises(ValueError, match=re.escape("['heatmap']") + "$"):
        traces_by_name(figure)


def test_annotation_texts_lists_each_annotations_text_in_the_order_the_figure_draws_them() -> None:
    """The annotations are written as make_subplots writes its subplot titles, in an order neither sorted nor reverse-sorted."""
    figure = _annotated(
        {"showarrow": False, "text": "Generation (kWh)", "x": 0.14, "xref": "paper", "y": 1.0},
        {"showarrow": False, "text": "Self-Consumption Ratio", "x": 0.5, "xref": "paper", "y": 1.0},
        {"showarrow": False, "text": "Grid Dependency Ratio", "x": 0.86, "xref": "paper", "y": 1.0},
    )

    assert annotation_texts(figure) == ["Generation (kWh)", "Self-Consumption Ratio", "Grid Dependency Ratio"]


def test_annotation_texts_lists_a_shared_text_once_for_each_annotation() -> None:
    """The annotations are written as make_subplots writes its subplot titles when two are the same, a repeat that annotation_texts, unlike annotations_by_text, does not refuse."""
    figure = _annotated(
        {"showarrow": False, "text": "Generation (kWh)", "x": 0.225, "xref": "paper", "y": 1.0},
        {"showarrow": False, "text": "Generation (kWh)", "x": 0.775, "xref": "paper", "y": 1.0},
    )

    assert annotation_texts(figure) == ["Generation (kWh)", "Generation (kWh)"]


@pytest.mark.parametrize(
    ("reader", "nothing"),
    [
        pytest.param(annotation_texts, [], id="annotation_texts"),
        pytest.param(annotations_by_text, {}, id="annotations_by_text"),
    ],
)
@pytest.mark.parametrize(
    "figure",
    [
        pytest.param(_figure(_BAR), id="layout-without-annotations"),
        pytest.param("{}", id="no-layout"),
    ],
)
def test_a_figure_with_no_annotations_reads_as_empty(
    reader: Callable[[str], object], nothing: object, figure: str
) -> None:
    """Figure.to_json writes no annotations key for a figure without any, and the last case is a figure's JSON with no data or layout.

    The first figure's title has a text, which is not an annotation's.
    """
    assert reader(figure) == nothing


def test_annotations_by_text_keys_each_annotation_as_written_by_its_text() -> None:
    """The annotations are written as add_hline writes battery_soc_chart's SOC-limit labels."""
    min_soc = {
        "showarrow": False,
        "text": "Min SOC",
        "x": 1,
        "xanchor": "right",
        "xref": "x domain",
        "y": 0.72,
        "yanchor": "top",
        "yref": "y",
    }
    max_soc = {
        "showarrow": False,
        "text": "Max SOC",
        "x": 1,
        "xanchor": "right",
        "xref": "x domain",
        "y": 6.84,
        "yanchor": "bottom",
        "yref": "y",
    }

    assert annotations_by_text(_annotated(min_soc, max_soc)) == {"Min SOC": min_soc, "Max SOC": max_soc}


def test_two_annotations_sharing_a_text_raise_rather_than_keeping_one() -> None:
    figure = _annotated({"text": "Min SOC", "y": 0.72}, {"text": "Max SOC", "y": 6.84}, {"text": "Min SOC", "y": 1.0})

    with pytest.raises(ValueError, match=re.escape("['Min SOC']") + "$"):
        annotations_by_text(figure)


@pytest.mark.parametrize("reader", _ANNOTATION_READERS)
def test_an_annotation_without_a_text_raises_rather_than_being_left_out(reader: Callable[[str], object]) -> None:
    """Figure.to_json writes no text for an annotation drawn without one, as an arrow alone is."""
    figure = _annotated(
        {"text": "Min SOC", "y": 0.72},
        {"showarrow": True, "x": 1, "y": 2},
        {"text": "Max SOC", "y": 6.84},
    )

    with pytest.raises(ValueError, match=re.escape("[{'showarrow': True, 'x': 1, 'y': 2}]") + "$"):
        reader(figure)


def test_sankey_link_values_keys_each_links_value_by_its_source_and_target_labels() -> None:
    figure = _figure(_pv_and_the_grid_feeding_demand())

    assert sankey_link_values(figure) == {
        ("PV Generation", "Demand"): 42.0,
        ("Grid", "Demand"): 30.0,
    }


def test_sankey_link_colours_keys_each_links_colour_as_written_by_its_source_and_target_labels() -> None:
    figure = _figure(_pv_and_the_grid_feeding_demand())

    assert sankey_link_colours(figure) == {
        ("PV Generation", "Demand"): "rgba(126,211,33,0.4)",
        ("Grid", "Demand"): "#9b9b9b",
    }


def test_sankey_node_colours_keys_each_nodes_colour_as_written_by_its_label() -> None:
    figure = _figure(_pv_and_the_grid_feeding_demand())

    assert sankey_node_colours(figure) == {
        "Demand": "#4a90e2",
        "PV Generation": "#F5A623",
        "Grid": "rgba(208,2,27,0.8)",
    }


@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize(
    ("figure", "types"),
    [
        pytest.param("{}", [], id="no-flow-drawn"),
        pytest.param(_figure(_BAR), ["bar"], id="bar-only"),
        pytest.param(_figure(_pv_and_the_grid_feeding_demand(), _BAR), ["sankey", "bar"], id="sankey-and-bar"),
    ],
)
def test_a_figure_that_is_not_one_sankey_trace_raises_rather_than_reading_a_trace(
    reader: Callable[[str], object], figure: str, types: list[str]
) -> None:
    """The case is a figure's JSON with no data or layout."""
    with pytest.raises(ValueError, match=re.escape(f"one trace, a Sankey; got traces of the types {types}") + "$"):
        reader(figure)


@pytest.mark.parametrize("reader", _LINK_READERS)
def test_two_links_joining_the_same_nodes_raise_rather_than_keeping_one(reader: Callable[[str], object]) -> None:
    figure = _figure(
        _sankey(
            ["PV Generation", "Grid", "Demand"],
            ["#f5a623", "#d0021b", "#4a90e2"],
            [(0, 2, 42.0, "#7ed321"), (1, 2, 30.0, "#d0021b"), (1, 2, 5.0, "#9b9b9b")],
        )
    )

    with pytest.raises(ValueError, match=re.escape("[('Grid', 'Demand')]") + "$"):
        reader(figure)


def test_two_nodes_sharing_a_label_raise_rather_than_keeping_one_colour() -> None:
    figure = _figure(
        _sankey(
            ["PV Generation", "Battery", "Battery", "Demand"],
            ["#f5a623", "#50e3c2", "#7ed321", "#4a90e2"],
            [(0, 1, 3.0, "#50e3c2"), (2, 3, 2.0, "#50e3c2")],
        )
    )

    with pytest.raises(ValueError, match=re.escape("['Battery']") + "$"):
        sankey_node_colours(figure)


@pytest.mark.parametrize(
    ("reader", "part", "attribute", "lengths"),
    [
        pytest.param(sankey_link_values, "link", "value", {"source": 2, "target": 2, "value": 1}, id="link-value"),
        pytest.param(sankey_link_colours, "link", "color", {"source": 2, "target": 2, "color": 1}, id="link-colour"),
        pytest.param(sankey_link_values, "link", "target", {"source": 2, "target": 1, "value": 2}, id="link-target"),
        pytest.param(sankey_node_colours, "node", "color", {"label": 3, "color": 2}, id="node-colour"),
    ],
)
def test_lists_of_unequal_length_raise_rather_than_dropping_an_entry(
    reader: Callable[[str], object], part: str, attribute: str, lengths: dict[str, int]
) -> None:
    sankey = _pv_and_the_grid_feeding_demand()
    del sankey[part][attribute][-1]

    with pytest.raises(ValueError, match=re.escape(f"one entry per {part}; got lengths {lengths}") + "$"):
        reader(_figure(sankey))


@pytest.mark.parametrize("reader", _LINK_READERS)
@pytest.mark.parametrize(
    ("end", "index"),
    [
        pytest.param("source", 3, id="source-past-the-last-node"),
        pytest.param("target", -1, id="target-before-the-first-node"),
    ],
)
def test_a_link_whose_source_or_target_is_not_the_index_of_a_node_raises(
    reader: Callable[[str], object], end: str, index: int
) -> None:
    """Python would read the index -1 as the last node's."""
    sankey = _pv_and_the_grid_feeding_demand()
    sankey["link"][end][0] = index

    with pytest.raises(ValueError, match=re.escape(f"one of the 3 nodes; got {index}") + "$"):
        reader(_figure(sankey))


@pytest.mark.parametrize(
    "written",
    [
        pytest.param("rgba(80,227,194,0.4)", id="rgba"),
        pytest.param("rgba( 80 , 227 , 194 , 1 )", id="rgba-spaced"),
        pytest.param("RGBA(80,227,194,0.4)", id="rgba-upper-case"),
        pytest.param("rgb(80,227,194)", id="rgb"),
        pytest.param("#50E3C2", id="rrggbb-upper-case"),
    ],
)
def test_opaque_writes_a_colour_as_lower_case_rrggbb_without_its_alpha(written: str) -> None:
    assert opaque(written) == "#50e3c2"


@pytest.mark.parametrize(
    "written",
    [
        pytest.param("#50e3c280", id="rrggbbaa"),
        pytest.param("#5e3", id="rgb-shorthand"),
        pytest.param("teal", id="colour-name"),
        pytest.param("rgba(80,227,194,0.4);", id="trailing-text"),
        pytest.param("#50e3c2 #f5a623", id="two-colours"),
        pytest.param("", id="empty"),
    ],
)
def test_opaque_refuses_anything_but_one_whole_colour(written: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"; got {written!r}") + "$"):
        opaque(written)


def test_colour_literals_yields_each_colour_written_in_a_text_in_order_as_written_with_its_red_green_and_blue() -> (
    None
):
    text = '{"fillcolor": "rgba(80, 227, 194, 0.4)", "line": {"color": "#F5A623"}, "marker": "rgb(1,2,3)"}'

    assert list(colour_literals(text)) == [
        ("rgba(80, 227, 194, 0.4)", (80, 227, 194)),
        ("#F5A623", (245, 166, 35)),
        ("rgb(1,2,3)", (1, 2, 3)),
    ]


def test_colour_literals_reads_an_eight_digit_rrggbbaa_through_its_rrggbb_prefix() -> None:
    """The palette guard relies on this to catch a translucent copy of a palette colour written in hex."""
    assert list(colour_literals("#50e3c280")) == [("#50e3c2", (80, 227, 194))]


def test_colour_literals_yields_nothing_for_a_text_that_writes_no_colour() -> None:
    assert list(colour_literals("system-ui, sans-serif; black; 0.4")) == []


def test_drawn_colours_keys_each_colour_the_traces_and_layout_draw_by_how_it_is_written_with_its_red_green_and_blue() -> (
    None
):
    """The Sankey's colours are entries of the node and link colour lists nested in its trace."""
    figure = json.dumps(
        {
            "data": [
                {"type": "scatter", "name": "Battery", "fill": "tozeroy", "fillcolor": "rgba(80, 227, 194, 0.4)"},
                _sankey(["PV Generation", "Demand"], ["#F5A623", "#4a90e2"], [(0, 1, 42.0, "#4a90e2")]),
            ],
            "layout": {"title": {"text": "Energy Flow", "font": {"color": "rgb(1,2,3)"}}},
        }
    )

    assert drawn_colours(figure) == {
        "rgba(80, 227, 194, 0.4)": (80, 227, 194),
        "#F5A623": (245, 166, 35),
        "#4a90e2": (74, 144, 226),
        "rgb(1,2,3)": (1, 2, 3),
    }


def test_drawn_colours_does_not_read_plotlys_default_template() -> None:
    """Figure.to_json writes Plotly's default template into the layout, though no builder chooses it."""
    figure = json.dumps(
        {
            "data": [{"type": "bar", "name": "Generation", "marker": {"color": "#f5a623"}}],
            "layout": {
                "template": {
                    "data": {"bar": [{"marker": {"line": {"color": "#E5ECF6"}}}]},
                    "layout": {"colorway": ["#636efa", "#EF553B"], "font": {"color": "#2a3f5f"}},
                },
            },
        }
    )

    assert drawn_colours(figure) == {"#f5a623": (245, 166, 35)}


@pytest.mark.parametrize(
    "transparent",
    [
        pytest.param("rgba(0,0,0,0)", id="alpha-0"),
        pytest.param("rgba( 0 , 0 , 0 , 0.0 )", id="alpha-0.0-spaced"),
    ],
)
def test_drawn_colours_does_not_read_a_colour_written_rgba_with_an_alpha_of_0(transparent: str) -> None:
    """Such a colour draws nothing; charts.py writes its transparent backgrounds so. Black drawn translucent or opaque is still read."""
    figure = json.dumps(
        {
            "data": [
                {
                    "type": "sankey",
                    "node": {"label": ["Grid"], "line": {"color": "rgb(0,0,0)"}},
                    "link": {"color": ["rgba(0,0,0,0.5)"]},
                }
            ],
            "layout": {"paper_bgcolor": transparent, "plot_bgcolor": transparent},
        }
    )

    assert drawn_colours(figure) == {"rgb(0,0,0)": (0, 0, 0), "rgba(0,0,0,0.5)": (0, 0, 0)}
