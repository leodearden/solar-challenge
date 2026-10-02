# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that tailwind.config.js is the one home of the dashboard's
theme colours, so no template and no hand-written stylesheet writes a colour value
the theme defines.

An element reaches a theme colour through a Tailwind utility: bg-primary-500, or on a
pseudo-element an arbitrary variant such as [&::-webkit-slider-thumb]:bg-primary-500.
A written-out value is a second home that a theme edit does not reach. Task 235 found
the range thumbs' --color-primary and a commented-out copy of the whole theme in
base.html.

A colour is a six-digit hex literal, matched case-insensitively anywhere in a source,
comments included. The compiled dist/style.css derives from the theme and is not
checked. Scripts hand colour strings to chart libraries and are not checked either.
"""

import re
from collections.abc import Mapping

import pytest

pytest.importorskip("jinja2")
from tests._dashboard_sources import dashboard_template_sources, tailwind_config_source

_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def _hex_colours(source: str) -> set[str]:
    """The six-digit hex colours *source* writes, lower-cased. An eight-digit colour
    such as #f59e0bcc counts through its first six digits."""
    return {colour.lower() for colour in _HEX_COLOUR.findall(source)}


def _written_theme_colours(sources: Mapping[str, str]) -> dict[str, list[str]]:
    """The theme colours each of *sources* writes, keyed by its path, for each source
    that writes any."""
    theme = _hex_colours(tailwind_config_source())
    assert theme, "read no hex colour from tailwind.config.js, so this guard would pass vacuously"
    return {
        path: sorted(written)
        for path, source in sources.items()
        if (written := _hex_colours(source) & theme)
    }


def test_no_template_writes_a_theme_colour() -> None:
    written = _written_theme_colours(dashboard_template_sources())

    listing = "".join(f"\n  {path}: {' '.join(colours)}" for path, colours in written.items())
    assert written == {}, (
        "These templates write out colours that tailwind.config.js defines, so a theme "
        f"edit does not reach them:{listing}\n"
        "Name the colour through a Tailwind utility instead, such as bg-primary-500, then "
        "rebuild with `cd src/solar_challenge/web && npm install && npm run build:css` and "
        "commit static/dist/style.css. Delete a commented-out copy."
    )
