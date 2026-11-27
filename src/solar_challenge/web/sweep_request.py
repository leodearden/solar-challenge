# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web sweep's parameters and its request reader.

Each parameter is the knob that sets it on a home, the fleet component whose value it is,
and the range the sweep page starts at. read_sweep_request reads a sweep request's body
into a SweepRequest, whose points lie within its parameter's component range. The module
imports no Flask of its own and answers no request.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from solar_challenge.fleet_distribution import SweepMode, SweepSpec
from solar_challenge.number_fields import Interval, as_finite_float, as_whole_number
from solar_challenge.scenario_knobs import Knob, KnobTarget, knob_named
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits
from solar_challenge.web.request_boundary import read_optional_string, read_string
from solar_challenge.web.text_options import read_one_of

#: The most steps a sweep may have, which the sweep page's Steps input offers.
SWEEP_MAX_STEPS = 50
_STEPS = Interval(2, SWEEP_MAX_STEPS)
_DEFAULT_STEPS = 5
_POINT_DECIMALS = 3


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


@dataclass(frozen=True)
class SweepRequest:
    """A sweep the web runs: the parameter it varies and the spec of its points.

    Raises:
        ConfigurationError: For a spec whose min or max lies outside the parameter's
            value_range, naming the end, the knob, the range and the value.
    """

    parameter: SweepParameter
    spec: SweepSpec

    def __post_init__(self) -> None:
        for end, value in (("min", self.spec.min), ("max", self.spec.max)):
            as_finite_float(value, f"{end} of a {self.parameter.knob.name} sweep", self.parameter.value_range)

    def values(self) -> tuple[float, ...]:
        """The sweep's points, each rounded to _POINT_DECIMALS decimals: the values its preview shows, its jobs run and its chart plots."""
        return tuple(round(value, _POINT_DECIMALS) for value in self.spec.get_values())


def read_sweep_request(body: Mapping[str, object]) -> SweepRequest:
    """The sweep *body*, a request's JSON object, asks for; each field it omits takes its default.

    The fields: parameter, a key of SWEEP_PARAMETERS (default its first); min and max,
    finite numbers (default the parameter's default_min and default_max); steps, a whole
    number from 2 to SWEEP_MAX_STEPS (default _DEFAULT_STEPS); and mode, a SweepMode's
    value, null reading as omitted (default SweepSpec's).

    Raises:
        ConfigurationError: For a field it cannot read, naming the field, and from SweepSpec
            or SweepRequest for points they refuse.
    """
    parameter = _read_parameter(body.get("parameter", next(iter(SWEEP_PARAMETERS))))
    low = as_finite_float(body.get("min", parameter.default_min), "min")
    high = as_finite_float(body.get("max", parameter.default_max), "max")
    steps = as_whole_number(body.get("steps", _DEFAULT_STEPS), "steps", within=_STEPS)
    mode = read_optional_string(body.get("mode"), "mode")
    spec = SweepSpec(low, high, steps) if mode is None else SweepSpec(low, high, steps, SweepMode.parse(mode))
    return SweepRequest(parameter, spec)


def _read_parameter(value: object) -> SweepParameter:
    """The SWEEP_PARAMETERS row whose key *value*, a request's parameter, names."""
    name = read_one_of(read_string(value, "parameter"), tuple(SWEEP_PARAMETERS), "parameter")
    return SWEEP_PARAMETERS[name]
