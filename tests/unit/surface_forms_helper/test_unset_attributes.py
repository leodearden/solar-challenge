# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's unset_attributes, one per test."""

import collections
import pathlib
import re
from dataclasses import dataclass, field
from typing import ClassVar, NamedTuple

import pytest

from tests._surface_forms import member_forms, unset_attributes
from tests.unit.surface_forms_helper._fixtures import REFUSED_ROUTINE_AND_PARTIAL_MEMBERS


def test_a_declared_attribute_member_forms_lists_that_the_source_never_sets_is_unset() -> None:
    class Meter:
        UNITS: ClassVar[str]
        site: pathlib.Path
        reading: float
        _level: float

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    @dataclass(frozen=True)
    class Reading:
        kwh: float

    assert unset_attributes(Meter) == {"reading"}
    assert unset_attributes(Reading) == set()


def test_an_attribute_the_class_body_annotates_and_lists_in_its_slots_is_unset_where_its_own_initialisers_never_set_it() -> None:
    class Meter:
        __slots__ = ("site", "reading")
        site: pathlib.Path
        reading: float

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    assert not hasattr(Meter(pathlib.Path("roof")), "reading")
    assert unset_attributes(Meter) == {"reading"}


def test_a_declared_attribute_only_a_method_other_than_init_or_post_init_sets_is_unset() -> None:
    class Meter:
        reading: float

        def reset(self) -> None:
            self.reading = 0.0

    assert not hasattr(Meter(), "reading")
    assert unset_attributes(Meter) == {"reading"}


def test_a_name_the_class_body_only_annotates_as_a_class_variable_in_a_string_is_never_unset() -> None:
    class Meter:
        UNITS: "ClassVar[str]"
        reading: float

    assert unset_attributes(Meter) == {"reading"}


def test_a_dataclass_field_with_a_default_or_a_default_factory_is_never_unset() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        derived: float = field(init=False, default=0.0)
        history: list[float] = field(init=False, default_factory=list)
        label: str = field(init=False)
        note: str = field(init=False)

        def __post_init__(self) -> None:
            object.__setattr__(self, "label", f"{self.kwh} kWh")

    assert unset_attributes(Reading) == {"note"}


def test_a_default_factory_field_counts_as_supplied_even_when_a_hand_written_init_skips_it() -> None:
    @dataclass(init=False)
    class InitFalse:
        root: str
        history: list[float] = field(default_factory=list)

        def __init__(self, root: str) -> None:
            self.root = root

    @dataclass
    class BodyInit:
        root: str
        history: list[float] = field(init=False, default_factory=list)

        def __init__(self, root: str) -> None:
            self.root = root

    for cls in (InitFalse, BodyInit):
        assert member_forms(cls) == {"history": "attribute list[float]"}
        assert not hasattr(cls("data"), "history")
        assert unset_attributes(cls) == set()


def test_a_named_tuple_field_its_instances_read_from_the_tuple_is_never_unset() -> None:
    class Point(NamedTuple):
        x: int
        y: int

    class OnX(Point):
        y: int

        def __new__(cls, x: int) -> "OnX":
            return super().__new__(cls, x, 0)

    Plain = collections.namedtuple("Plain", ["kwh", "site"])

    class OnKwh(Plain):
        site: str

        def __new__(cls, kwh: float) -> "OnKwh":
            return super().__new__(cls, kwh, "roof")

    class Withheld(Point):
        @property
        def y(self) -> int:
            raise AttributeError("y")

    class Redeclared(Withheld):
        y: int

    assert (OnX(1).y, OnKwh(1.0).site) == (0, "roof")
    assert not hasattr(Redeclared(1, 2), "y")
    assert member_forms(OnX) == {"y": "attribute int"}
    assert member_forms(OnKwh) == {"site": "attribute str"}
    assert member_forms(Redeclared) == {"y": "attribute int"}
    assert unset_attributes(OnX) == set()
    assert unset_attributes(OnKwh) == set()
    assert unset_attributes(Redeclared) == {"y"}


def test_an_attribute_a_tuple_whose_metaclass_alone_provides_fields_declares_is_unset_where_its_initialisers_never_set_it() -> None:
    class FieldsMeta(type):
        _fields = ("x",)

    class Fielded(tuple, metaclass=FieldsMeta):
        x: int

    assert not hasattr(Fielded((1,)), "x")
    assert unset_attributes(Fielded) == {"x"}


def test_a_dataclass_field_a_data_descriptor_hides_from_instances_is_unset_where_a_class_body_declares_it_again_and_no_default_or_own_initialiser_supplies_it() -> None:
    @dataclass
    class Point:
        x: int

    class Doubled(Point):
        @property
        def x(self) -> int:
            return self._x * 2

        @x.setter
        def x(self, value: int) -> None:
            self._x = value

    class Retyped(Doubled):
        x: int

    assert Retyped(1).x == 2
    assert member_forms(Retyped) == {"x": "attribute int"}
    assert unset_attributes(Doubled) == set()
    assert unset_attributes(Retyped) == {"x"}


def test_a_data_descriptor_a_class_body_binds_under_a_dataclass_field_name_it_annotates_declares_no_attribute_so_it_is_never_unset() -> None:
    @dataclass
    class Point:
        x: int

    class Fixed(Point):
        x: int

        @property
        def x(self) -> int:
            return 7

        @x.setter
        def x(self, value: int) -> None: ...

    assert Fixed(1).x == 7
    assert unset_attributes(Fixed) == set()


def test_a_reviewed_write_under_a_computed_name_sets_no_declared_attribute() -> None:
    class Meter:
        reading: float

        def __init__(self, name: str) -> None:
            setattr(self, name, 0.0)

    assert unset_attributes(Meter, reviewed={"setattr(self, name, 0.0)"}) == {"reading"}


@pytest.mark.parametrize(("routine", "kind"), REFUSED_ROUTINE_AND_PARTIAL_MEMBERS)
def test_a_class_with_a_member_member_forms_refuses_raises_the_type_error_member_forms_raises_for_it(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        unset_attributes(Meter)
