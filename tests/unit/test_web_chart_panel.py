# SPDX-License-Identifier: AGPL-3.0-or-later
"""chart_panel, of components/macros.html, draws the card of a chart that
static/js/chart-renderer.js draws from the figure its container carries, so a page writes
each chart's id once. A figure with nothing to draw, None or '{}', gets the card of a
message instead, or no card. A figure read under a name the page's route never set is
undefined, and fails the render, naming that name.
"""

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask
from jinja2 import UndefinedError

from tests._html_page import chart_figures, element_count, element_ids, headings, texts
from tests._server_drawn_badges import dashboard_macros_of
from tests._web_app import build_test_app

_FIGURE = json.dumps(
    {
        "data": [{"type": "bar", "x": ["a"], "y": [1]}],
        "layout": {"title": {"text": "<b>Tom's \"best\" day</b> & more"}},
    }
)
_NOTHING_TO_DRAW = [pytest.param(None, id="none"), pytest.param("{}", id="empty-object")]


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


@pytest.fixture
def macros(app: Flask) -> Any:
    """The public macros of components/macros.html, as callables that return their markup."""
    return dashboard_macros_of(app)


def test_a_chart_panel_draws_a_card_titled_with_its_title_whose_container_carries_the_figure(
    macros: Any,
) -> None:
    """The figure's title holds every character HTML escapes, and it survives autoescaping intact."""
    panel = str(macros.chart_panel("chart-sample", "Sample Chart", _FIGURE, "420px"))

    assert headings(panel) == ["Sample Chart"]
    assert chart_figures(panel) == {"chart-sample": _FIGURE}
    assert element_count(panel, "div", {"id": "chart-sample", "style": "min-height: 420px;"}) == 1


@pytest.mark.parametrize("figure", _NOTHING_TO_DRAW)
def test_a_chart_panel_of_a_figure_with_nothing_to_draw_draws_nothing(
    macros: Any, figure: str | None
) -> None:
    assert str(macros.chart_panel("chart-sample", "Sample Chart", figure, "420px")).strip() == ""


@pytest.mark.parametrize("figure", _NOTHING_TO_DRAW)
def test_a_chart_panel_of_a_figure_with_nothing_to_draw_draws_its_empty_message_instead(
    macros: Any, figure: str | None
) -> None:
    panel = str(
        macros.chart_panel(
            "chart-sample",
            "Sample Chart",
            figure,
            "420px",
            empty_message="Needs 180 days of simulation data.",
        )
    )

    assert texts(panel) == ["Needs 180 days of simulation data."]
    assert element_ids(panel) == set()
    assert chart_figures(panel) == {}


@pytest.mark.parametrize(
    "empty_message",
    [pytest.param("", id="no-empty-message"), pytest.param("Needs 180 days of simulation data.", id="empty-message")],
)
def test_a_chart_panel_of_a_figure_read_under_a_name_its_page_never_set_fails_the_render_naming_that_name(
    app: Flask, empty_message: str
) -> None:
    """A misspelt chart key reads as undefined, which chart_panel refuses rather than leave the chart, or its empty message's card, in place of the figure."""
    page = app.jinja_env.from_string(
        '{% from "components/macros.html" import chart_panel %}'
        "{{ chart_panel('chart-seasonal', 'Seasonal Comparison', charts.sesonal, '420px', empty_message=empty_message) }}"
    )

    with pytest.raises(UndefinedError, match="'sesonal'"):
        page.render(charts={"seasonal": _FIGURE}, empty_message=empty_message)


def test_a_chart_container_given_no_figure_carries_none(macros: Any) -> None:
    """compare.html calls chart_container positionally and draws its own charts, so chart-renderer.js must find no figure there."""
    container = str(macros.chart_container("chart-sample", "Sample Chart", "420px"))

    assert chart_figures(container) == {}
