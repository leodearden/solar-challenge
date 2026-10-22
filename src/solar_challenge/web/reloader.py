# SPDX-License-Identifier: AGPL-3.0-or-later
"""The watcher process of `solar-challenge web start --debug`, which never builds the dashboard.

Under --debug, werkzeug's reloader watcher binds the dashboard's port and runs the serving
process on it, re-executing this process's command line, and restarts that process after
each source change. Only the serving process builds the app, so the process that holds the
dashboard's store (web/store_lock.py) is the one that serves it.
"""

from collections.abc import Iterable
from wsgiref.types import StartResponse, WSGIEnvironment

from werkzeug.serving import is_running_from_reloader, run_simple


def started_by_reloader_watcher() -> bool:
    """Whether the --debug reloader's watcher started this process, as the process that serves the dashboard."""
    return is_running_from_reloader()


def run_reloader_watcher(host: str, port: int) -> None:
    """Bind *host* and *port* and run the reloader's watcher on them, starting the serving process and restarting it after each source change.

    Returns once Ctrl+C stops it, killing the serving process unless that process exits at
    once, so the simulations that process is running end unfinished. When the serving
    process exits other than to reload, raises SystemExit with that process's exit code,
    so this process exits with it.
    """
    run_simple(host, port, _never_served, use_reloader=True)


def _never_served(environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
    """The watcher's WSGI application: werkzeug needs one to build the server whose socket the watcher binds and hands to the serving process, and the watcher never serves a request."""
    raise RuntimeError("the --debug reloader's watcher never serves a request; the serving process it starts does")
