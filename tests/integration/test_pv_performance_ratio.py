# SPDX-License-Identifier: AGPL-3.0-or-later
"""The default PV system's annual performance ratio on Bristol's PVGIS TMY sits at MCS's 0.8.

The TMY comes through get_tmy_data from the working directory's weather cache,
which serves every slow test, so a cold cache needs network access to PVGIS.
docs/pv-system-losses.md defines the ratio and sources the band.
"""

import dataclasses
import warnings

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    create_model_chain,
    simulate_pv_output,
    wired_dc_capacity_kw,
)
from solar_challenge.weather import get_tmy_data

MCS_PERFORMANCE_RATIO_LOW = 0.76
MCS_PERFORMANCE_RATIO_HIGH = 0.84


def _annual_performance_ratio(config: PVConfig, location: Location, weather: pd.DataFrame) -> float:
    """Annual AC energy over the in-plane irradiation times the wired DC capacity."""
    ac_kwh = simulate_pv_output(config, location, weather).sum()

    chain = create_model_chain(config, location)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        chain.run_model(weather)
    in_plane = chain.results.total_irrad
    first_array = in_plane[0] if isinstance(in_plane, tuple) else in_plane
    poa_kwh_per_m2 = first_array["poa_global"].sum() / 1000

    return ac_kwh / (poa_kwh_per_m2 * wired_dc_capacity_kw(config))


@pytest.mark.slow
@pytest.mark.integration
class TestBristolPerformanceRatio:
    """The band is MCS's performance ratio of 0.8, +/- 5%."""

    def test_the_default_system_performs_at_mcs_ratio(self) -> None:
        bristol = Location.bristol()
        weather = get_tmy_data(bristol)
        config = PVConfig.default_4kw()

        lossless_ratio = _annual_performance_ratio(
            dataclasses.replace(config, system_losses=0.0), bristol, weather
        )
        ratio = _annual_performance_ratio(config, bristol, weather)

        assert lossless_ratio > MCS_PERFORMANCE_RATIO_HIGH, (
            f"without system losses the default system's performance ratio is {lossless_ratio:.4f}, "
            f"not above MCS's {MCS_PERFORMANCE_RATIO_HIGH}, so the band no longer tests the losses"
        )
        assert MCS_PERFORMANCE_RATIO_LOW <= ratio <= MCS_PERFORMANCE_RATIO_HIGH, (
            f"the default system's annual performance ratio on Bristol's TMY is {ratio:.4f}, "
            f"outside MCS's {MCS_PERFORMANCE_RATIO_LOW}-{MCS_PERFORMANCE_RATIO_HIGH}"
        )
