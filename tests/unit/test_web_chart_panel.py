# SPDX-License-Identifier: AGPL-3.0-or-later
"""chart_panel, of components/macros.html, draws the card of a chart that
static/js/chart-renderer.js draws from the figure its container carries, so a page writes
each chart's id once. A figure with nothing to draw, None or '{}', gets the card of a
message instead, or no card.
"""

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

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
def macros(tmp_path: Path) -> Any:
    """The public macros of components/macros.html, as callables that return their markup."""
    return dashboard_macros_of(build_test_app(tmp_path))


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


def test_a_chart_container_given_no_figure_carries_none(macros: Any) -> None:
    """compare.html calls chart_container positionally and draws its own charts, so chart-renderer.js must find no figure there."""
    container = str(macros.chart_container("chart-sample", "Sample Chart", "420px"))

    assert chart_figures(container) == {}
