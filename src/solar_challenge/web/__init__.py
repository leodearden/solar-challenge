# SPDX-License-Identifier: AGPL-3.0-or-later
"""Solar Challenge Web Dashboard.

A web-based dashboard for visualising solar PV and battery simulation results,
providing interactive charts and metrics for individual home and fleet analysis.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

__all__ = [
    "create_app",
]


def create_app() -> "Flask":
    """Create and configure the web dashboard application, its jobs run on the JobManager solar_challenge.web.app's default_jobs builds.

    Imports the application factory, and Flask with it, only when called, so
    importing this package, or a module of it that does not import Flask such as
    solar_challenge.web.jobs, needs no web extra, as
    tests/unit/test_conftests_need_no_web_extra.py pins.

    The app holds its store's lock until ``dashboard_of(app).close()``
    (solar_challenge.web.dashboard), which its caller calls once it stops.

    Returns:
        The configured Flask application.
    """
    from solar_challenge.web.app import create_app as _create_app, default_jobs

    return _create_app(jobs=default_jobs)
