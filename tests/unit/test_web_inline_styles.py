# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that no inline style in a dashboard template sets a property
that a class on the same element declares in a stylesheet base.html links.

An inline declaration beats every stylesheet declaration without !important, so the
class's declaration of that property is dead on the element, and the property has two
sources of truth. Task 232 found .chart-container's width and min-height overridden on
every chart the chart_container macro draws. tests/_css_classes.py lists what counts as
a declaration and the known gaps, each of which makes this guard miss an override.
"""

from collections.abc import Iterable

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import (
    InlineStyledElement,
    declared_properties_by_class,
    inline_styled_elements,
)
from tests._dashboard_sources import dashboard_template_sources, served_stylesheet_sources


def _declared_properties(stylesheets: Iterable[str]) -> dict[str, set[str]]:
    """The properties each class declares across *stylesheets*, merged per class."""
    declared: dict[str, set[str]] = {}
    for stylesheet in stylesheets:
        for class_name, properties in declared_properties_by_class(stylesheet).items():
            declared.setdefault(class_name, set()).update(properties)
    return declared


def _overridden_declarations(
    elements: Iterable[InlineStyledElement], declared: dict[str, set[str]]
) -> list[str]:
    """``<class> (<properties>)`` for each class of an element in *elements* that declares
    properties the element's inline style also sets."""
    return sorted(
        f"{class_name} ({' '.join(sorted(overridden))})"
        for element in elements
        for class_name in element.classes
        if (overridden := element.inline_properties & declared.get(class_name, set()))
    )


def test_no_inline_style_sets_a_property_a_class_on_its_element_declares() -> None:
    stylesheets = served_stylesheet_sources()
    templates = dashboard_template_sources()
    declared = _declared_properties(stylesheets.values())
    elements = {path: inline_styled_elements(source) for path, source in templates.items()}

    assert declared, (
        f"read no class rule from the {len(stylesheets)} stylesheets base.html links, "
        "so this guard would pass vacuously"
    )
    assert any(elements.values()), (
        f"read no inline-styled element from the {len(templates)} dashboard templates, "
        "so this guard would pass vacuously"
    )
    overridden = {
        path: entries
        for path, styled in elements.items()
        if (entries := _overridden_declarations(styled, declared))
    }
    listing = "".join(
        f"\n  {path}: {entry}" for path, entries in overridden.items() for entry in entries
    )
    assert overridden == {}, (
        "These inline styles set a property that a class on the same element declares, so "
        f"the class's declaration of it is dead on that element:{listing}\n"
        "Keep one source per property: drop the property from the style attribute, or drop "
        "the class from the element (and its rule from static/style.css if nothing else "
        "applies it)."
    )
