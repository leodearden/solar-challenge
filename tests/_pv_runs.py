# SPDX-License-Identifier: AGPL-3.0-or-later
"""The PV tests' runs of the PV model: the clear day they run it over, a config's AC energy over that day, and a run's result per array.

Usage::

    from tests._pv_runs import clear_day_kwh, clear_day_weather, per_array

    kwh = clear_day_kwh(PVConfig(capacity_kw=4.0))

    chain = create_model_chain(config, Location.bristol())
    chain.run_model(clear_day_weather())
    for cell_temperature in per_array(chain.results.cell_temperature):
        ...
"""

from typing import TypeVar

import pandas as pd

from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, simulate_pv_output
from tests._synthetic_weather import synthetic_june_weather

_PerArray = TypeVar("_PerArray", pd.Series, pd.DataFrame)


def clear_day_weather() -> pd.DataFrame:
    """The clear day's hourly weather: tests/_synthetic_weather.py's clear June day, on 2024-06-21."""
    return synthetic_june_weather("2024-06-21")


def clear_day_kwh(config: PVConfig) -> float:
    """The AC energy, in kWh, that *config*'s system yields at Bristol over the clear day."""
    return float(simulate_pv_output(config, Location.bristol(), clear_day_weather()).sum())


def per_array(result: _PerArray | tuple[_PerArray, ...]) -> tuple[_PerArray, ...]:
    """A run's result for each array: pvlib gives a tuple for several arrays and a bare value for one."""
    return result if isinstance(result, tuple) else (result,)
