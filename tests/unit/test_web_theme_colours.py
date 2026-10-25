# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards one invariant of the dashboard's theme colours: the accent is the only use of the
built-in Tailwind palette the accent names.

The tailwind section of static/src/theme-tokens.json names the accent, primary, as a built-in
palette, such as amber. An element reaches the accent through a Tailwind utility naming
primary: bg-primary-500, or on a pseudo-element an arbitrary variant such as
[&::-webkit-slider-thumb]:bg-primary-500. A class naming the palette primary names, such as
bg-amber-500, is a second home of the accent, which an edit of primary never reaches.

A UI colour independent of the accent, such as a run status or a fleet component, names its
own role's palette from the same section, as in bg-status-running-100, even when that role
names the accent's palette too. So no template or script applies a class naming the accent's
palette, and there is no allow-list.
"""

from collections.abc import Mapping

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import names_palette
from tests._dashboard_sources import (
    THEME_TOKENS_KEY,
    dashboard_applied_classes_by_source,
    theme_tokens,
)


def _listing(written: Mapping[str, list[str]]) -> str:
    return "".join(f"\n  {path}: {' '.join(colours)}" for path, colours in written.items())


def test_no_template_or_script_applies_the_built_in_palette_the_accent_names() -> None:
    accent = theme_tokens()["tailwind"]["primary"]
    applied = dashboard_applied_classes_by_source()
    assert any(applied.values()), (
        "read no class from the dashboard's templates and scripts, so this guard would pass "
        "vacuously"
    )

    accent_palette_classes = {
        source: sorted(named)
        for source, classes in applied.items()
        if (named := {c for c in classes if names_palette(c, accent)})
    }

    assert accent_palette_classes == {}, (
        f"These templates and scripts apply classes naming Tailwind's built-in {accent}, the "
        f"palette {THEME_TOKENS_KEY}'s tailwind section names as primary, the accent:"
        f"{_listing(accent_palette_classes)}\n"
        "An accent use (a button, tab, link, toggle, spinner or focus ring) names primary "
        "instead, the same colour, so an edit of primary reaches it: bg-primary-500 for "
        f"bg-{accent}-500. A UI role independent of the accent, such as a run status or a "
        "fleet component, names its role's palette from the token file's tailwind section, as "
        "in bg-status-running-100; a new role is added there first, naming a built-in "
        "palette. Then rebuild with `cd src/solar_challenge/web && npm ci && npm run build:css` "
        "and commit static/dist/style.css."
    )
