# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that no dashboard source writes out a colour that charts.py's
COLOUR_PALETTE defines: not tailwind.config.js, not a template, not the hand-written
stylesheet and not a script.

The charts take their colours from COLOUR_PALETTE as strings, which Plotly needs, so a
copy in any of these sources is a second home that a palette edit does not reach.

A colour counts as written where its hex literal appears in a source, matched
case-insensitively anywhere, comments included, so an eight-digit #rrggbbaa copy counts
through its prefix. Not checked: the compiled dist/style.css, which derives from the
templates and the theme; rgb() and rgba() forms; and the Python modules, charts.py
included.
"""

import pytest

pytest.importorskip("jinja2")
pytest.importorskip("plotly")
from solar_challenge.web.charts import COLOUR_PALETTE
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    TAILWIND_CONFIG_KEY,
    dashboard_script_sources,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    tailwind_config_source,
)

_CHART_COLOURS = frozenset(colour.lower() for colour in COLOUR_PALETTE.values())


def _written_chart_colours(source: str) -> list[str]:
    """The chart colours *source* writes out, sorted."""
    lowered = source.lower()
    return sorted(colour for colour in _CHART_COLOURS if colour in lowered)


def test_no_dashboard_source_writes_out_a_chart_colour() -> None:
    assert _CHART_COLOURS, "COLOUR_PALETTE defines no colour, so this guard would pass vacuously"
    sources = {
        TAILWIND_CONFIG_KEY: tailwind_config_source(),
        **dashboard_template_sources(),
        HAND_WRITTEN_STYLESHEET_KEY: hand_written_stylesheet_source(),
        **dashboard_script_sources(),
    }

    written = {
        path: colours
        for path, source in sources.items()
        if (colours := _written_chart_colours(source))
    }

    listing = "".join(f"\n  {path}: {' '.join(colours)}" for path, colours in written.items())
    assert written == {}, (
        "These dashboard sources write out colours that charts.py's COLOUR_PALETTE defines, "
        f"so a palette edit does not reach them:{listing}\n"
        "The charts take their colours from COLOUR_PALETTE, because Plotly needs colour "
        "strings rather than Tailwind classes. Delete the copy. If a page must show a chart "
        "colour, pass it from COLOUR_PALETTE to the page."
    )
