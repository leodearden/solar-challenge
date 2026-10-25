# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of solar_challenge.web.fleet_components, the one definition of the fleet components, and of the two fleet pages that render each component's card from it."""

import math
from collections.abc import Mapping
from dataclasses import replace

import pytest

pytest.importorskip("flask")

from flask.testing import FlaskClient

from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    EditorDistribution,
    FleetComponent,
)
from tests._css_classes import names_palette
from tests._html_page import counts_of, element_attributes, headings


def _editor_scopes(page: str) -> list[str | None]:
    """The x-data of each distribution editor of *page*, in page order."""
    return [
        attributes["x-data"]
        for attributes in element_attributes(page, "div")
        if (attributes.get("x-data") or "").startswith("distributionEditor(")
    ]


def _number_inputs(page: str, model: str) -> list[Mapping[str, str | None]]:
    """The attributes of each input of *page* whose x-model.number is *model*, in page order."""
    return [
        attributes
        for attributes in element_attributes(page, "input")
        if attributes.get("x-model.number") == model
    ]


class TestFleetComponents:
    """The fleet components FLEET_COMPONENTS defines, and the invariants each one keeps."""

    def test_the_components_are_pv_battery_and_load_each_listed_under_its_own_key(self) -> None:
        """The keys are the builder form's field prefixes and the fleet_distribution blocks, and their order is both pages' card order."""
        assert list(FLEET_COMPONENTS) == ["pv", "battery", "load"]
        assert all(component.key == key for key, component in FLEET_COMPONENTS.items())

    @pytest.mark.parametrize(
        "fixed_range",
        [
            pytest.param((20, 0.5), id="reversed"),
            pytest.param((4.0, 4.0), id="empty"),
        ],
    )
    def test_a_fixed_range_that_does_not_run_from_a_lower_to_a_higher_bound_is_refused_naming_the_component_and_the_range(
        self, fixed_range: tuple[float, float]
    ) -> None:
        with pytest.raises(ValueError) as exc_info:
            replace(FLEET_COMPONENTS["pv"], fixed_range=fixed_range)
        assert str(exc_info.value) == (
            f"fixed_range of fleet component 'pv' must be (low, high) with low < high, got {fixed_range!r}"
        )

    @pytest.mark.parametrize("beyond", ["below", "above"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_builder_default_fixed_value_beyond_the_fixed_range_is_refused_naming_the_component_the_range_and_the_value(
        self, component: FleetComponent, beyond: str
    ) -> None:
        low, high = component.fixed_range
        value = math.nextafter(low, -math.inf) if beyond == "below" else math.nextafter(high, math.inf)
        with pytest.raises(ValueError) as exc_info:
            replace(component, builder_default=replace(component.builder_default, fixed=value))
        assert str(exc_info.value) == (
            f"builder_default.fixed of fleet component {component.key!r} must lie within its fixed_range "
            f"{component.fixed_range!r}, got {value!r}"
        )

    def test_editor_state_is_the_distribution_editors_dist_at_fixed_value(self) -> None:
        """The shape templates/components/distribution-editor.html documents and the builder's script reads."""
        distribution = EditorDistribution(
            fixed=4.0,
            mean=4.0,
            std=1.0,
            min=2.0,
            max=8.0,
            values=((3.0, 20), (5.0, 80)),
            entries=((3.0, 60), (5.0, 40)),
        )
        assert distribution.editor_state() == {
            "type": "",
            "fixed": 4.0,
            "mean": 4.0,
            "std": 1.0,
            "min": 2.0,
            "max": 8.0,
            "values": [{"value": 3.0, "weight": 20}, {"value": 5.0, "weight": 80}],
            "entries": [{"value": 3.0, "count": 60}, {"value": 5.0, "count": 40}],
        }


@pytest.mark.parametrize(
    ("path", "dists"),
    [
        pytest.param("/scenarios/builder", ("dists.pv", "dists.battery", "dists.load"), id="builder"),
        pytest.param("/simulate/fleet", ("pvDist", "batteryDist", "loadDist"), id="fleet"),
    ],
)
class TestPagesRenderEachComponentFromTheTable:
    """Each fleet page renders one distribution editor per component, in FLEET_COMPONENTS order, as the table defines it.

    *dists* are the page's Alpine expressions of its cards' distributions, in card order.
    """

    def test_each_editor_edits_its_cards_distribution_and_starts_an_added_row_at_its_components_new_row_value(
        self, client: FlaskClient, path: str, dists: tuple[str, ...]
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert _editor_scopes(page) == [
            f"distributionEditor(() => {dist}, {component.new_row_value})"
            for component, dist in zip(FLEET_COMPONENTS.values(), dists, strict=True)
        ]

    def test_each_fixed_value_is_bounded_and_stepped_as_its_component(
        self, client: FlaskClient, path: str, dists: tuple[str, ...]
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert [
            (attributes.get("step"), attributes.get("min"), attributes.get("max"))
            for attributes in _number_inputs(page, "dist.fixed")
        ] == [
            (str(component.step), str(component.fixed_range[0]), str(component.fixed_range[1]))
            for component in FLEET_COMPONENTS.values()
        ]

    def test_each_row_value_steps_as_its_component(
        self, client: FlaskClient, path: str, dists: tuple[str, ...]
    ) -> None:
        """Each editor has two row templates, Weighted Discrete's and Shuffled Pool's, each with one Value input."""
        page = client.get(path).get_data(as_text=True)
        assert [attributes.get("step") for attributes in _number_inputs(page, "row.value")] == [
            str(component.step) for component in FLEET_COMPONENTS.values() for _ in range(2)
        ]


class TestPagesHeadEachCardFromTheTable:
    """Each fleet page heads each component's card with the words FLEET_COMPONENTS gives it."""

    def test_the_builder_heads_each_card_with_its_components_heading(self, client: FlaskClient) -> None:
        page = client.get("/scenarios/builder").get_data(as_text=True)
        card_headings = tuple(component.heading for component in FLEET_COMPONENTS.values())
        assert counts_of(headings(page), card_headings) == dict.fromkeys(card_headings, 1)

    def test_the_fleet_page_heads_each_card_with_its_components_subject(self, client: FlaskClient) -> None:
        page = client.get("/simulate/fleet").get_data(as_text=True)
        subjects = tuple(component.subject for component in FLEET_COMPONENTS.values())
        assert counts_of(headings(page), subjects) == dict.fromkeys(subjects, 1)


class TestTheFleetPageColoursEachCardByItsComponent:
    """The fleet page draws each component's card in the role palette the token file's
    tailwind.component group names under that component's key."""

    @pytest.mark.parametrize("key", list(FLEET_COMPONENTS))
    def test_the_fleet_page_draws_each_components_card_in_its_role_palette(
        self, client: FlaskClient, key: str
    ) -> None:
        """The card's header band and its dot are the page's only divs naming component-<key>."""
        page = client.get("/simulate/fleet").get_data(as_text=True)

        role_classes = {
            css_class
            for div in element_attributes(page, "div")
            for css_class in (div.get("class") or "").split()
            if names_palette(css_class, f"component-{key}")
        }

        assert role_classes == {
            f"bg-component-{key}-50",
            f"dark:bg-component-{key}-900/20",
            f"bg-component-{key}-500",
        }
