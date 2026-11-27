# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis."""

from pathlib import Path
from typing import Annotated, Optional, Sequence

import typer

from solar_challenge.board_report import AssumptionSection, FlexBlock, GridServicesIncome, generate_finance_report
from solar_challenge.cli.utils import (
    ASSUMPTION_BASES,
    AssumptionMode,
    EndOption,
    StartOption,
    handle_errors,
    invocation,
    print_info,
    print_report,
    required_finance,
    with_window_options,
)
from solar_challenge.config import load_scenario
from solar_challenge.finance import (
    FinanceConfig,
    bill_distribution,
    with_own_use_basis,
)
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate, reusing
from solar_challenge.gridservices import (
    GridServicesBand,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
    compute_grid_services_at_events,
)
from solar_challenge.home import SummaryStatistics, calculate_summary
from solar_challenge.projection import (
    ScenarioFleet,
    project_economics,
    project_fleet,
    run_cost_recovery,
    scenario_fleet,
)

app = typer.Typer(help="Financial analysis commands")


def _grid_services_income(fleet_results: FleetResults, pricing: GridServicesModel) -> Optional[GridServicesIncome]:
    """What *pricing* books on *fleet_results*, the bill run's fleet, or None when it prices no grid services.

    Under events pricing the income is the capacity-at-events breakdown's,
    priced once, on the path ``pricing.annual_income_gbp`` prices.
    """
    if isinstance(pricing, NoGridServices):
        return None
    batteries = [home.battery_config for home in fleet_results.home_configs if home.battery_config is not None]
    at_events = (
        compute_grid_services_at_events(fleet_results, pricing)
        if isinstance(pricing, GridServicesEventsConfig)
        else None
    )
    return GridServicesIncome(
        pricing=pricing,
        annual_income_gbp=pricing.annual_income_gbp(fleet_results) if at_events is None else at_events.annual_income_gbp,
        battery_homes=len(batteries),
        battery_discharge_kw=sum(battery.max_discharge_kw for battery in batteries),
        at_events=at_events,
    )


def _assumption_section(
    summaries: Sequence[SummaryStatistics],
    fleet: ScenarioFleet,
    finance: FinanceConfig,
    simulate: FleetSimulate,
    *,
    project: bool,
    cost_recovery: bool,
) -> AssumptionSection:
    """One --assumptions mode's section, every figure computed under *finance*: the bill of *summaries*, and, when asked for, *fleet*'s one projection run by *simulate*, its economics if *project* and its cost-recovery solve if *cost_recovery*."""
    bill = bill_distribution(summaries, finance)
    if cost_recovery:
        run = run_cost_recovery(fleet, finance, simulate=simulate)
        return AssumptionSection(
            finance,
            bill,
            projection=run.projection,
            economics=run.economics if project else None,
            cost_recovery=run.solution,
        )
    if project:
        projection = project_fleet(fleet, finance, simulate=simulate)
        return AssumptionSection(
            finance,
            bill,
            projection=projection,
            economics=project_economics(projection.curve, fleet, finance),
        )
    return AssumptionSection(finance, bill)


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

    Each --assumptions mode drives the bill, and with --project or
    --cost-recovery the projection, the economics and the solve, from its own
    finance, ``finance.with_own_use_basis`` of the scenario's: physics clears
    any override, spreadsheet keeps the scenario's or sets the default, and
    both runs the two.  Each mode is its column of every bill, economics and
    cost-recovery table of the report.

    The scenario file must contain a ``finance:`` block with at least
    ``standing_charge_pence_per_day``.

    Example::

        solar-challenge finance run scenarios/bristol-phase1.yaml
        solar-challenge finance run scenarios/bristol-phase1.yaml \\
            --assumptions both --start 2024-06-01 --end 2024-08-31
    """
    scenario_config = with_window_options(load_scenario(scenario), start=start, end=end)
    finance = required_finance(scenario_config)
    pricing = finance.grid_services_model
    band = flex_band if flex_band is not None else scenario_config.flex_band

    fleet = scenario_fleet(scenario_config)

    cli = invocation(ctx)
    print_info(cli, f"Simulating fleet of {len(fleet.homes)} homes for {scenario_config.window().days} days…")
    fleet_results = cli.runner.simulate(
        FleetConfig(homes=fleet.homes, name=scenario_config.name), fleet.start, fleet.end
    )
    grid_services = _grid_services_income(fleet_results, pricing)

    summaries = [calculate_summary(r) for r in fleet_results.per_home_results]

    if project:
        print_info(cli, "Computing project-level economics (DSCR/IRR/payback)…")
    if cost_recovery:
        print_info(cli, "Solving cost-recovery own-use rate…")
    simulate = reusing(cli.runner.simulate, fleet_results, fleet.start, fleet.end)
    sections = {
        basis: _assumption_section(
            summaries,
            fleet,
            with_own_use_basis(finance, basis),
            simulate,
            project=project,
            cost_recovery=cost_recovery,
        )
        for basis in ASSUMPTION_BASES[assumptions]
    }

    report = generate_finance_report(
        sections,
        scenario_name=scenario_config.name or str(scenario),
        grid_services=grid_services,
        flex=FlexBlock(band) if band is not None else None,
    )
    print_report(report)
