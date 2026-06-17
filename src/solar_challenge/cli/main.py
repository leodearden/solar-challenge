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
from solar_challenge.cli.utils import console

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
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version", "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q",
            help="Suppress non-essential output",
        ),
    ] = False,
) -> None:
    """Solar Challenge Energy Flow Simulator.

    A CLI tool for simulating domestic PV and battery systems in the UK.

    Commands:
      home      Single home simulation
      fleet     Fleet (multiple homes) simulation
      validate  Validate results or config files
      config    Configuration management
      web       Web dashboard server

    Examples:
      solar-challenge home quick 4 5 --days 7
      solar-challenge home run config.yaml --report
      solar-challenge fleet bristol-phase1 --days 30
      solar-challenge config template home -o my-config.yaml
      solar-challenge web start --port 8080
    """
    # Store verbose/quiet in context for subcommands
    # In practice, subcommands can check these via the context if needed
    pass


if __name__ == "__main__":
    app()
