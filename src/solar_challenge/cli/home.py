# SPDX-License-Identifier: AGPL-3.0-or-later
"""Home simulation commands."""

import dataclasses
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import typer

from solar_challenge.battery import BatteryConfig, has_battery
from solar_challenge.cli.utils import (
    console,
    create_progress,
    create_summary_table,
    handle_errors,
    home_summary_rows,
    load_config_with_overrides,
    print_info,
    print_report,
    print_success,
)
from solar_challenge.config import parse_home_block, parse_location_block, parse_seg_rate
from solar_challenge.home import HomeConfig, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.output import export_to_csv, generate_summary_report
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.weather import default_weather

app = typer.Typer(help="Single home simulation commands")


def home_config_for_run(
    config: Optional[Path],
    *,
    pv_kw: Optional[float] = None,
    battery_kwh: Optional[float] = None,
    consumption_kwh: Optional[float] = None,
    location_str: Optional[str] = None,
    system_losses: Optional[float] = None,
) -> HomeConfig:
    """The HomeConfig `home run` simulates: the file's home: block at its location:,
    with its seg: block and the command-line overrides applied."""
    config_dict = load_config_with_overrides(
        config,
        pv_kw=pv_kw,
        battery_kwh=battery_kwh,
        consumption_kwh=consumption_kwh,
        location_str=location_str,
        system_losses=system_losses,
    )
    loc = parse_location_block(config_dict.get("location"))
    home_config = parse_home_block(config_dict.get("home", {}), loc)
    seg_rate = parse_seg_rate(config_dict.get("seg"))
    if seg_rate is not None:
        home_config = dataclasses.replace(
            home_config,
            seg_tariff=SEGTariff(name="", rate_pence_per_kwh=seg_rate),
        )
    return home_config


@app.command()
@handle_errors
def run(
    config: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to YAML/JSON config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    start: Annotated[
        str,
        typer.Option(
            "--start",
            help="Start date (YYYY-MM-DD)",
        ),
    ] = "2024-01-01",
    end: Annotated[
        str,
        typer.Option(
            "--end",
            help="End date (YYYY-MM-DD)",
        ),
    ] = "2024-12-31",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output CSV file path",
        ),
    ] = None,
    report: Annotated[
        bool,
        typer.Option(
            "--report", "-r",
            help="Print the markdown summary report in place of the summary table",
        ),
    ] = False,
    pv_kw: Annotated[
        Optional[float],
        typer.Option(
            "--pv-kw",
            help="Override PV capacity (kW)",
        ),
    ] = None,
    battery_kwh: Annotated[
        Optional[float],
        typer.Option(
            "--battery-kwh",
            help="Override battery capacity (kWh), 0 for no battery",
        ),
    ] = None,
    consumption_kwh: Annotated[
        Optional[float],
        typer.Option(
            "--consumption-kwh",
            help="Override annual consumption (kWh)",
        ),
    ] = None,
    location: Annotated[
        Optional[str],
        typer.Option(
            "--location", "-l",
            help=(
                f"Location: a preset, one of {', '.join(LOCATION_PRESETS)}, in any case; "
                "or 'lat,lon' or 'lat,lon,alt' in decimal degrees and metres, e.g. '51.48,-3.18,10'"
            ),
        ),
    ] = None,
    system_losses: Annotated[
        Optional[float],
        typer.Option(
            "--system-losses",
            help="Override PV system losses, the fraction of DC power lost before the inverter (e.g. 0.05)",
        ),
    ] = None,
) -> None:
    """Run a single home simulation from config file or CLI arguments.

    If no config file is provided, uses default values with any CLI overrides.
    """
    home_config = home_config_for_run(
        config,
        pv_kw=pv_kw,
        battery_kwh=battery_kwh,
        consumption_kwh=consumption_kwh,
        location_str=location,
        system_losses=system_losses,
    )
    seg_rate = (
        home_config.seg_tariff.rate_pence_per_kwh
        if home_config.seg_tariff is not None
        else None
    )

    # Parse dates
    start_date = pd.Timestamp(start, tz=home_config.location.timezone)
    end_date = pd.Timestamp(end, tz=home_config.location.timezone)

    # Calculate simulation duration for progress display
    days_count = (end_date - start_date).days + 1
    print_info(f"Simulating {days_count} days from {start} to {end}")

    # Run simulation with progress
    with create_progress() as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = simulate_home(home_config, start_date, end_date, weather=default_weather())
        progress.update(task, completed=True)

    if report:
        print_report(
            generate_summary_report(results, home_config.name, seg_tariff_pence_per_kwh=seg_rate)
        )
    else:
        # Why this summary gets no SEG rate:
        # tests/unit/test_cli_summary_tables.py::TestPrintedSummaryTables::test_home_run_prints_a_seg_blocks_export_income_once
        summary = calculate_summary(results)
        console.print(
            create_summary_table(home_summary_rows(summary), title=f"Simulation Results: {home_config.name}")
        )

    # Export CSV if requested
    if output is not None:
        export_to_csv(results, output)
        print_success(f"Results saved to {output}")


_DEFAULT_LOAD = LoadConfig()


@app.command()
@handle_errors
def quick(
    pv_kw: Annotated[
        float,
        typer.Argument(help="PV system capacity in kW"),
    ],
    battery_kwh: Annotated[
        Optional[float],
        typer.Argument(help="Battery capacity in kWh (optional)"),
    ] = None,
    days: Annotated[
        int,
        typer.Option(
            "--days", "-d",
            help="Number of days to simulate",
        ),
    ] = 7,
    consumption_kwh: Annotated[
        Optional[float],
        typer.Option(
            "--consumption-kwh", "-c",
            help=(
                f"Annual consumption in kWh (default: {_DEFAULT_LOAD.get_annual_consumption():,.0f}, "
                f"the simulator's own figure for a {_DEFAULT_LOAD.household_occupants}-person household)"
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output CSV file path",
        ),
    ] = None,
) -> None:
    """Quick simulation with minimal arguments.

    Uses Bristol location and sensible defaults, simulating from 1 June 2024.
    Great for quick testing.

    Example:
        solar-challenge home quick 4 5 --days 7
    """
    loc = Location.bristol()

    pv_config = PVConfig(capacity_kw=pv_kw)

    battery_config = None
    if battery_kwh is not None and has_battery(battery_kwh, "battery_kwh"):
        battery_config = BatteryConfig(capacity_kwh=battery_kwh)

    load_config = dataclasses.replace(_DEFAULT_LOAD, annual_consumption_kwh=consumption_kwh)

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        location=loc,
        name="Quick Simulation",
    )

    start_date = pd.Timestamp("2024-06-01", tz=loc.timezone)
    end_date = start_date + pd.Timedelta(days=days - 1)

    print_info(f"Quick simulation: {pv_kw} kW PV, {battery_kwh or 0} kWh battery, {days} days")

    with create_progress() as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = simulate_home(home_config, start_date, end_date, weather=default_weather())
        progress.update(task, completed=True)

    summary = calculate_summary(results)
    console.print(
        create_summary_table(home_summary_rows(summary), title="Quick Simulation Results")
    )

    if output is not None:
        export_to_csv(results, output)
        print_success(f"Results saved to {output}")
