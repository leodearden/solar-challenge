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
from dataclasses import dataclass, field
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
    Optional,
    ParamSpec,
    Tuple,
    Type,
    Union,
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


def test_a_string_annotation_is_spelled_verbatim_and_unquoted() -> None:
    def f(a: "Optional[Foo]", b: "'Bar'") -> "Baz": ...  # noqa: F821

    assert surface_form(f) == "(a: Optional[Foo], b: 'Bar') -> Baz"


def test_a_forward_reference_inside_an_alias_is_spelled_by_its_name() -> None:
    def f(a: Optional["Foo"], b: List["Bar"]) -> None: ...  # noqa: F821

    assert surface_form(f) == "(a: Foo | None, b: list[Bar]) -> None"


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

    assert member_forms(Meter) == {"UNITS": "str", "SCALE": "float"}


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


def test_a_name_the_class_body_only_annotates_as_a_class_variable_is_not_a_member() -> None:
    class Meter:
        UNITS: ClassVar[str]
        SCALE: ClassVar

    assert member_forms(Meter) == {}


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
    assert named_classes(Meter) == {Preset, type(None), str}


def test_a_dataclass_field_its_constructor_takes_is_not_a_member_but_a_class_variable_is() -> None:
    @dataclass(frozen=True)
    class Site:
        LAT: ClassVar[float] = 51.45
        site_id: int
        name: str = ""
        tags: list[str] = field(default_factory=list)

    assert member_forms(Site) == {"LAT": "float"}


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


def test_a_union_names_its_members_classes_alone() -> None:
    def f(a: Optional[Preset], b: Union[int, str], c: float | None) -> None: ...

    assert named_classes(f) == {Preset, type(None), int, str, float}


def test_literal_values_and_annotated_metadata_name_no_class() -> None:
    def f(a: Literal["Preset"], b: Annotated[float, Preset]) -> None: ...

    assert named_classes(f) == {float}


def test_a_string_annotation_or_a_forward_reference_names_the_class_its_module_binds_the_name_to() -> None:
    def f(a: "Preset", b: Optional["Outer.Inner"]) -> "list[Preset]": ...

    assert named_classes(f) == {Preset, Outer.Inner, type(None), list}


def test_a_name_its_module_imports_only_for_type_checking_names_the_class_that_import_binds() -> None:
    def f(amount: "Decimal") -> None: ...

    assert named_classes(f) == {decimal.Decimal}


def test_an_unresolvable_forward_reference_raises_a_name_error_naming_it() -> None:
    def f(a: "Nowhere") -> None: ...  # noqa: F821

    with pytest.raises(NameError, match="Nowhere"):
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
    source = tmp_path / "metering.py"
    source.write_text(
        "from fractions import Fraction\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, ratio: 'Fraction') -> None: ...\n"
    )
    spec = importlib.util.spec_from_file_location("metering", source)
    assert spec is not None and spec.loader is not None
    metering = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "metering", metering)
    spec.loader.exec_module(metering)

    class Submeter(metering.Meter):
        pass

    assert named_classes(Submeter) == {fractions.Fraction}


def test_a_default_value_and_a_none_return_name_no_class() -> None:
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
