# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web dashboard commands."""

from typing import Annotated

import typer

from solar_challenge.cli.utils import handle_errors, print_error, print_info, print_report, status_console

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
    running finish before the process exits. Under --debug, stopping the
    server ends the running simulations too, and the next start marks their
    runs failed.

    One dashboard at a time may use the store under ~/.solar-challenge; while
    another holds it, this command exits with an error naming the lock file
    and the holding process.

    A store at a schema version other than this solar-challenge's is refused
    too, with an error naming its database and both versions; `solar-challenge
    web migrate` brings an older store to this version. So is a database file
    that cannot be read as one, naming it.

    Under --debug the server restarts when a source file changes; the
    restarted server process, not the watcher that restarts it, holds the
    store.

    Examples:
      solar-challenge web start
      solar-challenge web start --host 0.0.0.0 --port 8080
      solar-challenge web start --debug
    """
    from solar_challenge.web.reloader import run_reloader_watcher, started_by_reloader_watcher

    if debug and not started_by_reloader_watcher():
        run_reloader_watcher(host, port)
    else:
        _serve(host, port, debug)


def _serve(host: str, port: int, debug: bool) -> None:
    """Build the dashboard, which takes its store, and serve it on *host* and *port* until stopped; exit 1 if this process cannot take the store, or the store is at another schema version or cannot be read."""
    from solar_challenge.web import create_app
    from solar_challenge.web.jobs import shutdown_all_managers
    from solar_challenge.web.schema import SchemaVersionMismatch, StoreUnreadable
    from solar_challenge.web.store_lock import StoreLockError

    try:
        flask_app = create_app()
    except (StoreLockError, SchemaVersionMismatch, StoreUnreadable) as refused:
        print_error(str(refused))
        raise typer.Exit(1) from refused

    print_info(f"Starting web dashboard at http://{host}:{port}")
    status_console.print("  Press [bold]Ctrl+C[/bold] to stop the server.")

    try:
        flask_app.run(host=host, port=port, debug=debug)
    finally:
        shutdown_all_managers()


@app.command()
@handle_errors
def migrate() -> None:
    """Migrate the dashboard's store to this solar-challenge's schema version.

    Brings the store under ~/.solar-challenge, which an older solar-challenge
    left, to the schema version this one reads, applying in order each
    migration step it is behind by, and prints each step it applied. A store
    already at this version is left as it is.

    A step can bring each stored run to the stored-run format too: it prints
    each value it drops from a run's documents that is not null, naming the
    run, the document and the field, and each run it cannot migrate, which it
    leaves as it was, naming its run, document and field. It reads a run's
    JSON documents, not its time series, which have no format version: a run
    whose time series is damaged is migrated, and refused naming it when it is
    loaded.

    It refuses, changing nothing and exiting with an error: a store another
    dashboard holds, naming its lock file; a store a newer solar-challenge
    wrote, naming both versions; a store holding a row this version cannot
    keep, naming that row; a store whose tables a step cannot rebuild, naming
    the step and the fault; and a database file that cannot be read as one,
    naming it. A step that cannot write a stored run's file, e.g. on a full
    disk, is refused too, naming the step and the fault: the store stays at
    the version before it, and the command, run again once the fault is
    fixed, migrates it.

    Examples:
      solar-challenge web migrate
    """
    from solar_challenge.web.app import default_store_location
    from solar_challenge.web.schema import MigrationRefused, SchemaVersionMismatch, StoreUnreadable, migrate_store
    from solar_challenge.web.store_lock import StoreLockError, acquire_store_lock

    location = default_store_location()
    try:
        store_lock = acquire_store_lock(location.data_dir)
        try:
            report = migrate_store(location.database, location.data_dir)
        finally:
            store_lock.release()
    except (StoreLockError, SchemaVersionMismatch, StoreUnreadable, MigrationRefused) as refused:
        print_error(str(refused))
        raise typer.Exit(1) from refused
    print_report(str(report))
