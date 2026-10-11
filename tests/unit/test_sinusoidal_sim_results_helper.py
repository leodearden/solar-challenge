# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_sinusoidal_sim_results.py, the shared builder of a home's results at one row a minute, with sinusoidal generation and a flat demand."""

import numpy as np
import pandas as pd
import pytest

from solar_challenge.home import calculate_summary
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results


@pytest.mark.parametrize("days", [1, 3])
def test_results_span_the_given_days_one_row_a_minute_from_midnight_on_1_june_2024(days: int) -> None:
    results = make_sinusoidal_sim_results(days=days)

    pd.testing.assert_index_equal(
        results.to_dataframe().index,
        pd.date_range("2024-06-01", periods=days * 1440, freq="min", tz="Europe/London"),
    )
    assert calculate_summary(results).simulation_days == days


def test_pv_meets_the_flat_demand_first_and_the_grid_meets_the_rest() -> None:
    results = make_sinusoidal_sim_results(days=1)

    assert results.demand.nunique() == 1
    pd.testing.assert_series_equal(
        results.self_consumption, np.minimum(results.generation, results.demand), check_names=False
    )
    pd.testing.assert_series_equal(
        results.grid_export, results.generation - results.self_consumption, check_names=False
    )
    pd.testing.assert_series_equal(
        results.grid_import, results.demand - results.self_consumption, check_names=False
    )
    assert (results.grid_import > 0).any()
    assert (results.grid_export > 0).any()


def test_results_have_no_battery_activity_no_heat_pump_and_no_prices() -> None:
    results = make_sinusoidal_sim_results(days=1)

    for series in (
        results.battery_charge,
        results.battery_discharge,
        results.battery_soc,
        results.import_cost,
        results.export_revenue,
        results.tariff_rate,
    ):
        assert (series == 0.0).all(), series.name
    assert results.heat_pump_load is None


@pytest.mark.parametrize(
    ("shape", "peak_kw", "flat_kw"),
    [
        pytest.param({}, 3.0, 0.5, id="by-default"),
        pytest.param({"peak_generation_kw": 4.0, "demand_kw": 0.7}, 4.0, 0.7, id="as-given"),
    ],
)
def test_generation_peaks_and_demand_is_flat_at_the_kw_given(
    shape: dict[str, float], peak_kw: float, flat_kw: float
) -> None:
    results = make_sinusoidal_sim_results(days=1, **shape)

    assert results.generation.max() == pytest.approx(peak_kw)
    assert (results.demand == flat_kw).all()
    assert results.grid_import.max() == pytest.approx(flat_kw)
    assert results.grid_export.max() == pytest.approx(peak_kw - flat_kw)


def test_grid_import_and_export_are_priced_at_the_flat_rates_given() -> None:
    results = make_sinusoidal_sim_results(
        days=1, import_rate_gbp_per_kwh=0.30, export_rate_gbp_per_kwh=0.05
    )

    amounts = results.per_minute_amounts()
    pd.testing.assert_series_equal(
        amounts["import_cost_gbp"], amounts["grid_import_kwh"] * 0.30, check_names=False
    )
    pd.testing.assert_series_equal(
        amounts["export_revenue_gbp"], amounts["grid_export_kwh"] * 0.05, check_names=False
    )
    assert (results.tariff_rate == 0.30).all()
