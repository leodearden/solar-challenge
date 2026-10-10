# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to the Plotly figure JSON a solar_challenge.web.charts builder returns:
the nodes and links of a Sankey figure, keyed by node label, and the colours a figure writes,
read as red, green and blue.

A colour is written #rrggbb, rgb() or rgba(), in any case and with any whitespace inside the
parentheses; an alpha is never read.

Usage::

    from tests._plotly_figure import colour_literals, opaque, sankey_link_colours, sankey_link_values, sankey_node_colours

    figure = charts.sankey_diagram(summary)
    assert sankey_link_values(figure)[("Grid", "Battery")] == 2.0
    assert opaque(sankey_link_colours(figure)[("Grid", "Demand")]) == COLOUR_PALETTE["grid_import"]
    assert sankey_node_colours(figure)["Battery"] == COLOUR_PALETTE["battery_charge"]
    drawn = {rgb for _, rgb in colour_literals(figure)}
"""

import json
import re
from collections import Counter
from collections.abc import Hashable, Iterator, Sequence
from typing import Any, TypeVar

Rgb = tuple[int, int, int]

_COLOUR_LITERAL = re.compile(
    r"#(?P<hex>[0-9a-f]{6})"
    r"|rgba?\(\s*(?P<red>\d+)\s*,\s*(?P<green>\d+)\s*,\s*(?P<blue>\d+)\s*(?:,\s*[\d.]+\s*)?\)",
    re.IGNORECASE,
)

_Key = TypeVar("_Key", bound=Hashable)
_Value = TypeVar("_Value")


def sankey_link_values(figure: str) -> dict[tuple[str, str], float]:
    """Each link's value in *figure*, keyed by the labels of its source and target nodes.

    Raises ValueError, rather than guess which trace to read, unless *figure* is one Sankey
    trace; rather than keep one, when two links join the same source and target; and rather
    than drop a link, when the link lists differ in length.
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
    node = _sankey_trace(figure)["node"]
    return _keyed(node["label"], node["color"], expected="one node per label")


def colour_literals(text: str) -> Iterator[tuple[str, Rgb]]:
    """Each #rrggbb, rgb() or rgba() colour written in *text*, with its red, green and blue.

    An eight-digit #rrggbbaa is read through its #rrggbb prefix.
    """
    for match in _COLOUR_LITERAL.finditer(text):
        yield match.group(), _rgb(match)


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


def _sankey_trace(figure: str) -> dict[str, Any]:
    traces: list[dict[str, Any]] = json.loads(figure).get("data", [])
    types = [trace.get("type") for trace in traces]
    if types != ["sankey"]:
        raise ValueError(f"Expected a figure of one trace, a Sankey; got traces of the types {types}")
    return traces[0]


def _by_link(figure: str, attribute: str) -> dict[tuple[str, str], Any]:
    sankey = _sankey_trace(figure)
    labels, link = sankey["node"]["label"], sankey["link"]
    endpoints: list[tuple[str, str]] = [
        (labels[source], labels[target]) for source, target in zip(link["source"], link["target"], strict=True)
    ]
    return _keyed(endpoints, link[attribute], expected="one link per source and target")


def _keyed(keys: Sequence[_Key], values: Sequence[_Value], *, expected: str) -> dict[_Key, _Value]:
    repeated = [key for key, count in Counter(keys).items() if count > 1]
    if repeated:
        raise ValueError(f"Expected {expected}; got more than one for {repeated}")
    return dict(zip(keys, values, strict=True))
