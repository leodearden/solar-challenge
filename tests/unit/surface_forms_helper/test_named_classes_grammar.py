# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the classes an annotation names by its construct, and an object by its kind, one per test.

Gauge is defined at module level, where its forward reference to itself resolves in this
module's namespace.
"""

import collections
import collections.abc
import datetime
import enum
import fractions
import functools
import pathlib
import re
import sys
import types
from dataclasses import InitVar, dataclass
from typing import (
    Annotated,
    Callable,
    List,
    Literal,
    NamedTuple,
    NewType,
    NoReturn,
    Optional,
    ParamSpec,
    Self,
    Type,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
)

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    UNREADABLE_ROUTINES,
    Outer,
    Preset,
    imported_module,
)


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


def test_a_routine_cpython_defines_in_c_names_no_class() -> None:
    assert named_classes(str.join) == set()
    assert named_classes(", ".join) == set()
    assert named_classes(vars(dict)["fromkeys"]) == set()
    assert named_classes(object.__init__) == set()
    assert named_classes((1).__add__) == set()


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


@pytest.mark.parametrize(
    ("routine", "kind"),
    [
        *UNREADABLE_ROUTINES,
        pytest.param(functools.partial(round, ndigits=1), "functools.partial", id="partial"),
    ],
)
def test_a_class_with_a_member_member_forms_refuses_raises_the_type_error_member_forms_raises_for_it(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        named_classes(Meter)


def test_a_type_variable_or_a_new_type_inside_its_own_declaration_names_no_class_there(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linking = imported_module(
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


def test_a_forward_reference_inside_its_own_evaluation_names_no_class_there(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = imported_module(
        tmp_path,
        monkeypatch,
        "documents",
        "from typing import Union\n"
        "\n"
        "JSON = Union[dict[str, 'JSON'], list['JSON'], str, None]\n"
        "Tree = tuple[int, 'Forest']\n"
        "Forest = list['Tree']\n"
        "\n"
        "def store(document: JSON) -> None: ...\n"
        "\n"
        "def send(document: 'JSON') -> None: ...\n"
        "\n"
        "def plant(tree: Tree) -> None: ...\n",
    )

    assert named_classes(documents.store) == {dict, str, list}
    assert named_classes(documents.send) == {dict, str, list}
    assert named_classes(documents.plant) == {tuple, int, list}


def test_a_forward_reference_inside_its_own_evaluation_names_the_class_another_module_evaluating_it_binds_it_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "sharing",
        "from fractions import Fraction as Ratio\n"
        "from typing import NewType\n"
        "\n"
        "Share = NewType('Share', 'Ratio')\n",
    )
    pooling = imported_module(
        tmp_path,
        monkeypatch,
        "pooling",
        "from typing import Union\n"
        "\n"
        "import sharing\n"
        "\n"
        "Ratio = Union[sharing.Share, list['Ratio']]\n"
        "\n"
        "def pool(ratio: 'Ratio') -> None: ...\n",
    )

    assert named_classes(pooling.pool) == {fractions.Fraction, list}


def test_a_default_value_names_no_class() -> None:
    def f(at: object = Preset(rate=0.1)) -> None: ...

    assert named_classes(f) == {object}


def test_an_enum_names_its_methods_classes_but_not_its_members() -> None:
    class Period(enum.Enum):
        PEAK = 1.5

        def label(self) -> str: ...

    assert named_classes(Period) == {str}


def test_a_named_tuple_names_the_classes_its_constructor_annotates_its_fields_with_not_the_class_of_their_descriptors() -> None:
    class Reading(NamedTuple):
        site: pathlib.Path
        preset: Optional[Preset] = None

    assert named_classes(Reading) == {pathlib.Path, Preset}


def test_a_constant_names_its_type() -> None:
    assert named_classes({"a": 1}) == {dict}
    assert named_classes(Preset(rate=0.1)) == {Preset}
