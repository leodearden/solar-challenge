# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that every class a dashboard template or script applies is
named by a selector in a stylesheet base.html links.

static/dist/style.css is compiled by Tailwind from templates/ and static/js/, and
nothing rebuilds it automatically. A class added without ``npm run build:css``
therefore silently has no effect in the browser (task 170 found nine).
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import selector_classes
from tests._dashboard_sources import (
    BASE_TEMPLATE_KEY,
    dashboard_applied_classes_by_source,
    served_stylesheet_sources,
)


def _served_classes() -> set[str]:
    """Classes named by the stylesheets base.html links; every page template extends base.html."""
    return {
        name
        for source in served_stylesheet_sources().values()
        for name in selector_classes(source)
    }


def test_every_class_the_dashboard_applies_is_named_by_a_served_stylesheet() -> None:
    applied = dashboard_applied_classes_by_source()
    served = _served_classes()

    assert applied.get(BASE_TEMPLATE_KEY), (
        f"read no classes from {BASE_TEMPLATE_KEY}, the layout every page extends, among "
        f"{len(applied)} templates and scripts, so this guard would pass vacuously"
    )
    unstyled = {
        source: sorted(classes - served) for source, classes in applied.items() if classes - served
    }
    listing = "".join(f"\n  {source}: {' '.join(names)}" for source, names in unstyled.items())
    assert unstyled == {}, (
        "These classes have no rule in any stylesheet base.html links, so they do nothing "
        f"in the browser:{listing}\n"
        "For Tailwind utilities, rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:css`, then commit "
        "static/dist/style.css. For a hand-written class, define it in static/style.css."
    )
