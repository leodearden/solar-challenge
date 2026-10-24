# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis."""

import dataclasses
import enum
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Optional

import pandas as pd
import typer

from solar_challenge.cli.utils import CliFleetSimulator, handle_errors, print_info, print_report
from solar_challenge.config import (
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    load_fleet_config,
    parse_finance_config,
    parse_seg_rate,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import (
    DEFAULT_SPREADSHEET_SELF_CONSUMPTION,
    BillDistribution,
    CostRecoverySolution,
    FinanceConfig,
    ProjectEconomics,
    bill_distribution,
    project_economics,
    project_multi_year,
    solve_cost_recovery_rate,
)
from solar_challenge.flex import resolve_flex_band
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.gridservices import (
    GridServicesAtEvents,
    GridServicesBand,
    compute_grid_services_at_events,
)
from solar_challenge.home import calculate_summary
from solar_challenge.output import generate_finance_report
from solar_challenge.seg import SEGTariff

app = typer.Typer(help="Financial analysis commands")


class AssumptionMode(str, enum.Enum):
    """Self-consumption assumption mode for bill calculation."""

    physics = "physics"
    spreadsheet = "spreadsheet"
    both = "both"


def _required_finance_block(raw: Mapping[str, Any]) -> FinanceConfig:
    """The scenario's parsed finance: block, raising ConfigurationError when it has none."""
    finance = parse_finance_config(raw.get("finance"))
    if finance is None:
        raise ConfigurationError(
            "No 'finance:' block found in the scenario file. "
            "Add a finance: block with at least standing_charge_pence_per_day."
        )
    return finance


def _flex_band(
    flag: Optional[GridServicesBand], scenario_value: object
) -> Optional[GridServicesBand]:
    """The flexibility band to report: the --flex-band flag's, else the scenario's flex_band key's, else None when the key is absent or null.

    A string key is read case-insensitively, as the flag is; any other value is
    refused with ConfigurationError.
    """
    if flag is not None:
        return flag
    if scenario_value is None:
        return None
    return GridServicesBand.parse(
        scenario_value.lower() if isinstance(scenario_value, str) else scenario_value,
        what="flex_band",
    )


def _with_seg_tariff(fleet_config: FleetConfig, seg_rate: Optional[float]) -> FleetConfig:
    """*fleet_config* with *seg_rate* pence/kWh as every home's SEG export tariff (load_fleet_config sets none), or *fleet_config* itself when *seg_rate* is None."""
    if seg_rate is None:
        return fleet_config
    seg_tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)
    return dataclasses.replace(
        fleet_config,
        homes=[dataclasses.replace(home, seg_tariff=seg_tariff) for home in fleet_config.homes],
    )


def _grid_services_at_events(
    fleet_results: FleetResults, finance: FinanceConfig
) -> Optional[GridServicesAtEvents]:
    """The capacity-at-events grid-services income of *fleet_results* when *finance* prices grid services that way, else None."""
    if finance.grid_services_model != "capacity_at_events" or finance.grid_services_events is None:
        return None
    return compute_grid_services_at_events(fleet_results, finance.grid_services_events)


def _bill_finances(
    assumptions: AssumptionMode, finance: FinanceConfig
) -> tuple[FinanceConfig, Optional[FinanceConfig]]:
    """The FinanceConfigs of the report's first and second bill columns: for --assumptions physics or spreadsheet that mode's config and None, for both the physics config then the spreadsheet config."""
    physics = dataclasses.replace(finance, self_consumption_override=None)
    spreadsheet = dataclasses.replace(
        finance,
        self_consumption_override=(
            finance.self_consumption_override
            if finance.self_consumption_override is not None
            else DEFAULT_SPREADSHEET_SELF_CONSUMPTION
        ),
    )
    pairs: dict[AssumptionMode, tuple[FinanceConfig, Optional[FinanceConfig]]] = {
        AssumptionMode.physics: (physics, None),
        AssumptionMode.spreadsheet: (spreadsheet, None),
        AssumptionMode.both: (physics, spreadsheet),
    }
    return pairs[assumptions]


def _project_level_economics(
    scenario_config: ScenarioConfig, finance: FinanceConfig, simulator: CliFleetSimulator
) -> ProjectEconomics:
    """The project-level economics (DSCR/IRR/payback) of *scenario_config*'s fleet under *finance*, its simulations run by *simulator*."""
    print_info("Computing project-level economics (DSCR/IRR/payback)…")
    curve = project_multi_year(scenario_config, finance, simulate=simulator.simulate)
    return project_economics(curve, scenario_config, finance)


def _cost_recovery_solution(
    scenario_config: ScenarioConfig, finance: FinanceConfig, simulator: CliFleetSimulator
) -> CostRecoverySolution:
    """The own-use rate at which *scenario_config*'s fleet recovers its cost under *finance*, its simulations run by *simulator*."""
    print_info("Solving cost-recovery own-use rate…")
    return solve_cost_recovery_rate(scenario_config, finance, simulate=simulator.simulate)


@app.command()
@handle_errors
def run(
    ctx: typer.Context,
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
        Optional[GridServicesBand],
        typer.Option(
            "--flex-band",
            help=(
                "Render the flexibility-value (time-shift / grid-services) block for the "
                "given uncertainty band; overrides a scenario-level flex_band key."
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
    raw = load_config(scenario)
    finance = _required_finance_block(raw)
    band = _flex_band(flex_band, raw.get("flex_band"))

    fleet_config = load_fleet_config(scenario)
    seg_rate = parse_seg_rate(raw.get("seg"))
    fleet_config = _with_seg_tariff(fleet_config, seg_rate)

    loc = fleet_config.homes[0].location
    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)
    days = (end_date - start_date).days + 1

    print_info(f"Simulating fleet of {len(fleet_config.homes)} homes for {days} days…")
    simulator = ctx.ensure_object(CliFleetSimulator)
    fleet_results = simulator.simulate(fleet_config, start_date, end_date)
    grid_services_at_events = _grid_services_at_events(fleet_results, finance)

    summaries = [calculate_summary(r) for r in fleet_results.per_home_results]
    primary_finance, spreadsheet_finance = _bill_finances(assumptions, finance)
    primary_bill = bill_distribution(summaries, primary_finance, days)
    spreadsheet_bill: Optional[BillDistribution] = (
        bill_distribution(summaries, spreadsheet_finance, days)
        if spreadsheet_finance is not None
        else None
    )

    scenario_config = ScenarioConfig(
        name=raw.get("name", str(scenario)),
        period=SimulationPeriod(start_date=start, end_date=end),
        homes=list(fleet_config.homes),
        location=loc,
        finance=finance,
        # Only --cost-recovery passes the rate on:
        # tests/integration/test_finance_run_cli.py::test_project_economics_are_the_same_with_and_without_cost_recovery
        seg_tariff_pence_per_kwh=seg_rate if cost_recovery else None,
    )
    economics_result = (
        _project_level_economics(scenario_config, finance, simulator) if project else None
    )
    cost_recovery_result = (
        _cost_recovery_solution(scenario_config, finance, simulator) if cost_recovery else None
    )

    report = generate_finance_report(
        primary_bill,
        spreadsheet_bill,
        scenario_name=scenario_config.name,
        economics=economics_result,
        cost_recovery=cost_recovery_result,
        flex_band=resolve_flex_band(band) if band is not None else None,
        flex_band_name=band.value if band is not None else "",
        grid_services_at_events=grid_services_at_events,
    )
    print_report(report)
