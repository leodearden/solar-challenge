# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's undeclared_attributes, one per test."""

import pathlib
from dataclasses import InitVar, dataclass

import pytest

from tests._surface_forms import undeclared_attributes, unset_attributes


def test_each_assignment_to_a_public_attribute_of_self_sets_it() -> None:
    class Meter:
        def __init__(self, site: pathlib.Path, readings: list[float]) -> None:
            self.site = site
            self.reading: float = 0.0
            self.low, self.high = 0.0, 1.0
            for kwh in readings:
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


def test_setattr_or___setattr___on_the_receiver_with_a_string_constant_sets_the_attribute_it_names() -> None:
    class Meter:
        def __init__(self) -> None:
            setattr(self, "site", "roof")
            object.__setattr__(self, "reading", 0.0)
            self.__setattr__("low", 0.0)
            super().__setattr__("high", 1.0)

    assert vars(Meter()).keys() == {"site", "reading", "low", "high"}
    assert undeclared_attributes(Meter) == {"site", "reading", "low", "high"}


def test_only_the_init_and_post_init_the_class_body_itself_defines_are_read() -> None:
    class Meter:
        def __init__(self) -> None:
            self.ok = 1

        def reset(self) -> None:
            self.reading = 0.0

        @staticmethod
        def build(self: object) -> None:
            self.fromstatic = 1

        class _Helper:
            def __init__(self) -> None:
                self.leaked = 1

    assert undeclared_attributes(Meter) == {"ok"}


def test_the_receiver_is_the_first_parameter_whatever_its_name() -> None:
    class Meter:
        def __init__(this, self: object) -> None:
            this.renamed = 1
            self.elsewhere = 2

    assert undeclared_attributes(Meter) == {"renamed"}


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
        def __init__(self, site: pathlib.Path) -> None:
            super().__init__(site)
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
