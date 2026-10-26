# SPDX-License-Identifier: AGPL-3.0-or-later
"""A clock that only the test moves, for code that reads the time on a clock it is given.

Code that takes its clock as a callable returning seconds, as a JobManager and a
JobStreamPolicy take one in place of time.monotonic, sees whatever passage of time the
test gives it, without the test sleeping for it.

Usage::

    from tests._manual_clock import ManualClock

    clock = ManualClock()
    manager = JobManager(storage, simulate_home=simulation, clock=clock)
    clock.advance(24 * 60 * 60.0)  # a day passes for the manager, at once
"""


class ManualClock:
    """Stands in for time.monotonic: it reads 0.0 seconds, and time stands still until advance() moves it on."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
