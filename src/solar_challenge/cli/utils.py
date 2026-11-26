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

A command reads its --start and --end as StartOption and EndOption, and applies
them to its scenario with with_window_options, so each replaces only its own day
of the scenario's period.

`finance run` and `optimize configs` take their scenario's finance through
required_finance, so both refuse a file without a finance: block in one message.
Both read --assumptions as an AssumptionMode, and the own-use bases each mode
names from ASSUMPTION_BASES, so the two board commands share one vocabulary.
"""

import dataclasses
import enum
from collections.abc import Iterable, Mapping
from datetime import datetime
from functools import wraps
from types import MappingProxyType
from typing import Annotated, Any, Callable, Optional, TypeVar

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

from solar_challenge.config import ScenarioConfig
from solar_challenge.error_text import error_text_with_notes
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig, OwnUseBasis
from solar_challenge.fleet import FleetSimulator, FleetSummary, default_runner
from solar_challenge.dispatch import GridChargeForecast, distinct_grid_charge_forecasts
from solar_challenge.home import SummaryStatistics
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from solar_challenge.weather import WeatherDataError

console = Console()
error_console = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator that reports an error the user can act on as its label and text on stderr and exits 1, rather than as a traceback; Ctrl-C exits 130."""

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


StartOption = Annotated[
    Optional[datetime],
    typer.Option(
        "--start",
        formats=["%Y-%m-%d"],
        help=(
            "First day to simulate (YYYY-MM-DD), replacing only the start_date of the file's period:; "
            f"defaults to the file's start_date, else {DEFAULT_FIRST_DAY.isoformat()}"
        ),
    ),
]
"""The --start option of a command that simulates a scenario's period: the day with_window_options gives as its first."""

EndOption = Annotated[
    Optional[datetime],
    typer.Option(
        "--end",
        formats=["%Y-%m-%d"],
        help=(
            "Last day to simulate (YYYY-MM-DD), replacing only the end_date of the file's period:; "
            f"defaults to the file's end_date, else {DEFAULT_LAST_DAY.isoformat()}"
        ),
    ),
]
"""The --end option of a command that simulates a scenario's period: the day with_window_options gives as its last."""


def with_window_options(
    scenario: ScenarioConfig, *, start: Optional[datetime], end: Optional[datetime]
) -> ScenarioConfig:
    """*scenario* with its period's first day replaced by start's date and its last by end's, each only when given.

    Raises:
        ConfigurationError: for days that give no window, naming each flag given with its
            day, then the reason ScenarioConfig.with_window refuses the window for.
    """
    first_day = None if start is None else start.date()
    last_day = None if end is None else end.date()
    try:
        return scenario.with_window(first_day=first_day, last_day=last_day)
    except ConfigurationError as exc:
        given = " ".join(
            f"{flag} {day.isoformat()}"
            for flag, day in (("--start", first_day), ("--end", last_day))
            if day is not None
        )
        raise ConfigurationError(f"{given}: {exc.__cause__ or exc}") from exc


def required_finance(scenario: ScenarioConfig) -> FinanceConfig:
    """*scenario*'s finance.

    Raises:
        ConfigurationError: *scenario* has no finance: block, saying what the block needs.
    """
    if scenario.finance is None:
        raise ConfigurationError(
            "No 'finance:' block found in the scenario file. "
            "Add a finance: block with at least standing_charge_pence_per_day."
        )
    return scenario.finance


class AssumptionMode(str, enum.Enum):
    """A board command's --assumptions: the self-consumption assumption, or assumptions, it computes under."""

    physics = "physics"
    spreadsheet = "spreadsheet"
    both = "both"


ASSUMPTION_BASES: Mapping[AssumptionMode, tuple[OwnUseBasis, ...]] = MappingProxyType(
    {
        AssumptionMode.physics: (OwnUseBasis.SIMULATED,),
        AssumptionMode.spreadsheet: (OwnUseBasis.OVERRIDE,),
        AssumptionMode.both: (OwnUseBasis.SIMULATED, OwnUseBasis.OVERRIDE),
    }
)
"""The own-use bases each --assumptions mode names: finance run reports each as a column, and optimize configs ranks under a mode naming one."""


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
        ),
        *_grid_charge_forecast_rows(distinct_grid_charge_forecasts([summary.grid_charge_forecast])),
    )


def fleet_summary_rows(summary: FleetSummary) -> tuple[tuple[str, str], ...]:
    """The (metric, value) rows `fleet run` prints for a fleet's summary: the fleet's totals and the forecasts that sized its grid charge, then, after a blank row, the spread of its homes' generation and self-consumption ratios."""
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
        ),
        *_grid_charge_forecast_rows(summary.grid_charge_forecasts),
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


def _grid_charge_forecast_rows(forecasts: tuple[GridChargeForecast, ...]) -> tuple[tuple[str, str], ...]:
    """The Grid-charge forecast row naming *forecasts*, the forecasts that sized a summary's grid charge; none when nothing grid-charged."""
    return (("Grid-charge forecast", ", ".join(forecasts)),) if forecasts else ()


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
) -> tuple[tuple[str, str], ...]:
    """The Grid Import Cost, Grid Export Revenue and Net Cost rows, each only when its amount is not None."""
    amounts = (
        ("Grid Import Cost", import_cost_gbp),
        ("Grid Export Revenue", export_revenue_gbp),
        ("Net Cost", net_cost_gbp),
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
