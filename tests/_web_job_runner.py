# SPDX-License-Identifier: AGPL-3.0-or-later
"""The runner a test's JobManager runs its jobs through, over a home simulator the test gives it, and the job-manager factory built on that runner.

runner_of(home_simulator) runs each home through home_simulator in turn, in the test's own
process, on weather that answers every location with an empty frame, which the fake home
simulators ignore. jobs_running(home_simulator, **manager_options) builds a JobManager over a
RunStorage with that runner, the factory create_app's jobs parameter takes. NewJobManager and
NewJobManagerWithRunner are the types of tests/unit/conftest.py's new_job_manager and
new_job_manager_with_runner fixtures.

Importing this module needs no web extra: solar_challenge.web.jobs imports no Flask.

Usage::

    from tests._web_job_runner import jobs_running, runner_of

    manager = JobManager(storage, runner=runner_of(simulation), max_workers=1)
    jobs = jobs_running(simulation, max_workers=1)
    same_kind_of_manager = jobs(storage)
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from solar_challenge.fleet import FleetRunner, FleetSimulator, HomeSimulator
from solar_challenge.location import Location
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RunStorage


@dataclass(frozen=True)
class _NoWeather:
    """A WeatherProvider for home simulators that read no weather: every location gets an empty frame."""

    def get(self, location: Location) -> pd.DataFrame:
        return pd.DataFrame()


def runner_of(home_simulator: HomeSimulator) -> FleetRunner:
    """A FleetRunner that runs each home through *home_simulator* in turn, in this process, on weather answering every location with an empty frame."""
    return FleetRunner(weather=_NoWeather(), home_simulator=home_simulator, parallel=False)


def jobs_running(home_simulator: HomeSimulator, **manager_options: Any) -> Callable[[RunStorage], JobManager]:
    """The factory of a JobManager over a RunStorage whose jobs run through runner_of(*home_simulator*), built with *manager_options*."""
    return functools.partial(JobManager, runner=runner_of(home_simulator), **manager_options)


class NewJobManager(Protocol):
    """tests/unit/conftest.py's new_job_manager: a JobManager over *storage* whose jobs run through runner_of(*home_simulator*), built with *options* and shut down at the test's teardown."""

    def __call__(self, storage: RunStorage, home_simulator: HomeSimulator, /, **options: Any) -> JobManager: ...


class NewJobManagerWithRunner(Protocol):
    """tests/unit/conftest.py's new_job_manager_with_runner: a JobManager over *storage* whose jobs run through *runner*, built with *options* and shut down at the test's teardown."""

    def __call__(self, storage: RunStorage, runner: FleetSimulator, /, **options: Any) -> JobManager: ...
