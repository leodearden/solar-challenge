# SPDX-License-Identifier: AGPL-3.0-or-later
"""A memo that computes once per distinct set of arguments, so tests that ask for equal work share one result.

Arguments are compared with ==, never hashed, so a plain mutable dataclass such as FleetConfig can be one.
A test that shares a result must only read it.

Usage::

    from tests._computed_once import ComputedOnce

    @pytest.fixture(scope="module")
    def june_fleet_run() -> ComputedOnce[FleetResults]:
        return ComputedOnce(_simulate_june_days)

    def test_fleet_summary(june_fleet_run, fleet_config):
        results = june_fleet_run(fleet_config, 3)  # simulated by the first test that asks, shared by the rest
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

_Result = TypeVar("_Result")


class ComputedOnce(Generic[_Result]):
    """*compute*'s result for each distinct set of positional arguments, computed by the first call that passes them.

    Each call's arguments and result are kept, not copied, so no caller may change either.
    """

    def __init__(self, compute: Callable[..., _Result]) -> None:
        self._compute = compute
        self._computed: list[tuple[tuple[object, ...], _Result]] = []

    def __call__(self, *args: object) -> _Result:
        """The result computed for the first call whose arguments equal *args*, or *compute*'s for them now if none did."""
        for computed_args, result in self._computed:
            if computed_args == args:
                return result
        result = self._compute(*args)
        self._computed.append((args, result))
        return result
