# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that the range_input macro in components/macros.html draws
every range input on the dashboard.

static/style.css shapes every range thumb (appearance none, a 1rem circle, a white
border, a shadow) but leaves its fill to the theme utilities range_input applies. A
range input written out in any other template therefore shows a hollow thumb: task 235
measured it in Chromium, where the slate-200 track shows through.
"""

from html.parser import HTMLParser

import pytest

pytest.importorskip("jinja2")
from tests._dashboard_sources import dashboard_template_sources

MACRO_LIBRARY_KEY = "templates/components/macros.html"


class _RangeInputCounter(HTMLParser):
    """Counts the ``<input>`` start tags whose ``type`` is ``range``."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "input" and any(
            name == "type" and (value or "").lower() == "range" for name, value in attrs
        ):
            self.count += 1


def _range_input_count(source: str) -> int:
    counter = _RangeInputCounter()
    counter.feed(source)
    counter.close()
    return counter.count


def test_every_range_input_is_drawn_by_the_range_input_macro() -> None:
    templates = dashboard_template_sources()
    written_out = {
        path: count
        for path, source in templates.items()
        if path != MACRO_LIBRARY_KEY and (count := _range_input_count(source))
    }

    listing = "".join(f"\n  {path}: {count}" for path, count in written_out.items())
    assert written_out == {}, (
        "These templates write out range inputs instead of drawing them with the "
        f"range_input macro:{listing}\n"
        "Draw each slider with {{ range_input(...) }} from components/macros.html, whose "
        "class list gives the thumb the theme's colour."
    )
    drawn_by_macro = _range_input_count(templates[MACRO_LIBRARY_KEY])
    assert drawn_by_macro == 1, (
        f"read {drawn_by_macro} range inputs from {MACRO_LIBRARY_KEY}, where range_input "
        "draws exactly one, so the reader or the macro changed and this guard may pass "
        "vacuously"
    )
