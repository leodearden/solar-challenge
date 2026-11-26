# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Optimize CLI commands for the discrete install-config sweep.

The command and its report are specified in
docs/prds/discrete-install-config-sweep.md §3.6.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Optional

import typer

from solar_challenge.board_report import generate_config_ranking_report
from solar_challenge.cli.utils import (
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
from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import GridServicesEventsConfig, GridServicesModel
from solar_challenge.optimize import (
    SENSITIVITY_BANDS,
    enumerate_configs,
    run_sweep,
    sensitivity_panel,
)
from solar_challenge.projection import fewest_simulated_ages
from solar_challenge.scenario_knobs import KNOBS, Knob, knob_named, names_with_aliases

app = typer.Typer(help="Discrete install-config sweep and optimisation commands")

# The knob the flat grid-services pricing reads: what --grid-services-kw sets.
_FLAT_RATE_KNOB = KNOBS["grid_services_income_per_kw_per_year_gbp"]

# The knob the cost-recovery solve's retained-cash floor reads: what --retained-floor sets.
_RETAINED_FLOOR_KNOB = KNOBS["retained_cash_floor_per_home_per_year_gbp"]

# The --sensitivity names swept when the flag is not given, in report order.
_DEFAULT_SENSITIVITY_NAMES: tuple[str, ...] = ("retained_floor", "grid_services")

# Why --grid-services-kw and the grid_services axis have nothing to set under the events model.
_FLAT_RATE_UNREAD_UNDER_EVENTS = (
    f"the flat grid-services rate, {_FLAT_RATE_KNOB.name}, "
    "which the scenario's capacity_at_events grid_services_model does not read"
)

# A sensitivity axis as --sensitivity names it: the name as written, and the knob it names.
_NamedAxis = tuple[str, Knob]


def _parse_float_list(raw: str, flag: str) -> list[float]:
    """Parse a comma-separated string of floats.

    Args:
        raw: Comma-separated string, e.g. '3,4,5,6'.
        flag: Flag name for error messages.

    Returns:
        List of floats.

    Raises:
        ValueError: If any value is not a valid float.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError(f"--{flag} must be a non-empty comma-separated list of numbers")
    try:
        return [float(p) for p in parts]
    except ValueError:
        raise ValueError(
            f"--{flag} contains a non-numeric value: {raw!r}"
        ) from None


def _banded_knob(name: str) -> Knob:
    """The knob *name* names, canonically or by an alias, which has a SENSITIVITY_BANDS entry.

    Raises:
        ConfigurationError: If *name* names no knob, as knob_named refuses it, or
            names a knob with no sensitivity band, listing the knobs with one.
    """
    knob = knob_named(name)
    if knob not in SENSITIVITY_BANDS:
        raise ConfigurationError(
            f"--sensitivity names {name}, the knob {knob.name}, which has no sensitivity band; "
            f"the knobs with one: {names_with_aliases(SENSITIVITY_BANDS)}"
        )
    return knob


def _banded_axes(names: Iterable[str]) -> tuple[_NamedAxis, ...]:
    """Each of *names*, in order, paired with the banded knob it names.

    Raises:
        ConfigurationError: As _banded_knob refuses a name, or if two of *names*
            name one knob, naming both as written.
    """
    name_of: dict[Knob, str] = {}
    for name in names:
        knob = _banded_knob(name)
        if knob in name_of:
            raise ConfigurationError(
                f"--sensitivity names the knob {knob.name} twice, as {name_of[knob]} and as {name}; "
                "name each knob once"
            )
        name_of[knob] = name
    return tuple((name, knob) for knob, name in name_of.items())


def _parse_sensitivity(raw: str) -> tuple[_NamedAxis, ...]:
    """The sensitivity axes the comma-separated *raw* names, in order; '' names none.

    Raises:
        ConfigurationError: As _banded_axes refuses *raw*'s names.
    """
    return _banded_axes(name.strip() for name in raw.split(",") if name.strip())


def _flat_rate_names(axes: tuple[_NamedAxis, ...]) -> tuple[str, ...]:
    """The names, as written, of the axes of *axes* that sweep _FLAT_RATE_KNOB, in order."""
    return tuple(name for name, knob in axes if knob == _FLAT_RATE_KNOB)


def _resolve_sensitivity_axes(
    requested: Optional[tuple[_NamedAxis, ...]], pricing: GridServicesModel
) -> tuple[tuple[_NamedAxis, ...], tuple[str, ...]]:
    """The sensitivity axes to sweep under *pricing*, paired with the names of the default's axes left out of them.

    They are *requested*, leaving out none, or those _DEFAULT_SENSITIVITY_NAMES
    names when it is None. Under an events configuration the default leaves out
    each axis that sweeps _FLAT_RATE_KNOB.

    Raises:
        ConfigurationError: If *pricing* is an events configuration and
            *requested* names an axis that sweeps _FLAT_RATE_KNOB.
    """
    default = _banded_axes(_DEFAULT_SENSITIVITY_NAMES)
    if not isinstance(pricing, GridServicesEventsConfig):
        return (default if requested is None else requested), ()
    if requested is None:
        return tuple(axis for axis in default if axis[1] != _FLAT_RATE_KNOB), _flat_rate_names(default)
    refused = _flat_rate_names(requested)
    if refused:
        raise ConfigurationError(
            f"--sensitivity names {', '.join(refused)}, which sweeps "
            f"{_FLAT_RATE_UNREAD_UNDER_EVENTS}; drop it from --sensitivity"
        )
    return requested, ()


def _with_grid_services_kw(
    scenario: ScenarioConfig, grid_services_kw: Optional[float], pricing: GridServicesModel
) -> ScenarioConfig:
    """*scenario* with *grid_services_kw* as its flat grid-services rate, or *scenario* itself when it is None.

    Raises:
        ConfigurationError: If *grid_services_kw*, whatever its value, is given
            and *pricing* is an events configuration.
    """
    if grid_services_kw is None:
        return scenario
    if isinstance(pricing, GridServicesEventsConfig):
        raise ConfigurationError(
            f"--grid-services-kw sets {_FLAT_RATE_UNREAD_UNDER_EVENTS}; drop the flag or "
            "set the scenario's finance.grid_services_model to type: flat"
        )
    return _FLAT_RATE_KNOB.apply(scenario, grid_services_kw)


def _with_retained_floor(scenario: ScenarioConfig, retained_floor: Optional[float]) -> ScenarioConfig:
    """*scenario* with *retained_floor* as its retained-cash floor, or *scenario* itself when it is None."""
    if retained_floor is None:
        return scenario
    return _RETAINED_FLOOR_KNOB.apply(scenario, retained_floor)


@app.command()
@handle_errors
def configs(
    ctx: typer.Context,
    scenario: Annotated[
        Path,
        typer.Argument(
            help="Path to fleet scenario YAML config file",
            exists=True,
            dir_okay=False,
        ),
    ],
    pv: Annotated[
        str,
        typer.Option(
            "--pv",
            help="Comma-separated PV DC capacities in kWp to sweep (e.g. '3,4,5,6')",
        ),
    ] = "3,4,5,6",
    battery: Annotated[
        str,
        typer.Option(
            "--battery",
            help="Comma-separated battery nameplate (total) capacities in kWh to sweep "
                 "(e.g. '0,5,10'); each battery's usable energy is capped by its "
                 "state-of-charge limits. Use 0 for no-battery.",
        ),
    ] = "0,5,10",
    inverter: Annotated[
        str,
        typer.Option(
            "--inverter",
            help="Comma-separated AC inverter capacities in kW to sweep (e.g. '3.68,5,6')",
        ),
    ] = "3.68,5,6",
    retained_floor: Annotated[
        Optional[float],
        typer.Option(
            "--retained-floor",
            help=(
                "Set the CBS retained-cash floor (£/home/yr) on the scenario's finance "
                "block before enumeration, as the retained_floor knob does.  Defaults to "
                "the finance block's value."
            ),
        ),
    ] = None,
    grid_services_kw: Annotated[
        Optional[float],
        typer.Option(
            "--grid-services-kw",
            help=(
                "Override the flat grid-services income (£/kW/yr) baked into the base "
                "finance config before enumeration.  Refused under a grid_services_model of "
                "type: capacity_at_events, which reads no flat rate."
            ),
        ),
    ] = None,
    sensitivity: Annotated[
        Optional[str],
        typer.Option(
            "--sensitivity",
            help=(
                "Comma-separated knob names or aliases of OAT sensitivity axes to sweep "
                "(e.g. 'retained_floor,grid_services').  Defaults to "
                "retained_floor,grid_services, or to retained_floor alone under a "
                "grid_services_model of type: capacity_at_events, which refuses grid_services.  "
                "Use '' to skip sensitivity.  "
                "Knobs with a sensitivity band, each with its aliases: "
                + names_with_aliases(SENSITIVITY_BANDS)
            ),
        ),
    ] = None,
    start: StartOption = None,
    end: EndOption = None,
) -> None:
    """Run a discrete install-config sweep and produce a board-readable ranking report.

    Enumerates homogeneous-install scenarios over the cartesian product of
    PV/battery/inverter capacity dimensions, solves the CBS cost-recovery rate
    for each config, ranks by householder outlay, and renders a two-table
    markdown report (cost-recovery rank + configured-rate trade-off).

    When the sensitivity axes are non-empty, a one-at-a-time (OAT) sensitivity
    panel is appended showing which cost assumptions most affect the top-ranked
    config.  --sensitivity defaults to retained_floor,grid_services, or to
    retained_floor alone, with a note on stderr, when the finance block's
    grid_services_model is of type: capacity_at_events, which reads no flat rate for the
    grid_services axis to sweep; there an explicit grid_services axis is
    refused, as is --grid-services-kw, before any simulation.  The panel is
    skipped, with a note on stderr, when the sweep yields no feasible config.

    Example::

        solar-challenge optimize configs scenarios/bristol-phase1.yaml \\
            --pv 3,4,5,6 --battery 0,5,10 --inverter 3.68,5 \\
            --retained-floor 27 --sensitivity retained_floor,grid_services \\
            --start 2024-01-01 --end 2024-01-07
    """
    cli = invocation(ctx)

    # ---- Parse dim lists ----------------------------------------------------
    pv_list = _parse_float_list(pv, "pv")
    battery_list = _parse_float_list(battery, "battery")
    inverter_list = _parse_float_list(inverter, "inverter")

    # ---- Parse sensitivity names -------------------------------------------
    requested_sensitivity = None if sensitivity is None else _parse_sensitivity(sensitivity)

    # ---- Load the scenario and its finance block -----------------------------
    scenario_config = with_window_options(load_scenario(scenario), start=start, end=end)
    pricing = required_finance(scenario_config).grid_services_model
    base = _with_retained_floor(
        _with_grid_services_kw(scenario_config, grid_services_kw, pricing), retained_floor
    )
    finance = required_finance(base)
    sensitivity_axes, left_out_of_the_default = _resolve_sensitivity_axes(requested_sensitivity, pricing)
    for name in left_out_of_the_default:
        print_info(
            cli,
            f"Sensitivity axis {name} omitted from the default: it sweeps "
            f"{_FLAT_RATE_UNREAD_UNDER_EVENTS}."
        )

    days = base.window().days
    n_homes = len(base.simulated_homes())

    n_configs = len(pv_list) * len(battery_list) * len(inverter_list)
    print_info(
        cli,
        f"Sweeping {len(pv_list)}×{len(battery_list)}×{len(inverter_list)} "
        f"={n_configs} configs "
        f"over {n_homes} homes for {days} days…"
    )

    _LARGE_SWEEP_THRESHOLD = 100_000
    ages = fewest_simulated_ages(finance.asset_life_years)
    home_days = n_configs * ages * n_homes * days
    if home_days > _LARGE_SWEEP_THRESHOLD:
        print_info(
            cli,
            f"⚠  Large sweep: {n_configs} config(s) × at least {ages} simulated age(s) per projection × "
            f"{n_homes} home(s) × {days} day(s) ≈ {home_days:,} home-days. "
            "For exploratory runs, use --start / --end to limit the simulation window "
            "(e.g. --start 2024-01-01 --end 2024-01-07)."
        )

    # ---- Enumerate configs --------------------------------------------------
    all_configs = enumerate_configs(base, pv_list, battery_list, inverter_list)

    # ---- Run sweep ----------------------------------------------------------
    print_info(cli, "Solving cost-recovery rates…")
    simulate = cli.runner.simulate
    ranked = run_sweep(all_configs, simulate=simulate)

    # Report sweep summary so the user knows what to expect in the report.
    n_feasible = len(ranked.results)
    n_infeasible = len(ranked.infeasible)
    if n_feasible:
        print_info(
            cli,
            f"Sweep complete: {n_feasible} feasible config(s), "
            f"{n_infeasible} infeasible config(s)."
        )
    else:
        # Graceful no-feasible case: the report still renders Table 1 with an
        # empty rank and infeasible list.  sensitivity_panel is NOT called
        # (it requires a feasible baseline) — see the guard below.
        print_info(
            cli,
            f"No feasible configurations found "
            f"({n_infeasible} config(s) exceeded the retail rate). "
            "Check the finance block or try lower capex / higher grid-services values."
        )

    # ---- Optional sensitivity panel ----------------------------------------
    panel = None
    if sensitivity_axes and ranked.cheapest_feasible is not None:
        axes_map = {knob: SENSITIVITY_BANDS[knob] for _, knob in sensitivity_axes}
        print_info(cli, f"Computing sensitivity panel for axes: {[name for name, _ in sensitivity_axes]}…")
        panel = sensitivity_panel(all_configs, axes_map, baseline=ranked, simulate=simulate)
    elif sensitivity_axes and ranked.cheapest_feasible is None:
        # Explicit user message when axes were requested but there is no feasible
        # baseline — sensitivity_panel would raise immediately, so we skip it.
        print_info(
            cli,
            "Sensitivity panel skipped: no feasible baseline config found "
            "(sensitivity requires at least one feasible config)."
        )

    # ---- Render report ------------------------------------------------------
    report = generate_config_ranking_report(ranked, panel)
    print_report(report)
