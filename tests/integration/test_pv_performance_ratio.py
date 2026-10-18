# SPDX-License-Identifier: AGPL-3.0-or-later
"""The default PV system's annual performance ratio on Bristol's PVGIS TMY sits at MCS's 0.8.

scripts/measure_pv_performance_ratio.py measures the ratio that docs/pv-system-losses.md
defines and records; the note also sources the band. The TMY comes through get_tmy_data
from the working directory's weather cache, which serves every slow test, so a cold cache
needs network access to PVGIS.
"""

from types import ModuleType

import pytest

from solar_challenge.location import Location
from solar_challenge.weather import get_tmy_data
from tests._scripts import load_script

MCS_PERFORMANCE_RATIO_LOW = 0.76
MCS_PERFORMANCE_RATIO_HIGH = 0.84


@pytest.fixture(scope="module")
def pv_performance_ratio() -> ModuleType:
    """scripts/measure_pv_performance_ratio.py."""
    return load_script("measure_pv_performance_ratio")


@pytest.mark.slow
@pytest.mark.integration
class TestBristolPerformanceRatio:
    """The band is MCS's performance ratio of 0.8, +/- 5%."""

    def test_the_default_system_performs_at_mcs_ratio(
        self, pv_performance_ratio: ModuleType
    ) -> None:
        bristol = Location.bristol()

        site = pv_performance_ratio.measure("Bristol", bristol, get_tmy_data(bristol))

        lossless_ratio = site.lossless.performance_ratio
        ratio = site.with_losses.performance_ratio
        assert lossless_ratio > MCS_PERFORMANCE_RATIO_HIGH, (
            f"without system losses the default system's performance ratio is {lossless_ratio:.4f}, "
            f"not above MCS's {MCS_PERFORMANCE_RATIO_HIGH}, so the band no longer tests the losses"
        )
        assert MCS_PERFORMANCE_RATIO_LOW <= ratio <= MCS_PERFORMANCE_RATIO_HIGH, (
            f"the default system's annual performance ratio on Bristol's TMY is {ratio:.4f}, "
            f"outside MCS's {MCS_PERFORMANCE_RATIO_LOW}-{MCS_PERFORMANCE_RATIO_HIGH}"
        )
