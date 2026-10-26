# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to the Plotly figure JSON a solar_challenge.web.charts builder returns:
its traces, in drawing order or keyed by name, and the texts of its layout annotations or the
annotations keyed by text; the nodes and links of a Sankey figure, keyed by node label; and the
colours a text writes or a figure draws, read as red, green and blue.

A colour is written #rrggbb, rgb() or rgba(), in any case and with any whitespace inside the
parentheses; the alpha is read only to tell a fully transparent colour.

Usage::

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

    assert traces(charts.fleet_heatmap(summaries).content)[0]["y"] == ["Home 1", "Home 2"]
    assert traces_by_name(charts.financial_breakdown(results).content)["Daily Cost"]["y"] == [2.88, 2.88]
    assert annotation_texts(charts.financial_breakdown(unpriced_results).content) == [
        "No tariff configured — cost and revenue tracking unavailable"
    ]
    soc_chart = charts.battery_soc_chart(results, BatteryConfig(capacity_kwh=10.0)).content
    assert annotations_by_text(soc_chart)["Min SOC"]["y"] == 1.0

    figure = charts.sankey_diagram(summary).content
    assert sankey_link_values(figure)[("Grid", "Battery")] == 2.0
    assert opaque(sankey_link_colours(figure)[("Grid", "Demand")]) == COLOUR_PALETTE["grid_import"]
    assert sankey_node_colours(figure)["Battery"] == COLOUR_PALETTE["battery_charge"]
    assert (245, 166, 35) in drawn_colours(figure).values()
    written = [colour for colour, _ in colour_literals(stylesheet)]
"""

import json
import re
from collections import Counter
from collections.abc import Hashable, Iterator, Sequence
from typing import Any, TypeVar

Rgb = tuple[int, int, int]

_COLOUR_LITERAL = re.compile(
    r"#(?P<hex>[0-9a-f]{6})"
    r"|rgba?\(\s*(?P<red>\d+)\s*,\s*(?P<green>\d+)\s*,\s*(?P<blue>\d+)\s*(?:,\s*(?P<alpha>[\d.]+)\s*)?\)",
    re.IGNORECASE,
)

_Key = TypeVar("_Key", bound=Hashable)
_Value = TypeVar("_Value")


def traces(figure: str) -> list[dict[str, Any]]:
    """The traces of *figure*, as written, in the order it draws them; [] when it has none."""
    drawn: list[dict[str, Any]] = json.loads(figure).get("data", [])
    return drawn


def traces_by_name(figure: str) -> dict[str, dict[str, Any]]:
    """Each trace of *figure*, as written, keyed by its name.

    Raises ValueError, rather than leave it out, when a trace has no name; and rather than keep
    one, when two traces share a name.
    """
    drawn = traces(figure)
    unnamed = [trace.get("type") for trace in drawn if "name" not in trace]
    if unnamed:
        raise ValueError(f"Expected each trace to have a name; got unnamed traces of the types {unnamed}")
    return _keyed([trace["name"] for trace in drawn], drawn, expected="one trace per name")


def annotation_texts(figure: str) -> list[str]:
    """The texts of *figure*'s layout annotations, in the order it draws them; [] when it has none.

    Raises ValueError, rather than leave it out, when an annotation has no text.
    """
    return _texts(_annotations(figure))


def annotations_by_text(figure: str) -> dict[str, dict[str, Any]]:
    """Each of *figure*'s layout annotations, as written, keyed by its text; {} when it has none.

    Raises ValueError where annotation_texts does; and, rather than keep one, when two
    annotations share a text.
    """
    drawn = _annotations(figure)
    return _keyed(_texts(drawn), drawn, expected="one annotation per text")


def sankey_link_values(figure: str) -> dict[tuple[str, str], float]:
    """Each link's value in *figure*, keyed by the labels of its source and target nodes.

    Raises ValueError, rather than guess which trace to read, unless *figure* is one Sankey
    trace; rather than keep one, when two links join the same source and target; rather
    than drop a link, when the link lists differ in length; and rather than count a negative
    index back from the last node, when a link's source or target is not the index of a node.
    """
    return _by_link(figure, "value")


def sankey_link_colours(figure: str) -> dict[tuple[str, str], str]:
    """Each link's colour in *figure*, as written, keyed by the labels of its source and target nodes.

    Raises ValueError where sankey_link_values does.
    """
    return _by_link(figure, "color")


def sankey_node_colours(figure: str) -> dict[str, str]:
    """Each node's colour in *figure*, as written, keyed by its label.

    Raises ValueError, rather than guess which trace to read, unless *figure* is one Sankey
    trace; rather than keep one colour, when two nodes share a label; and rather than drop a
    node, when the node lists differ in length.
    """
    labels, colours = _parallel_lists(_sankey_trace(figure), "node", "label", "color")
    return _keyed(labels, colours, expected="one node per label")


def colour_literals(text: str) -> Iterator[tuple[str, Rgb]]:
    """Each #rrggbb, rgb() or rgba() colour written in *text*, with its red, green and blue.

    An eight-digit #rrggbbaa is read through its #rrggbb prefix.
    """
    for match in _COLOUR_LITERAL.finditer(text):
        yield match.group(), _rgb(match)


def drawn_colours(figure: str) -> dict[str, Rgb]:
    """Each colour *figure*'s traces and layout draw, keyed by how it is written, with its red, green and blue.

    Not read: Plotly's default template, which no builder chooses, and a colour written rgba()
    with an alpha of 0, which draws nothing.
    """
    drawn = json.loads(figure)
    drawn.get("layout", {}).pop("template", None)
    return {
        match.group(): _rgb(match)
        for text in _strings(drawn)
        for match in _COLOUR_LITERAL.finditer(text)
        if not _fully_transparent(match)
    }


def opaque(colour: str) -> str:
    """*colour* written as lower-case #rrggbb, without its alpha.

    Raises ValueError, rather than read a part of it, unless *colour* is exactly one colour.
    """
    match = _COLOUR_LITERAL.fullmatch(colour)
    if match is None:
        raise ValueError(f"Expected one colour written #rrggbb, rgb() or rgba(); got {colour!r}")
    return "#" + "".join(f"{channel:02x}" for channel in _rgb(match))


def _rgb(match: re.Match[str]) -> Rgb:
    if match["hex"] is not None:
        red, green, blue = bytes.fromhex(match["hex"])
    else:
        red, green, blue = (int(match[channel]) for channel in ("red", "green", "blue"))
    return red, green, blue


def _fully_transparent(match: re.Match[str]) -> bool:
    return match["alpha"] is not None and float(match["alpha"]) == 0


def _strings(node: object) -> Iterator[str]:
    """Every string leaf of the dicts and lists under *node*."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _annotations(figure: str) -> list[dict[str, Any]]:
    drawn: list[dict[str, Any]] = json.loads(figure).get("layout", {}).get("annotations", [])
    return drawn


def _texts(annotations: Sequence[dict[str, Any]]) -> list[str]:
    untexted = [annotation for annotation in annotations if "text" not in annotation]
    if untexted:
        raise ValueError(f"Expected each annotation to have a text; got annotations with no text {untexted}")
    return [annotation["text"] for annotation in annotations]


def _sankey_trace(figure: str) -> dict[str, Any]:
    drawn = traces(figure)
    types = [trace.get("type") for trace in drawn]
    if types != ["sankey"]:
        raise ValueError(f"Expected a figure of one trace, a Sankey; got traces of the types {types}")
    return drawn[0]


def _by_link(figure: str, attribute: str) -> dict[tuple[str, str], Any]:
    sankey = _sankey_trace(figure)
    labels = sankey["node"]["label"]
    sources, targets, attribute_values = _parallel_lists(sankey, "link", "source", "target", attribute)
    endpoints = [
        (_node_label(labels, source), _node_label(labels, target))
        for source, target in zip(sources, targets, strict=True)
    ]
    return _keyed(endpoints, attribute_values, expected="one link per source and target")


def _parallel_lists(sankey: dict[str, Any], part: str, *attributes: str) -> list[list[Any]]:
    lengths = {attribute: len(sankey[part][attribute]) for attribute in attributes}
    if len(set(lengths.values())) > 1:
        raise ValueError(
            f"Expected each of the Sankey's {part} lists to hold one entry per {part}; got lengths {lengths}"
        )
    return [sankey[part][attribute] for attribute in attributes]


def _node_label(labels: Sequence[str], index: int) -> str:
    if not 0 <= index < len(labels):
        raise ValueError(
            f"Expected each link's source and target to be the index of one of the {len(labels)} nodes; got {index}"
        )
    return labels[index]


def _keyed(keys: Sequence[_Key], values: Sequence[_Value], *, expected: str) -> dict[_Key, _Value]:
    repeated = [key for key, count in Counter(keys).items() if count > 1]
    if repeated:
        raise ValueError(f"Expected {expected}; got more than one for {repeated}")
    return dict(zip(keys, values, strict=True))
