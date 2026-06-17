# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Optimize CLI commands for W3 discrete install-config sweep (task E / PRD §3.6 / §10-E)."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from solar_challenge.cli.utils import console, handle_errors, print_info

app = typer.Typer(help="Discrete install-config sweep and optimisation commands (W3)")

# Short-name → FinanceConfig field-name alias map for --sensitivity.
# Values: (field_name, default_band) where default_band is the swept value sequence
# used when the axis is in the default-on set.
_SENSITIVITY_ALIAS_MAP: dict[str, tuple[str, tuple[float, ...]]] = {
    "grid_services": (
        "grid_services_income_per_kw_per_year_gbp",
        (1.5, 12.0, 48.0),
    ),
    "retained_floor": (
        "retained_cash_floor_per_home_per_year_gbp",
        (15.0, 27.0, 40.0),
    ),
    "battery_cost": (
        "battery_cost_per_kwh_gbp",
        (200.0, 300.0, 450.0),
    ),
    "pv_cost": (
        "pv_cost_per_kwp_gbp",
        (800.0, 1200.0, 1800.0),
    ),
    "inverter_cost": (
        "inverter_cost_per_kw_gbp",
        (100.0, 200.0, 350.0),
    ),
}


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


@app.command()
@handle_errors
def configs(
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
            help="Comma-separated battery usable capacities in kWh to sweep (e.g. '0,5,10'). "
                 "Use 0 for no-battery.",
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
                "Override the CBS retained-cash floor (£/home/yr) used by run_sweep "
                "and sensitivity_panel.  Defaults to the scenario finance block value."
            ),
        ),
    ] = None,
    grid_services_kw: Annotated[
        Optional[float],
        typer.Option(
            "--grid-services-kw",
            help=(
                "Override grid-services income (£/kW/yr) baked into the base finance "
                "config before enumeration."
            ),
        ),
    ] = None,
    sensitivity: Annotated[
        str,
        typer.Option(
            "--sensitivity",
            help=(
                "Comma-separated short alias names of OAT sensitivity axes to sweep "
                "(e.g. 'retained_floor,grid_services').  Use '' to skip sensitivity. "
                "Supported aliases: " + ", ".join(sorted(_SENSITIVITY_ALIAS_MAP))
            ),
        ),
    ] = "retained_floor,grid_services",
    start: Annotated[
        Optional[str],
        typer.Option(
            "--start",
            help=(
                "Simulation start date (YYYY-MM-DD).  Overrides the scenario 'period' "
                "block if present; defaults to the scenario period start or 2024-01-01."
            ),
        ),
    ] = None,
    end: Annotated[
        Optional[str],
        typer.Option(
            "--end",
            help=(
                "Simulation end date (YYYY-MM-DD).  Overrides the scenario 'period' "
                "block if present; defaults to the scenario period end or 2024-12-31."
            ),
        ),
    ] = None,
) -> None:
    """Run a W3 discrete install-config sweep and produce a board-readable ranking report.

    Enumerates homogeneous-install scenarios over the cartesian product of
    PV/battery/inverter capacity dimensions, solves the CBS cost-recovery rate
    for each config, ranks by householder outlay, and renders a two-table
    markdown report (cost-recovery rank + fixed-15p trade-off).

    When --sensitivity is non-empty, a one-at-a-time (OAT) sensitivity panel
    is appended showing which cost assumptions most affect the top-ranked config.
    The panel is skipped gracefully when the baseline sweep yields no feasible
    config (sensitivity_panel raises ValueError for an empty feasible baseline).

    Example::

        solar-challenge optimize configs scenarios/bristol-phase1.yaml \\
            --pv 3,4,5,6 --battery 0,5,10 --inverter 3.68,5 \\
            --retained-floor 27 --sensitivity retained_floor,grid_services \\
            --start 2024-01-01 --end 2024-01-07
    """
    import dataclasses

    import pandas as pd

    from solar_challenge.config import (
        ConfigurationError,
        ScenarioConfig,
        SimulationPeriod,
        _parse_finance_config,
        _parse_seg_config,
        load_config,
        load_fleet_config,
    )
    from solar_challenge.optimize import (
        enumerate_configs,
        run_sweep,
        sensitivity_panel,
    )
    from solar_challenge.output import generate_config_ranking_report
    from solar_challenge.seg import SEGTariff

    # ---- Parse dim lists ----------------------------------------------------
    pv_list = _parse_float_list(pv, "pv")
    battery_list = _parse_float_list(battery, "battery")
    inverter_list = _parse_float_list(inverter, "inverter")

    # ---- Parse sensitivity aliases -----------------------------------------
    sensitivity_axes: list[str] = []
    if sensitivity.strip():
        for alias in [a.strip() for a in sensitivity.split(",") if a.strip()]:
            if alias not in _SENSITIVITY_ALIAS_MAP:
                known = ", ".join(sorted(_SENSITIVITY_ALIAS_MAP))
                raise ValueError(
                    f"Unknown sensitivity alias '{alias}'. Known aliases: {known}"
                )
            sensitivity_axes.append(alias)

    # ---- Load raw config + finance block ------------------------------------
    raw = load_config(scenario)
    finance = _parse_finance_config(raw.get("finance"))
    if finance is None:
        raise ConfigurationError(
            "No 'finance:' block found in the scenario file. "
            "Add a finance: block with at least standing_charge_pence_per_day."
        )

    # ---- Apply --grid-services-kw override onto finance --------------------
    if grid_services_kw is not None:
        finance = dataclasses.replace(
            finance,
            grid_services_income_per_kw_per_year_gbp=grid_services_kw,
        )

    # ---- Load fleet config --------------------------------------------------
    fleet_config = load_fleet_config(scenario)

    # Thread SEG tariff onto each home
    seg_rate = _parse_seg_config(raw.get("seg"))
    if seg_rate is not None:
        seg_tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)
        homes_with_seg = [
            dataclasses.replace(home, seg_tariff=seg_tariff)
            for home in fleet_config.homes
        ]
        fleet_config = dataclasses.replace(fleet_config, homes=homes_with_seg)

    # ---- Resolve start/end: CLI args override scenario period; fall back to
    #      2024-01-01 / 2024-12-31 when neither is present. ---------------
    loc = fleet_config.homes[0].location
    _scenario_period: dict[str, str] = raw.get("period", {}) or {}
    _start_str = start or _scenario_period.get("start_date", "2024-01-01")
    _end_str = end or _scenario_period.get("end_date", "2024-12-31")
    start_date = pd.Timestamp(_start_str, tz=loc.timezone)
    end_date = pd.Timestamp(_end_str, tz=loc.timezone)
    days = (end_date - start_date).days + 1
    n_homes = len(fleet_config.homes)

    print_info(
        f"Sweeping {len(pv_list)}×{len(battery_list)}×{len(inverter_list)} "
        f"={len(pv_list)*len(battery_list)*len(inverter_list)} configs "
        f"over {n_homes} homes for {days} days…"
    )

    # ---- Build base ScenarioConfig ------------------------------------------
    base = ScenarioConfig(
        name=raw.get("name", str(scenario)),
        period=SimulationPeriod(
            start_date=_start_str,
            end_date=_end_str,
        ),
        homes=list(fleet_config.homes),
        location=loc,
        finance=finance,
    )
    if seg_rate is not None:
        base = dataclasses.replace(base, seg_tariff_pence_per_kwh=seg_rate)

    # ---- Enumerate configs --------------------------------------------------
    all_configs = enumerate_configs(base, pv_list, battery_list, inverter_list)

    # ---- Run sweep ----------------------------------------------------------
    print_info("Solving cost-recovery rates…")
    ranked = run_sweep(all_configs, retained_cash_floor_gbp=retained_floor)

    # Report sweep summary so the user knows what to expect in the report.
    n_feasible = len(ranked.results)
    n_infeasible = len(ranked.infeasible)
    if n_feasible:
        print_info(
            f"Sweep complete: {n_feasible} feasible config(s), "
            f"{n_infeasible} infeasible config(s)."
        )
    else:
        # Graceful no-feasible case: the report still renders Table 1 with an
        # empty rank and infeasible list.  sensitivity_panel is NOT called
        # (it requires a feasible baseline) — see the guard below.
        print_info(
            f"No feasible configurations found "
            f"({n_infeasible} config(s) exceeded the retail rate). "
            "Check the finance block or try lower capex / higher grid-services values."
        )

    # ---- Optional sensitivity panel ----------------------------------------
    panel = None
    if sensitivity_axes and ranked.cheapest_feasible is not None:
        axes_map: dict[str, list[float]] = {}
        for alias in sensitivity_axes:
            field_name, default_band = _SENSITIVITY_ALIAS_MAP[alias]
            axes_map[field_name] = list(default_band)
        print_info(f"Computing sensitivity panel for axes: {sensitivity_axes}…")
        try:
            panel = sensitivity_panel(
                all_configs,
                axes_map,
                retained_cash_floor_gbp=retained_floor,
            )
        except ValueError as exc:
            # Gracefully skip panel if no feasible baseline (rather than crashing)
            print_info(f"Sensitivity panel skipped: {exc}")
    elif sensitivity_axes and ranked.cheapest_feasible is None:
        # Explicit user message when axes were requested but there is no feasible
        # baseline — sensitivity_panel would raise immediately, so we skip it.
        print_info(
            "Sensitivity panel skipped: no feasible baseline config found "
            "(sensitivity requires at least one feasible config)."
        )

    # ---- Render report ------------------------------------------------------
    report = generate_config_ranking_report(ranked, panel)
    console.print(report)
