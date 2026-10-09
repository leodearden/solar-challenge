# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards two invariants of the dashboard's theme colours: no template and no hand-written
stylesheet writes out a hex colour that tailwind.config.js defines, and no template or
script applies Tailwind's built-in amber, whose shades the theme's primary copies, except
as one of the status and category roles _AMBER_ROLES lists.

An element reaches a theme colour through a Tailwind utility: bg-primary-500, or on a
pseudo-element an arbitrary variant such as [&::-webkit-slider-thumb]:bg-primary-500.
A written-out value is a second home that a theme edit does not reach, and so is a
utility naming a built-in palette whose shades the theme copies, such as
bg-amber-500 written for bg-primary-500.

A colour is a six-digit hex literal, matched case-insensitively anywhere in a source,
comments included. The compiled dist/style.css derives from the theme and is not
checked. The hex checks skip scripts, which hand colour strings to chart libraries.

Amber also draws a few status and category roles that are independent of the accent, such
as the 'running' run-status badge and the PV distribution card, and no rule over class
names tells those from accent uses. So _AMBER_ROLES lists each role's amber classes and
the templates that apply them, and an amber class passes only in a template whose role
lists it. An accent use written in such a class, in that template, is not caught. Every
listed class must still be applied where it is listed, so no allowance outlives its role.

The amber check holds only while primary copies amber, so it first checks that premise
through one shade: tailwind.config.js's primary-500 must be amber-500's value.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

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


@dataclass(frozen=True)
class _AmberRole:
    """A status or category the dashboard draws in amber, independently of the accent: the
    amber classes it applies and the keys of the templates that apply them."""

    name: str
    classes: frozenset[str]
    sources: frozenset[str]


def _amber_role(name: str, classes: str, *sources: str) -> _AmberRole:
    return _AmberRole(name, frozenset(classes.split()), frozenset(sources))


_AMBER_ROLES = (
    _amber_role(
        "the 'AI assistant not configured' warning banner",
        "border-amber-300 bg-amber-50 text-amber-800 "
        "dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-300",
        "templates/assistant/chat.html",
    ),
    _amber_role(
        "the 'running' run-status badge",
        "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400",
        "templates/dashboard.html",
        "templates/history/runs.html",
    ),
    _amber_role(
        "the progress bar of a run that has not completed",
        "bg-amber-500",
        "templates/simulate/partials/progress-tracker.html",
    ),
    _amber_role(
        "the Run Single Home quick-action card",
        "hover:border-amber-300 dark:hover:border-amber-600 "
        "bg-amber-50 dark:bg-amber-900/30 "
        "group-hover:bg-amber-100 dark:group-hover:bg-amber-900/50 "
        "text-amber-600 dark:text-amber-400 "
        "group-hover:text-amber-600 dark:group-hover:text-amber-400",
        "templates/dashboard.html",
    ),
    _amber_role(
        "the PV distribution card",
        "bg-amber-50 dark:bg-amber-900/20 bg-amber-500",
        "templates/simulate/fleet.html",
    ),
)


def _amber_classes(applied: set[str]) -> set[str]:
    return {c for c in applied if names_palette(c, _BUILT_IN_PALETTE_PRIMARY_COPIES)}


def _classes_listed_for(source: str, roles: Collection[_AmberRole]) -> set[str]:
    return {c for role in roles if source in role.sources for c in role.classes}


def _unlisted_amber_classes(
    applied_by_source: Mapping[str, set[str]], roles: Collection[_AmberRole]
) -> dict[str, list[str]]:
    """The amber classes each source applies that no role lists for that source, keyed by
    source, for each source that applies any."""
    return {
        source: sorted(unlisted)
        for source, applied in applied_by_source.items()
        if (unlisted := _amber_classes(applied) - _classes_listed_for(source, roles))
    }


def _unapplied_role_classes(
    applied_by_source: Mapping[str, set[str]], roles: Collection[_AmberRole]
) -> dict[tuple[str, str], list[str]]:
    """The classes each role lists that a source it lists does not apply, keyed by the
    role's name and that source, for each pair with any."""
    return {
        (role.name, source): sorted(unapplied)
        for role in roles
        for source in sorted(role.sources)
        if (unapplied := role.classes - applied_by_source.get(source, set()))
    }


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


def test_no_template_or_script_applies_amber_outside_a_listed_status_or_category_role() -> None:
    assert _primary_500() == _BUILT_IN_500_SHADE_PRIMARY_COPIES, (
        f"{TAILWIND_CONFIG_KEY}'s primary-500 is not Tailwind's built-in "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES}-500, so primary no longer copies "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES} and a class naming "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES} would be a colour of its own, not a second home "
        "of a theme colour. Point _BUILT_IN_PALETTE_PRIMARY_COPIES and "
        "_BUILT_IN_500_SHADE_PRIMARY_COPIES at the built-in palette primary now copies, and "
        "list the status and category roles drawn in it in _AMBER_ROLES, or delete this test "
        "and _AMBER_ROLES if it copies none."
    )
    applied = dashboard_applied_classes_by_source()
    assert any(names_palette(c, "primary") for classes in applied.values() for c in classes), (
        "read no class naming primary from the dashboard's templates and scripts, so this "
        "guard's reader may be broken and pass vacuously"
    )

    unlisted = _unlisted_amber_classes(applied, _AMBER_ROLES)

    assert unlisted == {}, (
        "These templates and scripts apply classes naming Tailwind's built-in "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES}, whose shades tailwind.config.js's primary copies, "
        f"outside the status and category roles _AMBER_ROLES lists:{_listing(unlisted)}\n"
        "An accent use (a button, tab, link, toggle, spinner or focus ring) names primary "
        "instead, the same colour, so a theme edit reaches it: bg-primary-500 for "
        f"bg-{_BUILT_IN_PALETTE_PRIMARY_COPIES}-500. Then rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        "static/dist/style.css. A status or category that is independent of the accent, like "
        "the roles _AMBER_ROLES lists, gets an entry there naming the role, its "
        f"{_BUILT_IN_PALETTE_PRIMARY_COPIES} classes and the templates that apply them."
    )


def test_every_listed_amber_role_is_applied_where_it_is_listed() -> None:
    undrawn = _unapplied_role_classes(dashboard_applied_classes_by_source(), _AMBER_ROLES)
    classes_by_source_and_role = {
        f"{source}, {role}": classes for (role, source), classes in undrawn.items()
    }

    assert undrawn == {}, (
        "These status and category roles list classes that a template listed for them does "
        f"not apply:{_listing(classes_by_source_and_role)}\n"
        "An allowance nothing applies would let an accent use written in that class pass "
        "unseen. If the role moved, for example into a macro, list the template it moved to; "
        "if it was restyled or deleted, update or delete its entry."
    )
