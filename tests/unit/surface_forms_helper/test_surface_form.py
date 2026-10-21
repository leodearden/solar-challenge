# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form, one per test.

Wrapper and Ledger are defined at module level, where their qualified names carry no
'<locals>'.
"""

import collections.abc
import datetime
import decimal
import enum
import fractions
import functools
import inspect
import pathlib
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

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import Outer, Preset, imported_module


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

    naming_zip = r"\bbuiltins\.zip\b.*\bbuiltins\.zip\b"
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        named_classes(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(functools.partial(zipping, [1]))
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(Zipper().zipped)
    with pytest.raises(
        TypeError, match=r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(building)


def test_a_routine_that_wraps_a_class_but_carries_a_signature_is_spelled_by_that_signature() -> None:
    zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    zipping.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    assert surface_form(zipping) == "(rate: int)"


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


def test_a_constant_form_is_its_type_qualified_name() -> None:
    assert surface_form({"a": 1}) == "dict"
    assert surface_form((1, 2)) == "tuple"
    assert surface_form(Preset(rate=0.15)) == "Preset"
