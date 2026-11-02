# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the classes an annotation names by its construct, and an object by its kind, one per test.

Gauge is defined at module level, where its forward reference to itself resolves in this
module's namespace.
"""

import collections.abc
import datetime
import enum
import functools
import pathlib
import re
import types
from dataclasses import InitVar
from typing import (
    Callable,
    List,
    Literal,
    NamedTuple,
    NoReturn,
    Optional,
    Self,
    Type,
    Union,
)

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import (
    REFUSED_ROUTINE_AND_PARTIAL_MEMBERS,
    RELABELLED_REFUSAL,
    Outer,
    Preset,
    Relabelled,
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


def test_literal_values_name_no_class() -> None:
    def f(a: Literal["Preset"], b: float) -> None: ...

    assert named_classes(f) == {float}


def test_a_special_form_names_no_class() -> None:
    def f(a: Self) -> NoReturn: ...

    assert named_classes(f) == set()


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


@pytest.mark.parametrize(("routine", "kind"), REFUSED_ROUTINE_AND_PARTIAL_MEMBERS)
def test_a_class_with_a_member_member_forms_refuses_raises_the_type_error_member_forms_raises_for_it(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        named_classes(Meter)


def test_a_named_tuple_whose_fields_holder_holds_no_tuple_of_strings_raises_the_type_error_member_forms_raises_for_it() -> None:
    with pytest.raises(TypeError, match=RELABELLED_REFUSAL):
        named_classes(Relabelled)


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


def test_a_string_annotation_evaluating_to_an_annotation_no_construct_reads_raises_a_type_error_naming_that_annotation_and_its_type() -> None:
    def f(value: "InitVar[int]") -> None: ...

    with pytest.raises(TypeError, match=r"dataclasses\.InitVar\[int\].*\bdataclasses\.InitVar\b"):
        named_classes(f)


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


def test_a_constant_names_its_type_and_the_classes_its_values_or_items_forms_name_but_never_a_keys_class() -> None:
    assert named_classes(Preset(rate=0.1)) == {Preset}
    assert named_classes({1: [2.0], 2: (Preset(rate=0.1),)}) == {
        dict,
        list,
        float,
        tuple,
        Preset,
    }
