# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Synthetic homes, scenarios and constant-power simulation results for the finance tests.

Tests of ``project_multi_year`` and ``solve_cost_recovery_rate`` inject their own
``simulate``, so they need fleet results whose totals they choose rather than a
PVGIS-driven simulation.  This module is the one place those fixtures are spelled:
a default 4 kWp Bristol home, with or without a battery, or fitted with a given
install, scenarios of n such homes or of given homes, and ``SimulationResults``
whose ``calculate_summary`` totals are exactly the kWh the caller passes, their
flows priced as simulate_home prices them at the ``RunPricing`` it passes.

Usage::

    from tests._finance_builders import make_fleet_results, make_scenario_and_finance

    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=25)
    fleet = make_fleet_results(n_homes=2, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)
    curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)

A home whose export earns SEG income at 5 p/kWh is priced
``pricing=RunPricing(None, 5.0)``; by default no tariff and no SEG priced the run.

A simulate that answers each aged fleet it is asked for pairs its results with
those homes: ``simulate=lambda fc, s, e: make_fleet_results(homes=fc.homes, ...)``.

A fleet of homes whose results differ is
``make_fleet_results_of([make_sim_results(...), make_sim_results(...)])``, each
result on a default home unless ``homes=`` is given.

The window a result covers is ``make_window(days=..., first_day=..., cadence=...)``
of the same arguments, which a hand-built ``SummaryStatistics`` names as its window.
make_scenario's period is ``make_period()``, the default window's dates, so a
builder scenario's ``simulate`` is asked for the window its default results cover.

"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import date, timedelta

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, RunPricing, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.timebase import SimulationWindow


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


def make_sized_home(
    *,
    pv_kwp: float,
    battery_kwh: float | None = None,
    inverter_kw: float | None = None,
) -> HomeConfig:
    """make_home_config's home fitted with the install project_economics prices.

    make_pv_config's array is resized to *pv_kwp* kWp on an *inverter_kw* kW
    inverter, sized to the array by default, and the home has a *battery_kwh* kWh
    battery, none by default.
    """
    battery = None if battery_kwh is None else BatteryConfig(capacity_kwh=battery_kwh)
    return dataclasses.replace(
        make_home_config(battery_config=battery),
        pv_config=dataclasses.replace(make_pv_config(), capacity_kw=pv_kwp, inverter_capacity_kw=inverter_kw),
    )


# 2021 is not a leap year, so the default window's 365 days are its whole calendar year.
_DEFAULT_WINDOW_FIRST_DAY = date(2021, 1, 1)
_DEFAULT_WINDOW_DAYS = 365
_DEFAULT_WINDOW_CADENCE = timedelta(hours=1)


def make_window(
    *,
    days: int = _DEFAULT_WINDOW_DAYS,
    first_day: date = _DEFAULT_WINDOW_FIRST_DAY,
    cadence: timedelta = _DEFAULT_WINDOW_CADENCE,
) -> SimulationWindow:
    """The Europe/London window over *days* local dates from *first_day*, both counted, its rows *cadence* apart, hourly by default."""
    return SimulationWindow(first_day, first_day + timedelta(days=days - 1), cadence, "Europe/London")


def make_period() -> SimulationPeriod:
    """The SimulationPeriod over make_window()'s local dates: the year make_sim_results covers by default."""
    window = make_window()
    return SimulationPeriod(start_date=window.first_day.isoformat(), end_date=window.last_day.isoformat())


def make_scenario(
    *,
    n_homes: int = 1,
    seg_tariff_pence_per_kwh: float | None = None,
    battery_config: BatteryConfig | None = None,
    finance: FinanceConfig | None = None,
) -> ScenarioConfig:
    """A scenario over make_period() of *n_homes* make_home_config homes, each with *battery_config*.

    The scenario-level SEG rate is *seg_tariff_pence_per_kwh*.  Its finance block
    is *finance*, which enumerate_configs copies into each config and run_sweep
    reads.  By default the homes have no battery and the scenario has no SEG rate
    or finance block.
    """
    return ScenarioConfig(
        name="test-scenario",
        period=make_period(),
        description="Unit test scenario",
        homes=tuple(make_home_config(battery_config=battery_config) for _ in range(n_homes)),
        seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh,
        finance=finance,
    )


def make_scenario_of(homes: Sequence[HomeConfig]) -> ScenarioConfig:
    """make_scenario's scenario, holding exactly *homes*."""
    return dataclasses.replace(make_scenario(), homes=tuple(homes))


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


_UNPRICED = RunPricing(None, None)
"""How simulate_home records a run that no tariff and no SEG priced."""


def _rates_gbp_per_kwh(pricing: RunPricing | None) -> tuple[float | None, float | None]:
    """The £ each kWh of import costs and each kWh of export earns at *pricing*'s rates: None for a flow it leaves unpriced, and for both without pricing."""
    if pricing is None:
        return None, None
    seg_rate = pricing.seg_rate_pence_per_kwh
    return pricing.import_tariff_mean_rate_gbp_per_kwh, (None if seg_rate is None else seg_rate / 100.0)


def _priced(kwh: float, rate_gbp_per_kwh: float | None, rows: pd.DatetimeIndex) -> pd.Series:
    """Each of *rows*' equal share of *kwh* priced at *rate_gbp_per_kwh*, or 0.0 in every row when no rate priced it."""
    if rate_gbp_per_kwh is None:
        return pd.Series(0.0, index=rows)
    return pd.Series(kwh * rate_gbp_per_kwh / len(rows), index=rows)


def make_sim_results(
    *,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    discharge_kwh: float = 0.0,
    pricing: RunPricing | None = _UNPRICED,
    days: int = _DEFAULT_WINDOW_DAYS,
    first_day: date = _DEFAULT_WINDOW_FIRST_DAY,
    cadence: timedelta = _DEFAULT_WINDOW_CADENCE,
) -> SimulationResults:
    """Constant-power SimulationResults for one home over *days* local dates from *first_day*.

    ``calculate_summary`` of the result totals exactly the arguments: the kWh of
    self-consumption, export, import and battery discharge.  Generation is
    self + export, demand is self + import - discharge, ``simulation_days`` is
    *days*, and the window is ``make_window(days=days, first_day=first_day,
    cadence=cadence)``.  By default that is make_window()'s window, one whole
    calendar year: annualisation scale 1, a whole year's standing charge.

    The flows are priced as simulate_home prices them, and the results record
    *pricing*: the import costs its import rate, each row's tariff_rate, and the
    export earns its SEG rate.  A flow whose rate is None, or both when *pricing*
    is None, costs or earns nothing, at a tariff_rate of 0.0.  By default no tariff
    and no SEG priced the run, as simulate_home records RunPricing(None, None) for
    a home with neither.

    The rows are *cadence* apart, hourly by default, which suffices because
    ``calculate_summary`` integrates each row over the time it lasts.  The rows
    are the window's, fewer or more of them on a day the clocks change: each kWh
    total is spread over the window's hours as a constant kW = kWh / hours, and
    each row holds an equal share of the £ of import cost and of export revenue.
    """
    window = make_window(days=days, first_day=first_day, cadence=cadence)
    idx = window.rows()
    n_steps = len(idx)
    hours = n_steps * window.step_hours
    sc_kw = self_kwh / hours
    exp_kw = export_kwh / hours
    imp_kw = import_kwh / hours
    dis_kw = discharge_kwh / hours
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw - dis_kw
    import_rate, export_rate = _rates_gbp_per_kwh(pricing)

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
        import_cost=_priced(import_kwh, import_rate, idx),
        export_revenue=_priced(export_kwh, export_rate, idx),
        tariff_rate=pd.Series(0.0 if import_rate is None else import_rate, index=idx),
        pricing=pricing,
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
    return FleetResults(per_home_results=tuple(per_home_results), home_configs=tuple(homes))


def make_fleet_results(
    *,
    n_homes: int | None = None,
    homes: Sequence[HomeConfig] | None = None,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    discharge_kwh: float = 0.0,
    pricing: RunPricing | None = _UNPRICED,
    days: int = _DEFAULT_WINDOW_DAYS,
) -> FleetResults:
    """Each home of a fleet paired with make_sim_results of the given totals over *days* days, priced at *pricing*.

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
                pricing=pricing,
                days=days,
            )
            for _ in range(n_results)
        ],
        homes=homes,
    )
