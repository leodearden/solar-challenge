# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet simulation commands."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Optional

import pandas as pd
import typer
from rich.progress import Progress, TaskID
from rich.table import Table

if TYPE_CHECKING:
    from solar_challenge.community import CommunityResults

from solar_challenge.cli.utils import (
    EndOption,
    StartOption,
    console,
    create_fleet_progress,
    create_summary_table,
    fleet_summary_rows,
    handle_errors,
    invocation,
    print_info,
    print_success,
    print_warning,
    with_window_options,
)
from solar_challenge.community import simulate_community
from solar_challenge.config import (
    ScenarioConfig,
    config_variables,
    detect_fleet_sweep_spec,
    fleet_of,
    load_community_config,
    load_config,
    load_scenario,
    parse_scenario,
    parse_sweep_scenarios,
    substitute_config_variables,
    sweep_point_fleet,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import (
    FleetResults,
    HomesDone,
    calculate_fleet_summary,
)
from solar_challenge.fleet_distribution import SweepMode, SweepSpec, swept_parameter_path
from solar_challenge.output import compute_community_metrics, generate_community_report
from solar_challenge.scenario_knobs import KNOBS, Knob, is_knob_name, knob_named, names_with_aliases

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


@app.command()
@handle_errors
def run(
    ctx: typer.Context,
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to fleet config YAML/JSON file",
            exists=True,
            dir_okay=False,
        ),
    ],
    start: StartOption = None,
    end: EndOption = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output CSV file path for aggregate results",
        ),
    ] = None,
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
    cli = invocation(ctx)
    scenario = with_window_options(load_scenario(config), start=start, end=end)
    community_config = load_community_config(config)
    fleet_config = fleet_of(scenario)
    n_homes = len(fleet_config.homes)

    start_date, end_date = scenario.simulation_bounds()

    print_info(cli, f"Simulating fleet of {n_homes} homes for {scenario.window().days} days")

    with create_fleet_progress(cli) as progress:
        task = progress.add_task(f"Simulating {n_homes} homes...", total=n_homes)
        results = cli.runner.simulate(fleet_config, start_date, end_date, progress=_homes_done_on(progress, task))

    summary = calculate_fleet_summary(results)

    console.print(
        create_summary_table(fleet_summary_rows(summary), title=f"Fleet Results: {fleet_config.name or 'Fleet'}")
    )

    if output is not None:
        _export_fleet_results(results, output)
        print_success(cli, f"Aggregate results saved to {output}")

    # Community sharing layer
    if community_config is not None:
        community_results = simulate_community(results, community_config)
        _print_community_section(community_results)
        if community_report is not None:
            community_report.write_text(generate_community_report(community_results))
            print_success(cli, f"Community report saved to {community_report}")
    else:
        if community_report is not None:
            print_warning(
                "--community-report ignored: config has no community: block"
            )


@app.command()
@handle_errors
def sweep(
    ctx: typer.Context,
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to fleet config YAML/JSON file",
            exists=True,
            dir_okay=False,
        ),
    ],
    start: StartOption = None,
    end: EndOption = None,
    param: Annotated[
        Optional[str],
        typer.Option(
            "--param",
            help=(
                "What the sweep varies: a knob, by its name or an alias, else NAME, the ${NAME} "
                "placeholders of the document; a name with both readings is refused.  "
                "The knobs, each with its aliases: " + names_with_aliases(KNOBS.values())
            ),
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
        SweepMode,
        typer.Option(
            "--mode",
            help="How the points are spaced from --min to --max: by a constant step (linear) or a constant ratio (geometric)",
        ),
    ] = SweepSpec.mode,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir", "-o",
            help="Output directory for sweep results",
        ),
    ] = None,
) -> None:
    """Run parameter sweep over fleet configuration.

    Supports two modes:

    1. YAML-defined sweep: When the config contains a sweep spec in the
       battery.capacity_kwh.multiplier field, runs all sweep points.

    2. CLI-driven sweep: When --param is provided, it resolves through the
       knob registry first, by a knob's name or an alias, and then as the
       NAME of the ${NAME} or ${NAME:default} placeholders of the config,
       each the whole value of a key; the sweep refuses a --param with both
       readings or neither. A knob sweep reads the config once, each
       placeholder at its default, and sets the knob to each point's value,
       from --min to --max. A variable sweep replaces every placeholder of
       NAME with the point's value; a placeholder --param does not name
       takes its default. The sweep refuses a placeholder inside a longer
       string, and a default that is not a finite number.

    Each point is labelled <axis label>=<value> and written to
    <axis label>_<value>.csv: the axis label is the knob's canonical name,
    the variable's NAME, or the path of the YAML sweep's field.

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

    Example knob sweep:

        solar-challenge fleet sweep config.yaml \\
            --param battery_capacity_kwh --min 5 --max 10 --steps 2
    """
    cli = invocation(ctx)
    raw_config = load_config(config)

    if "fleet_distribution" not in raw_config:
        raise ConfigurationError("Sweep requires fleet_distribution config")

    if param is None:
        source = "YAML"
        param_name, sweep_spec, sweep_points = _yaml_sweep(raw_config)
    else:
        source = "CLI"
        param_name, sweep_spec, sweep_points = _param_sweep(
            raw_config, param, min_val, max_val, steps, mode
        )
    start_date, end_date = _sweep_bounds(sweep_points, start=start, end=end)
    print_info(
        cli,
        f"{source} sweep: {param_name} from {sweep_spec.min} to {sweep_spec.max} "
        f"({sweep_spec.steps} steps, {sweep_spec.mode})"
    )
    fleets = [sweep_point_fleet(param_name, value, scenario) for value, scenario in sweep_points]

    # Create output directory if needed
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate totals
    n_sweeps = len(fleets)
    total_homes = sum(len(fleet.homes) for fleet in fleets)

    print_info(cli, f"Simulating {n_sweeps} sweeps ({total_homes} total homes)")

    sweep_results: dict[int, FleetResults] = {}
    with create_fleet_progress(cli) as progress:
        task = progress.add_task(
            f"Simulating {n_sweeps} sweeps ({total_homes} total homes)...",
            total=total_homes
        )
        for index, fleet_results in cli.runner.simulate_each(
            fleets, start_date, end_date, progress=_homes_done_on(progress, task)
        ):
            sweep_results[index] = fleet_results
            if output_dir is not None:
                _export_sweep_point(output_dir, param_name, sweep_points[index][0], fleet_results)

    results_summary = [
        _sweep_summary_row(param_name, sweep_value, sweep_results[index])
        for index, (sweep_value, _) in enumerate(sweep_points)
    ]

    # Print summary table
    _print_sweep_summary(results_summary)

    # Save summary CSV
    if output_dir is not None:
        summary_df = pd.DataFrame(results_summary)
        summary_file = output_dir / "sweep_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print_success(cli, f"Sweep summary saved to {summary_file}")


@dataclass(frozen=True)
class _KnobAxis:
    """A --param sweep of a knob: each point is the document's one scenario with the knob set to the point's value."""

    knob: Knob

    @property
    def label(self) -> str:
        """The knob's canonical name, which names each point and its output file."""
        return self.knob.name

    def scenarios(self, document: dict[str, Any], values: Iterable[float]) -> list[tuple[float, ScenarioConfig]]:
        """Each of *values* with the scenario *document* reads as, its placeholders at their defaults, and the knob set to that value."""
        scenario = parse_scenario(substitute_config_variables(document))
        return [(value, self.knob.apply(scenario, value)) for value in values]


@dataclass(frozen=True)
class _VariableAxis:
    """A --param sweep of a variable: each point is the scenario the document reads as once the point's value replaces ${name}."""

    name: str

    @property
    def label(self) -> str:
        """The variable's name, which names each point and its output file."""
        return self.name

    def scenarios(self, document: dict[str, Any], values: Iterable[float]) -> list[tuple[float, ScenarioConfig]]:
        """Each of *values* with the scenario *document* reads as once that value replaces ${name}."""
        return [
            (value, parse_scenario(substitute_config_variables(document, {self.name: value})))
            for value in values
        ]


_SweepAxis = _KnobAxis | _VariableAxis


def _param_sweep(
    raw_config: dict[str, Any],
    param: str,
    min_val: Optional[float],
    max_val: Optional[float],
    steps: int,
    mode: SweepMode,
) -> tuple[str, SweepSpec, list[tuple[float, ScenarioConfig]]]:
    """The label of the axis param names, its spec, and each sweep value with the scenario the axis builds from raw_config for it."""
    if min_val is None or max_val is None:
        raise ConfigurationError("CLI sweep requires --min and --max values")
    sweep_spec = SweepSpec(min=min_val, max=max_val, steps=steps, mode=mode)
    axis = _sweep_axis(raw_config, param)
    return axis.label, sweep_spec, axis.scenarios(raw_config, sweep_spec.get_values())


def _sweep_axis(document: dict[str, Any], name: str) -> _SweepAxis:
    """The axis --param *name* sweeps: the knob it names, else the variable of *document* it names.

    Raises:
        ConfigurationError: If *name* names both a knob and a variable of *document*, or
            neither, listing the document's variables and the knobs.
    """
    variables = config_variables(document)
    is_knob = is_knob_name(name)
    is_variable = name in variables
    if is_knob and is_variable:
        raise ConfigurationError(
            f"--param {name!r} names both the knob {knob_named(name).name!r} and the document's variable "
            f"${{{name}}}; rename the variable to sweep it, or remove it to sweep the knob"
        )
    if is_knob:
        return _KnobAxis(knob_named(name))
    if is_variable:
        return _VariableAxis(name)
    held = f"its variables: {', '.join(repr(each) for each in variables)}" if variables else "it holds no variables"
    raise ConfigurationError(
        f"--param {name!r} names no knob and no variable of the document; {held}; "
        f"the knobs, each with its aliases: {names_with_aliases(KNOBS.values())}"
    )


def _yaml_sweep(
    raw_config: Mapping[str, Any],
) -> tuple[str, SweepSpec, list[tuple[float, ScenarioConfig]]]:
    """The name of the sweep, the swept_parameter_path of its field, the spec raw_config's YAML-defined sweep gives it, and each sweep value with the scenario that sweep builds for it."""
    found = detect_fleet_sweep_spec(raw_config)
    if found is None:
        raise ConfigurationError(
            "No sweep spec found in config. "
            "Use --param for CLI sweep or add type: sweep to multiplier."
        )
    placement, sweep_spec = found
    return swept_parameter_path(placement), sweep_spec, parse_sweep_scenarios(raw_config)


def _sweep_bounds(
    points: list[tuple[float, ScenarioConfig]],
    *,
    start: Optional[datetime],
    end: Optional[datetime],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The start and end every point of the sweep simulates over, which is its document's period with each flag replacing only its own day.

    Every point holds that one period: a YAML sweep reads the document's blocks once, a ${VAR} stands only for a number, which is neither a day nor a timezone, and a knob edits homes, the SEG rate or finance, never the period or location.
    """
    return with_window_options(points[0][1], start=start, end=end).simulation_bounds()


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
