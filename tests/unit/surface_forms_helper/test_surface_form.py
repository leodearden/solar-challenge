# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form, one per test.

The classes above the first test, and the functions beside them, are defined at module
level, where their qualified names carry no '<locals>' and a parametrize decorator can
reach them.

docs/surface-forms-inspect-readings.md says how each minor reads what these rules refuse
or read alike, and names the tests that pin each by node-id.
"""

import collections.abc
import contextlib
import datetime
import decimal
import enum
import fractions
import functools
import inspect
import operator
import pathlib
import re
import sqlite3
import sys
import types
import typing
import warnings
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
    UNREADABLE_ROUTINES,
    CallableGetter,
    GetterPartial,
    NoneSignedCallableGetter,
    Outer,
    Preset,
    SettableGetterPartial,
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


class Ledger(dict):
    """A class that inherits its constructor from dict, which CPython defines in C."""


class GetterDeleter:
    """A descriptor whose type defines __get__ and __delete__ but no __set__."""

    def __get__(self, instance: object, owner: type) -> int:
        return 1

    def __delete__(self, instance: object) -> None: ...


class CallableGetterDeleter(GetterDeleter):
    """A callable GetterDeleter."""

    def __call__(self, rate: int) -> str: ...


class DeletableCallableGetter(CallableGetter):
    """A CallableGetter whose type also defines __delete__, so that inspect counts it a method descriptor before Python 3.13 alone."""

    def __delete__(self, instance: object) -> None: ...


class Tariff(enum.Enum):
    """An Enum that EnumCall's __call__ wraps."""

    PEAK = "peak"


class StringSignedCall:
    """A class whose __call__ carries a string as __signature__."""

    def __call__(self, rate: int) -> None: ...

    __call__.__signature__ = "(self, rate)"


class EnumCall:
    """A class whose __call__ wraps Tariff, as functools.wraps records one."""

    @functools.wraps(Tariff)
    def __call__(self, value: object) -> object: ...


class GetterCall:
    """A class whose __call__ is a CallableGetter, whose signature inspect cannot read."""

    __call__ = CallableGetter()


class TextedCall:
    """A class whose instances carry a __text_signature__ beside the __call__ it defines."""

    __text_signature__ = "(rate)"

    def __call__(self, rate: int) -> None: ...


class UnsignedTextedCall(TextedCall):
    """A TextedCall whose instances also carry a __signature__ of None."""

    __signature__ = None


def _settled(self: object, share: float, rate: int) -> None: ...


class DeletableGetterPartial(GetterPartial):
    """A GetterPartial whose type also defines __delete__, which inspect before Python 3.13 ignores in counting it a method descriptor."""

    def __delete__(self, instance: object) -> None: ...


class GetMixin:
    """A class that defines __get__, for a functools.partial subclass to take it from."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self


class MixedInGetterPartial(GetMixin, functools.partial):
    """A functools.partial whose type takes __get__ from a base before functools.partial in its MRO."""


class PartialFirstGetterPartial(functools.partial, GetMixin):
    """A functools.partial whose type takes __get__ from a base after functools.partial in its MRO."""


class GivingGetterPartial:
    """A descriptor, no functools.partial, whose __get__ gives a GetterPartial."""

    def __get__(self, instance: object, owner: type | None = None) -> GetterPartial:
        return GetterPartial(_settled, rate=1)


class GetterPartialNew:
    """A class whose __new__ is a GetterPartial."""

    __new__ = GetterPartial(_settled, rate=1)


class GivingGetterPartialInit:
    """A class whose __init__ is a GivingGetterPartial."""

    __init__ = GivingGetterPartial()


class GivingGetterPartialCall:
    """A class whose __call__ is a GivingGetterPartial."""

    __call__ = GivingGetterPartial()


def _with_a_signature_of_none(partial: GetterPartial) -> GetterPartial:
    partial.__signature__ = None
    return partial


def _with_a_text_signature(partial: GetterPartial) -> GetterPartial:
    partial.__text_signature__ = "(rate)"
    return partial


def _with_an_instance_attribute(partial: GetterPartial) -> GetterPartial:
    partial.note = "an attribute, so that a functools.partial of it keeps it as its func"
    return partial


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

    naming_it_and_its_type = r"Wrapper\[Preset\].*\btests\.unit\.surface_forms_helper\.test_surface_form\.Wrapper\b"
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


def test_a_partial_is_spelled_by_the_signature_it_leaves_of_the_callable_it_wraps() -> None:
    def settle(share: fractions.Fraction, rate: int, *, fee: Optional[float] = None) -> None: ...

    assert (
        surface_form(functools.partial(settle, rate=1))
        == "(share: Fraction, *, rate: int = 1, fee: float | None = None) -> None"
    )
    assert (
        surface_form(functools.partial(settle, fractions.Fraction(1, 2)))
        == "(rate: int, *, fee: float | None = None) -> None"
    )


def test_a_class_whose_init_is_a_partial_raises_a_type_error_naming_it_and_the_class_holding_the_partial() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    class Rebuilt(Built):
        pass

    naming_built_and_its_init = r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    with pytest.raises(TypeError, match=naming_built_and_its_init):
        surface_form(Built)
    with pytest.raises(TypeError, match=naming_built_and_its_init):
        named_classes(Built)
    with pytest.raises(
        TypeError, match=r"\.Rebuilt\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(Rebuilt)


def test_a_class_whose_new_is_a_partial_is_spelled_by_the_signature_the_partial_leaves_less_cls() -> None:
    def make(cls: type, rate: int, scale: float = 1.0) -> object: ...

    class Made:
        __new__ = functools.partial(make, scale=2.0)

    assert surface_form(Made) == "(rate: int, *, scale: float = 2.0) -> object"


def test_a_class_whose_init_is_a_partial_beside_a_new_defined_with_def_is_spelled_by_that_new() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Both:
        def __new__(cls, rate: int) -> object: ...

        __init__ = functools.partial(build, scale=2.0)

    assert surface_form(Both) == "(rate: int) -> object"


@pytest.mark.parametrize(
    "new",
    [
        pytest.param(object.__new__, id="builtin"),
        pytest.param(staticmethod(object.__new__), id="staticmethod"),
    ],
)
def test_a_class_whose_init_is_a_partial_beside_a_new_defined_in_c_raises_the_type_error_naming_the_partial(
    new: object,
) -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Assigned:
        __new__ = new
        __init__ = functools.partial(build, scale=2.0)

    with pytest.raises(
        TypeError, match=r"\.Assigned\b.*\.Assigned\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(Assigned)


@pytest.mark.parametrize(
    ("cls", "naming_it_and_its_constructor"),
    [
        pytest.param(
            functools.partial,
            r"\bfunctools\.partial\b.*\bfunctools\.partial\b",
            id="functools.partial",
        ),
        pytest.param(int, r"\bbuiltins\.int\b.*\bbuiltins\.int\b", id="int"),
        pytest.param(list, r"\bbuiltins\.list\b.*\bbuiltins\.list\b", id="list"),
        pytest.param(
            decimal.Decimal,
            r"\bdecimal\.Decimal\b.*\bdecimal\.Decimal\b",
            id="decimal.Decimal",
        ),
        pytest.param(
            types.ModuleType,
            r"\bbuiltins\.module\b.*\bbuiltins\.module\b",
            id="types.ModuleType",
        ),
        pytest.param(
            types.FunctionType,
            r"\bbuiltins\.function\b.*\bbuiltins\.function\b",
            id="types.FunctionType",
        ),
        pytest.param(
            Ledger,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form\.Ledger\b.*\bbuiltins\.dict\b",
            id="Ledger",
        ),
    ],
)
def test_a_class_constructed_by_a_class_defined_in_c_raises_a_type_error_naming_it_and_that_class(
    cls: type, naming_it_and_its_constructor: str
) -> None:
    with pytest.raises(TypeError, match=naming_it_and_its_constructor):
        surface_form(cls)
    with pytest.raises(TypeError, match=naming_it_and_its_constructor):
        named_classes(cls)


def test_a_class_that_object_constructs_is_spelled_with_no_parameters() -> None:
    class Plain:
        pass

    assert surface_form(object) == "()"
    assert surface_form(Plain) == "()"


def test_a_partial_of_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    with pytest.raises(
        TypeError, match=r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(functools.partial(Built, 1))
    with pytest.raises(TypeError, match=r"\bbuiltins\.dict\b.*\bbuiltins\.dict\b"):
        surface_form(functools.partial(dict, rate=1.0))
    with pytest.raises(
        TypeError, match=r"\bfunctools\.partial\b.*\bfunctools\.partial\b"
    ):
        named_classes(functools.partial(functools.partial, print))


def test_a_routine_that_wraps_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    class Zipper:
        @functools.wraps(zip)
        def zipped(self, *iterables: object) -> object: ...

    zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    building = functools.wraps(Built)(lambda rate: Built(rate))
    unsigned = functools.partial(zip, [1])
    unsigned.__signature__ = None
    wrapping = functools.partial(build, 1)
    wrapping.__wrapped__ = zip

    naming_zip = r"\bbuiltins\.zip\b.*\bbuiltins\.zip\b"
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        named_classes(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(functools.partial(zipping, [1]))
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(Zipper().zipped)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(unsigned)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(wrapping)
    with pytest.raises(
        TypeError, match=r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(building)


def test_a_routine_that_wraps_an_enum_raises_a_type_error_naming_it_and_that_enum() -> None:
    class Period(enum.Enum):
        PEAK = "peak"

    naming_the_partial_and_period = r"\bfunctools\.partial\(.*\.Period\b.*\benum\.Enum\b"
    with pytest.raises(TypeError, match=naming_the_partial_and_period):
        surface_form(functools.partial(Period))
    with pytest.raises(TypeError, match=naming_the_partial_and_period):
        named_classes(functools.partial(Period))
    with pytest.raises(TypeError, match=r"\.Period\b.*\.Period\b.*\benum\.Enum\b"):
        surface_form(functools.wraps(Period)(lambda value: Period(value)))


def test_a_routine_that_wraps_a_class_but_carries_a_signature_is_spelled_by_that_signature() -> None:
    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    zipping.__signature__ = signature
    zipped = functools.partial(zip, [1])
    zipped.__signature__ = signature

    assert surface_form(zipping) == "(rate: int)"
    assert named_classes(zipping) == {int}
    assert surface_form(zipped) == "(rate: int)"
    assert named_classes(zipped) == {int}


def test_a_routine_that_carries_a_signature_of_none_is_spelled_by_its_own_signature_whatever_it_wraps() -> None:
    def settle(self: object, rate: int) -> None: ...

    def zipping(share: decimal.Decimal) -> None: ...

    zipping.__wrapped__ = zip
    zipping.__signature__ = None

    @functools.wraps(functools.partialmethod(settle, rate=1))
    def halved(self: object) -> None: ...

    halved.__signature__ = None

    assert surface_form(zipping) == "(share: Decimal) -> None"
    assert named_classes(zipping) == {decimal.Decimal}
    assert surface_form(halved) == "(self: object) -> None"


def test_a_class_that_carries_a_signature_is_spelled_by_that_signature_whatever_its_constructor() -> None:
    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Rated(dict):
        __signature__ = signature

    class Rerated(Rated):
        pass

    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

    class Counted(metaclass=Counting):
        __signature__ = signature

    assert surface_form(Rated) == "(rate: int)"
    assert named_classes(Rated) == {int}
    assert surface_form(Rerated) == "(rate: int)"
    assert surface_form(Counted) == "(rate: int)"
    assert surface_form(functools.partial(Rated)) == "(rate: int)"


def test_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_what_carries_it_and_that_value() -> None:
    def pay(rate: int) -> None: ...

    def settle(rate: int) -> None: ...

    settle.__signature__ = "(rate)"
    paying = functools.wraps(pay)(lambda rate: pay(rate))
    paying.__signature__ = "(rate)"
    paid = functools.partial(pay)
    paid.__signature__ = "(rate)"
    texted = functools.partial(zip, [1])
    texted.__signature__ = "(rate)"
    texted_zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    texted_zipping.__signature__ = "(rate)"

    class Texted:
        __signature__ = "(rate)"

        def __init__(self, rate: int) -> None: ...

    class Keyed(dict):
        __signature__ = "(rate)"

    class Called(dict):
        @classmethod
        def __signature__(cls) -> inspect.Signature:
            return inspect.Signature(
                [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
            )

    class Meter:
        def read(self, rate: int) -> None: ...

        read.__signature__ = "(self, rate)"

    getter = CallableGetter()
    getter.__signature__ = "(rate)"

    carrying_text = r"'\(rate\)'.*\bbuiltins\.str\b.*\binspect\.Signature\b"
    naming_settle_and_its_text = rf"\.settle\b.*{carrying_text}"
    with pytest.raises(TypeError, match=naming_settle_and_its_text):
        surface_form(settle)
    with pytest.raises(TypeError, match=naming_settle_and_its_text):
        named_classes(settle)
    with pytest.raises(TypeError, match=rf"\.pay\b.*{carrying_text}"):
        surface_form(paying)
    with pytest.raises(TypeError, match=rf"\bfunctools\.partial\(.*\bpay\b.*{carrying_text}"):
        surface_form(paid)
    with pytest.raises(TypeError, match=rf"\bfunctools\.partial\(.*\bzip\b.*{carrying_text}"):
        surface_form(texted)
    with pytest.raises(TypeError, match=rf"\bbuiltins\.zip\b.*{carrying_text}"):
        surface_form(texted_zipping)
    naming_texted_and_its_text = rf"\.Texted\b.*{carrying_text}"
    with pytest.raises(TypeError, match=naming_texted_and_its_text):
        surface_form(Texted)
    with pytest.raises(TypeError, match=naming_texted_and_its_text):
        named_classes(Texted)
    with pytest.raises(
        TypeError, match=rf"\bfunctools\.partial\(.*\.Texted\b.*{carrying_text}"
    ):
        surface_form(functools.partial(Texted))
    with pytest.raises(TypeError, match=rf"\.Keyed\b.*{carrying_text}"):
        surface_form(Keyed)
    with pytest.raises(
        TypeError, match=r"\.Called\b.*\bbuiltins\.method\b.*\binspect\.Signature\b"
    ):
        surface_form(Called)
    with pytest.raises(
        TypeError, match=r"\.Meter\.read\b.*'\(self, rate\)'.*\bbuiltins\.str\b"
    ):
        surface_form(Meter().read)
    with pytest.raises(TypeError, match=rf"\bCallableGetter\b.*{carrying_text}"):
        surface_form(getter)


def test_a_class_whose_new_or_init_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_constructor_and_that_callable() -> None:
    class Created:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Created":
            return object.__new__(cls)

        def __init__(self, rate: int) -> None: ...

    class Recreated(Created):
        pass

    class Initialised:
        @functools.wraps(object.__init__)
        def __init__(self, rate: int) -> None: ...

    class Keyed(dict):
        @functools.wraps(dict.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Keyed":
            return dict.__new__(cls)

        def __init__(self, rate: int) -> None: ...

    naming_created_and_its_new = r"\.Created\b.*\.Created\.__new__\b.*\bobject\.__new__\b"
    with pytest.raises(TypeError, match=naming_created_and_its_new):
        surface_form(Created)
    with pytest.raises(TypeError, match=naming_created_and_its_new):
        named_classes(Created)
    with pytest.raises(
        TypeError, match=r"\.Recreated\b.*\.Created\.__new__\b.*\bobject\.__new__\b"
    ):
        surface_form(Recreated)
    with pytest.raises(
        TypeError,
        match=r"\.Initialised\b.*\.Initialised\.__init__\b.*\bobject\.__init__\b",
    ):
        surface_form(Initialised)
    with pytest.raises(
        TypeError, match=r"\.Keyed\b.*\.Keyed\.__new__\b.*\bdict\.__new__\b"
    ):
        surface_form(Keyed)


@pytest.mark.skipif(
    sys.version_info < (3, 13), reason="warnings.deprecated is new in Python 3.13"
)
def test_a_class_decorated_with_warnings_deprecated_raises_the_type_error_naming_the_new_it_writes() -> None:
    @warnings.deprecated("use Meter")
    class Gauge:
        def __init__(self, rate: int) -> None: ...

    with pytest.raises(
        TypeError, match=r"\.Gauge\b.*\.Gauge\.__new__\b.*\bobject\.__new__\b"
    ):
        surface_form(Gauge)


def test_a_constructor_that_wraps_one_defined_with_def_is_spelled_by_the_one_it_wraps() -> None:
    class Based:
        def __new__(cls, rate: int) -> "Based":
            return object.__new__(cls)

    class Rebased(Based):
        @functools.wraps(Based.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Rebased":
            return Based.__new__(cls, *args, **kwargs)

    assert surface_form(Rebased) == "(rate: int) -> Based"


def test_a_wrapper_of_a_callable_defined_in_c_that_inspect_reads_after_another_constructor_leaves_the_class_spelled_by_that_constructor() -> None:
    class Paired:
        def __new__(cls, rate: int) -> "Paired":
            return object.__new__(cls)

        @functools.wraps(object.__init__)
        def __init__(self, *args: object, **kwargs: object) -> None: ...

    class Wrapping:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Wrapping":
            return object.__new__(cls)

    class Overriding(Wrapping):
        def __init__(self, rate: int) -> None: ...

    assert surface_form(Paired) == "(rate: int) -> Paired"
    assert surface_form(Overriding) == "(rate: int) -> None"


def test_a_class_whose_metaclass_call_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_call_and_that_callable() -> None:
    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

    class Counted(metaclass=Counting):
        def __init__(self, rate: int) -> None: ...

    naming_counted_and_its_call = r"\.Counted\b.*\.Counting\.__call__\b.*\btype\.__call__\b"
    with pytest.raises(TypeError, match=naming_counted_and_its_call):
        surface_form(Counted)
    with pytest.raises(TypeError, match=naming_counted_and_its_call):
        named_classes(Counted)


def test_a_class_whose_metaclass_call_is_a_partial_raises_a_type_error_naming_it_and_that_call() -> None:
    def settle(cls: type, rate: int, scale: float = 1.0) -> None: ...

    class Partial(type):
        __call__ = functools.partial(settle, scale=2.0)

    class Made(metaclass=Partial):
        pass

    naming_made_and_its_call = r"\.Made\b.*\.Partial\.__call__\b.*\bfunctools\.partial\b"
    with pytest.raises(TypeError, match=naming_made_and_its_call):
        surface_form(Made)
    with pytest.raises(TypeError, match=naming_made_and_its_call):
        named_classes(Made)


def test_a_class_whose_constructor_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_it_that_constructor_and_that_value() -> None:
    class Initialised:
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = "(self, rate)"

    class Priced:
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = lambda: "(self, rate)"

    class Created:
        def __new__(cls, rate: int) -> "Created":
            return object.__new__(cls)

        __new__.__signature__ = "(cls, rate)"

    class Recreated(Created):
        pass

    class Texted:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Texted":
            return object.__new__(cls)

        __new__.__signature__ = "(cls, rate)"

        def __init__(self, rate: int) -> None: ...

    class Counting(type):
        def __call__(cls, rate: int) -> object: ...

        __call__.__signature__ = "(cls, rate)"

    class Counted(metaclass=Counting):
        pass

    class Wrapping(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

        __call__.__signature__ = "(cls, rate)"

    class Wrapped(metaclass=Wrapping):
        pass

    naming_initialised_its_init_and_the_text = (
        r"\.Initialised\b.*\.Initialised\.__init__\b.*'\(self, rate\)'"
        r".*\bbuiltins\.str\b.*\binspect\.Signature\b"
    )
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        surface_form(Initialised)
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        named_classes(Initialised)
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        surface_form(functools.partial(Initialised))
    with pytest.raises(
        TypeError, match=r"\.Priced\b.*\.Priced\.__init__\b.*\bbuiltins\.function\b"
    ):
        surface_form(Priced)
    with pytest.raises(
        TypeError, match=r"\.Created\b.*\.Created\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Created)
    with pytest.raises(
        TypeError, match=r"\.Recreated\b.*\.Created\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Recreated)
    with pytest.raises(
        TypeError, match=r"\.Texted\b.*\.Texted\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Texted)
    with pytest.raises(
        TypeError, match=r"\.Counted\b.*\.Counting\.__call__\b.*'\(cls, rate\)'"
    ):
        surface_form(Counted)
    with pytest.raises(
        TypeError, match=r"\.Wrapped\b.*\.Wrapping\.__call__\b.*'\(cls, rate\)'"
    ):
        surface_form(Wrapped)


def test_a_class_whose_constructor_wraps_a_callable_defined_in_c_but_carries_a_signature_of_none_is_spelled_by_that_constructor() -> None:
    class Created:
        @functools.wraps(object.__new__)
        def __new__(cls, rate: int) -> object:
            return object.__new__(cls)

        __new__.__signature__ = None

    class Initialised:
        @functools.wraps(object.__init__)
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = None

    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, rate: int) -> object: ...

        __call__.__signature__ = None

    class Counted(metaclass=Counting):
        pass

    assert surface_form(Created) == "(rate: int) -> object"
    assert surface_form(Initialised) == "(rate: int) -> None"
    assert surface_form(Counted) == "(rate: int) -> object"


def test_a_class_whose_metaclass_resolves_a_call_defined_in_python_is_spelled_by_that_call_whatever_its_constructor() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Charging(type):
        def __call__(cls, rate: int) -> None: ...

    class Keyed(dict, metaclass=Charging):
        pass

    class Built(metaclass=Charging):
        __init__ = functools.partial(build, scale=2.0)

    class Created(metaclass=Charging):
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Created":
            return object.__new__(cls)

    assert surface_form(Keyed) == "(rate: int) -> None"
    assert named_classes(Keyed) == {int}
    assert surface_form(Built) == "(rate: int) -> None"
    assert surface_form(Created) == "(rate: int) -> None"


@pytest.mark.parametrize(
    ("descriptor", "reading"),
    [
        pytest.param(CallableGetter(), r"\bevery admitted minor\b", id="get-only"),
        pytest.param(
            NoneSignedCallableGetter(lambda rate: None),
            r"\bevery admitted minor\b",
            id="get-only-signature-of-none",
        ),
        pytest.param(DeletableCallableGetter(), r"\b__delete__\b.*\b3\.13\b", id="get-delete"),
    ],
)
def test_a_class_constructed_through_a_descriptor_inspect_reads_as_a_builtin_raises_a_type_error_naming_it_that_constructor_and_the_descriptor_type(
    descriptor: object, reading: str
) -> None:
    class Built:
        __init__ = descriptor

    class Rebuilt(Built):
        pass

    class Made:
        __new__ = descriptor

    class Calling(type):
        __call__ = descriptor

    class Called(metaclass=Calling):
        pass

    class Wrapped:
        @functools.wraps(descriptor)
        def __init__(self, rate: int) -> None: ...

    kind = rf"\.{type(descriptor).__qualname__}\b"
    for cls, constructor in (
        (Built, "Built.__init__"),
        (Rebuilt, "Built.__init__"),
        (Made, "Made.__new__"),
        (Called, "Calling.__call__"),
        (Wrapped, "Wrapped.__init__"),
    ):
        naming_it = rf"\.{cls.__name__}\b.*\.{re.escape(constructor)}\b.*{kind}.*{reading}"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(cls)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(cls)
    with pytest.raises(TypeError, match=rf"\.Built\b.*\.Built\.__init__\b.*{kind}"):
        surface_form(functools.partial(Built))


def test_a_class_constructed_through_a_descriptor_that_carries_a_signature_or_whose_get_gives_a_function_is_spelled_by_what_inspect_reads() -> None:
    def build(rate: int) -> str: ...

    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Giving:
        def __get__(self, instance: object, owner: type) -> Callable[..., object]:
            return build

    class Signed(CallableGetter):
        __signature__ = signature

    class SignedDeletable(DeletableCallableGetter):
        __signature__ = signature

    class Given:
        __init__ = Giving()

    class Rated:
        __init__ = Signed()

    class Rerated:
        __init__ = SignedDeletable()

    class Calling(type):
        __call__ = Giving()

    class Called(metaclass=Calling):
        pass

    class SignedCalling(type):
        __call__ = Signed()

    class SignedCalled(metaclass=SignedCalling):
        pass

    assert surface_form(Given) == "(rate: int) -> str"
    assert surface_form(Rated) == "(rate: int)"
    assert surface_form(Rerated) == "(rate: int)"
    assert surface_form(Called) == "(rate: int) -> str"
    assert surface_form(SignedCalled) == "(rate: int)"


@pytest.mark.parametrize(("routine", "kind"), UNREADABLE_ROUTINES)
def test_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_it_and_its_kind(
    routine: object, kind: str
) -> None:
    naming_it_and_its_kind = rf"{re.escape(repr(routine))}.*\b{re.escape(kind)}\b"
    with pytest.raises(TypeError, match=naming_it_and_its_kind):
        surface_form(routine)
    with pytest.raises(TypeError, match=naming_it_and_its_kind):
        named_classes(routine)


def test_a_routine_that_wraps_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_both_and_their_kinds() -> None:
    def settle(self: object, rate: int) -> None: ...

    half = functools.partialmethod(settle, rate=1)

    @functools.wraps(half)
    def halved(self: object) -> None: ...

    naming_both_and_their_kinds = (
        rf"\.halved\b.*\bbuiltins\.function\b.*{re.escape(repr(half))}"
        r".*\bfunctools\.partialmethod\b"
    )
    with pytest.raises(TypeError, match=naming_both_and_their_kinds):
        surface_form(halved)
    with pytest.raises(TypeError, match=naming_both_and_their_kinds):
        named_classes(halved)


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


def test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_raises_a_type_error_naming_it_that_descriptor_and_its_type() -> None:
    called = CallableGetterDeleter()
    uncalled = GetterDeleter()
    partial = functools.partial(called)

    @functools.wraps(called)
    def calling(rate: int) -> str: ...

    @functools.wraps(uncalled)
    def reading(rate: int) -> str: ...

    naming_the_partial_and_called = (
        rf"{re.escape(repr(partial))}.*{re.escape(repr(called))}"
        r".*\.CallableGetterDeleter\b.*\b__delete__\b"
    )
    naming_calling_and_called = (
        rf"\.calling\b.*{re.escape(repr(called))}.*\.CallableGetterDeleter\b.*\b__delete__\b"
    )
    naming_reading_and_uncalled = (
        rf"\.reading\b.*{re.escape(repr(uncalled))}.*\.GetterDeleter\b.*\b__delete__\b"
    )
    for routine, naming_it in (
        (partial, naming_the_partial_and_called),
        (calling, naming_calling_and_called),
        (reading, naming_reading_and_uncalled),
    ):
        with pytest.raises(TypeError, match=naming_it):
            surface_form(routine)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(routine)


def test_a_routine_that_wraps_a_descriptor_whose_type_defines_set_or_no_get_or_that_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it() -> None:
    class Settable(CallableGetterDeleter):
        def __set__(self, instance: object, value: object) -> None: ...

    class Getless:
        def __delete__(self, instance: object) -> None: ...

        def __call__(self, rate: int) -> str: ...

    signed = CallableGetterDeleter()
    signed.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    assert surface_form(functools.partial(Settable())) == "(rate: int) -> str"
    assert surface_form(functools.partial(Getless())) == "(rate: int) -> str"
    assert surface_form(functools.partial(signed)) == "(rate: int)"


@pytest.mark.parametrize(
    "shape", ["partial", "functools-wraps-wrapper", "bound-method", "partial-of-a-signed-wrapper"]
)
def test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_is_spelled_by_the_signature_one_of_its_links_carries(
    shape: str,
) -> None:
    rate = inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)
    receiver = inspect.Parameter("receiver", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    called = CallableGetterDeleter()

    def signed(link: Callable[..., object], *receivers: inspect.Parameter) -> Callable[..., object]:
        link.__signature__ = inspect.Signature([*receivers, rate])
        return link

    def wrapper() -> Callable[..., object]:
        return functools.wraps(called)(lambda *args: called(*args))

    routine_builders = {
        "partial": lambda: signed(functools.partial(called)),
        "functools-wraps-wrapper": lambda: signed(wrapper()),
        "bound-method": lambda: types.MethodType(signed(wrapper(), receiver), object()),
        "partial-of-a-signed-wrapper": lambda: functools.partial(signed(wrapper())),
    }
    routine = routine_builders[shape]()

    assert surface_form(routine) == "(rate: int)"
    assert named_classes(routine) == {int}


@pytest.mark.parametrize(
    ("called", "refusing_its_call"),
    [
        pytest.param(
            StringSignedCall(),
            r" is read through .*\.StringSignedCall\.__call__\b.*'\(self, rate\)'.*\bbuiltins\.str\b",
            id="string-signature",
        ),
        pytest.param(EnumCall(), r" wraps .*\.Tariff\b.*\benum\.Enum\b", id="enum"),
        pytest.param(
            GetterCall(),
            r" is a functools\.partial that wraps <.*\.CallableGetter object\b"
            r".*\bsurface_forms_helper\._fixtures\.CallableGetter\b",
            id="callable-getter",
        ),
    ],
)
def test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_raises_the_type_error_the_call_it_is_read_through_raises_naming_the_routine(
    called: object, refusing_its_call: str
) -> None:
    routine = functools.partial(called)
    naming_the_routine = re.escape(repr(routine)) + refusing_its_call
    with pytest.raises(TypeError, match=naming_the_routine):
        surface_form(routine)
    with pytest.raises(TypeError, match=naming_the_routine):
        named_classes(routine)


def test_a_routine_whose_chain_ends_at_an_object_whose_call_wraps_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    class ZipCall:
        @functools.wraps(zip)
        def __call__(self, *iterables: object) -> object: ...

    zipping = functools.partial(ZipCall())

    naming_zip = r"\bbuiltins\.zip\b.*\bbuiltins\.zip\b"
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        named_classes(zipping)


def test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_a_partial_as_call_raises_a_type_error_naming_it_and_that_call_without_binding_the_partial() -> None:
    def settle(rate: int) -> None: ...

    class PartialCall:
        __call__ = functools.partial(settle)

    class SignedPartialCall:
        __call__ = functools.partial(settle)
        __call__.__signature__ = inspect.Signature(
            [
                inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
            ]
        )

    class NestedCall:
        __call__ = PartialCall()

    called = functools.partial(PartialCall())
    calling = functools.wraps(PartialCall())(lambda rate: None)
    nested = functools.partial(NestedCall())

    naming_the_partial_and_that_call = r"\bfunctools\.partial\(.*\.PartialCall\.__call__\b.*\bfunctools\.partial\b.*\b3\.14\b"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(TypeError, match=naming_the_partial_and_that_call):
            surface_form(called)
        with pytest.raises(TypeError, match=naming_the_partial_and_that_call):
            named_classes(called)
        with pytest.raises(TypeError, match=r"\.<lambda> is read through .*\.PartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(calling)
        with pytest.raises(TypeError, match=r"\bfunctools\.partial\(.*\.SignedPartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(functools.partial(SignedPartialCall()))
        with pytest.raises(TypeError, match=rf"{re.escape(repr(nested))} is read through .*\.PartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(nested)


def test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_is_spelled_by_the_call_its_class_resolves_bound_to_it_or_by_the_signature_that_object_carries() -> None:
    def settle(rate: int) -> None: ...

    def charge(owner: object, rate: int) -> None: ...

    class StaticCall:
        __call__ = staticmethod(functools.partial(settle))

    class ClassCall:
        __call__ = classmethod(charge)

    class HalvedCall:
        __call__ = functools.partialmethod(charge, rate=1)

    class SignedCall:
        __signature__ = inspect.Signature([inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float)])
        __text_signature__ = "(rate)"
        __call__ = functools.partial(settle)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(functools.partial(StaticCall())) == "(rate: int) -> None"
        assert surface_form(functools.partial(ClassCall())) == "(rate: int) -> None"
        assert surface_form(functools.partial(HalvedCall())) == "(*, rate: int = 1) -> None"
        assert surface_form(functools.partial(SignedCall())) == "(share: float)"
        assert named_classes(functools.partial(SignedCall())) == {float}


def test_a_routine_whose_chain_ends_at_an_object_a_class_defined_in_c_makes_callable_raises_a_type_error_naming_it_that_object_and_that_class() -> None:
    getting = functools.partial(operator.itemgetter(1))

    naming_it_that_object_and_that_class = (
        r"\bfunctools\.partial\(operator\.itemgetter\(1\)\).*\boperator\.itemgetter\.__call__\b"
        r".*\bdefined in C\b"
    )
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_class):
        surface_form(getting)
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_class):
        named_classes(getting)


def test_a_routine_whose_chain_ends_at_an_object_whose_class_overrides_a_call_a_base_defines_in_c_raises_a_type_error_naming_it_that_object_and_that_base() -> None:
    class Connected(sqlite3.Connection):
        def __call__(self, rate: int) -> None: ...

    naming_it_that_object_and_that_base = (
        r"\bfunctools\.partial\(.*\.Connected\b.*\bsqlite3\.Connection\.__call__\b.*\bdefined in C\b"
    )
    with contextlib.closing(Connected(":memory:")) as connection:
        with pytest.raises(TypeError, match=naming_it_that_object_and_that_base):
            surface_form(functools.partial(connection))
        with pytest.raises(TypeError, match=naming_it_that_object_and_that_base):
            named_classes(functools.partial(connection))


@pytest.mark.parametrize(
    "called",
    [
        pytest.param(TextedCall(), id="text-signature"),
        pytest.param(UnsignedTextedCall(), id="beside-a-signature-of-none"),
    ],
)
def test_a_routine_whose_chain_ends_at_an_object_that_carries_a_text_signature_raises_a_type_error_naming_it_that_object_and_that_text(
    called: object,
) -> None:
    naming_it_that_object_and_that_text = (
        rf"\bfunctools\.partial\(.*{re.escape(repr(called))}.*\b__text_signature__ '\(rate\)'"
    )
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_text):
        surface_form(functools.partial(called))
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_text):
        named_classes(functools.partial(called))


def test_a_functools_partial_subclass_whose_type_defines_delete_is_still_a_routine_spelled_by_the_signature_it_leaves() -> None:
    class Deleting(functools.partial):
        def __delete__(self, instance: object) -> None: ...

    def settle(rate: int, share: float) -> str: ...

    assert surface_form(Deleting(settle, 1)) == "(share: float) -> str"


_NAMED_ITSELF = "^{partial} is a {kind}, "
_NAMED_AS_A_LINK = " wraps {partial}, a {kind}, "


@pytest.mark.parametrize(
    ("build", "read_in", "naming"),
    [
        pytest.param(
            lambda: GetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="getter-partial",
        ),
        pytest.param(
            lambda: DeletableGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="deletable",
        ),
        pytest.param(
            lambda: MixedInGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="mixed-in",
        ),
        pytest.param(
            lambda: PartialFirstGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="partial-first",
        ),
        pytest.param(
            lambda: _with_a_signature_of_none(GetterPartial(_settled, rate=1)),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="signature-of-none",
        ),
        pytest.param(
            lambda: _with_a_text_signature(GetterPartial(_settled, rate=1)),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="text-signature",
        ),
        pytest.param(
            lambda: functools.wraps(GetterPartial(_settled, rate=1))(lambda share: None),
            lambda subject: subject.__wrapped__,
            _NAMED_AS_A_LINK,
            id="functools-wraps",
        ),
        pytest.param(
            lambda: types.MethodType(GetterPartial(_settled, rate=1), object()),
            lambda subject: subject.__func__,
            _NAMED_AS_A_LINK,
            id="bound-method",
        ),
        pytest.param(
            lambda: functools.partial(_with_an_instance_attribute(GetterPartial(_settled, rate=1))),
            lambda subject: subject.func,
            _NAMED_AS_A_LINK,
            id="partial-of-it",
        ),
        pytest.param(
            lambda: GetterPartialNew,
            lambda subject: subject.__new__,
            r"\.GetterPartialNew is constructed through .*\.GetterPartialNew\.__new__, "
            "which inspect reads as {partial}, a {kind}, ",
            id="new",
        ),
        pytest.param(
            lambda: GivingGetterPartialInit,
            lambda subject: subject.__init__,
            r"\.GivingGetterPartialInit is constructed through .*\.GivingGetterPartialInit\.__init__, "
            "which inspect reads as {partial}, a {kind}, ",
            id="init-giving-it",
        ),
        pytest.param(
            lambda: functools.partial(GivingGetterPartialCall()),
            lambda subject: subject.func.__call__,
            _NAMED_AS_A_LINK,
            id="call-giving-it",
        ),
    ],
)
def test_a_partial_whose_type_takes_get_from_another_class_and_defines_no_set_raises_a_type_error_naming_it_and_its_type_wherever_inspect_reads_it(
    build: Callable[[], object], read_in: Callable[[object], object], naming: str
) -> None:
    subject = build()
    partial = read_in(subject)
    naming_it_and_its_type = naming.format(
        partial=re.escape(repr(partial)), kind=rf".*\.{type(partial).__qualname__}"
    ) + r"a functools\.partial whose type takes __get__ .*\b3\.11 and 3\.12\b.*\bfrom 3\.13\b"
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        surface_form(subject)
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        named_classes(subject)


def test_a_partial_whose_type_takes_get_from_another_class_but_defines_set_or_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it() -> None:
    signed = GetterPartial(_settled, rate=1)
    signed.__signature__ = inspect.Signature(
        [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float)]
    )

    assert (
        surface_form(SettableGetterPartial(_settled, rate=1))
        == "(self: object, share: float, *, rate: int = 1) -> None"
    )
    assert surface_form(signed) == "(share: float)"
    assert (
        surface_form(functools.partial(GetterPartial(_settled, rate=1)))
        == "(self: object, share: float, *, rate: int = 1) -> None"
    )


@pytest.mark.parametrize("kind", [GetterPartial, SettableGetterPartial])
def test_a_class_or_call_bound_through_a_partial_whose_type_takes_get_from_another_class_raises_a_type_error_naming_that_type_instead_of_the_binding_of_a_partial(
    kind: type,
) -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = kind(build, scale=2.0)

    class Calling(type):
        __call__ = kind(build, scale=2.0)

    class Called(metaclass=Calling):
        pass

    class CallingObject:
        __call__ = kind(build, scale=2.0)

    naming_that_type = (
        rf"a .*\.{kind.__qualname__}, a functools\.partial whose type takes __get__ from a "
        r"class other than functools\.partial\b"
    )
    for routine, site in (
        (Built, r"\.Built\b.* is constructed through .*\.Built\.__init__, "),
        (Called, r"\.Called\b.* is constructed through .*\.Calling\.__call__, "),
        (functools.partial(CallingObject()), r" is read through .*\.CallingObject\.__call__, "),
    ):
        with pytest.raises(TypeError, match=site + naming_that_type):
            surface_form(routine)
