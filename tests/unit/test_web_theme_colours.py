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
focus-visible or focus-within variant, alone or as group- or peer-, named or not, such as
group-focus/item:. An arbitrary variant that selects focus, such as [&:focus]:, is not
read. Amber utilities outside focus indicators are not checked: amber also marks status
and category roles that are independent of the accent, such as the 'running' status
badge and the PV distribution card, and no rule over class names tells those from accent
uses.

The focus check holds only while primary copies amber, so it first checks that premise
through one shade: tailwind.config.js's primary-500 must be amber-500's value.
"""

import re
from collections.abc import Iterable, Mapping

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    TAILWIND_CONFIG_KEY,
    dashboard_applied_classes_by_source,
    dashboard_template_sources,
    hand_written_stylesheet_source,
    tailwind_config_source,
)

_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
_BUILT_IN_PALETTE_PRIMARY_COPIES = "amber"
_BUILT_IN_500_SHADE_PRIMARY_COPIES = "#f59e0b"
_PRIMARY_500_ENTRY = re.compile(
    r"""\bprimary\s*:\s*\{[^{}]*?\b500\s*:\s*['"](#[0-9a-fA-F]{6})['"]"""
)
_FOCUS_VARIANT = re.compile(r"(?:^|:)(?:(?:group|peer)-)?focus(?:-visible|-within)?(?:/[\w-]+)?:")


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


def _primary_500() -> str:
    """The hex colour tailwind.config.js gives primary's 500 shade, lower-cased."""
    entry = _PRIMARY_500_ENTRY.search(tailwind_config_source())
    assert entry, (
        f"read no hex primary-500 from {TAILWIND_CONFIG_KEY}, so this guard cannot check that "
        f"primary still copies Tailwind's built-in {_BUILT_IN_PALETTE_PRIMARY_COPIES}: extend "
        "_PRIMARY_500_ENTRY to read the form primary-500 is now written in"
    )
    return entry[1].lower()


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


def test_an_amber_class_passes_only_in_a_source_its_role_lists() -> None:
    badge = _amber_role("badge", "bg-amber-100", "templates/listed.html")
    applied = {
        "templates/listed.html": {"bg-amber-100", "text-amber-600", "bg-primary-500"},
        "templates/unlisted.html": {"bg-amber-100", "hover:bg-sky-500"},
        "static/js/script.js": {"dark:focus:ring-amber-500/50"},
    }

    assert _unlisted_amber_classes(applied, [badge]) == {
        "templates/listed.html": ["text-amber-600"],
        "templates/unlisted.html": ["bg-amber-100"],
        "static/js/script.js": ["dark:focus:ring-amber-500/50"],
    }


def test_a_role_class_a_listed_source_does_not_apply_is_reported() -> None:
    badge = _amber_role(
        "badge",
        "bg-amber-100 text-amber-800",
        "templates/drawn.html",
        "templates/restyled.html",
        "templates/deleted.html",
    )
    applied = {
        "templates/drawn.html": {"bg-amber-100", "text-amber-800"},
        "templates/restyled.html": {"bg-amber-100", "text-primary-800"},
    }

    assert _unapplied_role_classes(applied, [badge]) == {
        ("badge", "templates/restyled.html"): ["text-amber-800"],
        ("badge", "templates/deleted.html"): ["bg-amber-100", "text-amber-800"],
    }


@pytest.mark.parametrize(
    ("css_class", "is_indicator"),
    [
        pytest.param("focus:ring-amber-500", True, id="focus"),
        pytest.param("dark:focus:ring-amber-500", True, id="focus after another variant"),
        pytest.param("focus-visible:ring-amber-500", True, id="focus-visible"),
        pytest.param("group-focus-within:text-amber-500", True, id="group-focus-within"),
        pytest.param("peer-focus:border-amber-500", True, id="peer-focus"),
        pytest.param("group-focus/item:ring-amber-500", True, id="named group"),
        pytest.param("hover:bg-amber-500", False, id="another variant"),
        pytest.param("focus:ring-sky-500", False, id="another palette"),
    ],
)
def test_a_focus_indicator_is_a_shade_of_the_palette_under_any_focus_variant(
    css_class: str, is_indicator: bool
) -> None:
    expected = [css_class] if is_indicator else []

    assert _focus_indicators_naming("amber", [css_class]) == expected


def test_no_template_or_script_draws_a_focus_indicator_in_amber() -> None:
    assert _primary_500() == _BUILT_IN_500_SHADE_PRIMARY_COPIES, (
        f"{TAILWIND_CONFIG_KEY}'s primary-500 is not Tailwind's built-in "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES}-500, so primary no longer copies "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES} and a focus indicator in "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES} would be a colour of its own, not a second home "
        "of a theme colour. Point _BUILT_IN_PALETTE_PRIMARY_COPIES and "
        "_BUILT_IN_500_SHADE_PRIMARY_COPIES at the built-in palette primary now copies, or "
        "delete this test if it copies none."
    )
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
