# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for W3 sweep E: generate_config_ranking_report + optimize CLI.

This file MIXES fast and slow tests and must NOT be added to
tests/unit/test_marker_registration.py's INTEGRATION_FILES allow-list.
The slow class carries @pytest.mark.slow directly; the fast classes run
in the offline verify loop.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# §A — Helper factories (adapted from test_cost_recovery_cli.py)
# ---------------------------------------------------------------------------


def _make_bill_breakdown(total_outlay: float = 367.5) -> "BillBreakdown":  # type: ignore[name-defined]
    """Build a minimal BillBreakdown for fixture use."""
    from solar_challenge.finance import BillBreakdown

    return BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=total_outlay,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=132.5,
        saving_pct=26.5,
        self_consumption_fraction=0.35,
    )


def _make_bill_distribution(
    min_gbp: float = 310.0,
    mean_gbp: float = 355.0,
    median_gbp: float = 360.0,
    max_gbp: float = 410.0,
) -> "BillDistribution":  # type: ignore[name-defined]
    """Build a minimal BillDistribution for fixture use."""
    from solar_challenge.finance import BillDistribution

    rep = _make_bill_breakdown(total_outlay=median_gbp)
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(min_gbp, mean_gbp, max_gbp),
        min_gbp=min_gbp,
        mean_gbp=mean_gbp,
        median_gbp=median_gbp,
        max_gbp=max_gbp,
    )


def _make_solution(
    own_use_rate: float = 15.0,
    net_surplus: float = 27.0,
    feasible: bool = True,
    binding: str = "floor",
    outlay: "Optional[BillDistribution]" = None,  # type: ignore[name-defined]
) -> "CostRecoverySolution":  # type: ignore[name-defined]
    """Build a minimal CostRecoverySolution for fixture use."""
    from solar_challenge.finance import CostRecoverySolution

    dist = outlay if outlay is not None else _make_bill_distribution()
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate,
        outlay=dist,
        representative_outlay_gbp=dist.median_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus,
        saving_vs_baseline_gbp=dist.representative.saving_vs_baseline_gbp,
        saving_pct=dist.representative.saving_pct,
        feasible=feasible,
        binding=binding,
    )


def _make_config_result(
    pv_kwp: float = 4.0,
    battery_kwh: float = 0.0,
    inverter_kw: float = 5.0,
    own_use_rate: float = 15.0,
    net_surplus: float = 27.0,
    feasible: bool = True,
    binding: str = "floor",
    total_capex: float = 50_000.0,
    min_dscr: float = float("inf"),
    equity_irr: float = 0.08,
    payback_years: Optional[float] = 12.5,
    baseline_outlay: float = 380.0,
    baseline_surplus: float = 45.0,
    outlay_min: float = 310.0,
    outlay_mean: float = 355.0,
    outlay_median: float = 360.0,
    outlay_max: float = 410.0,
) -> "ConfigResult":  # type: ignore[name-defined]
    """Build a ConfigResult with distinct numeric values for each field."""
    from solar_challenge.optimize import ConfigPoint, ConfigResult

    point = ConfigPoint(pv_kwp=pv_kwp, battery_kwh=battery_kwh, inverter_kw=inverter_kw)
    dist = _make_bill_distribution(
        min_gbp=outlay_min,
        mean_gbp=outlay_mean,
        median_gbp=outlay_median,
        max_gbp=outlay_max,
    )
    solution = _make_solution(
        own_use_rate=own_use_rate,
        net_surplus=net_surplus,
        feasible=feasible,
        binding=binding,
        outlay=dist,
    )
    return ConfigResult(
        config=point,
        solution=solution,
        representative_outlay_gbp=outlay_median,
        solved_own_use_rate_pence_per_kwh=own_use_rate,
        surplus_at_solved_gbp=net_surplus,
        feasible=feasible,
        binding=binding,
        total_capex_gbp=total_capex,
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        baseline_outlay_gbp=baseline_outlay,
        baseline_surplus_per_home_gbp=baseline_surplus,
    )


def _make_ranked_sweep(
    results: "tuple[ConfigResult, ...]",
    infeasible: "tuple[ConfigPoint, ...]" = (),
    pareto: "tuple[ConfigPoint, ...]" = (),
    floor: float = 27.0,
) -> "RankedSweep":  # type: ignore[name-defined]
    """Assemble a RankedSweep honouring cheapest_feasible == results[0].config invariant."""
    from solar_challenge.optimize import RankedSweep

    cheapest = results[0].config if results else None
    return RankedSweep(
        results=results,
        infeasible=infeasible,
        retained_cash_floor_gbp=floor,
        cheapest_feasible=cheapest,
        pareto_baseline=pareto,
    )


def _make_sensitivity_panel(
    axes: "tuple[SensitivityAxis, ...]",  # type: ignore[name-defined]
    baseline_top: "ConfigPoint",  # type: ignore[name-defined]
    rank_stability: float = 0.8,
) -> "SensitivityPanel":  # type: ignore[name-defined]
    """Build a SensitivityPanel for fixture use."""
    from solar_challenge.optimize import SensitivityPanel

    return SensitivityPanel(
        axes=axes,
        baseline_top=baseline_top,
        rank_stability=rank_stability,
    )


def _make_sensitivity_axis(
    name: str = "grid_services_income_per_kw_per_year_gbp",
    values: "tuple[float, ...]" = (1.5, 12.0, 48.0),
    top_config: "ConfigPoint | None" = None,  # type: ignore[name-defined]
) -> "SensitivityAxis":  # type: ignore[name-defined]
    """Build a SensitivityAxis for fixture use."""
    from solar_challenge.optimize import ConfigPoint, SensitivityAxis

    if top_config is None:
        top_config = ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=5.0)
    rankings: tuple[tuple[ConfigPoint, ...], ...] = tuple(
        (top_config,) for _ in values
    )
    top_per_value: tuple[Optional[ConfigPoint], ...] = tuple(top_config for _ in values)
    return SensitivityAxis(
        name=name,
        values=values,
        rankings=rankings,
        top_config_per_value=top_per_value,
    )


# ---------------------------------------------------------------------------
# §B — Fast-simulate FleetResults factory (mirrors test_cost_recovery_cli.py §E)
# ---------------------------------------------------------------------------


def _make_pv_config(system_age_years: float = 0.0) -> "PVConfig":  # type: ignore[name-defined]
    from solar_challenge.pv import PVConfig

    return PVConfig(
        capacity_kw=4.0,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )


def _make_load_config() -> "LoadConfig":  # type: ignore[name-defined]
    from solar_challenge.load import LoadConfig

    return LoadConfig(annual_consumption_kwh=3500.0)


def _make_home_config() -> "HomeConfig":  # type: ignore[name-defined]
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    return HomeConfig(
        pv_config=_make_pv_config(),
        load_config=_make_load_config(),
        location=Location.bristol(),
    )


def _make_sim_results(
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    n_minutes: int = 525600,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a 365-day SimulationResults for constant-sim fixture use."""
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)
    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _make_fleet_results(n_homes: int = 5) -> "FleetResults":  # type: ignore[name-defined]
    """Build a FleetResults yielding binding='floor', feasible=True when solved.

    Uses full-year 525600-minute Series (365 × 24 × 60) so no annualisation
    is triggered by the CLI's default full-year window.
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [
        _make_sim_results(
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
            n_minutes=525600,
        )
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _write_optimize_scenario(tmp_path: Path, n_homes: int = 5) -> Path:
    """Write a minimal feasible-regime scenario YAML to tmp_path."""
    import yaml

    scenario = {
        "name": "W3 Optimize CLI Test",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": {
            "standing_charge_pence_per_day": 28.0,
            # Interior feasibility: high capex, no grant, floor=100, retail=30p
            "pv_cost_per_kwp_gbp": 2000.0,
            "battery_cost_per_kwh_gbp": 300.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 0.0,
            "own_use_rate_pence_per_kwh": 15.0,
            "retained_cash_floor_per_home_per_year_gbp": 100.0,
            "retail_baseline_rate_pence_per_kwh": 30.0,
            "asset_life_years": 25,
            "vat_rate": 0.05,
        },
    }
    path = tmp_path / "optimize_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path
