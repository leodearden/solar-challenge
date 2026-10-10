# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_surface_forms.py: the spelling of a public name's surface form, and of an exported class's member forms, that every admitted Python minor shares, the classes those forms name, directly or through other classes of a package, and the check that a class declares each public attribute it sets on self.

Each test pins one rule, so an edit that lets one minor's own rendering through, drops
part of a signature, or lets an attribute set on self go undeclared, fails here instead
of turning the frozen-surface lock red on one interpreter or blind to a real change.

The annotations below are evaluated, as in the modules they stand in for, so this module
does not import annotations from __future__. The classes whose qualified names are
asserted, or that a forward reference names, are defined at module level, where a
qualified name carries no '<locals>' and a name resolves in this module's namespace.
"""

import abc
import collections.abc
import datetime
import decimal
import enum
import fractions
import functools
import importlib.util
import pathlib
import sys
import types
import typing
from dataclasses import InitVar, dataclass, field
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Literal,
    LiteralString,
    Never,
    NewType,
    NoReturn,
    Optional,
    ParamSpec,
    Self,
    Tuple,
    Type,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
)

import pytest

from tests._surface_forms import (
    member_forms,
    named_classes,
    signature_closure,
    surface_form,
    undeclared_attributes,
    unset_attributes,
)

if TYPE_CHECKING:
    from decimal import Decimal


class Outer:
    class Inner:
        pass


@dataclass(frozen=True)
class Preset:
    rate: float


class Gauge:
    """A class with a public member of each kind member_forms spells, each annotated with its own class, and a private one."""

    reading: datetime.timedelta
    UNITS = "kWh"

    def __init__(self, site: pathlib.Path) -> None: ...

    def read(self, at: datetime.datetime) -> float: ...

    @classmethod
    def default(cls) -> "Gauge": ...

    @staticmethod
    def scale(kwh: int) -> int: ...

    @property
    def tariff(self) -> Preset: ...

    @functools.cached_property
    def inner(self) -> Outer.Inner: ...

    def _cache(self) -> bytes: ...


@dataclass(frozen=True)
class Feeder:
    """A class whose constructor names Tap and whose only member names Tally, which names Feeder back."""

    tap: "Tap"

    def tally(self) -> "Tally": ...


@dataclass(frozen=True)
class Tap:
    site: pathlib.Path


class Tally:
    def feeder(self) -> Feeder: ...


class Wrapper:
    """A wrapper of a type that, like dataclasses.InitVar, subscripts to an instance with no typing origin."""

    def __init__(self, inner: type) -> None:
        self.inner = inner

    def __class_getitem__(cls, inner: type) -> "Wrapper":
        return cls(inner)

    def __repr__(self) -> str:
        return f"Wrapper[{self.inner.__qualname__}]"


def _imported(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str, source: str
) -> types.ModuleType:
    """The module *name*, written from *source* under *tmp_path* and imported, left in sys.modules until the test ends.

    Give each test's module a name no other test uses: the helper under test reads a
    module's `if TYPE_CHECKING:` imports once per name.
    """
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_parameter_kinds_defaults_and_the_return_annotation_are_kept() -> None:
    def f(
        a: int, /, b: str = "x", *args: float, c: bool = True, **kwargs: int
    ) -> None: ...

    def g(a: int, *, b: int) -> int: ...

    def h(a, b=1): ...

    assert (
        surface_form(f)
        == "(a: int, /, b: str = 'x', *args: float, c: bool = True, **kwargs: int) -> None"
    )
    assert surface_form(g) == "(a: int, *, b: int) -> int"
    assert surface_form(h) == "(a, b=1)"


def test_an_optional_or_a_union_is_spelled_with_bars() -> None:
    def f(a: Optional[int], b: Union[int, str], c: int | None) -> None: ...

    assert surface_form(f) == "(a: int | None, b: int | str, c: int | None) -> None"


def test_none_and_type_none_are_spelled_none() -> None:
    def f(a: list[None], b: List[None], c: types.NoneType) -> None: ...

    assert surface_form(f) == "(a: list[None], b: list[None], c: None) -> None"


def test_a_class_is_spelled_by_its_qualified_name_without_its_module() -> None:
    def f(path: pathlib.Path, when: datetime.datetime, inner: Outer.Inner) -> None: ...

    assert surface_form(f) == "(path: Path, when: datetime, inner: Outer.Inner) -> None"


def test_a_typing_alias_is_spelled_by_its_builtin_origin() -> None:
    def f(
        a: List[Tuple[int, int]], b: Dict[str, float], c: tuple[int, ...], d: list[str]
    ) -> None: ...

    assert (
        surface_form(f)
        == "(a: list[tuple[int, int]], b: dict[str, float], c: tuple[int, ...], d: list[str]) -> None"
    )


def test_a_bare_typing_alias_is_spelled_by_its_origin_alone() -> None:
    def bare(
        a: List,
        b: Dict,
        c: Tuple,
        d: Callable,
        e: list,
        f: collections.abc.Callable,
        g: Type,
        h: Iterable,
    ) -> None: ...

    assert (
        surface_form(bare)
        == "(a: list, b: dict, c: tuple, d: Callable, e: list, f: Callable, g: type, h: Iterable) -> None"
    )


def test_an_empty_subscription_is_spelled_with_parentheses() -> None:
    def f(a: tuple[()], b: Tuple[()], c: Callable[[], None]) -> None: ...

    assert (
        surface_form(f) == "(a: tuple[()], b: tuple[()], c: Callable[[], None]) -> None"
    )


def test_a_param_spec_args_and_kwargs_are_spelled_by_their_reprs() -> None:
    P = ParamSpec("P")

    def f(*args: P.args, **kwargs: P.kwargs) -> None: ...

    assert surface_form(f) == "(*args: P.args, **kwargs: P.kwargs) -> None"


def test_a_type_variable_declaring_nothing_or_a_special_form_is_spelled_by_its_repr() -> None:
    T = TypeVar("T")
    P = ParamSpec("P")
    Ts = TypeVarTuple("Ts")

    def f(a: T, b: P, c: Ts, d: Self, e: LiteralString) -> Never: ...

    assert (
        surface_form(f)
        == "(a: ~T, b: ~P, c: Ts, d: typing.Self, e: typing.LiteralString) -> typing.Never"
    )


def test_a_type_variable_is_spelled_by_its_repr_then_the_constraints_and_the_bound_it_declares() -> None:
    Rated = TypeVar("Rated", bound=Preset)
    Pending = TypeVar("Pending", bound="Preset")
    Ratio = TypeVar("Ratio", bound=Optional[fractions.Fraction])
    Number = TypeVar("Number", int, "Outer.Inner")
    Source = TypeVar("Source", covariant=True, bound=Preset)
    Hook = ParamSpec("Hook", bound=Callable[..., Preset])

    def f(
        a: Rated,
        b: Pending,
        c: Ratio,
        d: Number,
        e: typing.AnyStr,
        g: Callable[Hook, None],
    ) -> Source: ...

    assert (
        surface_form(f)
        == "(a: ~Rated(bound=Preset), b: ~Pending(bound=Preset), c: ~Ratio(bound=Fraction | None), d: ~Number(int, Outer.Inner), e: ~AnyStr(bytes, str), g: Callable[~Hook(bound=Callable[..., Preset]), None]) -> +Source(bound=Preset)"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 13), reason="a type variable's default is new in Python 3.13"
)
def test_a_type_variable_default_is_spelled_last_by_keyword() -> None:
    Rated = TypeVar("Rated", bound=float, default=int)
    Absent = TypeVar("Absent", default=None)
    Hook = ParamSpec("Hook", default=[int, Preset])
    Shape = TypeVarTuple("Shape", default=Unpack[tuple[int, Preset]])

    def f(
        a: Rated, b: Absent, c: Callable[Hook, None], d: tuple[Unpack[Shape]]
    ) -> None: ...

    assert (
        surface_form(f)
        == "(a: ~Rated(bound=float, default=int), b: ~Absent(default=None), c: Callable[~Hook(default=[int, Preset]), None], d: tuple[typing.Unpack[Shape(default=typing.Unpack[tuple[int, Preset]])]]) -> None"
    )


def test_a_new_type_is_spelled_by_its_qualified_name_then_its_supertype() -> None:
    Kwh = NewType("Kwh", float)
    Wh = NewType("Wh", Kwh)
    Readings = NewType("Readings", list[Optional[Preset]])

    def f(a: Kwh, b: Wh, c: Readings) -> None: ...

    assert (
        surface_form(f)
        == "(a: Kwh(float), b: Wh(Kwh(float)), c: Readings(list[Preset | None])) -> None"
    )


def test_a_string_annotation_is_spelled_verbatim_and_unquoted() -> None:
    def f(a: "Optional[Foo]", b: "'Bar'", c: "Optional[int]") -> "Baz": ...  # noqa: F821

    assert surface_form(f) == "(a: Optional[Foo], b: 'Bar', c: Optional[int]) -> Baz"


def test_a_forward_reference_inside_an_alias_is_spelled_by_its_name() -> None:
    def f(a: Optional["Foo"], b: List["Bar"], c: list["Baz"]) -> None: ...  # noqa: F821

    assert surface_form(f) == "(a: Foo | None, b: list[Bar], c: list[Baz]) -> None"


def test_any_is_spelled_by_its_name() -> None:
    def f(a: Any, b: Dict[str, Any]) -> Any: ...

    assert surface_form(f) == "(a: Any, b: dict[str, Any]) -> Any"


def test_a_callable_is_spelled_with_its_parameter_types_respelled() -> None:
    def f(
        simulate: Callable[[pathlib.Path, Optional[int]], float],
        hook: Callable[..., None],
    ) -> None: ...

    assert (
        surface_form(f)
        == "(simulate: Callable[[Path, int | None], float], hook: Callable[..., None]) -> None"
    )


def test_a_literal_is_spelled_with_its_values_reprs() -> None:
    def f(sharing_mode: Literal["p2p", "community_battery"]) -> None: ...

    assert (
        surface_form(f) == "(sharing_mode: Literal['p2p', 'community_battery']) -> None"
    )


def test_an_annotated_is_spelled_with_its_metadata_reprs() -> None:
    def f(power: Annotated[Optional[float], "kW"]) -> None: ...

    assert surface_form(f) == "(power: Annotated[float | None, 'kW']) -> None"


def test_a_class_form_is_its_constructor_signature() -> None:
    @dataclass(frozen=True)
    class Point:
        x: float
        tags: list[str] = field(default_factory=list)
        label: str = ""

    class Plain:
        def __init__(self, a: int, b: Optional[str] = None) -> None: ...

    assert (
        surface_form(Point)
        == "(x: float, tags: list[str] = <factory>, label: str = '') -> None"
    )
    assert surface_form(Plain) == "(a: int, b: str | None = None) -> None"


def test_an_init_only_variable_is_spelled_init_var_then_its_type() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        scale: InitVar[Optional[float]]
        site: InitVar[Outer.Inner]

    assert (
        surface_form(Reading)
        == "(kwh: float, scale: InitVar[float | None], site: InitVar[Outer.Inner]) -> None"
    )


def test_an_enum_form_is_its_members_in_definition_order() -> None:
    class Period(enum.Enum):
        PEAK = "peak"
        OFF_PEAK = "off_peak"

    assert surface_form(Period) == "PEAK='peak', OFF_PEAK='off_peak'"


def test_a_constant_form_is_its_type_qualified_name() -> None:
    assert surface_form({"a": 1}) == "dict"
    assert surface_form((1, 2)) == "tuple"
    assert surface_form(Preset(rate=0.15)) == "Preset"


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


def test_an_inherited_member_is_a_member_of_the_class_that_defines_it() -> None:
    class Base:
        def read(self) -> float: ...

    class Child(Base):
        def reset(self) -> None: ...

    assert member_forms(Base) == {"read": "(self) -> float"}
    assert member_forms(Child) == {"reset": "(self) -> None"}


def test_a_generic_names_its_origin_and_its_arguments_classes() -> None:
    def f(
        a: list[Preset],
        b: dict[str, Outer.Inner],
        c: Callable[[Preset], float],
        d: tuple[int, ...],
    ) -> None: ...

    assert named_classes(f) == {
        list,
        Preset,
        dict,
        str,
        Outer.Inner,
        collections.abc.Callable,
        float,
        tuple,
        int,
    }


def test_a_bare_typing_alias_names_its_origin() -> None:
    def f(a: List, b: Callable, c: Type) -> None: ...

    assert named_classes(f) == {list, collections.abc.Callable, type}


def test_a_union_names_its_members_classes_alone() -> None:
    def f(a: Optional[Preset], b: Union[int, str], c: float | None) -> None: ...

    assert named_classes(f) == {Preset, int, str, float}


def test_an_init_only_variable_names_its_type_classes_alone() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        ratio: InitVar[Optional[fractions.Fraction]]
        preset: "InitVar[Preset]"

    assert named_classes(Reading) == {float, fractions.Fraction, Preset}


def test_literal_values_and_annotated_metadata_name_no_class() -> None:
    def f(a: Literal["Preset"], b: Annotated[float, Preset]) -> None: ...

    assert named_classes(f) == {float}


def test_a_param_spec_args_and_kwargs_name_no_class() -> None:
    P = ParamSpec("P")

    def f(*args: P.args, **kwargs: P.kwargs) -> None: ...

    assert named_classes(f) == set()


def test_a_type_variable_declaring_nothing_or_a_special_form_names_no_class() -> None:
    T = TypeVar("T")
    P = ParamSpec("P")
    Ts = TypeVarTuple("Ts")

    def f(a: T, b: P, c: Ts, d: Self) -> NoReturn: ...

    assert named_classes(f) == set()


def test_a_type_variable_names_the_classes_its_constraints_and_its_bound_name() -> None:
    Rated = TypeVar("Rated", bound=Optional[Preset])
    Pending = TypeVar("Pending", bound="Outer.Inner")
    Ratio = TypeVar("Ratio", int, fractions.Fraction)

    def f(a: Rated, b: Pending) -> Ratio: ...

    assert named_classes(f) == {Preset, Outer.Inner, int, fractions.Fraction}


@pytest.mark.skipif(
    sys.version_info < (3, 13), reason="a type variable's default is new in Python 3.13"
)
def test_a_type_variable_names_the_classes_its_default_names() -> None:
    Rated = TypeVar("Rated", default=Preset)
    Hook = ParamSpec("Hook", default=[fractions.Fraction])
    Shape = TypeVarTuple("Shape", default=Unpack[tuple[Outer.Inner]])

    def f(a: Rated, b: Callable[Hook, None], c: tuple[Unpack[Shape]]) -> None: ...

    assert named_classes(f) == {
        Preset,
        collections.abc.Callable,
        fractions.Fraction,
        tuple,
        Outer.Inner,
    }


def test_a_new_type_names_its_supertype_classes_alone() -> None:
    PresetId = NewType("PresetId", Preset)
    Readings = NewType("Readings", list[Outer.Inner])

    def f(a: PresetId, b: Readings) -> None: ...

    assert named_classes(f) == {Preset, list, Outer.Inner}


def test_none_and_type_none_name_no_class() -> None:
    def with_none(readings: list[None]) -> None: ...

    def with_type_none(readings: List[None]) -> types.NoneType: ...

    assert named_classes(with_none) == {list}
    assert named_classes(with_type_none) == {list}


def test_a_string_annotation_or_a_forward_reference_names_the_class_its_module_binds_the_name_to() -> None:
    def f(a: "Preset", b: Optional["Outer.Inner"]) -> "list[Preset]": ...

    assert named_classes(f) == {Preset, Outer.Inner, list}


def test_a_name_its_module_imports_only_for_type_checking_names_the_class_that_import_binds() -> None:
    def f(amount: "Decimal") -> None: ...

    assert named_classes(f) == {decimal.Decimal}


def test_an_unresolvable_forward_reference_raises_a_name_error_naming_it() -> None:
    def f(a: "Nowhere") -> None: ...  # noqa: F821

    with pytest.raises(NameError, match="Nowhere"):
        named_classes(f)


def test_an_annotation_no_construct_reads_raises_a_type_error_naming_it_and_its_type() -> None:
    def f(preset: Wrapper[Preset]) -> None: ...

    naming_it_and_its_type = r"Wrapper\[Preset\].*\btests\.unit\.test_surface_forms_helper\.Wrapper\b"
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        surface_form(f)
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        named_classes(f)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="typing.TypeAliasType is new in Python 3.12")
def test_a_type_alias_raises_a_type_error_since_it_means_its_value_which_no_construct_reads() -> None:
    Readings = typing.TypeAliasType("Readings", list[Preset])

    def f(readings: Readings) -> None: ...

    naming_it_and_its_type = r"Readings.*\btyping\.TypeAliasType\b"
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        surface_form(f)
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        named_classes(f)


def test_a_class_names_the_classes_its_constructor_and_each_public_member_name() -> None:
    assert named_classes(Gauge) == {
        pathlib.Path,
        datetime.timedelta,
        str,
        datetime.datetime,
        float,
        Gauge,
        int,
        Preset,
        Outer.Inner,
    }


def test_an_inherited_constructor_names_the_classes_the_module_defining_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metering = _imported(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, ratio: 'Fraction') -> None: ...\n",
    )

    class Submeter(metering.Meter):
        pass

    assert named_classes(Submeter) == {fractions.Fraction}


def test_a_forward_reference_a_type_variable_declares_names_the_class_the_module_declaring_it_binds_the_name_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rating = _imported(
        tmp_path,
        monkeypatch,
        "rating",
        "from fractions import Fraction\n"
        "from typing import TypeVar\n"
        "\n"
        "Ratio = TypeVar('Ratio', bound='Fraction')\n",
    )

    def f(ratio: rating.Ratio) -> None: ...

    assert named_classes(f) == {fractions.Fraction}


def test_a_type_variable_or_a_new_type_inside_its_own_declaration_names_no_class_there(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linking = _imported(
        tmp_path,
        monkeypatch,
        "linking",
        "from typing import Generic, NewType, TypeVar\n"
        "\n"
        "Linked = TypeVar('Linked', bound='Node[Linked]')\n"
        "Ranked = TypeVar('Ranked', bound='list[Graded]')\n"
        "Graded = TypeVar('Graded', bound='dict[str, Ranked]')\n"
        "Chain = NewType('Chain', 'list[Chain]')\n"
        "\n"
        "class Node(Generic[Linked]): ...\n",
    )

    def f(a: linking.Linked, b: linking.Ranked, c: linking.Chain) -> None: ...

    assert (
        surface_form(f)
        == "(a: ~Linked(bound=Node[Linked]), b: ~Ranked(bound=list[Graded]), c: Chain(list[Chain])) -> None"
    )
    assert named_classes(f) == {linking.Node, list, dict, str}


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="type parameter syntax is new in Python 3.12"
)
def test_a_type_parameter_inside_its_own_bound_is_spelled_there_by_its_name_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    branching = _imported(
        tmp_path,
        monkeypatch,
        "branching",
        "class Node[T]: ...\n\n\ndef link[T: Node[T]](node: T) -> T: ...\n",
    )

    assert surface_form(branching.link) == "(node: T(bound=Node[T])) -> T(bound=Node[T])"
    assert named_classes(branching.link) == {branching.Node}


def test_a_default_value_names_no_class() -> None:
    def f(at: object = Preset(rate=0.1)) -> None: ...

    assert named_classes(f) == {object}


def test_an_enum_names_its_methods_classes_but_not_its_members() -> None:
    class Period(enum.Enum):
        PEAK = 1.5

        def label(self) -> str: ...

    assert named_classes(Period) == {str}


def test_a_constant_names_its_type() -> None:
    assert named_classes({"a": 1}) == {dict}
    assert named_classes(Preset(rate=0.1)) == {Preset}


def test_a_signature_closure_follows_each_class_it_finds_through_its_constructor_and_its_members() -> None:
    def supply(feeder: Feeder) -> None: ...

    assert signature_closure([supply], "tests") == {Feeder, Tap, Tally}


def test_a_signature_closure_leaves_out_a_root_class_but_follows_its_forms() -> None:
    def supply(feeder: Feeder, preset: Preset) -> None: ...

    assert signature_closure([supply, Feeder, Preset], "tests") == {Tap, Tally}


def test_a_signature_closure_holds_only_classes_the_package_defines() -> None:
    def supply(feeder: Feeder, site: pathlib.Path) -> float: ...

    assert signature_closure([supply], "tests.unit") == {Feeder, Tap, Tally}
    assert signature_closure([supply], "solar_challenge") == set()


def test_a_signature_closure_follows_the_classes_a_type_variable_or_a_new_type_carries() -> None:
    Supplied = TypeVar("Supplied", bound=Feeder)
    PresetId = NewType("PresetId", Preset)

    def supply(feeder: Supplied, preset: PresetId) -> Supplied: ...

    assert signature_closure([supply], "tests") == {Feeder, Tap, Tally, Preset}


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
