# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's signature_closure, one per test.

Feeder, Tap and Tally are defined at module level, where their forward references to
each other resolve in this module's namespace.
"""

import pathlib
import re
from dataclasses import dataclass
from typing import NewType, TypeVar

import pytest

from tests._surface_forms import signature_closure
from tests.unit.surface_forms_helper._fixtures import REFUSED_ROUTINE_AND_PARTIAL_MEMBERS, Preset


@dataclass(frozen=True)
class Feeder:
    """A class whose constructor names Tap and whose only member names Tally, which names Feeder back."""

    tap: "Tap"

    def tally(self) -> "Tally": ...


@dataclass(frozen=True)
class Tap:
    site: pathlib.Path


class Tally:
    def feeder(self) -> Feeder: ...


def test_a_signature_closure_follows_each_class_it_finds_through_its_constructor_and_its_members() -> None:
    def supply(feeder: Feeder) -> None: ...

    assert signature_closure([supply], "tests") == {Feeder, Tap, Tally}


def test_a_signature_closure_leaves_out_a_root_class_but_follows_its_forms() -> None:
    def supply(feeder: Feeder, preset: Preset) -> None: ...

    assert signature_closure([supply, Feeder, Preset], "tests") == {Tap, Tally}


def test_a_signature_closure_holds_only_classes_the_package_defines() -> None:
    def supply(feeder: Feeder, site: pathlib.Path) -> float: ...

    assert signature_closure([supply], "tests.unit") == {Feeder, Tap, Tally}
    assert signature_closure([supply], "solar_challenge") == set()


def test_a_signature_closure_follows_the_classes_a_type_variable_or_a_new_type_carries() -> None:
    Supplied = TypeVar("Supplied", bound=Feeder)
    PresetId = NewType("PresetId", Preset)

    def supply(feeder: Supplied, preset: PresetId) -> Supplied: ...

    assert signature_closure([supply], "tests") == {Feeder, Tap, Tally, Preset}


@pytest.mark.parametrize(("routine", "kind"), REFUSED_ROUTINE_AND_PARTIAL_MEMBERS)
def test_a_class_with_a_member_member_forms_refuses_raises_the_type_error_member_forms_raises_for_it(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        signature_closure([Meter], "tests")
