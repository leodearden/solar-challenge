# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration management commands."""

from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.syntax import Syntax
from rich.table import Table

from solar_challenge.cli.utils import (
    console,
    handle_errors,
    print_success,
)
from solar_challenge.config import load_config
from solar_challenge.location import Location

app = typer.Typer(help="Configuration management commands")


# Template configurations
HOME_TEMPLATE = """\
# Single home simulation configuration
# All fields are optional - defaults will be used if not specified

# Geographic location (defaults to Bristol, UK)
location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
  altitude: 11.0
  name: Bristol, UK

# Simulation period
period:
  start_date: "2024-01-01"
  end_date: "2024-12-31"

# Home configuration
home:
  name: "My Home"

  # PV system configuration
  pv:
    capacity_kw: 4.0        # DC capacity in kW
    azimuth: 180.0          # Orientation: 0=N, 90=E, 180=S, 270=W
    tilt: 35.0              # Tilt from horizontal (degrees)

  # Battery configuration (remove section for PV-only)
  battery:
    capacity_kwh: 5.0       # Total capacity in kWh
    max_charge_kw: 2.5      # Max charging power
    max_discharge_kw: 2.5   # Max discharging power

  # Load/consumption configuration
  load:
    annual_consumption_kwh: 3400.0  # Target annual consumption
    household_occupants: 3          # Used if consumption not specified
    use_stochastic: true            # Use stochastic model if available

# Output configuration (optional)
output:
  csv_path: results.csv
  include_summary: true
"""

FLEET_TEMPLATE = """\
# Fleet simulation configuration
# Defines multiple homes with potentially different configurations

name: "My Fleet"

# Shared location for all homes
location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
  altitude: 11.0
  name: Bristol, UK

# List of homes in the fleet
homes:
  - name: "Home 1"
    pv:
      capacity_kw: 4.0
    battery:
      capacity_kwh: 5.0
    load:
      annual_consumption_kwh: 3200.0

  - name: "Home 2"
    pv:
      capacity_kw: 3.0
    # No battery for this home
    load:
      annual_consumption_kwh: 2800.0

  - name: "Home 3"
    pv:
      capacity_kw: 5.0
    battery:
      capacity_kwh: 10.0
    load:
      annual_consumption_kwh: 4200.0
"""

SCENARIO_TEMPLATE = """\
# Scenario configuration
# Can define single home or fleet with simulation period

name: "Annual Simulation"
description: "Full year simulation of typical UK home"

location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London

period:
  start_date: "2024-01-01"
  end_date: "2024-12-31"

# Single home scenario (use 'homes' instead for fleet)
home:
  pv:
    capacity_kw: 4.0
    azimuth: 180.0
    tilt: 35.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400.0

output:
  csv_path: scenario_results.csv
  include_summary: true
"""


@app.command()
@handle_errors
def show(
    config_file: Annotated[
        Path,
        typer.Argument(
            help="Path to config file to display",
            exists=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Display a parsed configuration file.

    Shows the configuration with syntax highlighting and validates
    that it can be parsed correctly.
    """
    # Load to validate
    config_data = load_config(config_file)

    # Read raw content for display
    content = config_file.read_text()

    # Determine syntax type
    suffix = config_file.suffix.lower()
    if suffix in (".yaml", ".yml"):
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
    elif suffix == ".json":
        syntax = Syntax(content, "json", theme="monokai", line_numbers=True)
    else:
        syntax = Syntax(content, "text", theme="monokai", line_numbers=True)

    console.print(f"\n[bold]Configuration:[/bold] {config_file}\n")
    console.print(syntax)

    # Show summary
    console.print("\n[bold]Parsed Summary:[/bold]")
    table = Table()
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    def _add_nested(data: dict[str, Any], prefix: str = "") -> None:
        for key, value in data.items():
            full_key = f"{prefix}{key}"
            if isinstance(value, dict):
                _add_nested(value, f"{full_key}.")
            elif isinstance(value, list):
                table.add_row(full_key, f"[{len(value)} items]")
            else:
                table.add_row(full_key, str(value))

    _add_nested(config_data)
    console.print(table)


@app.command()
@handle_errors
def template(
    template_type: Annotated[
        str,
        typer.Argument(
            help="Template type: home, fleet, or scenario",
        ),
    ] = "home",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output file path (prints to stdout if not specified)",
        ),
    ] = None,
) -> None:
    """Generate a template configuration file.

    Available templates:
    - home: Single home configuration
    - fleet: Multiple homes configuration
    - scenario: Full scenario with period and output settings
    """
    templates = {
        "home": HOME_TEMPLATE,
        "fleet": FLEET_TEMPLATE,
        "scenario": SCENARIO_TEMPLATE,
    }

    template_type_lower = template_type.lower()
    if template_type_lower not in templates:
        console.print(
            f"[red]Unknown template type: {template_type}[/red]\n"
            f"Available: {', '.join(templates.keys())}"
        )
        raise typer.Exit(1)

    content = templates[template_type_lower]

    if output is not None:
        output.write_text(content)
        print_success(f"Template written to {output}")
    else:
        syntax = Syntax(content, "yaml", theme="monokai")
        console.print(syntax)


@app.command()
@handle_errors
def locations() -> None:
    """List known locations and custom location format.

    Shows built-in location presets and explains how to specify
    custom locations.
    """
    console.print("\n[bold]Built-in Locations[/bold]\n")

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Latitude")
    table.add_column("Longitude")
    table.add_column("Timezone")
    table.add_column("Altitude (m)")

    # Bristol
    bristol = Location.bristol()
    table.add_row(
        "bristol",
        f"{bristol.latitude:.2f}",
        f"{bristol.longitude:.2f}",
        bristol.timezone,
        f"{bristol.altitude:.0f}",
    )

    console.print(table)

    console.print("\n[bold]Custom Location Format[/bold]\n")
    console.print("Use the --location option with coordinates:\n")
    console.print("  [cyan]--location 'lat,lon'[/cyan]")
    console.print("  Example: --location '51.50,-0.12'  (London)\n")
    console.print("  [cyan]--location 'lat,lon,altitude'[/cyan]")
    console.print("  Example: --location '51.50,-0.12,11'\n")

    console.print("[bold]In Config Files[/bold]\n")
    console.print("  location:")
    console.print("    latitude: 51.50")
    console.print("    longitude: -0.12")
    console.print("    timezone: Europe/London")
    console.print("    altitude: 11.0")
    console.print("    name: London, UK\n")
