# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Finance CLI commands for householder bill and distribution analysis."""

import dataclasses
import enum
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from solar_challenge.cli.utils import CliInvocation, handle_errors, invocation, print_info, print_report
from solar_challenge.config import (
    ScenarioConfig,
    load_config,
    load_fleet_config,
    load_scenario,
    period_window,
)
from solar_challenge.errors import ConfigurationError
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
    project_multi_year,
    scenario_fleet,
    solve_cost_recovery_rate,
)
from solar_challenge.scenario_blocks import (
    parse_finance_config,
    parse_seg_rate,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY

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


def _with_seg_tariff(fleet_config: FleetConfig, seg_rate: Optional[float]) -> FleetConfig:
    """*fleet_config* with *seg_rate* pence/kWh as every home's SEG export tariff, or *fleet_config* itself when *seg_rate* is None."""
    if seg_rate is None:
        return fleet_config
    seg_tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)
    return dataclasses.replace(
        fleet_config,
        homes=tuple(dataclasses.replace(home, seg_tariff=seg_tariff) for home in fleet_config.homes),
    )


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


def _project_level_economics(
    cli: CliInvocation, scenario_config: ScenarioConfig, finance: FinanceConfig, simulate: FleetSimulate
) -> ProjectEconomics:
    """The project-level economics (DSCR/IRR/payback) of *scenario_config*'s fleet under *finance*, its simulations run by *simulate*, after printing *cli*'s status line announcing them."""
    print_info(cli, "Computing project-level economics (DSCR/IRR/payback)…")
    curve = project_multi_year(scenario_config, finance, simulate=simulate)
    return project_economics(curve, scenario_fleet(scenario_config), finance)


def _cost_recovery_solution(
    cli: CliInvocation, scenario_config: ScenarioConfig, finance: FinanceConfig, simulate: FleetSimulate
) -> CostRecoverySolution:
    """The own-use rate at which *scenario_config*'s fleet recovers its cost under *finance*, its simulations run by *simulate*, after printing *cli*'s status line announcing it."""
    print_info(cli, "Solving cost-recovery own-use rate…")
    return solve_cost_recovery_rate(scenario_config, finance, simulate=simulate)


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
    ] = DEFAULT_FIRST_DAY.isoformat(),
    end: Annotated[
        str,
        typer.Option(
            "--end",
            help="Simulation end date (YYYY-MM-DD)",
        ),
    ] = DEFAULT_LAST_DAY.isoformat(),
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
    pricing = grid_services_model_of(finance)
    band = flex_band if flex_band is not None else load_scenario(scenario).flex_band

    fleet_config = load_fleet_config(scenario)
    seg_rate = parse_seg_rate(raw.get("seg"))
    fleet_config = _with_seg_tariff(fleet_config, seg_rate)

    loc = fleet_config.homes[0].location
    scenario_config = ScenarioConfig(
        name=raw.get("name", str(scenario)),
        period=period_window(start, end, timezone=loc.timezone),
        homes=fleet_config.homes,
        location=loc,
        finance=finance,
        # Only --cost-recovery passes the rate on:
        # tests/integration/test_finance_run_cli.py::test_project_economics_are_the_same_with_and_without_cost_recovery
        seg_tariff_pence_per_kwh=seg_rate if cost_recovery else None,
    )
    start_date, end_date = scenario_config.simulation_bounds()

    cli = invocation(ctx)
    print_info(cli, f"Simulating fleet of {len(fleet_config.homes)} homes for {scenario_config.period.days} days…")
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
    economics_result = (
        _project_level_economics(cli, scenario_config, finance, simulate) if project else None
    )
    cost_recovery_result = (
        _cost_recovery_solution(cli, scenario_config, finance, simulate) if cost_recovery else None
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
