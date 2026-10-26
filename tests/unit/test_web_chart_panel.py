# SPDX-License-Identifier: AGPL-3.0-or-later
"""chart_panel, of components/macros.html, draws the card of a chart that
static/js/chart-renderer.js draws from the figure its container carries, so a page writes
each chart's id once. A figure with nothing to draw, None or '{}', gets the card of a
message instead, or no card. A figure read under a name the page's route never set is
undefined, and fails the render, naming that name.

A chart is described by the frozen types of solar_challenge.web.charts: a ChartPanel holds
its id, title, height and content, a figure's JSON or the ChartAbsence that says why there
is none, and a ChartTab groups panels under a tab. Each refuses, naming the field and the
value, what the old convention allowed, so a figure of '{}' cannot be constructed.
"""

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask
from jinja2 import UndefinedError

from solar_challenge.web.charts import ChartAbsence, ChartPanel, ChartTab
from tests._html_page import chart_figures, element_count, element_ids, headings, texts

_FIGURE = json.dumps(
    {
        "data": [{"type": "bar", "x": ["a"], "y": [1]}],
        "layout": {"title": {"text": "<b>Tom's \"best\" day</b> & more"}},
    }
)
_NOTHING_TO_DRAW = [pytest.param(None, id="none"), pytest.param("{}", id="empty-object")]


def _panel(**fields: Any) -> ChartPanel:
    """A panel of _FIGURE titled 'Sample Chart', 420 px high, with *fields* in place of those."""
    return ChartPanel(
        **{"dom_id": "chart-sample", "title": "Sample Chart", "height_px": 420, "content": _FIGURE, **fields}
    )


def _tab(**fields: Any) -> ChartTab:
    """A tab 'Overview' of one _panel(), with *fields* in place of those."""
    return ChartTab(**{"key": "overview", "label": "Overview", "panels": (_panel(),), **fields})


_BUILD_WITH: dict[str, Callable[[Any], object]] = {
    "ChartPanel.dom_id": lambda value: _panel(dom_id=value),
    "ChartPanel.title": lambda value: _panel(title=value),
    "ChartPanel.height_px": lambda value: _panel(height_px=value),
    "ChartPanel.content": lambda value: _panel(content=value),
    "ChartAbsence.reason": lambda value: _panel(content=ChartAbsence(value)),
    "ChartTab.key": lambda value: _tab(key=value),
    "ChartTab.label": lambda value: _tab(label=value),
    "ChartTab.panels": lambda value: _tab(panels=value),
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ChartPanel.content", "{}"),
        ("ChartPanel.content", ""),
        ("ChartPanel.content", "   "),
        ("ChartPanel.dom_id", "Chart 1"),
        ("ChartPanel.dom_id", "chart_1"),
        ("ChartPanel.title", ""),
        ("ChartPanel.title", "  "),
        ("ChartPanel.height_px", 0),
        ("ChartPanel.height_px", -5),
        ("ChartAbsence.reason", ""),
        ("ChartAbsence.reason", "  "),
        ("ChartTab.key", "Power Flow"),
        ("ChartTab.key", ""),
        ("ChartTab.label", ""),
        ("ChartTab.panels", ()),
    ],
)
def test_a_chart_type_refuses_a_value_its_field_forbids_naming_the_field_and_the_value(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError) as refusal:
        _BUILD_WITH[field](value)

    message = str(refusal.value)
    assert field in message and repr(value) in message, message


def test_a_panel_of_a_figure_reads_as_the_figure_and_no_absence() -> None:
    panel = _panel(content=_FIGURE)

    assert (panel.figure_json, panel.absence_reason) == (_FIGURE, None)


def test_a_panel_of_an_absence_reads_as_its_reason_and_no_figure() -> None:
    panel = _panel(content=ChartAbsence("Needs 90 days."))

    assert (panel.figure_json, panel.absence_reason) == (None, "Needs 90 days.")


def test_a_panel_is_frozen() -> None:
    panel = _panel()

    with pytest.raises(dataclasses.FrozenInstanceError):
        panel.content = ChartAbsence("Needs 90 days.")


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
