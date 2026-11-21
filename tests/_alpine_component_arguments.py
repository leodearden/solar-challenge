# SPDX-License-Identifier: AGPL-3.0-or-later
"""The arguments a rendered HTML page hands an Alpine component, read as JSON from the x-data that mounts it.

A page hands its component server data in the x-data of the div that mounts it, a call of
the component, component(argument, ...), each argument rendered as JSON by Jinja's tojson.
tests/_html_page.py reads each div's x-data as text; this reader parses the call's
arguments, so a page test can compare them with the values the page was rendered from.

Usage::

    from tests._alpine_component_arguments import component_arguments

    page = client.get("/simulate/home").get_data(as_text=True)
    assert component_arguments(page, "homeSimulator") == [{"economy_7": {...}, "economy_10": {...}}]
"""

import json
from typing import Any

from tests._html_page import element_attributes


def component_arguments(page: str, component: str) -> list[Any]:
    """The arguments of the one div of *page* whose x-data calls the Alpine *component*, in order, each read as JSON.

    Raises ValueError, rather than guess which mount is meant, unless exactly one div's
    x-data starts with a call of *component*; and, rather than read it as something
    else, when the call does not end with its closing parenthesis or its arguments are
    not JSON values separated by commas.
    """
    opening = f"{component}("
    scopes = (attributes.get("x-data") or "" for attributes in element_attributes(page, "div"))
    calls = [scope for scope in scopes if scope.startswith(opening)]
    if len(calls) != 1:
        raise ValueError(f"Expected exactly one div whose x-data calls {component}; found {len(calls)}")
    (call,) = calls
    if not call.endswith(")"):
        raise ValueError(f"x-data={call!r} does not close its call of {component} with ')'")
    try:
        arguments: list[Any] = json.loads("[" + call[len(opening) : -1] + "]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"x-data={call!r} does not pass {component} JSON arguments: {exc}") from exc
    return arguments
