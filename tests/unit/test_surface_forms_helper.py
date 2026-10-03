# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_surface_forms.py, the spelling of a public name's surface form that every admitted Python minor shares.

Each test pins one spelling rule, so an edit that lets one minor's own rendering through,
or drops part of a signature, fails here instead of turning the frozen-surface lock red
on one interpreter or blind to a real change.

The annotations below are evaluated, as in the modules they stand in for, so this module
does not import annotations from __future__. The classes whose qualified names are
asserted are defined at module level, where a qualified name carries no '<locals>'.
"""

import collections.abc
import datetime
import enum
import pathlib
from dataclasses import dataclass, field
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    ParamSpec,
    Tuple,
    Union,
)

from tests._surface_forms import surface_form


class Outer:
    class Inner:
        pass


@dataclass(frozen=True)
class Preset:
    rate: float


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
        a: List, b: Dict, c: Tuple, d: Callable, e: list, f: collections.abc.Callable
    ) -> None: ...

    assert (
        surface_form(bare)
        == "(a: list, b: dict, c: tuple, d: Callable, e: list, f: Callable) -> None"
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
