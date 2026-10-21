# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that every colour role of the theme token file's tailwind section
is applied by some dashboard template or script.

Each key of the tailwind section of static/src/theme-tokens.json, such as ``primary``, is a
role that tailwind.config.js defines as a colour palette of that name, the built-in
Tailwind palette its value names, such as ``amber``. Tailwind emits no rule for a palette
that no utility applies, so editing its role changes nothing, yet it reads as the home of
a colour. test_web_compiled_css.py guards the other direction: a utility naming a palette
the theme does not define has no rule.

A template or script applies a role as ``<utility>-<role>-<shade>``, through a class that
names one of its shades, whatever its variants, as tests/_css_classes.py's names_palette
reads it: ``bg-primary-500``, ``dark:bg-primary-900/20``. A role applied only through its
``DEFAULT`` shade, as ``bg-<role>``, is not recognised. The applied classes come from
tests/_css_classes.py, whose docstring lists the channels it does not read.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    THEME_TOKENS_KEY,
    dashboard_applied_classes_by_source,
    theme_tokens,
)


def test_every_theme_palette_is_applied_by_the_dashboard() -> None:
    palettes = list(theme_tokens()["tailwind"])
    assert palettes, (
        f"read no colour role from {THEME_TOKENS_KEY}'s tailwind section, so this guard would "
        "pass vacuously"
    )
    applied = set().union(*dashboard_applied_classes_by_source().values())
    unapplied = sorted(p for p in palettes if not any(names_palette(c, p) for c in applied))

    assert unapplied == [], (
        f"{THEME_TOKENS_KEY}'s tailwind section defines colour roles that no dashboard template "
        f"or script applies: {' '.join(unapplied)}\n"
        "Tailwind emits no rule for them, so editing them changes nothing: delete the role from "
        f"{THEME_TOKENS_KEY}. If the dashboard does apply one, "
        "through a channel tests/_css_classes.py does not read (its docstring lists the known "
        "gaps), extend that reader and pin the new channel in "
        "tests/unit/test_css_classes_helper.py instead. A role applied only through its "
        "DEFAULT shade, as bg-<role>, is not recognised by tests/_css_classes.py's "
        "names_palette: extend it and its pins in tests/unit/test_css_classes_helper.py."
    )
