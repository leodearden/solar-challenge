# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of solar_challenge.web.fleet_components, the one definition of the fleet components."""

import math
from dataclasses import replace

import pytest

pytest.importorskip("flask")

from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    EditorDistribution,
    FleetComponent,
)


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
