# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis."""

import dataclasses
import enum
from pathlib import Path
from typing import Annotated, Optional

import typer

from solar_challenge.cli.utils import (
    CliInvocation,
    EndOption,
    StartOption,
    handle_errors,
    invocation,
    print_info,
    print_report,
    required_finance,
    with_window_options,
)
from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.finance import (
    DEFAULT_SPREADSHEET_SELF_CONSUMPTION,
    BillDistribution,
    CostRecoverySolution,
    FinanceConfig,
    bill_distribution,
    grid_services_model_of,
)
from solar_challenge.flex import resolve_flex_band
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate, reusing
from solar_challenge.gridservices import (
    GridServicesAtEvents,
    GridServicesBand,
    GridServicesEventsConfig,
    GridServicesModel,
    compute_grid_services_at_events,
)
from solar_challenge.home import calculate_summary
from solar_challenge.output import generate_finance_report
from solar_challenge.projection import (
    ProjectEconomics,
    project_economics,
    project_fleet,
    run_cost_recovery,
    scenario_fleet,
)

app = typer.Typer(help="Financial analysis commands")


class AssumptionMode(str, enum.Enum):
    """Self-consumption assumption mode for bill calculation."""

    physics = "physics"
    spreadsheet = "spreadsheet"
    both = "both"


def _grid_services_at_events(
    fleet_results: FleetResults, pricing: GridServicesModel
) -> Optional[GridServicesAtEvents]:
    """The capacity-at-events grid-services income of *fleet_results* when *pricing* prices grid services that way, else None."""
    if not isinstance(pricing, GridServicesEventsConfig):
        return None
    return compute_grid_services_at_events(fleet_results, pricing)


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


def _economics_and_solution(
    cli: CliInvocation,
    scenario_config: ScenarioConfig,
    finance: FinanceConfig,
    simulate: FleetSimulate,
    *,
    project: bool,
    cost_recovery: bool,
) -> tuple[Optional[ProjectEconomics], Optional[CostRecoverySolution]]:
    """The project-level economics (DSCR/IRR/payback) if *project* and the cost-recovery solution if *cost_recovery* of *scenario_config*'s fleet under *finance*, from one projection run by *simulate*, after printing *cli*'s status line announcing each."""
    if project:
        print_info(cli, "Computing project-level economics (DSCR/IRR/payback)…")
    if cost_recovery:
        print_info(cli, "Solving cost-recovery own-use rate…")
    if not (project or cost_recovery):
        return None, None
    fleet = scenario_fleet(scenario_config)
    if cost_recovery:
        run = run_cost_recovery(fleet, finance, simulate=simulate)
        return (run.economics if project else None), run.solution
    return project_economics(project_fleet(fleet, finance, simulate=simulate).curve, fleet, finance), None


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
    start: StartOption = None,
    end: EndOption = None,
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
    scenario's period:, each of --start and --end replacing its own day, and
    prints a finance report showing the representative householder bill and
    fleet bill distribution.

    The scenario file must contain a ``finance:`` block with at least
    ``standing_charge_pence_per_day``.

    Example::

        solar-challenge finance run scenarios/bristol-phase1.yaml
        solar-challenge finance run scenarios/bristol-phase1.yaml \\
            --assumptions both --start 2024-06-01 --end 2024-08-31
    """
    scenario_config = with_window_options(load_scenario(scenario), start=start, end=end)
    finance = required_finance(scenario_config)
    pricing = grid_services_model_of(finance)
    band = flex_band if flex_band is not None else scenario_config.flex_band

    fleet_config = FleetConfig(homes=scenario_config.simulated_homes(), name=scenario_config.name)
    start_date, end_date = scenario_config.simulation_bounds()

    cli = invocation(ctx)
    print_info(cli, f"Simulating fleet of {len(fleet_config.homes)} homes for {scenario_config.window().days} days…")
    fleet_results = cli.runner.simulate(fleet_config, start_date, end_date)
    grid_services_at_events = _grid_services_at_events(fleet_results, pricing)

    summaries = [calculate_summary(r) for r in fleet_results.per_home_results]
    primary_finance, spreadsheet_finance = _bill_finances(assumptions, finance)
    primary_bill = bill_distribution(summaries, primary_finance)
    spreadsheet_bill: Optional[BillDistribution] = (
        bill_distribution(summaries, spreadsheet_finance)
        if spreadsheet_finance is not None
        else None
    )

    simulate = reusing(cli.runner.simulate, fleet_results, start_date, end_date)
    economics_result, cost_recovery_result = _economics_and_solution(
        cli, scenario_config, finance, simulate, project=project, cost_recovery=cost_recovery
    )

    report = generate_finance_report(
        primary_bill,
        spreadsheet_bill,
        scenario_name=scenario_config.name or str(scenario),
        economics=economics_result,
        cost_recovery=cost_recovery_result,
        flex_band=resolve_flex_band(band) if band is not None else None,
        flex_band_name=band.value if band is not None else "",
        grid_services_at_events=grid_services_at_events,
    )
    print_report(report)
