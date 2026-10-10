# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_plotly_figure.py, the reader of a chart builder's Plotly figure JSON: a Sankey's nodes and links, and the colours a figure writes.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a chart test that uses it pass vacuously.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from tests._plotly_figure import (
    colour_literals,
    opaque,
    sankey_link_colours,
    sankey_link_values,
    sankey_node_colours,
)


def _figure(*traces: dict[str, Any]) -> str:
    """A figure of *traces*, written as JSON as Figure.to_json writes it."""
    return json.dumps({"data": list(traces), "layout": {"title": {"text": "Energy Flow"}}})


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
    """sankey_diagram returns "{}" when it draws no flow."""
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
