# SPDX-License-Identifier: AGPL-3.0-or-later
"""Home simulation commands."""

import dataclasses
from collections.abc import Callable
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
    invocation,
    print_info,
    print_report,
    print_success,
)
from solar_challenge.config import ScenarioConfig, load_scenario, parse_scenario
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.location import LOCATION_PRESETS, Location, parse_location
from solar_challenge.output import export_to_csv, generate_summary_report
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import refusal
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, SHORT_WINDOW_START, covered_days

app = typer.Typer(help="Single home simulation commands")


_HomeTransform = Callable[[HomeConfig], HomeConfig]


def scenario_for_run(
    config: Optional[Path],
    *,
    pv_kw: Optional[float] = None,
    battery_kwh: Optional[float] = None,
    consumption_kwh: Optional[float] = None,
    location_str: Optional[str] = None,
    system_losses: Optional[float] = None,
) -> ScenarioConfig:
    """The one-home scenario `home run` reads: the file's, as config.load_scenario reads it, else the default home's, with each command-line override given applied to it.

    location_str moves the scenario, its period's clock and its home to the location
    location.parse_location reads; pv_kw, system_losses, consumption_kwh and battery_kwh
    each replace only their own setting of the home. A battery_kwh of 0 removes the
    home's battery, and a home with none is given one of that capacity.

    Raises:
        ConfigurationError: as load_scenario refuses the file; for a fleet scenario, naming
            how many homes it holds and `fleet run`; as parse_location refuses location_str,
            or has_battery refuses battery_kwh, naming --battery-kwh; and for an override
            its home's config refuses, that config's own message under the option's name.
    """
    scenario = parse_scenario({"home": {}}) if config is None else load_scenario(config)
    if scenario.home is None:
        count = len(scenario.homes)
        raise refusal(
            "",
            f"holds a fleet of {'1 home' if count == 1 else f'{count} homes'}, not a home: block: "
            "simulate it with `fleet run`",
        )
    if location_str is not None:
        scenario = _relocated(scenario, parse_location(location_str))
    for option, transform in _home_overrides(
        pv_kw=pv_kw, system_losses=system_losses, consumption_kwh=consumption_kwh, battery_kwh=battery_kwh
    ):
        scenario = _overridden(scenario, option, transform)
    return scenario


def _relocated(scenario: ScenarioConfig, location: Location) -> ScenarioConfig:
    """*scenario* at *location*: its own location, its period on location's clock and each of its homes."""
    moved = dataclasses.replace(
        scenario, location=location, period=dataclasses.replace(scenario.period, timezone=location.timezone)
    )
    return moved.map_homes(lambda home: dataclasses.replace(home, location=location))


def _home_overrides(
    *,
    pv_kw: Optional[float],
    system_losses: Optional[float],
    consumption_kwh: Optional[float],
    battery_kwh: Optional[float],
) -> tuple[tuple[str, _HomeTransform], ...]:
    """The (option, transform) pair of each override given, in the order --pv-kw, --system-losses, --consumption-kwh, --battery-kwh."""
    builders: tuple[tuple[str, Optional[float], Callable[[float], _HomeTransform]], ...] = (
        ("--pv-kw", pv_kw, _with_pv_capacity),
        ("--system-losses", system_losses, _with_system_losses),
        ("--consumption-kwh", consumption_kwh, _with_annual_consumption),
        ("--battery-kwh", battery_kwh, _with_battery_capacity),
    )
    return tuple((option, build(value)) for option, value, build in builders if value is not None)


def _with_pv_capacity(kw: float) -> _HomeTransform:
    """The home with its PV capacity replaced by *kw*."""
    return lambda home: dataclasses.replace(home, pv_config=dataclasses.replace(home.pv_config, capacity_kw=kw))


def _with_system_losses(fraction: float) -> _HomeTransform:
    """The home with its PV system losses replaced by *fraction*."""
    return lambda home: dataclasses.replace(
        home, pv_config=dataclasses.replace(home.pv_config, system_losses=fraction)
    )


def _with_annual_consumption(kwh: float) -> _HomeTransform:
    """The home with its annual consumption replaced by *kwh*."""
    return lambda home: dataclasses.replace(
        home, load_config=dataclasses.replace(home.load_config, annual_consumption_kwh=kwh)
    )


def _with_battery_capacity(kwh: float) -> _HomeTransform:
    """The home with no battery for a *kwh* of 0, else its battery's capacity replaced by *kwh*, or a battery of that capacity when it has none.

    Raises:
        ConfigurationError: from has_battery, naming --battery-kwh, for a *kwh* that is
            negative or not finite.
    """
    if not has_battery(kwh, "--battery-kwh"):
        return lambda home: dataclasses.replace(home, battery_config=None)

    def with_capacity(home: HomeConfig) -> HomeConfig:
        battery = home.battery_config
        resized = BatteryConfig(capacity_kwh=kwh) if battery is None else dataclasses.replace(battery, capacity_kwh=kwh)
        return dataclasses.replace(home, battery_config=resized)

    return with_capacity


def _overridden(scenario: ScenarioConfig, option: str, transform: _HomeTransform) -> ScenarioConfig:
    """*scenario* with *transform* applied to its home, a refusal of the result re-raised under *option*'s name."""
    try:
        return scenario.map_homes(transform)
    except ConfigurationError as exc:
        raise ConfigurationError(f"{option}: {exc}") from exc


def home_config_for_run(
    config: Optional[Path],
    *,
    pv_kw: Optional[float] = None,
    battery_kwh: Optional[float] = None,
    consumption_kwh: Optional[float] = None,
    location_str: Optional[str] = None,
    system_losses: Optional[float] = None,
) -> HomeConfig:
    """The one home `home run` simulates: scenario_for_run's, exporting at the file's SEG rate unless it sets its own.

    Raises:
        ConfigurationError: as scenario_for_run refuses the file or an override.
    """
    (home,) = scenario_for_run(
        config,
        pv_kw=pv_kw,
        battery_kwh=battery_kwh,
        consumption_kwh=consumption_kwh,
        location_str=location_str,
        system_losses=system_losses,
    ).simulated_homes()
    return home


@app.command()
@handle_errors
def run(
    ctx: typer.Context,
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
    ] = DEFAULT_FIRST_DAY.isoformat(),
    end: Annotated[
        str,
        typer.Option(
            "--end",
            help="End date (YYYY-MM-DD)",
        ),
    ] = DEFAULT_LAST_DAY.isoformat(),
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
            help=(
                "Override the capacity (kWh) of the file's battery, keeping its other settings, "
                "or give a home without one a battery of that capacity; 0 for no battery"
            ),
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
                f"Location: a preset (case-insensitive), one of {', '.join(LOCATION_PRESETS)}; "
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
    scenario = scenario_for_run(
        config,
        pv_kw=pv_kw,
        battery_kwh=battery_kwh,
        consumption_kwh=consumption_kwh,
        location_str=location,
        system_losses=system_losses,
    )
    (home_config,) = scenario.simulated_homes()
    # Parse dates
    start_date = pd.Timestamp(start, tz=home_config.location.timezone)
    end_date = pd.Timestamp(end, tz=home_config.location.timezone)

    days_count = covered_days(start_date.date(), end_date.date())
    cli = invocation(ctx)
    print_info(cli, f"Simulating {days_count} days from {start} to {end}")

    # Run simulation with progress
    with create_progress(cli) as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = cli.runner.simulate_home(home_config, start_date, end_date)
        progress.update(task, completed=True)

    if report:
        print_report(generate_summary_report(results, home_config.name))
    else:
        summary = calculate_summary(results)
        console.print(
            create_summary_table(home_summary_rows(summary), title=f"Simulation Results: {home_config.name}")
        )

    # Export CSV if requested
    if output is not None:
        export_to_csv(results, output)
        print_success(cli, f"Results saved to {output}")


_DEFAULT_LOAD = LoadConfig()


@app.command()
@handle_errors
def quick(
    ctx: typer.Context,
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

    start_date = pd.Timestamp(SHORT_WINDOW_START, tz=loc.timezone)
    end_date = start_date + pd.Timedelta(days=days - 1)

    cli = invocation(ctx)
    print_info(cli, f"Quick simulation: {pv_kw} kW PV, {battery_kwh or 0} kWh battery, {days} days")

    with create_progress(cli) as progress:
        task = progress.add_task("Running simulation...", total=None)
        results = cli.runner.simulate_home(home_config, start_date, end_date)
        progress.update(task, completed=True)

    summary = calculate_summary(results)
    console.print(
        create_summary_table(home_summary_rows(summary), title="Quick Simulation Results")
    )

    if output is not None:
        export_to_csv(results, output)
        print_success(cli, f"Results saved to {output}")
