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

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests._package_modules import top_level_modules

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
