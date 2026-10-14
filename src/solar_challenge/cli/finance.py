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
from solar_challenge.gridservices import GridServicesAtEvents, compute_grid_services_at_events
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


def _required_finance_block(raw: Mapping[str, Any]) -> FinanceConfig:
    """The scenario's parsed finance: block, raising ConfigurationError when it has none."""
    finance = parse_finance_config(raw.get("finance"))
    if finance is None:
        raise ConfigurationError(
            "No 'finance:' block found in the scenario file. "
            "Add a finance: block with at least standing_charge_pence_per_day."
        )
    return finance


def _flex_band_name(flag: Optional[FlexBand], scenario_value: object) -> Optional[str]:
    """The flexibility band to report: the --flex-band flag's, else the scenario's flex_band key lower-cased to match the flag's case-insensitive values, else None."""
    if flag is not None:
        return flag.value
    if isinstance(scenario_value, str):
        return scenario_value.lower()
    return None


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
    """The FinanceConfig of the report's first bill column, and under --assumptions both of its spreadsheet column, else None."""
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


def _economics_and_cost_recovery(
    scenario_config: ScenarioConfig,
    finance: FinanceConfig,
    simulator: CliFleetSimulator,
    *,
    project: bool,
    cost_recovery: bool,
) -> tuple[Optional[ProjectEconomics], Optional[CostRecoverySolution]]:
    """The project economics --project asks for and the cost-recovery solution --cost-recovery asks for, each None without its flag."""
    economics_result: Optional[ProjectEconomics] = None
    if project:
        print_info("Computing project-level economics (DSCR/IRR/payback)…")
        curve = project_multi_year(scenario_config, finance, simulate=simulator.simulate)
        economics_result = project_economics(curve, scenario_config, finance)

    cost_recovery_result: Optional[CostRecoverySolution] = None
    if cost_recovery:
        print_info("Solving cost-recovery own-use rate…")
        cost_recovery_result = solve_cost_recovery_rate(
            scenario_config, finance, simulate=simulator.simulate
        )
    return economics_result, cost_recovery_result


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
    raw = load_config(scenario)
    finance = _required_finance_block(raw)
    band_name = _flex_band_name(flex_band, raw.get("flex_band"))
    resolved_flex_band = resolve_flex_band(band_name) if band_name else None

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
        seg_tariff_pence_per_kwh=seg_rate if cost_recovery else None,
    )
    economics_result, cost_recovery_result = _economics_and_cost_recovery(
        scenario_config, finance, simulator, project=project, cost_recovery=cost_recovery
    )

    report = generate_finance_report(
        primary_bill,
        spreadsheet_bill,
        scenario_name=scenario_config.name,
        economics=economics_result,
        cost_recovery=cost_recovery_result,
        flex_band=resolved_flex_band,
        flex_band_name=band_name or "",
        grid_services_at_events=grid_services_at_events,
    )
    print_report(report)
