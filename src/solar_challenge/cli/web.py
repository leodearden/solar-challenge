# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web dashboard commands."""

from typing import Annotated

import typer

from solar_challenge.cli.utils import handle_errors, print_error, print_info, status_console

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

    Stopping the server drops the simulations still queued; those already
    running finish before the process exits.

    One dashboard at a time may use the store under ~/.solar-challenge; while
    another holds it, this command exits with an error naming the lock file
    and the holding process.

    Examples:
      solar-challenge web start
      solar-challenge web start --host 0.0.0.0 --port 8080
      solar-challenge web start --debug
    """
    from solar_challenge.web import create_app
    from solar_challenge.web.jobs import shutdown_all_managers
    from solar_challenge.web.store_lock import StoreLockError

    try:
        flask_app = create_app()
    except StoreLockError as refused:
        print_error(str(refused))
        raise typer.Exit(1) from refused

    print_info(f"Starting web dashboard at http://{host}:{port}")
    status_console.print("  Press [bold]Ctrl+C[/bold] to stop the server.")

    try:
        flask_app.run(host=host, port=port, debug=debug)
    finally:
        shutdown_all_managers()
