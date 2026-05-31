# SPDX-License-Identifier: AGPL-3.0-or-later
"""Solar Challenge Energy Flow Simulator.

A simulation toolkit for modelling domestic PV and battery systems
in the Bristol area, supporting both individual home and fleet-level analysis.
"""

__version__ = "0.1.0"

# Lazy import of CLI app for programmatic access
def get_cli_app() -> "Typer":
    """Get the Typer CLI app for programmatic access.

    Returns:
        typer.Typer: The main CLI application
    """
    from solar_challenge.cli import app
    return app


# Type hint for lazy import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typer import Typer
