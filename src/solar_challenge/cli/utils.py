# SPDX-License-Identifier: AGPL-3.0-or-later
"""Utility functions for the CLI."""

import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from solar_challenge.config import ConfigurationError, load_config
from solar_challenge.location import Location

console = Console()
error_console = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator to handle common errors and display user-friendly messages."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ConfigurationError as e:
            error_console.print(f"[red]Configuration error:[/red] {e}")
            raise typer.Exit(1) from e
        except FileNotFoundError as e:
            error_console.print(f"[red]File not found:[/red] {e}")
            raise typer.Exit(1) from e
        except ValueError as e:
            error_console.print(f"[red]Invalid value:[/red] {e}")
            raise typer.Exit(1) from e
        except KeyboardInterrupt:
            error_console.print("\n[yellow]Interrupted by user[/yellow]")
            raise typer.Exit(130) from None

    return wrapper  # type: ignore[return-value]


def parse_location(location_str: str) -> Location:
    """Parse location from string.

    Accepts:
    - 'bristol' (case-insensitive preset)
    - 'lat,lon' format (e.g., '51.45,-2.58')
    - 'lat,lon,altitude' format (e.g., '51.45,-2.58,11')

    Args:
        location_str: Location string to parse

    Returns:
        Location object

    Raises:
        ValueError: If location string is invalid
    """
    location_lower = location_str.lower().strip()

    if location_lower == "bristol":
        return Location.bristol()

    # Try parsing as coordinates
    parts = location_str.split(",")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid location format: '{location_str}'. "
            "Use 'bristol' or 'lat,lon' format."
        )

    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
        alt = float(parts[2].strip()) if len(parts) > 2 else 0.0
        return Location(
            latitude=lat,
            longitude=lon,
            altitude=alt,
            name=f"Custom ({lat:.2f}, {lon:.2f})",
        )
    except ValueError as e:
        raise ValueError(
            f"Invalid coordinates in '{location_str}': {e}"
        ) from e


def load_config_with_overrides(
    config_path: Optional[Path],
    pv_kw: Optional[float] = None,
    battery_kwh: Optional[float] = None,
    consumption_kwh: Optional[float] = None,
    location_str: Optional[str] = None,
) -> dict[str, Any]:
    """Load config file and apply CLI overrides.

    Args:
        config_path: Path to config file (optional)
        pv_kw: Override PV capacity
        battery_kwh: Override battery capacity
        consumption_kwh: Override annual consumption
        location_str: Override location string

    Returns:
        Config dict with overrides applied
    """
    if config_path is not None:
        config = load_config(config_path)
    else:
        config = {}

    # Ensure nested structure exists
    if "home" not in config:
        config["home"] = {}
    if "pv" not in config["home"]:
        config["home"]["pv"] = {}
    if "load" not in config["home"]:
        config["home"]["load"] = {}

    # Apply overrides
    if pv_kw is not None:
        config["home"]["pv"]["capacity_kw"] = pv_kw

    if battery_kwh is not None:
        if battery_kwh > 0:
            config["home"]["battery"] = {"capacity_kwh": battery_kwh}
        else:
            config["home"].pop("battery", None)

    if consumption_kwh is not None:
        config["home"]["load"]["annual_consumption_kwh"] = consumption_kwh

    if location_str is not None:
        loc = parse_location(location_str)
        config["location"] = {
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "timezone": loc.timezone,
            "altitude": loc.altitude,
            "name": loc.name,
        }

    return config


def create_summary_table(summary: Any, title: str = "Simulation Summary") -> Table:
    """Create a Rich table from summary statistics.

    Args:
        summary: SummaryStatistics or FleetSummary object
        title: Table title

    Returns:
        Rich Table object
    """
    table = Table(title=title)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    # Energy totals
    table.add_row("Total Generation", f"{summary.total_generation_kwh:.1f} kWh")
    table.add_row("Total Demand", f"{summary.total_demand_kwh:.1f} kWh")
    table.add_row("Self-Consumption", f"{summary.total_self_consumption_kwh:.1f} kWh")
    table.add_row("Grid Import", f"{summary.total_grid_import_kwh:.1f} kWh")
    table.add_row("Grid Export", f"{summary.total_grid_export_kwh:.1f} kWh")

    # Ratios
    if hasattr(summary, "self_consumption_ratio"):
        table.add_row(
            "Self-Consumption Ratio",
            f"{summary.self_consumption_ratio:.1%}",
        )
    if hasattr(summary, "grid_dependency_ratio"):
        table.add_row(
            "Grid Dependency",
            f"{summary.grid_dependency_ratio:.1%}",
        )

    # Fleet-specific
    if hasattr(summary, "n_homes"):
        table.add_row("Number of Homes", str(summary.n_homes))

    # Simulation duration
    if hasattr(summary, "simulation_days"):
        table.add_row("Simulation Days", str(summary.simulation_days))

    return table


def create_progress() -> Progress:
    """Create a Rich progress bar for simulations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )


def create_fleet_progress() -> Progress:
    """Progress bar with ETA for fleet simulations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=console,
    )


def print_success(message: str) -> None:
    """Print success message."""
    console.print(f"[green]{message}[/green]")


def print_warning(message: str) -> None:
    """Print warning message."""
    console.print(f"[yellow]{message}[/yellow]")


def print_error(message: str) -> None:
    """Print error message to stderr."""
    error_console.print(f"[red]{message}[/red]")


def print_info(message: str) -> None:
    """Print info message."""
    console.print(f"[blue]{message}[/blue]")
