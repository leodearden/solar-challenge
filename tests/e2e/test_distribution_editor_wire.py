# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end tests of the wire both fleet pages post for a component (E5): the grammar's own spec, as #page-limits starts it.

The fleet page's run (aborted, so no job reaches the live server's JobManager) and the
builder's Validate both post every card as write_distribution_spec of its component's start
spec of the type chosen, or its Fixed Value's number. Each type any card offers is chosen in
every card that offers it, and both pages are held to that one expected value, so the two
pages post the same spec. A blanked input posts null: Normal's Max is then left out of the
clamp, and a battery pool's value is then a home without a battery.
"""

from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
from playwright.sync_api import Locator, Page, expect

from solar_challenge.fleet_distribution import DISTRIBUTION_TYPES, DistributionType
from solar_challenge.web.fleet_components import SCALAR_FORM, ComponentLimits, page_limits
from tests._fleet_form import start_spec, start_wire
from tests.e2e._scenario_builder_page import open_builder

_COMPONENTS = page_limits().components
_PV = _COMPONENTS["pv"]
_BATTERY = _COMPONENTS["battery"]


_NORMAL = DISTRIBUTION_TYPES["normal"]
_NORMAL_MAX_TITLE = next(parameter.title for parameter in _NORMAL.parameters if parameter.key == "max")


class _FleetPageEditor(NamedTuple):
    """One page's distribution editors: how to open the page, find a card's control by its caption, and read the body the page posts."""

    open: Callable[[Page, str], None]
    control: Callable[[Page, ComponentLimits, str, str], Locator]
    posted: Callable[[Page], dict[str, Any]]


def _open_fleet_page(page: Page, live_server: str) -> None:
    page.route("**/api/simulate/fleet-from-distribution", lambda route: route.abort())
    page.goto(live_server + "/simulate/fleet")


def _fleet_page_control(page: Page, component: ComponentLimits, role: str, caption: str) -> Locator:
    return page.get_by_role(role, name=f"{component.subject} {caption}", exact=True)


def _posted_by_fleet_run(page: Page) -> dict[str, Any]:
    with page.expect_request("**/api/simulate/fleet-from-distribution") as submission:
        page.get_by_role("button", name="Run Fleet Simulation").click()
    body: dict[str, Any] = submission.value.post_data_json
    return body


def _open_builder_fleet_section(page: Page, live_server: str) -> None:
    open_builder(page, live_server)
    page.get_by_role("button", name="Fleet Distribution", exact=True, expanded=False).click()
    expect(page.get_by_role("group", name=_PV.heading, exact=True).get_by_role("combobox")).to_be_visible()


def _builder_control(page: Page, component: ComponentLimits, role: str, caption: str) -> Locator:
    return page.get_by_role("group", name=component.heading, exact=True).get_by_role(role, name=caption, exact=True)


def _posted_by_builder_validate(page: Page) -> dict[str, Any]:
    with page.expect_request("**/api/scenarios/validate") as validated:
        page.get_by_role("button", name="Validate", exact=True).click()
    body: dict[str, Any] = validated.value.post_data_json
    return body


_FLEET_PAGE = _FleetPageEditor(_open_fleet_page, _fleet_page_control, _posted_by_fleet_run)
_BUILDER = _FleetPageEditor(_open_builder_fleet_section, _builder_control, _posted_by_builder_validate)
_PAGES = [pytest.param(_FLEET_PAGE, id="fleet"), pytest.param(_BUILDER, id="builder")]


def _choose(page: Page, editor: _FleetPageEditor, component: ComponentLimits, title: str) -> None:
    editor.control(page, component, "combobox", "Distribution Type").select_option(label=title)


def _cards_offering(editor_type: DistributionType) -> list[ComponentLimits]:
    """The components whose card offers *editor_type*: every one for Fixed Value, else those whose editor types hold it."""
    return [
        component
        for component in _COMPONENTS.values()
        if editor_type.is_scalar_form or editor_type in component.editor_types
    ]


#: Every type some card offers: Fixed Value, then the DISTRIBUTION_TYPES records some card's editor types hold, in table order.
_OFFERED_TYPES = [
    SCALAR_FORM,
    *(each for each in DISTRIBUTION_TYPES.values() if not each.is_scalar_form and _cards_offering(each)),
]


@pytest.mark.parametrize("editor_type", [pytest.param(each, id=each.name) for each in _OFFERED_TYPES])
@pytest.mark.parametrize("editor", _PAGES)
def test_choosing_a_type_in_every_card_that_offers_it_posts_each_cards_start_wire_of_it(
    page: Page, live_server: str, editor: _FleetPageEditor, editor_type: DistributionType
) -> None:
    """Choosing *editor_type* in each card that offers it posts each such card's field as start_wire of its component and that type."""
    offering = _cards_offering(editor_type)
    editor.open(page, live_server)
    for component in offering:
        _choose(page, editor, component, editor_type.title)

    posted = editor.posted(page)

    assert {component.key: posted[component.key] for component in offering} == {
        component.key: {component.grammar_key: start_wire(component, editor_type)} for component in offering
    }


@pytest.mark.parametrize("editor", _PAGES)
def test_blanking_normals_max_posts_max_null(page: Page, live_server: str, editor: _FleetPageEditor) -> None:
    """A blanked Max (clamp) posts max null, which the grammar reads as no upper clamp."""
    editor.open(page, live_server)
    _choose(page, editor, _PV, _NORMAL.title)
    editor.control(page, _PV, "spinbutton", _NORMAL_MAX_TITLE).fill("")

    assert editor.posted(page)["pv"] == {"capacity_kw": {**start_spec(_PV, "normal"), "max": None}}


@pytest.mark.parametrize("editor", _PAGES)
def test_blanking_a_battery_pool_value_posts_null(page: Page, live_server: str, editor: _FleetPageEditor) -> None:
    """The battery card starts at its shuffled pool, and a blanked Value 1 posts that value null: the homes it counts have no battery."""
    editor.open(page, live_server)
    expect(editor.control(page, _BATTERY, "combobox", "Distribution Type")).to_have_value(_BATTERY.start.shown)
    editor.control(page, _BATTERY, "spinbutton", "Value 1").fill("")

    pool = start_spec(_BATTERY, "shuffled_pool")
    assert editor.posted(page)["battery"] == {
        "capacity_kwh": {**pool, "values": [None, *pool["values"][1:]]}
    }
