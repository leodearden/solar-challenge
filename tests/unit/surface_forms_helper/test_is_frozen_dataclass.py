# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's is_frozen_dataclass, one per test."""

import enum
from dataclasses import dataclass
from typing import NamedTuple

from tests._surface_forms import is_frozen_dataclass


def test_a_dataclass_decorated_frozen_is_a_frozen_dataclass() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

    @dataclass(order=True, unsafe_hash=True, frozen=True)
    class Rank:
        level: int

    assert is_frozen_dataclass(Reading)
    assert is_frozen_dataclass(Rank)


def test_a_dataclass_not_decorated_frozen_is_not_a_frozen_dataclass() -> None:
    @dataclass
    class Register:
        count: int

    @dataclass(eq=False)
    class Probe:
        site: str

    assert not is_frozen_dataclass(Register)
    assert not is_frozen_dataclass(Probe)


def test_an_undecorated_subclass_of_a_dataclass_reads_the_frozen_it_inherits() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

    @dataclass
    class Register:
        count: int

    class Scaled(Reading):
        def scaled(self, factor: float) -> float: ...

    class Tally(Register):
        def doubled(self) -> int: ...

    assert is_frozen_dataclass(Scaled)
    assert not is_frozen_dataclass(Tally)


def test_a_class_that_is_no_dataclass_is_not_a_frozen_dataclass() -> None:
    class Meter:
        site: str

    class Period(enum.Enum):
        PEAK = "peak"

    class Point(NamedTuple):
        x: float

    assert not is_frozen_dataclass(Meter)
    assert not is_frozen_dataclass(Period)
    assert not is_frozen_dataclass(Point)
