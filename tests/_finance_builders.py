# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Synthetic homes, scenarios and constant-power simulation results for the finance tests.

Tests of ``project_multi_year`` and ``solve_cost_recovery_rate`` inject their own
``simulate``, so they need fleet results whose totals they choose rather than a
PVGIS-driven simulation.  This module is the one place those fixtures are spelled:
a default 4 kWp Bristol home, with or without a battery, scenarios of n such homes,
and ``SimulationResults`` whose ``calculate_summary`` totals are exactly the kWh and
£ the caller passes.

Usage::

    from tests._finance_builders import make_fleet_results, make_scenario_and_finance

    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=25)
    fleet = make_fleet_results(n_homes=2, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)
    curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)

A simulate that answers each aged fleet it is asked for pairs its results with
those homes: ``simulate=lambda fc, s, e: make_fleet_results(homes=fc.homes, ...)``.

A fleet of homes whose results differ is
``make_fleet_results_of([make_sim_results(...), make_sim_results(...)])``, each
result on a default home unless ``homes=`` is given.

"""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


def make_pv_config() -> PVConfig:
    """A new 4 kWp south-facing array at 35° tilt, degrading 0.5% a year."""
    return PVConfig(
        capacity_kw=4.0,
        azimuth=180.0,
        tilt=35.0,
        degradation_rate_per_year=0.005,
    )


def make_load_config() -> LoadConfig:
    """A household consuming 3,500 kWh a year."""
    return LoadConfig(annual_consumption_kwh=3500.0)


def make_home_config(*, battery_config: BatteryConfig | None = None) -> HomeConfig:
    """The default home: make_pv_config's array and make_load_config's load in Bristol.

    It has *battery_config*'s battery, or no battery by default.
    """
    return HomeConfig(
        pv_config=make_pv_config(),
        load_config=make_load_config(),
        battery_config=battery_config,
        location=Location.bristol(),
    )


def make_scenario(
    *,
    n_homes: int = 1,
    seg_tariff_pence_per_kwh: float | None = None,
    battery_config: BatteryConfig | None = None,
) -> ScenarioConfig:
    """A 2020 scenario of *n_homes* make_home_config homes, each with *battery_config*.

    The scenario-level SEG rate is *seg_tariff_pence_per_kwh*.  By default the
    homes have no battery and the scenario has no SEG rate.
    """
    return ScenarioConfig(
        name="test-scenario",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Unit test scenario",
        homes=[make_home_config(battery_config=battery_config) for _ in range(n_homes)],
        seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh,
    )


def make_scenario_and_finance(
    *,
    n_homes: int = 1,
    asset_life_years: int = 5,
    battery_config: BatteryConfig | None = None,
) -> tuple[ScenarioConfig, FinanceConfig]:
    """make_scenario's *n_homes* homes with *battery_config*, and a FinanceConfig over *asset_life_years*.

    The loan term is the default 15 years, cut to the asset life when that is
    shorter, as FinanceConfig requires.
    """
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life_years,
        loan_term_years=min(asset_life_years, 15),
    )
    return make_scenario(n_homes=n_homes, battery_config=battery_config), finance


def make_sim_results(
    *,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    discharge_kwh: float = 0.0,
    export_revenue_gbp: float = 0.0,
    days: int = 365,
) -> SimulationResults:
    """Constant-power SimulationResults for one home over *days* days, a full year by default.

    ``calculate_summary`` of the result totals exactly the arguments: the kWh of
    self-consumption, export, import and battery discharge, and the £ of export
    revenue, the physics SEG income.  Generation is self + export, demand is
    self + import - discharge, and ``simulation_days`` is *days*.

    Hourly steps suffice because ``calculate_summary`` integrates every step as
    one minute and takes ``simulation_days`` from the index span: each total is
    spread over the 24 * *days* steps as kW = kWh / (n_steps / 60).  Only the
    totals are meaningful; the peak kW is an artefact of that scaling.
    """
    n_steps = 24 * days
    idx = pd.date_range("2020-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = self_kwh / (n_steps / 60.0)
    exp_kw = export_kwh / (n_steps / 60.0)
    imp_kw = import_kwh / (n_steps / 60.0)
    dis_kw = discharge_kwh / (n_steps / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw - dis_kw

    zeros = pd.Series(0.0, index=idx)

    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=pd.Series(dis_kw, index=idx),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=pd.Series(export_revenue_gbp / n_steps, index=idx),
        tariff_rate=zeros.copy(),
    )


def make_fleet_results_of(
    per_home_results: Sequence[SimulationResults],
    *,
    homes: Sequence[HomeConfig] | None = None,
) -> FleetResults:
    """A fleet of *per_home_results*, each paired in order with a home of *homes*.

    Each home is a default make_home_config home unless *homes* is given.
    """
    if homes is None:
        homes = [make_home_config() for _ in per_home_results]
    elif len(homes) != len(per_home_results):
        raise ValueError(
            "make_fleet_results_of pairs one home with each result: "
            f"got {len(per_home_results)} results and {len(homes)} homes"
        )
    return FleetResults(per_home_results=list(per_home_results), home_configs=list(homes))


def make_fleet_results(
    *,
    n_homes: int | None = None,
    homes: Sequence[HomeConfig] | None = None,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    discharge_kwh: float = 0.0,
    export_revenue_gbp: float = 0.0,
    days: int = 365,
) -> FleetResults:
    """Each home of a fleet paired with make_sim_results of the given totals over *days* days.

    The fleet is *homes*, such as the aged ``fleet_config.homes`` an injected
    simulate receives, or else *n_homes* default homes, one by default.
    """
    if homes is None:
        n_results = 1 if n_homes is None else n_homes
    elif n_homes is None:
        n_results = len(homes)
    else:
        raise TypeError("make_fleet_results takes homes or n_homes, not both")
    return make_fleet_results_of(
        [
            make_sim_results(
                self_kwh=self_kwh,
                export_kwh=export_kwh,
                import_kwh=import_kwh,
                discharge_kwh=discharge_kwh,
                export_revenue_gbp=export_revenue_gbp,
                days=days,
            )
            for _ in range(n_results)
        ],
        homes=homes,
    )
