# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read a run badge as the dashboard's server draws it: the macros of components/macros.html,
as callables that return their markup, and the one span a badge macro draws, with its
attributes and its classes.

A page test counts the spans equal to a value's badge; an e2e test compares the classes a
badge in the browser carries with the classes the server draws for the same value. Flask is
imported only for type checking, so importing this module needs no web extra.

Usage::

    from tests._server_drawn_badges import dashboard_macros_of, server_drawn_badge, server_drawn_classes

    macros = dashboard_macros_of(app)
    assert spans.count(server_drawn_badge(macros.run_status_badge("failed"))) == 1
    assert "bg-status-failed-100" in server_drawn_classes(macros.run_status_badge("failed"))
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from tests._html_page import element_attributes

if TYPE_CHECKING:
    from flask import Flask


def dashboard_macros_of(app: Flask) -> Any:
    """The public macros of *app*'s components/macros.html, as callables that return their markup."""
    return app.jinja_env.get_template("components/macros.html").module


def server_drawn_badge(markup: object) -> Mapping[str, str | None]:
    """The attributes of the one span *markup*, a badge macro's rendering, draws.

    Raises ValueError, rather than pick one, unless *markup* draws exactly one span.
    """
    spans = element_attributes(str(markup), "span")
    if len(spans) != 1:
        raise ValueError(f"Expected a badge to be one span; found {len(spans)} in {markup!s}")
    return spans[0]


def server_drawn_classes(markup: object) -> set[str]:
    """The classes of the one span *markup*, a badge macro's rendering, draws."""
    return set((server_drawn_badge(markup).get("class") or "").split())
