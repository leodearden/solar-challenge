# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that every colour role of the theme token file's tailwind section
is applied by some dashboard template or script.

Each key of the tailwind section of static/src/theme-tokens.json is a role or a group of
roles. A role names a built-in Tailwind palette, such as ``amber``, which tailwind.config.js
defines under the role's name, such as ``primary``. A group is a JSON object of roles, such
as ``status``, whose palettes Tailwind names ``<group>-<role>``, such as ``status-running``;
tests/_dashboard_sources.py's tailwind_role_palettes reads every role under that name.
Tailwind emits no rule for a palette that no utility applies, so editing its role changes
nothing, yet it reads as the home of a colour. test_web_compiled_css.py guards the other
direction: a utility naming a palette the theme does not define has no rule.

A template or script applies a role as ``<utility>-<role>-<shade>``, and a grouped role as
``<utility>-<group>-<role>-<shade>``, through a class that names one of its shades, whatever
its variants, as tests/_css_classes.py's names_palette reads it: ``bg-primary-500``,
``dark:bg-primary-900/20``, ``bg-status-running-100``. A role applied only through its
``DEFAULT`` shade, as ``bg-<role>``, is not recognised. The applied classes come from
tests/_css_classes.py, whose docstring lists the channels it does not read.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    THEME_TOKENS_KEY,
    dashboard_applied_classes_by_source,
    tailwind_role_palettes,
    theme_tokens,
)


def test_every_theme_palette_is_applied_by_the_dashboard() -> None:
    palettes = list(tailwind_role_palettes(theme_tokens()["tailwind"]))
    assert palettes, (
        f"read no colour role from {THEME_TOKENS_KEY}'s tailwind section, so this guard would "
        "pass vacuously"
    )
    applied = set().union(*dashboard_applied_classes_by_source().values())
    unapplied = sorted(p for p in palettes if not any(names_palette(c, p) for c in applied))

    assert unapplied == [], (
        f"{THEME_TOKENS_KEY}'s tailwind section defines colour roles that no dashboard template "
        f"or script applies: {' '.join(unapplied)}\n"
        "Each key of the section is a role, naming a built-in Tailwind palette, or a group of "
        "roles; a grouped role is listed here as <group>-<role>, the palette its classes write as "
        "<utility>-<group>-<role>-<shade>, as in bg-status-running-100. Tailwind emits no rule "
        "for an unapplied role, so editing it changes nothing: delete the role from "
        f"{THEME_TOKENS_KEY}, or from its group. If the dashboard does apply one, "
        "through a channel tests/_css_classes.py does not read (its docstring lists the known "
        "gaps), extend that reader and pin the new channel in "
        "tests/unit/test_css_classes_helper.py instead. A role applied only through its "
        "DEFAULT shade, as bg-<role>, is not recognised by tests/_css_classes.py's "
        "names_palette: extend it and its pins in tests/unit/test_css_classes_helper.py."
    )
