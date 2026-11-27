# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_computed_once.py, the memo through which tests that ask for equal work share one computation."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from tests._computed_once import ComputedOnce


@dataclass
class _Fleet:
    """A plain mutable dataclass holding a list, so unhashable, as FleetConfig is."""

    homes: list[str]


class _CountingCompute:
    """A compute that logs each call's arguments and returns a fresh object, that call's own result."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.results: list[object] = []

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        result = object()
        self.results.append(result)
        return result


@pytest.mark.parametrize(
    "build_argument",
    [lambda: ["home"], lambda: _Fleet(homes=["home"])],
    ids=["list", "dataclass-holding-a-list"],
)
def test_equal_unhashable_arguments_are_computed_once_and_share_its_result(
    build_argument: Callable[[], object],
) -> None:
    compute = _CountingCompute()
    memo = ComputedOnce(compute)
    argument, equal_argument = build_argument(), build_argument()
    assert argument == equal_argument and argument is not equal_argument

    first = memo(argument, 3)
    second = memo(equal_argument, 3)

    assert compute.calls == [(argument, 3)]
    assert first is compute.results[0]
    assert second is first


def test_arguments_that_differ_in_one_position_are_computed_again() -> None:
    compute = _CountingCompute()
    memo = ComputedOnce(compute)

    three_days = memo(_Fleet(homes=["home"]), 3)
    one_day = memo(_Fleet(homes=["home"]), 1)

    assert compute.calls == [(_Fleet(homes=["home"]), 3), (_Fleet(homes=["home"]), 1)]
    assert three_days is compute.results[0]
    assert one_day is compute.results[1]


def test_a_repeat_of_an_earlier_call_computes_nothing_new() -> None:
    compute = _CountingCompute()
    memo = ComputedOnce(compute)
    three_days = memo(_Fleet(homes=["home"]), 3)
    one_day = memo(_Fleet(homes=["home"]), 1)

    assert memo(_Fleet(homes=["home"]), 3) is three_days
    assert memo(_Fleet(homes=["home"]), 1) is one_day
    assert len(compute.calls) == 2
