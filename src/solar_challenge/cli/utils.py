# SPDX-License-Identifier: AGPL-3.0-or-later
"""Utility functions for the CLI.

A command prints its product (a results table, a template or a report) on
stdout, through console and print_report, and nothing else there. Status
messages and progress print on stderr through the status helpers (print_status,
print_info, print_success, create_progress and create_fleet_progress), and
warnings and errors through error_console, so redirecting stdout captures the
product alone. Print the product after any progress display stops: while one
runs on a terminal, Rich routes sys.stdout writes through it to stderr.

The status helpers take the command's invocation. While it is quiet (--quiet,
or an injected quiet invocation) they print nothing and progress displays stay
off; products, warnings and errors print either way.

What one invocation runs with travels as Click's context object, a
CliInvocation. Every command that simulates (`home run`, `home quick`,
`fleet run`, `fleet sweep`, `finance run` and `optimize configs`) reads its
runner from the invocation, invocation(ctx).runner. The root callback builds
that runner from --workers and --sequential, as root_invocation says, unless
whoever invokes the CLI passes a CliInvocation as obj; the root's options leave
that invocation's runner as it is. `web start` passes it on once create_app
takes one (task 889).
"""

import dataclasses
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from solar_challenge.battery import has_battery
from solar_challenge.config import load_config
from solar_challenge.error_text import error_text_with_notes
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetSimulator, FleetSummary, default_runner
from solar_challenge.home import SummaryStatistics
from solar_challenge.location import parse_location
from solar_challenge.scenario_writer import location_block
from solar_challenge.weather import WeatherDataError

console = Console()
error_console = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator that prints a ConfigurationError, a FileNotFoundError, any other OSError (as from a weather cache entry that cannot be read), a ValueError or a WeatherDataError on stderr under its own label and exits 1; Ctrl-C exits 130."""

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
        except OSError as e:
            _print_error_verbatim("System error", e)
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
    """Print label in red, then error's text and each of its notes on a line of its own as error_text_with_notes reads them, none of it read as Rich markup."""
    _print_verbatim(error_console, (f"{label}:", "red"), " ", error_text_with_notes(error))


def _print_verbatim(target: Console, *parts: str | tuple[str, str]) -> None:
    """Print parts on target exactly as they are, never read as Rich markup or emoji codes; a (text, style) part is printed in that style."""
    target.print(Text.assemble(*parts))


@dataclasses.dataclass(frozen=True)
class CliInvocation:
    """What one CLI invocation runs with, on Click's context object.

    Attributes:
        runner: Runs every simulation of the commands that simulate
        quiet: Whether the invocation's status messages and progress go unprinted
    """

    runner: FleetSimulator = dataclasses.field(default_factory=default_runner)
    quiet: bool = False


def invocation(ctx: typer.Context) -> CliInvocation:
    """The CliInvocation ctx's command runs with: its context object, else a default CliInvocation()."""
    return ctx.ensure_object(CliInvocation)


def root_invocation(obj: object, *, quiet: bool, workers: int | None, sequential: bool) -> CliInvocation:
    """The invocation the root's options make of obj: with none, default_runner() with parallel=not sequential and max_workers=workers, quiet as quiet says; an injected CliInvocation keeps its runner, and is quiet if it already is or quiet says so.

    Raises:
        TypeError: obj is neither None nor a CliInvocation, naming CliInvocation and obj's type
    """
    if obj is None:
        runner = dataclasses.replace(default_runner(), parallel=not sequential, max_workers=workers)
        return CliInvocation(runner=runner, quiet=quiet)
    if isinstance(obj, CliInvocation):
        return dataclasses.replace(obj, quiet=obj.quiet or quiet)
    raise TypeError(f"The CLI's context object must be a CliInvocation or None, got a {type(obj).__name__}")


def load_config_with_overrides(
    config_path: Optional[Path],
    pv_kw: Optional[float] = None,
    battery_kwh: Optional[float] = None,
    consumption_kwh: Optional[float] = None,
    location_str: Optional[str] = None,
    system_losses: Optional[float] = None,
) -> dict[str, Any]:
    """Load config file and apply CLI overrides.

    Args:
        config_path: Path to config file (optional)
        pv_kw: Override PV capacity
        battery_kwh: Override battery capacity
        consumption_kwh: Override annual consumption
        location_str: Override location, a location in location.parse_location's grammar:
            a preset name or 'lat,lon[,alt]'
        system_losses: Override PV system losses, set as the home's pv: block system_losses
            key, which PVConfig range-checks

    Returns:
        Config dict with overrides applied

    Raises:
        ConfigurationError: From has_battery, naming --battery-kwh, if battery_kwh is
            negative or not finite; and from location.parse_location, for a location_str
            it refuses
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

    if system_losses is not None:
        config["home"]["pv"]["system_losses"] = system_losses

    if battery_kwh is not None:
        if has_battery(battery_kwh, "--battery-kwh"):
            config["home"]["battery"] = {"capacity_kwh": battery_kwh}
        else:
            config["home"].pop("battery", None)

    if consumption_kwh is not None:
        config["home"]["load"]["annual_consumption_kwh"] = consumption_kwh

    if location_str is not None:
        config["location"] = location_block(parse_location(location_str))

    return config


def verbatim_table_title(title: str) -> Text:
    """*title* for a Rich Table, printed exactly as it is, never read as Rich markup or emoji codes, in Rich's table-title style."""
    return Text(title, style="table.title")


def create_summary_table(rows: Iterable[tuple[str, str]], title: str = "Simulation Summary") -> Table:
    """Create a Rich table of summary rows.

    Args:
        rows: (metric, value) pairs, printed in order under the title
        title: Table title, printed exactly as it is, never read as Rich markup or emoji codes

    Returns:
        Rich Table object
    """
    table = Table(title=verbatim_table_title(title))
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    for metric, value in rows:
        table.add_row(metric, value)
    return table


def home_summary_rows(summary: SummaryStatistics) -> tuple[tuple[str, str], ...]:
    """The (metric, value) rows `home run` and `home quick` print for a home's summary."""
    return (
        *_energy_total_rows(summary),
        ("Self-Consumption Ratio", f"{summary.self_consumption_ratio:.1%}"),
        ("Grid Dependency", f"{summary.grid_dependency_ratio:.1%}"),
        ("Simulation Days", str(summary.simulation_days)),
        *_money_rows(
            import_cost_gbp=summary.total_import_cost_gbp,
            export_revenue_gbp=summary.total_export_revenue_gbp,
            net_cost_gbp=summary.net_cost_gbp,
            seg_revenue_gbp=summary.seg_revenue_gbp,
        ),
    )


def fleet_summary_rows(summary: FleetSummary) -> tuple[tuple[str, str], ...]:
    """The (metric, value) rows `fleet run` prints for a fleet's summary: the fleet's totals, then, after a blank row, the spread of its homes' generation and self-consumption ratios."""
    return (
        *_energy_total_rows(summary),
        ("Self-Consumption Ratio", f"{summary.fleet_self_consumption_ratio:.1%}"),
        ("Grid Dependency", f"{summary.fleet_grid_dependency_ratio:.1%}"),
        ("Number of Homes", str(summary.n_homes)),
        ("Simulation Days", str(summary.simulation_days)),
        *_money_rows(
            import_cost_gbp=summary.total_import_cost_gbp,
            export_revenue_gbp=summary.total_export_revenue_gbp,
            net_cost_gbp=summary.total_net_cost_gbp,
            seg_revenue_gbp=summary.total_seg_revenue_gbp,
        ),
        ("", ""),
        (
            "Per-Home Generation (min/max)",
            f"{summary.per_home_generation_min_kwh:.1f} / {summary.per_home_generation_max_kwh:.1f} kWh",
        ),
        (
            "Per-Home Generation (mean)",
            f"{summary.per_home_generation_mean_kwh:.1f} kWh",
        ),
        (
            "Per-Home Self-Consumption Ratio (min/max)",
            f"{summary.per_home_self_consumption_ratio_min:.1%} / {summary.per_home_self_consumption_ratio_max:.1%}",
        ),
        (
            "Per-Home Self-Consumption Ratio (mean)",
            f"{summary.per_home_self_consumption_ratio_mean:.1%}",
        ),
    )


def _energy_total_rows(summary: SummaryStatistics | FleetSummary) -> tuple[tuple[str, str], ...]:
    """The Total Generation, Total Demand, Self-Consumption, Grid Import and Grid Export rows of a summary's energy totals."""
    return (
        ("Total Generation", f"{summary.total_generation_kwh:.1f} kWh"),
        ("Total Demand", f"{summary.total_demand_kwh:.1f} kWh"),
        ("Self-Consumption", f"{summary.total_self_consumption_kwh:.1f} kWh"),
        ("Grid Import", f"{summary.total_grid_import_kwh:.1f} kWh"),
        ("Grid Export", f"{summary.total_grid_export_kwh:.1f} kWh"),
    )


def _money_rows(
    *,
    import_cost_gbp: float | None,
    export_revenue_gbp: float | None,
    net_cost_gbp: float | None,
    seg_revenue_gbp: float | None,
) -> tuple[tuple[str, str], ...]:
    """The Grid Import Cost, Grid Export Revenue, Net Cost and SEG Revenue rows, each only when its amount is not None."""
    amounts = (
        ("Grid Import Cost", import_cost_gbp),
        ("Grid Export Revenue", export_revenue_gbp),
        ("Net Cost", net_cost_gbp),
        ("SEG Revenue", seg_revenue_gbp),
    )
    return tuple((metric, f"£{amount:.2f}") for metric, amount in amounts if amount is not None)


def _status_console(cli: CliInvocation) -> Console:
    """A console on stderr that prints nothing while cli is quiet, built for each status call, so no console outlives the invocation it prints for."""
    return Console(stderr=True, quiet=cli.quiet)


def _status_progress(cli: CliInvocation, *columns: str | ProgressColumn) -> Progress:
    """A progress display of columns on stderr, off while cli is quiet, so a quiet display never captures what else a command writes to stdout or stderr."""
    return Progress(*columns, console=_status_console(cli), disable=cli.quiet)


def create_progress(cli: CliInvocation) -> Progress:
    """Create a Rich progress bar for cli's simulations, printed on stderr."""
    return _status_progress(
        cli,
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
    )


def create_fleet_progress(cli: CliInvocation) -> Progress:
    """Progress bar with ETA for cli's fleet simulations, printed on stderr."""
    return _status_progress(
        cli,
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
    )


def print_status(cli: CliInvocation, *parts: str | tuple[str, str]) -> None:
    """Print parts side by side on stderr exactly as they are, unless cli is quiet; a (text, style) part is printed in that style."""
    _print_verbatim(_status_console(cli), *parts)


def print_success(cli: CliInvocation, message: str) -> None:
    """Print message in green on stderr, exactly as it is, unless cli is quiet."""
    print_status(cli, (message, "green"))


def print_warning(message: str) -> None:
    """Print message in yellow on stderr, exactly as it is."""
    _print_verbatim(error_console, (message, "yellow"))


def print_error(message: str) -> None:
    """Print message in red to stderr, exactly as it is."""
    _print_verbatim(error_console, (message, "red"))


def print_info(cli: CliInvocation, message: str) -> None:
    """Print message in blue on stderr, exactly as it is, unless cli is quiet."""
    print_status(cli, (message, "blue"))


def print_report(report: str) -> None:
    """Print report on stdout exactly as it is, each line whole however wide the console: never read as Rich markup or emoji codes, wrapped or cropped."""
    console.print(Text(report), soft_wrap=True)
