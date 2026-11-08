# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_balanced_sim_results.py, the shared builder of a home's individually balanced results, row by row on a given index, and of a fleet of them."""

import re

import pandas as pd
import pytest

from solar_challenge.home import SimulationResults
from tests._balanced_sim_results import make_balanced_fleet, make_balanced_sim_results
from tests._finance_builders import make_home_config

_THREE_MINUTES = pd.date_range("2024-06-21 12:00", periods=3, freq="min", tz="Europe/London")
_FOUR_MINUTES = pd.date_range("2024-06-21 12:00", periods=4, freq="min", tz="Europe/London")


def _series_the_builder_sets(results: SimulationResults) -> tuple[pd.Series, ...]:
    return (
        results.generation,
        results.demand,
        results.self_consumption,
        results.battery_charge,
        results.battery_discharge,
        results.battery_soc,
        results.grid_import,
        results.grid_export,
        results.import_cost,
        results.export_revenue,
        results.tariff_rate,
    )


@pytest.mark.parametrize(
    "index",
    [
        pytest.param(_FOUR_MINUTES, id="minute-rows"),
        pytest.param(
            pd.date_range("2024-06-21 12:00", periods=10, freq="min", tz="Europe/London").delete(5),
            id="a-dropped-middle-row",
        ),
        pytest.param(
            pd.DatetimeIndex([pd.Timestamp("2024-06-21 12:00", tz="Europe/London")]), id="one-row-without-a-freq"
        ),
    ],
)
def test_every_series_is_on_the_given_index(index: pd.DatetimeIndex) -> None:
    results = make_balanced_sim_results(index, [2.0] * len(index), [1.0] * len(index))

    for series in _series_the_builder_sets(results):
        assert series.index.equals(index), series.name
        assert series.index.freq == index.freq, series.name


def test_without_battery_series_pv_meets_demand_first_and_the_grid_the_rest() -> None:
    results = make_balanced_sim_results(_FOUR_MINUTES, [3.0, 5.0, 0.0, 1.0], [1.0, 1.0, 2.0, 1.0])

    assert results.generation.tolist() == [3.0, 5.0, 0.0, 1.0]
    assert results.demand.tolist() == [1.0, 1.0, 2.0, 1.0]
    assert results.self_consumption.tolist() == [1.0, 1.0, 0.0, 1.0]
    assert results.grid_export.tolist() == [2.0, 4.0, 0.0, 0.0]
    assert results.grid_import.tolist() == [0.0, 0.0, 2.0, 0.0]
    for series in (
        results.battery_charge,
        results.battery_discharge,
        results.battery_soc,
        results.import_cost,
        results.export_revenue,
        results.tariff_rate,
    ):
        assert (series == 0.0).all(), series.name


@pytest.mark.parametrize(
    ("generation", "demand", "battery_charge", "battery_discharge", "grid_export", "grid_import"),
    [
        pytest.param(
            [6.0] * 3, [0.0] * 3, [4.0] * 3, [0.0] * 3, [2.0] * 3, [0.0] * 3, id="pv-charges-the-battery-and-exports-the-rest"
        ),
        pytest.param([0.0] * 3, [4.0] * 3, [0.0] * 3, [4.0] * 3, [0.0] * 3, [0.0] * 3, id="the-battery-meets-the-demand"),
    ],
)
def test_battery_series_enter_each_rows_balance(
    generation: list[float],
    demand: list[float],
    battery_charge: list[float],
    battery_discharge: list[float],
    grid_export: list[float],
    grid_import: list[float],
) -> None:
    results = make_balanced_sim_results(
        _THREE_MINUTES, generation, demand, battery_charge=battery_charge, battery_discharge=battery_discharge
    )

    assert results.grid_export.tolist() == grid_export
    assert results.grid_import.tolist() == grid_import
    assert results.battery_charge.tolist() == battery_charge
    assert results.battery_discharge.tolist() == battery_discharge
    assert (results.battery_soc == 0.0).all()
    assert results.self_consumption.tolist() == [min(g, d) for g, d in zip(generation, demand, strict=True)]
    pd.testing.assert_series_equal(
        results.generation + results.grid_import + results.battery_discharge,
        results.demand + results.grid_export + results.battery_charge,
        check_names=False,
    )


@pytest.mark.parametrize("name", ["generation", "demand", "battery_charge", "battery_discharge"])
def test_a_series_of_another_length_than_the_index_is_refused_naming_it(name: str) -> None:
    series = {"generation": [1.0] * 3, "demand": [1.0] * 3, "battery_charge": [0.0] * 3, "battery_discharge": [0.0] * 3}
    series[name] = series[name][:2]

    with pytest.raises(ValueError, match=rf"\b{name}\b") as refused:
        make_balanced_sim_results(_THREE_MINUTES, **series)

    numbers = re.findall(r"\b\d+\b", str(refused.value))
    assert "2" in numbers and "3" in numbers, str(refused.value)


def test_fleet_pairs_each_homes_results_in_order_with_a_default_home() -> None:
    homes = [([3.0, 5.0, 0.0, 1.0], [1.0, 1.0, 2.0, 1.0]), ([0.0, 1.0, 4.0, 2.0], [2.0, 0.5, 1.0, 2.0])]

    fleet = make_balanced_fleet(_FOUR_MINUTES, homes)

    assert len(fleet) == 2
    for i, (generation, demand) in enumerate(homes):
        alone = make_balanced_sim_results(_FOUR_MINUTES, generation, demand)
        pd.testing.assert_series_equal(fleet[i].generation, alone.generation)
        pd.testing.assert_series_equal(fleet[i].demand, alone.demand)
        pd.testing.assert_series_equal(fleet[i].grid_import, alone.grid_import)
        pd.testing.assert_series_equal(fleet[i].grid_export, alone.grid_export)
    assert list(fleet.home_configs) == [make_home_config(), make_home_config()]
