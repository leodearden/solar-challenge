# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation commands."""

from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import typer
from rich.table import Table

from solar_challenge.cli.utils import (
    console,
    error_console,
    handle_errors,
    print_error,
    print_success,
)
from solar_challenge.config import ConfigurationError, load_config
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
            help="PV system capacity in kW (for validation)",
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
    - Peak generation within capacity
    - Annual yield within UK range (800-1000 kWh/kWp)
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
        pv_kw,
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
    """Validate a configuration file.

    Checks:
    - File can be parsed (YAML/JSON syntax)
    - Required fields are present
    - Values are within valid ranges
    """
    try:
        config_data = load_config(config_file)

        # Basic structure validation
        errors = []
        warnings = []

        # Check for home or homes
        has_home = "home" in config_data
        has_homes = "homes" in config_data
        has_scenario = "scenario" in config_data or "scenarios" in config_data

        if not (has_home or has_homes or has_scenario):
            warnings.append("Config has no 'home', 'homes', or 'scenario' section")

        # Validate PV config if present
        home_data = config_data.get("home", {})
        pv_data = home_data.get("pv", {})

        if "capacity_kw" in pv_data:
            cap = pv_data["capacity_kw"]
            if cap <= 0:
                errors.append(f"PV capacity must be positive, got {cap}")
            elif cap > 50:
                warnings.append(f"PV capacity {cap} kW seems high for domestic")

        if "tilt" in pv_data:
            tilt = pv_data["tilt"]
            if not 0 <= tilt <= 90:
                errors.append(f"PV tilt must be 0-90 degrees, got {tilt}")

        if "azimuth" in pv_data:
            az = pv_data["azimuth"]
            if not 0 <= az <= 360:
                errors.append(f"PV azimuth must be 0-360 degrees, got {az}")

        # Validate battery config if present
        battery_data = home_data.get("battery", {})
        if battery_data:
            if "capacity_kwh" in battery_data:
                cap = battery_data["capacity_kwh"]
                if cap <= 0:
                    errors.append(f"Battery capacity must be positive, got {cap}")
                elif cap > 100:
                    warnings.append(f"Battery capacity {cap} kWh seems high for domestic")

        # Validate load config if present
        load_data = home_data.get("load", {})
        if "annual_consumption_kwh" in load_data:
            cons = load_data["annual_consumption_kwh"]
            if cons <= 0:
                errors.append(f"Annual consumption must be positive, got {cons}")
            elif cons > 20000:
                warnings.append(f"Annual consumption {cons} kWh seems high for domestic")

        if "household_occupants" in load_data:
            occ = load_data["household_occupants"]
            if occ < 1:
                errors.append(f"Household occupants must be at least 1, got {occ}")

        # Validate location if present
        loc_data = config_data.get("location", {})
        if "latitude" in loc_data:
            lat = loc_data["latitude"]
            if not -90 <= lat <= 90:
                errors.append(f"Latitude must be -90 to 90, got {lat}")

        if "longitude" in loc_data:
            lon = loc_data["longitude"]
            if not -180 <= lon <= 180:
                errors.append(f"Longitude must be -180 to 180, got {lon}")

        # Validate period if present
        period_data = config_data.get("period", {})
        if period_data:
            if "start_date" not in period_data:
                errors.append("Period missing 'start_date'")
            if "end_date" not in period_data:
                errors.append("Period missing 'end_date'")

        # Display results
        table = Table(title=f"Config Validation: {config_file.name}")
        table.add_column("Type", style="cyan")
        table.add_column("Message")

        if errors:
            for err in errors:
                table.add_row("[red]ERROR[/red]", err)

        if warnings:
            for warn in warnings:
                table.add_row("[yellow]WARNING[/yellow]", warn)

        if not errors and not warnings:
            table.add_row("[green]OK[/green]", "Configuration is valid")

        console.print(table)

        if errors:
            raise typer.Exit(1)

    except ConfigurationError as e:
        print_error(f"Configuration error: {e}")
        raise typer.Exit(1) from e
