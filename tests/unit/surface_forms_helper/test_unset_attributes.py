# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's unset_attributes, one per test."""

import functools
import pathlib
import re
from dataclasses import dataclass, field
from typing import ClassVar

import pytest

from tests._surface_forms import member_forms, unset_attributes
from tests.unit.surface_forms_helper._fixtures import UNREADABLE_ROUTINES


def test_a_declared_attribute_member_forms_lists_that_the_source_never_sets_is_unset() -> None:
    class Meter:
        UNITS: ClassVar[str]
        site: pathlib.Path
        reading: float
        _level: float

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    @dataclass(frozen=True)
    class Reading:
        kwh: float

    assert unset_attributes(Meter) == {"reading"}
    assert unset_attributes(Reading) == set()


def test_a_declared_attribute_only_a_method_other_than_init_or_post_init_sets_is_unset() -> None:
    class Meter:
        reading: float

        def reset(self) -> None:
            self.reading = 0.0

    assert not hasattr(Meter(), "reading")
    assert unset_attributes(Meter) == {"reading"}


def test_a_name_the_class_body_only_annotates_as_a_class_variable_in_a_string_is_never_unset() -> None:
    class Meter:
        UNITS: "ClassVar[str]"
        reading: float

    assert unset_attributes(Meter) == {"reading"}


def test_a_dataclass_field_with_a_default_or_a_default_factory_is_never_unset() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        derived: float = field(init=False, default=0.0)
        history: list[float] = field(init=False, default_factory=list)
        label: str = field(init=False)
        note: str = field(init=False)

        def __post_init__(self) -> None:
            object.__setattr__(self, "label", f"{self.kwh} kWh")

    assert unset_attributes(Reading) == {"note"}


def test_a_default_factory_field_counts_as_supplied_even_when_a_hand_written_init_skips_it() -> None:
    @dataclass(init=False)
    class InitFalse:
        root: str
        history: list[float] = field(default_factory=list)

        def __init__(self, root: str) -> None:
            self.root = root

    @dataclass
    class BodyInit:
        root: str
        history: list[float] = field(init=False, default_factory=list)

        def __init__(self, root: str) -> None:
            self.root = root

    for cls in (InitFalse, BodyInit):
        assert member_forms(cls) == {"history": "attribute list[float]"}
        assert not hasattr(cls("data"), "history")
        assert unset_attributes(cls) == set()


def test_a_reviewed_write_under_a_computed_name_sets_no_declared_attribute() -> None:
    class Meter:
        reading: float

        def __init__(self, name: str) -> None:
            setattr(self, name, 0.0)

    assert unset_attributes(Meter, reviewed={"setattr(self, name, 0.0)"}) == {"reading"}


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
        unset_attributes(Meter)
