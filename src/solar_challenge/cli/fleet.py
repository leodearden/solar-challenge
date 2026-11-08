# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet simulation commands."""

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Optional

import pandas as pd
import typer
from rich.progress import Progress, TaskID
from rich.table import Table

if TYPE_CHECKING:
    from solar_challenge.community import CommunityResults

from solar_challenge.cli.utils import (
    console,
    create_fleet_progress,
    create_summary_table,
    fleet_summary_rows,
    handle_errors,
    print_info,
    print_success,
    print_warning,
)
from solar_challenge.community import simulate_community
from solar_challenge.config import (
    SweepSpec,
    detect_fleet_sweep_spec,
    load_community_config,
    load_config,
    load_fleet_config,
    parse_fleet_config,
    parse_sweep_fleet_configs,
    substitute_config_variables,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    FleetRunner,
    HomesDone,
    calculate_fleet_summary,
    default_runner,
)
from solar_challenge.output import compute_community_metrics, generate_community_report

app = typer.Typer(help="Fleet simulation commands")


def _export_fleet_results(results: FleetResults, output: Path) -> None:
    """Export fleet results to CSV."""
    df = results.to_aggregate_dataframe()
    df.to_csv(output)


def _print_community_section(community_results: "CommunityResults") -> None:
    """Print a community sharing summary after the fleet summary table."""
    m = compute_community_metrics(community_results)

    table = Table(title="Community Sharing Results")
    table.add_column("Metric", style="bold")
    table.add_column("Unshared (Σ per-home)", justify="right")
    table.add_column("Community", justify="right")
    table.add_column("Reduction", justify="right")

    table.add_row(
        "Grid Import (kWh)",
        f"{m.unshared_import_kwh:.1f}",
        f"{m.community_import_kwh:.1f}",
        f"{m.import_reduction_kwh:.1f}",
    )
    table.add_row(
        "Grid Export (kWh)",
        f"{m.unshared_export_kwh:.1f}",
        f"{m.community_export_kwh:.1f}",
        f"{m.export_reduction_kwh:.1f}",
    )
    table.add_row("", "", "", "")  # separator
    table.add_row(
        "Community Self-Sufficiency",
        "",
        f"{m.self_sufficiency:.1%}",
        "",
    )

    # Community billing rows, only when VNM billing was computed
    if community_results.community_savings_gbp is not None:
        table.add_row("", "", "", "")  # separator before billing block
        table.add_row(
            "Baseline Net Cost (£)",
            "",
            f"{community_results.baseline_net_cost_gbp:.2f}",
            "",
        )
        table.add_row(
            "Community Net Cost (£)",
            "",
            f"{community_results.community_net_cost_gbp:.2f}",
            "",
        )
        table.add_row(
            "Community Savings (£)",
            "",
            f"{community_results.community_savings_gbp:.2f}",
            "",
        )

    console.print(table)


def _period_in_fleet_timezone(
    fleet: FleetConfig, start: str, end: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The timestamps the --start and --end dates name in the timezone of fleet's homes, which FleetConfig requires they share."""
    timezone = fleet.homes[0].location.timezone
    return pd.Timestamp(start, tz=timezone), pd.Timestamp(end, tz=timezone)


@app.command()
@handle_errors
def run(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to fleet config YAML/JSON file",
            exists=True,
            dir_okay=False,
        ),
    ],
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
            help="Output CSV file path for aggregate results",
        ),
    ] = None,
    workers: Annotated[
        Optional[int],
        typer.Option(
            "--workers", "-w",
            help="Number of parallel workers",
        ),
    ] = None,
    sequential: Annotated[
        bool,
        typer.Option(
            "--sequential",
            help="Disable parallelization",
        ),
    ] = False,
    community_report: Annotated[
        Optional[Path],
        typer.Option(
            "--community-report",
            help="Output markdown path for the community sharing report "
                 "(requires a community: block in the config)",
        ),
    ] = None,
) -> None:
    """Run a fleet simulation from config file.

    The config file should define a list of homes with their PV, battery,
    and load configurations.
    """
    runner = _runner(workers, sequential)
    fleet_config = load_fleet_config(config)
    n_homes = len(fleet_config.homes)

    start_date, end_date = _period_in_fleet_timezone(fleet_config, start, end)

    days = (end_date - start_date).days + 1
    print_info(f"Simulating fleet of {n_homes} homes for {days} days")

    with create_fleet_progress() as progress:
        task = progress.add_task(f"Simulating {n_homes} homes...", total=n_homes)
        results = runner.simulate(fleet_config, start_date, end_date, progress=_homes_done_on(progress, task))

    summary = calculate_fleet_summary(results)

    console.print(
        create_summary_table(fleet_summary_rows(summary), title=f"Fleet Results: {fleet_config.name or 'Fleet'}")
    )

    if output is not None:
        _export_fleet_results(results, output)
        print_success(f"Aggregate results saved to {output}")

    # Community sharing layer
    community_config = load_community_config(config)
    if community_config is not None:
        community_results = simulate_community(results, community_config)
        _print_community_section(community_results)
        if community_report is not None:
            community_report.write_text(generate_community_report(community_results))
            print_success(f"Community report saved to {community_report}")
    else:
        if community_report is not None:
            print_warning(
                "--community-report ignored: config has no community: block"
            )


@app.command()
@handle_errors
def sweep(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to fleet config YAML/JSON file",
            exists=True,
            dir_okay=False,
        ),
    ],
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
    param: Annotated[
        Optional[str],
        typer.Option(
            "--param",
            help="Name of the ${NAME} placeholder the CLI sweep sets (e.g., BATTERY_RATIO)",
        ),
    ] = None,
    min_val: Annotated[
        Optional[float],
        typer.Option(
            "--min",
            help="Minimum sweep value (for CLI sweep)",
        ),
    ] = None,
    max_val: Annotated[
        Optional[float],
        typer.Option(
            "--max",
            help="Maximum sweep value (for CLI sweep)",
        ),
    ] = None,
    steps: Annotated[
        int,
        typer.Option(
            "--steps",
            help="Number of sweep steps",
        ),
    ] = 10,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Sweep mode: geometric or linear",
        ),
    ] = "geometric",
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir", "-o",
            help="Output directory for sweep results",
        ),
    ] = None,
    workers: Annotated[
        Optional[int],
        typer.Option(
            "--workers", "-w",
            help="Number of parallel workers per simulation",
        ),
    ] = None,
    sequential: Annotated[
        bool,
        typer.Option(
            "--sequential",
            help="Disable parallelization",
        ),
    ] = False,
) -> None:
    """Run parameter sweep over fleet configuration.

    Supports two modes:

    1. YAML-defined sweep: When the config contains a sweep spec in the
       battery.capacity_kwh.multiplier field, runs all sweep points.

    2. CLI-driven sweep: When --param is provided, it is the NAME of the
       ${NAME} or ${NAME:default} placeholders to sweep, each the whole
       value of a key in the config. Each sweep point replaces every such
       placeholder with the point's value, from --min to --max; a
       placeholder --param does not name takes its default. The sweep
       refuses a --param that no placeholder names, a placeholder inside a
       longer string, and a default that is not a finite number.

    Example YAML-defined sweep:

        battery:
          capacity_kwh:
            type: proportional_to
            source: pv.capacity_kw
            multiplier:
              type: sweep
              min: 0.1
              max: 4.0
              steps: 10

    Example CLI-driven sweep:

        battery:
          capacity_kwh:
            type: proportional_to
            source: pv.capacity_kw
            multiplier: '${BATTERY_RATIO:1.0}'

        solar-challenge fleet sweep config.yaml \\
            --param BATTERY_RATIO --min 0.1 --max 4.0 --steps 10
    """
    runner = _runner(workers, sequential)
    raw_config = load_config(config)

    if "fleet_distribution" not in raw_config:
        raise ConfigurationError("Sweep requires fleet_distribution config")

    if param is None:
        param_name, sweep_configs = _yaml_sweep(raw_config)
    else:
        param_name, sweep_configs = _param_sweep(
            raw_config, param, min_val, max_val, steps, mode
        )

    start_date, end_date = _period_in_fleet_timezone(sweep_configs[0][1], start, end)

    # Create output directory if needed
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate totals
    n_sweeps = len(sweep_configs)
    total_homes = sum(len(cfg.homes) for _, cfg in sweep_configs)

    print_info(f"Simulating {n_sweeps} sweeps ({total_homes} total homes)")

    sweep_results: dict[int, FleetResults] = {}
    with create_fleet_progress() as progress:
        task = progress.add_task(
            f"Simulating {n_sweeps} sweeps ({total_homes} total homes)...",
            total=total_homes
        )
        for index, fleet_results in runner.simulate_each(
            [fleet for _, fleet in sweep_configs], start_date, end_date, progress=_homes_done_on(progress, task)
        ):
            sweep_results[index] = fleet_results
            if output_dir is not None:
                _export_sweep_point(output_dir, param_name, sweep_configs[index][0], fleet_results)

    results_summary = [
        _sweep_summary_row(param_name, sweep_value, sweep_results[index])
        for index, (sweep_value, _) in enumerate(sweep_configs)
    ]

    # Print summary table
    _print_sweep_summary(results_summary)

    # Save summary CSV
    if output_dir is not None:
        summary_df = pd.DataFrame(results_summary)
        summary_file = output_dir / "sweep_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print_success(f"Sweep summary saved to {summary_file}")


def _param_sweep(
    raw_config: dict[str, Any],
    param: str,
    min_val: Optional[float],
    max_val: Optional[float],
    steps: int,
    mode: str,
) -> tuple[str, list[tuple[float, FleetConfig]]]:
    """The name of the sweep, param, and each sweep value with the fleet raw_config builds when that value replaces ${param}."""
    if min_val is None or max_val is None:
        raise ConfigurationError("CLI sweep requires --min and --max values")
    sweep_spec = SweepSpec(min=min_val, max=max_val, steps=steps, mode=mode)
    print_info(
        f"CLI sweep: {param} from {min_val} to {max_val} "
        f"({steps} steps, {mode})"
    )
    return param, [
        (
            value,
            dataclasses.replace(
                parse_fleet_config(substitute_config_variables(raw_config, {param: value})),
                name=f"{param}={value:.4f}",
            ),
        )
        for value in sweep_spec.get_values()
    ]


def _yaml_sweep(
    raw_config: Mapping[str, Any],
) -> tuple[str, list[tuple[float, FleetConfig]]]:
    """The name of the sweep, multiplier, and each sweep value with the fleet raw_config's YAML-defined sweep builds for it."""
    param_name = "multiplier"
    sweep_spec = detect_fleet_sweep_spec(raw_config)
    if sweep_spec is None:
        raise ConfigurationError(
            "No sweep spec found in config. "
            "Use --param for CLI sweep or add type: sweep to multiplier."
        )
    print_info(
        f"YAML sweep: {param_name} from {sweep_spec.min} to {sweep_spec.max} "
        f"({sweep_spec.steps} steps, {sweep_spec.mode})"
    )
    return param_name, parse_sweep_fleet_configs(raw_config)


def _runner(workers: Optional[int], sequential: bool) -> FleetRunner:
    """The default runner, simulating homes in turn when sequential, else in parallel on workers workers, None meaning as many as the homes need, up to the CPUs."""
    return dataclasses.replace(default_runner(), parallel=not sequential, max_workers=workers)


def _homes_done_on(progress: Progress, task: TaskID) -> HomesDone:
    """A progress sink that shows the homes finished as task's completed count on progress."""

    def homes_done(done: int, total: int) -> None:
        progress.update(task, completed=done)

    return homes_done


def _export_sweep_point(output_dir: Path, param_name: str, sweep_value: float, fleet_results: FleetResults) -> None:
    """Export a completed sweep point to its CSV under output_dir."""
    _export_fleet_results(fleet_results, output_dir / f"{param_name}_{sweep_value:.4f}.csv")


def _sweep_summary_row(
    param_name: str, sweep_value: float, fleet_results: FleetResults
) -> dict[str, Any]:
    """The summary row of the sweep point at sweep_value: its fleet's self-consumption ratio and energy totals."""
    summary = calculate_fleet_summary(fleet_results)
    return {
        "sweep_value": sweep_value,
        "param": param_name,
        "self_consumption_ratio": summary.fleet_self_consumption_ratio,
        "total_generation_kwh": summary.total_generation_kwh,
        "total_consumption_kwh": summary.total_demand_kwh,
        "grid_import_kwh": summary.total_grid_import_kwh,
        "grid_export_kwh": summary.total_grid_export_kwh,
    }


def _print_sweep_summary(results: list[dict[str, Any]]) -> None:
    """Print sweep summary table."""
    table = Table(title="Sweep Results Summary")
    table.add_column("Value", justify="right")
    table.add_column("Self-Consumption", justify="right")
    table.add_column("Generation (kWh)", justify="right")
    table.add_column("Import (kWh)", justify="right")
    table.add_column("Export (kWh)", justify="right")

    for r in results:
        table.add_row(
            f"{r['sweep_value']:.4f}",
            f"{r['self_consumption_ratio']:.1%}",
            f"{r['total_generation_kwh']:.1f}",
            f"{r['grid_import_kwh']:.1f}",
            f"{r['grid_export_kwh']:.1f}",
        )

    console.print(table)
