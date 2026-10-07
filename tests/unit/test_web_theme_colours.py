# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards two invariants of the dashboard's theme colours: no template and no hand-written
stylesheet writes out a hex colour that tailwind.config.js defines, and no template or
script draws a focus indicator in Tailwind's built-in amber, whose shades the theme's
primary copies.

An element reaches a theme colour through a Tailwind utility: bg-primary-500, or on a
pseudo-element an arbitrary variant such as [&::-webkit-slider-thumb]:bg-primary-500.
A written-out value is a second home that a theme edit does not reach, and so is a
utility naming a built-in palette whose shades the theme copies, such as
focus:ring-amber-500 written for focus:ring-primary-500.

A colour is a six-digit hex literal, matched case-insensitively anywhere in a source,
comments included. The compiled dist/style.css derives from the theme and is not
checked. The hex checks skip scripts, which hand colour strings to chart libraries.

A focus indicator is a class, as tests/_css_classes.py reads it, under a focus,
focus-visible or focus-within variant, alone or as group- or peer-. Amber utilities
outside focus indicators are not checked: amber also marks status and category roles
that are independent of the accent, such as the 'running' status badge and the PV
distribution card, and no rule over class names tells those from accent uses.
"""

import re
from collections.abc import Iterable, Mapping

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    dashboard_applied_classes_by_source,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    tailwind_config_source,
)

_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
_BUILT_IN_PALETTE_PRIMARY_COPIES = "amber"
_FOCUS_VARIANT = re.compile(r"(?:^|:)(?:(?:group|peer)-)?focus(?:-visible|-within)?:")


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


def _focus_indicators_naming(palette: str, applied: Iterable[str]) -> list[str]:
    """The focus indicators among the *applied* classes that name a shade of *palette*."""
    return sorted(c for c in applied if _FOCUS_VARIANT.search(c) and names_palette(c, palette))


def _listing(written: Mapping[str, list[str]]) -> str:
    return "".join(f"\n  {path}: {' '.join(colours)}" for path, colours in written.items())


def test_no_template_writes_a_theme_colour() -> None:
    written = _written_theme_colours(dashboard_template_sources())

    assert written == {}, (
        "These templates write out colours that tailwind.config.js defines, so a theme "
        f"edit does not reach them:{_listing(written)}\n"
        "Name the colour through a Tailwind utility instead, such as bg-primary-500, then "
        "rebuild with `cd src/solar_challenge/web && npm ci && npm run build:css` and "
        "commit static/dist/style.css. Delete a commented-out copy."
    )


def test_the_hand_written_stylesheet_writes_no_theme_colour() -> None:
    written = _written_theme_colours(
        {HAND_WRITTEN_STYLESHEET_KEY: hand_written_stylesheet_source()}
    )

    assert written == {}, (
        "The hand-written stylesheet writes out colours that tailwind.config.js defines, so "
        f"a theme edit does not reach them:{_listing(written)}\n"
        f"{HAND_WRITTEN_STYLESHEET_KEY} is served as-is, never compiled, so it cannot name a "
        "theme colour. Colour the element with a Tailwind utility instead (on a pseudo-element, "
        "an arbitrary variant such as [&::-webkit-slider-thumb]:bg-primary-500), then rebuild "
        "with `cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        "static/dist/style.css. Delete the declaration, including both the :root and the "
        "html.dark copy of a variable."
    )


def test_no_template_or_script_draws_a_focus_indicator_in_amber() -> None:
    applied = dashboard_applied_classes_by_source()
    assert _focus_indicators_naming("primary", set().union(*applied.values())), (
        "read no focus indicator naming primary from the dashboard's templates and scripts, "
        "so this guard's reader may be broken and pass vacuously"
    )
    drawn = {
        path: found
        for path, classes in applied.items()
        if (found := _focus_indicators_naming(_BUILT_IN_PALETTE_PRIMARY_COPIES, classes))
    }

    assert drawn == {}, (
        "These templates and scripts draw focus indicators in Tailwind's built-in "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES}, whose shades tailwind.config.js's primary "
        f"copies, so a theme edit does not reach them:{_listing(drawn)}\n"
        "Name primary instead, the same colour: focus:ring-primary-500 for "
        f"focus:ring-{_BUILT_IN_PALETTE_PRIMARY_COPIES}-500. Then rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        "static/dist/style.css."
    )
