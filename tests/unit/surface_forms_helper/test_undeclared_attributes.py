# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's undeclared_attributes, one per test.

The annotations below are evaluated, as in the modules they stand in for, so this module
does not import annotations from __future__.
"""

import pathlib
from dataclasses import InitVar, dataclass

import pytest

from tests._surface_forms import undeclared_attributes, unset_attributes


def test_each_assignment_to_a_public_attribute_of_self_sets_it() -> None:
    class Meter:
        def __init__(self, site: pathlib.Path) -> None:
            self.site = site
            self.reading: float = 0.0
            self.low, self.high = 0.0, 1.0

        def add(self, kwh: float) -> None:
            self.total += kwh

    assert undeclared_attributes(Meter) == {"site", "reading", "low", "high", "total"}


def test_object_setattr_on_self_sets_the_attribute_it_names() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

        def __post_init__(self) -> None:
            object.__setattr__(self, "kwh", float(self.kwh))
            object.__setattr__(self, "label", f"{self.kwh} kWh")

    assert undeclared_attributes(Reading) == {"label"}


def test_an_attribute_a_class_body_in_the_mro_declares_or_defines_is_not_undeclared() -> None:
    class Base:
        site: pathlib.Path

    class Meter(Base):
        UNITS = "kWh"
        reading: float

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site
            self.UNITS = "MWh"
            self.reading = 0.0

    assert undeclared_attributes(Meter) == set()


def test_an_attribute_only_a_base_sets_on_self_is_undeclared_in_the_base_not_its_subclass() -> None:
    class Base:
        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    class Meter(Base):
        def reset(self) -> None:
            self.reading = 0.0

    assert undeclared_attributes(Base) == {"site"}
    assert undeclared_attributes(Meter) == {"reading"}


def test_a_private_attribute_set_on_self_is_never_undeclared() -> None:
    class Meter:
        def __init__(self) -> None:
            self._cache: dict[str, float] = {}
            object.__setattr__(self, "_level", 0.0)

    assert undeclared_attributes(Meter) == set()


def test_an_attribute_set_on_self_under_a_dataclass_init_only_variable_name_is_undeclared() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        scale: InitVar[float]
        offset: "InitVar[float]"
        floor: InitVar[float] = 0.0

        def __post_init__(self, scale: float, offset: float, floor: float) -> None:
            object.__setattr__(self, "scale", scale)
            object.__setattr__(self, "offset", offset)
            object.__setattr__(self, "floor", floor)

    @dataclass(frozen=True)
    class Scaled(Reading):
        def __post_init__(self, scale: float, offset: float, floor: float) -> None:
            object.__setattr__(self, "scale", scale)

    reading = Reading(kwh=1.0, scale=2.0, offset=0.5)
    assert vars(reading).keys() >= {"scale", "offset", "floor"}
    assert undeclared_attributes(Reading) == {"scale", "offset", "floor"}
    assert undeclared_attributes(Scaled) == {"scale"}


def test_a_class_body_string_annotation_naming_a_name_its_module_does_not_bind_raises_a_name_error_from_undeclared_attributes_and_unset_attributes() -> None:
    class Base:
        site: "Nowhere"  # noqa: F821

    class Meter(Base):
        def __init__(self) -> None:
            self.reading = 0.0

    with pytest.raises(NameError, match="Nowhere"):
        undeclared_attributes(Meter)
    with pytest.raises(NameError, match="Nowhere"):
        unset_attributes(Base)
