# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that static/style.css, the hand-written stylesheet base.html
serves as-is after the compiled dist/style.css, defines nothing the dashboard does
not use, and no @keyframes another served stylesheet already defines.

Tailwind compiles dist/style.css from the classes the dashboard applies, but nothing
prunes the hand-written stylesheet (task 221 found .spinner, a second @keyframes spin
and 16 unread --color-* variables). test_web_compiled_css.py guards the other
direction.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import (
    applied_classes_in_script,
    applied_classes_in_template,
    custom_property_references,
    declared_custom_properties,
    keyframes_names,
    selector_classes,
)
from tests._dashboard_sources import (
    HAND_WRITTEN_STYLESHEET_KEY,
    dashboard_script_sources,
    dashboard_template_sources,
    served_stylesheet_sources,
)


def _hand_written_source(served: dict[str, str]) -> str:
    assert HAND_WRITTEN_STYLESHEET_KEY in served, (
        f"base.html no longer links {HAND_WRITTEN_STYLESHEET_KEY}, so none of its rules apply: "
        "delete the file or link it again"
    )
    return served[HAND_WRITTEN_STYLESHEET_KEY]


def test_every_class_the_hand_written_stylesheet_styles_is_applied_by_the_dashboard() -> None:
    applied = set().union(
        *map(applied_classes_in_template, dashboard_template_sources().values()),
        *map(applied_classes_in_script, dashboard_script_sources().values()),
    )
    unapplied = selector_classes(_hand_written_source(served_stylesheet_sources())) - applied

    assert unapplied == set(), (
        f"{HAND_WRITTEN_STYLESHEET_KEY} styles classes that no dashboard template or script "
        f"applies: {' '.join(sorted(unapplied))}\n"
        "Delete their rules. If the dashboard does apply one, through a channel "
        "tests/_css_classes.py does not read (its docstring lists the known gaps), extend that "
        "reader and pin the new channel in tests/unit/test_css_classes_helper.py instead."
    )


def test_every_custom_property_the_hand_written_stylesheet_declares_is_read() -> None:
    served = served_stylesheet_sources()
    sources = [
        *served.values(),
        *dashboard_template_sources().values(),
        *dashboard_script_sources().values(),
    ]
    read = set().union(*map(custom_property_references, sources))
    unread = declared_custom_properties(_hand_written_source(served)) - read

    assert unread == set(), (
        f"{HAND_WRITTEN_STYLESHEET_KEY} declares custom properties that no var() in a served "
        f"stylesheet, template or script reads: {' '.join(sorted(unread))}\n"
        "Delete every declaration of them. If the dashboard does read one, through a channel "
        "other than var() (a script's getPropertyValue(), say), extend custom_property_references "
        "in tests/_css_classes.py and pin the new channel in tests/unit/test_css_classes_helper.py "
        "instead."
    )


def test_the_hand_written_stylesheet_redefines_no_keyframes_another_served_stylesheet_defines() -> None:
    served = served_stylesheet_sources()
    others = {
        name: keyframes_names(source)
        for name, source in served.items()
        if name != HAND_WRITTEN_STYLESHEET_KEY
    }
    definers = {
        keyframes: [name for name, defined in others.items() if keyframes in defined]
        for keyframes in sorted(keyframes_names(_hand_written_source(served)))
    }
    redefined = {keyframes: names for keyframes, names in definers.items() if names}

    assert redefined == {}, (
        f"{HAND_WRITTEN_STYLESHEET_KEY} redefines @keyframes that another stylesheet base.html "
        f"links also defines: {redefined}\n"
        "Same-named @keyframes replace one another in link order, so the copy linked last "
        "silently overrides the other. Delete the hand-written copy."
    )
