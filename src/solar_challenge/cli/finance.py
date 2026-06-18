# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis (δ surface)."""

import dataclasses
import enum
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import typer

from solar_challenge.cli.utils import console, handle_errors, print_info
from solar_challenge.config import (
    ConfigurationError,
    ScenarioConfig,
    SimulationPeriod,
    _parse_finance_config,
    _parse_seg_config,
    load_config,
    load_fleet_config,
)
from solar_challenge.finance import (
    DEFAULT_SPREADSHEET_SELF_CONSUMPTION,
    CostRecoverySolution,
    ProjectEconomics,
    bill_distribution,
    project_economics,
    project_multi_year,
    solve_cost_recovery_rate,
)
from solar_challenge.flex import FlexibilityValueBand, resolve_flex_band
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


class FlexBand(str, enum.Enum):
    """Flexibility-value uncertainty band for the finance report block."""

    low = "low"
    central = "central"
    high = "high"


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
    project: Annotated[
        bool,
        typer.Option(
            "--project/--no-project",
            help="Compute project-level economics (DSCR/IRR/payback) and append to report",
        ),
    ] = False,
    cost_recovery: Annotated[
        bool,
        typer.Option(
            "--cost-recovery/--no-cost-recovery",
            help=(
                "Solve the cost-recovery own-use rate and append a ## Cost-Recovery Analysis "
                "block with the solved rate, householder outlay distribution, "
                "CBS surplus vs floor, and feasibility"
            ),
        ),
    ] = False,
    flex_band: Annotated[
        Optional[FlexBand],
        typer.Option(
            "--flex-band",
            help=(
                "Render the flexibility-value (time-shift / grid-services) block for the "
                "given uncertainty band {low,central,high}; overrides a scenario-level "
                "flex_band key."
            ),
            case_sensitive=False,
        ),
    ] = None,
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

    # ---- Resolve flexibility band (CLI flag > scenario key > None) ----------
    # Scenario-level values are normalised to lowercase to match the CLI's
    # case-insensitive FlexBand enum behaviour (e.g. "Central" → "central").
    _raw_band = raw.get("flex_band")
    band_name: Optional[str] = (
        flex_band.value
        if flex_band is not None
        else (_raw_band.lower() if isinstance(_raw_band, str) else None)
    )
    resolved_flex_band: Optional[FlexibilityValueBand] = (
        resolve_flex_band(band_name) if band_name else None
    )
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

    # ---- Capacity-at-events grid-services figure (ε / task-76) -------------
    # Computed once from the already-available fleet_results; None for flat model.
    from solar_challenge.gridservices import GridServicesAtEvents as _GSAtEvents
    from solar_challenge.gridservices import compute_grid_services_at_events as _cgs

    _grid_services_at_events: Optional[_GSAtEvents] = (
        _cgs(fleet_results, finance.grid_services_events)
        if finance.grid_services_model == "capacity_at_events"
        and finance.grid_services_events is not None
        else None
    )

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

    # ---- Build shared ScenarioConfig (used by --project and/or --cost-recovery) ---
    econ_scenario: Optional[ScenarioConfig] = None
    if project or cost_recovery:
        _base = ScenarioConfig(
            name=raw.get("name", str(scenario)),
            period=SimulationPeriod(
                start_date=start,
                end_date=end,
            ),
            homes=list(fleet_config.homes),
            location=loc,
            finance=finance,
        )
        if cost_recovery and seg_rate is not None:
            # Thread seg_tariff_pence_per_kwh only when --cost-recovery is active so that
            # --project-only output is unchanged from pre-CR5 behaviour (avoids silently
            # changing project_multi_year SEG revenue for existing --project callers).
            econ_scenario = dataclasses.replace(_base, seg_tariff_pence_per_kwh=seg_rate)
        else:
            econ_scenario = _base

    # ---- Project economics (optional) ---------------------------------------
    economics_result: Optional[ProjectEconomics] = None
    if project:
        assert econ_scenario is not None
        print_info("Computing project-level economics (DSCR/IRR/payback)…")
        curve = project_multi_year(econ_scenario, finance)
        economics_result = project_economics(curve, econ_scenario, finance)

    # ---- Cost-recovery solve (optional) ------------------------------------
    cost_recovery_result: Optional[CostRecoverySolution] = None
    if cost_recovery:
        assert econ_scenario is not None
        print_info("Solving cost-recovery own-use rate…")
        cost_recovery_result = solve_cost_recovery_rate(econ_scenario, finance)

    # ---- Render report ------------------------------------------------------
    if assumptions == AssumptionMode.physics:
        assert dist_physics is not None
        report = generate_finance_report(
            dist_physics,
            scenario_name=raw.get("name", str(scenario)),
            economics=economics_result,
            cost_recovery=cost_recovery_result,
            flex_band=resolved_flex_band,
            flex_band_name=band_name or "",
            grid_services_at_events=_grid_services_at_events,
        )
    elif assumptions == AssumptionMode.spreadsheet:
        assert dist_spreadsheet is not None
        report = generate_finance_report(
            dist_spreadsheet,
            scenario_name=raw.get("name", str(scenario)),
            economics=economics_result,
            cost_recovery=cost_recovery_result,
            flex_band=resolved_flex_band,
            flex_band_name=band_name or "",
            grid_services_at_events=_grid_services_at_events,
        )
    else:  # both
        assert dist_physics is not None
        assert dist_spreadsheet is not None
        report = generate_finance_report(
            dist_physics,
            bill_spreadsheet=dist_spreadsheet,
            scenario_name=raw.get("name", str(scenario)),
            economics=economics_result,
            cost_recovery=cost_recovery_result,
            flex_band=resolved_flex_band,
            flex_band_name=band_name or "",
            grid_services_at_events=_grid_services_at_events,
        )

    console.print(report)
