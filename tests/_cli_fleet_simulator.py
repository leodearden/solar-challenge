# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Run the CLI in-process with the test's own fleet simulator, so its simulating commands never reach PVGIS.

The simulator travels as Click's context object, the CliFleetSimulator each
simulating command reads its simulator from.

Usage::

    from tests._cli_fleet_simulator import invoke_cli, invoke_finance_run

    result = invoke_finance_run(["--project", str(scenario_file)], fleet_results)
    result = invoke_cli(["optimize", "configs", str(scenario_file)], simulate)
"""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.cli.utils import CliFleetSimulator
from solar_challenge.fleet import FleetConfig, FleetResults


def invoke_cli(
    argv: list[str],
    simulate: Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults],
) -> Result:
    """Run the CLI on *argv*, with *simulate* running every fleet simulation."""
    return CliRunner().invoke(app, argv, obj=CliFleetSimulator(simulate=simulate))


def invoke_finance_run(args: list[str], fleet_results: FleetResults) -> Result:
    """Run `finance run` with *args*, answering every fleet simulation with *fleet_results*."""
    return invoke_cli(["finance", "run", *args], lambda fleet_config, start, end: fleet_results)
