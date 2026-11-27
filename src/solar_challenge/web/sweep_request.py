# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web sweep's parameters: each the knob that sets it on a home, the fleet component whose value it is, and the range the sweep page starts at; it imports no Flask."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from solar_challenge.number_fields import Interval
from solar_challenge.scenario_knobs import Knob, KnobTarget, knob_named
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits


@dataclass(frozen=True)
class SweepParameter:
    """A parameter the web sweep varies.

    Attributes:
        knob: The knob that sets the parameter on each home.
        component: The fleet component whose value the knob sets.
        default_min: The first point of the range the sweep page starts at.
        default_max: The last point of that range.

    Raises:
        ValueError: For a knob whose target is not KnobTarget.HOMES, which would simulate the
            same home at every point; a default_min or default_max outside the component's
            value_range; or a default_min not below default_max; naming the field and the value.
    """

    knob: Knob
    component: ComponentLimits
    default_min: float
    default_max: float

    def __post_init__(self) -> None:
        if self.knob.target is not KnobTarget.HOMES:
            raise ValueError(
                f"knob of a sweep parameter must set {KnobTarget.HOMES.value}, "
                f"got {self.knob.name!r}, which sets {self.knob.target.value}"
            )
        for field, value in (("default_min", self.default_min), ("default_max", self.default_max)):
            if not self.value_range.admits(value):
                raise ValueError(f"{field} of the {self.knob.name} sweep must be {self.value_range}, got {value!r}")
        if not self.default_min < self.default_max:
            raise ValueError(
                f"default_min of the {self.knob.name} sweep must be below its default_max, "
                f"{self.default_max!r}, got {self.default_min!r}"
            )

    @property
    def label(self) -> str:
        """The parameter as the sweep page names it: its component's heading, e.g. 'PV Capacity (kW)'."""
        return self.component.heading

    @property
    def value_range(self) -> Interval:
        """The values a point may take: its component's value_range."""
        return self.component.value_range


SWEEP_PARAMETERS: Mapping[str, SweepParameter] = MappingProxyType({
    parameter.knob.name: parameter
    for parameter in (
        SweepParameter(knob_named("pv_capacity_kw"), FLEET_COMPONENTS["pv"], 2.0, 8.0),
        SweepParameter(knob_named("battery_capacity_kwh"), FLEET_COMPONENTS["battery"], 0.0, 13.5),
        SweepParameter(knob_named("annual_consumption_kwh"), FLEET_COMPONENTS["load"], 2000.0, 5000.0),
    )
})
"""The parameters the web sweep varies, keyed by knob name, in the order the sweep page offers them."""
