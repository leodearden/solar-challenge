# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for tests/_fin_calibration.py, the [FIN] calibration facts and fixtures that θ and CR6 share."""

import dataclasses

import pytest

from tests._fin_calibration import (
    FIN_GOLDEN,
    FIN_SCF,
    PHYSICS_COLUMN_DAYS,
    make_fin_finance,
    make_fin_spreadsheet_curve,
    make_physics_column_scenario,
)
from tests._finance_builders import make_sized_home


def test_fin_finance_varies_only_the_self_consumption_override() -> None:
    physics = make_fin_finance(self_consumption_override=None)
    spreadsheet = make_fin_finance(self_consumption_override=FIN_SCF)

    assert physics.self_consumption_override is None
    assert spreadsheet.self_consumption_override == FIN_SCF
    assert dataclasses.replace(spreadsheet, self_consumption_override=None) == physics


def test_fin_finance_takes_its_spreadsheet_cells_from_fin_golden() -> None:
    finance = make_fin_finance(self_consumption_override=None)

    assert finance.grant_gbp == FIN_GOLDEN["grant_gbp"]
    assert finance.equity_fraction == FIN_GOLDEN["equity_fraction"]
    assert finance.loan_term_years == FIN_GOLDEN["loan_term_years"]
    assert finance.loan_rate == FIN_GOLDEN["loan_rate"]
    assert finance.own_use_rate_pence_per_kwh == FIN_GOLDEN["own_use_rate_pence_per_kwh"]


def test_fin_spreadsheet_curve_prices_the_golden_yield_at_fin_scf_and_the_golden_rates() -> None:
    curve = make_fin_spreadsheet_curve(n_homes=3, asset_life_years=20)

    generation_kwh = 3 * FIN_GOLDEN["inp_kWp"] * FIN_GOLDEN["inp_kWhPerkWp"]
    own_use_kwh = FIN_SCF * generation_kwh
    export_kwh = generation_kwh - own_use_kwh
    revenue_gbp = (
        own_use_kwh * FIN_GOLDEN["own_use_rate_pence_per_kwh"]
        + export_kwh * FIN_GOLDEN["export_rate_pence_per_kwh"]
    ) / 100.0
    assert len(curve.points) == 20
    for point in curve.points:
        assert point.fleet_billed_own_use_kwh == pytest.approx(own_use_kwh)
        assert point.fleet_export_kwh == pytest.approx(export_kwh)
        assert point.fleet_revenue_gbp == pytest.approx(revenue_gbp)


def test_physics_column_homes_are_the_golden_fin_install_on_their_own_load() -> None:
    install = make_sized_home(pv_kwp=FIN_GOLDEN["inp_kWp"], battery_kwh=FIN_GOLDEN["inp_Batt_kWh"])

    for home in make_physics_column_scenario().homes:
        assert dataclasses.replace(home, load_config=install.load_config) == install


def test_physics_column_runs_over_every_one_of_physics_column_days() -> None:
    first_day, last_day = PHYSICS_COLUMN_DAYS.window()
    period = make_physics_column_scenario().period

    assert (period.get_start_timestamp().date(), period.get_end_timestamp().date()) == (
        first_day.date(),
        last_day.date(),
    )


def test_fin_golden_cells_cannot_be_reassigned() -> None:
    with pytest.raises(TypeError):
        FIN_GOLDEN["grant_gbp"] = 0.0
