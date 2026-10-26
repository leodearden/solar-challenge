# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_steady_runs.py, the shared builder of a run whose every series is steady over the calendar days a test chooses."""

import pandas as pd

from tests._steady_runs import steady_run


def test_a_run_holds_one_row_a_minute_from_its_first_days_midnight_to_its_last_days_2359_in_europe_london() -> None:
    index = steady_run("2024-10-01", "2024-11-30").to_dataframe().index

    assert (index[0], index[-1]) == (
        pd.Timestamp("2024-10-01 00:00", tz="Europe/London"),
        pd.Timestamp("2024-11-30 23:59", tz="Europe/London"),
    )
    assert index.to_series().diff().dropna().unique().tolist() == [pd.Timedelta(minutes=1)]
    assert len(index) == 61 * 1440 + 60, "the autumn fall-back repeats an hour of minutes"


def test_a_run_across_the_autumn_fall_back_counts_its_calendar_days_not_its_elapsed_days() -> None:
    results = steady_run("2024-10-01", "2024-11-30")
    index = results.to_dataframe().index

    assert (index[-1] - index[0]).days + 1 == 62
    assert results.window.days == 61


def test_demand_heat_pump_load_import_cost_and_export_revenue_are_steady_at_the_levels_given_and_every_other_series_is_zero() -> None:
    frame = steady_run(
        "2024-06-01",
        "2024-06-02",
        demand_kw=4.0,
        heat_pump_kw=1.5,
        import_cost_gbp=0.002,
        export_revenue_gbp=0.001,
    ).to_dataframe()

    assert {column: sorted(set(frame[column])) for column in frame.columns} == {
        "generation_kw": [0.0],
        "demand_kw": [4.0],
        "self_consumption_kw": [0.0],
        "battery_charge_kw": [0.0],
        "battery_discharge_kw": [0.0],
        "battery_soc_kwh": [0.0],
        "grid_import_kw": [0.0],
        "grid_export_kw": [0.0],
        "import_cost_gbp": [0.002],
        "export_revenue_gbp": [0.001],
        "tariff_rate_per_kwh": [0.0],
        "heat_pump_load_kw": [1.5],
    }


def test_a_run_given_no_levels_has_every_series_at_zero_and_no_heat_pump() -> None:
    results = steady_run("2024-06-01", "2024-06-01")
    frame = results.to_dataframe()

    assert results.heat_pump_load is None
    assert sorted(column for column in frame.columns if (frame[column] != 0.0).any()) == []
