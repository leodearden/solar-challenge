# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards one invariant of the dashboard's theme colours: no template or script applies
Tailwind's built-in amber, the palette the theme token file names as primary, except as
one of the status and category roles _AMBER_ROLES lists.

An element reaches the accent through a Tailwind utility naming primary: bg-primary-500,
or on a pseudo-element an arbitrary variant such as
[&::-webkit-slider-thumb]:bg-primary-500. A utility naming the built-in palette primary
names, such as bg-amber-500 written for bg-primary-500, is a second home of the accent,
which an edit of the token file's primary does not reach.

Amber also draws a few status and category roles that are independent of the accent, such
as the 'running' run-status badge and the PV distribution card, and no rule over class
names tells those from accent uses. So _AMBER_ROLES lists each role's amber classes and
the templates that apply them, and an amber class passes only in a template whose role
lists it. An accent use written in such a class, in that template, is not caught. Every
listed class must still be applied where it is listed, so no allowance outlives its role.

The amber check holds only while primary names amber, so it first checks that premise:
the tailwind section of static/src/theme-tokens.json must name amber as primary.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    THEME_TOKENS_KEY,
    dashboard_applied_classes_by_source,
    theme_tokens,
)

_BUILT_IN_PALETTE_PRIMARY_NAMES = "amber"


def _amber_classes(classes: Iterable[str]) -> set[str]:
    return {c for c in classes if names_palette(c, _BUILT_IN_PALETTE_PRIMARY_NAMES)}


@dataclass(frozen=True)
class _AmberRole:
    """A status or category the dashboard draws in amber, independently of the accent: the
    amber classes it applies and the keys of the templates that apply them.

    It lists at least one class and one template, and every class names an amber shade: a role
    that does not allows nothing, and no guard would say so."""

    name: str
    classes: frozenset[str]
    sources: frozenset[str]

    def __post_init__(self) -> None:
        if not self.classes:
            raise ValueError(f"{self.name} lists no classes, so it allows nothing")
        if not self.sources:
            raise ValueError(f"{self.name} lists no templates, so it allows nothing")
        not_amber = self.classes - _amber_classes(self.classes)
        if not_amber:
            raise ValueError(
                f"{self.name} lists classes that name no {_BUILT_IN_PALETTE_PRIMARY_NAMES} "
                f"shade, so they allow nothing: {' '.join(sorted(not_amber))}"
            )


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
    ("classes", "sources", "rejection"),
    [
        pytest.param("", ["templates/listed.html"], "badge lists no classes", id="no classes"),
        pytest.param("bg-amber-50", [], "badge lists no templates", id="no templates"),
    ],
)
def test_an_amber_role_listing_no_class_or_no_template_is_rejected(
    classes: str, sources: list[str], rejection: str
) -> None:
    with pytest.raises(ValueError, match=rejection):
        _amber_role("badge", classes, *sources)


def test_an_amber_role_listing_a_class_naming_no_amber_shade_is_rejected_naming_it() -> None:
    with pytest.raises(ValueError, match="badge") as rejected:
        _amber_role(
            "badge", "bg-amber-50 hover:bg-primary-500 text-slate-500", "templates/listed.html"
        )

    message = str(rejected.value)
    assert "hover:bg-primary-500" in message
    assert "text-slate-500" in message
    assert "bg-amber-50" not in message


def test_no_template_or_script_applies_amber_outside_a_listed_status_or_category_role() -> None:
    primary = theme_tokens()["tailwind"]["primary"]
    assert primary == _BUILT_IN_PALETTE_PRIMARY_NAMES, (
        f"{THEME_TOKENS_KEY}'s tailwind section names {primary!r} as primary, not Tailwind's "
        f"built-in {_BUILT_IN_PALETTE_PRIMARY_NAMES}, so a class naming "
        f"{_BUILT_IN_PALETTE_PRIMARY_NAMES} would be a colour of its own, not a second home "
        "of the accent. Point _BUILT_IN_PALETTE_PRIMARY_NAMES at the built-in palette primary "
        "now names, and list the status and category roles drawn in it in _AMBER_ROLES."
    )
    applied = dashboard_applied_classes_by_source()
    assert any(applied.values()), (
        "read no class from the dashboard's templates and scripts, so this guard would pass "
        "vacuously"
    )

    unlisted = _unlisted_amber_classes(applied, _AMBER_ROLES)

    assert unlisted == {}, (
        "These templates and scripts apply classes naming Tailwind's built-in "
        f"{_BUILT_IN_PALETTE_PRIMARY_NAMES}, the palette {THEME_TOKENS_KEY} names as primary, "
        f"outside the status and category roles _AMBER_ROLES lists:{_listing(unlisted)}\n"
        "An accent use (a button, tab, link, toggle, spinner or focus ring) names primary "
        "instead, the same colour, so an edit of the token file's primary reaches it: "
        f"bg-primary-500 for bg-{_BUILT_IN_PALETTE_PRIMARY_NAMES}-500. Then rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        "static/dist/style.css. A status or category that is independent of the accent, like "
        "the roles _AMBER_ROLES lists, gets an entry there naming the role, its "
        f"{_BUILT_IN_PALETTE_PRIMARY_NAMES} classes and the templates that apply them."
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
