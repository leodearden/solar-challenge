# SPDX-License-Identifier: AGPL-3.0-or-later
"""Solar Challenge Web Dashboard.

A web-based dashboard for visualising solar PV and battery simulation results,
providing interactive charts and metrics for individual home and fleet analysis.
"""

from typing import Any

__all__ = [
    "create_app",
]


def create_app() -> Any:
    """Create and configure the web dashboard application.

    Returns:
        The configured web application instance.
    """
    from solar_challenge.web.app import create_app as _create_app
    return _create_app()
