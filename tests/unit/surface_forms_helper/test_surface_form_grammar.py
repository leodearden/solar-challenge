# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for how an annotation is spelled by its construct, and an object by its kind, one per test.

Wrapper is defined at module level, where its qualified name carries no '<locals>'.
"""

import collections.abc
import datetime
import enum
import fractions
import pathlib
import sys
import types
import typing
from dataclasses import InitVar, dataclass, field
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    LiteralString,
    Never,
    NewType,
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

from tests._surface_forms import member_forms, named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGetterDeleter,
    GetterDeleter,
    Outer,
    Preset,
    imported_module,
)


class Wrapper:
    """A wrapper of a type that, like dataclasses.InitVar, subscripts to an instance with no typing origin."""

    def __init__(self, inner: type) -> None:
        self.inner = inner

    def __class_getitem__(cls, inner: type) -> "Wrapper":
        return cls(inner)

    def __repr__(self) -> str:
        return f"Wrapper[{self.inner.__qualname__}]"


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


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="type parameter syntax is new in Python 3.12"
)
def test_a_type_parameter_inside_its_own_bound_is_spelled_there_by_its_name_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    branching = imported_module(
        tmp_path,
        monkeypatch,
        "branching",
        "class Node[T]: ...\n\n\ndef link[T: Node[T]](node: T) -> T: ...\n",
    )

    assert surface_form(branching.link) == "(node: T(bound=Node[T])) -> T(bound=Node[T])"
    assert named_classes(branching.link) == {branching.Node}


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="type parameter syntax is new in Python 3.12"
)
def test_a_new_type_inside_its_own_declaration_is_spelled_there_by_its_name_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grafting = imported_module(
        tmp_path,
        monkeypatch,
        "grafting",
        "from typing import NewType\n"
        "\n"
        "\n"
        "class Tree[T: Tree.Branch]:\n"
        "    Branch = NewType('Branch', list[T])\n"
        "\n"
        "\n"
        "def graft(branch: Tree.Branch) -> None: ...\n",
    )

    assert (
        surface_form(grafting.graft)
        == "(branch: Branch(list[T(bound=Branch)])) -> None"
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


def test_an_annotation_no_construct_reads_raises_a_type_error_naming_it_and_its_type() -> None:
    def f(preset: Wrapper[Preset]) -> None: ...

    naming_it_and_its_type = r"Wrapper\[Preset\].*\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.Wrapper\b"
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


def test_a_class_form_ends_with_its_constructor_signature() -> None:
    @dataclass(frozen=True)
    class Point:
        x: float
        tags: list[str] = field(default_factory=list)
        label: str = ""

    class Plain:
        def __init__(self, a: int, b: Optional[str] = None) -> None: ...

    assert (
        surface_form(Point)
        == "dataclass[eq, frozen] (x: float, tags: list[str] = <factory>, label: str = '') -> None"
    )
    assert surface_form(Plain) == "(a: int, b: str | None = None) -> None"


def test_a_dataclass_form_begins_with_dataclass_then_in_brackets_those_of_eq_order_unsafe_hash_and_frozen_that_are_on() -> None:
    @dataclass
    class Register:
        count: int

    @dataclass(frozen=True)
    class Reading:
        kwh: float

    @dataclass(order=True, unsafe_hash=True, frozen=True)
    class Rank:
        level: int

    @dataclass(eq=False)
    class Probe:
        site: str

    assert surface_form(Register) == "dataclass[eq] (count: int) -> None"
    assert surface_form(Reading) == "dataclass[eq, frozen] (kwh: float) -> None"
    assert (
        surface_form(Rank) == "dataclass[eq, order, unsafe_hash, frozen] (level: int) -> None"
    )
    assert surface_form(Probe) == "dataclass (site: str) -> None"


def test_a_dataclass_kind_lists_no_other_dataclass_parameter() -> None:
    @dataclass(repr=False, match_args=False, kw_only=True, slots=True, weakref_slot=True)
    class Quiet:
        kwh: float

    @dataclass(init=False)
    class Meter:
        site: str

        def __init__(self, site: str) -> None: ...

    assert surface_form(Quiet) == "dataclass[eq] (*, kwh: float) -> None"
    assert surface_form(Meter) == "dataclass[eq] (site: str) -> None"


def test_an_undecorated_subclass_of_a_dataclass_is_spelled_with_the_kind_it_inherits() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

    class Scaled(Reading):
        def scaled(self, factor: float) -> float: ...

    assert surface_form(Scaled) == "dataclass[eq, frozen] (kwh: float) -> None"


def test_an_init_only_variable_is_spelled_init_var_then_its_type() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        scale: InitVar[Optional[float]]
        site: InitVar[Outer.Inner]

    assert (
        surface_form(Reading)
        == "dataclass[eq, frozen] (kwh: float, scale: InitVar[float | None], site: InitVar[Outer.Inner]) -> None"
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


@pytest.mark.parametrize(
    ("descriptor", "name"),
    [
        pytest.param(GetterDeleter(), "GetterDeleter", id="getter-deleter"),
        pytest.param(CallableGetterDeleter(), "CallableGetterDeleter", id="callable-getter-deleter"),
    ],
)
def test_a_descriptor_whose_type_defines_get_and_delete_but_no_set_is_a_constant_spelled_by_its_type_qualified_name(
    descriptor: object, name: str
) -> None:
    class Meter:
        reset = descriptor

    assert surface_form(descriptor) == name
    assert named_classes(descriptor) == {type(descriptor)}
    assert member_forms(Meter) == {"reset": name}
    assert named_classes(Meter) == {type(descriptor)}
