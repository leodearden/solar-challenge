# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web dashboard commands."""

from typing import Annotated

import typer

from solar_challenge.cli.utils import console, handle_errors, print_info

app = typer.Typer(help="Web dashboard commands")


@app.command()
@handle_errors
def start(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Host address to bind the server to",
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            "--port", "-p",
            help="Port number to listen on",
        ),
    ] = 5000,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug mode",
        ),
    ] = False,
) -> None:
    """Start the Solar Challenge web dashboard server.

    Launches a local web server hosting the interactive dashboard for
    visualising solar PV and battery simulation results.

    Examples:
      solar-challenge web start
      solar-challenge web start --host 0.0.0.0 --port 8080
      solar-challenge web start --debug
    """
    from solar_challenge.web import create_app

    flask_app = create_app()

    print_info(f"Starting web dashboard at http://{host}:{port}")
    console.print(f"  Press [bold]Ctrl+C[/bold] to stop the server.")

    flask_app.run(host=host, port=port, debug=debug)
