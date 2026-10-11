# SPDX-License-Identifier: AGPL-3.0-or-later
"""FLEET_COMPONENTS is the one definition of the fleet components the dashboard distributes over a fleet's homes: PV, battery and load.

Both fleet pages, simulate/fleet.html and scenarios/builder.html, render each one's
distribution editor from it. The scenario builder's script, static/js/scenario-builder.js,
receives the builder's part of it through scenarios.py, and builder_form.py reads the
builder's form fields and each fixed value's bounds from it. The single-home page,
simulate/home.html, bounds and steps its annual consumption input with the load
component's fixed_range and step, and simulation_params.parse_home_config refuses a
home's consumption outside that range.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class EditorDistribution:
    """A distribution as the distribution editor holds it at Fixed Value: the fixed value, and the parameters and rows each other type starts at.

    Attributes:
        values: Weighted Discrete's (value, weight) rows.
        entries: Shuffled Pool's (value, count) rows.
    """

    fixed: float
    mean: float
    std: float
    min: float
    max: float
    values: tuple[tuple[float, float], ...]
    entries: tuple[tuple[float, int], ...]

    def editor_state(self) -> dict[str, Any]:
        """The distribution editor's dist object holding this distribution, which type '' shows at Fixed Value."""
        return {
            "type": "",
            "fixed": self.fixed,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "values": [{"value": value, "weight": weight} for value, weight in self.values],
            "entries": [{"value": value, "count": count} for value, count in self.entries],
        }


@dataclass(frozen=True)
class FleetComponent:
    """A fleet component: the names the form and the scenario grammar give it, and what its distribution editor shows.

    Attributes:
        key: Its fleet_distribution block, and the prefix of the builder form's fields for it.
        grammar_key: Its spec's key in that block.
        fixed_field: The builder form field carrying a fixed value.
        subject: What its values measure, e.g. 'PV Capacity': the fleet page's card heading,
            and the words that start each accessible name in that card's distribution editor.
        unit: The unit of its values, e.g. 'kW', which heading appends to subject in parentheses.
        step: The step of every value input but a weight or count.
        fixed_range: The (min, max) of a fixed value, ends included.
        new_row_value: The value an added row starts at.
        builder_default: The distribution the builder's card starts at.

    Raises:
        ValueError: for a fixed_range that does not run from a lower to a higher bound, or
            a builder_default whose fixed value lies outside it.
    """

    key: str
    grammar_key: str
    fixed_field: str
    subject: str
    unit: str
    step: float
    fixed_range: tuple[float, float]
    new_row_value: float
    builder_default: EditorDistribution

    def __post_init__(self) -> None:
        low, high = self.fixed_range
        if not low < high:
            raise ValueError(
                f"fixed_range of fleet component {self.key!r} must be (low, high) with low < high, "
                f"got {self.fixed_range!r}"
            )
        if not self.admits_fixed_value(self.builder_default.fixed):
            raise ValueError(
                f"builder_default.fixed of fleet component {self.key!r} must lie within its "
                f"fixed_range {self.fixed_range!r}, got {self.builder_default.fixed!r}"
            )

    @property
    def heading(self) -> str:
        """Its subject and unit, e.g. 'PV Capacity (kW)'."""
        return f"{self.subject} ({self.unit})"

    def admits_fixed_value(self, value: float) -> bool:
        """Whether *value* lies within fixed_range, either end included."""
        low, high = self.fixed_range
        return low <= value <= high


FLEET_COMPONENTS: Mapping[str, FleetComponent] = MappingProxyType({
    component.key: component
    for component in (
        FleetComponent(
            key="pv",
            grammar_key="capacity_kw",
            fixed_field="pv_capacity_kw",
            subject="PV Capacity",
            unit="kW",
            step=0.1,
            fixed_range=(0.5, 20),
            new_row_value=4.0,
            builder_default=EditorDistribution(
                fixed=4.0,
                mean=4.0,
                std=1.0,
                min=2.0,
                max=8.0,
                values=((3.0, 20), (4.0, 40), (5.0, 30)),
                entries=((3.0, 20), (4.0, 40), (5.0, 30), (6.0, 10)),
            ),
        ),
        FleetComponent(
            key="battery",
            grammar_key="capacity_kwh",
            fixed_field="battery_capacity_kwh",
            subject="Battery Capacity",
            unit="kWh",
            step=0.1,
            fixed_range=(0, 100),
            new_row_value=5.0,
            builder_default=EditorDistribution(
                fixed=5.0,
                mean=5.0,
                std=2.0,
                min=0,
                max=13.5,
                values=((0, 40), (5.0, 40), (10.0, 20)),
                entries=((0, 40), (5.0, 40), (10.0, 20)),
            ),
        ),
        FleetComponent(
            key="load",
            grammar_key="annual_consumption_kwh",
            fixed_field="annual_consumption_kwh",
            subject="Annual Consumption",
            unit="kWh",
            step=100,
            fixed_range=(500, 20000),
            new_row_value=3500,
            builder_default=EditorDistribution(
                fixed=3500,
                mean=3400,
                std=800,
                min=2000,
                max=5000,
                values=((2900, 30), (3500, 40), (4500, 30)),
                entries=((2900, 30), (3500, 40), (4500, 30)),
            ),
        ),
    )
})
