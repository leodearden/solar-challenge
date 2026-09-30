# SPDX-License-Identifier: AGPL-3.0-or-later
"""How much energy a simulated home imported at, and discharged away from, its tariff's peak rate.

TOU-optimized dispatch is asserted on these two readings of a ``SimulationResults``,
in kWh, taken from its per-minute kW series. The peak rate is the highest rate the
tariff charged. On a two-rate tariff such as Economy 7 that is exactly what TOU
dispatch treats as expensive, so a tariff with any other number of rates is rejected.

Usage::

    from tests.integration._peak_rate_energy import off_peak_discharge_kwh, peak_rate_import_kwh

    assert off_peak_discharge_kwh(tou_results) == 0.0
    assert peak_rate_import_kwh(tou_results) <= peak_rate_import_kwh(greedy_results)
"""

from __future__ import annotations

import pandas as pd

from solar_challenge.home import SimulationResults

_MINUTES_PER_HOUR = 60


def peak_rate_import_kwh(results: SimulationResults) -> float:
    """Energy imported from the grid in the minutes billed at the tariff's highest rate."""
    return _energy_kwh(results.grid_import[_peak_rate_minutes(results)])


def off_peak_discharge_kwh(results: SimulationResults) -> float:
    """Energy the battery discharged in the minutes not billed at the tariff's highest rate."""
    return _energy_kwh(results.battery_discharge[~_peak_rate_minutes(results)])


def _peak_rate_minutes(results: SimulationResults) -> pd.Series:
    rates = results.tariff_rate
    distinct_rates = sorted(rates.unique().tolist())
    if len(distinct_rates) != 2:
        raise ValueError(f"expected a two-rate tariff such as Economy 7, got rates {distinct_rates}")
    return rates == rates.max()


def _energy_kwh(kw_per_minute: pd.Series) -> float:
    return float(kw_per_minute.sum() / _MINUTES_PER_HOUR)
