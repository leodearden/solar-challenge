"""Fleet simulation commands."""

from pathlib import Path
from typing import Annotated, Any, Optional

import pandas as pd
import typer

from solar_challenge.cli.utils import (
    console,
    create_fleet_progress,
    create_progress,
    create_summary_table,
    handle_errors,
    print_info,
    print_success,
    print_warning,
)
from solar_challenge.config import (
    ConfigurationError,
    SweepSpec,
    detect_sweep_spec,
    expand_sweep_configs,
    generate_homes_from_distribution,
    load_config,
    load_fleet_config,
    substitute_config_variables,
    _parse_fleet_distribution_config,
)
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    calculate_fleet_summary,
    collect_multi_sweep_results,
    simulate_fleet_iter,
    simulate_multi_sweep_iter,
)
from solar_challenge.home import SimulationResults
from solar_challenge.location import Location

app = typer.Typer(help="Fleet simulation commands")


def _export_fleet_results(results: FleetResults, output: Path) -> None:
    """Export fleet results to CSV."""
    df = results.to_aggregate_dataframe()
    df.to_csv(output)


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
) -> None:
    """Run a fleet simulation from config file.

    The config file should define a list of homes with their PV, battery,
    and load configurations.
    """
    fleet_config = load_fleet_config(config)
    n_homes = len(fleet_config.homes)

    # Get location from first home for timezone
    loc = fleet_config.homes[0].location

    # Parse dates
    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    days = (end_date - start_date).days + 1
    print_info(f"Simulating fleet of {n_homes} homes for {days} days")

    results_list: list[SimulationResults | None] = [None] * n_homes

    with create_fleet_progress() as progress:
        task = progress.add_task(f"Simulating {n_homes} homes...", total=n_homes)
        for idx, result in simulate_fleet_iter(
            fleet_config, start_date, end_date,
            parallel=not sequential, max_workers=workers
        ):
            results_list[idx] = result
            progress.update(task, advance=1)

    # Build FleetResults from results_list
    final_results: list[SimulationResults] = []
    for r in results_list:
        assert r is not None
        final_results.append(r)

    results = FleetResults(
        per_home_results=final_results,
        home_configs=fleet_config.homes,
    )

    summary = calculate_fleet_summary(results)

    # Create and display summary table
    table = create_summary_table(summary, title=f"Fleet Results: {fleet_config.name or 'Fleet'}")

    # Add fleet-specific stats
    table.add_row("", "")  # Separator
    table.add_row(
        "Per-Home Generation (min/max)",
        f"{summary.per_home_generation_min_kwh:.1f} / {summary.per_home_generation_max_kwh:.1f} kWh",
    )
    table.add_row(
        "Per-Home Generation (mean)",
        f"{summary.per_home_generation_mean_kwh:.1f} kWh",
    )
    table.add_row(
        "Self-Consumption Ratio (min/max)",
        f"{summary.per_home_self_consumption_ratio_min:.1%} / {summary.per_home_self_consumption_ratio_max:.1%}",
    )
    table.add_row(
        "Self-Consumption Ratio (mean)",
        f"{summary.per_home_self_consumption_ratio_mean:.1%}",
    )

    console.print(table)

    if output is not None:
        _export_fleet_results(results, output)
        print_success(f"Aggregate results saved to {output}")


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
            help="Variable name for CLI sweep (e.g., BATTERY_RATIO)",
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

    2. CLI-driven sweep: When --param is provided, substitutes the variable
       in the config and sweeps from --min to --max.

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

        solar_challenge fleet sweep config.yaml \\
            --param BATTERY_RATIO --min 0.1 --max 4.0 --steps 10
    """
    raw_config = load_config(config)

    # Get location
    location_data = raw_config.get("location")
    if location_data:
        from solar_challenge.config import _parse_location
        location = _parse_location(location_data)
    else:
        location = Location.bristol()

    # Parse dates
    start_date = pd.Timestamp(start, tz=location.timezone)
    end_date = pd.Timestamp(end, tz=location.timezone)
    days = (end_date - start_date).days + 1

    # Create output directory if needed
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Build sweep configs upfront
    sweep_configs: list[tuple[float, FleetConfig]] = []
    param_name: str = "multiplier"  # Default for YAML sweep

    if param is not None:
        # CLI-driven sweep
        if min_val is None or max_val is None:
            raise ConfigurationError(
                "CLI sweep requires --min and --max values"
            )
        sweep_spec = SweepSpec(min=min_val, max=max_val, steps=steps, mode=mode)
        sweep_values = sweep_spec.get_values()
        param_name = param
        print_info(
            f"CLI sweep: {param} from {min_val} to {max_val} "
            f"({steps} steps, {mode})"
        )

        for val in sweep_values:
            substituted = substitute_config_variables(raw_config, {param: val})
            if "fleet_distribution" not in substituted:
                raise ConfigurationError(
                    "Sweep requires fleet_distribution config"
                )
            dist_config = _parse_fleet_distribution_config(
                substituted["fleet_distribution"]
            )
            homes = generate_homes_from_distribution(dist_config, location)
            fleet_config = FleetConfig(homes=homes, name=f"{param}={val:.4f}")
            sweep_configs.append((val, fleet_config))

    else:
        # YAML-defined sweep
        if "fleet_distribution" not in raw_config:
            raise ConfigurationError(
                "Sweep requires fleet_distribution config"
            )
        dist_config = _parse_fleet_distribution_config(
            raw_config["fleet_distribution"]
        )
        sweep_spec = detect_sweep_spec(dist_config)  # type: ignore[assignment]
        if sweep_spec is None:
            raise ConfigurationError(
                "No sweep spec found in config. "
                "Use --param for CLI sweep or add type: sweep to multiplier."
            )

        sweep_values = sweep_spec.get_values()
        print_info(
            f"YAML sweep: multiplier from {sweep_spec.min} to {sweep_spec.max} "
            f"({sweep_spec.steps} steps, {sweep_spec.mode})"
        )

        for val, expanded_config in expand_sweep_configs(dist_config):
            homes = generate_homes_from_distribution(expanded_config, location)
            fleet_config = FleetConfig(homes=homes, name=f"multiplier={val:.4f}")
            sweep_configs.append((val, fleet_config))

    # Calculate totals
    n_sweeps = len(sweep_configs)
    total_homes = sum(len(cfg.homes) for _, cfg in sweep_configs)

    print_info(f"Simulating {n_sweeps} sweeps ({total_homes} total homes)")

    # Run multi-sweep simulation with cross-sweep parallelism
    results_summary: list[dict[str, Any]] = []

    def on_sweep_complete(sweep_idx: int, sweep_val: float, fleet_results: FleetResults) -> None:
        """Handle completed sweep: save results and update summary."""
        summary = calculate_fleet_summary(fleet_results)
        results_summary.append({
            "sweep_value": sweep_val,
            "param": param_name,
            "self_consumption_ratio": summary.fleet_self_consumption_ratio,
            "total_generation_kwh": summary.total_generation_kwh,
            "total_consumption_kwh": summary.total_demand_kwh,
            "grid_import_kwh": summary.total_grid_import_kwh,
            "grid_export_kwh": summary.total_grid_export_kwh,
        })

        # Save individual result if output_dir specified
        if output_dir is not None:
            if param is not None:
                output_file = output_dir / f"{param}_{sweep_val:.4f}.csv"
            else:
                output_file = output_dir / f"multiplier_{sweep_val:.4f}.csv"
            _export_fleet_results(fleet_results, output_file)

    with create_fleet_progress() as progress:
        task = progress.add_task(
            f"Simulating {n_sweeps} sweeps ({total_homes} total homes)...",
            total=total_homes
        )

        result_iter = simulate_multi_sweep_iter(
            sweep_configs, start_date, end_date,
            parallel=not sequential, max_workers=workers
        )

        # Wrap iterator to update progress
        def progress_iter() -> Any:
            for item in result_iter:
                progress.update(task, advance=1)
                yield item

        collect_multi_sweep_results(
            sweep_configs,
            progress_iter(),
            on_sweep_complete=on_sweep_complete,
        )

    # Sort results by sweep value for consistent output
    results_summary.sort(key=lambda x: x["sweep_value"])

    # Print summary table
    _print_sweep_summary(results_summary)

    # Save summary CSV
    if output_dir is not None:
        summary_df = pd.DataFrame(results_summary)
        summary_file = output_dir / "sweep_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print_success(f"Sweep summary saved to {summary_file}")


def _print_sweep_summary(results: list[dict[str, Any]]) -> None:
    """Print sweep summary table."""
    from rich.table import Table

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
