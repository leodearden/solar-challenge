# SPDX-License-Identifier: AGPL-3.0-or-later
"""chart_panel, of components/macros.html, draws the card of a chart panel. A panel's
figure goes in its container, which static/js/chart-renderer.js draws, so a page writes each
chart's id once; an absent panel's card gives the absence's reason instead, on an element of
the same id. A panel read under a name the page's route never set is undefined, and fails
the render, naming that name. chart_tabs draws a page's chart tabs: one tab bar, whose first
tab the server draws selected, and each tab's panels.

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
from tests._html_page import chart_figures, element_attributes, element_count, element_ids, headings, texts

_FIGURE = json.dumps(
    {
        "data": [{"type": "bar", "x": ["a"], "y": [1]}],
        "layout": {"title": {"text": "<b>Tom's \"best\" day</b> & more"}},
    }
)


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
    card = str(macros.chart_panel(ChartPanel("chart-sample", "Sample Chart", 420, _FIGURE)))

    assert headings(card) == ["Sample Chart"]
    assert chart_figures(card) == {"chart-sample": _FIGURE}
    assert element_count(card, "div", {"id": "chart-sample", "style": "min-height: 420px;"}) == 1


def test_a_chart_panel_of_an_absence_draws_a_card_titled_with_its_title_that_gives_the_reason(
    macros: Any,
) -> None:
    card = str(macros.chart_panel(ChartPanel("chart-sample", "Sample Chart", 420, ChartAbsence("Needs 180 days."))))

    assert texts(card) == ["Sample Chart", "Needs 180 days."]
    assert element_ids(card) == {"chart-sample"}
    assert chart_figures(card) == {}


def test_a_chart_panel_of_a_panel_read_under_a_name_its_page_never_set_fails_the_render_naming_that_name(
    app: Flask,
) -> None:
    """A misspelt panel name reads as undefined, which fails chart_panel's first read of it rather than draw a card."""
    page = app.jinja_env.from_string(
        '{% from "components/macros.html" import chart_panel %}{{ chart_panel(sesonal) }}'
    )

    with pytest.raises(UndefinedError, match="'sesonal'"):
        page.render(seasonal=_panel())


def test_chart_tabs_draw_one_tab_bar_whose_first_tab_is_selected_and_every_panel_of_every_tab(
    macros: Any,
) -> None:
    tabs = (
        ChartTab("overview", "Overview", (_panel(dom_id="chart-first"),)),
        ChartTab("analysis", "Analysis", (_panel(dom_id="chart-second", content=ChartAbsence("Needs 180 days.")),)),
    )

    drawn = str(macros.chart_tabs(tabs))

    tab_buttons = [button for button in element_attributes(drawn, "button") if button.get("role") == "tab"]
    assert element_count(drawn, "nav", {"role": "tablist"}) == 1
    assert texts(drawn)[:2] == ["Overview", "Analysis"]
    assert [button.get("aria-selected") for button in tab_buttons] == ["true", "false"]
    assert element_ids(drawn) == {"chart-first", "chart-second"}
