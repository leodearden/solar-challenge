# SPDX-License-Identifier: AGPL-3.0-or-later
"""Utility functions for the CLI.

A command prints its product (a results table, a template or a report) on
stdout, through console and print_report, and nothing else there. Status
messages and progress print on stderr through status_console, and errors
through error_console, so redirecting stdout captures the product alone.
Print the product after any progress display stops: while one runs on a
terminal, Rich routes sys.stdout writes through it to stderr.
"""

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
from rich.text import Text

from solar_challenge.config import ConfigurationError, load_config
from solar_challenge.location import Location
from solar_challenge.weather import WeatherDataError

console = Console()
status_console = Console(stderr=True)
error_console = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator to handle common errors and display user-friendly messages."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ConfigurationError as e:
            _print_error_verbatim("Configuration error", e)
            raise typer.Exit(1) from e
        except FileNotFoundError as e:
            _print_error_verbatim("File not found", e)
            raise typer.Exit(1) from e
        except ValueError as e:
            _print_error_verbatim("Invalid value", e)
            raise typer.Exit(1) from e
        except WeatherDataError as e:
            _print_error_verbatim("Weather data unavailable", e)
            raise typer.Exit(1) from e
        except KeyboardInterrupt:
            error_console.print("\n[yellow]Interrupted by user[/yellow]")
            raise typer.Exit(130) from None

    return wrapper  # type: ignore[return-value]


def _print_error_verbatim(label: str, error: Exception) -> None:
    """Print label in red, then error's text exactly as it is."""
    _print_verbatim(error_console, (f"{label}:", "red"), " ", str(error))


def _print_verbatim(target: Console, *parts: str | tuple[str, str]) -> None:
    """Print parts on target exactly as they are, never read as Rich markup or emoji codes; a (text, style) part is printed in that style."""
    target.print(Text.assemble(*parts))


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


def verbatim_table_title(title: str) -> Text:
    """*title* for a Rich Table, printed exactly as it is, never read as Rich markup or emoji codes, in Rich's table-title style."""
    return Text(title, style="table.title")


def create_summary_table(summary: Any, title: str = "Simulation Summary") -> Table:
    """Create a Rich table from summary statistics.

    Args:
        summary: SummaryStatistics or FleetSummary object
        title: Table title, printed exactly as it is, never read as Rich markup or emoji codes

    Returns:
        Rich Table object
    """
    table = Table(title=verbatim_table_title(title))
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

    # Financial rows — present on SummaryStatistics; guarded so FleetSummary is unaffected
    if hasattr(summary, "total_import_cost_gbp") and summary.total_import_cost_gbp is not None:
        table.add_row("Grid Import Cost", f"£{summary.total_import_cost_gbp:.2f}")
    if hasattr(summary, "total_export_revenue_gbp") and summary.total_export_revenue_gbp is not None:
        table.add_row("Grid Export Revenue", f"£{summary.total_export_revenue_gbp:.2f}")
    if hasattr(summary, "net_cost_gbp") and summary.net_cost_gbp is not None:
        table.add_row("Net Cost", f"£{summary.net_cost_gbp:.2f}")
    seg_rev = getattr(summary, "seg_revenue_gbp", None)
    if seg_rev is not None:
        table.add_row("SEG Revenue", f"£{seg_rev:.2f}")

    return table


def set_status_quiet(quiet: bool) -> None:
    """Silence status messages and progress on stderr while quiet is True, and print them again once it is False; products and errors print either way."""
    status_console.quiet = quiet


def create_progress() -> Progress:
    """Create a Rich progress bar for simulations, printed on stderr."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=status_console,
    )


def create_fleet_progress() -> Progress:
    """Progress bar with ETA for fleet simulations, printed on stderr."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=status_console,
    )


def print_success(message: str) -> None:
    """Print message in green on stderr, exactly as it is."""
    _print_verbatim(status_console, (message, "green"))


def print_warning(message: str) -> None:
    """Print message in yellow on stderr, exactly as it is."""
    _print_verbatim(status_console, (message, "yellow"))


def print_error(message: str) -> None:
    """Print message in red to stderr, exactly as it is."""
    _print_verbatim(error_console, (message, "red"))


def print_info(message: str) -> None:
    """Print message in blue on stderr, exactly as it is."""
    _print_verbatim(status_console, (message, "blue"))


def print_report(report: str) -> None:
    """Print report on stdout exactly as it is, each line whole however wide the console: never read as Rich markup or emoji codes, wrapped or cropped."""
    console.print(Text(report), soft_wrap=True)
