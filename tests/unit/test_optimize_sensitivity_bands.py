# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""SENSITIVITY_BANDS: the board-facing values to sweep for each sensitivity_panel knob."""
from __future__ import annotations

import pytest

from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS
from solar_challenge.optimize import SENSITIVITY_BANDS


def test_grid_services_band_is_the_rate_tables_flat_column_low_to_high() -> None:
    assert SENSITIVITY_BANDS["grid_services_income_per_kw_per_year_gbp"] == (
        GRID_SERVICES_RATE_BANDS.low.flat_gbp_per_kw_per_year,
        GRID_SERVICES_RATE_BANDS.central.flat_gbp_per_kw_per_year,
        GRID_SERVICES_RATE_BANDS.high.flat_gbp_per_kw_per_year,
    )


def test_sweeps_the_headline_axes_first_then_the_board_facing_capex_bands() -> None:
    assert list(SENSITIVITY_BANDS) == [
        "retained_cash_floor_per_home_per_year_gbp",
        "grid_services_income_per_kw_per_year_gbp",
        "battery_cost_per_kwh_gbp",
        "pv_cost_per_kwp_gbp",
        "inverter_cost_per_kw_gbp",
    ]
    non_flex_bands = {
        "retained_cash_floor_per_home_per_year_gbp": (15.0, 27.0, 40.0),
        "battery_cost_per_kwh_gbp": (200.0, 300.0, 450.0),
        "pv_cost_per_kwp_gbp": (800.0, 1200.0, 1800.0),
        "inverter_cost_per_kw_gbp": (100.0, 200.0, 350.0),
    }
    assert {knob: SENSITIVITY_BANDS[knob] for knob in non_flex_bands} == non_flex_bands


def test_cannot_be_changed_in_place() -> None:
    with pytest.raises(TypeError):
        SENSITIVITY_BANDS["pv_cost_per_kwp_gbp"] = (1.0,)  # type: ignore[index]
