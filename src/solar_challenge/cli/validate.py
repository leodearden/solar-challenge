# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation commands."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Mapping, Optional, Sequence
from warnings import WarningMessage, catch_warnings, simplefilter

import pandas as pd
import typer
from rich.table import Table
from rich.text import Text

from solar_challenge.cli.utils import (
    console,
    handle_errors,
    print_error,
    print_success,
)
from solar_challenge.config import (
    ConfigurationError,
    ScenarioConfig,
    detect_sweep_spec,
    expand_sweep_configs,
    generate_homes_from_distribution,
    load_config,
    load_fleet_config,
    load_home_config,
    load_scenarios,
    parse_fleet_distribution_config,
    parse_location_block,
)
from solar_challenge.home import HomeConfig
from solar_challenge.pv import PVConfig
from solar_challenge.validation import (
    ValidationReport,
    validate_consumption,
    validate_pv_generation,
)

app = typer.Typer(help="Validation commands")


def _display_validation_report(report: ValidationReport) -> None:
    """Display validation report as a Rich table."""
    table = Table(title="Validation Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Message")
    table.add_column("Value", justify="right")
    table.add_column("Expected", justify="right")

    for result in report.results:
        status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        value_str = f"{result.value:.4f}" if result.value is not None else "-"
        expected_str = (
            f"{result.expected_range[0]:.2f} - {result.expected_range[1]:.2f}"
            if result.expected_range is not None
            else "-"
        )
        table.add_row(
            result.check_name,
            status,
            result.message,
            value_str,
            expected_str,
        )

    console.print(table)

    # Summary
    passed = sum(1 for r in report.results if r.passed)
    total = len(report.results)
    if report.all_passed:
        print_success(f"All {total} checks passed")
    else:
        print_error(f"{passed}/{total} checks passed")


@app.command()
@handle_errors
def results(
    csv_file: Annotated[
        Path,
        typer.Argument(
            help="Path to simulation results CSV file",
            exists=True,
            dir_okay=False,
        ),
    ],
    pv_kw: Annotated[
        float,
        typer.Option(
            "--pv-kw",
            help="Configured PV capacity in kW (PVConfig.capacity_kw) of a default-module system",
        ),
    ] = 4.0,
    consumption_kwh: Annotated[
        Optional[float],
        typer.Option(
            "--consumption-kwh",
            help="Target annual consumption in kWh (for validation)",
        ),
    ] = None,
) -> None:
    """Validate simulation results CSV against benchmarks.

    Checks PV generation and consumption values for sanity:
    - Generation never negative
    - Generation zero at night
    - Peak generation within 10% over the DC of the modules wired for --pv-kw
    - Annual yield per kWp of the modules wired for --pv-kw within the UK benchmark band
    - Consumption never negative or unrealistically high
    - Baseload present
    """
    # Load CSV
    df = pd.read_csv(csv_file, index_col=0, parse_dates=True)

    # Check for required columns
    gen_col = None
    demand_col = None
    for col in df.columns:
        if "generation" in col.lower():
            gen_col = col
        if "demand" in col.lower():
            demand_col = col

    if gen_col is None:
        print_error("CSV must contain a 'generation' column")
        raise typer.Exit(1)
    if demand_col is None:
        print_error("CSV must contain a 'demand' column")
        raise typer.Exit(1)

    # Get series
    generation = df[gen_col]
    demand = df[demand_col]

    # Run validation
    all_results = []

    # Validate PV
    pv_results = validate_pv_generation(
        generation,
        PVConfig(capacity_kw=pv_kw),
        check_annual=True,
    )
    all_results.extend(pv_results)

    # Validate consumption
    consumption_results = validate_consumption(
        demand,
        target_annual_kwh=consumption_kwh,
    )
    all_results.extend(consumption_results)

    report = ValidationReport(results=all_results)
    _display_validation_report(report)

    if not report.all_passed:
        raise typer.Exit(1)


@dataclass(frozen=True)
class _DefinedHomes:
    """The homes a config file defines.

    A YAML-defined sweep builds the file's fleet once per sweep point, so *homes* holds
    each of its homes once per point, and *sweep_points* is the number of points.
    """

    homes: Sequence[HomeConfig]
    sweep_points: int = 1


def _scenario_homes(scenario: ScenarioConfig) -> list[HomeConfig]:
    """The homes a scenario simulates: its single home, or else its fleet."""
    return [scenario.home] if scenario.home is not None else scenario.homes


def _fleet_homes(config_file: Path, document: Mapping[str, Any]) -> _DefinedHomes:
    """The homes `fleet run` builds from the file.

    For a YAML-defined sweep, the homes `fleet sweep` builds at every sweep point.
    """
    if "fleet_distribution" in document:
        distribution = parse_fleet_distribution_config(document["fleet_distribution"])
        if detect_sweep_spec(distribution) is not None:
            location = parse_location_block(document.get("location"))
            fleets = [
                generate_homes_from_distribution(point, location)
                for _, point in expand_sweep_configs(distribution)
            ]
            return _DefinedHomes(
                homes=[home for fleet in fleets for home in fleet],
                sweep_points=len(fleets),
            )
    return _DefinedHomes(homes=load_fleet_config(config_file).homes)


def _homes_defined_by(config_file: Path) -> _DefinedHomes:
    """The homes the file defines, built by the config.py loader its shape needs.

    Raises the loader's own ConfigurationError or ValueError when the file is refused.
    """
    document = load_config(config_file)
    if "scenarios" in document or "scenario" in document:
        return _DefinedHomes(
            homes=[
                home
                for scenario in load_scenarios(config_file)
                for home in _scenario_homes(scenario)
            ]
        )
    if "fleet_distribution" in document or "homes" in document:
        return _fleet_homes(config_file, document)
    return _DefinedHomes(homes=[load_home_config(config_file)])


@dataclass(frozen=True)
class _DomesticCeiling:
    """A size above which a domestic install seems implausible: an advisory, never a refusal."""

    subject: str
    unit: str
    ceiling: float
    size_of: Callable[[HomeConfig], Optional[float]]

    def warning(self, defined: _DefinedHomes) -> Optional[str]:
        """One line naming the largest size above the ceiling and how many *defined* homes exceed it, or None when none do."""
        sizes = [
            size
            for home in defined.homes
            if (size := self.size_of(home)) is not None and size > self.ceiling
        ]
        if not sizes:
            return None
        across = (
            f", across {defined.sweep_points} sweep points"
            if defined.sweep_points > 1
            else ""
        )
        return (
            f"{self.subject} {max(sizes)} {self.unit} seems high for domestic "
            f"({len(sizes)} of {len(defined.homes)} homes above {self.ceiling} {self.unit}{across})"
        )


def _battery_capacity_kwh(home: HomeConfig) -> Optional[float]:
    """The home's battery capacity, or None for a PV-only home."""
    return None if home.battery_config is None else home.battery_config.capacity_kwh


_DOMESTIC_CEILINGS: tuple[_DomesticCeiling, ...] = (
    _DomesticCeiling(
        subject="PV capacity",
        unit="kW",
        ceiling=50,
        size_of=lambda home: home.pv_config.capacity_kw,
    ),
    _DomesticCeiling(
        subject="Battery capacity",
        unit="kWh",
        ceiling=100,
        size_of=_battery_capacity_kwh,
    ),
    _DomesticCeiling(
        subject="Annual consumption",
        unit="kWh",
        ceiling=20000,
        size_of=lambda home: home.load_config.annual_consumption_kwh,
    ),
)


def _domestic_scale_warnings(defined: _DefinedHomes) -> list[str]:
    """One line for each domestic ceiling that some defined home exceeds."""
    return [
        warning
        for ceiling in _DOMESTIC_CEILINGS
        if (warning := ceiling.warning(defined)) is not None
    ]


def _user_warnings(caught: Sequence[WarningMessage]) -> list[str]:
    """The messages of the UserWarnings among *caught*: the advisories a loader raises as it builds."""
    return [
        str(item.message) for item in caught if issubclass(item.category, UserWarning)
    ]


def _findings(config_file: Path) -> tuple[list[str], list[str]]:
    """The (errors, warnings) of validating the file.

    The errors are the loader's first refusal, if any. The warnings are the advisories
    the loader raised on the way, then each domestic-scale size above its ceiling.
    """
    with catch_warnings(record=True) as caught:
        simplefilter("always")
        try:
            defined = _homes_defined_by(config_file)
        except (ConfigurationError, ValueError) as refusal:
            return [str(refusal)], _user_warnings(caught)
    return [], _user_warnings(caught) + _domestic_scale_warnings(defined)


def _print_config_findings(
    config_file: Path, errors: Sequence[str], warnings: Sequence[str]
) -> None:
    """Print the findings for the file as a table: its errors, then its warnings, or OK when there are none.

    Each message is printed exactly as it is, never read as Rich markup or emoji codes.
    """
    table = Table(title=f"Config Validation: {config_file.name}")
    table.add_column("Type", style="cyan")
    table.add_column("Message")

    for error in errors:
        table.add_row("[red]ERROR[/red]", Text(error))
    for warning in warnings:
        table.add_row("[yellow]WARNING[/yellow]", Text(warning))
    if not errors and not warnings:
        table.add_row("[green]OK[/green]", Text("Configuration is valid"))

    console.print(table)


@app.command()
@handle_errors
def config(
    config_file: Annotated[
        Path,
        typer.Argument(
            help="Path to config file to validate",
            exists=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Validate a configuration file by building the homes it defines.

    The file's shape picks which loader builds them:
    - scenarios: or scenario: files load as scenarios
    - homes: or fleet_distribution: files load as a fleet, as `fleet run` loads them
    - any other file loads as a home file: a home: block, or a flat home

    A YAML-defined sweep is built at every sweep point, as `fleet sweep` builds it.
    The first value or key the loader refuses is an ERROR. The loader's advisories,
    and sizes beyond a domestic install, are WARNINGs. Only the homes are checked,
    not the file's other top-level blocks, such as seg: or finance:.
    """
    errors, warnings = _findings(config_file)
    _print_config_findings(config_file, errors=errors, warnings=warnings)
    if errors:
        raise typer.Exit(1)
