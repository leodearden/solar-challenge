# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""The [FIN] calibration facts and fixtures that θ and CR6 share.

θ (tests/integration/test_finance_calibration.py) and CR6
(tests/integration/test_cost_recovery_calibration.py) calibrate the finance layer
against the investor spreadsheet's [FIN] inputs.  This module spells those inputs
once for both:

- FIN_GOLDEN: the spreadsheet's named cells, among them the [FIN] install of
  5.5 kWp of PV and a 5 kWh battery per home;
- FIN_SCF: the spreadsheet's with-battery self-consumption fraction, 0.70;
- make_fin_finance: the [FIN] FinanceConfig, under the self-consumption override
  its caller prices own-use with;
- make_fin_spreadsheet_curve: the spreadsheet's flat revenue curve for a fleet of
  the [FIN] install, at FIN_SCF;
- PHYSICS_COLUMN_DAYS: the clear June days each suite's physics column simulates.
  Its module seeds them as Bristol's TMY with the fixture
  PHYSICS_COLUMN_DAYS.bristol_tmy_fixture() makes;
- make_physics_column_scenario: the fleet each physics column simulates over those
  days;
- simulate_physics_column: the simulator each physics column gives its finance
  call, which simulates that fleet in the test's own process.

Usage::

    from tests._fin_calibration import (
        FIN_SCF, PHYSICS_COLUMN_DAYS, make_fin_finance, make_fin_spreadsheet_curve,
        make_physics_column_scenario, simulate_physics_column,
    )

    bristol_june_tmy = PHYSICS_COLUMN_DAYS.bristol_tmy_fixture()

    sol = solve_cost_recovery_rate(  # in a test that uses bristol_june_tmy
        make_physics_column_scenario(),
        make_fin_finance(self_consumption_override=None),
        simulate=simulate_physics_column,
    )
    spreadsheet_finance = make_fin_finance(self_consumption_override=FIN_SCF)
    spreadsheet_curve = make_fin_spreadsheet_curve(
        n_homes=2, asset_life_years=spreadsheet_finance.asset_life_years
    )
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType

import pandas as pd

from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.finance import FinanceConfig, MultiYearCurve, spreadsheet_revenue_curve
from solar_challenge.fleet import FleetConfig, FleetResults, simulate_fleet
from solar_challenge.load import LoadConfig
from tests._finance_builders import make_sized_home
from tests._seeded_tmy import ClearJuneDays

# The investor spreadsheet's named cells, transcribed from
# finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm.  They were
# read 2026-06-16 with openpyxl (data_only) via `uv run --with openpyxl`, because
# openpyxl is not in the dev environment.  The .xlsm is not git-tracked and is NOT
# read at runtime.
FIN_GOLDEN: Mapping[str, float] = MappingProxyType({
    # Sensitivity sheet — named solver inputs
    "inp_kWp": 5.5,              # Sensitivity!B6  (inp_kWp)
    "inp_Batt_kWh": 5.0,         # Sensitivity!B7  (inp_Batt_kWh) — 5 kWh basis
    "inp_kWhPerkWp": 1050.0,     # Sensitivity!B8  (inp_kWhPerkWp)
    "out_MinCash_WithBatt": 96334.55,    # Sensitivity!B10
    "out_RetSurplus_WithBatt": 207841.20, # Sensitivity!B12
    # Capital Stack
    "capital_stack_b6": 775000.0,        # Capital_Stack!B6 — Total Capex at 5 kWh
    #   100 × (5.5×£1000 + £1000 + 5kWh×£250) = 100 × £7,750 = £775,000
    # Workings sheet — per-roof build-up at 10 kWh basis
    "workings_c57": 9000.0,      # Workings!C57 — £9,000/roof at 10 kWh
    #   5.5×1000 + 1000 + 10×250 = 5500+1000+2500 = £9,000
    "workings_c94": 900000.0,    # Workings!C94 — 100 × £9,000 = £900,000 (10 kWh basis)
    # §2.3 delta: £900,000 − £775,000 = £125,000 = 100 × 5kWh × £250 (battery size, NOT error)
    # Debt Analytics
    "min_dscr": 2.10378435678433,   # Debt_Analytics!B16 (Presentation Funders!E8, Stress_Test!B9)
    "avg_dscr": 3.1735282491711,    # Debt_Analytics!B17
    # Equity IRR: no single labelled cell; from Debt_Analytics row 13 'Cash for IRR'
    #   B13=-244821, C13=155947, D13=163911, E13=172837, ...
    #   The sheet's equity is net of formation costs / fundraising fees / dividend deferral,
    #   so the sheet equity_irr (~69% prose estimate) differs from our model (~11%).
    #   G6 fallback: assert structural floor equity_irr > 0.
    "equity_irr_floor": 0.0,  # G6 fallback: assert > 0
    # [FIN] cost/rate assumptions
    "own_use_rate_pence_per_kwh": 15.0,
    "export_rate_pence_per_kwh": 6.0,
    "grant_gbp": 250000.0,
    "equity_fraction": 0.75,
    "loan_term_years": 15,
    "loan_rate": 0.07,
})

# The spreadsheet's with-battery self-consumption fraction assumption.
FIN_SCF = 0.70

PHYSICS_COLUMN_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=3)
"""The clear June days each suite's physics column simulates, which its module seeds as Bristol's TMY."""


def make_fin_finance(*, self_consumption_override: float | None) -> FinanceConfig:
    """The [FIN] FinanceConfig: the spreadsheet's costs, financing and rates, its own-use set by *self_consumption_override*, or simulated when that is None.

    Every value is spelled, each spreadsheet cell from FIN_GOLDEN, so a change to a
    FinanceConfig default cannot move the calibration's inputs.
    """
    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        vat_rate=0.05,
        retail_baseline_rate_pence_per_kwh=23.0,
        self_consumption_override=self_consumption_override,
        pv_cost_per_kwp_gbp=1000.0,
        roof_fit_cost_gbp=1000.0,
        battery_cost_per_kwh_gbp=250.0,
        inverter_cost_per_kw_gbp=0.0,
        grant_gbp=FIN_GOLDEN["grant_gbp"],
        equity_fraction=FIN_GOLDEN["equity_fraction"],
        loan_term_years=FIN_GOLDEN["loan_term_years"],
        loan_rate=FIN_GOLDEN["loan_rate"],
        opex_per_home_per_year_gbp=131.0,
        asset_life_years=25,
        own_use_rate_pence_per_kwh=FIN_GOLDEN["own_use_rate_pence_per_kwh"],
        retained_cash_floor_per_home_per_year_gbp=27.0,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )


def make_fin_spreadsheet_curve(*, n_homes: int, asset_life_years: int) -> MultiYearCurve:
    """The spreadsheet's flat revenue curve for *n_homes* homes of the [FIN] install, at FIN_SCF.

    It spans *asset_life_years*, which is the asset life of the finance the curve is priced with.
    """
    return spreadsheet_revenue_curve(
        n_homes=n_homes,
        pv_kwp=FIN_GOLDEN["inp_kWp"],
        kwh_per_kwp=FIN_GOLDEN["inp_kWhPerkWp"],
        self_consumption_fraction=FIN_SCF,
        own_use_rate_pence_per_kwh=FIN_GOLDEN["own_use_rate_pence_per_kwh"],
        export_rate_pence_per_kwh=FIN_GOLDEN["export_rate_pence_per_kwh"],
        asset_life_years=asset_life_years,
    )


def make_physics_column_scenario() -> ScenarioConfig:
    """Two homes of the [FIN] install on a deterministic 3,400 kWh load, over every day of PHYSICS_COLUMN_DAYS.

    The fleet is small and the window short for speed.
    """
    home = dataclasses.replace(
        make_sized_home(pv_kwp=FIN_GOLDEN["inp_kWp"], battery_kwh=FIN_GOLDEN["inp_Batt_kWh"]),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1),
    )
    first_day, last_day = PHYSICS_COLUMN_DAYS.window(PHYSICS_COLUMN_DAYS.count)
    return ScenarioConfig(
        name="FIN-Physics-Column",
        period=SimulationPeriod(
            start_date=first_day.date().isoformat(), end_date=last_day.date().isoformat()
        ),
        homes=[home] * 2,
    )


def simulate_physics_column(
    config: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> FleetResults:
    """*config*'s fleet simulated by the real simulate_fleet in this process, which a physics column gives its finance call as simulate.

    It starts no worker pool, because a pool would fork the test process, which
    tests/conftest.py's offline guard makes multi-threaded.
    """
    return simulate_fleet(config, start_date, end_date, parallel=False)
