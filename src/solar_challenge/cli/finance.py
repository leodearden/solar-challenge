# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis (δ surface)."""

import dataclasses
import enum
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from solar_challenge.cli.utils import console, handle_errors, print_info
from solar_challenge.config import (
    ConfigurationError,
    load_config,
    load_fleet_config,
    _parse_finance_config,
    _parse_seg_config,
)
from solar_challenge.finance import DEFAULT_SPREADSHEET_SELF_CONSUMPTION, bill_distribution
from solar_challenge.fleet import FleetConfig, FleetResults, simulate_fleet
from solar_challenge.home import calculate_summary
from solar_challenge.output import generate_finance_report
from solar_challenge.seg import SEGTariff

app = typer.Typer(help="Financial analysis commands")


class AssumptionMode(str, enum.Enum):
    """Self-consumption assumption mode for bill calculation."""

    physics = "physics"
    spreadsheet = "spreadsheet"
    both = "both"


@app.command()
@handle_errors
def run(
    scenario: Annotated[
        Path,
        typer.Argument(
            help="Path to scenario YAML config file",
            exists=True,
            dir_okay=False,
        ),
    ],
    assumptions: Annotated[
        AssumptionMode,
        typer.Option(
            "--assumptions",
            help="Self-consumption assumption: physics (model), spreadsheet (override), or both",
            case_sensitive=False,
        ),
    ] = AssumptionMode.physics,
    start: Annotated[
        str,
        typer.Option(
            "--start",
            help="Simulation start date (YYYY-MM-DD)",
        ),
    ] = "2024-01-01",
    end: Annotated[
        str,
        typer.Option(
            "--end",
            help="Simulation end date (YYYY-MM-DD)",
        ),
    ] = "2024-12-31",
) -> None:
    """Run a householder bill analysis for a fleet scenario.

    Loads the fleet from the scenario YAML, simulates all homes over the
    specified date range, and prints a finance report showing the
    representative householder bill and fleet bill distribution.

    The scenario file must contain a ``finance:`` block with at least
    ``standing_charge_pence_per_day``.

    Example::

        solar-challenge finance run scenarios/bristol-phase1.yaml
        solar-challenge finance run scenarios/bristol-phase1.yaml \\
            --assumptions both --start 2024-06-01 --end 2024-08-31
    """
    # ---- Load raw config + finance block ------------------------------------
    raw = load_config(scenario)
    finance = _parse_finance_config(raw.get("finance"))
    if finance is None:
        raise ConfigurationError(
            "No 'finance:' block found in the scenario file. "
            "Add a finance: block with at least standing_charge_pence_per_day."
        )

    # ---- Load fleet config --------------------------------------------------
    fleet_config = load_fleet_config(scenario)

    # Thread SEG tariff onto each home (load_fleet_config does not do this)
    seg_rate = _parse_seg_config(raw.get("seg"))
    if seg_rate is not None:
        seg_tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)
        homes_with_seg = [
            dataclasses.replace(home, seg_tariff=seg_tariff)
            for home in fleet_config.homes
        ]
        fleet_config = dataclasses.replace(fleet_config, homes=homes_with_seg)

    # ---- Parse dates --------------------------------------------------------
    loc = fleet_config.homes[0].location
    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)
    days = (end_date - start_date).days + 1

    n_homes = len(fleet_config.homes)
    print_info(f"Simulating fleet of {n_homes} homes for {days} days…")

    # ---- Simulate fleet -----------------------------------------------------
    fleet_results: FleetResults = simulate_fleet(fleet_config, start_date, end_date)

    # ---- Per-home summaries -------------------------------------------------
    summaries = [
        calculate_summary(r) for r in fleet_results.per_home_results
    ]

    # ---- Build bill distributions -------------------------------------------
    # Only compute the distributions that are actually needed for the selected
    # --assumptions mode.  dist_physics is skipped for spreadsheet-only to
    # avoid unnecessary arithmetic (cheap but misleading control flow).
    dist_physics = None
    if assumptions in (AssumptionMode.physics, AssumptionMode.both):
        finance_physics = dataclasses.replace(finance, self_consumption_override=None)
        dist_physics = bill_distribution(summaries, finance_physics, days)

    dist_spreadsheet = None
    if assumptions in (AssumptionMode.spreadsheet, AssumptionMode.both):
        # Use the finance.self_consumption_override if set, otherwise use the
        # module-level default documented alongside the other finance constants.
        override_val = (
            finance.self_consumption_override
            if finance.self_consumption_override is not None
            else DEFAULT_SPREADSHEET_SELF_CONSUMPTION
        )
        finance_spreadsheet = dataclasses.replace(
            finance, self_consumption_override=override_val
        )
        dist_spreadsheet = bill_distribution(summaries, finance_spreadsheet, days)

    # ---- Render report ------------------------------------------------------
    if assumptions == AssumptionMode.physics:
        assert dist_physics is not None
        report = generate_finance_report(
            dist_physics,
            scenario_name=raw.get("name", str(scenario)),
        )
    elif assumptions == AssumptionMode.spreadsheet:
        assert dist_spreadsheet is not None
        report = generate_finance_report(
            dist_spreadsheet,
            scenario_name=raw.get("name", str(scenario)),
        )
    else:  # both
        assert dist_physics is not None
        assert dist_spreadsheet is not None
        report = generate_finance_report(
            dist_physics,
            bill_spreadsheet=dist_spreadsheet,
            scenario_name=raw.get("name", str(scenario)),
        )

    console.print(report)
