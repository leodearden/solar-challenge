# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each minute of one winter day on the Europe/London clock, for a test that checks a tariff or its dispatch at every minute of the local day.

2024-01-10 is a GMT day with no clock change, so its 1,440 minutes read 00:00 to 23:59 on
the wall clock a TariffConfig reads, each once.

Usage::

    from tests._minutes_of_a_winter_day import MINUTES_OF_A_WINTER_DAY

    tariff = TariffConfig.economy_7()
    cheap = [minute for minute in MINUTES_OF_A_WINTER_DAY if tariff.is_cheap_at(minute)]
    assert len(cheap) == 420
"""

import pandas as pd

MINUTES_OF_A_WINTER_DAY = pd.date_range(
    "2024-01-10", periods=1440, freq="min", tz="Europe/London"
)
