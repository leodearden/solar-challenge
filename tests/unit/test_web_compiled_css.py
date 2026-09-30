# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that every class a dashboard template or script applies is
named by a selector in a stylesheet base.html links.

static/dist/style.css is compiled by Tailwind from templates/ and static/js/, and
nothing rebuilds it automatically. A class added without ``npm run build:css``
therefore silently has no effect in the browser (task 170 found nine).
"""

from pathlib import Path

import pytest

import solar_challenge.web

pytest.importorskip("jinja2")
from tests._css_classes import (
    applied_classes_in_script,
    applied_classes_in_template,
    linked_stylesheets,
    selector_classes,
)

WEB_DIR = Path(solar_challenge.web.__file__).parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative(path: Path) -> str:
    return path.relative_to(WEB_DIR).as_posix()


def _served_classes() -> set[str]:
    """Classes named by the stylesheets base.html links; every page template extends base.html."""
    stylesheets = linked_stylesheets(_read(WEB_DIR / "templates" / "base.html"))
    return {
        name
        for stylesheet in stylesheets
        for name in selector_classes(_read(WEB_DIR / "static" / stylesheet))
    }


def _applied_classes_by_source() -> dict[str, set[str]]:
    """Classes each dashboard template and script applies, keyed by its path relative to WEB_DIR."""
    templates = sorted((WEB_DIR / "templates").rglob("*.html"))
    scripts = sorted((WEB_DIR / "static" / "js").rglob("*.js"))
    return {
        **{_relative(path): applied_classes_in_template(_read(path)) for path in templates},
        **{_relative(path): applied_classes_in_script(_read(path)) for path in scripts},
    }


def test_every_class_the_dashboard_applies_is_named_by_a_served_stylesheet() -> None:
    applied = _applied_classes_by_source()
    served = _served_classes()

    assert applied, f"found no dashboard templates or scripts under {WEB_DIR}"
    unstyled = {
        source: sorted(classes - served) for source, classes in applied.items() if classes - served
    }
    listing = "".join(f"\n  {source}: {' '.join(names)}" for source, names in unstyled.items())
    assert unstyled == {}, (
        "These classes have no rule in any stylesheet base.html links, so they do nothing "
        f"in the browser:{listing}\n"
        "For Tailwind utilities, rebuild with "
        "`cd src/solar_challenge/web && npm install && npm run build:css`, then commit "
        "static/dist/style.css. For a hand-written class, define it in static/style.css."
    )
