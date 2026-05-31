# SPDX-License-Identifier: AGPL-3.0-or-later
"""Home simulation commands."""

import dataclasses
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import typer

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.utils import (
    console,
    create_progress,
    create_summary_table,
    handle_errors,
    load_config_with_overrides,
    parse_location,
    print_info,
    print_success,
)
from solar_challenge.config import _parse_home_config, _parse_seg_config
from solar_challenge.home import HomeConfig, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.output import export_to_csv, generate_summary_report
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff

app = typer.Typer(help="Single home simulation commands")


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
            help="Print markdown summary report",
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
            help="Location preset or 'lat,lon' (e.g., 'bristol' or '51.45,-2.58')",
        ),
    ] = None,
) -> None:
    """Run a single home simulation from config file or CLI arguments.

    If no config file is provided, uses default values with any CLI overrides.
    """
    # Build config dict with CLI overrides merged in
    config_dict = load_config_with_overrides(
        config,
        pv_kw=pv_kw,
        battery_kwh=battery_kwh,
        consumption_kwh=consumption_kwh,
        location_str=location,
    )

    # Parse location
    loc_data = config_dict.get("location")
    if loc_data:
        loc = Location(
            latitude=loc_data.get("latitude", 51.45),
            longitude=loc_data.get("longitude", -2.58),
            timezone=loc_data.get("timezone", "Europe/London"),
            altitude=loc_data.get("altitude", 11.0),
            name=loc_data.get("name", ""),
        )
    else:
        loc = Location.bristol()

    # Build home config via canonical parser (honours tariff, dispatch_strategy,
    # heat_pump, ev, pv-age, etc. — previously silently dropped by hand-built path)
    home_config = _parse_home_config(config_dict.get("home", {}), loc)

    # Parse top-level SEG block (sibling of `home:`) and thread onto config + summaries
    seg_rate = _parse_seg_config(config_dict.get("seg"))
    if seg_rate is not None:
        home_config = dataclasses.replace(
            home_config,
            seg_tariff=SEGTariff(name="", rate_pence_per_kwh=seg_rate),
        )

    # Parse dates
    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    # Calculate simulation duration for progress display
    days_count = (end_date - start_date).days + 1
    print_info(f"Simulating {days_count} days from {start} to {end}")

    # Run simulation with progress
    with create_progress() as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = simulate_home(home_config, start_date, end_date)
        progress.update(task, completed=True)

    # Calculate summary for the default table.  When seg_tariff is already set on
    # HomeConfig, the engine prices every export timestep at the SEG rate, so
    # total_export_revenue_gbp is the authoritative figure.  Omitting
    # seg_tariff_pence_per_kwh here prevents a duplicate "SEG Revenue" row in the
    # table that would equal "Grid Export Revenue" and mislead users into thinking
    # the revenue is counted twice.  The --report path below still passes seg_rate to
    # generate_summary_report so the detailed "## SEG Revenue" section appears there.
    summary = calculate_summary(results)

    # Display summary table
    table = create_summary_table(summary, title=f"Simulation Results: {home_config.name}")
    console.print(table)

    # Export CSV if requested
    if output is not None:
        export_to_csv(results, output)
        print_success(f"Results saved to {output}")

    # Print report if requested
    if report:
        console.print()
        report_text = generate_summary_report(
            results, home_config.name, seg_tariff_pence_per_kwh=seg_rate
        )
        console.print(report_text)


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
        float,
        typer.Option(
            "--consumption-kwh", "-c",
            help="Annual consumption in kWh",
        ),
    ] = 3400.0,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output CSV file path",
        ),
    ] = None,
) -> None:
    """Quick simulation with minimal arguments.

    Uses Bristol location and sensible defaults. Great for quick testing.

    Example:
        solar-challenge home quick 4 5 --days 7
    """
    loc = Location.bristol()

    pv_config = PVConfig(capacity_kw=pv_kw)

    battery_config = None
    if battery_kwh is not None and battery_kwh > 0:
        battery_config = BatteryConfig(capacity_kwh=battery_kwh)

    load_config = LoadConfig(annual_consumption_kwh=consumption_kwh)

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        location=loc,
        name="Quick Simulation",
    )

    # Default to starting today
    start_date = pd.Timestamp("2024-06-01", tz=loc.timezone)
    end_date = start_date + pd.Timedelta(days=days - 1)

    print_info(f"Quick simulation: {pv_kw} kW PV, {battery_kwh or 0} kWh battery, {days} days")

    with create_progress() as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = simulate_home(home_config, start_date, end_date)
        progress.update(task, completed=True)

    summary = calculate_summary(results)
    table = create_summary_table(summary, title="Quick Simulation Results")
    console.print(table)

    if output is not None:
        export_to_csv(results, output)
        print_success(f"Results saved to {output}")
