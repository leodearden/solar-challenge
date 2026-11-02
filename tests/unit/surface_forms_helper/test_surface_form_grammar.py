# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for how an annotation is spelled by its construct, and an object by its kind, one per test.

Wrapper is defined at module level, where its qualified name carries no '<locals>'.
"""

import collections
import collections.abc
import datetime
import enum
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
)

import pytest

from tests._surface_forms import member_forms, named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGetterDeleter,
    GetterDeleter,
    Outer,
    Preset,
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


def test_a_special_form_is_spelled_by_its_repr() -> None:
    def f(a: Self, b: LiteralString) -> Never: ...

    assert surface_form(f) == "(a: typing.Self, b: typing.LiteralString) -> typing.Never"


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


@pytest.mark.parametrize(
    ("annotation", "naming_it_and_its_type"),
    [
        pytest.param(
            Wrapper[Preset],
            r"Wrapper\[Preset\].*\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.Wrapper\b",
            id="wrapper",
        ),
        pytest.param(
            InitVar[int], r"dataclasses\.InitVar\[int\].*\bdataclasses\.InitVar\b", id="init-var"
        ),
        pytest.param(TypeVar("Rated"), r"~Rated\b.*\btyping\.TypeVar\b", id="type-variable"),
        pytest.param(ParamSpec("Hook"), r"~Hook\b.*\btyping\.ParamSpec\b", id="param-spec"),
        pytest.param(
            TypeVarTuple("Shape"),
            r"\bShape\b.*\btyping\.TypeVarTuple\b",
            id="type-variable-tuple",
        ),
        pytest.param(
            NewType("Kwh", float),
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.Kwh\b.*\btyping\.NewType\b",
            id="new-type",
        ),
        pytest.param(
            Annotated[int, 1],
            r"typing\.Annotated\[int, 1\].*\btyping\._AnnotatedAlias\b",
            id="annotated",
        ),
        pytest.param(
            Annotated[float, "kW"],
            r"typing\.Annotated\[float, 'kW'\].*\btyping\._AnnotatedAlias\b",
            id="annotated-string-metadata",
        ),
        pytest.param(
            ParamSpec("Hook").args,
            r"\bHook\.args\b.*\btyping\.ParamSpecArgs\b",
            id="param-spec-args",
        ),
        pytest.param(
            ParamSpec("Hook").kwargs,
            r"\bHook\.kwargs\b.*\btyping\.ParamSpecKwargs\b",
            id="param-spec-kwargs",
        ),
    ],
)
def test_an_annotation_no_construct_reads_raises_a_type_error_naming_it_and_its_type(
    annotation: object, naming_it_and_its_type: str
) -> None:
    def f(value: annotation) -> None: ...

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


def test_an_enum_form_is_its_members_in_definition_order() -> None:
    class Period(enum.Enum):
        PEAK = "peak"
        OFF_PEAK = "off_peak"

    assert surface_form(Period) == "PEAK='peak', OFF_PEAK='off_peak'"


def test_an_enum_form_lists_its_aliases_in_definition_order_each_with_the_value_of_the_member_it_names() -> None:
    class Rate(enum.Enum):
        A = 1
        B = 1
        C = 2

    class Access(enum.Flag):
        READ = 4
        WRITE = 2
        READ_WRITE = 6

    assert surface_form(Rate) == "A=1, B=1, C=2"
    assert surface_form(Access) == "READ=4, WRITE=2, READ_WRITE=6"


def test_a_constant_that_is_no_mapping_list_or_tuple_is_spelled_by_its_types_qualified_name() -> None:
    assert surface_form(Preset(rate=0.15)) == "Preset"
    assert surface_form("kWh") == "str"
    assert surface_form(frozenset({1})) == "frozenset"


def test_a_mapping_constant_is_spelled_by_its_type_then_its_entries_in_iteration_order_each_key_by_its_repr_and_each_value_by_its_form() -> None:
    assert (
        surface_form({"Octopus": Preset(rate=4.1), "OVO": Preset(rate=4.0), 3: 0.5})
        == "dict {'Octopus': Preset, 'OVO': Preset, 3: float}"
    )
    assert surface_form(types.MappingProxyType({"peak": 0.3})) == "mappingproxy {'peak': float}"
    assert surface_form(collections.OrderedDict(b=1, a="x")) == "OrderedDict {'b': int, 'a': str}"
    assert surface_form({}) == "dict {}"


def test_a_mapping_key_whose_type_is_not_exactly_str_int_float_bool_or_none_raises_a_type_error_naming_that_type() -> None:
    class Level(enum.IntEnum):
        LOW = 1

    assert surface_form({0.5: 1, True: 2, None: 3}) == "dict {0.5: int, True: int, None: int}"
    with pytest.raises(
        TypeError, match=r"\btests\.unit\.surface_forms_helper\._fixtures\.Preset\b"
    ):
        surface_form({Preset(rate=0.1): 1})
    with pytest.raises(TypeError, match=r"\bbuiltins\.object\b"):
        surface_form({"rates": {object(): 1}})
    with pytest.raises(TypeError, match=r"<locals>\.Level\b"):
        named_classes({Level.LOW: 1})


def test_a_list_or_tuple_constant_is_spelled_by_its_type_then_its_items_forms_in_order() -> None:
    assert surface_form([1.0, "kWh", Preset(rate=0.1)]) == "list [float, str, Preset]"
    assert surface_form((Outer.Inner(),)) == "tuple [Outer.Inner]"
    assert surface_form(()) == "tuple []"


def test_an_instance_of_a_list_tuple_or_mapping_subclass_is_spelled_by_its_type_then_its_items_or_entries_as_its_bases_is() -> None:
    class Readings(list):
        pass

    class Span(tuple):
        pass

    class Rates(dict):
        pass

    assert surface_form(Readings([0.5] * 48)) == f"{Readings.__qualname__} [float × 48]"
    assert surface_form(Span((0, 1.5))) == f"{Span.__qualname__} [int, float]"
    assert surface_form(Rates(a=0.1, b=0.2)) == f"{Rates.__qualname__} {{'a': float, 'b': float}}"
    assert named_classes(Readings([0.5])) == {Readings, float}


def test_a_named_tuple_instance_or_an_enum_member_is_spelled_by_its_types_qualified_name_alone_even_if_it_is_a_list_tuple_or_mapping() -> None:
    class Window(typing.NamedTuple):
        start: int
        end: float

    class Slot(Window):
        pass

    Pair = collections.namedtuple("Pair", "x y")

    class Band(tuple, enum.Enum):
        LOW = (0.0, 0.1)

    class Steps(list, enum.Enum):
        A = [1, 2]

    class Tier(dict, enum.Enum):
        LOW = {"rate": 0.1}

    assert surface_form(Window(1, 2.0)) == Window.__qualname__
    assert surface_form(Slot(1, 2.0)) == Slot.__qualname__
    assert surface_form(Pair(1, 2)) == Pair.__qualname__
    assert surface_form(Band.LOW) == Band.__qualname__
    assert surface_form(Steps.A) == Steps.__qualname__
    assert surface_form(Tier.LOW) == Tier.__qualname__
    assert named_classes(Window(1, 2.0)) == {Window}
    assert named_classes(Tier.LOW) == {Tier}


def test_a_run_of_equal_item_forms_in_a_list_or_tuple_is_spelled_once_with_its_count() -> None:
    assert surface_form([0.012] * 48) == "list [float × 48]"
    assert surface_form((1, 2, "a", 3)) == "tuple [int × 2, str, int]"


def test_a_value_a_constant_holds_is_spelled_by_the_rules_of_a_constant() -> None:
    assert (
        surface_form({"bands": [(0.1, 0.9)], "rates": {"peak": 0.3}})
        == "dict {'bands': list [tuple [float × 2]], 'rates': dict {'peak': float}}"
    )


def test_a_list_tuple_or_mapping_a_constant_holds_inside_itself_raises_a_type_error_naming_its_type() -> None:
    class Growing(list):
        pass

    looped: list[object] = [1.0]
    looped.append(looped)
    grown = Growing()
    grown.append(grown)
    keyed: dict[str, object] = {}
    keyed["self"] = (keyed,)
    shared = [0.5]

    assert surface_form((shared, shared)) == "tuple [list [float] × 2]"
    with pytest.raises(TypeError, match=r"\bbuiltins\.list held in a constant holds itself\b"):
        surface_form(looped)
    with pytest.raises(TypeError, match=r"<locals>\.Growing held in a constant holds itself\b"):
        surface_form(grown)
    with pytest.raises(TypeError, match=r"\bbuiltins\.dict held in a constant holds itself\b"):
        named_classes(keyed)


def test_a_class_or_routine_a_constant_holds_raises_a_type_error_naming_it() -> None:
    with pytest.raises(
        TypeError, match=r"\btests\.unit\.surface_forms_helper\._fixtures\.Preset\b"
    ):
        surface_form({"preset": Preset})
    with pytest.raises(TypeError, match=r"\bbuiltins\.len\b"):
        surface_form([len])
    with pytest.raises(TypeError, match=r"\bbuiltins\.len\b"):
        named_classes((len,))


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
