# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for how an annotation is spelled by its construct, and an object by its kind, one per test.

The module a string annotation is evaluated in, and the errors raised where it cannot be
evaluated there, have their rules in
tests/unit/surface_forms_helper/test_surface_form_module_lookup.py.

Wrapper, the classes whose __match_args__ is refused, and the classes whose instances do
or do not hold a __dict__, are defined at module level, where their qualified names carry
no '<locals>' and a parametrize decorator can reach them.
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


class PositionalMeter:
    """A class whose constructor takes site, then rate, positionally."""

    def __init__(self, site: str, rate: float = 0.0) -> None: ...


class MatchesFewer(PositionalMeter):
    __match_args__ = ("site",)


class MatchesReordered(PositionalMeter):
    __match_args__ = ("rate", "site")


class MatchesByList(PositionalMeter):
    __match_args__ = ["site", "rate"]


@dataclass(init=False)
class HandOrdered:
    """A dataclass whose __match_args__ names its fields, site then rate, while its hand-written constructor takes rate, then site."""

    site: str
    rate: float

    def __init__(self, rate: float, site: str) -> None: ...


class Sited:
    """A class whose constructor takes site, and whose instances hold a __dict__."""

    def __init__(self, site: str) -> None: ...


class SlottedSite:
    __slots__ = ("site",)

    def __init__(self, site: str) -> None: ...


class WeakSlottedSite:
    __slots__ = ("site", "__weakref__")

    def __init__(self, site: str) -> None: ...


class EmptySlotsBesideADict(Sited):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class SlottedReading:
    kwh: float


@dataclass(frozen=True, slots=True, weakref_slot=True)
class WeakSlottedReading:
    kwh: float


@dataclass(slots=True, match_args=False, kw_only=True)
class QuietSlottedReading:
    kwh: float


class UndecoratedUnderASlottedReading(SlottedReading):
    pass


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


def test_a_parameter_default_is_spelled_as_ascii_writes_it() -> None:
    def f(
        band: str = "\U0001F6DC", label="\xe9", *, pair: tuple[str, int] = ("\xe9", 1)
    ) -> None: ...

    @dataclass(frozen=True)
    class Tag:
        label: str = "\xe9"

    assert (
        surface_form(f)
        == "(band: str = '\\U0001f6dc', label='\\xe9', *, pair: tuple[str, int] = ('\\xe9', 1)) -> None"
    )
    assert surface_form(Tag) == "dataclass[eq, frozen, match_args] (label: str = '\\xe9') -> None"


def test_an_optional_or_a_union_is_spelled_with_bars() -> None:
    def f(a: Optional[int], b: Union[int, str], c: int | None) -> None: ...

    assert surface_form(f) == "(a: int | None, b: int | str, c: int | None) -> None"


def test_a_signature_is_spelled_alike_whether_its_module_imports_annotations_from_future_quotes_an_annotation_or_writes_optional_for_a_union_with_none(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "from typing import Optional\n"
        "\n"
        "class A: ...\n"
        "\n"
        'def f(a: Optional[A], b: A | None, c: "Optional[A]"): ...\n'
    )
    unionspelling = imported_module(tmp_path, monkeypatch, "unionspelling", source)
    futureunionspelling = imported_module(
        tmp_path,
        monkeypatch,
        "futureunionspelling",
        "from __future__ import annotations\n" + source,
    )

    assert surface_form(unionspelling.f) == "(a: A | None, b: A | None, c: A | None)"
    assert surface_form(futureunionspelling.f) == "(a: A | None, b: A | None, c: A | None)"


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


def test_a_string_annotation_is_spelled_as_what_it_evaluates_to_in_the_module_that_spells_it() -> None:
    def f(a: "Optional[Preset]", b: "'Preset'", c: "Optional[int]") -> "Preset": ...

    assert surface_form(f) == "(a: Preset | None, b: Preset, c: int | None) -> Preset"


def test_a_forward_reference_inside_an_alias_is_spelled_as_what_it_evaluates_to() -> None:
    def f(a: Optional["Preset"], b: List["pathlib.Path"], c: list["Optional[int]"]) -> None: ...

    assert surface_form(f) == "(a: Preset | None, b: list[Path], c: list[int | None]) -> None"


def test_a_string_met_again_inside_its_own_evaluation_raises_a_type_error_naming_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spelledrecursion = imported_module(
        tmp_path,
        monkeypatch,
        "spelledrecursion",
        "from typing import Union\n"
        "\n"
        "JSON = Union[dict[str, 'JSON'], list['JSON'], str, None]\n"
        "\n"
        "def store(document: JSON) -> None: ...\n"
        "\n"
        "def send(document: 'JSON') -> None: ...\n",
    )

    met_again = r"'JSON', read in the module 'spelledrecursion', is met again inside its own evaluation\b"
    with pytest.raises(TypeError, match=met_again):
        surface_form(spelledrecursion.store)
    with pytest.raises(TypeError, match=met_again):
        surface_form(spelledrecursion.send)


def test_a_string_met_again_outside_its_own_evaluation_is_spelled_as_what_it_evaluates_to_each_time() -> None:
    def f(
        a: dict["Preset", "Preset"], b: "tuple['Preset', 'Preset']", c: Tuple["Preset", "Preset"]
    ) -> None: ...

    assert surface_form(f) == (
        "(a: dict[Preset, Preset], b: tuple[Preset, Preset], c: tuple[Preset, Preset]) -> None"
    )


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


def test_a_literal_is_spelled_with_its_values_as_ascii_writes_them() -> None:
    def f(sharing_mode: Literal["p2p", "community_battery"]) -> None: ...

    def band(wireless: Literal["\U0001F6DC", "\xe9"]) -> None: ...

    assert (
        surface_form(f) == "(sharing_mode: Literal['p2p', 'community_battery']) -> None"
    )
    assert surface_form(band) == "(wireless: Literal['\\U0001f6dc', '\\xe9']) -> None"


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
        == "dataclass[eq, frozen, match_args] (x: float, tags: list[str] = <factory>, label: str = '') -> None"
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

    assert surface_form(Register) == "dataclass[eq, match_args] (count: int) -> None"
    assert surface_form(Reading) == "dataclass[eq, frozen, match_args] (kwh: float) -> None"
    assert (
        surface_form(Rank)
        == "dataclass[eq, order, unsafe_hash, frozen, match_args] (level: int) -> None"
    )
    assert surface_form(Probe) == "dataclass[match_args] (site: str) -> None"


def test_a_dataclass_kind_lists_match_args_when_its_match_args_names_its_constructors_positional_parameters() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        site: str = ""

    @dataclass(match_args=False)
    class Unmatched:
        kwh: float

    @dataclass(kw_only=True)
    class Keyed:
        kwh: float

    @dataclass
    class Empty:
        pass

    assert surface_form(Reading) == "dataclass[eq, frozen, match_args] (kwh: float, site: str = '') -> None"
    assert surface_form(Unmatched) == "dataclass[eq] (kwh: float) -> None"
    assert surface_form(Keyed) == "dataclass[eq] (*, kwh: float) -> None"
    assert surface_form(Empty) == "dataclass[eq] () -> None"


def test_a_class_other_than_a_dataclass_is_spelled_with_the_kind_class_only_when_it_has_a_qualifier() -> None:
    class Matched:
        __match_args__ = ("site", "rate")

        def __init__(self, site: str, rate: float = 0.0) -> None: ...

    class Unmatched:
        def __init__(self, site: str, rate: float = 0.0) -> None: ...

    assert surface_form(Matched) == "class[match_args] (site: str, rate: float = 0.0) -> None"
    assert surface_form(Unmatched) == "(site: str, rate: float = 0.0) -> None"


@pytest.mark.parametrize(
    ("cls", "naming_it_what_it_holds_and_those_parameters"),
    [
        pytest.param(
            MatchesFewer,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.MatchesFewer\.__match_args__\b"
            r".*\('site',\).*\('site', 'rate'\)",
            id="fewer-names",
        ),
        pytest.param(
            MatchesReordered,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.MatchesReordered\.__match_args__\b"
            r".*\('rate', 'site'\).*\('site', 'rate'\)",
            id="reordered-names",
        ),
        pytest.param(
            MatchesByList,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.MatchesByList\.__match_args__\b"
            r".*\['site', 'rate'\].*\('site', 'rate'\)",
            id="list-of-the-names",
        ),
        pytest.param(
            HandOrdered,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_grammar\.HandOrdered\.__match_args__\b"
            r".*\('site', 'rate'\).*\('rate', 'site'\)",
            id="dataclass-fields-not-its-hand-written-constructors-parameters",
        ),
    ],
)
def test_a_class_whose_match_args_is_neither_empty_nor_its_constructors_positional_parameters_raises_a_type_error_naming_it_what_it_holds_and_those_parameters(
    cls: type, naming_it_what_it_holds_and_those_parameters: str
) -> None:
    with pytest.raises(TypeError, match=naming_it_what_it_holds_and_those_parameters):
        surface_form(cls)


def test_a_dataclass_kind_lists_neither_init_repr_nor_kw_only() -> None:
    @dataclass(repr=False, kw_only=True)
    class Quiet:
        kwh: float

    @dataclass(init=False)
    class Meter:
        site: str

        def __init__(self, site: str) -> None: ...

    assert surface_form(Quiet) == "dataclass[eq] (*, kwh: float) -> None"
    assert surface_form(Meter) == "dataclass[eq, match_args] (site: str) -> None"


@pytest.mark.parametrize(
    ("cls", "form"),
    [
        pytest.param(SlottedSite, "class[slots] (site: str) -> None", id="slots"),
        pytest.param(
            WeakSlottedSite, "class[slots, weakref_slot] (site: str) -> None", id="slots-and-weakref"
        ),
        pytest.param(
            SlottedReading,
            "dataclass[eq, frozen, match_args, slots] (kwh: float) -> None",
            id="slots-dataclass",
        ),
        pytest.param(
            WeakSlottedReading,
            "dataclass[eq, frozen, match_args, slots, weakref_slot] (kwh: float) -> None",
            id="weakref-slot-dataclass",
        ),
        pytest.param(
            QuietSlottedReading,
            "dataclass[eq, slots] (*, kwh: float) -> None",
            id="slots-dataclass-without-match-args",
        ),
    ],
)
def test_a_class_whose_instances_hold_no_dict_lists_slots_then_weakref_slot_if_they_take_a_weakref(
    cls: type, form: str
) -> None:
    assert surface_form(cls) == form


@pytest.mark.parametrize(
    ("cls", "form"),
    [
        pytest.param(EmptySlotsBesideADict, "(site: str) -> None", id="empty-slots-beside-a-bases-dict"),
        pytest.param(
            UndecoratedUnderASlottedReading,
            "dataclass[eq, frozen, match_args] (kwh: float) -> None",
            id="undecorated-subclass-of-a-slots-dataclass",
        ),
    ],
)
def test_a_class_whose_instances_hold_a_dict_lists_no_slots_whatever_slots_its_own_body_or_its_decorator_sets(
    cls: type, form: str
) -> None:
    assert surface_form(cls) == form


def test_a_class_whose_instances_hold_a_dict_but_take_no_weakref_raises_a_type_error_naming_it() -> None:
    class Band(tuple):
        def __new__(cls, low: float, high: float):
            return super().__new__(cls, (low, high))

    with pytest.raises(TypeError, match=r"<locals>\.Band\b"):
        surface_form(Band)


def test_an_undecorated_subclass_of_a_dataclass_is_spelled_with_the_kind_it_inherits() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

    class Scaled(Reading):
        def scaled(self, factor: float) -> float: ...

    assert surface_form(Scaled) == "dataclass[eq, frozen, match_args] (kwh: float) -> None"


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


def test_an_enum_form_spells_each_members_value_as_ascii_writes_it() -> None:
    class Band(enum.Enum):
        WIFI = "\U0001F6DC"
        ACUTE = "\xe9"
        PAIR = ("\xe9", 1)

    assert surface_form(Band) == "WIFI='\\U0001f6dc', ACUTE='\\xe9', PAIR=('\\xe9', 1)"


def test_a_constant_that_is_no_mapping_list_or_tuple_is_spelled_by_its_types_qualified_name() -> None:
    assert surface_form(Preset(rate=0.15)) == "Preset"
    assert surface_form("kWh") == "str"
    assert surface_form(frozenset({1})) == "frozenset"


def test_a_mapping_constant_is_spelled_by_its_type_then_its_entries_in_iteration_order_each_key_as_ascii_writes_it_and_each_value_by_its_form() -> None:
    assert (
        surface_form({"Octopus": Preset(rate=4.1), "OVO": Preset(rate=4.0), 3: 0.5})
        == "dict {'Octopus': Preset, 'OVO': Preset, 3: float}"
    )
    assert surface_form(types.MappingProxyType({"peak": 0.3})) == "mappingproxy {'peak': float}"
    assert surface_form(collections.OrderedDict(b=1, a="x")) == "OrderedDict {'b': int, 'a': str}"
    assert surface_form({}) == "dict {}"
    assert surface_form({"\xe9": 1}) == "dict {'\\xe9': int}"


def test_a_str_key_holding_a_character_a_newer_unicode_database_assigns_is_spelled_with_its_escape_on_every_minor() -> None:
    assert surface_form({"\U0001F6DC": 1}) == "dict {'\\U0001f6dc': int}"


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


def test_a_mapping_keys_type_error_names_the_key_types_a_form_spells() -> None:
    with pytest.raises(TypeError, match=r"\bstr, int, float, bool, NoneType\b"):
        surface_form({object(): 1})


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
