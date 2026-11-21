# SPDX-License-Identifier: AGPL-3.0-or-later
"""Main CLI application for Solar Challenge."""

from typing import Annotated, Optional

import typer

from solar_challenge import __version__
from solar_challenge.cli import config as config_app
from solar_challenge.cli import finance as finance_app
from solar_challenge.cli import fleet as fleet_app
from solar_challenge.cli import home as home_app
from solar_challenge.cli import optimize as optimize_app
from solar_challenge.cli import validate as validate_app
from solar_challenge.cli import web as web_app
from solar_challenge.cli.utils import console, root_invocation, set_status_quiet

# Create main app
app = typer.Typer(
    name="solar-challenge",
    help="Solar Challenge Energy Flow Simulator CLI",
    no_args_is_help=True,
)

# Register subcommand apps
app.add_typer(home_app.app, name="home")
app.add_typer(fleet_app.app, name="fleet")
app.add_typer(validate_app.app, name="validate")
app.add_typer(config_app.app, name="config")
app.add_typer(web_app.app, name="web")
app.add_typer(finance_app.app, name="finance")
app.add_typer(optimize_app.app, name="optimize")


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"solar-challenge version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version", "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q",
            help="Suppress status messages and progress; results, warnings and errors still print",
        ),
    ] = False,
    workers: Annotated[
        Optional[int],
        typer.Option(
            "--workers", "-w",
            min=1,
            help="Worker processes each fleet simulation runs its homes on; by default as many as its homes, up to the CPU count",
        ),
    ] = None,
    sequential: Annotated[
        bool,
        typer.Option(
            "--sequential",
            help="Simulate homes one after another in this process, not in a process pool",
        ),
    ] = False,
) -> None:
    """Solar Challenge Energy Flow Simulator.

    A CLI tool for simulating domestic PV and battery systems in the UK.
    """
    ctx.obj = root_invocation(ctx.obj, quiet=quiet, workers=workers, sequential=sequential)
    set_status_quiet(ctx.obj.quiet)


if __name__ == "__main__":
    app()
