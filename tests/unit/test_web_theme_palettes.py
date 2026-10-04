# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that every colour palette tailwind.config.js defines is applied
by some dashboard template or script.

Tailwind emits no rule for a palette that no utility applies, so editing it changes
nothing, yet it reads as the home of a colour. test_web_compiled_css.py guards the other
direction: a utility naming a palette the theme does not define has no rule.

A palette is a key, bare or quoted, whose value is an object literal of six-digit hex
shades, such as ``primary: { 50: '#fffbeb', ... }``. A palette written any other way, such
as a reference to one of Tailwind's built-in palettes, is not read.

A template or script applies a palette through a class that ends with
``-<palette>-<shade>``, optionally followed by an opacity modifier, whatever its variants:
``bg-primary-500``, ``dark:[&::-webkit-slider-thumb]:bg-primary-400``,
``dark:bg-primary-900/20``. A palette applied only through its ``DEFAULT`` shade, as
``bg-<palette>``, is not recognised: a bare ``-<palette>`` suffix would also match
hand-written classes such as ``btn--primary``, so an unused palette could pass. The
applied classes come from tests/_css_classes.py, whose docstring lists the channels it
does not read.
"""

import re

import pytest

pytest.importorskip("jinja2")
from tests._dashboard_sources import (
    TAILWIND_CONFIG_KEY,
    dashboard_applied_classes_by_source,
    tailwind_config_source,
)

_PALETTE = re.compile(r"""['"]?([\w-]+)['"]?\s*:\s*\{[^{}]*#[0-9a-fA-F]{6}""")


def _palette_names(config_source: str) -> list[str]:
    """The names of the colour palettes *config_source* defines, in source order."""
    return _PALETTE.findall(config_source)


def _applies(applied_class: str, palette: str) -> bool:
    return re.search(rf"-{re.escape(palette)}-\w+(?:/\S+)?$", applied_class) is not None


@pytest.mark.parametrize(
    ("config_source", "names"),
    [
        pytest.param("brand: { 50: '#ffffff' }", ["brand"], id="bare key"),
        pytest.param("'brand-x': { 50: '#ffffff' }", ["brand-x"], id="single-quoted key"),
        pytest.param('"brand-x": { 50: "#ffffff" }', ["brand-x"], id="double-quoted key"),
        pytest.param(
            "brand: { 50: '#ffffff' }, 'brand-x': { 50: '#ffffff' }",
            ["brand", "brand-x"],
            id="bare and quoted keys side by side",
        ),
    ],
)
def test_palette_names_are_read_from_bare_and_quoted_keys(
    config_source: str, names: list[str]
) -> None:
    assert _palette_names(config_source) == names


def test_every_theme_palette_is_applied_by_the_dashboard() -> None:
    palettes = _palette_names(tailwind_config_source())
    assert palettes, (
        f"read no colour palette from {TAILWIND_CONFIG_KEY}, so this guard would pass vacuously"
    )
    applied = set().union(*dashboard_applied_classes_by_source().values())
    unapplied = sorted(p for p in palettes if not any(_applies(c, p) for c in applied))

    assert unapplied == [], (
        f"{TAILWIND_CONFIG_KEY} defines colour palettes that no dashboard template or script "
        f"applies: {' '.join(unapplied)}\n"
        "Tailwind emits no rule for them, so editing them changes nothing: delete the palette. "
        "If the dashboard does apply one, through a channel tests/_css_classes.py does not read "
        "(its docstring lists the known gaps), extend that reader and pin the new channel in "
        "tests/unit/test_css_classes_helper.py instead. A palette applied only through its "
        "DEFAULT shade, as bg-<palette>, is not recognised by _applies in this module: extend it."
    )
