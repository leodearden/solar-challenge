# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Run the CLI in-process with the test's own fleet simulator, so the commands that read it never reach PVGIS.

The simulator travels as Click's context object, the runner of a CliInvocation.
The root's --workers and --sequential never rewrite that simulator, since a
test owns its simulator, while --quiet still silences the invocation. See
solar_challenge.cli.utils for which commands read it.

Usage::

    from tests._cli_fleet_simulator import ReachedTheSweep, RecordingSimulate, answering, invoke_cli, invoke_finance_run, simulate_reaching_the_sweep

    result = invoke_finance_run(["--project", str(scenario_file)], fleet_results)
    result = invoke_cli(["optimize", "configs", str(scenario_file)], answering(simulate))

    recorder = RecordingSimulate()
    result = invoke_cli(["finance", "run", str(scenario_file)], answering(recorder))
    asked_homes = recorder.homes

    result = invoke_cli(["optimize", "configs", str(scenario_file)], answering(simulate_reaching_the_sweep))
    reached_the_sweep = isinstance(result.exception, ReachedTheSweep)
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from typing import NoReturn

import pandas as pd
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.cli.utils import CliInvocation
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate, FleetSimulator, HomesDone
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.timebase import ONE_MINUTE, covered_days
from tests._finance_builders import make_fleet_results_of, make_sim_results


def invoke_cli(argv: list[str], simulator: FleetSimulator) -> Result:
    """Run the CLI on *argv*, with *simulator* running every simulation of the commands that read the invocation's runner."""
    return CliRunner().invoke(app, argv, obj=CliInvocation(runner=simulator))


def invoke_finance_run(args: list[str], fleet_results: FleetResults) -> Result:
    """Run `finance run` with *args*, answering every fleet simulation with *fleet_results*."""
    return invoke_cli(["finance", "run", *args], answering(lambda fleet_config, start, end: fleet_results))


def answering(simulate: FleetSimulate) -> FleetSimulator:
    """A FleetSimulator answering every fleet it is asked for with what *simulate* returns for it, and a home with the results *simulate* gives the one-home fleet of it."""
    return _Answering(simulate)


@dataclasses.dataclass(frozen=True)
class _Answering:
    """The FleetSimulator answering returns: each fleet's results are what answer returns for it."""

    answer: FleetSimulate

    def simulate(
        self, fleet: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, progress: HomesDone | None = None
    ) -> FleetResults:
        """answer's results for fleet; progress, when given, is then told every home of fleet has finished."""
        results = self.answer(fleet, start_date, end_date)
        if progress is not None:
            progress(len(fleet.homes), len(fleet.homes))
        return results

    def simulate_each(
        self,
        fleets: Sequence[FleetConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        *,
        progress: HomesDone | None = None,
    ) -> Iterator[tuple[int, FleetResults]]:
        """Each fleet's index, in order, with answer's results for it; progress, when given, is told after each fleet the homes finished so far of those in the call."""
        homes_in_the_call = sum(len(fleet.homes) for fleet in fleets)
        homes_finished = 0
        for index, fleet in enumerate(fleets):
            results = self.answer(fleet, start_date, end_date)
            homes_finished += len(fleet.homes)
            if progress is not None:
                progress(homes_finished, homes_in_the_call)
            yield index, results

    def simulate_home(self, home: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        """answer's results for the one-home fleet of home, named as home is."""
        (results,) = self.answer(FleetConfig((home,), name=home.name), start_date, end_date).per_home_results
        return results


@dataclasses.dataclass
class RecordingSimulate:
    """A fleet simulate that records every fleet it is asked for in fleets.

    It answers each home of a fleet with make_sim_results over the asked
    window's calendar days, from its first, paired with that fleet's homes, so
    it needs no weather. Its rows are one minute apart, the cadence of the
    window simulate_home runs a home over, so `finance run`'s reusing wrapper
    accepts its answers.
    """

    fleets: list[FleetConfig] = dataclasses.field(default_factory=list)

    def __call__(self, fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        self.fleets.append(fleet)
        days = covered_days(start.date(), end.date())
        return make_fleet_results_of(
            [make_sim_results(days=days, first_day=start.date(), cadence=ONE_MINUTE) for _ in fleet.homes],
            homes=fleet.homes,
        )

    @property
    def homes(self) -> list[HomeConfig]:
        """Every home of every fleet asked for, in the order asked."""
        return [home for fleet in self.fleets for home in fleet.homes]


class ReachedTheSweep(Exception):
    """Raised by simulate_reaching_the_sweep, the sign that a command got as far as its first fleet simulation."""


def simulate_reaching_the_sweep(fleet_config: object, start: object, end: object) -> NoReturn:
    """A fleet simulate that stops the command at its first fleet simulation, raising ReachedTheSweep."""
    raise ReachedTheSweep
