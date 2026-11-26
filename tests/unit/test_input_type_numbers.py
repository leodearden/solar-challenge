# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 1: every input type refuses a number that is not a finite number by name, and every other numeric dataclass is classified with its reason.

A numeric dataclass is one a module directly under solar_challenge defines at its top level, with a field whose
annotation mentions int or float at any depth. An input type is one whose numbers a user gives: a scenario file, a web
request or a library caller. Constructing one with NaN, ±inf, True or a non-number in any numeric field, or with a
fraction in a whole-number field, raises ConfigurationError naming the field and the value. INPUT_TYPES gives each
input type a factory of a valid instance; NOT_INPUT_TYPES gives every other numeric dataclass the reason it carries no
such contract, and EXCLUDED_FIELDS each numeric field of an input type that is not tried (docs/prds/finite-quantities.md
§5.6 and §7).
"""

import dataclasses
import importlib.util
import math
import re
import sys
import typing
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import ModuleType

import pytest

from tests._exemption_reasons import Permanent, Transitional
from tests._package_modules import module_level_dataclasses, top_level_modules

_BAD_NUMBERS: tuple[object, ...] = (math.nan, math.inf, -math.inf, True, "x")

#: Each input type's dotted name, to a factory of a valid instance of it.
INPUT_TYPES: Mapping[str, Callable[[], object]] = {}

#: Each other numeric dataclass's dotted name, to the reason it refuses no bad number by name.
NOT_INPUT_TYPES: Mapping[str, Permanent] = {}

#: Each numeric field of an input type that is not tried, as (dotted name, field), to the reason.
EXCLUDED_FIELDS: Mapping[tuple[str, str], Permanent | Transitional] = {}

_NUMBER_TYPES_BY_NAME: Mapping[str, type] = {"int": int, "float": float}

_NUMBER_TYPE_NAME = re.compile(r"\b(int|float)\b")


def number_types(annotation: object) -> frozenset[type]:
    """Return int and float, each if *annotation* mentions it at any depth: in its text, its arguments or a Callable's parameter list, but not in a Literal's values; bool is not int here."""
    if isinstance(annotation, type) and annotation in _NUMBER_TYPES_BY_NAME.values():
        return frozenset({annotation})
    if isinstance(annotation, typing.ForwardRef):
        return number_types(annotation.__forward_arg__)
    if isinstance(annotation, str):
        return frozenset(_NUMBER_TYPES_BY_NAME[name] for name in _NUMBER_TYPE_NAME.findall(annotation))
    if typing.get_origin(annotation) is typing.Literal:
        return frozenset()
    items = annotation if isinstance(annotation, list) else typing.get_args(annotation)
    return frozenset().union(*(number_types(item) for item in items))


def numeric_fields(cls: type) -> dict[str, frozenset[type]]:
    """Return the number types each numeric field of the dataclass *cls* mentions, in field order.

    Its hints are resolved where they can be, and read as each field's annotation text where a name imported under
    TYPE_CHECKING leaves them unresolvable.
    """
    fields = dataclasses.fields(cls)
    try:
        hints = typing.get_type_hints(cls)
    except NameError:
        hints = {field.name: field.type for field in fields}
    types_by_field = {field.name: number_types(hints[field.name]) for field in fields}
    return {name: types for name, types in types_by_field.items() if types}


def numeric_dataclasses(modules: Iterable[ModuleType]) -> dict[str, type]:
    """Return each dataclass the *modules* define at their top level with a numeric field, keyed by its dotted name."""
    return {
        f"{cls.__module__}.{cls.__qualname__}": cls
        for module in modules
        for cls in module_level_dataclasses(module)
        if numeric_fields(cls)
    }


def unclassified(discovered: Iterable[str]) -> list[str]:
    """Return a message for each of the *discovered* dotted names in neither INPUT_TYPES nor NOT_INPUT_TYPES, sorted."""
    tried_with = ", ".join(repr(bad) for bad in _BAD_NUMBERS)
    return [
        f"{name} has a numeric field but is in neither INPUT_TYPES nor NOT_INPUT_TYPES: classify it, in INPUT_TYPES"
        " with a factory of a valid instance if a user gives its numbers (a scenario file, a web request or a library"
        f" caller), so each numeric field is tried with {tried_with}, or in NOT_INPUT_TYPES with the reason it carries"
        " no such contract"
        for name in sorted(discovered)
        if name not in INPUT_TYPES and name not in NOT_INPUT_TYPES
    ]


_SEEDED_MODULE_NAME = "seeded_numeric_dataclasses"

_SEEDED_SOURCE = '''
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from decimal import Decimal


@dataclass(frozen=True)
class SeededRate:
    rate: Optional[float]
    counts: tuple[int, ...]
    share: int | float
    label: str
    flag: bool
    other: Decimal | None = None


@dataclass
class SeededLabel:
    label: str
    flag: bool


class NotADataclass:
    rate: float
'''


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A module defining one numeric dataclass, whose hints a TYPE_CHECKING import leaves unresolvable, beside a dataclass with no numeric field and a plain class with one."""
    path = tmp_path / f"{_SEEDED_MODULE_NAME}.py"
    path.write_text(_SEEDED_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(_SEEDED_MODULE_NAME, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, _SEEDED_MODULE_NAME, module)
    spec.loader.exec_module(module)
    return module


def test_discovery_finds_a_dataclass_with_a_numeric_field_in_any_annotation_even_when_its_hints_cannot_be_resolved(
    seeded: ModuleType,
) -> None:
    seeded_rate = seeded.SeededRate

    assert numeric_dataclasses([seeded]) == {f"{seeded.__name__}.SeededRate": seeded_rate}
    assert numeric_fields(seeded_rate) == {
        "rate": frozenset({float}),
        "counts": frozenset({int}),
        "share": frozenset({int, float}),
    }


def test_top_level_modules_are_the_modules_directly_under_the_package() -> None:
    names = {module.__name__ for module in top_level_modules()}

    assert {"solar_challenge.pv", "solar_challenge.number_fields"} <= names
    assert [name for name in names if name.split(".")[1] in {"web", "cli"}] == []


def test_an_unclassified_numeric_dataclass_is_reported_by_name_with_the_classification_instruction(
    seeded: ModuleType,
) -> None:
    messages = unclassified(numeric_dataclasses([seeded]))

    assert len(messages) == 1, messages
    for part in (f"{seeded.__name__}.SeededRate", "INPUT_TYPES", "NOT_INPUT_TYPES", "classify it"):
        assert part in messages[0], messages[0]
