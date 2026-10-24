# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's member_forms, one per test."""

import abc
import collections
import enum
import functools
import inspect
import pathlib
import re
import types
from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from typing import ClassVar, NamedTuple, Optional

import pytest

from tests._surface_forms import (
    member_forms,
    named_classes,
    surface_form,
    undeclared_attributes,
    unset_attributes,
)
from tests.unit.surface_forms_helper._fixtures import (
    UNREADABLE_ROUTINES,
    CallableGetter,
    Preset,
    imported_module,
)


def test_a_method_member_is_spelled_by_its_signature_self_included() -> None:
    class Meter:
        def read(self, at: Optional[int] = None) -> float: ...

    assert member_forms(Meter) == {"read": "(self, at: int | None = None) -> float"}


def test_a_classmethod_or_staticmethod_member_is_spelled_by_its_kind_then_its_function() -> None:
    class Meter:
        @classmethod
        def default(cls) -> "Meter": ...

        @staticmethod
        def scale(kwh: float) -> float: ...

    assert member_forms(Meter) == {
        "default": "classmethod (cls) -> Meter",
        "scale": "staticmethod (kwh: float) -> float",
    }


def test_a_property_or_cached_property_member_is_spelled_by_its_kind_then_its_getter() -> None:
    class Meter:
        @property
        def reading(self) -> float: ...

        @functools.cached_property
        def peak(self) -> Optional[float]: ...

    assert member_forms(Meter) == {
        "reading": "property (self) -> float",
        "peak": "cached_property (self) -> float | None",
    }


def test_a_settable_or_deletable_property_member_says_so_in_its_kind() -> None:
    class Meter:
        @property
        def reading(self) -> float: ...

        @reading.setter
        def reading(self, kwh: float) -> None: ...

        @property
        def tariff(self) -> str: ...

        @tariff.deleter
        def tariff(self) -> None: ...

        @property
        def label(self) -> str: ...

        @label.setter
        def label(self, text: str) -> None: ...

        @label.deleter
        def label(self) -> None: ...

    assert member_forms(Meter) == {
        "reading": "property[settable] (self) -> float",
        "tariff": "property[deletable] (self) -> str",
        "label": "property[settable, deletable] (self) -> str",
    }


def test_an_abstract_member_form_begins_with_abstract() -> None:
    class Strategy(abc.ABC):
        @abc.abstractmethod
        def decide(self, demand_kw: float) -> str: ...

        @property
        @abc.abstractmethod
        def name(self) -> str: ...

        @classmethod
        @abc.abstractmethod
        def default(cls) -> "Strategy": ...

        def describe(self) -> str: ...

    assert member_forms(Strategy) == {
        "decide": "abstract (self, demand_kw: float) -> str",
        "name": "abstract property (self) -> str",
        "default": "abstract classmethod (cls) -> Strategy",
        "describe": "(self) -> str",
    }


def test_a_class_constant_member_is_spelled_by_its_type() -> None:
    class Meter:
        UNITS = "kWh"
        SCALE = 1.5
        RATE: ClassVar[float] = 0.15

    assert member_forms(Meter) == {"UNITS": "str", "SCALE": "float", "RATE": "float"}


def test_an_attribute_the_class_body_only_annotates_is_spelled_attribute_then_its_annotation() -> None:
    class Meter:
        site: pathlib.Path
        reading: Optional[float]

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site
            self.reading = None

    assert member_forms(Meter) == {
        "site": "attribute Path",
        "reading": "attribute float | None",
    }


def test_an_attribute_set_on_self_is_a_member_only_once_a_class_body_declares_it() -> None:
    class Undeclared:
        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    class Declared:
        site: pathlib.Path

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    assert member_forms(Undeclared) == {}
    assert member_forms(Declared) == {"site": "attribute Path"}


def test_the_attributes_a_class_body_declares_come_first_in_annotation_order_then_the_other_names_it_defines_in_class_body_order() -> None:
    class Meter:
        UNITS = "kWh"
        site: pathlib.Path

        @property
        def tariff(self) -> str: ...

        reading: float

        def read(self) -> float: ...

        label: str

    assert list(member_forms(Meter)) == ["site", "reading", "label", "UNITS", "tariff", "read"]


def test_a_name_the_class_body_only_annotates_as_a_class_variable_is_not_a_member() -> None:
    class Meter:
        UNITS: ClassVar[str]
        SCALE: ClassVar

    assert member_forms(Meter) == {}


def test_a_name_the_class_body_only_annotates_as_a_class_variable_in_a_string_is_not_a_member() -> None:
    class Meter:
        UNITS: "ClassVar[str]"
        SCALE: "ClassVar"

    assert member_forms(Meter) == {}


def test_a_class_body_string_annotation_naming_a_name_its_module_does_not_bind_raises_a_name_error_naming_it() -> None:
    class Meter:
        site: "Nowhere"  # noqa: F821

    with pytest.raises(NameError, match="Nowhere"):
        member_forms(Meter)


def test_a_class_body_string_annotation_of_a_class_whose_module_another_module_of_the_same_name_has_replaced_in_sys_modules_raises_a_lookup_error(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "class Plain:\n"
        "    share: 'Share'\n",
    )
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "class Plain:\n"
        "    share: 'Share'\n",
    )

    with pytest.raises(LookupError) as raised:
        member_forms(earlier.Plain)

    assert later.__file__ in str(raised.value)


def test_private_and_dunder_names_are_not_members() -> None:
    class Meter:
        _cache: dict[str, float] = {}
        _level: float

        def _read(self) -> float: ...

        def __len__(self) -> int: ...

    assert member_forms(Meter) == {}


def test_a_dataclass_field_its_constructor_does_not_take_is_spelled_attribute_then_its_annotation() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        history: list[float] = field(init=False, default_factory=list)
        label: Optional[str] = field(init=False)

    @dataclass(init=False)
    class Cache:
        root: str
        path: pathlib.Path

        def __init__(self, root: str) -> None:
            self.root = root
            self.path = pathlib.Path(root)

    assert member_forms(Reading) == {
        "history": "attribute list[float]",
        "label": "attribute str | None",
    }
    assert member_forms(Cache) == {"path": "attribute Path"}


def test_a_dataclass_field_with_a_default_is_spelled_and_names_classes_by_its_annotation_not_its_default() -> None:
    @dataclass(frozen=True)
    class Meter:
        UNITS: ClassVar[str] = "kWh"
        preset: Optional[Preset] = field(init=False, default=None)

    assert member_forms(Meter) == {"preset": "attribute Preset | None", "UNITS": "str"}
    assert named_classes(Meter) == {Preset, str}


def test_a_dataclass_field_its_constructor_takes_is_not_a_member_but_a_class_variable_is() -> None:
    @dataclass(frozen=True)
    class Site:
        LAT: ClassVar[float] = 51.45
        site_id: int
        name: str = ""
        tags: list[str] = field(default_factory=list)

    assert member_forms(Site) == {"LAT": "float"}


def test_a_dataclass_init_only_variable_is_neither_a_member_nor_an_unset_attribute() -> None:
    @dataclass(frozen=True)
    class Reading:
        LAT: ClassVar[float] = 51.45
        kwh: float
        scale: InitVar[float]
        offset: "InitVar[float]"
        floor: InitVar[float] = 0.0

        def __post_init__(self, scale: float, offset: float, floor: float) -> None:
            object.__setattr__(self, "kwh", max(self.kwh * scale + offset, floor))

    assert member_forms(Reading) == {"LAT": "float"}
    assert unset_attributes(Reading) == set()


def test_an_undecorated_subclass_of_a_dataclass_has_no_init_only_variable_so_it_declares_what_it_annotates() -> None:
    @dataclass
    class Base:
        x: int

    class Sub(Base):
        y: str

        def __init__(self, x: int, y: str) -> None:
            super().__init__(x)
            self.y = y

    assert vars(Sub(x=1, y="a")).keys() >= {"y"}
    assert member_forms(Sub) == {"y": "attribute str"}
    assert undeclared_attributes(Sub) == set()


def test_a_hand_written_constructor_parameter_does_not_hide_a_member_of_the_same_name() -> None:
    @dataclass(init=False)
    class Meter:
        site: str

        def __init__(self, site: str, reading: float) -> None:
            self.site = site
            self._reading = reading

        @property
        def reading(self) -> float: ...

    assert member_forms(Meter) == {"reading": "property (self) -> float"}


def test_a_class_variable_is_a_member_even_when_a_hand_written_constructor_takes_its_name() -> None:
    @dataclass(init=False)
    class Meter:
        UNITS: ClassVar[str] = "kWh"
        site: str

        def __init__(self, site: str, UNITS: str = "kWh") -> None:
            self.site = site

    assert member_forms(Meter) == {"UNITS": "str"}


def test_a_class_variable_annotated_in_a_string_is_a_member_even_when_a_hand_written_constructor_takes_its_name() -> None:
    @dataclass(init=False)
    class Meter:
        UNITS: "ClassVar[str]" = "kWh"
        site: str

        def __init__(self, site: str, UNITS: str = "kWh") -> None:
            self.site = site

    assert member_forms(Meter) == {"UNITS": "str"}


def test_an_enum_member_is_not_a_class_member_but_an_enum_method_is() -> None:
    class Period(enum.Enum):
        PEAK = "peak"
        OFF_PEAK = "off_peak"

        def label(self) -> str: ...

    assert member_forms(Period) == {"label": "(self) -> str"}


def test_a_named_tuple_field_is_not_a_member_since_its_class_form_pins_it_but_a_constant_or_method_its_body_defines_is() -> None:
    class Reading(NamedTuple):
        kwh: float
        site: Optional[str] = None
        UNITS = "kWh"

        def doubled(self) -> float: ...

    Plain = collections.namedtuple("Plain", ["kwh", "site"])

    assert surface_form(Reading) == "(kwh: float, site: str | None = None)"
    assert member_forms(Reading) == {"UNITS": "str", "doubled": "(self) -> float"}
    assert surface_form(Plain) == "(kwh, site)"
    assert member_forms(Plain) == {}


def test_a_named_tuple_field_a_subclass_body_annotates_again_is_a_member_only_if_the_subclass_constructor_does_not_take_it() -> None:
    class Point(NamedTuple):
        x: int
        y: int

    class Retyped(Point):
        y: int

    class OnX(Point):
        y: int

        def __new__(cls, x: int) -> "OnX":
            return super().__new__(cls, x, 0)

    assert member_forms(Retyped) == {}
    assert member_forms(OnX) == {"y": "attribute int"}


def test_an_inherited_member_is_a_member_of_the_class_that_defines_it() -> None:
    class Base:
        def read(self) -> float: ...

    class Child(Base):
        def reset(self) -> None: ...

    assert member_forms(Base) == {"read": "(self) -> float"}
    assert member_forms(Child) == {"reset": "(self) -> None"}


def test_a_callable_descriptor_member_is_spelled_by_the_signature_inspect_reads_through_the_function_it_wraps_or_the_signature_it_carries() -> None:
    class Memoized:
        def __init__(self, function: Callable[..., object]) -> None:
            functools.update_wrapper(self, function)
            self.function = function

        def __get__(self, instance: object, owner: type) -> object:
            return types.MethodType(self, instance)

        def __call__(self, *args: object) -> object:
            return self.function(*args)

    class Signed:
        __signature__ = inspect.Signature(
            [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
        )

        def __get__(self, instance: object, owner: type) -> "Signed":
            return self

        def __call__(self, rate: int) -> None: ...

    class Meter:
        @Memoized
        def read(self, at: int) -> float: ...

        signed = Signed()

    assert member_forms(Meter) == {"read": "(self, at: int) -> float", "signed": "(rate: int)"}


def test_a_function_member_that_wraps_a_callable_descriptor_but_carries_a_signature_of_none_is_spelled_by_its_own_signature() -> None:
    class Meter:
        def half(self, rate: int) -> None: ...

        half.__wrapped__ = CallableGetter()
        half.__signature__ = None

    assert member_forms(Meter) == {"half": "(self, rate: int) -> None"}


@pytest.mark.parametrize(("routine", "kind"), UNREADABLE_ROUTINES)
def test_a_member_that_is_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_the_class_the_member_and_its_kind(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        member_forms(Meter)


def test_a_partial_member_raises_a_type_error_naming_the_class_the_member_and_that_only_python_3_14_binds_it_to_the_instance() -> None:
    def settle(self: object, share: float, rate: int) -> None: ...

    class Meter:
        half = functools.partial(settle, rate=1)

    with pytest.raises(
        TypeError, match=r"\.Meter\.half\b.*\bfunctools\.partial\b.*\b3\.14\b.*\bmethod\b"
    ):
        member_forms(Meter)


def test_a_partial_member_that_wraps_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_that_routine_and_its_kind_instead_of_the_binding() -> None:
    getter = CallableGetter()

    class Meter:
        half = functools.partial(getter)

    with pytest.raises(
        TypeError,
        match=rf"\.Meter\.half\b.*\bfunctools\.partial\b.*{re.escape(repr(getter))}.*\.CallableGetter\b",
    ):
        member_forms(Meter)


def test_a_partial_member_wrapped_in_staticmethod_is_spelled_staticmethod_then_the_signature_the_partial_leaves() -> None:
    def settle(share: float, rate: int) -> None: ...

    class Meter:
        half = staticmethod(functools.partial(settle, rate=1))

    assert member_forms(Meter) == {"half": "staticmethod (share: float, *, rate: int = 1) -> None"}
