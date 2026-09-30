# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/integration/_peak_rate_energy.py, the kWh readings the TOU dispatch tests assert on."""

import re
from collections.abc import Callable

import pandas as pd
import pytest

from solar_challenge.home import SimulationResults
from tests.integration._peak_rate_energy import off_peak_discharge_kwh, peak_rate_import_kwh

OFF_PEAK_RATE = 0.09
MID_RATE = 0.15
PEAK_RATE = 0.25


def _results(
    tariff_rate: list[float],
    grid_import: list[float] | None = None,
    battery_discharge: list[float] | None = None,
) -> SimulationResults:
    """One minute per tariff_rate entry; every series not given is all zeros."""
    index = pd.date_range("2024-06-21", periods=len(tariff_rate), freq="min", tz="Europe/London")

    def series(values: list[float] | None = None) -> pd.Series:
        return pd.Series(values if values is not None else [0.0] * len(index), index=index)

    return SimulationResults(
        generation=series(),
        demand=series(),
        self_consumption=series(),
        battery_charge=series(),
        battery_discharge=series(battery_discharge),
        battery_soc=series(),
        grid_import=series(grid_import),
        grid_export=series(),
        import_cost=series(),
        export_revenue=series(),
        tariff_rate=series(tariff_rate),
    )


def test_peak_rate_import_is_the_kwh_imported_in_the_highest_rate_minutes() -> None:
    results = _results(
        tariff_rate=[OFF_PEAK_RATE, OFF_PEAK_RATE, PEAK_RATE, PEAK_RATE],
        grid_import=[600.0, 600.0, 120.0, 60.0],
    )

    assert peak_rate_import_kwh(results) == pytest.approx(3.0)


def test_off_peak_discharge_is_the_kwh_discharged_outside_the_highest_rate_minutes() -> None:
    results = _results(
        tariff_rate=[OFF_PEAK_RATE, OFF_PEAK_RATE, PEAK_RATE, PEAK_RATE],
        battery_discharge=[30.0, 60.0, 900.0, 900.0],
    )

    assert off_peak_discharge_kwh(results) == pytest.approx(1.5)


@pytest.mark.parametrize("reading", [peak_rate_import_kwh, off_peak_discharge_kwh])
@pytest.mark.parametrize(
    ("rates", "rates_named"),
    [
        ([OFF_PEAK_RATE, MID_RATE, PEAK_RATE], "[0.09, 0.15, 0.25]"),
        ([PEAK_RATE, PEAK_RATE, PEAK_RATE], "[0.25]"),
    ],
)
def test_a_tariff_that_is_not_two_rate_is_rejected_naming_its_rates(
    reading: Callable[[SimulationResults], float], rates: list[float], rates_named: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(f"got rates {rates_named}")):
        reading(_results(tariff_rate=rates))
